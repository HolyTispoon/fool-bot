"""
The cog wrappers the tests drive a step through, kept here and nowhere
else.

Every function in this module was a method on `D12Ball` until the
migration to ARCHITECTURE.md: a three-line wrapper that called one
flow function, or named one `FollowOnStep`, and dispatched. The bot
stopped calling them when every click started going through the
driver (Phase 6 of docs/design/model-discord-split.md), and
ARCHITECTURE.md's "What to remove" names them -- so they live with
their only callers now, as free functions over the cog, with `self`
spelled `cog`. A test that used to write `begin_run_back(cog, ...)`
writes `begin_run_back(cog, ...)`.

They are test plumbing, not an API: the way into a step from the
bot's own code is `GameService`, and a new test should prefer
`run_step` and `dispatch` below, which are the two shapes every one
of these reduces to.
"""

from __future__ import annotations

from typing import Optional  # noqa: F401

import discord  # noqa: F401

from d12ball.components import MatchState, TeamSide  # noqa: F401
from d12ball.flow import FollowOn, FollowOnStep, StepResult  # noqa: F401
from d12ball.game import D12BallGame  # noqa: F401
from flow_stubs import driver_reaches_cog_stubs
import discord  # noqa: F401
from d12ball import (  # noqa: F401
    tutorial,
)
from d12ball.components import (  # noqa: F401
    CoachingOccasion,
    MatchState,
    PlayerDefinition,
    TeamSide,
)
from d12ball.flow import (  # noqa: F401
    FollowOn,
    FollowOnStep,
    StepResult,
)
from d12ball.flow.arrivals import (  # noqa: F401
    attempt_mind_pull_step,
    begin_shooter_choice as flow_begin_shooter_choice,
    continue_mind_pull as flow_continue_mind_pull,
    continue_smooth as flow_continue_smooth,
    decline_scoring_attempt as flow_decline_scoring_attempt,
    dispatch_arrival_resume as flow_dispatch_arrival_resume,
    offer_scoring_attempt_choice as flow_offer_scoring_attempt_choice,
)
from d12ball.flow.effects import (  # noqa: F401
    deflection_step,
    dribble_advance_step,
    dribble_burst_step,
    high_pass_step,
    low_pass_step,
    offer_dribble_advance,
    offer_dribble_burst,
    offer_high_pass,
    offer_low_pass,
    offer_setup_pass_distance as flow_offer_setup_pass_distance,
    own_goal_roll_step,
    pressure_step,
    setup_pass_out_step,
    setup_pass_push_back_step,
    setup_pass_speed_step,
    setup_pass_step,
    speed_choice_step,
    steal_step,
    take_smooth_step,
)
from d12ball.flow.injuries import (  # noqa: F401
    begin_injury_tests as flow_begin_injury_tests,
    continue_injury_tests as flow_continue_injury_tests,
    injury_test_step,
)
from d12ball.flow.periods import (  # noqa: F401
    begin_full_time_coaching as flow_begin_full_time_coaching,
    begin_halftime as flow_begin_halftime,
    begin_halftime_extra_token as flow_begin_halftime_extra_token,
    begin_halftime_substitutions as flow_begin_halftime_substitutions,
    begin_shootout as flow_begin_shootout,
    finish_full_time_coaching as flow_finish_full_time_coaching,
    goal_log,
)
from d12ball.flow.turn import (  # noqa: F401
    announce_uncontested_maneuver as flow_announce_uncontested_maneuver,
    record_turn_action as flow_record_turn_action,
)
from d12ball.flow.turnovers import (  # noqa: F401
    run_back_space_ask,
)
from d12ball.flow.windows import (  # noqa: F401
    apply_position_swap as flow_apply_position_swap,
    apply_reposition as flow_apply_reposition,
    apply_substitution as flow_apply_substitution,
    begin_time_out as flow_begin_time_out,
    coaching_summary as flow_coaching_summary,
    coaching_window_note as flow_coaching_window_note,
    cover_kickoff_space as flow_cover_kickoff_space,
)
from d12ball.game import (  # noqa: F401
    D12BallGame,
)
from d12ball.prompts import (  # noqa: F401
    effect_choice_prompt,
    loose_ball_pick_prompt,
    maneuver_prompt_wording as flow_maneuver_prompt_wording,
    run_back_prompt,
    with_options,
)
from typing import (  # noqa: F401
    Optional,
)


