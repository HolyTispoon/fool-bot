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
from cogs.d12ball_helpers import (
    HUB_ROLE_CUSTOM_ID_PREFIX,
    HUB_ROLES,
    build_hub_roles_message,
    build_lobby_message,
)
from cogs.d12ball_views import (
    HubRolesView,
    LobbyNameModal,
    LobbyView,
    NewGameHubView,
)
from d12ball.game import AIOpponent, D12BallGame, GameMode, GameStatus
from gamesaves.d12ball import hub as hub_storage
from save_patches import suppressed_cog_saves, suppressed_view_saves


def build_cog() -> D12Ball:
    cog = object.__new__(D12Ball)
    cog.games = {}
    cog.hubs = {}
    cog.d12_emoji = None
    cog.d12_button_emoji = None
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
            send_modal=mock.AsyncMock(),
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
                entry = hub_storage.set_hub(42, 100, 200, 300)
                self.assertEqual(
                    entry,
                    {
                        "channel_id": 100,
                        "message_id": 200,
                        "roles_message_id": 300,
                    },
                )
                self.assertEqual(hub_storage.get_hub(42), entry)

    def test_an_entry_without_a_roles_message_still_loads(self) -> None:
        # A hub file written before the roles message existed.
        with TemporaryDirectory() as directory:
            path = Path(directory) / "d12ball_hubs.json"
            path.write_text(
                json.dumps({"42": {"channel_id": 100, "message_id": 200}})
            )
            with mock.patch.object(hub_storage, "HUBS_FILE", path):
                self.assertEqual(
                    hub_storage.load_hubs(),
                    {42: {"channel_id": 100, "message_id": 200}},
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
    def test_join_fills_player_two(self) -> None:
        cog = build_cog()
        game = build_lobby_game(ai_opponent=AIOpponent.DINKY)
        cog.games[game.game_id] = game
        interaction = fake_interaction(222, channel=fake_channel())

        with suppressed_cog_saves():
            asyncio.run(cog.lobby_join(interaction, game))

        self.assertEqual(game.player_2_id, 222)
        self.assertIsNone(game.ai_opponent)
        interaction.response.edit_message.assert_awaited_once()

    def test_join_drops_the_user_from_observers(self) -> None:
        cog = build_cog()
        game = build_lobby_game(observer_ids=[222])
        cog.games[game.game_id] = game
        interaction = fake_interaction(222, channel=fake_channel())

        with suppressed_cog_saves():
            asyncio.run(cog.lobby_join(interaction, game))

        self.assertEqual(game.player_2_id, 222)
        self.assertEqual(game.observer_ids, [])

    def test_join_refused_for_a_test_game(self) -> None:
        cog = build_cog()
        game = build_lobby_game(test_game=True)
        cog.games[game.game_id] = game
        interaction = fake_interaction(222, channel=fake_channel())

        with suppressed_cog_saves():
            asyncio.run(cog.lobby_join(interaction, game))

        self.assertIsNone(game.player_2_id)
        interaction.response.send_message.assert_awaited_once()

    def test_join_refused_for_a_tutorial(self) -> None:
        cog = build_cog()
        game = build_lobby_game(tutorial=True)
        cog.games[game.game_id] = game
        interaction = fake_interaction(222, channel=fake_channel())

        with suppressed_cog_saves():
            asyncio.run(cog.lobby_join(interaction, game))

        self.assertIsNone(game.player_2_id)

    def test_join_refused_when_full(self) -> None:
        cog = build_cog()
        game = build_lobby_game(player_2_id=222, player_2_name="Two")
        cog.games[game.game_id] = game
        interaction = fake_interaction(333, channel=fake_channel())

        with suppressed_cog_saves():
            asyncio.run(cog.lobby_join(interaction, game))

        self.assertEqual(game.player_2_id, 222)
        interaction.response.send_message.assert_awaited_once()

    def test_observe_adds_to_the_list_and_leave_removes(self) -> None:
        cog = build_cog()
        game = build_lobby_game()
        cog.games[game.game_id] = game
        interaction = fake_interaction(444, channel=fake_channel())

        with suppressed_cog_saves():
            asyncio.run(cog.lobby_observe(interaction, game))
        self.assertEqual(game.observer_ids, [444])

        with suppressed_cog_saves():
            asyncio.run(cog.lobby_leave(interaction, game))
        self.assertEqual(game.observer_ids, [])

    def test_a_player_cannot_observe(self) -> None:
        cog = build_cog()
        game = build_lobby_game()
        cog.games[game.game_id] = game
        interaction = fake_interaction(111, channel=fake_channel())

        with suppressed_cog_saves():
            asyncio.run(cog.lobby_observe(interaction, game))

        self.assertEqual(game.observer_ids, [])
        interaction.response.send_message.assert_awaited_once()

    def test_player_two_leaving_clears_the_slot(self) -> None:
        cog = build_cog()
        game = build_lobby_game(player_2_id=222, player_2_name="Two")
        cog.games[game.game_id] = game
        interaction = fake_interaction(222, channel=fake_channel())

        with suppressed_cog_saves():
            asyncio.run(cog.lobby_leave(interaction, game))

        self.assertIsNone(game.player_2_id)

    def test_creator_leaving_promotes_the_other_player(self) -> None:
        cog = build_cog()
        game = build_lobby_game(player_2_id=222, player_2_name="Two")
        cog.games[game.game_id] = game
        interaction = fake_interaction(111, channel=fake_channel())

        with suppressed_cog_saves():
            asyncio.run(cog.lobby_leave(interaction, game))

        self.assertEqual(game.player_1_id, 222)
        self.assertIsNone(game.player_2_id)

    def test_creator_leaving_an_empty_lobby_keeps_it_open(self) -> None:
        cog = build_cog()
        game = build_lobby_game()
        cog.games[game.game_id] = game
        cog.abandon_and_archive_game = mock.AsyncMock()
        interaction = fake_interaction(111, channel=fake_channel())

        with suppressed_cog_saves():
            asyncio.run(cog.lobby_leave(interaction, game))

        cog.abandon_and_archive_game.assert_not_awaited()
        self.assertIn("lob1", cog.games)
        self.assertTrue(game.in_lobby)
        interaction.response.send_message.assert_awaited_once()


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
    def test_view_has_every_lobby_action(self) -> None:
        cog = build_cog()
        game = build_lobby_game()
        cog.games[game.game_id] = game
        view = LobbyView(cog, game.game_id)
        actions = {
            item.custom_id.split(":")[2]
            for item in view.children
            if getattr(item, "custom_id", None)
        }
        self.assertLessEqual(
            {
                "join", "observe", "leave", "start", "name",
                "test", "tutorial", "mode", "board", "ai",
            },
            actions,
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

    def test_tutorial_toggle_pins_basic_seven_and_dinky(self) -> None:
        cog = build_cog()
        game = build_lobby_game(
            mode=GameMode.ADVANCED, board_size=9, test_game=True,
        )
        cog.games[game.game_id] = game
        view = LobbyView(cog, game.game_id)
        interaction = fake_interaction(game.player_1_id)

        with suppressed_view_saves():
            asyncio.run(
                view.change_setting(interaction, game, "tutorial", "")
            )

        self.assertTrue(game.tutorial)
        self.assertFalse(game.test_game)
        self.assertEqual(game.mode, GameMode.BASIC)
        self.assertEqual(game.board_size, 7)
        self.assertEqual(game.ai_opponent, AIOpponent.DINKY)

    def test_mode_change_refused_during_tutorial(self) -> None:
        cog = build_cog()
        game = build_lobby_game(tutorial=True, ai_opponent=AIOpponent.DINKY)
        cog.games[game.game_id] = game
        view = LobbyView(cog, game.game_id)
        interaction = fake_interaction(game.player_1_id)

        with suppressed_view_saves():
            asyncio.run(
                view.change_setting(interaction, game, "mode", "advanced")
            )

        self.assertEqual(game.mode, GameMode.BASIC)
        interaction.response.send_message.assert_awaited_once()

    def test_name_button_opens_the_modal(self) -> None:
        cog = build_cog()
        game = build_lobby_game()
        cog.games[game.game_id] = game
        view = LobbyView(cog, game.game_id)
        interaction = fake_interaction(game.player_1_id)

        asyncio.run(view.dispatch(interaction, "name"))

        interaction.response.send_modal.assert_awaited_once()
        self.assertIsInstance(
            interaction.response.send_modal.await_args.args[0], LobbyNameModal,
        )

    def test_name_modal_sets_the_game_name(self) -> None:
        cog = build_cog()
        game = build_lobby_game()
        cog.games[game.game_id] = game
        modal = LobbyNameModal(cog, game.game_id)
        modal.game_name._value = "The Cup Final"
        interaction = fake_interaction(game.player_1_id)

        with suppressed_view_saves():
            asyncio.run(modal.on_submit(interaction))

        self.assertEqual(game.game_name, "The Cup Final")

    def test_name_modal_gated_to_players(self) -> None:
        cog = build_cog()
        game = build_lobby_game()
        cog.games[game.game_id] = game
        modal = LobbyNameModal(cog, game.game_id)
        modal.game_name._value = "Nope"
        interaction = fake_interaction(555)

        with suppressed_view_saves():
            asyncio.run(modal.on_submit(interaction))

        self.assertIsNone(game.game_name)
        interaction.response.send_message.assert_awaited_once()


def fake_role(role_id: int, name: str) -> mock.MagicMock:
    role = mock.MagicMock(spec=discord.Role)
    role.id = role_id
    role.name = name
    return role


def role_interaction(
    guild_roles: list, member_roles: list,
) -> SimpleNamespace:
    """
    A click on the roles message: a member carrying `member_roles` in a
    guild whose roles are `guild_roles`.
    """
    interaction = fake_interaction(111)
    interaction.guild.roles = guild_roles
    member = interaction.user
    member.get_role = lambda role_id: next(
        (role for role in member_roles if role.id == role_id), None,
    )
    member.add_roles = mock.AsyncMock()
    member.remove_roles = mock.AsyncMock()
    return interaction


class HubRolesTests(unittest.TestCase):
    def test_the_view_carries_one_button_per_role(self) -> None:
        view = HubRolesView(build_cog())
        self.assertEqual(len(view.children), len(HUB_ROLES))
        for button, hub_role in zip(view.children, HUB_ROLES):
            self.assertEqual(
                button.custom_id,
                f"{HUB_ROLE_CUSTOM_ID_PREFIX}{hub_role.key}",
            )
            self.assertEqual(button.label, hub_role.label)
            self.assertEqual(button.style, discord.ButtonStyle.success)

    def test_a_d12_role_button_carries_the_emoji(self) -> None:
        cog = build_cog()
        cog.d12_emoji = "<:d12dice:123456789012345678>"
        cog.d12_button_emoji = "<:d12dicecream:876543210987654321>"
        for button, hub_role in zip(HubRolesView(cog).children, HUB_ROLES):
            if hub_role.d12_emoji:
                self.assertEqual(button.emoji.name, "d12dicecream")
            else:
                self.assertIsNone(button.emoji)
        self.assertTrue(HUB_ROLES[0].d12_emoji)

    def test_the_playtester_role_is_on_offer(self) -> None:
        self.assertIn("playtester", [role.key for role in HUB_ROLES])
        text = build_hub_roles_message()
        for hub_role in HUB_ROLES:
            self.assertIn(hub_role.role_name, text)
            self.assertIn(hub_role.description, text)

    def test_a_click_adds_the_role_a_member_lacks(self) -> None:
        hub_role = HUB_ROLES[0]
        role = fake_role(7, hub_role.role_name.upper())  # case-insensitive
        interaction = role_interaction([role], [])

        asyncio.run(build_cog().toggle_hub_role(interaction, hub_role.key))

        interaction.user.add_roles.assert_awaited_once()
        self.assertIs(interaction.user.add_roles.await_args.args[0], role)
        interaction.user.remove_roles.assert_not_awaited()
        self.assertTrue(
            interaction.response.send_message.await_args.kwargs["ephemeral"]
        )

    def test_a_click_removes_the_role_a_member_has(self) -> None:
        hub_role = HUB_ROLES[0]
        role = fake_role(7, hub_role.role_name)
        interaction = role_interaction([role], [role])

        asyncio.run(build_cog().toggle_hub_role(interaction, hub_role.key))

        interaction.user.remove_roles.assert_awaited_once()
        interaction.user.add_roles.assert_not_awaited()

    def test_a_missing_role_is_reported_not_created(self) -> None:
        hub_role = HUB_ROLES[0]
        interaction = role_interaction([fake_role(8, "Something else")], [])

        asyncio.run(build_cog().toggle_hub_role(interaction, hub_role.key))

        interaction.user.add_roles.assert_not_awaited()
        interaction.guild.create_role.assert_not_called()
        reply = interaction.response.send_message.await_args.args[0]
        self.assertIn(hub_role.role_name, reply)

    def test_a_forbidden_change_is_explained(self) -> None:
        hub_role = HUB_ROLES[0]
        role = fake_role(7, hub_role.role_name)
        interaction = role_interaction([role], [])
        interaction.user.add_roles.side_effect = discord.Forbidden(
            mock.MagicMock(status=403), "no",
        )

        asyncio.run(build_cog().toggle_hub_role(interaction, hub_role.key))

        reply = interaction.response.send_message.await_args.args[0]
        self.assertIn("Manage Roles", reply)

    def test_an_unknown_key_is_refused(self) -> None:
        interaction = role_interaction([], [])
        asyncio.run(build_cog().toggle_hub_role(interaction, "retired"))
        interaction.user.add_roles.assert_not_awaited()
        interaction.response.send_message.assert_awaited_once()


class SetupHubTests(unittest.TestCase):
    def build_cog_for_setup(self) -> D12Ball:
        cog = build_cog()
        cog.bot = SimpleNamespace(add_view=mock.Mock(), emojis=[])
        return cog

    def setup_interaction(self, channel) -> SimpleNamespace:
        interaction = fake_interaction(111, channel)
        interaction.user.guild_permissions = SimpleNamespace(
            manage_channels=True,
        )
        interaction.guild.roles = [fake_role(7, HUB_ROLES[0].role_name)]
        return interaction

    def test_setup_posts_both_messages_and_records_both(self) -> None:
        cog = self.build_cog_for_setup()
        channel = fake_channel()
        sent_ids = iter([500, 501])
        channel.send = mock.AsyncMock(
            side_effect=lambda *a, **k: SimpleNamespace(id=next(sent_ids)),
        )
        interaction = self.setup_interaction(channel)

        with mock.patch(
            "cogs.d12ball.slash_commands.load_d12_emoji",
            mock.AsyncMock(return_value=None),
        ), mock.patch(
            "cogs.d12ball.slash_commands.load_d12_button_emoji",
            mock.AsyncMock(return_value=None),
        ), mock.patch(
            "cogs.d12ball.slash_commands.get_hub", return_value=None,
        ), mock.patch(
            "cogs.d12ball.slash_commands.set_hub",
            side_effect=lambda g, c, m, r=None: {
                "channel_id": c, "message_id": m, "roles_message_id": r,
            },
        ) as set_hub:
            asyncio.run(cog.setup_hub.callback(cog, interaction))

        self.assertEqual(channel.send.await_count, 2)
        views = [call.kwargs["view"] for call in channel.send.await_args_list]
        self.assertIsInstance(views[0], NewGameHubView)
        self.assertIsInstance(views[1], HubRolesView)
        set_hub.assert_called_once_with(1, 2, 500, 501)
        self.assertEqual(cog.hubs[1]["roles_message_id"], 501)
        report = interaction.followup.send.await_args.args[0]
        self.assertNotIn("no role named", report)

    def test_setup_names_a_role_the_server_is_missing(self) -> None:
        cog = self.build_cog_for_setup()
        channel = fake_channel()
        interaction = self.setup_interaction(channel)
        interaction.guild.roles = []

        with mock.patch(
            "cogs.d12ball.slash_commands.load_d12_emoji",
            mock.AsyncMock(return_value=None),
        ), mock.patch(
            "cogs.d12ball.slash_commands.load_d12_button_emoji",
            mock.AsyncMock(return_value=None),
        ), mock.patch(
            "cogs.d12ball.slash_commands.get_hub", return_value=None,
        ), mock.patch(
            "cogs.d12ball.slash_commands.set_hub",
            return_value={"channel_id": 2, "message_id": 500},
        ):
            asyncio.run(cog.setup_hub.callback(cog, interaction))

        report = interaction.followup.send.await_args.args[0]
        self.assertIn(HUB_ROLES[0].role_name, report)

    def test_setup_edits_a_recorded_message_and_sends_the_other(self) -> None:
        # A hub registered before the roles message existed: the games
        # message is edited in place, the roles message sent under it.
        cog = self.build_cog_for_setup()
        channel = fake_channel()
        existing = SimpleNamespace(id=400, edit=mock.AsyncMock())
        channel.fetch_message = mock.AsyncMock(return_value=existing)
        interaction = self.setup_interaction(channel)

        with mock.patch(
            "cogs.d12ball.slash_commands.load_d12_emoji",
            mock.AsyncMock(return_value=None),
        ), mock.patch(
            "cogs.d12ball.slash_commands.load_d12_button_emoji",
            mock.AsyncMock(return_value=None),
        ), mock.patch(
            "cogs.d12ball.slash_commands.get_hub",
            return_value={"channel_id": 2, "message_id": 400},
        ), mock.patch(
            "cogs.d12ball.slash_commands.set_hub",
            return_value={},
        ) as set_hub:
            asyncio.run(cog.setup_hub.callback(cog, interaction))

        existing.edit.assert_awaited_once()
        self.assertIsInstance(
            existing.edit.await_args.kwargs["view"], NewGameHubView,
        )
        channel.send.assert_awaited_once()
        self.assertIsInstance(
            channel.send.await_args.kwargs["view"], HubRolesView,
        )
        set_hub.assert_called_once_with(1, 2, 400, 500)


class RestoreTests(unittest.TestCase):
    def test_restore_rearms_lobby_and_hub_views(self) -> None:
        cog = build_cog()
        cog.games = {"lob1": build_lobby_game()}
        cog.hubs = {
            1: {"channel_id": 10, "message_id": 20, "roles_message_id": 21},
        }

        cog.restore_saved_views()

        restored = {
            type(call.args[0] if call.args else call.kwargs.get("view")):
            call.kwargs.get("message_id")
            for call in cog.bot.add_view.call_args_list
        }
        self.assertIn(LobbyView, restored)
        self.assertEqual(restored[NewGameHubView], 20)
        self.assertEqual(restored[HubRolesView], 21)

    def test_a_hub_without_a_roles_message_rearms_the_games_button(self) -> None:
        cog = build_cog()
        cog.hubs = {1: {"channel_id": 10, "message_id": 20}}

        cog.restore_saved_views()

        restored = [
            type(call.args[0] if call.args else call.kwargs.get("view"))
            for call in cog.bot.add_view.call_args_list
        ]
        self.assertIn(NewGameHubView, restored)
        self.assertNotIn(HubRolesView, restored)


class LobbyMessageTests(unittest.TestCase):
    def test_open_slot_names_the_ai_not_a_player(self) -> None:
        game = build_lobby_game()
        text = build_lobby_message(game)
        self.assertIn("open", text)
        self.assertIn("Dinky AI", text)

    def test_joined_slot_mentions_the_player(self) -> None:
        game = build_lobby_game(player_2_id=222, player_2_name="Two")
        self.assertIn("<@222>", build_lobby_message(game))

    def test_d12_emoji_rides_the_heading_and_the_hub(self) -> None:
        from cogs.d12ball_helpers import build_hub_message

        emoji = "<:d12dice:123456789012345678>"
        self.assertIn(emoji, build_hub_message(emoji))
        self.assertIn(emoji, build_lobby_message(build_lobby_game(), emoji))
        # And degrades cleanly to nothing.
        self.assertNotIn("None", build_hub_message(None))
        self.assertNotIn("None", build_lobby_message(build_lobby_game(), None))

    def test_hub_button_carries_the_emoji(self) -> None:
        cog = build_cog()
        cog.d12_emoji = "<:d12dice:123456789012345678>"
        button = NewGameHubView(cog).children[0]
        self.assertEqual(button.emoji.name, "d12dice")
        self.assertEqual(button.style, discord.ButtonStyle.success)

    def test_hub_button_prefers_the_cream_emoji(self) -> None:
        cog = build_cog()
        cog.d12_emoji = "<:d12dice:123456789012345678>"
        cog.d12_button_emoji = "<:d12dicecream:876543210987654321>"
        button = NewGameHubView(cog).children[0]
        self.assertEqual(button.emoji.name, "d12dicecream")


if __name__ == "__main__":
    unittest.main()
