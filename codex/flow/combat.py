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
the targets of the attacker's attacks triggers (`codex.flow.resolve`),
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

from codex import effects, tokens
from codex.components import CardInstance, HeroState, MatchState, is_hero_ref
from codex.engine import SPARKSHOT_DAMAGE, TOWER_DAMAGE, building_name, unit_ref
from codex.flow import board, resolve
from codex.flow.result import StepResult
from codex.game import RuleRefusal
from codex.prompts import pending

if TYPE_CHECKING:
    from codex.engine import RulesEngine
    from codex.game import CodexGame

#: The stages an attack waits at, in the order it works through them:
#: obliterate before combat, then a new defender where obliterate took
#: the first, then the attacker's attacks triggers -- "after the defender
#: is chosen and before damage", and a new defender again where one of
#: them destroyed it -- then sparkshot's neighbour and overpower's
#: excess, then the damage. `MatchState.combat["stage"]` is one of these.
OBLITERATE = "obliterate"
DEFENDER = "defender"
TRIGGERS = "triggers"
AFTER_TRIGGERS = "after_triggers"
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
    if is_hero_ref(ref):
        return _Fighter(seat, ref, hero=player.hero_by_ref(ref))
    instance_id = unit_ref(ref)
    if instance_id is not None:
        return _Fighter(seat, ref, card=player.instance(instance_id))
    return _Fighter(seat, ref)


def _take(fighter: _Fighter, amount: int, piercing: bool = False) -> int:
    """Combat damage onto a unit or hero, armor first unless it pierces;
    what landed."""
    return board.take_damage(fighter.body, amount, piercing)


def _is_destroyed(engine: "RulesEngine", match: MatchState, fighter: _Fighter) -> bool:
    hp = engine.body_stats(match, fighter.body)[1]
    return hp <= 0 or fighter.body.damage >= hp


def _destroy(engine: "RulesEngine", match: MatchState, fighters: list[_Fighter],
             result: StepResult) -> None:
    """Destroy each of these, and give the kill's two levels to the
    opposing hero in play (UMR p. 7) -- `codex.flow.board.destroy`."""
    board.destroy(engine, match, [(fighter.seat, fighter.ref) for fighter in fighters], result)


# -- Declaring the attack ---------------------------------------------------


def declare_attack(engine: "RulesEngine", game: "CodexGame", match: MatchState,
                   attacker: str, defender: str) -> StepResult:
    """
    `attacker` takes `defender`, one of `engine.legal_defenders` -- then
    the attack works through its stages, asking only what it has to
    (`carry_on`).
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
            "triggered": False,
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
        # The defender obliterate or a trigger took, chosen again: the
        # attack goes on from where it stood -- its triggers, once.
        state["defender"] = defender
        state["stage"] = SPARKSHOT if state.get("triggered", True) else TRIGGERS
        taking = _fighter(match, other, defender)
        # The author's wording, 2026-10-08: the card alone, since the
        # line before has just named whose defender it had to be.
        result.narration.append(f"They have chosen {taking.named(whose=False)}.")
        match.record_event("attacked", attacker=state["attacker"], defender=defender)
    return carry_on(engine, game, match, result)


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
    return carry_on(engine, game, match, result)


def choose_sparkshot(engine: "RulesEngine", game: "CodexGame", match: MatchState,
                     patroller: str) -> StepResult:
    """Which neighbour of the attacked slot one instance of sparkshot's 1
    damage goes to (UMR p. 18); asked again for each instance left."""
    state = _in_combat(match, SPARKSHOT)
    if patroller not in engine.sparkshot_candidates(match, state["attacker"], state["defender"]):
        raise RuleRefusal(
            "Sparkshot hits a patroller one slot over from the one attacked.",
            cite="UMR p. 18",
        )
    state["sparks"] = [*state["sparks"], patroller]
    return carry_on(engine, game, match, StepResult(board_changed=True))


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
    return carry_on(engine, game, match, StepResult(board_changed=True))


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


def carry_on(engine: "RulesEngine", game: "CodexGame", match: MatchState,
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
        if match.resolving:
            # A death on the way -- obliterate's -- set something off:
            # it resolves before the attack goes on (step 11).
            if not resolve.run(engine, match, result):
                result.next = pending(engine, game, match)
                return result
            if match.winner is not None:
                match.combat = None
                match.attacking = None
                result.next = pending(engine, game, match)
                return result
        state = match.combat
        stage = state["stage"]
        if stage == OBLITERATE:
            if state["obliterate"] <= 0:
                if _defender_is_gone(match, state):
                    state["stage"] = DEFENDER
                else:
                    state["stage"] = SPARKSHOT if state.get("triggered", True) else TRIGGERS
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
                f"{tokens.player(seat)} has to choose a different defender."
            )
            result.next = pending(engine, game, match)
            return result
        if stage == TRIGGERS:
            # "Attacks:" -- each time it attacks, after the defender is
            # chosen and before the damage (Brick Thief's and Trojan
            # Duck's rulings: arrives *and* attacks, no choosing).
            state["triggered"] = True
            state["stage"] = AFTER_TRIGGERS
            resolve.push(match, *_attack_frames(match, state["attacker"]))
            if not resolve.run(engine, match, result):
                result.next = pending(engine, game, match)
                return result
            continue
        if stage == AFTER_TRIGGERS:
            if match.winner is not None:
                match.combat = None
                match.attacking = None
                result.next = pending(engine, game, match)
                return result
            if not board.still_there(match, seat, state["attacker"]):
                # Nothing in the basic set does it, but an attacker its own
                # trigger destroyed deals nothing.
                match.combat = None
                match.attacking = None
                result.next = pending(engine, game, match)
                return result
            state["stage"] = DEFENDER if _defender_is_gone(match, state) else SPARKSHOT
            continue
        if stage == SPARKSHOT:
            # Each instance of sparkshot deals its 1 to a neighbour, so
            # two may go to one patroller or one to each (Sirlin's
            # sparkshot ruling 6): asked once per instance where both
            # neighbours are filled, and placed without asking where one is.
            candidates = engine.sparkshot_candidates(match, state["attacker"], state["defender"])
            count = engine.sparkshot_count(match, state["attacker"])
            if len(candidates) > 1 and len(state["sparks"]) < count:
                result.next = pending(engine, game, match)
                return result
            if len(candidates) == 1:
                state["sparks"] = [candidates[0]] * count
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
    obliterate, or an attacks trigger, having destroyed it."""
    other = 2 if match.active == 1 else 1
    return (
        state["defender"] in state["obliterated"]
        or not board.still_there(match, other, state["defender"])
    )


