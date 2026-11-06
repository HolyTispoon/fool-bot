"""
The loop and the answers: `MODEL_STEPS` runs every `FollowOnStep`,
`advance` runs a chain until a prompt, and `answer`/`apply` take an
action, refuse it while the bot owes a step, check it against the
pending prompt and the position, and run it.

Copied from `codex/flow/driver.py`, whose docstrings say why each piece
is the shape it is (docs/design/model-discord-split.md,
docs/design/game-service.md). **`apply` is the one door** every click
goes through. It does not persist and it does not authorise: whose
Discord account may press a button is the frontend's question, and the
save is the service's (step 4 of docs/tnp-bot.md). There is no journal
yet: undo is later (docs/tnp-bot.md, decision 10).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Iterable, Mapping, Optional, Union

from gamekit.driver import MOVED_ON, STEP_OWED  # noqa: F401 -- re-exported
from tnp.flow import battle as fight
from tnp.flow.result import FollowOn, FollowOnStep, Roll, StepResult
from tnp.game import RuleRefusal
from tnp.prompts import CHOICES, Action, PendingPrompt, PromptKind, pending

if TYPE_CHECKING:
    from tnp.components import MatchState
    from tnp.engine import RulesEngine

__all__ = [
    "ANSWERS", "ARGUMENTS", "Action", "DriverRun", "MODEL_STEPS", "NarrationGroup",
    "Refusal", "advance", "answer", "apply", "resume",
]


#: Every `FollowOnStep`, run. `tests/test_tnp_battle.py` holds it to the
#: enum exactly.
MODEL_STEPS: Mapping[FollowOnStep, Callable[..., StepResult]] = {
    FollowOnStep.BEGIN_ROUND: fight.begin_round,
    FollowOnStep.CLOSE_GROUP: fight.close_group,
    FollowOnStep.END_ROUND: fight.end_round,
}


@dataclass(frozen=True)
class NarrationGroup:
    """Lines that belong together, and the step that said them -- the
    unit a frontend renders."""

    narration: tuple[str, ...]
    step: Optional[FollowOnStep] = None
    rolls: tuple[Roll, ...] = ()

    def to_dict(self) -> dict:
        return {
            "narration": list(self.narration),
            "step": None if self.step is None else self.step.name,
            "rolls": [roll.to_dict() for roll in self.rolls],
        }


@dataclass(frozen=True)
class DriverRun:
    """What one turn of the loop did, and where it stopped."""

    result: StepResult
    steps: tuple[FollowOnStep, ...] = ()
    groups: tuple[NarrationGroup, ...] = ()
    stopped_on: Optional[FollowOn] = None
    board_changed: bool = False

    @property
    def ran(self) -> bool:
        return bool(self.steps)

    @property
    def rolls(self) -> tuple[Roll, ...]:
        """Every roll along the run, in the order rolled."""
        found = [roll for group in self.groups for roll in group.rolls]
        return (*found, *self.result.rolls)

    @property
    def narration(self) -> tuple[str, ...]:
        """Every line along the run, in the order said."""
        found = [line for group in self.groups for line in group.narration]
        return (*found, *self.result.narration)


def advance(
    engine: "RulesEngine",
    game,
    match: "MatchState",
    result: StepResult,
    *,
    stop_after: Iterable[FollowOnStep] = (),
    own_message: Iterable[FollowOnStep] = (),
) -> DriverRun:
    """
    Run the chain `result` starts until only somebody's answer can carry
    on. The narration is carried into each next step as its lead-in;
    `own_message` closes a group after a step instead, and `stop_after`
    stops the run after one -- both the frontend's to name (step 7 names
    the round's end, so each round is its own edit).
    """
    stops = frozenset(stop_after)
    alone = frozenset(own_message)
    groups: list[NarrationGroup] = []
    narration = list(result.narration)
    rolls = list(result.rolls)
    board_changed = result.board_changed
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
        rolls.extend(ran.rolls)
        board_changed = board_changed or ran.board_changed
        last = ran
        following = ran.next
        if step.step in stops:
            stopped_on = step
            break
        if step.step in alone:
            groups.append(NarrationGroup(tuple(narration), step.step, tuple(rolls)))
            narration, rolls = [], []

    return DriverRun(
        result=StepResult(
            narration=narration,
            board_changed=last.board_changed if stopped_on is not None else board_changed,
            next=following,
            rolls=rolls,
        ),
        steps=tuple(steps),
        groups=tuple(groups),
        stopped_on=stopped_on,
        board_changed=board_changed,
    )


@dataclass(frozen=True)
class Refusal:
    """Why an action was not applied, in a sentence a frontend can show;
    `waiting_on` is what the match is actually waiting on, and `cite` the
    section of the rules that says no, where one does."""

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
    PromptKind.CHOOSE_ROLE: "The sides have already been chosen.",
    PromptKind.EMERGENCY_DEFENSE: "The emergency defense has already been decided.",
    PromptKind.PLACE_FORCE: "That placing has moved on.",
    PromptKind.DECLARE_RETREAT: "That retreat has already been declared or not.",
    PromptKind.CHOOSE_TARGET: "That roll has moved on.",
    PromptKind.REPAIR: "That repair has already been settled.",
    PromptKind.SPLASH: "That splash has already been settled.",
    PromptKind.DESTROY: "What the base card's hits destroy has already been chosen.",
}


def _required(value, name: str):
    if value is None:
        raise RuleRefusal(f"That answer needs a {name}.")
    return value


def _answer_role(engine, game, match, prompt, choice) -> StepResult:
    return fight.answer_role(engine, match, choice)


def _answer_emergency(engine, game, match, prompt, choice, *, units=None, trade=None) -> StepResult:
    return fight.answer_emergency(engine, match, choice, units=units, trade=trade)


def _answer_place(engine, game, match, prompt, choice, *, force=None, slot=None) -> StepResult:
    return fight.answer_place(engine, match, _required(force, "force"), _required(slot, "slot"))


def _answer_retreat(engine, game, match, prompt, choice, *, carried=None) -> StepResult:
    return fight.answer_retreat(engine, match, choice, carried=carried)


def _answer_target(engine, game, match, prompt, choice, *, force=None, target=None) -> StepResult:
    return fight.answer_target(engine, match, _required(force, "force"), _required(target, "target"))


def _answer_repair(engine, game, match, prompt, choice, *, workers=None) -> StepResult:
    return fight.answer_repair(engine, match, choice, workers=workers)


def _answer_splash(engine, game, match, prompt, choice, *, force=None) -> StepResult:
    return fight.answer_splash(engine, match, choice, force=force)


def _answer_destroy(engine, game, match, prompt, choice, *, thing=None) -> StepResult:
    return fight.answer_destroy(engine, match, _required(thing, "thing"))


#: Every `PromptKind`, answered. Covers the enum exactly.
ANSWERS: Mapping[PromptKind, Callable[..., StepResult]] = {
    PromptKind.CHOOSE_ROLE: _answer_role,
    PromptKind.EMERGENCY_DEFENSE: _answer_emergency,
    PromptKind.PLACE_FORCE: _answer_place,
    PromptKind.DECLARE_RETREAT: _answer_retreat,
    PromptKind.CHOOSE_TARGET: _answer_target,
    PromptKind.REPAIR: _answer_repair,
    PromptKind.SPLASH: _answer_splash,
    PromptKind.DESTROY: _answer_destroy,
}

#: The arguments each kind's answer may take.
ARGUMENTS: Mapping[PromptKind, frozenset[str]] = {
    PromptKind.CHOOSE_ROLE: frozenset(),
    PromptKind.EMERGENCY_DEFENSE: frozenset({"units", "trade"}),
    PromptKind.PLACE_FORCE: frozenset({"force", "slot"}),
    PromptKind.DECLARE_RETREAT: frozenset({"carried"}),
    PromptKind.CHOOSE_TARGET: frozenset({"force", "target"}),
    PromptKind.REPAIR: frozenset({"workers"}),
    PromptKind.SPLASH: frozenset({"force"}),
    PromptKind.DESTROY: frozenset({"thing"}),
}


def answer(engine: "RulesEngine", game, match: "MatchState",
           action: Action) -> Union[StepResult, Refusal]:
    """
    Answer the question this match is waiting on, and nothing after it.
    Refused while the bot owes a step, for a question not asked, for an
    answer the kind does not offer, for an argument it does not take, and
    wherever the position says no (`RuleRefusal`, the one exception
    caught).
    """
    waiting = pending(engine, game, match)
    if isinstance(waiting, FollowOn):
        return Refusal(STEP_OWED, waiting_on=None)
    if waiting is None or waiting.kind is not action.kind:
        return Refusal(STALE_CLICK.get(action.kind, MOVED_ON), waiting_on=waiting)
    if action.choice not in CHOICES[action.kind]:
        return Refusal("That is not one of the answers this question offers.", waiting_on=waiting)
    unexpected = set(action.arguments) - ARGUMENTS[action.kind]
    if unexpected:
        return Refusal(
            "That answer does not take " + ", ".join(sorted(unexpected)) + ".",
            waiting_on=waiting,
        )
    before = match.battle.to_dict()
    try:
        return ANSWERS[action.kind](engine, game, match, waiting, action.choice, **dict(action.arguments))
    except RuleRefusal as refused:
        # A refusal changes nothing, even where it was found part-way.
        from tnp.battle import BattleState

        match.battle = BattleState.from_dict(before)
        return Refusal(str(refused), waiting_on=waiting, cite=refused.cite)


def apply(
    engine: "RulesEngine",
    game,
    match: "MatchState",
    action: Action,
    *,
    stop_after: Iterable[FollowOnStep] = (),
    own_message: Iterable[FollowOnStep] = (),
) -> Union[DriverRun, Refusal]:
    """`answer` plus `advance`: a whole action in one call, the one door."""
    answered = answer(engine, game, match, action)
    if isinstance(answered, Refusal):
        return answered
    return advance(
        engine, game, match, answered, stop_after=stop_after, own_message=own_message,
    )


def resume(engine: "RulesEngine", game, match: "MatchState",
           *, own_message: Iterable[FollowOnStep] = ()) -> Optional[DriverRun]:
    """Run the step the bot owes, where it owes one -- after a restart
    that came between two of its own steps, or after a `stop_after`.
    `None` where somebody is asked or nothing is."""
    waiting = pending(engine, game, match)
    if not isinstance(waiting, FollowOn):
        return None
    return advance(engine, game, match, StepResult(next=waiting), own_message=own_message)
