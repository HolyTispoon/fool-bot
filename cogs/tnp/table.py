"""
The game's channel, its table and each seat's panel (docs/design/tnp.md,
"The lobby, the channel and the table" and "Hidden information on
Discord"):

- **The channel** is the game's own, under TNP Games, open to the whole
  server from the lobby to the end, as Codex's is: what is hidden is
  never in it, so a watcher sees the table and nothing more.
- **The table** is the one public message: the map (`tnp.briefs.map_brief`,
  public by construction), the turn and the phase, and who has locked in
  (`tnp.formatting.table_lines`), with **My board** under it.
- **A panel** is one seat's, ephemeral, to its player alone, and its
  controls: `cogs/tnp/turns.py`.

Every picture is drawn off the event loop (`asyncio.to_thread`).
"""

from __future__ import annotations

import asyncio
import io
import logging
from typing import Optional

import discord
from discord import app_commands

from cogs.game_auth import may_act_in_game
from cogs.tnp_helpers import UNAVAILABLE, channel_name, lobby_channel_name, tnp_games_category
from cogs.tnp.turns import MAP_FILENAME
from cogs.tnp_views import LobbyView, TableView, send_ephemeral
from tnp.briefs import map_brief
from tnp.formatting import map_caption, table_lines
from tnp.game import GameStatus, RuleRefusal, TnpGame
from tnp.render import render_map

LOGGER = logging.getLogger(__name__)


