"""
Low Pass as a flow step, and the cog wrapper around it.

The model half of Phase 2 of docs/design/model-discord-split.md.
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
from d12ball.components import MatchState
from d12ball.flow import FollowOn, FollowOnStep, StepResult
from d12ball.flow.effects import (
    answer_passer_advance,
    low_pass_step,
    offer_low_pass,
)
from d12ball.game import GameMode
from d12ball.prompts import PendingPrompt, PromptKind, pending_prompt

from low_pass_fixtures import (
    ENGINE,
    FINISH,
    LOW_PASS_CASES,
    RULESET,
    SCORING_CHOICE,
    build_game,
    build_match,
    label,
    stand_at,
    take_the_ball,
)
from d12ball.components import PlayerRole
from roster import fielded
from prompt_fixtures import CASES as PROMPT_CASES
from prompt_fixtures import ENGINE as PROMPT_ENGINE
from flow_stubs import chain_records_at
from save_patches import suppressed_cog_saves
from test_d12ball_low_pass_recording import build_cog
from cog_steps import answered_passer_advance, apply_low_pass


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
                result = answered_passer_advance(
                    ENGINE,
                    fixture.match,
                    low_pass_step(
                        ENGINE,
                        fixture.match,
                        fixture.distance,
                        receiver_id=fixture.receiver_id,
                        key=fixture.key,
                        free=fixture.free,
                    ),
                    fixture.advance,
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
                if fixture.passer_space is not None:
                    self.assertEqual(
                        match.board.meeple_position(
                            match.active_player_id,
                        ),
                        fixture.passer_space,
                    )

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
    `None` and `D12Ball.dispatch_step_result` -- the
    Discord half, which is now four lines and an ordering.
    """


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

        # The dispatcher writes the match once for the run it just
        # drove (principle 9), so a test calling it directly has to
        # suppress the save the way a wrapper's test does.
        with suppressed_cog_saves():
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

        # A Low Pass is asked over the field strip, so the prompt goes
        # through `send_field_prompt` -- keyed on the kind by
        # `render_prompt`, which is the frontend's half of principle 2.
        cog.send_field_prompt = mock.AsyncMock()
        with suppressed_cog_saves():
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

        cog.send_field_prompt.assert_awaited_once()
        _, _, _, content, view = cog.send_field_prompt.await_args.args
        # The lead-in opens the prompt's message as its own paragraph,
        # and the ask opens on a ping of the coach it is put to, since
        # it does not name them itself.
        mention = cog.tokens(fixture.game).mention(
            PROMPT_ENGINE.side_player_number(
                fixture.game, fixture.match.ball.possession,
            ),
        )
        self.assertTrue(mention.startswith("<@"))
        self.assertEqual(
            content,
            "**Low Pass:** the ball moves 2 spaces forward.\n\n"
            f"{mention} Choose your Low Pass:",
        )
        self.assertIsInstance(view, LowPassChoiceView)

    def test_an_ask_is_pinged_once_and_only_for_an_account(self) -> None:
        """
        A choice notifies the coach who has to make it: an ask that
        does not address them gets a mention in front, one that already
        does is left alone, and a side nobody can ping (the AI, a test
        game's seat) gets nothing added.
        """
        fixture = next(
            case.build() for case in LOW_PASS_CASES
            if case.name == "plain_forward"
        )
        cog = build_cog()
        game, match = fixture.game, fixture.match
        player_number = PROMPT_ENGINE.side_player_number(
            game, match.ball.possession,
        )
        mention = cog.tokens(game).mention(player_number)

        def ask(text: str) -> str:
            return cog.ping_asked(
                game, match,
                PendingPrompt(
                    kind=PromptKind.LOW_PASS_CHOICE,
                    ask=text,
                    maneuver_key="low_pass",
                ),
            )

        self.assertEqual(ask("Choose:"), f"{mention} Choose:")
        self.assertEqual(ask(f"{mention}, choose:"), f"{mention}, choose:")

        game.test_game = True
        self.assertEqual(ask("Choose:"), "Choose:")

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

        # `dispatch_step_result` records `turn_message_id` for every
        # prompt it posts since Phase 4, so it reaches the cog's own
        # `save_games` binding as well as the view's.
        with suppressed_cog_saves(), mock.patch(
            "cogs.d12ball.core.send_new_prompt", mock.AsyncMock(),
        ) as send:
            await cog.dispatch_step_result(
                SimpleNamespace(), fixture.game, fixture.match,
                StepResult(narration=["One.", "Two."], board_changed=False),
            )

        send.assert_awaited_once()
        self.assertEqual(send.await_args.args[1], "One. Two.")


