"""
When the clock advances (Law 16.2.4, 2026-09-28).

An action's cost is charged the moment its outcome is decided -- a
maneuver's winner known on the cards, on a won skill test, or as it
succeeds with no challenger; a score attempt once the shot has
resolved; a time out as it is called -- and everything it leads to
happens on the clock as it then stands. Last possession is still
declared at the end of the action (Law 4.4.4, 16.3.1).

Played through `driver.apply`, as either frontend plays it, from the
positions `tests/prompt_fixtures.py` stands in. The time out's own case
is in `tests/test_d12ball_time_out.py`, beside the rest of the time out.
"""

from __future__ import annotations

import random
import unittest
from unittest import mock

from d12ball.components import MatchPeriod, SECOND_HALF_START_MINUTE
from d12ball.flow import FollowOn, FollowOnStep, StepResult, arrivals, driver
from d12ball.flow.driver import Action, Refusal
from d12ball.prompts import PromptKind, pending_prompt
from prompt_fixtures import CASES, ENGINE, MANEUVERS


def build(name: str):
    fixture = next(case for case in CASES if case.name == name).build()
    return fixture.game, fixture.match


def said(run) -> list[str]:
    """Every line a run said, closed groups and the one left open."""
    return [
        line for group in run.groups for line in group.narration
    ] + list(run.result.narration)


