"""
Picking which halves of advanced mode a game plays.

Advanced mode is one switch over two modules -- the advanced maneuvers
and the species abilities -- and the game record has carried an opt-out
for each since they landed (see "Species abilities in the bot"). What
is tested here is the *offer*: the two toggles the setup settings block
and the lobby put beside the mode buttons, the rule that an advanced
game keeps at least one of them, and the wording that reads off them
rather than off the mode alone.
"""

import asyncio
import unittest
from types import SimpleNamespace
from unittest import mock

from cogs.d12ball_helpers import (
    ADVANCED_MODULES,
    advanced_module_label,
    build_lobby_message,
    build_setup_message,
    describe_game_mode,
    toggle_advanced_module,
)
from cogs.d12ball_views import CoinFlipView, LobbyView
from d12ball.components import load_player_catalog
from d12ball.game import D12BallGame, GameMode, GameStatus, Team
from save_patches import suppressed_view_saves


def build_game(**overrides) -> D12BallGame:
    fields = dict(
        game_id="modules-game",
        game_number=1,
        guild_id=1,
        channel_id=2,
        message_id=None,
        player_1_id=111,
        player_2_id=222,
        player_1_name="Player One",
        player_2_name="Player Two",
        player_1_team=Team.PURPLE,
        player_2_team=Team.TEAL,
        mode=GameMode.ADVANCED,
        board_size=9,
    )
    fields.update(overrides)
    return D12BallGame(**fields)


def build_lobby(**overrides) -> D12BallGame:
    return build_game(
        game_id="modules-lobby",
        player_2_id=None,
        player_2_name=None,
        player_1_team=None,
        player_2_team=None,
        status=GameStatus.SETUP,
        in_lobby=True,
        **overrides,
    )


class FakeCog:
    def __init__(self, game) -> None:
        self.games = {game.game_id: game}
        self.coin_emojis = {}
        self.d12_emoji = None
        self.d12_button_emoji = None
        self.player_catalog = load_player_catalog()


def build_interaction(user_id: int) -> SimpleNamespace:
    return SimpleNamespace(
        user=SimpleNamespace(id=user_id),
        response=SimpleNamespace(
            edit_message=mock.AsyncMock(),
            send_message=mock.AsyncMock(),
        ),
    )


def module_custom_ids(view) -> set[str]:
    return {
        item.custom_id
        for item in view.children
        if getattr(item, "custom_id", None) and ":module:" in item.custom_id
    }


class ToggleRuleTests(unittest.TestCase):
    """
    `toggle_advanced_module` is the one implementation both screens
    toggle through, so the rule about the last module still on cannot
    hold on one of them and not the other.
    """

    def test_a_module_toggles_off_and_back_on(self) -> None:
        game = build_game()

        self.assertIsNone(toggle_advanced_module(game, "species"))
        self.assertFalse(game.species_abilities)
        self.assertTrue(game.advanced_maneuvers)

        self.assertIsNone(toggle_advanced_module(game, "species"))
        self.assertTrue(game.species_abilities)

    def test_the_last_module_on_may_not_be_turned_off(self) -> None:
        game = build_game(advanced_maneuvers=False)

        refusal = toggle_advanced_module(game, "species")

        self.assertIsNotNone(refusal)
        self.assertIn("Basic", refusal)
        self.assertTrue(game.species_abilities)

    def test_every_module_names_a_field_on_the_game_record(self) -> None:
        # The table is what both screens build their buttons out of, so
        # a module named here and not on the record is a button that
        # raises on the click rather than one that does nothing.
        for field, _ in ADVANCED_MODULES.values():
            self.assertIsInstance(getattr(build_game(), field), bool)

    def test_the_label_says_which_way_the_module_is_set(self) -> None:
        game = build_game(species_abilities=False)

        self.assertEqual(
            advanced_module_label(game, "maneuvers"), "Maneuvers: on",
        )
        self.assertEqual(
            advanced_module_label(game, "species"), "Species: off",
        )


class ModeWordingTests(unittest.TestCase):
    def test_a_basic_game_is_described_by_its_cards(self) -> None:
        self.assertEqual(
            describe_game_mode(build_game(mode=GameMode.BASIC)),
            "three maneuvers a side",
        )

    def test_an_advanced_game_is_described_by_the_modules_it_plays(
        self,
    ) -> None:
        self.assertEqual(
            describe_game_mode(build_game()),
            "six maneuvers a side, species abilities",
        )
        self.assertEqual(
            describe_game_mode(build_game(advanced_maneuvers=False)),
            "species abilities",
        )
        self.assertEqual(
            describe_game_mode(build_game(species_abilities=False)),
            "six maneuvers a side",
        )

    def test_both_setup_screens_say_what_the_game_is_playing(self) -> None:
        game = build_game(advanced_maneuvers=False)

        self.assertIn("species abilities", build_setup_message(game))
        self.assertNotIn("six maneuvers", build_setup_message(game))
        self.assertIn("species abilities", build_lobby_message(build_lobby(
            advanced_maneuvers=False,
        )))


