import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from cogs.d12ball_helpers import (
    CHANNEL_NAME_PATTERN,
    PBD_ARCHIVE_CATEGORY_NAME,
    build_game_channel_name,
)
from d12ball.game import GameStatus
from gamesaves.d12ball.archive_export import archive_export_dir, write_game_export
from gamesaves.d12ball.storage import save_games


LOGGER = logging.getLogger(__name__)

# How long to wait before each retry of a channel delete that Discord
# refused.
#
# Deleting a channel sits in the channel-modification bucket, which is
# the most restrictive limit Discord documents -- two per ten minutes.
# discord.py does the waiting for an ordinary 429 itself, so a plain
# rate limit never reaches this loop at all; what does reach it is a
# Discord-side failure it gave up on, or a Cloudflare ban, which is
# what too many rejected requests in ten minutes earns. Retrying
# either of those immediately, which is what this used to do three
# times in a row per channel, is how a rate limit turns into a ban.
CHANNEL_DELETE_RETRY_DELAYS = (2.0, 8.0)


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
        """
        Deferred before any check runs, so a refusal below always
        answers through the followup webhook rather than racing
        Discord's three-second limit on an un-acknowledged interaction
        -- see the same note on `export_archived_games`.
        """
        await interaction.response.defer(ephemeral=True)

        if confirm != "confirm":
            await interaction.followup.send(
                'Reset cancelled. Type "confirm" in the confirm field '
                "to run this command.",
                ephemeral=True,
            )
            return

        guild = interaction.guild
        if guild is None:
            await interaction.followup.send(
                "This command can only be used inside a server.",
                ephemeral=True,
            )
            return

        d12ball_cog = self.bot.get_cog("D12Ball")
        if d12ball_cog is None:
            await interaction.followup.send(
                "The D12 Ball game system is not loaded.",
                ephemeral=True,
            )
            return

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
            for attempt in range(len(CHANNEL_DELETE_RETRY_DELAYS) + 1):
                if attempt:
                    await asyncio.sleep(
                        CHANNEL_DELETE_RETRY_DELAYS[attempt - 1]
                    )
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
                    if attempt == len(CHANNEL_DELETE_RETRY_DELAYS):
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

        try:
            await interaction.followup.send(result, ephemeral=True)
        except discord.HTTPException as error:
            # An interaction token is good for fifteen minutes, and the
            # rate limit on deleting channels means a reset of more
            # than a handful outlives it. The reset itself has already
            # happened and been saved -- only the report is lost, so it
            # goes to the console rather than being raised at someone.
            LOGGER.info(
                "Could not report the D12 Ball channel reset back to "
                "Discord (%s). %s",
                error,
                result,
            )


    @debug.command(
        name="export_archived_games",
        description=(
            "Export finished PBD Archive games to disk, then delete "
            "their channels to free category room."
        ),
    )
    @app_commands.describe(
        confirm='Type "confirm" to export and delete channels.',
        limit="How many archived games to process this run (default 5).",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    async def export_archived_games(
        self,
        interaction: discord.Interaction,
        confirm: str,
        limit: app_commands.Range[int, 1, 20] = 5,
    ) -> None:
        """
        Discord caps a category at 50 channels (see "Could not archive
        finished D12 Ball game ...: Maximum number of channels in
        category reached" in the console/#logs), and PBD Archive fills
        up with games nobody is ever going to look at in Discord again.
        This is the way out: write everything the channel and the save
        file know about a game to local disk -- the game/match record,
        the final board, and the whole channel transcript with its
        attachments -- and only once that has actually landed does it
        delete the channel. A failed export leaves the channel
        untouched rather than losing the game to make room for a new
        one.

        `FOOLBOT_D12BALL_ARCHIVE_EXPORT_DIR` is the switch: unset, this
        command refuses outright, the same opt-in-by-.env shape as the
        #logs mirror. There is no Google Drive API call here -- set it
        to a folder inside the mounted Drive letter the live bot
        already runs from, and the export reaches Drive exactly the
        way the checkout and the saved games already do.

        **Gated to Administrator, not `manage_channels`** like
        `reset_channels`. This one downloads a channel's whole message
        history and then permanently deletes it -- reset_channels only
        deletes, with nothing to lose beyond the channel itself -- so
        it gets the narrower gate.

        **Deferred before anything else runs**, unlike every other
        check in this file. Discord invalidates an interaction it has
        waited three seconds on with no acknowledgement at all, and
        every refusal below it (a missing confirm, no export
        directory) used to answer with a fresh `response.send_message`
        that could lose that race under load -- a channel-heavy guild
        with a nearly full archive is exactly the case likely to be
        slow enough to hit it. Deferring first means every branch
        below answers through the followup webhook instead, which has
        no three-second clock on it.

        **`confirm` is checked before anything else that can refuse**,
        including whether an export directory is even configured --
        the first thing typing the command wrong should tell a coach
        is that they typed it wrong, not some other unrelated reason it
        wouldn't have worked anyway.
        """
        await interaction.response.defer(ephemeral=True)

        export_dir = archive_export_dir()

        if confirm != "confirm":
            destination = f" to {export_dir}" if export_dir is not None else ""
            await interaction.followup.send(
                'Cancelled. Type "confirm" in the confirm field to '
                f"export up to {limit} finished game(s) from the PBD "
                f"Archive{destination} and then **permanently "
                "delete** their channels. Archiving keeps the channel; "
                "this does not.",
                ephemeral=True,
            )
            return

        if export_dir is None:
            await interaction.followup.send(
                "FOOLBOT_D12BALL_ARCHIVE_EXPORT_DIR is not set in this "
                "bot's .env, so there is nowhere to export games to. Set "
                "it to a folder (e.g. one inside the mounted Google "
                "Drive letter) and restart the bot before running this "
                "again.",
                ephemeral=True,
            )
            return

        guild = interaction.guild
        if guild is None:
            await interaction.followup.send(
                "This command can only be used inside a server.",
                ephemeral=True,
            )
            return

        d12ball_cog = self.bot.get_cog("D12Ball")
        if d12ball_cog is None:
            await interaction.followup.send(
                "The D12 Ball game system is not loaded.",
                ephemeral=True,
            )
            return

        try:
            guild_channels = await guild.fetch_channels()
        except (discord.Forbidden, discord.HTTPException):
            guild_channels = guild.channels

        archived_channels_by_id = {
            channel.id: channel
            for channel in guild_channels
            if isinstance(channel, discord.TextChannel)
            if CHANNEL_NAME_PATTERN.fullmatch(channel.name.lower())
            if (
                channel.category is not None
                and channel.category.name.casefold()
                == PBD_ARCHIVE_CATEGORY_NAME.casefold()
            )
        }

        # Oldest game_number first: any archived channel freed makes
        # the same room, so this is about tidying the oldest history
        # first rather than anything a coach would notice.
        candidates = sorted(
            (
                (game, archived_channels_by_id[game.channel_id])
                for game in d12ball_cog.games.values()
                if game.guild_id == guild.id
                and game.status == GameStatus.FINISHED
                and game.channel_id in archived_channels_by_id
            ),
            key=lambda pair: pair[0].game_number,
        )[:limit]

        if not candidates:
            await interaction.followup.send(
                "No finished games in the PBD Archive were found to "
                "export.",
                ephemeral=True,
            )
            return

        exported = 0
        deleted = 0
        failures: list[tuple[str, str]] = []

        for game, channel in candidates:
            try:
                board_png = await d12ball_cog.render_match_png(game)
            except Exception as error:
                LOGGER.warning(
                    "Could not render the final board for D12 Ball "
                    "game %s while exporting it: %s",
                    game.game_id, error,
                )
                board_png = None

            transcript: list[dict] = []
            attachments: list[tuple[str, bytes]] = []
            try:
                async for message in channel.history(
                    limit=None, oldest_first=True,
                ):
                    entry = {
                        "id": message.id,
                        "created_at": message.created_at.isoformat(),
                        "author": str(message.author),
                        "author_id": message.author.id,
                        "content": message.content,
                        "attachments": [],
                    }
                    for attachment in message.attachments:
                        filename = f"{message.id}-{attachment.filename}"
                        try:
                            data = await attachment.read()
                        except (discord.HTTPException, discord.NotFound) as error:
                            LOGGER.warning(
                                "Could not download an attachment from "
                                "D12 Ball game %s: %s",
                                game.game_id, error,
                            )
                            continue
                        attachments.append((filename, data))
                        entry["attachments"].append(filename)
                    transcript.append(entry)
            except (discord.Forbidden, discord.HTTPException) as error:
                failures.append(
                    (channel.name, f"could not read its history: {error}")
                )
                continue

            dest = export_dir / build_game_channel_name(
                game.game_number,
                game.player_1_name or "",
                game.player_2_name or "",
                game.game_name,
            )
            try:
                write_game_export(
                    dest,
                    game_data=game.to_dict(),
                    board_png=board_png,
                    transcript=transcript,
                    attachments=attachments,
                )
            except OSError as error:
                failures.append(
                    (channel.name, f"could not write its export: {error}")
                )
                continue

            exported += 1

            for attempt in range(len(CHANNEL_DELETE_RETRY_DELAYS) + 1):
                if attempt:
                    await asyncio.sleep(
                        CHANNEL_DELETE_RETRY_DELAYS[attempt - 1]
                    )
                try:
                    await channel.delete(
                        reason=(
                            "D12 Ball game exported to disk and deleted "
                            f"from the PBD Archive by {interaction.user}"
                        ),
                    )
                    deleted += 1
                    d12ball_cog.games.pop(game.game_id, None)
                    break
                except discord.NotFound:
                    deleted += 1
                    d12ball_cog.games.pop(game.game_id, None)
                    break
                except discord.Forbidden as error:
                    failures.append(
                        (channel.name, f"permission denied: {error}")
                    )
                    break
                except discord.HTTPException as error:
                    if attempt == len(CHANNEL_DELETE_RETRY_DELAYS):
                        failures.append(
                            (channel.name, f"Discord error: {error}")
                        )

        if exported:
            save_games(d12ball_cog.games)

        result = (
            f"Exported {exported} game(s) to {export_dir} and deleted "
            f"{deleted} channel(s) from the PBD Archive."
        )

        if failures:
            failure_details = "\n".join(
                f"- {name}: {error}" for name, error in failures
            )
            result += (
                "\n\nThese games were left alone -- their channel and "
                f"save data are unchanged:\n{failure_details}"
            )

        try:
            await interaction.followup.send(result, ephemeral=True)
        except discord.HTTPException as error:
            # A batch of exports plus channel deletes can outlive a
            # fifteen-minute interaction token, the same reason
            # reset_channels falls back to the console here.
            LOGGER.info(
                "Could not report the D12 Ball archive export back to "
                "Discord (%s). %s",
                error,
                result,
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Debug(bot))
