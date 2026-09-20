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

Rank O1 of Phase 3 (Skilled Pass and the shared `key=`) added the
second table at the bottom, `FAILED_PASS_CASES`. A pass with nobody in
reach never reaches `apply_low_pass` at all -- `resolve_low_pass`
handled it inline -- so it is a different entry point and a different
follow-on, and it gets its own fixture shape rather than four unused
fields on the one above.
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
#: And the one a pass with nobody to receive it ends on instead.
LOOSE_BALL = "BEGIN_LOOSE_BALL"


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


@dataclass
class FailedPassFixture:
    """
    One match mid-pass with nobody in reach, and what resolving it
    should produce.

    A separate shape from `LowPassFixture` because it is a separate
    entry point: the branch is reached through `resolve_low_pass`
    rather than `apply_low_pass`, it names a different follow-on, and
    no receiver is chosen for it. The fields it does share are spelled
    the same way, so the two tables read alike.
    """

    game: D12BallGame
    match: MatchState
    key: str = "low_pass"
    free: bool = False

    #: The narration, as one string: what the old cog built inline and
    #: handed `begin_loose_ball` as its `lead_in`.
    narration: str = ""
    #: False for every branch here, and deliberately: the loose ball
    #: draws this same board under its own announcement, so a refresh
    #: from the pass would be a second write of an identical board.
    #: See "Discord's rate limits" in docs/design/rate-limits.md.
    board_changed: bool = False
    #: Which step runs next, by `FollowOnStep` member name.
    follow_on: str = LOOSE_BALL
    #: The arguments that step is called with, `lead_in` aside.
    follow_on_kwargs: dict[str, Any] = field(
        default_factory=lambda: {"distance_moved": 1},
    )

    #: What the match looks like afterwards. Nobody carries a loose
    #: ball, so there is no carrier to name.
    ball_space: Optional[tuple[Zone, int]] = None
    ball_speed: int = 0


@dataclass(frozen=True)
class LowPassCase:
    """A fixture and the name it is reported under."""

    name: str
    build: Callable[[], LowPassFixture]


@dataclass(frozen=True)
class FailedPassCase:
    """A failed-pass fixture and the name it is reported under."""

    name: str
    build: Callable[[], FailedPassFixture]


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


def stand_the_handler_at(
    match: MatchState,
    flat_index: int,
    side: TeamSide = TeamSide.HOME,
) -> str:
    """
    Put the dealt handler on a named space of the board with the ball,
    and hand back who it is.

    `take_the_ball` leaves them where the standard deal put them,
    which is mid-field and in reach of most of their side; a pass with
    nobody to receive it needs the handler somewhere specific, and the
    space is named by flat index because what matters is the distance
    to everyone else rather than the zone it falls in.
    """
    zone, space_index = match.board.position_at_flat_index(flat_index)
    # Chosen off the side's own roster rather than through
    # `eligible_ball_handlers`, which reads whoever is standing on the
    # ball's *current* space -- and the whole point here is to move the
    # ball somewhere nobody is.
    team = match.home if side is TeamSide.HOME else match.visiting
    handler = team.field_players[0]
    match.move_meeple(handler, zone, space_index)
    match.set_ball_space(zone, space_index)
    match.ball.possession = side
    match.select_ball_handler(handler)
    return handler


def park_the_rest(
    match: MatchState,
    flat_indices: list[int],
    side: TeamSide = TeamSide.HOME,
) -> None:
    """
    Walk every other player of `side` out to the given spaces, so the
    handler has nobody in reach of a pass.

    They stack: occupancy is coverage rather than a limit, so three
    teammates on one space is a legal position and the shortest way to
    empty the field around the ball -- see
    docs/design/formations-and-occupancy.md.
    """
    others = [
        player_id
        for player_id in (
            match.home if side is TeamSide.HOME else match.visiting
        ).field_players
        if player_id != match.active_player_id
    ]
    for index, player_id in enumerate(others):
        zone, space_index = match.board.position_at_flat_index(
            flat_indices[index % len(flat_indices)]
        )
        match.move_meeple(player_id, zone, space_index)


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


