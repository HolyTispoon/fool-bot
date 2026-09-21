"""
What a match is waiting on, answered with no Discord in the room.

`pending_prompt(engine, game, match)` is the single reading of "what is
this match waiting on?" -- the branch chain that used to be
`D12Ball.pending_turn_view`, moved whole. It returns a `PendingPrompt`:
a `PromptKind` naming the question, the line to put above it, and the
handful of parameters the question carries. Turning one into a
`discord.ui.View` is the cog's job and the cog's alone
(`D12Ball.view_for_prompt`), which is what lets a second frontend ask
the same question without reimplementing the chain.

**A second copy of this chain is the failure mode.** It is how a resume
comes to offer a different prompt from the one a restart restores, and
with two frontends it is how a web app and the bot come to disagree
about whose turn it is. See "Recovering a stuck game" in
docs/design/recovery.md.

Nothing here mutates: the whole chain is a read, and the three builders
folded into it (the run back's, the loose ball's, the effect choice's)
were already pure decisions over match state that happened to end in a
`View` constructor.

**One kind per view class.** A prompt built with different arguments
for different situations is one kind carrying the difference in its
parameters, not several -- `SPEED_DELTA_CHOICE` is Setup Pass's, the
dribbles' and Steal/Intercept's, told apart by `maneuver_key`, and
`LOW_PASS_CHOICE` is the plain one and the free one, told apart by
`free`. That is the rule the cog's mapping table is a table under.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Optional

from d12ball.components import (
    MatchState,
    PlayerRole,
    TeamSide,
)
from d12ball.formatting import (
    contest_noun,
    format_player_with_team,
    space_label,
)
from d12ball.game import D12BallGame
from d12ball import tutorial

if TYPE_CHECKING:  # pragma: no cover - typing only
    from d12ball.engine import RulesEngine


class PromptKind(Enum):
    """
    Every distinct prompt the chain can come back with.

    The members are grouped the way the chain reads them, which is not
    the order they matter in -- the ordering decisions live in
    `pending_prompt` itself, in the comments on the branches.
    """

    # The two that outrank everything, because nothing is played
    # while either is up: a tutorial note the coach has not pressed
    # Continue on, and a game that is over. Both Phase 6's, and both
    # for the same reason -- each used to be a message the cog put up
    # on its own, so a restart could not say the match was waiting on
    # it, and a second frontend could not know it was.
    TUTORIAL_CONTINUE = "tutorial_continue"
    GAME_OVER = "game_over"

    # Windows and periods
    COACHING_HUB = "coaching_hub"
    COACHING_OFFER = "coaching_offer"
    HALFTIME_EXTRA_TOKEN = "halftime_extra_token"

    # Interrupts, which outrank the turn they interrupt
    MIND_PULL = "mind_pull"
    SMOOTH = "smooth"
    INJURY_TEST = "injury_test"
    OWN_GOAL_ROLL = "own_goal_roll"

    # The shootout
    SHOOTOUT_ORDER = "shootout_order"
    SHOOTOUT_PICK = "shootout_pick"
    SHOOTOUT_TEST = "shootout_test"

    # The turn
    PLAYER_ACTION = "player_action"
    BALL_HANDLER_SELECTION = "ball_handler_selection"
    RUN_BACK_SPACE = "run_back_space"
    RUN_BACK_PLAYER = "run_back_player"
    BALL_RECOVERY = "ball_recovery"
    LOOSE_BALL_PICK = "loose_ball_pick"
    LOOSE_BALL_SKILL_TEST = "loose_ball_skill_test"
    SCORE_ATTEMPT = "score_attempt"
    # The two halves of a scoring opportunity, closed in Phase 6 of
    # docs/model-discord-split.md -- until then each was a
    # `FollowOnStep` whose view carried what match state did not hold.
    SET_UP_ATTEMPT = "set_up_attempt"
    SHOOTER_CHOICE = "shooter_choice"
    MANEUVER_CHALLENGE = "maneuver_challenge"
    MANEUVER_ACTION = "maneuver_action"
    SKILL_TEST = "skill_test"

    # The effect a settled maneuver owes
    LOW_PASS_CHOICE = "low_pass_choice"
    HIGH_PASS_CHOICE = "high_pass_choice"
    SETUP_PASS_CHOICE = "setup_pass_choice"
    SPEED_DELTA_CHOICE = "speed_delta_choice"
    DRIBBLE_ADVANCE_CHOICE = "dribble_advance_choice"
    DRIBBLE_BURST_CHOICE = "dribble_burst_choice"
    # Setup Pass's cost, once a deflection has beaten it: how much
    # further back the coach who won drives the ball. A kind since
    # Phase 6; until then the view had no kind at all, so a restart
    # in that window fell through to the turn prompt.
    SETUP_PASS_PUSH_BACK = "setup_pass_push_back"


@dataclass(frozen=True)
class PendingPrompt:
    """
    The question, the line asking it, and what the question is about.

    Only the parameters the branches actually carry are here. Anything
    else a frontend needs it can ask the engine for, with the match it
    already holds -- a prompt is what to ask, not a rendering brief.
    """

    kind: PromptKind
    ask: str
    #: RUN_BACK_PLAYER: which of a stack may be the one to run back.
    player_ids: list[str] = field(default_factory=list)
    #: MIND_PULL, INJURY_TEST, RUN_BACK_SPACE, SPEED_DELTA_CHOICE.
    player_id: Optional[str] = None
    #: HALFTIME_EXTRA_TOKEN, LOOSE_BALL_PICK: the board side asked.
    side: Optional[TeamSide] = None
    #: LOW_PASS_CHOICE and SPEED_DELTA_CHOICE: the card resolving.
    maneuver_key: Optional[str] = None
    #: LOOSE_BALL_PICK and SPEED_DELTA_CHOICE: "offense" or "defense".
    skill_type: Optional[str] = None
    #: LOW_PASS_CHOICE: a pass that costs the passer nothing.
    free: bool = False
    #: SET_UP_ATTEMPT: the clock cost of the maneuver that offered it,
    #: which the shot adds its own extra minute to rather than
    #: replacing. Not derivable from the position by the time the offer
    #: is put, which is why it is on the match -- see
    #: `MatchState.pending_scoring_opportunity`.
    distance_moved: int = 1
    #: SET_UP_ATTEMPT: an overshoot is a shot or a contest, both at the
    #: same disadvantage, so declining lands in the long-pass contest
    #: rather than settling the ball (2026-08-10).
    contest_on_decline: bool = False


def run_back_prompt(
    engine: "RulesEngine",
    game: D12BallGame,
    match: MatchState,
) -> Optional[PendingPrompt]:
    """
    The run-back prompt for whichever player still needs a real choice.

    Any forced placements are always applied immediately in
    `continue_run_back`, before a message is ever posted, so anything
    still outstanding by the time this is called is an actual choice.

    Which of the two prompts it is is read back off the position,
    exactly as the cascade reads it: a stack with more than one player
    to spare comes back as the question of who runs, and everything
    else as the question of where.

    **A pick already made narrows the first question into the
    second.** `MatchState.run_back_pick` is the coach's answer to
    "who", recorded by `run_back_player_step`, and while it names one
    of the players the position still asks about the question is
    "where" for that player -- which is what the click that answers
    it is checked against. It used to live on the Discord message and
    nowhere else, so a restart asked "who" again and the driver
    refused "where" as a question the match had moved on from; see
    the field.
    """
    step = engine.next_run_back_step(game, match)
    if step is None:
        return None
    _, candidates = step
    picked = match.run_back_pick
    if len(candidates) == 1 or picked in candidates:
        return PendingPrompt(
            PromptKind.RUN_BACK_SPACE,
            "Choose where the next player runs back to:",
            player_id=picked if picked in candidates else candidates[0],
        )
    return PendingPrompt(
        PromptKind.RUN_BACK_PLAYER,
        "Choose which of your doubled-up players runs back:",
        player_ids=candidates,
    )


def loose_ball_pick_prompt(
    engine: "RulesEngine",
    match: MatchState,
) -> Optional[PendingPrompt]:
    """
    The loose-ball pick for the one side currently on the clock --
    purely from match state, so a bot restart mid-pick reconstructs
    correctly, same as `run_back_prompt`.

    `skill_type` is which side owes the pick and `side` is the board
    side that is, which is what names the candidates. They are two
    answers to one question and both are carried because the two views
    built from this need one each.
    """
    skill_type = engine.loose_ball_side_on_the_clock(match)
    if skill_type is None:
        return None
    return PendingPrompt(
        PromptKind.LOOSE_BALL_PICK,
        f"Choose who goes after the {contest_noun(match)}:",
        side=engine.loose_ball_prompt_side(match),
        skill_type=skill_type,
    )


def scoring_opportunity_prompt(
    engine: "RulesEngine",
    game: D12BallGame,
    match: MatchState,
) -> Optional[PendingPrompt]:
    """
    The scoring opportunity a coach has been asked about and has not
    answered: the attempt-or-decline offer, or the pick of who takes
    the shot.

    **Both were `FollowOnStep`s until Phase 6**, and for one reason:
    the view carried arguments match state did not hold, so a prompt
    carrying them would be a shape this chain could never produce --
    which is the second reading principle 3 is against. What closed
    them is `MatchState.pending_scoring_opportunity`, and what it
    holds is the *question*: the attempt's two numbers, which nothing
    in the position remembers, and for the shooter's pick nothing at
    all beyond the fact that it is being asked. The candidates are read
    back off the board here, where a restart reads everything else.

    The wording is the bare question. The live offer opens with the
    lines of the pass that set it up (see
    `d12ball.flow.arrivals.offer_scoring_attempt_choice`), which a
    restart has not got and does not invent -- the same difference the
    run back's prompt has carried since Phase 4.
    """
    outstanding = match.pending_scoring_opportunity or {}
    kind = outstanding.get("kind")

    if kind == "attempt":
        shooter = engine.get_player_definition(outstanding["shooter_id"])
        return PendingPrompt(
            PromptKind.SET_UP_ATTEMPT,
            f"{engine.format_player_label(match, shooter)} can "
            "attempt the scoring opportunity, or let it go:",
            player_id=shooter.player_id,
            distance_moved=outstanding.get("distance_moved", 1),
            contest_on_decline=outstanding.get(
                "contest_on_decline", False,
            ),
        )

    if kind == "shooter":
        candidates = engine.scoring_opportunity_candidates(
            match, match.ball.possession,
        )
        if not candidates:
            # The position no longer offers anybody the shot, which is
            # not a state the game can reach between the offer and the
            # answer -- nothing moves while a coach is being asked. A
            # save that says otherwise has been edited or has come
            # through a migration, and falling through to the turn
            # prompt is what every other unreadable corner of this
            # chain does.
            return None
        return PendingPrompt(
            PromptKind.SHOOTER_CHOICE,
            f"{shooter_mention(engine, game, match)}, choose who "
            "takes the shot:",
            player_ids=candidates,
        )

    return None


def shooter_mention(
    engine: "RulesEngine",
    game: D12BallGame,
    match: MatchState,
) -> str:
    """
    The coach who is being asked to send somebody after a scoring
    opportunity, as a mention.

    Shared by the live offer and the restored one so the two cannot
    word the same question differently -- which is the whole of
    principle 5 in one sentence.
    """
    return format_player_with_team(
        game,
        engine.possession_player_number(game, match),
        engine.team_emojis,
        mention=True,
    )


#: Which row a lone side is told to press, by name. The buttons carry
#: the colour themselves (see `ManeuverActionPromptView`); this is the
#: word for it in the line above them.
MANEUVER_ROW_COLOURS = {"offense": "red", "defense": "green"}


def maneuver_prompt_wording(
    engine: "RulesEngine",
    game: D12BallGame,
    match: MatchState,
    sides: list[str],
) -> tuple[list[str], str]:
    """
    Who is mentioned above the maneuver prompt, and what they are told
    to do.

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


