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
    is a joint of the battle a frontend may have something to decide
    at: step 7 redraws the battle round by round.
    """

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
    die had to reach, and the hits.
    """

    seat: str
    force: str
    target: str
    dice: tuple[int, ...]
    modifier: int
    needed: int
    hits: int

    def to_dict(self) -> dict:
        return {
            "seat": self.seat, "force": self.force, "target": self.target,
            "dice": list(self.dice), "modifier": self.modifier,
            "needed": self.needed, "hits": self.hits,
        }


@dataclass
class StepResult:
    """
    What one step did, and what should happen next. `narration` is a
    list of blocks in the order they were said, which the frontend
    joins; `board_changed` says whether anything a picture draws moved.
    """

    narration: list[str] = field(default_factory=list)
    board_changed: bool = False
    next: Optional[Union["PendingPrompt", FollowOn]] = None
    rolls: list[Roll] = field(default_factory=list)

    def to_dict(self) -> dict:
        from tnp.wire import jsonable

        return {
            "narration": list(self.narration),
            "board_changed": self.board_changed,
            "next": jsonable(self.next),
            "rolls": [roll.to_dict() for roll in self.rolls],
        }
