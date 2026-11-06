"""
The New Project's Discord frontend: every slash command under `/tnp`,
in fool-bot, under its token (docs/tnp-bot.md, decision 2).

`Tnp` is assembled from mixins, as `cogs/d12ball/` and `cogs/codex/`
are (docs/design/cog-structure.md): `core` (the games, the engine, the
service and the locks, the tokens, the startup sweep), `lobby`
(`/tnp create_game`, the hub's **TNP** button's `open_lobby`, Start),
`table` (the game's channel, the table, `/tnp resume`), `turns` (each
seat's panel and its controls, the answers, what a turn posts, the
table through the write gate) and `reference` (`/tnp unit`, `/tnp rules`). Nothing in
it decides a rule: it asks `tnp/` and posts the answer.

**An exception here stays here** (decision 2): `cog_load` reads the
data and logs, never raises, when it is missing, so a broken TNP
cannot stop fool-bot from loading D12 Ball; the commands then say TNP
is unavailable. The games file is read the same way: a game that
cannot be read is logged and skipped. See docs/design/tnp.md.
"""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from cogs.tnp.battles import BattleMixin
from cogs.tnp.core import CoreMixin
from cogs.tnp.lobby import LobbyMixin
from cogs.tnp.reference import ReferenceMixin
from cogs.tnp.table import TableMixin
from cogs.tnp.turns import TurnMixin
from cogs.tnp_helpers import UNAVAILABLE

LOGGER = logging.getLogger(__name__)


class Tnp(
    CoreMixin,
    LobbyMixin,
    TableMixin,
    TurnMixin,
    BattleMixin,
    ReferenceMixin,
    commands.GroupCog,
    group_name="tnp",
    group_description="The New Project: its games, its units and its rules.",
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
        self.setup_state()

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
