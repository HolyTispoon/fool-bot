"""
The rolls a contest owes, with no Discord in them.

A d12 a coach has to press a button for is two halves: *who owes it and
what happens when the queue empties*, which is the model's and is here,
and the die image and the message it is edited into, which is the cog's.
See "Every roll is a coach's" in docs/design/maneuvers.md.

A step here mutates the match and returns a `StepResult`. It does not
send, it does not save, and it never sees an `interaction`.
"""

from __future__ import annotations

from typing import Any, Mapping

from d12ball.components import MatchState, PlayerDefinition
from d12ball.engine import RulesEngine
from d12ball.flow.result import FollowOn, FollowOnStep, StepResult
from d12ball.game import D12BallGame
from d12ball.prompts import PendingPrompt, PromptKind


def begin_injury_tests_step(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    players: list[PlayerDefinition],
    resume: Mapping[str, Any],
) -> StepResult:
    """
    Hand the injury tests a resolved contest owes to the coaches, one
    button each, and remember what the contest was going to do next.

    **A contest cannot simply carry on into its effect any more**: the
    tests are clicks, and the last of them may be several minutes
    after the roll that owed them. `resume` is that continuation,
    persisted with the queue because a restart in between has nothing
    else to reconstruct it from -- the skill test's winner is not
    derivable once the roll has happened (`settled_maneuver_winner`
    answers None while a test is owed), and a loose ball's distance is
    gone with the state that cleared it. `dispatch_injury_resume` is
    the other half and is still the cog's.

    A player already injured owes nothing, so the queue is filtered
    here rather than refused at the prompt -- an injured player gains
    no exhaustion tokens and can never be asked again.

    **Nothing is written when nothing is owed**, which is the common
    case and the one that has to stay free: the contest carries
    straight on into its continuation, exactly as it did before the
    tests became clicks.
    """
    owed = [
        player.player_id
        for player in players
        if player.player_id not in match.injured
    ]
    if not owed:
        return StepResult(
            next=FollowOn(
                FollowOnStep.DISPATCH_INJURY_RESUME, {"resume": resume},
            ),
        )

    match.pending_injury_tests = owed
    match.pending_injury_resume = dict(resume)
    return continue_injury_tests_step(engine, game, match)


def continue_injury_tests_step(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
) -> StepResult:
    """
    Ask for the next injury test still owed, or -- when there are none
    left -- do what the contest that owed them was going to do.

    **The one exit from the queue**, so a test that is rolled and a
    test that turns out not to be owed leave by the same door. That is
    also why `begin_injury_tests_step` ends by calling it rather than
    by returning a prompt of its own: a queue with one entry and a
    queue with two leave by the same door too.
    """
    while match.pending_injury_tests:
        player_id = match.pending_injury_tests[0]
        if player_id in match.injured:
            # Injured since the queue was built -- by the other
            # participant's test, which cannot happen today, but a
            # player who cannot be injured twice should never be asked
            # to roll for it.
            match.pending_injury_tests.pop(0)
            continue

        return StepResult(
            next=PendingPrompt(
                PromptKind.INJURY_TEST,
                engine.build_injury_test_prompt(game, match, player_id),
                player_id=player_id,
            ),
        )

    resume = match.pending_injury_resume
    match.pending_injury_resume = None
    return StepResult(
        next=FollowOn(
            FollowOnStep.DISPATCH_INJURY_RESUME, {"resume": resume},
        ),
    )
