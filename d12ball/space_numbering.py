"""
**The spaces' numbers**: every space is named by its number counted
from the home end -- `1` to `7` on the standard board, `1` to `9` on
the big one (Law 2.1.3). It was an experiment from 2026-09-23 behind a
switch, with the rules still naming spaces `H1`/`M2`/`V1`; the author
kept it on 2026-09-28, and the rules and the Learn to Play number
spaces the same way since.

**Nothing here is a rule.** The number is presentation: no rule reads
it, and the model still measures everything in (zone, space_index)
pairs. `BoardState.flat_index` already numbers the board left to right
for distances -- this is that same number, one-based, put in front of a
coach.

**Two readers, one answer.** `d12ball.formatting.space_label` writes it
into sentences and buttons ("space 4"); `d12ball.render.space_code`
draws it in the corner of each space on the board image ("4"). Both ask
here, so the board and the message a coach reads beside it cannot
disagree about what a space is called.

**The board is asked because the zones differ by size.** A flat number
needs to know how many spaces the zones to its left hold, and that is
not the same on the 7-space board (2/3/2) and the 9-space one (3/3/3).
Every caller has the board or its layout in hand, so the count comes
from the position rather than from a table here; where a caller
genuinely has neither, `DEFAULT_BOARD_ZONES` stands in, which is the
7-space board. The goal zones hold no spaces (Law 2.1.4), so they are
not zones here and never shift a number.
"""

from typing import Optional, Union

from d12ball.components import BoardLayout, BoardState, Zone


# The 7-space board's zones, for a caller with no board to hand.
DEFAULT_BOARD_ZONES = {
    Zone.HOME_ZONE: 2,
    Zone.MIDFIELD: 3,
    Zone.VISITORS_ZONE: 2,
}


def zone_counts(
    board: Optional[Union[BoardState, BoardLayout]],
) -> dict[Zone, int]:
    """
    How many spaces each zone holds, from whichever of the two the
    caller had to hand -- the live `BoardState` (the model, the cog,
    the web app) or the `BoardLayout` alone (the printed sheets,
    which have no game on them).
    """
    if board is None:
        return DEFAULT_BOARD_ZONES
    if isinstance(board, BoardState):
        return {zone: len(spaces) for zone, spaces in board.spaces.items()}
    return board.zone_spaces


def flat_space_number(
    zone: Zone,
    space_index: int,
    board: Optional[Union[BoardState, BoardLayout]] = None,
) -> int:
    """
    A space's number counting from the home end -- 1 through 7 on the
    standard board, 1 through 9 on the big one.

    The same ordering `BoardState.flat_index` measures distance along,
    one-based because a coach counts from one.
    """
    zone = Zone(zone)
    counts = zone_counts(board)
    offset = 0
    for board_zone in Zone:
        if board_zone is zone:
            return offset + space_index + 1
        offset += counts[board_zone]
    raise ValueError("Unknown zone.")
