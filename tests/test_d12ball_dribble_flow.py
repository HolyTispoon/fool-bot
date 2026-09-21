"""
The two dribbles as flow steps, and the cog wrappers around them.

The model half of rank O2 of Phase 3 of docs/model-discord-split.md.
`tests/test_d12ball_dribble_recording.py` asked the cog what a dribble
says and does next, off `tests/dribble_fixtures.py`, and was run green
before anything moved. This asks `d12ball.flow.effects` the same
questions off the same fixtures -- so the two agreeing is the move
having changed nothing.

It also covers what the new shape adds and the old code had nowhere to
put:

- the steps **do not save** (principle 9: a step mutates and returns,
  the caller writes it down),
- the cog wrapper saves **between** the step and the dispatch, which is
  the transition rule for Phases 2 to 5 -- and for these two cards that
  is a fix as well as a rule: a beaten Clear's exhaustion used to be
  charged *after* `apply_dribble_advance` had already persisted,
- a restart in the middle of the effect still comes back to the same
  prompt, which is the Phase 1 effect-choice branch catching it.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from d12ball.components import MatchState
from d12ball.flow import FollowOn, FollowOnStep
from d12ball.flow.effects import dribble_advance_step, dribble_burst_step
from d12ball.prompts import pending_prompt

from dribble_fixtures import DRIBBLE_CASES, ENGINE, FINISH, SPEED_CHOICE
from flow_stubs import chain_records_at
from save_patches import suppressed_cog_saves
from test_d12ball_dribble_recording import build_cog


def run_step(fixture):
    """The step this fixture's card names, asked directly."""
    step = (
        dribble_advance_step
        if fixture.key == "dribble_advance"
        else dribble_burst_step
    )
    return step(ENGINE, fixture.game, fixture.match, fixture.distance)


class DribbleStepTests(unittest.TestCase):
    """
    The steps, asked directly. No cog, no interaction, no event loop --
    which is most of the point: a web app reaches these with the match
    it already holds.
    """

    def test_every_branch_answers_what_the_cog_recorded(self) -> None:
        for case in DRIBBLE_CASES:
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
                self.assertEqual(match.ball_carrier_id, fixture.carrier_id)
                self.assertEqual(
                    (match.ball.zone, match.ball.space_index),
                    fixture.ball_space,
                )
                self.assertEqual(
                    match.board.meeple_position(fixture.carrier_id),
                    fixture.handler_space,
                )
                for player_id, tokens in fixture.exhaustion.items():
                    self.assertEqual(
                        match.exhaustion.get(player_id, 0), tokens, player_id,
                    )
                if fixture.ball_speed is not None:
                    self.assertEqual(match.ball.speed, fixture.ball_speed)

    def test_each_card_ends_where_its_fixtures_say(self) -> None:
        """
        Rank O2 is self-contained: it moves the handler and stops. An
        advance hands the turn to the speed choice; a burst has left
        the ball at 12 (the author, 2026-09-20) and hands it straight
        to the maneuver's tail. Both are real `FollowOnStep` members
        rather than strings this module agrees with itself about.
        """
        self.assertEqual(
            FollowOnStep.OFFER_SPEED_CHOICE.name, SPEED_CHOICE,
        )
        self.assertEqual(
            FollowOnStep.FINISH_MANEUVER_RESOLUTION.name, FINISH,
        )
        for case in DRIBBLE_CASES:
            with self.subTest(case=case.name):
                fixture = case.build()
                result = run_step(fixture)
                expected = (
                    FollowOnStep.OFFER_SPEED_CHOICE
                    if fixture.key == "dribble_advance"
                    else FollowOnStep.FINISH_MANEUVER_RESOLUTION
                )
                self.assertIs(result.next.step, expected)

    def test_the_steps_do_not_save(self) -> None:
        """
        Neither step may write the match: the wrapper does, once,
        immediately after. `save_games` is replaced at its own module
        rather than at a binding, so an import added to the flow
        package later is caught too.
        """
        recorder = mock.Mock()
        with suppressed_cog_saves(), mock.patch(
            "gamesaves.d12ball.storage.save_games", recorder,
        ):
            for case in DRIBBLE_CASES:
                run_step(case.build())

        recorder.assert_not_called()

    def test_a_restart_mid_effect_comes_back_to_the_same_prompt(
        self,
    ) -> None:
        """
        The step leaves the match waiting on the speed choice, and a
        coach may take hours over it. What `pending_prompt` answers
        after a `to_dict`/`from_dict` round trip has to be what it
        answered before -- see "Recovering a stuck game" in
        docs/design/recovery.md.
        """
        for case in DRIBBLE_CASES:
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


