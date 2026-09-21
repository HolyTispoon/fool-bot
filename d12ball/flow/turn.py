"""
The front half of a turn, as flow steps: who challenges, what each side
picked, and which card won.

Lifted in Phase 4 of docs/model-discord-split.md out of
`cogs/d12ball/core.py`. Nothing in Phases 1 to 3 touched this half --
it is easy to read as covered by "the spine" and it was not -- and both
a human's pick and `play_ai_turn`'s pass through it, which is why
`interaction` could not die from the turn until this moved too.

**Four of the five functions here are wording**, and that is the point
rather than an accident: `maneuver_winner_text` and
`skill_test_headline` are the four ways a maneuver can land, worded,
and the wording rules are rules (principle 5). Who *won* is
`settled_maneuver_winner`'s alone to say and always was; what moved is
only the sentence about it.

See "Sending a player" in docs/design/sending-a-player.md for the
challenger, and "Maneuvers" in docs/design/maneuvers.md for how rank
decides and what an injured participant forfeits.
"""

from __future__ import annotations

from typing import Optional

from d12ball import tutorial
from d12ball.components import MatchState, SPECIES_CYBORG
from d12ball.engine import RulesEngine
from d12ball.flow.result import FollowOn, FollowOnStep, StepResult
from d12ball.formatting import (
    format_player_with_team,
    format_team_side_label,
    get_damaged_emoji,
    get_injured_emoji,
)
from d12ball.game import D12BallGame
from d12ball.prompts import PendingPrompt, PromptKind

#: Which row a lone side is told to press, by name. The buttons carry
#: the colour themselves (see `ManeuverActionPromptView`); this is the
#: word for it in the line above them.
MANEUVER_ROW_COLOURS = {"offense": "red", "defense": "green"}


def injured_word_and_emoji(
    engine: RulesEngine,
    game: D12BallGame,
    player_id: str,
) -> tuple[str, str]:
    """
    What a player out of the contest is called, and the mark for it.

    A Cyborg is **damaged** rather than injured -- the same condition
    under a different name, which is the species' own wording and not a
    second rule.
    """
    if engine.has_species_ability(game, player_id, SPECIES_CYBORG):
        return "damaged", get_damaged_emoji(engine.condition_emojis)
    return "injured", get_injured_emoji(engine.condition_emojis)


def maneuver_winner_text(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    reveal: str,
    outcome: str,
    winner_name: str,
    offense_name: str,
    defense_name: str,
) -> str:
    """
    How a maneuver settled on the cards reads. Two wordings: an
    ordinary decisive win, and a tie one injured participant loses
    outright.
    """
    if outcome != "tie":
        # Headed the same way a won skill test is (see
        # SkillTestView.roll), so the two ways a maneuver can be won
        # read alike. Whoever resolves the effect isn't named here: an
        # effect with a choice in it prompts them by name itself, and
        # one without needs nobody to do anything.
        return f"{reveal}\n\n## **{winner_name}** wins!"

    # A tie with exactly one injured participant: they lose it
    # outright. Nothing is rolled, so neither side pays the token a
    # skill test would have cost them.
    injured_player_id = (
        match.challenger_id
        if match.challenger_id in match.injured
        else match.active_player_id
    )
    injured_player = engine.get_player_definition(injured_player_id)
    word, emoji = injured_word_and_emoji(engine, game, injured_player_id)
    return (
        f"{reveal}\n\n"
        f"**{offense_name}** ties with **{defense_name}**, but "
        f"{engine.format_player_label(match, injured_player)}"
        f" is **{word}** "
        f"{emoji} and "
        "automatically loses the tie.\n\n"
        f"## **{winner_name}** wins!"
    )


