"""
A line of the model's, as the web draws it: **segments**, the resolver
the web gets beside `CodexTokens`.

A line is never HTML. Each token becomes a segment of its own, and the
text between them a text segment, so the page builds the line with
`textContent` and a display name can never be markup
(docs/design/pbd-site.md, "A line is segments"):

- `{"text": "..."}` -- with `"bold": true` and `"italic": true` where
  the line's `**bold**` and `*italic*` say so (on any segment inside
  them, a name or a card as well as text);
- `{"player": n, "name": ...}` for `{player:n}` and `{to:n}` alike --
  the seat's name off the record (`seat_label`), never a mention: the
  web pings nobody;
- `{"card": slug, "name": ...}` for `{card:slug}`, and `{hero:slug}`
  with `"hero": true`;
- `{"glyph": kind, "key": ...}` for `{exhaust}`, `{target}`, `{codex}`
  and `{gold:n}` (with `"n"`), `key` the picture's in the bucket --
  `exhaust`'s is `codex_exhaust.png`, as on Discord (`TOKEN_EMOJI`) --
  and `alt` the word it stands for;
- `{arrow}` as text, the character it is on Discord.

The tokens are found by `codex.tokens.render`, as `CodexTokens` finds
them, never by a pattern of this module's.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from codex import tokens
from codex.formatting import plain_token
from cogs.codex_helpers import TOKEN_EMOJI, seat_label
from cogs.codex_publish.keys import emoji_key

if TYPE_CHECKING:
    from codex.game import CodexGame

#: Stands in for a token while the line's emphasis is read: no line
#: holds it, and it holds no `*`.
_MARK = "\x00"

#: What a glyph says where its picture does not load.
GLYPH_WORDS = {"exhaust": "exhaust", "target": "target", "codex": "Codex", "gold": "gold"}


def segment(kind: str, arguments: tuple[str, ...], game: "Optional[CodexGame]") -> dict:
    """One token as a segment."""
    if kind in ("player", "to"):
        seat = int(arguments[0])
        return {"player": seat, "name": seat_label(game, seat)}
    if kind in ("card", "hero"):
        found = {"card": arguments[0], "name": plain_token(kind, arguments)}
        if kind == "hero":
            found["hero"] = True
        return found
    if kind in TOKEN_EMOJI:
        found = {"glyph": kind, "key": emoji_key(TOKEN_EMOJI[kind])}
        if kind == "gold":
            found["n"] = int(arguments[0])
            found["alt"] = f"{found['n']} gold"
        else:
            found["alt"] = GLYPH_WORDS[kind]
        return found
    return {"text": plain_token(kind, arguments)}


def _emphasis(text: str) -> tuple[list[tuple[int, str]], set[int]]:
    """
    The `**` and `*` markers in `text`, in order, and which of them open
    or close emphasis: each kind's markers pair up in order, and one
    left over -- an odd count -- is a literal asterisk.
    """
    markers: list[tuple[int, str]] = []
    index = 0
    while index < len(text):
        if text.startswith("**", index):
            markers.append((index, "**"))
            index += 2
        elif text[index] == "*":
            markers.append((index, "*"))
            index += 1
        else:
            index += 1
    paired: set[int] = set()
    for kind in ("**", "*"):
        positions = [position for position, marker in markers if marker == kind]
        if len(positions) % 2:
            positions = positions[:-1]
        paired.update(positions)
    return markers, paired


def segments(line: str, game: "Optional[CodexGame]" = None) -> list[dict]:
    """`line`, the model's with its tokens intact, as segments; names
    are `game`'s record's."""
    found: list[dict] = []

    def hold(kind: str, arguments: tuple[str, ...]) -> str:
        found.append(segment(kind, arguments, game))
        return _MARK

    held = tokens.render(line, hold)
    markers, paired = _emphasis(held)
    at = dict(markers)

    out: list[dict] = []
    flags = {"bold": False, "italic": False}

    def add(piece: dict) -> None:
        for flag, on in flags.items():
            if on:
                piece[flag] = True
        if "text" in piece and out and "text" in out[-1] \
                and {k: v for k, v in out[-1].items() if k != "text"} == \
                {k: v for k, v in piece.items() if k != "text"}:
            out[-1]["text"] += piece["text"]
            return
        if "text" in piece and not piece["text"]:
            return
        out.append(piece)

    tokens_seen = iter(found)
    index = 0
    while index < len(held):
        marker = at.get(index)
        if marker is not None:
            if index in paired:
                flag = "bold" if marker == "**" else "italic"
                flags[flag] = not flags[flag]
            else:
                add({"text": marker})
            index += len(marker)
            continue
        if held[index] == _MARK:
            add(dict(next(tokens_seen)))
            index += 1
            continue
        end = index
        while end < len(held) and held[end] not in ("*", _MARK):
            end += 1
        add({"text": held[index:end]})
        index = end
    return out
