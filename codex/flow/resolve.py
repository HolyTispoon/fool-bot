"""
The effects, resolved: a spell's text, a unit's arrives or attacks
trigger, an ability, Harmony's Dancer -- each a **frame** on
`MatchState.resolving`, worked through part by part (`codex.effects.EFFECTS`)
until a part has a choice to ask (`TARGET`) or the stack is empty.

**A choice is asked only where there is one**, as an attack's are: a
part with nothing it could choose is skipped -- "do as much as you can"
(Final Smash's ruling) -- and a part with one thing it could choose
takes it. Each part's target is chosen as the part resolves, not all at
once before anything happens, which is what makes the flagbearer a
question per part (Final Smash's ruling, 2016-03-19); the engine's
`target_rows` is the one reading of what may be chosen, resist paid
and the flagbearer forced included.

Two other questions stand on the stack the same way: Appel Stomp's
"you may put it on top of your draw pile" (`APPEL_STOMP_TOP`) and the
upkeep's order (`UPKEEP_ORDER`, which `codex.flow.turn` answers).

Frames run oldest first. A spell's own frame goes in before the Dancer
each Harmony owes for it, so the spell has "completely resolved" before
the Dancer is summoned (Harmony's ruling, 2016-03-02).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from codex import effects, history, tokens
from codex.components import MatchState
from codex.engine import parse_target, target_key
from codex.flow import board
from codex.flow.result import StepResult
from codex.flow.turn import damage_base, draw_cards
from codex.game import RuleRefusal
from codex.prompts import pending

if TYPE_CHECKING:
    from codex.engine import RulesEngine
    from codex.game import CodexGame

#: What a frame asks, besides a target.
APPEL_TOP = "appel_top"
UPKEEP_ORDER = "upkeep_order"
EFFECT = "effect"


def frame(effect: str, seat: int, by: str, *, source: Optional[str] = None,
          spell: Optional[str] = None, cancel_from: Optional[int] = None) -> dict:
    """
    A frame for `effect`, controlled by `seat`: `by` is its source as the
    narration names it (`{card:spark}`, `{hero:river_montoya}`),
    `source` the ref of the card in play it comes from (an arrives or
    attacks trigger's, an ability's), and `spell` the spell card being
    cast, which goes where it goes once its text is done.

    `cancel_from` is set for a spell or an ability action -- what a player
    chose to do, and so may take back while its targets are asked (the
    author, 2026-10-08) -- as the journal's length when it was played:
    the cancel replays the turn up to there (`cancel`). A trigger has
    none; it is not a choice, and must resolve.
    """
    return {
        "kind": EFFECT, "effect": effect, "seat": seat, "by": by,
        "source": source, "spell": spell, "part": 0, "taken": [],
        "flagbearer": False, "partners": [],
        "cancel_from": cancel_from, "drew": False,
    }


def cancellable(match: MatchState) -> bool:
    """
    Whether the effect asking now may be taken back: a spell or an
    ability, while the turn's snapshot it would go back to is there, and
    before it has drawn its caster a card -- a card seen cannot be
    unseen, so Appel Stomp's draw closes the door, as a draw does to
    every undo (docs/design/codex.md, "Undo's groundwork").
    """
    if not match.resolving:
        return False
    top = match.resolving[0]
    return (
        top.get("kind") == EFFECT and top.get("cancel_from") is not None
        and not top.get("drew") and history.latest_snapshot(match) is not None
        and match.combat is None
    )


def current_part(match: MatchState):
    """The part the stack's first frame stands at, or `None`."""
    if not match.resolving:
        return None
    top = match.resolving[0]
    if top.get("kind") != EFFECT:
        return None
    parts = effects.EFFECTS[top["effect"]].parts
    return parts[top["part"]] if top["part"] < len(parts) else None


def rows_for(engine: "RulesEngine", match: MatchState, top: dict):
    """What the frame's current part may choose (`RulesEngine.target_rows`)."""
    part = effects.EFFECTS[top["effect"]].parts[top["part"]]
    return engine.target_rows(
        match, top["seat"], part, taken=top["taken"], flagbearer_done=top["flagbearer"],
    )


