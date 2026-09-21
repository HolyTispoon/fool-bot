"""
A whole game played through `d12ball.flow.driver` alone -- no cog, no
view, no Discord -- from the kickoff board to the rematch buttons.

**This is the test Phase 6 of docs/design/model-discord-split.md was for.**
Every earlier phase moved a piece of the turn into the model and left
the cog running the rest, so a game with no frontend imported could
not be written: `driver.advance` stopped at whichever members were
still the cog's, and the worksheet's "full scripted game through the
driver alone" stayed open. The eighteen have moved. What this file
does is what a web app would do: read `pending_prompt`, build a legal
action off the position the way a frontend builds its buttons, hand
it to `driver.apply`, save, reload, and go again until the game record
says the game is over.

**The policy is deliberately dumb.** It takes the first legal answer
to every question -- the first candidate, the first distance -- with
three exceptions that exist to reach an ending: it shoots whenever the
ball is in range, it takes a time out whenever one is offered, so both
halves' time outs and every new play's window are played, and it
picks its **maneuver card at random** (under the seed), because a
coach who plays the first card in the hand every turn never gives the
ball away and a period under last possession never ends. Both coaches
are the policy, which is the one thing a Discord script cannot do
(`SafeView.may_act_for` refuses half the presses of a two-human game
on one user id) and this one can, because authorisation is the
frontend's and there is no frontend here.

**Every action is checked against the save**, which is the restart
written as a loop: after each apply the match is written out and read
back, and the reloaded position has to be waiting on the same question
the live one is (principle 3). A run that ever answers a different
prompt from the one a restart would restore fails here.

The seed is the one thing about the run that is chosen rather than
derived, and it is chosen so the game reaches the shootout -- the
ending a level score earns and the one a dumb policy is least likely
to reach by itself. `test_the_run_reaches_the_shootout` pins that, so
a seed that stops covering it says so.
"""

from __future__ import annotations

import random
import unittest

from d12ball import tutorial
from d12ball.ai import build_ai_strategies
from d12ball.components import MatchState, TeamSide
from d12ball.engine import RulesEngine
from d12ball.flow import FollowOn, FollowOnStep, StepResult
from d12ball.flow import driver
from d12ball.flow.driver import Action, Refusal
from d12ball.flow.turn import tutorial_beat
from d12ball.game import (
    AIOpponent,
    D12BallGame,
    Formation,
    GameMode,
    GameStatus,
    Team,
)
from d12ball.prompts import PendingPrompt, PromptKind, pending_prompt
from prompt_fixtures import CATALOG, MANEUVERS, RULESET

from test_d12ball_driver_actions import LEGAL_ACTIONS, UNANSWERABLE


#: A seed the dumb policy reaches the shootout on. Swept 0-19 and the
#: first level game kept; see the module docstring.
SEED = 3

#: More actions than any game takes: thirty-odd minutes a half at one
#: a turn, a handful of prompts a turn, both halves and a shootout.
MAX_ACTIONS = 1500


def build_engine() -> RulesEngine:
    return RulesEngine(
        CATALOG, RULESET, MANEUVERS, build_ai_strategies(CATALOG, MANEUVERS),
    )


def build_game() -> D12BallGame:
    """Two coaches, advanced mode, board 6 -- the advanced golden's game
    with a person on both sides."""
    return D12BallGame(
        game_id="driver-game",
        game_number=1,
        guild_id=1,
        channel_id=2,
        message_id=None,
        player_1_id=111,
        player_2_id=222,
        player_1_team=Team.TELEKINETICS,
        player_2_team=Team.FIRE_DEMONS,
        home_player_number=1,
        visiting_player_number=2,
        mode=GameMode.ADVANCED,
        advanced_maneuvers=True,
        species_abilities=True,
        status=GameStatus.IN_PROGRESS,
        board_size=6,
    )


