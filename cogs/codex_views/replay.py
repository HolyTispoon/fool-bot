"""
`ReplayView`: `/codex replay`'s slideshow, one message the
asker steps through -- their own alone, or with `public` the channel's -- **⏮ ◀ Play ▶ ⏭** -- each slide a turn's start
board with its heading and lines, the last the final board
(docs/design/codex.md, "The replay").

It reads no match and changes nothing, so it is no `SafeView`: no game
lock. A public replay is steered by whoever ran it, or a helper
(`is_game_helper`); anyone else clicking is told to run their own. Every
step is an edit of that message through the click's own response, and
**Play** edits it through the latest click's token every
`REPLAY_EVERY` seconds, never the channel. A pinned board is its
attachment's address, so only the final board is ever uploaded.
"""

from __future__ import annotations

import asyncio
import io
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import discord

from cogs.game_auth import is_game_helper

LOGGER = logging.getLogger(__name__)

#: Play shows the next slide this often, in seconds.
REPLAY_EVERY = 5
#: An interaction's token lasts 15 minutes; the view stops a little
#: before, since nothing could edit the message after.
REPLAY_TIMEOUT = 14 * 60
#: An embed's description is at most 4096 characters.
DESCRIPTION_MAX = 4096
FINAL_FILENAME = "codex-replay-final.webp"
#: What a public replay tells somebody else who clicks it.
NOT_YOUR_REPLAY = ("{owner} is steering this replay. `/codex replay` gives you one of "
                   "your own to step through.")


@dataclass
class ReplaySlide:
    """One slide: what it is called ("Turn 7's start"), the turn's
    heading and lines as Discord text, and its picture -- a pinned
    board's address, or the final board's bytes."""

    label: str
    heading: str
    lines: list[str] = field(default_factory=list)
    image_url: Optional[str] = None
    png: Optional[bytes] = None


def slide_text(slide: ReplaySlide) -> str:
    """The heading and the lines, folded to fit an embed with the count
    of the lines left out."""
    text = "\n".join([slide.heading, *slide.lines])
    if len(text) <= DESCRIPTION_MAX:
        return text
    kept = [slide.heading]
    for at, line in enumerate(slide.lines):
        more = f"*and {len(slide.lines) - at} more*"
        if len("\n".join([*kept, line, more])) > DESCRIPTION_MAX:
            kept.append(more)
            break
        kept.append(line)
    return "\n".join(kept)


class ReplayView(discord.ui.View):
    def __init__(self, number: int, slides: list[ReplaySlide], owner=None) -> None:
        super().__init__(timeout=REPLAY_TIMEOUT)
        self.number = number
        # Whoever ran it, where it is public; `None` for the asker's own.
        self.owner = owner
        self.slides = slides
        self.index = 0
        self.playing: Optional[asyncio.Task] = None
        # The latest interaction whose token edits the message, and when
        # it came.
        self.interaction: Optional[discord.Interaction] = None
        self.since = 0.0
        self.message: Optional[discord.Message] = None
        self.refresh_buttons()

    def attach(self, interaction: discord.Interaction, message: discord.Message) -> None:
        self.interaction, self.since, self.message = interaction, time.monotonic(), message

    # -- What the message shows ------------------------------------------------

    def content(self) -> dict:
        """The message's embed, its file where the slide uploads one, and
        this view -- as keywords for a send or an edit."""
        slide = self.slides[self.index]
        embed = discord.Embed(
            title=f"Game {self.number} -- {slide.label} ({self.index + 1} of {len(self.slides)})",
            description=slide_text(slide),
        )
        found = {"embed": embed, "view": self}
        if slide.png is not None:
            embed.set_image(url=f"attachment://{FINAL_FILENAME}")
            found["file"] = discord.File(io.BytesIO(slide.png), filename=FINAL_FILENAME)
        elif slide.image_url:
            embed.set_image(url=slide.image_url)
        return found

    def edit_content(self) -> dict:
        """`content` for an edit: a file is an attachment, and a slide
        with none takes the last one away."""
        found = self.content()
        made = found.pop("file", None)
        found["attachments"] = [made] if made is not None else []
        return found

    def refresh_buttons(self) -> None:
        last = len(self.slides) - 1
        self.first.disabled = self.previous.disabled = self.index == 0
        self.next.disabled = self.final.disabled = self.index == last
        self.play.label = "Pause" if self.playing is not None else "Play"
        self.play.style = discord.ButtonStyle.primary if self.playing is None else discord.ButtonStyle.secondary

    async def show(self, interaction: discord.Interaction, index: int) -> None:
        self.index = max(0, min(index, len(self.slides) - 1))
        if self.index == len(self.slides) - 1:
            self.stop_playing()
        self.refresh_buttons()
        self.interaction, self.since = interaction, time.monotonic()
        await interaction.response.edit_message(**self.edit_content())

    # -- Play ------------------------------------------------------------------

    def stop_playing(self) -> None:
        if self.playing is not None and self.playing is not asyncio.current_task():
            self.playing.cancel()
        self.playing = None

    async def run(self) -> None:
        try:
            while self.index < len(self.slides) - 1:
                await asyncio.sleep(REPLAY_EVERY)
                if self.interaction is None or time.monotonic() - self.since > REPLAY_TIMEOUT:
                    break
                self.index += 1
                if self.index == len(self.slides) - 1:
                    self.playing = None
                self.refresh_buttons()
                await self.interaction.edit_original_response(**self.edit_content())
        except asyncio.CancelledError:
            raise
        except discord.HTTPException as error:
            LOGGER.info("A Codex replay of game %s stopped playing: %s", self.number, error)
        if self.playing is asyncio.current_task():
            self.playing = None

    # -- The buttons -----------------------------------------------------------

    @discord.ui.button(emoji="⏮", style=discord.ButtonStyle.secondary)
    async def first(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.stop_playing()
        await self.show(interaction, 0)

    @discord.ui.button(emoji="◀", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.stop_playing()
        await self.show(interaction, self.index - 1)

    @discord.ui.button(label="Play", style=discord.ButtonStyle.primary)
    async def play(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.playing is not None:
            self.stop_playing()
            await self.show(interaction, self.index)
            return
        # Play from the final board starts again from the first.
        start = 0 if self.index == len(self.slides) - 1 else self.index
        self.playing = asyncio.get_running_loop().create_task(self.run())
        await self.show(interaction, start)

    @discord.ui.button(emoji="▶", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.stop_playing()
        await self.show(interaction, self.index + 1)

    @discord.ui.button(emoji="⏭", style=discord.ButtonStyle.secondary)
    async def final(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.stop_playing()
        await self.show(interaction, len(self.slides) - 1)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.owner is None or interaction.user.id == self.owner.id or is_game_helper(interaction.user):
            return True
        try:
            await interaction.response.send_message(
                NOT_YOUR_REPLAY.format(owner=self.owner.display_name), ephemeral=True)
        except discord.HTTPException:
            pass
        return False

    async def on_timeout(self) -> None:
        """The buttons taken away, while the last click's token can still
        edit the message: a public replay outlives its view."""
        self.stop_playing()
        if self.interaction is None:
            return
        try:
            await self.interaction.edit_original_response(view=None)
        except discord.HTTPException:
            pass
