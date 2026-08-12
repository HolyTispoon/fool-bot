"""
The command tree sync gate, and the state file it remembers itself in.

Registering global commands is heavily rate limited and setup_hook runs
on every process start, so a day of restarts used to re-upload an
identical command list dozens of times. These cover the two ways that
can go wrong: syncing when nothing changed (the waste), and not syncing
when something did (the bug that waste was hiding).
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import discord
from discord import app_commands
from discord.ext import commands

import botlog
import botstate

# foolbot is a script as well as a module: importing it starts the bot
# and configures the root logger. Neither belongs in a test process --
# the logging setup in particular would follow every other test in the
# run -- so both are stubbed out for the length of the import.
with (
    mock.patch.object(commands.Bot, "run", lambda self, *a, **k: None),
    mock.patch.object(botlog, "configure_logging"),
    mock.patch.object(botlog, "install_mirror"),
):
    import foolbot


def build_tree() -> app_commands.CommandTree:
    bot = commands.Bot(
        command_prefix="!",
        intents=discord.Intents.none(),
    )

    @bot.tree.command(name="ping", description="Say hello.")
    async def ping(interaction: discord.Interaction) -> None:
        del interaction

    return bot.tree


class BotStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.state_file = Path(self.directory.name) / "state" / "bot.json"

    def test_a_value_round_trips(self) -> None:
        self.assertIsNone(botstate.read_key("k", self.state_file))
        botstate.write_key("k", "v", self.state_file)
        self.assertEqual(botstate.read_key("k", self.state_file), "v")

    def test_other_keys_are_left_alone(self) -> None:
        botstate.write_key("first", "1", self.state_file)
        botstate.write_key("second", "2", self.state_file)

        state = json.loads(self.state_file.read_text(encoding="utf-8"))
        self.assertEqual(state, {"first": "1", "second": "2"})

    def test_a_corrupt_file_reads_as_no_record(self) -> None:
        self.state_file.parent.mkdir(parents=True)
        self.state_file.write_text("{not json", encoding="utf-8")

        self.assertIsNone(botstate.read_key("k", self.state_file))

        # And is recoverable: the next write replaces it wholesale
        # rather than failing forever.
        botstate.write_key("k", "v", self.state_file)
        self.assertEqual(botstate.read_key("k", self.state_file), "v")

    def test_a_non_string_value_reads_as_no_record(self) -> None:
        self.state_file.parent.mkdir(parents=True)
        self.state_file.write_text('{"k": 7}', encoding="utf-8")

        self.assertIsNone(botstate.read_key("k", self.state_file))

    def test_an_unwritable_folder_reads_as_no_record(self) -> None:
        # A checkout on a drive that has been unmounted. This runs on
        # the startup path, so a raise here would cost the bot rather
        # than the notice it is a note about.
        unreachable = Path("/nonexistent-mount/fool-bot/data/bot.json")

        botstate.write_key("k", "v", unreachable)

        self.assertIsNone(botstate.read_key("k", unreachable))


class CommandFingerprintTests(unittest.TestCase):
    def test_the_same_tree_fingerprints_the_same(self) -> None:
        tree = build_tree()

        self.assertEqual(
            foolbot.command_tree_fingerprint(tree),
            foolbot.command_tree_fingerprint(tree),
        )

    def test_an_edited_description_changes_the_fingerprint(self) -> None:
        # The point of hashing the payload rather than the command
        # names: this is exactly the kind of change that would
        # otherwise never reach Discord.
        tree = build_tree()
        before = foolbot.command_tree_fingerprint(tree)

        command = tree.get_commands()[0]
        command.description = "Say hello, but warmly."

        self.assertNotEqual(foolbot.command_tree_fingerprint(tree), before)

    def test_a_new_command_changes_the_fingerprint(self) -> None:
        tree = build_tree()
        before = foolbot.command_tree_fingerprint(tree)

        @tree.command(name="pong", description="Say goodbye.")
        async def pong(interaction: discord.Interaction) -> None:
            del interaction

        self.assertNotEqual(foolbot.command_tree_fingerprint(tree), before)

    def test_an_unfingerprintable_tree_is_none(self) -> None:
        # None means "cannot tell", and the caller syncs -- which is
        # what it did unconditionally before the gate existed.
        tree = build_tree()

        with mock.patch.object(
            type(tree),
            "_get_all_commands",
            side_effect=RuntimeError("discord.py moved on"),
        ):
            self.assertIsNone(foolbot.command_tree_fingerprint(tree))

    def test_a_translator_is_unfingerprintable(self) -> None:
        # A translator rewrites the payload after this point, so the
        # digest would not describe what gets uploaded.
        tree = build_tree()

        with mock.patch.object(
            type(tree),
            "translator",
            new=mock.Mock(),
        ):
            self.assertIsNone(foolbot.command_tree_fingerprint(tree))


class CommandSyncGateTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.state_file = Path(self.directory.name) / "bot_state.json"

        patched = mock.patch.object(
            botstate, "STATE_FILE", self.state_file,
        )
        patched.start()
        self.addCleanup(patched.stop)

    async def sync(self, fingerprint, forced=False, tree=None):
        """
        Run the gate against a stubbed tree, returning that stub so the
        caller can see whether it was synced. `tree` is only passed by
        the test that needs a sync to fail.
        """
        if tree is None:
            tree = mock.Mock()
            tree.sync = mock.AsyncMock(return_value=[1, 2, 3])

        bot = mock.Mock()
        bot.tree = tree

        with (
            mock.patch.object(
                foolbot, "command_tree_fingerprint", return_value=fingerprint,
            ),
            mock.patch.object(
                foolbot, "command_sync_forced", return_value=forced,
            ),
        ):
            await foolbot.GameBot.sync_commands_if_changed(bot)

        return tree

    async def test_the_first_start_syncs_and_records(self) -> None:
        tree = await self.sync("abc")

        tree.sync.assert_awaited_once()
        self.assertEqual(
            botstate.read_key(
                foolbot.COMMAND_FINGERPRINT_KEY, self.state_file,
            ),
            "abc",
        )

    async def test_an_unchanged_tree_does_not_sync(self) -> None:
        await self.sync("abc")
        tree = await self.sync("abc")

        tree.sync.assert_not_awaited()

    async def test_a_changed_tree_syncs_again(self) -> None:
        await self.sync("abc")
        tree = await self.sync("def")

        tree.sync.assert_awaited_once()
        self.assertEqual(
            botstate.read_key(
                foolbot.COMMAND_FINGERPRINT_KEY, self.state_file,
            ),
            "def",
        )

    async def test_the_override_syncs_anyway(self) -> None:
        await self.sync("abc")
        tree = await self.sync("abc", forced=True)

        tree.sync.assert_awaited_once()

    async def test_an_unfingerprintable_tree_always_syncs(self) -> None:
        first = await self.sync(None)
        second = await self.sync(None)

        first.sync.assert_awaited_once()
        second.sync.assert_awaited_once()
        # And records nothing, so it cannot skip a later real sync.
        self.assertIsNone(
            botstate.read_key(
                foolbot.COMMAND_FINGERPRINT_KEY, self.state_file,
            )
        )

    async def test_a_failed_sync_is_not_recorded(self) -> None:
        # Recording a sync that raised would skip it on the next start
        # and leave Discord holding the old commands indefinitely.
        tree = mock.Mock()
        tree.sync = mock.AsyncMock(
            side_effect=discord.HTTPException(
                mock.Mock(status=503), "nope",
            )
        )

        with self.assertRaises(discord.HTTPException):
            await self.sync("abc", tree=tree)

        self.assertIsNone(
            botstate.read_key(
                foolbot.COMMAND_FINGERPRINT_KEY, self.state_file,
            )
        )


class CommandSyncOverrideTests(unittest.TestCase):
    def test_the_override_reads_off_the_environment(self) -> None:
        for value, expected in (
            ("", False),
            ("off", False),
            ("always", True),
            ("Force", True),
            ("YES", True),
            ("1", True),
        ):
            with mock.patch.dict(
                "os.environ", {"FOOLBOT_COMMAND_SYNC": value}, clear=False,
            ):
                self.assertEqual(
                    foolbot.command_sync_forced(), expected, value,
                )


if __name__ == "__main__":
    unittest.main()
