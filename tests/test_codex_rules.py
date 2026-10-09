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

from codex.components import PATROL_SLOTS
from codex.engine import GOLD_CAP, RulesEngine
from codex.flow import StepResult, actions, board, combat, turn
from codex.flow import driver
from codex.game import RuleRefusal
from codex.prompts import Action, PromptKind, pending_prompt

from codex_positions import RIVER, TROQ, begin, built, hand, hero, hero_in_play, new_game, put

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
    return driver.apply(engine, game, match, Action(PromptKind.PATROL, arguments={"assignment": {}}))


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
        run = to_their_turn(engine, game, match)
        self.assertEqual(match.player(2).gold, GOLD_CAP)
        said = " ".join(run.result.narration)
        self.assertIn("collects {gold:2} from 5 workers and hits the gold cap: {gold:20}.", said)

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
        self.assertNotIn(TROQ, engine.attackers(match))
        self.assertIn(TROQ, engine.patrol_candidates(match))

    def test_summoning_runes_and_the_kills_two_levels(self) -> None:
        """A hero that dies goes to the command zone with two summoning
        runes, the other side's hero in play gains two levels, and a
        hero with runes cannot be summoned (UMR p. 6, 7)."""
        engine, game, match = main_phase()
        hero_in_play(match, 1, level=3)
        hero_in_play(match, 2, level=1, patrol="squad_leader")
        match.player(2).hero.armor = 0
        put(match, 1, "regularsized_rhinoceros")
        combat.declare_attack(engine, game, match, "unit:1", RIVER)
        river = match.player(2).hero
        self.assertEqual((river.zone, river.summoning_runes, river.level), ("command", 2, 1))
        self.assertEqual(match.player(1).hero.level, 5)
        option = engine.hero_option(match.player(2))
        self.assertFalse(option.allowed)
        self.assertIn("2 summoning runes", option.why_not)
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
        """A new add-on replaces the one in the slot, which is destroyed
        and deals its 2 to the base (the author, 2026-10-08)."""
        engine, game, match = main_phase()
        player = match.player(1)
        player.gold = 10
        actions.construct(engine, game, match, "tower")
        self.assertEqual((player.add_on.slug, player.add_on.hp), ("tower", 4))
        self.assertIn("already built", engine.build_option(player, "tower").why_not)
        result = actions.construct(engine, game, match, "surplus")
        self.assertEqual(player.add_on.slug, "surplus")
        self.assertEqual(player.base_hp, 18)
        self.assertIn("replaces", " ".join(result.narration))


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
    def test_the_squad_leaders_armor(self) -> None:
        """Armor 1, used up by the first damage of the turn and set again
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
            PromptKind.PATROL, arguments={"assignment": {"squad_leader": unit.ref, "lookout": TROQ}},
        ))
        self.assertEqual(match.player(1).patrollers(), {"squad_leader": unit.ref, "lookout": TROQ})
        self.assertEqual(set(PATROL_SLOTS) >= set(match.player(1).patrollers()), True)


class CardTests(unittest.TestCase):
    def test_a_spell_needs_a_hero_and_goes_to_the_discard(self) -> None:
        """A spell needs a hero in play (UMR p. 7); it is paid, does what
        it says, and goes to the discard pile. Since step 6 it plays its
        text, so nothing says it is not played."""
        engine, game, match = main_phase()
        player = match.player(1)
        hand(match, 1, "spark")
        player.gold = 5
        put(match, 2, "older_brother", patrol="elite")
        self.assertIn("hero", engine.why_not_playable(player, "spark"))
        hero_in_play(match, 1)
        result = actions.play_card(engine, game, match, "spark")
        self.assertEqual(player.discard[-1], "spark")
        self.assertEqual(player.gold, 4)
        self.assertNotIn(actions.NOT_PLAYED_YET, " ".join(result.narration))

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


class StandardGameHeroTests(unittest.TestCase):
    """The standard game's heroes (UMR pp. 6-7, 10): three a side, the
    hero limit, the spells' heroes and colours, and who gains a kill's
    levels."""

    RED = ("fire", "anarchy", "blood")
    GREEN = ("feral", "growth", "balance")

    def standard(self, teams=None):
        engine, game, match = new_game(teams=teams or (self.RED, self.GREEN))
        begin(engine, game, match)
        match.player(1).gold = 20
        return engine, game, match

    def summon(self, engine, game, match, slug):
        return driver.apply(engine, game, match, Action(
            PromptKind.MAIN_ACTION, "summon", {"hero": slug},
        ))

    def test_a_standard_match_deals_three_heroes_and_three_codexes(self) -> None:
        engine, game, match = self.standard()
        player = match.player(1)
        self.assertEqual(player.specs, self.RED)
        self.assertEqual([hero.slug for hero in player.heroes],
                         ["jaina_stormborne", "captain_zane", "drakk_ramhorn"])
        self.assertEqual(player.deck_color, "red")
        self.assertEqual(sum(player.codex.values()), 72)
        cards = engine.catalog
        dealt = sorted([*player.hand, *player.deck])
        self.assertEqual(dealt, sorted(cards.starting_deck("red")))

    def test_a_summon_past_the_hero_limit_is_refused(self) -> None:
        """"You begin the game with a hero limit of 1, which means that you
        can't summon a hero while you have a hero in play" (UMR p. 6)."""
        engine, game, match = self.standard()
        self.assertFalse(isinstance(self.summon(engine, game, match, "jaina_stormborne"), driver.Refusal))
        refused = self.summon(engine, game, match, "captain_zane")
        self.assertIsInstance(refused, driver.Refusal)
        self.assertEqual(refused.cite, "UMR p. 6")
        self.assertIn("hero limit is 1", refused.reason)
        options = pending_prompt(engine, game, match).options
        self.assertEqual([hero.allowed for hero in options.heroes], [True, False, False])
        self.assertEqual(options.heroes[0].action, "level")

    def test_the_hero_limit_rises_with_tech_ii_and_tech_iii(self) -> None:
        """Tech I 1, Tech II 2, Tech III 3 (UMR p. 8's table)."""
        engine, game, match = self.standard()
        built(match, 1, "tech1")
        self.summon(engine, game, match, "jaina_stormborne")
        self.assertIsInstance(self.summon(engine, game, match, "captain_zane"), driver.Refusal)
        built(match, 1, "tech2")
        self.assertNotIsInstance(self.summon(engine, game, match, "captain_zane"), driver.Refusal)
        self.assertIsInstance(self.summon(engine, game, match, "drakk_ramhorn"), driver.Refusal)
        built(match, 1, "tech3")
        self.assertNotIsInstance(self.summon(engine, game, match, "drakk_ramhorn"), driver.Refusal)
        self.assertEqual(len(match.player(1).heroes_in_play), 3)

    def test_a_dead_hero_is_replaced_at_once(self) -> None:
        """"When one of your heroes dies, you can immediately summon a
        different hero to replace it" (UMR p. 6): a hero in the command
        zone does not count against the limit."""
        engine, game, match = self.standard()
        self.summon(engine, game, match, "jaina_stormborne")
        jaina = match.player(1).hero_of("jaina_stormborne")
        jaina.arrived_this_turn = False
        board.destroy(engine, match, [(1, hero(match, 1, "jaina_stormborne"))], StepResult())
        self.assertEqual(jaina.zone, "command")
        self.assertNotIsInstance(self.summon(engine, game, match, "captain_zane"), driver.Refusal)
        option = engine.hero_option(match.player(1), jaina)
        self.assertIn("summoning runes", option.why_not)

    def test_losing_a_building_removes_nobody(self) -> None:
        """"You're not forced to destroy a hero if you have two heroes in
        play when an opponent destroys your tech II building" (UMR p. 6)."""
        engine, game, match = self.standard()
        built(match, 1, "tech1")
        built(match, 1, "tech2", hp=1)
        self.summon(engine, game, match, "jaina_stormborne")
        self.summon(engine, game, match, "captain_zane")
        board.damage_building(match, 1, "tech2", 1, StepResult())
        self.assertEqual(len(match.player(1).heroes_in_play), 2)
        self.assertEqual(engine.hero_limit(match.player(1)), 1)

    def test_a_starting_spell_costs_one_more_without_a_hero_of_its_colour(self) -> None:
        """"A starting spell costs +1 gold when played by a hero of the
        wrong color" (UMR p. 4); "neutral starting spells never cost extra
        gold to play"."""
        engine, game, match = self.standard(teams=(("feral", "fire", "bashing"), self.GREEN))
        player = match.player(1)
        hero_in_play(match, 1, slug="calamandra_moss")
        self.assertEqual(engine.effective_cost(player, "scorch"), 3 + 1)
        self.assertEqual(engine.effective_cost(player, "rampant_growth"), 2)
        self.assertEqual(engine.effective_cost(player, "spark"), 1)
        self.assertEqual(engine.caster(player, "scorch").slug, "calamandra_moss")
        hero_in_play(match, 1, slug="jaina_stormborne")
        self.assertEqual(engine.effective_cost(player, "scorch"), 3)
        self.assertEqual(engine.caster(player, "scorch").slug, "jaina_stormborne")

    def test_a_spec_spell_needs_its_heros_and_an_ultimate_its_max_level(self) -> None:
        """"To play a spec spell, you must have that spec's hero in play"
        and an ultimate "that hero must have been in play at maximum level
        at the beginning of your turn" (UMR p. 7) -- the spec's own hero,
        whatever else is in play."""
        engine, game, match = self.standard()
        player = match.player(1)
        fire = next(card.slug for card in engine.catalog.by_spec("fire")
                    if card.is_spell and "Ultimate" not in card.type)
        ultimate = next(card.slug for card in engine.catalog.by_spec("fire")
                        if "Ultimate" in card.type)
        hero_in_play(match, 1, slug="captain_zane", level=6)
        player.hero_of("captain_zane").max_level_since_turn_began = True
        self.assertIn("Fire hero", engine.why_not_playable(player, fire))
        self.assertIn("Fire hero", engine.why_not_playable(player, ultimate))
        hero_in_play(match, 1, slug="jaina_stormborne")
        self.assertEqual(engine.why_not_playable(player, fire), "")
        self.assertIn("maximum level", engine.why_not_playable(player, ultimate))
        player.hero_of("jaina_stormborne").max_level_since_turn_began = True
        self.assertEqual(engine.why_not_playable(player, ultimate), "")

    def test_the_kills_levels_are_asked_where_two_heroes_could_gain_them(self) -> None:
        """"If you have multiple heroes in play, choose one hero to gain
        the levels from destroying an opponent's hero" (UMR p. 10) -- the
        active player chooses, before anything after the kill resolves."""
        engine, game, match = self.standard()
        built(match, 1, "tech1")
        built(match, 1, "tech2")
        hero_in_play(match, 1, slug="jaina_stormborne")
        hero_in_play(match, 1, slug="captain_zane")
        hero_in_play(match, 2, slug="calamandra_moss", patrol="squad_leader")
        match.player(2).hero.armor = 0
        rhino = put(match, 1, "regularsized_rhinoceros")
        driver.apply(engine, game, match, Action(PromptKind.MAIN_ACTION, "attack", {"attacker": rhino.ref}))
        driver.apply(engine, game, match, Action(
            PromptKind.CHOOSE_DEFENDER, arguments={"defender": hero(match, 2, "calamandra_moss")},
        ))
        prompt = pending_prompt(engine, game, match)
        self.assertIs(prompt.kind, PromptKind.LEVEL_GAIN)
        self.assertEqual(prompt.asked_player, 1)
        self.assertEqual(prompt.options.heroes,
                         (hero(match, 1, "jaina_stormborne"), hero(match, 1, "captain_zane")))
        refused = driver.apply(engine, game, match, Action(
            PromptKind.LEVEL_GAIN, arguments={"hero": hero(match, 1, "drakk_ramhorn")},
        ))
        self.assertIsInstance(refused, driver.Refusal)
        driver.apply(engine, game, match, Action(
            PromptKind.LEVEL_GAIN, arguments={"hero": hero(match, 1, "captain_zane")},
        ))
        self.assertEqual(match.player(1).hero_of("captain_zane").level, 3)
        self.assertEqual(match.player(1).hero_of("jaina_stormborne").level, 1)
        self.assertIs(pending_prompt(engine, game, match).kind, PromptKind.MAIN_ACTION)

    def test_the_kills_levels_are_not_asked_with_one_hero(self) -> None:
        engine, game, match = self.standard()
        hero_in_play(match, 1, slug="captain_zane")
        hero_in_play(match, 2, slug="calamandra_moss", patrol="squad_leader")
        match.player(2).hero.armor = 0
        rhino = put(match, 1, "regularsized_rhinoceros")
        driver.apply(engine, game, match, Action(PromptKind.MAIN_ACTION, "attack", {"attacker": rhino.ref}))
        driver.apply(engine, game, match, Action(
            PromptKind.CHOOSE_DEFENDER, arguments={"defender": hero(match, 2, "calamandra_moss")},
        ))
        self.assertIs(pending_prompt(engine, game, match).kind, PromptKind.MAIN_ACTION)
        self.assertEqual(match.player(1).hero_of("captain_zane").level, 3)

    def test_one_summoning_rune_comes_off_each_hero_at_upkeep(self) -> None:
        """"Remove one summoning rune from each of your heroes" (UMR p. 5)."""
        engine, game, match = self.standard()
        for slug in ("feral", "growth"):
            match.player(2).heroes[("feral", "growth").index(slug)].summoning_runes = 2
        to_their_turn(engine, game, match)
        self.assertEqual([hero.summoning_runes for hero in match.player(2).heroes], [1, 1, 0])


