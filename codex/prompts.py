"""
`PromptKind`, `PendingPrompt`, `Action` and `pending` -- the one reading
of what a Codex match is waiting on, with no Discord in it.

D12 Ball's shape (`d12ball/prompts.py`; docs/design/model-discord-split.md):
`pending` answers a `PendingPrompt` where somebody is asked and a
`FollowOn` where the bot owes the next step, `pending_prompt` and
`owed_step` read one each, and **a prompt carries its `options`** -- what
may be chosen, one dataclass per kind built by the `OPTIONS` table off
the engine's answers -- which a view, a client and `driver.answer` all
read, so nothing computes a candidate list of its own.

**Codex's addition is the standing prompt** (docs/codex-bot.md,
decision 8). The tech choice is chosen secretly while the opponent
plays, so it is a second thing a match waits on: `pending` stays one
reading with one answer, the active player's, and `standing_prompts`
lists what the other player may answer meanwhile -- in this set only
`TECH_CHOICE`, answerable again and again until their turn begins, each
answer replacing the picks. Their turn then opens on `TECH_CONFIRM` (or
on `TECH_CHOICE` itself, if they never picked), and `begin_turn` runs
only once the picks are confirmed.

Every prompt names `asked_player`: the active player for every kind
but the tech choice and its confirmation, whose asked player is the
choice's owner, and nobody for a finished game. **What a prompt holds
is for its asked player's eyes** -- a tech prompt lists their codex --
and a frontend shows it to them alone.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import TYPE_CHECKING, Any, Mapping, Optional, Union

from codex import tokens
from codex.components import PATROL_SLOTS, MatchState
from codex.engine import BuildOption, HeroOption, HireOption, PlayableCard
from codex.flow.result import FollowOn, FollowOnStep
from codex.wire import jsonable

if TYPE_CHECKING:
    from codex.engine import RulesEngine
    from codex.game import CodexGame


class PromptKind(Enum):
    #: The main phase: hire, summon or level the hero, play a card,
    #: build, attack, or end the phase (UMR p. 6-11).
    MAIN_ACTION = "main_action"
    #: The attacker has been declared; which of the legal defenders it
    #: takes (UMR p. 10) -- asked after the attacker, so a misclick on
    #: the attacker costs nothing (decision 11).
    CHOOSE_DEFENDER = "choose_defender"
    #: The patrol lock that ends the main phase: what patrols which slot.
    PATROL = "patrol"
    #: The secret tech choice: two cards out of the codex, or none to two
    #: at ten workers (UMR p. 5).
    TECH_CHOICE = "tech_choice"
    #: The start of a turn: the picks shown to their owner, confirmed or
    #: changed, before the ready phase runs.
    TECH_CONFIRM = "tech_confirm"
    #: A base is destroyed (UMR p. 2).
    GAME_OVER = "game_over"


# -- What each kind offers ---------------------------------------------


@dataclass(frozen=True)
class MainActionOptions:
    """The engine's `legal_actions`, as the prompt carries them."""

    hire: HireOption
    hero: HeroOption
    playable: tuple[PlayableCard, ...]
    buildings: tuple[BuildOption, ...]
    attackers: tuple[str, ...]
    end_main: bool = True

    def to_dict(self) -> dict:
        return jsonable({
            "hire": self.hire, "hero": self.hero, "playable": self.playable,
            "buildings": self.buildings, "attackers": self.attackers,
            "end_main": self.end_main,
        })


@dataclass(frozen=True)
class DefenderOptions:
    attacker: str
    defenders: tuple[str, ...]

    def to_dict(self) -> dict:
        return {"attacker": self.attacker, "defenders": list(self.defenders)}


@dataclass(frozen=True)
class PatrolOptions:
    candidates: tuple[str, ...]
    slots: tuple[str, ...] = PATROL_SLOTS

    def to_dict(self) -> dict:
        return {"candidates": list(self.candidates), "slots": list(self.slots)}


@dataclass(frozen=True)
class TechOptions:
    """The owner's codex -- its slugs and the copies left of each -- the
    bounds of the choice, and the picks made so far."""

    seat: int
    codex: tuple[tuple[str, int], ...]
    minimum: int
    maximum: int
    picks: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "seat": self.seat,
            "codex": [list(row) for row in self.codex],
            "minimum": self.minimum,
            "maximum": self.maximum,
            "picks": list(self.picks),
        }


