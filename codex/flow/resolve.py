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
from codex.components import CardInstance, MatchState, hero_ref
from codex.engine import WORKERS, parse_target, target_key
from codex.flow import board
from codex.flow.result import StepResult
from codex.flow.turn import damage_base, draw_cards, gain_gold
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
          spell: Optional[str] = None, cancel_from: Optional[int] = None,
          boosted: bool = False, origin: Optional[str] = None) -> dict:
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
        **({"boosted": True} if boosted else {}),
        **({"origin": origin} if origin else {}),
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


#: What the frame at the top of the stack is asking, where it is an
#: effect's: a target, a mode, or how to divide the damage.
ASKS_TARGET = "target"
ASKS_MODE = "mode"
ASKS_DIVIDE = "divide"


def asking(match: MatchState) -> str:
    """Which question the effect on top of the stack asks: its mode
    (`MODE_CHOICE`), the split of its damage (`DIVIDE_DAMAGE`), or a
    target (`TARGET`)."""
    top = match.resolving[0]
    part = current_part(match)
    if part is not None and part.does == "mode" and "mode" not in top:
        return ASKS_MODE
    if top.get("split") is not None:
        return ASKS_DIVIDE
    return ASKS_TARGET


def _unique(ref: str) -> bool:
    """Whether a pick stays where it was, so a part choosing more than
    one may not choose it again: a unit, a hero, a building -- not a side's
    workers, which are many alike, nor a card in a hand or codex, which
    the pick takes away."""
    from codex.engine import CODEX, HAND

    return ref != WORKERS and not ref.startswith((HAND, CODEX))


def rows_for(engine: "RulesEngine", match: MatchState, top: dict):
    """What the frame's current part may choose (`RulesEngine.target_rows`),
    less what this part has already chosen where a pick stays."""
    part = effects.EFFECTS[top["effect"]].parts[top["part"]]
    rows = engine.target_rows(
        match, top["seat"], part, taken=top["taken"], flagbearer_done=top["flagbearer"],
        frame=top,
    )
    picks = top.get("picks") or []
    return tuple(row for row in rows if not (row.key in picks and _unique(row.ref)))


def pick_limit(engine: "RulesEngine", match: MatchState, top: dict, part) -> int:
    """How many things `part` chooses at most: its `most`, or -- `0` --
    as many as the damage it divides, at least 1 each (the Card FAQ)."""
    if part.does == "divide":
        total = damage_amount(engine, match, top, part.amount)
        return total if not part.most else min(part.most, total)
    return part.most or 1


def offers_done(top: dict, part) -> bool:
    """Whether the question offers **Done**: the part has chosen as many
    as it must (`Part.least`)."""
    return len(top.get("picks") or []) >= part.least


def damage_amount(engine: "RulesEngine", match: MatchState, top: dict, amount: int) -> int:
    """What a part of this frame deals: its printed amount, and Hotter
    Fire's bonus on a red spell's or ability's damage (commit 4)."""
    return amount + engine.damage_bonus(match, top)


def _applies(part, top: dict) -> bool:
    """Whether the frame does `part` at all: a part of one mode only in
    that mode or both, a boosted part only where it was boosted."""
    if part.only is not None and top.get("mode") not in (part.only, "both"):
        return False
    if part.when == "boosted" and not top.get("boosted"):
        return False
    return True


def _next_part(top: dict) -> None:
    top["part"] += 1
    top["picks"] = []
    top.pop("split", None)


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
        if not _applies(part, top):
            _next_part(top)
            continue
        if part.does == "mode":
            if "mode" not in top:
                # "If you boosted, choose both"; otherwise one is asked,
                # unless only one can be done (Land Octopus's).
                if top.get("boosted"):
                    top["mode"] = "both"
                else:
                    possible = [key for key, _, allowed in engine.mode_rows(match, top, part) if allowed]
                    if len(possible) != 1:
                        return False
                    top["mode"] = possible[0]
            _next_part(top)
            continue
        if top.get("split") is not None:
            if sum(top["split"].values()) < damage_amount(engine, match, top, part.amount):
                return False
            _deal_split(engine, match, top, part, result)
            continue
        if part.choose is None:
            _do(engine, match, top, part, None, result)
            continue
        rows = rows_for(engine, match, top)
        picks = top.setdefault("picks", [])
        if len(picks) >= pick_limit(engine, match, top, part) or not rows:
            # "Do as much as you can": a part with nothing (more) to
            # choose is done, and said nothing about -- the board shows it.
            _end_picks(engine, match, top, part, result)
            continue
        if len(picks) < part.least and len(rows) == 1:
            _choose(engine, match, top, part, rows[0], result)
            continue
        return False
    # The stack empty, the position's own consequences: a card played
    # with nothing to resolve -- a second copy of a legendary unit, say --
    # is settled here, and what that sets off is worked in turn.
    board.settle(engine, match, result)
    if match.resolving and match.winner is None:
        return run(engine, match, result)
    return True


