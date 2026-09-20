"""
A match standing in each branch a Low Pass resolves through, and what
that resolution should produce.

Phase 2 of docs/model-discord-split.md moves Low Pass's own resolution
out of the cog and into `d12ball/flow/effects.py`. The thing worth
asserting about a move like that is that **not one branch changed what
it said or what it did next**, and that needs one table standing in
every branch rather than the scattered assertions the suite already
had.

So the fixtures live here, built with no `discord` in scope, and two
test modules read the same table:

- `tests/test_d12ball_low_pass_flow.py` asks the model
  (`d12ball.flow.effects.low_pass_step`) for the `StepResult`.
- `tests/test_d12ball_low_pass_recording.py` asks the cog
  (`D12Ball.apply_low_pass`) what it handed the step that comes next.

The second one is the equivalence test, and it is the same shape
`tests/prompt_fixtures.py` gave Phase 1: it was written and run green
against the **old** cog before anything moved, so a green run after the
move is the two answering the same way rather than two halves of one
new thing agreeing with each other. Its commit is the first on the
branch for exactly that reason.

**The expected narration is built, never spelled out, wherever it names
a player** -- the roster is data the author revises (see `roster.py`),
and a fixture holding `Sizzifizik` would break on the next rename for
no reason connected to passing. The wording around the name is the
assertion; the name inside it is not. The numbers in it are spelled
out, because a ball speed the fixture set and a distance the fixture
chose are facts about the fixture rather than about the roster.

**The follow-on step is named by its `FollowOnStep` member name**, a
string, so this module needs no import from `d12ball/flow/` -- which is
what let it be written before that package existed.
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

#: The two follow-on steps a Low Pass can end on, by `FollowOnStep`
#: member name. Spelled as strings so this module stays free of the
#: package under test -- see the note on the roster above.
FINISH = "FINISH_MANEUVER_RESOLUTION"
SCORING_CHOICE = "OFFER_SCORING_ATTEMPT_CHOICE"


@dataclass
class LowPassFixture:
    """One match mid-Low-Pass, and everything resolving it should say."""

    game: D12BallGame
    match: MatchState
    distance: int
    receiver_id: Optional[str] = None
    key: str = "low_pass"
    free: bool = False

    #: The narration, as one string: what the old cog built inline and
    #: handed the next step as its `lead_in`.
    narration: str = ""
    #: Whether the board moved -- what `refresh_match_image` decided.
    board_changed: bool = True
    #: Which step runs next, by `FollowOnStep` member name.
    follow_on: str = FINISH
    #: The arguments that step is called with, `lead_in` aside.
    follow_on_kwargs: dict[str, Any] = field(default_factory=dict)

    #: What the match looks like afterwards.
    carrier_id: Optional[str] = None
    ball_space: Optional[tuple[Zone, int]] = None
    ball_speed: int = 0


@dataclass(frozen=True)
class LowPassCase:
    """A fixture and the name it is reported under."""

    name: str
    build: Callable[[], LowPassFixture]


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


def take_the_ball(match: MatchState) -> str:
    """Put the standard deal's handler on the ball."""
    match.select_ball_handler(match.eligible_ball_handlers()[0])
    return match.active_player_id


def stand_at(
    match: MatchState,
    player_id: str,
    distance: int,
    side: TeamSide = TeamSide.HOME,
) -> tuple[Zone, int]:
    """
    Walk a player to the space `distance` ahead of the ball, and hand
    back where that is. The standard deal decides where everybody
    starts, and a test about a pass should not also be a test of the
    deal.
    """
    origin = match.board.flat_index(match.ball.zone, match.ball.space_index)
    zone, space_index = match.board.position_at_flat_index(
        match.relative_flat_index(origin, side, distance)
    )
    match.move_meeple(player_id, zone, space_index)
    return zone, space_index


# -- The ordinary pass -------------------------------------------------


def plain_forward() -> LowPassFixture:
    """
    Two spaces up the field to the one teammate standing there. The
    baseline every other case is a variation on.
    """
    match = build_match()
    take_the_ball(match)
    match.ball.speed = 1
    receiver = fielded(match, PlayerRole.WINGER)
    stand_at(match, receiver, 2)
    return LowPassFixture(
        game=build_game(),
        match=match,
        distance=2,
        receiver_id=receiver,
        narration=(
            "**Low Pass:** the ball moves 2 spaces forward. "
            "Ball speed is now 2."
        ),
        follow_on_kwargs={"distance_moved": 1},
        carrier_id=receiver,
        ball_space=(Zone.VISITORS_GOAL, 0),
        ball_speed=2,
    )


