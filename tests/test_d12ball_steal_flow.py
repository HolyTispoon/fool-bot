"""
The two steals as one flow step, and the cog wrapper around it.

The model half of rank D2 of Phase 3 of docs/design/model-discord-split.md.
`tests/test_d12ball_steal_recording.py` asked the cog what a steal
says and does next, off `tests/steal_fixtures.py`, and was run green
before anything moved. This asks `d12ball.flow.effects.steal_step` the
same questions off the same fixtures -- so the two agreeing is the
move having changed nothing.

It also covers what the new shape adds and the old code had nowhere to
put:

- the step **does not save** (principle 9: a step mutates and returns,
  the caller writes it down), where the old code saved twice on one
  branch and once on the other,
- the cog wrapper saves **between** the step and the dispatch, which
  is the transition rule for Phases 2 to 5,
- the two follow-ons this rank is the first to name are real
  `FollowOnStep` members with rows in `driver.MODEL_STEPS`,
- a restart in the middle of the effect still comes back to the same
  prompt, which is the Phase 1 effect-choice branch catching it.
"""

from __future__ import annotations

import contextlib
import unittest
from types import SimpleNamespace
from unittest import mock

from d12ball.components import MatchState
from d12ball.flow import FollowOn, FollowOnStep
from d12ball.flow.effects import steal_step
from d12ball.prompts import pending_prompt

from d12ball.flow.arrivals import begin_shooter_choice
from d12ball.flow.turnovers import begin_run_back
from d12ball.flow import driver
from flow_stubs import (
    REAL_MODEL_STEPS,
    chain_records_at,
    driver_reaches_cog_stubs,
)
from save_patches import suppressed_cog_saves
from steal_fixtures import ENGINE, RUN_BACK, SHOOTER_CHOICE, STEAL_CASES
from test_d12ball_steal_recording import build_cog
from cog_steps import apply_steal


def run_step(fixture):
    """The step both cards share, asked directly."""
    return steal_step(ENGINE, fixture.match, fixture.key)


