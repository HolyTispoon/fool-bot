import asyncio
import logging
from pathlib import Path
from typing import NamedTuple

import discord
from discord import app_commands
from discord.ext import commands

from cogs.d12ball_helpers import (
    CHANNEL_NAME_PATTERN,
    PBD_ARCHIVE_CATEGORY_NAME,
    build_game_channel_name,
    send_error_fallback,
)
import botlog
from d12ball.game import D12BallGame, GameStatus
from gamesaves.d12ball.archive_export import archive_export_dir, write_game_export
from gamesaves.d12ball.storage import save_games


LOGGER = logging.getLogger(__name__)

# How long to wait before each retry of a channel delete that Discord
# refused.
#
# Deleting a channel sits in the channel-modification bucket, which is
# the most restrictive limit Discord documents -- two per ten minutes,
# and **per channel**: `channel_id` is one of discord.py's four major
# rate-limit parameters (`discord.http.Route.major_parameters`), so
# fifty different channels are fifty separate buckets rather than one
# queue two deep. Only a repeat request against the *same* channel is
# rationed -- which is exactly what a retry is, and the whole of why
# these delays exist.
#
# discord.py does the waiting for an ordinary 429 itself, so a plain
# rate limit never reaches this loop at all; what does reach it is a
# Discord-side failure it gave up on, or a Cloudflare ban, which is
# what too many rejected requests in ten minutes earns. Retrying
# either of those immediately, which is what this used to do three
# times in a row per channel, is how a rate limit turns into a ban.
CHANNEL_DELETE_RETRY_DELAYS = (2.0, 8.0)


async def defer_or_report(interaction: discord.Interaction) -> bool:
    """
    Acknowledge the interaction, and if Discord has already thrown it
    away, say **why** rather than raising a traceback that names only
    the symptom.

    Discord invalidates an interaction nothing has acknowledged within
    three seconds, and `defer` is then a 404 (error code 10062,
    "Unknown interaction"). Raised out of the first line of a command,
    that reads as a bug in the command -- it is not, and cannot be:
    nothing of ours has run yet. Only two things put a dead token
    there. Either the bot took longer than three seconds to reach this
    line (a blocked event loop, a stalled gateway), or something else
    had already answered that interaction, which for a token this bot
    has never used means a **second process signed in on the same
    token** -- two checkouts, or one started twice.

    Those two want opposite fixes, and the age of the interaction tells
    them apart. It is readable to the microsecond off the snowflake:
    Discord stamps the id with its own creation time, so the gap
    between that and now is exactly how long this interaction spent
    waiting for the bot. Three seconds or more is the first case; a
    handful of milliseconds is the second, because a token that young
    can only have been spent by somebody else.

    Logged at ERROR, so it reaches #logs. This is precisely the kind of
    failure nobody can act on from the symptom alone -- see "The level
    you log at decides who sees it" in docs/design/logging.md.
    """
    try:
        await interaction.response.defer(ephemeral=True)
        return True
    except discord.NotFound:
        age = (
            discord.utils.utcnow() - discord.utils.snowflake_time(interaction.id)
        ).total_seconds()
        command_name = (
            interaction.command.qualified_name
            if interaction.command is not None
            else "unknown command"
        )
        LOGGER.error(
            "Discord had already discarded the interaction for /%s "
            "(10062) by the time the bot acknowledged it, %.2fs after "
            "Discord created it. Three seconds or more means this bot "
            "was too busy to answer in time; a fraction of a second "
            "means a second process is signed in on the same token and "
            "answered first. Nothing ran, and nothing was deleted.",
            command_name, age,
        )
        return False


async def delete_channel_with_retries(
    channel: discord.abc.GuildChannel, reason: str,
) -> str | None:
    """
    Delete `channel`, retrying on the backoff in
    `CHANNEL_DELETE_RETRY_DELAYS` -- see the comment on that constant
    for why the delays exist and why they only lengthen.

    Returns `None` once Discord has confirmed the channel is gone (a
    delete that lands, or a `discord.NotFound` -- already gone counts
    as landed, since either way there is nothing left to retry).
    Returns the failure text for a `failed_channels`/`failures` entry
    otherwise: `"permission denied: ..."` for a `discord.Forbidden`,
    which is not worth retrying and stops on the first attempt, or
    `"Discord error: ..."` once every retry is spent.
    """
    for attempt in range(len(CHANNEL_DELETE_RETRY_DELAYS) + 1):
        if attempt:
            await asyncio.sleep(CHANNEL_DELETE_RETRY_DELAYS[attempt - 1])
        try:
            await channel.delete(reason=reason)
            return None
        except discord.NotFound:
            return None
        except discord.Forbidden as error:
            return f"permission denied: {error}"
        except discord.HTTPException as error:
            if attempt == len(CHANNEL_DELETE_RETRY_DELAYS):
                return f"Discord error: {error}"
    return None


class ExportOneGameResult(NamedTuple):
    exported: bool
    deleted: bool
    failure: tuple[str, str] | None


