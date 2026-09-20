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
    #: Where a drained injury-test queue puts the turn back. Phase 4's,
    #: and a member rather than a lift because two of the three
    #: arrivals it names are not the spine's: a maneuver's skill test
    #: goes on to `begin_effect_resolution` and a shootout test to
    #: `continue_shootout`, neither of which this phase moves. The
    #: third, `begin_run_back`, did move -- but a dispatcher that can
    #: only answer one of its three kinds in the model is a dispatcher
    #: split in two, which is the second-copy failure principle 3 is
    #: about. It goes when Phase 5 takes the shootout.
    DISPATCH_INJURY_RESUME = auto()
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
