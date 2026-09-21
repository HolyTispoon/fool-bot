"""
The driver: the one loop that runs a turn's own steps.

A flow step changes the match and returns a `StepResult` naming what
happens next (see `result.py`). Until Phase 6 of
docs/design/model-discord-split.md the *running* of that chain was the cog's:
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

**`MODEL_STEPS` covers `FollowOnStep` exactly**, and
`tests/test_d12ball_package_shape.py` asserts it. Through Phase 6 the
two came apart -- a member with no row here was a step still on the
other side of the seam, a picture, a pin or a gate, and the cog kept a
table of its own for those. The pictures became stops (`stop_after`
and `StepResult.new_play`), the pin a stop too, and the gate a prompt
(`PromptKind.TUTORIAL_CONTINUE`, over `d12ball.flow.gates`), so the
cog's table is gone and a member arriving without a row here fails
the suite rather than a turn.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Optional, Union

from d12ball import tutorial
from d12ball.components import BALL_SPEED_MAX, MatchState, TeamSide
from d12ball.engine import RulesEngine
from d12ball.flow import (
    arrivals,
    effects,
    gates,
    injuries,
    periods,
    rolls,
    turn,
    turnovers,
    windows,
)
from d12ball.flow.result import FollowOn, FollowOnStep, StepResult
from d12ball.game import D12BallGame
from d12ball.prompts import PendingPrompt, PromptKind, pending_prompt


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
#: that has moved on. Both are in the table since the last increment
#: and the frontend names the first in `stop_after` -- the loop runs
#: it and stops, and the frontend takes its picture of the position
#: it left. The second ends on a prompt, which is a stop by
#: definition, and the board it would have drawn is drawn a beat
#: later by the loose ball its answer starts (`PROMPTS_DRAWN_LATER`
#: in `cogs/d12ball/core.py`). A new play stops the loop the same
#: way, on the step's own `new_play`.
MODEL_STEPS: Mapping[FollowOnStep, Callable[..., StepResult]] = {
    FollowOnStep.FINISH_MANEUVER_RESOLUTION:
        arrivals.finish_maneuver_resolution,
    FollowOnStep.OFFER_SCORING_ATTEMPT_CHOICE:
        arrivals.offer_scoring_attempt_choice,
    FollowOnStep.OFFER_SPEED_CHOICE: effects.offer_speed_choice,
    FollowOnStep.BEGIN_RUN_BACK: turnovers.begin_run_back,
    FollowOnStep.BEGIN_SHOOTER_CHOICE: arrivals.begin_shooter_choice,
    FollowOnStep.BEGIN_OWN_GOAL_ROLL: arrivals.begin_own_goal_roll,
    FollowOnStep.BEGIN_LOOSE_BALL: arrivals.begin_loose_ball,
    FollowOnStep.OFFER_SETUP_PASS_PUSH_BACK:
        effects.offer_setup_pass_push_back,
    FollowOnStep.END_PERIOD: periods.end_period,
    FollowOnStep.SEND_TURN_PROMPT: turn.begin_turn,
    FollowOnStep.START_TURN: turn.start_turn,
    FollowOnStep.BEGIN_SUBSTITUTION_WINDOW: windows.begin_substitution_window,
    FollowOnStep.START_SET_UP_SHOT: _lead_in_first(
        arrivals.take_scoring_opportunity,
    ),
    FollowOnStep.CONTINUE_RUN_BACK: turnovers.continue_run_back,
    FollowOnStep.BEGIN_MANEUVER_ACTION_SELECTION:
        _begin_maneuver_action_selection,
    FollowOnStep.SEND_MANEUVER_ACTION_PROMPT: turn.offer_maneuver_action,
    FollowOnStep.RESOLVE_MANEUVER: _lead_in_first(turn.resolve_maneuver),
    FollowOnStep.BEGIN_EFFECT_RESOLUTION: effects.begin_effect_resolution,
    FollowOnStep.CONTINUE_EFFECT: effects.continue_effect,
    FollowOnStep.BEGIN_MANEUVER_SKILL_TEST: turn.begin_maneuver_skill_test,
    FollowOnStep.RESOLVE_LOOSE_BALL:
        _lead_in_first(arrivals.resolve_loose_ball),
    FollowOnStep.ANNOUNCE_RUN_BACK: turnovers.announce_run_back,
    FollowOnStep.FINISH_RUN_BACK: turnovers.finish_run_back,
    FollowOnStep.APPLY_BALL_RECOVERY: turnovers.recover_ball_step,
    FollowOnStep.FINISH_SETUP_COACHING: _lead_in_first(
        periods.finish_setup_coaching,
    ),
    FollowOnStep.FINISH_HALFTIME: _lead_in_first(periods.finish_halftime),
    FollowOnStep.ANNOUNCE_GAME_OVER: periods.announce_game_over,
    FollowOnStep.BEGIN_HIGH_PASS_CONTEST: arrivals.begin_high_pass_contest,
    FollowOnStep.CONTINUE_SHOOTOUT:
        _lead_in_first(periods.continue_shootout),
    FollowOnStep.AUTO_RESOLVE_CHALLENGER:
        _lead_in_first(turn.auto_resolve_challenger),
    FollowOnStep.FINISH_SUBSTITUTION_WINDOW:
        _lead_in_first(windows.finish_substitution_window),
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
    (see docs/design/model-discord-split.md): every spine method the cog
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
    #: The step the run stopped after, with its arguments, where it
    #: stopped because the frontend asked it to (`stop_after`) or
    #: because the step opened a new play -- and `None` where it ran
    #: until only a prompt or nothing was left. `result` is then that
    #: step's own result, verbatim: its lines, and *its* `board_changed`
    #: and `new_play` rather than the run's, because what the frontend
    #: has stopped to draw is the position this step left. The or-ed
    #: answer for the run is `board_changed` below.
    stopped_on: Optional[FollowOn] = None
    #: Whether anything a board draws moved anywhere along the run --
    #: the one write of the persistent board a frontend owes it.
    board_changed: bool = False
    #: What the answer handed back **beside** its lines, where it had
    #: something that is not a sentence: a roll's numbers, for the
    #: picture of the dice. It is `None` for every run of the loop
    #: alone and for every answer that only narrates.
    #:
    #: A field rather than a second return value, because it belongs to
    #: the answer and not to the loop -- `apply` puts it here and
    #: `advance` never touches it. Its type is the answer's own
    #: (`OwnGoalRoll` and its neighbours in `d12ball/flow/`), which is
    #: why it is typed as loosely as it is: a frontend that draws no
    #: dice ignores it, and one that does knows which prompt it asked.
    detail: Optional[object] = None

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
    board_changed = result.board_changed
    last = result
    following = result.next
    stopped_on: Optional[FollowOn] = None
    steps: list[FollowOnStep] = []

    while isinstance(following, FollowOn) and runs(following.step):
        step = following
        ran = _call(
            step.step,
            engine,
            game,
            match,
            " ".join(narration),
            step.kwargs,
        )
        steps.append(step.step)
        narration = list(ran.narration)
        board_changed = board_changed or ran.board_changed
        last = ran
        following = ran.next
        # **A new play stops the run**, whoever asked. The reset's
        # lines are the caption of the board the play starts from,
        # and a frontend has to put that board up before anything
        # behind it moves -- an AI side's coaching window is the next
        # step and rearranges its meeples. The frontend's own stops
        # are the same idea for the pictures it takes.
        if step.step in stops or ran.new_play:
            stopped_on = step
            break
        if step.step in alone and not _speaks_them(following, speaks):
            # Closed even when it said nothing: the frontend may have
            # a picture for this step's group -- the challenge image
            # rides on `AUTO_RESOLVE_CHALLENGER`'s -- and an empty
            # group is how it learns the step ran.
            groups.append(NarrationGroup(tuple(narration), step.step))
            narration = []

    return DriverRun(
        result=StepResult(
            narration=narration,
            board_changed=(
                last.board_changed if stopped_on is not None
                else board_changed
            ),
            next=following,
            new_play=last.new_play if stopped_on is not None else False,
        ),
        steps=tuple(steps),
        groups=tuple(groups),
        stopped_on=stopped_on,
        board_changed=board_changed,
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


@dataclass(frozen=True)
class Action:
    """
    What somebody did, named by the question it answers.

    **It names a prompt rather than a step**, which is the whole
    difference between this and `FollowOn`. A step is what the bot does
    next and the model names it; an action is what a *person* did, and
    the only thing that makes it legal is that the match was waiting on
    exactly that question. So an action carries the `PromptKind` it
    answers and `apply` checks it against `pending_prompt` before
    anything is applied -- which is a rule about whose turn it is, and
    therefore the model's.

    `choice` is which of the prompt's answers it is, where a prompt
    offers more than one: "send" or "decline" on a loose ball, "take"
    or "decline" on a scoring opportunity. A string rather than a
    second enum, because the answers belong to the prompt and not to
    the game -- a kind with one answer leaves it empty, and an
    unrecognised one is refused the way a wrong kind is.

    `arguments` is what the person chose and nothing else: a space, a
    player, a distance. **Anything the position already says is read
    off the prompt instead**, which is why `apply` hands the
    `PendingPrompt` to the answer rather than only the action. The
    loose ball's `skill_type` and the set-up's two numbers are the
    model's own answers to its own question, and a frontend that had to
    send them back could send back different ones.
    """

    kind: PromptKind
    choice: str = ""
    arguments: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Refusal:
    """
    Why an action was not applied, in a sentence a frontend can show.

    **Refusing is the model's, because every reason it can give is a
    rule**: the match is waiting on a different question, or on nothing
    at all, or the answer names a space that player may not take.
    Whose Discord account may press the button is *not* one of those --
    that is a fact about a person and it stays in `SafeView`, where
    docs/design/permissions.md puts it. `apply` takes an action that
    has already been authorised and asks only whether it answers the
    position.

    `waiting_on` is what the match is actually waiting on, so a
    frontend can put the right question back up rather than asking
    twice. It is always set: `pending_prompt` answers for every
    position a match can be in -- a state with nothing to ask falls
    through to the turn prompt rather than to None -- so a refusal
    always has a question to point at.
    """

    reason: str
    waiting_on: PendingPrompt


#: What a click on a prompt the position has moved on from is told,
#: by the kind that was answered. **These are the views' own stale-
#: click sentences, moved here** (principle 5): each says what the
#: position is -- the challenge is settled, the ball has been picked
#: up -- rather than that a click was refused, and a kind with no
#: sentence of its own gets `MOVED_ON`. See `answer`.
STALE_CLICK: Mapping[PromptKind, str] = {
    PromptKind.BALL_HANDLER_SELECTION: "A player has already been selected.",
    PromptKind.PLAYER_ACTION: "That turn has already been taken.",
    PromptKind.MANEUVER_CHALLENGE: "This challenge has already been settled.",
    PromptKind.MANEUVER_ACTION: "This maneuver has already been settled.",
    PromptKind.SKILL_TEST: "This skill test is no longer active.",
    PromptKind.INJURY_TEST: "This injury test is no longer active.",
    PromptKind.OWN_GOAL_ROLL: "This own goal roll is no longer active.",
    PromptKind.SCORE_ATTEMPT: "This score attempt is no longer active.",
    PromptKind.LOOSE_BALL_SKILL_TEST: "This contest is no longer active.",
    PromptKind.SHOOTOUT_TEST: "That skill test has already been rolled.",
    PromptKind.SHOOTOUT_ORDER: "That order is no longer being asked for.",
    PromptKind.SHOOTOUT_PICK: "That pick is no longer being asked for.",
    PromptKind.LOOSE_BALL_PICK: "That side has already answered.",
    PromptKind.SMOOTH: "That Smooth has already been answered.",
    PromptKind.MIND_PULL: "That Mind Pull has already been answered.",
    PromptKind.RUN_BACK_PLAYER: "They no longer have to run back.",
    PromptKind.RUN_BACK_SPACE: "They no longer have to run back.",
    PromptKind.BALL_RECOVERY: "The ball has already been picked up.",
    PromptKind.COACHING_OFFER: "That Coaching Choice has already closed.",
    PromptKind.COACHING_HUB: "That Coaching Choice has already closed.",
    PromptKind.HALFTIME_EXTRA_TOKEN: "That halftime step has already finished.",
    PromptKind.SET_UP_ATTEMPT: (
        "That scoring opportunity has already been settled."
    ),
    PromptKind.SHOOTER_CHOICE: (
        "That scoring opportunity has already been settled."
    ),
    PromptKind.TUTORIAL_CONTINUE: "There is no note to continue from.",
    PromptKind.SETUP_PASS_PUSH_BACK: "That push back has already been settled.",
    PromptKind.LOW_PASS_CHOICE: "That maneuver has already resolved.",
    PromptKind.HIGH_PASS_CHOICE: "That maneuver has already resolved.",
    PromptKind.SETUP_PASS_CHOICE: "That maneuver has already resolved.",
    PromptKind.SPEED_DELTA_CHOICE: "That maneuver has already resolved.",
    PromptKind.DRIBBLE_ADVANCE_CHOICE: "That maneuver has already resolved.",
    PromptKind.DRIBBLE_BURST_CHOICE: "That maneuver has already resolved.",
}

#: The sentence for a kind `STALE_CLICK` does not name.
MOVED_ON = "That answers a question this match has moved on from."


def _refuse(reason: str) -> None:
    """A refusal from inside an answer: `answer` turns it into one."""
    raise ValueError(reason)


def _rail(game: D12BallGame, key: str, options, chosen) -> None:
    """
    Refuse `chosen` where the tutorial's script rails this choice onto
    another of `options`. Every rail a view greys buttons for is asked
    again here, because the prompt may be an old one still sitting in
    the channel -- see `tutorial.resolve_choice`.
    """
    railed = tutorial.resolve_choice(turn.tutorial_beat(game), key, options)
    if railed is not None and chosen != railed:
        _refuse(
            "The tutorial is on one step of a single continuous game, "
            "so this choice is fixed. Use the prompt at the bottom of "
            "the channel."
        )


def _answer_ball_handler_selection(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
    choice: str,
    *,
    player_id: str,
) -> StepResult:
    """Whose hands the ball starts this play in."""
    return turn.select_ball_handler_step(engine, game, match, player_id)


def _answer_run_back_player(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
    choice: str,
    *,
    player_id: str,
) -> StepResult:
    """Which of a doubled-up pair runs back."""
    return turnovers.run_back_player_step(
        engine, game, match, player_id=player_id,
    )


def _answer_run_back_space(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
    choice: str,
    *,
    space_index: int,
    player_id: Optional[str] = None,
) -> StepResult:
    """
    Where the player the prompt named runs back to.

    **Who is running is the prompt's and not the action's.** The
    cascade decides that before anybody is asked -- it is what
    `run_back_prompt` answers -- so an action that carried its own
    player could name one the position is not asking about. A frontend
    that built its buttons for one player may say so, and is refused
    if the position has moved on to another.
    """
    if player_id is not None and player_id != prompt.player_id:
        _refuse(MOVED_ON)
    return turnovers.run_back_space_step(
        engine,
        game,
        match,
        player_id=prompt.player_id,
        space_index=space_index,
    )


def _answer_ball_recovery(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
    choice: str,
    *,
    player_id: str,
) -> StepResult:
    """Who goes and picks an out-of-bounds ball up."""
    return turnovers.recover_ball_step(
        engine, game, match, player_id=player_id,
    )


def _answer_loose_ball_pick(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
    choice: str,
    *,
    player_id: Optional[str] = None,
    skill_type: Optional[str] = None,
) -> StepResult:
    """
    Send somebody after the loose ball, or send nobody.

    `skill_type` is the prompt's: it is which side is on the clock,
    which the position decides and the coach does not. A frontend
    holding one side's prompt says which, and is refused once that
    side has answered -- the other side's prompt is a different
    question. Who may be sent is `loose_ball_candidates`, and the
    tutorial's one loose ball may not be waved through.
    """
    if skill_type is not None and skill_type != prompt.skill_type:
        _refuse("That side has already answered.")
    if choice == "decline":
        refusal = arrivals.loose_ball_decline_refusal(match, prompt.skill_type)
        if refusal is not None:
            _refuse(refusal)
        if tutorial.resolve_choice(
            turn.tutorial_beat(game), "loose_ball_decline", ("never",),
        ) == "never":
            _refuse(
                "This step of the tutorial is about fighting for a "
                "loose ball -- send somebody after it."
            )
        return arrivals.decline_loose_ball_contest(
            engine, game, match, skill_type=prompt.skill_type,
        )
    if player_id not in engine.loose_ball_candidates(match, prompt.side):
        _refuse("That player cannot be sent after the ball from here.")
    return arrivals.choose_loose_ball_contestant(
        engine,
        game,
        match,
        skill_type=prompt.skill_type,
        player_id=player_id,
    )


def _answer_set_up_attempt(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
    choice: str,
) -> StepResult:
    """
    Take the scoring opportunity a set-up opened, or let it go.

    Both of the offer's numbers are the prompt's -- the clock cost of
    the maneuver that offered it, and whether declining lands in the
    long-pass contest. Neither is derivable from the position by the
    time the offer is put, which is what
    `MatchState.pending_scoring_opportunity` exists to remember; see
    docs/design/model-discord-split.md.
    """
    if choice == "decline":
        # The tutorial ends on this shot, so declining it would end
        # the script on a pass and no goal.
        _rail(game, "setup_attempt", ("attempt", "decline"), "decline")
        return arrivals.decline_scoring_attempt(
            engine,
            game,
            match,
            prompt.distance_moved,
            contest=prompt.contest_on_decline,
        )
    return arrivals.take_scoring_opportunity(
        engine,
        game,
        match,
        shooter_id=prompt.player_id,
        maneuver_cost=prompt.distance_moved,
    )


def _answer_shooter_choice(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
    choice: str,
    *,
    shooter_id: str,
) -> StepResult:
    """Which of several candidates takes the shot."""
    if shooter_id not in prompt.player_ids:
        _refuse("That player cannot take the shot from here.")
    return arrivals.take_scoring_opportunity(
        engine, game, match, shooter_id=shooter_id,
    )


def _answer_smooth(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
    choice: str,
    *,
    player_id: Optional[str] = None,
) -> StepResult:
    """
    A Telekinetic takes the ball over, or lets it go past.

    Declining is `continue_smooth` rather than a step of its own, which
    is the queue's one exit: a coach who declines and a Telekinetic who
    was never asked leave by the same door. The player asked is the
    prompt's; a frontend that names one is refused once the queue has
    moved past them.
    """
    if player_id is not None and player_id != prompt.player_id:
        _refuse("That Smooth has already been answered.")
    if choice == "decline":
        return arrivals.decline_smooth_step(
            engine, game, match, player_id=prompt.player_id,
        )
    return effects.take_smooth_step(
        engine, game, match, player_id=prompt.player_id,
    )


def _answer_coaching_offer(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
    choice: str,
    *,
    side: TeamSide,
    coach_name: str = "",
) -> StepResult:
    """
    A coaching window that was *offered* rather than given, taken up or
    passed.

    `coach_name` is what to call the person who passed -- a label the
    frontend supplies rather than a rule, the way a shot's
    `action_label` is. Nothing in the match knows what to call a
    Discord account. `side` is checked against the open window: a
    window that has closed, or the other side's, is a stale click.
    """
    _window_is(match, side)
    if choice == "decline":
        return windows.decline_coaching_step(
            engine, game, match, side=side, coach_name=coach_name,
        )
    return windows.declare_coaching_step(engine, game, match)


def _answer_coaching_hub(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
    choice: str,
    *,
    side: TeamSide,
    formation: Optional[object] = None,
    outgoing_player_id: Optional[str] = None,
    incoming_player_id: Optional[str] = None,
    player_id: Optional[str] = None,
    other_player_id: Optional[str] = None,
    space_index: Optional[int] = None,
    swap_with: Optional[str] = None,
) -> StepResult:
    """
    The Coaching Choice's own five answers, on one message.

    **The hub is the one prompt with several answers that are not
    alternatives**: a coach changes shape, substitutes, exchanges two
    players' zones and moves a meeple within its zone, in any order and
    as often as their allowance lets them, and then says they are done.
    So `choice` names which of the five it is, and the four that change
    something return the note the hub puts back above its own buttons.

    **Its sub-menus are not prompts and never were.** They are steps of
    one answer on one Discord message -- pick a player, then pick where
    -- and what they read off the match to build themselves they read
    from the engine. A restart re-opens at the hub, which is why a
    part-made pick has never been in the save.

    `side` is checked against the open window, and a formation against
    the shapes this board offers; the other three refuse for
    themselves, before they move anybody.
    """
    _window_is(match, side)
    if choice == "done":
        return windows.finish_coaching_step(engine, game, match, side=side)
    if choice == "formation":
        if formation not in engine.available_formations(match):
            _refuse("That formation is not played on this board.")
        return StepResult(
            narration=[engine.apply_formation(match, side, formation)],
            board_changed=True,
        )
    if choice == "substitute":
        return StepResult(
            narration=[
                windows.apply_substitution(
                    engine,
                    game,
                    match,
                    side,
                    outgoing_player_id,
                    incoming_player_id,
                )
            ],
            board_changed=True,
        )
    if choice == "swap":
        return StepResult(
            narration=[
                windows.apply_position_swap(
                    engine, match, side, player_id, other_player_id,
                )
            ],
            board_changed=True,
        )
    return StepResult(
        narration=[
            windows.apply_reposition(
                engine, match, side, player_id, space_index, swap_with,
            )
        ],
        board_changed=True,
    )


def _window_is(match: MatchState, side: TeamSide) -> None:
    """Refuse a coaching answer for a window that is not this side's."""
    if match.pending_coaching_side is None:
        _refuse("That Coaching Choice has already closed.")
    if TeamSide(side) != TeamSide(match.pending_coaching_side):
        _refuse("That Coaching Choice is the other side's.")


