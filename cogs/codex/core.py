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
import logging
import time
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
from codex.prompts import PendingPrompt, PromptKind, owed_step, pending_prompts
from codex.render import preload_pictures, render_codex, render_hand
from cogs.codex_helpers import CodexTokens, seat_label
from cogs.codex_publish.config import store_from_env
from cogs.codex_publish.publisher import Publisher
from cogs.codex_views import (
    ERROR_RECOVERY_ADVICE,
    LobbyView,
    PatrolView,
    RematchView,
    TechChoiceView,
    TechConfirmView,
    TechGateView,
    TechSavedView,
    TurnMessageView,
    TurnPanelView,
    picture_file,
    send_ephemeral,
)
from cogs.d12ball_boards import BoardRefresher
from gamelocks import GameLocks
from gamesaves.codex.service import Batching, GameResult, GameService
from gamesaves.codex.storage import load_games

LOGGER = logging.getLogger(__name__)

#: Discord's limit on a message's text.
MESSAGE_LIMIT = 2000

#: The heading over the turn's lines on an ephemeral message.
TURN_LOG_HEADING = "**This turn**"


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
    PromptKind.LEVEL_GAIN: TurnPanelView,
    PromptKind.DIVIDE_DAMAGE: TurnPanelView,
    PromptKind.MODE_CHOICE: TurnPanelView,
    PromptKind.STASH: TurnPanelView,
    PromptKind.CHOOSE_NUMBER: TurnPanelView,
    PromptKind.OATH: TurnPanelView,
    PromptKind.PATROL: PatrolView,
    PromptKind.TECH_CHOICE: TechChoiceView,
    PromptKind.TECH_CONFIRM: TechConfirmView,
    PromptKind.GAME_OVER: None,
}

#: The prompts a turn may open on before its actions, its player's
#: tech, which **Tech** on the turn message opens. **My hand** opens the
#: confirmation at once, the hand pictured above the picks, and puts the
#: picker -- a choice never made -- behind `TechGateView`, the hand with
#: **Tech** alone under it (`show_panel`; the author, 2026-10-10).
TECH_GATE_KINDS = (PromptKind.TECH_CONFIRM, PromptKind.TECH_CHOICE)