def carry_on(engine: "RulesEngine", game: "CodexGame", match: MatchState,
             result: StepResult) -> StepResult:
    """
    Work the stack, then pick up whatever it interrupted: an attack whose
    attacks triggers it was resolving goes on to its damage
    (`codex.flow.combat`), and otherwise the main phase is asked again.
    """
    done = run(engine, match, result)
    if not done and match.resolving and match.resolving[0].get("kind") == UPKEEP_ORDER:
        # Under way in an upkeep: the upkeep goes on (`codex.flow.turn`).
        from codex.flow import turn

        return turn.carry_on_upkeep(engine, game, match, result)
    if done and match.combat is not None and match.winner is None:
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
    pick done -- the part done with it where it chooses one, and every
    pick's share dealt at once where it divides damage (`_end_picks`)."""
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
    top.setdefault("picks", []).append(row.key)
    if part.does != "divide":
        DOES[part.does](engine, match, top, part, (row.seat, row.ref), result)
        board.settle(engine, match, result, cause=top["seat"])
    if len(top["picks"]) >= pick_limit(engine, match, top, part):
        _end_picks(engine, match, top, part, result)


def _end_picks(engine: "RulesEngine", match: MatchState, top: dict, part,
               result: StepResult) -> None:
    """A part has chosen what it will: on to the next -- or, where it
    divides damage among what it chose, to the split: 1 each (the Card
    FAQ), and the rest asked of the caster where there is more than one
    target and damage left over."""
    picks = top.get("picks") or []
    if part.does == "divide" and picks:
        total = damage_amount(engine, match, top, part.amount)
        top["split"] = {key: 1 for key in picks}
        if len(picks) == 1:
            top["split"][picks[0]] = total
        if sum(top["split"].values()) >= total:
            _deal_split(engine, match, top, part, result)
        return
    _next_part(top)


def _deal_split(engine: "RulesEngine", match: MatchState, top: dict, part,
                result: StepResult) -> None:
    """The divided damage, dealt at once to every target as split."""
    split = top["split"]
    for key, amount in split.items():
        target = parse_target(key)
        _deal(engine, match, top, target, amount, result)
    board.settle(engine, match, result, cause=top["seat"])
    _next_part(top)


def add_to_split(engine: "RulesEngine", game: "CodexGame", match: MatchState,
                 target: str) -> StepResult:
    """The answer to `DIVIDE_DAMAGE`: a point more of the damage onto one
    of the targets chosen, until it is all placed."""
    if not match.resolving or asking(match) != ASKS_DIVIDE:
        raise RuleRefusal("Nothing is waiting on damage to divide.")
    top = match.resolving[0]
    if target not in top["split"]:
        raise RuleRefusal("That is not one of the targets chosen.")
    top["split"][target] += 1
    return carry_on(engine, game, match, StepResult(board_changed=True))


def choose_mode(engine: "RulesEngine", game: "CodexGame", match: MatchState,
                mode: str) -> StepResult:
    """The answer to `MODE_CHOICE`: one of the modes that can be done."""
    if not match.resolving or asking(match) != ASKS_MODE:
        raise RuleRefusal("Nothing is waiting on a choice of one.")
    top = match.resolving[0]
    part = current_part(match)
    allowed = {key for key, _, can in engine.mode_rows(match, top, part) if can}
    if mode not in allowed:
        raise RuleRefusal("That is not one of the choices offered.")
    top["mode"] = mode
    match.record_event("mode", effect=top["effect"], mode=mode)
    return carry_on(engine, game, match, StepResult(board_changed=True))


def done_choosing(engine: "RulesEngine", game: "CodexGame", match: MatchState) -> StepResult:
    """**Done** on a `TARGET` that offers it: the part chooses nothing
    more -- "up to two", "you may"."""
    part = current_part(match)
    if part is None or asking(match) != ASKS_TARGET:
        raise RuleRefusal("Nothing is waiting on a target.")
    top = match.resolving[0]
    if not offers_done(top, part):
        raise RuleRefusal(f"That has to be chosen: {part.says}.")
    result = StepResult(board_changed=True)
    _end_picks(engine, match, top, part, result)
    return carry_on(engine, game, match, result)