def backward_pass() -> LowPassFixture:
    """
    A pass the other way. The only difference is the word, and it is
    worth pinning because the direction is chosen from the sign of the
    distance rather than from where the ball ended up.
    """
    match = build_match()
    take_the_ball(match)
    match.ball.speed = 5
    receiver = fielded(match, PlayerRole.MIDFIELDER)
    stand_at(match, receiver, -1)
    return LowPassFixture(
        game=build_game(),
        match=match,
        distance=-1,
        receiver_id=receiver,
        narration=(
            "**Low Pass:** the ball moves 1 space backward. "
            "Ball speed is now 6."
        ),
        follow_on_kwargs={"distance_moved": 1},
        carrier_id=receiver,
        ball_space=(Zone.MIDFIELD, 0),
        ball_speed=6,
    )


def shared_space() -> LowPassFixture:
    """
    A pass of 0 crosses a shared space, so the ball does not travel and
    the passer steps forward instead (2026-08-07). It is the one branch
    whose wording names a player, which is why the label is built.
    """
    match = build_match()
    handler = take_the_ball(match)
    match.ball.speed = 1
    receiver = fielded(match, PlayerRole.MIDFIELDER)
    stand_at(match, receiver, 0)
    return LowPassFixture(
        game=build_game(),
        match=match,
        distance=0,
        receiver_id=receiver,
        narration=(
            "**Low Pass:** the ball goes to a teammate in the same "
            f"space, and {label(match, handler)} moves a space forward. "
            "Ball speed is now 2."
        ),
        follow_on_kwargs={"distance_moved": 1},
        carrier_id=receiver,
        ball_space=(Zone.MIDFIELD, 1),
        ball_speed=2,
    )


def stacked_destination() -> LowPassFixture:
    """
    Two teammates on the landing space, and the passer picked the
    second of them. The pick is what decides the carrier -- not
    whoever the occupant list happens to start with.
    """
    match = build_match()
    take_the_ball(match)
    match.ball.speed = 1
    first = fielded(match, PlayerRole.WINGER)
    second = fielded(match, PlayerRole.STRIKER)
    stand_at(match, first, 2)
    stand_at(match, second, 2)
    return LowPassFixture(
        game=build_game(),
        match=match,
        distance=2,
        receiver_id=second,
        narration=(
            "**Low Pass:** the ball moves 2 spaces forward. "
            "Ball speed is now 2."
        ),
        follow_on_kwargs={"distance_moved": 1},
        carrier_id=second,
        ball_space=(Zone.VISITORS_GOAL, 0),
        ball_speed=2,
    )


# -- The Winger's set-up -----------------------------------------------


def winger_set_up() -> LowPassFixture:
    """
    Role ability -- a Winger's pass can turn into a scoring
    opportunity right where it lands, and the shot is offered to
    whoever received it. The one branch that ends somewhere other than
    `finish_maneuver_resolution`.
    """
    match = build_match()
    winger = fielded(match, PlayerRole.WINGER)
    zone, space_index = match.board.meeple_position(winger)
    match.set_ball_space(zone, space_index)
    match.ball.possession = TeamSide.HOME
    match.select_ball_handler(winger)
    match.ball.speed = 1
    receiver = fielded(match, PlayerRole.STRIKER)
    stand_at(match, receiver, 1)
    return LowPassFixture(
        game=build_game(),
        match=match,
        distance=1,
        receiver_id=receiver,
        narration=(
            "**Low Pass:** the ball moves 1 space forward. "
            "Ball speed is now 2. "
            f"{label(match, winger)}'s Winger ability can turn this "
            "into a scoring opportunity!"
        ),
        follow_on=SCORING_CHOICE,
        follow_on_kwargs={"distance_moved": 1, "shooter_id": receiver},
        carrier_id=receiver,
        ball_space=(Zone.VISITORS_GOAL, 1),
        ball_speed=2,
    )


# -- The two continuations ---------------------------------------------


