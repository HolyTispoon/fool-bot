"""
The Codex cog's own machinery: its games and engine, the service and
the locks, re-arming the persistent views on startup, the tokens drawn
at the door, and `present` -- the one presenter over a `GameResult`
(copied from `cogs/d12ball/core.py`'s shape; docs/codex-bot.md,
decision 2).

**The turn message is the one public message per turn** (decision 5):
`present` adds what a result said to the turn's lines and writes the
board and the lines through the gate (`cogs.d12ball_boards.BoardRefresher`).
A cascade of the bot's own steps is one result, so one write. Nothing
here decides a rule.
"""

from __future__ import annotations

import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from codex.engine import RulesEngine
from codex.flow.driver import MODEL_STEPS  # noqa: F401 -- the package-shape ratchet reads it
from codex.game import CodexGame, GameStatus
from codex.prompts import PendingPrompt, PromptKind, owed_step
from cogs.codex_helpers import CodexTokens
from cogs.codex_views import ERROR_RECOVERY_ADVICE, LobbyView, TurnMessageView, send_ephemeral
from cogs.d12ball_boards import BoardRefresher
from gamelocks import GameLocks
from gamesaves.codex.service import Batching, GameResult, GameService
from gamesaves.codex.storage import load_games

LOGGER = logging.getLogger(__name__)

#: Discord's limit on a message's text.
MESSAGE_LIMIT = 2000


class DiscordBatching(Batching):
    """
    The Codex frontend's batching: none. A turn is one message, edited,
    so every line a run says joins the turn's lines and nothing is a
    message of its own; the bot's own steps run through without a stop.
    """


#: The view each prompt kind is answered from on Discord. In step 3 a
#: main-phase prompt is answered from the turn message's buttons; step 4
#: brings the panel each kind opens.
PROMPT_VIEWS = {
    PromptKind.MAIN_ACTION: TurnMessageView,
    PromptKind.CHOOSE_DEFENDER: TurnMessageView,
    PromptKind.PATROL: TurnMessageView,
    PromptKind.TECH_CHOICE: TurnMessageView,
    PromptKind.TECH_CONFIRM: TurnMessageView,
    PromptKind.GAME_OVER: TurnMessageView,
}