def contested_in_a_basic_game() -> LowPassFixture:
    """
    The same pass with a defender having actually played a card
    against it. Nothing about the resolution reads the contest -- the
    cost is the *loser's* card and a basic one owes none -- and that
    is what is pinned: a contested basic pass says exactly what an
    unchallenged one says.
    """
    match = build_match()
    take_the_ball(match)
    match.ball.speed = 1
    challenger = min(match.visiting.field_players, key=match.distance_to_ball)
    match.choose_challenger(challenger)
    match.choose_offense_maneuver("low_pass")
    match.choose_defense_maneuver("pressure")
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


# -- The same branches, played as a Skilled Pass -----------------------


def skilled_pass_shared_space() -> LowPassFixture:
    """
    Skilled Pass across a shared space. The reach the card buys is no
    help at distance 0, so what changes from `shared_space` is the
    banner and the +3 -- the passer still steps forward and the ball
    still does not travel.
    """
    match = build_match()
    handler = take_the_ball(match)
    match.ball.speed = 4
    receiver = fielded(match, PlayerRole.MIDFIELDER)
    stand_at(match, receiver, 0)
    return LowPassFixture(
        game=build_game(mode=GameMode.ADVANCED),
        match=match,
        distance=0,
        receiver_id=receiver,
        key="skilled_pass",
        narration=(
            "**Skilled Pass:** the ball goes to a teammate in the same "
            f"space, and {label(match, handler)} moves a space forward. "
            "Ball speed is now 7."
        ),
        follow_on_kwargs={"distance_moved": 1},
        carrier_id=receiver,
        ball_space=(Zone.MIDFIELD, 1),
        ball_speed=7,
    )


