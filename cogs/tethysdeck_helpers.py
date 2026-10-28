"""
Small, generic pieces shared by the tethysdeck cog and its views: the
card set itself, and the text formatting used across the deck-status,
hand, and discard messages.
"""

import logging

import discord

from gamesaves.tethysdeck.storage import ChannelDeck
from tethysdeck import deck


LOGGER = logging.getLogger(__name__)

# Suit names and symbols, vendored from the "Thetys Deck" tab of
# https://docs.google.com/spreadsheets/d/1OGvn3FSLqAN97zn5LMKe8KDDVaO5TbZiRIr6cbq46TE
# Fiends has no symbol filled in upstream yet; 〠 is what the rest of
# this codebase already used for it before the sheet existed.
SUITS = [  # the author's order (2026-10-09)
    ("$", "Money"),
    ("⚒", "Tools"),
    ("⚔", "Might"),
    ("〠", "Fiends"),
    ("☯", "States"),
    ("🃟", "Fools"),
]

# Discord select menus top out at 25 options, and a hand can in theory
# hold every card in the deck.
MAX_SELECT_OPTIONS = 25

SYMBOLS = {name.lower(): symbol for symbol, name in SUITS}


def build_deck() -> list[str]:
    return [card_name(card) for card in deck.cards()]


def card_name(card: deck.Card) -> str:
    """A card's name -- "13 of $ Money (Doom)". The fate is in it because
    a suit can hold one value under both; a card the deck holds twice is
    the same name twice."""
    return f"{card.value} of {SYMBOLS[card.suit]} {card.suit.title()} ({card.fate.title()})"


def parse_card(card: str) -> deck.Card | None:
    """A saved card's name as the card `tethysdeck` draws. The names are
    what a channel's deck saves, so they stay as `build_deck` writes them
    and are read here. A name with no fate -- "7 of ⚔ Might" -- is a card
    of the deck of 1 to 10, Left and Right that this one replaced
    (2026-10-28), from a channel that shuffled before then: None, and
    that channel's cards are named in words until it shuffles anew."""
    value, suit = card.split(" of ", 1)
    if not suit.endswith(")"):
        return None
    suit, fate = suit[:-1].rsplit(" (", 1)
    return deck.Card(suit.split()[-1].lower(), int(value), fate.lower())


def shuffled_before_replacement(state: ChannelDeck) -> bool:
    """Whether a channel's deck is the one this deck replaced: any of its
    cards will say, since a deck is shuffled whole."""
    for card in [*state.deck, *state.discard, *(c for hand in state.hands.values() for c in hand)]:
        return parse_card(card) is None
    return False


def remove_cards(hand: list[str], cards: list[str]) -> list[str]:
    """Take `cards` out of `hand`, one apiece -- a card held twice and
    chosen twice goes twice -- and return what was taken; a card the hand
    no longer holds is skipped."""
    taken = []
    for card in cards:
        if card in hand:
            hand.remove(card)
            taken.append(card)
    return taken


def format_cards(cards: list[str]) -> str:
    return ", ".join(cards) if cards else "none"


def deck_status_text(state: ChannelDeck) -> str:
    return (
        f"Current number of cards in the deck: {len(state.deck)}. "
        f"Current number of cards in the discard: {len(state.discard)}."
    )


def format_hand_text(
    user: discord.abc.User,
    hand: list[str],
    header: str | None = None,
    *,
    listed: bool = True,
) -> str:
    """The hand in words. With `listed` False the line is the caption over
    the hand's picture -- whose hand and how many -- and names no card:
    the picture shows them, so the words would say it twice."""
    lines = []
    if header:
        lines.append(header)

    possessive = f"{user.display_name}'s"
    if hand:
        card_word = "card" if len(hand) == 1 else "cards"
        count = f"{possessive} hand ({len(hand)} {card_word}):"
        lines.append(f"{count} {format_cards(hand)}" if listed else count)
    else:
        lines.append(f"{possessive} hand is empty.")

    return "\n".join(lines)


def format_discard_text(discard: list[str], *, listed: bool = True) -> str:
    """The discard pile in words, or with `listed` False the caption over
    its picture, which names no card."""
    if not discard:
        return "The discard pile is empty."
    card_word = "card" if len(discard) == 1 else "cards"
    count = f"Discard pile ({len(discard)} {card_word}):"
    return f"{count} {format_cards(discard)}" if listed else count


async def send_error_fallback(
    interaction: discord.Interaction,
    message: str,
) -> None:
    """
    Best-effort ephemeral notice for an interaction that failed with an
    unexpected exception, so a player sees something instead of their
    click or command silently doing nothing.
    """
    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except discord.HTTPException:
        pass
