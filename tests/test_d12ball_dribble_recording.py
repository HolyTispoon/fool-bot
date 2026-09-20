"""
What the cog's two dribbles say and do next, recorded off the old code.

This is the equivalence half of rank O2 of Phase 3 of
docs/model-discord-split.md. It drives `D12Ball.apply_dribble_advance`
and `D12Ball.apply_dribble_burst` over `tests/dribble_fixtures.py` and
asserts the narration byte for byte, whether the board moved, and which
step the resolution hands the turn to with which arguments -- the four
things a `StepResult` carries.

**It was written and run green before the move**, which is what makes
it evidence: `tests/test_d12ball_dribble_flow.py` asks the model the
same questions off the same fixtures, so the two agreeing afterwards is
the move having changed nothing rather than new code agreeing with
itself. `tests/low_pass_fixtures.py` and
`tests/test_d12ball_low_pass_recording.py` are the worked example from
Phase 2; this is the same shape on the rank after it.

The narration is read out of `offer_speed_choice`'s `lead_in` rather
than off a message, because a dribble posts nothing of its own: what it
says is the opening of the speed prompt every dribble ends on. Keeping
it that way is also what keeps the move from costing a Discord request
-- see "Discord's rate limits" in docs/design/rate-limits.md.
"""

from __future__ import annotations

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

from dribble_fixtures import DRIBBLE_CASES, SPEED_CHOICE
from save_patches import suppressed_cog_saves


def build_cog() -> D12Ball:
    """
    A cog with the engine it really uses and mocks where Discord would
    be. `offer_speed_choice` is an `AsyncMock` because what it was
    *called with* is the whole assertion.

    `condition_emojis` is set after the engine because it is a property
    over it -- the cog and the engine hold one dict between them, not
    two that can disagree about which upload exists (see
    `D12Ball.team_emojis`). Left empty, so every condition in the
    narration reads its fallback emoji.
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
    cog.condition_emojis = {}
    cog.refresh_match_image = mock.AsyncMock()
    cog.offer_speed_choice = mock.AsyncMock()
    cog.maneuver_hand_image_bytes = {
        (sides, tiers): b""
        for sides in (("offense",), ("defense",), ("offense", "defense"))
        for tiers in (
            (MANEUVER_TIER_BASIC,),
            (MANEUVER_TIER_BASIC, MANEUVER_TIER_ADVANCED),
        )
    }
    return cog


class DribbleRecordingTests(unittest.IsolatedAsyncioTestCase):
    """
    One subtest per branch, each reading the fixture table's own
    answer. A branch that stops matching here is a branch whose wording
    or whose next step changed, which is a rules-visible change and not
    a refactor.
    """

    async def test_every_branch_says_and_dispatches_what_it_recorded(
        self,
    ) -> None:
        for case in DRIBBLE_CASES:
            with self.subTest(case=case.name):
                await self._check(case)

    async def _check(self, case) -> None:
        fixture = case.build()
        cog = build_cog()
        cog.games[fixture.game.game_id] = fixture.game
        match = fixture.match
        apply = (
            cog.apply_dribble_advance
            if fixture.key == "dribble_advance"
            else cog.apply_dribble_burst
        )

        with suppressed_cog_saves():
            await apply(
                SimpleNamespace(),
                fixture.game,
                match,
                fixture.distance,
            )

        self.assertEqual(fixture.follow_on, SPEED_CHOICE)
        cog.offer_speed_choice.assert_awaited_once()

        kwargs = cog.offer_speed_choice.await_args.kwargs
        self.assertEqual(kwargs["lead_in"], fixture.narration)
        for name, value in fixture.follow_on_kwargs.items():
            self.assertEqual(kwargs[name], value, name)

        # Every dribble moves the handler and the ball with them, so
        # the persistent board message is redrawn -- including the run
        # that covered no ground, which the old code refreshed anyway.
        # The flag is carried rather than assumed because a step that
        # moves nothing a board draws is what it is for.
        self.assertEqual(
            cog.refresh_match_image.await_count,
            1 if fixture.board_changed else 0,
        )

        # They dribbled it there, so they still have it: the same
        # player takes the next turn.
        self.assertEqual(match.ball_carrier_id, fixture.carrier_id)
        self.assertEqual(
            (match.ball.zone, match.ball.space_index), fixture.ball_space,
        )
        self.assertEqual(
            match.exhaustion.get(fixture.carrier_id, 0), fixture.exhaustion,
        )


if __name__ == "__main__":
    unittest.main()