class StandardGameBuildingTests(unittest.TestCase):
    """The standard game's buildings (UMR pp. 4, 8-9): the spec chosen at
    Tech II, the tech lab's, the heroes' hall, and a multicolour team's
    first construction."""

    RED = ("fire", "anarchy", "blood")
    GREEN = ("feral", "growth", "balance")

    def standard(self, teams=None):
        engine, game, match = new_game(teams=teams or (self.RED, self.GREEN))
        begin(engine, game, match)
        player = match.player(1)
        player.gold, player.workers = 20, 10
        return engine, game, match

    def build(self, engine, game, match, building, **arguments):
        return driver.apply(engine, game, match, Action(
            PromptKind.MAIN_ACTION, "build", {"building": building, **arguments},
        ))

    def test_tech_ii_chooses_a_spec_among_the_heroes(self) -> None:
        """"In a standard game, when you construct your tech II building,
        you must choose a spec ... that matches one of your heroes'
        specs" (UMR p. 8)."""
        engine, game, match = self.standard()
        built(match, 1, "tech1")
        option = engine.build_option(match.player(1), "tech2")
        self.assertEqual(option.specs, self.RED)
        missing = self.build(engine, game, match, "tech2")
        self.assertIsInstance(missing, driver.Refusal)
        self.assertEqual(missing.cite, "UMR p. 8")
        foreign = self.build(engine, game, match, "tech2", spec="feral")
        self.assertIsInstance(foreign, driver.Refusal)
        self.assertEqual(foreign.cite, "UMR p. 8")
        self.assertNotIsInstance(self.build(engine, game, match, "tech2", spec="anarchy"), driver.Refusal)
        self.assertEqual(match.player(1).tech2_spec, "anarchy")

    def test_the_tech_ii_spec_is_kept_through_a_rebuild(self) -> None:
        """"You don't get to change this spec when your tech II building is
        destroyed and reconstructed" (UMR p. 8)."""
        engine, game, match = self.standard()
        built(match, 1, "tech1")
        self.build(engine, game, match, "tech2", spec="fire")
        board.damage_building(match, 1, "tech2", 5, StepResult())
        self.assertTrue(match.player(1).buildings["tech2"].destroyed)
        option = engine.build_option(match.player(1), "tech2")
        self.assertEqual((option.cost, option.specs), (0, ()))
        self.assertIsInstance(self.build(engine, game, match, "tech2", spec="blood"), driver.Refusal)
        self.assertNotIsInstance(self.build(engine, game, match, "tech2"), driver.Refusal)
        self.assertEqual(match.player(1).tech2_spec, "fire")

    def test_a_tech_ii_card_needs_its_spec_and_the_lab_unlocks_another(self) -> None:
        """"You can only play tech II and tech III cards of your chosen
        spec" (UMR p. 8); a tech lab's spec too, once it is finished --
        "You can't immediately play cards of the new tech when you
        construct this" (p. 9)."""
        engine, game, match = self.standard()
        player = match.player(1)
        built(match, 1, "tech1")
        built(match, 1, "tech2")
        player.tech2_spec = "fire"
        fire = next(card.slug for card in engine.catalog.by_spec("fire")
                    if card.is_unit and card.tech_level == 2)
        blood = next(card.slug for card in engine.catalog.by_spec("blood")
                     if card.is_unit and card.tech_level == 2)
        self.assertEqual(engine.why_not_playable(player, fire), "")
        self.assertIn("Fire", engine.why_not_playable(player, blood))
        self.assertEqual(engine.build_option(player, "tech_lab").specs, ("anarchy", "blood"))
        self.assertIsInstance(self.build(engine, game, match, "tech_lab", spec="fire"), driver.Refusal)
        self.build(engine, game, match, "tech_lab", spec="blood")
        self.assertEqual(player.add_on.spec, "blood")
        self.assertIn("tech lab", engine.why_not_playable(player, blood), "not until it is finished")
        player.add_on.under_construction = False
        self.assertEqual(engine.why_not_playable(player, blood), "")

    def test_a_destroyed_lab_loses_its_spec(self) -> None:
        """"When this is destroyed, you lose its bonus spec. If you
        reconstruct the tech lab, you can choose a different spec" (UMR
        p. 9)."""
        engine, game, match = self.standard()
        player = match.player(1)
        built(match, 1, "tech1")
        built(match, 1, "tech2")
        player.tech2_spec = "fire"
        self.build(engine, game, match, "tech_lab", spec="blood")
        player.add_on.under_construction = False
        board.damage_building(match, 1, "add_on", 4, StepResult())
        self.assertIsNone(player.add_on)
        self.assertEqual(engine.chosen_specs(player), ("fire",))
        self.build(engine, game, match, "tech_lab", spec="anarchy")
        self.assertEqual(player.add_on.spec, "anarchy")

    def test_the_basic_game_builds_the_tower_and_the_surplus_alone(self) -> None:
        """"Only use the tower and surplus add-ons. You can't construct
        heroes' halls or tech labs" (UMR p. 3)."""
        engine, game, match = main_phase()
        match.player(1).gold = 20
        offered = [row.building for row in pending_prompt(engine, game, match).options.buildings]
        self.assertEqual(offered, ["tech1", "tech2", "tech3", "tower", "surplus"])
        refused = driver.apply(engine, game, match, Action(
            PromptKind.MAIN_ACTION, "build", {"building": "heroes_hall"},
        ))
        self.assertIsInstance(refused, driver.Refusal)
        self.assertEqual(refused.cite, "UMR p. 3")

    def test_a_multicolour_teams_first_building_costs_one_more(self) -> None:
        """"If your team has multiple hero colors, then your first tech
        building or add-on costs +1 gold" (UMR p. 8) -- once, a rebuild
        included."""
        engine, game, match = self.standard(teams=(("fire", "feral", "anarchy"), self.GREEN))
        player = match.player(1)
        self.assertEqual(engine.team_colors(player), ("red", "green"))
        self.assertEqual(engine.build_option(player, "tech1").cost, 2)
        self.assertEqual(engine.build_option(player, "heroes_hall").cost, 3)
        self.build(engine, game, match, "tech1")
        self.assertEqual(player.gold, 18)
        self.assertTrue(player.constructed_once)
        self.assertEqual(engine.build_option(player, "heroes_hall").cost, 2)

    def test_a_rebuild_is_the_first_construction_too(self) -> None:
        engine, game, match = self.standard(teams=(("fire", "feral", "anarchy"), self.GREEN))
        player = match.player(1)
        built(match, 1, "tech1").destroyed = True
        self.assertEqual(engine.build_option(player, "tech1").cost, 1)
        self.build(engine, game, match, "tech1")
        self.assertEqual(engine.build_option(player, "tower").cost, 3)

    def test_one_colour_and_neutral_cost_nothing_more(self) -> None:
        """"Neutral heroes don't apply this cost to your team. For example,
        a team with Jaina (red), Zane (red), and Troq (neutral) wouldn't
        add to your building cost, but a team with Jaina, Troq, and
        Calamandra (green) would" (UMR p. 8)."""
        engine, game, match = self.standard(teams=(("fire", "anarchy", "bashing"), self.GREEN))
        self.assertEqual(engine.team_colors(match.player(1)), ("red",))
        self.assertEqual(engine.build_option(match.player(1), "tech1").cost, 1)
        engine, game, match = self.standard(teams=(("fire", "bashing", "feral"), self.GREEN))
        self.assertEqual(engine.build_option(match.player(1), "tech1").cost, 2)
        self.assertEqual(engine.build_option(match.player(2), "tech1").cost, 1)

    def test_the_heroes_hall_raises_the_limit_once_finished(self) -> None:
        """"You can't immediately summon a new hero when you construct
        this, because it finishes construction at end of turn" (UMR p. 9)."""
        engine, game, match = self.standard()
        player = match.player(1)
        hero_in_play(match, 1, slug="jaina_stormborne")
        self.build(engine, game, match, "heroes_hall")
        self.assertEqual(engine.hero_limit(player), 1)
        player.add_on.under_construction = False
        self.assertEqual(engine.hero_limit(player), 2)


