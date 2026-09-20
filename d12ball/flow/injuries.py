"""
The injury tests a resolved contest owes, as flow steps.

**A contest cannot simply carry on into its effect**: the tests are
clicks, and the last of them may be several minutes after the roll that
owed them. So the queue and the continuation are both match state, and
these two functions are the one way in and the one way out of it.

Lifted in Phase 4 of docs/model-discord-split.md out of
`cogs/d12ball/core.py`, and `dispatch_injury_resume` followed in Phase
5. It stayed behind the first time because two of the three arrivals it
names were still the cog's, and "a dispatcher that can only answer one
of its three kinds in the model is a dispatcher split in two". Phase 5
took the shootout, so `continue_shootout` answers here now; the third,
`begin_effect_resolution`, is still the cog's and is named as a
follow-on like any other. See "Injury tests" in
docs/design/maneuvers.md for what a test is.
"""

from __future__ import annotations

from typing import Optional, Sequence

import logging

from d12ball.components import (
    MatchState,
    PlayerDefinition,
    legacy_maneuver_key,
)
from d12ball.engine import RulesEngine
from d12ball.flow.result import FollowOn, FollowOnStep, StepResult
from d12ball.game import D12BallGame
from d12ball.prompts import PendingPrompt, PromptKind


LOGGER = logging.getLogger(__name__)


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
        return dispatch_injury_resume(engine, game, match, resume)

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
    return dispatch_injury_resume(engine, game, match, resume)


def dispatch_injury_resume(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    resume: Optional[dict],
    lead_in: str = "",
) -> StepResult:
    """
    Pick the turn back up where the injury tests interrupted it.
    The kinds are the contests that hand them out: a maneuver's
    skill test goes on to the winner's effect, a loose ball (or
    the long High Pass that borrows its machinery) goes on to its
    run back, and a shootout skill test goes on to the next one --
    or to the end of the game.

    `lead_in` is here because every follow-on is called with one,
    and it is passed on to the only kind with somewhere to put it.
    It is always `""` today: an injury test interrupts a contest
    that has already posted its own message, so there is no
    narration waiting when the queue drains. The parameter is what
    makes that true by construction rather than by accident -- a
    later caller that does batch into here reaches `begin_run_back`
    with its lines instead of dropping them silently.

    **A resume it cannot read is logged and nothing else**, which is
    the one place in the flow that logs rather than returning
    something. A game in that state needs `/d12ball resume`, and the
    step has nothing true to say about a position it cannot find.
    """
    from d12ball.flow.periods import continue_shootout

    kind = (resume or {}).get("kind")
    if kind == "shootout_test":
        # Nothing writes this any more -- a shootout test stopped
        # owing injury checks on 2026-08-15 and goes straight to
        # `continue_shootout` itself. It is still read, because a
        # game saved between that roll and its tests outlives the
        # change: the same reason `TeamSetup.from_dict` still
        # answers to `player_board`. It dies out on its own.
        return continue_shootout(engine, game, match)
    if kind == "maneuver_effect":
        # `winner_name` is what this carried before maneuvers had
        # keys, and a game saved mid-injury-test outlives the
        # change -- so the old spelling is still read and never
        # written. Same tolerance as `legacy_maneuver_key`.
        return StepResult(
            next=FollowOn(
                FollowOnStep.BEGIN_EFFECT_RESOLUTION,
                {
                    "winner_key": (
                        resume.get("winner_key")
                        or legacy_maneuver_key(resume.get("winner_name"))
                    ),
                },
            ),
        )
    if kind == "run_back":
        # **Named rather than called**, unlike the shootout above, and
        # for the reason the member exists: `D12Ball.begin_run_back` is
        # what decides whether a new play's board is posted and pinned,
        # which is not a decision the model may take. See
        # `FollowOnStep.BEGIN_RUN_BACK`.
        return StepResult(
            narration=[lead_in] if lead_in else [],
            next=FollowOn(
                FollowOnStep.BEGIN_RUN_BACK,
                {
                    "distance_moved": resume.get("distance_moved", 1),
                    "turnover_occurred": resume.get(
                        "turnover_occurred", True,
                    ),
                },
            ),
        )
    LOGGER.error(
        "Game %s finished its injury tests with nothing to resume "
        "(%r); it needs /d12ball resume.",
        game.game_id,
        resume,
    )
    return StepResult()