async def run_step(cog, interaction, game, match, step, lead_in='', **kwargs):
    """Run one step of the flow by name, and everything it starts."""
    await cog.dispatch_step_result(interaction, game, match, StepResult(narration=[lead_in] if lead_in else [], next=FollowOn(step, kwargs)))


async def dispatch(cog, interaction, game, match, result):
    """Run what a step handed back, through the cog's presenter."""
    await cog.dispatch_step_result(interaction, game, match, result)


def record_turn_action(cog, match: MatchState, action: str, by_ai: bool=False) -> None:
    flow_record_turn_action(match, action, by_ai)


async def auto_resolve_challenger(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState, challenger_id: str) -> None:
    await cog.dispatch_step_result(interaction, game, match, StepResult(next=FollowOn(FollowOnStep.AUTO_RESOLVE_CHALLENGER, {'challenger_id': challenger_id})))


async def announce_uncontested_maneuver(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState) -> None:
    await cog.dispatch_step_result(interaction, game, match, flow_announce_uncontested_maneuver(cog.engine, game, match), carry=False)


async def begin_maneuver_action_selection(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState, lead_in: str='') -> None:
    await run_step(cog, interaction, game, match, FollowOnStep.BEGIN_MANEUVER_ACTION_SELECTION, lead_in=lead_in)


async def resolve_maneuver(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState, lead_in: str='') -> None:
    await run_step(cog, interaction, game, match, FollowOnStep.RESOLVE_MANEUVER, lead_in=lead_in)


async def begin_maneuver_skill_test(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState, headline: str, lead_in: str='') -> None:
    await run_step(cog, interaction, game, match, FollowOnStep.BEGIN_MANEUVER_SKILL_TEST, lead_in=lead_in, headline=headline)


async def begin_effect_resolution(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState, winner_key: str, lead_in: str='') -> None:
    await run_step(cog, interaction, game, match, FollowOnStep.BEGIN_EFFECT_RESOLUTION, lead_in=lead_in, winner_key=winner_key)


def maneuver_prompt_wording(cog, game: D12BallGame, match: MatchState, sides: list[str]) -> tuple[list[str], str]:
    return flow_maneuver_prompt_wording(cog.engine, game, match, sides)


async def begin_injury_tests(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState, players: list[PlayerDefinition], resume: dict) -> None:
    result = flow_begin_injury_tests(cog.engine, game, match, players, resume)
    await cog.dispatch_step_result(interaction, game, match, result)


async def continue_injury_tests(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState) -> None:
    result = flow_continue_injury_tests(cog.engine, game, match)
    await cog.dispatch_step_result(interaction, game, match, result)


async def run_injury_test(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState, player: PlayerDefinition) -> None:
    roll, result = injury_test_step(cog.engine, game, match, player.player_id)
    split = 0 if roll is None else 1
    with driver_reaches_cog_stubs(cog):
        outcome = cog.service.run(
            game, match,
            StepResult(narration=list(result.narration[split:]), board_changed=result.board_changed, next=result.next),
            answer=result.narration[:split], detail=roll,
        )
    await cog.post_injury_die(interaction, game, match, outcome)


def build_effect_choice_view(cog, game_id: str, match: MatchState) -> Optional[discord.ui.View]:
    prompt = effect_choice_prompt(cog.engine, cog.games[game_id], match)
    if prompt is None:
        return None
    return cog.view_for_prompt(game_id, match, prompt)


def build_run_back_view(cog, game_id: str, match: MatchState) -> Optional[discord.ui.View]:
    prompt = run_back_prompt(cog.engine, cog.games[game_id], match)
    if prompt is None:
        return None
    return cog.view_for_prompt(game_id, match, prompt)


async def resolve_skilled_pass(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState) -> None:
    await resolve_low_pass(cog, interaction, game, match, key='skilled_pass')


async def resolve_low_pass(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState, key: str='low_pass', free: bool=False) -> None:
    await cog.dispatch_step_result(interaction, game, match, offer_low_pass(cog.engine, game, match, key=key, free=free))


async def apply_low_pass(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState, distance: int, receiver_id: Optional[str]=None, key: str='low_pass', free: bool=False) -> None:
    result = low_pass_step(cog.engine, match, distance, receiver_id=receiver_id, key=key, free=free)
    await cog.dispatch_step_result(interaction, game, match, result)


async def resolve_dribble_advance(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState) -> None:
    await cog.dispatch_step_result(interaction, game, match, offer_dribble_advance(cog.engine, game, match))


