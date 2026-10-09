"""
A game's channel and its category, for both bots: the name made safe to
keep and the category found or made. `cogs.d12ball_helpers` re-exports
all three names; `cogs.codex_helpers` imports them from here. Each bot's
channel name -- its prefix, the number after it, what follows -- and its
categories are its own.
"""

import re

import discord

#: Discord's limit on a channel's name.
CHANNEL_NAME_MAX_LENGTH = 100


def slugify_channel_part(text: str) -> str:
    """
    Turn free text into something Discord will keep verbatim in a
    channel name.

    Discord lowercases a text channel's name and rewrites spaces as
    dashes itself, so doing it here only means the name we save and the
    name the server shows are the same string. Punctuation is dropped
    rather than kept, because Discord's own rewriting of it is not
    worth predicting. Letters outside ASCII survive -- they are legal
    in a channel name, and a display name that is entirely non-Latin
    would otherwise slugify to nothing.
    """
    return re.sub(r"[^\w]+", "-", text, flags=re.UNICODE).strip("-_").casefold()


async def get_or_create_category(
    guild: discord.Guild,
    name: str,
    reason: str,
) -> discord.CategoryChannel:
    """The guild's category by that name, matched without case, or a
    new one."""
    for category in guild.categories:
        if category.name.casefold() == name.casefold():
            return category

    return await guild.create_category(name=name, reason=reason)
