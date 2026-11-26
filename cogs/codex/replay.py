"""
`/codex replay`: a game that is over shown again turn by turn, as a
slideshow the asker alone sees (docs/design/codex.md, "The replay").

The turns are the channel's pins -- each turn's start, posted and pinned
with its heading and its board (`open_turn`) -- so a replay draws no
old board and holds nothing new: a slide is the pin's own picture, by
its attachment's address, and the pin's heading. The lines of each turn
are the publisher's record's, where the site publishes (the history it
keeps turn by turn), else whatever lines the pin itself carries -- a
pin from before 2026-10-21 holds its turn's lines whole. The last slide
is the final board, drawn once from the saved match.

The requests: the pins' listing, 50 a request, and the final board's
upload; every slide after the first is an edit of the ephemeral message
through the interaction's webhook, never the channel's edit bucket
(docs/design/rate-limits.md).
"""

from __future__ import annotations

import logging
import re
from typing import Optional

import discord
from discord import app_commands

from codex import seats
from codex.game import CodexGame, GameStatus
from cogs.codex_publish import pins
from cogs.codex_views import send_ephemeral
from cogs.codex_views.replay import ReplaySlide, ReplayView

LOGGER = logging.getLogger(__name__)

#: The most pins one listing hands back (Discord's cap on the endpoint).
PIN_PAGE = 50

OVER = (GameStatus.FINISHED, GameStatus.ABANDONED)
NOTHING_OVER_HERE = (
    "No Codex game that is over was played in this channel. `/codex replay number:<n>` "
    "replays one by its number."
)
NOT_OVER = "Game {number} is still being played: a game is replayed once it is over."
NO_SUCH_GAME = "This server has no Codex game {number}."
NO_TURNS = "Game {number} has no pinned turns to replay."
UNREADABLE = "The pins of game {number}'s channel cannot be read."

#: A pinned turn's first line: "**Turn 7** -- ...".
HEADING = re.compile(r"^\*\*Turn (\d+)\*\*")


class ReplayMixin:
    @app_commands.command(name="replay",
                          description="Replay a finished Codex game turn by turn, to you alone.")
    @app_commands.describe(number="The game's number; by default the last one over in this channel.")
    async def replay(self, interaction: discord.Interaction, number: Optional[int] = None) -> None:
        game = self.replayed_game(interaction, number)
        if isinstance(game, str):
            await send_ephemeral(interaction, game)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        slides = await self.replay_slides(game)
        if isinstance(slides, str):
            await interaction.followup.send(slides, ephemeral=True)
            return
        view = ReplayView(game.game_number, slides)
        message = await interaction.followup.send(ephemeral=True, wait=True, **view.content())
        view.attach(interaction, message)

    def replayed_game(self, interaction: discord.Interaction,
                      number: Optional[int]) -> "CodexGame | str":
        """The game to replay -- by its number in this server, or the
        last one over in this channel -- or what to say instead."""
        if number is not None:
            guild_id = interaction.guild.id if interaction.guild else None
            found = next((game for game in self.games.values()
                          if game.guild_id == guild_id and game.game_number == number), None)
            if found is None:
                return NO_SUCH_GAME.format(number=number)
            if found.status not in OVER:
                return NOT_OVER.format(number=number)
            return found
        here = [game for game in self.games.values()
                if game.channel_id == interaction.channel_id and game.status in OVER
                and game.match_state is not None]
        if not here:
            return NOTHING_OVER_HERE
        return max(here, key=lambda game: game.game_number)

    async def replay_slides(self, game: CodexGame) -> "list[ReplaySlide] | str":
        """Every pinned turn's start, oldest first, then the final board."""
        try:
            pinned = await self.pinned_turns(game)
        except (discord.NotFound, discord.Forbidden):
            pinned = None
        except discord.HTTPException as error:
            LOGGER.warning("Could not list the pins of Codex game %s for a replay: %s",
                           game.game_id, error)
            pinned = None
        if pinned is None:
            return UNREADABLE.format(number=game.game_number)
        recorded = self.recorded_lines(game)
        slides = []
        for turn, (heading, carried, url) in sorted(pinned.items()):
            lines = recorded.get(turn)
            slides.append(ReplaySlide(
                label=f"Turn {turn}'s start", heading=heading,
                lines=[self.render_text(line, game) for line in lines] if lines else carried,
                image_url=url,
            ))
        final = await self.final_slide(game, recorded)
        if final is not None:
            slides.append(final)
        if len(slides) < 2:
            return NO_TURNS.format(number=game.game_number)
        return slides

    async def pinned_turns(self, game: CodexGame) -> dict[int, tuple[str, list[str], str]]:
        """Each turn the channel's pins hold for `game`: its heading, the
        lines the pin carries, and its board's address. A turn pinned
        twice -- undone to and played again -- is its later pin; the
        listing is newest first."""
        channel = self.bot.get_channel(game.channel_id)
        if channel is None:
            # An archived thread is not in the cache.
            channel = await self.bot.fetch_channel(game.channel_id)
        bot_id = self.bot.user.id
        found: dict[int, tuple[str, list[str], str]] = {}
        before = None
        while True:
            page = [message async for message in channel.pins(limit=PIN_PAGE, before=before)]
            for message in page:
                board = pins.board_of(message, game, bot_id)
                if board is None:
                    continue
                first, _, rest = (message.content or "").partition("\n")
                heading = HEADING.match(first)
                if heading is None or int(heading.group(1)) in found:
                    continue
                lines = [line for line in rest.split("\n") if line.strip()]
                found[int(heading.group(1))] = (first, lines, board.url)
            before = page[-1].pinned_at if page else None
            if len(page) < PIN_PAGE or before is None:
                return found

    def recorded_lines(self, game: CodexGame) -> dict[int, list[str]]:
        """Each turn's lines, the model's words with their tokens, as the
        publisher's record keeps them -- none where the site is off."""
        publisher = getattr(self, "publisher", None)
        published = publisher.record.games.get(game.game_id) if publisher is not None else None
        if published is None:
            return {}
        found = {entry["turn"]: list(entry.get("lines") or [])
                 for entry in published.history if entry.get("turn") is not None}
        if published.turn is not None and published.lines:
            found[published.turn] = list(published.lines)
        return {turn: lines for turn, lines in found.items() if lines}

    async def final_slide(self, game: CodexGame,
                          recorded: dict[int, list[str]]) -> Optional[ReplaySlide]:
        """Where the game ended: the board drawn from the saved match, and
        its last turn's lines."""
        if game.match_state is None:
            return None
        match = self.service.load(game)
        png = await self.render_match_png(game, match)
        heading = f"**Turn {match.turn}**"
        if match.winner is not None:
            names = self.seat_names(game)
            won = " and ".join(names.get(seat, "someone") for seat in seats.dragon_of(match, match.winner))
            heading += f" -- {won} {'win' if ' and ' in won else 'wins'}"
        elif game.status is GameStatus.ABANDONED:
            heading += " -- abandoned"
        lines = recorded.get(match.turn) or []
        return ReplaySlide(
            label="The final board", heading=heading,
            lines=[self.render_text(line, game) for line in lines], png=png,
        )
