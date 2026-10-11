"""What the Tethys deck is: the suits, the ranks, which card is Fortune
and which Doom, and how a card's value is made of pieces -- in two
editions, side by side: 1.0, six suits of 1 to 10 and two rulers, and
2.0, where the suits share the numbers 1 to 12 out between them (`Deck`,
`TETHYS_1`, `TETHYS_2`). The module's own names (`SUITS`, `RANKS`,
`worth`, `pieces`, `money_coins`) are 1.0's, as they always were.

The fate rule is the author's (2026-10-08, the rulers freed 2026-10-09),
and the table in the "Thetys Deck" tab of the World Building sheet is built
from the same two inputs per suit: the odd cards' fate, and Left's fate.
The evens and Right are the other one. So every suit is six Fortune and
six Doom; Left is Fortune in three suits and Doom in three, and whether it
sits with the odds falls out (four suits) rather than being the rule.
"""

SUITS = ["money", "tools", "might", "fiends", "states", "fools"]  # the author's order (2026-10-09)
RANKS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "Left", "Right"]

ODD_FATE = {"money": "fortune", "might": "fortune", "states": "fortune",
            "tools": "doom", "fiends": "doom", "fools": "doom"}
LEFT_FATE = {"money": "fortune", "tools": "doom", "might": "doom",
             "fiends": "fortune", "states": "fortune", "fools": "doom"}  # three and three


def other(fate: str) -> str:
    return "doom" if fate == "fortune" else "fortune"


def fate_of(suit: str, rank: str) -> str:
    """Fortune or Doom, for one card."""
    if rank == "Left":
        return LEFT_FATE[suit]
    if rank == "Right":
        return other(LEFT_FATE[suit])
    return ODD_FATE[suit] if int(rank) % 2 else other(ODD_FATE[suit])


# A card's value: its number; the two rulers share the suit's power equally
# (the author, 2026-10-09), each worth 12, so each is one whole piece under
# its own fate -- Money's Left and Right are each one gold coin.
RULER_WORTH = 12


def worth(suit: str, rank: str) -> int:
    if rank in ("Left", "Right"):
        return RULER_WORTH
    return int(rank)


# Every suit but Money makes a value of pieces worth 1, 3, 6 and 12, the
# way the coins do, with the fewest pieces, largest first.
DENOMINATIONS = (12, 6, 3, 1)


def pieces(suit: str, rank: str) -> list[int]:
    left, out = worth(suit, rank), []
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


def money_coins(rank: str) -> list[tuple[str, int]]:
    """The fewest coins worth the card, as (metal, amount) pairs, largest first."""
    left, coins = worth("money", rank), []
    for metal, amount, value in COIN_WORTH:
        while left >= value:
            coins.append((metal, amount))
            left -= value
    return coins


# --- the two editions -------------------------------------------------------

RULERS = ("Left", "Right")


class Deck:
    """One edition of the deck: which ranks each suit holds, what a ruler is
    worth, and which coins Money's rulers show. Both editions keep the same
    six suits and the same fate rule (`fate_of`)."""

    def __init__(self, name: str, ranks: dict[str, list[str]], ruler_worth: int,
                 ruler_coins: list[tuple[str, int]] | None = None, fortune_ruler_first: bool = False):
        self.name = name
        self.suits = list(ranks)
        self.ranks = ranks
        self.ruler_worth = ruler_worth
        # Money's rulers as coins, where they are not the fewest coins worth the card.
        self.ruler_coins = ruler_coins
        # Whether a suit's Fortune ruler outranks its Doom ruler, the two being worth the same.
        self.fortune_ruler_first = fortune_ruler_first

    def cards(self) -> list[tuple[str, str]]:
        """Every card, a suit at a time in the author's order, numbers first."""
        return [(suit, rank) for suit in self.suits for rank in self.ranks[suit]]

    def columns(self) -> list[str]:
        """Every rank any suit holds, numbers then the rulers: a contact sheet's columns."""
        numbers = sorted({int(r) for ranks in self.ranks.values() for r in ranks if r not in RULERS})
        return [str(n) for n in numbers] + list(RULERS)

    def worth(self, suit: str, rank: str) -> int:
        return self.ruler_worth if rank in RULERS else int(rank)

    def strength(self, suit: str, rank: str) -> tuple[int, int]:
        """How a card ranks: its worth, and between the two rulers of a suit,
        the Fortune one above the Doom one where the edition says so."""
        tie = rank in RULERS and self.fortune_ruler_first and fate_of(suit, rank) == "fortune"
        return self.worth(suit, rank), int(tie)

    def pieces(self, suit: str, rank: str) -> list[int]:
        left, out = self.worth(suit, rank), []
        for value in DENOMINATIONS:
            while left >= value:
                out.append(value)
                left -= value
        return out

    def money_coins(self, rank: str) -> list[tuple[str, int]]:
        if rank in RULERS and self.ruler_coins is not None:
            return list(self.ruler_coins)
        left, coins = self.worth("money", rank), []
        for metal, amount, value in COIN_WORTH:
            while left >= value:
                coins.append((metal, amount))
                left -= value
        return coins


def _numbers(low: int, high: int) -> list[str]:
    return [str(n) for n in range(low, high + 1)] + list(RULERS)


TETHYS_1 = Deck("1.0", {suit: RANKS for suit in SUITS}, RULER_WORTH)

# 2.0 (the author, 2026-10-11): Money is 1 to 12 alone; Fiends 1 to 6 and
# Fools 7 to 12 share the numbers; Tools 1 to 4, States 5 to 8 and Might 9 to
# 12 share them again. Every suit keeps its two rulers, each worth 13, the
# suit's Fortune ruler above its Doom ruler; Money's rulers show the three-gold
# coin. 48 cards, 24 Fortune and 24 Doom.
TETHYS_2 = Deck("2.0", {
    "money": _numbers(1, 12),
    "tools": _numbers(1, 4),
    "might": _numbers(9, 12),
    "fiends": _numbers(1, 6),
    "states": _numbers(5, 8),
    "fools": _numbers(7, 12),
}, ruler_worth=13, ruler_coins=[("gold", 3)], fortune_ruler_first=True)

EDITIONS = {deck.name: deck for deck in (TETHYS_1, TETHYS_2)}
