"""
A match in each state the pending-prompt chain can answer from.

The chain that reads "what is this match waiting on?" has one branch
per prompt the game can be sitting on, and the orderings between those
branches carry real decisions -- see "Recovering a stuck game" in
docs/design/recovery.md. Moving it into the model (Phase 1 of
docs/design/model-discord-split.md) is a pure refactor, so the thing worth
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

**A case is asked or owed.** Since step 5 of docs/architecture-migration.md
the chain answers a `FollowOn` for a position nobody is asked anything
on -- the bot owes the next step -- and those cases name the
`FollowOnStep` in `owed` and nothing in `kind` or `view`: there is no
prompt to restore and no view to map. `tests/test_d12ball_game_service_resume.py`
drives every owed case through `GameService.resume`.

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
    SPECIES_TELEKINETIC,
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
from d12ball.game import D12BallGame, Formation, GameMode, GameStatus, Team
from d12ball import tokens, tutorial
from d12ball.prompts import maneuver_action_ask, speed_choice_ask
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
    name, so this module needs no discord) -- or, for a position the
    bot owes a step on, the `FollowOnStep` (by member name) and neither
    of the other two.
    """

    name: str
    kind: str
    view: str
    build: Callable[[], PromptFixture]
    owed: str = ""
    #: The question is the AI's: the kind and the ask are the model's
    #: as for any prompt, but no view is built for it -- the service
    #: answers it (`GameService.run`, step 7 of
    #: docs/architecture-migration.md).
    ai: bool = False

    @property
    def asked(self) -> bool:
        """Whether this case is a question for somebody."""
        return bool(self.kind)


def owed_case(name: str, step: str, build: Callable[[], PromptFixture]):
    """A case the bot owes a step on: no kind, no view."""
    return PromptCase(name, "", "", build, owed=step)


def ai_case(name: str, kind: str, build: Callable[[], PromptFixture]):
    """A case the AI is asked on: a kind and an ask, and no view."""
    return PromptCase(name, kind, "", build, ai=True)


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
        mode=GameMode.TRAINING,
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
    # The stage and its window both: the stage alone is a position the
    # bot owes the next step on (`setup_stage_with_no_window`).
    match = build_match()
    match.pending_setup_stage = "coaching_home"
    match.open_coaching_window(TeamSide.HOME, CoachingOccasion.SETUP)
    return PromptFixture(
        build_game(), match, "Coaching Choice, before kickoff:",
        {"side": TeamSide.HOME},
    )


def setup_stage_with_no_window() -> PromptFixture:
    # The process died between setting the stage and opening the
    # window: nothing to re-post, and the sequence is re-driven.
    match = build_match()
    match.pending_setup_stage = "coaching_home"
    return PromptFixture(build_game(), match, "")


def full_time_coaching() -> PromptFixture:
    match = build_match()
    match.pending_full_time_stage = "coaching_home"
    match.open_coaching_window(TeamSide.HOME, CoachingOccasion.FULL_TIME)
    return PromptFixture(
        build_game(), match, "Coaching Choice, before the shootout:",
        {"side": TeamSide.HOME},
    )


def full_time_stage_with_no_window() -> PromptFixture:
    match = build_match()
    match.pending_full_time_stage = "coaching_home"
    return PromptFixture(build_game(), match, "")


def halftime_extra_token() -> PromptFixture:
    match = build_match()
    match.pending_halftime_stage = "extra_token_visiting"
    return PromptFixture(
        build_game(),
        match,
        "Halftime: choose a player to clear an extra exhaustion token.",
        {"side": TeamSide.VISITING},
    )


def halftime_extra_token_for_the_ai() -> PromptFixture:
    # An AI side is asked the same question a coach is, and the
    # service answers it.
    match = build_match()
    match.pending_halftime_stage = "extra_token_visiting"
    return PromptFixture(
        build_game(player_2_id=None),
        match,
        "Halftime: choose a player to clear an extra exhaustion token.",
        {"side": TeamSide.VISITING},
    )


def halftime_coaching() -> PromptFixture:
    match = build_match()
    match.pending_halftime_stage = "coaching_home"
    match.open_coaching_window(TeamSide.HOME, CoachingOccasion.HALFTIME)
    return PromptFixture(
        build_game(), match, "Halftime Coaching Choice:",
        {"side": TeamSide.HOME},
    )


