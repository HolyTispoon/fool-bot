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


#: What a patrol slot grants whatever stands in it (UMR p. 10): the
#: lookout's resist 1. The other four slots give armor, ATK, gold and a
#: card, which are the board's arithmetic rather than keywords.
PATROL_GRANTS: dict[str, tuple[tuple[str, Optional[int]], ...]] = {
    "lookout": (("Resist", 1),),
}

#: The keywords two instances of which are two (UMR p. 16, and Sirlin's
#: rulings on each): frenzy, resist and sparkshot stack; anti-air and
#: overpower do not, and the rest are flags. Healing is a card's own
#: ability rather than a stacking keyword -- two Helpful Turtles heal
#: twice because each heals once.
STACKING = frozenset({"Frenzy", "Resist", "Sparkshot", "Healing"})


def hero_keywords(slug: str, level: int) -> tuple[tuple[str, Optional[int]], ...]:
    """A hero's keywords at `level`: every band it has reached (UMR p. 6)
    -- Troq has readiness from level 8 on, and not before."""
    table = keyword_table()
    found: list[tuple[str, Optional[int]]] = []
    for key, pairs in table.items():
        if isinstance(key, tuple) and key[0] == slug and key[1] <= level:
            found.extend(pairs)
    return tuple(found)


def body_keywords(body, match=None) -> tuple[tuple[str, Optional[int]], ...]:
    """
    Every keyword a thing in play has: its card's printed ones (a hero's
    by the bands it has reached), and what its patrol slot grants it.
    Abilities granted by another card in play -- Nimble Fencer's haste,
    Blademaster's swift strike -- are step 6's, and come in here.
    """
    slug = getattr(body, "slug", None)
    if slug is None:
        return ()
    level = getattr(body, "level", None)
    found = list(hero_keywords(slug, level) if level is not None else keywords(slug))
    found.extend(PATROL_GRANTS.get(getattr(body, "patrol_slot", None) or "", ()))
    return tuple(found)


def has_keyword(body, keyword: str, match=None) -> bool:
    """Whether a unit, hero or add-on in play has `keyword`."""
    return any(name == keyword for name, _ in body_keywords(body, match))


def keyword_x(body, keyword: str, match=None) -> int:
    """
    `keyword`'s X on this thing: summed where the keyword stacks and the
    highest otherwise, 0 where it does not have it. A keyword written
    without a number counts as 1, so `keyword_x(card, "Flying")` is 1
    for a flier.
    """
    values = [1 if x is None else x for name, x in body_keywords(body, match) if name == keyword]
    if not values:
        return 0
    return sum(values) if keyword in STACKING else max(values)
