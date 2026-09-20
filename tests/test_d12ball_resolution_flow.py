"""
The tail of a maneuver, asked of the model.

Phase 4 of docs/model-discord-split.md moves
`finish_maneuver_resolution`'s decisions out of
`cogs/d12ball/periods.py`: the two arrival gates, the loose-ball
check, the clock, and the choice between ending the period and
handing the turn back.

**What this file is really guarding is the message boundary.** The
old flow said two things in two messages when the clock reached the
period's last minute -- the notice, and then the position with the
board under it -- and a `StepResult`'s narration blocks are one
message by contract. So the step ends on the notice and names
`ANNOUNCE_LAST_POSSESSION`, and the assertions below are what stops
a later simplification quietly joining them. See principle 8 in
CLAUDE.md.
"""

from __future__ import annotations

import unittest

from d12ball.components import MatchState
from d12ball.flow import FollowOnStep
from d12ball.flow.resolution import (
    finish_maneuver_resolution_step,
    hand_back_the_turn_line,
)

from low_pass_fixtures import ENGINE, build_game, build_match, take_the_ball


class FinishManeuverResolutionStepTests(unittest.TestCase):
    def build(self):
        game = build_game()
        match = build_match()
        take_the_ball(match)
        return game, match

    def test_an_ordinary_tail_advances_the_clock_and_hands_back(
        self,
    ) -> None:
        game, match = self.build()
        before = match.scoreboard.time

        result = finish_maneuver_resolution_step(
            ENGINE, game, match, distance_moved=2,
        )

        self.assertEqual(match.scoreboard.time, before + 2)
        self.assertIs(result.next.step, FollowOnStep.HAND_BACK_THE_TURN)
        self.assertEqual(result.next.kwargs, {"distance_moved": 2})
        # The maneuver state is cleared before the turn goes back.
        self.assertIsNone(match.offense_maneuver)
        self.assertIsNone(match.challenger_id)

    def test_the_caller_s_lead_in_rides_on_what_comes_next(self) -> None:
        game, match = self.build()

        result = finish_maneuver_resolution_step(
            ENGINE, game, match, lead_in="**Low Pass:** two spaces.",
        )

        self.assertEqual(result.narration, ["**Low Pass:** two spaces."])

    def test_an_empty_landing_space_detours_into_the_loose_ball(
        self,
    ) -> None:
        """
        And the clock does **not** move: the loose ball re-enters this
        step once it is settled, and a maneuver is charged once.
        """
        game, match = self.build()
        for player_id in list(match.board.spaces[match.ball.zone][
            match.ball.space_index
        ]):
            match.board.remove_meeple(player_id)
        before = match.scoreboard.time

        result = finish_maneuver_resolution_step(
            ENGINE, game, match, distance_moved=2, lead_in="Said already.",
        )

        self.assertEqual(match.scoreboard.time, before)
        self.assertIs(result.next.step, FollowOnStep.BEGIN_LOOSE_BALL)
        self.assertEqual(result.narration, ["Said already."])

    def test_the_last_minute_is_its_own_announcement(self) -> None:
        """
        The one place a step says something and then something else
        has to be said in a message of its own. If this ever comes
        back as `HAND_BACK_THE_TURN` with two narration blocks, the
        two messages have become one and a coach reads "this is now
        last possession" inside a board caption.
        """
        game, match = self.build()
        match.scoreboard.time = match.scoreboard.last_minute - 1

        result = finish_maneuver_resolution_step(
            ENGINE, game, match, distance_moved=1, lead_in="The pass.",
        )

        self.assertIs(
            result.next.step, FollowOnStep.ANNOUNCE_LAST_POSSESSION,
        )
        self.assertEqual(len(result.narration), 1)
        self.assertIn("last possession", result.narration[0])
        # The caller's lines open it, with a blank line between: one
        # message, so the model words it.
        self.assertTrue(result.narration[0].startswith("The pass.\n\n"))
        # And the maneuver is still cleared -- the turn is handed back
        # from the same state as any other.
        self.assertIsNone(match.offense_maneuver)

    def test_a_turnover_under_last_possession_ends_the_period(
        self,
    ) -> None:
        game, match = self.build()
        match.scoreboard.last_possession = True

        result = finish_maneuver_resolution_step(
            ENGINE, game, match, distance_moved=1, turnover_occurred=True,
        )

        self.assertIs(result.next.step, FollowOnStep.END_PERIOD)

    def test_the_maneuver_that_declares_it_plays_on(self) -> None:
        """
        Last possession is the possession that starts at the last
        minute, so the turnover that gets there does not end the
        period -- whoever came out of it with the ball plays it out.
        """
        game, match = self.build()
        match.scoreboard.time = match.scoreboard.last_minute - 1

        result = finish_maneuver_resolution_step(
            ENGINE, game, match, distance_moved=1, turnover_occurred=True,
        )

        self.assertIs(
            result.next.step, FollowOnStep.ANNOUNCE_LAST_POSSESSION,
        )
        self.assertIn(
            "came out of that maneuver with the ball",
            result.narration[0],
        )


class HandBackTheTurnLineTests(unittest.TestCase):
    """
    The sentence under the settled board. It is wording over the
    position, so it is the model's even though the message it goes in
    carries an image.
    """

    def test_it_names_the_space_the_side_and_the_clock(self) -> None:
        match = build_match()
        take_the_ball(match)
        match.scoreboard.time = 7

        line = hand_back_the_turn_line(match, 3)

        self.assertIn("Ball is now", line)
        self.assertIn("has possession", line)
        self.assertIn("Time has advanced 3, now at 07.", line)


if __name__ == "__main__":
    unittest.main()
