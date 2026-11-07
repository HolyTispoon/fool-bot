"""
The New Project's fixed data, read once: the Human units and their
infrastructure upgrades (`data/humans.json`, imported from the unit
sheet), the technology cards (`data/technology.json`, imported), the
player board (`data/human_board.json`, kept by hand) and the map
(`data/map.json`, kept by hand, its outlines traced). See
docs/design/tnp.md, "The data".

Everything is keyed by slug -- `stealth_sniper`, `factory`,
`barracks_upgrade`, `command_and_control_cpu`, an area's `"7"` or
`"blue_base"` -- and never by name; `Catalog.name` is the one way back
to a name, for wording alone. The slugs share one namespace, which
`load` checks.

`Rating` carries the d12 (docs/tnp-rules.md, 4.1): the number a rating
needs and how many dice a force rolls with it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Mapping, Optional

DATA_DIR = Path(__file__).resolve().parent / "data"


class CatalogError(ValueError):
    """A data file is missing, unreadable, or disagrees with itself."""


class UnitType(str, Enum):
    INFANTRY = "infantry"
    ARMORED = "armored"
    AIR = "air"


class Rating(str, Enum):
    """A unit's attack against a type of unit (docs/tnp-rules.md, 4.1)."""

    STRONG = "strong"
    FAIR = "fair"
    WEAK = "weak"
    POOR = "poor"

    @property
    def target(self) -> int:
        """The number a d12, with its modifiers, must reach to hit."""
        return _TARGETS[self]

    @property
    def shown(self) -> str:
        """How the board shows the rating: 3+, 6+, 12, X."""
        return _SHOWN[self]

    def dice(self, units: int) -> int:
        """The dice a force of `units` rolls: one a unit, or for Poor
        one for every two, rounded down (TNP 4.3)."""
        return units // 2 if self is Rating.POOR else units


_TARGETS = {Rating.STRONG: 3, Rating.FAIR: 6, Rating.WEAK: 12, Rating.POOR: 12}
_SHOWN = {Rating.STRONG: "3+", Rating.FAIR: "6+", Rating.WEAK: "12", Rating.POOR: "X"}


@dataclass(frozen=True)
class Cost:
    materials: int = 0
    gold: int = 0


@dataclass(frozen=True)
class Unit:
    slug: str
    name: str
    type: UnitType
    facility: str
    upgrade: Optional[str]
    cost: Cost
    attack: Mapping[UnitType, Rating] = field(compare=False)
    initiative: int
    traits: tuple[str, ...]
    scouting: int
    ability: str
    supply: int

    def rating(self, against: UnitType) -> Rating:
        return self.attack[against]


@dataclass(frozen=True)
class Facility:
    slug: str
    name: str
    built_at_start: bool
    build_cost: Optional[Cost]
    requires: Optional[str]
    production_cap: int
    infrastructure_upgrade: str
    upgraded_production_cap: int
    units: tuple[str, ...]
    unit_upgrades: tuple[str, ...]
    unit_upgrades_allowed: int
    unit_upgrades_allowed_upgraded: int
    destructible: bool


@dataclass(frozen=True)
class Upgrade:
    """A facility's infrastructure upgrade (`kind` "infrastructure",
    imported), a unit upgrade (`kind` "unit", the board's), or an
    upgrade of the base itself (`kind` "base", imported, with no
    `facility`): Command and Control CPU, which opens attack spot C."""

    slug: str
    name: str
    kind: str
    facility: Optional[str]
    cost: Cost
    units: tuple[str, ...] = ()
    ability: str = ""


@dataclass(frozen=True)
class Tech:
    slug: str
    name: str
    count: int
    type: str
    deck: str
    materials: Optional[int]
    ability: str
    short_ability: str


@dataclass(frozen=True)
class Area:
    slug: str
    name: str
    kind: str
    number: Optional[int]
    seat: Optional[str]
    adjacent: tuple[str, ...]
    resources: Mapping[str, int] = field(compare=False)
    outline: tuple[tuple[int, int], ...] = field(compare=False, repr=False)

    @property
    def is_base(self) -> bool:
        return self.kind == "base"


@dataclass(frozen=True)
class Catalog:
    units: Mapping[str, Unit]
    facilities: Mapping[str, Facility]
    upgrades: Mapping[str, Upgrade]
    techs: Mapping[str, Tech]
    areas: Mapping[str, Area]
    #: human_board.json's numbers that are not a facility or an upgrade:
    #: max_supply, conversion, starting, limits, and transport -- each
    #: carrier's capacity by the unit carried (TNP 7) -- and
    #: transport_improved, the same with Improved Carrier Capacity.
    board: Mapping[str, object] = field(compare=False)

    def name(self, slug: str) -> str:
        """The one way from a slug back to a name."""
        for table in (self.units, self.facilities, self.upgrades, self.techs, self.areas):
            if slug in table:
                return table[slug].name
        raise KeyError(slug)

    def adjacent(self, one: str, other: str) -> bool:
        return other in self.areas[one].adjacent

    def find_unit(self, text: str) -> Optional[str]:
        """A unit's slug from its slug or its name, any case."""
        needle = text.strip().lower()
        if needle in self.units:
            return needle
        for slug, unit in self.units.items():
            if unit.name.lower() == needle:
                return slug
        return None

    def search_units(self, text: str, limit: int = 25) -> list[str]:
        """Units whose name holds `text`, in the sheet's order."""
        needle = text.strip().lower()
        return [
            slug for slug, unit in self.units.items()
            if needle in unit.name.lower() or needle in slug
        ][:limit]


