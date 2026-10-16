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

from contextlib import contextmanager
from typing import TYPE_CHECKING, Iterator, Optional

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


def other_team(match: "MatchState", seat: int) -> tuple[int, ...]:
    """A dragon's team that `seat` is not on, its head first, as the deal
    pairs it (Rulebook p. 13). Asked of a dragon alone."""
    return next(tuple(pair) for pair in match.dragons if seat not in pair)


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


def rivals(match: "MatchState", seat: int) -> tuple[int, ...]:
    """The side that wins when `seat`'s side loses a two-sided game: the
    duel's one opponent, a dragon's other team (a free-for-all has more
    than two sides and refuses, `sole_opponent`)."""
    if match.dragons:
        return opponents(match, seat)
    return (sole_opponent(match, seat),)


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
    """Whose turn follows the active one's: the seat owed an extra turn
    after this one (Double Time) first -- ahead of a free-for-all's
    playoff too (the author, 2026-10-16: "extra turn first"), since the
    card says "after this one" -- then the playoff, the tied seats each
    taking one more turn ahead of the order (Rulebook p. 14), else the
    seat after in order, wrapping."""
    if owes_extra_turn(match):
        return match.extra_turns[0]
    if match.playoff:
        return match.playoff[0]
    if match.dragons:
        # The other team's head (Rulebook p. 13).
        return other_team(match, match.active)[0]
    return turn_order(match, match.active, inclusive=False)[0]


def owes_extra_turn(match: "MatchState") -> bool:
    """Whether the turn now ending is followed by an extra turn (Double
    Time): the first seat waiting in `extra_turns` is the active seat,
    or in a dragon one of its team ("you means you", Rulebook p. 13:
    that one seat's alone)."""
    return bool(match.extra_turns) and match.extra_turns[0] in dragon_of(match, match.active)


@contextmanager
def as_active(match: "MatchState", seat: int) -> Iterator[None]:
    """
    Make `seat` the active seat for the length of a reading, and put it
    back. **In a dragon `match.active` is whichever teammate is acting**
    (the driver sets it for their action and puts the team's head back
    between actions), so every reading made on a seat's behalf -- their
    options, their ask -- is made with that seat active; a duel's and a
    free-for-all's active seat is the only one there is.
    """
    before = match.active
    match.active = seat
    try:
        yield
    finally:
        match.active = before


def head_of(match: "MatchState") -> int:
    """The seat the turn rests on between actions: the team's head in a
    dragon, or the one seat whose extra turn is running."""
    return turn_seats(match)[0]
