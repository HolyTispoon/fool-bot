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
only once the picks are confirmed. **In a test game nothing stands**
(`tech_stands`): one person plays both sides, and their tech is chosen
in each side's own ready phase instead.

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
from codex import effects
from codex.engine import (
    AbilityOption,
    BuildOption,
    DetectOption,
    HeroOption,
    HireOption,
    PlayableCard,
    TargetRow,
)
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
    #: Obliterate X, before combat: which of the defending player's
    #: equally low-tech units it takes (UMR p. 17) -- asked only on a tie.
    OBLITERATE_CHOICE = "obliterate_choice"
    #: Sparkshot: which patroller beside the one attacked takes its 1
    #: damage (UMR p. 18) -- asked only where both neighbours are filled.
    SPARKSHOT_TARGET = "sparkshot_target"
    #: Overpower: where the excess over the patroller attacked goes
    #: (UMR p. 17) -- asked only where more than one thing could take it.
    OVERPOWER_TARGET = "overpower_target"
    #: What a part of a spell, a trigger or an ability chooses -- asked
    #: part by part as it resolves, and only where there is more than
    #: one thing it could choose (`codex.flow.resolve`).
    TARGET = "target"
    #: Appel Stomp, resolved: on top of the draw pile, or the discard.
    APPEL_STOMP_TOP = "appel_stomp_top"
    #: The upkeep's order, where it changes what happens -- healing and
    #: Star-Crossed Starlet's damage both due (Starlet's ruling).
    UPKEEP_ORDER = "upkeep_order"
    #: Which hero gains a kill's two levels, where the side that made
    #: the kill has more than one in play (UMR p. 10) -- asked of the
    #: active player where the kill happened, before anything after it
    #: resolves.
    LEVEL_GAIN = "level_gain"
    #: Damage divided as the caster chooses among the targets a part
    #: chose (Ember Sparks, Burning Volley): 1 each, and a point at a time
    #: onto one of them until it is all placed (step 11).
    DIVIDE_DAMAGE = "divide_damage"
    #: "Choose one" -- Feral Strike's, Murkwood Allies', Land Octopus's
    #: upkeep -- asked only where there is a choice (step 11).
    MODE_CHOICE = "mode_choice"
    #: A base is destroyed (UMR p. 2), or a player conceded.
    GAME_OVER = "game_over"


# -- What each kind offers ---------------------------------------------


@dataclass(frozen=True)
class MainActionOptions:
    """The engine's `legal_actions`, as the prompt carries them."""

    hire: HireOption
    #: One per hero of the team, in its order: summon or level, or why
    #: not (`RulesEngine.hero_options`).
    heroes: tuple[HeroOption, ...]
    playable: tuple[PlayableCard, ...]
    buildings: tuple[BuildOption, ...]
    attackers: tuple[str, ...]
    end_main: bool = True
    #: The tower's detection on its owner's own turn (UMR p. 9).
    detect: DetectOption = DetectOption()
    #: The hand card by card in its order, duplicates kept, each with
    #: its cost and why it may not be played (`hand_rows`): what the
    #: panel's picture numbers, and what a hire may trash.
    hand: tuple[PlayableCard, ...] = ()
    #: The ability actions the player's cards offer (`abilities`).
    abilities: tuple[AbilityOption, ...] = ()

    def to_dict(self) -> dict:
        return jsonable({
            "hire": self.hire, "heroes": self.heroes, "playable": self.playable,
            "buildings": self.buildings, "attackers": self.attackers,
            "end_main": self.end_main, "detect": self.detect, "hand": self.hand,
            "abilities": self.abilities,
        })


@dataclass(frozen=True)
class DefenderOptions:
    attacker: str
    defenders: tuple[str, ...]
    #: Why each of `defenders` is legal, in the same order: "squad
    #: leader", "patroller", "nothing is patrolling" (`defender_rows`).
    why: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "attacker": self.attacker, "defenders": list(self.defenders),
            "why": list(self.why),
        }


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
class ObliterateOptions:
    """The defending player's equally low-tech units, and how many
    obliterate has left to take."""

    attacker: str
    units: tuple[str, ...]
    left: int = 1

    def to_dict(self) -> dict:
        return {"attacker": self.attacker, "units": list(self.units), "left": self.left}


