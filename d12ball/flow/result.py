"""
What a flow step hands back: `StepResult`, and the two shapes of
"what happens next".

A step mutates the match and says what happened. It does not send
anything, it does not persist, and it does not know what a message is
-- see "The model and the Discord layer" in CLAUDE.md, principles 4
and 9. The frontend reads the result and decides what becomes a
message, what becomes an edit, and what becomes a websocket frame.

`next` is either a `PendingPrompt` -- the turn stops and waits on
somebody -- or a `FollowOn`, which names a step of the spine that has
not moved out of the cog yet. `None` is a step that neither asks nor
continues.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Mapping, Optional, Union

from d12ball.prompts import PendingPrompt


class FollowOnStep(Enum):
    """
    The spine steps a lifted step can end by naming.

    **Transitional, and deliberately a closed set.** Through Phases 2
    to 5 of docs/model-discord-split.md the spine of a turn is still
    async and still in `cogs/d12ball/`, so a step that has moved ends
    by naming the one that has not, and the cog dispatches it. Phase 6
    is what collapses that: the driver runs follow-ons itself and this
    enum goes with the cog's dispatch table.

    **Phase 4 widened what "has not moved" means, and the enum grew
    rather than shrank because of it.** Before it, a member named a
    step still wholly in `cogs/`. After it, most members name a step
    whose *decisions* are in `d12ball/flow/` and whose cog method is
    the wrapper that persists and posts -- so the enum still reads
    exactly as "what the cog still dispatches", which is the claim
    Phase 6 needs, but not as "what has not been lifted". Three kinds
    of member are here now, and each says which it is:

    **Phase 5 grew it again, by two, and for that same widening.** It
    took `DISPATCH_INJURY_RESUME` out -- the dispatcher is
    `d12ball.flow.injuries.dispatch_injury_resume` now, and all three
    of its arrivals answer in the model -- and added
    `FINISH_SETUP_COACHING`, `FINISH_HALFTIME` and
    `ANNOUNCE_GAME_OVER`. Every one of the three is the third kind
    below and none of them is a rule: a pinned board, a pinned board,
    and the message the rematch buttons hang off. `END_PERIOD` and
    `BEGIN_SUBSTITUTION_WINDOW` were expected to leave and did not;
    each now says on its own entry which kind it turned out to be.

    - a step no phase has touched, because it is pictures and no
      decision (`SEND_TURN_PROMPT`, `START_SET_UP_SHOT`);
    - a step whose model half moved but whose prompt **carries a
      picture** (`BEGIN_SUBSTITUTION_WINDOW`).
      A third kind stood beside this one until Phase 6 -- a prompt the
      view carried arguments for that match state did not hold
      (`SEND_SET_UP_ATTEMPT_PROMPT`, `SEND_SHOOTER_PROMPT`) -- and it
      is gone: `MatchState.pending_scoring_opportunity` records the
      offer, so both are ordinary `PendingPrompt`s and a restart
      inside either comes back to it;
    - a step whose model half moved but whose lines are **their own
      message**, so the ordinary "carry the narration forward" would
      merge two events into one paragraph (`BEGIN_LOOSE_BALL`,
      `RESOLVE_LOOSE_BALL`, `ANNOUNCE_RUN_BACK`, `FINISH_RUN_BACK`,
      `END_PERIOD`), or is a board this phase may not post and pin
      (`FINISH_SETUP_COACHING`, `FINISH_HALFTIME`,
      `ANNOUNCE_GAME_OVER`). See `D12Ball.post_then_dispatch` and
      `D12Ball.post_blocks_then_dispatch`.

    A closed set rather than a callable or a method name the cog
    `getattr`s, because then **the enum itself is the record of what
    the cog still dispatches**. Phases 3 to 5 add and remove members;
    Phase 6 reads this file rather than a pull request description to
    learn what is left. The members are named for the steps they name
    and their values carry nothing, so nothing can reach a cog method
    by spelling one.
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
    #: `FOLLOW_ONS_THAT_DRAW_THE_BOARD` in `cogs/d12ball/core.py`.
    BEGIN_LOOSE_BALL = auto()
    #: **Setup Pass's cost**: beaten by a deflection, the coach who
    #: beat it drives the ball a further 1, 2 or 3 spaces back, and it
    #: is loose where it stops. Rank D1's, and a follow-on rather than
    #: a `PendingPrompt` for 3a's reason -- whether anybody is asked at
    #: all is still the cog's: Dinky pushes the maximum itself, and a
    #: ball already at the end of the field has nothing to offer, so
    #: the cost is simply spent. Every one of those three branches ends
    #: in `BEGIN_LOOSE_BALL`, which is why it keeps that member's
    #: company in `FOLLOW_ONS_THAT_DRAW_THE_BOARD`: the board a
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
    #: `D12Ball.end_period` is the wrapper that posts them a message
    #: apiece through `post_blocks_then_dispatch`.
    END_PERIOD = auto()
    #: The offensive choice, handed back to whoever now has the ball --
    #: the last thing an ordinary turn does. It is three uploads and a
    #: pin decision (see `send_turn_prompt`), so what the model settles
    #: is that the turn is over and whose it is; the pictures are the
    #: frontend's.
    SEND_TURN_PROMPT = auto()
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
    #: game and `post_tutorial_note` is a Continue gate, neither of
    #: which the model may know about.
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
    #: have put it in `FOLLOW_ONS_THAT_DRAW_THE_BOARD` and lost that
    #: write, which is the answer being keyed to the step working
    #: exactly as rank D1 intended. `D12Ball.begin_high_pass_contest`
    #: already existed as a step, with a second caller in the declined
    #: set-up, so nothing moved to make room for it.
    BEGIN_HIGH_PASS_CONTEST = auto()


@dataclass(frozen=True)
class FollowOn:
    """
    A spine step to run next, by name, with the arguments it takes.

    `lead_in` is **not** in `kwargs`: the narration is the result's,
    and the frontend decides whether it opens that step's message or
    becomes something else entirely. Batching is the frontend's (see
    principle 8), so nothing here says how the two go together.
    """

    step: FollowOnStep
    kwargs: Mapping[str, Any] = field(default_factory=dict)


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
    """

    narration: list[str] = field(default_factory=list)
    board_changed: bool = False
    next: Optional[Union[PendingPrompt, FollowOn]] = None
