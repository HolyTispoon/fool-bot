"""
The groundwork for undo (docs/codex-bot.md, decision 11): a snapshot at
every turn start, the turn's journal written at `driver.apply`, a replay
that reproduces a position byte for byte -- the recorded shuffles handed
back, so an undo past a draw deals the same cards -- and the two undos
over the snapshots.
"""

from __future__ import annotations

import json
import unittest

from codex import history
from codex.engine import RulesEngine
from codex.flow import driver
from codex.prompts import Action, PromptKind, pending_prompt, standing_prompts

from codex_positions import begin, new_game


def apply(engine, game, match, *args, **kwargs):
    run = driver.apply(engine, game, match, Action(*args, **kwargs))
    assert not isinstance(run, driver.Refusal), run
    return run


def end_turn(engine, game, match):
    apply(engine, game, match, PromptKind.MAIN_ACTION, "end_main")
    apply(engine, game, match, PromptKind.PATROL, arguments={"assignment": {}})


class HistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        engine, game, match = new_game(seed=11)
        begin(engine, game, match)
        self.engine, self.game, self.match = engine, game, match
        self.turn_1 = match.to_dict()
        end_turn(engine, game, match)
        # Seat 2's first turn began inside that apply: no tech is owed.
        self.turn_2 = match.to_dict()
        end_turn(engine, game, match)
        # Seat 1 now opens turn 3 on its tech choice. A short deck, so
        # this turn's draw has to shuffle the discard pile in.
        player = match.player(1)
        player.deck = player.deck[:1]
        apply(engine, game, match, PromptKind.TECH_CHOICE,
              arguments={"player": 1, "picks": ["iron_man", "iron_man"]})
        apply(engine, game, match, PromptKind.TECH_CONFIRM, "confirm", {"player": 1})
        self.turn_3 = match.to_dict()

    def play_turn_3(self) -> None:
        engine, game, match = self.engine, self.game, self.match
        self.targets = 0
        player = match.player(1)
        apply(engine, game, match, PromptKind.MAIN_ACTION, "hire", {"slug": player.hand[0]})
        apply(engine, game, match, PromptKind.TECH_CHOICE,
              arguments={"player": 2, "picks": ["leaping_lizard", "cloud_sprite"]})
        cheapest = min(
            (row for row in pending_prompt(engine, game, match).options.playable if row.allowed),
            key=lambda row: row.cost,
        )
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", {"slug": cheapest.slug})
        # A card whose arrives trigger asks a target (step 6) is answered
        # in its own action, journalled like any other.
        while (asked := pending_prompt(engine, game, match)).kind is PromptKind.TARGET:
            apply(engine, game, match, PromptKind.TARGET,
                  arguments={"target": asked.options.targets[0].key})
            self.targets += 1
        apply(engine, game, match, PromptKind.TECH_CHOICE,
              arguments={"player": 2, "picks": ["maestro", "cloud_sprite"]})

    def test_the_journal_is_empty_when_a_turn_begins(self) -> None:
        self.assertEqual(self.turn_3["journal"], [])
        self.assertEqual([s["turn"] for s in self.match.turn_snapshots], [1, 2, 3])

    def test_replaying_the_journal_reproduces_the_position(self) -> None:
        """The turn's actions -- a hire, a card, the other player's tech
        answered twice, the patrol lock and a draw that reshuffles --
        replayed from the turn-start snapshot by an engine with another
        seed give the same position, byte for byte."""
        self.play_turn_3()
        end_turn(self.engine, self.game, self.match)
        self.assertEqual(self.match.active, 2)
        journal = self.match.journal
        self.assertEqual(len(journal), 6 + self.targets)
        self.assertTrue(any(entry["outcomes"] for entry in journal),
                        "the draw should have reshuffled")
        original = json.dumps(self.match.to_dict(), sort_keys=True)
        replayed = history.replay(
            RulesEngine(seed=999), self.game, self.match.turn_snapshots[-1],
            journal, history=self.match.turn_snapshots,
        )
        self.assertEqual(json.dumps(replayed.to_dict(), sort_keys=True), original)

    def test_a_prefix_of_the_journal_is_a_point_in_the_turn(self) -> None:
        self.play_turn_3()
        replayed = history.replay(RulesEngine(seed=5), self.game,
                                  self.match.turn_snapshots[-1], self.match.journal[:2])
        after_two = history.position(replayed)
        self.assertEqual(after_two["players"][0]["workers"], 5)
        self.assertEqual(after_two["players"][1]["tech_choice"], ["leaping_lizard", "cloud_sprite"])

    def test_undo_to_the_start_of_this_turn(self) -> None:
        self.play_turn_3()
        self.assertEqual(set(history.undo_targets(self.match)),
                         {history.TURN_START, history.PREVIOUS_TURN})
        history.undo_to_turn_start(self.match)
        self.assertEqual(self.match.to_dict(), self.turn_3)
        prompt = pending_prompt(self.engine, self.game, self.match)
        self.assertIs(prompt.kind, PromptKind.MAIN_ACTION)
        self.assertEqual(prompt.asked_player, 1)
        # The other player's tech answer went with the turn.
        self.assertIsNone(self.match.player(2).tech_choice)

    def test_undo_to_the_start_of_the_previous_turn(self) -> None:
        self.play_turn_3()
        history.undo_to_previous_turn(self.match)
        self.assertEqual(self.match.to_dict(), self.turn_2)
        prompt = pending_prompt(self.engine, self.game, self.match)
        self.assertEqual((prompt.kind, prompt.asked_player), (PromptKind.MAIN_ACTION, 2))
        standing = standing_prompts(self.engine, self.match, self.game)
        self.assertEqual([(p.kind, p.asked_player) for p in standing],
                         [(PromptKind.TECH_CHOICE, 1)])

    def test_an_undo_past_a_draw_deals_the_same_cards(self) -> None:
        """Undo cannot be used to redraw: replaying the turn deals what
        it dealt."""
        self.play_turn_3()
        end_turn(self.engine, self.game, self.match)
        dealt = list(self.match.player(1).hand)
        journal = list(self.match.journal)
        snapshot = self.match.turn_snapshots[-1]
        again = history.replay(RulesEngine(seed=12345), self.game, snapshot, journal)
        self.assertEqual(again.player(1).hand, dealt)

    def test_the_snapshots_are_bounded_to_three(self) -> None:
        engine, game, match = self.engine, self.game, self.match
        for _ in range(4):
            seat = match.active
            if pending_prompt(engine, game, match).kind is PromptKind.TECH_CHOICE:
                picks = [slug for slug, count in engine.codex_counts(match.player(seat)) if count][:1] * 2
                apply(engine, game, match, PromptKind.TECH_CHOICE,
                      arguments={"player": seat, "picks": picks})
            if pending_prompt(engine, game, match).kind is PromptKind.TECH_CONFIRM:
                apply(engine, game, match, PromptKind.TECH_CONFIRM, "confirm", {"player": seat})
            self.assertEqual(match.journal, [])
            end_turn(engine, game, match)
            self.assertLessEqual(len(match.turn_snapshots), history.KEPT_SNAPSHOTS)
        self.assertEqual([s["turn"] for s in match.turn_snapshots][-1], match.turn - 1)

    def test_no_undo_once_the_game_is_over(self) -> None:
        self.match.winner = 1
        self.assertEqual(history.undo_targets(self.match), {})


if __name__ == "__main__":
    unittest.main()
