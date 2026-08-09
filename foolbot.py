import hashlib
import json
import logging
import os
import random
from typing import Optional
from dotenv import load_dotenv
import discord
from discord import app_commands
from discord.ext import commands

import botlog
import botstate

load_dotenv()

# Before anything logs, and before the mirror is attached to the root
# logger. See botlog/__init__.py for the environment variables involved.
botlog.configure_logging()
LOGGER = logging.getLogger(__name__)
log_mirror = botlog.install_mirror()

TOKEN = os.getenv("DISCORD_TOKEN")

# The key in data/bot_state.json holding a digest of the command tree
# last successfully registered with Discord, beside the deploy notice's
# sha and local for the same reason.
COMMAND_FINGERPRINT_KEY = "command_tree_fingerprint"


def command_tree_fingerprint(
    tree: app_commands.CommandTree,
) -> Optional[str]:
    """
    A digest of exactly what `tree.sync()` would upload, or None when
    that cannot be worked out -- in which case the caller should sync,
    which is what it did unconditionally before this existed.

    It hashes the payload rather than a list of command names because
    the payload is what Discord actually stores: renaming a parameter
    or editing a description changes it, and those are exactly the
    changes that look like nothing has happened until someone notices
    the old description still in the client.

    `_get_all_commands` is private, and reproducing sync()'s payload is
    the only way to be sure the digest covers everything it sends --
    so anything at all going wrong here returns None and syncs, rather
    than risking a fingerprint that matches while the commands differ.
    A translator would rewrite the payload after this point, so its
    presence is the same kind of "cannot tell": this bot sets none.
    """
    if tree.translator is not None:
        return None

    try:
        payload = [
            command.to_dict(tree)
            for command in tree._get_all_commands(guild=None)
        ]
        encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
    except Exception as error:
        LOGGER.info(
            "Could not fingerprint the command tree (%r); syncing it.",
            error,
        )
        return None

    return hashlib.sha256(encoded).hexdigest()


def command_sync_forced() -> bool:
    """
    True when FOOLBOT_COMMAND_SYNC asks for a sync regardless of the
    fingerprint -- the way back in when Discord's copy and this
    checkout's have drifted apart some other way, such as commands
    edited from a second checkout or a sync that was recorded as done
    and was not.
    """
    raw = os.environ.get("FOOLBOT_COMMAND_SYNC", "").strip().lower()

    return raw in ("always", "force", "on", "1", "yes")


class GameBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()

        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
        )

    async def setup_hook(self):
        LOGGER.info("Loading coins extension...")
        await self.load_extension("cogs.coins")
        LOGGER.info("Coins extension loaded.")

        LOGGER.info("Loading D12 Ball extension...")
        await self.load_extension("cogs.d12ball")
        LOGGER.info("Extension loaded.")

        LOGGER.info("Loading Tethys deck extension...")
        await self.load_extension("cogs.tethysdeck")
        LOGGER.info("Tethys deck extension loaded.")

        LOGGER.info("Loading debug extension...")
        await self.load_extension("cogs.debug")
        LOGGER.info("Debug extension loaded.")

        await self.sync_commands_if_changed()

    async def sync_commands_if_changed(self) -> None:
        """
        Register the global command tree with Discord, but only when it
        differs from the one last registered from this checkout.

        Registering global commands is among the more heavily rate
        limited things a bot can do, and setup_hook runs on every
        process start -- which across a day of testing is dozens of
        starts, every one of them uploading a command list identical to
        the last. Nothing about the commands had changed; the requests
        were the whole cost.

        The fingerprint is only written once the sync has actually
        landed, the same way the deploy notice only records a sha once
        the post has gone out: a sync that raised has not happened, and
        the next start should try it again.
        """
        fingerprint = command_tree_fingerprint(self.tree)
        forced = command_sync_forced()

        if (
            fingerprint is not None
            and not forced
            and fingerprint == botstate.read_key(COMMAND_FINGERPRINT_KEY)
        ):
            LOGGER.info(
                "The command tree is unchanged since the last sync; not "
                "syncing. Set FOOLBOT_COMMAND_SYNC=always to sync anyway.",
            )
            return

        synced = await self.tree.sync()
        LOGGER.info("Synced %d commands.", len(synced))

        if fingerprint is not None:
            botstate.write_key(COMMAND_FINGERPRINT_KEY, fingerprint)

bot = GameBot()

@bot.event
async def on_ready():
    LOGGER.info(
        "Logged in as %s (bot user ID %s)",
        bot.user,
        getattr(bot.user, "id", "unknown"),
    )
    # Both of these are guarded internally and run on every reconnect:
    # binding is idempotent, and a build announces itself once.
    await botlog.start_mirror(bot, log_mirror)
    await botlog.announce_startup(bot)

@bot.tree.command(name="roll", description="Roll dice, e.g. 2d6")
async def roll(interaction: discord.Interaction, dice: str):
    try:
        n, sides = map(int, dice.lower().split("d"))
        if n < 1 or sides < 2 or n > 100:
            raise ValueError
    except ValueError:
        await interaction.response.send_message("Use format like `1d20`, `2d6`, or `4d8`.")
        return

    rolls = [random.randint(1, sides) for _ in range(n)]
    await interaction.response.send_message(
        f"{dice}: {rolls} = **{sum(rolls)}**"
    )

if TOKEN:
    LOGGER.info("Discord token loaded (%d characters).", len(TOKEN))
    # Which token, rather than whether there is one. Kept off the
    # default level because the log channel is a place in a server, not
    # a private console.
    LOGGER.debug("Discord token starts with %s.", TOKEN[:6])
else:
    LOGGER.error("No DISCORD_TOKEN in the environment or in .env.")

# log_handler=None: configure_logging already set the root logger up,
# and letting discord.py add its own would print every library line
# twice.
bot.run(TOKEN, log_handler=None)
