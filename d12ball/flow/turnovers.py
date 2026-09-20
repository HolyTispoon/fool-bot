"""
Turnovers: what happens after possession changes hands, as flow steps.

A steal runs everybody back; a new play resets both sides to the
arrangement their coaches set and opens a window. `new_play` is the
whole distinction -- see "Turnovers: steals and new plays" in
docs/design/possession-and-turnovers.md.

**Two things here are deliberately not the ordinary shape, and both
are called out where they happen.** The cascade is a generator rather
than a step, because it is a loop whose every pass may or may not
need a coach; and the loop's per-pass save stays, as the one named
exception to principle 9.
"""

from __future__ import annotations

from typing import Iterator, Optional

from d12ball.components import MatchState, TeamSide
from d12ball.engine import RulesEngine
from d12ball.formatting import space_label
from d12ball.game import D12BallGame
from d12ball.flow.arrival import check_for_ball_arrival
from d12ball.flow.result import FollowOn, FollowOnStep, StepResult


def run_back_step(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    *,
    distance_moved: int = 1,
    turnover_occurred: bool = True,
    new_play: bool = False,
    speed_choice_after: bool = False,
    speed_reset: bool = True,
    lead_in: str = "",
) -> StepResult:
    """
    Set a run back up, or decide that there is not going to be one.

    `distance_moved`/`turnover_occurred` describe the maneuver that
    triggered this, stashed on `match` so they survive the multi-turn
    choice flow and reach the tail of the maneuver correctly once the
    run back -- which only ever costs exhaustion, never time -- is
    done.

    `speed_reset` is the announcement's own note, and only ever False
    for Dribble Burst's cost: every caller has already set
    `match.ball.speed` to whatever it should read by the time this
    runs, so it is wording, not state.

    `new_play` says the ball changed hands because play stopped and is
    restarting -- a goal, an own goal, a missed attempt, a ball out of
    bounds -- rather than because the other team took it off them.
    Only a new play opens a substitution window. It is not persisted:
    it is consumed here, and by the time anything is saved the state
    already says which of the two happened.

    **The player holding the ball does not run back**, whoever they
    are. The exemption is read off `ball_carrier_id` rather than
    passed in, because the two are the same fact: a run back that
    moved the ball's holder would run them off the ball and charge
    them for it. **Don't reintroduce the parameter** -- see
    docs/design/possession-and-turnovers.md.

    A new play exempts nobody: the ball went dead, so nobody is
    carrying it, and the reset that follows moves both sides whatever
    they were doing.

    A turnover that happens while last possession is already in force
    ends the period immediately instead: no run back, no window, and
    no speed manipulation either.

    A resolution that left possession where it was runs no run back at
    all -- "every time there's a turnover for any reason (steal, goal
    etc.) players have to run back" is the whole of when one happens.
    Keeping the ball leaves whoever is out of position out of
    position, and charges nobody, until a turnover does come.
    """
    if turnover_occurred and match.scoreboard.last_possession:
        return StepResult(
            narration=[lead_in] if lead_in else [],
            next=FollowOn(FollowOnStep.END_PERIOD),
        )

    if not turnover_occurred:
        return StepResult(
            narration=[lead_in] if lead_in else [],
            next=FollowOn(
                FollowOnStep.FINISH_MANEUVER_RESOLUTION,
                {
                    "distance_moved": distance_moved,
                    "turnover_occurred": False,
                },
            ),
        )

    # **Mind Pull, before anyone runs back.** `mind_pull_candidates`
    # reads current board occupancy of `last_ball_path`, so a
    # Telekinetic who merely runs back onto a space the ball crossed
    # must never be offered a pull meant for whoever actually stood
    # there when it moved. A maneuver that settles its own turnover and
    # reaches this directly (Steal, Intercept, a Defender's pressure
    # steal, an own goal avoided) never passes through the three
    # ordinary arrival gates, so this is the one place guaranteed to
    # run before positions change.
    taken = check_for_ball_arrival(
        engine,
        game,
        match,
        {
            "kind": "run_back",
            "distance_moved": distance_moved,
            "turnover_occurred": turnover_occurred,
            "new_play": new_play,
            "speed_choice_after": speed_choice_after,
            "speed_reset": speed_reset,
            "lead_in": lead_in,
        },
    )
    if taken is not None:
        return taken

    if new_play:
        # The ball is dead. Clearing here as well as in the reset is
        # what keeps the exemption below honest: a goal scored off a
        # High Pass set-up leaves the receiver still recorded as
        # carrying it, and they are not -- the ball is on its way back
        # to the kickoff space.
        match.clear_ball_carrier()

    match.pending_run_back = True
    match.pending_run_back_distance = distance_moved
    match.pending_run_back_turnover = turnover_occurred
    match.pending_run_back_stays_player_id = match.ball_carrier_id
    match.pending_run_back_speed_choice = speed_choice_after
    # **Charge-up is armed here and awarded at the end**, because who
    # actually moved is only known once the cascade has run -- a stack
    # is a real decision. A new play is not a run back and triggers
    # none, and this flag is what remembers that: `new_play` is not
    # persisted, and by the time the reset leaves nobody displaced the
    # cascade can no longer tell the two apart.
    match.run_back_moved = []
    match.pending_run_back_charge_up = not new_play

    if new_play:
        return StepResult(
            narration=[lead_in] if lead_in else [],
            next=FollowOn(
                FollowOnStep.OPEN_NEW_PLAY, {"speed_reset": speed_reset},
            ),
        )

    return StepResult(
        narration=[lead_in] if lead_in else [],
        next=FollowOn(
            FollowOnStep.ANNOUNCE_RUN_BACK, {"speed_reset": speed_reset},
        ),
    )


