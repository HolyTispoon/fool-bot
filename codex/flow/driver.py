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

from codex import history, seats
from codex.components import MatchState
from codex.flow import actions, board, combat, resolve, turn
from codex.flow.result import FollowOn, FollowOnStep, Headline, StepResult
from codex.game import RuleRefusal
from gamekit.driver import MOVED_ON, STEP_OWED  # noqa: F401 -- re-exported
from codex.prompts import (
    CHOICES,
    Action,
    PendingPrompt,
    PromptKind,
    asked_options,
    pending,
    pending_all,
    standing_prompts,
    tech_stands,
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
    #: The position where the group closed (`history.position`), for a step the
    #: frontend named in `draw_after`; `None` everywhere else. Never on
    #: the wire: a save holds every hand.
    board: Optional[dict] = None

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
    #: Whether a card left the top of a deck anywhere along the run
    #: (`StepResult.drew`).
    drew: bool = False

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
    draw_after: Iterable[FollowOnStep] = (),
) -> DriverRun:
    """
    Run the chain `result` starts until only somebody's answer can carry
    on. The narration is carried into each next step as its lead-in;
    `own_message` closes a group after a step instead, and `stop_after`
    stops the run after one -- both the frontend's to name.

    `draw_after` closes a group after a step too, and hands the group
    the position as it stood there, without stopping: Codex's answer to
    "a picture of a position is a stop" where an action may not be
    stopped part-way (`apply`). The Discord frontend names the end of
    the turn, so the turn's last board is the turn's and not the next
    one's ready phase (docs/design/codex.md, "The turn message").
    """
    stops = frozenset(stop_after)
    drawn_after = frozenset(draw_after)
    alone = frozenset(own_message) | drawn_after
    groups: list[NarrationGroup] = []
    narration = list(result.narration)
    headlines = result.headlines
    board_changed = result.board_changed
    drawn = [tuple(order) for order in result.drawn]
    drew = result.drew
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
        drew = drew or ran.drew
        last = ran
        following = ran.next
        if step.step in stops or ran.new_play:
            stopped_on = step
            break
        if step.step in alone:
            board = history.position(match) if step.step in drawn_after else None
            groups.append(NarrationGroup(
                tuple(narration), step.step, step.kwargs, headlines, board=board,
            ))
            narration = []
            headlines = ()

    if isinstance(following, PendingPrompt):
        # Read with the asked seat active: in a dragon the teammate who
        # just acted is still `match.active` until `apply` settles the
        # head (`settle_active`), and their options are not the asked
        # seat's (the review of 2026-10-15).
        following = asked_options(engine, game, match, following)

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
        drew=drew,
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
    PromptKind.OBLITERATE_CHOICE: "That obliterate has already been settled.",
    PromptKind.SPARKSHOT_TARGET: "That sparkshot has already been settled.",
    PromptKind.OVERPOWER_TARGET: "That overpower has already been settled.",
    PromptKind.TARGET: "That target has already been chosen.",
    PromptKind.APPEL_STOMP_TOP: "Appel Stomp has already gone where it goes.",
    PromptKind.UPKEEP_ORDER: "That upkeep has already been done.",
    PromptKind.LEVEL_GAIN: "Those levels have already been gained.",
    PromptKind.DIVIDE_DAMAGE: "That damage has already been divided.",
    PromptKind.MODE_CHOICE: "That choice has already been made.",
    PromptKind.STASH: "That draw has already been made.",
    PromptKind.CHOOSE_NUMBER: "That number has already been chosen.",
    PromptKind.OATH: "That oath has already been sworn.",
    PromptKind.GAME_OVER: "The game is not over.",
}


# -- The answers -------------------------------------------------------------


def _answer_main(engine, game, match, prompt, choice, *, slug=None, levels=None,
                 building=None, attacker=None, card=None, ability=None,
                 source=None, hero=None, spec=None, lab_spec=None, boost=None,
                 against=None) -> StepResult:
    if choice == "hire":
        return actions.hire_worker(engine, game, match, _required(slug, "slug"))
    if choice == "summon":
        return actions.summon_hero(engine, game, match, hero)
    if choice == "level":
        return actions.level_hero(engine, game, match, 1 if levels is None else levels, hero)
    if choice == "play":
        return actions.play_card(engine, game, match, _required(slug, "slug"), bool(boost))
    if choice == "build":
        return actions.construct(
            engine, game, match, _required(building, "building"), spec, lab_spec,
        )
    if choice == "attack":
        return actions.declare_attacker(engine, game, match, _required(attacker, "attacker"))
    if choice == "detect":
        return actions.detect(engine, game, match, _required(card, "card"), against)
    if choice == "ability":
        return actions.use_ability(
            engine, game, match, _required(ability, "ability"), _required(source, "source"),
        )
    if choice == "repair":
        return actions.repair_base(engine, game, match)
    return actions.end_main(engine, game, match)


