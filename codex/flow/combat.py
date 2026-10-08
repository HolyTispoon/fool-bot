"""
An attack (UMR p. 10-11, 14, 16-18): the attacker exhausts -- unless it
has readiness -- attacker and defender deal their ATK to each other at
once, swift strike first, and whatever has damage equal to its HP, or 0
HP, is destroyed: a unit face-down to its owner's discard pile, with the
scavenger's gold or the technician's card to its controller; a hero to
the command zone with two summoning runes, and two levels to the
opposing hero in play; a building's 2 damage to its base. A base at 0
ends the game.

**The keywords are the engine's answers** (`codex.keywords`,
`RulesEngine`'s keyword questions), asked here and decided nowhere else:
who may be attacked and who may be ignored (flying, anti-air, stealth,
invisible, unstoppable, the tower's detection), what else takes damage
(the tower, the anti-air patrollers a flier flew over, sparkshot's
neighbour, overpower's excess), what is destroyed before combat
(obliterate) and in what order the damage lands (swift strike).

**An attack is one action with choices inside it.** Obliterate's tie,
sparkshot's two neighbours and overpower's excess are each asked only
where there is something to choose, so the attack stands half-resolved
on `MatchState.combat` -- the attacker, the defender, what has been
chosen, and the stage it waits at -- which `codex.prompts.pending` reads.
A choice answered carries the attack on from exactly there, and the
journal records the whole attack as the one action it is
(`codex.flow.driver.apply`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from codex import tokens
from codex.components import HERO, TECH_BUILDINGS, CardInstance, HeroState, MatchState
from codex.engine import (
    BUILDING_DESTROYED_DAMAGE,
    LEVELS_FOR_A_KILL,
    SCAVENGER_GOLD,
    SPARKSHOT_DAMAGE,
    SUMMONING_RUNES_ON_DEATH,
    TECHNICIAN_CARDS,
    TOWER_DAMAGE,
    building_name,
    unit_ref,
)
from codex.flow.actions import raise_level
from codex.flow.result import StepResult
from codex.flow.turn import damage_base, draw_cards, gain_gold
from codex.game import RuleRefusal
from codex.prompts import pending

if TYPE_CHECKING:
    from codex.engine import RulesEngine
    from codex.game import CodexGame

#: The stages an attack waits at, in the order it works through them:
#: obliterate before combat, then a new defender where obliterate took
#: the first, then sparkshot's neighbour and overpower's excess, then the
#: damage. `MatchState.combat["stage"]` is one of these.
OBLITERATE = "obliterate"
DEFENDER = "defender"
SPARKSHOT = "sparkshot"
OVERPOWER = "overpower"
RESOLVE = "resolve"


@dataclass
class _Fighter:
    """One side of a fight: a unit, a hero, or a building."""

    seat: int
    ref: str
    card: Optional[CardInstance] = None
    hero: Optional[HeroState] = None

    @property
    def body(self):
        """The unit or hero, or `None` for a building."""
        return self.card if self.card is not None else self.hero

    @property
    def is_building(self) -> bool:
        return self.body is None

    def named(self, whose: bool = True) -> str:
        """The fighter in a line -- with its side named, since both
        decks are the same ten starters and "Tenderfoot attacks
        Tenderfoot" says nothing; `whose=False` for the attacker, whose
        side the turn already names."""
        owner = f"{tokens.player(self.seat)}'s " if whose else ""
        if self.card is not None:
            return f"{owner}{tokens.card(self.card.slug)}"
        if self.hero is not None:
            return f"{owner}{tokens.hero(self.hero.slug)}"
        return f"{tokens.player(self.seat)}'s {building_name(self.ref)}"


@dataclass
class _Hit:
    """One instance of combat damage: which batch it lands in -- 0 is
    swift strike's, 1 everything else's -- where it comes from, where it
    goes, and how much."""

    batch: int
    source: Optional[_Fighter]
    target: _Fighter
    amount: int
    kind: str
    landed: int = 0
    skipped: bool = False


def _fighter(match: MatchState, seat: int, ref: str) -> _Fighter:
    player = match.player(seat)
    if ref == HERO:
        return _Fighter(seat, ref, hero=player.hero)
    instance_id = unit_ref(ref)
    if instance_id is not None:
        return _Fighter(seat, ref, card=player.instance(instance_id))
    return _Fighter(seat, ref)


def _take(fighter: _Fighter, amount: int) -> int:
    """Combat damage onto a unit or hero, armour first; what landed."""
    body = fighter.body
    absorbed = min(body.armor, amount)
    body.armor -= absorbed
    landed = amount - absorbed
    body.damage += landed
    return landed


def _hp(engine: "RulesEngine", fighter: _Fighter) -> int:
    if fighter.card is not None:
        return engine.unit_stats(fighter.card)[1]
    return engine.hero_stats(fighter.hero)[1]


def _is_destroyed(engine: "RulesEngine", fighter: _Fighter) -> bool:
    hp = _hp(engine, fighter)
    body = fighter.body
    return hp <= 0 or body.damage >= hp


def _damage_building(match: MatchState, seat: int, ref: str, amount: int,
                     result: StepResult) -> None:
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


def _destroy_unit(engine: "RulesEngine", match: MatchState, fighter: _Fighter,
                  result: StepResult) -> None:
    card = fighter.card
    controller = match.player(card.controller)
    controller.play.remove(card)
    if engine.catalog.cards[card.slug].kind != "token":
        match.player(card.owner).discard.append(card.slug)
    match.record_event("destroyed", slug=card.slug, owner=card.owner)
    line = f"{fighter.named()} is destroyed."
    if card.patrol_slot == "scavenger":
        gained = gain_gold(match, card.controller, SCAVENGER_GOLD)
        line += f" As scavenger, it gives {tokens.player(card.controller)} {tokens.gold(gained)}."
    elif card.patrol_slot == "technician":
        drawn = draw_cards(engine, match, card.controller, TECHNICIAN_CARDS, result)
        if drawn:
            line += f" As technician, it draws {tokens.player(card.controller)} a card."
    result.narration.append(line)


def _destroy_hero(engine: "RulesEngine", match: MatchState, fighter: _Fighter,
                  result: StepResult) -> None:
    hero = fighter.hero
    hero.zone = "command"
    hero.level = 1
    hero.damage = 0
    hero.exhausted = False
    hero.arrived_this_turn = False
    hero.attacked_this_turn = False
    hero.patrol_slot = None
    hero.armor = 0
    hero.max_level_since_turn_began = False
    hero.summoning_runes = SUMMONING_RUNES_ON_DEATH
    match.record_event("hero_died", slug=hero.slug, owner=fighter.seat)
    result.narration.append(
        f"{fighter.named()} dies and returns to the command zone with "
        f"{SUMMONING_RUNES_ON_DEATH} summoning runes."
    )


def _destroy(engine: "RulesEngine", match: MatchState, fighters: list[_Fighter],
             result: StepResult) -> None:
    """Destroy each of these, and give the kill's two levels to the
    opposing hero in play (UMR p. 7)."""
    for fighter in fighters:
        if fighter.card is not None:
            _destroy_unit(engine, match, fighter, result)
        else:
            _destroy_hero(engine, match, fighter, result)
    for fighter in fighters:
        if fighter.hero is None:
            continue
        victor = match.opponent(fighter.seat).hero
        if not victor.in_play:
            continue
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


# -- Declaring the attack ---------------------------------------------------


def declare_attack(engine: "RulesEngine", game: "CodexGame", match: MatchState,
                   attacker: str, defender: str) -> StepResult:
    """
    `attacker` takes `defender`, one of `engine.legal_defenders` -- then
    the attack works through its stages, asking only what it has to
    (`_carry_on`).
    """
    seat = match.active
    other = 2 if seat == 1 else 1
    state = match.combat
    if state is None and attacker not in engine.attackers(match):
        raise RuleRefusal("That attacker can no longer attack.", cite="UMR p. 10")
    if state is not None and state["stage"] != DEFENDER:
        raise RuleRefusal("That is not what this attack is waiting on.")
    if defender not in engine.legal_defenders(match, attacker):
        raise RuleRefusal(
            "That can't be attacked now: the squad leader first, then any "
            "patroller, then anything else.",
            cite="UMR p. 10",
        )
    result = StepResult(board_changed=True)
    if state is None:
        match.combat = {
            "attacker": attacker,
            "defender": defender,
            "stage": OBLITERATE,
            "obliterate": engine.obliterate_count(match, attacker),
            "obliterated": [],
            "sparks": [],
            "overpower": None,
        }
        match.attacking = attacker
        hitting = _fighter(match, seat, attacker)
        taking = _fighter(match, other, defender)
        result.narration.append(f"{hitting.named(whose=False)} attacks {taking.named()}.")
        match.record_event("attacked", attacker=attacker, defender=defender)
        # The tower detects the first hidden attacker of the turn the
        # moment it attacks, which is why it could not sneak past the
        # patrol zone (Sirlin, 2016-03-14).
        if engine.tower_detects(match, attacker):
            engine.tower(match.player(other)).detected = attacker
            result.narration.append(
                f"{tokens.player(other)}'s tower detects "
                f"{hitting.named(whose=False)}."
            )
            match.record_event("detected", card=attacker, by=other)
    else:
        # The defender obliterate took, chosen again: the attack goes on
        # from where it stood.
        state["defender"] = defender
        state["stage"] = SPARKSHOT
        taking = _fighter(match, other, defender)
        result.narration.append(f"It takes {taking.named()} instead.")
        match.record_event("attacked", attacker=state["attacker"], defender=defender)
    return _carry_on(engine, game, match, result)


def cancel_attack_allowed(match: MatchState) -> bool:
    """Whether a declared attacker may still be taken back: nothing of
    the attack has happened yet (`codex.flow.actions.cancel_attack`)."""
    return match.combat is None


# -- The choices inside an attack ---------------------------------------------


def choose_obliterate(engine: "RulesEngine", game: "CodexGame", match: MatchState,
                      unit: str) -> StepResult:
    """Which of the equally low-tech units obliterate takes (UMR p. 17)."""
    state = _in_combat(match, OBLITERATE)
    if unit not in engine.obliterate_candidates(match):
        raise RuleRefusal(
            "Obliterate takes their lowest-tech units, and that is not one of them.",
            cite="UMR p. 17",
        )
    result = StepResult(board_changed=True)
    _obliterate_one(engine, match, unit, state, result)
    return _carry_on(engine, game, match, result)


def choose_sparkshot(engine: "RulesEngine", game: "CodexGame", match: MatchState,
                     patroller: str) -> StepResult:
    """Which neighbour of the attacked slot sparkshot's 1 damage goes to
    (UMR p. 18)."""
    state = _in_combat(match, SPARKSHOT)
    if patroller not in engine.sparkshot_candidates(match, state["attacker"], state["defender"]):
        raise RuleRefusal(
            "Sparkshot hits a patroller one slot over from the one attacked.",
            cite="UMR p. 18",
        )
    state["sparks"] = [patroller]
    state["stage"] = OVERPOWER
    return _carry_on(engine, game, match, StepResult(board_changed=True))


def choose_overpower(engine: "RulesEngine", game: "CodexGame", match: MatchState,
                     target: str) -> StepResult:
    """Where overpower's excess goes (UMR p. 17)."""
    state = _in_combat(match, OVERPOWER)
    if target not in engine.overpower_candidates(match, state["attacker"], state["defender"]):
        raise RuleRefusal(
            "Overpower's excess goes to something else this attacker could have attacked.",
            cite="UMR p. 17",
        )
    state["overpower"] = target
    state["stage"] = RESOLVE
    return _carry_on(engine, game, match, StepResult(board_changed=True))


