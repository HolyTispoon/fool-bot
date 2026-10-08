"""
What step 4 asked of the Codex model and service for the turn on
Discord (docs/codex-bot.md, step 4): the panel's readings carried on
the prompt -- the hand the picture numbers, why each defender is legal
-- the end of the turn closed as its own group with its own position
(`draw_after`), and the two undos as service methods that save once.
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
            {"nothing is patrolling"},
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
        deck = match.player(seat).spec.title()
        self.assertEqual(turn_heading(match), f"**Turn 1** -- {{to:{seat}}} ({deck})")

    def test_a_deck_of_several_specs_is_named_by_all_of_them(self) -> None:
        """The standard game's multicolour deck: "spec1/spec2/spec3"
        (the author, 2026-10-08)."""
        from codex.formatting import deck_name

        self.assertEqual(deck_name(("bashing",)), "Bashing")
        self.assertEqual(deck_name(("anarchy", "blood", "fire")), "Anarchy/Blood/Fire")

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
        deck = svc.load(game).player(ending).spec.title()
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


if __name__ == "__main__":
    unittest.main()
