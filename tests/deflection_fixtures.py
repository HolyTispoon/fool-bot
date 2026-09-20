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

- `tests/test_d12ball_deflection_flow.py` asks the model
  (`d12ball.flow.effects.deflection_step`) for the `StepResult`.
- `tests/test_d12ball_deflection_recording.py` asks the cog
  (`D12Ball.apply_deflection`) what it handed the step that comes
  next.

The second one is the equivalence test, and it is the shape
`tests/low_pass_fixtures.py` gave Phase 2, `tests/dribble_fixtures.py`
rank O2, `tests/steal_fixtures.py` rank D2 and
`tests/pressure_fixtures.py` rank D3: it was written and run green
against the **old** cog before anything moved, so a green run
afterwards is the two answering the same way rather than two halves of
one new thing agreeing with each other. Its commit is the first on the
branch for exactly that reason.

**Rank D1 has no unchallenged branch**, the same as ranks D2 and D3: a
defense card only resolves where a defender was sent, so every fixture
here has a challenger, and `match.challenger_id` is who the deflection
is played *by*. It is also the only player either card reads -- the
distance and the speed drop are the card's, and the Fullback's +1 is
the challenger's role.

**The board and the refresh are two answers here, and this is the one
rank where they differ.** Every branch drives the ball back, so the
board moved on every one of them; but the old cog called
`refresh_match_image` on the overshoot-into-a-shot branch **only**,
because `begin_loose_ball` draws the board under its own announcement
and a refresh in front of it would write the same board twice (see
"Discord's rate limits" in docs/design/rate-limits.md). So the table
records `board_changed` -- what is true of the position, which is the
model's answer -- and `refreshes` -- what the frontend actually did
with it -- as two fields, and each test module reads the one that is
its own.

**The expected narration is built, never spelled out, wherever it
names a player or a side** -- the roster is data the author revises
(see `roster.py`). The distances and the speeds are spelled out,
because a distance the fixture chose is a fact about the fixture
rather than about the roster.

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

CATALOG = load_player_catalog()
RULESET = load_basic_ruleset()
MANEUVERS = load_maneuver_catalog()
ENGINE = RulesEngine(
    CATALOG, RULESET, MANEUVERS, build_ai_strategies(CATALOG, MANEUVERS),
)

GAME_ID = "g1"

#: Where a deflection ordinarily ends: the ball is out of anybody's
#: possession where it stopped, and how it is won is read off what is
#: standing on that space. It does **not** go through
#: `finish_maneuver_resolution` -- the question that step asks (does
#: the possessing team have somebody on the ball?) has an answer that
#: does not matter here, since either side's occupant is equally
#: dispossessed. By `FollowOnStep` member name, spelled as a string so
#: this module stays free of the package under test.
LOOSE_BALL = "BEGIN_LOOSE_BALL"

#: The overshoot's ending instead: the ball reached the space closest
#: to the offense's own goal with a defender standing on it, so the
#: deflecting side takes it and shoots.
SHOOTER_CHOICE = "BEGIN_SHOOTER_CHOICE"

#: **Setup Pass's cost**, asked inside the deflection that beat it
#: rather than as a step after it: the defending coach drives the ball
#: a further 1, 2 or 3 spaces back and it is loose where it stops.
SETUP_PASS_PUSH_BACK = "OFFER_SETUP_PASS_PUSH_BACK"

#: The offense card a basic deflection beats. Deflect and Clear beat
#: High Pass and Setup Pass and tie with both passes on rank O1, so a
#: fixture that wants "no advanced cost in this" plays the basic one
#: of the two the card actually beats.
BEATEN_BASIC = "high_pass"

#: And the advanced one, which is the only cost either card can ever
#: collect.
BEATEN_ADVANCED = "setup_pass"


@dataclass
class DeflectionFixture:
    """One match mid-deflection, and everything resolving it should say."""

    game: D12BallGame
    match: MatchState
    #: Which card: `deflect` or `clear`.
    key: str
    #: The defender playing it -- `match.challenger_id`, held here so
    #: the assertions can name them after the match has moved.
    challenger_id: str
    #: The handler it is played against -- `match.active_player_id`.
    handler_id: str

    #: The narration, as one string: what the old cog built inline and
    #: handed the next step as its `lead_in`. Every branch of this rank
    #: carries it that way; none of them posts a message of its own.
    narration: str = ""
    #: Whether the board moved -- true on every branch, since every
    #: branch drives the ball back or takes speed off it.
    board_changed: bool = True
    #: Whether the old cog wrote the persistent board message before
    #: handing over. Only the shot branch did; see the module
    #: docstring.
    refreshes: bool = False
    #: Which step runs next, by `FollowOnStep` member name.
    follow_on: str = LOOSE_BALL
    #: The arguments that step is called with, `lead_in` aside.
    follow_on_kwargs: dict[str, Any] = field(
        default_factory=lambda: {"distance_moved": 1},
    )

    #: What the match looks like afterwards.
    possession: TeamSide = TeamSide.HOME
    ball_space: Optional[tuple[Zone, int]] = None
    ball_speed: int = 1


