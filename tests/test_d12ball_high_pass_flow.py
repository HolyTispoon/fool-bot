"""
The two passes of rank O3 as flow steps, and the cog wrappers around
them.

The model half of rank O3 of Phase 3 of docs/model-discord-split.md.
`tests/test_d12ball_high_pass_recording.py` asked the cog what a High
Pass and a Setup Pass say and do next, off
`tests/high_pass_fixtures.py`, and was run green before anything moved.
This asks the model the same questions off the same fixtures -- so the
two agreeing is the move having changed nothing.

It also covers what the new shape adds and the old code had nowhere to
put:

- the steps **do not save** (principle 9: a step mutates and returns,
  the caller writes it down), where the old code saved inside
  `throw_high_pass` and again on every branch below it,
- each cog wrapper saves **between** the step and the dispatch, which
  is the transition rule for Phases 2 to 5,
- `BEGIN_HIGH_PASS_CONTEST`, the one member this rank adds, is real
  and has a row in `D12Ball.follow_on_methods`,
- and `follow_on_draws_the_board`, which is what this rank had to
  widen: `begin_run_back` is the first follow-on that draws a board
  only *sometimes*, and the argument that decides it is `new_play`.

Nothing a coach sees changed in this rank: the message count, the
board writes and the text are all what the recording took off the old
cog.
"""

from __future__ import annotations

import contextlib
import unittest
from types import SimpleNamespace
from unittest import mock

from cogs.d12ball import D12Ball
from cogs.d12ball.core import (
    FOLLOW_ONS_THAT_DRAW_THE_BOARD,
    follow_on_draws_the_board,
)
from d12ball.components import MatchState
from d12ball.flow import FollowOn, FollowOnStep, StepResult
from d12ball.flow import driver
from d12ball.flow.effects import (
    high_pass_step,
    setup_pass_out_step,
    setup_pass_speed_step,
    setup_pass_step,
    throw_high_pass,
)
from d12ball.prompts import pending_prompt

from high_pass_fixtures import (
    ENGINE,
    HIGH_PASS_CONTEST,
    PASS_CASES,
)
from flow_stubs import chain_records_at, chain_stops_at, lead_in_of
from save_patches import suppressed_cog_saves
from test_d12ball_high_pass_recording import (
    FOLLOW_ONS,
    build_cog,
    build_interaction,
    drive,
)


def case_named(name):
    """One fixture out of the table, built fresh."""
    return next(case.build() for case in PASS_CASES if case.name == name)


def run_step(fixture):
    """
    The step the fixture's entry point runs, asked directly -- one of
    the rank's four.
    """
    if fixture.entry == "high_pass":
        return high_pass_step(ENGINE, fixture.match, fixture.distance)
    if fixture.entry == "setup_pass":
        return setup_pass_step(ENGINE, fixture.match, fixture.distance)
    if fixture.entry == "setup_pass_out":
        return setup_pass_out_step(fixture.match)
    if fixture.entry == "setup_pass_speed":
        return setup_pass_speed_step(ENGINE, fixture.match)
    raise AssertionError(f"unknown entry {fixture.entry!r}")


