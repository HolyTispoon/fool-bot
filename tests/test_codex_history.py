"""
The groundwork for undo (docs/codex-bot.md, decision 11): a snapshot at
every turn start, the turn's journal written at `driver.apply`, a replay
that reproduces a position byte for byte -- the recorded shuffles handed
back, so an undo past a draw deals the same cards -- the two undos over
the snapshots, and the fine undo over the journal: the points between
the turn's actions, a card off a deck's top closing every point before
it, and the other player's tech answer kept through the cut
(docs/design/codex.md, "The undos").
"""

from __future__ import annotations

import json
import unittest

from codex import history
from codex.engine import RulesEngine
from codex.flow import driver
from codex.game import RuleRefusal
from codex.prompts import Action, PromptKind, pending_prompt, standing_prompts

from codex_positions import begin, hand, hero_in_play, new_game, put


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
        # The turn's confirmed tech is taken back and asked again, before
        # the main phase's actions (the author, 2026-10-10) ...
        prompt = pending_prompt(self.engine, self.game, self.match)
        self.assertEqual((prompt.kind, prompt.asked_player), (PromptKind.TECH_CHOICE, 1))
        self.assertEqual(self.match.player(1).codex["iron_man"],
                         self.turn_3["players"][0]["codex"]["iron_man"] + 2)
        # ... and the other player's tech answer went with the turn.
        self.assertIsNone(self.match.player(2).tech_choice)
        # The same picks again: the turn's start as it was, and the
        # snapshot is the position the choice was asked again on.
        self.assertEqual(self.match.turn_snapshots[-1], history.position(self.match))
        apply(self.engine, self.game, self.match, PromptKind.TECH_CHOICE,
              arguments={"player": 1, "picks": ["iron_man", "iron_man"]})
        apply(self.engine, self.game, self.match, PromptKind.TECH_CONFIRM, "confirm", {"player": 1})
        start = {key: value for key, value in self.turn_3.items()
                 if key not in ("turn_snapshots", "journal")}
        self.assertEqual(history.position(self.match), start)
        prompt = pending_prompt(self.engine, self.game, self.match)
        self.assertEqual((prompt.kind, prompt.asked_player), (PromptKind.MAIN_ACTION, 1))

    def test_undo_to_the_start_of_the_previous_turn(self) -> None:
        self.play_turn_3()
        history.undo_to_previous_turn(self.match)
        self.assertEqual(self.match.to_dict(), self.turn_2)
        prompt = pending_prompt(self.engine, self.game, self.match)
        self.assertEqual((prompt.kind, prompt.asked_player), (PromptKind.MAIN_ACTION, 2))
        standing = standing_prompts(self.engine, self.match, self.game)
        self.assertEqual([(p.kind, p.asked_player) for p in standing],
                         [(PromptKind.TECH_CHOICE, 1)])

    def test_an_undo_starts_a_standing_tech_choice_over(self) -> None:
        """A pick made before the turn's start is in its snapshot, and
        the undo clears it all the same: the player chooses again (the
        author, 2026-10-10)."""
        engine, game, match = new_game(seed=11)
        begin(engine, game, match)
        end_turn(engine, game, match)
        end_turn(engine, game, match)
        # Seat 2 picks while seat 1's turn 3 waits on its own tech.
        apply(engine, game, match, PromptKind.TECH_CHOICE,
              arguments={"player": 2, "picks": ["leaping_lizard", "cloud_sprite"]})
        apply(engine, game, match, PromptKind.TECH_CHOICE,
              arguments={"player": 1, "picks": ["iron_man", "iron_man"]})
        apply(engine, game, match, PromptKind.TECH_CONFIRM, "confirm", {"player": 1})
        self.assertEqual(history.latest_snapshot(match)["players"][1]["tech_choice"],
                         ["leaping_lizard", "cloud_sprite"])
        history.undo_to_turn_start(match)
        self.assertEqual(history.tech_started_over(match), (1, 2))
        self.assertIsNone(match.player(2).tech_choice)
        standing = standing_prompts(engine, match, game)
        self.assertEqual([(p.kind, p.asked_player, p.options.picks) for p in standing],
                         [(PromptKind.TECH_CHOICE, 2, ())])

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
        self.assertEqual(history.undo_points(self.engine, self.game, self.match), ())

    # -- The fine undo -------------------------------------------------------

    def test_the_points_are_between_the_active_players_actions(self) -> None:
        """Turn 3's journal: the hire, the other player's tech answer, the
        play with its targets, their tech answer again. One point is
        open: before the play -- not before the tech answer, which is
        theirs, nor inside the spell, nor at the start, which
        `undo_targets` offers."""
        self.play_turn_3()
        engine, game, match = self.engine, self.game, self.match
        (point,) = history.undo_points(engine, game, match)
        self.assertEqual((point.index, point.number, point.choice, point.of), (2, 2, "play", len(match.journal)))
        self.assertIn("plays", point.said[0])
        self.assertIn("{card:", point.said[0])

    def test_undo_to_a_point_keeps_what_came_before_and_the_other_players_tech(self) -> None:
        self.play_turn_3()
        engine, game, match = self.engine, self.game, self.match
        journal = list(match.journal)
        said = history.undo_to(engine, game, match, 2, of=len(journal))
        # The hire kept, the play gone, the tech answer saved after the
        # cut kept too (`cut`), and the position the replay of exactly
        # that reaches.
        self.assertEqual(match.player(1).workers, 5)
        self.assertEqual(match.player(2).tech_choice, ["maestro", "cloud_sprite"])
        self.assertIs(pending_prompt(engine, game, match).kind, PromptKind.MAIN_ACTION)
        kept = history.cut(journal, 2)
        self.assertEqual([entry["action"]["kind"] for entry in kept], ["main_action", "tech_choice", "tech_choice"])
        again = history.replay(RulesEngine(seed=5), game, match.turn_snapshots[-1], kept,
                               history=match.turn_snapshots)
        self.assertEqual(history.position(match), history.position(again))
        self.assertEqual(len(match.journal), len(kept))
        # What the turn says now: the hire's line, then the undone line.
        self.assertEqual(len(said), 2)
        self.assertIn("hires a worker", said[0])
        self.assertEqual(said[-1], history.undone_to(2))

    def test_a_point_not_offered_is_refused(self) -> None:
        self.play_turn_3()
        engine, game, match = self.engine, self.game, self.match
        before = match.to_dict()
        for index in (0, 1, len(match.journal)):
            with self.assertRaises(RuleRefusal):
                history.undo_to(engine, game, match, index)
        # The turn has moved on since the menu was built.
        with self.assertRaises(RuleRefusal):
            history.undo_to(engine, game, match, 2, of=len(match.journal) + 1)
        self.assertEqual(match.to_dict(), before)

    def test_the_tech_asked_again_after_a_turn_start_undo_is_no_action(self) -> None:
        """After an undo to the turn's start the active player's tech is
        asked again in the main phase, and its choice and confirmation
        open the journal: no action of the turn, so the hire after them
        is action 1 and the play action 2 -- and the point before the
        hire is a point of its own, the main phase with the tech
        settled, which the turn's start is not."""
        self.play_turn_3()
        engine, game, match = self.engine, self.game, self.match
        history.undo_to_turn_start(match)
        self.assertIs(pending_prompt(engine, game, match).kind, PromptKind.TECH_CHOICE)
        apply(engine, game, match, PromptKind.TECH_CHOICE,
              arguments={"player": 1, "picks": ["iron_man", "iron_man"]})
        apply(engine, game, match, PromptKind.TECH_CONFIRM, "confirm", {"player": 1})
        self.assertEqual(history.undo_points(engine, game, match), ())
        player = match.player(1)
        apply(engine, game, match, PromptKind.MAIN_ACTION, "hire", {"slug": player.hand[0]})
        cheapest = min(
            (row for row in pending_prompt(engine, game, match).options.playable if row.allowed),
            key=lambda row: row.cost,
        )
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", {"slug": cheapest.slug})
        while (asked := pending_prompt(engine, game, match)).kind is PromptKind.TARGET:
            apply(engine, game, match, PromptKind.TARGET,
                  arguments={"target": asked.options.targets[0].key})
        points = history.undo_points(engine, game, match)
        self.assertEqual([(p.index, p.number, p.choice) for p in points], [(2, 1, "hire"), (3, 2, "play")])

    def test_a_turn_that_no_longer_replays_offers_no_points(self) -> None:
        """A journal entry the rules now refuse -- a game saved before a
        rule changed -- closes the fine undo; the snapshots' undos still
        stand."""
        self.play_turn_3()
        engine, game, match = self.engine, self.game, self.match
        match.journal[0]["action"]["arguments"]["slug"] = "appel_stomp"
        self.assertEqual(history.undo_points(engine, game, match), ())
        with self.assertRaises(RuleRefusal):
            history.undo_to(engine, game, match, 2)
        self.assertIn(history.TURN_START, history.undo_targets(match))


