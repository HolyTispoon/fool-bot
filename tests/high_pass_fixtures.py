"""
A match standing in each branch a High Pass or a Setup Pass resolves
through, and what that resolution should produce.

Rank O3 of Phase 3 of docs/model-discord-split.md moves the two cards'
own resolution out of the cog and into `d12ball/flow/effects.py`. The
thing worth asserting about a move like that is that **not one branch
changed what it said or what it did next**, and that needs one table
standing in every branch rather than the scattered assertions the
suite already had.

So the fixtures live here, built with no `discord` in scope, and two
test modules read the same table:

- `tests/test_d12ball_high_pass_flow.py` asks the model
  (`d12ball.flow.effects.high_pass_step` and its Setup Pass
  neighbours) for the `StepResult`.
- `tests/test_d12ball_high_pass_recording.py` asks the cog what it
  handed the step that comes next.

The second one is the equivalence test, and it is the shape
`tests/low_pass_fixtures.py` gave Phase 2 and
`tests/deflection_fixtures.py` gave rank D1: it was written and run
green against the **old** cog before anything moved, so a green run
afterwards is the two answering the same way rather than two halves of
one new thing agreeing with each other. Its commit is the first on the
branch for exactly that reason.

**This rank has four entry points, not one**, which is the first way it
differs from every rank before it. A High Pass resolves through one
function; a Setup Pass is two prompts -- the speed first, the
destination after -- and its out-of-play ending is reachable from the
menu that never offered a distance as well as from the pass itself. So
each fixture names the `entry` it is driven through and the table reads
as four smaller tables that happen to share a shape.

**Both cards are an offense rank's**, so "contested and unchallenged"
is two real halves here where it was one for D1, D2 and D3: a fixture
that chooses no defense card is a pass nobody was sent against, which
is the ordinary case, and the contested ones name the card they beat.

**`board_changed` is the model's answer** -- what is true of the
position. What the frontend does with it is not in this table any
more: the three branches that hand over to a step which draws its own
board (the two passes that run out of play, whose new play posts and
pins its own, and the Setup Pass that lands on nobody, whose loose
ball is announced under the board) have that write skipped by the
dispatcher reading what the *next* step reports -- which a recorder
standing in for it does not. The recording tests therefore see one
write wherever the board moved and assert exactly that.

**The expected narration is built, never spelled out, wherever it
names a player or a side** -- the roster is data the author revises
(see `roster.py`). The distances and the speeds are spelled out,
because a distance the fixture chose is a fact about the fixture
rather than about the roster.

**The follow-on step is named by its `FollowOnStep` member name**, a
string, so this module needs no import from `d12ball/flow/` -- which
is what lets it be written before `BEGIN_HIGH_PASS_CONTEST` exists.
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
from d12ball.formatting import format_team_side_label
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

#: The tail of an ordinary maneuver: the clock, the end of a period,
#: and the offensive choice handed back. Where a pass that was simply
#: caught ends. By `FollowOnStep` member name, spelled as a string so
#: this module stays free of the package under test.
FINISH = "FINISH_MANEUVER_RESOLUTION"

#: A set-up: the offense is offered the shot instead of letting the
#: pass resolve. Both cards reach it, and an overshoot reaches it with
#: `contest_on_decline` set -- declining an overshoot is the contest,
#: not a settled pass.
SCORING_ATTEMPT = "OFFER_SCORING_ATTEMPT_CHOICE"

#: Setup Pass's first half: the ball's speed, set before the pass is
#: picked out. The card is the only one that asks it *first*, which is
#: why the rest of the pass is recorded as an effect continuation
#: once the speed has been chosen (`speed_choice_step`).
SPEED_CHOICE = "OFFER_SPEED_CHOICE"

#: Where a pass with nowhere to go ends: the ball went dead, so it is
#: a new play and the side that gains it sends somebody to fetch the
#: ball.
RUN_BACK = "BEGIN_RUN_BACK"

#: A Setup Pass that lands where nobody of the passing side is
#: standing: the ball settles there like a deflection's, and what is
#: on the space decides how it is won.
LOOSE_BALL = "BEGIN_LOOSE_BALL"

#: The long pass's contest -- the receiver standing where it landed
#: still has to win a skill test to keep it. It borrows the loose
#: ball's machinery and is not a loose ball: the ball is on a player
#: both coaches watched catch it, so it is announced plainly and the
#: board it is standing on was posted by the pass itself.
HIGH_PASS_CONTEST = "BEGIN_HIGH_PASS_CONTEST"

#: A basic defense card both passes beat, so a contested fixture can
#: have a challenger standing on the passer with no gambit's cost in
#: the resolution.
BEATEN_BASIC = "steal"

#: The gambit on that rank, and the only cost a High Pass can ever
#: collect: an Intercept it beat leaves the reception uncontested.
BEATEN_ADVANCED = "intercept"

#: High Pass's own clock cost -- a flat 2 space minutes whatever the
#: pass did (2026-08-16), which is why it is apart from the distance
#: the ball actually travelled. Setup Pass's is the same 2, as
#: `SETUP_PASS_CLOCK_COST` in `d12ball/components.py`.
CLOCK_COST = 2


@dataclass
class PassFixture:
    """One match mid-pass, and everything resolving it should say."""

    game: D12BallGame
    match: MatchState
    #: Which of the rank's four entry points drives this fixture:
    #: `high_pass`, `setup_pass`, `setup_pass_out` or
    #: `setup_pass_speed`.
    entry: str
    #: The passer -- `match.active_player_id`, held here so the
    #: assertions can name them after the match has moved.
    passer_id: str
    #: How far the pass was thrown, for the two entries that take one.
    distance: Optional[int] = None

    #: The narration, as one string: what the old cog built inline and
    #: handed the next step as its `lead_in`. No branch of this rank
    #: posts a message of its own.
    narration: str = ""
    #: Whether the board moved -- the model's answer, which is about
    #: the position rather than about what Discord was asked to do.
    board_changed: bool = True
    #: Which step runs next, by `FollowOnStep` member name.
    follow_on: str = FINISH
    #: The arguments that step is called with, `lead_in` aside.
    follow_on_kwargs: dict[str, Any] = field(
        default_factory=lambda: {"distance_moved": CLOCK_COST},
    )

    #: What the match looks like afterwards.
    possession: TeamSide = TeamSide.HOME
    ball_space: Optional[tuple[Zone, int]] = None
    ball_speed: int = 1
    carrier_id: Optional[str] = None
    #: The two flags a branch of this rank sets and a restart has to
    #: come back to.
    overshoot_flag: bool = False
    ball_recovery: bool = False
    #: Setup Pass's own continuation: set when the speed is chosen,
    #: spent by the destination half. None until then, which is what
    #: lets a match waiting on the speed read as waiting on the speed
    #: (see `speed_choice_step`).
    continuation: Optional[dict] = None


@dataclass(frozen=True)
class PassCase:
    """A fixture and the name it is reported under."""

    name: str
    build: Callable[[], PassFixture]


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
    `tests/deflection_fixtures.py` puts on its advanced fixtures.
    Setup Pass is a gambit, so every fixture for it is built from
    this one.
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


def label(match: MatchState, player_id: str) -> str:
    """The player as every message in the game names them."""
    return ENGINE.format_player_label(
        match, ENGINE.get_player_definition(player_id),
    )


def at(match: MatchState, flat: int) -> tuple[Zone, int]:
    """A flat board index as the zone and space the board calls it."""
    return match.board.position_at_flat_index(flat)


def flat_of(match: MatchState, player_id: str) -> int:
    """Where a meeple is standing, as a flat index."""
    return match.board.flat_index(*match.board.meeple_position(player_id))


def ball_flat(match: MatchState) -> int:
    """Where the ball is, as a flat index."""
    return match.board.flat_index(match.ball.zone, match.ball.space_index)


def lands_on(match: MatchState, distance: int) -> tuple[Zone, int]:
    """
    Where a pass of `distance` leaves the ball, clamped at the end of
    the field the way `move_ball_relative` clamps it.

    **The fixture works in flat indices throughout**, because the
    rank's whole geometry is "how much field is left ahead of the
    ball": board 7 is flats 0 to 6, the home side attacks toward 6,
    and its shooting range is 4, 5 and 6 with the kickoff space at 3
    in nobody's.
    """
    return at(
        match,
        match.relative_flat_index(
            ball_flat(match), match.ball.possession, distance,
        ),
    )


def travelled(match: MatchState, distance: int) -> int:
    """How far that pass actually goes once the board has clamped it."""
    origin = ball_flat(match)
    return abs(match.board.flat_index(*lands_on(match, distance)) - origin)


def offense_on(match: MatchState, flat: int) -> list[str]:
    """
    The passing side's players standing on a space, in board order --
    the pool `high_pass_receiver_candidates` reads, restated off the
    board so a fixture does not ask the engine for its own expected
    answer. The passer is **not** struck out here; the fixtures that
    care do it themselves, since "who else is standing there" is the
    question they are built around.
    """
    zone, space_index = at(match, flat)
    fielded_players = set(match.setup_for_side(match.ball.possession).field_players)
    return [
        player_id
        for player_id in match.board.spaces[zone][space_index]
        if player_id in fielded_players
    ]


def clear_offense_from(match: MatchState, flat: int) -> None:
    """
    Empty a space of the passing side, the passer aside.

    The standard deal parks a home player on the last space of the
    field -- they attack that goal -- so "the pass lands where nobody
    of ours is standing" has to be arranged rather than assumed. They
    are walked a space back rather than lifted off the board, because
    a formation short of a player is a different fixture again.
    """
    for player_id in offense_on(match, flat):
        if player_id == match.active_player_id:
            continue
        match.move_meeple(player_id, *at(match, max(0, flat - 1)))


def put_a_teammate_on(
    match: MatchState, flat: int, role: PlayerRole = PlayerRole.WINGER,
) -> str:
    """Walk one of the passing side's players onto a space, and name them."""
    player_id = fielded(match, role)
    match.move_meeple(player_id, *at(match, flat))
    return player_id