class CoreMixin:
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.tokens = CodexTokens(bot)
        self.games: dict[str, CodexGame] = load_games()
        self.engine = RulesEngine()
        #: The turn's lines so far, by game id, in the model's tokens --
        #: the turn message's text. In memory: after a restart the text
        #: on the message stands until `/codex resume` re-posts it.
        self.turn_lines: dict[str, list[str]] = {}
        # The turn message's write gate (docs/design/rate-limits.md),
        # with the Codex bot's message, view, text and name.
        self.boards = BoardRefresher(
            self,
            keep_view=lambda game: TurnMessageView(self, game.game_id),
            links=lambda game: True,
            message_of=lambda game: game.turn_message_id,
            text_for=self.turn_text_or_none,
            label="Codex",
        )
        self.restore_saved_views()

    # -- Startup ---------------------------------------------------------

    def restore_saved_views(self) -> None:
        """
        Re-arm every persistent view: each open lobby's `LobbyView` and
        each playing game's `TurnMessageView`. A playing game with no
        turn message, or one the bot owes a step, is logged at ERROR:
        somebody has to run `/codex resume`.
        """
        for game in self.games.values():
            if game.status is GameStatus.LOBBY and game.message_id is not None:
                self.bot.add_view(LobbyView(self, game.game_id), message_id=game.message_id)
                continue
            if game.status is not GameStatus.PLAYING:
                continue
            if game.turn_message_id is None:
                LOGGER.error(
                    "Codex game %s (#%s) is being played and has no turn message to "
                    "re-arm; it needs /codex resume.", game.game_id, game.game_number,
                )
                continue
            self.bot.add_view(TurnMessageView(self, game.game_id), message_id=game.turn_message_id)
            try:
                owed = owed_step(self.engine, game, self.service.load(game))
            except Exception:
                LOGGER.error("Could not load Codex game %s.", game.game_id, exc_info=True)
                continue
            if owed is not None:
                LOGGER.error(
                    "Codex game %s (#%s) waits on a step of the bot's own (%s); it "
                    "needs /codex resume.", game.game_id, game.game_number, owed.step.name,
                )

    async def cog_load(self) -> None:
        await self.tokens.refresh()

    async def cog_unload(self) -> None:
        self.boards.shutdown()

    async def cog_app_command_error(self, interaction: discord.Interaction,
                                    error: app_commands.AppCommandError) -> None:
        original = getattr(error, "original", error)
        name = interaction.command.qualified_name if interaction.command else "unknown command"
        LOGGER.error("Unhandled error in /%s: %r", name, original, exc_info=original)
        await send_ephemeral(
            interaction, f"Something went wrong running that command. {ERROR_RECOVERY_ADVICE}",
        )

    # -- Lookups -----------------------------------------------------------

    def game_for_channel(self, channel_id: Optional[int]) -> Optional[CodexGame]:
        """The game played in this channel, or the lobby posted in it."""
        playing = [
            game for game in self.games.values()
            if game.channel_id == channel_id and game.status is GameStatus.PLAYING
        ]
        return playing[0] if playing else None

    def seat_names(self, game: CodexGame) -> dict[int, str]:
        return {1: game.player_1_name or "Player 1", 2: game.player_2_name or "Player 2"}

    # -- Tokens ------------------------------------------------------------

    def render_text(self, text: str, game: Optional[CodexGame] = None) -> str:
        """A sentence of the model's, its tokens drawn once, here."""
        return self.tokens.render(text, game)

    # -- The service --------------------------------------------------------

    @property
    def locks(self) -> GameLocks:
        """One lock per game, held around a click's whole answer."""
        locks = self.__dict__.get("_locks")
        if locks is None:
            locks = GameLocks()
            self.__dict__["_locks"] = locks
        return locks

    @property
    def service(self) -> GameService:
        """**The one door for a change to a game**, over this cog's engine
        and games, rebuilt if either is replaced (a test's builder)."""
        service = self.__dict__.get("_service")
        if service is None or service.engine is not self.engine or service.games is not self.games:
            service = GameService(self.engine, self.games, DiscordBatching())
            self.__dict__["_service"] = service
        return service

    def view_for_prompt(self, game: CodexGame, prompt: Optional[PendingPrompt]) -> discord.ui.View:
        """The only place a `PromptKind` becomes a view."""
        if prompt is None:
            return TurnMessageView(self, game.game_id)
        return PROMPT_VIEWS[prompt.kind](self, game.game_id)

    async def render_prompt(self, game: CodexGame, prompt: Optional[PendingPrompt]):
        """A prompt's picture: in step 3 every kind rides on the board
        the turn message already carries, so none has its own."""
        return None

    # -- The presenter -------------------------------------------------------

    def turn_text(self, game: CodexGame) -> str:
        """The turn message's text: the turn's lines, rendered, within
        Discord's limit -- the oldest dropped first if they run over."""
        lines = [self.render_text(line, game) for line in self.turn_lines.get(game.game_id, [])]
        text = "\n".join(lines)
        while len(text) > MESSAGE_LIMIT and len(lines) > 1:
            lines.pop(0)
            text = "\n".join(["...", *lines])
        return text[:MESSAGE_LIMIT]

    def turn_text_or_none(self, game: CodexGame) -> Optional[str]:
        """The gate's text: `None` -- leave the message's text alone --
        where this process has not seen the turn's lines."""
        if game.game_id not in self.turn_lines:
            return None
        return self.turn_text(game)

    def note_lines(self, game: CodexGame, result: GameResult) -> None:
        if result.lines:
            self.turn_lines.setdefault(game.game_id, []).extend(result.lines)

    async def present(self, game: CodexGame, result: GameResult) -> None:
        """
        **The whole of the Discord side of a result**: what it said joins
        the turn's lines, and the board and the lines are written once
        through the gate. Hidden information never reaches here: a
        result's lines are public (docs/design/codex.md, "What the
        narration may say"), and its prompts are sent to their asked
        player by the entry point that asked.
        """
        self.note_lines(game, result)
        if result.lines or result.board_changed:
            await self.refresh_match_image(game)