def _answer_defender(engine, game, match, prompt, choice, *, defender=None, against=None) -> StepResult:
    if choice == "cancel":
        return actions.cancel_attack(engine, game, match)
    defender = _required(defender, "defender")
    if against is None:
        # The click names a ref; the seat is the one the options offer it on.
        offered = prompt.options
        seats = {seat for ref, seat in zip(offered.defenders, offered.seats) if ref == defender}
        if len(seats) > 1:
            raise RuleRefusal("Choose whose forces to attack: that is on more than one side.")
        against = next(iter(seats), None)
    return combat.declare_attack(engine, game, match, match.attacking, defender, against)


def _answer_patrol(engine, game, match, prompt, choice, *, assignment=None, lent=None) -> StepResult:
    return actions.lock_patrol(engine, game, match, assignment, lent)


def _answer_tech_choice(engine, game, match, prompt, choice, *, player=None, picks=None) -> StepResult:
    """
    The picks, replacing any made before (decision 8). Checked against
    the prompt's own options: the bounds, and the copies the codex still
    holds. **Nothing is said**: what was picked is the owner's secret,
    and that they picked is announced in their own ready phase, as the
    count of cards `begin_turn` puts into the discard.
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
    owner.tech_choice = picks
    if owner.seat in engine.turn_seats(match) or not tech_stands(game):
        # A choice made in its owner's own ready phase -- they never
        # picked during the other's turn, or pressed Change, or it is a
        # test game's (`codex.prompts.tech_stands`) -- was made just now,
        # so there is nothing earlier to review: no confirmation is
        # asked, even for none, and the turn begins on the pick (the
        # author, 2026-10-10).
        owner.tech_confirmed = True
        return _settled_in_main(engine, game, match, owner.seat)
    # Said nothing: a tech choice is announced only in its owner's ready
    # phase, as the count of cards into the discard (the author,
    # 2026-10-08) -- not while the other player's turn is going on.
    return StepResult(next=pending(engine, game, match))


def _settled_in_main(engine, game, match, seat: int) -> StepResult:
    """A tech choice confirmed: where the main phase is already open --
    an undo to the turn's start asked it again -- its picks go into the
    discard pile now, as the ready phase would have put them; otherwise
    the ready phase does, once the bot runs it."""
    result = StepResult()
    if match.phase == "main" and seat in engine.turn_seats(match):
        turn.settle_tech(match, seat, result)
        result.board_changed = True
    result.next = pending(engine, game, match)
    return result


def _answer_tech_confirm(engine, game, match, prompt, choice, *, player=None) -> StepResult:
    owner = match.player(prompt.asked_player)
    if choice == "change":
        owner.tech_choice = None
        return StepResult(next=pending(engine, game, match))
    owner.tech_confirmed = True
    return _settled_in_main(engine, game, match, owner.seat)


def _answer_obliterate(engine, game, match, prompt, choice, *, unit=None) -> StepResult:
    return combat.choose_obliterate(engine, game, match, _required(unit, "unit"))


def _answer_sparkshot(engine, game, match, prompt, choice, *, patroller=None) -> StepResult:
    return combat.choose_sparkshot(engine, game, match, _required(patroller, "patroller"))


def _answer_overpower(engine, game, match, prompt, choice, *, target=None) -> StepResult:
    return combat.choose_overpower(engine, game, match, _required(target, "target"))


def _answer_target(engine, game, match, prompt, choice, *, target=None) -> StepResult:
    if choice == "cancel":
        return resolve.cancel(engine, game, match)
    if choice == "done":
        return resolve.done_choosing(engine, game, match)
    return resolve.choose_target(engine, game, match, _required(target, "target"))


def _answer_divide(engine, game, match, prompt, choice, *, target=None) -> StepResult:
    if choice == "cancel":
        return resolve.cancel(engine, game, match)
    return resolve.add_to_split(engine, game, match, _required(target, "target"))


def _answer_mode(engine, game, match, prompt, choice, *, mode=None) -> StepResult:
    if choice == "cancel":
        return resolve.cancel(engine, game, match)
    return resolve.choose_mode(engine, game, match, _required(mode, "mode"))


def _answer_appel(engine, game, match, prompt, choice) -> StepResult:
    return resolve.appel_stomp_top(engine, game, match, choice == "top")


def _answer_upkeep_order(engine, game, match, prompt, choice, *, first=None) -> StepResult:
    return turn.finish_upkeep(engine, game, match, _required(first, "first"))


def _answer_level_gain(engine, game, match, prompt, choice, *, hero=None, seat=None) -> StepResult:
    """Which hero gains the kill's two levels (Rulebook p. 11), then the
    stack goes on from where the kill stood. `seat` names whose hero
    where a ref alone is on more than one side (a mirror game)."""
    offered = list(zip(prompt.options.seats or (None,) * len(prompt.options.heroes),
                       prompt.options.heroes))
    matching = [on for on, ref in offered if ref == hero and seat in (None, on)]
    if not matching:
        raise RuleRefusal("Choose one of their heroes in play to gain the levels.", cite="Rulebook p. 11")
    if seat is None and len(set(matching)) > 1:
        raise RuleRefusal("Choose whose hero gains the levels: that hero is on more than one side.")
    top = match.resolving.pop(0)
    result = StepResult(board_changed=True)
    # Either spelling of the ref: a hero lent to the holder is named
    # `<owner seat>:hero:<slug>` on their side (`hero_on`).
    gaining = next(
        found for on in ([seat] if seat is not None else top.get("seats") or [top["seat"]])
        for found in (match.hero_on(on, hero),) if found is not None
    )
    board.gain_kill_levels(engine, match, gaining, result)
    return resolve.carry_on(engine, game, match, result)


def _answer_stash(engine, game, match, prompt, choice, *, slug=None) -> StepResult:
    """Stash's card, or none, and the draw it changes (step 13)."""
    if match.dragons:
        # Both teammates' draws run together once each has answered
        # (`codex.flow.turn.draw_phase`).
        keeping = ""
        if choice != "none":
            keeping = _required(slug, "slug")
            if keeping not in prompt.options.hand:
                raise RuleRefusal("That card is not in your hand.", cite="bigby_hayes")
        match.player(prompt.asked_player).stash_choice = keeping
        return StepResult(next=pending(engine, game, match))
    if choice == "none":
        return turn.draw_phase(engine, game, match, stash="")
    slug = _required(slug, "slug")
    if slug not in prompt.options.hand:
        raise RuleRefusal("That card is not in your hand.", cite="bigby_hayes")
    return turn.draw_phase(engine, game, match, stash=slug)


