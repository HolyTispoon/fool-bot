"""
D12 Ball 2.2's coin (docs/rules-2.2.md, section 5): the setup toss's
face at the first turn, its face settles every tie -- a skill test's, a contest for
the ball's, a shot's -- rather than a re-roll or a goal, and it is tossed
again after the tie, so the next tie's answer is always known and shown
on the turn message; a tied shootout test scores for nobody -- and
moving on the board costs a
token a space (rules-2.2 5.4), where a card costs nothing. 1.0 is
untouched. See docs/design/maneuver-deck.md, "The coin" and "Moving
costs".
"""

import pathlib
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from d12ball.components import MatchState, PlayerRole, TeamSide
from d12ball.flow import effects, rolls
from d12ball.game import CoinFace, Edition, GameMode
from d12ball.flow.turn import settle_tie_coin
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


def tossed(face: CoinFace):
    """The coin's next toss -- the one after the tie -- fixed."""
    return mock.patch.object(ENGINE, "flip_coin", return_value=face)


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
        with tossed(CoinFace.DOOM):
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
        with tossed(CoinFace.FORTUNE):
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

    def test_the_face_settles_the_tie_and_is_tossed_again_after(self) -> None:
        # The face shown before the tie is what decides it; the toss
        # after it sets the next tie's answer.
        self.match.tie_coin = CoinFace.DOOM.value
        self.stage_skill_test()
        with tossed(CoinFace.FORTUNE) as flip:
            _, result = self.tied_skill_test()
        flip.assert_called_once()
        self.assertEqual(self.match.skill_test_winner, "steal")
        self.assertEqual(self.match.tie_coin, "fortune")
        self.assertIn("tossed again", result.narration[0])
        self.assertIn("offense wins ties from now", result.narration[0])

    def test_a_tie_before_any_flip_flips_it_first(self) -> None:
        self.stage_skill_test()
        with mock.patch.object(
            ENGINE, "flip_coin", side_effect=[CoinFace.FORTUNE, CoinFace.DOOM],
        ):
            _, result = self.tied_skill_test()
        self.assertEqual(self.match.skill_test_winner, "dribble_advance")
        self.assertEqual(self.match.tie_coin, "doom")
        self.assertIn("The coin is flipped", result.narration[0])

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
                ), tossed(CoinFace.FORTUNE):
                    _, result = rolls.loose_ball_test_step(
                        ENGINE, self.game, self.match,
                    )
                self.assertEqual(self.match.ball.possession, winner_side)
                self.assertIn("It's a tie (7-7)", result.narration[0])
                self.assertEqual(dict(self.match.exhaustion), before)

    # -- The shot ---------------------------------------------------------

    def tied_shot(self):
        def level_shot(*args, **kwargs):
            contestants, _, _, ignite = original(*args, **kwargs)
            return contestants, 9, 9, ignite
        original = rolls.score_score_attempt
        self.match.select_ball_handler(self.handler)
        self.match.pending_action = "shoot"
        with mock.patch.object(rolls, "score_score_attempt", level_shot):
            return rolls.score_attempt_step(ENGINE, self.game, self.match)

    def test_a_tied_shot_scores_on_fortune_and_misses_on_doom(self) -> None:
        for face, scored in ((CoinFace.FORTUNE, True), (CoinFace.DOOM, False)):
            with self.subTest(face=face):
                self.setUp()
                self.match.tie_coin = face.value
                with tossed(CoinFace.DOOM):
                    dice, result = self.tied_shot()
                self.assertIs(dice.scored, scored)
                self.assertIn("It's a tie (9-9)", result.narration[0])
                self.assertIn(
                    "the attack wins it" if scored else "the defense wins it",
                    result.narration[0],
                )

    def test_a_tied_shot_still_scores_in_one_point_oh(self) -> None:
        self.game.edition = Edition.ONE
        with mock.patch.object(ENGINE, "flip_coin") as flip:
            dice, _ = self.tied_shot()
        self.assertTrue(dice.scored)
        flip.assert_not_called()

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

    def test_a_double_teams_partner_pays_for_the_spaces_they_join_from(self) -> None:
        for edition in (Edition.TWO, Edition.ONE):
            with self.subTest(edition=edition):
                self.setUp()
                self.game.edition = edition
                self.stage_on_the_ball()
                partner = next(
                    player_id
                    for player_id in self.match.visiting.field_players
                    if player_id != self.challenger
                )
                start = self.match.board.flat_index(
                    *self.match.board.meeple_position(partner)
                )
                with mock.patch.object(
                    ENGINE, "double_team_partner", return_value=partner,
                ):
                    effects.pressure_step(
                        ENGINE, self.match, "double_team", self.game,
                    )
                came = abs(
                    self.match.board.flat_index(
                        *self.match.board.meeple_position(partner)
                    )
                    - start
                )
                self.assertGreater(came, 0)
                self.assertEqual(
                    self.tokens(partner),
                    came if edition == Edition.TWO else 0,
                )

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

    # -- Shown -------------------------------------------------------------

    def test_the_first_turn_takes_the_toss_face(self) -> None:
        # The coin that decided home or the visitors is the coin: it is
        # not flipped again (rules-2.2 5.2; the author, 2026-11-01).
        self.game.coin_face = CoinFace.DOOM
        with mock.patch.object(ENGINE, "flip_coin") as flip:
            self.assertIsNone(settle_tie_coin(ENGINE, self.game, self.match))
        flip.assert_not_called()
        self.assertEqual(self.match.tie_coin, "doom")
        # Not again at later turns: only a tie tosses it.
        self.game.coin_face = CoinFace.FORTUNE
        settle_tie_coin(ENGINE, self.game, self.match)
        self.assertEqual(self.match.tie_coin, "doom")

    def test_a_game_seated_without_a_toss_flips_it(self) -> None:
        self.game.coin_face = None
        with tossed(CoinFace.FORTUNE):
            settle_tie_coin(ENGINE, self.game, self.match)
        self.assertEqual(self.match.tie_coin, "fortune")

    def test_the_first_turn_says_the_coin_once(self) -> None:
        # The turn message shows the face; the turn's narration does not
        # repeat it.
        from d12ball.flow.turn import start_turn
        self.game.coin_face = CoinFace.DOOM
        self.match.select_ball_handler(self.handler)
        result = start_turn(ENGINE, self.game, self.match)
        said = " ".join(result.narration) + result.next.ask
        self.assertEqual(said.count("{coin:"), 1)
        self.assertIn("{coin:doom} **Doom**: defense wins ties.", said)

    def test_the_turn_message_shows_the_coin_once_flipped(self) -> None:
        self.assertNotIn("{coin:", ENGINE.build_turn_prompt(self.game, self.match))
        self.match.tie_coin = CoinFace.DOOM.value
        prompt = ENGINE.build_turn_prompt(self.game, self.match)
        self.assertIn("{coin:doom} **Doom**: defense wins ties.", prompt)
        self.game.edition = Edition.ONE
        self.assertNotIn("{coin:", ENGINE.build_turn_prompt(self.game, self.match))

    def test_one_point_oh_has_no_tie_coin(self) -> None:
        self.game.edition = Edition.ONE
        settle_tie_coin(ENGINE, self.game, self.match)
        self.assertIsNone(self.match.tie_coin)

    def test_the_board_is_drawn_with_the_coin(self) -> None:
        from d12ball.render import render_match_image
        self.match.tie_coin = CoinFace.FORTUNE.value
        png = render_match_image(
            self.match, ENGINE.player_catalog,
            tie_coin=("coin_gold_3_fortune", ENGINE.tie_coin_caption(self.match)),
        ).getvalue()
        self.assertTrue(png.startswith(b"\x89PNG"))
        self.assertEqual(ENGINE.tie_coin_caption(self.match), "Offense wins ties")

    # -- Saved -------------------------------------------------------------

    def test_saved_only_once_flipped(self) -> None:
        self.assertNotIn("tie_coin", self.match.to_dict())
        self.match.tie_coin = CoinFace.DOOM.value
        saved = self.match.to_dict()
        self.assertNotIn("tie_coin_owed", saved)
        restored = MatchState.from_dict(saved, ENGINE.basic_ruleset)
        self.assertEqual(restored.tie_coin, "doom")


if __name__ == "__main__":
    unittest.main()
