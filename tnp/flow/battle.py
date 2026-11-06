"""
The battle's steps (docs/tnp-rules.md, 6): `begin_battle`, which opens
one, the three steps the bot owes between answers (`begin_round`,
`close_group`, `end_round`, the keys of `tnp.flow.driver.MODEL_STEPS`),
and an answer for each question a battle asks. Each mutates
`match.battle` and says what happened in the model's voice with tokens;
none sends or saves anything. `tnp.prompts.pending` is the one reading
of what the battle waits on, and every step ends by asking it.

What a battle decides is handed back on the state (`outcome`) for the
March (step 4) to put on the map; see `tnp.battle` for what it is handed
in.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Mapping, Optional

from tnp import tokens
from tnp.battle import (
    BASE_CARD_HITS,
    BASE_CARDS,
    COLUMN,
    DAMAGE,
    EMERGENCY,
    ENGAGE,
    FLANK,
    LOSSES,
    OVER,
    PLACE,
    REPOSITION,
    RETREAT,
    ROLE,
    ROUND,
    ROUND_END,
    ROUNDS,
    SEATS,
    BattleState,
    Column,
    aimed,
    carriable,
    carriers,
    carriers_needed,
    Force,
    destroyable,
    dice,
    emergency_cap,
    emergency_limits,
    flankers_of,
    groups,
    initiative_totals,
    is_base,
    modifier,
    other,
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
from tnp.flow.result import Roll, StepResult
from tnp.game import RuleRefusal

if TYPE_CHECKING:
    from tnp.components import MatchState
    from tnp.engine import RulesEngine


# -- Words -----------------------------------------------------------------------


def _count(count: int, unit: str) -> str:
    return f"{count} {tokens.unit(unit)}"


def force_words(force: Force) -> str:
    """"{seat:blue}'s 3 {unit:tank}", and how many are damaged."""
    words = f"{tokens.seat(force.seat)}'s {_count(force.count, force.unit)}"
    if force.damaged:
        words += f" ({force.damaged} damaged)"
    return words


def _target_words(battle: BattleState, target: str) -> str:
    if target in BASE_CARDS:
        side = "left" if target == BASE_CARDS[0] else "right"
        return f"{tokens.seat(battle.defender)}'s {side} base card"
    return force_words(battle.force(target))


def _signed(value: int) -> str:
    return f"+{value}" if value >= 0 else f"−{-value}"


def _seat_forces(battle: BattleState, seat: str) -> str:
    found = [_count(force.count, force.unit) for force in battle.living(seat)]
    return ", ".join(found) if found else "nothing"


def _waiting(engine: "RulesEngine", match: "MatchState", result: StepResult) -> StepResult:
    """Every step ends here: the battle moved as far as nobody's answer
    is needed, and `next` is the one reading's."""
    from tnp.prompts import pending

    _settle(engine, match.battle)
    result.next = pending(engine, None, match)
    return result


# -- Opening a battle ------------------------------------------------------------