def stand_a_pass(
    offense_key: str,
    *,
    passer_flat: int,
    defense_key: Optional[str] = None,
    role: Optional[PlayerRole] = None,
    speed: int = 1,
) -> tuple[MatchState, str]:
    """
    A match with the ball on a chosen space, the passer standing on it
    with the card already won, and the field otherwise as the standard
    deal left it.

    `passer_flat` is the whole geometry of this rank: how much field
    is left ahead of the ball decides whether a pass overshoots, and
    whether the space it lands on is inside the passing side's
    shooting range decides whether a 2 sets up a shot or is simply
    caught.

    `role` picks the passer, because the Fullback's fourth space is
    read off theirs. They are walked onto the ball before being
    selected -- `select_ball_handler` only takes an eligible handler,
    which is the rule it exists to enforce -- and the pair is then
    moved together to `passer_flat`.

    A `defense_key` is a pass somebody was sent against: the defender
    is **placed** on the passer rather than walked there by
    `choose_challenger`, for the reason `tests/deflection_fixtures.py`
    gives -- a walk charges exhaustion for the distance, and neither
    pass charges any, so a walk would put a token in the fixture that
    the card never asked for.
    """
    match = build_match()
    if role is None:
        passer = match.eligible_ball_handlers()[0]
    else:
        passer = fielded(match, role)
        match.move_meeple(passer, match.ball.zone, match.ball.space_index)
    match.select_ball_handler(passer)

    match.move_meeple(passer, *at(match, passer_flat))
    match.set_ball_space(*at(match, passer_flat))
    match.ball.speed = speed

    if defense_key is not None:
        challenger = next(
            player_id
            for player_id in match.visiting.field_players
            if ENGINE.get_player_definition(player_id).role
            == PlayerRole.MIDFIELDER
        )
        match.board.remove_meeple(challenger)
        match.board.place_meeple(
            challenger, match.ball.zone, match.ball.space_index,
        )
        match.challenger_id = challenger
        match.choose_defense_maneuver(defense_key)
    else:
        # Nobody was sent, which is the ordinary pass: the two cards
        # of this rank are the offense's, so an unchallenged branch is
        # a real half of the bot stop rather than the absent one it
        # was for the three defense ranks.
        match.maneuver_uncontested = True

    match.choose_offense_maneuver(offense_key)
    return match, passer


