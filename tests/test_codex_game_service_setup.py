"""
The Codex lobby through `gamesaves.codex.service.GameService`: every
move a thin door over the record's rule, each saving once, and a
refusal saving nothing (docs/codex-bot.md, step 3).

The service is built with a recorder for its save, so nothing here
reaches the disk.
"""

from __future__ import annotations

import unittest

from codex.engine import RulesEngine
from codex.game import GameStatus, RuleRefusal
from codex.prompts import PromptKind, Action
from gamesaves.codex.service import GameService


class Saves:
    """Counts the service's saves, and what each wrote."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, games) -> None:
        self.calls += 1


def service(seed: int = 7) -> tuple[GameService, Saves]:
    saves = Saves()
    return GameService(RulesEngine(seed=seed), {}, save=saves), saves


def seated(seed: int = 7):
    """A lobby with both seats taken, and the save count reset."""
    svc, saves = service(seed)
    game = svc.create_game(guild_id=1, channel_id=10)
    svc.take_seat(game.game_id, 101, "basher", "bashing")
    svc.take_seat(game.game_id, 202, "fencer", "finesse")
    saves.calls = 0
    return svc, saves, game


class LobbyTests(unittest.TestCase):
    def test_create_game_is_an_empty_lobby_saved_once(self) -> None:
        svc, saves = service()
        game = svc.create_game(guild_id=1, channel_id=10)
        self.assertIs(game.status, GameStatus.LOBBY)
        self.assertIsNone(game.player_1_id)
        self.assertEqual(game.game_number, 1)
        self.assertIn(game.game_id, svc.games)
        self.assertEqual(saves.calls, 1)

    def test_game_numbers_count_per_server(self) -> None:
        svc, _ = service()
        svc.create_game(guild_id=1)
        svc.create_game(guild_id=1)
        self.assertEqual(svc.create_game(guild_id=1).game_number, 3)
        self.assertEqual(svc.create_game(guild_id=2).game_number, 1)

    def test_take_seat_saves_once(self) -> None:
        svc, saves = service()
        game = svc.create_game(guild_id=1)
        saves.calls = 0
        svc.take_seat(game.game_id, 101, "basher", "bashing")
        self.assertEqual(game.player_1_id, 101)
        self.assertEqual(game.player_specs, {1: "bashing"})
        self.assertEqual(saves.calls, 1)

    def test_a_taken_side_is_refused_and_nothing_is_saved(self) -> None:
        svc, saves = service()
        game = svc.create_game(guild_id=1)
        svc.take_seat(game.game_id, 101, "basher", "bashing")
        saves.calls = 0
        with self.assertRaises(RuleRefusal):
            svc.take_seat(game.game_id, 202, "fencer", "bashing")
        self.assertEqual(saves.calls, 0)
        self.assertIsNone(game.player_2_id)

    def test_leave_frees_the_seat_and_saves_once(self) -> None:
        svc, saves = service()
        game = svc.create_game(guild_id=1)
        svc.take_seat(game.game_id, 101, "basher", "bashing")
        saves.calls = 0
        svc.leave(game.game_id, 101)
        self.assertIsNone(game.player_1_id)
        self.assertEqual(game.player_specs, {})
        self.assertEqual(saves.calls, 1)

    def test_leaving_a_seat_not_held_is_refused(self) -> None:
        svc, saves = service()
        game = svc.create_game(guild_id=1)
        saves.calls = 0
        with self.assertRaises(RuleRefusal):
            svc.leave(game.game_id, 101)
        self.assertEqual(saves.calls, 0)

    def test_start_before_both_seats_is_refused(self) -> None:
        svc, saves = service()
        game = svc.create_game(guild_id=1)
        svc.take_seat(game.game_id, 101, "basher", "bashing")
        saves.calls = 0
        with self.assertRaises(RuleRefusal):
            svc.start(game.game_id)
        self.assertEqual(saves.calls, 0)
        self.assertIsNone(game.match_state)
        self.assertIs(game.status, GameStatus.LOBBY)

    def test_discard_forgets_a_lobby_that_never_started(self) -> None:
        svc, saves = service()
        game = svc.create_game(guild_id=1)
        svc.discard_game(game.game_id)
        self.assertNotIn(game.game_id, svc.games)


class StartTests(unittest.TestCase):
    def test_start_deals_and_runs_the_first_turns_start_in_one_save(self) -> None:
        svc, saves, game = seated()
        result = svc.start(game.game_id)
        self.assertEqual(saves.calls, 1)
        self.assertIs(game.status, GameStatus.PLAYING)
        self.assertIsNotNone(result.prompt)
        self.assertIs(result.prompt.kind, PromptKind.MAIN_ACTION)
        match = svc.load(game)
        self.assertEqual(result.prompt.asked_player, match.first)
        self.assertEqual(match.phase, "main")
        # The first player's opening workers are four, the other's five
        # (UMR p. 3), and the upkeep collected the first player's gold.
        self.assertEqual(match.player(match.first).workers, 4)
        self.assertEqual(match.player(match.first).gold, 4)
        self.assertTrue(result.board_changed)
        self.assertTrue(any("Turn 1" in line for line in result.lines))

    def test_the_lines_name_no_card_in_a_hand(self) -> None:
        """The start's lines are public: nothing in a hand is named."""
        svc, _, game = seated()
        result = svc.start(game.game_id)
        self.assertFalse(any("{card:" in line for line in result.lines))

    def test_a_second_start_is_refused(self) -> None:
        svc, saves, game = seated()
        svc.start(game.game_id)
        saves.calls = 0
        with self.assertRaises(RuleRefusal):
            svc.start(game.game_id)
        self.assertEqual(saves.calls, 0)

    def test_a_started_game_takes_no_seat(self) -> None:
        svc, _, game = seated()
        svc.start(game.game_id)
        with self.assertRaises(RuleRefusal):
            svc.leave(game.game_id, 101)

    def test_resume_on_a_started_game_runs_nothing_and_saves_nothing(self) -> None:
        svc, saves, game = seated()
        svc.start(game.game_id)
        saves.calls = 0
        found, result = svc.resume(game.game_id)
        self.assertIs(result.prompt.kind, PromptKind.MAIN_ACTION)
        self.assertEqual(saves.calls, 0)

    def test_resume_runs_the_owed_start_of_the_turn(self) -> None:
        """A game saved between the deal and the first ready phase -- a
        crash inside Start -- is taken on by resume."""
        svc, saves, game = seated()
        game.start(svc.engine)
        saves.calls = 0
        found, result = svc.resume(game.game_id)
        self.assertEqual(found, "the start of the turn")
        self.assertIs(result.prompt.kind, PromptKind.MAIN_ACTION)
        self.assertEqual(saves.calls, 1)

    def test_an_action_saves_once(self) -> None:
        svc, saves, game = seated()
        svc.start(game.game_id)
        saves.calls = 0
        result = svc.apply_action(game.game_id, Action(PromptKind.MAIN_ACTION, "end_main"))
        self.assertFalse(result.refused)
        self.assertEqual(saves.calls, 1)
        self.assertIs(result.prompt.kind, PromptKind.PATROL)

    def test_a_refused_action_saves_nothing(self) -> None:
        svc, saves, game = seated()
        svc.start(game.game_id)
        saves.calls = 0
        result = svc.apply_action(game.game_id, Action(PromptKind.PATROL, ""))
        self.assertTrue(result.refused)
        self.assertEqual(saves.calls, 0)

    def test_the_wire_carries_no_prompt(self) -> None:
        """A prompt lists a hand or a codex, which is its asked
        player's alone; the result's JSON is everybody's."""
        svc, _, game = seated()
        written = svc.start(game.game_id).to_dict()
        self.assertNotIn("prompt", written)
        self.assertNotIn("standing", written)


