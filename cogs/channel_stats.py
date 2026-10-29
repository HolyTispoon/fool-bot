import logging
from dataclasses import dataclass
from typing import Iterable

import discord
from discord import app_commands
from discord.ext import commands


LOGGER = logging.getLogger(__name__)

# Rows shown before the rest are summed into one line, so the table
# stays inside Discord's 2,000-character message limit.
MAX_ROWS = 25


@dataclass
class AuthorTally:
    name: str
    messages: int = 0
    words: int = 0


def word_count(text: str) -> int:
    return len(text.split())


def tally_messages(messages: Iterable[discord.Message]) -> list[AuthorTally]:
    """
    Messages and words per author, most messages first. Keyed on the
    author's id, so a rename partway through the history is one row;
    the name shown is the most recent message's.
    """
    tallies: dict[int, AuthorTally] = {}
    for message in messages:
        author = message.author
        tally = tallies.setdefault(author.id, AuthorTally(author.display_name))
        tally.messages += 1
        tally.words += word_count(message.content)
    return sorted(
        tallies.values(),
        key=lambda tally: (-tally.messages, -tally.words, tally.name.casefold()),
    )


def percent(part: int, whole: int) -> str:
    return f"{100 * part / whole:.1f}%" if whole else "0.0%"


def format_stats(channel_name: str, tallies: list[AuthorTally]) -> str:
    if not tallies:
        return f"#{channel_name} has no messages to count."

    total_messages = sum(tally.messages for tally in tallies)
    total_words = sum(tally.words for tally in tallies)
    shown = tallies[:MAX_ROWS]
    rest = tallies[MAX_ROWS:]

    name_width = min(24, max(len("User"), *(len(t.name) for t in shown)))
    header = (
        f"{'User':<{name_width}}  {'Msgs':>7} {'%':>6}  "
        f"{'Words':>8} {'%':>6}"
    )
    lines = [header, "-" * len(header)]

    def row(name: str, messages: int, words: int) -> str:
        return (
            f"{name[:name_width]:<{name_width}}  "
            f"{messages:>7} {percent(messages, total_messages):>6}  "
            f"{words:>8} {percent(words, total_words):>6}"
        )

    lines.extend(row(t.name, t.messages, t.words) for t in shown)
    if rest:
        lines.append(row(
            f"{len(rest)} others",
            sum(t.messages for t in rest),
            sum(t.words for t in rest),
        ))
    table = "\n".join(lines)
    return (
        f"**#{channel_name}**: {total_messages:,} messages, "
        f"{total_words:,} words from {len(tallies)} users\n"
        f"```\n{table}\n```"
    )


class ChannelStats(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="channel_stats",
        description="Count each user's messages and words in this channel's history.",
    )
    @app_commands.describe(
        public="Post the result in the channel for everyone. Default: only you see it.",
        include_bots="Count bots' messages too. Default: people only.",
    )
    @app_commands.guild_only()
    async def channel_stats(
        self,
        interaction: discord.Interaction,
        public: bool = False,
        include_bots: bool = False,
    ) -> None:
        # Reading a long history takes more than the three seconds an
        # interaction allows before it is acknowledged.
        await interaction.response.defer(ephemeral=not public, thinking=True)
        channel = interaction.channel
        try:
            messages = [
                message
                async for message in channel.history(limit=None)
                if include_bots or not message.author.bot
            ]
        except discord.Forbidden:
            await interaction.followup.send(
                "I can't read this channel's history.", ephemeral=True,
            )
            return
        await interaction.followup.send(
            format_stats(channel.name, tally_messages(messages)),
            ephemeral=not public,
            allowed_mentions=discord.AllowedMentions.none(),
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ChannelStats(bot))
