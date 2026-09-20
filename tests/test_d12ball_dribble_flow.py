"""
The two dribbles as flow steps, and the cog wrappers around them.

The model half of rank O2 of Phase 3 of docs/model-discord-split.md.
`tests/test_d12ball_dribble_recording.py` asked the cog what a dribble
says and does next, off `tests/dribble_fixtures.py`, and was run green
before anything moved. This asks `d12ball.flow.effects` the same
questions off the same fixtures -- so the two agreeing is the move
having changed nothing.

It also covers the things the step's new shape adds, none of which the
old code had anywhere to put:

- the steps **do not save** (principle 9: a step mutates and returns,
  the caller writes it down),
- each cog wrapper saves **between** the step and the dispatch, which
  is the transition rule for Phases 2 to 5 -- and matters more here
  than it did for Low Pass, because a burst charges exhaustion and
  re-tests the Exhausted flag,
- a match caught mid-effect comes back to the same prompt across a
  save and a reload, which is the Phase 1 effect-choice branch doing
  its job on a card it had not been asked about.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from d12ball.components import MatchState
from d12ball.flow import FollowOn, FollowOnStep
from d12ball.flow.effects import dribble_advance_step, dribble_burst_step
from d12ball.prompts import PromptKind, pending_prompt

from dribble_fixtures import DRIBBLE_CASES, ENGINE, RULESET, SPEED_CHOICE
from save_patches import suppressed_cog_saves
from test_d12ball_dribble_recording import build_cog


def win_the_maneuver(match: MatchState, key: str) -> None:
    """
    Stand a match in "this dribble won on the cards and the coach is
    being asked the distance" -- where a restart strands them, and the
    state each step is called from.

    The defense's card is Deflect, which is simply a basic card a
    dribble beats decisively: rank D1 against O2. A tie (Steal,
    Intercept) would leave a skill test owed and `pending_prompt`
    would answer with that instead, which is a different branch and
    not this one.
    """
    match.choose_challenger(
        min(match.visiting.field_players, key=match.distance_to_ball),
    )
    match.choose_offense_maneuver(key)
    match.choose_defense_maneuver("deflect")


def run_step(fixture):
    """Whichever of the two steps this fixture is standing in."""
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
                    match.exhaustion.get(fixture.carrier_id, 0),
                    fixture.exhaustion,
                )

    def test_both_cards_end_on_the_speed_choice(self) -> None:
        """
        A dribble's last word is always the same question, whichever
        of the two it was: manipulate the ball's speed. It is
        `OFFER_SPEED_CHOICE` rather than `FINISH_MANEUVER_RESOLUTION`
        because the speed choice is what runs *that* afterwards -- a
        step naming both would resolve the maneuver twice.
        """
        for case in DRIBBLE_CASES:
            with self.subTest(case=case.name):
                result = run_step(case.build())
                self.assertEqual(
                    result.next.step, FollowOnStep.OFFER_SPEED_CHOICE,
                )
                self.assertEqual(result.next.step.name, SPEED_CHOICE)

    def test_the_steps_do_not_save(self) -> None:
        """
        Neither step persisted in its own body, but both wrappers did
        -- in the middle of themselves, between the move and the
        message. The write moved out to the caller, and a step that
        saved would put it back where principle 9 took it from.

        `save_games` is replaced at its own module rather than at a
        binding, so an import added to the flow package later is
        caught too.
        """
        recorder = mock.Mock()
        with suppressed_cog_saves(), mock.patch(
            "gamesaves.d12ball.storage.save_games", recorder,
        ):
            for case in DRIBBLE_CASES:
                run_step(case.build())

        recorder.assert_not_called()

    def test_a_burst_charges_and_tests_in_one_breath(self) -> None:
        """
        The tokens and the Exhausted flag have to land together, before
        anything is written out -- the bug
        `RulesEngine.apply_exhaustion` exists to prevent is a flag set
        after the save and lost. Asserted on the state rather than on
        the wording, which the table already pins.
        """
        fixture = next(
            case.build() for case in DRIBBLE_CASES
            if case.name == "burst_tips_the_handler_over_their_line"
        )
        handler = fixture.carrier_id
        self.assertNotIn(handler, fixture.match.exhausted)

        run_step(fixture)

        self.assertIn(handler, fixture.match.exhausted)
        self.assertEqual(fixture.match.exhaustion[handler], fixture.exhaustion)


class DribbleWrapperTests(unittest.IsolatedAsyncioTestCase):
    """
    `D12Ball.apply_dribble_advance` / `apply_dribble_burst` -- the
    Discord half, which is now four lines and an ordering.
    """

    async def test_the_save_lands_between_the_step_and_the_dispatch(
        self,
    ) -> None:
        """
        The transition rule for Phases 2 to 5, asserted as an order
        *and* as content: at the moment the save runs, the run must
        already have been made and charged. A persist before the step
        writes a match that has not moved, and a persist after the
        dispatch is too late -- the speed choice ends in a prompt, and
        the next click reloads the match from the file.
        """
        fixture = next(
            case.build() for case in DRIBBLE_CASES
            if case.name == "burst_three_spaces"
        )
        cog = build_cog()
        cog.games[fixture.game.game_id] = fixture.game
        match = fixture.match
        calls: list[str] = []
        tokens_when_saved: list[int] = []

        def persist(game, saved_match) -> None:
            calls.append("persist")
            tokens_when_saved.append(
                saved_match.exhaustion.get(fixture.carrier_id, 0),
            )

        async def refresh(*args, **kwargs) -> None:
            calls.append("refresh")

        async def speed_choice(*args, **kwargs) -> None:
            calls.append("offer_speed_choice")

        cog.persist = persist
        cog.refresh_match_image = refresh
        cog.offer_speed_choice = speed_choice

        await cog.apply_dribble_burst(
            SimpleNamespace(), fixture.game, match, fixture.distance,
        )

        self.assertEqual(
            calls, ["persist", "refresh", "offer_speed_choice"],
        )
        self.assertEqual(tokens_when_saved, [fixture.exhaustion])

    async def test_a_restart_mid_effect_comes_back_to_the_same_prompt(
        self,
    ) -> None:
        """
        A coach who is being asked how far to dribble, and a bot that
        restarts under them: the question they come back to has to be
        the one they left. `pending_prompt` is the single reading of
        that (Phase 1), and this is the branch of it the two dribbles
        reach -- asserted across a `to_dict`/`from_dict` round trip,
        because that is what a restart actually does.

        Both cards are stood in the state *before* their step runs, so
        nothing has been applied and the coach re-picks. The two
        fixtures used are the ones that win a maneuver decisively; the
        distance each asks for is a Playmaker's on the advance and
        everybody's on the burst, which is the pair of branches
        `effect_choice_prompt` distinguishes.
        """
        for name, expected in (
            ("advance_clamped_at_the_end_of_the_field",
             PromptKind.DRIBBLE_ADVANCE_CHOICE),
            ("burst_three_spaces", PromptKind.DRIBBLE_BURST_CHOICE),
        ):
            with self.subTest(case=name):
                fixture = next(
                    case.build() for case in DRIBBLE_CASES
                    if case.name == name
                )
                match = fixture.match
                win_the_maneuver(match, fixture.key)

                before = pending_prompt(ENGINE, fixture.game, match)
                reloaded = MatchState.from_dict(match.to_dict(), RULESET)
                after = pending_prompt(ENGINE, fixture.game, reloaded)

                self.assertEqual(before.kind, expected)
                self.assertEqual(after.kind, before.kind)
                self.assertEqual(after.ask, before.ask)

if __name__ == "__main__":
    unittest.main()
