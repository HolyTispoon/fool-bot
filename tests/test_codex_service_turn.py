"""
What step 4 asked of the Codex model and service for the turn on
Discord (docs/codex-bot.md, step 4): the panel's readings carried on
the prompt -- the hand the picture numbers, why each defender is legal
-- the end of the turn closed as its own group with its own position
(`draw_after`), and the undos as service methods that save once -- the
fine undo's result the turn as it now reads.
"""

from __future__ import annotations

import unittest

from codex import history
from codex.engine import RulesEngine
from codex.flow.result import FollowOnStep
from codex.prompts import Action, PromptKind, pending_prompt
from codex_positions import put
from gamesaves.codex.service import Batching, GameService

TURN_END = Batching(draw_after=frozenset({FollowOnStep.BEGIN_TECH}))


class Saves:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, games) -> None:
        self.calls += 1


def started(batching: Batching = TURN_END):
    """A started game, the save count reset."""
    saves = Saves()
    svc = GameService(RulesEngine(seed=7), {}, batching, save=saves)
    game = svc.create_game(guild_id=1, channel_id=10)
    svc.take_seat(game.game_id, 101, "basher", "bashing")
    svc.take_seat(game.game_id, 202, "fencer", "finesse")
    svc.start(game.game_id)
    saves.calls = 0
    return svc, saves, game


def end_turn(svc: GameService, game_id: str):
    svc.apply_action(game_id, Action(PromptKind.MAIN_ACTION, "end_main"))
    return svc.apply_action(game_id, Action(PromptKind.PATROL, "", {"assignment": {}}))


class PromptReadingTests(unittest.TestCase):
    def test_the_main_phase_carries_the_hand_as_the_picture_numbers_it(self) -> None:
        svc, _, game = started()
        match = svc.load(game)
        prompt = pending_prompt(svc.engine, game, match)
        self.assertEqual(
            prompt.options.hand, svc.engine.hand_rows(match, match.active),
        )
        self.assertEqual([row.slug for row in prompt.options.hand], match.active_player.hand)

    def test_each_defender_carries_why_it_is_legal(self) -> None:
        """UMR p. 10: the squad leader alone while there is one; then
        any patroller; then anything with HP."""
        svc, _, game = started()
        match = svc.load(game)
        seat = match.active
        attacker = put(match, seat, "older_brother")
        engine = svc.engine
        self.assertEqual(
            {why for _, why in engine.defender_rows(match, attacker.ref)},
            {"no patrol"},
        )
        put(match, 2 if seat == 1 else 1, "tenderfoot", patrol="elite")
        self.assertEqual([why for _, why in engine.defender_rows(match, attacker.ref)], ["patroller"])
        leader = put(match, 2 if seat == 1 else 1, "iron_man", patrol="squad_leader")
        self.assertEqual(engine.defender_rows(match, attacker.ref), ((leader.ref, "squad leader"),))
        self.assertEqual(
            engine.legal_defenders(match, attacker.ref),
            tuple(ref for ref, _ in engine.defender_rows(match, attacker.ref)),
        )


