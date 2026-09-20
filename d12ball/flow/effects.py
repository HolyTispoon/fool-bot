"""
What a maneuver does when it wins, as flow steps.

One function per card, each taking the engine and the match, changing
the match, and handing back a `StepResult`. **All twelve are here**
since rank O3 -- as nine functions, since five of the cards are their
rank-mate parameterised. See "Maneuvers" in docs/design/maneuvers.md
for what each card actually does.

A step takes `(engine, match, ...)`, and `game` only where it
actually reads the record -- `low_pass_step`, `steal_step`,
`pressure_step`, `deflection_step` and rank O3's three do not and so
do not take one; both dribbles do, because charging an
exhaustion token tests a threshold the game record decides (a
Cyborg's is a flat 7, see `RulesEngine.exhaustion_threshold`). None of
them takes an `interaction`, ever: that is the single clearest test of
which side of the seam a function has ended up on, and it is
greppable.

**A rank's two cards are one function wherever they differ by a
parameter**: Low Pass and Skilled Pass by `key`, Steal and Intercept
by the sign of the carry, Pressure and Double Team by the push and the
partner it brings in, Deflect and Clear by the distance and the speed
drop. The dribbles needed two, because they have different costs
rather than different signs -- and so does rank O3, whose two cards
share a landing space and nothing else: a High Pass throws forward and
may overshoot, a Setup Pass picks the ball out and cannot, and the
Setup Pass is two steps because its speed choice comes first.

**Nothing here saves.** The caller persists once, immediately after the
step and before dispatching whatever comes next -- see
`D12Ball.apply_low_pass` and principle 9 in CLAUDE.md.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Optional

from d12ball.components import (
    BALL_SPEED_MAX,
    EVENT_OWN_GOAL_ROLL,
    MatchState,
    PlayerDefinition,
    PlayerRole,
    SETUP_PASS_CLOCK_COST,
    TeamSide,
)
from d12ball.engine import RulesEngine
from d12ball.formatting import format_goal_time, format_team_side_label
from d12ball.game import D12BallGame, team_display_name
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
    if engine.gambit_cost(match, winner_key) != "double_team":
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
        if engine.gambit_cost(match, key) == "double_team"
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
    walk, a shot and a run back do. See "Gambits" in
    docs/design/maneuvers.md.
    """
    if engine.gambit_cost(match, winner_key) != "clear":
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
    obstacle, at a token a space -- and the ball is left at speed
    `BALL_SPEED_MAX`, where a Dribble Advance offers the handler a
    change of up to oSkill (the author, 2026-09-20: "precisely 12, not
    any number"). Nothing is asked, so unlike the advance the burst
    ends on the maneuver's tail rather than on a speed choice; the
    speed is said in the narration the way `apply_speed_choice` says
    it, and said only where it changed.

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

    narration = [content]
    if match.ball.speed != BALL_SPEED_MAX:
        match.ball.speed = BALL_SPEED_MAX
        narration.append(f"Ball speed is now **{BALL_SPEED_MAX}**.")

    return StepResult(
        narration=narration,
        board_changed=True,
        next=FollowOn(
            FollowOnStep.FINISH_MANEUVER_RESOLUTION, {"distance_moved": 1},
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
    if engine.gambit_cost(match, key) == "skilled_pass":
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


def shove_pressured_handler(
    match: MatchState,
    push: int,
    partner_id: Optional[str],
) -> int:
    """
    Drive the handler and the ball back, and bring the challenger
    (and a Double Team's partner) onto the space they left.

    Returns how far the handler actually moved, which is less than
    `push` only when they were already against their own goal -- the
    caller reads that as the overshoot.
    """
    offense_side = match.ball.possession

    actual_distance = match.move_player_relative(
        match.active_player_id, offense_side, -push,
    )
    match.set_ball_space(
        *match.board.meeple_position(match.active_player_id)
    )

    # The challenger advances onto the handler's space. A Double
    # Team brings that teammate onto it as well, free of
    # exhaustion -- so they are *placed* rather than run, which is
    # what "no exhaustion cost" means in a game where every other
    # way to reach a space charges a token a space.
    handler_zone, handler_space = match.board.meeple_position(
        match.active_player_id
    )
    match.move_meeple(match.challenger_id, handler_zone, handler_space)
    if partner_id is not None:
        match.move_meeple(partner_id, handler_zone, handler_space)

    # Losing to a pressure does not lose the ball: the handler was
    # shoved back still holding it, so they take the next turn.
    # Set before the caller's overshoot branch, because an own goal
    # avoided is the same thing -- pressured, and still holding it.
    # The Defender's steal moves the carry to the Defender, and a
    # conceded own goal is a new play, which clears it.
    match.set_ball_carrier(match.active_player_id)

    return actual_distance


def pressure_result_text(
    engine: RulesEngine,
    match: MatchState,
    key: str,
    name: str,
    actual_distance: int,
    partner_id: Optional[str],
) -> str:
    """
    What the shove reads as, and -- for a Double Team -- the record
    of who is left challenging the next maneuver.
    """
    handler = engine.get_player_definition(match.active_player_id)
    defender = engine.get_player_definition(match.challenger_id)
    space_word = "space" if actual_distance == 1 else "spaces"
    content = (
        f"**{name}:** "
        f"{engine.format_player_label(match, handler)} and the "
        f"ball go back {actual_distance} {space_word}. "
        f"{engine.format_player_label(match, defender)} moves "
        "forward."
    )

    if key == "double_team" and partner_id is not None:
        partner = engine.get_player_definition(partner_id)
        # **The pair is recorded, not the fact that a Double Team
        # happened.** What the next maneuver needs is who
        # challenges it, and that is two named cards; a flag would
        # leave the following turn re-deriving "the nearest
        # teammate" off a board that has moved since.
        match.pending_double_team = [match.challenger_id, partner_id]
        content += (
            f" {engine.format_player_label(match, partner)} "
            "joins them -- and **both** will challenge on the next "
            "maneuver, each adding their defensive skill."
        )

    return content


def apply_pressure_turnover(
    engine: RulesEngine,
    match: MatchState,
    key: str,
    defense_side: TeamSide,
) -> tuple[str, bool, bool]:
    """
    Whether the pressure also took the ball, and what to say about
    it. Returns the text to append, and the two facts the caller
    dispatches on: a Dribble Burst cost paid, and a Defender's
    steal.

    The two are exclusive and in that order -- a burst cost already
    turns the ball over, so the Defender's ability has nothing left
    to take.
    """
    defender = engine.get_player_definition(match.challenger_id)
    content = ""

    # **Dribble Burst's cost**: beaten by a pressure, the offense
    # loses possession *and* the ball keeps whatever speed it was
    # carrying while the defense manipulates it. Neither of those
    # is something a pressure does on its own -- a turnover is the
    # steal's and so is the speed step -- which is what the matrix
    # means by the cost borrowing machinery its defeaters do not
    # have. It is also **the first exception to "every turnover
    # resets ball speed to 1"**, and the reason nothing here sets
    # `match.ball.speed = 1`.
    burst_cost = engine.gambit_cost(match, key) == "dribble_burst"
    if burst_cost:
        match.ball.possession = defense_side
        match.set_ball_carrier(match.challenger_id)
        content += (
            "\n\n# Turnover!\n"
            "**Dribble Burst** was beaten -- "
            f"{format_team_side_label(match.setup_for_side(defense_side))} "
            "take the ball, and it keeps the speed the burst put into "
            f"it ({match.ball.speed})."
        )

    # Role ability -- Defender: also steals the ball on a won
    # pressure, on top of the normal effect above.
    stolen = defender.role == PlayerRole.DEFENDER
    if stolen and not burst_cost:
        match.ball.possession = defense_side
        match.ball.speed = 1
        match.set_ball_carrier(match.challenger_id)
        content += (
            "\n\n# Turnover!\n"
            f"{engine.format_player_label(match, defender)} "
            "steals the ball (Defender ability)! "
            f"{format_team_side_label(match.setup_for_side(defense_side))} "
            "now has possession."
        )

    return content, burst_cost, stolen


def pressure_step(
    engine: RulesEngine,
    match: MatchState,
    key: str,
) -> StepResult:
    """
    Play a won Pressure -- or a Double Team, which is the same card
    at two spaces with a second defender brought in free of
    exhaustion, and the one card whose effect lands on the
    *following* maneuver. The two differ by the push and by that
    partner, so they are one function and a `key`, the way Low Pass
    and Skilled Pass are.

    Rank D3 has no unchallenged branch: a defense card only resolves
    where a defender was sent, so `match.challenger_id` is always the
    player who plays it.

    It reads nothing off the game record -- the shove charges no
    exhaustion, and the cost this card can collect is an engine
    question -- so it takes no `game`.
    """
    offense_side = match.ball.possession
    defense_side = match.defending_side()
    name = engine.maneuver_name(key)
    push = 2 if key == "double_team" else 1

    # Own-goal risk: a pressure is the only thing that threatens
    # one, and only when the ball-holder is already at the space
    # closest to their own goal, i.e. pushing them back further
    # isn't possible.
    origin_flat = match.board.flat_index(
        match.ball.zone, match.ball.space_index,
    )
    target_flat = match.relative_flat_index(
        origin_flat, offense_side, -push,
    )
    overshot = abs(target_flat - origin_flat) < push

    # **Read before anything moves.** The card says "the teammate
    # closest to the space where the play started", and the play
    # started where the ball is standing now -- a moment later the
    # handler has been shoved back two and the ball with them, and
    # the nearest defender to *that* space can be somebody else
    # entirely. Asked here, so the answer is the one the card
    # describes.
    partner_id = (
        engine.double_team_partner(match)
        if key == "double_team"
        else None
    )

    actual_distance = shove_pressured_handler(match, push, partner_id)
    content = pressure_result_text(
        engine, match, key, name, actual_distance, partner_id,
    )

    # Every branch below has moved a meeple: even a shove with
    # nowhere to go walks the challenger onto the handler's space.
    # So `board_changed` is True throughout, which is where
    # `refresh_match_image` sat in the cog on both paths.
    if overshot:
        # An own goal takes priority over the Defender's steal
        # ability: if it's conceded, the point is already over, and
        # stealing a ball that was just kicked off from the restart
        # wouldn't mean anything. So this returns before the
        # turnover below is read at all.
        #
        # **The extra sentence is part of the shove's own block**,
        # not a second one: the blocks are joined on a single space
        # and this paragraph is separated by a blank line, so a
        # block of its own would put a stray space in front of its
        # newlines -- the same reason the Intercept overshoot's
        # sentence rides inside the turnover's.
        return StepResult(
            narration=[
                content + "\n\nThat overshoots toward their own goal!"
            ],
            board_changed=True,
            next=FollowOn(
                FollowOnStep.BEGIN_OWN_GOAL_ROLL, {"distance_moved": 1},
            ),
        )

    turnover_text, burst_cost, stolen = apply_pressure_turnover(
        engine, match, key, defense_side,
    )
    content += turnover_text

    # Fixed 1 space minute per the rules table, independent of
    # clamping, same reasoning as a deflection.
    if burst_cost:
        # The defense has the ball and the speed step the cost
        # granted them, which is the steal's shape: run everyone
        # back first, then let them set the speed.
        following = FollowOn(
            FollowOnStep.BEGIN_RUN_BACK,
            {"speed_choice_after": True, "speed_reset": False},
        )
    elif stolen:
        # The stealing player keeps the ball and stays put --
        # everyone else who's out of position runs back. Read off
        # the carrier set in the shove, not passed in.
        following = FollowOn(FollowOnStep.BEGIN_RUN_BACK)
    else:
        following = FollowOn(
            FollowOnStep.FINISH_MANEUVER_RESOLUTION, {"distance_moved": 1},
        )

    return StepResult(
        narration=[content], board_changed=True, next=following,
    )


def apply_own_goal_outcome(
    engine: RulesEngine,
    match: MatchState,
    offense_player: PlayerDefinition,
    distance_moved: int,
    safe: bool,
    exhaustion_text: str,
) -> str:
    """
    Settle the own-goal roll and word it. Both outcomes restart play,
    which is why the caller's dispatch is the same either way -- what
    differs is whether a goal went on the board.

    The roll itself is still `D12Ball.run_own_goal_roll`'s: it is a
    coach's dice and a dice image, which is the frontend's half. This
    is only what the answer does to the match and what it reads as,
    and **it no longer saves** -- the caller writes the match down
    immediately after it, on both branches, where the conceded one
    used to save in here and the avoided one after two messages had
    gone out. See principle 9 in CLAUDE.md.
    """
    if safe:
        # A new play resets speed same as any other -- see
        # begin_run_back -- and nothing else on this path would,
        # since Pressure's overshoot branch never touches it.
        match.ball.speed = 1
        # The ball stays exactly where the overshot Pressure left
        # it, with no coverage guarantee at all -- not even the
        # standard deal's, since that position is wherever the play
        # happened to reach. So, since 2026-08-24, this owes the
        # same pickup an out-of-bounds ball does rather than a
        # two-sided loose ball: begin_ball_recovery checks
        # eligible_ball_handlers() first and asks nobody when the
        # reset already covers it.
        match.pending_ball_recovery = True
        return f"## Own goal avoided!\n\n{exhaustion_text}"

    conceding_side = match.ball.possession
    # The goal is the other side's; the kick is this player's,
    # and the log says both -- see concede_own_goal.
    match.concede_own_goal(offense_player.player_id)
    match.restart_after_goal(conceding_side)
    match.pending_run_back = True
    match.pending_run_back_distance = distance_moved
    match.pending_run_back_turnover = True
    return (
        f"# Own goal!\n"
        f"{engine.format_player_label(match, offense_player)} "
        "puts it in their own net on "
        f"**{format_goal_time(match.goals[-1])}**.\n"
        f"{team_display_name(match.home.team)} {match.scoreboard.home_score}:"
        f"{match.scoreboard.visiting_score} "
        f"{team_display_name(match.visiting.team)}\n\n"
        f"{exhaustion_text}"
    )


# -- Deflect and Clear -------------------------------------------------


def deflection_numbers(
    defender: PlayerDefinition,
    key: str,
) -> tuple[int, int, bool]:
    """
    How far a deflection drives the ball, how much speed it takes off,
    and whether a Fullback's ability is in it.

    **The speed drop is the card's, not the distance's.** A Fullback's
    Deflect has always moved the ball 2 and dropped the speed by 1, so
    the two are separate numbers that happen to match on an ordinary
    deflection -- and a Clear's -3 stays -3 when the Fullback pushes it
    to 4 spaces. Derived from the distance instead, this read correctly
    right up until the Fullback was let near a Clear, which is why they
    are returned as two numbers rather than one.
    """
    # Role ability -- Fullback: +1 space on a deflection, which takes a
    # Deflect from 1 to 2 and a Clear from 3 to 4.
    fullback_bonus = defender.role == PlayerRole.FULLBACK
    base_distance = 3 if key == "clear" else 1

    return (
        base_distance + (1 if fullback_bonus else 0),
        base_distance,
        fullback_bonus,
    )


def knock_ball_back(
    match: MatchState,
    offense_side: TeamSide,
    deflect_distance: int,
    speed_drop: int,
) -> tuple[bool, int]:
    """
    Drive the ball back toward the offense's own goal and take the
    speed off it. Returns whether it ran out of field and how far it
    actually went.

    The overshoot is read before the ball moves, the way every other
    overshoot in the game is. It no longer risks an own goal -- only
    Pressure does -- it sets up a scoring opportunity for the defense
    instead, who are now the side standing next to the goal the ball
    just reached.
    """
    origin_flat = match.board.flat_index(
        match.ball.zone, match.ball.space_index,
    )
    target_flat = match.relative_flat_index(
        origin_flat, offense_side, -deflect_distance,
    )
    overshot = abs(target_flat - origin_flat) < deflect_distance

    actual_distance = match.move_ball_relative(
        offense_side, -deflect_distance,
    )
    match.ball.speed = max(1, match.ball.speed - speed_drop)

    return overshot, actual_distance


def deflection_step(
    engine: RulesEngine,
    match: MatchState,
    key: str,
) -> StepResult:
    """
    Play a won Deflect -- or a Clear, which is the same card at three
    spaces and three points of speed.

    The card knocks the ball out of *everybody's* hands, which is what
    makes all three of its endings loose-ball-shaped rather than
    turnover-shaped: nobody gained possession, so nothing runs back and
    there is no speed reset to skip. What differs between them is only
    where the ball is lying when the question is asked.
    """
    offense_side = match.ball.possession
    defense_side = match.defending_side()
    defender = engine.get_player_definition(match.challenger_id)
    name = engine.maneuver_name(key)

    deflect_distance, speed_drop, fullback_bonus = deflection_numbers(
        defender, key,
    )

    overshot, actual_distance = knock_ball_back(
        match, offense_side, deflect_distance, speed_drop,
    )

    space_word = "space" if actual_distance == 1 else "spaces"
    ability_note = " (Fullback ability)" if fullback_bonus else ""
    content = (
        f"**{name}:** the ball moves {actual_distance} "
        f"{space_word} back{ability_note}. Ball speed is now "
        f"{match.ball.speed}."
    )

    # **The board moved on every branch below**, so `board_changed` is
    # True throughout -- the ball was driven back and the speed came
    # off it. That is *not* the same question as "was the persistent
    # board message written", which two of the three branches answer
    # no to: `begin_loose_ball` draws the board under its own
    # announcement, so the frontend skips a write it is about to make
    # anyway. That suppression lives with the frontend
    # (`FOLLOW_ONS_THAT_DRAW_THE_BOARD` in `cogs/d12ball/core.py`), because it
    # is a rate-limit
    # economy and rate limits are the frontend's -- principle 8 in
    # CLAUDE.md. A web app has no five-in-five bucket and should redraw
    # on all three.

    # A shot has to be within shooting range, and this one always is:
    # an overshoot means the ball reached the space closest to the
    # offense's own goal, which is as deep into the deflecting team's
    # range as the field goes. So this asks
    # scoring_opportunity_candidates with no range check over it -- the
    # check could never fail here, and a branch that cannot be taken
    # reads as if it could.
    candidates = []
    if overshot:
        candidates = engine.scoring_opportunity_candidates(
            match, defense_side,
        )

    if candidates:
        # A defender standing right where the ball ends up gets a shot
        # at the goal it's now next to -- that's a turnover before the
        # shot, same as any other change of possession, so the score
        # attempt reads the correct attacking and defending sides.
        match.ball.possession = defense_side
        match.ball.speed = 1
        return StepResult(
            narration=[
                content,
                "That overshoots the field -- a scoring opportunity!",
            ],
            board_changed=True,
            next=FollowOn(
                FollowOnStep.BEGIN_SHOOTER_CHOICE,
                {"candidates": candidates},
            ),
        )

    # **Setup Pass's cost**: beaten by a deflection, the defending
    # coach drives the ball back a further 1, 2 or 3 spaces and it is
    # loose where it stops. It is asked here rather than as a step
    # after the maneuver because a deflection already ends in a loose
    # ball -- the cost only decides where it lies. Not asked when the
    # deflection overshot into a shot above: the ball is already as far
    # back as the field goes and the shot is the bigger thing
    # happening.
    if engine.gambit_cost(match, key) == "setup_pass":
        return StepResult(
            narration=[content],
            board_changed=True,
            next=FollowOn(FollowOnStep.OFFER_SETUP_PASS_PUSH_BACK),
        )

    # A deflection knocks the ball out of anybody's possession, so it
    # does not go through finish_maneuver_resolution's ordinary
    # loose-ball check: that check asks whether the possessing team has
    # somebody on the ball, and here the answer does not matter --
    # either side's occupant is equally dispossessed.
    #
    # **Occupancy decides how it is won**, which since 2026-08-26 is
    # the rule everywhere rather than this card's own: an empty landing
    # space is a loose ball (each side may send someone); a space only
    # one side occupies is theirs outright, with no send offered to the
    # other; a space both occupy is a contest between the players
    # already there. See `D12Ball.begin_loose_ball`.
    #
    # A deflection's time cost is a fixed 1 space minute per the rules
    # table, not "distance traveled" like Low/High Pass, so this
    # doesn't shrink if the move was clamped at the edge (or grow with
    # the Fullback's extra distance, or Clear's).
    return StepResult(
        narration=[content],
        board_changed=True,
        next=FollowOn(
            FollowOnStep.BEGIN_LOOSE_BALL, {"distance_moved": 1},
        ),
    )


def throw_high_pass(
    match: MatchState,
    offense_side: TeamSide,
    distance: int,
    handler: PlayerDefinition,
) -> tuple[bool, int, str]:
    """
    Put the ball in the air and say what that looked like.

    Returns whether the throw overshot, how far the ball actually
    travelled, and the line every branch of the pass opens with.
    The overshoot is read **before** the ball moves, the same way
    Deflect reads its own and by the same test, so a pass that
    could not move the ball at all is an overshoot like any other
    -- which is the whole reason this is one function and not the
    caller's first three statements.
    """
    # Role ability -- Fullback: can choose to pass up to 4 spaces
    # instead of the usual 2-3 max (see HighPassChoiceView).
    fullback_bonus = handler.role == PlayerRole.FULLBACK and distance == 4

    overshot = match.high_pass_overshoots(offense_side, distance)

    actual_distance = match.move_ball_relative(offense_side, distance)

    ability_note = " (Fullback ability)" if fullback_bonus else ""
    if actual_distance:
        space_word = "space" if actual_distance == 1 else "spaces"
        content = (
            f"**High Pass:** the ball moves {actual_distance} "
            f"{space_word} forward{ability_note}."
        )
    else:
        # Thrown from the final space, so the clamp leaves the ball
        # exactly where it was. Worth saying in words rather than
        # as "moves 0 spaces forward", which reads as a bug -- and
        # a coach sees it now that the passer cannot shoot off it.
        content = (
            "**High Pass:** the ball is thrown up from the last space "
            "and comes straight back down on it."
        )

    return overshot, actual_distance, content


def send_ball_out_of_play(match: MatchState) -> str:
    """
    The ball went dead: the other team gains possession, the speed
    resets, nobody is carrying it, and the side that gained it owes a
    pickup. Returns that side, worded.

    Both passes of rank O3 reach this and nothing else does -- a High
    Pass with nowhere left to throw it, and a Setup Pass with nowhere
    to pick it out to. They say different things about how they got
    here, which is why the sentence is each branch's and only the
    state is shared. See `D12Ball.begin_run_back`'s `new_play`: this
    is the fourth of the four call sites that open one, and it is one
    for the same reason the other three are -- the ball went dead
    rather than being taken off anybody.
    """
    match.ball.possession = match.defending_side()
    match.ball.speed = 1
    match.clear_ball_carrier()
    match.pending_ball_recovery = True
    return format_team_side_label(
        match.setup_for_side(match.ball.possession),
    )


def high_pass_step(
    engine: RulesEngine,
    match: MatchState,
    distance: int,
) -> StepResult:
    """
    Play a won High Pass: put the ball in the air and settle what it
    found where it came down.

    **The hardest card of the twelve, and it is the landing space that
    makes it so.** Every branch below is one question asked of one
    position -- who of the passing side is standing where the ball
    landed, whether the ball got there at all, and whether the space
    is inside the passing side's shooting range -- and the six answers
    are six different endings. The order they are asked in carries the
    rules: an overshoot's set-up subsumes the ordinary one, a pass of
    2 is never made to win a contest, and a throw the field clamped to
    nothing goes out rather than staying with the passer.

    It reads nothing off the game record -- the gambit's cost is an
    engine question and nothing here charges exhaustion -- so it takes
    no `game`.
    """
    offense_side = match.ball.possession
    handler = engine.get_player_definition(match.active_player_id)

    overshot, actual_distance, content = throw_high_pass(
        match, offense_side, distance, handler,
    )

    # High Pass's own cost is a flat 2 space minutes regardless of
    # distance (2026-08-16) -- the one maneuver that isn't 1. Kept
    # apart from `actual_distance`, which is what the pass actually
    # did and what the result says.
    distance_moved = 2

    # Who this pass reached, read once now the ball has landed and
    # asked by every branch below -- the passer is not among them,
    # whatever the distance. See high_pass_receiver_candidates.
    receiver_candidates = engine.high_pass_receiver_candidates(
        match, offense_side,
    )

    # **The ball moved on every branch below**, or the speed came off
    # it, so `board_changed` is True throughout. That is not the same
    # question as "was the persistent board message written": the
    # branch that goes out of play hands over to a new play, which
    # posts and pins a board of its own, so the frontend skips a write
    # it is about to make anyway. That suppression lives with the
    # frontend (`follow_on_draws_the_board` in `cogs/d12ball/core.py`),
    # because it is a rate-limit economy and rate limits are the
    # frontend's -- principle 8 in CLAUDE.md.

    # An overshoot sets up a scoring opportunity whatever distance
    # was asked for (2026-08-10), on the space closest to the goal
    # -- which is where the clamp has just put the ball. The shot
    # is always legal there, as deep into the offense's own
    # shooting range as the field goes, so no range check: it could
    # never fail here, and a branch that cannot be taken reads as
    # if it could. Checked ahead of the ordinary 2-space set-up
    # below, which it subsumes -- the same shot is offered, but
    # with the modifier the other way round and a contest behind
    # it.
    if overshot and receiver_candidates:
        return offer_overshoot_set_up(
            match,
            shooter_id=receiver_candidates[0],
            distance_moved=distance_moved,
            lead_in=content,
        )
    # Nobody the pass could reach on the landing space leaves
    # nothing to set up, so an overshoot falls through to the
    # ordinary paths below: a loose ball, a clean turnover, or --
    # the case the passer exclusion opened (2026-08-12) -- the
    # passer keeping a ball that never left them.

    # A pass of 2 is received cleanly: no contest at all
    # (2026-08-07), and it may set up a scoring opportunity for
    # whoever it lands on -- unlike the old fixed-2 High Pass,
    # this no longer requires overshooting the field. A longer
    # pass never offers it, whether or not it happens to overshoot.
    #
    # A set-up's shot is an ordinary score attempt and obeys the
    # same rule about where a shot may be taken from: what the
    # set-up buys is the shot out of turn, not a shot from
    # anywhere. Out of range the pass is still received, which the
    # branch below settles -- the range rule takes away the shot,
    # not the catch.
    setup_candidates = []
    if distance == 2 and match.can_attempt_score(offense_side):
        setup_candidates = receiver_candidates

    if setup_candidates:
        # Received, so the receiver carries it -- set before the
        # set-up is offered, because declining resolves this as an
        # ordinary completed pass and the carrier has to survive
        # that. Taking the shot makes it moot: a goal or a miss is
        # a new play, which clears the carrier.
        match.set_ball_carrier(setup_candidates[0])
        return StepResult(
            narration=[
                content,
                "That reaches a teammate -- a scoring opportunity!",
            ],
            board_changed=True,
            next=FollowOn(
                FollowOnStep.OFFER_SCORING_ATTEMPT_CHOICE,
                {
                    "shooter_id": setup_candidates[0],
                    "distance_moved": distance_moved,
                },
            ),
        )

    # No scoring-opportunity option (or the requested distance
    # wasn't a 2). If the pass reached nobody, this isn't the High
    # Pass "receiver must win a skill test" contest at all -- it's
    # a plain loose ball, exactly like any other maneuver that
    # overshoots into empty territory.

    # A 2-space pass that found its receiver but not shooting range
    # is just a pass: it was received cleanly, and the only thing
    # the range rule takes away is the shot. Falling through would
    # hand it to the long-pass contest below, which a pass of 2 has
    # never had to win.
    if distance == 2 and receiver_candidates:
        # Caught cleanly, just out of shooting range -- the range
        # rule takes away the shot, not the catch, so the receiver
        # still carries it.
        return complete_high_pass_reception(
            match, receiver_candidates[0], distance_moved, content,
        )

    if not receiver_candidates:
        # **A passer never receives their own pass, and since
        # 2026-08-24 that is no longer a free ride.** The exclusion
        # above can only bite when the field clamped the throw to 0
        # spaces -- a High Pass moves the ball, not the handler, so
        # that is the only way the passer is still standing where
        # it lands. With nobody else there either, this is a throw
        # with nowhere to go: there was no field left to put it on
        # and no teammate to put it to, so it goes out exactly as a
        # Setup Pass with no legal destination does, rather than
        # quietly staying with the passer. `actual_distance` (not
        # `distance`) is the test, because that's what tells the
        # ball genuinely didn't move from a real empty destination
        # elsewhere on the field -- which stays an ordinary loose
        # ball below.
        if actual_distance == 0:
            gaining = send_ball_out_of_play(match)
            return StepResult(
                narration=[
                    content,
                    "There is nowhere left to throw it and nobody "
                    "to receive it there -- the ball goes out of play. "
                    f"{gaining} gain possession.",
                ],
                board_changed=True,
                next=FollowOn(
                    FollowOnStep.BEGIN_RUN_BACK,
                    {
                        "new_play": True,
                        "distance_moved": distance_moved,
                    },
                ),
            )
        return StepResult(
            narration=[content],
            board_changed=True,
            next=FollowOn(
                FollowOnStep.FINISH_MANEUVER_RESOLUTION,
                {"distance_moved": distance_moved},
            ),
        )

    # **Intercept's cost**: beaten by a High Pass, the reception is
    # not contested -- the receiver simply keeps it. It is the one
    # of the six costs that can be inert, and this is the only
    # branch it is not: a pass of 2, an overshoot's set-up and a
    # pass reaching nobody have all already returned above, and
    # none of them had a contest to skip.
    if engine.gambit_cost(match, "high_pass") == "intercept":
        receiver = engine.get_player_definition(receiver_candidates[0])
        return complete_high_pass_reception(
            match,
            receiver_candidates[0],
            distance_moved,
            # One block, not two: the blocks are joined on a single
            # space, so a paragraph opened with a blank line rides
            # inside the sentence it is charged against rather than
            # arriving with a stray space in front of its newlines.
            f"{content}\n\n**Intercept** was beaten -- the "
            "reception is not contested, and "
            f"{engine.format_player_label(match, receiver)} "
            "keeps the ball.",
        )

    # A teammate is standing right where the pass landed, and the
    # pass went 3 or more -- a distance of 2 with a teammate there
    # took the set-up branch above, since both branches ask
    # high_pass_receiver_candidates the same question. A long
    # High Pass still forces a skill test to keep the ball, unlike
    # any other maneuver.
    return StepResult(
        narration=[content],
        board_changed=True,
        next=FollowOn(
            FollowOnStep.BEGIN_HIGH_PASS_CONTEST,
            {"distance_moved": distance_moved},
        ),
    )


def complete_high_pass_reception(
    match: MatchState,
    receiver_id: str,
    distance_moved: int,
    content: str,
) -> StepResult:
    """
    A pass that was caught and settles there: the receiver carries
    it, and the maneuver ends without a contest.

    Two branches reach this -- a 2-space pass out of shooting
    range, and a pass whose contest a beaten Intercept called off.
    They differ in what they say and in nothing else.
    """
    match.set_ball_carrier(receiver_id)
    return StepResult(
        narration=[content],
        board_changed=True,
        next=FollowOn(
            FollowOnStep.FINISH_MANEUVER_RESOLUTION,
            {"distance_moved": distance_moved},
        ),
    )


def offer_overshoot_set_up(
    match: MatchState,
    *,
    shooter_id: str,
    distance_moved: int,
    lead_in: str,
) -> StepResult:
    """
    The scoring opportunity a High Pass that ran out of field sets
    up (2026-08-10) -- see "High Pass" in the living rules.

    The pass arrived faster than the receiver could settle it, so
    `pending_high_pass_overshoot` turns the ball speed modifier
    around for everything the overshoot leads to: this shot, and
    the long-pass contest behind it. It is set before either is
    offered, and cleared with the rest of the turn by
    reset_maneuver.

    **The two are one choice, not an offer and a fallback.** An
    overshoot is a shot at a disadvantage or a contest to keep the
    ball, both paying the modifier, so declining always lands in
    the contest -- there is no distance here that resolves as a
    settled pass. A distance of 2 could only overshoot from a
    position where no distance was ever offered (see
    `D12Ball.resolve_high_pass`), so the ordinary "a pass of 2 is
    received, full stop" rule and this one never meet.
    """
    match.pending_high_pass_overshoot = True
    # Received, so the receiver carries it -- set before the
    # set-up is offered, for the same reason the ordinary 2-space
    # set-up does it: declining can resolve this as a completed
    # pass, and the carrier has to survive that.
    match.set_ball_carrier(shooter_id)

    penalty = match.ball_speed_modifier()
    # A move that costs nothing says nothing: the modifier is the
    # speed halved and rounded down, so a walking ball pays none and
    # the note is absent rather than reading "(0)".
    speed_note = (
        " The ball comes in too fast to settle -- the ball speed "
        f"modifier counts **against** what follows ({penalty})."
        if penalty
        else ""
    )
    return StepResult(
        narration=[
            lead_in,
            "That overshoots the field -- a scoring "
            f"opportunity!{speed_note}",
        ],
        board_changed=True,
        next=FollowOn(
            FollowOnStep.OFFER_SCORING_ATTEMPT_CHOICE,
            {
                "shooter_id": shooter_id,
                "distance_moved": distance_moved,
                "contest_on_decline": True,
            },
        ),
    )


def setup_pass_speed_step(
    engine: RulesEngine,
    match: MatchState,
) -> StepResult:
    """
    Setup Pass, the High Pass gambit, in its first half: **adjust ball
    speed up to the passer's offensive skill, and then** pick the pass
    out.

    The order is the card's and it is the reason this is two prompts
    rather than one. A speed choice has always been the *last* human
    step of an effect, leading straight into
    `finish_maneuver_resolution`; here it is the first, so what comes
    after it is recorded as an effect continuation and picked up by
    `D12Ball.continue_effect`. A restart between the two comes back to
    whichever prompt is up, and the continuation is persisted so the
    pass is not lost with it.

    **Nothing on the board moves here**, which is what makes this the
    one step of the rank whose `board_changed` is False: the speed is
    set by the choice this hands off to, not by the card.
    """
    passer = engine.get_player_definition(match.active_player_id)
    match.pending_effect_continuation = {"kind": "setup_pass_shot"}
    return StepResult(
        narration=[
            "**Setup Pass:** "
            f"{engine.format_player_label(match, passer)} "
            "sets the ball's speed before picking out the pass."
        ],
        next=FollowOn(
            FollowOnStep.OFFER_SPEED_CHOICE,
            {
                "player_id": match.active_player_id,
                "skill_type": "offense",
                "distance_moved": SETUP_PASS_CLOCK_COST,
            },
        ),
    )


def setup_pass_step(
    engine: RulesEngine,
    match: MatchState,
    distance: int,
) -> StepResult:
    """
    Setup Pass's second half: the ball goes 0, 1 or 3 spaces, and a
    teammate standing where it lands takes a scoring opportunity.

    **Every distance that fits on the field is offered**, whether or
    not anybody of the passing side is standing there, so all three
    endings below are real outcomes rather than one outcome and two
    guards -- see `RulesEngine.setup_pass_distances`.
    """
    offense_side = match.ball.possession
    # Applied, so the continuation is spent -- see
    # `D12Ball.continue_effect` for why it survived until now.
    match.pending_effect_continuation = None
    actual_distance = match.move_ball_relative(offense_side, distance)
    receivers = engine.high_pass_receiver_candidates(match, offense_side)

    if not receivers:
        if actual_distance == 0:
            # Only reachable from a stale click: 0 is offered only
            # while a teammate shares the passer's space, and every
            # other distance is offered only where it fits on the
            # field, so nothing legal clamps to a standing still.
            # A ball that never left the passer is the High Pass's
            # own 0-space case -- nowhere to throw it and nobody to
            # throw it to -- so it goes out rather than settling
            # under the passer's own feet.
            return setup_pass_out_step(match)

        # **A pass that lands on nobody is still a pass**
        # (2026-08-25). The card is a set-up, but missing the
        # set-up does not un-throw the ball: it settles exactly
        # where a Deflect's does, so occupancy is what decides it
        # -- loose on an empty space, the other side's outright
        # where only they are standing. Refusing the distance
        # instead is what used to make this the only pass in the
        # game that could not be thrown badly.
        #
        # The board moved and the frontend writes no board in front
        # of this: `begin_loose_ball` posts one with its own
        # announcement, which is `FOLLOW_ONS_THAT_DRAW_THE_BOARD`'s
        # answer and rank D1's rather than this card's.
        space_word = "space" if actual_distance == 1 else "spaces"
        return StepResult(
            narration=[
                "**Setup Pass:** the ball is picked out "
                f"{actual_distance} {space_word} forward, with nobody "
                "there to set up."
            ],
            board_changed=True,
            next=FollowOn(
                FollowOnStep.BEGIN_LOOSE_BALL,
                {"distance_moved": SETUP_PASS_CLOCK_COST},
            ),
        )

    receiver_id = receivers[0]
    match.set_ball_carrier(receiver_id)

    receiver = engine.get_player_definition(receiver_id)
    space_word = "space" if actual_distance == 1 else "spaces"
    movement = (
        "goes to a teammate in the same space"
        if distance == 0
        else f"moves {actual_distance} {space_word} forward"
    )
    return StepResult(
        narration=[
            f"**Setup Pass:** the ball {movement} to "
            f"{engine.format_player_label(match, receiver)} "
            f"-- a scoring opportunity! Ball speed is {match.ball.speed}."
        ],
        board_changed=True,
        next=FollowOn(
            FollowOnStep.OFFER_SCORING_ATTEMPT_CHOICE,
            {
                "shooter_id": receiver_id,
                "distance_moved": SETUP_PASS_CLOCK_COST,
            },
        ),
    )


def setup_pass_out_step(match: MatchState) -> StepResult:
    """
    **Setup Pass cannot overshoot**, so the only way it runs out of
    play is having nowhere to throw it at all: the passer on the very
    last space of the field -- the one position from which even 1
    space runs off the end -- with no teammate beside them to take it
    at 0. Then the other team gains possession: a new play, both sides
    reset, and the gaining side sends the nearest player to fetch the
    ball -- the out-of-bounds outcome the game already has.

    Any other landing space is a pass that happened; see
    `setup_pass_step`, which leaves the ball lying there.

    Two things reach it: the menu with no distance to offer
    (`D12Ball.offer_setup_pass_distance`) and the stale click that
    picks a 0 nobody is standing on, which is why it is its own step
    rather than a branch of the pass.
    """
    match.pending_effect_continuation = None
    gaining = send_ball_out_of_play(match)
    return StepResult(
        narration=[
            "**Setup Pass:** there is nobody to pick the ball out to, "
            f"so it runs out of play. {gaining} gain possession."
        ],
        board_changed=True,
        next=FollowOn(
            FollowOnStep.BEGIN_RUN_BACK,
            {
                "new_play": True,
                "distance_moved": SETUP_PASS_CLOCK_COST,
            },
        ),
    )


@dataclass(frozen=True)
class OwnGoalRoll:
    """
    What an own-goal roll turned out to be, before anything is drawn
    or said about it.

    A record rather than a `StepResult` for `apply_own_goal_outcome`'s
    reason: the roll is a coach's dice and a dice image, and the two
    messages it becomes are shaped around that image. What is a rule
    is the arithmetic, the token and the event -- and that is all of
    this.
    """

    rolls: tuple[int, int]
    offense_skill: int
    ignite: object
    overdrive: int
    safe: bool
    exhaustion_text: str
    distance_moved: int


def roll_own_goal(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
) -> OwnGoalRoll:
    """
    The roll itself, off the button the own-goal prompt posted: 2d12
    at an advantage (take the higher), plus the ball-handler's
    offensive skill, safe on 7+.

    Making the attempt costs the rolling player 1 exhaust token, win
    or lose, on top of whatever the maneuver that triggered the risk
    already charged. It is not a skill test, so it owes no injury
    check.
    """
    distance_moved = match.pending_own_goal_distance
    match.pending_own_goal = False

    offense_player = engine.get_player_definition(match.active_player_id)
    offense_skill = engine.player_catalog.effective_profile(
        offense_player,
    ).offense

    rolls = (random.randint(1, 12), random.randint(1, 12))
    # Volatile reads the die that is **kept**, not both: an own goal is
    # rolled at an advantage, and the rules name "the die kept in an
    # own-goal roll".
    ignite = engine.ignite(game, offense_player.player_id, max(rolls))
    overdrive = match.overdrive_modifier(offense_player.player_id)
    match.consume_overdrive()
    safe = max(rolls) + offense_skill + ignite.modifier + overdrive >= 7

    # Logged ahead of `apply_own_goal_outcome`, which is what concedes
    # the goal, so the risk sits above the goal it sometimes produced.
    # Both outcomes, for the reason the injury test logs both: the
    # interesting number is how often a Pressure that risks an own goal
    # actually costs one, and that needs the attempts as well as the
    # concessions.
    match.record_event(
        EVENT_OWN_GOAL_ROLL,
        side=match.ball.possession,
        player_id=offense_player.player_id,
        conceded=not safe,
        rolls=list(rolls),
        offense_skill=offense_skill,
    )

    # Charged before either branch saves the match, so the token and
    # any Exhausted flag it sets are written out with the rest of the
    # roll's outcome -- see `RulesEngine.apply_exhaustion`.
    exhaustion_text = engine.apply_exhaustion(
        game, match, offense_player.player_id, 1,
    )

    return OwnGoalRoll(
        rolls=rolls,
        offense_skill=offense_skill,
        ignite=ignite,
        overdrive=overdrive,
        safe=safe,
        exhaustion_text=exhaustion_text,
        distance_moved=distance_moved,
    )
