"""Tethys poker: the sets a hand of six makes from the Tethys deck, and how many hands
make each one, as poker reads a hand of five.

All six cards count. Left and Right sit after 10: either follows 10 in
a straight, which never wraps round to 1, and **they pair only with each
other** -- a Left and a Right are a pair, two Lefts or two Rights are not
(the author, 2026-10-09). So three rulers are never three of a kind, and
two Lefts and two Rights are two pairs. A hand is its best set, and
`SETS` is the ranking: rarest first, then no set. A three or four of a
kind that also holds a pair is the three or the four.

Beside the set, a hand is **uniform** when all six cards are Fortune, or
all six Doom, and mixed otherwise. The deck is its own mirror -- every
rank of the numbers is three and three, and Left's four Fortune are
Right's four Doom -- so all Fortune and all Doom are always as likely as
each other, and `census` counts them together.

`census` counts every hand exactly, rank by rank rather than one hand at
a time: the hands made of one set of ranks are a product of choices per
rank, whose Fortune counts multiply as polynomials, and the hands all of
one suit (the flushes) are the only ones that need their suits, so those
5,544 are walked one by one. Nothing here draws; `sets_aid.py` does.

**Tethys 2.0** (`POKER_2`, the author, 2026-10-11) has its own pairing
and its own straights, over its 48 cards: **the rulers are one rank** --
any two pair, whatever their suits, so six rulers are six of a kind, and
the numbers, three cards each, make no more than three. **A straight is
numbers in a row and may end in a ruler, or in a Left and a Right**
(1-2-3-4-Left-Right is Tools whole), never two Lefts. 2.0 is not its
own mirror -- a number is one Fortune and two Doom or the other way
round -- so all Fortune and all Doom are counted apart. The module's
own names (`SETS`, `set_of`, `census`, ...) are 1.0's, as they always
were.
"""
from collections import Counter
from dataclasses import dataclass
from itertools import combinations, combinations_with_replacement
from math import comb

from tethysdeck.deck import SUITS, TETHYS_1, TETHYS_2, Deck, fate_of

HAND_SIZE = 6


@dataclass(frozen=True)
class SixCardSet:
    key: str
    name: str
    rule: str
    # A mixed hand that makes the set, for the player aid: (suit, rank).
    example: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class Count:
    mixed: int
    fortune: int  # all six Fortune
    doom: int  # all six Doom

    @property
    def uniform(self) -> int:
        return self.fortune + self.doom

    @property
    def total(self) -> int:
        return self.mixed + self.uniform


def _fortune_choices(fortune: int, doom: int, chosen: int) -> list[int]:
    """Ways to take `chosen` of a rank's cards, by how many are Fortune."""
    return [comb(fortune, k) * comb(doom, chosen - k) for k in range(chosen + 1)]


def _times(a: list[int], b: list[int]) -> list[int]:
    out = [0] * (len(a) + len(b) - 1)
    for i, x in enumerate(a):
        for j, y in enumerate(b):
            out[i + j] += x * y
    return out