@dataclass(frozen=True)
class TechConfirmOptions:
    seat: int
    picks: tuple[str, ...]
    answers: tuple[str, ...] = ("confirm", "change")

    def to_dict(self) -> dict:
        return {"seat": self.seat, "picks": list(self.picks), "answers": list(self.answers)}


@dataclass(frozen=True)
class GameOverOptions:
    winner: int

    def to_dict(self) -> dict:
        return {"winner": self.winner}


PromptOptions = Union[
    MainActionOptions, DefenderOptions, PatrolOptions, TechOptions,
    TechConfirmOptions, GameOverOptions,
]


@dataclass(frozen=True)
class PendingPrompt:
    """The question, the line asking it, who is asked, and what may be
    chosen."""

    kind: PromptKind
    ask: str
    asked_player: Optional[int] = None
    options: Optional[PromptOptions] = None

    def to_dict(self) -> dict:
        return {
            "kind": self.kind.value,
            "ask": self.ask,
            "asked_player": self.asked_player,
            "options": None if self.options is None else self.options.to_dict(),
        }


@dataclass(frozen=True)
class Action:
    """
    What somebody did, named by the question it answers (`d12ball.prompts.Action`).
    `choice` is which of the prompt's answers it is (`CHOICES`), and
    `arguments` what the person chose: a slug, a ref, a slot assignment.
    The tech prompts carry `player`, the seat answering, because both
    players may have one open at once.
    """

    kind: PromptKind
    choice: str = ""
    arguments: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind.value,
            "choice": self.choice,
            "arguments": jsonable(dict(self.arguments)),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Action":
        """An action off the wire or out of the journal -- the one thing
        read back."""
        return cls(
            kind=PromptKind(data["kind"]),
            choice=data.get("choice") or "",
            arguments=dict(data.get("arguments") or {}),
        )


#: The answers each kind offers. A kind with one answer offers "".
CHOICES: Mapping[PromptKind, tuple[str, ...]] = {
    PromptKind.MAIN_ACTION: (
        "hire", "summon", "level", "play", "build", "attack", "end_main",
    ),
    PromptKind.CHOOSE_DEFENDER: ("", "cancel"),
    PromptKind.PATROL: ("",),
    PromptKind.TECH_CHOICE: ("",),
    PromptKind.TECH_CONFIRM: ("confirm", "change"),
    PromptKind.GAME_OVER: (),
}


# -- The asks --------------------------------------------------------------


def _main_ask(match: MatchState) -> str:
    player = match.active_player
    return (
        f"{tokens.player(match.active)}, your main phase: "
        f"{tokens.gold(player.gold)} and {player.workers} workers."
    )


def _tech_ask(seat: int) -> str:
    return f"{tokens.player(seat)}, choose your tech: the cards go to your discard pile when your next turn begins."


def _confirm_ask(seat: int) -> str:
    return f"{tokens.player(seat)}, your turn: confirm your tech choice, or change it."


# -- The options -------------------------------------------------------------


def _main_options(engine, game, match, prompt) -> MainActionOptions:
    legal = engine.legal_actions(match)
    return MainActionOptions(
        legal.hire, legal.hero, legal.playable, legal.buildings, legal.attackers,
        legal.end_main,
    )


def _defender_options(engine, game, match, prompt) -> DefenderOptions:
    return DefenderOptions(match.attacking, engine.legal_defenders(match, match.attacking))


def _patrol_options(engine, game, match, prompt) -> PatrolOptions:
    return PatrolOptions(engine.patrol_candidates(match))


def _tech_options(engine, game, match, prompt) -> TechOptions:
    player = match.player(prompt.asked_player)
    minimum, maximum = engine.tech_bounds(player)
    return TechOptions(
        prompt.asked_player, engine.codex_counts(player), minimum, maximum,
        tuple(player.tech_choice or ()),
    )


def _confirm_options(engine, game, match, prompt) -> TechConfirmOptions:
    player = match.player(prompt.asked_player)
    return TechConfirmOptions(prompt.asked_player, tuple(player.tech_choice or ()))


def _game_over_options(engine, game, match, prompt) -> GameOverOptions:
    return GameOverOptions(match.winner)


