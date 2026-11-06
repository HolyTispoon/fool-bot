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
seats to `MatchState`, adds the readings that build them from a match
(`map_brief`, `board_brief`). See docs/design/tnp.md, "The pictures".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Mapping, Optional

from tnp.catalog import Catalog

if TYPE_CHECKING:
    from tnp.components import MatchState
    from tnp.engine import RulesEngine

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


def map_brief(match: "MatchState", caption: str = "") -> MapBrief:
    """
    The map of a match as everybody may see it: who holds each
    territory, the tokens left, the Stranded tokens, and what March has
    revealed this turn (`MatchState.revealed`) -- never an attack pile
    or a defense spot March has not reached (TNP 5.3).
    """
    return MapBrief(
        controllers={
            slug: area.controller for slug, area in match.areas.items()
            if area.controller is not None and not slug.endswith("_base")
        },
        resources={
            slug: {key: int(area.resources.get(key, 0)) for key in RESOURCES}
            for slug, area in match.areas.items() if not slug.endswith("_base")
        },
        stranded={slug: tuple(area.stranded) for slug, area in match.areas.items() if area.stranded},
        revealed=tuple(
            Pile(one["seat"], one["area"], one["spot"], dict(one["units"])) for one in match.revealed
        ),
        caption=caption,
    )


def board_brief(engine: "RulesEngine", match: "MatchState", seat: str, caption: str = "") -> BoardBrief:
    """
    A seat's own board -- **that seat's alone** (TNP 5.2): its pool, what
    is built, and its queue -- in Infrastructure and Deployment the queue
    its saved plan holds and the pool less what that costs, after it what
    was paid for -- with the supply left.
    """
    from tnp.components import PLAN
    from tnp.turn import supply_room

    from tnp.turn import normal_plan, plan_cost

    state = match.seat(seat)
    queued_units = dict(state.queued_units)
    queued = set(state.queued)
    pool = {key: int(state.pool.get(key, 0)) for key in POOL}
    if match.phase == PLAN and state.plan:
        queued_units = dict(state.plan.get("build", {}))
        queued = set(state.plan.get("structures", []))
        # What the plan's Infrastructure would leave: the pool the board
        # shows goes down as the plan is changed (the author, 2026-11-06).
        cost = plan_cost(engine, normal_plan(state.plan))
        pool["materials"] -= cost.materials
        pool["gold"] -= cost.gold
    room = supply_room(engine, match, seat)
    return BoardBrief(
        seat=seat,
        pool=pool,
        built=frozenset(state.built),
        queued=frozenset(queued),
        queued_units=queued_units,
        supply_left={slug: room[slug] - queued_units.get(slug, 0) for slug in room},
        caption=caption,
    )


# -- Deployment (TNP 2.5, 5.3) ---------------------------------------------------------

#: A spot's state on the public deployment boards: a pile face down, a
#: pile March has shown, or nothing in the spot.
FACE_DOWN, SHOWN, EMPTY = "face_down", "shown", "empty"


@dataclass(frozen=True)
class DeploySpot:
    """One spot of a seat's deployment board as one picture draws it."""

    #: "A", "B", "C", "1", "2", "3", or "base".
    spot: str
    #: The territory or base its card names -- `None` where the picture
    #: may not say (a face-down pile on the public boards) or nothing is
    #: there.
    area: Optional[str] = None
    #: Who holds `area` (`None`: neutral), and whether a ground unit has a
    #: path to it now -- the seat's own board's, for an attack.
    held_by: Optional[str] = None
    path: Optional[bool] = None
    units: Mapping[str, int] = field(default_factory=dict)
    state: str = EMPTY


@dataclass(frozen=True)
class DeploymentBrief:
    """
    **A seat's own attack board** (TNP 2.5), drawn from its saved plan --
    that seat's alone until March: each attack spot and its target, the
    three defense spots, the base's, the units still at the base, and
    what is queued and so not deployable yet. `picked` is the spot the
    panel is changing, ringed.
    """

    seat: str
    attacks: tuple[DeploySpot, ...] = ()
    defenses: tuple[DeploySpot, ...] = ()
    base: DeploySpot = DeploySpot("base")
    at_base: Mapping[str, int] = field(default_factory=dict)
    queued: Mapping[str, int] = field(default_factory=dict)
    picked: Optional[str] = None
    caption: str = ""


@dataclass(frozen=True)
class SpotsBrief:
    """**Both seats' deployment boards as everybody may see them** in
    March (TNP 5.4): which spots hold a pile, face down, and what March
    has shown of each pile it has reached -- never a face-down pile's
    units or its territory."""

    seats: tuple[tuple[str, tuple[DeploySpot, ...]], ...] = ()
    caption: str = ""


