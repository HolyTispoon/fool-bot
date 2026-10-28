"""What the Tethys deck is: the suits, the values, which card is Fortune
and which Doom, and how a card's value is made of pieces.

The deck is **structure E** of the author's "2d12 Distribution Card Deck"
document (2026-10-27), which replaced the deck of 1 to 10, Left and Right
on 2026-10-28: 72 cards whose values 2 to 24 come as often as two d12 roll
them, with a tall peak -- 13 eight times, its shoulders six, the tails one
card each -- in six suits of twelve, each suit worth 156. The document
numbers its suits 1 to 6; they are dealt to the suits in the author's
order (Money first).

**The fates** (the author, 2026-10-27: six and six, each half worth the
same; the split below kept, 2026-10-28): every suit is six Fortune and six
Doom, each half worth 78. A suit has 16 to 32 such splits, so three more
rules pick one:

- **The deck is its own mirror.** Fortune at a value is as many as Doom
  at the value across 13 from it (`FORTUNE[v] == DOOM[26 - v]` over the
  deck), so an all-Fortune hand is exactly as likely as the same set all
  Doom. 2,634 combinations of the suits' splits keep it.
- **A suit's repeated values are split between the fates where they can
  be**, so that as few cards as possible are the same card twice: 46 of
  those 2,634 leave only four such pairs (Money's three 13s must share a
  fate twice over, and so on).
- **Each half spread like the other**: of the 46, the two -- one the
  other's mirror -- whose halves' sums of squares are closest, suit by
  suit. Of that pair, the one whose Money 24 is Fortune.

The search was run once and is not kept: the tables below are its answer,
and `tests/test_tethys_deck.py` holds them to the document's suits and to
the first two rules.
"""
from typing import NamedTuple

SUITS = ["money", "tools", "might", "fiends", "states", "fools"]  # the author's order (2026-10-09)

# Structure E's card count per value, as the document gives it.
COUNTS = {2: 1, 3: 1, 4: 1, 5: 1, 6: 2, 7: 3, 8: 4, 9: 4, 10: 4, 11: 5, 12: 6,
          13: 8, 14: 6, 15: 5, 16: 4, 17: 4, 18: 4, 19: 3, 20: 2, 21: 1, 22: 1, 23: 1, 24: 1}
VALUES = tuple(COUNTS)

# Each suit's twelve, split by fate (see the module's note for which split).
FORTUNE = {
    "money": (5, 8, 12, 13, 16, 24),
    "tools": (4, 13, 14, 15, 15, 17),
    "might": (3, 11, 12, 16, 17, 19),
    "fiends": (8, 9, 12, 14, 16, 19),
    "states": (7, 10, 13, 15, 15, 18),
    "fools": (6, 8, 13, 14, 17, 20),
}
DOOM = {
    "money": (9, 10, 13, 13, 15, 18),
    "tools": (9, 10, 11, 11, 14, 23),
    "might": (7, 8, 11, 12, 18, 22),
    "fiends": (2, 11, 13, 14, 17, 21),
    "states": (6, 9, 12, 13, 18, 20),
    "fools": (7, 10, 12, 14, 16, 19),
}
FATES = {"fortune": FORTUNE, "doom": DOOM}


class Card(NamedTuple):
    """One card. Two cards of a suit at one value and one fate are the same
    card twice -- the same face, the same name -- so this is the whole of it."""
    suit: str
    value: int
    fate: str


def suit_cards(suit: str) -> list[Card]:
    """A suit's twelve, by value, Fortune first at a value both fates hold."""
    return sorted((Card(suit, value, fate) for fate, table in FATES.items() for value in table[suit]),
                  key=lambda c: (c.value, c.fate != "fortune"))


def cards() -> list[Card]:
    """All 72, a suit at a time in the suits' order, repeats included."""
    return [card for suit in SUITS for card in suit_cards(suit)]


def faces() -> list[Card]:
    """Every different card once, in the deck's order: what there is to draw."""
    return list(dict.fromkeys(cards()))


# Every suit but Money makes a value of pieces worth 1, 3, 6 and 12, the
# way the coins do, with the fewest pieces, largest first.
DENOMINATIONS = (12, 6, 3, 1)


def pieces(card: Card) -> list[int]:
    left, out = card.value, []
    for value in DENOMINATIONS:
        while left >= value:
            out.append(value)
            left -= value
    return out


# Might's denominations are four instruments of power and Tools' four
# tools, the heavier the worthier; every other suit is its one symbol at
# four sizes. (Fools had a ladder for a day -- cap, marotte, tambourine,
# mask -- and the author reverted it.)
VARIANTS = {
    "might": {1: "sword", 3: "axe", 6: "sceptre", 12: "crown"},
    "tools": {1: "hammer", 3: "pick", 6: "spade", 12: "anvil"},
}

# Money's pieces are the studio's coins, worth their dinkies (the Coins
# tab of the World Building sheet): metal, how many, worth.
COIN_WORTH = (("gold", 3, 36), ("silver", 3, 18), ("gold", 1, 12),
              ("silver", 1, 6), ("bronze", 3, 3), ("bronze", 1, 1))


def money_coins(card: Card) -> list[tuple[str, int]]:
    """The fewest coins worth the card, as (metal, amount) pairs, largest first."""
    left, coins = card.value, []
    for metal, amount, value in COIN_WORTH:
        while left >= value:
            coins.append((metal, amount))
            left -= value
    return coins
