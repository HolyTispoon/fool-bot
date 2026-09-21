"""
`driver.apply`: answering the question a match is waiting on.

`pending_prompt` says what a match is waiting on and `driver.advance`
runs what a step starts; `apply` is the half in between -- somebody
answers, and the answer is checked against the question before it
changes anything. **Checking it is a rule** ("whose turn is it", one
click later), which is why it is asserted here, against the model, with
no discord in scope.

The fixtures are `tests/prompt_fixtures.py`'s, which already stand a
match in every branch of the chain: that is exactly the table this
needs, because every case is a prompt somebody could answer. What this
module adds per kind is the *action* -- a legal one, read off the
position the same way a frontend would read it to build its buttons.

Two assertions run over every kind the driver can answer:

- a legal action applies and comes back as a `DriverRun`;
- an action naming a different kind is refused, and the refusal says
  what the match is really waiting on.

The second is the stale click a restart produces -- a coach scrolls
back to a prompt the game has moved past and presses it -- and it is
the reason the check is in the model rather than in each view.
"""

from __future__ import annotations

import random
import unittest

from d12ball.components import MatchState
from d12ball.flow import driver
from d12ball.prompts import PromptKind, pending_prompt

from prompt_fixtures import CASES, ENGINE, RULESET, PromptFixture


def _handler(fixture: PromptFixture) -> tuple[str, dict]:
    return "", {
        "player_id": fixture.match.turn_handler_candidates()[0],
    }


def _run_back_player(fixture: PromptFixture) -> tuple[str, dict]:
    prompt = pending_prompt(ENGINE, fixture.game, fixture.match)
    return "", {"player_id": prompt.player_ids[0]}


def _run_back_space(fixture: PromptFixture) -> tuple[str, dict]:
    match = fixture.match
    prompt = pending_prompt(ENGINE, fixture.game, match)
    player_id = prompt.player_id
    side = match.side_for_player(player_id)
    zone = match.setup_for_side(side).assigned_zone(player_id)
    spaces = ENGINE.placement_spaces_in_zone(
        fixture.game, match, side, zone, player_id,
    )
    return "", {"space_index": spaces[0]}


def _ball_recovery(fixture: PromptFixture) -> tuple[str, dict]:
    match = fixture.match
    return "", {
        "player_id": match.contest_candidates(match.ball.possession)[0],
    }


def _loose_ball_pick(fixture: PromptFixture) -> tuple[str, dict]:
    match = fixture.match
    side = ENGINE.loose_ball_prompt_side(match)
    return "send", {
        "player_id": ENGINE.loose_ball_candidates(match, side)[0],
    }


def _shooter_choice(fixture: PromptFixture) -> tuple[str, dict]:
    prompt = pending_prompt(ENGINE, fixture.game, fixture.match)
    return "", {"shooter_id": prompt.player_ids[0]}


def _own_goal(fixture: PromptFixture) -> tuple[str, dict]:
    """
    The roll needs a ball handler and the branch does not.

    `pending_own_goal` is the whole of what `pending_prompt` reads, so
    the fixture sets that and nothing else -- but the player who rolls
    is `match.active_player_id`, which the Pressure that risked the own
    goal would have left set. Standing one up here is the fixture
    finishing the position rather than the test reaching past it.
    """
    match = fixture.match
    match.active_player_id = match.home.field_players[0]
    return "", {}


def _low_pass(fixture: PromptFixture) -> tuple[str, dict]:
    prompt = pending_prompt(ENGINE, fixture.game, fixture.match)
    candidates = ENGINE.pass_candidates(
        fixture.match, prompt.maneuver_key or "low_pass",
    )
    return "", {"distance": candidates[0][0]}


def _high_pass(fixture: PromptFixture) -> tuple[str, dict]:
    return "", {
        "distance": ENGINE.high_pass_distance_options(fixture.match)[0],
    }


def _setup_pass(fixture: PromptFixture) -> tuple[str, dict]:
    return "", {
        "distance": ENGINE.setup_pass_distances(fixture.match)[0],
    }


