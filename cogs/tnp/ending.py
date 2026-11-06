"""
The end of a TNP game on Discord (docs/design/tnp.md, "The end of a
game"), Codex's shape (`cogs/codex/ending.py`):

- **A win is announced once**, in the lines that won it -- a fallen
  base, 51% harvested, or a concession -- and **the table becomes the
  final message**: the final map, the model's line saying who won and
  how, and **Rematch** in place of **My board**. One edit, made outside
  the gate once the gate's pending write is dropped (`BoardRefresher.
  forget`), since the gate's text-only edit keeps the view it finds.
- **The channel is moved to TNP Archive** (a thread archived instead):
  a request on the channel's own route, not the messages' edit bucket.
- **`/tnp concede`**: the clicker's own seat, behind a second click
  (`ConcedeConfirmView`).
- **`/tnp abandon`**: a player's own game, or any for a helper; no
  winner, no rematch, one public line.
- **Rematch** (`RematchView`): a new lobby with the same seats in the
  same place, the channel moved back under TNP Games.

Nothing here decides a rule.
"""

from __future__ import annotations

import asyncio
import io
import logging
from typing import Optional

import discord
from discord import app_commands

from cogs.game_auth import is_game_helper
from cogs.tnp_helpers import UNAVAILABLE, tnp_archive_category, tnp_games_category
from cogs.tnp_views import ConcedeConfirmView, RematchView, send_ephemeral
from tnp.briefs import map_brief
from tnp.formatting import map_caption
from tnp.game import GameStatus, RuleRefusal, TnpGame
from tnp.render import render_map

LOGGER = logging.getLogger(__name__)

#: The map's file on the table: the table's own name, so the final edit
#: replaces the picture.
from cogs.tnp.turns import MAP_FILENAME  # noqa: E402


