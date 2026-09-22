"""
The clock's own machinery, as flow steps: the period whistle, halftime,
the window before the shootout, and the shootout itself.

Lifted in Phase 5 of docs/design/model-discord-split.md out of
`cogs/d12ball/periods.py`, which keeps a wrapper per step -- the board
postings, the pin, the rematch buttons and the coaching image are the
frontend's and stayed there. See "The model and the Discord layer" in
CLAUDE.md, and [clock-and-records.md](../../docs/design/clock-and-records.md),
[coaching-choice.md](../../docs/design/coaching-choice.md) and
[shootout.md](../../docs/design/shootout.md) for the rules these steps
carry.

**The three stage machines are the shape of this file.** Setup,
halftime and full time are each a sequence of windows with the bot's
own step between them (`SETUP_STAGES`, `HALFTIME_STAGES`,
`FULL_TIME_STAGES` in d12ball/engine.py), and the shootout is a fourth
of the same kind. Each is `begin_ -> advance_ -> finish_`, and the
`advance_` is the one reading of which stage a saved game is on -- the
same claim `pending_prompt` makes about a turn, and for the same
reason: two of the four shootout steps are the bot's own, so a restart
between them has no button anywhere and `/d12ball resume` has to be
able to ask.

**`advance_shootout` is still the only reading of the shootout's
state.** It moved; it did not fork. `d12ball.prompts.pending_prompt`
answers the same three questions in the same order and a restart comes
back through it, which is the arrangement Phase 1 put there and this
phase leaves alone.

**What stays in the cog, and why.** The two ephemeral shootout menus
(the secret orders) are Discord's own trick -- neither coach may see
the other's, so there is no public message to put an order on -- and
`restore_shootout_menus` with them. The final board with the rematch
buttons, the pinned new-play board a half kicks off from, and the
tutorial's Continue gates are all "how this reaches a person", which is
the frontend's half of principle 2.
"""

from __future__ import annotations

from typing import Optional

from d12ball.components import (
    CoachingOccasion,
    MatchPeriod,
    MatchState,
    RuleRefusal,
    SECOND_HALF_START_MINUTE,
    TeamSide,
    Zone,
    kickoff_space_index,
)
from d12ball import tutorial
from d12ball.engine import (
    FULL_TIME_STAGES,
    HALFTIME_STAGES,
    RulesEngine,
    SETUP_STAGES,
)
from d12ball.flow import gates
from d12ball.flow.result import FollowOn, FollowOnStep, StepResult
from d12ball.formatting import (
    build_full_time_summary,
    build_goal_log,
    format_player,
    format_team_side_label,
)
from d12ball.game import D12BallGame
from d12ball.prompts import (
    PendingPrompt,
    PromptKind,
    shootout_order_prompt,
    shootout_pick_prompt,
)


# -- The whistle -----------------------------------------------------


