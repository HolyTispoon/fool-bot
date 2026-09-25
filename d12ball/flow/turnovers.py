"""
Running back after a turnover, and the pickup an out-of-bounds ball
owes, as flow steps.

Lifted in Phase 4 of docs/design/model-discord-split.md out of
`cogs/d12ball/turnovers.py`. See "Turnovers, resets, and running back"
in docs/design/possession-and-turnovers.md for what a run back is and
who is exempt from one.

**Two things deliberately stayed in the cog**, and both are principle 8
-- the frontend owns batching, and therefore owns the rate limits:

- the cascade's **batching**. `run_back_passes` below yields one
  `StepResult` per pass; that a dozen automatic placements become one
  message and one board refresh is a Discord economy, and a web app
  with no five-in-five bucket should not inherit the shape.
- the run-back prompt's **field strip**. The question, the candidates
  and the wording are all here; that the question is worth a picture
  is the frontend's call.

**And one exception to principle 9**, which is the important one:

**the cascade persists per pass, and must.** When
`next_run_back_step` comes back with a question the cascade stops there
and the turn is left waiting on a click that reloads the match out of
the save file -- so that pass's placements have to already be on disk
before the prompt goes out. Collapsing it to one save after the loop
loses the placements on every cascade that stops to ask. Yielding a
result per pass is what keeps that possible once the loop is here and
the saving is the caller's: the caller persists after each.

The give-up-after-`MAX_RUN_BACK_PASSES` branch is **not** that path,
though it reads like one: it leaves the loop rather than returning from
inside it, and `finish_run_back` persists after it. Its log line ("the
match is saved as it stands") is kept by that save whatever happens to
the per-pass one. Worth writing down because the branch *looks* like
the fragile one and is the safe one, and the genuinely fragile path has
no log line drawing attention to itself.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Iterator, Optional

from d12ball.components import MatchState, RuleRefusal, TeamSide
from d12ball.engine import RulesEngine
from d12ball.flow.result import FollowOn, FollowOnStep, StepResult
from d12ball.formatting import (
    address_coach,
    ball_space_label,
    format_player_with_team,
    space_label,
)
from d12ball.game import D12BallGame
from d12ball.prompts import PendingPrompt, PromptKind, run_back_prompt

LOGGER = logging.getLogger(__name__)

#: Every pass either places somebody or ends the cascade, so the budget
#: can only be reached if a placement left the player it moved still
#: owed one. That should not be possible -- see
#: `MatchState.placement_spaces_in_zone` -- but as a recursion it was
#: bounded by the interpreter and as a loop it is not, and a spin here
#: hangs the event loop for every game at once.
MAX_RUN_BACK_PASSES = 60


def begin_run_back(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    distance_moved: int = 1,
    turnover_occurred: bool = True,
    new_play: bool = False,
    speed_choice_after: bool = False,
    speed_reset: bool = True,
    lead_in: str = "",
) -> StepResult:
    """
    `distance_moved`/`turnover_occurred` describe the maneuver that
    triggered this run-back, stashed on `match` so they survive the
    multi-turn choice flow and reach `finish_maneuver_resolution`
    correctly once run-back itself (which only ever costs exhaustion,
    never time) is done.

    `speed_reset` is `announce_run_back`'s own note, and only ever
    False for Dribble Burst's cost: every caller has already set
    `match.ball.speed` to whatever it should read by the time this
    runs, so this is wording, not state.

    `new_play` says the ball changed hands because play stopped and is
    restarting -- a goal, an own goal, a missed attempt, a ball out of
    bounds -- rather than because the other team took it off them. Only
    a new play opens a substitution window; a steal runs everyone back
    and plays straight on. See "Steals and new plays" in
    docs/living-rules.md. It is not persisted: it is consumed here, and
    by the time anything is saved the state already says which of the
    two happened.

    **The player holding the ball does not run back**, whoever they
    are. The exemption is read off `ball_carrier_id` rather than passed
    in, because the two are the same fact: a run back that moved the
    ball's holder would run them off the ball and charge them for it.

    A new play exempts nobody: the ball went dead, so nobody is
    carrying it, and the reset that follows moves both sides whatever
    they were doing.

    A turnover that happens while last possession is already in force
    ends the period immediately instead: no run-back, no substitution
    window, and (for a steal) no speed-manipulation follow-up either.
    The maneuver that *declares* last possession is not that turnover
    and is not caught here: its own clock advance happens later, in
    `finish_maneuver_resolution`, so it runs back like any other.

    A resolution that left possession where it was does not run a run
    back at all: "every time there's a turnover for any reason (steal,
    goal etc.) players have to run back" is the whole of when one
    happens. Keeping the ball leaves whoever is out of position out of
    position, and charges nobody, until a turnover does come.
    """
    narration = [lead_in] if lead_in else []

    if turnover_occurred and match.scoreboard.last_possession:
        return StepResult(
            narration=narration,
            next=FollowOn(FollowOnStep.END_PERIOD),
        )

    if not turnover_occurred:
        return StepResult(
            narration=narration,
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
    # calls this directly (Steal, Intercept, a Defender's pressure
    # steal, an own goal avoided) never passes through the three
    # ordinary arrival gates, so this is the one place guaranteed to
    # run before positions change.
    from d12ball.flow.arrivals import check_for_ball_arrival

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
        # The ball is dead. Clearing here as well as in
        # `announce_new_play_reset` is what keeps the exemption below
        # honest: a goal scored off a High Pass set-up leaves the
        # receiver still recorded as carrying it, and they are not --
        # the ball is on its way back to the kickoff space.
        match.clear_ball_carrier()

    match.pending_run_back = True
    match.pending_run_back_distance = distance_moved
    match.pending_run_back_turnover = turnover_occurred
    match.pending_run_back_stays_player_id = match.ball_carrier_id
    match.pending_run_back_speed_choice = speed_choice_after
    # **Charge-up is armed here and awarded at the end**, because who
    # actually moved is only known once the cascade has run -- a stack
    # is a real decision (see `charge_up_players`). A new play is not a
    # run back and triggers none, and this flag is what remembers that:
    # `new_play` is not persisted, and by the time the reset leaves
    # nobody displaced the cascade can no longer tell the two apart.
    match.run_back_moved = []
    match.pending_run_back_charge_up = not new_play

    # A new play resets both sides to the shape their coaches set, free
    # of exhaustion, and only then opens the substitution window -- a
    # coach who declares rearranges from their own formation rather
    # than from wherever open play scattered them, and a coach who
    # passes has already got what passing gives them. It also leaves
    # nobody displaced, so the run back that follows finds nothing to
    # do and falls through to whatever the restart still owes (the
    # kickoff space, an out-of-bounds pickup).
    #
    # A steal does none of this: the ball is still live, so the coaches
    # get no pause and the ordinary run back stands.
    if new_play:
        # The reset is its own message -- it is the one the board is
        # pinned to -- so it does not carry the run-back note that
        # follows it. `ANNOUNCE_RUN_BACK` is how the two stay apart;
        # see `D12Ball.post_then_dispatch`.
        reset = announce_new_play_reset(engine, game, match, lead_in)
        # **Unconditionally.** "Every new play offers the side
        # restarting play a Coaching Choice, however many they have
        # already had this half, and it costs nothing" -- see "A new
        # play always offers one" in docs/living-rules.md. This used
        # to be gated on `may_take_time_out(winning_side)`, which was
        # right while a new play's declaration and the ceded ball
        # shared one once-a-half count and wrong from the moment they
        # stopped (2026-09-16): a coach who had spent their time out
        # was silently skipped past every later restart in the half.
        # What bounds coaching in open play is the two substitutions
        # (`CoachingOccasion.counts_against_the_half`), and a window
        # with no swaps left in it is still a rearrangement.
        reset.next = FollowOn(
            FollowOnStep.BEGIN_SUBSTITUTION_WINDOW,
            {"side": match.ball.possession},
        )
        return reset

    return StepResult(
        narration=narration,
        next=FollowOn(
            FollowOnStep.ANNOUNCE_RUN_BACK, {"speed_reset": speed_reset},
        ),
    )


def announce_new_play_reset(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    lead_in: str = "",
) -> StepResult:
    """
    Put both sides back on the arrangement their coaches last set and
    say so. Nobody pays a token for it -- see
    `MatchState.restore_assigned_positions`.

    This is where a new play's board goes out and gets pinned: the
    reset is the arrangement the play starts from, and it is the one
    moment in the restart where nothing is still moving. What the
    restart still owes (a kickoff fill, an out-of-bounds pickup) lands
    on the persistent board afterwards. That the board is *pinned* here
    rather than merely redrawn is the frontend's (`post_new_play_board`
    is the only pinning site in the game); what this says is that the
    play is starting again.
    """
    # The ball went dead and is being brought back into play, so nobody
    # is carrying it -- whoever ends up on it chooses.
    match.clear_ball_carrier()
    # **A new play is the one thing that ends a Double Team**, and the
    # card says so outright: "so long as it's not a new play, on their
    # next maneuver, both defending players challenge". Cleared here
    # rather than in `reset_maneuver`, which runs at the end of every
    # turn -- including the turn that set it.
    match.pending_double_team = []
    moved: list[str] = []
    for side in (TeamSide.HOME, TeamSide.VISITING):
        for player_id, zone, space_index in (
            match.restore_assigned_positions(side)
        ):
            player = engine.get_player_definition(player_id)
            moved.append(
                f"{engine.format_player_label(match, player)} to "
                f"{space_label(zone, space_index, match.board)}"
            )

    prefix = f"{lead_in}\n\n" if lead_in else ""
    body = (
        "Both teams reset to the positions their coaches last "
        "set:\n" + "\n".join(moved)
        if moved
        else "Players return to positions assigned by their coach."
    )
    return StepResult(
        narration=[f"{prefix}# New play\n{body}"],
        board_changed=True,
        new_play=True,
    )


def announce_run_back(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    lead_in: str = "",
    speed_reset: bool = True,
) -> StepResult:
    """
    The run back proper, split out of `begin_run_back` because a new
    play's substitution window sits in between and has to resolve
    before this can start.

    With nobody displaced there is nothing to explain, and heading an
    empty run back "Players run back!" reads as a bug. That is every
    new play: the reset put both sides back on their own arrangement,
    so only the speed note is left to say.
    """
    turnover_occurred = match.pending_run_back_turnover
    prefix = f"{lead_in}\n\n" if lead_in else ""
    # Speed manipulation (Steal) always happens after run-back now, so
    # a turnover's ball speed is still at its reset value of 1 here --
    # except Dribble Burst's cost, whose caller passes
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
    narration: list[str] = []
    if displaced:
        narration.append(
            f"{prefix}# Players run back!\n"
            "Players return to an open space in their assigned zone and "
            "gain 1 exhaustion token for every space traveled. "
            f"{speed_note}".rstrip()
        )
    elif prefix or speed_note:
        narration.append(f"{prefix}{speed_note}".strip())

    return StepResult(
        narration=narration,
        next=FollowOn(FollowOnStep.CONTINUE_RUN_BACK),
    )


def run_back_passes(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
) -> Iterator[StepResult]:
    """
    The cascade, one pass at a time.

    Auto-place every forced run-back (no real choice: the open spaces
    in a zone exactly match the players who need one), then the drop
    back that fills an empty kickoff -- yielding a result for each. A
    pass a coach has to answer yields a result carrying the prompt and
    **ends the generator**; a cascade that runs out of work ends it
    with a result naming `FINISH_RUN_BACK`. An AI side's pick is the
    same prompt, answered through the service (`AIStrategy.choose`);
    until step 7 of docs/architecture-migration.md the cascade placed
    for it here.

    **The caller persists after every yield**, which is the exception
    to principle 9 this module's docstring is about: a pass that ends
    on a question leaves the turn waiting on a click that reloads the
    match off disk, so that pass's placements have to be written before
    the prompt goes out. A generator is what lets the loop live here
    and the saving stay the caller's.

    A result with empty narration and no `next` is a pass that changed
    state and had nothing to say (an empty kickoff fill). The caller
    still saves it.
    """
    remaining_passes = MAX_RUN_BACK_PASSES

    while True:
        remaining_passes -= 1
        if remaining_passes < 0:
            LOGGER.error(
                "Giving up on the run back for D12 Ball game %s after "
                "%d placements: it is not settling. The match is saved "
                "as it stands.",
                game.game_id,
                MAX_RUN_BACK_PASSES,
            )
            break

        engine.apply_forced_run_backs(game, match)

        step = engine.next_run_back_step(game, match)

        if step is not None:
            side, candidates = step

            # A coach's choice ends the cascade here.
            yield StepResult(
                next=run_back_choice_prompt(engine, game, match, side),
            )
            return

        if match.pending_kickoff_fill:
            keep_going, note = run_back_kickoff_fill(engine, game, match)
            yield StepResult(narration=[note] if note else [])
            if keep_going:
                continue

        break

    yield StepResult(next=FollowOn(FollowOnStep.FINISH_RUN_BACK))


def continue_run_back(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    lead_in: str = "",
) -> StepResult:
    """
    Drive the cascade and **batch what it says**.

    The loop is `run_back_passes`, one `StepResult` a pass. Every
    placement made without asking anyone -- the forced ones, the AI's
    choices, the drop back that fills an empty kickoff -- collects into
    one block, which the frontend posts as one message with one board
    behind it, and the cascade stops where it reaches a coach's choice
    or runs out. It used to post a message and re-upload the board per
    player, which after a steal that scatters a 4-1-1 side is a
    dozen-odd REST calls into one channel with nothing between them,
    and enough to be rate limited for it. Nobody is reading the
    intermediate boards anyway.

    **The per-pass persist is gone with Phase 6**, and this is the one
    place principle 9 had a named exception: the cog saved after every
    yield because a pass that ended on a question left the turn
    waiting on a click that reloaded the match off disk. The driver's
    caller saves once after the whole run and before anything is
    posted, which is the same guarantee one write later.

    `lead_in` only ever applies to the first thing this says -- every
    call site that already consumed it passes none.
    """
    notes: list[str] = []
    board_changed = False
    following = None

    for result in run_back_passes(engine, game, match):
        notes.extend(result.narration)
        board_changed = board_changed or bool(result.narration)
        if result.next is not None:
            following = result.next
            # A coach's choice is asked over the board as it stands,
            # so the persistent message is settled in front of it
            # whether or not this pass moved anybody -- the cascade
            # always wrote it there.
            board_changed = board_changed or isinstance(following, PendingPrompt)
            break

    prefix = f"{lead_in}\n\n" if lead_in else ""
    body = "\n".join(notes)
    narration = [f"{prefix}{body}"] if body else ([lead_in] if lead_in else [])
    return StepResult(
        narration=narration,
        board_changed=board_changed,
        next=following,
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

    A goal (or own goal) restarts play with nobody necessarily standing
    on the kickoff space -- the conceding side's two midfield players
    could easily both be elsewhere in the zone from open play. Whoever
    is closest drops back to start the kickoff, at the usual run-back
    cost, once every other run-back is settled.

    Asked here rather than back in `restart_after_goal` because
    everyone has moved since: the new play's reset, and any placement
    its substitution window made. Somebody standing on the space
    already settles it for nothing.
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
            f"{ball_space_label(match)} "
            f"to start the kickoff.\n{exhaustion_text}"
        )

    # Nobody fielded in midfield at all (both benched or injured) --
    # nothing to place. Clear the flag and let the loose-ball check
    # downstream handle the empty kickoff.
    match.pending_kickoff_fill = False
    return False, None


def run_back_choice_prompt(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    side: TeamSide,
) -> Optional[PendingPrompt]:
    """
    Whichever of the run back's two questions this coach is owed, with
    the coach named in front of it.

    **A `PendingPrompt` since Phase 6.** It was `SEND_RUN_BACK_PROMPT`
    until then, and not because the question could not be one --
    `run_back_prompt` has answered it from match state since Phase 1,
    and a restart comes back through it -- but because the prompt
    carries **the field strip**, and a `PendingPrompt` has nowhere to
    put a picture. It still has not: the strip is attached by
    `D12Ball.post_run_back_prompt`, keyed on the kind, which is the
    frontend deciding how a question reaches a person (principle 2).

    Which of the two it is is `run_back_prompt`'s reading and is not
    repeated here; what this adds is the mention, because a message
    naming a coach is a message and `pending_prompt` words the bare
    question a restart falls back to.
    """
    prompt = run_back_prompt(engine, game, match)
    if prompt is None:  # pragma: no cover - the caller has just read it
        return None

    mention = address_coach(engine.side_player_number(game, side))
    if prompt.kind is PromptKind.RUN_BACK_SPACE:
        ask = run_back_space_ask(
            engine, game, match, side, prompt.player_id, mention,
        )
    else:
        ask = run_back_player_ask(
            engine, match, side, prompt.player_ids, mention,
        )
    return replace(prompt, ask=ask)


def run_back_space_ask(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    side: TeamSide,
    player_id: str,
    mention: str,
) -> str:
    """
    Where does this player run back to -- the question every run back
    ends on, whether the player was displaced or has just been picked
    out of a stack. It is a function rather than a string at the call
    site because those are two different places: the cascade asks it
    directly, and `RunBackPlayerChoiceView` asks it again over the top
    of its own answer, and the two have to word it identically.
    """
    player = engine.get_player_definition(player_id)
    return (
        f"{mention}, choose where "
        f"{engine.format_player_label(match, player)} runs back "
        "to:\n"
        f"{engine.describe_run_back_options(game, match, side, player_id)}"
    )


def run_back_player_ask(
    engine: RulesEngine,
    match: MatchState,
    side: TeamSide,
    candidates: list[str],
    mention: str,
) -> str:
    """
    Which of a stack runs back, and where each of them is standing -- a
    coach choosing between two teammates on one space is choosing which
    of them pays for the walk, so the prompt says who they are rather
    than leaving it to the buttons alone.
    """
    lines = []
    for player_id in candidates:
        player = engine.get_player_definition(player_id)
        position = match.board.meeple_position(player_id)
        lines.append(
            f"{engine.format_player_label(match, player)} on "
            f"{space_label(*position, match.board)}"
            if position is not None
            else engine.format_player_label(match, player)
        )
    return (
        f"{mention}, your players are doubled up while their zone "
        "still has a space with nobody on it — choose which of them "
        "runs back:\n" + "\n".join(lines)
    )


def apply_charge_up(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
) -> str:
    """
    Take a drain token off every Cyborg this run back leaves where they
    are, and word it -- or "" when there is nobody to charge up, which
    is every game not playing the species abilities and most turns of
    the ones that are.

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
            player_id,
            engine.charge_up_amount(game, player_id),
            engine.exhaustion_threshold(game, player_id),
        )
        if not removed:
            continue
        remaining = match.exhaustion.get(player_id, 0)
        lines.append(
            f"{engine.format_player_label(match, player)} holds position — "
            f"**Charge-up** removes {removed} drain "
            f"(now {remaining})."
        )
    return "\n".join(lines)


