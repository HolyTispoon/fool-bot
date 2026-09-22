"""
The clock and everything hanging off the end of it: the tail of a
maneuver, the period whistle, halftime, the window before the
shootout, and the shootout itself.
"""

import discord

from d12ball.components import (
    MatchState,
    TeamSide,
)
from d12ball.flow.periods import shootout_order_text
from d12ball.game import D12BallGame
from gamesaves.d12ball.storage import save_games
from cogs.d12ball_helpers import (
    add_full_image_button,
    send_new_prompt,
)
from cogs.d12ball_views import RematchView


class PeriodMixin:
    """
    The clock and everything hanging off the end of it: the tail of a
    """

    async def announce_game_over(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
        content: str,
    ) -> None:
        """
        The last message of a game: the result, the board the game
        ended on, and the rematch and archive buttons under it. Both
        endings post it -- the whistle when full time settles the game,
        and the shootout when it does not.

        The final board rides on this message rather than being left to
        the persistent one, for the reason a loose ball's does (see
        announce_board_update): by full time the persistent message has
        scrolled hours up the channel, and the result is exactly the
        thing nobody should have to go looking for the position of. It
        is the same render-once-upload-twice -- the persistent message
        is settled from these bytes -- so the callers no longer refresh
        it themselves. It is deliberately *not* pinned: pinning stays
        the new play's alone, and a pin here would be the one at the
        very bottom of a channel nobody is playing in any more.
        """
        view = RematchView(self, game.game_id)
        png = await self.render_match_png(game)
        final = await send_new_prompt(
            interaction,
            content,
            file=self.match_file_from_png(game, png),
            view=view,
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False,
            ),
        )
        # Handed the view, or the edit that adds the link drops the two
        # buttons this message exists for.
        await add_full_image_button(final, view)
        # Remembered so the buttons come back after a restart: the
        # channel stays where it is until someone clicks one, which can
        # be days later. The turn's own message is forgotten with it --
        # nothing on it is live any more, and a restart re-arms the
        # rematch rather than a question the game has finished with.
        game.rematch_message_id = final.id
        game.turn_message_id = None
        save_games(self.games)
        await self.refresh_match_image(interaction, game, png=png)

    async def begin_setup_coaching(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
    ) -> None:
        """
        The first thing a game runs once setup has settled the teams
        and the sides: `GameService.begin`, presented. Both callers are
        setup views holding only the game.
        """
        await self.present_result(
            interaction, game, self.service.begin(game.game_id),
        )

    def shootout_order_text(
        self,
        game: D12BallGame,
        match: MatchState,
        side: TeamSide,
    ) -> str:
        """
        The order a coach has built so far, on their own menu -- a
        forwarding method over
        `d12ball.flow.periods.shootout_order_text`, kept because the
        two ephemeral menus and the roll prompt's "Your Order" all read
        it from here -- rendered, since the flow names each player
        with tokens.
        """
        return self.render_text(
            shootout_order_text(self.engine, game, match, side), game,
        )