def end_period(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    lead_in: str = "",
) -> StepResult:
    """
    The turnover that closes out last possession: transition to the
    second half, or end the game at full time -- which, on a level
    score, means opening the extreme shootout rather than finishing
    anything.

    **It is reached only by a turnover under a last possession already
    in force.** The maneuver that *declares* last possession never ends
    a period, even when it is itself a turnover; that is
    `finish_maneuver_resolution`'s branch and it is why both of this
    step's callers check the flag before naming it.

    **The whistle is its own message and so is everything after it.**
    This step carries straight on into halftime or into the full-time
    window rather than naming either as a follow-on, and hands back a
    *list* of narration blocks -- which `d12ball.flow.periods.end_period` posts one
    message apiece through `post_blocks_then_dispatch`. Batching is the
    frontend's (principle 8); what the model settles is what was said
    and in what order.
    """
    prefix = f"{lead_in}\n\n" if lead_in else ""

    # The turnover that ends a period is the one carry that must
    # not survive it: a Steal under last possession names
    # a carrier, and the second half kicks off from the coaches'
    # arrangement with nobody holding anything.
    match.clear_ball_carrier()

    if match.scoreboard.period == MatchPeriod.FIRST_HALF:
        first_half_ended_at = match.scoreboard.time
        match.scoreboard.period = MatchPeriod.SECOND_HALF
        # The second half starts at 16 however far past 15 the
        # first half ran, so the number on the clock means the same
        # thing in every game. It is set here rather than at the
        # kickoff for the reason everything else in this branch is:
        # halftime is played with the second half's board already
        # on the scoreboard.
        match.scoreboard.time = SECOND_HALF_START_MINUTE
        match.scoreboard.last_possession = False
        # A time out is once every half, so both sides get theirs
        # back. Their two substitutions for the half come back with
        # it; halftime's own two are counted separately and are not
        # touched here.
        match.time_outs_used.clear()
        match.half_substitutions_used.clear()
        match.close_coaching_window()
        kickoff_index = kickoff_space_index(
            len(match.board.spaces[Zone.MIDFIELD]),
            TeamSide.VISITING,
        )
        match.restart_ball_at(Zone.MIDFIELD, kickoff_index)
        match.ball.possession = TeamSide.VISITING
        match.ball.speed = 1
        match.reset_maneuver()

        result = begin_halftime(engine, game, match)
        result.narration.insert(
            0,
            f"{prefix}**End of the first half!** The ball turns over "
            f"at {first_half_ended_at:02d} under last possession -- "
            "the period ends. The second half starts at "
            f"{SECOND_HALF_START_MINUTE:02d}.",
        )
        result.board_changed = True
        return result

    match.reset_maneuver()

    whistle = (
        f"{prefix}**Full time!** The ball turns over at "
        f"{match.scoreboard.time:02d} under last possession -- the "
        "game ends.\n\n"
        f"{build_full_time_summary(game, match)}"
    )

    if match.scoreboard.home_score == match.scoreboard.visiting_score:
        # Level, so nothing is finished: the summary above says the
        # game goes to the shootout, and the shootout is what ends
        # it -- the game record stays in progress until then, so a
        # restart mid-shootout comes back to a live game. One
        # substitution a side comes first.
        result = begin_full_time_coaching(engine, game, match)
        result.narration.insert(0, whistle)
        result.board_changed = True
        return result

    game.finish_game()
    return StepResult(
        narration=[f"{whistle}\n\n{goal_log(engine, match)}"],
        next=FollowOn(FollowOnStep.ANNOUNCE_GAME_OVER),
    )


def goal_log(engine: RulesEngine, match: MatchState) -> str:
    """
    The scoresheet, with this engine's roster and emoji behind it.

    A three-argument call written once rather than at both of its
    sites, which is what `D12Ball.build_goal_log` was before the lift
    and why the cog keeps that method forwarding here. It is built by
    the callers of `announce_game_over` rather than inside it, because
    that function is handed a string and has no match.
    """
    return build_goal_log(
        match,
        engine.player_catalog,
        engine.team_emojis,
        engine.role_emojis,
    )


# -- Setup, before the kickoff ---------------------------------------


def begin_setup_coaching(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
) -> StepResult:
    """
    Offer both coaches a Coaching Choice before kickoff, home
    first -- see "Setup" in docs/living-rules.md. Both
    teams are dealt the standard 2-2-2 and, in basic mode, dealt
    identically; this is where a coach may change any of it rather
    than waiting for their first window.

    Substitutions here are unlimited and a player taken off goes
    back to the bench: nobody has played, so nothing is used up.
    A coach happy with the deal finishes without changing anything.
    """
    # A tutorial kicks off on the standard deal. The Coaching
    # Choice is the most involved menu in the game and the script
    # explains it at beat 6, on the window a real new play offers;
    # putting a coach through it before they have seen a turn is
    # asking them to rearrange a board they cannot read yet. It
    # costs them nothing -- both sides are dealt the same 2-2-2,
    # and the tutorial re-deals both of them every beat anyway.
    if game.tutorial:
        return StepResult(next=FollowOn(FollowOnStep.FINISH_SETUP_COACHING))

    match.pending_setup_stage = SETUP_STAGES[0]
    return advance_setup_stage(engine, game, match)


