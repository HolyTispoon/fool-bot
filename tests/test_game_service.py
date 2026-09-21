"""
`GameService`: the one door, and the one save.

What ARCHITECTURE.md's part 2 promises, checked with no frontend
imported: an action is applied through the driver and the match is
written once, before the result comes back; a refusal writes nothing;
the frontend's batching decides what the result is made of, including
which of the answer's own lines are carried into the next step; and
the recovery ladder runs the step the bot owes rather than asking.
"""

from __future__ import annotations

import unittest
from unittest import mock

from d12ball.components import (
    MatchState,
    TeamSide,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.engine import RulesEngine
from d12ball.ai import build_ai_strategies
from d12ball.flow import FollowOnStep, StepResult
from d12ball.flow.driver import Action
from d12ball.game import D12BallGame, Formation, GameMode, GameStatus, Team
from d12ball.prompts import PromptKind
from gamesaves.d12ball.service import (
    Batching,
    GameResult,
    GameService,
    StopHandling,
)


CATALOG = load_player_catalog()
RULES = load_basic_ruleset()
MANEUVERS = load_maneuver_catalog()


def build_engine() -> RulesEngine:
    return RulesEngine(
        CATALOG, RULES, MANEUVERS, build_ai_strategies(CATALOG, MANEUVERS),
    )


def build_game() -> D12BallGame:
    return D12BallGame(
        game_id="g1",
        game_number=1,
        guild_id=1,
        channel_id=2,
        message_id=None,
        player_1_id=111,
        player_2_id=222,
        player_1_team=Team.ORANGE,
        player_2_team=Team.PURPLE,
        mode=GameMode.BASIC,
        status=GameStatus.IN_PROGRESS,
        home_player_number=1,
        visiting_player_number=2,
        coin_flipped=True,
    )


def build_match() -> MatchState:
    return MatchState.standard(
        catalog=CATALOG,
        ruleset=RULES,
        board_size=7,
        home_team=Team.ORANGE,
        visiting_team=Team.PURPLE,
        home_formation=Formation.TWO_TWO_TWO,
    )


class ServiceHarness(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = build_engine()
        self.game = build_game()
        self.match = build_match()
        self.game.match_state = self.match.to_dict()
        self.saves: list[dict] = []
        self.games = {self.game.game_id: self.game}

    def service(self, batching: Batching = Batching()) -> GameService:
        return GameService(
            self.engine,
            self.games,
            batching,
            save=lambda games: self.saves.append(
                dict(games[self.game.game_id].match_state),
            ),
        )


class ApplyActionTests(ServiceHarness):
    def test_an_answer_is_saved_once_before_it_comes_back(self) -> None:
        service = self.service()
        handler = self.match.eligible_ball_handlers()[0]

        result = service.apply_action(
            "g1",
            Action(
                PromptKind.BALL_HANDLER_SELECTION, "", {"player_id": handler},
            ),
        )

        self.assertIsInstance(result, GameResult)
        self.assertFalse(result.refused)
        self.assertEqual(len(self.saves), 1)
        # What was written is the position the result describes.
        self.assertEqual(self.saves[0], result.match.to_dict())
        self.assertEqual(result.prompt.kind, PromptKind.PLAYER_ACTION)

    def test_a_refusal_writes_nothing(self) -> None:
        service = self.service()
        before = dict(self.game.match_state)

        result = service.apply_action(
            "g1", Action(PromptKind.SKILL_TEST, "roll"),
        )

        self.assertTrue(result.refused)
        self.assertEqual(result.waiting_on.kind, PromptKind.BALL_HANDLER_SELECTION)
        self.assertEqual(self.saves, [])
        self.assertEqual(self.game.match_state, before)

    def test_carry_from_splits_the_answers_lines(self) -> None:
        """
        `None` keeps every line as the answer; an index hands the rest
        to the first step as its lead-in, where the step composes it.
        """
        handler = self.match.eligible_ball_handlers()[0]
        lines = ["first", "second"]
        answered = mock.Mock(
            result=StepResult(narration=list(lines), next=None),
            detail=None,
        )
        with mock.patch(
            "gamesaves.d12ball.service.driver.answer", return_value=answered,
        ):
            kept_all = self.service().apply_action(
                "g1", Action(PromptKind.BALL_HANDLER_SELECTION, "", {"player_id": handler}),
            )
            carried_rest = self.service().apply_action(
                "g1",
                Action(PromptKind.BALL_HANDLER_SELECTION, "", {"player_id": handler}),
                carry_from=1,
            )
            asked = self.service().apply_action(
                "g1",
                Action(PromptKind.BALL_HANDLER_SELECTION, "", {"player_id": handler}),
                carry_from=lambda answered: 0,
            )

        self.assertEqual(kept_all.answer, ("first", "second"))
        self.assertEqual(kept_all.narration, ())
        self.assertEqual(carried_rest.answer, ("first",))
        self.assertEqual(carried_rest.narration, ("second",))
        self.assertEqual(asked.answer, ())
        self.assertEqual(asked.narration, ("first", "second"))


class BatchingTests(ServiceHarness):
    """
    The stops are the frontend's, and what happens at one is the
    `Batching` it handed the service.
    """

    def run_through(self, batching: Batching, handling: StopHandling):
        recorded = []

        class Stops(Batching):
            def at_stop(self, stopped, result, following):
                recorded.append(stopped.step)
                return handling

        stops = Stops(
            stop_after=batching.stop_after,
            own_message=batching.own_message,
            speaks_lines=batching.speaks_lines,
        )
        service = self.service(stops)
        first = StepResult(
            narration=["moved"], board_changed=True,
            next=None,
        )
        second = StepResult(narration=["then"], next=None)
        steps = {
            FollowOnStep.BEGIN_LOOSE_BALL: mock.Mock(return_value=first),
            FollowOnStep.FINISH_MANEUVER_RESOLUTION: mock.Mock(
                return_value=second,
            ),
        }
        with mock.patch(
            "d12ball.flow.driver.MODEL_STEPS",
            {**__import__("d12ball.flow.driver", fromlist=["MODEL_STEPS"]).MODEL_STEPS, **steps},
        ):
            from d12ball.flow.result import FollowOn

            first.next = FollowOn(FollowOnStep.FINISH_MANEUVER_RESOLUTION)
            result = service.run(
                self.game,
                self.match,
                StepResult(
                    narration=["opening"],
                    next=FollowOn(FollowOnStep.BEGIN_LOOSE_BALL),
                ),
            )
        return result, recorded, steps

    def test_a_drawn_stop_carries_the_position(self) -> None:
        batching = Batching(stop_after=frozenset({FollowOnStep.BEGIN_LOOSE_BALL}))
        result, recorded, _ = self.run_through(batching, StopHandling.DRAW)

        self.assertEqual(recorded, [FollowOnStep.BEGIN_LOOSE_BALL])
        self.assertEqual(len(result.groups), 1)
        group = result.groups[0]
        self.assertTrue(group.drawn)
        self.assertEqual(group.step, FollowOnStep.BEGIN_LOOSE_BALL)
        self.assertEqual(group.lines, ("moved",))
        self.assertEqual(group.board, self.match.to_dict())
        # The picture wrote the board; nothing moved after it.
        self.assertFalse(result.board_changed)
        # The step after the stop ran with nothing carried.
        self.assertEqual(result.narration, ("then",))
        self.assertEqual(len(self.saves), 1)

    def test_a_posted_stop_carries_no_board(self) -> None:
        batching = Batching(stop_after=frozenset({FollowOnStep.BEGIN_LOOSE_BALL}))
        result, _, _ = self.run_through(batching, StopHandling.POST)

        self.assertFalse(result.groups[0].drawn)
        self.assertTrue(result.board_changed)

    def test_a_carried_stop_opens_the_next_step(self) -> None:
        batching = Batching(stop_after=frozenset({FollowOnStep.BEGIN_LOOSE_BALL}))
        result, _, steps = self.run_through(batching, StopHandling.CARRY)

        self.assertEqual(result.groups, ())
        _, kwargs = steps[FollowOnStep.FINISH_MANEUVER_RESOLUTION].call_args
        self.assertEqual(kwargs["lead_in"], "moved")

    def test_the_callers_own_lines_close_a_group_when_not_carried(self) -> None:
        service = self.service()
        result = service.run(
            self.game,
            self.match,
            StepResult(narration=["one", "two"], next=None),
            carry=False,
        )
        self.assertEqual(result.groups[0].lines, ("one", "two"))
        self.assertIsNone(result.groups[0].step)
        self.assertEqual(result.narration, ())


class ResumeTests(ServiceHarness):
    def test_a_stranded_run_back_is_driven_on(self) -> None:
        self.match.active_player_id = self.match.eligible_ball_handlers()[0]
        self.match.pending_run_back = True
        self.game.match_state = self.match.to_dict()
        service = self.service()
        ran = mock.Mock(return_value=StepResult())
        with mock.patch.dict(
            "d12ball.flow.driver.MODEL_STEPS",
            {FollowOnStep.CONTINUE_RUN_BACK: ran},
        ):
            waiting_on, result = service.resume("g1")

        self.assertEqual(waiting_on, "the run back")
        ran.assert_called_once()
        self.assertEqual(len(self.saves), 1)

    def test_nothing_owed_hands_back_the_prompt_and_saves_nothing(self) -> None:
        service = self.service()

        waiting_on, result = service.resume("g1")

        self.assertEqual(waiting_on, "a choice, re-posted above")
        self.assertEqual(result.prompt.kind, PromptKind.BALL_HANDLER_SELECTION)
        self.assertEqual(self.saves, [])

    def test_an_open_window_comes_back_with_the_note(self) -> None:
        from d12ball.components import CoachingOccasion

        self.match.active_player_id = self.match.eligible_ball_handlers()[0]
        self.match.open_coaching_window(TeamSide.HOME, CoachingOccasion.HALFTIME)
        self.match.declare_coaching()
        self.game.match_state = self.match.to_dict()

        waiting_on, result = self.service().resume("g1")

        self.assertEqual(waiting_on, "the open Coaching Choice")
        self.assertEqual(result.prompt.kind, PromptKind.COACHING_HUB)
        self.assertIn("Picking this up where it left off", result.prompt.ask)
        self.assertEqual(self.saves, [])


class PurityTests(unittest.TestCase):
    def test_the_service_imports_no_discord(self) -> None:
        import gamesaves.d12ball.service as module

        from pathlib import Path

        source = Path(module.__file__).read_text()
        self.assertNotIn("import discord", source)
        self.assertNotIn("async def", source)


if __name__ == "__main__":
    unittest.main()
