"""
Staging a TNP battle by unit slug and count, and fighting it through
`tnp.flow.driver.apply` -- the units are fixed data, so a TNP test names
the unit (as `tests/codex_positions.py` names a Codex card).

    engine, match = stage({"tank": 3}, {"mercenary": 4})
    fight(engine, match)            # every prompt answered by `first`
    match.battle.outcome["winner"]

`stage` opens the battle with `begin_battle` and runs it to its first
question; the attacker is Blue unless named. `rolls` scripts the dice:
each d12 the engine rolls is the next number in the list.
"""

from __future__ import annotations

import random
from contextlib import contextmanager
from typing import Callable, Iterable, Mapping, Optional
from unittest import mock

from tnp.components import MatchState
from tnp.engine import RulesEngine
from tnp.flow import battle as fight_steps
from tnp.flow import driver
from tnp.prompts import Action, PendingPrompt, PromptKind, pending
from tnp.tokens import plain


def stage(
    attacker: Mapping[str, int],
    defender: Mapping[str, int],
    *,
    territory: str = "8",
    attacking: str = "blue",
    held: bool = True,
    seed: int = 0,
    contested: bool = False,
    paths_home: Optional[Mapping[str, bool]] = None,
    structures: Optional[Mapping[str, list]] = None,
    emergency: Optional[Mapping] = None,
    modifiers: tuple = (),
    effects: Optional[Mapping] = None,
    damaged: Optional[Mapping[str, Mapping[str, int]]] = None,
    rolls: Optional[Iterable[int]] = None,
    answers_the_only_choice: bool = False,
):
    """A battle opened and run to its first question: `attacker`'s units
    for `attacking`, `defender`'s for the other seat. The territory is
    held by the defender unless `held` is false (or it is contested).
    Every question is asked, one answer or not, unless
    `answers_the_only_choice` -- the game's own setting -- is on."""
    engine = RulesEngine(rng=random.Random(seed), answers_the_only_choice=answers_the_only_choice)
    match = MatchState()
    defending = "green" if attacking == "blue" else "blue"
    area = engine.catalog.areas[territory]
    if area.is_base:
        attacking, defending = ("blue", "green") if area.seat == "green" else ("green", "blue")
    with scripted(engine, rolls):
        result = fight_steps.begin_battle(
            engine, match, territory,
            {attacking: dict(attacker), defending: dict(defender)},
            attacker=None if contested else attacking,
            contested=contested,
            held_by=defending if held and not contested and not area.is_base else None,
            paths_home=paths_home if paths_home is not None else {"blue": True, "green": True},
            structures=structures, emergency=emergency, modifiers=modifiers, effects=effects,
            damaged=damaged,
        )
        driver.advance(engine, None, match, result)
    return engine, match


@contextmanager
def scripted(engine: RulesEngine, rolls: Optional[Iterable[int]]):
    """Each d12 the next of `rolls`; the seeded `engine.rng` where none."""
    if rolls is None:
        yield
        return
    numbers = iter(rolls)
    with mock.patch.object(engine.rng, "randint", side_effect=lambda low, high: next(numbers)):
        yield


def asked(engine: RulesEngine, match: MatchState) -> Optional[PendingPrompt]:
    waiting = pending(engine, None, match)
    return waiting if isinstance(waiting, PendingPrompt) else None


def first(prompt: PendingPrompt) -> Action:
    """The first legal answer to any battle question: the first force to
    its first slot, the first shooter at its first target, fight on,
    attack, build nothing, keep the flankers, give no Workers, take the
    splash, the first thing destroyed, the first tactic card that does
    something, and every reroll."""
    options = prompt.options
    kind = prompt.kind
    if kind is PromptKind.CHOOSE_ROLE:
        return Action(kind, "attack")
    if kind is PromptKind.EMERGENCY_DEFENSE:
        return Action(kind, "none")
    if kind is PromptKind.REPOSITION_FLANKERS:
        return Action(kind, "keep")
    if kind is PromptKind.PLACE_FORCE:
        force = options.forces[0]
        return Action(kind, "", {"force": force.force, "slot": force.slots[0]})
    if kind is PromptKind.DECLARE_RETREAT:
        return Action(kind, "fight")
    if kind is PromptKind.CHOOSE_TARGET:
        shooter = options.forces[0]
        best = max(shooter.targets, key=lambda one: one.dice)
        return Action(kind, "", {"force": shooter.force, "target": best.target})
    if kind is PromptKind.REPAIR:
        return Action(kind, "decline")
    if kind is PromptKind.SPLASH:
        return Action(kind, "splash", {"force": options.forces[0]})
    if kind is PromptKind.DESTROY:
        return Action(kind, "", {"thing": options.things[0]})
    if kind is PromptKind.TACTIC:
        if options.applies:
            return Action(kind, "play", {"card": options.applies[0]}, seat=prompt.asked_seat)
        return Action(kind, "none", seat=prompt.asked_seat)
    if kind is PromptKind.REROLL:
        return Action(kind, "reroll", {"count": options.most})
    raise AssertionError(kind)


def play(engine: RulesEngine, match: MatchState, action: Action, rolls: Optional[Iterable[int]] = None):
    """One action through `driver.apply`, failing the test on a refusal."""
    with scripted(engine, rolls):
        run = driver.apply(engine, None, match, action)
    if isinstance(run, driver.Refusal):
        raise AssertionError(f"refused: {run.reason}")
    return run


def fight(engine: RulesEngine, match: MatchState,
          policy: Callable[[PendingPrompt], Action] = first, limit: int = 2000):
    """Answer every question with `policy` until the battle is over;
    every run, in order."""
    runs = []
    for _ in range(limit):
        prompt = asked(engine, match)
        if prompt is None:
            assert match.battle.outcome is not None, "the battle waits on nobody and is not over"
            return runs
        runs.append(play(engine, match, policy(prompt)))
    raise AssertionError("the battle did not end")


def words(engine: RulesEngine, runs) -> list[str]:
    """Every line the runs said, in plain words."""
    return [plain(line, engine.catalog) for run in runs for line in run.narration if line]