def gaining_side_label(match: MatchState) -> str:
    """
    The side a ball that went out of play is handed to, worded the way
    both out-of-play branches word it. Read **before** the resolution
    runs, since the resolution is what flips possession.
    """
    return format_team_side_label(
        match.setup_for_side(match.defending_side()),
    )


def high_pass_text(actual_distance: int, fullback: bool = False) -> str:
    """
    The line every branch of a High Pass opens with. The distance is
    the one the board allowed rather than the one the coach asked for,
    which is what makes the clamped fixtures worth having -- and a
    throw that moved the ball no distance at all says so in words
    rather than as "moves 0 spaces forward", which reads as a bug.
    """
    if not actual_distance:
        return (
            "**High Pass:** the ball is thrown up from the last space "
            "and comes straight back down on it."
        )
    space_word = "space" if actual_distance == 1 else "spaces"
    ability_note = " (Fullback ability)" if fullback else ""
    return (
        f"**High Pass:** the ball moves {actual_distance} "
        f"{space_word} forward{ability_note}."
    )


def out_of_play_text(match: MatchState, lead_in: str) -> str:
    """
    A High Pass with nowhere left to put it. The passer is on the
    space closest to the goal they attack and nobody shares it, so
    there is no field to overshoot onto and no teammate to land
    beside: it goes out rather than staying quietly with the passer.
    """
    return (
        f"{lead_in} There is nowhere left to throw it and nobody "
        "to receive it there -- the ball goes out of play. "
        f"{gaining_side_label(match)} gain possession."
    )