def _do(engine: "RulesEngine", match: MatchState, top: dict, part,
        target: Optional[tuple[int, str]], result: StepResult) -> None:
    DOES[part.does](engine, match, top, part, target, result)
    _next_part(top)
    board.settle(engine, match, result, cause=top["seat"])


def _thing(match: MatchState, target: tuple[int, str]) -> str:
    return board.named(match, *target)


def _damage(engine, match, top, part, target, result) -> None:
    seat, ref = target
    amount = part.amount
    if part.building is not None and engine.is_building_ref(match, seat, ref):
        amount = part.building
    _deal(engine, match, top, target, damage_amount(engine, match, top, amount), result)


def _deal(engine, match, top, target, amount: int, result) -> int:
    """`amount` damage from the frame onto a unit, hero or building, said;
    what landed on a unit or hero (all of it on a building)."""
    seat, ref = target
    if board.is_building(ref):
        result.narration.append(f"{top['by']} deals {amount} to {_thing(match, target)}.")
        board.damage_building(match, seat, ref, amount, result)
        return amount
    body = board.body_of(match, seat, ref)
    if body is None:
        return 0
    named = _thing(match, target)
    landed = board.take_damage(body, amount)
    line = f"{top['by']} deals {landed} to {named}"
    if landed < amount:
        line += f" (armor takes {amount - landed})"
    result.narration.append(line + ".")
    return landed


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
    other = 2 if top["seat"] == 1 else 1
    amount = damage_amount(engine, match, top, part.amount)
    result.narration.append(f"{top['by']} deals {amount} to {tokens.player(other)}'s base.")
    damage_base(match, other, amount, result)


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


def _gain_gold(engine, match, top, part, target, result) -> None:
    seat = top["seat"]
    gained = gain_gold(match, seat, part.amount)
    result.narration.append(f"{tokens.player(seat)} gains {tokens.gold(gained)} from {top['by']}.")


def steal_gold(match: MatchState, seat: int, other: int, amount: int) -> int:
    """`seat` takes up to `amount` of `other`'s gold -- "If that player has
    less than you would steal, then steal as much as you can" (UMR
    p. 18) -- gaining what was taken, to the cap; what was taken."""
    taken = min(amount, match.player(other).gold)
    match.player(other).gold -= taken
    gain_gold(match, seat, taken)
    return taken


def _coin(engine, match, top, part, target, result) -> None:
    """Rickety Mine's coin: heads, "Phew!", which does nothing; tails, the
    mine sacrificed and its controller's base taking `part.amount`, with
    Hotter Fire's +1 like any red card's damage (the author, 2026-10-09).
    The side is journalled beside the shuffles (`StepResult.drawn`), so a
    replay lands it again."""
    seat = top["seat"]
    side = engine.flip_coin()
    result.drawn.append([effects.COIN, side])
    match.record_event("coin", seat=seat, side=side)
    if side == "heads":
        result.narration.append(f"{top['by']} flips a coin: heads. Phew!")
        return
    mine = board.body_of(match, seat, top["source"]) if top.get("source") else None
    amount = damage_amount(engine, match, top, part.amount)
    result.narration.append(
        f"{top['by']} flips a coin: tails. It is sacrificed, and "
        f"{tokens.player(seat)}'s base takes {amount} damage."
    )
    if mine is not None:
        board.sacrifice(engine, match, mine)
    damage_base(match, seat, amount, result)


def _pillage(engine, match, top, part, target, result) -> None:
    """Pillage: 1 damage to the base and 1 gold stolen from its player --
    2 and 2 where the caster has a Pirate."""
    seat = top["seat"]
    other, _ = target
    pirate = any(
        engine.catalog.cards[card.slug].is_unit and effects.PIRATE in engine.subtype_of(card)
        for card in match.player(seat).play
    )
    steal = 2 if pirate else part.amount
    amount = damage_amount(engine, match, top, steal)
    result.narration.append(f"{top['by']} deals {amount} to {tokens.player(other)}'s base.")
    damage_base(match, other, amount, result)
    taken = steal_gold(match, seat, other, steal) if other != seat else 0
    if taken:
        result.narration.append(
            f"{tokens.player(seat)} steals {tokens.gold(taken)} from {tokens.player(other)}."
        )


def _trash(engine, match, top, part, target, result) -> None:
    """A worker, or a card in play, out of the game (UMR p. 13, 15): a
    worker unseen and all alike (Detonate's rulings)."""
    seat, ref = target
    if ref == WORKERS:
        if board.trash_worker(match, seat):
            result.narration.append(
                f"{top['by']} trashes one of {tokens.player(seat)}'s workers: "
                f"{match.player(seat).workers} left."
            )
        return
    card = board.body_of(match, seat, ref)
    if card is None:
        return
    result.narration.append(f"{top['by']} trashes {_thing(match, target)}.")
    board.trash(engine, match, card)


