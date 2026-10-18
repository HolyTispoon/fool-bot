"""
Naming a space in a test's expectations without spelling the code.

A test that expects the ball on the first space of the Home Zone
writes `code(match.board, "H1")` rather than `"space −3"`, and gets
back what the bot calls that space -- its place on the number line
whose zero is the middle of the field, "space −3" on the standard
board (`d12ball/space_numbering.py`).

The letter form is the spelling in the test source because it says
which zone and which space without the reader having to count, and
because it is the same on every board size -- `H1` is the home end's
space whether the board has seven spaces or nine, where the number is
−3 on one and −4 on the other. The board is asked because only it
knows which.
"""

from d12ball.components import Zone
from d12ball.formatting import space_label


ZONES_BY_LETTER = {
    "H": Zone.HOME_ZONE,
    "M": Zone.MIDFIELD,
    "V": Zone.VISITORS_ZONE,
}


def code(board, literal: str) -> str:
    """`"M2"` as this board's own name for that space."""
    zone = ZONES_BY_LETTER[literal[0]]
    return space_label(zone, int(literal[1:]) - 1, board)


def codes(board, *literals: str) -> list[str]:
    """The same, for a list of expected spaces."""
    return [code(board, literal) for literal in literals]
