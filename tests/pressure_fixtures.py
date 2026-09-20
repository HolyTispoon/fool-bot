"""
A match standing in each branch a Pressure or a Double Team resolves
through, and what that resolution should produce.

Rank D3 of Phase 3 of docs/model-discord-split.md moves the two cards'
own resolution out of the cog and into `d12ball/flow/effects.py`. The
thing worth asserting about a move like that is that **not one branch
changed what it said or what it did next**, and that needs one table
standing in every branch rather than the scattered assertions the
suite already had.

So the fixtures live here, built with no `discord` in scope, and two
test modules read the same table:

- `tests/test_d12ball_pressure_flow.py` asks the model
  (`d12ball.flow.effects.pressure_step`) for the `StepResult`.
- `tests/test_d12ball_pressure_recording.py` asks the cog
  (`D12Ball.apply_pressure`) what it handed the step that comes next.

The second one is the equivalence test, and it is the shape
`tests/low_pass_fixtures.py` gave Phase 2, `tests/dribble_fixtures.py`
rank O2 and `tests/steal_fixtures.py` rank D2: it was written and run
green against the **old** cog before anything moved, so a green run
afterwards is the two answering the same way rather than two halves of
one new thing agreeing with each other. Its commit is the first on the
branch for exactly that reason.

**Rank D3 has no unchallenged branch**, the same as rank D2: a defense
card only resolves where a defender was sent, so every fixture here
has a challenger and `match.challenger_id` is who the pressure is
played by rather than who it is played against.

**The overshoot branch is the one place the old cog posted a message
of its own.** Everywhere else the narration reached the next step as
its `lead_in`; an overshooting Pressure posted the shove, refreshed
the board and *then* asked for the own-goal roll, so the branch cost
two messages. The table records the text either way and
`tests/test_d12ball_pressure_recording.py` reads whichever carried it,
which is what lets one table answer for the shape before the move and
the shape after it -- the trick rank D2 used on `inspect.signature`,
applied to a message rather than to an argument.

**The expected narration is built, never spelled out, wherever it
names a player or a side** -- the roster is data the author revises
(see `roster.py`), and a side is named through the same formatter the
message uses. The distances are spelled out, because a distance the
fixture chose is a fact about the fixture rather than about the
roster.

**The follow-on step is named by its `FollowOnStep` member name**, a
string, so this module needs no import from `d12ball/flow/` -- which
is what let it be written before `BEGIN_OWN_GOAL_ROLL` existed.
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

CATALOG = load_player_catalog()
RULESET = load_basic_ruleset()
MANEUVERS = load_maneuver_catalog()
ENGINE = RulesEngine(
    CATALOG, RULESET, MANEUVERS, build_ai_strategies(CATALOG, MANEUVERS),
)

GAME_ID = "g1"

#: The ordinary tail of a maneuver that turned nothing over: the
#: clock, the end of a period, the offensive choice handed back. By
#: `FollowOnStep` member name, spelled as a string so this module
#: stays free of the package under test.
FINISH = "FINISH_MANEUVER_RESOLUTION"

#: The tail of a turnover -- a Defender's steal on a won pressure, or
#: the possession a beaten Dribble Burst hands over.
RUN_BACK = "BEGIN_RUN_BACK"

#: The overshoot's ending instead: there was nowhere left to push the
#: handler, so the shove threatens their own net and the roll that
#: settles it goes behind a button.
OWN_GOAL_ROLL = "BEGIN_OWN_GOAL_ROLL"


@dataclass
class PressureFixture:
    """One match mid-pressure, and everything resolving it should say."""

    game: D12BallGame
    match: MatchState
    #: Which card: `pressure` or `double_team`.
    key: str
    #: The handler being shoved -- `match.active_player_id`, held here
    #: so the assertions can name them after the match has moved them.
    handler_id: str
    #: The defender playing the card -- `match.challenger_id`.
    challenger_id: str
    #: The teammate a Double Team brings in, or None for a Pressure.
    partner_id: Optional[str] = None

    #: The narration, as one string: what the old cog built inline and
    #: handed the next step as its `lead_in` -- or, on the overshoot
    #: branch alone, posted as a message of its own.
    narration: str = ""
    #: Whether the board moved -- what `refresh_match_image` decided.
    #: True on every branch: even a shove with nowhere to go walks the
    #: challenger onto the handler's space.
    board_changed: bool = True
    #: Which step runs next, by `FollowOnStep` member name.
    follow_on: str = FINISH
    #: The arguments that step is called with, `lead_in` aside.
    follow_on_kwargs: dict[str, Any] = field(
        default_factory=lambda: {"distance_moved": 1},
    )

    #: What the match looks like afterwards.
    carrier_id: Optional[str] = None
    possession: TeamSide = TeamSide.HOME
    ball_space: Optional[tuple[Zone, int]] = None
    handler_space: Optional[tuple[Zone, int]] = None
    challenger_space: Optional[tuple[Zone, int]] = None
    ball_speed: int = 1
    #: The pair left challenging the next maneuver -- empty where the
    #: card does not leave one, which is what the match itself holds.
    pending_double_team: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PressureCase:
    """A fixture and the name it is reported under."""

    name: str
    build: Callable[[], PressureFixture]


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
    `tests/steal_fixtures.py` puts on its advanced fixtures.
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


def defense_label(match: MatchState) -> str:
    """
    The side taking the ball, worded the way the turnover's own
    sentence words it. Read off `defending_side` rather than off a
    match that may already have changed hands.
    """
    return format_team_side_label(
        match.setup_for_side(match.defending_side())
    )


def stand_a_pressure(
    offense_key: str,
    defense_key: str,
    role: PlayerRole = PlayerRole.MIDFIELDER,
    back_from_own_goal: Optional[int] = None,
) -> tuple[MatchState, str, str]:
    """
    A match mid-maneuver with the defense's card the winning one: the
    handler, and the defender standing on them who played it.

    The challenger is **placed** on the ball's space rather than walked
    there by `choose_challenger`, which is what
    `tests/test_d12ball_ball_carrier.py` does for the same reason: a
    walk charges exhaustion for the distance, and which role is
    standing there is the whole difference between two of these
    fixtures. Pressure is role-sensitive -- a Defender also steals the
    ball on a win -- so `role` is a parameter rather than "the nearest".

    `back_from_own_goal` parks the handler and the ball that many
    spaces out from the last space toward their own goal, before the
    challenger is placed. 0 is the only space a Pressure can overshoot
    from; 1 is the only one a Double Team can, and it shoves them a
    real space first. Nothing in the game walks a handler there, but
    the branch exists only there -- the same reason
    `tests/steal_fixtures.py` has a `far_end_for`.
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


