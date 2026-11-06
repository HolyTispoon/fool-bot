"""
The TNP battle (docs/tnp-rules.md, 6) fought through `tnp.flow.driver`
with nothing from `cogs/` or `discord`: each mechanic held to the
section it cites, and any two Human forces fought to a result with the
seeded `engine.rng` and a d12.

Positions are staged by unit slug and count (`tests/tnp_battles.py`);
dice are scripted where a test needs a number and seeded where it needs
only an end.
"""

from __future__ import annotations

import itertools
import json
import random
import unittest
from dataclasses import fields

from tnp.battle import BATTLE_SAVED_FIELDS, BattleState, adjacent, locate
from tnp.catalog import Rating, catalog
from tnp.components import MATCH_SAVED_FIELDS, MatchState
from tnp.engine import RulesEngine
from tnp.flow import driver
from tnp.flow.result import FollowOn, FollowOnStep
from tnp.prompts import CHOICES, OPTIONS, Action, PromptKind, pending

from tnp_battles import asked, fight, first, play, scripted, stage, words

PLACE = PromptKind.PLACE_FORCE
TARGET = PromptKind.CHOOSE_TARGET
RETREAT = PromptKind.DECLARE_RETREAT

def place(engine, match, force, slot, rolls=None):
    return play(engine, match, Action(PLACE, "", {"force": force, "slot": slot}), rolls)


def shoot(engine, match, force, target, rolls=None):
    return play(engine, match, Action(TARGET, "", {"force": force, "target": target}), rolls)


def fight_on(engine, match, rolls=None):
    return play(engine, match, Action(RETREAT, "fight"), rolls)


def retreat(engine, match, rolls=None):
    return play(engine, match, Action(RETREAT, "retreat"), rolls)


def options_for(prompt, force):
    return next(one for one in prompt.options.forces if one.force == force)


def target_option(prompt, force, target):
    return next(one for one in options_for(prompt, force).targets if one.target == target)


class FormingForcesTests(unittest.TestCase):
    def test_one_unit_type_a_force(self) -> None:
        """TNP 6.1: all a seat's units of one kind are one force."""
        engine, match = stage({"tank": 2, "worker": 3}, {"mercenary": 4})
        battle = match.battle
        self.assertEqual(
            sorted((one.id, one.count) for one in battle.forces),
            [("blue:tank", 2), ("blue:worker", 3), ("green:mercenary", 4)],
        )
        self.assertEqual((battle.attacker, battle.defender), ("blue", "green"))

    def test_base_defense_units_never_attack(self) -> None:
        """TNP 5.3, 7: Base Defense units are never in an attack."""
        from tnp.game import RuleRefusal

        with self.assertRaises(RuleRefusal) as refused:
            stage({"smart_mines": 1}, {"mercenary": 1})
        self.assertEqual(refused.exception.cite, "TNP 7")

    def test_an_undefended_territory_falls_at_once(self) -> None:
        """TNP 6.1: an attack on a held territory with nobody defending it wins at once."""
        engine, match = stage({"mercenary": 1}, {})
        outcome = match.battle.outcome
        self.assertEqual((outcome["winner"], outcome["by"], outcome["control"]), ("blue", "undefended", "blue"))
        self.assertIsNone(pending(engine, None, match))


class ContestedSidesTests(unittest.TestCase):
    def test_the_scouting_advantage_chooses(self) -> None:
        """TNP 6.1: both attack a neutral territory; the advantaged seat chooses its side."""
        engine, match = stage({"jeep": 1}, {"mercenary": 1}, contested=True, territory="1")
        prompt = asked(engine, match)
        self.assertEqual((prompt.kind, prompt.asked_seat), (PromptKind.CHOOSE_ROLE, "blue"))
        play(engine, match, Action(PromptKind.CHOOSE_ROLE, "defend"))
        self.assertEqual((match.battle.attacker, match.battle.defender), ("green", "blue"))

    def test_the_lower_initiative_defends(self) -> None:
        """TNP 6.1: with no advantage, the lower initiative total defends."""
        engine, match = stage({"mercenary": 2}, {"worker": 1}, contested=True, territory="1")
        # 2 Mercenaries at initiative 2 is 4; a Worker at 5 is 5.
        self.assertEqual((match.battle.attacker, match.battle.defender), ("green", "blue"))

    def test_equal_initiative_is_rolled_and_rerolled(self) -> None:
        """TNP 6.1: equal totals roll a die each, the higher attacking; equal rolls again."""
        engine, match = stage(
            {"mercenary": 1}, {"mercenary": 1}, contested=True, territory="1",
            rolls=[7, 7, 3, 9],
        )
        self.assertEqual((match.battle.attacker, match.battle.defender), ("green", "blue"))


