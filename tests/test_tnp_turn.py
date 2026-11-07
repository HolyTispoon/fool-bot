"""
TNP's turn (docs/tnp-rules.md, 1 to 5) through `tnp.flow.driver`, one
rule at a time: the opening position, the two simultaneous phases and
their lock-ins, the plan's checks, the reveal, March's order, neutral
conquest, battles put on the map, the Stranded tokens, the harvest,
production, the trade, Cleanup and the 51% count -- and the record, the
service and the games file around them. Each test cites the section it
holds the code to. The whole games are `test_tnp_driver_full_game.py`'s.
"""

from __future__ import annotations

import json
import logging
import random
import tempfile
import unittest
from dataclasses import fields
from pathlib import Path

from gamesaves.tnp import storage
from gamesaves.tnp.service import GameService
from tnp.battle import BattleState
from tnp.components import (
    AREA_SAVED_FIELDS,
    MARCH,
    MATCH_SAVED_FIELDS,
    PLAN,
    SEAT_SAVED_FIELDS,
    TRADE,
    WON_BY_HARVEST,
    AreaState,
    MatchState,
    SeatState,
)
from tnp.engine import RulesEngine
from tnp.flow import driver
from tnp.flow.result import FollowOn, FollowOnStep
from tnp.game import GAME_SAVED_FIELDS, GameStatus, RuleRefusal, TnpGame
from tnp.prompts import (
    Action,
    PromptKind,
    SeveralAsked,
    pending,
    pending_all,
    pending_prompts,
    prompt_for,
)
from tnp.briefs import (
    FACE_DOWN, SHOWN, STRANDED, board_brief, deployment_brief, map_brief, opening_board, opening_map, spots_brief,
)
from tnp.tokens import plain
from tnp.components import Pile
from tnp.turn import has_path, joined, stranded_areas

from tnp_battles import first
from tnp_games import Strategy, opening, reload

PLAN_KIND = PromptKind.PLAN
TRADE_KIND = PromptKind.TRADE


def lock(engine, game, match, seat, plan=None):
    arguments = {} if plan is None else {"plan": plan}
    return driver.apply(engine, game, match, Action(PLAN_KIND, "lock", arguments, seat=seat))


def save(engine, game, match, seat, plan):
    return driver.apply(engine, game, match, Action(PLAN_KIND, "save", {"plan": plan}, seat=seat))


def words(engine, run) -> str:
    return " ".join(plain(line, engine.catalog) for line in run.narration if line)


def answered(engine, game, match, run, limit=500):
    """Answer every battle question with `tnp_battles.first`, and every
    conquest with the first unit, until the match asks a plan or a
    trade again; every line said."""
    said = [words(engine, run)]
    for _ in range(limit):
        prompts = pending_prompts(engine, game, match)
        if not prompts or prompts[0].kind in (PLAN_KIND, TRADE_KIND) or match.winner:
            return " ".join(said)
        prompt = prompts[0]
        if prompt.kind is PromptKind.CONQUER:
            action = Action(PromptKind.CONQUER, "", {"unit": prompt.options.units[0]}, seat=prompt.asked_seat)
        elif prompt.kind is PromptKind.HARVEST:
            action = Action(PromptKind.HARVEST, "", {"tokens": Strategy().harvest(prompt.options)},
                            seat=prompt.asked_seat)
        else:
            action = first(prompt)
        run = driver.apply(engine, game, match, action)
        assert not isinstance(run, driver.Refusal), run
        said.append(words(engine, run))
    raise AssertionError("March did not end")


def both_lock(engine, game, match, blue=None, green=None) -> str:
    """Both seats lock in these plans, and March is played out."""
    assert not isinstance(lock(engine, game, match, "blue", blue), driver.Refusal)
    run = lock(engine, game, match, "green", green)
    assert not isinstance(run, driver.Refusal), run
    return answered(engine, game, match, run)


def hold(match, seat, *areas) -> None:
    for area in areas:
        match.areas[area].controller = seat


class OpeningTests(unittest.TestCase):
    def test_the_opening_position(self) -> None:
        """TNP 3: every territory neutral with its tokens, 3 Workers, 3
        Mercenaries and 5 materials a seat, the Barracks and Base
        Defenses built."""
        engine, game, match = opening()
        self.assertEqual((match.turn, match.phase), (1, PLAN))
        self.assertEqual(sum(area.tokens_left() for area in match.areas.values()), 96)
        for slug, area in match.areas.items():
            expected = engine.catalog.areas[slug].seat
            self.assertEqual(area.controller, expected, slug)
        for seat in ("blue", "green"):
            state = match.seat(seat)
            self.assertEqual(state.available, {"worker": 3, "mercenary": 3})
            self.assertEqual(state.pool["materials"], 5)
            self.assertEqual(state.pool["gold"], 0)
            self.assertEqual(sorted(state.built), ["barracks", "base_defenses"])
            self.assertEqual(state.faction, "humans")

    def test_both_seats_are_asked_at_once(self) -> None:
        """TNP 5.1, decision 7: Infrastructure and Deployment asks both
        seats; `pending` has no one question then."""
        engine, game, match = opening()
        prompts = pending_prompts(engine, game, match)
        self.assertEqual([(one.kind, one.asked_seat) for one in prompts],
                         [(PLAN_KIND, "blue"), (PLAN_KIND, "green")])
        with self.assertRaises(SeveralAsked):
            pending(engine, game, match)
        self.assertEqual(prompt_for(engine, game, match, "green").asked_seat, "green")


class BriefTests(unittest.TestCase):
    def test_the_briefs_of_the_opening_match_are_the_opening_briefs(self) -> None:
        engine, game, match = opening()
        self.assertEqual(map_brief(match), opening_map(engine.catalog))
        for seat in ("blue", "green"):
            self.assertEqual(board_brief(engine, match, seat), opening_board(engine.catalog, seat))

    def test_the_map_shows_no_plan(self) -> None:
        """TNP 5.3: the public map holds nothing of a deployment before
        March reveals it; the seat's own board shows its saved queue."""
        engine, game, match = opening()
        plan = {"build": {"worker": 4}, "attacks": {"A": {"target": "14", "units": {"worker": 3}}}}
        save(engine, game, match, "blue", plan)
        self.assertEqual(map_brief(match), opening_map(engine.catalog))
        self.assertEqual(board_brief(engine, match, "blue").queued_units, {"worker": 4})
        self.assertEqual(board_brief(engine, match, "green").queued_units, {})