class SetupSettingsTests(unittest.TestCase):
    """
    The settings block `CoinFlipView` carries -- see
    `GameConfigurationView.add_configuration_buttons`.
    """

    def test_the_toggles_are_offered_in_advanced_mode(self) -> None:
        game = build_game()
        view = CoinFlipView(FakeCog(game), game.game_id)

        self.assertEqual(len(module_custom_ids(view)), len(ADVANCED_MODULES))

    def test_a_basic_game_is_offered_neither(self) -> None:
        game = build_game(mode=GameMode.BASIC, board_size=7)
        view = CoinFlipView(FakeCog(game), game.game_id)

        self.assertEqual(module_custom_ids(view), set())

    def test_the_toggles_ride_the_mode_row(self) -> None:
        game = build_game()
        view = CoinFlipView(FakeCog(game), game.game_id)
        rows = {
            item.row
            for item in view.children
            if getattr(item, "custom_id", None)
            and (":module:" in item.custom_id or ":mode:" in item.custom_id)
        }

        self.assertEqual(len(rows), 1)

    def test_clicking_one_turns_it_off(self) -> None:
        game = build_game()
        view = CoinFlipView(FakeCog(game), game.game_id)
        interaction = build_interaction(game.player_1_id)

        with suppressed_view_saves():
            asyncio.run(view.select_module(interaction, "species"))

        self.assertFalse(game.species_abilities)
        interaction.response.edit_message.assert_awaited_once()

    def test_the_last_one_on_is_refused(self) -> None:
        game = build_game(species_abilities=False)
        view = CoinFlipView(FakeCog(game), game.game_id)
        interaction = build_interaction(game.player_1_id)

        with suppressed_view_saves():
            asyncio.run(view.select_module(interaction, "maneuvers"))

        self.assertTrue(game.advanced_maneuvers)
        interaction.response.send_message.assert_awaited_once()
        interaction.response.edit_message.assert_not_awaited()

    def test_only_a_player_may_toggle(self) -> None:
        game = build_game()
        view = CoinFlipView(FakeCog(game), game.game_id)
        interaction = build_interaction(999)

        with suppressed_view_saves():
            asyncio.run(view.select_module(interaction, "species"))

        self.assertTrue(game.species_abilities)
        interaction.response.send_message.assert_awaited_once()

    def test_going_back_to_basic_keeps_the_modules_as_they_were(self) -> None:
        # A mis-click on the mode should not quietly undo them -- see
        # `select_mode`.
        game = build_game(species_abilities=False)
        view = CoinFlipView(FakeCog(game), game.game_id)
        interaction = build_interaction(game.player_1_id)

        with suppressed_view_saves():
            asyncio.run(view.select_mode(interaction, GameMode.BASIC))

        self.assertFalse(game.species_abilities)


class LobbySettingsTests(unittest.TestCase):
    def test_the_toggles_are_offered_in_advanced_mode(self) -> None:
        game = build_lobby()
        view = LobbyView(FakeCog(game), game.game_id)
        actions = {
            item.custom_id.split(":")[2]
            for item in view.children
            if getattr(item, "custom_id", None)
        }

        self.assertIn("module", actions)

    def test_a_basic_lobby_is_offered_neither(self) -> None:
        game = build_lobby(mode=GameMode.BASIC, board_size=7)
        view = LobbyView(FakeCog(game), game.game_id)
        actions = {
            item.custom_id.split(":")[2]
            for item in view.children
            if getattr(item, "custom_id", None)
        }

        self.assertNotIn("module", actions)

    def test_clicking_one_turns_it_off(self) -> None:
        game = build_lobby()
        view = LobbyView(FakeCog(game), game.game_id)
        interaction = build_interaction(game.player_1_id)

        with suppressed_view_saves():
            asyncio.run(
                view.change_setting(interaction, game, "module", "maneuvers")
            )

        self.assertFalse(game.advanced_maneuvers)
        self.assertTrue(game.species_abilities)
        interaction.response.edit_message.assert_awaited_once()

    def test_the_last_one_on_is_refused(self) -> None:
        game = build_lobby(advanced_maneuvers=False)
        view = LobbyView(FakeCog(game), game.game_id)
        interaction = build_interaction(game.player_1_id)

        with suppressed_view_saves():
            asyncio.run(
                view.change_setting(interaction, game, "module", "species")
            )

        self.assertTrue(game.species_abilities)
        interaction.response.send_message.assert_awaited_once()
        interaction.response.edit_message.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