@dataclass(frozen=True)
class SparkshotOptions:
    """The two neighbours, how many instances of sparkshot are still to
    place (each asked on its own), and where the placed ones went."""

    attacker: str
    defender: str
    patrollers: tuple[str, ...]
    left: int = 1
    placed: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "attacker": self.attacker, "defender": self.defender,
            "patrollers": list(self.patrollers), "left": self.left,
            "placed": list(self.placed),
        }


@dataclass(frozen=True)
class OverpowerOptions:
    """Where the excess may go, and how much it is."""

    attacker: str
    defender: str
    excess: int
    targets: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "attacker": self.attacker, "defender": self.defender,
            "excess": self.excess, "targets": list(self.targets),
        }


@dataclass(frozen=True)
class TargetOptions:
    """
    What the part being resolved may choose: `effect` and `part` name it
    (`codex.effects.EFFECTS`), `source` is the card or hero whose text it
    is, `says` the part in words, and `targets` the rows -- each with the
    resist choosing it costs, and, where the flagbearer rule narrowed
    the list to the opposing flagbearers, `forced`.
    """

    seat: int
    effect: str
    source: str
    part: int
    says: str
    targets: tuple[TargetRow, ...]
    forced: bool = False
    #: Whether `cancel` is offered: a spell or ability, before it has
    #: drawn a card (`codex.flow.resolve.cancellable`).
    cancellable: bool = False
    #: Whether **Done** is offered: the part chooses "up to" so many, or
    #: "may", and has chosen as many as it must (step 11).
    done: bool = False
    #: What the part has chosen so far, as target keys.
    picked: tuple[str, ...] = ()
    #: Cards shown to the asked player alone beside the choice, by slug
    #: (step 12): Carrion Curse's whole look at an opponent's hand, of
    #: which only the non-units may be chosen. Empty for every other part.
    shown: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        found = jsonable({
            "seat": self.seat, "effect": self.effect, "source": self.source,
            "part": self.part, "says": self.says, "targets": self.targets,
            "forced": self.forced, "cancellable": self.cancellable,
        })
        if self.done or self.picked:
            found["done"] = self.done
            found["picked"] = list(self.picked)
        if self.shown:
            found["shown"] = list(self.shown)
        return found


@dataclass(frozen=True)
class DivideOptions:
    """Damage being divided: the targets chosen, how much each has so far
    (1 each to begin with), the total, and how much is left to place."""

    seat: int
    effect: str
    source: str
    total: int
    split: tuple[tuple[str, int], ...]
    cancellable: bool = False

    @property
    def left(self) -> int:
        return self.total - sum(amount for _, amount in self.split)

    def to_dict(self) -> dict:
        return {
            "seat": self.seat, "effect": self.effect, "source": self.source,
            "total": self.total, "split": [list(row) for row in self.split],
            "left": self.left, "cancellable": self.cancellable,
        }


@dataclass(frozen=True)
class ModeOptions:
    """The modes of a "choose one", each `(key, says)`, the ones that can
    be done alone."""

    seat: int
    effect: str
    source: str
    modes: tuple[tuple[str, str], ...]
    cancellable: bool = False

    def to_dict(self) -> dict:
        return {
            "seat": self.seat, "effect": self.effect, "source": self.source,
            "modes": [list(row) for row in self.modes], "cancellable": self.cancellable,
        }


@dataclass(frozen=True)
class AppelOptions:
    seat: int
    answers: tuple[str, ...] = ("top", "discard")

    def to_dict(self) -> dict:
        return {"seat": self.seat, "answers": list(self.answers)}


@dataclass(frozen=True)
class UpkeepOrderOptions:
    """The upkeep effects whose order is the player's: which goes first."""

    seat: int
    effects: tuple[str, ...] = ("healing", "starlet")

    def to_dict(self) -> dict:
        return {"seat": self.seat, "effects": list(self.effects)}


@dataclass(frozen=True)
class LevelGainOptions:
    """Which of `owner`'s heroes in play gains the kill's two levels --
    `heroes` as refs, `hero:<slug>`. `seat` is the active player, who
    is asked."""

    seat: int
    owner: int
    heroes: tuple[str, ...]

    def to_dict(self) -> dict:
        return {"seat": self.seat, "owner": self.owner, "heroes": list(self.heroes)}