class StealStepTests(unittest.TestCase):
    """
    The step, asked directly. No cog, no interaction, no event loop --
    which is most of the point: a web app reaches this with the match
    it already holds.
    """

    def test_every_branch_answers_what_the_cog_recorded(self) -> None:
        for case in STEAL_CASES:
            with self.subTest(case=case.name):
                fixture = case.build()
                result = run_step(fixture)

                # The cog joins the lines on a single space, which is
                # how the narration reached the next step before.
                self.assertEqual(
                    " ".join(result.narration), fixture.narration,
                )
                self.assertEqual(result.board_changed, fixture.board_changed)

                self.assertIsInstance(result.next, FollowOn)
                self.assertEqual(result.next.step.name, fixture.follow_on)
                self.assertEqual(
                    dict(result.next.kwargs), fixture.follow_on_kwargs,
                )
                # The narration is the result's, never the follow-on's
                # -- how the two go together is the frontend's call.
                self.assertNotIn("lead_in", result.next.kwargs)

                match = fixture.match
                self.assertEqual(match.ball.possession, fixture.possession)
                self.assertEqual(match.ball.speed, fixture.ball_speed)
                self.assertEqual(match.ball_carrier_id, fixture.carrier_id)
                self.assertEqual(
                    (match.ball.zone, match.ball.space_index),
                    fixture.ball_space,
                )
                self.assertEqual(
                    match.board.meeple_position(fixture.challenger_id),
                    fixture.challenger_space,
                )
                self.assertEqual(
                    match.pending_effect_continuation, fixture.continuation,
                )

    def test_the_carry_is_the_whole_difference_between_the_cards(
        self,
    ) -> None:
        """
        One function and a sign. A Steal falls back toward the goal
        the thief defends and an Intercept carries the ball on toward
        the one they now attack -- read off `relative_flat_index`
        rather than a literal, since that is what the step itself
        uses.
        """
        for name, direction in (
            ("steal_plain", -1), ("intercept_plain", 1),
        ):
            with self.subTest(case=name):
                fixture = next(
                    case.build() for case in STEAL_CASES
                    if case.name == name
                )
                match = fixture.match
                start = match.board.flat_index(
                    *match.board.meeple_position(fixture.challenger_id)
                )
                taking_side = match.defending_side()

                run_step(fixture)

                self.assertEqual(
                    match.board.flat_index(
                        *match.board.meeple_position(fixture.challenger_id)
                    ),
                    match.relative_flat_index(start, taking_side, direction),
                )

    def test_the_two_endings_are_real_members_with_rows(self) -> None:
        """
        Rank D2 is the first hand-off into the spine proper, so it
        adds two `FollowOnStep` members -- and a member with no row in
        `driver.MODEL_STEPS` raises inside a resolved maneuver,
        one card at a time. The membership itself is asserted in
        `tests/test_d12ball_package_shape.py`; this is that the two
        this rank names are the two it recorded.
        """
        self.assertEqual(FollowOnStep.BEGIN_RUN_BACK.name, RUN_BACK)
        self.assertEqual(
            FollowOnStep.BEGIN_SHOOTER_CHOICE.name, SHOOTER_CHOICE,
        )
        # **Both rows are the driver's.** Phase 6 moved the shooter
        # choice into `d12ball.flow.driver` and then the run back too,
        # whose new play the dispatcher posts and pins off the result's
        # own `new_play`. The table covers the enum exactly -- asserted
        # in `tests/test_d12ball_package_shape.py`.
        self.assertIs(
            REAL_MODEL_STEPS[FollowOnStep.BEGIN_SHOOTER_CHOICE],
            begin_shooter_choice,
        )
        self.assertIs(
            REAL_MODEL_STEPS[FollowOnStep.BEGIN_RUN_BACK], begin_run_back,
        )

    def test_the_step_does_not_save(self) -> None:
        """
        The step may not write the match: the wrapper does, once,
        immediately after. `save_games` is replaced at its own module
        rather than at a binding, so an import added to the flow
        package later is caught too.

        This is the one rank where the old code saved a *different*
        number of times on different branches -- twice where a Skilled
        Pass was beaten, once otherwise.
        """
        recorder = mock.Mock()
        with suppressed_cog_saves(), mock.patch(
            "gamesaves.d12ball.storage.save_games", recorder,
        ):
            for case in STEAL_CASES:
                run_step(case.build())

        recorder.assert_not_called()

    def test_a_restart_mid_effect_comes_back_to_the_same_prompt(
        self,
    ) -> None:
        """
        The step leaves the match waiting on the run back (or on the
        shot), and a coach may take hours over it. What
        `pending_prompt` answers after a `to_dict`/`from_dict` round
        trip has to be what it answered before -- see "Recovering a
        stuck game" in docs/design/recovery.md.

        The continuation a beaten Skilled Pass records is part of what
        has to survive that trip, and it is not a field of its own:
        `pending_effect_continuation` is read back off the save like
        everything else.
        """
        for case in STEAL_CASES:
            with self.subTest(case=case.name):
                fixture = case.build()
                run_step(fixture)

                before = pending_prompt(ENGINE, fixture.game, fixture.match)
                restored = MatchState.from_dict(
                    fixture.match.to_dict(), ENGINE.basic_ruleset,
                )
                after = pending_prompt(ENGINE, fixture.game, restored)

                self.assertEqual(before.kind, after.kind)
                self.assertEqual(before.ask, after.ask)
                self.assertEqual(
                    restored.pending_effect_continuation,
                    fixture.continuation,
                )


class StealWrapperTests(unittest.IsolatedAsyncioTestCase):
    """
    `None` and `dispatch_step_result` -- the Discord
    half, which is now four lines and an ordering.
    """


if __name__ == "__main__":
    unittest.main()
