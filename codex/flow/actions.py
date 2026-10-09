"""
The main phase's actions (UMR p. 6-11): hire a worker, summon and level
the hero, play a card, construct a building, declare an attacker, end
the phase, and lock the patrollers.

Each checks its own legality against the engine's answer -- the same
answer the prompt's options were built from -- and refuses with
`RuleRefusal`, citing the page, where the position says no. A card the
engine plays for its numbers alone is said to be (`effects.UNIMPLEMENTED`,
empty since step 6): nothing is ignored silently.

A card's text runs through `codex.flow.resolve`: a spell's when it is
cast, a unit's arrives trigger when it is played, an ability's when it is
used -- each a frame on the stack, asking a target only where there is a
choice.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Mapping, Optional

from codex import effects, tokens
from codex.components import PATROL_SLOTS, AddOnState, BuildingState, MatchState, is_hero_ref
from codex.effects import UNIMPLEMENTED
from codex.formatting import SLOT_NAMES, deck_name
from codex.engine import (
    ADD_ONS,
    BUILDING_DESTROYED_DAMAGE,
    TECH_LAB,
    HIRE_COST,
    LEVEL_COST,
    TECH_BUILDING_SLUGS,
    building_name,
)
from codex.flow import board, resolve
from codex.flow.board import raise_level
from codex.flow.result import FollowOn, FollowOnStep, StepResult
from codex.flow.turn import damage_base
from codex.game import RuleRefusal
from codex.prompts import pending

if TYPE_CHECKING:
    from codex.engine import RulesEngine
    from codex.game import CodexGame

#: What the line that plays a card adds while the engine ignores its text.
NOT_PLAYED_YET = "(its text is not played yet)"


def _vanilla_note(engine: "RulesEngine", slug: str) -> str:
    return f" {NOT_PLAYED_YET}" if slug in UNIMPLEMENTED else ""


def _done(engine, game, match, lines: list[str]) -> StepResult:
    return StepResult(narration=lines, board_changed=True, next=pending(engine, game, match))


def hire_worker(engine: "RulesEngine", game: "CodexGame", match: MatchState, slug: str) -> StepResult:
    """A gold and a card from the hand, trashed unseen, for a worker --
    once a turn (UMR p. 6). The card is never named."""
    seat = match.active
    player = match.active_player
    option = engine.hire_option(player)
    if not option.allowed:
        raise RuleRefusal(f"You can't hire a worker: {option.why_not}.", cite="UMR p. 6")
    if slug not in player.hand:
        raise RuleRefusal("That card is not in your hand.")
    player.hand.remove(slug)
    player.gold -= HIRE_COST
    player.workers += 1
    player.hired_this_turn = True
    match.record_event("hired", slug=slug)
    return _done(engine, game, match, [
        f"{tokens.player(seat)} hires a worker for {tokens.gold(HIRE_COST)}: "
        f"{player.workers} workers."
    ])


def _hero(match: MatchState, slug: Optional[str]):
    """The active player's hero named by `slug` -- their first where an
    older journal names none, from before a side had three."""
    player = match.active_player
    if slug is None:
        return player.heroes[0]
    hero = player.hero_of(slug)
    if hero is None:
        raise RuleRefusal("That is not one of your heroes.")
    return hero


def summon_hero(engine: "RulesEngine", game: "CodexGame", match: MatchState,
                slug: Optional[str] = None) -> StepResult:
    """A hero, for its cost, into play at level 1 with arrival fatigue --
    not with summoning runes, and not past the hero limit (UMR p. 6)."""
    seat = match.active
    player = match.active_player
    hero = _hero(match, slug)
    option = engine.hero_option(player, hero)
    if option.action != "summon" or option.why_not:
        why = option.why_not or "it is already in play"
        raise RuleRefusal(f"You can't summon {engine.name(hero.slug)}: {why}.", cite="UMR p. 6")
    player.gold -= option.cost
    hero.zone = "play"
    hero.level = 1
    hero.damage = 0
    hero.arrived_this_turn = True
    hero.exhausted = False
    hero.patrol_slot = None
    hero.max_level_since_turn_began = False
    match.record_event("summoned", slug=hero.slug)
    atk, hp = engine.hero_stats(hero)
    return _done(engine, game, match, [
        f"{tokens.player(seat)} summons {tokens.hero(hero.slug)} for "
        f"{tokens.gold(option.cost)}: level 1, {atk}/{hp}.{_vanilla_note(engine, hero.slug)}"
    ])


def level_hero(engine: "RulesEngine", game: "CodexGame", match: MatchState, levels: int,
               slug: Optional[str] = None) -> StepResult:
    """`levels` levels for a hero in play, a gold each (UMR p. 6)."""
    seat = match.active
    player = match.active_player
    hero = _hero(match, slug)
    option = engine.hero_option(player, hero)
    if option.action != "level" or option.why_not:
        why = option.why_not or "it is not in play"
        raise RuleRefusal(f"You can't level {engine.name(hero.slug)}: {why}.", cite="UMR p. 6")
    if not isinstance(levels, int) or levels < 1:
        raise RuleRefusal("Level the hero by one level or more.")
    if levels > option.max_levels:
        raise RuleRefusal(
            f"{engine.name(hero.slug)} can gain at most {option.max_levels} level"
            + ("s" if option.max_levels != 1 else "") + " now.",
            cite="UMR p. 6",
        )
    player.gold -= levels * LEVEL_COST
    reached = raise_level(engine, hero, levels)
    match.record_event("levelled", slug=hero.slug, levels=levels, level=hero.level)
    atk, hp = engine.hero_stats(hero)
    line = (
        f"{tokens.player(seat)} levels {tokens.hero(hero.slug)} to {hero.level} "
        f"for {tokens.gold(levels * LEVEL_COST)}"
    )
    line += f": a new band, {atk}/{hp} and healed." if reached else "."
    return _done(engine, game, match, [line])


def play_card(engine: "RulesEngine", game: "CodexGame", match: MatchState, slug: str,
              boost: bool = False) -> StepResult:
    """
    A card from the hand for its cost (UMR p. 7): a unit into play with
    arrival fatigue, its arrives triggers then resolving; a building card
    or an upgrade into play with arrival fatigue -- neither patrols nor
    attacks, and only the building has HP; a spell paid
    and its text resolved part by part (`codex.flow.resolve`) -- then
    into the discard pile, or into play for an ongoing spell -- and each
    Harmony of the caster's summoning its Dancer after it.
    """
    seat = match.active
    player = match.active_player
    if slug not in player.hand:
        raise RuleRefusal("That card is not in your hand.")
    why = engine.why_not_playable(player, slug, match)
    if why:
        raise RuleRefusal(f"You can't play {engine.name(slug)}: {why}.", cite="UMR p. 7")
    card = engine.catalog.cards[slug]
    cost = engine.effective_cost(player, slug)
    if boost:
        # Boost X: paid as the card is played from the hand, never where
        # an effect puts it into play (UMR p. 16; the boost rulings).
        extra = engine.boost_cost(slug)
        if extra is None:
            raise RuleRefusal(f"{engine.name(slug)} has no boost.", cite="UMR p. 16")
        if player.gold < cost + extra:
            raise RuleRefusal(f"You can't boost {engine.name(slug)}: not enough gold.", cite="UMR p. 16")
        cost += extra
    player.hand.remove(slug)
    player.gold -= cost
    match.record_event("played", slug=slug, cost=cost, **({"boosted": True} if boost else {}))
    note = _vanilla_note(engine, slug)
    result = StepResult(board_changed=True)
    if card.is_unit:
        instance = match.new_instance(slug, seat)
        atk, hp = engine.unit_stats(instance, match)
        boosted = ", boosted" if boost else ""
        result.narration.append(
            f"{tokens.player(seat)} plays {tokens.card(slug)} for {tokens.gold(cost)}{boosted}: "
            f"{atk}/{hp}.{note}"
        )
        resolve.push(match, *(
            resolve.frame(effect, seat, tokens.card(slug), source=instance.ref, boosted=boost)
            for effect in effects.triggers(slug, "arrives")
        ))
    elif card.is_permanent:
        match.new_instance(slug, seat)
        what = f"a building, {card.hp} HP" if card.is_building_card else "an upgrade"
        result.narration.append(
            f"{tokens.player(seat)} plays {tokens.card(slug)} for {tokens.gold(cost)}: "
            f"{what}.{note}"
        )
    else:
        boosted = ", boosted" if boost else ""
        result.narration.append(
            f"{tokens.player(seat)} casts {tokens.card(slug)} for {tokens.gold(cost)}{boosted}.{note}"
        )
        if slug in effects.EFFECTS:
            resolve.push(match, resolve.frame(
                slug, seat, tokens.card(slug), spell=slug, cancel_from=len(match.journal),
                boosted=boost,
            ))
        else:
            # A spell the table has no row for -- one in `UNIMPLEMENTED`,
            # said to be by its line -- is paid and discarded.
            player.discard.append(slug)
        # "Whenever you play a spell, summon a 0/1 neutral Dancer token" --
        # each Harmony already in play, so never the Harmony being played
        # (Sirlin, 2016-03-02), after the spell has resolved.
        resolve.push(match, *(
            resolve.frame("harmony_dancer", seat, tokens.card(effects.HARMONY), source=harmony.ref)
            for harmony in player.play if harmony.slug == effects.HARMONY
        ))
    return resolve.carry_on(engine, game, match, result)


def use_ability(engine: "RulesEngine", game: "CodexGame", match: MatchState,
                effect: str, source: str) -> StepResult:
    """
    An ability action (UMR p. 7), one of those `RulesEngine.abilities`
    offers: its cost paid -- the card exhausted, or Harmony sacrificed --
    and its text resolved like a spell's.
    """
    seat = match.active
    player = match.active_player
    option = next(
        (one for one in engine.abilities(match) if one.effect == effect and one.source == source),
        None,
    )
    if option is None:
        raise RuleRefusal("That card has no such ability to use now.", cite="UMR p. 7")
    if not option.allowed:
        raise RuleRefusal(f"You can't use that ability: {option.why_not}.", cite="UMR p. 7")
    result = StepResult(board_changed=True)
    body = engine.body(match, seat, source)
    if effect == "stop_the_music":
        harmony = player.instance(int(source.split(":", 1)[1]))
        board.sacrifice(engine, match, harmony)
        result.narration.append(
            f"{tokens.player(seat)} sacrifices {tokens.card(effects.HARMONY)}: stop the music!"
        )
        by = tokens.card(effects.HARMONY)
    else:
        body.exhausted = True
        if is_hero_ref(source):
            by = tokens.hero(body.slug)
        else:
            by = tokens.card(body.slug)
        result.narration.append(f"{tokens.player(seat)} exhausts {by}.")
    match.record_event("ability", effect=effect, source=source)
    resolve.push(match, resolve.frame(
        effect, seat, by, source=source, cancel_from=len(match.journal),
    ))
    return resolve.carry_on(engine, game, match, result)


def _check_spec(spec: Optional[str], choices, what: str) -> Optional[str]:
    """`spec`, one of `choices` -- refused citing UMR p. 8 where it is
    missing or not one of them -- or `None` where nothing is chosen."""
    if not choices:
        if spec is not None:
            raise RuleRefusal(f"Nothing chooses a spec for {what} now.", cite="UMR p. 8")
        return None
    spec = (spec or "").strip().lower() or None
    if spec is None:
        raise RuleRefusal(
            f"In a standard game, {what} chooses a spec: one of your heroes'.", cite="UMR p. 8",
        )
    if spec not in choices:
        raise RuleRefusal(
            f"{what[0].upper() + what[1:]}'s spec is one of your heroes' "
            f"that it may still take: {', '.join(choice.title() for choice in choices)}.",
            cite="UMR p. 8",
        )
    return spec


def construct(engine: "RulesEngine", game: "CodexGame", match: MatchState, building: str,
              spec: Optional[str] = None, lab_spec: Optional[str] = None) -> StepResult:
    """
    A tech building -- Tech I for 1 at six workers, Tech II for 4 at
    eight, Tech III for 5 at ten, each on the one below, each rebuilt for
    0 once destroyed (UMR p. 8) -- or an add-on: the tower, the surplus,
    the heroes' hall or the tech lab (UMR p. 9). Either is finished at
    the end of the turn. A new add-on replaces the one in the slot, which
    is destroyed and deals its 2 to the base (the author, 2026-10-08).

    In a standard game the tech II chooses a spec among the heroes'
    (`spec`, UMR p. 8), kept through its destruction and rebuild; a tech
    lab chooses its own where the tech II's is chosen, and otherwise
    waits for it and chooses with it (`lab_spec`, the tech_lab ruling).
    A multicolour team's first construction costs 1 more, a rebuild
    included (`RulesEngine.multicolor_surcharge`).
    """
    seat = match.active
    player = match.active_player
    if building not in (*TECH_BUILDING_SLUGS, *ADD_ONS):
        raise RuleRefusal(f"There is no building called {building!r}.")
    option = engine.build_option(player, building)
    if not option.allowed:
        page = "UMR p. 8" if building in TECH_BUILDING_SLUGS else "UMR p. 9"
        if option.why_not.startswith("the basic game"):
            page = "UMR p. 3"
        raise RuleRefusal(
            f"You can't build {_build_label(building)}: {option.why_not}.", cite=page,
        )
    what = "a tech lab" if building == TECH_LAB else "the Tech II building"
    spec = _check_spec(spec, option.specs, what)
    lab_spec = _check_spec(lab_spec, option.lab_specs, "the tech lab")
    if lab_spec is not None and lab_spec == spec:
        raise RuleRefusal("A tech lab unlocks a spec besides the Tech II's.", cite="UMR p. 9")
    player.gold -= option.cost
    player.constructed_once = True
    hp = engine.building_hp(building)
    if building in TECH_BUILDING_SLUGS:
        rebuilt = player.buildings[building] is not None
        player.buildings[building] = BuildingState(hp=hp, under_construction=True)
        verb = "rebuilds" if rebuilt else "builds"
        if building == "tech2" and spec is not None:
            player.tech2_spec = spec
            if lab_spec is not None:
                player.add_on.spec = lab_spec
    else:
        replaced = player.add_on
        player.add_on = AddOnState(slug=building, hp=hp, under_construction=True, spec=spec)
        verb = "builds"
    match.record_event("built", building=building, cost=option.cost)
    line = (
        f"{tokens.player(seat)} {verb} {_build_label(building)} for "
        f"{tokens.gold(option.cost)}"
    )
    if building == "tech2" and spec is not None:
        line += f", choosing {deck_name((spec,))}"
        if lab_spec is not None:
            line += f" and {deck_name((lab_spec,))} for their {tokens.card(TECH_LAB)}"
    elif building == TECH_LAB and spec is not None:
        line += f", choosing {deck_name((spec,))}"
    line += "; it is finished at the end of the turn."
    if building in ADD_ONS:
        line += _vanilla_note(engine, building)
    result = _done(engine, game, match, [line])
    if building in ADD_ONS and replaced is not None:
        result.narration.append(
            f"It replaces their {tokens.card(replaced.slug)}, which is destroyed "
            f"and deals {BUILDING_DESTROYED_DAMAGE} to their base."
        )
        match.record_event("building_destroyed", owner=seat, building=replaced.slug)
        damage_base(match, seat, BUILDING_DESTROYED_DAMAGE, result)
        result.next = pending(engine, game, match)
    return result


def _build_label(building: str) -> str:
    if building in ADD_ONS:
        return tokens.card(building)
    return f"a {building_name(building)} building"


def declare_attacker(engine: "RulesEngine", game: "CodexGame", match: MatchState, attacker: str) -> StepResult:
    """Name the attacker; the defender is asked next (decision 11)."""
    if attacker not in engine.attackers(match):
        raise RuleRefusal(_why_not_attacker(engine, match, attacker), cite="UMR p. 10")
    match.attacking = attacker
    return StepResult(next=pending(engine, game, match))


def _why_not_attacker(engine, match: MatchState, attacker: str) -> str:
    player = match.active_player
    if is_hero_ref(attacker):
        hero = player.hero_by_ref(attacker)
        if hero is None:
            return "That is not one of your heroes."
        name = engine.name(hero.slug)
        if not hero.in_play:
            return f"{name} can't attack: it is not in play."
        if hero.arrived_this_turn:
            return f"{name} can't attack: it arrived this turn."
        return f"{name} can't attack: it is exhausted."
    card = None
    if attacker.startswith("unit:"):
        try:
            card = player.instance(int(attacker.split(":", 1)[1]))
        except ValueError:
            card = None
    if card is None:
        return "That is not one of your units in play."
    name = engine.name(card.slug)
    if card.arrived_this_turn:
        return f"{name} can't attack: it arrived this turn."
    return f"{name} can't attack: it is exhausted."


def cancel_attack(engine: "RulesEngine", game: "CodexGame", match: MatchState) -> StepResult:
    """
    Take back a declared attacker before its defender is chosen -- a
    misclick on the attacker costs nothing (decision 11). Once the
    attack itself has begun, it cannot be taken back: `MatchState.combat`
    is how far it got (`codex.flow.combat`), and by then the defender has
    been chosen, obliterate may have destroyed something and the tower
    may have spent its detection.
    """
    if match.combat is not None:
        raise RuleRefusal("This attack has begun: it cannot be taken back.", cite="UMR p. 10")
    match.attacking = None
    return StepResult(next=pending(engine, game, match))


def detect(engine: "RulesEngine", game: "CodexGame", match: MatchState, card: str) -> StepResult:
    """
    The tower's detection, on its owner's own turn (UMR p. 9): one
    opposing stealth or invisible card named, visible for the rest of the
    turn (Sirlin, 2016-03-14) -- so it may be attacked and, from step 6,
    targeted. Once a turn.
    """
    seat = match.active
    other = 2 if seat == 1 else 1
    option = engine.detect_option(match)
    if not option.allowed:
        raise RuleRefusal(f"Your tower can't detect: {option.why_not}.", cite="UMR p. 9")
    if card not in option.candidates:
        raise RuleRefusal("That is not one of their hidden cards.", cite="UMR p. 9")
    body = engine.body(match, other, card)
    engine.tower(match.active_player).detected = card
    match.record_event("detected", card=card, by=seat)
    named = tokens.hero(body.slug) if is_hero_ref(card) else tokens.card(body.slug)
    return _done(engine, game, match, [
        f"{tokens.player(seat)}'s tower detects {tokens.player(other)}'s {named}: "
        "it is visible for the rest of the turn."
    ])


def end_main(engine: "RulesEngine", game: "CodexGame", match: MatchState) -> StepResult:
    """The main phase ends on the patrol lock (UMR p. 10)."""
    match.enter_phase("patrol")
    return StepResult(next=pending(engine, game, match))


def lock_patrol(engine: "RulesEngine", game: "CodexGame", match: MatchState,
                assignment: Optional[Mapping[str, str]]) -> StepResult:
    """
    Put ready units and heroes into the five slots -- slot to
    `unit:<id>` or `hero:<slug>`, any slot left empty -- and end the main phase
    (UMR p. 10). Exhausted cards cannot patrol; fatigued ones can.
    """
    seat = match.active
    player = match.active_player
    assignment = dict(assignment or {})
    candidates = engine.patrol_candidates(match)
    for slot, ref in assignment.items():
        if slot not in PATROL_SLOTS:
            raise RuleRefusal(f"There is no patrol slot called {slot!r}.", cite="UMR p. 10")
        if ref not in candidates:
            raise RuleRefusal(
                "Only your ready units and hero can patrol.", cite="UMR p. 10",
            )
    if len(set(assignment.values())) != len(assignment):
        raise RuleRefusal("A card patrols one slot at most.", cite="UMR p. 10")
    lines = []
    for slot in PATROL_SLOTS:
        ref = assignment.get(slot)
        if ref is None:
            continue
        if is_hero_ref(ref):
            hero = player.hero_by_ref(ref)
            hero.patrol_slot = slot
            named = tokens.hero(hero.slug)
        else:
            card = player.instance(int(ref.split(":", 1)[1]))
            card.patrol_slot = slot
            named = tokens.card(card.slug)
        lines.append(f"{named} as {SLOT_NAMES[slot]}")
    if lines:
        said = f"{tokens.player(seat)} patrols with " + ", ".join(lines) + "."
    else:
        said = f"{tokens.player(seat)} leaves the patrol zone empty."
    match.record_event("patrolled", slots=dict(assignment))
    match.enter_phase("draw")
    return StepResult(narration=[said], board_changed=True, next=FollowOn(FollowOnStep.DRAW_PHASE))

