"""
Plain-text wording over TNP's data, with no Discord in it: what
`/tnp unit` answers, and since step 5 the table's lines -- the turn, the
phase and who has locked in -- and a pool in words. The words are the
model's (CLAUDE.md, "The model and the Discord layer", principle 5); the
cog only posts them, rendering the seat tokens at its door.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Mapping

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