def _answer_number(engine, game, match, prompt, choice, *, number=None) -> StepResult:
    return resolve.choose_number(engine, game, match, _required(number, "number"))


def _answer_oath(engine, game, match, prompt, choice, *, oath=None) -> StepResult:
    return resolve.choose_oath(engine, game, match, _required(oath, "oath"))


def _answer_game_over(engine, game, match, prompt, choice) -> StepResult:
    raise RuleRefusal("The game is over.")


#: Every `PromptKind`, answered. Covers the enum exactly.
ANSWERS: Mapping[PromptKind, Callable[..., StepResult]] = {
    PromptKind.MAIN_ACTION: _answer_main,
    PromptKind.CHOOSE_DEFENDER: _answer_defender,
    PromptKind.PATROL: _answer_patrol,
    PromptKind.TECH_CHOICE: _answer_tech_choice,
    PromptKind.TECH_CONFIRM: _answer_tech_confirm,
    PromptKind.OBLITERATE_CHOICE: _answer_obliterate,
    PromptKind.SPARKSHOT_TARGET: _answer_sparkshot,
    PromptKind.OVERPOWER_TARGET: _answer_overpower,
    PromptKind.TARGET: _answer_target,
    PromptKind.APPEL_STOMP_TOP: _answer_appel,
    PromptKind.UPKEEP_ORDER: _answer_upkeep_order,
    PromptKind.LEVEL_GAIN: _answer_level_gain,
    PromptKind.DIVIDE_DAMAGE: _answer_divide,
    PromptKind.MODE_CHOICE: _answer_mode,
    PromptKind.STASH: _answer_stash,
    PromptKind.CHOOSE_NUMBER: _answer_number,
    PromptKind.OATH: _answer_oath,
    PromptKind.GAME_OVER: _answer_game_over,
}

