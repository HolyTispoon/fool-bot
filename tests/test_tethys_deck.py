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


# Tethys 2.0's census, (mixed, all Fortune, all Doom): as an evaluator written
# apart from `sets.py` counted it, walking all 12,271,512 hands and trying
# every partition of each hand's rulers (2026-10-11).
CENSUS_2 = {
    "six_of_a_kind": (2, 0, 0),
    "straight_flush": (51, 0, 0),
    "five_of_a_kind": (504, 0, 0),
    "two_triples": (944, 1, 1),
    "flush": (2_997, 7, 7),
    "four_of_a_kind": (25_830, 0, 0),
    "three_pairs": (35_006, 209, 209),
    "straight": (53_244, 804, 576),
    "three_of_a_kind": (622_272, 2_658, 2_658),
    "two_pairs": (1_437_408, 11_916, 11_916),
    "one_pair": (5_779_620, 63_789, 63_897),
    "no_set": (4_044_442, 55_212, 55_332),
}


class Tethys2DeckTests(unittest.TestCase):
    """2.0 (the author, 2026-10-11): the suits share the numbers 1 to 12 out
    between them, each keeps two rulers worth 13, and 1.0 stands beside it."""

    deck = deck.TETHYS_2

    def test_the_suits_hold_their_numbers(self):
        numbers = {suit: [int(r) for r in ranks if r not in deck.RULERS] for suit, ranks in self.deck.ranks.items()}
        self.assertEqual(numbers, {
            "money": list(range(1, 13)), "fiends": list(range(1, 7)), "fools": list(range(7, 13)),
            "tools": list(range(1, 5)), "states": list(range(5, 9)), "might": list(range(9, 13)),
        })
        self.assertEqual(self.deck.suits, deck.SUITS)
        for suit in self.deck.suits:
            self.assertEqual(self.deck.ranks[suit][-2:], ["Left", "Right"], suit)
        self.assertEqual(len(self.deck.cards()), 48)

    def test_every_number_three_times(self):
        numbers = [rank for _, rank in self.deck.cards() if rank not in deck.RULERS]
        for n in range(1, 13):
            self.assertEqual(numbers.count(str(n)), 3, n)

    def test_every_suit_half_and_half(self):
        for suit in self.deck.suits:
            fates = [deck.fate_of(suit, rank) for rank in self.deck.ranks[suit]]
            self.assertEqual(fates.count("fortune"), fates.count("doom"), suit)

    def test_the_rulers_are_worth_thirteen_and_fortune_rules(self):
        for suit in self.deck.suits:
            fortune, doom = sorted(deck.RULERS, key=lambda r: deck.fate_of(suit, r) == "doom")
            self.assertEqual(self.deck.worth(suit, fortune), 13, suit)
            self.assertEqual(self.deck.worth(suit, doom), 13, suit)
            self.assertGreater(self.deck.strength(suit, fortune), self.deck.strength(suit, doom), suit)
            self.assertGreater(self.deck.strength(suit, doom), self.deck.strength(suit, self.deck.ranks[suit][-3]), suit)

    def test_pieces_and_coins(self):
        value_of = {(metal, amount): value for metal, amount, value in deck.COIN_WORTH}
        for suit, rank in self.deck.cards():
            pieces = self.deck.pieces(suit, rank)
            if rank in deck.RULERS:  # the author: one big piece, like the anvil
                self.assertEqual(pieces, [12], (suit, rank))
            else:
                self.assertEqual(sum(pieces), self.deck.worth(suit, rank), (suit, rank))
            self.assertLessEqual(len(pieces), 4, (suit, rank))
        for rank in self.deck.ranks["money"]:
            coins = self.deck.money_coins(rank)
            if rank in deck.RULERS:  # the author: Money's rulers show the three-gold coin
                self.assertEqual(coins, [("gold", 3)])
            else:
                self.assertEqual(sum(value_of[c] for c in coins), int(rank), rank)

    def test_one_point_zero_is_unchanged(self):
        self.assertEqual(deck.TETHYS_1.cards(), [(suit, rank) for suit in deck.SUITS for rank in deck.RANKS])
        self.assertEqual(deck.TETHYS_1.money_coins("Left"), [("gold", 1)])


