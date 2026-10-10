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
#: Reputable Newsman's number and Oathkeeper's oath (step 13): a part
#: whose answer is a choice of the card's own, kept on the frame under
#: the part's name until the part is done.
ASKS_NUMBER = "number"
ASKS_OATH = "oath"
ASKED_PARTS = (ASKS_NUMBER, ASKS_OATH)


def asking(match: MatchState) -> str:
    """Which question the effect on top of the stack asks: its mode
    (`MODE_CHOICE`), the split of its damage (`DIVIDE_DAMAGE`), or a
    target (`TARGET`)."""
    top = match.resolving[0]
    part = current_part(match)
    if part is not None and part.does == "mode" and "mode" not in top:
        return ASKS_MODE
    if part is not None and part.does in ASKED_PARTS and part.does not in top:
        return part.does
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
    that mode or both, a boosted part only where it was boosted, and a
    part that follows an earlier pick only where one was made (step 12)."""
    if part.only is not None and top.get("mode") not in (part.only, "both"):
        return False
    if part.when == "boosted" and not top.get("boosted"):
        return False
    if part.when == "from_hand" and not top.get("from_hand"):
        return False
    if part.follows and not top.get("chose"):
        return False
    if part.when == "stormed" and len(top.get("stormed") or []) < 2:
        # True Power of Storms: "If you do" -- both cards discarded.
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
        if part.does in ASKED_PARTS and part.does not in top:
            # The number or the oath is asked (`CHOOSE_NUMBER`, `OATH`).
            return False
        if part.does == "look_at" and top.get("looked") != top["part"]:
            # A look with nothing to choose (Martial Mastery): asked once,
            # what is seen pictured to the asker alone, and Done (step 13).
            top["looked"] = top["part"]
            top["picks"] = []
            return False
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
    top["chose"] = True
    top["picked"] = row.key
    if part.targeted and _targeted_away(engine, match, top, row, result):
        # Smoker went home, or an Illusion died, the moment it was
        # targeted: the rest of the part does not resolve on it.
        board.settle(engine, match, result, cause=top["seat"])
    elif part.does != "divide":
        DOES[part.does](engine, match, top, part, (row.seat, row.ref), result)
        board.settle(engine, match, result, cause=top["seat"])
    if len(top["picks"]) >= pick_limit(engine, match, top, part):
        _end_picks(engine, match, top, part, result)


def _targeted_away(engine: "RulesEngine", match: MatchState, top: dict, row,
                   result: StepResult) -> bool:
    """
    What being targeted does by itself (step 13), before the part does
    anything to it: Smoker returns to his owner's hand (his ruling), and an
    Illusion dies -- "At the moment they are targeted, they die (and go to
    their owner's discard pile)", so the damage or the rune never lands
    (the illusion ruling) -- unless its controller has a Macciatus. Whether
    the target went.
    """
    body = board.body_of(match, row.seat, row.ref)
    if not isinstance(body, CardInstance) or not engine.catalog.cards[body.slug].is_unit:
        return False
    named = _thing(match, (row.seat, row.ref))
    if engine.text_slug(body) in effects.RETURNS_WHEN_TARGETED and not engine.cant_leave_play(match, body):
        result.narration.append(f"{named} is targeted, and returns to {tokens.player(body.owner)}'s hand.")
        board.leave_play(engine, match, body, "hand")
        match.record_event("returned", slug=body.slug, owner=body.owner)
        board.second_chances(engine, match, [body], result)
        return True
    if engine.illusion_dies(match, body):
        result.narration.append(f"{named} is an Illusion: targeted by {top['by']}, it dies.")
        board.destroy(engine, match, [(row.seat, row.ref)], result, cause=top["seat"])
        return True
    return False


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
    bodies = [board.body_of(match, *parse_target(key)) for key in split]
    shielded = board.sentry_shields(engine, match, [body for body in bodies if body is not None], result)
    for key, amount in split.items():
        target = parse_target(key)
        if board.body_of(match, *target) in shielded:
            continue
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


def choose_number(engine: "RulesEngine", game: "CodexGame", match: MatchState,
                  number) -> StepResult:
    """The answer to `CHOOSE_NUMBER`: Reputable Newsman's number, 0 to 20."""
    if not match.resolving or asking(match) != ASKS_NUMBER:
        raise RuleRefusal("Nothing is waiting on a number.")
    if not isinstance(number, int) or isinstance(number, bool) or not 0 <= number <= effects.NUMBER_MOST:
        raise RuleRefusal(f"Choose a number from 0 to {effects.NUMBER_MOST}.", cite="reputable_newsman")
    match.resolving[0][ASKS_NUMBER] = number
    return carry_on(engine, game, match, StepResult(board_changed=True))


def choose_oath(engine: "RulesEngine", game: "CodexGame", match: MatchState,
                oath: str) -> StepResult:
    """The answer to `OATH`: one of Oathkeeper's two oaths."""
    if not match.resolving or asking(match) != ASKS_OATH:
        raise RuleRefusal("Nothing is waiting on an oath.")
    if oath not in (effects.OATH_HAND, effects.OATH_DRAW):
        raise RuleRefusal("That is not one of the oaths.", cite="oathkeeper_of_kor_mountain")
    match.resolving[0][ASKS_OATH] = oath
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
        result.narration.append(
            f"{top['by']} deals {amount} to {_thing(match, target)}"
            f"{board.left_after(engine, match, seat, ref, amount, by=top['seat'])}."
        )
        board.damage_building(match, seat, ref, amount, result, by=top["seat"])
        return amount
    body = board.body_of(match, seat, ref)
    if body is None:
        return 0
    named = _thing(match, target)
    if (isinstance(body, CardInstance) and engine.catalog.cards[body.slug].is_building_card
            and board.pass_prevents(match, seat, body)):
        result.narration.append(f"{top['by']} deals {amount} to {named}{board._PREVENTED}.")
        return 0
    if board.sentry_shields(engine, match, [body], result):
        return 0
    amount = board.focus_prevents(engine, match, body, amount, result=result)
    landed = board.take_damage(body, amount)
    line = f"{top['by']} deals {landed} to {named}"
    if landed < amount:
        line += f" (armor takes {amount - landed})"
    result.narration.append(line + board.card_left(engine, match, body) + ".")
    return landed


def _repair(engine, match, top, part, target, result) -> None:
    seat, ref = target
    repaired = board.repair_building(engine, match, seat, ref, part.amount)
    if repaired:
        result.narration.append(
            f"{top['by']} repairs {repaired} damage on {_thing(match, target)}"
            f"{board.now_at(engine, match, seat, ref)}."
        )
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


def _return(engine, match, top, part, target, result) -> bool:
    """A unit to its owner's hand -- not a death (Undo's, Rewind's and the
    Stewardess's rulings) -- unless it can't leave play (Gilded Glaxx with
    gold); whether it went."""
    seat, ref = target
    card = board.body_of(match, seat, ref)
    if card is None:
        return False
    if engine.cant_leave_play(match, card):
        result.narration.append(f"{_thing(match, target)} can't leave play.")
        return False
    line = f"{top['by']} returns {_thing(match, target)} to {tokens.player(card.owner)}'s hand."
    board.leave_play(engine, match, card, "hand")
    match.record_event("returned", slug=card.slug, owner=card.owner)
    result.narration.append(line)
    board.second_chances(engine, match, [card], result)
    return True


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
        what = "a card" if drawn == 1 else f"{drawn} cards"
        result.narration.append(f"{tokens.player(seat)} draws {what}.")


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
    amount = damage_amount(engine, match, top, part.amount)
    source = top["by"]
    printed = effects.printing_band(top["effect"])
    if printed is not None:
        source = f"{top['by']}'s {band_name(engine, *printed)} band's ability"
    result.narration.append(
        f"{source} deals {amount} to {tokens.player(other)}'s base"
        f"{board.base_left_after(match, other, amount, by=top['seat'])}."
    )
    damage_base(match, other, amount, result, by=top["seat"])