def build_match() -> MatchState:
    return MatchState.standard(
        catalog=CATALOG,
        ruleset=RULESET,
        board_size=6,
        home_team=Team.TELEKINETICS,
        visiting_team=Team.FIRE_DEMONS,
        home_formation=Formation.TWO_THREE_ONE,
    )


class Policy:
    """
    A legal answer to whatever the match is waiting on, read off the
    position -- `tests/test_d12ball_driver_actions.LEGAL_ACTIONS` with
    the few answers a whole game needs to be smarter about.
    """

    def __init__(self, engine: RulesEngine, game: D12BallGame):
        self.engine = engine
        self.game = game

    def action(self, match: MatchState, prompt: PendingPrompt) -> Action:
        kind = prompt.kind
        fixture = _Fixture(self.game, match)
        if kind is PromptKind.PLAYER_ACTION:
            if match.can_attempt_score():
                return Action(kind, "shoot", {"action_label": "shoot"})
            if match.may_call_time_out():
                return Action(kind, "time_out")
            return Action(kind, "maneuver")
        if kind is PromptKind.MANEUVER_ACTION:
            # Whichever side is still owed a pick; a two-human game
            # has both rows on one prompt and the offense answers
            # first here, as the prompt lists them.
            side = "offense" if match.offense_maneuver is None else "defense"
            hand = self.engine.maneuver_hand(self.game, match, side)
            card = random.choice(hand)
            return Action(kind, "", {"side": side, "maneuver_key": card.key})
        if kind is PromptKind.COACHING_HUB:
            return Action(kind, "done", {"side": match.pending_coaching_side})
        if kind is PromptKind.COACHING_OFFER:
            return Action(
                kind, "decline",
                {"side": match.pending_coaching_side, "coach_name": "Coach"},
            )
        if kind is PromptKind.SHOOTOUT_ORDER:
            side = next(
                side for side in TeamSide
                if not match.shootout_order_complete(side)
            )
            return Action(
                kind, "send",
                {"side": side, "player_id": match.shootout_order_remaining(side)[0]},
            )
        choice, arguments = LEGAL_ACTIONS[kind](fixture)
        return Action(kind, choice, arguments)


class TutorialPolicy(Policy):
    """
    The tutorial's own rails as a policy: wherever a beat fixes a
    choice, take it; everywhere else, the plain policy. What a Discord
    coach gets as greyed-out buttons a driver frontend gets as refusals
    (`driver._rail`), so a policy that ignored the rails would be
    refused rather than railed -- which is the assertion.
    """

    def action(self, match: MatchState, prompt: PendingPrompt) -> Action:
        kind = prompt.kind
        beat = tutorial_beat(self.game)
        if kind is PromptKind.PLAYER_ACTION:
            allowed = tutorial.allowed_actions(beat)
            if allowed is not None:
                action = allowed[0]
                return Action(
                    kind, action,
                    {"action_label": "shoot"} if action == "shoot" else {},
                )
        if kind is PromptKind.MANEUVER_ACTION:
            side = "offense" if match.offense_maneuver is None else "defense"
            allowed = tutorial.allowed_maneuvers(beat, side)
            if allowed is not None:
                return Action(
                    kind, "", {"side": side, "maneuver_key": allowed[0]},
                )
        if kind is PromptKind.DRIBBLE_ADVANCE_CHOICE:
            railed = tutorial.resolve_choice(beat, "dribble_advance", (1, 2))
            if railed is not None:
                return Action(kind, "", {"distance": railed})
        if kind is PromptKind.HIGH_PASS_CHOICE:
            distances = self.engine.high_pass_distance_options(match)
            railed = tutorial.resolve_choice(beat, "high_pass", distances)
            if railed is not None:
                return Action(kind, "", {"distance": railed})
        if kind is PromptKind.SPEED_DELTA_CHOICE:
            skill = self.engine.player_catalog.effective_profile(
                self.engine.get_player_definition(prompt.player_id),
            )
            reach = (
                skill.offense if prompt.skill_type == "offense"
                else skill.defense
            )
            targets = sorted({
                max(1, min(12, match.ball.speed + delta))
                for delta in range(-reach, reach + 1)
            })
            railed = tutorial.resolve_choice(beat, "speed", targets)
            if railed is not None:
                return Action(kind, "", {"target_speed": railed})
        if kind is PromptKind.SET_UP_ATTEMPT:
            return Action(kind, "take")
        return super().action(match, prompt)