@dataclass(frozen=True)
class DeflectionCase:
    """A fixture and the name it is reported under."""

    name: str
    build: Callable[[], DeflectionFixture]


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


def build_match(board_size: int = 7) -> MatchState:
    return MatchState.standard(
        catalog=CATALOG,
        ruleset=RULESET,
        board_size=board_size,
        home_team=Team.ORANGE,
        visiting_team=Team.PURPLE,
        home_formation=Formation.TWO_TWO_TWO,
    )


def stand_a_deflection(
    offense_key: str,
    defense_key: str,
    role: PlayerRole = PlayerRole.MIDFIELDER,
    speed: int = 5,
    back_from_own_goal: Optional[int] = None,
) -> tuple[MatchState, str, str]:
    """
    A match mid-maneuver with the deflection the winning card: the
    handler, and the defender standing on them who played it.

    The challenger is **placed** on the ball's space rather than walked
    there by `choose_challenger`, for the reason
    `tests/pressure_fixtures.py` gives: a walk charges exhaustion for
    the distance, and a deflection charges none, so a walk would put a
    token in the fixture that the card never asked for. `role` is a
    parameter because the Fullback's +1 space is read off it.

    `back_from_own_goal` parks the handler and the ball that many
    spaces out from the last space toward the offense's own goal,
    before the challenger is placed. That is where the overshoot lives
    and the only place it does -- a Deflect can only overshoot from 0,
    a Clear from 2 or nearer.
    """
    match = build_match()
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
    match.ball.speed = speed

    challenger = next(
        player_id
        for player_id in match.visiting.field_players
        if ENGINE.get_player_definition(player_id).role == role
    )
    match.board.remove_meeple(challenger)
    match.board.place_meeple(
        challenger, match.ball.zone, match.ball.space_index,
    )
    match.challenger_id = challenger

    match.choose_offense_maneuver(offense_key)
    match.choose_defense_maneuver(defense_key)
    return match, handler, challenger


def defenders_waiting_at(match: MatchState, distance: int) -> list[str]:
    """
    The deflecting side's players already standing where this
    deflection will drive the ball -- the rule
    `scoring_opportunity_candidates` reads, restated off the board so
    the fixture does not ask the engine for its own expected answer.

    **In board order**, which is the order the shot's prompt offers
    them in, and not the order anything was placed in.
    """
    zone, space_index = deflected_to(match, distance)
    occupants = match.board.spaces[zone][space_index]
    fielded = set(match.visiting.field_players)
    return [player_id for player_id in occupants if player_id in fielded]


def clear_the_landing_space(match: MatchState, distance: int) -> None:
    """
    Empty the space the deflection will drive the ball to, of the
    deflecting side alone.

    The standard deal already parks the visiting striker on the home
    goal line -- they attack that goal -- so "the ball overshoots onto
    a space with nobody on it" has to be arranged rather than assumed.
    They are moved a space out rather than lifted off the board,
    because a formation short of a player is a different fixture again.
    """
    for player_id in defenders_waiting_at(match, distance):
        match.move_player_relative(player_id, TeamSide.HOME, 1)


def deflected_to(match: MatchState, distance: int):
    """
    Where a deflection of `distance` leaves the ball, relative to the
    side that still has it. Clamped at the end of the field, the same
    way `move_ball_relative` is.
    """
    origin = match.board.flat_index(match.ball.zone, match.ball.space_index)
    return match.board.position_at_flat_index(
        match.relative_flat_index(origin, match.ball.possession, -distance)
    )


def travelled(match: MatchState, distance: int) -> int:
    """How far that deflection actually goes once the board has clamped it."""
    origin = match.board.flat_index(match.ball.zone, match.ball.space_index)
    target = match.board.flat_index(*deflected_to(match, distance))
    return abs(target - origin)


