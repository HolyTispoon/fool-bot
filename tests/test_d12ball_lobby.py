"""
The game-creation hub and the pre-game lobby.

The hub is one locked channel with a persistent "D12 Ball" button; the
lobby is a SETUP game with `in_lobby=True` whose own channel is reused
as the game channel once Start Game is pressed. See "The game-creation
hub and the lobby" in CLAUDE.md.
"""

import asyncio
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import mock

import discord

from cogs.d12ball import D12Ball
from cogs.d12ball_helpers import build_lobby_message
from cogs.d12ball_views import LobbyView, NewGameHubView
from d12ball.game import AIOpponent, D12BallGame, GameMode, GameStatus
from gamesaves.d12ball import hub as hub_storage
from save_patches import suppressed_cog_saves, suppressed_view_saves


def build_cog() -> D12Ball:
    cog = object.__new__(D12Ball)
    cog.games = {}
    cog.hubs = {}
    cog.bot = SimpleNamespace(add_view=mock.Mock())
    return cog


def build_lobby_game(**overrides) -> D12BallGame:
    fields = dict(
        game_id="lob1",
        game_number=3,
        guild_id=1,
        channel_id=2,
        message_id=99,
        player_1_id=111,
        player_2_id=None,
        player_1_name="One",
        player_2_name=None,
        status=GameStatus.SETUP,
        in_lobby=True,
    )
    fields.update(overrides)
    return D12BallGame(**fields)


def fake_channel() -> mock.MagicMock:
    channel = mock.MagicMock(spec=discord.TextChannel)
    channel.id = 2
    channel.send = mock.AsyncMock(return_value=SimpleNamespace(id=500))
    channel.edit = mock.AsyncMock()
    channel.set_permissions = mock.AsyncMock()
    return channel


def fake_interaction(user_id: int, channel=None) -> SimpleNamespace:
    member = mock.MagicMock(spec=discord.Member)
    member.id = user_id
    member.display_name = f"user{user_id}"
    guild = mock.MagicMock(spec=discord.Guild)
    guild.id = 1
    guild.me = mock.MagicMock()
    guild.default_role = mock.MagicMock()
    return SimpleNamespace(
        user=member,
        guild=guild,
        channel=channel,
        response=SimpleNamespace(
            send_message=mock.AsyncMock(),
            edit_message=mock.AsyncMock(),
            defer=mock.AsyncMock(),
        ),
        followup=SimpleNamespace(send=mock.AsyncMock()),
    )


class HubStorageTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "d12ball_hubs.json"
            with mock.patch.object(hub_storage, "HUBS_FILE", path), \
                    mock.patch.object(
                        hub_storage, "DATA_FOLDER", Path(directory),
                    ):
                hub_storage.set_hub(42, 100, 200)
                self.assertEqual(
                    hub_storage.load_hubs(),
                    {42: {"channel_id": 100, "message_id": 200}},
                )
                self.assertEqual(
                    hub_storage.get_hub(42),
                    {"channel_id": 100, "message_id": 200},
                )

    def test_missing_and_corrupt_read_as_empty(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "d12ball_hubs.json"
            with mock.patch.object(hub_storage, "HUBS_FILE", path):
                self.assertEqual(hub_storage.load_hubs(), {})
                path.write_text("not json {")
                self.assertEqual(hub_storage.load_hubs(), {})


class OpenLobbyTests(unittest.TestCase):
    def test_open_lobby_creates_a_setup_game_in_a_lobby(self) -> None:
        cog = build_cog()
        channel = fake_channel()
        cog.create_private_game_channel = mock.AsyncMock(return_value=channel)
        interaction = fake_interaction(111)

        with suppressed_cog_saves():
            asyncio.run(cog.open_lobby(interaction))

        self.assertEqual(len(cog.games), 1)
        game = next(iter(cog.games.values()))
        self.assertTrue(game.in_lobby)
        self.assertEqual(game.status, GameStatus.SETUP)
        self.assertEqual(game.player_1_id, 111)
        self.assertIsNone(game.player_2_id)
        self.assertEqual(game.message_id, 500)
        channel.send.assert_awaited_once()
        interaction.followup.send.assert_awaited_once()


class LobbyMembershipTests(unittest.TestCase):
    def test_join_fills_player_two_and_grants_access(self) -> None:
        cog = build_cog()
        game = build_lobby_game(ai_opponent=AIOpponent.DINKY)
        cog.games[game.game_id] = game
        channel = fake_channel()
        interaction = fake_interaction(222, channel=channel)

        with suppressed_cog_saves():
            asyncio.run(cog.lobby_join(interaction, game))

        self.assertEqual(game.player_2_id, 222)
        self.assertIsNone(game.ai_opponent)
        channel.set_permissions.assert_awaited_once()
        interaction.response.edit_message.assert_awaited_once()

    def test_join_refused_for_a_test_game(self) -> None:
        cog = build_cog()
        game = build_lobby_game(test_game=True)
        cog.games[game.game_id] = game
        interaction = fake_interaction(222, channel=fake_channel())

        with suppressed_cog_saves():
            asyncio.run(cog.lobby_join(interaction, game))

        self.assertIsNone(game.player_2_id)
        interaction.response.send_message.assert_awaited_once()

    def test_join_refused_when_full(self) -> None:
        cog = build_cog()
        game = build_lobby_game(player_2_id=222, player_2_name="Two")
        cog.games[game.game_id] = game
        interaction = fake_interaction(333, channel=fake_channel())

        with suppressed_cog_saves():
            asyncio.run(cog.lobby_join(interaction, game))

        self.assertEqual(game.player_2_id, 222)
        interaction.response.send_message.assert_awaited_once()

    def test_player_two_leaving_clears_the_slot(self) -> None:
        cog = build_cog()
        game = build_lobby_game(player_2_id=222, player_2_name="Two")
        cog.games[game.game_id] = game
        channel = fake_channel()
        interaction = fake_interaction(222, channel=channel)

        with suppressed_cog_saves():
            asyncio.run(cog.lobby_leave(interaction, game))

        self.assertIsNone(game.player_2_id)
        channel.set_permissions.assert_awaited_once()

    def test_creator_leaving_promotes_the_other_player(self) -> None:
        cog = build_cog()
        game = build_lobby_game(player_2_id=222, player_2_name="Two")
        cog.games[game.game_id] = game
        interaction = fake_interaction(111, channel=fake_channel())

        with suppressed_cog_saves():
            asyncio.run(cog.lobby_leave(interaction, game))

        self.assertEqual(game.player_1_id, 222)
        self.assertIsNone(game.player_2_id)

    def test_creator_leaving_an_empty_lobby_abandons_it(self) -> None:
        cog = build_cog()
        game = build_lobby_game()
        cog.games[game.game_id] = game
        cog.abandon_and_archive_game = mock.AsyncMock()
        interaction = fake_interaction(111, channel=fake_channel())

        with suppressed_cog_saves():
            asyncio.run(cog.lobby_leave(interaction, game))

        cog.abandon_and_archive_game.assert_awaited_once()


class LobbyStartTests(unittest.TestCase):
    def _start(self, game: D12BallGame):
        cog = build_cog()
        cog.games[game.game_id] = game
        cog.post_game_setup_message = mock.AsyncMock(return_value=777)
        channel = mock.MagicMock(spec=discord.TextChannel)
        channel.edit = mock.AsyncMock()
        interaction = fake_interaction(game.player_1_id, channel=channel)
        with suppressed_cog_saves():
            asyncio.run(cog.lobby_start(interaction, game))
        return cog, channel, interaction

    def test_solo_start_falls_back_to_dinky(self) -> None:
        game = build_lobby_game()
        _, channel, _ = self._start(game)

        self.assertFalse(game.in_lobby)
        self.assertEqual(game.ai_opponent, AIOpponent.DINKY)
        self.assertEqual(game.message_id, 777)
        channel.edit.assert_awaited_once()

    def test_two_human_start_keeps_both_players(self) -> None:
        game = build_lobby_game(player_2_id=222, player_2_name="Two")
        self._start(game)

        self.assertFalse(game.in_lobby)
        self.assertEqual(game.player_2_id, 222)
        self.assertIsNone(game.ai_opponent)

    def test_test_game_start_puts_the_creator_on_both_sides(self) -> None:
        game = build_lobby_game(test_game=True)
        self._start(game)

        self.assertFalse(game.in_lobby)
        self.assertTrue(game.test_game)
        self.assertEqual(game.player_2_id, game.player_1_id)
        self.assertIsNone(game.ai_opponent)

    def test_start_refused_for_a_stranger(self) -> None:
        cog = build_cog()
        game = build_lobby_game()
        cog.games[game.game_id] = game
        cog.post_game_setup_message = mock.AsyncMock()
        channel = mock.MagicMock(spec=discord.TextChannel)
        interaction = fake_interaction(555, channel=channel)

        with suppressed_cog_saves():
            asyncio.run(cog.lobby_start(interaction, game))

        self.assertTrue(game.in_lobby)
        cog.post_game_setup_message.assert_not_awaited()


class LobbyViewTests(unittest.TestCase):
    def test_view_has_join_leave_start_and_settings(self) -> None:
        cog = build_cog()
        game = build_lobby_game()
        cog.games[game.game_id] = game
        view = LobbyView(cog, game.game_id)
        actions = {
            item.custom_id.split(":")[2]
            for item in view.children
        }
        self.assertLessEqual(
            {"join", "leave", "start", "mode", "board", "ai"}, actions,
        )

    def test_setting_change_is_gated_to_lobby_players(self) -> None:
        cog = build_cog()
        game = build_lobby_game()
        cog.games[game.game_id] = game
        view = LobbyView(cog, game.game_id)
        interaction = fake_interaction(555)

        with suppressed_view_saves():
            asyncio.run(
                view.change_setting(interaction, game, "mode", "advanced")
            )

        self.assertEqual(game.mode, GameMode.BASIC)
        interaction.response.send_message.assert_awaited_once()

    def test_test_game_toggle_flips_the_flag(self) -> None:
        cog = build_cog()
        game = build_lobby_game()
        cog.games[game.game_id] = game
        view = LobbyView(cog, game.game_id)
        interaction = fake_interaction(game.player_1_id)

        with suppressed_view_saves():
            asyncio.run(view.change_setting(interaction, game, "test", ""))
        self.assertTrue(game.test_game)

        with suppressed_view_saves():
            asyncio.run(view.change_setting(interaction, game, "test", ""))
        self.assertFalse(game.test_game)

    def test_test_game_toggle_refused_when_someone_joined(self) -> None:
        cog = build_cog()
        game = build_lobby_game(player_2_id=222, player_2_name="Two")
        cog.games[game.game_id] = game
        view = LobbyView(cog, game.game_id)
        interaction = fake_interaction(game.player_1_id)

        with suppressed_view_saves():
            asyncio.run(view.change_setting(interaction, game, "test", ""))

        self.assertFalse(game.test_game)
        interaction.response.send_message.assert_awaited_once()

    def test_advanced_mode_defaults_the_board_to_nine(self) -> None:
        cog = build_cog()
        game = build_lobby_game()
        cog.games[game.game_id] = game
        view = LobbyView(cog, game.game_id)
        interaction = fake_interaction(game.player_1_id)

        with suppressed_view_saves():
            asyncio.run(
                view.change_setting(interaction, game, "mode", "advanced")
            )

        self.assertEqual(game.mode, GameMode.ADVANCED)
        self.assertEqual(game.board_size, 9)


class RestoreTests(unittest.TestCase):
    def test_restore_rearms_lobby_and_hub_views(self) -> None:
        cog = build_cog()
        cog.games = {"lob1": build_lobby_game()}
        cog.hubs = {1: {"channel_id": 10, "message_id": 20}}

        cog.restore_saved_views()

        restored = [
            call.args[0] if call.args else call.kwargs.get("view")
            for call in cog.bot.add_view.call_args_list
        ]
        self.assertTrue(any(isinstance(v, LobbyView) for v in restored))
        self.assertTrue(any(isinstance(v, NewGameHubView) for v in restored))


class LobbyMessageTests(unittest.TestCase):
    def test_open_slot_names_the_ai_not_a_player(self) -> None:
        game = build_lobby_game()
        text = build_lobby_message(game)
        self.assertIn("open", text)
        self.assertIn("Dinky AI", text)

    def test_joined_slot_mentions_the_player(self) -> None:
        game = build_lobby_game(player_2_id=222, player_2_name="Two")
        self.assertIn("<@222>", build_lobby_message(game))


if __name__ == "__main__":
    unittest.main()
