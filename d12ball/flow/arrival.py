"""
Where a ball that has moved is settled, as flow steps.

**This is one ordering group and it moved whole.** A maneuver's
movement ends at one of the arrival points, and each of them opens
with the same two gates in the same order -- Smooth, then Mind Pull,
then "is anybody of the possessing side standing on it". Which of
those is asked before which is a rule (see "Mind Pull, and the
arrival gate" and "Smooth" in
docs/design/species-abilities.md), so splitting the group across the
seam would have left half the ordering in `cogs/` deciding a rule.

A step here takes `(engine, game, match, ...)`, never an
`interaction`, and saves nothing -- the caller persists immediately
after it, before dispatching whatever comes next. The two functions
that *gate* return `Optional[StepResult]` rather than a `StepResult`:
`None` is "nobody took the ball over, carry on", and a result is "the
arrival has been interrupted and this is what happens instead". That
is the same `if ...: return` shape the cog's gates had, read from the
model's side.

**What is still the cog's, and why.** How a loose ball reaches a
channel -- named with the board drawn under it, where a High Pass
contest is announced plainly -- is a frontend decision, so
`D12Ball.begin_loose_ball` stays as the wrapper that posts it and
`FollowOnStep.BEGIN_LOOSE_BALL` stays in the enum. See principle 8 in
CLAUDE.md, and [loose-balls.md](../../docs/design/loose-balls.md).
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping, Optional, Sequence

from d12ball.components import MatchState
from d12ball.engine import RulesEngine
from d12ball.formatting import (
    HIGH_PASS_CONTEST_HEADLINE,
    ball_location_line,
    contest_noun,
)
from d12ball.game import D12BallGame
from d12ball.prompts import (
    PendingPrompt,
    PromptKind,
    loose_ball_pick_prompt,
)
from d12ball.flow.result import FollowOn, FollowOnStep, StepResult


def check_for_ball_arrival(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    resume: Mapping[str, Any],
) -> Optional[StepResult]:
    """
    **The one gate every ball arrival runs through.** Smooth first,
    then Mind Pull; a `StepResult` when either took over, so a caller
    is one `if ...: return` exactly as it was when Mind Pull was the
    whole of it.

    **Smooth is asked first, and that is a rule rather than an
    ordering convenience.** Both read the same `last_ball_path`, and a
    Smooth that is taken stops the ball short of where the movement
    was going -- so whichever is asked first decides whether the other
    is asked at all. Asking the possessing side first means their own
    Telekinetic can take the ball off a movement before an opponent's
    gets to reach for it -- the author, 2026-09-20, asked directly
    because the sheet settles what each half does and says nothing
    about the race.

    **The path is spent by `check_for_mind_pull`, which is the last
    reader**, so Smooth deliberately does not clear it -- a Smooth that
    nobody wanted must still leave the pull its movement.
    """
    taken = check_for_smooth(engine, game, match, resume)
    if taken is not None:
        return taken
    return check_for_mind_pull(engine, game, match, resume)


def check_for_smooth(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    resume: Mapping[str, Any],
) -> Optional[StepResult]:
    """
    Did the ball just move to or through one of its **own** side's
    Telekinetics, who may take it over? The twin of
    `check_for_mind_pull`, and the same contract: a result when the
    offer is to be put and the caller should stop.

    **It does not spend the path.** `check_for_mind_pull` runs after
    it on the same movement and needs it -- see
    `check_for_ball_arrival`. That is the one way the two gates differ
    mechanically, and it is why they are not the same function with a
    side argument.
    """
    candidates = engine.smooth_candidates(game, match)
    if not candidates:
        return None

    match.pending_smooth = candidates
    match.pending_smooth_resume = dict(resume)
    return StepResult(next=FollowOn(FollowOnStep.CONTINUE_SMOOTH))


def check_for_mind_pull(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    resume: Mapping[str, Any],
) -> Optional[StepResult]:
    """
    Did the ball just cross an opposing Telekinetic who may pull it
    in? A result when it did and the offer is to be put, so the caller
    stops -- exactly the shape `check_for_loose_ball` has, and for the
    same reason.

    Mind Pull "resolves before the ball settles", so this sits at the
    top of the functions that settle an arrival: the tail of every
    ordinary path (`finish_maneuver_resolution_step`), the loose ball
    (a Deflect, which reaches it directly, and the High Pass contest,
    which comes through it), a set-up
    (`scoring_attempt_choice_step`), the run back of a turnover a
    maneuver settled for itself, and the own-goal roll a shove that
    overshot risks. Between them they are every one of "a reception, a
    scoring opportunity, a contest, a loose ball", plus the two that
    are neither a settling nor a turnover.

    **The path is consumed whether or not anybody may pull**, before
    the early return. That is what stops the same movement being
    offered twice when two gates run in a row --
    `finish_maneuver_resolution_step` gates and then calls
    `check_for_loose_ball`, which reaches the second gate with the
    path already spent.

    `resume` is the arrival this interrupted, as
    `{"kind": ..., ...}` -- the same shape `pending_injury_resume`
    uses, and for the same reason: a coach may take minutes over the
    offer, and between the interrupt and the answer nothing else on
    the match says what the ball was about to do.
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
    match.pending_mind_pull_resume = dict(resume)
    return StepResult(next=FollowOn(FollowOnStep.CONTINUE_MIND_PULL))