class PassStepTests(unittest.TestCase):
    """
    The steps, asked directly. No cog, no interaction, no event loop --
    which is most of the point: a web app reaches these with the match
    it already holds.
    """

    def test_every_branch_answers_what_the_cog_recorded(self) -> None:
        for case in PASS_CASES:
            with self.subTest(case=case.name):
                fixture = case.build()
                result = run_step(fixture)

                # The cog joins the lines on a single space, which is
                # how the narration reached the next step before.
                self.assertEqual(
                    " ".join(result.narration), fixture.narration,
                )
                self.assertEqual(result.board_changed, fixture.board_changed)

                self.assertIsInstance(result.next, FollowOn)
                self.assertEqual(result.next.step.name, fixture.follow_on)
                self.assertEqual(
                    dict(result.next.kwargs), fixture.follow_on_kwargs,
                )
                # The narration is the result's, never the follow-on's
                # -- how the two go together is the frontend's call.
                self.assertNotIn("lead_in", result.next.kwargs)

                match = fixture.match
                self.assertEqual(match.ball.possession, fixture.possession)
                self.assertEqual(match.ball.speed, fixture.ball_speed)
                self.assertEqual(
                    (match.ball.zone, match.ball.space_index),
                    fixture.ball_space,
                )
                self.assertEqual(match.ball_carrier_id, fixture.carrier_id)
                self.assertEqual(
                    match.pending_high_pass_overshoot,
                    fixture.overshoot_flag,
                )
                self.assertEqual(
                    match.pending_ball_recovery, fixture.ball_recovery,
                )
                self.assertEqual(
                    match.pending_effect_continuation, fixture.continuation,
                )

    def test_only_the_speed_half_moved_nothing(self) -> None:
        """
        `board_changed` is the position's answer, and on this rank it
        is True everywhere except the one step that is not a pass at
        all: Setup Pass's speed choice records the continuation and
        asks, and the speed it is about is set by the answer rather
        than here.
        """
        for case in PASS_CASES:
            with self.subTest(case=case.name):
                fixture = case.build()
                self.assertEqual(
                    run_step(fixture).board_changed,
                    fixture.entry != "setup_pass_speed",
                )

    def test_the_overshoot_note_rides_in_the_set_up_s_own_block(
        self,
    ) -> None:
        """
        Two blocks joined by the single space `dispatch_step_result`
        joins with, exactly as the old cog built the string -- and the
        ball speed note is part of the second rather than a third,
        because it is appended without a space of its own.
        """
        result = run_step(case_named("an_overshoot_into_a_set_up"))
        self.assertEqual(len(result.narration), 2)
        self.assertTrue(result.narration[1].endswith("(-2)."))

    def test_a_move_that_costs_nothing_says_nothing(self) -> None:
        """
        The ball speed modifier is the speed halved and rounded down,
        so a walking ball pays none -- and the note is absent rather
        than reading "(0)". See "What a message says" in
        docs/design/naming-and-wording.md.
        """
        result = run_step(case_named("an_overshoot_with_no_modifier_to_pay"))
        self.assertNotIn("ball speed modifier", " ".join(result.narration))

    def test_the_beaten_intercept_is_one_block_not_two(self) -> None:
        """
        A paragraph separated by a blank line stays inside the block it
        is charged against: the blocks are joined on a single space, so
        a second block would carry a stray space in front of its
        newlines. Rank D2 settled this on the Intercept overshoot and
        this is the same rule on the other side of the same card.
        """
        result = run_step(
            case_named("a_beaten_intercept_leaves_the_reception_alone"),
        )
        self.assertEqual(len(result.narration), 1)
        self.assertIn("\n\n**Intercept** was beaten", result.narration[0])

    def test_a_throw_that_moved_nothing_says_so_in_words(self) -> None:
        """
        `throw_high_pass` words a clamped throw rather than reporting
        "the ball moves 0 spaces forward", which reads as a bug -- and
        a coach sees it, since the passer cannot shoot off it.
        """
        fixture = case_named("nowhere_left_to_throw_it")
        match = fixture.match
        overshot, actual_distance, content = throw_high_pass(
            match,
            match.ball.possession,
            2,
            ENGINE.get_player_definition(match.active_player_id),
        )
        self.assertTrue(overshot)
        self.assertEqual(actual_distance, 0)
        self.assertNotIn("0 spaces", content)
        self.assertIn("comes straight back down on it", content)

    def test_the_new_member_is_real_and_has_a_row(self) -> None:
        """
        Rank O3 adds one `FollowOnStep` member, and a member with no
        row in `D12Ball.follow_on_methods` raises inside a resolved
        maneuver one card at a time. The membership itself is asserted
        in `tests/test_d12ball_package_shape.py`; this is that the one
        this rank names is the one it recorded.
        """
        cog = build_cog()
        member = FollowOnStep[HIGH_PASS_CONTEST]
        # **Still the cog's after Phase 6**, and the board write in
        # front of it is why -- see `MODEL_STEPS` in
        # `d12ball/flow/driver.py` and
        # `test_the_high_pass_contest_is_drawn_in_front_of` below.
        self.assertNotIn(member, driver.MODEL_STEPS)
        self.assertIs(
            D12Ball.follow_on_methods(cog)[member],
            cog.begin_high_pass_contest,
        )

    def test_the_steps_do_not_save(self) -> None:
        """
        A step may not write the match: the wrapper does, once,
        immediately after. `save_games` is replaced at its own module
        rather than at a binding, so an import added to the flow
        package later is caught too.
        """
        recorder = mock.Mock()
        with suppressed_cog_saves(), mock.patch(
            "gamesaves.d12ball.storage.save_games", recorder,
        ):
            for case in PASS_CASES:
                run_step(case.build())

        recorder.assert_not_called()

    def test_a_restart_mid_effect_comes_back_to_the_same_prompt(
        self,
    ) -> None:
        """
        The step leaves the match between the pass and whatever comes
        next, and a coach may take hours over that. What
        `pending_prompt` answers after a `to_dict`/`from_dict` round
        trip has to be what it answered before -- see "Recovering a
        stuck game" in docs/design/recovery.md.

        Setup Pass is the one card of the twelve where this is not a
        formality: the continuation its speed half leaves behind is
        what the rest of the pass is, and a restart that lost it would
        hand the turn back with the pass silently unspent.
        """
        for case in PASS_CASES:
            with self.subTest(case=case.name):
                fixture = case.build()
                run_step(fixture)

                before = pending_prompt(ENGINE, fixture.game, fixture.match)
                restored = MatchState.from_dict(
                    fixture.match.to_dict(), ENGINE.basic_ruleset,
                )
                after = pending_prompt(ENGINE, fixture.game, restored)

                self.assertEqual(before.kind, after.kind)
                self.assertEqual(before.ask, after.ask)
                self.assertEqual(
                    (restored.ball.zone, restored.ball.space_index),
                    fixture.ball_space,
                )
                self.assertEqual(restored.ball.speed, fixture.ball_speed)
                self.assertEqual(
                    restored.pending_effect_continuation,
                    fixture.continuation,
                )
                self.assertEqual(
                    restored.pending_high_pass_overshoot,
                    fixture.overshoot_flag,
                )