@dataclass(frozen=True)
class GameOverOptions:
    """Who won, and who conceded where the game ended that way. Nothing
    answers a finished game: playing it again is a new record
    (`GameService.rematch`), not an answer to this one."""

    winner: int
    conceded: Optional[int] = None
    #: The seat that could not pay Promise of Payment's debt (step 12).
    lost_by_debt: Optional[int] = None

    def to_dict(self) -> dict:
        found = {"winner": self.winner, "conceded": self.conceded}
        if self.lost_by_debt is not None:
            found["lost_by_debt"] = self.lost_by_debt
        return found


PromptOptions = Union[
    MainActionOptions, DefenderOptions, PatrolOptions, TechOptions,
    TechConfirmOptions, ObliterateOptions, SparkshotOptions, OverpowerOptions,
    TargetOptions, AppelOptions, UpkeepOrderOptions, LevelGainOptions, GameOverOptions,
    DivideOptions, ModeOptions,
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
        "hire", "summon", "level", "play", "build", "attack", "detect", "ability",
        "end_main",
    ),
    PromptKind.CHOOSE_DEFENDER: ("", "cancel"),
    PromptKind.PATROL: ("",),
    PromptKind.TECH_CHOICE: ("",),
    PromptKind.TECH_CONFIRM: ("confirm", "change"),
    PromptKind.OBLITERATE_CHOICE: ("",),
    PromptKind.SPARKSHOT_TARGET: ("",),
    PromptKind.OVERPOWER_TARGET: ("",),
    PromptKind.TARGET: ("", "cancel", "done"),
    PromptKind.APPEL_STOMP_TOP: ("top", "discard"),
    PromptKind.UPKEEP_ORDER: ("",),
    PromptKind.LEVEL_GAIN: ("",),
    PromptKind.DIVIDE_DAMAGE: ("", "cancel"),
    PromptKind.MODE_CHOICE: ("", "cancel"),
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


def _obliterate_ask(seat: int) -> str:
    return (
        f"{tokens.player(seat)}, obliterate takes their lowest-tech units: "
        "choose which one goes."
    )


def _sparkshot_ask(seat: int) -> str:
    return f"{tokens.player(seat)}, choose which patroller sparkshot hits."


def _overpower_ask(seat: int) -> str:
    return f"{tokens.player(seat)}, choose where overpower's excess goes."


def _target_ask(engine, match: MatchState, top: dict) -> str:
    part = effects.EFFECTS[top["effect"]].parts[top["part"]]
    ask = f"{tokens.player(top['seat'])}, {top['by']}: {part.says}."
    from codex.flow.resolve import rows_for

    if any(row.flagbearer for row in rows_for(engine, match, top)):
        ask += " Their flagbearer must be the target."
    return ask


def _divide_ask(match: MatchState, top: dict, left: int) -> str:
    return (
        f"{tokens.player(top['seat'])}, {top['by']}: divide its damage -- "
        f"{left} more to place, a point at a time."
    )


def _mode_ask(top: dict) -> str:
    return f"{tokens.player(top['seat'])}, {top['by']}: choose one."


def _appel_ask(seat: int) -> str:
    return (
        f"{tokens.player(seat)}, put {tokens.card(effects.APPEL_STOMP)} on top of your "
        "draw pile, or into your discard pile?"
    )


def _upkeep_ask(seat: int, effects_due=("healing", "starlet")) -> str:
    if tuple(effects_due) == ("healing", "starlet") or set(effects_due) == {"healing", "starlet"}:
        return (
            f"{tokens.player(seat)}, your upkeep: heal first, or "
            f"{tokens.card('starcrossed_starlet')} takes her damage first?"
        )
    return f"{tokens.player(seat)}, your upkeep: which of its effects goes next?"


def _level_ask(seat: int, owner: int) -> str:
    whose = "your" if seat == owner else f"{tokens.player(owner)}'s"
    return f"{tokens.player(seat)}, a hero was destroyed: choose which of {whose} heroes gains the 2 levels."


def _confirm_ask(seat: int) -> str:
    return f"{tokens.player(seat)}, your turn: confirm your tech choice, or change it."


#: The stage an attack waits at, as the prompt that asks it
#: (`codex.flow.combat`). A stage with nothing to choose never waits.
COMBAT_PROMPTS = {
    "obliterate": (PromptKind.OBLITERATE_CHOICE, _obliterate_ask),
    "sparkshot": (PromptKind.SPARKSHOT_TARGET, _sparkshot_ask),
    "overpower": (PromptKind.OVERPOWER_TARGET, _overpower_ask),
}


# -- The options -------------------------------------------------------------