class EndingMixin:
    # -- Which game -------------------------------------------------------

    def open_game_for_channel(self, channel_id: Optional[int]) -> Optional[TnpGame]:
        """The game being played in this channel, or else the lobby open
        in it -- what `/tnp abandon` ends."""
        return self.game_for_channel(channel_id)

    def table_view(self, game: TnpGame):
        """The view the table carries: **My board** while the game is
        played, **Rematch** once it is won and until a rematch is opened,
        and none otherwise."""
        from cogs.tnp_views import TableView

        if game.status is GameStatus.PLAYING:
            return TableView(self, game.game_id)
        if game.status is GameStatus.FINISHED and game.rematch_game_id is None:
            return RematchView(self, game.game_id)
        return None

    # -- The channel --------------------------------------------------------

    async def move_channel(self, channel, category_for, reason: str, game: TnpGame) -> None:
        """The game's channel under a TNP category, its name and
        permissions left as they are. A failure is logged and nothing
        waits on it."""
        guild = getattr(channel, "guild", None)
        if guild is None:
            return
        try:
            category = await category_for(guild)
            if getattr(channel, "category_id", None) == getattr(category, "id", object()):
                return
            await channel.edit(category=category, reason=reason)
        except discord.HTTPException as error:
            LOGGER.warning("Could not move the channel of TNP game %s: %s", game.game_id, error)

    async def set_thread_archived(self, thread, archived: bool, game: TnpGame) -> None:
        try:
            await thread.edit(archived=archived)
        except discord.HTTPException as error:
            LOGGER.warning("Could not %s the thread of TNP game %s: %s",
                           "archive" if archived else "reopen", game.game_id, error)

    async def archive_channel(self, channel, game: TnpGame) -> None:
        """A finished or abandoned game's channel moved to TNP Archive,
        its messages the game's record; a game's thread archived."""
        if channel is None:
            return
        if game.venue == "thread":
            await self.set_thread_archived(channel, True, game)
        else:
            await self.move_channel(channel, tnp_archive_category,
                                    f"TNP game {game.game_number} is over", game)

    async def reopen_channel(self, channel, game: TnpGame) -> None:
        """A rematch's place opened again: the channel back under TNP
        Games, the thread out of the archive."""
        if game.venue == "thread":
            await self.set_thread_archived(channel, False, game)
        else:
            await self.move_channel(channel, tnp_games_category,
                                    f"TNP game {game.game_number}: a rematch", game)

    # -- The final table --------------------------------------------------------

    async def stand_table(self, channel, game: TnpGame, *, picture: bool = True) -> None:
        """
        The table's last edit: the gate's pending write dropped (the game
        is over, and a trailing write would put **My board** back), then
        the final map, the table's words and the view the record now
        calls for (`table_view`). One request on the channel's bucket.
        """
        self.boards.forget(game)
        if channel is None or game.table_message_id is None:
            return
        fields: dict = dict(view=self.table_view(game), allowed_mentions=discord.AllowedMentions.none())
        try:
            match = self.service.load(game)
            fields["content"] = self.table_text(game, match)
            if picture:
                png = await asyncio.to_thread(render_map, self.catalog, map_brief(match, map_caption(match)))
                fields["attachments"] = [discord.File(io.BytesIO(png), filename=MAP_FILENAME)]
        except Exception:
            LOGGER.exception("TNP game %s: the final table could not be drawn.", game.game_id)
        try:
            await channel.get_partial_message(game.table_message_id).edit(**fields)
        except discord.HTTPException as error:
            LOGGER.error("Could not put up the final table of TNP game %s: %s", game.game_id, error)

    async def finish_game(self, channel, game: TnpGame) -> None:
        """A won game's end, after the lines that won it are posted: the
        table as the final message, with **Rematch**, and the channel
        archived."""
        await self.stand_table(channel, game)
        await self.archive_channel(channel, game)

    # -- Concede -------------------------------------------------------------------

    @app_commands.command(name="concede", description="Give up this channel's TNP game: the other seat wins.")
    async def concede(self, interaction: discord.Interaction) -> None:
        """The clicker's own seat, behind a second click: answered
        privately with **Concede as ...** a seat they hold, and
        **Cancel**. Nobody concedes for anybody else."""
        if self.service is None:
            await send_ephemeral(interaction, UNAVAILABLE)
            return
        game = self.game_for_channel(interaction.channel_id)
        if game is None or game.status is not GameStatus.PLAYING:
            await send_ephemeral(interaction, "No TNP game is being played in this channel.")
            return
        seats = game.seats_of(interaction.user.id)
        if not seats:
            await send_ephemeral(interaction, "Only a player of this game can concede it.")
            return
        await interaction.response.send_message(
            "Concede the game? The other seat wins, and the game ends.",
            view=ConcedeConfirmView(self, game.game_id, interaction.user.id, seats),
            ephemeral=True,
        )

    async def concede_seat(self, interaction: discord.Interaction, game_id: str, seat: str) -> None:
        """The second click: the seat concedes through the service, the
        question closed in the click's own response, and the end posted
        as a win's is (`present`, then `finish_game`)."""
        game = self.games.get(game_id)
        if game is None or game.status is not GameStatus.PLAYING:
            await interaction.response.edit_message(content="This game is not being played.", view=None)
            return
        if seat not in game.seats_of(interaction.user.id):
            await interaction.response.edit_message(content="That seat is not yours.", view=None)
            return
        try:
            result = self.service.concede(game_id, seat)
        except RuleRefusal as refused:
            await interaction.response.edit_message(content=str(refused), view=None)
            return
        await interaction.response.edit_message(content="You conceded.", view=None)
        await self.present(self.game_channel(game, interaction.channel), game, result)

    # -- Abandon -------------------------------------------------------------------

    @app_commands.command(
        name="abandon",
        description="End this channel's TNP game or lobby, unfinished: its players' own, or a helper's.",
    )
    async def abandon(self, interaction: discord.Interaction) -> None:
        """
        End the game played here -- or the lobby open here -- with no
        winner (`GameService.abandon`): the table, or the lobby, stands
        without its buttons, a battle's message without its controls, one
        public line says who abandoned it, and the channel is archived.
        **Either player may abandon their own game**, and a game helper
        (Manage Channels) any; nobody else. No second click: a command
        typed in the game's channel, as Codex's.
        """
        if self.service is None:
            await send_ephemeral(interaction, UNAVAILABLE)
            return
        game = self.open_game_for_channel(interaction.channel_id)
        if game is None:
            await send_ephemeral(interaction, "No TNP game or lobby is open in this channel.")
            return
        if game.seat_of(interaction.user.id) is None and not is_game_helper(interaction.user):
            await send_ephemeral(
                interaction, "Only this game's players, or a helper with Manage Channels, can abandon it.",
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.locks.hold(game.game_id):
            was_playing = game.status is GameStatus.PLAYING
            try:
                self.service.abandon(game.game_id)
            except RuleRefusal as refused:
                await interaction.followup.send(str(refused), ephemeral=True)
                return
            channel = self.game_channel(game, interaction.channel)
            if was_playing:
                post = game.battle_post or {}
                if post.get("id") is not None:
                    await self.close_battle_message(channel, None, game, post["id"])
                    self.note_battle(game, key=None, lines=())
                await self.stand_table(channel, game, picture=False)
            elif game.message_id is not None and channel is not None:
                try:
                    await channel.get_partial_message(game.message_id).edit(
                        content=self.lobby_text(game), view=None,
                    )
                except discord.HTTPException as error:
                    LOGGER.warning("Could not close the lobby of TNP game %s: %s", game.game_id, error)
            if channel is not None:
                try:
                    await channel.send(
                        f"**TNP game {game.game_number} was abandoned** by "
                        f"{interaction.user.display_name}: it ends with no winner.",
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                except discord.HTTPException as error:
                    LOGGER.warning("Could not say TNP game %s was abandoned: %s", game.game_id, error)
            await self.archive_channel(channel, game)
        await interaction.followup.send("Abandoned, and the channel archived.", ephemeral=True)

    # -- Rematch -------------------------------------------------------------------

    async def open_rematch(self, interaction: discord.Interaction, game: TnpGame) -> None:
        """
        **Rematch**: the service opens the new lobby (the same seats);
        **Rematch** comes off the table in the click's own response; the
        channel goes back under TNP Games, since a game is about to be
        played in it; and the lobby is posted there. A second press finds
        the lobby already open.
        """
        opened = game.rematch_game_id is not None and game.rematch_game_id in self.games
        if not opened and self.game_for_channel(game.channel_id) is not None:
            await send_ephemeral(interaction, "A TNP game is already open here: finish or abandon it first.")
            return
        try:
            rematch = self.service.rematch(game.game_id)
        except RuleRefusal as refused:
            await send_ephemeral(interaction, str(refused))
            return
        if opened and rematch.message_id is not None:
            await send_ephemeral(interaction, "The rematch's lobby is already open, below.")
            return
        channel = self.game_channel(game, interaction.channel)
        if channel is None:
            await send_ephemeral(interaction, "I cannot find this game's channel.")
            return
        if rematch.venue == "thread":
            # Out of the archive first: a message in an archived thread
            # cannot be edited, the button's own among them.
            await self.reopen_channel(channel, rematch)
        await interaction.response.edit_message(view=None)
        if rematch.venue != "thread":
            await self.reopen_channel(channel, rematch)
        message = await self.post_lobby(channel, rematch)
        if message is None:
            game.rematch_game_id = None
            self.service.discard_game(rematch.game_id)
            return
        rematch.message_id = message.id
        self.service.save()


__all__ = ["EndingMixin"]
