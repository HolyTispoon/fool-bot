"""
What `tnp/render.py` draws the map and a player board from, with no
Pillow in it, so the model can build one without importing a drawing
library (the purity ratchet, `tests/test_tnp_purity.py`).

A brief is a reading of the position for one picture, and it is
**already filtered for whoever will see it** -- the renderer draws what
it is handed and decides nothing:

- `MapBrief` is public. It holds who holds each territory, the resource
  tokens left, the Stranded tokens and the piles March has revealed so
  far, and nothing else: no seat's deployment is in it before March
  reveals that pile (TNP 5.3, the author's answer to question 12).
- `BoardBrief` is one seat's own player board, its queue included,
  which is that seat's alone until Production and Trade (TNP 5.2): the
  frontend shows it to that seat and nobody else.

The battle needs no brief: it is a saved state of its own
(`tnp.battle.BattleState`), already one picture's worth, and public.

Step 3 builds the opening position's briefs (`opening_map`,
`opening_board`) from the data; step 4, which adds the map and the
seats to `MatchState`, adds the readings that build them from a match.
See docs/design/tnp.md, "The pictures".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from tnp.catalog import Catalog

#: The resource tokens, in the order they are drawn (TNP 2.1, 2.2).
RESOURCES = ("blue_minerals", "orange_minerals", "gems")

#: What a seat's pool holds, in the order the board shows it (TNP 2.2).
POOL = ("materials", "gold") + RESOURCES

#: A pile's spot: the attack spots, and the defense spot (TNP 2.5).
ATTACK_SPOTS = ("A", "B", "C")
DEFENSE = "defense"


@dataclass(frozen=True)
class Pile:
    """One pile March has revealed (TNP 5.4): a seat's units in one
    spot, with the area it attacks or defends."""

    seat: str
    area: str
    spot: str
    units: Mapping[str, int] = field(compare=False)


@dataclass(frozen=True)
class MapBrief:
    """The map as everybody may see it."""

    #: Each held territory's seat (TNP 2.1); a territory not here is
    #: neutral. The bases are their seats' always and are not listed.
    controllers: Mapping[str, str] = field(default_factory=dict)
    #: The resource tokens left on each area, by `RESOURCES` key.
    resources: Mapping[str, Mapping[str, int]] = field(default_factory=dict)
    #: The seats with a Stranded token on each area (TNP 5.7).
    stranded: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    #: The piles March has revealed so far, in the order it revealed them.
    revealed: tuple[Pile, ...] = ()
    #: A line under the title -- the turn and the phase -- worded by the
    #: model; empty for none.
    caption: str = ""


@dataclass(frozen=True)
class BoardBrief:
    """A seat's own player board (TNP 2.4)."""

    seat: str
    #: The available resource pool, by `POOL` key (TNP 2.2).
    pool: Mapping[str, int] = field(default_factory=dict)
    #: The facilities and upgrades finished, by slug.
    built: frozenset[str] = frozenset()
    #: The facilities and upgrades placed this Infrastructure, finished
    #: at Production and Trade (TNP 5.2).
    queued: frozenset[str] = frozenset()
    #: The units placed this Infrastructure, by slug.
    queued_units: Mapping[str, int] = field(default_factory=dict)
    #: How many more of each unit the seat may have (TNP 2.3).
    supply_left: Mapping[str, int] = field(default_factory=dict)
    caption: str = ""


def opening_map(catalog: Catalog) -> MapBrief:
    """The map at setup: every territory neutral, with its tokens
    (TNP 3)."""
    return MapBrief(
        resources={
            slug: {key: int(area.resources.get(key, 0)) for key in RESOURCES}
            for slug, area in catalog.areas.items() if not area.is_base
        },
    )


def opening_board(catalog: Catalog, seat: str) -> BoardBrief:
    """A seat's board at setup: the Barracks and Base Defenses built,
    3 Workers, 3 Mercenaries and 5 materials (TNP 3)."""
    starting = catalog.board["starting"]
    units = starting["units"]
    pool = {key: int(starting["pool"].get(key, 0)) for key in POOL}
    return BoardBrief(
        seat=seat,
        pool=pool,
        built=frozenset(slug for slug, facility in catalog.facilities.items() if facility.built_at_start),
        supply_left={
            slug: unit.supply - int(units.get(slug, 0)) for slug, unit in catalog.units.items()
        },
    )
