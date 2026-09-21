"""
`d12ball.flow.driver` -- the one loop that runs a turn's own steps.

**Nothing here imports `discord` or `cogs`**, and that is the point of
the file rather than a tidiness about it: the loop is what a second
frontend runs instead of writing its own, so it has to be drivable
with nothing of Discord's in the room. The engine is built from the
catalogs directly rather than off a cog, for the same reason.

What it holds to:

- the loop runs the chain and **carries the narration** into each step
  as its `lead_in`, which is how "a resolved maneuver is one message"
  is already written;
- it **stops where the frontend is owed something** -- a
  `PendingPrompt`, or a `FollowOn` naming a step that is still a
  picture, a pin or a gate -- and hands that back untouched;
- `board_changed` is **or-ed across the run**, because the position
  worth drawing is the one the run finished on;
- it **saves nothing** (principle 9), and `DriverRun.ran` is what
  tells the caller whether a save is owed at all;
- what it stops on **agrees with `pending_prompt`** over the match it
  leaves behind, which is the property a restart depends on.

The two tables' coverage of `FollowOnStep` -- the driver's and the
cog's, disjoint and exhaustive -- is asserted in
`tests/test_d12ball_package_shape.py`, beside the enum itself.
"""

from __future__ import annotations

import unittest
from unittest import mock

