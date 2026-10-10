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
    FUTURE,
    building_name,
    future_ref,
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
    future = future_card(match, seat, ref)
    if future is not None:
        return f"{owner}{tokens.card(future.slug)} in the future"
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


def future_card(match: MatchState, seat: int, ref: str) -> Optional[CardInstance]:
    """The card `ref` names in `seat`'s future (step 12), or `None`."""
    if not isinstance(ref, str) or not ref.startswith(FUTURE):
        return None
    try:
        ident = int(ref[len(FUTURE):])
    except ValueError:
        return None
    return next((card for card in match.player(seat).future if card.id == ident), None)


def timed(match: MatchState, seat: int, ref: str):
    """What carries time runes that `ref` names on `seat`'s side: a card in
    play, a hero in play, or a card in the future."""
    found = body_of(match, seat, ref)
    return found if found is not None else future_card(match, seat, ref)


def is_building(ref: str) -> bool:
    """Whether `ref` names the base, a tech building or the add-on --
    the buildings with no card in play. A building card is a `unit:<id>`
    ref, damaged and destroyed as a card is."""
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


def take_damage(body, amount: int, piercing: bool = False) -> int:
    """Damage onto a unit or hero, its armor first -- unless it is
    armor piercing, which armor prevents nothing of, and which leaves the
    armor for the next damage (UMR p. 16); what landed."""
    if piercing:
        body.damage += amount
        return amount
    absorbed = min(body.armor, amount)
    body.armor -= absorbed
    landed = amount - absorbed
    body.damage += landed
    return landed


def pass_prevents(match: MatchState, seat: int, target) -> bool:
    """
    Morningstar Pass: "Prevent all damage that would be dealt to your other
    buildings." -- `seat`'s base, tech buildings, add-on and building cards
    but the Pass itself, while it is in play with its text (step 13).
    `target` is a ref or a card in play.
    """
    ref = target.ref if isinstance(target, CardInstance) else target
    return any(
        card.slug in effects.PASSES and "polymorph" not in (card.printed or {}) and card.ref != ref
        for card in match.player(seat).play
    )


def damage_building(match: MatchState, seat: int, ref: str, amount: int,
                    result: StepResult, by: Optional[int] = None) -> None:
    """Damage onto a building: the base (at 0 the game ends), a tech
    building or the add-on, a destroyed one dealing its 2 to its base
    (UMR p. 8, 9) -- dealt by `by`, for Blackhand Dozer's floor. None of
    it where Morningstar Pass prevents it (step 13)."""
    player = match.player(seat)
    if pass_prevents(match, seat, ref):
        return
    if ref == "base":
        damage_base(match, seat, amount, result, by=by)
        return
    if ref in TECH_BUILDINGS:
        building = player.buildings[ref]
        building.hp = max(0, building.hp - amount)
        if building.hp == 0:
            building.destroyed = True
            building.under_construction = False
            result.narration.append(
                f"{tokens.player(seat)}'s {building_name(ref)} building is destroyed, "
                f"and deals {BUILDING_DESTROYED_DAMAGE} to their base"
                f"{base_left_after(match, seat, BUILDING_DESTROYED_DAMAGE, by=by)}."
            )
            match.record_event("building_destroyed", owner=seat, building=ref)
            damage_base(match, seat, BUILDING_DESTROYED_DAMAGE, result, by=by)
        return
    add_on = player.add_on
    add_on.hp = max(0, add_on.hp - amount)
    if add_on.hp == 0:
        player.add_on = None
        result.narration.append(
            f"{tokens.player(seat)}'s {tokens.card(add_on.slug)} is destroyed, "
            f"and deals {BUILDING_DESTROYED_DAMAGE} to their base"
            f"{base_left_after(match, seat, BUILDING_DESTROYED_DAMAGE, by=by)}."
        )
        match.record_event("building_destroyed", owner=seat, building=add_on.slug)
        damage_base(match, seat, BUILDING_DESTROYED_DAMAGE, result, by=by)


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


def left_after(engine: "RulesEngine", match: MatchState, seat: int, ref: str,
               amount: int, by: Optional[int] = None) -> str:
    """What a damage line about a building says of what is left, before
    the damage lands: ", now at 2/5", or nothing where the damage
    destroys it -- the next line says so (the author, 2026-10-10)."""
    if ref == "base":
        return base_left_after(match, seat, amount, by=by)
    if pass_prevents(match, seat, ref):
        return _PREVENTED
    left = max(0, building_hp(match, seat, ref) - amount)
    return _now_at(left, building_max_hp(engine, match, seat, ref))


def base_left_after(match: MatchState, seat: int, amount: int,
                    by: Optional[int] = None) -> str:
    """`left_after` for the base: ", now at 17/20" -- where Blackhand
    Dozer's floor holds it (`turn.base_floor`, `by` the seat dealing the
    damage), what the floor leaves (step 12)."""
    from codex.flow.turn import base_floor

    if pass_prevents(match, seat, "base"):
        return _PREVENTED
    left = max(0, match.player(seat).base_hp - amount)
    floor = base_floor(match, seat, by)
    if floor is not None:
        left = max(left, min(match.player(seat).base_hp, floor))
    return _now_at(left, BASE_HP)


def now_at(engine: "RulesEngine", match: MatchState, seat: int, ref: str) -> str:
    """Where a building or a building card stands now -- ", now at 5/5"
    -- for a line that repairs it."""
    if is_building(ref):
        return _now_at(building_hp(match, seat, ref), building_max_hp(engine, match, seat, ref))
    card = body_of(match, seat, ref)
    most = engine.body_stats(match, card)[1]
    return _now_at(most - card.damage, most)


#: What a damage line says where Morningstar Pass prevents the damage.
_PREVENTED = f", which {tokens.card('morningstar_pass')} prevents"


def _now_at(left: int, most: int) -> str:
    return f", now at {left}/{most}" if left > 0 else ""


def card_left(engine: "RulesEngine", match: MatchState, body) -> str:
    """`left_after` for a building card, asked once its damage has landed
    -- a card's damage lands before its line is said; nothing for a unit
    or a hero, or for a building card the damage destroyed."""
    if not isinstance(body, CardInstance) or not engine.catalog.cards[body.slug].is_building_card:
        return ""
    most = engine.body_stats(match, body)[1]
    return _now_at(most - body.damage, most)


def repair_building(engine: "RulesEngine", match: MatchState, seat: int, ref: str,
                    amount: int) -> int:
    """Repair up to `amount` damage on a building, never above its
    maximum HP (Brick Thief's ruling); what was repaired."""
    player = match.player(seat)
    card = body_of(match, seat, ref) if not is_building(ref) else None
    if card is not None:
        # A building card: its damage is what a repair takes off.
        repaired = min(card.damage, amount)
        card.damage -= repaired
        return repaired
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
    _empty_graveyard(match, card)
    if is_token(engine, card.slug):
        return
    owner = match.player(card.owner)
    if to == "hand":
        owner.hand.append(card.slug)
    elif to == "died" and _bury(engine, match, card):
        return
    else:
        owner.discard.append(card.slug)