def _attack_frames(match: MatchState, attacker: str) -> list[dict]:
    """The attacker's attacks triggers, as frames to resolve: a unit's
    printed ones, and a hero's from the bands it has reached (Troq at 5)."""
    seat = match.active
    player = match.player(seat)
    if is_hero_ref(attacker):
        hero = player.hero_by_ref(attacker)
        found = effects.triggers(hero.slug, "attacks", hero.level)
        by = tokens.hero(hero.slug)
    else:
        card = player.instance(unit_ref(attacker))
        found = effects.triggers(card.slug, "attacks")
        by = tokens.card(card.slug)
    return [resolve.frame(effect, seat, by, source=attacker) for effect in found]



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
    ready = engine.has_keyword(body, "Readiness", match)
    body.attacked_this_turn = True
    rampaged = False
    if not ready:
        body.exhausted = True
        if (
            isinstance(body, CardInstance) and body.slug in effects.READIES_ONCE
            and not any(modifier.get("kind") == "readied_once" for modifier in body.modifiers)
        ):
            # "The first time Rampaging Elephant exhausts each turn, ready
            # him. (He can attack again!)"
            body.exhausted = False
            body.modifiers.append({"kind": "readied_once", "until": "end_of_turn"})
            rampaged = True

    dealt = engine.attack_value(match, seat, attacker, against=defender)
    back = engine.damage_back(match, attacker, defender)
    excess = engine.overpower_excess(match, attacker, defender) if state["overpower"] else 0
    # Stampede: "Excess combat damage they would deal to units and heroes
    # hits that opponent's base. (This takes precedence over overpower.)"
    stampeded = 0
    if not taking.is_building and engine.stampedes(body):
        stampeded = max(0, dealt - engine.lethal_damage(match, seat, attacker, taking.body))
        excess = 0
    slot_attacked = None if taking.is_building else taking.body.patrol_slot
    swift_attacker = engine.has_keyword(body, "Swift strike", match)
    swift_defender = not taking.is_building and engine.has_keyword(taking.body, "Swift strike", match)

    hits: list[_Hit] = []
    mine = 0 if swift_attacker else 1
    # Overpower's excess is what is left over once the patroller is
    # destroyed -- its remaining HP and its armor -- so the patroller takes
    # what destroys it and the rest goes on (the author, 2026-10-08).
    hits.append(_Hit(mine, hitting, taking, dealt - excess - stampeded, "attack"))
    if stampeded:
        hits.append(_Hit(mine, hitting, _fighter(match, other, "base"), stampeded, "stampede"))
    for ref in dict.fromkeys(state["sparks"]):
        sparked = state["sparks"].count(ref) * SPARKSHOT_DAMAGE
        hits.append(_Hit(mine, hitting, _fighter(match, other, ref), sparked, "sparkshot"))
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
            0 if engine.has_keyword(patroller.body, "Swift strike", match) else 1,
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
    #: What deathtouch hit: "Destroy any unit or hero that takes combat
    #: damage from this card, including damage prevented by armor"
    #: (UMR p. 16).
    touched: list = []
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
            source = hit.source.body if hit.source is not None else None
            piercing = source is not None and engine.has_keyword(source, "Armor piercing", match)
            hit.landed = _take(hit.target, hit.amount, piercing)
            if (
                hit.amount > 0 and source is not None
                and engine.has_keyword(source, "Deathtouch", match)
                and not engine.is_building_ref(match, hit.target.seat, hit.target.ref)
            ):
                touched.append(hit.target.body)
        for fighter in seen:
            if any(fighter.body is one.body for one in dead):
                continue
            if _is_destroyed(engine, match, fighter) or any(fighter.body is one for one in touched):
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
        elif hit.kind == "stampede" and not hit.skipped:
            result.narration.append(
                f"Stampede carries {hit.amount} over to {hit.target.named()}."
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

    if rampaged:
        result.narration.append(f"{hitting.named(whose=False)} readies: it can attack again.")
    for hit in hits:
        if hit.target.is_building and not hit.skipped:
            board.damage_building(match, hit.target.seat, hit.target.ref, hit.amount, result)

    mine_hits = [hit for hit in hits if hit.source is hitting and not hit.skipped and hit.amount > 0]
    killed = any(fighter.body is taking.body for fighter in dead)
    _destroy(engine, match, dead, result)
    _fight_triggers(engine, match, hitting, taking, slot_attacked, mine_hits, killed, result)
    # What the deaths change -- a Grounded Guide gone, a Finesse hero gone
    # with Harmony channeled on it, a dance partner lost.
    board.settle(engine, match, result)
    if board.still_there(match, seat, attacker) and match.winner is None:
        card = hitting.card
        effect = effects.AFTER_COMBAT.get(card.slug) if card is not None else None
        if effect is not None:
            # Ogre Recruiter: "If this survives the combat, gain control of
            # a tech 0 or tech I unit" -- after the damage.
            resolve.push(match, resolve.frame(effect, seat, tokens.card(card.slug),
                                              source=attacker, origin=card.slug))

    match.attacking = None
    match.combat = None
    return resolve.carry_on(engine, game, match, result)


def _fight_triggers(engine: "RulesEngine", match: MatchState, hitting: _Fighter,
                    taking: _Fighter, slot: Optional[str], hits: list, killed: bool,
                    result: StepResult) -> None:
    """
    What an attack's own combat damage sets off (step 11): Might of Leaf
    and Claw's growth rune where the attacker dealt any -- armor's share
    counts, 0 does not, and sparkshot and overpower are the same instance
    (its rulings); Predator Tiger's worker trashed at a base it damaged;
    Molting Firebird's 1 to everything of a player whose building it
    damaged; Gunpoint Taxman's gold for a patroller it killed; and
    Captain Zane's for a scavenger or technician he killed.
    """
    seat = hitting.seat
    other = taking.seat
    if not hits:
        return
    for card in match.player(seat).play:
        if card.slug in effects.GROWTH_RUNES:
            card.runes["growth"] = card.runes.get("growth", 0) + 1
            result.narration.append(f"{tokens.card(card.slug)} gets a growth rune.")
    slug = hitting.card.slug if hitting.card is not None else None
    on_buildings = [hit for hit in hits if engine.is_building_ref(match, hit.target.seat, hit.target.ref)]
    if slug in effects.TRASHES_WORKER_ON_BASE_DAMAGE and any(
        hit.target.ref == "base" for hit in on_buildings
    ):
        if board.trash_worker(match, other):
            result.narration.append(
                f"{tokens.card(slug)} trashes a worker at {tokens.player(other)}'s base."
            )
    if slug in effects.ON_DAMAGING_A_BUILDING and on_buildings:
        firebird = resolve.frame(effects.ON_DAMAGING_A_BUILDING[slug], seat, tokens.card(slug),
                                 source=hitting.ref, origin=slug)
        firebird["against"] = other
        resolve.push(match, firebird)
    if killed and slot is not None:
        steal = effects.STEALS_ON_PATROLLER_KILL.get(slug)
        if steal:
            taken = resolve.steal_gold(match, seat, other, steal)
            if taken:
                result.narration.append(
                    f"{tokens.card(slug)} killed a patroller: {tokens.player(seat)} steals "
                    f"{tokens.gold(taken)} from {tokens.player(other)}."
                )
        if hitting.hero is not None:
            board.kill_bonus(engine, match, seat, hitting.hero.slug, slot, result)


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
        said += f" (armor takes {attack.amount - attack.landed})"
    if swift:
        said += " with swift strike"
    if defence is None:
        return said + "."
    if defence.skipped:
        return said + f"; {taking.named()} is destroyed before it strikes back."
    return said + f"; {taking.named()} deals {defence.landed}."
