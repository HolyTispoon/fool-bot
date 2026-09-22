"""
Where a ball that has moved is settled, as flow steps.

**The gates and the arrivals they guard are one module because they are
one ordering.** `check_for_ball_arrival` runs Smooth and then Mind Pull;
`check_for_loose_ball` asks whether anybody of the possessing side is
standing where the ball came down; and the five arrival points each open
with one or both. Which runs first, and which of the two spends
`last_ball_path`, is a rule -- see "Mind Pull, and the arrival gate" and
"Smooth" in docs/design/species-abilities.md. Splitting the ordering
across the seam would have been worse than not moving it, so Phase 4 of
docs/design/model-discord-split.md moved it whole.

**The one sentence to keep in mind reading this file**: *the path is
spent whether or not anybody may pull*, before the early return. Two
gates run in a row on an ordinary path -- `finish_maneuver_resolution`
gates and then calls `check_for_loose_ball`, which reaches the second
gate -- and an unconditional spend is what stops one movement being
offered twice.

**A gate returns `Optional[StepResult]`**: a `StepResult` when it took
over, `None` when it did not. That keeps the caller the one
`if ...: return` it has always been, and it is why these are not
`StepResult`-returning like everything else here.

**`begin_loose_ball` in this module is the cog's old one**, the flow
step; `MatchState.begin_loose_ball` in d12ball/components.py is the
model's own state change and is what this calls into. They are two
different things with one name and the shorter one is the older.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, replace
from typing import Optional

from d12ball.components import (
    MIND_PULL_SUCCESS_FACES,
    MIND_PULL_TOKEN_COST,
    MatchState,
    RuleRefusal,
    SPECIES_TELEKINETIC,
    TeamSide,
)
from d12ball.engine import RulesEngine
from d12ball.flow.result import FollowOn, FollowOnStep, StepResult
from d12ball.formatting import (
    HIGH_PASS_CONTEST_HEADLINE,
    ball_location_line,
    ball_space_phrase,
    contest_noun,
    format_team_side_label,
    get_species_ability_emoji,
    space_label,
)
from d12ball.game import D12BallGame
from d12ball.prompts import (
    SCORE_ATTEMPT_ASK,
    PendingPrompt,
    PromptKind,
    loose_ball_pick_prompt,
    scoring_opportunity_prompt,
    shooter_mention,
)


# -- The two gates ---------------------------------------------------


def check_for_ball_arrival(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    resume: dict,
) -> Optional[StepResult]:
    """
    **The one gate every ball arrival runs through.** Smooth first,
    then Mind Pull; a `StepResult` when either took over, so a caller
    is one `if ...: return` exactly as it was when Mind Pull was the
    whole of it.

    **Smooth is asked first, and that is a rule rather than an ordering
    convenience.** Both read the same `last_ball_path`, and a Smooth
    that is taken stops the ball short of where the movement was going
    -- so whichever is asked first decides whether the other is asked
    at all. Asking the possessing side first means their own
    Telekinetic can take the ball off a movement before an opponent's
    gets to reach for it (the author, 2026-09-20).

    **The path is spent by `check_for_mind_pull`, which is the last
    reader**, so Smooth deliberately does not clear it -- a Smooth that
    nobody wanted must still leave the pull its movement.

    `resume` is the arrival this interrupted, as `{"kind": ..., ...}`:
    a coach may take minutes over the offer, and between the interrupt
    and the answer nothing else on the match says what the ball was
    about to do.
    """
    taken = check_for_smooth(engine, game, match, resume)
    if taken is not None:
        return taken
    return check_for_mind_pull(engine, game, match, resume)


def check_for_smooth(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    resume: dict,
) -> Optional[StepResult]:
    """
    Did the ball just move to or through one of its **own** side's
    Telekinetics, who may take it over? The twin of
    `check_for_mind_pull`, and the same contract.

    **It does not spend the path.** `check_for_mind_pull` runs after it
    on the same movement and needs it -- see `check_for_ball_arrival`.
    That is the one way the two gates differ mechanically, and it is
    why they are not the same function with a side argument.
    """
    candidates = engine.smooth_candidates(game, match)
    if not candidates:
        return None

    match.pending_smooth = candidates
    match.pending_smooth_resume = resume
    return continue_smooth(engine, game, match)


def check_for_mind_pull(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    resume: dict,
) -> Optional[StepResult]:
    """
    Did the ball just cross an opposing Telekinetic who may pull it in?

    Mind Pull "resolves before the ball settles", so this sits at the
    top of the five functions that settle an arrival:
    `finish_maneuver_resolution` (the tail of every ordinary path,
    receptions included), `begin_loose_ball` (a Deflect, which calls it
    directly, and the High Pass contest, which comes through it),
    `offer_scoring_attempt_choice` (a set-up), `begin_run_back` (a
    turnover a maneuver settles for itself) and `begin_own_goal_roll`
    (a shove that overshot). See "Mind Pull, and the arrival gate" in
    docs/design/species-abilities.md for what each of the last two
    catches that the first three do not.

    **The path is consumed whether or not anybody may pull.** That is
    what stops the same movement being offered twice when two gates run
    in a row -- `finish_maneuver_resolution` gates and then calls
    `check_for_loose_ball`, which reaches the second gate with the path
    already spent.
    """
    candidates = engine.mind_pull_candidates(game, match)
    # Spent either way, and before the early return: a movement that
    # offered nobody a pull must not offer one at the next arrival
    # point either. The movers go with it -- they are only disqualified
    # from the movement that moved them, so a second movement in the
    # same turn must find them eligible again.
    match.last_ball_path = []
    match.last_ball_movers = []
    if not candidates:
        return None

    match.pending_mind_pull = candidates
    match.pending_mind_pull_resume = resume
    return continue_mind_pull(engine, game, match)


def continue_smooth(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
) -> StepResult:
    """
    Put the offer to the next Telekinetic the ball reached, or -- when
    none are left -- hand the movement on to the pull, and then to the
    arrival this interrupted. **The one exit from the queue**, so a
    coach who declines and a Telekinetic who was never asked leave by
    the same door.

    **Dinky never takes a Smooth**, so an AI side's Telekinetics are
    skipped rather than prompted -- the same call as never ceding and
    never pulling. Taking the ball over moves who plays the next turn,
    which is a judgement, and Dinky makes none.

    Injured players are **not** skipped, unlike the pull's queue: a
    Smooth costs nothing, so there is no charge for an injured player
    to fail to pay.
    """
    while match.pending_smooth:
        player_id = match.pending_smooth[0]
        if engine.controlling_user_id(game, match, player_id) is None:
            match.pending_smooth.pop(0)
            continue

        player = engine.get_player_definition(player_id)
        smooth_emoji = get_species_ability_emoji(
            engine.species_ability_emojis, SPECIES_TELEKINETIC,
        )
        return StepResult(
            next=PendingPrompt(
                PromptKind.SMOOTH,
                f"{smooth_emoji} **Smooth** — the ball reaches near "
                f"{engine.format_player_label(match, player)}, who may "
                "_smoothly_ pull to become handler.",
                player_id=player_id,
            ),
        )

    resume = match.pending_smooth_resume
    match.pending_smooth_resume = None

    # Nobody took it, so the movement carries on to the opposing side's
    # pull -- the second half of `check_for_ball_arrival`, reached here
    # rather than there because the queue above may have taken minutes
    # to drain.
    taken = check_for_mind_pull(engine, game, match, resume or {})
    if taken is not None:
        return taken
    return dispatch_arrival_resume(engine, game, match, resume)


def decline_smooth_step(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    *,
    player_id: str,
) -> StepResult:
    """
    A Telekinetic lets the ball run through rather than taking it over.

    Taking the offer is `d12ball.flow.effects.take_smooth_step`; this
    is the other button, and it was the one half of the pair still
    inside a view body -- `SmoothView.decline` popped the queue and
    worded the line itself. Both of those are the model's: which
    Telekinetic is still owed an offer is what `pending_smooth` means,
    and the sentence is a fact about the position (principle 5).

    **The line is the first block and the queue's own lines follow
    it**, because a frontend that put the decline up as an *edit of
    the offer it answers* needs to tell the two apart -- which is what
    the cog does, and why this is one result rather than two. Draining
    the queue is `continue_smooth`'s, the one exit, so a coach who
    declines and a Telekinetic who was never asked still leave by the
    same door.
    """
    player = engine.get_player_definition(player_id)
    match.pending_smooth.remove(player_id)
    result = continue_smooth(engine, game, match)
    result.narration.insert(
        0, f"{engine.format_player_label(match, player)} lets it run.",
    )
    return result


def continue_mind_pull(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
) -> StepResult:
    """
    Put the offer to the next Telekinetic the ball crossed, or -- when
    none are left -- do what the arrival this interrupted was going to
    do. **The one exit from the queue**, so a coach who declines and a
    Telekinetic who was never asked leave by the same door; this can
    never be where a turn stops for good.

    **Dinky never pulls**, so an AI side's Telekinetics are skipped
    rather than prompted. Paying a token for a one-in-six steal is a
    judgement call, and Dinky makes none.
    """
    while match.pending_mind_pull:
        player_id = match.pending_mind_pull[0]
        controller = engine.controlling_user_id(game, match, player_id)
        # Skipped rather than refused: a player who has been injured
        # since the offer was queued cannot pay the token, and an AI's
        # never wanted it.
        if controller is None or player_id in match.injured:
            match.pending_mind_pull.pop(0)
            continue

        player = engine.get_player_definition(player_id)
        mind_pull_emoji = get_species_ability_emoji(
            engine.species_ability_emojis, SPECIES_TELEKINETIC,
        )
        faces = "-".join(str(face) for face in MIND_PULL_SUCCESS_FACES)
        return StepResult(
            next=PendingPrompt(
                PromptKind.MIND_PULL,
                f"{mind_pull_emoji} **Mind Pull** — the ball crossed "
                f"{engine.format_player_label(match, player)}, who may "
                f"reach out for it: {MIND_PULL_TOKEN_COST} exhaustion "
                f"token and a d12, pulling it in on a {faces}.",
                player_id=player_id,
            ),
        )

    resume = match.pending_mind_pull_resume
    match.pending_mind_pull_resume = None
    return dispatch_arrival_resume(engine, game, match, resume)


def dispatch_arrival_resume(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    resume: Optional[dict],
) -> StepResult:
    """
    Put the turn back where the interrupt found it -- the kind names
    the arrival, and the rest of the dict is the arguments that arrival
    needs.

    Named for the arrival rather than for Mind Pull because both gates
    end here: a Smooth queue that drains hands on to the pull, and a
    pull queue that drains hands on to this.

    **This one is the model's outright**, where its twin
    `D12Ball.dispatch_injury_resume` is still a `FollowOnStep`: all
    five kinds here moved into `d12ball/flow/` in Phase 4, so nothing
    it names has to be reached back through the cog.

    An unrecognised kind (or none at all) falls through to the ordinary
    end of a maneuver rather than stranding the turn, the same as
    `continue_effect`'s own fallback.
    """
    resume = resume or {}
    kind = resume.get("kind")

    if kind == "loose_ball":
        return StepResult(
            narration=(
                [resume["lead_in"]] if resume.get("lead_in") else []
            ),
            next=FollowOn(
                FollowOnStep.BEGIN_LOOSE_BALL,
                {
                    "distance_moved": resume.get("distance_moved", 1),
                    "headline": resume.get("headline"),
                    "is_high_pass": resume.get("is_high_pass", False),
                },
            ),
        )

    if kind == "scoring_attempt":
        return offer_scoring_attempt_choice(
            engine,
            game,
            match,
            shooter_id=resume["shooter_id"],
            distance_moved=resume.get("distance_moved", 1),
            lead_in=resume.get("lead_in", ""),
            contest_on_decline=resume.get("contest_on_decline", False),
        )

    if kind == "own_goal":
        return begin_own_goal_roll(
            engine,
            game,
            match,
            distance_moved=resume.get("distance_moved", 1),
            lead_in=resume.get("lead_in", ""),
        )

    if kind == "run_back":
        return StepResult(
            next=FollowOn(
                FollowOnStep.BEGIN_RUN_BACK,
                {
                    "distance_moved": resume.get("distance_moved", 1),
                    "turnover_occurred": resume.get(
                        "turnover_occurred", True,
                    ),
                    "new_play": resume.get("new_play", False),
                    "speed_choice_after": resume.get(
                        "speed_choice_after", False,
                    ),
                    "speed_reset": resume.get("speed_reset", True),
                },
            ),
            narration=(
                [resume["lead_in"]] if resume.get("lead_in") else []
            ),
        )

    return StepResult(
        next=FollowOn(
            FollowOnStep.FINISH_MANEUVER_RESOLUTION,
            {
                "distance_moved": resume.get("distance_moved", 1),
                "turnover_occurred": resume.get("turnover_occurred", False),
            },
        ),
        narration=[resume["lead_in"]] if resume.get("lead_in") else [],
    )


def check_for_loose_ball(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    distance_moved: int,
    lead_in: str = "",
) -> Optional[StepResult]:
    """
    The one check every maneuver-effect path runs through, via
    `finish_maneuver_resolution`: does the possessing team actually
    have a player on the ball's space? If not, this detours into the
    loose ball instead of letting the turn proceed with nobody eligible
    to act.

    **There is one detour now, not two.** A ball landing where only the
    *other* side is standing used to be theirs outright: no movement,
    no roll, a clean steal. It is a loose ball like any other since
    2026-08-18, and the side that lost it may send somebody to contest
    it -- the defender standing there is simply a contestant who costs
    their side nothing. See "The loose ball" in docs/living-rules.md.

    A Deflect does not come through here at all: it makes a loose ball
    whoever is standing on the landing space, so its own effect calls
    `begin_loose_ball` directly rather than answering a question whose
    answer would be "not loose".
    """
    if match.eligible_ball_handlers():
        return None
    # **Named rather than called**, which is rank D1's answer and not a
    # new one: the loose ball announces the position with the board
    # under it, because the ball is lying somewhere nothing in the
    # channel has named. A step that merely returned its lines would
    # have them carried into whatever came next as a lead-in, which is
    # the opposite of a message of their own. See
    # `FollowOnStep.BEGIN_LOOSE_BALL`.
    return StepResult(
        narration=[lead_in] if lead_in else [],
        next=FollowOn(
            FollowOnStep.BEGIN_LOOSE_BALL,
            {"distance_moved": distance_moved},
        ),
    )


# -- The arrival points ----------------------------------------------


def finish_maneuver_resolution(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    distance_moved: int = 1,
    turnover_occurred: bool = False,
    lead_in: str = "",
) -> StepResult:
    """
    The tail of every maneuver-effect path once movement, speed, any
    turnover, and run-back are all settled: advance the clock, end the
    period if this turnover closes out last possession, clear the
    maneuver state, and hand the offensive choice back to whoever now
    has the ball.

    The maneuver that reaches the period's last minute never ends it,
    even when it is itself a turnover: last possession is the
    possession that starts there, so whoever comes out of that maneuver
    with the ball gets to play it out and only loses the period when
    *they* lose the ball. Only a turnover under a last possession that
    was already in force ends it -- which is the case `begin_run_back`
    catches earlier, before any run back.

    Checked first, before the clock moves: does the possessing team
    actually have a player on the ball's space? If the maneuver left it
    somewhere they don't -- an empty space, or one only the other team
    occupies -- this detours into the loose-ball flow instead, which
    re-enters this function itself once it's settled.
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

    loose = check_for_loose_ball(
        engine, game, match, distance_moved, lead_in=lead_in,
    )
    if loose is not None:
        return loose

    narration: list[str] = []
    entered_last_possession = match.advance_time(distance_moved)
    if entered_last_possession:
        prefix = f"{lead_in}\n\n" if lead_in else ""
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
        narration.append(
            f"{prefix}The clock reaches "
            f"{match.scoreboard.last_minute:02d} -- this is now "
            f"**last possession**. {body} The clock keeps running."
        )
        lead_in = ""

    if (
        turnover_occurred
        and match.scoreboard.last_possession
        and not entered_last_possession
    ):
        # `narration` is empty here: the two branches are exclusive,
        # since entering last possession is what stops this one being
        # reached. So the lead-in is still whatever the effect handed
        # over, and it rides through `StepResult.narration` into
        # `end_period`'s own `lead_in` like any other follow-on's.
        return StepResult(
            narration=[lead_in] if lead_in else [],
            next=FollowOn(FollowOnStep.END_PERIOD),
        )

    match.reset_maneuver()

    prefix = f"{lead_in}\n\n" if lead_in else ""
    # Every maneuver costs at least its flat space minute (2026-08-16),
    # ceding included, so there is no longer a zero-cost turn to word
    # specially here.
    clock = (
        f"Time has advanced {distance_moved}, now "
        f"at {match.scoreboard.time:02d}."
    )
    narration.append(
        f"{prefix}Ball is now "
        f"{space_label(match.ball.zone, match.ball.space_index)}, "
        f"{format_team_side_label(match.setup_for_side(match.ball.possession))} "
        f"has possession. {clock}"
    )
    return StepResult(
        narration=narration,
        board_changed=True,
        next=FollowOn(FollowOnStep.SEND_TURN_PROMPT),
    )


