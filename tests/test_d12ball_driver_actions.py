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

from d12ball.components import MatchState, TeamSide
from d12ball.game import Formation, GameMode, Team
from d12ball.flow import driver
from d12ball.flow.effects import setup_pass_push_back_distances
from d12ball.flow.windows import open_substitution_window
from d12ball.prompts import PromptKind, pending_prompt

from prompt_fixtures import (
    CASES,
    CATALOG,
    ENGINE,
    RULESET,
    PromptFixture,
    build_game,
    challenge,
)


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
    match = fixture.match
    side = _coaching_side(fixture)
    setup = match.setup_for_side(side)
    return "substitute", {
        "side": side,
        "outgoing_player_id": setup.field_players[0],
        "incoming_player_id": setup.team_board.bench[0],
    }


def _shootout_order(fixture: PromptFixture) -> tuple[str, dict]:
    match = fixture.match
    side = next(
        side for side in TeamSide
        if match.shootout_order_remaining(side)
    )
    return "send", {
        "side": side,
        "player_id": match.shootout_order_remaining(side)[0],
    }


def _shootout_pick(fixture: PromptFixture) -> tuple[str, dict]:
    match = fixture.match
    side = next(
        side for side in TeamSide if match.shootout_shooter(side) is None
    )
    return "", {
        "side": side,
        "player_id": match.shootout_eligible(side)[0],
    }


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


def _maneuver_challenge(fixture: PromptFixture) -> tuple[str, dict]:
    return "send", {
        "player_id": fixture.match.challenge_candidates()[0],
    }


def _maneuver_action(fixture: PromptFixture) -> tuple[str, dict]:
    match = fixture.match
    hand = ENGINE.maneuver_hand(fixture.game, match, "offense")
    return "", {"side": "offense", "maneuver_key": hand[0].key}


def _halftime_extra_token(fixture: PromptFixture) -> tuple[str, dict]:
    match = fixture.match
    side = pending_prompt(ENGINE, fixture.game, match).side
    return "", {
        "player_id": next(
            player_id
            for player_id in match.setup_for_side(side).field_players
            if player_id not in match.injured
        ),
    }


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


def _setup_pass_push_back(fixture: PromptFixture) -> tuple[str, dict]:
    return "", {
        "distance": setup_pass_push_back_distances(fixture.match)[0],
    }


#: The kinds that have a row in `driver.ANSWERS` and no legal answer:
#: a finished game asks nothing, and its row refuses every action.
UNANSWERABLE = frozenset({PromptKind.GAME_OVER})


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
    PromptKind.MANEUVER_CHALLENGE: _maneuver_challenge,
    PromptKind.MANEUVER_ACTION: _maneuver_action,
    PromptKind.MIND_PULL: lambda fixture: ("take", {}),
    PromptKind.HALFTIME_EXTRA_TOKEN: _halftime_extra_token,
    PromptKind.LOW_PASS_CHOICE: _low_pass,
    PromptKind.HIGH_PASS_CHOICE: _high_pass,
    PromptKind.SETUP_PASS_CHOICE: _setup_pass,
    PromptKind.SPEED_DELTA_CHOICE: _speed_delta,
    PromptKind.DRIBBLE_ADVANCE_CHOICE: lambda fixture: ("", {"distance": 1}),
    PromptKind.DRIBBLE_BURST_CHOICE: _dribble_burst,
    PromptKind.SETUP_PASS_PUSH_BACK: _setup_pass_push_back,
    PromptKind.TUTORIAL_CONTINUE: lambda fixture: ("", {}),
}


#: The cases whose kind the driver can answer, one per kind -- several
#: fixtures stand in the same branch (three Low Passes, two speed
#: choices) and one of each is enough to assert the seam.
def _answerable_cases():
    seen = set()
    for case in CASES:
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
        and *then* refuses is a different question, and today several
        of them mutate on the way to raising; see "What `answer`
        refuses, and what it does not" in
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

    def test_every_prompt_kind_has_a_model_answer(self) -> None:
        """
        **The claim Phase 6 was for**: a frontend that authorises a
        person and calls `apply` can drive every question this game
        asks. It is asserted as an equality rather than a subset so a
        new kind arriving without an answer fails here, once, rather
        than in whatever corner of a game reaches it.
        """
        self.assertEqual(set(driver.ANSWERS), set(PromptKind))

    def test_a_kind_with_no_model_answer_raises_rather_than_refuses(
        self,
    ) -> None:
        """
        A question this module cannot answer is a fact about the seam,
        not about the position -- so it is not a refusal, which a
        frontend would show to a coach as though they had done
        something wrong.

        Every kind has an answer today, which is what the test above
        says, so the missing row is staged here rather than found: the
        guard has to outlive the day the table was first complete.
        """
        fixture = next(
            case.build() for case in CASES if case.name == "skill test"
        )
        thinner = {
            kind: answer
            for kind, answer in driver.ANSWERS.items()
            if kind is not PromptKind.SKILL_TEST
        }
        with mock.patch.object(driver, "ANSWERS", thinner):
            self.assertFalse(driver.can_answer(PromptKind.SKILL_TEST))
            with self.assertRaises(LookupError):
                driver.apply(
                    ENGINE,
                    fixture.game,
                    fixture.match,
                    driver.Action(PromptKind.SKILL_TEST),
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