class PlacementTests(unittest.TestCase):
    def test_the_advantage_places_last(self) -> None:
        """TNP 6.4, 6.5: with an advantage of N the other seat places N forces first, then they alternate."""
        engine, match = stage({"jeep": 2}, {"mercenary": 1, "worker": 1, "cyborg_soldier": 1})
        self.assertEqual(match.battle.advantage, {"seat": "blue", "by": 2})
        seats = []
        while asked(engine, match).kind is PLACE:
            prompt = asked(engine, match)
            seats.append(prompt.asked_seat)
            play(engine, match, first(prompt))
        self.assertEqual(seats, ["green", "green", "blue", "green"])

    def test_with_no_advantage_the_defender_places_first(self) -> None:
        """TNP 6.5: with no advantage the defender places first; then a turn engages, places one new force, and ends."""
        engine, match = stage({"mercenary": 1, "worker": 1}, {"mercenary": 1, "worker": 1})
        seats = []
        while asked(engine, match).kind is PLACE:
            prompt = asked(engine, match)
            seats.append(prompt.asked_seat)
            play(engine, match, first(prompt))
        self.assertEqual(seats, ["green", "blue", "blue", "green"])

    def test_an_unengaged_force_must_be_engaged(self) -> None:
        """TNP 6.5: while the other seat has an unengaged force in the line, a placement engages one."""
        engine, match = stage({"mercenary": 1, "worker": 1}, {"mercenary": 1, "worker": 1})
        place(engine, match, "green:mercenary", "column:0")
        prompt = asked(engine, match)
        for force in prompt.options.forces:
            self.assertEqual(force.slots, ("engage:0",))
        refused = driver.apply(engine, None, match, Action(PLACE, "", {"force": "blue:worker", "slot": "column:1"}))
        self.assertIsInstance(refused, driver.Refusal)
        self.assertEqual(refused.cite, "TNP 6.5")

    def test_flanking_only_once_the_other_seat_is_all_engaged(self) -> None:
        """TNP 6.5: a turn engages then places one new force; flanking only once every
        force of the other seat is placed and engaged, one flanking force behind a force."""
        engine, match = stage(
            {"mercenary": 1, "worker": 1, "tank": 1, "jeep": 1}, {"mercenary": 1, "worker": 1, "cyborg_soldier": 1},
        )
        # The Jeep's Scouting 1: Green, without the advantage, places one first.
        place(engine, match, "green:mercenary", "column:0")
        place(engine, match, "blue:mercenary", "engage:0")
        prompt = asked(engine, match)
        self.assertEqual(prompt.asked_seat, "blue")
        self.assertEqual(options_for(prompt, "blue:worker").slots, ("column:0", "column:1"))
        place(engine, match, "blue:worker", "column:1")
        prompt = asked(engine, match)
        self.assertEqual(prompt.asked_seat, "green")
        self.assertEqual(options_for(prompt, "green:worker").slots, ("engage:1",))
        place(engine, match, "green:worker", "engage:1")
        place(engine, match, "green:cyborg_soldier", "column:2")
        place(engine, match, "blue:tank", "engage:2")
        prompt = asked(engine, match)
        self.assertEqual(options_for(prompt, "blue:jeep").slots,
                         ("column:0", "column:1", "column:2", "column:3", "flank:0", "flank:1", "flank:2"))
        place(engine, match, "blue:jeep", "flank:0")
        self.assertIsNot(asked(engine, match).kind, PLACE)

    def test_one_flanking_force_behind_a_force(self) -> None:
        """TNP 6.5: each force has at most one flanking force behind it."""
        engine, match = stage({"mercenary": 1, "worker": 1, "tank": 1}, {"mercenary": 1})
        place(engine, match, "green:mercenary", "column:0")
        place(engine, match, "blue:mercenary", "engage:0")
        place(engine, match, "blue:worker", "flank:0")
        prompt = asked(engine, match)
        self.assertEqual(options_for(prompt, "blue:tank").slots, ("column:0", "column:1"))

    def test_a_base_defense_unit_cannot_flank(self) -> None:
        """TNP 6.5, 7: a Base Defense unit cannot flank."""
        engine, match = stage({"mercenary": 1}, {"smart_mines": 1, "rocket_launcher": 1}, territory="green_base")
        place(engine, match, "green:smart_mines", "column:0")
        place(engine, match, "blue:mercenary", "engage:0")
        prompt = asked(engine, match)
        self.assertEqual(options_for(prompt, "green:rocket_launcher").slots, ("column:0", "column:1"))

    def test_only_unengaged_forces_are_placed_in_later_rounds(self) -> None:
        """TNP 6.5: each round only unengaged forces are placed; a round with none places nothing."""
        engine, match = stage({"mercenary": 1}, {"mercenary": 1})
        place(engine, match, "green:mercenary", "column:0")
        place(engine, match, "blue:mercenary", "engage:0")
        fight_on(engine, match)
        fight_on(engine, match)
        shoot(engine, match, "blue:mercenary", "green:mercenary", rolls=[2])
        shoot(engine, match, "green:mercenary", "blue:mercenary", rolls=[2])
        self.assertEqual(match.battle.round, 2)
        self.assertIs(asked(engine, match).kind, RETREAT)

    def test_a_force_whose_opponent_is_destroyed_is_placed_again(self) -> None:
        """TNP 6.5: later rounds place the forces whose opponent was destroyed."""
        engine, match = stage({"mercenary": 2, "worker": 1}, {"mercenary": 1, "worker": 1})
        place(engine, match, "green:mercenary", "column:0")
        place(engine, match, "blue:mercenary", "engage:0")
        place(engine, match, "blue:worker", "column:1")
        place(engine, match, "green:worker", "engage:1")
        fight_on(engine, match)
        fight_on(engine, match)
        shoot(engine, match, "blue:mercenary", "green:mercenary", rolls=[9, 2])
        shoot(engine, match, "green:mercenary", "blue:mercenary", rolls=[2])
        shoot(engine, match, "blue:worker", "green:worker", rolls=[2])
        shoot(engine, match, "green:worker", "blue:worker", rolls=[2])
        self.assertEqual(match.battle.round, 2)
        prompt = asked(engine, match)
        self.assertEqual((prompt.kind, prompt.asked_seat), (PLACE, "blue"))
        self.assertEqual([one.force for one in prompt.options.forces], ["blue:mercenary"])
        # Green has nothing left to place, so Blue may flank.
        self.assertIn("flank:0", prompt.options.forces[0].slots)


class FlankersTests(unittest.TestCase):
    def _round_two(self, choice=None, forces=None):
        engine, match = stage({"mercenary": 1, "worker": 1}, {"mercenary": 1})
        place(engine, match, "green:mercenary", "column:0")
        place(engine, match, "blue:mercenary", "engage:0")
        place(engine, match, "blue:worker", "flank:0")
        fight_on(engine, match)
        fight_on(engine, match)
        shoot(engine, match, "blue:mercenary", "green:mercenary", rolls=[2])
        shoot(engine, match, "green:mercenary", "blue:mercenary", rolls=[2])
        shoot(engine, match, "blue:worker", "green:mercenary", rolls=[2])
        return engine, match

    def test_a_flanker_is_kept_or_repositioned(self) -> None:
        """TNP 6.5: at a round's start a flanking force stays where it stands, or its seat repositions it."""
        engine, match = self._round_two()
        prompt = asked(engine, match)
        self.assertEqual((prompt.kind, prompt.asked_seat), (PromptKind.REPOSITION_FLANKERS, "blue"))
        self.assertEqual([(one.force, one.behind) for one in prompt.options.flankers],
                         [("blue:worker", "blue:mercenary")])
        play(engine, match, Action(PromptKind.REPOSITION_FLANKERS, "keep"))
        self.assertEqual(locate(match.battle, "blue:worker"), (0, True))
        self.assertIs(asked(engine, match).kind, RETREAT)

    def test_a_repositioned_flanker_is_placed_again(self) -> None:
        engine, match = self._round_two()
        play(engine, match, Action(PromptKind.REPOSITION_FLANKERS, "move", {"forces": ["blue:worker"]}))
        prompt = asked(engine, match)
        self.assertEqual((prompt.kind, [one.force for one in prompt.options.forces]), (PLACE, ["blue:worker"]))
        self.assertIn("column:1", prompt.options.forces[0].slots)
        refused = driver.apply(engine, None, match, Action(PromptKind.REPOSITION_FLANKERS, "keep"))
        self.assertIsInstance(refused, driver.Refusal)

    def test_a_flanker_goes_with_its_force(self) -> None:
        """TNP 6.5: a flanking force behind a force that is placed again is placed again with it."""
        engine, match = stage({"mercenary": 1, "worker": 1, "jeep": 1}, {"mercenary": 1, "cyborg_soldier": 1})
        # Blue's Jeep: Green, without the advantage, places one first.
        place(engine, match, "green:mercenary", "column:0")
        place(engine, match, "blue:mercenary", "engage:0")
        place(engine, match, "blue:jeep", "column:1")
        place(engine, match, "green:cyborg_soldier", "engage:1")
        place(engine, match, "blue:worker", "flank:0")
        fight_on(engine, match)
        fight_on(engine, match)
        shoot(engine, match, "blue:mercenary", "green:mercenary", rolls=[9])
        shoot(engine, match, "blue:jeep", "green:cyborg_soldier", rolls=[2])
        shoot(engine, match, "green:mercenary", "blue:mercenary", rolls=[2])
        shoot(engine, match, "green:cyborg_soldier", "blue:jeep", rolls=[2])
        shoot(engine, match, "blue:worker", "green:cyborg_soldier", rolls=[2])
        self.assertEqual(match.battle.round, 2)
        self.assertIsNone(locate(match.battle, "blue:worker"))
        prompt = asked(engine, match)
        self.assertEqual((prompt.kind, prompt.asked_seat), (PLACE, "blue"))
        self.assertEqual([one.force for one in prompt.options.forces], ["blue:worker", "blue:mercenary"])