def offer_scoring_attempt_choice(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    *,
    shooter_id: str,
    distance_moved: int,
    lead_in: str,
    contest_on_decline: bool = False,
) -> StepResult:
    """
    Offer the offense a chance to attempt a scoring-opportunity shot
    instead of letting a maneuver resolve normally -- used by a High
    Pass's 2-space pass, a High Pass that overshoots, and a Winger's
    Low Pass.

    Declining nearly always resolves the maneuver as a normal pass; a
    2-space High Pass stopped forcing a contest instead on 2026-08-07.
    `contest_on_decline` is the one exception: an overshoot is a shot
    or a contest, both at the same disadvantage, so declining lands in
    the contest rather than settling the ball (2026-08-10). It is
    passed rather than derived because by the time this runs, an
    overshot pass and an ordinary 2-space one have left the match in
    the same state.
    """
    # **A scoring opportunity is an arrival too**, and one the rules
    # name outright among what a pull pre-empts -- so the offer goes
    # out before the shot is put to anybody.
    taken = check_for_ball_arrival(
        engine,
        game,
        match,
        {
            "kind": "scoring_attempt",
            "shooter_id": shooter_id,
            "distance_moved": distance_moved,
            "lead_in": lead_in,
            "contest_on_decline": contest_on_decline,
        },
    )
    if taken is not None:
        return taken

    narration = [lead_in] if lead_in else []

    if engine.side_controlled_by_ai(game, match, "offense"):
        attempt = engine.get_ai_strategy(
            game
        ).choose_scoring_opportunity_attempt(match)
        if attempt:
            return StepResult(
                narration=narration,
                next=FollowOn(
                    FollowOnStep.START_SET_UP_SHOT,
                    {
                        "shooter_id": shooter_id,
                        "maneuver_cost": distance_moved,
                    },
                ),
            )
        return decline_scoring_attempt(
            engine,
            game,
            match,
            distance_moved,
            contest=contest_on_decline,
            lead_in=lead_in,
        )

    # **A `PendingPrompt` since Phase 6**, and what it took was
    # `MatchState.pending_scoring_opportunity`. It was a follow-on
    # until then for the reason `PendingPrompt`'s own docstring gives:
    # a prompt carries only what a branch of `pending_prompt` carries,
    # and neither `distance_moved` nor `contest_on_decline` was
    # anywhere in match state -- so a prompt carrying them was a shape
    # the restart chain could never produce, and a game that went down
    # here came back to the maneuver's first-stage distance choice
    # instead. The offer is recorded on the match now and
    # `scoring_opportunity_prompt` reads it, so the live question and
    # the restored one are the same question.
    #
    # The `ask` opens with the pass's own lines because the offer is
    # where this turn stops and there is nothing else to hang them on.
    # A restart has not got them and does not invent them, which is the
    # difference the run back's prompt has carried since Phase 4.
    match.pending_scoring_opportunity = {
        "kind": "attempt",
        "shooter_id": shooter_id,
        "distance_moved": distance_moved,
        "contest_on_decline": contest_on_decline,
    }
    restored = scoring_opportunity_prompt(engine, game, match)
    return StepResult(
        next=PendingPrompt(
            restored.kind,
            f"{lead_in}\n\n{restored.ask}" if lead_in else restored.ask,
            player_id=restored.player_id,
            distance_moved=restored.distance_moved,
            contest_on_decline=restored.contest_on_decline,
        ),
    )