def _desperation(engine, match, top, part, target, result) -> None:
    """Desperation: with the hand empty -- it is, once Desperation is the
    one card in it and played (its rulings) -- trashed, and three cards
    drawn; and the hand discarded at the end of the main phase, whatever
    (`PlayerState.discards_at_main_end`, which the patrol lock reads)."""
    seat = top["seat"]
    player = match.player(seat)
    if not player.hand:
        top["trashed"] = True
        top["drew"] = True
        drawn = draw_cards(engine, match, seat, part.amount, result)
        result.narration.append(
            f"{top['by']} is trashed, and {tokens.player(seat)} draws "
            f"{drawn} card{'' if drawn == 1 else 's'}."
        )
    player.discards_at_main_end = True
    result.narration.append(
        f"{tokens.player(seat)} discards their hand at the end of the main phase."
    )


# -- Red and green's handlers (step 11) -----------------------------------------


def _own_base_damage(engine, match, top, part, target, result) -> None:
    """Careless Musketeer's "and 1 damage to your base"."""
    seat = top["seat"]
    amount = damage_amount(engine, match, top, part.amount)
    result.narration.append(f"{top['by']} deals {amount} to {tokens.player(seat)}'s own base.")
    damage_base(match, seat, amount, result)


def _active_base_damage(engine, match, top, part, target, result) -> None:
    """Crash Bomber's "Dies on another player's turn: Deal 1 damage to that
    player's base" -- the base of whoever's turn it is."""
    seat = match.active
    amount = damage_amount(engine, match, top, part.amount)
    result.narration.append(f"{top['by']} deals {amount} to {tokens.player(seat)}'s base.")
    damage_base(match, seat, amount, result)


def _damage_ready(engine, match, top, part, target, result) -> None:
    """Firehouse: its 2, and readied where the 2 destroyed what it hit --
    so it can fire again (its rulings)."""
    _damage(engine, match, top, part, target, result)
    seat, ref = target
    if board.is_building(ref):
        destroyed = not board.still_there(match, seat, ref)
    else:
        body = board.body_of(match, seat, ref)
        destroyed = body is None or board.lethal(engine, match, body)
    house = board.body_of(match, top["seat"], top["source"]) if top.get("source") else None
    if destroyed and house is not None:
        house.exhausted = False
        result.narration.append(f"{top['by']} readies: its 2 destroys what it hit.")


def _runes_on_self(engine, match, top, part, target, result) -> None:
    """Spore Shambler: "Put two +1/+1 runes on this." """
    body = board.body_of(match, top["seat"], top["source"])
    if body is None:
        return
    board.add_plus_rune(body, part.amount)
    result.narration.append(f"{top['by']} gets {part.amount} +1/+1 runes.")


def _elm_runes(engine, match, top, part, target, result) -> None:
    """Blooming Elm: three +1/+1 runes on a unit, one on a hero -- and none
    on one that has any already (its ruling: a legal choice, no more)."""
    body = board.body_of(match, *target)
    named = _thing(match, target)
    if body.plus_runes:
        result.narration.append(f"{named} has +1/+1 runes already: {top['by']} adds none.")
        return
    count = part.amount if isinstance(body, CardInstance) else 1
    board.add_plus_rune(body, count)
    result.narration.append(
        f"{top['by']} puts {count} +1/+1 rune{'' if count == 1 else 's'} on {named}."
    )


def _instant_build(engine, match, top, part, target, result) -> None:
    """Verdant Tree: its controller's tech buildings build instantly this
    turn -- each finished as it is built, so several in a row (its
    rulings), and any under construction finished now."""
    seat = top["seat"]
    tree = board.body_of(match, seat, top["source"])
    if tree is not None:
        tree.modifiers.append({"kind": "instant_build", "until": "end_of_turn"})
    finished = finish_buildings(match, seat)
    line = f"{tokens.player(seat)}'s tech buildings build instantly this turn"
    if finished:
        line += ": " + ", ".join(finished) + " finished now"
    result.narration.append(line + ".")


def finish_buildings(match: MatchState, seat: int) -> list[str]:
    """Every tech building of `seat`'s under construction, finished; their
    names."""
    names = {"tech1": "Tech I", "tech2": "Tech II", "tech3": "Tech III"}
    done = []
    for name, building in match.player(seat).buildings.items():
        if building is not None and building.under_construction and not building.destroyed:
            building.under_construction = False
            done.append(names[name])
    return done


