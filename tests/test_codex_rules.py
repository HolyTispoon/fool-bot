"""
The basic game's rules as the vanilla engine plays them (docs/codex-bot.md,
"The game, in the terms the code will use"), each against the rulebook
page it comes from. Positions are staged by card slug
(`tests/codex_positions.py`).
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from codex.components import HERO, PATROL_SLOTS
from codex.engine import GOLD_CAP, RulesEngine
from codex.flow import StepResult, actions, combat, turn
from codex.flow import driver
from codex.game import RuleRefusal
from codex.prompts import Action, PromptKind, pending_prompt

from codex_positions import begin, built, hand, hero_in_play, new_game, put

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main_phase(seed: int = 7):
    """Seat 1's first main phase."""
    engine, game, match = new_game(seed)
    begin(engine, game, match)
    return engine, game, match


def to_their_turn(engine, game, match):
    """End seat 1's turn and begin seat 2's -- seat 2 owes no tech on
    its first turn, so its main phase follows at once."""
    driver.apply(engine, game, match, Action(PromptKind.MAIN_ACTION, "end_main"))
    driver.apply(engine, game, match, Action(PromptKind.PATROL, arguments={"assignment": {}}))
    return match


class DrawTests(unittest.TestCase):
    def test_the_draw_table(self) -> None:
        """Two more than were discarded, to at most five (UMR p. 5)."""
        engine = RulesEngine(seed=1)
        self.assertEqual(
            [engine.draw_count(n) for n in range(6)], [2, 3, 4, 5, 5, 5],
        )

    def test_the_draw_phase_discards_the_hand_and_draws(self) -> None:
        engine, game, match = main_phase()
        player = match.player(1)
        hand(match, 1, "spark", "bloom")
        before = len(player.deck)
        match.enter_phase("draw")
        turn.draw_phase(engine, game, match)
        self.assertEqual(len(player.hand), 4)
        self.assertEqual(player.discard[-2:], ["spark", "bloom"])
        self.assertEqual(len(player.deck), before - 4)

    def test_the_discard_is_shuffled_in_once_a_phase(self) -> None:
        """An empty deck takes the discard pile once a phase; a second
        empty deck in the same phase draws nothing more (UMR p. 5)."""
        engine, game, match = main_phase()
        player = match.player(1)
        player.hand, player.deck, player.discard = [], [], ["spark", "bloom"]
        result = StepResult()
        drawn = turn.draw_cards(engine, match, 1, 5, result)
        self.assertEqual(drawn, 2)
        self.assertEqual(len(result.drawn), 1)
        self.assertTrue(player.reshuffled_this_phase)
        player.discard = ["wither"]
        self.assertEqual(turn.draw_cards(engine, match, 1, 1, result), 0)
        match.enter_phase("patrol")
        self.assertEqual(turn.draw_cards(engine, match, 1, 1, result), 1)


class EconomyTests(unittest.TestCase):
    def test_gold_is_capped(self) -> None:
        """Gold is capped at 20 (UMR p. 5)."""
        engine, game, match = main_phase()
        player = match.player(2)
        player.gold = GOLD_CAP - 2
        player.workers = 5
        to_their_turn(engine, game, match)
        self.assertEqual(match.player(2).gold, GOLD_CAP)

    def test_a_worker_is_hired_once_a_turn_and_its_card_is_gone(self) -> None:
        """A gold and a card from the hand, trashed unseen, once a turn
        (UMR p. 6)."""
        engine, game, match = main_phase()
        player = match.player(1)
        hand(match, 1, "spark", "tenderfoot")
        everywhere = lambda: player.hand + player.deck + player.discard
        spark_count = everywhere().count("spark")
        run = driver.apply(engine, game, match,
                           Action(PromptKind.MAIN_ACTION, "hire", {"slug": "spark"}))
        self.assertNotIsInstance(run, driver.Refusal)
        self.assertEqual(player.workers, 5)
        self.assertEqual(player.gold, 3)
        self.assertEqual(everywhere().count("spark"), spark_count - 1)
        self.assertNotIn("Spark", " ".join(run.result.narration))
        again = driver.apply(engine, game, match,
                             Action(PromptKind.MAIN_ACTION, "hire", {"slug": "tenderfoot"}))
        self.assertIsInstance(again, driver.Refusal)


