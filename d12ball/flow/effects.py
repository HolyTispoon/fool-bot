"""
What a maneuver does when it wins, as flow steps.

One function per card, each taking the engine and the match, changing
the match, and handing back a `StepResult`. Low Pass (rank O1), the
two dribbles (rank O2) and the two steals (rank D2) are here; the
other seven are still `cogs/d12ball/effects.py`'s until Phase 3 of
docs/model-discord-split.md lifts them a rank at a time. See
"Maneuvers" in docs/design/maneuvers.md for what each card actually
does.

A step takes `(engine, match, ...)`, and `game` only where it
actually reads the record -- `low_pass_step` and `steal_step` do not
and so do not take one; both dribbles do, because charging an
exhaustion token tests a threshold the game record decides (a
Cyborg's is a flat 7, see `RulesEngine.exhaustion_threshold`). None of
them takes an `interaction`, ever: that is the single clearest test of
which side of the seam a function has ended up on, and it is
greppable.

**A rank's two cards are one function wherever they differ by a
parameter**: Low Pass and Skilled Pass by `key`, Steal and Intercept
by the sign of the carry. Only the dribbles needed two, and they have
different costs rather than different signs.

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
from d12ball.formatting import format_team_side_label
from d12ball.game import D12BallGame
from d12ball.flow.result import FollowOn, FollowOnStep, StepResult


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
    sending. Empty string when Clear was not the card beaten, which
    is nearly always.

    It is a flat 2 exhaustion rather than 2 on top of a maneuver's own
    charge, because a maneuver charges none: only a skill test, a
    walk, a shot and a run back do. See "Advanced maneuvers" in
    docs/design/maneuvers.md.
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
    Play a won Dribble Advance: the handler carries the ball forward
    and keeps it, then manipulates ball speed the way every dribble
    ends.

    Role ability -- Playmaker: 2 spaces instead of the usual 1. The
    note says which of the two was taken, so it rides on the distance
    rather than on the player; whether the coach was even asked is
    `resolve_dribble_advance`'s, above the seam.

    `distance` is what was chosen; `actual_distance` is what the move
    came to, since `move_player_relative` clamps at the end of the
    field. The wording reads the second, because what a coach watched
    is where the handler actually got to.

    It takes the `game` for the exhaustion a beaten Clear is charged
    -- the Exhausted threshold is the game record's (see
    `RulesEngine.exhaustion_threshold`) -- and for nothing else.
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
        # played it gains 2 exhaustion, said inside this sentence
        # rather than as a message after it.
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
    Play a won Dribble Burst: the handler carries the ball up to
    `DRIBBLE_BURST_MAX_DISTANCE` spaces forward, defenders no
    obstacle, at a token a space -- then manipulates ball speed
    exactly as a Dribble Advance does.

    Role ability -- Playmaker: one token fewer for the run (the
    author, 2026-08-26) rather than the extra space their sentence
    names, which is the only ability that reads differently on the two
    cards of a rank. Floored at 0 rather than allowed to go negative:
    a burst that moved nowhere costs nothing, and the discount cannot
    turn a run into a token back.

    `distance` is what the coach picked (or what the field left);
    `actual_distance` is what the move came to. The exhaustion and the
    wording both read the second, since what a coach pays for is where
    the handler actually got to.
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
    tokens = max(0, actual_distance - (1 if playmaker_bonus else 0))
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

    # **Clear's cost**, the same charge the advance collects.
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


def take_ball_by_steal(
    match: MatchState,
    challenger_id: str,
    new_possession_side: TeamSide,
    direction: int,
) -> tuple[bool, int]:
    """
    Turn the ball over and carry it off, returning whether the carry
    ran out of field and how far it actually went.

    The turnover happens first, then both the interceptor and the
    ball move -- relative to the *new* possessing side, not the old
    one. Moving the challenger's meeple (not just the ball) and
    re-deriving the ball's space from it keeps the two in the same
    space, so possession can be assigned directly without
    set_possession's occupancy check.
    """
    match.ball.possession = new_possession_side
    # Every turnover drops the ball's speed back to 1 -- the
    # defender's manipulate-speed choice applies to that reset
    # value, not whatever the speed was before the steal.
    match.ball.speed = 1

    # Intercept moving forward can run out of field, which a Steal
    # falling back never can: the ball was in play, so there is
    # always a space behind it. Read before the move, the way every
    # other overshoot is.
    origin_flat = match.board.flat_index(
        *match.board.meeple_position(challenger_id)
    )
    target_flat = match.relative_flat_index(
        origin_flat, new_possession_side, direction,
    )
    overshot = abs(target_flat - origin_flat) < 1

    actual_distance = match.move_player_relative(
        challenger_id, new_possession_side, direction,
    )
    match.set_ball_space(*match.board.meeple_position(challenger_id))
    # The interceptor took the ball off someone and moved with it,
    # so they carry it into their side's next turn -- the same
    # player the run back exempts.
    match.set_ball_carrier(challenger_id)

    return overshot, actual_distance


def steal_result_text(
    engine: RulesEngine,
    match: MatchState,
    key: str,
    name: str,
    challenger_id: str,
    actual_distance: int,
) -> str:
    """The turnover, and which way the thief carried it."""
    space_word = "space" if actual_distance == 1 else "spaces"
    challenger = engine.get_player_definition(challenger_id)
    challenger_label = engine.format_player_label(match, challenger)
    new_possession = match.setup_for_side(match.ball.possession)
    travel = (
        f"then carries it {actual_distance} {space_word} forward, "
        "toward the goal they now attack"
        if key == "intercept"
        else f"then falls back {actual_distance} {space_word} toward "
        "their own goal with the ball"
    )
    return (
        f"**{name}:**\n"
        "# Turnover!\n"
        f"{challenger_label} steals the ball. "
        f"{format_team_side_label(new_possession)} now has possession, "
        f"{travel}."
    )


def steal_step(
    engine: RulesEngine,
    match: MatchState,
    key: str,
) -> StepResult:
    """
    Play a won Steal -- or an Intercept, which is the same card with
    the sign flipped: the thief carries the ball **forward**, toward
    the goal they now attack, rather than falling back toward their
    own. It is the only card in the game that moves the ball against
    the way the offense was going, and that is the whole of the
    difference, so the two are one function and a `direction`.

    Rank D2 has no unchallenged branch: a defense card only resolves
    where a defender was sent, so `match.challenger_id` is always the
    player who plays it.

    It reads nothing off the game record -- the exhaustion a run back
    charges is `begin_run_back`'s, and the cost this card can collect
    is an engine question -- so it takes no `game`.
    """
    new_possession_side = match.defending_side()
    challenger_id = match.challenger_id
    name = engine.maneuver_name(key)
    # Toward the new possessor's own goal for a Steal, toward the
    # goal they now attack for an Intercept.
    direction = 1 if key == "intercept" else -1

    overshot, actual_distance = take_ball_by_steal(
        match, challenger_id, new_possession_side, direction,
    )
    content = steal_result_text(
        engine, match, key, name, challenger_id, actual_distance,
    )

    # Both endings below have moved a meeple and the ball with it, so
    # `board_changed` is True either way -- which is exactly where
    # `refresh_match_image` sat in the cog, on both paths.
    if key == "intercept" and overshot:
        # **The interceptor was already on the last space toward
        # the goal they now attack, so there is nowhere to carry
        # it: it is a scoring opportunity instead** (the author,
        # 2026-08-19).
        #
        # Straight to the shot, the same as a deflection's
        # overshoot and for the same reason: the run back and the
        # speed step both belong after a turnover that left the
        # play running, and this one has not. That drops
        # Intercept's own speed-manipulation step, which is the one
        # thing about this branch worth watching -- a set-up shot
        # already reads the ball speed the turnover reset.
        #
        # It returns **before** the cost below, exactly as the cog
        # did: an Intercept that overshoots collects no beaten
        # Skilled Pass. Preserved rather than corrected, because
        # whether that is the rule is the author's to say -- see the
        # questions on the pull request for rank D2.
        return StepResult(
            narration=[
                content
                + "\n\nThere is no field left ahead of them -- "
                "a scoring opportunity!"
            ],
            board_changed=True,
            next=FollowOn(
                FollowOnStep.BEGIN_SHOOTER_CHOICE,
                {"candidates": [challenger_id]},
            ),
        )

    # **Skilled Pass's cost**: beaten by a steal, the passing side
    # hands the defender an unopposed Low Pass once the steal has
    # settled. It is recorded rather than played here because the
    # steal is not finished: the run back and then the speed choice
    # both come first, and the pass is played from wherever that
    # leaves the interceptor. See `pending_effect_continuation`.
    if engine.advanced_cost(match, key) == "skilled_pass":
        match.pending_effect_continuation = {
            "kind": "free_low_pass",
            "player_id": challenger_id,
        }
        content += (
            "\n\n**Skilled Pass** was beaten -- the defense gets an "
            "unopposed Low Pass once everyone is back in position."
        )

    # Ball-speed manipulation is offered after run-back finishes,
    # not here -- see begin_run_back's speed_choice_after.
    # No stays_player_id: begin_run_back exempts the ball carrier,
    # which take_ball_by_steal has already made the interceptor.
    return StepResult(
        narration=[content],
        board_changed=True,
        next=FollowOn(
            FollowOnStep.BEGIN_RUN_BACK, {"speed_choice_after": True},
        ),
    )
