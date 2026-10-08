"""
`codex.prompts`: the one reading of what a match waits on, and the
standing prompt beside it (docs/codex-bot.md, decision 8).

A fixture per `PromptKind` and per owed `FollowOnStep`, each asserting
that exactly one of `pending_prompt` and `owed_step` answers -- the
property that keeps a resume and a restart from disagreeing.
"""

from __future__ import annotations

import unittest

from codex.flow import FollowOnStep, turn
from codex.flow import driver
from codex.game import RuleRefusal
from codex.prompts import (
    Action,
    PromptKind,
    owed_step,
    pending_prompt,
    standing_prompts,
)

from codex_positions import begin, new_game, put


def _main():
    engine, game, match = new_game()
    begin(engine, game, match)
    return engine, game, match


def _end_turn(engine, game, match):
    driver.apply(engine, game, match, Action(PromptKind.MAIN_ACTION, "end_main"))
    return driver.apply(engine, game, match, Action(PromptKind.PATROL, arguments={"assignment": {}}))


def _tech_owed():
    """Seat 1 at the start of turn 3, owing the tech choice it was
    offered at the end of turn 1 -- unanswered."""
    engine, game, match = _main()
    _end_turn(engine, game, match)
    _end_turn(engine, game, match)
    return engine, game, match


def main_action():
    return _main()


def choose_defender():
    engine, game, match = _main()
    put(match, 1, "iron_man")
    driver.apply(engine, game, match, Action(PromptKind.MAIN_ACTION, "attack", {"attacker": "unit:1"}))
    return engine, game, match


def obliterate_choice():
    """Trojan Duck attacks into two equally low-tech units, so obliterate
    asks which one it takes."""
    engine, game, match = _main()
    put(match, 1, "trojan_duck")
    put(match, 2, "tenderfoot")
    put(match, 2, "older_brother")
    driver.apply(engine, game, match, Action(PromptKind.MAIN_ACTION, "attack", {"attacker": "unit:1"}))
    driver.apply(engine, game, match, Action(PromptKind.CHOOSE_DEFENDER, "", {"defender": "base"}))
    return engine, game, match


def sparkshot_target():
    """Revolver Ocelot attacks a patroller with a patroller on either
    side of it."""
    engine, game, match = _main()
    put(match, 1, "revolver_ocelot")
    put(match, 2, "tenderfoot", patrol="elite")
    put(match, 2, "iron_man", patrol="scavenger")
    put(match, 2, "older_brother", patrol="technician")
    driver.apply(engine, game, match, Action(PromptKind.MAIN_ACTION, "attack", {"attacker": "unit:1"}))
    driver.apply(engine, game, match, Action(PromptKind.CHOOSE_DEFENDER, "", {"defender": "unit:3"}))
    return engine, game, match


def overpower_target():
    """Harvest Reaper's excess over the squad leader, with two other
    patrollers that could have taken it."""
    engine, game, match = _main()
    put(match, 1, "harvest_reaper")
    put(match, 2, "tenderfoot", patrol="squad_leader")
    put(match, 2, "iron_man", patrol="elite")
    put(match, 2, "older_brother", patrol="scavenger")
    driver.apply(engine, game, match, Action(PromptKind.MAIN_ACTION, "attack", {"attacker": "unit:1"}))
    driver.apply(engine, game, match, Action(PromptKind.CHOOSE_DEFENDER, "", {"defender": "unit:2"}))
    return engine, game, match


def patrol():
    engine, game, match = _main()
    driver.apply(engine, game, match, Action(PromptKind.MAIN_ACTION, "end_main"))
    return engine, game, match


def tech_choice():
    return _tech_owed()


def tech_confirm():
    engine, game, match = _tech_owed()
    match.player(1).tech_choice = ["iron_man", "iron_man"]
    return engine, game, match


def target():
    """Spark, with a patroller on each side: which one it hits."""
    engine, game, match = _main()
    from codex_positions import hand, hero_in_play
    hero_in_play(match, 1)
    put(match, 1, "older_brother", patrol="elite")
    put(match, 2, "tenderfoot", patrol="elite")
    hand(match, 1, "spark")
    match.player(1).gold = 5
    driver.apply(engine, game, match, Action(PromptKind.MAIN_ACTION, "play", {"slug": "spark"}))
    return engine, game, match


