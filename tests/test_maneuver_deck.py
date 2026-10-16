"""
D12 Ball 2.0's maneuver deck (`d12ball/maneuver_deck.py`): the fifteen
cards, the hand of four, the discard and the reshuffle -- and whole 2.0
games through the driver, with the save reloaded after every click, as
`test_driver_full_game` plays 1.0. See docs/design/maneuver-deck.md.
"""

from __future__ import annotations

import random
import unittest
from collections import Counter

from d12ball import maneuver_deck
from d12ball.components import MatchState, TeamSide
from d12ball.flow.driver import Action
from d12ball.game import D12BallGame, Edition, GameMode, RuleRefusal
from d12ball.prompts import PromptKind, pending_prompt
from prompt_fixtures import MANEUVERS

from test_driver_full_game import build_engine, build_game, build_match, play


def two_point_oh(mode: GameMode = GameMode.ADVANCED) -> D12BallGame:
    game = build_game()
    game.mode = mode
    game.edition = Edition.TWO
    return game


class DeckTests(unittest.TestCase):

    def test_fifteen_cards_nine_two_headed_and_six_advanced(self) -> None:
        cards = maneuver_deck.deck_cards(MANEUVERS)
        self.assertEqual(len(cards), 15)
        counts = Counter(cards)
        self.assertEqual(
            {card: count for card, count in counts.items()
             if maneuver_deck.is_basic_card(card)},
            {"basic_1": 3, "basic_2": 3, "basic_3": 3},
        )
        advanced = [card for card in cards if not maneuver_deck.is_basic_card(card)]
        self.assertEqual(len(advanced), 6)
        self.assertTrue(all(MANEUVERS.definition(card).is_gambit for card in advanced))

    def test_a_two_headed_card_plays_its_rank_on_either_side(self) -> None:
        for rank in (1, 2, 3):
            card = maneuver_deck.basic_card_id(rank)
            for side in ("offense", "defense"):
                maneuver = maneuver_deck.plays_as(MANEUVERS, card, side)
                self.assertEqual(maneuver.rank, rank)
                self.assertFalse(maneuver.is_gambit)
                self.assertIn(maneuver, MANEUVERS.side(side))

    def test_an_advanced_card_plays_on_its_own_side_alone(self) -> None:
        for side, other in (("offense", "defense"), ("defense", "offense")):
            for maneuver in MANEUVERS.side(side):
                if not maneuver.is_gambit:
                    continue
                self.assertEqual(
                    maneuver_deck.plays_as(MANEUVERS, maneuver.key, side),
                    maneuver,
                )
                self.assertIsNone(
                    maneuver_deck.plays_as(MANEUVERS, maneuver.key, other),
                )

    def test_any_hand_of_four_holds_a_card_either_side_can_play(self) -> None:
        from itertools import combinations
        cards = maneuver_deck.deck_cards(MANEUVERS)
        for hand in combinations(cards, maneuver_deck.HAND_SIZE):
            for side in ("offense", "defense"):
                self.assertTrue(any(
                    maneuver_deck.plays_as(MANEUVERS, card, side)
                    for card in hand
                ), (hand, side))

    def test_a_new_deck_deals_four(self) -> None:
        deck = maneuver_deck.new_deck(MANEUVERS, random.Random(1))
        self.assertEqual(len(deck["hand"]), 4)
        self.assertEqual(len(deck["draw"]), 11)
        self.assertEqual(deck["discard"], [])

    def test_drawing_the_last_card_shuffles_the_discard_into_a_new_deck(self) -> None:
        rng = random.Random(2)
        deck = {"draw": ["basic_1"],
                "hand": ["basic_2", "basic_3", "basic_3", "intercept"],
                "discard": ["clear", "basic_1"]}
        reshuffles = maneuver_deck.play_card(deck, "intercept", rng)
        self.assertEqual(reshuffles, 1)
        self.assertEqual(
            sorted(deck["hand"]), ["basic_1", "basic_2", "basic_3", "basic_3"],
        )
        # The card just played was on the discard when the last card was
        # drawn, so it is in the new deck with the rest.
        self.assertEqual(sorted(deck["draw"]), ["basic_1", "clear", "intercept"])
        self.assertEqual(deck["discard"], [])

    def test_a_play_with_cards_left_is_one_card_in_and_one_out(self) -> None:
        deck = maneuver_deck.new_deck(MANEUVERS, random.Random(3))
        card = deck["hand"][0]
        self.assertEqual(maneuver_deck.play_card(deck, card, random.Random(3)), 0)
        self.assertEqual(len(deck["hand"]), 4)
        self.assertEqual(deck["discard"], [card])
        self.assertEqual(len(deck["draw"]), 10)


    def test_halftime_reshuffles_everything_and_deals_four(self) -> None:
        deck = maneuver_deck.new_deck(MANEUVERS, random.Random(4))
        for _ in range(6):
            maneuver_deck.play_card(deck, deck["hand"][0], random.Random(4))
        fresh = maneuver_deck.reshuffled(deck, random.Random(5))
        self.assertEqual(len(fresh["hand"]), 4)
        self.assertEqual(fresh["discard"], [])
        self.assertEqual(
            Counter(fresh["draw"] + fresh["hand"]),
            Counter(maneuver_deck.deck_cards(MANEUVERS)),
        )

    def test_both_halves_of_a_two_headed_card_share_one_band(self) -> None:
        from d12ball.cards import matchup_rank_groups, two_headed_ranks
        for rank in (1, 2, 3):
            defense = maneuver_deck.plays_as(
                MANEUVERS, maneuver_deck.basic_card_id(rank), "defense",
            )
            self.assertEqual(
                two_headed_ranks(MANEUVERS, rank),
                tuple(
                    group_rank for group_rank, _ in
                    matchup_rank_groups(MANEUVERS, defense, False)
                ),
            )


