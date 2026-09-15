"""
Important bot logs, mirrored into a Discord channel.

The bot runs on someone's desktop machine. Before this, the only record
of a crash was that machine's console, so a problem seen by a player in
Discord could only be diagnosed by whoever was sitting at the host. This
package puts errors where the people using the bot already are: a #logs
channel in the server.

Four pieces, one per module:

- handler.py resolves nothing and decides nothing; it is the sink that
  gets a formatted record onto a channel without blocking whoever
  logged it.
- channel.py answers which channel that is, and refuses to bind one the
  bot cannot post in.
- gateway.py answers which records are worth a person's attention at
  all, which today is one question: whether discord.py reconnecting is
  weather or an outage.
- deploy_notice.py is the other thing worth posting: which build is
  running, once per build.

The five functions below are the seam foolbot.py calls, in this order:
configure_logging() at import, install_mirror() right after, then
start_mirror(), announce_gateway_recovery() and announce_startup() from
on_ready, which is the first point at which the client knows what
servers it is in. announce_gateway_recovery() is also called from
on_resumed, which is how most reconnects come back.

Everything is driven by environment variables, all optional, all read
from .env like DISCORD_TOKEN:

  FOOLBOT_LOG_MIRROR          "on" to post to the channel at all; off
                              unless set, so a test bot run from a
                              clone of this repo stays out of #logs
  FOOLBOT_LOG_LEVEL           console threshold (default INFO)
  FOOLBOT_LOG_CHANNEL_LEVEL   Discord threshold (default ERROR;
                              "off" disables the mirror)
  FOOLBOT_LOG_CHANNEL_ID      the exact channel to mirror into
  FOOLBOT_LOG_CHANNEL_NAME    the channel to find or create (default
                              "logs"), when no id is set
  FOOLBOT_LOG_GUILD_ID        which server hosts it (default: the first
                              server the bot is in)
  FOOLBOT_DEPLOY_NOTICE       "off" to stop announcing new builds
"""

import asyncio
import logging
import os
from typing import Optional

import discord

from botlog import deploy_notice, gateway
from botlog.channel import (
    DEFAULT_LOG_CHANNEL_NAME,
    ensure_log_channel,
    log_channel_level,
    log_channel_name,
    log_target_guild,
    mirror_enabled,
)
from botlog.gateway import GatewayReconnectFilter
from botlog.handler import DiscordLogChannelHandler, chunk_log_message


__all__ = [
    "DEFAULT_LOG_CHANNEL_NAME",
    "DiscordLogChannelHandler",
    "GatewayReconnectFilter",
    "announce_gateway_recovery",
    "announce_startup",
    "chunk_log_message",
    "configure_logging",
    "console_level",
    "deploy_notice",
    "ensure_log_channel",
    "gateway",
    "install_mirror",
    "log_channel_level",
    "log_channel_name",
    "log_target_guild",
    "mirror_enabled",
    "post_notice",
    "start_mirror",
]


DEFAULT_CONSOLE_LEVEL = logging.INFO

# Discord's own cap on a message. post_notice truncates rather than
# pages: everything it sends is a sentence or two, and a notice long
# enough to need splitting is a notice that should have been shorter.
NOTICE_LENGTH_LIMIT = 2000

LOGGER = logging.getLogger(__name__)

_console_handler: Optional[logging.Handler] = None
# The mirror's gateway filter, kept here for the same reason the
# console handler is: announce_gateway_recovery needs it back, and
# foolbot.py holds the handler rather than the pieces bolted to it.
_gateway_filter: Optional[GatewayReconnectFilter] = None


def console_level() -> int:
    """
    The console threshold, from FOOLBOT_LOG_LEVEL (default INFO). An
    unrecognised name falls back to INFO rather than silencing the bot.
    """
    raw = os.environ.get("FOOLBOT_LOG_LEVEL", "").strip().upper()

    if not raw:
        return DEFAULT_CONSOLE_LEVEL

    level = logging.getLevelName(raw)

    return level if isinstance(level, int) else DEFAULT_CONSOLE_LEVEL


def configure_logging() -> None:
    """
    Set up console logging for the whole process, once.

    discord.py normally does this itself inside bot.run, but only for
    its own logger, which would leave the bot's own log calls going
    nowhere and would double up every line once we add a root handler.
    So we configure the root logger here and pass log_handler=None to
    bot.run instead. discord.utils.setup_logging is still what does the
    work, because it picks the coloured formatter when the console can
    show colour.

    The handler carries its own level as well as the root logger, which
    matters for install_mirror: mirroring below the console threshold
    means lowering the root level, and the console must not get noisier
    as a result.
    """
    global _console_handler

    if _console_handler is not None:
        return

    level = console_level()
    handler = logging.StreamHandler()
    discord.utils.setup_logging(handler=handler, level=level, root=True)
    handler.setLevel(level)
    _console_handler = handler