async def collect_export_candidates(
    guild: discord.Guild, cog, limit: int,
) -> list[tuple[D12BallGame, discord.TextChannel]]:
    """
    Every finished D12 Ball game `cog` still tracks for `guild` whose
    channel is currently sitting in the PBD Archive category, oldest
    `game_number` first and cut to `limit` -- any archived channel
    freed makes the same room, so there is no other reason to prefer
    one game over another. A game whose channel already vanished is
    left for the startup sweep to prune, with nothing here left to
    export.
    """
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

    # Oldest game_number first: any archived channel freed makes the
    # same room, so this is about tidying the oldest history first
    # rather than anything a coach would notice.
    return sorted(
        (
            (game, archived_channels_by_id[game.channel_id])
            for game in cog.games.values()
            if game.guild_id == guild.id
            and game.status == GameStatus.FINISHED
            and game.channel_id in archived_channels_by_id
        ),
        key=lambda pair: pair[0].game_number,
    )[:limit]


async def read_channel_transcript(
    channel: discord.TextChannel, game_id: str,
) -> tuple[list[dict], list[tuple[str, bytes]]]:
    """
    Walk `channel`'s whole history oldest-first and download every
    attachment along the way. Raises `discord.Forbidden` or
    `discord.HTTPException` straight through -- `export_one_game`
    already catches those to leave the channel and the game alone. A
    single attachment that fails to download is logged and skipped
    rather than failing the whole transcript.
    """
    transcript: list[dict] = []
    attachments: list[tuple[str, bytes]] = []
    async for message in channel.history(limit=None, oldest_first=True):
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
                    game_id, error,
                )
                continue
            attachments.append((filename, data))
            entry["attachments"].append(filename)
        transcript.append(entry)
    return transcript, attachments


async def export_one_game(
    cog,
    game: D12BallGame,
    channel: discord.TextChannel,
    export_dir: Path,
    actor: object,
) -> ExportOneGameResult:
    """
    Export one archived game to `export_dir` and only then delete its
    channel. **The export has to land before the channel dies, never
    after** -- render, transcript and write all happen first, and a
    failure at any of those three returns a failure reason with that
    game's channel and save record completely untouched. Losing a
    channel Discord will never give back over a write that could be
    retried is the one failure mode this whole feature exists to
    avoid, so this ordering does not change.
    """
    try:
        board_png = await cog.render_match_png(game)
    except Exception as error:
        LOGGER.warning(
            "Could not render the final board for D12 Ball "
            "game %s while exporting it: %s",
            game.game_id, error,
        )
        board_png = None

    try:
        transcript, attachments = await read_channel_transcript(
            channel, game.game_id,
        )
    except (discord.Forbidden, discord.HTTPException) as error:
        return ExportOneGameResult(
            exported=False,
            deleted=False,
            failure=(channel.name, f"could not read its history: {error}"),
        )

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
        return ExportOneGameResult(
            exported=False,
            deleted=False,
            failure=(channel.name, f"could not write its export: {error}"),
        )

    error_text = await delete_channel_with_retries(
        channel,
        reason=(
            "D12 Ball game exported to disk and deleted "
            f"from the PBD Archive by {actor}"
        ),
    )
    if error_text is None:
        cog.games.pop(game.game_id, None)
        return ExportOneGameResult(exported=True, deleted=True, failure=None)

    return ExportOneGameResult(
        exported=True, deleted=False, failure=(channel.name, error_text),
    )