def setup_pass_out_text(match: MatchState) -> str:
    """Setup Pass's own version of the same dead end."""
    return (
        "**Setup Pass:** there is nobody to pick the ball out to, "
        "so it runs out of play. "
        f"{gaining_side_label(match)} gain possession."
    )


# -- High Pass: the set-ups --------------------------------------------


def two_spaces_into_a_set_up() -> PassFixture:
    """
    **A pass of 2 is received cleanly and may set up a shot**
    (2026-08-07): no contest at all, and the teammate it reaches takes
    a scoring opportunity because the ball landed inside the passing
    side's range. The baseline the other set-ups are variations on.
    """
    match, passer = stand_a_pass("high_pass", passer_flat=4)
    receiver = put_a_teammate_on(match, 6, PlayerRole.STRIKER)
    return PassFixture(
        game=build_game(),
        match=match,
        entry="high_pass",
        passer_id=passer,
        distance=2,
        narration=(
            f"{high_pass_text(2)} That reaches a teammate -- a scoring "
            "opportunity!"
        ),
        follow_on=SCORING_ATTEMPT,
        follow_on_kwargs={
            "shooter_id": receiver, "distance_moved": CLOCK_COST,
        },
        ball_space=lands_on(match, 2),
        carrier_id=receiver,
    )


def two_spaces_into_a_set_up_contested() -> PassFixture:
    """
    The same pass with a defender sent against it and beaten on a
    basic card, so no gambit's cost reaches the resolution. It
    is here because this is an **offense** rank: contested and
    unchallenged are two real halves of it, where a defense card only
    ever resolves contested.
    """
    match, passer = stand_a_pass(
        "high_pass", passer_flat=4, defense_key=BEATEN_BASIC,
    )
    receiver = put_a_teammate_on(match, 6, PlayerRole.STRIKER)
    return PassFixture(
        game=build_game(),
        match=match,
        entry="high_pass",
        passer_id=passer,
        distance=2,
        narration=(
            f"{high_pass_text(2)} That reaches a teammate -- a scoring "
            "opportunity!"
        ),
        follow_on=SCORING_ATTEMPT,
        follow_on_kwargs={
            "shooter_id": receiver, "distance_moved": CLOCK_COST,
        },
        ball_space=lands_on(match, 2),
        carrier_id=receiver,
    )


