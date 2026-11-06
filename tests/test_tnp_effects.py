"""
The advanced game (docs/tnp-rules.md, 8; step 9 of docs/tnp-bot.md):
the three decks, a harvest drawing cards, a card traded as the mineral
it is, the cards put into play, Tactical Command, and **a test per card
whose effect is built** (`CARD_TESTS` holds every one of
`tnp.effects.EFFECTS` to a test), each at the author's d12 value.
"""

from __future__ import annotations

import json
import random
import re
import unittest
from pathlib import Path

from tnp import effects
from tnp.battle import BASE_LEFT, Column, carriable, cloaked, initiative, scouting_totals, targets
from tnp.components import PLAN, TRADE, MatchState, SeatState
from tnp.engine import RulesEngine
from tnp.flow import battle as fight_steps
from tnp.flow import driver
from tnp.flow.result import StepResult
from tnp.formatting import card_lines, find_card
from tnp.game import RuleRefusal
from tnp.prompts import Action, PromptKind, pending_prompts
from tnp.tokens import plain
from tnp import turn

from tnp_battles import asked, scripted
from tnp_games import Harvester, Raider, opening, play

ROOT = Path(__file__).resolve().parent.parent

#: Each card whose effect is built, and the test that pins it.
CARD_TESTS = {
    "command_and_control_cpu": "test_command_and_control_cpu_opens_attack_spot_c",
    "salvage_yard": "test_salvage_gains_a_material_a_mechanical_unit_destroyed",
    "salvaging_under_fire": "test_salvaging_under_fire_is_one_a_round",
    "jeweler": "test_jeweler_and_trader_raise_a_minerals_trade",
    "trader": "test_jeweler_and_trader_raise_a_minerals_trade",
    "harvesters": "test_harvesters_take_two_a_worker",
    "satellite_connection": "test_satellite_connection_adds_two_scouting",
    "automation": "test_automation_and_construction_crane_discount_a_unit",
    "construction_crane": "test_automation_and_construction_crane_discount_a_unit",
    "surprisingly_valuable_side_effects": "test_side_effects_gain_a_gold_when_the_facility_produces",
    "ammo_depos": "test_ammo_depos_reroll_missed_dice",
    "extra_large_ammo_depos": "test_ammo_depos_reroll_missed_dice",
    "improved_carrier_capacity": "test_improved_carrier_capacity",
    "jet_engines": "test_jet_engines_and_radars_on_initiative",
    "radars": "test_jet_engines_and_radars_on_initiative",
    "arm_workers": "test_tactical_command_reveals_both_cards_together",
    "enhancing_drugs": "test_enhancing_drugs_each_hit_kills_two",
    "advanced_targeting": "test_the_tactic_modifiers",
    "heat_seeking_missile": "test_the_tactic_modifiers",
    "cloaking": "test_cloaking_hides_an_unengaged_transformer_force",
    "explosives": "test_explosives_against_the_base",
    "aa_missiles": "test_the_building_techs_modifiers",
    "lasers": "test_the_building_techs_modifiers",
    "grenades": "test_the_building_techs_modifiers",
    "specialized_training": "test_the_building_techs_modifiers",
}


def advanced_match(blue: SeatState | None = None, green: SeatState | None = None) -> MatchState:
    """A battle's match in the advanced game, with the seats' cards."""
    return MatchState(advanced=True, seats={"blue": blue or SeatState(), "green": green or SeatState()})


def open_battle(engine, match, attacker, defender, *, territory="8", tactics=(), **kwargs):
    """`begin_battle` with both seats' cards in play handed in, Blue
    attacking Green's territory, and the battle run to its first question."""
    rows, record = effects.battle_effects(engine, match)
    area = engine.catalog.areas[territory]
    held = None if area.is_base else "green"
    result = fight_steps.begin_battle(
        engine, match, territory, {"blue": attacker, "green": defender},
        attacker="blue", held_by=held, paths_home={"blue": True, "green": True},
        modifiers=tuple(rows), effects=record, tactics=tactics, **kwargs,
    )
    driver.advance(engine, None, match, result)
    return match.battle


def lock(engine, game, match, seat, plan):
    run = driver.apply(engine, game, match, Action(PromptKind.PLAN, "lock", {"plan": plan}, seat=seat))
    if isinstance(run, driver.Refusal):
        raise AssertionError(run.reason)
    return run


class TheCardsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = RulesEngine()
        self.catalog = self.engine.catalog

    def test_every_card_is_built_or_asked_about(self) -> None:
        """TNP 8: every Human tech row is built, or waits on a question."""
        built, asked_about = set(effects.EFFECTS), set(effects.UNIMPLEMENTED)
        self.assertFalse(built & asked_about)
        self.assertEqual(built | asked_about, set(self.catalog.techs))
        for slug, effect in effects.EFFECTS.items():
            for unit in effect.units:
                self.assertIn(unit, self.catalog.units, slug)
            if effect.attached:
                self.assertEqual(self.catalog.techs[slug].type, effects.BUILDING_TECH, slug)

    def test_a_test_for_every_built_card(self) -> None:
        self.assertEqual(set(CARD_TESTS), set(effects.EFFECTS))
        for slug, name in CARD_TESTS.items():
            self.assertTrue(hasattr(self, name) or hasattr(CardEffectTests, name), (slug, name))

    def test_the_d12_values_are_the_authors(self) -> None:
        """TNP 8.5: each card's modifier is the d12 column of the rules'
        table, read from docs/tnp-rules.md itself."""
        text = (ROOT / "docs" / "tnp-rules.md").read_text(encoding="utf-8")
        section = text[text.index("### 8.5"):text.index("## Change log")]
        found = 0
        for name, value in re.findall(r"^\| ([A-Z][^|]+?) \| [^|]+ \| [^|]+ \| ([+−-]\d)", section, re.M):
            slug = find_card(self.catalog, name)
            if slug is None:
                continue  # Positioning and Air Cover have no count in the sheet
            self.assertEqual(effects.EFFECTS[slug].modifier, int(value.replace("−", "-")), name)
            found += 1
        self.assertEqual(found, 9)

    def test_the_card_command_answers(self) -> None:
        words = [plain(line, self.catalog) for line in card_lines(self.catalog, find_card(self.catalog, "grenades"))]
        self.assertIn("**Grenades** -- building tech, gems deck, 3 in the deck.", words)
        self.assertTrue(any("+3 against infantry" in line for line in words))
        asked_about = card_lines(self.catalog, "snipe")
        self.assertTrue(any("Not built yet" in line for line in asked_about))


class SetupTests(unittest.TestCase):
    def test_the_decks_are_shuffled_at_setup(self) -> None:
        """TNP 3, 8.1: each card as many times as its count, shuffled from
        the engine's rng; none in the basic game."""
        engine, game, match = opening(seed=4, advanced=True)
        catalog = engine.catalog
        for deck, cards in match.decks.items():
            expected = sorted(slug for slug, tech in catalog.techs.items() if tech.deck == deck
                              for _ in range(tech.count))
            self.assertEqual(sorted(cards), expected)
            self.assertEqual(match.discards[deck], [])
        again = opening(seed=4, advanced=True)[2]
        self.assertEqual(again.decks, match.decks)
        self.assertNotEqual(opening(seed=5, advanced=True)[2].decks, match.decks)
        self.assertEqual(opening(seed=4)[2].decks, {})
        self.assertEqual(MatchState.from_dict(json.loads(json.dumps(match.to_dict()))).decks, match.decks)

    def test_the_decks_cover_the_map(self) -> None:
        """A card a token harvested: each deck holds at least the map's tokens of its kind."""
        engine, _, match = opening(advanced=True)
        for deck in match.decks:
            on_map = sum(area.resources.get(deck, 0) for area in match.areas.values())
            self.assertGreaterEqual(len(match.decks[deck]), on_map, deck)


class TurnTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine, self.game, self.match = opening(seed=2, advanced=True)

    def test_a_harvest_draws_a_card_a_token(self) -> None:
        """TNP 5.8, 8.1: the Workers take the tokens off the map -- they
        count toward the 51% -- and draw the cards in their place."""
        top = list(self.match.decks["blue_minerals"][:3])
        lock(self.engine, self.game, self.match, "blue",
             {"attacks": {"A": {"target": "14", "units": {"worker": 3}}}})
        run = lock(self.engine, self.game, self.match, "green", {})
        blue = self.match.seat("blue")
        self.assertEqual(blue.harvested, 3)
        self.assertEqual(self.match.areas["14"].resources["blue_minerals"], 7)
        self.assertEqual(blue.pool.get("blue_minerals", 0), 0)
        self.assertEqual(sum(blue.hand.values()), 3)
        self.assertEqual(sorted(slug for slug, n in blue.hand.items() for _ in range(n)), sorted(top))
        said = " ".join(plain(line, self.engine.catalog) for line in run.narration)
        self.assertIn("3 blue minerals, drawn as cards", said)
        for slug in top:  # which cards were drawn is the seat's own
            self.assertNotIn(self.engine.catalog.name(slug), said)

    def test_a_card_trades_as_its_mineral(self) -> None:
        """TNP 5.9, 8.1: a mineral card for 2 materials or 1 gold, a gem
        card for 3 or 2; traded cards are discarded."""
        blue = self.match.seat("blue")
        blue.hand = {"jeweler": 2, "grenades": 1}
        self.match.phase = TRADE
        refused = driver.apply(self.engine, self.game, self.match, Action(
            PromptKind.TRADE, "lock", {"trade": {"materials": {"blue_minerals": 1}}}, seat="blue"))
        self.assertIsInstance(refused, driver.Refusal)
        self.assertEqual(refused.cite, "TNP 8.1")
        driver.apply(self.engine, self.game, self.match, Action(
            PromptKind.TRADE, "lock", {"trade": {"materials": {"jeweler": 2}, "gold": {"grenades": 1}}},
            seat="blue"))
        blue = self.match.seat("blue")  # a refusal puts the match back from its save
        self.assertEqual(blue.hand, {})
        self.assertEqual(blue.pool["materials"], 5 + 4)
        self.assertEqual(blue.pool["gold"], 2)
        self.assertEqual(self.match.discards["blue_minerals"], ["jeweler", "jeweler"])
        self.assertEqual(self.match.discards["gems"], ["grenades"])

    def test_cards_are_put_into_play_at_production(self) -> None:
        """TNP 5.2, 8.3, 8.4: a building tech on a production facility, a
        tech facility paid for, both in play from Production."""
        blue = self.match.seat("blue")
        blue.hand = {"grenades": 1, "jeweler": 1, "command_and_control_cpu": 1}
        plan = {"techs": {"attach": {"barracks": "grenades"}, "build": ["jeweler"]}}
        lock(self.engine, self.game, self.match, "blue", plan)
        lock(self.engine, self.game, self.match, "green", {})
        self.assertEqual(blue.pool["materials"], 5 - 3)
        self.assertEqual(blue.hand, {"command_and_control_cpu": 1})
        self.assertEqual(blue.tech, ["jeweler"])
        self.assertEqual(blue.attached, {"barracks": "grenades"})
        self.assertEqual(blue.queued_techs, {})

    def test_what_a_plan_may_not_put_into_play(self) -> None:
        blue = self.match.seat("blue")
        blue.hand = {"lasers": 1, "jeweler": 1, "trader": 2, "intelligence_facility": 1, "snipe": 1}
        blue.pool["materials"] = 30
        cases = [
            ({"attach": {"factory": "lasers"}}, "TNP 8.3"),        # the Factory is not built
            ({"attach": {"barracks": "jeweler"}}, "TNP 8.3"),      # not a building tech
            ({"build": ["lasers"]}, "TNP 8.4"),                    # not a tech facility
            ({"build": ["trader", "trader", "jeweler"]}, "TNP 8.4"),  # three tech facilities
            ({"build": ["intelligence_facility"]}, "TNP 8"),       # waits on the author
            ({"build": ["snipe"]}, "TNP 8"),
        ]
        for techs, cite in cases:
            with self.subTest(techs=techs):
                with self.assertRaises(RuleRefusal) as refused:
                    turn.check_plan(self.engine, self.match, "blue", turn.normal_plan({"techs": techs}))
                self.assertEqual(refused.exception.cite, cite)
        blue.tech = ["trader", "satellite_connection"]
        turn.check_plan(self.engine, self.match, "blue",
                        turn.normal_plan({"techs": {"build": ["jeweler"], "discard": ["trader"]}}))
        blue.attached = {"barracks": "grenades"}
        with self.assertRaises(RuleRefusal):
            turn.check_plan(self.engine, self.match, "blue",
                            turn.normal_plan({"techs": {"attach": {"barracks": "lasers"}}}))

    def test_the_basic_game_puts_no_card_into_play(self) -> None:
        engine, _, match = opening()
        match.seat("blue").hand = {"jeweler": 1}
        with self.assertRaises(RuleRefusal) as refused:
            turn.check_plan(engine, match, "blue", turn.normal_plan({"techs": {"build": ["jeweler"]}}))
        self.assertEqual(refused.exception.cite, "TNP 8")

    def test_a_tech_facility_discarded_makes_room(self) -> None:
        blue = self.match.seat("blue")
        blue.tech = ["trader", "satellite_connection"]
        blue.hand = {"jeweler": 1}
        lock(self.engine, self.game, self.match, "blue",
             {"techs": {"build": ["jeweler"], "discard": ["trader"]}})
        lock(self.engine, self.game, self.match, "green", {})
        self.assertEqual(blue.tech, ["satellite_connection", "jeweler"])
        self.assertEqual(self.match.discards["blue_minerals"], ["trader"])

    def test_a_whole_advanced_game_through_the_driver(self) -> None:
        """Blue's Raider against Green's Harvester, the advanced game, to
        a win: cards drawn, traded and kept, every position through its
        save."""
        engine, game, match = opening(seed=11, advanced=True)
        match, runs = play(engine, game, match, {"blue": Raider(), "green": Harvester()}, turns=60)
        self.assertIsNotNone(match.winner)
        drawn = sum(len(pile) for pile in match.discards.values()) + sum(
            match.seat(seat).cards() for seat in ("blue", "green"))
        self.assertEqual(drawn, sum(match.seat(seat).harvested for seat in ("blue", "green")))