class RetreatTests(unittest.TestCase):
    def _placed(self, attacker, defender, **staging):
        engine, match = stage(attacker, defender, **staging)
        while asked(engine, match) is not None and asked(engine, match).kind is PLACE:
            play(engine, match, first(asked(engine, match)))
        return engine, match

    def test_the_attacker_is_asked_first(self) -> None:
        """TNP 6.6: the attacker first; only if it does not retreat is the defender asked."""
        engine, match = self._placed({"mercenary": 1}, {"mercenary": 1})
        self.assertEqual(asked(engine, match).asked_seat, "blue")
        fight_on(engine, match)
        self.assertEqual((asked(engine, match).kind, asked(engine, match).asked_seat), (RETREAT, "green"))

    def test_a_retreat_is_a_defeat_after_the_round(self) -> None:
        """TNP 6.6, 6.10: the retreating seat does not attack this round; the battle ends after it; it lost."""
        engine, match = self._placed({"mercenary": 1}, {"mercenary": 1})
        retreat(engine, match)
        prompt = asked(engine, match)
        self.assertEqual((prompt.kind, prompt.asked_seat), (TARGET, "green"))
        shoot(engine, match, "green:mercenary", "blue:mercenary", rolls=[2])
        outcome = match.battle.outcome
        self.assertEqual((outcome["winner"], outcome["by"], outcome["home"]), ("green", "retreat", []))
        self.assertEqual(outcome["withdrawn"], {"blue": {"mercenary": {"count": 1, "damaged": 0}}})

    def test_the_defender_of_a_base_cannot_retreat(self) -> None:
        """TNP 6.6: the defender of a base cannot retreat."""
        engine, match = self._placed({"mercenary": 1}, {"mercenary": 1}, territory="green_base")
        fight_on(engine, match)
        self.assertIs(asked(engine, match).kind, TARGET)

    def test_with_no_path_home_the_air_units_retreat_and_carry(self) -> None:
        """TNP 6.6, 7: with no path home the air units retreat, the Chopper Carriers carrying
        ground units up to their capacity, and the rest stay and fight; the battle goes on."""
        engine, match = self._placed(
            {"chopper_carrier": 1, "mercenary": 4}, {"mercenary": 1}, paths_home={"blue": False, "green": True},
        )
        prompt = asked(engine, match)
        self.assertEqual(prompt.asked_seat, "blue")
        options = prompt.options
        self.assertEqual((options.path_home, options.air, options.carriers), (False, ("blue:chopper_carrier",), 1))
        self.assertEqual([(one.force, one.count, one.per_carrier) for one in options.carry], [("blue:mercenary", 4, 3)])
        refused = driver.apply(engine, None, match, Action(RETREAT, "retreat", {"carried": {"blue:mercenary": 4}}))
        self.assertEqual(refused.cite, "TNP 7")
        play(engine, match, Action(RETREAT, "retreat", {"carried": {"blue:mercenary": 3}}))
        prompt = asked(engine, match)
        # Green's Mercenary and Blue's share initiative 2: Blue's staying one rolls first, one die.
        self.assertEqual(target_option(prompt, "blue:mercenary", "green:mercenary").dice, 1)
        self.assertNotIn("blue:chopper_carrier", [one.force for one in prompt.options.forces])
        shoot(engine, match, "blue:mercenary", "green:mercenary", rolls=[2])
        shoot(engine, match, "green:mercenary", "blue:mercenary", rolls=[2])
        battle = match.battle
        self.assertIsNone(battle.outcome)
        self.assertEqual(battle.round, 2)
        self.assertEqual(battle.withdrawn, {"blue": {"chopper_carrier": {"count": 1, "damaged": 0},
                                                     "mercenary": {"count": 3, "damaged": 0}}})
        self.assertEqual([(one.id, one.count) for one in battle.living("blue")], [("blue:mercenary", 1)])
        # The stranded Mercenary cannot retreat now: the defender is asked.
        self.assertEqual(asked(engine, match).asked_seat, "green")

    def test_a_split_forces_hits_come_off_those_staying_first(self) -> None:
        """TNP 6.6: the retreating part of a split force is hit only once every unit it
        was leaving behind is destroyed."""
        engine, match = self._placed(
            {"chopper_carrier": 1, "mercenary": 4}, {"mercenary": 2}, paths_home={"blue": False, "green": True},
        )
        play(engine, match, Action(RETREAT, "retreat", {"carried": {"blue:mercenary": 3}}))
        shoot(engine, match, "blue:mercenary", "green:mercenary", rolls=[2])
        shoot(engine, match, "green:mercenary", "blue:mercenary", rolls=[9, 9])
        battle = match.battle
        # Two hits: the one Mercenary staying, then one of the three carried.
        self.assertEqual(battle.withdrawn["blue"]["mercenary"], {"count": 2, "damaged": 0})
        self.assertEqual(battle.outcome["winner"], "green")

    def test_one_kind_a_carrier(self) -> None:
        """TNP 7: a carrier carries one kind of unit, without mixing."""
        engine, match = self._placed(
            {"chopper_carrier": 1, "mercenary": 1, "tank": 1}, {"mercenary": 1},
            paths_home={"blue": False, "green": True},
        )
        refused = driver.apply(engine, None, match, Action(
            RETREAT, "retreat", {"carried": {"blue:mercenary": 1, "blue:tank": 1}},
        ))
        self.assertEqual(refused.cite, "TNP 7")

    def test_no_path_home_no_retreat_but_air_always(self) -> None:
        """TNP 6.6: a ground force retreats only with a path home; an air force always."""
        engine, match = self._placed({"mercenary": 1}, {"mercenary": 1}, paths_home={"blue": False, "green": True})
        self.assertEqual(asked(engine, match).asked_seat, "green")
        engine, match = self._placed({"viper_spy_plane": 1}, {"mercenary": 1}, paths_home={"blue": False, "green": True})
        self.assertEqual(asked(engine, match).asked_seat, "blue")