def two_spaces_short_of_shooting_range() -> PassFixture:
    """
    **The range rule takes away the shot, not the catch.** A pass of 2
    that finds its receiver outside the passing side's shooting range
    is simply a completed pass -- it may not fall through to the
    long-pass contest, which a pass of 2 has never had to win.
    """
    match, passer = stand_a_pass("high_pass", passer_flat=0)
    receiver = put_a_teammate_on(match, 2, PlayerRole.MIDFIELDER)
    return PassFixture(
        game=build_game(),
        match=match,
        entry="high_pass",
        passer_id=passer,
        distance=2,
        narration=high_pass_text(2),
        follow_on=FINISH,
        ball_space=lands_on(match, 2),
        carrier_id=receiver,
    )


# -- High Pass: the overshoot ------------------------------------------


def an_overshoot_into_a_set_up() -> PassFixture:
    """
    **An overshoot is the set-up the range rule cannot bite.** The
    ball is clamped onto the space closest to the goal the passing
    side attacks, which is as deep into their range as the field goes,
    and the teammate standing there is offered the shot -- at a
    disadvantage, because the pass arrived faster than they could
    settle it.
    """
    match, passer = stand_a_pass("high_pass", passer_flat=5, speed=4)
    receiver = put_a_teammate_on(match, 6, PlayerRole.STRIKER)
    return PassFixture(
        game=build_game(),
        match=match,
        entry="high_pass",
        passer_id=passer,
        distance=2,
        narration=(
            f"{high_pass_text(1)} That overshoots the field -- a scoring "
            "opportunity! The ball comes in too fast to settle -- the "
            "ball speed modifier counts **against** what follows (-2)."
        ),
        follow_on=SCORING_ATTEMPT,
        follow_on_kwargs={
            "shooter_id": receiver,
            "distance_moved": CLOCK_COST,
            "contest_on_decline": True,
        },
        ball_space=lands_on(match, 2),
        ball_speed=4,
        carrier_id=receiver,
        overshoot_flag=True,
    )


def an_overshoot_with_no_modifier_to_pay() -> PassFixture:
    """
    The same branch with the ball walking: the modifier is the speed
    halved and rounded down, so a speed of 1 pays nothing and **a move
    that costs nothing says nothing** -- the note is absent rather
    than reading "(0)". The flag is set all the same, because the
    contest behind a declined set-up reads it too.
    """
    match, passer = stand_a_pass("high_pass", passer_flat=5, speed=1)
    receiver = put_a_teammate_on(match, 6, PlayerRole.STRIKER)
    return PassFixture(
        game=build_game(),
        match=match,
        entry="high_pass",
        passer_id=passer,
        distance=2,
        narration=(
            f"{high_pass_text(1)} That overshoots the field -- a scoring "
            "opportunity!"
        ),
        follow_on=SCORING_ATTEMPT,
        follow_on_kwargs={
            "shooter_id": receiver,
            "distance_moved": CLOCK_COST,
            "contest_on_decline": True,
        },
        ball_space=lands_on(match, 2),
        carrier_id=receiver,
        overshoot_flag=True,
    )


def an_overshoot_onto_nobody() -> PassFixture:
    """
    Nobody of the passing side where it came down, so there is nothing
    to set up: the overshoot falls through to the ordinary paths, and
    the ball has genuinely moved, so it is the maneuver's ordinary
    tail rather than the dead end below.
    """
    match, passer = stand_a_pass("high_pass", passer_flat=5)
    clear_offense_from(match, 6)
    return PassFixture(
        game=build_game(),
        match=match,
        entry="high_pass",
        passer_id=passer,
        distance=2,
        narration=high_pass_text(1),
        follow_on=FINISH,
        ball_space=lands_on(match, 2),
    )


