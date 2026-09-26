"""
The web frontend's door: an asyncio server over a `GameService` of
its own.

**It is its own process, over its own games** (`python3 -m webapp`;
decided 2026-09-25, docs/web-app-next.md). The web app and the bot
share the model of the game and nothing at runtime: not a process, not
a games file, not a service. `main` below builds an engine from the
same loaders the cog uses, loads `WEB_GAMES_FILE`, and hands the
service a save that writes that file and never the bot's.
`gamesaves/d12ball/storage.py` rewrites the whole file on every save
and reads it once at startup, so two processes over one file would
clobber each other; one process per file is what keeps them apart, and
`gamelocks.GameLocks` is what keeps two coaches' answers in order.

What a request does is the shape ARCHITECTURE.md draws: authenticate
the person (`webapp/keys.py`), turn what they pressed into an
`Action`, call `apply_action`, render the `GameResult`
(`webapp/present.py`). Read-only requests -- the board, the state --
do not go near the driver.

**A page may only send back a control it was offered.** The
server builds this viewer's controls off the prompt's options, and an
action that is not one of them is refused here, before the model sees
it -- which is the web equivalent of a button Discord never drew. It
is not a second reading of the rules: what may be *chosen* is the
prompt's, and what the position allows is still the driver's, which
refuses again on its own reading. It is how a hand-made request
cannot reach an adapter with an argument no prompt ever offered.

**What was said reaches a page that did not ask for it.** A game is
played from two pages: the journal below is fed by every result the
service produces, through `GameService.listeners`, so a coach watching
a web page sees the other coach's turn as it happens.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional

from aiohttp import web

from dotenv import load_dotenv

from d12ball import tutorial
from d12ball.ai import build_ai_strategies
from d12ball.components import (
    MatchState,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.engine import RulesEngine
from d12ball.formatting import coach_name, format_player_with_team_name
from d12ball.game import D12BallGame, GameStatus, Team, team_display_name
from d12ball.prompts import Action, PendingPrompt, pending
from d12ball.render import TEAM_COLORS, render_match_image
from gamelocks import GameLocks
from gamesaves.d12ball.service import GameResult, GameService
from gamesaves.d12ball.storage import WEB_GAMES_FILE, load_games, save_games
from webapp import keys, pictures
from webapp.board import board_layout, period_name
from webapp.present import Viewer, controls_for, render_text

LOGGER = logging.getLogger(__name__)

STATIC = Path(__file__).resolve().parent / "static"

#: How much of a game's narration a page can scroll back through. A
#: browser that has been open all game holds the rest; this is what a
#: page that has just been opened is given, and what a coach coming
#: back to one catches up on.
JOURNAL_LENGTH = 200

#: How many rendered boards are kept in hand. A board is ~200KB and a
#: page asks for one per entry it draws, so a few are worth keeping
#: and a game's worth is not.
BOARD_CACHE = 24

#: How much of a game's chat a page is handed on opening, and the
#: longest message it takes. Chat is people talking beside the game,
#: so it is bounded the way the journal is and kept nowhere else.
CHAT_LENGTH = 200
CHAT_MESSAGE_LIMIT = 500

#: How many card pictures are kept in hand: every face a game can show
#: is eighteen players and twelve maneuvers twice, and they never
#: change, so a few games' worth is cheap and saves a Pillow render a
#: card on every page that opens.
CARD_CACHE = 400

#: A card never changes while the process runs, so a browser may keep
#: it; a restart after an import re-renders it under the same URL,
#: which is why this is a day rather than a year.
CARD_MAX_AGE = 86400

#: The environment this reads: the port to listen on (8080 when unset)
#: and the address to bind (every interface when unset).
PORT_VARIABLE = "FOOLBOT_WEB_PORT"
HOST_VARIABLE = "FOOLBOT_WEB_HOST"
DEFAULT_PORT = 8080


@dataclass
class Entry:
    """One thing that was said, as the journal keeps it."""

    id: int
    lines: tuple[str, ...]
    #: The position the frontend stopped to draw, where it did.
    board: Optional[dict] = None
    new_play: bool = False
    #: When it was said, as a Discord message carries its time.
    at: float = field(default_factory=time.time)

    def to_dict(self, game: D12BallGame, layout=None) -> dict:
        """`layout` draws the snapshot, where there is one -- the
        server's, since it needs the engine."""
        return {
            "id": self.id,
            "lines": [render_text(game, line) for line in self.lines],
            "board": self.board is not None,
            "layout": (
                layout(self.board)
                if layout is not None and self.board is not None
                else None
            ),
            "new_play": self.new_play,
            "at": self.at,
        }


