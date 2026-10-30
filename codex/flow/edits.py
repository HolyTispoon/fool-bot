"""
A helper's corrections to a position (`/codex debug`), for a board a
bug left wrong: a unit or hero moved into a patrol slot, between slots
or out of the patrol zone; damage added to or removed from a unit, hero
or building card; and runes -- +1/+1, -1/-1, time and every named kind --
added to or removed from any card in play or hero. Not a rule and not an
action of the game's; nobody's turn is spent and nothing triggers. Each
still keeps the rules a position holds -- an exhausted card can't patrol
(UMR p. 16), one slot holds one patroller, a +1/+1 rune cancels a -1/-1
one -- since a correction that broke one would be a bug of its own; and
none kills: a death runs its triggers and asks, which only the driver
may.

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


#: A rune by the kind a correction names it with: the three every card
#: may carry, then the named ones the cards put (`CardInstance.runes`,
#: `HeroState.runes`), and what each is called in a line.
PLUS, MINUS, TIME = "plus", "minus", "time"
NAMED_RUNES = ("blood", "growth", "feather", "corpse", "javelin", "sword", "focus", "crumbling")
RUNE_WORDS = {PLUS: "+1/+1", MINUS: "-1/-1", TIME: "time", **{kind: kind for kind in NAMED_RUNES}}

#: What each correction may name: a unit or hero to patrol, anything
#: with HP to damage, any card in play or hero to carry runes.
PATROL, DAMAGE, RUNE = "patrol", "damage", "rune"


@dataclass(frozen=True)
class EditTarget:
    """A card in play or a hero a correction may name: where it is, what
    it is, its HP where it has any, its slot and its runes, for a
    frontend to word."""

    seat: int
    ref: str
    slug: str
    is_hero: bool
    hp: Optional[int]
    max_hp: Optional[int]
    slot: Optional[str]
    exhausted: bool
    runes: tuple[tuple[str, int], ...]


def targets(engine: "RulesEngine", match: MatchState, edit: str = PATROL) -> tuple[EditTarget, ...]:
    """What the correction `edit` may name, seat by seat: a seat's cards
    in the order they came into play, then its heroes -- a lent one on
    its borrower's side, where it stands. Units and heroes to patrol;
    those and the building cards, which have HP, to damage; every card
    and hero for runes."""
    found = []
    for player in match.players:
        for card in player.play:
            if _names(engine, card, edit):
                found.append(_target(engine, match, player.seat, card.ref, card))
        for owner in match.players:
            for hero in owner.heroes_on_table:
                lent = hero.lent_to is not None
                if (hero.lent_to if lent else owner.seat) != player.seat:
                    continue
                ref = f"{owner.seat}:{hero_ref(hero.slug)}" if lent else hero_ref(hero.slug)
                found.append(_target(engine, match, player.seat, ref, hero))
    return tuple(found)


def _names(engine: "RulesEngine", body, edit: str) -> bool:
    """Whether the correction `edit` may name `body`."""
    if isinstance(body, HeroState) or edit == RUNE:
        return True
    if edit == DAMAGE:
        return engine.has_hp(body)
    return engine.catalog.cards[body.slug].is_unit


def _target(engine: "RulesEngine", match: MatchState, seat: int, ref: str, body) -> EditTarget:
    max_hp = engine.body_stats(match, body)[1] if _has_hp(engine, body) else None
    return EditTarget(
        seat=seat, ref=ref, slug=body.slug, is_hero=isinstance(body, HeroState),
        hp=None if max_hp is None else max_hp - body.damage, max_hp=max_hp,
        slot=body.patrol_slot, exhausted=body.exhausted, runes=_runes(body),
    )


def _has_hp(engine: "RulesEngine", body) -> bool:
    return isinstance(body, HeroState) or engine.has_hp(body)


def _runes(body) -> tuple[tuple[str, int], ...]:
    counts = [(PLUS, body.plus_runes), (MINUS, body.minus_runes), (TIME, body.time_runes)]
    counts += sorted((body.runes or {}).items())
    return tuple((kind, count) for kind, count in counts if count)


def patrol(seat: int, ref: str, slot: str) -> dict:
    """A correction moving `ref` on `seat`'s side into `slot` of that
    side's patrol zone, or out of it (`OFF`)."""
    return {"kind": EDIT, "edit": PATROL, "seat": seat, "ref": ref, "slot": slot}


def damage(seat: int, ref: str, change: int) -> dict:
    """A correction adding `change` damage to `ref` on `seat`'s side, or
    removing it where `change` is negative."""
    return {"kind": EDIT, "edit": DAMAGE, "seat": seat, "ref": ref, "change": change}


