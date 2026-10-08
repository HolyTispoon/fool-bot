"""
The main phase's actions (UMR p. 6-11): hire a worker, summon and level
the hero, play a card, construct a building, declare an attacker, end
the phase, and lock the patrollers.

Each checks its own legality against the engine's answer -- the same
answer the prompt's options were built from -- and refuses with
`RuleRefusal`, citing the page, where the position says no. A card the
engine plays for its numbers alone is said to be (`effects.UNIMPLEMENTED`):
nothing is ignored silently.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Mapping, Optional

from codex import tokens
from codex.components import HERO, PATROL_SLOTS, AddOnState, BuildingState, MatchState
from codex.effects import UNIMPLEMENTED
from codex.engine import (
    ADD_ONS,
    BUILDING_DESTROYED_DAMAGE,
    HIRE_COST,
    LEVEL_COST,
    TECH_BUILDING_SLUGS,
    building_name,
)
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


def summon_hero(engine: "RulesEngine", game: "CodexGame", match: MatchState) -> StepResult:
    """The hero, for its cost, into play at level 1 with arrival fatigue
    (UMR p. 6)."""
    seat = match.active
    player = match.active_player
    option = engine.hero_option(player)
    if option.action != "summon" or option.why_not:
        why = option.why_not or "it is already in play"
        raise RuleRefusal(f"You can't summon your hero: {why}.", cite="UMR p. 6")
    hero = player.hero
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


def raise_level(engine: "RulesEngine", hero, levels: int) -> bool:
    """Up to `levels` levels for `hero`, to its maximum, healing it if it
    reaches a new band (UMR p. 6). Returns whether it reached one."""
    card = engine.hero_card(hero)
    before = card.band(hero.level).min_level
    hero.level = min(card.max_level, hero.level + levels)
    reached = card.band(hero.level).min_level != before
    if reached:
        hero.damage = 0
    return reached


def level_hero(engine: "RulesEngine", game: "CodexGame", match: MatchState, levels: int) -> StepResult:
    """`levels` levels for the hero in play, a gold each (UMR p. 6)."""
    seat = match.active
    player = match.active_player
    option = engine.hero_option(player)
    if option.action != "level" or option.why_not:
        why = option.why_not or "it is not in play"
        raise RuleRefusal(f"You can't level your hero: {why}.", cite="UMR p. 6")
    if not isinstance(levels, int) or levels < 1:
        raise RuleRefusal("Level the hero by one level or more.")
    if levels > option.max_levels:
        raise RuleRefusal(
            f"Your hero can gain at most {option.max_levels} level"
            + ("s" if option.max_levels != 1 else "") + " now.",
            cite="UMR p. 6",
        )
    hero = player.hero
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


def play_card(engine: "RulesEngine", game: "CodexGame", match: MatchState, slug: str) -> StepResult:
    """
    A card from the hand for its cost (UMR p. 7): a unit into play with
    arrival fatigue; a spell paid and put into the discard pile -- which,
    in this step, is all a spell does, since every spell of the set is
    in `UNIMPLEMENTED`.
    """
    seat = match.active
    player = match.active_player
    if slug not in player.hand:
        raise RuleRefusal("That card is not in your hand.")
    why = engine.why_not_playable(player, slug)
    if why:
        raise RuleRefusal(f"You can't play {engine.name(slug)}: {why}.", cite="UMR p. 7")
    card = engine.catalog.cards[slug]
    cost = engine.effective_cost(player, slug)
    player.hand.remove(slug)
    player.gold -= cost
    match.record_event("played", slug=slug, cost=cost)
    note = _vanilla_note(engine, slug)
    if card.is_unit:
        match.new_instance(slug, seat)
        atk, hp = card.atk or 0, card.hp or 0
        line = (
            f"{tokens.player(seat)} plays {tokens.card(slug)} for {tokens.gold(cost)}: "
            f"{atk}/{hp}.{note}"
        )
    else:
        player.discard.append(slug)
        line = f"{tokens.player(seat)} casts {tokens.card(slug)} for {tokens.gold(cost)}.{note}"
    return _done(engine, game, match, [line])


def construct(engine: "RulesEngine", game: "CodexGame", match: MatchState, building: str) -> StepResult:
    """
    A tech building -- Tech I for 1 at six workers, Tech II for 4 at
    eight, Tech III for 5 at ten, each on the one below, each rebuilt for
    0 once destroyed (UMR p. 8) -- or an add-on, the tower or the surplus
    (UMR p. 9). Either is finished at the end of the turn. A new add-on
    replaces the one in the slot, which is destroyed and deals its 2 to
    the base (the author, 2026-10-08).
    """
    seat = match.active
    player = match.active_player
    if building not in (*TECH_BUILDING_SLUGS, *ADD_ONS):
        raise RuleRefusal(f"There is no building called {building!r}.")
    option = engine.build_option(player, building)
    if not option.allowed:
        page = "UMR p. 8" if building in TECH_BUILDING_SLUGS else "UMR p. 9"
        raise RuleRefusal(
            f"You can't build {_build_label(building)}: {option.why_not}.", cite=page,
        )
    player.gold -= option.cost
    hp = engine.building_hp(building)
    if building in TECH_BUILDING_SLUGS:
        rebuilt = player.buildings[building] is not None
        player.buildings[building] = BuildingState(hp=hp, under_construction=True)
        verb = "rebuilds" if rebuilt else "builds"
    else:
        replaced = player.add_on
        player.add_on = AddOnState(slug=building, hp=hp, under_construction=True)
        verb = "builds"
    match.record_event("built", building=building, cost=option.cost)
    result = _done(engine, game, match, [
        f"{tokens.player(seat)} {verb} {_build_label(building)} for "
        f"{tokens.gold(option.cost)}; it is finished at the end of the turn."
        + (_vanilla_note(engine, building) if building in ADD_ONS else "")
    ])
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
    if attacker == HERO:
        hero = player.hero
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
    """Take back a declared attacker before its defender is chosen."""
    match.attacking = None
    return StepResult(next=pending(engine, game, match))


def end_main(engine: "RulesEngine", game: "CodexGame", match: MatchState) -> StepResult:
    """The main phase ends on the patrol lock (UMR p. 10)."""
    match.enter_phase("patrol")
    return StepResult(next=pending(engine, game, match))


def lock_patrol(engine: "RulesEngine", game: "CodexGame", match: MatchState,
                assignment: Optional[Mapping[str, str]]) -> StepResult:
    """
    Put ready units and the hero into the five slots -- slot to
    `unit:<id>` or `hero`, any slot left empty -- and end the main phase
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
        if ref == HERO:
            player.hero.patrol_slot = slot
            named = tokens.hero(player.hero.slug)
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


#: The slots as a line names them.
SLOT_NAMES = {
    "squad_leader": "squad leader",
    "elite": "elite",
    "scavenger": "scavenger",
    "technician": "technician",
    "lookout": "lookout",
}