def halftime_stage_with_no_window() -> PromptFixture:
    match = build_match()
    match.pending_halftime_stage = "coaching_home"
    return PromptFixture(build_game(), match, "")


# -- The four interrupts, ahead of everything they interrupt ----------


def smooth() -> PromptFixture:
    match = build_match()
    taker = fielded(match, PlayerRole.WINGER)
    # Somebody is holding it: the decline names them, so a fixture
    # with nobody on the ball would stand in the branch that has
    # nothing to name (`RulesEngine.smooth_keeper`) rather than the
    # ordinary one.
    match.set_ball_carrier(fielded(match, PlayerRole.PLAYMAKER))
    match.pending_smooth = [taker]
    return PromptFixture(
        build_game(),
        match,
        f"{tokens.species(SPECIES_TELEKINETIC)} **Smooth** — "
        f"{label(match, taker)} can still take the ball to become "
        "the ball handler:",
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


def fly() -> PromptFixture:
    # Zenith's Fly (Law 21), at the head of a steal's run back: the
    # queue and the run back's own arguments, which the answer resumes.
    match = build_match()
    take_the_ball(match)
    flier = fielded(match, PlayerRole.WINGER)
    match.pending_fly = [flier]
    match.pending_fly_resume = {
        "distance_moved": 1,
        "turnover_occurred": True,
        "speed_choice_after": False,
        "speed_reset": True,
    }
    return PromptFixture(
        build_game(),
        match,
        f"{label(match, flier)} may **Fly** before the run back: to any "
        "space on the field, at a token a space, and then they do not "
        "run back.",
        {"player_id": flier},
    )


def join_the_ball() -> PromptFixture:
    # Glompex (Law 21): a challenger in place, nobody's cards chosen.
    match = build_match()
    challenge(match)
    joiner = next(
        player_id for player_id in match.home.field_players
        if player_id != match.active_player_id
    )
    match.pending_join = [joiner]
    game = build_game()
    noun, _ = ENGINE.token_word_and_mark(game, joiner)
    return PromptFixture(
        game,
        match,
        f"{label(match, joiner)} is next to the ball, and may take 1 "
        f"{noun} to step onto its space and Merge before the cards are "
        "chosen:",
        {"player_id": joiner},
    )


def force_test() -> PromptFixture:
    # Scorchit (Law 21): the cards revealed and gone against the
    # challenger, who is asked whether to force the test.
    match = build_match()
    challenger = challenge(match)
    match.offense_maneuver = "low_pass"
    match.defense_maneuver = "pressure"
    match.pending_force_test = challenger
    game = build_game()
    noun, _ = ENGINE.token_word_and_mark(game, challenger)
    return PromptFixture(
        game,
        match,
        f"{label(match, challenger)}'s card lost, but they may force a "
        f"skill test: 2 {noun} to them and none to their opponent.",
        {"player_id": challenger},
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
        build_game(),
        match,
        "### Extreme shootout\n{coach:1} and {coach:2}: set the order your six "
        "players shoot in. Nobody else sees it.",
    )


def shootout_order_for_the_ai() -> PromptFixture:
    # The coach has set theirs; the AI's is the same question, one
    # name at a time, answered by the service -- and addressed to the
    # AI by its coach token, as every question is (it read "Purple
    # (Visiting)" until step 9, the side standing in for the account
    # the AI has not got).
    match = build_match()
    match.begin_shootout()
    match.set_shootout_order(
        TeamSide.HOME, list(match.shootout_squad(TeamSide.HOME)),
    )
    return PromptFixture(
        build_game(player_2_id=None),
        match,
        "### Extreme shootout\n{coach:2}: set the order your six "
        "players shoot in. Nobody else sees it.",
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
    fixture.ask = (
        f"{ENGINE.shootout_heading(fixture.match)}\n{{coach:1}} and {{coach:2}}: "
        "choose who goes out next, from the players who have not shot "
        "yet this round. Nobody else sees it until the reveal."
    )
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
        {"side": TeamSide.HOME},
    )


def time_out_tail() -> PromptFixture:
    # Both windows closed: what is left is the tail, and that is the
    # bot's own next step, so there is no button to restore.
    match = build_match()
    _ceded_time_out(match)
    return PromptFixture(build_game(), match, "")


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
        {"side": TeamSide.HOME},
    )