def skill_test_headline(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    reveal: str,
    outcome: str,
    offense_name: str,
    defense_name: str,
) -> str:
    """
    Why a maneuver the cards did not settle is going to a skill test:
    the two ranked the same, or the one that would have won is owed to
    an injured player.
    """
    if outcome == "tie":
        # An ordinary tie -- both or neither participant is injured.
        return (
            f"{reveal}\n\n"
            f"**{offense_name}** ties with **{defense_name}** — skill "
            "test!\n\n"
        )

    # An injured player's maneuver never wins outright -- they still
    # have to win a skill test to make it stick.
    would_be_winner = offense_name if outcome == "offense" else defense_name
    injured_player_id = (
        match.active_player_id
        if outcome == "offense"
        else match.challenger_id
    )
    injured_player = engine.get_player_definition(injured_player_id)
    word, emoji = injured_word_and_emoji(engine, game, injured_player_id)
    return (
        f"{reveal}\n\n"
        f"**{would_be_winner}** would win, but "
        f"{engine.format_player_label(match, injured_player)} is "
        f"**{word}** {emoji} -- "
        "a skill test decides it instead!\n\n"
    )


def resolve_maneuver(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
) -> StepResult:
    """
    Reveal both picks and say how the maneuver landed: won on the
    cards, won by an injured opponent's forfeit, or going to a skill
    test.

    **Nothing here decides who wins.** `settled_maneuver_winner` does,
    and `ManeuverCatalog.resolve` ranks the two cards; what this adds
    is which of four sentences says so -- an ordinary win, a win handed
    over by an injury, a tie, and a would-be win an injury sends to a
    test. The distinction matters because a coach reading the channel
    has to be able to tell the four apart.
    """
    # Keys are what the match holds and what everything below
    # dispatches on; the names are only ever printed.
    offense_key = match.offense_maneuver
    defense_key = match.defense_maneuver
    offense_name = engine.maneuver_name(offense_key)
    defense_name = engine.maneuver_name(defense_key)
    offense_display = format_player_with_team(
        game,
        engine.possession_player_number(game, match),
        engine.team_emojis,
    )
    defense_display = format_player_with_team(
        game,
        engine.defending_player_number(game, match),
        engine.team_emojis,
    )

    if match.maneuver_uncontested:
        # Nothing to reveal against and nothing to rank: the offense's
        # pick is the winner, and its effect runs the same pipeline a
        # decisive win always does.
        return StepResult(
            narration=[
                f"{offense_display} chose **{offense_name}**, "
                f"unchallenged.\n\n## **{offense_name}** succeeds!"
            ],
            next=FollowOn(
                FollowOnStep.BEGIN_EFFECT_RESOLUTION,
                {"winner_key": offense_key},
            ),
        )

    reveal = (
        f"{offense_display} chose **{offense_name}**.\n"
        f"{defense_display} chose **{defense_name}**."
    )

    # Who wins is settled_maneuver_winner's alone to say; what is
    # decided here is only how the four ways it can land are worded.
    # `outcome` is the ranking on its own, which is what separates a
    # win on the cards from a win handed over by the other player's
    # injury.
    outcome = engine.maneuver_catalog.resolve(offense_key, defense_key)
    winner_key = engine.settled_maneuver_winner(match)

    if winner_key is not None:
        return StepResult(
            narration=[
                maneuver_winner_text(
                    engine,
                    game,
                    match,
                    reveal,
                    outcome,
                    engine.maneuver_name(winner_key),
                    offense_name,
                    defense_name,
                )
            ],
            next=FollowOn(
                FollowOnStep.BEGIN_EFFECT_RESOLUTION,
                {"winner_key": winner_key},
            ),
        )

    # **The headline is not narration here**, and that is the one
    # subtlety in this function: the skill test embeds it in its own
    # reveal message rather than posting it above one, so it rides as
    # the step's argument. A line carried as narration would have
    # become a message of its own and the reveal would have said the
    # same thing twice.
    return StepResult(
        next=FollowOn(
            FollowOnStep.BEGIN_MANEUVER_SKILL_TEST,
            {
                "headline": skill_test_headline(
                    engine,
                    game,
                    match,
                    reveal,
                    outcome,
                    offense_name,
                    defense_name,
                )
            },
        ),
    )


def describe_challenger_walk_in(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    defender_id: str,
    distance: int,
) -> str:
    """
    The challenger's walk-in and what it cost, or "" when they were
    already on the ball's space.

    Like every other exhaustion message this tests the Exhausted
    threshold as it writes it, so it has to be built before `match` is
    saved -- see `RulesEngine.apply_exhaustion`.
    """
    if distance <= 0:
        return ""

    defender = engine.get_player_definition(defender_id)
    space_word = "space" if distance == 1 else "spaces"
    return (
        f"{defender.name} has moved {distance} {space_word}."
        f"\n{engine.describe_exhaustion_gain(game, match, defender_id, distance)}"
    )


