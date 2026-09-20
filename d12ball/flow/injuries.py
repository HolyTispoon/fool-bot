"""
The injury tests a resolved contest owes, as flow steps.

**A contest cannot simply carry on into its effect**: the tests are
clicks, and the last of them may be several minutes after the roll that
owed them. So the queue and the continuation are both match state, and
these two functions are the one way in and the one way out of it.

Lifted in Phase 4 of docs/model-discord-split.md out of
`cogs/d12ball/core.py`. What did **not** come with them is
`dispatch_injury_resume`: two of the three arrivals it names
(`begin_effect_resolution` and `continue_shootout`) are still the cog's,
so the drained queue ends on `FollowOnStep.DISPATCH_INJURY_RESUME` and
the cog dispatches it -- which is what that enum is for. See
"Injury tests" in docs/design/maneuvers.md for what a test is.
"""

from __future__ import annotations

from typing import Optional, Sequence

from d12ball.components import MatchState, PlayerDefinition
from d12ball.engine import RulesEngine
from d12ball.flow.result import FollowOn, FollowOnStep, StepResult
from d12ball.game import D12BallGame
from d12ball.prompts import PendingPrompt, PromptKind


def injury_test_ask(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    player_id: str,
) -> str:
    """
    The line the next owed test is put up under.

    **Deliberately not `pending_prompt`'s wording for the same state.**
    That one is a restart re-asking a question a coach has already seen
    ("... still owes an injury test"); this is the first time it is
    put, and it carries the mention and the token count because the
    coach is being asked to roll now. Two askings of one question, not
    two answers to it -- the *kind* is the same either way, which is
    what `view_for_prompt` reads.
    """
    player = engine.get_player_definition(player_id)
    controller_id = engine.controlling_user_id(game, match, player_id)
    mention = f"<@{controller_id}>" if controller_id else "Someone"
    tokens = match.exhaustion.get(player_id, 0)
    return (
        f"{mention}, "
        f"{engine.format_player_label(match, player)} is "
        "exhausted and owes an injury test: a d12 that has to "
        f"beat their {tokens} exhaustion "
        f"{'token' if tokens == 1 else 'tokens'}."
    )


def begin_injury_tests(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    players: Sequence[PlayerDefinition],
    resume: dict,
) -> StepResult:
    """
    Queue the tests a resolved contest owes and ask for the first, or
    hand straight on when it owes none.

    `resume` is the continuation, persisted with the queue because a
    restart in between has nothing else to reconstruct it from -- the
    skill test's winner is not derivable once the roll has happened
    (`settled_maneuver_winner` answers None while a test is owed), and
    a loose ball's distance is gone with the state that cleared it.

    A player already injured owes nothing, so the queue is filtered
    here rather than refused at the prompt -- an injured player gains
    no exhaustion tokens and can never be asked again.
    """
    owed = [
        player.player_id
        for player in players
        if player.player_id not in match.injured
    ]
    if not owed:
        # Nothing owed is the common case, and it writes nothing: the
        # contest carries straight on into its continuation, exactly as
        # it did before the tests became clicks.
        return StepResult(
            next=FollowOn(
                FollowOnStep.DISPATCH_INJURY_RESUME, {"resume": resume},
            ),
        )

    match.pending_injury_tests = owed
    match.pending_injury_resume = resume
    return continue_injury_tests(engine, game, match)


def continue_injury_tests(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
) -> StepResult:
    """
    Ask for the next injury test still owed, or -- when there are none
    left -- hand back what the contest that owed them was going to do.
    The one exit from the queue, so a test that is rolled and a test
    that turns out not to be owed leave by the same door.
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
                injury_test_ask(engine, game, match, player_id),
                player_id=player_id,
            ),
        )

    resume: Optional[dict] = match.pending_injury_resume
    match.pending_injury_resume = None
    return StepResult(
        next=FollowOn(
            FollowOnStep.DISPATCH_INJURY_RESUME, {"resume": resume},
        ),
    )
