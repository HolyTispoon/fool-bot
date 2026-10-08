"""
The keyword table: which keywords each card of the basic set has, and
its X where it takes one, read off the card texts in `codex/data/`.

**Present and inert in step 2**: nothing reads it to decide a rule yet,
and every card that has a keyword is in `codex.effects.UNIMPLEMENTED`.
Step 5 makes the engine's combat and targeting questions read it --
flying, anti-air, stealth, invisible, unstoppable, swift strike,
sparkshot, overpower, obliterate, readiness, frenzy, healing, resist,
haste -- the way `d12ball.special_abilities` is the one table for D12
Ball's abilities (docs/codex-bot.md, decision 7).

A keyword is read where a line of text *opens* with it -- "Frenzy 1
(Gets +1 ATK on your turn.)" -- so a sentence that only mentions one
("Arrives: Gets stealth this turn") is an effect, step 6's, and not a
keyword the card has.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Optional

from codex.cards import CardCatalog, Hero, catalog as load_catalog
from codex.effects import BASIC_SET

#: The keywords the basic set's texts open with, as the rulings'
#: `General` group names them.
KEYWORDS = (
    "Anti-air", "Channeling", "Flying", "Frenzy", "Haste", "Healing",
    "Invisible", "Obliterate", "Overpower", "Readiness", "Resist",
    "Sparkshot", "Stealth", "Swift strike", "Unstoppable",
)

_OPENING = re.compile(
    r"^(" + "|".join(re.escape(keyword) for keyword in KEYWORDS) + r")(?: (\d+))?(?:\s*\(|$)",
    re.IGNORECASE,
)


def read_keywords(lines) -> tuple[tuple[str, Optional[int]], ...]:
    """The (keyword, X) pairs a card's text lines open with."""
    found = []
    for line in lines:
        match = _OPENING.match(line.strip())
        if match:
            keyword = next(k for k in KEYWORDS if k.lower() == match.group(1).lower())
            found.append((keyword, int(match.group(2)) if match.group(2) else None))
    return tuple(found)


@lru_cache(maxsize=1)
def keyword_table(catalog: Optional[CardCatalog] = None) -> dict:
    """
    Slug to its keywords, for every card of the basic set that has any.
    A hero's are keyed `(slug, band's first level)`, since they come with
    its bands.
    """
    catalog = catalog or load_catalog()
    table: dict = {}
    for slug in sorted(BASIC_SET):
        card = catalog.by_slug(slug)
        if isinstance(card, Hero):
            for band in card.bands:
                found = read_keywords(band.text)
                if found:
                    table[(slug, band.min_level)] = found
            continue
        found = read_keywords(card.text)
        if found:
            table[slug] = found
    return table


def keywords(slug: str) -> tuple[tuple[str, Optional[int]], ...]:
    """A card's keywords, or none."""
    return keyword_table().get(slug, ())