class Debug(commands.Cog):
    # The permission gate has to sit on the **group**, not on the
    # subcommands. Discord only carries `default_member_permissions`
    # and `dm_permission`/`contexts` on a top-level command, and
    # discord.py's own `Command.to_dict` says so: it fills those keys
    # in only `if self.parent is None`. So the
    # `@app_commands.default_permissions(...)` and
    # `@app_commands.guild_only()` that used to sit on
    # `reset_channels` and `export_archived_games` were read by
    # nothing -- the decorators applied, the attributes were set, and
    # the payload Discord was sent carried neither. Both commands were
    # therefore visible to, and runnable by, every member of the
    # server, which for two commands whose whole job is deleting
    # channels is the wrong way round.
    #
    # `manage_channels` is the wider of the two gates the subcommands
    # wanted, and Discord has no way to express a narrower one per
    # subcommand -- so `export_archived_games` re-checks for
    # Administrator itself at runtime. Either gate is only Discord's
    # *default*; a server can widen or narrow it per-role in
    # Integrations settings.
    debug = app_commands.Group(
        name="debug",
        description="Debug and maintenance commands.",
        guild_only=True,
        default_permissions=discord.Permissions(manage_channels=True),
    )

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        """
        Report an unexpected failure back to whoever ran the command,
        the way `D12Ball.cog_app_command_error` does for a coach.

        Both commands in this file defer first, so without this a
        crash anywhere below the defer leaves the caller looking at an
        ephemeral "thinking" spinner that never resolves -- and the
        traceback only reaches the console and #logs, which is on the
        machine hosting the bot rather than in front of the person who
        pressed the button. These two are the most destructive
        commands the bot has; "it gave an error" has to be answerable
        without going to look at a log.

        Unlike the coach-facing one, this **names the exception**. The
        audience is whoever is allowed to delete channels, the reason
        is the whole of what they need, and there is no `/d12ball
        resume` to point them at.
        """
        original = getattr(error, "original", error)
        command_name = (
            interaction.command.qualified_name
            if interaction.command is not None
            else "unknown command"
        )
        LOGGER.error(
            "Unhandled error in /%s: %r",
            command_name, original, exc_info=original,
        )
        await send_error_fallback(
            interaction,
            f"`/{command_name}` failed: "
            f"`{type(original).__name__}: {original}`. Nothing was "
            "deleted after the point it failed. The full traceback is "
            "on the bot's console and in #logs.",
        )

    @debug.command(
        name="reset_channels",
        description="Delete all D12 Ball PBD channels and reset numbering.",
    )
    @app_commands.describe(
        confirm='Type "confirm" to delete every D12 Ball PBD channel.',
    )
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
        if not await defer_or_report(interaction):
            return

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
            error_text = await delete_channel_with_retries(
                channel,
                reason=(
                    "D12 Ball channel and count reset requested by "
                    f"{interaction.user}"
                ),
            )
            if error_text is None:
                deleted_channels += 1
            else:
                failed_channels.append((channel.name, error_text))

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
        limit="How many archived games to process this run (default 50).",
    )
    async def export_archived_games(
        self,
        interaction: discord.Interaction,
        confirm: str,
        limit: app_commands.Range[int, 1, 50] = 50,
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

        That gate is checked **here, in the body**, because Discord
        cannot express one per subcommand: `default_member_permissions`
        rides on the top-level `/debug` group alone, which is set to
        `manage_channels` for the pair of them (see the comment on the
        group). A decorator on this function set an attribute nothing
        ever sent, so for two releases this command was runnable by
        every member of the server.

        **Authorization comes before the `confirm` check**, and it is
        the one thing that does. Somebody who may not run this command
        should be told that and nothing else -- not walked through what
        it would have done, and not handed the export path. Every
        *operational* refusal below still comes after confirm.

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

        **That did not fix the failure it was written for**, and could
        not have: the live 10062 was raised *by the defer itself*, on
        the command's first line, before anything of ours had run. See
        `defer_or_report`, which is what says so in the log rather than
        raising a traceback that names the symptom.

        **`confirm` is checked before anything else that can refuse**,
        including whether an export directory is even configured --
        the first thing typing the command wrong should tell a coach
        is that they typed it wrong, not some other unrelated reason it
        wouldn't have worked anyway.

        The refusal says that and stops. It used to restate what the
        command was about to do -- how many games, out of where, to
        which directory, and that the channels would not survive it --
        which is a briefing, and the person reading it has just been
        told their command did not run. What they need is which field
        was wrong. The description on `confirm` carries the warning,
        where it is read *before* the command is sent rather than after
        it has failed.
        """
        if not await defer_or_report(interaction):
            return

        permissions = getattr(interaction.user, "guild_permissions", None)
        if permissions is None or not permissions.administrator:
            await interaction.followup.send(
                "This command needs the Administrator permission: it "
                "downloads a game channel's whole history and then "
                "permanently deletes the channel.",
                ephemeral=True,
            )
            return

        export_dir = archive_export_dir()

        if confirm != "confirm":
            await interaction.followup.send(
                'This command has to be confirmed with "confirm" in the '
                "confirm field. It did not go through because the "
                "confirmation was missing.",
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

        candidates = await collect_export_candidates(guild, d12ball_cog, limit)

        if not candidates:
            await interaction.followup.send(
                "No finished games in the PBD Archive were found to "
                "export.",
                ephemeral=True,
            )
            return

        # #logs, not the invoking channel, and at both ends.
        #
        # A full run walks fifty channels' histories and every
        # attachment in them, which outlives the fifteen-minute
        # interaction token -- so the summary the command would have
        # replied with is exactly the thing most likely to be lost, on
        # exactly the runs that matter most. These two lines are not
        # errors, so they cannot go through the logger without breaking
        # what an ERROR in that channel means; `botlog.post_notice` is
        # the deliberate, non-error way in. It is opt-in with the rest
        # of the mirror and never raises, so a bot that posts nothing
        # exports exactly as before.
        await botlog.post_notice(
            self.bot,
            f"**Archive export started** by {interaction.user} in "
            f"{guild.name}: {len(candidates)} finished game(s) from the "
            f"PBD Archive to `{export_dir}`. Their channels are deleted "
            "once each export is written.",
        )

        exported = 0
        deleted = 0
        failures: list[tuple[str, str]] = []

        for game, channel in candidates:
            game_result = await export_one_game(
                d12ball_cog, game, channel, export_dir, interaction.user,
            )
            if game_result.exported:
                exported += 1
            if game_result.deleted:
                deleted += 1
            if game_result.failure is not None:
                failures.append(game_result.failure)

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

        await botlog.post_notice(self.bot, f"**Archive export finished.** {result}")

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