def deflection_text(
    key: str,
    actual_distance: int,
    speed_after: int,
    fullback: bool = False,
) -> str:
    """
    The sentence both cards share. The distance is the one the board
    allowed, not the one the card asked for, which is what makes the
    clamped fixtures worth having.
    """
    space_word = "space" if actual_distance == 1 else "spaces"
    ability_note = " (Fullback ability)" if fullback else ""
    return (
        f"**{ENGINE.maneuver_name(key)}:** the ball moves "
        f"{actual_distance} {space_word} back{ability_note}. Ball speed "
        f"is now {speed_after}."
    )


#: What an overshoot that lands on a defender adds, and the whole of
#: what sends the turn to a shot instead of to a loose ball. It reads
#: as one sentence after the deflection's own, joined by the single
#: space `dispatch_step_result` joins narration blocks with.
OVERSHOOT_NOTE = "That overshoots the field -- a scoring opportunity!"


def speed_after(speed: int, drop: int) -> int:
    """The floor is 1: a deflection takes speed off, it never stops the ball."""
    return max(1, speed - drop)


# -- Deflect -----------------------------------------------------------


def deflect_plain() -> DeflectionFixture:
    """
    The basic card: the ball goes back a space, a point comes off its
    speed, and it is loose where it stops. The baseline the rest are
    variations on -- and note what is *not* here: no turnover sentence
    and no possession change. A deflection knocks the ball out of
    everybody's hands, and who ends up with it is the loose ball's
    question rather than this card's.
    """
    match, handler, challenger = stand_a_deflection(BEATEN_BASIC, "deflect")
    return DeflectionFixture(
        game=build_game(),
        match=match,
        key="deflect",
        challenger_id=challenger,
        handler_id=handler,
        narration=deflection_text("deflect", travelled(match, 1), 4),
        ball_space=deflected_to(match, 1),
        ball_speed=4,
    )


def deflect_by_a_fullback() -> DeflectionFixture:
    """
    **Role ability -- Fullback: +1 space on a deflection**, which takes
    a Deflect from 1 to 2 -- and the speed drop stays at 1, because the
    drop is the card's number and not the distance's. The two happen to
    match on an ordinary Deflect, which is exactly why this fixture and
    `clear_by_a_fullback` are both here.
    """
    match, handler, challenger = stand_a_deflection(
        BEATEN_BASIC, "deflect", role=PlayerRole.FULLBACK,
    )
    return DeflectionFixture(
        game=build_game(),
        match=match,
        key="deflect",
        challenger_id=challenger,
        handler_id=handler,
        narration=deflection_text(
            "deflect", travelled(match, 2), 4, fullback=True,
        ),
        ball_space=deflected_to(match, 2),
        ball_speed=4,
    )


def deflect_that_overshoots_into_a_shot() -> DeflectionFixture:
    """
    **The ball is already on the space closest to the offense's own
    goal**, so there is nowhere to drive it back to -- and the defender
    standing on it is now next to the goal they attack. That is a
    turnover before the shot, so possession changes hands and the speed
    drops to 1 before the shot is offered.

    The distance reads 0: the sentence says what the board allowed, not
    what the card asked for. And the speed it quotes is the *drop's*,
    4, not the 1 the turnover then sets -- pre-existing wording, left
    exactly as it was (see the PR).

    A Deflect can only overshoot from here, which is why this is the
    only fixture that stands on the end space.
    """
    match, handler, challenger = stand_a_deflection(
        BEATEN_BASIC, "deflect", back_from_own_goal=0,
    )
    # The challenger is standing on the ball, and a 0-space deflection
    # leaves the ball standing on them -- so they are a candidate for
    # the shot they just created, beside the striker the standard deal
    # already has camped on that goal line.
    candidates = defenders_waiting_at(match, 1)
    return DeflectionFixture(
        game=build_game(),
        match=match,
        key="deflect",
        challenger_id=challenger,
        handler_id=handler,
        narration=(
            f"{deflection_text('deflect', 0, 4)} {OVERSHOOT_NOTE}"
        ),
        refreshes=True,
        follow_on=SHOOTER_CHOICE,
        follow_on_kwargs={"candidates": candidates},
        possession=TeamSide.VISITING,
        ball_space=deflected_to(match, 1),
        ball_speed=1,
    )


