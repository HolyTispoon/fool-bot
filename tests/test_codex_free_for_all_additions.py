"""
The free-for-all's three additions (docs/codex-multiplayer.md, step 3),
each staged by slug and played through `driver.apply`: repairing the
base, the free gold for a kill, and lending a patroller.

The rules are Rulebook p. 14, with p. 11 for a dead hero's levels and the
author's answers of 2026-10-14 to questions 18 and 19.
"""

from __future__ import annotations

import json
import unittest

from codex import history
from codex.components import MatchState
from codex.engine import RulesEngine, target_key
from codex.flow import StepResult, board, driver
from codex.prompts import Action, PromptKind, pending_prompt

from test_codex_free_for_all import apply, end_turn, free_for_all, said
from codex_positions import begin, hand, hero_in_play, new_game, put


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


def attack(engine, game, match, attacker, defender, against):
    """`attacker` (a ref) attacks `defender` of `against`, through the
    driver. What was said."""
    heard = [said(apply(engine, game, match, Action(
        PromptKind.MAIN_ACTION, "attack", {"attacker": attacker}))),
    ]
    heard.append(said(apply(engine, game, match, Action(
        PromptKind.CHOOSE_DEFENDER, arguments={"defender": defender, "against": against},
    ))))
    return "\n".join(heard)