def _main_options(engine, game, match, prompt) -> MainActionOptions:
    legal = engine.legal_actions(match)
    return MainActionOptions(
        legal.hire, legal.heroes, legal.playable, legal.buildings, legal.attackers,
        legal.end_main, legal.detect, engine.hand_rows(match, match.active),
        legal.abilities,
    )


def _target_options(engine, game, match, prompt) -> TargetOptions:
    from codex.flow.resolve import cancellable, offers_done, rows_for

    top = match.resolving[0]
    part = effects.EFFECTS[top["effect"]].parts[top["part"]]
    rows = rows_for(engine, match, top)
    shown: tuple[str, ...] = ()
    if part.choose in LOOKS:
        # Carrion Curse: "Look at an opponent's hand" -- all of it, to the
        # caster alone.
        other = 2 if top["seat"] == 1 else 1
        shown = tuple(match.player(other).hand)
    return TargetOptions(
        top["seat"], top["effect"], top["by"], top["part"], part.says, rows,
        any(row.flagbearer for row in rows), cancellable(match),
        offers_done(top, part), tuple(top.get("picks") or ()), shown,
    )


#: The parts that look at a hidden pile while they choose from it.
LOOKS = frozenset({"opponent_hand_nonunit"})


def _divide_options(engine, game, match, prompt) -> DivideOptions:
    from codex.flow.resolve import cancellable, current_part, damage_amount

    top = match.resolving[0]
    part = current_part(match)
    return DivideOptions(
        top["seat"], top["effect"], top["by"], damage_amount(engine, match, top, part.amount),
        tuple((key, amount) for key, amount in top["split"].items()), cancellable(match),
    )


def _mode_options(engine, game, match, prompt) -> ModeOptions:
    from codex.flow.resolve import cancellable, current_part

    top = match.resolving[0]
    part = current_part(match)
    return ModeOptions(
        top["seat"], top["effect"], top["by"],
        tuple((key, says) for key, says, allowed in engine.mode_rows(match, top, part) if allowed),
        cancellable(match),
    )


def _appel_options(engine, game, match, prompt) -> AppelOptions:
    return AppelOptions(prompt.asked_player)


def _upkeep_options(engine, game, match, prompt) -> UpkeepOrderOptions:
    from codex.flow.turn import upkeep_asks

    return UpkeepOrderOptions(prompt.asked_player, tuple(upkeep_asks(match) or ()))


def _level_options(engine, game, match, prompt) -> LevelGainOptions:
    from codex.components import hero_ref

    top = match.resolving[0]
    owner = match.player(top["seat"])
    return LevelGainOptions(
        prompt.asked_player, owner.seat,
        tuple(hero_ref(hero.slug) for hero in owner.heroes_in_play),
    )


def _obliterate_options(engine, game, match, prompt) -> ObliterateOptions:
    state = match.combat
    return ObliterateOptions(
        state["attacker"], engine.obliterate_candidates(match), state["obliterate"],
    )


def _sparkshot_options(engine, game, match, prompt) -> SparkshotOptions:
    state = match.combat
    placed = tuple(state["sparks"])
    return SparkshotOptions(
        state["attacker"], state["defender"],
        engine.sparkshot_candidates(match, state["attacker"], state["defender"]),
        engine.sparkshot_count(match, state["attacker"]) - len(placed), placed,
    )


def _overpower_options(engine, game, match, prompt) -> OverpowerOptions:
    state = match.combat
    return OverpowerOptions(
        state["attacker"], state["defender"],
        engine.overpower_excess(match, state["attacker"], state["defender"]),
        engine.overpower_candidates(match, state["attacker"], state["defender"]),
    )


def _defender_options(engine, game, match, prompt) -> DefenderOptions:
    rows = engine.defender_rows(match, match.attacking)
    return DefenderOptions(
        match.attacking, tuple(ref for ref, _ in rows), tuple(why for _, why in rows),
    )


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
    return GameOverOptions(match.winner, match.conceded, match.lost_by_debt)


