"""
A helper's corrections to a position (`/codex debug`), for a board a
bug left wrong: a unit or hero moved into a patrol slot, between slots
or out of the patrol zone, and a unit's or hero's HP set. Not a rule and
not an action of the game's; nobody's turn is spent and nothing
triggers. Each still keeps the rules a position holds -- an exhausted
card can't patrol (UMR p. 16), one slot holds one patroller -- since a
correction that broke one would be a bug of its own.

**A correction is a journal entry of its own kind** (`EDIT`), written by
`correct` and replayed by `codex.history.replay` as it was written, so
the fine undo, a spell's cancel and the turn's end taken back all
rebuild it. It is never an undo point of its own: an undo to a point
before it takes it back with what it follows, and the snapshot undos,
which restore a turn's start, take back every correction since
(docs/design/codex.md, "Corrections by hand").
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from codex import history
from codex.components import PATROL_SLOTS, CardInstance, HeroState, MatchState, hero_ref
from codex.engine import SQUAD_LEADER_ARMOR
from codex.flow import board
from codex.flow.result import StepResult
from codex.formatting import SLOT_NAMES
from codex.game import RuleRefusal

if TYPE_CHECKING:
    from codex.engine import RulesEngine

#: The journal's kind for a correction, beside the prompt kinds.
EDIT = history.EDIT

#: The slot a patrol correction names to take a card out of the zone.
OFF = "off"


@dataclass(frozen=True)
class EditTarget:
    """A unit or hero in play a correction may name: where it is, what it
    is, its HP and its slot, for a frontend to word."""

    seat: int
    ref: str
    slug: str
    is_hero: bool
    hp: int
    max_hp: int
    slot: Optional[str]
    exhausted: bool


def targets(engine: "RulesEngine", match: MatchState) -> tuple[EditTarget, ...]:
    """Every unit and hero in play, seat by seat: a seat's units in the
    order they came into play, then its heroes -- a lent one on its
    borrower's side, where it stands."""
    found = []
    for player in match.players:
        for card in player.play:
            if engine.catalog.cards[card.slug].is_unit:
                found.append(_target(engine, match, player.seat, card.ref, card))
        for owner in match.players:
            for hero in owner.heroes_on_table:
                lent = hero.lent_to is not None
                if (hero.lent_to if lent else owner.seat) != player.seat:
                    continue
                ref = f"{owner.seat}:{hero_ref(hero.slug)}" if lent else hero_ref(hero.slug)
                found.append(_target(engine, match, player.seat, ref, hero))
    return tuple(found)


def _target(engine: "RulesEngine", match: MatchState, seat: int, ref: str, body) -> EditTarget:
    max_hp = engine.body_stats(match, body)[1]
    return EditTarget(
        seat=seat, ref=ref, slug=body.slug, is_hero=isinstance(body, HeroState),
        hp=max_hp - body.damage, max_hp=max_hp, slot=body.patrol_slot, exhausted=body.exhausted,
    )


def patrol(seat: int, ref: str, slot: str) -> dict:
    """A correction moving `ref` on `seat`'s side into `slot` of that
    side's patrol zone, or out of it (`OFF`)."""
    return {"kind": EDIT, "edit": "patrol", "seat": seat, "ref": ref, "slot": slot}


def set_hp(seat: int, ref: str, hp: int) -> dict:
    """A correction leaving `ref` on `seat`'s side with `hp` HP."""
    return {"kind": EDIT, "edit": "hp", "seat": seat, "ref": ref, "hp": hp}


def correct(engine: "RulesEngine", match: MatchState, edit: dict) -> StepResult:
    """Make the correction `edit` and journal it; refused with
    `RuleRefusal`, and nothing changed, where it can't be made."""
    if match.winner is not None:
        raise RuleRefusal("This game is over.")
    result = apply(engine, match, edit)
    history.record_edit(match, edit)
    return result