def _bury(engine: "RulesEngine", match: MatchState, card: CardInstance) -> bool:
    """
    The Graveyard: "Whenever your non-token units die, bury them here" --
    a unit dying under the control of a player with a Graveyard in play
    goes into it, out of play and out of the discard pile, its runes and
    effects gone (its ruling). Whether it was buried.
    """
    if not engine.catalog.cards[card.slug].is_unit:
        return False
    yards = engine.graveyards(match.player(card.controller))
    if not yards:
        return False
    yards[0].buried.append({"slug": card.slug, "owner": card.owner})
    match.record_event("buried", slug=card.slug, owner=card.owner)
    return True


def _empty_graveyard(match: MatchState, card: CardInstance) -> None:
    """A Graveyard leaving play discards what is buried in it, each to its
    owner's discard pile -- and a Jail the unit it holds (step 13: "They're
    discarded if Jail is destroyed")."""
    for buried in card.buried:
        match.player(buried["owner"]).discard.append(buried["slug"])
    card.buried = []
    if card.jailed is not None:
        match.player(card.jailed["owner"]).discard.append(card.jailed["slug"])
        card.jailed = None


def _destroy_unit(engine: "RulesEngine", match: MatchState, seat: int, card: CardInstance,
                  result: StepResult, by: str = "") -> None:
    if by:
        line = f"{by} destroys {named(match, seat, card.ref)}."
    else:
        line = f"{named(match, seat, card.ref)} is destroyed."
    leave_play(engine, match, card, "died")
    match.record_event("destroyed", slug=card.slug, owner=card.owner)
    if card.patrol_slot == "scavenger":
        gained = gain_gold(match, card.controller, SCAVENGER_GOLD)
        line += f" As scavenger, it gives {tokens.player(card.controller)} {tokens.gold(gained)}."
    elif card.patrol_slot == "technician":
        drawn = draw_cards(engine, match, card.controller, TECHNICIAN_CARDS, result)
        if drawn:
            line += f" As technician, it draws {tokens.player(card.controller)} a card."
    result.narration.append(line)


def _destroy_hero(engine: "RulesEngine", match: MatchState, seat: int, hero: HeroState,
                  result: StepResult, by: str = "") -> None:
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
    hero.printed = None
    hero.bands = {}
    hero.time_runes = 0
    hero.disabled = False
    hero.runes = {}
    hero.max_level_since_turn_began = False
    hero.summoning_runes = SUMMONING_RUNES_ON_DEATH
    match.record_event("hero_died", slug=hero.slug, owner=seat)
    result.narration.append(line)
    hero_left(engine, match, seat, hero, result)


def to_command_zone(engine: "RulesEngine", match: MatchState, seat: int, hero: HeroState,
                    result: StepResult) -> None:
    """
    A hero returned to its command zone without dying -- Origin Story,
    Ebbflow Archon: no death effect, its levels, damage, runes and effects
    gone as any hero's are, and no summoning runes, so its owner may summon
    it again on their next turn (the author, 2026-10-09; its ruling).
    """
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
    hero.printed = None
    hero.bands = {}
    hero.time_runes = 0
    hero.disabled = False
    hero.runes = {}
    hero.max_level_since_turn_began = False
    match.record_event("hero_returned", slug=hero.slug, owner=seat)
    hero_left(engine, match, seat, hero, result)


def hero_left(engine: "RulesEngine", match: MatchState, seat: int, hero: HeroState,
              result: StepResult) -> None:
    """Prynn at 7: "Leaves: Return all cards to play that Pasternaak
    trashed." -- each fresh, under whoever controlled it when it went (her
    rulings)."""
    trashed, hero.trashed = list(hero.trashed), []
    for entry in trashed:
        result.narration.append(
            f"{tokens.card(entry['slug'])} returns to play as {tokens.hero(hero.slug)} leaves it."
        )
        return_fresh(engine, match, entry["slug"], entry["controller"], entry["owner"], result)


