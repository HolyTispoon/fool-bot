"""
The board and the channel: the board rendered off the thread
(`codex/render.py` through `asyncio.to_thread`), the gate's one
forwarder, the game's channel, the turn message posted -- for a new
turn, or again at the foot of the channel after an action -- a
player's hand sent to them alone as a message of its own and brought
up to date in place (`HandMessage`), and their whole deck.
"""

from __future__ import annotations

import asyncio
import io
import logging
import time
from dataclasses import dataclass
from typing import Optional

import aiohttp
import discord

from codex.game import CodexGame
from codex.render import render_board
from cogs.codex_helpers import (
    BOARD_IMAGE_FILENAME_PREFIX,
    channel_name,
    codex_games_category,
    elapsed_ms,
    pictures_size,
)
from cogs.codex_views import (
    HandView,
    TurnMessageView,
    deck_caption,
    deck_file,
    hand_caption,
    hand_file,
    side_label,
)

LOGGER = logging.getLogger(__name__)


@dataclass
class HandMessage:
    """
    A hand picture the bot sent a player, ephemeral, remembered so a
    later click may bring it up to date in place rather than send the
    hand again (docs/design/codex.md, "The panel"): the interaction
    that made it -- an ephemeral message can be reached no other way,
    and Discord honours the token for fifteen minutes -- which of its
    messages this is (`None`: its first answer; else a follow-up's id),
    and what it shows, so that a click that changed neither sends
    nothing. In memory only: a restart forgets every one, as it does
    the panels.
    """

    interaction: discord.Interaction
    message_id: Optional[int]
    caption: str
    picture: str

    async def edit(self, **kwargs) -> None:
        if self.message_id is None:
            await self.interaction.edit_original_response(**kwargs)
        else:
            await self.interaction.followup.edit_message(self.message_id, **kwargs)

    async def delete(self) -> None:
        if self.message_id is None:
            await self.interaction.delete_original_response()
        else:
            await self.interaction.followup.delete_message(self.message_id)


