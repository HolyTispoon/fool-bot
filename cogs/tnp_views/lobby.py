"""
`LobbyView`: the lobby `/tnp create_game` -- or the hub's **TNP** button
-- posts, rebuilt from the record on every change (docs/design/tnp.md,
"The lobby, the channel and the table"): **Join as Blue**, **Join as
Green**, **Leave**, **Start** and **Test game**; **Basic game** and
**Advanced game**, the advanced greyed out until its technology cards
are built (TNP 8); and under them a button a faction -- **Join as Humans**, the first free seat, and the
XzzzX and the Space Dragons greyed out until their rules come in. Both
seats are people's; there is no AI (TNP 1.2).

Persistent, its custom ids fixed and carrying the game id, so a restart
re-arms it. Every move is a service method over the record's own rule
(`TnpGame.take_seat`, `leave`, `start`), which refuses with
`RuleRefusal`; the view changes nothing itself and saves nothing. A
seat taken or given up edits the lobby through the click's own
response, which spends nothing from the channel's edit bucket.
"""

from __future__ import annotations

import discord

from cogs.tnp_views.base import SafeView, send_ephemeral
from tnp.components import FACTIONS, PLAYABLE_FACTIONS
from tnp.formatting import FACTION_NAMES
from tnp.game import SEAT_NAMES, GameStatus, RuleRefusal


class LobbyView(SafeView):
    """
    The lobby's buttons. A seat is the clicker's own to take or leave;
    **Start** is either seated player's or a game helper's -- a lobby is
    where a helper is expected to press things for people, so nothing
    here asks for a confirmation, as in D12 Ball's and Codex's.
    """

    def __init__(self, cog, game_id: str) -> None:
        super().__init__(timeout=None)
        self.cog = cog
        self.game_id = game_id
        game = self.game()
        test_game = bool(game and game.test_game)
        buttons = [
            *((f"Join as {seat.title()}", f"seat_{seat}", discord.ButtonStyle.primary, 0, False)
              for seat in SEAT_NAMES),
            ("Leave", "leave", discord.ButtonStyle.secondary, 0, False),
            ("Start", "start", discord.ButtonStyle.success, 0, False),
            (f"Test game: {'on' if test_game else 'off'}", "test_game",
             discord.ButtonStyle.success if test_game else discord.ButtonStyle.secondary, 0, False),
            # The game: Advanced greyed out until its technology cards
            # are built (TNP 8, step 9 of docs/tnp-bot.md).
            ("Basic game", "basic", discord.ButtonStyle.success, 1, False),
            ("Advanced game", "advanced", discord.ButtonStyle.secondary, 1, True),
            *((f"Join as {FACTION_NAMES[faction]}", f"join_{faction}", discord.ButtonStyle.primary,
               2, faction not in PLAYABLE_FACTIONS) for faction in FACTIONS),
        ]
        for label, action, style, row, disabled in buttons:
            button = discord.ui.Button(
                label=label, style=style, custom_id=f"tnp:lobby:{action}:{game_id}",
                row=row, disabled=disabled,
            )
            button.callback = self._callback(action)
            self.add_item(button)

    def _callback(self, action: str):
        async def callback(interaction: discord.Interaction) -> None:
            await self.press(interaction, action)
        return callback

    async def press(self, interaction: discord.Interaction, action: str) -> None:
        game = self.game()
        if game is None or game.status is not GameStatus.LOBBY:
            await send_ephemeral(interaction, "This lobby is closed.")
            return
        if action == "start":
            if not self.may_act_in_game(interaction, game):
                await send_ephemeral(interaction, "Only a seated player may start the game.")
                return
            await interaction.response.defer()
            await self.cog.start_game(interaction, game)
            return
        if action in ("test_game", "basic", "advanced") and not self.may_act_in_game(interaction, game):
            await send_ephemeral(interaction, "Only a seated player may change the game's settings.")
            return
        try:
            if action == "leave":
                self.cog.service.leave(game.game_id, interaction.user.id)
            elif action in ("basic", "advanced"):
                self.cog.service.set_advanced(game.game_id, action == "advanced")
            elif action == "test_game":
                self.cog.service.set_test_game(game.game_id, not game.test_game)
            elif action.startswith("join_"):
                if action.removeprefix("join_") not in PLAYABLE_FACTIONS:
                    raise RuleRefusal("That faction cannot be played yet.", cite="TNP 1.2")
                self.cog.service.take_seat(
                    game.game_id, interaction.user.id, interaction.user.display_name,
                )
            else:
                seat = action.removeprefix("seat_")
                self.cog.service.take_seat(
                    game.game_id, interaction.user.id, interaction.user.display_name, seat,
                )
        except RuleRefusal as refused:
            await send_ephemeral(interaction, str(refused))
            return
        await interaction.response.edit_message(
            content=self.cog.lobby_text(game), view=LobbyView(self.cog, game.game_id),
            allowed_mentions=discord.AllowedMentions.none(),
        )