def _speed_delta(fixture: PromptFixture) -> tuple[str, dict]:
    return "", {"target_speed": fixture.match.ball.speed}


def _dribble_burst(fixture: PromptFixture) -> tuple[str, dict]:
    return "", {
        "distance": ENGINE.dribble_burst_distances(fixture.match)[0],
    }


#: A legal answer to each prompt the driver can apply one to, read off
#: the position the way a frontend reads it to build its buttons.
#:
#: **Every kind in `driver.ANSWERS` has a row**, which
#: `test_every_answerable_kind_has_a_legal_action` asserts -- so a kind
#: that arrives in the table without one fails here rather than going
#: untested.
LEGAL_ACTIONS = {
    PromptKind.BALL_HANDLER_SELECTION: _handler,
    PromptKind.RUN_BACK_PLAYER: _run_back_player,
    PromptKind.RUN_BACK_SPACE: _run_back_space,
    PromptKind.BALL_RECOVERY: _ball_recovery,
    PromptKind.LOOSE_BALL_PICK: _loose_ball_pick,
    PromptKind.SET_UP_ATTEMPT: lambda fixture: ("take", {}),
    PromptKind.SHOOTER_CHOICE: _shooter_choice,
    PromptKind.SMOOTH: lambda fixture: ("take", {}),
    PromptKind.OWN_GOAL_ROLL: _own_goal,
    # The two contested rolls take no arguments at all: the action
    # is that somebody pressed, and the position is the rest.
    PromptKind.SKILL_TEST: lambda fixture: ("", {}),
    PromptKind.LOOSE_BALL_SKILL_TEST: lambda fixture: ("", {}),
    PromptKind.SCORE_ATTEMPT: lambda fixture: ("roll", {}),
    PromptKind.SHOOTOUT_TEST: lambda fixture: ("", {}),
    PromptKind.LOW_PASS_CHOICE: _low_pass,
    PromptKind.HIGH_PASS_CHOICE: _high_pass,
    PromptKind.SETUP_PASS_CHOICE: _setup_pass,
    PromptKind.SPEED_DELTA_CHOICE: _speed_delta,
    PromptKind.DRIBBLE_ADVANCE_CHOICE: lambda fixture: ("", {"distance": 1}),
    PromptKind.DRIBBLE_BURST_CHOICE: _dribble_burst,
}


#: The cases whose kind the driver can answer, one per kind -- several
#: fixtures stand in the same branch (three Low Passes, two speed
#: choices) and one of each is enough to assert the seam.
def _answerable_cases():
    seen = set()
    for case in CASES:
        kind = PromptKind[case.kind]
        if kind in driver.ANSWERS and kind not in seen:
            seen.add(kind)
            yield case, kind


class ApplyFixture(unittest.TestCase):
    """A seeded RNG, because two of the answers roll dice."""

    def setUp(self) -> None:
        state = random.getstate()
        random.seed(7)
        self.addCleanup(random.setstate, state)