async def apply_dribble_advance(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState, distance: int) -> None:
    result = dribble_advance_step(cog.engine, game, match, distance)
    await cog.dispatch_step_result(interaction, game, match, result)


async def resolve_dribble_burst(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState) -> None:
    await cog.dispatch_step_result(interaction, game, match, offer_dribble_burst(cog.engine, game, match))


async def apply_dribble_burst(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState, distance: int) -> None:
    result = dribble_burst_step(cog.engine, game, match, distance)
    await cog.dispatch_step_result(interaction, game, match, result)


async def resolve_high_pass(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState) -> None:
    await cog.dispatch_step_result(interaction, game, match, offer_high_pass(cog.engine, game, match))


async def resolve_setup_pass(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState) -> None:
    result = setup_pass_speed_step(cog.engine, match)
    await cog.dispatch_step_result(interaction, game, match, result)


async def offer_setup_pass_distance(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState) -> None:
    await cog.dispatch_step_result(interaction, game, match, flow_offer_setup_pass_distance(cog.engine, game, match))


async def apply_setup_pass(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState, distance: int) -> None:
    result = setup_pass_step(cog.engine, match, distance)
    await cog.dispatch_step_result(interaction, game, match, result)


async def apply_setup_pass_out(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState) -> None:
    result = setup_pass_out_step(match)
    await cog.dispatch_step_result(interaction, game, match, result)


async def apply_high_pass(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState, distance: int) -> None:
    result = high_pass_step(cog.engine, match, distance)
    await cog.dispatch_step_result(interaction, game, match, result)


async def begin_high_pass_contest(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState, distance_moved: int, lead_in: str='') -> None:
    await run_step(cog, interaction, game, match, FollowOnStep.BEGIN_HIGH_PASS_CONTEST, lead_in=lead_in, distance_moved=distance_moved)


async def offer_scoring_attempt_choice(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState, *, shooter_id: str, distance_moved: int, lead_in: str, contest_on_decline: bool=False) -> None:
    result = flow_offer_scoring_attempt_choice(cog.engine, game, match, shooter_id=shooter_id, distance_moved=distance_moved, lead_in=lead_in, contest_on_decline=contest_on_decline)
    await cog.dispatch_step_result(interaction, game, match, result)


async def decline_scoring_attempt(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState, distance_moved: int, contest: bool=False) -> None:
    result = flow_decline_scoring_attempt(cog.engine, game, match, distance_moved, contest=contest)
    await cog.dispatch_step_result(interaction, game, match, result)


async def continue_smooth(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState) -> None:
    result = flow_continue_smooth(cog.engine, game, match)
    await cog.dispatch_step_result(interaction, game, match, result)


async def continue_mind_pull(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState) -> None:
    result = flow_continue_mind_pull(cog.engine, game, match)
    await cog.dispatch_step_result(interaction, game, match, result)


async def run_smooth(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState, player_id: str) -> None:
    result = take_smooth_step(cog.engine, game, match, player_id=player_id)
    await cog.dispatch_step_result(interaction, game, match, result)


async def dispatch_arrival_resume(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState, resume: Optional[dict]) -> None:
    result = flow_dispatch_arrival_resume(cog.engine, game, match, resume)
    await cog.dispatch_step_result(interaction, game, match, result)


async def run_mind_pull(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState, player_id: str) -> None:
    roll, result = attempt_mind_pull_step(cog.engine, game, match, player_id=player_id)
    split = 1 if roll is not None and not roll.pulled else 0
    with driver_reaches_cog_stubs(cog):
        outcome = cog.service.run(
            game, match,
            StepResult(narration=list(result.narration[split:]), board_changed=result.board_changed, next=result.next),
            answer=result.narration[:split], detail=roll,
        )
    await cog.post_mind_pull_die(interaction, game, match, outcome)


def build_loose_ball_view(cog, game_id: str, match: MatchState) -> Optional[discord.ui.View]:
    prompt = loose_ball_pick_prompt(cog.engine, match)
    if prompt is None:
        return None
    game = cog.games[game_id]
    return cog.view_for_prompt(
        game_id, match, with_options(cog.engine, game, match, prompt),
    )


async def begin_loose_ball(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState, distance_moved: int, lead_in: str='', headline: Optional[str]=None, is_high_pass: bool=False) -> None:
    await run_step(cog, interaction, game, match, FollowOnStep.BEGIN_LOOSE_BALL, lead_in=lead_in, distance_moved=distance_moved, headline=headline, is_high_pass=is_high_pass)


