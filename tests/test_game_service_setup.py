"""
Setup and the lobby through `GameService`, with no frontend imported.

Step 8 of docs/architecture-migration.md (decision 6 of
docs/web-app.md): a lobby is opened, joined, configured and started, a
team is picked, the coin is flipped, home or visiting chosen and the
pre-kickoff window opened, all through service methods -- each one
change to the record the record itself rules on, saved once. A
refusal is a `RuleRefusal` and writes nothing. The game has no server,
channel or message, which is what a web app's game looks like.
"""

from __future__ import annotations

import unittest

from d12ball.components import RuleRefusal
from d12ball.game import (
    AIOpponent,
    CoinFace,
    D12BallGame,
    GameMode,
    GameStatus,
    HomeChoice,
    Team,
    paired_team,
)
from d12ball.prompts import PromptKind
from gamesaves.d12ball.service import GameService
from prompt_fixtures import ENGINE


CREATOR = 111
JOINER = 222
WATCHER = 333


class SetupHarness(unittest.TestCase):
    def setUp(self) -> None:
        self.games: dict[str, D12BallGame] = {}
        self.saves = 0

        def save(games: dict) -> None:
            self.saves += 1

        self.service = GameService(ENGINE, self.games, save=save)

    def open_lobby(self) -> D12BallGame:
        return self.service.create_game(
            player_1_id=CREATOR, player_1_name="One", in_lobby=True,
        )

    def refused(self, call, *args) -> str:
        """The refusal's sentence, with the record left as it was and
        nothing written."""
        game = self.games[args[0]] if args else None
        before = game.to_dict() if game is not None else None
        saves = self.saves
        with self.assertRaises(RuleRefusal) as caught:
            call(*args)
        if game is not None:
            self.assertEqual(game.to_dict(), before)
        self.assertEqual(self.saves, saves)
        return str(caught.exception)


class CreateGameTests(SetupHarness):
    def test_a_game_needs_no_discord(self) -> None:
        game = self.service.create_game(
            player_1_id=CREATOR, player_1_name="One",
        )

        self.assertIn(game.game_id, self.games)
        self.assertEqual(
            (game.guild_id, game.channel_id, game.message_id),
            (None, None, None),
        )
        self.assertEqual(game.status, GameStatus.SETUP)
        self.assertEqual(game.game_number, 1)
        self.assertEqual(self.saves, 1)

    def test_a_solo_game_is_against_dinky_and_a_lobby_settles_nothing(
        self,
    ) -> None:
        solo = self.service.create_game(player_1_id=CREATOR, player_1_name="One")
        lobby = self.open_lobby()
        paired = self.service.create_game(
            player_1_id=CREATOR,
            player_1_name="One",
            player_2_id=JOINER,
            player_2_name="Two",
            ai_opponent=AIOpponent.DINKY,
        )

        self.assertEqual(solo.ai_opponent, AIOpponent.DINKY)
        self.assertIsNone(lobby.ai_opponent)
        self.assertIsNone(paired.ai_opponent)

    def test_game_numbers_run_per_server(self) -> None:
        self.service.create_game(player_1_id=CREATOR, player_1_name="One", guild_id=1)
        self.service.create_game(player_1_id=CREATOR, player_1_name="One", guild_id=1)
        elsewhere = self.service.create_game(
            player_1_id=CREATOR, player_1_name="One", guild_id=2,
        )
        nowhere = self.service.create_game(player_1_id=CREATOR, player_1_name="One")

        self.assertEqual(self.service.next_game_number(1), 3)
        self.assertEqual(elsewhere.game_number, 1)
        self.assertEqual(nowhere.game_number, 1)

    def test_a_game_that_never_started_may_be_discarded(self) -> None:
        game = self.open_lobby()

        self.service.discard_game(game.game_id)

        self.assertNotIn(game.game_id, self.games)
        self.assertEqual(self.saves, 2)