def staged(match) -> None:
    """The hand-staged position as the turn's start, as the spell tests
    stage a cancel: the fine undo replays the turn from its snapshot,
    which staging by hand would bypass."""
    match.turn_snapshots[-1] = history.position(match)
    match.journal = []


class FineUndoTests(unittest.TestCase):
    """Finesse (seat 2) going first, its position staged by hand."""

    def setUp(self) -> None:
        engine, game, match = new_game(seed=3, first=2)
        begin(engine, game, match)
        self.engine, self.game, self.match = engine, game, match
        match.player(2).gold = 20

    def test_a_card_off_a_decks_top_closes_every_point_before_it(self) -> None:
        """Appel Stomp draws its caster a card: a card seen cannot be
        unseen, so no point before the cast is open -- the start of the
        turn aside -- while the point after it is."""
        engine, game, match = self.engine, self.game, self.match
        hero_in_play(match, 2, level=5)
        match.player(2).hero.max_level_since_turn_began = True
        put(match, 1, "iron_man", patrol="squad_leader")
        hand(match, 2, "appel_stomp", "timely_messenger")
        staged(match)
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", {"slug": "timely_messenger"})
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", {"slug": "appel_stomp"})
        self.assertIs(pending_prompt(engine, game, match).kind, PromptKind.APPEL_STOMP_TOP)
        apply(engine, game, match, PromptKind.APPEL_STOMP_TOP, "top")
        apply(engine, game, match, PromptKind.MAIN_ACTION, "end_main")
        (point,) = history.undo_points(engine, game, match)
        self.assertEqual((point.index, point.number, point.choice, point.said), (3, 3, "end_main", ()))
        with self.assertRaises(RuleRefusal):
            history.undo_to(engine, game, match, 1)
        self.assertEqual(history.undo_to(engine, game, match, 3)[-1], history.undone_to(3))
        self.assertEqual(match.phase, "main")
        self.assertIn(history.TURN_START, history.undo_targets(match))

    def test_an_action_that_changed_nothing_is_no_point(self) -> None:
        """An attacker declared and taken back before its defender left
        the position as it was: no point of its own, and no number."""
        engine, game, match = self.engine, self.game, self.match
        unit = put(match, 2, "timely_messenger")
        hand(match, 2, "spark", "tenderfoot")
        staged(match)
        apply(engine, game, match, PromptKind.MAIN_ACTION, "hire", {"slug": "spark"})
        apply(engine, game, match, PromptKind.MAIN_ACTION, "attack", {"attacker": f"unit:{unit.id}"})
        apply(engine, game, match, PromptKind.CHOOSE_DEFENDER, "cancel")
        apply(engine, game, match, PromptKind.MAIN_ACTION, "play", {"slug": "tenderfoot"})
        self.assertEqual(len(match.journal), 4)
        (point,) = history.undo_points(engine, game, match)
        self.assertEqual((point.index, point.number, point.choice), (3, 2, "play"))


if __name__ == "__main__":
    unittest.main()
