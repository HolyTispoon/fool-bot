"""
`SafeView`, which every Codex view subclasses: the game's lock around a
click's whole answer, the error surfaced instead of swallowed, the
lookups, the gates, and `apply` -- the one call a click makes, through
`GameService` (copied from `cogs/d12ball_views/base.py`; docs/codex-bot.md,
decision 2).

It imports from no sibling, which keeps the package a DAG.

**The helper's confirmation is not here yet.** D12 Ball puts a game
helper's click for a coach behind Confirm/Cancel; in step 3 no Codex
button acts for a player but the lobby's, where a helper is expected to
press things and nothing asks (`confirms_helper_clicks = False`). Every
other gate lets the seated players alone through until step 4 brings
the panel and the confirmation with it.
"""

import logging
from typing import Optional

import discord

from codex.components import MatchState
from codex.game import CodexGame, RuleRefusal
from codex.prompts import Action
from cogs.game_auth import may_act_in_game as user_may_act_in_game
from gamelocks import GameLocks
from gamesaves.codex.service import GameResult

LOGGER = logging.getLogger(__name__)

#: What a click that failed is told, beside what went wrong.
ERROR_RECOVERY_ADVICE = (
    "If trying again doesn't work, `/codex resume` puts the table back up. "
    "If that doesn't help either, let the bot developer know."
)


async def send_ephemeral(interaction: discord.Interaction, message: str) -> None:
    """Tell the person who clicked, privately, whether or not the click
    has been answered yet; a failure to say so is swallowed."""
    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except discord.HTTPException:
        pass


class SafeView(discord.ui.View):
    """
    Base class for every Codex view. Every subclass carries `self.cog`
    and `self.game_id`, set before anything below is called.
    """

    game_id: Optional[str] = None
    #: Whether a game helper's click for a player is put behind a
    #: confirmation; the lobby turns it off. Until step 4 builds the
    #: confirmation, a view that would ask lets the players alone through.
    confirms_helper_clicks = True

    async def _scheduled_task(self, item: discord.ui.Item, interaction: discord.Interaction) -> None:
        """Every click on this game, one at a time, holding the game's
        lock (`gamelocks.py`) -- around everything the callback puts up,
        not only the apply."""
        locks = getattr(self.cog, "locks", None)
        if not isinstance(locks, GameLocks) or self.game_id is None:
            await super()._scheduled_task(item, interaction)
            return
        async with locks.hold(self.game_id):
            await super()._scheduled_task(item, interaction)

    async def on_error(self, interaction: discord.Interaction, error: Exception,
                       item: discord.ui.Item) -> None:
        LOGGER.error("Unhandled error in %r for %r: %r", self, item, error, exc_info=error)
        await send_ephemeral(
            interaction, f"Something went wrong handling that click. {ERROR_RECOVERY_ADVICE}",
        )

    def load_match(self) -> tuple[Optional[CodexGame], Optional[MatchState]]:
        """`(game, match)`, or `(game, None)` before Start, or
        `(None, None)` when the game is gone. Silent."""
        game = self.cog.games.get(self.game_id)
        if game is None:
            return None, None
        if game.match_state is None:
            return game, None
        return game, self.cog.service.load(game)

    async def require_match(self, interaction: discord.Interaction) -> tuple[Optional[CodexGame], Optional[MatchState]]:
        game, match = self.load_match()
        if match is None:
            await send_ephemeral(interaction, "I could not find the saved data for this game.")
            return None, None
        return game, match

    def seat_of(self, interaction: discord.Interaction, game: CodexGame) -> Optional[int]:
        """The seat the clicker holds, or None."""
        return game.seat_of(interaction.user.id)

    def may_act_in_game(self, interaction: discord.Interaction, game: CodexGame) -> bool:
        """Either player -- or, where this view asks no confirmation, a
        game helper (`cogs.game_auth.may_act_in_game`)."""
        if game.seat_of(interaction.user.id) is not None:
            return True
        return not self.confirms_helper_clicks and user_may_act_in_game(interaction.user, game)

    async def refuse(self, interaction: discord.Interaction, reason: str) -> None:
        await send_ephemeral(interaction, reason)

    async def apply(self, interaction: discord.Interaction, game: CodexGame,
                    action: Action) -> Optional[GameResult]:
        """
        Apply what the person did, through `GameService` -- **the one
        door every click goes through**. A refusal is told to the person
        who clicked and `None` comes back. Authorisation comes before
        this and is not here.
        """
        try:
            result = self.cog.service.apply_action(game.game_id, action)
        except RuleRefusal as error:
            await send_ephemeral(interaction, str(error))
            return None
        if result.refused:
            await self.refuse(interaction, self.cog.render_text(result.refusal, game))
            return None
        return result

    async def answer(self, interaction: discord.Interaction, game: CodexGame,
                     action: Action) -> Optional[GameResult]:
        """`apply`, then what it changed put up by `cog.present`."""
        result = await self.apply(interaction, game, action)
        if result is not None:
            await self.cog.present(game, result)
        return result