def deflect_beats_a_setup_pass() -> DeflectionFixture:
    """
    **Setup Pass's cost**, and the only cost either card of this rank
    can ever collect: Deflect and Clear beat High Pass and Setup Pass
    and tie with both passes on rank O1, so Setup Pass is the one
    advanced card they ever see lose.

    It is asked inside the deflection rather than as a step after it,
    because a deflection already ends in a loose ball -- the cost only
    decides where the ball lies when it does. So this branch hands over
    to the question rather than to the loose ball, and the loose ball
    happens on the far side of the answer.
    """
    match, handler, challenger = stand_a_deflection(
        BEATEN_ADVANCED, "deflect",
    )
    return DeflectionFixture(
        game=advanced_game(),
        match=match,
        key="deflect",
        challenger_id=challenger,
        handler_id=handler,
        narration=deflection_text("deflect", travelled(match, 1), 4),
        follow_on=SETUP_PASS_PUSH_BACK,
        follow_on_kwargs={},
        ball_space=deflected_to(match, 1),
        ball_speed=4,
    )


def an_overshooting_deflection_skips_the_setup_pass_cost() -> (
    DeflectionFixture
):
    """
    **The shot comes first and the cost is not asked at all.** The ball
    is already as far back as the field goes, so there is nothing for a
    push-back to buy, and the shot is the bigger thing happening.

    Worth its own fixture rather than trusting the two above: the only
    thing distinguishing it from `deflect_beats_a_setup_pass` is a
    question that is *not* asked, and an ordering nothing else pins.
    """
    match, handler, challenger = stand_a_deflection(
        BEATEN_ADVANCED, "deflect", back_from_own_goal=0,
    )
    candidates = defenders_waiting_at(match, 1)
    return DeflectionFixture(
        game=advanced_game(),
        match=match,
        key="deflect",
        challenger_id=challenger,
        handler_id=handler,
        narration=(
            f"{deflection_text('deflect', 0, 4)} {OVERSHOOT_NOTE}"
        ),
        refreshes=True,
        follow_on=SHOOTER_CHOICE,
        follow_on_kwargs={"candidates": candidates},
        possession=TeamSide.VISITING,
        ball_space=deflected_to(match, 1),
        ball_speed=1,
    )


# -- Clear -------------------------------------------------------------


def clear_plain() -> DeflectionFixture:
    """
    The advanced card is Deflect at three spaces, and the speed comes
    off three at a time with it. Everything else about it -- the
    overshoot set-up, the loose ball it leaves behind -- is the same
    card, which is why the two share one step.
    """
    match, handler, challenger = stand_a_deflection(BEATEN_BASIC, "clear")
    return DeflectionFixture(
        game=advanced_game(),
        match=match,
        key="clear",
        challenger_id=challenger,
        handler_id=handler,
        narration=deflection_text("clear", travelled(match, 3), 2),
        ball_space=deflected_to(match, 3),
        ball_speed=2,
    )


def clear_by_a_fullback() -> DeflectionFixture:
    """
    **The Fullback's +1 is the rule behind the number, not the number**
    (the author, 2026-08-19): their card reads "ball goes back 2
    spaces", which against a 3-space clearance would be a *reduction*,
    and what carries is the +1 that takes a basic Deflect from 1 to 2.
    So a Clear they play goes back 4.

    The speed still drops by 3 -- the card's number, unmoved by the
    extra space. This is the fixture that would have caught deriving
    one from the other, which read correctly right up until the
    Fullback was let near a Clear.

    Stood four spaces out from the end so the 4 actually travels;
    from the standard deal a Fullback's Clear overshoots, which is a
    different branch and has its own fixture.
    """
    match, handler, challenger = stand_a_deflection(
        BEATEN_BASIC, "clear", role=PlayerRole.FULLBACK,
        back_from_own_goal=4,
    )
    return DeflectionFixture(
        game=advanced_game(),
        match=match,
        key="clear",
        challenger_id=challenger,
        handler_id=handler,
        narration=deflection_text(
            "clear", travelled(match, 4), 2, fullback=True,
        ),
        ball_space=deflected_to(match, 4),
        ball_speed=2,
    )


