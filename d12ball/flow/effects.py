"""
What a maneuver does when it wins, as flow steps.

One function per card, each taking the engine and the match, changing
the match, and handing back a `StepResult`. Low Pass (with Skilled
Pass, which is the same card parameterised) and the two dribbles are
here; the other nine are still `cogs/d12ball/effects.py`'s until the
remaining ranks of Phase 3 of docs/model-discord-split.md lift them.
See "Maneuvers" in docs/design/maneuvers.md for what each card
actually does.

**The two dribbles are two steps, not one parameterised by key**, the
way the two passes are one. A Skilled Pass is a Low Pass with more
reach and a bigger bonus and nothing else; a Dribble Burst is not a
Dribble Advance with a longer run -- it charges by distance, words a
run that covered no ground, and reads the Playmaker's ability as a
token off rather than a space on. Two cards in a rank share a step
only where they share an effect.

A step takes `(engine, match, ...)`, and `(engine, game, match, ...)`
where it actually reads the game record -- which is what the dribbles
do and Low Pass does not, because charging exhaustion has to ask
whether the player's threshold is a Cyborg's. The rule is the one
`d12ball.prompts.pending_prompt` follows: take the record only when
something is read off it. None of them takes an `interaction`, ever:
that is the single clearest test of which side of the seam a function
has ended up on, and it is greppable.

**Nothing here saves.** The caller persists once, immediately after the
step and before dispatching whatever comes next -- see
`D12Ball.apply_low_pass` and principle 9 in CLAUDE.md.
"""

from __future__ import annotations

from typing import Optional

from d12ball.components import (
    MatchState,
    PlayerDefinition,
    PlayerRole,
    TeamSide,
)
from d12ball.engine import RulesEngine
from d12ball.flow.result import FollowOn, FollowOnStep, StepResult
from d12ball.game import D12BallGame


def send_low_pass(
    engine: RulesEngine,
    match: MatchState,
    offense_side: TeamSide,
    distance: int,
    key: str,
    receiver_id: Optional[str],
) -> tuple[int, int]:
    """
    Move the ball, step its speed up, and hand it to whoever the
    pass was aimed at. Returns how far the ball went and how far
    the passer advanced.
    """
    actual_distance = match.move_ball_relative(offense_side, distance)
    match.ball.speed = min(
        12, match.ball.speed + engine.pass_speed_bonus(key)
    )
    # A pass across a shared space sends the passer a space forward
    # (2026-08-07) -- the ball hasn't gone anywhere, so this is what
    # the maneuver buys. Clamped at the far end of the field, where
    # there is nowhere to run to.
    passer_advance = (
        match.move_player_relative(match.active_player_id, offense_side, 1)
        if distance == 0
        else 0
    )
    # The pass was aimed at somebody, and it is the same somebody a
    # Winger's set-up would hand the shot to -- so they receive it
    # and take the next turn. A receiver of None means the pass had
    # no legal destination, which rolls the ball forward loose
    # instead of completing; nobody carries a loose ball.
    match.set_ball_carrier(receiver_id)

    return actual_distance, passer_advance


def low_pass_movement_note(
    engine: RulesEngine,
    match: MatchState,
    handler: PlayerDefinition,
    distance: int,
    actual_distance: int,
    passer_advance: int,
) -> str:
    """
    What the ball did, worded. A pass of 0 crosses a shared space
    and so is described by what the *passer* did instead.
    """
    if distance != 0:
        direction = "forward" if distance > 0 else "backward"
        space_word = "space" if actual_distance == 1 else "spaces"
        return f"moves {actual_distance} {space_word} {direction}"

    movement_note = "goes to a teammate in the same space"
    if passer_advance:
        movement_note += (
            f", and {engine.format_player_label(match, handler)} "
            "moves a space forward"
        )
    return movement_note


def pay_double_team_cost(
    engine: RulesEngine,
    match: MatchState,
    winner_key: str,
    partner_id: Optional[str],
) -> str:
    """
    Double Team's cost, charged inside the pass that beat it: the
    defender who played it and the nearest teammate each move a
    space forward, away from their own goal.

    `partner_id` is passed rather than looked up, because by the
    time this runs the pass has already moved the ball and "the
    closest teammate" would be measured from the wrong space -- the
    card means the space the play started from. Its caller reads it
    before the ball moves, the same way a won Double Team does.

    No exhaustion -- nobody chose to go, and every per-space charge
    in the game is for a move somebody was sent on. Empty string
    when Double Team was not the card beaten, which is nearly
    always.
    """
    if engine.advanced_cost(match, winner_key) != "double_team":
        return ""
    defense_side = match.defending_side()
    moved = []
    for player_id in (match.challenger_id, partner_id):
        if player_id is None:
            continue
        match.move_player_relative(player_id, defense_side, 1)
        moved.append(
            engine.format_player_label(
                match, engine.get_player_definition(player_id),
            )
        )
    if not moved:
        return ""
    return (
        "\n\n**Double Team** was beaten -- "
        + " and ".join(moved)
        + " are each shoved a space forward, away from their own goal."
    )