class ClockTimingTests(unittest.TestCase):
    """The charge lands at the decision, and the finish adds nothing."""

    def setUp(self) -> None:
        ENGINE.rng.seed(3)

    def apply(self, game, match, kind, choice="", **arguments) -> list[str]:
        """
        Answer, then walk on through every stop a frontend re-enters
        the loop from, as `tests/test_driver_full_game.py` does.
        """
        run = driver.apply(
            ENGINE, game, match, Action(kind, choice, arguments),
        )
        self.assertNotIsInstance(run, Refusal, run)
        lines = said(run)
        while isinstance(run.result.next, FollowOn):
            run = driver.advance(
                ENGINE, game, match, StepResult(next=run.result.next),
            )
            lines += said(run)
        return lines

    def pick(self, game, match, offense: str, defense: str) -> list[str]:
        """Both coaches pick, and the cards are revealed."""
        lines: list[str] = []
        while True:
            prompt = pending_prompt(ENGINE, game, match)
            if prompt is None or prompt.kind is not PromptKind.MANEUVER_ACTION:
                return lines
            hand = next(one for one in prompt.options.hands if not one.picked)
            key = offense if hand.side == "offense" else defense
            lines += self.apply(
                game, match, PromptKind.MANEUVER_ACTION,
                side=hand.side, maneuver_key=key,
            )

    def play_out(self, game, match, until, shoot=False) -> list[str]:
        """
        Answer the effect's own questions until `until(prompt)`,
        declining a set-up unless `shoot`.
        """
        from test_d12ball_driver_actions import LEGAL_ACTIONS
        from prompt_fixtures import PromptFixture

        lines: list[str] = []
        for _ in range(40):
            prompt = pending_prompt(ENGINE, game, match)
            if prompt is None or until(prompt):
                return lines
            # A new play's Coaching Choice is passed, and one already
            # open closed unchanged: neither is what these tests are of.
            if prompt.kind is PromptKind.SET_UP_ATTEMPT and not shoot:
                choice, arguments = "decline", {}
            elif prompt.kind is PromptKind.COACHING_OFFER:
                choice, arguments = "decline", {"side": prompt.side.value}
            elif prompt.kind is PromptKind.COACHING_HUB:
                choice, arguments = "done", {"side": prompt.side.value}
            else:
                choice, arguments = LEGAL_ACTIONS[prompt.kind](
                    PromptFixture(game, match, ""),
                )
            lines += self.apply(game, match, prompt.kind, choice, **arguments)
        self.fail("the maneuver did not finish")

    def test_a_win_on_the_cards_is_charged_at_the_reveal(self) -> None:
        game, match = build("maneuver picks")
        lines = self.pick(game, match, "high_pass", "steal")

        # The High Pass's own distance question is still to come, and
        # its two minutes are already on the clock.
        self.assertIs(
            pending_prompt(ENGINE, game, match).kind,
            PromptKind.HIGH_PASS_CHOICE,
        )
        self.assertEqual(match.scoreboard.time, 2)
        self.assertTrue(match.clock_charged)
        self.assertIn("Time has advanced 2, now at 02.", " ".join(lines))

        self.play_out(
            game, match,
            lambda prompt: prompt.kind in (
                PromptKind.PLAYER_ACTION, PromptKind.BALL_HANDLER_SELECTION,
            ),
        )
        # And the finish added nothing.
        self.assertEqual(match.scoreboard.time, 2)
        self.assertFalse(match.clock_charged)

    def test_a_set_up_shot_is_charged_again_once_it_resolves(self) -> None:
        """
        Law 16.2.5: the High Pass's 2 at the reveal, and the shot's 1
        once it has resolved -- not 3 at the end.
        """
        game, match = build("maneuver picks")
        self.pick(game, match, "high_pass", "steal")
        self.play_out(
            game, match,
            lambda prompt: prompt.kind is PromptKind.SCORE_ATTEMPT,
            shoot=True,
        )
        self.assertIs(
            pending_prompt(ENGINE, game, match).kind,
            PromptKind.SCORE_ATTEMPT,
        )
        self.assertEqual(match.scoreboard.time, 2)

        lines = self.apply(game, match, PromptKind.SCORE_ATTEMPT, "roll")
        self.assertEqual(match.scoreboard.time, 3)
        self.assertIn("Time has advanced 1, now at 03.", " ".join(lines))

    def test_the_card_charged_is_the_one_that_resolves(self) -> None:
        # Law 16.2.3: a High Pass beaten by a Deflect costs the
        # Deflect's 1, not its own 2.
        game, match = build("maneuver picks")
        self.pick(game, match, "high_pass", "deflect")
        self.assertEqual(match.scoreboard.time, 1)

    def test_an_unchallenged_maneuver_is_charged_as_it_succeeds(self) -> None:
        # Declined, or nobody to send: either way no challenger.
        game, match = build("maneuver picks")
        match.challenger_id = None
        match.maneuver_uncontested = True
        lines = self.pick(game, match, "high_pass", "")

        self.assertEqual(match.scoreboard.time, 2)
        self.assertIn("succeeds!", " ".join(lines))
        self.assertIn("Time has advanced 2, now at 02.", " ".join(lines))

    def test_letting_the_cards_stand_is_the_decision(self) -> None:
        game, match = build("force test")
        lines = self.apply(game, match, PromptKind.FORCE_TEST, "decline")
        self.assertEqual(match.scoreboard.time, 1)
        self.assertIn("Time has advanced 1, now at 01.", " ".join(lines))

    def test_a_skill_test_is_charged_on_the_winning_roll(self) -> None:
        """
        Before the injury checks the test owes: a participant already
        Exhausted is asked for one, and the clock has moved by then.
        """
        game, match = build("skill test")
        match.exhausted.add(match.challenger_id)
        match.exhaustion[match.challenger_id] = 6

        lines: list[str] = []
        for _ in range(20):
            prompt = pending_prompt(ENGINE, game, match)
            if prompt.kind is not PromptKind.SKILL_TEST:
                break
            self.assertEqual(match.scoreboard.time, 0)
            lines += self.apply(game, match, PromptKind.SKILL_TEST, "roll")

        self.assertIs(
            pending_prompt(ENGINE, game, match).kind, PromptKind.INJURY_TEST,
        )
        self.assertEqual(match.scoreboard.time, 1)
        self.assertIn("Time has advanced 1, now at 01.", " ".join(lines))

    def test_the_last_minute_is_declared_at_the_reveal_and_taken_up_next(
        self,
    ) -> None:
        """
        The author, on PR #385: last possession is declared when the
        time advances, and whoever is offered the next offensive choice
        has it. Here the Steal that reaches 15 declares it at the
        reveal; its own turnover does not end the period, and the
        stealing side, offered the next turn, is the side that has it.
        """
        game, match = build("maneuver picks")
        match.scoreboard.time = 14
        defending = match.defending_side()
        lines = self.pick(game, match, "low_pass", "steal")

        self.assertEqual(match.scoreboard.time, 15)
        self.assertTrue(match.last_possession_declared)
        self.assertFalse(match.scoreboard.last_possession)
        self.assertIn("**last possession** is declared", " ".join(lines))

        lines = self.play_out(
            game, match,
            lambda prompt: prompt.kind in (
                PromptKind.PLAYER_ACTION, PromptKind.BALL_HANDLER_SELECTION,
            ),
        )
        self.assertFalse(match.last_possession_declared)
        self.assertTrue(match.scoreboard.last_possession)
        self.assertEqual(match.ball.possession, defending)
        self.assertIn("has **last possession**", " ".join(lines))
        self.assertIs(
            MatchPeriod(match.scoreboard.period), MatchPeriod.FIRST_HALF,
        )
        self.assertEqual(match.scoreboard.time, 15)

    def test_a_time_out_on_14_declares_it_for_the_side_that_called_it(
        self,
    ) -> None:
        """
        A time out is legal on 14 and costs its minute as it is called,
        so that call reaches 15 and declares last possession; the caller
        keeps the ball, and takes it up at their next turn.
        """
        game, match = build("plain turn")
        match.scoreboard.time = 14
        calling = match.ball.possession
        lines = self.apply(game, match, PromptKind.PLAYER_ACTION, "time_out")

        self.assertEqual(match.scoreboard.time, 15)
        self.assertTrue(match.last_possession_declared)
        self.assertIn("**last possession** is declared", " ".join(lines))

        self.play_out(
            game, match,
            lambda prompt: prompt.kind in (
                PromptKind.PLAYER_ACTION, PromptKind.BALL_HANDLER_SELECTION,
            ),
        )
        self.assertTrue(match.scoreboard.last_possession)
        self.assertEqual(match.ball.possession, calling)
        self.assertFalse(match.may_call_time_out())

    def test_a_declaration_survives_a_save(self) -> None:
        from d12ball.components import MatchState
        from prompt_fixtures import RULESET

        _, match = build("plain turn")
        match.last_possession_declared = True
        saved = match.to_dict()
        self.assertTrue(
            MatchState.from_dict(saved, RULESET).last_possession_declared,
        )
        saved.pop("last_possession_declared")
        self.assertFalse(
            MatchState.from_dict(saved, RULESET).last_possession_declared,
        )

    def test_the_turnover_that_ends_a_period_is_on_the_clock(self) -> None:
        """
        Law 16.3.4: every turn of a last possession is charged, the one
        whose turnover ends the period included. The whistle's minute is
        the clock after that maneuver's cost.
        """
        game, match = build("maneuver picks")
        match.scoreboard.time = 16
        match.scoreboard.last_possession = True
        lines = self.pick(game, match, "low_pass", "steal")
        lines += self.play_out(
            game, match,
            lambda prompt: MatchPeriod(match.scoreboard.period)
            is MatchPeriod.SECOND_HALF,
        )

        self.assertIn(
            "turns over at 17 under last possession", " ".join(lines),
        )
        self.assertIs(
            MatchPeriod(match.scoreboard.period), MatchPeriod.SECOND_HALF,
        )
        self.assertEqual(match.scoreboard.time, SECOND_HALF_START_MINUTE)


