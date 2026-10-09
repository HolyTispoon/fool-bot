"""
What the Codex cog draws the model's tokens with.

The model writes `{exhaust}`, `{target}`, `{gold:2}`, `{arrow}` and
`{codex}` (`codex/tokens.py`); this renders each once, at the cog's door,
as the Codex application's own emoji where it has been uploaded and as a
word where it has not. Application emoji belong to one application and
are uploaded by hand in the Developer Portal -- there is no upload code
-- so the PNGs are drawn into `codex/images/emoji/` by
`scripts/render_codex_emoji.py` and each is picked up by its file name
once it is there, the way `cogs/d12ball_helpers.py`'s loaders fall back.
"""

import logging
import re
from typing import TYPE_CHECKING, Optional

from discord.ext import commands

from codex import tokens
from codex.cards import catalog
from codex.formatting import plain_token
from cogs.game_auth import (  # noqa: F401 -- the shared gates, for the Codex views
    game_participant_ids,
    is_game_helper,
    may_act_for_coach,
    may_act_in_game,
    send_new_prompt,
)
from cogs.d12ball_helpers import get_or_create_category, slugify_channel_part
from discord_emoji_cache import ensure_cached_emojis

if TYPE_CHECKING:
    from codex.game import CodexGame

LOGGER = logging.getLogger(__name__)

#: The application emoji the resolver asks for, by the name each must
#: carry in the Developer Portal -- each PNG's file name under
#: codex/images/emoji/. The heroes' are for the lines that name a hero.
EMOJI_NAMES = ("codex", "gold", "exhaust", "target", "troq_bashar", "river_montoya")

#: The token kinds an emoji stands for; `arrow` stays a character.
TOKEN_EMOJI = {"codex": "codex", "gold": "gold", "exhaust": "exhaust", "target": "target"}

# -- Channels ----------------------------------------------------------------
#
# The Codex bot's own categories, not D12 Ball's: `/debug`'s reset and the
# pin rollover match PBD's by name, and PBD's fifty-channel cap is D12
# Ball's (docs/design/codex.md, "The channel").

CODEX_GAMES_CATEGORY_NAME = "Codex Games"
CODEX_ARCHIVE_CATEGORY_NAME = "Codex Archive"
#: Discord's limit on a channel's name.
CHANNEL_NAME_MAX_LENGTH = 100
#: `codex-<n>`, then the players: the number is what identifies the game.
CHANNEL_NAME_PATTERN = re.compile(r"^codex-(\d+)(?:-|$)")
#: The board's file name begins with this, so the pin rollover knows the
#: Codex bot's boards.
BOARD_IMAGE_FILENAME_PREFIX = "codex-"


def channel_name(game: "CodexGame") -> str:
    """`codex-<n>-<p1>-vs-<p2>`, capped at Discord's 100 characters."""
    prefix = f"codex-{game.game_number}"
    suffix = "-vs-".join(
        part for part in (
            slugify_channel_part(game.player_1_name or ""),
            slugify_channel_part(game.player_2_name or ""),
        ) if part
    )
    if not suffix:
        return prefix
    return f"{prefix}-{suffix}"[:CHANNEL_NAME_MAX_LENGTH].rstrip("-")


async def codex_games_category(guild):
    return await get_or_create_category(
        guild, CODEX_GAMES_CATEGORY_NAME, "Create the category for Codex games.",
    )


async def codex_archive_category(guild):
    """Where a finished or abandoned game's channel is moved and left."""
    return await get_or_create_category(
        guild, CODEX_ARCHIVE_CATEGORY_NAME, "Create the category for finished Codex games.",
    )


async def load_codex_emojis(bot: commands.Bot) -> dict[str, str]:
    """The uploaded emoji of `EMOJI_NAMES`, by name, as Discord writes
    them; whatever is missing is left to the word."""
    try:
        emojis = await bot.fetch_application_emojis()
    except Exception as error:
        LOGGER.warning("Could not load the Codex emoji: %s", error)
        return {}
    found = {emoji.name: str(emoji) for emoji in emojis if emoji.name in EMOJI_NAMES}
    missing = sorted(set(EMOJI_NAMES) - found.keys())
    if missing:
        LOGGER.info("Codex emoji not uploaded yet, shown as words: %s", ", ".join(missing))
    return found


class CodexTokens:
    """The one resolver from the model's tokens to what Discord shows."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.emojis: dict[str, str] = {}
        self.checked_at: Optional[float] = None

    async def refresh(self) -> None:
        self.emojis, self.checked_at = await ensure_cached_emojis(
            self.emojis,
            self.checked_at,
            len(EMOJI_NAMES),
            lambda: load_codex_emojis(self.bot),
        )

    def resolve(self, kind: str, arguments: tuple[str, ...],
                game: "Optional[CodexGame]" = None) -> str:
        """
        One token as Discord shows it. `{player:n}` is the seat's name
        on `game`'s record; `{to:n}` the seat's player as a mention; `{card:slug}` the card's name in bold;
        `{hero:slug}` the hero's emoji, where uploaded, before its name.
        """
        if kind == "player":
            name = game.seat_name(int(arguments[0])) if game is not None else None
            return name or plain_token(kind, arguments)
        if kind == "to":
            seat = int(arguments[0])
            player_id = None if game is None else (game.player_1_id if seat == 1 else game.player_2_id)
            if player_id:
                return f"<@{player_id}>"
            name = game.seat_name(seat) if game is not None else None
            return name or plain_token(kind, arguments)
        if kind == "card":
            return f"**{plain_token(kind, arguments)}**"
        if kind == "hero":
            emoji = self.emojis.get(arguments[0])
            name = f"**{plain_token(kind, arguments)}**"
            return f"{emoji} {name}" if emoji else name
        emoji = self.emojis.get(TOKEN_EMOJI.get(kind, ""))
        if emoji is None:
            return plain_token(kind, arguments)
        if kind == "gold":
            return f"{emoji}{arguments[0]}"
        return emoji

    def render(self, text: str, game: "Optional[CodexGame]" = None) -> str:
        """Every token in `text`, drawn once, at the cog's door."""
        return tokens.render(text, lambda kind, arguments: self.resolve(kind, arguments, game))


def card_name(slug: str) -> str:
    """A card's name, for a list of the player's own cards."""
    return catalog().name(slug)