def clear_that_overshoots_into_a_shot() -> DeflectionFixture:
    """
    A Clear overshoots from further out than a Deflect can, and **it
    drives the ball a real space first**: the 3 clamps to 1, so the
    sentence reads the distance actually travelled and the ball has
    moved by the time the shot is offered.

    Here the defender who takes the shot is **not** the one who played
    the card: the challenger is still standing where the ball started,
    and the candidate is the striker the standard deal already has
    camped on that goal line. Which is the ordinary way round, and the
    reason `scoring_opportunity_candidates` reads the space rather than
    the challenger.
    """
    match, handler, challenger = stand_a_deflection(
        BEATEN_BASIC, "clear", back_from_own_goal=1,
    )
    candidates = defenders_waiting_at(match, 3)
    return DeflectionFixture(
        game=advanced_game(),
        match=match,
        key="clear",
        challenger_id=challenger,
        handler_id=handler,
        narration=(
            f"{deflection_text('clear', travelled(match, 3), 2)} "
            f"{OVERSHOOT_NOTE}"
        ),
        refreshes=True,
        follow_on=SHOOTER_CHOICE,
        follow_on_kwargs={"candidates": candidates},
        possession=TeamSide.VISITING,
        ball_space=deflected_to(match, 3),
        ball_speed=1,
    )


def clear_that_overshoots_onto_an_empty_space() -> DeflectionFixture:
    """
    **An overshoot with nobody standing there is an ordinary loose
    ball**, and this is the branch that says so: the overshoot decides
    only whether to *look* for a shooter, and the look can come back
    empty. Then nothing was turned over, the ball keeps the speed the
    clearance left it and it is loose where it stopped.

    Without this fixture the two halves of `if overshot` and
    `if candidates` cannot be told apart.
    """
    match, handler, challenger = stand_a_deflection(
        BEATEN_BASIC, "clear", back_from_own_goal=2,
    )
    clear_the_landing_space(match, 3)
    return DeflectionFixture(
        game=advanced_game(),
        match=match,
        key="clear",
        challenger_id=challenger,
        handler_id=handler,
        narration=deflection_text("clear", travelled(match, 3), 2),
        ball_space=deflected_to(match, 3),
        ball_speed=2,
    )


def clear_clamps_the_speed_at_one() -> DeflectionFixture:
    """
    **A deflection takes speed off; it never stops the ball.** A ball
    already crawling at 2 meets a Clear's -3 and comes out at 1 rather
    than at -1, and the sentence quotes the floor.
    """
    match, handler, challenger = stand_a_deflection(
        BEATEN_BASIC, "clear", speed=2,
    )
    return DeflectionFixture(
        game=advanced_game(),
        match=match,
        key="clear",
        challenger_id=challenger,
        handler_id=handler,
        narration=deflection_text(
            "clear", travelled(match, 3), speed_after(2, 3),
        ),
        ball_space=deflected_to(match, 3),
        ball_speed=1,
    )


def clear_beats_a_setup_pass() -> DeflectionFixture:
    """
    The same cost on the other card of the rank. Worth its own fixture
    rather than trusting the Deflect's: this is where the push-back is
    offered on top of a clearance that has already driven the ball
    three spaces, so what the coach is choosing from is a different
    position entirely.
    """
    match, handler, challenger = stand_a_deflection(
        BEATEN_ADVANCED, "clear",
    )
    return DeflectionFixture(
        game=advanced_game(),
        match=match,
        key="clear",
        challenger_id=challenger,
        handler_id=handler,
        narration=deflection_text("clear", travelled(match, 3), 2),
        follow_on=SETUP_PASS_PUSH_BACK,
        follow_on_kwargs={},
        ball_space=deflected_to(match, 3),
        ball_speed=2,
    )


DEFLECTION_CASES: tuple[DeflectionCase, ...] = (
    DeflectionCase("deflect_plain", deflect_plain),
    DeflectionCase("deflect_by_a_fullback", deflect_by_a_fullback),
    DeflectionCase(
        "deflect_that_overshoots_into_a_shot",
        deflect_that_overshoots_into_a_shot,
    ),
    DeflectionCase("deflect_beats_a_setup_pass", deflect_beats_a_setup_pass),
    DeflectionCase(
        "an_overshooting_deflection_skips_the_setup_pass_cost",
        an_overshooting_deflection_skips_the_setup_pass_cost,
    ),
    DeflectionCase("clear_plain", clear_plain),
    DeflectionCase("clear_by_a_fullback", clear_by_a_fullback),
    DeflectionCase(
        "clear_that_overshoots_into_a_shot",
        clear_that_overshoots_into_a_shot,
    ),
    DeflectionCase(
        "clear_that_overshoots_onto_an_empty_space",
        clear_that_overshoots_onto_an_empty_space,
    ),
    DeflectionCase(
        "clear_clamps_the_speed_at_one", clear_clamps_the_speed_at_one,
    ),
    DeflectionCase("clear_beats_a_setup_pass", clear_beats_a_setup_pass),
)