def begin_battle(
    engine: "RulesEngine",
    match: "MatchState",
    territory: str,
    forces: Mapping[str, Mapping[str, int]],
    *,
    attacker: Optional[str] = None,
    contested: bool = False,
    held_by: Optional[str] = None,
    paths_home: Optional[Mapping[str, bool]] = None,
    structures: Optional[Mapping[str, list]] = None,
    emergency: Optional[Mapping] = None,
    modifiers: tuple = (),
    damaged: Optional[Mapping[str, Mapping[str, int]]] = None,
) -> StepResult:
    """
    Open a battle over `territory` between the units each seat revealed
    there (TNP 6.1): `forces[seat]` is unit slug to count, formed into one
    force a kind. `attacker` names the attacking seat, except where both
    seats attacked a neutral territory (`contested`), when TNP 6.1 decides
    who is which. A base's battle is attacked by the other seat, and
    carries the defender's `structures` (its built facilities and
    upgrades) and `emergency` (its pool and supply room).

    The caller is the March (step 4), which has already applied the
    deployment rules; what this refuses (`RuleRefusal`) is a battle the
    rules could not have produced.
    """
    catalog = engine.catalog
    if territory not in catalog.areas:
        raise RuleRefusal(f"There is no area {territory!r} on the map.", cite="TNP 2.1")
    area = catalog.areas[territory]
    battle = BattleState(territory=territory, contested=contested, held_by=held_by)
    for seat in SEATS:
        for slug in catalog.units:
            count = int((forces.get(seat) or {}).get(slug, 0))
            if count < 0:
                raise RuleRefusal("A force cannot have fewer than no units.", cite="TNP 6.1")
            if count:
                hurt = int(((damaged or {}).get(seat) or {}).get(slug, 0))
                if hurt and not engine.has_trait(slug, "tough"):
                    raise RuleRefusal("Only a Tough unit carries damage.", cite="TNP 6.8")
                battle.forces.append(Force(seat, slug, count, min(hurt, count)))
        unknown = set(forces.get(seat) or {}) - set(catalog.units)
        if unknown:
            raise RuleRefusal(f"No unit is called {sorted(unknown)[0]!r}.", cite="TNP 2.3")
    if area.is_base:
        if contested:
            raise RuleRefusal("Nobody attacks a base they share.", cite="TNP 6.1")
        battle.defender = area.seat
        battle.attacker = other(area.seat)
        battle.held_by = None
        battle.structures = {
            "facilities": list((structures or {}).get("facilities", [])),
            "upgrades": list((structures or {}).get("upgrades", [])),
        }
        battle.emergency = {
            "pool": dict((emergency or {}).get("pool", {})),
            "supply_room": dict((emergency or {}).get("supply_room", {})),
        }
    elif contested:
        if held_by is not None:
            raise RuleRefusal("Only a neutral territory is attacked by both seats.", cite="TNP 6.1")
        if not all(battle.living(seat) for seat in SEATS):
            raise RuleRefusal("Both seats attack a contested territory.", cite="TNP 6.1")
    else:
        if attacker not in SEATS:
            raise RuleRefusal("A battle needs an attacker.", cite="TNP 6.1")
        battle.attacker, battle.defender = attacker, other(attacker)
        if held_by is not None and held_by != battle.defender:
            raise RuleRefusal("A seat does not attack its own territory in a battle.", cite="TNP 6.1")
    for found in battle.living():
        if engine.has_trait(found.unit, "base_defense") and not (
            area.is_base and found.seat == battle.defender
        ):
            raise RuleRefusal(
                "Base Defense units go only in the base defense spot.", cite="TNP 7",
            )
    if battle.attacker is not None and not battle.living(battle.attacker):
        raise RuleRefusal("An attack needs units.", cite="TNP 5.4")
    battle.paths_home = {seat: bool((paths_home or {}).get(seat, False)) for seat in SEATS}
    battle.modifiers = [dict(row) for row in modifiers]
    match.battle = battle

    result = StepResult(board_changed=True)
    if contested:
        result.narration.append(
            f"{tokens.seat(SEATS[0])} and {tokens.seat(SEATS[1])} both attack "
            f"{tokens.area(territory)}."
        )
        for seat in SEATS:
            result.narration.append(f"{tokens.seat(seat)} reveals {_seat_forces(battle, seat)}.")
        _contested_sides(engine, battle, result)
    else:
        result.narration.append(
            f"{tokens.seat(battle.attacker)} attacks {tokens.area(territory)} with "
            f"{_seat_forces(battle, battle.attacker)}."
        )
        result.narration.append(
            f"{tokens.seat(battle.defender)} defends with {_seat_forces(battle, battle.defender)}."
        )
        _after_sides(engine, battle, result)
    return _waiting(engine, match, result)


def _contested_sides(engine: "RulesEngine", battle: BattleState, result: StepResult) -> None:
    """
    Both seats attacked a neutral territory (TNP 6.1): the seat with the
    scouting advantage chooses its side; with none, the lower initiative
    total defends, and equal totals are settled by a die each, the higher
    roll attacking, equal rolls rolled again.
    """
    advantage = scouting_advantage(engine, battle)
    if advantage is not None:
        battle.phase = ROLE
        result.narration.append(
            f"{tokens.seat(advantage['seat'])} has the scouting advantage and chooses "
            "whether to attack or defend."
        )
        return
    totals = initiative_totals(engine, battle)
    blue, green = (totals[seat] for seat in SEATS)
    if blue != green:
        defender = SEATS[0] if blue < green else SEATS[1]
        result.narration.append(
            f"{tokens.seat(defender)} has the lower initiative ({min(blue, green)} to "
            f"{max(blue, green)}) and defends."
        )
    else:
        while True:
            rolled = {seat: engine.d12() for seat in SEATS}
            result.narration.append(
                f"Initiative tied at {blue}: {tokens.seat(SEATS[0])} rolls {rolled[SEATS[0]]}, "
                f"{tokens.seat(SEATS[1])} rolls {rolled[SEATS[1]]}."
            )
            if rolled[SEATS[0]] != rolled[SEATS[1]]:
                break
        defender = SEATS[0] if rolled[SEATS[0]] < rolled[SEATS[1]] else SEATS[1]
        result.narration.append(f"{tokens.seat(other(defender))} attacks.")
    battle.defender, battle.attacker = defender, other(defender)
    _after_sides(engine, battle, result)


def _after_sides(engine: "RulesEngine", battle: BattleState, result: StepResult) -> None:
    """The sides are known: a base's emergency defense (TNP 6.2), where
    its defender can produce anything, then the rounds."""
    if is_base(engine, battle) and emergency_possible(engine, battle):
        battle.phase = EMERGENCY
        return
    _open_rounds(engine, battle, result)


