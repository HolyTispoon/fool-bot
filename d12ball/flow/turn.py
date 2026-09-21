"""
The front half of a turn, as flow steps: who challenges, what each side
picked, and which card won.

Lifted in Phase 4 of docs/design/model-discord-split.md out of
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

import random

from d12ball import tutorial
from d12ball.components import (
    DECISION_CARDS,
    DECISION_INJURY_FORFEIT,
    DECISION_SKILL_TEST,
    DECISION_UNCONTESTED,
    EVENT_MANEUVER,
    EVENT_SKILL_TEST,
    EVENT_TURN_ACTION,
    MatchState,
    SPECIES_CYBORG,
)
from d12ball.engine import RulesEngine
from d12ball.flow import gates
from d12ball.flow.result import FollowOn, FollowOnStep, StepResult
from d12ball.formatting import (
    challenger_prompt_ask,
    format_ai_name,
    format_player_with_team,
    format_team_side_label,
    get_damaged_emoji,
    get_injured_emoji,
)
from d12ball.game import D12BallGame, team_display_name
from d12ball.prompts import (
    SCORE_ATTEMPT_ASK,
    PendingPrompt,
    PromptKind,
    maneuver_action_ask,
)



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


def record_turn_action(
    match: MatchState,
    action: str,
    by_ai: bool = False,
) -> None:
    """
    Open a turn in the event log -- see `MatchEvent`.

    **Every event in a turn belongs to the `turn_action` that opened
    it**, and belongs to it by being logged after it, so this has to be
    called before anything the turn does.

    `action` is the button's own value -- `maneuver` or `shoot` -- so
    the share of each in the statistics is the share of the choice a
    coach actually made, not of what it led to. **A time out is not one
    of them**: it is a pause inside a possession rather than a turn,
    and it records its own event kind instead -- see `EVENT_TIME_OUT`
    and `begin_time_out`.

    `d12ball.flow.turn.record_turn_action` forwards to this, so none of its call
    sites moved -- the shape `team_emojis` took in Phase 1a.
    """
    match.record_event(
        EVENT_TURN_ACTION,
        side=match.ball.possession,
        player_id=match.active_player_id,
        action=action,
        by_ai=by_ai,
    )


def turn_action_refusal(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    action: str,
) -> Optional[str]:
    """
    Why this turn action cannot be taken, or None.

    **Every one of these is a stale click**: the buttons are only built
    for the actions the position allows, so reaching any branch here
    means a prompt from an earlier beat is still sitting in the channel
    and somebody pressed it. The wording is the model's because it says
    what the position *is* -- the ball moved into shooting range, the
    side has spent its time out, last possession has been declared.

    Whose account may press the button is not here; that stays in
    `SafeView` (docs/design/permissions.md), and so does "choose a
    player to handle the ball first", which is the frontend noticing
    there is no turn to take yet rather than a rule about this action.
    """
    allowed = tutorial.allowed_actions(tutorial_beat(game))
    if allowed is not None and action not in allowed:
        return (
            "The tutorial is on this step's action. Use the prompt "
            "at the bottom of the channel."
        )

    if action == "shoot" and not match.can_attempt_score():
        return "The ball is out of shooting range."

    if action == "time_out" and not match.may_call_time_out():
        # The same three reasons the button would not have been built.
        if match.can_attempt_score():
            return (
                "The ball is in shooting range now, so there is "
                "nothing to stop play for."
            )
        if match.scoreboard.last_possession:
            return (
                "Last possession has been declared, so there are "
                "no more time outs this period."
            )
        return "Your side has already taken its time out this half."

    return None


def begin_shot_step(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    action_label: str,
) -> StepResult:
    """
    Take the shot on, and say who is taking it.

    `action_label` is the button's own word for it, which the tutorial
    rewrites, so the sentence takes it rather than deciding it -- the
    one thing on this path that is the frontend's, and it is a label
    rather than a rule.

    It ends on the roll prompt. What the frontend puts up for that
    kind is the composition image and then the prompt -- two uploads
    and no decision -- and it is keyed on the kind, which is how the
    AI's shot and a coach's reach the same picture.
    """
    record_turn_action(match, "shoot")
    match.pending_action = "shoot"

    handler = engine.get_player_definition(match.active_player_id)
    offense_display = format_player_with_team(
        game,
        engine.possession_player_number(game, match),
        engine.team_emojis,
    )
    return StepResult(
        narration=[
            f"{offense_display} has chosen to {action_label} with "
            f"{engine.format_player_label(match, handler)}."
        ],
        next=PendingPrompt(PromptKind.SCORE_ATTEMPT, SCORE_ATTEMPT_ASK),
    )


def challenger_choice_prompt(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
) -> PendingPrompt:
    """
    The challenge put to the defending coach, worded for the first
    asking.

    **Deliberately not `pending_prompt`'s wording for the same state**,
    the way the injury test's is not: that one is a restart re-asking a
    question a coach has already seen, and this carries the mention and
    names the handler because the defense is being asked to choose
    before the challenge image exists -- this is the only place they
    can read who they would be up against. The *kind* is the same
    either way, which is what `view_for_prompt` reads.
    """
    handler = engine.get_player_definition(match.active_player_id)
    defender_mention = format_player_with_team(
        game,
        engine.defending_player_number(game, match),
        engine.team_emojis,
        mention=True,
    )
    handler_team = match.team_for_player(handler.player_id)
    return PendingPrompt(
        PromptKind.MANEUVER_CHALLENGE,
        f"{engine.format_player_label(match, handler)} will "
        f"maneuver for {team_display_name(handler_team)}.\n\n"
        f"{defender_mention}, {challenger_prompt_ask(match)}",
    )


def begin_maneuver_step(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
) -> StepResult:
    """
    Start a maneuver, which reaches the offense's pick by one of three
    routes: nobody to challenge at all, a challenger settled without
    asking, or the defending coach's own choice.

    - **Nobody left to challenge with at all** needs an empty field --
      a side with a meeple anywhere on the board has a candidate. The
      maneuver succeeds automatically and the offense still picks which
      one (docs/living-rules.md, "Maneuvers"). A defense that is
      offered a challenge and sends nobody lands in the same place,
      through `decline_challenge_step`.
    - **One defender already sharing the ball's exact space** leaves
      nothing to choose: they pay nothing to challenge, so it is
      neither theirs to decline nor a pick between players, and it goes
      ahead the same way it does when the AI is picking. Two of them is
      a pick, and the defending coach makes it (the author,
      2026-08-17): they are the whole of the choice, since nobody may
      be walked in past them. See `MatchState.challenge_candidates`.
    - **Otherwise the defending coach is asked**, and the prompt is
      `challenger_choice_prompt`.

    The middle route ends on `AUTO_RESOLVE_CHALLENGER` rather than
    running the pick itself, because what a frontend puts up for it is
    the **challenge image** -- the matchup, drawn -- and a picture is
    the frontend's (principle 8 in CLAUDE.md).
    """
    record_turn_action(match, "maneuver")

    if not match.eligible_challengers():
        return decline_challenge_step(engine, game, match)

    match.pending_action = "maneuver"
    on_ball_space = match.automatic_challengers()
    defender_number = engine.defending_player_number(game, match)
    if len(on_ball_space) == 1 or (
        game.is_solo_game and defender_number == 2
    ):
        challenger_id = (
            on_ball_space[0]
            if len(on_ball_space) == 1
            else engine.get_ai_strategy(game).choose_challenger(match)
        )
        return StepResult(
            next=FollowOn(
                FollowOnStep.AUTO_RESOLVE_CHALLENGER,
                {"challenger_id": challenger_id},
            ),
        )

    return StepResult(next=challenger_choice_prompt(engine, game, match))


def decline_challenge_step(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
) -> StepResult:
    """
    The defense sends nobody in, and the maneuver goes unchallenged.

    `announce_uncontested_maneuver` is what says so, and this is the
    mutation in front of it -- the half that was still inside
    `ManeuverChallengeView.decline`. `MatchState.begin_uncontested_maneuver`
    refuses a defense that has somebody it could still send, which is a
    stale click on a prompt a restart re-attached; it is left to
    propagate for `select_ball_handler_step`'s reason.
    """
    match.begin_uncontested_maneuver()
    return announce_uncontested_maneuver(engine, game, match)


def maneuver_pick_refusal(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    side: str,
    maneuver_key: str,
) -> Optional[str]:
    """
    Why this pick cannot be taken, or None -- **everything except who
    is allowed to make it**.

    Authorization is a fact about a Discord user and stays in
    `SafeView` (see docs/design/permissions.md), and it is answered
    *before* this: the other coach's row is sitting on the same
    message, so replying "that side has already chosen" to a click on
    it would say whether they had. The frontend keeps that ordering,
    which is why this does not take it.

    The other three are rules. A prompt can still be sitting in the
    channel from an earlier turn, so the tutorial's rail and the hand
    are both re-read here rather than trusted from whatever built the
    buttons -- exactly as the distances are re-read in a High Pass's
    own menu.
    """
    already_chosen = (
        match.offense_maneuver is not None
        if side == "offense"
        else match.defense_maneuver is not None
    )
    if already_chosen:
        return "You have already chosen your maneuver."

    allowed = tutorial.allowed_maneuvers(tutorial_beat(game), side)
    if allowed is not None and maneuver_key not in allowed:
        return (
            "This step of the tutorial wants "
            f"**{engine.maneuver_name(allowed[0])}**. Use the "
            "prompt at the bottom of the channel."
        )

    playable = {
        maneuver.key
        for maneuver in engine.maneuver_hand(game, match, side)
    }
    if maneuver_key not in playable:
        return (
            "That maneuver isn't in your hand for this turn. Use the "
            "prompt at the bottom of the channel."
        )

    return None


def maneuver_pick_step(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    *,
    side: str,
    maneuver_key: str,
) -> StepResult:
    """
    One coach's pick, written down.

    **"Someone has picked, you can't see what" is only worth saying
    while the other side is still choosing**, which is a rule about the
    position and not about batching: an uncontested maneuver has nobody
    to keep in the dark, and the reveal a moment later names the pick
    anyway. So the line is narration here, and an uncontested pick says
    nothing at all.

    It ends on the reveal once both sides have answered, and on nothing
    while one of them has not -- the position then reads as the other
    side's own `MANEUVER_ACTION`, which is what a frontend puts up
    next.

    `maneuver_pick_refusal` is what says a pick cannot be taken; this
    assumes it has been asked, the way every other step assumes its
    prompt was the one outstanding.
    """
    if side == "offense":
        match.choose_offense_maneuver(maneuver_key)
    else:
        match.choose_defense_maneuver(maneuver_key)

    narration = []
    if not match.maneuver_uncontested:
        side_number = (
            engine.possession_player_number(game, match)
            if side == "offense"
            else engine.defending_player_number(game, match)
        )
        narration.append(
            f"{format_player_with_team(game, side_number, engine.team_emojis)}"
            " has picked their maneuver."
        )

    if not match.maneuver_selections_complete:
        return StepResult(narration=narration)
    return StepResult(
        narration=narration,
        next=FollowOn(FollowOnStep.RESOLVE_MANEUVER),
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


def scripted_or_random(
    game: D12BallGame,
    kind: str,
    count: int,
) -> list[int]:
    """
    The dice the tutorial's script fixes for this roll, or real ones.

    `D12Ball.tutorial_dice` was this and it was two lines over
    `tutorial.scripted_dice` -- which reads the beat and nothing else,
    so it was already on the model's side of the line in everything but
    its address. It lives beside `tutorial_beat` for the same reason
    that does: it is the one thing every lifted roll site needs from
    the script, and a module that rolls dice should not each keep its
    own copy of "did the script want a number here".
    """
    scripted = tutorial.scripted_dice(tutorial_beat(game), kind, count)
    if scripted:
        return list(scripted)
    return [random.randint(1, 12) for _ in range(count)]


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

    return StepResult(
        next=FollowOn(FollowOnStep.SEND_MANEUVER_ACTION_PROMPT),
    )


def offer_maneuver_action(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    lead_in: str = "",
) -> StepResult:
    """
    Put the maneuver pick up -- or, in a tutorial, the note about the
    cards first, with the pick behind its Continue.

    The prompt is `pending_prompt`'s own reading of this position, and
    that is not a shortcut: the tutorial's note is a gate whose
    continuation is "show what the match is waiting on", so the live
    ask and the restored ask have to be one ask
    (`maneuver_action_ask`). Everything the frontend adds -- the hand
    image, the full-size link, the field strip -- is keyed on the kind.

    The note goes in front of the prompt rather than with the lesson
    two messages up: by the time the hands are in front of a coach
    they have watched a challenger walk in and are looking at three
    buttons, which is the moment the explanation is worth reading.
    """
    beat = tutorial_beat(game)
    if beat is not None:
        return gates.hold_behind_note(
            game, tutorial.NOTE_MANEUVER, None, lead_in=lead_in,
        )
    return StepResult(
        narration=[lead_in] if lead_in else [],
        next=PendingPrompt(
            PromptKind.MANEUVER_ACTION,
            maneuver_action_ask(engine, game, match),
        ),
    )


def begin_maneuver_skill_test(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    headline: str,
    lead_in: str = "",
) -> StepResult:
    """
    Charge both participants their token, say what is at stake, and
    put the roll behind a button -- every roll is a coach's.

    **The reveal is a message of its own**, separate from the roll
    prompt, so it survives every re-roll intact instead of being
    edited away: the lines here are this step's narration and the
    prompt is what it ends on, and the frontend keeps the two apart
    (`DRIVER_OWN_MESSAGE`). `headline` is `resolve_maneuver`'s reveal,
    handed over as an argument rather than as narration because it is
    embedded in this message rather than posted above it.

    `lead_in` is always "" for this step and is kept in front of the
    reveal rather than dropped, because every step is called with one.
    """
    exhaustion_text = (
        engine.apply_exhaustion(game, match, match.active_player_id, 1)
        + "\n"
        + engine.apply_exhaustion(game, match, match.challenger_id, 1)
    )
    offense_player = engine.get_player_definition(match.active_player_id)
    defense_player = engine.get_player_definition(match.challenger_id)
    offense_skill = engine.player_catalog.effective_profile(
        offense_player,
    ).offense
    defense_skill = engine.player_catalog.effective_profile(
        defense_player,
    ).defense

    prefix = f"{lead_in}\n\n" if lead_in else ""
    return StepResult(
        narration=[
            f"{prefix}{headline}"
            f"{engine.format_player_label(match, offense_player)}: "
            f"offense skill {offense_skill}\n"
            f"{engine.format_player_label(match, defense_player)}: "
            f"defense skill {defense_skill}\n\n"
            + exhaustion_text
        ],
        board_changed=True,
        next=PendingPrompt(PromptKind.SKILL_TEST, "Either player can roll:"),
    )


def record_maneuver(
    engine: RulesEngine,
    match: MatchState,
    winner_key: str,
) -> None:
    """
    Log the maneuver that has just been settled -- both picks, the
    winner, and how it was won.

    Called from `begin_effect_resolution`, which every maneuver in the
    game reaches **exactly once**: a decisive win and an unchallenged
    one go straight there from `resolve_maneuver`, and a tie goes
    there through the skill test and whatever injury tests it owed. A
    skill-test tie re-rolls without passing through, which is right --
    nothing has been settled yet, and the re-roll logs a `skill_test`
    event of its own.

    **How it was won is read off the log, not off the match.** The
    obvious test -- ask `settled_maneuver_winner` whether the cards
    decided it -- is wrong here by a hair: the injury tests run
    between the roll and this call, so a skill test whose loser went
    down injured would come back reading as a win on the cards. The
    log cannot move under it that way: a `skill_test` event in this
    turn means the dice settled it, full stop. Reading the log to
    *describe* a decision is not reading it to decide a rule.
    """
    decision = DECISION_UNCONTESTED
    if not match.maneuver_uncontested:
        rolled = any(
            event.kind == EVENT_SKILL_TEST
            for event in match.events_this_turn()
        )
        if rolled:
            decision = DECISION_SKILL_TEST
        elif engine.maneuver_catalog.resolve(
            match.offense_maneuver, match.defense_maneuver,
        ) == "tie":
            # A tie nothing was rolled for is the one an injured
            # participant forfeits outright.
            decision = DECISION_INJURY_FORFEIT
        else:
            decision = DECISION_CARDS

    match.record_event(
        EVENT_MANEUVER,
        side=match.ball.possession,
        player_id=match.active_player_id,
        offense_key=match.offense_maneuver,
        defense_key=match.defense_maneuver,
        winner_key=winner_key,
        decision=decision,
        challenger_id=match.challenger_id,
    )


# -- The turn prompt, and an AI side's whole turn ----------------------


def begin_turn(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    lead_in: str = "",
) -> StepResult:
    """
    The turn is over and the next one starts: stage a tutorial beat if
    one is due, and hold its lesson behind Continue; otherwise straight
    on to `start_turn`.

    **It moves nothing.** The board is set once, at kickoff, and every
    beat after that is played from wherever the previous turn left it
    -- see the module docstring in `d12ball/tutorial.py`. Called once
    a turn, which is what counts the beats; `tutorial_staged` is what
    keeps that honest, because the recovery commands
    (`/d12ball offensive_choice` and `resume force:true`) also start a
    turn without one having been played, and re-entering a beat must
    not silently skip the next one.

    Ahead of everything, including the AI's turn: a beat the coach is
    *defending* is still a beat, and its lesson has to be up before
    Dinky takes a turn on it -- which is why the gate's continuation
    is `START_TURN` and not this step again.
    """
    if not game.in_tutorial:
        return StepResult(
            narration=[lead_in] if lead_in else [],
            next=FollowOn(FollowOnStep.START_TURN),
        )

    if game.tutorial_staged:
        game.tutorial_step = (game.tutorial_step or 0) + 1
        game.tutorial_staged = False

    beat = tutorial.beat_for_step(game.tutorial_step)
    if beat is None:
        # Past the last beat: the script is over. The flag is cleared
        # before anything else, so the prompt this turn puts up is
        # built with no rails on it at all.
        game.tutorial_step = None
        game.tutorial_staged = False
        return gates.hold_behind_note(
            game,
            tutorial.NOTE_HANDOVER,
            FollowOn(FollowOnStep.START_TURN),
            lead_in=lead_in,
        )

    game.tutorial_staged = True
    return gates.hold_behind_note(
        game,
        tutorial.NOTE_LESSON,
        FollowOn(FollowOnStep.START_TURN),
        lead_in=lead_in,
    )


def start_turn(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    lead_in: str = "",
) -> StepResult:
    """
    Hand the ball to whoever now has it: the carrier when the last
    resolution left it with somebody, everyone on the ball's space
    otherwise. A single candidate is selected without asking, so the
    rule costs a coach a click rather than adding one; an AI side
    plays its whole turn from here.

    Through the engine, which is where the single answer to "who may
    take this turn" lives even now that it adds nothing of its own:
    Slip in used to widen this list, and Smooth replaced it on
    2026-09-20 by settling the same question one step earlier, at the
    arrival gate.

    Raises `ValueError` where the side in possession has nobody on the
    ball's space, which is a position the flow should not be able to
    leave and the frontend reports rather than acts on.
    """
    narration = [lead_in] if lead_in else []

    eligible_handlers = engine.turn_handler_candidates(game, match)
    if not eligible_handlers:
        raise ValueError(
            "The team in possession has no player in the ball's space."
        )
    carrying = match.ball_carrier_id in eligible_handlers

    offense_number = engine.possession_player_number(game, match)
    if game.is_solo_game and offense_number == 2:
        result = ai_turn_step(engine, game, match)
        result.narration[:0] = narration
        return result

    if len(eligible_handlers) == 1:
        match.select_ball_handler(eligible_handlers[0])
        kind = PromptKind.PLAYER_ACTION
    else:
        kind = PromptKind.BALL_HANDLER_SELECTION

    return StepResult(
        narration=narration,
        next=PendingPrompt(
            kind, engine.build_turn_prompt(game, match, carrying=carrying),
        ),
    )


def ai_turn_step(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
) -> StepResult:
    """
    The AI opponent's turn with possession, whole: pick a ball
    handler, then shoot if the ball is already on the space closest to
    the opponent's goal, call a time out if one of theirs is injured
    on the field, otherwise maneuver.

    **The decisions are `d12ball/ai.py`'s**; what is here is the
    sequencing and the four things said, which is what stayed in the
    cog until Phase 6 -- and the four exits are the same four a human
    coach's turn takes, through the same steps.

    Each line is a message of its own (the frontend's
    `DRIVER_BLOCKS_PER_MESSAGE`), which is how the AI's turn always
    read: "Dinky has chosen to maneuver", then "Unchallenged!".
    """
    ai_name = format_ai_name(game.ai_opponent)
    ai_strategy = engine.get_ai_strategy(game)
    handler_id = ai_strategy.choose_ball_handler(match)
    match.select_ball_handler(handler_id)
    handler = engine.get_player_definition(handler_id)
    label = engine.format_player_label(match, handler)
    action = ai_strategy.choose_action(match)

    # **Ahead of the turn-action record**, because a time out is not a
    # turn action -- `begin_time_out` logs its own event instead, and
    # recording one here would open a turn for a pause and hang the
    # real turn's events off it. See `MatchState.record_event` and
    # EVENT_TIME_OUT.
    #
    # Dinky calls one to get an injured player off (the author,
    # 2026-09-16); `DinkyAI.choose_action` is the whole of when. The
    # window it opens runs through `run_ai_substitution_window` like
    # any other AI window, and the human coach gets theirs in reply
    # exactly as a human caller's opponent would.
    if action == "time_out":
        from d12ball.flow.windows import begin_time_out

        result = begin_time_out(engine, game, match)
        result.narration.insert(0, f"{ai_name} calls a time out.")
        return result

    # Recorded here rather than in the two branches below: the AI has
    # no prompt and no stale click to guard against, so the strategy's
    # answer *is* the turn it takes.
    record_turn_action(match, action, by_ai=True)

    if action == "shoot":
        match.pending_action = "shoot"
        return StepResult(
            narration=[
                f"{ai_name} has chosen to shoot to score with {label}."
            ],
            next=PendingPrompt(PromptKind.SCORE_ATTEMPT, SCORE_ATTEMPT_ASK),
        )

    # Unchallenged, so the AI's pick succeeds outright -- the same
    # branch a human offense takes, see `begin_maneuver_step`.
    if not match.eligible_challengers():
        result = decline_challenge_step(engine, game, match)
        result.narration.insert(
            0, f"{ai_name} has chosen to maneuver with {label}.",
        )
        return result

    match.pending_action = "maneuver"

    # *One* defender already sharing the ball's exact space leaves
    # nothing to choose -- see `begin_maneuver_step`, and note that
    # this is a count and not a flag there too: two of them on the
    # ball is the defending coach's pick (the author, 2026-08-17), and
    # taking `on_ball_space[0]` here picked for them off placement
    # order without asking. Nothing is announced: the challenge image
    # names the handler the AI picked, along with everything else
    # about the matchup.
    on_ball_space = match.automatic_challengers()
    if len(on_ball_space) == 1:
        return StepResult(
            next=FollowOn(
                FollowOnStep.AUTO_RESOLVE_CHALLENGER,
                {"challenger_id": on_ball_space[0]},
            ),
        )

    defender_mention = format_player_with_team(
        game,
        engine.defending_player_number(game, match),
        engine.team_emojis,
        mention=True,
    )
    return StepResult(
        next=PendingPrompt(
            PromptKind.MANEUVER_CHALLENGE,
            f"{ai_name} will maneuver with {label}.\n\n"
            f"{defender_mention}, {challenger_prompt_ask(match)}",
        ),
    )


# -- Answering the turn's own prompts ---------------------------------
#
# Phase 6 of docs/design/model-discord-split.md: a click answers a
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
