"""The sets a hand of six makes from the Tethys deck, and how many hands
make each one, as poker reads a hand of five.

All six cards count. Left and Right are one rank, the one after 10: they
pair with each other and either follows 10 in a straight, which never
wraps round to 1 (the author, 2026-10-09). A hand is its best set, the
rarest it makes, and `SETS` is that order. A pair alone is no set, and
a three or four of a kind that also holds a pair is the three or the four.

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
RULERS = ("Left", "Right")
# A rank as sets count it: the numbers 0 to 9, and Left and Right both 10.
SET_RANKS = 11


def set_rank(rank: str) -> int:
    return SET_RANKS - 1 if rank in RULERS else int(rank) - 1


@dataclass(frozen=True)
class SixCardSet:
    key: str
    name: str
    rule: str
    # A mixed hand that makes the set, for the player aid: (suit, rank).
    example: tuple[tuple[str, str], ...]


# Rarest first, which is the ranking: a hand is the first set it makes.
SETS = (
    SixCardSet("straight_flush", "6-card straight flush", "Six in a row, all one suit",
               (("might", "5"), ("might", "6"), ("might", "7"), ("might", "8"), ("might", "9"), ("might", "10"))),
    SixCardSet("six_of_a_kind", "Six of a kind", "Six of one rank",
               tuple((suit, "7") for suit in SUITS)),
    SixCardSet("flush", "6-card flush", "Six of one suit",
               (("states", "1"), ("states", "3"), ("states", "4"), ("states", "7"), ("states", "9"), ("states", "Left"))),
    SixCardSet("five_of_a_kind", "Five of a kind", "Five of one rank",
               (("money", "4"), ("might", "4"), ("fiends", "4"), ("tools", "4"), ("states", "4"), ("fools", "9"))),
    SixCardSet("two_triples", "Two triples", "Three of one rank, three of another",
               (("money", "8"), ("tools", "8"), ("fiends", "8"), ("might", "2"), ("states", "2"), ("fools", "2"))),
    SixCardSet("straight", "6-card straight", "Six in a row, any suits",
               (("money", "3"), ("money", "4"), ("fiends", "5"), ("states", "6"), ("fools", "7"), ("might", "8"))),
    SixCardSet("three_pairs", "Three pairs", "Three ranks, two of each",
               (("money", "4"), ("tools", "4"), ("might", "9"), ("states", "9"), ("fiends", "Left"), ("fools", "Right"))),
    SixCardSet("four_of_a_kind", "Four of a kind", "Four of one rank",
               (("money", "10"), ("tools", "10"), ("might", "10"), ("fools", "10"), ("fiends", "2"), ("states", "6"))),
    SixCardSet("three_of_a_kind", "Three of a kind", "Three of one rank",
               (("might", "5"), ("fiends", "5"), ("states", "5"), ("tools", "1"), ("money", "7"), ("fools", "Left"))),
    SixCardSet("two_pairs", "Two pairs", "Two of one rank, two of another",
               (("money", "9"), ("fiends", "9"), ("tools", "3"), ("states", "3"), ("might", "6"), ("fools", "Right"))),
    SixCardSet("no_set", "No set", "None of the above",
               (("money", "1"), ("might", "3"), ("fiends", "6"), ("tools", "8"), ("states", "10"), ("fools", "Right"))),
)
SET_BY_KEY = {s.key: s for s in SETS}


def _in_a_row(counts: Counter) -> bool:
    """Six different ranks, one after another."""
    ranks = sorted(counts)
    return len(ranks) == HAND_SIZE and ranks[-1] - ranks[0] == HAND_SIZE - 1


def _by_ranks(counts: Counter) -> str:
    """The best set a hand makes from its ranks alone, its suits aside."""
    shape = sorted(counts.values(), reverse=True)
    if shape[0] >= 4:
        return {6: "six_of_a_kind", 5: "five_of_a_kind", 4: "four_of_a_kind"}[shape[0]]
    if shape[:2] == [3, 3]:
        return "two_triples"
    if _in_a_row(counts):
        return "straight"
    if shape == [2, 2, 2]:
        return "three_pairs"
    if shape[0] == 3:
        return "three_of_a_kind"
    if shape[:2] == [2, 2]:
        return "two_pairs"
    return "no_set"


def set_of(hand) -> str:
    """The best set six (suit, rank) cards make. A hand of one suit holds
    at most one pair (its Left and Right), so a flush always outranks
    what its ranks make."""
    counts = Counter(set_rank(rank) for _, rank in hand)
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
    cards = [(suit, rank) for suit in SUITS for rank in RANKS]
    fortune, doom = Counter(), Counter()
    for suit, rank in cards:
        (fortune if fate_of(suit, rank) == "fortune" else doom)[set_rank(rank)] += 1

    # Fortune count (0 to 6) -> hands, per set.
    by_fortune = {s.key: [0] * (HAND_SIZE + 1) for s in SETS}
    for ranks in combinations_with_replacement(range(SET_RANKS), HAND_SIZE):
        counts = Counter(ranks)
        if any(n > fortune[r] + doom[r] for r, n in counts.items()):
            continue
        ways = [1]
        for r, n in counts.items():
            ways = _times(ways, _fortune_choices(fortune[r], doom[r], n))
        tally = by_fortune[_by_ranks(counts)]
        for k, n in enumerate(ways):
            tally[k] += n

    # The flushes were counted above by their ranks; move them to their own.
    for suit in SUITS:
        for hand in combinations([c for c in cards if c[0] == suit], HAND_SIZE):
            k = sum(fate_of(*c) == "fortune" for c in hand)
            by_fortune[_by_ranks(Counter(set_rank(r) for _, r in hand))][k] -= 1
            by_fortune[set_of(hand)][k] += 1

    return {key: Count(mixed=sum(t[1:HAND_SIZE]), uniform=t[0] + t[HAND_SIZE])
            for key, t in by_fortune.items()}


def total_hands() -> int:
    return comb(len(SUITS) * len(RANKS), HAND_SIZE)
