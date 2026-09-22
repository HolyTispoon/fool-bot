"""
The Coaching Choice and the time out that buys one, as flow steps.

Lifted in Phase 5 of docs/design/model-discord-split.md out of
`cogs/d12ball/turnovers.py`. See
[coaching-choice.md](../../docs/design/coaching-choice.md) and
[time-out.md](../../docs/design/time-out.md) for the rules, and "The
model and the Discord layer" in CLAUDE.md for the line these sit on.

**One flow, five occasions.** Setup, a new play's window, halftime, the
window before the shootout and a time out are the same walk through the
same menu, and `CoachingOccasion` carries every difference between them
-- the allowance, whether the declare-or-pass offer is put, where a
player taken off goes, and whether the three positional actions are
offered at all. Nothing here branches on which occasion it is except
where that enum has no property for it.

**The window's prompt is the one prompt in the game that carries the
coach's own half-field**, and `d12ball.flow.windows.begin_substitution_window` is
what attaches it. So this module opens a window and says what to ask;
the picture, the tutorial's Continue gate over the top of it, and the
menu's own clicks (which are `interaction.response.edit_message` and
never leave the one message) all stay in `cogs/`. That is why
`FollowOnStep.BEGIN_SUBSTITUTION_WINDOW` outlived this phase: a step
that wants to open a window names it rather than calling into a
frontend.

**`finish_substitution_window` is the junction of the whole thing.**
Five occasions come into it and five different things go out -- the
next stage of a sequence, the other coach's reply, a time out's tail,
or the run back a new play still owes -- and the order those are asked
in is a rule rather than a convenience. It moved whole for the reason
the arrival gates did.
"""

from __future__ import annotations

import logging
from typing import Optional

from d12ball.components import (
    CoachingOccasion,
    EVENT_TIME_OUT,
    MatchState,
    RuleRefusal,
    SPECIES_CYBORG,
    TeamSide,
    Zone,
)
from d12ball import tutorial
from d12ball.engine import RulesEngine
from d12ball.flow import gates
from d12ball.flow.result import FollowOn, FollowOnStep, StepResult
from d12ball.flow.turnovers import begin_ball_recovery
from d12ball.formatting import (
    destination_display_name,
    format_team_side_label,
    get_exhaust_emoji,
    get_team_emoji,
    space_label,
)
from d12ball.game import D12BallGame
from d12ball.prompts import PendingPrompt, PromptKind


LOGGER = logging.getLogger(__name__)


# -- What the window says --------------------------------------------


def coaching_window_note(
    engine: RulesEngine,
    match: MatchState,
    side: TeamSide,
    occasion: CoachingOccasion,
    is_response: bool,
    restored: bool,
) -> str:
    """
    The line under a coaching prompt: what this window costs, what
    moved on the way in, and who is hurt.

    The three answer separately -- the question, if there is one,
    then a restore only where it actually moved somebody, then an
    injured player as a nudge rather than a requirement. Any of
    them may have nothing to say, so the parts that are there are
    joined rather than interpolated; see "What a message says".

    **Almost all of it is gone, and what is left is the question
    and the reason** (the author, 2026-09-16). Every branch used to
    explain what the window cost and what it left unspent -- a
    paragraph of rules recited above a menu that answers the same
    questions by what it offers, and the header above it already
    carries the substitution allowance.

    - A new play asks **"Coach?"**, because the two buttons under it
      are Coach and Pass and the question is the whole of the note.
    - A time out's own coach is told nothing: they pressed the
      button, so there is nothing a note can add.
    - The **one reply that says anything** is a time out's, and it
      says only what the coach could not otherwise know: the other
      team called one. A new play's reply is silent, since the
      restart they are answering is in the channel above them.

    What it cost and what it left unspent were both worth saying
    while a window was once a half and shared between the two
    occasions. It no longer is -- a new play's is free and
    unlimited -- so the reassurance was answering a question
    nobody had.
    """
    lines: list[str] = []
    if occasion.asks_declaration and not is_response:
        lines.append("Coach?")
    elif occasion == CoachingOccasion.TIME_OUT and is_response:
        lines.append("The other team called a time out.")

    # Said only when it actually moved somebody, which is halftime
    # and nowhere else: a coach who left the first half with their
    # side scattered is looking at their own shape again and
    # should be told why.
    if restored:
        lines.append("Your side is back on the arrangement you last set.")

    # An injured player is worth pointing out, but only as a
    # nudge: nothing compels a side to get them off, and a coach
    # may leave them on, disadvantaged, all game.
    injured_ids = match.injured_field_players(side)
    if injured_ids:
        injured = ", ".join(
            engine.format_player_label(
                match, engine.get_player_definition(player_id),
            )
            for player_id in injured_ids
        )
        verb = "is" if len(injured_ids) == 1 else "are"
        lines.append(f"{injured} {verb} injured and still on the field.")

    return "\n".join(lines)


