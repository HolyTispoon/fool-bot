"""
The Codex bot's Discord frontend: every slash command under `/codex`.

`Codex` is assembled from mixins, as `cogs/d12ball/` is
(docs/design/cog-structure.md): `core` (lifecycle, lookups, the
`service` property, `DiscordBatching`, `render_prompt`,
`view_for_prompt`, the turn message's text), `turns` (`present`, the
panel, the turn's rollover, the finished game, the two undos), `lobby`
(`/codex start_game` and what Start does), `ending` (Concede,
`/codex abandon`, Rematch, the channel archived, `/codex admin
reset_channels`), `presentation` (the board, the channel, the turn
message, a hand),
`slash_commands` (`/codex games`, `board`, `hand`, `resume`) and
`reference` (`/codex card`, `/codex rules`). Nothing in it decides a
rule: it asks `codex/` and renders the answer.
"""

from discord.ext import commands

from cogs.codex.core import CoreMixin
from cogs.codex.ending import EndingMixin
from cogs.codex.lobby import LobbyMixin
from cogs.codex.presentation import PresentationMixin
from cogs.codex.reference import ReferenceMixin
from cogs.codex.slash_commands import SlashCommandsMixin
from cogs.codex.turns import TurnsMixin


class Codex(
    CoreMixin,
    TurnsMixin,
    EndingMixin,
    LobbyMixin,
    PresentationMixin,
    SlashCommandsMixin,
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
    `setup_hook`, so the bot does not start at all. `commands.GroupCog`
    is last, as in `cogs/d12ball/`.
    """

    def __init__(self, bot: commands.Bot) -> None:
        commands.GroupCog.__init__(self)
        CoreMixin.__init__(self, bot)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Codex(bot))

__all__ = ["Codex", "setup"]