class DeploymentBriefTests(unittest.TestCase):
    """The seat's own attack board, and both deployment boards as
    everybody sees them in March (TNP 2.5, 5.3, 5.4)."""

    def setUp(self) -> None:
        self.engine, self.game, self.match = opening()

    def test_the_seat_s_own_board_is_its_saved_plan(self) -> None:
        hold(self.match, "blue", "14", "13")
        save(self.engine, self.game, self.match, "blue", {
            "build": {"worker": 2},
            "attacks": {"A": {"target": "10", "units": {"worker": 2}}},
            "defense": {"14": {"mercenary": 1}, "13": {"mercenary": 1}, "blue_base": {"mercenary": 1}},
        })
        brief = deployment_brief(self.engine, self.match, "blue", picked="A")
        self.assertEqual([(one.spot, one.area) for one in brief.attacks], [("A", "10"), ("B", None)])
        self.assertEqual([(one.spot, one.area) for one in brief.defenses], [("1", "13"), ("2", "14"), ("3", None)])
        self.assertEqual(brief.base.units, {"mercenary": 1})
        self.assertEqual(brief.at_base, {"worker": 1})
        self.assertEqual(brief.queued, {"worker": 2})
        # The pool on the player board goes down as the plan is changed.
        self.assertEqual(board_brief(self.engine, self.match, "blue").pool["materials"], 5 - 2)

    def test_the_public_boards_show_a_face_down_pile_and_nothing_of_it(self) -> None:
        lock(self.engine, self.game, self.match, "blue", {
            "attacks": {"A": {"target": "14", "units": {"worker": 1, "mercenary": 1}},
                        "B": {"target": "13", "units": {"mercenary": 1}}},
            "defense": {"blue_base": {"mercenary": 1}},
        })
        lock(self.engine, self.game, self.match, "green", {
            "attacks": {"A": {"target": "15", "units": {"worker": 3}}},
            "defense": {"green_base": {"mercenary": 3}},
        })
        # March waits on Blue's conquest at 14: nothing is shown yet.
        boards = dict(spots_brief(self.engine, self.match).seats)
        blue = {one.spot: one for one in boards["blue"]}
        self.assertEqual([blue[spot].state for spot in ("A", "B", "1", "base")],
                         [FACE_DOWN, FACE_DOWN, "empty", FACE_DOWN])
        for one in (*boards["blue"], *boards["green"]):
            if one.state == FACE_DOWN:
                # The base's spot is the base's; any other face-down pile
                # says nothing of where it is.
                self.assertTrue(one.spot == "base" or one.area is None)
                self.assertFalse(one.units)
        answered(self.engine, self.game, self.match,
                 driver.apply(self.engine, self.game, self.match,
                              Action(PromptKind.CONQUER, "", {"unit": "worker"}, seat="blue")))


class SimultaneousPhaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine, self.game, self.match = opening()

    def test_an_answer_names_its_seat(self) -> None:
        run = driver.apply(self.engine, self.game, self.match, Action(PLAN_KIND, "lock"))
        self.assertIsInstance(run, driver.Refusal)

    def test_a_save_says_nothing_and_survives_a_restart(self) -> None:
        """Decision 7: a seat changes its plan until it locks in, and the
        plan is held on the match, so a restart keeps it."""
        plan = {"build": {"worker": 2}, "attacks": {"A": {"target": "14", "units": {"worker": 3}}}}
        run = save(self.engine, self.game, self.match, "blue", plan)
        self.assertEqual(run.narration, ())
        self.assertFalse(self.match.seat("blue").locked)
        again = reload(self.match)
        options = prompt_for(self.engine, self.game, again, "blue").options
        self.assertEqual(options.plan["build"], {"worker": 2})
        self.assertEqual(options.plan["attacks"]["A"]["target"], "14")
        self.assertIsNone(prompt_for(self.engine, self.game, again, "green").options.plan)
        changed = save(self.engine, self.game, again, "blue", {"build": {"mercenary": 1}})
        self.assertNotIsInstance(changed, driver.Refusal)
        self.assertEqual(again.seat("blue").plan["build"], {"mercenary": 1})
        lock(self.engine, self.game, again, "blue")
        self.assertTrue(again.seat("blue").locked)
        self.assertEqual(again.seat("blue").plan["build"], {"mercenary": 1})

    def test_a_locked_seat_is_asked_nothing_more(self) -> None:
        run = lock(self.engine, self.game, self.match, "blue")
        self.assertIn("Blue locks in.", words(self.engine, run))
        self.assertEqual([one.asked_seat for one in pending_prompts(self.engine, self.game, self.match)], ["green"])
        again = save(self.engine, self.game, self.match, "blue", {"build": {"worker": 1}})
        self.assertIsInstance(again, driver.Refusal)

    def test_the_phase_moves_on_once_both_have_locked_in(self) -> None:
        lock(self.engine, self.game, self.match, "blue")
        run = lock(self.engine, self.game, self.match, "green")
        # With nothing planned and nothing to trade, the whole turn runs.
        self.assertEqual(run.steps[:2], (FollowOnStep.REVEAL, FollowOnStep.MARCH))
        self.assertEqual((self.match.turn, self.match.phase), (2, PLAN))

    def test_the_reveal_names_no_unit(self) -> None:
        """TNP 5.2, 5.3: nothing a seat plans is said before March."""
        lock(self.engine, self.game, self.match, "blue", {"build": {"worker": 4}, "defense": {"blue_base": {"mercenary": 3}}})
        run = driver.apply(self.engine, self.game, self.match, Action(
            PLAN_KIND, "lock", {"plan": {"build": {"mercenary": 2}}}, seat="green"))
        head = " ".join(run.narration).split("March begins.")[0]
        self.assertNotIn("{unit:", head)
        self.assertIn("{seat:blue} spends 4 materials.", head)
        # Built this turn, ready the next (TNP 5.9); the defenders back
        # at Cleanup (TNP 5.10).
        self.assertEqual(self.match.seat("blue").available, {"worker": 7, "mercenary": 3})
        self.assertEqual(self.match.seat("green").available, {"worker": 3, "mercenary": 5})