def _answer_shootout_order(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
    choice: str,
    *,
    side: TeamSide,
    player_id: Optional[str] = None,
) -> StepResult:
    """
    One name added to a side's shooting order, or the order cleared to
    start again.

    **`side` is the action's and not the prompt's**, and this is the
    second place that is right (the maneuver pick is the first): both
    sides are asked at once and each answers on their own ephemeral
    menu, so which side a click is for is part of what was clicked.
    Who may click it is `SafeView`'s, as always.
    """
    if choice == "restart":
        return periods.restart_shootout_order_step(
            engine, game, match, side=side,
        )
    return periods.shootout_order_step(
        engine, game, match, side=side, player_id=player_id,
    )


def _answer_shootout_pick(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
    choice: str,
    *,
    side: TeamSide,
    player_id: str,
) -> StepResult:
    """Which of a side's remaining players shoots this round."""
    return periods.shootout_pick_step(
        engine, game, match, side=side, player_id=player_id,
    )


def _answer_tutorial_continue(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
    choice: str,
) -> StepResult:
    """The Continue under a tutorial note -- see `d12ball.flow.gates`."""
    return gates.continue_step(engine, game, match)


def _answer_game_over(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
    choice: str,
) -> StepResult:
    """
    Nothing. A finished game asks no question; the rematch under its
    last message opens a *new* game, which is the frontend's and not
    an action on this one. A row here so every kind has an answer,
    and it refuses.
    """
    raise ValueError("This game is over; nothing more is asked of it.")


