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
parameter**: Low Pass and Pinpoint by `key`, Steal and Intercept
by the sign of the carry, Pressure and Double Team by the push and the
partner it brings in, Deflect and Clear by the distance and the speed
drop. The dribbles needed two, because they have different costs
rather than different signs -- and so does rank O3, whose two cards
share a landing space and nothing else: a High Pass throws forward and
may reach the goal zone, a Cross picks the ball out and never does, and the
Cross is two steps because its speed choice comes first.

**Nothing here saves.** The caller persists once, immediately after the
step and before dispatching whatever comes next -- see
`D12Ball.apply_low_pass` and principle 9 in CLAUDE.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from d12ball import tutorial
from d12ball.components import (
    BALL_SPEED_MAX,
    DRIBBLE_BURST_MAX_DISTANCE,
    EVENT_OWN_GOAL_ROLL,
    MIN_HIGH_PASS_DISTANCE,
    MatchState,
    PlayerDefinition,
    PlayerRole,
    SETUP_PASS_CLOCK_COST,
    SKILLED_PASS_REACH,
    SPECIES_TELEKINETIC,
    TeamSide,
)
from d12ball.engine import RulesEngine
from d12ball.flow import gates
from d12ball.flow.clock import charge_maneuver_clock
from d12ball.flow.result import (
    TURNOVER_HEADING,
    FollowOn,
    FollowOnStep,
    Headline,
    StepResult,
)
from d12ball.flow.turn import record_maneuver, scripted_or_random, tutorial_beat
from d12ball.formatting import (
    ball_space_phrase,
    format_goal_time,
    format_player_with_team,
    format_team_side_label,
    space_label,
    score_side_label,
)
from d12ball import tokens
from d12ball.game import D12BallGame
from d12ball.special_abilities import (
    INFERNO_BALL_SPEED,
    PULSAR_CHARGE_UP,
    QUANTOR_RUN_DRAIN,
    VORIX_BALL_SPEED,
    VORIX_PASS_DISTANCE,
    SpecialAbility,
)
from d12ball.prompts import (
    PendingPrompt,
    PromptKind,
    double_team_partner_prompt,
    passer_advance_prompt,
    speed_choice_ask,
)


#: How far a Low Pass with nobody to receive it rolls the ball (Law
#: 6.5.5, the author 2026-10-07). A Pinpoint's rolls its reach,
#: `SKILLED_PASS_REACH`.
LOW_PASS_NOBODY_ROLL = 2


def send_low_pass(
    engine: RulesEngine,
    match: MatchState,
    offense_side: TeamSide,
    distance: int,
    key: str,
    receiver_id: Optional[str],
) -> int:
    """
    Move the ball, step its speed up, and hand it to whoever the
    pass was aimed at. Returns how far the ball went. The passer
    stays where they are: whether they move is their coach's to say,
    afterwards (`offer_passer_advance`).
    """
    actual_distance = match.move_ball_relative(offense_side, distance)
    match.ball.speed = min(
        12, match.ball.speed + engine.pass_speed_bonus(key)
    )
    # The pass was aimed at somebody, and it is the same somebody a
    # Winger's set-up would hand the shot to -- so they receive it
    # and take the next turn. A receiver of None means the pass had
    # no legal destination, which rolls the ball forward loose
    # instead of completing; nobody carries a loose ball.
    match.set_ball_carrier(receiver_id)

    return actual_distance


def low_pass_movement_note(
    engine: RulesEngine,
    match: MatchState,
    handler: PlayerDefinition,
    distance: int,
    actual_distance: int,
) -> str:
    """
    What the ball did, worded. A pass of 0 crosses a shared space
    and so goes nowhere a distance could say.
    """
    if distance != 0:
        direction = "forward" if distance > 0 else "backward"
        space_word = "space" if actual_distance == 1 else "spaces"
        return f"moves {actual_distance} {space_word} {direction}"
    return "goes to a teammate in the same space"