class PlanCheckTests(unittest.TestCase):
    """TNP 2.4, 2.5, 5.2, 5.3: each refused with its section, and a
    refusal changes nothing."""

    def setUp(self) -> None:
        self.engine, self.game, self.match = opening()

    def refused(self, plan, cite):
        before = self.match.to_dict()
        run = save(self.engine, self.game, self.match, "blue", plan)
        self.assertIsInstance(run, driver.Refusal, plan)
        self.assertEqual(run.cite, cite, run.reason)
        self.assertEqual(self.match.to_dict(), before)
        return run

    def test_infrastructure(self) -> None:
        self.refused({"build": {"tank": 1}}, "TNP 5.2")
        self.refused({"build": {"stealth_sniper": 1}}, "TNP 5.2")
        self.refused({"build": {"worker": 5}}, "TNP 2.4")
        self.refused({"structures": ["airport"]}, "TNP 2.4")
        self.refused({"structures": ["factory", "factory_upgrade"]}, "TNP 2.4")
        self.refused({"structures": ["stealth_upgrade", "cyborg_upgrade"]}, "TNP 2.4")
        self.refused({"structures": ["factory"], "build": {"worker": 4}}, "TNP 5.2")
        run = self.refused({"build": {"worker": 4, "mercenary": 2}}, "TNP 2.4")
        self.assertIn("at most 4", run.reason)

    def test_the_supply(self) -> None:
        self.match.seat("blue").available["worker"] = 7
        self.refused({"build": {"worker": 2}}, "TNP 2.3")

    def test_deployment(self) -> None:
        self.refused({"attacks": {"C": {"target": "14", "units": {"worker": 1}}}}, "TNP 2.5")
        self.refused({"attacks": {"A": {"target": "blue_base", "units": {"worker": 1}}}}, "TNP 5.3")
        self.refused({"defense": {"14": {"worker": 1}}}, "TNP 2.5")
        # Held, but not joined to the base: only stranded units are there.
        hold(self.match, "blue", "2")
        self.refused({"defense": {"2": {"worker": 1}}}, "TNP 2.5")
        self.refused({"attacks": {"A": {"target": "14", "units": {"worker": 4}}}}, "TNP 5.3")
        self.refused({"attacks": {"A": {"target": "14", "units": {"worker": 2}}},
                      "defense": {"blue_base": {"worker": 2}}}, "TNP 5.3")
        self.match.seat("blue").available["smart_mines"] = 9
        self.refused({"attacks": {"A": {"target": "14", "units": {"smart_mines": 1}}}}, "TNP 7")
        hold(self.match, "blue", "14")
        self.refused({"defense": {"14": {"smart_mines": 1}}}, "TNP 7")
        self.refused({"defense": {"blue_base": {"smart_mines": 9}}}, "TNP 2.4")

    def test_three_defense_spots_beside_the_base(self) -> None:
        """At most three territories defended a turn; the base's spot is
        its own (TNP 2.5, the author, 2026-11-06)."""
        for area in ("10", "13", "14"):
            hold(self.match, "blue", area)
        fourth = next(
            there for there in sorted(self.engine.catalog.areas["14"].adjacent)
            if there not in {"10", "13", "14"} and not self.engine.catalog.areas[there].is_base
        )
        hold(self.match, "blue", fourth)
        self.match.seat("blue").available["mercenary"] = 5
        three = {area: {"mercenary": 1} for area in ("10", "13", "14")}
        run = save(self.engine, self.game, self.match, "blue",
                   {"defense": {**three, "blue_base": {"mercenary": 1}}})
        self.assertNotIsInstance(run, driver.Refusal, getattr(run, "reason", ""))
        self.refused({"defense": {**three, fourth: {"mercenary": 1}}}, "TNP 2.5")

    def test_one_card_a_territory(self) -> None:
        """A territory goes into one spot a turn: never two attacks, nor an
        attack and a defense (TNP 2.5, the author, 2026-11-06)."""
        hold(self.match, "blue", "14")
        self.refused({"attacks": {"A": {"target": "8", "units": {"worker": 1}},
                                  "B": {"target": "8", "units": {"worker": 1}}}}, "TNP 2.5")
        run = self.refused({"attacks": {"A": {"target": "14", "units": {"worker": 1}}},
                            "defense": {"14": {"mercenary": 1}}}, "TNP 2.5")
        self.assertIn("one spot", run.reason)
        options = prompt_for(self.engine, self.game, self.match, "blue").options
        self.assertEqual(options.cards, {})
        save(self.engine, self.game, self.match, "blue", {
            "attacks": {"A": {"target": "8", "units": {"worker": 1}}},
            "defense": {"14": {"mercenary": 1}, "blue_base": {"mercenary": 1}},
        })
        options = prompt_for(self.engine, self.game, self.match, "blue").options
        self.assertEqual(options.cards, {"8": "A", "14": "defense"})
        self.assertEqual(options.defense_spots, 3)

    def test_a_card_for_the_other_base(self) -> None:
        """The deck has a card for the other seat's base, so two attack
        spots never go at it (TNP 2.5, the author, 2026-11-06)."""
        self.refused({"attacks": {"A": {"target": "green_base", "units": {"worker": 1}},
                                  "B": {"target": "green_base", "units": {"worker": 1}}}}, "TNP 2.5")
        save(self.engine, self.game, self.match, "blue",
             {"attacks": {"A": {"target": "green_base", "units": {"worker": 1}}}})
        options = prompt_for(self.engine, self.game, self.match, "blue").options
        self.assertEqual(options.cards, {"green_base": "A"})

    def test_stranded_units_keep_a_defense_spot(self) -> None:
        """A territory where a seat's stranded units stand keeps one of
        the three defense spots (TNP 2.5, 5.7)."""
        for area in ("10", "13", "14"):
            hold(self.match, "blue", area)
        far = next(
            slug for slug, area in sorted(self.engine.catalog.areas.items())
            if not area.is_base and slug not in joined(self.engine, self.match, "blue")
            and slug not in self.engine.catalog.areas["14"].adjacent
        )
        hold(self.match, "blue", far)
        self.match.areas[far].stranded.append("blue")
        self.match.spots.setdefault(far, {})["blue"] = Pile({"mercenary": 2})
        self.assertEqual(stranded_areas(self.match, "blue"), (far,))
        self.match.seat("blue").available["mercenary"] = 5
        two = {area: {"mercenary": 1} for area in ("10", "13")}
        run = save(self.engine, self.game, self.match, "blue", {"defense": two})
        self.assertNotIsInstance(run, driver.Refusal, getattr(run, "reason", ""))
        run = self.refused({"defense": {**two, "14": {"mercenary": 1}}}, "TNP 2.5")
        self.assertIn("stranded units keep 1", run.reason)
        options = prompt_for(self.engine, self.game, self.match, "blue").options
        self.assertEqual(options.stranded, (far,))
        self.assertEqual(options.cards[far], "stranded")
        board = deployment_brief(self.engine, self.match, "blue")
        self.assertEqual([(one.area, one.state) for one in board.defenses],
                         [(far, STRANDED), ("10", FACE_DOWN), ("13", FACE_DOWN)])
        public = dict(spots_brief(self.engine, self.match).seats)["blue"]
        kept = [one for one in public if one.state == STRANDED]
        self.assertEqual([(one.area, dict(one.units)) for one in kept], [(far, {})])

    def test_attack_spot_c_with_the_command_and_control_cpu(self) -> None:
        """TNP 2.4, 2.5: the base upgrade is placed with no facility, and
        once built the seat has attack spot C; the other seat does not."""
        options = prompt_for(self.engine, self.game, self.match, "blue").options
        self.assertIn("command_and_control_cpu", {one.structure for one in options.structures})
        self.match.seat("blue").built.append("command_and_control_cpu")
        options = prompt_for(self.engine, self.game, self.match, "blue").options
        self.assertEqual(options.spots, ("A", "B", "C"))
        self.assertNotIn("command_and_control_cpu", {one.structure for one in options.structures})
        self.assertEqual(prompt_for(self.engine, self.game, self.match, "green").options.spots, ("A", "B"))
        run = save(self.engine, self.game, self.match, "blue", {
            "attacks": {"C": {"target": "8", "units": {"worker": 1}}},
        })
        self.assertNotIsInstance(run, driver.Refusal, getattr(run, "reason", ""))

    def test_what_is_allowed(self) -> None:
        hold(self.match, "blue", "14")
        run = save(self.engine, self.game, self.match, "blue", {
            "build": {"worker": 2, "mercenary": 1}, "structures": ["factory"],
            "attacks": {"A": {"target": "8", "units": {"worker": 3}},
                        "B": {"target": "green_base", "units": {"mercenary": 1}}},
            "defense": {"14": {"mercenary": 1}, "blue_base": {"mercenary": 1}},
        })
        self.assertNotIsInstance(run, driver.Refusal, getattr(run, "reason", ""))

    def test_the_options_carry_what_a_panel_needs(self) -> None:
        options = prompt_for(self.engine, self.game, self.match, "blue").options
        self.assertEqual({one.unit for one in options.build}, {"worker", "mercenary", "smart_mines", "rocket_launcher"})
        self.assertEqual({one.structure for one in options.structures},
                         {"factory", "barracks_upgrade", "base_defense_upgrade", "stealth_upgrade",
                          "cyborg_upgrade", "laser_cannon_upgrade", "command_and_control_cpu"})
        self.assertEqual(options.spots, ("A", "B"))
        self.assertEqual(options.defenses, ("blue_base",))
        reachable = {one.area for one in options.targets if one.path}
        self.assertEqual(reachable, {"10", "13", "14"})
        self.assertIn("green_base", {one.area for one in options.targets})
        self.assertNotIn("blue_base", {one.area for one in options.targets})


class MarchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine, self.game, self.match = opening(seed=7)

    def test_march_order(self) -> None:
        """TNP 5.4: A for both seats, then B; within a spot, ascending
        territory number, a base after every territory."""
        from tnp.flow.turn import next_attack

        match = self.match
        match.attacks = {
            "blue": {"A": {"target": "13", "units": {"worker": 1}}, "B": {"target": "2", "units": {"worker": 1}}},
            "green": {"A": {"target": "blue_base", "units": {"mercenary": 1}},
                      "B": {"target": "12", "units": {"worker": 1}}},
        }
        found = []
        while (attack := next_attack(match)) is not None:
            found.append(attack)
            spot, area = attack
            for seat in ("blue", "green"):
                if match.attacks[seat].get(spot, {}).get("target") == area:
                    del match.attacks[seat][spot]
        self.assertEqual(found, [("A", "13"), ("A", "blue_base"), ("B", "2"), ("B", "12")])

    def test_a_later_attack_uses_an_earlier_conquest(self) -> None:
        """TNP 5.3, 5.4: an attack may be planned on a territory with no
        path yet, which A's conquest opens for B."""
        said = both_lock(self.engine, self.game, self.match, blue={
            "attacks": {"A": {"target": "10", "units": {"mercenary": 1}},
                        "B": {"target": "2", "units": {"mercenary": 1}}},
        })
        self.assertIn("Blue reveals a Mercenary in attack A and takes area 10.", said)
        self.assertIn("Blue reveals a Mercenary in attack B and takes area 2.", said)
        self.assertEqual((self.match.controller("10"), self.match.controller("2")), ("blue", "blue"))

    def test_no_path_sends_the_ground_units_home_and_the_air_units_on(self) -> None:
        """TNP 5.3: the ground units of a pile with no path go home
        unrevealed, and its air units attack alone, as they must."""
        hold(self.match, "green", "1")
        self.match.seat("blue").available["viper_spy_plane"] = 2
        said = both_lock(self.engine, self.game, self.match, blue={
            "attacks": {"A": {"target": "1", "units": {"viper_spy_plane": 2, "mercenary": 2}}},
        })
        self.assertIn("what cannot fly goes back to its base unrevealed, and its air units attack alone", said)
        self.assertIn("Blue attacks area 1 with 2 Viper Spy Plane.", said)
        self.assertNotIn("Mercenary", said.split("March is over.")[0])
        self.assertIsNone(self.match.controller("1"))

    def test_no_path_sends_the_pile_home_unrevealed(self) -> None:
        said = both_lock(self.engine, self.game, self.match, blue={
            "attacks": {"A": {"target": "1", "units": {"mercenary": 2}}},
        })
        self.assertIn("Blue's attack A cannot reach area 1", said)
        self.assertNotIn("Mercenary", said)
        self.assertIsNone(self.match.controller("1"))

    def test_a_carried_stack_needs_no_path(self) -> None:
        """TNP 7: Chopper Carriers carry ground troops, and the stack
        moves like air units."""
        self.match.seat("blue").available.update({"chopper_carrier": 1, "mercenary": 3})
        said = both_lock(self.engine, self.game, self.match, blue={
            "attacks": {"A": {"target": "1", "units": {"chopper_carrier": 1, "mercenary": 3}}},
        })
        self.assertIn("takes area 1", said)
        self.assertEqual(self.match.controller("1"), "blue")

    def test_air_alone_takes_nothing(self) -> None:
        """TNP 5.5: air units cannot take a territory."""
        self.match.seat("blue").available["viper_spy_plane"] = 2
        said = both_lock(self.engine, self.game, self.match, blue={
            "attacks": {"A": {"target": "7", "units": {"viper_spy_plane": 2}}},
        })
        self.assertIn("with air units alone, which cannot take a territory", said)
        self.assertIsNone(self.match.controller("7"))

    def test_neutral_conquest_asks_which_ground_unit(self) -> None:
        """TNP 5.5: one ground unit is revealed to take the territory, and
        the attacker chooses which."""
        lock(self.engine, self.game, self.match, "blue", {
            "attacks": {"A": {"target": "14", "units": {"mercenary": 2, "worker": 3}}},
        })
        lock(self.engine, self.game, self.match, "green")
        (prompt,) = pending_prompts(self.engine, self.game, self.match)
        self.assertIs(prompt.kind, PromptKind.CONQUER)
        self.assertEqual(set(prompt.options.units), {"mercenary", "worker"})
        refused = driver.apply(self.engine, self.game, self.match,
                               Action(PromptKind.CONQUER, "", {"unit": "tank"}, seat="blue"))
        self.assertEqual(refused.cite, "TNP 5.5")
        run = driver.apply(self.engine, self.game, self.match,
                           Action(PromptKind.CONQUER, "", {"unit": "mercenary"}, seat="blue"))
        said = words(self.engine, run)
        self.assertIn("Blue reveals a Mercenary in attack A and takes area 14.", said)
        self.assertIn("Blue's 3 Worker harvest area 14: 3 blue minerals, 3 harvested in all.", said)
        # One pile, shown once: the Mercenary that took it and the
        # Workers that harvested it.
        self.assertEqual(self.match.revealed, [
            {"seat": "blue", "area": "14", "spot": "A", "units": {"mercenary": 1, "worker": 3}},
        ])

    def test_a_pile_shown_twice_is_revealed_once(self) -> None:
        """A Worker revealed to take a territory (TNP 5.5) is one of the
        Workers that then harvest it (TNP 5.8): the map shows the pile
        once, with its three Workers, never a Worker and three more."""
        lock(self.engine, self.game, self.match, "blue", {
            "attacks": {"A": {"target": "14", "units": {"worker": 3}}},
        })
        lock(self.engine, self.game, self.match, "green")
        self.assertEqual(self.match.revealed, [
            {"seat": "blue", "area": "14", "spot": "A", "units": {"worker": 3}},
        ])

    def test_the_seat_chooses_which_tokens(self) -> None:
        """TNP 5.8: from a territory of two kinds, the seat chooses."""
        hold(self.match, "blue", "14", "8", "5")
        self.match.areas["5"].resources = {"blue_minerals": 2, "orange_minerals": 5, "gems": 0}
        lock(self.engine, self.game, self.match, "blue", {"attacks": {"A": {"target": "5", "units": {"worker": 3}}}})
        lock(self.engine, self.game, self.match, "green")
        (prompt,) = pending_prompts(self.engine, self.game, self.match)
        self.assertIs(prompt.kind, PromptKind.HARVEST)
        self.assertEqual((prompt.options.count, prompt.options.left), (3, {"blue_minerals": 2, "orange_minerals": 5}))
        for wrong in ({"blue_minerals": 3}, {"orange_minerals": 2}, {"gems": 3}, {"orange_minerals": 4}):
            refused = driver.apply(self.engine, self.game, self.match,
                                   Action(PromptKind.HARVEST, "", {"tokens": wrong}, seat="blue"))
            self.assertEqual(refused.cite, "TNP 5.8", wrong)
        run = driver.apply(self.engine, self.game, self.match,
                           Action(PromptKind.HARVEST, "", {"tokens": {"blue_minerals": 2, "orange_minerals": 1}}, seat="blue"))
        self.assertIn("Blue's 3 Worker harvest area 5: 2 blue minerals, 1 orange mineral", words(self.engine, run))
        self.assertEqual(self.match.areas["5"].resources["orange_minerals"], 4)

    def test_harvest(self) -> None:
        """TNP 5.8: a token a Worker, into the pool; attacking a territory
        the seat holds is the way to harvest it again; in the basic game
        a territory of two minerals gives the one with more left."""
        hold(self.match, "blue", "14")
        self.match.areas["14"].resources = {"blue_minerals": 2, "orange_minerals": 0, "gems": 0}
        said = both_lock(self.engine, self.game, self.match, blue={
            "attacks": {"A": {"target": "14", "units": {"worker": 3}}},
        })
        self.assertIn("Blue's attack A reaches area 14, which it holds.", said)
        self.assertIn("2 blue minerals, 2 harvested in all", said)
        self.assertNotEqual(pending_prompts(self.engine, self.game, self.match)[0].kind, PromptKind.HARVEST)
        self.assertEqual(self.match.seat("blue").pool["blue_minerals"], 2)
        self.assertEqual(self.match.areas["14"].tokens_left(), 0)

    def test_a_held_territory_with_nobody_in_it_falls_at_once(self) -> None:
        """TNP 2.1, 6.1: held with nobody left in it, until an enemy
        takes it -- which wins at once."""
        hold(self.match, "green", "13")
        hold(self.match, "blue", "14")
        said = both_lock(self.engine, self.game, self.match, blue={
            "attacks": {"A": {"target": "13", "units": {"worker": 3}}},
        })
        self.assertIn("Nobody defends area 13.", said)
        self.assertEqual(self.match.controller("13"), "blue")
        self.assertEqual(self.match.seat("blue").harvested, 3)

    def test_a_battle_goes_on_the_map(self) -> None:
        """TNP 5.6, 5.7, 6.11: the winner's survivors stay in the
        territory's defense spot for the rest of March, the loser's go
        home, control is the outcome's, and the winner's Workers harvest."""
        hold(self.match, "blue", "10", "2", "1", "3", "9")
        hold(self.match, "green", "15")
        lock(self.engine, self.game, self.match, "blue", {
            "attacks": {"A": {"target": "15", "units": {"mercenary": 3, "worker": 3}}},
        })
        run = lock(self.engine, self.game, self.match, "green", {"defense": {"15": {"worker": 1}}})
        self.assertIsNotNone(self.match.battle)
        said = answered(self.engine, self.game, self.match, run)
        self.assertIn("Blue attacks area 15 with 3 Worker, 3 Mercenary.", said)
        self.assertIn("Blue wins the battle for area 15.", said)
        self.assertEqual(self.match.controller("15"), "blue")
        self.assertIsNone(self.match.battle)
        self.assertGreater(self.match.seat("blue").harvested, 0)
        self.assertEqual(self.match.phase, TRADE)
        piles = {(one["seat"], one["spot"]) for one in self.match.revealed}
        self.assertIn(("green", "defense"), piles)
        self.assertIn(("blue", "A"), piles)

    def test_both_seats_at_one_neutral_territory_fight_for_it(self) -> None:
        """TNP 5.6, 6.1: a contested territory is a battle."""
        hold(self.match, "blue", "10", "2")
        hold(self.match, "green", "11", "3")
        lock(self.engine, self.game, self.match, "blue", {"attacks": {"A": {"target": "1", "units": {"mercenary": 3}}}})
        run = lock(self.engine, self.game, self.match, "green", {"attacks": {"A": {"target": "1", "units": {"worker": 2}}}})
        self.assertTrue(self.match.battle.contested)
        said = answered(self.engine, self.game, self.match, run)
        self.assertIn("Blue and Green both attack area 1.", said)
        self.assertIsNotNone(self.match.controller("1"))

    def test_stranded(self) -> None:
        """TNP 5.7, 5.10: a held territory cut off from its base, with its
        seat's units in it, takes a Stranded token; they stay through
        Cleanup and cannot be deployed; taking a territory beside it
        lifts the token."""
        engine, game, match = self.engine, self.game, self.match
        hold(match, "blue", "10", "2", "14")
        match.seat("green").available["chopper_carrier"] = 1
        lock(engine, game, match, "blue", {"defense": {"2": {"mercenary": 3}}})
        run = lock(engine, game, match, "green", {
            "attacks": {"A": {"target": "10", "units": {"chopper_carrier": 1, "worker": 3}}},
        })
        said = answered(engine, game, match, run)
        self.assertIn("Nobody defends area 10.", said)
        self.assertEqual(match.controller("10"), "green")
        self.assertIn("Blue's units in area 2 are stranded.", said)
        self.assertEqual(match.areas["2"].stranded, ["blue"])
        self.assertNotIn("2", joined(engine, match, "blue"))
        self.assertEqual((match.turn, match.phase), (2, PLAN))
        self.assertEqual(match.spots["2"]["blue"].units, {"mercenary": 3})
        self.assertNotIn("mercenary", match.seat("blue").available)
        refused = save(engine, game, match, "blue", {"attacks": {"A": {"target": "8", "units": {"mercenary": 1}}}})
        self.assertEqual(refused.cite, "TNP 5.3")
        refused = save(engine, game, match, "blue", {"defense": {"2": {"worker": 1}}})
        self.assertEqual(refused.cite, "TNP 2.5")
        # Blue takes 1, beside 2, by air: no path home, so the token stays.
        match.seat("blue").available["chopper_carrier"] = 1
        lock(engine, game, match, "blue", {"attacks": {"A": {"target": "1", "units": {"chopper_carrier": 1, "worker": 1}}}})
        said = answered(engine, game, match, lock(engine, game, match, "green"))
        self.assertEqual(match.controller("1"), "blue")
        self.assertNotIn("no longer stranded", said)
        self.assertEqual(match.areas["2"].stranded, ["blue"])
        # Blue takes 8, beside 2 and joined to the base by 14: the path is
        # made, the token is lifted, and Cleanup sends its units home.
        lock(engine, game, match, "blue", {"attacks": {"A": {"target": "8", "units": {"worker": 1}}}})
        said = answered(engine, game, match, lock(engine, game, match, "green"))
        self.assertIn("Blue's units in area 2 are no longer stranded.", said)
        self.assertEqual(match.areas["2"].stranded, [])
        self.assertEqual(match.seat("blue").available.get("mercenary"), 3)


