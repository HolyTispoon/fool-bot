"""The Tethys deck's rule: which card is which fate, and how a value is
made of pieces. Nothing drawn is tested (the author, 2026-09-23); this is
the data under the drawings.
"""
import unittest
from collections import Counter
from math import comb

from tethysdeck import deck, sets


# Structure E of the author's "2d12 Distribution Card Deck" document, its six
# suits in its order -- dealt to the suits in the author's order.
STRUCTURE_E = (
    (5, 8, 9, 10, 12, 13, 13, 13, 15, 16, 18, 24),
    (4, 9, 10, 11, 11, 13, 14, 14, 15, 15, 17, 23),
    (3, 7, 8, 11, 11, 12, 12, 16, 17, 18, 19, 22),
    (2, 8, 9, 11, 12, 13, 14, 14, 16, 17, 19, 21),
    (6, 7, 9, 10, 12, 13, 13, 15, 15, 18, 18, 20),
    (6, 7, 8, 10, 12, 13, 14, 14, 16, 17, 19, 20),
)


class DeckTests(unittest.TestCase):
    def test_the_suits_are_the_documents(self):
        for suit, values in zip(deck.SUITS, STRUCTURE_E):
            self.assertEqual(tuple(c.value for c in deck.suit_cards(suit)), values, suit)

    def test_the_counts_are_the_documents(self):
        self.assertEqual(Counter(c.value for c in deck.cards()), deck.COUNTS)
        self.assertEqual(sum(deck.COUNTS.values()), 72)
        self.assertEqual(deck.VALUES, tuple(range(2, 25)))

    def test_every_suit_is_six_and_six_and_worth_the_same(self):
        for suit in deck.SUITS:
            for table in (deck.FORTUNE, deck.DOOM):
                self.assertEqual(len(table[suit]), 6, suit)
                self.assertEqual(sum(table[suit]), 78, suit)

    def test_the_deck_is_its_own_mirror(self):
        fortune = Counter(v for values in deck.FORTUNE.values() for v in values)
        doom = Counter(v for values in deck.DOOM.values() for v in values)
        for value in deck.VALUES:
            self.assertEqual(fortune[value], doom[26 - value], value)

    def test_repeats_are_split_between_the_fates_where_they_can_be(self):
        """Four cards are the same card twice, the fewest any mirrored split leaves."""
        repeats = sum(n * (n - 1) // 2 for n in Counter(deck.cards()).values())
        self.assertEqual(repeats, 4)
        self.assertEqual(len(deck.faces()), 68)

    def test_pieces_make_the_value_with_the_fewest(self):
        value_of = {(metal, amount): value for metal, amount, value in deck.COIN_WORTH}
        for c in deck.cards():
            pieces = deck.pieces(c)
            self.assertEqual(pieces, sorted(pieces, reverse=True), c)
            self.assertTrue(set(pieces) <= set(deck.DENOMINATIONS), c)
            self.assertEqual(sum(pieces), c.value, c)
            self.assertLessEqual(len(pieces), 5, c)
            coins = deck.money_coins(c)
            self.assertEqual(sum(value_of[coin] for coin in coins), c.value, c)
            self.assertLessEqual(len(coins), 4, c)
        # Only one face is five pieces, and it is not Money's.
        fives = [c for c in deck.cards() if c.suit != "money" and len(deck.pieces(c)) == 5]
        self.assertEqual(fives, [deck.Card("tools", 23, "doom")])


# Every hand of six by its best set, (mixed, uniform), as a
# walk of all 156,238,908 hands one by one counted them (2026-10-27); all
# Fortune and all Doom were counted apart there, and were equal in every set.
CENSUS = {
    "six_of_a_kind": (30, 0),
    "five_of_a_kind": (4_510, 0),
    "flush": (5_532, 12),
    "two_triples": (7_833, 132),
    "straight": (145_410, 5_370),
    "three_pairs": (207_062, 4_392),
    "four_of_a_kind": (239_264, 1_984),
    "three_of_a_kind": (6_279_586, 133_656),
    "two_pairs": (11_318_613, 262_890),
    "one_pair": (64_744_318, 1_626_826),
    "no_set": (69_391_166, 1_860_322),
}


class SixCardSetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.census = sets.census()

    def test_the_census(self):
        self.assertEqual({key: (c.mixed, c.uniform) for key, c in self.census.items()}, CENSUS)
        self.assertEqual(sum(c.total for c in self.census.values()), comb(72, 6))

    def test_by_formula(self):
        # 13 is eight cards, 12 and 14 six each.
        self.assertEqual(self.census["six_of_a_kind"].total, comb(8, 6) + 2)
        self.assertEqual(self.census["flush"].total, 6 * comb(12, 6))

    def test_no_suit_holds_six_in_a_row(self):
        for suit in deck.SUITS:
            values = sorted({c.value for c in deck.suit_cards(suit)})
            self.assertFalse(any(values[i + 5] - values[i] == 5 for i in range(len(values) - 5)), suit)

    def test_the_sets_are_rarest_first_and_no_set_last(self):
        totals = [self.census[s.key].total for s in sets.SETS[:-1]]
        self.assertEqual(totals, sorted(totals))
        self.assertEqual(sets.SETS[-1].key, "no_set")

    def test_every_example_is_its_set_mixed_and_in_the_deck(self):
        held = Counter(deck.cards())
        for s in sets.SETS:
            self.assertEqual(len(set(s.example)), 6, s.key)
            self.assertTrue(all(held[c] for c in s.example), s.key)
            self.assertEqual(sets.set_of(s.example), s.key, s.key)
            self.assertFalse(sets.is_uniform(s.example), s.key)

    def test_a_flush_is_a_flush_whatever_it_holds(self):
        money = [c for c in deck.suit_cards("money") if c.value in (13, 5, 8, 9)]
        self.assertEqual([c.value for c in money], [5, 8, 9, 13, 13, 13])
        self.assertEqual(sets.set_of(money), "flush")


class VariantTests(unittest.TestCase):
    def test_every_variant_is_a_denomination(self):
        for suit, variants in deck.VARIANTS.items():
            self.assertIn(suit, deck.SUITS)
            self.assertEqual(set(variants), set(deck.DENOMINATIONS), suit)
        self.assertEqual(set(deck.VARIANTS), {"might", "tools"})


class PictureNamesTests(unittest.TestCase):
    """The committed pictures are named as `icons.icon_name` names a piece, so
    `IconSet` finds each one; the pictures themselves are not tested."""

    def test_every_picture_is_a_piece(self):
        from tethysdeck import icons
        from tethysdeck.relief import PICTURES

        names = {icons.icon_name(suit, variant, fate) for suit, variant, fate in icons.every_icon()}
        for path in sorted(PICTURES.glob("*.png")):
            self.assertIn(path.stem, names, path.name)

class CogAgreementTests(unittest.TestCase):
    """The bot deals the same deck by name."""

    def test_the_cog_names_the_same_suits(self):
        from cogs.tethysdeck_helpers import SUITS

        self.assertEqual([name.lower() for _, name in SUITS], deck.SUITS)


if __name__ == "__main__":
    unittest.main()
