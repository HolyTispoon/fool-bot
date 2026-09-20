"""
What the cog's Steal and Intercept say and do next, recorded off the
old code.

This is the equivalence half of rank D2 of Phase 3 of
docs/model-discord-split.md. It drives `D12Ball.apply_steal` over
`tests/steal_fixtures.py` and asserts the narration byte for byte,
whether the board moved, and which step the resolution hands the turn
to with which arguments -- the four things a `StepResult` carries --
plus where the ball and the thief ended up and what the turnover left
recorded on the match.

**It was written and run green before the move**, which is what makes
it evidence: `tests/test_d12ball_steal_flow.py` asks the model the
same questions off the same fixtures, so the two agreeing afterwards
is the move having changed nothing rather than new code agreeing with
itself. `tests/dribble_fixtures.py` with
`tests/test_d12ball_dribble_recording.py` is rank O2's copy of the
same shape.

The narration is read out of the follow-on's `lead_in` rather than off
a message, because a steal posts nothing of its own: what it says is
the opening of the run-back announcement (or of the scoring
opportunity, where the interceptor ran out of field). Keeping it that
way is also what keeps the move from costing a Discord request -- see
"Discord's rate limits" in docs/design/rate-limits.md.

**The follow-on's arguments are read through the real method's
signature**, not off `call.args`. The old cog hands
`begin_shooter_choice` its candidate list positionally where a
`FollowOn` names it, so binding the recorded call to
`inspect.signature` is what lets one table answer for both halves --
and it is a reading of the cog's own parameter names rather than of
this module's guess at them.
"""

from __future__ import annotations

import inspect
import unittest
from types import SimpleNamespace
from unittest import mock

from cogs.d12ball import D12Ball
from d12ball.ai import build_ai_strategies
from d12ball.cards import maneuver_hand_combinations
from d12ball.components import (
    MANEUVER_TIER_GAMBIT,
    MANEUVER_TIER_BASIC,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.engine import RulesEngine

from flow_stubs import driver_reaches_cog_stubs
from save_patches import suppressed_cog_saves
from steal_fixtures import RUN_BACK, SHOOTER_CHOICE, STEAL_CASES

#: The parameters every follow-on takes and no fixture records: the
#: three the cog threads through everything and the narration, which
#: is the result's rather than the follow-on's.
PLUMBING = ("self", "interaction", "game", "match", "lead_in")


def build_cog() -> D12Ball:
    """
    A cog with the engine it really uses and mocks where Discord would
    be. Both follow-ons are `AsyncMock`s because what they were
    *called with* is the whole assertion.
    """
    cog = object.__new__(D12Ball)
    cog.games = {}
    cog.player_catalog = load_player_catalog()
    cog.maneuver_catalog = load_maneuver_catalog()
    cog.basic_ruleset = load_basic_ruleset()
    cog.coin_emojis = {}
    cog.ai_strategies = build_ai_strategies(
        cog.player_catalog, cog.maneuver_catalog,
    )
    cog.engine = RulesEngine(
        cog.player_catalog,
        cog.basic_ruleset,
        cog.maneuver_catalog,
        cog.ai_strategies,
    )
    cog.refresh_match_image = mock.AsyncMock()
    cog.begin_run_back = mock.AsyncMock()
    cog.begin_shooter_choice = mock.AsyncMock()
    cog.maneuver_hand_image_bytes = {
        hands: b"" for hands in maneuver_hand_combinations()
    }
    return cog


def named_arguments(method, call) -> dict:
    """
    One recorded call as named arguments, plumbing dropped.

    Bound against the unbound method's signature and **without**
    `apply_defaults`, so what comes back is what the call actually
    passed -- which is exactly what a `FollowOn` carries in its
    `kwargs`.
    """
    bound = inspect.signature(method).bind(
        None, *call.args, **call.kwargs,
    )
    return {
        name: value
        for name, value in bound.arguments.items()
        if name not in PLUMBING
    }


class StealRecordingTests(unittest.IsolatedAsyncioTestCase):
    """
    One subtest per branch, each reading the fixture table's own
    answer. A branch that stops matching here is a branch whose
    wording or whose next step changed, which is a rules-visible
    change and not a refactor.
    """

    async def test_every_branch_says_and_dispatches_what_it_recorded(
        self,
    ) -> None:
        for case in STEAL_CASES:
            with self.subTest(case=case.name):
                await self._check(case)

    async def _check(self, case) -> None:
        fixture = case.build()
        cog = build_cog()
        self.enterContext(driver_reaches_cog_stubs(cog))
        cog.games[fixture.game.game_id] = fixture.game
        match = fixture.match

        with suppressed_cog_saves():
            await cog.apply_steal(
                SimpleNamespace(), fixture.game, match, fixture.key,
            )

        if fixture.follow_on == RUN_BACK:
            taken, method = cog.begin_run_back, D12Ball.begin_run_back
            cog.begin_shooter_choice.assert_not_awaited()
        else:
            self.assertEqual(fixture.follow_on, SHOOTER_CHOICE)
            taken, method = (
                cog.begin_shooter_choice, D12Ball.begin_shooter_choice,
            )
            cog.begin_run_back.assert_not_awaited()

        taken.assert_awaited_once()
        call = taken.await_args
        self.assertEqual(call.kwargs["lead_in"], fixture.narration)
        self.assertEqual(
            named_arguments(method, call), fixture.follow_on_kwargs,
        )

        # Every branch moves a meeple and the ball with it, so the
        # persistent board message is redrawn. The flag is carried
        # anyway because a step that moves nothing is the reason
        # `StepResult` has it.
        self.assertEqual(
            cog.refresh_match_image.await_count,
            1 if fixture.board_changed else 0,
        )

        self.assertEqual(match.ball.possession, fixture.possession)
        self.assertEqual(match.ball.speed, fixture.ball_speed)
        self.assertEqual(match.ball_carrier_id, fixture.carrier_id)
        self.assertEqual(
            (match.ball.zone, match.ball.space_index), fixture.ball_space,
        )
        self.assertEqual(
            match.board.meeple_position(fixture.challenger_id),
            fixture.challenger_space,
        )
        self.assertEqual(
            match.pending_effect_continuation, fixture.continuation,
        )


if __name__ == "__main__":
    unittest.main()