def _open_rounds(engine: "RulesEngine", battle: BattleState, result: StepResult) -> None:
    """
    A seat with no units in the battle has lost it (TNP 6.1): an attack
    on a held territory, or a base, with nobody defending it wins at
    once. Otherwise the first round begins (TNP 6.4). Tactical Command
    (TNP 6.3) is step 9's.
    """
    if not battle.living(battle.defender):
        result.narration.append(f"Nobody defends {tokens.area(battle.territory)}.")
        finish(engine, battle, result, battle.attacker, "undefended")
        return
    battle.round = 1
    battle.phase = ROUND


# -- Who is which, contested -----------------------------------------------------


def answer_role(engine: "RulesEngine", match: "MatchState", choice: str) -> StepResult:
    battle = match.battle
    chooser = scouting_advantage(engine, battle)["seat"]
    if choice == "attack":
        battle.attacker, battle.defender = chooser, other(chooser)
    else:
        battle.attacker, battle.defender = other(chooser), chooser
    result = StepResult(board_changed=True)
    result.narration.append(f"{tokens.seat(chooser)} chooses to {choice}.")
    _after_sides(engine, battle, result)
    return _waiting(engine, match, result)


# -- The emergency base defense --------------------------------------------------


TRADES = ("blue", "orange", "gems_materials", "gems_gold")


def _pool(battle: BattleState) -> dict[str, int]:
    pool = (battle.emergency or {}).get("pool", {})
    return {key: int(pool.get(key, 0)) for key in ("materials", "gold", "blue", "orange", "gems")}


def _affordable(pool: Mapping[str, int], materials: int, gold: int) -> bool:
    """Whether a cost can be paid from the pool at the emergency rates
    (TNP 6.2): a mineral 1 material, a gem 1 material or 1 gold."""
    gold_short = max(0, gold - pool["gold"])
    if gold_short > pool["gems"]:
        return False
    materials_short = max(0, materials - pool["materials"] - pool["blue"] - pool["orange"])
    return materials_short <= pool["gems"] - gold_short


def emergency_possible(engine: "RulesEngine", battle: BattleState) -> bool:
    """Whether the defender of a base could produce one base defense
    unit now -- asked only where it could (TNP 6.2)."""
    most, together = emergency_limits(engine, battle)
    pool = _pool(battle)
    for slug, count in most.items():
        if count <= 0:
            continue
        if any(slug in units and room <= 0 for units, room in together):
            continue
        cost = engine.unit(slug).cost
        if _affordable(pool, cost.materials, cost.gold):
            return True
    return False


def answer_emergency(engine: "RulesEngine", match: "MatchState", choice: str,
                     units: Optional[Mapping[str, int]] = None,
                     trade: Optional[Mapping[str, int]] = None) -> StepResult:
    """
    The defender of a base spends its pool, trading minerals and gems at
    the emergency rates, on base defense units that join the battle at
    once (TNP 6.2): at most the Base Defenses' cap, within each unit's
    supply and the limit on Smart Mines and Rocket Launchers together, a
    Laser Cannon only with its upgrade.
    """
    battle = match.battle
    result = StepResult(board_changed=True)
    defender = battle.defender
    if choice == "none":
        result.narration.append(f"{tokens.seat(defender)} produces no emergency defenses.")
        _open_rounds(engine, battle, result)
        return _waiting(engine, match, result)
    units = {slug: int(count) for slug, count in (units or {}).items() if int(count)}
    trade = {key: int((trade or {}).get(key, 0)) for key in TRADES}
    unknown = set((trade or {})) - set(TRADES)
    if unknown:
        raise RuleRefusal(f"Nothing trades as {sorted(unknown)[0]!r}.", cite="TNP 6.2")
    if not units:
        raise RuleRefusal("Choose the units to produce, or produce none.", cite="TNP 6.2")
    if any(count < 0 for count in (*units.values(), *trade.values())):
        raise RuleRefusal("A count cannot be below none.", cite="TNP 6.2")
    most, together = emergency_limits(engine, battle)
    for slug, count in units.items():
        if slug not in most:
            raise RuleRefusal("Only base defenses are produced in an emergency.", cite="TNP 6.2")
        if count > most[slug]:
            raise RuleRefusal(
                f"At most {most[slug]} {tokens.unit(slug)} can be produced now.", cite="TNP 6.2",
            )
    cap = emergency_cap(engine, battle)
    if sum(units.values()) > cap:
        raise RuleRefusal(f"The Base Defenses produce at most {cap}.", cite="TNP 6.2")
    for limited, room in together:
        if sum(units.get(slug, 0) for slug in limited) > room:
            raise RuleRefusal(
                f"Only {room} more of " + " and ".join(tokens.unit(slug) for slug in limited)
                + " may be deployed.", cite="TNP 2.4",
            )
    pool = _pool(battle)
    if trade["blue"] > pool["blue"] or trade["orange"] > pool["orange"] \
            or trade["gems_materials"] + trade["gems_gold"] > pool["gems"]:
        raise RuleRefusal("That trades more tokens than the pool holds.", cite="TNP 6.2")
    rates = engine.catalog.board["conversion"]["emergency"]
    materials = pool["materials"] + (trade["blue"] + trade["orange"]) * rates["mineral"]["materials"] \
        + trade["gems_materials"] * rates["gem"]["materials"]
    gold = pool["gold"] + trade["gems_gold"] * rates["gem"]["gold"]
    cost_materials = sum(engine.unit(slug).cost.materials * count for slug, count in units.items())
    cost_gold = sum(engine.unit(slug).cost.gold * count for slug, count in units.items())
    if cost_materials > materials or cost_gold > gold:
        raise RuleRefusal("That trade does not pay for those units.", cite="TNP 6.2")
    battle.emergency["pool"] = {
        "materials": materials - cost_materials,
        "gold": gold - cost_gold,
        "blue": pool["blue"] - trade["blue"],
        "orange": pool["orange"] - trade["orange"],
        "gems": pool["gems"] - trade["gems_materials"] - trade["gems_gold"],
    }
    for slug, count in units.items():
        battle.produced[slug] = battle.produced.get(slug, 0) + count
        room = battle.emergency["supply_room"]
        room[slug] = int(room.get(slug, 0)) - count
        if battle.has_force(f"{defender}:{slug}"):
            battle.force(f"{defender}:{slug}").count += count
        else:
            battle.forces.append(Force(defender, slug, count))
    order = list(engine.catalog.units)
    battle.forces.sort(key=lambda found: (SEATS.index(found.seat), order.index(found.unit)))
    result.narration.append(
        f"{tokens.seat(defender)} produces emergency defenses: "
        + ", ".join(_count(count, slug) for slug, count in units.items()) + "."
    )
    _open_rounds(engine, battle, result)
    return _waiting(engine, match, result)


