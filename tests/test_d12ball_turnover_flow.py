"""
The run back, asked of the model.

Phase 4 of docs/model-discord-split.md moves `begin_run_back`,
`continue_run_back`, `finish_run_back` and `begin_ball_recovery` out
of `cogs/d12ball/turnovers.py`. Two things about the shape are worth
asserting rather than only describing, and both are here:

- **the cascade is a generator**, because whether a pass needs a
  coach is only known once it has run, and a single `StepResult`
  could not say "these four placements happened and then somebody has
  to choose";
- **the loop's per-pass save stays**, which is the one named
  exception to principle 9. That one is asserted through the cog in
  `tests/test_d12ball_run_back_batching.py`, where the saving is.

See docs/design/possession-and-turnovers.md.
"""

from __future__ import annotations

import unittest

from d12ball.components import TeamSide
from d12ball.flow import FollowOnStep
from d12ball.flow.turnovers import (
    after_new_play_reset_step,
    ball_recovery_step,
    finish_run_back_step,
    run_back_announcement,
    run_back_passes,
    run_back_step,
)

from low_pass_fixtures import ENGINE, build_game, build_match, take_the_ball


class RunBackStepTests(unittest.TestCase):
    def build(self):
        game = build_game()
        match = build_match()
        take_the_ball(match)
        return game, match

    def test_a_turnover_under_last_possession_ends_the_period(
        self,
    ) -> None:
        game, match = self.build()
        match.scoreboard.last_possession = True

        result = run_back_step(ENGINE, game, match, turnover_occurred=True)

        self.assertIs(result.next.step, FollowOnStep.END_PERIOD)
        self.assertFalse(match.pending_run_back)

    def test_keeping_the_ball_runs_nobody_back(self) -> None:
        """
        Run backs belong to turnovers. Keeping the ball leaves whoever
        is out of position where they are, at no cost, and goes
        straight on to the clock.
        """
        game, match = self.build()

        result = run_back_step(
            ENGINE, game, match, distance_moved=3, turnover_occurred=False,
        )

        self.assertIs(
            result.next.step, FollowOnStep.FINISH_MANEUVER_RESOLUTION,
        )
        self.assertEqual(
            result.next.kwargs,
            {"distance_moved": 3, "turnover_occurred": False},
        )
        self.assertFalse(match.pending_run_back)

    def test_a_steal_arms_the_run_back_and_the_charge_up(self) -> None:
        game, match = self.build()
        carrier = match.eligible_ball_handlers()[0]
        match.ball_carrier_id = carrier

        result = run_back_step(
            ENGINE, game, match, distance_moved=2, speed_choice_after=True,
        )

        self.assertIs(result.next.step, FollowOnStep.ANNOUNCE_RUN_BACK)
        self.assertTrue(match.pending_run_back)
        self.assertEqual(match.pending_run_back_distance, 2)
        self.assertTrue(match.pending_run_back_speed_choice)
        self.assertTrue(match.pending_run_back_charge_up)
        # **The exemption is the carry, read from the other end.**
        self.assertEqual(
            match.pending_run_back_stays_player_id, carrier,
        )

    def test_a_new_play_exempts_nobody_and_opens_the_play(self) -> None:
        game, match = self.build()
        match.ball_carrier_id = match.eligible_ball_handlers()[0]

        result = run_back_step(ENGINE, game, match, new_play=True)

        self.assertIs(result.next.step, FollowOnStep.OPEN_NEW_PLAY)
        self.assertIsNone(match.pending_run_back_stays_player_id)
        # A new play is not a run back and triggers no charge-up.
        self.assertFalse(match.pending_run_back_charge_up)


class AfterNewPlayResetTests(unittest.TestCase):
    def build(self):
        game = build_game()
        match = build_match()
        take_the_ball(match)
        return game, match

    def test_a_side_with_a_window_left_gets_one(self) -> None:
        game, match = self.build()
        self.assertTrue(match.may_take_time_out(match.ball.possession))

        result = after_new_play_reset_step(ENGINE, game, match)

        self.assertIs(
            result.next.step, FollowOnStep.BEGIN_SUBSTITUTION_WINDOW,
        )
        self.assertEqual(
            result.next.kwargs, {"side": match.ball.possession},
        )

    def test_a_side_that_has_had_its_window_goes_straight_on(self) -> None:
        """
        Lifted exactly as it stood, and the predicate is the one the
        cog was reading: `may_take_time_out`, whose own docstring says
        it "no longer gates a new play's window". The two disagree --
        see the pull request; the behaviour is not this phase's to
        change.
        """
        game, match = self.build()
        match.time_outs_used = {match.ball.possession.value}

        result = after_new_play_reset_step(ENGINE, game, match)

        self.assertIs(result.next.step, FollowOnStep.ANNOUNCE_RUN_BACK)