@dataclass
class Journal:
    """
    What has been said in one game since this process started.

    It is the web frontend's own memory and nothing to do with the
    save: `MatchState.events` is the game's record of what happened
    (and nothing may read it to decide a rule), where this is the run
    of messages a page shows, in the order a coach reads them. A
    restart empties it, and the board and the prompt are still right,
    which is the difference between a transcript and a position.
    """

    entries: deque = field(
        default_factory=lambda: deque(maxlen=JOURNAL_LENGTH),
    )
    next_id: int = 1
    #: Bumped whenever anything a board draws has moved, so a page's
    #: `<img>` asks for the new one rather than the browser's copy.
    board_version: int = 1

    def add(self, result: GameResult) -> None:
        """One result, as the page reads it: the answer's own lines,
        then every group the run closed."""
        for lines, group in self._blocks(result):
            if not lines and group is None:
                continue
            self.entries.append(
                Entry(
                    self.next_id,
                    tuple(lines),
                    board=None if group is None else group.board,
                    new_play=False if group is None else group.new_play,
                ),
            )
            self.next_id += 1
        if result.board_changed or any(
            group.board is not None for group in result.groups
        ):
            self.board_version += 1

    def _blocks(self, result: GameResult):
        """
        What one result is worth reading, in the order it was said:
        the answer's own lines, every group the run closed, and what
        it was still carrying when it stopped.

        **The last of those opens the prompt**, and the Discord cog
        posts it *with* the prompt as one message (`render_prompt`'s
        `lead_in`). A page has no reason to: the ask is a panel of its
        own under the board, so the lines go where every other line
        goes and the panel says what is being asked. Batching is the
        frontend's (principle 8), and this is the frontend.
        """
        if result.answer:
            yield list(result.answer), None
        for group in result.groups:
            yield list(group.lines), group
        if result.narration:
            yield list(result.narration), None

    def since(
        self, entry_id: int, game: D12BallGame, layout=None,
    ) -> list[dict]:
        return [
            entry.to_dict(game, layout)
            for entry in self.entries
            if entry.id > entry_id
        ]

    def board_for(self, entry_id: int) -> Optional[dict]:
        for entry in self.entries:
            if entry.id == entry_id:
                return entry.board
        return None


@dataclass
class ChatMessage:
    """One thing a person said at the table."""

    id: int
    who: str
    text: str
    #: The team colour of the coach who said it, or `None` for an
    #: observer -- the page's to draw their name in.
    colour: Optional[str] = None
    at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "who": self.who,
            "text": self.text,
            "colour": self.colour,
            "at": self.at,
        }


@dataclass
class Chat:
    """
    What the people at one game have said to each other since this
    process started -- step 4 of docs/web-app-next.md, in memory.

    **It is not the game's**: never on the record, never read by the
    model, and nothing in it is rendered as the model's markdown or
    tokens, because it is not the model's voice. A message is plain
    text and the page draws it as text. A restart empties it, as it
    empties the journal; the file step 4 keeps it in comes with the
    rooms (step 2), which is when a person has a name of their own
    rather than a seat's.
    """

    messages: deque = field(default_factory=lambda: deque(maxlen=CHAT_LENGTH))
    next_id: int = 1

    def add(self, who: str, text: str, colour: Optional[str]) -> ChatMessage:
        message = ChatMessage(self.next_id, who, text, colour)
        self.messages.append(message)
        self.next_id += 1
        return message

    def since(self, message_id: int) -> list[dict]:
        return [one.to_dict() for one in self.messages if one.id > message_id]


