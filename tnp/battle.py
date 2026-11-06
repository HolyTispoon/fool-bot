"""
The battle (docs/tnp-rules.md, 6) as a saved state of its own --
`BattleState`, with its `SavedField` table, so a battle survives a
restart mid-round -- and the readings over it: the line, who is engaged,
what is adjacent, the scouting advantage, where a force may be placed,
what it may target and at what, who may retreat, and what a base card's
hits may destroy. The steps that change it are `tnp.flow.battle`'s; the
one reading of what it is waiting on is `tnp.prompts.pending`'s.

**The battle is self-contained.** What it needs from outside -- whether
each seat has a path home (TNP 6.6), the defending base's facilities and
upgrades (TNP 6.9), the pool and the supply an emergency defense spends
(TNP 6.2), and step 9's card modifiers (TNP 4.2) -- is handed in when it
opens and kept on it, and what it decides is handed back in `outcome`
and beside it (`structures`, `emergency`, `produced`), for the March
(`tnp.flow.turn.settle_battle`) to put on the map. See docs/design/tnp.md, "The battle".

**The line** is a list of columns, left to right. A column holds at
most one force a seat **in front** -- two, one a seat, is an engaged
pair (TNP 6.5) -- and any number **flanking** behind it. A force is
named `"<seat>:<unit>"`, since a seat's units of one kind are one force
(TNP 6.1); the two base cards are the targets `"base_left"` and
`"base_right"`, standing just beyond the line's two ends (TNP 6.9).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Mapping, Optional

from gamekit.saved import SavedField
from tnp.catalog import UnitType

if TYPE_CHECKING:
    from tnp.engine import RulesEngine

#: The two seats, Blue's base on the left of the map and Green's on the
#: right (TNP 1.2, 2.1).
SEATS = ("blue", "green")

BASE_LEFT = "base_left"
BASE_RIGHT = "base_right"
BASE_CARDS = (BASE_LEFT, BASE_RIGHT)

#: The most rounds a battle has (TNP 6.4).
ROUNDS = 6

#: Hits a force must score on a base card in one roll to destroy one
#: thing (TNP 6.9).
BASE_CARD_HITS = 2

# The battle's phases, as saved. Each is either a question somebody is
# asked (`tnp.prompts`) or a step the bot owes (`OWED`).
ROLE = "role"            # TNP 6.1: the advantaged seat chooses its side
EMERGENCY = "emergency"  # TNP 6.2: the defender of a base produces defenses
ROUND = "round"          # owed: the round's start
REPOSITION = "reposition"  # TNP 6.5: flanking forces kept or taken out
PLACE = "place"          # TNP 6.5
RETREAT = "retreat"      # TNP 6.6
DAMAGE = "damage"        # TNP 6.7
LOSSES = "losses"        # owed: the group's losses
ROUND_END = "round_end"  # owed: TNP 6.10
OVER = "over"

# Placement slots, as an action names them (TNP 6.5).
ENGAGE = "engage"   # "engage:<column>": in front of an unengaged enemy force
COLUMN = "column"   # "column:<gap>": a new column at a gap, 0 the left end
FLANK = "flank"     # "flank:<column>": behind the seat's own force


def other(seat: str) -> str:
    return SEATS[1] if seat == SEATS[0] else SEATS[0]


def force_id(seat: str, unit: str) -> str:
    return f"{seat}:{unit}"


# -- The state ---------------------------------------------------------------


@dataclass
class Force:
    """A seat's units of one kind in the battle (TNP 6.1), and how many
    of them carry a damage token (Tough, TNP 6.8)."""

    seat: str
    unit: str
    count: int
    damaged: int = 0

    @property
    def id(self) -> str:
        return force_id(self.seat, self.unit)

    def to_dict(self) -> dict:
        return {"seat": self.seat, "unit": self.unit, "count": self.count, "damaged": self.damaged}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Force":
        return cls(data["seat"], data["unit"], int(data["count"]), int(data.get("damaged", 0)))


@dataclass
class Column:
    """One column of the line: the force each seat has in front, and
    the forces each has flanking behind it."""

    front: dict[str, str] = field(default_factory=dict)
    flank: dict[str, list[str]] = field(default_factory=dict)

    def flankers(self, seat: str) -> list[str]:
        return self.flank.get(seat, [])

    def everyone(self) -> list[str]:
        found = list(self.front.values())
        for seat in SEATS:
            found.extend(self.flankers(seat))
        return found

    def to_dict(self) -> dict:
        return {
            "front": dict(self.front),
            "flank": {seat: list(ids) for seat, ids in self.flank.items() if ids},
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Column":
        return cls(
            front=dict(data.get("front", {})),
            flank={seat: list(ids) for seat, ids in data.get("flank", {}).items()},
        )


def _forces_out(forces: list) -> list:
    return [force.to_dict() for force in forces]


def _forces_in(data: list) -> list:
    return [Force.from_dict(row) for row in data]


def _line_out(line: list) -> list:
    return [column.to_dict() for column in line]


def _line_in(data: list) -> list:
    return [Column.from_dict(row) for row in data]


def _copy(value):
    """A deep copy of plain JSON, so neither the save nor the live
    battle holds a reference into the other (`SavedField`)."""
    if isinstance(value, dict):
        return {key: _copy(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copy(item) for item in value]
    return value


@dataclass
class BattleState:
    """
    A battle as it stands. Every field is in `BATTLE_SAVED_FIELDS`, and
    a saved key is never renamed (the preamble's save rule).
    """

    #: The area fought over: a territory's number, or a base's slug.
    territory: str
    attacker: Optional[str] = None
    defender: Optional[str] = None
    #: Who held the territory as the battle opened, `None` if neutral
    #: (TNP 6.11 reads it: air units keep a territory already held).
    held_by: Optional[str] = None
    #: Both seats attacked a neutral territory (TNP 6.1).
    contested: bool = False
    forces: list[Force] = field(default_factory=list)
    line: list[Column] = field(default_factory=list)
    round: int = 1
    phase: str = ROUND
    #: The round's scouting advantage, `{"seat": ..., "by": n}`, or `None`.
    advantage: Optional[dict] = None
    #: Who places next this round; `run_left` is what is left of the
    #: advantage's opening placements, 0 once the seats take turns.
    to_place: Optional[str] = None
    run_left: int = 0
    #: The seats that declared a retreat this round, and the seats asked.
    retreats: list[str] = field(default_factory=list)
    retreat_asked: list[str] = field(default_factory=list)
    #: The seats asked this round whether they keep their flanking
    #: forces where they stand (TNP 6.5).
    reposition_asked: list[str] = field(default_factory=list)
    #: How many units of each force are retreating this round: they do
    #: not attack, and leave at the round's end (TNP 6.6).
    leaving: dict[str, int] = field(default_factory=dict)
    #: The units that have retreated home, by seat and unit, with their
    #: damage (TNP 6.6) -- in `outcome` too, once it is over.
    withdrawn: dict[str, dict] = field(default_factory=dict)
    #: The initiative group rolling, and the forces in it that have rolled.
    group: Optional[int] = None
    rolled: list[str] = field(default_factory=list)
    #: The group's hits on each force, and its units removed outright
    #: (Splash, a Worker given for Repair), which come off together once
    #: the whole group has rolled (TNP 6.7).
    hits: dict[str, int] = field(default_factory=dict)
    removals: dict[str, int] = field(default_factory=dict)
    #: Whether this group's Repair has been asked (TNP 6.8).
    repairs_asked: bool = False
    #: The choices a roll left owed, asked before anything else: a Splash
    #: target, what a base card's hits destroy, a Repair.
    owed: list[dict] = field(default_factory=list)
    #: Whether each seat's ground forces have a path home (TNP 6.6).
    paths_home: dict[str, bool] = field(default_factory=dict)
    #: The defending base's facilities and upgrades, for a base battle
    #: (TNP 6.9): `{"facilities": [...], "upgrades": [...]}`.
    structures: Optional[dict] = None
    #: What the base card's hits destroyed, one thing an attack.
    destroyed: Optional[str] = None
    #: The defender's emergency resources, for a base battle (TNP 6.2):
    #: `{"pool": {...}, "supply_room": {unit: n}}`.
    emergency: Optional[dict] = None
    #: The units the emergency defense produced.
    produced: dict[str, int] = field(default_factory=dict)
    #: Modifiers handed in from outside -- step 9's cards (TNP 4.2, 8.5):
    #: each `{"seat", "unit", "against", "value"}`, `None` for any.
    modifiers: list[dict] = field(default_factory=list)
    #: How it ended, once it has (`tnp.flow.battle.finish`).
    outcome: Optional[dict] = None

    def to_dict(self) -> dict:
        return {row.name: row.stored(getattr(self, row.name)) for row in BATTLE_SAVED_FIELDS}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BattleState":
        return cls(**{row.name: row.restored(data) for row in BATTLE_SAVED_FIELDS})

    # -- Lookups -------------------------------------------------------------

    def force(self, ident: str) -> Force:
        for found in self.forces:
            if found.id == ident:
                return found
        raise KeyError(ident)

    def has_force(self, ident: str) -> bool:
        return any(found.id == ident for found in self.forces)

    def living(self, seat: Optional[str] = None) -> list[Force]:
        return [
            found for found in self.forces
            if found.count > 0 and (seat is None or found.seat == seat)
        ]


#: The battle's save table: the format is the contract.
BATTLE_SAVED_FIELDS: tuple[SavedField, ...] = (
    SavedField("territory"),
    SavedField("attacker"),
    SavedField("defender"),
    SavedField("held_by"),
    SavedField("contested", default=False),
    SavedField("forces", factory=list, write=_forces_out, read=_forces_in),
    SavedField("line", factory=list, write=_line_out, read=_line_in),
    SavedField("round", default=1),
    SavedField("phase", default=ROUND),
    SavedField("advantage", write=_copy, read=_copy),
    SavedField("to_place"),
    SavedField("run_left", default=0),
    SavedField("retreats", factory=list, write=list, read=list),
    SavedField("retreat_asked", factory=list, write=list, read=list),
    SavedField("reposition_asked", factory=list, write=list, read=list),
    SavedField("leaving", factory=dict, write=dict, read=dict),
    SavedField("withdrawn", factory=dict, write=_copy, read=_copy),
    SavedField("group"),
    SavedField("rolled", factory=list, write=list, read=list),
    SavedField("hits", factory=dict, write=dict, read=dict),
    SavedField("removals", factory=dict, write=dict, read=dict),
    SavedField("repairs_asked", default=False),
    SavedField("owed", factory=list, write=_copy, read=_copy),
    SavedField("paths_home", factory=dict, write=dict, read=dict),
    SavedField("structures", write=_copy, read=_copy),
    SavedField("destroyed"),
    SavedField("emergency", write=_copy, read=_copy),
    SavedField("produced", factory=dict, write=dict, read=dict),
    SavedField("modifiers", factory=list, write=_copy, read=_copy),
    SavedField("outcome", write=_copy, read=_copy),
)


# -- The line ------------------------------------------------------------------


def locate(battle: BattleState, ident: str) -> Optional[tuple[int, bool]]:
    """Where a force stands: its column and whether it is flanking, or
    `None` while it is not in the line."""
    for index, column in enumerate(battle.line):
        if ident in column.front.values():
            return index, False
        for seat in SEATS:
            if ident in column.flankers(seat):
                return index, True
    return None


def in_line(battle: BattleState) -> list[str]:
    found = []
    for column in battle.line:
        found.extend(column.everyone())
    return found


def unplaced(battle: BattleState, seat: str) -> list[Force]:
    """A seat's living forces not in the line, in the order they were
    formed (the unit sheet's)."""
    placed = set(in_line(battle))
    return [found for found in battle.living(seat) if found.id not in placed]


def engaged(battle: BattleState, ident: str) -> bool:
    """In front, with an opposing force in front in the same column
    (TNP 6.5)."""
    where = locate(battle, ident)
    if where is None or where[1]:
        return False
    return len(battle.line[where[0]].front) == 2


def flanking(battle: BattleState, ident: str) -> bool:
    where = locate(battle, ident)
    return where is not None and where[1]


def adjacent(battle: BattleState, one: str, another: str) -> bool:
    """
    Two forces of the same seat side by side (TNP 6.5, 6.8): in the same
    column -- a force and the force flanking it, which "is in the same
    column as the force it stands behind" -- or in neighbouring columns,
    front or flanking.
    """
    if one == another:
        return False
    if battle.force(one).seat != battle.force(another).seat:
        return False
    here, there = locate(battle, one), locate(battle, another)
    if here is None or there is None:
        return False
    return abs(here[0] - there[0]) <= 1


def adjacent_forces(battle: BattleState, ident: str) -> list[str]:
    """The living forces of the same seat adjacent to this one."""
    return [
        found.id for found in battle.living(battle.force(ident).seat)
        if adjacent(battle, ident, found.id)
    ]


def flankers_of(battle: BattleState, seat: str) -> list[str]:
    """A seat's flanking forces in the line, left to right."""
    found = []
    for column in battle.line:
        found.extend(column.flankers(seat))
    return found


def reposition_asker(battle: BattleState) -> Optional[str]:
    """Who is asked whether they keep their flanking forces where they
    stand, at a round's start after the first: the attacker first, then
    the defender, each only where it has one (TNP 6.5)."""
    for seat in (battle.attacker, battle.defender):
        if seat not in battle.reposition_asked and flankers_of(battle, seat):
            return seat
    return None


# -- The scouting advantage ------------------------------------------------------


def scouting_totals(engine: "RulesEngine", battle: BattleState) -> dict[str, int]:
    """Each seat's scouting points: every unit its Scouting number
    (TNP 6.4)."""
    totals = {seat: 0 for seat in SEATS}
    for found in battle.living():
        totals[found.seat] += engine.unit(found.unit).scouting * found.count
    return totals


def scouting_advantage(engine: "RulesEngine", battle: BattleState) -> Optional[dict]:
    """The seat with the higher total and by how much, or `None` for
    equal totals (TNP 6.4)."""
    totals = scouting_totals(engine, battle)
    blue, green = (totals[seat] for seat in SEATS)
    if blue == green:
        return None
    seat = SEATS[0] if blue > green else SEATS[1]
    return {"seat": seat, "by": abs(blue - green)}


def initiative_totals(engine: "RulesEngine", battle: BattleState) -> dict[str, int]:
    """Each seat's initiative values over all its units there (TNP 6.1)."""
    totals = {seat: 0 for seat in SEATS}
    for found in battle.living():
        totals[found.seat] += engine.unit(found.unit).initiative * found.count
    return totals


# -- Placing a force -------------------------------------------------------------


def slots(engine: "RulesEngine", battle: BattleState, seat: str, force: Force) -> tuple[str, ...]:
    """
    Where `force` may be placed now (TNP 6.5):

    - while the other seat has an unengaged force in front in the line,
      only in front of one of them (`engage:<column>`);
    - otherwise in a new column, at either end or between two
      (`column:<gap>`, gap 0 the left end);
    - and, once every force of the other seat is placed and engaged,
      also behind a force of its own in front that has no flanking force
      yet (`flank:<column>`) -- never a Base Defense unit (TNP 7).
    """
    enemy = other(seat)
    open_enemies = [
        index for index, column in enumerate(battle.line)
        if enemy in column.front and seat not in column.front
    ]
    if open_enemies:
        return tuple(f"{ENGAGE}:{index}" for index in open_enemies)
    found = [f"{COLUMN}:{gap}" for gap in range(len(battle.line) + 1)]
    if not unplaced(battle, enemy) and not engine.has_trait(force.unit, "base_defense"):
        found.extend(
            f"{FLANK}:{index}" for index, column in enumerate(battle.line)
            if seat in column.front and not column.flankers(seat)
        )
    return tuple(found)


# -- Retreat ---------------------------------------------------------------------


def may_retreat(engine: "RulesEngine", battle: BattleState, seat: str) -> bool:
    """
    Whether a seat may declare a retreat (TNP 6.6): never the defender
    of a base; with a path home, always; with none, only where it has an
    air force, which can always go -- the ground units its Chopper
    Carriers cannot carry stay and fight.
    """
    if seat == battle.defender and is_base(engine, battle):
        return False
    forces = battle.living(seat)
    if not forces:
        return False
    if battle.paths_home.get(seat, False):
        return True
    return any(engine.unit(found.unit).type is UnitType.AIR for found in forces)


def carriers(engine: "RulesEngine", battle: BattleState, seat: str) -> dict[str, int]:
    """The seat's carrying units in the battle, by unit, with how many
    (TNP 7: Transport)."""
    capacity = engine.catalog.board.get("transport", {})
    return {
        found.unit: found.count for found in battle.living(seat) if found.unit in capacity
    }


def carriable(engine: "RulesEngine", battle: BattleState, seat: str) -> dict[str, int]:
    """The seat's ground forces a carrier can take, and how many of each
    one carrier holds (TNP 7)."""
    capacity = engine.catalog.board.get("transport", {})
    found = {}
    for carrier in carriers(engine, battle, seat):
        for one in battle.living(seat):
            held = capacity[carrier].get(one.unit)
            if held:
                found[one.id] = max(found.get(one.id, 0), int(held))
    return found


def carriers_needed(engine: "RulesEngine", battle: BattleState, carried: Mapping[str, int]) -> int:
    """How many carriers it takes to carry `carried` -- one kind of unit
    a carrier, without mixing (TNP 7)."""
    per = carriable(engine, battle, battle.force(next(iter(carried))).seat) if carried else {}
    return sum(-(-count // per[ident]) for ident, count in carried.items() if count)


def firing(battle: BattleState, ident: str) -> int:
    """The units of a force that attack this round: all but those
    retreating (TNP 6.6)."""
    return battle.force(ident).count - battle.leaving.get(ident, 0)


def retreat_asker(engine: "RulesEngine", battle: BattleState) -> Optional[str]:
    """Who is asked whether they retreat: the attacker first, and the
    defender only if the attacker does not (TNP 6.6)."""
    if battle.retreats:
        return None
    for seat in (battle.attacker, battle.defender):
        if seat in battle.retreat_asked:
            continue
        if may_retreat(engine, battle, seat):
            return seat
    return None


# -- Damage ----------------------------------------------------------------------


def is_base(engine: "RulesEngine", battle: BattleState) -> bool:
    return engine.catalog.areas[battle.territory].is_base


def target_type(engine: "RulesEngine", battle: BattleState, target: str) -> UnitType:
    """What a target is attacked as: its unit's type, or armored for a
    base card, a building (TNP 6.9)."""
    if target in BASE_CARDS:
        return UnitType.ARMORED
    return engine.unit(battle.force(target).unit).type


def _target_column(battle: BattleState, target: str) -> int:
    if target == BASE_LEFT:
        return -1
    if target == BASE_RIGHT:
        return len(battle.line)
    return locate(battle, target)[0]


def position_modifier(battle: BattleState, ident: str, target: str) -> int:
    """
    The position modifier of a force in front, engaged or alone in its
    column (TNP 6.7, 6.9): −1 for each column it reaches across, a base
    card's place being just beyond the end of the line -- so at least −1
    against one, which no force can engage. A flanking force adds +1 to
    it (`flank_modifier`).
    """
    return -abs(locate(battle, ident)[0] - _target_column(battle, target))


def outside_modifier(engine: "RulesEngine", battle: BattleState, ident: str, target: str) -> int:
    """The modifiers handed in from outside (step 9's cards, TNP 8.5)."""
    attacker = battle.force(ident)
    against = "base" if target in BASE_CARDS else target_type(engine, battle, target).value
    total = 0
    for row in battle.modifiers:
        if row.get("seat") not in (None, attacker.seat):
            continue
        if row.get("unit") not in (None, attacker.unit):
            continue
        if row.get("against") not in (None, against):
            continue
        total += int(row["value"])
    return total


def flank_modifier(battle: BattleState, ident: str, target: str) -> int:
    """
    A flanking force's modifier for where it stands (TNP 6.5): +1 on top
    of the position modifier every force takes -- +1 at the opposing
    force in its own column, none one column away, −1 two away -- and
    against a base card the same (TNP 6.9).
    """
    return position_modifier(battle, ident, target) + 1


def modifier(engine: "RulesEngine", battle: BattleState, ident: str, target: str) -> int:
    """Every modifier one force's dice take against one target (TNP
    4.2): a flanking force's for where it stands, or anybody else's
    position modifier, and the outside ones."""
    if flanking(battle, ident):
        total = flank_modifier(battle, ident, target)
    else:
        total = position_modifier(battle, ident, target)
    return total + outside_modifier(engine, battle, ident, target)


def dice(engine: "RulesEngine", battle: BattleState, ident: str, target: str) -> int:
    """The dice a force rolls at a target: one a unit, or one for every
    two if its rating against the target's type is Poor (TNP 4.3)."""
    found = battle.force(ident)
    rating = engine.rating(found.unit, target_type(engine, battle, target))
    return rating.dice(max(0, firing(battle, ident)))


def targets(engine: "RulesEngine", battle: BattleState, ident: str) -> tuple[str, ...]:
    """
    What a force may attack (TNP 6.7, 6.9): any opposing force in the
    line, and, for the attacker of a base, the two base cards. Losses
    come off only when the group has rolled, so a force its own group
    has already finished is still a target.
    """
    seat = battle.force(ident).seat
    enemy = other(seat)
    found = [one for one in in_line(battle) if battle.force(one).seat == enemy and battle.force(one).count > 0]
    if seat == battle.attacker and is_base(engine, battle):
        found.extend(BASE_CARDS)
    return tuple(found)


def rollers(engine: "RulesEngine", battle: BattleState, seat: str) -> list[str]:
    """
    The forces of `seat` still to roll in this initiative group (TNP
    6.7): in the line, of the group's initiative, not yet rolled, and
    with a die to roll at something -- a lone Poor unit rolls none
    (TNP 4.3), so it is not asked. Units retreating this round do not
    attack (TNP 6.6), so a force whose every unit is leaving rolls none.
    """
    if battle.group is None:
        return []
    placed = set(in_line(battle))
    found = []
    for force in battle.living(seat):
        if force.id not in placed or force.id in battle.rolled:
            continue
        if engine.unit(force.unit).initiative != battle.group:
            continue
        if aimed(engine, battle, force.id):
            found.append(force.id)
    return found


def aimed(engine: "RulesEngine", battle: BattleState, ident: str) -> tuple[str, ...]:
    """The targets a force has a die to roll at -- what it is offered.
    A target it would roll no die at (a lone Poor unit's, TNP 4.3) asks
    nothing, so it is not offered."""
    return tuple(target for target in targets(engine, battle, ident) if dice(engine, battle, ident, target) > 0)


def roller(engine: "RulesEngine", battle: BattleState) -> Optional[str]:
    """Who rolls next in the group: the attacker for all its forces,
    then the defender (TNP 6.7)."""
    for seat in (battle.attacker, battle.defender):
        if rollers(engine, battle, seat):
            return seat
    return None


def groups(engine: "RulesEngine", battle: BattleState) -> list[int]:
    """The initiative groups among the forces in the line, lowest first."""
    return sorted({
        engine.unit(battle.force(one).unit).initiative
        for one in in_line(battle) if battle.force(one).count > 0
    })


# -- Repair and Splash -----------------------------------------------------------


def repair_workers(engine: "RulesEngine", battle: BattleState, ident: str) -> tuple[tuple[str, int], ...]:
    """
    The Workers that may ignore a hit on a Mechanical force (TNP 6.8):
    each adjacent force of its seat with the Repair trait, and how many
    of its units are not already given up this group.
    """
    found = []
    for one in adjacent_forces(battle, ident):
        force = battle.force(one)
        if not engine.has_trait(force.unit, "repair"):
            continue
        left = force.count - battle.removals.get(one, 0)
        if left > 0:
            found.append((one, left))
    return tuple(found)


def splash_targets(engine: "RulesEngine", battle: BattleState, hit: str) -> tuple[str, ...]:
    """The infantry forces adjacent to the force a Splash force hit
    (TNP 6.8), of the hit force's seat."""
    return tuple(
        one for one in adjacent_forces(battle, hit)
        if engine.unit(battle.force(one).unit).type is UnitType.INFANTRY
    )


# -- The base cards --------------------------------------------------------------


def destroyable(engine: "RulesEngine", battle: BattleState) -> tuple[str, ...]:
    """
    What a base card's hits may destroy (TNP 6.9): nothing once one
    thing has gone this attack; otherwise any upgrade the defender has
    built, and a facility only once it has no upgrade left -- and never
    the Barracks or Base Defenses.
    """
    if battle.destroyed is not None or battle.structures is None:
        return ()
    upgrades = [slug for slug in battle.structures.get("upgrades", [])]
    standing = {engine.catalog.upgrades[slug].facility for slug in upgrades}
    facilities = [
        slug for slug in battle.structures.get("facilities", [])
        if engine.catalog.facilities[slug].destructible and slug not in standing
    ]
    return tuple(upgrades + facilities)


# -- The emergency base defense --------------------------------------------------


def emergency_cap(engine: "RulesEngine", battle: BattleState) -> int:
    """The Base Defenses' production cap: 4, or 8 with its
    infrastructure upgrade (TNP 2.4, 6.2)."""
    facility = engine.catalog.facilities["base_defenses"]
    built = (battle.structures or {}).get("upgrades", [])
    if facility.infrastructure_upgrade in built:
        return facility.upgraded_production_cap
    return facility.production_cap


def emergency_limits(engine: "RulesEngine", battle: BattleState) -> tuple[dict[str, int], list[tuple[tuple[str, ...], int]]]:
    """
    The most of each base defense unit an emergency defense may produce
    (TNP 6.2): its supply room, at most the cap, and a Laser Cannon only
    once its upgrade is built; and each limit on units deployed together
    with the room left under it, counting the defender's units already
    in the battle (TNP 2.4).
    """
    cap = emergency_cap(engine, battle)
    built = set((battle.structures or {}).get("upgrades", []))
    room = (battle.emergency or {}).get("supply_room", {})
    most = {}
    for slug in engine.catalog.facilities["base_defenses"].units:
        upgrade = engine.unit(slug).upgrade
        if upgrade is not None and upgrade not in built:
            most[slug] = 0
            continue
        most[slug] = max(0, min(cap, int(room.get(slug, 0))))
    together = []
    for limit in engine.catalog.board["limits"]["deployed_together"]:
        units = tuple(limit["units"])
        deployed = sum(
            found.count for found in battle.living(battle.defender) if found.unit in units
        )
        together.append((units, max(0, int(limit["max"]) - deployed)))
    return most, together
