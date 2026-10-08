"""
The game's slash commands besides the lobby: `/codex games`,
`/codex board`, `/codex hand` and `/codex resume` (docs/codex-bot.md,
decision 10). Each answers ephemerally where it shows anything, so none
of them spends the channel's edit bucket -- but `/codex resume`, which
re-posts the table.
"""

from __future__ import annotations

import logging

import discord
from discord import app_commands

from codex.game import GameStatus, RuleRefusal
from cogs.codex.turns import split_at_turn_end
from cogs.codex_helpers import is_game_helper
from cogs.codex_views import NOT_YOUR_TABLE, send_ephemeral

LOGGER = logging.getLogger(__name__)

NO_GAME_HERE = "No Codex game is being played in this channel."


class SlashCommandsMixin:
    @app_commands.command(name="games", description="List this server's Codex games.")
    async def games_command(self, interaction: discord.Interaction) -> None:
        guild_id = interaction.guild.id if interaction.guild else None
        games = sorted(
            (game for game in self.games.values() if game.guild_id == guild_id),
            key=lambda game: game.game_number,
        )
        if not games:
            await send_ephemeral(interaction, "No Codex games in this server yet: `/codex lobby` opens one.")
            return
        lines = []
        for game in games[-20:]:
            players = " vs ".join(
                name for name in (game.player_1_name, game.player_2_name) if name
            ) or "nobody seated"
            where = f" in <#{game.channel_id}>" if game.channel_id else ""
            lines.append(f"**{game.game_number}** -- {game.status.value}: {players}{where}")
        await send_ephemeral(interaction, "\n".join(lines))

    @app_commands.command(name="board", description="Show this channel's Codex board, to you alone.")
    async def board(self, interaction: discord.Interaction) -> None:
        game = self.game_for_channel(interaction.channel_id)
        if game is None:
            await send_ephemeral(interaction, NO_GAME_HERE)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        png = await self.render_match_png(game)
        await interaction.followup.send(file=self.match_file_from_png(game, png), ephemeral=True)

    @app_commands.command(name="hand", description="Show your hand and discard pile in this channel's game.")
    async def hand(self, interaction: discord.Interaction) -> None:
        game = self.game_for_channel(interaction.channel_id)
        if game is None:
            await send_ephemeral(interaction, NO_GAME_HERE)
            return
        seat = game.seat_of(interaction.user.id)
        if seat is None:
            await send_ephemeral(interaction, NOT_YOUR_TABLE)
            return
        await self.send_hand(interaction, game, self.service.load(game), seat)

    @app_commands.command(name="resume", description="Put this channel's Codex table back up: the board and its buttons.")
    async def resume(self, interaction: discord.Interaction) -> None:
        """
        Run any step the bot owes, then re-post the turn message -- the
        board, the turn's lines and the buttons -- pinned, the old one
        unpinned; and put up, afresh and ephemerally, what the clicker is
        asked: the panel for the active player, the tech picker for the
        other while their choice is open. Either player's, or a game
        helper's.
        """
        game = self.game_for_channel(interaction.channel_id)
        if game is None or game.status is not GameStatus.PLAYING:
            await send_ephemeral(interaction, NO_GAME_HERE)
            return
        if game.seat_of(interaction.user.id) is None and not is_game_helper(interaction.user):
            await send_ephemeral(interaction, "Only the players, or a helper with Manage Channels, can resume this game.")
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.locks.hold(game.game_id):
            try:
                before = self.service.load(game)
                found, result = self.service.resume(game.game_id)
            except RuleRefusal as refused:
                await interaction.followup.send(str(refused), ephemeral=True)
                return
            match = result.match
            _, _, opening, ended = split_at_turn_end(result)
            if ended or match.turn != before.turn:
                self.turn_lines[game.game_id] = opening
            else:
                self.note_lines(game, result)
                self.turn_lines.setdefault(game.game_id, [])
            if match.phase == "main" and before.phase != "main":
                self.note_turn_head(game, match)
            await self.post_turn_message(interaction.channel, game, match)
            await interaction.followup.send(f"Picked up at {found}: the table is re-posted.", ephemeral=True)
            seat = game.seat_of(interaction.user.id)
            if seat is not None and match.winner is None:
                if seat == match.active and self.prompt_for(game, match, seat) is not None:
                    await self.show_panel(interaction, game, match, seat, edit=False)
                elif seat != match.active and self.standing_for(game, match, seat) is not None:
                    await self.show_panel(interaction, game, match, seat, edit=False, standing=True)
