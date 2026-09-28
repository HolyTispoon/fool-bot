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

**Last possession is declared here**, the moment the charge reaches the
period's last minute (Law 16.3.1, the author, 2026-09-28), and announced
in the charge's own sentence. It is nobody's yet: `start_turn` hands it
to whoever is offered the next turn (`MatchState.begin_last_possession`),
so the declaring action is finished in full and its own turnover does
not end the period.

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


def last_possession_line(match: MatchState) -> str:
    """The declaration, said when the clock gets there."""
    return (
        f"The clock has reached {match.scoreboard.last_minute:02d}: "
        "**last possession** is declared. Whoever has the ball once "
        "this play resolves has it, and their next turnover ends the "
        "period. The clock keeps running."
    )


def charge_clock(match: MatchState, minutes: int) -> str:
    """
    Advance the clock by an action's cost, mark the action charged, and
    say so -- with last possession declared, and said, when the charge
    is what reaches the period's last minute.

    **It always charges.** A set-up shot is the one action charged
    twice -- the maneuver's cost when its winner is decided and the
    shot's minute once the shot resolves (Law 16.2.5) -- so the guard
    against charging a maneuver twice is `charge_maneuver_clock`'s,
    not this.
    """
    match.advance_time(minutes)
    match.clock_charged = True
    line = clock_line(match, minutes)
    if match.declare_last_possession():
        line = f"{line} {last_possession_line(match)}"
    return line


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