# -- The round's start -----------------------------------------------------------


def begin_round(engine: "RulesEngine", game, match: "MatchState", lead_in: str = "") -> StepResult:
    """
    A round begins (TNP 6.4, 6.5): after the first, every unengaged force
    in front is lifted out of the line to be placed again -- engaged pairs
    stay, and so do the flanking forces behind them, which each seat may
    then keep or take out (`answer_reposition`) -- the scouting advantage
    is counted, and the placing begins (`_start_placing`).
    """
    battle = match.battle
    result = StepResult(narration=[lead_in] if lead_in else [], board_changed=True)
    battle.reposition_asked = []
    if battle.round > 1:
        kept = []
        for column in battle.line:
            if len(column.front) == 2:
                kept.append(Column(
                    front=dict(column.front),
                    flank={seat: list(ids) for seat, ids in column.flank.items() if ids},
                ))
        battle.line = kept
    battle.retreats, battle.retreat_asked, battle.leaving = [], [], {}
    battle.group, battle.rolled = None, []
    battle.hits, battle.removals, battle.repairs_asked = {}, {}, False
    battle.advantage = scouting_advantage(engine, battle)
    words = f"Round {battle.round}."
    if battle.advantage is not None:
        words += (
            f" {tokens.seat(battle.advantage['seat'])} has the scouting advantage by "
            f"{battle.advantage['by']}."
        )
    result.narration.append(words)
    if reposition_asker(battle) is not None:
        battle.phase = REPOSITION
    else:
        _start_placing(battle)
    return _waiting(engine, match, result)


def _start_placing(battle: BattleState) -> None:
    """With an advantage of N the other seat places N forces first; with
    none the defender has the first turn (TNP 6.5; `answer_place` says
    what a turn is)."""
    if battle.advantage is not None:
        first, run = other(battle.advantage["seat"]), battle.advantage["by"]
    else:
        first, run = battle.defender, 0
    if not unplaced(battle, first):
        first, run = other(first), 0
    battle.to_place = first if unplaced(battle, first) else None
    battle.run_left = run
    battle.phase = PLACE


def answer_reposition(engine: "RulesEngine", match: "MatchState", choice: str,
                      forces: Optional[list] = None) -> StepResult:
    """A seat keeps its flanking forces where they stand, or takes the
    ones `forces` names out of the line to be placed again (TNP 6.5)."""
    battle = match.battle
    seat = reposition_asker(battle)
    result = StepResult()
    if choice == "move":
        chosen = list(dict.fromkeys(forces or []))
        if not chosen:
            raise RuleRefusal("Choose the flanking forces to reposition, or keep them.", cite="TNP 6.5")
        standing = flankers_of(battle, seat)
        if any(one not in standing for one in chosen):
            raise RuleRefusal("Only a flanking force of yours may be repositioned.", cite="TNP 6.5")
        for column in battle.line:
            if seat in column.flank:
                column.flank[seat] = [one for one in column.flank[seat] if one not in chosen]
        result.board_changed = True
        result.narration.append(
            f"{tokens.seat(seat)} repositions "
            + ", ".join(force_words(battle.force(one)) for one in chosen) + "."
        )
    battle.reposition_asked.append(seat)
    if reposition_asker(battle) is None:
        _start_placing(battle)
    return _waiting(engine, match, result)


