"""
A helper's corrections by hand (`codex.flow.edits`, `/codex debug`): a
unit or hero moved into, between and out of patrol slots, damage and
runes added and removed, each keeping the rules a position holds and
none killing; journalled, so a replay
makes it again, never an undo point of its own, and taken back by an
undo to before it (docs/design/codex.md, "Corrections by hand").
"""

from __future__ import annotations

import unittest

from codex import history
from codex.flow import driver, edits
from codex.game import RuleRefusal
from codex.prompts import Action, PromptKind, pending_prompt

from codex_positions import begin, hero, hero_in_play, new_game, put


def apply(engine, game, match, *args, **kwargs):
    run = driver.apply(engine, game, match, Action(*args, **kwargs))
    assert not isinstance(run, driver.Refusal), run
    return run


class CorrectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine, self.game, self.match = new_game(seed=11)
        begin(self.engine, self.game, self.match)

    def correct(self, edit):
        return edits.correct(self.engine, self.match, edit).narration

    def test_a_unit_patrols_moves_between_slots_and_leaves(self) -> None:
        card = put(self.match, 2, "tenderfoot")
        self.assertEqual(self.correct(edits.patrol(2, card.ref, "elite")),
                         ["Corrected: {player:2}'s {card:tenderfoot} patrols as elite."])
        self.assertEqual(self.match.patrollers(2), {"elite": card.ref})
        self.correct(edits.patrol(2, card.ref, "lookout"))
        self.assertEqual(self.match.patrollers(2), {"lookout": card.ref})
        self.assertEqual(self.correct(edits.patrol(2, card.ref, edits.OFF)),
                         ["Corrected: {player:2}'s {card:tenderfoot} leaves the patrol zone."])
        self.assertEqual(self.match.patrollers(2), {})

    def test_a_squad_leader_gets_its_armor_on_another_players_turn_and_loses_it_leaving(self) -> None:
        card = put(self.match, 2, "tenderfoot")
        self.correct(edits.patrol(2, card.ref, "squad_leader"))
        self.assertEqual(card.armor, 1)
        self.correct(edits.patrol(2, card.ref, "elite"))
        self.assertEqual(card.armor, 0)

    def test_a_hero_patrols(self) -> None:
        hero_in_play(self.match, 2)
        ref = hero(self.match, 2)
        self.correct(edits.patrol(2, ref, "technician"))
        self.assertEqual(self.match.patrollers(2), {"technician": ref})

    def test_what_a_position_holds_is_refused(self) -> None:
        tired = put(self.match, 2, "tenderfoot", exhausted=True)
        leader = put(self.match, 2, "older_brother", patrol="squad_leader")
        fresh = put(self.match, 2, "tenderfoot")
        with self.assertRaises(RuleRefusal) as refused:
            self.correct(edits.patrol(2, tired.ref, "elite"))
        self.assertEqual(refused.exception.cite, "UMR p. 16")
        with self.assertRaisesRegex(RuleRefusal, "already holds"):
            self.correct(edits.patrol(2, fresh.ref, "squad_leader"))
        with self.assertRaisesRegex(RuleRefusal, "already patrols"):
            self.correct(edits.patrol(2, leader.ref, "squad_leader"))
        with self.assertRaisesRegex(RuleRefusal, "isn't patrolling"):
            self.correct(edits.patrol(2, fresh.ref, edits.OFF))
        with self.assertRaisesRegex(RuleRefusal, "not a unit or hero"):
            self.correct(edits.patrol(2, "unit:999", "elite"))
        self.assertEqual(self.match.journal, [], "a refusal writes nothing")

    def test_damage_is_added_and_removed_and_never_kills(self) -> None:
        card = put(self.match, 1, "iron_man", damage=1)
        self.assertEqual(self.correct(edits.damage(1, card.ref, 2)),
                         ["Corrected: {player:1}'s {card:iron_man} now has 3 damage, 1 HP of 4."])
        self.correct(edits.damage(1, card.ref, -3))
        self.assertEqual(card.damage, 0)
        with self.assertRaisesRegex(RuleRefusal, "only 0 damage"):
            self.correct(edits.damage(1, card.ref, -1))
        with self.assertRaisesRegex(RuleRefusal, "would destroy it"):
            self.correct(edits.damage(1, card.ref, 4))
        self.assertEqual(card.damage, 0)

    def test_damage_names_no_card_without_hp(self) -> None:
        upgrade = put(self.match, 1, "might_of_leaf_and_claw")
        with self.assertRaisesRegex(RuleRefusal, "not a unit, hero or building card"):
            self.correct(edits.damage(1, upgrade.ref, 1))

    def test_a_named_rune_goes_on_any_card_in_play_and_comes_off(self) -> None:
        upgrade = put(self.match, 1, "might_of_leaf_and_claw")
        self.assertEqual(self.correct(edits.rune(1, upgrade.ref, "growth", 3)),
                         ["Corrected: {player:1}'s {card:might_of_leaf_and_claw} now has 3 growth runes."])
        self.correct(edits.rune(1, upgrade.ref, "growth", -3))
        self.assertEqual(upgrade.runes, {})
        with self.assertRaisesRegex(RuleRefusal, "has no growth runes to remove"):
            self.correct(edits.rune(1, upgrade.ref, "growth", -1))

    def test_a_plus_rune_cancels_a_minus_rune_as_the_rules_do(self) -> None:
        card = put(self.match, 1, "iron_man")
        card.minus_runes = 1
        self.assertEqual(self.correct(edits.rune(1, card.ref, edits.PLUS, 2)),
                         ["Corrected: {player:1}'s {card:iron_man} now has 1 +1/+1 rune and no -1/-1 runes."])
        self.assertEqual((card.plus_runes, card.minus_runes), (1, 0))
        self.correct(edits.rune(1, card.ref, edits.PLUS, -1))
        self.assertEqual(card.plus_runes, 0)

    def test_no_rune_change_kills(self) -> None:
        card = put(self.match, 1, "tenderfoot", damage=1)
        with self.assertRaisesRegex(RuleRefusal, "would destroy"):
            self.correct(edits.rune(1, card.ref, edits.MINUS, 1))
        self.assertEqual((card.minus_runes, card.plus_runes), (0, 0), "put back as it was")
        upgrade = put(self.match, 1, "might_of_leaf_and_claw")
        with self.assertRaisesRegex(RuleRefusal, "no ATK or HP"):
            self.correct(edits.rune(1, upgrade.ref, edits.PLUS, 1))

    def test_time_runes_but_never_a_fading_cards_last(self) -> None:
        card = put(self.match, 1, "tenderfoot")
        self.correct(edits.rune(1, card.ref, edits.TIME, 2))
        self.correct(edits.rune(1, card.ref, edits.TIME, -2))
        self.assertEqual(card.time_runes, 0)
        _, _, scratch = new_game()
        fading = next(slug for slug, printed in self.engine.catalog.cards.items()
                      if printed.is_unit and self.engine.fading(put(scratch, 2, slug)))
        faded = put(self.match, 2, fading)
        faded.time_runes = 1
        with self.assertRaisesRegex(RuleRefusal, "last time rune"):
            self.correct(edits.rune(2, faded.ref, edits.TIME, -1))

    def test_the_targets_are_what_each_correction_may_name(self) -> None:
        card = put(self.match, 2, "tenderfoot", patrol="elite", damage=1)
        card.runes = {"feather": 1}
        upgrade = put(self.match, 1, "might_of_leaf_and_claw")
        hero_in_play(self.match, 1)
        named = lambda edit: {(target.seat, target.ref) for target in edits.targets(self.engine, self.match, edit)}
        self.assertEqual(named(edits.PATROL), {(2, card.ref), (1, hero(self.match, 1))})
        self.assertEqual(named(edits.DAMAGE), named(edits.PATROL))
        self.assertEqual(named(edits.RUNE), named(edits.PATROL) | {(1, upgrade.ref)})
        found = {(target.seat, target.ref): target for target in edits.targets(self.engine, self.match, edits.RUNE)}
        self.assertEqual((found[2, card.ref].hp, found[2, card.ref].max_hp, found[2, card.ref].slot,
                          found[2, card.ref].runes), (1, 2, "elite", (("feather", 1),)))
        self.assertIsNone(found[1, upgrade.ref].max_hp)

    def test_every_rune_the_board_draws_may_be_named(self) -> None:
        from codex.render import RUNE_COLORS, SINGLE_RUNES

        self.assertLessEqual(set(RUNE_COLORS) | set(SINGLE_RUNES), set(edits.NAMED_RUNES))