from d12ball.ai import build_ai_strategies
from d12ball.components import (
    MatchState,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.engine import RulesEngine
from d12ball.flow import FollowOn, FollowOnStep, StepResult
from d12ball.flow import driver
from d12ball.game import D12BallGame, Formation, GameStatus, Team
from d12ball.prompts import PendingPrompt, PromptKind, pending_prompt

CATALOG = load_player_catalog()
RULES = load_basic_ruleset()
MANEUVERS = load_maneuver_catalog()


def build_engine() -> RulesEngine:
    """The engine the bot uses, built without the cog that holds it."""
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
        home_player_number=1,
        visiting_player_number=2,
        status=GameStatus.IN_PROGRESS,
        tutorial=False,
        tutorial_step=None,
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


class DriverFixture(unittest.TestCase):
    """A standard deal and the engine over it, with no cog anywhere."""

    def setUp(self) -> None:
        self.engine = build_engine()
        self.game = build_game()
        self.match = build_match()

    def advance(self, result: StepResult, **kwargs) -> driver.DriverRun:
        return driver.advance(
            self.engine, self.game, self.match, result, **kwargs,
        )


class LoopTests(DriverFixture):
    """
    The walk itself, over stand-in steps.

    The steps are stubbed rather than real because what is asserted
    here is the *loop* -- the carrying, the or, the stopping. What the
    real steps say is asserted in each rank's own recording table, and
    end to end in the three goldens.
    """

    def steps(self, table):
        """Patch the driver's table for the duration of one test."""
        patched = dict(driver.MODEL_STEPS)
        patched.update(table)
        return mock.patch.object(driver, "MODEL_STEPS", patched)

    def test_a_result_that_names_nothing_comes_straight_back(self) -> None:
        run = self.advance(StepResult(narration=["a line"]))

        self.assertEqual(run.steps, ())
        self.assertFalse(run.ran)
        self.assertEqual(run.result.narration, ["a line"])
        self.assertIsNone(run.result.next)

    def test_a_prompt_is_handed_back_untouched(self) -> None:
        """
        The turn stops on a person, and the loop is not what decides
        how they are asked.
        """
        prompt = PendingPrompt(kind=PromptKind.PLAYER_ACTION, ask="Your turn.")

        run = self.advance(StepResult(next=prompt))

        self.assertIs(run.result.next, prompt)
        self.assertFalse(run.ran)

    def test_a_step_the_loop_cannot_run_is_handed_back_untouched(
        self,
    ) -> None:
        """
        A member with no row in `MODEL_STEPS` is a picture, a pin or a
        gate, and the frontend is owed it -- including its arguments,
        which the loop may not eat.
        """
        following = FollowOn(
            FollowOnStep.SEND_TURN_PROMPT, {"speed_reset": True},
        )

        run = self.advance(StepResult(narration=["said"], next=following))

        self.assertIs(run.result.next, following)
        self.assertEqual(run.result.narration, ["said"])
        self.assertFalse(run.ran)

    def test_the_narration_is_carried_into_the_next_step(self) -> None:
        """
        `lead_in` is the one thing the loop passes between steps, and
        the steps fold it into their own lines -- which is how a
        cascade of the bot's own steps stays one message.
        """
        seen = []

        def step(engine, game, match, *, lead_in="", **kwargs):
            seen.append(lead_in)
            return StepResult(narration=[lead_in, "and then this"])

        with self.steps({FollowOnStep.FINISH_RUN_BACK: step}):
            run = self.advance(
                StepResult(
                    narration=["first", "second"],
                    next=FollowOn(FollowOnStep.FINISH_RUN_BACK),
                ),
            )

        self.assertEqual(seen, ["first second"])
        self.assertEqual(run.result.narration, ["first second", "and then this"])
        self.assertEqual(run.steps, (FollowOnStep.FINISH_RUN_BACK,))
        self.assertTrue(run.ran)

    def test_the_loop_runs_a_chain_of_steps_to_its_end(self) -> None:
        def first(engine, game, match, *, lead_in="", **kwargs):
            return StepResult(
                narration=["one"],
                next=FollowOn(FollowOnStep.BEGIN_SHOOTER_CHOICE),
            )

        def second(engine, game, match, *, lead_in="", **kwargs):
            return StepResult(narration=[lead_in, "two"])

        with self.steps({
            FollowOnStep.FINISH_RUN_BACK: first,
            FollowOnStep.BEGIN_SHOOTER_CHOICE: second,
        }):
            run = self.advance(
                StepResult(next=FollowOn(FollowOnStep.FINISH_RUN_BACK)),
            )

        self.assertEqual(
            run.steps,
            (FollowOnStep.FINISH_RUN_BACK, FollowOnStep.BEGIN_SHOOTER_CHOICE),
        )
        self.assertEqual(run.result.narration, ["one", "two"])

    def test_the_arguments_a_follow_on_carries_reach_the_step(self) -> None:
        """
        By keyword, every one of them -- which is the shape
        `dispatch_step_result` called the cog's wrappers with and the
        reason a lifted step needed no signature change.
        """
        seen = {}

        def step(engine, game, match, *, lead_in="", **kwargs):
            seen.update(kwargs)
            return StepResult()

        with self.steps({FollowOnStep.BEGIN_OWN_GOAL_ROLL: step}):
            self.advance(
                StepResult(
                    next=FollowOn(
                        FollowOnStep.BEGIN_OWN_GOAL_ROLL,
                        {"distance_moved": 3},
                    ),
                ),
            )

        self.assertEqual(seen, {"distance_moved": 3})

    def test_the_board_answer_is_ored_across_the_run(self) -> None:
        """
        Something moved somewhere is the run's answer; how many writes
        that costs is the frontend's (principle 8).
        """
        def moved(engine, game, match, *, lead_in="", **kwargs):
            return StepResult(board_changed=True)

        def still(engine, game, match, *, lead_in="", **kwargs):
            return StepResult(board_changed=False)

        with self.steps({FollowOnStep.FINISH_RUN_BACK: moved}):
            run = self.advance(
                StepResult(next=FollowOn(FollowOnStep.FINISH_RUN_BACK)),
            )
        self.assertTrue(run.result.board_changed)

        with self.steps({FollowOnStep.FINISH_RUN_BACK: still}):
            run = self.advance(
                StepResult(
                    board_changed=True,
                    next=FollowOn(FollowOnStep.FINISH_RUN_BACK),
                ),
            )
        self.assertTrue(run.result.board_changed)

        with self.steps({FollowOnStep.FINISH_RUN_BACK: still}):
            run = self.advance(
                StepResult(next=FollowOn(FollowOnStep.FINISH_RUN_BACK)),
            )
        self.assertFalse(run.result.board_changed)

    def test_stop_after_stops_the_run_once_that_step_has_run(self) -> None:
        """
        The frontend has a picture of the position to put up, so the
        loop may not run on behind it -- but the step itself has
        happened, which is what "after" means.
        """
        ran = []

        def first(engine, game, match, *, lead_in="", **kwargs):
            ran.append("first")
            return StepResult(next=FollowOn(FollowOnStep.BEGIN_SHOOTER_CHOICE))

        def second(engine, game, match, *, lead_in="", **kwargs):
            ran.append("second")
            return StepResult()

        with self.steps({
            FollowOnStep.FINISH_RUN_BACK: first,
            FollowOnStep.BEGIN_SHOOTER_CHOICE: second,
        }):
            run = self.advance(
                StepResult(next=FollowOn(FollowOnStep.FINISH_RUN_BACK)),
                stop_after={FollowOnStep.FINISH_RUN_BACK},
            )

        self.assertEqual(ran, ["first"])
        self.assertEqual(run.steps, (FollowOnStep.FINISH_RUN_BACK,))
        self.assertEqual(
            run.result.next, FollowOn(FollowOnStep.BEGIN_SHOOTER_CHOICE),
        )


class TableTests(unittest.TestCase):
    """What the loop can run, and what it says about it."""

    def test_runs_answers_for_a_member_either_way(self) -> None:
        self.assertTrue(driver.runs(FollowOnStep.FINISH_RUN_BACK))
        self.assertFalse(driver.runs(FollowOnStep.SEND_TURN_PROMPT))

    def test_every_step_in_the_table_takes_the_loop_s_shape(self) -> None:
        """
        `(engine, game, match, *, lead_in, ...)`, because that is how
        `_call` calls them. A row whose function takes `lead_in`
        positionally would work until a follow-on carried a keyword
        that collided with it.
        """
        import inspect

        for member, step in driver.MODEL_STEPS.items():
            with self.subTest(step=member.name):
                parameters = list(inspect.signature(step).parameters)
                self.assertEqual(parameters[:3], ["engine", "game", "match"])
                self.assertIn("lead_in", parameters)


class SaveTests(DriverFixture):
    """
    The driver saves nothing, and neither do the steps it runs.

    Principle 9: a step mutates and returns, the driver runs the
    chain, and the *caller* writes the match once after it. The guard
    replaces `save_games` at its own module rather than at a binding,
    so an import added under `d12ball/` later is caught too.
    """

    def test_a_run_writes_nothing(self) -> None:
        recorder = mock.Mock()
        with mock.patch(
            "gamesaves.d12ball.storage.save_games", recorder,
        ):
            self.advance(
                StepResult(next=FollowOn(FollowOnStep.SEND_TURN_PROMPT)),
            )
            self.advance(StepResult(narration=["x"]))

        recorder.assert_not_called()

    def test_a_run_that_ran_nothing_says_so(self) -> None:
        """
        `ran` is what the caller reads to know whether a save is owed,
        so a run that touched nothing has to be honest about it -- a
        save per dispatch would put the file write back on every
        click the loop had nothing to do on.
        """
        self.assertFalse(self.advance(StepResult()).ran)
        self.assertFalse(
            self.advance(
                StepResult(next=FollowOn(FollowOnStep.SEND_TURN_PROMPT)),
            ).ran,
        )


class WaitingOnTests(DriverFixture):
    """
    What the driver stops on is what the save says it is waiting on.

    This is the property a restart depends on: a frontend that put up
    the prompt the run handed back, and a restart that reads
    `pending_prompt` off the file, have to reach the same question.
    `waiting_on` is that one reading re-exported, never a second copy
    -- see principle 3 in CLAUDE.md.
    """

    def test_waiting_on_is_pending_prompt_and_nothing_else(self) -> None:
        self.assertEqual(
            driver.waiting_on(self.engine, self.game, self.match),
            pending_prompt(self.engine, self.game, self.match),
        )

    def test_a_prompt_the_run_stops_on_survives_the_save(self) -> None:
        """
        The run hands back a prompt, the caller writes the match, and
        what comes back out of the file asks the same thing.
        """
        run = self.advance(StepResult())
        restored = MatchState.from_dict(self.match.to_dict(), RULES)

        self.assertEqual(
            driver.waiting_on(self.engine, self.game, restored).kind,
            driver.waiting_on(self.engine, self.game, self.match).kind,
        )
        self.assertFalse(run.ran)


if __name__ == "__main__":
    unittest.main()
