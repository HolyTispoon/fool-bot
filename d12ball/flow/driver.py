"""
The driver: the one loop that runs a turn's own steps.

A flow step changes the match and returns a `StepResult` naming what
happens next (see `result.py`). Until Phase 6 of
docs/model-discord-split.md the *running* of that chain was the cog's:
`D12Ball.dispatch_step_result` read `StepResult.next`, looked the
`FollowOnStep` up in `D12Ball.follow_on_methods`, and awaited the cog
wrapper it found -- which called the flow function, saved, and
dispatched again. So the sequencing of a turn, which is a rule, was
spelled out in Discord's half of the bot and a second frontend would
have had to write its own copy of it.

`advance` is that loop with the Discord taken out. It takes the result
a step just produced and keeps going -- calling the next flow function,
carrying the narration into it as its `lead_in` -- until it reaches
something only a frontend can do. What it hands back is the same shape
it was given: a `StepResult` whose `next` is a `PendingPrompt` (the
turn stops and waits on somebody), a `FollowOn` naming a step that is
still the frontend's, or nothing.

**There is exactly one loop, and this is it.**
`D12Ball.dispatch_step_result` calls `advance` and renders what comes
back; it no longer walks the chain itself. That is the whole point --
two loops is how the bot and a web app come to disagree about what
happens after a Deflect, in the same way two copies of
`pending_prompt` would have them disagree about whose turn it is (see
principle 10 in CLAUDE.md).

**What it does not do**

- **It does not persist.** Principle 9: a step mutates and returns, and
  the caller saves once, after the loop. Collapsing a run of steps into
  one save is the point rather than a side effect -- the old chain
  wrote the match once per step, so a five-step cascade was five
  identical writes of the same file.
- **It does not batch, and it does not draw.** `StepResult.narration`
  comes back as the blocks the steps said, in order; how many messages
  that is, and whether the board is written in front of them, is the
  frontend's (principle 8). `stop_after` is how a frontend says "I have
  a picture to put up of the position *here*, so do not run on past
  it".
- **It does not know what a message is**, so `lead_in` is the only
  thing it carries between steps -- which is a parameter the flow
  functions already take.

**`MODEL_STEPS` is the record of what the loop can run**, the way
`FollowOnStep` is the record of what the cog still dispatches. A member
of the enum that is not a key here is one whose step is still on the
other side of the seam -- a picture, a pin, or a gate. As those move,
rows arrive here and leave the cog's table; when the cog's table is
empty, `FollowOnStep` and `FollowOn` go with it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Optional

from d12ball.components import MatchState
from d12ball.engine import RulesEngine
from d12ball.flow import arrivals, turn, turnovers
from d12ball.flow.result import FollowOn, FollowOnStep, StepResult
from d12ball.game import D12BallGame
from d12ball.prompts import PendingPrompt


def _begin_maneuver_action_selection(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    *,
    lead_in: str = "",
) -> StepResult:
    """
    `turn.begin_maneuver_action_selection`, with the lead-in put back
    in front of its lines.

    The step takes no `lead_in` of its own -- both callers post their
    own line first, the challenge image or the unchallenged notice --
    so the cog wrapper prepended it and this does the same. It is an
    adapter rather than a signature change for the reason the cog's
    own adapters were: the step has another caller.
    """
    result = turn.begin_maneuver_action_selection(engine, game, match)
    if lead_in:
        result.narration.insert(0, lead_in)
    return result


#: Which flow function each `FollowOnStep` the driver can run is.
#:
#: Every one of these was a cog method of three lines -- call the step,
#: save, dispatch -- so what moved here is the call and what went is
#: the save (principle 9) and the dispatch (this loop). The signature
#: is uniform on purpose: `(engine, game, match, *, lead_in, **kwargs)`,
#: which is the shape `dispatch_step_result` already called the cog's
#: wrappers with.
MODEL_STEPS: Mapping[FollowOnStep, Callable[..., StepResult]] = {
    FollowOnStep.OFFER_SCORING_ATTEMPT_CHOICE:
        arrivals.offer_scoring_attempt_choice,
    FollowOnStep.BEGIN_SHOOTER_CHOICE: arrivals.begin_shooter_choice,
    FollowOnStep.BEGIN_OWN_GOAL_ROLL: arrivals.begin_own_goal_roll,
    FollowOnStep.BEGIN_HIGH_PASS_CONTEST: arrivals.begin_high_pass_contest,
    FollowOnStep.FINISH_RUN_BACK: turnovers.finish_run_back,
    FollowOnStep.BEGIN_MANEUVER_ACTION_SELECTION:
        _begin_maneuver_action_selection,
}


def _call(
    step: FollowOnStep,
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    lead_in: str,
    kwargs: Mapping[str, Any],
) -> StepResult:
    """
    Run one step of the table.

    **The arguments arrive by keyword**, which is rank D2's lesson
    (see docs/model-discord-split.md): every spine method the cog
    dispatched to was called `method(..., lead_in=..., **kwargs)`, so
    a parameter that used to be positional arrives named. Keeping that
    exactly is what makes the move invisible to the steps themselves.
    """
    return MODEL_STEPS[step](
        engine, game, match, lead_in=lead_in, **dict(kwargs),
    )


def runs(step: FollowOnStep) -> bool:
    """Whether the driver's loop can run this step itself."""
    return step in MODEL_STEPS