class LobbyTests(SetupHarness):
    def test_join_observe_and_leave(self) -> None:
        game = self.open_lobby()

        self.service.lobby_observe(game.game_id, JOINER)
        self.assertEqual(game.observer_ids, [JOINER])

        self.service.lobby_join(game.game_id, JOINER, "Two")
        self.assertEqual((game.player_2_id, game.player_2_name), (JOINER, "Two"))
        self.assertEqual(game.observer_ids, [])

        self.service.lobby_observe(game.game_id, WATCHER)
        self.service.lobby_leave(game.game_id, WATCHER)
        self.assertEqual(game.observer_ids, [])

        self.service.lobby_leave(game.game_id, JOINER)
        self.assertIsNone(game.player_2_id)
        self.assertEqual(self.saves, 6)

    def test_joining_clears_the_creators_ai_pick(self) -> None:
        game = self.open_lobby()
        self.service.configure(game.game_id, "ai", "dinky")

        self.service.lobby_join(game.game_id, JOINER, "Two")

        self.assertIsNone(game.ai_opponent)

    def test_the_creator_leaving_hands_the_lobby_over(self) -> None:
        game = self.open_lobby()
        self.service.lobby_join(game.game_id, JOINER, "Two")

        self.service.lobby_leave(game.game_id, CREATOR)

        self.assertEqual((game.player_1_id, game.player_1_name), (JOINER, "Two"))
        self.assertIsNone(game.player_2_id)

    def test_the_refusals_leave_the_lobby_as_it_was(self) -> None:
        game = self.open_lobby()

        self.assertIn(
            "already in", self.refused(self.service.lobby_join, game.game_id, CREATOR, "One"),
        )
        self.assertIn(
            "only player", self.refused(self.service.lobby_leave, game.game_id, CREATOR),
        )
        self.assertIn(
            "not in this lobby", self.refused(self.service.lobby_leave, game.game_id, WATCHER),
        )
        self.assertIn(
            "playing in this game",
            self.refused(self.service.lobby_observe, game.game_id, CREATOR),
        )

        self.service.lobby_observe(game.game_id, WATCHER)
        self.assertIn(
            "already on the observer list",
            self.refused(self.service.lobby_observe, game.game_id, WATCHER),
        )

        self.service.lobby_join(game.game_id, JOINER, "Two")
        self.assertIn(
            "full", self.refused(self.service.lobby_join, game.game_id, WATCHER, "Three"),
        )
        self.assertIn(
            "already joined",
            self.refused(self.service.configure, game.game_id, "test"),
        )

    def test_a_one_player_lobby_cannot_be_joined(self) -> None:
        game = self.open_lobby()
        self.service.configure(game.game_id, "tutorial")

        self.assertIn(
            "one-player", self.refused(self.service.lobby_join, game.game_id, JOINER, "Two"),
        )

    def test_start_settles_the_other_side(self) -> None:
        solo = self.open_lobby()
        self.service.start_lobby(solo.game_id)
        self.assertFalse(solo.in_lobby)
        self.assertEqual(solo.ai_opponent, AIOpponent.DINKY)

        test = self.open_lobby()
        self.service.configure(test.game_id, "test")
        self.service.start_lobby(test.game_id)
        self.assertEqual(test.player_2_id, test.player_1_id)
        self.assertIsNone(test.ai_opponent)

        pair = self.open_lobby()
        self.service.lobby_join(pair.game_id, JOINER, "Two")
        self.service.start_lobby(pair.game_id)
        self.assertEqual(pair.player_2_id, JOINER)
        self.assertIsNone(pair.ai_opponent)

    def test_a_started_lobby_is_closed_and_may_be_reopened(self) -> None:
        game = self.open_lobby()
        self.service.configure(game.game_id, "test")
        self.service.start_lobby(game.game_id)

        for call, args in (
            (self.service.lobby_join, (game.game_id, JOINER, "Two")),
            (self.service.lobby_observe, (game.game_id, WATCHER)),
            (self.service.lobby_leave, (game.game_id, CREATOR)),
            (self.service.start_lobby, (game.game_id,)),
            (self.service.configure, (game.game_id, "tutorial")),
            (self.service.configure, (game.game_id, "name", "x")),
        ):
            with self.subTest(call=call.__name__):
                self.assertIn("no longer open", self.refused(call, *args))

        self.service.reopen_lobby(game.game_id)

        self.assertTrue(game.in_lobby)
        self.assertIsNone(game.player_2_id)
        self.assertTrue(game.test_game)
        self.assertIn(
            "left its lobby", self.refused(self.service.reopen_lobby, game.game_id),
        )


