"""
`PromptKind`, `PendingPrompt`, `Action` and `pending` -- the one reading
of what a TNP match is waiting on, with no Discord in it.

Codex's shape (`codex/prompts.py`; docs/design/model-discord-split.md):
`pending` answers a `PendingPrompt` where somebody is asked and a
`FollowOn` where the bot owes the next step, `pending_prompt` and
`owed_step` read one each, and **a prompt carries its `options`** --
every legal choice, one dataclass per kind built by the `OPTIONS` table
off `tnp.battle`'s readings -- which a view and `driver.answer` both
read, so nothing computes a candidate list of its own.

Step 2 asks only a battle's questions (TNP 6), each of one seat at a
time: `asked_seat` is the seat asked. Step 4 adds the turn's, two of
which ask both seats at once (docs/tnp-bot.md, decision 7). A battle's
units are revealed (TNP 6.1) and a seat's pool is open information
(TNP 2.2), so nothing a battle prompt carries is hidden.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields, replace
from enum import Enum
from typing import TYPE_CHECKING, Any, Mapping, Optional, Union

from tnp import tokens
from tnp.battle import (
    DAMAGE,
    EMERGENCY,
    LOSSES,
    PLACE,
    REPOSITION,
    RETREAT,
    ROLE,
    ROUND,
    ROUND_END,
    BattleState,
    aimed,
    carriable,
    carriers,
    destroyable,
    dice,
    emergency_cap,
    emergency_limits,
    modifier,
    repair_workers,
    reposition_asker,
    retreat_asker,
    roller,
    rollers,
    scouting_advantage,
    slots,
    splash_targets,
    target_type,
    unplaced,
)
from tnp.catalog import UnitType
from tnp.flow.result import FollowOn, FollowOnStep
from tnp.wire import jsonable

if TYPE_CHECKING:
    from tnp.components import MatchState
    from tnp.engine import RulesEngine


class PromptKind(Enum):
    #: Both seats attacked a neutral territory and one has the scouting
    #: advantage: it chooses to attack or defend (TNP 6.1).
    CHOOSE_ROLE = "choose_role"
    #: The defender of a base may produce base defenses from its pool at
    #: the emergency rates (TNP 6.2).
    EMERGENCY_DEFENSE = "emergency_defense"
    #: A round after the first: keep the flanking forces where they
    #: stand, or take some out to be placed again (TNP 6.5).
    REPOSITION_FLANKERS = "reposition_flankers"
    #: One unengaged force into the line (TNP 6.5).
    PLACE_FORCE = "place_force"
    #: Retreat or fight on: the attacker first, then the defender (TNP 6.6).
    DECLARE_RETREAT = "declare_retreat"
    #: A force's target, which rolls its dice (TNP 6.7, decision 8).
    CHOOSE_TARGET = "choose_target"
    #: Workers given to ignore hits on a Mechanical force (TNP 6.8).
    REPAIR = "repair"
    #: Splash: an infantry unit taken from a force beside the one hit
    #: (TNP 6.8).
    SPLASH = "splash"
    #: What a base card's hits destroy (TNP 6.9).
    DESTROY = "destroy"


class _Wire:
    """`to_dict` for an options dataclass: its fields, through `jsonable`."""

    def to_dict(self) -> dict:
        return {item.name: jsonable(getattr(self, item.name)) for item in fields(self)}


# -- What each kind offers -------------------------------------------------------


@dataclass(frozen=True)
class RoleOptions(_Wire):
    seat: str
    advantage: int


@dataclass(frozen=True)
class EmergencyUnit(_Wire):
    unit: str
    materials: int
    gold: int
    #: The most of it that may be produced: its supply room, within the
    #: cap, and none of a Laser Cannon without its upgrade.
    most: int


@dataclass(frozen=True)
class TogetherLimit(_Wire):
    units: tuple[str, ...]
    room: int


@dataclass(frozen=True)
class EmergencyOptions(_Wire):
    #: The pool: materials, gold, blue and orange minerals, gems.
    pool: Mapping[str, int]
    #: The emergency rates (TNP 6.2): `{"mineral": {"materials", "gold"}, "gem": ...}`.
    rates: Mapping[str, Mapping[str, Optional[int]]]
    cap: int
    units: tuple[EmergencyUnit, ...]
    together: tuple[TogetherLimit, ...]
    #: What an action's `trade` may name.
    trades: tuple[str, ...] = ("blue", "orange", "gems_materials", "gems_gold")


@dataclass(frozen=True)
class FlankerOption(_Wire):
    force: str
    unit: str
    count: int
    #: The force it stands behind.
    behind: str


@dataclass(frozen=True)
class RepositionOptions(_Wire):
    seat: str
    #: Its flanking forces, any of which an action's `forces` may name.
    flankers: tuple[FlankerOption, ...]


@dataclass(frozen=True)
class PlaceForce(_Wire):
    force: str
    unit: str
    count: int
    damaged: int
    #: Where it may go (`tnp.battle.slots`): `engage:<column>`,
    #: `column:<gap>`, `flank:<column>`.
    slots: tuple[str, ...]


@dataclass(frozen=True)
class PlaceOptions(_Wire):
    seat: str
    forces: tuple[PlaceForce, ...]
    #: How many forces this seat places before the other places one.
    run: int
    columns: int


@dataclass(frozen=True)
class CarryOption(_Wire):
    """A ground force the Chopper Carriers may take out, and how many of
    it one carrier holds (TNP 7)."""

    force: str
    unit: str
    count: int
    per_carrier: int


@dataclass(frozen=True)
class RetreatOptions(_Wire):
    seat: str
    round: int
    #: With a path home every unit retreats (TNP 6.6), and nothing below
    #: is offered.
    path_home: bool = True
    #: With none: the air forces, which go; the carriers, and what they
    #: may carry -- an action's `carried`, force to count, one kind of
    #: unit a carrier.
    air: tuple[str, ...] = ()
    carriers: int = 0
    carry: tuple[CarryOption, ...] = ()


@dataclass(frozen=True)
class TargetOption(_Wire):
    target: str
    #: What it is attacked as: infantry, armored or air -- armored for a
    #: base card (TNP 6.9).
    type: str
    dice: int
    #: Every modifier on each die (TNP 4.2).
    modifier: int
    #: The number a die must reach before its modifier (TNP 4.1).
    needed: int


@dataclass(frozen=True)
class ShooterOption(_Wire):
    force: str
    unit: str
    count: int
    targets: tuple[TargetOption, ...]


@dataclass(frozen=True)
class TargetOptions(_Wire):
    seat: str
    group: int
    forces: tuple[ShooterOption, ...]


@dataclass(frozen=True)
class WorkerOption(_Wire):
    force: str
    available: int


@dataclass(frozen=True)
class RepairOptions(_Wire):
    force: str
    hits: int
    workers: tuple[WorkerOption, ...]


@dataclass(frozen=True)
class SplashOptions(_Wire):
    by: str
    hit: str
    forces: tuple[str, ...]


@dataclass(frozen=True)
class DestroyOptions(_Wire):
    things: tuple[str, ...]


PromptOptions = Union[
    RoleOptions, EmergencyOptions, RepositionOptions, PlaceOptions, RetreatOptions, TargetOptions,
    RepairOptions, SplashOptions, DestroyOptions,
]


@dataclass(frozen=True)
class PendingPrompt:
    """The question, the line asking it, the seat asked, and what may be
    chosen."""

    kind: PromptKind
    ask: str
    asked_seat: Optional[str] = None
    options: Optional[PromptOptions] = None

    def to_dict(self) -> dict:
        return {
            "kind": self.kind.value,
            "ask": self.ask,
            "asked_seat": self.asked_seat,
            "options": None if self.options is None else self.options.to_dict(),
        }


@dataclass(frozen=True)
class Action:
    """
    What somebody did, named by the question it answers (`codex.prompts.Action`):
    `choice` is which of the prompt's answers (`CHOICES`), `arguments`
    what was chosen -- a force, a slot, a target.
    """

    kind: PromptKind
    choice: str = ""
    arguments: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"kind": self.kind.value, "choice": self.choice, "arguments": jsonable(dict(self.arguments))}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Action":
        """An action off the wire -- the one thing read back."""
        return cls(
            kind=PromptKind(data["kind"]),
            choice=data.get("choice") or "",
            arguments=dict(data.get("arguments") or {}),
        )


#: The answers each kind offers. A kind with one answer offers "".
CHOICES: Mapping[PromptKind, tuple[str, ...]] = {
    PromptKind.CHOOSE_ROLE: ("attack", "defend"),
    PromptKind.EMERGENCY_DEFENSE: ("build", "none"),
    PromptKind.REPOSITION_FLANKERS: ("keep", "move"),
    PromptKind.PLACE_FORCE: ("",),
    PromptKind.DECLARE_RETREAT: ("retreat", "fight"),
    PromptKind.CHOOSE_TARGET: ("",),
    PromptKind.REPAIR: ("repair", "decline"),
    PromptKind.SPLASH: ("splash", "decline"),
    PromptKind.DESTROY: ("",),
}


# -- The options ---------------------------------------------------------------


def _role_options(engine, battle: BattleState, prompt) -> RoleOptions:
    advantage = scouting_advantage(engine, battle)
    return RoleOptions(advantage["seat"], advantage["by"])


def _emergency_options(engine, battle: BattleState, prompt) -> EmergencyOptions:
    most, together = emergency_limits(engine, battle)
    pool = (battle.emergency or {}).get("pool", {})
    return EmergencyOptions(
        pool={key: int(pool.get(key, 0)) for key in ("materials", "gold", "blue", "orange", "gems")},
        rates=engine.catalog.board["conversion"]["emergency"],
        cap=emergency_cap(engine, battle),
        units=tuple(
            EmergencyUnit(slug, engine.unit(slug).cost.materials, engine.unit(slug).cost.gold, count)
            for slug, count in most.items()
        ),
        together=tuple(TogetherLimit(units, room) for units, room in together),
    )


def _reposition_options(engine, battle: BattleState, prompt) -> RepositionOptions:
    seat = prompt.asked_seat
    found = []
    for column in battle.line:
        for one in column.flankers(seat):
            force = battle.force(one)
            found.append(FlankerOption(one, force.unit, force.count, column.front[seat]))
    return RepositionOptions(seat, tuple(found))


def _place_options(engine, battle: BattleState, prompt) -> PlaceOptions:
    seat = prompt.asked_seat
    return PlaceOptions(
        seat=seat,
        forces=tuple(
            PlaceForce(found.id, found.unit, found.count, found.damaged,
                       slots(engine, battle, seat, found))
            for found in unplaced(battle, seat)
        ),
        run=battle.run_left,
        columns=len(battle.line),
    )


def _retreat_options(engine, battle: BattleState, prompt) -> RetreatOptions:
    seat = prompt.asked_seat
    if battle.paths_home.get(seat, False):
        return RetreatOptions(seat, battle.round)
    room = carriable(engine, battle, seat)
    return RetreatOptions(
        seat, battle.round, path_home=False,
        air=tuple(
            found.id for found in battle.living(seat)
            if engine.unit(found.unit).type is UnitType.AIR
        ),
        carriers=sum(carriers(engine, battle, seat).values()),
        carry=tuple(
            CarryOption(ident, battle.force(ident).unit, battle.force(ident).count, per)
            for ident, per in room.items()
        ),
    )


def _target_options(engine, battle: BattleState, prompt) -> TargetOptions:
    seat = prompt.asked_seat
    shooters = []
    for ident in rollers(engine, battle, seat):
        found = battle.force(ident)
        offered = []
        for target in aimed(engine, battle, ident):
            against = target_type(engine, battle, target)
            offered.append(TargetOption(
                target, against.value, dice(engine, battle, ident, target),
                modifier(engine, battle, ident, target),
                engine.rating(found.unit, against).target,
            ))
        shooters.append(ShooterOption(ident, found.unit, found.count, tuple(offered)))
    return TargetOptions(seat, battle.group, tuple(shooters))


def _repair_options(engine, battle: BattleState, prompt) -> RepairOptions:
    owed = battle.owed[0]
    return RepairOptions(
        owed["force"], battle.hits.get(owed["force"], 0),
        tuple(WorkerOption(one, left) for one, left in repair_workers(engine, battle, owed["force"])),
    )


def _splash_options(engine, battle: BattleState, prompt) -> SplashOptions:
    owed = battle.owed[0]
    return SplashOptions(owed["force"], owed["hit"], splash_targets(engine, battle, owed["hit"]))


def _destroy_options(engine, battle: BattleState, prompt) -> DestroyOptions:
    return DestroyOptions(destroyable(engine, battle))


OPTIONS = {
    PromptKind.CHOOSE_ROLE: _role_options,
    PromptKind.EMERGENCY_DEFENSE: _emergency_options,
    PromptKind.REPOSITION_FLANKERS: _reposition_options,
    PromptKind.PLACE_FORCE: _place_options,
    PromptKind.DECLARE_RETREAT: _retreat_options,
    PromptKind.CHOOSE_TARGET: _target_options,
    PromptKind.REPAIR: _repair_options,
    PromptKind.SPLASH: _splash_options,
    PromptKind.DESTROY: _destroy_options,
}


def with_options(engine: "RulesEngine", battle: BattleState, prompt: PendingPrompt) -> PendingPrompt:
    return replace(prompt, options=OPTIONS[prompt.kind](engine, battle, prompt))


# -- The asks --------------------------------------------------------------------


def _owed_prompt(battle: BattleState) -> PendingPrompt:
    owed = battle.owed[0]
    seat = owed["seat"]
    if owed["kind"] == "destroy":
        return PendingPrompt(
            PromptKind.DESTROY,
            f"{tokens.seat(seat)}, the base card is hit twice: choose what is destroyed.", seat,
        )
    if owed["kind"] == "splash":
        return PendingPrompt(
            PromptKind.SPLASH,
            f"{tokens.seat(seat)}, splash: take an infantry unit from a force beside the one hit?",
            seat,
        )
    return PendingPrompt(
        PromptKind.REPAIR,
        f"{tokens.seat(seat)}, give Workers beside your {tokens.unit(battle.force(owed['force']).unit)} "
        "to ignore their hits?",
        seat,
    )


#: The phases where the bot owes a step, and which.
OWED_STEPS = {
    ROUND: FollowOnStep.BEGIN_ROUND,
    LOSSES: FollowOnStep.CLOSE_GROUP,
    ROUND_END: FollowOnStep.END_ROUND,
}


def _pending(engine: "RulesEngine", battle: BattleState) -> Union[PendingPrompt, FollowOn, None]:
    if battle.outcome is not None:
        return None
    if battle.owed:
        return _owed_prompt(battle)
    phase = battle.phase
    if phase in OWED_STEPS:
        return FollowOn(OWED_STEPS[phase])
    if phase == ROLE:
        seat = scouting_advantage(engine, battle)["seat"]
        return PendingPrompt(
            PromptKind.CHOOSE_ROLE,
            f"{tokens.seat(seat)}, you have the scouting advantage: attack or defend "
            f"{tokens.area(battle.territory)}?", seat,
        )
    if phase == EMERGENCY:
        return PendingPrompt(
            PromptKind.EMERGENCY_DEFENSE,
            f"{tokens.seat(battle.defender)}, your base is attacked: produce emergency defenses?",
            battle.defender,
        )
    if phase == REPOSITION:
        seat = reposition_asker(battle)
        return PendingPrompt(
            PromptKind.REPOSITION_FLANKERS,
            f"{tokens.seat(seat)}, round {battle.round}: keep your flanking forces where they "
            "stand, or reposition them?", seat,
        )
    if phase == PLACE:
        return PendingPrompt(
            PromptKind.PLACE_FORCE, f"{tokens.seat(battle.to_place)}, place a force.",
            battle.to_place,
        )
    if phase == RETREAT:
        seat = retreat_asker(engine, battle)
        return PendingPrompt(
            PromptKind.DECLARE_RETREAT,
            f"{tokens.seat(seat)}, round {battle.round}: retreat, or fight on?", seat,
        )
    if phase == DAMAGE:
        seat = roller(engine, battle)
        if seat is None:
            return FollowOn(FollowOnStep.CLOSE_GROUP)
        return PendingPrompt(
            PromptKind.CHOOSE_TARGET,
            f"{tokens.seat(seat)}, initiative {battle.group}: choose a force's target.", seat,
        )
    return None


def pending(engine: "RulesEngine", game, match: "MatchState") -> Union[PendingPrompt, FollowOn, None]:
    """
    What this match is waiting on: a seat's question, with its options,
    or the step the bot owes -- or `None` where nothing is (no battle,
    or one already over). `game`, the record, is step 5's; nothing reads
    it yet.
    """
    battle = match.battle
    if battle is None:
        return None
    waiting = _pending(engine, battle)
    if isinstance(waiting, PendingPrompt):
        return with_options(engine, battle, waiting)
    return waiting


def pending_prompt(engine, game, match) -> Optional[PendingPrompt]:
    waiting = pending(engine, game, match)
    return waiting if isinstance(waiting, PendingPrompt) else None


def owed_step(engine, game, match) -> Optional[FollowOn]:
    waiting = pending(engine, game, match)
    return waiting if isinstance(waiting, FollowOn) else None
