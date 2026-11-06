"""
What a TNP flow step hands back: `StepResult`, and the two shapes of
"what happens next" -- copied from `codex/flow/result.py`, whose
docstrings say why each is the shape it is
(docs/design/model-discord-split.md).

A step mutates the match and says what happened, in the model's voice
with tokens (`tnp.tokens`). It sends nothing and saves nothing. `next`
is a `PendingPrompt` -- somebody is asked -- or a `FollowOn` naming the
step the driver runs next, or `None`.

TNP's addition is `rolls`: **each force's dice, as numbers beside the
sentence saying them**, so a frontend can draw the dice without parsing
a line (`d12ball/flow/rolls.py` hands its numbers back the same way).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING, Any, Mapping, Optional, Union

if TYPE_CHECKING:
    from tnp.prompts import PendingPrompt


class FollowOnStep(Enum):
    """
    The steps a step can end by naming -- the keys of
    `tnp.flow.driver.MODEL_STEPS`, which covers this enum exactly. Each
    is a joint a frontend may have something to decide at: step 6 posts
    March attack by attack, and step 7 redraws the battle round by round.
    """

    # -- The turn (TNP 5) -------------------------------------------------
    #: Both seats have locked in Infrastructure and Deployment: each
    #: pays, its queue goes on its facilities and its units into their
    #: spots, and March opens (TNP 5.2, 5.3).
    REVEAL = auto()
    #: The next attack of March, or March's end (TNP 5.4 to 5.8).
    MARCH = auto()
    #: A battle in March is over: its outcome goes on the map (TNP 5.7,
    #: 6.11).
    SETTLE_BATTLE = auto()
    #: Production and Trade opens: the queues are finished (TNP 5.9).
    PRODUCE = auto()
    #: Both seats have locked in their trades (TNP 5.9).
    SETTLE_TRADES = auto()
    #: Cleanup, the 51% count, and the next turn (TNP 5.10, 1.3).
    CLEANUP = auto()

    # -- The battle (TNP 6) ---------------------------------------------

    #: A round's start (TNP 6.4, 6.5): the scouting advantage, the
    #: unengaged forces lifted out of the line, and who places first.
    BEGIN_ROUND = auto()
    #: An initiative group has rolled (TNP 6.7, 6.8): Repair asked
    #: where it can be used, then the group's losses come off.
    CLOSE_GROUP = auto()
    #: A round's end (TNP 6.10): a retreat, a side with nothing left, or
    #: the round track moving up.
    END_ROUND = auto()


@dataclass(frozen=True)
class FollowOn:
    """A step to run next, by name, with the arguments it takes."""

    step: FollowOnStep
    kwargs: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"step": self.step.name, "kwargs": dict(self.kwargs)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FollowOn":
        return cls(FollowOnStep[data["step"]], dict(data.get("kwargs", {})))


@dataclass(frozen=True)
class Roll:
    """
    One force's dice against one target (TNP 6.7): who rolled, at what,
    each die as rolled, the modifier added to every die, the number a
    die had to reach, and the hits; and since step 7 the rating and each
    modifier the roll was made at.
    """

    seat: str
    force: str
    target: str
    dice: tuple[int, ...]
    modifier: int
    needed: int
    hits: int
    #: The rating rolled at (`Rating.value`), each modifier by its kind
    #: (`tnp.battle.modifier_parts`' rows), and the number a die had to
    #: show (`tnp.battle.needs`) -- why the roll needed what it did.
    rating: str = ""
    parts: tuple = ()
    needs: int = 0

    def to_dict(self) -> dict:
        return {
            "seat": self.seat, "force": self.force, "target": self.target,
            "dice": list(self.dice), "modifier": self.modifier,
            "needed": self.needed, "hits": self.hits,
            "rating": self.rating, "parts": [list(part) for part in self.parts],
            "needs": self.needs,
        }


@dataclass
class StepResult:
    """
    What one step did, and what should happen next. `narration` is a
    list of blocks in the order they were said, which the frontend
    joins; `board_changed` says whether anything a picture draws moved;
    `part` which part of the phase the lines are about.
    """

    narration: list[str] = field(default_factory=list)
    board_changed: bool = False
    next: Optional[Union["PendingPrompt", FollowOn]] = None
    rolls: list[Roll] = field(default_factory=list)
    #: Which part of its phase the step's own lines are about, where the
    #: phase has parts a frontend may tell apart: a March attack's spot,
    #: "A" or "B" (TNP 5.4). Where one thing ends and the next begins,
    #: never how the lines are put together, which is the frontend's.
    part: Optional[str] = None
    #: The area of the map those lines are about, where they are about
    #: one: the territory or base a March attack resolved at.
    area: Optional[str] = None

    def to_dict(self) -> dict:
        from tnp.wire import jsonable

        return {
            "narration": list(self.narration),
            "board_changed": self.board_changed,
            "next": jsonable(self.next),
            "rolls": [roll.to_dict() for roll in self.rolls],
            "part": self.part,
            "area": self.area,
        }