def decline_scoring_attempt(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    distance_moved: int,
    contest: bool = False,
    lead_in: str = "",
) -> StepResult:
    """
    Let go of a scoring opportunity: the maneuver that offered it
    resolves as it otherwise would have.

    For an overshot High Pass that is the long-pass contest, not a
    settled ball -- the shot and the contest are the two halves of one
    choice. See `offer_scoring_attempt_choice`.

    **The offer is spent here**, whichever way it goes: the field that
    records it is what `pending_prompt` reads, so a match that still
    held it would be asked the same question again on the next click.
    """
    match.pending_scoring_opportunity = None
    if contest:
        return begin_high_pass_contest(
            engine,
            game,
            match,
            distance_moved,
            lead_in="The scoring opportunity is let go -- but the "
            "pass still has to be kept.",
        )
    return StepResult(
        narration=[lead_in] if lead_in else [],
        next=FollowOn(
            FollowOnStep.FINISH_MANEUVER_RESOLUTION,
            {"distance_moved": distance_moved},
        ),
    )


def begin_high_pass_contest(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    distance_moved: int,
    lead_in: str = "",
) -> StepResult:
    """
    The long-pass contest: the receiver standing where the pass landed
    still has to win a skill test to keep the ball.

    Since 2026-08-18 this is a loose ball and nothing else -- the
    receiver contests because they are standing on the ball, which is
    the ordinary rule, and so does a defender sharing the space. The
    one thing still peculiar to a High Pass is the ball speed modifier,
    which `is_high_pass` carries.

    Two paths reach it, and callers of both have already found the
    receiver on the landing space: an unclamped pass of 3 or 4, and an
    overshoot whose set-up the coach declined (2026-08-10). The second
    still carries `pending_high_pass_overshoot`, so the contest is
    rolled with the ball speed modifier against the receiver rather
    than for them.
    """
    return StepResult(
        narration=[lead_in] if lead_in else [],
        next=FollowOn(
            FollowOnStep.BEGIN_LOOSE_BALL,
            {
                "distance_moved": distance_moved,
                "headline": HIGH_PASS_CONTEST_HEADLINE,
                "is_high_pass": True,
            },
        ),
    )


