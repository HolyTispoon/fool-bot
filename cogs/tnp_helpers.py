"""
What TNP's Discord frontend needs beside the cog and its views: the
game's channel name and its category, and `TnpTokens`, the one resolver
from the model's tokens to the words a Discord message shows
(docs/design/tnp.md, "The lobby, the channel and the table").

The category is TNP's own, **TNP Games**, apart from D12 Ball's PBD
categories -- whose names `/debug`'s reset and the pin rollover match --
and from the Codex bot's (docs/design/codex.md, "The lobby and the
channel"). Nothing here decides a rule.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Optional

from botkit.channels import CHANNEL_NAME_MAX_LENGTH, get_or_create_category, slugify_channel_part
from tnp import tokens
from tnp.game import SEAT_NAMES

if TYPE_CHECKING:
    from tnp.catalog import Catalog
    from tnp.game import TnpGame

#: What every command and click says while the data has not loaded.
UNAVAILABLE = "TNP isn't available right now: its data didn't load. The bot's log says why."

TNP_GAMES_CATEGORY_NAME = "TNP Games"
#: `tnp-<n>`, then the players: the number is what identifies the game.
CHANNEL_NAME_PATTERN = re.compile(r"^tnp-(\d+)(?:-|$)")


def lobby_channel_name(game: "TnpGame") -> str:
    """The lobby's channel, before anybody is named in it: `tnp-<n>`."""
    return f"tnp-{game.game_number}"


def channel_name(game: "TnpGame") -> str:
    """`tnp-<n>-<blue>-vs-<green>` once both seats are taken, each
    player's name slugged, capped at Discord's 100 characters; `tnp-<n>`
    while a seat is open."""
    prefix = lobby_channel_name(game)
    names = [slugify_channel_part(game.seats[seat]["name"] or "") for seat in SEAT_NAMES]
    if not all(names):
        return prefix
    return f"{prefix}-{'-vs-'.join(names)}"[:CHANNEL_NAME_MAX_LENGTH].rstrip("-")


async def tnp_games_category(guild):
    return await get_or_create_category(
        guild, TNP_GAMES_CATEGORY_NAME, "Create the category for TNP games.",
    )


def seat_word(seat: str) -> str:
    """"Blue", "Green": a seat as the rules name it (TNP 1.2)."""
    return seat.title()


def seat_label(game: "Optional[TnpGame]", seat: str) -> str:
    """A seat as a message names it: "**Blue** (alice)", or "**Blue**"
    where nobody sits there."""
    name = game.seats[seat]["name"] if game is not None else None
    return f"**{seat_word(seat)}** ({name})" if name else f"**{seat_word(seat)}**"


class TnpTokens:
    """
    The model's tokens as words on Discord, rendered once at the cog's
    door: a seat by its colour and its player, a unit, a facility or an
    upgrade by its name, a territory as "area 8" and a base by its name
    -- `tnp.tokens.plain`'s words, the seat's player added. No emoji
    yet: none is uploaded for TNP.
    """

    def __init__(self, catalog: "Optional[Catalog]") -> None:
        self.catalog = catalog

    def render(self, text: str, game: "Optional[TnpGame]" = None) -> str:
        def resolve(kind: str, arguments: tuple[str, ...]) -> Optional[str]:
            (slug,) = arguments
            if kind == "seat":
                return seat_label(game, slug)
            if self.catalog is None:
                return None
            if kind == "area":
                found = self.catalog.areas[slug]
                return found.name if found.is_base else f"area {found.number}"
            return self.catalog.name(slug)

        return tokens.render(text, resolve)