class _Fixture:
    """The shape `LEGAL_ACTIONS` reads: a game and a match."""

    def __init__(self, game: D12BallGame, match: MatchState):
        self.game = game
        self.match = match


def play(
    seed: int,
    game: D12BallGame | None = None,
    match: MatchState | None = None,
    policy_class: type = Policy,
    until: object = None,
) -> tuple[D12BallGame, MatchState, list[PromptKind]]:
    """
    Play one game through the driver and return the record, the final
    match and every prompt kind that was answered, in order.

    `until` is a predicate on the game record that ends the run early
    -- the tutorial's run stops at the handover rather than at full
    time.
    """
    state = random.getstate()
    random.seed(seed)
    try:
        engine = build_engine()
        game = game or build_game()
        match = match or build_match()
        policy = policy_class(engine, game)
        answered: list[PromptKind] = []

        # The kickoff: the pre-kickoff windows are the coaches' and a
        # standard deal needs neither, so the game starts where the
        # setup's last step leaves it -- the board, and the turn.
        driver.advance(
            engine, game, match,
            StepResult(next=FollowOn(FollowOnStep.FINISH_SETUP_COACHING)),
        )
        match = MatchState.from_dict(match.to_dict(), RULESET)

        for _ in range(MAX_ACTIONS):
            if game.is_finished or (until is not None and until(game)):
                break
            prompt = pending_prompt(engine, game, match)
            if prompt.kind in UNANSWERABLE:
                break
            action = policy.action(match, prompt)
            run = driver.apply(engine, game, match, action)
            if isinstance(run, Refusal):
                raise AssertionError(
                    f"{action} refused on {prompt.kind.name}: {run.reason}"
                )
            answered.append(prompt.kind)

            # **A restart after every click.** The reloaded save has
            # to be waiting on the same question the live match is.
            # Only the stops a frontend re-enters the loop for are
            # walked on here -- the driver stops on a new play so a
            # frontend can draw its board, and a game with no board to
            # draw simply carries on.
            while isinstance(run.result.next, FollowOn):
                run = driver.advance(
                    engine, game, match, StepResult(next=run.result.next),
                )
            reloaded = MatchState.from_dict(match.to_dict(), RULESET)
            assert pending_prompt(engine, game, reloaded) == pending_prompt(
                engine, game, match,
            ), "the save and the live match disagree about what is asked"
            match = reloaded
        else:
            raise AssertionError("the game did not finish inside the budget")

        return game, match, answered
    finally:
        random.setstate(state)


