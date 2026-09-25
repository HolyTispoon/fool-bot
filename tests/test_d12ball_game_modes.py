"""
Picking the mode a game plays: training, basic or advanced (2026-09-25).

Training plays no ability, basic adds the species abilities, advanced
adds the gambits on top (see "Modes" in
docs/design/species-abilities.md). What is tested here is the *offer*:
the three mode buttons the setup settings block and the lobby build out
of one table, and the wording that reads off the mode -- and off the
opt-outs an advanced game saved before the three modes could carry.
"""

import asyncio
import unittest
from types import SimpleNamespace
from unittest import mock

from cogs.d12ball_helpers import (
    DiscordTokens,
    GAME_MODE_BUTTONS,
    build_lobby_message,
    build_setup_message,
    describe_game_mode,
)
from cogs.d12ball_views import CoinFlipView, LobbyView
from d12ball.game import (
    D12BallGame,
    GameMode,
    GameStatus,
    Team,
)
from gamesaves.d12ball.service import GameService
from prompt_fixtures import ENGINE
from save_patches import suppressed_cog_saves


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
        self.team_emojis = {}
        self.d12_emoji = None
        self.d12_button_emoji = None
        # A setting is changed through the service (step 8 of
        # docs/architecture-migration.md), so a view cannot be clicked
        # without one.
        self.service = GameService(ENGINE, self.games)

    def render_text(self, text: str, game=None) -> str:
        return DiscordTokens(self.team_emojis, {}, {}, {}, game).render(text)


def build_interaction(user_id: int) -> SimpleNamespace:
    return SimpleNamespace(
        user=SimpleNamespace(id=user_id),
        response=SimpleNamespace(
            edit_message=mock.AsyncMock(),
            send_message=mock.AsyncMock(),
        ),
    )


def mode_buttons(view) -> dict[str, object]:
    """
    The mode row, by the mode value each button's custom_id carries --
    last on the setup screen, before the game id in the lobby.
    """
    values = {mode.value for mode in GameMode}
    buttons = {}
    for item in view.children:
        parts = (getattr(item, "custom_id", None) or "").split(":")
        if "mode" in parts:
            buttons[next(part for part in parts if part in values)] = item
    return buttons


class ModeTableTests(unittest.TestCase):
    def test_every_mode_is_offered_once(self) -> None:
        self.assertEqual(
            [mode for _, mode in GAME_MODE_BUTTONS], list(GameMode),
        )


class ModeWordingTests(unittest.TestCase):
    def test_a_training_game_is_described_by_its_cards(self) -> None:
        self.assertEqual(
            describe_game_mode(build_game(mode=GameMode.TRAINING)),
            "three maneuvers a side",
        )

    def test_a_basic_game_plays_the_species_abilities(self) -> None:
        self.assertEqual(
            describe_game_mode(build_game(mode=GameMode.BASIC)),
            "three maneuvers a side, species abilities",
        )

    def test_an_advanced_game_adds_the_gambits(self) -> None:
        self.assertEqual(
            describe_game_mode(build_game()),
            "a gambit on every rank, species abilities, personal abilities",
        )

    def test_an_advanced_game_saved_with_a_module_off_says_so(
        self,
    ) -> None:
        self.assertEqual(
            describe_game_mode(build_game(advanced_maneuvers=False)),
            "three maneuvers a side, species abilities, personal abilities",
        )
        self.assertEqual(
            describe_game_mode(build_game(species_abilities=False)),
            "a gambit on every rank, personal abilities",
        )

    def test_a_tutorial_saved_as_basic_is_described_as_training(
        self,
    ) -> None:
        self.assertEqual(
            describe_game_mode(
                build_game(mode=GameMode.BASIC, tutorial=True),
            ),
            "three maneuvers a side",
        )

    def test_both_setup_screens_say_what_the_game_is_playing(self) -> None:
        game = build_game(mode=GameMode.BASIC, board_size=7)

        self.assertIn("species abilities", build_setup_message(game))
        self.assertNotIn("gambit", build_setup_message(game))
        self.assertIn("species abilities", build_lobby_message(build_lobby(
            mode=GameMode.BASIC, board_size=7,
        )))


class SetupSettingsTests(unittest.TestCase):
    """
    The settings block `CoinFlipView` carries -- see
    `GameConfigurationView.add_configuration_buttons`.
    """

    def test_all_three_modes_are_offered_on_one_row(self) -> None:
        game = build_game(mode=GameMode.BASIC, board_size=7)
        buttons = mode_buttons(CoinFlipView(FakeCog(game), game.game_id))

        self.assertEqual(set(buttons), {mode.value for mode in GameMode})
        self.assertEqual(len({button.row for button in buttons.values()}), 1)
        self.assertTrue(buttons["basic"].disabled)
        self.assertFalse(buttons["training"].disabled)

    def test_no_module_toggle_is_offered(self) -> None:
        game = build_game()
        view = CoinFlipView(FakeCog(game), game.game_id)

        self.assertFalse(any(
            ":module:" in (getattr(item, "custom_id", None) or "")
            for item in view.children
        ))

    def test_picking_training_sets_it(self) -> None:
        game = build_game(mode=GameMode.BASIC, board_size=7)
        view = CoinFlipView(FakeCog(game), game.game_id)
        interaction = build_interaction(game.player_1_id)

        with suppressed_cog_saves():
            asyncio.run(view.select_mode(interaction, GameMode.TRAINING))

        self.assertEqual(game.mode, GameMode.TRAINING)
        interaction.response.edit_message.assert_awaited_once()


class LobbySettingsTests(unittest.TestCase):
    def test_all_three_modes_are_offered(self) -> None:
        game = build_lobby(mode=GameMode.BASIC, board_size=7)
        buttons = mode_buttons(LobbyView(FakeCog(game), game.game_id))

        self.assertEqual(set(buttons), {mode.value for mode in GameMode})

    def test_the_tutorial_greys_out_every_mode(self) -> None:
        game = build_lobby(
            mode=GameMode.TRAINING, board_size=7, tutorial=True,
        )
        buttons = mode_buttons(LobbyView(FakeCog(game), game.game_id))

        self.assertTrue(all(button.disabled for button in buttons.values()))

    def test_picking_training_sets_it(self) -> None:
        game = build_lobby()
        view = LobbyView(FakeCog(game), game.game_id)
        interaction = build_interaction(game.player_1_id)

        with suppressed_cog_saves():
            asyncio.run(
                view.change_setting(interaction, game, "mode", "training")
            )

        self.assertEqual(game.mode, GameMode.TRAINING)
        interaction.response.edit_message.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
