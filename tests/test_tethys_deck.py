"""The Tethys decks' rule -- the classic deck's and the 2d12 deck's: which
card is which fate, and how a value is made of pieces. Nothing drawn is tested (the author, 2026-09-23); this is
the data under the drawings.
"""
import unittest
from collections import Counter
from math import comb

from tethysdeck import deck, deck_2d12, sets, sets_2d12


# The author's rule, as the World Building sheet's table holds it.
EXPECTED = {
    "money": ("fortune", "doom", "fortune", "doom"),
    "might": ("fortune", "doom", "doom", "fortune"),
    "fiends": ("doom", "fortune", "fortune", "doom"),
    "tools": ("doom", "fortune", "doom", "fortune"),
    "states": ("fortune", "doom", "fortune", "doom"),
    "fools": ("doom", "fortune", "doom", "fortune"),
}  # odd cards, even cards, Left, Right


class FateRuleTests(unittest.TestCase):
    def test_the_table(self):
        for suit, (odd, even, left, right) in EXPECTED.items():
            for rank in deck.RANKS[:10]:
                self.assertEqual(deck.fate_of(suit, rank), odd if int(rank) % 2 else even, (suit, rank))
            self.assertEqual(deck.fate_of(suit, "Left"), left, suit)
            self.assertEqual(deck.fate_of(suit, "Right"), right, suit)

    def test_the_rulers_are_split_between_the_fates(self):
        lefts = [deck.fate_of(suit, "Left") for suit in deck.SUITS]
        self.assertEqual(lefts.count("fortune"), 3)
        for suit in deck.SUITS:
            self.assertNotEqual(deck.fate_of(suit, "Left"), deck.fate_of(suit, "Right"), suit)

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


class PictureNamesTests(unittest.TestCase):
    """The committed pictures are named as `icons.icon_name` names a piece, so
    `IconSet` finds each one; the pictures themselves are not tested."""

    def test_every_picture_is_a_piece(self):
        from tethysdeck import icons
        from tethysdeck.relief import PICTURES

        names = {icons.icon_name(suit, variant, fate) for suit, variant, fate in icons.every_icon()}
        for path in sorted(PICTURES.glob("*.png")):
            self.assertIn(path.stem, names, path.name)

# Every hand of six by its best set, (mixed, uniform). The totals per set are
# as a brute-force walk of all 156,238,908 hands counted them (2026-10-09);
# the uniform share -- all six Fortune or all six Doom -- depends on the fate
# table, and was re-walked over the 3,895,584 uniform hands when Left's fate
# became the table's own input (the same day), the mixed share following.
CENSUS = {
    "six_of_a_kind": (10, 0),
    "straight_flush": (42, 0),
    "five_of_a_kind": (3_960, 0),
    "flush": (5_490, 12),
    "two_triples": (17_910, 90),
    "four_of_a_kind": (321_750, 0),
    "straight": (316_344, 10_206),
    "three_pairs": (789_338, 14_312),
    "three_of_a_kind": (9_007_060, 108_940),
    "two_pairs": (24_697_350, 537_750),
    "one_pair": (76_199_472, 1_976_400),
    "no_set": (40_984_598, 1_247_874),
}


class SixCardSetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.census = sets.census()

    def test_the_census(self):
        self.assertEqual({key: (c.mixed, c.uniform) for key, c in self.census.items()}, CENSUS)
        self.assertEqual(sum(c.total for c in self.census.values()), comb(72, 6))

    def test_by_formula(self):
        """Only the numbers make four or more of a kind, six cards each."""
        self.assertEqual(self.census["six_of_a_kind"].total, 10)
        self.assertEqual(self.census["five_of_a_kind"].total, 10 * 6 * 66)
        self.assertEqual(self.census["four_of_a_kind"].total, 10 * comb(6, 4) * comb(66, 2))
        # Five runs of numbers in one suit, and 6-10 then either ruler.
        self.assertEqual(self.census["straight_flush"].total, 6 * (5 + 2))
        self.assertEqual(self.census["flush"].total, 6 * comb(12, 6) - 42)

    def test_the_sets_are_rarest_first_and_no_set_last(self):
        totals = [self.census[s.key].total for s in sets.SETS[:-1]]
        self.assertEqual(totals, sorted(totals))
        self.assertEqual(sets.SETS[-1].key, "no_set")

    def test_every_example_is_its_set_and_mixed(self):
        for s in sets.SETS:
            self.assertEqual(len(set(s.example)), 6, s.key)
            self.assertEqual(sets.set_of(s.example), s.key, s.key)
            self.assertFalse(sets.is_uniform(s.example), s.key)

    def test_a_left_pairs_only_with_a_right(self):
        def hand(*rulers):
            numbers = (("fiends", "1"), ("tools", "3"), ("states", "5"), ("fools", "7"), ("money", "9"))
            return tuple(zip(("money", "might", "tools", "states"), rulers)) + numbers[:6 - len(rulers)]

        self.assertEqual(sets.set_of(hand("Left", "Right")), "one_pair")
        self.assertEqual(sets.set_of(hand("Left", "Left")), "no_set")
        self.assertEqual(sets.set_of(hand("Right", "Right")), "no_set")
        self.assertEqual(sets.set_of(hand("Left", "Left", "Right")), "one_pair")
        self.assertEqual(sets.set_of(hand("Left", "Left", "Right", "Right")), "two_pairs")
        self.assertEqual(sets.set_of((("money", "6"), ("might", "7"), ("fiends", "8"),
                                      ("tools", "9"), ("states", "10"), ("fools", "Right"))), "straight")


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


