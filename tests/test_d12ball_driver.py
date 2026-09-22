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
from dataclasses import replace
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

    def test_a_prompt_is_handed_back_with_its_options_and_nothing_else(
        self,
    ) -> None:
        """
        The turn stops on a person, and the loop is not what decides
        how they are asked. What it adds is the prompt's `options`,
        built off the position (step 6 of docs/architecture-migration.md);
        the kind and the ask are the step's.
        """
        prompt = PendingPrompt(kind=PromptKind.PLAYER_ACTION, ask="Your turn.")

        run = self.advance(StepResult(next=prompt))

        self.assertEqual(run.result.next, replace(
            prompt, options=run.result.next.options,
        ))
        self.assertIsNotNone(run.result.next.options)
        self.assertFalse(run.ran)

    def test_a_step_the_frontend_stops_on_is_handed_back_with_its_arguments(
        self,
    ) -> None:
        """
        The loop runs every member since Phase 6, so what a frontend
        is handed back is a step it asked to stop *after* -- with the
        step's own arguments, which is what the picture it stops for
        is keyed on (`stopped_on`), and with the lines the step said.
        """
        def loose(engine, game, match, *, lead_in="", **kwargs):
            return StepResult(
                narration=["lying there"],
                board_changed=True,
                next=FollowOn(FollowOnStep.RESOLVE_LOOSE_BALL),
            )

        following = FollowOn(
            FollowOnStep.BEGIN_LOOSE_BALL, {"is_high_pass": True},
        )
        with self.steps({FollowOnStep.BEGIN_LOOSE_BALL: loose}):
            run = self.advance(
                StepResult(narration=["said"], next=following),
                stop_after={FollowOnStep.BEGIN_LOOSE_BALL},
            )

        self.assertEqual(run.stopped_on, following)
        self.assertEqual(run.result.narration, ["lying there"])
        self.assertEqual(
            run.result.next, FollowOn(FollowOnStep.RESOLVE_LOOSE_BALL),
        )
        self.assertEqual(run.steps, (FollowOnStep.BEGIN_LOOSE_BALL,))

    def test_a_new_play_stops_the_run_on_its_own(self) -> None:
        """
        The reset's lines caption the board the play starts from, and
        a frontend has to put that board up before anything behind it
        moves -- so a result that says `new_play` ends the run whoever
        asked, and the frontend re-enters the loop for what follows.
        """
        def reset(engine, game, match, *, lead_in="", **kwargs):
            return StepResult(
                narration=["# New play"],
                board_changed=True,
                new_play=True,
                next=FollowOn(FollowOnStep.BEGIN_SUBSTITUTION_WINDOW),
            )

        def window(engine, game, match, *, lead_in="", **kwargs):
            raise AssertionError("ran on past the new play")

        with self.steps({
            FollowOnStep.BEGIN_RUN_BACK: reset,
            FollowOnStep.BEGIN_SUBSTITUTION_WINDOW: window,
        }):
            run = self.advance(
                StepResult(next=FollowOn(FollowOnStep.BEGIN_RUN_BACK)),
            )

        self.assertEqual(run.stopped_on, FollowOn(FollowOnStep.BEGIN_RUN_BACK))
        self.assertTrue(run.result.new_play)
        self.assertEqual(run.result.narration, ["# New play"])
        self.assertEqual(
            run.result.next,
            FollowOn(FollowOnStep.BEGIN_SUBSTITUTION_WINDOW),
        )

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


