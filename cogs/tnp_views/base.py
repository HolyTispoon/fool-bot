"""
`SafeView`, which every TNP view subclasses: the game's lock around a
click's whole answer (`botkit.views.GameLockedView`'s, shared with
D12 Ball and Codex), an error logged and told rather than swallowed,
the lookups, and the gates, which are `cogs/game_auth.py`'s
(docs/design/permissions.md). Modelled on `cogs/codex_views/base.py`.

It imports from no sibling, which keeps the package a DAG. **No view
saves**: every change is a service method or `GameService.apply_action`.
"""

from __future__ import annotations

import logging
from typing import Optional

import discord

from botkit.views import GameLockedView
from cogs.game_auth import may_act_in_game as user_may_act_in_game
from cogs.tnp_helpers import UNAVAILABLE
from tnp.game import TnpGame

LOGGER = logging.getLogger(__name__)

#: What a click that failed is told, beside what went wrong.
ERROR_RECOVERY_ADVICE = (
    "If trying again doesn't work, `/tnp resume` puts the table back up. "
    "If that doesn't help either, let the bot developer know."
)


async def send_ephemeral(interaction: discord.Interaction, message: str, **fields) -> None:
    """Tell the person who clicked, privately, whether or not the click
    has been answered yet; a failure to say so is swallowed."""
    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True, **fields)
        else:
            await interaction.response.send_message(message, ephemeral=True, **fields)
    except discord.HTTPException:
        pass


class SafeView(GameLockedView):
    """
    Base class for every TNP view. Every subclass carries `self.cog` and
    `self.game_id`, set before a click arrives.
    """

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """A click while TNP's data has not loaded is told so, and runs
        nothing (decision 2)."""
        if self.cog.service is None:
            await send_ephemeral(interaction, UNAVAILABLE)
            return False
        return True

    async def on_error(self, interaction: discord.Interaction, error: Exception,
                       item: discord.ui.Item) -> None:
        # The view's class, the item's kind and the game -- never the
        # item itself: a panel's labels will name a seat's own units
        # (the preamble's hidden-information rule).
        LOGGER.error(
            "Unhandled error in %s (a %s) on TNP game %s: %r",
            type(self).__name__, type(item).__name__, self.game_id, error, exc_info=error,
        )
        await send_ephemeral(
            interaction, f"Something went wrong handling that click. {ERROR_RECOVERY_ADVICE}",
        )

    def game(self) -> Optional[TnpGame]:
        return self.cog.games.get(self.game_id)

    def seats_of(self, interaction: discord.Interaction, game: TnpGame) -> tuple[str, ...]:
        """The seats the clicker holds: both in a test game, none for a
        watcher."""
        return game.seats_of(interaction.user.id)

    def may_act_in_game(self, interaction: discord.Interaction, game: TnpGame) -> bool:
        """Either player, or a game helper (`cogs.game_auth.may_act_in_game`,
        which reads the permission with `is True`)."""
        if game.seat_of(interaction.user.id) is not None:
            return True
        return user_may_act_in_game(interaction.user, game)