#: The arguments each kind's answer may take.
ARGUMENTS: Mapping[PromptKind, frozenset[str]] = {
    PromptKind.MAIN_ACTION: frozenset({
        "slug", "levels", "building", "attacker", "card", "ability", "source", "hero",
        "spec", "lab_spec", "boost", "against",
    }),
    PromptKind.CHOOSE_DEFENDER: frozenset({"defender", "against"}),
    PromptKind.PATROL: frozenset({"assignment", "lent"}),
    PromptKind.TECH_CHOICE: frozenset({"player", "picks"}),
    PromptKind.TECH_CONFIRM: frozenset({"player"}),
    PromptKind.OBLITERATE_CHOICE: frozenset({"unit"}),
    PromptKind.SPARKSHOT_TARGET: frozenset({"patroller"}),
    PromptKind.OVERPOWER_TARGET: frozenset({"target"}),
    PromptKind.TARGET: frozenset({"target"}),
    PromptKind.APPEL_STOMP_TOP: frozenset(),
    PromptKind.UPKEEP_ORDER: frozenset({"first"}),
    PromptKind.LEVEL_GAIN: frozenset({"hero", "seat"}),
    PromptKind.DIVIDE_DAMAGE: frozenset({"target"}),
    PromptKind.MODE_CHOICE: frozenset({"mode"}),
    PromptKind.STASH: frozenset({"slug"}),
    PromptKind.CHOOSE_NUMBER: frozenset({"number"}),
    PromptKind.OATH: frozenset({"oath"}),
    PromptKind.GAME_OVER: frozenset(),
}

#: The kinds whose action names the seat answering, since either player
#: may have one open.
SEATED_KINDS = frozenset({PromptKind.TECH_CHOICE, PromptKind.TECH_CONFIRM})

#: **In a two-headed dragon every action names its seat** (decision 8):
#: both teammates may have a prompt of one kind open, and the driver
#: finds the one the action's `player` is asked. The driver fills it in
#: where it is left out, so a journal always holds it; a duel's and a
#: free-for-all's journal never does, which is why those are the bytes
#: they always were.
ARGUMENTS = {kind: names | {"player"} for kind, names in ARGUMENTS.items()}


def _required(value, name: str):
    if value is None:
        raise RuleRefusal(f"That answer needs a {name}.")
    return value


def _find_team_prompt(engine, game, match, action: Action) -> Union[PendingPrompt, Refusal]:
    """`_find_prompt` for a two-headed dragon: the team has one prompt
    per acting seat, and the action's `player` names which it answers
    (older journals have none and are read as the active seat's)."""
    from codex import tokens

    owed = pending_all(engine, game, match)
    if any(isinstance(one, FollowOn) for one in owed):
        return Refusal(STEP_OWED, waiting_on=None)
    open_prompts = [*owed, *standing_prompts(engine, match, game)]
    seat = action.arguments.get("player")
    found = [one for one in open_prompts if one.kind is action.kind]
    if seat is not None:
        found = [one for one in found if one.asked_player == seat]
    if len(found) > 1:
        found = [one for one in found if one.asked_player == seats.head_of(match)] or found[:1]
    if found:
        return found[0]
    first = owed[0]
    if seat is not None and len(owed) == 1 and first.asked_player not in (None, seat) \
            and first.asked_player in engine.turn_seats(match) and seat in engine.turn_seats(match):
        what = "attack" if match.attacking is not None or match.combat is not None else "action"
        return Refusal(
            f"Waiting on {tokens.player(first.asked_player)}'s {what}.", waiting_on=first,
        )
    return Refusal(STALE_CLICK.get(action.kind, MOVED_ON), waiting_on=first)


def _find_prompt(engine, game, match, action: Action) -> Union[PendingPrompt, Refusal]:
    if match.dragons:
        return _find_team_prompt(engine, game, match, action)
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


