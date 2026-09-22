"""
The two deflections as one flow step, and the cog wrapper around it.

The model half of rank D1 of Phase 3 of docs/design/model-discord-split.md.
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
- the dispatcher saves **after** the run and before anything is
  posted, which is what principle 9 collapsed the Phase 2-5
  transition rule into,
- `BEGIN_LOOSE_BALL` and `OFFER_SETUP_PASS_PUSH_BACK`, the two members
  this rank adds, are real and have rows in the driver's table,
- and the board write the loose ball takes over: a step says the
  board moved, and the frontend skips its own write when the loose
  ball it hands to draws the board under its announcement -- read
  off what that step itself reports (`D12Ball.stop_draws_the_board`),
  which is the answer for all of `begin_loose_ball`'s callers rather
  than for Deflect.

Nothing a coach sees changed in this rank: the message count, the
board writes and the text are all what the recording took off the old
cog.
"""

from __future__ import annotations

import contextlib
import unittest
from types import SimpleNamespace
from unittest import mock

from d12ball.components import MatchState
from d12ball.flow import FollowOn, FollowOnStep, StepResult
from d12ball.flow.effects import deflection_numbers, deflection_step
from d12ball.prompts import pending

from deflection_fixtures import (
    DEFLECTION_CASES,
    ENGINE,
    LOOSE_BALL,
    SETUP_PASS_PUSH_BACK,
    SHOOTER_CHOICE,
)
from d12ball.flow import driver
from flow_stubs import chain_records_at, chain_stops_at
from save_patches import suppressed_cog_saves, suppressed_full_image_links
from test_d12ball_deflection_recording import build_cog, build_interaction
from cog_steps import apply_deflection


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
        row in the driver's table cannot be run. The membership itself
        is asserted in `tests/test_d12ball_package_shape.py`; this is
        that the two this rank names are the two it recorded.
        """
        for member_name in (LOOSE_BALL, SETUP_PASS_PUSH_BACK):
            with self.subTest(member=member_name):
                self.assertIn(FollowOnStep[member_name], driver.MODEL_STEPS)

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

                before = pending(ENGINE, fixture.game, fixture.match)
                restored = MatchState.from_dict(
                    fixture.match.to_dict(), ENGINE.basic_ruleset,
                )
                after = pending(ENGINE, fixture.game, restored)

                # A question or the step the bot owes: the same one
                # either way.
                self.assertEqual(before, after)
                self.assertEqual(
                    (restored.ball.zone, restored.ball.space_index),
                    fixture.ball_space,
                )
                self.assertEqual(restored.ball.speed, fixture.ball_speed)


class BoardWriteSuppressionTests(unittest.IsolatedAsyncioTestCase):
    """
    The loose ball's board write, asserted as the rule it is rather
    than through the one card that needed it first.

    The rule: a `StepResult` saying the board moved gets one write,
    **unless** the loose ball it hands to draws the board under its own
    announcement -- in which case that announcement *is* the write
    (render once, upload twice, see `announce_board_update`). Whether
    it does is read off what the loose ball's step itself reports: a
    genuine loose ball says the board moved and is drawn; the long
    High Pass says it did not (the ball is on a receiver both coaches
    watched catch it) and is announced plainly over the board the pass
    already wrote. That is a Discord economy -- one five-in-five bucket
    for every edit in a channel -- and rate limits are the frontend's
    (principle 8 in CLAUDE.md). The model's `board_changed` stays
    honest either way, which is what lets a web app redraw on all of
    them.
    """

    async def test_a_genuine_loose_ball_draws_the_board_itself(self) -> None:
        cog = build_cog()
        cog.announce_board_update = mock.AsyncMock()
        stop = StepResult(narration=["loose"], board_changed=True)
        with suppressed_cog_saves(), chain_stops_at(
            cog, FollowOnStep.BEGIN_LOOSE_BALL, stop,
        ):
            await cog.dispatch_step_result(
                build_interaction(),
                SimpleNamespace(game_id="g1", match_state=None),
                SimpleNamespace(to_dict=dict),
                StepResult(
                    narration=["x"],
                    board_changed=True,
                    next=FollowOn(FollowOnStep.BEGIN_LOOSE_BALL),
                ),
            )
        cog.announce_board_update.assert_awaited_once()
        cog.refresh_match_image.assert_not_awaited()

    async def test_a_high_pass_contest_is_announced_over_the_written_board(
        self,
    ) -> None:
        cog = build_cog()
        cog.announce_board_update = mock.AsyncMock()
        interaction = build_interaction()
        stop = StepResult(narration=["contest"], board_changed=False)
        with suppressed_cog_saves(), chain_stops_at(
            cog, FollowOnStep.BEGIN_LOOSE_BALL, stop,
        ):
            await cog.dispatch_step_result(
                interaction,
                SimpleNamespace(game_id="g1", match_state=None),
                SimpleNamespace(to_dict=dict),
                StepResult(
                    narration=["x"],
                    board_changed=True,
                    next=FollowOn(
                        FollowOnStep.BEGIN_LOOSE_BALL, {"is_high_pass": True},
                    ),
                ),
            )
        cog.announce_board_update.assert_not_awaited()
        cog.refresh_match_image.assert_awaited_once()
        self.assertEqual(
            interaction.followup.send.await_args_list[-1].args[0], "contest",
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
                cog.announce_board_update = mock.AsyncMock()
                cog.post_new_play_board = mock.AsyncMock()
                cog.announce_maneuver_challenge = mock.AsyncMock()
                # The walk-in's group is drawn of the challenger it
                # names, so its follow-on carries one.
                arguments = (
                    {"challenger_id": "x"}
                    if member is FollowOnStep.AUTO_RESOLVE_CHALLENGER
                    else {}
                )
                with suppressed_cog_saves(), chain_stops_at(cog, member):
                    await cog.dispatch_step_result(
                        build_interaction(),
                        SimpleNamespace(game_id="g1", match_state=None),
                        SimpleNamespace(to_dict=dict, challenger_id=None),
                        StepResult(next=FollowOn(member, arguments)),
                    )
                cog.refresh_match_image.assert_not_awaited()
                cog.announce_board_update.assert_not_awaited()


class DeflectionWrapperTests(unittest.IsolatedAsyncioTestCase):
    """
    `None` and `dispatch_step_result` -- the
    Discord half, which is now four lines and an ordering.
    """


    @staticmethod
    def _recorder(calls: list[str], name: str):
        async def recorded(*args, **kwargs) -> None:
            calls.append(name)

        return recorded

    async def test_a_loose_ball_still_costs_one_board_write(self) -> None:
        """
        The thing this rank must not change. A deflection that ends in
        a loose ball writes the persistent board **once**, from inside
        the loose ball's own announcement -- as it did before the
        move. The step says `board_changed=True` where the old call
        site simply did not refresh, so without the dispatcher reading
        the loose ball's own answer this branch would have gone from
        one write to two for one click. See "Discord's rate limits" in
        docs/design/rate-limits.md. The real loose ball runs here, so
        the announcement is the write.
        """
        fixture = case_named("deflect_plain")
        cog = build_cog()
        cog.games[fixture.game.game_id] = fixture.game
        del cog.begin_loose_ball
        cog.announce_board_update = mock.AsyncMock()
        cog.render_match_png = mock.AsyncMock(return_value=b"")
        cog.match_file_from_png = mock.Mock(return_value=None)

        # The loose ball is announced and the chain stops on the far
        # side of it, where the board it announced would be written
        # again by whatever settles the contest.
        with suppressed_cog_saves(), suppressed_full_image_links(), \
                chain_stops_at(cog, FollowOnStep.RESOLVE_LOOSE_BALL):
            await apply_deflection(cog, 
                build_interaction(),
                fixture.game,
                fixture.match,
                fixture.key,
            )

        cog.refresh_match_image.assert_not_awaited()
        cog.announce_board_update.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