def begin_loose_ball(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    distance_moved: int,
    lead_in: str = "",
    headline: Optional[str] = None,
    is_high_pass: bool = False,
) -> StepResult:
    """
    The ball is out of everybody's hands where it stopped, and what is
    standing on that space decides how it is won.

    **This is the flow step, not `MatchState.begin_loose_ball`** --
    that one is the state change this calls into, and the two share a
    name because the step was named after it.

    `distance_moved` (the pass's own clamped travel) is stashed on
    `match`: the pick and, if it comes to one, the skill test both span
    later interactions that cannot see a Python-level parameter from
    this call, so everything downstream reads it back from match state
    instead.

    `headline` overrides the wording, which is otherwise built from the
    position by `build_loose_ball_headline` -- the ball may come down
    on an occupied space, so nothing may assume emptiness.

    **Nobody's contestant is forced from here.** A side with somebody
    standing on the ball puts them up, for nothing and without being
    asked, and that is one rule read off the position by
    `loose_ball_candidates` rather than call sites passing players in.

    **Occupancy decides who may be sent, and there is no longer a flag
    for it** (the author, 2026-08-26). A ball is *loose* only where it
    comes down on an empty space, and only then may each side send a
    player after it. Where one side is already standing there the ball
    is simply theirs; where both are, it is a contest between the
    players already on the space. Either way nobody walks in, so the
    side with nobody there is pre-declined before either side is put on
    the clock.

    **A High Pass is the one exemption**, and `is_high_pass` is already
    the flag for it: the ball is high in the air, which gives players
    time to run at it, so a landing space holding only one side's
    players may still be contested by the other.
    """
    # **Mind Pull pre-empts a contest and a loose ball alike**, so the
    # offer goes out before any of this side's state is set.
    # `finish_maneuver_resolution` has usually gated already and spent
    # the path; the callers that reach here directly -- a Deflect, and
    # the High Pass contest -- have not.
    taken = check_for_ball_arrival(
        engine,
        game,
        match,
        {
            "kind": "loose_ball",
            "distance_moved": distance_moved,
            "lead_in": lead_in,
            "headline": headline,
            "is_high_pass": is_high_pass,
        },
    )
    if taken is not None:
        return taken

    match.begin_loose_ball(distance_moved, is_high_pass=is_high_pass)
    # The ball is free and about to be contested, so nobody is carrying
    # it -- including the long High Pass, where a receiver who has to
    # win a test to keep it is not yet in possession of anything.
    match.clear_ball_carrier()

    if not is_high_pass:
        offense_side = match.ball.possession
        defense_side = match.defending_side()
        offense_occupied = bool(match.loose_ball_occupants(offense_side))
        defense_occupied = bool(match.loose_ball_occupants(defense_side))
        if offense_occupied != defense_occupied:
            empty_side = defense_side if offense_occupied else offense_side
            match.decline_loose_ball(empty_side)

    engine.auto_resolve_loose_ball_picks(game, match)

    if headline is None:
        headline = engine.build_loose_ball_headline(match)
    prefix = f"{lead_in}\n\n" if lead_in else ""
    if is_high_pass:
        # A High Pass is not a loose ball: the ball is on a player
        # everyone can already see, and the board it is standing on was
        # posted by the pass itself.
        announcement = f"{prefix}{headline}"
        board_changed = False
    else:
        # A genuine loose ball is the one position nobody can read off
        # the last thing they were told -- the ball is lying in an
        # empty space some number of spaces from wherever the pass
        # started, and the very next question is who to send after it.
        # So it is named and drawn, together.
        announcement = f"{prefix}{headline}\n{ball_location_line(match)}"
        board_changed = True

    # **The announcement is its own message, so it is its own step's
    # narration and nothing after it is merged in.** Whether the
    # settlement below happens immediately or after a coach answers, it
    # says its own sentence -- naming where the ball is and then who
    # came away with it in one paragraph would read as one event.
    # `FollowOnStep.RESOLVE_LOOSE_BALL` is how the first hands to the
    # second without the frontend's ordinary "carry the lines forward"
    # applying; see `D12Ball.post_then_dispatch`.
    if engine.loose_ball_side_on_the_clock(match) is None:
        return StepResult(
            narration=[announcement],
            board_changed=board_changed,
            next=FollowOn(FollowOnStep.RESOLVE_LOOSE_BALL),
        )

    # **The kind and the view's two arguments come from
    # `loose_ball_pick_prompt`; the wording does not.** A restart asks
    # "Choose who goes after the loose ball:" because it is putting a
    # question back up with nothing above it, where this one is posted
    # under the headline that has just said where the ball is and names
    # the coach and the space itself. One question, two askings -- the
    # same split `injury_test_ask` makes, and the reason the kind is
    # read off the one chain rather than spelled again here.
    return StepResult(
        narration=[announcement],
        board_changed=board_changed,
        next=replace(
            loose_ball_pick_prompt(engine, match),
            ask=engine.build_loose_ball_prompt(game, match),
        ),
    )