async def resolve_loose_ball(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState, lead_in: str='') -> None:
    await run_step(cog, interaction, game, match, FollowOnStep.RESOLVE_LOOSE_BALL, lead_in=lead_in)


async def begin_shooter_choice(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState, candidates: list[str], lead_in: str='') -> None:
    result = flow_begin_shooter_choice(cog.engine, game, match, candidates, lead_in=lead_in)
    await cog.dispatch_step_result(interaction, game, match, result)


async def start_set_up_shot(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState, shooter_id: str, maneuver_cost: int=1) -> None:
    await run_step(cog, interaction, game, match, FollowOnStep.START_SET_UP_SHOT, shooter_id=shooter_id, maneuver_cost=maneuver_cost)


async def resolve_deflect(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState) -> None:
    await apply_deflection(cog, interaction, game, match, 'deflect')


async def resolve_clear(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState) -> None:
    await apply_deflection(cog, interaction, game, match, 'clear')


async def apply_deflection(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState, key: str) -> None:
    result = deflection_step(cog.engine, match, key)
    await cog.dispatch_step_result(interaction, game, match, result)


async def offer_setup_pass_push_back(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState, lead_in: str='') -> None:
    await run_step(cog, interaction, game, match, FollowOnStep.OFFER_SETUP_PASS_PUSH_BACK, lead_in=lead_in)


async def apply_setup_pass_push_back(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState, distance: int, lead_in: str='') -> None:
    result = setup_pass_push_back_step(cog.engine, game, match, distance=distance)
    if lead_in:
        result.narration[0] = f'{lead_in}\n\n{result.narration[0]}'
    await cog.dispatch_step_result(interaction, game, match, result)


async def resolve_steal(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState) -> None:
    await apply_steal(cog, interaction, game, match, 'steal')


async def resolve_intercept(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState) -> None:
    await apply_steal(cog, interaction, game, match, 'intercept')


async def apply_steal(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState, key: str) -> None:
    result = steal_step(cog.engine, match, key)
    await cog.dispatch_step_result(interaction, game, match, result)


async def resolve_pressure(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState) -> None:
    await apply_pressure(cog, interaction, game, match, 'pressure')


async def resolve_double_team(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState) -> None:
    await apply_pressure(cog, interaction, game, match, 'double_team')


async def apply_pressure(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState, key: str) -> None:
    result = pressure_step(cog.engine, match, key)
    await cog.dispatch_step_result(interaction, game, match, result)


async def offer_speed_choice(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState, player_id: str, skill_type: str, turnover_occurred: bool=False, distance_moved: int=1, lead_in: str='') -> None:
    await run_step(cog, interaction, game, match, FollowOnStep.OFFER_SPEED_CHOICE, lead_in=lead_in, player_id=player_id, skill_type=skill_type, turnover_occurred=turnover_occurred, distance_moved=distance_moved)


async def apply_speed_choice(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState, target_speed: int, turnover_occurred: bool=False, distance_moved: int=1, lead_in: str='') -> None:
    result = speed_choice_step(cog.engine, game, match, target_speed=target_speed, turnover_occurred=turnover_occurred, distance_moved=distance_moved)
    if lead_in:
        result.narration[0] = f'{lead_in}\n\n{result.narration[0]}'
    await cog.dispatch_step_result(interaction, game, match, result, carry=False)


async def continue_effect(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState, distance_moved: int=1, turnover_occurred: bool=False) -> None:
    await run_step(cog, interaction, game, match, FollowOnStep.CONTINUE_EFFECT, distance_moved=distance_moved, turnover_occurred=turnover_occurred)


async def begin_own_goal_roll(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState, distance_moved: int, lead_in: str='') -> None:
    await run_step(cog, interaction, game, match, FollowOnStep.BEGIN_OWN_GOAL_ROLL, lead_in=lead_in, distance_moved=distance_moved)


async def run_own_goal_roll(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState) -> None:
    roll, result = own_goal_roll_step(cog.engine, game, match)
    with driver_reaches_cog_stubs(cog):
        outcome = cog.service.run(
            game, match,
            StepResult(board_changed=result.board_changed, next=result.next),
            answer=result.narration, detail=roll,
        )
    await cog.post_own_goal_dice(interaction, game, match, outcome)


