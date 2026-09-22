"""
Recovery through the service, over every position the chain can read.

Step 5 of docs/architecture-migration.md: `GameService.resume` runs the
step `d12ball.prompts.owed_step` names and hands back the prompt
`pending_prompt` reads, off one chain -- so a game saved by one
frontend is picked up by the other from the same reading. **This
module imports no `discord`**: it is the resume a web app inherits,
run over the same fixtures the cog's restart is measured on
(`tests/prompt_fixtures.py`), so the two cannot disagree about which
positions are somebody's to answer and which are the bot's to run.
`tests/test_d12ball_recovery.py` is the Discord half of the same
table.
"""

from __future__ import annotations

import random
import unittest

from d12ball.components import CoachingOccasion, TeamSide
from d12ball.flow import FollowOnStep, driver
from d12ball.prompts import PromptKind, owed_step, pending_prompt
from gamesaves.d12ball.service import (
    OWED_STEP_NAMES,
    RESUME_COACHING_NOTE,
    GameService,
)
from prompt_fixtures import CASES, ENGINE, PromptFixture, build_game, build_match, take_the_ball


def service_over(fixture: PromptFixture) -> tuple[GameService, list[dict]]:
    """A service over one fixture, recording every save it makes."""
    fixture.game.match_state = fixture.match.to_dict()
    saves: list[dict] = []
    return GameService(
        ENGINE,
        {fixture.game.game_id: fixture.game},
        save=lambda games: saves.append(
            dict(games[fixture.game.game_id].match_state),
        ),
    ), saves


class ResumeOverEveryPositionTests(unittest.TestCase):
    """Every fixture, resumed the way a frontend with no cog would."""

    def setUp(self) -> None:
        state = random.getstate()
        random.seed(11)
        self.addCleanup(random.setstate, state)

    def test_an_asked_position_is_handed_back_and_nothing_runs(self) -> None:
        for case in CASES:
            if not case.asked or case.ai:
                continue
            with self.subTest(case.name):
                fixture = case.build()
                expected = pending_prompt(ENGINE, fixture.game, fixture.match)
                service, saves = service_over(fixture)

                waiting_on, result = service.resume(fixture.game.game_id)

                self.assertIs(result.prompt.kind, expected.kind)
                self.assertEqual(result.groups, ())
                self.assertEqual(saves, [])
                if expected.kind in (
                    PromptKind.COACHING_HUB, PromptKind.COACHING_OFFER,
                ):
                    # The one prompt a resume rewords: the note above
                    # the allowance saying nothing has been undone.
                    self.assertEqual(waiting_on, "the open Coaching Choice")
                    self.assertIn(RESUME_COACHING_NOTE, result.prompt.ask)
                else:
                    self.assertEqual(result.prompt, expected)

    def test_an_owed_position_is_run_on_to_a_question(self) -> None:
        """
        The step the bot owes is run, saved once, and leaves a position
        somebody is asked on -- which is the whole of what a stranded
        game needs to come back.
        """
        for case in CASES:
            if case.asked:
                continue
            with self.subTest(case.name):
                fixture = case.build()
                step = FollowOnStep[case.owed]
                service, saves = service_over(fixture)

                waiting_on, result = service.resume(fixture.game.game_id)

                self.assertEqual(waiting_on, OWED_STEP_NAMES[step])
                self.assertEqual(len(saves), 1)
                self.assertIsNotNone(result.prompt)
                self.assertIsNone(
                    owed_step(ENGINE, fixture.game, result.match),
                )
                # The live ask opens with the step's own lines; what a
                # restart would read off the save is the bare question,
                # and it has to be the same question.
                self.assertIs(
                    result.prompt.kind,
                    pending_prompt(ENGINE, fixture.game, result.match).kind,
                )

    def test_the_ai_s_question_is_answered_and_run_on(self) -> None:
        """
        A save waiting on the AI is a run that never finished: the
        service answers for it (`driver.ai_action`) and runs on to a
        coach's question or the end of the game, one save, exactly as
        an owed step is -- so a restart mid-AI-turn strands nothing.
        """
        for case in CASES:
            if not case.ai:
                continue
            with self.subTest(case.name):
                fixture = case.build()
                service, saves = service_over(fixture)

                waiting_on, result = service.resume(fixture.game.game_id)

                self.assertEqual(waiting_on, "the AI's choice")
                self.assertEqual(len(saves), 1)
                self.assertIsNone(
                    owed_step(ENGINE, fixture.game, result.match),
                )
                if result.prompt is not None:
                    self.assertIsNone(driver.ai_action(
                        ENGINE, fixture.game, result.match, result.prompt,
                    ))
                # What the AI did is in the result: its answer's own
                # lines as a group tagged with the action, or the step
                # the answer named (the pickup) as that step's group.
                self.assertTrue(result.groups)

    def test_every_step_a_resume_can_run_has_a_name(self) -> None:
        """
        `/d12ball resume` reports what it found in words, and a step
        without a row would be reported by its member name.
        """
        owed = {
            FollowOnStep[case.owed] for case in CASES if not case.asked
        }
        self.assertLessEqual(owed, set(OWED_STEP_NAMES))


class ResetTurnTests(unittest.TestCase):
    """The recovery command's `force`, as a service method."""

    def test_a_turn_gone_wrong_is_cleared_and_re_asked(self) -> None:
        match = build_match()
        take_the_ball(match)
        match.pending_action = "shoot"
        match.pending_run_back = True
        match.open_coaching_window(TeamSide.HOME, CoachingOccasion.NEW_PLAY)
        fixture = PromptFixture(build_game(), match, "")
        service, saves = service_over(fixture)

        result = service.reset_turn(fixture.game.game_id)

        self.assertFalse(result.refused)
        self.assertIs(result.prompt.kind, PromptKind.PLAYER_ACTION)
        self.assertIsNone(result.match.pending_action)
        self.assertFalse(result.match.pending_run_back)
        self.assertIsNone(result.match.pending_coaching_side)
        self.assertTrue(result.board_changed)
        self.assertEqual(len(saves), 1)

    def test_a_pause_is_refused_and_left_alone(self) -> None:
        """
        Setup, halftime, the window before the shootout, the shootout
        and a time out are positions in the game rather than a turn
        gone wrong: `RulesEngine.turn_reset_refusal` holds the list,
        and nothing is written.
        """
        pauses = {
            "setup": lambda match: setattr(
                match, "pending_setup_stage", "coaching_home",
            ),
            "halftime": lambda match: setattr(
                match, "pending_halftime_stage", "coaching_home",
            ),
            "full time": lambda match: setattr(
                match, "pending_full_time_stage", "coaching_home",
            ),
            "shootout": lambda match: match.begin_shootout(),
            "time out": lambda match: match.call_time_out(),
        }
        for name, pause in pauses.items():
            with self.subTest(name):
                match = build_match()
                take_the_ball(match)
                pause(match)
                before = match.to_dict()
                fixture = PromptFixture(build_game(), match, "")
                service, saves = service_over(fixture)

                result = service.reset_turn(fixture.game.game_id)

                self.assertTrue(result.refused)
                self.assertIn("clearing the turn", result.refusal)
                self.assertEqual(saves, [])
                self.assertEqual(fixture.game.match_state, before)


if __name__ == "__main__":
    unittest.main()
