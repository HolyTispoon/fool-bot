"""
The two deflections as one flow step, and the cog wrapper around it.

The model half of rank D1 of Phase 3 of docs/model-discord-split.md.
`tests/test_d12ball_deflection_recording.py` asked the cog what a
Deflect and a Clear say and do next, off
`tests/deflection_fixtures.py`, and was run green before anything
moved. This asks `d12ball.flow.effects.deflection_step` the same
questions off the same fixtures -- so the two agreeing is the move
having changed nothing.

It also covers what the new shape adds and the old code had nowhere to
put:

- the step **does not save** (principle 9: a step mutates and returns,
  the caller writes it down), where the old code saved inside
  `knock_ball_back` and again on the shot branch,
- the cog wrapper saves **between** the step and the dispatch, which
  is the transition rule for Phases 2 to 5,
- `BEGIN_LOOSE_BALL` and `OFFER_SETUP_PASS_PUSH_BACK`, the two members
  this rank adds, are real and have rows in
  `D12Ball.follow_on_methods`,
- and `FOLLOW_ONS_THAT_DRAW_THE_BOARD`, which is the answer this rank
  owed: a step says the board moved, and the frontend skips a write
  that the step it is handing to is about to make anyway. Asserted
  **for the rule and not only for this card**, since it is the answer
  for all eight of `begin_loose_ball`'s callers rather than for
  Deflect.

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
from cogs.d12ball.core import FOLLOW_ONS_THAT_DRAW_THE_BOARD
from d12ball.components import MatchState
from d12ball.flow import FollowOn, FollowOnStep, StepResult
from d12ball.flow.effects import deflection_numbers, deflection_step
from d12ball.prompts import pending_prompt

from deflection_fixtures import (
    DEFLECTION_CASES,
    ENGINE,
    LOOSE_BALL,
    SETUP_PASS_PUSH_BACK,
    SHOOTER_CHOICE,
)
from d12ball.flow import driver
from flow_stubs import chain_records_at, chain_stops_at
from save_patches import suppressed_cog_saves
from test_d12ball_deflection_recording import build_cog, build_interaction


def case_named(name):
    """One fixture out of the table, built fresh."""
    return next(
        case.build() for case in DEFLECTION_CASES if case.name == name
    )


def run_step(fixture):
    """The step both cards share, asked directly."""
    return deflection_step(ENGINE, fixture.match, fixture.key)


class DeflectionStepTests(unittest.TestCase):
    """
    The step, asked directly. No cog, no interaction, no event loop --
    which is most of the point: a web app reaches this with the match
    it already holds.
    """

    def test_every_branch_answers_what_the_cog_recorded(self) -> None:
        for case in DEFLECTION_CASES:
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

    def test_the_board_moved_on_every_branch(self) -> None:
        """
        The model's answer, and it is the same on all three endings:
        every deflection drives the ball back, or takes speed off it,
        or both. What differs is only what the **frontend** does with
        that, which is the next test down.
        """
        for case in DEFLECTION_CASES:
            with self.subTest(case=case.name):
                self.assertTrue(run_step(case.build()).board_changed)

    def test_the_overshoot_note_is_a_block_of_its_own(self) -> None:
        """
        Two blocks joined by the single space `dispatch_step_result`
        joins with, which is exactly how the old cog built the string:
        `f"{content} That overshoots..."`. Rank D3's own-goal paragraph
        went the other way -- one block -- because it was separated by
        a blank line and a second block would have carried a stray
        space in front of its newlines. A sentence that follows on the
        same line is a second block; a paragraph is not.
        """
        for name in (
            "deflect_that_overshoots_into_a_shot",
            "clear_that_overshoots_into_a_shot",
        ):
            with self.subTest(case=name):
                result = run_step(case_named(name))
                self.assertEqual(len(result.narration), 2)

    def test_the_distance_and_the_speed_drop_are_two_numbers(self) -> None:
        """
        One function and a key: a Deflect goes back 1 and drops the
        speed 1, a Clear 3 and 3 -- and a Fullback's +1 moves the
        distance alone. The two happen to match on an ordinary
        deflection, which is what made deriving one from the other read
        correctly right up until the Fullback was let near a Clear.
        """
        fullback = ENGINE.get_player_definition(
            case_named("deflect_by_a_fullback").challenger_id,
        )
        midfielder = ENGINE.get_player_definition(
            case_named("deflect_plain").challenger_id,
        )
        self.assertEqual(deflection_numbers(midfielder, "deflect"), (1, 1, False))
        self.assertEqual(deflection_numbers(midfielder, "clear"), (3, 3, False))
        self.assertEqual(deflection_numbers(fullback, "deflect"), (2, 1, True))
        self.assertEqual(deflection_numbers(fullback, "clear"), (4, 3, True))

    def test_the_two_new_members_are_real_and_have_rows(self) -> None:
        """
        Rank D1 adds two `FollowOnStep` members, and a member with no
        row in `D12Ball.follow_on_methods` raises inside a resolved
        maneuver one card at a time. The membership itself is asserted
        in `tests/test_d12ball_package_shape.py`; this is that the two
        this rank names are the two it recorded.
        """
        cog = build_cog()
        table = D12Ball.follow_on_methods(cog)
        for member_name, method_name in (
            (LOOSE_BALL, "begin_loose_ball"),
            (SETUP_PASS_PUSH_BACK, "offer_setup_pass_push_back"),
        ):
            with self.subTest(member=member_name):
                member = FollowOnStep[member_name]
                self.assertIs(table[member], getattr(cog, method_name))

    def test_the_step_does_not_save(self) -> None:
        """
        The step may not write the match: the wrapper does, once,
        immediately after. `save_games` is replaced at its own module
        rather than at a binding, so an import added to the flow
        package later is caught too.
        """
        recorder = mock.Mock()
        with suppressed_cog_saves(), mock.patch(
            "gamesaves.d12ball.storage.save_games", recorder,
        ):
            for case in DEFLECTION_CASES:
                run_step(case.build())

        recorder.assert_not_called()

    def test_a_restart_mid_effect_comes_back_to_the_same_prompt(
        self,
    ) -> None:
        """
        The step leaves the match between the deflection and whatever
        comes next, and a coach may take hours over that. What
        `pending_prompt` answers after a `to_dict`/`from_dict` round
        trip has to be what it answered before -- see "Recovering a
        stuck game" in docs/design/recovery.md.
        """
        for case in DEFLECTION_CASES:
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


class BoardWriteSuppressionTests(unittest.IsolatedAsyncioTestCase):
    """
    `FOLLOW_ONS_THAT_DRAW_THE_BOARD`, asserted as the rule it is rather
    than through the one card that needed it first.

    The rule: a `StepResult` saying the board moved gets one write,
    **unless** it is handing over to a step that puts the board up
    itself. That is a Discord economy -- one five-in-five bucket for
    every edit in a channel -- and rate limits are the frontend's
    (principle 8 in CLAUDE.md). The model's `board_changed` stays
    honest either way, which is what lets a web app redraw on all of
    them.
    """

    async def test_a_board_drawing_follow_on_is_not_written_in_front_of(
        self,
    ) -> None:
        for member in FollowOnStep:
            with self.subTest(member=member.name):
                cog = build_cog()
                # The dispatcher saves once for whatever the driver
                # ran (principle 9), so the stand-ins have to be
                # writable -- this test is about board writes and the
                # save is suppressed underneath it.
                with suppressed_cog_saves(), chain_stops_at(cog, member):
                    await cog.dispatch_step_result(
                        build_interaction(),
                        SimpleNamespace(game_id="g1", match_state=None),
                        SimpleNamespace(to_dict=dict),
                        StepResult(
                            narration=["x"],
                            board_changed=True,
                            next=FollowOn(member),
                        ),
                    )
                self.assertEqual(
                    cog.refresh_match_image.await_count,
                    0 if member in FOLLOW_ONS_THAT_DRAW_THE_BOARD else 1,
                )

    async def test_a_step_that_moved_nothing_is_never_written(self) -> None:
        """
        The suppression only ever removes a write. A result that says
        the board did not move gets none whatever it hands to, which is
        what `board_changed` meant before this rank and still does.
        """
        for member in FollowOnStep:
            with self.subTest(member=member.name):
                cog = build_cog()
                # The dispatcher saves once for whatever the driver
                # ran (principle 9), so the stand-ins have to be
                # writable -- this test is about board writes and the
                # save is suppressed underneath it.
                with suppressed_cog_saves(), chain_stops_at(cog, member):
                    await cog.dispatch_step_result(
                        build_interaction(),
                        SimpleNamespace(game_id="g1", match_state=None),
                        SimpleNamespace(to_dict=dict),
                        StepResult(next=FollowOn(member)),
                    )
                cog.refresh_match_image.assert_not_awaited()


class DeflectionWrapperTests(unittest.IsolatedAsyncioTestCase):
    """
    `D12Ball.apply_deflection` and `dispatch_step_result` -- the
    Discord half, which is now four lines and an ordering.
    """

    async def test_the_save_lands_between_the_step_and_the_dispatch(
        self,
    ) -> None:
        """
        The transition rule for Phases 2 to 5, asserted as an order
        *and* as content: at the moment the save runs, the ball must
        already have been driven back. A persist before the step writes
        a match nothing was deflected in, and a persist after the
        dispatch is too late for a step whose next question reloads the
        match from the file -- which the push-back prompt is, exactly.
        """
        for name, following in (
            ("deflect_plain", "begin_loose_ball"),
            ("deflect_that_overshoots_into_a_shot", "begin_shooter_choice"),
            ("deflect_beats_a_setup_pass", "offer_setup_pass_push_back"),
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
                member = FollowOnStep[following.upper()]
                stack = contextlib.ExitStack()
                with stack:
                    for step in (
                        LOOSE_BALL,
                        "BEGIN_SHOOTER_CHOICE",
                        SETUP_PASS_PUSH_BACK,
                    ):
                        stack.enter_context(
                            chain_records_at(
                                cog, FollowOnStep[step], calls,
                            ),
                        )
                    await cog.apply_deflection(
                        SimpleNamespace(),
                        fixture.game,
                        fixture.match,
                        fixture.key,
                    )

                # **Two saves where the driver runs the next step, one
                # where it does not.** The wrapper writes its own step
                # (the transition rule Phases 2-5 were built on), and
                # `dispatch_step_result` writes whatever
                # `driver.advance` ran after it -- principle 9's "the
                # driver's caller persists", now that the caller is
                # the dispatcher rather than each wrapper in turn. The
                # board write moves behind the driver's run for the
                # same reason: the position it draws is the one the
                # run finished on, which is what `BoardRefresher` was
                # already collapsing several writes into.
                expected = ["persist"]
                if driver.runs(member):
                    expected += [following, "persist"]
                    if fixture.refreshes:
                        expected.append("refresh")
                else:
                    if fixture.refreshes:
                        expected.append("refresh")
                    expected.append(following)
                self.assertEqual(calls, expected)
                self.assertEqual(
                    ball_when_saved,
                    [fixture.ball_space] * expected.count("persist"),
                )

    @staticmethod
    def _recorder(calls: list[str], name: str):
        async def recorded(*args, **kwargs) -> None:
            calls.append(name)

        return recorded

    async def test_a_loose_ball_still_costs_one_board_write(self) -> None:
        """
        The thing this rank must not change. A deflection that ends in
        a loose ball writes the persistent board **once**, from inside
        `begin_loose_ball`'s own announcement -- as it did before the
        move. The step now says `board_changed=True` where the old call
        site simply did not refresh, so without
        `FOLLOW_ONS_THAT_DRAW_THE_BOARD` this branch would have gone
        from one write to two for one click. See "Discord's rate
        limits" in docs/design/rate-limits.md.
        """
        fixture = case_named("deflect_plain")
        cog = build_cog()
        cog.games[fixture.game.game_id] = fixture.game

        with suppressed_cog_saves():
            await cog.apply_deflection(
                build_interaction(),
                fixture.game,
                fixture.match,
                fixture.key,
            )

        cog.refresh_match_image.assert_not_awaited()
        cog.begin_loose_ball.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