def _answer_setup_pass_push_back(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
    choice: str,
    *,
    distance: int,
) -> StepResult:
    """Setup Pass's cost, spent: how much further back the ball goes."""
    if distance not in effects.setup_pass_push_back_distances(match):
        _refuse("That push runs off the end of the field.")
    return effects.setup_pass_push_back_step(
        engine, game, match, distance=distance,
    )


def _answer_player_action(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
    choice: str,
    *,
    action_label: str = "shoot to score",
) -> StepResult:
    """
    The turn itself: shoot, maneuver, or call a time out.

    **A time out is not a turn action and is answered here anyway.**
    It is a pause inside a possession rather than a turn -- it records
    its own event kind, and `windows.begin_time_out` is the step. It
    answers this prompt because this is the prompt it is offered on,
    and `turn_action_refusal` is what says when it is not: the same
    three reasons the button would not have been built. The Discord
    view confirms it first (`TimeOutConfirmView`), and Back is not an
    action -- it puts the prompt back up.

    `action_label` is the button's own word for the shot, which the
    tutorial rewrites; it is a label rather than a rule, which is why
    it arrives with the action.
    """
    refusal = turn.turn_action_refusal(engine, game, match, choice)
    if refusal is not None:
        raise ValueError(refusal)
    if choice == "time_out":
        return windows.begin_time_out(engine, game, match)
    if choice == "shoot":
        return turn.begin_shot_step(engine, game, match, action_label)
    return turn.begin_maneuver_step(engine, game, match)