def advance_setup_stage(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
) -> StepResult:
    """Hand the next coach their pre-kickoff Coaching Choice, or
    kick off."""
    stage = match.pending_setup_stage
    if stage in ("coaching_home", "coaching_visiting"):
        side = (
            TeamSide.HOME
            if stage == "coaching_home"
            else TeamSide.VISITING
        )
        setup = match.setup_for_side(side)
        return StepResult(
            next=FollowOn(
                FollowOnStep.BEGIN_SUBSTITUTION_WINDOW,
                {
                    "side": side,
                    "occasion": CoachingOccasion.SETUP,
                    "heading": (
                        f"## Before kickoff\n"
                        f"{format_team_side_label(setup)} "
                        "set their line-up. Substitutions are unlimited "
                        "here and anyone taken off goes back to the bench "
                        "-- the game has not started, so nothing is used "
                        "up."
                    ),
                },
            ),
        )

    return StepResult(next=FollowOn(FollowOnStep.FINISH_SETUP_COACHING))


def finish_setup_coaching(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
) -> StepResult:
    """
    Both coaches are done, so the game can start -- and this is
    where the board first goes up. Nothing has been played yet, so
    a board posted before the windows would show a deal neither
    coach had finished with, and be redrawn twice over before
    anyone acted on it; the one worth looking at is the line-up the
    game actually kicks off from.

    A kickoff is a new play, so the line is the board's caption
    (`StepResult.new_play`); that the board is *pinned* is the
    frontend's (`post_new_play_board`, the one pinning site in the
    game). It used to attach the board to the persistent message
    instead, which is a message near the top of the channel -- and
    Discord leaves an edited message where it was, so the board a
    coach had just finished setting appeared *above* the windows that
    set it.

    **The tutorial's script arms here** rather than at creation, so
    everything up to the kickoff -- teams, the toss, home or visiting
    -- is played exactly as an ordinary game plays it. The welcome
    goes under the board it describes and is held behind Continue, and
    the first beat is staged by the turn prompt behind that click.
    """
    match.pending_setup_stage = None

    kicking_off = match.setup_for_side(match.ball.possession)
    caption = (
        "**The teams are dealt.** The game kicks off with "
        f"{format_team_side_label(kicking_off)} in possession."
        if game.tutorial
        else "**Both coaches are set.** The game kicks off with "
        f"{format_team_side_label(kicking_off)} in possession."
    )
    if game.tutorial:
        game.tutorial_step = tutorial.FIRST_STEP
        game.tutorial_staged = False
        # The welcome and beat 1's own lesson are two narration
        # messages with nothing for the coach to click between them,
        # so the first is held behind Continue -- with the turn prompt,
        # which stages the beat, as what the click runs.
        gated = gates.hold_behind_note(
            game,
            tutorial.NOTE_WELCOME,
            FollowOn(FollowOnStep.SEND_TURN_PROMPT),
        )
        return StepResult(
            narration=[caption],
            board_changed=True,
            new_play=True,
            next=gated.next,
        )
    return StepResult(
        narration=[caption],
        board_changed=True,
        new_play=True,
        next=FollowOn(FollowOnStep.SEND_TURN_PROMPT),
    )


# -- Halftime --------------------------------------------------------


def begin_halftime(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
) -> StepResult:
    """
    Kicks off halftime cleanup once `end_period` has already flipped
    the period, reset the clock, and moved the ball to the
    second-half kickoff space: automatic exhaustion recovery for
    every fielded player, then the rest of the sequence (each
    side's extra-token choice, substitution window, and free
    repositioning) driven by `match.pending_halftime_stage` --
    see `advance_halftime_stage`.
    """
    recovery_lines = []
    for side in (TeamSide.HOME, TeamSide.VISITING):
        for player_id in match.setup_for_side(side).field_players:
            player = engine.get_player_definition(player_id)
            # A Cyborg's own line, not their defensive skill --
            # "Drained counts as Exhausted everywhere the rules use
            # that word", the halftime re-test included.
            threshold = engine.exhaustion_threshold(game, player_id)
            removed = match.recover_exhaustion(player_id, 1, threshold)
            if removed:
                remaining = match.exhaustion.get(player_id, 0)
                recovery_lines.append(
                    f"{engine.format_player_label(match, player)} "
                    f"recovers 1 exhaustion token (now {remaining})."
                )

    body = (
        "\n".join(recovery_lines)
        if recovery_lines
        else "No fielded player had any exhaustion tokens to recover."
    )

    match.pending_halftime_stage = HALFTIME_STAGES[0]
    result = advance_halftime_stage(engine, game, match)
    result.narration.insert(
        0,
        f"# Halftime\nEvery fielded player recovers 1 exhaustion "
        f"token:\n{body}",
    )
    result.board_changed = True
    return result


