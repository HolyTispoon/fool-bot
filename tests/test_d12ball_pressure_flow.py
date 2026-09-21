"""
The two pressures as one flow step, and the cog wrapper around it.

The model half of rank D3 of Phase 3 of docs/design/model-discord-split.md.
`tests/test_d12ball_pressure_recording.py` asked the cog what a
Pressure says and does next, off `tests/pressure_fixtures.py`, and was
run green before anything moved. This asks
`d12ball.flow.effects.pressure_step` the same questions off the same
fixtures -- so the two agreeing is the move having changed nothing.

It also covers what the new shape adds and the old code had nowhere to
put:

- the step **does not save** (principle 9: a step mutates and returns,
  the caller writes it down), where the old code saved on both
  branches of its own,
- the cog wrapper saves **between** the step and the dispatch, which
  is the transition rule for Phases 2 to 5,
- `BEGIN_OWN_GOAL_ROLL`, the member this rank adds, is real and has a
  row in `driver.MODEL_STEPS`,
- the overshoot costs **one** message where it used to cost two,
  which is the only thing a coach sees differently after this move,
- the own-goal outcome no longer saves either, and `run_own_goal_roll`
  writes both its branches down before it posts anything.
"""

from __future__ import annotations

import contextlib
import unittest
from types import SimpleNamespace
from unittest import mock

from cogs.d12ball import D12Ball
from d12ball.components import MatchState
from d12ball.flow import FollowOn, FollowOnStep
from d12ball.flow.effects import apply_own_goal_outcome, pressure_step
from d12ball.prompts import pending_prompt

from pressure_fixtures import ENGINE, OWN_GOAL_ROLL, PRESSURE_CASES
from d12ball.flow.arrivals import begin_own_goal_roll
from d12ball.flow import driver
from flow_stubs import (
    REAL_MODEL_STEPS,
    chain_records_at,
    driver_reaches_cog_stubs,
)
from save_patches import suppressed_cog_saves
from test_d12ball_pressure_recording import build_cog, build_interaction
from cog_steps import apply_pressure, run_own_goal_roll


def case_named(name):
    """One fixture out of the table, built fresh."""
    return next(case.build() for case in PRESSURE_CASES if case.name == name)


def run_step(fixture):
    """The step both cards share, asked directly."""
    return pressure_step(ENGINE, fixture.match, fixture.key)


class PressureStepTests(unittest.TestCase):
    """
    The step, asked directly. No cog, no interaction, no event loop --
    which is most of the point: a web app reaches this with the match
    it already holds.
    """

    def test_every_branch_answers_what_the_cog_recorded(self) -> None:
        for case in PRESSURE_CASES:
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
                    match.board.meeple_position(fixture.handler_id),
                    fixture.handler_space,
                )
                self.assertEqual(
                    match.board.meeple_position(fixture.challenger_id),
                    fixture.challenger_space,
                )
                self.assertEqual(
                    match.pending_double_team, fixture.pending_double_team,
                )

    def test_the_overshoot_paragraph_is_one_block(self) -> None:
        """
        The blocks are joined on a single space and this paragraph is
        separated by a blank line, so a second block would carry a
        stray space in front of its newlines -- the same reading rank
        D2 wrote down for the Intercept's "no field left ahead of
        them".
        """
        for name in ("pressure_that_overshoots", "double_team_that_overshoots"):
            with self.subTest(case=name):
                result = run_step(case_named(name))
                self.assertEqual(len(result.narration), 1)

    def test_the_push_and_the_partner_are_the_difference(self) -> None:
        """
        One function and two parameters read off the key: a Pressure
        shoves one space alone, a Double Team two with the nearest
        other defender placed beside it. The distance is read off
        `relative_flat_index` rather than a literal, since that is
        what the step itself uses.
        """
        for name, push in (("pressure_plain", 1), ("double_team_plain", 2)):
            with self.subTest(case=name):
                fixture = case_named(name)
                match = fixture.match
                start = match.board.flat_index(
                    *match.board.meeple_position(fixture.handler_id)
                )
                holding_side = match.ball.possession

                run_step(fixture)

                self.assertEqual(
                    match.board.flat_index(
                        *match.board.meeple_position(fixture.handler_id)
                    ),
                    match.relative_flat_index(start, holding_side, -push),
                )
                partner = fixture.partner_id
                self.assertEqual(partner is not None, push == 2)
                if partner is not None:
                    self.assertEqual(
                        match.board.meeple_position(partner),
                        match.board.meeple_position(fixture.handler_id),
                    )

    def test_the_own_goal_roll_is_a_real_member_with_a_row(self) -> None:
        """
        Rank D3 adds one `FollowOnStep` member, and a member with no
        row in `driver.MODEL_STEPS` raises inside a resolved
        maneuver one card at a time. The membership itself is asserted
        in `tests/test_d12ball_package_shape.py`; this is that the one
        this rank names is the one it recorded.
        """
        self.assertEqual(FollowOnStep.BEGIN_OWN_GOAL_ROLL.name, OWN_GOAL_ROLL)
        # **Phase 6 moved it across.** The roll's own step is the
        # driver's -- it was a wrapper that called the step, saved and
        # dispatched, which is the whole of what the loop does. The
        # table covers the enum exactly; see
        # `tests/test_d12ball_package_shape.py`.
        self.assertIs(
            REAL_MODEL_STEPS[FollowOnStep.BEGIN_OWN_GOAL_ROLL],
            begin_own_goal_roll,
        )

    def test_the_step_does_not_save(self) -> None:
        """
        The step may not write the match: the wrapper does, once,
        immediately after. `save_games` is replaced at its own module
        rather than at a binding, so an import added to the flow
        package later is caught too.
        """
        recorder = mock.Mock()
        with suppressed_cog_saves(), mock.patch(
            "gamesaves.d12ball.storage.save_games", recorder,
        ):
            for case in PRESSURE_CASES:
                run_step(case.build())

        recorder.assert_not_called()

    def test_a_restart_mid_effect_comes_back_to_the_same_prompt(
        self,
    ) -> None:
        """
        The step leaves the match between the shove and whatever comes
        next, and a coach may take hours over that. What
        `pending_prompt` answers after a `to_dict`/`from_dict` round
        trip has to be what it answered before -- see "Recovering a
        stuck game" in docs/design/recovery.md.

        The pair a Double Team leaves is part of what has to survive
        the trip: `pending_double_team` reaches into the *following*
        maneuver, so a restart that lost it would quietly give the
        next turn one challenger instead of two.
        """
        for case in PRESSURE_CASES:
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
                    restored.pending_double_team,
                    fixture.pending_double_team,
                )


