"""
**What each technology card does**, as data (docs/tnp-rules.md, 8) --
the way `codex/effects.py` holds Codex's cards: `EFFECTS`, one `Effect`
a card, which the turn and the battle read, and `UNIMPLEMENTED`, the
cards whose text leaves a rules question the author has not answered
yet, each with its question. A card in `UNIMPLEMENTED` is still a
mineral or a gem: it is drawn, held and traded (TNP 8.1), but never put
into play, and the refusal says why.

A modifier is the author's d12 value (docs/tnp-bot.md, "The dice
modifiers, for the d12"; TNP 8.5), never the sheet's d6 number, and
`tests/test_tnp_effects.py` holds each against the rules' table.

The readings at the foot turn the cards a seat has in play -- its tech
facilities and its building techs, each attached to a production
facility -- into what the turn reads (the attack spots, the trade rates,
the harvest, the discounts) and into what a battle is handed as it opens
(`battle_effects`): the modifier rows `tnp.battle.outside_modifier`
adds up, and the `BattleState.effects` record the battle's own readings
consult. A tactic card adds its own to the battle once Tactical Command
reveals it (`add_tactic`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable, Mapping, Optional

if TYPE_CHECKING:
    from tnp.components import MatchState, SeatState
    from tnp.engine import RulesEngine

#: The three kinds of card (TNP 8.2 to 8.4), as the Technology tab's
#: type column names them.
TACTIC = "tactic"
BUILDING_TECH = "building_tech"
TECH_FACILITY = "tech_facility"

#: What a card is as a mineral or a gem (TNP 8.1): its deck's resource,
#: and the conversion rates' key.
DECK_RATE = {"blue_minerals": "mineral", "orange_minerals": "mineral", "gems": "gem"}

#: A modifier against the base: a base card, or a Base Defense unit
#: (Explosives, "vs. base defense or when targeting base").
BASE = "base"


@dataclass(frozen=True)
class Effect:
    """
    What one card does. Every field is optional; a card sets those its
    text names.

    - **Which units**: `units` names them; a building tech's are the
      units its facility builds (`attached`), and `mechanical` keeps the
      Mechanical ones among them. A tactic card whose `units` are not in
      the battle on its seat's side is discarded without effect (TNP 8.2).
    - **In a battle**: `modifier` added to each die (TNP 4.2), `against`
      a target type or `BASE`, `None` for every roll; `initiative` added
      to the units' initiative; `traits` they gain; each hit on them
      removing `hit_kills` units; `cloaked`, that an unengaged force of
      them cannot be targeted; `scouting` added to the seat's total;
      `rerolls`, dice the seat may roll again each battle; `salvage`, a
      material for each Mechanical unit destroyed, at most `max` a
      battle or a round (`per`).
    - **In the turn**: `spot`, an attack spot it opens (TNP 2.5);
      `rates`, a mineral's trade for materials or gold (TNP 5.9);
      `harvest`, the tokens a Worker takes (TNP 5.8); `discount`, off
      each unit's materials, to at least 1 -- `everywhere` for every
      facility, else the one it is attached to; `production_gold`, gold
      each time its facility produces; `carriers`, Improved Carrier
      Capacity (TNP 7).
    """

    units: tuple[str, ...] = ()
    attached: bool = False
    mechanical: bool = False
    modifier: int = 0
    against: Optional[str] = None
    initiative: int = 0
    traits: tuple[str, ...] = ()
    hit_kills: int = 0
    cloaked: bool = False
    scouting: int = 0
    rerolls: int = 0
    salvage: Optional[tuple[str, int]] = None
    spot: Optional[str] = None
    rates: Optional[tuple[str, int]] = None
    harvest: int = 0
    discount: int = 0
    everywhere: bool = False
    production_gold: int = 0
    carriers: bool = False


#: Every card built, by slug. A modifier is the author's d12 value
#: (TNP 8.5).
EFFECTS: Mapping[str, Effect] = {
    # -- Blue minerals: the economy ---------------------------------------------
    "command_and_control_cpu": Effect(spot="C"),
    "salvage_yard": Effect(salvage=("battle", 3)),
    "jeweler": Effect(rates=("gold", 2)),
    "harvesters": Effect(harvest=2),
    "trader": Effect(rates=("materials", 3)),
    "satellite_connection": Effect(scouting=2),
    "salvaging_under_fire": Effect(salvage=("round", 1)),
    "automation": Effect(discount=1),
    "surprisingly_valuable_side_effects": Effect(production_gold=1),
    # -- Orange minerals: the military -------------------------------------------
    "ammo_depos": Effect(rerolls=2),
    "extra_large_ammo_depos": Effect(rerolls=4),
    "improved_carrier_capacity": Effect(carriers=True),
    "jet_engines": Effect(units=("jeep",), traits=("mechanical",), initiative=-1),
    "arm_workers": Effect(units=("worker",), modifier=3),
    "enhancing_drugs": Effect(units=("mercenary",), modifier=4, initiative=-1, hit_kills=2),
    "advanced_targeting": Effect(units=("cyborg_soldier",), modifier=3, against="air"),
    "cloaking": Effect(units=("the_transformer",), cloaked=True),
    "heat_seeking_missile": Effect(units=("viper_spy_plane",), modifier=3),
    # -- Gems: the advanced techs ------------------------------------------------
    "explosives": Effect(units=("stealth_sniper",), modifier=6, against=BASE),
    "aa_missiles": Effect(attached=True, modifier=3, against="air"),
    "lasers": Effect(attached=True, modifier=3, against="armored"),
    "grenades": Effect(attached=True, modifier=3, against="infantry"),
    "radars": Effect(attached=True, mechanical=True, initiative=-2),
    "specialized_training": Effect(attached=True, modifier=2),
    "construction_crane": Effect(discount=1, everywhere=True),
}

#: The cards whose text leaves a question for the author (TNP 8; the
#: preamble's rule: a question goes to the author, never into the code
#: as a guess). Each is still a mineral or a gem, drawn and traded.
UNIMPLEMENTED: Mapping[str, str] = {
    "intelligence_facility": (
        "Whose pile is examined, and who chooses which half of it is seen? Which pile may be "
        "redeployed -- one of the seat's own, anywhere its deployment could have gone? With "
        "both seats holding one, who goes first?"
    ),
    "converters": "When may a mineral card be discarded to draw another: at any time, or in Production and Trade?",
    "rapid_distillation": (
        "Production and Trade is one phase, its production run before the trade: what does "
        "converting a card \"at the beginning of the production phase\" give that the trade "
        "does not?"
    ),
    "research_and_development": (
        "Are the \"advanced technology cards\" drawn from the gems deck? Are the materials "
        "placed on it spent in Infrastructure, and taken off in that turn's Production?"
    ),
    "gathering_resources_under_fire": (
        "A gathered resource is a card drawn in the advanced game: does it count toward the "
        "51% as a token taken off the map, and may it be of any kind the territory holds?"
    ),
    "aggressive_harvesting": (
        "The Workers in the base defense spot join a battle away from the base: do they go "
        "back to the base's spot after it, and do they harvest if it is won?"
    ),
    "snipe": (
        "\"Before the battle starts\" no force is engaged yet: is the Sniper force's chance "
        "before round 1's placing, and who chooses the units removed?"
    ),
    "medic_on_board": (
        "A battle does not record which units a Chopper Carrier carried in: are they all the "
        "Mercenaries and Workers of a pile that needed carrying, or only as many as the "
        "carriers hold?"
    ),
    "aggressive_construction": (
        "Are the 4 Base Defense units paid for, and from the supply? \"Cannot be moved from "
        "this territory defense spot\": do they stay through Cleanup?"
    ),
    "bunkers": (
        "\"Sustain 1 hit as armored\": is the first hit on the force rolled at the attacker's "
        "armored rating, and does a miss there use the hit up?"
    ),
    "attached_mechanics": (
        "Is the Worker removed from the units at the base, or from the base defense spot, "
        "and is that one Worker a hit ignored, as Repair is?"
    ),
    "tactical_maneuvering": (
        "Into which two counts may the force be broken, by whose choice, and do the two "
        "forces join again when the battle ends?"
    ),
    "tactical_nuke": (
        "Both seats share one Production phase: is the Nuke played as it opens, before "
        "either seat's queue is finished, and what does \"(construction, upgrade and "
        "infrastructure)\" let it destroy?"
    ),
    "advanced_robotics": (
        "Moving like air units: may a Transformer pile attack with no path, and may a "
        "Transformer that chose air take a neutral territory it reached with no battle?"
    ),
    "super_cannon": (
        "Is a \"non-building unit\" any unit but a Base Defense unit, and who chooses which "
        "units are removed after each round?"
    ),
    "exploding_smoke_shells": (
        "\"An adjacent Force\": adjacent to the Tanks, or to the force they hit, as Splash "
        "reads it? And is it a choice, like Splash, or always?"
    ),
}


def built(slug: str) -> bool:
    """Whether a card's effect is built -- it may be put into play."""
    return slug in EFFECTS