class ConfigureTests(SetupHarness):
    def test_every_setting_from_its_wire_value(self) -> None:
        game = self.open_lobby()

        self.service.configure(game.game_id, "mode", "advanced")
        self.assertEqual((game.mode, game.board_size), (GameMode.ADVANCED, 9))
        self.service.configure(game.game_id, "board", "7")
        self.assertEqual(game.board_size, 7)
        # The six-space board was withdrawn on 2026-09-22 (see the
        # rules log), so the record refuses it however it is asked for.
        with self.assertRaises(ValueError):
            self.service.configure(game.game_id, "board", "6")
        self.assertEqual(game.board_size, 7)
        self.service.configure(game.game_id, "module", "species")
        self.assertFalse(game.species_abilities)
        self.service.configure(game.game_id, "ai", "dinky")
        self.assertEqual(game.ai_opponent, AIOpponent.DINKY)
        self.service.configure(game.game_id, "name", "  The Cup Final ")
        self.assertEqual(game.game_name, "The Cup Final")
        self.service.configure(game.game_id, "name", "")
        self.assertIsNone(game.game_name)
        self.service.configure(game.game_id, "mode", GameMode.BASIC)
        # Going back to Basic leaves the modules as they were.
        self.assertFalse(game.species_abilities)

    def test_the_tutorial_pins_basic_seven_and_dinky(self) -> None:
        game = self.open_lobby()
        self.service.configure(game.game_id, "mode", "advanced")

        self.service.configure(game.game_id, "tutorial")

        self.assertTrue(game.tutorial)
        self.assertFalse(game.test_game)
        self.assertEqual(
            (game.mode, game.board_size, game.ai_opponent),
            (GameMode.BASIC, 7, AIOpponent.DINKY),
        )
        self.assertIn(
            "Basic-mode", self.refused(self.service.configure, game.game_id, "mode", "advanced"),
        )
        self.assertIn(
            "7-space", self.refused(self.service.configure, game.game_id, "board", "9"),
        )
        # The pin holds past the lobby too: the setup screen's board
        # buttons used to let a tutorial onto a nine-space board.
        self.service.start_lobby(game.game_id)
        self.assertIn(
            "7-space", self.refused(self.service.configure, game.game_id, "board", "9"),
        )

    def test_test_game_and_tutorial_exclude_each_other(self) -> None:
        game = self.open_lobby()

        self.service.configure(game.game_id, "test")
        self.service.configure(game.game_id, "tutorial")
        self.assertEqual((game.test_game, game.tutorial), (False, True))
        self.service.configure(game.game_id, "test")
        self.assertEqual((game.test_game, game.tutorial), (True, False))

    def test_the_last_module_on_and_the_decent_ai_are_refused(self) -> None:
        game = self.open_lobby()
        self.service.configure(game.game_id, "mode", "advanced")
        self.service.configure(game.game_id, "module", "maneuvers")

        self.assertIn(
            "Basic", self.refused(self.service.configure, game.game_id, "module", "species"),
        )
        self.assertIn(
            "Dinky", self.refused(self.service.configure, game.game_id, "ai", "decent"),
        )

    def test_the_ai_row_belongs_to_an_open_solo_game(self) -> None:
        game = self.open_lobby()
        self.service.lobby_join(game.game_id, JOINER, "Two")

        self.assertIn(
            "already taken",
            self.refused(self.service.configure, game.game_id, "ai", "dinky"),
        )

    def test_a_setting_the_record_cannot_read_is_a_bug(self) -> None:
        game = self.open_lobby()

        with self.assertRaises(ValueError) as caught:
            self.service.configure(game.game_id, "colour", "red")
        self.assertNotIsInstance(caught.exception, RuleRefusal)
        with self.assertRaises(ValueError) as caught:
            self.service.configure(game.game_id, "board", "8")
        self.assertNotIsInstance(caught.exception, RuleRefusal)

    def test_settings_close_with_setup(self) -> None:
        game = self.two_coaches_at_the_coin()
        self.service.flip_coin(game.game_id, 1)

        self.assertIn(
            "during setup",
            self.refused(self.service.configure, game.game_id, "mode", "advanced"),
        )

    def two_coaches_at_the_coin(self) -> D12BallGame:
        game = self.open_lobby()
        self.service.lobby_join(game.game_id, JOINER, "Two")
        self.service.start_lobby(game.game_id)
        self.service.pick_team(game.game_id, 1, Team.ORANGE)
        self.service.pick_team(game.game_id, 2, Team.PURPLE)
        return game