def band_name(engine, slug: str, first: int) -> str:
    """A hero's band by where it is on the card -- "first level", "middle
    level" or "max level" -- from the first level of the band (the
    author, 2026-10-10: every hero ability is a first level band, middle
    level band or max level band one)."""
    starts = [band.min_level for band in engine.catalog.heroes[slug].bands]
    if first == starts[-1]:
        return "max level"
    return "first level" if first == starts[0] else "middle level"


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
        f"{tokens.player(seat)}'s base takes {amount} damage"
        f"{board.base_left_after(match, seat, amount)}."
    )
    if mine is not None:
        board.sacrifice(engine, match, mine, result)
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
    result.narration.append(
        f"{top['by']} deals {amount} to {tokens.player(other)}'s base"
        f"{board.base_left_after(match, other, amount, by=top['seat'])}."
    )
    damage_base(match, other, amount, result, by=top["seat"])
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
    named = _thing(match, target)
    if engine.cant_leave_play(match, card):
        result.narration.append(f"{named} can't leave play.")
        return
    result.narration.append(f"{top['by']} trashes {named}.")
    board.trash(engine, match, card, result)


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
    result.narration.append(
        f"{top['by']} deals {amount} to {tokens.player(seat)}'s own base"
        f"{board.base_left_after(match, seat, amount)}."
    )
    damage_base(match, seat, amount, result)


def _active_base_damage(engine, match, top, part, target, result) -> None:
    """Crash Bomber's "Dies on another player's turn: Deal 1 damage to that
    player's base" -- the base of whoever's turn it is."""
    seat = match.active
    amount = damage_amount(engine, match, top, part.amount)
    result.narration.append(
        f"{top['by']} deals {amount} to {tokens.player(seat)}'s base"
        f"{board.base_left_after(match, seat, amount, by=top['seat'])}."
    )
    damage_base(match, seat, amount, result, by=top["seat"])


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
    result.narration.append(
        f"{top['by']} puts {tokens.card(slug)} from {tokens.player(seat)}'s hand into play"
        + _arrived(engine, match, card, slug)
    )
    return card


def _arrived(engine, match, card, slug: str) -> str:
    """The end of a line that puts a card into play: its numbers, or --
    a forecast card -- that it went into the future instead (step 12)."""
    if card is None:
        return f", which goes into the future with {engine.forecast(slug)} time runes."
    atk, hp = engine.unit_stats(card, match)
    return f": {atk}/{hp}."


