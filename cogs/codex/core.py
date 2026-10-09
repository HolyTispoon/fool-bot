"""
The Codex cog's own machinery: its games and engine, the service and
the locks, re-arming the persistent views on startup, the tokens drawn
at the door, the turn message's text, `render_prompt` and
`view_for_prompt` (copied from `cogs/d12ball/core.py`'s shape;
docs/codex-bot.md, decision 2).

**The turn message is the one public message per turn** (decision 5):
`present` (in `cogs/codex/turns.py`) adds what a result said to the
turn's lines and writes the board and the lines through the gate
(`cogs.d12ball_boards.BoardRefresher`). A cascade of the bot's own steps
is one result, so one write. Nothing here decides a rule.
"""

from __future__ import annotations

import asyncio
import io
import logging
from collections import Counter
from dataclasses import dataclass
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from codex.engine import RulesEngine
from codex.flow.driver import MODEL_STEPS  # noqa: F401 -- the package-shape ratchet reads it
from codex.flow.result import FollowOnStep
from codex.formatting import turn_heading
from codex.game import CodexGame, GameStatus
from codex.prompts import PendingPrompt, PromptKind, owed_step, pending_prompt
from codex.render import render_codex, render_hand
from cogs.codex_helpers import CodexTokens
from cogs.codex_views import (
    ERROR_RECOVERY_ADVICE,
    LobbyView,
    PatrolView,
    TechChoiceView,
    TechConfirmView,
    TurnMessageView,
    TurnPanelView,
    send_ephemeral,
)
from cogs.d12ball_boards import BoardRefresher
from gamelocks import GameLocks
from gamesaves.codex.service import Batching, GameResult, GameService
from gamesaves.codex.storage import load_games

LOGGER = logging.getLogger(__name__)

#: Discord's limit on a message's text.
MESSAGE_LIMIT = 2000


@dataclass(frozen=True)
class DiscordBatching(Batching):
    """
    The Codex frontend's batching. A turn is one message, edited, so
    every line a run says joins the turn's lines and nothing is a
    message of its own; the bot's own steps run through without a stop.
    **The one joint is the end of the turn** (`draw_after`): the group
    closing there carries the position as it stood, so the turn's
    message stands with its own last board and lines, and what the next
    turn's start said goes on the next turn's message.
    """

    draw_after: frozenset = frozenset({FollowOnStep.BEGIN_TECH})


#: The view each prompt kind is answered from on Discord: the active
#: player's panel, or the tech choice's owner's. A finished game has
#: none -- its line and its final board are public.
PROMPT_VIEWS = {
    PromptKind.MAIN_ACTION: TurnPanelView,
    PromptKind.CHOOSE_DEFENDER: TurnPanelView,
    PromptKind.OBLITERATE_CHOICE: TurnPanelView,
    PromptKind.SPARKSHOT_TARGET: TurnPanelView,
    PromptKind.OVERPOWER_TARGET: TurnPanelView,
    PromptKind.TARGET: TurnPanelView,
    PromptKind.APPEL_STOMP_TOP: TurnPanelView,
    PromptKind.UPKEEP_ORDER: TurnPanelView,
    PromptKind.PATROL: PatrolView,
    PromptKind.TECH_CHOICE: TechChoiceView,
    PromptKind.TECH_CONFIRM: TechConfirmView,
    PromptKind.GAME_OVER: None,
}