def advance_halftime_stage(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
) -> StepResult:
    """Dispatch to whichever halftime stage comes next, or finish."""
    stage = engine.halftime_stage(match)
    if stage == "extra_token_home":
        return begin_halftime_extra_token(engine, game, match, TeamSide.HOME)
    if stage == "extra_token_visiting":
        return begin_halftime_extra_token(
            engine, game, match, TeamSide.VISITING,
        )
    if stage == "coaching_home":
        return begin_halftime_substitutions(
            engine, game, match, TeamSide.HOME,
        )
    if stage == "coaching_visiting":
        return begin_halftime_substitutions(
            engine, game, match, TeamSide.VISITING,
        )
    return StepResult(next=FollowOn(FollowOnStep.FINISH_HALFTIME))


def begin_halftime_extra_token(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    side: TeamSide,
) -> StepResult:
    """
    The coach's choice of one fielded player to lose an extra
    exhaustion token, on top of the automatic recovery every
    fielded player already got in `begin_halftime`.

    **A side with nobody eligible is passed over in silence**, the way
    the full-time window skips a side with an empty bench: a menu with
    no button on it is not a question.
    """
    setup = match.setup_for_side(side)
    eligible = [
        player_id
        for player_id in setup.field_players
        if player_id not in match.injured
    ]

    if not eligible:
        engine.next_halftime_stage(match)
        return advance_halftime_stage(engine, game, match)

    mention = format_player(
        game, engine.side_player_number(game, side), mention=True,
    )
    return StepResult(
        next=PendingPrompt(
            PromptKind.HALFTIME_EXTRA_TOKEN,
            f"{mention}, {format_team_side_label(setup)}: choose one "
            "fielded player to lose an extra exhaustion token.",
            side=side,
        ),
    )


def halftime_extra_token_step(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    *,
    player_id: str,
) -> StepResult:
    """
    The coach's pick of one fielded player to lose an extra exhaustion
    token, applied.

    The answer to `begin_halftime_extra_token`'s own prompt, for a
    coach and for the AI alike (`AIStrategy.choose`, through the
    service).

    **A player with no tokens to lose is not refused**, because picking
    them is a legal answer to the question asked: every fielded player
    who is not injured is on the menu, and what a coach gets for
    picking the fresh one is a sentence saying so.
    """
    player = engine.get_player_definition(player_id)
    threshold = engine.exhaustion_threshold(game, player_id)
    removed = match.recover_exhaustion(player_id, 1, threshold)
    engine.next_halftime_stage(match)

    remaining = match.exhaustion.get(player_id, 0)
    # What halftime does next comes back with the answer: the first
    # block is this pick's own line, the rest are the next stage's,
    # and the frontend keeps them apart (the answer replaces the
    # prompt; the stage is its own messages).
    result = advance_halftime_stage(engine, game, match)
    result.narration.insert(
        0,
        f"{engine.format_player_label(match, player)} loses "
        f"an extra exhaustion token (now {remaining})."
        if removed
        else f"{engine.format_player_label(match, player)} "
        "had no tokens to lose.",
    )
    result.board_changed = True
    return result


def begin_halftime_substitutions(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    side: TeamSide,
) -> StepResult:
    """
    Give `side` a full substitution window -- unlike a turnover's
    declare-then-respond pairing, halftime gives each side its own
    independent window, so `finish_substitution_window` routes back
    into the halftime sequence instead of chaining to the other
    side's response.

    Nobody is asked whether to declare, and nothing is charged for
    it: halftime substitutions just happen ("the coach can change
    their team's formation and the players' assignment as they
    please", End of Time), and they leave the side's once-a-half
    declaration unspent for the second half. A side with nothing
    it wants to change finishes the menu without doing anything,
    which is the same as passing used to be.
    """
    setup = match.setup_for_side(side)
    return StepResult(
        next=FollowOn(
            FollowOnStep.BEGIN_SUBSTITUTION_WINDOW,
            {
                "side": side,
                "occasion": CoachingOccasion.HALFTIME,
                "heading": (
                    f"## Halftime\n{format_team_side_label(setup)} set up "
                    "for the second half."
                ),
            },
        ),
    )