class TurnHeadingTests(unittest.TestCase):
    def test_the_heading_is_the_turn_its_player_addressed_and_their_deck(self) -> None:
        from codex.formatting import turn_heading

        svc, _, game = started()
        match = svc.load(game)
        seat = match.active
        deck = match.player(seat).specs[0].title()
        self.assertEqual(turn_heading(match), f"**Turn 1** -- {{to:{seat}}} ({deck})")

    def test_a_deck_of_several_specs_is_named_by_all_of_them(self) -> None:
        """The standard game's multicolour deck: "spec1/spec2/spec3"
        (the author, 2026-10-08)."""
        from codex.formatting import deck_name

        self.assertEqual(deck_name(("bashing",)), "Bashing")
        self.assertEqual(deck_name(("anarchy", "blood", "fire")), "Anarchy/Blood/Fire")

    def test_a_team_is_named_by_its_faction_or_its_specs(self) -> None:
        """A colour's own three heroes by the faction's name, any other
        team by its specs in the order chosen, never by its heroes'
        names (the author, 2026-10-10) -- what the heading, the end of a
        turn and a test game's sides all say."""
        from codex.formatting import team_name

        self.assertEqual(team_name(("necromancy", "disease", "demonology")), "Blackhand Scourge")
        self.assertEqual(team_name(("present", "past", "future")), "Vortoss Conclave")
        self.assertEqual(team_name(("fire", "anarchy", "blood")), "Blood Anarchs")
        self.assertEqual(team_name(("balance", "feral", "growth")), "Moss Sentinels")
        self.assertEqual(team_name(("feral", "fire", "bashing")), "Feral/Fire/Bashing")
        self.assertEqual(team_name(("bashing",)), "Bashing")

    def test_copies_of_one_card_are_numbered_in_the_order_they_came(self) -> None:
        """Two Bone Collectors 3/3 read alike on two buttons, so each
        copy carries its number, as the board's picture marks it (the
        author, 2026-10-11): counted in the order they came into play,
        patrolling or not; a card with no copy has no number, and a copy
        keeps its number while the ones before it stay."""
        from codex.formatting import copy_number, ref_label
        from codex_positions import new_game

        engine, _, match = new_game()
        first = put(match, 1, "bone_collector")
        second = put(match, 1, "bone_collector", patrol="squad_leader")
        third = put(match, 1, "bone_collector", exhausted=True)
        alone = put(match, 1, "iron_man")
        theirs = put(match, 2, "bone_collector")
        label = lambda card, seat=1: ref_label(engine, match, seat, f"unit:{card.id}")
        self.assertEqual(label(first), "Bone Collector #1 3/3")
        self.assertEqual(label(second), "Bone Collector #2 3/3")
        self.assertEqual(label(third), "Bone Collector #3 3/3")
        self.assertEqual(label(alone), "Iron Man 3/4")
        self.assertEqual(label(theirs, 2), "Bone Collector 3/3")
        match.player(1).play.remove(third)
        self.assertEqual(copy_number(match.player(1), second), 2)

    def test_no_line_of_the_models_opens_a_turn(self) -> None:
        """The heading is not narration, so it is never said twice."""
        svc, _, game = started()
        result = end_turn(svc, game.game_id)
        self.assertFalse(any("**Turn " in line for line in result.lines))


class TechChoiceSaysNothingTests(unittest.TestCase):
    def test_a_tech_choice_is_said_only_in_its_owners_ready_phase(self) -> None:
        """Picking (or changing) a tech choice during the other player's
        turn says nothing; the owner's ready phase says how many cards
        went into the discard (the author, 2026-10-08)."""
        svc, _, game = started()
        owner = svc.load(game).active
        end_turn(svc, game.game_id)
        match = svc.load(game)
        picks = [slug for slug, copies in svc.engine.codex_counts(match.player(owner)) if copies][:2]
        for _ in range(2):
            saved = svc.apply_action(game.game_id, Action(
                PromptKind.TECH_CHOICE, "", {"player": owner, "picks": picks},
            ))
            self.assertIsNone(saved.refusal)
            self.assertEqual(saved.lines, ())
            self.assertFalse(saved.board_changed)
        result = end_turn(svc, game.game_id)
        confirmed = svc.apply_action(game.game_id, Action(
            PromptKind.TECH_CONFIRM, "confirm", {"player": owner},
        ))
        self.assertTrue(any("puts 2 tech cards into their discard pile" in line
                            for line in confirmed.lines))
        self.assertFalse(any("tech" in line for line in result.lines))


class TurnEndGroupTests(unittest.TestCase):
    def test_the_end_of_the_turn_is_its_own_group_with_its_own_position(self) -> None:
        svc, _, game = started()
        ending = svc.load(game).active
        result = end_turn(svc, game.game_id)
        (closing,) = [group for group in result.groups if group.step is FollowOnStep.BEGIN_TECH]
        self.assertTrue(any("draws" in line for line in closing.lines))
        # The model says the turn is over, as the group's last words,
        # naming the player and their deck; the event log says which turn.
        deck = svc.load(game).player(ending).specs[0].title()
        self.assertTrue(closing.lines[-1].endswith(
            f"**End of turn 1** -- {{player:{ending}}} ({deck})."
        ))
        ended = [event for event in result.match.events if event["kind"] == "turn_ended"]
        self.assertEqual(ended[-1]["turn"], 1)
        self.assertIsNotNone(closing.board)
        self.assertNotIn("turn_snapshots", closing.board)
        # The second turn began in the same action; what it said is
        # after the group, not in it.
        self.assertFalse(any("collects" in line for line in closing.lines))
        self.assertTrue(any("collects" in line for line in result.narration))
        self.assertNotEqual(result.match.active, ending)

    def test_without_draw_after_nothing_is_cut(self) -> None:
        svc, _, game = started(Batching())
        result = end_turn(svc, game.game_id)
        self.assertEqual(result.groups, ())