class TeamPickTests(SetupHarness):
    def test_a_solo_pick_draws_dinkys_team_from_the_pool(self) -> None:
        game = self.open_lobby()
        self.service.start_lobby(game.game_id)

        self.service.pick_team(game.game_id, 1, Team.ORANGE)

        self.assertEqual(game.player_1_team, Team.ORANGE)
        self.assertIn(
            game.player_2_team,
            set(Team) - {Team.ORANGE, paired_team(Team.ORANGE)},
        )
        self.assertTrue(game.teams_selected)

    def test_a_pair_is_refused_for_its_colour(self) -> None:
        game = self.open_lobby()
        self.service.lobby_join(game.game_id, JOINER, "Two")
        self.service.start_lobby(game.game_id)
        self.service.pick_team(game.game_id, 1, Team.TEAL)

        for taken in (Team.TEAL, paired_team(Team.TEAL)):
            with self.subTest(team=taken.value):
                self.assertIn(
                    "no longer available",
                    self.refused(self.service.pick_team, game.game_id, 2, taken),
                )
        self.service.pick_team(game.game_id, 2, Team.OOZES)
        self.assertEqual(game.player_2_team, Team.OOZES)

    def test_a_test_games_screens_go_player_one_first(self) -> None:
        game = self.open_lobby()
        self.service.configure(game.game_id, "test")
        self.service.start_lobby(game.game_id)

        self.assertEqual(game.picking_player_number(), 1)
        self.service.pick_team(game.game_id, 1, Team.SLIME)
        self.assertEqual(game.picking_player_number(), 2)
        self.assertEqual(game.excluded_teams(2), {Team.SLIME, Team.OOZES})
        self.assertEqual(game.team_pick_lands_on(2), 2)

    def test_a_helpers_pick_lands_on_the_open_side(self) -> None:
        game = self.open_lobby()
        self.service.lobby_join(game.game_id, JOINER, "Two")
        self.service.start_lobby(game.game_id)

        self.assertEqual(game.team_pick_lands_on(None), 1)
        self.service.pick_team(game.game_id, 1, Team.ORANGE)
        self.assertEqual(game.team_pick_lands_on(None), 2)

    def test_a_lobby_has_no_team_picker(self) -> None:
        game = self.open_lobby()

        self.assertIn(
            "closed", self.refused(self.service.pick_team, game.game_id, 1, Team.ORANGE),
        )


