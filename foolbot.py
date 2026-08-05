import logging
import os
import random
from dotenv import load_dotenv
import discord
from discord.ext import commands

import botlog

load_dotenv()

# Before anything logs, and before the mirror is attached to the root
# logger. See botlog/__init__.py for the environment variables involved.
botlog.configure_logging()
LOGGER = logging.getLogger(__name__)
log_mirror = botlog.install_mirror()

TOKEN = os.getenv("DISCORD_TOKEN")

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

        synced = await self.tree.sync()
        LOGGER.info("Synced %d commands.", len(synced))

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