class BuildingCardTests(unittest.TestCase):
    """Building cards and upgrades in play (UMR p. 7), since red and
    green's starters have them: a building has HP and may be attacked, an
    upgrade has none and may not; neither patrols nor attacks; both
    arrive with arrival fatigue."""

    def green(self):
        engine, game, match = new_game(teams=(("feral",), ("fire",)))
        begin(engine, game, match)
        return engine, game, match

    def test_a_building_card_and_an_upgrade_are_played_into_play(self) -> None:
        engine, game, match = self.green()
        player = match.player(1)
        player.gold = 10
        hand(match, 1, "verdant_tree", "rich_earth")
        driver.apply(engine, game, match, Action(PromptKind.MAIN_ACTION, "play", {"slug": "verdant_tree"}))
        driver.apply(engine, game, match, Action(PromptKind.MAIN_ACTION, "play", {"slug": "rich_earth"}))
        tree, earth = player.play
        self.assertEqual((tree.slug, earth.slug), ("verdant_tree", "rich_earth"))
        self.assertTrue(tree.arrived_this_turn and earth.arrived_this_turn)
        self.assertEqual(player.gold, 10 - 2 - 3)
        self.assertNotIn(tree.ref, engine.attackers(match))
        self.assertNotIn(tree.ref, engine.patrol_candidates(match))
        self.assertNotIn(earth.ref, engine.patrol_candidates(match))

    def test_a_building_card_may_be_attacked_and_goes_to_the_discard(self) -> None:
        """"Buildings have HP, so your opponent can attack and destroy
        them" (UMR p. 7) -- once the patrol zone allows; destroyed, it
        goes to its owner's discard and deals nothing to the base, which
        p. 8 says of tech buildings and add-ons alone."""
        engine, game, match = self.green()
        tree = put(match, 2, "verdant_tree")
        earth = put(match, 2, "rich_earth")
        guard = put(match, 2, "older_brother", patrol="squad_leader")
        rhino = put(match, 1, "regularsized_rhinoceros")
        self.assertNotIn(tree.ref, engine.legal_defenders(match, rhino.ref))
        guard.patrol_slot = None
        defenders = engine.legal_defenders(match, rhino.ref)
        self.assertIn(tree.ref, defenders)
        self.assertNotIn(earth.ref, defenders, "an upgrade has no HP")
        combat.declare_attack(engine, game, match, rhino.ref, tree.ref)
        self.assertIsNone(match.player(2).instance(tree.id))
        self.assertIn("verdant_tree", match.player(2).discard)
        self.assertEqual(match.player(2).base_hp, 20)
        self.assertEqual(rhino.damage, 0, "a building deals nothing back")

    def test_a_tech_building_card_needs_its_building_and_its_spec(self) -> None:
        engine, game, match = new_game(teams=(("fire", "anarchy", "blood"), ("feral", "growth", "balance")))
        begin(engine, game, match)
        player = match.player(1)
        player.gold = 10
        self.assertIn("Tech II", engine.why_not_playable(player, "firehouse"))
        built(match, 1, "tech1")
        built(match, 1, "tech2")
        self.assertIn("Fire", engine.why_not_playable(player, "firehouse"))
        player.tech2_spec = "fire"
        self.assertEqual(engine.why_not_playable(player, "firehouse"), "")
