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


if __name__ == "__main__":
    unittest.main()
