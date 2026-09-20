"""
What a maneuver does when it wins, as flow steps.

One function per card, each taking the engine and the match, changing
the match, and handing back a `StepResult`. Ten of the twelve are
here -- rank O1's two, rank O2's two, rank D1's two, rank D2's two and
rank D3's two -- as seven functions, since six of the cards are their
rank-mate parameterised. The two still `cogs/d12ball/effects.py`'s are
rank O3's (High Pass, Setup Pass), until Phase 3 of
docs/model-discord-split.md lifts them. See "Maneuvers" in
docs/design/maneuvers.md for what each card actually does.

A step takes `(engine, match, ...)`, and `game` only where it
actually reads the record -- `low_pass_step`, `steal_step`,
`pressure_step` and `deflect_step` do not and so do not take one;
both dribbles do,
because charging an
exhaustion token tests a threshold the game record decides (a
Cyborg's is a flat 7, see `RulesEngine.exhaustion_threshold`). None of
them takes an `interaction`, ever: that is the single clearest test of
which side of the seam a function has ended up on, and it is
greppable.

**A rank's two cards are one function wherever they differ by a
parameter**: Low Pass and Skilled Pass by `key`, Steal and Intercept
by the sign of the carry, Pressure and Double Team by the push and the
partner it brings in, Deflect and Clear by the distance driven and the
speed taken off. Only the dribbles needed two, and they have different
costs rather than different signs.

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
    burst_cost = engine.advanced_cost(match, key) == "dribble_burst"
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


def deflection_numbers(
    defender: PlayerDefinition,
    key: str,
) -> tuple[int, int, bool]:
    """
    How far a deflection drives the ball, how much speed it takes
    off, and whether a Fullback's ability is in it.

    **The speed drop is the card's, not the distance's.** A
    Fullback's Deflect has always moved the ball 2 and dropped the
    speed by 1, so the two are separate numbers that happen to
    match on an ordinary deflection -- and a Clear's -3 stays -3
    when the Fullback pushes it to 4 spaces. Derived from the
    distance instead, this read correctly right up until the
    Fullback was let near a Clear, which is why they are returned
    as two numbers rather than one.
    """
    # Role ability -- Fullback: +1 space on a deflection, which
    # takes a Deflect from 1 to 2 and a Clear from 3 to 4.
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
    speed off it. Returns whether it ran out of field and how far
    it actually went.

    The overshoot is read before the ball moves, the way every
    other overshoot in the game is. It no longer risks an own goal
    -- only Pressure does -- it sets up a scoring opportunity for
    the defense instead, who are now the side standing next to the
    goal the ball just reached.
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


def deflect_step(
    engine: RulesEngine,
    match: MatchState,
    key: str,
) -> StepResult:
    """
    Play a won Deflect -- or a Clear, which is Deflect at three
    spaces with three steps of speed taken off instead of one.
    Everything else about it, the overshoot and the loose ball it
    leaves behind alike, is the same card, so the two are one
    function and a `key`.

    **A Fullback's Clear goes back 4** (the author, 2026-08-19). Its
    sentence reads "Block deflect: ball goes back 2 spaces", which
    read as a number is a *reduction* against a 3-space clearance and
    read as the rule behind the number is the +1 that takes a basic
    deflection from 1 to 2. The rule is what carries -- see
    `deflection_numbers`, where the distance and the speed drop are
    two numbers for exactly this reason.

    Rank D1 has no unchallenged branch: a defense card only resolves
    where a defender was sent, so `match.challenger_id` is always the
    player who plays it.

    It reads nothing off the game record -- a deflection charges no
    exhaustion, and the cost it can collect is an engine question --
    so it takes no `game`.
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

    # **The board moved on every branch below**, and it moved here:
    # the ball has been driven back and has lost a step of speed,
    # which the last branch is worth saying out loud about because
    # the field clamped its distance to nothing. `board_changed` is
    # what is true of the position; how many times the persistent
    # board message is actually written is the frontend's, and two
    # of the three branches hand over to something that draws it
    # under its own announcement -- see
    # `D12Ball.follow_on_posts_its_own_board` and "Discord's rate
    # limits" in docs/design/rate-limits.md.
    #
    # A shot has to be within shooting range, and this one always
    # is: an overshoot means the ball reached the space closest to
    # the offense's own goal, which is as deep into the deflecting
    # team's range as the field goes. So this asks
    # scoring_opportunity_candidates with no range check over it --
    # the check could never fail here, and a branch that cannot be
    # taken reads as if it could.
    candidates = []
    if overshot:
        candidates = engine.scoring_opportunity_candidates(
            match, defense_side,
        )

    if candidates:
        # A defender standing right where the ball ends up gets a
        # shot at the goal it's now next to -- that's a turnover
        # before the shot, same as any other change of possession,
        # so the score attempt reads the correct attacking and
        # defending sides.
        #
        # **After the sentence, not before it**: the speed the
        # deflection left is what the narration reports, and the
        # turnover's reset to 1 is a separate thing happening to the
        # same number.
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
    # coach drives the ball a further 1, 2 or 3 spaces back and it
    # is loose where it stops. It is charged here rather than as a
    # step after the maneuver because a deflection already ends in
    # a loose ball -- the cost only decides where it lies. Not
    # charged when the deflection overshot into a shot above: the
    # ball is already as far back as the field goes and the shot is
    # the bigger thing happening.
    #
    # A follow-on rather than a prompt this step returns, for
    # `offer_speed_choice`'s reason: whether anybody is asked at all
    # is still the cog's, since Dinky drives it back itself and a
    # push with no room left is not offered to anyone.
    if engine.advanced_cost(match, key) == "setup_pass":
        return StepResult(
            narration=[content],
            board_changed=True,
            next=FollowOn(FollowOnStep.OFFER_SETUP_PASS_PUSH_BACK),
        )

    # A deflection knocks the ball out of anybody's possession, so
    # it does not go through finish_maneuver_resolution's ordinary
    # loose-ball check: that check asks whether the possessing team
    # has somebody on the ball, and here the answer does not
    # matter -- either side's occupant is equally dispossessed.
    #
    # **Occupancy decides how it is won**, which since 2026-08-26
    # is the rule everywhere rather than this card's own: an empty
    # landing space is a loose ball (each side may send someone); a
    # space only one side occupies is theirs outright, with no send
    # offered to the other; a space both occupy is a contest
    # between the players already there. See begin_loose_ball.
    #
    # A deflection's time cost is a fixed 1 space minute per the
    # rules table, not "distance traveled" like Low/High Pass, so
    # this doesn't shrink if the move was clamped at the edge (or
    # grow with the Fullback's extra distance, or Clear's).
    return StepResult(
        narration=[content],
        board_changed=True,
        next=FollowOn(FollowOnStep.BEGIN_LOOSE_BALL, {"distance_moved": 1}),
    )