def _answer_maneuver_challenge(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
    choice: str,
    *,
    player_id: Optional[str] = None,
) -> StepResult:
    """
    Which defender walks in to challenge, or nobody.

    Sending is `auto_resolve_challenger`, which the AI's own pick and a
    defender already sharing the ball's space have come through since
    Phase 4 -- three ways to make one pick, one step.
    """
    if choice == "decline":
        # Railed during the tutorial's beat 3: the coach has nobody
        # standing near the ball there, and letting Dinky's maneuver
        # through unchallenged would leave nothing for the lesson's
        # Pressure to defend against.
        if tutorial.resolve_choice(
            turn.tutorial_beat(game), "challenge_decline", ("never",),
        ) == "never":
            _refuse(
                "This step of the tutorial wants a challenger sent. "
                "Use the prompt at the bottom of the channel."
            )
        return turn.decline_challenge_step(engine, game, match)
    if player_id not in match.challenge_candidates():
        _refuse("That player cannot challenge from where they stand.")
    return turn.auto_resolve_challenger(engine, game, match, player_id)


def _answer_maneuver_action(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
    choice: str,
    *,
    side: str,
    maneuver_key: str,
) -> StepResult:
    """
    One coach's maneuver, picked.

    **The refusal is asked here and raised**, which is what puts it
    through `answer`'s own `ValueError` door: "you have already chosen",
    a card the tutorial's rail does not want and a card that is not in
    this turn's hand are all rules about the position. Whose account
    may press the button is not, and is answered before this ever runs
    -- see `maneuver_pick_refusal`.

    `side` is the action's rather than the prompt's, and it is the one
    place that is right: the prompt is **one message with both sides'
    rows on it**, so which side a click answers for is part of what was
    clicked.
    """
    refusal = turn.maneuver_pick_refusal(
        engine, game, match, side, maneuver_key,
    )
    if refusal is not None:
        raise ValueError(refusal)
    return turn.maneuver_pick_step(
        engine, game, match, side=side, maneuver_key=maneuver_key,
    )