def deck_of(engine: "RulesEngine", slug: str) -> str:
    return engine.catalog.techs[slug].deck


def kind_of(engine: "RulesEngine", slug: str) -> str:
    """A card's kind: tactic, building tech or tech facility (TNP 8)."""
    return engine.catalog.techs[slug].type


def rate_key(engine: "RulesEngine", slug: str) -> str:
    """What a card is as a token (TNP 8.1): "mineral" or "gem"."""
    return DECK_RATE[deck_of(engine, slug)]


# -- What a seat has in play ----------------------------------------------------


def in_play(state: "SeatState") -> list[tuple[str, Optional[str]]]:
    """A seat's cards in play: each tech facility, and each building tech
    with the production facility it is attached to (TNP 8.3, 8.4)."""
    found: list[tuple[str, Optional[str]]] = [(slug, None) for slug in state.tech]
    found.extend((slug, facility) for facility, slug in state.attached.items())
    return found


def _effects(state: "SeatState") -> list[tuple[Effect, Optional[str]]]:
    return [(EFFECTS[slug], facility) for slug, facility in in_play(state) if slug in EFFECTS]


def attack_spots(state: "SeatState") -> tuple[str, ...]:
    """The extra attack spots a seat's cards open: C with Command and
    Control CPU (TNP 2.5)."""
    return tuple(sorted({effect.spot for effect, _ in _effects(state) if effect.spot}))


