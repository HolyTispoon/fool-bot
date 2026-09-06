"""
/debug export_archived_games -- writing a finished game to disk before
deleting its channel out of a full PBD Archive category.

The export itself (gamesaves/d12ball/archive_export.write_game_export)
is covered in tests/test_d12ball_archive_export.py against a real
tmpdir; this module is about the command's plumbing -- which games it
picks, that a channel is never deleted before its export is written,
and that a failure at either step leaves the channel and the save data
alone rather than losing the game.
"""

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import discord

from discord.ext import commands

from cogs.debug import Debug
from d12ball.game import D12BallGame, GameStatus


class FakeAuthor:
    def __init__(self, name: str, author_id: int):
        self.id = author_id
        self._name = name

    def __str__(self) -> str:
        return self._name


def build_message(
    message_id: int,
    content: str = "hello",
    attachments: list | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=message_id,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        author=FakeAuthor("Coach", 1),
        content=content,
        attachments=attachments or [],
    )


def build_attachment(filename: str, data: bytes) -> SimpleNamespace:
    return SimpleNamespace(
        filename=filename, read=mock.AsyncMock(return_value=data),
    )


async def _async_iter(items):
    for item in items:
        yield item


def build_channel(
    name: str,
    messages: list | None = None,
    history_error: Exception | None = None,
    delete_error: Exception | None = None,
) -> mock.Mock:
    channel = mock.Mock(spec=discord.TextChannel)
    channel.name = name
    channel.id = abs(hash(name))
    channel.category = SimpleNamespace(name="PBD Archive")

    if history_error is not None:
        def raise_history(**kwargs):
            raise history_error
        channel.history = mock.Mock(side_effect=raise_history)
    else:
        channel.history = mock.Mock(
            side_effect=lambda **kwargs: _async_iter(messages or []),
        )

    async def delete(reason: str = "") -> None:
        del reason
        if delete_error is not None:
            raise delete_error

    channel.delete = mock.AsyncMock(side_effect=delete)
    return channel


def build_game(game_id: str, channel_id: int, game_number: int = 1) -> D12BallGame:
    return D12BallGame(
        game_id=game_id,
        game_number=game_number,
        guild_id=1,
        channel_id=channel_id,
        message_id=None,
        player_1_id=10,
        player_2_id=20,
        player_1_name="Alice",
        player_2_name="Bob",
        status=GameStatus.FINISHED,
    )


class FakeUser:
    """
    Whoever ran the command. `guild_permissions` is what the runtime
    Administrator gate reads -- Discord only carries a default
    permission on the top-level `/debug` group, so a subcommand that
    wants a narrower one has to ask for it itself.
    """

    def __init__(self, administrator: bool = True):
        self.guild_permissions = discord.Permissions(
            administrator=administrator,
        )

    def __str__(self) -> str:
        return "tester"


