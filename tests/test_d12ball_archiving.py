"""
Archiving finished games on startup, and pruning the ones that have
nothing left to archive.

The startup sweep exists to catch games that finished while the bot
could not move their channel. A saved game outliving its channel is not
that: nobody can act on it, and it would otherwise post the same error
into #logs on every reconnect, so it is an INFO and the record goes.
A game whose *server* is missing is only skipped -- an outage looks the
same from here. See docs/design/logging.md for what earns an
ERROR.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

import discord

from cogs.d12ball import D12Ball
from d12ball.game import D12BallGame, GameStatus, Team


def build_cog(*games: D12BallGame) -> D12Ball:
    cog = object.__new__(D12Ball)
    cog.games = {game.game_id: game for game in games}
    cog.bot = SimpleNamespace(get_guild=lambda guild_id: object())
    cog.fetch_game_channel = mock.AsyncMock()
    cog.move_channel_to_archive = mock.AsyncMock()
    return cog


def build_game(**overrides) -> D12BallGame:
    fields = dict(
        game_id="g1",
        game_number=1,
        guild_id=1,
        channel_id=2,
        message_id=None,
        player_1_id=111,
        player_2_id=222,
        player_1_name="One",
        player_2_name="Two",
        player_1_team=Team.ORANGE,
        player_2_team=Team.PURPLE,
        home_player_number=1,
        visiting_player_number=2,
        status=GameStatus.FINISHED,
    )
    fields.update(overrides)
    return D12BallGame(**fields)


def build_http_error(
    error_type: type[discord.HTTPException],
    status: int,
    message: str,
) -> discord.HTTPException:
    response = SimpleNamespace(status=status, reason=message)
    return error_type(response, message)


def build_not_found() -> discord.NotFound:
    return build_http_error(discord.NotFound, 404, "Unknown Channel")


class StartupArchivingTests(unittest.IsolatedAsyncioTestCase):
    async def run_sweep(self, cog: D12Ball) -> tuple[list, mock.Mock]:
        with mock.patch("cogs.d12ball.slash_commands.save_games") as save:
            with self.assertLogs("cogs.d12ball_helpers", level="INFO") as logs:
                await cog.on_ready()

        return logs.records, save

    async def test_a_deleted_channel_is_not_an_error(self) -> None:
        game = build_game()
        cog = build_cog(game)
        cog.fetch_game_channel.side_effect = build_not_found()

        records, _ = await self.run_sweep(cog)

        self.assertEqual([record.levelname for record in records], ["INFO"])
        self.assertIn("no longer exists", records[0].getMessage())
        self.assertIn(game.game_id, records[0].getMessage())

    async def test_a_game_whose_channel_is_gone_is_dropped(self) -> None:
        game = build_game()
        cog = build_cog(game)
        cog.fetch_game_channel.side_effect = build_not_found()

        _, save = await self.run_sweep(cog)

        self.assertEqual(cog.games, {})
        save.assert_called_once_with(cog.games)

    async def test_a_server_the_bot_has_left_is_skipped_not_dropped(
        self,
    ) -> None:
        game = build_game()
        cog = build_cog(game)
        cog.bot = SimpleNamespace(get_guild=lambda guild_id: None)

        records, save = await self.run_sweep(cog)

        self.assertEqual([record.levelname for record in records], ["INFO"])
        self.assertIn("not in its server", records[0].getMessage())
        self.assertEqual(list(cog.games), [game.game_id])
        cog.fetch_game_channel.assert_not_awaited()
        save.assert_not_called()

    async def test_a_channel_the_bot_may_not_move_is_still_an_error(
        self,
    ) -> None:
        game = build_game()
        cog = build_cog(game)
        cog.move_channel_to_archive.side_effect = build_http_error(
            discord.Forbidden, 403, "Missing Permissions",
        )

        records, save = await self.run_sweep(cog)

        self.assertEqual([record.levelname for record in records], ["ERROR"])
        self.assertIn("Could not archive", records[0].getMessage())
        self.assertEqual(list(cog.games), [game.game_id])
        save.assert_not_called()

    async def test_a_404_from_the_move_does_not_drop_the_game(self) -> None:
        # Only the channel lookup speaks for the channel's existence.
        # A 404 from the category or the move itself is a lost race, and
        # dropping the game over it would lose a game that is still
        # there.
        game = build_game()
        cog = build_cog(game)
        cog.move_channel_to_archive.side_effect = build_not_found()

        records, save = await self.run_sweep(cog)

        self.assertEqual([record.levelname for record in records], ["ERROR"])
        self.assertEqual(list(cog.games), [game.game_id])
        save.assert_not_called()

    async def test_one_dead_game_does_not_stop_the_others(self) -> None:
        dead = build_game(game_id="dead", channel_id=2)
        alive = build_game(game_id="alive", channel_id=3)
        unfinished = build_game(
            game_id="unfinished", status=GameStatus.IN_PROGRESS,
        )
        cog = build_cog(dead, alive, unfinished)
        channel = object()
        not_found = build_not_found()

        def fetch(game: D12BallGame) -> object:
            if game is dead:
                raise not_found
            return channel

        cog.fetch_game_channel.side_effect = fetch

        _, save = await self.run_sweep(cog)

        self.assertEqual(list(cog.games), ["alive", "unfinished"])
        cog.move_channel_to_archive.assert_awaited_once_with(channel)
        save.assert_called_once_with(cog.games)


class ArchiveGameChannelTests(unittest.IsolatedAsyncioTestCase):
    async def test_archiving_looks_the_channel_up_and_moves_it(self) -> None:
        game = build_game()
        cog = build_cog(game)
        channel = object()
        cog.fetch_game_channel.return_value = channel

        await cog.archive_game_channel(game)

        cog.fetch_game_channel.assert_awaited_once_with(game)
        cog.move_channel_to_archive.assert_awaited_once_with(channel)


if __name__ == "__main__":
    unittest.main()