def apply_substitution(cog, game: D12BallGame, match: MatchState, side: TeamSide, outgoing_player_id: str, incoming_player_id: str) -> str:
    return flow_apply_substitution(cog.engine, game, match, side, outgoing_player_id, incoming_player_id)


def apply_position_swap(cog, match: MatchState, side: TeamSide, player_id: str, other_player_id: str) -> str:
    return flow_apply_position_swap(cog.engine, match, side, player_id, other_player_id)


def apply_reposition(cog, match: MatchState, side: TeamSide, player_id: str, space_index: int, swap_with: Optional[str]=None) -> str:
    return flow_apply_reposition(cog.engine, match, side, player_id, space_index, swap_with)


def coaching_window_note(cog, match: MatchState, side: TeamSide, occasion: CoachingOccasion, is_response: bool, restored: bool) -> str:
    return flow_coaching_window_note(cog.engine, match, side, occasion, is_response, restored)


async def begin_substitution_window(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState, side: TeamSide, occasion: CoachingOccasion=CoachingOccasion.NEW_PLAY, is_response: bool=False, lead_in: str='') -> None:
    await run_step(cog, interaction, game, match, FollowOnStep.BEGIN_SUBSTITUTION_WINDOW, side=TeamSide(side), occasion=CoachingOccasion(occasion), is_response=is_response, heading=lead_in)


def coaching_summary(cog, match: MatchState, side: TeamSide) -> list[str]:
    return flow_coaching_summary(cog.engine, match, side)


def cover_kickoff_space(cog, match: MatchState, side: TeamSide) -> Optional[str]:
    return flow_cover_kickoff_space(cog.engine, match, side)


async def finish_substitution_window(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState) -> None:
    await run_step(cog, interaction, game, match, FollowOnStep.FINISH_SUBSTITUTION_WINDOW)


async def begin_time_out(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState) -> None:
    result = flow_begin_time_out(cog.engine, game, match)
    cog.service.persist(game, match)
    await cog.drop_turn_prompt(interaction, game)
    await cog.dispatch_step_result(interaction, game, match, result)


async def begin_run_back(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState, distance_moved: int=1, turnover_occurred: bool=True, new_play: bool=False, speed_choice_after: bool=False, speed_reset: bool=True, lead_in: str='') -> None:
    await run_step(cog, interaction, game, match, FollowOnStep.BEGIN_RUN_BACK, lead_in=lead_in, distance_moved=distance_moved, turnover_occurred=turnover_occurred, new_play=new_play, speed_choice_after=speed_choice_after, speed_reset=speed_reset)


async def announce_run_back(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState, lead_in: str='', speed_reset: bool=True) -> None:
    await run_step(cog, interaction, game, match, FollowOnStep.ANNOUNCE_RUN_BACK, lead_in=lead_in, speed_reset=speed_reset)


def run_back_space_prompt(cog, game: D12BallGame, match: MatchState, side: TeamSide, player_id: str, mention: str) -> str:
    return run_back_space_ask(cog.engine, game, match, side, player_id, mention)


async def finish_run_back(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState, lead_in: str='') -> None:
    await run_step(cog, interaction, game, match, FollowOnStep.FINISH_RUN_BACK, lead_in=lead_in)


async def apply_ball_recovery(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState, player_id: str, lead_in: str='') -> None:
    await run_step(cog, interaction, game, match, FollowOnStep.APPLY_BALL_RECOVERY, lead_in=lead_in, player_id=player_id)


async def finish_maneuver_resolution(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState, distance_moved: int=1, turnover_occurred: bool=False, lead_in: str='') -> None:
    await run_step(cog, interaction, game, match, FollowOnStep.FINISH_MANEUVER_RESOLUTION, lead_in=lead_in, distance_moved=distance_moved, turnover_occurred=turnover_occurred)


async def end_period(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState, lead_in: str='') -> None:
    await run_step(cog, interaction, game, match, FollowOnStep.END_PERIOD, lead_in=lead_in)


def build_goal_log(cog, match: MatchState) -> str:
    return goal_log(cog.engine, match)


async def begin_halftime(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState) -> None:
    result = flow_begin_halftime(cog.engine, game, match)
    await cog.dispatch_step_result(interaction, game, match, result, carry=False)


async def finish_setup_coaching(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState, lead_in: str='') -> None:
    await run_step(cog, interaction, game, match, FollowOnStep.FINISH_SETUP_COACHING, lead_in=lead_in)