def coaching_summary(
    engine: RulesEngine,
    match: MatchState,
    side: TeamSide,
) -> list[str]:
    """
    What the open window changed, a line each, for the message it
    closes with. Asked while the window is still open -- closing
    it clears what this reads.

    **Only the shape and the swaps.** Zone assignment and space
    positioning are on the board everyone can see, and the board
    is posted the moment coaching is over; a substitution changes
    who is playing, and a formation change is the shape those
    positions are read against, so both are worth saying in words.
    The substitution notes especially: each one is written over by
    the next step of the flow, so without this they are gone by
    the time the coach clicks Done.
    """
    side = TeamSide(side)
    lines: list[str] = []

    was = match.pending_coaching_formation
    now = engine.current_formation(match, side)
    if now is not None and now.value != was:
        lines.append(
            f"Formation: **{was} → {now.value}**."
            if was
            else f"Formation: **{now.value}**."
        )

    for outgoing_player_id, incoming_player_id in (
        match.pending_coaching_swaps
    ):
        outgoing = engine.get_player_definition(outgoing_player_id)
        incoming = engine.get_player_definition(incoming_player_id)
        lines.append(
            f"{engine.format_player_label(match, incoming)} came "
            f"on for {engine.format_player_label(match, outgoing)}."
        )

    return lines


# -- What the window does --------------------------------------------


def apply_substitution(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    side: TeamSide,
    outgoing_player_id: str,
    incoming_player_id: str,
) -> str:
    """
    Make one swap and describe it. Raises `RuleRefusal` with the
    rule that refused it if the swap is not allowed.

    **The allowance is asked here, before anything moves.** Until step
    6 of docs/architecture-migration.md only the hub's button asked
    `may_substitute`, and a third new-play substitution sent through
    the driver went through with "No substitutions left." in its own
    narration (finding 3 of docs/web-app.md). A button is a
    convenience over the rule, never the rule.
    """
    if not match.may_substitute():
        raise RuleRefusal(
            f"{engine.substitution_allowance_label(match)} in this "
            "Coaching Choice."
        )
    was_injured = outgoing_player_id in match.injured
    from_back_bench = (
        incoming_player_id
        in match.setup_for_side(side).team_board.back_bench
    )
    occasion = match.coaching_occasion or CoachingOccasion.NEW_PLAY

    match.substitute(
        side,
        outgoing_player_id,
        incoming_player_id,
        retire_outgoing=occasion.retires_outgoing_players,
    )
    match.record_substitution(outgoing_player_id, incoming_player_id)

    outgoing = engine.get_player_definition(outgoing_player_id)
    incoming = engine.get_player_definition(incoming_player_id)
    outgoing_drain = engine.has_species_ability(
        game, outgoing_player_id, SPECIES_CYBORG,
    )
    was_damaged = was_injured and outgoing_drain
    text = (
        f"{engine.format_player_label(match, incoming)} comes on "
        f"for {engine.format_player_label(match, outgoing)}"
        f"{' (damaged)' if was_damaged else ''}"
        f"{' (injured)' if was_injured and not outgoing_drain else ''}."
    )

    if from_back_bench:
        # Half the tokens, rounded up, come off a returning
        # player -- but Exhausted is whatever the remainder says,
        # so it has to be re-tested rather than assumed cleared.
        #
        # Against their own threshold, which for a Cyborg is the
        # flat Drained line rather than their defensive skill: a
        # Cyborg is exactly the player this re-test would get
        # wrong, since half of a big drain total is still well
        # over a striker's defence of 2 and nowhere near 7.
        threshold = engine.exhaustion_threshold(game, incoming_player_id)
        incoming_drain = engine.has_species_ability(
            game, incoming_player_id, SPECIES_CYBORG,
        )
        noun = "drain" if incoming_drain else "exhaustion"
        remaining = match.exhaustion.get(incoming_player_id, 0)
        exhaust_emoji = get_exhaust_emoji(engine.condition_emojis)
        text += (
            f"\nBack on from the back bench, down to {remaining} "
            f"{noun} {'token' if remaining == 1 else 'tokens'} "
            f"{exhaust_emoji * remaining}."
        )
        if match.mark_exhausted_if_needed(incoming_player_id, threshold):
            condition = "Drained" if incoming_drain else "Exhausted"
            text += (
                f" Still **{condition}** -- {remaining} is over "
                f"{threshold}."
            )

    text += f"\n{engine.substitution_allowance_label(match)}."
    return text