class DamageTests(unittest.TestCase):
    def _line(self, attacker, defender, placements, **staging):
        engine, match = stage(attacker, defender, **staging)
        for force, slot in placements:
            place(engine, match, force, slot)
        while asked(engine, match).kind is RETREAT:
            fight_on(engine, match)
        return engine, match

    def test_initiative_groups_lowest_first_attacker_first(self) -> None:
        """TNP 6.7: group 1 before 2, and within a group the attacker's forces first."""
        engine, match = self._line(
            {"mercenary": 1, "stealth_sniper": 1}, {"mercenary": 1, "stealth_sniper": 1},
            [("green:mercenary", "column:0"), ("blue:mercenary", "engage:0"),
             ("blue:stealth_sniper", "column:1"), ("green:stealth_sniper", "engage:1")],
        )
        order = []
        while (prompt := asked(engine, match)) is not None and prompt.kind is TARGET and match.battle.round == 1:
            shooter = prompt.options.forces[0].force
            order.append(shooter)
            shoot(engine, match, shooter, prompt.options.forces[0].targets[0].target, rolls=[2] * 2)
        self.assertEqual(order, ["blue:stealth_sniper", "green:stealth_sniper", "blue:mercenary", "green:mercenary"])

    def test_a_unit_destroyed_by_its_own_group_still_shoots(self) -> None:
        """TNP 6.7: the group's losses come off only when the whole group has rolled."""
        engine, match = self._line(
            {"mercenary": 1}, {"mercenary": 1},
            [("green:mercenary", "column:0"), ("blue:mercenary", "engage:0")],
        )
        shoot(engine, match, "blue:mercenary", "green:mercenary", rolls=[9])
        prompt = asked(engine, match)
        self.assertEqual((prompt.kind, prompt.asked_seat), (TARGET, "green"))
        shoot(engine, match, "green:mercenary", "blue:mercenary", rolls=[9])
        # TNP 6.10: neither side has a unit left; nobody wins, and the territory stays as it was.
        self.assertEqual(match.battle.outcome["winner"], None)
        self.assertEqual(match.battle.outcome["control"], "green")

    def test_a_unit_destroyed_by_an_earlier_group_does_not(self) -> None:
        """TNP 6.7: a unit destroyed by an earlier group does not shoot."""
        engine, match = self._line(
            {"stealth_sniper": 1}, {"mercenary": 1},
            [("green:mercenary", "column:0"), ("blue:stealth_sniper", "engage:0")],
        )
        shoot(engine, match, "blue:stealth_sniper", "green:mercenary", rolls=[3])
        self.assertEqual(match.battle.outcome["winner"], "blue")

    def test_the_d12_numbers(self) -> None:
        """TNP 4.1, 4.2: Strong 3, Fair 6, Weak and Poor 12; a 12 always hits and a 1 always misses; no cap."""
        self.assertEqual([Rating(name).target for name in ("strong", "fair", "weak", "poor")], [3, 6, 12, 12])
        self.assertTrue(RulesEngine.hits(12, -20, Rating.STRONG))
        self.assertFalse(RulesEngine.hits(1, 20, Rating.WEAK))
        self.assertTrue(RulesEngine.hits(4, 2, Rating.FAIR))
        self.assertTrue(RulesEngine.hits(2, 10, Rating.WEAK))
        self.assertFalse(RulesEngine.hits(11, 0, Rating.WEAK))

    def test_poor_rolls_a_die_for_every_two(self) -> None:
        """TNP 4.3: Poor rolls one die for every two units, rounded down; a lone Poor unit rolls none."""
        engine, match = self._line(
            {"jeep": 3}, {"viper_spy_plane": 1},
            # The Viper's Scouting 4 to the Jeeps' 3: Blue, without the advantage, places first.
            [("blue:jeep", "column:0"), ("green:viper_spy_plane", "engage:0")],
        )
        self.assertEqual(Rating.POOR.dice(1), 0)
        self.assertEqual(Rating.POOR.dice(3), 1)
        prompt = asked(engine, match)
        self.assertEqual(prompt.asked_seat, "green")  # the Viper's group, 1, rolls first
        shoot(engine, match, "green:viper_spy_plane", "blue:jeep", rolls=[2])
        prompt = asked(engine, match)
        self.assertEqual(target_option(prompt, "blue:jeep", "green:viper_spy_plane").dice, 1)
        run = shoot(engine, match, "blue:jeep", "green:viper_spy_plane", rolls=[12])
        self.assertEqual(run.rolls[0].dice, (12,))

    def test_a_lone_poor_unit_is_not_asked(self) -> None:
        """TNP 4.3: a lone Poor unit rolls no die, so nobody is asked to roll it."""
        engine, match = self._line(
            {"jeep": 1}, {"viper_spy_plane": 1},
            [("blue:jeep", "column:0"), ("green:viper_spy_plane", "engage:0")],
        )
        shoot(engine, match, "green:viper_spy_plane", "blue:jeep", rolls=[2])
        self.assertNotEqual(asked(engine, match).kind, TARGET)

    def test_a_target_with_no_die_is_not_offered(self) -> None:
        """TNP 4.3: a lone Poor unit rolls no die at its Poor type, so that target is not offered."""
        engine, match = self._line(
            {"jeep": 1}, {"viper_spy_plane": 1, "mercenary": 1},
            [("blue:jeep", "column:0"), ("green:viper_spy_plane", "engage:0"),
             ("green:mercenary", "column:1")],
        )
        shoot(engine, match, "green:viper_spy_plane", "blue:jeep", rolls=[2])
        prompt = asked(engine, match)
        self.assertEqual([one.target for one in options_for(prompt, "blue:jeep").targets], ["green:mercenary"])

    def test_flanking_and_the_position_modifier(self) -> None:
        """TNP 6.5, 6.7: flanking +1; −1 a column for an engaged force; none for an unengaged one."""
        engine, match = self._line(
            {"mercenary": 1, "jeep": 1, "worker": 1}, {"mercenary": 1, "worker": 1},
            [("green:mercenary", "column:0"), ("blue:jeep", "engage:0"),
             ("blue:mercenary", "column:1"), ("green:worker", "engage:1"),
             ("blue:worker", "flank:0")],
        )
        prompt = asked(engine, match)
        self.assertEqual(target_option(prompt, "blue:jeep", "green:mercenary").modifier, 0)
        self.assertEqual(target_option(prompt, "blue:jeep", "green:worker").modifier, -1)
        self.assertEqual(target_option(prompt, "blue:mercenary", "green:mercenary").modifier, -1)
        shoot(engine, match, "blue:jeep", "green:mercenary", rolls=[2])
        shoot(engine, match, "blue:mercenary", "green:worker", rolls=[2])
        shoot(engine, match, "green:mercenary", "blue:jeep", rolls=[2])
        prompt = asked(engine, match)
        # TNP 6.5: a flanking force at +1 in its own column, with none one column away.
        self.assertEqual(target_option(prompt, "blue:worker", "green:mercenary").modifier, 1)
        self.assertEqual(target_option(prompt, "blue:worker", "green:worker").modifier, 0)

    def test_a_flanker_two_columns_away(self) -> None:
        """TNP 6.5: a flanking force attacks two columns away at −2."""
        engine, match = self._line(
            {"mercenary": 1, "worker": 1, "jeep": 1, "tank": 1},
            {"mercenary": 1, "worker": 1, "jeep": 1},
            [("green:mercenary", "column:0"), ("blue:mercenary", "engage:0"),
             ("blue:worker", "column:1"), ("green:worker", "engage:1"),
             ("green:jeep", "column:2"), ("blue:jeep", "engage:2"), ("blue:tank", "flank:0")],
        )
        while (prompt := asked(engine, match)).asked_seat != "blue" or prompt.options.group != 3:
            shooter = prompt.options.forces[0]
            shoot(engine, match, shooter.force, shooter.targets[0].target, rolls=[2])
        self.assertEqual(target_option(prompt, "blue:tank", "green:mercenary").modifier, 1)
        self.assertEqual(target_option(prompt, "blue:tank", "green:worker").modifier, 0)
        self.assertEqual(target_option(prompt, "blue:tank", "green:jeep").modifier, -2)

    def test_outside_modifiers_add(self) -> None:
        """TNP 4.2: modifiers handed in from outside (step 9's cards) add to the roll."""
        engine, match = self._line(
            {"mercenary": 1}, {"tank": 1},
            [("green:tank", "column:0"), ("blue:mercenary", "engage:0")],
            modifiers=({"seat": "blue", "against": "armored", "value": 4},),
        )
        prompt = asked(engine, match)
        self.assertEqual(target_option(prompt, "blue:mercenary", "green:tank").modifier, 4)


