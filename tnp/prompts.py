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

Step 2 asks a battle's questions (TNP 6), each of one seat at a time:
`asked_seat` is the seat asked. Step 4 adds the turn's (TNP 5): two
**simultaneous** kinds, `PLAN` and `TRADE`, which ask both seats at
once (docs/tnp-bot.md, decision 7), and `CONQUER`, one seat's in March.
**`pending_all` is the one reading** -- every question open now, both
seats' in a simultaneous phase, or the step the bot owes -- and
`pending` the one thing where there is one thing, raising
`SeveralAsked` where both seats are asked (Codex's two-headed dragon,
`codex/prompts.py`). A battle's units are revealed (TNP 6.1) and a
seat's pool is open information (TNP 2.2), so nothing a battle prompt
carries is hidden; **a `PLAN` or `TRADE` prompt is its asked seat's
alone** -- its options carry the seat's saved plan and its units.
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
    SEATS,
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
from tnp.components import MARCH, OVER, PLAN, PRODUCTION, TRADE, CLEANUP, MatchState
from tnp.flow.result import FollowOn, FollowOnStep
from tnp.wire import jsonable

if TYPE_CHECKING:
    from tnp.engine import RulesEngine


class PromptKind(Enum):
    # -- The turn (TNP 5) ---------------------------------------------------
    #: Infrastructure and Deployment, both seats at once: the plan, kept
    #: until the seat locks in (TNP 5.2, 5.3).
    PLAN = "plan"
    #: Which ground unit is revealed to take a neutral territory (TNP 5.5).
    CONQUER = "conquer"
    #: Production and Trade's trade, both seats at once (TNP 5.9).
    TRADE = "trade"

    # -- The battle (TNP 6) ---------------------------------------------------
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
class BuildOption(_Wire):
    """A unit the seat's board builds now (TNP 5.2): its facility, its
    cost, and the most of it the supply and the facility's cap allow."""

    unit: str
    facility: str
    materials: int
    gold: int
    most: int


@dataclass(frozen=True)
class FacilityCap(_Wire):
    facility: str
    cap: int


@dataclass(frozen=True)
class StructureOption(_Wire):
    """A facility or upgrade the seat may place this Infrastructure."""

    structure: str
    materials: int
    gold: int


@dataclass(frozen=True)
class AttackTarget(_Wire):
    """An area an attack may be aimed at, who holds it, and whether a
    ground unit has a path there now (TNP 5.3) -- an attack may still be
    planned without one, in the hope of a path by the time it resolves."""

    area: str
    held_by: Optional[str]
    path: bool


@dataclass(frozen=True)
class PlanOptions(_Wire):
    seat: str
    turn: int
    #: The pool (TNP 2.2): what Infrastructure spends is the materials
    #: and gold in it.
    pool: Mapping[str, int]
    build: tuple[BuildOption, ...]
    caps: tuple[FacilityCap, ...]
    structures: tuple[StructureOption, ...]
    #: The units at the base, deployable (TNP 5.3).
    available: Mapping[str, int]
    #: The attack spots, and what each may be aimed at (TNP 2.5, 5.3).
    spots: tuple[str, ...]
    targets: tuple[AttackTarget, ...]
    #: Where defenders may go: the territories held, and the base.
    defenses: tuple[str, ...]
    #: The units that go only into the base defense spot (TNP 7).
    base_only: tuple[str, ...]
    together: tuple["TogetherLimit", ...]
    #: The plan saved so far (`tnp.turn.normal_plan`'s shape), or `None`.
    plan: Optional[Mapping[str, Any]] = None


@dataclass(frozen=True)
class ConquerOptions(_Wire):
    area: str
    spot: str
    #: The ground units in the attacking pile, one of which is revealed.
    units: tuple[str, ...]