def low_pass_step(
    engine: RulesEngine,
    match: MatchState,
    distance: int,
    receiver_id: Optional[str] = None,
    key: str = "low_pass",
    free: bool = False,
) -> StepResult:
    """
    Play a won Low Pass -- or a Skilled Pass, which is the same card
    with more reach and a bigger bonus, or the unopposed pass Skilled
    Pass's own cost hands the defense.

    `free` marks that last one: it is not this side's maneuver, so it
    charges no clock, and applying it is what spends the continuation
    that recorded it.
    """
    name = engine.maneuver_name(key)
    # A pass granted by Skilled Pass's cost is a continuation, and
    # applying it is what spends it -- see `continue_effect`.
    if free:
        match.pending_effect_continuation = None
    offense_side = match.ball.possession
    handler = engine.get_player_definition(match.active_player_id)
    # Read before the ball moves, because the receivers are
    # relative to where it is now. `receiver_id` is who the passer
    # picked out of a shared space; without one -- a single
    # occupant, so nothing was asked -- it is whoever is standing
    # there. Either way this is the player the pass was aimed at,
    # which is not always the same as whoever the landing space's
    # occupant list happens to start with -- see the Winger branch
    # below.
    receivers = engine.low_pass_receivers(match, distance)
    if receiver_id not in receivers:
        receiver_id = receivers[0] if receivers else None

    # Read before the ball moves too, and for the same reason a
    # won Double Team reads it before the push: "the closest
    # teammate" is measured from where the play started, which is
    # where the ball is standing right now. See
    # `pay_double_team_cost`.
    double_team_partner = (
        engine.double_team_partner(match)
        if engine.advanced_cost(match, key) == "double_team"
        else None
    )

    actual_distance, passer_advance = send_low_pass(
        engine, match, offense_side, distance, key, receiver_id,
    )

    content = (
        f"**{name}:** the ball "
        f"{low_pass_movement_note(engine, match, handler, distance, actual_distance, passer_advance)}. "
        f"Ball speed is now {match.ball.speed}."
    )

    # **Double Team's cost**: beaten by a pass, the defender who
    # played it and the teammate who would have joined them are
    # each shoved a space forward, away from their own goal.
    content += pay_double_team_cost(engine, match, key, double_team_partner)
    # Low Pass's own cost is a flat 1 space minute regardless of
    # distance (2026-08-16), the same as every maneuver but High
    # Pass. A pass granted by Skilled Pass's cost is not this
    # side's maneuver and charges nothing: the clock was already
    # spent on the steal that produced it.
    distance_moved = 0 if free else 1

    # Both branches below have moved the ball, so `board_changed` is
    # True either way -- which is exactly where `refresh_match_image`
    # sat in the cog. The flag is carried rather than assumed because
    # a step that moves nothing a board draws is what it is for, and
    # the ranks Phase 3 lifts will have some.
    #
    # Role ability -- Winger: the receiving player may attempt a
    # scoring opportunity right where the pass lands, whatever the
    # distance -- unlike High Pass's set-up, this doesn't require
    # reaching the space nearest the goal. It does require shooting
    # range, like any other shot: the ability frees the set-up from
    # a distance, not from where a goal can be scored from.
    if handler.role != PlayerRole.WINGER or not match.can_attempt_score(
        offense_side,
    ):
        return StepResult(
            narration=[content],
            board_changed=True,
            next=FollowOn(
                FollowOnStep.FINISH_MANEUVER_RESOLUTION,
                {"distance_moved": distance_moved},
            ),
        )

    if receiver_id is None:
        # Only reachable if the board changed under a stale
        # choice; fall back to whoever is on the ball's space.
        receiver_id = match.eligible_ball_handlers()[0]
    return StepResult(
        narration=[
            content,
            (
                f"{engine.format_player_label(match, handler)}'s Winger "
                "ability can turn this into a scoring opportunity!"
            ),
        ],
        board_changed=True,
        next=FollowOn(
            FollowOnStep.OFFER_SCORING_ATTEMPT_CHOICE,
            {"shooter_id": receiver_id, "distance_moved": distance_moved},
        ),
    )


def pay_clear_cost(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    winner_key: str,
) -> str:
    """
    Clear's cost, charged where it is due -- inside the dribble that
    beat it -- and worded for the message that dribble is already
    sending. Empty string when Clear was not the card beaten, which is
    nearly always.

    A flat 2 exhaustion rather than 2 on top of a maneuver's own
    charge, because a maneuver charges none -- only a skill test, a
    walk, a shot and a run back do.
    """
    if engine.advanced_cost(match, winner_key) != "clear":
        return ""
    defender_id = match.challenger_id
    if defender_id is None:
        return ""
    text = engine.apply_exhaustion(game, match, defender_id, 2)
    return f"\n\n**Clear** was beaten -- 2 exhaustion.\n{text}"


