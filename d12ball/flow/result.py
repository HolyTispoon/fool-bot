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
    #: The loose ball a pass with nobody to receive it rolls into.
    #: Rank O1 of Phase 3 added it and rank D1 (Deflect and Clear)
    #: inherits it, the way D2 inherits `OFFER_SPEED_CHOICE` -- both
    #: reach `begin_loose_ball` without going through
    #: `finish_maneuver_resolution` first.
    BEGIN_LOOSE_BALL = auto()
    #: The ball-speed manipulation a dribble (and a steal) ends on:
    #: always the last human choice in an effect, and it leads into
    #: `finish_maneuver_resolution` itself once answered. It is a
    #: follow-on rather than a `PendingPrompt` because whether anyone
    #: is asked at all is a decision the cog still owns -- Dinky
    #: answers for itself, and a tutorial beat holds the prompt behind
    #: a note.
    OFFER_SPEED_CHOICE = auto()


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
    newlines, the way an advanced card's cost does; it is part of the
    sentence it is charged inside rather than a message after it.

    `board_changed` is what `refresh_match_image` used to decide at the
    call site: whether anything a board draws actually moved. The cog
    turns it into at most one write of the persistent board message --
    see "Discord's rate limits" in docs/design/rate-limits.md.
    """

    narration: list[str] = field(default_factory=list)
    board_changed: bool = False
    next: Optional[Union[PendingPrompt, FollowOn]] = None
