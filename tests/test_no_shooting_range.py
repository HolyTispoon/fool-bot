"""
D12 Ball 2.0 has no shooting range (docs/rules-2.1.md section 6): a
shot may be taken from anywhere, and a time out may be called on any
turn, once a half and not after last possession. 1.0 is untouched.
`RulesEngine.can_attempt_score` and `may_call_time_out` are the one
reading of each; see docs/design/maneuver-deck.md, "No shooting range".
"""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from d12ball.components import TeamSide, Zone, kickoff_space_index
from d12ball.flow.turn import turn_action_refusal
from d12ball.game import Edition, GameMode

from cogs.d12ball_views import PlayerActionView
from flow_stubs import driver_reaches_cog_stubs
from test_d12ball_shooting_range import build_cog, build_game as range_game
from test_d12ball_species_abilities import (
    build_engine,
    build_game,
    build_match,
)

ENGINE = build_engine()


class NoShootingRangeTests(unittest.TestCase):

    def stage(self, edition: Edition, side: TeamSide = TeamSide.HOME):
        game = build_game(mode=GameMode.TRAINING)
        game.edition = edition
        match = build_match(ENGINE, game)
        match.ball.possession = side
        match.ball.zone = Zone.MIDFIELD
        match.ball.space_index = kickoff_space_index(
            len(match.board.spaces[Zone.MIDFIELD]), side,
        )
        return game, match

    def put_ball_in_old_range(self, match) -> None:
        # The far end of the zone home attacks: in home's range in 1.0.
        match.ball.zone = Zone.VISITORS_ZONE
        match.ball.space_index = len(match.board.spaces[Zone.VISITORS_ZONE]) - 1

    def test_the_range_applies_in_one_and_not_in_two(self) -> None:
        for edition, applies in ((Edition.ONE, True), (Edition.TWO, False)):
            game, _ = self.stage(edition)
            with self.subTest(edition=edition):
                self.assertEqual(ENGINE.shooting_range_applies(game), applies)

    def test_a_shot_is_on_from_the_kickoff_space_in_two_alone(self) -> None:
        for side in TeamSide:
            for edition, may in ((Edition.ONE, False), (Edition.TWO, True)):
                game, match = self.stage(edition, side)
                with self.subTest(side=side, edition=edition):
                    self.assertEqual(ENGINE.can_attempt_score(game, match), may)
                    refusal = turn_action_refusal(ENGINE, game, match, "shoot")
                    self.assertEqual(refusal is None, may)

    def test_a_shot_is_on_from_a_side_own_end_in_two(self) -> None:
        game, match = self.stage(Edition.TWO)
        match.ball.zone = Zone.HOME_ZONE
        match.ball.space_index = 0
        self.assertTrue(ENGINE.can_attempt_score(game, match))
        self.assertTrue(ENGINE.can_attempt_score(game, match, TeamSide.HOME))

    def test_a_time_out_may_be_called_where_one_could_shoot_in_two(self) -> None:
        for edition, may in ((Edition.ONE, False), (Edition.TWO, True)):
            game, match = self.stage(edition)
            self.put_ball_in_old_range(match)
            with self.subTest(edition=edition):
                self.assertTrue(ENGINE.can_attempt_score(game, match))
                self.assertEqual(ENGINE.may_call_time_out(game, match), may)
                refusal = turn_action_refusal(ENGINE, game, match, "time_out")
                self.assertEqual(refusal is None, may)

    def test_a_time_out_in_two_keeps_its_other_two_conditions(self) -> None:
        game, match = self.stage(Edition.TWO)
        self.assertTrue(ENGINE.may_call_time_out(game, match))

        match.scoreboard.last_possession = True
        self.assertFalse(ENGINE.may_call_time_out(game, match))
        match.scoreboard.last_possession = False

        match.time_outs_used.add(TeamSide.HOME.value)
        self.assertFalse(ENGINE.may_call_time_out(game, match))

    def test_the_turn_prompt_offers_every_action_in_two(self) -> None:
        game, match = self.stage(Edition.TWO)
        handler = match.home.field_players[0]
        match.move_meeple(handler, match.ball.zone, match.ball.space_index)
        match.select_ball_handler(handler)
        self.assertIn(
            "Choose an action:", ENGINE.build_turn_prompt(game, match),
        )


class NoShootingRangeButtonTests(unittest.IsolatedAsyncioTestCase):
    """The turn's buttons on Discord, built off the prompt's options:
    at the kickoff space a 2.0 side is offered the shot and the time
    out together, where 1.0 offers the time out alone."""

    def buttons(self, edition: Edition) -> list[str]:
        cog = build_cog()
        self.enterContext(driver_reaches_cog_stubs(cog))
        game = range_game()
        game.edition = edition
        match = cog.engine.initialize_standard_match(game)
        match.ball.possession = TeamSide.HOME
        match.ball.zone = Zone.MIDFIELD
        match.ball.space_index = kickoff_space_index(
            len(match.board.spaces[Zone.MIDFIELD]), TeamSide.HOME,
        )
        handler = match.home.field_players[0]
        match.move_meeple(handler, match.ball.zone, match.ball.space_index)
        match.select_ball_handler(handler)
        game.match_state = match.to_dict()
        cog.games[game.game_id] = game
        return [item.label for item in PlayerActionView(cog, game.game_id).children]

    async def test_the_shot_and_the_time_out_are_both_offered_in_two(self) -> None:
        self.assertEqual(
            self.buttons(Edition.TWO), ["Maneuver", "Shoot to score", "Time out"],
        )
        self.assertEqual(self.buttons(Edition.ONE), ["Maneuver", "Time out"])


if __name__ == "__main__":
    unittest.main()