class BoardWriteSuppressionTests(unittest.IsolatedAsyncioTestCase):
    """
    `follow_on_draws_the_board`, which rank O3 had to widen.

    The rule is rank D1's and unchanged: a `StepResult` saying the
    board moved gets one write, **unless** it is handing over to a step
    that puts the board up itself. What this rank found is that
    `begin_run_back` is the first such step that draws one only
    sometimes -- a new play posts and pins a board, an ordinary run
    back after a steal draws nothing -- so the answer is read off the
    follow-on's own arguments as well as its member. Still the step's
    answer and not the calling card's, which is what lets the callers
    still to be lifted inherit it.
    """

    def test_a_new_play_run_back_draws_its_own_board(self) -> None:
        self.assertTrue(
            follow_on_draws_the_board(
                FollowOn(FollowOnStep.BEGIN_RUN_BACK, {"new_play": True}),
            )
        )

    def test_an_ordinary_run_back_does_not(self) -> None:
        """
        Rank D2's steal ends on this member with no `new_play`, and it
        refreshed the board before handing over -- as it still must.
        """
        for kwargs in ({}, {"speed_choice_after": True}, {"new_play": False}):
            with self.subTest(kwargs=kwargs):
                self.assertFalse(
                    follow_on_draws_the_board(
                        FollowOn(FollowOnStep.BEGIN_RUN_BACK, kwargs),
                    )
                )

    async def test_a_pass_that_goes_out_still_costs_one_board_write(
        self,
    ) -> None:
        """
        The thing this rank must not change. Both passes that run out
        of play write the persistent board **once**, from inside the
        new play's own reset -- as they did before the move. The step
        now says `board_changed=True` where the old call site simply
        did not refresh, so without the `new_play` clause above these
        two branches would have gone from one write to two for one
        click. See "Discord's rate limits" in
        docs/design/rate-limits.md.
        """
        for name in (
            "nowhere_left_to_throw_it",
            "setup_pass_with_no_distance_to_offer",
        ):
            with self.subTest(case=name):
                fixture = case_named(name)
                cog = build_cog()
                cog.games[fixture.game.game_id] = fixture.game

                with suppressed_cog_saves():
                    await drive(cog, fixture, build_interaction())

                cog.refresh_match_image.assert_not_awaited()
                cog.begin_run_back.assert_awaited_once()

    async def test_the_high_pass_contest_is_drawn_in_front_of(
        self,
    ) -> None:
        """
        The other half of the same question, and the reason this rank's
        contest is a member of its own. `begin_loose_ball` draws no
        board for a High Pass -- the ball is on a receiver both coaches
        watched catch it -- so the board the pass moved has to be
        written before it, which is what the old cog did.
        """
        fixture = case_named("a_long_pass_into_a_contest")
        self.assertNotIn(
            FollowOnStep.BEGIN_HIGH_PASS_CONTEST,
            FOLLOW_ONS_THAT_DRAW_THE_BOARD,
        )
        cog = build_cog()
        cog.games[fixture.game.game_id] = fixture.game

        with suppressed_cog_saves():
            await drive(cog, fixture, build_interaction())

        cog.refresh_match_image.assert_awaited_once()
        cog.begin_high_pass_contest.assert_awaited_once()