@dataclass(frozen=True)
class TradeOptions(_Wire):
    seat: str
    #: The minerals and gems in the pool, by kind.
    tokens: Mapping[str, int]
    #: The conversion rates (TNP 5.9): `{"mineral": {"materials", "gold"}, "gem": ...}`.
    rates: Mapping[str, Mapping[str, Optional[int]]]
    #: The trade saved so far (`tnp.turn.normal_trade`'s shape), or `None`.
    trade: Optional[Mapping[str, Any]] = None


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
    PlanOptions, ConquerOptions, TradeOptions, RoleOptions, EmergencyOptions, RepositionOptions, PlaceOptions, RetreatOptions, TargetOptions,
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
    what was chosen -- a force, a slot, a target, a plan. **`seat` names
    whose answer it is**, which a simultaneous kind (`SIMULTANEOUS`)
    must, since both seats are asked at once; any other kind may, and is
    refused where it names a seat that was not asked.
    """

    kind: PromptKind
    choice: str = ""
    arguments: Mapping[str, Any] = field(default_factory=dict)
    seat: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "kind": self.kind.value, "choice": self.choice,
            "arguments": jsonable(dict(self.arguments)), "seat": self.seat,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Action":
        """An action off the wire -- the one thing read back."""
        return cls(
            kind=PromptKind(data["kind"]),
            choice=data.get("choice") or "",
            arguments=dict(data.get("arguments") or {}),
            seat=data.get("seat"),
        )


#: The kinds that ask both seats at once (decision 7).
SIMULTANEOUS = frozenset({PromptKind.PLAN, PromptKind.TRADE})


#: The answers each kind offers. A kind with one answer offers "".
CHOICES: Mapping[PromptKind, tuple[str, ...]] = {
    PromptKind.PLAN: ("save", "lock"),
    PromptKind.CONQUER: ("",),
    PromptKind.TRADE: ("save", "lock"),
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


def _role_options(engine, match, prompt) -> RoleOptions:
    battle = match.battle
    advantage = scouting_advantage(engine, battle)
    return RoleOptions(advantage["seat"], advantage["by"])


def _emergency_options(engine, match, prompt) -> EmergencyOptions:
    battle = match.battle
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


def _reposition_options(engine, match, prompt) -> RepositionOptions:
    battle = match.battle
    seat = prompt.asked_seat
    found = []
    for column in battle.line:
        for one in column.flankers(seat):
            force = battle.force(one)
            found.append(FlankerOption(one, force.unit, force.count, column.front[seat]))
    return RepositionOptions(seat, tuple(found))


def _place_options(engine, match, prompt) -> PlaceOptions:
    battle = match.battle
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


def _retreat_options(engine, match, prompt) -> RetreatOptions:
    battle = match.battle
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


def _target_options(engine, match, prompt) -> TargetOptions:
    battle = match.battle
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


def _repair_options(engine, match, prompt) -> RepairOptions:
    battle = match.battle
    owed = battle.owed[0]
    return RepairOptions(
        owed["force"], battle.hits.get(owed["force"], 0),
        tuple(WorkerOption(one, left) for one, left in repair_workers(engine, battle, owed["force"])),
    )


def _splash_options(engine, match, prompt) -> SplashOptions:
    battle = match.battle
    owed = battle.owed[0]
    return SplashOptions(owed["force"], owed["hit"], splash_targets(engine, battle, owed["hit"]))


def _destroy_options(engine, match, prompt) -> DestroyOptions:
    battle = match.battle
    return DestroyOptions(destroyable(engine, battle))


def _plan_options(engine, match, prompt) -> PlanOptions:
    from tnp import turn

    seat = prompt.asked_seat
    state = match.seat(seat)
    catalog = engine.catalog
    room = turn.supply_room(engine, match, seat)
    build = []
    for slug, unit in catalog.units.items():
        if not turn.can_build_unit(engine, state, slug):
            continue
        most = min(room[slug], turn.production_cap(engine, state, unit.facility))
        build.append(BuildOption(slug, unit.facility, unit.cost.materials, unit.cost.gold, most))
    return PlanOptions(
        seat=seat,
        turn=match.turn,
        pool=dict(state.pool),
        build=tuple(build),
        caps=tuple(
            FacilityCap(slug, turn.production_cap(engine, state, slug))
            for slug in catalog.facilities if slug in state.built
        ),
        structures=tuple(
            StructureOption(slug, turn.structure_cost(engine, slug).materials,
                            turn.structure_cost(engine, slug).gold)
            for slug in turn.structures_open(engine, state)
        ),
        available=dict(state.available),
        spots=turn.attack_spots(match),
        targets=tuple(
            AttackTarget(area, match.controller(area), turn.has_path(engine, match, seat, area))
            for area in sorted(turn.attack_targets(engine, seat), key=turn.area_order)
        ),
        defenses=turn.defense_areas(match, seat),
        base_only=tuple(slug for slug in catalog.units if engine.has_trait(slug, "base_defense")),
        together=tuple(
            TogetherLimit(tuple(limit["units"]), int(limit["max"]))
            for limit in catalog.board["limits"]["deployed_together"]
        ),
        plan=state.plan,
    )


def _conquer_options(engine, match, prompt) -> ConquerOptions:
    from tnp import turn

    resolving = match.resolving
    return ConquerOptions(
        resolving["area"], resolving["spot"],
        tuple(turn.ground_units(engine, resolving["piles"][prompt.asked_seat])),
    )


def _trade_options(engine, match, prompt) -> TradeOptions:
    from tnp.components import RESOURCES

    state = match.seat(prompt.asked_seat)
    return TradeOptions(
        prompt.asked_seat,
        {kind: int(state.pool.get(kind, 0)) for kind in RESOURCES},
        engine.catalog.board["conversion"]["normal"],
        state.plan,
    )


OPTIONS = {
    PromptKind.PLAN: _plan_options,
    PromptKind.CONQUER: _conquer_options,
    PromptKind.TRADE: _trade_options,
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


def with_options(engine: "RulesEngine", match: MatchState, prompt: PendingPrompt) -> PendingPrompt:
    return replace(prompt, options=OPTIONS[prompt.kind](engine, match, prompt))


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


#: Where the turn's phase is one the bot runs, the step it owes.
TURN_STEPS = {
    PRODUCTION: FollowOnStep.PRODUCE,
    CLEANUP: FollowOnStep.CLEANUP,
}


def _plan_ask(match: MatchState, seat: str) -> PendingPrompt:
    return PendingPrompt(
        PromptKind.PLAN,
        f"{tokens.seat(seat)}, turn {match.turn}: Infrastructure and Deployment. Plan what to "
        "build and where your units go, then lock in.",
        seat,
    )


def _trade_ask(match: MatchState, seat: str) -> PendingPrompt:
    return PendingPrompt(
        PromptKind.TRADE,
        f"{tokens.seat(seat)}, Production and Trade: trade your minerals and gems, then lock in.",
        seat,
    )


def _turn_pending(engine: "RulesEngine", game, match: MatchState) -> list[Union[PendingPrompt, FollowOn]]:
    """
    Everything a game's turn waits on (TNP 5): a battle's one question
    while March fights one, the step that puts its outcome on the map
    once it is over, both seats' plans or trades in a simultaneous phase
    -- each seat that has not locked in, and in the trade only a seat
    with something to trade -- and otherwise the step the bot owes.
    """
    from tnp import turn

    if match.winner is not None or match.phase == OVER:
        return []
    battle = match.battle
    if battle is not None:
        if battle.outcome is None:
            waiting = _pending(engine, battle)
            return [] if waiting is None else [waiting]
        return [FollowOn(FollowOnStep.SETTLE_BATTLE)]
    phase = match.phase
    if phase == PLAN:
        asked = [_plan_ask(match, seat) for seat in SEATS if not match.seat(seat).locked]
        return asked or [FollowOn(FollowOnStep.REVEAL)]
    if phase == MARCH:
        resolving = match.resolving
        if resolving is not None and resolving.get("stage") == "conquer":
            (seat,) = resolving["piles"]
            return [PendingPrompt(
                PromptKind.CONQUER,
                f"{tokens.seat(seat)}, reveal a ground unit from attack {resolving['spot']} to take "
                f"{tokens.area(resolving['area'])}.", seat,
            )]
        return [FollowOn(FollowOnStep.MARCH)]
    if phase == TRADE:
        asked = [
            _trade_ask(match, seat) for seat in SEATS
            if not match.seat(seat).locked and turn.has_tokens(match, seat)
        ]
        return asked or [FollowOn(FollowOnStep.SETTLE_TRADES)]
    if phase in TURN_STEPS:
        return [FollowOn(TURN_STEPS[phase])]
    return []


def pending_all(engine: "RulesEngine", game, match: MatchState) -> tuple[Union[PendingPrompt, FollowOn], ...]:
    """
    **Everything this match is waiting on -- the one reading.** One
    prompt a seat in a simultaneous phase (both, until one locks in),
    one seat's question in a battle or in March, a step the bot owes
    alone, or nothing (the game over, or a battle staged alone and
    over). Each prompt carries its options. `game`, the record, is
    step 5's; nothing reads it yet.
    """
    if not match.playing:
        battle = match.battle
        waiting = None if battle is None else _pending(engine, battle)
        found = [] if waiting is None else [waiting]
    else:
        found = _turn_pending(engine, game, match)
    return tuple(
        with_options(engine, match, one) if isinstance(one, PendingPrompt) else one
        for one in found
    )


class SeveralAsked(RuntimeError):
    """`pending` was asked of a match whose phase asks both seats at once:
    it has no one question. A frontend lists them with `pending_prompts`
    (`codex.prompts.SeveralAsked`, the precedent)."""


def pending(engine: "RulesEngine", game, match: MatchState) -> Union[PendingPrompt, FollowOn, None]:
    """
    The one thing this match is waiting on: a seat's question, with its
    options, or the step the bot owes -- or `None` where nothing is.
    **Raises `SeveralAsked` where both seats are asked at once**: nothing
    may read one seat's plan prompt for the phase's.
    """
    everything = pending_all(engine, game, match)
    if len(everything) > 1:
        raise SeveralAsked("Both seats are asked; list them with pending_prompts.")
    return everything[0] if everything else None


def pending_prompts(engine, game, match) -> tuple[PendingPrompt, ...]:
    """Every question asked now, in seat order: both seats' in a
    simultaneous phase, none while the bot owes a step."""
    return tuple(one for one in pending_all(engine, game, match) if isinstance(one, PendingPrompt))


def pending_prompt(engine, game, match) -> Optional[PendingPrompt]:
    waiting = pending(engine, game, match)
    return waiting if isinstance(waiting, PendingPrompt) else None


def prompt_for(engine, game, match, seat: str) -> Optional[PendingPrompt]:
    """The question `seat` is asked now, if any -- what a seat's own
    panel shows."""
    for one in pending_prompts(engine, game, match):
        if one.asked_seat == seat:
            return one
    return None


def owed_step(engine, game, match) -> Optional[FollowOn]:
    everything = pending_all(engine, game, match)
    return everything[0] if everything and isinstance(everything[0], FollowOn) else None