def check_for_loose_ball(
    match: MatchState,
    distance_moved: int,
) -> Optional[StepResult]:
    """
    The check every maneuver-effect path runs through, via
    `finish_maneuver_resolution_step`: does the possessing team
    actually have a player on the ball's space? If not, this detours
    into the loose ball instead of letting the turn proceed with
    nobody eligible to act -- a result when it took that detour, so
    the caller stops instead of continuing.

    **There is one detour now, not two.** A ball landing where only
    the *other* side is standing used to be theirs outright: no
    movement, no roll, a clean steal. It is a loose ball like any
    other since 2026-08-18, and the side that lost it may send
    somebody to contest it -- the defender standing there is simply a
    contestant who costs their side nothing. See "The loose ball" in
    docs/living-rules.md.

    A Deflect does not come through here at all: it makes a loose ball
    whoever is standing on the landing space, so `deflection_step`
    names the loose ball directly rather than answering a question
    whose answer would be "not loose".

    It reads the match and nothing else, so it takes no engine and no
    game -- the one function in this module that does not.
    """
    if match.eligible_ball_handlers():
        return None

    return StepResult(
        next=FollowOn(
            FollowOnStep.BEGIN_LOOSE_BALL,
            {"distance_moved": distance_moved},
        ),
    )


def loose_ball_step(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    distance_moved: int,
    *,
    lead_in: str = "",
    headline: Optional[str] = None,
    is_high_pass: bool = False,
) -> StepResult:
    """
    The ball is out of everybody's hands where it stopped: set the
    contest up, say what the position is, and either settle it or ask
    whoever still has a choice.

    Not to be confused with **`MatchState.begin_loose_ball`**, which
    is the state change this calls into -- that one stashes
    `distance_moved` and the High Pass flag on the match, because the
    pick and the skill test both span later interactions that cannot
    see a Python-level parameter from this call.

    `headline` overrides the wording, which is otherwise built from
    the position by `build_loose_ball_headline` -- the ball may come
    down on an occupied space, so nothing may assume emptiness. A
    caller passing its own is saying the wording would be a lie, which
    is the High Pass's case and nobody else's.

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
    side with nobody there is pre-declined before either side is put
    on the clock -- never prompted, and never given the chance.

    **A High Pass is the one exemption**, and `is_high_pass` is
    already the flag for it: the ball is high in the air, which gives
    players time to run at it, so a landing space holding only one
    side's players may still be contested by the other. That is a
    property of the pass and not of the space, which is why it rides
    on the same flag that carries the ball speed modifier.

    **The narration is one block and the frontend decides how it goes
    out.** A genuine loose ball is named with the board drawn under
    it and a High Pass contest is announced plainly -- which is a
    question about what a coach can already see rather than about the
    position, so it is `D12Ball.begin_loose_ball`'s to answer. See
    [loose-balls.md](../../docs/design/loose-balls.md).
    """
    # **Mind Pull pre-empts a contest and a loose ball alike**, so the
    # offer goes out before any of this side's state is set.
    # `finish_maneuver_resolution_step` has usually gated already and
    # spent the path; the callers that reach here directly -- a
    # Deflect, and the High Pass contest -- have not.
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
    # The ball is free and about to be contested, so nobody is
    # carrying it -- including the long High Pass, where a receiver who
    # has to win a test to keep it is not yet in possession of
    # anything. Whoever comes out of the contest with it is chosen off
    # the ball's space in the ordinary way.
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
    if is_high_pass:
        # A High Pass is not a loose ball: the ball is on a player
        # everyone can already see, and the board it is standing on was
        # posted by the pass itself.
        announcement = headline
    else:
        # A genuine loose ball is the one position nobody can read off
        # the last thing they were told -- the ball is lying in an empty
        # space some number of spaces from wherever the pass started,
        # and the very next question is who to send after it. So it is
        # named and drawn, together.
        announcement = f"{headline}\n{ball_location_line(match)}"

    # **The caller's lines are a block of their own**, in front of the
    # announcement rather than joined to it: the pass said what it did
    # and this says where the ball ended up, and a frontend that put
    # them in one message puts a blank line between them. Which is the
    # frontend's call to make -- what is settled here is that they are
    # two things said rather than one (principle 8).
    narration = [block for block in (lead_in, announcement) if block]

    pick = loose_ball_pick_prompt(engine, match)
    if pick is None:
        # Nobody is left to ask: both sides are settled, so the
        # contest resolves on what is already on the board.
        return StepResult(
            narration=narration,
            next=FollowOn(FollowOnStep.RESOLVE_LOOSE_BALL),
        )

    # **The same prompt a restart restores, worded the way the live
    # flow words it.** `loose_ball_pick_prompt` is the one reading of
    # which side is on the clock and who its candidates are, and
    # `build_loose_ball_prompt` is the fuller sentence the flow has
    # always put the question in -- it names the coach and words "which
    # of these two" differently from "send somebody or don't". A
    # restart's terser ask is deliberately not the same sentence (see
    # `pending_prompt`), so the kind and its parameters come from the
    # one reading and only the ask is this one's.
    return StepResult(
        narration=narration,
        next=replace(pick, ask=engine.build_loose_ball_prompt(game, match)),
    )


