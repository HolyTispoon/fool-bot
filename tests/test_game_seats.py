"""
A web room's seats, on the record: `take_seat` and `vacate_seat`.

Step 2 of docs/web-app-next.md (decision 1): a seat changes hands
before kickoff or during the game, and the other seat never moves. The
lobby's own moves are untouched (`tests/test_game_service_setup.py`
still holds them to the Discord lobby's rules). What this watches for:

- **A seat changing hands changes nothing about the position.** The
  match keeps its sides by player number, so a new id in a seat
  mid-match is asked the same question the old one was.
- **An empty seat is not the AI's.** A seat is held by a person, by
  the AI, or by nobody (`D12BallGame.ai_seats`), and a side with nobody
  in its seat waits; the AI may be put in either seat and taken out
  again, and a save no room ever touched reads exactly as before.
- **Every predicate over the seat ids copes with an empty seat.**
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from cogs.d12ball_helpers import game_participant_ids, refresh_player_names
from d12ball.components import RuleRefusal, TeamSide
from d12ball.formatting import coach_name
from d12ball.game import AIOpponent, CoinFace, D12BallGame, Team, paired_team
from d12ball.prompts import asked_sides, pending_prompt
from d12ball.stats import SCOPE_DINKY, SCOPE_HUMAN, game_category
from gamesaves.d12ball.service import GameService
from prompt_fixtures import ENGINE, CASES


CREATOR = 111
JOINER = 222
WATCHER = 333
NEW_DEVICE = 444


def case(name: str):
    for entry in CASES:
        if entry.name == name:
            return entry.build()
    raise AssertionError(f"no fixture called {name}")


class SeatHarness(unittest.TestCase):
    def setUp(self) -> None:
        self.games: dict[str, D12BallGame] = {}
        self.saves = 0

        def save(games: dict) -> None:
            self.saves += 1

        self.service = GameService(ENGINE, self.games, save=save)

    def room(self) -> D12BallGame:
        return self.service.create_game(
            player_1_id=CREATOR, player_1_name="One", in_lobby=True,
        )

    def refused(self, call, game_id: str, *args) -> str:
        """The refusal's sentence, with the record left as it was and
        nothing written."""
        game = self.games[game_id]
        before = game.to_dict()
        saves = self.saves
        with self.assertRaises(RuleRefusal) as caught:
            call(game_id, *args)
        self.assertEqual(game.to_dict(), before)
        self.assertEqual(self.saves, saves)
        return str(caught.exception)


class TakeSeatTests(SeatHarness):
    def test_the_second_arrival_takes_seat_two(self) -> None:
        game = self.room()

        self.service.take_seat(game.game_id, JOINER, "Two")

        self.assertEqual((game.player_1_id, game.player_2_id), (CREATOR, JOINER))
        self.assertEqual(game.player_2_name, "Two")

    def test_a_third_arrival_is_refused_a_seat(self) -> None:
        game = self.room()
        self.service.take_seat(game.game_id, JOINER, "Two")

        sentence = self.refused(
            self.service.take_seat, game.game_id, WATCHER, "Three",
        )

        self.assertIn("Both seats are taken", sentence)

    def test_a_seat_held_by_somebody_else_is_refused(self) -> None:
        game = self.room()

        sentence = self.refused(
            self.service.take_seat, game.game_id, JOINER, "Two", 1,
        )

        self.assertEqual(sentence, "That seat is held by somebody else.")

    def test_one_person_holds_one_seat(self) -> None:
        game = self.room()

        sentence = self.refused(
            self.service.take_seat, game.game_id, CREATOR, "One", 2,
        )

        self.assertIn("already hold a seat", sentence)

    def test_a_one_player_game_has_no_second_seat(self) -> None:
        for setting in ("test", "tutorial"):
            with self.subTest(setting):
                game = self.room()
                self.service.configure(game.game_id, setting)

                sentence = self.refused(
                    self.service.take_seat, game.game_id, JOINER, "Two",
                )

                self.assertIn("Both seats are taken", sentence)
                self.assertIn(
                    "one-player game",
                    self.refused(
                        self.service.take_seat, game.game_id, JOINER, "Two", 2,
                    ),
                )

    def test_taking_seat_two_settles_the_opponent(self) -> None:
        game = self.room()
        self.service.configure(game.game_id, "ai", AIOpponent.DINKY)
        self.service.lobby_observe(game.game_id, JOINER)

        self.service.take_seat(game.game_id, JOINER, "Two")

        self.assertIsNone(game.ai_opponent)
        self.assertNotIn(JOINER, game.observer_ids)

    def test_a_solo_game_s_second_seat_is_the_ai_s(self) -> None:
        game = self.room()
        self.service.start_lobby(game.game_id)

        sentence = self.refused(
            self.service.take_seat, game.game_id, JOINER, "Two", 2,
        )

        self.assertIn("The AI holds that seat", sentence)

    def test_one_change_and_one_save(self) -> None:
        game = self.room()
        saves = self.saves

        self.service.take_seat(game.game_id, JOINER, "Two")
        self.service.vacate_seat(game.game_id, JOINER)

        self.assertEqual(self.saves, saves + 2)


class VacateSeatTests(SeatHarness):
    def test_the_other_seat_does_not_move(self) -> None:
        """Where `lobby_leave` hands the creator's seat to the joiner,
        a room leaves it empty for whoever comes next."""
        game = self.room()
        self.service.take_seat(game.game_id, JOINER, "Two")

        self.service.vacate_seat(game.game_id, CREATOR)

        self.assertEqual((game.player_1_id, game.player_2_id), (None, JOINER))
        self.assertIsNone(game.player_1_name)

    def test_a_left_seat_is_taken_again(self) -> None:
        game = self.room()
        self.service.take_seat(game.game_id, JOINER, "Two")
        self.service.vacate_seat(game.game_id, JOINER)

        self.service.take_seat(game.game_id, NEW_DEVICE, "Two again")

        self.assertEqual(game.player_2_id, NEW_DEVICE)
        self.assertEqual(game.player_2_name, "Two again")

    def test_the_only_coach_may_leave(self) -> None:
        """A room is not a lobby: it stays open with nobody seated,
        and the next arrival takes seat 1."""
        game = self.room()

        self.service.vacate_seat(game.game_id, CREATOR)
        self.service.take_seat(game.game_id, WATCHER, "Three")

        self.assertEqual(game.player_1_id, WATCHER)

    def test_somebody_with_no_seat_is_refused(self) -> None:
        game = self.room()

        sentence = self.refused(self.service.vacate_seat, game.game_id, WATCHER)

        self.assertEqual(sentence, "You do not hold a seat in this game.")

    def test_seat_two_left_mid_game_is_empty_not_the_ai_s(self) -> None:
        """An empty `player_2_id` used to be the AI's side; a room says
        outright that nobody holds it, and the side waits."""
        fixture = case("kickoff")
        game = fixture.game
        self.games[game.game_id] = game

        self.service.vacate_seat(game.game_id, JOINER)

        self.assertIsNone(game.player_2_id)
        self.assertFalse(game.ai_holds(2))
        self.assertFalse(game.is_solo_game)
        self.assertTrue(game.seat_is_free(2))
        self.assertEqual(game.to_dict()["ai_seats"], [])
        self.assertFalse(D12BallGame.from_dict(game.to_dict()).is_solo_game)

    def test_a_test_game_s_coach_holds_both_seats(self) -> None:
        game = self.room()
        self.service.configure(game.game_id, "test")
        self.service.start_lobby(game.game_id)

        sentence = self.refused(self.service.vacate_seat, game.game_id, CREATOR)

        self.assertIn("test game", sentence)

    def test_a_lobby_with_seat_one_empty_does_not_start(self) -> None:
        game = self.room()
        self.service.vacate_seat(game.game_id, CREATOR)

        sentence = self.refused(self.service.start_lobby, game.game_id)

        self.assertIn("Seat 1 is empty", sentence)


class AISeatTests(SeatHarness):
    """The AI in either seat of a room, put in by a move and taken out
    by one, before the game or during it."""

    def test_the_ai_takes_an_empty_seat_and_a_kick_empties_it(self) -> None:
        game = self.room()

        self.service.seat_ai(game.game_id, 2)

        self.assertTrue(game.ai_holds(2))
        self.assertTrue(game.is_solo_game)
        self.assertEqual(game.ai_opponent, AIOpponent.DINKY)
        self.assertEqual(coach_name(game, 2), "Dinky AI")
        self.assertIn(
            "The AI holds that seat",
            self.refused(
                self.service.take_seat, game.game_id, JOINER, "Two", 2,
            ),
        )

        self.service.unseat_ai(game.game_id, 2)
        self.service.take_seat(game.game_id, JOINER, "Two")

        self.assertFalse(game.is_solo_game)
        self.assertEqual(game.player_2_id, JOINER)

    def test_the_ai_may_hold_seat_one(self) -> None:
        game = self.room()
        self.service.take_seat(game.game_id, JOINER, "Two")
        self.service.vacate_seat(game.game_id, CREATOR)

        self.service.seat_ai(game.game_id, 1)

        self.assertEqual(game.ai_player_numbers(), (1,))
        self.assertEqual(coach_name(game, 1), "Dinky AI")
        self.assertEqual(game_category(game), SCOPE_DINKY)

    def test_the_refusals(self) -> None:
        game = self.room()
        self.assertIn(
            "held by somebody else",
            self.refused(self.service.seat_ai, game.game_id, 1),
        )
        self.service.seat_ai(game.game_id, 2)
        self.assertIn(
            "already holds",
            self.refused(self.service.seat_ai, game.game_id, 2),
        )
        self.service.vacate_seat(game.game_id, CREATOR)
        self.assertIn(
            "both sides",
            self.refused(self.service.seat_ai, game.game_id, 1),
        )
        self.assertIn(
            "does not hold",
            self.refused(self.service.unseat_ai, game.game_id, 1),
        )

    def test_a_one_player_game_s_sides_are_settled(self) -> None:
        for setting in ("test", "tutorial"):
            with self.subTest(setting):
                game = self.room()
                self.service.configure(game.game_id, setting)
                self.assertIn(
                    "one-player game",
                    self.refused(self.service.seat_ai, game.game_id, 2),
                )

    def test_a_room_starts_only_with_both_seats_held(self) -> None:
        game = self.service.create_game(
            player_1_id=CREATOR, player_1_name="One", in_lobby=True,
            ai_seats=[],
        )
        self.assertIn(
            "Seat 2 is empty",
            self.refused(self.service.start_lobby, game.game_id),
        )

        self.service.seat_ai(game.game_id, 2)
        self.service.start_lobby(game.game_id)

        self.assertFalse(game.in_lobby)
        self.assertTrue(game.ai_holds(2))

    def test_the_ai_in_seat_one_picks_its_team_and_takes_the_coin(
        self,
    ) -> None:
        game = self.room()
        self.service.take_seat(game.game_id, JOINER, "Two")
        self.service.vacate_seat(game.game_id, CREATOR)
        self.service.seat_ai(game.game_id, 1)
        self.service.start_lobby(game.game_id)

        self.service.pick_team(game.game_id, 2, Team.ORANGE)

        self.assertIsNotNone(game.player_1_team)
        self.assertNotIn(
            game.player_1_team, (Team.ORANGE, paired_team(Team.ORANGE)),
        )
        # The coach flips and loses: the AI in seat 1 won, and chooses.
        with mock.patch.object(
            ENGINE, "flip_coin", return_value=CoinFace.DOOM,
        ):
            self.service.flip_coin(game.game_id, 2)

        self.assertEqual(game.coin_winner_player_number, 1)
        self.assertIsNotNone(game.home_player_number)
        self.assertIsNotNone(game.match_state)

    def test_a_save_no_room_touched_is_written_as_it_was(self) -> None:
        game = case("kickoff").game
        data = game.to_dict()

        self.assertNotIn("ai_seats", data)
        self.assertEqual(D12BallGame.from_dict(data).to_dict(), data)
        solo = D12BallGame.from_dict({**data, "player_2_id": None})
        self.assertEqual(solo.ai_player_numbers(), (2,))


class MidMatchTests(SeatHarness):
    """A seat that changes hands during the game."""

    def setUp(self) -> None:
        super().setUp()
        ENGINE.rng.seed(11)
        fixture = case("kickoff")
        fixture.game.match_state = fixture.match.to_dict()
        self.game = fixture.game
        self.games[self.game.game_id] = self.game

    def asked(self):
        prompt = pending_prompt(
            ENGINE, self.game, self.service.load(self.game),
        )
        return prompt.kind, prompt.ask, prompt.options

    def test_a_new_id_in_seat_one_is_asked_the_same_question(self) -> None:
        before = self.asked()
        side = ENGINE.side_for_user(self.game, CREATOR)

        self.service.vacate_seat(self.game.game_id, CREATOR)
        self.service.take_seat(self.game.game_id, NEW_DEVICE, "One, phone")

        self.assertEqual(self.asked(), before)
        self.assertEqual(ENGINE.side_for_user(self.game, NEW_DEVICE), side)
        self.assertIsNone(ENGINE.side_for_user(self.game, CREATOR))
        self.assertEqual(coach_name(self.game, 1), "One, phone")

    def test_an_empty_seat_one_reads_as_nobody(self) -> None:
        self.service.vacate_seat(self.game.game_id, CREATOR)

        self.assertEqual(game_participant_ids(self.game), {JOINER})
        self.assertFalse(self.game.is_solo_game)
        self.assertEqual(game_category(self.game), SCOPE_HUMAN)
        self.assertEqual(coach_name(self.game, 1), "Player 1")
        self.assertIsNone(ENGINE.side_for_user(self.game, None))
        # The record reads back as it was written.
        self.assertEqual(
            D12BallGame.from_dict(self.game.to_dict()).to_dict(),
            self.game.to_dict(),
        )

    def test_the_discord_names_follow_the_ids(self) -> None:
        """`refresh_player_names` reads the names off whoever holds
        the seats now, and skips an empty one."""
        self.game.player_2_id = NEW_DEVICE
        members = {
            JOINER: SimpleNamespace(display_name="Old"),
            NEW_DEVICE: SimpleNamespace(display_name="New"),
        }
        guild = SimpleNamespace(get_member=members.get)
        self.service.vacate_seat(self.game.game_id, CREATOR)

        refresh_player_names(self.game, guild)

        self.assertEqual(self.game.player_2_name, "New")
        self.assertIsNone(self.game.player_1_name)

    def test_the_ai_seated_for_the_side_asked_answers_at_once(self) -> None:
        """The kickoff asks the home side, seat 1. Its coach leaves;
        the AI is put in, and answers the question that was up."""
        before = pending_prompt(ENGINE, self.game, self.service.load(self.game))
        self.assertIn(TeamSide.HOME, asked_sides(self.service.load(self.game), before))
        self.service.vacate_seat(self.game.game_id, CREATOR)

        game, result = self.service.seat_ai(self.game.game_id, 1)

        self.assertIsNotNone(result)
        self.assertTrue(ENGINE.side_is_ai(game, TeamSide.HOME))
        after = pending_prompt(ENGINE, game, self.service.load(game))
        self.assertNotEqual(after.kind, before.kind)

    def test_a_person_takes_over_from_the_ai_mid_game(self) -> None:
        self.service.vacate_seat(self.game.game_id, JOINER)
        self.service.seat_ai(self.game.game_id, 2)

        self.service.unseat_ai(self.game.game_id, 2)
        self.service.take_seat(self.game.game_id, NEW_DEVICE, "Two again")

        self.assertFalse(self.game.is_solo_game)
        self.assertEqual(ENGINE.side_for_user(self.game, NEW_DEVICE), TeamSide.VISITING)

    def test_the_sides_stay_with_the_numbers(self) -> None:
        self.service.vacate_seat(self.game.game_id, CREATOR)
        self.service.take_seat(self.game.game_id, NEW_DEVICE, "One, phone")

        self.assertEqual(
            ENGINE.side_player_number(self.game, TeamSide.HOME), 1,
        )
        self.assertEqual(self.game.home_player_number, 1)


if __name__ == "__main__":
    unittest.main()
