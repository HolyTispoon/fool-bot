"""
A match standing in each branch a Deflect or a Clear resolves through,
and what that resolution should produce.

Rank D1 of Phase 3 of docs/model-discord-split.md moves the two cards'
own resolution out of the cog and into `d12ball/flow/effects.py`. The
thing worth asserting about a move like that is that **not one branch
changed what it said or what it did next**, and that needs one table
standing in every branch rather than the scattered assertions the
suite already had.

So the fixtures live here, built with no `discord` in scope, and two
test modules read the same table:

- `tests/test_d12ball_deflect_flow.py` asks the model
  (`d12ball.flow.effects.deflect_step`) for the `StepResult`.
- `tests/test_d12ball_deflect_recording.py` asks the cog
  (`D12Ball.apply_deflection`) what it handed the step that comes
  next.

The second one is the equivalence test, and it is the shape
`tests/low_pass_fixtures.py` gave Phase 2, `tests/dribble_fixtures.py`
rank O2, `tests/steal_fixtures.py` rank D2 and `tests/pressure_fixtures.py`
rank D3: it was written and run green against the **old** cog before
anything moved, so a green run afterwards is the two answering the same
way rather than two halves of one new thing agreeing with each other.
Its commit is the first on the branch for exactly that reason.

**Rank D1 has no unchallenged branch**, the same as D2 and D3: a
defense card only resolves where a defender was sent, so every fixture
here has a challenger and `match.challenger_id` is who the deflection
is played by.

**The board and the refresh are two columns, not one.** Every branch
of this rank moves the ball, so `board_changed` is True throughout --
but the old cog refreshed the persistent board message on exactly one
of them. The other two hand over to something that draws the board
itself under its own announcement, and a refresh first would write the
same board twice (see "Discord's rate limits" in
docs/design/rate-limits.md). So `board_changed` records what the model
says about the position and `refreshes` records what the cog wrote,
and rank D1 is where the two stopped being the same number -- see
`D12Ball.follow_on_posts_its_own_board`.

**The expected narration is built, never spelled out, wherever it
names a card** -- the maneuver catalog is data the author revises. The
distances and the speeds are spelled out, because a distance the
fixture chose is a fact about the fixture rather than about the data.

**The follow-on step is named by its `FollowOnStep` member name**, a
string, so this module needs no import from `d12ball/flow/` -- which
is what lets it be written before `BEGIN_LOOSE_BALL` and
`OFFER_SETUP_PASS_PUSH_BACK` exist.
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

#: Where a deflection ordinarily ends: the ball is out of everybody's
#: possession on the space it stopped on, and who -- if anyone -- comes
#: away with it is occupancy's question. By `FollowOnStep` member name,
#: spelled as a string so this module stays free of the package under
#: test.
LOOSE_BALL = "BEGIN_LOOSE_BALL"

#: The overshoot's ending instead: the ball reached the space closest
#: to the offense's own goal, and a defender standing there is next to
#: a goal with the ball at their feet.
SHOOTER_CHOICE = "BEGIN_SHOOTER_CHOICE"

#: **Setup Pass's cost**: the coach who beat the card drives the ball a
#: further 1, 2 or 3 spaces back before it is loose. A follow-on rather
#: than a prompt the step returns, because whether anybody is asked at
#: all is still the cog's decision -- Dinky answers for itself, and a
#: push with no room left is not offered.
PUSH_BACK = "OFFER_SETUP_PASS_PUSH_BACK"


@dataclass
class DeflectFixture:
    """One match mid-deflection, and everything resolving it should say."""

    game: D12BallGame
    match: MatchState
    #: Which card: `deflect` or `clear`.
    key: str
    #: The handler holding the ball -- `match.active_player_id`, held
    #: here so the assertions can name them afterwards.
    handler_id: str
    #: The defender playing the card -- `match.challenger_id`.
    challenger_id: str

    #: The narration, as one string: what the old cog built inline and
    #: handed the next step as its `lead_in`. Every branch of this rank
    #: hands it over; none of them posts a message of its own.
    narration: str = ""
    #: Whether the board moved. True on every branch -- a deflection
    #: always takes speed off the ball even where the field clamped
    #: the distance to nothing.
    board_changed: bool = True
    #: How many times the old cog redrew the persistent board message.
    #: 1 on the overshoot, 0 everywhere else, and the reason is the
    #: module docstring's.
    refreshes: int = 0
    #: Which step runs next, by `FollowOnStep` member name.
    follow_on: str = LOOSE_BALL
    #: The arguments that step is called with, `lead_in` aside.
    follow_on_kwargs: dict[str, Any] = field(
        default_factory=lambda: {"distance_moved": 1},
    )

    #: What the match looks like afterwards. **Nobody carries the ball
    #: on any branch**: moving it knocks it out of the handler's
    #: possession, which is the rule this card is named for -- so this
    #: is None throughout and asserted rather than assumed.
    carrier_id: Optional[str] = None
    possession: TeamSide = TeamSide.HOME
    ball_space: Optional[tuple[Zone, int]] = None
    ball_speed: int = 1


@dataclass(frozen=True)
class DeflectCase:
    """A fixture and the name it is reported under."""

    name: str
    build: Callable[[], DeflectFixture]


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


def advanced_game() -> D12BallGame:
    """
    An advanced game with species abilities off, so nothing but the
    card under test reads into the resolution -- the same guard
    `tests/steal_fixtures.py` and `tests/pressure_fixtures.py` put on
    their advanced fixtures.
    """
    return build_game(mode=GameMode.ADVANCED, species_abilities=False)


def build_match(board_size: int = 9) -> MatchState:
    """
    A standard deal on board 9. **Nine rather than seven**, because a
    Clear drives the ball three spaces and a Fullback's four: on the
    short board the ordinary case would clamp at the end of the field
    and every Clear fixture would be an overshoot.
    """
    return MatchState.standard(
        catalog=CATALOG,
        ruleset=RULESET,
        board_size=board_size,
        home_team=Team.ORANGE,
        visiting_team=Team.PURPLE,
        home_formation=Formation.TWO_TWO_TWO,
    )


def ball_flat(match: MatchState) -> int:
    return match.board.flat_index(match.ball.zone, match.ball.space_index)


def deflected_to(match: MatchState, distance: int):
    """
    Where a deflection of `distance` leaves the ball, clamped at the
    end of the field the way `move_ball_relative` clamps it.
    """
    origin = ball_flat(match)
    return match.board.position_at_flat_index(
        match.relative_flat_index(origin, match.ball.possession, -distance)
    )


def deflected_distance(match: MatchState, distance: int) -> int:
    """
    How far that deflection actually travels once the board has
    clamped it.
    """
    origin = ball_flat(match)
    target = match.board.flat_index(*deflected_to(match, distance))
    return abs(target - origin)


def deflect_text(
    match: MatchState,
    key: str,
    actual_distance: int,
    speed_after: int,
    fullback: bool = False,
) -> str:
    """
    The sentence both cards share, built rather than spelled out.

    `speed_after` is the speed the *deflection* left on the ball, which
    on the overshoot branch is not the speed the match ends on: the
    turnover that follows resets it to 1 after the sentence has been
    worded. That ordering is the whole reason this takes the number
    rather than reading `match.ball.speed` back.
    """
    space_word = "space" if actual_distance == 1 else "spaces"
    ability_note = " (Fullback ability)" if fullback else ""
    return (
        f"**{ENGINE.maneuver_name(key)}:** the ball moves "
        f"{actual_distance} {space_word} back{ability_note}. Ball speed "
        f"is now {speed_after}."
    )


#: What an overshooting deflection adds. It rides inside the
#: deflection's own block, joined on the single space the cog joins
#: narration with.
OVERSHOOT_NOTE = "That overshoots the field -- a scoring opportunity!"


def stand_a_deflection(
    offense_key: str,
    defense_key: str,
    role: PlayerRole = PlayerRole.MIDFIELDER,
    back_from_own_goal: Optional[int] = None,
    ball_speed: int = 1,
    board_size: int = 9,
) -> tuple[MatchState, str, str]:
    """
    A match mid-maneuver with the defense's card the winning one: the
    handler, and the defender standing on them who played it.

    The challenger is **placed** on the ball's space rather than walked
    there by `choose_challenger`, for the reason
    `tests/pressure_fixtures.py` places its own: a walk charges
    exhaustion for the distance, and which role is standing there is
    the whole difference between two of these fixtures. A deflection is
    role-sensitive -- a Fullback drives the ball one space further --
    so `role` is a parameter rather than "the nearest".

    `back_from_own_goal` parks the handler and the ball that many
    spaces out from the last space toward the offense's own goal,
    before the challenger is placed. 0 is the only space a Deflect can
    overshoot from; a Clear overshoots from anywhere inside three.
    """
    match = build_match(board_size)
    handler = match.eligible_ball_handlers()[0]
    match.select_ball_handler(handler)
    if back_from_own_goal is not None:
        zone, space_index = match.own_goal_restart_space(TeamSide.HOME)
        match.move_meeple(handler, zone, space_index)
        if back_from_own_goal:
            match.move_player_relative(
                handler, TeamSide.HOME, back_from_own_goal,
            )
        match.set_ball_space(*match.board.meeple_position(handler))
    match.ball.speed = ball_speed

    challenger = fielded(match, role, TeamSide.VISITING)
    match.board.remove_meeple(challenger)
    match.board.place_meeple(
        challenger, match.ball.zone, match.ball.space_index,
    )
    match.challenger_id = challenger

    match.choose_offense_maneuver(offense_key)
    match.choose_defense_maneuver(defense_key)
    return match, handler, challenger


def empty_the_landing_space(match: MatchState, distance: int) -> None:
    """
    Move the defending side off the space a deflection of `distance`
    ends on, the challenger aside.

    A standard deal decides where everybody starts, and an overshoot
    fixture is about whether *the branch* offers a shot rather than
    about who the deal happened to leave near the offense's own goal.
    So the space is emptied deliberately and then filled deliberately,
    which is what lets both overshoot fixtures spell their candidates
    out.
    """
    zone, space_index = deflected_to(match, distance)
    visiting = match.setup_for_side(TeamSide.VISITING).field_players
    parked = match.own_goal_restart_space(TeamSide.VISITING)
    for player_id in list(match.board.spaces[zone][space_index]):
        if player_id in visiting and player_id != match.challenger_id:
            match.move_meeple(player_id, *parked)


def stand_a_defender_where_the_ball_lands(
    match: MatchState,
    distance: int,
    role: PlayerRole,
) -> str:
    """
    Put one more of the defending side on the space a deflection of
    `distance` ends on, and hand back who it is -- the shooter a
    scoring opportunity is offered to.

    Placed rather than walked, the same as the challenger and for the
    same reason.
    """
    empty_the_landing_space(match, distance)
    zone, space_index = deflected_to(match, distance)
    player_id = fielded(match, role, TeamSide.VISITING)
    match.board.remove_meeple(player_id)
    match.board.place_meeple(player_id, zone, space_index)
    return player_id


# -- Deflect -----------------------------------------------------------


def deflect_plain() -> DeflectFixture:
    """
    The basic card: the ball is knocked one space back toward the
    offense's own goal, loses a step of speed, and is loose where it
    stops. The baseline the rest are variations on.
    """
    match, handler, challenger = stand_a_deflection(
        "low_pass", "deflect", ball_speed=3,
    )
    destination = deflected_to(match, 1)
    return DeflectFixture(
        game=build_game(),
        match=match,
        key="deflect",
        handler_id=handler,
        challenger_id=challenger,
        narration=deflect_text(match, "deflect", 1, 2),
        ball_space=destination,
        ball_speed=2,
    )


def deflect_by_a_fullback() -> DeflectFixture:
    """
    **Role ability -- Fullback**: +1 space, so a Deflect they play
    drives the ball two. The speed drop is the card's and stays at 1 --
    the two numbers are separate for exactly this reason, and the
    sentence names the ability where it is in force.
    """
    match, handler, challenger = stand_a_deflection(
        "low_pass", "deflect", role=PlayerRole.FULLBACK, ball_speed=3,
    )
    destination = deflected_to(match, 2)
    return DeflectFixture(
        game=build_game(),
        match=match,
        key="deflect",
        handler_id=handler,
        challenger_id=challenger,
        narration=deflect_text(match, "deflect", 2, 2, fullback=True),
        ball_space=destination,
        ball_speed=2,
    )


def deflect_that_overshoots() -> DeflectFixture:
    """
    **The ball is already on the space closest to the offense's own
    goal**, so there is nowhere to knock it back to -- and the
    defender standing on it is next to a goal with the ball at their
    feet. That is a turnover before the shot, so possession changes
    and the speed resets to 1.

    The sentence is worded **before** the reset: it reads the speed the
    deflection itself left, which here is one step down from 3 rather
    than the 1 the match ends on. A deflection of zero spaces still
    says so -- saying what the position is, rather than what it is not.
    """
    match, handler, challenger = stand_a_deflection(
        "low_pass", "deflect", back_from_own_goal=0, ball_speed=3,
    )
    empty_the_landing_space(match, 0)
    where = (match.ball.zone, match.ball.space_index)
    return DeflectFixture(
        game=build_game(),
        match=match,
        key="deflect",
        handler_id=handler,
        challenger_id=challenger,
        narration=(
            deflect_text(match, "deflect", 0, 2) + " " + OVERSHOOT_NOTE
        ),
        refreshes=1,
        follow_on=SHOOTER_CHOICE,
        follow_on_kwargs={"candidates": [challenger]},
        possession=TeamSide.VISITING,
        ball_space=where,
        ball_speed=1,
    )


def deflect_beats_a_setup_pass() -> DeflectFixture:
    """
    **Setup Pass's cost**, charged inside the deflection that beat it:
    the defending coach drives the ball a further 1, 2 or 3 spaces and
    it is loose where it stops. The deflection does not settle the ball
    itself, so this branch hands over to the choice rather than to the
    loose ball -- and says nothing extra while doing it, because the
    prompt is where the cost is explained.
    """
    match, handler, challenger = stand_a_deflection(
        "setup_pass", "deflect", ball_speed=2,
    )
    destination = deflected_to(match, 1)
    return DeflectFixture(
        game=advanced_game(),
        match=match,
        key="deflect",
        handler_id=handler,
        challenger_id=challenger,
        narration=deflect_text(match, "deflect", 1, 1),
        follow_on=PUSH_BACK,
        follow_on_kwargs={},
        ball_space=destination,
        ball_speed=1,
    )


# -- Clear -------------------------------------------------------------


def clear_plain() -> DeflectFixture:
    """
    Clear is Deflect at three spaces: the ball goes back 3 and the
    speed drops by 3 rather than 1. Everything else about it is the
    same card, which is why the two share one step.
    """
    match, handler, challenger = stand_a_deflection(
        "low_pass", "clear", ball_speed=4,
    )
    destination = deflected_to(match, 3)
    return DeflectFixture(
        game=build_game(),
        match=match,
        key="clear",
        handler_id=handler,
        challenger_id=challenger,
        narration=deflect_text(match, "clear", 3, 1),
        ball_space=destination,
        ball_speed=1,
    )


def clear_by_a_fullback() -> DeflectFixture:
    """
    **A Fullback's Clear goes back four** (the author, 2026-08-19), and
    **the speed still drops by three**. The two numbers coming apart is
    the whole of what this fixture pins: read the drop off the distance
    and this reads correctly right up until a Fullback plays a Clear.
    """
    match, handler, challenger = stand_a_deflection(
        "low_pass", "clear", role=PlayerRole.FULLBACK, ball_speed=6,
    )
    destination = deflected_to(match, 4)
    return DeflectFixture(
        game=build_game(),
        match=match,
        key="clear",
        handler_id=handler,
        challenger_id=challenger,
        narration=deflect_text(match, "clear", 4, 3, fullback=True),
        ball_space=destination,
        ball_speed=3,
    )


def clear_that_overshoots_onto_nobody() -> DeflectFixture:
    """
    A Clear overshoots from anywhere inside three spaces of the end,
    and **the ball still travels** -- the sentence reads the clamped
    distance, not the card's. With nobody of the defending side
    standing where it stops there is no scoring opportunity to offer,
    so the overshoot changes nothing at all: it is a loose ball like
    any other deflection.

    The branch exists because `scoring_opportunity_candidates` is asked
    after the overshoot rather than instead of it, and an empty answer
    falls through. Worth its own fixture: the only thing distinguishing
    it from `clear_plain` is a sentence that is *not* there.
    """
    match, handler, challenger = stand_a_deflection(
        "low_pass", "clear", back_from_own_goal=1, ball_speed=4,
    )
    empty_the_landing_space(match, 3)
    distance = deflected_distance(match, 3)
    destination = deflected_to(match, 3)
    return DeflectFixture(
        game=build_game(),
        match=match,
        key="clear",
        handler_id=handler,
        challenger_id=challenger,
        narration=deflect_text(match, "clear", distance, 1),
        ball_space=destination,
        ball_speed=1,
    )


def clear_that_overshoots_onto_a_defender() -> DeflectFixture:
    """
    The same overshoot with one of the defending side standing where
    the ball comes to rest. **The shot needs no range check**: an
    overshoot means the ball reached the space closest to the
    offense's own goal, which is as deep into the defending team's
    range as the field goes.

    The challenger is not the shooter here -- they are back on the
    space the deflection was played from -- which is what makes this
    the fixture that proves the candidates are read off the ball's new
    space rather than off who played the card.
    """
    match, handler, challenger = stand_a_deflection(
        "low_pass", "clear", back_from_own_goal=1, ball_speed=4,
    )
    shooter = stand_a_defender_where_the_ball_lands(
        match, 3, PlayerRole.STRIKER,
    )
    distance = deflected_distance(match, 3)
    destination = deflected_to(match, 3)
    return DeflectFixture(
        game=build_game(),
        match=match,
        key="clear",
        handler_id=handler,
        challenger_id=challenger,
        narration=(
            deflect_text(match, "clear", distance, 1) + " " + OVERSHOOT_NOTE
        ),
        refreshes=1,
        follow_on=SHOOTER_CHOICE,
        follow_on_kwargs={"candidates": [shooter]},
        possession=TeamSide.VISITING,
        ball_space=destination,
        ball_speed=1,
    )


def clear_beats_a_setup_pass() -> DeflectFixture:
    """
    The same cost on the other card of the rank. Worth its own fixture
    rather than trusting the Deflect's: the push-back is offered from
    wherever the deflection left the ball, and a Clear has already
    driven it three spaces further back than a Deflect would have.
    """
    match, handler, challenger = stand_a_deflection(
        "setup_pass", "clear", ball_speed=4,
    )
    destination = deflected_to(match, 3)
    return DeflectFixture(
        game=advanced_game(),
        match=match,
        key="clear",
        handler_id=handler,
        challenger_id=challenger,
        narration=deflect_text(match, "clear", 3, 1),
        follow_on=PUSH_BACK,
        follow_on_kwargs={},
        ball_space=destination,
        ball_speed=1,
    )


DEFLECT_CASES: tuple[DeflectCase, ...] = (
    DeflectCase("deflect_plain", deflect_plain),
    DeflectCase("deflect_by_a_fullback", deflect_by_a_fullback),
    DeflectCase("deflect_that_overshoots", deflect_that_overshoots),
    DeflectCase("deflect_beats_a_setup_pass", deflect_beats_a_setup_pass),
    DeflectCase("clear_plain", clear_plain),
    DeflectCase("clear_by_a_fullback", clear_by_a_fullback),
    DeflectCase(
        "clear_that_overshoots_onto_nobody",
        clear_that_overshoots_onto_nobody,
    ),
    DeflectCase(
        "clear_that_overshoots_onto_a_defender",
        clear_that_overshoots_onto_a_defender,
    ),
    DeflectCase("clear_beats_a_setup_pass", clear_beats_a_setup_pass),
)
