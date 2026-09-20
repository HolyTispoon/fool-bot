"""
What the cog's Deflect and Clear say and do next, recorded off the old
code.

This is the equivalence half of rank D1 of Phase 3 of
docs/model-discord-split.md. It drives `D12Ball.apply_deflection` over
`tests/deflect_fixtures.py` and asserts the narration byte for byte,
how many times the board was redrawn, and which step the resolution
hands the turn to with which arguments -- plus where the ball ended up,
how fast it is going and who has it.

**It was written and run green before the move**, which is what makes
it evidence: `tests/test_d12ball_deflect_flow.py` asks the model the
same questions off the same fixtures, so the two agreeing afterwards is
the move having changed nothing rather than new code agreeing with
itself. `tests/pressure_fixtures.py` with
`tests/test_d12ball_pressure_recording.py` is rank D3's copy of the
same shape.

**The refresh count is recorded rather than derived from
`board_changed`**, which is the one place this rank departs from D3's
table. Every branch here moves the ball, and the old cog redrew the
board on exactly one of them: the two that hand over to something
which draws the board under its own announcement got no refresh, and a
refresh there would have written the same board twice. So the fixture
carries both numbers and this asserts the cog's -- see
`tests/test_d12ball_deflect_flow.py` for the assertion that the moved
step still costs the same.

**The follow-on's arguments are read through the real method's
signature**, not off `call.args`, for the reason rank D2 wrote down:
the old cog hands some of them positionally where a `FollowOn` names
them. `begin_loose_ball`'s `distance_moved` is exactly that.
"""

from __future__ import annotations

import inspect
import unittest
from types import SimpleNamespace
from unittest import mock

from cogs.d12ball import D12Ball
from d12ball.ai import build_ai_strategies
from d12ball.components import (
    MANEUVER_TIER_ADVANCED,
    MANEUVER_TIER_BASIC,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.engine import RulesEngine

from deflect_fixtures import (
    DEFLECT_CASES,
    LOOSE_BALL,
    PUSH_BACK,
    SHOOTER_CHOICE,
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
    cog.begin_loose_ball = mock.AsyncMock()
    cog.begin_shooter_choice = mock.AsyncMock()
    cog.offer_setup_pass_push_back = mock.AsyncMock()
    cog.maneuver_hand_image_bytes = {
        (sides, tiers): b""
        for sides in (("offense",), ("defense",), ("offense", "defense"))
        for tiers in (
            (MANEUVER_TIER_BASIC,),
            (MANEUVER_TIER_BASIC, MANEUVER_TIER_ADVANCED),
        )
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
    LOOSE_BALL: ("begin_loose_ball", D12Ball.begin_loose_ball),
    SHOOTER_CHOICE: ("begin_shooter_choice", D12Ball.begin_shooter_choice),
    PUSH_BACK: (
        "offer_setup_pass_push_back", D12Ball.offer_setup_pass_push_back,
    ),
}


class DeflectRecordingTests(unittest.IsolatedAsyncioTestCase):
    """
    One subtest per branch, each reading the fixture table's own
    answer. A branch that stops matching here is a branch whose
    wording or whose next step changed, which is a rules-visible
    change and not a refactor.
    """

    async def test_every_branch_says_and_dispatches_what_it_recorded(
        self,
    ) -> None:
        for case in DEFLECT_CASES:
            with self.subTest(case=case.name):
                await self._check(case)

    async def _check(self, case) -> None:
        fixture = case.build()
        cog = build_cog()
        cog.games[fixture.game.game_id] = fixture.game
        match = fixture.match
        interaction = build_interaction()

        with suppressed_cog_saves():
            await cog.apply_deflection(
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

        # Every branch of this rank hands the narration on as the next
        # step's `lead_in`; none of them posts a message of its own.
        self.assertEqual(posted_messages(interaction), [])
        self.assertEqual(
            call.kwargs.get("lead_in") or "", fixture.narration,
        )

        self.assertEqual(
            cog.refresh_match_image.await_count, fixture.refreshes,
        )

        self.assertEqual(match.ball.possession, fixture.possession)
        self.assertEqual(match.ball.speed, fixture.ball_speed)
        self.assertEqual(match.ball_carrier_id, fixture.carrier_id)
        self.assertEqual(
            (match.ball.zone, match.ball.space_index), fixture.ball_space,
        )


if __name__ == "__main__":
    unittest.main()
