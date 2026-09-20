"""
The front half of a turn, and the injury tests a contest owes.

From a challenger being picked to a maneuver being settled: nothing in
Phases 1 to 3 touched any of it, and both a human's pick and
`play_ai_turn`'s pass through it -- which is why "`interaction` dies
from the flow" was qualified until Phase 4.

The injury tests are here too rather than beside the rolls, because
what they interrupt is a contest and what they resume into is the
contest's own continuation. See "Every roll is a coach's" in
docs/design/maneuvers.md.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

from d12ball.components import MatchState, PlayerDefinition
from d12ball.engine import RulesEngine
from d12ball.formatting import format_player_with_team, format_team_side_label
from d12ball.game import D12BallGame
from d12ball.prompts import PendingPrompt, PromptKind
from d12ball.flow.result import FollowOn, FollowOnStep, StepResult


def challenger_walk_in_note(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    defender_id: str,
    distance: int,
) -> str:
    """
    The challenger's walk-in and what it cost, or `""` when they were
    already on the ball's space.

    Like every other exhaustion message this tests the Exhausted
    threshold as it writes it, so it has to be built before `match` is
    saved -- see `RulesEngine.apply_exhaustion`.
    """
    if distance <= 0:
        return ""

    defender = engine.get_player_definition(defender_id)
    space_word = "space" if distance == 1 else "spaces"
    return (
        f"{defender.name} has moved {distance} {space_word}."
        f"\n{engine.describe_exhaustion_gain(game, match, defender_id, distance)}"
    )


def challenger_step(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    challenger_id: str,
) -> StepResult:
    """
    Apply an already-decided challenger pick -- no human choice
    involved, either because the AI made it or because a defender
    already shares the ball's space, leaving nothing to choose.

    The walk-in is built **before** the caller saves: the tokens it
    costs can cross the Exhausted threshold, and that flag is set
    while the description is put together.

    `board_changed` because the challenger has walked in; the
    announcement that follows draws the matchup rather than the board,
    so the frontend still writes one.
    """
    distance = match.choose_challenger(challenger_id)
    walk_in = challenger_walk_in_note(
        engine, game, match, challenger_id, distance,
    )
    return StepResult(
        narration=[walk_in] if walk_in else [],
        board_changed=True,
        next=FollowOn(
            FollowOnStep.ANNOUNCE_MANEUVER_CHALLENGE,
            {"challenger_id": challenger_id},
        ),
    )


def uncontested_maneuver_note(
    engine: RulesEngine,
    match: MatchState,
) -> str:
    """
    That there is nobody to challenge, and which of the two ways that
    happened.

    The message asks the state rather than taking a flag: anyone still
    eligible means the defense was offered the challenge and sent
    nobody, since a defense with somebody to send is the only defense
    that gets the choice. Since 2026-08-16 that is practically always
    the answer -- the other branch needs a side with nobody on the
    field at all.
    """
    handler = engine.get_player_definition(match.active_player_id)
    defense_setup = match.setup_for_side(match.defending_side())

    if match.eligible_challengers():
        reason = "have sent nobody in to challenge"
    else:
        reason = "have nobody left to challenge"

    return (
        f"**Unchallenged!** {format_team_side_label(defense_setup)} "
        f"{reason} "
        f"{engine.format_player_label(match, handler)}, "
        "so whichever maneuver the offense picks succeeds."
    )


def uncontested_maneuver_step(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
) -> StepResult:
    """
    Say that there is nobody to challenge, then go straight to the
    offense's pick.

    No matchup image and no board write: a decline moves nobody and
    charges nobody.
    """
    return StepResult(
        narration=[uncontested_maneuver_note(engine, match)],
        next=FollowOn(FollowOnStep.BEGIN_MANEUVER_ACTION_SELECTION),
    )


def maneuver_action_selection_step(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
) -> StepResult:
    """
    Are both picks in?

    Thin on purpose: the rest of what the cog does around this --
    Dinky answering before the prompt is built, the hand image, the
    tutorial note held behind Continue -- is all *how* the question
    reaches a coach. What is a rule is only whether there is still a
    question to ask, and `maneuver_selections_complete` is the one
    reading of it. Two call sites used to check
    `offense_maneuver and defense_maneuver` directly and would have
    hung the turn.
    """
    if match.maneuver_selections_complete:
        return StepResult(next=FollowOn(FollowOnStep.RESOLVE_MANEUVER))
    return StepResult(
        next=FollowOn(FollowOnStep.ASK_MANEUVER_ACTION),
    )


def maneuver_winner_text(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    reveal: str,
    outcome: str,
    winner_name: str,
    offense_name: str,
    defense_name: str,
) -> str:
    """
    How a maneuver settled on the cards reads. Two wordings: an
    ordinary decisive win, and a tie one injured participant loses
    outright.
    """
    if outcome != "tie":
        # Headed the same way a won skill test is, so the two ways a
        # maneuver can be won read alike. Whoever resolves the effect
        # isn't named here: an effect with a choice in it prompts them
        # by name itself, and one without needs nobody to do anything.
        return f"{reveal}\n\n## **{winner_name}** wins!"

    # A tie with exactly one injured participant: they lose it
    # outright. Nothing is rolled, so neither side pays the token a
    # skill test would have cost them.
    injured_player_id = (
        match.challenger_id
        if match.challenger_id in match.injured
        else match.active_player_id
    )
    injured_player = engine.get_player_definition(injured_player_id)
    word, emoji = engine.injured_word_and_emoji(game, injured_player_id)
    return (
        f"{reveal}\n\n"
        f"**{offense_name}** ties with **{defense_name}**, but "
        f"{engine.format_player_label(match, injured_player)}"
        f" is **{word}** "
        f"{emoji} and "
        "automatically loses the tie.\n\n"
        f"## **{winner_name}** wins!"
    )


def skill_test_headline(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    reveal: str,
    outcome: str,
    offense_name: str,
    defense_name: str,
) -> str:
    """
    Why a maneuver the cards did not settle is going to a skill test:
    the two ranked the same, or the one that would have won is owed to
    an injured player.
    """
    if outcome == "tie":
        # An ordinary tie -- both or neither participant is injured.
        return (
            f"{reveal}\n\n"
            f"**{offense_name}** ties with **{defense_name}** — skill "
            "test!\n\n"
        )

    # An injured player's maneuver never wins outright -- they still
    # have to win a skill test to make it stick.
    would_be_winner = (
        offense_name if outcome == "offense" else defense_name
    )
    injured_player_id = (
        match.active_player_id
        if outcome == "offense"
        else match.challenger_id
    )
    injured_player = engine.get_player_definition(injured_player_id)
    word, emoji = engine.injured_word_and_emoji(game, injured_player_id)
    return (
        f"{reveal}\n\n"
        f"**{would_be_winner}** would win, but "
        f"{engine.format_player_label(match, injured_player)} is "
        f"**{word}** {emoji} -- "
        "a skill test decides it instead!\n\n"
    )


def resolve_maneuver_step(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
) -> StepResult:
    """
    Both picks are in: reveal them, say how the maneuver landed, and
    hand it to the effect or to a skill test.

    **Who wins is `settled_maneuver_winner`'s alone to say**; what is
    decided here is only how the four ways it can land are worded.
    `outcome` is the ranking on its own, which is what separates a win
    on the cards from a win handed over by the other player's injury.
    """
    # Keys are what the match holds and what everything below
    # dispatches on; the names are only ever printed.
    offense_key = match.offense_maneuver
    defense_key = match.defense_maneuver
    offense_name = engine.maneuver_name(offense_key)
    defense_name = engine.maneuver_name(defense_key)
    offense_number = engine.possession_player_number(game, match)
    defense_number = engine.defending_player_number(game, match)
    offense_display = format_player_with_team(
        game, offense_number, engine.team_emojis,
    )
    defense_display = format_player_with_team(
        game, defense_number, engine.team_emojis,
    )

    if match.maneuver_uncontested:
        # Nothing to reveal against and nothing to rank: the offense's
        # pick is the winner, and its effect runs the same pipeline a
        # decisive win always does.
        return StepResult(
            narration=[
                f"{offense_display} chose **{offense_name}**, "
                f"unchallenged.\n\n## **{offense_name}** succeeds!"
            ],
            next=FollowOn(
                FollowOnStep.BEGIN_EFFECT_RESOLUTION,
                {"winner_key": offense_key},
            ),
        )

    reveal = (
        f"{offense_display} chose **{offense_name}**.\n"
        f"{defense_display} chose **{defense_name}**."
    )

    outcome = engine.maneuver_catalog.resolve(offense_key, defense_key)
    winner_key = engine.settled_maneuver_winner(match)

    if winner_key is not None:
        return StepResult(
            narration=[
                maneuver_winner_text(
                    engine,
                    game,
                    match,
                    reveal,
                    outcome,
                    engine.maneuver_name(winner_key),
                    offense_name,
                    defense_name,
                )
            ],
            next=FollowOn(
                FollowOnStep.BEGIN_EFFECT_RESOLUTION,
                {"winner_key": winner_key},
            ),
        )

    # **The headline is narration, not an argument.** It is the
    # reveal and why the cards did not settle it, and it opens the
    # message the skill test posts -- so it rides in `narration` like
    # every other lifted step's lines. Putting it in `FollowOn.kwargs`
    # would have worked and would have been wrong; see
    # "d12ball/flow/" in docs/design/model-discord-split.md.
    return StepResult(
        narration=[
            skill_test_headline(
                engine, game, match, reveal, outcome,
                offense_name, defense_name,
            )
        ],
        next=FollowOn(FollowOnStep.BEGIN_MANEUVER_SKILL_TEST),
    )


def begin_injury_tests_step(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    players: Sequence[PlayerDefinition],
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
    gone with the state that cleared it.

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
        # contest carries straight on into its continuation, exactly
        # as it did before the tests became clicks.
        return StepResult(
            next=FollowOn(
                FollowOnStep.DISPATCH_INJURY_RESUME,
                {"resume": dict(resume)},
            ),
        )

    match.pending_injury_tests = owed
    match.pending_injury_resume = dict(resume)
    return StepResult(
        next=FollowOn(FollowOnStep.CONTINUE_INJURY_TESTS),
    )


def continue_injury_tests_step(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
) -> StepResult:
    """
    Ask for the next injury test still owed, or -- when there are none
    left -- do what the contest that owed them was going to do.

    **The one exit from the queue**, so a test that is rolled and a
    test that turns out not to be owed leave by the same door.
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

        player = engine.get_player_definition(player_id)
        controller_id = engine.controlling_user_id(game, match, player_id)
        mention = f"<@{controller_id}>" if controller_id else "Someone"
        tokens = match.exhaustion.get(player_id, 0)
        return StepResult(
            next=PendingPrompt(
                PromptKind.INJURY_TEST,
                f"{mention}, "
                f"{engine.format_player_label(match, player)} is "
                "exhausted and owes an injury test: a d12 that has to "
                f"beat their {tokens} exhaustion "
                f"{'token' if tokens == 1 else 'tokens'}.",
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