def shoved_to(match: MatchState, handler: str, push: int):
    """
    Where a shove of `push` leaves the handler, relative to the side
    that still has the ball. Clamped at the end of the field, the same
    way `move_player_relative` is.
    """
    origin = match.board.flat_index(*match.board.meeple_position(handler))
    return match.board.position_at_flat_index(
        match.relative_flat_index(origin, match.ball.possession, -push)
    )


def shove_distance(match: MatchState, handler: str, push: int) -> int:
    """How far that shove actually travels once the board has clamped it."""
    origin = match.board.flat_index(*match.board.meeple_position(handler))
    target = match.board.flat_index(*shoved_to(match, handler, push))
    return abs(target - origin)


def shove_text(
    match: MatchState,
    key: str,
    handler: str,
    challenger: str,
    actual_distance: int,
    partner: Optional[str] = None,
) -> str:
    """
    The sentence both cards share, built rather than spelled out, plus
    the Double Team's record of who is left challenging next.
    """
    space_word = "space" if actual_distance == 1 else "spaces"
    content = (
        f"**{ENGINE.maneuver_name(key)}:** "
        f"{label(match, handler)} and the "
        f"ball go back {actual_distance} {space_word}. "
        f"{label(match, challenger)} moves "
        "forward."
    )
    if partner is not None:
        content += (
            f" {label(match, partner)} "
            "joins them -- and **both** will challenge on the next "
            "maneuver, each adding their defensive skill."
        )
    return content


def defender_steal_text(match: MatchState, challenger: str) -> str:
    """
    **Role ability -- Defender**: a won pressure also takes the ball,
    on top of the shove. Every turnover drops the speed back to 1,
    which is why this branch is the one that says nothing about speed.
    """
    return (
        "\n\n# Turnover!\n"
        f"{label(match, challenger)} "
        "steals the ball (Defender ability)! "
        f"{defense_label(match)} "
        "now has possession."
    )


def burst_cost_text(match: MatchState, speed: int) -> str:
    """
    **Dribble Burst's cost**: the offense loses possession *and* the
    ball keeps the speed the burst put into it -- the first exception
    to "every turnover resets ball speed to 1", which is why the
    number is in the sentence.
    """
    return (
        "\n\n# Turnover!\n"
        "**Dribble Burst** was beaten -- "
        f"{defense_label(match)} "
        "take the ball, and it keeps the speed the burst put into "
        f"it ({speed})."
    )


#: What an overshooting shove adds, and the whole of what sends the
#: turn to the own-goal roll instead of to the ordinary tail.
OVERSHOOT_NOTE = "\n\nThat overshoots toward their own goal!"


# -- Pressure ----------------------------------------------------------


