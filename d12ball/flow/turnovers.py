"""
The turnover half of the turn's flow, with no Discord in it.

What a turnover *does* -- who runs back, who picks the ball up off the
floor -- is the model's; how the question reaches a coach is the cog's.
See "The model and the Discord layer" in CLAUDE.md, and
`docs/design/possession-and-turnovers.md` for the rules these steps
carry.

A step here mutates the match and returns a `StepResult`. It does not
send, it does not save, and it never sees an `interaction`.
"""

from __future__ import annotations

from d12ball.components import MatchState
from d12ball.engine import RulesEngine
from d12ball.flow.result import FollowOn, FollowOnStep, StepResult
from d12ball.game import D12BallGame
from d12ball.prompts import PendingPrompt, PromptKind


def ball_recovery_step(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
) -> StepResult:
    """
    Ask the side that won an out-of-bounds ball, or called a time out,
    which of their players goes and stands on it: the nearest either
    side of it, from any zone, at one exhaustion token per space
    traveled. It is the same choice a loose ball and a challenge put,
    and since 2026-08-16 it is the same pool -- it used to offer the
    whole field, which is a distance sum the coach had to do off the
    board.

    Deliberately the last thing that happens: both callers reset
    everyone to their arrangement first, so this player is placed once
    and stays, where placing them before it would only have them run
    back off the ball and leave it loose all over again.

    **Which is also why it asks whether there is anything to do.** A
    reset can perfectly well put one of the gaining side on the ball's
    space by itself -- that is the arrangement's own doing, and the
    rules ask for a pickup "unless one of theirs is already on it".
    `finish_time_out` decides this before it sets the flag, because it
    has a second branch to run either way; the out-of-bounds path sets
    the flag before the reset, so the question can only be asked here.

    It takes `game` because two of its three branches ask something
    only the record knows -- which side the AI is playing, and which
    coach to name.
    """
    side = match.ball.possession
    candidates = (
        [] if match.eligible_ball_handlers()
        else match.contest_candidates(side)
    )
    if not candidates:
        # Somebody of theirs is already standing on it, or nobody is
        # fielded at all. Either way nothing is placed: let the
        # loose-ball check downstream deal with it, the same way an
        # empty kickoff is handled.
        match.pending_ball_recovery = False
        return StepResult(
            next=FollowOn(
                FollowOnStep.FINISH_MANEUVER_RESOLUTION,
                {
                    "distance_moved": match.pending_run_back_distance,
                    "turnover_occurred": True,
                },
            ),
        )

    if engine.side_is_ai(game, side):
        # Nearest, not best: this walk costs a token per space and
        # wins nothing, so the only thing worth optimizing is how much
        # it costs.
        return StepResult(
            next=FollowOn(
                FollowOnStep.APPLY_BALL_RECOVERY,
                {"player_id": min(candidates, key=match.distance_to_ball)},
            ),
        )

    return StepResult(
        next=PendingPrompt(
            PromptKind.BALL_RECOVERY,
            engine.build_ball_recovery_prompt(game, match),
        ),
    )
