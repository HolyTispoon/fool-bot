"""
The three ways possession changes hands: the run back after a steal,
the time out that buys both coaches a Coaching Choice, and the pickup
after a ball has gone out. See "Turnovers: steals and new plays" and
"The time out" in docs/design/time-out.md.
"""

import asyncio
import discord
import io

from d12ball.components import MatchState, TeamSide
from d12ball.game import D12BallGame
from d12ball.render import render_coaching_image


class TurnoverMixin:
    """
    The three ways possession changes hands: the run back after a steal,
    """

    async def coaching_file(
        self,
        game: D12BallGame,
        match: MatchState,
        side: TeamSide,
    ) -> discord.File:
        """
        The coach's own half of the field, as an attachment for their
        Coaching Choice message. Rendered in a worker thread like every
        other image: Pillow is pure CPU and the event loop is shared by
        every game at once.

        **This is the Coaching Choice's picture and nothing else's.**
        It shows one side's row and leaves the ball off, which is right
        for arranging your own team with play stopped and wrong for
        reading a live position -- the prompts that ask about one carry
        the field strip instead, through `send_field_prompt`.
        """
        png = await asyncio.to_thread(
            render_coaching_image,
            match,
            self.player_catalog,
            side,
            self.engine.coaching_title(match, side),
            species_icons=self.engine.species_abilities_apply(game),
            cyborg_ids=self.engine.cyborg_condition_ids(game, match),
        )
        return discord.File(
            io.BytesIO(png.getvalue()),
            filename=f"d12ball-coaching-{game.game_number}.png",
        )


    async def resume_game(
        self,
        interaction: discord.Interaction,
        game: D12BallGame,
    ) -> str:
        """
        Put the game back in front of whoever it is waiting on, and say
        what that was -- `GameService.resume`, presented. See
        `/d12ball resume`, and "Recovering a stuck game" in
        docs/design/recovery.md.

        A restart only ever re-arms **one** message per game, the one
        recorded in `turn_message_id`, so a game that lost that message
        comes back with nothing live in its channel. The service runs
        whatever step the bot itself owed and hands back the prompt;
        `present` posts a fresh one, with its picture.
        """
        waiting_on, result = self.service.resume(game.game_id)
        await self.present_result(interaction, game, result)
        return waiting_on