class WebApp:
    """
    The aiohttp application, and the state one process keeps for it.

    It owns nothing about the game: the engine, the games and the
    service are handed in -- by `main`, which builds them over the web
    app's own file. What is its own is what a frontend's is -- who is
    reading a page, what has been said, and the pictures it has drawn.
    """

    def __init__(
        self,
        service: GameService,
        locks: GameLocks,
        *,
        host: str = "0.0.0.0",
        port: int = 8080,
    ) -> None:
        self.service = service
        self.locks = locks
        self.host = host
        self.port = port
        self.journals: dict[str, Journal] = {}
        self.chats: dict[str, Chat] = {}
        self._boards: dict[tuple, bytes] = {}
        self._cards: dict[tuple, bytes] = {}
        self._runner: Optional[web.AppRunner] = None
        self.app = web.Application()
        self.app.add_routes(
            [
                web.get("/", self.index),
                web.get("/game/{game_id}", self.page),
                web.get("/api/game/{game_id}", self.state),
                web.post("/api/game/{game_id}/action", self.act),
                web.post("/api/game/{game_id}/resume", self.resume),
                web.post("/api/game/{game_id}/chat", self.say),
                web.get("/api/game/{game_id}/board.png", self.board),
                web.get(
                    "/api/game/{game_id}/card/{card_id}.png", self.player_card,
                ),
                web.get(
                    "/api/game/{game_id}/maneuver/{key}.png",
                    self.maneuver_card,
                ),
                web.get("/api/game/{game_id}/goal/{side}.png", self.goal),
                web.get("/emoji/{name}", self.emoji),
                web.get("/species/{name}", self.species),
                web.get("/fonts/{name}", self.font),
                web.static("/static", STATIC),
            ],
        )

    # -- The service's side ------------------------------------------

    @property
    def engine(self) -> RulesEngine:
        return self.service.engine

    def watch(self) -> None:
        """
        Listen to every result the service produces, from every page.
        Without this a web page would see its own turns and none of
        the other coach's.
        """
        self.service.listeners.append(self.record)

    def record(self, game: D12BallGame, result: GameResult) -> None:
        """One result, into that game's journal. It must not raise:
        this runs inside somebody's click."""
        try:
            self.journal(game.game_id).add(result)
        except Exception:  # pragma: no cover - a frontend's own bug
            LOGGER.exception(
                "The web journal could not record a result for game %s",
                game.game_id,
            )

    def journal(self, game_id: str) -> Journal:
        journal = self.journals.get(game_id)
        if journal is None:
            journal = Journal()
            self.journals[game_id] = journal
        return journal

    def chat(self, game_id: str) -> Chat:
        chat = self.chats.get(game_id)
        if chat is None:
            chat = Chat()
            self.chats[game_id] = chat
        return chat

    async def start(self) -> None:
        self._runner = web.AppRunner(self.app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.host, self.port)
        await site.start()
        LOGGER.info(
            "The D12 Ball web app is listening on %s:%s (links point at %s).",
            self.host,
            self.port,
            keys.base_url(),
        )

    async def stop(self) -> None:
        if self.service is not None and self.record in self.service.listeners:
            self.service.listeners.remove(self.record)
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None

    # -- Reading a request -------------------------------------------

    def _game(self, request: web.Request) -> D12BallGame:
        game = self.service.games.get(request.match_info["game_id"])
        if game is None:
            raise web.HTTPNotFound(text="No such game.")
        return game

    def _viewer(self, request: web.Request, game: D12BallGame) -> Viewer:
        return Viewer(
            keys.player_number_for(
                game.game_id, request.query.get("key"),
            ),
        )

    def _match(self, game: D12BallGame) -> Optional[MatchState]:
        if game.match_state is None:
            return None
        return self.service.load(game)

    # -- The pages ---------------------------------------------------

    async def index(self, request: web.Request) -> web.Response:
        return web.Response(
            text=(
                "D12 Ball. A game is opened with its own link."
            ),
        )

    async def page(self, request: web.Request) -> web.Response:
        """The page itself. Everything on it arrives from the API
        below, so this is the same file for every game."""
        self._game(request)
        return web.FileResponse(STATIC / "game.html")

    async def state(self, request: web.Request) -> web.Response:
        game = self._game(request)
        return web.json_response(
            self._state(
                game,
                self._viewer(request, game),
                since=_since(request),
                chat_since=_int(request.query.get("chat_since")) or 0,
            ),
        )

    async def act(self, request: web.Request) -> web.Response:
        """
        One control pressed: one `Action` through `apply_action`, the
        same door a Discord click goes through.

        The lock is held around the answer *and* the state built from
        it, so two coaches pressing at once are answered in the order
        they were applied rather than in the order their renders
        finished (`gamelocks.py`).
        """
        game = self._game(request)
        viewer = self._viewer(request, game)
        body = await _body(request)
        match = self._match(game)
        if match is None:
            raise web.HTTPConflict(text="This game has not kicked off yet.")

        prompt = self.service.waiting_on(game, match)
        offered = controls_for(self.engine, game, match, prompt, viewer)
        posted = body.get("action") or {}
        if not _was_offered(offered, posted):
            # Not this viewer's question, not one of its answers, or an
            # argument nothing offered -- refused before the model sees
            # it. See the module docstring.
            return web.json_response(
                {
                    **self._state(game, viewer, since=_since(request)),
                    "refusal": (
                        "That is not one of the controls this page is "
                        "offering. It may have been answered already -- "
                        "the position below is the current one."
                    ),
                },
                status=409,
            )

        try:
            action = Action.from_dict(posted)
        except (KeyError, ValueError):
            raise web.HTTPBadRequest(text="That is not an answer.")

        async with self.locks.hold(game.game_id):
            result = self.service.apply_action(game.game_id, action)
            state = self._state(game, viewer, since=_since(request))
        state["refusal"] = result.refusal
        return web.json_response(state)

    async def resume(self, request: web.Request) -> web.Response:
        """
        Run the step the bot owes here -- what `/d12ball resume` does,
        off the same reading (`GameService.resume`). A page offers it
        where a restart has left a cascade half-run and nobody is
        being asked anything.
        """
        game = self._game(request)
        viewer = self._viewer(request, game)
        if not viewer.is_coach:
            raise web.HTTPForbidden(text="Only a coach may pick a game up.")
        if game.match_state is None:
            raise web.HTTPConflict(text="This game has not kicked off yet.")

        async with self.locks.hold(game.game_id):
            found, _ = self.service.resume(game.game_id)
            state = self._state(game, viewer, since=_since(request))
        state["resumed"] = found
        return web.json_response(state)

    async def say(self, request: web.Request) -> web.Response:
        """
        One chat message. Anybody reading the page may talk -- a coach
        under their name off the record, anybody else as an observer
        -- and it goes nowhere near the service: talking is not an
        action on the game.
        """
        game = self._game(request)
        viewer = self._viewer(request, game)
        body = await _body(request)
        text = str(body.get("text") or "").strip()
        if not text:
            raise web.HTTPBadRequest(text="Say something.")
        text = text[:CHAT_MESSAGE_LIMIT]
        if viewer.is_coach:
            coach = self._coach(game, viewer.player_number)
            who, colour = coach["name"], coach["colour"]
        else:
            who, colour = "Observer", None
        self.chat(game.game_id).add(who, text, colour)
        return web.json_response(
            self._state(
                game,
                viewer,
                since=_since(request),
                chat_since=_int(request.query.get("chat_since")) or 0,
            ),
        )

    async def board(self, request: web.Request) -> web.Response:
        """
        The board as a PNG -- read-only, so it never goes near the
        driver (ARCHITECTURE.md, "State-changing and read-only
        operations"). `entry` draws the position the frontend stopped
        at rather than the one the game is in now.
        """
        game = self._game(request)
        match = self._match(game)
        if match is None:
            raise web.HTTPNotFound(text="This game has no board yet.")
        entry_id = _int(request.query.get("entry"))
        snapshot = (
            self.journal(game.game_id).board_for(entry_id)
            if entry_id is not None
            else None
        )
        if entry_id is not None and snapshot is None:
            raise web.HTTPNotFound(text="That board is no longer in hand.")
        key = (
            game.game_id,
            entry_id
            if entry_id is not None
            else ("now", self.journal(game.game_id).board_version),
        )
        png = self._boards.get(key)
        if png is None:
            png = await asyncio.to_thread(
                self._render_board,
                game,
                match if snapshot is None else MatchState.from_dict(
                    snapshot, self.engine.basic_ruleset,
                ),
            )
            self._boards[key] = png
            while len(self._boards) > BOARD_CACHE:
                self._boards.pop(next(iter(self._boards)))
        return web.Response(
            body=png,
            content_type="image/png",
            headers={"Cache-Control": "public, max-age=31536000"},
        )

    async def player_card(self, request: web.Request) -> web.Response:
        """
        One player's card, read-only. `face=board` is the face the
        bot's board draws (the default); `face=full` is the printed
        card with the whole ability on it -- its advanced face in an
        advanced game (`personal_abilities_apply`: the personal ability
        and the advanced skills are that face), which is the card a
        coach in that game is holding.
        """
        game = self._game(request)
        match = self._match(game)
        if match is None:
            raise web.HTTPNotFound(text="This game has no cards yet.")
        card_id = request.match_info["card_id"]
        try:
            team = match.team_for_player(card_id)
        except (KeyError, ValueError):
            raise web.HTTPNotFound(text="No such card in this game.")
        face = request.query.get("face", "board")
        if face not in ("board", "full"):
            raise web.HTTPBadRequest(text="A face is board or full.")
        catalog = self.engine.player_catalog
        if face == "board":
            # The marks the card is drawn with, as the page's layout
            # spelled them (`webapp/board.py`). A picture of a card and
            # nothing more: a mark asked for here changes no game.
            exhaustion = _int(request.query.get("x")) or 0
            flags = [
                request.query.get(name, "0") == "1" for name in ("e", "i", "c")
            ]
            if not 0 <= exhaustion <= 20:
                raise web.HTTPBadRequest(text="No card carries that many.")
            exhausted, injured, cyborg = flags
            # The skills an advanced game prints, answered off the
            # game rather than the request (`RulesEngine.card_skills`).
            skills = self.engine.card_skills(game, match)
            printed = skills.get(card_id)
            key = ("board", card_id, team, exhaustion, *flags, printed)
            draw = lambda: pictures.board_card_png(  # noqa: E731
                catalog,
                card_id,
                team,
                exhaustion=exhaustion,
                exhausted=exhausted,
                injured=injured,
                cyborg=cyborg,
                card_skills=skills,
            )
        else:
            advanced = self.engine.personal_abilities_apply(game)
            key = ("full", card_id, team, advanced)
            draw = lambda: pictures.player_card_png(  # noqa: E731
                catalog, card_id, team, advanced=advanced, size="full",
            )
        return await self._card(key, draw)

    async def goal(self, request: web.Request) -> web.Response:
        """One end zone, in the colour of the side defending it, turned
        the way the bot's board turns it."""
        game = self._game(request)
        match = self._match(game)
        if match is None:
            raise web.HTTPNotFound(text="This game has no board yet.")
        side = request.match_info["side"]
        if side not in ("home", "visiting"):
            raise web.HTTPNotFound()
        team = match.home.team if side == "home" else match.visiting.team
        angle = 90 if side == "home" else 270
        return await self._card(
            ("goal", team, angle), lambda: pictures.goal_png(team, angle),
        )

    async def maneuver_card(self, request: web.Request) -> web.Response:
        """One maneuver card, in the colour of the side holding it."""
        self._game(request)
        key = request.match_info["key"]
        side = request.query.get("side", "offense")
        if side not in ("offense", "defense"):
            raise web.HTTPBadRequest(text="A side is offense or defense.")
        if self.engine.maneuver_catalog.get(key) is None:
            raise web.HTTPNotFound(text="No such maneuver.")
        size = request.query.get("size", "small")
        if size not in pictures.CARD_WIDTHS:
            raise web.HTTPBadRequest(text="A size is small or full.")
        return await self._card(
            ("maneuver", key, side, size),
            lambda: pictures.maneuver_card_png(
                self.engine.maneuver_catalog,
                self.engine.player_catalog,
                key,
                offense=side == "offense",
                size=size,
            ),
        )

    async def _card(self, key: tuple, draw) -> web.Response:
        png = self._cards.get(key)
        if png is None:
            png = await asyncio.to_thread(draw)
            self._cards[key] = png
            while len(self._cards) > CARD_CACHE:
                self._cards.pop(next(iter(self._cards)))
        return web.Response(
            body=png,
            content_type="image/png",
            headers={"Cache-Control": f"public, max-age={CARD_MAX_AGE}"},
        )

    async def emoji(self, request: web.Request) -> web.Response:
        """The bot's emoji, as it uploads them."""
        path = pictures.emoji_path(request.match_info["name"])
        if path is None:
            raise web.HTTPNotFound()
        return web.FileResponse(
            path, headers={"Cache-Control": f"public, max-age={CARD_MAX_AGE}"},
        )

    async def species(self, request: web.Request) -> web.Response:
        """The four species icons, ink and coloured."""
        path = pictures.species_path(request.match_info["name"])
        if path is None:
            raise web.HTTPNotFound()
        return web.FileResponse(
            path, headers={"Cache-Control": f"public, max-age={CARD_MAX_AGE}"},
        )

    async def font(self, request: web.Request) -> web.Response:
        """The board's own typefaces."""
        path = pictures.font_path(request.match_info["name"])
        if path is None:
            raise web.HTTPNotFound()
        return web.FileResponse(
            path, headers={"Cache-Control": f"public, max-age={CARD_MAX_AGE}"},
        )

    def _layout(self, game: D12BallGame, match: MatchState) -> dict:
        """The board as the page draws it (`webapp/board.py`)."""
        return board_layout(
            self.engine,
            game,
            match,
            card_url=f"/api/game/{game.game_id}/card/{{card}}.png",
            goal_url=f"/api/game/{game.game_id}/goal/{{side}}.png",
        )

    def _snapshot_layout(self, game: D12BallGame):
        """How an entry's snapshot is drawn: the same layout, over the
        position the frontend stopped at."""

        def draw(snapshot: dict) -> Optional[dict]:
            try:
                match = MatchState.from_dict(
                    snapshot, self.engine.basic_ruleset,
                )
                return self._layout(game, match)
            except Exception:  # pragma: no cover - a frontend's own bug
                LOGGER.exception(
                    "The web app could not draw a snapshot for game %s",
                    game.game_id,
                )
                return None

        return draw

    def _title(self, game: D12BallGame, match: Optional[MatchState]) -> str:
        """The title the bot's board carries: the game's number, both
        coaches with their teams, and the half."""
        title = (
            f"PBD{game.game_number} - "
            f"{format_player_with_team_name(game, game.home_player_number)}"
            f" vs. "
            f"{format_player_with_team_name(game, game.visiting_player_number)}"
        )
        return title if match is None else f"{title}, {_period(match)}"

    def _render_board(self, game: D12BallGame, match: MatchState) -> bytes:
        """Pillow, in a worker thread: the same picture the bot pins,
        off the same renderer."""
        return render_match_image(
            match,
            self.engine.player_catalog,
            title=self._title(game, match),
            species_icons=self.engine.species_abilities_apply(game),
            cyborg_ids=self.engine.cyborg_condition_ids(game, match),
            card_skills=self.engine.card_skills(game, match),
        ).getvalue()

    # -- What a page is handed ---------------------------------------

    def _state(
        self,
        game: D12BallGame,
        viewer: Viewer,
        *,
        since: int = 0,
        chat_since: int = 0,
    ) -> dict:
        journal = self.journal(game.game_id)
        chat = self.chat(game.game_id)
        match = self._match(game)
        # The one reading of what the match waits on: a question for
        # somebody, or a step the bot owes (`d12ball.prompts.pending`).
        waiting = None if match is None else pending(self.engine, game, match)
        prompt = waiting if isinstance(waiting, PendingPrompt) else None
        owed = waiting is not None and prompt is None
        return {
            "game": {
                "id": game.game_id,
                "number": game.game_number,
                "name": game.game_name,
                "status": GameStatus(game.status).value,
                "tutorial": game.tutorial,
                # The board PNG's own title, which is how the bot
                # names a game everywhere it pins one.
                "title": self._title(game, match),
                "coaches": [
                    self._coach(game, number) for number in (1, 2)
                ],
            },
            "you": {
                "player_number": viewer.player_number,
                "is_coach": viewer.is_coach,
            },
            "scoreboard": (
                None if match is None else {
                    "home": match.scoreboard.home_score,
                    "visiting": match.scoreboard.visiting_score,
                    "minute": match.scoreboard.time,
                    "period": _period(match),
                }
            ),
            "board": {
                "url": (
                    None if match is None else
                    f"/api/game/{game.game_id}/board.png"
                    f"?v={journal.board_version}"
                ),
                "version": journal.board_version,
                "layout": (
                    None if match is None else self._layout(game, match)
                ),
            },
            "prompt": (
                None if prompt is None else {
                    "kind": prompt.kind.value,
                    "ask": render_text(game, prompt.ask),
                    "controls": controls_for(
                        self.engine, game, match, prompt, viewer,
                    ),
                    "yours": bool(
                        controls_for(
                            self.engine, game, match, prompt, viewer,
                        ),
                    ),
                }
            ),
            "owed": owed,
            "entries": journal.since(
                since, game, self._snapshot_layout(game),
            ),
            "latest": journal.next_id - 1,
            "chat": chat.since(chat_since),
            "chat_latest": chat.next_id - 1,
        }

    def _coach(self, game: D12BallGame, player_number: int) -> dict:
        team = (
            game.player_1_team if player_number == 1 else game.player_2_team
        )
        side = (
            "home" if game.home_player_number == player_number
            else "visiting" if game.visiting_player_number == player_number
            else None
        )
        return {
            "player_number": player_number,
            "name": coach_name(game, player_number),
            # Named with `team_display_name` and coloured with
            # `TEAM_COLORS`, which are the model's one naming and
            # `render.py`'s one hex -- a team is not `.value.title()`
            # anywhere (see docs/design/teams-and-players.md).
            "team": None if team is None else team_display_name(team),
            # What the team's emoji is filed under (`/emoji/team_<key>.png`).
            "team_key": None if team is None else Team(team).value,
            "colour": None if team is None else TEAM_COLORS[team],
            "side": side,
        }


