"""
Where the mirrored records go, and the switch that turns the mirror off.

FOOLBOT_LOG_CHANNEL_ID wins when it is set. Otherwise the bot looks for
a channel named FOOLBOT_LOG_CHANNEL_NAME (#logs by default) and creates
one if there is none, which is what makes the feature work in a fresh
server without a setup step.

A channel is only ever bound if the bot can actually post in it. That is
worth checking rather than assuming, because a guild's text_channels
includes channels the bot cannot see, so matching one by name proves
nothing about access -- and the sink cannot log its own failures (that
would feed it its own records), so a channel it cannot reach fails
invisibly. Refusing to bind and saying why in the console is the only
way that outage announces itself.
"""

import logging
import os
from typing import Optional

import discord


DEFAULT_LOG_CHANNEL_NAME = "logs"

# What the mirror needs on its channel. Send Messages alone is not
# enough: a channel the bot cannot view rejects the post with 50001
# Missing Access.
LOG_CHANNEL_PERMISSIONS = ("view_channel", "send_messages")

LOGGER = logging.getLogger(__name__)


def log_channel_level() -> Optional[int]:
    """
    The threshold for records mirrored to Discord, from
    FOOLBOT_LOG_CHANNEL_LEVEL (default ERROR).

    "off", "none" or an empty value disables the mirror entirely, which
    is what None means to the caller. An unrecognised name falls back to
    ERROR rather than switching the feature off by accident.
    """
    raw = os.environ.get("FOOLBOT_LOG_CHANNEL_LEVEL", "ERROR")
    raw = raw.strip().upper()

    if raw in ("", "OFF", "NONE", "DISABLED"):
        return None

    # getLevelName returns an int for a known name and a string for
    # anything else.
    level = logging.getLevelName(raw)

    return level if isinstance(level, int) else logging.ERROR


def log_channel_name() -> str:
    return os.environ.get(
        "FOOLBOT_LOG_CHANNEL_NAME",
        DEFAULT_LOG_CHANNEL_NAME,
    ).strip() or DEFAULT_LOG_CHANNEL_NAME


def log_channel_gaps(channel: discord.TextChannel) -> list[str]:
    """
    Which of LOG_CHANNEL_PERMISSIONS the bot lacks on `channel`. An
    empty list means the channel is usable.
    """
    me = getattr(channel.guild, "me", None)

    if me is None:
        # The guild's own member object is not cached yet. Assume the
        # worst and say so, rather than binding a channel blind.
        return list(LOG_CHANNEL_PERMISSIONS)

    permissions = channel.permissions_for(me)

    return [
        permission
        for permission in LOG_CHANNEL_PERMISSIONS
        if not getattr(permissions, permission, False)
    ]


def log_target_guild(client: discord.Client) -> Optional[discord.Guild]:
    """
    The server that should host the log channel: the one named by
    FOOLBOT_LOG_GUILD_ID if the bot can see it, otherwise the first
    server the bot is in.

    One channel, not one per server. The log is about the bot process,
    and the people reading it are the two of us.
    """
    raw = os.environ.get("FOOLBOT_LOG_GUILD_ID", "").strip()

    if raw.isdigit():
        guild = client.get_guild(int(raw))

        if guild is not None:
            return guild

        LOGGER.warning(
            "FOOLBOT_LOG_GUILD_ID=%s is not a server I am in; using the "
            "first server instead.",
            raw,
        )

    return client.guilds[0] if client.guilds else None


async def ensure_log_channel(
    client: discord.Client,
) -> Optional[discord.TextChannel]:
    """
    Resolve the channel to mirror into, creating it if necessary.

    Returns None when nothing usable could be resolved, which leaves the
    bot logging to the console only. Every such case is logged with what
    to do about it.
    """
    channel = _configured_channel(client)

    if channel is not None:
        return channel

    name = log_channel_name()
    guild = log_target_guild(client)

    if guild is None:
        LOGGER.warning(
            "No server available to host the #%s log channel.", name,
        )
        return None

    named = [
        channel
        for channel in guild.text_channels
        if channel.name == name
    ]

    for channel in named:
        if not log_channel_gaps(channel):
            return channel

    if named:
        # A namesake exists but is closed to us. Do not create a second
        # one: the channel is right and the permissions are wrong, so
        # say exactly that instead of posting into the void.
        LOGGER.warning(
            "Found #%s (%s) but cannot post there -- missing %s. The log "
            "channel mirror is OFF: grant those on the channel, or point "
            "FOOLBOT_LOG_CHANNEL_ID at one I can post in.",
            name,
            named[0].id,
            ", ".join(log_channel_gaps(named[0])),
        )
        return None

    try:
        return await guild.create_text_channel(
            name,
            reason="Fool bot log channel",
        )
    except discord.Forbidden:
        LOGGER.warning(
            "Missing the Manage Channels permission to create #%s; set "
            "FOOLBOT_LOG_CHANNEL_ID to an existing channel instead.",
            name,
        )
        return None
    except discord.HTTPException as error:
        LOGGER.warning("Could not create the #%s log channel: %r", name, error)
        return None


def _configured_channel(
    client: discord.Client,
) -> Optional[discord.TextChannel]:
    """
    The channel FOOLBOT_LOG_CHANNEL_ID names, when it names a text
    channel the bot can post in. Anything else falls through to the
    by-name search, after saying why.
    """
    raw = os.environ.get("FOOLBOT_LOG_CHANNEL_ID", "").strip()

    if not raw.isdigit():
        return None

    channel = client.get_channel(int(raw))

    if not isinstance(channel, discord.TextChannel):
        LOGGER.warning(
            "FOOLBOT_LOG_CHANNEL_ID=%s is not a text channel I can see; "
            "falling back to a channel by name.",
            raw,
        )
        return None

    gaps = log_channel_gaps(channel)

    if gaps:
        LOGGER.warning(
            "FOOLBOT_LOG_CHANNEL_ID=%s (#%s) is missing %s; falling back "
            "to a channel by name.",
            raw,
            channel.name,
            ", ".join(gaps),
        )
        return None

    return channel
