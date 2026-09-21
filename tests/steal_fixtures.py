"""
A match standing in each branch a Steal or an Intercept resolves
through, and what that resolution should produce.

Rank D2 of Phase 3 of docs/model-discord-split.md moves the two cards'
own resolution out of the cog and into `d12ball/flow/effects.py`. The
thing worth asserting about a move like that is that **not one branch
changed what it said or what it did next**, and that needs one table
standing in every branch rather than the scattered assertions the
suite already had.

So the fixtures live here, built with no `discord` in scope, and two
test modules read the same table:

- `tests/test_d12ball_steal_flow.py` asks the model
  (`d12ball.flow.effects.steal_step`) for the `StepResult`.
- `tests/test_d12ball_steal_recording.py` asks the cog
  (`D12Ball.apply_steal`) what it handed the step that comes next.

The second one is the equivalence test, and it is the shape
`tests/low_pass_fixtures.py` gave Phase 2 and
`tests/dribble_fixtures.py` rank O2: it was written and run green
against the **old** cog before anything moved, so a green run
afterwards is the two answering the same way rather than two halves of
one new thing agreeing with each other. Its commit is the first on the
branch for exactly that reason.

**Rank D2 has no unchallenged branch.** A defense card only resolves
where a defender was sent -- an uncontested maneuver is the offense's
by definition -- so every fixture here has a challenger, and
`match.challenger_id` is who the steal is played by rather than who it
is played against.

**The expected narration is built, never spelled out, wherever it
names a player or a side** -- the roster is data the author revises
(see `roster.py`), and a side is named through the same formatter the
message uses. The distances are spelled out, because a distance the
fixture chose is a fact about the fixture rather than about the
roster.

**The follow-on step is named by its `FollowOnStep` member name**, a
string, so this module needs no import from `d12ball/flow/` -- which
is what let it be written before either member existed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from d12ball.ai import build_ai_strategies
from d12ball.components import (
    MatchState,
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

#: The turnover's own tail: everyone who is not carrying the ball runs
#: back, and the ball-speed choice rides on the flag rather than being
#: offered here. By `FollowOnStep` member name, spelled as a string so
#: this module stays free of the package under test.
RUN_BACK = "BEGIN_RUN_BACK"

#: The Intercept overshoot's ending instead: no field left ahead of
#: the interceptor, so it is a scoring opportunity and there is no run
#: back to make.
SHOOTER_CHOICE = "BEGIN_SHOOTER_CHOICE"


@dataclass
class StealFixture:
    """One match mid-steal, and everything resolving it should say."""

    game: D12BallGame
    match: MatchState
    #: Which card: `steal` or `intercept`.
    key: str
    #: The defender playing it -- `match.challenger_id`, held here so
    #: the assertions can name them after the match has moved them.
    challenger_id: str

    #: The narration, as one string: what the old cog built inline and
    #: handed the next step as its `lead_in`.
    narration: str = ""
    #: Whether the board moved -- what `refresh_match_image` decided.
    board_changed: bool = True
    #: Which step runs next, by `FollowOnStep` member name.
    follow_on: str = RUN_BACK
    #: The arguments that step is called with, `lead_in` aside.
    follow_on_kwargs: dict[str, Any] = field(
        default_factory=lambda: {"speed_choice_after": True},
    )

    #: What the match looks like afterwards.
    carrier_id: Optional[str] = None
    possession: TeamSide = TeamSide.VISITING
    ball_space: Optional[tuple[Zone, int]] = None
    challenger_space: Optional[tuple[Zone, int]] = None
    #: Every turnover drops the ball back to speed 1.
    ball_speed: int = 1
    #: `pending_effect_continuation` afterwards. Always None since
    #: Phase 6: the unopposed Low Pass a beaten Skilled Pass owes the
    #: defense is *said* by the steal and recorded when the speed
    #: choice behind the run back is answered (`speed_choice_step`),
    #: because the record is what `effect_choice_prompt` reads first
    #: and a match still owing the run back and the speed must not
    #: read as owing the pass.
    continuation: Optional[dict[str, Any]] = None


@dataclass(frozen=True)
class StealCase:
    """A fixture and the name it is reported under."""

    name: str
    build: Callable[[], StealFixture]


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


def new_possession_label(match: MatchState) -> str:
    """
    The side about to take the ball, worded the way the turnover's own
    sentence words it. Read before the steal runs, which is why it
    asks `defending_side` rather than reading possession back off a
    match that has already changed hands.
    """
    return format_team_side_label(
        match.setup_for_side(match.defending_side())
    )


def stand_a_steal(
    offense_key: str,
    defense_key: str,
    far_end_for: Optional[TeamSide] = None,
) -> tuple[MatchState, str]:
    """
    A match mid-maneuver with the defense's card the winning one, and
    the defender who played it handed back.

    `choose_challenger` walks the nearest defender onto the ball's
    space, which is where a contest happens, so a steal is always
    played from the handler's own space -- see "Sending a player" in
    docs/design/sending-a-player.md.

    `far_end_for` parks the handler and the ball on the last space of
    the field in that side's attacking direction **before** the
    challenger is chosen, so the challenger is walked to wherever the
    ball ended up. Nothing in the game walks a handler that far, but
    the two branches at the ends of the field only exist there -- the
    same reason `tests/dribble_fixtures.py` has a
    `walk_to_the_far_end`. The move is a relative one so it clamps,
    rather than a flat index this module would have to know the board
    size to name.
    """
    match = build_match()
    handler = match.eligible_ball_handlers()[0]
    match.select_ball_handler(handler)
    if far_end_for is not None:
        match.move_player_relative(
            handler, far_end_for, len(match.board.spaces_in_order()),
        )
        match.set_ball_space(*match.board.meeple_position(handler))
    challenger = min(
        match.visiting.field_players, key=match.distance_to_ball,
    )
    match.choose_challenger(challenger)
    match.choose_offense_maneuver(offense_key)
    match.choose_defense_maneuver(defense_key)
    return match, challenger


def carried_to(match: MatchState, player_id: str, direction: int):
    """
    Where a carry of one space in `direction` leaves the thief,
    relative to the side that is about to possess the ball. Clamped at
    the end of the field, the same way `move_player_relative` is.
    """
    origin = match.board.flat_index(*match.board.meeple_position(player_id))
    return match.board.position_at_flat_index(
        match.relative_flat_index(origin, match.defending_side(), direction)
    )


def turnover_text(
    match: MatchState,
    key: str,
    challenger: str,
    actual_distance: int,
) -> str:
    """
    The turnover sentence both cards share, built rather than spelled
    out. `travel` is the whole of the difference between them: a Steal
    falls back toward the goal the thief defends, an Intercept carries
    it on toward the one they now attack.
    """
    space_word = "space" if actual_distance == 1 else "spaces"
    travel = (
        f"then carries it {actual_distance} {space_word} forward, "
        "toward the goal they now attack"
        if key == "intercept"
        else f"then falls back {actual_distance} {space_word} toward "
        "their own goal with the ball"
    )
    return (
        f"**{ENGINE.maneuver_name(key)}:**\n"
        "# Turnover!\n"
        f"{label(match, challenger)} steals the ball. "
        f"{new_possession_label(match)} now has possession, "
        f"{travel}."
    )


#: What a beaten Skilled Pass says: the defense is owed an unopposed
#: Low Pass, played once the steal is finished -- the run back and the
#: speed choice both come first, and the speed choice is what records
#: it. See `pending_effect_continuation` in docs/design/maneuvers.md.
SKILLED_PASS_NOTE = (
    "\n\n**Skilled Pass** was beaten -- the defense gets an "
    "unopposed Low Pass once everyone is back in position."
)


# -- Steal -------------------------------------------------------------


def steal_plain() -> StealFixture:
    """
    The basic card: the ball changes hands and the thief falls back a
    space toward the goal they defend. The baseline the other steals
    are variations on.
    """
    match, challenger = stand_a_steal("low_pass", "steal")
    destination = carried_to(match, challenger, -1)
    return StealFixture(
        game=build_game(),
        match=match,
        key="steal",
        challenger_id=challenger,
        narration=turnover_text(match, "steal", challenger, 1),
        carrier_id=challenger,
        ball_space=destination,
        challenger_space=destination,
    )


def steal_with_nowhere_to_fall_back() -> StealFixture:
    """
    A thief already on the last space of the field behind them carries
    it nowhere: `move_player_relative` clamps, and the sentence reads
    the distance actually travelled.

    Nothing routes this into the Intercept overshoot -- that branch
    reads the key as well as the clamp -- so a Steal with nowhere to
    go still runs everybody back, which is the point of standing it
    here.
    """
    match, challenger = stand_a_steal(
        "low_pass", "steal", far_end_for=TeamSide.HOME,
    )
    where = match.board.meeple_position(challenger)
    return StealFixture(
        game=build_game(),
        match=match,
        key="steal",
        challenger_id=challenger,
        narration=turnover_text(match, "steal", challenger, 0),
        carrier_id=challenger,
        ball_space=where,
        challenger_space=where,
    )


def steal_beats_a_skilled_pass() -> StealFixture:
    """
    **Skilled Pass's cost**, charged inside the steal that beat it:
    the defense is owed an unopposed Low Pass, recorded on the match
    and said at the end of the steal's own message rather than played
    here -- the run back and the speed choice both come first.

    Species abilities are off so nothing else reads into the
    turnover.
    """
    match, challenger = stand_a_steal("skilled_pass", "steal")
    destination = carried_to(match, challenger, -1)
    return StealFixture(
        game=build_game(mode=GameMode.ADVANCED, species_abilities=False),
        match=match,
        key="steal",
        challenger_id=challenger,
        narration=(
            turnover_text(match, "steal", challenger, 1) + SKILLED_PASS_NOTE
        ),
        carrier_id=challenger,
        ball_space=destination,
        challenger_space=destination,
    )


# -- Intercept ---------------------------------------------------------


def intercept_plain() -> StealFixture:
    """
    The gambit is the basic Steal with the sign flipped: the
    interceptor carries the ball **forward**, toward the goal they now
    attack. It is the only card in the game that moves the ball
    against the way the offense was going.
    """
    match, challenger = stand_a_steal("low_pass", "intercept")
    destination = carried_to(match, challenger, 1)
    return StealFixture(
        game=build_game(mode=GameMode.ADVANCED, species_abilities=False),
        match=match,
        key="intercept",
        challenger_id=challenger,
        narration=turnover_text(match, "intercept", challenger, 1),
        carrier_id=challenger,
        ball_space=destination,
        challenger_space=destination,
    )


def intercept_beats_a_skilled_pass() -> StealFixture:
    """
    The same cost on the other card of the rank. Worth its own fixture
    rather than trusting the Steal's: this is where the note is pinned
    after a sentence that reads the other way.
    """
    match, challenger = stand_a_steal("skilled_pass", "intercept")
    destination = carried_to(match, challenger, 1)
    return StealFixture(
        game=build_game(mode=GameMode.ADVANCED, species_abilities=False),
        match=match,
        key="intercept",
        challenger_id=challenger,
        narration=(
            turnover_text(match, "intercept", challenger, 1)
            + SKILLED_PASS_NOTE
        ),
        carrier_id=challenger,
        ball_space=destination,
        challenger_space=destination,
    )


def intercept_with_no_field_left() -> StealFixture:
    """
    **The interceptor was already on the last space toward the goal
    they now attack, so there is nowhere to carry it: it is a scoring
    opportunity instead** (the author, 2026-08-19).

    Straight to the shot, so there is no run back and no speed choice
    -- which is the one thing about this branch worth watching, and
    the reason it is recorded with the rest.
    """
    match, challenger = stand_a_steal(
        "low_pass", "intercept", far_end_for=TeamSide.VISITING,
    )
    where = match.board.meeple_position(challenger)
    return StealFixture(
        game=build_game(mode=GameMode.ADVANCED, species_abilities=False),
        match=match,
        key="intercept",
        challenger_id=challenger,
        narration=(
            turnover_text(match, "intercept", challenger, 0)
            + "\n\nThere is no field left ahead of them -- "
            "a scoring opportunity!"
        ),
        follow_on=SHOOTER_CHOICE,
        follow_on_kwargs={"candidates": [challenger]},
        carrier_id=challenger,
        ball_space=where,
        challenger_space=where,
    )


STEAL_CASES: tuple[StealCase, ...] = (
    StealCase("steal_plain", steal_plain),
    StealCase(
        "steal_with_nowhere_to_fall_back", steal_with_nowhere_to_fall_back,
    ),
    StealCase("steal_beats_a_skilled_pass", steal_beats_a_skilled_pass),
    StealCase("intercept_plain", intercept_plain),
    StealCase(
        "intercept_beats_a_skilled_pass", intercept_beats_a_skilled_pass,
    ),
    StealCase(
        "intercept_with_no_field_left", intercept_with_no_field_left,
    ),
)