def skilled_pass_winger_set_up() -> LowPassFixture:
    """
    A Winger's set-up off a Skilled Pass -- the one branch that ends
    somewhere other than `finish_maneuver_resolution`, reached with
    the other key. The ability is the passer's role and the shot is
    the receiver's, neither of which the card changes.
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
        game=build_game(mode=GameMode.ADVANCED),
        match=match,
        distance=1,
        receiver_id=receiver,
        key="skilled_pass",
        narration=(
            "**Skilled Pass:** the ball moves 1 space forward. "
            "Ball speed is now 4. "
            f"{label(match, winger)}'s Winger ability can turn this "
            "into a scoring opportunity!"
        ),
        follow_on=SCORING_CHOICE,
        follow_on_kwargs={"distance_moved": 1, "shooter_id": receiver},
        carrier_id=receiver,
        ball_space=(Zone.VISITORS_GOAL, 1),
        ball_speed=4,
    )


def skilled_pass_beats_double_team() -> LowPassFixture:
    """
    **Double Team's cost** charged inside a Skilled Pass rather than a
    Low Pass. The cost is the beaten card's, so it is read off the
    loser and not off the winner -- which is the thing worth pinning
    on the second key, since `advanced_cost` is asked with the
    winner's.
    """
    match = build_match()
    take_the_ball(match)
    match.ball.speed = 1
    challenger = min(match.visiting.field_players, key=match.distance_to_ball)
    match.choose_challenger(challenger)
    match.choose_offense_maneuver("skilled_pass")
    match.choose_defense_maneuver("double_team")
    partner = ENGINE.double_team_partner(match)
    receiver = fielded(match, PlayerRole.WINGER)
    stand_at(match, receiver, 2)
    return LowPassFixture(
        game=build_game(mode=GameMode.ADVANCED),
        match=match,
        distance=2,
        receiver_id=receiver,
        key="skilled_pass",
        narration=(
            "**Skilled Pass:** the ball moves 2 spaces forward. "
            "Ball speed is now 4."
            "\n\n**Double Team** was beaten -- "
            f"{label(match, challenger)} and {label(match, partner)} "
            "are each shoved a space forward, away from their own goal."
        ),
        follow_on_kwargs={"distance_moved": 1},
        carrier_id=receiver,
        ball_space=(Zone.VISITORS_GOAL, 0),
        ball_speed=4,
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
    LowPassCase("contested_in_a_basic_game", contested_in_a_basic_game),
    LowPassCase("skilled_pass_shared_space", skilled_pass_shared_space),
    LowPassCase("skilled_pass_winger_set_up", skilled_pass_winger_set_up),
    LowPassCase(
        "skilled_pass_beats_double_team", skilled_pass_beats_double_team,
    ),
)


# -- The pass with nobody to receive it ---------------------------------


def low_pass_with_no_receiver() -> FailedPassFixture:
    """
    A handler with no teammate within two spaces has won the maneuver
    and has nowhere to put the ball. The ball goes a space forward and
    is loose, and its speed still rises -- the bonus does not depend
    on the pass finding anyone (2026-08-07).

    The board is not redrawn here: the loose ball draws the same board
    under its own announcement.
    """
    match = build_match()
    stand_the_handler_at(match, 3)
    park_the_rest(match, [0, 6])
    match.ball.speed = 1
    return FailedPassFixture(
        game=build_game(),
        match=match,
        narration=(
            "**Low Pass:** there is no teammate within two spaces to "
            "receive it, and a pass can't be played to the passer -- "
            "the ball rolls a space forward. Ball speed is now 2."
        ),
        ball_space=(Zone.MIDFIELD, 2),
        ball_speed=2,
    )


def skilled_pass_with_no_receiver() -> FailedPassFixture:
    """
    The same branch on the other key, and the one place the two cards
    are worded differently: Skilled Pass reaches any teammate within
    `SKILLED_PASS_REACH`, so a Skilled Pass that finds nobody has
    nobody on the field to find rather than nobody within two spaces.
    The speed bonus is still the card's own +3.
    """
    match = build_match()
    stand_the_handler_at(match, 0)
    park_the_rest(match, [4, 5, 6])
    match.ball.speed = 4
    return FailedPassFixture(
        game=build_game(mode=GameMode.ADVANCED),
        match=match,
        key="skilled_pass",
        narration=(
            "**Skilled Pass:** there is nobody on the field to receive "
            "it, and a pass can't be played to the passer -- the ball "
            "rolls a space forward. Ball speed is now 7."
        ),
        ball_space=(Zone.HOME_GOAL, 1),
        ball_speed=7,
    )


def no_receiver_at_the_far_end() -> FailedPassFixture:
    """
    The same branch with nowhere for the ball to roll: the handler is
    already on the last space of the field they attack, so the ball is
    loose where it is standing. The speed still rises, and it is
    capped at 12 like every speed change -- which is what the 12 here
    pins.
    """
    match = build_match()
    stand_the_handler_at(match, 6)
    park_the_rest(match, [0, 1, 2])
    match.ball.speed = 12
    return FailedPassFixture(
        game=build_game(),
        match=match,
        narration=(
            "**Low Pass:** there is no teammate within two spaces to "
            "receive it, and a pass can't be played to the passer -- "
            "the ball stays where it is. Ball speed is now 12."
        ),
        ball_space=(Zone.VISITORS_GOAL, 1),
        ball_speed=12,
    )


def free_pass_with_no_receiver() -> FailedPassFixture:
    """
    The unopposed pass **Skilled Pass's cost** hands the defense,
    played with nobody in reach.

    **This branch does not read `free` at all**, and the fixture
    records that rather than correcting it: the clock is charged a
    space minute where a completed free pass charges none, and the
    continuation that produced it is left standing where applying a
    free pass spends it. Both are questions for the author, raised in
    the pull request and not answered here -- see `low_pass_step`,
    which does read it.
    """
    match = build_match()
    passer = stand_the_handler_at(match, 3, TeamSide.VISITING)
    park_the_rest(match, [0, 6], TeamSide.VISITING)
    match.ball.speed = 1
    match.pending_effect_continuation = {
        "kind": "free_low_pass",
        "player_id": passer,
    }
    return FailedPassFixture(
        game=build_game(mode=GameMode.ADVANCED),
        match=match,
        free=True,
        narration=(
            "**Low Pass:** there is no teammate within two spaces to "
            "receive it, and a pass can't be played to the passer -- "
            "the ball rolls a space forward. Ball speed is now 2."
        ),
        # The visitors attack from high flat indices to low, so a space
        # forward from midfield 1 is midfield 0.
        ball_space=(Zone.MIDFIELD, 0),
        ball_speed=2,
    )


FAILED_PASS_CASES: tuple[FailedPassCase, ...] = (
    FailedPassCase("low_pass_with_no_receiver", low_pass_with_no_receiver),
    FailedPassCase(
        "skilled_pass_with_no_receiver", skilled_pass_with_no_receiver,
    ),
    FailedPassCase("no_receiver_at_the_far_end", no_receiver_at_the_far_end),
    FailedPassCase("free_pass_with_no_receiver", free_pass_with_no_receiver),
)