class LowPassRestartTests(unittest.TestCase):
    """
    A restart in the middle of a pass, which is the branch of Phase 1
    that catches a step whose `next` is wrong.

    Rank O1 has no branch that *ends* on a `PendingPrompt` -- the
    receiver is picked before the pass is applied -- so what a restart
    can land in the middle of is the choice **before** the step runs.
    The thing worth asserting there is the one the two cards share:
    `key` is what tells a Pinpoint from a Low Pass all the way
    down to `low_pass_step`, and it is not a field on the match. It is
    read back out of `offense_maneuver` (or, for the free pass, out of
    `pending_effect_continuation`), so a save round trip is the whole
    of what stands between the prompt a coach was looking at and the
    one they get handed back.
    """

    #: The mid-effect states of this rank, by `prompt_fixtures` case
    #: name. All three are `LOW_PASS_CHOICE`; what a restart has to
    #: preserve is which card is under it.
    CASES = (
        "low pass",
        "skilled pass",
        "free low pass",
    )

    def test_a_restart_mid_effect_offers_the_same_card(self) -> None:
        for name in self.CASES:
            with self.subTest(case=name):
                case = next(c for c in PROMPT_CASES if c.name == name)
                fixture = case.build()

                before = pending_prompt(
                    PROMPT_ENGINE, fixture.game, fixture.match,
                )
                restored = MatchState.from_dict(
                    fixture.match.to_dict(), RULESET,
                )
                after = pending_prompt(
                    PROMPT_ENGINE, fixture.game, restored,
                )

                self.assertIs(after.kind, PromptKind.LOW_PASS_CHOICE)
                self.assertIs(after.kind, before.kind)
                self.assertEqual(after.ask, before.ask)
                # The two parameters that decide which card the
                # reconstructed prompt applies, and the ones
                # `apply_low_pass` is handed.
                self.assertEqual(after.maneuver_key, before.maneuver_key)
                self.assertEqual(after.free, before.free)
                self.assertEqual(
                    after.maneuver_key, fixture.params["maneuver_key"],
                )
                self.assertEqual(after.free, fixture.params["free"])


if __name__ == "__main__":
    unittest.main()


