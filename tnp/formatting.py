"""
Plain-text wording over TNP's data, with no Discord in it: what
`/tnp unit` answers, and since step 5 the table's lines -- the turn, the
phase and who has locked in -- and a pool in words. The words are the
model's (CLAUDE.md, "The model and the Discord layer", principle 5); the
cog only posts them, rendering the seat tokens at its door.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Mapping, Optional

from tnp import tokens
from tnp.catalog import Catalog, Cost, Rating, UnitType

if TYPE_CHECKING:
    from tnp.components import MatchState
    from tnp.engine import RulesEngine

#: A trait's name, as the glossary has it (docs/tnp-rules.md, 7).
TRAIT_NAMES = {
    "base_defense": "Base Defense",
    "mechanical": "Mechanical",
    "harvest": "Harvest",
    "repair": "Repair",
    "scouting": "Scouting",
    "tough": "Tough",
    "splash": "Splash damage",
    "transformation": "Transformation",
    "transport": "Transport",
}

TYPE_NAMES = {
    UnitType.INFANTRY: "infantry",
    UnitType.ARMORED: "armored",
    UnitType.AIR: "air",
}


def cost_text(cost: Cost) -> str:
    """"3 materials", "1 material and 1 gold", "nothing"."""
    parts = []
    if cost.materials:
        parts.append(f"{cost.materials} material{'s' if cost.materials != 1 else ''}")
    if cost.gold:
        parts.append(f"{cost.gold} gold")
    return " and ".join(parts) or "nothing"


def rating_text(rating: Rating) -> str:
    """A rating with its d12 number (TNP 4.1, 4.3)."""
    if rating is Rating.POOR:
        return "Poor (X: a 12, one die for every two units)"
    if rating is Rating.WEAK:
        return "Weak (a 12)"
    return f"{rating.value.title()} ({rating.shown})"


def trait_text(slug: str, scouting: int) -> str:
    name = TRAIT_NAMES.get(slug, slug.replace("_", " ").title())
    return f"{name} {scouting}" if slug == "scouting" else name


def unit_lines(catalog: Catalog, slug: str) -> list[str]:
    """`/tnp unit`'s answer: the unit's type and facility, its cost, its
    three ratings with their d12 numbers, initiative, traits, supply,
    what builds it, and the unit sheet's own text."""
    unit = catalog.units[slug]
    facility = catalog.facilities[unit.facility]
    builds = f"Built at the {facility.name}"
    if unit.upgrade:
        builds += f", once it has the {catalog.name(unit.upgrade)}"
    if not facility.built_at_start and facility.build_cost is not None:
        builds += f" (the {facility.name} costs {cost_text(facility.build_cost)} to build"
        if facility.requires:
            builds += f" and needs a {catalog.name(facility.requires)}"
        builds += ")"
    attack = " · ".join(
        f"vs {TYPE_NAMES[kind]} {rating_text(unit.rating(kind))}" for kind in UnitType
    )
    traits = ", ".join(trait_text(trait, unit.scouting) for trait in unit.traits) or "none"
    lines = [
        f"**{unit.name}** -- {TYPE_NAMES[unit.type]}",
        f"Cost: {cost_text(unit.cost)}",
        f"Attack: {attack}",
        f"Initiative: {unit.initiative}",
        f"Traits: {traits}",
        f"Supply: {unit.supply}",
        f"{builds}.",
    ]
    if unit.ability:
        lines.append(f"> {unit.ability}")
    return lines


# -- The table (step 5) ----------------------------------------------------------

#: Each phase by its name in the rules (TNP 5.1). Production and Trade
#: is one phase; its production, which the bot runs, is saved apart from
#: the trade the seats answer.
PHASE_NAMES = {
    "plan": "Infrastructure and Deployment",
    "march": "March",
    "production": "Production and Trade",
    "trade": "Production and Trade",
    "cleanup": "Cleanup",
    "over": "The game is over",
}