def deployment_brief(engine: "RulesEngine", match: "MatchState", seat: str,
                     picked: Optional[str] = None, caption: str = "") -> DeploymentBrief:
    """
    A seat's attack board from the plan saved on the match -- **that
    seat's alone** (TNP 5.3): its attack spots with their targets, who
    holds each and whether a ground unit has a path there now, its
    defended territories in number order as defense spots 1 to 3, its
    base's spot, and what is left at the base.
    """
    from tnp.components import DEFENSE_SPOTS
    from tnp.turn import area_order, attack_spots, base_of, deployed, has_path, normal_plan

    state = match.seat(seat)
    plan = normal_plan(state.plan)
    attacks = []
    for spot in attack_spots(match):
        attack = plan["attacks"].get(spot)
        if attack is None:
            attacks.append(DeploySpot(spot))
            continue
        target = attack["target"]
        attacks.append(DeploySpot(
            spot, target, match.controller(target), has_path(engine, match, seat, target),
            dict(attack["units"]), FACE_DOWN,
        ))
    defended = sorted((area for area in plan["defense"] if area != base_of(seat)), key=area_order)
    defenses = [
        DeploySpot(str(index + 1), area, seat, None, dict(plan["defense"][area]), FACE_DOWN)
        for index, area in enumerate(defended)
    ]
    defenses += [DeploySpot(str(index + 1)) for index in range(len(defenses), DEFENSE_SPOTS)]
    base_units = plan["defense"].get(base_of(seat), {})
    base = DeploySpot("base", base_of(seat), seat, None, dict(base_units), FACE_DOWN if base_units else EMPTY)
    going = deployed(plan)
    at_base = {
        slug: count - going.get(slug, 0) for slug, count in state.available.items()
        if count - going.get(slug, 0) > 0
    }
    return DeploymentBrief(
        seat=seat, attacks=tuple(attacks), defenses=tuple(defenses), base=base,
        at_base=at_base, queued={slug: count for slug, count in plan["build"].items() if count},
        picked=picked, caption=caption,
    )


def spots_brief(engine: "RulesEngine", match: "MatchState", caption: str = "") -> SpotsBrief:
    """
    Both seats' deployment boards in March, as everybody may see them
    (TNP 5.3, 5.4). An attack spot is face down while its pile waits,
    shown once March has revealed it -- what was revealed, at its
    territory -- and empty otherwise: a pile that resolved unrevealed has
    left its spot, home or into the territory's defense spot (TNP 5.3,
    5.5). The defense piles are the piles in territories' defense spots
    that no revealed attack of the seat's put there and no Stranded token
    holds, each face down, with no territory, until a battle reveals it
    -- an air pile waiting where it took nothing among them, as it waits
    there face down; the base's spot the same.
    """
    from tnp.components import DEFENSE_SPOTS
    from tnp.turn import area_order, attack_spots, base_of

    seats = []
    for seat in ("blue", "green"):
        shown: dict[tuple[str, str], dict[str, int]] = {}
        for one in match.revealed:
            if one["seat"] != seat:
                continue
            key = (one["spot"], one["area"])
            units = shown.setdefault(key, {})
            for slug, count in one["units"].items():
                units[slug] = max(units.get(slug, 0), int(count))
        attacked_at = {area for (spot, area) in shown if spot != DEFENSE}
        waiting = match.attacks.get(seat, {})
        resolving = match.resolving or {}
        if seat in (resolving.get("piles") or {}):
            # The pile March is resolving is its attack spot's still.
            attacked_at.add(resolving.get("area"))
        spots = []
        for spot in attack_spots(match):
            revealed = [(area, units) for (where, area), units in shown.items() if where == spot]
            if revealed:
                area, units = revealed[-1]
                spots.append(DeploySpot(spot, area, match.controller(area), None, units, SHOWN))
            elif spot in waiting or (resolving.get("spot") == spot and seat in (resolving.get("piles") or {})):
                spots.append(DeploySpot(spot, state=FACE_DOWN))
            else:
                spots.append(DeploySpot(spot))
        defended = []
        for area in sorted(match.spots, key=area_order):
            if area == base_of(seat) or area in attacked_at:
                continue
            pile = match.spots[area].get(seat)
            if pile is None or pile.empty() or seat in match.areas[area].stranded:
                continue
            units = shown.get((DEFENSE, area))
            defended.append(
                DeploySpot("", area, seat, None, units, SHOWN) if units else DeploySpot("", state=FACE_DOWN)
            )
        # The face-down piles after the shown ones, so their order says
        # nothing of where they are.
        defended.sort(key=lambda one: one.state != SHOWN)
        for index, one in enumerate(defended):
            spots.append(DeploySpot(str(index + 1), one.area, one.held_by, None, one.units, one.state))
        spots += [DeploySpot(str(index + 1)) for index in range(len(defended), DEFENSE_SPOTS)]
        base = match.spots.get(base_of(seat), {}).get(seat)
        if base is not None and not base.empty():
            units = shown.get((DEFENSE, base_of(seat)))
            spots.append(DeploySpot("base", base_of(seat), seat, None, units or {}, SHOWN if units else FACE_DOWN))
        else:
            spots.append(DeploySpot("base"))
        seats.append((seat, tuple(spots)))
    return SpotsBrief(seats=tuple(seats), caption=caption)
