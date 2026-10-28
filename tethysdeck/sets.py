"""Tethys poker: the sets a hand of six makes from the Tethys deck, and how
many hands make each one, as poker reads a hand of five.

All six cards count. A pair is two cards of one value, a straight six
values in a row that never wraps from 24 to 2, a flush six of one suit.
A hand is its best set, and `SETS` is the ranking: rarest first, then no
set, though no set is the commonest hand of all. A three or four of a
kind that also holds a pair is the three or the four.

The sets are the ones the deck of 1 to 10, Left and Right had (the
author, 2026-10-09), recounted when this deck replaced it (2026-10-27,
"recount for E"), and the recount changed the ranking:

- **Two cards can be the same card twice** (two of Money's 13s are
  Doom), and a suit can hold three of a value, so a flush may hold a pair
  or three of a kind. It is a flush whatever it holds -- it is rarer than
  all of them.
- **No suit holds six values in a row**, so there is no straight flush,
  and the set is not in the table.
- **The straight is commoner than two triples and rarer than three
  pairs and four of a kind.** The order is the census's.

Beside the set, a hand is **uniform** when all six cards are Fortune, or
all six Doom, and mixed otherwise. The deck is its own mirror (`deck.py`),
so all Fortune and all Doom are always as likely as each other, and
`census` counts them together.

`census` counts every hand exactly, value by value rather than one hand
at a time: the hands made of one set of values are a product of choices
per value, whose Fortune counts multiply as polynomials, and the hands all
of one suit (the flushes) are the only ones that need their suits, so
those 5,544 are walked one by one. Nothing here draws; `sets_aid.py` does.
"""
from collections import Counter
from dataclasses import dataclass
from itertools import combinations, combinations_with_replacement
from math import comb

from tethysdeck.deck import Card, cards

HAND_SIZE = 6
F, D = "fortune", "doom"


@dataclass(frozen=True)
class SixCardSet:
    key: str
    name: str
    rule: str
    # A mixed hand that makes the set, for the player aid.
    example: tuple[Card, ...]


# The ranking, rarest first and no set last: a hand is the first it makes.
SETS = (
    SixCardSet("six_of_a_kind", "Six of a kind", "Six of one value",
               (Card("money", 13, F), Card("money", 13, D), Card("tools", 13, F),
                Card("fiends", 13, D), Card("states", 13, F), Card("fools", 13, F))),
    SixCardSet("five_of_a_kind", "Five of a kind", "Five of one value",
               (Card("money", 12, F), Card("might", 12, F), Card("fiends", 12, F),
                Card("might", 12, D), Card("states", 12, D), Card("fools", 19, D))),
    SixCardSet("flush", "6-card flush", "Six of one suit, whatever else they make",
               (Card("fiends", 2, D), Card("fiends", 8, F), Card("fiends", 9, F),
                Card("fiends", 14, F), Card("fiends", 17, D), Card("fiends", 21, D))),
    SixCardSet("two_triples", "Two triples", "Three of one value, three of another",
               (Card("money", 8, F), Card("fiends", 8, F), Card("might", 8, D),
                Card("tools", 14, F), Card("fiends", 14, D), Card("fools", 14, D))),
    SixCardSet("straight", "6-card straight", "Six values in a row, any suits",
               (Card("money", 9, D), Card("states", 10, F), Card("might", 11, F),
                Card("fiends", 12, F), Card("tools", 13, F), Card("fools", 14, D))),
    SixCardSet("three_pairs", "Three pairs", "Three pairs at once",
               (Card("states", 7, F), Card("might", 7, D), Card("money", 15, D),
                Card("states", 15, F), Card("might", 16, F), Card("fools", 16, D))),
    SixCardSet("four_of_a_kind", "Four of a kind", "Four of one value",
               (Card("money", 5, F), Card("might", 11, F), Card("tools", 11, D),
                Card("might", 11, D), Card("fiends", 11, D), Card("fools", 20, F))),
    SixCardSet("three_of_a_kind", "Three of a kind", "Three of one value",
               (Card("tools", 4, F), Card("fiends", 9, F), Card("money", 18, D),
                Card("states", 18, F), Card("might", 18, D), Card("fools", 20, F))),
    SixCardSet("two_pairs", "Two pairs", "Two pairs at once",
               (Card("might", 3, F), Card("fools", 6, F), Card("money", 10, D),
                Card("states", 10, F), Card("tools", 17, F), Card("fiends", 17, D))),
    SixCardSet("one_pair", "One pair", "Two of one value",
               (Card("money", 5, F), Card("tools", 9, D), Card("states", 13, F),
                Card("might", 19, F), Card("fools", 19, D), Card("fiends", 21, D))),
    SixCardSet("no_set", "No set", "None of the above",
               (Card("fiends", 2, D), Card("states", 7, F), Card("fools", 14, F),
                Card("might", 22, D), Card("tools", 23, D), Card("money", 24, F))),
)
SET_BY_KEY = {s.key: s for s in SETS}


def _by_values(counts: Counter) -> str:
    """The best set a hand makes from its values alone, its suits aside."""
    groups = sorted(counts.values(), reverse=True)
    values = sorted(counts)
    in_a_row = len(values) == HAND_SIZE and values[-1] - values[0] == HAND_SIZE - 1
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
    """The best set six `Card`s make. A flush outranks whatever its values
    make, since no suit holds four of a value or six in a row."""
    if len({c.suit for c in hand}) == 1:
        return "flush"
    return _by_values(Counter(c.value for c in hand))


def is_uniform(hand) -> bool:
    return len({c.fate for c in hand}) == 1


def _fortune_choices(fortune: int, doom: int, chosen: int) -> list[int]:
    """Ways to take `chosen` of a value's cards, by how many are Fortune."""
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
    """Every hand of six from the 72, by its best set: mixed, and uniform."""
    deck = cards()
    fortune, doom = Counter(), Counter()
    for c in deck:
        (fortune if c.fate == F else doom)[c.value] += 1

    # Fortune count (0 to 6) -> hands, per set.
    by_fortune = {s.key: [0] * (HAND_SIZE + 1) for s in SETS}
    for values in combinations_with_replacement(sorted(set(fortune) | set(doom)), HAND_SIZE):
        counts = Counter(values)
        if any(n > fortune[v] + doom[v] for v, n in counts.items()):
            continue
        ways = [1]
        for v, n in counts.items():
            ways = _times(ways, _fortune_choices(fortune[v], doom[v], n))
        tally = by_fortune[_by_values(counts)]
        for k, n in enumerate(ways):
            tally[k] += n

    # The flushes were counted above by their values; move them to their own.
    for suit in dict.fromkeys(c.suit for c in deck):
        for hand in combinations([c for c in deck if c.suit == suit], HAND_SIZE):
            k = sum(c.fate == F for c in hand)
            by_fortune[_by_values(Counter(c.value for c in hand))][k] -= 1
            by_fortune[set_of(hand)][k] += 1

    return {key: Count(mixed=sum(t[1:HAND_SIZE]), uniform=t[0] + t[HAND_SIZE])
            for key, t in by_fortune.items()}


def total_hands() -> int:
    return comb(len(cards()), HAND_SIZE)