class BaseBattleTests(unittest.TestCase):
    def test_what_a_base_battle_leaves_on_the_base(self) -> None:
        """TNP 6.2, 6.9: the emergency spend comes out of the defender's
        pool, and what the base card destroyed is gone from the base;
        units queued at a destroyed facility are not produced (TNP 5.9)."""
        engine, game, match = opening()
        green = match.seat("green")
        green.built += ["factory"]
        green.queued_units = {"tank": 2, "worker": 1}
        green.pool.update({"materials": 2, "blue_minerals": 3})
        match.phase = MARCH
        match.resolving = {"spot": "B", "area": "green_base", "piles": {"blue": {"mercenary": 3}}, "stage": "battle"}
        match.battle = BattleState(
            territory="green_base", attacker="blue", defender="green", phase="over",
            emergency={"pool": {"materials": 0, "gold": 0, "blue": 1, "orange": 0, "gems": 0}, "supply_room": {}},
            outcome={"winner": "green", "by": "held", "control": None, "base_fallen": False,
                     "destroyed": "factory", "home": ["blue"], "withdrawn": {},
                     "survivors": {"blue": {"mercenary": {"count": 1, "damaged": 0}},
                                   "green": {"smart_mines": {"count": 2, "damaged": 0},
                                             "laser_cannon": {"count": 1, "damaged": 1}}}},
        )
        self.assertEqual(pending_all(engine, game, match), (FollowOn(FollowOnStep.SETTLE_BATTLE),))
        run = driver.resume(engine, game, match)
        self.assertEqual(run.steps[:3], (FollowOnStep.SETTLE_BATTLE, FollowOnStep.MARCH, FollowOnStep.PRODUCE))
        self.assertNotIn("factory", green.built)
        self.assertEqual((green.pool["materials"], green.pool["blue_minerals"]), (0, 1))
        self.assertEqual(match.spots["green_base"]["green"].units, {"smart_mines": 2, "laser_cannon": 1})
        # A damage token lasts the battle alone (TNP 6.8).
        self.assertEqual(match.spots["green_base"]["green"].damaged, {})
        self.assertEqual(match.seat("blue").available["mercenary"], 4)
        self.assertIsNone(match.battle)
        self.assertNotIn("tank", green.available)
        self.assertEqual(green.available["worker"], 4)
        self.assertIn("loses what was queued", " ".join(run.narration))

    def test_a_fallen_base_wins_the_game(self) -> None:
        """TNP 1.3, 6.1: an undefended base, offered its emergency
        defense, falls -- and its attacker wins."""
        engine, game, match = opening()
        hold(match, "blue", "10", "2", "1", "3", "11")
        match.seat("green").pool["materials"] = 0
        lock(engine, game, match, "blue", {"attacks": {"A": {"target": "green_base", "units": {"mercenary": 3}}}})
        run = lock(engine, game, match, "green")
        said = words(engine, run)
        self.assertIn("Nobody defends Green base.", said)
        self.assertIn("Blue wins the game: Green base has fallen.", said)
        self.assertEqual((match.winner, match.won_by), ("blue", "base"))
        self.assertEqual(pending_all(engine, game, match), ())


class TradeAndCleanupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine, self.game, self.match = opening()
        self.match.seat("blue").pool.update({"blue_minerals": 2, "orange_minerals": 1, "gems": 1})
        self.match.phase = TRADE

    def test_only_a_seat_with_tokens_is_asked(self) -> None:
        prompts = pending_prompts(self.engine, self.game, self.match)
        self.assertEqual([one.asked_seat for one in prompts], ["blue"])
        self.assertEqual(prompts[0].options.tokens, {"blue_minerals": 2, "orange_minerals": 1, "gems": 1})

    def test_the_conversion_rates(self) -> None:
        """TNP 5.9: a mineral 2 materials or 1 gold, a gem 3 or 2; each
        token for one or the other, never both; blue and orange alike."""
        trade = {"materials": {"blue_minerals": 1, "orange_minerals": 1}, "gold": {"blue_minerals": 1, "gems": 1}}
        run = driver.apply(self.engine, self.game, self.match, Action(TRADE_KIND, "lock", {"trade": trade}, seat="blue"))
        self.assertIn("Blue trades 2 blue minerals, 1 orange mineral, 1 gem for 4 materials and 3 gold.", words(self.engine, run))
        pool = self.match.seat("blue").pool
        self.assertEqual((pool["materials"], pool["gold"], pool["blue_minerals"], pool["gems"]), (9, 3, 0, 0))

    def test_a_token_trades_once(self) -> None:
        before = self.match.to_dict()
        for trade in ({"materials": {"gems": 1}, "gold": {"gems": 1}}, {"materials": {"blue_minerals": 3}},
                      {"materials": {"materials": 1}}, {"silver": {"gems": 1}}):
            run = driver.apply(self.engine, self.game, self.match, Action(TRADE_KIND, "save", {"trade": trade}, seat="blue"))
            self.assertIsInstance(run, driver.Refusal, trade)
            self.assertEqual(run.cite, "TNP 5.9")
        self.assertEqual(self.match.to_dict(), before)

    def test_cleanup_clears_every_spot_and_opens_the_next_turn(self) -> None:
        """TNP 5.10: every spot back to the seat's available units."""
        self.match.pile("blue_base", "blue").add({"mercenary": 2})
        self.match.seat("blue").available = {"worker": 3, "mercenary": 1}
        self.match.revealed = [{"seat": "blue", "area": "14", "spot": "A", "units": {"worker": 1}}]
        run = driver.apply(self.engine, self.game, self.match, Action(TRADE_KIND, "lock", {}, seat="blue"))
        self.assertIn("Turn 2: Infrastructure and Deployment.", words(self.engine, run))
        self.assertEqual(self.match.seat("blue").available, {"worker": 3, "mercenary": 3})
        self.assertEqual((self.match.spots, self.match.revealed), ({}, []))
        self.assertEqual((self.match.turn, self.match.phase), (2, PLAN))

    def test_51_percent_is_counted_at_cleanup(self) -> None:
        """TNP 1.3: 49 of 96 tokens harvested wins, counted at Cleanup."""
        self.match.seat("green").harvested = 49
        self.assertIsNone(self.match.winner)
        driver.apply(self.engine, self.game, self.match, Action(TRADE_KIND, "lock", {}, seat="blue"))
        self.assertEqual((self.match.winner, self.match.won_by), ("green", WON_BY_HARVEST))

    def test_production(self) -> None:
        """TNP 5.9: what Infrastructure placed is finished, ready next
        turn -- and a facility built this turn takes its units next."""
        match = self.match
        match.phase = "production"
        match.seat("blue").queued_units = {"worker": 2}
        match.seat("blue").queued = ["factory"]
        driver.resume(self.engine, self.game, match)
        self.assertEqual(match.seat("blue").available["worker"], 5)
        self.assertIn("factory", match.seat("blue").built)
        self.assertEqual(match.phase, TRADE)