#: What a seat is doing in a phase that asks both at once, while it has
#: not locked in.
ANSWERING = {"plan": "planning", "trade": "trading"}

#: A pool's parts, in the order the board shows them (TNP 2.2), each
#: with its one and its many.
POOL_WORDS = (
    ("materials", "material", "materials"),
    ("gold", "gold", "gold"),
    ("blue_minerals", "blue mineral", "blue minerals"),
    ("orange_minerals", "orange mineral", "orange minerals"),
    ("gems", "gem", "gems"),
)


def phase_heading(match: "MatchState") -> str:
    """"**Turn 1**: Infrastructure and Deployment" -- the table's first
    line, and the map's caption without the bold."""
    return f"**Turn {match.turn}**: {PHASE_NAMES.get(match.phase, match.phase)}"


def map_caption(match: "MatchState") -> str:
    """"Turn 1 · Infrastructure and Deployment", under the map."""
    return f"Turn {match.turn} · {PHASE_NAMES.get(match.phase, match.phase)}"


def board_caption(match: "MatchState") -> str:
    """"Turn 1", over a player board: the board's header has room for
    the turn, not the phase's name beside the pool."""
    return f"Turn {match.turn}"


def table_lines(engine: "RulesEngine", game, match: "MatchState") -> list[str]:
    """
    The table's lines, public: the turn and the phase, and in a phase
    both seats answer at once (TNP 5.2, 5.3, 5.9) where each seat stands
    -- answering, locked in, or, in the trade, with nothing to trade.
    **Nothing of a plan is in them**: the seat's `locked` is all that is
    read, and which seats are asked, off `pending_prompts`, the one
    reading.
    """
    from tnp.battle import SEATS
    from tnp.prompts import pending_prompts

    lines = [phase_heading(match)]
    if match.winner is not None:
        lines.append(f"{tokens.seat(match.winner)} has won.")
        return lines
    doing = ANSWERING.get(match.phase)
    if doing is None:
        return lines
    asked = {prompt.asked_seat for prompt in pending_prompts(engine, game, match)}
    for seat in SEATS:
        if seat in asked:
            lines.append(f"{tokens.seat(seat)} is {doing}.")
        elif match.seat(seat).locked:
            lines.append(f"{tokens.seat(seat)} has locked in.")
        else:
            lines.append(f"{tokens.seat(seat)} has nothing to trade.")
    return lines


def pool_text(pool: Mapping[str, int]) -> str:
    """"5 materials, 0 gold, 1 blue mineral, 0 orange minerals, 0 gems"
    -- every part, a 0 included, since the pool is the seat's to spend."""
    parts = []
    for key, one, many in POOL_WORDS:
        count = int(pool.get(key, 0))
        parts.append(f"{count} {one if count == 1 else many}")
    return ", ".join(parts)


# -- A seat's panel (step 6) ------------------------------------------------------
#
# The words a seat's own panel shows -- what its prompt offers and what
# it has saved so far -- read off `PendingPrompt.options` and nothing
# else. **Each is its seat's alone**: a plan's words name its units and
# where they go, so they are shown ephemerally to that seat's player and
# never posted.

#: A token kind as a pool names it, by `tnp.components.RESOURCES`' key.
TOKEN_WORDS = {
    "blue_minerals": ("blue mineral", "blue minerals"),
    "orange_minerals": ("orange mineral", "orange minerals"),
    "gems": ("gem", "gems"),
}


def token_text(kind: str, count: int) -> str:
    """"1 gem", "3 blue minerals"."""
    one, many = TOKEN_WORDS.get(kind, (kind, kind))
    return f"{count} {one if count == 1 else many}"


def units_text(units: Mapping[str, int]) -> str:
    """"3 {unit:worker}, 1 {unit:mercenary}", or "nothing"."""
    found = [f"{count} {tokens.unit(slug)}" for slug, count in units.items() if count]
    return ", ".join(found) if found else "nothing"