#: What the turn message says while the new turn waits on its player's
#: tech -- the cog's caption, not the model's line -- worded for the
#: prompt Tech opens: the confirmation of picks made during the
#: opponent's turn, or the picker itself where none were made (always,
#: in a test game: `codex.prompts.tech_stands`). It does not name the
#: **Tech** button: the button is under the message, and naming it again
#: said "tech" twice (the author, 2026-10-19).
TECH_WAIT = {
    PromptKind.TECH_CONFIRM: "*The turn waits on {who} to confirm their tech.*",
    PromptKind.TECH_CHOICE: "*The turn waits on {who} to choose their tech.*",
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
        #: Each recent turn's first lines -- what its message said when
        #: its main phase opened -- by game id and turn: what an undo
        #: puts back. In memory, the last three turns, as the snapshots.
        self.turn_heads: dict[str, dict[int, list[str]]] = {}
        #: The board last drawn, by game id: what it was drawn from
        #: (`board_key`) and its bytes, so a position unchanged is not
        #: drawn again (`render_match_png`).
        self.boards_drawn: dict[str, tuple[str, bytes]] = {}
        #: Where the cards are on each board drawn lately, by its bytes'
        #: SHA-256 (`board_map`), oldest first, for the site's hover.
        self.board_maps: dict[str, dict] = {}
        #: The board pinned at the current turn's start, by game id: its
        #: turn, its bytes and its map, which the turn's history entry on
        #: the site carries when the turn ends (`turn_start_png`). In
        #: memory: after a restart it is drawn again off the model.
        self.turn_start_boards: dict[str, tuple[int, bytes, Optional[dict]]] = {}
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
        #: The pictures read into memory as the bot starts (`cog_load`),
        #: off the event loop; cancelled by `cog_unload`.
        self.preloading: Optional[asyncio.Task] = None
        #: The Codex games on the web (docs/design/pbd-site.md): built in
        #: `cog_load` where `CODEX_PUBLISH_*` is set, `None` elsewhere.
        self.publisher: Optional[Publisher] = None
        self.restore_saved_views()

    # -- Startup ---------------------------------------------------------

    def restore_saved_views(self) -> None:
        """
        Re-arm every persistent view: each open lobby's `LobbyView`,
        each playing game's `TurnMessageView` -- the current turn
        message's buttons and no older turn's, which stand as summaries
        -- and a finished game's **Rematch** while no rematch has been
        opened from it. An abandoned game's messages, and a finished
        one's turn messages, are left as they stand. A playing game with
        no turn message, or one the bot owes a step, is logged at ERROR:
        somebody has to run `/codex resume`.
        """
        for game in self.games.values():
            if game.status is GameStatus.LOBBY and game.message_id is not None:
                self.bot.add_view(LobbyView(self, game.game_id), message_id=game.message_id)
                continue
            if game.status is GameStatus.FINISHED:
                if game.final_message_id is not None and game.rematch_game_id is None:
                    self.bot.add_view(RematchView(self, game.game_id), message_id=game.final_message_id)
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
        self.preloading = asyncio.create_task(self.preload_pictures())
        store = store_from_env()
        if store is not None:
            self.publisher = Publisher(self, store)
            # A task, since the views are re-armed already (`__init__`)
            # and a click may come before it is done.
            self.publisher.start()

    async def preload_pictures(self) -> None:
        """
        Every file a picture is drawn from, read into memory once, off
        the event loop (`codex.render.preload_pictures`), so that no
        click reads the host's disk -- a mounted Google Drive letter on
        the live host, met by the first hand and codex of every game
        after a restart until then (docs/design/codex.md, "The board on
        Discord"). The line it logs says what the host's disk took. A
        file it cannot read is a warning, and the renderer reads from
        the disk on first use as before.
        """
        started = time.perf_counter()
        try:
            files, size = await asyncio.to_thread(preload_pictures)
        except OSError as error:
            LOGGER.warning("Could not read the Codex pictures into memory: %s", error)
            return
        LOGGER.info("Codex pictures read into memory: %d files, %d MB, in %.1f s",
                    files, round(size / 2 ** 20), time.perf_counter() - started)

    async def cog_unload(self) -> None:
        self.boards.shutdown()
        if self.preloading is not None:
            self.preloading.cancel()
        if self.publisher is not None:
            await self.publisher.close()

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
        return {
            seat: seat_label(game, seat)
            for seat in range(1, game.seat_count + 1)
        }

    # -- Tokens ------------------------------------------------------------

    def render_text(self, text: str, game: Optional[CodexGame] = None) -> str:
        """A sentence of the model's, its tokens drawn once, here."""
        return self.tokens.render(text, game)

    def plain_text(self, text: str, game: Optional[CodexGame] = None) -> str:
        """A sentence of the model's as a label -- a menu's option --
        its tokens as words and its markup gone."""
        return self.tokens.plain(text, game).replace("**", "")

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
                        match, gate: bool = False) -> Optional[discord.ui.View]:
        """**The only place a `PromptKind` becomes a view**: the panel the
        prompt is answered from, shown to its asked player alone, or
        `None` for a kind nobody answers (a finished game). With `gate`,
        a turn's tech choice never made is **Tech** alone
        (`TechGateView`), the hand's panel until it is opened; a tech
        choice saved is its picks and **Change** (`TechSavedView`)."""
        if prompt is None:
            return None
        if gate and prompt.kind is PromptKind.TECH_CHOICE:
            return TechGateView(self, game.game_id, prompt, match)
        if prompt.kind is PromptKind.TECH_CHOICE and prompt.options.saved:
            return TechSavedView(self, game.game_id, prompt, match)
        view = PROMPT_VIEWS[prompt.kind]
        return None if view is None else view(self, game.game_id, prompt, match)

    async def render_prompt(self, game: CodexGame, prompt: Optional[PendingPrompt],
                            *, picks=None, view: Optional[str] = None) -> Optional[discord.File]:
        """
        A prompt's own picture, off the event loop: the tech picker's
        codex with the picks marked (`picks`, the picker's selection so
        far, defaulting to the prompt's) and narrowed to `view` -- the
        prompt's opening view by default (`TechOptions.opening`), or the
        one its Show menu or **Whole codex** chose (the engine's
        `codex_view_rows`) -- and the
        confirmation's picks as a hand, as a saved choice's are where no
        `picks` ask for the picker (`TechSavedView`). The main phase, the defender and
        the patrol lock have none -- the board on the turn message is
        theirs, and the panel pictures the hand (`hand_files`).
        Everything here is its asked player's alone.
        """
        if prompt is None or prompt.options is None:
            return None
        cards = self.engine.catalog
        if prompt.kind is PromptKind.TECH_CHOICE and (picks is not None or not prompt.options.saved):
            options = prompt.options
            chosen = Counter(options.picks if picks is None else picks)
            view = options.opening if view is None else view
            shown = self.engine.codex_view_rows(options.codex, view)
            webp = await asyncio.to_thread(
                render_codex, [slug for slug, _ in shown], [left for _, left in shown], cards,
                [chosen.get(slug, 0) for slug, _ in shown],
                self.engine.codex_places(shown, view),
            )
            return picture_file(webp, "codex-tech")
        if prompt.kind in (PromptKind.TECH_CHOICE, PromptKind.TECH_CONFIRM) and prompt.options.picks:
            picks = list(prompt.options.picks)
            webp = await asyncio.to_thread(
                render_hand, picks, [True] * len(picks),
                [cards.cards[slug].cost or 0 for slug in picks], cards,
            )
            return picture_file(webp, "codex-tech")
        return None

    # -- The turn message's text ----------------------------------------------

    def turn_header(self, game: CodexGame, match) -> str:
        """The turn's heading -- the model's (`codex.formatting.turn_heading`),
        "**Turn 7** -- @perrytom (Bashing)" -- rendered at the door: the
        mention the turn message's post pings once."""
        return self.render_text(turn_heading(match), game)

    def turn_footer(self, game: CodexGame, match) -> Optional[str]:
        """The caption under the lines while the turn waits on its
        player's tech: the cog's words over the model's prompt. The
        player the heading already mentions is "them", not a second
        mention (the author, 2026-10-14: "no need to ping the user
        twice")."""
        # In a two-headed dragon both teammates may owe their tech at
        # once (`pending_prompts`); the turn's caption names the first.
        prompt = next((one for one in pending_prompts(self.engine, game, match)
                       if one.kind in TECH_WAIT), None)
        if prompt is None:
            return None
        if prompt.asked_player in self.engine.turn_seats(match):
            return TECH_WAIT[prompt.kind].format(who="them")
        player_id = game.seat_user_id(prompt.asked_player)
        who = f"<@{player_id}>" if player_id else (game.seat_name(prompt.asked_player) or "its player")
        return TECH_WAIT[prompt.kind].format(who=who)

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

    def with_turn_log(self, game: CodexGame, text: str) -> str:
        """
        `text` -- an ephemeral message's, the panel's or the hand's --
        under the turn's lines so far, quoted, so the player reads what
        has happened beside their hand without scrolling up to the turn
        message (the author, 2026-10-12). The earliest lines fold into
        "and n more" as the turn message's do, to keep the whole within
        Discord's 2000 characters. `text` alone where this process has
        not seen the turn's lines, or the turn has said nothing yet.
        """
        lines = self.turn_lines.get(game.game_id)
        if not lines:
            return text
        room = MESSAGE_LIMIT - len(text) - 2
        body = ["> " + self.render_text(line, game).replace("\n", "\n> ") for line in lines]
        log = "\n".join([TURN_LOG_HEADING, *body])
        folded = 0
        while len(log) > room and body:
            body.pop(0)
            folded += 1
            log = "\n".join([TURN_LOG_HEADING, f"> *and {folded} more*", *body])
        if len(log) > room:
            return text
        return f"{log}\n\n{text}"

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
        """Keep this turn's lines so far as its first lines: what it
        said before its snapshot was taken, which the journal does not
        hold and an undo puts back above what it says -- called when the
        turn's message first goes up, and where the bot's own step
        opened the main phase of a turn that owed no tech."""
        heads = self.turn_heads.setdefault(game.game_id, {})
        heads[match.turn] = list(self.turn_lines.get(game.game_id, []))
        for turn in sorted(heads)[:-3]:
            del heads[turn]
        if self.publisher is not None:
            self.publisher.head_noted(game, match)