class CoinAndSidesTests(SetupHarness):
    def seeded(self, seed: int):
        # The coin and Dinky's draws are the engine's `rng`, so that
        # is what a test seeds.
        ENGINE.rng.seed(seed)

    def two_coaches(self) -> D12BallGame:
        game = self.open_lobby()
        self.service.lobby_join(game.game_id, JOINER, "Two")
        self.service.start_lobby(game.game_id)
        self.service.pick_team(game.game_id, 1, Team.ORANGE)
        self.service.pick_team(game.game_id, 2, Team.PURPLE)
        return game

    def test_the_coin_needs_both_teams(self) -> None:
        game = self.open_lobby()
        self.service.start_lobby(game.game_id)

        self.assertIn(
            "Both teams", self.refused(self.service.flip_coin, game.game_id, 1),
        )

    def test_the_toss_starts_the_game_and_names_its_winner(self) -> None:
        game = self.two_coaches()

        self.service.flip_coin(game.game_id, 2)

        self.assertTrue(game.coin_flipped)
        self.assertEqual(game.coin_flipped_by_player_number, 2)
        self.assertEqual(game.status, GameStatus.IN_PROGRESS)
        self.assertIsInstance(game.coin_face, CoinFace)
        winner = game.coin_winner_player_number
        self.assertEqual(
            winner, 2 if game.coin_face is CoinFace.FORTUNE else 1,
        )
        self.assertEqual(game.coin_winner, "Two" if winner == 2 else "One")
        # Two coaches: nobody has chosen yet, and there is no match.
        self.assertFalse(game.home_and_visiting_selected)
        self.assertIsNone(game.match_state)
        self.assertIn(
            "already been flipped", self.refused(self.service.flip_coin, game.game_id, 1),
        )

    def test_the_winner_chooses_and_the_match_is_dealt(self) -> None:
        game = self.two_coaches()
        self.service.flip_coin(game.game_id, 1)
        winner = game.coin_winner_player_number
        loser = 2 if winner == 1 else 1

        self.assertIn(
            "coin-toss winner",
            self.refused(
                self.service.choose_home_or_visiting, game.game_id, loser, "home",
            ),
        )
        self.service.choose_home_or_visiting(game.game_id, winner, "visiting")

        self.assertEqual(game.visiting_player_number, winner)
        self.assertEqual(game.home_player_number, loser)
        self.assertIsNotNone(game.match_state)
        self.assertIn(
            "already assigned",
            self.refused(
                self.service.choose_home_or_visiting, game.game_id, winner, HomeChoice.HOME,
            ),
        )

        result = self.service.begin(game.game_id)
        self.assertEqual(result.prompt.kind, PromptKind.COACHING_HUB)

    def test_a_tutorials_coach_is_home_whoever_wins(self) -> None:
        """
        The record's rail (`D12BallGame.home_choice_rail`): the script
        is written for a coach with the ball at kickoff. A coach who
        wins the toss may take Home and nothing else; Dinky, winning,
        takes Visiting -- one reading for the button, the refusal and
        the service's own choice for Dinky.
        """
        for seed in range(12):
            self.seeded(seed)
            game = self.open_lobby()
            self.service.configure(game.game_id, "tutorial")
            self.service.start_lobby(game.game_id)
            self.service.pick_team(game.game_id, 1, Team.ORANGE)
            self.service.flip_coin(game.game_id, 1)
            if game.coin_winner_player_number == 1:
                break
        else:  # pragma: no cover - twelve tails in a row
            self.fail("the coach never won the toss")

        self.assertEqual(game.home_choice_rail(1), HomeChoice.HOME)
        self.assertIn(
            "plays Home",
            self.refused(
                self.service.choose_home_or_visiting,
                game.game_id, 1, HomeChoice.VISITING,
            ),
        )
        self.service.choose_home_or_visiting(game.game_id, 1, HomeChoice.HOME)
        self.assertEqual(game.home_player_number, 1)
        self.assertIsNone(game.home_choice_rail(1))

    def test_dinky_winning_the_toss_chooses_for_itself(self) -> None:
        """
        Whichever way the coin lands, the record ends up in one of two
        shapes: Dinky won and chose, and the match is dealt; or the
        coach won and is asked. Both are reached across a dozen seeds.
        """
        seen = set()
        for seed in range(12):
            with self.subTest(seed=seed):
                self.seeded(seed)
                game = self.open_lobby()
                self.service.start_lobby(game.game_id)
                self.service.pick_team(game.game_id, 1, Team.ORANGE)

                self.service.flip_coin(game.game_id, 1)

                winner = game.coin_winner_player_number
                seen.add(winner)
                if winner == 2:
                    self.assertIn("Dinky", game.coin_winner)
                    self.assertTrue(game.home_and_visiting_selected)
                    self.assertIsNotNone(game.match_state)
                else:
                    self.assertEqual(game.coin_winner, "One")
                    self.assertFalse(game.home_and_visiting_selected)
                    self.assertIsNone(game.match_state)
        self.assertEqual(seen, {1, 2})

    def test_a_tutorials_dinky_takes_visiting(self) -> None:
        """
        The script is written for a coach with the ball at kickoff,
        so Dinky leaves them home whenever it wins the toss -- every
        seed, not most of them.
        """
        for seed in range(12):
            with self.subTest(seed=seed):
                self.seeded(seed)
                game = self.open_lobby()
                self.service.configure(game.game_id, "tutorial")
                self.service.start_lobby(game.game_id)
                self.service.pick_team(game.game_id, 1, Team.ORANGE)
                self.service.flip_coin(game.game_id, 1)
                if game.coin_winner_player_number == 2:
                    self.assertEqual(game.visiting_player_number, 2)
                    self.assertEqual(game.home_player_number, 1)

    def test_one_save_per_call_and_none_for_a_refusal(self) -> None:
        game = self.two_coaches()
        saves = self.saves

        self.service.flip_coin(game.game_id, 1)
        self.assertEqual(self.saves, saves + 1)
        self.refused(self.service.flip_coin, game.game_id, 1)
        self.assertEqual(self.saves, saves + 1)


if __name__ == "__main__":
    unittest.main()
