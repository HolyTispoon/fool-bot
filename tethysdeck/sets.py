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
"""
from collections import Counter
from dataclasses import dataclass
from itertools import combinations, combinations_with_replacement
from math import comb

from tethysdeck.deck import RANKS, SUITS, fate_of

HAND_SIZE = 6
# A rank by its place in RANKS: the numbers 0 to 9, Left 10 and Right 11.
RANK_INDEX = {rank: i for i, rank in enumerate(RANKS)}
LEFT, RIGHT = RANK_INDEX["Left"], RANK_INDEX["Right"]


def straight_rank(index: int) -> int:
    """Where a rank sits in a straight: Left and Right both follow 10."""
    return min(index, LEFT)


@dataclass(frozen=True)
class SixCardSet:
    key: str
    name: str
    rule: str
    # A mixed hand that makes the set, for the player aid: (suit, rank).
    example: tuple[tuple[str, str], ...]


# The ranking, rarest first and no set last: a hand is the first it makes.
SETS = (
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
)
SET_BY_KEY = {s.key: s for s in SETS}


def _in_a_row(counts: Counter) -> bool:
    """Six cards, six places in a row."""
    places = sorted({straight_rank(r) for r in counts})
    return sum(counts.values()) == len(places) == HAND_SIZE and places[-1] - places[0] == HAND_SIZE - 1


def _groups(counts: Counter) -> list[int]:
    """The hand's matched groups, largest first: a number's cards are one
    group, and each Left with a Right is a pair; a ruler left over is alone."""
    pairs = min(counts[LEFT], counts[RIGHT])
    groups = [n for r, n in counts.items() if r < LEFT and n]
    groups += [2] * pairs + [1] * (counts[LEFT] + counts[RIGHT] - 2 * pairs)
    return sorted(groups, reverse=True)


def _by_ranks(counts: Counter) -> str:
    """The best set a hand makes from its ranks alone, its suits aside."""
    return by_shape(_groups(counts), _in_a_row(counts))


def by_shape(groups: list[int], in_a_row: bool) -> str:
    """The best set a hand's matched groups (largest first) make, or its
    six places in a row -- the ladder both decks read their ranks by."""
    if groups[0] >= 4:
        return {6: "six_of_a_kind", 5: "five_of_a_kind", 4: "four_of_a_kind"}[groups[0]]
    if groups[:2] == [3, 3]:
        return "two_triples"
    if in_a_row:
        return "straight"
    if groups == [2, 2, 2]:
        return "three_pairs"
    if groups[0] == 3:
        return "three_of_a_kind"
    if groups[:2] == [2, 2]:
        return "two_pairs"
    if groups[0] == 2:
        return "one_pair"
    return "no_set"


def set_of(hand) -> str:
    """The best set six (suit, rank) cards make. A hand of one suit holds
    at most one pair (its Left and Right), so a flush always outranks
    what its ranks make."""
    counts = Counter(RANK_INDEX[rank] for _, rank in hand)
    if len({suit for suit, _ in hand}) == 1:
        return "straight_flush" if _in_a_row(counts) else "flush"
    return _by_ranks(counts)


def is_uniform(hand) -> bool:
    return len({fate_of(suit, rank) for suit, rank in hand}) == 1


def _fortune_choices(fortune: int, doom: int, chosen: int) -> list[int]:
    """Ways to take `chosen` of a rank's cards, by how many are Fortune."""
    return [comb(fortune, k) * comb(doom, chosen - k) for k in range(chosen + 1)]


def _times(a: list[int], b: list[int]) -> list[int]:
    out = [0] * (len(a) + len(b) - 1)
    for i, x in enumerate(a):
        for j, y in enumerate(b):
            out[i + j] += x * y
    return out


@dataclass(frozen=True)
class Count:
    mixed: int
    uniform: int

    @property
    def total(self) -> int:
        return self.mixed + self.uniform


def census() -> dict[str, Count]:
    """Every hand of six, by its best set: mixed, and uniform."""
    return count_hands([(suit, rank) for suit in SUITS for rank in RANKS],
                       lambda c: RANK_INDEX[c[1]], lambda c: fate_of(*c), _by_ranks, set_of, SETS)


def count_hands(cards, rank_of, fate, by_ranks, of_one_suit, ranking) -> dict[str, Count]:
    """Every hand of six from `cards` -- each a tuple whose first item is its
    suit, a card held twice listed twice -- by its best set in `ranking`.
    `by_ranks` reads a Counter of `rank_of`s, `of_one_suit` a hand of one
    suit. A rank's cards differ only by fate as far as a set can tell, so
    the hands of one set of ranks are counted by multiplying, and only the
    hands of one suit are walked."""
    fortune, doom = Counter(), Counter()
    for c in cards:
        (fortune if fate(c) == "fortune" else doom)[rank_of(c)] += 1

    # Fortune count (0 to 6) -> hands, per set.
    by_fortune = {s.key: [0] * (HAND_SIZE + 1) for s in ranking}
    for ranks in combinations_with_replacement(sorted(set(fortune) | set(doom)), HAND_SIZE):
        counts = Counter(ranks)
        if any(n > fortune[r] + doom[r] for r, n in counts.items()):
            continue
        ways = [1]
        for r, n in counts.items():
            ways = _times(ways, _fortune_choices(fortune[r], doom[r], n))
        tally = by_fortune[by_ranks(counts)]
        for k, n in enumerate(ways):
            tally[k] += n

    # The flushes were counted above by their ranks; move them to their own.
    for suit in dict.fromkeys(c[0] for c in cards):
        for hand in combinations([c for c in cards if c[0] == suit], HAND_SIZE):
            k = sum(fate(c) == "fortune" for c in hand)
            by_fortune[by_ranks(Counter(rank_of(c) for c in hand))][k] -= 1
            by_fortune[of_one_suit(hand)][k] += 1

    return {key: Count(mixed=sum(t[1:HAND_SIZE]), uniform=t[0] + t[HAND_SIZE])
            for key, t in by_fortune.items()}


def total_hands() -> int:
    return comb(len(SUITS) * len(RANKS), HAND_SIZE)
