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
from unittest import mock

from d12ball import tutorial
from d12ball.ai import DinkyAI
from d12ball.components import MatchState, RuleRefusal, TeamSide
from d12ball.game import Formation, GameMode, Team
from d12ball.flow import driver
from d12ball.flow.windows import open_substitution_window
from d12ball.prompts import NOBODYS_QUESTIONS, PromptKind, pending_prompt

from prompt_fixtures import (
    CASES,
    CATALOG,
    ENGINE,
    RULESET,
    PromptFixture,
    build_game,
    challenge,
)


def _prompt(fixture: PromptFixture):
    return pending_prompt(ENGINE, fixture.game, fixture.match)


def _first_player(fixture: PromptFixture) -> tuple[str, dict]:
    """A pick among players: the first the prompt offers."""
    return "", {"player_id": _prompt(fixture).options.player_ids[0]}


def _run_back_space(fixture: PromptFixture) -> tuple[str, dict]:
    return "", {"space_index": _prompt(fixture).options.space_indices[0]}


def _loose_ball_pick(fixture: PromptFixture) -> tuple[str, dict]:
    return "send", {"player_id": _prompt(fixture).options.player_ids[0]}


def _shooter_choice(fixture: PromptFixture) -> tuple[str, dict]:
    return "", {"shooter_id": _prompt(fixture).options.player_ids[0]}


def _coaching_side(fixture: PromptFixture) -> TeamSide:
    """
    The side whose window is open, opening one where the fixture has
    not.

    The setup and full-time hubs stand in their branch off
    `pending_setup_stage` alone -- `pending_prompt` needs nothing else
    to read them -- but answering one needs the window itself, which
    `begin_setup_coaching` opens a step earlier. The fixture finishing
    its own position, the same as the own-goal roll's ball handler.
    """
    match = fixture.match
    if match.pending_coaching_side is None:
        open_substitution_window(
            ENGINE, fixture.game, match, TeamSide.HOME,
        )
    return match.pending_coaching_side


def _coaching_offer(fixture: PromptFixture) -> tuple[str, dict]:
    return "declare", {"side": _coaching_side(fixture)}


def _coaching_hub(fixture: PromptFixture) -> tuple[str, dict]:
    """
    A substitution, which is the hub answer every occasion offers --
    the three positional ones are not on a full-time window's menu.
    """
    side = _coaching_side(fixture)
    options = _prompt(fixture).options
    return "substitute", {
        "side": side,
        "outgoing_player_id": options.outgoing_ids[0],
        "incoming_player_id": options.incoming_ids[0],
    }


def _shootout_order(fixture: PromptFixture) -> tuple[str, dict]:
    options = _prompt(fixture).options
    side = options.owed()[0]
    return "send", {"side": side, "player_id": options.for_side(side)[0]}


def _shootout_pick(fixture: PromptFixture) -> tuple[str, dict]:
    options = _prompt(fixture).options
    side = options.owed()[0]
    return "", {"side": side, "player_id": options.for_side(side)[0]}


def _player_action(fixture: PromptFixture) -> tuple[str, dict]:
    """
    Taking a turn needs a ball handler and the branch does not.

    `PLAYER_ACTION` is the chain's fallback as well as the turn's own
    question, and the first fixture standing in it is a time-out tail
    -- a position whose *next* step is the bot's. Standing a handler up
    is the fixture finishing the position rather than the test reaching
    past it, the same as the own-goal roll's.
    """
    match = fixture.match
    if match.active_player_id is None:
        match.active_player_id = match.home.field_players[0]
    return "maneuver", {}


def _maneuver_action(fixture: PromptFixture) -> tuple[str, dict]:
    hand = _prompt(fixture).options.hands[0]
    return "", {"side": hand.side, "maneuver_key": hand.maneuver_keys[0]}


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
    return "roll", {}


def _low_pass(fixture: PromptFixture) -> tuple[str, dict]:
    return "", {"distance": _prompt(fixture).options.passes[0].distance}


def _first_distance(fixture: PromptFixture) -> tuple[str, dict]:
    return "", {"distance": _prompt(fixture).options.distances[0]}