class HitsTests(unittest.TestCase):
    def test_tough_takes_two_hits_damaged_first(self) -> None:
        """TNP 6.8: a Tough unit takes two hits, and a damaged one always takes a hit first."""
        engine, match = stage({"cyborg_soldier": 2}, {"cyborg_soldier": 2}, damaged={"green": {"cyborg_soldier": 1}})
        place(engine, match, "green:cyborg_soldier", "column:0")
        place(engine, match, "blue:cyborg_soldier", "engage:0")
        fight_on(engine, match)
        fight_on(engine, match)
        shoot(engine, match, "blue:cyborg_soldier", "green:cyborg_soldier", rolls=[9, 2])
        shoot(engine, match, "green:cyborg_soldier", "blue:cyborg_soldier", rolls=[9, 2])
        green, blue = match.battle.force("green:cyborg_soldier"), match.battle.force("blue:cyborg_soldier")
        self.assertEqual((green.count, green.damaged), (1, 0))
        self.assertEqual((blue.count, blue.damaged), (2, 1))

    def test_repair_gives_a_worker_to_ignore_a_hit(self) -> None:
        """TNP 6.8: a Mechanical unit hit, its seat may remove a Worker from an adjacent force to ignore the hit."""
        engine, match = stage({"tank": 1, "worker": 2}, {"cyborg_soldier": 1})
        place(engine, match, "green:cyborg_soldier", "column:0")
        place(engine, match, "blue:tank", "engage:0")
        place(engine, match, "blue:worker", "flank:0")
        fight_on(engine, match)
        fight_on(engine, match)
        shoot(engine, match, "blue:tank", "green:cyborg_soldier", rolls=[2])
        shoot(engine, match, "green:cyborg_soldier", "blue:tank", rolls=[9])
        prompt = asked(engine, match)
        self.assertEqual((prompt.kind, prompt.asked_seat), (PromptKind.REPAIR, "blue"))
        self.assertEqual(prompt.options.hits, 1)
        self.assertEqual([(one.force, one.available) for one in prompt.options.workers], [("blue:worker", 2)])
        play(engine, match, Action(PromptKind.REPAIR, "repair", {"workers": {"blue:worker": 1}}))
        tank, workers = match.battle.force("blue:tank"), match.battle.force("blue:worker")
        self.assertEqual((tank.count, tank.damaged, workers.count), (1, 0, 1))

    def test_adjacent_is_the_same_or_a_neighbouring_column(self) -> None:
        """TNP 6.5, 6.8: a flanking force is in its force's column, adjacent to it and to
        whatever it is adjacent to; adjacent means the same column or a neighbouring one."""
        engine, match = stage(
            {"mercenary": 1, "worker": 1, "jeep": 1, "tank": 1, "cyborg_soldier": 1},
            {"mercenary": 1, "worker": 1, "jeep": 1},
        )
        for force, slot in [
            ("green:mercenary", "column:0"), ("blue:mercenary", "engage:0"),
            ("blue:worker", "column:1"), ("green:worker", "engage:1"),
            ("green:jeep", "column:2"), ("blue:jeep", "engage:2"),
            ("blue:tank", "flank:0"), ("blue:cyborg_soldier", "flank:1"),
        ]:
            place(engine, match, force, slot)
        battle = match.battle
        self.assertTrue(adjacent(battle, "blue:mercenary", "blue:worker"))
        self.assertFalse(adjacent(battle, "blue:mercenary", "blue:jeep"))
        self.assertTrue(adjacent(battle, "blue:tank", "blue:mercenary"))
        self.assertTrue(adjacent(battle, "blue:tank", "blue:worker"))
        self.assertFalse(adjacent(battle, "blue:tank", "blue:jeep"))
        self.assertTrue(adjacent(battle, "blue:tank", "blue:cyborg_soldier"))
        self.assertTrue(adjacent(battle, "blue:cyborg_soldier", "blue:jeep"))
        self.assertFalse(adjacent(battle, "blue:mercenary", "green:mercenary"))
        self.assertEqual(locate(battle, "blue:tank"), (0, True))

    def test_splash_takes_an_adjacent_infantry_unit(self) -> None:
        """TNP 6.8: a Splash force that hits may also remove an infantry unit from an adjacent force."""
        engine, match = stage({"tank": 1, "mercenary": 1}, {"mercenary": 1, "cyborg_soldier": 1})
        place(engine, match, "green:mercenary", "column:0")
        place(engine, match, "blue:tank", "engage:0")
        place(engine, match, "blue:mercenary", "column:1")
        place(engine, match, "green:cyborg_soldier", "engage:1")
        fight_on(engine, match)
        fight_on(engine, match)
        shoot(engine, match, "blue:mercenary", "green:cyborg_soldier", rolls=[2])
        shoot(engine, match, "green:mercenary", "blue:tank", rolls=[2])
        shoot(engine, match, "blue:tank", "green:mercenary", rolls=[6])
        prompt = asked(engine, match)
        self.assertEqual((prompt.kind, prompt.options.forces), (PromptKind.SPLASH, ("green:cyborg_soldier",)))
        play(engine, match, Action(PromptKind.SPLASH, "splash", {"force": "green:cyborg_soldier"}))
        shoot(engine, match, "green:cyborg_soldier", "blue:tank", rolls=[2])
        # Tough or not, the splashed Cyborg is removed.
        self.assertEqual(match.battle.outcome["winner"], "blue")


