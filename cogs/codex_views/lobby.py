"""
`LobbyView`: the lobby `/codex lobby` posts -- **Play Bashing**, **Play
Finesse**, **Leave** and **Start** -- persistent, so a restart re-arms it
(docs/codex-bot.md, decision 10). Every move is a service method over the
record's rule; the view changes nothing itself and saves nothing.
"""

import discord

from codex.game import GameStatus, RuleRefusal
from cogs.codex_views.base import SafeView, send_ephemeral


class LobbyView(SafeView):
    """
    The lobby's four buttons, custom_ids fixed and carrying the game id.
    Start is either seated player's -- or a game helper's: a lobby is
    where a helper is expected to press things for people, so nothing
    here asks for a confirmation.
    """

    confirms_helper_clicks = False

    def __init__(self, cog, game_id: str) -> None:
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id
        for label, action, style in (
            ("Play Bashing", "bashing", discord.ButtonStyle.primary),
            ("Play Finesse", "finesse", discord.ButtonStyle.primary),
            ("Leave", "leave", discord.ButtonStyle.secondary),
            ("Start", "start", discord.ButtonStyle.success),
        ):
            button = discord.ui.Button(
                label=label, style=style, custom_id=f"codex:lobby:{action}:{game_id}",
            )
            button.callback = self._callback(action)
            self.add_item(button)

    def _callback(self, action: str):
        async def callback(interaction: discord.Interaction) -> None:
            if action == "start":
                await self.start(interaction)
            elif action == "leave":
                await self.move(interaction, lambda: self.cog.service.leave(
                    self.game_id, interaction.user.id))
            else:
                await self.move(interaction, lambda: self.cog.service.take_seat(
                    self.game_id, interaction.user.id, interaction.user.display_name, action))
        return callback

    async def move(self, interaction: discord.Interaction, change) -> None:
        """A seat taken or given up: the service's, then the lobby's text
        edited in place -- the click's own response, which costs nothing
        out of the channel's edit bucket."""
        game = self.cog.games.get(self.game_id)
        if game is None or game.status is not GameStatus.LOBBY:
            await send_ephemeral(interaction, "This lobby is closed.")
            return
        try:
            change()
        except RuleRefusal as refused:
            await send_ephemeral(interaction, str(refused))
            return
        await interaction.response.edit_message(
            content=self.cog.lobby_text(game), view=LobbyView(self.cog, self.game_id),
        )

    async def start(self, interaction: discord.Interaction) -> None:
        game = self.cog.games.get(self.game_id)
        if game is None or game.status is not GameStatus.LOBBY:
            await send_ephemeral(interaction, "This lobby is closed.")
            return
        if not self.may_act_in_game(interaction, game):
            await send_ephemeral(interaction, "Only a seated player can start the game.")
            return
        if not game.may_start():
            await send_ephemeral(interaction, "Both seats have to be taken before the game can start.")
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        await self.cog.start_game(interaction, game)