def apply_position_swap(
    engine: RulesEngine,
    match: MatchState,
    side: TeamSide,
    player_id: str,
    other_player_id: str,
) -> str:
    """
    The Coaching Choice's zone assignment: trade two players' zones,
    meeples included, and describe it.

    `d12ball.flow.windows.apply_position_swap` was this; it moved in Phase 6 because
    a window's answers are the window's, and a sentence about the
    position is the model's (principle 5 in CLAUDE.md).
    """
    match.exchange_field_players(side, player_id, other_player_id)

    setup = match.setup_for_side(side)
    board_size = match.board.layout.board_size
    first = engine.get_player_definition(player_id)
    second = engine.get_player_definition(other_player_id)
    return (
        f"{engine.format_player_label(match, first)} and "
        f"{engine.format_player_label(match, second)} change "
        "places: "
        f"{engine.format_player_label(match, first)} to "
        f"{destination_display_name(setup.assigned_zone(player_id).value, board_size)}"
        f", {engine.format_player_label(match, second)} to "
        f"{destination_display_name(setup.assigned_zone(other_player_id).value, board_size)}"
        ". No exhaustion cost."
    )


def apply_reposition(
    engine: RulesEngine,
    match: MatchState,
    side: TeamSide,
    player_id: str,
    space_index: int,
    swap_with: Optional[str] = None,
) -> str:
    """
    The Coaching Choice's space positioning: move one meeple within its
    own zone, trading with whoever is already there when the rule says
    so, and describe what happened.
    """
    setup = match.setup_for_side(side)
    zone = setup.assigned_zone(player_id)
    partner = match.position_meeple(
        side, player_id, space_index, swap_with=swap_with,
    )

    player = engine.get_player_definition(player_id)
    if partner is None:
        return (
            f"{engine.format_player_label(match, player)} moves "
            f"to {space_label(zone, space_index)}. No exhaustion cost."
        )
    other = engine.get_player_definition(partner)
    return (
        f"{engine.format_player_label(match, player)} moves to "
        f"{space_label(zone, space_index)} and "
        f"{engine.format_player_label(match, other)} takes their "
        "place. No exhaustion cost."
    )


def declare_coaching_step(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
) -> StepResult:
    """
    Take the coaching window up. It says nothing: the hub that replaces
    the offer is what a coach reads next.
    """
    match.declare_coaching()
    return StepResult()


def decline_coaching_step(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    *,
    side: TeamSide,
    coach_name: str,
) -> StepResult:
    """
    Pass on a coaching window that was offered rather than given.

    `coach_name` is what to call the person who passed. **It is a
    label the frontend supplies, not a rule** -- the same shape
    `begin_shot_step`'s `action_label` has: this one message names the
    human rather than the side, which nothing in the match knows, and
    a model that guessed at it would be inventing a fact about a
    Discord account. Everything around it is the model's, including
    that it is a heading and that the window closes behind it.
    """
    setup = match.setup_for_side(side)
    return StepResult(
        narration=[
            "# Coaching Choice\n"
            f"**{get_team_emoji(engine.team_emojis, setup.team)} "
            f"{coach_name} passed.**"
        ],
        next=FollowOn(FollowOnStep.FINISH_SUBSTITUTION_WINDOW),
    )