def _private_slug(ref: str) -> str:
    return ref.split(":", 1)[1]


def _sanatorium(engine, match, top, part, target, result) -> None:
    """Sanatorium: a tech 0, I or II unit from the hand into play, free
    and needing no building (its ruling), with haste and ephemeral for
    good (its ruling)."""
    card = _from_hand(engine, match, top, target, result)
    if card is not None:
        for keyword in ("Haste", "Ephemeral"):
            card.modifiers.append({"kind": "keyword", "keyword": keyword, "until": None})


def _from_hand(engine, match, top, target, result):
    seat, ref = target
    slug = _private_slug(ref)
    player = match.player(seat)
    if slug not in player.hand:
        return None
    player.hand.remove(slug)
    card = board.put_into_play(engine, match, slug, seat, from_hand=True)
    atk, hp = engine.unit_stats(card, match)
    result.narration.append(
        f"{top['by']} puts {tokens.card(slug)} from {tokens.player(seat)}'s hand into play: {atk}/{hp}."
    )
    return card


def _put_into_play(engine, match, top, part, target, result) -> None:
    """A unit into play from the hand or the codex (UMR p. 15): Feral
    Strike's, Circle of Life's, Calamandra's -- no cost paid, no building
    needed, and from the codex a card of its owner's from then on."""
    seat, ref = target
    from codex.engine import CODEX

    if not ref.startswith(CODEX):
        _from_hand(engine, match, top, target, result)
        return
    slug = _private_slug(ref)
    player = match.player(seat)
    if player.codex.get(slug, 0) <= 0:
        return
    player.codex[slug] -= 1
    card = board.put_into_play(engine, match, slug, seat, from_hand=False)
    atk, hp = engine.unit_stats(card, match)
    result.narration.append(
        f"{top['by']} puts {tokens.card(slug)} from {tokens.player(seat)}'s codex into play: {atk}/{hp}."
    )


def _fetch(engine, match, top, part, target, result) -> None:
    """Feral Strike: a unit from the codex into the hand, revealed -- and
    so named."""
    seat, ref = target
    slug = _private_slug(ref)
    player = match.player(seat)
    if player.codex.get(slug, 0) <= 0:
        return
    player.codex[slug] -= 1
    player.hand.append(slug)
    result.narration.append(
        f"{tokens.player(seat)} fetches {tokens.card(slug)} from their codex into their hand."
    )


def _discard(engine, match, top, part, target, result) -> None:
    """Calamandra's cost: a card from the hand, face-down to the discard
    pile -- counted, never named."""
    seat, ref = target
    slug = _private_slug(ref)
    player = match.player(seat)
    if slug not in player.hand:
        return
    player.hand.remove(slug)
    player.discard.append(slug)
    if len(top.get("picks") or []) == part.most:
        result.narration.append(f"{tokens.player(seat)} discards {part.most} cards for {top['by']}.")


def _token(engine, match, top, part, target, result) -> None:
    board.summon(engine, match, part.token, top["seat"], part.amount, result, by=top["by"])


def _token_for_opponent(engine, match, top, part, target, result) -> None:
    """Final Showdown's Hunters: summoned for the opponent, who controls
    them, in their play zone and never their patrol zone (the Card FAQ)."""
    other = 2 if top["seat"] == 1 else 1
    board.summon(engine, match, part.token, other, part.amount, result, by=top["by"])


def _exhaust_self(engine, match, top, part, target, result) -> None:
    """"Arrives: Exhausted." -- the Pandas."""
    body = board.body_of(match, top["seat"], top["source"])
    if body is not None:
        body.exhausted = True
        result.narration.append(f"{top['by']} arrives exhausted.")


def _buff(engine, match, top, part, target, result) -> None:
    """+X ATK and +X armor this turn (Rampant Growth, Dinosize, Argagarg)
    -- the armor temporary, gone unused at the end of the turn (UMR
    p. 16)."""
    body = board.body_of(match, *target)
    body.modifiers.append({"kind": "atk", "amount": part.amount, "until": "end_of_turn"})
    board.grant_armor(body, part.amount)
    result.narration.append(
        f"{top['by']} gives {_thing(match, target)} +{part.amount} ATK and +{part.amount} armor this turn."
    )


def _feather(engine, match, top, part, target, result) -> None:
    """Fairie Dragon: a feather rune -- 3/1 and flying while any Fairie
    Dragon is in play (commit 4's grant)."""
    body = board.body_of(match, *target)
    body.runes["feather"] = body.runes.get("feather", 0) + 1
    result.narration.append(f"{top['by']} puts a feather rune on {_thing(match, target)}.")