def pay_double_team_cost(
    engine: RulesEngine,
    match: MatchState,
    winner_key: str,
    partner_id: Optional[str],
) -> str:
    """
    Double Team's cost, charged inside the pass that beat it: the
    defender who played it and the partner -- the nearest teammate on
    the ball's space or behind it (Law 19.10.6) -- each move a space
    forward, away from their own goal.

    `partner_id` is passed rather than looked up, because by the
    time this runs the pass has already moved the ball and the
    partner would be measured from the wrong space. Its caller reads
    it before the ball moves, the same way a won Double Team does.

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


def ball_comes_to(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    before: Optional[str],
) -> list[str]:
    """
    **Inferno lights the ball and Pulsar charges up on it** (Law 21):
    whenever either *receives* the ball -- `RulesEngine.ball_holder`
    changed to them across one step or one answer, and they are its
    carrier -- Inferno's ball goes to speed 12 and Pulsar clears 1
    drain. Returns what to say.

    **Receiving is being left holding it** (the author, 2026-09-26):
    the carrier a pass, a steal, a contest, a pull or a Smooth leaves.
    A handler chosen off the ball's space is not the carrier -- the
    choice consumes the carry -- so choosing Inferno to handle a ball
    they already stood on lights nothing. A pickup receives the ball
    too ("a steal, a pickup, or a pass") but leaves no carrier, so
    `turnovers.recover_ball_step` asks `receives_the_ball` itself.

    Asked by the driver around every step and every answer
    (`driver._touch`), because the ball is received in a dozen places,
    and this is the one rule about all of them.
    """
    holder = engine.ball_holder(match)
    if holder is None or holder == before:
        return []
    if getattr(match, "ball_carrier_id", None) != holder:
        return []
    return receives_the_ball(engine, game, match, holder)


def receives_the_ball(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    holder: str,
) -> list[str]:
    """
    What Law 21 does to a player who has just received the ball --
    Inferno's speed and Pulsar's Charge-up -- and what to say about it.
    """
    lines = []
    if engine.has_special_ability(
        game, holder, SpecialAbility.LIGHTS_THE_BALL,
    ) and match.ball.speed != INFERNO_BALL_SPEED:
        match.ball.speed = INFERNO_BALL_SPEED
        player = engine.get_player_definition(holder)
        # Said as the special ability it is (the author, 2026-09-28): a
        # speed that jumps with no card behind it reads as a mistake.
        lines.append(
            f"The ball comes to {engine.format_player_label(match, player)}"
            f" -- their special ability sets ball speed to "
            f"**{INFERNO_BALL_SPEED}**."
        )
    if engine.has_special_ability(
        game, holder, SpecialAbility.CHARGES_ON_THE_BALL,
    ):
        removed = match.recover_exhaustion(
            holder,
            PULSAR_CHARGE_UP,
            engine.exhaustion_threshold(game, holder),
        )
        if removed:
            player = engine.get_player_definition(holder)
            lines.append(
                f"{engine.format_player_label(match, player)} takes the "
                f"ball -- their special ability, **Charge-up**, clears "
                f"{removed} drain."
            )
    return lines


def low_pass_step(
    engine: RulesEngine,
    match: MatchState,
    distance: int,
    receiver_id: Optional[str] = None,
    key: str = "low_pass",
    free: bool = False,
    game: Optional[D12BallGame] = None,
) -> StepResult:
    """
    Play a won Low Pass -- or a Pinpoint, which is the same card
    with more reach and a bigger bonus, or the unopposed pass
    Pinpoint's own cost hands the defense.

    `free` marks that last one: it is not this side's maneuver, so it
    charges no clock, and applying it is what spends the continuation
    that recorded it.
    """
    name = engine.maneuver_name(key)
    # A pass granted by Pinpoint's cost is a continuation, and
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
    # won Double Team reads it before the push: the partner is
    # measured from where the play started, which is where the ball
    # is standing right now -- or was chosen there by the defending
    # coach from a tie. See `pay_double_team_cost`.
    double_team_partner = None
    if engine.gambit_cost(match, key) == "double_team":
        double_team_partner = engine.double_team_partner(match)
        engine.record_double_team_partner(match, double_team_partner)

    actual_distance = send_low_pass(
        engine, match, offense_side, distance, key, receiver_id,
    )

    content = (
        f"**{name}:** the ball "
        f"{low_pass_movement_note(engine, match, handler, distance, actual_distance)}. "
        f"Ball speed is now {match.ball.speed}."
    )

    # **Double Team's cost**: beaten by a pass, the defender who
    # played it and the teammate who would have joined them are
    # each shoved a space forward, away from their own goal.
    content += pay_double_team_cost(engine, match, key, double_team_partner)
    # Low Pass's own cost is a flat 1 time regardless of
    # distance (2026-08-16), the same as every maneuver but High
    # Pass. A pass granted by Pinpoint's cost is not this
    # side's maneuver and charges nothing: the clock was already
    # spent on the steal that produced it.
    distance_moved = 0 if free else 1

    # **The passer may move 1 space forward** once the ball has gone
    # (Law 6.5.3, the author 2026-10-07) -- a Low Pass's, never a
    # Pinpoint's. Asked before the tail below, which is what the
    # answer runs.
    advance = offer_passer_advance(
        engine, game, match, key,
        {"then": "pass", "receiver_id": receiver_id, "free": free},
    )
    if advance is not None:
        return StepResult(
            narration=[content], board_changed=True, next=advance,
        )
    lines, follow_on = low_pass_tail(
        engine, match, receiver_id, distance_moved, game,
    )
    return StepResult(
        narration=[content, *lines], board_changed=True, next=follow_on,
    )


def low_pass_tail(
    engine: RulesEngine,
    match: MatchState,
    receiver_id: Optional[str],
    distance_moved: int,
    game: Optional[D12BallGame] = None,
) -> tuple[list[str], FollowOn]:
    """
    What a completed pass leads to once the ball is with its receiver
    and the passer has moved or stayed: a Winger's or Zytheris's
    set-up where the ball is in range, and otherwise the end of the
    maneuver. The lines are what it adds to the pass's own.
    """
    offense_side = match.ball.possession
    handler = engine.get_player_definition(match.active_player_id)
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
    # **Zytheris shoots off any pass** (Law 21): received, they are
    # offered the Winger's set-up whoever threw it.
    zytheris = (
        receiver_id is not None
        and match.ball_carrier_id == receiver_id
        and engine.has_special_ability(
            game, receiver_id, SpecialAbility.SHOOTS_OFF_ANY_PASS,
        )
    )
    if not (
        handler.role == PlayerRole.WINGER or zytheris
    ) or not match.can_attempt_score(offense_side):
        return [], FollowOn(
            FollowOnStep.FINISH_MANEUVER_RESOLUTION,
            {"distance_moved": distance_moved},
        )

    if receiver_id is None:
        # Only reachable if the board changed under a stale
        # choice; fall back to whoever is on the ball's space.
        receiver_id = match.eligible_ball_handlers()[0]
    receiver = engine.get_player_definition(receiver_id)
    return [
        (
            f"{engine.format_player_label(match, handler)}'s Winger "
            "ability can turn this into a scoring opportunity!"
            if handler.role == PlayerRole.WINGER
            else f"{engine.format_player_label(match, receiver)}'s "
            "special ability can turn this into a scoring opportunity!"
        ),
    ], FollowOn(
        FollowOnStep.OFFER_SCORING_ATTEMPT_CHOICE,
        {"shooter_id": receiver_id, "distance_moved": distance_moved},
    )


def offer_passer_advance(
    engine: RulesEngine,
    game: Optional[D12BallGame],
    match: MatchState,
    key: str,
    then: dict,
) -> Optional[PendingPrompt]:
    """
    Ask whether a Low Pass's passer moves 1 space forward (Law 6.5.3,
    6.5.5), recording the question and what the pass does once it is
    answered (`MatchState.pending_passer_advance`); `None` where there
    is nothing to ask -- a Pinpoint, whose passer never moves (Law
    19.5.3), or a passer on the last space before the goal zone, with
    no space in front of them to move into.
    """
    if key == "skilled_pass":
        return None
    passer_id = match.active_player_id
    position = match.board.meeple_position(passer_id)
    if position is None or match.relative_move_destination(
        passer_id, match.ball.possession, 1,
    ) == position:
        return None
    match.pending_passer_advance = {"passer_id": passer_id, **then}
    return passer_advance_prompt(engine, game, match)


def answer_passer_advance(
    engine: RulesEngine,
    game: Optional[D12BallGame],
    match: MatchState,
    advance: bool,
) -> StepResult:
    """
    The passer moves 1 space forward or stays, and the pass goes on
    to what it was owed: the tail of a completed pass, or the landing
    of one that reached nobody. Staying says nothing -- a move that is
    not made is not news.
    """
    pending = match.pending_passer_advance or {}
    match.pending_passer_advance = None
    passer_id = pending.get("passer_id", match.active_player_id)
    lines: list[str] = []
    if advance:
        offense_side = match.ball.possession
        if match.move_player_relative(passer_id, offense_side, 1):
            passer = engine.get_player_definition(passer_id)
            lines.append(
                f"{engine.format_player_label(match, passer)} moves a "
                "space forward."
            )
    if pending.get("then") == "loose":
        return StepResult(
            narration=lines,
            board_changed=bool(lines),
            next=FollowOn(
                FollowOnStep.BEGIN_LOOSE_BALL, {"distance_moved": 1},
            ),
        )
    tail, follow_on = low_pass_tail(
        engine, match, pending.get("receiver_id"),
        0 if pending.get("free") else 1, game,
    )
    return StepResult(
        narration=[*lines, *tail],
        board_changed=bool(lines),
        next=follow_on,
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
    return f"\n\n**Clear** was beaten -- exhaust 2.\n{text}"


def dribble_advance_step(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    distance: int,
) -> StepResult:
    """
    Play a won Dribble: the handler carries the ball forward
    and keeps it, then manipulates ball speed the way every dribble
    ends.

    Role ability -- Playmaker: 2 spaces instead of the usual 1. The
    note says which of the two was taken, so it rides on the distance
    rather than on the player; whether the coach was even asked is
    `resolve_dribble_advance`'s, above the seam.

    `distance` is what was chosen; `actual_distance` is what the move
    came to, since `move_player_relative` clamps at the last space
    before the goal zone. The wording reads the second, because what a coach watched
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
    # Emberdash's third space is theirs alone (Law 21); the second is
    # every Playmaker's.
    ability_note = (
        " (special ability)"
        if distance > 2
        else " (Playmaker ability)"
        if handler.role == PlayerRole.PLAYMAKER and distance > 1
        else ""
    )
    content = (
        f"**{engine.maneuver_name('dribble_advance')}:** "
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
    Play a won Burst: the handler carries the ball up to
    `DRIBBLE_BURST_MAX_DISTANCE` spaces forward (one more for a
    Playmaker), defenders no obstacle, at a token a space -- and the
    ball is left at speed `BALL_SPEED_MAX`, where a Dribble
    offers the handler a change of up to oSkill (the author,
    2026-09-20: "precisely 12, not any number"). Nothing is asked, so
    unlike the advance the burst ends on the maneuver's tail rather
    than on a speed choice; the speed is said in the narration the way
    `apply_speed_choice` says it, and said only where it changed.

    Role ability -- Playmaker: the extra space their sentence names,
    same as the advance's (the author, 2026-09-26, reversing the
    2026-08-19/2026-08-26 reading that kept this one on the cost
    instead -- the only ability that used to read differently on the
    two cards of a rank). `dribble_burst_distances` is where the space
    is offered; the cost here is everybody's same token a space.

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
    # Emberdash bursts for nothing (Law 21), which the cost already
    # says; the note below says why.
    free_burst = engine.has_special_ability(
        game, match.active_player_id, SpecialAbility.FREE_BURST,
    )
    tokens = engine.dribble_burst_cost(match, actual_distance, game)
    exhaustion_text = engine.apply_exhaustion(

        game, match, match.active_player_id, tokens,
    )

    space_word = "space" if actual_distance == 1 else "spaces"
    handler_label = engine.format_player_label(match, handler)
    # The fifth space is a Playmaker's alone, same as the advance's
    # second (`dribble_advance_step`'s ability_note).
    ability_note = (
        " (Playmaker ability)"
        if playmaker_bonus and actual_distance > DRIBBLE_BURST_MAX_DISTANCE
        else ""
    )
    if actual_distance:
        content = (
            f"**{engine.maneuver_name('dribble_burst')}:** "
            f"{handler_label} bursts "
            f"{actual_distance} {space_word} forward, past everyone in "
            f"the way{ability_note}."
        )
    else:
        # The handler was already on the last space before the goal
        # zone, so the burst had nowhere to go -- said plainly rather
        # than reported as a run of 0 spaces, which is the same call
        # `throw_high_pass` makes for a throw from the last space.
        content = (
            f"**{engine.maneuver_name('dribble_burst')}:** "
            f"{handler_label} is already on the last space before the "
            "goal zone, so the ball stays where it is."
        )
    # Worth saying only for Emberdash: everybody else, Playmaker
    # included, pays the plain token-a-space cost.
    if free_burst and actual_distance:
        content += " That costs them nothing (special ability)."
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
    reached the goal zone and how far it actually went.

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

    # Intercept moving forward can reach the goal zone, which a Steal
    # falling back never can: the ball was in play, so there is
    # always a space behind it. Read before the move, the way every
    # other reading of the goal zone is.
    origin_flat = match.board.flat_index(
        *match.board.meeple_position(challenger_id)
    )
    reaches_goal_zone = match.goal_zone_reached(
        origin_flat, new_possession_side, direction,
    ) is not None

    actual_distance = match.move_player_relative(
        challenger_id, new_possession_side, direction,
    )
    match.set_ball_space(*match.board.meeple_position(challenger_id))
    # The interceptor took the ball off someone and moved with it,
    # so they carry it into their side's next turn -- the same
    # player the run back exempts.
    match.set_ball_carrier(challenger_id)

    return reaches_goal_zone, actual_distance


def steal_result_text(
    engine: RulesEngine,
    match: MatchState,
    key: str,
    name: str,
    challenger_id: str,
    actual_distance: int,
    game: Optional[D12BallGame] = None,
) -> tuple[str, Headline]:
    """The turnover, and which way the thief carried it -- and its
    `Headline`, for the side that took the ball."""
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
    under = (
        f"{challenger_label} steals the ball. "
        f"{format_team_side_label(new_possession, game)} now has possession, "
        f"{travel}."
    )
    headline = Headline(TURNOVER_HEADING, match.ball.possession, under)
    return f"**{name}:**\n# {headline.text}\n{under}", headline