class FreeGoldTests(unittest.TestCase):
    """1 gold for each enemy unit the active player kills on their turn,
    to 3 a turn: a unit, never a hero or a building (Rulebook p. 14;
    question 19, answered 2026-10-14: "whenever you kill")."""

    def setUp(self) -> None:
        self.engine, self.game, self.match = free_for_all()
        self.match.player(1).gold = 0

    def kill(self, units, cause=1, combat=False):
        result = StepResult()
        board.destroy(self.engine, self.match, [(unit.controller, unit.ref) for unit in units],
                      result, cause=cause, combat=combat)
        return "\n".join(result.narration)

    def test_a_kill_in_combat_pays_the_attacker(self) -> None:
        iron = put(self.match, 1, "iron_man")
        victim = put(self.match, 2, "tenderfoot", patrol="elite")
        heard = attack(self.engine, self.game, self.match, iron.ref, victim.ref, 2)
        self.assertIn("{player:1} collects {gold:1}.", heard)
        self.assertEqual((self.match.player(1).gold, self.match.player(1).bounties), (1, 1))

    def test_a_kill_by_a_spell_pays_its_caster(self) -> None:
        hero_in_play(self.match, 1)
        victim = put(self.match, 3, "tenderfoot", patrol="elite", damage=1)
        hand(self.match, 1, "spark")
        self.match.player(1).gold = 1
        run = apply(self.engine, self.game, self.match, Action(
            PromptKind.MAIN_ACTION, "play", {"slug": "spark"}))
        while pending_prompt(self.engine, self.game, self.match).kind is PromptKind.TARGET:
            run = apply(self.engine, self.game, self.match, Action(
                PromptKind.TARGET, arguments={"target": target_key(3, victim.ref)}))
        self.assertEqual(self.match.player(1).gold, 1)  # spent 1, collected 1
        self.assertEqual(self.match.player(1).bounties, 1)
        self.assertIn("{player:1} collects {gold:1}.", said(run))

    def test_a_unit_that_dies_to_its_own_controllers_trigger_pays_nothing(self) -> None:
        """Jandra's "Dies from combat damage: Destroy all your units" is
        seat 2's own trigger: Jandra's death in combat pays, the units
        she takes with her do not."""
        iron = put(self.match, 1, "iron_man")
        jandra = put(self.match, 2, "jandra_the_negator", patrol="elite")
        put(self.match, 2, "tenderfoot")
        put(self.match, 2, "older_brother")
        heard = attack(self.engine, self.game, self.match, iron.ref, jandra.ref, 2)
        self.assertEqual(heard.count("collects"), 1)
        self.assertEqual(self.match.player(2).play, [])
        self.assertEqual(self.match.player(1).bounties, 1)

    def test_a_unit_the_state_of_the_table_kills_pays_nothing(self) -> None:
        victim = put(self.match, 2, "tenderfoot")
        victim.minus_runes = 2
        result = StepResult()
        board.settle(self.engine, self.match, result)
        self.assertEqual(self.match.player(2).play, [])
        self.assertEqual(self.match.player(1).bounties, 0)

    def test_a_fourth_kill_in_a_turn_pays_nothing(self) -> None:
        units = [put(self.match, 2, "tenderfoot") for _ in range(2)] + [
            put(self.match, 3, "tenderfoot") for _ in range(2)]
        heard = self.kill(units)
        self.assertEqual(heard.count("collects"), 3)
        self.assertEqual((self.match.player(1).gold, self.match.player(1).bounties), (3, 3))

    def test_the_count_starts_again_with_the_next_turn(self) -> None:
        self.kill([put(self.match, 2, "tenderfoot") for _ in range(3)])
        self.assertEqual(self.match.player(1).bounties, 3)
        end_turn(self.engine, self.game, self.match)
        end_turn(self.engine, self.game, self.match)
        end_turn(self.engine, self.game, self.match)
        self.assertEqual(self.match.active, 1)
        self.assertEqual(self.match.player(1).bounties, 0)

    def test_the_gold_cap_is_respected(self) -> None:
        self.match.player(1).gold = 20
        heard = self.kill([put(self.match, 2, "tenderfoot")])
        self.assertNotIn("collects", heard)
        self.assertEqual((self.match.player(1).gold, self.match.player(1).bounties), (20, 0))

    def test_a_token_pays(self) -> None:
        token = put(self.match, 2, "mercenary")
        self.assertIn("collects", self.kill([token]))

    def test_a_hero_pays_nothing(self) -> None:
        hero_in_play(self.match, 2)
        result = StepResult()
        board.destroy(self.engine, self.match, [(2, f"hero:{self.match.player(2).heroes[0].slug}")],
                      result, cause=1)
        self.assertNotIn("collects", "\n".join(result.narration))
        self.assertEqual(self.match.player(1).gold, 0)

    def test_my_own_unit_pays_nothing(self) -> None:
        self.assertNotIn("collects", self.kill([put(self.match, 1, "tenderfoot")]))

    def test_a_unit_destroyed_on_another_players_turn_pays_the_active_player_nothing(self) -> None:
        """Seat 3's kill of seat 2's unit is not seat 1's."""
        self.assertNotIn("collects", self.kill([put(self.match, 2, "tenderfoot")], cause=3))
        self.assertEqual(self.match.player(1).gold, 0)

    def test_a_lent_card_is_its_controllers(self) -> None:
        """A card lent to an opponent is theirs (Rulebook p. 14)."""
        card = put(self.match, 1, "tenderfoot")
        self.assertNotIn("collects", self.kill([card]))
        card = put(self.match, 1, "tenderfoot")
        card.controller = 3
        self.match.player(1).play.remove(card)
        self.match.player(3).play.append(card)
        self.assertIn("collects", self.kill([card]))

    def test_blackhand_dozer_dies_and_the_active_player_destroys_one_more(self) -> None:
        """The Dozer's "Active player destroys one of your lowest tech
        units" is the active player's kill (question 19's list): the Dozer
        pays in combat and the unit it takes pays too."""
        iron = put(self.match, 1, "regularsized_rhinoceros")
        dozer = put(self.match, 2, "blackhand_dozer", patrol="elite")
        dozer.damage = 5
        put(self.match, 2, "tenderfoot")
        heard = attack(self.engine, self.game, self.match, iron.ref, dozer.ref, 2)
        while pending_prompt(self.engine, self.game, self.match).kind is PromptKind.TARGET:
            prompt = pending_prompt(self.engine, self.game, self.match)
            row = prompt.options.rows[0]
            heard += said(apply(self.engine, self.game, self.match, Action(
                PromptKind.TARGET, arguments={"target": row.key})))
        self.assertEqual(self.match.player(2).play, [])
        self.assertEqual(self.match.player(1).bounties, 2)

    def test_a_duel_pays_nothing(self) -> None:
        engine, game, match = new_game()
        begin(engine, game, match)
        match.player(1).gold = 0
        result = StepResult()
        victim = put(match, 2, "tenderfoot")
        board.destroy(engine, match, [(2, victim.ref)], result, cause=1)
        self.assertNotIn("collects", "\n".join(result.narration))
        self.assertEqual(match.player(1).gold, 0)

    def test_bounties_are_saved_only_while_set(self) -> None:
        self.assertNotIn("bounties", self.match.to_dict()["players"][0])
        self.match.player(1).bounties = 2
        saved = self.match.to_dict()
        self.assertEqual(saved["players"][0]["bounties"], 2)
        self.assertEqual(MatchState.from_dict(saved).player(1).bounties, 2)
        del saved["players"][0]["bounties"]
        self.assertEqual(MatchState.from_dict(saved).player(1).bounties, 0)