class LegalActionTests(ApplyFixture):
    """Every kind the driver can answer, answered."""

    def test_every_answerable_kind_has_a_legal_action(self) -> None:
        """
        The table above covers `driver.ANSWERS` exactly.

        A kind arriving in the driver's table without a row here would
        be a kind nothing asserts, which is the failure a phase makes
        when it lifts an answer and forgets its evidence.
        """
        self.assertEqual(set(LEGAL_ACTIONS), set(driver.ANSWERS))

    def test_every_answerable_kind_is_reached_by_a_fixture(self) -> None:
        """
        And every one of them has a match standing in it, so the
        assertions below actually run for each.
        """
        self.assertEqual(
            {kind for _, kind in _answerable_cases()},
            set(driver.ANSWERS),
        )

    def test_a_legal_answer_applies(self) -> None:
        for case, kind in _answerable_cases():
            with self.subTest(case.name):
                fixture = case.build()
                choice, arguments = LEGAL_ACTIONS[kind](fixture)
                run = driver.apply(
                    ENGINE,
                    fixture.game,
                    fixture.match,
                    driver.Action(kind, choice, arguments),
                )
                self.assertNotIsInstance(run, driver.Refusal)
                self.assertIsInstance(run, driver.DriverRun)

    def test_an_answer_to_another_question_is_refused(self) -> None:
        """
        The stale click: a coach scrolls back to a prompt the game has
        moved past and presses it.

        The refusal names what the match is really waiting on, so the
        frontend can put that question up rather than asking twice.
        """
        for case, kind in _answerable_cases():
            with self.subTest(case.name):
                fixture = case.build()
                other = (
                    PromptKind.SHOOTOUT_ORDER
                    if kind is not PromptKind.SHOOTOUT_ORDER
                    else PromptKind.PLAYER_ACTION
                )
                refusal = driver.apply(
                    ENGINE,
                    fixture.game,
                    fixture.match,
                    driver.Action(other),
                )
                self.assertIsInstance(refusal, driver.Refusal)
                self.assertEqual(refusal.waiting_on.kind, kind)

    def test_a_refused_action_changes_nothing(self) -> None:
        """
        A refusal is not a half-applied answer: the match it was asked
        about is the match it leaves behind.
        """
        for case, kind in _answerable_cases():
            with self.subTest(case.name):
                fixture = case.build()
                before = fixture.match.to_dict()
                driver.apply(
                    ENGINE,
                    fixture.game,
                    fixture.match,
                    driver.Action(PromptKind.SHOOTOUT_PICK),
                )
                self.assertEqual(fixture.match.to_dict(), before)


class ChoiceTests(ApplyFixture):
    """The answers a prompt offers, and the ones it does not."""

    def test_a_choice_the_prompt_does_not_offer_is_refused(self) -> None:
        for case, kind in _answerable_cases():
            with self.subTest(case.name):
                fixture = case.build()
                refusal = driver.apply(
                    ENGINE,
                    fixture.game,
                    fixture.match,
                    driver.Action(kind, "sing"),
                )
                self.assertIsInstance(refusal, driver.Refusal)

    def test_a_kind_with_one_answer_takes_the_empty_choice(self) -> None:
        """
        A prompt that offers one answer is named by no choice at all,
        rather than by a word every frontend would have to agree on.
        """
        for kind in driver.ANSWERS:
            if kind in driver.CHOICES:
                continue
            with self.subTest(kind.name):
                self.assertTrue(driver._choice_is_offered(kind, ""))
                self.assertFalse(driver._choice_is_offered(kind, "take"))

    def test_every_offered_choice_is_answered_rather_than_unknown(
        self,
    ) -> None:
        """
        Both halves of a two-answer prompt reach a real answer.

        **Not "both halves apply"**, because one of them may be
        refused by the position and that is the right outcome: a side
        with somebody standing on the ball contests it and cannot be
        held back, so "decline" on that loose ball is a refusal with a
        rule behind it. What this asserts is that it is *that*
        refusal and not "that is not one of the answers this question
        offers", which would mean the choice never reached an answer
        at all.
        """
        unknown = "That is not one of the answers this question offers."
        for case, kind in _answerable_cases():
            if kind not in driver.CHOICES:
                continue
            for choice in driver.CHOICES[kind]:
                with self.subTest(f"{case.name}: {choice}"):
                    fixture = case.build()
                    _, arguments = LEGAL_ACTIONS[kind](fixture)
                    before = fixture.match.to_dict()
                    run = driver.apply(
                        ENGINE,
                        fixture.game,
                        fixture.match,
                        driver.Action(
                            kind,
                            choice,
                            arguments if choice != "decline" else {},
                        ),
                    )
                    if isinstance(run, driver.Refusal):
                        self.assertNotEqual(run.reason, unknown)
                        self.assertEqual(fixture.match.to_dict(), before)
                        continue
                    self.assertNotEqual(fixture.match.to_dict(), before)


