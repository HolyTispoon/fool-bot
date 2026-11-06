"""
The turn's steps (docs/tnp-rules.md, 5), with no Discord in them: each
seat's plan and its lock-in, the reveal once both have locked in, March
attack by attack -- neutral conquest, battle through `tnp.flow.battle`,
control and stranded, harvest -- production, each seat's trade, and
Cleanup with the 51% check. Each mutates the match and says what
happened in the model's voice with tokens; none sends or saves
anything. `tnp.prompts.pending_all` is the one reading of what the
match waits on, and every step ends by asking it.

**A simultaneous phase** is Infrastructure and Deployment, and
Production and Trade's trade: both seats are asked at once, each answer
is that seat's plan, held on its `SeatState` and changed as often as it
likes until it locks in, and the phase moves on -- an owed step -- once
both have. Nothing a seat plans is said in public until the phase that
reveals it: a lock-in says only that the seat has locked in, and the
reveal says what was paid, never what for (TNP 5.2, 5.3).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Mapping, Optional

from tnp import tokens
from tnp.battle import SEATS, other
from tnp.components import (
    ATTACK_SPOTS,
    CLEANUP,
    HARVEST_TO_WIN,
    MARCH,
    OVER,
    PLAN,
    PRODUCTION,
    RESOURCES,
    TRADE,
    WON_BY_BASE,
    WON_BY_HARVEST,
    MatchState,
)
from tnp.flow import battle as fight
from tnp.flow.result import StepResult
from tnp.game import RuleRefusal
from tnp.turn import (
    area_order,
    base_of,
    check_plan,
    check_trade,
    deployed,
    ground_units,
    has_path,
    joined,
    normal_plan,
    normal_trade,
    plan_cost,
    reaches,
    supply_room,
    trade_gains,
)

if TYPE_CHECKING:
    from tnp.engine import RulesEngine


# -- Words -----------------------------------------------------------------------

RESOURCE_WORDS = {
    "blue_minerals": ("blue mineral", "blue minerals"),
    "orange_minerals": ("orange mineral", "orange minerals"),
    "gems": ("gem", "gems"),
}

#: The battle's pool keys for the pool's minerals (`tnp.battle`'s
#: emergency pool says "blue", "orange", "gems").
BATTLE_POOL = {"blue_minerals": "blue", "orange_minerals": "orange", "gems": "gems"}


def _tokens_words(counts: Mapping[str, int]) -> str:
    found = []
    for kind in RESOURCES:
        count = counts.get(kind, 0)
        if count:
            one, many = RESOURCE_WORDS[kind]
            found.append(f"{count} {one if count == 1 else many}")
    return ", ".join(found) if found else "nothing"


def _amount(count: int, one: str) -> str:
    """"1 material", "2 materials", "1 gold"."""
    return f"{count} {one}" if count == 1 or one == "gold" else f"{count} {one}s"


def _spent(materials: int, gold: int) -> str:
    found = [_amount(materials, "material")] if materials else []
    if gold:
        found.append(_amount(gold, "gold"))
    return " and ".join(found)


def _units_words(units: Mapping[str, int]) -> str:
    found = [f"{count} {tokens.unit(slug)}" for slug, count in units.items() if count]
    return ", ".join(found) if found else "nothing"


def _waiting(engine: "RulesEngine", game, match: MatchState, result: StepResult) -> StepResult:
    """Every step ends here: `next` is the step the bot owes, or the one
    question asked -- `None` where both seats are asked at once, which a
    frontend lists with `tnp.prompts.pending_prompts`."""
    from tnp.prompts import PendingPrompt, pending_all

    everything = pending_all(engine, game, match)
    prompts = [one for one in everything if isinstance(one, PendingPrompt)]
    if everything and not prompts:
        result.next = everything[0]
    elif len(prompts) == 1:
        result.next = prompts[0]
    else:
        result.next = None
    return result


# -- Infrastructure and Deployment -------------------------------------------------


def answer_plan(engine: "RulesEngine", game, match: MatchState, seat: str, choice: str,
                plan: Optional[Mapping] = None) -> StepResult:
    """
    A seat's Infrastructure and Deployment (TNP 5.2, 5.3): `save` keeps
    the plan, which the seat may change until it locks in; `lock` locks
    in the plan given, or the one saved. Every plan is checked as it is
    saved, so a locked plan is always one the rules allow. A save says
    nothing in public, and a lock-in only that the seat has locked in.
    """
    state = match.seat(seat)
    if plan is None and choice == "save":
        raise RuleRefusal("Saving a plan needs the plan.", cite="TNP 5.2")
    normal = normal_plan(plan if plan is not None else state.plan)
    check_plan(engine, match, seat, normal)
    state.plan = normal
    result = StepResult()
    if choice == "lock":
        state.locked = True
        result.narration.append(f"{tokens.seat(seat)} locks in.")
        result.board_changed = True
    return _waiting(engine, game, match, result)


def reveal(engine: "RulesEngine", game, match: MatchState, lead_in: str = "") -> StepResult:
    """
    Both seats have locked in: each pays for its Infrastructure, its
    queue goes onto its facilities to be finished at Production and
    Trade, and its units go face down into their spots (TNP 5.2, 5.3).
    March opens. What each seat paid is said -- the pool is open
    information (TNP 2.2) -- and nothing of what for.
    """
    result = StepResult(narration=[lead_in] if lead_in else [], board_changed=True)
    result.narration.append("Both seats have locked in.")
    for seat in SEATS:
        state = match.seat(seat)
        plan = normal_plan(state.plan)
        cost = plan_cost(engine, plan)
        state.pool["materials"] = state.pool.get("materials", 0) - cost.materials
        state.pool["gold"] = state.pool.get("gold", 0) - cost.gold
        state.queued_units = dict(plan["build"])
        state.queued = list(plan["structures"])
        for slug, count in deployed(plan).items():
            state.available[slug] -= count
            if not state.available[slug]:
                del state.available[slug]
        for area, units in plan["defense"].items():
            match.pile(area, seat).add(units)
        match.attacks[seat] = {
            spot: {"target": attack["target"], "units": dict(attack["units"])}
            for spot, attack in plan["attacks"].items()
        }
        state.plan, state.locked = None, False
        if cost.materials or cost.gold:
            result.narration.append(f"{tokens.seat(seat)} spends {_spent(cost.materials, cost.gold)}.")
    match.revealed = []
    match.phase = MARCH
    result.narration.append("March begins.")
    return _waiting(engine, game, match, result)


# -- March -------------------------------------------------------------------------


def next_attack(match: MatchState) -> Optional[tuple[str, str]]:
    """
    The attack March resolves next (TNP 5.4): attack spot A for both
    seats, then B, then C; within a spot, in ascending territory number,
    a base after every territory. Two seats' piles aimed at one area in
    the same spot are one attack.
    """
    for spot in ATTACK_SPOTS:
        areas = {
            attack["target"]
            for seat in SEATS
            for name, attack in match.attacks.get(seat, {}).items() if name == spot
        }
        if areas:
            return spot, min(areas, key=area_order)
    return None


def _reveal(match: MatchState, seat: str, area: str, spot: str, units: Mapping[str, int]) -> None:
    """What March has shown in public, for the map (`tnp.briefs.Pile`)."""
    if any(units.values()):
        match.revealed.append({
            "seat": seat, "area": area, "spot": spot,
            "units": {slug: int(count) for slug, count in units.items() if count},
        })


def march(engine: "RulesEngine", game, match: MatchState, lead_in: str = "") -> StepResult:
    """
    Resolve the next attack (TNP 5.4 to 5.8), or, with none left, end
    March and open Production and Trade. A pile that cannot reach the
    area it attacks -- no path of held territories, and ground units its
    Chopper Carriers cannot carry -- sends its ground units back to its
    base unrevealed, and its air units, where it has any, attack alone,
    as they must (TNP 5.3, the author, 2026-11-06).
    """
    result = StepResult(narration=[lead_in] if lead_in else [])
    found = next_attack(match)
    if found is None:
        result.narration.append("March is over.")
        match.attacks = {}
        match.phase = PRODUCTION
        result.board_changed = True
        return _waiting(engine, game, match, result)
    spot, area = found
    result.part = spot
    piles: dict[str, dict[str, int]] = {}
    for seat in SEATS:
        attack = match.attacks.get(seat, {}).get(spot)
        if attack is not None and attack["target"] == area:
            del match.attacks[seat][spot]
            piles[seat] = dict(attack["units"])
    for seat in list(piles):
        if reaches(engine, match, seat, area, piles[seat]):
            continue
        ground = ground_units(engine, piles[seat])
        air = {slug: count for slug, count in piles[seat].items() if count and slug not in ground}
        _home(match, seat, ground)
        if air:
            piles[seat] = air
            result.narration.append(
                f"{tokens.seat(seat)}'s attack {spot} has no path to {tokens.area(area)}: what "
                "cannot fly goes back to its base unrevealed, and its air units attack alone."
            )
        else:
            del piles[seat]
            result.narration.append(
                f"{tokens.seat(seat)}'s attack {spot} cannot reach {tokens.area(area)}: it has no "
                "path of held territories there, and its units go back to its base."
            )
    if not piles:
        return _waiting(engine, game, match, result)
    match.resolving = {"spot": spot, "area": area, "piles": piles}
    _resolve(engine, game, match, result)
    return _waiting(engine, game, match, result)


def _home(match: MatchState, seat: str, units: Mapping[str, int]) -> None:
    """Units back at their base, available."""
    available = match.seat(seat).available
    for slug, count in units.items():
        if count:
            available[slug] = available.get(slug, 0) + int(count)


def _resolve(engine: "RulesEngine", game, match: MatchState, result: StepResult) -> None:
    """The attack in `match.resolving`: a battle, a neutral conquest, a
    harvest of a territory the seat holds, or nothing to take."""
    resolving = match.resolving
    spot, area, piles = resolving["spot"], resolving["area"], resolving["piles"]
    is_base = engine.catalog.areas[area].is_base
    holder = match.controller(area)
    standing = {seat: match.standing(area, seat) for seat in SEATS}

    if len(piles) == 2:
        if holder is None:
            _open_battle(engine, match, result, contested=True)
        else:
            _open_battle(engine, match, result, attacker=other(holder))
        return
    (seat,) = piles
    if is_base or holder == other(seat) or standing[other(seat)] is not None:
        _open_battle(engine, match, result, attacker=seat)
        return
    pile = match.pile(area, seat)
    pile.add(piles[seat])
    if holder == seat:
        result.narration.append(
            f"{tokens.seat(seat)}'s attack {spot} reaches {tokens.area(area)}, which it holds."
        )
        _harvest(engine, match, seat, area, piles[seat].get("worker", 0), result)
        _done_unless_harvesting(match)
        return
    ground = ground_units(engine, piles[seat])
    if not ground:
        result.narration.append(
            f"{tokens.seat(seat)}'s attack {spot} reaches {tokens.area(area)} with air units "
            "alone, which cannot take a territory."
        )
        match.resolving = None
        return
    if len(ground) == 1:
        _conquer(engine, match, seat, next(iter(ground)), result)
        return
    resolving["stage"] = "conquer"


def _conquer(engine: "RulesEngine", match: MatchState, seat: str, unit: str,
             result: StepResult) -> None:
    """A neutral territory taken by revealing one ground unit (TNP 5.5),
    then harvested (TNP 5.8)."""
    resolving = match.resolving
    area, spot = resolving["area"], resolving["spot"]
    result.narration.append(
        f"{tokens.seat(seat)} reveals a {tokens.unit(unit)} in attack {spot} and takes "
        f"{tokens.area(area)}."
    )
    _reveal(match, seat, area, spot, {unit: 1})
    _set_control(engine, match, area, seat, result)
    _harvest(engine, match, seat, area, resolving["piles"][seat].get("worker", 0), result)
    _done_unless_harvesting(match)
    result.board_changed = True


def answer_conquer(engine: "RulesEngine", game, match: MatchState, seat: str,
                   unit: str) -> StepResult:
    """Which ground unit is revealed to take a neutral territory (TNP 5.5)."""
    ground = ground_units(engine, match.resolving["piles"][seat])
    if unit not in ground:
        raise RuleRefusal("Reveal a ground unit from the attacking pile.", cite="TNP 5.5")
    result = StepResult(part=match.resolving["spot"])
    _conquer(engine, match, seat, unit, result)
    return _waiting(engine, game, match, result)


def _open_battle(engine: "RulesEngine", match: MatchState, result: StepResult, *,
                 attacker: Optional[str] = None, contested: bool = False) -> None:
    """
    A battle over the attack being resolved (TNP 5.6, 6.1): each seat's
    attacking pile and its units already in the area's defense spot are
    its forces; the attacker's go with it. Everything in the battle is
    revealed, and what a base battle needs from the base is handed in
    (`tnp.flow.battle.begin_battle`).
    """
    resolving = match.resolving
    area, spot, piles = resolving["area"], resolving["spot"], resolving["piles"]
    is_base = engine.catalog.areas[area].is_base
    forces: dict[str, dict[str, int]] = {}
    damaged: dict[str, dict[str, int]] = {}
    for seat in SEATS:
        units: dict[str, int] = {}
        hurt: dict[str, int] = {}
        for slug, count in piles.get(seat, {}).items():
            units[slug] = units.get(slug, 0) + count
        _reveal(match, seat, area, spot, piles.get(seat, {}))
        standing = match.standing(area, seat)
        if standing is not None:
            for slug, count in standing.units.items():
                units[slug] = units.get(slug, 0) + count
            for slug, count in standing.damaged.items():
                hurt[slug] = hurt.get(slug, 0) + count
            _reveal(match, seat, area, "defense", standing.units)
        match.spots.get(area, {}).pop(seat, None)
        forces[seat] = units
        damaged[seat] = hurt
    holder = None if is_base else match.controller(area)
    defender = None if contested else (other(attacker) if attacker else None)
    structures = emergency = None
    if is_base:
        defender = engine.catalog.areas[area].seat
        state = match.seat(defender)
        structures = {
            "facilities": [slug for slug in state.built if slug in engine.catalog.facilities],
            "upgrades": [slug for slug in state.built if slug in engine.catalog.upgrades],
        }
        room = supply_room(engine, match, defender)
        emergency = {
            "pool": {"materials": state.pool.get("materials", 0), "gold": state.pool.get("gold", 0),
                     **{BATTLE_POOL[kind]: state.pool.get(kind, 0) for kind in RESOURCES}},
            "supply_room": {
                slug: room[slug] for slug in engine.catalog.facilities["base_defenses"].units
            },
        }
    resolving["stage"] = "battle"
    opened = fight.begin_battle(
        engine, match, area, forces,
        attacker=None if contested else attacker,
        contested=contested,
        held_by=holder,
        paths_home={seat: has_path(engine, match, seat, area) for seat in SEATS},
        structures=structures,
        emergency=emergency,
        damaged=damaged,
    )
    result.narration.extend(opened.narration)
    result.rolls.extend(opened.rolls)
    result.board_changed = True


def settle_battle(engine: "RulesEngine", game, match: MatchState, lead_in: str = "") -> StepResult:
    """
    A battle in March is over: its outcome goes on the map (TNP 5.7,
    6.11). The winner's survivors stay in the area's defense spot for
    the rest of March, their damage tokens off, since a damage token
    lasts the battle alone (TNP 6.8); the loser's go back to their base,
    and so do the units that retreated; the territory's control is the outcome's, with
    the Stranded tokens it moves; a fallen base wins the game (TNP 1.3);
    and a winner who attacked with Workers harvests (TNP 5.8). A base's
    emergency spend and what its base card destroyed are the base's.
    """
    battle = match.battle
    outcome = battle.outcome
    resolving = match.resolving or {"area": battle.territory, "piles": {}}
    area = battle.territory
    is_base = engine.catalog.areas[area].is_base
    result = StepResult(narration=[lead_in] if lead_in else [], board_changed=True)
    winner = outcome["winner"]
    for seat in SEATS:
        survivors = outcome["survivors"].get(seat, {})
        units = {slug: row["count"] for slug, row in survivors.items()}
        if seat in outcome["home"] or seat != winner:
            _home(match, seat, units)
        else:
            match.pile(area, seat).add(units)
        _home(match, seat, {slug: row["count"] for slug, row in outcome["withdrawn"].get(seat, {}).items()})
    if is_base:
        defender = battle.defender
        state = match.seat(defender)
        pool = (battle.emergency or {}).get("pool")
        if pool is not None:
            state.pool["materials"] = int(pool.get("materials", 0))
            state.pool["gold"] = int(pool.get("gold", 0))
            for kind in RESOURCES:
                state.pool[kind] = int(pool.get(BATTLE_POOL[kind], 0))
        if outcome["destroyed"] is not None:
            state.built.remove(outcome["destroyed"])
        if outcome["base_fallen"]:
            match.battle, match.resolving = None, None
            _win(match, winner, WON_BY_BASE, result)
            return _waiting(engine, game, match, result)
    elif outcome["control"] != match.controller(area):
        _set_control(engine, match, area, outcome["control"], result)
    if winner is not None and winner in resolving["piles"] and not is_base:
        workers = min(
            int(outcome["survivors"].get(winner, {}).get("worker", {}).get("count", 0)),
            int(resolving["piles"][winner].get("worker", 0)),
        )
        match.battle = None
        _harvest(engine, match, winner, area, workers, result)
    match.battle = None
    _done_unless_harvesting(match)
    return _waiting(engine, game, match, result)


def _set_control(engine: "RulesEngine", match: MatchState, area: str, seat: Optional[str],
                 result: StepResult) -> None:
    """
    `area` is held by `seat` now, or neutral (TNP 5.7): a seat's held
    territory the change leaves no longer joined to its base, with its
    units in it, takes a Stranded token; a Stranded token on a territory
    joined to its seat's base again comes off -- taking a territory beside
    it lifts the token only where that makes the path (the author,
    2026-11-06); and a seat that no longer holds a territory has no
    Stranded token left there.
    """
    before = {one: joined(engine, match, one) for one in SEATS}
    match.areas[area].controller = seat
    for one in SEATS:
        after = joined(engine, match, one)
        for lost in sorted(before[one] - after, key=area_order):
            if match.controller(lost) != one or match.standing(lost, one) is None:
                continue
            if one not in match.areas[lost].stranded:
                match.areas[lost].stranded.append(one)
                result.narration.append(
                    f"{tokens.seat(one)}'s units in {tokens.area(lost)} are stranded."
                )
        for slug in sorted(after, key=area_order):
            stranded = match.areas[slug].stranded
            if one in stranded and match.controller(slug) == one:
                stranded.remove(one)
                result.narration.append(
                    f"{tokens.seat(one)}'s units in {tokens.area(slug)} are no longer stranded."
                )
    for slug, state in match.areas.items():
        state.stranded = [one for one in state.stranded if state.controller == one]
    result.board_changed = True


def harvest_choice(match: MatchState, area: str, workers: int) -> tuple[int, dict[str, int]]:
    """How many tokens a harvest takes -- one a Worker, as many as are
    left (TNP 5.8) -- and the tokens left by kind."""
    left = {kind: int(count) for kind, count in match.areas[area].resources.items() if count}
    return min(int(workers), sum(left.values())), left


def _harvest(engine: "RulesEngine", match: MatchState, seat: str, area: str, workers: int,
             result: StepResult) -> None:
    """
    For each Worker in the winning attacking pile, one token off the
    territory into the seat's pool (TNP 5.8). Where the territory holds
    more than one kind and the Workers take less than all of it, the
    seat chooses which (the author, 2026-11-06): March waits on
    `HARVEST`, the attack still resolving. Otherwise the tokens are
    taken at once.
    """
    count, left = harvest_choice(match, area, workers)
    if count <= 0:
        return
    if len(left) > 1 and count < sum(left.values()):
        match.resolving["stage"] = "harvest"
        match.resolving["harvest"] = {"seat": seat, "workers": int(workers)}
        return
    if len(left) == 1:
        taken = {next(iter(left)): count}
    else:
        taken = dict(left)
    _take(match, seat, area, int(workers), taken, result)


def _take(match: MatchState, seat: str, area: str, workers: int, taken: Mapping[str, int],
          result: StepResult) -> None:
    left = match.areas[area].resources
    state = match.seat(seat)
    for kind, count in taken.items():
        if count:
            left[kind] -= count
            state.pool[kind] = state.pool.get(kind, 0) + count
    state.harvested += sum(taken.values())
    spot = (match.resolving or {}).get("spot", "")
    _reveal(match, seat, area, spot, {"worker": workers})
    result.narration.append(
        f"{tokens.seat(seat)}'s {workers} {tokens.unit('worker')} harvest {tokens.area(area)}: "
        f"{_tokens_words(taken)}, {state.harvested} harvested in all."
    )
    result.board_changed = True


def _done_unless_harvesting(match: MatchState) -> None:
    """The attack is resolved, unless its harvest waits on the seat."""
    if match.resolving is not None and match.resolving.get("stage") != "harvest":
        match.resolving = None


def answer_harvest(engine: "RulesEngine", game, match: MatchState, seat: str,
                   taken: Optional[Mapping]) -> StepResult:
    """Which tokens the seat's Workers take (TNP 5.8): one a Worker, of
    the kinds the territory holds."""
    resolving = match.resolving
    area = resolving["area"]
    workers = int(resolving["harvest"]["workers"])
    count, left = harvest_choice(match, area, workers)
    if not isinstance(taken, Mapping):
        raise RuleRefusal("Name the tokens taken, by kind.", cite="TNP 5.8")
    chosen = {}
    for kind, number in taken.items():
        try:
            number = int(number)
        except (TypeError, ValueError):
            raise RuleRefusal(f"{number!r} is not a count.", cite="TNP 5.8") from None
        if number < 0 or kind not in RESOURCES:
            raise RuleRefusal("Take minerals or gems, none below none.", cite="TNP 5.8")
        if number:
            chosen[kind] = number
    if any(number > left.get(kind, 0) for kind, number in chosen.items()):
        raise RuleRefusal("That is more than the territory holds.", cite="TNP 5.8")
    if sum(chosen.values()) != count:
        raise RuleRefusal(f"The Workers take {count} tokens, one a Worker.", cite="TNP 5.8")
    result = StepResult(part=resolving["spot"])
    _take(match, seat, area, workers, chosen, result)
    match.resolving = None
    return _waiting(engine, game, match, result)


def _win(match: MatchState, seat: str, by: str, result: StepResult) -> None:
    match.winner, match.won_by = seat, by
    match.phase = OVER
    match.attacks = {}
    if by == WON_BY_BASE:
        result.narration.append(f"{tokens.seat(seat)} wins the game: {tokens.area(base_of(other(seat)))} has fallen.")
    else:
        result.narration.append(
            f"{tokens.seat(seat)} wins the game: {match.seat(seat).harvested} of the planet's "
            "tokens harvested, 51% of them."
        )
    result.board_changed = True


# -- Production and Trade ---------------------------------------------------------


def produce(engine: "RulesEngine", game, match: MatchState, lead_in: str = "") -> StepResult:
    """
    Production (TNP 5.9): everything placed in Infrastructure is
    finished -- the units join the seat's available units, ready to
    deploy next turn, and the facilities and upgrades are built. What a
    seat produced stays behind its screen: nothing of it is said. Units
    queued at a facility a base card destroyed this March are not
    produced. Then each seat trades.
    """
    result = StepResult(narration=[lead_in] if lead_in else [], board_changed=True)
    result.narration.append("Production: everything placed in Infrastructure is finished.")
    for seat in SEATS:
        state = match.seat(seat)
        lost = False
        for slug, count in state.queued_units.items():
            if engine.unit(slug).facility not in state.built:
                lost = True
                continue
            state.available[slug] = state.available.get(slug, 0) + count
        for slug in state.queued:
            if slug not in state.built:
                state.built.append(slug)
        state.queued_units, state.queued = {}, []
        state.plan, state.locked = None, False
        if lost:
            result.narration.append(
                f"{tokens.seat(seat)} loses what was queued at a facility destroyed this turn."
            )
    match.phase = TRADE
    return _waiting(engine, game, match, result)


def answer_trade(engine: "RulesEngine", game, match: MatchState, seat: str, choice: str,
                 trade: Optional[Mapping] = None) -> StepResult:
    """A seat's trade (TNP 5.9), held until it locks in like a plan."""
    state = match.seat(seat)
    if trade is None and choice == "save":
        raise RuleRefusal("Saving a trade needs the trade.", cite="TNP 5.9")
    normal = normal_trade(trade if trade is not None else state.plan)
    check_trade(match, seat, normal)
    state.plan = normal
    result = StepResult()
    if choice == "lock":
        state.locked = True
        result.narration.append(f"{tokens.seat(seat)} locks in.")
        result.board_changed = True
    return _waiting(engine, game, match, result)