class TwoDiceDeckTests(unittest.TestCase):
    def test_the_suits_are_the_documents(self):
        for suit, values in zip(deck.SUITS, STRUCTURE_E):
            self.assertEqual(tuple(c.value for c in deck_2d12.suit_cards(suit)), values, suit)

    def test_the_counts_are_the_documents(self):
        self.assertEqual(Counter(c.value for c in deck_2d12.cards()), deck_2d12.COUNTS)
        self.assertEqual(sum(deck_2d12.COUNTS.values()), 72)
        self.assertEqual(deck_2d12.VALUES, tuple(range(2, 25)))

    def test_every_suit_is_six_and_six_and_worth_the_same(self):
        for suit in deck.SUITS:
            for table in (deck_2d12.FORTUNE, deck_2d12.DOOM):
                self.assertEqual(len(table[suit]), 6, suit)
                self.assertEqual(sum(table[suit]), 78, suit)

    def test_the_deck_is_its_own_mirror(self):
        fortune = Counter(v for values in deck_2d12.FORTUNE.values() for v in values)
        doom = Counter(v for values in deck_2d12.DOOM.values() for v in values)
        for value in deck_2d12.VALUES:
            self.assertEqual(fortune[value], doom[26 - value], value)

    def test_repeats_are_split_between_the_fates_where_they_can_be(self):
        """Four cards are the same card twice, the fewest any mirrored split leaves."""
        repeats = sum(n * (n - 1) // 2 for n in Counter(deck_2d12.cards()).values())
        self.assertEqual(repeats, 4)
        self.assertEqual(len(deck_2d12.faces()), 68)

    def test_pieces_make_the_value_with_the_fewest(self):
        value_of = {(metal, amount): value for metal, amount, value in deck.COIN_WORTH}
        for c in deck_2d12.cards():
            pieces = deck_2d12.pieces(c)
            self.assertEqual(sum(pieces), c.value, c)
            self.assertLessEqual(len(pieces), 5, c)
            coins = deck_2d12.money_coins(c)
            self.assertEqual(sum(value_of[coin] for coin in coins), c.value, c)
            self.assertLessEqual(len(coins), 4, c)
        # Only one face is five pieces, and it is not Money's.
        fives = [c for c in deck_2d12.cards() if c.suit != "money" and len(deck_2d12.pieces(c)) == 5]
        self.assertEqual(fives, [deck_2d12.Card("tools", 23, "doom")])


# Every hand of six from the 2d12 deck by its best set, (mixed, uniform), as a
# walk of all 156,238,908 hands one by one counted them (2026-10-27); all
# Fortune and all Doom were counted apart there, and were equal in every set.
CENSUS_2D12 = {
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


class TwoDiceSetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.census = sets_2d12.census()

    def test_the_census(self):
        self.assertEqual({key: (c.mixed, c.uniform) for key, c in self.census.items()}, CENSUS_2D12)
        self.assertEqual(sum(c.total for c in self.census.values()), comb(72, 6))

    def test_by_formula(self):
        # 13 is eight cards, 12 and 14 six each.
        self.assertEqual(self.census["six_of_a_kind"].total, comb(8, 6) + 2)
        self.assertEqual(self.census["flush"].total, 6 * comb(12, 6))

    def test_no_suit_holds_six_in_a_row(self):
        for suit in deck.SUITS:
            values = sorted({c.value for c in deck_2d12.suit_cards(suit)})
            self.assertFalse(any(values[i + 5] - values[i] == 5 for i in range(len(values) - 5)), suit)

    def test_the_sets_are_rarest_first_and_no_set_last(self):
        totals = [self.census[s.key].total for s in sets_2d12.SETS[:-1]]
        self.assertEqual(totals, sorted(totals))
        self.assertEqual(sets_2d12.SETS[-1].key, "no_set")

    def test_every_example_is_its_set_mixed_and_in_the_deck(self):
        held = Counter(deck_2d12.cards())
        for s in sets_2d12.SETS:
            self.assertEqual(len(set(s.example)), 6, s.key)
            self.assertTrue(all(held[c] for c in s.example), s.key)
            self.assertEqual(sets_2d12.set_of(s.example), s.key, s.key)
            self.assertFalse(sets_2d12.is_uniform(s.example), s.key)

    def test_a_flush_is_a_flush_whatever_it_holds(self):
        money = [c for c in deck_2d12.suit_cards("money") if c.value in (13, 5, 8, 9)]
        self.assertEqual([c.value for c in money], [5, 8, 9, 13, 13, 13])
        self.assertEqual(sets_2d12.set_of(money), "flush")


class CogAgreementTests(unittest.TestCase):
    """The bot deals the same deck by name."""

    def test_the_cog_names_the_same_cards(self):
        from cogs.tethysdeck_helpers import RANKS, SUITS

        self.assertEqual([name.lower() for _, name in SUITS], deck.SUITS)
        self.assertEqual(RANKS, deck.RANKS)


if __name__ == "__main__":
    unittest.main()