def destroy(engine: "RulesEngine", match: MatchState, things: Iterable[tuple[int, str]],
            result: StepResult, by: str = "", cause: Optional[int] = None,
            forced: bool = False, combat: bool = False) -> None:
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

    An indestructible unit is spared instead (`spare`, step 12) unless
    `forced` -- the second copy of a legendary card, which no rule saves
    (UMR p. 15).
    """
    things = list(things)
    witnesses = _witnesses(engine, match)
    heroes = []
    dead_units: list[CardInstance] = []
    dead_heroes: list[tuple[int, HeroState]] = []
    for seat, ref in things:
        if is_hero_ref(ref):
            hero = match.player(seat).hero_by_ref(ref)
            if hero is not None and hero.in_play and not forced and two_lives_saves(
                engine, match, hero, result,
            ):
                continue
            if hero is not None and hero.in_play:
                _destroy_hero(engine, match, seat, hero, result, by)
                heroes.append(seat)
                dead_heroes.append((seat, hero))
            continue
        card = body_of(match, seat, ref)
        if card is not None and not forced and not combat and engine.cant_leave_play(match, card):
            # Gilded Glaxx with gold: only combat damage kills him.
            result.narration.append(f"{named(match, seat, card.ref)} can't leave play.")
            continue
        if card is not None and not forced and engine.catalog.cards[card.slug].is_unit and \
                soul_stone_saves(engine, match, card, result):
            continue
        if card is not None and not forced and two_lives_saves(engine, match, card, result):
            # Two Lives: it doesn't actually die, so nothing that triggers
            # on "dies" happens (its rulings).
            continue
        if card is not None and not forced and engine.indestructible(match, card):
            # Indestructible: it doesn't leave play -- exhausted, its
            # damage and attachments gone, its runes kept (UMR p. 17).
            spare(engine, match, card, result)
            continue
        if card is not None:
            _destroy_unit(engine, match, seat, card, result, by)
            if engine.catalog.cards[card.slug].is_unit:
                dead_units.append(card)
    _deaths(engine, match, dead_units, dead_heroes, witnesses, combat=combat, result=result)
    if not combat:
        second_chances(engine, match, dead_units, result)
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
    """The kill's two levels for `victor`, to its maximum, said -- and
    its max level text, where it got there."""
    before = victor.level
    reached = raise_level(engine, victor, LEVELS_FOR_A_KILL, match)
    seat = engine.seat_of(match, victor)
    if victor.level > before:
        gained = victor.level - before
        line = (
            f"{tokens.hero(victor.slug)} gains {gained} "
            f"level{'' if gained == 1 else 's'} for the kill: level {victor.level}"
        )
        line += ", a new band, and healed." if reached else "."
        result.narration.append(line)
        if seat is not None:
            max_level_reached(engine, match, seat, victor, result)


def raise_level(engine: "RulesEngine", hero: HeroState, levels: int,
                match: Optional[MatchState] = None) -> bool:
    """Up to `levels` levels for `hero`, to its maximum, healing it if it
    reaches a new band (UMR p. 6). Returns whether it reached one. A
    hero now at its maximum that was not is marked `max_reached`, for
    its "Max level:" trigger (`max_level_reached`)."""
    card = engine.hero_card(hero)
    if engine.levels_frozen(match, hero) or any(
        m.get("kind") == "no_level" for m in hero.modifiers
    ):
        # Chronofixer: "Opposing heroes can't level up" -- by any means;
        # Nether Drain's drained hero "can't level up this turn".
        return False
    before = card.band(hero.level).min_level
    was_max = hero.level >= card.max_level
    hero.level = min(card.max_level, hero.level + levels)
    reached = card.band(hero.level).min_level != before
    if reached and match is not None:
        for band in card.bands:
            if before < band.min_level <= hero.level:
                hero.bands[str(band.min_level)] = match.next_sequence()
    if reached:
        hero.damage = 0
    if not was_max and hero.level >= card.max_level:
        hero.modifiers.append({"kind": "max_reached", "until": "end_of_turn"})
    return reached


def max_level_reached(engine: "RulesEngine", match: MatchState, seat: int, hero: HeroState,
                      result: StepResult) -> None:
    """
    A hero that has just reached its maximum level resolves its "Max
    level:" text once (UMR p. 17: not again if it would gain a level
    while already there): Zane's shove, Argagarg's Water Elemental. **On
    an opponent's turn an effect that asks a decision does not resolve**
    (UMR p. 14), so Zane's, which chooses, waits on nobody and is lost.
    """
    from codex.flow import resolve

    mark = next((m for m in hero.modifiers if m.get("kind") == "max_reached"), None)
    if mark is None:
        return
    hero.modifiers.remove(mark)
    if match.player(seat).silenced:
        # Silenced: its max level text is an ability it does not have
        # (Free Speech, step 13).
        return
    for effect in effects.triggers(hero.slug, "max_level", hero.level):
        asks = any(part.choose is not None for part in effects.EFFECTS[effect].parts)
        if asks and seat != match.active:
            result.narration.append(
                f"{tokens.hero(hero.slug)} reaches its maximum level on another player's turn: "
                "its max level effect has nothing to decide it, and does not resolve."
            )
            continue
        resolve.push(match, resolve.frame(
            effect, seat, tokens.hero(hero.slug), source=hero_ref(hero.slug), origin=hero.slug,
        ))


def trash(engine: "RulesEngine", match: MatchState, card: CardInstance,
          result: Optional[StepResult] = None) -> bool:
    """`card` out of play and out of the game (UMR p. 13): in no pile and
    in no count, never returning -- not a death, so nothing that pays on
    one pays. A Gilded Glaxx with gold stays; whether it went."""
    if engine.cant_leave_play(match, card):
        return False
    match.player(card.controller).play.remove(card)
    _empty_graveyard(match, card)
    match.record_event("trashed", slug=card.slug, owner=card.owner)
    if result is not None and engine.catalog.cards[card.slug].is_unit:
        second_chances(engine, match, [card], result)
    return True


def trash_worker(match: MatchState, seat: int) -> bool:
    """One of `seat`'s workers trashed (UMR p. 15): a count down, unseen
    and all alike. False where there is none to trash."""
    player = match.player(seat)
    if player.workers <= 0:
        return False
    player.workers -= 1
    match.record_event("worker_trashed", owner=seat)
    return True


def sacrifice(engine: "RulesEngine", match: MatchState, card: CardInstance,
              result: Optional[StepResult] = None) -> None:
    """
    A card of yours out of play to its owner's discard pile. A unit
    sacrificed **dies** -- "Dies: A card dies when it is destroyed or
    sacrificed" (UMR p. 16) -- so what pays on a death pays (step 11:
    Bombaster, Land Octopus, Circle of Life); a spell or a building card
    is no unit, and nothing pays.
    """
    if engine.catalog.cards[card.slug].is_unit and not engine.may_sacrifice(match, card):
        # "You can't sacrifice this card" (UMR p. 17): nothing happens.
        return
    if engine.catalog.cards[card.slug].is_unit and soul_stone_saves(engine, match, card, result):
        return
    if two_lives_saves(engine, match, card, result):
        # Sacrificed without a crumbling rune, it takes the rune instead;
        # what the sacrifice paid for still happens (step 13).
        return
    witnesses = _witnesses(engine, match)
    leave_play(engine, match, card, "died")
    match.record_event("sacrificed", slug=card.slug, owner=card.owner)
    if engine.catalog.cards[card.slug].is_unit:
        _deaths(engine, match, [card], [], witnesses, result=result)
        second_chances(engine, match, [card], result)


# -- What pays on a death (step 11) -------------------------------------------


def _witnesses(engine: "RulesEngine", match: MatchState) -> dict:
    """What is in play to see a death, taken before the dying leave: so a
    Captured Bugblatter that dies with the others still counts them, and
    itself (its ruling), and Pirategang Commander's units that die with
    it still had its "Dies:"."""
    found = {"bugblatters": [], "pirategang": {}, "necromancers": {}, "retellers": {}}
    for player in match.players:
        for card in player.play:
            slug = engine.text_slug(card)
            if slug is None:
                continue
            if slug in effects.SKELETON_ON_DEATH:
                found["necromancers"].setdefault(player.seat, []).append(card.id)
            if slug in effects.ON_ANY_DEATH:
                found["bugblatters"].append((player.seat, slug))
            if slug in effects.GRANTS_DIES:
                found["pirategang"][player.seat] = slug
            if slug in effects.RETELLERS:
                found["retellers"][player.seat] = found["retellers"].get(player.seat, 0) + 1
    return found


def _deaths(engine: "RulesEngine", match: MatchState, units: list,
            heroes: list, witnesses: dict, combat: bool = False,
            result: Optional[StepResult] = None) -> None:
    """
    The triggers a death sets off, each a frame onto the stack -- which
    whoever destroyed or sacrificed them runs -- or, where nothing is
    chosen and nothing is said, done at once: Crash Bomber's by whose
    turn it is, Pirategang Commander's granted line, each Captured
    Bugblatter's, a blood rune on each Bloodburn (limit 4), and a hero's
    "Dies:" (Drakk's).
    """
    from codex.flow import resolve

    frames = []
    for card in units:
        seat = card.controller
        by = tokens.card(card.slug)
        mine = seat == match.active
        effect = (effects.DIES_ON_YOUR_TURN if mine else effects.DIES_ON_THEIR_TURN).get(
            engine.text_slug(card) or "")
        if effect is not None:
            frames.append(resolve.frame(effect, seat, by, origin=card.slug))
        granted = witnesses["pirategang"].get(seat)
        if granted is not None:
            # The line is the dying unit's, granted by the Commander --
            # so Hotter Fire adds to it only where that unit is red (the
            # author, 2026-10-09).
            frames.append(resolve.frame(
                effects.GRANTS_DIES[granted], seat, f"{by} (from {tokens.card(granted)})",
                origin=card.slug,
            ))
        for when in ("dies", *(("dies_from_combat",) if combat else ())):
            for effect in effects.triggers(engine.text_slug(card) or "", when):
                one = resolve.frame(effect, seat, by, origin=card.slug)
                if effect == "blackhand_dozer":
                    # "Active player destroys one of your lowest tech units."
                    one["seat"], one["against"] = match.active, seat
                frames.append(one)
        for catapult in match.player(seat).play:
            if catapult.slug in effects.CORPSE_RUNES and engine.texted(catapult):
                catapult.runes["corpse"] = catapult.runes.get("corpse", 0) + 1
        if not is_token(engine, card.slug):
            for watcher in witnesses["necromancers"].get(seat, ()):
                if watcher != card.id:
                    frames.append(resolve.frame(
                        "necromancer", seat, tokens.card("necromancer"), origin="necromancer",
                    ))
        if card.minus_runes and _orpal_unspent(engine, match):
            # Orpal at 6: "The first time a unit with a -1/-1 rune dies each
            # turn, the active player puts a -1/-1 rune on two units
            # friendly to the dead unit."
            one = resolve.frame("orpal_gloor_max", match.active, tokens.hero("orpal_gloor"),
                                origin="orpal_gloor")
            one["against"] = seat
            frames.append(one)
        for watcher, slug in witnesses["bugblatters"]:
            frames.append(resolve.frame(
                effects.ON_ANY_DEATH[slug], watcher, tokens.card(slug), origin=slug,
            ))
        for player in match.players:
            for upgrade in player.play:
                limit = effects.BLOOD_RUNES.get(upgrade.slug)
                if limit is not None:
                    upgrade.runes["blood"] = min(limit, upgrade.runes.get("blood", 0) + 1)
        if witnesses["retellers"].get(seat) and not is_token(engine, card.slug) \
                and engine.is_illusion(match, card):
            _retell(engine, match, seat, card, witnesses["retellers"][seat], result)
        if any(lasting.get("kind") == effects.DEATH_RITES
               for lasting in match.player(seat).lasting):
            # Death Rites: "Whenever one of your units dies this turn,
            # destroy one of an opponent's lowest tech units."
            frames.append(resolve.frame(
                "death_rites_destroy", seat, tokens.card(effects.DEATH_RITES),
                origin=effects.DEATH_RITES,
            ))
    for seat, hero in heroes:
        if match.player(seat).silenced:
            continue
        for effect in effects.triggers(hero.slug, "dies", 1):
            frames.append(resolve.frame(effect, seat, tokens.hero(hero.slug), origin=hero.slug))
    resolve.push(match, *frames)


def _retell(engine: "RulesEngine", match: MatchState, seat: int, card: CardInstance,
            retellers: int, result: Optional[StepResult]) -> None:
    """
    Reteller of Truths: "The first two times each turn one of your
    non-token Illusion units dies (including this one), return it to its
    owner's hand." -- it really died, so what triggers on a death has
    triggered (its ruling); then it goes from where it went to its
    owner's hand, two a turn for each Reteller that saw it die.
    """
    player = match.player(seat)
    count = next((entry for entry in player.lasting if entry.get("kind") == "retold"), None)
    if count is None:
        count = {"kind": "retold", "count": 0, "until": "end_of_turn"}
        player.lasting.append(count)
    if count["count"] >= effects.RETELLER_LIMIT * retellers:
        return
    count["count"] += 1
    _take_back(engine, match, card)
    match.player(card.owner).hand.append(card.slug)
    match.record_event("retold", slug=card.slug, owner=card.owner)
    if result is not None:
        result.narration.append(
            f"{tokens.card('reteller_of_truths')} returns {tokens.card(card.slug)} to "
            f"{tokens.player(card.owner)}'s hand."
        )


def _orpal_unspent(engine: "RulesEngine", match: MatchState) -> bool:
    """Whether an Orpal Gloor at 6 is in play whose "first time each turn"
    has not been spent -- spending it."""
    slug, level = effects.ORPAL_MAX
    for player in match.players:
        if player.silenced:
            continue
        for hero in player.heroes_in_play:
            if hero.slug == slug and hero.level >= level:
                if any(m.get("kind") == "once" and m.get("effect") == "orpal_gloor_max"
                       for m in hero.modifiers):
                    return False
                hero.modifiers.append({"kind": "once", "effect": "orpal_gloor_max",
                                       "until": "end_of_turn"})
                return True
    return False


# -- Arriving (step 11) ---------------------------------------------------------


def add_minus_rune(body, count: int = 1) -> None:
    """-1/-1 runes onto a unit or hero, each cancelling a +1/+1 rune first
    (UMR p. 13)."""
    for _ in range(count):
        if body.plus_runes:
            body.plus_runes -= 1
        else:
            body.minus_runes += 1


def add_plus_rune(body, count: int = 1) -> None:
    """+1/+1 runes onto a unit or hero, each cancelling a -1/-1 rune
    first (UMR p. 13)."""
    for _ in range(count):
        if body.minus_runes:
            body.minus_runes -= 1
        else:
            body.plus_runes += 1


def arrive(engine: "RulesEngine", match: MatchState, card: CardInstance, *,
           from_hand: bool = False, boosted: bool = False) -> None:
    """
    `card` has come into play under its controller, from wherever (UMR
    p. 16, "Arrives"): its arrives triggers go on the stack -- boosted,
    where it was played boosted -- and each Blooming Ancient of its
    controller's grows a rune for another unit of theirs arriving.
    """
    from codex.flow import resolve

    seat = card.controller
    fading = engine.fading(card)
    if fading:
        # Fading X: "Arrives with X time runes" (UMR p. 17).
        card.time_runes = fading
    frames = [
        resolve.frame(effect, seat, tokens.card(card.slug), source=card.ref, boosted=boosted,
                      origin=card.slug)
        for effect in effects.triggers(card.slug, "arrives")
    ]
    for one in frames:
        if from_hand:
            # Zarramonde's "If you played Zarramonde from your hand".
            one["from_hand"] = True
    resolve.push(match, *frames)
    if engine.catalog.cards[card.slug].is_unit:
        _grow_on_arrival(match, seat, card)
        lasting_armor(match, card)
        if from_hand:
            _first_from_hand(engine, match, seat, card)


def _first_from_hand(engine: "RulesEngine", match: MatchState, seat: int, card: CardInstance) -> None:
    """
    Drakk at 6: "The first unit that arrives from your hand each turn
    gets haste." -- for good; only the first, whether or not Drakk was at
    his maximum when it came; never one that arrived otherwise -- a
    token, a unit from the codex -- and played or put into play from the
    hand alike (his rulings).
    """
    player = match.player(seat)
    if player.arrived_from_hand:
        return
    player.arrived_from_hand = True
    slug, level = effects.FIRST_FROM_HAND_HASTE
    if not player.silenced and any(hero.slug == slug and hero.level >= level
                                   for hero in player.heroes_in_play):
        card.modifiers.append({"kind": "keyword", "keyword": "Haste", "until": None})


def hero_arrives(engine: "RulesEngine", match: MatchState, seat: int, hero: HeroState) -> None:
    """A hero summoned: its arrives triggers from the bands it has --
    Argagarg's Wisp -- and Blooming Ancient's rune."""
    from codex.flow import resolve

    fading = engine.fading(hero)
    if fading:
        # Prynn Pasternaak's fading 4: she arrives with four time runes.
        hero.time_runes = fading
    if match.player(seat).silenced:
        # A hero summoned while its player is silenced arrives with no
        # abilities (Free Speech's ruling).
        _grow_on_arrival(match, seat, hero)
        return
    resolve.push(match, *(
        resolve.frame(effect, seat, tokens.hero(hero.slug), source=hero_ref(hero.slug),
                      origin=hero.slug)
        for effect in effects.triggers(hero.slug, "arrives", hero.level)
    ))
    _grow_on_arrival(match, seat, hero)


def _grow_on_arrival(match: MatchState, seat: int, body) -> None:
    for card in match.player(seat).play:
        if card.slug in effects.GROWS_ON_ARRIVAL and card is not body and "polymorph" not in (card.printed or {}):
            add_plus_rune(card)


def summon(engine: "RulesEngine", match: MatchState, slug: str, seat: int,
           count: int, result: StepResult, by: str = "",
           made_by: Optional[int] = None) -> list[CardInstance]:
    """`count` tokens of `slug` summoned for `seat` -- theirs, arriving
    as any unit does (UMR p. 13, 15) -- said in one line."""
    made = []
    for _ in range(count):
        if engine.forecast(slug):
            # A forecast token -- Vir's Mech -- goes to the future instead
            # (the forecast ruling).
            to_future(engine, match, slug, seat)
            match.record_event("summoned_token", slug=slug, seat=seat)
            continue
        card = match.new_instance(slug, seat)
        card.made_by = made_by
        match.record_event("summoned_token", slug=slug, seat=seat)
        arrive(engine, match, card)
        made.append(card)
    if count:
        what = (f"a {tokens.card(slug)} token" if count == 1
                else f"{count} {tokens.card(slug)} tokens")
        line = f"{by} summons {what} for {tokens.player(seat)}"
        if engine.forecast(slug):
            line += f", into the future with {engine.forecast(slug)} time runes"
        result.narration.append(line + ".")
    return made


def put_into_play(engine: "RulesEngine", match: MatchState, slug: str, seat: int, *,
                  from_hand: bool, owner: Optional[int] = None) -> Optional[CardInstance]:
    """A card put into play by an effect (UMR p. 15): no cost paid, no
    tech building needed, no boost -- and it arrives. A forecast card goes
    to the future instead, with its time runes ("When it would come into
    play from something other than forecast, instead it goes to the
    'future' zone", the forecast ruling): `None` then."""
    if engine.forecast(slug):
        to_future(engine, match, slug, seat, owner=owner)
        match.record_event("put_into_play", slug=slug, seat=seat, future=True)
        return None
    card = match.new_instance(slug, seat)
    if owner is not None:
        card.owner = owner
    match.record_event("put_into_play", slug=slug, seat=seat)
    arrive(engine, match, card, from_hand=from_hand)
    return card


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
    lasting_armor(match, card)
    return True


def lasting_armor(match: MatchState, card: CardInstance) -> None:
    """Stampede's +3 armor for a unit that comes under a side whose
    Stampede is in play this turn -- the ATK is the engine's to read, the
    armor is spent as it is hit, so it is granted as the unit arrives."""
    if any(lasting.get("kind") == "stampede" for lasting in match.player(card.controller).lasting):
        grant_armor(card, effects.STAMPEDE_BONUS)


def give_back(match: MatchState, card: CardInstance, result: StepResult) -> None:
    """Kidnapping's end: the unit back to the player it was taken from,
    where it is still in play (its ruling)."""
    seat = card.returns_to
    card.returns_to = None
    if seat is None or seat == card.controller:
        return
    gain_control(match, card, seat)
    result.narration.append(f"{tokens.card(card.slug)} goes back to {tokens.player(seat)}.")


def sideline(body) -> None:
    """Out of the patrol zone, and with it the squad leader's armor."""
    body.patrol_slot = None
    body.armor = 0


# -- Time, the future, indestructible and disable (step 12) --------------------


def to_future(engine: "RulesEngine", match: MatchState, slug: str, seat: int,
              owner: Optional[int] = None) -> CardInstance:
    """
    `slug` into `seat`'s future with its forecast X time runes (UMR p. 17):
    not in play -- untargetable, unaffected -- until its last rune goes.
    It is given its id now, never reused.
    """
    card = CardInstance(
        id=match.next_instance_id, slug=slug, owner=seat if owner is None else owner,
        controller=seat, arrived_this_turn=False, time_runes=engine.forecast(slug) or 1,
    )
    match.next_instance_id += 1
    match.player(seat).future.append(card)
    return card


def arrive_from_future(engine: "RulesEngine", match: MatchState, seat: int, card: CardInstance,
                       result: StepResult) -> None:
    """
    A forecast card whose last time rune is gone: a unit arrives and
    enters play -- with arrival fatigue and its arrives trigger then,
    needing nothing it needed to be played (the forecast rulings) -- and a
    spell resolves (Double Time).
    """
    from codex.flow import resolve

    player = match.player(seat)
    if card in player.future:
        player.future.remove(card)
    printed = engine.catalog.cards[card.slug]
    if printed.is_spell:
        result.narration.append(f"{tokens.card(card.slug)} resolves from the future.")
        if card.slug not in effects.EFFECTS:
            match.player(card.owner).discard.append(card.slug)
            return
        match.record_event("from_future", slug=card.slug, seat=seat)
        resolve.push(match, resolve.frame(
            card.slug, seat, tokens.card(card.slug), spell=card.slug, origin=card.slug,
        ))
        return
    card.controller = seat
    card.time_runes = 0
    card.arrived_this_turn = True
    card.exhausted = False
    card.sequence = match.next_sequence()
    player.play.append(card)
    match.record_event("from_future", slug=card.slug, seat=seat)
    atk, hp = engine.unit_stats(card, match)
    result.narration.append(
        f"{tokens.player(seat)}'s {tokens.card(card.slug)} arrives from the future: {atk}/{hp}."
    )
    arrive(engine, match, card)


def add_time_rune(thing, count: int = 1) -> None:
    thing.time_runes += count


def remove_time_rune(engine: "RulesEngine", match: MatchState, seat: int, ref: str,
                     result: StepResult, *, by_fading: bool = False) -> bool:
    """
    A time rune off what `ref` names on `seat`'s side -- a card in play, a
    hero, or a card in the future -- and what its last one does: a card in
    the future arrives (or resolves); a fading card or hero is sacrificed,
    "for any reason" (the fading ruling). `by_fading` says the upkeep's
    fading took it, which Prynn's "dies from fading" alone counts. Whether
    a rune was there to remove.
    """
    thing = timed(match, seat, ref)
    if thing is None or thing.time_runes <= 0:
        return False
    thing.time_runes -= 1
    remembers = (
        isinstance(thing, CardInstance) and engine.text_slug(thing) in effects.REMEMBERERS
        and seat == match.active and future_card(match, seat, ref) is None
    )
    if thing.time_runes > 0:
        if remembers:
            _remember(match, seat, thing)
        return True
    if future_card(match, seat, ref) is not None:
        arrive_from_future(engine, match, seat, thing, result)
        return True
    if not engine.fading(thing):
        return True
    if isinstance(thing, HeroState):
        result.narration.append(f"{tokens.hero(thing.slug)} loses her last time rune and fades away.")
        died_from_fading(engine, match, seat, thing, result, by_fading)
        destroy(engine, match, [(seat, hero_ref(thing.slug))], result, cause=seat)
        return True
    result.narration.append(f"{named(match, seat, thing.ref)} loses its last time rune and is sacrificed.")
    sacrifice(engine, match, thing, result)
    if remembers:
        # Rememberer: the sacrifice and the return trigger at once, and the
        # active player sacrifices first, so she may return herself (the
        # Card FAQ) -- which costs no choice, since the return is "may".
        _remember(match, seat, thing)
    return True


def _remember(match: MatchState, seat: int, card: CardInstance) -> None:
    """Rememberer: "you may put a unit with fading from your discard pile
    into play if you meet the tech requirements for it" -- on its
    controller's own turn, where the choice is theirs to make (UMR p. 14)."""
    from codex.flow import resolve

    resolve.push(match, resolve.frame("rememberer", seat, tokens.card(card.slug), origin=card.slug))


def died_from_fading(engine: "RulesEngine", match: MatchState, seat: int, hero: HeroState,
                     result: StepResult, by_fading: bool) -> None:
    """
    Prynn at 4: "Dies from fading: Opponents skip their next draw/discard
    step (they keep their hand cards)." -- only where the upkeep's fading
    took her last rune, never Time Spiral or her own ability (her rulings).
    """
    slug, level = effects.PRYNN_FADES
    if not by_fading or hero.slug != slug or hero.level < level:
        return
    other = match.opponent(seat)
    other.skip_draw = True
    result.narration.append(
        f"{tokens.hero(hero.slug)} died from fading: {tokens.player(other.seat)} skips their next "
        "draw and discard."
    )


def spare(engine: "RulesEngine", match: MatchState, card: CardInstance,
          result: StepResult) -> None:
    """An indestructible card that would die: exhausted, its damage and
    the cards attached to it gone, its runes kept (UMR p. 17)."""
    card.exhausted = True
    card.damage = 0
    for spell in list(match.instances()):
        if spell.slug != effects.TWO_STEP and card.id in spell.attached:
            leave_play(engine, match, spell, "discard")
    result.narration.append(
        f"{named(match, card.controller, card.ref)} is indestructible: it is exhausted instead."
    )


def _spareable(match: MatchState, card: CardInstance) -> bool:
    """Whether sparing an indestructible card would change anything: damage
    or an attachment to take off, or it is not yet exhausted."""
    attached = any(
        spell.slug != effects.TWO_STEP and card.id in spell.attached for spell in match.instances()
    )
    return bool(card.damage) or attached or not card.exhausted


def two_lives_saves(engine: "RulesEngine", match: MatchState, body,
                    result: Optional[StepResult]) -> bool:
    """
    Two Lives (Garus Rook at 8, Justice Juggernaut): "If this would die,
    heal all damage on it and put a crumbling rune on it instead. While it
    has a crumbling rune, it can really die." -- it does not die, so
    nothing that triggers on "dies" happens, the technician's card among
    them (its rulings). Whether Two Lives saved it.
    """
    if not engine.has_keyword(body, effects.TWO_LIVES, match):
        return False
    if body.runes.get(effects.CRUMBLING):
        return False
    body.runes[effects.CRUMBLING] = 1
    body.damage = 0
    if result is not None:
        seat = engine.seat_of(match, body)
        ref = hero_ref(body.slug) if isinstance(body, HeroState) else body.ref
        result.narration.append(
            f"{named(match, seat, ref)} would die: Two Lives heals it and puts a crumbling "
            "rune on it instead."
        )
    return True


def soul_stone_saves(engine: "RulesEngine", match: MatchState, card: CardInstance,
                     result: Optional[StepResult]) -> bool:
    """
    Soul Stone: "If it would die, instead remove all damage from it and
    sacrifice all Soul Stones on it." -- it does not die, so nothing that
    pays on a death pays (its rulings). Whether a Soul Stone saved it.
    """
    stones = [spell for spell in match.instances()
              if spell.slug == effects.SOUL_STONE and card.id in spell.attached]
    if not stones:
        return False
    card.damage = 0
    for stone in stones:
        leave_play(engine, match, stone, "discard")
        match.record_event("sacrificed", slug=stone.slug, owner=stone.owner)
    if result is not None:
        result.narration.append(
            f"{named(match, card.controller, card.ref)} would die: its "
            f"{tokens.card(effects.SOUL_STONE)} is sacrificed instead, and its damage removed."
        )
    return True


def random_discard(engine: "RulesEngine", match: MatchState, seat: int,
                   result: StepResult, by: str) -> bool:
    """
    `seat` discards a card at random (Thieving Imp, Cursed Crow, Shadow
    Blade): picked by `engine.pick`, recorded beside the shuffles so a
    replay discards the same one -- and said as a count, never by name.
    """
    player = match.player(seat)
    if not player.hand:
        return False
    slug = engine.pick(player.hand)
    result.drawn.append([effects.PICK, slug])
    player.hand.remove(slug)
    player.discard.append(slug)
    match.record_event("discarded_at_random", seat=seat, slug=slug)
    result.narration.append(f"{tokens.player(seat)} discards a card at random for {by}.")
    return True


def _has_tech_ii_unit(engine: "RulesEngine", player) -> bool:
    """A tech II unit in play or in the future -- never tech III, a tech II
    building or upgrade, or a buried unit (Hardened Mox's ruling)."""
    for card in (*player.play, *player.future):
        printed = engine.catalog.cards[card.slug]
        if printed.is_unit and (printed.tech_level or 0) == 2:
            return True
    return False


def _stinger_excess(engine: "RulesEngine", match: MatchState, result: StepResult) -> bool:
    """
    Hive: "limit: 5 per Hive" -- a player with more Stingers than five for
    each Hive of theirs in play sacrifices the rest; with no Hive, all of
    them, and otherwise the active player chooses which (Hive's rulings),
    asked as a frame. Whether anything was done or asked.
    """
    from codex.flow import resolve

    if any(frame.get("effect") == "hive_excess" for frame in match.resolving):
        return False
    for player in match.players:
        stingers = [card for card in player.play if card.slug == effects.STINGER]
        hives = [card for card in player.play if card.slug == effects.HIVE and engine.texted(card)]
        made = any(event.get("kind") == "summoned_token" and event.get("slug") == effects.STINGER
                   and event.get("seat") == player.seat for event in match.events)
        if not made:
            continue
        excess = len(stingers) - effects.STINGERS_PER_HIVE * len(hives)
        if excess <= 0:
            continue
        if not hives or excess == len(stingers):
            result.narration.append(f"{tokens.player(player.seat)}'s Stingers go with their Hive.")
            for card in stingers:
                sacrifice(engine, match, card, result)
            return True
        frame = resolve.frame("hive_excess", match.active, tokens.card(effects.HIVE), origin=effects.HIVE)
        frame["against"] = player.seat
        match.resolving.insert(0, frame)
        return True
    return False


def golgort(engine: "RulesEngine", match: MatchState, seat: int, result: StepResult) -> None:
    """Yesterday's Golgort: a time rune each time its controller deals
    combat damage to a building -- with any unit or hero (its ruling), and
    combat damage alone, as the card says (the author, 2026-10-10): a
    spell's or an ability's damage gives none."""
    for card in match.player(seat).play:
        if engine.text_slug(card) in effects.GOLGORTS:
            card.time_runes += 1
            result.narration.append(f"{tokens.card(card.slug)} gets a time rune: {card.time_runes}.")


def return_fresh(engine: "RulesEngine", match: MatchState, slug: str, controller: int,
                 owner: int, result: StepResult) -> Optional[CardInstance]:
    """A card back into play "fresh" -- a new object, under the player who
    controlled it when it left, with arrival fatigue and none of what it
    had (Max Geiger's, Prynn's and Second Chances' rulings); a forecast
    card goes to the future."""
    card = put_into_play(engine, match, slug, controller, from_hand=False, owner=owner)
    if card is not None:
        atk, hp = engine.unit_stats(card, match)
        result.narration.append(f"{tokens.card(slug)} returns to play under {tokens.player(controller)}: {atk}/{hp}.")
    return card


def second_chances(engine: "RulesEngine", match: MatchState, cards, result: Optional[StepResult]) -> None:
    """
    Second Chances: "Whenever one of your non-token units leaves play from
    something other than combat damage, return it to play. Once-per-turn.
    (Choose randomly if multiples leave at once.)" -- under its last
    controller, fresh, taken back from wherever it went: the discard pile,
    the hand, the Graveyard, the trash (its rulings). A token is gone and
    uses nothing up. The random choice is `engine.pick`, recorded.
    """
    if result is None:
        return
    by_seat: dict[int, list] = {}
    for card in cards:
        if is_token(engine, card.slug) or not engine.catalog.cards[card.slug].is_unit:
            continue
        by_seat.setdefault(card.controller, []).append(card)
    for seat, gone in by_seat.items():
        upgrade = next((other for other in match.player(seat).play
                        if other.slug in effects.SECOND_CHANCES and engine.texted(other)
                        and not any(m.get("kind") == "once" and m.get("effect") == "second_chances"
                                    for m in other.modifiers)), None)
        if upgrade is None:
            continue
        if len(gone) > 1:
            key = engine.pick([str(card.id) for card in gone])
            result.drawn.append([effects.PICK, key])
            card = next(card for card in gone if str(card.id) == key)
        else:
            card = gone[0]
        upgrade.modifiers.append({"kind": "once", "effect": "second_chances", "until": "end_of_turn"})
        _take_back(engine, match, card)
        result.narration.append(f"{tokens.card('second_chances')} returns {tokens.card(card.slug)}.")
        return_fresh(engine, match, card.slug, seat, card.owner, result)


def _take_back(engine: "RulesEngine", match: MatchState, card: CardInstance) -> None:
    """A card that left play, taken back from wherever it went, so it can
    return: the newest copy in its owner's discard pile or hand, a
    Graveyard, or Prynn's list of the trashed."""
    owner = match.player(card.owner)
    for pile in (owner.discard, owner.hand):
        if card.slug in pile:
            index = len(pile) - 1 - pile[::-1].index(card.slug)
            pile.pop(index)
            return
    for player in match.players:
        for yard in engine.graveyards(player):
            for entry in yard.buried:
                if entry["slug"] == card.slug and entry["owner"] == card.owner:
                    yard.buried.remove(entry)
                    return
        for hero in player.heroes:
            hero.trashed = [entry for entry in hero.trashed if entry.get("id") != card.id]


def sentry_shields(engine: "RulesEngine", match: MatchState, bodies, result: StepResult) -> list:
    """
    Sentry: "Prevent the first damage per turn that a spell or ability
    would deal to one of your patrollers. (Choose randomly if multiple
    patrollers are damaged at once.)" -- sparkshot's and the tower's too
    (its ruling). `bodies` are what is about to be damaged at once; the
    one shielded, as a list of none or one.
    """
    for seat in (1, 2):
        sentry = next((card for card in match.player(seat).play
                       if card.slug in effects.SENTRIES and engine.texted(card)
                       and not any(m.get("kind") == "once" and m.get("effect") == "sentry"
                                   for m in card.modifiers)), None)
        if sentry is None:
            continue
        mine = [body for body in bodies
                if engine.seat_of(match, body) == seat and getattr(body, "patrol_slot", None)]
        if not mine:
            continue
        if len(mine) > 1:
            keys = [getattr(body, "ref", None) or hero_ref(body.slug) for body in mine]
            key = engine.pick(keys)
            result.drawn.append([effects.PICK, key])
            shielded = mine[keys.index(key)]
        else:
            shielded = mine[0]
        sentry.modifiers.append({"kind": "once", "effect": "sentry", "until": "end_of_turn"})
        name = tokens.hero(shielded.slug) if isinstance(shielded, HeroState) else tokens.card(shielded.slug)
        result.narration.append(f"{tokens.card('sentry')} prevents the damage to {name}.")
        return [shielded]
    return []


def disable(body) -> None:
    """Disable (UMR p. 16): exhausted, sidelined if it was patrolling, and
    not readied at its next ready phase."""
    body.exhausted = True
    sideline(body)
    body.disabled = True


# -- The position's own consequences ----------------------------------------------


def lethal(engine: "RulesEngine", match: MatchState, body) -> bool:
    """Whether a unit or hero has damage equal to its HP, or 0 HP."""
    hp = engine.body_stats(match, body)[1]
    return hp <= 0 or body.damage >= hp


_lethal = lethal


def grant_armor(body, amount: int) -> None:
    """Temporary armor (Rampant Growth, Dinosize, Stampede, Argagarg):
    onto the body's armor now, and taken off what is left at the end of
    the turn (UMR p. 16)."""
    body.armor += amount
    body.modifiers.append({"kind": "armor", "amount": amount, "until": "end_of_turn"})


def kill_bonus(engine: "RulesEngine", match: MatchState, seat: int, killer: Optional[str],
               slot: Optional[str], result: StepResult) -> None:
    """
    Captain Zane at 4: "Whenever Zane kills a scavenger, get {gold:1}.
    Whenever Zane kills a technician, draw a card." -- by his own combat
    damage or his max level ability alone (his ruling). `killer` is the
    hero's slug, `slot` where what died patrolled.
    """
    if killer is None or slot is None:
        return
    hero = match.player(seat).hero_of(killer)
    if hero is None or match.player(seat).silenced:
        return
    for (slug, level), bonuses in effects.KILL_BONUSES.items():
        if slug != killer or hero.level < level:
            continue
        bonus = bonuses.get(slot)
        if bonus == "gold":
            gained = gain_gold(match, seat, 1)
            result.narration.append(
                f"{tokens.hero(slug)} killed a scavenger: {tokens.player(seat)} gets {tokens.gold(gained)}."
            )
        elif bonus == "card":
            if draw_cards(engine, match, seat, 1, result):
                result.narration.append(
                    f"{tokens.hero(slug)} killed a technician: {tokens.player(seat)} draws a card."
                )


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
                if engine.has_hp(card) and _lethal(engine, match, card):
                    if engine.cant_leave_play(match, card):
                        # Gilded Glaxx with gold: 0 HP alone does not kill
                        # him (his rulings).
                        continue
                    if engine.indestructible(match, card) and not _spareable(match, card):
                        # At 0 HP from its runes it stays exhausted for good
                        # (the indestructible ruling): nothing more to do.
                        continue
                    dead.append((player.seat, card.ref))
            for hero in player.heroes_in_play:
                if _lethal(engine, match, hero):
                    dead.append((player.seat, hero_ref(hero.slug)))
        if dead:
            destroy(engine, match, dead, result, cause=cause)
            continue
        twin = _legendary_twin(engine, match)
        if twin is not None:
            # "If you ever have multiple copies of a legendary card in
            # play, the newest copy is immediately destroyed" (UMR p. 15).
            result.narration.append(
                f"{named(match, twin.controller, twin.ref)} is a second copy of a legendary card."
            )
            destroy(engine, match, [(twin.controller, twin.ref)], result, cause=cause, forced=True)
            continue
        mox = next((card for player in match.players for card in player.play
                    if engine.text_slug(card) in effects.TRASHED_BY_TECH_II
                    and _has_tech_ii_unit(engine, match.player(card.controller))), None)
        if mox is not None:
            # Hardened Mox: "When you have a tech II unit (even a
            # forecasted one), trash Hardened Mox."
            result.narration.append(
                f"{named(match, mox.controller, mox.ref)} is trashed: its controller has a tech II unit."
            )
            match.player(mox.controller).play.remove(mox)
            match.record_event("trashed", slug=mox.slug, owner=mox.owner)
            continue
        if _stinger_excess(engine, match, result):
            continue
        full = next((yard for player in match.players for yard in engine.graveyards(player)
                     if len(yard.buried) >= effects.GRAVEYARD_LIMIT), None)
        if full is not None:
            # "Sacrifice Graveyard when four or more units are buried in it
            # (and discard those units)."
            result.narration.append(
                f"{named(match, full.controller, full.ref)} holds {len(full.buried)} units: it is "
                "sacrificed, and they are discarded."
            )
            sacrifice(engine, match, full)
            continue
        gone = _sacrifice_due(engine, match)
        if gone is None:
            return
        card, why = gone
        line = f"{named(match, card.controller, card.ref)} is sacrificed: {why}."
        sacrifice(engine, match, card)
        result.narration.append(line)


def _legendary_twin(engine: "RulesEngine", match: MatchState) -> Optional[CardInstance]:
    """The newest copy of a legendary card a player has two of in play,
    or `None` -- by the order things came into play, then by id."""
    for player in match.players:
        seen: dict[str, list[CardInstance]] = {}
        for card in player.play:
            if "Legendary" in (engine.catalog.cards[card.slug].type or ""):
                seen.setdefault(card.slug, []).append(card)
        for copies in seen.values():
            if len(copies) > 1:
                return max(copies, key=lambda card: (getattr(card, "sequence", 0), card.id))
    return None


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
            if card.slug in effects.ATTACHING:
                # Attached to a unit or a hero, it goes when that leaves
                # play (UMR p. 15): Spirit of the Panda, Final Showdown.
                if card.attached and match.instance(card.attached[0]) is None:
                    return card, "what it was attached to is gone"
                host = getattr(card, "attached_hero", None)
                if host is not None:
                    side, ref = host.split(":", 1)
                    hero = match.player(int(side)).hero_by_ref(ref)
                    if hero is None or not hero.in_play:
                        return card, "the hero it was attached to is gone"
    return None


__all__ = [
    "LEVEL_GAIN", "body_of", "building_hp", "building_max_hp", "damage_building", "destroy",
    "gain_kill_levels", "level_gain_owed",
    "gain_control", "is_building", "leave_play", "named", "raise_level",
    "repair_building", "sacrifice", "settle", "sideline", "still_there", "take_damage",
]