def after_new_play_reset_step(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    *,
    speed_reset: bool = True,
) -> StepResult:
    """
    What a new play does once both sides are back on their own
    arrangement: the window, or straight on to the run back.

    A coach who declares rearranges from their own formation rather
    than from wherever open play scattered them, and a coach who
    passes has already got what passing gives them. The reset also
    leaves nobody displaced, so the run back that follows finds
    nothing to do and falls through to whatever the restart still owes
    -- the kickoff space, an out-of-bounds pickup.

    It is a second step rather than a branch inside the first because
    the reset itself is a message and a pinned board, which is the
    frontend's; what is a rule is *whether the window opens*, and that
    is here.
    """
    winning_side = match.ball.possession
    if match.may_take_time_out(winning_side):
        return StepResult(
            next=FollowOn(
                FollowOnStep.BEGIN_SUBSTITUTION_WINDOW,
                {"side": winning_side},
            ),
        )
    return StepResult(
        next=FollowOn(
            FollowOnStep.ANNOUNCE_RUN_BACK, {"speed_reset": speed_reset},
        ),
    )


def run_back_announcement(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    speed_reset: bool = True,
) -> str:
    """
    What a run back is announced as, or `""` when there is nothing to
    say.

    With nobody displaced there is nothing to explain, and heading an
    empty run back "Players run back!" reads as a bug. That is every
    new play: the reset put both sides back on their own arrangement,
    so only the speed note is left.
    """
    turnover_occurred = match.pending_run_back_turnover
    # Speed manipulation (Steal) always happens after the run back now,
    # so a turnover's ball speed is still at its reset value of 1 here
    # -- except Dribble Burst's cost, whose caller passes
    # speed_reset=False because the ball kept the burst's own speed
    # instead, and that is already said in the lead-in this note would
    # otherwise contradict.
    speed_note = (
        "The ball speed goes down to **1**."
        if turnover_occurred and speed_reset
        else ""
    )
    displaced = any(
        engine.run_back_movers(game, match, side)
        for side in (TeamSide.HOME, TeamSide.VISITING)
    )
    if displaced:
        return (
            "# Players run back!\n"
            "Players return to an open space in their assigned zone and "
            "gain 1 exhaustion token for every space traveled. "
            f"{speed_note}"
        ).rstrip()
    return speed_note


def charge_up_note(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
) -> str:
    """
    Take a drain token off every Cyborg this run back leaves where
    they are, and word it -- or `""` when there is nobody to charge
    up, which is every game not playing the species abilities and most
    turns of the ones that are.

    Who qualifies is `RulesEngine.charge_up_players`; this is the
    removal and the sentence. The re-test matters: a Cyborg sitting on
    exactly 7 is Drained, and dropping to 6 clears it, so this goes
    through `recover_exhaustion` rather than decrementing the count by
    hand.
    """
    charged = engine.charge_up_players(game, match)
    if not charged:
        return ""

    lines = []
    for player_id in charged:
        player = engine.get_player_definition(player_id)
        removed = match.recover_exhaustion(
            player_id, 1, engine.exhaustion_threshold(game, player_id),
        )
        if not removed:
            continue
        remaining = match.exhaustion.get(player_id, 0)
        lines.append(
            f"{engine.format_player_label(match, player)} holds position — "
            f"**Charge-up** removes 1 drain "
            f"(now {remaining})."
        )
    return "\n".join(lines)


