"""
The turn-start snapshots and the turn's journal: what undo is made of
(docs/codex-bot.md, decision 11; docs/design/codex.md, "Undo's
groundwork").

`begin_turn` calls `snapshot`, which keeps the position the turn's main
phase opens on -- the last three, oldest first -- and empties the
journal. `codex.flow.driver.apply`, the one door every action goes
through, calls `record` with the action and the random outcomes it
consumed (a reshuffle's order, from `StepResult.drawn`). So any point in
a turn is a snapshot plus a prefix of the journal, and `replay` rebuilds
it byte for byte -- the recorded shuffles are handed back rather than
drawn again, so **an undo past a draw deals the same cards**: undo
cannot be used to redraw.

Two undos are over the snapshots alone: `undo_to_turn_start` (the
active player's own) and `undo_to_previous_turn` (which unwinds the
opponent's turn too, so a frontend asks the opponent first). The third,
**the fine undo**, is over the journal: `undo_points` reads the turn as
it replays and names each point between two actions of the active
player's that may be gone back to, and `undo_to` replays the journal up
to one, keeping the other player's tech answers after it (`cut`, which
a spell's cancel shares). **A card that has left the top of a deck
closes every point before it** -- a card seen cannot be unseen, as for
the cancel -- while the start of the turn stays open as it always was
(the author, 2026-10-10). Every undo says what it did, in lines a
frontend puts under what it kept.

Hidden information is in the save already, so a snapshot exposes
nothing new; neither is ever shown to anybody.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Iterable, Optional, Sequence

from codex import tokens
from codex.components import MatchState
from codex.game import RuleRefusal
from codex.prompts import PendingPrompt, PromptKind

if TYPE_CHECKING:
    from codex.engine import RulesEngine
    from codex.flow.driver import DriverRun
    from codex.game import CodexGame
    from codex.prompts import Action

#: How many turn starts are kept.
KEPT_SNAPSHOTS = 3

#: The two fields a snapshot leaves out: it is *of* them.
_HISTORY_FIELDS = ("turn_snapshots", "journal")

TURN_START = "turn_start"
PREVIOUS_TURN = "previous_turn"

#: What an undo says, on the turn message it takes back.
UNDONE = "Undone to the start of the turn."


def undone_to(number: int) -> str:
    """What the fine undo says, under the lines of what it kept."""
    return f"Undone to before action {number} of the turn."


#: The other player's answers a cut keeps, by the kind the journal
#: writes: their tech choice, which is theirs whatever the active
#: player takes back.
KEPT_KINDS = frozenset({"tech_choice"})

#: The journal entries that are no action of the turn: a tech answer --
#: the other player's choice, or the active player's own choice and its
#: confirmation, asked again in the main phase after an undo to the
#: turn's start. None begins an action, and a stretch of them alone is
#: no action to number.
TECH_KINDS = frozenset({"tech_choice", "tech_confirm"})

#: What a position between two actions asks: the main phase's menu, or
#: the patrol's once the main phase has ended -- nothing of an action
#: under way (a target, a defender, a mode). The fine undo goes back to
#: these alone.
BETWEEN_ACTIONS = frozenset({PromptKind.MAIN_ACTION, PromptKind.PATROL})


def cut(journal: Sequence[dict], index: int) -> list[dict]:
    """
    The journal from its `index`th entry on taken back, but for the
    other player's answers after it (`KEPT_KINDS`), which are replayed
    after what is kept. A spell's cancel and the fine undo both cut
    this way.
    """
    return [
        *journal[:index],
        *(entry for entry in journal[index:] if entry["action"]["kind"] in KEPT_KINDS),
    ]


@dataclass(frozen=True)
class UndoPoint:
    """
    A point of this turn the fine undo may go back to: before the
    `index`th journal entry, where the active player's `number`th
    action of the turn begins -- `choice` the answer that began it
    (`Action.choice`: "play", "hire", "end_main"). `said` is what that
    action said, from there to the next, to name it by; `of` is the
    journal's length when the point was offered, so an undo asked for a
    point of a turn that has moved on since is refused.
    """

    index: int
    number: int
    choice: str
    said: tuple[str, ...]
    of: int

    def to_dict(self) -> dict:
        return {
            "index": self.index, "number": self.number, "choice": self.choice,
            "said": list(self.said), "of": self.of,
        }


def tech_again(seat: int) -> str:
    """What an undo says to a player whose tech choice it started over
    -- said whether or not they had picked, so it tells nobody that
    they had."""
    return f"{tokens.addressed(seat)}, the undo starts your tech choice over: choose it again."


def position(match: MatchState) -> dict:
    """The match as saved, without the snapshots and the journal."""
    data = match.to_dict()
    for name in _HISTORY_FIELDS:
        data.pop(name, None)
    return data


def snapshot(match: MatchState) -> None:
    """Keep this position as the turn's start, and begin a new journal."""
    match.turn_snapshots.append(position(match))
    del match.turn_snapshots[:-KEPT_SNAPSHOTS]
    match.journal = []


