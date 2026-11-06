"""
`/tnp create_game`, the hub's **TNP** button, and what Start does
(docs/design/tnp.md, "The lobby, the channel and the table"): both open
the game's own channel, `tnp-<n>` under **TNP Games** -- or, where the
bot may not make one, a public thread of that name -- and post the
lobby in it with the person who asked already in the Blue seat; Start
renames that channel for its players, `tnp-<n>-<blue>-vs-<green>`, deals
the opening position (TNP 3), and posts the table under the lobby.
"""

from __future__ import annotations

import logging

import discord
from discord import app_commands

from cogs.tnp_helpers import UNAVAILABLE, seat_word
from cogs.tnp_views import send_ephemeral
from tnp.game import SEAT_NAMES, GameStatus, RuleRefusal, TnpGame

LOGGER = logging.getLogger(__name__)

#: What the person who asked for the lobby is told, by where it opened.
LOBBY_OPENED = {
    "channel": "Lobby open: {place}",
    "thread": ("Lobby open in a thread: {place}. I could not create a channel for the game "
               "(that needs **Manage Channels**), so it is played in the thread."),
}


class LobbyMixin:
    def lobby_text(self, game: TnpGame) -> str:
        """The lobby's text: the game, who sits where, and what Start
        waits on."""
        which = "the advanced game, with the technology cards" if game.advanced else "the basic game"
        head = f"**TNP game {game.game_number}**: {which}, Humans against Humans."
        if game.test_game:
            head += " A **test game**: one person may take both seats and play both sides."
        rows = []
        for seat in SEAT_NAMES:
            name = game.seats[seat]["name"]
            rows.append(f"**{seat_word(seat)}**: {name if name else '*open*'}")
        if game.status is not GameStatus.LOBBY:
            waiting = "The game has started."
        elif game.full:
            waiting = "Both seats are taken: either player may **Start**."
        else:
            waiting = "Take a seat to play."
        return "\n".join([head, *rows, waiting])

    @app_commands.command(name="create_game", description="Open a TNP lobby in a channel of its own.")
    @app_commands.describe(test_game="A test game: you may take both seats and play both sides")
    async def create_game(self, interaction: discord.Interaction, test_game: bool = False) -> None:
        await self.open_lobby(interaction, test_game=test_game)

    async def open_lobby(self, interaction: discord.Interaction, test_game: bool = False) -> None:
        """
        A lobby in a channel of its own, `tnp-<n>` under TNP Games, open
        to the server -- anyone may look in and take the free seat -- and
        the person who asked sat as Blue. **`/tnp create_game` and the
        hub's TNP button both come here** (the author, 2026-11-05): the
        hub's click is fool-bot's, since TNP is a cog of fool-bot's own
        application. **Where the bot may not make the channel, the game
        is played in a public thread** of that name in the channel the
        lobby was asked for in (the author, 2026-11-06; `open_game_place`).
        The person who asked is told where, privately. Where neither can
        be made, nothing is kept and they are told why.
        """
        guild = interaction.guild
        if guild is None or not isinstance(interaction.user, discord.Member):
            await send_ephemeral(interaction, "A TNP game is played in a server's channel.")
            return
        service = self.service
        if service is None:
            await send_ephemeral(interaction, UNAVAILABLE)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        creator = interaction.user
        game = service.create_game(guild_id=guild.id, test_game=test_game)
        service.take_seat(game.game_id, creator.id, creator.display_name, SEAT_NAMES[0])
        try:
            place, venue, message = await self.open_game_place(interaction, game)
        except ValueError as error:
            service.discard_game(game.game_id)
            await interaction.followup.send(str(error), ephemeral=True)
            return
        game.channel_id, game.venue, game.message_id = place.id, venue, message.id
        service.save()
        await interaction.followup.send(LOBBY_OPENED[venue].format(place=place.mention), ephemeral=True)

    async def start_game(self, interaction: discord.Interaction, game: TnpGame) -> None:
        """
        Start, from the lobby's own channel, the click deferred: the
        service deals the opening position and saves once (refused until
        both seats are taken); the channel is renamed for the players;
        the lobby is edited through the click's own response to say the
        game has started, its buttons gone; and the table goes up under
        it.
        """
        channel = self.bot.get_channel(game.channel_id) if game.channel_id else None
        if channel is None:
            await interaction.followup.send("I cannot find this lobby's channel.", ephemeral=True)
            return
        try:
            self.service.start(game.game_id)
        except RuleRefusal as refused:
            await interaction.followup.send(str(refused), ephemeral=True)
            return
        await self.name_game_channel(channel, game)
        try:
            await interaction.edit_original_response(
                content=self.lobby_text(game), view=None,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException as error:
            LOGGER.warning("Could not close the lobby of TNP game %s: %s", game.game_id, error)
        await self.post_table(channel, game)