# -- Working the stack -----------------------------------------------------------


def run(engine: "RulesEngine", match: MatchState, result: StepResult) -> bool:
    """
    Work the stack until a frame asks something or it is empty -- True
    when it is. A finished game empties it: nothing more resolves once a
    base is destroyed.
    """
    while match.resolving:
        if match.winner is not None:
            match.resolving = []
            return True
        top = match.resolving[0]
        if top.get("kind") != EFFECT:
            return False
        parts = effects.EFFECTS[top["effect"]].parts
        if top["part"] >= len(parts):
            match.resolving.pop(0)
            _finish(engine, match, top, result)
            board.settle(engine, match, result, cause=top["seat"])
            continue
        part = parts[top["part"]]
        if part.choose is None:
            _do(engine, match, top, part, None, result)
            continue
        rows = rows_for(engine, match, top)
        if not rows:
            # "Do as much as you can": a part with nothing to choose is
            # skipped, and said nothing about -- the board shows it.
            top["part"] += 1
            continue
        if len(rows) == 1:
            _choose(engine, match, top, part, rows[0], result)
            continue
        return False
    return True


def carry_on(engine: "RulesEngine", game: "CodexGame", match: MatchState,
             result: StepResult) -> StepResult:
    """
    Work the stack, then pick up whatever it interrupted: an attack whose
    attacks triggers it was resolving goes on to its damage
    (`codex.flow.combat`), and otherwise the main phase is asked again.
    """
    if run(engine, match, result) and match.combat is not None and match.winner is None:
        from codex.flow import combat

        return combat.carry_on(engine, game, match, result)
    if match.winner is not None:
        match.combat = None
        match.attacking = None
    result.next = pending(engine, game, match)
    return result


def push(match: MatchState, *frames: dict) -> None:
    """Frames onto the end of the stack, to resolve after what is there."""
    match.resolving.extend(frames)


# -- The answers ----------------------------------------------------------------------


def choose_target(engine: "RulesEngine", game: "CodexGame", match: MatchState,
                  target: str) -> StepResult:
    """The answer to `TARGET`: one of the rows the question offered."""
    part = current_part(match)
    if part is None:
        raise RuleRefusal("Nothing is waiting on a target.")
    top = match.resolving[0]
    rows = rows_for(engine, match, top)
    row = next((row for row in rows if row.key == target), None)
    if row is None:
        if any(found.flagbearer for found in rows):
            raise RuleRefusal(
                "A flagbearer must be targeted: an opponent's spell or ability that can "
                "target one must target one at least once.",
                cite="granfalloon_flagbearer",
            )
        raise RuleRefusal(f"That can't be chosen: {part.says}.")
    result = StepResult(board_changed=True)
    _choose(engine, match, top, part, row, result)
    return carry_on(engine, game, match, result)


def cancel(engine: "RulesEngine", game: "CodexGame", match: MatchState) -> StepResult:
    """
    Take back the spell or ability asking now: the turn replayed from its
    snapshot up to the action that played it (`history.replay`), so
    everything it did comes back -- the gold, the card to its place in the
    hand, the exhausted card readied, a part that resolved unasked, a
    resist paid. A tech choice the other player saved meanwhile is theirs
    and is kept: it is replayed after.
    """
    if not cancellable(match):
        raise RuleRefusal("This can't be taken back now.")
    top = match.resolving[0]
    by, seat = top["by"], top["seat"]
    played = top["cancel_from"]
    later = [
        entry for entry in match.journal[played + 1:]
        if entry["action"]["kind"] == "tech_choice"
    ]
    kept = [*match.journal[:played], *later]
    rebuilt = history.replay(
        engine, game, history.latest_snapshot(match), kept, history=match.turn_snapshots,
    )
    # Nothing is written to the event log: it would be the one trace of
    # the cast the replay has taken away, and a later replay of the turn
    # could not write it again.
    match.__dict__.update(rebuilt.__dict__)
    result = StepResult(
        narration=[f"{tokens.player(seat)} takes back {by}."], board_changed=True,
    )
    result.next = pending(engine, game, match)
    return result