def install_mirror() -> Optional[DiscordLogChannelHandler]:
    """
    Attach the Discord sink to the root logger, so it catches
    everything: the bot's own errors, the game code's, and discord.py's.

    Returns the handler, which start_mirror needs once there is a live
    client, or None when the mirror is switched off.

    Two ways off, and this is the first of the two places that check
    both -- announce_startup is the other. Gating here rather than
    inside ensure_log_channel is what keeps a silent bot from attaching
    a sink at all, and so from lowering the root level below the
    console's for records nothing will read.
    """
    global _gateway_filter

    if not mirror_enabled():
        # Console-only is the default, so say why: the alternative is a
        # developer reading the silence as the mirror being broken.
        LOGGER.info(
            "Not posting to #%s from this bot: FOOLBOT_LOG_MIRROR is not "
            "set. Logging to the console only.",
            log_channel_name(),
        )
        return None

    level = log_channel_level()

    if level is None:
        return None

    handler = DiscordLogChannelHandler(level=level)
    # On the sink, not on the root logger: the console is where a
    # dropped connection is worth reading about, and the point of the
    # filter is that those records go there and stop there. See
    # botlog/gateway.py.
    _gateway_filter = GatewayReconnectFilter()
    handler.addFilter(_gateway_filter)
    root = logging.getLogger()
    root.addHandler(handler)

    # A record filtered out by the root logger never reaches any
    # handler, so mirroring below the console threshold means lowering
    # the root level. The console handler has its own level and so stays
    # exactly as quiet as it was.
    if root.level > level:
        root.setLevel(level)

    return handler


async def start_mirror(
    client: discord.Client,
    handler: Optional[DiscordLogChannelHandler],
) -> None:
    """
    Bind the sink to a channel. Call from on_ready, which is where the
    guild list finally exists; safe to call on every reconnect, since
    binding is idempotent and this returns early once bound.
    """
    if handler is None or handler.started:
        return

    try:
        channel = await ensure_log_channel(client)

        if channel is None:
            return

        handler.start(client, channel.id)
        LOGGER.info(
            "Mirroring log records at %s and above to #%s (%s).",
            logging.getLevelName(handler.level),
            channel.name,
            channel.id,
        )
    except Exception:
        # Deliberately broad. Nothing about a log channel is worth
        # taking down the startup of a bot that is otherwise fine, and
        # the console handler still has this traceback.
        LOGGER.exception("Could not bind the Discord log channel.")


async def post_notice(client: discord.Client, message: str) -> bool:
    """
    Put one deliberate, non-error line in the log channel, and say
    whether it landed.

    The mirror carries records at ERROR and above, and a long
    maintenance job is neither an error nor something anybody wants
    raised at them -- but "the export started" and "the export
    finished, here is what it did" are exactly what somebody watching
    #logs needs, because the job outlives its own interaction token and
    goes silent otherwise. Logging it at ERROR to get it into the
    channel would break the one rule that makes that channel worth
    reading: an ERROR means somebody has to fix something (see "The
    level you log at decides who sees it" in CLAUDE.md).

    So this is the third thing that reaches the channel on purpose,
    after the sink and the deploy notice, and the third place
    FOOLBOT_LOG_MIRROR is read -- a bot that is not posting stays not
    posting, and does not go looking for a channel to bind.

    Never raises. A notice that cannot be delivered is worth a console
    line and nothing more: the work it is reporting on has either
    already happened or is about to, and neither should fail over its
    own commentary.
    """
    if not mirror_enabled():
        return False

    try:
        channel = await ensure_log_channel(client)

        if channel is None:
            return False

        # Sent as prose, not through chunk_log_message, which wraps a
        # record in a code fence -- right for a traceback and wrong for
        # a sentence somebody is meant to read. A notice is a line or
        # two by construction, so the limit is a guard rather than a
        # paging scheme.
        await channel.send(message[:NOTICE_LENGTH_LIMIT])

        return True
    except Exception:
        LOGGER.exception("Could not post a notice to the log channel.")
        return False


async def announce_gateway_recovery(client: discord.Client) -> None:
    """
    Say that the bot is back on the gateway, if its absence was ever
    announced. Call from on_ready and on_resumed -- the two events that
    fire when a connection is re-established, one per way of doing it.

    Almost always a no-op, and deliberately so: a reconnect nobody was
    told about needs no follow-up, and the filter answers None for one.
    What it is for is the outage that *was* escalated, which is a
    message in #logs describing a state somebody may be acting on --
    leaving that standing after it has cleared is the one thing worse
    than never having posted it.

    Goes out as a notice rather than a log record, for the reason
    post_notice exists: this is not an error, and an ERROR in that
    channel means somebody has to fix something.
    """
    if _gateway_filter is None:
        return

    recovery = _gateway_filter.note_recovery()

    if recovery is None:
        return

    LOGGER.info("%s", recovery)
    await post_notice(client, recovery)


async def announce_startup(client: discord.Client) -> None:
    """
    Post the "now running this build" notice, if this build has not been
    announced already. Silent on a restart of the same commit -- see
    deploy_notice for why that is the point.

    Runs after start_mirror so that if this fails, the traceback has
    somewhere to go.

    The notice is the other thing that reaches the channel, so it is
    the other place FOOLBOT_LOG_MIRROR is read. Checking it here rather
    than further in also keeps a test bot from shelling out to git on
    every reconnect for a message it is never going to send -- and
    leaves the sha unmarked, so the real bot still announces the build
    when it comes to it.
    """
    if not mirror_enabled():
        return

    try:
        previous = deploy_notice.last_announced()
        # git is a subprocess; keep it off the event loop.
        pending = await asyncio.to_thread(deploy_notice.notice_for, previous)

        if pending is None:
            return

        sha, message = pending
        channel = await ensure_log_channel(client)

        if channel is None:
            return

        await channel.send(message)
        deploy_notice.mark_announced(sha)
    except Exception:
        LOGGER.exception("Could not post the startup notice.")
