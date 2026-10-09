"""
A game's end on Discord (docs/codex-bot.md, step 8; docs/design/codex.md,
"The end of a game"): **Concede** -- on the turn message and as
`/codex concede`, the clicker's own side alone, behind a second click --
`/codex abandon` -- a player's own game, or any game for a helper -- **Rematch** under the finished game's last
line, the channel moved to **Codex Archive**, and `/codex admin
reset_channels` for the test server.

A finished or abandoned game's channel is moved aside and left as it is:
**nothing is exported from it and no statistics are read from it** (the
author, 2026-10-07); the event log stays in the save. Nothing here
decides a rule: whether a game may be conceded, abandoned or played
again is the record's and the service's answer.
"""

from __future__ import annotations

import logging
from typing import Optional

import discord
from discord import app_commands

from codex.formatting import deck_name
from codex.game import CodexGame, GameStatus, RuleRefusal
from cogs.codex_helpers import (
    CHANNEL_NAME_PATTERN,
    CODEX_ARCHIVE_CATEGORY_NAME,
    codex_archive_category,
    codex_games_category,
    is_game_helper,
)
from cogs.codex_views import ConcedeConfirmView, LobbyView, send_ephemeral
from cogs.debug import delete_channel_with_retries

LOGGER = logging.getLogger(__name__)

NOT_PLAYING_HERE = "No Codex game is being played in this channel."
HELPERS_ONLY = "Only a helper with Manage Channels can do that."