def lock(engine, game, match, assignment=None, lent=None) -> str:
    """The active player ends their main phase and locks `assignment`
    and `lent`; the turn runs on to the next main phase, the tech each
    player owes settled with no picks. What was said."""
    heard = [said(apply(engine, game, match, Action(PromptKind.MAIN_ACTION, "end_main")))]
    arguments = {"assignment": assignment or {}}
    if lent is not None:
        arguments["lent"] = lent
    heard.append(said(apply(engine, game, match, Action(PromptKind.PATROL, arguments=arguments))))
    while match.winner is None:
        for player in match.players:
            player.tech_owed = False
        from codex.prompts import owed_step

        owed = owed_step(engine, game, match)
        if owed is None:
            break
        heard.append(said(driver.advance(engine, game, match, StepResult(next=owed))))
    return "\n".join(heard)


def patrol_prompt(engine, game, match):
    apply(engine, game, match, Action(PromptKind.MAIN_ACTION, "end_main"))
    return pending_prompt(engine, game, match)


class LendingTests(unittest.TestCase):
    """Lending patrollers (Rulebook p. 14): at the lock a player may put
    units and heroes into an opponent's open slots. The borrower controls
    them until their upkeep, when they go home. Turn order here is 3, 1,
    2: seat 3 locks, seat 1 has a turn with the card in seat 2's zone,
    and the card goes home at seat 2's upkeep."""

    def setUp(self) -> None:
        self.engine, self.game, self.match = free_for_all(first=3)
        self.lender = self.match.player(3)

    def lend_unit(self, slug="tenderfoot", slot="technician", **staged):
        card = put(self.match, 3, slug, **staged)
        # The staged card is part of the turn's start, as a replay needs.
        self.match.turn_snapshots[-1] = history.position(self.match)
        heard = lock(self.engine, self.game, self.match, lent={"2": {slot: card.ref}})
        return card, heard

    def test_the_lock_offers_each_opponents_open_slots(self) -> None:
        put(self.match, 2, "tenderfoot", patrol="squad_leader")
        options = patrol_prompt(self.engine, self.game, self.match).options
        self.assertEqual(dict(options.zones)[2][0], "elite")
        self.assertNotIn("squad_leader", dict(options.zones)[2])
        self.assertEqual({seat for seat, _ in options.zones}, {1, 2})
        self.assertEqual(set(options.to_dict()["zones"]), {"1", "2"})

    def test_a_duel_offers_no_zones_and_refuses_lending(self) -> None:
        engine, game, match = new_game()
        begin(engine, game, match)
        card = put(match, 1, "tenderfoot")
        options = patrol_prompt(engine, game, match).options
        self.assertEqual(options.zones, ())
        self.assertNotIn("zones", options.to_dict())
        refusal = refused_by(engine, game, match, Action(
            PromptKind.PATROL, arguments={"assignment": {}, "lent": {"2": {"elite": card.ref}}}))
        self.assertEqual(refusal.cite, "Rulebook p. 14")

    def test_a_lent_card_is_the_borrowers_and_nothing_on_it_changes(self) -> None:
        card = put(self.match, 3, "tenderfoot", damage=1)
        card.plus_runes = 2
        card.minus_runes = 1
        before = (card.damage, card.plus_runes, card.minus_runes, card.exhausted, card.id,
                  card.arrived_this_turn)
        card.arrived_this_turn = True
        before = before[:-1] + (True,)
        apply(self.engine, self.game, self.match, Action(PromptKind.MAIN_ACTION, "end_main"))
        run = apply(self.engine, self.game, self.match, Action(PromptKind.PATROL, arguments={
            "assignment": {}, "lent": {"2": {"elite": card.ref}}}))
        self.assertIn("{player:3} lends {card:tenderfoot} to {player:2} as elite.", said(run))
        self.assertNotIn(card, self.match.player(3).play)
        self.assertIn(card, self.match.player(2).play)
        self.assertEqual((card.controller, card.owner, card.lent, card.patrol_slot), (2, 3, True, "elite"))
        self.assertEqual((card.damage, card.plus_runes, card.minus_runes, card.exhausted, card.id,
                          card.arrived_this_turn), before)
        self.assertNotIn("{card:tenderfoot} arrives", said(run))
        self.assertEqual(self.match.patrollers(2)["elite"], card.ref)

    def test_a_lent_card_protects_the_borrower_alone(self) -> None:
        card, _ = self.lend_unit(slot="squad_leader")
        self.assertEqual(self.match.active, 1)
        self.assertEqual(self.match.patrollers(2), {"squad_leader": card.ref})
        self.assertEqual(self.match.patrollers(3), {})
        options = pending_prompt(self.engine, self.game, self.match).options
        iron = put(self.match, 1, "iron_man")
        apply(self.engine, self.game, self.match, Action(PromptKind.MAIN_ACTION, "attack", {"attacker": iron.ref}))
        prompt = pending_prompt(self.engine, self.game, self.match)
        offered = dict(zip(prompt.options.defenders, prompt.options.seats))
        self.assertEqual(offered.get(card.ref), 2)

    def test_the_slot_must_be_open_and_the_card_patrols_once(self) -> None:
        taken = put(self.match, 2, "tenderfoot", patrol="elite")
        card = put(self.match, 3, "older_brother")
        apply(self.engine, self.game, self.match, Action(PromptKind.MAIN_ACTION, "end_main"))
        run = lambda **arguments: refused_by(self.engine, self.game, self.match, Action(
            PromptKind.PATROL, arguments=arguments))
        self.assertIn("not open", run(assignment={}, lent={"2": {"elite": card.ref}}).reason)
        self.assertIn("opponent", run(assignment={}, lent={"3": {"scavenger": card.ref}}).reason)
        self.assertIn("one slot", run(assignment={"elite": card.ref},
                                      lent={"2": {"scavenger": card.ref}}).reason)
        self.assertIn("ready", run(assignment={}, lent={"2": {"scavenger": "unit:99"}}).reason)
        self.assertEqual(card.controller, 3)

    def test_the_card_goes_home_at_the_borrowers_upkeep(self) -> None:
        card, _ = self.lend_unit(damage=1)
        card.exhausted = False
        heard = lock(self.engine, self.game, self.match)
        self.assertEqual(self.match.active, 2)
        self.assertIn("{card:tenderfoot} goes home to {player:3}.", heard)
        self.assertIn(card, self.match.player(3).play)
        self.assertNotIn(card, self.match.player(2).play)
        self.assertEqual((card.controller, card.lent, card.patrol_slot, card.damage), (3, False, None, 1))
        self.assertNotIn("{card:tenderfoot} arrives", heard)

    def test_the_return_readies_nothing_the_borrowers_ready_phase_did(self) -> None:
        card = put(self.match, 3, "tenderfoot")
        apply(self.engine, self.game, self.match, Action(PromptKind.MAIN_ACTION, "end_main"))
        apply(self.engine, self.game, self.match, Action(PromptKind.PATROL, arguments={
            "assignment": {}, "lent": {"2": {"elite": card.ref}}}))
        card.exhausted = True   # worn out on seat 1's turn
        self.match.active = 1
        for player in self.match.players:
            player.tech_owed = False
        card.exhausted = True
        lock(self.engine, self.game, self.match) if self.match.phase == "main" else None
        while self.match.active != 2 or self.match.phase != "main":
            from codex.prompts import owed_step
            owed = owed_step(self.engine, self.game, self.match)
            if owed is None:
                break
            driver.advance(self.engine, self.game, self.match, StepResult(next=owed))
        self.assertEqual(self.match.active, 2)
        self.assertFalse(card.exhausted)   # readied by seat 2's ready phase, as theirs
        self.assertEqual(card.controller, 3)

    def test_the_return_keeps_a_card_as_it_was(self) -> None:
        card, _ = self.lend_unit()
        card.plus_runes = 1
        card.exhausted = False
        lock(self.engine, self.game, self.match)
        self.assertEqual((card.plus_runes, card.exhausted), (1, False))

    def test_the_scavenger_pays_the_owner_and_the_technician_draws_for_the_owner(self) -> None:
        card, _ = self.lend_unit(slot="scavenger")
        self.lender.gold = 0
        self.match.player(2).gold = 0
        iron = put(self.match, 1, "iron_man")
        heard = attack(self.engine, self.game, self.match, iron.ref, card.ref, 2)
        self.assertEqual((self.lender.gold, self.match.player(2).gold), (1, 0))
        self.assertIn("As scavenger, it gives {player:3} {gold:1}", heard)

    def test_the_technician_draws_for_the_owner(self) -> None:
        """The stop: seat 3 lends seat 2 a technician, seat 1 attacks it,
        seat 3 collects the card, and nobody is left to bring home."""
        card, _ = self.lend_unit(slot="technician")
        hands = {seat: len(self.match.player(seat).hand) for seat in (1, 2, 3)}
        iron = put(self.match, 1, "iron_man")
        heard = attack(self.engine, self.game, self.match, iron.ref, card.ref, 2)
        self.assertIn("As technician, it draws {player:3} a card.", heard)
        self.assertEqual(len(self.match.player(3).hand), hands[3] + 1)
        self.assertEqual(len(self.match.player(2).hand), hands[2])
        self.assertNotIn(card, self.match.player(2).play)

    def test_a_kill_of_a_lent_card_pays_the_free_gold_to_the_killer(self) -> None:
        card, _ = self.lend_unit()
        self.match.player(1).gold = 0
        iron = put(self.match, 1, "iron_man")
        heard = attack(self.engine, self.game, self.match, iron.ref, card.ref, 2)
        self.assertEqual(self.match.player(1).gold, 1)
        self.assertIn("{player:1} collects {gold:1}", heard)

    def test_an_effect_on_the_borrowers_units_reaches_a_lent_card(self) -> None:
        """Bloom-style "your units": the borrower's controller reading is
        the card's controller, so a lent card is read as theirs."""
        card, _ = self.lend_unit()
        self.assertEqual(self.engine.seat_of(self.match, card), 2)
        self.assertIn(card, [one for one in self.match.player(2).play])
        self.assertNotIn(card, self.match.player(3).play)

    def test_lent_flags_are_saved_only_while_set(self) -> None:
        self.assertNotIn('"lent"', repr(self.match.to_dict()))
        card, _ = self.lend_unit()
        saved = self.match.to_dict()
        row = next(one for one in saved["players"][1]["play"] if one["id"] == card.id)
        self.assertTrue(row["lent"])
        loaded = MatchState.from_dict(saved)
        self.assertTrue(loaded.instance(card.id).lent)
        loaded.validate(self.engine.catalog)
        for one in saved["players"][1]["play"]:
            one.pop("lent", None)
        self.assertFalse(MatchState.from_dict(saved).instance(card.id).lent)

    def test_a_turn_that_lends_replays(self) -> None:
        """The journal replays the lock that lends: the lock is journalled
        only where a choice is asked before the next turn begins, so the
        entries are written as the driver writes them."""
        card = put(self.match, 3, "tenderfoot")
        start = history.position(self.match)
        journal = [
            {"action": Action(PromptKind.MAIN_ACTION, "end_main").to_dict(), "outcomes": []},
            {"action": Action(PromptKind.PATROL, arguments={
                "assignment": {}, "lent": {"2": {"elite": card.ref}}}).to_dict(), "outcomes": []},
        ]
        replayed = history.replay(RulesEngine(seed=11), self.game, start, journal)
        lent = replayed.instance(card.id)
        self.assertEqual((lent.lent, lent.controller, lent.patrol_slot), (True, 2, "elite"))
        self.assertEqual(replayed.to_dict()["players"][1]["play"][0]["lent"], True)

    def test_taking_back_the_end_of_the_turn_takes_the_lending_back(self) -> None:
        card, _ = self.lend_unit()
        self.assertEqual(history.end_of_turn_owner(self.engine, self.game, self.match), 3)
        history.undo_end_of_turn(self.engine, self.game, self.match)
        self.assertEqual(self.match.active, 3)
        back = self.match.instance(card.id)
        self.assertEqual((back.controller, back.lent, back.patrol_slot), (3, False, None))
        self.assertIn(back, self.match.player(3).play)
        self.assertNotIn(back, self.match.player(2).play)