def run_back_ai_placement(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    side: TeamSide,
    candidates: list[str],
) -> str:
    """
    Place one of an AI side's run-backs and describe it: the line comes
    back for the cascade to batch with every other automatic
    placement.
    """
    # One candidate is a settled player and only the space is open;
    # several is a stack Dinky picks out of, the same call a coach is
    # given.
    player_id = (
        candidates[0]
        if len(candidates) == 1
        else engine.get_ai_strategy(game).choose_run_back_player(
            match, candidates,
        )
    )
    zone = match.setup_for_side(side).assigned_zone(player_id)
    player = engine.get_player_definition(player_id)
    exempt_ids = engine.spread_exempt_ids(game, match, side)
    space_index = engine.get_ai_strategy(game).choose_run_back_space(
        match.placement_spaces_in_zone(side, zone, player_id, exempt_ids)
    )
    distance = match.run_back_player(
        player_id, zone, space_index, exempt_ids,
    )
    exhaustion_text = engine.apply_exhaustion(
        game, match, player_id, distance,
    )

    return (
        f"{engine.format_player_label(match, player)} "
        f"runs back to {space_label(zone, space_index)}."
        f"\n{exhaustion_text}"
    )


def run_back_kickoff_fill(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
) -> tuple[bool, Optional[str]]:
    """
    Settle a pending kickoff fill, and say whether the cascade goes
    round again -- with the line describing the drop back, when
    somebody actually moved.

    A goal (or own goal) restarts play with nobody necessarily
    standing on the kickoff space -- the conceding side's two midfield
    players could easily both be elsewhere in the zone from open play.
    Whoever is closest drops back to start the kickoff, at the usual
    run-back cost, once every other run back is settled.

    Asked here rather than back at the restart because everyone has
    moved since: the new play's reset, and any placement its
    substitution window made. Somebody standing on the space already
    settles it for nothing.
    """
    if match.eligible_ball_handlers():
        match.pending_kickoff_fill = False
        return True, None

    candidates = match.kickoff_fill_candidates()
    if candidates:
        player_id = candidates[0]
        player = engine.get_player_definition(player_id)
        distance = match.fill_kickoff(player_id)
        exhaustion_text = engine.apply_exhaustion(
            game, match, player_id, distance,
        )

        return True, (
            f"{engine.format_player_label(match, player)} "
            "drops back to "
            f"{space_label(match.ball.zone, match.ball.space_index)} "
            f"to start the kickoff.\n{exhaustion_text}"
        )

    # Nobody fielded in midfield at all (both benched or injured) --
    # nothing to place. Clear the flag and let the loose-ball check
    # downstream deal with it.
    match.pending_kickoff_fill = False
    return False, None


def run_back_passes(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    max_passes: int,
) -> Iterator[StepResult]:
    """
    The cascade, a pass at a time.

    **A generator rather than a step**, and that is the one place this
    phase departs from the shape. Every pass either places somebody or
    ends the cascade, and whether it needs a coach is only known once
    it has run -- so a single `StepResult` could not say "these four
    placements happened and then somebody has to choose". What comes
    back instead is one result per pass: a placement's line in
    `narration`, or `next` naming the question a coach is owed, after
    which the generator is finished.

    **The caller saves after every pass**, which is the one named
    exception to principle 9 and the reason this is a generator at
    all. When a pass ends on a coach's question the turn is handed to
    a click that reloads the match out of the save file, so that
    pass's placements have to already be on disk. Collapsing it to one
    save after the loop loses the placements of every cascade that
    stops to ask.

    - **The give-up branch is not that path**, though it reads like
      it. Running out of passes stops the generator normally, and the
      caller goes on to flush and finish -- which saves. Worth writing
      down because the branch *looks* like the fragile one and is the
      safe one, and the genuinely fragile path has no log line drawing
      attention to itself. The caller counts the passes it was given
      and logs if it used them all.
    """
    for _ in range(max_passes):
        engine.apply_forced_run_backs(game, match)

        step = engine.next_run_back_step(game, match)

        if step is not None:
            side, candidates = step

            if engine.side_is_ai(game, side):
                yield StepResult(
                    narration=[
                        run_back_ai_placement(
                            engine, game, match, side, candidates,
                        )
                    ],
                )
                continue

            # A coach's choice ends the cascade here.
            yield StepResult(
                next=FollowOn(
                    FollowOnStep.ASK_RUN_BACK,
                    {"side": side, "candidates": list(candidates)},
                ),
            )
            return

        if match.pending_kickoff_fill:
            keep_going, note = run_back_kickoff_fill(engine, game, match)
            result = StepResult(narration=[note] if note else [])
            if keep_going:
                yield result
                continue
            yield result
            return

        return