def apply(engine: "RulesEngine", match: MatchState, edit: dict) -> StepResult:
    """The correction `edit`, made: what `correct` journals and a replay
    makes again."""
    seat, ref = edit["seat"], edit["ref"]
    body = board.body_of(match, seat, ref)
    if body is None or (isinstance(body, CardInstance) and not engine.catalog.cards[body.slug].is_unit):
        raise RuleRefusal("That is not a unit or hero in play.")
    if edit["edit"] == "patrol":
        line = _patrol(engine, match, seat, ref, body, edit["slot"])
    elif edit["edit"] == "hp":
        line = _hp(engine, match, seat, ref, body, edit["hp"])
    else:
        raise RuleRefusal(f"There is no correction called {edit['edit']!r}.")
    return StepResult(narration=[line], board_changed=True)


def _patrol(engine: "RulesEngine", match: MatchState, seat: int, ref: str, body, slot: str) -> str:
    if slot == OFF:
        if body.patrol_slot is None:
            raise RuleRefusal(f"{_plain(engine, body)} isn't patrolling.")
        board.sideline(match, body)
        # A lent card goes home as it leaves (`sideline`): named where it
        # stands now.
        if isinstance(body, CardInstance):
            seat = body.controller
        else:
            seat, ref = _hero_seat(match, body), hero_ref(body.slug)
        return f"Corrected: {board.named(match, seat, ref)} leaves the patrol zone."
    if slot not in PATROL_SLOTS:
        raise RuleRefusal(f"There is no patrol slot called {slot!r}.")
    if body.patrol_slot == slot:
        raise RuleRefusal(f"{_plain(engine, body)} already patrols as {SLOT_NAMES[slot]}.")
    if body.exhausted:
        raise RuleRefusal("Cards can't patrol while exhausted.", cite="UMR p. 16")
    if isinstance(body, CardInstance) and (
        engine.cant_patrol_as_printed(body) or engine.barred_by(match, body) is not None
    ):
        raise RuleRefusal(f"{_plain(engine, body)} can't patrol.")
    holder = match.patrollers(seat).get(slot)
    if holder is not None:
        raise RuleRefusal(
            f"The {SLOT_NAMES[slot]} slot already holds a patroller: move it out first."
        )
    leaving = body.patrol_slot
    body.patrol_slot = slot
    if leaving == "squad_leader":
        body.armor = 0
    if slot == "squad_leader" and seat not in engine.turn_seats(match):
        # A squad leader's armor comes at each turn's start (UMR p. 10),
        # which has been: given now, as that start would have.
        body.armor = max(body.armor, board.armor_gain(body, SQUAD_LEADER_ARMOR))
    return f"Corrected: {board.named(match, seat, ref)} patrols as {SLOT_NAMES[slot]}."


def _hp(engine: "RulesEngine", match: MatchState, seat: int, ref: str, body, hp: int) -> str:
    max_hp = engine.body_stats(match, body)[1]
    if max_hp < 1:
        raise RuleRefusal(f"{_plain(engine, body)} has no HP to set.")
    if not 1 <= hp <= max_hp:
        raise RuleRefusal(f"{_plain(engine, body)}'s HP can be set from 1 to {max_hp}.")
    body.damage = max_hp - hp
    return f"Corrected: {board.named(match, seat, ref)} has {hp} HP of {max_hp}."


def _hero_seat(match: MatchState, hero: HeroState) -> int:
    return next(player.seat for player in match.players if hero in player.heroes)


def _plain(engine: "RulesEngine", body) -> str:
    """A thing's name in a refusal, which goes to the helper alone."""
    return engine.catalog.name(body.slug)


def replayed(engine: "RulesEngine", game, match: MatchState, entry: dict):
    """A journalled correction made again in a replay
    (`codex.history.replay`), as a run the replay's readers take as any
    action's: its line, and what the position asks after it."""
    from codex.flow.driver import DriverRun
    from codex.prompts import pending

    result = apply(engine, match, entry["action"])
    result.next = pending(engine, game, match)
    return DriverRun(result=result, board_changed=True)