def maneuver_action_ask(
    engine: "RulesEngine",
    game: D12BallGame,
    match: MatchState,
) -> str:
    """
    The whole of what the maneuver prompt says: who is being asked,
    which row is theirs, and who holds their gambits.

    **One wording for the live prompt and the restored one.** The
    tutorial holds this prompt behind a note, and what goes up after
    the click is whatever `pending_prompt` says the match is waiting
    on -- so the restore's ask has to be the live one, or the coach
    would read a different question after the note from the one it
    was put in front of. See `d12ball.flow.gates`.

    Who holds their gambits goes under the instruction and above the
    cards. It is public knowledge either coach could work out from the
    scoreboard and the board (see `RulesEngine.may_play_gambits`), and
    `""` in the games and positions where the question does not arise
    -- so this adds a paragraph to an advanced prompt and nothing at
    all to a basic one.
    """
    sides = list(engine.maneuver_pick_sides(game, match))
    waiting_on, instruction = maneuver_prompt_wording(
        engine, game, match, sides,
    )
    ask = f"{' and '.join(waiting_on)}, {instruction}"
    gambit_access = engine.describe_gambit_access(game, match)
    if gambit_access:
        ask = f"{ask}\n\n{gambit_access}"
    return ask


def speed_choice_ask(
    engine: "RulesEngine",
    game: D12BallGame,
    match: MatchState,
    player_id: str,
    skill_type: str,
) -> str:
    """
    The speed choice, worded for the coach whose player made the move:
    up to that player's skill, either way.

    One wording for the live prompt and the restored one, for
    `maneuver_action_ask`'s reason: the tutorial holds this one behind
    a note too.
    """
    skill = engine.player_catalog.effective_profile(
        engine.get_player_definition(player_id),
    )
    skill_value = skill.offense if skill_type == "offense" else skill.defense
    controller_id = engine.controlling_user_id(game, match, player_id)
    mention = f"<@{controller_id}>" if controller_id else "Someone"
    return f"{mention}, manipulate the ball's speed (up to {skill_value}):"