def _destroy_any(engine, match, top, part, target, result) -> None:
    """Tyrannosaurus Rex: a unit or an upgrade destroyed, or a worker --
    destroyed, a worker is trashed (its rulings)."""
    seat, ref = target
    if ref == WORKERS:
        _trash(engine, match, top, part, target, result)
        return
    card = board.body_of(match, seat, ref)
    if card is not None and engine.catalog.cards[card.slug].is_upgrade:
        _destroy_card(engine, match, top, part, target, result)
        return
    _destroy(engine, match, top, part, target, result)


def _destroy_card(engine, match, top, part, target, result) -> None:
    """An upgrade or an ongoing spell destroyed: to its owner's discard."""
    card = board.body_of(match, *target)
    if card is None:
        return
    result.narration.append(f"{top['by']} destroys {_thing(match, target)}.")
    board.leave_play(engine, match, card, "discard")
    match.record_event("destroyed", slug=card.slug, owner=card.owner)


def _free_spell(engine, match, top, part, target, result) -> None:
    """Cinderblast Dragon: a non-ultimate Fire spell from the hand or the
    codex, played free and with no Fire hero needed (its rulings) -- its
    frame at the front of the stack, so it resolves now, and the spell to
    the discard after: from the codex, a card of its owner's from then
    on."""
    from codex.engine import CODEX

    seat, ref = target
    slug = _private_slug(ref)
    player = match.player(seat)
    if ref.startswith(CODEX):
        if player.codex.get(slug, 0) <= 0:
            return
        player.codex[slug] -= 1
        where = "codex"
    else:
        if slug not in player.hand:
            return
        player.hand.remove(slug)
        where = "hand"
    player.spells_played += 1
    match.record_event("played", slug=slug, cost=0, free=True)
    result.narration.append(
        f"{top['by']}: {tokens.player(seat)} plays {tokens.card(slug)} from their {where}, free."
    )
    spell = frame(slug, seat, tokens.card(slug), spell=slug, origin=slug)
    harmonies = [
        frame("harmony_dancer", seat, tokens.card(effects.HARMONY), source=harmony.ref)
        for harmony in player.play if harmony.slug == effects.HARMONY
    ]
    # After this frame's part, before anything else on the stack.
    match.resolving[1:1] = [spell, *harmonies]


def _kidnap(engine, match, top, part, target, result) -> None:
    """Kidnapping: control of the unit until the end of the turn, readied,
    with haste -- back to whoever had it then (its rulings)."""
    seat = top["seat"]
    card = board.body_of(match, *target)
    named = _thing(match, target)
    before = card.controller
    if not board.gain_control(match, card, seat):
        return
    card.returns_to = before
    card.exhausted = False
    card.modifiers.append({"kind": "keyword", "keyword": "Haste", "until": "end_of_turn"})
    result.narration.append(
        f"{tokens.player(seat)} kidnaps {named} until the end of the turn: readied, with haste."
    )


def _anarchy(engine, match, top, part, target, result) -> None:
    """Maximum Anarchy: every unit and hero, destroyed -- its caster's
    heroes too (its rulings)."""
    everything = [
        (player.seat, card.ref) for player in match.players for card in player.play
        if engine.catalog.cards[card.slug].is_unit
    ] + [
        (player.seat, hero_ref(hero.slug)) for player in match.players
        for hero in player.heroes_in_play
    ]
    result.narration.append(f"{top['by']} destroys every unit and hero.")
    board.destroy(engine, match, everything, result, cause=top["seat"])


def _bloodlust(engine, match, top, part, target, result) -> None:
    body = board.body_of(match, *target)
    body.modifiers.append({"kind": "atk", "amount": part.amount, "until": "end_of_turn"})
    body.modifiers.append({"kind": "keyword", "keyword": "Haste", "until": "end_of_turn"})
    body.modifiers.append({"kind": "bloodlust", "until": "end_of_turn"})
    result.narration.append(
        f"{top['by']} gives {_thing(match, target)} +1 ATK and haste this turn; "
        "it takes 1 damage at the end of the turn."
    )


def _charge(engine, match, top, part, target, result) -> None:
    body = board.body_of(match, *target)
    body.modifiers.append({"kind": "atk", "amount": part.amount, "until": "end_of_turn"})
    body.modifiers.append({"kind": "keyword", "keyword": "Haste", "until": "end_of_turn"})
    result.narration.append(f"{top['by']} gives {_thing(match, target)} haste and +1 ATK this turn.")