def settle_trades(engine: "RulesEngine", game, match: MatchState, lead_in: str = "") -> StepResult:
    """Both seats have traded: each trade goes into its pool, and is said
    -- the pool is open information (TNP 2.2, 5.9)."""
    result = StepResult(narration=[lead_in] if lead_in else [])
    for seat in SEATS:
        state = match.seat(seat)
        trade = normal_trade(state.plan) if state.locked and state.plan else None
        state.plan, state.locked = None, False
        if trade is None or not (trade["materials"] or trade["gold"]):
            continue
        gains = trade_gains(engine, trade)
        for into in ("materials", "gold"):
            for kind, count in trade[into].items():
                state.pool[kind] -= count
            state.pool[into] = state.pool.get(into, 0) + gains[into]
        spent = {kind: trade["materials"].get(kind, 0) + trade["gold"].get(kind, 0) for kind in RESOURCES}
        result.narration.append(
            f"{tokens.seat(seat)} trades {_tokens_words(spent)} for "
            f"{_spent(gains['materials'], gains['gold'])}."
        )
        result.board_changed = True
    match.phase = CLEANUP
    return _waiting(engine, game, match, result)


# -- Cleanup -----------------------------------------------------------------------


def cleanup(engine: "RulesEngine", game, match: MatchState, lead_in: str = "") -> StepResult:
    """
    Cleanup (TNP 5.10): every attack and defense spot cleared back to
    its seat's available units, except where the seat's units are
    stranded, which stay; then each seat's harvest is counted, and a seat
    with 49 or more of the map's tokens wins (TNP 1.3). Otherwise the
    next turn's Infrastructure and Deployment opens.
    """
    result = StepResult(narration=[lead_in] if lead_in else [], board_changed=True)
    for area in list(match.spots):
        piles = match.spots[area]
        for seat in list(piles):
            if seat in match.areas[area].stranded:
                continue
            _home(match, seat, piles.pop(seat).units)
        if not piles:
            del match.spots[area]
    match.revealed = []
    match.attacks = {}
    for seat in SEATS:
        if match.seat(seat).harvested >= HARVEST_TO_WIN:
            _win(match, seat, WON_BY_HARVEST, result)
            return _waiting(engine, game, match, result)
    match.turn += 1
    match.phase = PLAN
    for seat in SEATS:
        match.seat(seat).plan, match.seat(seat).locked = None, False
    result.narration.append(f"Turn {match.turn}: Infrastructure and Deployment.")
    return _waiting(engine, game, match, result)


__all__ = [
    "answer_conquer", "answer_harvest", "harvest_choice", "answer_plan", "answer_trade", "cleanup", "march", "next_attack",
    "produce", "reveal", "settle_battle", "settle_trades",
]
