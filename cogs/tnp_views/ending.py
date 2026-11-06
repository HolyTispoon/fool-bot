"""
The end of a TNP game's views (docs/design/tnp.md, "The end of a
game"): `ConcedeConfirmView`, the second click `/tnp concede` asks for,
and `RematchView`, **Rematch** on a finished game's table.

- **Concede is the clicker's own seat, behind a second click.** The
  command answers privately with a button a seat the clicker holds --
  both, in a test game -- and **Cancel**; nobody concedes for anybody
  else, a helper included. Not persistent: it is a moment's question.
- **Rematch** is either player's or a game helper's, as the lobby's
  **Start** is. Persistent, re-armed on a finished game's table at
  startup until a rematch is opened from it.

No view saves: each click is a service method, through the cog.
"""

from __future__ import annotations

import discord

from cogs.tnp_views.base import SafeView, send_ephemeral
from tnp.game import GameStatus

#: How long the second click of a concession waits.
CONCEDE_TIMEOUT = 300


class ConcedeConfirmView(SafeView):
    """**Concede as Blue** (and as Green, in a test game) or **Cancel**,
    to the person who asked alone."""

    def __init__(self, cog, game_id: str, user_id: int, seats) -> None:
        super().__init__(timeout=CONCEDE_TIMEOUT)
        self.cog = cog
        self.game_id = game_id
        self.user_id = user_id
        for seat in seats:
            button = discord.ui.Button(label=f"Concede as {seat.title()}", style=discord.ButtonStyle.danger)
            button.callback = self.conceder(seat)
            self.add_item(button)
        cancel = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary)
        cancel.callback = self.cancel
        self.add_item(cancel)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False
        if interaction.user.id != self.user_id:
            await send_ephemeral(interaction, "This question is somebody else's.")
            return False
        return True

    def conceder(self, seat: str):
        async def concede(interaction: discord.Interaction) -> None:
            await self.cog.concede_seat(interaction, self.game_id, seat)
        return concede

    async def cancel(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(content="Not conceded: the game goes on.", view=None)


class RematchView(SafeView):
    """**Rematch** on a finished game's table: a new lobby with the same
    seats, in the same place."""

    def __init__(self, cog, game_id: str) -> None:
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id
        button = discord.ui.Button(
            label="Rematch", style=discord.ButtonStyle.success, custom_id=f"tnp:rematch:{game_id}",
        )
        button.callback = self.rematch
        self.add_item(button)

    async def rematch(self, interaction: discord.Interaction) -> None:
        game = self.game()
        if game is None or game.status is not GameStatus.FINISHED:
            await send_ephemeral(interaction, "Only a finished game can be played again.")
            return
        if not self.may_act_in_game(interaction, game):
            await send_ephemeral(interaction, "Only this game's players, or a helper, can open its rematch.")
            return
        await self.cog.open_rematch(interaction, game)


__all__ = ["CONCEDE_TIMEOUT", "ConcedeConfirmView", "RematchView"]