def _peace(engine, match, top, part, target, result) -> None:
    seat = top["seat"]
    match.player(seat).peace = True
    result.narration.append(
        f"Until {tokens.player(seat)}'s next turn, their units can't patrol and "
        "opposing units can't attack them."
    )


def _circle_sacrifice(engine, match, top, part, target, result) -> None:
    """Circle of Life: the green unit sacrificed, and its tech remembered
    for the second part -- "If you do"."""
    card = board.body_of(match, *target)
    top["sacrificed_tech"] = engine.catalog.cards[card.slug].tech_level or 0
    result.narration.append(f"{tokens.player(top['seat'])} sacrifices {_thing(match, target)}.")
    board.sacrifice(engine, match, card)


def _stampede(engine, match, top, part, target, result) -> None:
    """Stampede: its caster's units +3 ATK and +3 armor this turn, their
    excess combat damage to units and heroes onto that opponent's base --
    continuous, so a unit that comes under them later this turn gets it
    too (`board.lasting_armor`; the author, 2026-10-09)."""
    seat = top["seat"]
    match.player(seat).lasting.append({"kind": "stampede", "until": "end_of_turn"})
    for card in match.player(seat).play:
        if engine.catalog.cards[card.slug].is_unit:
            board.grant_armor(card, effects.STAMPEDE_BONUS)
    result.narration.append(
        f"{top['by']}: {tokens.player(seat)}'s units get +3 ATK and +3 armor this turn, "
        "their excess combat damage to the opposing base."
    )


def _ferocity(engine, match, top, part, target, result) -> None:
    """Ferocity: its caster's units armor piercing and swift strike until
    the caster's next upkeep -- continuous, every unit they control while
    it lasts (the author, 2026-10-09)."""
    seat = top["seat"]
    match.player(seat).lasting.append({"kind": "ferocity", "until": "upkeep", "seat": seat})
    result.narration.append(
        f"{top['by']}: {tokens.player(seat)}'s units get armor piercing and swift strike "
        "until their next upkeep."
    )


def _attach(engine, match, top, part, target, result) -> None:
    """What an attaching spell attaches to, kept on the frame until the
    spell goes into play with it (`_finish`)."""
    top["host"] = target_key(*target)


def _firebird(engine, match, top, part, target, result) -> None:
    """Molting Firebird: 1 damage to every unit and hero the opponent it
    damaged controls."""
    other = top.get("against") or (2 if top["seat"] == 1 else 1)
    amount = damage_amount(engine, match, top, part.amount)
    player = match.player(other)
    hit = [card for card in player.play if engine.catalog.cards[card.slug].is_unit]
    for card in hit:
        board.take_damage(card, amount)
    for hero in player.heroes_in_play:
        board.take_damage(hero, amount)
    result.narration.append(
        f"{top['by']} deals {amount} to every unit and hero {tokens.player(other)} controls."
    )


def _mirror(engine, match, top, part, target, result) -> None:
    """Chaos Mirror: once both are chosen, their printed ATKs swapped
    until the end of the turn -- what runes, attachments and other
    effects add stays each one's own (the Card FAQ)."""
    picks = top.get("picks") or []
    if len(picks) < 2:
        return
    first, second = (board.body_of(match, *parse_target(key)) for key in picks[:2])
    if first is None or second is None:
        return
    one, other = engine.printed_atk(first), engine.printed_atk(second)
    for body, atk in ((first, other), (second, one)):
        body.printed = {**(body.printed or {}), "atk": atk}
    names = [_thing(match, parse_target(key)) for key in picks[:2]]
    result.narration.append(
        f"{top['by']} swaps the printed ATK of {names[0]} and {names[1]} until the end of the turn: "
        f"{other} and {one}."
    )


def _polymorph(engine, match, top, part, target, result) -> None:
    """Polymorph: Squirrel: a 1/1 green Squirrel with no abilities until
    its caster's next upkeep -- no arrival, its runes, damage and
    attachments kept, the one-time effects on it before gone, and its
    tech level the same (its rulings)."""
    card = board.body_of(match, *target)
    named = _thing(match, target)
    lent = sum(m.get("amount", 0) for m in card.modifiers if m.get("kind") == "armor")
    card.armor = max(0, card.armor - lent)
    card.modifiers = []
    card.printed = {"polymorph": top["seat"]}
    result.narration.append(
        f"{top['by']} transforms {named} into a 1/1 {tokens.card(effects.POLYMORPH_INTO)} "
        f"with no abilities until {tokens.player(top['seat'])}'s next upkeep."
    )


