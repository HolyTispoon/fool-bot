import asyncio
import json
import logging
import os
import subprocess
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import discord

import botlog
from botlog import deploy_notice
from botlog.channel import (
    ensure_log_channel,
    log_channel_gaps,
    log_channel_level,
    log_channel_name,
    log_target_guild,
)
from botlog.handler import DiscordLogChannelHandler, chunk_log_message


# Every FOOLBOT_ variable the package reads. Cleared for each test that
# cares, so a developer's own .env cannot change what the suite asserts.
LOG_ENVIRONMENT_KEYS = (
    "FOOLBOT_LOG_LEVEL",
    "FOOLBOT_LOG_CHANNEL_LEVEL",
    "FOOLBOT_LOG_CHANNEL_ID",
    "FOOLBOT_LOG_CHANNEL_NAME",
    "FOOLBOT_LOG_GUILD_ID",
    "FOOLBOT_DEPLOY_NOTICE",
)


@contextmanager
def environment(**values):
    """The listed variables set, and every other FOOLBOT_ one unset."""
    patched = {key: None for key in LOG_ENVIRONMENT_KEYS}
    patched.update(values)
    saved = {key: os.environ.get(key) for key in patched}

    for key, value in patched.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value

    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class FakePermissions:
    def __init__(self, view_channel=True, send_messages=True) -> None:
        self.view_channel = view_channel
        self.send_messages = send_messages


class FakeTextChannel:
    def __init__(self, name="logs", channel_id=1, permissions=None) -> None:
        self.name = name
        self.id = channel_id
        self.guild = None
        self.permissions = permissions or FakePermissions()
        self.sent: list[str] = []

    def permissions_for(self, member) -> FakePermissions:
        return self.permissions

    async def send(self, content: str):
        self.sent.append(content)
        return content


class FakeGuild:
    def __init__(self, channels=(), guild_id=10, create_error=None) -> None:
        self.id = guild_id
        self.me = object()
        self.text_channels = list(channels)
        self.create_error = create_error
        self.created: list[str] = []

        for channel in self.text_channels:
            channel.guild = self

    async def create_text_channel(self, name, reason=None):
        if self.create_error is not None:
            raise self.create_error

        self.created.append(name)
        channel = FakeTextChannel(name=name, channel_id=99)
        channel.guild = self
        self.text_channels.append(channel)

        return channel


class FakeClient:
    def __init__(self, guilds=(), channels=None) -> None:
        self.guilds = list(guilds)
        self.channels = channels or {}

    def get_guild(self, guild_id):
        for guild in self.guilds:
            if guild.id == guild_id:
                return guild

        return None

    def get_channel(self, channel_id):
        return self.channels.get(channel_id)


class FakeResponse:
    """The bare minimum discord.HTTPException reads off a response."""

    status = 403
    reason = "Forbidden"


def run_ensure(client):
    """
    ensure_log_channel with the fakes above passing the isinstance check
    the real code does on whatever FOOLBOT_LOG_CHANNEL_ID names.
    """
    with mock.patch.object(discord, "TextChannel", FakeTextChannel):
        return asyncio.run(ensure_log_channel(client))


class ChunkLogMessageTests(unittest.TestCase):
    def test_a_short_record_is_one_fenced_chunk(self) -> None:
        chunks = chunk_log_message("boom\nTraceback (most recent call last):")

        self.assertEqual(len(chunks), 1)
        self.assertTrue(chunks[0].startswith("```\n"))
        self.assertTrue(chunks[0].endswith("\n```"))
        self.assertIn("boom", chunks[0])

    def test_nothing_to_say_is_nothing_to_post(self) -> None:
        # An empty post is a 400 from Discord, and a blank one is noise.
        self.assertEqual(chunk_log_message(""), [])
        self.assertEqual(chunk_log_message("   \n  "), [])

    def test_a_long_record_splits_on_line_boundaries(self) -> None:
        text = "\n".join(f"line {number}" * 10 for number in range(50))

        chunks = chunk_log_message(text, limit=500)

        self.assertGreater(len(chunks), 1)

        for chunk in chunks:
            self.assertLessEqual(len(chunk), 500 + len("```\n\n```"))

    def test_one_very_long_line_is_hard_split(self) -> None:
        # A single line over the limit has no boundary to split on, and
        # dropping it would lose the record.
        chunks = chunk_log_message("z" * 5000, limit=1000)

        self.assertEqual(len(chunks), 5)
        self.assertEqual(
            sum(chunk.count("z") for chunk in chunks), 5000,
        )