async def begin_halftime_extra_token(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState, side: TeamSide) -> None:
    result = flow_begin_halftime_extra_token(cog.engine, game, match, side)
    await cog.dispatch_step_result(interaction, game, match, result, carry=False)


async def begin_halftime_substitutions(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState, side: TeamSide) -> None:
    result = flow_begin_halftime_substitutions(cog.engine, game, match, side)
    await cog.dispatch_step_result(interaction, game, match, result, carry=False)


async def finish_halftime(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState, lead_in: str='') -> None:
    await run_step(cog, interaction, game, match, FollowOnStep.FINISH_HALFTIME, lead_in=lead_in)


async def begin_full_time_coaching(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState) -> None:
    result = flow_begin_full_time_coaching(cog.engine, game, match)
    await cog.dispatch_step_result(interaction, game, match, result, carry=False)


async def finish_full_time_coaching(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState) -> None:
    result = flow_finish_full_time_coaching(cog.engine, game, match)
    await cog.dispatch_step_result(interaction, game, match, result, carry=False)


async def begin_shootout(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState) -> None:
    result = flow_begin_shootout(cog.engine, game, match)
    await cog.dispatch_step_result(interaction, game, match, result, carry=False)


async def continue_shootout(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState) -> None:
    await run_step(cog, interaction, game, match, FollowOnStep.CONTINUE_SHOOTOUT)


def apply_exhaustion(cog, game: D12BallGame, match: MatchState, player_id: str, amount: int) -> str:
    return cog.engine.apply_exhaustion(game, match, player_id, amount)


def describe_exhaustion_gain(cog, game: D12BallGame, match: MatchState, player_id: str, amount: int) -> str:
    return cog.engine.describe_exhaustion_gain(game, match, player_id, amount)


def describe_challenger_walk_in(cog, game: D12BallGame, match: MatchState, defender_id: str, distance: int) -> str:
    if distance <= 0:
        return ''
    defender = cog.engine.get_player_definition(defender_id)
    space_word = 'space' if distance == 1 else 'spaces'
    return f'{defender.name} has moved {distance} {space_word}.\n{describe_exhaustion_gain(cog, game, match, defender_id, distance)}'


def schedule_board_refresh(cog, channel: discord.TextChannel, game: D12BallGame, delay: float) -> None:
    cog.boards.schedule(channel, game, delay)


def board_refresh_interval(cog, game: D12BallGame) -> float:
    return cog.boards.interval(game)


def note_board_write_refused(cog, game: D12BallGame) -> None:
    cog.boards.note_write_refused(game)


async def wait_out_board_interval(cog, game: D12BallGame) -> None:
    await cog.boards.wait_out_interval(game)


async def write_board_message(cog, channel: discord.TextChannel, game: D12BallGame, png: Optional[bytes]=None, *, relink: bool=True) -> None:
    await cog.boards.write(channel, game, png, relink=relink)


async def settle_board_link(cog, channel: discord.TextChannel, game: D12BallGame) -> None:
    await cog.boards.settle_link(channel, game)


async def play_ai_turn(cog, interaction: discord.Interaction, game: D12BallGame, match: MatchState) -> None:
    await run_step(cog, interaction, game, match, FollowOnStep.START_TURN)


def tutorial_player_side(cog, game: D12BallGame) -> TeamSide:
    return tutorial.player_side(game)


def tutorial_dice(cog, game: D12BallGame, kind: str, count: int) -> Optional[list[int]]:
    return tutorial.scripted_dice(tutorial.beat_for_game(game), kind, count)


# -- The live routines that moved into GameService ---------------------


async def continue_run_back(cog, interaction, game, match, lead_in=""):
    await run_step(cog, interaction, game, match, FollowOnStep.CONTINUE_RUN_BACK, lead_in=lead_in)


async def begin_ball_recovery(cog, interaction, game, match, lead_in=""):
    from d12ball.flow.turnovers import begin_ball_recovery as step
    await dispatch(cog, interaction, game, match, step(cog.engine, game, match, lead_in=lead_in))


async def finish_time_out(cog, interaction, game, match):
    from d12ball.flow.windows import finish_time_out as step
    await dispatch(cog, interaction, game, match, step(cog.engine, game, match))


async def resume_pending_prompt(cog, interaction, game, match) -> str:
    """`GameService.resume`, over the match a test has built by hand:
    the service reads the record, so the match is written to it first."""
    game.match_state = match.to_dict()
    return await cog.resume_game(interaction, game)
