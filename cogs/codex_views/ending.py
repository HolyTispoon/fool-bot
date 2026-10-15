"""
The views of a game's end (docs/codex-bot.md, step 8; docs/design/codex.md,
"The end of a game"): `ConcedeConfirmView`, the second click a
concession asks, ephemeral to the player conceding -- `TeamConcedeView`,
a two-headed dragon's teammate's agreement, in public -- and `RematchView`,
**Rematch** under the finished game's last public line, persistent, so a
restart re-arms it while no rematch has been opened.

Who may concede is the clicker's own side alone (no helper concedes for
anybody); the rematch is either player's, or a game helper's, as the
lobby's Start is. What a concession does and what a rematch holds are the
service's (`GameService.concede`, `GameService.rematch`); the views change
nothing themselves and save nothing.
"""

import discord

from codex.game import GameStatus
from cogs.codex_helpers import seat_label
from cogs.codex_views.base import SafeView, edit_clicked, send_ephemeral

#: How long the concession's confirmation stays up.
CONCEDE_TIMEOUT = 300


class ConcedeConfirmView(SafeView):
    """
    **Concede** pressed once: the second click it asks, on an ephemeral
    message only the player conceding sees -- **Concede the game** or
    **Cancel**. Holds the seat it was asked for, so a test game's one
    person concedes the side whose turn it was when they asked.
    """

    def __init__(self, cog, game_id: str, seat: int, user_id: int) -> None:
        super().__init__(timeout=CONCEDE_TIMEOUT)
        self.cog = cog
        self.game_id = game_id
        self.seat = seat
        self.user_id = user_id
        confirm = discord.ui.Button(label="Concede the game", style=discord.ButtonStyle.danger)
        confirm.callback = self.confirm
        cancel = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary)
        cancel.callback = self.cancel
        self.add_item(confirm)
        self.add_item(cancel)

    async def confirm(self, interaction: discord.Interaction) -> None:
        game = self.cog.games.get(self.game_id)
        if game is None or game.status is not GameStatus.PLAYING:
            await interaction.response.edit_message(content="This game is already over.", view=None)
            return
        if interaction.user.id != self.user_id or self.seat not in game.seats_of(interaction.user.id):
            await send_ephemeral(interaction, "Only the player conceding can confirm it.")
            return
        self.stop()
        await self.cog.concede(interaction, game, self.seat)

    async def cancel(self, interaction: discord.Interaction) -> None:
        self.stop()
        await interaction.response.edit_message(content="Not conceded: the game goes on.", view=None)


class TeamConcedeView(SafeView):
    """
    A two-headed dragon's concession, asked of the teammate in public
    once the first player has confirmed theirs (decision 15: a concession
    needs both teammates): **Agree** is the teammate's -- or a game
    helper's, behind the helper's confirmation -- and never the asker's;
    **Refuse** is either teammate's. Modelled on `UndoConfirmView`, and
    like it not persistent: after a restart the asker asks again.
    """

    acknowledges_while_waiting = True  # as the panel's (`PanelView`)

    def __init__(self, cog, game_id: str, asker: int, mate: int) -> None:
        super().__init__(timeout=CONCEDE_TIMEOUT)
        self.cog = cog
        self.game_id = game_id
        self.asker = asker
        self.mate = mate
        agree = discord.ui.Button(label="Agree: concede the game", style=discord.ButtonStyle.danger)
        agree.callback = self.agree
        refuse = discord.ui.Button(label="Refuse", style=discord.ButtonStyle.secondary)
        refuse.callback = self.refuse_concession
        self.add_item(agree)
        self.add_item(refuse)

    async def agree(self, interaction: discord.Interaction) -> None:
        game = self.cog.games.get(self.game_id)
        if game is None or game.status is not GameStatus.PLAYING:
            await edit_clicked(interaction, content="This game is already over.", view=None)
            return
        seats = game.seats_of(interaction.user.id)
        if self.mate not in seats:
            if self.asker in seats:
                await send_ephemeral(interaction, "Your teammate has to agree to this.")
                return
            if not self.may_act_for(interaction, game, self.mate):
                await send_ephemeral(
                    interaction,
                    "Only the teammate, or a helper with Manage Channels, can agree to this.",
                )
                return
        self.stop()
        await self.cog.concede_for_team(interaction, game, self.asker, self.mate)

    async def refuse_concession(self, interaction: discord.Interaction) -> None:
        game = self.cog.games.get(self.game_id)
        if game is None:
            return
        seats = game.seats_of(interaction.user.id)
        refusing = next((seat for seat in (self.mate, self.asker) if seat in seats), None)
        if refusing is None:
            await send_ephemeral(interaction, "Only the two teammates can refuse this.")
            return
        self.stop()
        name = seat_label(game, refusing)
        await edit_clicked(interaction, content=f"The concession was refused by {name}: the game goes on.",
                           view=None)


class RematchView(SafeView):
    """
    **Rematch** under a finished game's last line: a new lobby in the
    same channel with the same two seats, the heroes swapped unless both
    press **Keep heroes** there. Persistent -- the custom id carries the
    finished game's id -- and taken off the message once pressed.
    """

    confirms_helper_clicks = False

    def __init__(self, cog, game_id: str) -> None:
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id
        button = discord.ui.Button(
            label="Rematch", style=discord.ButtonStyle.success,
            custom_id=f"codex:rematch:{game_id}",
        )
        button.callback = self.rematch
        self.add_item(button)

    async def rematch(self, interaction: discord.Interaction) -> None:
        game = self.cog.games.get(self.game_id)
        if game is None or game.status is not GameStatus.FINISHED:
            await send_ephemeral(interaction, "Only a finished game can be played again.")
            return
        if not self.may_act_in_game(interaction, game):
            await send_ephemeral(interaction, "Only the game's players can ask for a rematch.")
            return
        await self.cog.open_rematch(interaction, game)