def _in_combat(match: MatchState, stage: str) -> dict:
    state = match.combat
    if state is None or state["stage"] != stage:
        raise RuleRefusal("That is not what this attack is waiting on.")
    return state


def _obliterate_one(engine: "RulesEngine", match: MatchState, unit: str,
                    state: dict, result: StepResult) -> None:
    other = 2 if match.active == 1 else 1
    _destroy(engine, match, [_fighter(match, other, unit)], result)
    state["obliterated"].append(unit)
    state["obliterate"] -= 1


def _carry_on(engine: "RulesEngine", game: "CodexGame", match: MatchState,
              result: StepResult) -> StepResult:
    """
    Work the attack through its stages until a choice has to be asked or
    the damage is dealt. A stage with one answer answers itself: one
    adjacent patroller is no question (docs/design/codex.md, "The
    keywords").
    """
    seat = match.active
    other = 2 if seat == 1 else 1
    while True:
        state = match.combat
        stage = state["stage"]
        if stage == OBLITERATE:
            if state["obliterate"] <= 0:
                state["stage"] = DEFENDER if _defender_is_gone(match, state) else SPARKSHOT
                continue
            candidates = engine.obliterate_candidates(match)
            if not candidates:
                state["obliterate"] = 0
                continue
            if len(candidates) == 1:
                if not state["obliterated"]:
                    result.narration.append(_obliterate_line(engine, match, state))
                _obliterate_one(engine, match, candidates[0], state, result)
                continue
            if not state["obliterated"]:
                result.narration.append(_obliterate_line(engine, match, state))
            result.next = pending(engine, game, match)
            return result
        if stage == DEFENDER:
            # Obliterate took what was attacked, so the attacker chooses
            # again (UMR p. 17).
            result.narration.append(
                f"{tokens.player(seat)} chooses another defender."
            )
            result.next = pending(engine, game, match)
            return result
        if stage == SPARKSHOT:
            candidates = engine.sparkshot_candidates(match, state["attacker"], state["defender"])
            if len(candidates) > 1:
                result.next = pending(engine, game, match)
                return result
            state["sparks"] = list(candidates[:1])
            state["stage"] = OVERPOWER
            continue
        if stage == OVERPOWER:
            candidates = engine.overpower_candidates(match, state["attacker"], state["defender"])
            if len(candidates) > 1:
                result.next = pending(engine, game, match)
                return result
            state["overpower"] = candidates[0] if candidates else None
            state["stage"] = RESOLVE
            continue
        return _resolve(engine, game, match, result)


