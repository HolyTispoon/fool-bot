"""
What a flow step hands back: `StepResult`, and the two shapes of
"what happens next".

A step mutates the match and says what happened. It does not send
anything, it does not persist, and it does not know what a message is
-- see "The model and the Discord layer" in CLAUDE.md, principles 4
and 9. The frontend reads the result and decides what becomes a
message, what becomes an edit, and what becomes a websocket frame.

`next` is either a `PendingPrompt` -- the turn stops and waits on
somebody -- or a `FollowOn`, which names the step the driver runs
next. `None` is a step that neither asks nor continues.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING, Any, Mapping, Optional, Union

if TYPE_CHECKING:
    # A type only: `d12ball.prompts` imports `FollowOn` from here, so
    # that `owed_step` can name a step, and the two modules cannot
    # both import the other at run time.
    from d12ball.prompts import PendingPrompt


class FollowOnStep(Enum):
    """
    The steps a step can end by naming -- the keys of the driver's
    table, `d12ball.flow.driver.MODEL_STEPS`, which runs every one of
    them.

    **It was transitional, and it is not any more.** Through Phases 2
    to 5 of docs/design/model-discord-split.md the spine of a turn was still
    async and still in `cogs/d12ball/`, so a step that had moved ended
    by naming the one that had not, and the cog dispatched it out of
    `D12Ball.follow_on_methods`. Phase 6 collapsed that table: the
    driver runs every member itself, and what the enum records now is
    **where one step ends and the next begins** -- which is what a
    frontend reads to decide what becomes a message of its own
    (`NarrationGroup.step`), where a picture goes, and where the loop
    must stop for one to be taken (`advance`'s `stop_after`). A closed
    set for the same reason as before: nothing on either side can
    reach a step by spelling its name.

    The member notes below are the history of how each arrived, kept
    because the *ordering* decisions they record -- what is announced
    before what, and which line rides inside which message -- are the
    rules a second frontend has to keep.

    **How it grew is worth one paragraph, because the growth was not
    the split failing.** Phase 2 started it at nine members, every one
    a step still wholly in `cogs/`. Phase 4 widened what a member
    meant -- most came to name a step whose decisions had moved and
    whose cog method was the wrapper that persisted and posted -- and
    Phases 5 and 6 each added members for steps the model already
    owned that *needed a name* once the thing reaching them became a
    step too. So the enum counted what a frontend still dispatched,
    and a member arrived every time a caller crossed the seam ahead
    of the thing it called. When the last caller crossed, the count
    stopped meaning that and started meaning this: the joints of a
    turn, which the loop runs and the frontend renders around. The
    members are named for the steps they name and their values carry
    nothing, so nothing can reach a step by spelling one.
    """

    #: The tail of every ordinary maneuver path: the clock, the end of
    #: a period, and the offensive choice handed back.
    FINISH_MANEUVER_RESOLUTION = auto()
    #: A set-up -- the offense is offered a scoring attempt instead of
    #: letting the maneuver resolve normally.
    OFFER_SCORING_ATTEMPT_CHOICE = auto()
    #: The ball-speed manipulation a Dribble Advance ends on (a burst
    #: sets 12 and asks nothing): always the last
    #: human choice in an effect, and it leads into
    #: `finish_maneuver_resolution` itself once answered. It is a
    #: follow-on rather than a `PendingPrompt` because whether anyone
    #: is asked at all is a decision the cog still owns -- Dinky
    #: answers for itself, and a tutorial beat holds the prompt behind
    #: a note. A steal owes the same choice and does **not** name this
    #: member: it rides on `BEGIN_RUN_BACK`'s `speed_choice_after`
    #: flag and `finish_run_back` offers it, once everybody is back.
    OFFER_SPEED_CHOICE = auto()
    #: The tail of a turnover: everyone who is not carrying the ball
    #: runs back to their own half, and the speed choice a steal still
    #: owes is offered at the end of it rather than before it. Rank
    #: D2's, and the first hand-off from a lifted effect into the
    #: spine proper.
    BEGIN_RUN_BACK = auto()
    #: A scoring opportunity, and the candidates who may take it. An
    #: Intercept with no field left ahead of it ends here instead of
    #: on a run back: the play never stopped, so there is nothing to
    #: run back from -- and that drops the speed choice with it.
    BEGIN_SHOOTER_CHOICE = auto()
    #: The own-goal risk a Pressure can create, put behind a button
    #: for the coach whose player is about to concede. Rank D3's, and
    #: the only member so far that names a step which posts a prompt
    #: of its own: the shove that overshot has nothing further to say
    #: and the roll is where the turn stops, so the narration opens
    #: that prompt rather than a message before it.
    BEGIN_OWN_GOAL_ROLL = auto()
    #: The ball is out of everybody's hands where it stopped, and what
    #: is standing on that space decides how it is won. Rank D1's, and
    #: the first member whose step **puts the board up itself**: it
    #: announces the position with the board under it, because the ball
    #: is lying somewhere nothing in the channel has named. A step
    #: naming this one still reports `board_changed` honestly -- the
    #: ball moved; a frontend that would otherwise draw the same board
    #: twice for one click skips its own write, which is the Discord
    #: cog's business and not the model's (principle 8). See
    #: `stop_draws_the_board` in `cogs/d12ball/core.py`.
    BEGIN_LOOSE_BALL = auto()
    #: **Setup Pass's cost**: beaten by a deflection, the coach who
    #: beat it drives the ball a further 1, 2 or 3 spaces back, and it
    #: is loose where it stops. Rank D1's, and a follow-on rather than
    #: a `PendingPrompt` for 3a's reason -- whether anybody is asked at
    #: all is still the cog's: Dinky pushes the maximum itself, and a
    #: ball already at the end of the field has nothing to offer, so
    #: the cost is simply spent. Every one of those three branches ends
    #: in `BEGIN_LOOSE_BALL`, which is why the prompt it puts up is
    #: in `PROMPTS_DRAWN_LATER` in `cogs/d12ball/core.py`: the board a
    #: deflection moved reaches the channel a beat later, from the far
    #: side of the coach's answer, rather than in front of a question
    #: whose answer moves the ball again.
    OFFER_SETUP_PASS_PUSH_BACK = auto()
    #: The whistle. Phase 5 lifted the step
    #: (`d12ball.flow.periods.end_period`) and left the member, which
    #: is the third kind below rather than the first: the cascade the
    #: whistle opens -- the whistle, the halftime recovery, an AI's
    #: extra token, the shootout's explainer -- is a **run of separate
    #: messages**, and the two steps that name this one
    #: (`finish_maneuver_resolution` and `begin_run_back`) hand their
    #: results to dispatchers that would join them into one paragraph.
    #: `d12ball.flow.periods.end_period` is the wrapper that posts them a message
    #: apiece through `post_blocks_then_dispatch`.
    END_PERIOD = auto()
    #: The offensive choice, handed back to whoever now has the ball --
    #: the last thing an ordinary turn does. Two steps since Phase 6:
    #: this one stages a tutorial beat and holds its lesson behind a
    #: Continue (`d12ball.flow.turn.begin_turn`), and `START_TURN` is
    #: what comes after the click -- the lone handler picked without
    #: asking, an AI side's whole turn, or the prompt. Split because a
    #: gate's continuation has to be a step that does not stage the
    #: beat a second time (see `d12ball.flow.gates`).
    SEND_TURN_PROMPT = auto()
    START_TURN = auto()
    #: A coaching window, on any of its five occasions. Phase 5 lifted
    #: the step (`d12ball.flow.windows.open_substitution_window`) and
    #: left the member, because the window's prompt is the one in the
    #: game that carries **the coach's own half-field** and because the
    #: tutorial's coaching explainer gates the whole of it behind a
    #: Continue button -- a picture and a gate, which is the second
    #: kind above. `heading` rides in `kwargs` rather than as narration
    #: and is not a lead-in: it goes *inside* the prompt, above the
    #: allowance, where `RulesEngine.coaching_prompt` puts it.
    BEGIN_SUBSTITUTION_WINDOW = auto()
    #: The score attempt a set-up leads into. It posts the composition
    #: image and the roll prompt, which is two uploads and no decision.
    START_SET_UP_SHOT = auto()
    #: The run-back cascade, one pass at a time. The loop is the
    #: model's (`d12ball.flow.turnovers.run_back_passes`); what stays
    #: here is the batching of its automatic placements into one
    #: message and one board refresh, which is a Discord economy and
    #: not a rule (principle 8), and the **per-pass persist**, which is
    #: a named exception to principle 9 -- see the generator.
    CONTINUE_RUN_BACK = auto()
    #: The front half of a turn, named rather than lifted because each
    #: is pictures, a bespoke view, or Phase 5's:
    #:
    #: `BEGIN_MANEUVER_ACTION_SELECTION` is where a challenger's pick
    #: hands on; `SEND_MANEUVER_ACTION_PROMPT` is the prompt it ends on,
    #: which carries the hand image, the full-size link, the field strip
    #: and a tutorial's Continue gate. `RESOLVE_MANEUVER` is the reveal.
    #: `BEGIN_EFFECT_RESOLUTION` dispatches a won card to its effect --
    #: one `if` per key over `cogs/d12ball/effects.py`, which Phase 6
    #: collapses. `BEGIN_MANEUVER_SKILL_TEST` charges both participants
    #: and puts the roll behind a button, and takes the reveal as its
    #: `headline` rather than as narration: it embeds the line in its
    #: own message instead of posting one above it.
    BEGIN_MANEUVER_ACTION_SELECTION = auto()
    SEND_MANEUVER_ACTION_PROMPT = auto()
    RESOLVE_MANEUVER = auto()
    BEGIN_EFFECT_RESOLUTION = auto()
    #: What a gambit's effect still owes once its last prompt has been
    #: answered -- Skilled Pass's free Low Pass, Setup Pass's scoring
    #: opportunity. Added by Phase 6, and the enum growing again for
    #: Phase 4's reason: the *decision* moved (it is
    #: `speed_choice_step` that reads whether a continuation is
    #: outstanding, which is a rule) and the two prompts it dispatches
    #: to are effect menus the frontend builds. See
    #: `MatchState.pending_effect_continuation` for why the record
    #: outlives its dispatch.
    CONTINUE_EFFECT = auto()
    BEGIN_MANEUVER_SKILL_TEST = auto()
    #: Settling a loose ball once both sides have answered. A member
    #: rather than a call inside `begin_loose_ball`, because the
    #: announcement above it is **its own message**: the line naming
    #: where the ball is and the line naming who came away with it are
    #: two events, and the ordinary "carry the lines forward" would
    #: make them one paragraph. See `D12Ball.post_then_dispatch`.
    RESOLVE_LOOSE_BALL = auto()
    #: The "Players run back!" note and the cascade behind it. A member
    #: for `RESOLVE_LOOSE_BALL`'s reason, and because a new play's
    #: reset -- the message the board is pinned to -- must not carry it.
    ANNOUNCE_RUN_BACK = auto()
    #: The tail of a settled cascade. A member rather than a plain call
    #: because the cog has batched narration in hand that has to be
    #: flushed before it runs -- the ordering is the frontend's, so the
    #: generator names the step and the cog decides when.
    FINISH_RUN_BACK = auto()
    #: An AI side's out-of-bounds pickup, applied without asking. It
    #: posts and redraws, and it is also what `BallRecoveryView`'s own
    #: click runs, so it stayed whole in the cog rather than being
    #: split for one of its two callers.
    APPLY_BALL_RECOVERY = auto()
    #: The kickoff board, and the tutorial's welcome over the top of
    #: it. Phase 5's, and a member for `END_PERIOD`'s neighbours'
    #: reason: `post_new_play_board` is the one pinning site in the
    #: game and the welcome was a Continue gate the cog ran, neither
    #: of which the model could know about until the last increment
    #: made the pin a stop (`StepResult.new_play`) and the gate a
    #: prompt (`d12ball.flow.gates`).
    FINISH_SETUP_COACHING = auto()
    #: The same board for the second half's kickoff. A member of its
    #: own rather than `FINISH_SETUP_COACHING` with a flag, because
    #: only one of the two arms a tutorial script.
    FINISH_HALFTIME = auto()
    #: The last message of a game: the result, the board it ended on,
    #: and the rematch and archive buttons under it. Both endings name
    #: it -- the whistle when full time settles the game, and the
    #: shootout when it does not. **It speaks the step's own lines**
    #: rather than having them posted above it, which is what
    #: `FOLLOW_ONS_THAT_SPEAK_THE_LINES` in `cogs/d12ball/core.py`
    #: says: the result and the scoresheet are the content of the
    #: message the final board rides on.
    ANNOUNCE_GAME_OVER = auto()
    #: The long pass's contest: the receiver standing where a High
    #: Pass of 3 or 4 landed still has to win a skill test to keep it.
    #: Rank O3's, and a member of its own rather than `BEGIN_LOOSE_BALL`
    #: with a `headline=` and `is_high_pass=True`, because the two
    #: steps do different things with the board: a High Pass is on a
    #: receiver both coaches watched catch it, so the contest is
    #: announced plainly and the board the pass moved has to be written
    #: **before** it. Folding it into the loose ball's member would
    #: have put it under the loose ball's stop and lost that
    #: write, which is the answer being keyed to the step working
    #: exactly as rank D1 intended. `d12ball.flow.arrivals.begin_high_pass_contest`
    #: already existed as a step, with a second caller in the declined
    #: set-up, so nothing moved to make room for it.
    BEGIN_HIGH_PASS_CONTEST = auto()
    #: What a settled shootout test hands back to: the next test, or
    #: the end of the shootout. Added by Phase 6, when the test itself
    #: moved (`d12ball.flow.rolls.shootout_test_step`) and needed a
    #: name for what follows it -- the roll used to call
    #: `d12ball.flow.periods.continue_shootout` from inside a view. It is the loop's
    #: from the moment it exists: `d12ball.flow.periods.continue_shootout`
    #: is already a step, and what the cog wrapper added was
    #: `post_blocks_then_dispatch`, which is now a row in the
    #: frontend's `own_message` set like every other run of separate
    #: events.
    CONTINUE_SHOOTOUT = auto()
    #: A challenger pick nobody was asked for -- the one defender
    #: already standing on the ball, or the AI's. Added by Phase 6,
    #: when the turn's own action (`d12ball.flow.turn.begin_maneuver_step`)
    #: became a step and needed a name for the route it takes. The step
    #: it names is `turn.auto_resolve_challenger`, which has been the
    #: model's since Phase 4; what keeps the member the *cog's* is the
    #: second kind above -- what a frontend puts up for it is the
    #: **challenge image**, the matchup drawn, and a picture is the
    #: frontend's.
    AUTO_RESOLVE_CHALLENGER = auto()
    #: The junction all five coaching occasions come back through:
    #: hand the window on, or give up on it and let the run back go
    #: ahead. Added by Phase 6, when the window's own two answers
    #: became steps and needed a name for what they end on.
    #: `d12ball.flow.windows.finish_substitution_window` has been the
    #: model's since Phase 5 and the loop runs it; what its cog wrapper
    #: added was the choice of dispatcher, which is a row in the
    #: frontend's `own_message` set now like the whistle's.
    FINISH_SUBSTITUTION_WINDOW = auto()
    #: **The steps the bot itself owes**, which `d12ball.prompts.owed_step`
    #: names for a position nobody is asked anything on: the next stage
    #: of setup, halftime or full time where no window is open; the
    #: shootout's next step; the tail of a time out once both windows
    #: have closed; the out-of-bounds pickup where nobody need move.
    #: Added by step 5 of docs/architecture-migration.md, when the
    #: recovery ladder in `GameService.resume` stopped calling the flow
    #: functions by name and started running whatever `owed_step`
    #: hands it -- so a restart, a resume and a web request all read
    #: the same answer to "is anybody asked here?". Every one of these
    #: is also called inline by the step that ordinarily reaches it;
    #: the member is the door a resume comes back in through. (Step 7
    #: took `RUN_AI_COACHING_WINDOW` out again: an AI side's window is
    #: a prompt it answers through the service, not a routine.)
    ADVANCE_SETUP_STAGE = auto()
    ADVANCE_HALFTIME_STAGE = auto()
    ADVANCE_FULL_TIME_STAGE = auto()
    ADVANCE_SHOOTOUT = auto()
    FINISH_TIME_OUT = auto()
    BEGIN_BALL_RECOVERY = auto()


@dataclass(frozen=True)
class FollowOn:
    """
    A step to run next, by name, with the arguments it takes.

    `lead_in` is **not** in `kwargs`: the narration is the result's,
    and the frontend decides whether it opens that step's message or
    becomes something else entirely. Batching is the frontend's (see
    principle 8), so nothing here says how the two go together.

    **It can be written down and read back**, because one thing in the
    game holds a step across a click: the tutorial's Continue gate
    remembers what it is holding up (`D12BallGame.tutorial_gate`). The
    arguments a gated step takes are all JSON as they stand -- two
    `str` enums, a bool and a heading -- which is what makes this a
    dict rather than a scheme.
    """

    step: FollowOnStep
    kwargs: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """The step by name and its arguments, as saved."""
        return {"step": self.step.name, "kwargs": dict(self.kwargs)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FollowOn":
        """A saved follow-on, read back. Raises `KeyError` for a step
        this version of the game does not have."""
        return cls(FollowOnStep[data["step"]], dict(data.get("kwargs", {})))


@dataclass
class StepResult:
    """
    What one step of the flow did, and what should happen next.

    `narration` is a list of blocks in the order they were said, and
    the frontend joins them -- the Discord cog joins on a single
    space, which is how the messages in a channel already read. A
    block that wants a paragraph of its own carries its own leading
    newlines, the way a gambit's cost does; it is part of the
    sentence it is charged inside rather than a message after it.

    `board_changed` is what `refresh_match_image` used to decide at the
    call site: whether anything a board draws actually moved. The cog
    turns it into at most one write of the persistent board message --
    see "Discord's rate limits" in docs/design/rate-limits.md.

    `new_play` says play is restarting from this position -- a
    kickoff, halftime, the reset after a goal, an own goal, a missed
    shot or a ball out of bounds -- and that the lines are the board's
    caption. It is the fact the frontend pins on: the Discord cog
    posts the board as its own message and pins it
    (`post_new_play_board`, the one pinning site in the game), where
    an ordinary `board_changed` is at most one write of the persistent
    message. A flag beside `board_changed` rather than a step of its
    own, because the same steps say it on some calls and not others.
    The loop stops on it, so the board a frontend puts up is the
    position the play actually starts from -- see `driver.advance`.
    """

    narration: list[str] = field(default_factory=list)
    board_changed: bool = False
    next: Optional[Union[PendingPrompt, FollowOn]] = None
    new_play: bool = False