def appel_stomp_top(engine: "RulesEngine", game: "CodexGame", match: MatchState,
                    top_of_deck: bool) -> StepResult:
    """Appel Stomp on top of its owner's draw pile, or into the discard
    ("If you choose not to put Appel Stomp on top of your draw pile, it
    will go to your discard pile", Sirlin, 2016-03-04)."""
    if not match.resolving or match.resolving[0].get("kind") != APPEL_TOP:
        raise RuleRefusal("Nothing is waiting on Appel Stomp.")
    top = match.resolving.pop(0)
    seat = top["seat"]
    player = match.player(seat)
    result = StepResult(board_changed=True)
    if top_of_deck:
        player.deck.append(effects.APPEL_STOMP)
        result.narration.append(
            f"{tokens.player(seat)} puts {tokens.card(effects.APPEL_STOMP)} on top of their draw pile."
        )
    else:
        player.discard.append(effects.APPEL_STOMP)
    match.record_event("appel_stomp_top", seat=seat, top=bool(top_of_deck))
    return carry_on(engine, game, match, result)


# -- One part -------------------------------------------------------------------------


def _choose(engine: "RulesEngine", match: MatchState, top: dict, part, row,
            result: StepResult) -> None:
    """Take `row` for the frame's current part: its resist paid, the
    flagbearer rule marked as obeyed for the rest of the cast, and the
    part done."""
    seat = top["seat"]
    if row.resist:
        match.player(seat).gold -= row.resist
        result.narration.append(
            f"{tokens.player(seat)} pays {tokens.gold(row.resist)} for its resist."
        )
    body = board.body_of(match, row.seat, row.ref)
    if part.targeted and row.seat != seat and body is not None and engine.is_flagbearer(body.slug):
        # The flagbearer rule is obeyed for the rest of this cast
        # (Final Smash's ruling).
        top["flagbearer"] = True
    top["taken"].append(row.key)
    _do(engine, match, top, part, (row.seat, row.ref), result)


def _do(engine: "RulesEngine", match: MatchState, top: dict, part,
        target: Optional[tuple[int, str]], result: StepResult) -> None:
    DOES[part.does](engine, match, top, part, target, result)
    top["part"] += 1
    board.settle(engine, match, result, cause=top["seat"])


def _thing(match: MatchState, target: tuple[int, str]) -> str:
    return board.named(match, *target)


def _damage(engine, match, top, part, target, result) -> None:
    seat, ref = target
    if board.is_building(ref):
        result.narration.append(f"{top['by']} deals {part.amount} to {_thing(match, target)}.")
        board.damage_building(match, seat, ref, part.amount, result)
        return
    body = board.body_of(match, seat, ref)
    named = _thing(match, target)
    landed = board.take_damage(body, part.amount)
    line = f"{top['by']} deals {landed} to {named}"
    if landed < part.amount:
        line += f" (armor takes {part.amount - landed})"
    result.narration.append(line + ".")


def _repair(engine, match, top, part, target, result) -> None:
    seat, ref = target
    repaired = board.repair_building(engine, match, seat, ref, part.amount)
    if repaired:
        result.narration.append(f"{top['by']} repairs {repaired} damage on {_thing(match, target)}.")
    else:
        # The repair ruling: an undamaged building is a legal choice,
        # and nothing happens to it.
        result.narration.append(f"{_thing(match, target)} has no damage to repair.")


def _plus_rune(engine, match, top, part, target, result) -> None:
    body = board.body_of(match, *target)
    if body.minus_runes:
        # A +1/+1 and a -1/-1 rune cancel (UMR p. 13).
        body.minus_runes -= 1
        result.narration.append(
            f"{top['by']} cancels the -1/-1 rune on {_thing(match, target)}."
        )
    else:
        body.plus_runes += 1
        result.narration.append(f"{top['by']} puts a +1/+1 rune on {_thing(match, target)}.")