def ai_coaching_window() -> PromptFixture:
    # An AI side's window is the offer a coach gets, answered by the
    # service one hub action at a time.
    match = build_match()
    take_the_ball(match)
    match.open_coaching_window(TeamSide.VISITING, CoachingOccasion.NEW_PLAY)
    return PromptFixture(
        build_game(player_2_id=None),
        match,
        "Coaching Choice — coach, or pass?",
        {"side": TeamSide.VISITING},
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
    # than a coach's: the cascade's, to finish.
    match = build_match()
    take_the_ball(match)
    match.pending_run_back = True
    return PromptFixture(build_game(), match, "")


def _nobody_on_the_ball(match: MatchState) -> None:
    """Move whoever is standing on the ball's space off it."""
    for player_id in list(match.board.spaces[match.ball.zone][
        match.ball.space_index
    ]):
        match.board.place_meeple(player_id, Zone.HOME_GOAL, 0)


def ball_recovery() -> PromptFixture:
    match = build_match()
    _nobody_on_the_ball(match)
    match.pending_ball_recovery = True
    return PromptFixture(
        build_game(),
        match,
        "Send the nearest player either side of the ball to pick it "
        f"up at {space_label(match.ball.zone, match.ball.space_index)}:",
    )


def ball_recovery_for_the_ai() -> PromptFixture:
    # An AI side is asked whom to send, like a coach. The AI is
    # always player 2, which is the visiting side here.
    match = build_match()
    match.ball.possession = TeamSide.VISITING
    _nobody_on_the_ball(match)
    match.pending_ball_recovery = True
    return PromptFixture(
        build_game(player_2_id=None),
        match,
        "Send the nearest player either side of the ball to pick it "
        f"up at {space_label(match.ball.zone, match.ball.space_index)}:",
    )


def ball_recovery_with_somebody_on_the_ball() -> PromptFixture:
    # The reset put one of theirs on it already: nobody is placed, and
    # the step says so by moving on.
    match = build_match()
    take_the_ball(match)
    match.pending_ball_recovery = True
    return PromptFixture(build_game(), match, "")


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
    # nothing left to ask: settling it is the step's.
    match = build_match()
    take_the_ball(match)
    match.begin_loose_ball(1)
    match.decline_loose_ball(match.ball.possession)
    match.decline_loose_ball(match.defending_side())
    return PromptFixture(build_game(), match, "")


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
    # The live wording, not a bare "Choose your maneuver:" -- the
    # tutorial holds this prompt behind a note and shows what the
    # match is waiting on after the click, so the restored ask is the
    # live one (see `maneuver_action_ask`).
    match = build_match()
    challenge(match)
    game = build_game()
    return PromptFixture(
        game, match, maneuver_action_ask(ENGINE, game, match),
    )


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


def _speed(fixture: PromptFixture, player_id: str, skill_type: str) -> None:
    """
    The speed choice's live wording, which is also its restored one --
    the tutorial holds it behind a note, for `maneuver_picks`'s reason.
    """
    fixture.ask = speed_choice_ask(
        ENGINE, fixture.game, fixture.match, player_id, skill_type,
    )


def setup_pass_speed_choice() -> PromptFixture:
    fixture = _settled("setup_pass", "steal")
    fixture.params = {
        "player_id": fixture.match.active_player_id,
        "skill_type": "offense",
        "maneuver_key": "setup_pass",
    }
    _speed(fixture, fixture.match.active_player_id, "offense")
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
    fixture = PromptFixture(
        build_game(),
        match,
        RESOLVE,
        {
            "player_id": match.active_player_id,
            "skill_type": "offense",
            "maneuver_key": "dribble_advance",
        },
    )
    _speed(fixture, match.active_player_id, "offense")
    return fixture


def dribble_advance_speed_after_the_distance() -> PromptFixture:
    # A Playmaker's advance, *after* the distance has been taken: the
    # handler is recorded as carrying, which is what
    # `dribble_advance_step` sets and `select_ball_handler` clears --
    # so the speed choice is owed, not the distance. The other reading
    # was the crash-window guess `effect_choice_prompt` used to make.
    fixture = _settled("dribble_advance", "deflect")
    fixture.match.set_ball_carrier(fixture.match.active_player_id)
    fixture.params = {
        "player_id": fixture.match.active_player_id,
        "skill_type": "offense",
        "maneuver_key": "dribble_advance",
    }
    _speed(fixture, fixture.match.active_player_id, "offense")
    return fixture


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
    fixture.ask = ""
    return fixture


def steal_speed_choice() -> PromptFixture:
    fixture = _settled("low_pass", "steal")
    fixture.params = {
        "player_id": fixture.match.challenger_id,
        "skill_type": "defense",
        "maneuver_key": "steal",
    }
    _speed(fixture, fixture.match.challenger_id, "defense")
    return fixture


def intercept_speed_choice() -> PromptFixture:
    fixture = _settled("low_pass", "intercept")
    fixture.params = {
        "player_id": fixture.match.challenger_id,
        "skill_type": "defense",
        "maneuver_key": "intercept",
    }
    _speed(fixture, fixture.match.challenger_id, "defense")
    return fixture


def skill_test_settled_a_tie() -> PromptFixture:
    # A tie the dice settled: the winner is on the match
    # (`skill_test_winner`), so the effect's own prompt is owed rather
    # than the roll -- which is what a restart inside that effect used
    # to re-offer.
    match = build_match()
    challenge(match)
    match.offense_maneuver = "low_pass"
    match.defense_maneuver = "deflect"
    match.skill_test_winner = "low_pass"
    fixture = PromptFixture(build_game(), match, RESOLVE)
    fixture.params = {"maneuver_key": "low_pass", "free": False}
    return fixture


def setup_pass_push_back() -> PromptFixture:
    # Setup Pass beaten by a Deflect, the deflection played and the
    # ball not yet loose: the coach who won is owed the push back.
    fixture = _settled("setup_pass", "deflect")
    return fixture


def tutorial_note_up() -> PromptFixture:
    # A note held behind Continue outranks everything: the position
    # underneath is exactly what it was before the note went up.
    match = build_match()
    take_the_ball(match)
    game = build_game(tutorial=True, tutorial_step=1)
    game.tutorial_gate = {"note": tutorial.NOTE_LESSON, "then": None}
    return PromptFixture(game, match, tutorial.gate_text(game))


def game_over() -> PromptFixture:
    match = build_match()
    take_the_ball(match)
    game = build_game()
    game.status = GameStatus.IN_PROGRESS
    game.finish_game()
    return PromptFixture(game, match, "")


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
    # window that persisted one owes the effect itself.
    fixture = _settled("high_pass", "deflect")
    fixture.ask = ""
    return fixture


def plain_turn() -> PromptFixture:
    match = build_match()
    take_the_ball(match)
    return PromptFixture(build_game(), match, "Choose an action:")


CASES: tuple[PromptCase, ...] = (
    PromptCase("setup coaching", "COACHING_HUB", "CoachingHubView",
               setup_coaching),
    owed_case("setup stage, no window", "ADVANCE_SETUP_STAGE",
              setup_stage_with_no_window),
    PromptCase("full-time coaching", "COACHING_HUB", "CoachingHubView",
               full_time_coaching),
    owed_case("full-time stage, no window", "ADVANCE_FULL_TIME_STAGE",
              full_time_stage_with_no_window),
    PromptCase("halftime extra token", "HALFTIME_EXTRA_TOKEN",
               "HalftimeExtraTokenView", halftime_extra_token),
    ai_case("halftime extra token, the AI's", "HALFTIME_EXTRA_TOKEN",
            halftime_extra_token_for_the_ai),
    PromptCase("halftime coaching", "COACHING_HUB", "CoachingHubView",
               halftime_coaching),
    owed_case("halftime stage, no window", "ADVANCE_HALFTIME_STAGE",
              halftime_stage_with_no_window),
    PromptCase("smooth", "SMOOTH", "SmoothView", smooth),
    PromptCase("mind pull", "MIND_PULL", "MindPullView", mind_pull),
    PromptCase("fly", "FLY", "FlyView", fly),
    PromptCase("force test", "FORCE_TEST", "ForceTestView", force_test),
    PromptCase("join the ball", "JOIN_THE_BALL", "JoinTheBallView",
               join_the_ball),
    PromptCase("injury test", "INJURY_TEST", "InjuryTestView", injury_test),
    PromptCase("own goal", "OWN_GOAL_ROLL", "OwnGoalRollView", own_goal),
    PromptCase("shootout order", "SHOOTOUT_ORDER", "ShootoutOrderPromptView",
               shootout_order),
    ai_case("shootout order, the AI's", "SHOOTOUT_ORDER",
            shootout_order_for_the_ai),
    PromptCase("shootout pick", "SHOOTOUT_PICK", "ShootoutPickPromptView",
               shootout_pick),
    PromptCase("shootout test", "SHOOTOUT_TEST", "ShootoutTestView",
               shootout_test),
    PromptCase("time-out window", "COACHING_HUB", "CoachingHubView",
               time_out_window),
    owed_case("time-out tail", "FINISH_TIME_OUT", time_out_tail),
    PromptCase("kickoff", "BALL_HANDLER_SELECTION",
               "BallHandlerSelectionView", kickoff),
    PromptCase("coaching offer", "COACHING_OFFER", "CoachingOfferView",
               coaching_offer),
    PromptCase("coaching hub", "COACHING_HUB", "CoachingHubView",
               coaching_hub),
    ai_case("the AI's window", "COACHING_OFFER", ai_coaching_window),
    PromptCase("run back, where", "RUN_BACK_SPACE", "RunBackChoiceView",
               run_back_space),
    PromptCase("run back, who", "RUN_BACK_PLAYER", "RunBackPlayerChoiceView",
               run_back_player),
    owed_case("run back, nothing left", "CONTINUE_RUN_BACK",
              run_back_finished),
    PromptCase("ball recovery", "BALL_RECOVERY", "BallRecoveryView",
               ball_recovery),
    ai_case("ball recovery, the AI's", "BALL_RECOVERY",
            ball_recovery_for_the_ai),
    owed_case("ball recovery, somebody on it", "BEGIN_BALL_RECOVERY",
              ball_recovery_with_somebody_on_the_ball),
    PromptCase("loose ball pick", "LOOSE_BALL_PICK", "LooseBallChoiceView",
               loose_ball_pick),
    PromptCase("loose ball roll", "LOOSE_BALL_SKILL_TEST",
               "LooseBallSkillTestView", loose_ball_skill_test),
    owed_case("loose ball settled", "RESOLVE_LOOSE_BALL",
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
    PromptCase("dribble advance speed, after the distance",
               "SPEED_DELTA_CHOICE", "SpeedDeltaChoiceView",
               dribble_advance_speed_after_the_distance),
    PromptCase("dribble burst", "DRIBBLE_BURST_CHOICE",
               "DribbleBurstChoiceView", dribble_burst_choice),
    owed_case("dribble burst, nothing to ask", "BEGIN_EFFECT_RESOLUTION",
              dribble_burst_with_nothing_to_ask),
    PromptCase("steal", "SPEED_DELTA_CHOICE", "SpeedDeltaChoiceView",
               steal_speed_choice),
    PromptCase("intercept", "SPEED_DELTA_CHOICE", "SpeedDeltaChoiceView",
               intercept_speed_choice),
    owed_case("effect with no choice", "BEGIN_EFFECT_RESOLUTION",
              effect_with_no_choice),
    PromptCase("skill test settled a tie", "LOW_PASS_CHOICE",
               "LowPassChoiceView", skill_test_settled_a_tie),
    PromptCase("setup pass push back", "SETUP_PASS_PUSH_BACK",
               "SetupPassPushBackView", setup_pass_push_back),
    PromptCase("tutorial note up", "TUTORIAL_CONTINUE",
               "TutorialContinueView", tutorial_note_up),
    PromptCase("game over", "GAME_OVER", "RematchView", game_over),
    PromptCase("plain turn", "PLAYER_ACTION", "PlayerActionView", plain_turn),
)