OPTIONS = {
    PromptKind.MAIN_ACTION: _main_options,
    PromptKind.CHOOSE_DEFENDER: _defender_options,
    PromptKind.PATROL: _patrol_options,
    PromptKind.TECH_CHOICE: _tech_options,
    PromptKind.TECH_CONFIRM: _confirm_options,
    PromptKind.OBLITERATE_CHOICE: _obliterate_options,
    PromptKind.SPARKSHOT_TARGET: _sparkshot_options,
    PromptKind.OVERPOWER_TARGET: _overpower_options,
    PromptKind.TARGET: _target_options,
    PromptKind.APPEL_STOMP_TOP: _appel_options,
    PromptKind.UPKEEP_ORDER: _upkeep_options,
    PromptKind.LEVEL_GAIN: _level_options,
    PromptKind.DIVIDE_DAMAGE: _divide_options,
    PromptKind.MODE_CHOICE: _mode_options,
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


def tech_stands(game: "Optional[CodexGame]") -> bool:
    """
    Whether the tech choice stands open through the opponent's turn
    (decision 8), or waits for its owner's ready phase.

    **A test game's waits** (the author, 2026-10-09). One person plays
    both sides there, and a choice standing for the side whose turn it
    is not reached them beside the other side's: the Lock's follow-up
    was the side that had just ended its turn, My hand the side whose
    turn had begun -- two pickers in a row, with nothing to say whose
    was whose. So in a test game nothing stands: the picker is the
    pending prompt in its owner's ready phase, from their second turn
    on (nobody owes tech before their first turn has ended), and the
    pick made there is the choice, with no confirmation asked after it
    (`codex.flow.driver._answer_tech_choice`). With no record to read,
    the choice stands.
    """
    return game is None or not game.test_game


def _pending(engine, game, match: MatchState) -> Union[PendingPrompt, FollowOn]:
    if match.winner is not None:
        if match.conceded is not None:
            how = f"{tokens.player(match.conceded)} conceded."
        elif match.lost_by_debt is not None:
            how = f"{tokens.player(match.lost_by_debt)} could not pay their debt."
        else:
            how = "the opposing base is destroyed."
        return PendingPrompt(PromptKind.GAME_OVER, f"{tokens.player(match.winner)} wins: {how}")
    seat = match.active
    if match.resolving:
        # An effect under way asks before anything else does: a target,
        # Appel Stomp's place, the upkeep's order (`codex.flow.resolve`).
        top = match.resolving[0]
        kind = top.get("kind")
        if kind == "appel_top":
            return PendingPrompt(PromptKind.APPEL_STOMP_TOP, _appel_ask(top["seat"]), top["seat"])
        if kind == "upkeep_order":
            from codex.flow.turn import upkeep_asks

            return PendingPrompt(PromptKind.UPKEEP_ORDER,
                                 _upkeep_ask(top["seat"], upkeep_asks(match) or ()), top["seat"])
        if kind == "level_gain":
            asked = top.get("asked", seat)
            return PendingPrompt(PromptKind.LEVEL_GAIN, _level_ask(asked, top["seat"]), asked)
        from codex.flow.resolve import ASKS_DIVIDE, ASKS_MODE, asking, current_part, damage_amount

        asks = asking(match)
        if asks == ASKS_MODE:
            return PendingPrompt(PromptKind.MODE_CHOICE, _mode_ask(top), top["seat"])
        if asks == ASKS_DIVIDE:
            left = damage_amount(engine, match, top, current_part(match).amount) - sum(top["split"].values())
            return PendingPrompt(PromptKind.DIVIDE_DAMAGE, _divide_ask(match, top, left), top["seat"])
        return PendingPrompt(PromptKind.TARGET, _target_ask(engine, match, top), top["seat"])
    if match.phase == "ready":
        if tech_is_owed(match, seat):
            return tech_prompt(seat, match)
        return FollowOn(FollowOnStep.BEGIN_TURN)
    if match.phase == "main":
        if match.combat is not None and match.combat["stage"] in COMBAT_PROMPTS:
            kind, ask = COMBAT_PROMPTS[match.combat["stage"]]
            return PendingPrompt(kind, ask(seat), seat)
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
    their own turn begins (decision 8). Nothing once the game is over,
    and nothing in a test game (`tech_stands`).
    """
    if match.winner is not None or not tech_stands(game):
        return ()
    other = 2 if match.active == 1 else 1
    if not tech_is_owed(match, other):
        return ()
    prompt = PendingPrompt(PromptKind.TECH_CHOICE, _tech_ask(other), other)
    return (with_options(engine, game, match, prompt),)


def asked_player(prompt: PendingPrompt) -> Optional[int]:
    """Whose question a prompt is -- `None` for a finished game's."""
    return prompt.asked_player