def _period(match: MatchState) -> str:
    """The half a coach reads, worded as the board's own title words
    it."""
    return period_name(match)


def _was_offered(sections: list, posted: Mapping[str, Any]) -> bool:
    """
    Whether `posted` is one of the controls this viewer was handed.

    A button matches its own action exactly. A chooser matches its
    fixed arguments, plus exactly its fields, each one a value that
    field offered -- which is the whole of what a page may add to what
    it was given.
    """
    kind = posted.get("kind")
    choice = posted.get("choice") or ""
    arguments = dict(posted.get("arguments") or {})
    for section in sections:
        for control in section["controls"]:
            offer = control["action"]
            if offer["kind"] != kind or offer["choice"] != choice:
                continue
            if control["type"] == "button":
                if control["disabled"]:
                    continue
                if arguments == dict(offer["arguments"]):
                    return True
                continue
            fields = {
                one["name"]: {option["value"] for option in one["choices"]}
                for one in control["fields"]
            }
            fixed = {
                name: value
                for name, value in arguments.items()
                if name not in fields
            }
            if fixed != dict(offer["arguments"]):
                continue
            if set(arguments) - set(fixed) != set(fields):
                continue
            if all(
                str(arguments[name]) in values
                for name, values in fields.items()
            ):
                return True
    return False


