"""
What happens to the things on the table, whatever did it: damage onto a
unit, a hero or a building, a repair, a card destroyed or sacrificed or
returned to its owner's hand, control changing hands, a patroller
sidelined -- and `settle`, the position's own consequences, run after
anything that may have changed them: a unit or hero with damage equal
to its HP or with 0 HP is destroyed, a channeling spell whose hero is
gone is sacrificed, Two Step is sacrificed when a partner leaves.

Combat (`codex.flow.combat`) and the effects (`codex.flow.resolve`) both
come here, so a card destroyed by The Boot dies exactly as one destroyed
in combat does -- to its owner's discard, with the scavenger's gold or
the technician's card (The Boot's ruling: "Anything that triggers on
'dies' ... will trigger"). Each function changes the match and adds its
lines to the `StepResult` it is handed; nothing here asks anything.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable, Optional

from codex import effects, tokens
from codex.components import TECH_BUILDINGS, CardInstance, HeroState, MatchState, hero_ref, is_hero_ref
from codex.engine import (
    BASE_HP,
    BUILDING_DESTROYED_DAMAGE,
    LEVELS_FOR_A_KILL,
    SCAVENGER_GOLD,
    SUMMONING_RUNES_ON_DEATH,
    TECHNICIAN_CARDS,
    building_name,
    unit_ref,
)
from codex.flow.result import StepResult
from codex.flow.turn import damage_base, draw_cards, gain_gold

if TYPE_CHECKING:
    from codex.engine import RulesEngine


def named(match: MatchState, seat: int, ref: str, *, whose: bool = True) -> str:
    """
    A thing on the table in a line, with its side named -- both decks are
    the same ten starters, so "Tenderfoot attacks Tenderfoot" says
    nothing -- or without (`whose=False`) where the line has just said
    whose it is: "{player:2}'s {card:iron_man}", "{player:1}'s Tech II
    building", "{player:2}'s base".
    """
    owner = f"{tokens.player(seat)}'s " if whose else ""
    player = match.player(seat)
    if is_hero_ref(ref):
        hero = player.hero_by_ref(ref)
        if hero is not None:
            return f"{owner}{tokens.hero(hero.slug)}"
    instance_id = unit_ref(ref)
    if instance_id is not None:
        card = player.instance(instance_id)
        if card is not None:
            return f"{owner}{tokens.card(card.slug)}"
    if ref == "add_on" and player.add_on is not None:
        return f"{tokens.player(seat)}'s {tokens.card(player.add_on.slug)}"
    if ref in TECH_BUILDINGS:
        return f"{tokens.player(seat)}'s {building_name(ref)} building"
    return f"{tokens.player(seat)}'s {building_name(ref)}"


def body_of(match: MatchState, seat: int, ref: str):
    """The unit or hero `ref` names on `seat`'s side, or `None` -- a
    building, or something no longer in play."""
    player = match.player(seat)
    if is_hero_ref(ref):
        hero = player.hero_by_ref(ref)
        return hero if hero is not None and hero.in_play else None
    instance_id = unit_ref(ref)
    return None if instance_id is None else player.instance(instance_id)


def is_building(ref: str) -> bool:
    return ref in TECH_BUILDINGS or ref in ("add_on", "base")


def still_there(match: MatchState, seat: int, ref: str) -> bool:
    """Whether what `ref` named on `seat`'s side is still there to be
    attacked: a unit or hero in play, a building standing."""
    player = match.player(seat)
    if ref == "base":
        return player.base_hp > 0
    if ref == "add_on":
        return player.add_on is not None
    if ref in TECH_BUILDINGS:
        building = player.buildings[ref]
        return building is not None and not building.destroyed
    return body_of(match, seat, ref) is not None


# -- Damage --------------------------------------------------------------------


def take_damage(body, amount: int) -> int:
    """Damage onto a unit or hero, its armor first; what landed."""
    absorbed = min(body.armor, amount)
    body.armor -= absorbed
    landed = amount - absorbed
    body.damage += landed
    return landed


def damage_building(match: MatchState, seat: int, ref: str, amount: int,
                    result: StepResult) -> None:
    """Damage onto a building: the base (at 0 the game ends), a tech
    building or the add-on, a destroyed one dealing its 2 to its base
    (UMR p. 8, 9)."""
    player = match.player(seat)
    if ref == "base":
        damage_base(match, seat, amount, result)
        return
    if ref in TECH_BUILDINGS:
        building = player.buildings[ref]
        building.hp = max(0, building.hp - amount)
        if building.hp == 0:
            building.destroyed = True
            building.under_construction = False
            result.narration.append(
                f"{tokens.player(seat)}'s {building_name(ref)} building is destroyed, "
                f"and deals {BUILDING_DESTROYED_DAMAGE} to their base."
            )
            match.record_event("building_destroyed", owner=seat, building=ref)
            damage_base(match, seat, BUILDING_DESTROYED_DAMAGE, result)
        return
    add_on = player.add_on
    add_on.hp = max(0, add_on.hp - amount)
    if add_on.hp == 0:
        player.add_on = None
        result.narration.append(
            f"{tokens.player(seat)}'s {tokens.card(add_on.slug)} is destroyed, "
            f"and deals {BUILDING_DESTROYED_DAMAGE} to their base."
        )
        match.record_event("building_destroyed", owner=seat, building=add_on.slug)
        damage_base(match, seat, BUILDING_DESTROYED_DAMAGE, result)


def building_max_hp(engine: "RulesEngine", match: MatchState, seat: int, ref: str) -> int:
    player = match.player(seat)
    if ref == "base":
        return BASE_HP
    if ref == "add_on":
        return engine.building_hp(player.add_on.slug)
    return engine.building_hp(ref)


def building_hp(match: MatchState, seat: int, ref: str) -> int:
    player = match.player(seat)
    if ref == "base":
        return player.base_hp
    if ref == "add_on":
        return player.add_on.hp
    return player.buildings[ref].hp


def repair_building(engine: "RulesEngine", match: MatchState, seat: int, ref: str,
                    amount: int) -> int:
    """Repair up to `amount` damage on a building, never above its
    maximum HP (Brick Thief's ruling); what was repaired."""
    player = match.player(seat)
    most = building_max_hp(engine, match, seat, ref)
    before = building_hp(match, seat, ref)
    after = min(most, before + amount)
    if ref == "base":
        player.base_hp = after
    elif ref == "add_on":
        player.add_on.hp = after
    else:
        player.buildings[ref].hp = after
    return after - before


# -- Leaving play -------------------------------------------------------------------


def is_token(engine: "RulesEngine", slug: str) -> bool:
    return engine.catalog.cards[slug].kind == "token"


def leave_play(engine: "RulesEngine", match: MatchState, card: CardInstance, to: str) -> None:
    """
    `card` out of play to its **owner's** `to` -- "discard" or "hand"; a
    token is trashed wherever it goes, never entering a hand, a deck or a
    discard pile.
    """
    match.player(card.controller).play.remove(card)
    if is_token(engine, card.slug):
        return
    owner = match.player(card.owner)
    if to == "hand":
        owner.hand.append(card.slug)
    else:
        owner.discard.append(card.slug)


def _destroy_unit(engine: "RulesEngine", match: MatchState, seat: int, card: CardInstance,
                  result: StepResult, by: str = "") -> None:
    if by:
        line = f"{by} destroys {named(match, seat, card.ref)}."
    else:
        line = f"{named(match, seat, card.ref)} is destroyed."
    leave_play(engine, match, card, "discard")
    match.record_event("destroyed", slug=card.slug, owner=card.owner)
    if card.patrol_slot == "scavenger":
        gained = gain_gold(match, card.controller, SCAVENGER_GOLD)
        line += f" As scavenger, it gives {tokens.player(card.controller)} {tokens.gold(gained)}."
    elif card.patrol_slot == "technician":
        drawn = draw_cards(engine, match, card.controller, TECHNICIAN_CARDS, result)
        if drawn:
            line += f" As technician, it draws {tokens.player(card.controller)} a card."
    result.narration.append(line)


def _destroy_hero(match: MatchState, seat: int, hero: HeroState, result: StepResult,
                  by: str = "") -> None:
    ref = hero_ref(hero.slug)
    line = (
        f"{named(match, seat, ref)} dies and returns to the command zone with "
        f"{SUMMONING_RUNES_ON_DEATH} summoning runes."
    )
    if by:
        line = f"{by} destroys {named(match, seat, ref)}, which returns to the command zone with {SUMMONING_RUNES_ON_DEATH} summoning runes."
    hero.zone = "command"
    hero.level = 1
    hero.damage = 0
    hero.exhausted = False
    hero.arrived_this_turn = False
    hero.attacked_this_turn = False
    hero.patrol_slot = None
    hero.armor = 0
    hero.plus_runes = 0
    hero.minus_runes = 0
    hero.modifiers = []
    hero.max_level_since_turn_began = False
    hero.summoning_runes = SUMMONING_RUNES_ON_DEATH
    match.record_event("hero_died", slug=hero.slug, owner=seat)
    result.narration.append(line)


def destroy(engine: "RulesEngine", match: MatchState, things: Iterable[tuple[int, str]],
            result: StepResult, by: str = "", cause: Optional[int] = None) -> None:
    """
    Destroy each of these units and heroes -- a unit face-down to its
    owner's discard pile, a hero to the command zone -- and give the
    kill's two levels to a hero of the opposing side's in play: "When you
    destroy an opponent's hero, one of your heroes immediately gains 2
    levels" (UMR p. 10). `cause` is the seat whose effect destroyed them,
    where an effect did; a hero its own controller's effect destroyed
    (Wither on your own River) gives nobody levels. Combat passes none:
    there each side's hero falls to the other side.

    "A hero must be in play to gain levels. If you have multiple heroes
    in play, choose one hero to gain the levels" (p. 10): with one in
    play it gains them at once, with none nobody does, and with more
    than one the active player is asked (`level_gain_owed`, a frame put
    at the front of the stack, so nothing else resolves before it).
    """
    things = list(things)
    heroes = []
    for seat, ref in things:
        if is_hero_ref(ref):
            hero = match.player(seat).hero_by_ref(ref)
            if hero is not None and hero.in_play:
                _destroy_hero(match, seat, hero, result, by)
                heroes.append(seat)
            continue
        card = body_of(match, seat, ref)
        if card is not None:
            _destroy_unit(engine, match, seat, card, result, by)
    for seat in heroes:
        if cause == seat:
            continue
        victor = match.opponent(seat)
        standing = victor.heroes_in_play
        if not standing:
            continue
        if len(standing) > 1:
            level_gain_owed(match, victor.seat)
            continue
        gain_kill_levels(engine, match, standing[0], result)


#: The frame the kill's levels wait on where the victor has more than
#: one hero in play (`codex.prompts`' `LEVEL_GAIN`).
LEVEL_GAIN = "level_gain"


def level_gain_owed(match: MatchState, seat: int) -> None:
    """Two levels owed to one of `seat`'s heroes, asked of the active
    player before anything else on the stack resolves."""
    match.resolving.insert(0, {"kind": LEVEL_GAIN, "seat": seat, "asked": match.active})


def gain_kill_levels(engine: "RulesEngine", match: MatchState, victor: HeroState,
                     result: StepResult) -> None:
    """The kill's two levels for `victor`, to its maximum, said."""
    before = victor.level
    reached = raise_level(engine, victor, LEVELS_FOR_A_KILL)
    if victor.level > before:
        gained = victor.level - before
        line = (
            f"{tokens.hero(victor.slug)} gains {gained} "
            f"level{'' if gained == 1 else 's'} for the kill: level {victor.level}"
        )
        line += ", a new band, and healed." if reached else "."
        result.narration.append(line)


def raise_level(engine: "RulesEngine", hero: HeroState, levels: int) -> bool:
    """Up to `levels` levels for `hero`, to its maximum, healing it if it
    reaches a new band (UMR p. 6). Returns whether it reached one."""
    card = engine.hero_card(hero)
    before = card.band(hero.level).min_level
    hero.level = min(card.max_level, hero.level + levels)
    reached = card.band(hero.level).min_level != before
    if reached:
        hero.damage = 0
    return reached


def sacrifice(engine: "RulesEngine", match: MatchState, card: CardInstance) -> None:
    """A card of yours out of play to its owner's discard pile -- not a
    death, so nothing that pays on one pays."""
    leave_play(engine, match, card, "discard")
    match.record_event("sacrificed", slug=card.slug, owner=card.owner)


def gain_control(match: MatchState, card: CardInstance, seat: int) -> bool:
    """
    `seat` takes control of `card` -- the owner stays who it was. It comes under its new controller as a card does that
    arrived: out of the patrol zone, with arrival fatigue (the arrival
    fatigue ruling: "if the card is not under your control since the very
    beginning of your turn, it has arrival fatigue"). Returns whether
    control changed; a card already theirs stays as it is (Final Smash's
    ruling: it "does nothing").
    """
    if card.controller == seat:
        return False
    match.player(card.controller).play.remove(card)
    card.controller = seat
    card.patrol_slot = None
    card.armor = 0
    card.arrived_this_turn = True
    match.player(seat).play.append(card)
    match.record_event("gained_control", slug=card.slug, by=seat)
    return True


def sideline(body) -> None:
    """Out of the patrol zone, and with it the squad leader's armor."""
    body.patrol_slot = None
    body.armor = 0


# -- The position's own consequences ----------------------------------------------


def _lethal(engine: "RulesEngine", match: MatchState, body) -> bool:
    hp = engine.body_stats(match, body)[1]
    return hp <= 0 or body.damage >= hp


def settle(engine: "RulesEngine", match: MatchState, result: StepResult,
           cause: Optional[int] = None) -> None:
    """
    Everything the position now requires, until nothing more does: a
    unit or hero at 0 HP or with damage equal to its HP is destroyed --
    through armor, which prevents damage and not a loss of HP (Discord's
    and Wither's rulings) -- a channeling spell whose controller has lost
    its hero is sacrificed ("If at any moment you don't control the
    correct hero for a channeling spell, you sacrifice the channeling
    spell"), and Two Step is sacrificed once either partner has left play
    or its controller's control ("If you lose one, sacrifice Two Step").
    A grant that ended -- Grounded Guide gone -- can kill this way too.
    `cause` is the seat whose effect led here, for a hero's kill levels
    (`destroy`).
    """
    while True:
        dead = []
        for player in match.players:
            for card in player.play:
                if engine.catalog.cards[card.slug].is_unit and _lethal(engine, match, card):
                    dead.append((player.seat, card.ref))
            for hero in player.heroes_in_play:
                if _lethal(engine, match, hero):
                    dead.append((player.seat, hero_ref(hero.slug)))
        if dead:
            destroy(engine, match, dead, result, cause=cause)
            continue
        gone = _sacrifice_due(engine, match)
        if gone is None:
            return
        card, why = gone
        line = f"{named(match, card.controller, card.ref)} is sacrificed: {why}."
        sacrifice(engine, match, card)
        result.narration.append(line)


def _sacrifice_due(engine: "RulesEngine", match: MatchState) -> Optional[tuple[CardInstance, str]]:
    for player in match.players:
        for card in player.play:
            spec = effects.CHANNELING.get(card.slug)
            if spec is not None:
                if not any(
                    (engine.hero_card(hero).spec or "").lower() == spec
                    for hero in player.heroes_in_play
                ):
                    return card, f"its controller has no {spec.title()} hero"
            if card.slug == effects.TWO_STEP:
                if any(player.instance(partner) is None for partner in card.attached):
                    return card, "a dance partner is gone"
    return None


__all__ = [
    "LEVEL_GAIN", "body_of", "building_hp", "building_max_hp", "damage_building", "destroy",
    "gain_kill_levels", "level_gain_owed",
    "gain_control", "is_building", "leave_play", "named", "raise_level",
    "repair_building", "sacrifice", "settle", "sideline", "still_there", "take_damage",
]
