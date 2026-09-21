"""
A match in each state the pending-prompt chain can answer from.

The chain that reads "what is this match waiting on?" has one branch
per prompt the game can be sitting on, and the orderings between those
branches carry real decisions -- see "Recovering a stuck game" in
docs/design/recovery.md. Moving it into the model (Phase 1 of
docs/model-discord-split.md) is a pure refactor, so the thing worth
asserting is that **not one branch changed its answer**, and that needs
a fixture standing in every one of them at once rather than the
twenty-odd scattered ones the suite already had.

So the fixtures live here, built with no `discord` in scope, and two
test modules read the same table:

- `tests/test_d12ball_prompts.py` asks the model
  (`d12ball.prompts.pending_prompt`) for the kind and the parameters.
- `tests/test_d12ball_prompt_mapping.py` asks the cog
  (`D12Ball.pending_turn_view`) for the `discord.ui.View` class and the
  line above it.

The second one is the equivalence test: it was written and run against
the old chain **before** anything moved, so a green run after the move
is the two answering the same way rather than two halves of one new
thing agreeing with each other.

**The expected `ask` is built, never spelled out**, wherever it names a
player: the roster is data the author revises (see `roster.py`), and a
fixture holding `Sizzifizik` would break on the next rename for no
reason connected to prompts. The wording around the name is the
assertion; the name inside it is not.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from d12ball.ai import build_ai_strategies
from d12ball.components import (
    CoachingOccasion,
    MatchState,
    PlayerRole,
    TeamSide,
    Zone,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.engine import RulesEngine
from d12ball.formatting import (
    contest_noun,
    format_player_with_team,
    space_label,
)
from d12ball.game import D12BallGame, Formation, GameStatus, Team
from roster import fielded

CATALOG = load_player_catalog()
RULESET = load_basic_ruleset()
MANEUVERS = load_maneuver_catalog()
ENGINE = RulesEngine(
    CATALOG, RULESET, MANEUVERS, build_ai_strategies(CATALOG, MANEUVERS),
)

GAME_ID = "g1"


@dataclass
class PromptFixture:
    """One match standing in one branch, and what it should answer."""

    game: D12BallGame
    match: MatchState
    ask: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PromptCase:
    """
    A fixture, named by the two things it should produce: the model's
    `PromptKind` (by member name, so this module needs no import of it)
    and the `discord.ui.View` class the cog maps that kind to (by class
    name, so this module needs no discord).
    """

    name: str
    kind: str
    view: str
    build: Callable[[], PromptFixture]


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
    """The player as a message names them -- team emoji, name, role."""
    return ENGINE.format_player_label(
        match, ENGINE.get_player_definition(player_id),
    )


def take_the_ball(match: MatchState) -> str:
    """Put a handler on the ball, which most branches below assume."""
    match.active_player_id = match.eligible_ball_handlers()[0]
    return match.active_player_id


def challenge(match: MatchState) -> str:
    """A maneuver under way, with a challenger picked."""
    take_the_ball(match)
    match.challenger_id = match.visiting.field_players[0]
    return match.challenger_id


# -- Before the whistle, and between the halves ------------------------


def setup_coaching() -> PromptFixture:
    match = build_match()
    match.pending_setup_stage = "coaching_home"
    return PromptFixture(
        build_game(), match, "Coaching Choice, before kickoff:",
    )


def full_time_coaching() -> PromptFixture:
    match = build_match()
    match.pending_full_time_stage = "coaching_home"
    return PromptFixture(
        build_game(), match, "Coaching Choice, before the shootout:",
    )


def halftime_extra_token() -> PromptFixture:
    match = build_match()
    match.pending_halftime_stage = "extra_token_visiting"
    return PromptFixture(
        build_game(),
        match,
        "Halftime: choose a player to lose an extra exhaustion token.",
        {"side": TeamSide.VISITING},
    )


def halftime_coaching() -> PromptFixture:
    match = build_match()
    match.pending_halftime_stage = "coaching_home"
    return PromptFixture(build_game(), match, "Halftime Coaching Choice:")


# -- The four interrupts, ahead of everything they interrupt ----------


def smooth() -> PromptFixture:
    match = build_match()
    taker = fielded(match, PlayerRole.WINGER)
    match.pending_smooth = [taker]
    return PromptFixture(
        build_game(),
        match,
        f"{label(match, taker)} can still take the ball over:",
        {"player_id": taker},
    )


def mind_pull() -> PromptFixture:
    match = build_match()
    puller = fielded(match, PlayerRole.PLAYMAKER)
    match.pending_mind_pull = [puller]
    return PromptFixture(
        build_game(),
        match,
        f"{label(match, puller)} can still reach for the ball:",
        {"player_id": puller},
    )


def injury_test() -> PromptFixture:
    match = build_match()
    hurt = fielded(match, PlayerRole.FULLBACK)
    match.pending_injury_tests = [hurt]
    return PromptFixture(
        build_game(),
        match,
        f"{label(match, hurt)} still owes an injury test:",
        {"player_id": hurt},
    )


def own_goal() -> PromptFixture:
    match = build_match()
    match.pending_own_goal = True
    return PromptFixture(
        build_game(), match, "Either player can roll for the own goal.",
    )


# -- The shootout's three states ---------------------------------------


def shootout_order() -> PromptFixture:
    match = build_match()
    match.begin_shootout()
    return PromptFixture(
        build_game(), match, "Extreme shootout — set your shooting order:",
    )


def shootout_test() -> PromptFixture:
    match = build_match()
    match.begin_shootout()
    for side in (TeamSide.HOME, TeamSide.VISITING):
        match.set_shootout_order(side, match.shootout_squad(side))
    return PromptFixture(
        build_game(),
        match,
        "Either player can roll the shootout skill test:",
    )


def shootout_pick() -> PromptFixture:
    fixture = shootout_test()
    # Round one needs no pick -- the order says who is next -- so the
    # pick prompt is only owed once the order has been played out.
    for _ in range(6):
        fixture.match.finish_shootout_test()
    fixture.ask = "Extreme shootout — choose who shoots next:"
    return fixture


# -- The time out ------------------------------------------------------


def _ceded_time_out(match: MatchState) -> None:
    take_the_ball(match)
    match.ball.possession = TeamSide.HOME
    match.ball.zone = Zone.MIDFIELD
    match.ball.space_index = 0
    match.call_time_out()


def time_out_window() -> PromptFixture:
    match = build_match()
    _ceded_time_out(match)
    match.open_coaching_window(TeamSide.HOME, CoachingOccasion.TIME_OUT)
    return PromptFixture(
        build_game(), match, "Coaching Choice, on the time out:",
    )


def time_out_tail() -> PromptFixture:
    # Both windows closed: what is left is the tail, and that was the
    # bot's own next step, so there is no button to restore.
    match = build_match()
    _ceded_time_out(match)
    return PromptFixture(build_game(), match, "Settle the time out:")


# -- The turn itself ---------------------------------------------------


def kickoff() -> PromptFixture:
    return PromptFixture(
        build_game(), build_match(), "Choose who takes the ball:",
    )


def coaching_offer() -> PromptFixture:
    match = build_match()
    take_the_ball(match)
    match.open_coaching_window(TeamSide.HOME, CoachingOccasion.NEW_PLAY)
    return PromptFixture(
        build_game(), match, "Coaching Choice — coach, or pass?",
    )


def coaching_hub() -> PromptFixture:
    fixture = coaching_offer()
    fixture.match.declare_coaching()
    fixture.ask = "Coaching Choice:"
    return fixture


def run_back_space() -> PromptFixture:
    match = build_match()
    take_the_ball(match)
    stray = match.home.zones[Zone.MIDFIELD][0]
    match.board.remove_meeple(stray)
    match.board.place_meeple(stray, Zone.VISITORS_GOAL, 0)
    match.pending_run_back = True
    game = build_game()
    _, candidates = ENGINE.next_run_back_step(game, match)
    return PromptFixture(
        game,
        match,
        "Choose where the next player runs back to:",
        {"player_id": candidates[0]},
    )


def run_back_player() -> PromptFixture:
    # Which of two on one space runs back is the coach's, and it lives
    # on the view rather than in the save -- so a restart has to put
    # the question back rather than the answer.
    match = build_match()
    take_the_ball(match)
    for player_id in match.home.zones[Zone.MIDFIELD]:
        match.board.remove_meeple(player_id)
        match.board.place_meeple(player_id, Zone.MIDFIELD, 0)
    match.pending_run_back = True
    game = build_game()
    _, candidates = ENGINE.next_run_back_step(game, match)
    return PromptFixture(
        game,
        match,
        "Choose which of your doubled-up players runs back:",
        {"player_ids": candidates},
    )


def run_back_finished() -> PromptFixture:
    # Nothing left to place, which is the bot's own next step rather
    # than a coach's -- the first of the three PlayerActionView
    # fallbacks, and it keeps the run back's own ask.
    match = build_match()
    take_the_ball(match)
    match.pending_run_back = True
    return PromptFixture(
        build_game(), match, "Choose where the next player runs back to:",
    )


def ball_recovery() -> PromptFixture:
    match = build_match()
    take_the_ball(match)
    match.pending_ball_recovery = True
    return PromptFixture(
        build_game(),
        match,
        "Send the nearest player either side of the ball to pick it "
        f"up at {space_label(match.ball.zone, match.ball.space_index)}:",
    )


def loose_ball_pick() -> PromptFixture:
    match = build_match()
    take_the_ball(match)
    match.begin_loose_ball(1)
    return PromptFixture(
        build_game(),
        match,
        f"Choose who goes after the {contest_noun(match)}:",
        {
            "side": ENGINE.loose_ball_prompt_side(match),
            "skill_type": ENGINE.loose_ball_side_on_the_clock(match),
        },
    )


def loose_ball_skill_test() -> PromptFixture:
    match = build_match()
    take_the_ball(match)
    match.begin_loose_ball(1)
    match.loose_ball_offense_player = fielded(match, PlayerRole.STRIKER)
    match.loose_ball_defense_player = fielded(
        match, PlayerRole.FULLBACK, TeamSide.VISITING,
    )
    return PromptFixture(
        build_game(),
        match,
        f"Either player can roll for the {contest_noun(match)}:",
    )


def loose_ball_settled() -> PromptFixture:
    # Both sides have answered and neither sent anybody, so there is
    # nothing left to ask -- the second PlayerActionView fallback.
    match = build_match()
    take_the_ball(match)
    match.begin_loose_ball(1)
    match.decline_loose_ball(match.ball.possession)
    match.decline_loose_ball(match.defending_side())
    return PromptFixture(
        build_game(),
        match,
        f"Choose who goes after the {contest_noun(match)}:",
    )


def score_attempt() -> PromptFixture:
    match = build_match()
    take_the_ball(match)
    match.pending_action = "shoot"
    return PromptFixture(
        build_game(), match, "Either player can roll for the score attempt.",
    )


def set_up_attempt() -> PromptFixture:
    """
    A set-up offered and not yet answered.

    **A branch only since Phase 6**, and a restart here used to come
    back to the maneuver's first-stage distance choice instead: the
    two numbers the offer carries were on the view and nowhere else.
    `MatchState.pending_scoring_opportunity` is where they live now.
    """
    match = build_match()
    shooter = take_the_ball(match)
    match.pending_scoring_opportunity = {
        "kind": "attempt",
        "shooter_id": shooter,
        "distance_moved": 2,
        "contest_on_decline": True,
    }
    return PromptFixture(
        build_game(),
        match,
        f"{label(match, shooter)} can attempt the scoring "
        "opportunity, or let it go:",
        {
            "player_id": shooter,
            "distance_moved": 2,
            "contest_on_decline": True,
        },
    )


def shooter_choice() -> PromptFixture:
    """
    Two players standing on an overshot ball, and the coach picking
    which of them shoots.

    The candidates are **read back off the board** rather than saved,
    so the fixture stands them on the ball's space and lets
    `scoring_opportunity_prompt` find them -- which is the half of
    this prompt that did not need a new field.
    """
    match = build_match()
    game = build_game()
    candidates = [
        fielded(match, PlayerRole.STRIKER),
        fielded(match, PlayerRole.WINGER),
    ]
    for player_id in candidates:
        match.board.remove_meeple(player_id)
        match.board.place_meeple(
            player_id, match.ball.zone, match.ball.space_index,
        )
    match.pending_scoring_opportunity = {"kind": "shooter"}
    # Whoever else the standard deal already put on that space counts
    # too -- the candidates are the position and not a list this
    # fixture owns, which is the point of the branch.
    candidates = ENGINE.scoring_opportunity_candidates(
        match, match.ball.possession,
    )
    mention = format_player_with_team(
        game,
        ENGINE.possession_player_number(game, match),
        ENGINE.team_emojis,
        mention=True,
    )
    return PromptFixture(
        game,
        match,
        f"{mention}, choose who takes the shot:",
        {"player_ids": candidates},
    )


def maneuver_challenge() -> PromptFixture:
    match = build_match()
    take_the_ball(match)
    match.pending_action = "maneuver"
    return PromptFixture(
        build_game(), match, "Choose who challenges the maneuver:",
    )


def maneuver_picks() -> PromptFixture:
    match = build_match()
    challenge(match)
    return PromptFixture(build_game(), match, "Choose your maneuver:")


def skill_test() -> PromptFixture:
    # A tie on the cards, so no winner is settled and a roll is owed.
    match = build_match()
    challenge(match)
    match.offense_maneuver = "low_pass"
    match.defense_maneuver = "deflect"
    return PromptFixture(build_game(), match, "Either player can roll:")


# -- The effect a settled maneuver owes --------------------------------
#
# Every one of these is "Resolve the maneuver:"; what differs is which
# choice is put under it, and that is read off the winner (and, first,
# off a continuation the winner would talk over).

RESOLVE = "Resolve the maneuver:"


def _settled(offense: str, defense: str) -> PromptFixture:
    match = build_match()
    challenge(match)
    match.offense_maneuver = offense
    match.defense_maneuver = defense
    return PromptFixture(build_game(), match, RESOLVE)


def low_pass_choice() -> PromptFixture:
    fixture = _settled("low_pass", "pressure")
    fixture.params = {"maneuver_key": "low_pass", "free": False}
    return fixture


def skilled_pass_choice() -> PromptFixture:
    fixture = _settled("skilled_pass", "pressure")
    fixture.params = {"maneuver_key": "skilled_pass", "free": False}
    return fixture


def high_pass_choice() -> PromptFixture:
    return _settled("high_pass", "steal")


def setup_pass_speed_choice() -> PromptFixture:
    fixture = _settled("setup_pass", "steal")
    fixture.params = {
        "player_id": fixture.match.active_player_id,
        "skill_type": "offense",
        "maneuver_key": "setup_pass",
    }
    return fixture


def dribble_advance_choice() -> PromptFixture:
    # A Playmaker's Dribble Advance asks a distance first; the standard
    # deal's first eligible handler is the Playmaker.
    fixture = _settled("dribble_advance", "deflect")
    assert ENGINE.get_player_definition(
        fixture.match.active_player_id,
    ).role == PlayerRole.PLAYMAKER
    return fixture


def dribble_advance_speed_choice() -> PromptFixture:
    # Anybody else's goes straight to the speed choice.
    match = build_match()
    match.active_player_id = fielded(match, PlayerRole.STRIKER)
    match.challenger_id = match.visiting.field_players[0]
    match.offense_maneuver = "dribble_advance"
    match.defense_maneuver = "deflect"
    return PromptFixture(
        build_game(),
        match,
        RESOLVE,
        {
            "player_id": match.active_player_id,
            "skill_type": "offense",
            "maneuver_key": "dribble_advance",
        },
    )


def dribble_burst_choice() -> PromptFixture:
    return _settled("dribble_burst", "deflect")


def dribble_burst_with_nothing_to_ask() -> PromptFixture:
    # From the last space of the field there is no distance to ask,
    # and a burst asks nothing else -- the ball is left at 12 -- so it
    # is a choiceless effect there, and restores to the turn prompt
    # like a Deflect.
    fixture = _settled("dribble_burst", "deflect")
    match = fixture.match
    last = match.board.layout.zone_spaces[Zone.VISITORS_GOAL] - 1
    match.board.remove_meeple(match.active_player_id)
    match.board.place_meeple(match.active_player_id, Zone.VISITORS_GOAL, last)
    match.ball.zone = Zone.VISITORS_GOAL
    match.ball.space_index = last
    return fixture


def steal_speed_choice() -> PromptFixture:
    fixture = _settled("low_pass", "steal")
    fixture.params = {
        "player_id": fixture.match.challenger_id,
        "skill_type": "defense",
        "maneuver_key": "steal",
    }
    return fixture


def intercept_speed_choice() -> PromptFixture:
    fixture = _settled("low_pass", "intercept")
    fixture.params = {
        "player_id": fixture.match.challenger_id,
        "skill_type": "defense",
        "maneuver_key": "intercept",
    }
    return fixture


def setup_pass_shot_choice() -> PromptFixture:
    # The continuation is read ahead of the winner: the speed choice
    # has already been answered by the time one is set, and reading the
    # winner would put it back up.
    fixture = _settled("setup_pass", "steal")
    fixture.match.pending_effect_continuation = {"kind": "setup_pass_shot"}
    return fixture


def free_low_pass_choice() -> PromptFixture:
    fixture = _settled("setup_pass", "steal")
    fixture.match.pending_effect_continuation = {"kind": "free_low_pass"}
    fixture.params = {"maneuver_key": "low_pass", "free": True}
    return fixture


def effect_with_no_choice() -> PromptFixture:
    # Deflect and Pressure resolve with nothing to ask, so a crash
    # window that persisted one falls back to the turn prompt -- the
    # third PlayerActionView fallback.
    return _settled("high_pass", "deflect")


def plain_turn() -> PromptFixture:
    match = build_match()
    take_the_ball(match)
    return PromptFixture(build_game(), match, "Choose an action:")


CASES: tuple[PromptCase, ...] = (
    PromptCase("setup coaching", "COACHING_HUB", "CoachingHubView",
               setup_coaching),
    PromptCase("full-time coaching", "COACHING_HUB", "CoachingHubView",
               full_time_coaching),
    PromptCase("halftime extra token", "HALFTIME_EXTRA_TOKEN",
               "HalftimeExtraTokenView", halftime_extra_token),
    PromptCase("halftime coaching", "COACHING_HUB", "CoachingHubView",
               halftime_coaching),
    PromptCase("smooth", "SMOOTH", "SmoothView", smooth),
    PromptCase("mind pull", "MIND_PULL", "MindPullView", mind_pull),
    PromptCase("injury test", "INJURY_TEST", "InjuryTestView", injury_test),
    PromptCase("own goal", "OWN_GOAL_ROLL", "OwnGoalRollView", own_goal),
    PromptCase("shootout order", "SHOOTOUT_ORDER", "ShootoutOrderPromptView",
               shootout_order),
    PromptCase("shootout pick", "SHOOTOUT_PICK", "ShootoutPickPromptView",
               shootout_pick),
    PromptCase("shootout test", "SHOOTOUT_TEST", "ShootoutTestView",
               shootout_test),
    PromptCase("time-out window", "COACHING_HUB", "CoachingHubView",
               time_out_window),
    PromptCase("time-out tail", "PLAYER_ACTION", "PlayerActionView",
               time_out_tail),
    PromptCase("kickoff", "BALL_HANDLER_SELECTION",
               "BallHandlerSelectionView", kickoff),
    PromptCase("coaching offer", "COACHING_OFFER", "CoachingOfferView",
               coaching_offer),
    PromptCase("coaching hub", "COACHING_HUB", "CoachingHubView",
               coaching_hub),
    PromptCase("run back, where", "RUN_BACK_SPACE", "RunBackChoiceView",
               run_back_space),
    PromptCase("run back, who", "RUN_BACK_PLAYER", "RunBackPlayerChoiceView",
               run_back_player),
    PromptCase("run back, nothing left", "PLAYER_ACTION", "PlayerActionView",
               run_back_finished),
    PromptCase("ball recovery", "BALL_RECOVERY", "BallRecoveryView",
               ball_recovery),
    PromptCase("loose ball pick", "LOOSE_BALL_PICK", "LooseBallChoiceView",
               loose_ball_pick),
    PromptCase("loose ball roll", "LOOSE_BALL_SKILL_TEST",
               "LooseBallSkillTestView", loose_ball_skill_test),
    PromptCase("loose ball settled", "PLAYER_ACTION", "PlayerActionView",
               loose_ball_settled),
    PromptCase("set-up attempt", "SET_UP_ATTEMPT", "SetUpAttemptChoiceView",
               set_up_attempt),
    PromptCase("shooter choice", "SHOOTER_CHOICE", "ShooterChoiceView",
               shooter_choice),
    PromptCase("score attempt", "SCORE_ATTEMPT", "ScoreAttemptView",
               score_attempt),
    PromptCase("maneuver challenge", "MANEUVER_CHALLENGE",
               "ManeuverChallengeView", maneuver_challenge),
    PromptCase("maneuver picks", "MANEUVER_ACTION",
               "ManeuverActionPromptView", maneuver_picks),
    PromptCase("skill test", "SKILL_TEST", "SkillTestView", skill_test),
    PromptCase("low pass", "LOW_PASS_CHOICE", "LowPassChoiceView",
               low_pass_choice),
    PromptCase("skilled pass", "LOW_PASS_CHOICE", "LowPassChoiceView",
               skilled_pass_choice),
    PromptCase("free low pass", "LOW_PASS_CHOICE", "LowPassChoiceView",
               free_low_pass_choice),
    PromptCase("high pass", "HIGH_PASS_CHOICE", "HighPassChoiceView",
               high_pass_choice),
    PromptCase("setup pass shot", "SETUP_PASS_CHOICE", "SetupPassChoiceView",
               setup_pass_shot_choice),
    PromptCase("setup pass speed", "SPEED_DELTA_CHOICE",
               "SpeedDeltaChoiceView", setup_pass_speed_choice),
    PromptCase("dribble advance", "DRIBBLE_ADVANCE_CHOICE",
               "DribbleAdvanceChoiceView", dribble_advance_choice),
    PromptCase("dribble advance speed", "SPEED_DELTA_CHOICE",
               "SpeedDeltaChoiceView", dribble_advance_speed_choice),
    PromptCase("dribble burst", "DRIBBLE_BURST_CHOICE",
               "DribbleBurstChoiceView", dribble_burst_choice),
    PromptCase("dribble burst, nothing to ask", "PLAYER_ACTION",
               "PlayerActionView", dribble_burst_with_nothing_to_ask),
    PromptCase("steal", "SPEED_DELTA_CHOICE", "SpeedDeltaChoiceView",
               steal_speed_choice),
    PromptCase("intercept", "SPEED_DELTA_CHOICE", "SpeedDeltaChoiceView",
               intercept_speed_choice),
    PromptCase("effect with no choice", "PLAYER_ACTION", "PlayerActionView",
               effect_with_no_choice),
    PromptCase("plain turn", "PLAYER_ACTION", "PlayerActionView", plain_turn),
)