class Poker:
    """Tethys poker over one edition of the deck: what a hand's ranks make
    (`_groups`, `_in_a_row`, each edition's own), and the census. `sets` is
    the ranking, rarest first and no set last: a hand is the first it makes."""

    def __init__(self, deck: Deck, sets: tuple[SixCardSet, ...]):
        self.deck = deck
        self.sets = sets
        self.set_by_key = {s.key: s for s in sets}
        # A rank by its place among the deck's ranks: the numbers, then Left and Right.
        self.rank_index = {rank: i for i, rank in enumerate(deck.columns())}
        self.left, self.right = self.rank_index["Left"], self.rank_index["Right"]

    def _groups(self, counts: Counter) -> list[int]:
        raise NotImplementedError

    def _in_a_row(self, counts: Counter) -> bool:
        raise NotImplementedError

    def _makes(self, key: str, counts: Counter, one_suit: bool) -> bool:
        shape = self._groups(counts)
        return {
            "six_of_a_kind": lambda: shape[0] == 6,
            "five_of_a_kind": lambda: shape[0] == 5,
            "four_of_a_kind": lambda: shape[0] == 4,
            "two_triples": lambda: shape[:2] == [3, 3],
            "straight_flush": lambda: one_suit and self._in_a_row(counts),
            "flush": lambda: one_suit,
            "straight": lambda: self._in_a_row(counts),
            "three_pairs": lambda: shape == [2, 2, 2],
            "three_of_a_kind": lambda: shape[0] == 3,
            "two_pairs": lambda: shape[:2] == [2, 2],
            "one_pair": lambda: shape[0] == 2,
            "no_set": lambda: True,
        }[key]()

    def _best(self, counts: Counter, one_suit: bool) -> str:
        return next(s.key for s in self.sets if self._makes(s.key, counts, one_suit))

    def _by_ranks(self, counts: Counter) -> str:
        """The best set a hand makes from its ranks alone, its suits aside."""
        return self._best(counts, one_suit=False)

    def set_of(self, hand) -> str:
        """The best set six (suit, rank) cards make."""
        counts = Counter(self.rank_index[rank] for _, rank in hand)
        return self._best(counts, one_suit=len({suit for suit, _ in hand}) == 1)

    @staticmethod
    def is_uniform(hand) -> bool:
        return len({fate_of(suit, rank) for suit, rank in hand}) == 1

    def census(self) -> dict[str, Count]:
        """Every hand of six, by its best set: mixed, all Fortune and all Doom."""
        cards = self.deck.cards()
        fortune, doom = Counter(), Counter()
        for suit, rank in cards:
            (fortune if fate_of(suit, rank) == "fortune" else doom)[self.rank_index[rank]] += 1

        # Fortune count (0 to 6) -> hands, per set.
        by_fortune = {s.key: [0] * (HAND_SIZE + 1) for s in self.sets}
        for ranks in combinations_with_replacement(range(len(self.rank_index)), HAND_SIZE):
            counts = Counter(ranks)
            if any(n > fortune[r] + doom[r] for r, n in counts.items()):
                continue
            ways = [1]
            for r, n in counts.items():
                ways = _times(ways, _fortune_choices(fortune[r], doom[r], n))
            tally = by_fortune[self._by_ranks(counts)]
            for k, n in enumerate(ways):
                tally[k] += n

        # The flushes were counted above by their ranks; move them to their own.
        for suit in self.deck.suits:
            for hand in combinations([c for c in cards if c[0] == suit], HAND_SIZE):
                k = sum(fate_of(*c) == "fortune" for c in hand)
                by_fortune[self._by_ranks(Counter(self.rank_index[r] for _, r in hand))][k] -= 1
                by_fortune[self.set_of(hand)][k] += 1

        return {key: Count(mixed=sum(t[1:HAND_SIZE]), fortune=t[HAND_SIZE], doom=t[0])
                for key, t in by_fortune.items()}

    def total_hands(self) -> int:
        return comb(len(self.deck.cards()), HAND_SIZE)


class Poker1(Poker):
    """1.0: Left and Right both follow 10, and pair only with each other."""

    def straight_rank(self, index: int) -> int:
        """Where a rank sits in a straight: Left and Right both follow 10."""
        return min(index, self.left)

    def _in_a_row(self, counts: Counter) -> bool:
        """Six cards, six places in a row."""
        places = sorted({self.straight_rank(r) for r in counts})
        return sum(counts.values()) == len(places) == HAND_SIZE and places[-1] - places[0] == HAND_SIZE - 1

    def _groups(self, counts: Counter) -> list[int]:
        """The hand's matched groups, largest first: a number's cards are one
        group, and each Left with a Right is a pair; a ruler left over is alone."""
        pairs = min(counts[self.left], counts[self.right])
        groups = [n for r, n in counts.items() if r < self.left and n]
        groups += [2] * pairs + [1] * (counts[self.left] + counts[self.right] - 2 * pairs)
        return sorted(groups, reverse=True)


class Poker2(Poker):
    """2.0: the rulers are one rank, and a straight of numbers may end in a
    ruler, or in a Left and a Right."""

    def _in_a_row(self, counts: Counter) -> bool:
        lefts, rights = counts[self.left], counts[self.right]
        if lefts > 1 or rights > 1:
            return False
        numbers = sorted(r for r in counts if r < self.left)
        return (sum(counts.values()) == HAND_SIZE
                and all(counts[r] == 1 for r in numbers)
                and len(numbers) == HAND_SIZE - lefts - rights
                and numbers[-1] - numbers[0] == len(numbers) - 1)

    def _groups(self, counts: Counter) -> list[int]:
        """The hand's matched groups, largest first: a number's cards are one
        group, and every ruler in the hand is one more."""
        groups = [n for r, n in counts.items() if r < self.left and n]
        rulers = counts[self.left] + counts[self.right]
        return sorted(groups + ([rulers] if rulers else []), reverse=True)


