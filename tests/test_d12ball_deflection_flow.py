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
from d12ball.components import PlayerRole, TeamSide
from d12ball.flow.effects import (
    deflection_numbers,
    deflection_step,
    offer_setup_pass_push_back,
    setup_pass_push_back_step,
)
from d12ball.prompts import PendingPrompt, PromptKind, pending, pending_prompt

from deflection_fixtures import (
    BEATEN_ADVANCED,
    DEFLECTION_CASES,
    ENGINE,
    OVERSHOOT_NOTE,
    advanced_game,
    defenders_waiting_at,
    deflected_to,
    stand_a_deflection,
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
        that, which is the next test down. A failed Setup Pass gambit
        is the exception, and says so: nothing moves until its coach
        has chosen how far.
        """
        for case in DEFLECTION_CASES:
            with self.subTest(case=case.name):
                fixture = case.build()
                self.assertEqual(
                    run_step(fixture).board_changed,
                    fixture.follow_on != SETUP_PASS_PUSH_BACK,
                )

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

    def test_only_the_challenger_is_offered_the_overshoot_shot(
        self,
    ) -> None:
        """
        An overshot deflection is the challenger's shot and nobody
        else's, even with a teammate standing on the same space -- the
        author, 2026-09-26. The standard deal parks the deflecting
        side's striker on that goal line, so each of these has a second
        defender there to be passed over; asserted here rather than
        assumed, or the case would stop testing the rule the moment the
        deal changed.
        """
        for name, distance in (
            ("deflect_that_overshoots_into_a_shot", 1),
            ("clear_that_overshoots_into_a_shot", 3),
        ):
            with self.subTest(case=name):
                fixture = case_named(name)
                waiting = defenders_waiting_at(fixture.match, distance)
                self.assertIn(fixture.challenger_id, waiting)
                self.assertGreater(len(waiting), 1)

                result = run_step(fixture)
                self.assertEqual(
                    result.next.kwargs["candidates"],
                    [fixture.challenger_id],
                )

    def test_a_clear_that_runs_past_its_challenger_sets_up_no_shot(
        self,
    ) -> None:
        """
        The other half of the same rule: a Clear can overshoot from
        spaces its challenger is not driven with, and the defender
        waiting where the ball stops is not the challenger -- so there
        is no shot, and the ball lands as any deflection's does.
        """
        fixture = case_named("clear_that_overshoots_past_its_challenger")
        waiting = defenders_waiting_at(fixture.match, 3)
        self.assertTrue(waiting)
        self.assertNotIn(fixture.challenger_id, waiting)

        result = run_step(fixture)
        self.assertEqual(result.next.step, FollowOnStep[LOOSE_BALL])

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



def failed_setup_pass(
    key: str,
    role: PlayerRole = PlayerRole.MIDFIELDER,
    back_from_own_goal=None,
):
    """A Setup Pass that `key` has just beaten, and the challenger who
    played it -- nothing moved yet."""
    match, _, challenger = stand_a_deflection(
        BEATEN_ADVANCED, key, role=role,
        back_from_own_goal=back_from_own_goal,
    )
    return advanced_game(), match, challenger


def flat(match) -> int:
    return match.board.flat_index(match.ball.zone, match.ball.space_index)


class FailedSetupPassGambitTests(unittest.TestCase):
    """
    **A failed Setup Pass gambit** (Law 19.7.7-19.7.8, the author,
    2026-09-27): the card that beat the pass moves the ball back once,
    as far as its coach chooses -- 1, 2 or 3 for a Deflect, 2, 3 or 4
    for a Clear, one more each for a Fullback -- and it lands as any
    deflection does. Of the distances that run out of field only the
    shortest is offered, and that one is the challenger's shot where
    they stand on the last space.
    """

    def test_the_distances_are_the_beating_cards(self) -> None:
        for key, role, expected in (
            ("deflect", PlayerRole.MIDFIELDER, (1, 2, 3)),
            ("clear", PlayerRole.MIDFIELDER, (2, 3, 4)),
            ("deflect", PlayerRole.FULLBACK, (2, 3, 4)),
            ("clear", PlayerRole.FULLBACK, (3, 4, 5)),
        ):
            with self.subTest(key=key, role=role):
                _, match, _ = failed_setup_pass(key, role)
                self.assertEqual(
                    ENGINE.setup_pass_push_back_range(match, key), expected,
                )

    def test_a_blaze_turning_a_deflect_into_a_clear_takes_the_clears(
        self,
    ) -> None:
        """The range is the *resolving* card's: a Deflect a blaze or an
        Overdrive resolves as a Clear sends it 2, 3 or 4."""
        _, match, _ = failed_setup_pass("deflect")
        self.assertEqual(
            ENGINE.setup_pass_push_back_range(match, "clear"), (2, 3, 4),
        )

    def test_only_the_shortest_distance_off_the_field_is_offered(
        self,
    ) -> None:
        for key, back, expected in (
            ("deflect", 5, [1, 2, 3]),
            ("deflect", 1, [1, 2]),
            ("deflect", 0, [1]),
            ("clear", 5, [2, 3, 4]),
            ("clear", 2, [2, 3]),
            ("clear", 1, [2]),
        ):
            with self.subTest(key=key, back=back):
                game, match, _ = failed_setup_pass(
                    key, back_from_own_goal=back,
                )
                distances = ENGINE.setup_pass_push_back_distances(
                    game, match,
                )
                self.assertEqual(distances, expected)
                overshoot = ENGINE.setup_pass_push_back_to_goal_zone(
                    match, distances,
                )
                self.assertEqual(
                    overshoot, expected[-1] if expected[-1] > back else None,
                )

    def test_the_coach_who_beat_it_is_asked_before_anything_moves(
        self,
    ) -> None:
        game, match, _ = failed_setup_pass("deflect", back_from_own_goal=5)
        before = flat(match)

        self.assertEqual(
            deflection_step(ENGINE, match, "deflect").next.step,
            FollowOnStep[SETUP_PASS_PUSH_BACK],
        )
        result = offer_setup_pass_push_back(ENGINE, game, match)

        self.assertIsInstance(result.next, PendingPrompt)
        self.assertIs(result.next.kind, PromptKind.SETUP_PASS_PUSH_BACK)
        self.assertEqual(flat(match), before)
        asked = pending_prompt(ENGINE, game, match)
        self.assertIs(asked.kind, PromptKind.SETUP_PASS_PUSH_BACK)
        self.assertEqual(asked.options.distances, (1, 2, 3))

    def test_the_chosen_distance_is_the_one_move(self) -> None:
        game, match, _ = failed_setup_pass("clear", back_from_own_goal=5)
        landing = deflected_to(match, 4)

        result = setup_pass_push_back_step(ENGINE, game, match, distance=4)

        self.assertEqual((match.ball.zone, match.ball.space_index), landing)
        self.assertEqual(match.ball.speed, 2)
        self.assertEqual(
            result.narration,
            [
                f"**{ENGINE.maneuver_name('clear')}** beat the "
                f"**{ENGINE.maneuver_name('setup_pass')}**: the ball "
                "moves 4 spaces back. Ball speed is now 2."
            ],
        )
        self.assertTrue(result.board_changed)
        self.assertEqual(result.next.step, FollowOnStep[LOOSE_BALL])

    def test_the_overshoot_is_the_challengers_shot_on_the_last_space(
        self,
    ) -> None:
        game, match, challenger = failed_setup_pass(
            "deflect", back_from_own_goal=1,
        )
        match.move_meeple(
            challenger, *match.own_goal_restart_space(TeamSide.HOME),
        )

        result = setup_pass_push_back_step(ENGINE, game, match, distance=2)

        self.assertEqual(result.narration[-1], OVERSHOOT_NOTE)
        self.assertEqual(result.next.step, FollowOnStep[SHOOTER_CHOICE])
        self.assertEqual(result.next.kwargs["candidates"], [challenger])
        self.assertEqual(match.ball.possession, TeamSide.VISITING)

    def test_stopping_on_the_last_space_is_not_the_overshoot(self) -> None:
        game, match, challenger = failed_setup_pass(
            "deflect", back_from_own_goal=1,
        )
        match.move_meeple(
            challenger, *match.own_goal_restart_space(TeamSide.HOME),
        )

        result = setup_pass_push_back_step(ENGINE, game, match, distance=1)

        self.assertEqual(result.next.step, FollowOnStep[LOOSE_BALL])

    def test_one_distance_is_played_without_asking(self) -> None:
        """On the last space already, only the shortest distance runs
        out of field and nothing else is on it -- so nothing is asked,
        and the challenger standing there shoots."""
        game, match, challenger = failed_setup_pass(
            "deflect", back_from_own_goal=0,
        )

        result = offer_setup_pass_push_back(ENGINE, game, match)

        self.assertIsInstance(result.next, FollowOn)
        self.assertEqual(result.next.step, FollowOnStep[SHOOTER_CHOICE])
        self.assertEqual(result.next.kwargs["candidates"], [challenger])


if __name__ == "__main__":
    unittest.main()