def pressure_plain() -> PressureFixture:
    """
    The basic card: the handler and the ball go back a space and the
    challenger takes the space they left. Nothing changes hands -- the
    handler was pressured and kept the ball, so they carry it into
    their side's next turn. The baseline the rest are variations on.
    """
    match, handler, challenger = stand_a_pressure("low_pass", "pressure")
    destination = shoved_to(match, handler, 1)
    return PressureFixture(
        game=build_game(),
        match=match,
        key="pressure",
        handler_id=handler,
        challenger_id=challenger,
        narration=shove_text(match, "pressure", handler, challenger, 1),
        carrier_id=handler,
        ball_space=destination,
        handler_space=destination,
        challenger_space=destination,
    )


def pressure_by_a_defender() -> PressureFixture:
    """
    **Role ability -- Defender**: the same shove, and the ball as well.
    The steal is on top of the normal effect rather than instead of
    it, so the handler is still pushed back a space before it lands --
    and the carry moves to the Defender, who stays put while everybody
    else runs back.
    """
    match, handler, challenger = stand_a_pressure(
        "low_pass", "pressure", role=PlayerRole.DEFENDER,
    )
    destination = shoved_to(match, handler, 1)
    return PressureFixture(
        game=build_game(),
        match=match,
        key="pressure",
        handler_id=handler,
        challenger_id=challenger,
        narration=(
            shove_text(match, "pressure", handler, challenger, 1)
            + defender_steal_text(match, challenger)
        ),
        follow_on=RUN_BACK,
        follow_on_kwargs={},
        carrier_id=challenger,
        possession=TeamSide.VISITING,
        ball_space=destination,
        handler_space=destination,
        challenger_space=destination,
    )


def pressure_that_overshoots() -> PressureFixture:
    """
    **The handler is already on the space closest to their own goal**,
    so there is nowhere to push them back to and the shove threatens
    their own net. The roll that settles it goes behind a button, so
    this is where the effect stops rather than where it hands over.

    An own goal takes priority over the Defender's steal: the branch
    returns before the turnover is read at all, which is why the
    challenger here is a Midfielder and the question does not arise.
    """
    match, handler, challenger = stand_a_pressure(
        "low_pass", "pressure", back_from_own_goal=0,
    )
    where = match.board.meeple_position(handler)
    return PressureFixture(
        game=build_game(),
        match=match,
        key="pressure",
        handler_id=handler,
        challenger_id=challenger,
        narration=(
            shove_text(match, "pressure", handler, challenger, 0)
            + OVERSHOOT_NOTE
        ),
        follow_on=OWN_GOAL_ROLL,
        follow_on_kwargs={"distance_moved": 1},
        carrier_id=handler,
        ball_space=where,
        handler_space=where,
        challenger_space=where,
    )


def pressure_beats_a_dribble_burst() -> PressureFixture:
    """
    **Dribble Burst's cost**, charged inside the pressure that beat
    it: the offense loses the ball *and* the defense keeps the speed
    the burst put into it, then sets it themselves once everyone is
    back. Nothing else in the game turns the ball over without
    resetting the speed, so the speed is asserted rather than assumed.
    """
    match, handler, challenger = stand_a_pressure(
        "dribble_burst", "pressure",
    )
    match.ball.speed = 3
    destination = shoved_to(match, handler, 1)
    return PressureFixture(
        game=advanced_game(),
        match=match,
        key="pressure",
        handler_id=handler,
        challenger_id=challenger,
        narration=(
            shove_text(match, "pressure", handler, challenger, 1)
            + burst_cost_text(match, 3)
        ),
        follow_on=RUN_BACK,
        follow_on_kwargs={"speed_choice_after": True, "speed_reset": False},
        carrier_id=challenger,
        possession=TeamSide.VISITING,
        ball_space=destination,
        handler_space=destination,
        challenger_space=destination,
        ball_speed=3,
    )


def pressure_by_a_defender_beats_a_dribble_burst() -> PressureFixture:
    """
    The two turnovers are exclusive and in that order: a burst cost
    has already taken the ball, so the Defender's ability has nothing
    left to take and says nothing. Worth its own fixture because the
    only thing distinguishing it from the one above is a sentence that
    is *not* there.
    """
    match, handler, challenger = stand_a_pressure(
        "dribble_burst", "pressure", role=PlayerRole.DEFENDER,
    )
    match.ball.speed = 4
    destination = shoved_to(match, handler, 1)
    return PressureFixture(
        game=advanced_game(),
        match=match,
        key="pressure",
        handler_id=handler,
        challenger_id=challenger,
        narration=(
            shove_text(match, "pressure", handler, challenger, 1)
            + burst_cost_text(match, 4)
        ),
        follow_on=RUN_BACK,
        follow_on_kwargs={"speed_choice_after": True, "speed_reset": False},
        carrier_id=challenger,
        possession=TeamSide.VISITING,
        ball_space=destination,
        handler_space=destination,
        challenger_space=destination,
        ball_speed=4,
    )