def _answer_injury_test(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
    choice: str,
    *,
    player_id: Optional[str] = None,
) -> tuple[object, StepResult]:
    """
    The injury test the prompt names, rolled.

    **Who rolls is the prompt's**, because the queue decides it: the
    tests are owed in the order a contest queued them, and an action
    naming its own player could answer for somebody the position is
    not asking about. A frontend whose button was built for one player
    says so with `player_id`, and is refused once the queue has moved
    past them -- except on an Overdrive, where the player named is the
    Cyborg declaring.
    """
    if choice == "overdrive":
        return _declared_overdrive(engine, game, match, prompt, player_id)
    if player_id is not None and player_id != prompt.player_id:
        _refuse("This injury test is no longer active.")
    return injuries.injury_test_step(engine, game, match, prompt.player_id)


def _answer_mind_pull(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
    choice: str,
    *,
    player_id: Optional[str] = None,
) -> object:
    """
    A Telekinetic reaches for the ball, or lets it go past.

    Reaching costs a token whether or not it lands, which is why the
    two are different answers rather than one with a flag. The player
    asked is the prompt's, as for the Smooth.
    """
    if player_id is not None and player_id != prompt.player_id:
        _refuse("That Mind Pull has already been answered.")
    if choice == "decline":
        return arrivals.decline_mind_pull_step(
            engine, game, match, player_id=prompt.player_id,
        )
    return arrivals.attempt_mind_pull_step(
        engine, game, match, player_id=prompt.player_id,
    )


def _answer_halftime_extra_token(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
    choice: str,
    *,
    player_id: str,
    side: Optional[TeamSide] = None,
) -> StepResult:
    """
    Which fielded player loses an extra token at the break -- one of
    this side's own, and not an injured one. `side` is the prompt's;
    a frontend that names one is refused once the other side is asked.
    """
    if side is not None and TeamSide(side) != prompt.side:
        _refuse("That halftime step has already finished.")
    setup = match.setup_for_side(prompt.side)
    if player_id not in setup.field_players or player_id in match.injured:
        _refuse("That player cannot lose a token here.")
    return periods.halftime_extra_token_step(
        engine, game, match, player_id=player_id,
    )


def _answer_own_goal_roll(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
    choice: str,
    *,
    player_id: Optional[str] = None,
) -> tuple[object, StepResult]:
    """
    The own-goal roll, and the numbers the dice are drawn from.

    **The first answer that hands back two things**, which is the shape
    `own_goal_roll_step` settled and every roll that follows it copies:
    the `StepResult` is the arithmetic and the verdict, and the
    `OwnGoalRoll` beside it is the same numbers for the picture. They
    are separate because the frontend puts the image *between* the two
    lines. `apply` puts it in `DriverRun.detail`.
    """
    if choice == "overdrive":
        return _declared_overdrive(engine, game, match, prompt, player_id)
    return effects.own_goal_roll_step(engine, game, match)


#: The six prompts a roll is asked on, and therefore the six an
#: Overdrive can be declared on. The rules' own list.
ROLL_KINDS = frozenset(rolls.OVERDRIVE_ROLLERS)


def _declared_overdrive(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
    player_id: str,
) -> StepResult:
    """
    The `overdrive` choice, shared by all six roll prompts.

    **It answers the prompt without settling it**, and comes back on
    the same question -- the roll is still owed. That is the coaching
    hub's shape rather than a new one: four of its five choices change
    the position and return to it, and only "done" ends the window.
    See `rolls.declare_overdrive_step`.
    """
    return rolls.declare_overdrive_step(
        engine, game, match, prompt, player_id,
    )


def _answer_skill_test(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
    choice: str,
    *,
    player_id: Optional[str] = None,
) -> tuple[object, StepResult]:
    """
    The maneuver's skill test, off the button either coach may press.

    **It takes no arguments at all**, which is what "nothing rolls
    dice on its own" looks like from this side: the action is that
    somebody pressed, and everything the roll needs is the position.
    A tie comes back as this same prompt worded by what happened, so a
    frontend puts the question up again without knowing that a tie is
    a thing.
    """
    if choice == "overdrive":
        return _declared_overdrive(engine, game, match, prompt, player_id)
    return rolls.skill_test_step(engine, game, match)