# -- Placing a force -------------------------------------------------------------


def answer_place(engine: "RulesEngine", match: "MatchState", force: str, slot: str) -> StepResult:
    """
    One force into the line (TNP 6.5), where `slots` allows it, and who
    places next. The advantage's opening placements (`run_left`) are made
    one after another; then the seats take turns. **A turn** engages every
    unengaged force of the other seat it can, then puts down one new
    force for the other seat to engage, and ends there -- while the other
    seat has forces to place. Once it has none, the seat places the rest
    of its own, one after another.
    """
    battle = match.battle
    seat = battle.to_place
    choices = [found for found in unplaced(battle, seat) if found.id == force]
    if not choices:
        raise RuleRefusal("That force is not one still to place.", cite="TNP 6.5")
    chosen = choices[0]
    if slot not in slots(engine, battle, seat, chosen):
        raise RuleRefusal("That force cannot be placed there now.", cite="TNP 6.5")
    kind, _, where = slot.partition(":")
    index = int(where)
    result = StepResult(board_changed=True)
    if kind == ENGAGE:
        battle.line[index].front[seat] = chosen.id
        enemy = battle.force(battle.line[index].front[other(seat)])
        result.narration.append(f"{force_words(chosen)} engage {force_words(enemy)}.")
    elif kind == COLUMN:
        battle.line.insert(index, Column(front={seat: chosen.id}))
        result.narration.append(f"{force_words(chosen)} take their place in the line.")
    elif kind == FLANK:
        column = battle.line[index]
        column.flank.setdefault(seat, []).append(chosen.id)
        behind = battle.force(column.front[seat])
        result.narration.append(f"{force_words(chosen)} flank behind {force_words(behind)}.")
    mine, theirs = bool(unplaced(battle, seat)), bool(unplaced(battle, other(seat)))
    if battle.run_left > 0:
        battle.run_left -= 1
        turn_over = battle.run_left == 0
    else:
        turn_over = kind == COLUMN
    if not mine:
        battle.to_place, battle.run_left = (other(seat) if theirs else None), 0
    elif theirs and turn_over:
        battle.to_place, battle.run_left = other(seat), 0
    return _waiting(engine, match, result)


# -- Retreat ---------------------------------------------------------------------


def answer_retreat(engine: "RulesEngine", match: "MatchState", choice: str,
                   carried: Optional[Mapping[str, int]] = None) -> StepResult:
    """
    A seat declares a retreat or fights on (TNP 6.6). With a path home
    every unit of its retreats; with none, its air units do, and its
    Chopper Carriers take the ground units `carried` names, up to their
    capacity, one kind a carrier (TNP 7) -- the rest stay and fight. The
    retreating units do not attack this round, and leave at its end.
    """
    battle = match.battle
    seat = retreat_asker(engine, battle)
    result = StepResult()
    if choice != "retreat":
        battle.retreat_asked.append(seat)
        result.narration.append(f"{tokens.seat(seat)} fights on.")
        return _waiting(engine, match, result)
    carried = {ident: int(count) for ident, count in (carried or {}).items() if int(count)}
    leaving: dict[str, int] = {}
    if battle.paths_home.get(seat, False):
        if carried:
            raise RuleRefusal("With a path home every unit retreats; nothing is carried.",
                              cite="TNP 6.6")
        leaving = {found.id: found.count for found in battle.living(seat)}
    else:
        room = carriable(engine, battle, seat)
        for ident, count in carried.items():
            if ident not in room:
                raise RuleRefusal("A Chopper Carrier cannot carry that.", cite="TNP 7")
            if count < 0 or count > battle.force(ident).count:
                raise RuleRefusal("There are not that many to carry.", cite="TNP 7")
        if carriers_needed(engine, battle, carried) > sum(carriers(engine, battle, seat).values()):
            raise RuleRefusal(
                "That is more than the Chopper Carriers hold, one kind of unit a carrier.",
                cite="TNP 7",
            )
        for found in battle.living(seat):
            if engine.unit(found.unit).type is UnitType.AIR:
                leaving[found.id] = found.count
        leaving.update(carried)
    battle.retreat_asked.append(seat)
    battle.retreats.append(seat)
    battle.leaving = leaving
    result.board_changed = True
    staying = [
        _count(found.count - leaving.get(found.id, 0), found.unit)
        for found in battle.living(seat) if found.count > leaving.get(found.id, 0)
    ]
    if not staying:
        result.narration.append(f"{tokens.seat(seat)} declares a retreat.")
    else:
        going = ", ".join(_count(count, battle.force(ident).unit) for ident, count in leaving.items())
        result.narration.append(
            f"{tokens.seat(seat)} retreats {going}; {', '.join(staying)} stay and fight."
        )
    return _waiting(engine, match, result)