def _obliterate_line(engine: "RulesEngine", match: MatchState, state: dict) -> str:
    seat = match.active
    other = 2 if seat == 1 else 1
    hitting = _fighter(match, seat, state["attacker"])
    count = state["obliterate"]
    return (
        f"{hitting.named(whose=False)} obliterates {count} of "
        f"{tokens.player(other)}'s lowest-tech units."
    )


def _defender_is_gone(match: MatchState, state: dict) -> bool:
    """Whether what the attack named is no longer there to be attacked --
    obliterate having destroyed it."""
    return state["defender"] in state["obliterated"]


# -- The damage ----------------------------------------------------------------


def _resolve(engine: "RulesEngine", game: "CodexGame", match: MatchState,
             result: StepResult) -> StepResult:
    """
    The damage, all of it at once but for swift strike's, which lands
    first and so kills before anything without it strikes back (UMR
    p. 18): the attacker's ATK and the defender's back, sparkshot's 1 and
    overpower's excess, each anti-air patroller the attacker flew over,
    and the defending tower's 1 where it can see the attacker.
    """
    state = match.combat
    seat = match.active
    other = 2 if seat == 1 else 1
    attacker, defender = state["attacker"], state["defender"]
    hitting = _fighter(match, seat, attacker)
    taking = _fighter(match, other, defender)

    # Readiness does not exhaust to attack, but attacks once a turn
    # (UMR p. 17).
    body = hitting.body
    ready = engine.has_keyword(body, "Readiness")
    body.attacked_this_turn = True
    if not ready:
        body.exhausted = True

    dealt = engine.attack_value(match, seat, attacker)
    back = engine.damage_back(match, attacker, defender)
    excess = engine.overpower_excess(match, attacker, defender) if state["overpower"] else 0
    swift_attacker = engine.has_keyword(body, "Swift strike")
    swift_defender = not taking.is_building and engine.has_keyword(taking.body, "Swift strike")

    hits: list[_Hit] = []
    mine = 0 if swift_attacker else 1
    hits.append(_Hit(mine, hitting, taking, dealt, "attack"))
    for ref in state["sparks"]:
        hits.append(_Hit(mine, hitting, _fighter(match, other, ref), SPARKSHOT_DAMAGE, "sparkshot"))
    if state["overpower"] and excess:
        hits.append(_Hit(mine, hitting, _fighter(match, other, state["overpower"]), excess, "overpower"))
    defence: Optional[_Hit] = None
    if back:
        defence = _Hit(0 if swift_defender else 1, taking, hitting, back, "defend")
        hits.append(defence)
    overflown = []
    for ref in engine.flown_over(match, attacker, defender):
        if not engine.has(match, other, ref, "Anti-air"):
            continue
        patroller = _fighter(match, other, ref)
        hits.append(_Hit(
            0 if engine.has_keyword(patroller.body, "Swift strike") else 1,
            patroller, hitting, engine.attack_value(match, other, ref), "antiair",
        ))
        overflown.append(hits[-1])
    tower = None
    if engine.tower_sees(match, attacker):
        # The tower's damage is simultaneous with the rest, and with
        # swift strike where there is any (Sirlin, 2016-03-14).
        first = any(hit.batch == 0 for hit in hits)
        tower = _Hit(0 if first else 1, None, hitting, TOWER_DAMAGE, "tower")
        hits.append(tower)

    bodies = [hit.target for hit in hits if not hit.target.is_building]
    bodies += [hit.source for hit in hits if hit.source is not None]
    seen: list[_Fighter] = []
    for fighter in bodies:
        if all(fighter.body is not one.body for one in seen):
            seen.append(fighter)

    dead: list[_Fighter] = []
    for batch in (0, 1):
        for hit in hits:
            if hit.batch != batch:
                continue
            if hit.source is not None and any(hit.source.body is one.body for one in dead):
                hit.skipped = True
                continue
            if hit.target.is_building:
                # Buildings deal nothing back and their destruction kills
                # nobody, so their damage lands after the narration, in
                # the order the lines read.
                hit.landed = hit.amount
                continue
            hit.landed = _take(hit.target, hit.amount)
        for fighter in seen:
            if any(fighter.body is one.body for one in dead):
                continue
            if _is_destroyed(engine, fighter):
                dead.append(fighter)

    result.narration.append(_damage_line(hitting, taking, hits[0], defence, swift_attacker))
    for hit in hits[1:]:
        if hit.kind == "sparkshot" and not hit.skipped:
            result.narration.append(
                f"Sparkshot deals {hit.amount} to {hit.target.named()}."
            )
        elif hit.kind == "overpower" and not hit.skipped:
            result.narration.append(
                f"Overpower carries {hit.amount} over to {hit.target.named()}."
            )
    for hit in overflown:
        if not hit.skipped:
            result.narration.append(
                f"{hit.source.named()}, with anti-air, deals {hit.landed} to "
                f"{hitting.named(whose=False)} as it flies over."
            )
    if tower is not None and not tower.skipped:
        result.narration.append(
            f"{tokens.player(other)}'s tower deals {tower.landed} to "
            f"{hitting.named(whose=False)}."
        )

    for hit in hits:
        if hit.target.is_building and not hit.skipped:
            _damage_building(match, hit.target.seat, hit.target.ref, hit.amount, result)

    _destroy(engine, match, dead, result)

    match.attacking = None
    match.combat = None
    result.next = pending(engine, game, match)
    return result


def _damage_line(hitting: _Fighter, taking: _Fighter, attack: _Hit,
                 defence: Optional[_Hit], swift: bool) -> str:
    """The attacker's damage and the defender's back, in one line as step
    2 worded it, with swift strike said where it decided the order."""
    if attack.skipped:
        return f"{hitting.named(whose=False)} is destroyed before it deals its damage."
    if taking.is_building:
        said = f"{hitting.named(whose=False)} deals {attack.amount} to {taking.named()}"
        return said + (" with swift strike." if swift else ".")
    said = f"{hitting.named(whose=False)} deals {attack.landed}"
    if attack.landed < attack.amount:
        said += f" (armour takes {attack.amount - attack.landed})"
    if swift:
        said += " with swift strike"
    if defence is None:
        return said + "."
    if defence.skipped:
        return said + f"; {taking.named()} is destroyed before it strikes back."
    return said + f"; {taking.named()} deals {defence.landed}."