class LogLevelTests(unittest.TestCase):
    def test_the_mirror_defaults_to_errors_only(self) -> None:
        with environment():
            self.assertEqual(log_channel_level(), logging.ERROR)

    def test_the_mirror_can_be_switched_off(self) -> None:
        for value in ("off", "none", "  ", "DISABLED"):
            with environment(FOOLBOT_LOG_CHANNEL_LEVEL=value):
                self.assertIsNone(log_channel_level(), value)

    def test_a_named_level_is_honoured(self) -> None:
        with environment(FOOLBOT_LOG_CHANNEL_LEVEL="warning"):
            self.assertEqual(log_channel_level(), logging.WARNING)

    def test_an_unknown_level_falls_back_to_errors(self) -> None:
        # Rather than silently mirroring nothing, which looks identical
        # to the feature being broken.
        with environment(FOOLBOT_LOG_CHANNEL_LEVEL="loud"):
            self.assertEqual(log_channel_level(), logging.ERROR)

    def test_the_console_defaults_to_info(self) -> None:
        with environment():
            self.assertEqual(botlog.console_level(), logging.INFO)

    def test_the_console_level_is_configurable(self) -> None:
        with environment(FOOLBOT_LOG_LEVEL="debug"):
            self.assertEqual(botlog.console_level(), logging.DEBUG)

        with environment(FOOLBOT_LOG_LEVEL="nonsense"):
            self.assertEqual(botlog.console_level(), logging.INFO)

    def test_the_channel_name_defaults_to_logs(self) -> None:
        with environment():
            self.assertEqual(log_channel_name(), "logs")

        with environment(FOOLBOT_LOG_CHANNEL_NAME="bot-errors"):
            self.assertEqual(log_channel_name(), "bot-errors")


class FloodControlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.handler = DiscordLogChannelHandler()

    def test_the_first_record_posts(self) -> None:
        self.assertEqual(self.handler._admit("boom", 0.0), ["boom"])

    def test_a_repeat_of_the_same_record_is_silent(self) -> None:
        self.handler._admit("boom", 0.0)

        self.assertEqual(self.handler._admit("boom", 0.1), [])
        self.assertEqual(self.handler._admit("boom", 0.2), [])

    def test_a_still_repeating_record_posts_a_heartbeat(self) -> None:
        # An ongoing problem that went quiet looks like a fixed one.
        self.handler._admit("boom", 0.0)
        posts = [
            self.handler._admit("boom", 0.0)
            for _ in range(DiscordLogChannelHandler.DUPLICATE_HEARTBEAT)
        ]

        self.assertEqual([post for post in posts if post], [
            ["(still repeating the previous error -- "
             f"{DiscordLogChannelHandler.DUPLICATE_HEARTBEAT} times so far)"],
        ])

    def test_a_new_record_reports_what_the_repeat_hid(self) -> None:
        self.handler._admit("boom", 0.0)
        self.handler._admit("boom", 0.0)
        self.handler._admit("boom", 0.0)

        posts = self.handler._admit("different", 0.0)

        self.assertEqual(posts, [
            "(previous message repeated 2 more time(s))",
            "different",
        ])

    def test_a_storm_of_varied_errors_is_capped(self) -> None:
        limit = DiscordLogChannelHandler.RATE_LIMIT

        for number in range(limit):
            self.assertEqual(
                self.handler._admit(f"error {number}", 0.0),
                [f"error {number}"],
            )

        self.assertEqual(self.handler._admit("one too many", 0.0), [])
        self.assertEqual(self.handler._admit("and another", 0.0), [])

    def test_the_suppressed_count_is_reported_when_the_window_rolls(
        self,
    ) -> None:
        limit = DiscordLogChannelHandler.RATE_LIMIT
        window = DiscordLogChannelHandler.RATE_WINDOW

        for number in range(limit + 3):
            self.handler._admit(f"error {number}", 0.0)

        posts = self.handler._admit("after the window", window + 1)

        self.assertEqual(len(posts), 2)
        self.assertIn("suppressed 3 log record(s)", posts[0])
        self.assertEqual(posts[1], "after the window")