class DriverFullGameTests(unittest.TestCase):
    """One whole game, no frontend."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.game, cls.match, cls.answered = play(SEED)

    def test_the_game_finishes(self) -> None:
        self.assertTrue(self.game.is_finished)
        self.assertFalse(self.game.abandoned)

    def test_a_finished_game_waits_on_the_rematch(self) -> None:
        engine = build_engine()
        self.assertIs(
            pending_prompt(engine, self.game, self.match).kind,
            PromptKind.GAME_OVER,
        )

    def test_the_run_reaches_the_shootout(self) -> None:
        """
        The seed is doing its job: the ending a dumb policy is least
        likely to reach is the one this run has to cover.
        """
        self.assertIn(PromptKind.SHOOTOUT_ORDER, self.answered)
        self.assertIn(PromptKind.SHOOTOUT_TEST, self.answered)

    def test_the_run_covers_a_turn_end_to_end(self) -> None:
        """
        Every question a turn asks was asked and answered somewhere in
        the run: the handler, the action, the challenge, the pick, the
        roll, an effect's own choice, and the windows.
        """
        for kind in (
            PromptKind.BALL_HANDLER_SELECTION,
            PromptKind.PLAYER_ACTION,
            PromptKind.MANEUVER_CHALLENGE,
            PromptKind.MANEUVER_ACTION,
            PromptKind.SKILL_TEST,
            PromptKind.SCORE_ATTEMPT,
            PromptKind.COACHING_OFFER,
            PromptKind.COACHING_HUB,
            PromptKind.HALFTIME_EXTRA_TOKEN,
            PromptKind.LOW_PASS_CHOICE,
        ):
            with self.subTest(kind=kind.name):
                self.assertIn(kind, self.answered)

    def test_the_clock_ran_both_halves(self) -> None:
        self.assertGreaterEqual(self.match.scoreboard.time, 30)

    def test_two_runs_on_one_seed_agree(self) -> None:
        """The model is deterministic under a seed, which is what makes
        the goldens possible at all."""
        first = play(SEED)
        second = play(SEED)
        self.assertEqual(first[1].to_dict(), second[1].to_dict())
        self.assertEqual(first[2], second[2])


def build_tutorial_game() -> D12BallGame:
    """The tutorial suite's game: a person against Dinky, on the rails."""
    return D12BallGame(
        game_id="driver-tutorial",
        game_number=2,
        guild_id=1,
        channel_id=3,
        message_id=None,
        player_1_id=111,
        player_2_id=None,
        ai_opponent=AIOpponent.DINKY,
        player_1_team=Team.ORANGE,
        player_2_team=Team.PURPLE,
        home_player_number=1,
        visiting_player_number=2,
        status=GameStatus.IN_PROGRESS,
        tutorial=True,
    )


def build_tutorial_match() -> MatchState:
    return MatchState.standard(
        catalog=CATALOG,
        ruleset=RULESET,
        board_size=7,
        home_team=Team.ORANGE,
        visiting_team=Team.PURPLE,
        home_formation=Formation.TWO_TWO_TWO,
    )


class DriverTutorialTests(unittest.TestCase):
    """
    The scripted opening through the driver alone -- which is where
    every one of the tutorial's Continue gates is answered, and the
    reason they had to become a prompt the model owns
    (`d12ball/flow/gates.py`).
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.game, cls.match, cls.answered = play(
            2,
            game=build_tutorial_game(),
            match=build_tutorial_match(),
            policy_class=TutorialPolicy,
            # Past the handover: the rails are off and the beats are
            # played. One more turn is taken so the last note's
            # continuation runs too.
            until=lambda game: (
                not game.in_tutorial and game.tutorial_gate is None
            ),
        )

    def test_every_note_is_held_behind_continue_and_answered(self) -> None:
        continues = self.answered.count(PromptKind.TUTORIAL_CONTINUE)
        # The welcome, five lessons, the handover, and the notes the
        # beats hold in front of their own prompts.
        self.assertGreaterEqual(continues, 7)

    def test_the_script_runs_out(self) -> None:
        self.assertIsNone(self.game.tutorial_step)
        self.assertFalse(self.game.in_tutorial)
        self.assertIsNone(self.game.tutorial_gate)

    def test_the_notes_are_the_scripts_own(self) -> None:
        """
        A gate remembers a note by key and reads the text off the
        script, so what is asked is what the beat says.
        """
        engine = build_engine()
        game = build_tutorial_game()
        match = build_tutorial_match()
        driver.advance(
            engine, game, match,
            StepResult(next=FollowOn(FollowOnStep.FINISH_SETUP_COACHING)),
        )
        prompt = pending_prompt(engine, game, match)
        self.assertIs(prompt.kind, PromptKind.TUTORIAL_CONTINUE)
        self.assertEqual(prompt.ask, tutorial.WELCOME)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
