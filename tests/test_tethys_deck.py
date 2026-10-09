"""The Tethys deck's rule: which card is which fate, and how a value is
made of pieces. Nothing drawn is tested (the author, 2026-09-23); this is
the data under the drawings.
"""
import unittest
from math import comb

from tethysdeck import deck, sets


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

    def test_a_ruler_is_twelve_for_fortune_and_eleven_for_doom(self):
        for suit in deck.SUITS:
            for rank in ("Left", "Right"):
                expected = 12 if deck.fate_of(suit, rank) == "fortune" else 11
                self.assertEqual(deck.worth(suit, rank), expected, (suit, rank))
        self.assertEqual(deck.worth("money", "Left"), 12)
        self.assertEqual(deck.worth("money", "Right"), 11)
        self.assertEqual(deck.pieces("tools", "Left"), [6, 3, 1, 1])
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


# Every hand of six by its best set, (mixed, uniform), as a brute-force
# walk of all 156,238,908 hands counted them (2026-10-09).
CENSUS = {
    "straight_flush": (42, 0),
    "six_of_a_kind": (932, 2),
    "flush": (5_490, 12),
    "five_of_a_kind": (51_120, 360),
    "two_triples": (61_510, 490),
    "straight": (316_344, 10_206),
    "three_pairs": (1_054_620, 18_630),
    "four_of_a_kind": (1_184_850, 13_050),
    "three_of_a_kind": (16_285_860, 270_540),
    "two_pairs": (28_256_040, 612_360),
    "no_set": (105_126_516, 2_969_934),
}


class SixCardSetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.census = sets.census()

    def test_the_census(self):
        self.assertEqual({key: (c.mixed, c.uniform) for key, c in self.census.items()}, CENSUS)
        self.assertEqual(sum(c.total for c in self.census.values()), comb(72, 6))

    def test_by_formula(self):
        """Left and Right make one rank of twelve cards; the numbers six each."""
        self.assertEqual(self.census["six_of_a_kind"].total, 10 + comb(12, 6))
        # Five runs of numbers in one suit, and 6-10 then either ruler.
        self.assertEqual(self.census["straight_flush"].total, 6 * (5 + 2))
        self.assertEqual(self.census["flush"].total, 6 * comb(12, 6) - 42)

    def test_the_sets_are_rarest_first(self):
        totals = [self.census[s.key].total for s in sets.SETS]
        self.assertEqual(totals, sorted(totals))

    def test_every_example_is_its_set_and_mixed(self):
        for s in sets.SETS:
            self.assertEqual(len(set(s.example)), 6, s.key)
            self.assertEqual(sets.set_of(s.example), s.key, s.key)
            self.assertFalse(sets.is_uniform(s.example), s.key)

    def test_left_and_right_pair_and_follow_ten(self):
        self.assertEqual(sets.set_of((("money", "Left"), ("might", "Right"), ("fiends", "1"),
                                      ("tools", "3"), ("states", "5"), ("fools", "7"))), "no_set")
        self.assertEqual(sets.set_of((("money", "Left"), ("might", "Right"), ("fiends", "1"),
                                      ("tools", "1"), ("states", "5"), ("fools", "7"))), "two_pairs")
        self.assertEqual(sets.set_of((("money", "6"), ("might", "7"), ("fiends", "8"),
                                      ("tools", "9"), ("states", "10"), ("fools", "Right"))), "straight")


class CogAgreementTests(unittest.TestCase):
    """The bot deals the same deck by name."""

    def test_the_cog_names_the_same_cards(self):
        from cogs.tethysdeck_helpers import RANKS, SUITS

        self.assertEqual([name.lower() for _, name in SUITS], deck.SUITS)
        self.assertEqual(RANKS, deck.RANKS)


if __name__ == "__main__":
    unittest.main()
