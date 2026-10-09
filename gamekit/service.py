"""
What both games' services share (`gamesaves.d12ball.service`,
`gamesaves.codex.service`, which re-export it): `StopHandling`, the
three answers a frontend's `Batching.at_stop` gives where the loop
stopped for it.

Each game's `Batching` stays its own -- D12 Ball's carries
`speaks_lines` and `carry_answer` for the AI's turn, Codex's
`draw_after` for the turn's end -- and so do `Narration`, `GameResult`
and `GameService`, which are typed by each game's own steps, prompts
and record (docs/design/codex.md, "What the two games share").
"""

from enum import Enum, auto


class StopHandling(Enum):
    """What a frontend does where the loop stopped for it."""

    #: Take the picture: the group carries the position as it stands.
    DRAW = auto()
    #: Post the lines plainly, with no picture.
    POST = auto()
    #: Nothing to show here after all: the lines carry on into the
    #: next step as its lead-in.
    CARRY = auto()
