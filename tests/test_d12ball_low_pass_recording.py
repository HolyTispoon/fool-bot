"""
What the cog's Low Pass says and does next, recorded off the old code.

This is the equivalence half of Phase 2 of docs/model-discord-split.md.
It drives `D12Ball.apply_low_pass` over `tests/low_pass_fixtures.py`
and asserts the narration byte for byte, whether the board moved, and
which step the resolution hands the turn to with which arguments --
the four things a `StepResult` carries.

**It was written and run green before the move**, which is what makes
it evidence: `tests/test_d12ball_low_pass_flow.py` asks the model the
same questions off the same fixtures, so the two agreeing afterwards is
the move having changed nothing rather than new code agreeing with
itself. `tests/prompt_fixtures.py` and
`tests/test_d12ball_prompt_mapping.py` are the worked example from
Phase 1; this is the same shape on the write side.

The narration is read out of the follow-on step's `lead_in` rather than
off a message, because a Low Pass posts nothing of its own: what it
says is the opening of the message the next step sends. Keeping it that
way is also what keeps the move from costing a Discord request -- see
"Discord's rate limits" in docs/design/rate-limits.md.
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

from low_pass_fixtures import (
    FAILED_PASS_CASES,
    FINISH,
    LOW_PASS_CASES,
    SCORING_CHOICE,
)
from save_patches import suppressed_cog_saves


def build_cog() -> D12Ball:
    """
    A cog with the engine it really uses and mocks where Discord would
    be. The two follow-on steps are `AsyncMock`s because what they were
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
    cog.offer_scoring_attempt_choice = mock.AsyncMock()
    cog.begin_loose_ball = mock.AsyncMock()
    cog.maneuver_hand_image_bytes = {
        (sides, tiers): b""
        for sides in (("offense",), ("defense",), ("offense", "defense"))
        for tiers in (
            (MANEUVER_TIER_BASIC,),
            (MANEUVER_TIER_BASIC, MANEUVER_TIER_ADVANCED),
        )
    }
    return cog


class LowPassRecordingTests(unittest.IsolatedAsyncioTestCase):
    """
    One test per branch, each reading the fixture table's own answer.
    A branch that stops matching here is a branch whose wording or
    whose next step changed, which is a rules-visible change and not a
    refactor.
    """

    async def test_every_branch_says_and_dispatches_what_it_recorded(
        self,
    ) -> None:
        for case in LOW_PASS_CASES:
            with self.subTest(case=case.name):
                await self._check(case)

    async def _check(self, case) -> None:
        fixture = case.build()
        cog = build_cog()
        cog.games[fixture.game.game_id] = fixture.game
        match = fixture.match
        interaction = SimpleNamespace()

        with suppressed_cog_saves():
            await cog.apply_low_pass(
                interaction,
                fixture.game,
                match,
                fixture.distance,
                receiver_id=fixture.receiver_id,
                key=fixture.key,
                free=fixture.free,
            )

        step = (
            cog.finish_maneuver_resolution
            if fixture.follow_on == FINISH
            else cog.offer_scoring_attempt_choice
        )
        unused = (
            cog.offer_scoring_attempt_choice
            if fixture.follow_on == FINISH
            else cog.finish_maneuver_resolution
        )
        self.assertIn(fixture.follow_on, (FINISH, SCORING_CHOICE))
        step.assert_awaited_once()
        unused.assert_not_awaited()

        kwargs = step.await_args.kwargs
        self.assertEqual(kwargs["lead_in"], fixture.narration)
        for name, value in fixture.follow_on_kwargs.items():
            self.assertEqual(kwargs[name], value, name)

        # The board moved, so the persistent message is redrawn. Every
        # Low Pass branch does; the flag is carried anyway because a
        # step that does not is the reason `StepResult` has it.
        self.assertEqual(
            cog.refresh_match_image.await_count, 1 if fixture.board_changed
            else 0,
        )

        self.assertEqual(match.ball_carrier_id, fixture.carrier_id)
        self.assertEqual(
            (match.ball.zone, match.ball.space_index), fixture.ball_space,
        )
        self.assertEqual(match.ball.speed, fixture.ball_speed)

    async def test_a_free_pass_spends_its_continuation(self) -> None:
        """
        Applying the pass is what spends Skilled Pass's cost -- see
        `continue_effect`. Asserted on its own because it is the one
        thing the branch changes that no narration mentions.
        """
        fixture = next(
            case.build() for case in LOW_PASS_CASES
            if case.name == "free_pass_off_a_beaten_skilled_pass"
        )
        cog = build_cog()
        cog.games[fixture.game.game_id] = fixture.game
        self.assertIsNotNone(fixture.match.pending_effect_continuation)

        with suppressed_cog_saves():
            await cog.apply_low_pass(
                SimpleNamespace(),
                fixture.game,
                fixture.match,
                fixture.distance,
                receiver_id=fixture.receiver_id,
                key=fixture.key,
                free=fixture.free,
            )

        self.assertIsNone(fixture.match.pending_effect_continuation)


