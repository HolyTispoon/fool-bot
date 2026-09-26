"""
The injury tests a resolved contest owes, as flow steps.

**A contest cannot simply carry on into its effect**: the tests are
clicks, and the last of them may be several minutes after the roll that
owed them. So the queue and the continuation are both match state, and
these two functions are the one way in and the one way out of it.

Lifted in Phase 4 of docs/design/model-discord-split.md out of
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
from dataclasses import dataclass

from d12ball.components import (
    EVENT_INJURY_TEST,
    MatchState,
    PlayerDefinition,
    legacy_maneuver_key,
)
from d12ball.engine import RulesEngine
from d12ball.flow.result import FollowOn, FollowOnStep, StepResult
from d12ball.flow.turn import injured_word_and_emoji, scripted_or_random
from d12ball.formatting import address_coach
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
    mention = address_coach(
        engine.controlling_player_number(game, match, player_id),
    )
    tokens = match.exhaustion.get(player_id, 0)
    exhausted_word, _ = engine.exhausted_word_and_mark(game, player_id)
    token_noun, _ = engine.token_word_and_mark(game, player_id)
    test_name = _with_article(engine.injury_test_name(game, player_id))
    return (
        f"{mention}, "
        f"{engine.format_player_label(match, player)} is "
        f"{exhausted_word} and owes {test_name}: a d12 that has to "
        f"beat their {tokens} {token_noun} "
        f"{'token' if tokens == 1 else 'tokens'}."
    )


def _with_article(test_name: str) -> str:
    """ "an injury test", "a damage test". """
    return f"{'an' if test_name[0] in 'aeiou' else 'a'} {test_name}"


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
        # for the reason the member exists: `d12ball.flow.turnovers.begin_run_back` is
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


@dataclass(frozen=True)
class InjuryRoll:
    """
    One injury check's numbers, for the picture of the die.

    **Not narration and not a `StepResult`.** What the check came to is
    the sentence beside this; what is here is the face, whether it was
    safe, and whether Overdrive was on it -- which is what
    `render_injury_test_die` draws and what a frontend with no dice
    image ignores. There is no `ignite`: Volatile does not reach an
    injury check (the author, 2026-09-23), and Kindlefinger's (Law 21)
    is said in the sentence beside the die rather than drawn.
    """

    player_id: str
    roll: int
    safe: bool
    overdrive: int

    def to_dict(self) -> dict:
        return {
            "shape": "injury",
            "player_id": self.player_id,
            "roll": self.roll,
            "safe": self.safe,
            "overdrive": self.overdrive,
        }


def injury_test_step(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    player_id: str,
) -> tuple[Optional[InjuryRoll], StepResult]:
    """
    One injury test, off the button `continue_injury_tests` posted for
    it: roll a d12, and if it does not beat the player's current
    exhaustion token count, they become injured.

    Exhausted is judged when the contest resolves, not when it started,
    and against every token they hold by then -- the one each
    participant pays to enter the test and one more each time a tie
    sends it back to be rolled again, all of which count. A player the
    test itself pushed over their defensive skill rolls this check for
    that same test.

    **An already-injured player rolls nothing**, and the roll comes
    back as None to say so: an injured player cannot be injured again,
    so they leave the queue in silence. Back to the queue rather than
    out of it, so this can never be where a turn stops.
    """
    player = engine.get_player_definition(player_id)
    if player_id in match.injured:
        if player_id in match.pending_injury_tests:
            match.pending_injury_tests.remove(player_id)
        return None, continue_injury_tests(engine, game, match)

    # The script fixes injury checks to pass for the whole tutorial --
    # see `BLANKET_ROLLS`. The check still runs and the coach still
    # watches it.
    roll = scripted_or_random(engine, game, "injury", 1)[0]
    # **Volatile does not reach this roll** (the author, 2026-09-23):
    # a Fire Demon's natural 6 or 7 here is only the number -- except
    # Kindlefinger's (Law 21), which `injury_ignite` alone answers.
    # Overdrive still is -- it is the Cyborg's to spend on any roll.
    ignite = engine.injury_ignite(game, player_id, roll)
    overdrive = match.overdrive_modifier(player_id)
    match.consume_overdrive()
    check = roll + overdrive + ignite.modifier
    # Kindlefinger's token moves **before** the check is compared (the
    # author, 2026-09-26), as a skill test's own tokens count toward the
    # check behind it.
    ignite_tokens = engine.settle_injury_ignite(game, match, player_id, ignite)
    current_tokens = match.exhaustion.get(player_id, 0)
    safe = check > current_tokens
    # The die image draws the natural face, so a modifier has to be
    # said in words or the number a coach reads and the verdict they
    # are given would not add up.
    modifiers = [
        part for part in (
            f"+{overdrive} Overdrive" if overdrive else None,
            ignite.detail,
        )
        if part
    ]
    overdrive_note = (
        f" ({', '.join(modifiers)}, {check})" if modifiers else ""
    )

    if player_id in match.pending_injury_tests:
        match.pending_injury_tests.remove(player_id)

    # Both outcomes, not only the injury. What a coach wants from this
    # is the *rate* -- how often playing a card that ties actually
    # costs a player -- and a log holding only the failures has no
    # denominator. `mark_injured` deliberately logs nothing for the
    # same reason.
    match.record_event(
        EVENT_INJURY_TEST,
        side=match.side_for_player(player_id),
        player_id=player_id,
        roll=roll,
        tokens=current_tokens,
        injured=not safe,
    )

    drain = engine.drain_wording(game, player_id)
    exhausted_word = "drained" if drain else "exhausted"
    token_noun = "drain" if drain else "exhaustion"
    # A Cyborg's check is a damage test, and what it does to them is
    # damage (the author, 2026-09-23).
    test_name = _with_article(engine.injury_test_name(game, player_id))
    harm_noun = "damage" if drain else "injury"

    if safe:
        content = (
            f"{engine.format_player_label(match, player)} is "
            f"{exhausted_word} and rolls {test_name}: "
            f"{roll}{overdrive_note} beats their {current_tokens} "
            f"{token_noun} tokens — safe."
        )
    else:
        match.mark_injured(player_id)
        # What happened, and nothing about what it means from here. The
        # rest of the rule -- tokens removed, no longer exhausted, no
        # further tokens and no further checks -- was recited on every
        # injury in the game, and the board says all of it a moment
        # later: the tokens come off the card and the badge goes on.
        word, emoji = injured_word_and_emoji(engine, game, player_id)
        content = (
            f"{engine.format_player_label(match, player)} is "
            f"{exhausted_word} and rolls {test_name}: "
            f"{roll}{overdrive_note} does not beat their {current_tokens} "
            f"{token_noun} tokens — {harm_noun}! They are **{word}** {emoji}."
        )

    if ignite.ignited:
        content = "\n".join(filter(None, [
            ignite.explain(engine.format_player_label(match, player)),
            ignite_tokens,
            content,
        ]))

    result = continue_injury_tests(engine, game, match)
    result.narration.insert(0, content)
    result.board_changed = (
        result.board_changed or not safe or ignite.ignited
    )
    return (
        InjuryRoll(player_id, roll, safe, overdrive),
        result,
    )