class HeroTests(unittest.TestCase):
    def test_bands_give_the_stats_and_a_new_band_heals(self) -> None:
        engine, game, match = main_phase()
        hero_in_play(match, 1, level=4, damage=2)
        hero = match.player(1).hero
        self.assertEqual(engine.hero_stats(hero), (2, 3))
        match.player(1).gold = 5
        actions.level_hero(engine, game, match, 1)
        self.assertEqual(hero.level, 5)
        self.assertEqual(engine.hero_stats(hero), (3, 4))
        self.assertEqual(hero.damage, 0)
        hero.damage = 1
        actions.level_hero(engine, game, match, 1)
        self.assertEqual(hero.damage, 1, "a level inside a band does not heal")
        river = match.player(2).hero
        river.level = 3
        self.assertEqual(engine.hero_stats(river), (2, 4))

    def test_a_hero_is_summoned_at_level_one_with_arrival_fatigue(self) -> None:
        engine, game, match = main_phase()
        match.player(1).gold = 2
        actions.summon_hero(engine, game, match)
        hero = match.player(1).hero
        self.assertTrue(hero.in_play)
        self.assertEqual((hero.level, match.player(1).gold), (1, 0))
        self.assertNotIn(HERO, engine.attackers(match))
        self.assertIn(HERO, engine.patrol_candidates(match))

    def test_summoning_runes_and_the_kills_two_levels(self) -> None:
        """A hero that dies goes to the command zone with two summoning
        runes, the other side's hero in play gains two levels, and a
        hero with runes cannot be summoned (UMR p. 6, 7)."""
        engine, game, match = main_phase()
        hero_in_play(match, 1, level=3)
        hero_in_play(match, 2, level=1, patrol="squad_leader")
        match.player(2).hero.armor = 0
        put(match, 1, "regularsized_rhinoceros")
        combat.declare_attack(engine, game, match, "unit:1", HERO)
        river = match.player(2).hero
        self.assertEqual((river.zone, river.summoning_runes, river.level), ("command", 2, 1))
        self.assertEqual(match.player(1).hero.level, 5)
        self.assertEqual(engine.hero_option(match.player(2)).action, None)
        to_their_turn(engine, game, match)
        self.assertEqual(river.summoning_runes, 1)


class BuildingTests(unittest.TestCase):
    def test_each_tech_buildings_cost_and_workers(self) -> None:
        """Tech I for 1 at six workers, Tech II for 4 at eight, Tech III
        for 5 at ten, each on the one below (UMR p. 8)."""
        engine, game, match = main_phase()
        player = match.player(1)
        player.gold = 20
        player.workers = 5
        self.assertIn("6 workers", engine.build_option(player, "tech1").why_not)
        player.workers = 10
        self.assertEqual(engine.build_option(player, "tech1").cost, 1)
        self.assertIn("Tech I", engine.build_option(player, "tech2").why_not)
        built(match, 1, "tech1")
        self.assertEqual(engine.build_option(player, "tech2").cost, 4)
        player.workers = 7
        self.assertIn("8 workers", engine.build_option(player, "tech2").why_not)
        player.workers = 10
        built(match, 1, "tech2")
        self.assertEqual(engine.build_option(player, "tech3").cost, 5)
        player.workers = 9
        self.assertIn("10 workers", engine.build_option(player, "tech3").why_not)

    def test_a_building_is_finished_at_the_end_of_the_turn(self) -> None:
        engine, game, match = main_phase()
        player = match.player(1)
        player.gold, player.workers = 5, 6
        hand(match, 1, "iron_man")
        actions.construct(engine, game, match, "tech1")
        building = player.buildings["tech1"]
        self.assertTrue(building.under_construction)
        self.assertIn("Tech I", engine.why_not_playable(player, "iron_man"))
        to_their_turn(engine, game, match)
        self.assertFalse(building.under_construction)
        self.assertTrue(engine.tech_building_active(player, 1))

    def test_a_destroyed_building_deals_two_and_is_rebuilt_for_nothing(self) -> None:
        engine, game, match = main_phase()
        built(match, 2, "tech1", hp=3)
        put(match, 1, "regularsized_rhinoceros")
        combat.declare_attack(engine, game, match, "unit:1", "tech1")
        other = match.player(2)
        self.assertTrue(other.buildings["tech1"].destroyed)
        self.assertEqual(other.base_hp, 18)
        other.workers = 6
        self.assertEqual(engine.build_option(other, "tech1").cost, 0)

    def test_an_add_on_takes_the_one_slot(self) -> None:
        engine, game, match = main_phase()
        player = match.player(1)
        player.gold = 10
        actions.construct(engine, game, match, "tower")
        self.assertEqual((player.add_on.slug, player.add_on.hp), ("tower", 4))
        self.assertIn("slot", engine.build_option(player, "surplus").why_not)