class RecordTests(unittest.TestCase):
    def test_the_lobby(self) -> None:
        engine = RulesEngine()
        game = TnpGame(game_id="g")
        with self.assertRaises(RuleRefusal):
            game.start(engine)
        self.assertEqual(game.take_seat(1, "one"), "blue")
        with self.assertRaises(RuleRefusal):
            game.take_seat(1, "one")
        with self.assertRaises(RuleRefusal):
            game.take_seat(2, "two", "blue")
        self.assertEqual(game.take_seat(2, "two"), "green")
        with self.assertRaises(RuleRefusal):
            game.take_seat(3, "three")
        with self.assertRaises(RuleRefusal) as refused:
            game.set_advanced(True)
        self.assertEqual(refused.exception.cite, "TNP 8")
        game.leave(2)
        self.assertEqual(game.seat_ids(), [1])
        game.take_seat(2, "two", "green")
        game.start(engine)
        self.assertIs(game.status, GameStatus.PLAYING)
        with self.assertRaises(RuleRefusal):
            game.take_seat(3, "three")
        self.assertEqual(TnpGame.from_dict(json.loads(json.dumps(game.to_dict()))).to_dict(), game.to_dict())

    def test_a_test_game_seats_one_person_twice(self) -> None:
        game = TnpGame(game_id="g", test_game=True)
        game.take_seat(1, "one")
        game.take_seat(1, "one")
        self.assertEqual(game.seats_of(1), ("blue", "green"))

    def test_every_field_is_saved(self) -> None:
        """The save format is the contract: every field in its table."""
        for table, cls in ((MATCH_SAVED_FIELDS, MatchState), (SEAT_SAVED_FIELDS, SeatState),
                           (AREA_SAVED_FIELDS, AreaState), (GAME_SAVED_FIELDS, TnpGame)):
            self.assertEqual({row.name for row in table}, {one.name for one in fields(cls)}, cls)


class ServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.saves = []
        self.service = GameService(RulesEngine(rng=random.Random(1)), {}, save=self.saves.append)

    def started(self) -> TnpGame:
        game = self.service.create_game(guild_id=5)
        self.service.take_seat(game.game_id, 1, "one")
        self.service.take_seat(game.game_id, 2, "two")
        return game

    def test_one_save_an_action_and_no_prompt_on_the_wire(self) -> None:
        game = self.started()
        started = self.service.start(game.game_id)
        self.assertEqual([one.asked_seat for one in started.prompts], ["blue", "green"])
        before = len(self.saves)
        result = self.service.apply_action(game.game_id, Action(
            PLAN_KIND, "save", {"plan": {"build": {"worker": 4}}}, seat="blue"))
        self.assertEqual(len(self.saves), before + 1)
        self.assertNotIn("prompts", result.to_dict())
        self.assertNotIn("worker", json.dumps(result.to_dict()))
        refused = self.service.apply_action(game.game_id, Action(PLAN_KIND, "lock", {"plan": {"build": {"tank": 1}}}, seat="blue"))
        self.assertTrue(refused.refused)
        self.assertEqual(len(self.saves), before + 1)

    def test_a_restart_mid_phase_keeps_both_plans(self) -> None:
        game = self.started()
        self.service.start(game.game_id)
        self.service.apply_action(game.game_id, Action(PLAN_KIND, "save", {"plan": {"build": {"worker": 4}}}, seat="blue"))
        self.service.apply_action(game.game_id, Action(PLAN_KIND, "lock", {"plan": {"build": {"mercenary": 2}}}, seat="green"))
        restarted = GameService(RulesEngine(), {game.game_id: TnpGame.from_dict(json.loads(json.dumps(game.to_dict())))})
        found, result = restarted.resume(game.game_id)
        self.assertEqual([one.asked_seat for one in result.prompts], ["blue"])
        self.assertEqual(result.prompt_for("blue").options.plan["build"], {"worker": 4})
        match = restarted.load(restarted.game(game.game_id))
        self.assertTrue(match.seat("green").locked)
        self.assertEqual(match.seat("green").plan["build"], {"mercenary": 2})

    def test_a_win_finishes_the_record(self) -> None:
        game = self.started()
        self.service.start(game.game_id)
        match = self.service.load(game)
        match.phase = TRADE
        match.seat("blue").harvested = 49
        self.service.persist(game, match)
        result = self.service.resume(game.game_id)[1]
        self.assertEqual(result.match.winner, "blue")
        self.assertIs(game.status, GameStatus.FINISHED)
        with self.assertRaises(RuleRefusal):
            self.service.apply_action(game.game_id, Action(PLAN_KIND, "lock", {}, seat="blue"))


class StorageTests(unittest.TestCase):
    def test_a_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "tnp_games.json"
            engine = RulesEngine()
            game = TnpGame(game_id="g")
            game.take_seat(1, "one")
            game.take_seat(2, "two")
            game.start(engine)
            storage.save_games({"g": game}, path)
            loaded = storage.load_games(path)
            self.assertEqual(loaded["g"].to_dict(), game.to_dict())

    def test_a_corrupt_file_loads_nothing_and_is_never_written_over(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "tnp_games.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertLogs(storage.LOGGER, logging.ERROR):
                self.assertEqual(storage.load_games(path), {})
            with self.assertLogs(storage.LOGGER, logging.ERROR):
                storage.save_games({}, path)
            self.assertEqual(path.read_text(encoding="utf-8"), "{not json")

    def test_one_bad_game_takes_no_other_with_it(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "tnp_games.json"
            path.write_text(json.dumps({"bad": {"status": "nonsense", "game_id": "bad"},
                                        "good": TnpGame(game_id="good").to_dict()}), encoding="utf-8")
            with self.assertLogs(storage.LOGGER, logging.ERROR):
                loaded = storage.load_games(path)
            self.assertEqual(list(loaded), ["good"])



if __name__ == "__main__":
    unittest.main()