def finish_run_back(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    lead_in: str = "",
) -> StepResult:
    """
    Nobody is displaced on either side: clear the run back and hand the
    turn on to whatever it was still holding up.
    """
    match.pending_run_back = False
    match.run_back_pick = None
    distance_moved = match.pending_run_back_distance
    turnover_occurred = match.pending_run_back_turnover
    speed_choice_after = match.pending_run_back_speed_choice
    stays_player_id = match.pending_run_back_stays_player_id
    match.pending_run_back_speed_choice = False

    # **Charge-up, now that everybody who was going to move has.** It
    # rides on `lead_in` rather than being sent on its own: this is the
    # tail of a cascade that has been batching its messages all the way
    # down, and a line about drain tokens does not earn a message of
    # its own.
    if match.pending_run_back_charge_up:
        match.pending_run_back_charge_up = False
        charge_up = apply_charge_up(engine, game, match)
        if charge_up:
            lead_in = "\n\n".join(filter(None, (lead_in, charge_up)))
    match.run_back_moved = []

    narration = [lead_in] if lead_in else []

    if match.pending_ball_recovery:
        # An out-of-bounds ball is still lying there with nobody on it.
        # Now that everyone is back in position, the side that won it
        # sends the nearest player either side of it, at the usual
        # per-space cost.
        recovery = begin_ball_recovery(engine, game, match, lead_in=lead_in)
        return recovery

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

    # Run-back itself only ever costs exhaustion, not time -- the time
    # cost is whatever the triggering maneuver's own ball movement was,
    # stashed by `begin_run_back`.
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


