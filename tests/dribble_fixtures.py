"""
A match standing in each branch the two dribbles resolve through, and
what that resolution should produce.

Rank O2 of Phase 3 of docs/model-discord-split.md moves Dribble Advance
and Dribble Burst out of the cog and into `d12ball/flow/effects.py`.
The thing worth asserting about a move like that is that **not one
branch changed what it said or what it did next**, and that needs one
table standing in every branch rather than the scattered assertions the
suite already had.

So the fixtures live here, built with no `discord` in scope, and two
test modules read the same table:

- `tests/test_d12ball_dribble_flow.py` asks the model
  (`d12ball.flow.effects.dribble_advance_step` /
  `dribble_burst_step`) for the `StepResult`.
- `tests/test_d12ball_dribble_recording.py` asks the cog
  (`D12Ball.apply_dribble_advance` / `apply_dribble_burst`) what it
  handed the step that comes next.

The second one is the equivalence test, and it is the same shape
`tests/low_pass_fixtures.py` gave Phase 2: it was written and run green
against the **old** cog before anything moved, so a green run after the
move is the two answering the same way rather than two halves of one
new thing agreeing with each other. Its commit is the first on the
branch for exactly that reason.

**The expected narration is built, never spelled out, wherever it reads
the roster** -- that is data the author revises (see `roster.py`), so a
fixture holding a name or a defensive skill would break on the next
revision for no reason connected to dribbling. A number the fixture
itself chose is spelled: a distance picked here, and the tokens that
follow from it, are facts about the fixture. A number read off a player
-- the Exhausted line one case runs a handler past -- is built.

**The condition emoji are spelled out as their fallbacks**, because the
cog under test has fetched none: an application with no `exhaust`
upload writes the plain emoji, and that is what these fixtures stand
in. They are facts about an empty `condition_emojis`, not about the
roster -- see `load_condition_emojis`.

**The follow-on step is named by its `FollowOnStep` member name**, a
string, so this module needs no import from `d12ball/flow/` -- which is
what lets it be read by the recording test before the step exists.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from d12ball.ai import build_ai_strategies
from d12ball.components import (
    MatchState,
    PlayerRole,
    SPECIES_CYBORG,
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

#: The one follow-on step a dribble can end on, by `FollowOnStep`
#: member name. Spelled as a string so this module stays free of the
#: package under test -- see the note on the roster above.
SPEED_CHOICE = "OFFER_SPEED_CHOICE"

#: What `get_exhaust_emoji` and `get_exhausted_emoji` answer when the
#: application has uploaded neither -- which is every cog in this
#: suite. Spelled here rather than imported, so the fixture asserts the
#: text a coach reads rather than re-deriving it from the lookup under
#: test.
EXHAUST = "\U0001f62e‍\U0001f4a8"
EXHAUSTED = "\U0001f975"


@dataclass
class DribbleFixture:
    """One match mid-dribble, and everything resolving it should say."""

    game: D12BallGame
    match: MatchState
    distance: int
    #: Which card this is: "dribble_advance" or "dribble_burst". The
    #: two are separate steps rather than one parameterised by key --
    #: unlike Skilled Pass, a burst is not an advance with bigger
    #: numbers, it charges by distance and words a run of nowhere.
    key: str = "dribble_advance"

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
    #: The handler's exhaustion total once the run has been charged.
    exhaustion: int = 0


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


def hand_the_ball_to(match: MatchState, player_id: str) -> str:
    """
    Stand `player_id` on the ball and make them the handler, so the
    dribble under test is theirs. The standard deal decides where
    everybody starts, and a test about a dribble should not also be a
    test of the deal.
    """
    zone, space_index = match.board.meeple_position(player_id)
    match.set_ball_space(zone, space_index)
    match.ball.possession = TeamSide.HOME
    match.select_ball_handler(player_id)
    return player_id


def walk_to_the_last_space(match: MatchState, player_id: str) -> None:
    """
    Put the handler on the last space of the goal they attack, where a
    dribble has nowhere left to run. Walked with the same relative move
    the dribble itself uses, so the fixture cannot disagree with the
    board about which end that is.
    """
    match.move_player_relative(player_id, TeamSide.HOME, 12)
    zone, space_index = match.board.meeple_position(player_id)
    match.set_ball_space(zone, space_index)


def beaten_clear(
    match: MatchState, game: D12BallGame, offense_key: str,
) -> str:
    """
    Stand the match in "the defense played Clear and lost on the
    cards", so the winning dribble collects the advanced cost. Hands
    back the defender who played it, who is who the cost is charged
    to.

    **The challenger is walked onto the ball's space first**, so the
    walk-in charges nothing and the only exhaustion in the message is
    the cost itself. A challenger chosen from where the deal left them
    arrives with a token already spent, and the fixture would then be
    pinning the walk-in as well as the cost.

    **And they are chosen for not having Lithium Powered**, because a
    Cyborg's tokens are *drain* and are called that (see
    "species-abilities.md"). That branch of `describe_exhaustion_gain`
    is shared by every exhaustion site in the game and is tested where
    it belongs, in `tests/test_d12ball_species_abilities.py`; what this
    fixture is about is the cost riding inside the dribble's own
    message. Picking by the ability rather than by name keeps it that
    way after the next roster revision.
    """
    challenger = next(
        player_id
        for player_id in sorted(
            match.visiting.field_players, key=match.distance_to_ball,
        )
        if not ENGINE.has_species_ability(game, player_id, SPECIES_CYBORG)
    )
    match.move_meeple(challenger, match.ball.zone, match.ball.space_index)
    match.choose_challenger(challenger)
    match.choose_offense_maneuver(offense_key)
    match.choose_defense_maneuver("clear")
    return challenger


# -- Dribble Advance ---------------------------------------------------


def advance_one_space() -> DribbleFixture:
    """
    The fixed 1-space advance every role but the Playmaker gets, and
    the baseline the rest of the card is a variation on.
    """
    match = build_match()
    handler = hand_the_ball_to(match, fielded(match, PlayerRole.MIDFIELDER))
    return DribbleFixture(
        game=build_game(),
        match=match,
        distance=1,
        narration=(
            f"**Dribble Advance:** {label(match, handler)} and the "
            "ball move forward 1 space."
        ),
        follow_on_kwargs={"player_id": handler, "skill_type": "offense"},
        carrier_id=handler,
        ball_space=(Zone.MIDFIELD, 1),
    )


def advance_two_spaces_as_playmaker() -> DribbleFixture:
    """
    Role ability -- a Playmaker may advance 2 instead of 1, and the
    note is what says so. The only branch that appends it.
    """
    match = build_match()
    handler = hand_the_ball_to(match, fielded(match, PlayerRole.PLAYMAKER))
    return DribbleFixture(
        game=build_game(),
        match=match,
        distance=2,
        narration=(
            f"**Dribble Advance:** {label(match, handler)} and the "
            "ball move forward 2 spaces (Playmaker ability)."
        ),
        follow_on_kwargs={"player_id": handler, "skill_type": "offense"},
        carrier_id=handler,
        ball_space=(Zone.VISITORS_GOAL, 0),
    )


def advance_one_space_as_playmaker() -> DribbleFixture:
    """
    The same Playmaker taking the ordinary 1. The note is on the
    distance rather than on the role, so it says nothing here -- which
    is the half of that condition a test of the 2 would miss.
    """
    match = build_match()
    handler = hand_the_ball_to(match, fielded(match, PlayerRole.PLAYMAKER))
    return DribbleFixture(
        game=build_game(),
        match=match,
        distance=1,
        narration=(
            f"**Dribble Advance:** {label(match, handler)} and the "
            "ball move forward 1 space."
        ),
        follow_on_kwargs={"player_id": handler, "skill_type": "offense"},
        carrier_id=handler,
        ball_space=(Zone.MIDFIELD, 2),
    )


def advance_clamped_at_the_end_of_the_field() -> DribbleFixture:
    """
    A Playmaker's 2 from the last space of the field. `actual_distance`
    is 0 and the wording reads it rather than the pick -- and the
    ability note goes with it, because the note is conditioned on the
    distance asked for rather than on the ground covered.
    """
    match = build_match()
    handler = hand_the_ball_to(match, fielded(match, PlayerRole.PLAYMAKER))
    walk_to_the_last_space(match, handler)
    space = match.board.meeple_position(handler)
    return DribbleFixture(
        game=build_game(),
        match=match,
        distance=2,
        narration=(
            f"**Dribble Advance:** {label(match, handler)} and the "
            "ball move forward 0 spaces (Playmaker ability)."
        ),
        follow_on_kwargs={"player_id": handler, "skill_type": "offense"},
        carrier_id=handler,
        ball_space=space,
    )


def advance_collects_a_beaten_clear() -> DribbleFixture:
    """
    **Clear's cost**, charged inside the dribble that beat it: a flat 2
    exhaustion on the defender who played it. It is paid in the middle
    of this step's own wording, which is why it belongs to the move
    rather than to whatever runs next.
    """
    match = build_match()
    game = build_game(mode=GameMode.ADVANCED)
    handler = hand_the_ball_to(match, fielded(match, PlayerRole.MIDFIELDER))
    challenger = beaten_clear(match, game, "dribble_advance")
    return DribbleFixture(
        game=game,
        match=match,
        distance=1,
        narration=(
            f"**Dribble Advance:** {label(match, handler)} and the "
            "ball move forward 1 space."
            "\n\n**Clear** was beaten -- 2 exhaustion.\n"
            f"{label(match, challenger)} gains 2 exhaustion tokens "
            f"{EXHAUST * 2} (now 2 total)."
        ),
        follow_on_kwargs={"player_id": handler, "skill_type": "offense"},
        carrier_id=handler,
        ball_space=(Zone.MIDFIELD, 1),
    )


# -- Dribble Burst -----------------------------------------------------


def burst_three_spaces() -> DribbleFixture:
    """
    The ordinary run: three spaces past everyone in the way, at a token
    a space. The baseline for the card that charges by distance.
    """
    match = build_match()
    handler = hand_the_ball_to(match, fielded(match, PlayerRole.MIDFIELDER))
    return DribbleFixture(
        game=build_game(),
        match=match,
        distance=3,
        key="dribble_burst",
        narration=(
            f"**Dribble Burst:** {label(match, handler)} bursts 3 "
            "spaces forward, past everyone in the way."
            f"\n{label(match, handler)} gains 3 exhaustion tokens "
            f"{EXHAUST * 3} (now 3 total)."
        ),
        follow_on_kwargs={"player_id": handler, "skill_type": "offense"},
        carrier_id=handler,
        ball_space=(Zone.VISITORS_GOAL, 0),
        exhaustion=3,
    )


def burst_as_playmaker() -> DribbleFixture:
    """
    **The Playmaker pays one token fewer** (the author, 2026-08-19)
    rather than running an extra space -- the only ability that reads
    differently on the two cards of this rank. Two lines say it: the
    discount note, and a token count one short of the distance.
    """
    match = build_match()
    handler = hand_the_ball_to(match, fielded(match, PlayerRole.PLAYMAKER))
    return DribbleFixture(
        game=build_game(),
        match=match,
        distance=3,
        key="dribble_burst",
        narration=(
            f"**Dribble Burst:** {label(match, handler)} bursts 3 "
            "spaces forward, past everyone in the way."
            " That costs them a token less (Playmaker ability)."
            f"\n{label(match, handler)} gains 2 exhaustion tokens "
            f"{EXHAUST * 2} (now 2 total)."
        ),
        follow_on_kwargs={"player_id": handler, "skill_type": "offense"},
        carrier_id=handler,
        ball_space=(Zone.VISITORS_GOAL, 1),
        exhaustion=2,
    )


def burst_tips_the_handler_over_their_line() -> DribbleFixture:
    """
    A run that costs more than the runner had left: the tokens are
    charged and the Exhausted line is re-tested **in the same breath**,
    so the transition is announced inside the burst's own message.

    That ordering is the whole reason `apply_exhaustion` exists (the
    flag used to be set after the save and never written out), and this
    is the branch that would notice it being lost in the move.

    The starting tokens and the total are read off the player's own
    threshold rather than spelled, because a defensive skill is roster
    data -- what is pinned here is the wording around the number.
    """
    match = build_match()
    game = build_game()
    handler = hand_the_ball_to(match, fielded(match, PlayerRole.MIDFIELDER))
    # One short of over: `mark_exhausted_if_needed` marks on *greater
    # than*, so a player sitting on their threshold is not Exhausted
    # yet and the next token is what tips them.
    already = ENGINE.exhaustion_threshold(game, handler)
    match.add_exhaustion(handler, already)
    return DribbleFixture(
        game=game,
        match=match,
        distance=3,
        key="dribble_burst",
        narration=(
            f"**Dribble Burst:** {label(match, handler)} bursts 3 "
            "spaces forward, past everyone in the way."
            f"\n{label(match, handler)} gains 3 exhaustion tokens "
            f"{EXHAUST * 3} (now {already + 3} total)."
            f"\n{label(match, handler)} is now *exhausted* {EXHAUSTED}"
        ),
        follow_on_kwargs={"player_id": handler, "skill_type": "offense"},
        carrier_id=handler,
        ball_space=(Zone.VISITORS_GOAL, 0),
        exhaustion=already + 3,
    )


def burst_with_nowhere_to_go() -> DribbleFixture:
    """
    From the last space of the field the burst has no ground to cover,
    so it is said plainly rather than reported as a run of 0 spaces --
    and it costs nothing, which is why no exhaustion line follows it.
    `resolve_dribble_burst` applies this without a menu.
    """
    match = build_match()
    handler = hand_the_ball_to(match, fielded(match, PlayerRole.STRIKER))
    walk_to_the_last_space(match, handler)
    space = match.board.meeple_position(handler)
    return DribbleFixture(
        game=build_game(),
        match=match,
        distance=0,
        key="dribble_burst",
        narration=(
            f"**Dribble Burst:** {label(match, handler)} is already as "
            "far forward as the field goes, so the ball stays where it "
            "is."
        ),
        follow_on_kwargs={"player_id": handler, "skill_type": "offense"},
        carrier_id=handler,
        ball_space=space,
    )


def burst_with_nowhere_to_go_as_playmaker() -> DribbleFixture:
    """
    The same run of nowhere by a Playmaker. **The discount says
    nothing**, because no token was saved -- a burst that moved nowhere
    is free for everybody. The half of that condition the ordinary
    Playmaker burst cannot show.
    """
    match = build_match()
    handler = hand_the_ball_to(match, fielded(match, PlayerRole.PLAYMAKER))
    walk_to_the_last_space(match, handler)
    space = match.board.meeple_position(handler)
    return DribbleFixture(
        game=build_game(),
        match=match,
        distance=0,
        key="dribble_burst",
        narration=(
            f"**Dribble Burst:** {label(match, handler)} is already as "
            "far forward as the field goes, so the ball stays where it "
            "is."
        ),
        follow_on_kwargs={"player_id": handler, "skill_type": "offense"},
        carrier_id=handler,
        ball_space=space,
    )


def burst_collects_a_beaten_clear() -> DribbleFixture:
    """
    Clear's cost on the other card of the rank, which is where the two
    exhaustion charges of one step land in the same message: the
    runner's own tokens first, then the defender's flat 2.
    """
    match = build_match()
    game = build_game(mode=GameMode.ADVANCED)
    handler = hand_the_ball_to(match, fielded(match, PlayerRole.MIDFIELDER))
    challenger = beaten_clear(match, game, "dribble_burst")
    return DribbleFixture(
        game=game,
        match=match,
        distance=2,
        key="dribble_burst",
        narration=(
            f"**Dribble Burst:** {label(match, handler)} bursts 2 "
            "spaces forward, past everyone in the way."
            f"\n{label(match, handler)} gains 2 exhaustion tokens "
            f"{EXHAUST * 2} (now 2 total)."
            "\n\n**Clear** was beaten -- 2 exhaustion.\n"
            f"{label(match, challenger)} gains 2 exhaustion tokens "
            f"{EXHAUST * 2} (now 2 total)."
        ),
        follow_on_kwargs={"player_id": handler, "skill_type": "offense"},
        carrier_id=handler,
        ball_space=(Zone.MIDFIELD, 2),
        exhaustion=2,
    )


DRIBBLE_CASES: tuple[DribbleCase, ...] = (
    DribbleCase("advance_one_space", advance_one_space),
    DribbleCase(
        "advance_two_spaces_as_playmaker", advance_two_spaces_as_playmaker,
    ),
    DribbleCase(
        "advance_one_space_as_playmaker", advance_one_space_as_playmaker,
    ),
    DribbleCase(
        "advance_clamped_at_the_end_of_the_field",
        advance_clamped_at_the_end_of_the_field,
    ),
    DribbleCase(
        "advance_collects_a_beaten_clear", advance_collects_a_beaten_clear,
    ),
    DribbleCase("burst_three_spaces", burst_three_spaces),
    DribbleCase("burst_as_playmaker", burst_as_playmaker),
    DribbleCase(
        "burst_tips_the_handler_over_their_line",
        burst_tips_the_handler_over_their_line,
    ),
    DribbleCase("burst_with_nowhere_to_go", burst_with_nowhere_to_go),
    DribbleCase(
        "burst_with_nowhere_to_go_as_playmaker",
        burst_with_nowhere_to_go_as_playmaker,
    ),
    DribbleCase(
        "burst_collects_a_beaten_clear", burst_collects_a_beaten_clear,
    ),
)