def mineral_rates(state: "SeatState", normal: Mapping[str, int]) -> dict[str, int]:
    """A mineral's trade for materials and for gold (TNP 5.9), raised by
    Jeweler (2 gold) and Trader (3 materials) -- the better of each."""
    found = dict(normal)
    for effect, _ in _effects(state):
        if effect.rates is not None:
            into, value = effect.rates
            found[into] = max(int(found.get(into) or 0), value)
    return found


def harvest_per_worker(state: "SeatState") -> int:
    """Tokens one Worker takes (TNP 5.8): 2 with Harvesters, else 1."""
    return max([1] + [effect.harvest for effect, _ in _effects(state) if effect.harvest])


def unit_discount(engine: "RulesEngine", state: "SeatState", unit: str) -> int:
    """Materials off a unit's cost (Automation at its facility,
    Construction Crane at every one)."""
    facility = engine.unit(unit).facility
    return sum(
        effect.discount for effect, at in _effects(state)
        if effect.discount and (effect.everywhere or at == facility)
    )


def discounted(materials: int, discount: int) -> int:
    """A unit's materials less its discount, to a minimum of 1 -- a unit
    that cost none still costs none."""
    if not discount or materials <= 0:
        return materials
    return max(1, materials - discount)


def production_gold(state: "SeatState", facilities: Iterable[str]) -> int:
    """Gold from the building techs on the facilities that produced
    this turn (Surprisingly valuable side-effects)."""
    producing = set(facilities)
    return sum(
        effect.production_gold for effect, at in _effects(state)
        if effect.production_gold and at in producing
    )


def improved_carriers(state: "SeatState") -> bool:
    return any(effect.carriers for effect, _ in _effects(state))


def carrier_capacity(engine: "RulesEngine", improved: bool) -> Mapping[str, Mapping[str, int]]:
    """Each carrier's capacity by unit carried (TNP 7): the regular
    table, or Improved Carrier Capacity's."""
    board = engine.catalog.board
    return board.get("transport_improved", {}) if improved else board.get("transport", {})


# -- What a battle is handed ----------------------------------------------------