class PositionRefusalTests(ApplyFixture):
    """
    A step refusing what was chosen, which arrives as a `ValueError`
    and leaves as a `Refusal`.
    """

    def test_an_illegal_space_is_refused_with_the_step_s_own_reason(
        self,
    ) -> None:
        fixture = next(
            case.build() for case in CASES if case.name == "run back, where"
        )
        refusal = driver.apply(
            ENGINE,
            fixture.game,
            fixture.match,
            driver.Action(
                PromptKind.RUN_BACK_SPACE, arguments={"space_index": 99},
            ),
        )
        self.assertIsInstance(refusal, driver.Refusal)
        self.assertTrue(refusal.reason)
        self.assertEqual(
            refusal.waiting_on.kind, PromptKind.RUN_BACK_SPACE,
        )


class SeamTests(unittest.TestCase):
    """What `apply` is not, and what it says about itself."""

    def test_a_kind_with_no_model_answer_raises_rather_than_refuses(
        self,
    ) -> None:
        """
        A question this module cannot answer yet is a fact about the
        seam, not about the position -- so it is not a refusal, which
        a frontend would show to a coach as though they had done
        something wrong.
        """
        fixture = next(
            case.build() for case in CASES if case.name == "maneuver picks"
        )
        self.assertFalse(driver.can_answer(PromptKind.MANEUVER_ACTION))
        with self.assertRaises(LookupError):
            driver.apply(
                ENGINE,
                fixture.game,
                fixture.match,
                driver.Action(PromptKind.MANEUVER_ACTION),
            )

    def test_every_answer_takes_the_same_shape(self) -> None:
        """
        `(engine, game, match, prompt, choice, **arguments)` -- the
        uniform signature is what lets `apply` be one call rather than
        a branch per kind.
        """
        import inspect

        for kind, answer in driver.ANSWERS.items():
            with self.subTest(kind.name):
                positional = [
                    name
                    for name, parameter in inspect.signature(
                        answer,
                    ).parameters.items()
                    if parameter.kind is parameter.POSITIONAL_OR_KEYWORD
                ]
                self.assertEqual(
                    positional[:5],
                    ["engine", "game", "match", "prompt", "choice"],
                )


class SaveTests(ApplyFixture):
    """`apply` saves nothing -- principle 9."""

    def test_applying_an_action_writes_nothing(self) -> None:
        import gamesaves.d12ball.storage as storage
        from unittest import mock

        for case, kind in _answerable_cases():
            with self.subTest(case.name):
                fixture = case.build()
                choice, arguments = LEGAL_ACTIONS[kind](fixture)
                with mock.patch.object(storage, "save_games") as saved:
                    driver.apply(
                        ENGINE,
                        fixture.game,
                        fixture.match,
                        driver.Action(kind, choice, arguments),
                    )
                saved.assert_not_called()


class PromptAgreementTests(ApplyFixture):
    """
    What a run stops on agrees with what the save says it is waiting
    on.

    This is the restart written as a test, one click further in than
    `test_a_prompt_survives_a_save_and_a_load`: a coach answers, the
    bot goes down before the next click, and the prompt they are handed
    back has to be the one the answer led to.
    """

    def test_the_prompt_a_run_stops_on_survives_a_save(self) -> None:
        for case, kind in _answerable_cases():
            with self.subTest(case.name):
                fixture = case.build()
                choice, arguments = LEGAL_ACTIONS[kind](fixture)
                run = driver.apply(
                    ENGINE,
                    fixture.game,
                    fixture.match,
                    driver.Action(kind, choice, arguments),
                )
                reloaded = MatchState.from_dict(
                    fixture.match.to_dict(), RULESET,
                )
                self.assertEqual(
                    pending_prompt(ENGINE, fixture.game, reloaded),
                    pending_prompt(ENGINE, fixture.game, fixture.match),
                )
                self.assertIsInstance(run, driver.DriverRun)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
