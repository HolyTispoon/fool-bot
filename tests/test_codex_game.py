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
        self.assertEqual([p.specs for p in match.players], [("bashing",), ("finesse",)])

    def test_both_sides_may_play_one_hero(self) -> None:
        """Each player chooses their heroes (UMR p. 3): nothing says the
        two may not choose the same one."""
        self.game.take_seat(1, "a", "bashing")
        self.assertEqual(self.game.take_seat(2, "b", "bashing"), 2)
        self.assertEqual(self.game.player_specs, {1: ["bashing"], 2: ["bashing"]})

    def test_a_seated_player_may_choose_again(self) -> None:
        self.game.take_seat(1, "a", "bashing")
        self.assertEqual(self.game.take_seat(1, "a", "finesse"), 1)
        self.assertEqual(self.game.player_specs, {1: ["finesse"]})

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
        self.assertEqual(data["player_specs"], {"1": ["bashing"], "2": ["finesse"]})
        self.assertEqual(data["player_decks"], {"1": "neutral", "2": "neutral"})
        self.assertEqual(data["mode"], "basic")

    def test_a_record_older_than_the_standard_game_reads_as_a_basic_one(self) -> None:
        """Step 10's keys, each with its fallback: no mode is the basic
        game, a spec saved as a string is a team of one, and no decks is
        the neutral deck for every seat."""
        self.game.take_seat(1, "a", "bashing")
        self.game.take_seat(2, "b", "finesse")
        older = self.game.to_dict()
        for key in ("mode", "player_decks", "rematch_decks"):
            older.pop(key)
        older["player_specs"] = {"1": "bashing", "2": "finesse"}
        read = CodexGame.from_dict(older)
        self.assertEqual(read.mode, "basic")
        self.assertEqual(read.player_specs, {1: ["bashing"], 2: ["finesse"]})
        self.assertEqual(read.player_decks, {1: "neutral", 2: "neutral"})
        self.assertTrue(read.may_start())

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


class StandardLobbyTests(unittest.TestCase):
    """The standard game's lobby rules (UMR pp. 3-4), on the record."""

    RED = ["fire", "anarchy", "blood"]
    GREEN = ["feral", "growth", "balance"]

    def setUp(self) -> None:
        self.game = CodexGame("g1", 1)
        self.game.set_mode("standard")

    def test_three_heroes_of_one_colour_settle_the_deck(self) -> None:
        self.game.take_seat(1, "a", self.RED)
        self.assertEqual(self.game.player_decks, {1: "red"})
        self.game.take_seat(2, "b", self.GREEN)
        self.assertTrue(self.game.may_start())
        self.game.start(RulesEngine(seed=3))
        match = MatchState.from_dict(self.game.match_state)
        self.assertEqual(sum(match.player(1).codex.values()), 72)

    def test_a_hero_of_a_colour_not_landed_is_refused(self) -> None:
        with self.assertRaises(RuleRefusal) as refused:
            self.game.take_seat(1, "a", ["fire", "anarchy", "law"])
        self.assertIn("not in this bot yet", str(refused.exception))
        self.assertIsNone(refused.exception.cite)
        self.assertIsNone(self.game.player_1_id)

    def test_a_fourth_hero_is_refused(self) -> None:
        with self.assertRaises(RuleRefusal) as refused:
            self.game.take_seat(1, "a", [*self.RED, "feral"])
        self.assertEqual(refused.exception.cite, "UMR p. 3")
        with self.assertRaises(RuleRefusal):
            self.game.take_seat(1, "a", self.RED[:2])

    def test_a_hero_twice_is_refused(self) -> None:
        with self.assertRaises(RuleRefusal):
            self.game.take_seat(1, "a", ["fire", "fire", "blood"])

    def test_a_multicolour_team_chooses_its_deck(self) -> None:
        """"Use the 10 starting cards that match one of your three
        heroes' colors" (UMR p. 3) -- the neutral heroes' colour among
        them."""
        self.game.take_seat(1, "a", ["fire", "feral", "bashing"])
        self.assertEqual(self.game.deck_choices(1), ("red", "green", "neutral"))
        self.assertNotIn(1, self.game.player_decks)
        self.game.take_seat(2, "b", self.GREEN)
        self.assertFalse(self.game.may_start())
        self.game.choose_deck(1, "neutral")
        self.assertEqual(self.game.player_decks[1], "neutral")
        self.assertTrue(self.game.may_start())

    def test_a_deck_of_a_colour_nobody_plays_is_refused(self) -> None:
        self.game.take_seat(1, "a", ["fire", "feral", "anarchy"])
        with self.assertRaises(RuleRefusal) as refused:
            self.game.choose_deck(1, "neutral")
        self.assertEqual(refused.exception.cite, "UMR p. 3")
        with self.assertRaises(RuleRefusal):
            self.game.choose_deck(2, "red")

    def test_start_before_the_seats_are_complete_is_refused(self) -> None:
        self.game.take_seat(1, "a", ["fire", "feral", "anarchy"])
        self.game.take_seat(2, "b", self.GREEN)
        with self.assertRaises(RuleRefusal):
            self.game.start(RulesEngine())
        self.assertIs(self.game.status, GameStatus.LOBBY)

    def test_the_basic_games_deck_is_its_heros_colour(self) -> None:
        game = CodexGame("g2", 2)
        game.take_seat(1, "a", "fire")
        game.take_seat(2, "b", "feral")
        self.assertEqual(game.player_decks, {1: "red", 2: "green"})
        game.start(RulesEngine(seed=1))
        match = MatchState.from_dict(game.match_state)
        cards = RulesEngine().catalog
        dealt = [*match.player(1).hand, *match.player(1).deck]
        self.assertEqual(sorted(dealt), sorted(cards.starting_deck("red")))

    def test_changing_the_mode_clears_the_teams_but_not_the_seats(self) -> None:
        self.game.take_seat(1, "a", self.RED)
        self.game.set_mode("basic")
        self.assertEqual(self.game.player_1_id, 1)
        self.assertEqual(self.game.player_specs, {})
        self.assertFalse(self.game.may_start())
        with self.assertRaises(RuleRefusal):
            self.game.set_mode("draft")

    def test_a_rematch_swaps_the_teams_whole(self) -> None:
        self.game.take_seat(1, "a", ["fire", "feral", "bashing"])
        self.game.choose_deck(1, "green")
        self.game.take_seat(2, "b", self.GREEN)
        self.game.start(RulesEngine(seed=2))
        self.game.status = GameStatus.FINISHED
        rematch = self.game.rematch("g9", 9)
        self.assertEqual(rematch.mode, "standard")
        self.assertEqual(rematch.player_specs, {1: self.GREEN, 2: ["fire", "feral", "bashing"]})
        self.assertEqual(rematch.player_decks, {1: "green", 2: "green"})
        self.assertTrue(rematch.may_start())
        rematch.keep_heroes(1)
        rematch.keep_heroes(2)
        self.assertEqual(rematch.player_specs[1], ["fire", "feral", "bashing"])
        self.assertEqual(rematch.player_decks, {1: "green", 2: "green"})