def appel_stomp_top():
    """Appel Stomp has sidelined its patroller and drawn: where it goes.
    Finesse (seat 2) goes first, River at her maximum level."""
    engine, game, match = new_game(first=2)
    begin(engine, game, match)
    from codex_positions import hand, hero_in_play
    hero_in_play(match, 2, level=5)
    match.player(2).hero.max_level_since_turn_began = True
    put(match, 1, "tenderfoot", patrol="elite")
    hand(match, 2, "appel_stomp")
    match.player(2).gold = 5
    driver.apply(engine, game, match, Action(PromptKind.MAIN_ACTION, "play", {"slug": "appel_stomp"}))
    return engine, game, match


def upkeep_order():
    """Seat 2's upkeep with a Helpful Turtle and a Star-Crossed Starlet:
    the order changes what she is left with, so it is asked."""
    engine, game, match = _main()
    put(match, 2, "helpful_turtle")
    put(match, 2, "starcrossed_starlet", damage=1)
    _end_turn(engine, game, match)
    return engine, game, match


def game_over():
    engine, game, match = _main()
    match.winner = 2
    return engine, game, match


PROMPT_FIXTURES = {
    PromptKind.MAIN_ACTION: main_action,
    PromptKind.CHOOSE_DEFENDER: choose_defender,
    PromptKind.PATROL: patrol,
    PromptKind.TECH_CHOICE: tech_choice,
    PromptKind.TECH_CONFIRM: tech_confirm,
    PromptKind.OBLITERATE_CHOICE: obliterate_choice,
    PromptKind.SPARKSHOT_TARGET: sparkshot_target,
    PromptKind.OVERPOWER_TARGET: overpower_target,
    PromptKind.TARGET: target,
    PromptKind.APPEL_STOMP_TOP: appel_stomp_top,
    PromptKind.UPKEEP_ORDER: upkeep_order,
    PromptKind.GAME_OVER: game_over,
}


def begin_turn():
    return new_game()


def draw_phase():
    engine, game, match = _main()
    match.enter_phase("draw")
    return engine, game, match


def begin_tech():
    engine, game, match = _main()
    match.enter_phase("tech")
    return engine, game, match


OWED_FIXTURES = {
    FollowOnStep.BEGIN_TURN: begin_turn,
    FollowOnStep.DRAW_PHASE: draw_phase,
    FollowOnStep.BEGIN_TECH: begin_tech,
}


class OneReadingTests(unittest.TestCase):
    def test_every_kind_has_a_fixture(self) -> None:
        self.assertEqual(set(PROMPT_FIXTURES), set(PromptKind))
        self.assertEqual(set(OWED_FIXTURES), set(FollowOnStep))

    def test_each_prompt_is_asked_and_nothing_is_owed(self) -> None:
        for kind, fixture in PROMPT_FIXTURES.items():
            with self.subTest(kind=kind):
                engine, game, match = fixture()
                prompt = pending_prompt(engine, game, match)
                self.assertIsNotNone(prompt)
                self.assertIs(prompt.kind, kind)
                self.assertIsNone(owed_step(engine, game, match))
                self.assertIsNotNone(prompt.options)

    def test_each_owed_step_is_owed_and_nothing_is_asked(self) -> None:
        for step, fixture in OWED_FIXTURES.items():
            with self.subTest(step=step):
                engine, game, match = fixture()
                self.assertIsNone(pending_prompt(engine, game, match))
                self.assertIs(owed_step(engine, game, match).step, step)

    def test_who_is_asked(self) -> None:
        """The active player, but for a finished game's question."""
        for kind, fixture in PROMPT_FIXTURES.items():
            with self.subTest(kind=kind):
                engine, game, match = fixture()
                prompt = pending_prompt(engine, game, match)
                expected = None if kind is PromptKind.GAME_OVER else match.active
                self.assertEqual(prompt.asked_player, expected)

    def test_the_options_reach_the_wire(self) -> None:
        for kind, fixture in PROMPT_FIXTURES.items():
            with self.subTest(kind=kind):
                engine, game, match = fixture()
                data = pending_prompt(engine, game, match).to_dict()
                self.assertEqual(data["kind"], kind.value)


