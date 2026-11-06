"""
The turn's readings (docs/tnp-rules.md, 2 to 5): what a seat holds and
what its held territories join to its base, where a pile can reach,
what a seat owns and may still build, what its plan costs, and whether a
plan or a trade is one the rules allow. The steps that change the match
are `tnp.flow.turn`'s; the one reading of what the match waits on is
`tnp.prompts`'.

Nothing here changes the match. A check refuses with `RuleRefusal`,
citing the section that says no; `tnp.flow.driver.answer` turns that
into a `Refusal` and puts the match back as it was.

**A plan** is a seat's Infrastructure and Deployment, as one dict
(TNP 5.2, 5.3):

    {
        "build": {"worker": 4},                 # units, at their facility
        "structures": ["factory"],              # facilities and upgrades
        "attacks": {"A": {"target": "14", "units": {"worker": 3}}},
        "defense": {"blue_base": {"mercenary": 3}},
    }

and **a trade** the tokens of each kind traded for materials and for
gold (TNP 5.9):

    {"materials": {"blue_minerals": 3}, "gold": {"gems": 1}}
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable, Mapping, Optional

from tnp.battle import SEATS, other
from tnp.catalog import Cost, UnitType
from tnp.components import ATTACK_SPOTS, BASIC_ATTACK_SPOTS, RESOURCES, MatchState, SeatState
from tnp.game import RuleRefusal

if TYPE_CHECKING:
    from tnp.engine import RulesEngine


def base_of(seat: str) -> str:
    """A seat's base, an area of the map (TNP 2.1)."""
    return f"{seat}_base"


# -- What a seat holds, and what joins it to its base ------------------------------


def held(match: MatchState, seat: str) -> set[str]:
    """The territories a seat holds (TNP 2.1) -- its base not among them."""
    return {
        slug for slug, area in match.areas.items()
        if area.controller == seat and slug != base_of(seat)
    }


def joined(engine: "RulesEngine", match: MatchState, seat: str) -> set[str]:
    """
    The seat's base and every territory its held territories join to it
    (TNP 5.3, 5.7): the areas a path of held territories reaches from
    the base.
    """
    holding = held(match, seat)
    found = {base_of(seat)}
    frontier = [base_of(seat)]
    while frontier:
        here = frontier.pop()
        for there in engine.catalog.areas[here].adjacent:
            if there in holding and there not in found:
                found.add(there)
                frontier.append(there)
    return found


def has_path(engine: "RulesEngine", match: MatchState, seat: str, area: str) -> bool:
    """
    Whether a path of held territories runs from the seat's base to
    `area` (TNP 5.3): `area` is beside the base, or beside a territory
    the seat holds that its held territories join to the base. The same
    reading is a path home from a battle there (TNP 6.6).
    """
    reach = joined(engine, match, seat)
    return area in reach or any(there in reach for there in engine.catalog.areas[area].adjacent)


