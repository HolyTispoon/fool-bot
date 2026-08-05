import discord
from discord import app_commands
from discord.ext import commands

from cogs.d12ball_helpers import (
    CHANNEL_NAME_PATTERN,
    PBD_ARCHIVE_CATEGORY_NAME,
)
from gamesaves.d12ball.storage import save_games


class Debug(commands.Cog):
    debug = app_commands.Group(
        name="debug",
        description="Debug and maintenance commands.",
    )

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @debug.command(
        name="reset_channels",
        description="Delete all D12 Ball PBD channels and reset numbering.",
    )
    @app_commands.describe(
        confirm='Type "confirm" to delete every D12 Ball PBD channel.',
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_channels=True)
    async def reset_channels(
        self,
        interaction: discord.Interaction,
        confirm: str,
    ) -> None:
        if confirm != "confirm":
            await interaction.response.send_message(
                'Reset cancelled. Type "confirm" in the confirm field '
                "to run this command.",
                ephemeral=True,
            )
            return

        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "This command can only be used inside a server.",
                ephemeral=True,
            )
            return

        d12ball_cog = self.bot.get_cog("D12Ball")
        if d12ball_cog is None:
            await interaction.response.send_message(
                "The D12 Ball game system is not loaded.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            guild_channels = await guild.fetch_channels()
        except (discord.Forbidden, discord.HTTPException):
            guild_channels = guild.channels

        pbd_channels = [
            channel
            for channel in guild_channels
            if isinstance(channel, discord.TextChannel)
            if CHANNEL_NAME_PATTERN.fullmatch(channel.name.lower())
            if (
                channel.category is None
                or channel.category.name.casefold()
                != PBD_ARCHIVE_CATEGORY_NAME.casefold()
            )
        ]
        archived_channel_ids = {
            channel.id
            for channel in guild_channels
            if isinstance(channel, discord.TextChannel)
            if CHANNEL_NAME_PATTERN.fullmatch(channel.name.lower())
            if (
                channel.category is not None
                and channel.category.name.casefold()
                == PBD_ARCHIVE_CATEGORY_NAME.casefold()
            )
        }
        failed_channels: list[tuple[str, str]] = []
        deleted_channels = 0

        for channel in pbd_channels:
            for attempt in range(3):
                try:
                    await channel.delete(
                        reason=(
                            "D12 Ball channel and count reset requested by "
                            f"{interaction.user}"
                        ),
                    )
                    deleted_channels += 1
                    break
                except discord.NotFound:
                    deleted_channels += 1
                    break
                except discord.Forbidden as error:
                    failed_channels.append(
                        (channel.name, f"permission denied: {error}")
                    )
                    break
                except discord.HTTPException as error:
                    if attempt == 2:
                        failed_channels.append(
                            (channel.name, f"Discord error: {error}")
                        )

        game_ids = [
            game_id
            for game_id, game in d12ball_cog.games.items()
            if (
                game.guild_id == guild.id
                and game.channel_id not in archived_channel_ids
            )
        ]

        for game_id in game_ids:
            d12ball_cog.games.pop(game_id)

        save_games(d12ball_cog.games)
        next_game_number = d12ball_cog.get_next_game_number(guild)

        result = (
            f"Deleted {deleted_channels} PBD channel(s) and "
            f"{len(game_ids)} saved game(s). "
            "The channel count has been reset; the next D12 Ball game "
            f"will be pbd{next_game_number}."
        )

        if failed_channels:
            failure_details = "\n".join(
                f"- {name}: {error}"
                for name, error in failed_channels
            )
            result += (
                "\n\nI could not delete these channels after retrying, "
                "but they will no longer affect the game count:\n"
                f"{failure_details}"
            )

        await interaction.followup.send(result, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Debug(bot))