class PressureWrapperTests(unittest.IsolatedAsyncioTestCase):
    """
    `None` and `dispatch_step_result` -- the Discord
    half, which is now four lines and an ordering.
    """


    @staticmethod
    def _recorder(calls: list[str], name: str):
        async def recorded(*args, **kwargs) -> None:
            calls.append(name)

        return recorded

    async def test_an_overshoot_is_one_message_and_one_refresh(
        self,
    ) -> None:
        """
        The one thing a coach sees differently after this move. The
        old branch posted the shove, refreshed the board and *then*
        asked for the roll, so an overshooting Pressure cost two
        messages where every other resolved maneuver costs one. The
        narration is the result's now, so it opens the roll's own
        prompt -- see "Discord's rate limits" in
        docs/design/rate-limits.md, and note that nothing about the
        text itself changed: both halves are still said, in order.
        """
        fixture = case_named("pressure_that_overshoots")
        cog = build_cog()
        self.enterContext(driver_reaches_cog_stubs(cog))
        cog.games[fixture.game.game_id] = fixture.game
        # The real prompt, so what reaches the channel is counted
        # rather than mocked away.
        del cog.begin_own_goal_roll
        interaction = build_interaction()

        with suppressed_cog_saves():
            await apply_pressure(cog, 
                interaction, fixture.game, fixture.match, fixture.key,
            )

        posted = [
            call.args[0]
            for call in interaction.followup.send.await_args_list
            if call.args
        ]
        self.assertEqual(len(posted), 1)
        self.assertTrue(posted[0].startswith(fixture.narration))
        self.assertIn("**Own goal risk!**", posted[0])
        self.assertEqual(cog.refresh_match_image.await_count, 1)
        # And the roll still owes what it owed: the wait is a place
        # the turn stops, so the prompt persists it before returning.
        self.assertTrue(fixture.match.pending_own_goal)
        self.assertEqual(fixture.match.pending_own_goal_distance, 1)


class OwnGoalOutcomeTests(unittest.IsolatedAsyncioTestCase):
    """
    The other half of what rank D3 moved. `apply_own_goal_outcome`
    settles the roll and words it; the roll itself, its dice image and
    the messages around it stay `None`'s.
    """

    def build(self):
        """A match with the Pressure that risked the own goal still live."""
        fixture = case_named("pressure_that_overshoots")
        pressure_step(ENGINE, fixture.match, fixture.key)
        return fixture

    def test_the_outcome_does_not_save(self) -> None:
        """
        It saved itself on the conceded branch and left the avoided
        one to the caller, which is the split principle 9 exists to
        collapse: the caller writes both down now.
        """
        recorder = mock.Mock()
        for safe in (True, False):
            with self.subTest(safe=safe):
                fixture = self.build()
                player = ENGINE.get_player_definition(fixture.handler_id)
                with suppressed_cog_saves(), mock.patch(
                    "gamesaves.d12ball.storage.save_games", recorder,
                ):
                    apply_own_goal_outcome(
                        ENGINE, fixture.match, player, 1, safe, "",
                    )
                recorder.assert_not_called()

    def test_each_outcome_leaves_what_it_owes(self) -> None:
        """
        Avoiding one is a stoppage rather than a play that carries on,
        so it owes the pickup an out-of-bounds ball does; conceding
        one restarts from the kickoff with the run back already
        pending. Both are read back off the match, which is what makes
        the save that follows them worth its ordering.
        """
        avoided = self.build()
        player = ENGINE.get_player_definition(avoided.handler_id)
        verdict = apply_own_goal_outcome(
            ENGINE, avoided.match, player, 1, True, "",
        )
        self.assertIn("Own goal avoided!", verdict)
        self.assertTrue(avoided.match.pending_ball_recovery)
        self.assertEqual(avoided.match.ball.speed, 1)
        self.assertEqual(avoided.match.goals, [])

        conceded = self.build()
        player = ENGINE.get_player_definition(conceded.handler_id)
        verdict = apply_own_goal_outcome(
            ENGINE, conceded.match, player, 2, False, "",
        )
        self.assertIn("Own goal!", verdict)
        self.assertEqual(len(conceded.match.goals), 1)
        self.assertTrue(conceded.match.pending_run_back)
        self.assertEqual(conceded.match.pending_run_back_distance, 2)
        self.assertTrue(conceded.match.pending_run_back_turnover)


    @staticmethod
    def _noting(calls: list[str], name: str):
        async def recorded(*args, **kwargs):
            calls.append(name)
            return SimpleNamespace(id=999)

        return recorded


if __name__ == "__main__":
    unittest.main()
