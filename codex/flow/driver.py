"""
The loop and the answers: `MODEL_STEPS` runs every `FollowOnStep`,
`advance` runs a chain until a prompt, and `answer`/`apply` take an
action, refuse it while the bot owes a step, check it against the
pending prompt (or a standing one) and the position, and run it.

Copied from `d12ball/flow/driver.py`, whose docstrings say why each
piece is the shape it is (docs/design/model-discord-split.md,
docs/design/game-service.md). **`apply` is the one door** every click
and every client request goes through, which is why it is where the
journal is written (docs/codex-bot.md, decision 11): an applied action
is recorded with the random outcomes it consumed, unless the turn began
during it, in which case it belongs to the turn the snapshot closed.

It does not persist and it does not authorise: whose Discord account may
press a button is the frontend's question, and the save is the
service's (step 3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Iterable, Mapping, Optional, Sequence, Union

from codex import history, tokens
from codex.components import MatchState
from codex.flow import actions, combat, turn
from codex.flow.result import FollowOn, FollowOnStep, Headline, StepResult
from codex.game import RuleRefusal
from codex.prompts import (
    CHOICES,
    Action,
    PendingPrompt,
    PromptKind,
    pending,
    standing_prompts,
    with_options,
)

if TYPE_CHECKING:
    from codex.engine import RulesEngine
    from codex.game import CodexGame

__all__ = [
    "ANSWERS", "Action", "Answered", "DriverRun", "MODEL_STEPS", "NarrationGroup",
    "Refusal", "advance", "answer", "apply",
]


#: Every `FollowOnStep`, run. `tests/test_codex_driver_actions.py` holds
#: it to the enum exactly.
MODEL_STEPS: Mapping[FollowOnStep, Callable[..., StepResult]] = {
    FollowOnStep.BEGIN_TURN: turn.begin_turn,
    FollowOnStep.DRAW_PHASE: turn.draw_phase,
    FollowOnStep.BEGIN_TECH: turn.begin_tech,
}


@dataclass(frozen=True)
class NarrationGroup:
    """Lines that belong together, and the step that said them -- the
    unit a frontend renders (`d12ball.flow.driver.NarrationGroup`)."""

    narration: tuple[str, ...]
    step: Optional[FollowOnStep] = None
    arguments: Mapping[str, Any] = field(default_factory=dict)
    headlines: tuple[Headline, ...] = ()

    def to_dict(self) -> dict:
        return {
            "narration": list(self.narration),
            "step": None if self.step is None else self.step.name,
            "headlines": [headline.to_dict() for headline in self.headlines],
        }


@dataclass(frozen=True)
class DriverRun:
    """What one turn of the loop did, and where it stopped. `drawn` is
    every shuffle's order along the run, for the journal -- never for a
    frontend."""

    result: StepResult
    steps: tuple[FollowOnStep, ...] = ()
    groups: tuple[NarrationGroup, ...] = ()
    stopped_on: Optional[FollowOn] = None
    board_changed: bool = False
    drawn: tuple[tuple[str, ...], ...] = ()

    @property
    def ran(self) -> bool:
        return bool(self.steps)


def advance(
    engine: "RulesEngine",
    game: "CodexGame",
    match: MatchState,
    result: StepResult,
    *,
    stop_after: Iterable[FollowOnStep] = (),
    own_message: Iterable[FollowOnStep] = (),
) -> DriverRun:
    """
    Run the chain `result` starts until only somebody's answer can carry
    on. The narration is carried into each next step as its lead-in;
    `own_message` closes a group after a step instead, and `stop_after`
    stops the run after one -- both the frontend's to name.
    """
    stops = frozenset(stop_after)
    alone = frozenset(own_message)
    groups: list[NarrationGroup] = []
    narration = list(result.narration)
    headlines = result.headlines
    board_changed = result.board_changed
    drawn = [tuple(order) for order in result.drawn]
    last = result
    following = result.next
    stopped_on: Optional[FollowOn] = None
    steps: list[FollowOnStep] = []

    while isinstance(following, FollowOn) and following.step in MODEL_STEPS:
        step = following
        ran = MODEL_STEPS[step.step](
            engine, game, match, lead_in=" ".join(narration), **dict(step.kwargs),
        )
        steps.append(step.step)
        narration = list(ran.narration)
        headlines = (*headlines, *ran.headlines)
        board_changed = board_changed or ran.board_changed
        drawn.extend(tuple(order) for order in ran.drawn)
        last = ran
        following = ran.next
        if step.step in stops or ran.new_play:
            stopped_on = step
            break
        if step.step in alone:
            groups.append(NarrationGroup(tuple(narration), step.step, step.kwargs, headlines))
            narration = []
            headlines = ()

    if isinstance(following, PendingPrompt):
        following = with_options(engine, game, match, following)

    return DriverRun(
        result=StepResult(
            narration=narration,
            board_changed=last.board_changed if stopped_on is not None else board_changed,
            next=following,
            new_play=last.new_play if stopped_on is not None else False,
            headlines=headlines,
        ),
        steps=tuple(steps),
        groups=tuple(groups),
        stopped_on=stopped_on,
        board_changed=board_changed,
        drawn=tuple(drawn),
    )


@dataclass(frozen=True)
class Refusal:
    """
    Why an action was not applied, in a sentence a frontend can show.
    `waiting_on` is what the match is actually waiting on, and `cite`
    the rulebook page or card the refusal names, where its
    `RuleRefusal` named one.
    """

    reason: str
    waiting_on: Optional[PendingPrompt]
    cite: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "reason": self.reason,
            "waiting_on": None if self.waiting_on is None else self.waiting_on.to_dict(),
            "cite": self.cite,
        }


#: What a click on a prompt the position has moved on from is told.
STALE_CLICK: Mapping[PromptKind, str] = {
    PromptKind.MAIN_ACTION: "That main phase has moved on.",
    PromptKind.CHOOSE_DEFENDER: "That attack has already been settled.",
    PromptKind.PATROL: "The patrollers have already been locked.",
    PromptKind.TECH_CHOICE: "That tech choice is no longer open.",
    PromptKind.TECH_CONFIRM: "That tech choice has already been confirmed.",
    PromptKind.GAME_OVER: "The game is not over.",
}
MOVED_ON = "That answers a question this match has moved on from."
STEP_OWED = (
    "Nothing is being asked yet: the game still has a step of its own "
    "to run here."
)


# -- The answers -------------------------------------------------------------


def _answer_main(engine, game, match, prompt, choice, *, slug=None, levels=None,
                 building=None, attacker=None) -> StepResult:
    if choice == "hire":
        return actions.hire_worker(engine, game, match, _required(slug, "slug"))
    if choice == "summon":
        return actions.summon_hero(engine, game, match)
    if choice == "level":
        return actions.level_hero(engine, game, match, 1 if levels is None else levels)
    if choice == "play":
        return actions.play_card(engine, game, match, _required(slug, "slug"))
    if choice == "build":
        return actions.construct(engine, game, match, _required(building, "building"))
    if choice == "attack":
        return actions.declare_attacker(engine, game, match, _required(attacker, "attacker"))
    return actions.end_main(engine, game, match)


def _answer_defender(engine, game, match, prompt, choice, *, defender=None) -> StepResult:
    if choice == "cancel":
        return actions.cancel_attack(engine, game, match)
    return combat.declare_attack(engine, game, match, match.attacking, _required(defender, "defender"))


def _answer_patrol(engine, game, match, prompt, choice, *, assignment=None) -> StepResult:
    return actions.lock_patrol(engine, game, match, assignment)


def _answer_tech_choice(engine, game, match, prompt, choice, *, player=None, picks=None) -> StepResult:
    """
    The picks, replacing any made before (decision 8). Checked against
    the prompt's own options: the bounds, and the copies the codex still
    holds. Said as a count -- what was picked is the owner's secret.
    """
    options = prompt.options
    picks = list(picks or ())
    if not options.minimum <= len(picks) <= options.maximum:
        if options.minimum == options.maximum:
            wanted = f"exactly {options.maximum}"
        else:
            wanted = f"{options.minimum} to {options.maximum}"
        raise RuleRefusal(f"A tech choice is {wanted} cards.", cite="UMR p. 5")
    left = dict(options.codex)
    for slug in picks:
        if left.get(slug, 0) <= 0:
            raise RuleRefusal("Your codex has no more copies of that card.", cite="UMR p. 5")
        left[slug] -= 1
    owner = match.player(prompt.asked_player)
    first_time = owner.tech_choice is None
    owner.tech_choice = picks
    verb = "has chosen" if first_time else "has changed"
    return StepResult(
        narration=[f"{tokens.player(prompt.asked_player)} {verb} their tech."],
        next=pending(engine, game, match),
    )


def _answer_tech_confirm(engine, game, match, prompt, choice, *, player=None) -> StepResult:
    owner = match.player(prompt.asked_player)
    if choice == "change":
        owner.tech_choice = None
        return StepResult(next=pending(engine, game, match))
    owner.tech_confirmed = True
    return StepResult(next=pending(engine, game, match))


def _answer_game_over(engine, game, match, prompt, choice) -> StepResult:
    raise RuleRefusal("The game is over.")


#: Every `PromptKind`, answered. Covers the enum exactly.
ANSWERS: Mapping[PromptKind, Callable[..., StepResult]] = {
    PromptKind.MAIN_ACTION: _answer_main,
    PromptKind.CHOOSE_DEFENDER: _answer_defender,
    PromptKind.PATROL: _answer_patrol,
    PromptKind.TECH_CHOICE: _answer_tech_choice,
    PromptKind.TECH_CONFIRM: _answer_tech_confirm,
    PromptKind.GAME_OVER: _answer_game_over,
}

#: The arguments each kind's answer may take.
ARGUMENTS: Mapping[PromptKind, frozenset[str]] = {
    PromptKind.MAIN_ACTION: frozenset({"slug", "levels", "building", "attacker"}),
    PromptKind.CHOOSE_DEFENDER: frozenset({"defender"}),
    PromptKind.PATROL: frozenset({"assignment"}),
    PromptKind.TECH_CHOICE: frozenset({"player", "picks"}),
    PromptKind.TECH_CONFIRM: frozenset({"player"}),
    PromptKind.GAME_OVER: frozenset(),
}

#: The kinds whose action names the seat answering, since either player
#: may have one open.
SEATED_KINDS = frozenset({PromptKind.TECH_CHOICE, PromptKind.TECH_CONFIRM})


def _required(value, name: str):
    if value is None:
        raise RuleRefusal(f"That answer needs a {name}.")
    return value


def _find_prompt(engine, game, match, action: Action) -> Union[PendingPrompt, Refusal]:
    waiting = pending(engine, game, match)
    if isinstance(waiting, FollowOn):
        return Refusal(STEP_OWED, waiting_on=None)
    open_prompts = [waiting, *standing_prompts(engine, match, game)]
    if action.kind in SEATED_KINDS:
        seat = action.arguments.get("player")
        for prompt in open_prompts:
            if prompt.kind is action.kind and prompt.asked_player == seat:
                return prompt
        return Refusal(STALE_CLICK.get(action.kind, MOVED_ON), waiting_on=waiting)
    if waiting.kind is not action.kind:
        return Refusal(STALE_CLICK.get(action.kind, MOVED_ON), waiting_on=waiting)
    return waiting


@dataclass(frozen=True)
class Answered:
    """What one answer did, before anything that follows it has run."""

    result: StepResult


def answer(engine: "RulesEngine", game: "CodexGame", match: MatchState,
           action: Action) -> Union[Answered, Refusal]:
    """
    Answer the question this match is waiting on -- the active player's,
    or a standing tech choice -- and nothing after it. Refused while the
    bot owes a step, for a question not asked, for an answer the kind
    does not offer, for an argument it does not take, and wherever the
    position says no (`RuleRefusal`, the one exception caught).
    """
    found = _find_prompt(engine, game, match, action)
    if isinstance(found, Refusal):
        return found
    if action.choice not in CHOICES[action.kind]:
        return Refusal("That is not one of the answers this question offers.", waiting_on=found)
    unexpected = set(action.arguments) - ARGUMENTS[action.kind]
    if unexpected:
        return Refusal(
            "That answer does not take " + ", ".join(sorted(unexpected)) + ".",
            waiting_on=found,
        )
    try:
        result = ANSWERS[action.kind](
            engine, game, match, found, action.choice, **dict(action.arguments),
        )
    except RuleRefusal as refused:
        return Refusal(str(refused), waiting_on=found, cite=refused.cite)
    return Answered(result=result)


def apply(
    engine: "RulesEngine",
    game: "CodexGame",
    match: MatchState,
    action: Action,
    outcomes: Optional[Sequence[Sequence[str]]] = None,
) -> Union[DriverRun, Refusal]:
    """
    `answer` plus `advance`: a whole action in one call, and the one
    door the journal is written at. `outcomes` are recorded shuffle
    orders to hand back instead of drawing -- a replay's
    (`codex.history.replay`).
    """
    engine.replaying = [list(order) for order in (outcomes or ())]
    marker = history.latest_snapshot(match)
    try:
        answered = answer(engine, game, match, action)
        if isinstance(answered, Refusal):
            return answered
        run = advance(engine, game, match, answered.result)
    finally:
        engine.replaying = []
    if history.latest_snapshot(match) is marker:
        history.record(match, action, run.drawn)
    return run