# -- Double Team -------------------------------------------------------


def double_team_plain() -> PressureFixture:
    """
    The advanced card is Pressure at two spaces with a second defender
    brought in free of exhaustion -- **placed** on the handler's new
    space rather than run to it, which is what "no exhaustion cost"
    means in a game where every other way to reach a space charges a
    token a space.

    It is also the one card whose effect lands on the *following*
    maneuver: `pending_double_team` is the pair, not a flag, so the
    next turn knows who challenges without re-deriving it off a board
    that has moved since.
    """
    match, handler, challenger = stand_a_pressure(
        "low_pass", "double_team",
    )
    partner = ENGINE.double_team_partner(match)
    destination = shoved_to(match, handler, 2)
    return PressureFixture(
        game=advanced_game(),
        match=match,
        key="double_team",
        handler_id=handler,
        challenger_id=challenger,
        partner_id=partner,
        narration=shove_text(
            match, "double_team", handler, challenger, 2, partner,
        ),
        carrier_id=handler,
        ball_space=destination,
        handler_space=destination,
        challenger_space=destination,
        pending_double_team=[challenger, partner],
    )


def double_team_that_overshoots() -> PressureFixture:
    """
    A Double Team overshoots from one space further out than a
    Pressure can, and **it shoves them a real space first**: the push
    of 2 clamps to 1, so the sentence reads the distance actually
    travelled and the ball has moved by the time the roll is asked
    for.

    The pair is still recorded. The shove's own wording runs before
    the overshoot is read, so a Double Team that ends in an own-goal
    roll still leaves both defenders challenging the next maneuver --
    which, if the roll is survived, is the next maneuver of a restart.
    """
    match, handler, challenger = stand_a_pressure(
        "low_pass", "double_team", back_from_own_goal=1,
    )
    partner = ENGINE.double_team_partner(match)
    destination = shoved_to(match, handler, 2)
    return PressureFixture(
        game=advanced_game(),
        match=match,
        key="double_team",
        handler_id=handler,
        challenger_id=challenger,
        partner_id=partner,
        narration=(
            shove_text(
                match, "double_team", handler, challenger, 1, partner,
            )
            + OVERSHOOT_NOTE
        ),
        follow_on=OWN_GOAL_ROLL,
        follow_on_kwargs={"distance_moved": 1},
        carrier_id=handler,
        ball_space=destination,
        handler_space=destination,
        challenger_space=destination,
        pending_double_team=[challenger, partner],
    )


def double_team_beats_a_dribble_burst() -> PressureFixture:
    """
    The same cost on the other card of the rank. Worth its own fixture
    rather than trusting the Pressure's: this is where the turnover is
    pinned after a sentence that has already said two more things, and
    where the pair recorded for the next maneuver has to survive a
    branch that hands the ball over.
    """
    match, handler, challenger = stand_a_pressure(
        "dribble_burst", "double_team",
    )
    partner = ENGINE.double_team_partner(match)
    match.ball.speed = 2
    destination = shoved_to(match, handler, 2)
    return PressureFixture(
        game=advanced_game(),
        match=match,
        key="double_team",
        handler_id=handler,
        challenger_id=challenger,
        partner_id=partner,
        narration=(
            shove_text(
                match, "double_team", handler, challenger, 2, partner,
            )
            + burst_cost_text(match, 2)
        ),
        follow_on=RUN_BACK,
        follow_on_kwargs={"speed_choice_after": True, "speed_reset": False},
        carrier_id=challenger,
        possession=TeamSide.VISITING,
        ball_space=destination,
        handler_space=destination,
        challenger_space=destination,
        ball_speed=2,
        pending_double_team=[challenger, partner],
    )


PRESSURE_CASES: tuple[PressureCase, ...] = (
    PressureCase("pressure_plain", pressure_plain),
    PressureCase("pressure_by_a_defender", pressure_by_a_defender),
    PressureCase("pressure_that_overshoots", pressure_that_overshoots),
    PressureCase(
        "pressure_beats_a_dribble_burst", pressure_beats_a_dribble_burst,
    ),
    PressureCase(
        "pressure_by_a_defender_beats_a_dribble_burst",
        pressure_by_a_defender_beats_a_dribble_burst,
    ),
    PressureCase("double_team_plain", double_team_plain),
    PressureCase(
        "double_team_that_overshoots", double_team_that_overshoots,
    ),
    PressureCase(
        "double_team_beats_a_dribble_burst",
        double_team_beats_a_dribble_burst,
    ),
)