class ScoreAttemptClockTests(unittest.TestCase):
    """The shot's minute is added once the shot has resolved."""

    def setUp(self) -> None:
        ENGINE.rng.seed(3)

    def shoot(self, game, match) -> list[str]:
        # The attack's die first and the defense's second: a 12 and a
        # 1 is a goal whatever either side adds.
        with mock.patch.object(
            random.Random, "randint", side_effect=[12, 1, 12, 1],
        ):
            run = driver.apply(
                ENGINE, game, match,
                Action(PromptKind.SCORE_ATTEMPT, "roll", {}),
            )
        self.assertNotIsInstance(run, Refusal, run)
        return said(run)

    def test_an_ordinary_shot_costs_its_minute_after_the_goal(self) -> None:
        game, match = build("score attempt")
        match.scoreboard.time = 5
        lines = self.shoot(game, match)

        self.assertEqual(len(match.goals), 1)
        # Stamped as the ball crossed the line, before its own minute.
        self.assertEqual(match.goals[0].time, 5)
        self.assertEqual(match.scoreboard.time, 6)
        self.assertIn("Time has advanced 1, now at 06.", " ".join(lines))

    def test_a_set_up_shot_adds_only_its_own_minute(self) -> None:
        """
        The maneuver that set it up was charged when its winner was
        decided, so the shot adds its 1 and nothing of the maneuver's.
        """
        game, match = build("score attempt")
        match.scoreboard.time = 7
        match.clock_charged = True
        match.pending_shot_is_set_up = True
        match.pending_shot_setup_cost = 2
        self.shoot(game, match)

        self.assertEqual(match.goals[0].time, 7)
        self.assertEqual(match.scoreboard.time, 8)

    def test_a_set_up_shot_saved_under_the_old_rule_owes_both(self) -> None:
        """
        A game saved at the offer before 2026-09-28 never had its
        maneuver charged: `clock_charged` reads False from that save,
        and the shot charges the maneuver's cost with its own.
        """
        game, match = build("score attempt")
        match.scoreboard.time = 7
        match.pending_shot_is_set_up = True
        match.pending_shot_setup_cost = 2
        self.shoot(game, match)

        self.assertEqual(match.scoreboard.time, 10)