class PresentationMixin:
    async def render_match_png(self, game: CodexGame, match=None) -> bytes:
        """The board as WebP bytes (`render.WEBP_QUALITY`), drawn off
        the event loop. The name is the gate's: `BoardRefresher` looks
        this and `match_file_from_png` up on the cog by D12 Ball's names."""
        if match is None:
            match = self.service.load(game)
        return await asyncio.to_thread(
            render_board, match, game.board_layout, self.seat_names(game), self.engine.catalog,
        )

    def match_file_from_png(self, game: CodexGame, png: bytes) -> discord.File:
        return discord.File(
            io.BytesIO(png),
            filename=f"{BOARD_IMAGE_FILENAME_PREFIX}{game.game_number}-board.webp",
        )

    async def refresh_match_image(self, game: CodexGame, png: Optional[bytes] = None) -> None:
        """**The one forwarder** over the turn message's write gate: an
        edit in place, for what is not an action -- **Swap view**. An
        action posts the message again instead (`repost_turn_message`)."""
        channel = self.bot.get_channel(game.channel_id) if game.channel_id else None
        if channel is None:
            return
        await self.boards.refresh(channel, game, png)

    def bot_access(self) -> discord.PermissionOverwrite:
        """The bot's own place in a game's channel: it writes, deletes its
        own turn messages and pins each finished turn's, and manages the
        channel, to rename it at Start and archive it later."""
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

    async def post_turn_message(self, channel: discord.TextChannel, game: CodexGame,
                                match=None, *, replace: bool = False,
                                ping: Optional[bool] = None) -> discord.Message:
        """
        Post the turn's message **at the foot of the channel** -- the
        board as its picture, its text "**Turn 7** -- @perrytom (Bashing)"
        and the turn's lines, the game's buttons. Two ways:

        - **A new turn's** (`replace=False`): the one it follows stands
          above it as that turn's summary and becomes the record's
          `previous_turn_message_id`, what the undo to the previous turn
          puts back. The post pings the player whose turn it is, and
          only them.
        - **The same turn's again** (`replace=True`): after every action
          that puts something in public, an undo, or `/codex resume`.
          The message it replaces is deleted, so the table is always the
          channel's last message and the panel sent after it sits below
          it (the author, 2026-10-09: "instead of editing the message
          with the board every time an action is taken, it should be
          deleted and reposted"). It pings nobody unless `ping`.

        The current turn's message is never pinned: a pin is a system
        message of its own, which would land under the board, and the
        pinned message would be deleted at the turn's first action. A
        turn's message is pinned once the turn ends and it stands
        (`stand_turn_message`). Posted under the gate's lock, so
        no edit of the gate's lands on a message on its way out, and
        handed to the gate after (`BoardRefresher.posted`) as the board
        it keeps. The record's new ids are saved through the service.
        """
        if match is None:
            match = self.service.load(game)
        if ping is None:
            ping = not replace
        started = time.perf_counter()
        png = await self.render_match_png(game, match)
        drawn = elapsed_ms(started)
        text = self.turn_text(game, match)
        player_id = game.player_1_id if match.active == 1 else game.player_2_id
        state = self.boards.state(game.game_id)
        async with state.lock:
            started = time.perf_counter()
            message = await channel.send(
                text,
                file=self.match_file_from_png(game, png),
                view=TurnMessageView(self, game.game_id),
                allowed_mentions=discord.AllowedMentions(
                    everyone=False, roles=False,
                    users=[discord.Object(id=player_id)] if ping and player_id else False,
                ),
            )
            LOGGER.info("Codex game #%s: the board drawn in %d ms (%d KB), posted in %d ms",
                        game.game_number, drawn, len(png) // 1024, elapsed_ms(started))
            old = game.turn_message_id
            game.turn_message_id = message.id
            if not replace:
                game.previous_turn_message_id = old
            self.service.save()
            if replace and old is not None:
                await self.delete_table_message(channel, game, old)
        self.boards.posted(channel, game, message, png, text)
        return message

    async def repost_turn_message(self, game: CodexGame, match=None) -> None:
        """
        The turn's message posted again at the foot of the game's
        channel, the one it replaces deleted (`post_turn_message`) --
        after an action, whose answer is already saved. So a post that
        fails is logged and the click goes on to its panel: the old
        message stands, a board behind, until the next action or
        `/codex resume` posts it again.
        """
        channel = self.bot.get_channel(game.channel_id) if game.channel_id else None
        if channel is None:
            return
        try:
            await self.post_turn_message(channel, game, match, replace=True)
        except (discord.HTTPException, aiohttp.ClientError) as error:
            LOGGER.warning("Could not post the turn message of Codex game %s again: %s",
                           game.game_id, error)

    async def delete_table_message(self, channel: discord.TextChannel, game: CodexGame,
                                   message_id: int) -> None:
        """A turn message deleted; one already gone is no matter."""
        try:
            await channel.get_partial_message(message_id).delete()
        except discord.NotFound:
            pass
        except discord.HTTPException as error:
            LOGGER.warning("Could not delete a turn message of Codex game %s: %s", game.game_id, error)

    # -- The hand, a message of its own ---------------------------------------

    async def hand_parts(self, game: CodexGame, match, seat: int) -> tuple[str, discord.File]:
        """The hand message's caption -- the hand's count and the discard
        pile (`hand_caption`) -- and its picture (`hand_file`, over the
        engine's `hand_rows`: the list the main phase's buttons read)."""
        return (hand_caption(match, seat, side_label(game, match, seat)),
                await hand_file(self.engine, match, seat))

    async def send_hand_message(self, interaction: discord.Interaction, game: CodexGame, match,
                                seat: int, view: Optional[discord.ui.View] = None) -> None:
        """
        `seat`'s hand pictured and their discard pile listed, **ephemeral
        to them alone**: the click's first answer, or its follow-up where
        the click has been answered already -- and remembered
        (`HandMessage`), the one remembered before it deleted where its
        token still allows, so My hand pressed twice leaves one. `view`
        is the other player's **My deck** (`send_hand`); the active
        player's panel carries its own.
        """
        held = self.hand_messages.pop((game.game_id, seat), None)
        if held is not None:
            try:
                await held.delete()
            except discord.HTTPException:
                pass  # past its fifteen minutes, or gone already: it stands
        started = time.perf_counter()
        caption, file = await self.hand_parts(game, match, seat)
        drawn = elapsed_ms(started)
        kwargs: dict = {"file": file, "ephemeral": True}
        if view is not None:
            kwargs["view"] = view
        started = time.perf_counter()
        if interaction.response.is_done():
            message = await interaction.followup.send(caption, **kwargs)
            message_id = message.id
        else:
            await interaction.response.send_message(caption, **kwargs)
            message_id = None
        self.hand_messages[(game.game_id, seat)] = HandMessage(
            interaction, message_id, caption, file.filename,
        )
        LOGGER.info("Codex game #%s: the hand drawn in %d ms (%d KB), sent in %d ms",
                    game.game_number, drawn, pictures_size([file]) // 1024, elapsed_ms(started))

    async def refresh_hand_message(self, game: CodexGame, match, seat: int,
                                   interaction: Optional[discord.Interaction] = None) -> None:
        """
        `seat`'s hand message brought up to date where its hand or its
        caption changed -- the picture uploaded again only where the hand
        did -- in place, through the interaction that made it; nothing
        is sent where neither changed. Where the edit fails (its fifteen
        minutes past, or the message gone) the message is forgotten,
        and where the click is `seat`'s own (`interaction`) the hand is
        sent afresh as its follow-up: under the board, above the panel
        sent after it.
        """
        held = self.hand_messages.get((game.game_id, seat))
        if held is None:
            return
        started = time.perf_counter()
        caption, file = await self.hand_parts(game, match, seat)
        drawn = elapsed_ms(started)
        if (caption, file.filename) == (held.caption, held.picture):
            return
        kwargs: dict = {"content": caption}
        if file.filename != held.picture:
            kwargs["attachments"] = [file]
        started = time.perf_counter()
        try:
            await held.edit(**kwargs)
        except discord.HTTPException as error:
            del self.hand_messages[(game.game_id, seat)]
            LOGGER.info("Codex game #%s: the hand message could not be brought up to date (%s): %s",
                        game.game_number, error, "sent afresh" if interaction is not None else "forgotten")
            if interaction is not None:
                await self.send_hand_message(interaction, game, match, seat)
            return
        held.caption, held.picture = caption, file.filename
        LOGGER.info("Codex game #%s: the hand drawn in %d ms (%d KB), brought up to date in %d ms",
                    game.game_number, drawn, pictures_size(kwargs.get("attachments", ())) // 1024,
                    elapsed_ms(started))

    async def refresh_hand_messages(self, game: CodexGame, match, seat: int,
                                    interaction: discord.Interaction) -> None:
        """Both players' hand messages after a public result -- a card
        played, the draw at the turn's end, a card an effect returned to
        the other hand: the clicker's (`seat`) through their click where
        it must be sent afresh, the other's in place or not at all."""
        await self.refresh_hand_message(game, match, seat, interaction)
        await self.refresh_hand_message(game, match, 2 if seat == 1 else 1)

    async def send_hand(self, interaction: discord.Interaction, game: CodexGame, match,
                        seat: int) -> None:
        """The other player's hand pictured and their discard listed,
        **ephemeral to them alone** -- the first hidden thing the bot
        shows -- with **My deck** under it; remembered and kept up to
        date as the active player's is (`send_hand_message`)."""
        await self.send_hand_message(interaction, game, match, seat,
                                     view=HandView(self, game.game_id, seat))

    async def send_deck(self, interaction: discord.Interaction, game: CodexGame, match,
                        seat: int) -> None:
        """
        Every card `seat` owns, wherever it is (the engine's `own_deck`),
        pictured with each card's copies and its places counted,
        **ephemeral to them alone**. A message of its own rather than the
        panel's edit, so the hand, the panel or the tech picker it was
        pressed under stays up beside it.
        """
        deck = self.engine.own_deck(match, seat)
        started = time.perf_counter()
        file = await deck_file(self.engine, deck)
        drawn = elapsed_ms(started)
        started = time.perf_counter()
        await interaction.response.send_message(
            deck_caption(deck, side_label(game, match, seat)),
            file=file,
            ephemeral=True,
        )
        LOGGER.info("Codex game #%s: the deck drawn in %d ms (%d KB), sent in %d ms",
                    game.game_number, drawn, pictures_size([file]) // 1024, elapsed_ms(started))
