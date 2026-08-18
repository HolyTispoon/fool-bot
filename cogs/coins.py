import logging
import random
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from discord_emoji_cache import EMOJI_REFETCH_INTERVAL, ensure_cached_emojis


LOGGER = logging.getLogger(__name__)
COIN_EMOJI_FALLBACK = "🪙"


class CoinFace(str, Enum):
    FORTUNE = "fortune"
    DOOM = "doom"


@dataclass(frozen=True)
class Coin:
    value: int
    material: str

    @property
    def label(self) -> str:
        return f"{self.value} {self.material.title()}"

    @property
    def key(self) -> str:
        return f"{self.value}_{self.material}"

    def emoji_name(self, face: CoinFace) -> str:
        return f"{self.value}_{self.material}_{face.value}"


COINS = tuple(
    Coin(value, material)
    for value in (1, 3)
    for material in ("bronze", "silver", "gold")
)


async def load_coin_emojis(bot: commands.Bot) -> dict[str, str]:
    """Fetch all coin-face application emoji by their uploaded names."""
    try:
        emojis = await bot.fetch_application_emojis()
    except Exception as error:
        LOGGER.warning("Could not load the coin emoji: %s", error)
        return {}

    emojis_by_name = {emoji.name: str(emoji) for emoji in emojis}
    expected_names = {
        coin.emoji_name(face)
        for coin in COINS
        for face in CoinFace
    }
    missing = sorted(expected_names - emojis_by_name.keys())
    if missing:
        LOGGER.info(
            "This application has no coin emoji named %s; those coins "
            "will show %s instead.",
            ", ".join(missing),
            COIN_EMOJI_FALLBACK,
        )

    return {
        name: emojis_by_name[name]
        for name in expected_names
        if name in emojis_by_name
    }


def format_coin_emoji(
    coin_emojis: dict[str, str],
    coin: Coin,
    face: CoinFace,
) -> str:
    return coin_emojis.get(
        coin.emoji_name(face),
        COIN_EMOJI_FALLBACK,
    )


def coin_flip_result(face: CoinFace) -> str:
    return (
        "Your coin shows Fortune! You have won the coin toss!"
        if face is CoinFace.FORTUNE
        else "Your coin shows Doom! You have lost the coin toss."
    )


def find_coin(key: str) -> Optional[Coin]:
    return next((coin for coin in COINS if coin.key == key), None)


class CoinCommands(commands.GroupCog, group_name="coin"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.coin_emojis: dict[str, str] = {}
        # None rather than 0.0 -- see the same field on the D12 Ball
        # cog for why the monotonic clock makes that distinction real.
        self.coin_emojis_checked_at: Optional[float] = None

    async def cog_load(self) -> None:
        self.coin_emojis = await load_coin_emojis(self.bot)

    async def ensure_coin_emojis(self) -> dict[str, str]:
        """
        The coin emoji, retrying while any are missing so an upload
        takes effect without a restart -- but no more often than
        EMOJI_REFETCH_INTERVAL. An application with none of them
        uploaded is short of them on every flip, and the retry was
        costing an HTTP request per flip for an answer that had not
        changed since startup. The cache-with-cooldown shape is
        `ensure_cached_emojis`, shared with the D12 Ball cog; the load
        itself stays this cog's own -- see load_coin_emojis above.
        """
        self.coin_emojis, self.coin_emojis_checked_at = (
            await ensure_cached_emojis(
                self.coin_emojis,
                self.coin_emojis_checked_at,
                len(COINS) * len(CoinFace),
                lambda: load_coin_emojis(self.bot),
            )
        )
        return self.coin_emojis

    @app_commands.command(
        name="flip",
        description="Flip a bronze, silver, or gold coin.",
    )
    @app_commands.describe(
        coin="The coin to flip. Leave blank to choose one at random.",
    )
    async def flip(
        self,
        interaction: discord.Interaction,
        coin: Optional[str] = None,
    ) -> None:
        selected_coin = random.choice(COINS) if coin is None else find_coin(coin)
        if selected_coin is None:
            await interaction.response.send_message(
                "Choose one of the six coins from the autocomplete options.",
                ephemeral=True,
            )
            return

        face = random.choice(tuple(CoinFace))
        coin_emojis = await self.ensure_coin_emojis()
        await interaction.response.send_message(
            format_coin_emoji(coin_emojis, selected_coin, face),
        )
        await interaction.followup.send(coin_flip_result(face))

    @flip.autocomplete("coin")
    async def coin_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        del interaction
        search = current.casefold().strip()
        return [
            app_commands.Choice(name=coin.label, value=coin.key)
            for coin in COINS
            if not search
            or search in coin.label.casefold()
            or search in coin.key.casefold()
        ][:25]


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CoinCommands(bot))