class CombatTests(unittest.TestCase):
    def test_the_three_attack_priorities(self) -> None:
        """The squad leader alone while there is one, then any patroller,
        then anything with HP (UMR p. 10)."""
        engine, game, match = main_phase()
        attacker = put(match, 1, "iron_man").ref
        idle = put(match, 2, "tenderfoot").ref
        leader = put(match, 2, "older_brother", patrol="squad_leader").ref
        elite = put(match, 2, "fruit_ninja", patrol="elite").ref
        self.assertEqual(engine.legal_defenders(match, attacker), (leader,))
        match.player(2).play[1].patrol_slot = None
        self.assertEqual(engine.legal_defenders(match, attacker), (elite,))
        match.player(2).play[2].patrol_slot = None
        built(match, 2, "tech1")
        self.assertEqual(
            set(engine.legal_defenders(match, attacker)),
            {idle, leader, elite, "tech1", "base"},
        )

    def test_damage_is_simultaneous(self) -> None:
        engine, game, match = main_phase()
        put(match, 1, "older_brother")
        put(match, 2, "fruit_ninja")
        combat.declare_attack(engine, game, match, "unit:1", "unit:2")
        self.assertEqual(match.player(1).play, [])
        self.assertEqual(match.player(2).play, [])
        self.assertIn("older_brother", match.player(1).discard)
        self.assertIn("fruit_ninja", match.player(2).discard)

    def test_an_attacker_exhausts_and_a_new_unit_is_fatigued(self) -> None:
        engine, game, match = main_phase()
        put(match, 1, "iron_man")
        fresh = put(match, 1, "tenderfoot", arrived=True).ref
        self.assertNotIn(fresh, engine.attackers(match))
        self.assertIn(fresh, engine.patrol_candidates(match))
        combat.declare_attack(engine, game, match, "unit:1", "base")
        self.assertNotIn("unit:1", engine.attackers(match))
        self.assertNotIn("unit:1", engine.patrol_candidates(match),
                         "an exhausted card cannot patrol")
        self.assertEqual(match.player(2).base_hp, 17)

    def test_a_base_at_zero_ends_the_game(self) -> None:
        engine, game, match = main_phase()
        match.player(2).base_hp = 3
        put(match, 1, "iron_man")
        combat.declare_attack(engine, game, match, "unit:1", "base")
        self.assertEqual(match.winner, 1)
        self.assertIs(pending_prompt(engine, game, match).kind, PromptKind.GAME_OVER)