class LentHeroTests(unittest.TestCase):
    """A lent hero stays on its owner's list, controlled by the borrower
    until their upkeep, and sits in the borrower's slot spelled
    `<owner seat>:hero:<slug>` (Rulebook p. 14)."""

    def setUp(self) -> None:
        self.engine, self.game, self.match = free_for_all(first=3)
        hero_in_play(self.match, 3, level=3)
        hero_in_play(self.match, 1, level=2)
        self.hero = self.match.player(3).heroes[0]
        self.ref = f"hero:{self.hero.slug}"
        self.lent_ref = f"3:{self.ref}"
        self.match.turn_snapshots[-1] = history.position(self.match)
        lock(self.engine, self.game, self.match, lent={"2": {"squad_leader": self.ref}})

    def test_the_hero_is_lent_and_stays_on_its_owners_list(self) -> None:
        self.assertEqual(self.hero.lent_to, 2)
        self.assertEqual(self.hero.patrol_slot, "squad_leader")
        self.assertIn(self.hero, self.match.player(3).heroes)
        self.assertNotIn(self.hero, self.match.player(3).heroes_in_play)
        self.assertEqual(self.match.patrollers(2), {"squad_leader": self.lent_ref})
        self.assertEqual(self.match.patrollers(3), {})
        self.assertEqual(self.engine.seat_of(self.match, self.hero), 2)
        self.assertIs(self.match.hero_on(2, self.lent_ref), self.hero)
        self.assertIsNone(self.match.hero_on(1, self.lent_ref))

    def test_the_saved_match_holds_it_and_validates(self) -> None:
        saved = self.match.to_dict()
        self.assertEqual(saved["players"][2]["heroes"][0]["lent_to"], 2)
        loaded = MatchState.from_dict(saved)
        loaded.validate(self.engine.catalog)
        self.assertEqual(loaded.patrollers(2), {"squad_leader": self.lent_ref})

    def test_it_is_a_defender_on_the_borrowers_side(self) -> None:
        iron = put(self.match, 1, "iron_man")
        apply(self.engine, self.game, self.match, Action(
            PromptKind.MAIN_ACTION, "attack", {"attacker": iron.ref}))
        prompt = pending_prompt(self.engine, self.game, self.match)
        offered = dict(zip(prompt.options.defenders, prompt.options.seats))
        self.assertEqual(offered[self.lent_ref], 2)
        heard = said(apply(self.engine, self.game, self.match, Action(
            PromptKind.CHOOSE_DEFENDER, arguments={"defender": self.lent_ref, "against": 2})))
        self.assertGreater(self.hero.damage, 0)
        self.assertIn("{hero:", heard)

    def test_a_lent_hero_that_dies_goes_to_its_owner_and_the_borrowers_opponents_level(self) -> None:
        """Question 18: the levels go to a hero of an opponent of its
        controller -- the borrower -- the active player choosing; the
        hero leaves play to its owner's command zone with its runes."""
        self.hero.damage = 99
        killer = self.match.player(1).heroes[0]
        level = killer.level
        iron = put(self.match, 1, "iron_man")
        heard = attack(self.engine, self.game, self.match, iron.ref, self.lent_ref, 2)
        self.assertEqual((self.hero.zone, self.hero.lent_to, self.hero.patrol_slot, self.hero.level),
                         ("command", None, None, 1))
        self.assertEqual(self.hero.summoning_runes, 2)
        self.assertEqual(killer.level, level + 2)
        self.assertIn("dies and returns to the command zone", heard)
        self.assertEqual(self.match.patrollers(2), {})

    def test_a_lent_hero_at_zero_hp_dies_in_settle(self) -> None:
        self.hero.damage = 999
        result = StepResult()
        board.settle(self.engine, self.match, result, cause=1)
        self.assertEqual((self.hero.zone, self.hero.lent_to), ("command", None))

    def test_it_goes_home_readied_and_never_patrols_the_owners_zone(self) -> None:
        self.hero.exhausted = True
        lock(self.engine, self.game, self.match)
        self.assertEqual(self.match.active, 2)
        self.assertEqual((self.hero.lent_to, self.hero.patrol_slot, self.hero.exhausted), (None, None, False))
        self.assertIn(self.hero, self.match.player(3).heroes_in_play)
        self.assertEqual(self.match.patrollers(3), {})

    def test_the_owner_cannot_use_it_while_it_is_lent(self) -> None:
        self.assertNotIn(self.ref, self.engine.patrol_candidates(self.match)
                         if self.match.active == 3 else ())
        self.match.active = 3
        self.assertNotIn(self.ref, self.engine.attackers(self.match))
        self.assertNotIn(self.ref, self.engine.patrol_candidates(self.match))


if __name__ == "__main__":
    unittest.main()