class BoardLayoutTests(unittest.TestCase):
    def test_swap_view_flips_the_layout_and_saves_once(self) -> None:
        svc, saves, game = seated()
        svc.start(game.game_id)
        saves.calls = 0
        svc.set_board_layout(game.game_id, "side_by_side")
        self.assertEqual(game.board_layout, "side_by_side")
        self.assertEqual(saves.calls, 1)

    def test_an_unknown_layout_is_refused(self) -> None:
        svc, saves, game = seated()
        svc.start(game.game_id)
        saves.calls = 0
        with self.assertRaises(RuleRefusal):
            svc.set_board_layout(game.game_id, "diagonal")
        self.assertEqual(saves.calls, 0)

    def test_a_lobby_has_no_board_to_lay_out(self) -> None:
        svc, _, game = seated()
        with self.assertRaises(RuleRefusal):
            svc.set_board_layout(game.game_id, "side_by_side")

    def test_the_layout_round_trips_and_defaults_to_stacked(self) -> None:
        from codex.game import CodexGame

        svc, _, game = seated()
        svc.start(game.game_id)
        svc.set_board_layout(game.game_id, "side_by_side")
        self.assertEqual(CodexGame.from_dict(game.to_dict()).board_layout, "side_by_side")
        older = game.to_dict()
        del older["board_layout"]
        self.assertEqual(CodexGame.from_dict(older).board_layout, "stacked")


class AbandonTests(unittest.TestCase):
    def test_abandon_saves_once_and_keeps_the_record(self) -> None:
        svc, saves, game = seated()
        svc.start(game.game_id)
        saves.calls = 0
        svc.abandon(game.game_id)
        self.assertIs(game.status, GameStatus.ABANDONED)
        self.assertIn(game.game_id, svc.games)
        self.assertEqual(saves.calls, 1)

    def test_abandoning_twice_is_refused(self) -> None:
        svc, saves, game = seated()
        svc.abandon(game.game_id)
        saves.calls = 0
        with self.assertRaises(RuleRefusal):
            svc.abandon(game.game_id)
        self.assertEqual(saves.calls, 0)


class StorageTests(unittest.TestCase):
    def test_a_game_round_trips_through_the_file(self) -> None:
        import tempfile
        from pathlib import Path

        from gamesaves.codex import storage

        svc, _, game = seated()
        svc.start(game.game_id)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "codex_games.json"
            storage.save_games(svc.games, path)
            loaded = storage.load_games(path)
        self.assertEqual(loaded[game.game_id].to_dict(), game.to_dict())

    def test_an_unreadable_file_is_never_written_over(self) -> None:
        import tempfile
        from pathlib import Path

        from gamesaves.codex import storage

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "codex_games.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertLogs("gamesaves.codex.storage", "ERROR"):
                self.assertEqual(storage.load_games(path), {})
                storage.save_games({}, path)
            self.assertEqual(path.read_text(encoding="utf-8"), "{not json")


if __name__ == "__main__":
    unittest.main()