# -- Damage ----------------------------------------------------------------------


def answer_target(engine: "RulesEngine", match: "MatchState", force: str, target: str) -> StepResult:
    """
    A force's seat chooses its target, and the force rolls at once
    (TNP 6.7, decision 8): a die a unit, or one for every two if Poor,
    each the number rolled plus every modifier against the rating's
    number. The hits are held until the whole group has rolled. A Splash
    force that hits may take an adjacent infantry unit too, and a force's
    2 hits on a base card destroy one thing (TNP 6.8, 6.9) -- each asked
    before the next roll.
    """
    battle = match.battle
    seat = roller(engine, battle)
    if force not in rollers(engine, battle, seat):
        raise RuleRefusal("That force is not one still to roll in this group.", cite="TNP 6.7")
    if target not in aimed(engine, battle, force):
        raise RuleRefusal("That force cannot attack that.", cite="TNP 6.7")
    shooter = battle.force(force)
    against = target_type(engine, battle, target)
    rating = engine.rating(shooter.unit, against)
    count = dice(engine, battle, force, target)
    bonus = modifier(engine, battle, force, target)
    rolled = tuple(engine.d12() for _ in range(count))
    hit = sum(1 for die in rolled if engine.hits(die, bonus, rating))
    battle.rolled.append(force)
    result = StepResult(board_changed=bool(hit))
    result.rolls.append(Roll(seat, force, target, rolled, bonus, rating.target, hit))
    shown = ", ".join(str(die) for die in rolled) if rolled else "no dice"
    words = (
        f"{force_words(shooter)} fire at {_target_words(battle, target)}: {shown}, "
        f"needing {rating.shown}"
    )
    if bonus:
        words += f" at {_signed(bonus)}"
    words += f" — {hit} hit{'' if hit == 1 else 's'}."
    result.narration.append(words)
    if target in BASE_CARDS:
        if hit >= BASE_CARD_HITS:
            things = destroyable(engine, battle)
            if len(things) == 1:
                _destroy(battle, things[0], result)
            elif things:
                battle.owed.append({"kind": "destroy", "seat": seat, "force": force})
    elif hit:
        battle.hits[target] = battle.hits.get(target, 0) + hit
        if engine.has_trait(shooter.unit, "splash") and splash_targets(engine, battle, target):
            battle.owed.append({"kind": "splash", "seat": seat, "force": force, "hit": target})
    return _waiting(engine, match, result)


def _destroy(battle: BattleState, thing: str, result: StepResult) -> None:
    battle.destroyed = thing
    for key in ("upgrades", "facilities"):
        if thing in battle.structures.get(key, []):
            battle.structures[key].remove(thing)
    result.narration.append(f"{tokens.seat(battle.defender)}'s {tokens.thing(thing)} is destroyed.")
    result.board_changed = True


def answer_destroy(engine: "RulesEngine", match: "MatchState", thing: str) -> StepResult:
    """The attacker's choice of what the base card's hits destroy (TNP 6.9)."""
    battle = match.battle
    if thing not in destroyable(engine, battle):
        raise RuleRefusal(
            "That cannot be destroyed: an upgrade goes before its facility, and the "
            "Barracks and Base Defenses never.", cite="TNP 6.9",
        )
    battle.owed.pop(0)
    result = StepResult()
    _destroy(battle, thing, result)
    return _waiting(engine, match, result)


def answer_splash(engine: "RulesEngine", match: "MatchState", choice: str,
                  force: Optional[str] = None) -> StepResult:
    """A Splash force's seat takes one infantry unit from a force beside
    the one it hit, or does not (TNP 6.8)."""
    battle = match.battle
    owed = battle.owed[0]
    result = StepResult()
    if choice == "splash":
        if force not in splash_targets(engine, battle, owed["hit"]):
            raise RuleRefusal("Splash takes an infantry unit from a force beside the one hit.",
                              cite="TNP 6.8")
        battle.removals[force] = battle.removals.get(force, 0) + 1
        result.narration.append(
            f"{force_words(battle.force(owed['force']))} splash {force_words(battle.force(force))}."
        )
        result.board_changed = True
    battle.owed.pop(0)
    return _waiting(engine, match, result)