def finish_halftime(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
) -> StepResult:
    """
    The last step of halftime -- the visiting kickoff-space
    guarantee is already enforced before this is reached (see
    `RulesEngine.coaching_finish_refusal`), so this just clears the
    halftime flag and hands play to the second half.
    """
    match.pending_halftime_stage = None

    # A half begins the way any other new play does: with the board
    # everyone is about to play from, which `new_play` says and the
    # frontend posts and pins.
    return StepResult(
        narration=[
            "**Halftime is over.** The second half kicks off with "
            f"{format_team_side_label(match.visiting)} in possession."
        ],
        board_changed=True,
        new_play=True,
        next=FollowOn(FollowOnStep.SEND_TURN_PROMPT),
    )


def announce_game_over(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    lead_in: str = "",
) -> StepResult:
    """
    The last thing a game says: the result and the scoresheet, which
    arrive as `lead_in` from whichever ending named this step -- the
    whistle when full time settles the game, and the shootout when it
    does not. Both have already called `game.finish_game()`.

    It ends on `PromptKind.GAME_OVER`, which is not a question but is
    what the match is waiting on: the frontend puts the final board
    and the rematch buttons on the message that carries these lines,
    and a restart re-attaches those buttons. Nothing is asked and the
    ask is empty, so the lines are the whole of the message.
    """
    return StepResult(
        narration=[lead_in] if lead_in else [],
        next=PendingPrompt(PromptKind.GAME_OVER, ""),
    )


# -- The window before the shootout ----------------------------------


def begin_full_time_coaching(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
) -> StepResult:
    """
    The last Coaching Choice of a level game, one to each coach
    before the shootout opens -- see "Full time" in
    docs/living-rules.md. **One substitution and nothing else**: a
    shootout is played by who is on the field and by nothing about
    where they stand, so the three positional actions would
    rearrange a side that never plays from a position again.

    Home go first, which is the author's call rather than anything
    the position decides: nobody kicks off here, so the reason
    setup and halftime have an order does not apply.

    It runs as a stage sequence for the same reason halftime does:
    two windows one after the other are two live interactions with
    the bot's own step between them, and a restart in the middle
    has nothing to click. `pending_full_time_stage` is what a
    restart reads.
    """
    match.pending_full_time_stage = FULL_TIME_STAGES[0]
    return advance_full_time_stage(engine, game, match)


def advance_full_time_stage(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
) -> StepResult:
    """Hand the next coach their one substitution, or shoot out."""
    stage = match.pending_full_time_stage
    if stage in ("coaching_home", "coaching_visiting"):
        side = (
            TeamSide.HOME
            if stage == "coaching_home"
            else TeamSide.VISITING
        )
        # A menu whose only action is disabled is a Done button
        # with extra steps, and this window has no other action to
        # fall back on -- so a side with nobody it could bring on
        # is passed over in silence, the way halftime passes over a
        # side with nobody to take an extra token off. It takes
        # both benches spent: three substitutions to drain the
        # bench, and every one of the three who came off injured.
        if not match.substitution_pool(side):
            engine.next_full_time_stage(match)
            return advance_full_time_stage(engine, game, match)

        setup = match.setup_for_side(side)
        return StepResult(
            next=FollowOn(
                FollowOnStep.BEGIN_SUBSTITUTION_WINDOW,
                {
                    "side": side,
                    "occasion": CoachingOccasion.FULL_TIME,
                    "heading": (
                        "## Before the shootout\n"
                        f"{format_team_side_label(setup)} "
                        "may make **one substitution** -- the last change "
                        "either side gets. Nothing else is offered: the "
                        "shootout is played by whoever is on the field, "
                        "and not by where they are standing."
                    ),
                },
            ),
        )

    return finish_full_time_coaching(engine, game, match)


def finish_full_time_coaching(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
) -> StepResult:
    """Both coaches are done, so the shooting can start."""
    match.pending_full_time_stage = None
    return begin_shootout(engine, game, match)