def nowhere_left_to_throw_it() -> PassFixture:
    """
    **A passer never receives their own pass, and since 2026-08-24
    that is no longer a free ride.** The exclusion can only bite on a
    throw the field clamped to nothing -- a High Pass moves the ball
    and not the handler -- and with nobody else on the space there is
    no field left to put it on and no teammate to put it to. So it
    goes out exactly as a Setup Pass with no legal destination does,
    rather than staying quietly with the passer.

    The test is `actual_distance == 0` and not the candidate list
    alone: a pass landing on a genuinely empty space elsewhere is the
    fixture above, and still ends in the maneuver's ordinary tail.
    """
    match, passer = stand_a_pass("high_pass", passer_flat=6, speed=5)
    clear_offense_from(match, 6)
    return PassFixture(
        game=build_game(),
        match=match,
        entry="high_pass",
        passer_id=passer,
        distance=2,
        narration=out_of_play_text(match, high_pass_text(0)),
        follow_on=RUN_BACK,
        follow_on_kwargs={
            "new_play": True, "distance_moved": CLOCK_COST,
        },
        possession=TeamSide.VISITING,
        ball_space=lands_on(match, 0),
        ball_recovery=True,
    )


# -- High Pass: the long pass ------------------------------------------


def a_long_pass_into_a_contest() -> PassFixture:
    """
    **A long High Pass still forces a skill test to keep the ball**,
    unlike any other maneuver: the teammate standing where it landed
    has to win it. A pass of 2 with a teammate there took a set-up
    branch above -- both ask
    `high_pass_receiver_candidates` the same question -- so this is
    the 3-and-4 path alone.
    """
    match, passer = stand_a_pass("high_pass", passer_flat=3, speed=3)
    put_a_teammate_on(match, 6, PlayerRole.STRIKER)
    return PassFixture(
        game=build_game(),
        match=match,
        entry="high_pass",
        passer_id=passer,
        distance=3,
        narration=high_pass_text(3),
        follow_on=HIGH_PASS_CONTEST,
        ball_space=lands_on(match, 3),
        ball_speed=3,
    )


def a_long_pass_onto_nobody() -> PassFixture:
    """
    The same throw with nobody standing where it came down. There is
    no receiver to force a contest for, so it is not the High Pass
    contest at all -- just a pass into empty field, which the
    maneuver's ordinary tail settles.
    """
    match, passer = stand_a_pass("high_pass", passer_flat=3)
    clear_offense_from(match, 6)
    return PassFixture(
        game=build_game(),
        match=match,
        entry="high_pass",
        passer_id=passer,
        distance=3,
        narration=high_pass_text(3),
        follow_on=FINISH,
        ball_space=lands_on(match, 3),
    )


def a_fullback_throws_four() -> PassFixture:
    """
    **Role ability -- Fullback: up to 4 spaces instead of the usual
    2-3.** The note rides inside the card's own sentence, and the
    fourth space is the only thing about the pass that differs.
    """
    match, passer = stand_a_pass(
        "high_pass", passer_flat=2, role=PlayerRole.FULLBACK,
    )
    put_a_teammate_on(match, 6, PlayerRole.STRIKER)
    return PassFixture(
        game=build_game(),
        match=match,
        entry="high_pass",
        passer_id=passer,
        distance=4,
        narration=high_pass_text(4, fullback=True),
        follow_on=HIGH_PASS_CONTEST,
        ball_space=lands_on(match, 4),
    )


def a_beaten_intercept_leaves_the_reception_alone() -> PassFixture:
    """
    **Intercept's cost**: beaten by a High Pass, the reception is not
    contested and the receiver simply keeps it. It is the one of the
    six costs that can be inert, and this is the only branch it is
    not -- a pass of 2, an overshoot's set-up and a pass reaching
    nobody have all returned before it, and none of them had a contest
    to skip.

    The sentence is a paragraph of its own inside the same block: the
    blocks are joined on a single space, so a second block would carry
    a stray space in front of its newlines.
    """
    match, passer = stand_a_pass(
        "high_pass",
        passer_flat=3,
        defense_key=BEATEN_ADVANCED,
        speed=3,
    )
    receiver = put_a_teammate_on(match, 6, PlayerRole.STRIKER)
    return PassFixture(
        game=advanced_game(),
        match=match,
        entry="high_pass",
        passer_id=passer,
        distance=3,
        narration=(
            f"{high_pass_text(3)}\n\n**Intercept** was beaten -- the "
            "reception is not contested, and "
            f"{label(match, receiver)} keeps the ball."
        ),
        follow_on=FINISH,
        ball_space=lands_on(match, 3),
        ball_speed=3,
        carrier_id=receiver,
    )