class HandlerTests(unittest.TestCase):
    def make_record(self, message: str = "boom") -> logging.LogRecord:
        return logging.LogRecord(
            name="tests",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg=message,
            args=(),
            exc_info=None,
        )

    def test_a_record_before_the_channel_is_bound_is_dropped(self) -> None:
        # The console handler still has it; what must not happen is an
        # exception out of logging itself.
        handler = DiscordLogChannelHandler()

        handler.emit(self.make_record())

        self.assertFalse(handler.started)

    def test_a_full_queue_drops_rather_than_grows(self) -> None:
        async def fill() -> "asyncio.Queue[str]":
            queue: "asyncio.Queue[str]" = asyncio.Queue(maxsize=2)

            for number in range(5):
                DiscordLogChannelHandler._offer(queue, f"record {number}")

            return queue

        queue = asyncio.run(fill())

        self.assertEqual(queue.qsize(), 2)

    def test_the_default_level_is_errors_only(self) -> None:
        self.assertEqual(DiscordLogChannelHandler().level, logging.ERROR)


class LogChannelResolutionTests(unittest.TestCase):
    def test_a_channel_the_bot_can_post_in_has_no_gaps(self) -> None:
        channel = FakeTextChannel()
        channel.guild = FakeGuild([channel])

        self.assertEqual(log_channel_gaps(channel), [])

    def test_a_channel_the_bot_cannot_see_is_reported(self) -> None:
        # Send Messages alone is not enough: a channel the bot cannot
        # view rejects the post with 50001 Missing Access.
        channel = FakeTextChannel(
            permissions=FakePermissions(view_channel=False),
        )
        channel.guild = FakeGuild([channel])

        self.assertEqual(log_channel_gaps(channel), ["view_channel"])

    def test_an_uncached_guild_member_assumes_the_worst(self) -> None:
        channel = FakeTextChannel()
        channel.guild = mock.Mock(spec=[])

        self.assertEqual(
            log_channel_gaps(channel), ["view_channel", "send_messages"],
        )

    def test_an_existing_channel_is_reused(self) -> None:
        existing = FakeTextChannel(name="logs", channel_id=7)
        guild = FakeGuild([existing])

        with environment():
            channel = run_ensure(FakeClient([guild]))

        self.assertIs(channel, existing)
        self.assertEqual(guild.created, [])

    def test_a_missing_channel_is_created(self) -> None:
        guild = FakeGuild()

        with environment():
            channel = run_ensure(FakeClient([guild]))

        self.assertEqual(guild.created, ["logs"])
        self.assertEqual(channel.name, "logs")

    def test_a_namesake_it_cannot_post_in_is_not_duplicated(self) -> None:
        # The channel is right and the permissions are wrong. Creating a
        # second #logs would hide that instead of fixing it.
        blocked = FakeTextChannel(
            name="logs",
            permissions=FakePermissions(send_messages=False),
        )
        guild = FakeGuild([blocked])

        with environment():
            with self.assertLogs("botlog.channel", level="WARNING"):
                channel = run_ensure(FakeClient([guild]))

        self.assertIsNone(channel)
        self.assertEqual(guild.created, [])

    def test_the_configured_channel_id_wins(self) -> None:
        configured = FakeTextChannel(name="somewhere-else", channel_id=42)
        named = FakeTextChannel(name="logs", channel_id=7)
        guild = FakeGuild([named, configured])

        with environment(FOOLBOT_LOG_CHANNEL_ID="42"):
            channel = run_ensure(FakeClient([guild], {42: configured}))

        self.assertIs(channel, configured)

    def test_an_unpostable_configured_id_falls_back_to_the_name(
        self,
    ) -> None:
        configured = FakeTextChannel(
            name="somewhere-else",
            channel_id=42,
            permissions=FakePermissions(send_messages=False),
        )
        named = FakeTextChannel(name="logs", channel_id=7)
        guild = FakeGuild([named, configured])

        with environment(FOOLBOT_LOG_CHANNEL_ID="42"):
            with self.assertLogs("botlog.channel", level="WARNING"):
                channel = run_ensure(FakeClient([guild], {42: configured}))

        self.assertIs(channel, named)

    def test_a_bot_in_no_servers_resolves_nothing(self) -> None:
        with environment():
            with self.assertLogs("botlog.channel", level="WARNING"):
                channel = run_ensure(FakeClient())

        self.assertIsNone(channel)

    def test_a_refused_creation_is_not_an_exception(self) -> None:
        guild = FakeGuild(
            create_error=discord.Forbidden(FakeResponse(), "no"),
        )

        with environment():
            with self.assertLogs("botlog.channel", level="WARNING"):
                channel = run_ensure(FakeClient([guild]))

        self.assertIsNone(channel)

    def test_the_host_server_can_be_named(self) -> None:
        first, second = FakeGuild(guild_id=1), FakeGuild(guild_id=2)

        with environment(FOOLBOT_LOG_GUILD_ID="2"):
            self.assertIs(
                log_target_guild(FakeClient([first, second])), second,
            )

        with environment():
            self.assertIs(
                log_target_guild(FakeClient([first, second])), first,
            )