class CardEffectTests(unittest.TestCase):
    """A test per card whose effect is built (`CARD_TESTS`)."""

    def setUp(self) -> None:
        self.engine = RulesEngine(rng=random.Random(1))

    def parts(self, battle, force, target):
        from tnp.battle import modifier_parts

        return {kind: value for kind, value, _ in modifier_parts(self.engine, battle, force, target)}

    def line(self, battle, *columns):
        battle.line = [Column(front=dict(front)) for front in columns]

    # -- The turn ---------------------------------------------------------

    def test_command_and_control_cpu_opens_attack_spot_c(self) -> None:
        engine, game, match = opening(advanced=True)
        self.assertEqual(turn.attack_spots(match, "blue"), ("A", "B"))
        with self.assertRaises(RuleRefusal):
            turn.check_plan(engine, match, "blue", turn.normal_plan(
                {"attacks": {"C": {"target": "13", "units": {"worker": 1}}}}))
        match.seat("blue").tech = ["command_and_control_cpu"]
        self.assertEqual(turn.attack_spots(match, "blue"), ("A", "B", "C"))
        lock(engine, game, match, "blue", {"attacks": {"C": {"target": "13", "units": {"worker": 1}}}})
        lock(engine, game, match, "green", {})
        self.assertEqual(match.controller("13"), "blue")

    def test_jeweler_and_trader_raise_a_minerals_trade(self) -> None:
        state = SeatState()
        self.assertEqual(turn.trade_rates(self.engine, state)["mineral"], {"materials": 2, "gold": 1})
        state.tech = ["jeweler"]
        self.assertEqual(turn.trade_rates(self.engine, state)["mineral"], {"materials": 2, "gold": 2})
        state.tech = ["jeweler", "trader"]
        self.assertEqual(turn.trade_rates(self.engine, state)["mineral"], {"materials": 3, "gold": 2})
        self.assertEqual(turn.trade_rates(self.engine, state)["gem"], {"materials": 3, "gold": 2})
        gains = turn.trade_gains(self.engine, {"materials": {"trader": 1}, "gold": {"jeweler": 1, "lasers": 1}},
                                 state, advanced=True)
        self.assertEqual(gains, {"materials": 3, "gold": 4})

    def test_harvesters_take_two_a_worker(self) -> None:
        engine, game, match = opening(advanced=True)
        match.seat("blue").tech = ["harvesters"]
        lock(engine, game, match, "blue", {"attacks": {"A": {"target": "14", "units": {"worker": 3}}}})
        lock(engine, game, match, "green", {})
        self.assertEqual(match.seat("blue").harvested, 6)
        self.assertEqual(match.seat("blue").cards(), 6)
        self.assertEqual(match.areas["14"].resources["blue_minerals"], 4)

    def test_automation_and_construction_crane_discount_a_unit(self) -> None:
        state = SeatState(built=["barracks", "base_defenses", "factory"])
        self.assertEqual(turn.unit_cost(self.engine, state, "cyborg_soldier").materials, 3)
        state.attached = {"barracks": "automation"}
        self.assertEqual(turn.unit_cost(self.engine, state, "cyborg_soldier").materials, 2)
        self.assertEqual(turn.unit_cost(self.engine, state, "tank").materials, 3)
        self.assertEqual(turn.unit_cost(self.engine, state, "worker").materials, 1)  # to a minimum of 1
        state.tech = ["construction_crane"]
        self.assertEqual(turn.unit_cost(self.engine, state, "cyborg_soldier").materials, 1)
        self.assertEqual(turn.unit_cost(self.engine, state, "tank").materials, 2)
        self.assertEqual(turn.unit_cost(self.engine, state, "stealth_sniper").gold, 1)

    def test_side_effects_gain_a_gold_when_the_facility_produces(self) -> None:
        engine, game, match = opening(advanced=True)
        blue = match.seat("blue")
        blue.attached = {"barracks": "surprisingly_valuable_side_effects"}
        lock(engine, game, match, "blue", {"build": {"worker": 1}})
        run = lock(engine, game, match, "green", {"build": {"worker": 1}})
        self.assertEqual(blue.pool["gold"], 1)
        self.assertEqual(match.seat("green").pool["gold"], 0)
        self.assertIn("Blue gains 1 gold from its production.",
                      " ".join(plain(line, engine.catalog) for line in run.narration))

    def test_improved_carrier_capacity(self) -> None:
        """TNP 7: 4 infantry, 3 Jeeps, or 2 Tanks or Transformers a carrier."""
        self.assertEqual(turn.carriers_needed(self.engine, {"mercenary": 4}), 2)
        self.assertEqual(turn.carriers_needed(self.engine, {"mercenary": 4}, improved=True), 1)
        self.assertEqual(turn.carriers_needed(self.engine, {"tank": 2}, improved=True), 1)
        match = advanced_match(SeatState(tech=["improved_carrier_capacity"]))
        battle = open_battle(self.engine, match, {"chopper_carrier": 1, "jeep": 3}, {"mercenary": 1})
        self.assertEqual(carriable(self.engine, battle, "blue"), {"blue:jeep": 3})

    # -- The battle ------------------------------------------------------

    def test_the_building_techs_modifiers(self) -> None:
        """TNP 8.5: AA Missiles, Lasers, Grenades +3 against their type and
        Specialized Training +2 on every roll, for the units the facility
        they are attached to builds."""
        blue = SeatState(attached={"barracks": "grenades", "factory": "lasers", "airport": "aa_missiles"})
        green = SeatState(attached={"barracks": "specialized_training"})
        match = advanced_match(blue, green)
        battle = open_battle(self.engine, match,
                             {"mercenary": 2, "tank": 1, "viper_spy_plane": 1},
                             {"mercenary": 2, "jeep": 1, "chopper_carrier": 1})
        self.line(battle, {"blue": "blue:mercenary", "green": "green:mercenary"},
                  {"blue": "blue:tank", "green": "green:jeep"},
                  {"blue": "blue:viper_spy_plane", "green": "green:chopper_carrier"})
        self.assertEqual(self.parts(battle, "blue:mercenary", "green:mercenary"), {"outside:grenades": 3})
        self.assertNotIn("outside:grenades", self.parts(battle, "blue:mercenary", "green:jeep"))
        self.assertEqual(self.parts(battle, "blue:tank", "green:jeep"), {"outside:lasers": 3})
        self.assertEqual(self.parts(battle, "blue:viper_spy_plane", "green:chopper_carrier"),
                         {"outside:aa_missiles": 3})
        self.assertEqual(self.parts(battle, "green:mercenary", "blue:tank")["outside:specialized_training"], 2)
        self.assertEqual(self.parts(battle, "green:mercenary", "blue:viper_spy_plane")["outside:specialized_training"], 2)
        self.assertNotIn("outside:specialized_training", self.parts(battle, "green:jeep", "blue:tank"))

    def test_explosives_against_the_base(self) -> None:
        """Stealth Snipers +6 against a Base Defense unit or a base card."""
        match = advanced_match(SeatState(tech=["explosives"]))
        battle = open_battle(
            self.engine, match, {"stealth_sniper": 2}, {"laser_cannon": 1, "mercenary": 1},
            territory="green_base",
            structures={"facilities": ["barracks", "base_defenses"], "upgrades": []},
            emergency={"pool": {}, "supply_room": {}},
        )
        self.line(battle, {"blue": "blue:stealth_sniper", "green": "green:laser_cannon"},
                  {"green": "green:mercenary"})
        self.assertEqual(self.parts(battle, "blue:stealth_sniper", "green:laser_cannon")["outside:explosives"], 6)
        self.assertEqual(self.parts(battle, "blue:stealth_sniper", BASE_LEFT)["outside:explosives"], 6)
        self.assertNotIn("outside:explosives", self.parts(battle, "blue:stealth_sniper", "green:mercenary"))

    def test_jet_engines_and_radars_on_initiative(self) -> None:
        """Jet Engines: Jeeps Mechanical, −1 initiative; Radars on the
        Factory: its Mechanical units −2 -- the Jeep too, once Jet Engines
        make it Mechanical."""
        match = advanced_match(SeatState(attached={"factory": "radars"}), SeatState(tech=["jet_engines"]))
        battle = open_battle(self.engine, match, {"jeep": 1, "tank": 1}, {"jeep": 1})
        self.assertEqual(initiative(self.engine, battle, battle.force("blue:tank")), 1)
        self.assertEqual(initiative(self.engine, battle, battle.force("blue:jeep")), 2)
        self.assertEqual(initiative(self.engine, battle, battle.force("green:jeep")), 1)
        both = advanced_match(SeatState(tech=["jet_engines"], attached={"factory": "radars"}))
        battle = open_battle(self.engine, both, {"jeep": 1}, {"mercenary": 1})
        self.assertEqual(initiative(self.engine, battle, battle.force("blue:jeep")), -1)

    def test_satellite_connection_adds_two_scouting(self) -> None:
        match = advanced_match(SeatState(tech=["satellite_connection"]))
        battle = open_battle(self.engine, match, {"mercenary": 1}, {"mercenary": 1})
        self.assertEqual(scouting_totals(self.engine, battle), {"blue": 2, "green": 0})

    def test_the_tactic_modifiers(self) -> None:
        """Advanced Targeting: Cyborgs +3 against air; Heat Seeking
        Missile: Vipers +3; Arm Workers: Workers +3."""
        match = advanced_match()
        battle = open_battle(self.engine, match, {"cyborg_soldier": 1, "viper_spy_plane": 1, "worker": 1},
                             {"chopper_carrier": 1, "mercenary": 1})
        for card in ("advanced_targeting", "heat_seeking_missile", "arm_workers"):
            self.assertTrue(effects.add_tactic(self.engine, battle, "blue", card))
        self.line(battle, {"blue": "blue:cyborg_soldier", "green": "green:chopper_carrier"},
                  {"blue": "blue:viper_spy_plane", "green": "green:mercenary"}, {"blue": "blue:worker"})
        self.assertEqual(self.parts(battle, "blue:cyborg_soldier", "green:chopper_carrier"),
                         {"outside:advanced_targeting": 3})
        self.assertNotIn("outside:advanced_targeting", self.parts(battle, "blue:cyborg_soldier", "green:mercenary"))
        self.assertEqual(self.parts(battle, "blue:viper_spy_plane", "green:mercenary")["outside:heat_seeking_missile"], 3)
        self.assertEqual(self.parts(battle, "blue:worker", "green:mercenary")["outside:arm_workers"], 3)
        self.assertFalse(effects.add_tactic(self.engine, battle, "green", "arm_workers"))

    def test_cloaking_hides_an_unengaged_transformer_force(self) -> None:
        match = advanced_match()
        battle = open_battle(self.engine, match, {"mercenary": 2}, {"the_transformer": 1, "mercenary": 1})
        effects.add_tactic(self.engine, battle, "green", "cloaking")
        self.line(battle, {"blue": "blue:mercenary", "green": "green:mercenary"},
                  {"green": "green:the_transformer"})
        self.assertTrue(cloaked(battle, "green:the_transformer"))
        self.assertNotIn("green:the_transformer", targets(self.engine, battle, "blue:mercenary"))
        self.line(battle, {"blue": "blue:mercenary", "green": "green:the_transformer"},
                  {"green": "green:mercenary"})
        self.assertIn("green:the_transformer", targets(self.engine, battle, "blue:mercenary"))

    def _fight_round(self, battle_match, rolls):
        """Answer one round's retreats with fight, the dice scripted; the
        question asked when the round is over or another is asked."""
        start = battle_match.battle.round
        with scripted(self.engine, rolls):
            while True:
                prompt = asked(self.engine, battle_match)
                if battle_match.battle.round != start and prompt is not None:
                    return prompt
                if prompt is None or prompt.kind is not PromptKind.DECLARE_RETREAT:
                    return prompt
                run = driver.apply(self.engine, None, battle_match, Action(PromptKind.DECLARE_RETREAT, "fight"))
                self.assertNotIsInstance(run, driver.Refusal)

    def test_enhancing_drugs_each_hit_kills_two(self) -> None:
        """Mercenaries −1 initiative, +4 on every roll, and each hit on
        them kills 2."""
        self.engine.answers_the_only_choice = True
        match = advanced_match()
        battle = open_battle(self.engine, match, {"mercenary": 1}, {"mercenary": 4})
        effects.add_tactic(self.engine, battle, "green", "enhancing_drugs")
        self.assertEqual(initiative(self.engine, battle, battle.force("green:mercenary")), 1)
        self.assertEqual(self.parts(battle, "green:mercenary", "blue:mercenary")["outside:enhancing_drugs"], 4)
        # Green's four roll first, at initiative 1, and miss; Blue's one hits.
        self._fight_round(match, [1, 1, 1, 1, 12])
        self.assertEqual(battle.force("green:mercenary").count, 2)

    def test_salvage_gains_a_material_a_mechanical_unit_destroyed(self) -> None:
        self.engine.answers_the_only_choice = True
        match = advanced_match(SeatState(tech=["salvage_yard"]))
        battle = open_battle(self.engine, match, {"mercenary": 3}, {"cyborg_soldier": 1})
        # Blue's Mercenaries (initiative 2) hit twice: the Cyborg is damaged, then destroyed.
        self._fight_round(match, [12, 12, 1])
        self.assertEqual(battle.outcome["winner"], "blue")
        self.assertEqual(battle.outcome["gains"], {"blue": 1})

    def test_salvaging_under_fire_is_one_a_round(self) -> None:
        self.engine.answers_the_only_choice = True
        match = advanced_match()
        battle = open_battle(self.engine, match, {"mercenary": 6}, {"cyborg_soldier": 2})
        effects.add_tactic(self.engine, battle, "blue", "salvaging_under_fire")
        self._fight_round(match, [12, 12, 12, 12, 1, 1])
        self.assertEqual(battle.outcome["gains"], {"blue": 1})

    def test_ammo_depos_reroll_missed_dice(self) -> None:
        """Ammo Depos: 2 rerolls a battle, Extra Large 4; a roll's missed
        dice may be rolled again before its hits land."""
        self.engine.answers_the_only_choice = True
        match = advanced_match(SeatState(tech=["ammo_depos", "extra_large_ammo_depos"]))
        battle = open_battle(self.engine, match, {"mercenary": 2}, {"mercenary": 2})
        self.assertEqual(battle.effects["rerolls"], {"blue": 6})
        prompt = self._fight_round(match, [1, 1])
        self.assertIs(prompt.kind, PromptKind.REROLL)
        self.assertEqual((prompt.options.missed, prompt.options.most, prompt.options.left), (2, 2, 6))
        refused = driver.apply(self.engine, None, match, Action(PromptKind.REROLL, "reroll", {"count": 3}))
        self.assertIsInstance(refused, driver.Refusal)
        with scripted(self.engine, [12, 12, 1, 1]):
            driver.apply(self.engine, None, match, Action(PromptKind.REROLL, "reroll", {"count": 2}))
        battle = match.battle  # a refusal puts the match back from its save
        self.assertEqual(battle.effects["rerolls"], {"blue": 4})
        self.assertEqual(battle.force("green:mercenary").count, 0)

    def test_tactical_command_reveals_both_cards_together(self) -> None:
        """TNP 6.3: both seats choose at once, in secret; nothing is said
        of a card until both have chosen; then each is revealed, leaves
        its seat's hand for the discard pile, and does what it says."""
        match = advanced_match(SeatState(hand={"arm_workers": 1, "grenades": 1}),
                               SeatState(hand={"cloaking": 1}))
        battle = open_battle(self.engine, match, {"worker": 2}, {"mercenary": 2},
                             tactics=("blue", "green"))
        prompts = pending_prompts(self.engine, None, match)
        self.assertEqual([(one.kind, one.asked_seat) for one in prompts],
                         [(PromptKind.TACTIC, "blue"), (PromptKind.TACTIC, "green")])
        self.assertEqual([one.card for one in prompts[0].options.cards], ["arm_workers"])
        self.assertEqual(prompts[1].options.applies, ())
        unnamed = driver.apply(self.engine, None, match, Action(PromptKind.TACTIC, "play", {"card": "arm_workers"}))
        self.assertIsInstance(unnamed, driver.Refusal)
        first = driver.apply(self.engine, None, match,
                             Action(PromptKind.TACTIC, "play", {"card": "arm_workers"}, seat="blue"))
        said = " ".join(plain(line, self.engine.catalog) for line in first.narration)
        self.assertNotIn("Arm", said)
        self.assertEqual(match.seat("blue").hand, {"arm_workers": 1, "grenades": 1})
        second = driver.apply(self.engine, None, match,
                              Action(PromptKind.TACTIC, "play", {"card": "cloaking"}, seat="green"))
        said = " ".join(plain(line, self.engine.catalog) for line in second.narration)
        self.assertIn("Blue plays Arm workers.", said)
        self.assertIn("Green plays Cloaking: its units are not in the battle, and it does nothing.", said)
        self.assertEqual(match.seat("blue").hand, {"grenades": 1})
        self.assertEqual(match.discards, {"orange_minerals": ["arm_workers", "cloaking"]})
        self.assertEqual([row["card"] for row in battle.modifiers], ["arm_workers"])
        self.assertNotEqual(battle.phase, "tactics")

    def test_the_base_card_destroys_a_tech_before_its_facility(self) -> None:
        """TNP 6.9: a tech facility or a building tech may be destroyed,
        and a facility only once nothing is attached to it."""
        from tnp.battle import destroyable

        match = advanced_match()
        battle = open_battle(
            self.engine, match, {"tank": 2}, {"mercenary": 1}, territory="green_base",
            structures={"facilities": ["barracks", "base_defenses", "factory"], "upgrades": [],
                        "tech": ["jeweler"], "attached": {"factory": "lasers"}},
            emergency={"pool": {}, "supply_room": {}},
        )
        self.assertEqual(destroyable(self.engine, battle), ("jeweler", "lasers:factory"))
        fight_steps._destroy(battle, "lasers:factory", StepResult())
        self.assertEqual(battle.structures["attached"], {})

    def test_an_emergency_defense_pays_with_cards(self) -> None:
        """TNP 6.2, 8.1: in the advanced game the defender trades cards at
        the emergency rates -- a mineral card a material, a gem card a
        material or a gold."""
        match = advanced_match()
        battle = open_battle(
            self.engine, match, {"mercenary": 3}, {}, territory="green_base",
            structures={"facilities": ["barracks", "base_defenses"], "upgrades": []},
            emergency={"pool": {"materials": 0, "gold": 0, "blue": 2, "orange": 0, "gems": 1},
                       "supply_room": {"smart_mines": 8, "rocket_launcher": 8, "laser_cannon": 2},
                       "hand": {"jeweler": 2, "grenades": 1}},
        )
        prompt = asked(self.engine, match)
        self.assertIs(prompt.kind, PromptKind.EMERGENCY_DEFENSE)
        self.assertTrue(prompt.options.advanced)
        refused = driver.apply(self.engine, None, match, Action(
            PromptKind.EMERGENCY_DEFENSE, "build", {"units": {"smart_mines": 1},
                                                    "trade": {"gold": {"jeweler": 1}}}))
        self.assertIsInstance(refused, driver.Refusal)
        battle = match.battle  # a refusal puts the match back from its save
        driver.apply(self.engine, None, match, Action(
            PromptKind.EMERGENCY_DEFENSE, "build",
            {"units": {"smart_mines": 1}, "trade": {"materials": {"jeweler": 2}}}))
        self.assertEqual(battle.emergency["spent"], {"jeweler": 2})
        self.assertEqual(battle.emergency["hand"], {"grenades": 1})
        self.assertEqual(battle.force("green:smart_mines").count, 1)


if __name__ == "__main__":
    unittest.main()