def dribble_advance_step(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    distance: int,
) -> StepResult:
    """
    Play a won Dribble Advance: the handler carries the ball `distance`
    spaces forward and keeps it.

    One space for everyone but a Playmaker, who may take two -- which
    is the only thing there is to choose here, and the only thing the
    wording adds a note for.

    Takes the `game` because Clear's cost charges exhaustion, and a
    Cyborg's threshold is the game record's to answer (see
    `RulesEngine.exhaustion_threshold`).
    """
    offense_side = match.ball.possession
    actual_distance = match.move_player_relative(
        match.active_player_id, offense_side, distance,
    )
    match.set_ball_space(
        *match.board.meeple_position(match.active_player_id)
    )
    # They dribbled it there, so they still have it: the same player
    # takes the next turn rather than the coach choosing again off the
    # space they landed on.
    match.set_ball_carrier(match.active_player_id)

    handler = engine.get_player_definition(match.active_player_id)
    space_word = "space" if actual_distance == 1 else "spaces"
    # Read off the distance asked for rather than the ground covered:
    # a Playmaker who called for 2 used the ability whether or not the
    # end of the field took one of them away.
    ability_note = (
        " (Playmaker ability)"
        if handler.role == PlayerRole.PLAYMAKER and distance > 1
        else ""
    )

    content = (
        f"**Dribble Advance:** "
        f"{engine.format_player_label(match, handler)} and the "
        f"ball move forward {actual_distance} {space_word}"
        f"{ability_note}."
        # **Clear's cost**: beaten by a dribble, the defender who
        # played it gains 2 exhaustion.
        + pay_clear_cost(engine, game, match, "dribble_advance")
    )

    return StepResult(
        narration=[content],
        board_changed=True,
        next=FollowOn(
            FollowOnStep.OFFER_SPEED_CHOICE,
            {
                "player_id": match.active_player_id,
                "skill_type": "offense",
            },
        ),
    )


def dribble_burst_step(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    distance: int,
) -> StepResult:
    """
    Run a won Dribble Burst `distance` spaces, charge a token a space,
    and hand over to the speed choice every dribble ends with.

    `distance` is what the coach picked (or what the field left);
    `actual_distance` is what the move came to, since
    `move_player_relative` clamps at the end of the field. The
    exhaustion and the wording both read the second, because what a
    coach pays for is where the handler actually got to.
    """
    offense_side = match.ball.possession
    handler = engine.get_player_definition(match.active_player_id)

    actual_distance = match.move_player_relative(
        match.active_player_id, offense_side, distance,
    )
    match.set_ball_space(
        *match.board.meeple_position(match.active_player_id)
    )
    match.set_ball_carrier(match.active_player_id)
    playmaker_bonus = handler.role == PlayerRole.PLAYMAKER
    # Floored at 0 rather than allowed to go negative: a burst that
    # moved nowhere costs nothing, and a Playmaker's discount cannot
    # turn a run into a token back.
    tokens = max(0, actual_distance - (1 if playmaker_bonus else 0))
    # Charged and re-tested in one step, and before anything saves --
    # see `RulesEngine.apply_exhaustion` for the bug that ordering
    # exists to prevent.
    exhaustion_text = engine.apply_exhaustion(
        game, match, match.active_player_id, tokens,
    )

    space_word = "space" if actual_distance == 1 else "spaces"
    handler_label = engine.format_player_label(match, handler)
    if actual_distance:
        content = (
            f"**Dribble Burst:** {handler_label} bursts "
            f"{actual_distance} {space_word} forward, past everyone in "
            "the way."
        )
    else:
        # The handler was already on the last space of the field, so
        # the burst had nowhere to go -- said plainly rather than
        # reported as a run of 0 spaces, which is the same call
        # `apply_high_pass` makes for a clamped throw.
        content = (
            f"**Dribble Burst:** {handler_label} is already as far "
            "forward as the field goes, so the ball stays where it is."
        )
    # Only worth saying where a token was actually saved: a burst that
    # moved nowhere is free for everybody.
    if playmaker_bonus and actual_distance:
        content += " That costs them a token less (Playmaker ability)."
    if exhaustion_text:
        content += f"\n{exhaustion_text}"

    # **Clear's cost**: beaten by a dribble, the defender who played it
    # gains 2 exhaustion.
    content += pay_clear_cost(engine, game, match, "dribble_burst")

    return StepResult(
        narration=[content],
        board_changed=True,
        next=FollowOn(
            FollowOnStep.OFFER_SPEED_CHOICE,
            {
                "player_id": match.active_player_id,
                "skill_type": "offense",
            },
        ),
    )