#: Every effect choice is put up under the same line; what differs is
#: which choice is under it.
EFFECT_ASK = "Resolve the maneuver:"

#: What the score-attempt prompt says the first time it is put up.
#: The one thing the composition image does not show is how the two
#: rolls are read against each other, so it rides on the prompt --
#: which becomes the dice image the moment it is answered, taking the
#: explanation with it once it is no longer needed. A restart asks the
#: bare question instead (see `pending_prompt`).
SCORE_ATTEMPT_ASK = (
    "Either player can roll. Both sides roll one d12; the attacker "
    "scores on a total equal to or higher than the defence."
)


def effect_choice_prompt(
    engine: "RulesEngine",
    game: D12BallGame,
    match: MatchState,
) -> Optional[PendingPrompt]:
    """
    Whichever initial effect choice is pending for a decisively-won
    maneuver, purely from match state -- used both to restore it on a
    bot restart and (implicitly, by the same logic) to post it the
    first time. Returns None for a maneuver that needs no choice
    (Deflect, Pressure) or an unrecognized winner -- those resolve
    synchronously and should never actually leave this state persisted
    except in a narrow crash window, which falls back to
    `PromptKind.PLAYER_ACTION`.

    A Playmaker's Dribble Advance has two possible pending prompts
    (distance, then speed) with nothing in match state to tell them
    apart, so a restart in that narrow window guesses the first one --
    the same class of crash-window gap as the unrecognized-winner case
    above. A won Low Pass or High Pass that has moved on to its
    scoring-opportunity attempt/decline choice
    (`SetUpAttemptChoiceView`) has the same gap, as does a Low Pass
    waiting on which of several teammates on the destination space
    receives it (`LowPassReceiverView`): this always reconstructs the
    first-stage distance choice instead. Nothing has been applied by
    then, so the coach re-picks.
    """
    # **An effect continuation is read first**, because it says the
    # effect is already past the prompt its winner would restore.
    # Setup Pass's speed choice has been answered by the time one
    # is set, and a beaten Skilled Pass's Low Pass belongs to the
    # *defense* -- reading the winner there would put the steal's
    # speed choice back up and let a coach answer it twice. See
    # `continue_effect` for why the field outlives its dispatch.
    continuation = match.pending_effect_continuation or {}
    if continuation.get("kind") == "setup_pass_shot":
        return PendingPrompt(
            PromptKind.SETUP_PASS_CHOICE, EFFECT_ASK,
        )
    if continuation.get("kind") == "free_low_pass":
        return PendingPrompt(
            PromptKind.LOW_PASS_CHOICE,
            EFFECT_ASK,
            maneuver_key="low_pass",
            free=True,
        )

    winner_key = engine.settled_maneuver_winner(match)
    if winner_key is None:
        # Still owed a skill test, so no effect is pending yet.
        return None
    # A tie a skill test settled resolves as the basic card, so the
    # prompt restored has to be that card's -- see
    # `RulesEngine.resolving_maneuver`.
    winner_key = engine.resolving_maneuver(match, winner_key)
    if winner_key in ("low_pass", "skilled_pass"):
        return PendingPrompt(
            PromptKind.LOW_PASS_CHOICE, EFFECT_ASK, maneuver_key=winner_key,
        )
    if winner_key == "high_pass":
        return PendingPrompt(PromptKind.HIGH_PASS_CHOICE, EFFECT_ASK)
    if winner_key == "setup_pass":
        return _speed_delta(
            engine, game, match, match.active_player_id, "offense", winner_key,
        )
    if winner_key in ("dribble_advance", "dribble_burst"):
        handler = engine.get_player_definition(match.active_player_id)
        # **A Playmaker's advance has two prompts, and the carrier
        # tells them apart.** `select_ball_handler` clears
        # `ball_carrier_id` at the top of every turn and
        # `dribble_advance_step` is what sets it again, so a handler
        # recorded as carrying has already run and is owed the speed
        # choice; one who is not has not yet been asked how far. This
        # used to be the crash-window guess the docstring above
        # describes, and Phase 6 needed it exact: every click is
        # checked against this reading now, and a speed choice read
        # as a distance choice is a refused click.
        if (
            winner_key == "dribble_advance"
            and handler.role == PlayerRole.PLAYMAKER
            and match.ball_carrier_id != match.active_player_id
        ):
            return PendingPrompt(
                PromptKind.DRIBBLE_ADVANCE_CHOICE, EFFECT_ASK,
            )
        # A Dribble Burst asks a distance of everybody, not only a
        # Playmaker, and asks nothing else: the ball is left at 12
        # rather than offered to the handler (the author, 2026-09-20).
        # So a handler already on the last space of the field has
        # nothing to be asked at all, and the burst resolves like a
        # Deflect -- a crash window there falls back to the turn
        # prompt, the same as every other choiceless effect.
        if winner_key == "dribble_burst":
            if engine.dribble_burst_distances(match):
                return PendingPrompt(
                    PromptKind.DRIBBLE_BURST_CHOICE, EFFECT_ASK,
                )
            return None
        return _speed_delta(
            engine, game, match, match.active_player_id, "offense", winner_key,
        )
    if winner_key in ("steal", "intercept"):
        return _speed_delta(
            engine, game, match, match.challenger_id, "defense", winner_key,
        )
    if (
        winner_key in ("deflect", "clear")
        and engine.gambit_cost(match, winner_key) == "setup_pass"
        and not match.pending_loose_ball
        and match.pending_scoring_opportunity is None
    ):
        # **Setup Pass's cost**, still owed: the deflection has been
        # played and the ball is not yet loose, so the coach who beat
        # it is being asked how much further back it goes. Once the
        # loose ball begins the `pending_loose_ball` branch above
        # answers instead, and an overshoot into a shot is the
        # scoring opportunity's.
        return PendingPrompt(PromptKind.SETUP_PASS_PUSH_BACK, EFFECT_ASK)
    return None


