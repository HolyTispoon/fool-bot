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

#: A faction's name, as the rules spell it (TNP 1.2).
FACTION_NAMES = {
    "humans": "Humans",
    "xzzzx": "XzzzX",
    "space_dragons": "Space Dragons",
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


#: How a won game was won, on the table (TNP 1.3), by `MatchState.won_by`.
WON_HOW = {
    "base": ": the other seat's base has fallen",
    "harvest": ": 51% of the planet's tokens harvested",
    "concession": ": the other seat conceded",
}


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
        lines.append(f"{tokens.seat(match.winner)} has won{WON_HOW.get(match.won_by, '')}.")
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
    techs = plan.get("techs") or {}
    if not (build or structures or attacks or defense or any(techs.values())):
        return ["Your plan: nothing yet."]
    lines = ["Your plan:"]
    lines.append(f"- Build: {units_text(build)}.")
    if structures:
        lines.append("- Place: " + ", ".join(tokens.thing(slug) for slug in structures) + ".")
    for facility, card in (techs.get("attach") or {}).items():
        lines.append(f"- Attach {tokens.card(card)} to the {tokens.thing(facility)}.")
    for card in techs.get("build") or []:
        lines.append(f"- Build the tech facility {tokens.card(card)}.")
    for card in techs.get("discard") or []:
        lines.append(f"- Discard the tech facility {tokens.card(card)}.")
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


# -- The advanced game's cards (step 9) ------------------------------------------

#: A card's kind and deck as the rules name them (TNP 8).
CARD_KINDS = {"tactic": "tactic card", "building_tech": "building tech", "tech_facility": "tech facility"}
DECK_WORDS = {"blue_minerals": "blue minerals", "orange_minerals": "orange minerals", "gems": "gems"}


def card_kind_text(kind: str) -> str:
    return CARD_KINDS.get(kind, kind)


def hand_text(cards) -> str:
    """A hand in words, off `CardOption`s: "2 {card:grenades}, 1
    {card:jeweler}", or "no cards"."""
    found = [f"{one.count} {tokens.card(one.card)}" for one in cards if one.count]
    return ", ".join(found) if found else "no cards"


def cards_lines(options) -> list[str]:
    """
    A seat's cards in its panel (TNP 8), off a plan prompt's options:
    its hand by kind, what it has in play, and what may be put into play
    -- a card whose effect is not built yet is said to be held and
    traded, never played. **Its own alone.**
    """
    if not getattr(options, "advanced", False):
        return []
    lines = []
    if options.cards:
        for kind in ("tactic", "building_tech", "tech_facility"):
            held = [one for one in options.cards if one.kind == kind]
            if held:
                lines.append(f"Your {card_kind_text(kind)}s: {hand_text(held)}.")
        waiting = [one for one in options.cards if not one.built]
        if waiting:
            lines.append(
                "Not built yet, so held and traded but not played: "
                + ", ".join(tokens.card(one.card) for one in waiting) + "."
            )
    else:
        lines.append("Your hand: no cards. A harvest draws one a token (TNP 8.1).")
    in_play = [tokens.card(slug) for slug in options.tech]
    in_play += [f"{tokens.card(card)} on the {tokens.thing(facility)}" for facility, card in options.attached.items()]
    lines.append(
        f"In play: {', '.join(in_play) if in_play else 'nothing'} "
        f"(at most {options.tech_facilities} tech facilities, one building tech a facility)."
    )
    return lines


def card_trade_lines(options) -> list[str]:
    """An advanced trade (TNP 8.1): the cards held, each a mineral or a
    gem at the seat's rates, and what is saved so far."""
    rates = options.rates
    lines = [f"Your hand: {hand_text(options.cards)}."]
    lines.append(
        f"Rates: a mineral card for {rates['mineral']['materials']} materials or "
        f"{rates['mineral']['gold']} gold; a gem card for {rates['gem']['materials']} materials or "
        f"{rates['gem']['gold']} gold."
    )
    trade = options.trade or {}
    parts = []
    for into in ("materials", "gold"):
        for card, count in (trade.get(into) or {}).items():
            if count:
                parts.append(f"{count} {tokens.card(card)} for {into}")
    if parts:
        lines.append(f"Your trade: {', '.join(parts)} -- gaining {_cost_words(options.gains)}.")
    else:
        lines.append("Your trade: nothing yet. Cards not traded stay in your hand.")
    return lines


def card_lines(catalog: Catalog, slug: str) -> list[str]:
    """
    What `/tnp card` answers (TNP 8): the card's name, its kind and deck,
    how many are in the deck, what a tech facility costs, its text as the
    sheet has it, and what the bot does with it -- its d12 value where it
    changes a roll, or the question its text waits on.
    """
    from tnp.effects import EFFECTS, UNIMPLEMENTED

    tech = catalog.techs[slug]
    lines = [f"**{tech.name}** -- {card_kind_text(tech.type)}, {DECK_WORDS.get(tech.deck, tech.deck)} deck, {tech.count} in the deck."]
    if tech.type == "tech_facility":
        lines.append(f"Costs {plural(int(tech.materials or 0), 'material')}; at most two tech facilities in play.")
    elif tech.type == "building_tech":
        lines.append("Attached to a production facility, one a facility, for the units it builds.")
    else:
        lines.append("Played face down at Tactical Command, for one battle.")
    lines.append(f"*{tech.ability}*")
    effect = EFFECTS.get(slug)
    if effect is not None and effect.modifier:
        against = {"air": "against air", "armored": "against armored", "infantry": "against infantry",
                   "base": "against the base and Base Defense units"}.get(effect.against, "on every roll")
        lines.append(f"On the d12: {_signed(effect.modifier)} {against} (the author's value, TNP 8.5).")
    if slug in UNIMPLEMENTED:
        lines.append(f"Not built yet -- a question to the author: {UNIMPLEMENTED[slug]}")
    lines.append("Any card is also a mineral or a gem, traded at the conversion rates (TNP 8.1).")
    return lines


def find_card(catalog: Catalog, name: str) -> Optional[str]:
    """A card by its slug or its name, any case; `None` where none is."""
    wanted = name.strip().lower().replace("-", " ")
    for slug, tech in catalog.techs.items():
        if wanted in (slug, slug.replace("_", " "), tech.name.lower().replace("-", " ")):
            return slug
    return None


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


# -- A battle's words (step 7) ----------------------------------------------------------

def _signed(value: int) -> str:
    return f"+{value}" if value >= 0 else f"−{-value}"


def modifier_words(parts) -> str:
    """
    Each modifier a roll takes, said with its reason (TNP 4.2): "−1, a
    column across", "−2, 2 columns across", "+1 flanking", "+2 from the
    cards", "+3 {card:grenades}" for a card by its name; "no modifier"
    where there is none. `parts` are
    `tnp.battle.modifier_parts`' rows, `(kind, value, columns)`.
    """
    from tnp.battle import ACROSS, FLANKING

    said = []
    for kind, value, columns in parts:
        if kind == ACROSS:
            said.append(f"{_signed(value)}, " + ("a column across" if columns == 1 else f"{columns} columns across"))
        elif kind == FLANKING:
            said.append(f"{_signed(value)} flanking")
        elif ":" in kind:
            said.append(f"{_signed(value)} {tokens.card(kind.partition(':')[2])}")
        else:
            said.append(f"{_signed(value)} from the cards")
    return "; ".join(said) if said else "no modifier"


def hits_on(target: int, bonus: int) -> str:
    """What a die must show (TNP 4.1, 4.2): "hits on 5+", or "hits only
    on a 12" where nothing less can -- `tnp.battle.needs`."""
    from tnp.battle import needs

    found = needs(target, bonus)
    return "hits only on a 12" if found >= 12 else f"hits on {found}+"


def roll_reason(rating: Rating, against: UnitType, bonus: int, parts) -> str:
    """
    Why a roll needs what it needs, before or after it is made: the
    rating against the target's type with its number, each modifier, and
    what a die must show -- "Fair against infantry, 6+; −1, a column
    across; +1 flanking: each die hits on 6+".
    """
    words = f"{rating.value.title()} against {TYPE_NAMES[against]}, {rating.shown}"
    if parts:
        words += "; " + modifier_words(parts)
    return f"{words}: each die {hits_on(rating.target, bonus)}"


def plural(count: int, one: str, many: Optional[str] = None) -> str:
    return f"{count} {one if count == 1 else (many or one + 's')}"


def battle_heading(battle) -> str:
    """
    A battle's heading on its message (TNP 6): where, which round of the
    six, and who attacks whom -- "**Battle at {area:14}**, round 2 of 6:
    {seat:blue} attacks, {seat:green} defends." -- or, before the sides
    are chosen, that both seats attacked it (TNP 6.1).
    """
    from tnp.battle import ROUNDS

    if battle.outcome is not None:
        when = "over"
    elif battle.round:
        when = f"round {battle.round} of {ROUNDS}"
    else:
        when = "before the first round"
    if battle.attacker and battle.defender:
        sides = f"{tokens.seat(battle.attacker)} attacks, {tokens.seat(battle.defender)} defends."
    else:
        sides = "Both seats attacked it."
    return f"**Battle at {tokens.area(battle.territory)}**, {when}: {sides}"


def battle_force_text(battle, ident: str) -> str:
    """A force or a base card as a battle names it: "{seat:green}'s 4
    {unit:mercenary}", "{seat:green}'s left base card"."""
    from tnp.flow.battle import _target_words

    return _target_words(battle, ident)


def slot_text(battle, seat: str, slot: str) -> str:
    """
    Where a force may be placed (`tnp.battle.slots`), in words: engaging
    the enemy force in a column, a new column at a gap of the line, or
    flanking behind the seat's own force (TNP 6.5). Columns are counted
    from 1 at the left.
    """
    from tnp.battle import COLUMN, ENGAGE, FLANK, other

    kind, _, where = slot.partition(":")
    index = int(where)
    if kind == ENGAGE:
        enemy = battle.line[index].front[other(seat)]
        return f"engage {battle_force_text(battle, enemy)} (column {index + 1})"
    if kind == FLANK:
        own = battle.line[index].front[seat]
        return f"flank behind {battle_force_text(battle, own)} (column {index + 1})"
    if kind == COLUMN:
        columns = len(battle.line)
        if columns == 0:
            return "the first column of the line"
        if index == 0:
            return "a new column at the left end"
        if index >= columns:
            return "a new column at the right end"
        return f"a new column between columns {index} and {index + 1}"
    return slot


def target_text(battle, option) -> str:
    """A target a force may roll at (`tnp.prompts.TargetOption`): what it
    is, the dice and what each must show -- "{seat:green}'s 4
    {unit:mercenary}: 3 dice, each hits on 7+"."""
    words = f"{battle_force_text(battle, option.target)}: {plural(option.dice, 'die', 'dice')}, "
    return words + f"each {hits_on(option.needed, option.modifier)}"


def target_reason(option) -> str:
    """Why a target needs what it does, before the roll (`roll_reason`,
    off the option)."""
    return roll_reason(Rating(option.rating), UnitType(option.type), option.modifier, option.parts)


def battle_offer_lines(prompt) -> list[str]:
    """
    What a battle question offers that its controls cannot say alone,
    off the prompt's options: a placing run -- how many forces the seat
    places before the other places one (TNP 6.5) -- and a retreat with
    no path home, which takes the air units and what the Chopper
    Carriers carry (TNP 6.6, 7).
    """
    from tnp.prompts import PromptKind

    options = prompt.options
    seat = tokens.seat(prompt.asked_seat) if prompt.asked_seat else "This seat"
    if prompt.kind is PromptKind.PLACE_FORCE and options.run > 1:
        return [f"{seat} places {options.run} forces before the other seat places one."]
    if prompt.kind is PromptKind.DECLARE_RETREAT and not options.path_home:
        said = f"{seat} has no path home: a retreat takes its air units"
        if options.carriers:
            said += (
                f", and its {plural(options.carriers, 'Chopper Carrier')} carry what the menus say, "
                "one kind of unit a carrier"
            )
        return [said + "; the rest stay and fight."]
    if prompt.kind is PromptKind.CHOOSE_TARGET:
        return ["Each target in the menu shows its dice, what a die must show and why. "
                "Choosing one rolls at once."]
    if prompt.kind is PromptKind.TACTIC:
        return ["Each seat with a tactic card chooses in secret; the cards are revealed together "
                "and last this battle."]
    if prompt.kind is PromptKind.REROLL:
        return [f"{seat} may roll up to {options.most} of the {options.missed} missed dice again; "
                f"{options.left} reroll{'' if options.left == 1 else 's'} left this battle."]
    return []
