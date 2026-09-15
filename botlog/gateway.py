"""
Gateway reconnects, and which of them are worth a person's attention.

discord.py reconnects on its own. When a connection drops -- Discord
restarting a gateway node, a 503 from the handshake, the host's wifi
blinking -- Client.connect catches it, waits out an exponential
backoff and tries again, and the only trace of it is one line:

    ERROR discord.client: Attempting a reconnect in 14.13s
    ... aiohttp.client_exceptions.WSServerHandshakeError: 503 ...

That is logged at ERROR with the traceback attached, which under this
bot's rules puts it in #logs (see "The level you log at decides who
sees it" in CLAUDE.md). It should not be there. Nobody can act on it,
the library has already dealt with it, and a channel that carries
Discord's own weather reports is a channel people stop reading -- so
the one record in it that did need somebody goes past unnoticed.

So the mirror filters them out and the console keeps every one, which
is the right way round: the traceback names the actual cause, and the
person who wants it is the one sitting at the host with the bot in
front of them.

What survives the filter is the case where the reconnecting genuinely
is a problem: a run of failures that has gone on long enough that the
bot is, for practical purposes, off the server. That is escalated once
the run passes ESCALATE_AFTER_SECONDS, and again every
ESCALATION_INTERVAL_SECONDS it continues, so an outage neither floods
the channel nor quietly looks resolved. The escalated record is the
library's own, traceback and all -- by then the cause is the useful
part -- carrying a note that says how long it has been going on,
which is the whole of what makes it different from the ones held back.

Delivery is best-effort and that is not a new caveat: the mirror posts
over the REST API rather than the gateway, so it usually works while
the gateway is down, and when it does not the sink already prints to
stderr and drops the record.
"""

import logging
import time
from typing import Callable, Optional


# The attribute an escalated record carries, naming the outage behind
# it. Set by the filter and read by DiscordLogChannelHandler.format;
# the console's formatter ignores attributes it was not asked for, so
# this reaches the channel and nowhere else.
OUTAGE_NOTE_ATTRIBUTE = "foolbot_gateway_outage"

# How long an unbroken run of failed reconnects has to last before it
# is worth somebody's attention. discord.py's backoff doubles from a
# second, so five minutes is somewhere around eight or nine attempts --
# well past anything a gateway node restarting produces, and short
# enough that a game in progress has not been abandoned over it.
ESCALATE_AFTER_SECONDS = 5 * 60

# Once escalated, how long the same run goes quiet for before saying so
# again. The channel should not be able to tell the difference between
# an outage that ended and one nobody has fixed, but it should not be
# told every seventeen seconds either.
ESCALATION_INTERVAL_SECONDS = 15 * 60

# A gap this long with no reconnect record at all means the previous
# run ended, whether or not anything told us so. The recovery hook
# below is the ordinary way a run is closed; this is what keeps the
# filter honest if that hook is never called -- without it, one hiccup
# today and another next month would read as a month-long outage and
# escalate on the spot. Comfortably past discord.py's own ceiling on
# the backoff, so it cannot fire in the middle of a live run.
RUN_RESET_AFTER_SECONDS = 30 * 60

# What discord.py's reconnect line starts with, in client.py (one
# connection) and shard.py (a shard's). Matching the library's own
# wording is the load-bearing part of this module and the part that can
# rot: if it is ever reworded, this filter stops recognising the record
# and #logs goes back to carrying it, which is today's behaviour and
# not a new failure.
RECONNECT_MESSAGE_PREFIX = "Attempting a reconnect"


def is_gateway_reconnect(record: logging.LogRecord) -> bool:
    """
    Whether this record is discord.py announcing that it is about to
    retry a dropped connection.

    Read off the format string rather than the formatted message: the
    template is the library's own literal, where the message has a
    delay interpolated into it, and record.getMessage() can raise on a
    record whose args do not match -- which is not something a filter
    may do.
    """
    if not record.name.startswith("discord."):
        return False

    message = record.msg

    if not isinstance(message, str):
        return False

    return message.startswith(RECONNECT_MESSAGE_PREFIX)


def describe_duration(seconds: float) -> str:
    """One rough, readable span. Nothing here is worth a stopwatch."""
    if seconds < 90:
        return f"{int(round(seconds))} seconds"

    minutes = int(round(seconds / 60))

    if minutes < 90:
        return f"{minutes} minutes"

    return f"{minutes / 60:.1f} hours"


def describe_attempts(attempts: int) -> str:
    return "1 attempt" if attempts == 1 else f"{attempts} attempts"


class GatewayReconnectFilter(logging.Filter):
    """
    Keeps routine reconnects out of the log channel, and lets a
    sustained one through.

    Attached to the Discord sink and to nothing else, so the console
    still gets every record. Pure over its own state and the clock it
    is given, which is what lets the awkward sequences be tested
    without a gateway to drop.

    The state needs no lock, for the reason the sink's flood control
    does not: only a reconnect record touches it, every other record
    is answered before the first field is read, and the reconnects and
    the recovery hook both arrive on the event loop's own thread.
    """

    def __init__(
        self,
        escalate_after: float = ESCALATE_AFTER_SECONDS,
        escalation_interval: float = ESCALATION_INTERVAL_SECONDS,
        run_reset_after: float = RUN_RESET_AFTER_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__()
        self._escalate_after = escalate_after
        self._escalation_interval = escalation_interval
        self._run_reset_after = run_reset_after
        self._clock = clock
        self._reset()

    def _reset(self) -> None:
        self._run_started: Optional[float] = None
        self._last_seen: Optional[float] = None
        self._last_escalation: Optional[float] = None
        self._attempts = 0
        self._escalated = False

    def filter(self, record: logging.LogRecord) -> bool:
        if not is_gateway_reconnect(record):
            return True

        now = self._clock()

        if (
            self._run_started is None
            or self._last_seen is None
            or now - self._last_seen >= self._run_reset_after
        ):
            self._reset()
            self._run_started = now

        self._last_seen = now
        self._attempts += 1
        outage = now - self._run_started

        if outage < self._escalate_after:
            return False

        if (
            self._last_escalation is not None
            and now - self._last_escalation < self._escalation_interval
        ):
            return False

        self._last_escalation = now
        self._escalated = True
        setattr(record, OUTAGE_NOTE_ATTRIBUTE, self._outage_note(outage))

        return True

    def _outage_note(self, outage: float) -> str:
        return (
            "**Discord's gateway has been unreachable for "
            f"{describe_duration(outage)}** "
            f"({describe_attempts(self._attempts)}). The bot is still "
            "retrying on its own; the record below is the latest "
            "failure."
        )

    def note_recovery(self) -> Optional[str]:
        """
        Called when the bot is back on the gateway. Closes the run and
        answers with the line worth posting, or None.

        Only an outage that was *escalated* gets a line. Announcing the
        end of something the channel was never told about is noise of
        exactly the kind this module exists to remove -- but leaving an
        escalation standing with no resolution is worse than never
        having posted it, since the state it describes is the one
        somebody would be acting on.
        """
        started = self._run_started
        attempts = self._attempts
        escalated = self._escalated
        outage = (
            self._clock() - started
            if started is not None
            else 0.0
        )

        self._reset()

        if not escalated:
            return None

        return (
            "**Back on Discord's gateway**, after "
            f"{describe_duration(outage)} and "
            f"{describe_attempts(attempts)}."
        )