# -- The extreme shootout --------------------------------------------


def begin_shootout(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
) -> StepResult:
    """
    Open the shootout that settles a game level at full time. See
    "Extreme shootout" in docs/living-rules.md.

    The shootout is **four steps that hand back to each other**,
    and `advance_shootout` is the single reading of which one a
    saved game is on -- the same job `pending_prompt` does for
    a turn, and for the same reason: two of the four are the
    bot's own move, so a restart between them has no button
    anywhere to press.

    The explainer is its own message, which is why
    `d12ball.flow.periods.begin_shootout` posts it rather than carrying it into the
    order prompt: what the shootout is and whose turn it is to answer
    are two things to read.
    """
    match.begin_shootout()
    result = advance_shootout(engine, game, match)
    result.narration.insert(
        0,
        (
            "# Extreme shootout\n"
            "The scores are level, so the game is settled on the "
            "extreme shootout.\n\n"
            "Each coach secretly puts their **six field players** in "
            "the order they will shoot. Both sides then reveal their "
            "top card together and those two players roll a **skill "
            "test**, each adding their offensive skill -- an injured "
            "player adds none and rolls the bare d12. The winner "
            "scores a goal; a tie scores for nobody. Six skill tests "
            "is a **round**, and a level round goes to sudden death."
        ),
    )
    return result


def advance_shootout(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
) -> StepResult:
    """
    Put the shootout's next step in front of whoever owes it.

    Everything routes through here -- opening the shootout, the
    end of a skill test, and `/d12ball resume` -- so there is one
    answer to "what is this shootout waiting on?" and no way for
    the resume to offer a different step from the one a restart
    restores. `d12ball.prompts.pending_prompt` reads the same three
    states off the same three questions.
    """
    if not match.shootout_orders_complete:
        return ask_shootout_orders(engine, game, match)

    if not match.shootout_shooters_complete:
        return ask_shootout_shooters(engine, game, match)

    return reveal_shootout_test(engine, game, match)


def ask_shootout_orders(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
) -> StepResult:
    """
    The secret ordering both coaches do before the first test. An AI
    side answers the same prompt through the service, one name at a
    time (`AIStrategy.choose`), before it reaches the coach.
    """
    if match.shootout_orders_complete:
        return reveal_shootout_test(engine, game, match)

    return StepResult(next=shootout_order_prompt(engine, game, match))


def ask_shootout_shooters(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
) -> StepResult:
    """
    Sudden death's pick. Only ever reached in a round past the
    first: the first round's shooter is read off the order, so
    there is nothing to ask for and nothing to lose in a restart.
    """
    if match.shootout_shooters_complete:
        return reveal_shootout_test(engine, game, match)

    return StepResult(next=shootout_pick_prompt(engine, game, match))


def shootout_order_step(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    *,
    side: TeamSide,
    player_id: str,
) -> StepResult:
    """
    Add one player to a side's shooting order.

    **The order as it stands is the first narration block**, because a
    frontend puts it back on the menu a coach is still filling in, and
    **the line saying the order is set is the second** -- that one is
    public, since both sides watch for it. A side still choosing says
    only the first.

    `MatchState.add_to_shootout_order` refuses a stale click -- a coach
    who scrolled back, or a menu restored after a restart -- and the
    refusal is left to propagate, as everywhere else.

    It ends on `advance_shootout` once *both* sides have answered,
    which is the one reading of what a shootout is waiting on.
    """
    match.add_to_shootout_order(side, player_id)
    narration = [shootout_order_text(engine, game, match, side)]
    if not match.shootout_order_complete(side):
        return StepResult(narration=narration)

    narration.append(
        f"{format_team_side_label(match.setup_for_side(side))} "
        "has set their shooting order."
    )
    if not match.shootout_orders_complete:
        return StepResult(narration=narration)
    result = advance_shootout(engine, game, match)
    result.narration[:0] = narration
    return result