class LegacyFinishTests(unittest.TestCase):
    """A game saved mid-action under the old rule is charged at the end."""

    def test_an_uncharged_action_is_charged_by_its_finish(self) -> None:
        game, match = build("plain turn")
        match.scoreboard.time = 3
        self.assertFalse(match.clock_charged)

        result = arrivals.finish_maneuver_resolution(
            ENGINE, game, match, distance_moved=2,
        )

        self.assertEqual(match.scoreboard.time, 5)
        self.assertIn("Time has advanced 2, now at 05.", result.narration[-1])

    def test_a_charged_action_is_not_charged_again(self) -> None:
        game, match = build("plain turn")
        match.scoreboard.time = 3
        match.clock_charged = True

        result = arrivals.finish_maneuver_resolution(
            ENGINE, game, match, distance_moved=2,
        )

        self.assertEqual(match.scoreboard.time, 3)
        self.assertNotIn("Time has advanced", result.narration[-1])
        self.assertFalse(match.clock_charged)

    def test_the_flag_survives_a_save_and_an_old_save_reads_false(
        self,
    ) -> None:
        from d12ball.components import MatchState
        from prompt_fixtures import RULESET

        game, match = build("plain turn")
        match.clock_charged = True
        saved = match.to_dict()
        self.assertTrue(MatchState.from_dict(saved, RULESET).clock_charged)

        saved.pop("clock_charged")
        self.assertFalse(MatchState.from_dict(saved, RULESET).clock_charged)


class EveryFinishIsChargedTests(unittest.TestCase):
    """
    Whole advanced games through the driver, on eight seeds so the
    special abilities' detours get their turn: no maneuver, shot or
    time out reaches its finish with nothing on the clock. The finish's own
    charge is only for a game saved under the old rule, so a path
    reaching it uncharged is a decision that forgot to charge.
    """

    def test_no_finish_in_a_whole_game_charges_the_clock(self) -> None:
        from test_driver_full_game import play

        finish = driver.MODEL_STEPS[FollowOnStep.FINISH_MANEUVER_RESOLUTION]
        uncharged: list[int] = []
        finishes: list[int] = []

        def watched(engine, game, match, *args, **kwargs):
            finishes.append(match.scoreboard.time)
            if not match.clock_charged:
                uncharged.append(match.scoreboard.time)
            return finish(engine, game, match, *args, **kwargs)

        with mock.patch.dict(
            driver.MODEL_STEPS,
            {FollowOnStep.FINISH_MANEUVER_RESOLUTION: watched},
        ):
            for seed in range(1, 9):
                game, _, _ = play(seed)
                self.assertTrue(game.is_finished, seed)

        self.assertGreater(len(finishes), 200)
        self.assertEqual(uncharged, [])


class ManeuverClockCostTests(unittest.TestCase):
    """The engine's one reading agrees with what the cards print."""

    def test_every_card_costs_what_it_says(self) -> None:
        from prompt_fixtures import build_match

        match = build_match()
        for maneuver in MANEUVERS.by_key().values():
            printed = int(maneuver.time.split()[0])
            with self.subTest(maneuver=maneuver.key):
                self.assertEqual(
                    ENGINE.maneuver_clock_cost(match, maneuver.key), printed,
                )


if __name__ == "__main__":
    unittest.main()