class RunBackAnnouncementTests(unittest.TestCase):
    def test_nobody_displaced_says_only_the_speed(self) -> None:
        """
        Heading an empty run back "Players run back!" reads as a bug,
        and that is every new play: the reset put both sides back on
        their own arrangement.
        """
        game = build_game()
        match = build_match()
        take_the_ball(match)
        match.pending_run_back_turnover = True

        line = run_back_announcement(ENGINE, game, match)

        self.assertNotIn("Players run back!", line)
        self.assertEqual(line, "The ball speed goes down to **1**.")

    def test_a_burst_s_cost_does_not_claim_a_reset(self) -> None:
        game = build_game()
        match = build_match()
        take_the_ball(match)
        match.pending_run_back_turnover = True

        self.assertEqual(
            run_back_announcement(ENGINE, game, match, speed_reset=False),
            "",
        )


class FinishRunBackStepTests(unittest.TestCase):
    def build(self):
        game = build_game()
        match = build_match()
        take_the_ball(match)
        match.pending_run_back = True
        match.pending_run_back_distance = 2
        match.pending_run_back_turnover = True
        return game, match

    def test_the_ordinary_tail_is_the_clock(self) -> None:
        game, match = self.build()

        result = finish_run_back_step(ENGINE, game, match)

        self.assertFalse(match.pending_run_back)
        self.assertIs(
            result.next.step, FollowOnStep.FINISH_MANEUVER_RESOLUTION,
        )
        self.assertEqual(
            result.next.kwargs,
            {"distance_moved": 2, "turnover_occurred": True},
        )

    def test_a_pickup_still_owed_comes_first(self) -> None:
        game, match = self.build()
        match.pending_ball_recovery = True

        result = finish_run_back_step(ENGINE, game, match)

        self.assertIs(
            result.next.step, FollowOnStep.BEGIN_BALL_RECOVERY,
        )

    def test_a_steal_s_speed_choice_is_offered_after_everyone_is_back(
        self,
    ) -> None:
        game, match = self.build()
        thief = match.eligible_ball_handlers()[0]
        match.pending_run_back_speed_choice = True
        match.pending_run_back_stays_player_id = thief

        result = finish_run_back_step(ENGINE, game, match)

        self.assertIs(result.next.step, FollowOnStep.OFFER_SPEED_CHOICE)
        self.assertEqual(result.next.kwargs["player_id"], thief)
        self.assertEqual(result.next.kwargs["skill_type"], "defense")
        self.assertFalse(match.pending_run_back_speed_choice)


class BallRecoveryStepTests(unittest.TestCase):
    def build(self):
        game = build_game()
        match = build_match()
        take_the_ball(match)
        match.pending_ball_recovery = True
        return game, match

    def test_somebody_of_theirs_already_on_it_asks_nobody(self) -> None:
        game, match = self.build()
        self.assertTrue(match.eligible_ball_handlers())

        result = ball_recovery_step(ENGINE, game, match)

        self.assertFalse(match.pending_ball_recovery)
        self.assertIs(
            result.next.step, FollowOnStep.FINISH_MANEUVER_RESOLUTION,
        )

    def test_an_empty_space_is_the_coach_s_pickup(self) -> None:
        game, match = self.build()
        for player_id in list(match.board.spaces[match.ball.zone][
            match.ball.space_index
        ]):
            match.board.remove_meeple(player_id)

        result = ball_recovery_step(ENGINE, game, match)

        self.assertIs(result.next.step, FollowOnStep.ASK_BALL_RECOVERY)
        self.assertTrue(match.pending_ball_recovery)


class RunBackCascadeTests(unittest.TestCase):
    """
    The generator, and the one thing only its shape can be asked: that
    a pass that needs a coach ends it.
    """

    def build(self):
        game = build_game()
        match = build_match()
        take_the_ball(match)
        match.pending_run_back = True
        match.pending_run_back_distance = 1
        match.pending_run_back_turnover = True
        return game, match

    def test_a_settled_board_yields_nothing(self) -> None:
        game, match = self.build()

        self.assertEqual(
            list(run_back_passes(ENGINE, game, match, 60)), [],
        )

    def test_a_coach_s_question_ends_the_cascade(self) -> None:
        """
        And it is the last thing yielded: whatever the generator does
        afterwards, nothing is placed behind a question a coach has
        not answered.
        """
        game, match = self.build()
        # Displace somebody, so a question is owed.
        side = TeamSide.HOME
        mover = match.setup_for_side(side).field_players[0]
        zone = match.setup_for_side(side).assigned_zone(mover)
        elsewhere = next(
            other for other in match.board.spaces
            if other is not zone
        )
        match.board.remove_meeple(mover)
        match.board.place_meeple(mover, elsewhere, 0)

        results = list(run_back_passes(ENGINE, game, match, 60))

        asking = [
            result for result in results
            if result.next is not None
        ]
        if asking:
            self.assertIs(
                asking[0].next.step, FollowOnStep.ASK_RUN_BACK,
            )
            self.assertIs(asking[0], results[-1])

    def test_the_pass_bound_is_honoured(self) -> None:
        """
        As a recursion the interpreter bounded this; as a generator a
        number does, and a spin would hang the event loop for every
        game at once.
        """
        game, match = self.build()

        self.assertLessEqual(
            len(list(run_back_passes(ENGINE, game, match, 3))), 3,
        )


if __name__ == "__main__":
    unittest.main()
