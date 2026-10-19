"""
The cards' pictures on the site (docs/design/pbd-site.md, "The cards'
pictures"): which cards have one, where each is in the bucket, and a card
as the page's JSON names it -- its slug, its name and its picture's key.

A card's picture is the file the board draws it from (`Card.picture`,
`Hero.picture`): the database's art for a card or a hero, the module's
face for a token or a building. Every one is put once into the bucket,
under `codex/cards/`, and a line's card, a board's card and a tech
building's codex all name the same key, so the page builds none.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

from codex.cards import catalog
from cogs.codex_publish import keys


@lru_cache(maxsize=None)
def picture(slug: str) -> Optional[Path]:
    """The file `slug`'s card is drawn from, or `None` where it has
    none on disk -- a card the board draws as its back."""
    try:
        found = catalog().by_slug(slug).picture
    except KeyError:
        return None
    return found if found is not None and found.is_file() else None


def key(slug: str) -> Optional[str]:
    """`slug`'s picture in the bucket, or `None` where it has none."""
    found = picture(slug)
    return keys.card_key(slug, found.suffix) if found is not None else None


def entry(slug: str) -> dict:
    """A card as the page's JSON names it: its `slug`, its `name` off
    the catalog, and its picture's `key` -- `None` where it has none."""
    try:
        name = catalog().name(slug)
    except KeyError:
        name = slug
    return {"slug": slug, "name": name, "key": key(slug)}


def pictured() -> list[str]:
    """Every card and hero with a picture, by slug: what the startup
    puts into the bucket."""
    found = catalog()
    return sorted(slug for slug in [*found.cards, *found.heroes] if picture(slug) is not None)
