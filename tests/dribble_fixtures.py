"""
A match standing in each branch the two dribbles resolve through, and
what that resolution should produce.

Rank O2 of Phase 3 of docs/model-discord-split.md moves Dribble
Advance's and Dribble Burst's own resolution out of the cog and into
`d12ball/flow/effects.py`. The thing worth asserting about a move like
that is that **not one branch changed what it said or what it did
next**, and that needs one table standing in every branch rather than
the scattered assertions the suite already had.

So the fixtures live here, built with no `discord` in scope, and two
test modules read the same table:

- `tests/test_d12ball_dribble_flow.py` asks the model
  (`d12ball.flow.effects.dribble_advance_step` /
  `dribble_burst_step`) for the `StepResult`.
- `tests/test_d12ball_dribble_recording.py` asks the cog
  (`D12Ball.apply_dribble_advance` / `apply_dribble_burst`) what it
  handed the step that comes next.

The second one is the equivalence test, and it is the shape
`tests/low_pass_fixtures.py` gave Phase 2: it was written and run
green against the **old** cog before anything moved, so a green run
afterwards is the two answering the same way rather than two halves of
one new thing agreeing with each other. Its commit is the first on the
branch for exactly that reason.

**The expected narration is built, never spelled out, wherever it
names a player** -- the roster is data the author revises (see
`roster.py`). The numbers are spelled out, because a distance the
fixture chose is a fact about the fixture rather than about the
roster. The exhaustion emoji is read through the same fallback lookup
the message uses, for the same reason: it is Discord data the
application uploads, and a test that spells it pins an upload rather
than a sentence.

**The follow-on step is named by its `FollowOnStep` member name**, a
string, so this module needs no import from `d12ball/flow/` -- which
is what let it be written before that member existed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from d12ball.ai import build_ai_strategies
from d12ball.components import (
    MatchState,
    PlayerRole,
    TeamSide,
    Zone,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.engine import RulesEngine
from d12ball.formatting import get_exhaust_emoji, get_exhausted_emoji
from d12ball.game import (
    D12BallGame,
    Formation,
    GameMode,
    GameStatus,
    Team,
)
from roster import fielded

CATALOG = load_player_catalog()
RULESET = load_basic_ruleset()
MANEUVERS = load_maneuver_catalog()
ENGINE = RulesEngine(
    CATALOG, RULESET, MANEUVERS, build_ai_strategies(CATALOG, MANEUVERS),
)

GAME_ID = "g1"

#: The two follow-on steps a dribble can end on, by `FollowOnStep`
#: member name. Spelled as strings so this module stays free of the
#: package under test. An advance ends on the speed choice; a burst
#: leaves the ball at 12 and asks nothing, so it ends on the tail.
SPEED_CHOICE = "OFFER_SPEED_CHOICE"
FINISH = "FINISH_MANEUVER_RESOLUTION"
#: What a burst says about the speed, when it changed it.
BURST_SPEED_LINE = "Ball speed is now **12**."

#: What a message shows for an exhaustion token, and for the
#: Exhausted condition, when the application has uploaded nothing --
#: which is every test, since the fixtures fetch no emoji.
EXHAUST = get_exhaust_emoji({})
EXHAUSTED = get_exhausted_emoji({})


@dataclass
class DribbleFixture:
    """One match mid-dribble, and everything resolving it should say."""

    game: D12BallGame
    match: MatchState
    #: Which card: `dribble_advance` or `dribble_burst`.
    key: str
    distance: int

    #: The narration, as one string: what the old cog built inline and
    #: handed the speed choice as its `lead_in`.
    narration: str = ""
    #: Whether the board moved -- what `refresh_match_image` decided.
    board_changed: bool = True
    #: Which step runs next, by `FollowOnStep` member name.
    follow_on: str = SPEED_CHOICE
    #: The arguments that step is called with, `lead_in` aside.
    follow_on_kwargs: dict[str, Any] = field(default_factory=dict)

    #: What the match looks like afterwards.
    carrier_id: Optional[str] = None
    ball_space: Optional[tuple[Zone, int]] = None
    handler_space: Optional[tuple[Zone, int]] = None
    #: Token counts worth checking, by player id. A dribble charges
    #: the handler and a beaten Clear charges the defender, and both
    #: are read off `match.exhaustion` rather than off the sentence.
    exhaustion: dict[str, int] = field(default_factory=dict)
    #: The ball's speed afterwards, where the card sets it: a burst
    #: leaves it at 12, an advance leaves it to the choice that follows.
    ball_speed: Optional[int] = None


@dataclass(frozen=True)
class DribbleCase:
    """A fixture and the name it is reported under."""

    name: str
    build: Callable[[], DribbleFixture]


def build_game(**overrides) -> D12BallGame:
    fields = dict(
        game_id=GAME_ID,
        game_number=1,
        guild_id=1,
        channel_id=2,
        message_id=None,
        player_1_id=111,
        player_2_id=222,
        player_1_team=Team.ORANGE,
        player_2_team=Team.PURPLE,
        home_player_number=1,
        visiting_player_number=2,
        status=GameStatus.IN_PROGRESS,
    )
    fields.update(overrides)
    return D12BallGame(**fields)


def build_match(board_size: int = 7) -> MatchState:
    return MatchState.standard(
        catalog=CATALOG,
        ruleset=RULESET,
        board_size=board_size,
        home_team=Team.ORANGE,
        visiting_team=Team.PURPLE,
        home_formation=Formation.TWO_TWO_TWO,
    )


def label(match: MatchState, player_id: str) -> str:
    """The player as every message in the game names them."""
    return ENGINE.format_player_label(
        match, ENGINE.get_player_definition(player_id),
    )


def put_on_the_ball(
    match: MatchState,
    player_id: str,
    side: TeamSide = TeamSide.HOME,
) -> str:
    """
    Stand `player_id` on the ball and hand it to them, wherever the
    standard deal happened to put them. A dribble is about the player
    carrying it, so every fixture here starts from a named role rather
    than from whoever the deal's handler list starts with.
    """
    zone, space_index = match.board.meeple_position(player_id)
    match.set_ball_space(zone, space_index)
    match.ball.possession = side
    match.select_ball_handler(player_id)
    return player_id


def walk_to_the_far_end(
    match: MatchState,
    player_id: str,
    side: TeamSide = TeamSide.HOME,
) -> None:
    """
    Park a player on the last space of the goal they attack. Nothing
    in the game walks a player that far, but two branches only exist
    there -- a dribble with nowhere left to run.
    """
    match.move_player_relative(
        player_id, side, len(match.board.spaces_in_order()),
    )


def stand_a_beaten_clear(match: MatchState, key: str) -> str:
    """
    Put the match in the state a dribble that beat an advanced Clear
    leaves it in, and hand back the defender who played it.

    The cost is charged inside the dribble that beat it -- see
    "Gambits" in docs/design/maneuvers.md -- so this is the
    whole of what the fixture needs: a challenger, the two keys, and
    an advanced game around them.

    **Walking the challenger in costs them a token**, which is why the
    running total the cost's sentence reports is one higher than the
    2 it charges. That is `choose_challenger`'s charge and not the
    dribble's, and it is left in rather than zeroed out because it is
    the state a real beaten Clear is charged in.
    """
    challenger = min(match.visiting.field_players, key=match.distance_to_ball)
    match.choose_challenger(challenger)
    match.choose_offense_maneuver(key)
    match.choose_defense_maneuver("clear")
    return challenger


# -- Dribble Advance ---------------------------------------------------


def advance_plain() -> DribbleFixture:
    """
    The ordinary one space forward, by somebody with no ability to
    read into it. The baseline the other advances are variations on.
    """
    match = build_match()
    handler = put_on_the_ball(match, fielded(match, PlayerRole.MIDFIELDER))
    origin = match.board.flat_index(match.ball.zone, match.ball.space_index)
    destination = match.board.position_at_flat_index(
        match.relative_flat_index(origin, TeamSide.HOME, 1)
    )
    return DribbleFixture(
        game=build_game(),
        match=match,
        key="dribble_advance",
        distance=1,
        narration=(
            f"**Dribble Advance:** {label(match, handler)} and the "
            "ball move forward 1 space."
        ),
        follow_on_kwargs={"player_id": handler, "skill_type": "offense"},
        carrier_id=handler,
        ball_space=destination,
        handler_space=destination,
    )


def advance_playmaker_two() -> DribbleFixture:
    """
    Role ability -- a Playmaker may advance 2 instead of 1, and the
    note is what says which of the two they took.
    """
    match = build_match()
    handler = put_on_the_ball(match, fielded(match, PlayerRole.PLAYMAKER))
    origin = match.board.flat_index(match.ball.zone, match.ball.space_index)
    destination = match.board.position_at_flat_index(
        match.relative_flat_index(origin, TeamSide.HOME, 2)
    )
    return DribbleFixture(
        game=build_game(),
        match=match,
        key="dribble_advance",
        distance=2,
        narration=(
            f"**Dribble Advance:** {label(match, handler)} and the "
            "ball move forward 2 spaces (Playmaker ability)."
        ),
        follow_on_kwargs={"player_id": handler, "skill_type": "offense"},
        carrier_id=handler,
        ball_space=destination,
        handler_space=destination,
    )


def advance_playmaker_one() -> DribbleFixture:
    """
    The same Playmaker taking the ordinary space instead. The ability
    note is on the distance, not on the player -- a move that bought
    nothing says nothing about the ability.
    """
    match = build_match()
    handler = put_on_the_ball(match, fielded(match, PlayerRole.PLAYMAKER))
    origin = match.board.flat_index(match.ball.zone, match.ball.space_index)
    destination = match.board.position_at_flat_index(
        match.relative_flat_index(origin, TeamSide.HOME, 1)
    )
    return DribbleFixture(
        game=build_game(),
        match=match,
        key="dribble_advance",
        distance=1,
        narration=(
            f"**Dribble Advance:** {label(match, handler)} and the "
            "ball move forward 1 space."
        ),
        follow_on_kwargs={"player_id": handler, "skill_type": "offense"},
        carrier_id=handler,
        ball_space=destination,
        handler_space=destination,
    )


def advance_clamped_at_the_far_end() -> DribbleFixture:
    """
    A handler already on the last space of the field advances
    nowhere: `move_player_relative` clamps, and the wording reads the
    distance it actually travelled rather than the one asked for.
    """
    match = build_match()
    handler = fielded(match, PlayerRole.MIDFIELDER)
    walk_to_the_far_end(match, handler)
    put_on_the_ball(match, handler)
    where = match.board.meeple_position(handler)
    return DribbleFixture(
        game=build_game(),
        match=match,
        key="dribble_advance",
        distance=1,
        narration=(
            f"**Dribble Advance:** {label(match, handler)} and the "
            "ball move forward 0 spaces."
        ),
        follow_on_kwargs={"player_id": handler, "skill_type": "offense"},
        carrier_id=handler,
        ball_space=where,
        handler_space=where,
    )


def advance_beats_a_clear() -> DribbleFixture:
    """
    **Clear's cost**, charged inside the dribble that beat it: the
    defender who played it gains 2 exhaustion, said in the middle of
    the dribble's own message rather than as one after it.

    The three tokens take the defender past their own defensive
    skill, so the charge tests the Exhausted threshold as it writes
    it and the sentence says so. That test is a **state change made
    while the message is being built** -- see `apply_exhaustion` --
    which is exactly the write the old code made after its save.

    Species abilities are off so the sentence is the plain one. A
    Cyborg's tokens are drain and are called that -- which is
    `describe_exhaustion_gain`'s own branch, tested where it lives
    (`tests/test_d12ball_species_abilities.py`), and not something
    this rank decides.
    """
    match = build_match()
    handler = put_on_the_ball(match, fielded(match, PlayerRole.MIDFIELDER))
    defender = stand_a_beaten_clear(match, "dribble_advance")
    origin = match.board.flat_index(match.ball.zone, match.ball.space_index)
    destination = match.board.position_at_flat_index(
        match.relative_flat_index(origin, TeamSide.HOME, 1)
    )
    return DribbleFixture(
        game=build_game(mode=GameMode.ADVANCED, species_abilities=False),
        match=match,
        key="dribble_advance",
        distance=1,
        narration=(
            f"**Dribble Advance:** {label(match, handler)} and the "
            "ball move forward 1 space."
            "\n\n**Clear** was beaten -- 2 exhaustion.\n"
            f"{label(match, defender)} gains 2 exhaustion tokens "
            f"{EXHAUST * 2} (now 3 total)."
            f"\n{label(match, defender)} is now *exhausted* {EXHAUSTED}"
        ),
        follow_on_kwargs={"player_id": handler, "skill_type": "offense"},
        carrier_id=handler,
        ball_space=destination,
        handler_space=destination,
        exhaustion={defender: 3},
    )


# -- Dribble Burst -----------------------------------------------------


def burst_plain() -> DribbleFixture:
    """
    Three spaces past everybody, at a token a space. The baseline the
    other bursts are variations on.
    """
    match = build_match()
    handler = put_on_the_ball(match, fielded(match, PlayerRole.MIDFIELDER))
    origin = match.board.flat_index(match.ball.zone, match.ball.space_index)
    destination = match.board.position_at_flat_index(
        match.relative_flat_index(origin, TeamSide.HOME, 3)
    )
    return DribbleFixture(
        game=build_game(),
        match=match,
        key="dribble_burst",
        distance=3,
        narration=(
            f"**Dribble Burst:** {label(match, handler)} bursts 3 "
            "spaces forward, past everyone in the way."
            f"\n{label(match, handler)} gains 3 exhaustion tokens "
            f"{EXHAUST * 3} (now 3 total)."
            f" {BURST_SPEED_LINE}"
        ),
        follow_on=FINISH,
        follow_on_kwargs={"distance_moved": 1},
        carrier_id=handler,
        ball_space=destination,
        handler_space=destination,
        exhaustion={handler: 3},
        ball_speed=12,
    )


def burst_playmaker_discount() -> DribbleFixture:
    """
    Role ability -- a Playmaker pays one token fewer for the run (the
    author, 2026-08-26). The saving is named once beside the run
    rather than subtracted from each button's price.
    """
    match = build_match()
    handler = put_on_the_ball(match, fielded(match, PlayerRole.PLAYMAKER))
    origin = match.board.flat_index(match.ball.zone, match.ball.space_index)
    destination = match.board.position_at_flat_index(
        match.relative_flat_index(origin, TeamSide.HOME, 3)
    )
    return DribbleFixture(
        game=build_game(),
        match=match,
        key="dribble_burst",
        distance=3,
        narration=(
            f"**Dribble Burst:** {label(match, handler)} bursts 3 "
            "spaces forward, past everyone in the way."
            " That costs them a token less (Playmaker ability)."
            f"\n{label(match, handler)} gains 2 exhaustion tokens "
            f"{EXHAUST * 2} (now 2 total)."
            f" {BURST_SPEED_LINE}"
        ),
        follow_on=FINISH,
        follow_on_kwargs={"distance_moved": 1},
        carrier_id=handler,
        ball_space=destination,
        handler_space=destination,
        exhaustion={handler: 2},
        ball_speed=12,
    )


def burst_playmaker_one_space_is_free() -> DribbleFixture:
    """
    A Playmaker's single space costs nothing -- the discount floors
    the charge at 0 rather than handing a token back -- so the saving
    is still named and there is no exhaustion line under it.
    """
    match = build_match()
    handler = put_on_the_ball(match, fielded(match, PlayerRole.PLAYMAKER))
    origin = match.board.flat_index(match.ball.zone, match.ball.space_index)
    destination = match.board.position_at_flat_index(
        match.relative_flat_index(origin, TeamSide.HOME, 1)
    )
    return DribbleFixture(
        game=build_game(),
        match=match,
        key="dribble_burst",
        distance=1,
        narration=(
            f"**Dribble Burst:** {label(match, handler)} bursts 1 "
            "space forward, past everyone in the way."
            " That costs them a token less (Playmaker ability)."
            f" {BURST_SPEED_LINE}"
        ),
        follow_on=FINISH,
        follow_on_kwargs={"distance_moved": 1},
        carrier_id=handler,
        ball_space=destination,
        handler_space=destination,
        exhaustion={handler: 0},
        ball_speed=12,
    )


def burst_with_nowhere_to_go() -> DribbleFixture:
    """
    The handler is already as far forward as the field goes, so the
    burst is said plainly rather than reported as a run of 0 spaces --
    and a run that moved nowhere is free for everybody, Playmaker or
    not.
    """
    match = build_match()
    handler = fielded(match, PlayerRole.MIDFIELDER)
    walk_to_the_far_end(match, handler)
    put_on_the_ball(match, handler)
    where = match.board.meeple_position(handler)
    return DribbleFixture(
        game=build_game(),
        match=match,
        key="dribble_burst",
        distance=0,
        narration=(
            f"**Dribble Burst:** {label(match, handler)} is already as "
            "far forward as the field goes, so the ball stays where it "
            "is."
            f" {BURST_SPEED_LINE}"
        ),
        follow_on=FINISH,
        follow_on_kwargs={"distance_moved": 1},
        carrier_id=handler,
        ball_space=where,
        handler_space=where,
        exhaustion={handler: 0},
        ball_speed=12,
    )


def burst_beats_a_clear() -> DribbleFixture:
    """
    **Clear's cost** on the other card of the rank. Worth its own
    fixture rather than trusting the advance's: the burst has an
    exhaustion line of its own above it, so this is also where the two
    charges are pinned in the right order.
    """
    match = build_match()
    handler = put_on_the_ball(match, fielded(match, PlayerRole.MIDFIELDER))
    defender = stand_a_beaten_clear(match, "dribble_burst")
    origin = match.board.flat_index(match.ball.zone, match.ball.space_index)
    destination = match.board.position_at_flat_index(
        match.relative_flat_index(origin, TeamSide.HOME, 2)
    )
    return DribbleFixture(
        game=build_game(mode=GameMode.ADVANCED, species_abilities=False),
        match=match,
        key="dribble_burst",
        distance=2,
        narration=(
            f"**Dribble Burst:** {label(match, handler)} bursts 2 "
            "spaces forward, past everyone in the way."
            f"\n{label(match, handler)} gains 2 exhaustion tokens "
            f"{EXHAUST * 2} (now 2 total)."
            "\n\n**Clear** was beaten -- 2 exhaustion.\n"
            f"{label(match, defender)} gains 2 exhaustion tokens "
            f"{EXHAUST * 2} (now 3 total)."
            f"\n{label(match, defender)} is now *exhausted* {EXHAUSTED}"
            f" {BURST_SPEED_LINE}"
        ),
        follow_on=FINISH,
        follow_on_kwargs={"distance_moved": 1},
        carrier_id=handler,
        ball_space=destination,
        handler_space=destination,
        exhaustion={handler: 2, defender: 3},
        ball_speed=12,
    )


def burst_with_the_ball_already_at_twelve() -> DribbleFixture:
    """
    The speed is said only where it changed -- a move that costs
    nothing says nothing, and a ball already at 12 is left there
    without a line about it.
    """
    match = build_match()
    handler = put_on_the_ball(match, fielded(match, PlayerRole.MIDFIELDER))
    match.ball.speed = 12
    origin = match.board.flat_index(match.ball.zone, match.ball.space_index)
    destination = match.board.position_at_flat_index(
        match.relative_flat_index(origin, TeamSide.HOME, 1)
    )
    return DribbleFixture(
        game=build_game(),
        match=match,
        key="dribble_burst",
        distance=1,
        narration=(
            f"**Dribble Burst:** {label(match, handler)} bursts 1 "
            "space forward, past everyone in the way."
            f"\n{label(match, handler)} gains 1 exhaustion token "
            f"{EXHAUST} (now 1 total)."
        ),
        follow_on=FINISH,
        follow_on_kwargs={"distance_moved": 1},
        carrier_id=handler,
        ball_space=destination,
        handler_space=destination,
        exhaustion={handler: 1},
        ball_speed=12,
    )


DRIBBLE_CASES: tuple[DribbleCase, ...] = (
    DribbleCase("advance_plain", advance_plain),
    DribbleCase("advance_playmaker_two", advance_playmaker_two),
    DribbleCase("advance_playmaker_one", advance_playmaker_one),
    DribbleCase(
        "advance_clamped_at_the_far_end", advance_clamped_at_the_far_end,
    ),
    DribbleCase("advance_beats_a_clear", advance_beats_a_clear),
    DribbleCase("burst_plain", burst_plain),
    DribbleCase("burst_playmaker_discount", burst_playmaker_discount),
    DribbleCase(
        "burst_playmaker_one_space_is_free",
        burst_playmaker_one_space_is_free,
    ),
    DribbleCase("burst_with_nowhere_to_go", burst_with_nowhere_to_go),
    DribbleCase("burst_beats_a_clear", burst_beats_a_clear),
    DribbleCase(
        "burst_with_the_ball_already_at_twelve",
        burst_with_the_ball_already_at_twelve,
    ),
)
