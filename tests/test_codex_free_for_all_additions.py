"""
The free-for-all's three additions (docs/codex-multiplayer.md, step 3),
each staged by slug and played through `driver.apply`: repairing the
base, the free gold for a kill, and lending a patroller.

The rules are Rulebook p. 14, with p. 11 for a dead hero's levels and the
author's answers of 2026-10-14 to questions 18 and 19.
"""

from __future__ import annotations

import unittest

from codex import history
from codex.engine import RulesEngine
from codex.flow import driver
from codex.prompts import Action, PromptKind, pending_prompt

from test_codex_free_for_all import THREE, apply, free_for_all, said
from codex_positions import new_game, begin


def refused_by(engine, game, match, action):
    refusal = driver.apply(engine, game, match, action)
    assert isinstance(refusal, driver.Refusal), refusal
    return refusal


def main_options(engine, game, match):
    return pending_prompt(engine, game, match).options


class RepairTests(unittest.TestCase):
    """Repairing the base: 3 gold for 1 damage, any number of times a
    turn, in a free-for-all alone (Rulebook p. 14)."""

    def test_a_free_for_all_lists_the_repair_with_its_cost_and_why_not(self) -> None:
        engine, game, match = free_for_all()
        option = main_options(engine, game, match).repair
        self.assertFalse(option.allowed)
        self.assertEqual((option.cost, option.why_not), (3, "the base is undamaged"))
        match.set_base(1, 15)
        match.active_player.gold = 2
        self.assertEqual(main_options(engine, game, match).repair.why_not, "not enough gold")
        match.active_player.gold = 3
        self.assertTrue(main_options(engine, game, match).repair.allowed)

    def test_a_repair_costs_three_gold_for_one_hp_as_often_as_the_gold_goes(self) -> None:
        engine, game, match = free_for_all()
        match.set_base(1, 15)
        match.active_player.gold = 7
        first = said(apply(engine, game, match, Action(PromptKind.MAIN_ACTION, "repair")))
        self.assertEqual(first, "{player:1} repairs the base: 16 HP.")
        apply(engine, game, match, Action(PromptKind.MAIN_ACTION, "repair"))
        self.assertEqual((match.base_of(1), match.active_player.gold), (17, 1))
        self.assertFalse(main_options(engine, game, match).repair.allowed)

    def test_a_repair_stops_at_twenty(self) -> None:
        engine, game, match = free_for_all()
        match.set_base(1, 19)
        match.active_player.gold = 9
        apply(engine, game, match, Action(PromptKind.MAIN_ACTION, "repair"))
        refusal = refused_by(engine, game, match, Action(PromptKind.MAIN_ACTION, "repair"))
        self.assertIn("undamaged", refusal.reason)
        self.assertEqual(refusal.cite, "Rulebook p. 14")
        self.assertEqual(match.active_player.gold, 6)

    def test_a_repair_is_journaled_and_replays(self) -> None:
        engine, game, match = free_for_all()
        match.set_base(1, 15)
        match.active_player.gold = 3
        start = history.position(match)
        apply(engine, game, match, Action(PromptKind.MAIN_ACTION, "repair"))
        self.assertEqual(match.journal[-1]["action"]["choice"], "repair")
        replayed = history.replay(RulesEngine(seed=3), game, start, match.journal)
        self.assertEqual(replayed.base_of(1), 16)

    def test_a_duel_never_lists_it_and_refuses_it(self) -> None:
        engine, game, match = new_game()
        begin(engine, game, match)
        self.assertIsNone(main_options(engine, game, match).repair)
        self.assertNotIn("repair", main_options(engine, game, match).to_dict())
        match.set_base(1, 15)
        match.active_player.gold = 9
        refusal = refused_by(engine, game, match, Action(PromptKind.MAIN_ACTION, "repair"))
        self.assertIn("free-for-all", refusal.reason)
        self.assertEqual(match.base_of(1), 15)


if __name__ == "__main__":
    unittest.main()
