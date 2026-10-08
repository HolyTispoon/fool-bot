"""
The Codex bot's Discord frontend: every slash command under `/codex`.

`Codex` is assembled from mixins, as `cogs/d12ball/` is
(docs/design/cog-structure.md); in step 1 of docs/codex-bot.md there is
one, `reference` -- `/codex card` and `/codex rules`. Nothing in it
decides a rule: it asks `codex/` and renders the answer.
"""

from discord.ext import commands

from cogs.codex.reference import ReferenceMixin
from cogs.codex_helpers import CodexTokens


class Codex(
    ReferenceMixin,
    commands.GroupCog,
    group_name="codex",
    group_description="Play Codex -- one game per channel.",
):
    """
    A Discord cog for Sirlin Games' Codex.

    `group_description` is passed explicitly because discord.py falls
    back to this docstring for it, and Discord refuses a group
    description over 100 characters -- a failed `tree.sync()` out of
    `setup_hook`, so the bot does not start at all.
    """

    def __init__(self, bot: commands.Bot) -> None:
        super().__init__()
        self.bot = bot
        self.tokens = CodexTokens(bot)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Codex(bot))

__all__ = ["Codex", "setup"]