class ServiceUndoTests(unittest.TestCase):
    def test_undo_to_turn_start_restores_and_saves_once(self) -> None:
        svc, saves, game = started()
        start = history.position(svc.load(game))
        svc.apply_action(game.game_id, Action(PromptKind.MAIN_ACTION, "end_main"))
        saves.calls = 0
        result = svc.undo_to_turn_start(game.game_id)
        self.assertEqual(saves.calls, 1)
        self.assertEqual(history.position(svc.load(game)), start)
        self.assertEqual(result.narration, (history.UNDONE,))
        self.assertIs(result.prompt.kind, PromptKind.MAIN_ACTION)
        self.assertTrue(result.board_changed)

    def test_undo_to_previous_turn_goes_back_a_turn(self) -> None:
        svc, _, game = started()
        first = svc.load(game).active
        end_turn(svc, game.game_id)
        self.assertEqual(
            svc.undo_targets(game.game_id),
            {history.TURN_START: 2, history.PREVIOUS_TURN: 1},
        )
        result = svc.undo_to_previous_turn(game.game_id)
        self.assertEqual((result.match.turn, result.match.active), (1, first))
        self.assertIs(result.prompt.kind, PromptKind.MAIN_ACTION)

    def test_an_undo_with_nothing_to_go_back_to_saves_nothing(self) -> None:
        from codex.game import RuleRefusal

        svc, saves, game = started()
        with self.assertRaises(RuleRefusal):
            svc.undo_to_previous_turn(game.game_id)
        self.assertEqual(saves.calls, 0)

    def test_undo_to_a_point_saves_once_and_says_the_turn_so_far(self) -> None:
        """The hire kept, the main phase's end taken back: the result's
        lines are the hire's and the undone line -- the turn as it now
        reads, which a frontend puts under the turn's first lines."""
        svc, saves, game = started()
        hired = svc.apply_action(
            game.game_id, Action(PromptKind.MAIN_ACTION, "hire", {"slug": svc.load(game).active_player.hand[0]}),
        )
        svc.apply_action(game.game_id, Action(PromptKind.MAIN_ACTION, "end_main"))
        (point,) = svc.undo_points(game.game_id)
        self.assertEqual((point.index, point.number, point.choice, point.of), (1, 2, "end_main", 2))
        saves.calls = 0
        result = svc.undo_to(game.game_id, point.index, of=point.of)
        self.assertEqual(saves.calls, 1)
        self.assertEqual(result.narration, (*hired.lines, history.undone_to(2)))
        self.assertIs(result.prompt.kind, PromptKind.MAIN_ACTION)
        self.assertTrue(result.board_changed)
        self.assertEqual(svc.load(game).phase, "main")

    def test_the_fine_undo_keeps_the_other_players_tech_and_says_nothing_to_them(self) -> None:
        """The player whose turn just ended saves a tech choice during
        this turn; the active player undoes to before their last action:
        the choice stands (`history.cut`) and no line asks them to choose
        again -- unlike an undo to the turn's start."""
        svc, _, game = started()
        end_turn(svc, game.game_id)
        match = svc.load(game)
        other = 2 if match.active == 1 else 1
        picks = [slug for slug, count in svc.engine.codex_counts(match.player(other)) if count][:1] * 2
        svc.apply_action(game.game_id, Action(PromptKind.MAIN_ACTION, "hire", {"slug": match.active_player.hand[0]}))
        svc.apply_action(game.game_id, Action(PromptKind.TECH_CHOICE, "", {"player": other, "picks": picks}))
        svc.apply_action(game.game_id, Action(PromptKind.MAIN_ACTION, "end_main"))
        (point,) = svc.undo_points(game.game_id)
        self.assertEqual(point.choice, "end_main")
        result = svc.undo_to(game.game_id, point.index, of=point.of)
        self.assertEqual(result.narration[-1], history.undone_to(2))
        self.assertFalse(any("tech" in line for line in result.narration), result.narration)
        self.assertEqual(svc.load(game).player(other).tech_choice, picks)
        # The turn-start undo, by contrast, starts it over and says so.
        result = svc.undo_to_turn_start(game.game_id)
        self.assertIn(history.tech_again(other), result.narration)
        self.assertIsNone(svc.load(game).player(other).tech_choice)

    def test_a_stale_undo_point_saves_nothing(self) -> None:
        from codex.game import RuleRefusal

        svc, saves, game = started()
        svc.apply_action(game.game_id, Action(PromptKind.MAIN_ACTION, "end_main"))
        saves.calls = 0
        with self.assertRaises(RuleRefusal):
            svc.undo_to(game.game_id, 1, of=3)
        self.assertEqual(saves.calls, 0)


if __name__ == "__main__":
    unittest.main()
