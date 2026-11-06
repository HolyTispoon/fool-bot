"""
`TableView`: the button under the table, the game's one public message
-- **My board**, which answers the clicker alone, ephemerally, with
each seat they hold: its player board, its pool and what it may do now
(docs/design/tnp.md, "Hidden information on Discord"). A watcher is
told the table is not theirs.

Persistent, its custom id fixed and carrying the game id, re-armed at
startup. It saves nothing and changes nothing: what the panel shows is
`GameService`'s prompts and the model's briefs, filtered for the seat.
"""

from __future__ import annotations

import discord

from cogs.tnp_views.base import SafeView, send_ephemeral
from tnp.game import GameStatus


class TableView(SafeView):
    def __init__(self, cog, game_id: str) -> None:
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id
        board = discord.ui.Button(
            label="My board", style=discord.ButtonStyle.primary,
            custom_id=f"tnp:table:board:{game_id}",
        )
        board.callback = self.my_board
        self.add_item(board)

    async def my_board(self, interaction: discord.Interaction) -> None:
        game = self.game()
        if game is None or game.status is not GameStatus.PLAYING:
            await send_ephemeral(interaction, "This game is not being played.")
            return
        seats = self.seats_of(interaction, game)
        if not seats:
            await send_ephemeral(interaction, "You are watching this game: the boards are its players' alone.")
            return
        await self.cog.send_panels(interaction, game, seats)