def _answer_loose_ball_skill_test(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
    choice: str,
    *,
    player_id: Optional[str] = None,
) -> tuple[object, StepResult]:
    """The contest for the ball, which the long High Pass borrows."""
    if choice == "overdrive":
        return _declared_overdrive(engine, game, match, prompt, player_id)
    return rolls.loose_ball_test_step(engine, game, match)


def _answer_score_attempt(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
    choice: str,
    *,
    player_id: Optional[str] = None,
) -> object:
    """
    The shot -- or the coach changing their mind about taking it.

    **"Back" is an answer to this prompt and not the absence of one**,
    which is why it is a choice here rather than a second prompt: the
    shot has been declared and not yet rolled, and walking it back is
    a move the position allows for exactly as long as nothing else has
    happened. `retract_shot_step` is what refuses when it no longer
    does.
    """
    if choice == "back":
        return rolls.retract_shot_step(engine, game, match)
    if choice == "overdrive":
        return _declared_overdrive(engine, game, match, prompt, player_id)
    return rolls.score_attempt_step(engine, game, match)


def _answer_shootout_test(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
    choice: str,
    *,
    player_id: Optional[str] = None,
) -> tuple[object, StepResult]:
    """Both shooters' dice, and the goal one of them scores."""
    if choice == "overdrive":
        return _declared_overdrive(engine, game, match, prompt, player_id)
    return rolls.shootout_test_step(engine, game, match)


def _answer_low_pass_choice(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
    choice: str,
    *,
    distance: int,
    receiver_id: Optional[str] = None,
) -> StepResult:
    """
    A won Low Pass, Skilled Pass, or the free pass a beaten Skilled
    Pass hands the defense -- which card it is and whether it is free
    are the prompt's, read back off the position.

    `receiver_id` is the one argument a *second* question asks, where
    several teammates share the landing space. Match state does not
    record that the passer has been asked it (see
    `effect_choice_prompt`), so a frontend that asks it separately
    sends the answer here with the distance; one that does not leaves
    it out and the step takes whoever is standing there. Both are
    checked against the position: the distances on offer are
    `pass_candidates`', and the receivers `low_pass_receivers`'.
    """
    key = prompt.maneuver_key or "low_pass"
    if distance not in {
        offered for offered, _ in engine.pass_candidates(match, key)
    }:
        _refuse("That pass is not on offer from where the ball is now.")
    if receiver_id is not None and receiver_id not in (
        engine.low_pass_receivers(match, distance)
    ):
        _refuse("That player is no longer standing there.")
    return effects.low_pass_step(
        engine,
        match,
        distance,
        receiver_id=receiver_id,
        key=prompt.maneuver_key or "low_pass",
        free=prompt.free,
    )


def _answer_high_pass_choice(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
    choice: str,
    *,
    distance: int,
) -> StepResult:
    """
    A won High Pass, thrown as far as the coach chose -- one of the
    distances that fit on the field, and the tutorial's where it rails
    one.
    """
    distances = engine.high_pass_distance_options(match)
    if distance not in distances:
        _refuse(
            f"A {distance}-space pass runs off the end of the field "
            "from where the ball is now."
        )
    _rail(game, "high_pass", distances, distance)
    return effects.high_pass_step(engine, match, distance)


def _answer_setup_pass_choice(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
    choice: str,
    *,
    distance: Optional[int] = None,
) -> StepResult:
    """
    Setup Pass's second half: where the ball goes.

    A pass with nowhere to go at all is the card's one way out of play,
    and it is the *absence* of a distance rather than a choice a coach
    makes -- `RulesEngine.setup_pass_distances` empty is what decides
    it, which is why the frontend does not put a menu up for it.
    """
    distances = engine.setup_pass_distances(match)
    if distance is None:
        if distances:
            _refuse("This Setup Pass still has somewhere to go.")
        return effects.setup_pass_out_step(match)
    if distance not in distances:
        _refuse(
            "That distance is not on offer any more -- 0 spaces needs "
            "a teammate in your own space, and every other distance "
            "has to fit on the field."
        )
    return effects.setup_pass_step(engine, match, distance)


def _answer_speed_delta_choice(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
    choice: str,
    *,
    target_speed: int,
) -> StepResult:
    """
    The ball-speed manipulation a maneuver's effect ends on.

    **Whether a turnover happened is read here rather than sent**, and
    that is a rule rather than bookkeeping: a steal -- basic or
    Intercept -- has already flipped possession and run the defense
    back by the time this is asked, and a dribble never caused a
    turnover at all. It was `SpeedDeltaChoiceView.choose`'s own reading
    until Phase 6; it is the same reading, in the one place a second
    frontend can also ask it.
    """
    skill = engine.player_catalog.effective_profile(
        engine.get_player_definition(prompt.player_id),
    )
    reach = skill.offense if prompt.skill_type == "offense" else skill.defense
    targets = sorted({
        max(1, min(BALL_SPEED_MAX, match.ball.speed + delta))
        for delta in range(-reach, reach + 1)
    })
    if target_speed not in targets:
        _refuse(
            f"The ball's speed can only be set between {targets[0]} and "
            f"{targets[-1]} from here."
        )
    # The tutorial's speed rail is "take the highest offered" -- the
    # cap is the stealer's own defensive skill, so the script cannot
    # name a number.
    _rail(game, "speed", targets, target_speed)

    turnover_occurred = (
        match.defense_maneuver in ("steal", "intercept")
        and prompt.skill_type == "defense"
    )
    return effects.speed_choice_step(
        engine,
        game,
        match,
        target_speed=target_speed,
        turnover_occurred=turnover_occurred,
    )


def _answer_dribble_advance_choice(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
    choice: str,
    *,
    distance: int,
) -> StepResult:
    """A Playmaker's won Dribble Advance: one space or two."""
    if distance not in (1, 2):
        _refuse("A Dribble Advance is one space or two.")
    _rail(game, "dribble_advance", (1, 2), distance)
    return effects.dribble_advance_step(engine, game, match, distance)


def _answer_dribble_burst_choice(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    prompt: PendingPrompt,
    choice: str,
    *,
    distance: int,
) -> StepResult:
    """A won Dribble Burst: how far, at a token a space."""
    if distance not in engine.dribble_burst_distances(match):
        _refuse("That distance is no longer available.")
    return effects.dribble_burst_step(engine, game, match, distance)