def latest_snapshot(match: MatchState) -> Optional[dict]:
    """The snapshot most recently taken -- what `driver.apply` compares
    by identity to tell whether a turn began during an action."""
    return match.turn_snapshots[-1] if match.turn_snapshots else None


def record(match: MatchState, action: "Action", outcomes: Iterable[Sequence[str]]) -> None:
    """Write an applied action into the journal with what it drew."""
    match.journal.append({
        "action": action.to_dict(),
        "outcomes": [list(order) for order in outcomes],
    })


def _restore(match: MatchState, data: dict, snapshots: list[dict]) -> None:
    restored = MatchState.from_dict(copy.deepcopy(data))
    restored.turn_snapshots = snapshots
    restored.journal = []
    match.__dict__.update(restored.__dict__)
    start_tech_over(match)
    # The turn's start is now the position with its tech asked again,
    # so a later undo, and a replay of the journal, start from there.
    match.turn_snapshots[-1] = position(match)


def start_tech_over(match: MatchState) -> None:
    """
    **An undo to a turn's start clears every tech choice, a confirmed
    one too, and asks it again** (the author, 2026-10-10). The active
    player's picks, which the ready phase put into the discard pile
    (`teched`), go back into their codex and the choice is owed again,
    asked before the main phase's actions and settled in it
    (`codex.flow.turn.settle_tech`), the upkeep not run twice. The other
    player's picks, never confirmed before their own turn, are cleared,
    whatever the restored position held -- one made before the turn's
    start as surely as one made during it.
    """
    active = match.active_player
    if active.teched is not None and not active.tech_owed:
        for slug in active.teched:
            _take_back(active, slug)
            active.codex[slug] = active.codex.get(slug, 0) + 1
        active.teched = None
        active.tech_owed = True
        active.tech_confirmed = False
    for seat in tech_started_over(match):
        match.player(seat).tech_choice = None


def _take_back(player, slug: str) -> None:
    """One teched copy of `slug` out of the pile it went into: the
    discard pile, the latest copy first -- or, where the upkeep drew and
    shuffled the discard pile into the deck, the deck, then the hand."""
    for pile in (player.discard, player.deck, player.hand):
        if slug in pile:
            del pile[len(pile) - 1 - pile[::-1].index(slug)]
            return


def tech_started_over(match: MatchState) -> tuple[int, ...]:
    """The seats whose tech choice is asked again: whoever owes one not
    yet confirmed -- after an undo, everyone whose choice it started
    over."""
    return tuple(
        player.seat for player in match.players
        if player.tech_owed and not player.tech_confirmed
    )


