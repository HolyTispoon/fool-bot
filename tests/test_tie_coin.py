"""
D12 Ball 2.0's coin (docs/rules-2.0.md, section 5): a tied roll goes to
the side the coin favours rather than being rolled again, the coin is
flipped at the first turn and tossed again after a maneuver an advanced
card was played in -- and moving on the board costs a token a space
(rules-2.0 5.4), where a card costs nothing. 1.0 is untouched. See
docs/design/maneuver-deck.md, "The coin" and "Moving costs".
"""

import pathlib
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from d12ball.components import MatchState, PlayerRole, TeamSide
from d12ball.flow import effects, rolls
from d12ball.flow.turn import owe_coin_toss, settle_tie_coin
from d12ball.game import CoinFace, Edition, GameMode
from d12ball.prompts import PromptKind, PendingPrompt

from roster import fielded
from test_d12ball_species_abilities import (
    build_engine,
    build_game,
    build_match,
)

ENGINE = build_engine()


def level(original):
    """`original` with its two totals made equal, so the roll ties."""
    def tied(*args, **kwargs):
        contestants, _, _, offense_ignite, defense_ignite = original(
            *args, **kwargs,
        )
        return contestants, 7, 7, offense_ignite, defense_ignite
    return tied


class TieCoinTests(unittest.TestCase):

    def setUp(self) -> None:
        # Training mode, so no ability adds to a roll or a cost.
        self.game = build_game(mode=GameMode.TRAINING)
        self.game.edition = Edition.TWO
        self.match = build_match(ENGINE, self.game)
        self.match.ball.possession = TeamSide.HOME
        self.handler = fielded(self.match, PlayerRole.PLAYMAKER, TeamSide.HOME)
        self.challenger = fielded(
            self.match, PlayerRole.MIDFIELDER, TeamSide.VISITING,
        )

    def stage_skill_test(self) -> None:
        self.match.select_ball_handler(self.handler)
        self.match.challenger_id = self.challenger
        self.match.offense_maneuver = "dribble_advance"
        self.match.defense_maneuver = "steal"

    def tied_skill_test(self):
        with mock.patch.object(
            rolls, "score_skill_test", level(rolls.score_skill_test),
        ):
            return rolls.skill_test_step(ENGINE, self.game, self.match)

    # -- The skill test ------------------------------------------------

    def test_fortune_gives_a_tied_skill_test_to_the_offense(self) -> None:
        self.match.tie_coin = CoinFace.FORTUNE.value
        self.stage_skill_test()
        before = dict(self.match.exhaustion)
        _, result = self.tied_skill_test()
        self.assertEqual(self.match.skill_test_winner, "dribble_advance")
        self.assertIn("It's a tie (7-7)", result.narration[0])
        self.assertIn("Fortune", result.narration[0])
        self.assertNotIsInstance(result.next, PendingPrompt)
        # Not rolled again, so nobody paid for it.
        self.assertEqual(dict(self.match.exhaustion), before)

    def test_doom_gives_it_to_the_defense(self) -> None:
        self.match.tie_coin = CoinFace.DOOM.value
        self.stage_skill_test()
        _, result = self.tied_skill_test()
        self.assertEqual(self.match.skill_test_winner, "steal")
        self.assertIn("Doom", result.narration[0])

    def test_one_point_oh_still_rolls_a_tie_again(self) -> None:
        self.game.edition = Edition.ONE
        self.stage_skill_test()
        _, result = self.tied_skill_test()
        self.assertIsInstance(result.next, PendingPrompt)
        self.assertEqual(result.next.kind, PromptKind.SKILL_TEST)
        self.assertIsNone(self.match.skill_test_winner)
        self.assertEqual(self.match.exhaustion.get(self.handler), 1)

    def test_a_save_from_before_the_coin_flips_it_at_the_tie(self) -> None:
        self.stage_skill_test()
        _, result = self.tied_skill_test()
        self.assertIn(self.match.tie_coin, {"fortune", "doom"})
        self.assertIn("The coin is flipped", result.narration[0])
        self.assertIsNotNone(self.match.skill_test_winner)

    # -- The contest for the ball ---------------------------------------

    def test_a_tied_contest_goes_to_the_side_that_last_held_the_ball(self) -> None:
        for face, winner_side in (
            (CoinFace.FORTUNE, TeamSide.HOME),
            (CoinFace.DOOM, TeamSide.VISITING),
        ):
            with self.subTest(face=face):
                self.setUp()
                self.match.tie_coin = face.value
                self.match.pending_loose_ball = True
                self.match.loose_ball_offense_player = self.handler
                self.match.loose_ball_defense_player = self.challenger
                before = dict(self.match.exhaustion)
                with mock.patch.object(
                    rolls, "score_loose_ball", level(rolls.score_loose_ball),
                ):
                    _, result = rolls.loose_ball_test_step(
                        ENGINE, self.game, self.match,
                    )
                self.assertEqual(self.match.ball.possession, winner_side)
                self.assertIn("It's a tie (7-7)", result.narration[0])
                self.assertEqual(dict(self.match.exhaustion), before)

    # -- A card costs nothing; moving costs a token a space ------------

    def stage_on_the_ball(self) -> None:
        """The handler holding the ball, and the challenger walked in
        onto their space -- walked in for nothing, so every token after
        is the effect's."""
        self.stage_skill_test()
        position = self.match.board.meeple_position(self.handler)
        self.match.set_ball_space(*position)
        self.match.set_ball_carrier(self.handler)
        self.match.move_meeple(self.challenger, *position)

    def tokens(self, player_id: str) -> int:
        return self.match.exhaustion.get(player_id, 0)

    def test_revealing_the_cards_costs_nothing(self) -> None:
        self.stage_skill_test()
        self.match.offense_maneuver = "high_pass"
        self.match.defense_maneuver = "steal"
        owe_coin_toss(ENGINE, self.game, self.match)
        self.assertEqual(self.tokens(self.handler), 0)
        self.assertEqual(self.tokens(self.challenger), 0)
        # Basic cards owe the coin nothing.
        self.assertFalse(self.match.tie_coin_owed)

    def test_an_unchallenged_advanced_card_owes_a_toss(self) -> None:
        self.match.select_ball_handler(self.handler)
        self.match.maneuver_uncontested = True
        self.match.offense_maneuver = "skilled_pass"
        owe_coin_toss(ENGINE, self.game, self.match)
        self.assertEqual(self.tokens(self.handler), 0)
        self.assertTrue(self.match.tie_coin_owed)

    def test_entering_the_skill_test_is_free_in_two_point_oh(self) -> None:
        self.stage_skill_test()
        self.assertEqual(
            ENGINE.skill_test_tokens(self.game, self.match, self.handler), 0,
        )
        self.game.edition = Edition.ONE
        self.assertEqual(
            ENGINE.skill_test_tokens(self.game, self.match, self.handler), 1,
        )

    def test_a_dribble_costs_the_handler_its_space(self) -> None:
        for edition, paid in ((Edition.TWO, 1), (Edition.ONE, 0)):
            with self.subTest(edition=edition):
                self.setUp()
                self.game.edition = edition
                self.stage_on_the_ball()
                result = effects.dribble_advance_step(
                    ENGINE, self.game, self.match, 1,
                )
                self.assertEqual(self.tokens(self.handler), paid)
                self.assertEqual(
                    "exhausts 1" in result.narration[0], bool(paid),
                )

    def test_a_steal_costs_the_thief_its_carry(self) -> None:
        for edition, paid in ((Edition.TWO, 1), (Edition.ONE, 0)):
            with self.subTest(edition=edition):
                self.setUp()
                self.game.edition = edition
                self.stage_on_the_ball()
                effects.steal_step(ENGINE, self.match, "steal", self.game)
                self.assertEqual(self.tokens(self.challenger), paid)

    def test_a_pressure_costs_the_handler_and_the_challenger_who_follows(self) -> None:
        for edition, paid in ((Edition.TWO, 1), (Edition.ONE, 0)):
            with self.subTest(edition=edition):
                self.setUp()
                self.game.edition = edition
                self.stage_on_the_ball()
                effects.pressure_step(
                    ENGINE, self.match, "pressure", self.game,
                )
                self.assertEqual(self.tokens(self.handler), paid)
                self.assertEqual(self.tokens(self.challenger), paid)

    def test_a_beaten_double_team_costs_its_step_forward(self) -> None:
        for edition, paid in ((Edition.TWO, 1), (Edition.ONE, 0)):
            with self.subTest(edition=edition):
                self.setUp()
                self.game.edition = edition
                self.stage_on_the_ball()
                self.match.offense_maneuver = "low_pass"
                self.match.defense_maneuver = "double_team"
                said = effects.pay_double_team_cost(
                    ENGINE, self.match, "low_pass", None, self.game,
                )
                self.assertIn("shoved a space forward", said)
                self.assertEqual(self.tokens(self.challenger), paid)

    def test_the_passers_step_costs_its_space_and_the_ask_says_so(self) -> None:
        for edition, paid in ((Edition.TWO, 1), (Edition.ONE, 0)):
            with self.subTest(edition=edition):
                self.setUp()
                self.game.edition = edition
                self.stage_on_the_ball()
                self.match.pending_passer_advance = {
                    "passer_id": self.handler, "then": "loose",
                }
                ask = effects.passer_advance_prompt(
                    ENGINE, self.game, self.match,
                ).ask
                self.assertEqual("for 1 exhaustion" in ask, bool(paid))
                effects.answer_passer_advance(
                    ENGINE, self.game, self.match, True,
                )
                self.assertEqual(self.tokens(self.handler), paid)

    # -- Flipped and tossed ----------------------------------------------

    def test_flipped_at_the_first_turn_and_tossed_only_when_owed(self) -> None:
        line = settle_tie_coin(ENGINE, self.game, self.match)
        self.assertIn("The coin is flipped", line)
        face = self.match.tie_coin
        self.assertIn(face, {"fortune", "doom"})
        self.assertEqual(settle_tie_coin(ENGINE, self.game, self.match), "")
        self.assertEqual(self.match.tie_coin, face)

        self.match.tie_coin_owed = True
        line = settle_tie_coin(ENGINE, self.game, self.match)
        self.assertIn("tossed again", line)
        self.assertFalse(self.match.tie_coin_owed)

    def test_one_point_oh_has_no_tie_coin(self) -> None:
        self.game.edition = Edition.ONE
        self.assertEqual(settle_tie_coin(ENGINE, self.game, self.match), "")
        self.assertIsNone(self.match.tie_coin)

    # -- Shown -------------------------------------------------------------

    def test_the_turn_message_shows_the_coin_once_flipped(self) -> None:
        self.assertNotIn("{coin:", ENGINE.build_turn_prompt(self.game, self.match))
        self.match.tie_coin = CoinFace.DOOM.value
        prompt = ENGINE.build_turn_prompt(self.game, self.match)
        self.assertIn("{coin:doom} **Doom**: defense wins ties.", prompt)
        self.game.edition = Edition.ONE
        self.assertNotIn("{coin:", ENGINE.build_turn_prompt(self.game, self.match))

    def test_the_board_is_drawn_with_the_coin(self) -> None:
        from d12ball.render import render_match_image
        self.match.tie_coin = CoinFace.FORTUNE.value
        png = render_match_image(
            self.match, ENGINE.player_catalog,
            tie_coin=("coin_gold_3_fortune", ENGINE.tie_coin_caption(self.match)),
        ).getvalue()
        self.assertTrue(png.startswith(b"\x89PNG"))
        self.assertEqual(
            ENGINE.tie_coin_caption(self.match), "Offense wins ties",
        )

    # -- Saved -------------------------------------------------------------

    def test_saved_only_once_flipped(self) -> None:
        self.assertNotIn("tie_coin", self.match.to_dict())
        self.match.tie_coin = CoinFace.DOOM.value
        self.match.tie_coin_owed = True
        saved = self.match.to_dict()
        restored = MatchState.from_dict(saved, ENGINE.basic_ruleset)
        self.assertEqual(restored.tie_coin, "doom")
        self.assertTrue(restored.tie_coin_owed)


if __name__ == "__main__":
    unittest.main()
