"""
What the cog's Deflect and Clear say and do next, recorded off the old
code.

This is the equivalence half of rank D1 of Phase 3 of
docs/design/model-discord-split.md. It drives `None` over
`tests/deflection_fixtures.py` and asserts the narration byte for
byte, whether the board was written, and which step the resolution
hands the turn to with which arguments -- the four things a
`StepResult` carries -- plus where the ball ended up, how fast it is
going and who has it.

**It was written and run green before the move**, which is what makes
it evidence: `tests/test_d12ball_deflection_flow.py` asks the model
the same questions off the same fixtures, so the two agreeing
afterwards is the move having changed nothing rather than new code
agreeing with itself. `tests/pressure_fixtures.py` with
`tests/test_d12ball_pressure_recording.py` is rank D3's copy of the
same shape.

**The refresh is recorded, not assumed.** Every branch drives the ball
back, so every branch earns the dispatcher's one write. Two of them
hand over to a step that draws the board under its own announcement,
and in a real game the dispatcher skips its write in front of that --
by reading what the loose ball's step itself reports (see
`D12Ball.stop_draws_the_board`), which the recorder standing in for
it here does not. So this asserts one write per branch, which is what
keeps the move from quietly adding a second.

**The follow-on's arguments are read through the real method's
signature**, not off `call.args`, for the reason rank D2 wrote down:
the old cog hands some of them positionally where a `FollowOn` names
them. `begin_loose_ball(interaction, game, match, 1, lead_in=...)` is
exactly that case -- `distance_moved` is the fourth positional
argument today and arrives named after the move.
"""

from __future__ import annotations

import inspect
import unittest
from types import SimpleNamespace
from unittest import mock

from cogs.d12ball import D12Ball
from d12ball.flow import FollowOnStep
from d12ball.ai import build_ai_strategies
from d12ball.cards import maneuver_hand_combinations
from d12ball.components import (
    MANEUVER_TIER_BASIC,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.engine import RulesEngine

from deflection_fixtures import (
    DEFLECTION_CASES,
    LOOSE_BALL,
    SETUP_PASS_PUSH_BACK,
    SHOOTER_CHOICE,
)
from flow_stubs import (
    every_step_stubbed,
    lead_in_of,
    named_arguments,
    reached_once,
    was_reached,
)
from save_patches import suppressed_cog_saves
from cog_steps import apply_deflection

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


FOLLOW_ONS = {
    LOOSE_BALL: ("begin_loose_ball", None),
    SHOOTER_CHOICE: ("begin_shooter_choice", None),
    SETUP_PASS_PUSH_BACK: (
        "offer_setup_pass_push_back", None,
    ),
}


class DeflectionRecordingTests(unittest.IsolatedAsyncioTestCase):
    """
    One subtest per branch, each reading the fixture table's own
    answer. A branch that stops matching here is a branch whose
    wording or whose next step changed, which is a rules-visible
    change and not a refactor.
    """

    async def test_every_branch_says_and_dispatches_what_it_recorded(
        self,
    ) -> None:
        for case in DEFLECTION_CASES:
            with self.subTest(case=case.name):
                await self._check(case)

    async def _check(self, case) -> None:
        fixture = case.build()
        cog = build_cog()
        cog.games[fixture.game.game_id] = fixture.game
        match = fixture.match
        interaction = build_interaction()

        # **Each step is stubbed on the side that runs it.** Phase 6
        # moved some of these into `d12ball.flow.driver`, which has no
        # cog method to patch; `flow_stubs.chain_stops_at` answers
        # which side owns a member so this table does not have to.
        members = [FollowOnStep[key] for key in FOLLOW_ONS]
        with every_step_stubbed(cog, members) as recorders, \
                suppressed_cog_saves():
            await apply_deflection(cog, 
                interaction, fixture.game, match, fixture.key,
            )

        member = FollowOnStep[fixture.follow_on]
        _, method = FOLLOW_ONS[fixture.follow_on]
        for other in members:
            if other is not member:
                self.assertFalse(was_reached(recorders[other]), other.name)

        self.assertTrue(reached_once(recorders[member]))
        self.assertEqual(
            named_arguments(member, method, recorders[member], PLUMBING),
            fixture.follow_on_kwargs,
        )

        # Every branch of this rank carries its narration into the next
        # step. Nothing here posts a message of its own -- the
        # overshoot included, which is where rank D3 differed.
        self.assertEqual(posted_messages(interaction), [])
        self.assertEqual(lead_in_of(recorders[member]), fixture.narration)

        # One write wherever the board moved. The next step is a
        # recorder here, and the dispatcher's suppression reads what
        # the real next step reports -- see the fixture module.
        self.assertEqual(
            cog.refresh_match_image.await_count,
            1 if fixture.board_changed else 0,
        )

        self.assertEqual(match.ball.possession, fixture.possession)
        self.assertEqual(match.ball.speed, fixture.ball_speed)
        self.assertEqual(
            (match.ball.zone, match.ball.space_index), fixture.ball_space,
        )


if __name__ == "__main__":
    unittest.main()
