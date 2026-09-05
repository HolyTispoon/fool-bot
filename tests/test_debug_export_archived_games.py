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
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import discord

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


class ExportArchivedGamesTests(unittest.IsolatedAsyncioTestCase):
    def build_interaction(self, channels: list) -> SimpleNamespace:
        guild = SimpleNamespace(
            id=1,
            channels=channels,
            fetch_channels=mock.AsyncMock(return_value=channels),
        )
        return SimpleNamespace(
            guild=guild,
            user="tester",
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

    async def test_refuses_when_no_export_directory_is_configured(self) -> None:
        cog, _ = self.build_cog({})
        interaction = self.build_interaction([])

        write_export, save_games = await self.run_export(
            cog, interaction, export_dir=None,
        )

        write_export.assert_not_called()
        save_games.assert_not_called()
        self.assertIn(
            "FOOLBOT_D12BALL_ARCHIVE_EXPORT_DIR",
            interaction.response.send_message.await_args.args[0],
        )

    async def test_a_missing_confirmation_changes_nothing(self) -> None:
        cog, _ = self.build_cog({})
        interaction = self.build_interaction([])

        write_export, save_games = await self.run_export(cog, interaction, confirm="")

        write_export.assert_not_called()
        save_games.assert_not_called()
        interaction.response.send_message.assert_awaited_once()

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