def rune(seat: int, ref: str, kind: str, change: int) -> dict:
    """A correction adding `change` runes of `kind` to `ref` on `seat`'s
    side, or removing them where `change` is negative."""
    return {"kind": EDIT, "edit": RUNE, "seat": seat, "ref": ref, "rune": kind, "change": change}


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
    seat, ref, kind = edit["seat"], edit["ref"], edit["edit"]
    if kind not in (PATROL, DAMAGE, RUNE):
        raise RuleRefusal(f"There is no correction called {kind!r}.")
    body = board.body_of(match, seat, ref)
    if body is None or (isinstance(body, CardInstance) and not _names(engine, body, kind)):
        raise RuleRefusal({
            PATROL: "That is not a unit or hero in play.",
            DAMAGE: "That is not a unit, hero or building card in play.",
            RUNE: "That is not a card or hero in play.",
        }[kind])
    if kind == PATROL:
        line = _patrol(engine, match, seat, ref, body, edit["slot"])
    elif kind == DAMAGE:
        line = _damage(engine, match, seat, ref, body, edit["change"])
    else:
        line = _rune(engine, match, seat, ref, body, edit["rune"], edit["change"])
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


def _damage(engine: "RulesEngine", match: MatchState, seat: int, ref: str, body, change: int) -> str:
    if not change:
        raise RuleRefusal("Add or remove at least 1 damage.")
    left = body.damage + change
    if left < 0:
        raise RuleRefusal(f"{_plain(engine, body)} has only {body.damage} damage to remove.")
    max_hp = engine.body_stats(match, body)[1]
    if left >= max_hp:
        raise RuleRefusal(
            f"{_plain(engine, body)} has {max_hp} HP: {left} damage would destroy it, "
            "which a correction never does."
        )
    body.damage = left
    return f"Corrected: {board.named(match, seat, ref)} now has {left} damage, {max_hp - left} HP of {max_hp}."


def _rune(engine: "RulesEngine", match: MatchState, seat: int, ref: str, body, kind: str,
          change: int) -> str:
    if kind not in RUNE_WORDS:
        raise RuleRefusal(f"There is no rune called {kind!r}.")
    if not change:
        raise RuleRefusal("Add or remove at least 1 rune.")
    plain = _plain(engine, body)
    if kind in (PLUS, MINUS) and not _has_hp(engine, body):
        raise RuleRefusal(f"{plain} has no ATK or HP for {RUNE_WORDS[kind]} runes to change.")
    before = _rune_counts(body)
    if change < 0 and before[kind] < -change:
        having = f"only {_count(before[kind], kind)}" if before[kind] else _count(0, kind)
        raise RuleRefusal(f"{plain} has {having} to remove.")
    if kind == TIME and change < 0 and before[kind] + change == 0 and \
            (engine.fading(body) or isinstance(body, HeroState)):
        # Fading's last time rune sacrifices it as the upkeep takes it
        # (`board.remove_time_rune`), which a correction may not run.
        raise RuleRefusal(f"{plain} loses its last time rune at its controller's upkeep, not by hand.")
    if kind == PLUS:
        board.add_plus_rune(body, change) if change > 0 else _take(body, "plus_runes", -change)
    elif kind == MINUS:
        board.add_minus_rune(body, change) if change > 0 else _take(body, "minus_runes", -change)
    elif kind == TIME:
        body.time_runes += change
    else:
        count = body.runes.get(kind, 0) + change
        if count:
            body.runes[kind] = count
        else:
            body.runes.pop(kind, None)
    if _has_hp(engine, body) and board.lethal(engine, match, body):
        _put_back(body, before)
        raise RuleRefusal(f"That would destroy {plain}, which a correction never does.")
    after = _rune_counts(body)
    said = [
        _count(after[changed], changed)
        for changed in (kind, *(other for other in (PLUS, MINUS) if other != kind))
        if changed == kind or after[changed] != before[changed]
    ]
    return f"Corrected: {board.named(match, seat, ref)} now has {' and '.join(said)}."


def _rune_counts(body) -> dict[str, int]:
    return {PLUS: body.plus_runes, MINUS: body.minus_runes, TIME: body.time_runes,
            **{kind: body.runes.get(kind, 0) for kind in NAMED_RUNES}, **(body.runes or {})}


def _put_back(body, counts: dict[str, int]) -> None:
    body.plus_runes, body.minus_runes, body.time_runes = counts[PLUS], counts[MINUS], counts[TIME]
    body.runes = {kind: count for kind, count in counts.items()
                  if kind not in (PLUS, MINUS, TIME) and count}


def _take(body, field: str, count: int) -> None:
    setattr(body, field, getattr(body, field) - count)


def _count(count: int, kind: str) -> str:
    """"3 growth runes", "1 +1/+1 rune", "no time runes"."""
    word = RUNE_WORDS[kind]
    if not count:
        return f"no {word} runes"
    return f"{count} {word} rune{'' if count == 1 else 's'}"


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
