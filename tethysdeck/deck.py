"""What the Tethys deck is: the suits, the ranks, which card is Fortune
and which Doom, and how a card's value is made of pieces.

The fate rule is the author's (2026-10-08), and the table in the "Thetys
Deck" tab of the World Building sheet is built from the same two inputs
per suit: the odd cards' fate, and which parity Left sits with. Right is
the other one. So every suit is six Fortune and six Doom.
"""

SUITS = ["money", "might", "fiends", "tools", "states", "fools"]  # the sheet's order
RANKS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "Left", "Right"]

ODD_FATE = {"money": "fortune", "might": "fortune", "states": "fortune",
            "tools": "doom", "fiends": "doom", "fools": "doom"}
LEFT_WITH = {"money": "odds", "tools": "odds", "might": "odds",
             "fiends": "evens", "states": "evens", "fools": "evens"}


def other(fate: str) -> str:
    return "doom" if fate == "fortune" else "fortune"


def fate_of(suit: str, rank: str) -> str:
    """Fortune or Doom, for one card."""
    odd, even = ODD_FATE[suit], other(ODD_FATE[suit])
    if rank == "Left":
        return odd if LEFT_WITH[suit] == "odds" else even
    if rank == "Right":
        return even if LEFT_WITH[suit] == "odds" else odd
    return odd if int(rank) % 2 else even


# A card's value: its number; a ruler is worth 12 when it is Fortune and 11
# when it is Doom (the author), so Money's Left is the 12 and its Right the 11.
RULER_WORTH = {"fortune": 12, "doom": 11}


def worth(suit: str, rank: str) -> int:
    if rank in ("Left", "Right"):
        return RULER_WORTH[fate_of(suit, rank)]
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


# Might's denominations are four instruments of power, Tools' four tools,
# the heavier the worthier, and Fools' four things a fool carries; every
# other suit is its one symbol at four sizes.
VARIANTS = {
    "might": {1: "sword", 3: "axe", 6: "sceptre", 12: "crown"},
    "tools": {1: "hammer", 3: "pick", 6: "spade", 12: "anvil"},
    "fools": {1: "cap", 3: "marotte", 6: "tambourine", 12: "mask"},
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