def resolve_loose_ball(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
) -> StepResult:
    """
    Settle a loose ball (or a long High Pass, which comes through the
    same machinery) once both sides have answered: out of bounds when
    neither sent anybody, an unopposed take when only one did, and a
    skill test when both did.
    """
    offense_player_id = match.loose_ball_offense_player
    defense_player_id = match.loose_ball_defense_player
    distance_moved = match.pending_loose_ball_distance

    if offense_player_id is None and defense_player_id is None:
        return send_loose_ball_out_of_bounds(
            engine, game, match, distance_moved,
        )

    if defense_player_id is None:
        return resolve_unopposed_loose_ball(
            engine, game, match, offense_player_id,
            turnover=False, distance_moved=distance_moved,
        )

    if offense_player_id is None:
        # Only the defending side went for it -- because the side in
        # possession sent nobody. Not out of bounds: that is the branch
        # above, where neither side ends up with a player to send.
        return resolve_unopposed_loose_ball(
            engine, game, match, defense_player_id,
            turnover=True, distance_moved=distance_moved,
        )

    return begin_loose_ball_skill_test(
        engine, game, match, offense_player_id, defense_player_id,
    )


def send_loose_ball_out_of_bounds(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    distance_moved: int,
) -> StepResult:
    """
    Nobody could be sent, or nobody was. The side that last held the
    ball loses it, and the side that just won it owes a player on the
    ball's space -- placed after the run back, not before, or the run
    back would pull that player straight back off the ball again.
    """
    winning_side = match.defending_side()
    reason = (
        "Nobody is sent after it"
        if match.loose_ball_offense_declined
        or match.loose_ball_defense_declined
        # Only a side with nobody fielded at all lands here now --
        # distance replaced the zone as the measure on 2026-08-16, so
        # declining is otherwise the whole of how a ball goes out.
        else "Neither side has anyone left to send"
    )
    # Assigned rather than set_possession'd: that insists on a player
    # of the new side already standing on the ball, and out of bounds
    # is precisely the case where nobody is -- pending_ball_recovery is
    # the promise that somebody will be, once the run back is done.
    match.ball.possession = winning_side
    match.ball.speed = 1
    match.pending_loose_ball = False
    match.pending_ball_recovery = True

    return StepResult(
        narration=[
            f"**Out of bounds!** {reason} -- "
            f"{format_team_side_label(match.setup_for_side(winning_side))} "
            "take over.\n\n# Turnover!\nOnce everyone has run back, "
            "they place a player on the ball."
        ],
        board_changed=True,
        # Out of bounds is the one loose ball that is a new play rather
        # than a steal: nobody took the ball off anyone, it simply went
        # dead and is being brought back in.
        next=FollowOn(
            FollowOnStep.BEGIN_RUN_BACK,
            {
                "distance_moved": distance_moved,
                "turnover_occurred": True,
                "new_play": True,
            },
        ),
    )


