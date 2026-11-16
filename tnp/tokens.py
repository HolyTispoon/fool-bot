"""
The marks TNP's narration leaves for a frontend to draw: a seat
(`{seat:blue}`), a unit (`{unit:tank}`), an area of the map
(`{area:8}`, `{area:blue_base}`) and a thing in a base
(`{thing:factory_upgrade}`, a facility or an upgrade). The model never
holds a name a frontend would draw differently; a frontend renders every
token once, at its door -- `plain` here is the words, which the tests
and the logs read. The shape is Codex's (`codex/tokens.py`), the kinds
TNP's own (docs/design/model-discord-split.md, "Tokens").
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from gamekit.tokens import Resolver

if TYPE_CHECKING:
    from tnp.catalog import Catalog

KINDS = ("seat", "unit", "area", "thing", "card")

TOKEN_PATTERN = re.compile(r"\{(" + "|".join(KINDS) + r")((?::[a-z0-9_]+)*)\}")


def seat(name: str) -> str:
    """A seat, "blue" or "green" -- whoever sits there."""
    return f"{{seat:{name}}}"


def unit(slug: str) -> str:
    return f"{{unit:{slug}}}"


def area(slug: str) -> str:
    return f"{{area:{slug}}}"


def thing(slug: str) -> str:
    """A facility or an upgrade of a base -- or, in the advanced game, a
    tech facility, or a building tech on its facility, named
    `"<card>:<facility>"` (TNP 6.9, 8)."""
    return f"{{thing:{slug}}}"


def card(slug: str) -> str:
    """A technology card (TNP 8), by its name."""
    return f"{{card:{slug}}}"


def words(kind: str, arguments: tuple[str, ...], catalog: "Catalog") -> str:
    """Every token but a seat, in words: a unit, a thing or a card by
    its name, a territory as "area 8" and a base by its name, a building
    tech as "Grenades on the Factory"."""
    if kind == "area":
        found = catalog.areas[arguments[0]]
        return found.name if found.is_base else f"area {found.number}"
    if kind == "thing" and len(arguments) == 2:
        return f"{catalog.name(arguments[0])} on the {catalog.name(arguments[1])}"
    return catalog.name(arguments[0])


def _arguments(found: re.Match) -> tuple[str, ...]:
    return tuple(part for part in found.group(2).split(":") if part)


def render(text: str, resolve: Resolver) -> str:
    """Every token in `text` as `resolve` draws it; a token it returns
    `None` for is left as it stands."""

    def one(found: re.Match) -> str:
        drawn = resolve(found.group(1), _arguments(found))
        return found.group(0) if drawn is None else drawn

    return TOKEN_PATTERN.sub(one, text)


def find(text: str) -> list[tuple[str, tuple[str, ...]]]:
    return [(found.group(1), _arguments(found)) for found in TOKEN_PATTERN.finditer(text)]


def plain(text: str, catalog: "Catalog") -> str:
    """The text in words: "Blue", "Tank", "area 8", "Blue's base"."""

    def resolve(kind: str, arguments: tuple[str, ...]):
        if kind == "seat":
            return arguments[0].title()
        return words(kind, arguments, catalog)

    return render(text, resolve)
