"""
`/codex lobby` and what Start does (docs/codex-bot.md, decision 10): the
lobby is posted in the channel the command is called in, and Start
makes the game's channel, deals, and posts the first turn's message.
"""

from __future__ import annotations

import logging

import discord
from discord import app_commands

from codex import tokens
from codex.game import CodexGame, RuleRefusal
from cogs.codex_views import LobbyView, send_ephemeral

LOGGER = logging.getLogger(__name__)

#: The seats, by spec, as the lobby names them.
SPEC_HEROES = {"bashing": "Troq Bashar", "finesse": "River Montoya"}


class LobbyMixin:
    def lobby_text(self, game: CodexGame) -> str:
        """The lobby's text: who sits where, and what Start waits on."""
        rows = []
        for spec in ("bashing", "finesse"):
            seat = next((held for held, chosen in game.player_specs.items() if chosen == spec), None)
            name = game.seat_name(seat) if seat is not None else None
            rows.append(f"**{spec.title()}** ({SPEC_HEROES[spec]}): {name or '*open*'}")
        waiting = (
            "Both seats are taken: either player may **Start**."
            if game.may_start() else "Take a seat to play."
        )
        head = self.render_text(f"{tokens.codex()} **Codex game {game.game_number}** -- the basic game, Bashing against Finesse.")
        return "\n".join([head.strip(), *rows, waiting])

    @app_commands.command(name="lobby", description="Open a Codex lobby in this channel: two seats, then Start.")
    async def lobby(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await send_ephemeral(interaction, "A Codex game is played in a server's channel.")
            return
        await self.tokens.refresh()
        game = self.service.create_game(guild_id=interaction.guild.id, channel_id=interaction.channel_id)
        try:
            await interaction.response.send_message(
                self.lobby_text(game), view=LobbyView(self, game.game_id),
            )
            message = await interaction.original_response()
        except discord.HTTPException:
            self.service.discard_game(game.game_id)
            raise
        game.message_id = message.id
        self.service.save()

    async def start_game(self, interaction: discord.Interaction, game: CodexGame) -> None:
        """
        Start: the channel first, so a refusal leaves the lobby as it
        was; then the service deals and runs the first turn's start, and
        the first turn's message is posted and pinned in the new channel;
        the lobby is edited once to say where the game is. The click has
        been deferred, so every answer here is a followup.
        """
        try:
            channel = await self.create_game_channel(interaction.guild, game)
        except ValueError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return
        try:
            result = self.service.start(game.game_id)
        except RuleRefusal as refused:
            await interaction.followup.send(str(refused), ephemeral=True)
            try:
                await channel.delete(reason="The Codex game did not start")
            except discord.HTTPException:
                pass
            return
        lobby_channel_id, lobby_message_id = game.channel_id, game.message_id
        game.channel_id = channel.id
        self.service.save()
        self.turn_lines[game.game_id] = list(result.lines)
        await self.post_turn_message(channel, game)
        await interaction.followup.send(f"The game is on: {channel.mention}", ephemeral=True)

        lobby_channel = self.bot.get_channel(lobby_channel_id) if lobby_channel_id else None
        if lobby_channel is not None and lobby_message_id is not None:
            try:
                await lobby_channel.get_partial_message(lobby_message_id).edit(
                    content=self.lobby_text(game) + f"\nThe game is being played in {channel.mention}.",
                    view=None,
                )
            except discord.HTTPException:
                pass