def resolve_unopposed_loose_ball(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    player_id: str,
    turnover: bool,
    distance_moved: int,
) -> StepResult:
    """
    One side sent somebody and the other did not, so there is nothing
    to roll: they walk in and take it.

    `turnover` is the whole difference between the two sides arriving
    here. The defending side taking it changes possession and resets
    the ball's speed; the side already in possession keeping it changes
    neither. It is a steal either way -- picked off rather than
    restarted -- so neither opens a substitution window.
    """
    player = engine.get_player_definition(player_id)
    recovery_distance = match.distance_to_ball(player_id)
    match.move_meeple(player_id, match.ball.zone, match.ball.space_index)
    exhaustion_text = engine.apply_exhaustion(
        game, match, player_id, recovery_distance,
    )
    if turnover:
        match.ball.possession = match.defending_side()
        match.ball.speed = 1
    match.pending_loose_ball = False
    # They went after it and came away with it, so they are holding it
    # -- the same answer as a contested win, since an unopposed contest
    # is still how they got it.
    match.set_ball_carrier(player_id)

    bracket = engine.format_player_label(match, player)
    # Each of these says what happened and stops there. "Recovers the
    # loose ball uncontested" was three faults in five words: it called
    # an arrival loose that the message above it had just said was not,
    # and "uncontested" defined the result by the roll that did not
    # happen -- which no coach was waiting for, since nobody had been
    # offered a send.
    if match.pending_loose_ball_is_high_pass:
        headline = (
            f"{bracket} picks off the high pass."
            if turnover
            else f"{bracket} keeps possession after the high pass."
        )
    else:
        headline = f"{bracket} picks up the ball."

    if turnover:
        content = (
            "# Turnover!\n"
            f"{headline} "
            f"{format_team_side_label(match.setup_for_side(match.ball.possession))} "
            "now has possession."
        )
    else:
        content = headline

    # A move that costs nothing says nothing -- see
    # `describe_exhaustion_gain`, which is why this is a join over what
    # is there rather than an interpolation.
    content = "\n".join(filter(None, [content, exhaustion_text]))

    return StepResult(
        narration=[content],
        board_changed=True,
        next=FollowOn(
            FollowOnStep.BEGIN_RUN_BACK,
            {
                "distance_moved": distance_moved,
                "turnover_occurred": turnover,
            },
        ),
    )


def begin_loose_ball_skill_test(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    offense_player_id: str,
    defense_player_id: str,
) -> StepResult:
    """
    Both sides have a candidate: move them both in, charge each their
    own recovery distance in exhaustion, and put the skill test up.
    """
    offense_recovery_distance = match.distance_to_ball(offense_player_id)
    defense_recovery_distance = match.distance_to_ball(defense_player_id)
    match.move_meeple(
        offense_player_id, match.ball.zone, match.ball.space_index,
    )
    match.move_meeple(
        defense_player_id, match.ball.zone, match.ball.space_index,
    )
    # Filtered: a contestant already standing on the ball is charged
    # nothing and says nothing, and an unfiltered join would leave
    # their blank line in the message.
    exhaustion_text = "\n".join(
        filter(
            None,
            [
                engine.apply_exhaustion(
                    game, match, offense_player_id,
                    offense_recovery_distance,
                ),
                engine.apply_exhaustion(
                    game, match, defense_player_id,
                    defense_recovery_distance,
                ),
            ],
        )
    )

    offense_player = engine.get_player_definition(offense_player_id)
    defense_player = engine.get_player_definition(defense_player_id)
    offense_skill = engine.player_catalog.effective_profile(
        offense_player,
    ).offense
    defense_skill = engine.player_catalog.effective_profile(
        defense_player,
    ).defense

    # Who is defending what differs between the two: a High Pass's
    # receiver already has the ball and is being challenged for it,
    # where a loose ball belongs to nobody yet and both sides are going
    # for it.
    contest_line = (
        f"{engine.format_player_label(match, defense_player)} "
        f"(defense skill {defense_skill}) challenges "
        f"{engine.format_player_label(match, offense_player)} "
        f"(offense skill {offense_skill}) for the high pass -- the "
        "receiver must win this skill test to keep possession!"
        if match.pending_loose_ball_is_high_pass
        else f"{engine.format_player_label(match, offense_player)} "
        f"(offense skill {offense_skill}) and "
        f"{engine.format_player_label(match, defense_player)} "
        f"(defense skill {defense_skill}) both contest the "
        f"{contest_noun(match)} -- skill test!"
    )
    return StepResult(
        board_changed=True,
        next=PendingPrompt(
            PromptKind.LOOSE_BALL_SKILL_TEST,
            f"{contest_line}\n{exhaustion_text}\n\nEither "
            "player can roll:",
        ),
    )


def begin_shooter_choice(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    candidates: list[str],
    lead_in: str = "",
) -> StepResult:
    """
    Who takes a scoring opportunity the position has opened up.

    `lead_in` is narration from the pass that set this up -- it rides
    along on the "choose who takes the shot" prompt when a human has to
    pick. When the pick is automatic there is no prompt to attach it
    to, so it is posted on its own instead of being dropped.
    """
    if len(candidates) == 1 or engine.side_controlled_by_ai(
        game, match, "offense",
    ):
        if len(candidates) == 1:
            shooter_id = candidates[0]
        else:
            shooter_id = engine.get_ai_strategy(game).choose_shooter(
                candidates, match,
            )
        return StepResult(
            narration=[lead_in] if lead_in else [],
            next=FollowOn(
                FollowOnStep.START_SET_UP_SHOT, {"shooter_id": shooter_id},
            ),
        )

    # **A `PendingPrompt` since Phase 6**, for
    # `offer_scoring_attempt_choice`'s reason and closed the same way:
    # nothing in match state said a scoring opportunity was being
    # asked about, so the candidate list lived on the view. It is
    # recorded on the match now -- the *fact* only, since the
    # candidates are whoever is standing on the ball's space and
    # `scoring_opportunity_prompt` reads them back off the board.
    match.pending_scoring_opportunity = {"kind": "shooter"}
    prefix = f"{lead_in}\n\n" if lead_in else ""
    mention = shooter_mention(engine, game, match)
    return StepResult(
        next=PendingPrompt(
            PromptKind.SHOOTER_CHOICE,
            f"{prefix}{mention}, choose who takes the shot:",
            player_ids=list(candidates),
        ),
    )