def _minus_rune(engine, match, top, part, target, result) -> None:
    body = board.body_of(match, *target)
    if body.plus_runes:
        body.plus_runes -= 1
        result.narration.append(
            f"{top['by']} cancels the +1/+1 rune on {_thing(match, target)}."
        )
    else:
        body.minus_runes += 1
        result.narration.append(f"{top['by']} puts a -1/-1 rune on {_thing(match, target)}.")


def _destroy(engine, match, top, part, target, result) -> None:
    board.destroy(engine, match, [target], result, by=top["by"], cause=top["seat"])


def _weaken(engine, match, top, part, target, result) -> None:
    body = board.body_of(match, *target)
    body.modifiers.append({"kind": "atk", "amount": -part.amount, "until": "end_of_turn"})
    result.narration.append(
        f"{top['by']} gives {_thing(match, target)} -{part.amount} ATK this turn."
    )


def _return(engine, match, top, part, target, result) -> None:
    seat, ref = target
    card = board.body_of(match, seat, ref)
    line = f"{top['by']} returns {_thing(match, target)} to {tokens.player(card.owner)}'s hand."
    board.leave_play(engine, match, card, "hand")
    match.record_event("returned", slug=card.slug, owner=card.owner)
    result.narration.append(line)


def _steal(engine, match, top, part, target, result) -> None:
    seat = top["seat"]
    card = board.body_of(match, *target)
    named = _thing(match, target)
    if board.gain_control(match, card, seat):
        result.narration.append(f"{tokens.player(seat)} gains control of {named}.")
    else:
        result.narration.append(f"{named} is already theirs: gaining control of it does nothing.")


def _sideline(engine, match, top, part, target, result) -> None:
    body = board.body_of(match, *target)
    board.sideline(body)
    result.narration.append(f"{top['by']} sidelines {_thing(match, target)}.")


def _partner(engine, match, top, part, target, result) -> None:
    card = board.body_of(match, *target)
    top["partners"].append(card.id)


def _draw(engine, match, top, part, target, result) -> None:
    seat = top["seat"]
    top["drew"] = True
    drawn = draw_cards(engine, match, seat, part.amount or 1, result)
    if drawn:
        result.narration.append(f"{tokens.player(seat)} draws a card.")


def _discord(engine, match, top, part, target, result) -> None:
    seat = top["seat"]
    other = 2 if seat == 1 else 1
    hit = 0
    for card in list(match.player(other).play):
        printed = engine.catalog.cards[card.slug]
        if printed.is_unit and (printed.tech_level or 0) <= 1:
            card.modifiers.append({"kind": "atk", "amount": -2, "until": "end_of_turn"})
            card.modifiers.append({"kind": "hp", "amount": -1, "until": "end_of_turn"})
            hit += 1
    if hit:
        result.narration.append(
            f"{top['by']} gives each of {tokens.player(other)}'s tech 0 and I units "
            "-2/-1 until the end of the turn."
        )
    else:
        result.narration.append(f"{tokens.player(other)} has no tech 0 or I unit for {top['by']}.")


def _stealth(engine, match, top, part, target, result) -> None:
    seat = top["seat"]
    card = board.body_of(match, seat, top["source"])
    if card is None:
        return
    card.modifiers.append({"kind": "keyword", "keyword": "Stealth", "until": "end_of_turn"})
    result.narration.append(f"{top['by']} has stealth this turn.")


def _base_damage(engine, match, top, part, target, result) -> None:
    # "deal 1 damage to the base controlled by the same player who
    # controls the thing he's attacking" (Sirlin, 2016-03-03).
    # The line names the band the damage comes from and what the base
    # has left (the author, 2026-10-09); at 0 the next line is the
    # base destroyed, which says it.
    other = 2 if top["seat"] == 1 else 1
    source = top["by"]
    printed = effects.printing_band(top["effect"])
    if printed is not None:
        source = f"{top['by']}'s level {band_levels(engine, *printed)} ability"
    left = max(0, match.player(other).base_hp - part.amount)
    rest = f"; it has {left} left" if left else ""
    result.narration.append(f"{source} deals {part.amount} to {tokens.player(other)}'s base{rest}.")
    damage_base(match, other, part.amount, result)


