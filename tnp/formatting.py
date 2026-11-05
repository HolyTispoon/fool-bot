"""
Plain-text wording over TNP's data, with no Discord in it: what
`/tnp unit` answers. The words are the model's (CLAUDE.md, "The model
and the Discord layer", principle 5); the cog only posts them.
"""

from __future__ import annotations

from tnp.catalog import Catalog, Cost, Rating, UnitType

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
