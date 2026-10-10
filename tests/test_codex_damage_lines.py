"""
A line that damages a building or the base says where it now stands
out of its most -- ", now at 17/20" -- and a line whose damage destroys
it says nothing of the kind -- the next line says it is destroyed (the
author, 2026-10-09 and 2026-10-10;
docs/design/codex.md, "What the narration may say").
"""

from __future__ import annotations

import unittest

from codex.components import AddOnState
from codex.effects import Part
from codex.flow import combat, resolve, turn
from codex.flow.result import StepResult
from codex_positions import begin, built, hero_in_play, new_game, put


def fresh():
    engine, game, match = new_game(seed=7)
    begin(engine, game, match)
    return engine, game, match


class BuildingDamageLineTests(unittest.TestCase):
    def test_an_attack_on_the_base(self) -> None:
        engine, game, match = fresh()
        iron = put(match, 1, "iron_man").ref
        result = combat.declare_attack(engine, game, match, iron, "base")
        self.assertIn("{card:iron_man} deals 3 to {player:2}'s base, now at 17/20.", result.narration)

    def test_an_attack_on_a_tech_building_it_leaves_standing(self) -> None:
        engine, game, match = fresh()
        iron = put(match, 1, "iron_man").ref
        built(match, 2, "tech1")
        result = combat.declare_attack(engine, game, match, iron, "tech1")
        self.assertIn("{card:iron_man} deals 3 to {player:2}'s Tech I building, now at 2/5.", result.narration)

    def test_a_destroyed_building_says_so_and_what_the_base_has_left(self) -> None:
        engine, game, match = fresh()
        iron = put(match, 1, "iron_man").ref
        built(match, 2, "tech1", hp=3)
        result = combat.declare_attack(engine, game, match, iron, "tech1")
        self.assertEqual(result.narration[1:], [
            "{card:iron_man} deals 3 to {player:2}'s Tech I building.",
            "{player:2}'s Tech I building is destroyed, and deals 2 to their base, now at 18/20.",
        ])

    def test_a_destroyed_add_on(self) -> None:
        engine, game, match = fresh()
        reaper = put(match, 1, "harvest_reaper").ref
        match.player(2).add_on = AddOnState(slug="surplus", hp=4, under_construction=False)
        result = combat.declare_attack(engine, game, match, reaper, "add_on")
        self.assertEqual(result.narration[:2], [
            "{card:harvest_reaper} attacks {player:2}'s {card:surplus}.",
            "{card:harvest_reaper} deals 6 to {player:2}'s {card:surplus}.",
        ])
        self.assertIn(
            "{player:2}'s {card:surplus} is destroyed, and deals 2 to their base, now at 18/20.",
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

    def test_a_building_card(self) -> None:
        engine, game, match = fresh()
        iron = put(match, 1, "iron_man").ref
        elm = put(match, 2, "blooming_elm").ref  # 4 HP
        result = combat.declare_attack(engine, game, match, iron, elm)
        self.assertIn("{card:iron_man} deals 3, now at 1/4.", result.narration)

    def test_a_building_card_the_damage_destroys(self) -> None:
        engine, game, match = fresh()
        iron = put(match, 1, "iron_man").ref
        tree = put(match, 2, "verdant_tree").ref  # 3 HP
        result = combat.declare_attack(engine, game, match, iron, tree)
        self.assertIn("{card:iron_man} deals 3.", result.narration)

    def test_overpower_onto_the_base(self) -> None:
        engine, game, match = fresh()
        reaper = put(match, 1, "harvest_reaper").ref
        leader = put(match, 2, "tenderfoot", patrol="squad_leader").ref
        built(match, 2, "tech1")
        combat.declare_attack(engine, game, match, reaper, leader)
        result = combat.choose_overpower(engine, game, match, "base")
        self.assertIn("Overpower carries 4 over to {player:2}'s base, now at 16/20.", result.narration)


class HealingLineTests(unittest.TestCase):
    """Healing and repair name what they mend and where it now stands,
    the healing its source too (the author, 2026-10-10)."""

    def test_healing_names_its_source_and_each_card_it_heals(self) -> None:
        engine, game, match = fresh()
        put(match, 1, "helpful_turtle")
        hero_in_play(match, 1, level=5)
        match.player(1).heroes_in_play[0].damage = 1
        put(match, 1, "iron_man", damage=2)
        put(match, 1, "tenderfoot")
        result = StepResult()
        turn._upkeep_effect(engine, match, 1, "healing", result)
        self.assertEqual(result.narration, [
            "{card:helpful_turtle}'s healing 1 heals {player:1}'s {card:iron_man} 1, now at 3/4 "
            "and {hero:troq_bashar} 1, now at 4/4.",
        ])

    def test_a_repair(self) -> None:
        engine, game, match = fresh()
        built(match, 2, "tech1", hp=3)
        result = StepResult()
        resolve._repair(engine, match, {"by": "{card:brick_thief}"},
                        Part("repair", "other_building", 1, "repair 1 damage"), (2, "tech1"), result)
        self.assertEqual(result.narration, [
            "{card:brick_thief} repairs 1 damage on {player:2}'s Tech I building, now at 4/5.",
        ])


if __name__ == "__main__":
    unittest.main()