def begin_ball_recovery(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    lead_in: str = "",
) -> StepResult:
    """
    Ask the side that won an out-of-bounds ball, or called a time out,
    which of their players goes and stands on it: the nearest either
    side of it, from any zone, at one exhaustion token per space
    travelled. It is the same choice a loose ball and a challenge put,
    and since 2026-08-16 it is the same pool.

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
            narration=[lead_in] if lead_in else [],
            next=FollowOn(
                FollowOnStep.FINISH_MANEUVER_RESOLUTION,
                {
                    "distance_moved": match.pending_run_back_distance,
                    "turnover_occurred": True,
                },
            ),
        )

    number = (
        game.home_player_number
        if side == TeamSide.HOME
        else game.visiting_player_number
    )
    mention = format_player_with_team(
        game, number, mention=True,
    )
    return StepResult(
        narration=[lead_in] if lead_in else [],
        next=PendingPrompt(
            PromptKind.BALL_RECOVERY,
            f"{mention}, everyone is back in position -- send "
            "the nearest player either side of the ball to pick it up "
            f"at {ball_space_label(match)}:",
        ),
    )


# -- Answering the run back's own prompts ------------------------------
#
# Phase 6 of docs/design/model-discord-split.md. Both were the view's until
# now -- `RunBackPlayerChoiceView.choose` and `RunBackChoiceView.choose`
# in `cogs/d12ball_views/runback.py` -- and each mixed the rule with
# the edit that renders it. The rule is here; the field strip the
# question is asked over stays the frontend's.


def run_back_player_step(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    *,
    player_id: str,
) -> StepResult:
    """
    Which of a doubled-up pair runs back -- the answer to the first of
    the run back's two questions.

    **It moves nobody, and it is still a change to the match**: the
    pick narrows the second question and is not itself a move, and
    `MatchState.run_back_pick` is where it is written down, so that
    `run_back_prompt` reads the position back as "where" for this
    player from here on. Until Phase 6 of docs/design/model-discord-split.md
    it lived on the prompt and nowhere else -- a restart asked "who"
    again, and the driver refused the "where" that followed as a
    question the match had moved on from, because the model's own
    reading still said "who". Raises `ValueError` for a player the
    position is not asking about, which is the stale click on a stack
    the board has moved out from under.
    """
    side = (
        TeamSide.HOME
        if player_id in match.home.field_players
        else TeamSide.VISITING
    )
    if player_id not in engine.run_back_crowded(game, match, side):
        raise RuleRefusal("They no longer have to run back.")
    match.run_back_pick = player_id
    return StepResult(
        next=PendingPrompt(
            PromptKind.RUN_BACK_SPACE,
            run_back_space_ask(
                engine,
                game,
                match,
                side,
                player_id,
                # The bare address the view has always used here, not
                # the mark-and-name one the cascade's own prompt
                # carries: this question is an edit of the one above it
                # and the coach has already been named there.
                address_coach(
                    engine.controlling_player_number(game, match, player_id),
                ),
            ),
            player_id=player_id,
        ),
    )


def run_back_space_step(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    *,
    player_id: str,
    space_index: int,
) -> StepResult:
    """
    Run one player back to a space in their own zone, and charge them
    for the walk.

    Raises `ValueError` where the space is not one they may take, which
    is `MatchState.run_back_player`'s own refusal, left to propagate
    for `select_ball_handler_step`'s reason.

    The cascade carries on from `CONTINUE_RUN_BACK`, whose batching of
    the automatic placements behind this one is a Discord economy and
    stays the frontend's (principle 8).
    """
    side = (
        TeamSide.HOME
        if player_id in match.home.field_players
        else TeamSide.VISITING
    )
    zone = match.setup_for_side(side).assigned_zone(player_id)
    distance = match.run_back_player(
        player_id,
        zone,
        space_index,
        engine.spread_exempt_ids(game, match, side),
    )
    # The pick is spent by the move it narrowed the question to.
    match.run_back_pick = None
    exhaustion_text = engine.apply_exhaustion(
        game,
        match,
        player_id,
        engine.run_back_cost(game, player_id, distance),
    )
    player = engine.get_player_definition(player_id)
    return StepResult(
        narration=[
            f"{engine.format_player_label(match, player)} "
            f"runs back to {space_label(zone, space_index, match.board)}."
            f"\n{exhaustion_text}",
        ],
        board_changed=True,
        next=FollowOn(FollowOnStep.CONTINUE_RUN_BACK),
    )


def recover_ball_step(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    *,
    player_id: str,
    lead_in: str = "",
) -> StepResult:
    """
    Send somebody to pick an out-of-bounds ball up, and carry on from
    where the maneuver that put it there left off.

    `distance_moved` is the triggering maneuver's own travel, for the
    clock. It outlives the run back that just finished -- only
    `reset_maneuver` clears it -- precisely so this step, which can
    span a restart, can still read it back.

    **A time out's pickup is the one walk to the ball that charges
    nothing**, and it is not a turnover either: the side fetching the
    ball is the side that has had it all along, so nothing resets and
    nothing ends. Read before the pickup clears it. See
    `finish_time_out`.
    """
    player = engine.get_player_definition(player_id)
    distance_moved = match.pending_run_back_distance
    from_time_out = match.pending_recovery_from_time_out
    distance = match.recover_out_of_bounds_ball(player_id)
    exhaustion_text = (
        "" if from_time_out
        else engine.apply_exhaustion(game, match, player_id, distance)
    )

    prefix = f"{lead_in}\n\n" if lead_in else ""
    # Joined rather than interpolated: a free pickup has no exhaustion
    # line at all, and interpolating one would leave a blank line under
    # the sentence. See "What a message says".
    return StepResult(
        narration=[
            "\n".join(
                part for part in (
                    f"{prefix}"
                    f"{engine.format_player_label(match, player)} picks "
                    "the ball up at "
                    f"{ball_space_label(match)}.",
                    exhaustion_text,
                ) if part
            ),
        ],
        board_changed=True,
        next=FollowOn(
            FollowOnStep.FINISH_MANEUVER_RESOLUTION,
            {
                "distance_moved": distance_moved,
                "turnover_occurred": not from_time_out,
            },
        ),
    )