class FailedPassRecordingTests(unittest.IsolatedAsyncioTestCase):
    """
    The other half of rank O1: the pass that finds nobody.

    It never reaches `apply_low_pass` -- `resolve_low_pass` moves the
    ball, words it and hands the turn to `begin_loose_ball` inline --
    so this drives the resolution itself, with the loose ball mocked
    because what it was *called with* is the whole assertion. Recorded
    off the old code, for the same reason the table above was.
    """

    async def test_every_branch_says_and_dispatches_what_it_recorded(
        self,
    ) -> None:
        for case in FAILED_PASS_CASES:
            with self.subTest(case=case.name):
                await self._check(case)

    async def _check(self, case) -> None:
        fixture = case.build()
        cog = build_cog()
        cog.games[fixture.game.game_id] = fixture.game
        match = fixture.match

        # Nobody in reach is the whole premise of the branch, so it is
        # asserted rather than assumed: a fixture the roster drifted
        # under would otherwise quietly resolve an ordinary pass and
        # record the wrong thing.
        self.assertEqual(cog.engine.pass_candidates(match, fixture.key), [])

        with suppressed_cog_saves():
            await cog.resolve_low_pass(
                SimpleNamespace(),
                fixture.game,
                match,
                key=fixture.key,
                free=fixture.free,
            )

        cog.begin_loose_ball.assert_awaited_once()
        cog.finish_maneuver_resolution.assert_not_awaited()
        cog.offer_scoring_attempt_choice.assert_not_awaited()

        kwargs = cog.begin_loose_ball.await_args.kwargs
        self.assertEqual(kwargs["lead_in"], fixture.narration)
        for name, value in fixture.follow_on_kwargs.items():
            self.assertEqual(kwargs[name], value, name)
        # No headline: what to call the space the ball stopped on is a
        # question about that space rather than about the pass that
        # failed, so the loose ball reads it off the position.
        self.assertIsNone(kwargs.get("headline"))

        # No refresh: the loose ball draws this same board under its
        # own announcement, and a second write of an identical board is
        # a request spent for nothing -- see "Discord's rate limits" in
        # docs/design/rate-limits.md.
        self.assertEqual(
            cog.refresh_match_image.await_count, 1 if fixture.board_changed
            else 0,
        )

        # Nobody carries a loose ball.
        self.assertIsNone(match.ball_carrier_id)
        self.assertEqual(
            (match.ball.zone, match.ball.space_index), fixture.ball_space,
        )
        self.assertEqual(match.ball.speed, fixture.ball_speed)

    async def test_a_failed_free_pass_leaves_its_continuation_standing(
        self,
    ) -> None:
        """
        Recorded, not endorsed. A *completed* free pass spends the
        continuation that produced it (`low_pass_step`); a free pass
        with nobody in reach does not, so the record is still on the
        match when the loose ball is announced. Whether that is the
        rule is the author's to say -- this pins the behaviour so the
        move cannot change it either way.
        """
        fixture = next(
            case.build() for case in FAILED_PASS_CASES
            if case.name == "free_pass_with_no_receiver"
        )
        cog = build_cog()
        cog.games[fixture.game.game_id] = fixture.game

        with suppressed_cog_saves():
            await cog.resolve_low_pass(
                SimpleNamespace(),
                fixture.game,
                fixture.match,
                key=fixture.key,
                free=fixture.free,
            )

        self.assertEqual(
            fixture.match.pending_effect_continuation,
            {"kind": "free_low_pass", "player_id": fixture.match.active_player_id},
        )
        # And the same branch charges the space minute a completed free
        # pass does not -- the other half of the same question.
        self.assertEqual(
            cog.begin_loose_ball.await_args.kwargs["distance_moved"], 1,
        )


if __name__ == "__main__":
    unittest.main()