def restart_shootout_order_step(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    *,
    side: TeamSide,
) -> StepResult:
    """
    Clear a side's shooting order so they can build it again.

    **An order cannot be changed once it is complete**, and that is the
    whole of the rule here: up to then it is a draft, and after it the
    other side may already have read it.
    """
    if match.shootout_order_complete(side):
        raise RuleRefusal(
            "Your order is already set, and an order cannot be "
            "changed once it is."
        )
    match.clear_shootout_order(side)
    return StepResult(
        narration=[shootout_order_text(engine, game, match, side)],
    )


def shootout_pick_step(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    *,
    side: TeamSide,
    player_id: str,
) -> StepResult:
    """
    Send one side's shooter out for this round.

    Two blocks, the same way the order's are: what *this* coach is
    told, which is secret until both have answered, and the public line
    saying they have answered. It ends on `advance_shootout` once both
    have.
    """
    if match.shootout_shooter(side) is not None:
        raise RuleRefusal("You have already chosen your shooter.")

    match.set_shootout_shooter(side, player_id)
    player = engine.get_player_definition(player_id)
    narration = [
        f"You send out {engine.format_player_label(match, player)}.",
        f"{format_team_side_label(match.setup_for_side(side))} "
        "has chosen their shooter.",
    ]
    if not match.shootout_shooters_complete:
        return StepResult(narration=narration)
    result = advance_shootout(engine, game, match)
    result.narration[:0] = narration
    return result


def reveal_shootout_test(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
) -> StepResult:
    """
    Both top cards, turned over together, and the button that
    rolls them against each other. Either coach may press it, like
    every other roll in the game.
    """
    from d12ball.flow.turn import injured_word_and_emoji

    lines = []
    for side in (TeamSide.HOME, TeamSide.VISITING):
        shooter_id = match.shootout_shooter(side)
        if shooter_id is None:
            # Nothing to reveal means the state moved under us --
            # advance_shootout is the only way back in.
            return advance_shootout(engine, game, match)
        player = engine.get_player_definition(shooter_id)
        if shooter_id in match.injured:
            word, _ = injured_word_and_emoji(engine, game, shooter_id)
            note = f" — {word}, no skill modifier"
        else:
            note = ""
        lines.append(f"{engine.format_player_label(match, player)}{note}")

    return StepResult(
        next=PendingPrompt(
            PromptKind.SHOOTOUT_TEST,
            f"{engine.shootout_heading(match)}\n"
            f"{lines[0]}\nversus\n{lines[1]}\n\nEither player can roll:",
        ),
    )


def shootout_order_text(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    side: TeamSide,
) -> str:
    """The order a coach has built so far, on their own menu."""
    from d12ball.flow.turn import injured_word_and_emoji

    lines = []
    for position, player_id in enumerate(
        match.shootout_order(side), start=1,
    ):
        player = engine.get_player_definition(player_id)
        if player_id in match.injured:
            word, _ = injured_word_and_emoji(engine, game, player_id)
            note = f" — {word}"
        else:
            note = ""
        lines.append(
            f"{position}. "
            f"{engine.format_player_label(match, player)}{note}"
        )

    if match.shootout_order_complete(side):
        header = (
            "**Your shooting order is set.** You may look at it, "
            "but not reorder it."
        )
    elif lines:
        header = "Keep going -- click the next player to shoot."
    else:
        header = (
            "Click your six players in the order they shoot. Only "
            "you can see this."
        )

    return "\n".join([header, *lines])


def continue_shootout(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
) -> StepResult:
    """
    What a settled skill test hands back to: end the shootout, or
    set the next test up.

    The test has already retired its two shooters by the time this
    runs (`finish_shootout_test`, in the same save as the goal),
    which is what lets `shootout_winner` count the tests still to
    come simply by asking who is left.
    """
    winner: Optional[TeamSide] = match.shootout_winner()
    if winner is None:
        return advance_shootout(engine, game, match)

    match.pending_shootout = False
    game.finish_game()

    home = match.shootout_goals_for(TeamSide.HOME)
    visiting = match.shootout_goals_for(TeamSide.VISITING)
    return StepResult(
        narration=[
            f"**The extreme shootout is settled, {home}-{visiting}.**"
            f"\n\n{build_full_time_summary(game, match)}"
            f"\n\n{goal_log(engine, match)}"
        ],
        next=FollowOn(FollowOnStep.ANNOUNCE_GAME_OVER),
    )