class PassWrapperTests(unittest.IsolatedAsyncioTestCase):
    """
    The four cog wrappers and `dispatch_step_result` -- the Discord
    half, which is now four lines and an ordering apiece.
    """

    async def test_the_save_lands_between_the_step_and_the_dispatch(
        self,
    ) -> None:
        """
        The transition rule for Phases 2 to 5, asserted as an order
        *and* as content: at the moment the save runs, the ball must
        already be where the pass left it. A persist before the step
        writes a match nothing was thrown in, and a persist after the
        dispatch is too late for a step whose next question reloads
        the match from the file -- which every one of these is.
        """
        for name in (
            "two_spaces_into_a_set_up",
            "nowhere_left_to_throw_it",
            "a_long_pass_into_a_contest",
            "the_speed_before_the_pass",
            "setup_pass_onto_nobody",
            "setup_pass_with_no_distance_to_offer",
        ):
            with self.subTest(case=name):
                fixture = case_named(name)
                cog = build_cog()
                cog.games[fixture.game.game_id] = fixture.game
                calls: list[str] = []
                ball_when_saved: list[object] = []

                def persist(game, saved_match) -> None:
                    calls.append("persist")
                    ball_when_saved.append(
                        (saved_match.ball.zone, saved_match.ball.space_index)
                    )

                async def refresh(*args, **kwargs) -> None:
                    calls.append("refresh")

                cog.persist = persist
                cog.refresh_match_image = refresh
                stack = contextlib.ExitStack()
                with stack:
                    for key, (step, _) in FOLLOW_ONS.items():
                        stack.enter_context(
                            chain_records_at(
                                cog, FollowOnStep[key], calls, step,
                            ),
                        )
                    await drive(cog, fixture, SimpleNamespace())

                # **Two saves where the driver runs the next step.**
                # The wrapper writes its own step and
                # `dispatch_step_result` writes whatever
                # `driver.advance` ran after it -- principle 9 with
                # the dispatcher as the driver's caller. The board
                # write follows the run rather than preceding it, for
                # the reason `BoardRefresher` collapses a cascade's
                # writes already: the position worth drawing is the
                # one the run finished on.
                member = FollowOnStep[fixture.follow_on]
                taken = FOLLOW_ONS[fixture.follow_on][0]
                if driver.runs(member):
                    expected = [taken, "persist"]
                    if fixture.refreshes:
                        expected.append("refresh")
                else:
                    expected = ["persist"]
                    if fixture.refreshes:
                        expected.append("refresh")
                    expected.append(taken)
                self.assertEqual(calls, expected)
                self.assertEqual(ball_when_saved, [fixture.ball_space])

    async def test_no_branch_posts_a_message_of_its_own(self) -> None:
        """
        A resolved maneuver is one message and one board refresh. The
        narration opens whatever the result hands to, rather than being
        posted in front of it -- which is `dispatch_step_result`'s
        whole job and what keeps this rank at the request count the
        recording measured.
        """
        for case in PASS_CASES:
            with self.subTest(case=case.name):
                fixture = case.build()
                cog = build_cog()
                cog.games[fixture.game.game_id] = fixture.game
                interaction = build_interaction()

                member = FollowOnStep[fixture.follow_on]
                with chain_stops_at(cog, member) as taken, \
                        suppressed_cog_saves():
                    await drive(cog, fixture, interaction)

                interaction.followup.send.assert_not_awaited()
                self.assertEqual(lead_in_of(taken), fixture.narration)


if __name__ == "__main__":
    unittest.main()
