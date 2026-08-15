"""
The Tethys deck's card set -- six suits of twelve, seventy-two cards.

This is the deck itself and nothing about Discord, so both things that
deal it read it from here: `cogs/tethysdeck_helpers.py`, which shuffles
it into a channel, and `tethysdeck/cards.py`, which prints it. It used
to live in the cog's helpers, where a renderer could only have reached
it by importing discord.

**A card's `name` is what the bot stores in a saved deck**, so the
string is the deck's identity and not a label: a channel's deck, the
hands drawn from it and its discard pile are all lists of these. Change
how one is spelled and every deck saved in `data/tethysdeck_decks.json`
loses the cards its players are holding.

Suit names and symbols are vendored from the "Thetys Deck" tab of
https://docs.google.com/spreadsheets/d/1OGvn3FSLqAN97zn5LMKe8KDDVaO5TbZiRIr6cbq46TE
-- Fiends has no symbol filled in upstream yet, and U+3020 is what this
codebase used for it before the sheet existed. The printed card cannot
draw that one; see PRINT_SYMBOLS in `tethysdeck/cards.py`.
"""
from typing import NamedTuple


class Suit(NamedTuple):
    symbol: str
    name: str


class Card(NamedTuple):
    suit: Suit
    rank: str

    @property
    def name(self) -> str:
        """
        What the bot deals, holds and discards. See the module note:
        this string is stored in every saved deck.
        """
        return f"{self.rank} of {self.suit.symbol} {self.suit.name}"

    @property
    def is_number(self) -> bool:
        return self.rank.isdigit()


SUITS = [
    Suit("$", "Money"),
    Suit("⚔", "Might"),
    Suit("〠", "Fiends"),
    Suit("⚒", "Tools"),
    Suit("☯", "States"),
    Suit("🃟", "Fools"),
]

# Ten numbers and the two the deck is odd for. Left and Right are the
# court cards of this deck: they are the two ranks with no count to
# draw, which is the whole of why a printed card treats them apart.
RANKS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "Left", "Right"]


def build_cards() -> list[Card]:
    """Every card, suit by suit and in rank order."""
    return [Card(suit, rank) for suit in SUITS for rank in RANKS]


def build_deck() -> list[str]:
    """The deck as the bot stores it: one name per card, unshuffled."""
    return [card.name for card in build_cards()]