def free_pass_off_a_beaten_skilled_pass() -> LowPassFixture:
    """
    **Skilled Pass's cost**: the defense stole the ball and now plays
    an unopposed Low Pass with it. Applying the pass is what spends the
    continuation, and the clock was already charged on the steal that
    produced it -- so this is the one branch that moves no space
    minute.
    """
    match = build_match()
    passer = fielded(match, PlayerRole.MIDFIELDER, TeamSide.VISITING)
    zone, space_index = match.board.meeple_position(passer)
    match.set_ball_space(zone, space_index)
    match.ball.possession = TeamSide.VISITING
    match.select_ball_handler(passer)
    match.ball.speed = 4
    match.pending_effect_continuation = {
        "kind": "free_low_pass",
        "player_id": passer,
    }
    receiver = fielded(match, PlayerRole.DEFENDER, TeamSide.VISITING)
    stand_at(match, receiver, 1, TeamSide.VISITING)
    return LowPassFixture(
        game=build_game(),
        match=match,
        distance=1,
        receiver_id=receiver,
        free=True,
        narration=(
            "**Low Pass:** the ball moves 1 space forward. "
            "Ball speed is now 5."
        ),
        follow_on_kwargs={"distance_moved": 0},
        carrier_id=receiver,
        # The visitors attack from high flat indices to low, so their
        # midfielder's own space is midfield 2 and a space forward is
        # midfield 1.
        ball_space=(Zone.MIDFIELD, 1),
        ball_speed=5,
    )


def skilled_pass() -> LowPassFixture:
    """
    Skilled Pass is a Low Pass with three times the speed bonus and a
    space more reach, resolved by the same function -- so what is
    pinned here is the name on the banner and the +3.
    """
    match = build_match()
    take_the_ball(match)
    match.ball.speed = 4
    receiver = fielded(match, PlayerRole.WINGER)
    stand_at(match, receiver, 2)
    return LowPassFixture(
        game=build_game(),
        match=match,
        distance=2,
        receiver_id=receiver,
        key="skilled_pass",
        narration=(
            "**Skilled Pass:** the ball moves 2 spaces forward. "
            "Ball speed is now 7."
        ),
        follow_on_kwargs={"distance_moved": 1},
        carrier_id=receiver,
        ball_space=(Zone.VISITORS_GOAL, 0),
        ball_speed=7,
    )


# -- The cost the pass collects ----------------------------------------


def double_team_cost() -> LowPassFixture:
    """
    **Double Team's cost**, charged inside the pass that beat it: the
    defender who played it and the teammate who would have joined them
    are each shoved a space forward. It is paid in the middle of this
    step's own wording, which is why it belongs to the move rather than
    to whatever runs next.
    """
    match = build_match()
    take_the_ball(match)
    match.ball.speed = 1
    challenger = min(match.visiting.field_players, key=match.distance_to_ball)
    match.choose_challenger(challenger)
    match.choose_offense_maneuver("low_pass")
    match.choose_defense_maneuver("double_team")
    partner = ENGINE.double_team_partner(match)
    receiver = fielded(match, PlayerRole.WINGER)
    stand_at(match, receiver, 2)
    return LowPassFixture(
        game=build_game(mode=GameMode.ADVANCED),
        match=match,
        distance=2,
        receiver_id=receiver,
        narration=(
            "**Low Pass:** the ball moves 2 spaces forward. "
            "Ball speed is now 2."
            "\n\n**Double Team** was beaten -- "
            f"{label(match, challenger)} and {label(match, partner)} "
            "are each shoved a space forward, away from their own goal."
        ),
        follow_on_kwargs={"distance_moved": 1},
        carrier_id=receiver,
        ball_space=(Zone.VISITORS_GOAL, 0),
        ball_speed=2,
    )


LOW_PASS_CASES: tuple[LowPassCase, ...] = (
    LowPassCase("plain_forward", plain_forward),
    LowPassCase("backward_pass", backward_pass),
    LowPassCase("shared_space", shared_space),
    LowPassCase("stacked_destination", stacked_destination),
    LowPassCase("winger_set_up", winger_set_up),
    LowPassCase(
        "free_pass_off_a_beaten_skilled_pass",
        free_pass_off_a_beaten_skilled_pass,
    ),
    LowPassCase("skilled_pass", skilled_pass),
    LowPassCase("double_team_cost", double_team_cost),
)