def _speed_delta(
    engine: "RulesEngine",
    game: D12BallGame,
    match: MatchState,
    player_id: Optional[str],
    skill_type: str,
    maneuver_key: str,
) -> PendingPrompt:
    return PendingPrompt(
        PromptKind.SPEED_DELTA_CHOICE,
        speed_choice_ask(engine, game, match, player_id, skill_type)
        if player_id is not None
        else EFFECT_ASK,
        player_id=player_id,
        skill_type=skill_type,
        maneuver_key=maneuver_key,
    )


def pending_prompt(
    engine: "RulesEngine",
    game: D12BallGame,
    match: MatchState,
) -> PendingPrompt:
    """
    The prompt a saved match still owes: the question to put in front
    of whoever it is waiting on, and a line asking for it.

    **This is the only reading of "what is this match waiting on?", and
    the cog has two callers of it that must not drift apart.** Startup
    re-attaches the view to the message the prompt was already posted
    on (`turn_message_id`); `/d12ball resume` posts a fresh message
    carrying the same one, for the games where that message is gone,
    was never recorded, or was left with nothing live on it. A second
    copy of this branch chain is how a resume ends up offering a
    different prompt from the one a restart restores.

    Ordering matters more than it looks:

    - Setup and halftime come first because both leave
      `active_player_id` None, and the "no ball handler yet" branch
      would otherwise misread either as the kickoff.
    - `challenger_id` (or `maneuver_uncontested`) is what says a
      maneuver is under way, not `pending_action`, which
      `choose_challenger` clears the moment a challenger is picked.
    - An owed injury test and an owed own-goal roll come next, ahead of
      everything else, because both are interruptions of a turn whose
      own state is still set underneath them and would otherwise answer
      first.

    The three `PLAYER_ACTION` fallbacks are states whose next step is
    the bot's, not a coach's -- a run back with only forced placements
    left, an effect with no choice in it. There is no button to restore
    for those, so startup falls back to the turn prompt;
    `resume_pending_prompt` re-drives the pipeline instead, which is
    the difference between the two callers and the reason this returns
    a prompt rather than doing the posting itself.
    """
    if getattr(game, "tutorial_gate", None):
        # Ahead of everything: a note held behind Continue is a
        # click the game is waiting on before whatever the note
        # explains goes up, and nothing about the position says so
        # -- the position underneath is exactly what it was before
        # the note. See `d12ball.flow.gates`.
        return PendingPrompt(
            PromptKind.TUTORIAL_CONTINUE, tutorial.gate_text(game),
        )

    if getattr(game, "is_finished", False):
        # Nothing is asked of a finished game; what it waits on is
        # the rematch, which is the frontend's to offer. Ahead of the
        # branches below because the match under a finished game is
        # whatever full time or the shootout left there, and every
        # one of them would misread it.
        return PendingPrompt(PromptKind.GAME_OVER, "")

    if match.pending_setup_stage is not None:
        # Before kickoff, so active_player_id is None and the "no
        # ball handler yet" branch below would otherwise misread
        # this as the kickoff prompt -- the same reason halftime is
        # checked ahead of it.
        return PendingPrompt(
            PromptKind.COACHING_HUB, "Coaching Choice, before kickoff:",
        )

    if match.pending_full_time_stage is not None:
        # Between the whistle and the shootout, so the turn is
        # already reset and every branch below would misread it.
        # Always the hub: the window is given rather than declared,
        # so there is no offer to come back to.
        return PendingPrompt(
            PromptKind.COACHING_HUB, "Coaching Choice, before the shootout:",
        )

    if match.pending_halftime_stage is not None:
        # Halftime resets active_player_id before its own stages
        # run, so it has to be checked ahead of the "no ball
        # handler yet" branch below, which would otherwise misread
        # halftime as kickoff.
        stage = engine.halftime_stage(match)
        if stage in ("extra_token_home", "extra_token_visiting"):
            side = (
                TeamSide.HOME
                if stage == "extra_token_home"
                else TeamSide.VISITING
            )
            return PendingPrompt(
                PromptKind.HALFTIME_EXTRA_TOKEN,
                "Halftime: choose a player to lose an extra "
                "exhaustion token.",
                side=side,
            )
        # coaching_home / coaching_visiting. Always the hub:
        # halftime never asks whether to declare, so there is no
        # offer to come back to, unlike an ordinary turnover's
        # window below. A part-made pick inside the flow is not
        # persisted and restarts here, the same simplification a
        # run-back choice makes.
        return PendingPrompt(
            PromptKind.COACHING_HUB, "Halftime Coaching Choice:",
        )

    if match.pending_smooth:
        # Ahead of the pull for the reason `check_for_ball_arrival`
        # asks it first: both are owed on one movement, and a Smooth
        # that is taken stops the ball short of where the pull would
        # have reached for it. A restart has to come back to the same
        # offer the flow was on, so the two orderings are one ordering
        # written twice -- which is exactly the second copy this file
        # exists to prevent, and is why the reason is written down
        # here rather than only in the cog.
        player = engine.get_player_definition(match.pending_smooth[0])
        return PendingPrompt(
            PromptKind.SMOOTH,
            f"{engine.format_player_label(match, player)} can still take "
            "the ball over:",
            player_id=player.player_id,
        )

    if match.pending_mind_pull:
        # Ahead of the injury tests and of everything a maneuver
        # leaves set, for a stronger version of their reason: a
        # pull interrupts an arrival that has *not happened yet*,
        # so the maneuver's own state is still exactly as it was
        # and every branch below would resolve the arrival this is
        # holding back. It is also the one interrupt that can
        # change who has the ball, so answering it first is what
        # keeps the rest of the chain reading a settled position.
        player = engine.get_player_definition(match.pending_mind_pull[0])
        return PendingPrompt(
            PromptKind.MIND_PULL,
            f"{engine.format_player_label(match, player)} can still reach "
            "for the ball:",
            player_id=player.player_id,
        )

    if match.pending_injury_tests:
        # Ahead of everything a contest leaves set, because that is
        # all still set: a maneuver's skill test comes back here
        # with its challenger and both picks in place, and a loose
        # ball with no active player at all, which the kickoff
        # branch below would misread.
        player = engine.get_player_definition(match.pending_injury_tests[0])
        return PendingPrompt(
            PromptKind.INJURY_TEST,
            f"{engine.format_player_label(match, player)} still "
            "owes an injury test:",
            player_id=player.player_id,
        )

    if match.pending_own_goal:
        # Same reason: the Pressure that risked it is still the
        # live maneuver, so the effect branch would otherwise offer
        # to resolve it a second time.
        return PendingPrompt(
            PromptKind.OWN_GOAL_ROLL,
            "Either player can roll for the own goal.",
        )

    scoring_opportunity = scoring_opportunity_prompt(engine, game, match)
    if scoring_opportunity is not None:
        # After the interrupts and ahead of everything a maneuver
        # leaves set, which is the same reason the own-goal roll is:
        # the pass that opened the scoring opportunity is still the
        # live maneuver, so the effect branch below would offer to
        # resolve it a second time. Behind the interrupts because a
        # scoring opportunity is an arrival like any other and both
        # gates run in front of it -- `offer_scoring_attempt_choice`
        # calls `check_for_ball_arrival` before it asks anybody, so a
        # match in this state has already drained them.
        return scoring_opportunity

    if match.pending_shootout:
        # The three shootout states, read off the same three
        # questions `advance_shootout` asks and in the same order.
        # It comes after the injury queue because a shootout skill
        # test owes its checks before the next one is set up, and
        # ahead of everything below because the match underneath a
        # shootout is still whatever full time left there.
        if not match.shootout_orders_complete:
            return PendingPrompt(
                PromptKind.SHOOTOUT_ORDER,
                "Extreme shootout — set your shooting order:",
            )
        if not match.shootout_shooters_complete:
            return PendingPrompt(
                PromptKind.SHOOTOUT_PICK,
                "Extreme shootout — choose who shoots next:",
            )
        return PendingPrompt(
            PromptKind.SHOOTOUT_TEST,
            "Either player can roll the shootout skill test:",
        )

    if match.pending_time_out:
        # A time out resets the turn before either window opens,
        # so active_player_id is None and the kickoff branch below
        # would misread it -- the same reason setup and halftime
        # are checked ahead of that one. Always the hub: ceding is
        # what bought the window, so neither coach is ever asked
        # whether to take it. With no window open the cascade died
        # between the second one closing and the tail behind it,
        # which is resume's to re-drive rather than a click's.
        if match.pending_coaching_side is not None:
            return PendingPrompt(
                PromptKind.COACHING_HUB, "Coaching Choice, on the time out:",
            )
        return PendingPrompt(
            PromptKind.PLAYER_ACTION, "Settle the time out:",
        )

    if match.pending_coaching_side is not None:
        # A window mid-flight comes back as either the offer or the
        # menu. A part-made choice (picked who goes off, not yet
        # who comes on) is not persisted and restarts at the menu,
        # the same way a run-back choice does.
        #
        # **Ahead of the kickoff branch below**, because a new play's
        # window opens after the reset has cleared the turn: a window
        # offered after a missed shot has no ball handler yet, and
        # read the other way round it was the kickoff prompt -- which
        # a restart put up over an open window, and which Phase 6
        # then refused the window's own answers against.
        if match.pending_coaching_declared:
            return PendingPrompt(
                PromptKind.COACHING_HUB, "Coaching Choice:",
            )
        return PendingPrompt(
            PromptKind.COACHING_OFFER, "Coaching Choice — coach, or pass?",
        )

    if match.pending_run_back:
        step = engine.next_run_back_step(game, match)
        return run_back_prompt(engine, game, match) or PendingPrompt(
            PromptKind.PLAYER_ACTION,
            "Choose which of your doubled-up players runs back:"
            if step is not None and len(step[1]) > 1
            else "Choose where the next player runs back to:",
        )

    if match.pending_ball_recovery:
        # An out-of-bounds ball whose run back has already
        # finished, waiting on the winning side to send someone to
        # pick it up.
        return PendingPrompt(
            PromptKind.BALL_RECOVERY,
            "Send the nearest player either side of the ball to "
            "pick it up at "
            f"{space_label(match.ball.zone, match.ball.space_index)}:",
        )

    if match.pending_loose_ball:
        # Named off the position like every other message on this
        # path: only a ball lying where nobody stands is loose, and
        # a resume that calls a contest -- or a High Pass -- a
        # loose ball misreads it in front of the coach about to
        # act on it. See contest_noun.
        noun = contest_noun(match)
        if (
            match.loose_ball_offense_player is not None
            and match.loose_ball_defense_player is not None
        ):
            return PendingPrompt(
                PromptKind.LOOSE_BALL_SKILL_TEST,
                f"Either player can roll for the {noun}:",
            )
        return loose_ball_pick_prompt(engine, match) or PendingPrompt(
            PromptKind.PLAYER_ACTION,
            f"Choose who goes after the {noun}:",
        )

    if match.active_player_id is None:
        # No ball handler yet: the kickoff. **Behind every flag a
        # position can carry** -- a run back, a pickup, a loose ball
        # -- because each of those is a position with no handler in
        # it that is not a kickoff: a new play's reset clears the turn
        # before its run back, and a contest can be lying on the
        # board with nobody having taken the ball. Read ahead of them,
        # as it used to be, this branch answered "choose who takes the
        # ball" over a run back's own question -- which a restart put
        # up, and which Phase 6 refused the run back's answers against.
        return PendingPrompt(
            PromptKind.BALL_HANDLER_SELECTION, "Choose who takes the ball:",
        )

    if match.pending_action == "shoot":
        return PendingPrompt(
            PromptKind.SCORE_ATTEMPT,
            "Either player can roll for the score attempt.",
        )

    if match.pending_action == "maneuver" and match.challenger_id is None:
        return PendingPrompt(
            PromptKind.MANEUVER_CHALLENGE,
            "Choose who challenges the maneuver:",
        )

    if match.challenger_id is not None or match.maneuver_uncontested:
        # challenger_id is only ever set while a maneuver is in
        # progress and cleared by reset_maneuver(), so it alone
        # disambiguates this from any other phase -- pending_action
        # itself is cleared to None by choose_challenger() right
        # when the challenger is picked, so it can't be relied on
        # from here on. maneuver_uncontested says the same thing
        # for a maneuver that never had a challenger, and is
        # cleared by the same reset.
        if not match.maneuver_selections_complete:
            return PendingPrompt(
                PromptKind.MANEUVER_ACTION,
                maneuver_action_ask(engine, game, match),
            )
        if engine.settled_maneuver_winner(match) is None:
            # No winner yet means a skill test is owed -- a tie, or
            # a decisive maneuver an injured player still has to
            # roll for. Asking the ranking directly here would get
            # both wrong.
            return PendingPrompt(
                PromptKind.SKILL_TEST, "Either player can roll:",
            )
        return effect_choice_prompt(engine, game, match) or PendingPrompt(
            PromptKind.PLAYER_ACTION, EFFECT_ASK,
        )

    return PendingPrompt(PromptKind.PLAYER_ACTION, "Choose an action:")