class JournalTests(unittest.TestCase):
    """Turn 1, staged: a hire, a correction, a play."""

    def setUp(self) -> None:
        engine, game, match = new_game(seed=11)
        begin(engine, game, match)
        self.engine, self.game, self.match = engine, game, match
        self.foe = put(match, 2, "tenderfoot")
        match.turn_snapshots[-1] = history.position(match)
        player = match.player(1)
        apply(engine, game, match, PromptKind.MAIN_ACTION, "hire", {"slug": player.hand[1]})
        edits.correct(engine, match, edits.patrol(2, self.foe.ref, "elite"))
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", {"slug": "tenderfoot"})

    def test_it_is_journalled_and_a_replay_makes_it_again(self) -> None:
        match = self.match
        self.assertEqual([entry["action"]["kind"] for entry in match.journal],
                         ["main_action", "edit", "main_action"])
        again = history.replay(self.engine, self.game, match.turn_snapshots[-1], match.journal,
                               history=match.turn_snapshots)
        self.assertEqual(history.position(again), history.position(match))

    def test_it_is_no_undo_point_and_an_undo_to_after_it_keeps_it(self) -> None:
        engine, game, match = self.engine, self.game, self.match
        points = history.undo_points(engine, game, match)
        self.assertEqual([(point.index, point.choice) for point in points], [(2, "play")])
        history.undo_to(engine, game, match, 2, of=len(match.journal))
        self.assertEqual(match.patrollers(2), {"elite": self.foe.ref})
        self.assertIs(pending_prompt(engine, game, match).kind, PromptKind.MAIN_ACTION)

    def test_the_undo_to_the_turns_start_takes_it_back(self) -> None:
        history.undo_to_turn_start(self.match)
        self.assertEqual(self.match.patrollers(2), {})

    def test_a_correction_closes_taking_back_the_end_of_the_turn(self) -> None:
        engine, game, match = self.engine, self.game, self.match
        apply(engine, game, match, PromptKind.MAIN_ACTION, "end_main")
        apply(engine, game, match, PromptKind.PATROL, arguments={"assignment": {}})
        self.assertEqual(history.end_of_turn_owner(engine, game, match), 1)
        edits.correct(engine, match, edits.damage(2, self.foe.ref, 1))
        self.assertIsNone(history.end_of_turn_owner(engine, game, match))


if __name__ == "__main__":
    unittest.main()