#: Which model function answers each `PromptKind` the driver can apply
#: an action to.
#:
#: **The record of how much of a turn a second frontend can drive**,
#: the way `MODEL_STEPS` is the record of what the loop can run. A kind
#: that is not a key here is one whose answer is still inside a view
#: body -- `answers` says so, and a frontend that meets one has to know
#: what to do about it itself. As those move, rows arrive here; when
#: every kind has one, a web app can play a whole game through this
#: module and nothing else.
#:
#: The signature is uniform: `(engine, game, match, prompt, choice,
#: **arguments)`. `prompt` is there so an answer reads what the
#: *position* decided off the question rather than off the action --
#: which side owes a loose-ball pick, which card is resolving, what the
#: set-up's two numbers were. An action carries only what a person
#: chose.
#:
#: **An answer may hand back two things**, the way
#: `own_goal_roll_step` does: `(detail, StepResult)`, where the detail
#: is the numbers a picture is made of and the result is the sentences
#: about them. `apply` splits the pair and puts the detail in
#: `DriverRun.detail`; an answer with no picture returns the
#: `StepResult` alone.
ANSWERS: Mapping[PromptKind, Callable[..., Any]] = {
    PromptKind.TUTORIAL_CONTINUE: _answer_tutorial_continue,
    PromptKind.GAME_OVER: _answer_game_over,
    PromptKind.SETUP_PASS_PUSH_BACK: _answer_setup_pass_push_back,
    PromptKind.BALL_HANDLER_SELECTION: _answer_ball_handler_selection,
    PromptKind.RUN_BACK_PLAYER: _answer_run_back_player,
    PromptKind.RUN_BACK_SPACE: _answer_run_back_space,
    PromptKind.BALL_RECOVERY: _answer_ball_recovery,
    PromptKind.LOOSE_BALL_PICK: _answer_loose_ball_pick,
    PromptKind.SET_UP_ATTEMPT: _answer_set_up_attempt,
    PromptKind.SHOOTER_CHOICE: _answer_shooter_choice,
    PromptKind.SMOOTH: _answer_smooth,
    PromptKind.OWN_GOAL_ROLL: _answer_own_goal_roll,
    PromptKind.PLAYER_ACTION: _answer_player_action,
    PromptKind.COACHING_OFFER: _answer_coaching_offer,
    PromptKind.COACHING_HUB: _answer_coaching_hub,
    PromptKind.SHOOTOUT_ORDER: _answer_shootout_order,
    PromptKind.SHOOTOUT_PICK: _answer_shootout_pick,
    PromptKind.MANEUVER_CHALLENGE: _answer_maneuver_challenge,
    PromptKind.MANEUVER_ACTION: _answer_maneuver_action,
    PromptKind.INJURY_TEST: _answer_injury_test,
    PromptKind.MIND_PULL: _answer_mind_pull,
    PromptKind.HALFTIME_EXTRA_TOKEN: _answer_halftime_extra_token,
    PromptKind.SKILL_TEST: _answer_skill_test,
    PromptKind.LOOSE_BALL_SKILL_TEST: _answer_loose_ball_skill_test,
    PromptKind.SCORE_ATTEMPT: _answer_score_attempt,
    PromptKind.SHOOTOUT_TEST: _answer_shootout_test,
    PromptKind.LOW_PASS_CHOICE: _answer_low_pass_choice,
    PromptKind.HIGH_PASS_CHOICE: _answer_high_pass_choice,
    PromptKind.SETUP_PASS_CHOICE: _answer_setup_pass_choice,
    PromptKind.SPEED_DELTA_CHOICE: _answer_speed_delta_choice,
    PromptKind.DRIBBLE_ADVANCE_CHOICE: _answer_dribble_advance_choice,
    PromptKind.DRIBBLE_BURST_CHOICE: _answer_dribble_burst_choice,
}


#: Which of a prompt's answers each kind offers, where it offers more
#: than one.
#:
#: A separate table rather than a check inside each adapter, for
#: `MODEL_STEPS`'s reason: it is a *list*, and a frontend that wants to
#: know what buttons a prompt has may read it. An unlisted kind takes
#: the empty choice and nothing else, which is what a prompt with one
#: answer means.
CHOICES: Mapping[PromptKind, tuple[str, ...]] = {
    # **Every roll prompt offers two answers**, and the second one
    # does not settle it: Overdrive is declared before the dice and
    # the roll is still owed afterwards. `SCORE_ATTEMPT` has its
    # own third, below, because a declared shot can also be walked
    # back.
    **{
        kind: ("roll", "overdrive")
        for kind in ROLL_KINDS
    },
    PromptKind.LOOSE_BALL_PICK: ("send", "decline"),
    PromptKind.SET_UP_ATTEMPT: ("take", "decline"),
    PromptKind.SMOOTH: ("take", "decline"),
    PromptKind.MIND_PULL: ("take", "decline"),
    PromptKind.MANEUVER_CHALLENGE: ("send", "decline"),
    PromptKind.PLAYER_ACTION: ("shoot", "maneuver", "time_out"),
    PromptKind.SHOOTOUT_ORDER: ("send", "restart"),
    PromptKind.COACHING_OFFER: ("declare", "decline"),
    PromptKind.COACHING_HUB: (
        "formation", "substitute", "swap", "reposition", "done",
    ),
    PromptKind.SCORE_ATTEMPT: ("roll", "back", "overdrive"),
}


def can_answer(kind: PromptKind) -> bool:
    """Whether the driver can answer this prompt itself."""
    return kind in ANSWERS


def _argument_mismatch(action: Action) -> Optional[str]:
    """
    Why this action's arguments do not fit the answer's signature, or
    None. The signature is the contract: every argument an answer takes
    is keyword-only, so the names are the whole of it.
    """
    parameters = inspect.signature(ANSWERS[action.kind]).parameters
    keyword = {
        name: parameter
        for name, parameter in parameters.items()
        if parameter.kind is inspect.Parameter.KEYWORD_ONLY
    }
    unknown = set(action.arguments) - set(keyword)
    if unknown:
        return (
            f"This question does not take {', '.join(sorted(unknown))}."
        )
    missing = [
        name
        for name, parameter in keyword.items()
        if parameter.default is inspect.Parameter.empty
        and name not in action.arguments
    ]
    if missing:
        return f"This answer needs {', '.join(missing)}."
    return None


