import logging
import os
import random
from dotenv import load_dotenv
import discord

import botlog
import botstate
import gamebot
# Re-exported, as the names tests/test_command_sync.py patches on this
# module; the class and the gate are gamebot.py's.
from gamebot import COMMAND_FINGERPRINT_KEY, command_tree_fingerprint

load_dotenv()

# Before anything logs, and before the mirror is attached to the root
# logger. See botlog/__init__.py for the environment variables involved.
botlog.configure_logging(prefix="FOOLBOT", bot_name="fool-bot")
LOGGER = logging.getLogger(__name__)
log_mirror = botlog.install_mirror()

TOKEN = os.getenv("DISCORD_TOKEN")

EXTENSIONS = ("cogs.coins", "cogs.d12ball", "cogs.tethysdeck", "cogs.debug")
COMMAND_SYNC_VARIABLE = "FOOLBOT_COMMAND_SYNC"


def command_sync_forced() -> bool:
    """True when FOOLBOT_COMMAND_SYNC asks for a sync regardless of the
    fingerprint (gamebot.command_sync_forced)."""
    return gamebot.command_sync_forced(COMMAND_SYNC_VARIABLE)


class GameBot(gamebot.GameBot):
    """
    fool-bot: the four extensions, data/bot_state.json, and the
    message-content intent, which a game channel's export needs to show
    the players' chat.
    """

    def __init__(self):
        super().__init__(
            extensions=EXTENSIONS,
            state_file=None,
            sync_variable=COMMAND_SYNC_VARIABLE,
            message_content=True,
        )

    async def sync_commands_if_changed(self) -> None:
        # This module's names and botstate's default file, read at call
        # time, so the sync gate's tests can stand each in.
        await gamebot.sync_command_tree(
            self.tree,
            fingerprint=command_tree_fingerprint(self.tree),
            forced=command_sync_forced(),
            state_file=botstate.STATE_FILE,
            sync_variable=COMMAND_SYNC_VARIABLE,
        )

bot = GameBot()

@bot.event
async def on_ready():
    LOGGER.info(
        "Logged in as %s (bot user ID %s)",
        bot.user,
        getattr(bot.user, "id", "unknown"),
    )
    # All three are guarded internally and run on every reconnect:
    # binding is idempotent, a recovery is only announced when the
    # outage was, and a build announces itself once.
    await botlog.start_mirror(bot, log_mirror)
    await botlog.announce_gateway_recovery(bot)
    await botlog.announce_startup(bot)

@bot.event
async def on_resumed():
    """
    The other way back from a dropped connection, and the common one:
    discord.py resumes the session where it can and only re-identifies
    (which is what fires on_ready) when the gateway refuses. So an
    outage announced in #logs would go unresolved there if this event
    were left out. See botlog/gateway.py.
    """
    await botlog.announce_gateway_recovery(bot)

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