def finish_coaching_step(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    *,
    side: TeamSide,
) -> StepResult:
    """
    Close a coaching window a coach has finished with, and say what
    they did.

    **The summary is read while the window still remembers it**:
    closing it clears the record, and every note the flow put up along
    the way was written over by the step after it, so this message is
    the only place a coach's substitutions survive.

    `RulesEngine.coaching_finish_refusal` is what says they may not
    close it yet -- a half-made substitution -- and it is raised here
    so it arrives as a refusal like every other.
    """
    refusal = engine.coaching_finish_refusal(match, side)
    if refusal is not None:
        raise RuleRefusal(refusal)

    setup = match.setup_for_side(side)
    changes = coaching_summary(engine, match, side)
    return StepResult(
        narration=[
            "\n".join(
                [
                    "# Coaching Choice",
                    f"**{format_team_side_label(setup)} are done.**",
                    *(changes or ["No substitutions, and no change of shape."]),
                ]
            )
        ],
        next=FollowOn(FollowOnStep.FINISH_SUBSTITUTION_WINDOW),
    )


def cover_kickoff_space(
    engine: RulesEngine,
    match: MatchState,
    side: TeamSide,
) -> Optional[str]:
    """
    Put one of an AI side's meeples on their own kickoff space when
    nobody is standing on it, and describe the move -- or None when
    there is nothing to do.

    A human coach is refused the Done button until they have
    covered it (see `RulesEngine.coaching_finish_refusal`); the AI has
    no menu to be held in, so it does the same thing here. The kickoff
    space is always in midfield and every basic shape puts at least two
    cards there, so the mover is always somebody whose own zone it is.
    """
    side = TeamSide(side)
    if engine.coaching_finish_refusal(match, side) is None:
        return None

    setup = match.setup_for_side(side)
    kickoff_index = match.kickoff_space_for(side)
    kickoff_flat = match.board.flat_index(Zone.MIDFIELD, kickoff_index)
    candidates = [
        player_id
        for player_id in setup.field_players
        if setup.assigned_zone(player_id) == Zone.MIDFIELD
    ]
    if not candidates:
        LOGGER.error(
            "No %s card is assigned to midfield, so nobody can take "
            "the kickoff space.",
            side.value,
        )
        return None

    def distance(player_id: str) -> int:
        position = match.board.meeple_position(player_id)
        if position is None:
            return 10**6
        return abs(match.board.flat_index(*position) - kickoff_flat)

    nearest = min(candidates, key=distance)
    match.position_meeple(side, nearest, kickoff_index)
    player = engine.get_player_definition(nearest)
    return (
        f"{engine.format_player_label(match, player)} takes the "
        f"kickoff spot at {space_label(Zone.MIDFIELD, kickoff_index)}."
    )


def open_substitution_window(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    side: TeamSide,
    occasion: CoachingOccasion = CoachingOccasion.NEW_PLAY,
    is_response: bool = False,
    heading: str = "",
) -> StepResult:
    """
    Offer `side` the window. A declaration is once a half, so a
    side that has already spent theirs is never offered one. An
    injured player on the field is named in the heading but
    compels nothing -- leaving them on is the coach's call.

    `occasion` carries every difference between the five -- the
    substitution allowance, whether the declare-or-pass offer is
    put at all, where a player taken off goes, and whether the
    three positional actions are offered at all. Setup, halftime
    and full time are given rather than declared, so all three skip
    the offer and open the menu directly; a time out skips it for
    the opposite reason, having already been paid for.

    **A window opens on the arrangement its coach last settled**,
    never on the scramble a run back left behind -- see
    `MatchState.restore_assigned_positions`. A new play resets both
    sides before offering the window, so this only ever does
    anything at halftime, where the first half ended wherever it
    ended; but it is the guarantee for every occasion rather than
    a halftime step, because a coach reading their half-field is
    reading the shape they set either way.

    Except full time, which has no positioning in it: nothing is
    played from a position after it, so restoring would rearrange
    the last board of the game to no purpose.

    **`heading` is the window's own opening line, not a lead-in.** It
    goes *inside* the prompt (`RulesEngine.coaching_prompt` puts it
    above the allowance), which is why it rides as a named argument
    rather than as narration the frontend would post above the menu.
    A new play's announcement is the other thing and is a block of
    narration on the step that opened the window.
    """
    side = TeamSide(side)
    occasion = CoachingOccasion(occasion)

    restored = (
        match.restore_assigned_positions(side)
        if occasion.offers_positioning
        else False
    )
    shape = engine.current_formation(match, side)
    match.open_coaching_window(
        side,
        occasion,
        is_response=is_response,
        formation=shape.value if shape else None,
    )

    if engine.side_is_ai(game, side):
        result = run_ai_substitution_window(engine, game, match, heading)
        # Only when the restore actually moved somebody, so the
        # common case -- setup, and a new play that has just reset
        # both sides -- costs nothing.
        result.board_changed = result.board_changed or restored
        return result

    note = coaching_window_note(
        engine, match, side, occasion, is_response, restored,
    )
    return StepResult(
        # Only when the restore actually moved somebody. Halftime does
        # move them, and a coach whose half-field disagrees with the
        # board above it has no way to tell which one the game thinks
        # is true.
        board_changed=restored,
        next=PendingPrompt(
            PromptKind.COACHING_OFFER
            if occasion.asks_declaration
            else PromptKind.COACHING_HUB,
            engine.coaching_prompt(game, match, side, note, lead_in=heading),
            side=side,
        ),
    )