def auto_resolve_challenger(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    challenger_id: str,
) -> StepResult:
    """
    Apply an already-decided challenger pick and move straight on to
    maneuver-action selection -- no human choice involved, either
    because the AI made the pick or because a defender already shares
    the ball's space, leaving nothing to choose (see
    `PlayerActionView.choose_action`).

    The walk-in is described **before the caller saves**: the walk-in's
    tokens can cross the Exhausted threshold, and that flag is set
    while the description is put together.
    """
    distance = match.choose_challenger(challenger_id)
    return StepResult(
        narration=[
            describe_challenger_walk_in(
                engine, game, match, challenger_id, distance,
            )
        ],
        board_changed=True,
        next=FollowOn(FollowOnStep.BEGIN_MANEUVER_ACTION_SELECTION),
    )


def announce_uncontested_maneuver(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
) -> StepResult:
    """
    Say that there is nobody to challenge, then go straight to the
    offense's pick. No matchup image: it draws two players against each
    other and there is only one.

    Two ways to get here and they read differently, so the message asks
    the state which one it was rather than taking a flag: anyone still
    eligible means the defense was offered the challenge and sent
    nobody, since a defense with somebody to send is the only defense
    that gets the choice. Since 2026-08-16 that is practically always
    the answer -- the other branch needs a side with nobody on the
    field.
    """
    handler = engine.get_player_definition(match.active_player_id)
    defense_setup = match.setup_for_side(match.defending_side())

    if match.eligible_challengers():
        reason = "have sent nobody in to challenge"
    else:
        reason = "have nobody left to challenge"

    return StepResult(
        narration=[
            f"**Unchallenged!** {format_team_side_label(defense_setup)} "
            f"{reason} "
            f"{engine.format_player_label(match, handler)}, "
            "so whichever maneuver the offense picks succeeds."
        ],
        next=FollowOn(FollowOnStep.BEGIN_MANEUVER_ACTION_SELECTION),
    )


def write_ai_maneuver_picks(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
) -> None:
    """
    Dinky answers before the prompt is built, which is what makes a
    solo game's prompt one hand and one row --
    `RulesEngine.maneuver_pick_sides` is read afterwards, so it already
    knows the AI has picked.

    A tutorial beat names the card Dinky plays, and it is written
    straight into the match here rather than through the strategy:
    `choose_maneuver_action` takes a side and nothing else, so it has
    no way to know which beat is running, and changing its signature
    for one caller would put the script inside the AI. Dinky's pick is
    made before the coach's exactly as it always is -- the rails decide
    what the coach may answer with, not the other way round.
    """
    if not game.is_solo_game:
        return

    ai_strategy = engine.get_ai_strategy(game)
    beat = tutorial_beat(game)

    if engine.possession_player_number(game, match) == 2:
        scripted = beat.dinky_maneuver_for("offense") if beat else None
        match.choose_offense_maneuver(
            scripted
            or ai_strategy.choose_maneuver_action(
                "offense",
                engine.maneuver_hand(game, match, "offense"),
            )
        )
    if (
        not match.maneuver_uncontested
        and engine.defending_player_number(game, match) == 2
    ):
        scripted = beat.dinky_maneuver_for("defense") if beat else None
        match.choose_defense_maneuver(
            scripted
            or ai_strategy.choose_maneuver_action(
                "defense",
                engine.maneuver_hand(game, match, "defense"),
            )
        )


def tutorial_beat(game: D12BallGame):
    """
    The beat now in progress, or None when no rail applies -- an
    ordinary game, or a tutorial whose script has run out or been
    skipped.

    A copy of `D12Ball.tutorial_beat`'s body rather than a call into
    it, because this side of the seam may not reach into `cogs/`. The
    cog's is still the one every *view* asks, which is what its own
    docstring is about.
    """
    if not game.in_tutorial:
        return None
    return tutorial.beat_for_step(game.tutorial_step)