def begin_own_goal_roll(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    distance_moved: int,
    lead_in: str = "",
) -> StepResult:
    """
    Put the own-goal roll behind a button, the way a score attempt is:
    the coach whose player is about to concede rolls it themselves
    rather than reading what the bot already rolled for them.

    Nothing is decided here, so everything the roll needs is persisted
    by the caller -- `pending_own_goal` says one is owed and
    `pending_own_goal_distance` carries the clock cost of the maneuver
    that risked it, which the resolution spends whichever way the roll
    goes.

    **It gates the shove's own arrival first**, which is the one
    arrival no other gate reaches. `shove_pressured_handler` drove the
    ball back through `set_ball_space`, so the shove has a recorded
    path like any other ball movement, and what that movement led to is
    this roll -- so a Smooth or a pull is owed *before* it, since "a
    pull that lands pre-empts whatever the movement would have led to".
    Left to `begin_run_back`'s gate at the far end it was both too late
    to pre-empt the roll and, when the own goal is conceded, never
    reached with the path intact at all.

    **Above `pending_own_goal`**, so a restart mid-offer reads the
    offer rather than the roll; a decline comes back through the
    `"own_goal"` resume kind and finds the path spent, so this reading
    is a no-op the second time.

    **Only a Double Team can arrive with a path.** A plain Pressure
    overshoots only from the space closest to the offense's own goal,
    where the handler does not move and `ball_path_to` answers empty
    for a move that goes nowhere.
    """
    taken = check_for_ball_arrival(
        engine,
        game,
        match,
        {
            "kind": "own_goal",
            "distance_moved": distance_moved,
            "lead_in": lead_in,
        },
    )
    if taken is not None:
        return taken

    match.pending_own_goal = True
    match.pending_own_goal_distance = distance_moved

    offense_player = engine.get_player_definition(match.active_player_id)
    offense_skill = engine.player_catalog.effective_profile(
        offense_player,
    ).offense
    controller_id = engine.controlling_user_id(
        game, match, offense_player.player_id,
    )
    mention = f"<@{controller_id}>" if controller_id else "Someone"

    prefix = f"{lead_in}\n\n" if lead_in else ""
    return StepResult(
        next=PendingPrompt(
            PromptKind.OWN_GOAL_ROLL,
            f"{prefix}**Own goal risk!** {mention}, "
            f"{engine.format_player_label(match, offense_player)} "
            "rolls two d12 at an advantage — the higher of the two, plus "
            f"their offensive skill ({offense_skill}). A total of 7 or "
            "more and the own goal is avoided.",
        ),
    )


# -- Answering the loose ball's and the set-up's own prompts -----------
#
# Phase 6 of docs/design/model-discord-split.md. Each was in a view body --
# `LooseBallChoiceView` in `cogs/d12ball_views/loose_ball.py`,
# `SetUpAttemptChoiceView` and `ShooterChoiceView` in
# `cogs/d12ball_views/effects.py` -- with the rule and the edit that
# renders it in one method. The rule is here now;
# `d12ball.flow.driver.apply` runs one over a prompt it has checked,
# and the views call the same function.


def choose_loose_ball_contestant(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    *,
    skill_type: str,
    player_id: str,
) -> StepResult:
    """
    Send this player after the loose ball, for the side on the clock.

    Ends on the other side's pick where one is still owed, and on
    `RESOLVE_LOOSE_BALL` once both have answered -- the same reading
    `loose_ball_pick_prompt` makes, because it is that reading.
    """
    if skill_type == "offense":
        match.choose_loose_ball_offense_player(player_id)
    else:
        match.choose_loose_ball_defense_player(player_id)

    player = engine.get_player_definition(player_id)
    return _loose_ball_answered(
        engine,
        game,
        match,
        f"{engine.format_player_label(match, player)} "
        f"contests the {contest_noun(match)} ({skill_type}).",
    )


def loose_ball_decline_refusal(
    match: MatchState,
    skill_type: str,
) -> Optional[str]:
    """
    Why this side may not send nobody after the loose ball, or None.

    A **pure read**, and separate from the step for one reason: the
    frontend has to be able to refuse *before* anything is applied.
    `LooseBallChoiceView.decline` asks this, then its own tutorial
    rail, and only then runs the step -- and a step that raised on the
    way out would already have recorded the decline by the time the
    rail refused it. `decline_loose_ball_contest` asks the same
    question on its own account, so a frontend that skips this one
    still cannot get past it.

    The answer is `MatchState.may_decline_loose_ball`'s; what is here
    is the sentence for it.
    """
    side = (
        match.ball.possession
        if skill_type == "offense"
        else match.defending_side()
    )
    if match.may_decline_loose_ball(side):
        return None
    return (
        "Somebody of theirs is standing on the ball -- they "
        "contest it, and cannot be held back."
    )


def decline_loose_ball_contest(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    *,
    skill_type: str,
) -> StepResult:
    """
    Send nobody after the loose ball.

    Raises `ValueError` where the side has somebody standing on the
    ball and therefore cannot be held back -- which is a stale click on
    a prompt a restart re-attached from before the ball reached them.
    See `loose_ball_decline_refusal`, which is the same answer asked
    without applying anything.
    """
    refusal = loose_ball_decline_refusal(match, skill_type)
    if refusal is not None:
        raise RuleRefusal(refusal)
    side = (
        match.ball.possession
        if skill_type == "offense"
        else match.defending_side()
    )
    match.decline_loose_ball(side)
    return _loose_ball_answered(
        engine,
        game,
        match,
        f"{format_team_side_label(match.setup_for_side(side))} send "
        f"nobody after the {contest_noun(match)}.",
    )


def _loose_ball_answered(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    announcement: str,
) -> StepResult:
    """
    One side has answered: put the question to the other, or settle it.

    The announcement is **its own message** -- it is the edit the view
    makes over the question it answers -- so it is the result's
    narration and the frontend decides that it replaces the prompt
    rather than standing above the next one.
    """
    pick = loose_ball_pick_prompt(engine, match)
    if pick is not None:
        return StepResult(
            narration=[announcement],
            next=PendingPrompt(
                pick.kind,
                engine.build_loose_ball_prompt(game, match),
                side=pick.side,
                skill_type=pick.skill_type,
            ),
        )
    return StepResult(
        narration=[announcement],
        next=FollowOn(FollowOnStep.RESOLVE_LOOSE_BALL),
    )


