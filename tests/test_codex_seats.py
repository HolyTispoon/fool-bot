"""
The seats as a list (docs/codex-multiplayer.md, step 1): a match of three
or four players saves, loads and validates; `opponents`, `next_seat` and
`base_of` answer for each seat; a record with three seats saves and
loads, and one saved before the list (the four `player_*` keys, no
"seats") loads with two.
"""

from __future__ import annotations

import unittest

from codex import seats
from codex.cards import catalog
from codex.components import MatchState
from codex.engine import RulesEngine
from codex.game import CodexGame, RuleRefusal

from codex_positions import new_game

TEAMS = (("bashing",), ("finesse",), ("bashing",), ("finesse",))


class MatchOfSeveralSeatsTests(unittest.TestCase):
    def table(self, count: int):
        engine, _, match = new_game(teams=TEAMS[:count])
        return engine, match

    def test_a_match_of_three_or_four_round_trips_and_validates(self) -> None:
        for count in (3, 4):
            with self.subTest(players=count):
                engine, match = self.table(count)
                self.assertEqual([player.seat for player in match.players], list(range(1, count + 1)))
                saved = match.to_dict()
                loaded = MatchState.from_dict(saved)
                loaded.validate(catalog())
                self.assertEqual(loaded.to_dict(), saved)

    def test_opponents_are_every_other_seat(self) -> None:
        for count in (2, 3, 4):
            with self.subTest(players=count):
                engine, match = self.table(count)
                for seat in range(1, count + 1):
                    self.assertEqual(
                        engine.opponents(match, seat),
                        tuple(other for other in range(1, count + 1) if other != seat),
                    )

    def test_a_duel_has_one_sole_opponent_and_a_longer_table_refuses(self) -> None:
        engine, match = self.table(2)
        self.assertEqual(engine.sole_opponent(match, 1), 2)
        engine, match = self.table(3)
        with self.assertRaises(RuleRefusal):
            engine.sole_opponent(match, 1)

    def test_the_turn_passes_to_the_next_seat_and_wraps(self) -> None:
        engine, match = self.table(3)
        order = []
        for _ in range(4):
            order.append(match.active)
            match.active = engine.next_seat(match)
        self.assertEqual(order, [1, 2, 3, 1])

    def test_an_extra_turn_is_the_same_seat_again(self) -> None:
        engine, match = self.table(3)
        match.active = 2
        match.extra_turns = [2]
        self.assertEqual(engine.next_seat(match), 2)
        self.assertEqual(engine.turn_seats(match), (2,))
        self.assertEqual(engine.acting_seats(match), (2,))

    def test_a_seats_base_is_read_and_written_in_one_place(self) -> None:
        engine, match = self.table(4)
        for seat in range(1, 5):
            self.assertEqual(match.base_of(seat), 20)
        match.set_base(3, 7)
        self.assertEqual([match.base_of(seat) for seat in range(1, 5)], [20, 20, 7, 20])
        self.assertEqual(MatchState.from_dict(match.to_dict()).base_of(3), 7)

    def test_first_and_winner_may_be_any_seat_the_match_has(self) -> None:
        engine, match = self.table(3)
        match.first = match.active = 3
        match.winner = 2
        match.validate(catalog())
        match.winner = 4
        with self.assertRaises(ValueError):
            match.validate(catalog())

    def test_one_player_is_no_match(self) -> None:
        _, match = self.table(3)
        match.players = match.players[:1]
        with self.assertRaises(ValueError):
            match.validate(catalog())

    def test_the_attacked_seat_is_saved_only_while_an_attack_is_declared(self) -> None:
        engine, match = self.table(2)
        self.assertNotIn("against", match.to_dict())
        match.attacking, match.against = "hero:troq_bashar", 2
        self.assertEqual(MatchState.from_dict(match.to_dict()).against, 2)

    def test_a_save_older_than_the_attacked_seat_reads_the_one_opponent(self) -> None:
        engine, match = self.table(2)
        match.combat = {"attacker": "hero:troq_bashar", "defender": "base", "stage": "resolve",
                        "obliterate": 0, "obliterated": [], "sparks": [], "overpower": None,
                        "triggered": True}
        match.attacking = "hero:troq_bashar"
        saved = match.to_dict()
        saved.pop("against", None)
        loaded = MatchState.from_dict(saved)
        self.assertEqual(loaded.combat["against"], 2)
        self.assertEqual(loaded.against, 2)


class RecordOfSeveralSeatsTests(unittest.TestCase):
    def test_the_record_saves_its_seats_and_the_four_older_keys(self) -> None:
        game = CodexGame("g1", 1)
        game.take_seat(11, "one", ["bashing"])
        game.take_seat(22, "two", ["finesse"])
        saved = game.to_dict()
        self.assertEqual(saved["seats"], [{"id": 11, "name": "one"}, {"id": 22, "name": "two"}])
        self.assertEqual(
            (saved["player_1_id"], saved["player_1_name"], saved["player_2_id"], saved["player_2_name"]),
            (11, "one", 22, "two"),
        )
        loaded = CodexGame.from_dict(saved)
        self.assertEqual(loaded.seat_ids(), (11, 22))
        self.assertEqual((loaded.seat_user_id(1), loaded.seat_user_id(2)), (11, 22))

    def test_a_record_saved_before_the_list_loads_with_two_seats(self) -> None:
        older = CodexGame("g1", 1).to_dict()
        older.pop("seats")
        older.update(player_1_id=11, player_1_name="one", player_2_id=22, player_2_name="two")
        game = CodexGame.from_dict(older)
        self.assertEqual(game.seat_count, 2)
        self.assertEqual(game.seats, [{"id": 11, "name": "one"}, {"id": 22, "name": "two"}])
        self.assertEqual((game.player_1_id, game.player_2_name), (11, "two"))

    def test_a_third_seat_is_refused_with_the_count(self) -> None:
        game = CodexGame("g1", 1)
        game.take_seat(11, "one", ["bashing"])
        game.take_seat(22, "two", ["finesse"])
        with self.assertRaises(RuleRefusal) as refused:
            game.take_seat(33, "three", ["bashing"])
        self.assertIn("2", str(refused.exception))
        with self.assertRaises(RuleRefusal) as refused:
            game.take_seat(33, "three", ["bashing"], seat=3)
        self.assertIn("2 seats", str(refused.exception))

    def test_a_seat_left_empty_keeps_its_number(self) -> None:
        game = CodexGame("g1", 1)
        game.take_seat(11, "one", ["bashing"])
        game.take_seat(22, "two", ["finesse"])
        game.leave(11)
        self.assertIsNone(game.seat_user_id(1))
        self.assertEqual(game.seat_of(22), 2)
        self.assertEqual(game.take_seat(33, "three", ["bashing"]), 1)

    def test_a_longer_record_saves_and_loads(self) -> None:
        """The list is as long as the game's seat count; a record that
        holds more seats than the count reads as the count."""
        game = CodexGame("g1", 1)
        saved = game.to_dict()
        saved["seats"] = [{"id": n, "name": f"p{n}"} for n in (1, 2, 3)]
        self.assertEqual(len(CodexGame.from_dict(saved).seats), game.seat_count)

    def test_the_readings_are_the_modules_functions(self) -> None:
        engine, _, match = new_game()
        self.assertEqual(engine.opponents(match, 1), seats.opponents(match, 1))
        self.assertEqual(engine.next_seat(match), seats.next_seat(match))


if __name__ == "__main__":
    unittest.main()