@dataclass(frozen=True)
class DriverRun:
    """
    What one turn of the loop did: where it stopped, and what it ran
    to get there.

    `steps` is there so the caller knows whether the match was touched
    at all. A run that stopped immediately -- the step it was handed
    already ended on a prompt -- changed nothing, and the frontend
    owes it no save; one that ran three steps owes exactly one
    (principle 9). Keeping the count here rather than having the
    frontend diff the result is what stops that save being guessed at.
    """

    result: StepResult
    steps: tuple[FollowOnStep, ...] = ()

    @property
    def ran(self) -> bool:
        """Whether the loop ran any step, and so changed the match."""
        return bool(self.steps)


def advance(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    result: StepResult,
    *,
    stop_after: Iterable[FollowOnStep] = (),
) -> DriverRun:
    """
    Run the chain `result` starts until only a frontend can carry on.

    Returns a `DriverRun`. Its `result` is whatever the loop stopped
    on: `narration` is every line said since the caller's own step,
    `board_changed` is true if anything a board draws moved anywhere
    along the way, and `next` is a `PendingPrompt`, a `FollowOn` the
    driver cannot run, or `None`.

    **The narration is carried, not collected.** A step takes the
    lines said before it as its `lead_in` and returns them as part of
    its own narration -- that is how "a resolved maneuver is one
    message" is already written, and the loop simply keeps doing it.
    A step whose lines must be a message of their own is not in
    `MODEL_STEPS`: the frontend is handed the `FollowOn`, posts what
    it wants to post, and calls back in.

    **`board_changed` is or-ed across the run**, and that is the
    whole of the arithmetic the loop does about the board. The old
    chain wrote the persistent board between steps, which
    `BoardRefresher` was already collapsing -- its own docstring says
    the intermediate boards are worth nothing, because a coach reads
    the board once everything has finished moving. So the run's answer
    is "something moved", and the frontend writes at most one board
    for it. No step in the table draws a board of its own, which is
    what makes the or safe: one that did would be a picture and
    therefore the frontend's (see `stop_after`).

    `stop_after` is the frontend saying it has something to put up at
    a particular point -- a snapshot under the line that names it --
    so the loop must not run past that step and leave the picture
    showing a later position. Naming a step there does not take it out
    of the table; it stops the run *after* it has been run.
    """
    stops = frozenset(stop_after)
    narration = list(result.narration)
    board_changed = result.board_changed
    following = result.next
    steps: list[FollowOnStep] = []

    while isinstance(following, FollowOn) and runs(following.step):
        step = following.step
        ran = _call(
            step,
            engine,
            game,
            match,
            " ".join(narration),
            following.kwargs,
        )
        steps.append(step)
        narration = list(ran.narration)
        board_changed = board_changed or ran.board_changed
        following = ran.next
        if step in stops:
            break

    return DriverRun(
        result=StepResult(
            narration=narration,
            board_changed=board_changed,
            next=following,
        ),
        steps=tuple(steps),
    )


def waiting_on(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
) -> Optional[PendingPrompt]:
    """
    What this match is waiting on, for a frontend that has just been
    handed a run and wants to check it against the save.

    It is `d12ball.prompts.pending_prompt` and nothing else -- the one
    reading, re-exported here so the driver is the whole of what a
    frontend has to import rather than the first of two things. See
    principle 3 in CLAUDE.md.
    """
    from d12ball.prompts import pending_prompt

    return pending_prompt(engine, game, match)
