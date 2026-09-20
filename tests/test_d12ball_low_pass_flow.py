"""
Low Pass as a flow step, and the cog wrapper around it.

The model half of Phase 2 of docs/model-discord-split.md.
`tests/test_d12ball_low_pass_recording.py` asked the cog what a Low
Pass says and does next, off `tests/low_pass_fixtures.py`, and was run
green before anything moved. This asks `d12ball.flow.effects` the same
questions off the same fixtures -- so the two agreeing is the move
having changed nothing.

It also covers the three things the step's new shape adds, none of
which the old code had anywhere to put:

- the step **does not save** (principle 9: a step mutates and returns,
  the caller writes it down),
- the cog wrapper saves **between** the step and the dispatch, which is
  the transition rule for Phases 2 to 5,
- a `StepResult` carrying a `PendingPrompt` renders through
  `view_for_prompt`, the same table a restart restores through.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from cogs.d12ball_views import LowPassChoiceView
from d12ball.flow import FollowOn, FollowOnStep, StepResult
from d12ball.flow.effects import low_pass_step
from d12ball.prompts import PendingPrompt, PromptKind

from low_pass_fixtures import ENGINE, FINISH, LOW_PASS_CASES, SCORING_CHOICE
from save_patches import suppressed_cog_saves
from test_d12ball_low_pass_recording import build_cog


class LowPassStepTests(unittest.TestCase):
    """
    The step, asked directly. No cog, no interaction, no event loop --
    which is most of the point: a web app reaches this with the match
    it already holds.
    """

    def test_every_branch_answers_what_the_cog_recorded(self) -> None:
        for case in LOW_PASS_CASES:
            with self.subTest(case=case.name):
                fixture = case.build()
                result = low_pass_step(
                    ENGINE,
                    fixture.match,
                    fixture.distance,
                    receiver_id=fixture.receiver_id,
                    key=fixture.key,
                    free=fixture.free,
                )

                # The cog joins the lines on a single space, which is
                # how the narration reached the next step before.
                self.assertEqual(
                    " ".join(result.narration), fixture.narration,
                )
                self.assertEqual(result.board_changed, fixture.board_changed)

                self.assertIsInstance(result.next, FollowOn)
                self.assertEqual(
                    result.next.step.name, fixture.follow_on,
                )
                self.assertEqual(
                    dict(result.next.kwargs), fixture.follow_on_kwargs,
                )
                # The narration is the result's, never the follow-on's
                # -- how the two go together is the frontend's call.
                self.assertNotIn("lead_in", result.next.kwargs)

                match = fixture.match
                self.assertEqual(match.ball_carrier_id, fixture.carrier_id)
                self.assertEqual(
                    (match.ball.zone, match.ball.space_index),
                    fixture.ball_space,
                )
                self.assertEqual(match.ball.speed, fixture.ball_speed)

    def test_the_two_follow_on_steps_are_the_ones_low_pass_can_name(
        self,
    ) -> None:
        """
        Low Pass ends on one of exactly these two, and both are real
        members rather than strings this module happens to agree with
        itself about.

        The **whole** of `FollowOnStep` is asserted in
        `tests/test_d12ball_package_shape.py`, not here: the enum is
        the record of what the cog still dispatches and every rank of
        Phase 3 adds to it, so a list of its members belongs
        somewhere no one rank owns.
        """
        self.assertLessEqual(
            {FINISH, SCORING_CHOICE},
            {member.name for member in FollowOnStep},
        )

    def test_a_free_pass_spends_its_continuation(self) -> None:
        fixture = next(
            case.build() for case in LOW_PASS_CASES
            if case.name == "free_pass_off_a_beaten_skilled_pass"
        )
        self.assertIsNotNone(fixture.match.pending_effect_continuation)

        low_pass_step(
            ENGINE,
            fixture.match,
            fixture.distance,
            receiver_id=fixture.receiver_id,
            key=fixture.key,
            free=fixture.free,
        )

        self.assertIsNone(fixture.match.pending_effect_continuation)

    def test_the_step_does_not_save(self) -> None:
        """
        The step that moved used to persist inside itself. It must
        not any more: the driver saves, so a step that saved would put
        the write back where principle 9 took it from.

        `save_games` is replaced at its own module rather than at a
        binding, so an import added to the flow package later is
        caught too -- `save_patches.guard_stray_saves` deliberately
        leaves `gamesaves.d12ball.storage` alone, which is what makes
        it patchable here.
        """
        recorder = mock.Mock()
        with suppressed_cog_saves(), mock.patch(
            "gamesaves.d12ball.storage.save_games", recorder,
        ):
            for case in LOW_PASS_CASES:
                fixture = case.build()
                low_pass_step(
                    ENGINE,
                    fixture.match,
                    fixture.distance,
                    receiver_id=fixture.receiver_id,
                    key=fixture.key,
                    free=fixture.free,
                )

        recorder.assert_not_called()


class LowPassWrapperTests(unittest.IsolatedAsyncioTestCase):
    """
    `D12Ball.apply_low_pass` and `D12Ball.dispatch_step_result` -- the
    Discord half, which is now four lines and an ordering.
    """

    async def test_the_save_lands_between_the_step_and_the_dispatch(
        self,
    ) -> None:
        """
        The transition rule for Phases 2 to 5, asserted as an order
        *and* as content: at the moment the save runs, the pass must
        already have happened. A persist before the step writes a
        match that has not moved, and a persist after the dispatch is
        too late for a step that ends in a prompt -- the next click
        reloads the match from the file.
        """
        fixture = next(
            case.build() for case in LOW_PASS_CASES
            if case.name == "plain_forward"
        )
        cog = build_cog()
        cog.games[fixture.game.game_id] = fixture.game
        match = fixture.match
        calls: list[str] = []
        carrier_when_saved: list[object] = []

        def persist(game, saved_match) -> None:
            calls.append("persist")
            carrier_when_saved.append(saved_match.ball_carrier_id)

        async def refresh(*args, **kwargs) -> None:
            calls.append("refresh")

        async def finish(*args, **kwargs) -> None:
            calls.append("finish_maneuver_resolution")

        cog.persist = persist
        cog.refresh_match_image = refresh
        cog.finish_maneuver_resolution = finish

        await cog.apply_low_pass(
            SimpleNamespace(),
            fixture.game,
            match,
            fixture.distance,
            receiver_id=fixture.receiver_id,
        )

        self.assertEqual(
            calls, ["persist", "refresh", "finish_maneuver_resolution"],
        )
        self.assertEqual(carrier_when_saved, [fixture.carrier_id])

    async def test_a_board_that_did_not_move_is_not_redrawn(self) -> None:
        """
        `board_changed` is what `refresh_match_image` used to decide
        at the call site. Every Low Pass branch moves the ball, so the
        False case has no fixture yet and is asserted directly -- the
        ranks Phase 3 lifts are what will bring one.
        """
        fixture = next(
            case.build() for case in LOW_PASS_CASES
            if case.name == "plain_forward"
        )
        cog = build_cog()

        await cog.dispatch_step_result(
            SimpleNamespace(), fixture.game, fixture.match,
            StepResult(board_changed=False),
        )

        cog.refresh_match_image.assert_not_awaited()

    async def test_a_pending_prompt_is_rendered_through_view_for_prompt(
        self,
    ) -> None:
        """
        Principle 3, on the write side: the live flow and the restart
        flow build a prompt through one table. A second table is how a
        resume comes to offer a different question from the one a
        restart restores.

        No Low Pass branch ends on a prompt today -- the receiver pick
        is asked before the pass is applied -- so this is asserted on
        the dispatcher directly, which is where Phase 3's effects will
        meet it.
        """
        fixture = next(
            case.build() for case in LOW_PASS_CASES
            if case.name == "plain_forward"
        )
        cog = build_cog()
        cog.games[fixture.game.game_id] = fixture.game
        prompt = PendingPrompt(
            kind=PromptKind.LOW_PASS_CHOICE,
            ask="Choose your Low Pass:",
            maneuver_key="low_pass",
        )

        with mock.patch(
            "cogs.d12ball.core.send_new_prompt", mock.AsyncMock(),
        ) as send:
            await cog.dispatch_step_result(
                SimpleNamespace(),
                fixture.game,
                fixture.match,
                StepResult(
                    narration=["**Low Pass:** the ball moves 2 spaces "
                               "forward."],
                    board_changed=True,
                    next=prompt,
                ),
            )

        send.assert_awaited_once()
        content = send.await_args.args[1]
        self.assertEqual(
            content,
            "**Low Pass:** the ball moves 2 spaces forward. "
            "Choose your Low Pass:",
        )
        self.assertIsInstance(
            send.await_args.kwargs["view"], LowPassChoiceView,
        )

    async def test_a_step_with_nothing_next_posts_its_own_lines(
        self,
    ) -> None:
        """
        A result that neither asks nor continues has nobody to hand
        its narration to, so the dispatcher posts it. Nothing in Phase
        2 produces one; it is here so a step lifted later cannot lose
        its lines silently.
        """
        fixture = next(
            case.build() for case in LOW_PASS_CASES
            if case.name == "plain_forward"
        )
        cog = build_cog()

        with mock.patch(
            "cogs.d12ball.core.send_new_prompt", mock.AsyncMock(),
        ) as send:
            await cog.dispatch_step_result(
                SimpleNamespace(), fixture.game, fixture.match,
                StepResult(narration=["One.", "Two."], board_changed=False),
            )

        send.assert_awaited_once()
        self.assertEqual(send.await_args.args[1], "One. Two.")


if __name__ == "__main__":
    unittest.main()
