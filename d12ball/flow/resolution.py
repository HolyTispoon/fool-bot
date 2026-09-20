"""
The tail of every ordinary maneuver path, as a flow step.

A maneuver's movement, its speed, any turnover and the run back are
all settled by the time this runs. What is left is the spine: the two
arrival gates, the loose-ball check, the clock, and the decision
between ending the period and handing the offensive choice back.

**A step says one thing, and the frontend decides what a message
is.** Where the old cog said two things in two messages -- the clock
reaching last possession, and then the position with the board under
it -- the step ends on the first and names the second, so the two
stay two. Which is the rule the whole seam is made by, read from the
awkward end: batching is the frontend's (principle 8), and a step
that quietly joined those two would have changed what a coach reads
under cover of a refactor.
"""

from __future__ import annotations

from d12ball.components import MatchState
from d12ball.engine import RulesEngine
from d12ball.formatting import format_team_side_label, space_label
from d12ball.game import D12BallGame
from d12ball.flow.arrival import check_for_ball_arrival, check_for_loose_ball
from d12ball.flow.result import FollowOn, FollowOnStep, StepResult


def finish_maneuver_resolution_step(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    *,
    distance_moved: int = 1,
    turnover_occurred: bool = False,
    lead_in: str = "",
) -> StepResult:
    """
    Advance the clock, end the period if this turnover closes out last
    possession, clear the maneuver state, and say what happens next.

    The maneuver that reaches the period's last minute never ends it,
    even when it is itself a turnover: last possession is the
    possession that starts there, so whoever comes out of that
    maneuver with the ball gets to play it out and only loses the
    period when *they* lose the ball. Only a turnover under a last
    possession that was already in force ends it -- which is the case
    `begin_run_back` catches earlier, before any run back.

    `lead_in` is narration from earlier in the same effect that has
    not been posted yet. It rides along on whatever this hands to,
    instead of being sent separately, so a deterministic effect (no
    further human choice in between) reads as one message rather than
    a chain of them.

    Checked first, before the clock moves: the two arrival gates, and
    then does the possessing team actually have a player on the ball's
    space? If the maneuver left it somewhere they don't -- an empty
    space, or one only the other team occupies -- this detours into
    the loose ball instead, which re-enters this step itself once it
    is settled.
    """
    # **Mind Pull first**, because it pre-empts the arrival rather than
    # reacting to it: a pull that lands stops the ball on the
    # Telekinetic's space, so whether the possessing side has anybody
    # where the maneuver *would* have left it is a question that must
    # not be asked yet.
    taken = check_for_ball_arrival(
        engine,
        game,
        match,
        {
            "kind": "finish_maneuver",
            "distance_moved": distance_moved,
            "turnover_occurred": turnover_occurred,
            "lead_in": lead_in,
        },
    )
    if taken is not None:
        return taken

    detour = check_for_loose_ball(match, distance_moved)
    if detour is not None:
        return StepResult(
            narration=[lead_in] if lead_in else [],
            next=detour.next,
        )

    entered_last_possession = match.advance_time(distance_moved)
    if entered_last_possession:
        possessing_side = format_team_side_label(
            match.setup_for_side(match.ball.possession)
        )
        body = (
            "The turnover that got here doesn't end it -- "
            f"{possessing_side} came out of that maneuver with the "
            "ball, so they play last possession out."
            if turnover_occurred
            else "Play continues until the ball turns over, which "
            "ends the period."
        )
        # The minute is the period's own, and the clock does not stop
        # on it: from here every turn is charged as usual and only the
        # turnover ends the period.
        prefix = f"{lead_in}\n\n" if lead_in else ""
        notice = (
            f"{prefix}The clock reaches "
            f"{match.scoreboard.last_minute:02d} -- this is now "
            f"**last possession**. {body} The clock keeps running."
        )
        # **One block, and then the turn is handed back with nothing
        # carried.** The two sentences are one announcement, so the
        # model words them together; the board that follows is a
        # second message, so the frontend is told so by name rather
        # than by a blank line inside a string.
        #
        # The reset below still runs: the maneuver that declared last
        # possession is over like any other, and the turn is handed
        # back from the same state.
        match.reset_maneuver()
        return StepResult(
            narration=[notice],
            next=FollowOn(
                FollowOnStep.ANNOUNCE_LAST_POSSESSION,
                {"distance_moved": distance_moved},
            ),
        )

    if turnover_occurred and match.scoreboard.last_possession:
        # Only a turnover under a last possession **already in force**
        # ends the period -- the one that declares it is caught above
        # and never reaches here.
        return StepResult(
            narration=[lead_in] if lead_in else [],
            next=FollowOn(FollowOnStep.END_PERIOD),
        )

    match.reset_maneuver()
    return StepResult(
        narration=[lead_in] if lead_in else [],
        next=FollowOn(
            FollowOnStep.HAND_BACK_THE_TURN,
            {"distance_moved": distance_moved},
        ),
    )


def hand_back_the_turn_line(
    match: MatchState,
    distance_moved: int,
) -> str:
    """
    The one sentence under the settled board: where the ball is, whose
    it is, and what the maneuver cost.

    Every maneuver costs at least its flat space minute (2026-08-16),
    ceding included, so there is no longer a zero-cost turn to word
    specially here.

    It is a function of its own rather than part of the step above
    because the message it goes in carries the board image, so the
    cog builds that message -- but what it *says* is a fact about the
    position, which is the model's (principle 5).
    """
    clock = (
        f"Time has advanced {distance_moved}, now "
        f"at {match.scoreboard.time:02d}."
    )
    return (
        f"Ball is now "
        f"{space_label(match.ball.zone, match.ball.space_index)}, "
        f"{format_team_side_label(match.setup_for_side(match.ball.possession))} "
        f"has possession. {clock}"
    )