class PatrolSlotTests(unittest.TestCase):
    def test_the_squad_leaders_armour(self) -> None:
        """Armour 1, used up by the first damage of the turn and set again
        when a turn begins (UMR p. 10)."""
        engine, game, match = main_phase()
        leader = put(match, 2, "regularsized_rhinoceros", patrol="squad_leader")
        leader.armor = 1
        put(match, 1, "iron_man")
        put(match, 1, "tenderfoot")
        combat.declare_attack(engine, game, match, "unit:3", leader.ref)
        self.assertEqual((leader.damage, leader.armor), (0, 0))
        combat.declare_attack(engine, game, match, "unit:2", leader.ref)
        self.assertEqual(leader.damage, 3)
        match.active = 2
        match.enter_phase("ready")
        match.active = 1
        turn.begin_turn(engine, game, match)
        self.assertEqual(leader.armor, 1)

    def test_the_elite_hits_harder(self) -> None:
        engine, game, match = main_phase()
        put(match, 1, "regularsized_rhinoceros")
        elite = put(match, 2, "older_brother", patrol="elite")
        self.assertEqual(engine.attack_value(match, 2, elite.ref), 3)
        combat.declare_attack(engine, game, match, "unit:1", elite.ref)
        self.assertEqual(match.player(1).play[0].damage, 3)

    def test_the_scavenger_gives_a_gold_when_it_dies(self) -> None:
        engine, game, match = main_phase()
        put(match, 1, "regularsized_rhinoceros")
        scavenger = put(match, 2, "tenderfoot", patrol="scavenger")
        match.player(2).gold = 0
        combat.declare_attack(engine, game, match, "unit:1", scavenger.ref)
        self.assertEqual(match.player(2).gold, 1)

    def test_the_technician_draws_a_card_when_it_dies(self) -> None:
        engine, game, match = main_phase()
        put(match, 1, "regularsized_rhinoceros")
        technician = put(match, 2, "tenderfoot", patrol="technician")
        before = len(match.player(2).hand)
        combat.declare_attack(engine, game, match, "unit:1", technician.ref)
        self.assertEqual(len(match.player(2).hand), before + 1)

    def test_lock_patrol_fills_the_slots(self) -> None:
        engine, game, match = main_phase()
        unit = put(match, 1, "tenderfoot")
        hero_in_play(match, 1)
        driver.apply(engine, game, match, Action(PromptKind.MAIN_ACTION, "end_main"))
        refused = driver.apply(engine, game, match, Action(
            PromptKind.PATROL, arguments={"assignment": {"squad_leader": unit.ref, "elite": unit.ref}},
        ))
        self.assertIsInstance(refused, driver.Refusal)
        driver.apply(engine, game, match, Action(
            PromptKind.PATROL, arguments={"assignment": {"squad_leader": unit.ref, "lookout": HERO}},
        ))
        self.assertEqual(match.player(1).patrollers(), {"squad_leader": unit.ref, "lookout": HERO})
        self.assertEqual(set(PATROL_SLOTS) >= set(match.player(1).patrollers()), True)


class CardTests(unittest.TestCase):
    def test_a_spell_needs_a_hero_and_goes_to_the_discard(self) -> None:
        """A spell needs a hero in play (UMR p. 7); in this step it is paid
        and discarded and does nothing, since its text is unimplemented."""
        engine, game, match = main_phase()
        player = match.player(1)
        hand(match, 1, "spark")
        player.gold = 5
        self.assertIn("hero", engine.why_not_playable(player, "spark"))
        hero_in_play(match, 1)
        result = actions.play_card(engine, game, match, "spark")
        self.assertEqual(player.discard[-1], "spark")
        self.assertEqual(player.gold, 4)
        self.assertIn(actions.NOT_PLAYED_YET, result.narration[0])

    def test_an_ultimate_needs_the_hero_at_maximum_level_since_the_turn_began(self) -> None:
        engine, game, match = main_phase()
        player = match.player(1)
        player.gold = 20
        hand(match, 1, "final_smash")
        hero_in_play(match, 1, level=8)
        self.assertIn("maximum level", engine.why_not_playable(player, "final_smash"))
        player.hero.max_level_since_turn_began = True
        self.assertEqual(engine.why_not_playable(player, "final_smash"), "")

    def test_a_tech_card_needs_its_building(self) -> None:
        engine, game, match = main_phase()
        player = match.player(1)
        player.gold = 20
        hand(match, 1, "eggship")
        self.assertIn("Tech II", engine.why_not_playable(player, "eggship"))
        built(match, 1, "tech2")
        self.assertEqual(engine.why_not_playable(player, "eggship"), "")

    def test_refusals_cite_the_page(self) -> None:
        engine, game, match = main_phase()
        hand(match, 1, "eggship")
        with self.assertRaises(RuleRefusal) as refused:
            actions.play_card(engine, game, match, "eggship")
        self.assertEqual(refused.exception.cite, "UMR p. 7")


class RandomnessTests(unittest.TestCase):
    def test_only_the_engine_reaches_for_random(self) -> None:
        """Every draw is `engine.rng` (docs/codex-bot.md, decision 9):
        the engine imports the `Random` class for it, and nothing under
        `codex/` imports the module or its functions."""
        offenders = []
        for path in sorted((PROJECT_ROOT / "codex").rglob("*.py")):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import) and any(a.name == "random" for a in node.names):
                    offenders.append(f"{path.name} imports random")
                if isinstance(node, ast.ImportFrom) and node.module == "random":
                    names = [alias.name for alias in node.names]
                    if path.name != "engine.py" or names != ["Random"]:
                        offenders.append(f"{path.name} imports {names} from random")
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