def maneuver_prompt_wording(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    sides: list[str],
) -> tuple[list[str], str]:
    """
    Who is mentioned above the prompt, and what they are told to do.

    Both come off the same `sides` list the buttons are built from,
    which is the point: a coach named here and given no row to press
    would stall a game, and nothing else would catch it.
    """
    waiting_on = [
        format_player_with_team(
            game,
            engine.possession_player_number(game, match)
            if side == "offense"
            else engine.defending_player_number(game, match),
            engine.team_emojis,
            mention=True,
        )
        for side in sides
    ]

    # The buttons are on the message, so there is nothing to tell a
    # coach to open. What the wording has to do instead is say which
    # row is theirs, since a contested prompt carries both.
    #
    # A lone side is not always the offense: a solo game's prompt is
    # one row, and it is the *defense's* whenever Dinky has the ball.
    # So the colour is read off the side rather than written down -- it
    # is the row's own colour either way (offense red, defense green;
    # see ManeuverActionPromptView).
    instruction = (
        "choose a maneuver from the "
        f"{MANEUVER_ROW_COLOURS[sides[0]]} row -- only you can "
        "see what you picked."
        if len(sides) == 1
        else (
            "both sides pick privately from the same message: red "
            "for the offense, green for the defense. Only you can "
            "see what you picked."
        )
    )
    return waiting_on, instruction


def begin_maneuver_action_selection(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
) -> StepResult:
    """
    Kick off the simultaneous maneuver-action choice once a challenger
    has been chosen: the AI opponent picks immediately, and every human
    side is owed its own row of buttons on one public prompt.

    An uncontested maneuver comes through here too, and waits on the
    offense alone -- there is no defender to pick a defensive maneuver,
    and nothing secret about a pick with nobody to conceal it from, but
    the prompt is the same one so the coach reads the same cards they
    always do.

    **The prompt itself is the frontend's** and is named rather than
    returned: it carries the hand image, a link to the full-size
    version, the field strip under it, and (in a tutorial) a note held
    behind a Continue button. What is settled here is that the AI has
    picked, whether anybody is still owed a choice, who they are and
    what they are told.
    """
    write_ai_maneuver_picks(engine, game, match)

    if match.maneuver_selections_complete:
        return StepResult(next=FollowOn(FollowOnStep.RESOLVE_MANEUVER))

    sides = engine.maneuver_pick_sides(game, match)
    waiting_on, instruction = maneuver_prompt_wording(
        engine, game, match, sides,
    )
    return StepResult(
        next=FollowOn(
            FollowOnStep.SEND_MANEUVER_ACTION_PROMPT,
            {
                "sides": list(sides),
                "ask": f"{' and '.join(waiting_on)}, {instruction}",
            },
        ),
    )


# -- Answering the turn's own prompts ---------------------------------
#
# Phase 6 of docs/model-discord-split.md: a click answers a
# `PendingPrompt`, and what that answer *does* is a rule. These are the
# model halves of the three that open a turn -- who takes the ball,
# what they do with it, and who challenges -- lifted out of
# `cogs/d12ball_views/turn.py`, where each was mixed in with the edit
# that renders it. `d12ball.flow.driver.apply` is what runs one over a
# prompt it has checked; the views call the same function, so there is
# one answer to each question rather than one per frontend.


def select_ball_handler_step(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    player_id: str,
) -> StepResult:
    """
    The kickoff pick: whose hands the ball starts this play in.

    Raises `ValueError` where the pick is not a legal one, which is
    `MatchState.select_ball_handler`'s own refusal and is left to
    propagate -- a frontend turns it into whatever it turns a refusal
    into (the cog, an ephemeral reply).

    The prompt it ends on is the turn's own, worded by
    `RulesEngine.build_turn_prompt` -- the fuller line a coach reads in
    the channel rather than `pending_prompt`'s bare "Choose an action:",
    which is what a restart falls back to when the message is gone.
    """
    match.select_ball_handler(player_id)
    return StepResult(
        next=PendingPrompt(
            PromptKind.PLAYER_ACTION,
            engine.build_turn_prompt(game, match),
        ),
    )