def replay(
    engine: "RulesEngine",
    game: "CodexGame",
    snapshot_data: dict,
    actions: Iterable[dict],
    history: Optional[list[dict]] = None,
    each: Optional[Callable[[int, MatchState, "DriverRun"], None]] = None,
) -> MatchState:
    """
    The position `snapshot_data` and the journal entries `actions` lead
    to, each applied through the driver with the outcomes it recorded.
    `history` is the snapshot list the rebuilt match carries (by default
    the one snapshot); with the original's, the rebuilt match's
    `to_dict` is the original's byte for byte. `each(index, match, run)`,
    where given, is called after every entry with the live match -- to
    read, never to change -- and what applying it did: how `undo_points`
    reads the turn as it replays.
    """
    from codex.flow import driver
    from codex.prompts import Action

    match = MatchState.from_dict(copy.deepcopy(snapshot_data))
    match.turn_snapshots = copy.deepcopy(history) if history is not None else [copy.deepcopy(snapshot_data)]
    match.journal = []
    for index, entry in enumerate(actions):
        applied = driver.apply(
            engine, game, match, Action.from_dict(entry["action"]),
            outcomes=entry.get("outcomes", ()),
        )
        if isinstance(applied, driver.Refusal):
            raise ValueError(f"a journalled action no longer applies: {applied.reason}")
        if each is not None:
            each(index, match, applied)
    return match


def _snapshot_index(match: MatchState, turn: int) -> Optional[int]:
    for index in range(len(match.turn_snapshots) - 1, -1, -1):
        if match.turn_snapshots[index].get("turn") == turn:
            return index
    return None


def undo_targets(match: MatchState) -> dict[str, int]:
    """
    The undos open on this position, each with the turn it goes back
    to: the start of this turn once its main phase has begun, and the
    start of the previous turn while its snapshot is kept.
    """
    targets = {}
    if match.winner is not None:
        return targets
    if _snapshot_index(match, match.turn) is not None:
        targets[TURN_START] = match.turn
    if match.turn > 1 and _snapshot_index(match, match.turn - 1) is not None:
        targets[PREVIOUS_TURN] = match.turn - 1
    return targets


def undo_to_turn_start(match: MatchState) -> tuple[str, ...]:
    """Put the match back to the start of this turn's main phase, and
    say so (`UNDONE`)."""
    index = _snapshot_index(match, match.turn)
    if index is None or match.winner is not None:
        raise RuleRefusal("There is no start of this turn to go back to.")
    _restore(match, match.turn_snapshots[index], match.turn_snapshots[:index + 1])
    return (UNDONE,)


def undo_to_previous_turn(match: MatchState) -> tuple[str, ...]:
    """Put the match back to the start of the previous turn's main
    phase, unwinding this turn and everything after that start, and
    say so (`UNDONE`)."""
    index = _snapshot_index(match, match.turn - 1)
    if index is None or match.winner is not None:
        raise RuleRefusal("There is no previous turn to go back to.")
    _restore(match, match.turn_snapshots[index], match.turn_snapshots[:index + 1])
    return (UNDONE,)


# -- The fine undo ------------------------------------------------------------


@dataclass(frozen=True)
class _Replayed:
    """One journal entry replayed: what it said, whether a card left the
    top of a deck, and -- where the entry after it may begin an action
    of the active player's, or it is the last -- the position after it,
    as saved (`position`)."""

    lines: tuple[str, ...]
    drew: bool
    position_after: Optional[dict]


def _replayed(engine: "RulesEngine", game: "CodexGame", match: MatchState) -> Optional[list[_Replayed]]:
    """
    This turn's journal replayed from its snapshot, a record an entry --
    or `None` where there is no snapshot of this turn, or an entry no
    longer applies (a game saved before a rule changed), which closes
    the fine undo while the snapshots' undos still stand.
    """
    start = latest_snapshot(match)
    journal = match.journal
    if start is None or start.get("turn") != match.turn:
        return None
    records: list[_Replayed] = []

    def note(index: int, replayed: MatchState, run: "DriverRun") -> None:
        waiting = run.result.next
        between = isinstance(waiting, PendingPrompt) and waiting.kind in BETWEEN_ACTIONS
        last = index + 1 == len(journal)
        boundary = last or (between and journal[index + 1]["action"]["kind"] not in TECH_KINDS)
        records.append(_Replayed(
            tuple(line for group in run.groups for line in group.lines) + tuple(run.result.narration),
            run.drew,
            position(replayed) if boundary else None,
        ))

    try:
        replay(engine, game, start, journal, history=match.turn_snapshots, each=note)
    except ValueError:
        return None
    return records