def carriers_needed(engine: "RulesEngine", units: Mapping[str, int]) -> Optional[int]:
    """
    How many Chopper Carriers it takes to carry a pile's ground units
    (TNP 7: Transport), one kind a carrier without mixing -- `None` where
    one of them cannot be carried at all.
    """
    capacity = engine.catalog.board.get("transport", {}).get("chopper_carrier", {})
    needed = 0
    for slug, count in units.items():
        if not count or engine.unit(slug).type is UnitType.AIR:
            continue
        per = capacity.get(slug)
        if not per:
            return None
        needed += -(-int(count) // int(per))
    return needed


def reaches(engine: "RulesEngine", match: MatchState, seat: str, area: str,
            units: Mapping[str, int]) -> bool:
    """
    Whether a pile reaches the area it attacks as its attack resolves
    (TNP 5.3): along a path of held territories, or with no path where it
    is air units alone, or a carried stack -- every ground unit in it
    fitting its Chopper Carriers (TNP 7).
    """
    if has_path(engine, match, seat, area):
        return True
    needed = carriers_needed(engine, units)
    return needed is not None and needed <= int(units.get("chopper_carrier", 0))


def ground_units(engine: "RulesEngine", units: Mapping[str, int]) -> dict[str, int]:
    """The infantry and armored units of a pile, which can take a
    territory (TNP 5.5)."""
    return {
        slug: count for slug, count in units.items()
        if count and engine.unit(slug).type is not UnitType.AIR
    }


# -- What a seat owns and may build ----------------------------------------------------


def owned(match: MatchState, seat: str) -> dict[str, int]:
    """
    Every unit the seat has, wherever it is (TNP 2.3, supply): at its
    base, queued, in a defense spot, in an attack pile, in the attack
    being resolved and in a battle.
    """
    found: dict[str, int] = {}

    def add(units: Mapping[str, int]) -> None:
        for slug, count in units.items():
            if count:
                found[slug] = found.get(slug, 0) + int(count)

    state = match.seat(seat)
    add(state.available)
    add(state.queued_units)
    for piles in match.spots.values():
        if seat in piles:
            add(piles[seat].units)
    for attack in match.attacks.get(seat, {}).values():
        add(attack["units"])
    if match.resolving is not None:
        add(match.resolving.get("piles", {}).get(seat, {}))
    if match.battle is not None and match.battle.outcome is None:
        add({force.unit: force.count for force in match.battle.living(seat)})
    return found


def supply_room(engine: "RulesEngine", match: MatchState, seat: str) -> dict[str, int]:
    """How many more of each unit the seat may have (TNP 2.3)."""
    have = owned(match, seat)
    return {
        slug: max(0, unit.supply - have.get(slug, 0)) for slug, unit in engine.catalog.units.items()
    }


def production_cap(engine: "RulesEngine", state: SeatState, facility: str) -> int:
    """A facility's production cap: its upgraded cap once its
    infrastructure upgrade is built (TNP 2.4)."""
    found = engine.catalog.facilities[facility]
    if found.infrastructure_upgrade in state.built:
        return found.upgraded_production_cap
    return found.production_cap


def can_build_unit(engine: "RulesEngine", state: SeatState, slug: str) -> bool:
    """Whether a seat's board builds a unit now: its facility finished
    in an earlier turn, and its unit upgrade too where it needs one
    (TNP 2.4, 5.2)."""
    unit = engine.unit(slug)
    return unit.facility in state.built and (unit.upgrade is None or unit.upgrade in state.built)


def unit_upgrades_allowed(engine: "RulesEngine", state: SeatState, facility: str) -> int:
    """How many unit upgrades a facility may have: the Barracks one, two
    once its infrastructure upgrade is built (TNP 2.4)."""
    found = engine.catalog.facilities[facility]
    if found.infrastructure_upgrade in state.built:
        return found.unit_upgrades_allowed_upgraded
    return found.unit_upgrades_allowed


def structures_open(engine: "RulesEngine", state: SeatState) -> tuple[str, ...]:
    """
    The facilities and upgrades a seat may place this Infrastructure
    (TNP 2.4, 5.2), each on its own: a facility not built, whose
    requirement is finished; an infrastructure or unit upgrade of a
    finished facility, not built, within the facility's unit upgrades.
    Together they are checked by `check_plan`.
    """
    catalog = engine.catalog
    found = []
    for slug, facility in catalog.facilities.items():
        if slug in state.built:
            continue
        if facility.build_cost is None:
            continue
        if facility.requires is not None and facility.requires not in state.built:
            continue
        found.append(slug)
    for slug, upgrade in catalog.upgrades.items():
        if slug in state.built or upgrade.facility not in state.built:
            continue
        if upgrade.kind == "unit":
            standing = [one for one in catalog.facilities[upgrade.facility].unit_upgrades if one in state.built]
            if len(standing) >= unit_upgrades_allowed(engine, state, upgrade.facility):
                continue
        found.append(slug)
    return tuple(found)


def structure_cost(engine: "RulesEngine", slug: str) -> Cost:
    catalog = engine.catalog
    if slug in catalog.facilities:
        return catalog.facilities[slug].build_cost
    return catalog.upgrades[slug].cost


def attack_spots(match: MatchState) -> tuple[str, ...]:
    """A and B; C only with Command and Control CPU, the advanced game's
    (TNP 2.5) -- never in the basic game."""
    return BASIC_ATTACK_SPOTS


def attack_targets(engine: "RulesEngine", seat: str) -> tuple[str, ...]:
    """What an attack may be aimed at (TNP 5.3): any territory, the
    seat's own included -- the only way to harvest it (TNP 5.8) -- and
    the other seat's base."""
    return tuple(
        slug for slug, area in engine.catalog.areas.items()
        if not area.is_base or slug == base_of(other(seat))
    )


def defense_areas(engine: "RulesEngine", match: MatchState, seat: str) -> tuple[str, ...]:
    """Where a seat may deploy defenders: a territory it holds that its
    held territories join to its base, and the base (TNP 2.5) -- a
    territory cut off holds only the stranded units already there."""
    reach = joined(engine, match, seat)
    return tuple(sorted(held(match, seat) & reach, key=_area_order)) + (base_of(seat),)


def _area_order(slug: str) -> tuple[int, str]:
    return (int(slug), "") if slug.isdigit() else (100, slug)


def area_order(slug: str) -> tuple[int, str]:
    """Ascending territory number, the order a spot's attacks resolve in
    (TNP 5.4); a base after every territory."""
    return _area_order(slug)


# -- Checking a plan -----------------------------------------------------------------


def _counts(value, what: str, cite: str) -> dict[str, int]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise RuleRefusal(f"{what} is a count by unit.", cite=cite)
    found = {}
    for slug, count in value.items():
        try:
            count = int(count)
        except (TypeError, ValueError):
            raise RuleRefusal(f"{what}: {count!r} is not a count.", cite=cite) from None
        if count < 0:
            raise RuleRefusal(f"{what}: a count cannot be below none.", cite=cite)
        if count:
            found[str(slug)] = count
    return found


def normal_plan(plan: Optional[Mapping]) -> dict:
    """A plan with every part present and its zeros dropped -- the shape
    `check_plan` reads and the match keeps."""
    plan = dict(plan or {})
    unknown = set(plan) - {"build", "structures", "attacks", "defense"}
    if unknown:
        raise RuleRefusal(f"A plan has no part called {sorted(unknown)[0]!r}.", cite="TNP 5.2")
    attacks = {}
    for spot, attack in (plan.get("attacks") or {}).items():
        if not isinstance(attack, Mapping):
            raise RuleRefusal("An attack names its target and its units.", cite="TNP 5.3")
        units = _counts(attack.get("units"), "An attack's units", "TNP 5.3")
        if units:
            attacks[str(spot)] = {"target": str(attack.get("target")), "units": units}
    defense = {}
    for area, units in (plan.get("defense") or {}).items():
        units = _counts(units, "A defense's units", "TNP 5.3")
        if units:
            defense[str(area)] = units
    structures = plan.get("structures") or []
    if isinstance(structures, (str, bytes)) or not isinstance(structures, Iterable):
        raise RuleRefusal("The structures are a list of facilities and upgrades.", cite="TNP 5.2")
    return {
        "build": _counts(plan.get("build"), "What is built", "TNP 5.2"),
        "structures": [str(slug) for slug in structures],
        "attacks": attacks,
        "defense": defense,
    }


def plan_cost(engine: "RulesEngine", plan: Mapping) -> Cost:
    """What a plan's Infrastructure costs (TNP 5.2)."""
    materials = gold = 0
    for slug, count in plan["build"].items():
        cost = engine.unit(slug).cost
        materials += cost.materials * count
        gold += cost.gold * count
    for slug in plan["structures"]:
        cost = structure_cost(engine, slug)
        materials += cost.materials
        gold += cost.gold
    return Cost(materials, gold)


def deployed(plan: Mapping) -> dict[str, int]:
    """Every unit a plan deploys, into any spot."""
    found: dict[str, int] = {}
    for units in (*(attack["units"] for attack in plan["attacks"].values()), *plan["defense"].values()):
        for slug, count in units.items():
            found[slug] = found.get(slug, 0) + count
    return found


def check_plan(engine: "RulesEngine", match: MatchState, seat: str, plan: Mapping) -> None:
    """
    Refuse a plan the rules do not allow (TNP 2.4, 2.5, 5.2, 5.3), with
    the section that says no. `plan` is `normal_plan`'s.
    """
    catalog = engine.catalog
    state = match.seat(seat)

    # Infrastructure (TNP 5.2).
    for slug in plan["build"]:
        if slug not in catalog.units:
            raise RuleRefusal(f"No unit is called {slug!r}.", cite="TNP 2.3")
        if not can_build_unit(engine, state, slug):
            raise RuleRefusal(
                f"{catalog.name(slug)} needs its facility, and its upgrade where it has one, "
                "finished in an earlier turn.", cite="TNP 5.2",
            )
    by_facility: dict[str, int] = {}
    for slug, count in plan["build"].items():
        facility = catalog.units[slug].facility
        by_facility[facility] = by_facility.get(facility, 0) + count
    for facility, count in by_facility.items():
        cap = production_cap(engine, state, facility)
        if count > cap:
            raise RuleRefusal(
                f"The {catalog.name(facility)} produces at most {cap} a turn.", cite="TNP 2.4",
            )
    room = supply_room(engine, match, seat)
    for slug, count in plan["build"].items():
        if count > room[slug]:
            raise RuleRefusal(
                f"Only {room[slug]} more {catalog.name(slug)} fit the supply.", cite="TNP 2.3",
            )
    open_now = structures_open(engine, state)
    if len(set(plan["structures"])) != len(plan["structures"]):
        raise RuleRefusal("Each facility or upgrade is placed once.", cite="TNP 5.2")
    for slug in plan["structures"]:
        if slug not in catalog.facilities and slug not in catalog.upgrades:
            raise RuleRefusal(f"Nothing in a base is called {slug!r}.", cite="TNP 2.4")
        if slug not in open_now:
            raise RuleRefusal(
                f"The {catalog.name(slug)} cannot be placed now: it is built, or what it needs "
                "is not finished from an earlier turn.", cite="TNP 2.4",
            )
    for facility, found in catalog.facilities.items():
        upgrading = [slug for slug in plan["structures"] if slug in found.unit_upgrades]
        standing = [slug for slug in found.unit_upgrades if slug in state.built]
        if len(standing) + len(upgrading) > unit_upgrades_allowed(engine, state, facility):
            raise RuleRefusal(
                f"The {found.name} takes one unit upgrade until its infrastructure upgrade.",
                cite="TNP 2.4",
            )
    cost = plan_cost(engine, plan)
    pool = state.pool
    if cost.materials > pool.get("materials", 0) or cost.gold > pool.get("gold", 0):
        raise RuleRefusal(
            f"That costs {cost.materials} materials and {cost.gold} gold; the pool holds "
            f"{pool.get('materials', 0)} and {pool.get('gold', 0)}. Minerals and gems are "
            "traded at Production and Trade.", cite="TNP 5.2",
        )

    # Deployment (TNP 2.5, 5.3).
    spots = attack_spots(match)
    targets = attack_targets(engine, seat)
    for spot, attack in plan["attacks"].items():
        if spot not in ATTACK_SPOTS:
            raise RuleRefusal(f"There is no attack spot {spot!r}.", cite="TNP 2.5")
        if spot not in spots:
            raise RuleRefusal(
                f"Attack spot {spot} needs Command and Control CPU, the advanced game's.",
                cite="TNP 2.5",
            )
        if attack["target"] not in targets:
            raise RuleRefusal("An attack is aimed at a territory or the other seat's base.", cite="TNP 5.3")
        for slug in attack["units"]:
            if slug not in catalog.units:
                raise RuleRefusal(f"No unit is called {slug!r}.", cite="TNP 2.3")
            if engine.has_trait(slug, "base_defense"):
                raise RuleRefusal(
                    "Base Defense units go only into the base defense spot.", cite="TNP 7",
                )
    allowed = set(defense_areas(engine, match, seat))
    for area, units in plan["defense"].items():
        if area not in allowed:
            raise RuleRefusal(
                "Defenders go into a territory the seat holds and its held territories join to "
                "its base, or into the base.", cite="TNP 2.5",
            )
        for slug in units:
            if slug not in catalog.units:
                raise RuleRefusal(f"No unit is called {slug!r}.", cite="TNP 2.3")
            if engine.has_trait(slug, "base_defense") and area != base_of(seat):
                raise RuleRefusal(
                    "Base Defense units go only into the base defense spot.", cite="TNP 7",
                )
    going = deployed(plan)
    for slug, count in going.items():
        if count > state.available.get(slug, 0):
            raise RuleRefusal(
                f"Only {state.available.get(slug, 0)} {catalog.name(slug)} are available to deploy; "
                "a unit built this turn is deployed next turn.", cite="TNP 5.3",
            )
    for limit in catalog.board["limits"]["deployed_together"]:
        units = tuple(limit["units"])
        if sum(going.get(slug, 0) for slug in units) > int(limit["max"]):
            raise RuleRefusal(
                f"At most {limit['max']} of " + " and ".join(catalog.name(slug) for slug in units)
                + " are deployed together.", cite="TNP 2.4",
            )


# -- Checking a trade -------------------------------------------------------------------


def normal_trade(trade: Optional[Mapping]) -> dict:
    trade = dict(trade or {})
    unknown = set(trade) - {"materials", "gold"}
    if unknown:
        raise RuleRefusal(f"A token trades for materials or gold, not {sorted(unknown)[0]!r}.", cite="TNP 5.9")
    found = {}
    for into in ("materials", "gold"):
        counts = _counts(trade.get(into), "A trade", "TNP 5.9")
        for kind in counts:
            if kind not in RESOURCES:
                raise RuleRefusal(f"Only minerals and gems are traded, not {kind!r}.", cite="TNP 5.9")
        found[into] = counts
    return found


def _rate_key(kind: str) -> str:
    return "gem" if kind == "gems" else "mineral"


def trade_gains(engine: "RulesEngine", trade: Mapping) -> dict[str, int]:
    """What a trade gains at the conversion rates (TNP 5.9)."""
    rates = engine.catalog.board["conversion"]["normal"]
    return {
        into: sum(count * int(rates[_rate_key(kind)][into]) for kind, count in trade[into].items())
        for into in ("materials", "gold")
    }


def check_trade(match: MatchState, seat: str, trade: Mapping) -> None:
    """Each token trades for materials or for gold, never both, from the
    tokens in the pool (TNP 5.9)."""
    pool = match.seat(seat).pool
    for kind in RESOURCES:
        traded = trade["materials"].get(kind, 0) + trade["gold"].get(kind, 0)
        if traded > pool.get(kind, 0):
            raise RuleRefusal(
                f"The pool holds {pool.get(kind, 0)} of that, and a token trades once.", cite="TNP 5.9",
            )


def has_tokens(match: MatchState, seat: str) -> bool:
    """Whether a seat has a mineral or a gem to trade -- asked only then."""
    pool = match.seat(seat).pool
    return any(pool.get(kind, 0) for kind in RESOURCES)


__all__ = [
    "SEATS", "area_order", "attack_spots", "attack_targets", "base_of", "can_build_unit",
    "carriers_needed", "check_plan", "check_trade", "defense_areas", "deployed", "ground_units",
    "has_path", "has_tokens", "held", "joined", "normal_plan", "normal_trade", "owned",
    "plan_cost", "production_cap", "reaches", "structure_cost", "structures_open",
    "supply_room", "trade_gains", "unit_upgrades_allowed",
]