class SplashDamagedFirstTests(unittest.TestCase):
    def test_splash_takes_a_damaged_unit_first(self) -> None:
        """TNP 6.8: Splash removes a damaged unit first."""
        engine, match = stage(
            {"tank": 1, "mercenary": 1}, {"mercenary": 1, "cyborg_soldier": 2},
            damaged={"green": {"cyborg_soldier": 1}},
        )
        place(engine, match, "green:mercenary", "column:0")
        place(engine, match, "blue:tank", "engage:0")
        place(engine, match, "blue:mercenary", "column:1")
        place(engine, match, "green:cyborg_soldier", "engage:1")
        fight_on(engine, match)
        fight_on(engine, match)
        shoot(engine, match, "blue:mercenary", "green:cyborg_soldier", rolls=[2])
        shoot(engine, match, "green:mercenary", "blue:tank", rolls=[2])
        shoot(engine, match, "blue:tank", "green:mercenary", rolls=[6])
        play(engine, match, Action(PromptKind.SPLASH, "splash", {"force": "green:cyborg_soldier"}))
        shoot(engine, match, "green:cyborg_soldier", "blue:tank", rolls=[2, 2])
        cyborgs = match.battle.force("green:cyborg_soldier")
        self.assertEqual((cyborgs.count, cyborgs.damaged), (1, 0))


class BaseTests(unittest.TestCase):
    STRUCTURES = {
        "facilities": ["barracks", "factory", "airport", "base_defenses"],
        "upgrades": ["factory_upgrade", "robotic_facility"],
    }

    def _at_base(self, attacker, defender, **staging):
        staging.setdefault("structures", self.STRUCTURES)
        engine, match = stage(attacker, defender, territory="green_base", **staging)
        while (prompt := asked(engine, match)) is not None and prompt.kind is PLACE:
            play(engine, match, first(prompt))
        while (prompt := asked(engine, match)) is not None and prompt.kind is RETREAT:
            fight_on(engine, match)
        return engine, match

    def test_base_cards_are_armored_and_at_least_minus_one(self) -> None:
        """TNP 6.9: a base card at each end, attacked with the armored rating, every force at least −1."""
        engine, match = self._at_base({"cyborg_soldier": 2}, {"tank": 1})
        prompt = asked(engine, match)
        left = target_option(prompt, "blue:cyborg_soldier", "base_left")
        right = target_option(prompt, "blue:cyborg_soldier", "base_right")
        self.assertEqual((left.type, left.needed, left.modifier), ("armored", 3, -1))
        self.assertEqual((right.type, right.needed, right.modifier), ("armored", 3, -1))

    def test_every_force_is_minus_one_a_column(self) -> None:
        """TNP 6.7, 6.9: any force takes −1 a column, engaged, alone or flanking, to a force
        or to a base card's place beyond the end of the line; a flanker's +1 is its own
        column's force's alone."""
        engine, match = stage(
            {"mercenary": 1, "jeep": 1, "cyborg_soldier": 1}, {"mercenary": 1},
            territory="green_base", structures=self.STRUCTURES,
        )
        place(engine, match, "green:mercenary", "column:0")
        place(engine, match, "blue:mercenary", "engage:0")
        place(engine, match, "blue:jeep", "column:1")
        place(engine, match, "blue:cyborg_soldier", "flank:0")
        while (prompt := asked(engine, match)).kind is RETREAT:
            fight_on(engine, match)
        # The line: column 0 the Mercenaries, Blue's Cyborgs behind; column 1 Blue's Jeep alone.
        self.assertEqual(target_option(prompt, "blue:jeep", "green:mercenary").modifier, -1)
        self.assertEqual(target_option(prompt, "blue:jeep", "base_left").modifier, -2)
        self.assertEqual(target_option(prompt, "blue:jeep", "base_right").modifier, -1)
        self.assertEqual(target_option(prompt, "blue:mercenary", "base_right").modifier, -2)
        shoot(engine, match, "blue:mercenary", "green:mercenary", rolls=[2])
        shoot(engine, match, "blue:jeep", "green:mercenary", rolls=[2])
        shoot(engine, match, "green:mercenary", "blue:mercenary", rolls=[2])
        prompt = asked(engine, match)
        self.assertEqual(target_option(prompt, "blue:cyborg_soldier", "green:mercenary").modifier, 1)
        self.assertEqual(target_option(prompt, "blue:cyborg_soldier", "base_left").modifier, -1)
        self.assertEqual(target_option(prompt, "blue:cyborg_soldier", "base_right").modifier, -2)

    def test_two_hits_destroy_one_thing_an_attack(self) -> None:
        """TNP 6.9: 2 hits destroy one thing, the attacker's choice -- an upgrade before its facility,
        never the Barracks or Base Defenses -- and one thing an attack."""
        engine, match = self._at_base({"cyborg_soldier": 2}, {"tank": 1})
        shoot(engine, match, "blue:cyborg_soldier", "base_left", rolls=[12, 12])
        prompt = asked(engine, match)
        self.assertEqual(prompt.kind, PromptKind.DESTROY)
        self.assertEqual(prompt.options.things, ("factory_upgrade", "robotic_facility", "airport"))
        refused = driver.apply(engine, None, match, Action(PromptKind.DESTROY, "", {"thing": "factory"}))
        self.assertEqual(refused.cite, "TNP 6.9")
        play(engine, match, Action(PromptKind.DESTROY, "", {"thing": "airport"}))
        self.assertEqual(match.battle.destroyed, "airport")
        self.assertNotIn("airport", match.battle.structures["facilities"])
        shoot(engine, match, "green:tank", "blue:cyborg_soldier", rolls=[2])
        while (prompt := asked(engine, match)) is not None and prompt.kind is RETREAT:
            fight_on(engine, match)
        shoot(engine, match, "blue:cyborg_soldier", "base_left", rolls=[12, 12])
        self.assertNotEqual(asked(engine, match).kind, PromptKind.DESTROY)

    def test_base_defense_units_roll(self) -> None:
        """TNP 6.9, 7: Base Defense units roll like any other unit when their base is attacked."""
        engine, match = self._at_base({"mercenary": 1}, {"smart_mines": 1})
        prompt = asked(engine, match)
        self.assertEqual((prompt.asked_seat, prompt.options.forces[0].force), ("green", "green:smart_mines"))

    def test_an_undefended_base_falls(self) -> None:
        """TNP 1.3, 6.1: an attack on an undefended base succeeds at once."""
        engine, match = stage({"mercenary": 1}, {}, territory="green_base", structures=self.STRUCTURES)
        outcome = match.battle.outcome
        self.assertEqual((outcome["winner"], outcome["base_fallen"], outcome["by"]), ("blue", True, "undefended"))

    def test_six_rounds_and_the_defender_holds(self) -> None:
        """TNP 6.10: after six rounds the defender wins if it still has units, whatever the base cards took."""
        engine, match = self._at_base({"mercenary": 1}, {"mercenary": 1})
        with scripted(engine, itertools.repeat(2)):
            runs = fight(engine, match)
        outcome = match.battle.outcome
        self.assertEqual((outcome["winner"], outcome["by"], match.battle.round), ("green", "held", 6))
        self.assertFalse(outcome["base_fallen"])
        self.assertIn("Green holds for 6 rounds.", words(engine, runs))


