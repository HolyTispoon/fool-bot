"""
`GameLockedView`, the base both bots' `SafeView`s stand on
(`cogs.d12ball_views.base`, `cogs.codex_views.base`): every click on a
game answered one at a time, holding that game's lock. Everything else a
`SafeView` does -- its gates, its error handling, the helper's
confirmation, `apply` through the game's service -- stays each bot's.
"""

from typing import Optional

import discord

from gamelocks import GameLocks


class GameLockedView(discord.ui.View):
    """
    A view whose clicks are ordered per game. A subclass carries
    `self.cog` (whose `locks` is the process's `GameLocks`) and
    `self.game_id`, set before a click arrives.
    """

    # None on a view that belongs to no game -- a hub's.
    game_id: Optional[str] = None

    async def _scheduled_task(
        self,
        item: discord.ui.Item,
        interaction: discord.Interaction,
    ) -> None:
        """
        **Every click on this game, one at a time** -- discord.py's own
        dispatch, run while holding the game's lock (`gamelocks.py`).

        The lock is around the whole callback rather than around
        `apply` alone, because what has to stay in order is not the
        answer -- `GameService.apply_action` is synchronous and cannot
        be interleaved on one event loop -- but everything the callback
        does afterwards: two clicks applied back to back can otherwise
        render, upload and edit in either order, which is a turn
        arriving in a channel out of sequence. Decision 5 of
        docs/web-app.md; the web app takes the same lock over the same
        games, which is the whole reason it is a lock and not an
        ordering convention.

        It overrides discord.py's dispatch because that is the only
        place a callback can be wrapped: `interaction_check` runs
        *before* the callback and cannot hold anything across it.
        `tests/test_game_locks.py` ratchets that the method being
        overridden still exists, so a rename upstream fails the suite
        rather than quietly leaving every click unordered.

        A cog that is a test double holds nothing: there is no game
        loop to order against. Neither does a view with no game (a
        hub's): there is no game for its click to be ordered against,
        and the lobby it opens is a new one.
        """
        locks = getattr(self.cog, "locks", None)
        if not isinstance(locks, GameLocks) or self.game_id is None:
            await super()._scheduled_task(item, interaction)
            return
        async with locks.hold(self.game_id):
            await super()._scheduled_task(item, interaction)
