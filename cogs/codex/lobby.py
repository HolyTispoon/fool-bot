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
from codex.game import CodexGame, GameStatus, RuleRefusal
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
        if game.status is not GameStatus.LOBBY:
            waiting = "The game has started."
        elif game.may_start():
            waiting = "Both seats are taken: either player may **Start**."
        else:
            waiting = "Take a seat to play."
        head = self.render_text(f"{tokens.codex()} **Codex game {game.game_number}** -- the basic game, Bashing against Finesse.")
        if game.test_game:
            head += " A **test game**: one person may take both seats and play both sides."
        return "\n".join([head.strip(), *rows, waiting])

    @app_commands.command(name="lobby", description="Open a Codex lobby in a channel of its own: two seats, then Start.")
    @app_commands.describe(test_game="A test game: you may take both seats and play both sides")
    async def lobby(self, interaction: discord.Interaction, test_game: bool = False) -> None:
        """
        Open the game's channel, `codex-<n>` under Codex Games, and post
        the lobby in it: the game is played where its lobby was, as D12
        Ball's are. The person who asked is told where, privately.
        `test_game` lets one person take both seats and play both sides,
        as D12 Ball's test games do.
        """
        if interaction.guild is None:
            await send_ephemeral(interaction, "A Codex game is played in a server's channel.")
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        await self.tokens.refresh()
        game = self.service.create_game(guild_id=interaction.guild.id, test_game=test_game)
        try:
            channel = await self.create_game_channel(interaction.guild, game)
        except ValueError as error:
            self.service.discard_game(game.game_id)
            await interaction.followup.send(str(error), ephemeral=True)
            return
        try:
            message = await channel.send(self.lobby_text(game), view=LobbyView(self, game.game_id))
        except discord.HTTPException:
            self.service.discard_game(game.game_id)
            try:
                await channel.delete(reason="The Codex lobby could not be posted")
            except discord.HTTPException:
                pass
            raise
        game.channel_id, game.message_id = channel.id, message.id
        self.service.save()
        await interaction.followup.send(f"Lobby open: {channel.mention}", ephemeral=True)

    async def start_game(self, interaction: discord.Interaction, game: CodexGame) -> None:
        """
        Start, in the lobby's own channel: the service deals and runs the
        first turn's start; the channel is renamed for the players and
        closed to everybody else's messages; the lobby is edited once to
        say the game has started, its buttons gone; and the first turn's
        message is posted and pinned under it. The click has been
        deferred, so every answer here is a followup.
        """
        channel = self.bot.get_channel(game.channel_id) if game.channel_id else None
        if channel is None:
            await interaction.followup.send(
                "I cannot find this lobby's channel.", ephemeral=True,
            )
            return
        try:
            result = self.service.start(game.game_id)
        except RuleRefusal as refused:
            await interaction.followup.send(str(refused), ephemeral=True)
            return
        await self.lock_game_channel(channel, game)
        if game.message_id is not None:
            try:
                await channel.get_partial_message(game.message_id).edit(
                    content=self.lobby_text(game), view=None,
                )
            except discord.HTTPException:
                pass
        self.turn_lines[game.game_id] = list(result.lines)
        await self.post_turn_message(channel, game)
        await interaction.followup.send("The game has started.", ephemeral=True)
