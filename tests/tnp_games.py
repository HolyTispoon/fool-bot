"""
Playing a whole TNP game through `tnp.flow.driver.apply`, with nothing
from `cogs/` or `discord` imported -- the seats' answers come from a
`Strategy`, which reads each prompt's options and nothing else, as a
view would.

    engine, game, match = opening(seed=3)
    match, runs = play(engine, game, match, {"blue": Harvester(), "green": Turtle()})

A strategy answers the turn's four kinds (`plan`, `trade`, `conquer`,
`harvest`)
and the battle's (`battle`, `tnp_battles.first` unless overridden). The
units are fixed data, so a strategy names units by slug.
"""

from __future__ import annotations

import json
import random
from typing import Mapping, Optional

from tnp.components import MatchState
from tnp.engine import RulesEngine
from tnp.flow import driver
from tnp.game import TnpGame
from tnp.prompts import Action, PendingPrompt, PromptKind, pending_all, pending_prompts
from tnp.turn import base_of, has_path

from tnp_battles import first as first_battle_answer

TURN_KINDS = (PromptKind.PLAN, PromptKind.TRADE, PromptKind.CONQUER, PromptKind.HARVEST)


def opening(seed: int = 0) -> tuple[RulesEngine, TnpGame, MatchState]:
    """A game with both seats taken, started: turn 1's plans open."""
    engine = RulesEngine(rng=random.Random(seed))
    game = TnpGame(game_id="test")
    game.take_seat(1, "Blue's player", "blue")
    game.take_seat(2, "Green's player", "green")
    game.start(engine)
    return engine, game, MatchState.from_dict(game.match_state)


class Strategy:
    """Lock in an empty plan, trade nothing, reveal the first ground unit,
    and answer a battle with `tnp_battles.first`."""

    def plan(self, engine: RulesEngine, match: MatchState, seat: str, options) -> dict:
        return {}

    def trade(self, engine: RulesEngine, match: MatchState, seat: str, options) -> dict:
        return {}

    def conquer(self, options) -> str:
        return options.units[0]

    def harvest(self, options) -> dict:
        """The tokens taken, the kind with most left first."""
        left = dict(options.left)
        taken: dict[str, int] = {}
        for _ in range(options.count):
            kind = max(left, key=lambda one: (left[one], one))
            left[kind] -= 1
            taken[kind] = taken.get(kind, 0) + 1
        return taken

    def battle(self, prompt: PendingPrompt) -> Action:
        return first_battle_answer(prompt)


def buy(options, wanted: Mapping[str, int], materials: Optional[int] = None) -> dict:
    """As many of each wanted unit, in order, as the options, the
    facility caps and the pool's materials and gold allow."""
    left_materials = options.pool.get("materials", 0) if materials is None else materials
    left_gold = options.pool.get("gold", 0)
    caps = {one.facility: one.cap for one in options.caps}
    found: dict[str, int] = {}
    for unit, count in wanted.items():
        offer = next((one for one in options.build if one.unit == unit), None)
        if offer is None:
            continue
        for _ in range(min(count, offer.most)):
            if caps.get(offer.facility, 0) <= 0:
                break
            if offer.materials > left_materials or offer.gold > left_gold:
                break
            found[unit] = found.get(unit, 0) + 1
            caps[offer.facility] -= 1
            left_materials -= offer.materials
            left_gold -= offer.gold
    return found


def trade_everything(options, into: str = "materials") -> dict:
    """Every mineral and gem for materials (or gold)."""
    return {into: {kind: count for kind, count in options.tokens.items() if count}}


def tokens_left(match: MatchState, area: str) -> int:
    return match.areas[area].tokens_left()


class Harvester(Strategy):
    """
    Workers, as many as the Barracks and the supply allow, sent every
    turn from attack spot A to the reachable territory with most tokens
    left; a Mercenary from spot B to take a territory that opens the way
    to more; every token traded for materials.
    """

    def plan(self, engine, match, seat, options):
        catalog = engine.catalog
        build = buy(options, {"worker": 8, "mercenary": 8})
        reachable = [one.area for one in options.targets if one.path and not catalog.areas[one.area].is_base]
        rich = [area for area in reachable if tokens_left(match, area)]
        attacks = {}
        workers = options.available.get("worker", 0)
        if rich and workers:
            best = max(rich, key=lambda area: (tokens_left(match, area), -int(area)))
            attacks["A"] = {"target": best, "units": {"worker": workers}}
        held = {area for area, state in match.areas.items() if state.controller == seat}
        stepping = [
            area for area in reachable
            if area not in held and not tokens_left(match, area)
            and any(tokens_left(match, there) for there in catalog.areas[area].adjacent)
        ]
        if stepping and options.available.get("mercenary", 0):
            attacks["B"] = {"target": min(stepping, key=int), "units": {"mercenary": 1}}
        return {"build": build, "attacks": attacks}

    def trade(self, engine, match, seat, options):
        return trade_everything(options)


