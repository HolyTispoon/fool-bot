"""What the Tethys deck is: the suits, the ranks, which card is Fortune
and which Doom, and how a card's value is made of pieces.

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