def _upgrade_refs(match: MatchState, action: Action) -> Action:
    """
    An action from a journal older than step 10 names a hero `hero`
    alone -- its side's one hero -- where it attacks, defends, patrols
    or is targeted; read as `hero:<slug>`, the side's first, so a replay
    of such a turn (a cancel's) finds the hero the engine now names.
    """
    from codex.components import HERO, hero_ref

    active = match.active
    others = seats.opponents(match, active)
    if len(others) != 1:
        # Only a duel's journal is older than step 10: a table of several
        # never named a hero `hero` alone.
        return action
    other = others[0]

    def mine(seat: int, value):
        if value == HERO:
            return hero_ref(match.player(seat).heroes[0].slug)
        if isinstance(value, str) and value[:1].isdigit() and value[1:2] == ":" and value[2:] == HERO:
            return f"{value[0]}:{hero_ref(match.player(int(value[0])).heroes[0].slug)}"
        return value

    sides = {
        "attacker": active, "source": active, "defender": other, "card": other,
        "unit": other, "patroller": other, "target": other,
    }
    arguments = dict(action.arguments)
    changed = False
    for name, seat in sides.items():
        if name in arguments and mine(seat, arguments[name]) != arguments[name]:
            arguments[name] = mine(seat, arguments[name])
            changed = True
    if isinstance(arguments.get("assignment"), Mapping):
        assignment = {slot: mine(active, ref) for slot, ref in arguments["assignment"].items()}
        if assignment != arguments["assignment"]:
            arguments["assignment"] = assignment
            changed = True
    if not changed:
        return action
    return Action(action.kind, action.choice, arguments)


@dataclass(frozen=True)
class Answered:
    """What one answer did, before anything that follows it has run.
    `action` is the action as journalled: in a dragon with the seat that
    answered named."""

    result: StepResult
    action: Optional[Action] = None


def answer(engine: "RulesEngine", game: "CodexGame", match: MatchState,
           action: Action) -> Union[Answered, Refusal]:
    """
    Answer the question this match is waiting on -- the active player's,
    or a standing tech choice -- and nothing after it. Refused while the
    bot owes a step, for a question not asked, for an answer the kind
    does not offer, for an argument it does not take, and wherever the
    position says no (`RuleRefusal`, the one exception caught).
    """
    action = _upgrade_refs(match, action)
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
    arguments = dict(action.arguments)
    before = match.active
    if match.dragons:
        # Journalled with the seat that answered, and run with that seat
        # active: every reading below is made on their behalf.
        if found.asked_player is not None:
            arguments["player"] = found.asked_player
            action = Action(action.kind, action.choice, dict(arguments))
        if found.asked_player in engine.turn_seats(match):
            match.active = found.asked_player
    if action.kind not in SEATED_KINDS:
        arguments.pop("player", None)
    try:
        result = ANSWERS[action.kind](engine, game, match, found, action.choice, **arguments)
    except RuleRefusal as refused:
        match.active = before
        return Refusal(str(refused), waiting_on=found, cite=refused.cite)
    return Answered(result=result, action=action)


def settle_active(match: MatchState) -> None:
    """
    Between a dragon's actions the active seat is the team's head again:
    `match.active` is whichever teammate is acting only while that
    teammate's action stands part-way (an attack, an effect's choice, an
    upkeep), and the turn is handed over from the head
    (`codex.seats.next_seat`). A duel's and a free-for-all's is left
    alone.
    """
    from codex.prompts import _half_resolved

    if match.dragons and match.winner is None and not _half_resolved(match):
        match.active = seats.head_of(match)


def apply(
    engine: "RulesEngine",
    game: "CodexGame",
    match: MatchState,
    action: Action,
    outcomes: Optional[Sequence[Sequence[str]]] = None,
    *,
    own_message: Iterable[FollowOnStep] = (),
    draw_after: Iterable[FollowOnStep] = (),
) -> Union[DriverRun, Refusal]:
    """
    `answer` plus `advance`: a whole action in one call, and the one
    door the journal is written at. `outcomes` are recorded shuffle
    orders to hand back instead of drawing -- a replay's
    (`codex.history.replay`). `own_message` is `advance`'s, the
    frontend's batching, and `draw_after` with it; there is no
    `stop_after`, since a stop would cut what the journal records as
    one action in two.
    """
    engine.replaying = [list(order) for order in (outcomes or ())]
    marker = history.latest_snapshot(match)
    try:
        answered = answer(engine, game, match, action)
        if isinstance(answered, Refusal):
            return answered
        run = advance(
            engine, game, match, answered.result,
            own_message=own_message, draw_after=draw_after,
        )
        action = answered.action
        settle_active(match)
    finally:
        engine.replaying = []
    # A cancel is not recorded: it put the journal back to before the
    # cast it took back (`codex.flow.resolve.cancel`), and a replay of it
    # would have nothing to cancel.
    cancelled = action.choice == "cancel" and action.kind in (
        PromptKind.TARGET, PromptKind.DIVIDE_DAMAGE, PromptKind.MODE_CHOICE,
    )
    if history.latest_snapshot(match) is marker and not cancelled:
        history.record(match, action, run.drawn)
    return run
