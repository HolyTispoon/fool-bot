"""
Archiving finished games on startup.

The startup sweep exists to catch games that finished while the bot
could not move their channel. A saved game outliving its channel -- or
its whole server -- is not that: nobody can act on it, and it would
otherwise post the same error into #logs on every reconnect. See the
logging section of CLAUDE.md for what earns an ERROR.
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


class StartupArchivingTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_deleted_channel_is_not_an_error(self) -> None:
        game = build_game()
        cog = build_cog(game)
        cog.bot = SimpleNamespace(get_guild=lambda guild_id: object())
        cog.archive_game_channel = mock.AsyncMock(
            side_effect=build_http_error(
                discord.NotFound, 404, "Unknown Channel",
            ),
        )

        with self.assertLogs("cogs.d12ball_helpers", level="INFO") as logs:
            await cog.on_ready()

        self.assertEqual([record.levelname for record in logs.records], ["INFO"])
        self.assertIn("no longer exists", logs.output[0])
        self.assertIn(game.game_id, logs.output[0])

    async def test_a_server_the_bot_has_left_is_not_an_error(self) -> None:
        game = build_game()
        cog = build_cog(game)
        cog.bot = SimpleNamespace(get_guild=lambda guild_id: None)
        cog.archive_game_channel = mock.AsyncMock()

        with self.assertLogs("cogs.d12ball_helpers", level="INFO") as logs:
            await cog.on_ready()

        self.assertEqual([record.levelname for record in logs.records], ["INFO"])
        self.assertIn("not in its server", logs.output[0])
        cog.archive_game_channel.assert_not_awaited()

    async def test_a_channel_the_bot_may_not_move_is_still_an_error(
        self,
    ) -> None:
        game = build_game()
        cog = build_cog(game)
        cog.bot = SimpleNamespace(get_guild=lambda guild_id: object())
        cog.archive_game_channel = mock.AsyncMock(
            side_effect=build_http_error(
                discord.Forbidden, 403, "Missing Permissions",
            ),
        )

        with self.assertLogs("cogs.d12ball_helpers", level="INFO") as logs:
            await cog.on_ready()

        self.assertEqual([record.levelname for record in logs.records], ["ERROR"])
        self.assertIn("Could not archive", logs.output[0])

    async def test_one_dead_game_does_not_stop_the_others(self) -> None:
        dead = build_game(game_id="dead", channel_id=2)
        alive = build_game(game_id="alive", channel_id=3)
        unfinished = build_game(
            game_id="unfinished", status=GameStatus.IN_PROGRESS,
        )
        cog = build_cog(dead, alive, unfinished)
        cog.bot = SimpleNamespace(get_guild=lambda guild_id: object())
        not_found = build_http_error(discord.NotFound, 404, "Unknown Channel")

        def archive(game: D12BallGame) -> None:
            if game is dead:
                raise not_found

        cog.archive_game_channel = mock.AsyncMock(side_effect=archive)

        with self.assertLogs("cogs.d12ball_helpers", level="INFO"):
            await cog.on_ready()

        archived = [
            call.args[0] for call in cog.archive_game_channel.await_args_list
        ]
        self.assertEqual(archived, [dead, alive])


if __name__ == "__main__":
    unittest.main()
