"""
The board and the channel: the board rendered off the thread
(`codex/render.py` through `asyncio.to_thread`), the gate's one
forwarder, the game's channel, the turn message posted and pinned, and
a player's hand sent to them alone.
"""

from __future__ import annotations

import asyncio
import io
import logging
from typing import Optional

import discord

from codex.game import CodexGame
from codex.render import render_board
from cogs.codex_helpers import (
    BOARD_IMAGE_FILENAME_PREFIX,
    channel_name,
    codex_games_category,
)
from cogs.codex_views import TurnMessageView, hand_caption, hand_file, side_label

LOGGER = logging.getLogger(__name__)


class PresentationMixin:
    async def render_match_png(self, game: CodexGame, match=None) -> bytes:
        """The board as PNG bytes, drawn off the event loop."""
        if match is None:
            match = self.service.load(game)
        return await asyncio.to_thread(
            render_board, match, game.board_layout, self.seat_names(game), self.engine.catalog,
        )

    def match_file_from_png(self, game: CodexGame, png: bytes) -> discord.File:
        return discord.File(
            io.BytesIO(png),
            filename=f"{BOARD_IMAGE_FILENAME_PREFIX}{game.game_number}-board.png",
        )

    async def refresh_match_image(self, game: CodexGame, png: Optional[bytes] = None) -> None:
        """**The one forwarder** over the turn message's write gate."""
        channel = self.bot.get_channel(game.channel_id) if game.channel_id else None
        if channel is None:
            return
        await self.boards.refresh(channel, game, png)

    def bot_access(self) -> discord.PermissionOverwrite:
        """The bot's own place in a game's channel: it writes, pins, and
        manages the channel, to rename it at Start and archive it later."""
        return discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True,
            manage_channels=True, manage_messages=True, attach_files=True,
        )

    def channel_overwrites(self, guild: discord.Guild,
                           bot_member: discord.Member) -> dict:
        """
        A game's channel is open to the whole server, from the lobby to
        the end: anyone may read it and talk in it (the author,
        2026-10-08 -- the hands are ephemeral, so a watcher sees the
        table and nothing more, and may say what they think of it).
        """
        return {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True,
            ),
            bot_member: self.bot_access(),
        }

    async def create_game_channel(self, guild: discord.Guild, game: CodexGame) -> discord.TextChannel:
        """
        The game's channel, made when the lobby opens: `codex-<n>` under
        Codex Games, open to the server. The lobby is posted in it and
        the game is played in it. Every failure is a `ValueError`
        carrying the sentence to show.
        """
        bot_member = guild.me
        try:
            category = await codex_games_category(guild)
            return await guild.create_text_channel(
                name=channel_name(game),
                category=category,
                overwrites=self.channel_overwrites(guild, bot_member),
                reason=f"Codex game {game.game_number}",
            )
        except discord.Forbidden:
            raise ValueError(
                "I do not have permission to create the Codex Games category or its channels."
            )
        except discord.HTTPException as error:
            raise ValueError(f"Discord could not create the channel: {error}")

    async def name_game_channel(self, channel: discord.TextChannel, game: CodexGame) -> None:
        """
        At Start, the lobby's channel is renamed for its players,
        `codex-<n>-<p1>-vs-<p2>`; its permissions stand. A failure is
        logged and the game goes on in the channel either way.
        """
        try:
            await channel.edit(
                name=channel_name(game), reason=f"Codex game {game.game_number} started",
            )
        except discord.HTTPException as error:
            LOGGER.warning("Could not rename the channel of Codex game %s: %s", game.game_id, error)

    async def post_turn_message(self, channel: discord.TextChannel, game: CodexGame) -> discord.Message:
        """
        Post the turn's message -- the board as its picture, the turn's
        lines as its text, the game's buttons -- pin it, and unpin the
        one it replaces: the rollover D12 Ball's board does, so the pin
        is always the current position. The record's new
        `turn_message_id` is saved through the service.
        """
        png = await self.render_match_png(game)
        message = await channel.send(
            self.turn_text(game) or None,
            file=self.match_file_from_png(game, png),
            view=TurnMessageView(self, game.game_id),
            allowed_mentions=discord.AllowedMentions.none(),
        )
        old = game.turn_message_id
        game.turn_message_id = message.id
        self.boards.forget(game)
        self.service.save()
        try:
            await message.pin(reason="The current turn of a Codex game")
        except discord.HTTPException as error:
            LOGGER.warning("Could not pin the turn message of Codex game %s: %s", game.game_id, error)
        if old is not None:
            try:
                await channel.get_partial_message(old).unpin(reason="A newer turn is pinned")
            except discord.HTTPException:
                pass
        return message

    async def send_hand(self, interaction: discord.Interaction, game: CodexGame, match,
                        seat: int) -> None:
        """A player's hand pictured and their discard listed, **ephemeral
        to them alone** -- the first hidden thing the bot shows."""
        await interaction.response.send_message(
            hand_caption(match, seat, side_label(game, match, seat)),
            file=await hand_file(self.engine, match, seat),
            ephemeral=True,
        )
