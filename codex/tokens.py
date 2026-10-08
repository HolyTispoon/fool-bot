"""
The marks a card's text and the bot's sentences leave for a frontend to
draw.

Codex's cards print a few things as glyphs rather than words -- the
exhaust arrow, the target ring, a gold cost in a circle, the arrow
between an ability's cost and its effect -- and the bot's own mark opens
its lobby and its turn message. The model writes each as a token,
`{exhaust}`, `{target}`, `{gold:2}`, `{arrow}`, `{codex}`, and its
narration names a seat, a card and a hero the same way --
`{player:1}`, `{card:iron_man}`, `{hero:troq_bashar}` -- so nothing in
the model holds a name a frontend would draw differently. A
frontend renders every one once, at its door: an application emoji on
Discord (`cogs.codex_helpers.CodexTokens`), a word in plain text
(`codex.formatting.plain_text`). The shape is D12 Ball's
(`d12ball/tokens.py`, and docs/design/model-discord-split.md, "Tokens");
the kinds are Codex's own. `scripts/import_codex_cards.py` writes the
card texts' tokens.
"""

import re
from typing import Callable, Optional

#: The kinds a token may be. `gold` takes the amount, `player` the seat,
#: `card` and `hero` the slug.
KINDS = ("exhaust", "target", "gold", "arrow", "codex", "player", "card", "hero")

TOKEN_PATTERN = re.compile(r"\{(" + "|".join(KINDS) + r")((?::[a-z0-9_]+)*)\}")

#: What a frontend renders a token with: the kind and its arguments in,
#: the text out -- or `None` to leave the token as it stands.
Resolver = Callable[[str, tuple[str, ...]], Optional[str]]


def exhaust() -> str:
    return "{exhaust}"


def target() -> str:
    return "{target}"


def gold(amount: int) -> str:
    if amount < 0:
        raise ValueError(f"not an amount of gold: {amount!r}")
    return f"{{gold:{amount}}}"


def arrow() -> str:
    return "{arrow}"


def codex() -> str:
    """The bot's own mark, the medallion off the back of every card."""
    return "{codex}"


def player(seat: int) -> str:
    """A seat, 1 or 2 -- whoever sits there, as the frontend names them."""
    if seat not in (1, 2):
        raise ValueError(f"not a seat: {seat!r}")
    return f"{{player:{seat}}}"


def card(slug: str) -> str:
    """A card by its slug; the frontend asks the catalog for the name."""
    return f"{{card:{slug}}}"


def hero(slug: str) -> str:
    """A hero by its slug."""
    return f"{{hero:{slug}}}"


def _arguments(found: re.Match) -> tuple[str, ...]:
    return tuple(found.group(2).split(":")[1:])


def render(text: str, resolve: Resolver) -> str:
    """
    Every token in `text`, replaced by what `resolve` says it shows as.
    A token the resolver answers `None` for is left in place.
    """
    def substitute(found: re.Match) -> str:
        rendered = resolve(found.group(1), _arguments(found))
        return found.group(0) if rendered is None else rendered

    return TOKEN_PATTERN.sub(substitute, text)


def find(text: str) -> list[tuple[str, tuple[str, ...]]]:
    """The tokens in `text`, in order."""
    return [(found.group(1), _arguments(found)) for found in TOKEN_PATTERN.finditer(text)]
