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
from codex.cards import catalog
from codex.formatting import team_name
from codex.game import CodexGame, GameStatus, RuleRefusal
from cogs.codex_views import LobbyView, send_ephemeral

LOGGER = logging.getLogger(__name__)

class LobbyMixin:
    def lobby_text(self, game: CodexGame) -> str:
        """The lobby's text: the game, who sits where with which heroes
        and deck, and what Start waits on. The catalog names the heroes."""
        cards = catalog()
        rows = []
        for seat in (1, 2):
            name = game.seat_name(seat)
            if name is None:
                rows.append(f"**Player {seat}**: *open*")
                continue
            specs = game.player_specs.get(seat, ())
            if not specs:
                rows.append(f"**Player {seat}**: {name} -- *choosing heroes*")
                continue
            heroes = [cards.hero_for(spec) for spec in specs]
            row = f"**Player {seat}**: {name} -- **{team_name(specs)}**"
            if len(heroes) == 1:
                row += f" ({heroes[0].name})"
            elif cards.color_deck_of(specs) is not None:
                row += f" ({', '.join(hero.name for hero in heroes)})"
            else:
                # The first hero names the deck: said, so it is clear.
                row += f" ({heroes[0].name} first, then " + ", ".join(
                    hero.name for hero in heroes[1:]) + ")"
            if len(specs) < game.heroes_per_seat:
                row += " -- *choosing heroes*"
            deck = game.player_decks.get(seat)
            if deck in game.deck_choices(seat):
                row += f"; the {deck.title()} starting deck"
            rows.append(row)
        if game.status is not GameStatus.LOBBY:
            waiting = "The game has started."
        elif game.may_start():
            waiting = "Both seats are ready: either player may **Start**."
        else:
            waiting = ("Choose your hero to take a seat." if game.mode == "basic" else
                       "Choose a colour's deck, or **Mixed colours** for any three heroes "
                       "-- the first hero's colour is the starting deck -- to take a seat.")
        if game.mode == "standard":
            kind = "a standard game, three heroes a side"
        else:
            kind = "the basic game, one hero a side"
        head = self.render_text(f"{tokens.codex()} **Codex game {game.game_number}** -- {kind}.")
        if game.test_game:
            head += " A **test game**: one person may take both seats and play both sides."
        lines = [head.strip(), *rows]
        if game.rematch_specs:
            lines.append(self.rematch_line(game))
        return "\n".join([*lines, waiting])

    async def refresh_lobby(self, game: CodexGame) -> None:
        """The lobby edited to show a change made from somewhere else --
        the mixed-team picker, whose click answers the picker -- through
        the channel: one edit, in a channel where nothing else is being
        edited before Start."""
        channel = self.bot.get_channel(game.channel_id) if game.channel_id else None
        if channel is None or game.message_id is None:
            return
        try:
            await channel.get_partial_message(game.message_id).edit(
                content=self.lobby_text(game), view=LobbyView(self, game.game_id),
            )
        except discord.HTTPException:
            pass

    def rematch_line(self, game: CodexGame) -> str:
        """What a rematch's lobby says about its heroes: swapped from
        the last game, or kept because both players asked."""
        played = next(
            (other for other in self.games.values() if other.game_id == game.rematch_of), None,
        )
        last = f"game {played.game_number}" if played is not None else "the last game"
        if game.heroes_kept:
            return f"A rematch of {last}: both players keep their heroes."
        asked = [game.seat_name(seat) or f"Player {seat}" for seat in game.kept_heroes]
        if game.test_game and asked:
            asked = asked[:1]
        tail = f" ({' and '.join(asked)} asked to keep them.)" if asked else ""
        return (
            f"A rematch of {last}: the teams are swapped, heroes and decks -- unless "
            f"both players press **Keep heroes**.{tail}"
        )

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
        first turn's start; the channel is renamed for the players; the lobby is edited once to
        say the game has started, its buttons gone; and the first turn's
        message is posted under it. The click has been
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
        await self.name_game_channel(channel, game)
        if game.message_id is not None:
            try:
                await channel.get_partial_message(game.message_id).edit(
                    content=self.lobby_text(game), view=None,
                )
            except discord.HTTPException:
                pass
        self.turn_lines[game.game_id] = list(result.lines)
        if result.match is not None and result.match.phase == "main":
            self.note_turn_head(game, result.match)
        await self.post_turn_message(channel, game, result.match)
        await interaction.followup.send("The game has started.", ephemeral=True)