def _cost_words(cost: Mapping[str, int]) -> str:
    return cost_text(Cost(int(cost.get("materials", 0)), int(cost.get("gold", 0))))


def plan_offer_lines(options) -> list[str]:
    """What a plan's options offer, as its seat reads them: the units to
    build, with their cost and the most of each; the facilities and
    upgrades to place; the units at the base; the attack spots, and
    where a ground unit has a path now (TNP 5.2, 5.3)."""
    lines = []
    if options.build:
        lines.append("Build: " + "; ".join(
            f"{tokens.unit(one.unit)} ({cost_text(Cost(one.materials, one.gold))}, up to {one.most})"
            for one in options.build
        ) + ".")
    if options.structures:
        lines.append("Place: " + "; ".join(
            f"{tokens.thing(one.structure)} ({cost_text(Cost(one.materials, one.gold))})"
            for one in options.structures
        ) + ".")
    available = {slug: count for slug, count in options.available.items() if count}
    if available:
        lines.append(f"At your base, to deploy: {units_text(available)}.")
    if options.spots:
        line = f"Attack spots: {', '.join(options.spots)}"
        reached = [one.area for one in options.targets if one.path]
        if reached:
            line += "; a ground unit has a path now to " + ", ".join(tokens.area(area) for area in reached)
        lines.append(line + ".")
    return lines


def plan_lines(options) -> list[str]:
    """
    The plan a seat has saved, in words (TNP 5.2, 5.3): what it builds
    and places, each attack spot's units and target, each defense, and
    what its Infrastructure costs against the pool. "Nothing yet" where
    nothing is saved.
    """
    plan = options.plan or {}
    build = plan.get("build") or {}
    structures = plan.get("structures") or []
    attacks = plan.get("attacks") or {}
    defense = plan.get("defense") or {}
    if not (build or structures or attacks or defense):
        return ["Your plan: nothing yet."]
    lines = ["Your plan:"]
    lines.append(f"- Build: {units_text(build)}.")
    if structures:
        lines.append("- Place: " + ", ".join(tokens.thing(slug) for slug in structures) + ".")
    for spot in options.spots:
        attack = attacks.get(spot)
        if attack:
            lines.append(f"- Attack {spot}: {units_text(attack['units'])} at {tokens.area(attack['target'])}.")
        else:
            lines.append(f"- Attack {spot}: nothing.")
    for area, units in defense.items():
        lines.append(f"- Defend {tokens.area(area)}: {units_text(units)}.")
    pool = options.pool
    lines.append(
        f"- It costs {_cost_words(options.cost)}; the pool holds "
        f"{cost_text(Cost(int(pool.get('materials', 0)), int(pool.get('gold', 0))))}."
    )
    return lines


def _rate_words(rates: Mapping[str, Mapping[str, Optional[int]]], kind: str) -> str:
    rate = rates["gem" if kind == "gems" else "mineral"]
    one = TOKEN_WORDS.get(kind, (kind, kind))[0]
    return f"a {one} for {rate['materials']} materials or {rate['gold']} gold"


def trade_lines(options) -> list[str]:
    """A seat's trade (TNP 5.9): the tokens it holds and their rates,
    and what it has saved so far and what that gains."""
    held = {kind: count for kind, count in options.tokens.items() if count}
    lines = ["To trade: " + ", ".join(token_text(kind, count) for kind, count in held.items()) + "."]
    lines.append("Rates: " + "; ".join(_rate_words(options.rates, kind) for kind in held) + ".")
    trade = options.trade or {}
    parts = []
    for into in ("materials", "gold"):
        for kind, count in (trade.get(into) or {}).items():
            if count:
                parts.append(f"{token_text(kind, count)} for {into}")
    if parts:
        lines.append(f"Your trade: {', '.join(parts)} -- gaining {_cost_words(options.gains)}.")
    else:
        lines.append("Your trade: nothing yet. Tokens not traded stay in the pool.")
    return lines
