"""
A line that damages a building or the base says what it has left, and
a line whose damage destroys it says nothing of the kind -- the next
line says it is destroyed (the author, 2026-10-09;
docs/design/codex.md, "What the narration may say").
"""

from __future__ import annotations

import unittest

from codex.components import AddOnState
from codex.flow import combat
from codex_positions import begin, built, new_game, put


def fresh():
    engine, game, match = new_game(seed=7)
    begin(engine, game, match)
    return engine, game, match


class BuildingDamageLineTests(unittest.TestCase):
    def test_an_attack_on_the_base(self) -> None:
        engine, game, match = fresh()
        iron = put(match, 1, "iron_man").ref
        result = combat.declare_attack(engine, game, match, iron, "base")
        self.assertIn("{card:iron_man} deals 3 to {player:2}'s base; it has 17 left.", result.narration)

    def test_an_attack_on_a_tech_building_it_leaves_standing(self) -> None:
        engine, game, match = fresh()
        iron = put(match, 1, "iron_man").ref
        built(match, 2, "tech1")
        result = combat.declare_attack(engine, game, match, iron, "tech1")
        self.assertIn("{card:iron_man} deals 3 to {player:2}'s Tech I; it has 2 left.", result.narration)

    def test_a_destroyed_building_says_so_and_what_the_base_has_left(self) -> None:
        engine, game, match = fresh()
        iron = put(match, 1, "iron_man").ref
        built(match, 2, "tech1", hp=3)
        result = combat.declare_attack(engine, game, match, iron, "tech1")
        self.assertEqual(result.narration[1:], [
            "{card:iron_man} deals 3 to {player:2}'s Tech I.",
            "{player:2}'s Tech I building is destroyed, and deals 2 to their base; "
            "their base has 18 left.",
        ])

    def test_a_destroyed_add_on(self) -> None:
        engine, game, match = fresh()
        reaper = put(match, 1, "harvest_reaper").ref
        match.player(2).add_on = AddOnState(slug="surplus", hp=4, under_construction=False)
        result = combat.declare_attack(engine, game, match, reaper, "add_on")
        self.assertIn(
            "{player:2}'s {card:surplus} is destroyed, and deals 2 to their base; their base has 18 left.",
            result.narration,
        )

    def test_a_base_the_falling_building_destroys_has_no_count(self) -> None:
        engine, game, match = fresh()
        iron = put(match, 1, "iron_man").ref
        built(match, 2, "tech1", hp=3)
        match.player(2).base_hp = 2
        result = combat.declare_attack(engine, game, match, iron, "tech1")
        self.assertEqual(result.narration[2:], [
            "{player:2}'s Tech I building is destroyed, and deals 2 to their base.",
            "**{player:2}'s base is destroyed. {player:1} wins!**",
        ])

    def test_overpower_onto_the_base(self) -> None:
        engine, game, match = fresh()
        reaper = put(match, 1, "harvest_reaper").ref
        leader = put(match, 2, "tenderfoot", patrol="squad_leader").ref
        built(match, 2, "tech1")
        combat.declare_attack(engine, game, match, reaper, leader)
        result = combat.choose_overpower(engine, game, match, "base")
        self.assertIn("Overpower carries 4 over to {player:2}'s base; it has 16 left.", result.narration)


if __name__ == "__main__":
    unittest.main()
