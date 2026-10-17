"""
**The spaces' numbers**: every space is named by its place on a number
line whose zero is the middle of the field (Law 2.1.3) -- negative
toward the home end, positive toward the visitors'. On the boards with
an odd number of spaces the middle is the kickoff space, which is `0`:
board 7 runs `-3` to `3`, board 9 `-4` to `4`. Board 10 has no middle
space; its middle is the halfway line between its two kickoff spaces,
so it has no `0` and runs `-5` to `-1` and `1` to `5`. The author set
this on 2026-10-17, for both editions; before it, a space was counted
`1` to `7` (or `9`, `10`) from the home end, which was itself an
experiment from 2026-09-23 the author kept on 2026-09-28.

**Nothing here is a rule.** The number is presentation: no rule reads
it, and the model still measures everything in (zone, space_index)
pairs. `BoardState.flat_index` already numbers the board left to right
for distances -- this is that same order, shifted so the middle is
zero, put in front of a coach.

**Two readers, one answer.** `d12ball.formatting.space_label` writes it
into sentences and buttons ("space -2"); `d12ball.render.space_code`
draws it large in the middle of each space on the board image. Both
ask `space_name` here, so the board and the message a coach reads
beside it cannot disagree about what a space is called -- or about how
a negative number is spelt: with the minus sign, U+2212, never the
hyphen, which already joins a range ("spaces 1-2").

**The board is asked because the zones differ by size.** A number
needs to know how many spaces the zones to its left hold and where the
middle falls, and neither is the same on the 7-space board (2/3/2),
the 9-space one (3/3/3) and the 10-space one (3/4/3). Every caller has
the board or its layout in hand, so the count comes from the position
rather than from a table here; where a caller genuinely has neither,
`DEFAULT_BOARD_ZONES` stands in, which is the 7-space board. The goal
zones hold no spaces (Law 2.1.4), so they are not zones here and never
shift a number.
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


def space_number(
    zone: Zone,
    space_index: int,
    board: Optional[Union[BoardState, BoardLayout]] = None,
) -> int:
    """
    A space's place on the number line whose zero is the middle of
    the field: -3 to 3 on board 7, -4 to 4 on board 9, and -5 to -1
    and 1 to 5 on board 10, which has a halfway line where the others
    have a middle space, and so no 0.

    The same ordering `BoardState.flat_index` measures distance along,
    shifted so the middle is zero.
    """
    zone = Zone(zone)
    counts = zone_counts(board)
    size = sum(counts.values())
    offset = 0
    for board_zone in Zone:
        if board_zone is zone:
            flat = offset + space_index
            break
        offset += counts[board_zone]
    else:
        raise ValueError("Unknown zone.")
    half = size // 2
    if size % 2:
        return flat - half
    return flat - half + (1 if flat >= half else 0)


# U+2212, the minus sign: a hyphen already joins a range.
MINUS = "\u2212"


def space_name(
    zone: Zone,
    space_index: int,
    board: Optional[Union[BoardState, BoardLayout]] = None,
) -> str:
    """
    The number as it is written -- "3", "0", "-2" -- with the minus
    sign (`MINUS`) where this docstring has a hyphen, so a range
    ("spaces 1-2") and a negative number never read alike.
    """
    number = space_number(zone, space_index, board)
    return f"{MINUS}{-number}" if number < 0 else str(number)