def _choice_is_offered(kind: PromptKind, choice: str) -> bool:
    """Whether this kind offers the named answer."""
    offered = CHOICES.get(kind)
    if offered is None:
        return choice == ""
    return choice in offered


@dataclass(frozen=True)
class Answered:
    """
    What one answer did, before anything that follows it has run.

    `result` is the `StepResult` the answer produced and `detail` is
    the numbers a picture is made of, where it had any (see
    `DriverRun.detail`).

    **It exists because the Discord frontend renders an answer before
    it runs what follows.** A prompt in this bot is a message with
    buttons on it, and answering it *replaces* that message with what
    the answer said -- an edit rather than a new message, which is one
    Discord request instead of two and therefore the frontend's
    decision (principle 8). A frontend doing that has to see the
    answer's own lines before the chain behind it runs, because the
    chain's first step takes those lines as its lead-in. So `answer`
    stops there and `apply` is `answer` plus `advance` for a frontend
    that wants the whole turn in one call.
    """

    result: StepResult
    detail: Optional[object] = None


def answer(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    action: Action,
) -> Union[Answered, Refusal]:
    """
    Answer the question this match is waiting on -- and nothing after
    it.

    **The other half of the seam.** `pending_prompt` says what a match
    is waiting on and `advance` runs what a step starts; this is what
    happens in between: somebody answers, and the answer is checked
    against the question before it changes anything. Checking it is a
    rule -- it is "whose turn is it", one click later -- so it is here
    and not in a frontend.

    **It does not persist** (principle 9) and it does not authorise
    (docs/design/permissions.md). Those are the two things it is
    deliberately not, and both have a home already: the driver takes an
    action that has already been authorised and asks only whether it
    answers the position.

    Two things are refused here, and they are the same rule read at
    different depths:

    - the match is waiting on a *different* question, which is the
      stale click a restart re-attaching an old prompt produces, and
      the reason the refusal carries what it is really waiting on;
    - the kind offers no such answer -- a "decline" on a prompt that
      cannot be declined.

    A third comes from the answer itself: a step raises `ValueError`
    where the position refuses what was chosen (a space that player may
    not take, a side that cannot be held back), and that is a refusal
    with its sentence already written, so it is returned as one rather
    than left to each frontend to turn into a reply of its own. The
    three views that catch it today word it exactly this way.

    A kind with no row in `ANSWERS` is **not** a refusal: it is a
    question this module cannot answer yet, which is a fact about the
    seam rather than about the position, so it raises. Ask `can_answer`
    first; the cog does.
    """
    waiting = pending_prompt(engine, game, match)
    if waiting.kind is not action.kind:
        return Refusal(
            STALE_CLICK.get(action.kind, MOVED_ON), waiting_on=waiting,
        )
    # **Ahead of the choice check**, so a kind with no row raises the
    # same way whatever the action says -- "that answer is not
    # offered", for a question this module cannot answer at all, would
    # read as a rule and is a fact about the seam.
    if not can_answer(action.kind):
        raise LookupError(
            f"No model answer for {action.kind.name}; ask `can_answer` "
            "first -- see ANSWERS in d12ball/flow/driver.py.",
        )
    if not _choice_is_offered(action.kind, action.choice):
        return Refusal(
            "That is not one of the answers this question offers.",
            waiting_on=waiting,
        )

    # **The arguments are checked against the answer's own signature
    # before it runs**, so an argument this question does not take,
    # or one it needs and was not given, is a refusal rather than a
    # `TypeError` out of the middle of a step that may already have
    # moved something.
    unexpected = _argument_mismatch(action)
    if unexpected is not None:
        return Refusal(unexpected, waiting_on=waiting)

    try:
        answered = ANSWERS[action.kind](
            engine,
            game,
            match,
            waiting,
            action.choice,
            **dict(action.arguments),
        )
    except ValueError as refused:
        # The position itself refusing what was chosen. It arrives as a
        # `ValueError` because that is how the steps have always said
        # it -- `MatchState.run_back_player` and its neighbours raise
        # with the sentence already written -- and a refusal is what it
        # has always meant. See `loose_ball_decline_refusal`, which is
        # the same answer asked without applying anything.
        return Refusal(str(refused), waiting_on=waiting)

    if isinstance(answered, tuple):
        detail, result = answered
        return Answered(result=result, detail=detail)
    return Answered(result=answered)


#: `answer` under a second name, for a caller whose own namespace
#: holds an `answer` of its own (a Discord view with a method of that
#: name). The same function.
driver_answer = answer


def apply(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    action: Action,
    *,
    stop_after: Iterable[FollowOnStep] = (),
    own_message: Iterable[FollowOnStep] = (),
    speaks_lines: Iterable[FollowOnStep] = (),
) -> Union[DriverRun, Refusal]:
    """
    Answer the question this match is waiting on, and run what follows.

    `answer` plus `advance`, which is a whole turn of the game in one
    call: a frontend authorises the person, calls this, saves the match
    once, and renders what comes back. That is the shape a web app
    wants, and it is the thing "the web app is a frontend rather than a
    port" means.

    Returns the same `DriverRun` `advance` returns, with `detail` set
    where the answer had a picture's numbers to hand back -- or the
    `Refusal` `answer` gave, unchanged.

    **A frontend that renders the answer before running the chain
    calls `answer` instead**, and then `advance` itself. The Discord
    cog does that wherever the answer *replaces* the prompt it
    answered, because the first step of the chain takes the answer's
    own lines as its lead-in and there would be nothing left to edit
    the message with. Both go through `answer`, so there is still one
    reading of whether an action is legal.

    `ran` means what it means on a plain run -- whether the *loop* ran
    a step -- and must not be read as "was anything applied". An answer
    that ends on a prompt with no follow-on has run no step and has
    still changed the match: a player walked back, a pass was thrown.
    **Every answer that returns rather than refuses owes a save.**
    """
    answered = answer(engine, game, match, action)
    if isinstance(answered, Refusal):
        return answered

    run = advance(
        engine,
        game,
        match,
        answered.result,
        stop_after=stop_after,
        own_message=own_message,
        speaks_lines=speaks_lines,
    )
    return DriverRun(
        result=run.result,
        steps=run.steps,
        groups=run.groups,
        stopped_on=run.stopped_on,
        board_changed=run.board_changed,
        detail=answered.detail,
    )