def begin_substitution_window(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    side: TeamSide,
    occasion: CoachingOccasion = CoachingOccasion.NEW_PLAY,
    is_response: bool = False,
    heading: str = "",
    lead_in: str = "",
) -> StepResult:
    """
    Open a coaching window -- `open_substitution_window` -- behind the
    tutorial's coaching explainer where that is still owed.

    The explainer is the tutorial's last lesson, and the one it cannot
    schedule: a new play offers the window to the side *restarting*
    play, which after the coach's goal is Dinky. So the note fires at
    the first window this coach is ever offered, whenever the game
    gets round to it -- which is why it reads `tutorial` rather than
    `in_tutorial`, and usually lands a few turns after the script has
    finished. `skip_tutorial` sets `tutorial_coaching_explained` so a
    coach who opted out is not taught anyway.

    **The flag is set before the gate goes up**, so the window this
    gate holds -- the same step, with the same arguments -- opens
    rather than gating again when the coach continues. See
    `d12ball.flow.gates`.

    `heading` is the window's own opening line and goes *inside* the
    prompt (`RulesEngine.coaching_prompt` puts it above the
    allowance); `lead_in` is the narration of whatever step named this
    one -- a new play's reset, the full-time whistle -- and is its own
    message above the menu, which the frontend keeps apart
    (`DRIVER_OWN_MESSAGE`).
    """
    side = TeamSide(side)
    occasion = CoachingOccasion(occasion)

    if (
        game.tutorial
        and not game.tutorial_coaching_explained
        and side == tutorial.player_side(game)
    ):
        game.tutorial_coaching_explained = True
        return gates.hold_behind_note(
            game,
            tutorial.NOTE_COACHING,
            FollowOn(
                FollowOnStep.BEGIN_SUBSTITUTION_WINDOW,
                {
                    "side": side,
                    "occasion": occasion,
                    "is_response": is_response,
                    "heading": heading,
                },
            ),
            lead_in=lead_in,
        )

    result = open_substitution_window(
        engine,
        game,
        match,
        side,
        occasion,
        is_response=is_response,
        heading=heading,
    )
    if lead_in:
        result.narration.insert(0, lead_in)
    return result