def _speed_delta(fixture: PromptFixture) -> tuple[str, dict]:
    # The middle of the range, which is the current speed until the
    # ball's own limits clamp one end.
    targets = _prompt(fixture).options.targets
    return "", {"target_speed": targets[len(targets) // 2]}


#: The kinds that have a row in `driver.ANSWERS` and no legal answer:
#: a finished game asks nothing, and its row refuses every action.
UNANSWERABLE = frozenset({PromptKind.GAME_OVER})


#: A legal answer to each prompt the driver can apply one to, read off
#: the prompt's `options` the way a frontend reads them to build its
#: buttons -- and nothing off the match, which is principle 10 as a
#: thing that can be run (see `tests/test_driver_full_game.py`).
#:
#: **Every kind in `driver.ANSWERS` has a row**, which
#: `test_every_answerable_kind_has_a_legal_action` asserts -- so a kind
#: that arrives in the table without one fails here rather than going
#: untested.
LEGAL_ACTIONS = {
    PromptKind.BALL_HANDLER_SELECTION: _first_player,
    PromptKind.RUN_BACK_PLAYER: _first_player,
    PromptKind.RUN_BACK_SPACE: _run_back_space,
    PromptKind.BALL_RECOVERY: _first_player,
    PromptKind.LOOSE_BALL_PICK: _loose_ball_pick,
    PromptKind.SET_UP_ATTEMPT: lambda fixture: ("take", {}),
    PromptKind.SHOOTER_CHOICE: _shooter_choice,
    PromptKind.SMOOTH: lambda fixture: ("take", {}),
    PromptKind.OWN_GOAL_ROLL: _own_goal,
    # The two contested rolls take no arguments at all: the action
    # is that somebody pressed, and the position is the rest.
    PromptKind.SKILL_TEST: lambda fixture: ("roll", {}),
    PromptKind.LOOSE_BALL_SKILL_TEST: lambda fixture: ("roll", {}),
    PromptKind.SCORE_ATTEMPT: lambda fixture: ("roll", {}),
    PromptKind.SHOOTOUT_TEST: lambda fixture: ("roll", {}),
    PromptKind.INJURY_TEST: lambda fixture: ("roll", {}),
    PromptKind.PLAYER_ACTION: _player_action,
    PromptKind.COACHING_OFFER: _coaching_offer,
    PromptKind.COACHING_HUB: _coaching_hub,
    PromptKind.SHOOTOUT_ORDER: _shootout_order,
    PromptKind.SHOOTOUT_PICK: _shootout_pick,
    PromptKind.MANEUVER_CHALLENGE: _loose_ball_pick,
    PromptKind.MANEUVER_ACTION: _maneuver_action,
    PromptKind.MIND_PULL: lambda fixture: ("take", {}),
    PromptKind.HALFTIME_EXTRA_TOKEN: _first_player,
    PromptKind.LOW_PASS_CHOICE: _low_pass,
    PromptKind.HIGH_PASS_CHOICE: _first_distance,
    PromptKind.SETUP_PASS_CHOICE: _first_distance,
    PromptKind.SPEED_DELTA_CHOICE: _speed_delta,
    PromptKind.DRIBBLE_ADVANCE_CHOICE: _first_distance,
    PromptKind.DRIBBLE_BURST_CHOICE: _first_distance,
    PromptKind.SETUP_PASS_PUSH_BACK: _first_distance,
    PromptKind.TUTORIAL_CONTINUE: lambda fixture: ("", {}),
}


#: The cases whose kind the driver can answer, one per kind -- several
#: fixtures stand in the same branch (three Low Passes, two speed
#: choices) and one of each is enough to assert the seam.
def _answerable_cases():
    seen = set()
    for case in CASES:
        if not case.asked:
            continue
        kind = PromptKind[case.kind]
        if kind in LEGAL_ACTIONS and kind not in seen:
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
        self.assertEqual(
            set(LEGAL_ACTIONS) | UNANSWERABLE, set(driver.ANSWERS),
        )

    def test_every_answerable_kind_is_reached_by_a_fixture(self) -> None:
        """
        And every one of them has a match standing in it, so the
        assertions below actually run for each.
        """
        self.assertEqual(
            {kind for _, kind in _answerable_cases()},
            set(LEGAL_ACTIONS),
        )

    def test_a_finished_game_refuses_every_answer(self) -> None:
        """
        `GAME_OVER` has a row so every kind has one, and the row
        refuses: nothing is asked of a finished game, and the rematch
        under its last message opens a new game rather than acting on
        this one.
        """
        fixture = next(
            case for case in CASES if case.kind == "GAME_OVER"
        ).build()
        refusal = driver.apply(
            ENGINE, fixture.game, fixture.match, driver.Action(PromptKind.GAME_OVER),
        )
        self.assertIsInstance(refusal, driver.Refusal)
        self.assertIs(refusal.waiting_on.kind, PromptKind.GAME_OVER)

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

        **This covers the two refusals `answer` makes before any
        adapter runs** -- the wrong kind and an unoffered choice -- and
        that is the whole of what it can claim. An adapter that runs
        and *then* refuses is a different question, answered adapter
        by adapter: each checks its argument against the candidate
        list before it calls the step, since the last increment of
        Phase 6; see "What `answer` refuses, and what it does not" in
        docs/design/model-discord-split.md.
        """
        for case, kind in _answerable_cases():
            with self.subTest(case.name):
                fixture = case.build()
                before = fixture.match.to_dict()
                other = (
                    PromptKind.SHOOTOUT_PICK
                    if kind is not PromptKind.SHOOTOUT_PICK
                    else PromptKind.PLAYER_ACTION
                )
                driver.apply(
                    ENGINE, fixture.game, fixture.match, driver.Action(other),
                )
                self.assertEqual(fixture.match.to_dict(), before)


class OwedStepTests(ApplyFixture):
    """
    A position the bot owes a step on refuses every answer, before any
    adapter runs and whatever kind it names -- finding 1 of
    docs/web-app.md: a turn action used to be **Answered** on the
    `run_back_finished` fixture, with `pending_run_back` still set
    underneath the maneuver it started.
    """

    def test_every_owed_state_refuses_every_kind_and_changes_nothing(
        self,
    ) -> None:
        for case in CASES:
            if case.asked:
                continue
            for kind in LEGAL_ACTIONS:
                with self.subTest(f"{case.name} / {kind.name}"):
                    fixture = case.build()
                    before = fixture.match.to_dict()

                    refusal = driver.apply(
                        ENGINE, fixture.game, fixture.match, driver.Action(kind),
                    )

                    self.assertIsInstance(refusal, driver.Refusal)
                    self.assertEqual(refusal.reason, driver.STEP_OWED)
                    self.assertIsNone(refusal.waiting_on)
                    self.assertEqual(fixture.match.to_dict(), before)

    def test_a_turn_action_mid_cascade_no_longer_starts_a_maneuver(
        self,
    ) -> None:
        fixture = next(
            case for case in CASES if case.name == "run back, nothing left"
        ).build()

        refusal = driver.apply(
            ENGINE,
            fixture.game,
            fixture.match,
            driver.Action(PromptKind.PLAYER_ACTION, "maneuver"),
        )

        self.assertIsInstance(refusal, driver.Refusal)
        self.assertIsNone(fixture.match.pending_action)
        self.assertTrue(fixture.match.pending_run_back)


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
        rule behind it. Nor "both halves change the match": clearing a
        shooting order nobody has started is a legal answer that leaves
        the position exactly as it was, the way the run back's "who
        runs" pick does. What this asserts is that every offered choice
        reaches a real answer -- a refusal here has to be a rule, and
        never "that is not one of the answers this question offers".
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
                        driver.Action(kind, choice, arguments),
                    )
                    if isinstance(run, driver.Refusal):
                        self.assertNotEqual(run.reason, unknown)
                        self.assertEqual(fixture.match.to_dict(), before)
                        continue
                    self.assertIsInstance(run, driver.DriverRun)


class OverdriveTests(ApplyFixture):
    """
    The one answer that does not settle the question it answers.

    Overdrive is declared *before* a roll and spent by it, so it comes
    back on the same prompt with the roll still owed -- which is the
    coaching hub's shape rather than a new one.
    """

    def test_every_roll_prompt_offers_it(self) -> None:
        """
        The six are the rules' own list, and they are exactly the
        prompts a roll is asked on.
        """
        for kind in driver.ROLL_KINDS:
            with self.subTest(kind.name):
                self.assertIn("overdrive", driver.CHOICES[kind])
                self.assertIn("roll", driver.CHOICES[kind])

    def cyborg_skill_test(self):
        """
        A skill test with a Cyborg on each side of it.

        The shared fixtures play a **basic** game between two colour
        teams, where no Overdrive is ever offered -- so this one is
        built here: the two species teams, an advanced game with
        species abilities on, and the contest put between two of them.
        `mode` is set as well as the flag, which is the trap
        `RulesEngine.species_abilities_apply` exists to close.
        """
        game = build_game(
            player_1_team=Team.CYBORGS,
            player_2_team=Team.CYBORGS,
            mode=GameMode.ADVANCED,
            species_abilities=True,
        )
        match = MatchState.standard(
            catalog=CATALOG,
            ruleset=RULESET,
            board_size=7,
            home_team=Team.CYBORGS,
            visiting_team=Team.CYBORGS,
            home_formation=Formation.TWO_TWO_TWO,
        )
        challenge(match)
        match.offense_maneuver = "low_pass"
        match.defense_maneuver = "deflect"
        return PromptFixture(game, match, "Either player can roll:")

    def test_a_declaration_comes_back_on_the_same_prompt(self) -> None:
        fixture = self.cyborg_skill_test()
        match = fixture.match
        roller = match.active_player_id
        run = driver.apply(
            ENGINE,
            fixture.game,
            match,
            driver.Action(
                PromptKind.SKILL_TEST,
                "overdrive",
                {"player_id": roller},
            ),
        )
        self.assertNotIsInstance(run, driver.Refusal)
        self.assertEqual(run.result.next.kind, PromptKind.SKILL_TEST)
        self.assertIn("Overdrive", run.result.narration[0])
        self.assertTrue(match.overdrive_modifier(roller))

    def test_a_player_who_is_not_in_this_roll_is_refused(self) -> None:
        """
        The list is the roll's, not the field's -- which is what makes
        a scrolled-back prompt unable to declare for somebody else's
        contest.
        """
        fixture = self.cyborg_skill_test()
        match = fixture.match
        outsider = next(
            player_id
            for player_id in match.home.field_players
            if player_id not in (match.active_player_id, match.challenger_id)
        )
        before = match.to_dict()
        refusal = driver.apply(
            ENGINE,
            fixture.game,
            match,
            driver.Action(
                PromptKind.SKILL_TEST,
                "overdrive",
                {"player_id": outsider},
            ),
        )
        self.assertIsInstance(refusal, driver.Refusal)
        self.assertEqual(match.to_dict(), before)

    def test_a_second_declaration_for_one_player_is_refused(self) -> None:
        """Once per roll, which `overdrive_candidates` is the reading of."""
        fixture = self.cyborg_skill_test()
        action = driver.Action(
            PromptKind.SKILL_TEST,
            "overdrive",
            {"player_id": fixture.match.active_player_id},
        )
        driver.apply(ENGINE, fixture.game, fixture.match, action)
        before = fixture.match.to_dict()
        refusal = driver.apply(ENGINE, fixture.game, fixture.match, action)
        self.assertIsInstance(refusal, driver.Refusal)
        self.assertEqual(fixture.match.to_dict(), before)


def _case(name: str) -> PromptFixture:
    return next(case.build() for case in CASES if case.name == name)


def _refused(fixture: PromptFixture, action: driver.Action) -> driver.Refusal:
    """Apply `action` and assert it was refused with the match untouched."""
    before = fixture.match.to_dict()
    outcome = driver.apply(ENGINE, fixture.game, fixture.match, action)
    assert isinstance(outcome, driver.Refusal), outcome
    assert fixture.match.to_dict() == before, "a refusal moved something"
    return outcome


class PositionRefusalTests(ApplyFixture):
    """
    A step refusing what was chosen, which arrives as a `RuleRefusal`
    and leaves as a `Refusal`.
    """

    def test_an_argument_a_choice_needs_is_refused_as_missing(self) -> None:
        """
        Finding 4 of docs/web-app.md: a hub `reposition` with no
        `space_index` used to raise `TypeError` out of
        `MatchState.position_meeple`, past the driver's `ValueError`
        net. `REQUIRED_ARGUMENTS` names it, so it is refused before
        the adapter runs.
        """
        fixture = _case("coaching hub")
        side = fixture.match.pending_coaching_side
        player_id = fixture.match.setup_for_side(side).field_players[0]
        refusal = _refused(
            fixture,
            driver.Action(
                PromptKind.COACHING_HUB, "reposition",
                {"side": side, "player_id": player_id},
            ),
        )
        self.assertEqual(refusal.reason, "This answer needs space_index.")

    def test_only_a_rule_refusal_is_a_refusal(self) -> None:
        """
        A bare `ValueError` out of an adapter is the interpreter's
        sentence, not the position's, and propagates as a bug rather
        than being shown to a coach as a rule.
        """
        fixture = _case("coaching hub")
        with self.assertRaises(ValueError) as caught:
            driver.apply(
                ENGINE, fixture.game, fixture.match,
                driver.Action(
                    PromptKind.COACHING_HUB, "done", {"side": "sideways"},
                ),
            )
        self.assertNotIsInstance(caught.exception, RuleRefusal)


# -- A refused answer per kind per choice ----------------------------


def _other_side(side) -> TeamSide:
    return TeamSide.VISITING if TeamSide(side) is TeamSide.HOME else TeamSide.HOME


def _not_offered(offered, universe) -> str:
    """Somebody the prompt does not offer, from a wider pool."""
    return next(candidate for candidate in universe if candidate not in offered)


def _everybody(match: MatchState) -> list[str]:
    return (
        match.home.field_players + match.home.team_board.bench
        + match.visiting.field_players + match.visiting.team_board.bench
    )


def _wrong_player(fixture: PromptFixture) -> dict:
    options = _prompt(fixture).options
    return {
        "player_id": _not_offered(options.player_ids, _everybody(fixture.match)),
    }


def _wrong_distance(fixture: PromptFixture) -> dict:
    return {"distance": 99}


def _wrong_side_player(fixture: PromptFixture) -> dict:
    """SMOOTH, MIND_PULL, INJURY_TEST: a player the prompt is not
    about."""
    prompt = _prompt(fixture)
    return {
        "player_id": _not_offered((prompt.player_id,), _everybody(fixture.match)),
    }


def _wrong_overdrive(fixture: PromptFixture) -> dict:
    """A player who is not in this roll."""
    match = fixture.match
    if match.active_player_id is None:
        match.active_player_id = match.home.field_players[0]
    options = _prompt(fixture).options
    return {
        "player_id": _not_offered(
            options.overdrive_player_ids, match.home.team_board.bench,
        ),
    }


def _railed_tutorial(fixture: PromptFixture, key: str, wanted: str) -> None:
    """Put the fixture's game on the beat that rails `key` to `wanted`."""
    beat = next(
        beat for beat in tutorial.BEATS if beat.choices.get(key) == wanted
    )
    fixture.game = build_game(
        player_2_id=None, tutorial=True, tutorial_step=beat.step,
    )


def _railed_set_up_decline(fixture: PromptFixture) -> dict:
    _railed_tutorial(fixture, "setup_attempt", "attempt")
    return {}


def _decline_with_somebody_on_the_ball(fixture: PromptFixture) -> dict:
    """The fixture's side has a player standing on the ball, so the
    contest is not theirs to decline (`may_decline_loose_ball`)."""
    assert not _prompt(fixture).options.may_decline
    return {}


def _shot_out_of_range(fixture: PromptFixture) -> dict:
    match = fixture.match
    if match.active_player_id is None:
        match.active_player_id = match.home.field_players[0]
    assert not match.can_attempt_score()
    return {"action_label": "shoot"}


def _time_out_in_the_last_minute(fixture: PromptFixture) -> dict:
    match = fixture.match
    if match.active_player_id is None:
        match.active_player_id = match.home.field_players[0]
    match.scoreboard.last_possession = True
    return {}


def _other_side_s_window(fixture: PromptFixture) -> dict:
    return {"side": _other_side(_coaching_side(fixture))}


def _other_side_s_offer_decline(fixture: PromptFixture) -> dict:
    return {**_other_side_s_window(fixture), "coach_name": "Coach"}


def _formation_off_the_board(fixture: PromptFixture) -> dict:
    side = _coaching_side(fixture)
    options = _prompt(fixture).options
    return {
        "side": side,
        "formation": next(
            shape for shape in Formation if shape not in options.formations
        ),
    }


def _substitute_from_the_field(fixture: PromptFixture) -> dict:
    side = _coaching_side(fixture)
    options = _prompt(fixture).options
    return {
        "side": side,
        "outgoing_player_id": options.outgoing_ids[0],
        "incoming_player_id": options.outgoing_ids[1],
    }


def _swap_inside_a_zone(fixture: PromptFixture) -> dict:
    side = _coaching_side(fixture)
    zones = fixture.match.setup_for_side(side).zones
    first, second = next(
        players for players in zones.values() if len(players) >= 2
    )[:2]
    return {"side": side, "player_id": first, "other_player_id": second}


def _reposition_off_the_zone(fixture: PromptFixture) -> dict:
    side = _coaching_side(fixture)
    options = _prompt(fixture).options
    return {
        "side": side,
        "player_id": options.repositions[0].player_id,
        "space_index": 99,
    }


def _shootout_wrong_player(fixture: PromptFixture) -> dict:
    options = _prompt(fixture).options
    side = options.owed()[0]
    return {
        "side": side,
        "player_id": _not_offered(options.for_side(side), _everybody(fixture.match)),
    }


def _restart_for_the_other_side(fixture: PromptFixture) -> dict:
    """A side whose order is complete has nothing to start over."""
    match = fixture.match
    options = _prompt(fixture).options
    side = options.owed()[0]
    for player_id in options.for_side(side):
        match.add_to_shootout_order(side, player_id)
    return {"side": side}


def _defender_on_the_ball(fixture: PromptFixture) -> dict:
    match = fixture.match
    walker = match.setup_for_side(match.defending_side()).field_players[0]
    match.board.remove_meeple(walker)
    match.board.place_meeple(walker, match.ball.zone, match.ball.space_index)
    return {"player_id": None}


def _card_not_in_hand(fixture: PromptFixture) -> dict:
    hand = _prompt(fixture).options.hands[0]
    return {"side": hand.side, "maneuver_key": "no_such_card"}


def _ai_side_s_shot(fixture: PromptFixture) -> dict:
    fixture.game = build_game(player_2_id=None)
    match = fixture.match
    match.pending_action = None
    match.active_player_id = None
    match.ball.possession = TeamSide.VISITING
    handler = match.visiting.field_players[0]
    match.board.remove_meeple(handler)
    match.board.place_meeple(handler, match.ball.zone, match.ball.space_index)
    match.select_ball_handler(handler)
    match.pending_action = "shoot"
    return {}


def _wrong_speed(fixture: PromptFixture) -> dict:
    return {"target_speed": 99}


def _three_space_advance(fixture: PromptFixture) -> dict:
    return {"distance": 3}


def _wrong_shooter(fixture: PromptFixture) -> dict:
    options = _prompt(fixture).options
    return {
        "shooter_id": _not_offered(options.player_ids, _everybody(fixture.match)),
    }


def _wrong_receiver(fixture: PromptFixture) -> dict:
    option = _prompt(fixture).options.passes[0]
    return {
        "distance": option.distance,
        "receiver_id": _not_offered(option.receiver_ids, _everybody(fixture.match)),
    }


#: For every kind the driver answers and every choice it offers, an
#: answer of that choice the position refuses -- built off the prompt's
#: options as the wrong thing: a player the prompt does not offer, a
#: distance off the field, the other side's window, a rail the tutorial
#: has fixed. `None` where the choice takes nothing the position could
#: refuse (a roll is the button either coach may press; the tutorial's
#: Continue holds nothing), so the wrong-kind refusal is the whole of
#: what can go wrong with it.
#:
#: **Every pair has a row**, which `test_every_choice_has_a_refusal`
#: asserts against `driver.ANSWERS` and `driver.CHOICES`; each refusal
#: leaves the match byte for byte as it was, which is
#: `test_a_refused_choice_changes_nothing`. The builder may finish the
#: fixture's position first (a handler stood up, a rail put on), and
#: the snapshot is taken after it has.
REFUSED_ACTIONS = {
    (PromptKind.TUTORIAL_CONTINUE, ""): None,
    (PromptKind.SETUP_PASS_PUSH_BACK, ""): _wrong_distance,
    (PromptKind.BALL_HANDLER_SELECTION, ""): _wrong_player,
    (PromptKind.RUN_BACK_PLAYER, ""): _wrong_player,
    (PromptKind.RUN_BACK_SPACE, ""): lambda fixture: {"space_index": 99},
    (PromptKind.BALL_RECOVERY, ""): _wrong_player,
    (PromptKind.LOOSE_BALL_PICK, "send"): _wrong_player,
    (PromptKind.LOOSE_BALL_PICK, "decline"): _decline_with_somebody_on_the_ball,
    (PromptKind.SET_UP_ATTEMPT, "take"): None,
    (PromptKind.SET_UP_ATTEMPT, "decline"): _railed_set_up_decline,
    (PromptKind.SHOOTER_CHOICE, ""): _wrong_shooter,
    (PromptKind.SMOOTH, "take"): _wrong_side_player,
    (PromptKind.SMOOTH, "decline"): _wrong_side_player,
    (PromptKind.OWN_GOAL_ROLL, "roll"): None,
    (PromptKind.OWN_GOAL_ROLL, "overdrive"): _wrong_overdrive,
    (PromptKind.PLAYER_ACTION, "shoot"): _shot_out_of_range,
    # A maneuver is always on: the position refuses it by kind alone.
    (PromptKind.PLAYER_ACTION, "maneuver"): None,
    (PromptKind.PLAYER_ACTION, "time_out"): _time_out_in_the_last_minute,
    (PromptKind.COACHING_OFFER, "declare"): _other_side_s_window,
    (PromptKind.COACHING_OFFER, "decline"): _other_side_s_offer_decline,
    (PromptKind.COACHING_HUB, "formation"): _formation_off_the_board,
    (PromptKind.COACHING_HUB, "substitute"): _substitute_from_the_field,
    (PromptKind.COACHING_HUB, "swap"): _swap_inside_a_zone,
    (PromptKind.COACHING_HUB, "reposition"): _reposition_off_the_zone,
    (PromptKind.COACHING_HUB, "done"): _other_side_s_window,
    (PromptKind.SHOOTOUT_ORDER, "send"): _shootout_wrong_player,
    (PromptKind.SHOOTOUT_ORDER, "restart"): _restart_for_the_other_side,
    (PromptKind.SHOOTOUT_PICK, ""): _shootout_wrong_player,
    (PromptKind.MANEUVER_CHALLENGE, "send"): _wrong_player,
    (PromptKind.MANEUVER_CHALLENGE, "decline"): _defender_on_the_ball,
    (PromptKind.MANEUVER_ACTION, ""): _card_not_in_hand,
    (PromptKind.INJURY_TEST, "roll"): _wrong_side_player,
    (PromptKind.INJURY_TEST, "overdrive"): _wrong_overdrive,
    (PromptKind.MIND_PULL, "take"): _wrong_side_player,
    (PromptKind.MIND_PULL, "decline"): _wrong_side_player,
    (PromptKind.HALFTIME_EXTRA_TOKEN, ""): _wrong_player,
    (PromptKind.SKILL_TEST, "roll"): None,
    (PromptKind.SKILL_TEST, "overdrive"): _wrong_overdrive,
    (PromptKind.LOOSE_BALL_SKILL_TEST, "roll"): None,
    (PromptKind.LOOSE_BALL_SKILL_TEST, "overdrive"): _wrong_overdrive,
    (PromptKind.SCORE_ATTEMPT, "roll"): None,
    (PromptKind.SCORE_ATTEMPT, "back"): _ai_side_s_shot,
    (PromptKind.SCORE_ATTEMPT, "overdrive"): _wrong_overdrive,
    (PromptKind.SHOOTOUT_TEST, "roll"): None,
    (PromptKind.SHOOTOUT_TEST, "overdrive"): _wrong_overdrive,
    (PromptKind.LOW_PASS_CHOICE, ""): _wrong_receiver,
    (PromptKind.HIGH_PASS_CHOICE, ""): _wrong_distance,
    (PromptKind.SETUP_PASS_CHOICE, ""): _wrong_distance,
    (PromptKind.SPEED_DELTA_CHOICE, ""): _wrong_speed,
    (PromptKind.DRIBBLE_ADVANCE_CHOICE, ""): _three_space_advance,
    (PromptKind.DRIBBLE_BURST_CHOICE, ""): _wrong_distance,
}


class RefusedChoiceTests(ApplyFixture):
    """
    Every choice every kind offers, refused by the position and leaving
    it untouched -- the second half of `test_a_refused_action_changes_nothing`,
    which covers only the two refusals `answer` makes before an adapter
    runs. Since step 6 of docs/architecture-migration.md every rule a
    button held is the adapter's, and this is where that is measured.
    """

    def test_every_choice_has_a_refusal(self) -> None:
        pairs = {
            (kind, choice)
            for kind in driver.ANSWERS
            if kind not in UNANSWERABLE
            for choice in driver.CHOICES.get(kind, ("",))
        }
        self.assertEqual(set(REFUSED_ACTIONS), pairs)

    def test_a_refused_choice_changes_nothing(self) -> None:
        for case, kind in _answerable_cases():
            for choice in driver.CHOICES.get(kind, ("",)):
                build = REFUSED_ACTIONS[(kind, choice)]
                if build is None:
                    continue
                with self.subTest(case=case.name, choice=choice or "-"):
                    fixture = case.build()
                    arguments = build(fixture)
                    self.assertIs(
                        pending_prompt(ENGINE, fixture.game, fixture.match).kind,
                        kind,
                        "the builder moved the fixture off its prompt",
                    )
                    before = fixture.match.to_dict()
                    outcome = driver.apply(
                        ENGINE, fixture.game, fixture.match,
                        driver.Action(kind, choice, arguments),
                    )
                    self.assertIsInstance(outcome, driver.Refusal, outcome)
                    self.assertTrue(outcome.reason)
                    self.assertEqual(fixture.match.to_dict(), before)


class ButtonRuleTests(ApplyFixture):
    """
    The rules a disabled button used to hold alone, now refused by the
    adapter (finding 3 of docs/web-app.md; step 6 of the migration).
    Each refusal leaves the match untouched.
    """

    def test_a_substitution_past_the_allowance_is_refused(self) -> None:
        fixture = _case("coaching hub")
        match = fixture.match
        side = match.pending_coaching_side
        setup = match.setup_for_side(side)
        # Spend the window's allowance through the same door.
        while match.may_substitute():
            run = driver.apply(
                ENGINE, fixture.game, match,
                driver.Action(
                    PromptKind.COACHING_HUB, "substitute",
                    {
                        "side": side,
                        "outgoing_player_id": setup.field_players[0],
                        "incoming_player_id": match.substitution_pool(side)[0],
                    },
                ),
            )
            self.assertIsInstance(run, driver.DriverRun)
        refusal = _refused(
            fixture,
            driver.Action(
                PromptKind.COACHING_HUB, "substitute",
                {
                    "side": side,
                    "outgoing_player_id": setup.field_players[0],
                    "incoming_player_id": match.substitution_pool(side)[0],
                },
            ),
        )
        self.assertIn("No substitutions left", refusal.reason)

    def test_a_swap_inside_one_zone_is_refused(self) -> None:
        """A swap that moves nobody is not a swap (the author,
        2026-09-21)."""
        fixture = _case("coaching hub")
        match = fixture.match
        side = match.pending_coaching_side
        zones = match.setup_for_side(side).zones
        first, second = next(
            players for players in zones.values() if len(players) >= 2
        )[:2]
        refusal = _refused(
            fixture,
            driver.Action(
                PromptKind.COACHING_HUB, "swap",
                {"side": side, "player_id": first, "other_player_id": second},
            ),
        )
        self.assertIn("same zone", refusal.reason)

    def test_an_ai_side_s_shot_is_never_walked_back(self) -> None:
        """
        Not a rule of the game but a feature of how the AI plays: it
        does not misclick (the author, 2026-09-21). The visiting side
        is Dinky's in a solo game, so its shot is the fixture's with
        the ball turned over.
        """
        fixture = _case("score attempt")
        fixture.game = build_game(player_2_id=None)
        match = fixture.match
        match.pending_action = None
        match.active_player_id = None
        match.ball.possession = TeamSide.VISITING
        handler = match.visiting.field_players[0]
        match.board.remove_meeple(handler)
        match.board.place_meeple(handler, match.ball.zone, match.ball.space_index)
        match.select_ball_handler(handler)
        match.pending_action = "shoot"
        self.assertTrue(ENGINE.side_is_ai(fixture.game, TeamSide.VISITING))
        self.assertIs(
            pending_prompt(ENGINE, fixture.game, match).kind,
            PromptKind.SCORE_ATTEMPT,
        )
        refusal = _refused(
            fixture, driver.Action(PromptKind.SCORE_ATTEMPT, "back"),
        )
        self.assertIn("shot stands", refusal.reason)

    def test_declining_a_challenge_a_defender_on_the_ball_owes_is_refused(
        self,
    ) -> None:
        fixture = _case("maneuver challenge")
        match = fixture.match
        defender = match.defending_side()
        walker = match.setup_for_side(defender).field_players[0]
        match.board.remove_meeple(walker)
        match.board.place_meeple(walker, match.ball.zone, match.ball.space_index)
        self.assertFalse(match.may_decline_challenge())
        refusal = _refused(
            fixture, driver.Action(PromptKind.MANEUVER_CHALLENGE, "decline"),
        )
        self.assertEqual(
            refusal.reason, "A defender on the ball's space has to challenge.",
        )

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

    def test_every_prompt_kind_has_a_model_answer(self) -> None:
        """
        **The claim Phase 6 was for**: a frontend that authorises a
        person and calls `apply` can drive every question this game
        asks. It is asserted as an equality rather than a subset so a
        new kind arriving without an answer fails here, once, rather
        than in whatever corner of a game reaches it.
        """
        self.assertEqual(set(driver.ANSWERS), set(PromptKind))


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


class AIAnswerTests(ApplyFixture):
    """
    **The AI chooses an `Action` like anyone else** (ARCHITECTURE.md,
    "AI"; step 7 of docs/architecture-migration.md). Every fixture in
    the shared table is stood in front of Dinky on either side of the
    board, and wherever the question is Dinky's -- `asked_sides` says
    so -- its answer has to be one `driver.answer` accepts: an action
    the prompt offers, with the arguments the adapter needs. A
    strategy that reads past the offer is refused here, once, rather
    than raising out of the middle of a game.
    """

    @staticmethod
    def _solo(fixture, ai_number: int):
        """The fixture's game with player 2 an AI on the given side."""
        game = fixture.game
        game.player_2_id = None
        game.tutorial = False
        game.tutorial_step = None
        game.home_player_number = ai_number
        game.visiting_player_number = 3 - ai_number
        return game

    def _dinkys_questions(self):
        for case in CASES:
            if not case.asked:
                continue
            for ai_number in (1, 2):
                fixture = case.build()
                game = self._solo(fixture, ai_number)
                prompt = pending_prompt(ENGINE, game, fixture.match)
                if prompt is None:
                    continue
                action = driver.ai_action(ENGINE, game, fixture.match, prompt)
                if action is None:
                    continue
                yield f"{case.name}, the AI {'home' if ai_number == 1 else 'visiting'}", fixture, game, prompt, action

    def test_dinky_s_answer_to_every_question_put_to_it_is_accepted(
        self,
    ) -> None:
        reached = set()
        for name, fixture, game, prompt, action in self._dinkys_questions():
            with self.subTest(name):
                self.assertIs(action.kind, prompt.kind)
                answered = driver.answer(ENGINE, game, fixture.match, action)
                self.assertNotIsInstance(
                    answered,
                    driver.Refusal,
                    getattr(answered, "reason", None),
                )
                reached.add(prompt.kind)
        # Every question Dinky can be asked was asked of it at least
        # once, on some fixture: a kind missing here is a branch of
        # `DinkyAI.choose` nothing is watching.
        self.assertEqual(reached, set(DinkyAI.ANSWERS))

    def test_dinky_is_never_asked_a_roll(self) -> None:
        """
        Every roll waits behind a button either coach may press
        (CLAUDE.md, "Nothing rolls dice on its own"): a roll prompt is
        nobody's question, so the service never answers one for the
        AI, on either side of the board.
        """
        for case in CASES:
            if not case.asked or PromptKind[case.kind] not in driver.ROLL_KINDS:
                continue
            for ai_number in (1, 2):
                with self.subTest(f"{case.name}, the AI {ai_number}"):
                    fixture = case.build()
                    game = self._solo(fixture, ai_number)
                    prompt = pending_prompt(ENGINE, game, fixture.match)
                    self.assertIsNone(
                        driver.ai_action(ENGINE, game, fixture.match, prompt),
                    )

    def test_the_kinds_nobody_owns_are_the_rolls_and_the_two_with_no_side(
        self,
    ) -> None:
        self.assertEqual(
            NOBODYS_QUESTIONS,
            driver.ROLL_KINDS
            | {PromptKind.TUTORIAL_CONTINUE, PromptKind.GAME_OVER},
        )
        self.assertEqual(
            set(DinkyAI.ANSWERS), set(PromptKind) - NOBODYS_QUESTIONS,
        )


class SaveTests(ApplyFixture):
    """`apply` saves nothing -- principle 9."""

    def test_applying_an_action_leaves_the_record_unwritten(self) -> None:
        """
        The *game record* is what a save writes, and `apply` does not
        touch it: `D12Ball.persist` sets `game.match_state` and calls
        `save_games`, and the caller does that once, after this.

        **Asserted on the record rather than on `save_games`**, because
        a patch on that function cannot fail here -- nothing under
        `d12ball/` imports it, which `tests/test_model_purity.py` is
        the real guard for. `game.match_state` is a thing an adapter
        could plausibly write by reaching for `to_dict`, so it is the
        one worth watching.
        """
        for case, kind in _answerable_cases():
            with self.subTest(case.name):
                fixture = case.build()
                before = fixture.game.match_state
                choice, arguments = LEGAL_ACTIONS[kind](fixture)
                driver.apply(
                    ENGINE,
                    fixture.game,
                    fixture.match,
                    driver.Action(kind, choice, arguments),
                )
                self.assertIs(fixture.game.match_state, before)


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