class Turtle(Harvester):
    """A Harvester that builds nothing but Workers, keeps its Mercenaries
    home in its base's defense spot, and never takes a stepping stone."""

    def plan(self, engine, match, seat, options):
        plan = super().plan(engine, match, seat, options)
        plan["build"] = buy(options, {"worker": 1})
        plan["attacks"].pop("B", None)
        mercenaries = options.available.get("mercenary", 0)
        if mercenaries:
            plan["defense"] = {base_of(seat): {"mercenary": mercenaries}}
        return plan


#: The way from Blue's base to Green's, a territory at a time (TNP 2.1).
ROAD_TO_GREEN = ("10", "2", "1", "3", "11")


class Raider(Strategy):
    """
    Mercenaries, as many as the pool allows, and Workers harvesting the
    territories beside the base from spot A to pay for them; a Mercenary
    from spot B taking the road to the other base a territory at a time,
    and once the road is held, every Mercenary at the base from B.
    """

    road = ROAD_TO_GREEN

    def plan(self, engine, match, seat, options):
        build = buy(options, {"mercenary": 8})
        attacks = {}
        workers = options.available.get("worker", 0)
        rich = [one.area for one in options.targets if one.path and tokens_left(match, one.area)]
        if workers and rich:
            attacks["A"] = {"target": max(rich, key=lambda area: (tokens_left(match, area), -int(area))),
                            "units": {"worker": workers}}
        mercenaries = options.available.get("mercenary", 0)
        target = base_of("green" if seat == "blue" else "blue")
        untaken = [area for area in self.road if match.areas[area].controller != seat]
        if untaken:
            if mercenaries:
                attacks["B"] = {"target": untaken[0], "units": {"mercenary": 1}}
        elif mercenaries and has_path(engine, match, seat, target):
            attacks["B"] = {"target": target, "units": {"mercenary": mercenaries}}
        return {"build": build, "attacks": attacks}

    def trade(self, engine, match, seat, options):
        return trade_everything(options)


def answer(engine: RulesEngine, match: MatchState, strategy: Strategy, prompt: PendingPrompt) -> Action:
    seat = prompt.asked_seat
    if prompt.kind is PromptKind.PLAN:
        return Action(PromptKind.PLAN, "lock", {"plan": strategy.plan(engine, match, seat, prompt.options)}, seat=seat)
    if prompt.kind is PromptKind.TRADE:
        return Action(PromptKind.TRADE, "lock", {"trade": strategy.trade(engine, match, seat, prompt.options)}, seat=seat)
    if prompt.kind is PromptKind.CONQUER:
        return Action(PromptKind.CONQUER, "", {"unit": strategy.conquer(prompt.options)}, seat=seat)
    if prompt.kind is PromptKind.HARVEST:
        return Action(PromptKind.HARVEST, "", {"tokens": strategy.harvest(prompt.options)}, seat=seat)
    return strategy.battle(prompt)


def step(engine, game, match, strategies: Mapping[str, Strategy]):
    """Answer the first question open, through `driver.apply`; the run,
    failing the test on a refusal."""
    prompts = pending_prompts(engine, game, match)
    assert prompts, f"nothing is asked: {pending_all(engine, game, match)}"
    prompt = prompts[0]
    action = answer(engine, match, strategies[prompt.asked_seat], prompt)
    run = driver.apply(engine, game, match, action)
    if isinstance(run, driver.Refusal):
        raise AssertionError(f"refused {action}: {run.reason} ({run.cite})")
    return run


def reload(match: MatchState) -> MatchState:
    """The position through its save and back -- a restart."""
    return MatchState.from_dict(json.loads(json.dumps(match.to_dict())))


def play(engine, game, match, strategies: Mapping[str, Strategy], *, turns: int = 40,
         limit: int = 20000) -> tuple[MatchState, list]:
    """
    Play until somebody wins, or `turns` turns: the match at the end and
    every run, in order. **Every position round-trips** through the save
    before the next question is read, which is a restart written as a
    loop -- so a plan held on the match is what the next answer reads.
    """
    runs = []
    for _ in range(limit):
        if match.winner is not None or match.turn > turns:
            game.match_state = match.to_dict()
            return match, runs
        runs.append(step(engine, game, match, strategies))
        match = reload(match)
    raise AssertionError("the game did not end")
