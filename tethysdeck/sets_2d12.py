"""Tethys poker on the 2d12 deck: the classic deck's sets (`sets.py`),
counted again over values 2 to 24 (the author, 2026-10-27: "recount for
E").

The rules are the classic deck's with no rulers: a pair is two cards of
one value, a straight is six values in a row and never wraps from 24 to
2, a flush is six of one suit. All six cards count, and a hand is the
first set it makes in `SETS`. What the recount changes is the ranking:

- **Two cards can be the same card twice** (two of Money's 13s are
  Doom), and a suit can hold three of a value, so a flush may hold a pair
  or three of a kind. It is a flush whatever it holds -- it is rarer than
  all of them.
- **No suit holds six values in a row**, so there is no straight flush,
  and the set is not in the table.
- **The straight is commoner than two triples and rarer than three
  pairs and four of a kind**, and no set is the commonest hand of all.
  The order is the census's.

The deck is its own mirror (`deck_2d12`), so all Fortune and all Doom are
as likely as each other, as in the classic deck, and are counted together.
"""
from collections import Counter

from tethysdeck.deck_2d12 import Card, cards
from tethysdeck.sets import HAND_SIZE, Count, SixCardSet, by_shape, count_hands


def _c(suit: str, value: int, fate: str) -> Card:
    return Card(suit, value, fate)


F, D = "fortune", "doom"

# The ranking, rarest first and no set last: a hand is the first it makes.
SETS = (
    SixCardSet("six_of_a_kind", "Six of a kind", "Six of one value",
               (_c("money", 13, F), _c("money", 13, D), _c("tools", 13, F),
                _c("fiends", 13, D), _c("states", 13, F), _c("fools", 13, F))),
    SixCardSet("five_of_a_kind", "Five of a kind", "Five of one value",
               (_c("money", 12, F), _c("might", 12, F), _c("fiends", 12, F),
                _c("might", 12, D), _c("states", 12, D), _c("fools", 19, D))),
    SixCardSet("flush", "6-card flush", "Six of one suit, whatever else they make",
               (_c("fiends", 2, D), _c("fiends", 8, F), _c("fiends", 9, F),
                _c("fiends", 14, F), _c("fiends", 17, D), _c("fiends", 21, D))),
    SixCardSet("two_triples", "Two triples", "Three of one value, three of another",
               (_c("money", 8, F), _c("fiends", 8, F), _c("might", 8, D),
                _c("tools", 14, F), _c("fiends", 14, D), _c("fools", 14, D))),
    SixCardSet("straight", "6-card straight", "Six values in a row, any suits",
               (_c("money", 9, D), _c("states", 10, F), _c("might", 11, F),
                _c("fiends", 12, F), _c("tools", 13, F), _c("fools", 14, D))),
    SixCardSet("three_pairs", "Three pairs", "Three pairs at once",
               (_c("states", 7, F), _c("might", 7, D), _c("money", 15, D),
                _c("states", 15, F), _c("might", 16, F), _c("fools", 16, D))),
    SixCardSet("four_of_a_kind", "Four of a kind", "Four of one value",
               (_c("money", 5, F), _c("might", 11, F), _c("tools", 11, D),
                _c("might", 11, D), _c("fiends", 11, D), _c("fools", 20, F))),
    SixCardSet("three_of_a_kind", "Three of a kind", "Three of one value",
               (_c("tools", 4, F), _c("fiends", 9, F), _c("money", 18, D),
                _c("states", 18, F), _c("might", 18, D), _c("fools", 20, F))),
    SixCardSet("two_pairs", "Two pairs", "Two pairs at once",
               (_c("might", 3, F), _c("fools", 6, F), _c("money", 10, D),
                _c("states", 10, F), _c("tools", 17, F), _c("fiends", 17, D))),
    SixCardSet("one_pair", "One pair", "Two of one value",
               (_c("money", 5, F), _c("tools", 9, D), _c("states", 13, F),
                _c("might", 19, F), _c("fools", 19, D), _c("fiends", 21, D))),
    SixCardSet("no_set", "No set", "None of the above",
               (_c("fiends", 2, D), _c("states", 7, F), _c("fools", 14, F),
                _c("might", 22, D), _c("tools", 23, D), _c("money", 24, F))),
)
SET_BY_KEY = {s.key: s for s in SETS}


def _by_values(counts: Counter) -> str:
    """The best set a hand makes from its values alone, its suits aside."""
    values = sorted(counts)
    in_a_row = len(values) == HAND_SIZE and values[-1] - values[0] == HAND_SIZE - 1
    return by_shape(sorted(counts.values(), reverse=True), in_a_row)


def set_of(hand) -> str:
    """The best set six `Card`s make."""
    if len({c.suit for c in hand}) == 1:
        return "flush"
    return _by_values(Counter(c.value for c in hand))


def is_uniform(hand) -> bool:
    return len({c.fate for c in hand}) == 1


def census() -> dict[str, Count]:
    """Every hand of six from the 72, by its best set: mixed, and uniform."""
    return count_hands(cards(), lambda c: c.value, lambda c: c.fate, _by_values, set_of, SETS)