class StandingPromptTests(unittest.TestCase):
    def test_the_tech_choice_stands_through_the_opponents_turn(self) -> None:
        """Offered when the turn ends, answerable again and again until
        the owner's turn begins, each answer replacing the picks."""
        engine, game, match = _main()
        _end_turn(engine, game, match)
        self.assertEqual(match.active, 2)
        standing = standing_prompts(engine, match, game)
        self.assertEqual([p.kind for p in standing], [PromptKind.TECH_CHOICE])
        self.assertEqual(standing[0].asked_player, 1)
        self.assertEqual((standing[0].options.minimum, standing[0].options.maximum), (2, 2))
        self.assertIs(pending_prompt(engine, game, match).kind, PromptKind.MAIN_ACTION)

        pick = lambda *slugs: driver.apply(engine, game, match, Action(
            PromptKind.TECH_CHOICE, arguments={"player": 1, "picks": list(slugs)},
        ))
        self.assertNotIsInstance(pick("iron_man", "iron_man"), driver.Refusal)
        self.assertNotIsInstance(pick("iron_man", "revolver_ocelot"), driver.Refusal)
        self.assertEqual(match.player(1).tech_choice, ["iron_man", "revolver_ocelot"])
        self.assertEqual(standing_prompts(engine, match, game)[0].options.picks,
                         ("iron_man", "revolver_ocelot"))
        self.assertIsInstance(pick("iron_man"), driver.Refusal)
        self.assertIsInstance(pick("iron_man", "iron_man", "iron_man"), driver.Refusal)

        _end_turn(engine, game, match)
        self.assertEqual(standing_prompts(engine, match, game)[0].asked_player, 2)
        prompt = pending_prompt(engine, game, match)
        self.assertIs(prompt.kind, PromptKind.TECH_CONFIRM)
        self.assertEqual(prompt.options.picks, ("iron_man", "revolver_ocelot"))

    def test_the_turn_begins_only_once_the_picks_are_confirmed(self) -> None:
        engine, game, match = tech_confirm()
        with self.assertRaises(RuleRefusal):
            turn.begin_turn(engine, game, match)
        codex_before = dict(match.player(1).codex)
        driver.apply(engine, game, match, Action(PromptKind.TECH_CONFIRM, "confirm", {"player": 1}))
        self.assertIs(pending_prompt(engine, game, match).kind, PromptKind.MAIN_ACTION)
        player = match.player(1)
        self.assertEqual(player.discard[-2:], ["iron_man", "iron_man"])
        self.assertEqual(player.codex["iron_man"], codex_before["iron_man"] - 2)
        self.assertEqual((player.tech_choice, player.tech_owed, player.tech_confirmed),
                         (None, False, False))

    def test_change_reopens_the_picker(self) -> None:
        engine, game, match = tech_confirm()
        driver.apply(engine, game, match, Action(PromptKind.TECH_CONFIRM, "change", {"player": 1}))
        self.assertIs(pending_prompt(engine, game, match).kind, PromptKind.TECH_CHOICE)

    def test_a_tech_answer_names_its_seat(self) -> None:
        engine, game, match = _main()
        _end_turn(engine, game, match)
        refused = driver.apply(engine, game, match, Action(
            PromptKind.TECH_CHOICE, arguments={"player": 2, "picks": ["eggship", "eggship"]},
        ))
        self.assertIsInstance(refused, driver.Refusal)

    def test_ten_workers_may_tech_fewer(self) -> None:
        engine, game, match = _main()
        match.player(1).workers = 10
        _end_turn(engine, game, match)
        options = standing_prompts(engine, match, game)[0].options
        self.assertEqual((options.minimum, options.maximum), (0, 2))


if __name__ == "__main__":
    unittest.main()