class ExportArchivedGamesTests(unittest.IsolatedAsyncioTestCase):
    def build_interaction(
        self,
        channels: list,
        user: object | None = None,
    ) -> SimpleNamespace:
        guild = SimpleNamespace(
            id=1,
            channels=channels,
            fetch_channels=mock.AsyncMock(return_value=channels),
        )
        return SimpleNamespace(
            guild=guild,
            user=user if user is not None else FakeUser(),
            response=SimpleNamespace(
                send_message=mock.AsyncMock(),
                defer=mock.AsyncMock(),
            ),
            followup=SimpleNamespace(send=mock.AsyncMock()),
        )

    def build_cog(self, games: dict) -> tuple[Debug, SimpleNamespace]:
        cog = Debug(mock.Mock())
        d12ball = SimpleNamespace(
            games=games,
            render_match_png=mock.AsyncMock(return_value=b"PNGDATA"),
        )
        cog.bot.get_cog = mock.Mock(return_value=d12ball)
        return cog, d12ball

    async def run_export(
        self,
        cog: Debug,
        interaction: SimpleNamespace,
        confirm: str = "confirm",
        limit: int = 5,
        export_dir: Path | None = Path("/export"),
    ):
        with (
            mock.patch(
                "cogs.debug.archive_export_dir", return_value=export_dir,
            ),
            mock.patch("cogs.debug.write_game_export") as write_export,
            mock.patch("cogs.debug.save_games") as save_games,
        ):
            await Debug.export_archived_games.callback(
                cog, interaction, confirm, limit,
            )
        return write_export, save_games

    async def test_defers_before_any_check_so_nothing_ever_races_the_ack(
        self,
    ) -> None:
        """
        Discord invalidates an interaction it waited three seconds on
        with no acknowledgement -- reported live as a 404 "Unknown
        interaction" on this exact command, on every single invocation,
        because every early refusal used to answer with a fresh
        `response.send_message` instead of deferring first. Every
        branch below must go through the followup webhook, which has
        no such clock, and `response.send_message` must never be
        called at all.
        """
        cog, _ = self.build_cog({})
        interaction = self.build_interaction([])

        await self.run_export(cog, interaction, export_dir=None)

        interaction.response.defer.assert_awaited_once()
        interaction.response.send_message.assert_not_awaited()

    async def test_a_non_administrator_is_refused_before_anything_else(
        self,
    ) -> None:
        """
        Discord fills `default_member_permissions` in only for a
        top-level command -- discord.py's own `Command.to_dict` gates
        it on `self.parent is None` -- so the
        `@app_commands.default_permissions(administrator=True)` that
        used to sit on this subcommand was sent to nobody, and every
        member of the server could run it. The group carries
        `manage_channels` for the pair of them now, and the narrower
        gate this one wants is checked here.

        It is checked ahead of `confirm`, unlike every other refusal:
        somebody who may not run this should not be walked through
        what it would have done, or handed the export path.
        """
        cog, d12ball = self.build_cog({})
        interaction = self.build_interaction(
            [], user=FakeUser(administrator=False),
        )

        write_export, save_games = await self.run_export(
            cog, interaction, confirm="not the word",
        )

        write_export.assert_not_called()
        save_games.assert_not_called()
        message = interaction.followup.send.await_args.args[0]
        self.assertIn("Administrator", message)
        self.assertNotIn("confirm", message.lower())

    async def test_the_permission_gate_rides_on_the_group(self) -> None:
        """
        The one place Discord reads it. A `default_permissions` on a
        subcommand applies the decorator, sets the attribute, and is
        left out of the payload entirely -- which is invisible from
        the Python side and was live for two releases.
        """
        payload = Debug.debug.to_dict(mock.Mock())

        self.assertEqual(
            payload["default_member_permissions"],
            discord.Permissions(manage_channels=True).value,
        )
        self.assertFalse(payload["dm_permission"])

    async def test_an_unexpected_failure_is_reported_back_by_name(
        self,
    ) -> None:
        """
        Both commands here defer first, so a crash below the defer used
        to leave the caller on an ephemeral spinner that never resolved
        while the traceback went only to the host console and #logs.

        discord.py's own handler stands down as soon as a cog defines
        `cog_app_command_error` (`Command._has_any_error_handlers`), so
        this one has to log the traceback itself or #logs loses it --
        which is asserted here alongside the reply.
        """
        cog = Debug(mock.Mock())
        interaction = self.build_interaction([])
        interaction.response.is_done = mock.Mock(return_value=True)
        interaction.command = SimpleNamespace(
            qualified_name="debug export_archived_games",
        )
        error = discord.app_commands.CommandInvokeError(
            mock.Mock(), OSError("K:\\ is not there"),
        )

        with self.assertLogs("cogs.debug", level="ERROR") as logs:
            await cog.cog_app_command_error(interaction, error)

        self.assertIn("export_archived_games", logs.output[0])
        message = interaction.followup.send.await_args.args[0]
        self.assertIn("debug export_archived_games", message)
        self.assertIn("OSError", message)
        self.assertIn("K:\\ is not there", message)

    async def test_discord_defers_to_our_error_handler(self) -> None:
        """
        The handler only ever runs because discord.py checks the cog
        for one and stands down -- if that link breaks, the reply above
        is never sent and the failure is silent again.
        """
        bot = commands.Bot(
            command_prefix="!", intents=discord.Intents.none(),
        )
        await bot.add_cog(Debug(bot))
        group = next(iter(bot.tree.get_commands()))
        command = next(
            sub for sub in group.commands
            if sub.name == "export_archived_games"
        )

        self.assertTrue(command._has_any_error_handlers())

    async def test_a_dead_interaction_names_its_own_cause(self) -> None:
        """
        The live failure: `defer` raised 10062 out of the first line of
        the command, which reads as a bug in the command and cannot be
        one -- nothing of ours has run yet. Only a lagging bot or a
        second process on the same token puts a dead token there, and
        the interaction's own age tells them apart, so the log line has
        to carry it. Nothing may run afterwards either: a refusal sent
        on a dead token is a second traceback for the same cause.
        """
        cog, d12ball = self.build_cog({})
        interaction = self.build_interaction([])
        interaction.id = discord.utils.time_snowflake(
            discord.utils.utcnow() - timedelta(seconds=9),
        )
        interaction.command = SimpleNamespace(
            qualified_name="debug export_archived_games",
        )
        interaction.response.defer = mock.AsyncMock(
            side_effect=discord.NotFound(mock.Mock(status=404), "10062"),
        )

        with self.assertLogs("cogs.debug", level="ERROR") as logs:
            write_export, save_games = await self.run_export(cog, interaction)

        write_export.assert_not_called()
        save_games.assert_not_called()
        interaction.followup.send.assert_not_awaited()
        self.assertIn("10062", logs.output[0])
        # Nine seconds: the bot was too busy, not a second process.
        self.assertIn("9.0", logs.output[0])

    async def test_a_token_spent_by_someone_else_reads_as_no_delay(
        self,
    ) -> None:
        """
        The other half of the same diagnosis. A token barely a moment
        old that Discord has already discarded was not lost to a slow
        bot -- it was answered by a second process signed in on the
        same token, which is the opposite fix.
        """
        cog, _ = self.build_cog({})
        interaction = self.build_interaction([])
        interaction.id = discord.utils.time_snowflake(discord.utils.utcnow())
        interaction.command = None
        interaction.response.defer = mock.AsyncMock(
            side_effect=discord.NotFound(mock.Mock(status=404), "10062"),
        )

        with self.assertLogs("cogs.debug", level="ERROR") as logs:
            await self.run_export(cog, interaction)

        self.assertIn("second process", logs.output[0])
        self.assertIn("unknown command", logs.output[0])

    async def test_one_run_can_clear_a_full_category(self) -> None:
        """
        50 is what fills a Discord category, and making room in a full
        one is this command's whole purpose -- so a single run has to be
        able to empty it.

        It was capped at 20, defaulting to 5, on the reading that
        deleting channels is rationed two per ten minutes. That limit is
        real but **per channel** -- `channel_id` is one of the four
        major rate-limit parameters -- so fifty different channels are
        fifty buckets, not one queue two deep.
        """
        bot = commands.Bot(
            command_prefix="!", intents=discord.Intents.none(),
        )
        await bot.add_cog(Debug(bot))
        group = next(iter(bot.tree.get_commands()))
        command = next(
            sub for sub in group.commands
            if sub.name == "export_archived_games"
        )
        option = next(
            param for param in command.to_dict(bot.tree)["options"]
            if param["name"] == "limit"
        )

        self.assertEqual(option["min_value"], 1)
        self.assertEqual(option["max_value"], 50)
        self.assertEqual(command._params["limit"].default, 50)
        self.assertIn(
            "channel_id",
            discord.http.Route("DELETE", "/channels/{channel_id}", channel_id=1)
            .major_parameters or "channel_id",
        ) if False else self.assertEqual(
            discord.http.Route(
                "DELETE", "/channels/{channel_id}", channel_id=7,
            ).major_parameters,
            "7",
        )

    async def test_the_run_is_bounded_by_the_limit_it_was_given(self) -> None:
        """
        The cap is the only thing between one run and the whole
        category, so it has to actually bound the work -- not just the
        wording of the confirmation.
        """
        channels = [
            build_channel(f"d12ball-pbd{n}-alice-vs-bob") for n in range(1, 5)
        ]
        games = {
            f"g{n}": build_game(f"g{n}", channel.id, game_number=n)
            for n, channel in enumerate(channels, start=1)
        }
        cog, _ = self.build_cog(games)
        interaction = self.build_interaction(channels)

        write_export, _ = await self.run_export(cog, interaction, limit=2)

        self.assertEqual(write_export.call_count, 2)
        # Oldest game_number first, and no further.
        exported = [call.args[0].name for call in write_export.call_args_list]
        self.assertEqual(
            exported,
            ["d12ball-pbd1-alice-vs-bob", "d12ball-pbd2-alice-vs-bob"],
        )

    async def test_refuses_when_no_export_directory_is_configured(self) -> None:
        cog, _ = self.build_cog({})
        interaction = self.build_interaction([])

        write_export, save_games = await self.run_export(
            cog, interaction, export_dir=None,
        )

        write_export.assert_not_called()
        save_games.assert_not_called()
        interaction.response.defer.assert_awaited_once()
        self.assertIn(
            "FOOLBOT_D12BALL_ARCHIVE_EXPORT_DIR",
            interaction.followup.send.await_args.args[0],
        )

    async def test_a_missing_confirmation_changes_nothing(self) -> None:
        cog, _ = self.build_cog({})
        interaction = self.build_interaction([])

        write_export, save_games = await self.run_export(cog, interaction, confirm="")

        write_export.assert_not_called()
        save_games.assert_not_called()
        interaction.response.defer.assert_awaited_once()
        interaction.followup.send.assert_awaited_once()

    async def test_confirm_is_checked_before_the_export_directory(self) -> None:
        """
        Typing the command wrong should be told exactly that, not some
        other unrelated reason it wouldn't have worked anyway.

        The refusal names the field and stops. It used to restate the
        whole operation -- how many games, out of where, to which
        directory -- which is a briefing given to somebody who has just
        been told their command did not run.
        """
        cog, _ = self.build_cog({})
        interaction = self.build_interaction([])

        write_export, save_games = await self.run_export(
            cog, interaction, confirm="", export_dir=None,
        )

        write_export.assert_not_called()
        save_games.assert_not_called()
        message = interaction.followup.send.await_args.args[0]
        self.assertIn("confirm field", message)
        self.assertIn("confirmation was missing", message)
        self.assertNotIn(
            "FOOLBOT_D12BALL_ARCHIVE_EXPORT_DIR", message,
        )
        # Not a briefing: no count, no destination, no warning about
        # what the command would have done.
        self.assertNotIn("game(s)", message)
        self.assertNotIn("delete", message)

    async def test_a_clean_export_writes_then_deletes_then_saves(self) -> None:
        channel = build_channel(
            "d12ball-pbd1-alice-vs-bob",
            messages=[
                build_message(1, "kickoff"),
                build_message(
                    2, "board", attachments=[build_attachment("d12ball-pbd1.png", b"img")],
                ),
            ],
        )
        game = build_game("g1", channel.id)
        cog, d12ball = self.build_cog({"g1": game})
        interaction = self.build_interaction([channel])

        write_export, save_games = await self.run_export(cog, interaction)

        write_export.assert_called_once()
        _, kwargs = write_export.call_args
        self.assertEqual(kwargs["board_png"], b"PNGDATA")
        self.assertEqual(len(kwargs["transcript"]), 2)
        self.assertEqual(kwargs["attachments"], [("2-d12ball-pbd1.png", b"img")])

        channel.delete.assert_awaited_once()
        self.assertNotIn("g1", d12ball.games)
        save_games.assert_called_once_with(d12ball.games)
        self.assertIn(
            "Exported 1 game(s)",
            interaction.followup.send.await_args.args[0],
        )

    async def test_only_finished_games_in_the_archive_category_are_candidates(
        self,
    ) -> None:
        in_progress_channel = build_channel("d12ball-pbd1-alice-vs-bob")
        in_progress = build_game("g1", in_progress_channel.id)
        in_progress.status = GameStatus.IN_PROGRESS

        not_archived_channel = build_channel("d12ball-pbd2-alice-vs-bob")
        not_archived_channel.category = SimpleNamespace(name="PBD Games")
        not_archived = build_game("g2", not_archived_channel.id, game_number=2)

        cog, d12ball = self.build_cog({"g1": in_progress, "g2": not_archived})
        interaction = self.build_interaction(
            [in_progress_channel, not_archived_channel],
        )

        write_export, save_games = await self.run_export(cog, interaction)

        write_export.assert_not_called()
        save_games.assert_not_called()
        self.assertIn(
            "No finished games",
            interaction.followup.send.await_args.args[0],
        )

    async def test_a_history_failure_leaves_the_channel_and_game_alone(self) -> None:
        channel = build_channel(
            "d12ball-pbd1-alice-vs-bob",
            history_error=discord.Forbidden(
                mock.Mock(status=403, reason=""), "nope",
            ),
        )
        game = build_game("g1", channel.id)
        cog, d12ball = self.build_cog({"g1": game})
        interaction = self.build_interaction([channel])

        write_export, save_games = await self.run_export(cog, interaction)

        write_export.assert_not_called()
        channel.delete.assert_not_awaited()
        self.assertIn("g1", d12ball.games)
        save_games.assert_not_called()
        self.assertIn(
            "could not read its history",
            interaction.followup.send.await_args.args[0],
        )

    async def test_a_failed_write_leaves_the_channel_and_game_alone(self) -> None:
        channel = build_channel("d12ball-pbd1-alice-vs-bob", messages=[build_message(1)])
        game = build_game("g1", channel.id)
        cog, d12ball = self.build_cog({"g1": game})
        interaction = self.build_interaction([channel])

        with (
            mock.patch(
                "cogs.debug.archive_export_dir", return_value=Path("/export"),
            ),
            mock.patch(
                "cogs.debug.write_game_export",
                side_effect=OSError("disk full"),
            ),
            mock.patch("cogs.debug.save_games") as save_games,
        ):
            await Debug.export_archived_games.callback(
                cog, interaction, "confirm", 5,
            )

        channel.delete.assert_not_awaited()
        self.assertIn("g1", d12ball.games)
        save_games.assert_not_called()
        self.assertIn(
            "could not write its export",
            interaction.followup.send.await_args.args[0],
        )

    async def test_the_export_folder_is_named_like_the_channel(self) -> None:
        channel = build_channel("d12ball-pbd7-cup-final", messages=[])
        game = build_game("g1", channel.id, game_number=7)
        game.game_name = "Cup Final"
        cog, d12ball = self.build_cog({"g1": game})
        interaction = self.build_interaction([channel])

        write_export, _ = await self.run_export(cog, interaction)

        args, kwargs = write_export.call_args
        self.assertEqual(args[0], Path("/export/d12ball-pbd7-cup-final"))


if __name__ == "__main__":
    unittest.main()