class DribbleWrapperTests(unittest.IsolatedAsyncioTestCase):
    """
    `D12Ball.apply_dribble_advance` / `apply_dribble_burst` and
    `dispatch_step_result` -- the Discord half, which is now four lines
    and an ordering.
    """

    async def test_the_save_lands_between_the_step_and_the_dispatch(
        self,
    ) -> None:
        """
        Principle 9, asserted as an order
        *and* as content: at the moment the save runs, the dribble
        must already have happened. A persist before the step writes a
        match that has not moved, and a persist after the dispatch is
        too late for a step whose next question reloads the match from
        the file.
        """
        for name in ("advance_plain", "burst_plain"):
            with self.subTest(case=name):
                fixture = next(
                    case.build() for case in DRIBBLE_CASES
                    if case.name == name
                )
                cog = build_cog()
                cog.games[fixture.game.game_id] = fixture.game
                calls: list[str] = []
                carrier_when_saved: list[object] = []

                def persist(game, saved_match) -> None:
                    calls.append("persist")
                    carrier_when_saved.append(saved_match.ball_carrier_id)

                async def refresh(*args, **kwargs) -> None:
                    calls.append("refresh")

                cog.persist = persist
                cog.refresh_match_image = refresh
                apply = (
                    cog.apply_dribble_advance
                    if fixture.key == "dribble_advance"
                    else cog.apply_dribble_burst
                )

                with chain_records_at(
                    cog, FollowOnStep.OFFER_SPEED_CHOICE, calls,
                ), chain_records_at(
                    cog, FollowOnStep.FINISH_MANEUVER_RESOLUTION, calls,
                ):
                    await apply(
                        SimpleNamespace(),
                        fixture.game,
                        fixture.match,
                        fixture.distance,
                    )

                # The advance ends on the speed choice; the burst has
                # set the speed itself and ends on the tail. Either
                # runs in the driver, and the one save comes after it
                # (principle 9), the board behind that.
                following = (
                    "offer_speed_choice"
                    if fixture.key == "dribble_advance"
                    else "finish_maneuver_resolution"
                )
                self.assertEqual(calls, [following, "persist", "refresh"])
                self.assertEqual(
                    carrier_when_saved, [fixture.carrier_id],
                )

    async def test_a_beaten_clears_exhaustion_is_saved_with_the_move(
        self,
    ) -> None:
        """
        The one thing this move changes about the bot, and it is a
        fix rather than a rule.

        `apply_dribble_advance` used to persist and *then* call
        `pay_clear_cost`, which charges two tokens and re-tests the
        Exhausted threshold -- so both writes happened after the save
        and the next click reloaded a defender who had never been
        charged. The step does the whole of the effect and the wrapper
        saves after it, which is exactly the class of bug principle 9
        exists for. Asserted on the state as it reaches `persist`.
        """
        for name in ("advance_beats_a_clear", "burst_beats_a_clear"):
            with self.subTest(case=name):
                fixture = next(
                    case.build() for case in DRIBBLE_CASES
                    if case.name == name
                )
                cog = build_cog()
                cog.games[fixture.game.game_id] = fixture.game
                saved: list[dict[str, int]] = []

                cog.persist = lambda game, match: saved.append(
                    dict(match.exhaustion),
                )
                apply = (
                    cog.apply_dribble_advance
                    if fixture.key == "dribble_advance"
                    else cog.apply_dribble_burst
                )

                await apply(
                    SimpleNamespace(),
                    fixture.game,
                    fixture.match,
                    fixture.distance,
                )

                self.assertEqual(len(saved), 1)
                for player_id, tokens in fixture.exhaustion.items():
                    self.assertEqual(
                        saved[0].get(player_id, 0), tokens, player_id,
                    )


if __name__ == "__main__":
    unittest.main()