def band_levels(engine, slug: str, first: int) -> str:
    """A hero's band as the levels it covers -- "5-7", or "8" for the
    top band."""
    later = [band.min_level for band in engine.catalog.heroes[slug].bands if band.min_level > first]
    last = later[0] - 1 if later else first
    return f"{first}-{last}" if last > first else str(first)


def _dancer(engine, match, top, part, target, result) -> None:
    seat = top["seat"]
    dancers = [
        card for card in match.player(seat).play
        if card.slug in (effects.DANCER, effects.ANGRY_DANCER)
    ]
    if len(dancers) >= effects.DANCER_LIMIT:
        result.narration.append(
            f"{tokens.player(seat)} has {effects.DANCER_LIMIT} Dancers already, "
            f"{tokens.card(effects.HARMONY)}'s limit."
        )
        return
    match.new_instance(effects.DANCER, seat)
    match.record_event("summoned_token", slug=effects.DANCER, seat=seat)
    result.narration.append(
        f"{tokens.card(effects.HARMONY)} summons a {tokens.card(effects.DANCER)} token "
        f"for {tokens.player(seat)}."
    )


def _stop_music(engine, match, top, part, target, result) -> None:
    """Every Dancer its controller has flips into an Angry Dancer, its
    runes and damage kept and nothing arriving (the Dancer ruling)."""
    seat = top["seat"]
    flipped = 0
    for card in match.player(seat).play:
        if card.slug == effects.DANCER:
            card.slug = effects.ANGRY_DANCER
            card.flipped = True
            flipped += 1
    if flipped:
        result.narration.append(
            f"{flipped} {tokens.card(effects.DANCER)} token"
            + ("s flip" if flipped != 1 else " flips")
            + f" into {tokens.card(effects.ANGRY_DANCER)}" + ("s." if flipped != 1 else ".")
        )
    else:
        result.narration.append(f"{tokens.player(seat)} has no Dancer to flip.")


#: What each `Part.does` does. Every key `codex.effects.EFFECTS` uses is
#: here, which `tests/test_codex_spells.py` holds.
DOES = {
    "damage": _damage,
    "repair": _repair,
    "plus_rune": _plus_rune,
    "minus_rune": _minus_rune,
    "destroy": _destroy,
    "weaken": _weaken,
    "return": _return,
    "steal": _steal,
    "sideline": _sideline,
    "partner": _partner,
    "draw": _draw,
    "discord": _discord,
    "stealth": _stealth,
    "base_damage": _base_damage,
    "dancer": _dancer,
    "stop_music": _stop_music,
}


# -- A cast's end ---------------------------------------------------------------------


def _finish(engine: "RulesEngine", match: MatchState, top: dict, result: StepResult) -> None:
    """
    A frame whose parts are done: the spell it cast goes where it goes --
    an ongoing spell into play, Two Step with the partners it chose
    attached; Appel Stomp to the question of its own place; any other to
    its owner's discard pile.
    """
    spell = top.get("spell")
    if spell is None:
        return
    seat = top["seat"]
    if spell in effects.CHANNELING:
        card = match.new_instance(spell, seat)
        card.arrived_this_turn = True
        if spell == effects.TWO_STEP:
            card.attached = list(top["partners"])
            if len(card.attached) == 2:
                first, second = (match.instance(i) for i in card.attached)
                result.narration.append(
                    f"{tokens.card(effects.TWO_STEP)} partners {tokens.card(first.slug)} and "
                    f"{tokens.card(second.slug)}: +2/+2 each while both are held."
                )
            elif card.attached:
                only = match.instance(card.attached[0])
                result.narration.append(
                    f"{tokens.card(effects.TWO_STEP)} has one partner, {tokens.card(only.slug)}: "
                    "no bonus without a second."
                )
        return
    if spell == effects.APPEL_STOMP:
        match.resolving.insert(0, {"kind": APPEL_TOP, "seat": seat})
        return
    match.player(seat).discard.append(spell)


__all__ = [
    "APPEL_TOP", "DOES", "EFFECT", "UPKEEP_ORDER", "appel_stomp_top", "carry_on",
    "choose_target", "current_part", "frame", "push", "rows_for", "run",
]
