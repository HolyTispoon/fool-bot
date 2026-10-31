"""
D12 Ball 2.1's maneuver deck (`d12ball/maneuver_deck.py`): the
twenty-four cards, the flip, the hand of five, the discard and the
reshuffle -- and whole 2.1 games through the driver, with the save reloaded after every click, as
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

from test_driver_full_game import Policy, build_engine, build_game, build_match, play


def two_point_oh(mode: GameMode = GameMode.ADVANCED) -> D12BallGame:
    game = build_game()
    game.mode = mode
    game.edition = Edition.TWO
    return game


class DeckTests(unittest.TestCase):

    def test_twenty_four_cards_four_a_basic_maneuver(self) -> None:
        cards = maneuver_deck.deck_cards(MANEUVERS)
        self.assertEqual(len(cards), 24)
        self.assertEqual(len(set(cards)), 24)
        per_maneuver = Counter(
            MANEUVERS.deck_card(card).maneuver for card in cards
        )
        self.assertEqual(set(per_maneuver.values()), {4})
        self.assertEqual(
            set(per_maneuver),
            {m.key for side in ("offense", "defense")
             for m in MANEUVERS.side(side) if not m.is_gambit},
        )
        # No advanced maneuvers.
        self.assertFalse(any(
            MANEUVERS.definition(MANEUVERS.deck_card(card).maneuver).is_gambit
            for card in cards
        ))

    def test_a_card_is_keyed_by_its_index_not_its_name(self) -> None:
        # P3 is named after 1.0's advanced pass, and plays a Pass.
        card = MANEUVERS.deck_card("P3")
        self.assertEqual(card.name, "Pinpoint")
        self.assertEqual(card.maneuver, "low_pass")
        self.assertEqual(MANEUVERS.deck_card("P4").name, "Reset")

    def test_a_card_plays_its_own_maneuver_or_flips_to_the_other_sides(self) -> None:
        self.assertEqual(
            maneuver_deck.plays_as(MANEUVERS, "P1", "offense"), ("low_pass", False),
        )
        self.assertEqual(
            maneuver_deck.plays_as(MANEUVERS, "P1", "defense"), ("deflect", True),
        )
        self.assertEqual(
            maneuver_deck.plays_as(MANEUVERS, "F2", "offense"), ("low_pass", True),
        )
        self.assertEqual(
            maneuver_deck.plays_as(MANEUVERS, "S4", "offense"),
            ("dribble_advance", True),
        )
        self.assertEqual(
            maneuver_deck.plays_as(MANEUVERS, "H1", "defense"), ("pressure", True),
        )

    def test_each_ranks_specials_name_every_role_once(self) -> None:
        from d12ball.components import PlayerRole
        by_rank: dict = {}
        for card in MANEUVERS.deck_cards:
            by_rank.setdefault((card.side, card.rank), []).extend(card.roles)
        for key, roles in by_rank.items():
            self.assertEqual(sorted(roles), sorted(PlayerRole), key)

    def test_every_special_the_rules_read_is_a_card(self) -> None:
        for index in maneuver_deck.SPECIAL_INDEXES:
            self.assertIsNotNone(MANEUVERS.deck_card(index), index)
        self.assertEqual(
            set(maneuver_deck.SPECIAL_INDEXES),
            set(maneuver_deck.deck_cards(MANEUVERS)),
        )

    def test_a_new_deck_deals_five(self) -> None:
        deck = maneuver_deck.new_deck(MANEUVERS, random.Random(1))
        self.assertEqual(len(deck["hand"]), 5)
        self.assertEqual(len(deck["draw"]), 19)
        self.assertEqual(deck["discard"], [])

    def test_drawing_the_last_card_shuffles_the_discard_into_a_new_deck(self) -> None:
        rng = random.Random(2)
        deck = {"draw": ["P1"],
                "hand": ["B1", "B2", "H1", "H2", "S1"],
                "discard": ["F1", "R1"]}
        reshuffles = maneuver_deck.play_cards(deck, ["S1"], rng)
        self.assertEqual(reshuffles, 1)
        self.assertEqual(sorted(deck["hand"]), ["B1", "B2", "H1", "H2", "P1"])
        # The card just played was on the discard when the last card was
        # drawn, so it is in the new deck with the rest.
        self.assertEqual(sorted(deck["draw"]), ["F1", "R1", "S1"])
        self.assertEqual(deck["discard"], [])

    def test_a_play_is_one_card_in_and_one_out(self) -> None:
        deck = maneuver_deck.new_deck(MANEUVERS, random.Random(3))
        card = deck["hand"][0]
        self.assertEqual(maneuver_deck.play_cards(deck, [card], random.Random(3)), 0)
        self.assertEqual(len(deck["hand"]), 5)
        self.assertEqual(deck["discard"], [card])
        self.assertEqual(len(deck["draw"]), 18)

    def test_a_flip_discards_two_and_draws_two(self) -> None:
        deck = maneuver_deck.new_deck(MANEUVERS, random.Random(3))
        played, extra = deck["hand"][:2]
        maneuver_deck.play_cards(deck, [played, extra], random.Random(3))
        self.assertEqual(len(deck["hand"]), 5)
        self.assertEqual(deck["discard"], [played, extra])
        self.assertEqual(len(deck["draw"]), 17)

    def test_halftime_reshuffles_everything_and_deals_five(self) -> None:
        deck = maneuver_deck.new_deck(MANEUVERS, random.Random(4))
        for _ in range(6):
            maneuver_deck.play_cards(deck, [deck["hand"][0]], random.Random(4))
        fresh = maneuver_deck.reshuffled(deck, random.Random(5))
        self.assertEqual(len(fresh["hand"]), 5)
        self.assertEqual(fresh["discard"], [])
        self.assertEqual(
            Counter(fresh["draw"] + fresh["hand"]),
            Counter(maneuver_deck.deck_cards(MANEUVERS)),
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
            self.assertEqual(len(self.engine.maneuver_deck_hand(match, side)), 5)

    def test_one_point_oh_deals_nothing(self) -> None:
        game = build_game()
        match = build_match()
        self.engine.deal_maneuver_decks(game, match)
        self.assertEqual(match.maneuver_decks, {})

    def test_two_point_one_has_no_gambits_and_no_gambit_coin(self) -> None:
        game = two_point_oh()
        self.assertFalse(self.engine.gambits_apply(game))
        self.assertFalse(self.engine.coin_applies(game))
        self.assertIsNone(self.engine.coin_holder(game, build_match()))

    def test_halftime_reshuffles_in_two_point_oh_alone(self) -> None:
        one = build_game()
        match = build_match()
        self.assertFalse(self.engine.reshuffle_maneuver_decks(one, match))

        two = two_point_oh()
        self.engine.deal_maneuver_decks(two, match)
        home = match.maneuver_decks["home"]
        maneuver_deck.play_cards(home, [home["hand"][0]], self.engine.rng)
        self.assertTrue(self.engine.reshuffle_maneuver_decks(two, match))
        for deck in match.maneuver_decks.values():
            self.assertEqual(deck["discard"], [])
            self.assertEqual(len(deck["hand"]), 5)
            self.assertEqual(len(deck["draw"]), 19)

    def test_the_hand_plays_its_own_cards_and_flips_the_others(self) -> None:
        game = two_point_oh()
        match = build_match()
        match.maneuver_decks = {
            side: {"draw": [], "hand": ["P1", "P2", "F3", "S1", "R2"], "discard": []}
            for side in ("home", "visiting")
        }
        plays = self.engine.card_plays(game, match, "offense")
        self.assertEqual(
            [(p.card_id, p.maneuver_key, p.flip) for p in plays],
            [("P1", "low_pass", False), ("P2", "low_pass", False),
             ("F3", "low_pass", True), ("S1", "dribble_advance", True),
             ("R2", "high_pass", True)],
        )
        # A flip may discard any other card in the hand.
        self.assertEqual(plays[2].extra_ids, ("P1", "P2", "S1", "R2"))
        keys = [m.key for m in self.engine.maneuver_hand(game, match, "offense")]
        self.assertEqual(keys, ["low_pass", "dribble_advance", "high_pass"])

    def test_a_lone_card_of_the_other_side_cannot_flip(self) -> None:
        game = two_point_oh()
        match = build_match()
        match.maneuver_decks = {
            side: {"draw": [], "hand": ["F1"], "discard": []}
            for side in ("home", "visiting")
        }
        self.assertEqual(self.engine.card_plays(game, match, "offense"), ())


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


class DeckPolicy(Policy):
    """The full-game policy, but for the shot. It shoots whenever one
    is offered, which in 1.0 is only in range; 2.0 has no range
    (docs/rules-2.1.md section 6), so a shot is offered every turn and
    that policy would never play a card. This one shoots a turn in
    three, off the engine's own stream, and otherwise plays the turn
    as the policy does."""

    def action(self, match, prompt):
        if (
            prompt.kind is PromptKind.PLAYER_ACTION
            and "shoot" in prompt.options.live
            and self.engine.rng.randrange(3)
        ):
            if "time_out" in prompt.options.live:
                return Action(prompt.kind, "time_out")
            return Action(prompt.kind, "maneuver")
        return super().action(match, prompt)


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
                    game, match, answered = play(
                        seed, game, match, policy_class=DeckPolicy,
                    )
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
        game, match, _ = play(21, game, match, policy_class=DeckPolicy)
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
            card for card in maneuver_deck.deck_cards(MANEUVERS)
            if card not in hand.held
        )
        key, _ = maneuver_deck.plays_as(MANEUVERS, missing, hand.side)
        run = driver.apply(engine, game, match, Action(
            PromptKind.MANEUVER_ACTION, "",
            {"side": hand.side, "maneuver_key": key, "card_id": missing},
        ))
        self.assertIsInstance(run, driver.Refusal)
        self.assertEqual(len(hand.held), 5)
        # No card at all is refused too, and so is a flip with no extra.
        for arguments in (
            {"maneuver_key": hand.cards[0].maneuver_key},
            *(
                {"maneuver_key": play.maneuver_key, "card_id": play.card_id}
                for play in hand.cards if play.flip
            ),
        ):
            run = driver.apply(engine, game, match, Action(
                PromptKind.MANEUVER_ACTION, "", {"side": hand.side, **arguments},
            ))
            self.assertIsInstance(run, driver.Refusal, arguments)


if __name__ == "__main__":
    unittest.main()
