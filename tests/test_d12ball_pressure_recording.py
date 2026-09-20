"""
What the cog's Pressure and Double Team say and do next, recorded off
the old code.

This is the equivalence half of rank D3 of Phase 3 of
docs/model-discord-split.md. It drives `D12Ball.apply_pressure` over
`tests/pressure_fixtures.py` and asserts the narration byte for byte,
whether the board moved, and which step the resolution hands the turn
to with which arguments -- the four things a `StepResult` carries --
plus where the handler, the ball and the defenders ended up, and the
pair a Double Team leaves challenging the next maneuver.

**It was written and run green before the move**, which is what makes
it evidence: `tests/test_d12ball_pressure_flow.py` asks the model the
same questions off the same fixtures, so the two agreeing afterwards
is the move having changed nothing rather than new code agreeing with
itself. `tests/steal_fixtures.py` with
`tests/test_d12ball_steal_recording.py` is rank D2's copy of the same
shape.

**The narration is read off whichever thing carried it**, because
this rank is the one where that changes. On six of the eight branches
it is the follow-on's `lead_in` and a pressure posts nothing of its
own; on the two overshoots the old cog posted the shove as a message
and then asked for the own-goal roll separately, so the branch cost
two messages where every other resolved maneuver costs one. Accepting
either is what lets one table answer for the shape before the move and
the shape after it -- the trick rank D2 used on `inspect.signature`,
applied to a message rather than to an argument. Which of the two
carried it is asserted, so the branch cannot quietly start doing both.

**The follow-on's arguments are read through the real method's
signature**, not off `call.args`, for the reason rank D2 wrote down:
the old cog hands some of them positionally where a `FollowOn` names
them.
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
    MANEUVER_TIER_BASIC,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.engine import RulesEngine

from pressure_fixtures import (
    FINISH,
    OWN_GOAL_ROLL,
    PRESSURE_CASES,
    RUN_BACK,
)
from save_patches import suppressed_cog_saves

#: The parameters every follow-on takes and no fixture records: the
#: three the cog threads through everything and the narration, which
#: is the result's rather than the follow-on's.
PLUMBING = ("self", "interaction", "game", "match", "lead_in")


def build_cog() -> D12Ball:
    """
    A cog with the engine it really uses and mocks where Discord would
    be. All three follow-ons are `AsyncMock`s because what they were
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
    cog.finish_maneuver_resolution = mock.AsyncMock()
    cog.begin_run_back = mock.AsyncMock()
    cog.begin_own_goal_roll = mock.AsyncMock()
    cog.maneuver_hand_image_bytes = {
        hands: b"" for hands in maneuver_hand_combinations()
    }
    return cog


def build_interaction() -> SimpleNamespace:
    """
    One mock behind both post routes, so "what this posted" reads back
    the same whether it went through the followup or the channel --
    which is `send_new_prompt`'s own choice and nothing this table
    cares about.
    """
    send = mock.AsyncMock(return_value=SimpleNamespace(id=999))
    return SimpleNamespace(
        user=SimpleNamespace(id=111, display_name="One"),
        channel=SimpleNamespace(send=send),
        guild=None,
        followup=SimpleNamespace(send=send),
        response=SimpleNamespace(
            defer=mock.AsyncMock(),
            edit_message=mock.AsyncMock(),
            send_message=mock.AsyncMock(),
            is_done=lambda: True,
        ),
        edit_original_response=mock.AsyncMock(),
    )


def posted_messages(interaction) -> list[str]:
    """Every message the resolution posted on its own account."""
    return [
        call.args[0]
        for call in interaction.followup.send.await_args_list
        if call.args
    ]


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


FOLLOW_ONS = {
    FINISH: ("finish_maneuver_resolution", D12Ball.finish_maneuver_resolution),
    RUN_BACK: ("begin_run_back", D12Ball.begin_run_back),
    OWN_GOAL_ROLL: ("begin_own_goal_roll", D12Ball.begin_own_goal_roll),
}


class PressureRecordingTests(unittest.IsolatedAsyncioTestCase):
    """
    One subtest per branch, each reading the fixture table's own
    answer. A branch that stops matching here is a branch whose
    wording or whose next step changed, which is a rules-visible
    change and not a refactor.
    """

    async def test_every_branch_says_and_dispatches_what_it_recorded(
        self,
    ) -> None:
        for case in PRESSURE_CASES:
            with self.subTest(case=case.name):
                await self._check(case)

    async def _check(self, case) -> None:
        fixture = case.build()
        cog = build_cog()
        cog.games[fixture.game.game_id] = fixture.game
        match = fixture.match
        interaction = build_interaction()

        with suppressed_cog_saves():
            await cog.apply_pressure(
                interaction, fixture.game, match, fixture.key,
            )

        name, method = FOLLOW_ONS[fixture.follow_on]
        taken = getattr(cog, name)
        for other, _ in FOLLOW_ONS.values():
            if other != name:
                getattr(cog, other).assert_not_awaited()

        taken.assert_awaited_once()
        call = taken.await_args
        self.assertEqual(
            named_arguments(method, call), fixture.follow_on_kwargs,
        )

        # Either the next step opened with it, or the branch posted it
        # itself -- never both, and never neither.
        posted = posted_messages(interaction)
        carried = call.kwargs.get("lead_in") or ""
        if carried:
            self.assertEqual(posted, [])
        else:
            self.assertEqual(len(posted), 1)
            carried = posted[0]
        self.assertEqual(carried, fixture.narration)

        # Every branch moves a meeple -- even a shove with nowhere to
        # go walks the challenger onto the handler's space -- so the
        # persistent board message is redrawn once.
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
            match.board.meeple_position(fixture.handler_id),
            fixture.handler_space,
        )
        self.assertEqual(
            match.board.meeple_position(fixture.challenger_id),
            fixture.challenger_space,
        )
        if fixture.partner_id is not None:
            # A Double Team's partner is placed on the handler's new
            # space beside the challenger, free of exhaustion.
            self.assertEqual(
                match.board.meeple_position(fixture.partner_id),
                fixture.challenger_space,
            )
        self.assertEqual(
            match.pending_double_team, fixture.pending_double_team,
        )


if __name__ == "__main__":
    unittest.main()
