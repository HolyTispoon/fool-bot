"""
The old turns, read back off the pins (docs/pbd-site.md, step 6;
docs/design/pbd-site.md, "The old turns").

A finished turn's message stands pinned with its lines and its last
board (`stand_turn_message`), so a game that was being played, or had
ended, before the site went live has its history in its channel's pins
and nowhere else. This module reads one pinned message: whether it is
one of a game's turns, and the turn, heading and lines its text holds.
The publisher lists the pins and downloads the boards; nothing here
touches Discord.

**A pin is a game's only by its board's file name**,
`codex-<number>-board.webp` (`match_file_from_png`), and by its author
being the bot -- never by `BOARD_IMAGE_FILENAME_PREFIX` alone, which
starts every ephemeral picture's name too. A Rematch reuses its channel
with a new number, and a game in the `here` venue shares a channel with
people's own pins.

**The text is read back into the model's tokens**, so the history's
lines are what the record's other lines are and go through
`segments.segments` the same way: a mention becomes `{to:n}` for the
seat its user holds, a glyph's emoji its token (`{gold:n}` with the
amount after it), a hero's emoji and the bold name after it
`{hero:slug}`. A card stays bold text: the catalog is read by slug,
never by name (docs/design/codex.md, "The cards are data"), so a name
is not read back into a slug. A turn folded at
Discord's 2000 characters keeps its "*and n more*" line: what was
folded away is not there to import.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from codex import tokens
from cogs.codex_helpers import BOARD_IMAGE_FILENAME_PREFIX, TOKEN_EMOJI

if TYPE_CHECKING:
    from codex.game import CodexGame

#: A turn message's first line: "**Turn 7** -- ...".
HEADING = re.compile(r"^\*\*Turn (\d+)\*\*")
MENTION = re.compile(r"<@!?(\d+)>")
#: A custom emoji as Discord writes it, and what `CodexTokens.resolve`
#: puts after it: gold's amount, or a hero's bold name.
EMOJI = re.compile(r"<a?:(?P<name>[A-Za-z0-9_]+):\d+>(?P<after>\d+| \*\*[^*]+\*\*)?")
#: The emoji's name back to the token kind it stands for.
GLYPHS = {name: kind for kind, name in TOKEN_EMOJI.items()}


@dataclass
class PinnedTurn:
    """One finished turn as its pin holds it: the model's words with
    their tokens, and the board's attachment to download."""

    turn: int
    heading: str
    lines: list[str]
    board: object


def board_filename(game: "CodexGame") -> str:
    """The name `match_file_from_png` gives the game's board."""
    return f"{BOARD_IMAGE_FILENAME_PREFIX}{game.game_number}-board.webp"


def board_of(message, game: "CodexGame", bot_id: int):
    """The pinned message's board, where the message is one of `game`'s
    turns -- the bot's own, carrying the game's board by its exact
    name -- else `None`."""
    author = getattr(message, "author", None)
    if author is None or getattr(author, "id", None) != bot_id:
        return None
    name = board_filename(game)
    return next((attachment for attachment in getattr(message, "attachments", ())
                 if attachment.filename == name), None)


def seat_of(game: "CodexGame", user_id: int) -> Optional[int]:
    """The seat a user holds -- the first, where one person holds two
    seats of a test game."""
    return next((seat for seat in range(1, len(game.seats) + 1)
                 if game.seat_user_id(seat) == user_id), None)


def as_tokens(text: str, game: "CodexGame") -> str:
    """Discord's text read back into the model's: a seat's mention as
    `{to:n}`, the glyphs' and heroes' emoji as their tokens. A mention
    of somebody seated nowhere is "@someone", and an emoji that is no
    token's its name between colons."""
    def mention(found: re.Match) -> str:
        seat = seat_of(game, int(found.group(1)))
        return tokens.addressed(seat) if seat is not None else "@someone"

    def emoji(found: re.Match) -> str:
        name, after = found.group("name"), found.group("after") or ""
        kind = GLYPHS.get(name)
        if kind == "gold" and after.isdigit():
            return tokens.gold(int(after))
        if kind is not None:
            return "{" + kind + "}" + after
        if after.startswith(" **"):
            return tokens.hero(name)
        return f":{name}:{after}"

    return EMOJI.sub(emoji, MENTION.sub(mention, text))


def read_turn(message, game: "CodexGame", bot_id: int) -> Optional[PinnedTurn]:
    """The finished turn a pinned message stands for, or `None` where it
    is not one of `game`'s: another game's, somebody else's, or a text
    with no turn's heading."""
    board = board_of(message, game, bot_id)
    if board is None:
        return None
    text = getattr(message, "content", None) or ""
    first, _, rest = text.partition("\n")
    found = HEADING.match(first)
    if found is None:
        return None
    lines = [as_tokens(line, game) for line in rest.split("\n") if line.strip()]
    return PinnedTurn(int(found.group(1)), as_tokens(first, game), lines, board)