def _comparable(data: dict) -> dict:
    """A position without the players' tech answers, which are the other
    player's doing and kept through a cut (`KEPT_KINDS`), so an action
    is judged by what it changed itself."""
    return {**data, "players": [{**player, "tech_choice": None} for player in data["players"]]}


def _points(match: MatchState, records: Sequence[_Replayed]) -> tuple[UndoPoint, ...]:
    """`undo_points` over a replay's records (`_replayed`)."""
    journal = match.journal
    starts = [0] + [
        index for index in range(1, len(journal))
        if records[index - 1].position_after is not None
        and journal[index]["action"]["kind"] not in TECH_KINDS
    ]
    boundaries = [*starts, len(journal)]

    def position_at(index: int) -> dict:
        return latest_snapshot(match) if index == 0 else records[index - 1].position_after

    # A card off a deck's top at or after an entry closes every point
    # up to and including it.
    drew_from = [False] * (len(records) + 1)
    for index in range(len(records) - 1, -1, -1):
        drew_from[index] = records[index].drew or drew_from[index + 1]

    points = []
    number = 0
    for start, end in zip(boundaries, boundaries[1:]):
        if all(entry["action"]["kind"] in TECH_KINDS for entry in journal[start:end]):
            continue
        if _comparable(position_at(start)) == _comparable(position_at(end)):
            continue
        number += 1
        if start == 0 or drew_from[start]:
            continue
        points.append(UndoPoint(
            index=start, number=number, choice=journal[start]["action"].get("choice") or "",
            said=tuple(line for record in records[start:end] for line in record.lines),
            of=len(journal),
        ))
    return tuple(points)


def undo_points(engine: "RulesEngine", game: "CodexGame", match: MatchState) -> tuple[UndoPoint, ...]:
    """
    The points of this turn the fine undo may go back to, oldest first:
    before each action of the active player's that began between two
    actions (`BETWEEN_ACTIONS`) and changed the position -- not the
    turn's start, which `undo_targets` offers, and not the other
    player's tech answer, which a cut keeps -- and only while no card
    has left the top of a deck from there on (`StepResult.drew`): a card
    seen cannot be unseen, so a draw closes every point before it, as
    it closes a spell's cancel. Nothing once the game is over, and
    nothing where the turn no longer replays (`_replayed`).
    """
    if match.winner is not None:
        return ()
    records = _replayed(engine, game, match)
    if not records:
        return ()
    return _points(match, records)


def undo_to(engine: "RulesEngine", game: "CodexGame", match: MatchState, index: int,
            *, of: Optional[int] = None) -> tuple[str, ...]:
    """
    Put the match back to before the `index`th entry of this turn's
    journal -- one of `undo_points` -- keeping the other player's tech
    answers after it (`cut`). Returns what the turn says now: the lines
    of the actions kept, then the undone line (`undone_to`). Refused
    with `RuleRefusal` for a point not offered, and where `of` is given
    and the journal is not that long any more: the turn has moved on
    since the point was offered.
    """
    if of is not None and of != len(match.journal):
        raise RuleRefusal("The turn has moved on since those undos were offered.")
    records = None if match.winner is not None else _replayed(engine, game, match)
    points = {point.index: point for point in _points(match, records)} if records else {}
    point = points.get(index)
    if point is None:
        raise RuleRefusal("There is no such point of this turn to go back to.")
    kept = tuple(line for record in records[:index] for line in record.lines)
    rebuilt = replay(
        engine, game, latest_snapshot(match), cut(match.journal, index), history=match.turn_snapshots,
    )
    match.__dict__.update(rebuilt.__dict__)
    return (*kept, undone_to(point.number))
