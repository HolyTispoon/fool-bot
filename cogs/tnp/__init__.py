"""
The New Project's Discord frontend: every slash command under `/tnp`,
in fool-bot, under its token (docs/tnp-bot.md, decision 2).

`Tnp` is assembled from mixins, as `cogs/d12ball/` and `cogs/codex/`
are (docs/design/cog-structure.md). Step 1 has one, `reference`
(`/tnp unit`, `/tnp rules`); the game's own come with the steps after
it. Nothing in it decides a rule: it asks `tnp/` and posts the answer.

**An exception here stays here** (decision 2): `cog_load` reads the
data and logs, never raises, when it is missing, so a broken TNP
cannot stop fool-bot from loading D12 Ball; the commands then say TNP
is unavailable. See docs/design/tnp.md.
"""

from __future__ import annotations

import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from cogs.tnp.reference import UNAVAILABLE, ReferenceMixin
from tnp.catalog import Catalog, CatalogError, load

LOGGER = logging.getLogger(__name__)


class Tnp(
    ReferenceMixin,
    commands.GroupCog,
    group_name="tnp",
    group_description="The New Project: its units and its rules.",
):
    """
    A Discord cog for The New Project.

    `group_description` is passed explicitly because discord.py falls
    back to this docstring for it, and Discord refuses a group
    description over 100 characters -- a failed `tree.sync()` out of
    `setup_hook`, so the bot does not start at all. `commands.GroupCog`
    is last, as in `cogs/d12ball/`.
    """

    def __init__(self, bot: commands.Bot) -> None:
        commands.GroupCog.__init__(self)
        self.bot = bot
        #: None until `cog_load` reads the data, and after it if the
        #: data could not be read.
        self.catalog: Optional[Catalog] = None

    async def cog_load(self) -> None:
        try:
            self.catalog = load()
        except (CatalogError, OSError) as error:
            # ERROR: somebody has to put the data back. Never raised,
            # so fool-bot's other cogs load regardless.
            LOGGER.error("TNP's data did not load; /tnp answers that it is unavailable: %s", error)
            self.catalog = None
        except Exception:
            LOGGER.exception("TNP's data did not load; /tnp answers that it is unavailable.")
            self.catalog = None

    async def cog_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        original = getattr(error, "original", error)
        command = interaction.command.qualified_name if interaction.command else "unknown command"
        LOGGER.error("Unhandled error in /%s: %r", command, original, exc_info=original)
        message = "Something went wrong running that command. Please try again."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.HTTPException:
            pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Tnp(bot))


__all__ = ["Tnp", "UNAVAILABLE", "setup"]
