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


class CogAgreementTests(unittest.TestCase):
    """The bot deals the same deck by name."""

    def test_the_cog_names_the_same_cards(self):
        from cogs.tethysdeck_helpers import RANKS, SUITS

        self.assertEqual([name.lower() for _, name in SUITS], deck.SUITS)
        self.assertEqual(RANKS, deck.RANKS)


if __name__ == "__main__":
    unittest.main()