#: What the turn message says while the new turn waits on its player's
#: tech confirmation -- the cog's caption, not the model's line.
TECH_WAIT = "*The turn waits on {who} to confirm their tech: **My hand**.*"


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
        #: Each recent turn's first lines -- what its message said when
        #: its main phase opened -- by game id and turn: what an undo
        #: puts back. In memory, the last three turns, as the snapshots.
        self.turn_heads: dict[str, dict[int, list[str]]] = {}
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

    def view_for_prompt(self, game: CodexGame, prompt: Optional[PendingPrompt],
                        match) -> Optional[discord.ui.View]:
        """**The only place a `PromptKind` becomes a view**: the panel the
        prompt is answered from, shown to its asked player alone, or
        `None` for a kind nobody answers (a finished game)."""
        if prompt is None:
            return None
        view = PROMPT_VIEWS[prompt.kind]
        return None if view is None else view(self, game.game_id, prompt, match)

    async def render_prompt(self, game: CodexGame, prompt: Optional[PendingPrompt],
                            *, picks=None) -> Optional[discord.File]:
        """
        A prompt's own picture, off the event loop: the tech picker's
        codex with the picks marked (`picks`, the picker's selection so
        far, defaulting to the prompt's), and the confirmation's picks as
        a hand. The main phase, the defender and the patrol lock have
        none -- the board on the turn message is theirs, and the panel
        pictures the hand (`hand_file`). Everything here is its asked
        player's alone.
        """
        if prompt is None or prompt.options is None:
            return None
        cards = self.engine.catalog
        if prompt.kind is PromptKind.TECH_CHOICE:
            options = prompt.options
            chosen = Counter(options.picks if picks is None else picks)
            webp = await asyncio.to_thread(
                render_codex, [slug for slug, _ in options.codex],
                [left for _, left in options.codex], cards,
                [chosen.get(slug, 0) for slug, _ in options.codex],
            )
            return discord.File(io.BytesIO(webp), filename="codex-tech.webp")
        if prompt.kind is PromptKind.TECH_CONFIRM and prompt.options.picks:
            picks = list(prompt.options.picks)
            webp = await asyncio.to_thread(
                render_hand, picks, [True] * len(picks),
                [cards.cards[slug].cost or 0 for slug in picks], cards,
            )
            return discord.File(io.BytesIO(webp), filename="codex-tech.webp")
        return None

    # -- The turn message's text ----------------------------------------------

    def turn_header(self, game: CodexGame, match) -> str:
        """The turn's heading -- the model's (`codex.formatting.turn_heading`),
        "**Turn 7** -- @perrytom (Bashing)" -- rendered at the door: the
        mention the turn message's post pings once."""
        return self.render_text(turn_heading(match), game)

    def turn_footer(self, game: CodexGame, match) -> Optional[str]:
        """The caption under the lines while the turn waits on its
        player's tech: the cog's words over the model's prompt."""
        prompt = pending_prompt(self.engine, game, match)
        if prompt is None or prompt.kind not in (PromptKind.TECH_CONFIRM, PromptKind.TECH_CHOICE):
            return None
        player_id = game.player_1_id if prompt.asked_player == 1 else game.player_2_id
        who = f"<@{player_id}>" if player_id else (game.seat_name(prompt.asked_player) or "its player")
        return TECH_WAIT.format(who=who)

    def turn_text(self, game: CodexGame, match=None, lines=None, footer: bool = True) -> str:
        """
        The turn message's text: the header, the turn's lines rendered,
        and the caption a waiting turn carries -- within Discord's 2000
        characters, **the earliest lines folding into "and n more"**
        past that, since the board carries the position. `footer=False`
        for a turn that has ended, which waits on nobody.
        """
        if match is None:
            match = self.service.load(game)
        if lines is None:
            lines = self.turn_lines.get(game.game_id, [])
        head = [self.turn_header(game, match)]
        caption = self.turn_footer(game, match) if footer else None
        tail = [caption] if caption else []
        body = [self.render_text(line, game) for line in lines]
        text = "\n".join([*head, *body, *tail])
        folded = 0
        while len(text) > MESSAGE_LIMIT and body:
            body.pop(0)
            folded += 1
            text = "\n".join([*head, f"*and {folded} more*", *body, *tail])
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

    def note_turn_head(self, game: CodexGame, match) -> None:
        """Keep this turn's lines so far as its first lines -- called
        when its main phase has just opened."""
        heads = self.turn_heads.setdefault(game.game_id, {})
        heads[match.turn] = list(self.turn_lines.get(game.game_id, []))
        for turn in sorted(heads)[:-3]:
            del heads[turn]
