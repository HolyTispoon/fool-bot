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
- **It does not decide where one message ends and the next begins.**
  Some steps' lines are an event in their own right rather than the
  opening of the next one, and carrying those forward would join two
  events into one paragraph. Which steps those are is the frontend's
  answer (principle 8 again), so it arrives as `own_message` and the
  loop merely stops carrying across it: the run comes back as a
  sequence of `NarrationGroup`s, each tagged with the step that said
  it, and the frontend picks a dispatcher per group. Before Phase 6
  that distinction was made by the cog calling a *different
  dispatcher*, which is why `RESOLVE_MANEUVER` and the whistle could
  not be in the loop at all.

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
from d12ball.flow import arrivals, periods, turn, turnovers
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


def _lead_in_first(
    step: Callable[..., StepResult],
) -> Callable[..., StepResult]:
    """
    A step that takes no `lead_in`, with the lead-in put back in front
    of its lines.

    `turn.resolve_maneuver` and `arrivals.resolve_loose_ball` both word
    a settled position and neither takes the lines said before it; the
    cog wrappers prepended them and this does the same. An adapter
    rather than a signature change, for `_begin_maneuver_action_selection`'s
    reason: each step has another caller.
    """

    def run(
        engine: RulesEngine,
        game: D12BallGame,
        match: MatchState,
        *,
        lead_in: str = "",
        **kwargs: Any,
    ) -> StepResult:
        result = step(engine, game, match, **kwargs)
        if lead_in:
            result.narration.insert(0, lead_in)
        return result

    return run


