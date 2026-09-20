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
    MANEUVER_TIER_GAMBIT,
    MANEUVER_TIER_BASIC,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.engine import RulesEngine

from low_pass_fixtures import FINISH, LOW_PASS_CASES, SCORING_CHOICE
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
    cog.maneuver_hand_image_bytes = {
        (sides, tiers): b""
        for sides in (("offense",), ("defense",), ("offense", "defense"))
        for tiers in (
            (MANEUVER_TIER_BASIC,),
            (MANEUVER_TIER_BASIC, MANEUVER_TIER_GAMBIT),
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


class SkilledPassDelegationTests(unittest.IsolatedAsyncioTestCase):
    """
    The cog surface rank O1 still has, which is the `key=` parameter
    and the two callers that set it.

    `resolve_skilled_pass` is two lines and `continue_effect`'s free
    branch is a handful, and neither moves in this phase -- both are
    the *ask* half: whether anybody is put a question at all. What is
    worth pinning is that the card's identity survives the delegation,
    because from `resolve_low_pass` down to `low_pass_step` there is
    one function for two cards and `key` is the only thing telling
    them apart.
    """

    def _stand_a_pass_up(self):
        """A match with a pass to make and a coach to ask about it."""
        fixture = next(
            case.build() for case in LOW_PASS_CASES
            if case.name == "skilled_pass"
        )
        cog = build_cog()
        cog.games[fixture.game.game_id] = fixture.game
        cog.send_field_prompt = mock.AsyncMock()
        cog.apply_low_pass = mock.AsyncMock()
        cog.begin_loose_ball = mock.AsyncMock()
        return cog, fixture

    async def test_a_skilled_pass_is_asked_as_a_skilled_pass(self) -> None:
        cog, fixture = self._stand_a_pass_up()

        with suppressed_cog_saves():
            await cog.resolve_skilled_pass(
                SimpleNamespace(), fixture.game, fixture.match,
            )

        cog.send_field_prompt.assert_awaited_once()
        content, view = cog.send_field_prompt.await_args.args[3:5]
        self.assertIn("Skilled Pass", content)
        self.assertEqual(view.key, "skilled_pass")
        self.assertFalse(view.free)
        # Nothing was applied: the coach has not answered yet.
        cog.apply_low_pass.assert_not_awaited()

    async def test_the_free_pass_is_asked_as_a_low_pass(self) -> None:
        """
        **Skilled Pass's cost.** The defense's unopposed pass is a Low
        Pass -- the card that was beaten does not come with it -- and
        it is `free`, which is what will charge it no space minute
        when it is applied.
        """
        cog, fixture = self._stand_a_pass_up()
        match = fixture.match
        passer = match.active_player_id
        match.pending_effect_continuation = {
            "kind": "free_low_pass",
            "player_id": passer,
        }

        with suppressed_cog_saves():
            await cog.continue_effect(
                SimpleNamespace(), fixture.game, match,
            )

        cog.send_field_prompt.assert_awaited_once()
        content, view = cog.send_field_prompt.await_args.args[3:5]
        self.assertIn("Low Pass", content)
        self.assertNotIn("Skilled Pass", content)
        self.assertEqual(view.key, "low_pass")
        self.assertTrue(view.free)

    async def test_the_continuation_outlives_the_prompt(self) -> None:
        """
        The record is cleared by whatever **applies** the pass -- see
        `continue_effect`, and `low_pass_step`'s `free` branch. A
        coach can take hours over the prompt, and between dispatching
        it and the click that answers, this field is the only thing on
        the match saying what is owed: clear it here and a restart in
        that window reads the maneuver's winner instead and re-offers
        a choice that was already made.
        """
        cog, fixture = self._stand_a_pass_up()
        match = fixture.match
        match.pending_effect_continuation = {
            "kind": "free_low_pass",
            "player_id": match.active_player_id,
        }

        with suppressed_cog_saves():
            await cog.continue_effect(
                SimpleNamespace(), fixture.game, match,
            )

        self.assertEqual(
            match.pending_effect_continuation.get("kind"), "free_low_pass",
        )


if __name__ == "__main__":
    unittest.main()