class EmergencyTests(unittest.TestCase):
    STRUCTURES = {"facilities": ["barracks", "base_defenses"], "upgrades": []}

    def _staged(self, defender, pool, room=None, upgrades=()):
        structures = {"facilities": ["barracks", "base_defenses"], "upgrades": list(upgrades)}
        room = room if room is not None else {"smart_mines": 8, "rocket_launcher": 8, "laser_cannon": 6}
        return stage(
            {"mercenary": 1}, defender, territory="green_base", structures=structures,
            emergency={"pool": pool, "supply_room": room},
        )

    def test_emergency_defenses_join_at_once(self) -> None:
        """TNP 6.2: the defender of a base trades at the emergency rates; the units join at once."""
        engine, match = self._staged({}, {"materials": 1, "blue": 1, "gems": 1})
        prompt = asked(engine, match)
        self.assertEqual((prompt.kind, prompt.options.cap), (PromptKind.EMERGENCY_DEFENSE, 4))
        lasers = next(one for one in prompt.options.units if one.unit == "laser_cannon")
        self.assertEqual(lasers.most, 0)
        play(engine, match, Action(PromptKind.EMERGENCY_DEFENSE, "build",
                                   {"units": {"smart_mines": 1}, "trade": {"blue": 1}}))
        battle = match.battle
        self.assertEqual(battle.force("green:smart_mines").count, 1)
        self.assertEqual(battle.emergency["pool"], {"materials": 0, "gold": 0, "blue": 0, "orange": 0, "gems": 1})
        self.assertEqual(battle.produced, {"smart_mines": 1})
        self.assertIsNone(battle.outcome)

    def test_the_limits(self) -> None:
        """TNP 6.2, 2.4: the cap, the supply, 8 Mines and Rockets together, a Laser Cannon only with its upgrade."""
        engine, match = self._staged({"smart_mines": 7}, {"materials": 20, "gold": 5}, upgrades=["laser_cannon_upgrade"])
        prompt = asked(engine, match)
        self.assertEqual(next(one for one in prompt.options.units if one.unit == "laser_cannon").most, 4)
        self.assertEqual(prompt.options.together[0].room, 1)
        for units, cite in (({"smart_mines": 2}, "TNP 2.4"), ({"laser_cannon": 5}, "TNP 6.2"),
                            ({"laser_cannon": 3, "rocket_launcher": 1, "smart_mines": 1}, "TNP 6.2")):
            refused = driver.apply(engine, None, match, Action(PromptKind.EMERGENCY_DEFENSE, "build", {"units": units}))
            self.assertIsInstance(refused, driver.Refusal, units)
            self.assertEqual(refused.cite, cite, units)

    def test_an_unpaid_emergency_is_refused(self) -> None:
        """TNP 6.2: a mineral is 1 material, never gold."""
        engine, match = self._staged({"mercenary": 1}, {"blue": 1, "gems": 1}, upgrades=["laser_cannon_upgrade"])
        refused = driver.apply(engine, None, match, Action(
            PromptKind.EMERGENCY_DEFENSE, "build", {"units": {"laser_cannon": 1}, "trade": {"gems_materials": 1}},
        ))
        self.assertEqual(refused.cite, "TNP 6.2")
        play(engine, match, Action(
            PromptKind.EMERGENCY_DEFENSE, "build",
            {"units": {"laser_cannon": 1}, "trade": {"blue": 1, "gems_gold": 1}},
        ))
        self.assertEqual(match.battle.force("green:laser_cannon").count, 1)

    def test_nothing_to_spend_asks_nothing(self) -> None:
        """TNP 6.2: a defender who could produce nothing is not asked."""
        engine, match = self._staged({"mercenary": 1}, {})
        self.assertIs(asked(engine, match).kind, PLACE)


class AirTests(unittest.TestCase):
    def _duel(self, attacker, defender, a_roll, d_roll, **staging):
        engine, match = stage(attacker, defender, **staging)
        (a,), (d,) = attacker, defender
        place(engine, match, f"green:{d}", "column:0")
        place(engine, match, f"blue:{a}", "engage:0")
        while asked(engine, match).kind is RETREAT:
            fight_on(engine, match)
        while (prompt := asked(engine, match)) is not None:
            shooter = prompt.options.forces[0].force
            rolls = a_roll if shooter.startswith("blue") else d_roll
            shoot(engine, match, shooter, prompt.options.forces[0].targets[0].target, rolls=rolls)
            if match.battle.outcome is None and asked(engine, match).kind is not TARGET:
                break
        return engine, match

    def test_air_alone_cannot_take_a_territory(self) -> None:
        """TNP 6.11: an attacker that wins with air units alone leaves the territory neutral."""
        engine, match = self._duel({"fighter_bomber": 1}, {"mercenary": 1}, [9], [2])
        self.assertEqual((match.battle.outcome["winner"], match.battle.outcome["control"]), ("blue", None))

    def test_air_keeps_a_territory_already_held(self) -> None:
        """TNP 6.11: a defender that wins with only air units left keeps a territory it held."""
        engine, match = self._duel({"mercenary": 1}, {"fighter_bomber": 1}, [2], [9])
        self.assertEqual((match.battle.outcome["winner"], match.battle.outcome["control"]), ("green", "green"))


