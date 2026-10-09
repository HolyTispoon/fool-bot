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

from codex.components import HERO, BuildingState, CardInstance, MatchState, hero_ref
from codex.engine import RulesEngine
from codex.flow import StepResult
from codex.flow import driver
from codex.game import CodexGame
from codex.prompts import owed_step


def new_game(seed: int = 7, first: Optional[int] = 1,
             teams=(("bashing",), ("finesse",)), mode: Optional[str] = None,
             ) -> tuple[RulesEngine, CodexGame, MatchState]:
    """A started game, its engine seeded, and the match standing on the
    first turn's start: Bashing (seat 1) against Finesse (seat 2) by
    default, or `teams` -- each seat's specs, three for a standard game,
    whose `mode` follows from them unless given -- each on the deck the
    lobby settles, or its first hero's colour where it is the player's
    choice."""
    teams = tuple((team,) if isinstance(team, str) else tuple(team) for team in teams)
    engine = RulesEngine(seed=seed)
    game = CodexGame("codex-test", 1)
    game.mode = mode or ("standard" if len(teams[0]) == 3 else "basic")
    game.take_seat(101, "basher", list(teams[0]))
    game.take_seat(202, "fencer", list(teams[1]))
    for seat in (1, 2):
        if seat not in game.player_decks:
            game.player_decks[seat] = game.deck_choices(seat)[0]
    match = engine.new_match(teams, first=first, decks=(game.player_decks[1], game.player_decks[2]))
    game.match_state = match.to_dict()
    return engine, game, match


#: How an action names the basic game's two heroes, Bashing's seat 1
#: and Finesse's seat 2 in `new_game`'s default.
TROQ = hero_ref("troq_bashar")
RIVER = hero_ref("river_montoya")


def hero(match: MatchState, seat: int, slug: Optional[str] = None) -> str:
    """How an action names `seat`'s hero -- `slug`, or their first, the
    basic game's one: `hero:troq_bashar`."""
    player = match.player(seat)
    return hero_ref(slug or player.heroes[0].slug)


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
                 patrol: Optional[str] = None, arrived: bool = False,
                 slug: Optional[str] = None) -> None:
    """`seat`'s hero into play -- `slug`, where a side has three, or the
    first."""
    player = match.player(seat)
    hero = player.hero_of(slug) if slug else player.heroes[0]
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


__all__ = ["HERO", "RIVER", "TROQ", "begin", "built", "hand", "hero", "hero_in_play", "new_game", "put", "run_owed"]
