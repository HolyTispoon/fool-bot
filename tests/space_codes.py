"""
Naming a space in a test's expectations without spelling the code.

A test that expects the ball on the second space of midfield writes
`code(match.board, "M2")` rather than `"M2"`, and gets back whatever
the bot currently calls that space: the letter form, or the flat
number while the numbering experiment is on
(`d12ball/space_numbering.py`, docs/SPACE-NUMBERING-EXPERIMENT.md).

The letter form is the spelling in the test source because it says
which zone and which space without the reader having to count, and
because it is the same on both board sizes -- `M2` is midfield's
middle space whether the board has seven spaces or nine, where the
flat number is 4 on one and 5 on the other. The board is asked
because only it knows which.
"""

from d12ball.components import Zone
from d12ball.formatting import space_label


ZONES_BY_LETTER = {
    "H": Zone.HOME_GOAL,
    "M": Zone.MIDFIELD,
    "V": Zone.VISITORS_GOAL,
}


def code(board, literal: str) -> str:
    """`"M2"` as this board's own name for that space."""
    zone = ZONES_BY_LETTER[literal[0]]
    return space_label(zone, int(literal[1:]) - 1, board)


def codes(board, *literals: str) -> list[str]:
    """The same, for a list of expected spaces."""
    return [code(board, literal) for literal in literals]
