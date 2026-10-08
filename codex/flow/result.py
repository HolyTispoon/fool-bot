"""
What a Codex flow step hands back: `StepResult`, and the two shapes of
"what happens next" -- copied from `d12ball/flow/result.py`, whose
docstrings say why each is the shape it is (docs/design/model-discord-split.md).

A step mutates the match and says what happened, in the model's voice
with tokens (`codex.tokens`). It sends nothing and saves nothing.
`next` is a `PendingPrompt` -- somebody is asked -- or a `FollowOn`
naming the step the driver runs next, or `None`.

Codex's addition is `drawn`: **the random outcomes the step consumed**
(a reshuffle's order), which `codex.flow.driver.apply` writes into the
journal beside the action, so a replay deals exactly what was dealt
(docs/codex-bot.md, decision 11).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING, Any, Mapping, Optional, Union

if TYPE_CHECKING:
    from codex.prompts import PendingPrompt


class FollowOnStep(Enum):
    """
    The steps a step can end by naming -- the keys of
    `codex.flow.driver.MODEL_STEPS`, which covers this enum exactly.
    Each is a joint of the turn a frontend has something to decide at,
    and the door a resume comes back in through when the bot owes it.
    """

    #: The ready phase and the upkeep (UMR p. 5): the confirmed tech
    #: cards into the discard, everything readied, the armour set, the
    #: gold collected, a summoning rune off the hero -- and the
    #: turn-start snapshot. Owed once the turn's tech choice is
    #: confirmed, or at once where none is owed.
    BEGIN_TURN = auto()
    #: The draw phase: the hand to the discard, two more drawn than were
    #: discarded, with the once-a-phase reshuffle (UMR p. 5).
    DRAW_PHASE = auto()
    #: The end of the turn: the buildings finished, the tech choice
    #: offered to the player whose turn it was, and the turn handed on.
    BEGIN_TECH = auto()


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
class Headline:
    """
    The outcome a step's lines announce, said once more on its own, for
    a frontend that puts an outcome up large. `seat` is whose outcome it
    is, where it is somebody's.
    """

    text: str
    seat: Optional[int] = None
    under: str = ""

    def to_dict(self) -> dict:
        return {"text": self.text, "seat": self.seat, "under": self.under}


@dataclass
class StepResult:
    """
    What one step did, and what should happen next. `narration` is a
    list of blocks in the order they were said, which the frontend
    joins; `board_changed` says whether anything a board draws moved.
    """

    narration: list[str] = field(default_factory=list)
    board_changed: bool = False
    next: Optional[Union["PendingPrompt", FollowOn]] = None
    new_play: bool = False
    headlines: tuple[Headline, ...] = ()
    #: Each shuffle's resulting order, in the order they were made.
    drawn: list[list[str]] = field(default_factory=list)

    def to_dict(self) -> dict:
        """
        The result as JSON -- `codex.wire`. **`drawn` is left out**: it
        is a deck's order, which nobody may know, and it goes to the
        journal in the save and nowhere else.
        """
        from codex.wire import jsonable

        return {
            "narration": list(self.narration),
            "board_changed": self.board_changed,
            "next": jsonable(self.next),
            "new_play": self.new_play,
            "headlines": [headline.to_dict() for headline in self.headlines],
        }