class PasserAdvanceTests(unittest.TestCase):
    """
    A Low Pass's passer may move 1 space forward once the ball has gone
    (Law 6.5.3, the author 2026-10-07): asked, saved, and answered
    through the same step whether the pass reached anybody or not.
    """

    def setUp(self) -> None:
        self.match = build_match()
        self.handler = take_the_ball(self.match)
        self.game = build_game()

    def flat(self, player_id: str) -> int:
        return self.match.board.flat_index(
            *self.match.board.meeple_position(player_id),
        )

    def ball_flat(self) -> int:
        return self.match.board.flat_index(
            self.match.ball.zone, self.match.ball.space_index,
        )

    def nobody_in_reach(self) -> None:
        for player_id in self.match.home.field_players:
            if player_id != self.handler:
                self.match.board.remove_meeple(player_id)

    def test_a_low_pass_asks_and_a_restart_asks_the_same(self) -> None:
        receiver = fielded(self.match, PlayerRole.MIDFIELDER)
        stand_at(self.match, receiver, 1)
        result = low_pass_step(
            ENGINE, self.match, 1, receiver_id=receiver, game=self.game,
        )
        self.assertIsInstance(result.next, PendingPrompt)
        self.assertIs(result.next.kind, PromptKind.PASSER_ADVANCE)
        self.assertEqual(result.next.player_id, self.handler)
        # The pass is still the live maneuver; the saved question is
        # what a restart reads, rather than the pass a second time.
        restored = MatchState.from_dict(self.match.to_dict(), RULESET)
        prompt = pending_prompt(ENGINE, self.game, restored)
        self.assertIs(prompt.kind, PromptKind.PASSER_ADVANCE)
        self.assertEqual(prompt.ask, result.next.ask)

    def test_moving_steps_the_passer_forward_and_finishes(self) -> None:
        receiver = fielded(self.match, PlayerRole.MIDFIELDER)
        stand_at(self.match, receiver, 1)
        before = self.flat(self.handler)
        low_pass_step(
            ENGINE, self.match, 1, receiver_id=receiver, game=self.game,
        )
        result = answer_passer_advance(ENGINE, self.game, self.match, True)
        self.assertEqual(self.flat(self.handler), before + 1)
        self.assertEqual(
            result.narration, [f"{label(self.match, self.handler)} moves a space forward."],
        )
        self.assertEqual(result.next.step, FollowOnStep.FINISH_MANEUVER_RESOLUTION)
        self.assertIsNone(self.match.pending_passer_advance)

    def test_staying_says_nothing(self) -> None:
        receiver = fielded(self.match, PlayerRole.MIDFIELDER)
        stand_at(self.match, receiver, 1)
        before = self.flat(self.handler)
        low_pass_step(
            ENGINE, self.match, 1, receiver_id=receiver, game=self.game,
        )
        result = answer_passer_advance(ENGINE, self.game, self.match, False)
        self.assertEqual(self.flat(self.handler), before)
        self.assertEqual(result.narration, [])
        self.assertFalse(result.board_changed)

    def test_a_pinpoint_s_passer_is_never_asked(self) -> None:
        receiver = fielded(self.match, PlayerRole.MIDFIELDER)
        stand_at(self.match, receiver, 1)
        before = self.flat(self.handler)
        result = low_pass_step(
            ENGINE, self.match, 1, receiver_id=receiver,
            key="skilled_pass", game=build_game(mode=GameMode.ADVANCED),
        )
        self.assertIsInstance(result.next, FollowOn)
        self.assertEqual(self.flat(self.handler), before)
        self.assertIsNone(self.match.pending_passer_advance)

    def test_no_question_with_no_space_in_front(self) -> None:
        last = self.match.board.position_at_flat_index(
            self.match.board.layout.board_size - 1,
        )
        self.match.move_meeple(self.handler, *last)
        self.match.set_ball_space(*last)
        receiver = fielded(self.match, PlayerRole.MIDFIELDER)
        stand_at(self.match, receiver, -1)
        result = low_pass_step(
            ENGINE, self.match, -1, receiver_id=receiver, game=self.game,
        )
        self.assertIsInstance(result.next, FollowOn)

    def test_a_low_pass_to_nobody_rolls_two_and_still_asks(self) -> None:
        self.nobody_in_reach()
        start = self.ball_flat()
        result = offer_low_pass(ENGINE, self.game, self.match)
        self.assertEqual(self.ball_flat(), start + 2)
        self.assertIn("rolls 2 spaces forward", result.narration[0])
        self.assertIs(result.next.kind, PromptKind.PASSER_ADVANCE)
        answered = answer_passer_advance(
            ENGINE, self.game, self.match, True,
        )
        self.assertEqual(answered.next.step, FollowOnStep.BEGIN_LOOSE_BALL)

    def test_a_pinpoint_to_nobody_rolls_three(self) -> None:
        self.match = build_match(board_size=9)
        self.handler = take_the_ball(self.match)
        self.nobody_in_reach()
        start = self.ball_flat()
        result = offer_low_pass(
            ENGINE, build_game(mode=GameMode.ADVANCED), self.match,
            key="skilled_pass",
        )
        self.assertEqual(self.ball_flat(), start + 3)
        self.assertIn("no teammate within three spaces", result.narration[0])
        self.assertEqual(result.next.step, FollowOnStep.BEGIN_LOOSE_BALL)