def _put_into_play(engine, match, top, part, target, result) -> None:
    """A unit into play from the hand or the codex (UMR p. 15): Feral
    Strike's, Circle of Life's, Calamandra's -- no cost paid, no building
    needed, and from the codex a card of its owner's from then on."""
    seat, ref = target
    from codex.engine import CODEX

    from codex.engine import DISCARD

    if ref.startswith(DISCARD):
        # Garth at 7: from the discard pile, free, its tech met.
        slug = _private_slug(ref)
        player = match.player(seat)
        if slug not in player.discard:
            return
        player.discard.remove(slug)
        card = board.put_into_play(engine, match, slug, seat, from_hand=False)
        result.narration.append(
            f"{top['by']} puts {tokens.card(slug)} from {tokens.player(seat)}'s discard pile into play"
            + _arrived(engine, match, card, slug)
        )
        return
    if not ref.startswith(CODEX):
        _from_hand(engine, match, top, target, result)
        return
    slug = _private_slug(ref)
    player = match.player(seat)
    if player.codex.get(slug, 0) <= 0:
        return
    player.codex[slug] -= 1
    card = board.put_into_play(engine, match, slug, seat, from_hand=False)
    result.narration.append(
        f"{top['by']} puts {tokens.card(slug)} from {tokens.player(seat)}'s codex into play"
        + _arrived(engine, match, card, slug)
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
        what = "a card" if part.most == 1 else f"{part.most} cards"
        result.narration.append(f"{tokens.player(seat)} discards {what} for {top['by']}.")


def _token(engine, match, top, part, target, result) -> None:
    board.summon(engine, match, part.token, top["seat"], part.amount, result, by=top["by"])


def _token_for_opponent(engine, match, top, part, target, result) -> None:
    """Final Showdown's Hunters: summoned for the opponent, who controls
    them, in their play zone and never their patrol zone (the Card FAQ)."""
    other = 2 if top["seat"] == 1 else 1
    source = board.body_of(match, top["seat"], top.get("source") or "")
    made_by = source.id if isinstance(source, CardInstance) and source.slug in effects.SHACKLED else None
    board.summon(engine, match, part.token, other, part.amount, result, by=top["by"], made_by=made_by)


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
    if isinstance(card, CardInstance) and not engine.catalog.cards[card.slug].is_unit:
        # An upgrade or an ongoing spell (Zarramonde).
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
    from codex.flow.actions import spend_promise

    # "If you play another card in between (even with an effect like
    # Cinderblast Dragon's attack effect), you have to apply Promise of
    # Payment's effect to that card instead" (its ruling).
    spend_promise(engine, match, seat, slug, result)
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
    board.sacrifice(engine, match, card, result)


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
    board.sacrifice(engine, match, card, result)


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


# -- Purple and black's handlers (step 12) --------------------------------------


def _time_target(engine, match, top, part, target, result) -> None:
    """Time Spiral, Tinkerer, Seer: the card whose time runes change,
    kept for the part that adds or removes one."""
    top["time_target"] = target_key(*target)


def _time_rune(engine, match, top, part, target, result) -> None:
    """A time rune added to or removed from the card chosen: one in the
    future arriving, a fading card sacrificed, as its last goes."""
    key = top.get("time_target")
    if key is None:
        return
    seat, ref = parse_target(key)
    thing = board.timed(match, seat, ref)
    if thing is None:
        return
    named = board.named(match, seat, ref)
    if top.get("mode") == "add":
        board.add_time_rune(thing)
        result.narration.append(f"{top['by']} adds a time rune to {named}: {thing.time_runes}.")
        return
    result.narration.append(
        f"{top['by']} removes a time rune from {named}: {max(thing.time_runes - 1, 0)}."
    )
    board.remove_time_rune(engine, match, seat, ref, result)


def _time_rune_self(engine, match, top, part, target, result) -> None:
    """A time rune onto the card the ability is on (Shimmer Ray), or off
    it (Omegacron, from the future): `part.amount` says which."""
    seat, source = top["seat"], top.get("source")
    thing = board.timed(match, seat, source) if source else None
    if thing is None:
        return
    if part.amount > 0:
        board.add_time_rune(thing, part.amount)
        result.narration.append(f"{top['by']} gets a time rune: {thing.time_runes}.")
        return
    result.narration.append(f"{top['by']} loses a time rune: {max(thing.time_runes - 1, 0)} left.")
    board.remove_time_rune(engine, match, seat, source, result)


def _sacrifice(engine, match, top, part, target, result) -> None:
    """A sacrifice as a cost or an effect (step 12): a unit or an upgrade
    to its owner's discard pile -- or the Graveyard -- a hero to its
    command zone, a worker trashed (Omegacron's ruling)."""
    seat, ref = target
    if ref == WORKERS:
        if board.trash_worker(match, seat):
            result.narration.append(
                f"{tokens.player(top['seat'])} sacrifices a worker: {match.player(seat).workers} left."
            )
        return
    named = _thing(match, target)
    from codex.components import is_hero_ref

    if is_hero_ref(ref):
        result.narration.append(f"{tokens.player(top['seat'])} sacrifices {named}.")
        board.destroy(engine, match, [target], result, cause=seat)
        return
    card = board.body_of(match, seat, ref)
    if card is None:
        return
    result.narration.append(f"{tokens.player(top['seat'])} sacrifices {named}.")
    board.sacrifice(engine, match, card, result)


def _research(engine, match, top, part, target, result) -> None:
    """Temporal Research's further cards: one more at three time runes,
    another at ten -- every rune on what its caster controls (its
    rulings)."""
    seat = top["seat"]
    runes = engine.time_runes_of(match, seat)
    more = (1 if runes >= 3 else 0) + (1 if runes >= 10 else 0)
    if not more:
        return
    top["drew"] = True
    drawn = draw_cards(engine, match, seat, more, result)
    if drawn:
        result.narration.append(
            f"{tokens.player(seat)} has {runes} time runes, and draws "
            f"{drawn} more card{'' if drawn == 1 else 's'}."
        )


def _rites(engine, match, top, part, target, result) -> None:
    """Death Rites: the trigger set on its caster for the rest of the
    turn."""
    seat = top["seat"]
    match.player(seat).lasting.append({"kind": effects.DEATH_RITES, "until": "end_of_turn"})
    result.narration.append(
        f"{top['by']}: this turn, whenever one of {tokens.player(seat)}'s units dies, one of "
        f"{tokens.player(2 if seat == 1 else 1)}'s lowest tech units is destroyed."
    )


def _plague(engine, match, top, part, target, result) -> None:
    """Spreading Plague: every tech 0, I or II unit and every hero with a
    -1/-1 rune, either side's, destroyed."""
    doomed = [
        (player.seat, card.ref) for player in match.players for card in player.play
        if engine.catalog.cards[card.slug].is_unit and card.minus_runes > 0
        and (engine.catalog.cards[card.slug].tech_level or 0) <= 2
    ] + [
        (player.seat, hero_ref(hero.slug)) for player in match.players
        for hero in player.heroes_in_play if hero.minus_runes > 0
    ]
    if not doomed:
        result.narration.append(f"{top['by']} finds nothing with a -1/-1 rune.")
        return
    result.narration.append(f"{top['by']} destroys every tech 0, I and II unit and hero with a -1/-1 rune.")
    board.destroy(engine, match, doomed, result, cause=top["seat"])


def _decay(engine, match, top, part, target, result) -> None:
    """Death and Decay: -3/-3 this turn to every unit and hero the opponent
    has, and 3 damage to each of their buildings -- one being built this
    turn excepted (UMR p. 8)."""
    seat = top["seat"]
    other = 2 if seat == 1 else 1
    player = match.player(other)
    for body in [*(card for card in player.play if engine.catalog.cards[card.slug].is_unit),
                 *player.heroes_in_play]:
        body.modifiers.append({"kind": "atk", "amount": -part.amount, "until": "end_of_turn"})
        body.modifiers.append({"kind": "hp", "amount": -part.amount, "until": "end_of_turn"})
    result.narration.append(
        f"{top['by']} gives every unit and hero {tokens.player(other)} controls -3/-3 this turn, "
        "and deals 3 to each of their buildings."
    )
    board.settle(engine, match, result, cause=seat)
    buildings = [
        ref for ref in ("tech1", "tech2", "tech3", "add_on")
        if board.still_there(match, other, ref) and not engine._under_construction(player, ref)
    ]
    cards = [card for card in player.play if engine.catalog.cards[card.slug].is_building_card
             and not board.pass_prevents(match, other, card)]
    for card in cards:
        board.take_damage(card, damage_amount(engine, match, top, part.amount))
    for ref in buildings:
        if board.still_there(match, other, ref):
            board.damage_building(match, other, ref, damage_amount(engine, match, top, part.amount),
                                  result, by=seat)
    board.damage_building(match, other, "base", damage_amount(engine, match, top, part.amount),
                          result, by=seat)


def _shadow_blade(engine, match, top, part, target, result) -> None:
    """Shadow Blade: 3 to a patroller, and where that kills it, its
    controller discards a card at random."""
    seat, ref = target
    body = board.body_of(match, seat, ref)
    _damage(engine, match, top, part, target, result)
    if body is not None and board.lethal(engine, match, body):
        board.settle(engine, match, result, cause=top["seat"])
        if board.body_of(match, seat, ref) is None:
            board.random_discard(engine, match, seat, result, top["by"])


def _poison(engine, match, top, part, target, result) -> None:
    """Poisonblade Rogue, as it attacks: armor piercing, and its damage to
    units and heroes as -1/-1 runes, this turn."""
    card = board.body_of(match, top["seat"], top.get("source") or "")
    if card is None:
        return
    card.modifiers.append({"kind": "keyword", "keyword": "Armor piercing", "until": "end_of_turn"})
    card.modifiers.append({"kind": "rune_damage", "until": "end_of_turn"})
    result.narration.append(
        f"{top['by']} gets armor piercing and deals its damage as -1/-1 runes this turn."
    )


def _pick_buried(engine, match, top, part, target, result) -> None:
    """The Graveyard: the buried unit to play, kept for the play."""


def _play_buried(engine, match, top, part, target, result) -> None:
    """
    A buried unit played from the Graveyard: "You still pay for it and
    must meet the tech reqs for it" -- its cost, boosted where the mode
    says, its owner still its owner -- and it arrives, its arrives effects
    with it (the Graveyard's ruling).
    """
    from codex.engine import buried_entry

    seat = top["seat"]
    found = buried_entry(match, top.get("picked") or "")
    if found is None:
        return
    yard, entry = found
    slug = entry["slug"]
    player = match.player(seat)
    why = engine.why_not_play_buried(player, slug)
    if why:
        result.narration.append(f"{tokens.card(slug)} can't be played: {why}.")
        return
    boosted = top.get("mode") == "boosted"
    cost = engine.effective_cost(player, slug) + (engine.boost_cost(slug) or 0 if boosted else 0)
    if player.gold < cost:
        result.narration.append(f"{tokens.card(slug)} can't be played: not enough gold.")
        return
    yard.buried.remove(entry)
    player.gold -= cost
    match.record_event("played", slug=slug, cost=cost, buried=True,
                       **({"boosted": True} if boosted else {}))
    from codex.flow.actions import spend_promise

    spend_promise(engine, match, seat, slug, result)
    card = match.new_instance(slug, seat)
    card.owner = entry["owner"]
    atk, hp = engine.unit_stats(card, match)
    result.narration.append(
        f"{tokens.player(seat)} plays {tokens.card(slug)} from their {tokens.card(effects.GRAVEYARD)} "
        f"for {tokens.gold(cost)}{', boosted' if boosted else ''}: {atk}/{hp}."
    )
    board.arrive(engine, match, card, boosted=boosted)


# -- Black's handlers (step 12, commit 4) ---------------------------------------


def _against(top: dict) -> int:
    """The other player of a frame -- or the one it names, where the active
    player resolves something about another's cards."""
    return top.get("against") or (2 if top["seat"] == 1 else 1)


def _random_discard(engine, match, top, part, target, result) -> None:
    """Thieving Imp, Cursed Crow: the opponent -- the defending player --
    discards a card at random."""
    board.random_discard(engine, match, _against(top), result, top["by"])


def _runes_on_opposing(engine, match, top, part, target, result) -> None:
    """Plague Lab: a -1/-1 rune on each of an opponent's units; Plague Lord
    on each opposing unit and hero too (`part.token` "heroes")."""
    other = _against(top)
    player = match.player(other)
    bodies = [card for card in player.play if engine.catalog.cards[card.slug].is_unit]
    if part.token == "heroes":
        bodies += player.heroes_in_play
    for body in bodies:
        board.add_minus_rune(body)
    what = "unit and hero" if part.token == "heroes" else "unit"
    result.narration.append(f"{top['by']} puts a -1/-1 rune on each {what} {tokens.player(other)} controls.")


def _lab_rune(engine, match, top, part, target, result) -> None:
    """Plague Lab: another rune of a kind already on the card -- one a
    card."""
    seat, ref = target
    ref, _, kind = ref.partition("#")
    body = board.body_of(match, seat, ref)
    if body is None:
        return
    top.setdefault("lab_done", []).append(target_key(seat, ref))
    if kind == "plus":
        board.add_plus_rune(body)
    elif kind == "minus":
        board.add_minus_rune(body)
    elif kind == "time":
        board.add_time_rune(body)
    else:
        body.runes[kind] = body.runes.get(kind, 0) + 1
        limit = effects.BLOOD_RUNES.get(body.slug) if kind == "blood" else None
        if limit is not None:
            body.runes[kind] = min(limit, body.runes[kind])
    rune = {"plus": "+1/+1", "minus": "-1/-1"}.get(kind, kind)
    result.narration.append(f"{top['by']} adds a {rune} rune to {_thing(match, (seat, ref))}.")


def _rune_on_self(engine, match, top, part, target, result) -> None:
    """Skeleton Javelineer: "Put a javelin rune on this." """
    body = board.body_of(match, top["seat"], top.get("source") or "")
    if body is None:
        return
    body.runes[part.token] = body.runes.get(part.token, 0) + part.amount
    result.narration.append(f"{top['by']} gets a {part.token} rune.")


def _keyword_self(engine, match, top, part, target, result) -> None:
    """A keyword for the turn on the card the ability is on: the
    Javelineer's long-range."""
    body = board.body_of(match, top["seat"], top.get("source") or "")
    if body is None:
        return
    body.modifiers.append({"kind": "keyword", "keyword": part.token, "until": "end_of_turn"})
    result.narration.append(f"{top['by']} gets {part.token.lower()} this turn.")


def _negate(engine, match, top, part, target, result) -> None:
    """Jandra: "Destroy all your units except for Demons." """
    seat = top["seat"]
    doomed = [(seat, card.ref) for card in match.player(seat).play
              if engine.catalog.cards[card.slug].is_unit and not engine.is_demon(card)]
    result.narration.append(f"{top['by']} destroys every unit of {tokens.player(seat)}'s but its Demons.")
    if doomed:
        board.destroy(engine, match, doomed, result, cause=seat)


def _debuff(engine, match, top, part, target, result) -> None:
    """-X/-X this turn (Deteriorate)."""
    body = board.body_of(match, *target)
    body.modifiers.append({"kind": "atk", "amount": -part.amount, "until": "end_of_turn"})
    body.modifiers.append({"kind": "hp", "amount": -part.amount, "until": "end_of_turn"})
    result.narration.append(
        f"{top['by']} gives {_thing(match, target)} -{part.amount}/-{part.amount} this turn."
    )


def _dark_pact(engine, match, top, part, target, result) -> None:
    """Dark Pact: 2 to a base, then that player draws 2."""
    seat, _ = target
    amount = damage_amount(engine, match, top, part.amount)
    result.narration.append(f"{top['by']} deals {amount} to {tokens.player(seat)}'s base.")
    damage_base(match, seat, amount, result, by=top["seat"])
    if match.winner is not None:
        return
    drawn = draw_cards(engine, match, seat, 2, result)
    if seat == top["seat"]:
        top["drew"] = True
    if drawn:
        result.narration.append(f"{tokens.player(seat)} draws {drawn} card{'' if drawn == 1 else 's'}.")


def _curse_discard(engine, match, top, part, target, result) -> None:
    """Carrion Curse: a non-unit card the caster chose from the opponent's
    hand, discarded by them -- counted, never named."""
    seat, ref = target
    slug = _private_slug(ref)
    player = match.player(seat)
    if slug not in player.hand:
        return
    player.hand.remove(slug)
    player.discard.append(slug)
    match.record_event("discarded", seat=seat, slug=slug, by=top["effect"])
    result.narration.append(f"{tokens.player(seat)} discards a card for {top['by']}.")


def _drain(engine, match, top, part, target, result) -> None:
    """Nether Drain: two levels off a hero, never below 1, and no levels for
    it this turn."""
    hero = board.body_of(match, *target)
    if hero is None:
        return
    before = hero.level
    hero.level = max(1, hero.level - part.amount)
    if hero.level < engine.hero_card(hero).max_level:
        hero.max_level_since_turn_began = False
    hero.modifiers.append({"kind": "no_level", "until": "end_of_turn"})
    result.narration.append(
        f"{top['by']} drains {_thing(match, target)} from level {before} to {hero.level}: "
        "it can't level up this turn."
    )


def _gain_levels(engine, match, top, part, target, result) -> None:
    """Nether Drain: two levels for another hero, to its maximum -- its max
    level effect, where reached on another player's turn, not resolving
    where it asks a choice (UMR p. 14)."""
    seat, ref = target
    hero = board.body_of(match, seat, ref)
    if hero is None:
        return
    before = hero.level
    reached = board.raise_level(engine, hero, part.amount, match)
    if hero.level == before:
        result.narration.append(f"{_thing(match, target)} gains no level.")
        return
    line = f"{top['by']} raises {_thing(match, target)} to level {hero.level}"
    result.narration.append(line + (", a new band, and healed." if reached else "."))
    board.max_level_reached(engine, match, seat, hero, result)


def _metamorphosis(engine, match, top, part, target, result) -> None:
    """Metamorphosis: every unit its caster controls sacrificed; each of
    their heroes not yet a Demon to its maximum level, a Demon until it
    leaves play, two +1/+1 runes, readiness and invisibility."""
    seat = top["seat"]
    player = match.player(seat)
    units = [card for card in player.play if engine.catalog.cards[card.slug].is_unit]
    result.narration.append(f"{tokens.player(seat)} sacrifices every unit they control for {top['by']}.")
    for card in units:
        if player.instance(card.id) is not None:
            board.sacrifice(engine, match, card, result)
    board.settle(engine, match, result, cause=seat)
    for hero in player.heroes_in_play:
        if engine.is_demon(hero):
            continue
        board.raise_level(engine, hero, engine.hero_card(hero).max_level, match)
        hero.modifiers.append({"kind": "demon", "until": None})
        for keyword in effects.METAMORPHOSIS_KEYWORDS:
            hero.modifiers.append({"kind": "keyword", "keyword": keyword, "until": None})
        board.add_plus_rune(hero, part.amount)
        result.narration.append(
            f"{tokens.hero(hero.slug)} becomes a Demon at level {hero.level}: two +1/+1 runes, "
            "readiness and invisibility."
        )
        board.max_level_reached(engine, match, seat, hero, result)


def _doom_buff(engine, match, top, part, target, result) -> None:
    """Vandy at 5: +2/+2, and death at her controller's next upkeep -- with
    or without her (her rulings)."""
    seat = top["seat"]
    body = board.body_of(match, *target)
    body.modifiers.append({"kind": "atk", "amount": part.amount, "until": "doom", "seat": seat})
    body.modifiers.append({"kind": "hp", "amount": part.amount, "until": "doom", "seat": seat})
    body.modifiers.append({"kind": "doomed", "seat": seat, "until": "doom"})
    result.narration.append(
        f"{top['by']} gives {_thing(match, target)} +2/+2: it dies at {tokens.player(seat)}'s next upkeep."
    )


def _gargoyle(engine, match, top, part, target, result) -> None:
    """Gargoyle: until its controller's next upkeep, not indestructible,
    flying, +3 ATK, and free to attack and patrol."""
    seat = top["seat"]
    body = board.body_of(match, seat, top.get("source") or "")
    if body is None:
        return
    until = {"until": "upkeep", "seat": seat}
    body.modifiers += [
        {"kind": "lose_keyword", "keyword": "Indestructible", **until},
        {"kind": "keyword", "keyword": "Flying", **until},
        {"kind": "atk", "amount": part.amount, **until},
        {"kind": "unbound", **until},
    ]
    result.narration.append(
        f"{top['by']} wakes: until {tokens.player(seat)}'s next upkeep it is not indestructible, "
        "flies, has +3 ATK and may attack and patrol."
    )


def _ground(engine, match, top, part, target, result) -> None:
    """Crypt Crawler: a flier loses flying this turn."""
    body = board.body_of(match, *target)
    body.modifiers.append({"kind": "lose_keyword", "keyword": "Flying", "until": "end_of_turn"})
    result.narration.append(f"{top['by']} grounds {_thing(match, target)}: it loses flying this turn.")


def _exhaust_skeletons(engine, match, top, part, target, result) -> None:
    """Skeletal Lord's cost: five of its controller's ready Skeletons,
    exhausted -- fatigued ones too (its ruling)."""
    seat = top["seat"]
    skeletons = engine.ready_skeletons(match, seat)[:part.amount]
    for card in skeletons:
        card.exhausted = True
    result.narration.append(f"{tokens.player(seat)} exhausts {len(skeletons)} Skeletons for {top['by']}.")


def _resurrect(engine, match, top, part, target, result) -> None:
    """Blackhand Resurrector: a hero that died this game summoned from the
    command zone at its maximum level -- level 1 against an opposing
    Chronofixer -- its summoning runes gone and its max level effect
    resolved (its rulings); never past the hero limit (the author,
    2026-10-10)."""
    seat, ref = target
    player = match.player(seat)
    hero = player.hero_by_ref(ref)
    if hero is None or hero.in_play or len(player.heroes_in_play) >= engine.hero_limit(player):
        return
    hero.zone = "play"
    hero.level = 1
    hero.damage = 0
    hero.summoning_runes = 0
    hero.arrived_this_turn = True
    hero.exhausted = False
    hero.patrol_slot = None
    hero.bands = {str(engine.hero_card(hero).bands[0].min_level): match.next_sequence()}
    match.record_event("summoned", slug=hero.slug, seat=seat, by="blackhand_resurrector")
    board.raise_level(engine, hero, engine.hero_card(hero).max_level, match)
    result.narration.append(
        f"{top['by']} summons {tokens.hero(hero.slug)} back from the command zone at level {hero.level}."
    )
    board.hero_arrives(engine, match, seat, hero)
    board.max_level_reached(engine, match, seat, hero, result)


def _exhaust(engine, match, top, part, target, result) -> None:
    """Voidblocker: another of the attacker's ready units or heroes,
    exhausted."""
    body = board.body_of(match, *target)
    if body is None:
        return
    body.exhausted = True
    result.narration.append(f"{tokens.player(top['seat'])} exhausts {_thing(match, target)} for {top['by']}.")


# -- Purple's handlers (step 12, commit 5) --------------------------------------


def _geiger(engine, match, top, part, target, result) -> None:
    """Max Geiger at 5: a friendly unit trashed, then back in play fresh
    under the same controller, with arrival fatigue (his rulings) -- a
    token too: the ability returns what it trashed (the author,
    2026-10-10)."""
    seat, ref = target
    card = board.body_of(match, seat, ref)
    if card is None:
        return
    named = _thing(match, target)
    if engine.cant_leave_play(match, card):
        result.narration.append(f"{named} can't leave play.")
        return
    match.player(card.controller).play.remove(card)
    board._empty_graveyard(match, card)
    match.record_event("trashed", slug=card.slug, owner=card.owner)
    result.narration.append(f"{top['by']} trashes {named}.")
    board.return_fresh(engine, match, card.slug, card.controller, card.owner, result)


def _prynn_trash(engine, match, top, part, target, result) -> None:
    """Prynn at 7: a unit trashed -- remembered on her, to come back when
    she leaves play."""
    seat, ref = target
    card = board.body_of(match, seat, ref)
    prynn = match.player(top["seat"]).hero_of(effects.PRYNN)
    if card is None:
        return
    named = _thing(match, target)
    entry = {"slug": card.slug, "owner": card.owner, "controller": card.controller, "id": card.id}
    if not board.trash(engine, match, card):
        result.narration.append(f"{named} can't leave play.")
        return
    result.narration.append(f"{top['by']} trashes {named}.")
    if prynn is not None and prynn.in_play and not board.is_token(engine, entry["slug"]):
        prynn.trashed.append(entry)
    board.second_chances(engine, match, [card], result)


def _fade_check(engine, match, top, part, target, result) -> None:
    """After an ability whose cost took time runes: a fading card or hero
    left with none is sacrificed now -- Prynn dies at once, "not from
    fading" (her rulings), and what she trashed comes back."""
    seat, source = top["seat"], top.get("source")
    thing = board.body_of(match, seat, source) if source else None
    if thing is None or thing.time_runes > 0 or not engine.fading(thing):
        return
    thing.time_runes = 1
    board.remove_time_rune(engine, match, seat, source, result)


def _look(engine, match, top, part, target, result) -> None:
    """Vir: the top card looked at -- pictured to him alone by the question
    that offered it; nothing changes."""


def _exchange(engine, match, top, part, target, result) -> None:
    """Vir: the top card of the draw pile and a card from the hand trade
    places -- unseen by anybody else."""
    seat, ref = target
    player = match.player(seat)
    slug = _private_slug(ref)
    if not player.deck or slug not in player.hand:
        return
    top_card = player.deck.pop()
    player.hand.remove(slug)
    player.deck.append(slug)
    player.hand.append(top_card)
    result.narration.append(f"{tokens.player(seat)} exchanges the top card of their draw pile with a card from their hand.")


def _pick_top(engine, match, top, part, target, result) -> None:
    """Vir at 5: the top card chosen to play, kept for the play."""


def _play_top(engine, match, top, part, target, result) -> None:
    """Vir at 5: the top card of the draw pile played -- paid and its
    requirements met, boosted where the mode says (the boost ruling)."""
    from codex.flow import actions

    seat = top["seat"]
    player = match.player(seat)
    if not player.deck:
        return
    slug = player.deck[-1]
    if engine.why_not_play_top(match, player, slug):
        return
    boosted = top.get("mode") == "boosted"
    player.deck.pop()
    actions.put_card_into_play(engine, match, seat, slug, boosted, result, where="draw pile")


def _to_command_zone(engine, match, top, part, target, result) -> None:
    """Origin Story: a hero to its command zone, without dying."""
    seat, ref = target
    hero = board.body_of(match, seat, ref)
    if hero is None:
        return
    result.narration.append(f"{top['by']} returns {_thing(match, target)} to the command zone.")
    board.to_command_zone(engine, match, seat, hero, result)


def _bounce(engine, match, top, part, target, result) -> None:
    """Ebbflow Archon: a unit to its owner's hand, or a hero to its command
    zone."""
    from codex.components import is_hero_ref

    if is_hero_ref(target[1]):
        _to_command_zone(engine, match, top, part, target, result)
    else:
        _return(engine, match, top, part, target, result)


def _distort(engine, match, top, part, target, result) -> None:
    """Temporal Distortion: a tech I or II unit of the caster's to its
    owner's hand -- "If you do", the second part may put in a unit of that
    level costing no more (its rulings: not where it can't leave play)."""
    seat, ref = target
    card = board.body_of(match, seat, ref)
    if card is None:
        return
    printed = engine.catalog.cards[card.slug]
    if _return(engine, match, top, part, target, result):
        top["distorted"] = {"tech": printed.tech_level or 0, "cost": printed.cost or 0}
    else:
        top["chose"] = False


def _ready(engine, match, top, part, target, result) -> None:
    """Ready one of your units: it may attack again, where it has no
    readiness (Ready or Not's rulings)."""
    body = board.body_of(match, *target)
    body.exhausted = False
    result.narration.append(f"{top['by']} readies {_thing(match, target)}.")


def _hold_down(engine, match, top, part, target, result) -> None:
    """Ready or Not: "Opposing exhausted units don't ready during their next
    ready step." """
    other = _against(top)
    held = [card for card in match.player(other).play
            if engine.catalog.cards[card.slug].is_unit and card.exhausted]
    for card in held:
        card.disabled = True
    if held:
        result.narration.append(
            f"{tokens.player(other)}'s exhausted units don't ready at their next ready phase."
        )


def _rewind(engine, match, top, part, target, result) -> None:
    """Rewind: every tech 0, I and II unit to its owner's hand -- no deaths
    (its ruling); one that can't leave play stays."""
    going = [card for player in match.players for card in list(player.play)
             if engine.catalog.cards[card.slug].is_unit
             and (engine.catalog.cards[card.slug].tech_level or 0) <= 2
             and not engine.cant_leave_play(match, card)]
    result.narration.append(f"{top['by']} returns every tech 0, I and II unit to its owner's hand.")
    for card in going:
        board.leave_play(engine, match, card, "hand")
        match.record_event("returned", slug=card.slug, owner=card.owner)
    board.second_chances(engine, match, going, result)


def _keyword(engine, match, top, part, target, result) -> None:
    """A keyword for the turn on a unit or hero: Now's haste."""
    body = board.body_of(match, *target)
    body.modifiers.append({"kind": "keyword", "keyword": part.token, "until": "end_of_turn"})
    result.narration.append(f"{top['by']} gives {_thing(match, target)} {part.token.lower()} this turn.")


def _unphase(engine, match, top, part, target, result) -> None:
    """Unphase: invisible until its caster's next upkeep."""
    seat = top["seat"]
    body = board.body_of(match, *target)
    body.modifiers.append({"kind": "keyword", "keyword": "Invisible", "until": "upkeep", "seat": seat})
    result.narration.append(
        f"{top['by']} makes {_thing(match, target)} invisible until {tokens.player(seat)}'s next upkeep."
    )


def _stingers(engine, match, top, part, target, result) -> None:
    """Hive: Stingers summoned for its controller, to five for each Hive of
    theirs in play (Hive's limit and rulings)."""
    seat = top["seat"]
    player = match.player(seat)
    hives = sum(1 for card in player.play if card.slug == effects.HIVE and engine.texted(card))
    have = sum(1 for card in player.play if card.slug == effects.STINGER)
    room = max(0, effects.STINGERS_PER_HIVE * hives - have)
    count = min(part.amount, room)
    if not count:
        result.narration.append(f"{tokens.player(seat)} has as many Stingers as their Hives allow.")
        return
    board.summon(engine, match, effects.STINGER, seat, count, result, by=top["by"])


def _ready_self(engine, match, top, part, target, result) -> None:
    """Octavian: "Ready Octavian." """
    body = board.body_of(match, top["seat"], top.get("source") or "")
    if body is not None:
        body.exhausted = False
        result.narration.append(f"{top['by']} readies.")


def _disable(engine, match, top, part, target, result) -> None:
    """Disable (UMR p. 16): exhausted, sidelined if patrolling, not readied
    at its next ready phase."""
    body = board.body_of(match, *target)
    board.disable(body)
    result.narration.append(f"{top['by']} disables {_thing(match, target)}.")


def _void_star(engine, match, top, part, target, result) -> None:
    """Void Star: +4 ATK until its controller's next upkeep."""
    seat = top["seat"]
    body = board.body_of(match, seat, top.get("source") or "")
    if body is None:
        return
    body.modifiers.append({"kind": "atk", "amount": part.amount, "until": "upkeep", "seat": seat})
    result.narration.append(f"{top['by']} gets +4 ATK until {tokens.player(seat)}'s next upkeep.")


# -- The upkeep, the extra turn and the debt (step 12, commit 6) -------------


def _promise(engine, match, top, part, target, result) -> None:
    """Promise of Payment: the next card played this turn costs 0."""
    seat = top["seat"]
    match.player(seat).promised = True
    result.narration.append(
        f"The next card {tokens.player(seat)} plays this turn costs {tokens.gold(0)}; its cost is owed "
        "at their next upkeep."
    )


def _extra_turn(engine, match, top, part, target, result) -> None:
    """Double Time: an extra turn after this one -- two copies, two turns
    (its ruling, the Card FAQ)."""
    seat = top["seat"]
    match.extra_turns.append(seat)
    result.narration.append(f"{tokens.player(seat)} takes an extra turn after this one.")


def _banefire(engine, match, top, part, target, result) -> None:
    """Banefire Golem, having sacrificed: 1 damage to each opposing unit,
    hero and building -- one being built this turn excepted (UMR p. 8)."""
    seat = top["seat"]
    other = _against(top)
    player = match.player(other)
    amount = damage_amount(engine, match, top, part.amount)
    bodies = [card for card in player.play if engine.catalog.cards[card.slug].is_unit]
    bodies += player.heroes_in_play
    shielded = board.sentry_shields(engine, match, bodies, result)
    for body in bodies:
        if body not in shielded:
            board.take_damage(body, amount)
    for card in [card for card in player.play if engine.catalog.cards[card.slug].is_building_card
                 and not board.pass_prevents(match, other, card)]:
        board.take_damage(card, amount)
    result.narration.append(
        f"{top['by']} deals {amount} to each unit, hero and building {tokens.player(other)} controls."
    )
    for ref in ("tech1", "tech2", "tech3", "add_on"):
        if board.still_there(match, other, ref) and not engine._under_construction(player, ref):
            board.damage_building(match, other, ref, amount, result, by=seat)
    board.damage_building(match, other, "base", amount, result, by=seat)


# -- White and blue's handlers (step 13) -----------------------------------------


def _illusion(engine, match, top, part, target, result) -> None:
    """Hallucination: the unit is an Illusion this turn."""
    body = board.body_of(match, *target)
    if body is None:
        return
    body.modifiers.append({"kind": "illusion", "until": "end_of_turn"})
    result.narration.append(f"{top['by']} makes {_thing(match, target)} an Illusion this turn.")


def _copier(engine, match, top, part, target, result) -> None:
    """Manufactured Truth, first: the unit of the caster's that becomes a
    copy, kept for the part that names what it copies."""


def make_copy(engine, match, card: CardInstance, original: CardInstance) -> None:
    """`card` becomes a copy of `original` (the glossary's Copy): the
    printed card -- the one `original` is read as, its printed override
    read first (Manufactured Truth's rulings) -- and none of its runes,
    attachments or modifiers. Nothing arrives."""
    card.copy_of = original.copy_of or original.slug
    card.printed = dict(original.printed) if original.printed else None


def _copy(engine, match, top, part, target, result) -> None:
    """Manufactured Truth: the unit chosen first becomes a copy of this
    one until the end of the turn -- its own printed override kept on the
    modifier, to come back with it."""
    if not top["taken"]:
        return
    copier_key = top["taken"][0]
    card = board.body_of(match, *parse_target(copier_key))
    original = board.body_of(match, *target)
    if card is None or original is None or card is original:
        return
    card.modifiers.append({"kind": "copy", "until": "end_of_turn", "printed": card.printed,
                           "copy_of": card.copy_of})
    make_copy(engine, match, card, original)
    result.narration.append(
        f"{top['by']} makes {_thing(match, parse_target(copier_key))} a copy of "
        f"{_thing(match, target)} until the end of the turn."
    )


def _birds(engine, match, top, part, target, result) -> None:
    """Bird's Nest's upkeep: lost Birds re-summoned, to two in all -- every
    Nest sees the two (its ruling)."""
    seat = top["seat"]
    have = sum(1 for card in match.player(seat).play if card.slug == effects.BIRD)
    lost = max(0, effects.BIRD_LIMIT - have)
    if lost:
        board.summon(engine, match, effects.BIRD, seat, lost, result, by=top["by"])


def _building_targets(engine, match, seat: int) -> list:
    """Every building of `seat`'s that can be dealt damage now: the base,
    the tech buildings and add-on not started this turn, and the building
    cards."""
    player = match.player(seat)
    refs = [ref for ref in ("tech1", "tech2", "tech3", "add_on")
            if board.still_there(match, seat, ref) and not engine._under_construction(player, ref)]
    refs.append("base")
    refs += [card.ref for card in player.play if engine.catalog.cards[card.slug].is_building_card]
    return refs


def _damaged(engine, match, seat: int, ref: str) -> bool:
    if board.is_building(ref):
        return board.building_hp(match, seat, ref) < board.building_max_hp(engine, match, seat, ref)
    card = board.body_of(match, seat, ref)
    return card is not None and card.damage > 0


def _earthquake(engine, match, top, part, target, result) -> None:
    """Earthquake: 4 to each of the opponent's damaged buildings, then 1 to
    each undamaged one -- the second sentence read after the first, so a
    base the first damaged is damaged by then (its ruling)."""
    other = _against(top)
    damaged = [ref for ref in _building_targets(engine, match, other) if _damaged(engine, match, other, ref)]
    for ref in damaged:
        if board.still_there(match, other, ref):
            _deal(engine, match, top, (other, ref), damage_amount(engine, match, top, part.amount), result)
    if match.winner is not None:
        return
    for ref in _building_targets(engine, match, other):
        if ref not in damaged and not _damaged(engine, match, other, ref) and board.still_there(match, other, ref):
            _deal(engine, match, top, (other, ref), damage_amount(engine, match, top, 1), result)


def _make_ninja(engine, match, top, part, target, result) -> None:
    """Fox's Den School: a Ninja for good, while it is in play (its ruling)."""
    body = board.body_of(match, *target)
    if body is None:
        return
    body.modifiers.append({"kind": "ninja", "until": None})
    result.narration.append(f"{top['by']} makes {_thing(match, target)} a Ninja.")


def _den_students(engine, match, top, part, target, result) -> None:
    seat = top["seat"]
    match.player(seat).lasting.append({"kind": effects.DEN_STUDENTS, "until": "end_of_turn"})
    result.narration.append(f"This turn, {tokens.player(seat)}'s Ninja units have haste and stealth.")


def _daigo(engine, match, top, part, target, result) -> None:
    """Hero's Monument: Daigo Stormborne, remembered by the Monument that
    made him, trashed when it leaves play (`board.settle`)."""
    source = board.body_of(match, top["seat"], top.get("source") or "")
    board.summon(engine, match, part.token, top["seat"], 1, result, by=top["by"],
                 made_by=source.id if isinstance(source, CardInstance) else None)


def _hidden(engine, match, top, part, target, result) -> None:
    """Hidden Ninja: stealth this turn, kept past 4 ATK (its ruling) -- and
    a Ninja or the Ninjutsu hero among them draws its card after."""
    body = board.body_of(match, *target)
    if body is None:
        return
    body.modifiers.append({"kind": "keyword", "keyword": "Stealth", "until": "end_of_turn"})
    result.narration.append(f"{top['by']} gives {_thing(match, target)} stealth this turn.")
    ninja = engine.is_ninja(body) if isinstance(body, CardInstance) else (
        (engine.hero_card(body).spec or "").lower() == "ninjutsu")
    if ninja:
        top["ninja"] = True


def _ninja_draw(engine, match, top, part, target, result) -> None:
    if top.get("ninja"):
        _draw(engine, match, top, part, target, result)


def _destroy_tokens(engine, match, top, part, target, result) -> None:
    """Jefferson DeGrey: "Destroy all tokens." -- both sides'."""
    tokens_now = [(player.seat, card.ref) for player in match.players for card in player.play
                  if board.is_token(engine, card.slug)]
    if not tokens_now:
        result.narration.append(f"{top['by']} finds no token to destroy.")
        return
    result.narration.append(f"{top['by']} destroys every token.")
    board.destroy(engine, match, tokens_now, result, cause=top["seat"])


def _look_at(engine, match, top, part, target, result) -> None:
    """A look: what was seen was pictured to the asker alone."""


def _disable_picked(engine, match, top, part, target, result) -> None:
    """Reversal: the patroller it damaged, then disabled -- where it lives."""
    key = top.get("picked")
    if key is None:
        return
    body = board.body_of(match, *parse_target(key))
    if body is None:
        return
    board.disable(body)
    result.narration.append(f"{top['by']} disables {_thing(match, parse_target(key))}.")


def _hail(engine, match, top, part, target, result) -> None:
    """Shuriken Hail: 1 to each patroller, both sides', at once."""
    hit = [(player.seat, ref) for player in match.players for ref in player.patrollers().values()]
    bodies = [board.body_of(match, *one) for one in hit]
    shielded = board.sentry_shields(engine, match, [body for body in bodies if body is not None], result)
    for one, body in zip(hit, bodies):
        if body is not None and body not in shielded:
            _deal(engine, match, top, one, damage_amount(engine, match, top, part.amount), result)


def _snapback(engine, match, top, part, target, result) -> None:
    """Snapback: the opposing hero to its command zone -- no death -- with
    two summoning runes, which keep it there until after its owner's next
    turn (the Card FAQ)."""
    seat, ref = target
    hero = board.body_of(match, seat, ref)
    if hero is None:
        top["chose"] = False
        return
    result.narration.append(f"{top['by']} returns {_thing(match, target)} to the command zone.")
    board.to_command_zone(engine, match, seat, hero, result)
    hero.summoning_runes = 2
    top["snapped"] = [seat, ref]


def _snapback_in(engine, match, top, part, target, result) -> None:
    """Snapback: another hero of that command zone into play, its summoning
    runes removed -- or the same one, where there is no other (its
    rulings)."""
    seat, ref = target
    hero = match.player(seat).hero_by_ref(ref)
    if hero is None or hero.in_play:
        return
    hero.zone = "play"
    hero.level = 1
    hero.damage = 0
    hero.summoning_runes = 0
    hero.arrived_this_turn = True
    hero.exhausted = False
    hero.patrol_slot = None
    hero.bands = {str(engine.hero_card(hero).bands[0].min_level): match.next_sequence()}
    match.record_event("summoned", slug=hero.slug, seat=seat, by="snapback")
    result.narration.append(f"{tokens.hero(hero.slug)} comes into play for {tokens.player(seat)}.")
    board.hero_arrives(engine, match, seat, hero)


def _spar(engine, match, top, part, target, result) -> None:
    """Sparring Partner: readied, but no attack for him this turn."""
    body = board.body_of(match, top["seat"], top.get("source") or "")
    if body is None:
        return
    body.exhausted = False
    body.modifiers.append({"kind": effects.CANT_ATTACK_MODIFIER, "until": "end_of_turn"})
    result.narration.append(f"{top['by']} readies to spar: it can't attack this turn.")


def _fox_speed(engine, match, top, part, target, result) -> None:
    """Speed of the Fox: haste, readiness, armor piercing and +1 ATK this
    turn, for the Ninjutsu hero."""
    hero = board.body_of(match, *target)
    if hero is None:
        return
    for keyword in ("Haste", "Readiness", "Armor piercing"):
        hero.modifiers.append({"kind": "keyword", "keyword": keyword, "until": "end_of_turn"})
    hero.modifiers.append({"kind": "atk", "amount": part.amount, "until": "end_of_turn"})
    result.narration.append(
        f"{top['by']} gives {_thing(match, target)} haste, readiness, armor piercing and +1 ATK this turn."
    )


def _max_level(engine, match, top, part, target, result) -> None:
    """Training Grounds: a hero levelled to its max -- healed at a new band,
    its max level text resolving."""
    seat, ref = target
    hero = board.body_of(match, seat, ref)
    if hero is None:
        return
    before = hero.level
    reached = board.raise_level(engine, hero, engine.hero_card(hero).max_level, match)
    if hero.level == before:
        result.narration.append(f"{_thing(match, target)} gains no level.")
        return
    result.narration.append(
        f"{top['by']} levels {_thing(match, target)} to {hero.level}"
        + (", a new band, and healed." if reached else ".")
    )
    board.max_level_reached(engine, match, seat, hero, result)


def _storm_discard(engine, match, top, part, target, result) -> None:
    """True Power of Storms: a card that costs 3, revealed -- and so named --
    and discarded."""
    seat, ref = target
    slug = _private_slug(ref)
    player = match.player(seat)
    if slug not in player.hand:
        return
    player.hand.remove(slug)
    player.discard.append(slug)
    top.setdefault("stormed", []).append(slug)
    result.narration.append(f"{tokens.player(seat)} reveals and discards {tokens.card(slug)} for {top['by']}.")


def _detector(engine, match, top, part, target, result) -> None:
    """Versatile Style: the Discipline hero a detector this turn."""
    seat = top["seat"]
    for hero in match.player(seat).heroes_in_play:
        if (engine.hero_card(hero).spec or "").lower() == "discipline":
            hero.modifiers.append({"kind": "keyword", "keyword": effects.DETECTOR, "until": "end_of_turn"})
            result.narration.append(f"{top['by']} makes {tokens.hero(hero.slug)} a detector this turn.")
            return


def _grapple(engine, match, top, part, target, result) -> None:
    """Whitestar Grappler: 4 to a unit; one that lives deals its ATK back to
    the Grappler; and it is sidelined if it was patrolling."""
    seat, ref = target
    body = board.body_of(match, seat, ref)
    if body is None:
        return
    _damage(engine, match, top, part, target, result)
    alive = board.body_of(match, seat, ref) is not None and not board.lethal(engine, match, body)
    grappler = board.body_of(match, top["seat"], top.get("source") or "")
    if alive and grappler is not None:
        back = engine.unit_stats(body, match)[0]
        landed = board.take_damage(grappler, back)
        result.narration.append(f"{_thing(match, target)} deals {landed} back to {top['by']}.")
    if alive and body.patrol_slot is not None:
        board.sideline(body)
        result.narration.append(f"{top['by']} sidelines {_thing(match, target)}.")


def _atk_self(engine, match, top, part, target, result) -> None:
    """Young Lightning Dragon: +1 ATK this turn."""
    body = board.body_of(match, top["seat"], top.get("source") or "")
    if body is None:
        return
    body.modifiers.append({"kind": "atk", "amount": part.amount, "until": "end_of_turn"})
    result.narration.append(f"{top['by']} gets +{part.amount} ATK this turn.")


def _number(engine, match, top, part, target, result) -> None:
    """Reputable Newsman's number, kept on him while he is in play."""
    card = board.body_of(match, top["seat"], top.get("source") or "")
    if card is None:
        return
    card.number = top[ASKS_NUMBER]
    other = 2 if top["seat"] == 1 else 1
    result.narration.append(
        f"{top['by']} chooses {card.number}: {tokens.player(other)} can't play spells or upgrades "
        f"that cost {card.number} while it is in play."
    )


#: Each oath in the card's words.
OATHS = {
    effects.OATH_HAND: "I won't play cards from my hand besides workers",
    effects.OATH_DRAW: "I will skip my draw/discard phase",
}


def _oath(engine, match, top, part, target, result) -> None:
    """Oathkeeper's oath, kept on him while he is in play -- "You can't
    break that oath while Oathkeeper is in play"."""
    card = board.body_of(match, top["seat"], top.get("source") or "")
    if card is None:
        return
    card.oath = top[ASKS_OATH]
    result.narration.append(f"{tokens.player(top['seat'])} swears: \"{OATHS[card.oath]}.\"")


def _sideline_all(engine, match, top, part, target, result) -> None:
    """Oathkeeper: "Sideline all patrolling units." -- both sides'."""
    sidelined = [card for player in match.players for card in player.play
                 if engine.catalog.cards[card.slug].is_unit and card.patrol_slot is not None]
    for card in sidelined:
        board.sideline(card)
    result.narration.append(
        f"{top['by']} sidelines every patrolling unit." if sidelined
        else f"{top['by']} finds no patrolling unit to sideline."
    )


def _silence(engine, match, top, part, target, result) -> None:
    """Free Speech: "Silence an opponent." -- until after that opponent's
    next turn (`PlayerState.silenced`)."""
    other = _against(top)
    match.player(other).silenced = True
    result.narration.append(
        f"{top['by']} silences {tokens.player(other)}: their heroes cast no spells and have no "
        "abilities until after their next turn."
    )


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
    "time_target": _time_target,
    "time_rune": _time_rune,
    "time_rune_self": _time_rune_self,
    "sacrifice": _sacrifice,
    "research": _research,
    "rites": _rites,
    "plague": _plague,
    "decay": _decay,
    "shadow_blade": _shadow_blade,
    "poison": _poison,
    "pick_buried": _pick_buried,
    "play_buried": _play_buried,
    "random_discard": _random_discard,
    "runes_on_opposing": _runes_on_opposing,
    "lab_rune": _lab_rune,
    "rune_on_self": _rune_on_self,
    "keyword_self": _keyword_self,
    "negate": _negate,
    "debuff": _debuff,
    "dark_pact": _dark_pact,
    "curse_discard": _curse_discard,
    "drain": _drain,
    "gain_levels": _gain_levels,
    "metamorphosis": _metamorphosis,
    "doom_buff": _doom_buff,
    "gargoyle": _gargoyle,
    "ground": _ground,
    "exhaust_skeletons": _exhaust_skeletons,
    "resurrect": _resurrect,
    "exhaust": _exhaust,
    "geiger": _geiger,
    "prynn_trash": _prynn_trash,
    "fade_check": _fade_check,
    "look": _look,
    "exchange": _exchange,
    "pick_top": _pick_top,
    "play_top": _play_top,
    "to_command_zone": _to_command_zone,
    "bounce": _bounce,
    "distort": _distort,
    "ready": _ready,
    "hold_down": _hold_down,
    "rewind": _rewind,
    "keyword": _keyword,
    "unphase": _unphase,
    "stingers": _stingers,
    "ready_self": _ready_self,
    "disable": _disable,
    "void_star": _void_star,
    "promise": _promise,
    "extra_turn": _extra_turn,
    "banefire": _banefire,
    # White and blue (step 13).
    "illusion": _illusion,
    "copier": _copier,
    "copy": _copy,
    "number": _number,
    "birds": _birds,
    "earthquake": _earthquake,
    "make_ninja": _make_ninja,
    "den_students": _den_students,
    "daigo": _daigo,
    "hidden": _hidden,
    "ninja_draw": _ninja_draw,
    "destroy_tokens": _destroy_tokens,
    "look_at": _look_at,
    "disable_picked": _disable_picked,
    "hail": _hail,
    "snapback": _snapback,
    "snapback_in": _snapback_in,
    "spar": _spar,
    "fox_speed": _fox_speed,
    "max_level": _max_level,
    "storm_discard": _storm_discard,
    "detector": _detector,
    "grapple": _grapple,
    "atk_self": _atk_self,
    "oath": _oath,
    "sideline_all": _sideline_all,
    "silence": _silence,
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
        # Vortoss Emblem's fading 3: it arrives with its runes.
        card.time_runes = engine.fading(card)
        side, ref = parse_target(host)
        if ref.startswith("unit:"):
            card.attached = [int(ref.split(":", 1)[1])]
        else:
            card.attached_hero = host
        result.narration.append(f"{tokens.card(spell)} is attached to {board.named(match, side, ref)}.")
        if spell == effects.VINES:
            # Entangling Vines: "Sideline the unit." (step 13)
            host_card = board.body_of(match, side, ref)
            if host_card is not None and host_card.patrol_slot is not None:
                board.sideline(host_card)
                result.narration.append(f"{board.named(match, side, ref)} is sidelined.")
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