def finish_run_back_step(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    *,
    lead_in: str = "",
) -> StepResult:
    """
    Nobody is displaced on either side: clear the run back and hand
    the turn on to whatever it was still holding up.
    """
    match.pending_run_back = False
    distance_moved = match.pending_run_back_distance
    turnover_occurred = match.pending_run_back_turnover
    speed_choice_after = match.pending_run_back_speed_choice
    stays_player_id = match.pending_run_back_stays_player_id
    match.pending_run_back_speed_choice = False

    # **Charge-up, now that everybody who was going to move has.** It
    # rides on `lead_in` rather than being said on its own: this is the
    # tail of a cascade that has been batching all the way down, and a
    # line about drain tokens does not earn a message of its own.
    if match.pending_run_back_charge_up:
        match.pending_run_back_charge_up = False
        charge_up = charge_up_note(engine, game, match)
        if charge_up:
            lead_in = "\n\n".join(filter(None, (lead_in, charge_up)))
    match.run_back_moved = []

    narration = [lead_in] if lead_in else []

    if match.pending_ball_recovery:
        # An out-of-bounds ball is still lying there with nobody on it.
        # Now that everyone is back in position, the side that won it
        # sends the nearest player either side of it, at the usual
        # per-space cost.
        return StepResult(
            narration=narration,
            next=FollowOn(FollowOnStep.BEGIN_BALL_RECOVERY),
        )

    if speed_choice_after:
        # Steal: the defender who stole the ball still gets to
        # manipulate its speed, now that everyone is back in position.
        return StepResult(
            narration=narration,
            next=FollowOn(
                FollowOnStep.OFFER_SPEED_CHOICE,
                {
                    "player_id": stays_player_id,
                    "skill_type": "defense",
                    "turnover_occurred": turnover_occurred,
                    "distance_moved": distance_moved,
                },
            ),
        )

    # The run back itself only ever costs exhaustion, not time -- the
    # time cost is whatever the triggering maneuver's own ball movement
    # was, stashed when the run back began.
    return StepResult(
        narration=narration,
        next=FollowOn(
            FollowOnStep.FINISH_MANEUVER_RESOLUTION,
            {
                "distance_moved": distance_moved,
                "turnover_occurred": turnover_occurred,
            },
        ),
    )


def ball_recovery_step(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    *,
    lead_in: str = "",
) -> StepResult:
    """
    Ask the side that won an out-of-bounds ball, or called a time out,
    which of their players goes and stands on it: the nearest either
    side of it, from any zone, at one exhaustion token per space
    traveled. It is the same choice a loose ball and a challenge put,
    and since 2026-08-16 it is the same pool.

    Deliberately the last thing that happens: both callers reset
    everyone to their arrangement first, so this player is placed once
    and stays, where placing them before it would only have them run
    back off the ball and leave it loose all over again.

    **Which is also why it asks whether there is anything to do.** A
    reset can perfectly well put one of the gaining side on the ball's
    space by itself -- that is the arrangement's own doing, and the
    rules ask for a pickup "unless one of theirs is already on it".
    """
    side = match.ball.possession
    candidates = (
        [] if match.eligible_ball_handlers()
        else match.contest_candidates(side)
    )
    narration = [lead_in] if lead_in else []

    if not candidates:
        # Somebody of theirs is already standing on it, or nobody is
        # fielded at all. Either way nothing is placed: let the
        # loose-ball check downstream deal with it, the same way an
        # empty kickoff is handled.
        match.pending_ball_recovery = False
        return StepResult(
            narration=narration,
            next=FollowOn(
                FollowOnStep.FINISH_MANEUVER_RESOLUTION,
                {
                    "distance_moved": match.pending_run_back_distance,
                    "turnover_occurred": True,
                },
            ),
        )

    if engine.side_is_ai(game, side):
        # Nearest, not best: this walk costs a token per space and wins
        # nothing, so the only thing worth optimizing is how much it
        # costs.
        return StepResult(
            narration=narration,
            next=FollowOn(
                FollowOnStep.APPLY_BALL_RECOVERY,
                {"player_id": min(candidates, key=match.distance_to_ball)},
            ),
        )

    return StepResult(
        narration=narration,
        next=FollowOn(FollowOnStep.ASK_BALL_RECOVERY),
    )