def _cost(data: Optional[Mapping]) -> Optional[Cost]:
    if data is None:
        return None
    return Cost(materials=int(data.get("materials") or 0), gold=int(data.get("gold") or 0))


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise CatalogError(f"{path.name}: {error}") from error


def load(data_dir: Path = DATA_DIR) -> Catalog:
    """Read the four files into a `Catalog`, or raise `CatalogError`."""
    humans = _read(data_dir / "humans.json")
    technology = _read(data_dir / "technology.json")
    board = _read(data_dir / "human_board.json")
    world = _read(data_dir / "map.json")
    try:
        units = {
            slug: Unit(
                slug=slug,
                name=row["name"],
                type=UnitType(row["type"]),
                facility=row["facility"],
                upgrade=row["upgrade"],
                cost=_cost(row["cost"]),
                attack={UnitType(kind): Rating(value) for kind, value in row["attack"].items()},
                initiative=int(row["initiative"]),
                traits=tuple(row["traits"]),
                scouting=int(row["scouting"]),
                ability=row["ability"],
                supply=int(row["supply"]),
            )
            for slug, row in humans["units"].items()
        }
        facilities = {
            slug: Facility(
                slug=slug,
                name=row["name"],
                built_at_start=bool(row["built_at_start"]),
                build_cost=_cost(row["build_cost"]),
                requires=row["requires"],
                production_cap=int(row["production_cap"]),
                infrastructure_upgrade=row["infrastructure_upgrade"],
                upgraded_production_cap=int(row["upgraded_production_cap"]),
                units=tuple(row["units"]),
                unit_upgrades=tuple(row["unit_upgrades"]),
                unit_upgrades_allowed=int(row["unit_upgrades_allowed"]),
                unit_upgrades_allowed_upgraded=int(row["unit_upgrades_allowed_upgraded"]),
                destructible=bool(row["destructible"]),
            )
            for slug, row in board["facilities"].items()
        }
        upgrades = {
            slug: Upgrade(
                slug=slug,
                name=row["name"],
                kind="infrastructure" if row["facility"] else "base",
                facility=row["facility"],
                cost=_cost(row["cost"]),
                ability=row["ability"],
            )
            for slug, row in humans["infrastructure_upgrades"].items()
        }
        for slug, row in board["unit_upgrades"].items():
            if slug in upgrades:
                raise CatalogError(f"the upgrade {slug!r} is both an infrastructure and a unit upgrade")
            upgrades[slug] = Upgrade(
                slug=slug,
                name=row["name"],
                kind="unit",
                facility=row["facility"],
                cost=_cost(row["cost"]),
                units=tuple(row["units"]),
            )
        techs = {
            slug: Tech(
                slug=slug,
                name=row["name"],
                count=int(row["count"]),
                type=row["type"],
                deck=row["deck"],
                materials=row["materials"],
                ability=row["ability"],
                short_ability=row["short_ability"],
            )
            for slug, row in technology["techs"].items()
        }
        areas = {
            row["id"]: Area(
                slug=row["id"],
                name=row["name"],
                kind=row["kind"],
                number=row.get("number"),
                seat=row.get("seat"),
                adjacent=tuple(row["adjacent"]),
                resources=dict(row["resources"]),
                outline=tuple(tuple(point) for point in row.get("outline", ())),
            )
            for row in world["areas"]
        }
        extras = {
            key: board[key] for key in ("max_supply", "conversion", "starting", "limits")
        }
        for key in ("transport", "transport_improved"):
            extras[key] = {
                carrier: dict(capacity) for carrier, capacity in board.get(key, {}).items()
                if not carrier.startswith("_")
            }
    except (KeyError, TypeError, ValueError) as error:
        if isinstance(error, CatalogError):
            raise
        raise CatalogError(f"the TNP data does not read: {error!r}") from error

    seen: dict[str, str] = {}
    for kind, table in (
        ("unit", units), ("facility", facilities), ("upgrade", upgrades),
        ("tech", techs), ("area", areas),
    ):
        for slug in table:
            if slug in seen:
                raise CatalogError(f"the slug {slug!r} names a {seen[slug]} and a {kind}")
            seen[slug] = kind
    return Catalog(
        units=units, facilities=facilities, upgrades=upgrades,
        techs=techs, areas=areas, board=extras,
    )


@lru_cache(maxsize=1)
def catalog() -> Catalog:
    """The catalog over the committed data, read once a process."""
    return load()