def steal_step(
    engine: RulesEngine,
    match: MatchState,
    key: str,
    game: Optional[D12BallGame] = None,
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

    It reads nothing off the game record to decide anything -- the
    exhaustion a run back charges is `begin_run_back`'s, and the cost
    this card can collect is an engine question -- and takes `game`
    only to name the side that took the ball by its coach.
    """
    new_possession_side = match.defending_side()
    challenger_id = match.challenger_id
    name = engine.maneuver_name(key)
    # Toward the new possessor's own goal for a Steal, toward the
    # goal they now attack for an Intercept.
    direction = 1 if key == "intercept" else -1

    reaches_goal_zone, actual_distance = take_ball_by_steal(
        match, challenger_id, new_possession_side, direction,
    )
    content, headline = steal_result_text(
        engine, match, key, name, challenger_id, actual_distance, game,
    )

    # Both endings below have moved a meeple and the ball with it, so
    # `board_changed` is True either way -- which is exactly where
    # `refresh_match_image` sat in the cog, on both paths.
    if key == "intercept" and reaches_goal_zone:
        # **The interceptor was already on the last space before
        # the goal they now attack, so the ball reaches the goal
        # zone and there is nowhere to carry it: it is a scoring
        # opportunity instead** (the author,
        # 2026-08-19).
        #
        # Straight to the shot, the same as a deflection that
        # reaches the goal zone and for the same reason: the run back and the
        # speed step both belong after a turnover that left the
        # play running, and this one has not. That drops
        # Intercept's own speed-manipulation step, which is the one
        # thing about this branch worth watching -- a set-up shot
        # already reads the ball speed the turnover reset.
        #
        # It returns **before** the cost below, exactly as the cog
        # did: an Intercept that reaches the goal zone collects no beaten
        # Pinpoint. Preserved rather than corrected, because
        # whether that is the rule is the author's to say -- see the
        # questions on the pull request for rank D2.
        return StepResult(
            narration=[
                content
                + "\n\nThe ball reaches the goal zone ahead of them -- "
                "a scoring opportunity!"
            ],
            headlines=(headline,),
            board_changed=True,
            next=FollowOn(
                FollowOnStep.BEGIN_SHOOTER_CHOICE,
                {"candidates": [challenger_id]},
            ),
        )

    # **Pinpoint's cost**: beaten by a steal, the passing side
    # hands the defender an unopposed Low Pass once the steal has
    # settled. It is said here and played later, because the steal is
    # not finished: the run back and then the speed choice both come
    # first, and the pass is played from wherever that leaves the
    # interceptor. The record of it is written when the speed choice
    # is answered (`speed_choice_step`), which is the moment the
    # effect has nothing left in front of it -- see
    # `pending_effect_continuation`.
    if engine.gambit_cost(match, key) == "skilled_pass":
        content += (
            f"\n\n**{engine.maneuver_name('skilled_pass')}** was beaten "
            "-- the defense gets an "
            "unopposed Low Pass once everyone is back in position."
        )

    # Ball-speed manipulation is offered after run-back finishes,
    # not here -- see begin_run_back's speed_choice_after.
    # No stays_player_id: begin_run_back exempts the ball carrier,
    # which take_ball_by_steal has already made the interceptor.
    return StepResult(
        narration=[content],
        headlines=(headline,),
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
    (and a Double Team's partner) onto the handler's new space.

    Returns how far the handler actually moved, which is less than
    `push` only when the push reaches their own goal zone -- which the
    caller has already read, before anything moved.
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
    # Set before the caller's goal-zone branch, because an own goal
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
    What the shove reads as, with a Double Team's partner joining in.
    Whether that partner then Merges is `pressure_step`'s to say,
    once it knows the ball is still the offense's.
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
        content += f" {engine.format_player_label(match, partner)} joins them."

    return content


def apply_pressure_turnover(
    engine: RulesEngine,
    match: MatchState,
    key: str,
    defense_side: TeamSide,
    game: Optional[D12BallGame] = None,
) -> tuple[str, bool, bool]:
    """
    Whether the pressure also took the ball, and what to say about
    it. Returns the text to append, and the two facts the caller
    dispatches on: a Burst cost paid, and a Defender's
    steal.

    The two are exclusive and in that order -- a burst cost already
    turns the ball over, so the Defender's ability has nothing left
    to take.
    """
    defender = engine.get_player_definition(match.challenger_id)
    content = ""

    # **Burst's cost**: beaten by a pressure, the offense
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
            f"**{engine.maneuver_name('dribble_burst')}** was beaten -- "
            f"{format_team_side_label(match.setup_for_side(defense_side), game)} "
            "takes the ball, and it keeps the speed the burst put into "
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
            f"{format_team_side_label(match.setup_for_side(defense_side), game)} "
            "now has possession."
        )

    return content, burst_cost, stolen


def pressure_step(
    engine: RulesEngine,
    match: MatchState,
    key: str,
    game: Optional[D12BallGame] = None,
) -> StepResult:
    """
    Play a won Pressure -- or a Double Team, which is the same card
    with a partner brought in free of exhaustion, who Merges through
    the *following* maneuver (Law 19.10). The two differ only by that
    partner, so they are one function and a `key`, the way Low Pass
    and Pinpoint are.

    Rank D3 has no unchallenged branch: a defense card only resolves
    where a defender was sent, so `match.challenger_id` is always the
    player who plays it.

    It reads the game record for one thing only: whether the
    challenger is Acidel, whose pressure into the goal zone is a shot
    rather than an own-goal roll (Law 21).
    """
    offense_side = match.ball.possession
    defense_side = match.defending_side()
    name = engine.maneuver_name(key)
    # Both cards push 1 (Law 19.10.2, 2026-10-03: a Double Team
    # pushed 2 until then).
    push = 1

    # Own-goal risk: a pressure is the only thing that threatens
    # one, and only when its push reaches the handler's own goal zone
    # (Law 11.1) -- the handler already on the last space before it.
    reaches_goal_zone = match.ball_reaches_goal_zone(offense_side, -push)

    # **Read before anything moves.** The partner is the nearest
    # defender on the ball's space or behind it, where the play
    # started (Law 19.10.3) -- a moment later the ball has moved and
    # the nearest to *that* space can be somebody else. A tie was the
    # defending coach's to break before this step ran
    # (`DOUBLE_TEAM_PARTNER`); either way it is recorded here, so no
    # later reading this maneuver measures again.
    partner_id = None
    if key == "double_team":
        partner_id = engine.double_team_partner(match)
        engine.record_double_team_partner(match, partner_id)

    actual_distance = shove_pressured_handler(match, push, partner_id)
    content = pressure_result_text(
        engine, match, key, name, actual_distance, partner_id,
    )

    # Every branch below has moved a meeple: even a shove with
    # nowhere to go walks the challenger onto the handler's space.
    # So `board_changed` is True throughout, which is where
    # `refresh_match_image` sat in the cog on both paths.
    if reaches_goal_zone and engine.has_special_ability(
        game, match.challenger_id, SpecialAbility.PRESSURE_SHOT,
    ):
        # **Acidel's special ability** (Law 21): "a scoring
        # opportunity replaces the own goal" (the author, 2026-09-25).
        # The shove walked Acidel onto the handler's space, so the ball
        # is taken there -- the Intercept's goal-zone shape in
        # `steal_step`: possession, speed 1, straight to the shot.
        challenger_id = match.challenger_id
        match.ball.possession = defense_side
        match.ball.speed = 1
        match.set_ball_space(*match.board.meeple_position(challenger_id))
        match.set_ball_carrier(challenger_id)
        acidel = engine.get_player_definition(challenger_id)
        return StepResult(
            narration=[
                content
                + "\n\nThe ball reaches their own goal zone -- and "
                f"{engine.format_player_label(match, acidel)} takes the "
                "ball for a scoring opportunity!"
            ],
            board_changed=True,
            next=FollowOn(
                FollowOnStep.BEGIN_SHOOTER_CHOICE,
                {"candidates": [challenger_id]},
            ),
        )

    if reaches_goal_zone:
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
        # newlines -- the same reason the Intercept's goal-zone
        # sentence rides inside the turnover's.
        return StepResult(
            narration=[
                content + "\n\nThe ball reaches their own goal zone!"
            ],
            board_changed=True,
            next=FollowOn(
                FollowOnStep.BEGIN_OWN_GOAL_ROLL, {"distance_moved": 1},
            ),
        )

    turnover_text, burst_cost, stolen = apply_pressure_turnover(
        engine, match, key, defense_side, game,
    )
    content += turnover_text

    if key == "double_team" and partner_id is not None and not (
        burst_cost or stolen
    ):
        # **The partner Merges through the next maneuver** (Law
        # 19.10.5) -- unless the ball has just changed hands, which
        # ends it before it starts. Recorded by name, so the next
        # maneuver does not re-derive a partner off a board that has
        # moved; `finish_maneuver_resolution` keeps it past this
        # maneuver's own end (the `merges` mark) and clears it at the
        # next one's.
        match.pending_double_team = [partner_id]
        engine.record_double_team_partner(match, partner_id, merges=True)
        partner = engine.get_player_definition(partner_id)
        content += (
            f" {engine.format_player_label(match, partner)} Merges on the "
            "next maneuver, adding their defensive skill while they stand "
            "on the ball."
        )

    # Fixed 1 time per the rules table, whether or not the
    # push reached the goal zone, same reasoning as a deflection.
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
    game: Optional[D12BallGame] = None,
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
        # since Pressure's goal-zone branch never touches it.
        match.ball.speed = 1
        # The ball stays exactly where the Pressure into the goal zone left
        # it, with no coverage guarantee at all -- not even the
        # standard deal's, since that position is wherever the play
        # happened to reach. So, since 2026-08-24, this owes the
        # same pickup an out-of-bounds ball does rather than a
        # two-sided loose ball: begin_ball_recovery checks
        # eligible_ball_handlers() first and asks nobody when the
        # reset already covers it.
        match.pending_ball_recovery = True
        return f"## {OWN_GOAL_AVOIDED}\n\n{exhaustion_text}"

    conceding_side = match.ball.possession
    # The goal is the other side's; the kick is this player's,
    # and the log says both -- see concede_own_goal.
    match.concede_own_goal(offense_player.player_id)
    match.restart_after_goal(conceding_side)
    match.pending_run_back = True
    match.pending_run_back_distance = distance_moved
    match.pending_run_back_turnover = True
    return (
        f"# {OWN_GOAL}\n"
        f"{engine.format_player_label(match, offense_player)} "
        "puts it in their own net on "
        f"**{format_goal_time(match.goals[-1])}**.\n"
        f"{score_side_label(match.home, game)} {match.scoreboard.home_score}:"
        f"{match.scoreboard.visiting_score} "
        f"{score_side_label(match.visiting, game)}\n\n"
        f"{exhaustion_text}"
    )


@dataclass(frozen=True)
class OwnGoalRoll:
    """
    The numbers an own-goal roll produced, for the frontend to draw.

    **Not narration and not a `StepResult`.** The two sentences the
    roll is worth are the model's and are in `own_goal_roll_step`'s
    result; what is here is the arithmetic a *picture* is made of --
    two faces, whether it was safe, whether Overdrive was spent. A
    frontend with no dice image ignores it and posts the two lines.
    """

    rolls: tuple[int, int]
    offense_skill: int
    safe: bool
    overdrive: int
    #: Who rolled, for the die's colour. By the time the step returns
    #: the run back has handed the ball over, so the position no longer
    #: says whose roll it was -- the reason `ShotDice` carries its
    #: shooter (step 7 of docs/web-app-next.md).
    player_id: str = ""

    def to_dict(self) -> dict:
        return {
            "shape": "own_goal",
            "rolls": list(self.rolls),
            "offense_skill": self.offense_skill,
            "safe": self.safe,
            "overdrive": self.overdrive,
            "player_id": self.player_id,
        }


#: The two headings an own-goal roll is announced under, in its line
#: and its `Headline` alike.
OWN_GOAL_AVOIDED = "Own goal avoided!"

#: The lowest total that avoids an own goal (Law 11.2): the higher of
#: two d12 plus the handler's offensive skill. Named so the roll and a
#: frontend saying what it needs read the one number.
OWN_GOAL_SAFE_TOTAL = 7
OWN_GOAL = "Own goal!"


def own_goal_roll_step(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
) -> tuple[OwnGoalRoll, StepResult]:
    """
    The roll itself, off the button `begin_own_goal_roll` posted: 2d12
    at an advantage (take the higher), plus the ball-handler's
    offensive skill, safe on 7+.

    Making the attempt costs the rolling player 1 exhaust token, win or
    lose, on top of whatever the maneuver that triggered the risk
    already charged. It is not a skill test, so it owes no injury
    check.

    **It returns two things, and that is deliberate.** The
    `StepResult`'s narration is the arithmetic and the verdict, in that
    order; the `OwnGoalRoll` is the same numbers for the dice image.
    They are separate because the frontend puts the image *between* the
    two lines -- a message's attachments render below its content, so a
    verdict written above the roll would be read before it. How the
    lines go together is the frontend's (principle 8), which is why
    this hands over two of them rather than one joined block.
    """
    distance_moved = match.pending_own_goal_distance
    match.pending_own_goal = False

    offense_player = engine.get_player_definition(match.active_player_id)
    offense_skill = engine.attacking_skill(
        game, match, offense_player.player_id, "own_goal",
    )
    skill_name = engine.attacking_skill_name(
        game, match, offense_player.player_id, "own_goal",
    )

    rolls = tuple(scripted_or_random(engine, game, "own_goal", 2))
    # **Volatile does not reach this roll** (the author, 2026-09-23),
    # so neither die is asked through `engine.ignite`: a Fire Demon's
    # natural 6 or 7 here is only the number.
    overdrive = match.overdrive_modifier(offense_player.player_id)
    # Worded per declaration, read before they are spent: Gearclaw's
    # Boost is its own line, beside an Overdrive or alone (Law 21).
    overdrive_details = engine.overdrive_details(
        match, offense_player.player_id,
    )
    match.consume_overdrive()
    # Zorch adds the ball speed modifier to every roll they make (Law 21).
    speed, speed_line = engine.speed_roll_bonus(
        game, match, offense_player.player_id,
    )
    safe = (
        max(rolls) + offense_skill + overdrive + speed >= OWN_GOAL_SAFE_TOTAL
    )

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

    # Charged before the outcome is applied, so the token and any
    # Exhausted flag it sets are settled with the rest of the roll.
    exhaustion_text = engine.apply_exhaustion(
        game, match, offense_player.player_id, 1,
    )

    taken = max(rolls)
    arithmetic = (
        f"{engine.format_player_label(match, offense_player)} "
        f"rolls at an advantage: higher of {rolls[0]}/{rolls[1]} "
        f"is {taken}, + {offense_skill} ({skill_name.lower()} skill)"
    )
    for line in overdrive_details:
        arithmetic += f", {line}"
    if speed:
        arithmetic += f", {speed_line}"
    total = taken + offense_skill + overdrive + speed
    arithmetic += f" = {total}"
    breakdown = f"**Own goal risk!** {arithmetic}"
    # Whose outcome it is: the roller's side keeps it out, the other
    # side is given the goal -- read before the outcome moves the ball.
    headline = Headline(
        OWN_GOAL_AVOIDED if safe else OWN_GOAL,
        match.ball.possession if safe else match.defending_side(),
        # The breakdown's own pieces, a line apiece (`roll_working`).
        working=((
            f"{engine.format_player_label(match, offense_player)} "
            f"rolls at an advantage: higher of {rolls[0]}/{rolls[1]} "
            f"is **{taken}**",
            f"+ {offense_skill} ({skill_name.lower()} skill)",
            *overdrive_details,
            *((speed_line,) if speed else ()),
            f"= **{total}**",
        ),),
        reading=(
            f"**{total}** is {OWN_GOAL_SAFE_TOTAL} or more: safe."
            if safe
            else f"**{total}** is under {OWN_GOAL_SAFE_TOTAL}: an own goal."
        ),
    )

    verdict = apply_own_goal_outcome(
        engine, match, offense_player, distance_moved, safe,
        exhaustion_text, game,
    )

    return (
        OwnGoalRoll(
            rolls, offense_skill, safe, overdrive,
            player_id=offense_player.player_id,
        ),
        StepResult(
            narration=[breakdown, verdict],
            headlines=(headline,),
            board_changed=True,
            # **Both outcomes are new plays.** A conceded own goal
            # restarts from the kickoff space as any other goal does;
            # avoiding one is a stoppage too, not a play that carries
            # on -- both sides reset to their saved arrangement and the
            # side with the ball may declare. If this closes out last
            # possession, `begin_run_back`'s own check ends the period
            # here instead. See "Own goal" in docs/living-rules.md.
            next=FollowOn(
                FollowOnStep.BEGIN_RUN_BACK,
                {
                    "distance_moved": distance_moved,
                    "turnover_occurred": True,
                    "new_play": True,
                },
            ),
        ),
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
    speed off it. Returns whether it reached the goal zone and how far
    it actually went.

    The goal zone is read before the ball moves, the way every other
    reading of it is. Reaching it no longer risks an own goal -- only
    Pressure does -- it sets up a scoring opportunity for the defense
    instead, who are now the side standing next to the goal the ball
    just reached.
    """
    reaches_goal_zone = match.ball_reaches_goal_zone(
        offense_side, -deflect_distance,
    )

    actual_distance = match.move_ball_relative(
        offense_side, -deflect_distance,
    )
    match.ball.speed = max(1, match.ball.speed - speed_drop)

    return reaches_goal_zone, actual_distance


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
    where the ball is lying when the question is asked
    (`deflection_lands`).
    """
    # **A failed Cross gambit is this card, as itself** (Law 19.7.7,
    # the author, 2026-10-03): the ball goes back the card's own
    # distance and lands as it always does. What the failure changes is
    # the contest it may lead to, which the side that played this card
    # wins without a roll -- `RulesEngine.contest_auto_winner`.
    offense_side = match.ball.possession
    defender = engine.get_player_definition(match.challenger_id)
    name = engine.maneuver_name(key)

    deflect_distance, speed_drop, fullback_bonus = deflection_numbers(
        defender, key,
    )

    reaches_goal_zone, actual_distance = knock_ball_back(
        match, offense_side, deflect_distance, speed_drop,
    )

    space_word = "space" if actual_distance == 1 else "spaces"
    ability_note = " (Fullback ability)" if fullback_bonus else ""
    content = (
        f"**{name}:** the ball moves {actual_distance} "
        f"{space_word} back{ability_note}. Ball speed is now "
        f"{match.ball.speed}."
    )
    return deflection_lands(engine, match, content, reaches_goal_zone)


def deflection_lands(
    engine: RulesEngine,
    match: MatchState,
    content: str,
    reaches_goal_zone: bool,
) -> StepResult:
    """
    Where a deflection's ball comes to rest decides what happens next:
    the challenger's shot where it reached the goal zone, or a loose
    ball settled by who is standing there -- a failed Cross's
    deflection included, which lands exactly as any other.
    """
    defense_side = match.defending_side()

    # **The board moved on every branch below**, so `board_changed` is
    # True throughout -- the ball was driven back and the speed came
    # off it. That is *not* the same question as "was the persistent
    # board message written", which two of the three branches answer
    # no to: `begin_loose_ball` draws the board under its own
    # announcement, so the frontend skips a write it is about to make
    # anyway. That suppression lives with the frontend
    # (`stop_draws_the_board` in `cogs/d12ball/core.py`), because it
    # is a rate-limit economy and rate limits are the frontend's --
    # principle 8 in CLAUDE.md. A web app has no five-in-five bucket
    # and should redraw on all three.

    # A shot has to be within shooting range, and this one always is:
    # reaching the goal zone leaves the ball on the last space before
    # the offense's own goal, which is as deep into the deflecting team's
    # range as the field goes. So this asks
    # scoring_opportunity_candidates with no range check over it -- the
    # check could never fail here, and a branch that cannot be taken
    # reads as if it could.
    #
    # **Only the challenger shoots** -- the player who played the card,
    # and only if the ball came to rest on their own space. A teammate
    # who happens to be standing there as well is not offered it (the
    # author, 2026-09-26), so a deflection into the goal zone never
    # asks who shoots. A Clear that reaches the goal zone with its
    # challenger anywhere but that last space sets up nothing, and lands like any other
    # deflection below.
    candidates = []
    if reaches_goal_zone and match.challenger_id in (
        engine.scoring_opportunity_candidates(match, defense_side)
    ):
        candidates = [match.challenger_id]

    if candidates:
        # The challenger, standing right where the ball ends up, gets a
        # shot at the goal it's now next to -- that's a turnover before the
        # shot, same as any other change of possession, so the score
        # attempt reads the correct attacking and defending sides.
        match.ball.possession = defense_side
        match.ball.speed = 1
        return StepResult(
            narration=[
                content,
                "The ball reaches the goal zone -- a scoring opportunity!",
            ],
            board_changed=True,
            next=FollowOn(
                FollowOnStep.BEGIN_SHOOTER_CHOICE,
                {"candidates": candidates},
            ),
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
    # already there. See `d12ball.flow.arrivals.begin_loose_ball`.
    #
    # A deflection's time cost is a fixed 1 time per the rules
    # table, not "distance traveled" like Low/High Pass, so this
    # doesn't shrink if the ball reached the goal zone (or grow with
    # the Fullback's extra distance, or Clear's, or a chosen one).
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

    Returns whether the throw reached the goal zone, how far the
    ball actually travelled, and the line every branch of the pass
    opens with. The goal zone is read **before** the ball moves, the
    same way Deflect reads it and by the same test, so a pass that
    could not move the ball at all reaches the goal zone like any
    other -- which is the whole reason this is one function and not the
    caller's first three statements.
    """
    # Role ability -- Fullback: can choose to pass up to 4 spaces
    # instead of the usual 2-3 max (see HighPassChoiceView).
    fullback_bonus = handler.role == PlayerRole.FULLBACK and distance == 4

    reaches_goal_zone = match.high_pass_reaches_goal_zone(
        offense_side, distance,
    )

    actual_distance = match.move_ball_relative(offense_side, distance)

    ability_note = " (Fullback ability)" if fullback_bonus else ""
    if actual_distance:
        space_word = "space" if actual_distance == 1 else "spaces"
        content = (
            f"**High Pass:** the ball moves {actual_distance} "
            f"{space_word} forward{ability_note}."
        )
    else:
        # Thrown from the last space, so the ball reaches the goal
        # zone and comes to rest exactly where it was. Worth saying in words rather than
        # as "moves 0 spaces forward", which reads as a bug -- and
        # a coach sees it now that the passer cannot shoot off it.
        content = (
            "**High Pass:** the ball is thrown from the last space into "
            "the goal zone and comes straight back down on it."
        )

    return reaches_goal_zone, actual_distance, content


def send_ball_out_of_play(
    match: MatchState,
    game: Optional[D12BallGame] = None,
) -> str:
    """
    The ball went dead: the other team gains possession, the speed
    resets, nobody is carrying it, and the side that gained it owes a
    pickup. Returns that side, worded.

    Both passes of rank O3 reach this and nothing else does -- a High
    Pass with nowhere left to throw it, and a Cross with nowhere
    to pick it out to. They say different things about how they got
    here, which is why the sentence is each branch's and only the
    state is shared. See `d12ball.flow.turnovers.begin_run_back`'s `new_play`: this
    is the fourth of the four call sites that open one, and it is one
    for the same reason the other three are -- the ball went dead
    rather than being taken off anybody.
    """
    match.ball.possession = match.defending_side()
    match.ball.speed = 1
    match.clear_ball_carrier()
    match.pending_ball_recovery = True
    return format_team_side_label(
        match.setup_for_side(match.ball.possession), game,
    )


def run_onto_pass(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    runner_id: str,
    distance: int,
) -> str:
    """
    **Quantor runs onto the pass** (Law 21): drain 3 and move to the
    space the pass is aimed at, before it is thrown, so the pass lands
    on them. Returns the sentence saying so.

    `move_meeple` records them as moved by this resolution, so neither
    a Mind Pull nor a Smooth is offered to them on the movement that
    carried them -- they arrive with the ball, the reading every other
    carried player has. The target is read the way the throw reads it,
    so the space run to is the space the ball comes down on.
    """
    side = match.ball.possession
    origin_flat = match.board.flat_index(
        match.ball.zone, match.ball.space_index,
    )
    zone, space_index = match.board.position_at_flat_index(
        match.relative_flat_index(origin_flat, side, distance),
    )
    match.move_meeple(runner_id, zone, space_index)
    exhaustion_text = engine.apply_exhaustion(
        game, match, runner_id, QUANTOR_RUN_DRAIN,
    )
    runner = engine.get_player_definition(runner_id)
    return "\n".join(filter(None, (
        f"{engine.format_player_label(match, runner)} runs to "
        f"{space_label(zone, space_index, match.board)} to take the pass "
        "(special ability).",
        exhaustion_text,
    )))


def high_pass_step(
    engine: RulesEngine,
    match: MatchState,
    distance: int,
    runner_id: Optional[str] = None,
    game: Optional[D12BallGame] = None,
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
    rules: the goal zone's set-up subsumes the ordinary one, a pass of
    2 is never made to win a contest, and a throw from the last space
    that reaches the goal zone with nobody there goes out rather than
    staying with the passer.

    It reads nothing off the game record but the special abilities
    -- the gambit's cost is an engine question and nothing here
    charges exhaustion -- so `game` is optional, and without it none
    of Law 21 applies: Vorix's long set-up is asked of it below.
    Zytheris's shot off a long pass comes after its contest, and is
    `rolls.after_the_contest`'s.
    """
    offense_side = match.ball.possession
    handler = engine.get_player_definition(match.active_player_id)

    reaches_goal_zone, actual_distance, content = throw_high_pass(
        match, offense_side, distance, handler,
    )

    # High Pass's own cost is a flat 2 time regardless of
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
    # Quantor ran onto it (`run_onto_pass`), so it is theirs whoever
    # else is standing there (Law 21).
    if runner_id is not None:
        receiver_candidates = [runner_id]

    # **The ball moved on every branch below**, or the speed came off
    # it, so `board_changed` is True throughout. That is not the same
    # question as "was the persistent board message written": the
    # branch that goes out of play hands over to a new play, which
    # posts and pins a board of its own, so the frontend skips a write
    # it is about to make anyway. That suppression lives with the
    # frontend (`StepResult.new_play` stops the driver, and
    # `D12Ball.dispatch_step_result` skips the write in front of the
    # pinned board), because it is a rate-limit economy and rate
    # limits are the frontend's -- principle 8 in CLAUDE.md.

    # Reaching the goal zone sets up a scoring opportunity whatever
    # distance was asked for (2026-08-10), on the last space before
    # it -- which is where the ball has just come to rest. The shot
    # is always legal there, as deep into the offense's own
    # shooting range as the field goes, so no range check: it could
    # never fail here, and a branch that cannot be taken reads as
    # if it could. Checked ahead of the ordinary 2-space set-up
    # below, which it subsumes -- the same shot is offered, but
    # with the modifier the other way round and a contest behind
    # it.
    if reaches_goal_zone and receiver_candidates:
        return offer_goal_zone_set_up(
            match,
            shooter_id=receiver_candidates[0],
            distance_moved=distance_moved,
            lead_in=content,
        )
    # Nobody the pass could reach on the landing space leaves
    # nothing to set up, so the goal zone falls through to the
    # ordinary paths below: a loose ball, a clean turnover, or --
    # the case the passer exclusion opened (2026-08-12) -- the
    # passer keeping a ball that never left them.

    # A pass of 2 is received cleanly: no contest at all
    # (2026-08-07), and it may set up a scoring opportunity for
    # whoever it lands on -- unlike the old fixed-2 High Pass,
    # this no longer requires reaching the goal zone. A longer
    # pass never offers it, whether or not it reaches the goal zone.
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

    # **Vorix's pass of 3 is a set-up** (Law 21): no contest, the
    # ball at 12, and the shot where it is in range -- the 2-space
    # branch's shape, which is why it is asked here, before the
    # contest a pass of 3 otherwise owes.
    vorix = (
        distance == VORIX_PASS_DISTANCE
        and not reaches_goal_zone
        and receiver_candidates
        and engine.has_special_ability(
            game, match.active_player_id, SpecialAbility.LONG_SET_UP,
        )
    )
    if vorix:
        match.ball.speed = VORIX_BALL_SPEED
        content = (
            f"{content}\n\n{engine.format_player_label(match, handler)}'s "
            f"long pass needs no contest -- ball speed "
            f"**{VORIX_BALL_SPEED}**."
        )
        if match.can_attempt_score(offense_side):
            setup_candidates = receiver_candidates
        else:
            return complete_high_pass_reception(
                match, receiver_candidates[0], distance_moved, content,
            )

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
    # lands on an empty space.

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
        # above can only bite when a throw from the last space reached
        # the goal zone and came back down on it -- a High Pass moves
        # the ball, not the handler, so
        # that is the only way the passer is still standing where
        # it lands. With nobody else there either, this is a throw
        # with nowhere to go: there was no space left to put it on
        # and no teammate to put it to, so it goes out exactly as a
        # Cross with no legal destination does, rather than
        # quietly staying with the passer. `actual_distance` (not
        # `distance`) is the test, because that's what tells the
        # ball genuinely didn't move from a real empty destination
        # elsewhere on the field -- which stays an ordinary loose
        # ball below.
        if actual_distance == 0:
            gaining = send_ball_out_of_play(match, game)
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

    # **Quantor gains possession without contest** (Law 21): a pass
    # of 3 or 4 they ran onto is simply received.
    if runner_id is not None:
        return complete_high_pass_reception(
            match, runner_id, distance_moved, content,
        )

    # **Intercept's cost**: beaten by a High Pass, the reception is
    # not contested -- the receiver simply keeps it. It is the one
    # of the six costs that can be inert, and this is the only
    # branch it is not: a pass of 2, the goal zone's set-up and a
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


def offer_goal_zone_set_up(
    match: MatchState,
    *,
    shooter_id: str,
    distance_moved: int,
    lead_in: str,
) -> StepResult:
    """
    The scoring opportunity a High Pass that reached the goal zone
    sets up (2026-08-10) -- see "High Pass" in the living rules.

    The pass arrived faster than the receiver could settle it, so
    `pending_high_pass_overshoot` (the saved key keeps the old word)
    turns the ball speed modifier around for everything it leads
    to: this shot, and
    the long-pass contest behind it. It is set before either is
    offered, and cleared with the rest of the turn by
    reset_maneuver.

    **The two are one choice, not an offer and a fallback.** A pass
    into the goal zone is a shot at a disadvantage or a contest to keep the
    ball, both paying the modifier, so declining always lands in
    the contest -- there is no distance here that resolves as a
    settled pass. A distance of 2 could only reach it from a
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
    # The modifier is the speed itself (Law 7.1), never below 1, so
    # every pass that reaches the goal zone pays it.
    speed_note = (
        " The ball comes in too fast to settle -- the ball speed "
        f"modifier counts **against** what follows ({penalty})."
    )
    return StepResult(
        narration=[
            lead_in,
            "The ball reaches the goal zone -- a scoring "
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


def setup_pass_step(
    engine: RulesEngine,
    match: MatchState,
    distance: int,
    runner_id: Optional[str] = None,
    game: Optional[D12BallGame] = None,
) -> StepResult:
    """
    Cross: the ball goes 0, 1 or 3 spaces, and a teammate standing
    where it lands takes a scoring opportunity.

    **Every distance that fits on the field is offered**, whether or
    not anybody of the passing side is standing there, so all three
    endings below are real outcomes rather than one outcome and two
    guards -- see `RulesEngine.setup_pass_distances`.
    """
    offense_side = match.ball.possession
    # A game saved after the speed choice Cross used to ask first
    # carries a `setup_pass_shot` continuation; applying the pass spends
    # it, as it always did.
    match.pending_effect_continuation = None
    actual_distance = match.move_ball_relative(offense_side, distance)
    receivers = engine.high_pass_receiver_candidates(match, offense_side)
    # Quantor ran onto it, so it sets up their shot (Law 21).
    if runner_id is not None:
        receivers = [runner_id]

    if not receivers:
        if actual_distance == 0:
            # Only reachable from a stale click: 0 is offered only
            # while a teammate shares the passer's space, and every
            # other distance is offered only where it lands short of
            # the goal zone, so nothing legal comes to a standstill.
            # A ball that never left the passer is the High Pass's
            # own 0-space case -- nowhere to throw it and nobody to
            # throw it to -- so it goes out rather than settling
            # under the passer's own feet.
            return setup_pass_out_step(engine, match, game)

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
        # announcement, which is `stop_draws_the_board`'s answer
        # and rank D1's rather than this card's.
        space_word = "space" if actual_distance == 1 else "spaces"
        return StepResult(
            narration=[
                f"**{engine.maneuver_name('setup_pass')}:** "
                "the ball is picked out "
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
            f"**{engine.maneuver_name('setup_pass')}:** "
            f"the ball {movement} to "
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


def setup_pass_out_step(
    engine: RulesEngine,
    match: MatchState,
    game: Optional[D12BallGame] = None,
) -> StepResult:
    """
    **Cross never reaches the goal zone**, so the only way it runs
    out of play is having nowhere to throw it at all: the passer on the
    last space before the goal zone -- the one position from which even
    1 space would reach it -- with no teammate beside them to take it
    at 0. Then the other team gains possession: a new play, both sides
    reset, and the gaining side sends the nearest player to fetch the
    ball -- the out-of-bounds outcome the game already has.

    Any other landing space is a pass that happened; see
    `setup_pass_step`, which leaves the ball lying there.

    Two things reach it: the menu with no distance to offer
    (`d12ball.flow.effects.offer_setup_pass_distance`) and the stale click that
    picks a 0 nobody is standing on, which is why it is its own step
    rather than a branch of the pass.
    """
    match.pending_effect_continuation = None
    gaining = send_ball_out_of_play(match, game)
    return StepResult(
        narration=[
            f"**{engine.maneuver_name('setup_pass')}:** "
            "there is nobody to pick the ball out to, "
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


# -- Answering an effect's own prompts ---------------------------------
#
# Phase 6 of docs/design/model-discord-split.md. Each of these was a cog
# method or a view body that mixed the rule with the posting; what is
# here is the rule. `d12ball.flow.driver.apply` runs one over a prompt
# it has checked, and the cog calls the same function.


def take_smooth_step(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    *,
    player_id: str,
) -> StepResult:
    """
    One Telekinetic taking the ball over, off the button they were
    offered. There is no roll and nothing to charge, so this is the
    whole of it: stop the ball on them, and finish the maneuver.

    **A Smooth is not a turnover**, which is the one place it parts
    company with a landed pull. Possession never changed hands, so
    nobody runs back and the ball keeps the speed the maneuver gave it
    -- the turn simply ends with a different player holding it.

    **The arrival it pre-empted does not happen.** That is the rule the
    pull already follows -- what the movement was going to lead to is
    exactly what taking the ball early takes away -- and it is what
    makes a Double Team into the goal zone safe: the own-goal roll the shove was
    about to ask for is never asked, because the ball is no longer
    sitting on the handler who would have rolled it (the author,
    2026-09-20). What it does not drop is the clock: the maneuver that
    moved the ball still costs its time, which rides out in
    `distance_moved`.

    **A turnover-driven arrival is the exception**, and the only one.
    `begin_run_back` is not a question about where the ball settles --
    it is the consequence of a turnover that has already happened -- so
    a Smooth cannot pre-empt it; it only changes who is standing on the
    ball when everyone runs back. The carrier this just set is the one
    who does not run back, exactly as a landed pull arranges it.

    **`board_changed` is False on both branches**, and deliberately:
    each of the two steps it hands to redraws as its last act (or, for
    the run back, batches to one refresh at the end), so reporting a
    move here would be a second write to the same five-in-five bucket
    for one click. See docs/design/rate-limits.md.
    """
    player = engine.get_player_definition(player_id)
    if player_id in match.pending_smooth:
        match.pending_smooth.remove(player_id)

    resume = match.pending_smooth_resume or {}
    match.pending_smooth_resume = None
    match.apply_smooth(player_id)

    smooth_emoji = tokens.species(SPECIES_TELEKINETIC)
    lead_in = (
        f"{smooth_emoji} **Smooth** — "
        f"{engine.format_player_label(match, player)} takes the ball "
        f"on {ball_space_phrase(match)}."
    )

    if resume.get("kind") == "run_back":
        return StepResult(
            narration=[lead_in],
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
        )

    return StepResult(
        narration=[lead_in],
        next=FollowOn(
            FollowOnStep.FINISH_MANEUVER_RESOLUTION,
            {
                "distance_moved": resume.get("distance_moved", 1),
                "turnover_occurred": False,
            },
        ),
    )


def speed_choice_step(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    *,
    target_speed: int,
    turnover_occurred: bool = False,
    distance_moved: int = 1,
) -> StepResult:
    """
    Set the ball speed a maneuver's last human choice asks for.

    A gambit's effect can reach past its own maneuver, and a speed
    choice is the last human step of the one that does: the
    unopposed Low Pass a beaten Pinpoint hands the side that stole
    it. (Cross's own pass followed a speed choice too, until the
    2026-10-03 card dropped the speed.) **What is still owed is written down
    here**, at the moment the effect has nothing left in front of it,
    and run instead of the ordinary tail. Written here rather than by
    the card that earned it because the record is what
    `effect_choice_prompt` reads first: a continuation on the match
    means the effect is past every prompt of its own, and it has to
    mean exactly that. See `MatchState.pending_effect_continuation`.
    """
    match.ball.speed = target_speed
    line = f"Ball speed is now **{target_speed}**."

    if match.pending_effect_continuation is None:
        winner_key = engine.settled_maneuver_winner(match, game)
        if winner_key is not None:
            resolving = engine.resolving_maneuver(match, winner_key)
            if (
                resolving in ("steal", "intercept")
                and engine.gambit_cost(match, winner_key) == "skilled_pass"
            ):
                match.pending_effect_continuation = {
                    "kind": "free_low_pass",
                    "player_id": match.challenger_id,
                }

    if match.pending_effect_continuation is not None:
        return StepResult(
            narration=[line],
            board_changed=True,
            next=FollowOn(
                FollowOnStep.CONTINUE_EFFECT,
                {
                    "distance_moved": distance_moved,
                    "turnover_occurred": turnover_occurred,
                },
            ),
        )

    return StepResult(
        narration=[line],
        board_changed=True,
        next=FollowOn(
            FollowOnStep.FINISH_MANEUVER_RESOLUTION,
            {
                "distance_moved": distance_moved,
                "turnover_occurred": turnover_occurred,
            },
        ),
    )


# -- Offering an effect's choice --------------------------------------
#
# Phase 6 of docs/design/model-discord-split.md. Each `offer_*` is the half of
# a won card that used to be `D12Ball.resolve_<card>`: does anybody
# have to be asked at all, and if so what. A card with nothing to
# choose applies itself; an AI side answers for itself; a coach is
# asked, and the ask is the prompt's. Every one of them ends on the
# same `apply` step the coach's own click reaches through
# `driver.answer`, so there is one answer to each card however it was
# chosen. What a frontend puts up for the prompt -- the field strip
# under the six distance questions -- is keyed on the kind.


def _possession_mention(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
) -> str:
    """The coach in possession, addressed, with their team's mark."""
    return format_player_with_team(
        game,
        engine.possession_player_number(game, match),
        mention=True,
    )


def offer_low_pass(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    key: str = "low_pass",
    free: bool = False,
    lead_in: str = "",
) -> StepResult:
    """
    A won Low Pass or Pinpoint: who it can reach, and whether
    anybody chooses.

    Pinpoint is a Low Pass with the nearest-each-way rule taken
    off, a space more reach, and the speed bonus tripled; every other
    thing about it is a Low Pass's, which is why the two share one
    function. `free` marks the unopposed Low Pass **Pinpoint's
    cost** hands the defense: it is not this side's maneuver, so it
    charges no further clock and cannot be a Pinpoint.

    A handler with no teammate in reach has won the maneuver and has
    nowhere to put the ball: it rolls forward -- 2 spaces for a Low
    Pass, 3 for a Pinpoint (the author, 2026-10-07; Law 6.5.5,
    19.5.3) -- and settles where it lands, and its speed still rises
    (2026-08-07): the maneuver's speed bonus doesn't depend on the
    pass finding anyone. A Low Pass's passer may still move, and is
    asked before the ball settles. No headline of its own
    for that loose ball: the ball may well roll onto somebody, so what
    to call it is a question about the space it stopped on rather than
    about the pass that failed.
    """
    candidates = engine.pass_candidates(match, key)
    name = engine.maneuver_name(key)

    if not candidates:
        offense_side = match.ball.possession
        roll = (
            SKILLED_PASS_REACH if key == "skilled_pass"
            else LOW_PASS_NOBODY_ROLL
        )
        actual_distance = match.move_ball_relative(offense_side, roll)
        match.ball.speed = min(
            BALL_SPEED_MAX, match.ball.speed + engine.pass_speed_bonus(key),
        )
        movement_note = (
            "the ball stays where it is"
            if not actual_distance
            else "the ball rolls a space forward"
            if actual_distance == 1
            else f"the ball rolls {actual_distance} spaces forward"
        )
        prefix = f"{lead_in}\n\n" if lead_in else ""
        content = (
            f"{prefix}**{name}:** there is "
            + (
                "no teammate within three spaces to receive it"
                if key == "skilled_pass"
                else "no teammate within two spaces to receive it"
            )
            + ", and a pass can't be played to the passer -- "
            f"{movement_note}. "
            f"Ball speed is now {match.ball.speed}."
        )
        advance = offer_passer_advance(
            engine, game, match, key, {"then": "loose"},
        )
        return StepResult(
            narration=[content],
            board_changed=True,
            next=advance if advance is not None else FollowOn(
                FollowOnStep.BEGIN_LOOSE_BALL, {"distance_moved": 1},
            ),
        )

    return StepResult(
        narration=[lead_in] if lead_in else [],
        next=PendingPrompt(
            PromptKind.LOW_PASS_CHOICE,
            f"{_possession_mention(engine, game, match)}, choose your "
            f"{name}:",
            maneuver_key=key,
            free=free,
        ),
    )


def offer_dribble_advance(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    lead_in: str = "",
) -> StepResult:
    """
    A won Dribble. Role ability -- Playmaker: may advance 2
    spaces instead of the usual 1. Everyone else has no choice to make
    here, so they skip straight to applying the fixed 1-space advance.
    """
    handler = engine.get_player_definition(match.active_player_id)
    if handler.role != PlayerRole.PLAYMAKER:
        return _with_lead_in(
            dribble_advance_step(engine, game, match, 1), lead_in,
        )

    return StepResult(
        narration=[lead_in] if lead_in else [],
        next=PendingPrompt(
            PromptKind.DRIBBLE_ADVANCE_CHOICE,
            f"{_possession_mention(engine, game, match)}, choose your "
            f"{engine.maneuver_name('dribble_advance')} "
            "distance (Playmaker ability):",
        ),
    )


def offer_dribble_burst(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    lead_in: str = "",
) -> StepResult:
    """
    A won Burst: how far, at a token a space -- see
    `dribble_burst_step` for the card, and `RulesEngine.dribble_burst_distances`
    for what is offered.

    From the last space of the field there is nothing to ask: a burst
    that moves nowhere costs nothing and still gets its speed choice.
    Applying 0 rather than putting up an empty menu is the same call
    `offer_high_pass` makes for a pass with no distance left in it.
    """
    distances = engine.dribble_burst_distances(match)

    if not distances:
        return _with_lead_in(
            dribble_burst_step(engine, game, match, 0), lead_in,
        )

    # "Drain 1" and "exhaust 1" are the verbs for gaining a token.
    cost = (
        "drain 1"
        if engine.drain_wording(game, match.active_player_id)
        else "exhaust 1"
    )
    # Emberdash's burst costs nothing (Law 21), so the prompt names no
    # price rather than one that is not charged.
    price = (
        ""
        if engine.has_special_ability(
            game, match.active_player_id, SpecialAbility.FREE_BURST,
        )
        else f" ({cost} a space)"
    )
    return StepResult(
        narration=[lead_in] if lead_in else [],
        next=PendingPrompt(
            PromptKind.DRIBBLE_BURST_CHOICE,
            f"{_possession_mention(engine, game, match)}, choose your "
            f"{engine.maneuver_name('dribble_burst')} distance{price}:",
        ),
    )


def offer_high_pass(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    lead_in: str = "",
) -> StepResult:
    """
    A won High Pass: how far to throw.

    There is nothing to choose when even the shortest pass reaches the
    goal zone -- 2, 3 and 4 all come to rest on the last space before
    it, so the pass reaches the goal zone before anyone picks anything
    (2026-08-10).
    The prompt is skipped rather than answered: asking would be putting
    one answer up three times, and a Fullback's 4 is no less moot than
    the 2. The distance handed on is the minimum, which is what the
    clock charges once the ball has come to rest.
    """
    distances = engine.high_pass_distance_options(match)
    if not distances:
        return _with_lead_in(
            high_pass_step(
                engine, match, MIN_HIGH_PASS_DISTANCE, game=game,
            ),
            lead_in,
        )

    return StepResult(
        narration=[lead_in] if lead_in else [],
        next=PendingPrompt(
            PromptKind.HIGH_PASS_CHOICE,
            f"{_possession_mention(engine, game, match)}, choose your "
            "High Pass distance:",
        ),
    )


def offer_setup_pass_distance(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    lead_in: str = "",
) -> StepResult:
    """
    Cross: 0, 1 or 3 spaces, and a teammate standing where it lands
    takes a scoring opportunity at the speed the ball already has --
    the card sets no speed (Law 19.7.2, 2026-10-03).

    **Every distance that fits on the field is offered**, whether or
    not anybody of the passing side is standing there -- see
    `RulesEngine.setup_pass_distances`. A pass that lands on nobody is
    a real outcome, not a pass the menu should refuse. **0 is the
    exception**: it means a teammate sharing the passer's own space,
    since a passer never receives their own pass (2026-08-12), so it is
    on the menu only while somebody else is standing there.

    **Cross never reaches the goal zone**, so the one way it goes out
    is having nowhere to throw it at all: the passer on the last space
    before the goal zone with no teammate beside them. That is the existing
    out-of-bounds outcome -- `setup_pass_out_step`.
    """
    distances = engine.setup_pass_distances(match)

    if not distances:
        return _with_lead_in(
            setup_pass_out_step(engine, match, game), lead_in,
        )

    return StepResult(
        narration=[lead_in] if lead_in else [],
        next=PendingPrompt(
            PromptKind.SETUP_PASS_CHOICE,
            f"{_possession_mention(engine, game, match)}, choose where "
            f"your **{engine.maneuver_name('setup_pass')}** lands:",
        ),
    )


def offer_speed_choice(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    player_id: str,
    skill_type: str,
    turnover_occurred: bool = False,
    distance_moved: int = 1,
    lead_in: str = "",
) -> StepResult:
    """
    Always the last choice in a maneuver's effect -- speed is
    manipulated after any run-back it caused (Steal), so this leads
    straight into `finish_maneuver_resolution` once chosen. The
    answer (`driver._answer_speed_delta_choice`) reads whether a
    turnover happened back off the position; `turnover_occurred` and
    `distance_moved` are what the callers still name and are not
    read here, since the AI's pick goes through the same answer a
    coach's does (step 7 of docs/architecture-migration.md).

    `lead_in` is narration from the maneuver that led here, and opens
    the prompt.

    In a tutorial the beat's speed note goes with the choice itself,
    the same way a maneuver's own note goes in front of its menu
    rather than with the lesson two messages up, and is held behind
    Continue -- see `d12ball.flow.gates`.
    """
    beat = tutorial_beat(game)
    if beat is not None and beat.speed_note:
        return gates.hold_behind_note(
            game, tutorial.NOTE_SPEED, None, lead_in=lead_in,
        )

    return StepResult(
        narration=[lead_in] if lead_in else [],
        next=PendingPrompt(
            PromptKind.SPEED_DELTA_CHOICE,
            speed_choice_ask(engine, game, match, player_id, skill_type),
            player_id=player_id,
            skill_type=skill_type,
        ),
    )


def _with_lead_in(result: StepResult, lead_in: str) -> StepResult:
    """`result`, with the lines said before it put back in front."""
    if lead_in:
        result.narration.insert(0, lead_in)
    return result


#: Which `offer_*` a settled card runs, by key. A tie a skill test
#: settled resolves as the basic card, which `RulesEngine.resolving_maneuver`
#: says, so the gambits' rows are the ones their basic card reaches
#: with a parameter -- see `begin_effect_resolution`.
EFFECT_OFFERS = {
    "low_pass": lambda engine, game, match: offer_low_pass(
        engine, game, match, key="low_pass",
    ),
    "skilled_pass": lambda engine, game, match: offer_low_pass(
        engine, game, match, key="skilled_pass",
    ),
    "dribble_advance": offer_dribble_advance,
    "dribble_burst": offer_dribble_burst,
    "high_pass": offer_high_pass,
    "setup_pass": offer_setup_pass_distance,
    "deflect": lambda engine, game, match: deflection_step(
        engine, match, "deflect",
    ),
    "clear": lambda engine, game, match: deflection_step(
        engine, match, "clear",
    ),
    "steal": lambda engine, game, match: steal_step(
        engine, match, "steal", game,
    ),
    "intercept": lambda engine, game, match: steal_step(
        engine, match, "intercept", game,
    ),
    "pressure": lambda engine, game, match: pressure_step(
        engine, match, "pressure", game,
    ),
    "double_team": lambda engine, game, match: pressure_step(
        engine, match, "double_team", game,
    ),
}


def begin_effect_resolution(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    winner_key: str,
    lead_in: str = "",
) -> StepResult:
    """
    Log the settled maneuver and run the won card's effect, by
    **key**. `offense_maneuver`/`defense_maneuver`/`active_player_id`/
    `challenger_id` all stay set until the whole pipeline (effect, any
    run-back, time) finishes -- `reset_maneuver` only happens at the
    very end, in `finish_maneuver_resolution` -- so a bot restart
    mid-choice can still reconstruct exactly where things left off
    (see `effect_choice_prompt`).

    **A tie settled by a skill test resolves as the basic card.** A
    gambit's effect follows the cards, so a winner that only won on
    the dice runs its counterpart's effect and the loser pays nothing
    -- see `RulesEngine.gambit_cost_applies`. Substituting the key
    here rather than branching inside six handlers is what keeps that
    one rule in one place.

    An unrecognised key (future data) has nothing to automate and
    falls through to the ordinary end of a maneuver, which is a game
    to finish rather than a game to lose.

    `lead_in` is always "" today -- `resolve_maneuver`'s reveal is a
    message of its own -- and is kept in front rather than dropped.

    **The clock is charged before the effect, and normally already
    was** (Law 16.2.4): every place a winner is decided charges it
    there and then, so this asks again only as a backstop, and
    `charge_maneuver_clock` answers "" for a maneuver already charged.
    What it catches is a game saved between a decision and its effect
    under the old rule -- a skill test's injury checks, most often --
    which reaches here with nothing on the clock yet.
    """
    if engine.double_team_partner_owed(
        match, engine.resolving_maneuver(match, winner_key),
    ):
        # **A Double Team's partner is chosen first** where several tie
        # (Law 19.10.3), won or beaten -- ahead of the log and the
        # effect, so the answer comes back through here and the
        # maneuver is still logged exactly once.
        return StepResult(
            narration=[lead_in] if lead_in else [],
            next=double_team_partner_prompt(engine, game, match),
        )
    record_maneuver(engine, match, winner_key)
    clock = charge_maneuver_clock(engine, match, winner_key)
    lead_in = "\n\n".join(filter(None, (lead_in, clock)))

    offer = EFFECT_OFFERS.get(engine.resolving_maneuver(match, winner_key))
    if offer is None:
        return StepResult(
            narration=[lead_in] if lead_in else [],
            next=FollowOn(FollowOnStep.FINISH_MANEUVER_RESOLUTION),
        )
    return _with_lead_in(offer(engine, game, match), lead_in)


def continue_effect(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    distance_moved: int = 1,
    turnover_occurred: bool = False,
    lead_in: str = "",
) -> StepResult:
    """
    Run whatever a gambit's effect still owes once its last prompt has
    been answered.

    **The record is cleared by whatever applies the step, not here.**
    A continuation is one more prompt, and a coach may take hours over
    it -- so between dispatching and the click that answers, the only
    thing on the match saying what is owed is this field. Clearing it
    at dispatch would leave a restart in that window reading the
    maneuver's winner instead and re-offering the speed choice a coach
    had already answered. `effect_choice_prompt` reads this first for
    the same reason.

    An unrecognised kind falls through to the ordinary end of a
    maneuver rather than stranding the turn: a continuation written by
    a version of the bot this one does not have is a game to finish,
    not a game to lose. That branch *does* clear it, or the next speed
    choice in the game would find it still set.
    """
    continuation = match.pending_effect_continuation or {}

    if continuation.get("kind") == "free_low_pass":
        # **Pinpoint's cost.** The defense stole the ball and now
        # plays a Low Pass with it, unopposed. The passer is whoever
        # took it -- named when the cost was recorded, and re-derived
        # from the ball if a run back has moved things since.
        passer_id = continuation.get("player_id")
        holders = match.eligible_ball_handlers()
        if passer_id not in holders:
            passer_id = holders[0] if holders else None
        if passer_id is not None:
            match.active_player_id = passer_id
            return offer_low_pass(
                engine, game, match, key="low_pass", free=True,
                lead_in=lead_in,
            )

    match.pending_effect_continuation = None
    # Named rather than called: the tail of a maneuver is a step the
    # frontend stops on.
    return StepResult(
        narration=[lead_in] if lead_in else [],
        next=FollowOn(
            FollowOnStep.FINISH_MANEUVER_RESOLUTION,
            {
                "distance_moved": distance_moved,
                "turnover_occurred": turnover_occurred,
            },
        ),
    )
