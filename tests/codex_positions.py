"""
Staging a Codex position by card slug, for the Codex tests.

**Naming by slug is right here, where D12 Ball names by role.** D12
Ball's roster is data the author revises -- a player moves teams, a
role changes hands -- so a D12 Ball test names a player by role
(`tests/roster.py`) and survives the revision. Codex's cards are fixed
data, imported whole from the card database at a pinned commit and
never edited (docs/design/codex.md, "The cards are data"): Iron Man is
`iron_man` and 3/4 today and every day, so a test says exactly the card
it means (docs/codex-bot.md, step 2).

Every helper builds or changes a `MatchState` directly and saves nothing.
"""

from __future__ import annotations

from typing import Optional

from codex.components import HERO, BuildingState, CardInstance, MatchState
from codex.engine import RulesEngine
from codex.flow import StepResult
from codex.flow import driver
from codex.game import CodexGame
from codex.prompts import owed_step


def new_game(seed: int = 7, first: Optional[int] = 1) -> tuple[RulesEngine, CodexGame, MatchState]:
    """A started game of Bashing (seat 1) against Finesse (seat 2), its
    engine seeded, and the match standing on the first turn's start."""
    engine = RulesEngine(seed=seed)
    game = CodexGame("codex-test", 1)
    game.take_seat(101, "basher", "bashing")
    game.take_seat(202, "fencer", "finesse")
    match = engine.new_match(("bashing", "finesse"), first=first)
    game.match_state = match.to_dict()
    return engine, game, match


def run_owed(engine: RulesEngine, game: CodexGame, match: MatchState):
    """Run whatever step the bot owes, as the service's resume does;
    `None` where nothing is owed."""
    owed = owed_step(engine, game, match)
    if owed is None:
        return None
    return driver.advance(engine, game, match, StepResult(next=owed))


def begin(engine: RulesEngine, game: CodexGame, match: MatchState) -> MatchState:
    """Run the owed steps until somebody is asked something."""
    while run_owed(engine, game, match) is not None:
        pass
    return match


def put(
    match: MatchState,
    seat: int,
    slug: str,
    *,
    patrol: Optional[str] = None,
    damage: int = 0,
    exhausted: bool = False,
    arrived: bool = False,
) -> CardInstance:
    """`slug` into `seat`'s play zone -- patrolling `patrol` if given --
    ready and without arrival fatigue unless told otherwise."""
    card = match.new_instance(slug, seat)
    card.patrol_slot = patrol
    card.damage = damage
    card.exhausted = exhausted
    card.arrived_this_turn = arrived
    return card


def hero_in_play(match: MatchState, seat: int, *, level: int = 1, damage: int = 0,
                 patrol: Optional[str] = None, arrived: bool = False) -> None:
    hero = match.player(seat).hero
    hero.zone = "play"
    hero.level = level
    hero.damage = damage
    hero.patrol_slot = patrol
    hero.arrived_this_turn = arrived
    hero.exhausted = False


def built(match: MatchState, seat: int, building: str, *, hp: int = 5,
          finished: bool = True) -> BuildingState:
    state = BuildingState(hp=hp, under_construction=not finished)
    match.player(seat).buildings[building] = state
    return state


def hand(match: MatchState, seat: int, *slugs: str) -> None:
    match.player(seat).hand = list(slugs)


__all__ = ["HERO", "begin", "built", "hand", "hero_in_play", "new_game", "put", "run_owed"]