#: Which flow function each `FollowOnStep` the driver can run is.
#:
#: Every one of these was a cog method of three lines -- call the step,
#: save, dispatch -- so what moved here is the call and what went is
#: the save (principle 9) and the dispatch (this loop). The signature
#: is uniform on purpose: `(engine, game, match, *, lead_in, **kwargs)`,
#: which is the shape `dispatch_step_result` already called the cog's
#: wrappers with.
#:
#: **A step whose lines are a message of their own is here too since
#: Phase 6's second increment.** The loop used to be able to run only
#: the steps whose narration carries forward into the next one,
#: because carrying was the only thing it could do with a line -- so
#: the reveal, the settled loose ball, the run-back note and the
#: whistle stayed the cog's although their steps had moved long
#: before. `own_message` is what changed: the run comes back as
#: several `NarrationGroup`s and the frontend picks a dispatcher per
#: group, which is where that decision belonged all along
#: (principle 8).
#:
#: **`BEGIN_HIGH_PASS_CONTEST` is here now and was the near miss.**
#: It is the one step with a board write ordered *in front of* it:
#: `begin_loose_ball` draws no board for a High Pass -- the ball is on
#: a receiver both coaches watched catch it -- so rank O3 made it a
#: member of its own precisely so the board the pass moved is written
#: before the contest is announced (see
#: `tests/test_d12ball_high_pass_flow.py`). That ordering is kept
#: without a `stop_before`, because the frontend writes the board
#: **before** it posts any of the run's groups: the pass's board goes
#: up, then the contest is announced over it, exactly as it did when
#: the cog dispatched the step itself. What the loop may not run is a
#: step that puts up a picture of its *own* -- `BEGIN_LOOSE_BALL` and
#: `OFFER_SETUP_PASS_PUSH_BACK` announce the position with a snapshot
#: attached, and a snapshot taken after the run would show a position
#: that has moved on. Those two stop the loop by being absent, and
#: `stop_after` is there for a step in the table that later grows a
#: picture.
MODEL_STEPS: Mapping[FollowOnStep, Callable[..., StepResult]] = {
    FollowOnStep.OFFER_SCORING_ATTEMPT_CHOICE:
        arrivals.offer_scoring_attempt_choice,
    FollowOnStep.BEGIN_SHOOTER_CHOICE: arrivals.begin_shooter_choice,
    FollowOnStep.BEGIN_OWN_GOAL_ROLL: arrivals.begin_own_goal_roll,
    FollowOnStep.FINISH_RUN_BACK: turnovers.finish_run_back,
    FollowOnStep.BEGIN_MANEUVER_ACTION_SELECTION:
        _begin_maneuver_action_selection,
    FollowOnStep.BEGIN_HIGH_PASS_CONTEST: arrivals.begin_high_pass_contest,
    FollowOnStep.RESOLVE_MANEUVER: _lead_in_first(turn.resolve_maneuver),
    FollowOnStep.RESOLVE_LOOSE_BALL:
        _lead_in_first(arrivals.resolve_loose_ball),
    FollowOnStep.ANNOUNCE_RUN_BACK: turnovers.announce_run_back,
    FollowOnStep.END_PERIOD: periods.end_period,
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
class NarrationGroup:
    """
    Lines that belong together, and the step that said them.

    **The unit the frontend renders.** A run of steps says several
    things, and how many messages those are is the frontend's question
    (principle 8) -- but *where one thing ends and the next begins* is
    not a free choice: "X wins the maneuver!" and "the ball moves two
    spaces back" are two events, and joining them into one paragraph
    would be the frontend rewording the position. So the loop reports
    the boundaries and the frontend decides what each side of one
    becomes.

    `step` is the step whose lines these are, or `None` for the lines
    the caller's own step said before the loop started. It is what the
    frontend reads to pick a dispatcher -- a period transition's blocks
    are a message apiece, the reveal is one message, and the last group
    of all is carried into whatever the run stopped on. Naming the step
    rather than a dispatcher is the same choice `FollowOnStep` made:
    the model says what happened and the frontend says how it reaches
    a person.
    """

    narration: tuple[str, ...]
    step: Optional[FollowOnStep] = None


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

    `groups` is every **closed** narration group, in order: the lines
    the frontend has to put up before whatever comes next, each tagged
    with the step that said them. It is empty for the ordinary run,
    where every step's lines carry forward into the next; what is
    carried is `result.narration`, which is the run's last word and
    belongs to the prompt or the follow-on it stopped on.
    """

    result: StepResult
    steps: tuple[FollowOnStep, ...] = ()
    groups: tuple[NarrationGroup, ...] = ()

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
    own_message: Iterable[FollowOnStep] = (),
    speaks_lines: Iterable[FollowOnStep] = (),
) -> DriverRun:
    """
    Run the chain `result` starts until only a frontend can carry on.

    Returns a `DriverRun`. Its `result` is whatever the loop stopped
    on: `narration` is the lines still being carried, `board_changed`
    is true if anything a board draws moved anywhere along the way,
    and `next` is a `PendingPrompt`, a `FollowOn` the driver cannot
    run, or `None`. Anything said that is *not* being carried is in
    `groups`, in order, tagged with the step that said it.

    **The narration is carried, not collected.** A step takes the
    lines said before it as its `lead_in` and returns them as part of
    its own narration -- that is how "a resolved maneuver is one
    message" is already written, and the loop simply keeps doing it.

    **`own_message` is where the carrying stops.** Naming a step there
    says its lines are an event of their own: the loop closes a group
    once that step has run, and the step after it starts with no
    lead-in. It is the frontend's answer rather than the model's --
    a web app with no five-in-five bucket may want every step's lines
    separately, and the Discord cog wants a resolved maneuver to be one
    message and the whistle to be several. Before Phase 6 the same
    distinction was three different dispatchers in `cogs/`, which is
    why the steps that needed one could not be in the loop at all.

    **`speaks_lines` is the exception to it**: a step that takes the
    lines said before it as the *content of its own message* -- the
    final board rides on the whistle and the scoresheet -- must be
    handed them rather than have them posted above it. So a group that
    would close in front of one of those is carried instead.

    **`board_changed` is or-ed across the run**, and that is the
    whole of the arithmetic the loop does about the board. The old
    chain wrote the persistent board between steps, which
    `BoardRefresher` was already collapsing -- its own docstring says
    the intermediate boards are worth nothing, because a coach reads
    the board once everything has finished moving. So the run's answer
    is "something moved", and the frontend writes at most one board
    for it, **before** it posts any of the groups. No step in the
    table draws a board of its own, which is what makes the or safe:
    one that did would be a picture and therefore the frontend's (see
    `stop_after`).

    `stop_after` is the frontend saying it has something to put up at
    a particular point -- a snapshot under the line that names it --
    so the loop must not run past that step and leave the picture
    showing a later position. Naming a step there does not take it out
    of the table; it stops the run *after* it has been run.
    """
    stops = frozenset(stop_after)
    alone = frozenset(own_message)
    speaks = frozenset(speaks_lines)

    groups: list[NarrationGroup] = []
    narration = list(result.narration)
    said_by: Optional[FollowOnStep] = None
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
        said_by = step
        board_changed = board_changed or ran.board_changed
        following = ran.next
        if step in stops:
            break
        if step in alone and not _speaks_them(following, speaks):
            if narration:
                groups.append(NarrationGroup(tuple(narration), step))
            narration = []
            said_by = None

    return DriverRun(
        result=StepResult(
            narration=narration,
            board_changed=board_changed,
            next=following,
        ),
        steps=tuple(steps),
        groups=tuple(groups),
    )


def _speaks_them(
    following: Optional[object],
    speaks: frozenset,
) -> bool:
    """
    Whether the step a run is handing on to takes the lines said so far
    as the content of its own message rather than having them posted
    above it.

    One caller, and a function rather than the condition inline because
    it is the whole of `speaks_lines` and reads as a sentence where the
    `isinstance` does not.
    """
    return isinstance(following, FollowOn) and following.step in speaks


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