class EditionSettingTests(unittest.TestCase):

    def test_a_game_starts_in_one_point_oh_and_saves_without_the_field(self) -> None:
        game = build_game()
        self.assertEqual(game.edition, Edition.ONE)
        self.assertNotIn("edition", game.to_dict())

    def test_two_point_oh_is_saved_and_read_back(self) -> None:
        game = two_point_oh()
        data = game.to_dict()
        self.assertEqual(data["edition"], Edition.TWO)
        self.assertEqual(D12BallGame.from_dict(data).edition, Edition.TWO)

    def test_the_tutorial_refuses_two_point_oh(self) -> None:
        game = build_game()
        game.status = game.status.SETUP
        game.pin_tutorial()
        with self.assertRaises(RuleRefusal):
            game.configure("edition", "2.0")


class EngineTests(unittest.TestCase):

    def setUp(self) -> None:
        self.engine = build_engine()
        self.engine.rng.seed(5)

    def test_kickoff_deals_both_decks_in_two_point_oh(self) -> None:
        game = two_point_oh()
        match = build_match()
        self.engine.deal_maneuver_decks(game, match)
        for side in (TeamSide.HOME, TeamSide.VISITING):
            self.assertEqual(len(self.engine.maneuver_deck_hand(match, side)), 4)

    def test_one_point_oh_deals_nothing(self) -> None:
        game = build_game()
        match = build_match()
        self.engine.deal_maneuver_decks(game, match)
        self.assertEqual(match.maneuver_decks, {})

    def test_two_point_oh_has_no_coin(self) -> None:
        game = two_point_oh()
        self.assertTrue(self.engine.gambits_apply(game))
        self.assertFalse(self.engine.coin_applies(game))
        self.assertIsNone(self.engine.coin_holder(game, build_match()))

    def test_halftime_reshuffles_in_two_point_oh_alone(self) -> None:
        one = build_game()
        match = build_match()
        self.assertFalse(self.engine.reshuffle_maneuver_decks(one, match))

        two = two_point_oh()
        self.engine.deal_maneuver_decks(two, match)
        home = match.maneuver_decks["home"]
        maneuver_deck.play_card(home, home["hand"][0], self.engine.rng)
        self.assertTrue(self.engine.reshuffle_maneuver_decks(two, match))
        for deck in match.maneuver_decks.values():
            self.assertEqual(deck["discard"], [])
            self.assertEqual(len(deck["hand"]), 4)
            self.assertEqual(len(deck["draw"]), 11)

    def test_the_hand_is_what_the_cards_play_on_the_side(self) -> None:
        game = two_point_oh()
        match = build_match()
        match.maneuver_decks = {
            "home": {"draw": [], "hand": ["basic_1", "basic_1", "skilled_pass", "clear"],
                     "discard": []},
            "visiting": {"draw": [], "hand": ["basic_2", "double_team", "intercept", "clear"],
                         "discard": []},
        }
        offense_team = match.ball.possession
        hands = {
            TeamSide.HOME: match.maneuver_decks["home"]["hand"],
            TeamSide.VISITING: match.maneuver_decks["visiting"]["hand"],
        }
        keys = [m.key for m in self.engine.maneuver_hand(game, match, "offense")]
        expected = {
            TeamSide.HOME: ["low_pass", "skilled_pass"],
            TeamSide.VISITING: ["dribble_advance"],
        }[TeamSide(offense_team)]
        self.assertEqual(keys, expected, hands)