class Tethys2PokerTests(unittest.TestCase):
    poker = sets.POKER_2

    @classmethod
    def setUpClass(cls):
        cls.census = cls.poker.census()

    def test_the_census(self):
        self.assertEqual({k: (c.mixed, c.fortune, c.doom) for k, c in self.census.items()}, CENSUS_2)
        self.assertEqual(sum(c.total for c in self.census.values()), comb(48, 6))

    def test_by_formula(self):
        """Only six Lefts or six Rights make four or more of a kind; the numbers are three each."""
        self.assertEqual(self.census["six_of_a_kind"].total, 2)
        # Five of one side, and any card but the sixth of it.
        self.assertEqual(self.census["five_of_a_kind"].total, 2 * comb(6, 5) * 42)
        # Four of one side and any two of the 42 cards not of it.
        self.assertEqual(self.census["four_of_a_kind"].total, 2 * comb(6, 4) * comb(42, 2))
        # Three Lefts and three Rights; three of a side and a number's three; two numbers' threes.
        self.assertEqual(self.census["two_triples"].total, comb(6, 3) ** 2 + 2 * comb(6, 3) * 12 + comb(12, 2))
        # Per suit: runs of six numbers, of five then either ruler, of four then Left and Right.
        def runs(n, length):
            return max(0, n - length + 1)
        sizes = {"money": 12, "fiends": 6, "fools": 6, "tools": 4, "states": 4, "might": 4}
        flushes = sum(runs(n, 6) + 2 * runs(n, 5) + runs(n, 4) for n in sizes.values())
        self.assertEqual(self.census["straight_flush"].total, flushes)
        self.assertEqual(self.census["straight_flush"].total, 51)
        self.assertEqual(self.census["flush"].total, sum(comb(n + 2, 6) for n in sizes.values()) - 51)

    def test_the_sets_are_rarest_first_and_no_set_last(self):
        totals = [self.census[s.key].total for s in self.poker.sets[:-1]]
        self.assertEqual(totals, sorted(totals))
        self.assertEqual(self.poker.sets[-1].key, "no_set")

    def test_every_example_is_its_set_and_mixed(self):
        cards = set(self.poker.deck.cards())
        for s in self.poker.sets:
            self.assertEqual(len(set(s.example)), 6, s.key)
            self.assertTrue(set(s.example) <= cards, s.key)
            self.assertEqual(self.poker.set_of(s.example), s.key, s.key)
            self.assertFalse(self.poker.is_uniform(s.example), s.key)

    def test_a_left_and_a_right_pair_and_three_of_a_side_are_a_kind(self):
        """The author, 2026-10-11: "Left and right are pair. Left and left are
        not a pair. Rulers are 3/5/6 of a kind only if they are LLL or RRRR"."""
        numbers = (("fiends", "1"), ("tools", "3"), ("states", "6"), ("fools", "8"), ("money", "11"))

        def hand(*rulers):
            suits = ("money", "tools", "might", "fiends", "states", "fools")
            return tuple(zip(suits, rulers)) + numbers[:6 - len(rulers)]

        self.assertEqual(self.poker.set_of(hand("Left", "Right")), "one_pair")
        self.assertEqual(self.poker.set_of(hand("Left", "Left")), "no_set")
        self.assertEqual(self.poker.set_of(hand("Left", "Left", "Right")), "one_pair")
        self.assertEqual(self.poker.set_of(hand("Left", "Left", "Left")), "three_of_a_kind")
        self.assertEqual(self.poker.set_of(hand("Left", "Left", "Right", "Right")), "two_pairs")
        self.assertEqual(self.poker.set_of(hand("Right", "Right", "Right", "Right")), "four_of_a_kind")
        self.assertEqual(self.poker.set_of(hand("Left", "Left", "Left", "Left", "Right")), "four_of_a_kind")
        self.assertEqual(self.poker.set_of(hand("Left", "Left", "Left", "Right", "Right")), "three_of_a_kind")
        self.assertEqual(self.poker.set_of(hand("Left", "Left", "Left", "Right", "Right", "Right")), "two_triples")
        self.assertEqual(self.poker.set_of(hand(*["Right"] * 5)), "five_of_a_kind")
        self.assertEqual(self.poker.set_of(hand(*["Left"] * 6)), "six_of_a_kind")

    def test_a_straight_may_end_in_a_ruler_or_a_left_and_a_right(self):
        run = (("money", "2"), ("fiends", "3"), ("tools", "4"), ("fiends", "5"), ("states", "6"))
        self.assertEqual(self.poker.set_of(run + (("money", "7"),)), "straight")
        self.assertEqual(self.poker.set_of(run + (("might", "Left"),)), "straight")
        self.assertEqual(self.poker.set_of(run[:4] + (("might", "Left"), ("fools", "Right"))), "straight")
        self.assertEqual(self.poker.set_of(run[:4] + (("might", "Left"), ("fools", "Left"))), "no_set")  # two Lefts: no pair, no straight
        self.assertEqual(self.poker.set_of((("money", "Left"),) + run), "straight")  # the ruler ends it, wherever it is dealt
        self.assertEqual(self.poker.set_of((("money", "11"), ("fools", "12"), ("might", "Left"),
                                            ("tools", "1"), ("tools", "2"), ("fiends", "3"))), "no_set")  # no wrap


class CogAgreementTests(unittest.TestCase):
    """The bot deals the same decks by name: 2.0 new, 1.0 as saved."""

    def test_the_cog_names_the_same_cards(self):
        from cogs.tethysdeck_helpers import EDITION, SUITS, build_deck, parse_card

        self.assertEqual([name.lower() for _, name in SUITS], deck.SUITS)
        self.assertEqual(EDITION, "2.0")
        for name, edition in deck.EDITIONS.items():
            self.assertEqual([parse_card(card) for card in build_deck(name)], edition.cards(), name)


if __name__ == "__main__":
    unittest.main()