class EndingMixin:
    # -- Who is playing here ---------------------------------------------

    def open_game_for_channel(self, channel_id: Optional[int]) -> Optional[CodexGame]:
        """The game being played in this channel, or else the lobby open
        in it -- what `/codex abandon` ends."""
        game = self.game_for_channel(channel_id)
        if game is not None:
            return game
        lobbies = [
            game for game in self.games.values()
            if game.channel_id == channel_id and game.status is GameStatus.LOBBY
        ]
        return lobbies[-1] if lobbies else None

    # -- The channel -------------------------------------------------------

    async def move_channel(self, channel, category_for, reason: str, game: CodexGame) -> None:
        """Move the game's channel under a category of the Codex bot's
        own, its name and permissions left as they are. A failure is
        logged and nothing else waits on it."""
        guild = getattr(channel, "guild", None)
        if guild is None:
            return
        try:
            category = await category_for(guild)
            if getattr(channel, "category_id", None) == getattr(category, "id", object()):
                return
            await channel.edit(category=category, reason=reason)
        except discord.HTTPException as error:
            LOGGER.warning("Could not move the channel of Codex game %s: %s", game.game_id, error)

    async def archive_channel(self, channel, game: CodexGame) -> None:
        """A finished or abandoned game's channel, moved to Codex
        Archive and left as it is: its messages are the game's record,
        and nothing is exported from it."""
        await self.move_channel(
            channel, codex_archive_category, f"Codex game {game.game_number} is over", game,
        )

    # -- Concede -------------------------------------------------------------

    async def ask_concede(self, interaction: discord.Interaction, game: Optional[CodexGame]) -> None:
        """
        **Concede**, the first click: the clicker's own side -- in a test
        game the side whose turn it is -- asked to confirm, privately.
        Nobody concedes for anybody else, helper or not.
        """
        if game is None or game.status is not GameStatus.PLAYING:
            await send_ephemeral(interaction, NOT_PLAYING_HERE)
            return
        match = self.service.load(game)
        seat = game.seat_for(interaction.user.id, match.active)
        if seat is None:
            await send_ephemeral(interaction, "Only the game's two players can concede, each their own side.")
            return
        other = 2 if seat == 1 else 1
        winner = game.seat_name(other) or f"Player {other}"
        side = f" {deck_name(match.player(seat).specs)}'s side of" if game.test_game else ""
        await interaction.response.send_message(
            f"Concede{side} the game? {winner} wins, and it cannot be undone.",
            view=ConcedeConfirmView(self, game.game_id, seat, interaction.user.id),
            ephemeral=True,
        )

    async def concede(self, interaction: discord.Interaction, game: CodexGame, seat: int) -> None:
        """
        The second click: the service ends the game for `seat`'s
        opponent, the confirmation closes in place, and the end goes up
        as a destroyed base's does -- the turn message's last edit, the
        winner's line with the board and **Rematch**, the channel
        archived (`present`, `finish_game`).
        """
        try:
            result = self.service.concede(game.game_id, seat)
        except RuleRefusal as refused:
            await interaction.response.edit_message(content=str(refused), view=None)
            return
        await interaction.response.edit_message(content="You conceded.", view=None)
        await self.present(game, result)

    @app_commands.command(name="concede", description="Concede this channel's Codex game: your own side, confirmed by a second click.")
    async def concede_command(self, interaction: discord.Interaction) -> None:
        await self.ask_concede(interaction, self.game_for_channel(interaction.channel_id))

    # -- Abandon -------------------------------------------------------------

    @app_commands.command(name="abandon", description="End this channel's Codex game or lobby, unfinished: its players' own, or a helper's.")
    async def abandon_command(self, interaction: discord.Interaction) -> None:
        """
        End the game played here -- or the lobby open here -- with no
        winner, through the service (`GameService.abandon`); its turn
        message stands without its buttons (the lobby's, without its
        own), one public line says it was abandoned and by whom, and the
        channel is archived. **Either of its players may abandon their
        own game** (the author, 2026-10-09), and a game helper (Manage
        Channels) any game; nobody else.
        """
        if interaction.guild is None:
            await send_ephemeral(interaction, "A Codex game is played in a server's channel.")
            return
        game = self.open_game_for_channel(interaction.channel_id)
        if game is None:
            await send_ephemeral(interaction, "No Codex game or lobby is open in this channel.")
            return
        if game.seat_of(interaction.user.id) is None and not is_game_helper(interaction.user):
            await send_ephemeral(
                interaction,
                "Only this game's players, or a helper with Manage Channels, can abandon it.",
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
            channel = interaction.channel or self.bot.get_channel(game.channel_id)
            if was_playing and game.turn_message_id is not None:
                match = self.service.load(game)
                png = await self.render_match_png(game, match)
                text = self.turn_text(game, match, footer=False) if game.game_id in self.turn_lines else None
                await self.stand_turn_message(channel, game, game.turn_message_id, png, text)
            elif not was_playing and game.message_id is not None:
                try:
                    await channel.get_partial_message(game.message_id).edit(
                        content=self.lobby_text(game), view=None,
                    )
                except discord.HTTPException as error:
                    LOGGER.warning("Could not close the lobby of Codex game %s: %s", game.game_id, error)
            self.turn_lines.pop(game.game_id, None)
            self.turn_heads.pop(game.game_id, None)
            try:
                await channel.send(
                    f"**Codex game {game.game_number} was abandoned** by "
                    f"{interaction.user.display_name}: it ends with no winner.",
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except discord.HTTPException as error:
                LOGGER.warning("Could not say Codex game %s was abandoned: %s", game.game_id, error)
            await self.archive_channel(channel, game)
        await interaction.followup.send("Abandoned, and the channel archived.", ephemeral=True)

    # -- Rematch -------------------------------------------------------------

    async def open_rematch(self, interaction: discord.Interaction, game: CodexGame) -> None:
        """
        **Rematch**: the service opens the new lobby (the same two seats,
        the heroes swapped until both press **Keep heroes**); the button
        comes off the finished game's line in the click's own response;
        the channel goes back under Codex Games, since a game is about to
        be played in it; and the lobby is posted there. A second press
        finds the lobby already open.
        """
        opened = game.rematch_game_id is not None and game.rematch_game_id in self.games
        try:
            rematch = self.service.rematch(game.game_id)
        except RuleRefusal as refused:
            await send_ephemeral(interaction, str(refused))
            return
        if opened and rematch.message_id is not None:
            await send_ephemeral(interaction, "The rematch's lobby is already open, below.")
            return
        await interaction.response.edit_message(view=None)
        channel = self.bot.get_channel(game.channel_id) if game.channel_id else interaction.channel
        if channel is None:
            await send_ephemeral(interaction, "I cannot find this game's channel.")
            return
        await self.move_channel(
            channel, codex_games_category, f"Codex game {rematch.game_number}: a rematch", rematch,
        )
        try:
            message = await channel.send(self.lobby_text(rematch), view=LobbyView(self, rematch.game_id))
        except discord.HTTPException as error:
            LOGGER.warning("Could not post the rematch lobby of Codex game %s: %s", game.game_id, error)
            game.rematch_game_id = None
            self.service.discard_game(rematch.game_id)
            return
        rematch.message_id = message.id
        self.service.save()

    # -- The test server's reset ---------------------------------------------

    admin = app_commands.Group(
        name="admin",
        description="Helpers: maintenance for the Codex bot's channels.",
        guild_only=True,
    )

    @admin.command(name="reset_channels", description="Delete every Codex channel not archived, and drop its game.")
    @app_commands.describe(confirm='Type "confirm" to delete every Codex channel outside Codex Archive.')
    async def reset_channels(self, interaction: discord.Interaction, confirm: str) -> None:
        """
        For the test server: every Codex channel outside Codex Archive
        deleted -- lobbies and games being played alike -- and every
        game of this server not in an archived channel dropped, after
        the confirmation word, as `/debug reset_channels` does for D12
        Ball's. The gate is `/debug`'s -- in a server, Manage Channels
        -- read at run time, since Discord carries a default permission
        on a top-level command alone.
        """
        guild = interaction.guild
        if guild is None or not is_game_helper(interaction.user):
            await send_ephemeral(interaction, HELPERS_ONLY)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        if confirm != "confirm":
            await interaction.followup.send(
                'Reset cancelled. Type "confirm" in the confirm field to run it.', ephemeral=True,
            )
            return
        try:
            channels = await guild.fetch_channels()
        except discord.HTTPException:
            channels = guild.channels

        def archived(channel) -> bool:
            category = getattr(channel, "category", None)
            return category is not None and category.name.casefold() == CODEX_ARCHIVE_CATEGORY_NAME.casefold()

        codex_channels = [
            channel for channel in channels
            if isinstance(channel, discord.TextChannel)
            and CHANNEL_NAME_PATTERN.match(channel.name.lower())
        ]
        kept = {channel.id for channel in codex_channels if archived(channel)}
        failed: list[tuple[str, str]] = []
        deleted = 0
        for channel in codex_channels:
            if channel.id in kept:
                continue
            error = await delete_channel_with_retries(
                channel, reason=f"Codex channel reset requested by {interaction.user}",
            )
            if error is None:
                deleted += 1
            else:
                failed.append((channel.name, error))
        dropped = [
            game_id for game_id, game in self.games.items()
            if game.guild_id == guild.id and game.channel_id not in kept
        ]
        for game_id in dropped:
            game = self.games[game_id]
            self.boards.forget(game)
            self.turn_lines.pop(game_id, None)
            self.turn_heads.pop(game_id, None)
        self.service.drop_games(dropped)
        report = (
            f"Deleted {deleted} Codex channel(s) and dropped {len(dropped)} game(s). "
            f"The next Codex game will be number {self.service.next_game_number(guild.id)}."
        )
        if failed:
            report += "\n\nI could not delete these channels:\n" + "\n".join(
                f"- {name}: {error}" for name, error in failed
            )
        try:
            await interaction.followup.send(report, ephemeral=True)
        except discord.HTTPException as error:
            LOGGER.info("Could not report the Codex channel reset (%s). %s", error, report)