def high_pass_contest_step(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    distance_moved: int,
    *,
    lead_in: str = "",
) -> StepResult:
    """
    The long-pass contest: the receiver standing where the pass landed
    still has to win a skill test to keep the ball.

    Since 2026-08-18 this is a loose ball and nothing else -- the
    receiver contests because they are standing on the ball, which is
    the ordinary rule, and so does a defender sharing the space. The
    one thing still peculiar to a High Pass is the ball speed
    modifier, which `is_high_pass` carries. So there is nothing here
    but the flag: the contestants are read off the position by
    `loose_ball_candidates`, and the passer is struck out of the
    offense's pool by `MatchState.loose_ball_occupants`.

    Two paths reach it, and callers of both have already found the
    receiver on the landing space: an unclamped pass of 3 or 4, and an
    overshoot whose set-up the coach declined (2026-08-10). The second
    still carries `pending_high_pass_overshoot`, so the contest is
    rolled with the ball speed modifier against the receiver rather
    than for them -- the same sign the declined shot would have paid.

    It stays a step of its own rather than folding into
    `loose_ball_step` with a `headline=`, for the reason rank O3 gave
    `BEGIN_HIGH_PASS_CONTEST` a member of its own: the two do
    different things with the board.
    """
    return loose_ball_step(
        engine,
        game,
        match,
        distance_moved,
        lead_in=lead_in,
        headline=HIGH_PASS_CONTEST_HEADLINE,
        is_high_pass=True,
    )