def answer_repair(engine: "RulesEngine", match: "MatchState", choice: str,
                  workers: Optional[Mapping[str, int]] = None) -> StepResult:
    """A Mechanical force's seat gives Workers from forces beside it, one
    a hit ignored (TNP 6.8), or does not."""
    battle = match.battle
    owed = battle.owed[0]
    hit = owed["force"]
    result = StepResult()
    if choice == "repair":
        given = {one: int(count) for one, count in (workers or {}).items() if int(count)}
        offered = dict(repair_workers(engine, battle, hit))
        if not given:
            raise RuleRefusal("Choose the Workers to give, or decline.", cite="TNP 6.8")
        for one, count in given.items():
            if one not in offered or count < 0 or count > offered[one]:
                raise RuleRefusal("Those Workers are not beside the force hit.", cite="TNP 6.8")
        total = sum(given.values())
        if total > battle.hits.get(hit, 0):
            raise RuleRefusal("Each Worker ignores one hit, and no more are given than hits.",
                              cite="TNP 6.8")
        battle.hits[hit] -= total
        for one, count in given.items():
            battle.removals[one] = battle.removals.get(one, 0) + count
        result.narration.append(
            f"{tokens.seat(battle.force(hit).seat)} gives {total} {tokens.unit('worker')} "
            f"to repair {force_words(battle.force(hit))}, ignoring {total} "
            f"hit{'' if total == 1 else 's'}."
        )
        result.board_changed = True
    battle.owed.pop(0)
    return _waiting(engine, match, result)


def close_group(engine: "RulesEngine", game, match: "MatchState", lead_in: str = "") -> StepResult:
    """
    The whole group has rolled (TNP 6.7): first each hit Mechanical
    force with Workers beside it is asked whether to repair (TNP 6.8),
    the attacker's first; then the losses come off together -- a damaged
    Tough unit before an undamaged one, a Tough unit damaged before it is
    removed, the units Splash and Repair took removed outright -- and the
    next group rolls.
    """
    battle = match.battle
    result = StepResult(narration=[lead_in] if lead_in else [])
    if not battle.repairs_asked:
        battle.repairs_asked = True
        for seat in (battle.attacker, battle.defender):
            for force in battle.living(seat):
                if battle.hits.get(force.id, 0) <= 0:
                    continue
                if engine.has_trait(force.unit, "mechanical") and repair_workers(engine, battle, force.id):
                    battle.owed.append({"kind": "repair", "seat": seat, "force": force.id})
        if battle.owed:
            return _waiting(engine, match, result)
    lost = []
    for force in list(battle.forces):
        before, hurt = force.count, force.damaged
        for _ in range(battle.hits.get(force.id, 0)):
            if force.count <= 0:
                break
            if force.damaged:
                force.damaged -= 1
                force.count -= 1
            elif engine.has_trait(force.unit, "tough"):
                force.damaged += 1
            else:
                force.count -= 1
        for _ in range(battle.removals.get(force.id, 0)):
            if force.count <= 0:
                break
            if force.damaged:
                force.damaged -= 1
            force.count -= 1
        if force.count < before or force.damaged > hurt:
            gone = before - force.count
            words = f"{tokens.seat(force.seat)} loses {_count(gone, force.unit)}" if gone else ""
            if force.damaged > hurt and force.count:
                fresh = force.damaged - hurt
                damage = f"{fresh} {tokens.unit(force.unit)} damaged"
                words = f"{words}, and {damage}" if words else f"{tokens.seat(force.seat)}: {damage}"
            lost.append(words + ".")
    if lost:
        result.narration.extend(lost)
        result.board_changed = True
    _clear_the_dead(battle)
    finished = battle.group
    battle.hits, battle.removals, battle.rolled, battle.repairs_asked = {}, {}, [], False
    later = [value for value in groups(engine, battle) if value > finished]
    if later:
        battle.group = later[0]
        battle.phase = DAMAGE
    else:
        battle.group = None
        battle.phase = ROUND_END
    return _waiting(engine, match, result)


def _clear_the_dead(battle: BattleState) -> None:
    """Every force with no units left taken out of the line, and every
    column with nobody left in it."""
    for column in list(battle.line):
        for seat, ident in list(column.front.items()):
            if battle.force(ident).count <= 0:
                del column.front[seat]
        for seat in SEATS:
            if seat in column.flank:
                column.flank[seat] = [one for one in column.flank[seat] if battle.force(one).count > 0]
        if not column.everyone():
            battle.line.remove(column)


# -- The round's end -------------------------------------------------------------


def _withdraw(battle: BattleState, result: StepResult) -> None:
    """
    The units retreating this round leave for their base (TNP 6.6).
    Where a carry splits a force, its losses this round came off the
    units staying, and its damaged units stay first.
    """
    for ident, count in battle.leaving.items():
        force = battle.force(ident)
        going = min(count, force.count)
        if going <= 0:
            continue
        hurt = max(0, force.damaged - (force.count - going))
        force.count -= going
        force.damaged -= hurt
        home = battle.withdrawn.setdefault(force.seat, {}).setdefault(force.unit, {"count": 0, "damaged": 0})
        home["count"] += going
        home["damaged"] += hurt
    if battle.leaving:
        result.board_changed = True
    battle.leaving = {}
    _clear_the_dead(battle)


