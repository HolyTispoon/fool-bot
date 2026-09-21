"""
What the cog's High Pass and Setup Pass say and do next, recorded off
the old code.

This is the equivalence half of rank O3 of Phase 3 of
docs/model-discord-split.md. It drives the rank's four entry points
over `tests/high_pass_fixtures.py` and asserts the narration byte for
byte, whether the board was written, and which step the resolution
hands the turn to with which arguments -- the four things a
`StepResult` carries -- plus where the ball ended up, how fast it is
going, who has it and the two flags a branch can leave behind.

**It was written and run green before the move**, which is what makes
it evidence: `tests/test_d12ball_high_pass_flow.py` asks the model the
same questions off the same fixtures, so the two agreeing afterwards
is the move having changed nothing rather than new code agreeing with
itself. `tests/deflection_fixtures.py` with
`tests/test_d12ball_deflection_recording.py` is rank D1's copy of the
same shape.

**The refresh is recorded, not assumed.** Three branches of this rank
hand over to a step that draws its own board -- the two passes that
run out of play, where a new play posts and pins one, and the Setup
Pass that lands on nobody, where the loose ball is announced with the
board under it -- and the old cog wrote no board in front of any of
them. This asserts the count either way, so the move cannot quietly
add one.

**The follow-on's arguments are read through the real method's
signature**, not off `call.args`, for the reason rank D2 wrote down:
the old cog hands some of them positionally where a `FollowOn` names
them. `begin_high_pass_contest(interaction, game, match, 2,
lead_in=...)` and `begin_loose_ball(..., 2, lead_in=...)` are both
exactly that case.
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
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.engine import RulesEngine

from high_pass_fixtures import (
    FINISH,
    HIGH_PASS_CONTEST,
    LOOSE_BALL,
    PASS_CASES,
    RUN_BACK,
    SCORING_ATTEMPT,
    SPEED_CHOICE,
)
from flow_stubs import (
    every_step_stubbed,
    lead_in_of,
    named_arguments,
    reached_once,
    was_reached,
)
from save_patches import suppressed_cog_saves

#: The parameters every follow-on takes and no fixture records: the
#: three the cog threads through everything and the narration, which
#: is the result's rather than the follow-on's.
PLUMBING = ("self", "interaction", "game", "match", "lead_in")

#: Each `FollowOnStep` member name this rank can end on, as the cog
#: method it names and that method's unbound original -- the signature
#: the recorded call is read through.
FOLLOW_ONS = {
    FINISH: ("finish_maneuver_resolution", D12Ball.finish_maneuver_resolution),
    SCORING_ATTEMPT: (
        "offer_scoring_attempt_choice", D12Ball.offer_scoring_attempt_choice,
    ),
    SPEED_CHOICE: ("offer_speed_choice", D12Ball.offer_speed_choice),
    RUN_BACK: ("begin_run_back", D12Ball.begin_run_back),
    LOOSE_BALL: ("begin_loose_ball", D12Ball.begin_loose_ball),
    HIGH_PASS_CONTEST: (
        "begin_high_pass_contest", D12Ball.begin_high_pass_contest,
    ),
}


def build_cog() -> D12Ball:
    """
    A cog with the engine it really uses and mocks where Discord would
    be. Every follow-on is an `AsyncMock` because what they were
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
    # Set after the engine: `team_emojis` is a property whose setter
    # writes through to it (rank 1a's forwarding shape).
    cog.team_emojis = {}
    cog.refresh_match_image = mock.AsyncMock()
    for name, _ in FOLLOW_ONS.values():
        setattr(cog, name, mock.AsyncMock())
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


async def drive(cog, fixture, interaction) -> None:
    """
    The fixture's own entry point, which for this rank is one of four:
    a High Pass, a Setup Pass's speed half, its destination half, or
    the dead end its menu falls to when it has no distance to offer.
    """
    args = (interaction, fixture.game, fixture.match)
    if fixture.entry == "high_pass":
        await cog.apply_high_pass(*args, fixture.distance)
    elif fixture.entry == "setup_pass":
        await cog.apply_setup_pass(*args, fixture.distance)
    elif fixture.entry == "setup_pass_out":
        await cog.apply_setup_pass_out(*args)
    elif fixture.entry == "setup_pass_speed":
        await cog.resolve_setup_pass(*args)
    else:  # pragma: no cover -- a typo in the table, not a branch
        raise AssertionError(f"unknown entry {fixture.entry!r}")


class PassRecordingTests(unittest.IsolatedAsyncioTestCase):
    """
    One subtest per branch, each reading the fixture table's own
    answer. A branch that stops matching here is a branch whose
    wording or whose next step changed, which is a rules-visible
    change and not a refactor.
    """

    async def test_every_branch_says_and_dispatches_what_it_recorded(
        self,
    ) -> None:
        for case in PASS_CASES:
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
            await drive(cog, fixture, interaction)

        member = FollowOnStep[fixture.follow_on]
        _, method = FOLLOW_ONS[fixture.follow_on]
        for other in members:
            if other is not member:
                self.assertFalse(
                    was_reached(recorders[other]), other.name,
                )

        self.assertTrue(reached_once(recorders[member]))
        self.assertEqual(
            named_arguments(member, method, recorders[member], PLUMBING),
            fixture.follow_on_kwargs,
        )

        # Every branch of this rank carries its narration into the next
        # step. Nothing here posts a message of its own.
        self.assertEqual(posted_messages(interaction), [])
        self.assertEqual(lead_in_of(recorders[member]), fixture.narration)

        # The board was written only where the old cog wrote it; see
        # the module docstring.
        self.assertEqual(
            cog.refresh_match_image.await_count,
            1 if fixture.refreshes else 0,
        )

        self.assertEqual(match.ball.possession, fixture.possession)
        self.assertEqual(match.ball.speed, fixture.ball_speed)
        self.assertEqual(
            (match.ball.zone, match.ball.space_index), fixture.ball_space,
        )
        self.assertEqual(match.ball_carrier_id, fixture.carrier_id)
        self.assertEqual(
            match.pending_high_pass_overshoot, fixture.overshoot_flag,
        )
        self.assertEqual(match.pending_ball_recovery, fixture.ball_recovery)
        self.assertEqual(
            match.pending_effect_continuation, fixture.continuation,
        )


if __name__ == "__main__":
    unittest.main()