def maneuver_deck_copy(match: MatchState) -> dict:
    return {
        side: {pile: list(cards) for pile, cards in deck.items()}
        for side, deck in match.maneuver_decks.items()
    }


def _deck_invariants(test: unittest.TestCase, match: MatchState) -> None:
    for side, deck in match.maneuver_decks.items():
        cards = deck["draw"] + deck["hand"] + deck["discard"]
        test.assertEqual(
            Counter(cards), Counter(maneuver_deck.deck_cards(MANEUVERS)), side,
        )
        test.assertEqual(len(deck["hand"]), maneuver_deck.HAND_SIZE, side)
        test.assertTrue(deck["draw"], side)


class WholeGameTests(unittest.TestCase):
    """2.0 in every mode, through the driver with a reload after every
    click (`test_driver_full_game.play`)."""

    def test_whole_games_finish_in_every_mode(self) -> None:
        for mode in (GameMode.TRAINING, GameMode.STANDARD, GameMode.ADVANCED):
            for seed in (11, 12):
                with self.subTest(mode=mode, seed=seed):
                    game = two_point_oh(mode)
                    match = build_match()
                    dealer = build_engine()
                    dealer.rng.seed(seed)
                    dealer.deal_maneuver_decks(game, match)
                    dealt = maneuver_deck_copy(match)
                    game, match, answered = play(seed, game, match)
                    self.assertTrue(game.is_finished)
                    self.assertNotIn(PromptKind.GAMBIT_ANSWER, answered)
                    self.assertIn(PromptKind.MANEUVER_ACTION, answered)
                    _deck_invariants(self, match)
                    # The cards went round.
                    self.assertNotEqual(maneuver_deck_copy(match), dealt)

    def test_a_solo_game_against_dinky_finishes(self) -> None:
        from d12ball.game import AIOpponent
        game = two_point_oh()
        game.player_2_id = None
        game.ai_opponent = AIOpponent.DINKY
        match = build_match()
        dealer = build_engine()
        dealer.rng.seed(21)
        dealer.deal_maneuver_decks(game, match)
        game, match, _ = play(21, game, match)
        self.assertTrue(game.is_finished)
        _deck_invariants(self, match)

    def test_a_card_not_in_the_hand_is_refused(self) -> None:
        from d12ball.flow import driver
        engine = build_engine()
        engine.rng.seed(7)
        game = two_point_oh()
        match = build_match()
        engine.deal_maneuver_decks(game, match)
        from d12ball.flow import FollowOn, FollowOnStep, StepResult
        driver.advance(
            engine, game, match,
            StepResult(next=FollowOn(FollowOnStep.FINISH_SETUP_COACHING)),
        )
        for _ in range(50):
            prompt = pending_prompt(engine, game, match)
            if prompt.kind is PromptKind.MANEUVER_ACTION:
                break
            if prompt.kind is PromptKind.PLAYER_ACTION:
                driver.apply(engine, game, match, Action(prompt.kind, "maneuver"))
                continue
            from test_d12ball_driver_actions import LEGAL_ACTIONS
            from test_driver_full_game import _Fixture
            choice, arguments = LEGAL_ACTIONS[prompt.kind](_Fixture(game, match))
            driver.apply(engine, game, match, Action(prompt.kind, choice, arguments))
        hand = prompt.options.hands[0]
        missing = next(
            m.key for m in MANEUVERS.side(hand.side)
            if m.key not in hand.maneuver_keys
        )
        run = driver.apply(engine, game, match, Action(
            PromptKind.MANEUVER_ACTION, "",
            {"side": hand.side, "maneuver_key": missing},
        ))
        self.assertIsInstance(run, driver.Refusal)
        self.assertEqual(len(hand.held), 4)


if __name__ == "__main__":
    unittest.main()