def loose_ball_skill_test_step(
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
                    game, match, offense_player_id, offense_recovery_distance,
                ),
                engine.apply_exhaustion(
                    game, match, defense_player_id, defense_recovery_distance,
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

    # One message: the contest, what it cost the two of them, and the
    # invitation to roll. It is the prompt's own ask rather than
    # narration in front of it, because there is nothing here that is
    # not part of asking.
    return StepResult(
        board_changed=True,
        next=PendingPrompt(
            PromptKind.LOOSE_BALL_SKILL_TEST,
            f"{contest_line}\n{exhaustion_text}\n\nEither "
            "player can roll:",
        ),
    )


def shooter_choice_step(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    candidates: Sequence[str],
) -> StepResult:
    """
    A scoring opportunity, and who of the offense may take it.

    One candidate is nobody's choice and an AI offense makes its own,
    so both go straight to the shot; anything else is the coach's.
    """
    if len(candidates) == 1 or engine.side_controlled_by_ai(
        game, match, "offense",
    ):
        if len(candidates) == 1:
            shooter_id = candidates[0]
        else:
            shooter_id = engine.get_ai_strategy(game).choose_shooter(
                list(candidates), match,
            )
        return StepResult(
            next=FollowOn(
                FollowOnStep.START_SET_UP_SHOT, {"shooter_id": shooter_id},
            ),
        )

    return StepResult(
        next=FollowOn(
            FollowOnStep.ASK_SHOOTER_CHOICE, {"candidates": list(candidates)},
        ),
    )


def scoring_attempt_choice_step(
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
    2-space High Pass stopped forcing a contest instead on
    2026-08-07. `contest_on_decline` is the one exception: an
    overshoot is a shot or a contest, both at the same disadvantage,
    so declining lands in the contest rather than settling the ball
    (2026-08-10). It is passed rather than derived because by the time
    this runs, an overshot pass and an ordinary 2-space one have left
    the match in the same state.

    **A scoring opportunity is an arrival too**, and one the rules
    name outright among what a pull pre-empts -- so the gate is asked
    before the shot is put to anybody.

    `contest_on_decline` rides on the view rather than on the match
    (see [shooting.md](../../docs/design/shooting.md)), which is why
    the coach's branch is a follow-on and not a `PendingPrompt`:
    `SetUpAttemptChoiceView` is the one view a restart cannot
    reconstruct, so it has no `PromptKind` to be rendered through.
    """
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

    if engine.side_controlled_by_ai(game, match, "offense"):
        attempt = engine.get_ai_strategy(
            game
        ).choose_scoring_opportunity_attempt(match)
        if attempt:
            return StepResult(
                narration=[lead_in] if lead_in else [],
                next=FollowOn(
                    FollowOnStep.START_SET_UP_SHOT,
                    {
                        "shooter_id": shooter_id,
                        "maneuver_cost": distance_moved,
                    },
                ),
            )
        return StepResult(
            narration=[lead_in] if lead_in else [],
            next=FollowOn(
                FollowOnStep.DECLINE_SCORING_ATTEMPT,
                {
                    "distance_moved": distance_moved,
                    "contest": contest_on_decline,
                },
            ),
        )

    shooter = engine.get_player_definition(shooter_id)
    return StepResult(
        narration=[
            f"{lead_in}\n\n"
            f"{engine.format_player_label(match, shooter)} can attempt "
            "the scoring opportunity, or let it go:"
        ],
        next=FollowOn(
            FollowOnStep.ASK_SET_UP_ATTEMPT,
            {
                "shooter_id": shooter_id,
                "distance_moved": distance_moved,
                "contest_on_decline": contest_on_decline,
            },
        ),
    )