OPTIONS = {
    PromptKind.MAIN_ACTION: _main_options,
    PromptKind.CHOOSE_DEFENDER: _defender_options,
    PromptKind.PATROL: _patrol_options,
    PromptKind.TECH_CHOICE: _tech_options,
    PromptKind.TECH_CONFIRM: _confirm_options,
    PromptKind.GAME_OVER: _game_over_options,
}


def with_options(engine: "RulesEngine", game: "CodexGame", match: MatchState,
                 prompt: PendingPrompt) -> PendingPrompt:
    build = OPTIONS.get(prompt.kind)
    if build is None:
        return prompt
    return replace(prompt, options=build(engine, game, match, prompt))


# -- The one reading -------------------------------------------------------


def tech_prompt(seat: int, match: MatchState) -> PendingPrompt:
    """The tech prompt `seat` is owed: the confirmation once they have
    picked, the picker until then."""
    player = match.player(seat)
    if player.tech_choice is None:
        return PendingPrompt(PromptKind.TECH_CHOICE, _tech_ask(seat), seat)
    return PendingPrompt(PromptKind.TECH_CONFIRM, _confirm_ask(seat), seat)


def tech_is_owed(match: MatchState, seat: int) -> bool:
    """Whether `seat` still owes their tech choice its confirmation."""
    player = match.player(seat)
    return player.tech_owed and not player.tech_confirmed


def _pending(engine, game, match: MatchState) -> Union[PendingPrompt, FollowOn]:
    if match.winner is not None:
        return PendingPrompt(
            PromptKind.GAME_OVER,
            f"{tokens.player(match.winner)} wins: the opposing base is destroyed.",
        )
    seat = match.active
    if match.phase == "ready":
        if tech_is_owed(match, seat):
            return tech_prompt(seat, match)
        return FollowOn(FollowOnStep.BEGIN_TURN)
    if match.phase == "main":
        if match.attacking is not None:
            return PendingPrompt(
                PromptKind.CHOOSE_DEFENDER,
                f"{tokens.player(seat)}, choose what the attacker takes.",
                seat,
            )
        return PendingPrompt(PromptKind.MAIN_ACTION, _main_ask(match), seat)
    if match.phase == "patrol":
        return PendingPrompt(
            PromptKind.PATROL,
            f"{tokens.player(seat)}, lock your patrollers: the main phase ends.",
            seat,
        )
    if match.phase == "draw":
        return FollowOn(FollowOnStep.DRAW_PHASE)
    if match.phase == "tech":
        return FollowOn(FollowOnStep.BEGIN_TECH)
    # The upkeep is never stood on between two clicks: `begin_turn`
    # runs it through to the main phase in one step.
    return FollowOn(FollowOnStep.BEGIN_TURN)


def pending(engine: "RulesEngine", game: "CodexGame", match: MatchState) -> Union[PendingPrompt, FollowOn]:
    """What this match is waiting on: the active player's question, or
    the step the bot owes. Read through `pending_prompt` and `owed_step`."""
    waiting = _pending(engine, game, match)
    if isinstance(waiting, FollowOn):
        return waiting
    return with_options(engine, game, match, waiting)


def pending_prompt(engine, game, match) -> Optional[PendingPrompt]:
    waiting = pending(engine, game, match)
    return waiting if isinstance(waiting, PendingPrompt) else None


def owed_step(engine, game, match) -> Optional[FollowOn]:
    waiting = pending(engine, game, match)
    return waiting if isinstance(waiting, FollowOn) else None


def standing_prompts(engine: "RulesEngine", match: MatchState,
                     game: "Optional[CodexGame]" = None) -> tuple[PendingPrompt, ...]:
    """
    What the player who is not active may answer meanwhile: the tech
    choice they owe from the turn they just ended, open to change until
    their own turn begins (decision 8). Nothing once the game is over.
    """
    if match.winner is not None:
        return ()
    other = 2 if match.active == 1 else 1
    if not tech_is_owed(match, other):
        return ()
    prompt = PendingPrompt(PromptKind.TECH_CHOICE, _tech_ask(other), other)
    return (with_options(engine, game, match, prompt),)


def asked_player(prompt: PendingPrompt) -> Optional[int]:
    """Whose question a prompt is -- `None` for a finished game's."""
    return prompt.asked_player
