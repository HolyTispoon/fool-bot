import logging
import os, random, json
from dataclasses import dataclass, field, asdict
from dotenv import load_dotenv
import discord
from discord import app_commands
from discord.ext import commands

import botlog

load_dotenv()

# Before anything logs, and before the mirror is attached to the root
# logger. See botlog/__init__.py for the environment variables involved.
botlog.configure_logging()
LOGGER = logging.getLogger(__name__)
log_mirror = botlog.install_mirror()

TOKEN = os.getenv("DISCORD_TOKEN")
STATE_FILE = "game_state.json"

SUITS = ["$", "⚔", "〠", "⚒", "☯", "🃟"]
RANKS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "L", "R"]

@dataclass
class GameState:
    deck: list[str] = field(default_factory=list)
    discard: list[str] = field(default_factory=list)
    units: dict[str, dict] = field(default_factory=dict)  # unit -> {"x": int, "y": int}

def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            data = json.load(f)
        return GameState(**data)
    except FileNotFoundError:
        return GameState()

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(asdict(state), f, indent=2)

state = load_state()

class GameBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()

        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
        )

    async def setup_hook(self):
        LOGGER.info("Loading D12 Ball extension...")
        await self.load_extension("cogs.d12ball")
        LOGGER.info("Extension loaded.")

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

@bot.tree.command(name="newdeck", description="Create and shuffle a 72-card Foolish Style deck")
async def newdeck(interaction: discord.Interaction):
    state.deck = [f"{rank}{suit}" for suit in SUITS for rank in RANKS]
    random.shuffle(state.deck)
    state.discard = []
    save_state(state)
    await interaction.response.send_message("Shuffled a new Foolish style 72-card deck.")

@bot.tree.command(name="draw", description="Draw cards from the deck")
async def draw(interaction: discord.Interaction, count: int = 1):
    if count < 1:
        await interaction.response.send_message("You must draw at least one card.")
        return
    drawn = []
    for _ in range(min(count, len(state.deck))):
        drawn.append(state.deck.pop())
    state.discard.extend(drawn)
    save_state(state)
    await interaction.response.send_message(
        f"Drew: {', '.join(drawn) if drawn else 'deck is empty'}"
    )

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

@bot.tree.command(name="place", description="Place a unit on the board")
async def place(interaction: discord.Interaction, unit: str, x: int, y: int):
    state.units[unit] = {"x": x, "y": y}
    save_state(state)
    await interaction.response.send_message(f"Placed **{unit}** at ({x}, {y}).")

@bot.tree.command(name="move", description="Move a unit by dx, dy")
async def move(interaction: discord.Interaction, unit: str, dx: int, dy: int):
    if unit not in state.units:
        await interaction.response.send_message(f"No unit named **{unit}**.")
        return
    state.units[unit]["x"] += dx
    state.units[unit]["y"] += dy
    save_state(state)
    pos = state.units[unit]
    await interaction.response.send_message(
        f"Moved **{unit}** to ({pos['x']}, {pos['y']})."
    )

@bot.tree.command(name="board", description="Show unit positions")
async def board(interaction: discord.Interaction):
    if not state.units:
        await interaction.response.send_message("No units on the board.")
        return
    lines = [f"**{u}**: ({p['x']}, {p['y']})" for u, p in state.units.items()]
    await interaction.response.send_message("\n".join(lines))

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