# -- Setup Pass --------------------------------------------------------


def the_speed_before_the_pass() -> PassFixture:
    """
    **Setup Pass is two prompts because the card's order is speed
    first.** A speed choice has always been the *last* human step of
    an effect; here it is the first, so the rest of the pass is
    recorded as an effect continuation **when the speed is chosen**
    and picked up afterwards -- and the continuation is persisted, so
    a restart between the two comes back to whichever prompt is up
    with the pass still owed. Nothing is recorded by this half: a
    match waiting on the speed has to read as waiting on the speed.

    Nothing moves here, which is why this is the one fixture of the
    rank whose board did not change.
    """
    match, passer = stand_a_pass(
        "setup_pass", passer_flat=3, speed=3,
    )
    return PassFixture(
        game=advanced_game(),
        match=match,
        entry="setup_pass_speed",
        passer_id=passer,
        narration=(
            f"**Setup Pass:** {label(match, passer)} sets the ball's "
            "speed before picking out the pass."
        ),
        board_changed=False,
        follow_on=SPEED_CHOICE,
        follow_on_kwargs={
            "player_id": passer,
            "skill_type": "offense",
            "distance_moved": CLOCK_COST,
        },
        ball_space=at(match, 3),
        ball_speed=3,
    )


def setup_pass_into_a_set_up() -> PassFixture:
    """
    The card doing what it is for: the ball picked out to a teammate,
    who takes a scoring opportunity with the speed the passer just set
    counting toward the shot.
    """
    match, passer = stand_a_pass("setup_pass", passer_flat=3, speed=5)
    receiver = put_a_teammate_on(match, 6, PlayerRole.STRIKER)
    return PassFixture(
        game=advanced_game(),
        match=match,
        entry="setup_pass",
        passer_id=passer,
        distance=3,
        narration=(
            "**Setup Pass:** the ball moves 3 spaces forward to "
            f"{label(match, receiver)} -- a scoring opportunity! "
            "Ball speed is 5."
        ),
        follow_on=SCORING_ATTEMPT,
        follow_on_kwargs={
            "shooter_id": receiver, "distance_moved": CLOCK_COST,
        },
        ball_space=lands_on(match, 3),
        ball_speed=5,
        carrier_id=receiver,
    )


def setup_pass_to_a_teammate_in_the_same_space() -> PassFixture:
    """
    **0 is the card's own exception**: it means a teammate sharing the
    passer's space, and it is on the menu only while somebody else is
    standing there -- a passer never receives their own pass.
    """
    match, passer = stand_a_pass("setup_pass", passer_flat=4, speed=2)
    receiver = put_a_teammate_on(match, 4, PlayerRole.WINGER)
    return PassFixture(
        game=advanced_game(),
        match=match,
        entry="setup_pass",
        passer_id=passer,
        distance=0,
        narration=(
            "**Setup Pass:** the ball goes to a teammate in the same "
            f"space to {label(match, receiver)} -- a scoring "
            "opportunity! Ball speed is 2."
        ),
        follow_on=SCORING_ATTEMPT,
        follow_on_kwargs={
            "shooter_id": receiver, "distance_moved": CLOCK_COST,
        },
        ball_space=at(match, 4),
        ball_speed=2,
        carrier_id=receiver,
    )


