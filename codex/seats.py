"""
The table's seats, read one way (docs/design/codex.md, "Multiplayer").

Nothing in the Codex model or its frontends computes "the other seat" or
"is it this seat's turn" inline: it asks here, or asks the engine, whose
`opponents`, `turn_seats` and `next_seat` are these functions. They are
functions of the match alone so the renderer and the save code, which
hold no engine, read the same answer.

A seat is any positive number the match has; nothing here names 1 and 2.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from codex.components import MatchState


def seat_numbers(match: "MatchState") -> tuple[int, ...]:
    """Every seat the match has, in order."""
    return tuple(player.seat for player in match.players)


def dragon_of(match: "MatchState", seat: int) -> tuple[int, ...]:
    """The seats on `seat`'s team, `seat` included, the team's head
    first: a two-headed dragon's pair (Rulebook p. 13), else `seat`
    alone."""
    for pair in match.dragons:
        if seat in pair:
            return tuple(pair)
    return (seat,)


def teammate(match: "MatchState", seat: int) -> Optional[int]:
    """The seat `seat` shares a base with, or `None` outside a dragon."""
    others = [number for number in dragon_of(match, seat) if number != seat]
    return others[0] if others else None


def opponents(match: "MatchState", seat: int) -> tuple[int, ...]:
    """Every seat that is `seat`'s opponent, in seat order -- the one
    other seat of a duel, and in a dragon the other team's two: a
    teammate is never an opponent (Rulebook p. 13)."""
    team = dragon_of(match, seat)
    return tuple(number for number in seat_numbers(match) if number not in team)


def sole_opponent(match: "MatchState", seat: int) -> int:
    """
    The one opponent of a duel. A reading that is not yet a table's:
    every call is a site the free-for-all and the dragon have to give a
    real answer (docs/codex-multiplayer.md, "What the bot assumes
    today"), and until they do, a table with several opponents refuses
    here rather than answering for one of them.
    """
    from codex.game import RuleRefusal

    found = opponents(match, seat)
    if len(found) != 1:
        raise RuleRefusal("This needs one opponent, and this table has several.")
    return found[0]


def turn_order(match: "MatchState", after: int, *, inclusive: bool = True) -> tuple[int, ...]:
    """Every seat in turn order from `after` -- `after` first, or, not
    `inclusive`, the seat after it first and `after` last. Turn order is
    seat order, wrapping (Rulebook p. 14)."""
    numbers = seat_numbers(match)
    start = numbers.index(after) + (0 if inclusive else 1)
    return tuple(numbers[(start + step) % len(numbers)] for step in range(len(numbers)))


def turn_seats(match: "MatchState") -> tuple[int, ...]:
    """The seats whose turn it is: the active seat alone in a duel and a
    free-for-all; in a dragon both teammates of the active team, for the
    whole turn, a locked one included -- or the one seat whose extra turn
    is running ("you means you", Rulebook p. 13)."""
    if match.solo is not None:
        return (match.solo,)
    return dragon_of(match, match.active)


def acting_seats(match: "MatchState") -> tuple[int, ...]:
    """The seats that may act now: those whose turn it is, less a seat
    that has locked its patrollers -- or all of them once every seat has
    (the draw and tech phases are the team's)."""
    taking = turn_seats(match)
    unlocked = tuple(seat for seat in taking if not match.player(seat).locked)
    return unlocked or taking


def next_seat(match: "MatchState") -> int:
    """Whose turn follows the active one's: a free-for-all's playoff
    first -- the tied seats each take one more turn, ahead of the order
    (Rulebook p. 14) -- then the seat owed an extra turn (Double Time),
    else the seat after in order, wrapping."""
    if match.playoff:
        return match.playoff[0]
    if match.extra_turns and match.extra_turns[0] in turn_seats(match):
        return match.extra_turns[0]
    if match.dragons:
        # The other team's head (Rulebook p. 13).
        theirs = next(pair for pair in match.dragons if match.active not in pair)
        return theirs[0]
    seats = seat_numbers(match)
    return seats[(seats.index(match.active) + 1) % len(seats)]
