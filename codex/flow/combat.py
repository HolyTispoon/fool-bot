"""
An attack (UMR p. 10-11, 14): the attacker exhausts, attacker and
defender deal their ATK to each other at once, and whatever has damage
equal to its HP is destroyed -- a unit to its owner's discard pile, with
the scavenger's gold or the technician's card to its controller; a hero
to the command zone with two summoning runes, and two levels to the
opposing hero in play; a building's 2 damage to its base. A base at 0
ends the game.

The vanilla engine's combat: flying, stealth, swift strike, overpower
and the rest of the keywords come in step 5, the tower's damage with
them. The patrol slots' bonuses are here, since they are the board's
rather than any card's.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from codex import tokens
from codex.components import HERO, TECH_BUILDINGS, CardInstance, HeroState, MatchState
from codex.engine import (
    BUILDING_DESTROYED_DAMAGE,
    LEVELS_FOR_A_KILL,
    SCAVENGER_GOLD,
    SUMMONING_RUNES_ON_DEATH,
    TECHNICIAN_CARDS,
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


@dataclass
class _Fighter:
    """One side of a fight: a unit, a hero, or a building."""

    seat: int
    ref: str
    card: Optional[CardInstance] = None
    hero: Optional[HeroState] = None

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
    body = fighter.card if fighter.card is not None else fighter.hero
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
    body = fighter.card if fighter.card is not None else fighter.hero
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
    hero.patrol_slot = None
    hero.armor = 0
    hero.max_level_since_turn_began = False
    hero.summoning_runes = SUMMONING_RUNES_ON_DEATH
    match.record_event("hero_died", slug=hero.slug, owner=fighter.seat)
    result.narration.append(
        f"{fighter.named()} dies and returns to the command zone with "
        f"{SUMMONING_RUNES_ON_DEATH} summoning runes."
    )


def declare_attack(engine: "RulesEngine", game: "CodexGame", match: MatchState,
                   attacker: str, defender: str) -> StepResult:
    """`attacker` takes `defender`, one of `engine.legal_defenders`."""
    seat = match.active
    other = 2 if seat == 1 else 1
    if attacker not in engine.attackers(match):
        raise RuleRefusal("That attacker can no longer attack.", cite="UMR p. 10")
    if defender not in engine.legal_defenders(match, attacker):
        raise RuleRefusal(
            "That can't be attacked now: the squad leader first, then any "
            "patroller, then anything else.",
            cite="UMR p. 10",
        )
    result = StepResult(board_changed=True)
    hitting = _fighter(match, seat, attacker)
    taking = _fighter(match, other, defender)
    body = hitting.card if hitting.card is not None else hitting.hero
    body.exhausted = True

    dealt = engine.attack_value(match, seat, attacker)
    back = engine.attack_value(match, other, defender)
    result.narration.append(f"{hitting.named(whose=False)} attacks {taking.named()}.")
    match.record_event("attacked", attacker=attacker, defender=defender)

    # Simultaneous: work out both before applying either (UMR p. 11).
    if taking.card is not None or taking.hero is not None:
        landed = _take(taking, dealt)
        returned = _take(hitting, back) if back else 0
        said = f"{hitting.named(whose=False)} deals {landed}"
        if landed < dealt:
            said += f" (armour takes {dealt - landed})"
        said += f"; {taking.named()} deals {returned}." if back else "."
        result.narration.append(said)
        killed = [f for f in (taking, hitting) if _is_destroyed(engine, f)]
        for fighter in killed:
            if fighter.card is not None:
                _destroy_unit(engine, match, fighter, result)
            else:
                _destroy_hero(engine, match, fighter, result)
        for fighter in killed:
            if fighter.hero is None:
                continue
            # The other side's hero in play gains two levels for the
            # kill (UMR p. 7), and a new band heals it.
            victor = match.opponent(fighter.seat).hero
            if victor.in_play:
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
    else:
        result.narration.append(f"{hitting.named(whose=False)} deals {dealt}.")
        _damage_building(match, other, defender, dealt, result)

    match.attacking = None
    result.next = pending(engine, game, match)
    return result
