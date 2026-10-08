"""
`CodexGame`, the record: its seat fields spelt as `D12BallGame` spells
them, and the lobby's rules refusing with `RuleRefusal`.
"""

from __future__ import annotations

import unittest

from codex.components import MatchState
from codex.engine import RulesEngine
from codex.game import CodexGame, GameStatus, RuleRefusal
from d12ball.game import D12BallGame


class LobbyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.game = CodexGame("g1", 1)

    def test_two_seats_and_a_start(self) -> None:
        self.assertEqual(self.game.take_seat(1, "a", "bashing"), 1)
        self.assertFalse(self.game.may_start())
        self.assertEqual(self.game.take_seat(2, "b", "finesse"), 2)
        self.assertTrue(self.game.may_start())
        self.game.start(RulesEngine(seed=3))
        self.assertIs(self.game.status, GameStatus.PLAYING)
        match = MatchState.from_dict(self.game.match_state)
        self.assertEqual([p.spec for p in match.players], ["bashing", "finesse"])

    def test_a_side_is_held_once(self) -> None:
        self.game.take_seat(1, "a", "bashing")
        with self.assertRaises(RuleRefusal):
            self.game.take_seat(2, "b", "bashing")
        with self.assertRaises(RuleRefusal):
            self.game.take_seat(1, "a", "bashing")

    def test_a_seated_player_may_switch_to_the_free_side(self) -> None:
        self.game.take_seat(1, "a", "bashing")
        self.assertEqual(self.game.take_seat(1, "a", "finesse"), 1)
        self.assertEqual(self.game.player_specs, {1: "finesse"})

    def test_a_third_player_is_refused(self) -> None:
        self.game.take_seat(1, "a", "bashing")
        self.game.take_seat(2, "b", "finesse")
        self.game.leave(2)
        self.game.take_seat(3, "c", "finesse")
        self.assertEqual(self.game.player_2_id, 3)

    def test_leaving_and_starting_are_refused_where_they_should_be(self) -> None:
        with self.assertRaises(RuleRefusal):
            self.game.leave(1)
        with self.assertRaises(RuleRefusal):
            self.game.start(RulesEngine())
        self.game.take_seat(1, "a", "bashing")
        self.game.take_seat(2, "b", "finesse")
        self.game.start(RulesEngine())
        with self.assertRaises(RuleRefusal):
            self.game.leave(1)

    def test_an_observer_who_sits_down_stops_observing(self) -> None:
        self.game.observer_ids.append(5)
        self.game.take_seat(5, "e", "finesse")
        self.assertEqual(self.game.observer_ids, [])

    def test_the_record_round_trips(self) -> None:
        self.game.take_seat(1, "a", "bashing")
        self.game.take_seat(2, "b", "finesse")
        self.game.start(RulesEngine(seed=1))
        data = self.game.to_dict()
        self.assertEqual(CodexGame.from_dict(data).to_dict(), data)
        self.assertEqual(data["player_specs"], {"1": "bashing", "2": "finesse"})

    def test_the_seat_fields_are_spelt_as_d12_balls(self) -> None:
        """So step 3's shared authorisation predicates read either record."""
        shared = ("player_1_id", "player_2_id", "player_1_name", "player_2_name",
                  "observer_ids", "test_game", "game_id", "game_number",
                  "guild_id", "channel_id", "message_id")
        codex_fields = CodexGame.__dataclass_fields__
        d12_fields = D12BallGame.__dataclass_fields__
        for name in shared:
            self.assertIn(name, codex_fields)
            self.assertIn(name, d12_fields)


if __name__ == "__main__":
    unittest.main()
