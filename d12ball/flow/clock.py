"""
The clock, charged the moment an action's outcome is decided.

**Law 16.2.4** (2026-09-28): a maneuver is charged as soon as its winner
is known -- on the cards, on a won skill test, or as it succeeds with no
challenger; a score attempt once the shot has resolved; a time out as it
is called. Everything the action leads to -- the movement, a loose
ball, a run back, a pickup, the injury checks -- happens on the clock as
it then stands. Until then the whole cost was charged at the very end,
in `finish_maneuver_resolution`, which is also why the turnover that
ended a period never reached the clock at all.

**Last possession is not this module's.** It is declared at the end of
the action that reached the last minute (Law 4.4.4, 16.3.1), which is
still `finish_maneuver_resolution`; charging here only moves the
number. See `MatchState.advance_time` and `declare_last_possession`.

A leaf: it imports nothing from the rest of the flow, so every step
that decides an outcome can charge through it. See
docs/design/clock-and-records.md, "When the clock advances".
"""

from __future__ import annotations

from d12ball.components import MatchState
from d12ball.engine import RulesEngine


def clock_line(match: MatchState, minutes: int) -> str:
    """The sentence a charge is said with: what it cost, and the minute."""
    return (
        f"Time has advanced {minutes}, now at "
        f"{match.scoreboard.time:02d}."
    )


def charge_clock(match: MatchState, minutes: int) -> str:
    """
    Advance the clock by an action's cost, mark the action charged, and
    say so.

    **It always charges.** A set-up shot is the one action charged
    twice -- the maneuver's cost when its winner is decided and the
    shot's minute once the shot resolves (Law 16.2.5) -- so the guard
    against charging a maneuver twice is `charge_maneuver_clock`'s,
    not this.
    """
    match.advance_time(minutes)
    match.clock_charged = True
    return clock_line(match, minutes)


def charge_maneuver_clock(
    engine: RulesEngine,
    match: MatchState,
    winner_key: str,
) -> str:
    """
    Charge a maneuver's cost the moment its winner is decided, once.

    Returns the clock's sentence, or "" when this maneuver has already
    been charged. The guard is what lets `begin_effect_resolution` ask
    again as a backstop behind every place a winner is decided: a
    skill test charges on the winning roll and its effect runs only
    after the injury checks, possibly after a restart, and a game saved
    under the old rule reaches the effect with nothing charged yet.
    """
    if match.clock_charged:
        return ""
    return charge_clock(
        match, engine.maneuver_clock_cost(match, winner_key),
    )
