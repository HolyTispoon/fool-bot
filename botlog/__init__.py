"""
Important bot logs, mirrored into a Discord channel.

The bot runs on someone's desktop machine. Before this, the only record
of a crash was that machine's console, so a problem seen by a player in
Discord could only be diagnosed by whoever was sitting at the host. This
package puts errors where the people using the bot already are: a #logs
channel in the server.

Three pieces, one per module:

- handler.py resolves nothing and decides nothing; it is the sink that
  gets a formatted record onto a channel without blocking whoever
  logged it.
- channel.py answers which channel that is, and refuses to bind one the
  bot cannot post in.
- deploy_notice.py is the other thing worth posting: which build is
  running, once per build.

The four functions below are the seam foolbot.py calls, in this order:
configure_logging() at import, install_mirror() right after, then
start_mirror() and announce_startup() from on_ready, which is the first
point at which the client knows what servers it is in.

Everything is driven by environment variables, all optional, all read
from .env like DISCORD_TOKEN:

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

from botlog import deploy_notice
from botlog.channel import (
    DEFAULT_LOG_CHANNEL_NAME,
    ensure_log_channel,
    log_channel_level,
    log_channel_name,
    log_target_guild,
)
from botlog.handler import DiscordLogChannelHandler, chunk_log_message


__all__ = [
    "DEFAULT_LOG_CHANNEL_NAME",
    "DiscordLogChannelHandler",
    "announce_startup",
    "chunk_log_message",
    "configure_logging",
    "console_level",
    "deploy_notice",
    "ensure_log_channel",
    "install_mirror",
    "log_channel_level",
    "log_channel_name",
    "log_target_guild",
    "start_mirror",
]


DEFAULT_CONSOLE_LEVEL = logging.INFO

LOGGER = logging.getLogger(__name__)

_console_handler: Optional[logging.Handler] = None


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
    """
    level = log_channel_level()

    if level is None:
        return None

    handler = DiscordLogChannelHandler(level=level)
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


async def announce_startup(client: discord.Client) -> None:
    """
    Post the "now running this build" notice, if this build has not been
    announced already. Silent on a restart of the same commit -- see
    deploy_notice for why that is the point.

    Runs after start_mirror so that if this fails, the traceback has
    somewhere to go.
    """
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
