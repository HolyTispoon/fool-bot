"""
The board and the game's place: the board rendered off the event loop
(`codex/render.py` through `asyncio.to_thread`), the gate's one
forwarder, where the game is played -- its own channel, else a Discord
thread, else the channel the lobby was asked for in -- the turn message
posted -- for a new turn, or again at the foot of the channel after an
action -- and a player's hand and their whole deck sent to them alone.
"""

from __future__ import annotations

import asyncio
import io
import logging
import time
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
    LobbyView,
    TurnMessageView,
    deck_caption,
    deck_file,
    hand_caption,
    hand_file,
    revealed_caption,
    revealed_files,
    side_label,
)

LOGGER = logging.getLogger(__name__)


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

    async def open_game_place(self, interaction: discord.Interaction, game: CodexGame):
        """
        Where `/codex create_game`'s game is played, with its lobby posted
        there -- the first of three the bot may make and post in (the
        author, 2026-10-10):

        1. **a channel of its own**, `codex-<n>` under Codex Games
           (`create_game_channel`);
        2. where it may not, **a public thread of that name** in the
           channel the command was typed in;
        3. where it may make neither, **that channel itself** -- unless a
           Codex game or lobby is already open in it, since a channel
           holds one game at a time (`game_for_channel`).

        A place made whose lobby cannot be posted is deleted and the next
        tried. Returns `(place, venue, lobby message)`, the venue one of
        `codex.game.VENUES`; raises `ValueError` carrying the sentence to
        show when there is nowhere.
        """
        here = interaction.channel or self.bot.get_channel(interaction.channel_id)
        try:
            channel = await self.create_game_channel(interaction.guild, game)
        except ValueError as error:
            LOGGER.info("Codex game %s: no channel of its own, so a thread or here (%s)",
                        game.game_id, error)
        else:
            message = await self.post_lobby(channel, game)
            if message is not None:
                return channel, "channel", message
            await self.delete_place(channel, game)
        if isinstance(here, discord.TextChannel):
            try:
                thread = await here.create_thread(
                    name=channel_name(game),
                    type=discord.ChannelType.public_thread,
                    # A week, the longest: a game may sit a few days
                    # between turns, and a post wakes it either way.
                    auto_archive_duration=10080,
                    reason=f"Codex game {game.game_number}",
                )
            except discord.HTTPException as error:
                LOGGER.info("Codex game %s: no thread either, so here (%s)", game.game_id, error)
            else:
                message = await self.post_lobby(thread, game)
                if message is not None:
                    return thread, "thread", message
                await self.delete_place(thread, game)
        if here is None:
            raise ValueError("I could not create a channel or a thread for the game, "
                             "and I cannot find this channel to open it here.")
        if self.open_game_for_channel(here.id) is not None:
            raise ValueError(
                "I could not create a channel or a thread for the game, and a Codex game "
                "is already open in this channel: finish or abandon it first."
            )
        message = await self.post_lobby(here, game)
        if message is None:
            raise ValueError("I could not create a channel or a thread for the game, "
                             "nor post its lobby in this channel.")
        return here, "here", message

    async def post_lobby(self, place, game: CodexGame) -> Optional[discord.Message]:
        """The lobby posted in `place`, or `None` where Discord refused it."""
        try:
            return await place.send(self.lobby_text(game), view=LobbyView(self, game.game_id))
        except discord.HTTPException as error:
            LOGGER.info("Could not post the lobby of Codex game %s: %s", game.game_id, error)
            return None

    async def delete_place(self, place, game: CodexGame) -> None:
        """A channel or thread made for a lobby that could not be posted."""
        try:
            await place.delete(reason="The Codex lobby could not be posted")
        except discord.HTTPException as error:
            LOGGER.warning("Could not delete the empty place of Codex game %s: %s",
                           game.game_id, error)

    async def name_game_channel(self, channel, game: CodexGame) -> None:
        """
        At Start, the lobby's channel -- or thread -- is renamed for its
        players, `codex-<n>-<p1>-vs-<p2>`; its permissions stand. A
        channel the game was only opened in (venue "here") is not the
        bot's to rename. A failure is logged and the game goes on either
        way.
        """
        if game.venue == "here":
            return
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

    async def send_hand(self, interaction: discord.Interaction, game: CodexGame, match,
                        seat: int) -> None:
        """A player's hand pictured and their discard listed, **ephemeral
        to them alone** -- the first hidden thing the bot shows -- with
        **My deck** under it."""
        started = time.perf_counter()
        files = [await hand_file(self.engine, match, seat),
                 *await revealed_files(self.engine, match, seat)]
        drawn = elapsed_ms(started)
        started = time.perf_counter()
        caption = hand_caption(match, seat, side_label(game, match, seat))
        revealed = revealed_caption(self.engine, match, seat)
        # One picture as ever; two where Eyes of the Chancellor shows the
        # opponent's hand beneath (step 13).
        pictures = {"file": files[0]} if len(files) == 1 else {"files": files}
        await interaction.response.send_message(
            caption + (f"\n{revealed}" if revealed else ""),
            **pictures,
            view=HandView(self, game.game_id, seat),
            ephemeral=True,
        )
        LOGGER.info("Codex game #%s: the hand drawn in %d ms (%d KB), sent in %d ms",
                    game.game_number, drawn, pictures_size(files) // 1024, elapsed_ms(started))

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
