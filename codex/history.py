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

The two undos the steps build are over the snapshots alone:
`undo_to_turn_start` (the active player's own) and
`undo_to_previous_turn` (which unwinds the opponent's turn too, so a
frontend asks the opponent first). The finer undo, to any action, is a
replay of a journal prefix and is not built yet.

Hidden information is in the save already, so a snapshot exposes
nothing new; neither is ever shown to anybody.
"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Iterable, Optional, Sequence

from codex.components import MatchState
from codex.game import RuleRefusal

if TYPE_CHECKING:
    from codex.engine import RulesEngine
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


def replay(
    engine: "RulesEngine",
    game: "CodexGame",
    snapshot_data: dict,
    actions: Iterable[dict],
    history: Optional[list[dict]] = None,
) -> MatchState:
    """
    The position `snapshot_data` and the journal entries `actions` lead
    to, each applied through the driver with the outcomes it recorded.
    `history` is the snapshot list the rebuilt match carries (by default
    the one snapshot); with the original's, the rebuilt match's
    `to_dict` is the original's byte for byte.
    """
    from codex.flow import driver
    from codex.prompts import Action

    match = MatchState.from_dict(copy.deepcopy(snapshot_data))
    match.turn_snapshots = copy.deepcopy(history) if history is not None else [copy.deepcopy(snapshot_data)]
    match.journal = []
    for entry in actions:
        applied = driver.apply(
            engine, game, match, Action.from_dict(entry["action"]),
            outcomes=entry.get("outcomes", ()),
        )
        if isinstance(applied, driver.Refusal):
            raise ValueError(f"a journalled action no longer applies: {applied.reason}")
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


def undo_to_turn_start(match: MatchState) -> MatchState:
    """Put the match back to the start of this turn's main phase."""
    index = _snapshot_index(match, match.turn)
    if index is None or match.winner is not None:
        raise RuleRefusal("There is no start of this turn to go back to.")
    _restore(match, match.turn_snapshots[index], match.turn_snapshots[:index + 1])
    return match


def undo_to_previous_turn(match: MatchState) -> MatchState:
    """Put the match back to the start of the previous turn's main
    phase, unwinding this turn and everything after that start."""
    index = _snapshot_index(match, match.turn - 1)
    if index is None or match.winner is not None:
        raise RuleRefusal("There is no previous turn to go back to.")
    _restore(match, match.turn_snapshots[index], match.turn_snapshots[:index + 1])
    return match
