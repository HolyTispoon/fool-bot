"""
What a maneuver does when it wins, as flow steps.

One function per card, each taking the engine and the match, changing
the match, and handing back a `StepResult`. Low Pass is here; the other
eleven are still `cogs/d12ball/effects.py`'s until Phase 3 of
docs/model-discord-split.md lifts them a rank at a time. See
"Maneuvers" in docs/design/maneuvers.md for what each card actually
does.

A step takes `(engine, match, ...)`. The game record is not a
parameter here because nothing Low Pass decides reads it -- a step that
does read it (an advanced-mode switch, an AI side) takes `game` as
well, the way `d12ball.prompts.pending_prompt` does. None of them takes
an `interaction`, ever: that is the single clearest test of which side
of the seam a function has ended up on, and it is greppable.

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