def run_ai_substitution_window(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    heading: str = "",
) -> StepResult:
    """
    An AI side's whole window, start to finish: it is a routine rather
    than a menu, so there is nothing to put in front of anybody and
    nothing to come back to after a restart.
    """
    side = TeamSide(match.pending_coaching_side)
    occasion = match.coaching_occasion or CoachingOccasion.NEW_PLAY
    strategy = engine.get_ai_strategy(game)
    lines: list[str] = []

    while match.may_substitute():
        choice = strategy.choose_substitution(match, side)
        if choice is None:
            break
        if not match.pending_coaching_declared:
            match.declare_coaching()
        outgoing_player_id, incoming_player_id = choice
        try:
            lines.append(
                apply_substitution(
                    engine,
                    game,
                    match,
                    side,
                    outgoing_player_id,
                    incoming_player_id,
                )
            )
        except RuleRefusal as error:
            LOGGER.error(
                "AI substitution refused in game %s: %s",
                game.game_id, error,
            )
            break

    covered = cover_kickoff_space(engine, match, side)
    if covered:
        lines.append(covered)

    setup = match.setup_for_side(side)
    prefix = f"{heading}\n\n" if heading else ""
    narration: list[str] = []
    board_changed = False
    if lines:
        body = "\n".join(lines)
        narration.append(
            f"{prefix}# Coaching Choice\n"
            f"{format_team_side_label(setup)}:\n{body}"
        )
        # Before kickoff there is no board up yet, deliberately --
        # `finish_setup_coaching` posts it once both coaches are
        # done, and an AI window is not the moment to break that.
        board_changed = match.pending_setup_stage is None
    elif heading and occasion.spends_time_out:
        # A new play's heading is the announcement that opened the
        # window -- the goal, the miss -- and has to be posted
        # whatever the AI decided. Setup's and halftime's are
        # instructions to a coach, so an AI that changed nothing
        # says nothing rather than posting a menu heading with no
        # menu under it.
        narration.append(heading)

    result = finish_substitution_window(engine, game, match)
    result.narration[:0] = narration
    result.board_changed = result.board_changed or board_changed
    return result


def finish_substitution_window(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
) -> StepResult:
    """
    Hand the window on, or give up on it and let the run back go
    ahead. The other team only gets its single answering
    substitution because a declaration actually happened -- a side
    that passes takes the opposing reply down with it.

    A side that used its window comes out of it standing where its
    coach put them, and that becomes the arrangement the next new
    play restores. A side that passed changed nothing, so their
    existing arrangement stands untouched.
    """
    from d12ball.flow.periods import (
        advance_full_time_stage,
        advance_halftime_stage,
        advance_setup_stage,
    )

    declared = match.pending_coaching_declared
    was_response = match.pending_coaching_is_response
    occasion = match.coaching_occasion
    side = (
        TeamSide(match.pending_coaching_side)
        if match.pending_coaching_side
        else None
    )
    match.close_coaching_window()
    # Full time records nothing: the window it closes had no
    # positioning in it, and nothing is played from a position
    # again, so writing where the second half left the side would
    # overwrite the coach's arrangement with a scramble no new play
    # will ever restore.
    if (
        declared
        and side is not None
        and (occasion is None or occasion.offers_positioning)
    ):
        match.set_assigned_positions(side)

    # Setup, halftime and full time give each side its own window
    # rather than a turnover's declare-then-respond pairing, so all
    # three move on to the next stage of their own sequence instead
    # of offering the other side a response.
    if match.pending_full_time_stage is not None:
        engine.next_full_time_stage(match)
        return advance_full_time_stage(engine, game, match)

    if match.pending_setup_stage is not None:
        engine.next_setup_stage(match)
        return advance_setup_stage(engine, game, match)

    if engine.halftime_stage(match) in ("coaching_home", "coaching_visiting"):
        engine.next_halftime_stage(match)
        return advance_halftime_stage(engine, game, match)

    if declared and not was_response and side is not None:
        other_side = (
            TeamSide.VISITING
            if side == TeamSide.HOME
            else TeamSide.HOME
        )
        # The reply is the same occasion as the declaration it
        # answers -- a time out opens the other coach's window
        # already declared too, since there is nothing for them to
        # pass on: they have been handed the ball and the window
        # both, and neither costs them anything.
        return StepResult(
            next=FollowOn(
                FollowOnStep.BEGIN_SUBSTITUTION_WINDOW,
                {
                    "side": other_side,
                    "occasion": occasion or CoachingOccasion.NEW_PLAY,
                    "is_response": True,
                },
            ),
        )

    if match.pending_time_out:
        # Nobody ran anywhere and nothing is displaced: both sides
        # took the field on their own arrangement as their windows
        # opened. So this skips the run back entirely rather than
        # letting it charge for a scramble that never happened.
        return finish_time_out(engine, game, match)

    return StepResult(next=FollowOn(FollowOnStep.ANNOUNCE_RUN_BACK))


# -- The time out ----------------------------------------------------