def take_scoring_opportunity(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    *,
    shooter_id: str,
    maneuver_cost: int = 1,
) -> StepResult:
    """
    Take the scoring opportunity: this player shoots.

    `maneuver_cost` is the flat cost of the maneuver that offered the
    set-up -- 1 for everything but a High Pass, which is why it
    defaults to 1 and only a High Pass call site overrides it. Stored
    so the score attempt can charge it on top of the shot's own extra
    minute (2026-08-16): the two stack, instead of the shot's cost
    replacing the maneuver's.

    **The offer is spent here.** `pending_scoring_opportunity` is what
    `pending_prompt` reads, so a match that still held it would be
    asked the same question again on the next click.
    """
    match.pending_scoring_opportunity = None
    match.active_player_id = shooter_id
    match.pending_action = "shoot"
    match.pending_shot_is_set_up = True
    match.pending_shot_setup_cost = maneuver_cost

    shooter = engine.get_player_definition(shooter_id)
    return StepResult(
        narration=[
            f"{engine.format_player_label(match, shooter)} takes the "
            "shot off the set-up.",
        ],
        # The roll prompt. What a frontend puts up for the kind is the
        # composition image and then the prompt -- two uploads and no
        # decision -- keyed on the kind, which is how the AI's set-up,
        # a coach's "Attempt" and the shooter's own pick all reach the
        # same picture. `START_SET_UP_SHOT` is this step under the name
        # the two automatic routes reach it by.
        next=PendingPrompt(PromptKind.SCORE_ATTEMPT, SCORE_ATTEMPT_ASK),
    )


@dataclass(frozen=True)
class MindPullRoll:
    """
    One Mind Pull attempt's numbers, for the picture of the die.

    The same shape `InjuryRoll` and `OwnGoalRoll` take, and for the
    same reason: what the roll came to is the sentence beside this, and
    what is here is the face and whether it landed, which
    `render_mind_pull_die` draws. `ignite` rides along for the second
    die.

    **A player who was injured between being queued and answering
    rolls nothing**, and the step hands back no roll at all to say so.
    """

    player_id: str
    roll: int
    pulled: bool
    ignite: object


def decline_mind_pull_step(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    *,
    player_id: str,
) -> StepResult:
    """
    A Telekinetic lets the ball go past rather than reaching for it.

    Nothing is charged for letting it go -- the token is the price of
    *trying* -- so this says only that they did, and hands the queue
    on. `decline_smooth_step`'s shape and for its reasons: popping the
    queue and wording the line are both the model's, and the line is
    the first block so a frontend can put it up as an edit of the offer
    it answers.
    """
    player = engine.get_player_definition(player_id)
    match.pending_mind_pull.remove(player_id)
    result = continue_mind_pull(engine, game, match)
    result.narration.insert(
        0,
        f"{engine.format_player_label(match, player)} lets the ball "
        "go past.",
    )
    return result


def attempt_mind_pull_step(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    *,
    player_id: str,
) -> tuple[Optional[MindPullRoll], StepResult]:
    """
    One Telekinetic's attempt, off the button they were offered: pay
    the token, roll a d12, and either take the ball or hand the queue
    on.

    **The token is paid whether or not the pull lands**, which is the
    rule and is why the charge is above the roll rather than in the
    winning branch.

    **It is not a skill test and owes no injury check** (the rules say
    so outright), so nothing here goes through the injury queue -- a
    Telekinetic the token pushes over their threshold is Exhausted and
    simply carries it.

    A pull that lands is a **steal**: possession flips, the ball stops
    here, and this player is the carrier who does not run back. The
    arrival it pre-empted never happens -- "a pull that lands pre-empts
    whatever the movement would have led to" -- so the resume is
    dropped rather than dispatched. Its clock cost is not: the maneuver
    that moved the ball still charges its space minute.
    """
    player = engine.get_player_definition(player_id)
    if player_id in match.pending_mind_pull:
        match.pending_mind_pull.remove(player_id)

    # Injured between being queued and answering: they cannot pay the
    # token, and `add_exhaustion` would refuse it silently and hand
    # them a free roll. Skipped rather than refused, the same way
    # `continue_mind_pull` skips them -- this can never be where a turn
    # stops.
    if player_id in match.injured:
        return None, continue_mind_pull(engine, game, match)

    exhaustion_text = engine.apply_exhaustion(
        game, match, player_id, MIND_PULL_TOKEN_COST,
    )
    roll = random.randint(1, 12)
    # Volatile is a Fire Demon's and this is a Telekinetic's roll, so
    # nothing ignites here -- asked anyway, through the one funnel,
    # rather than assuming the two can never meet.
    ignite = engine.ignite(game, player_id, roll)
    total = roll + ignite.modifier
    pulled = total in MIND_PULL_SUCCESS_FACES

    # The die image draws the natural face, exactly as the injury
    # test's does, so an ignite has to be said in words or the number a
    # coach reads and the verdict they are given would not add up.
    ignite_note = f" ({ignite.detail}, {total})" if ignite.detail else ""
    mind_pull_emoji = get_species_ability_emoji(
        engine.species_ability_emojis, SPECIES_TELEKINETIC,
    )
    note = "\n".join(filter(None, (
        f"{mind_pull_emoji} **Mind Pull** — "
        f"{engine.format_player_label(match, player)} reaches for the "
        f"ball{ignite_note}.",
        exhaustion_text,
    )))
    numbers = MindPullRoll(player_id, roll, pulled, ignite)

    if not pulled:
        # The resume is left exactly as it was: the next Telekinetic in
        # the queue is owed the same offer, and the arrival behind them
        # is still the one to fall back to.
        result = continue_mind_pull(engine, game, match)
        result.narration.insert(0, f"{note}\nThe ball slips past them.")
        return numbers, result

    resume = match.pending_mind_pull_resume
    match.pending_mind_pull_resume = None
    match.apply_mind_pull(player_id)
    match.ball.speed = 1

    return numbers, StepResult(
        narration=[
            f"{note}\n\n## "
            f"{engine.format_player_label(match, player)} grabs "
            "the ball with their telekinetic powers!\n"
            f"**Turnover!** They take it on "
            f"{ball_space_phrase(match)}.",
        ],
        board_changed=True,
        next=FollowOn(
            FollowOnStep.BEGIN_RUN_BACK,
            {
                "distance_moved": (resume or {}).get("distance_moved", 1),
                "turnover_occurred": True,
            },
        ),
    )