# The ranking, rarest first and no set last: a hand is the first it makes.
POKER_1 = Poker1(TETHYS_1, (
    SixCardSet("six_of_a_kind", "Six of a kind", "Six of one number",
               tuple((suit, "7") for suit in SUITS)),
    SixCardSet("straight_flush", "6-card straight flush", "Six in a row, all one suit",
               (("might", "5"), ("might", "6"), ("might", "7"), ("might", "8"), ("might", "9"), ("might", "10"))),
    SixCardSet("five_of_a_kind", "Five of a kind", "Five of one number",
               (("money", "4"), ("might", "4"), ("fiends", "4"), ("tools", "4"), ("states", "4"), ("fools", "9"))),
    SixCardSet("flush", "6-card flush", "Six of one suit",
               (("states", "1"), ("states", "3"), ("states", "4"), ("states", "7"), ("states", "9"), ("states", "Left"))),
    SixCardSet("two_triples", "Two triples", "Three of one number, three of another",
               (("money", "8"), ("tools", "8"), ("fiends", "8"), ("might", "2"), ("states", "2"), ("fools", "2"))),
    SixCardSet("four_of_a_kind", "Four of a kind", "Four of one number",
               (("money", "10"), ("tools", "10"), ("might", "10"), ("fools", "10"), ("fiends", "2"), ("states", "6"))),
    SixCardSet("straight", "6-card straight", "Six in a row, any suits",
               (("money", "3"), ("money", "4"), ("fiends", "5"), ("states", "6"), ("fools", "7"), ("might", "8"))),
    SixCardSet("three_pairs", "Three pairs", "Three pairs at once",
               (("money", "4"), ("tools", "4"), ("might", "9"), ("states", "9"), ("fiends", "Left"), ("fools", "Right"))),
    SixCardSet("three_of_a_kind", "Three of a kind", "Three of one number",
               (("might", "5"), ("fiends", "5"), ("states", "5"), ("tools", "1"), ("money", "7"), ("fools", "Left"))),
    SixCardSet("two_pairs", "Two pairs", "Two pairs at once",
               (("money", "9"), ("fiends", "9"), ("tools", "3"), ("states", "3"), ("might", "6"), ("fools", "Right"))),
    SixCardSet("one_pair", "One pair", "Two of one number, or a Left and a Right",
               (("money", "5"), ("tools", "5"), ("might", "1"), ("fiends", "3"), ("states", "8"), ("fools", "Left"))),
    SixCardSet("no_set", "No set", "None of the above",
               (("money", "1"), ("might", "3"), ("fiends", "6"), ("tools", "8"), ("states", "10"), ("fools", "Right"))),
))

# 2.0's ranking is its own census's, rarest first: the rulers' kinds climb
# it, and two pairs is rarer than three of a kind.
POKER_2 = Poker2(TETHYS_2, (
    SixCardSet("straight_flush", "6-card straight flush", "Six in a row, all one suit",
               (("tools", "1"), ("tools", "2"), ("tools", "3"), ("tools", "4"), ("tools", "Left"), ("tools", "Right"))),
    SixCardSet("six_of_a_kind", "Six of a kind", "Six rulers",
               (("money", "Left"), ("money", "Right"), ("tools", "Left"), ("fiends", "Right"), ("states", "Left"), ("fools", "Right"))),
    SixCardSet("two_triples", "Two triples", "Three of one rank, three of another",
               (("money", "5"), ("fiends", "5"), ("states", "5"), ("money", "9"), ("fools", "9"), ("might", "9"))),
    SixCardSet("flush", "6-card flush", "Six of one suit",
               (("money", "2"), ("money", "5"), ("money", "7"), ("money", "10"), ("money", "11"), ("money", "Right"))),
    SixCardSet("five_of_a_kind", "Five of a kind", "Five rulers",
               (("money", "Left"), ("might", "Right"), ("fiends", "Left"), ("tools", "Right"), ("fools", "Left"), ("states", "6"))),
    SixCardSet("three_pairs", "Three pairs", "Three pairs at once",
               (("money", "3"), ("tools", "3"), ("states", "8"), ("fools", "8"), ("might", "Left"), ("fiends", "Right"))),
    SixCardSet("straight", "6-card straight", "Six in a row, any suits",
               (("fools", "7"), ("states", "8"), ("might", "9"), ("money", "10"), ("fiends", "Left"), ("might", "Right"))),
    SixCardSet("four_of_a_kind", "Four of a kind", "Four rulers",
               (("money", "Right"), ("states", "Left"), ("might", "Left"), ("fools", "Right"), ("money", "4"), ("tools", "2"))),
    SixCardSet("two_pairs", "Two pairs", "Two pairs at once",
               (("money", "6"), ("states", "6"), ("fools", "11"), ("might", "11"), ("fiends", "2"), ("tools", "3"))),
    SixCardSet("three_of_a_kind", "Three of a kind", "Three of one number, or three rulers",
               (("money", "10"), ("might", "10"), ("fools", "10"), ("fiends", "1"), ("states", "5"), ("tools", "Left"))),
    SixCardSet("one_pair", "One pair", "Two of one number, or two rulers",
               (("money", "Left"), ("fools", "Left"), ("fiends", "2"), ("states", "7"), ("might", "11"), ("tools", "4"))),
    SixCardSet("no_set", "No set", "None of the above",
               (("money", "1"), ("tools", "3"), ("states", "6"), ("fools", "8"), ("might", "12"), ("fiends", "Right"))),
))
EDITIONS = {poker.deck.name: poker for poker in (POKER_1, POKER_2)}

# 1.0, under the names it always had.
SETS = POKER_1.sets
SET_BY_KEY = POKER_1.set_by_key
RANK_INDEX = POKER_1.rank_index
LEFT, RIGHT = POKER_1.left, POKER_1.right
straight_rank = POKER_1.straight_rank
set_of = POKER_1.set_of
is_uniform = Poker.is_uniform
census = POKER_1.census
total_hands = POKER_1.total_hands
