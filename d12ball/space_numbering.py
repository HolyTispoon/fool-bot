"""
**TEMPORARY EXPERIMENT -- flat left-to-right space numbering.**

The board's spaces are ordinarily named by zone letter and position
within the zone: `H1 H2 | M1 M2 M3 | V1 V2`. This module is the one
switch that renames them as a single run across the whole field,
`1 2 3 4 5 6 7`, to see how the references read in play before any
rule or rulebook is changed.

**Nothing here is a rule.** The numbering is presentation: no rule
reads a space code, and the model still measures everything in
(zone, space_index) pairs. `BoardState.flat_index` already numbers
the board left to right for distances -- this is that same number,
one-based, put in front of a coach.

To turn the experiment off, set `FLAT_SPACE_NUMBERING = False`
below; every space code in the bot goes back to the letter form on
the next restart. The full reversal is
[docs/SPACE-NUMBERING-EXPERIMENT.md](../docs/SPACE-NUMBERING-EXPERIMENT.md).

**Two readers, one answer.** `d12ball.formatting.space_label` writes
the code into sentences and buttons; `d12ball.render.space_code`
draws it in the corner of each space on the board image. Both ask
here, so the board and the message a coach reads beside it cannot
disagree about what a space is called.

**The board is asked because the zones differ by size.** A flat
number needs to know how many spaces the zones to its left hold, and
that is not the same on the 7-space board (2/3/2) and the 9-space one
(3/3/3). Every caller has the board or its layout in hand, so the
count comes from the position rather than from a table here; where a
caller genuinely has neither, `DEFAULT_BOARD_ZONES` stands in, which
is the 7-space board.
"""

from typing import Optional, Union

from d12ball.components import BoardLayout, BoardState, Zone


# The experiment's one switch. False restores H1/M1/V1 everywhere.
FLAT_SPACE_NUMBERING = True


# The zone letters the codes are built from when the experiment is
# off. `formatting.ZONE_LETTERS` and `render.ZONE_CODES` are the two
# that spell them; neither is touched by this module.
DEFAULT_BOARD_ZONES = {
    Zone.HOME_GOAL: 2,
    Zone.MIDFIELD: 3,
    Zone.VISITORS_GOAL: 2,
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
