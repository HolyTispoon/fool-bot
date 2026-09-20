"""
The two deflections as one flow step, and the cog wrapper around it.

The model half of rank D1 of Phase 3 of docs/model-discord-split.md.
`tests/test_d12ball_deflect_recording.py` asked the cog what a Deflect
says and does next, off `tests/deflect_fixtures.py`, and was run green
before anything moved. This asks `d12ball.flow.effects.deflect_step`
the same questions off the same fixtures -- so the two agreeing is the
move having changed nothing.

It also covers what the new shape adds and the old code had nowhere to
put:

- the step **does not save** (principle 9: a step mutates and returns,
  the caller writes it down), where `knock_ball_back` saved the moment
  the ball moved,
- the cog wrapper saves **between** the step and the dispatch, which
  is the transition rule for Phases 2 to 5,
- `BEGIN_LOOSE_BALL` and `OFFER_SETUP_PASS_PUSH_BACK`, the two members
  this rank adds, are real and have rows in `D12Ball.follow_on_methods`,
- and the one this rank exists to settle: **`board_changed` is a fact
  about the position, and the frontend owns the write**. Every branch
  here moves the ball and every one of them says so, yet the
  persistent board message is written exactly as often as the old cog
  wrote it -- because `begin_loose_ball` draws the board under its own
  announcement and `D12Ball.follow_on_posts_its_own_board` declines the
  duplicate. See "Discord's rate limits" in docs/design/rate-limits.md.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from cogs.d12ball import D12Ball
from d12ball.components import MatchState
from d12ball.flow import FollowOn, FollowOnStep, StepResult
from d12ball.flow.effects import deflect_step, deflection_numbers
from d12ball.prompts import pending_prompt

from deflect_fixtures import (
    DEFLECT_CASES,
    ENGINE,
    LOOSE_BALL,
    PUSH_BACK,
)
from save_patches import suppressed_cog_saves
from test_d12ball_deflect_recording import build_cog, build_interaction


def case_named(name):
    """One fixture out of the table, built fresh."""
    return next(case.build() for case in DEFLECT_CASES if case.name == name)


def run_step(fixture):
    """The step both cards share, asked directly."""
    return deflect_step(ENGINE, fixture.match, fixture.key)


class DeflectStepTests(unittest.TestCase):
    """
    The step, asked directly. No cog, no interaction, no event loop --
    which is most of the point: a web app reaches this with the match
    it already holds.
    """

    def test_every_branch_answers_what_the_cog_recorded(self) -> None:
        for case in DEFLECT_CASES:
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
                self.assertEqual(match.ball_carrier_id, fixture.carrier_id)
                self.assertEqual(
                    (match.ball.zone, match.ball.space_index),
                    fixture.ball_space,
                )

    def test_the_board_moved_on_every_branch(self) -> None:
        """
        The claim the refresh economy below rests on. A deflection
        always takes a step of speed off the ball, even where the field
        clamped the distance to nothing, so there is no branch here
        that can honestly report the position unchanged.
        """
        for case in DEFLECT_CASES:
            with self.subTest(case=case.name):
                self.assertTrue(run_step(case.build()).board_changed)

    def test_the_distance_and_the_speed_drop_are_two_numbers(self) -> None:
        """
        **A Fullback's Clear goes back 4 and still takes 3 off** (the
        author, 2026-08-19). Derived from the distance instead, this
        read correctly right up until a Fullback was let near a Clear,
        which is why `deflection_numbers` returns both.
        """
        fullback = ENGINE.get_player_definition(
            case_named("clear_by_a_fullback").match.challenger_id,
        )
        self.assertEqual(deflection_numbers(fullback, "clear"), (4, 3, True))
        self.assertEqual(deflection_numbers(fullback, "deflect"), (2, 1, True))

        midfielder = ENGINE.get_player_definition(
            case_named("clear_plain").match.challenger_id,
        )
        self.assertEqual(
            deflection_numbers(midfielder, "clear"), (3, 3, False),
        )
        self.assertEqual(
            deflection_numbers(midfielder, "deflect"), (1, 1, False),
        )

    def test_the_two_new_members_are_real_and_have_rows(self) -> None:
        """
        Rank D1 adds two `FollowOnStep` members, and a member with no
        row in `D12Ball.follow_on_methods` raises inside a resolved
        maneuver one card at a time. The membership itself is asserted
        in `tests/test_d12ball_package_shape.py`; this is that the two
        this rank names are the two it recorded.
        """
        self.assertEqual(FollowOnStep.BEGIN_LOOSE_BALL.name, LOOSE_BALL)
        self.assertEqual(
            FollowOnStep.OFFER_SETUP_PASS_PUSH_BACK.name, PUSH_BACK,
        )
        cog = build_cog()
        table = D12Ball.follow_on_methods(cog)
        self.assertIs(
            table[FollowOnStep.BEGIN_LOOSE_BALL], cog.begin_loose_ball,
        )
        self.assertIs(
            table[FollowOnStep.OFFER_SETUP_PASS_PUSH_BACK],
            cog.offer_setup_pass_push_back,
        )

    def test_the_step_does_not_save(self) -> None:
        """
        The step may not write the match: the wrapper does, once,
        immediately after. `knock_ball_back` used to persist the moment
        the ball moved, and that call left with it. `save_games` is
        replaced at its own module rather than at a binding, so an
        import added to the flow package later is caught too.
        """
        recorder = mock.Mock()
        with suppressed_cog_saves(), mock.patch(
            "gamesaves.d12ball.storage.save_games", recorder,
        ):
            for case in DEFLECT_CASES:
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
        for case in DEFLECT_CASES:
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


class DeflectWrapperTests(unittest.IsolatedAsyncioTestCase):
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
        already have been knocked back. A persist before the step
        writes a match the deflection never happened in, and a persist
        after the dispatch is too late for a step whose next question
        reloads the match from the file -- which the loose-ball pick
        is, exactly.

        The refresh is in the order too, and where it is missing that
        is the point: two of the three branches hand over to something
        that draws the board itself.
        """
        for name, expected in (
            ("deflect_plain", ["persist", "begin_loose_ball"]),
            (
                "deflect_that_overshoots",
                ["persist", "refresh", "begin_shooter_choice"],
            ),
            (
                "deflect_beats_a_setup_pass",
                ["persist", "offer_setup_pass_push_back"],
            ),
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
                for step in (
                    "begin_loose_ball",
                    "begin_shooter_choice",
                    "offer_setup_pass_push_back",
                ):
                    setattr(cog, step, self._recorder(calls, step))

                await cog.apply_deflection(
                    SimpleNamespace(),
                    fixture.game,
                    fixture.match,
                    fixture.key,
                )

                self.assertEqual(calls, expected)
                self.assertEqual(ball_when_saved, [fixture.ball_space])

    @staticmethod
    def _recorder(calls: list[str], name: str):
        async def recorded(*args, **kwargs) -> None:
            calls.append(name)

        return recorded

    async def test_the_board_is_written_as_often_as_it_was_before(
        self,
    ) -> None:
        """
        **What rank D1 settles.** `board_changed` is True on every
        branch -- the ball moved -- and the persistent board message is
        still written exactly as often as the old cog wrote it, which
        is the number `tests/deflect_fixtures.py` recorded before the
        move. The model reports the position and the frontend owns the
        write, which is principle 8; the alternative, a step returning
        `board_changed=False` because Discord happens to redraw a
        moment later, would have put a rate-limit economy inside the
        rules.
        """
        for case in DEFLECT_CASES:
            with self.subTest(case=case.name):
                fixture = case.build()
                cog = build_cog()
                cog.games[fixture.game.game_id] = fixture.game

                with suppressed_cog_saves():
                    await cog.apply_deflection(
                        build_interaction(),
                        fixture.game,
                        fixture.match,
                        fixture.key,
                    )

                self.assertEqual(
                    cog.refresh_match_image.await_count, fixture.refreshes,
                )

    async def test_a_high_pass_keeps_its_refresh(self) -> None:
        """
        `begin_loose_ball` draws the board on every path but one: a
        High Pass announces without drawing, because the ball is on a
        player everybody can see and the board was posted by the pass
        itself. So the exemption rides on the same flag inside
        `follow_on_posts_its_own_board`.

        Rank D1 hands over no high passes -- rank O3 is what will --
        but the reading belongs with the rule rather than with the
        caller, and an untested branch of it is one that quietly stops
        drawing a board later.
        """
        cog = build_cog()
        self.assertFalse(
            D12Ball.follow_on_posts_its_own_board(
                cog,
                FollowOn(
                    FollowOnStep.BEGIN_LOOSE_BALL,
                    {"distance_moved": 2, "is_high_pass": True},
                ),
            ),
        )
        self.assertTrue(
            D12Ball.follow_on_posts_its_own_board(
                cog,
                FollowOn(
                    FollowOnStep.BEGIN_LOOSE_BALL, {"distance_moved": 2},
                ),
            ),
        )
        # And nothing else claims it: a follow-on that posts a prompt
        # over the board it was handed still needs the board drawn.
        for step in FollowOnStep:
            if step in (
                FollowOnStep.BEGIN_LOOSE_BALL,
                FollowOnStep.OFFER_SETUP_PASS_PUSH_BACK,
            ):
                continue
            with self.subTest(step=step.name):
                self.assertFalse(
                    D12Ball.follow_on_posts_its_own_board(
                        cog, FollowOn(step),
                    ),
                )

    async def test_a_prompt_or_nothing_still_redraws(self) -> None:
        """
        The suppression reads the follow-on, so a result that asks a
        question or ends the cascade is unaffected by it -- the board
        is redrawn for those exactly as it was before this rank.
        """
        cog = build_cog()
        cog.games["g1"] = case_named("deflect_plain").game
        interaction = build_interaction()

        await cog.dispatch_step_result(
            interaction,
            cog.games["g1"],
            case_named("deflect_plain").match,
            StepResult(narration=["Something moved."], board_changed=True),
        )

        self.assertEqual(cog.refresh_match_image.await_count, 1)


if __name__ == "__main__":
    unittest.main()