class DeployNoticeTextTests(unittest.TestCase):
    def test_a_plain_subject_is_shown_as_written(self) -> None:
        self.assertEqual(
            deploy_notice.display_subject("Implement shoot to score", ""),
            "Implement shoot to score",
        )

    def test_a_merge_shows_the_pull_request_title(self) -> None:
        # "Merge pull request #18 from HolyTispoon/claude/some-branch"
        # says nothing about what changed; the body's first line does.
        self.assertEqual(
            deploy_notice.display_subject(
                "Merge pull request #18 from HolyTispoon/claude/thing",
                "Automate maneuver effect resolution\n\nDetails here.",
            ),
            "Automate maneuver effect resolution",
        )

    def test_a_merge_with_no_body_keeps_its_subject(self) -> None:
        subject = "Merge pull request #18 from HolyTispoon/claude/thing"

        self.assertEqual(deploy_notice.display_subject(subject, "  \n "), subject)

    def test_the_notice_names_the_running_build(self) -> None:
        message = deploy_notice.deploy_message(
            deploy_notice.Build("f" * 40, "f50e0fe", "Resolve maneuvers"),
            deploy_notice.Changes(
                (deploy_notice.Commit(
                    "434cf5f", "Implement the role abilities",
                ),),
            ),
        )

        self.assertIn("`f50e0fe` Resolve maneuvers", message)
        self.assertIn("Changes in this deploy (1 commit):", message)
        self.assertIn("- `434cf5f` Implement the role abilities", message)

    def test_the_heading_names_the_pull_requests_that_landed(self) -> None:
        # Several merging between one restart and the next is the normal
        # case here, and their merge commits are not listed, so without
        # this the notice never says a pull request was involved.
        message = deploy_notice.deploy_message(
            deploy_notice.Build("f" * 40, "f50e0fe", "Head"),
            deploy_notice.Changes(
                (deploy_notice.Commit("434cf5f", "Implement roles"),),
                pull_requests=(23, 24, 25),
            ),
        )

        self.assertIn(
            "Changes in this deploy (1 commit, from pull requests "
            "#23, #24, #25):",
            message,
        )

    def test_one_pull_request_is_not_called_pull_requests(self) -> None:
        message = deploy_notice.deploy_message(
            deploy_notice.Build("f" * 40, "f50e0fe", "Head"),
            deploy_notice.Changes(
                (deploy_notice.Commit("434cf5f", "Implement roles"),),
                pull_requests=(23,),
            ),
        )

        self.assertIn("from pull request #23):", message)

    def test_a_long_change_list_is_clipped(self) -> None:
        commits = tuple(
            deploy_notice.Commit(f"sha{number}", f"change {number}")
            for number in range(deploy_notice.MAX_LISTED_COMMITS + 4)
        )

        message = deploy_notice.deploy_message(
            deploy_notice.Build("f" * 40, "f50e0fe", "Head"),
            deploy_notice.Changes(commits, previous_short="1dfe373"),
        )

        self.assertIn("...and 4 more", message)
        self.assertLessEqual(len(message), deploy_notice.MAX_MESSAGE_LENGTH)

    def test_a_clipped_change_list_says_where_the_rest_is(self) -> None:
        # A deploy this far behind is exactly when someone wants the
        # commits the cap hid, so the notice hands over the range.
        commits = tuple(
            deploy_notice.Commit(f"sha{number}", f"change {number}")
            for number in range(deploy_notice.MAX_LISTED_COMMITS + 4)
        )

        message = deploy_notice.deploy_message(
            deploy_notice.Build("f" * 40, "f50e0fe", "Head"),
            deploy_notice.Changes(commits, previous_short="1dfe373"),
        )

        self.assertIn("`git log 1dfe373..f50e0fe`", message)

    def test_the_first_build_says_so_instead_of_listing_history(
        self,
    ) -> None:
        message = deploy_notice.deploy_message(
            deploy_notice.Build("f" * 40, "f50e0fe", "Head"),
            None,
            first_run=True,
        )

        self.assertIn("First build on record", message)

    def test_an_unreadable_range_says_so(self) -> None:
        message = deploy_notice.deploy_message(
            deploy_notice.Build("f" * 40, "f50e0fe", "Head"), None,
        )

        self.assertIn("not in this checkout's history", message)

    def test_an_empty_range_says_so(self) -> None:
        message = deploy_notice.deploy_message(
            deploy_notice.Build("f" * 40, "f50e0fe", "Head"),
            deploy_notice.Changes(()),
        )

        self.assertIn("rollback or a force-push", message)

    def test_a_pull_request_merge_subject_gives_up_its_number(self) -> None:
        self.assertEqual(
            deploy_notice.pull_request_number(
                "Merge pull request #25 from HolyTispoon/additional-tweaks",
            ),
            25,
        )

    def test_other_subjects_have_no_pull_request_number(self) -> None:
        for subject in (
            "Reset ball speed to 1 on every turnover",
            "Merge remote-tracking branch 'origin/main' into claude/thing",
            "Merge pull request from HolyTispoon/no-number",
        ):
            with self.subTest(subject=subject):
                self.assertIsNone(deploy_notice.pull_request_number(subject))

    def test_backticks_in_a_subject_cannot_break_the_code_span(
        self,
    ) -> None:
        message = deploy_notice.deploy_message(
            deploy_notice.Build("f" * 40, "f50e0fe", "Fix `render.py`"),
            deploy_notice.Changes(()),
        )

        self.assertIn("Fix 'render.py'", message)


