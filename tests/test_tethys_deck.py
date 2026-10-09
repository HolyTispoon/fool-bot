"""The Tethys deck's rule: which card is which fate, and how a value is
made of pieces. Nothing drawn is tested (the author, 2026-09-23); this is
the data under the drawings.
"""
import unittest

from tethysdeck import deck


# The author's rule, as the World Building sheet's table holds it.
EXPECTED = {
    "money": ("fortune", "doom", "fortune", "doom"),
    "might": ("fortune", "doom", "fortune", "doom"),
    "fiends": ("doom", "fortune", "fortune", "doom"),
    "tools": ("doom", "fortune", "doom", "fortune"),
    "states": ("fortune", "doom", "doom", "fortune"),
    "fools": ("doom", "fortune", "fortune", "doom"),
}  # odd cards, even cards, Left, Right


class FateRuleTests(unittest.TestCase):
    def test_the_table(self):
        for suit, (odd, even, left, right) in EXPECTED.items():
            for rank in deck.RANKS[:10]:
                self.assertEqual(deck.fate_of(suit, rank), odd if int(rank) % 2 else even, (suit, rank))
            self.assertEqual(deck.fate_of(suit, "Left"), left, suit)
            self.assertEqual(deck.fate_of(suit, "Right"), right, suit)

    def test_every_suit_is_six_and_six(self):
        for suit in deck.SUITS:
            fates = [deck.fate_of(suit, rank) for rank in deck.RANKS]
            self.assertEqual(fates.count("fortune"), 6, suit)
            self.assertEqual(fates.count("doom"), 6, suit)

    def test_the_deck_is_seventy_two(self):
        self.assertEqual(len(deck.SUITS) * len(deck.RANKS), 72)


class PiecesTests(unittest.TestCase):
    def test_pieces_make_the_value_with_the_fewest(self):
        for suit in deck.SUITS:
            for rank in deck.RANKS:
                pieces = deck.pieces(suit, rank)
                self.assertEqual(sum(pieces), deck.worth(suit, rank), (suit, rank))
                self.assertEqual(pieces, sorted(pieces, reverse=True), (suit, rank))
                self.assertLessEqual(len(pieces), 4, (suit, rank))
                self.assertTrue(set(pieces) <= set(deck.DENOMINATIONS), (suit, rank))

    def test_the_two_rulers_share_the_power_equally(self):
        for suit in deck.SUITS:
            self.assertEqual(deck.worth(suit, "Left"), deck.worth(suit, "Right"), suit)
            self.assertEqual(deck.worth(suit, "Left"), 12, suit)
            self.assertEqual(deck.pieces(suit, "Left"), [12], suit)
            self.assertEqual(deck.pieces(suit, "Right"), [12], suit)
        self.assertEqual(deck.money_coins("Left"), [("gold", 1)])
        self.assertEqual(deck.money_coins("Right"), [("gold", 1)])
        self.assertEqual(deck.pieces("tools", "Right"), [12])

    def test_money_coins_make_the_value_in_dinkies(self):
        value_of = {(metal, amount): value for metal, amount, value in deck.COIN_WORTH}
        for rank in deck.RANKS:
            coins = deck.money_coins(rank)
            self.assertEqual(sum(value_of[coin] for coin in coins), deck.worth("money", rank), rank)
            self.assertLessEqual(len(coins), 4, rank)

    def test_every_variant_is_a_denomination(self):
        for suit, variants in deck.VARIANTS.items():
            self.assertIn(suit, deck.SUITS)
            self.assertEqual(set(variants), set(deck.DENOMINATIONS), suit)
        self.assertEqual(set(deck.VARIANTS), {"might", "tools"})


class CogAgreementTests(unittest.TestCase):
    """The bot deals the same deck by name."""

    def test_the_cog_names_the_same_cards(self):
        from cogs.tethysdeck_helpers import RANKS, SUITS

        self.assertEqual([name.lower() for _, name in SUITS], deck.SUITS)
        self.assertEqual(RANKS, deck.RANKS)


if __name__ == "__main__":
    unittest.main()
