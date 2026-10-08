"""
Plain-text formatting over the cards, with nothing that touches Discord.
"""

from __future__ import annotations

from codex import tokens
from codex.cards import Card, Hero, catalog

#: How a token reads where nothing draws it.
PLAIN_WORDS = {
    "exhaust": "[exhaust]",
    "target": "[target]",
    "arrow": "->",
    "codex": "",
}


def plain_token(kind: str, arguments: tuple[str, ...]) -> str:
    if kind == "gold":
        return f"({arguments[0]})"
    if kind == "player":
        return f"Player {arguments[0]}"
    if kind in ("card", "hero"):
        try:
            return catalog().name(arguments[0])
        except KeyError:
            return arguments[0]
    return PLAIN_WORDS[kind]


def plain_text(text: str) -> str:
    """A line of card text with its tokens as words: `{gold:2}` is
    "(2)", `{exhaust}` "[exhaust]"."""
    return tokens.render(text, plain_token)


def card_label(card: Card | Hero) -> str:
    """
    A card the way a list names it: "Trojan Duck (7) 8/9" -- the cost
    in brackets, a unit's ATK/HP after it; a spell "Spark (1)"; a hero
    "Troq Bashar (2) 2/3" at its first band.
    """
    if isinstance(card, Hero):
        band = card.bands[0]
        return f"{card.name} ({card.cost}) {band.atk}/{band.hp}"
    label = card.name if card.cost is None else f"{card.name} ({card.cost})"
    if card.atk is not None and card.hp is not None:
        return f"{label} {card.atk}/{card.hp}"
    return label