def _units_of(engine: "RulesEngine", effect: Effect, facility: Optional[str],
              traits: Mapping[str, Iterable[str]]) -> tuple[str, ...]:
    """The units an effect names: its own, or its facility's."""
    if effect.attached:
        found = [slug for slug, unit in engine.catalog.units.items() if unit.facility == facility]
    else:
        found = list(effect.units)
    if effect.mechanical:
        found = [
            slug for slug in found
            if "mechanical" in engine.unit(slug).traits or "mechanical" in traits.get(slug, ())
        ]
    return tuple(found)


def _add(engine: "RulesEngine", effects: dict, rows: list, seat: str, slug: str, effect: Effect,
         facility: Optional[str]) -> None:
    """One card's effect into a battle's record and modifier rows."""
    traits = effects.setdefault("traits", {}).setdefault(seat, {})
    units = _units_of(engine, effect, facility, traits)
    for unit in units:
        if effect.modifier:
            rows.append({
                "seat": seat, "unit": unit, "against": effect.against,
                "value": effect.modifier, "card": slug,
            })
        if effect.initiative:
            table = effects.setdefault("initiative", {}).setdefault(seat, {})
            table[unit] = table.get(unit, 0) + effect.initiative
        for trait in effect.traits:
            held = traits.setdefault(unit, [])
            if trait not in held:
                held.append(trait)
        if effect.hit_kills:
            effects.setdefault("hit_kills", {}).setdefault(seat, {})[unit] = effect.hit_kills
        if effect.cloaked:
            cloaked = effects.setdefault("cloaked", {}).setdefault(seat, [])
            if unit not in cloaked:
                cloaked.append(unit)
    if effect.scouting:
        scouting = effects.setdefault("scouting", {})
        scouting[seat] = scouting.get(seat, 0) + effect.scouting
    if effect.rerolls:
        rerolls = effects.setdefault("rerolls", {})
        rerolls[seat] = rerolls.get(seat, 0) + effect.rerolls
    if effect.salvage is not None:
        per, most = effect.salvage
        effects.setdefault("salvage", {}).setdefault(seat, []).append(
            {"card": slug, "per": per, "max": most, "used": 0}
        )
    if effect.carriers:
        carriers = effects.setdefault("carriers", [])
        if seat not in carriers:
            carriers.append(seat)
    if not effects["traits"][seat]:
        del effects["traits"][seat]
    if not effects["traits"]:
        del effects["traits"]


def battle_effects(engine: "RulesEngine", match: "MatchState") -> tuple[list[dict], dict]:
    """
    What both seats' cards in play hand a battle as it opens: the
    modifier rows (`BattleState.modifiers`) and the effects record
    (`BattleState.effects`). Jet Engines' trait is added before Radars
    reads which units are Mechanical, so a jeep with both is both.
    """
    from tnp.battle import SEATS

    rows: list[dict] = []
    effects: dict = {}
    if not match.advanced:
        return rows, effects
    for seat in SEATS:
        state = match.seats.get(seat)
        if state is None:
            continue
        cards = sorted(in_play(state), key=lambda one: bool(EFFECTS.get(one[0], Effect()).mechanical))
        for slug, facility in cards:
            if slug in EFFECTS:
                _add(engine, effects, rows, seat, slug, EFFECTS[slug], facility)
    return rows, effects


def tactic_applies(engine: "RulesEngine", battle, seat: str, slug: str) -> bool:
    """Whether a tactic card's units are in the battle on its seat's
    side (TNP 8.2): a card naming no units always applies."""
    effect = EFFECTS[slug]
    if not effect.units:
        return True
    return any(found.unit in effect.units for found in battle.living(seat))


def add_tactic(engine: "RulesEngine", battle, seat: str, slug: str) -> bool:
    """A revealed tactic card's effect into the battle (TNP 6.3, 8.2);
    `False` where its units are not there, and it does nothing."""
    if not tactic_applies(engine, battle, seat, slug):
        return False
    _add(engine, battle.effects, battle.modifiers, seat, slug, EFFECTS[slug], None)
    return True


__all__ = [
    "BASE", "BUILDING_TECH", "DECK_RATE", "EFFECTS", "Effect", "TACTIC", "TECH_FACILITY",
    "UNIMPLEMENTED", "add_tactic", "attack_spots", "battle_effects", "built", "carrier_capacity",
    "deck_of", "discounted", "harvest_per_worker", "improved_carriers", "in_play", "kind_of",
    "mineral_rates", "production_gold", "rate_key", "tactic_applies", "unit_discount",
]