def begin_time_out(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
) -> StepResult:
    """
    The side in possession stops play to coach -- see "Time out" in
    docs/living-rules.md, and `MatchState.may_call_time_out` for
    when it is on offer at all.

    **It is not a turnover.** The ball does not move, possession
    does not change, ball speed is left alone and nobody runs back.
    What it costs is the flat space minute every action costs
    (2026-08-16), charged in `finish_time_out` once its tail (a
    pickup may span a restart) is settled.

    Both coaches then coach: the caller's window opens at once, and
    `finish_substitution_window` hands the other theirs exactly as
    a declaration's reply -- which is what it is.

    **There is no last-possession branch here any more, because the
    button is never built then.** Ceding was a turnover, so under
    last possession it ended the period; a time out turns nothing
    over, and the author refused it outright there instead
    (2026-09-16). `may_call_time_out` is the whole of that, and
    `PlayerActionView` and `choose_action` both read it -- so this
    is only ever reached in a position where play goes on.
    """
    # **Its own event kind, not a turn action** (the author,
    # 2026-09-16). A possession is a run of consecutive
    # `turn_action`s by one side and every event in a turn belongs
    # to the last one before it, so logging a pause as a turn would
    # invent a turn nobody played and hang the rest of the real
    # turn's events off it. It is still recorded -- a coach wants
    # to know how often these get called -- on a row of its own in
    # the statistics.
    #
    # **Recorded here rather than on the confirm prompt**, which is
    # where the two real turn actions are recorded. A time out is
    # the one of the three that asks first, and a coach who opens
    # the confirm and presses Back has not called one.
    #
    # Read before `call_time_out`, which resets the turn: the side
    # is the side in possession, and that is what the record is of.
    match.record_event(
        EVENT_TIME_OUT,
        side=match.ball.possession,
        player_id=match.active_player_id,
    )

    side = match.call_time_out()
    label = format_team_side_label(match.setup_for_side(side))

    return StepResult(
        board_changed=True,
        next=FollowOn(
            FollowOnStep.BEGIN_SUBSTITUTION_WINDOW,
            {
                "side": side,
                "occasion": CoachingOccasion.TIME_OUT,
                "heading": (
                    f"# {label} call a time out\n"
                    "Both coaches get a Coaching Choice. The ball stays "
                    f"with {label} on "
                    f"{space_label(match.ball.zone, match.ball.space_index)}."
                ),
            },
        ),
    )


def finish_time_out(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
) -> StepResult:
    """
    The tail of a time out, once both coaches have closed their
    windows. There is no run back to run and none is owed: each
    window opened on its own coach's arrangement, so by here both
    sides are standing where their own coach left them.

    What is left is whether the side that called it still has
    anybody on their own ball. A Coaching Choice can re-deal a
    whole side, so a coach can rearrange their handler off the
    space the ball is lying on. Possession is the team's and stays
    with them either way (the author, 2026-09-16); they send the
    nearest player either side of it to pick it back up.

    **That pickup is free**, which is the one walk to the ball in
    the game that charges nothing. A time out costs a minute and no
    exhaustion, and a coach should not be billed for putting
    somebody back on a ball their side never lost.
    `pending_recovery_from_time_out` is what says so, and it says
    the other half too: the pickup is not a turnover, because the
    side doing it is the side that had the ball all along.

    **`turnover_occurred` is False**, unlike a cede's, and that is
    the whole of what stopped being a turnover: nothing resets ball
    speed, and last possession is not ended by a side keeping the
    ball it already had. The button is not built under last
    possession at all -- see `MatchState.may_call_time_out`.

    `pending_time_out` is cleared before either branch: from here on
    the state says what is owed on its own, and leaving it set
    would have `pending_prompt` answering for a window that has
    closed.
    """
    match.pending_time_out = False
    needs_recovery = not match.eligible_ball_handlers()
    match.pending_ball_recovery = needs_recovery
    match.pending_recovery_from_time_out = needs_recovery

    if needs_recovery:
        return begin_ball_recovery(engine, game, match)

    # A time out costs the flat space minute every action costs
    # (2026-08-16), and nothing else: no turnover, so no speed
    # reset and no last-possession end.
    return StepResult(
        next=FollowOn(
            FollowOnStep.FINISH_MANEUVER_RESOLUTION,
            {"distance_moved": 1, "turnover_occurred": False},
        ),
    )
