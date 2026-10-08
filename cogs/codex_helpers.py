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
from typing import Optional

from discord.ext import commands

from codex import tokens
from codex.formatting import plain_token
from discord_emoji_cache import ensure_cached_emojis

LOGGER = logging.getLogger(__name__)

#: The application emoji the resolver asks for, by the name each must
#: carry in the Developer Portal -- each PNG's file name under
#: codex/images/emoji/. The heroes' are for the lines that name a hero.
EMOJI_NAMES = ("codex", "gold", "exhaust", "target", "troq_bashar", "river_montoya")

#: The token kinds an emoji stands for; `arrow` stays a character.
TOKEN_EMOJI = {"codex": "codex", "gold": "gold", "exhaust": "exhaust", "target": "target"}


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

    def resolve(self, kind: str, arguments: tuple[str, ...]) -> str:
        emoji = self.emojis.get(TOKEN_EMOJI.get(kind, ""))
        if emoji is None:
            return plain_token(kind, arguments)
        if kind == "gold":
            return f"{emoji}{arguments[0]}"
        return emoji

    def render(self, text: str) -> str:
        return tokens.render(text, self.resolve)