def _since(request: web.Request) -> int:
    return _int(request.query.get("since")) or 0


def _int(value: Optional[str]) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


async def _body(request: web.Request) -> Mapping[str, Any]:
    try:
        body = await request.json()
    except Exception:
        raise web.HTTPBadRequest(text="Expected JSON.")
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text="Expected an object.")
    return body


def configured_port() -> int:
    """The port the environment asks for, or `DEFAULT_PORT`."""
    port = _int(os.environ.get(PORT_VARIABLE, "").strip() or None)
    return DEFAULT_PORT if port is None else port


async def start_web_app(
    service: GameService,
    locks: GameLocks,
    *,
    port: Optional[int] = None,
    host: Optional[str] = None,
) -> WebApp:
    """Start the server over `service` on this process's event loop."""
    app = WebApp(
        service,
        locks,
        host=host or os.environ.get(HOST_VARIABLE, "0.0.0.0"),
        port=port if port is not None else configured_port(),
    )
    app.watch()
    await app.start()
    return app


def build_service(games_file: Path) -> GameService:
    """
    The web app's own service: an engine from the same four loaders
    the cog builds its own from, the games saved in `games_file`, the
    default `Batching()` (Discord's economy is not the web's), and a
    save that writes `games_file` and nothing else.

    **The file is always named.** `storage`'s default is the bot's
    file, so a call here that forgot the path would write over the
    bot's games; `games_file` has no default for that reason.
    """
    player_catalog = load_player_catalog()
    maneuver_catalog = load_maneuver_catalog()
    # The cog's own check at startup, for the same reason: a tutorial
    # beat railed onto a card the sheet has renamed is three disabled
    # buttons rather than an error. See d12ball/tutorial.py.
    tutorial.validate_script(maneuver_catalog)
    engine = RulesEngine(
        player_catalog,
        load_basic_ruleset(),
        maneuver_catalog,
        build_ai_strategies(player_catalog, maneuver_catalog),
    )
    games = load_games(games_file)
    return GameService(
        engine,
        games,
        save=lambda games: save_games(games, games_file),
    )


def configure_logging() -> None:
    """
    Console logging for the web process, at `FOOLBOT_LOG_LEVEL` like
    the bot's (default INFO). Not `botlog`'s: it imports discord, and
    the #logs mirror is the bot's.
    """
    raw = os.environ.get("FOOLBOT_LOG_LEVEL", "").strip().upper()
    level = logging.getLevelName(raw) if raw else logging.INFO
    logging.basicConfig(
        level=level if isinstance(level, int) else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
    )


async def serve(games_file: Path = WEB_GAMES_FILE) -> None:
    """Run the web app over `games_file` until cancelled."""
    service = build_service(games_file)
    LOGGER.info(
        "Loaded %d web game(s) from %s.", len(service.games), games_file,
    )
    app = await start_web_app(service, GameLocks())
    try:
        await asyncio.Event().wait()
    finally:
        await app.stop()


def main() -> None:
    """`python3 -m webapp`: no Discord token, no bot, its own file."""
    load_dotenv()
    configure_logging()
    try:
        asyncio.run(serve())
    except KeyboardInterrupt:
        LOGGER.info("The D12 Ball web app has stopped.")