class TableMixin:
    # -- The channel -------------------------------------------------------

    def channel_overwrites(self, guild: discord.Guild) -> dict:
        """
        The game's channel is open to the whole server, from the lobby to
        the end: anyone may read it, talk in it and take the free seat.
        The bot writes, renames the channel at Start, and manages its own
        messages.
        """
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True,
            ),
        }
        if guild.me is not None:
            overwrites[guild.me] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True,
                manage_channels=True, manage_messages=True, attach_files=True,
            )
        return overwrites

    async def create_game_channel(self, guild: discord.Guild, game: TnpGame) -> discord.TextChannel:
        """`tnp-<n>` under TNP Games; every failure a `ValueError`
        carrying the sentence to show."""
        try:
            category = await tnp_games_category(guild)
            return await guild.create_text_channel(
                name=lobby_channel_name(game),
                category=category,
                overwrites=self.channel_overwrites(guild),
                reason=f"TNP game {game.game_number}",
            )
        except discord.Forbidden:
            raise ValueError(
                "I do not have permission to create the TNP Games category or its channels "
                "(that needs **Manage Channels**)."
            )
        except discord.HTTPException as error:
            raise ValueError(f"Discord could not create the channel: {error}")

    async def open_game_place(self, interaction: discord.Interaction, game: TnpGame):
        """
        Where the game is played, with its lobby posted there: **a
        channel of its own** (`create_game_channel`), or where the bot may
        not make one, **a public thread** named `tnp-<n>` in the channel
        the lobby was asked for in -- the hub's channel, for the hub's
        button (the author, 2026-11-06). A week's auto-archive, the
        longest: a post wakes it, and so does any click or `/tnp` command
        (`wake_thread`). A place made whose lobby cannot be posted is
        deleted and the next tried. Returns `(place, venue, message)`;
        raises `ValueError` with the sentence to show where there is
        nowhere.
        """
        try:
            channel = await self.create_game_channel(interaction.guild, game)
        except ValueError as error:
            LOGGER.info("TNP game %s: no channel of its own, so a thread (%s)", game.game_id, error)
        else:
            message = await self.post_lobby(channel, game)
            if message is not None:
                return channel, "channel", message
            await self.delete_place(channel, game)
        here = interaction.channel or self.bot.get_channel(interaction.channel_id)
        if isinstance(here, discord.TextChannel):
            try:
                thread = await here.create_thread(
                    name=lobby_channel_name(game),
                    type=discord.ChannelType.public_thread,
                    auto_archive_duration=10080,
                    reason=f"TNP game {game.game_number}",
                )
            except discord.HTTPException as error:
                LOGGER.info("TNP game %s: no thread either (%s)", game.game_id, error)
            else:
                message = await self.post_lobby(thread, game)
                if message is not None:
                    return thread, "thread", message
                await self.delete_place(thread, game)
        raise ValueError(
            "I could not create a channel or a thread for the game: that needs "
            "**Manage Channels**, or **Create Public Threads** in this channel."
        )

    async def post_lobby(self, place, game: TnpGame) -> Optional[discord.Message]:
        """The lobby posted in `place`, or `None` where Discord refused it."""
        try:
            return await place.send(
                self.lobby_text(game), view=LobbyView(self, game.game_id),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException as error:
            LOGGER.info("Could not post the lobby of TNP game %s: %s", game.game_id, error)
            return None

    async def delete_place(self, place, game: TnpGame) -> None:
        """A channel or thread made for a lobby that could not be posted."""
        try:
            await place.delete(reason="The TNP lobby could not be posted")
        except discord.HTTPException as error:
            LOGGER.warning("Could not delete the empty place of TNP game %s: %s",
                           game.game_id, error)

    async def wake_thread(self, thread, game: Optional[TnpGame]) -> None:
        """
        A game's thread taken out of the archive before a click or a
        command on it is answered, where Discord archived it after a week
        idle: a message in an archived thread cannot be edited, the
        click's own answer among them (`cogs/codex/ending.py`'s
        `wake_thread`). One request, and only then. An open game's or
        lobby's alone; a failure is logged and the click goes on.
        """
        if not (isinstance(thread, discord.Thread) and thread.archived and game is not None
                and game.venue == "thread"
                and game.status in (GameStatus.LOBBY, GameStatus.PLAYING)):
            return
        try:
            await thread.edit(archived=False)
        except discord.HTTPException as error:
            LOGGER.warning("Could not take the thread of TNP game %s out of the archive: %s",
                           game.game_id, error)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Every `/tnp` command first wakes the archived thread it is
        typed in, where a TNP game is open there (`wake_thread`). Never
        refuses."""
        thread = interaction.channel
        if isinstance(thread, discord.Thread) and thread.archived:
            await self.wake_thread(thread, self.game_for_channel(thread.id))
        return True

    async def name_game_channel(self, channel, game: TnpGame) -> None:
        """At Start, the channel -- or the thread -- renamed
        `tnp-<n>-<blue>-vs-<green>`; its permissions stand. A failure is
        logged and the game goes on."""
        try:
            await channel.edit(name=channel_name(game), reason=f"TNP game {game.game_number} started")
        except discord.HTTPException as error:
            LOGGER.warning("Could not rename the channel of TNP game %s: %s", game.game_id, error)

    # -- The table -----------------------------------------------------------

    def table_text(self, game: TnpGame, match) -> str:
        """The table's words: the model's lines, rendered."""
        return "\n".join(
            self.render_text(line, game) for line in table_lines(self.engine, game, match)
        )

    async def post_table_message(self, channel, game: TnpGame, match):
        """The table sent, its picture handed to the gate as the one on
        the message (`BoardRefresher.posted`), so the gate's next write
        skips what is already up."""
        png = await asyncio.to_thread(render_map, self.catalog, map_brief(match, map_caption(match)))
        text = self.table_text(game, match)
        message = await channel.send(
            text,
            file=discord.File(io.BytesIO(png), filename=MAP_FILENAME),
            view=TableView(self, game.game_id),
            allowed_mentions=discord.AllowedMentions.none(),
        )
        return message, png, text

    async def post_table(self, channel, game: TnpGame) -> Optional[discord.Message]:
        """
        The table posted in the game's channel, its id saved on the
        record so a restart re-arms **My board**. One send. A failure is
        logged at ERROR -- the game can't be played until somebody runs
        `/tnp resume` -- and the game is otherwise left as it is.
        """
        match = self.service.load(game)
        try:
            message, png, text = await self.post_table_message(channel, game, match)
        except discord.HTTPException as error:
            LOGGER.error("Could not post the table of TNP game %s; it needs /tnp resume: %s",
                         game.game_id, error)
            return None
        game.table_message_id = message.id
        self.service.save()
        self.boards.forget(game)
        self.boards.posted(channel, game, message, png, text)
        return message

    # -- /tnp resume ---------------------------------------------------------

    @app_commands.command(name="resume", description="Put a TNP game's table back up in its channel.")
    async def resume(self, interaction: discord.Interaction) -> None:
        """
        In a game's channel, a player's or a game helper's: the step the
        bot owes run where there is one (`GameService.resume`, off the
        one reading), and a fresh table posted, its **My board** re-armed
        -- for a table that was never posted or was deleted. The old
        table, if any, stands as it was.
        """
        service = self.service
        if service is None:
            await send_ephemeral(interaction, UNAVAILABLE)
            return
        game = self.game_for_channel(interaction.channel_id)
        if game is None or game.status is not GameStatus.PLAYING:
            await send_ephemeral(interaction, "No TNP game is being played in this channel.")
            return
        if not may_act_in_game(interaction.user, game):
            await send_ephemeral(interaction, "Only this game's players, or a helper, may resume it.")
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            found, result = service.resume(game.game_id)
        except RuleRefusal as refused:
            await interaction.followup.send(str(refused), ephemeral=True)
            return
        channel = self.bot.get_channel(game.channel_id) or interaction.channel
        if result.groups or result.narration:
            # The step the bot owed said something: posted as a turn's
            # lines are, before the fresh table.
            for lines, pictures in self.messages_for(result):
                await self.post(channel, game, "\n".join(self.render_text(line, game) for line in lines), pictures)
        message = await self.post_table(channel, game)
        said = "The table is back up." if message is not None else "I could not post the table."
        await interaction.followup.send(f"Found {found}. {said}", ephemeral=True)