class NarrationGroupTests(DriverFixture):
    """
    Where one message ends and the next begins.

    Until Phase 6's second increment the loop could only *carry* a
    step's lines forward, so a step whose lines were an event in their
    own right -- the reveal, a settled loose ball, "Players run
    back!", the whistle -- could not be in the table at all: the
    distinction was the cog calling `post_then_dispatch` instead of
    `dispatch_step_result`. `own_message` is that distinction as an
    argument, and it stays the frontend's: a web app with no
    five-in-five bucket may want every step's lines separately.
    """

    def steps(self, table):
        patched = dict(driver.MODEL_STEPS)
        patched.update(table)
        return mock.patch.object(driver, "MODEL_STEPS", patched)

    def two_steps(self):
        """A step that names a second, and the second."""
        def first(engine, game, match, *, lead_in="", **kwargs):
            return StepResult(
                narration=[line for line in (lead_in, "the first") if line],
                next=FollowOn(FollowOnStep.BEGIN_SHOOTER_CHOICE),
            )

        def second(engine, game, match, *, lead_in="", **kwargs):
            return StepResult(
                narration=[line for line in (lead_in, "the second") if line],
            )

        return {
            FollowOnStep.FINISH_RUN_BACK: first,
            FollowOnStep.BEGIN_SHOOTER_CHOICE: second,
        }

    def test_without_own_message_every_line_is_carried(self) -> None:
        """The ordinary run, and still the common one: no groups."""
        with self.steps(self.two_steps()):
            run = self.advance(
                StepResult(next=FollowOn(FollowOnStep.FINISH_RUN_BACK)),
            )

        self.assertEqual(run.groups, ())
        self.assertEqual(run.result.narration, ["the first", "the second"])

    def test_own_message_closes_a_group_and_carries_nothing_on(
        self,
    ) -> None:
        """
        The step's lines come back as a group of their own, tagged with
        the step that said them, and the step after it opens with no
        lead-in -- which is exactly what `post_then_dispatch` did.
        """
        with self.steps(self.two_steps()):
            run = self.advance(
                StepResult(next=FollowOn(FollowOnStep.FINISH_RUN_BACK)),
                own_message={FollowOnStep.FINISH_RUN_BACK},
            )

        self.assertEqual(
            run.groups,
            (
                driver.NarrationGroup(
                    ("the first",), FollowOnStep.FINISH_RUN_BACK,
                ),
            ),
        )
        self.assertEqual(run.result.narration, ["the second"])

    def test_the_caller_s_own_lines_ride_into_the_first_step(self) -> None:
        """
        `own_message` closes a group *after* a step, never in front of
        one: the lines said before it are its `lead_in`, the way they
        always were.
        """
        with self.steps(self.two_steps()):
            run = self.advance(
                StepResult(
                    narration=["said before"],
                    next=FollowOn(FollowOnStep.FINISH_RUN_BACK),
                ),
                own_message={FollowOnStep.FINISH_RUN_BACK},
            )

        self.assertEqual(
            run.groups[0].narration, ("said before", "the first"),
        )

    def test_a_step_that_speaks_the_lines_is_handed_them_instead(
        self,
    ) -> None:
        """
        The whistle's lines are the *content* of the game-over message
        -- the final board rides on them -- so a group that would close
        in front of one of those is carried across instead. This is
        `FOLLOW_ONS_THAT_SPEAK_THE_LINES` in `cogs/d12ball/core.py`,
        which the cog passes in.
        """
        def whistle(engine, game, match, *, lead_in="", **kwargs):
            return StepResult(
                narration=["full time"],
                next=FollowOn(FollowOnStep.ANNOUNCE_GAME_OVER),
            )

        with self.steps({FollowOnStep.END_PERIOD: whistle}):
            run = self.advance(
                StepResult(next=FollowOn(FollowOnStep.END_PERIOD)),
                own_message={FollowOnStep.END_PERIOD},
                speaks_lines={FollowOnStep.ANNOUNCE_GAME_OVER},
            )

        # Carried into the game-over step, which speaks them as the
        # content of the message it ends on.
        self.assertEqual(run.groups, ())
        self.assertEqual(run.result.narration, ["full time"])
        self.assertEqual(run.result.next.kind, PromptKind.GAME_OVER)

    def test_a_group_that_said_nothing_is_still_reported(self) -> None:
        """
        A step in `own_message` that had nothing to say still closes a
        group -- empty -- because the frontend may have a picture for
        that step's group and an empty group is how it learns the step
        ran (the challenge image rides on `AUTO_RESOLVE_CHALLENGER`'s,
        whose walk-in line is "" for a defender already on the ball).
        The frontend posts nothing for empty lines.
        """
        def silent(engine, game, match, *, lead_in="", **kwargs):
            return StepResult()

        with self.steps({FollowOnStep.RESOLVE_LOOSE_BALL: silent}):
            run = self.advance(
                StepResult(next=FollowOn(FollowOnStep.RESOLVE_LOOSE_BALL)),
                own_message={FollowOnStep.RESOLVE_LOOSE_BALL},
            )

        self.assertEqual(
            run.groups,
            (driver.NarrationGroup((), FollowOnStep.RESOLVE_LOOSE_BALL),),
        )
        self.assertEqual(run.result.narration, [])

    def test_several_groups_come_back_in_the_order_they_were_said(
        self,
    ) -> None:
        def first(engine, game, match, *, lead_in="", **kwargs):
            return StepResult(
                narration=["one"],
                next=FollowOn(FollowOnStep.RESOLVE_LOOSE_BALL),
            )

        def second(engine, game, match, *, lead_in="", **kwargs):
            return StepResult(
                narration=["two"],
                next=FollowOn(FollowOnStep.BEGIN_SHOOTER_CHOICE),
            )

        def third(engine, game, match, *, lead_in="", **kwargs):
            return StepResult(narration=["three"])

        with self.steps({
            FollowOnStep.RESOLVE_MANEUVER: first,
            FollowOnStep.RESOLVE_LOOSE_BALL: second,
            FollowOnStep.BEGIN_SHOOTER_CHOICE: third,
        }):
            run = self.advance(
                StepResult(next=FollowOn(FollowOnStep.RESOLVE_MANEUVER)),
                own_message={
                    FollowOnStep.RESOLVE_MANEUVER,
                    FollowOnStep.RESOLVE_LOOSE_BALL,
                },
            )

        self.assertEqual(
            [group.step for group in run.groups],
            [FollowOnStep.RESOLVE_MANEUVER, FollowOnStep.RESOLVE_LOOSE_BALL],
        )
        self.assertEqual(
            [group.narration for group in run.groups],
            [("one",), ("two",)],
        )
        self.assertEqual(run.result.narration, ["three"])


class TableTests(unittest.TestCase):
    """What the loop can run, and what it says about it."""

    def test_runs_answers_for_every_member(self) -> None:
        """The table covers the enum: the loop runs every step."""
        for member in FollowOnStep:
            with self.subTest(member=member.name):
                self.assertIn(member, driver.MODEL_STEPS)

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
        `ran` is what the caller reads to know whether the loop touched
        the match, so a run that ran no step has to be honest about it
        -- and one that ran a step, whatever the step did, has to say
        so too.
        """
        self.assertFalse(self.advance(StepResult()).ran)
        prompt = PendingPrompt(kind=PromptKind.PLAYER_ACTION, ask="Your turn.")
        self.assertFalse(self.advance(StepResult(next=prompt)).ran)
        self.assertTrue(
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