def _trash_workers(engine, match, top, part, target, result) -> None:
    """Land Octopus's two workers, sacrificed -- and so trashed (its
    ruling)."""
    seat = top["seat"]
    gone = sum(1 for _ in range(part.amount) if board.trash_worker(match, seat))
    result.narration.append(
        f"{tokens.player(seat)} sacrifices {gone} workers to {top['by']}: "
        f"{match.player(seat).workers} left."
    )


def _sacrifice_self(engine, match, top, part, target, result) -> None:
    card = board.body_of(match, top["seat"], top["source"])
    if card is None:
        return
    result.narration.append(f"{tokens.player(top['seat'])} sacrifices {top['by']}.")
    board.sacrifice(engine, match, card)


def _shove(engine, match, top, part, target, result) -> None:
    """Zane's shove, first: the patroller chosen; its new slot is the next
    part's, and its damage the one after."""


def _shove_slot(engine, match, top, part, target, result) -> None:
    from codex.engine import SLOT

    side, ref = target
    shoved = parse_target(top["taken"][0])
    body = board.body_of(match, *shoved)
    if body is None:
        return
    slot = ref[len(SLOT):]
    body.patrol_slot = slot
    if slot != "squad_leader":
        body.armor = 0
    result.narration.append(
        f"{top['by']} shoves {_thing(match, shoved)} to the {slot.replace('_', ' ')} slot."
    )


def _damage_shoved(engine, match, top, part, target, result) -> None:
    """Zane's 1 to the patroller he shoved -- or could not, with every
    slot filled (his rulings) -- and his kill bonus where it is lethal."""
    if not top["taken"]:
        return
    shoved = parse_target(top["taken"][0])
    body = board.body_of(match, *shoved)
    if body is None:
        return
    slot = body.patrol_slot
    _deal(engine, match, top, shoved, damage_amount(engine, match, top, part.amount), result)
    if board.lethal(engine, match, body):
        board.kill_bonus(engine, match, top["seat"], top.get("origin"), slot, result)


#: The parts `run` works itself rather than a handler: "choose one" and
#: divided damage.
STRUCTURAL = frozenset({"mode", "divide"})

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
    "gain_gold": _gain_gold,
    "coin": _coin,
    "pillage": _pillage,
    "trash": _trash,
    "desperation": _desperation,
    "own_base_damage": _own_base_damage,
    "active_base_damage": _active_base_damage,
    "damage_ready": _damage_ready,
    "runes_on_self": _runes_on_self,
    "elm_runes": _elm_runes,
    "instant_build": _instant_build,
    "sanatorium": _sanatorium,
    "put_into_play": _put_into_play,
    "fetch": _fetch,
    "discard": _discard,
    "token": _token,
    "token_for_opponent": _token_for_opponent,
    "exhaust_self": _exhaust_self,
    "buff": _buff,
    "feather": _feather,
    "destroy_any": _destroy_any,
    "destroy_card": _destroy_card,
    "free_spell": _free_spell,
    "kidnap": _kidnap,
    "anarchy": _anarchy,
    "bloodlust": _bloodlust,
    "charge": _charge,
    "peace": _peace,
    "circle_sacrifice": _circle_sacrifice,
    "stampede": _stampede,
    "ferocity": _ferocity,
    "attach": _attach,
    "firebird": _firebird,
    "shove": _shove,
    "mirror": _mirror,
    "trash_workers": _trash_workers,
    "sacrifice_self": _sacrifice_self,
    "polymorph": _polymorph,
    "shove_slot": _shove_slot,
    "damage_shoved": _damage_shoved,
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
    if spell in effects.ATTACHING:
        host = top.get("host")
        if host is None:
            # Nothing to attach to: it goes to the discard.
            match.player(seat).discard.append(spell)
            return
        card = match.new_instance(spell, seat)
        card.arrived_this_turn = True
        side, ref = parse_target(host)
        if ref.startswith("unit:"):
            card.attached = [int(ref.split(":", 1)[1])]
        else:
            card.attached_hero = host
        result.narration.append(f"{tokens.card(spell)} is attached to {board.named(match, side, ref)}.")
        return
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
    if top.get("trashed") or effects.EFFECTS[top["effect"]].trash_after:
        # "... then trash this card": out of the game (UMR p. 13).
        match.record_event("trashed", slug=spell, owner=seat)
        return
    match.player(seat).discard.append(spell)


__all__ = [
    "APPEL_TOP", "DOES", "EFFECT", "UPKEEP_ORDER", "appel_stomp_top", "carry_on",
    "choose_target", "current_part", "frame", "push", "rows_for", "run",
]