class DeployNoticeRangeTests(unittest.TestCase):
    """
    commits_since and merges_with_content against a real repository.

    Both parse git output, and the thing they have to tell apart -- a
    merge that only joined two branches from one that resolved a
    conflict -- cannot be faked convincingly with a stub. So this builds
    the history instead.
    """

    def git(self, *args: str) -> str:
        completed = subprocess.run(
            [
                "git",
                "-c", "user.name=Test",
                "-c", "user.email=test@example.com",
                "-c", "commit.gpgsign=false",
                "-C", str(self.repo),
                *args,
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        return completed.stdout.strip()

    def commit(self, name: str, text: str, message: str) -> str:
        (self.repo / name).write_text(text, encoding="utf-8")
        self.git("add", name)
        self.git("commit", "-m", message)

        return self.git("rev-parse", "HEAD")

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.repo = Path(self.directory.name)

        self.git("init", "--quiet", "--initial-branch=main")
        self.base = self.commit("a.txt", "base\n", "Base")
        self.commit("shared.txt", "base\n", "Add the shared file")
        self.base = self.git("rev-parse", "HEAD")

        # A pull request that touches its own file, so merging it back
        # is clean and its merge commit holds nothing of its own.
        self.git("checkout", "--quiet", "-b", "tidy")
        self.commit("b.txt", "tidy\n", "Tidy the board labels")
        self.git("checkout", "--quiet", "main")
        self.commit("a.txt", "main\n", "Adjust the main file")
        self.git(
            "merge", "--no-ff", "tidy",
            "-m", "Merge pull request #7 from tester/tidy",
            "-m", "Tidy up the board labels",
        )

        # A branch that edits the same line as main, so merging it needs
        # a resolution -- work that exists only in the merge commit.
        self.git("checkout", "--quiet", "-b", "rework")
        self.commit("shared.txt", "rework\n", "Rework the shared file")
        self.git("checkout", "--quiet", "main")
        self.commit("shared.txt", "main edit\n", "Edit the shared file")
        self.git("merge", "--no-ff", "rework")
        (self.repo / "shared.txt").write_text("resolved\n", encoding="utf-8")
        self.git("add", "shared.txt")
        self.git("commit", "-m", "Merge branch 'rework'")

        self.conflict_merge = self.git("rev-parse", "--short", "HEAD")

    def changes(self) -> deploy_notice.Changes:
        result = deploy_notice.commits_since(self.base, self.repo)
        self.assertIsNotNone(result)

        return result

    def test_a_conflict_resolving_merge_is_listed(self) -> None:
        # The resolution is written while merging and is in no other
        # commit, so dropping this merge drops work outright.
        listed = [commit.short for commit in self.changes().commits]

        self.assertIn(self.conflict_merge, listed)

    def test_a_clean_pull_request_merge_is_not_listed(self) -> None:
        subjects = [commit.subject for commit in self.changes().commits]

        self.assertNotIn("Tidy up the board labels", subjects)
        for subject in subjects:
            self.assertNotIn("Merge pull request", subject)

    def test_the_dropped_pull_request_is_still_named(self) -> None:
        self.assertEqual(self.changes().pull_requests, (7,))

    def test_every_ordinary_commit_is_listed(self) -> None:
        subjects = [commit.subject for commit in self.changes().commits]

        for expected in (
            "Tidy the board labels",
            "Adjust the main file",
            "Rework the shared file",
            "Edit the shared file",
        ):
            self.assertIn(expected, subjects)

    def test_only_the_conflict_resolving_merge_carries_content(self) -> None:
        carrying = deploy_notice.merges_with_content(self.base, self.repo)

        self.assertEqual(carrying, frozenset({self.conflict_merge}))

    def test_an_unreadable_range_is_none(self) -> None:
        self.assertIsNone(deploy_notice.commits_since("f" * 40, self.repo))

    def test_a_range_of_nothing_is_empty_rather_than_none(self) -> None:
        head = self.git("rev-parse", "HEAD")
        result = deploy_notice.commits_since(head, self.repo)

        self.assertIsNotNone(result)
        self.assertEqual(result.commits, ())

    def test_a_range_of_only_clean_merges_keeps_them(self) -> None:
        # Deploying the merge of a branch whose commits were already
        # announced. Dropping the merge would leave the notice claiming
        # an empty deploy, so the merge is the list.
        self.git("checkout", "--quiet", "-b", "later")
        self.commit("c.txt", "later\n", "Work on a later branch")
        branch_tip = self.git("rev-parse", "HEAD")
        self.git("checkout", "--quiet", "main")
        self.git(
            "merge", "--no-ff", "later",
            "-m", "Merge pull request #8 from tester/later",
            "-m", "Later branch work",
        )

        result = deploy_notice.commits_since(branch_tip, self.repo)

        self.assertEqual(len(result.commits), 1)
        self.assertEqual(result.commits[0].subject, "Later branch work")
        self.assertEqual(result.pull_requests, ())

    def test_a_multi_line_body_does_not_break_the_records(self) -> None:
        # %b spans lines, which is why the records carry a separator of
        # their own. A body that looks like another record must not be
        # able to invent one.
        self.git("checkout", "--quiet", "main")
        self.commit(
            "d.txt", "body\n",
            "Add a described commit\n\nFirst line.\nSecond line.\n",
        )

        subjects = [commit.subject for commit in self.changes().commits]

        self.assertIn("Add a described commit", subjects)
        self.assertNotIn("First line.", subjects)


class DeployNoticeDedupTests(unittest.TestCase):
    def build(self) -> deploy_notice.Build:
        return deploy_notice.Build("a" * 40, "aaaaaaa", "Latest work")

    def test_the_same_build_announces_nothing(self) -> None:
        # on_ready fires on every reconnect, and a restart is not a
        # deploy. This is what keeps the channel quiet.
        with environment():
            with mock.patch.object(
                deploy_notice, "head_build", return_value=self.build(),
            ):
                self.assertIsNone(deploy_notice.notice_for("a" * 40))

    def test_a_new_build_announces_once(self) -> None:
        with environment():
            with mock.patch.object(
                deploy_notice, "head_build", return_value=self.build(),
            ):
                with mock.patch.object(
                    deploy_notice,
                    "commits_since",
                    return_value=deploy_notice.Changes(()),
                ):
                    pending = deploy_notice.notice_for("b" * 40)

        self.assertIsNotNone(pending)
        sha, message = pending
        self.assertEqual(sha, "a" * 40)
        self.assertIn("aaaaaaa", message)

    def test_a_checkout_without_git_announces_nothing(self) -> None:
        with environment():
            with mock.patch.object(
                deploy_notice, "head_build", return_value=None,
            ):
                self.assertIsNone(deploy_notice.notice_for(None))

    def test_the_notice_can_be_switched_off(self) -> None:
        with environment(FOOLBOT_DEPLOY_NOTICE="off"):
            with mock.patch.object(
                deploy_notice, "head_build", return_value=self.build(),
            ):
                self.assertIsNone(deploy_notice.notice_for(None))

        with environment():
            self.assertTrue(deploy_notice.notices_enabled())


class DeployNoticeStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.state_file = Path(self.directory.name) / "state" / "bot.json"

    def test_a_machine_that_has_never_posted_reads_as_none(self) -> None:
        self.assertIsNone(deploy_notice.last_announced(self.state_file))

    def test_a_recorded_sha_survives_a_restart(self) -> None:
        deploy_notice.mark_announced("a" * 40, self.state_file)

        self.assertEqual(
            deploy_notice.last_announced(self.state_file), "a" * 40,
        )

    def test_a_corrupt_state_file_is_a_first_run(self) -> None:
        # Costing one extra notice beats refusing to start.
        self.state_file.parent.mkdir(parents=True)
        self.state_file.write_text("{not json", encoding="utf-8")

        self.assertIsNone(deploy_notice.last_announced(self.state_file))

    def test_recording_keeps_anything_else_in_the_file(self) -> None:
        self.state_file.parent.mkdir(parents=True)
        self.state_file.write_text(
            json.dumps({"something_else": 1}), encoding="utf-8",
        )

        deploy_notice.mark_announced("a" * 40, self.state_file)

        state = json.loads(self.state_file.read_text(encoding="utf-8"))
        self.assertEqual(state["something_else"], 1)
        self.assertEqual(state[deploy_notice.LAST_SHA_KEY], "a" * 40)


class ReadyClient(FakeClient):
    """A client the sink's worker can wait on."""

    async def wait_until_ready(self) -> None:
        return None


async def wait_for(condition, timeout: float = 2.0) -> None:
    """
    Give the sink's worker enough loop turns to drain its queue. Polled
    rather than slept on a fixed delay, so a slow machine does not turn
    this into a flaky test.
    """
    deadline = asyncio.get_running_loop().time() + timeout

    while not condition():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("the log record never reached the channel")

        await asyncio.sleep(0.01)


class SinkDeliveryTests(unittest.TestCase):
    def test_a_logged_error_is_posted_to_the_channel(self) -> None:
        async def scenario() -> FakeTextChannel:
            channel = FakeTextChannel(channel_id=5)
            client = ReadyClient(channels={5: channel})
            handler = DiscordLogChannelHandler()
            logger = logging.getLogger("tests.sink.delivery")
            logger.addHandler(handler)
            self.addCleanup(logger.removeHandler, handler)

            handler.start(client, 5)

            with mock.patch.object(discord, "TextChannel", FakeTextChannel):
                logger.error("the board could not be drawn")
                await wait_for(lambda: bool(channel.sent))

            return channel

        channel = asyncio.run(scenario())

        self.assertEqual(len(channel.sent), 1)
        self.assertIn("the board could not be drawn", channel.sent[0])
        self.assertIn("ERROR tests.sink.delivery", channel.sent[0])
        self.assertTrue(channel.sent[0].startswith("```"))

    def test_a_traceback_is_posted_with_the_message(self) -> None:
        async def scenario() -> FakeTextChannel:
            channel = FakeTextChannel(channel_id=5)
            client = ReadyClient(channels={5: channel})
            handler = DiscordLogChannelHandler()
            logger = logging.getLogger("tests.sink.traceback")
            logger.addHandler(handler)
            self.addCleanup(logger.removeHandler, handler)

            handler.start(client, 5)

            with mock.patch.object(discord, "TextChannel", FakeTextChannel):
                try:
                    raise ValueError("no such space")
                except ValueError as error:
                    logger.error("click failed", exc_info=error)

                await wait_for(lambda: bool(channel.sent))

            return channel

        channel = asyncio.run(scenario())

        posted = "\n".join(channel.sent)
        self.assertIn("click failed", posted)
        self.assertIn("ValueError: no such space", posted)
        self.assertIn("Traceback (most recent call last)", posted)

    def test_a_channel_that_refuses_the_post_is_not_an_exception(
        self,
    ) -> None:
        # And in particular does not log, which would feed the sink its
        # own failure and spin.
        class RefusingChannel(FakeTextChannel):
            async def send(self, content: str):
                raise discord.HTTPException(FakeResponse(), "nope")

        async def scenario() -> DiscordLogChannelHandler:
            channel = RefusingChannel(channel_id=5)
            client = ReadyClient(channels={5: channel})
            handler = DiscordLogChannelHandler()
            logger = logging.getLogger("tests.sink.refused")
            logger.addHandler(handler)
            self.addCleanup(logger.removeHandler, handler)

            handler.start(client, 5)

            with mock.patch.object(discord, "TextChannel", FakeTextChannel):
                logger.error("boom")
                await asyncio.sleep(0.05)

            return handler

        handler = asyncio.run(scenario())

        self.assertTrue(handler.started)


class StartupWiringTests(unittest.TestCase):
    def test_the_mirror_is_not_installed_when_it_is_switched_off(
        self,
    ) -> None:
        with environment(FOOLBOT_LOG_CHANNEL_LEVEL="off"):
            self.assertIsNone(botlog.install_mirror())

    def test_installing_the_mirror_lets_its_records_reach_it(self) -> None:
        # A record filtered out by the root logger never reaches any
        # handler, so a mirror below the root level would post nothing.
        root = logging.getLogger()
        saved_level = root.level
        root.setLevel(logging.CRITICAL)
        self.addCleanup(root.setLevel, saved_level)

        with environment(FOOLBOT_LOG_CHANNEL_LEVEL="ERROR"):
            handler = botlog.install_mirror()

        self.addCleanup(root.removeHandler, handler)

        self.assertIn(handler, root.handlers)
        self.assertLessEqual(root.level, logging.ERROR)

    def test_binding_is_skipped_when_there_is_no_mirror(self) -> None:
        asyncio.run(botlog.start_mirror(FakeClient(), None))

    def test_the_console_is_configured_once(self) -> None:
        # bot.run is told log_handler=None on the strength of this, so a
        # second call adding a second handler would double every line.
        root = logging.getLogger()
        saved_handlers = list(root.handlers)
        saved_level = root.level
        saved_console = botlog._console_handler
        self.addCleanup(setattr, botlog, "_console_handler", saved_console)
        self.addCleanup(root.setLevel, saved_level)
        self.addCleanup(
            lambda: root.handlers.__setitem__(slice(None), saved_handlers),
        )
        botlog._console_handler = None

        with environment(FOOLBOT_LOG_LEVEL="WARNING"):
            botlog.configure_logging()
            added = [
                handler
                for handler in root.handlers
                if handler not in saved_handlers
            ]
            botlog.configure_logging()

        self.assertEqual(len(added), 1)
        self.assertEqual(added[0].level, logging.WARNING)
        self.assertEqual(root.level, logging.WARNING)
        self.assertEqual(
            [
                handler
                for handler in root.handlers
                if handler not in saved_handlers
            ],
            added,
        )

    def test_binding_survives_a_channel_that_cannot_be_resolved(
        self,
    ) -> None:
        handler = DiscordLogChannelHandler()

        with environment():
            with self.assertLogs("botlog.channel", level="WARNING"):
                asyncio.run(botlog.start_mirror(FakeClient(), handler))

        self.assertFalse(handler.started)


if __name__ == "__main__":
    unittest.main()
