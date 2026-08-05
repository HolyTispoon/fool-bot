"""
Small, generic pieces shared by the tethysdeck cog and its views: the
card set itself, and the text formatting used across the deck-status,
hand, and discard messages.
"""

import logging

import discord

from gamesaves.tethysdeck.storage import ChannelDeck


LOGGER = logging.getLogger(__name__)

# Suit names and symbols, vendored from the "Thetys Deck" tab of
# https://docs.google.com/spreadsheets/d/1OGvn3FSLqAN97zn5LMKe8KDDVaO5TbZiRIr6cbq46TE
# Fiends has no symbol filled in upstream yet; 〠 is what the rest of
# this codebase already used for it before the sheet existed.
SUITS = [
    ("$", "Money"),
    ("⚔", "Might"),
    ("〠", "Fiends"),
    ("⚒", "Tools"),
    ("☯", "States"),
    ("🃟", "Fools"),
]
RANKS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "Left", "Right"]

# Discord select menus top out at 25 options, and a hand can in theory
# hold every card in the deck.
MAX_SELECT_OPTIONS = 25


def build_deck() -> list[str]:
    return [
        f"{rank} of {symbol} {name}"
        for symbol, name in SUITS
        for rank in RANKS
    ]


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
) -> str:
    lines = []
    if header:
        lines.append(header)

    possessive = f"{user.display_name}'s"
    if hand:
        card_word = "card" if len(hand) == 1 else "cards"
        lines.append(
            f"{possessive} hand ({len(hand)} {card_word}): "
            f"{format_cards(hand)}"
        )
    else:
        lines.append(f"{possessive} hand is empty.")

    return "\n".join(lines)


def format_discard_text(discard: list[str]) -> str:
    if not discard:
        return "The discard pile is empty."
    card_word = "card" if len(discard) == 1 else "cards"
    return (
        f"Discard pile ({len(discard)} {card_word}): "
        f"{format_cards(discard)}"
    )


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