def end_round(engine: "RulesEngine", game, match: "MatchState", lead_in: str = "") -> StepResult:
    """
    The round ends (TNP 6.10): the retreating units leave; a seat that
    retreated every unit it had has lost; a seat with no units left has
    lost -- and neither having any is nobody's battle; otherwise the
    round track moves up, and after the sixth the defender wins if it
    still has units, whatever the base cards took.
    """
    battle = match.battle
    result = StepResult(narration=[lead_in] if lead_in else [])
    retreated = list(battle.retreats)
    _withdraw(battle, result)
    attacking, defending = bool(battle.living(battle.attacker)), bool(battle.living(battle.defender))
    gone = [seat for seat in retreated if not battle.living(seat)]
    if gone and battle.living(other(gone[0])):
        finish(engine, battle, result, other(gone[0]), "retreat")
    elif not attacking and not defending:
        finish(engine, battle, result, None, "destroyed")
    elif not defending:
        finish(engine, battle, result, battle.attacker, "destroyed")
    elif not attacking:
        finish(engine, battle, result, battle.defender, "destroyed")
    elif battle.round >= ROUNDS:
        result.narration.append(f"{tokens.seat(battle.defender)} holds for {ROUNDS} rounds.")
        finish(engine, battle, result, battle.defender, "held")
    else:
        battle.round += 1
        battle.phase = ROUND
    return _waiting(engine, match, result)


def finish(engine: "RulesEngine", battle: BattleState, result: StepResult,
           winner: Optional[str], by: str) -> None:
    """
    The battle is over (TNP 6.10, 6.11), and `outcome` says how, for the
    March to put on the map:

    - `winner`, `None` where both sides were destroyed together;
    - `control`, who holds the territory now: the winner where it has a
      ground unit left; where it has only air units left, the defender
      keeps a territory it held, and otherwise it is neutral; unchanged
      where nobody won;
    - `base_fallen`, for an attack on a base that won, which wins the
      game (TNP 1.3);
    - `survivors` by seat and unit, with their damage; `withdrawn`, the
      units that retreated home during the battle (TNP 6.6); and `home`,
      the seats whose survivors go back to their base -- the losing
      side's units left when the defender holds (TNP 6.11).
    """
    survivors = {
        seat: {
            found.unit: {"count": found.count, "damaged": found.damaged}
            for found in battle.living(seat)
        }
        for seat in SEATS
    }
    if winner is None:
        control = battle.held_by
    elif any(engine.unit(found.unit).type is not UnitType.AIR for found in battle.living(winner)):
        control = winner
    elif winner == battle.held_by:
        control = winner
    else:
        control = None
    base = is_base(engine, battle)
    if base:
        control = None
    loser = None if winner is None else other(winner)
    home = [loser] if loser is not None and battle.living(loser) else []
    battle.outcome = {
        "winner": winner,
        "by": by,
        "control": control,
        "base_fallen": base and winner == battle.attacker,
        "destroyed": battle.destroyed,
        "survivors": survivors,
        "withdrawn": {seat: dict(units) for seat, units in battle.withdrawn.items()},
        "home": home,
    }
    battle.phase = OVER
    battle.owed = []
    result.board_changed = True
    if winner is None:
        result.narration.append(
            f"Both sides are destroyed at {tokens.area(battle.territory)}; nobody wins the battle."
        )
    elif base and winner == battle.attacker:
        result.narration.append(
            f"{tokens.seat(winner)} wins the battle, and {tokens.area(battle.territory)} falls."
        )
    else:
        result.narration.append(f"{tokens.seat(winner)} wins the battle for {tokens.area(battle.territory)}.")
        if not base and control is None and winner == battle.attacker:
            result.narration.append(
                f"Air units cannot take a territory: {tokens.area(battle.territory)} is neutral."
            )
    if home:
        result.narration.append(f"{tokens.seat(home[0])}'s survivors go back to their base.")


# -- Moving on where nobody is asked ---------------------------------------------


def _settle(engine: "RulesEngine", battle: Optional[BattleState]) -> None:
    """
    Move the battle past every point that asks nobody: the placing done,
    the retreats asked, the group's rollers done. It stops at a question
    or at a step the bot owes (`tnp.prompts.pending` reads which).
    """
    while battle is not None and battle.outcome is None and not battle.owed:
        if battle.phase == PLACE:
            if battle.to_place is not None:
                return
            battle.phase = RETREAT
            battle.retreat_asked = []
            continue
        if battle.phase == RETREAT:
            if retreat_asker(engine, battle) is not None:
                return
            found = groups(engine, battle)
            battle.group = found[0] if found else None
            battle.rolled, battle.hits, battle.removals = [], {}, {}
            battle.repairs_asked = False
            battle.phase = DAMAGE if found else ROUND_END
            continue
        if battle.phase == DAMAGE:
            if roller(engine, battle) is None:
                battle.phase = LOSSES
            return
        return


__all__ = [
    "answer_destroy", "answer_emergency", "answer_place", "answer_repair", "answer_reposition",
    "answer_retreat",
    "answer_role", "answer_splash", "answer_target", "begin_battle", "begin_round",
    "close_group", "emergency_possible", "end_round", "finish", "force_words",
]