class DriverTests(unittest.TestCase):
    def test_every_kind_and_step_is_covered(self) -> None:
        for table in (CHOICES, OPTIONS, driver.ANSWERS, driver.ARGUMENTS, driver.STALE_CLICK):
            self.assertEqual(set(table), set(PromptKind))
        self.assertEqual(set(driver.MODEL_STEPS), set(FollowOnStep))

    def test_every_field_is_saved(self) -> None:
        """The save format is the contract: every field in its table."""
        self.assertEqual({row.name for row in BATTLE_SAVED_FIELDS}, {one.name for one in fields(BattleState)})
        self.assertEqual({row.name for row in MATCH_SAVED_FIELDS}, {one.name for one in fields(MatchState)})

    def test_refusals(self) -> None:
        engine, match = stage({"mercenary": 1}, {"mercenary": 1})
        before = match.to_dict()
        for action in (
            Action(TARGET, "", {"force": "green:mercenary", "target": "blue:mercenary"}),
            Action(PLACE, "nope", {"force": "green:mercenary", "slot": "column:0"}),
            Action(PLACE, "", {"force": "green:mercenary", "slot": "column:0", "extra": 1}),
            Action(PLACE, "", {"force": "green:mercenary", "slot": "flank:0"}),
            Action(PLACE, "", {"force": "blue:mercenary", "slot": "column:0"}),
        ):
            self.assertIsInstance(driver.apply(engine, None, match, action), driver.Refusal, action)
        self.assertEqual(match.to_dict(), before)

    def test_an_owed_step_refuses_and_resumes(self) -> None:
        engine, match = stage({"mercenary": 1}, {"mercenary": 1})
        place(engine, match, "green:mercenary", "column:0")
        place(engine, match, "blue:mercenary", "engage:0")
        fight_on(engine, match)
        fight_on(engine, match)
        shoot(engine, match, "blue:mercenary", "green:mercenary", rolls=[2])
        with scripted(engine, [2]):
            run = driver.apply(
                engine, None, match,
                Action(TARGET, "", {"force": "green:mercenary", "target": "blue:mercenary"}),
                stop_after=[FollowOnStep.CLOSE_GROUP],
            )
        self.assertEqual(run.stopped_on, FollowOn(FollowOnStep.CLOSE_GROUP))
        self.assertIsInstance(pending(engine, None, match), FollowOn)
        refused = driver.apply(engine, None, match, Action(RETREAT, "fight"))
        self.assertEqual(refused.reason, driver.STEP_OWED)
        driver.resume(engine, None, match)
        self.assertIs(asked(engine, match).kind, RETREAT)


class AnyTwoForcesTests(unittest.TestCase):
    """The stop: any two Human forces fought to a result with the seeded rng and a d12."""

    def _random_policy(self, chooser):
        def policy(prompt):
            options = prompt.options
            kind = prompt.kind
            if kind is PromptKind.PLACE_FORCE:
                force = chooser.choice(options.forces)
                return Action(kind, "", {"force": force.force, "slot": chooser.choice(force.slots)})
            if kind is PromptKind.CHOOSE_TARGET:
                shooter = chooser.choice(options.forces)
                return Action(kind, "", {"force": shooter.force, "target": chooser.choice(shooter.targets).target})
            if kind is PromptKind.DECLARE_RETREAT:
                if chooser.random() >= 0.05:
                    return Action(kind, "fight")
                if options.path_home or not options.carry or not options.carriers:
                    return Action(kind, "retreat")
                one = chooser.choice(options.carry)
                return Action(kind, "retreat", {"carried": {
                    one.force: min(one.count, one.per_carrier * options.carriers),
                }})
            if kind is PromptKind.REPAIR:
                worker = options.workers[0]
                return Action(kind, "repair", {"workers": {worker.force: min(worker.available, options.hits)}})
            if kind is PromptKind.SPLASH:
                return Action(kind, "splash", {"force": chooser.choice(options.forces)})
            if kind is PromptKind.DESTROY:
                return Action(kind, "", {"thing": chooser.choice(options.things)})
            if kind is PromptKind.REPOSITION_FLANKERS and chooser.random() < 0.5:
                return Action(kind, "move", {"forces": [options.flankers[0].force]})
            return first(prompt)
        return policy

    def test_every_pair_of_human_units(self) -> None:
        units = [slug for slug, unit in catalog().units.items() if "base_defense" not in unit.traits]
        structures = {"facilities": ["barracks", "factory", "airport", "base_defenses"],
                      "upgrades": ["barracks_upgrade", "airport_upgrade"]}
        outcomes = set()
        for index, (mine, theirs) in enumerate(itertools.product(units, units)):
            chooser = random.Random(index)
            engine, match = stage(
                {mine: 3, "worker": 2, "chopper_carrier": 1}, {theirs: 2, "tank": 1}, seed=index,
                paths_home={"blue": index % 2 == 0, "green": True},
            )
            fight(engine, match, self._random_policy(chooser))
            json.dumps(match.to_dict())
            outcomes.add(match.battle.outcome["by"])
            engine, match = stage(
                {mine: 4}, {theirs: 2, "smart_mines": 1, "rocket_launcher": 1},
                territory="green_base", seed=index, structures=structures,
            )
            fight(engine, match, self._random_policy(chooser))
            self.assertIsNotNone(match.battle.outcome)
        self.assertTrue({"destroyed", "held"} <= outcomes, outcomes)

    def test_a_restart_mid_round_changes_nothing(self) -> None:
        """A battle saved and loaded mid-round fights on exactly as it would have."""
        def run(cut):
            engine, match = stage({"tank": 2, "worker": 2, "jeep": 1}, {"mercenary": 3, "cyborg_soldier": 2}, seed=11)
            for count in itertools.count():
                prompt = asked(engine, match)
                if prompt is None:
                    break
                if count == cut:
                    state = engine.rng.getstate()
                    match = MatchState.from_dict(json.loads(json.dumps(match.to_dict())))
                    engine = RulesEngine(rng=random.Random())
                    engine.rng.setstate(state)
                    prompt = asked(engine, match)
                play(engine, match, first(prompt))
            return match.to_dict()

        self.assertEqual(run(cut=-1), run(cut=9))

    def test_every_prompt_goes_on_the_wire(self) -> None:
        engine, match = stage({"tank": 2, "worker": 2}, {"mercenary": 3}, seed=3)
        while (prompt := asked(engine, match)) is not None:
            json.dumps(prompt.to_dict())
            json.dumps(play(engine, match, first(prompt)).result.to_dict())


if __name__ == "__main__":
    unittest.main()
