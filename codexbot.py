"""
The Codex bot: Sirlin Games' Codex on Discord, its own process with its
own token beside fool-bot (docs/design/codex.md).

    python3 codexbot.py
"""

import logging
import os

from dotenv import load_dotenv

import botlog
import botstate
import gamebot

load_dotenv()

STATE_FILE = botstate.REPO_DIR / "data" / "codex_bot_state.json"
# The top-level command ids, written after each sync: fool-bot reads it
# to mention </codex lobby:ID> in its hub (docs/design/codex.md).
COMMAND_IDS_FILE = botstate.REPO_DIR / "data" / "codex_command_ids.json"

# Each CODEX_LOG_* falls back to its FOOLBOT_LOG_* value, so one .env
# and one #logs channel serve both bots (botlog/settings.py).
botlog.configure_logging(prefix="CODEX", bot_name="Codex bot", state_file=STATE_FILE)
LOGGER = logging.getLogger(__name__)
log_mirror = botlog.install_mirror()

TOKEN = os.getenv("CODEX_DISCORD_TOKEN")

bot = gamebot.GameBot(
    extensions=("cogs.codex",),
    state_file=STATE_FILE,
    sync_variable="CODEX_COMMAND_SYNC",
    # Slash commands and buttons only: no privileged intent to switch on.
    message_content=False,
    command_ids_file=COMMAND_IDS_FILE,
)


@bot.event
async def on_ready():
    LOGGER.info("Logged in as %s (bot user ID %s)", bot.user, getattr(bot.user, "id", "unknown"))
    await botlog.start_mirror(bot, log_mirror)
    await botlog.announce_gateway_recovery(bot)
    await botlog.announce_startup(bot, STATE_FILE)


@bot.event
async def on_resumed():
    await botlog.announce_gateway_recovery(bot)


if __name__ == "__main__":
    if TOKEN:
        LOGGER.info("Codex token loaded (%d characters).", len(TOKEN))
    else:
        LOGGER.error("No CODEX_DISCORD_TOKEN in the environment or in .env.")
    bot.run(TOKEN, log_handler=None)