def setup_pass_onto_nobody() -> PassFixture:
    """
    **A pass that lands on nobody is still a pass** (2026-08-25). The
    card is a set-up, but missing the set-up does not un-throw the
    ball: it settles exactly where a deflection's does, so what is
    standing on the space is what decides how it is won. Refusing the
    distance instead is what used to make this the only pass in the
    game that could not be thrown badly.
    """
    match, passer = stand_a_pass("setup_pass", passer_flat=3, speed=2)
    clear_offense_from(match, 6)
    return PassFixture(
        game=advanced_game(),
        match=match,
        entry="setup_pass",
        passer_id=passer,
        distance=3,
        narration=(
            "**Setup Pass:** the ball is picked out 3 spaces forward, "
            "with nobody there to set up."
        ),
        follow_on=LOOSE_BALL,
        ball_space=lands_on(match, 3),
        ball_speed=2,
    )


def setup_pass_one_space_onto_nobody() -> PassFixture:
    """
    The same branch at a single space, which is the only thing that
    changes the word.
    """
    match, passer = stand_a_pass("setup_pass", passer_flat=3, speed=2)
    clear_offense_from(match, 4)
    return PassFixture(
        game=advanced_game(),
        match=match,
        entry="setup_pass",
        passer_id=passer,
        distance=1,
        narration=(
            "**Setup Pass:** the ball is picked out 1 space forward, "
            "with nobody there to set up."
        ),
        follow_on=LOOSE_BALL,
        ball_space=lands_on(match, 1),
        ball_speed=2,
    )


def setup_pass_at_zero_with_nobody_there() -> PassFixture:
    """
    Only reachable from a stale click -- 0 is offered while a teammate
    shares the passer's space, and every other distance only where it
    fits -- so nothing legal clamps to standing still. A ball that
    never left the passer is the High Pass's own dead end, and it goes
    out for the same reason rather than settling under their feet.
    """
    match, passer = stand_a_pass("setup_pass", passer_flat=4, speed=4)
    clear_offense_from(match, 4)
    return PassFixture(
        game=advanced_game(),
        match=match,
        entry="setup_pass",
        passer_id=passer,
        distance=0,
        narration=setup_pass_out_text(match),
        follow_on=RUN_BACK,
        follow_on_kwargs={
            "new_play": True, "distance_moved": CLOCK_COST,
        },
        possession=TeamSide.VISITING,
        ball_space=at(match, 4),
        ball_recovery=True,
    )


def setup_pass_with_no_distance_to_offer() -> PassFixture:
    """
    **Setup Pass cannot overshoot**, so the one way it runs out of
    play is having nowhere to throw it at all: the passer on the very
    last space of the field, with no teammate beside them to take it
    at 0. The menu never offers a distance, and this is the branch it
    goes to instead -- the same ending the stale click above reaches,
    from the other side.
    """
    match, passer = stand_a_pass("setup_pass", passer_flat=6, speed=4)
    clear_offense_from(match, 6)
    return PassFixture(
        game=advanced_game(),
        match=match,
        entry="setup_pass_out",
        passer_id=passer,
        narration=setup_pass_out_text(match),
        follow_on=RUN_BACK,
        follow_on_kwargs={
            "new_play": True, "distance_moved": CLOCK_COST,
        },
        possession=TeamSide.VISITING,
        ball_space=at(match, 6),
        ball_recovery=True,
    )


#: Every branch either card resolves through, in the order the code
#: checks them. A name here is the name a subtest reports under.
PASS_CASES = [
    PassCase(name=build.__name__, build=build)
    for build in (
        two_spaces_into_a_set_up,
        two_spaces_into_a_set_up_contested,
        two_spaces_short_of_shooting_range,
        an_overshoot_into_a_set_up,
        an_overshoot_with_no_modifier_to_pay,
        an_overshoot_onto_nobody,
        nowhere_left_to_throw_it,
        a_long_pass_into_a_contest,
        a_long_pass_onto_nobody,
        a_fullback_throws_four,
        a_beaten_intercept_leaves_the_reception_alone,
        the_speed_before_the_pass,
        setup_pass_into_a_set_up,
        setup_pass_to_a_teammate_in_the_same_space,
        setup_pass_onto_nobody,
        setup_pass_one_space_onto_nobody,
        setup_pass_at_zero_with_nobody_there,
        setup_pass_with_no_distance_to_offer,
    )
]
