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
the person (`webapp/identity.py`, and which seat of the room they
hold), turn what they pressed into an
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
from d12ball.formatting import (
    AI_OPPONENT_NAMES,
    coach_name,
    format_player_with_team_name,
)
from d12ball.game import (
    COLOR_TEAMS,
    SPECIES_TEAMS,
    VALID_BOARD_SIZES,
    AIOpponent,
    D12BallGame,
    GameMode,
    GameStatus,
    HomeChoice,
    RuleRefusal,
    Team,
    team_display_name,
)
from d12ball.prompts import Action, PendingPrompt, pending
from d12ball.render import TEAM_COLORS, render_match_image
from gamelocks import GameLocks
from gamesaves.d12ball.service import GameResult, GameService
from gamesaves.d12ball.storage import WEB_GAMES_FILE, load_games, save_games
from webapp import identity, keys, pictures
from webapp.identity import Coach
from webapp.board import board_layout, period_name
from webapp.present import Viewer, controls_for, render_text
from webapp.rooms import WEB_ROOMS_FILE, Rooms

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
        rooms: Optional[Rooms] = None,
        host: str = "0.0.0.0",
        port: int = 8080,
    ) -> None:
        self.service = service
        self.locks = locks
        #: Who is admin in each room and who has been in -- the web
        #: app's own file (`webapp/rooms.py`); in memory when none is
        #: handed in, which is what a test wants.
        self.rooms = rooms if rooms is not None else Rooms()
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
                web.get("/api/me", self.who_am_i),
                web.post("/api/me", self.call_me),
                web.get("/api/rooms", self.list_rooms),
                web.post("/api/rooms", self.open_room),
                web.get("/room/{game_id}", self.page),
                web.delete("/api/room/{game_id}", self.close_room),
                web.post(
                    "/api/room/{game_id}/seat/{move}", self.seat,
                ),
                web.post(
                    "/api/room/{game_id}/table/{move}", self.table,
                ),
                web.post("/api/room/{game_id}/rematch", self.rematch),
                web.post("/api/room/{game_id}/admin", self.take_admin),
                web.delete("/api/room/{game_id}/admin", self.drop_admin),
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
        """Which seat of this room the reader holds, if either."""
        coach = identity.coach_for(request)
        return Viewer(None if coach is None else seat_of(game, coach.id))

    def _required_coach(self, request: web.Request) -> Coach:
        coach = identity.coach_for(request)
        if coach is None:
            raise web.HTTPUnauthorized(text="Say who you are first.")
        return coach

    def _arrive(self, game: D12BallGame, coach: Optional[Coach]) -> None:
        """
        The first time somebody opens a room, a free seat is theirs --
        so the creator is Coach 1, the second person in Coach 2, and
        everybody after an observer. Through `GameService.take_seat`,
        so the record still judges it: a one-player game's second seat,
        or the AI's, refuses, and the person watches. Only the first
        time: somebody who has left their seat stays out of it until
        they take one.
        """
        if coach is None or not self.rooms.first_sight(game.game_id, coach.id):
            return
        if seat_of(game, coach.id) is not None:
            return
        try:
            self.service.take_seat(game.game_id, coach.id, coach.name)
        except RuleRefusal:
            pass

    def _match(self, game: D12BallGame) -> Optional[MatchState]:
        if game.match_state is None:
            return None
        return self.service.load(game)

    # -- The pages ---------------------------------------------------

    async def index(self, request: web.Request) -> web.Response:
        """Where a room is opened from."""
        return web.FileResponse(STATIC / "index.html")

    # -- Who is reading ----------------------------------------------

    async def who_am_i(self, request: web.Request) -> web.Response:
        """The person this browser's cookie names, or null."""
        coach = identity.coach_for(request)
        return web.json_response(None if coach is None else coach.to_dict())

    async def call_me(self, request: web.Request) -> web.Response:
        """
        Take a name: a new id the first time, the same id with the new
        name after that (`webapp/identity.py`).
        """
        body = await _body(request)
        try:
            name = identity.clean_name(body.get("name"))
        except identity.NameRefused as refusal:
            raise web.HTTPBadRequest(text=str(refusal))
        known = identity.coach_for(request)
        coach = (
            identity.issue(name)
            if known is None
            else identity.Coach(known.id, name)
        )
        response = web.json_response(coach.to_dict())
        identity.set_cookie(response, request, coach)
        return response

    async def page(self, request: web.Request) -> web.Response:
        """A room's page. Everything on it arrives from the API below,
        so this is the same file for every room; its link is good for
        as long as the game record is."""
        self._game(request)
        return web.FileResponse(STATIC / "game.html")

    async def state(self, request: web.Request) -> web.Response:
        game = self._game(request)
        coach = identity.coach_for(request)
        async with self.locks.hold(game.game_id):
            self._arrive(game, coach)
            state = self._state(
                game,
                self._viewer(request, game),
                since=_since(request),
                chat_since=_int(request.query.get("chat_since")) or 0,
                coach=coach,
            )
        return web.json_response(state)

    # -- Rooms and seats ---------------------------------------------

    async def list_rooms(self, request: web.Request) -> web.Response:
        """
        The front door's two lists: this reader's rooms, by where each
        stands, and the rooms with a seat free that they are not in.
        Every room here is a game in the web app's own file -- the
        bot's games are never in this service.
        """
        coach = identity.coach_for(request)
        mine: dict[str, list] = {
            "lobby": [], "setup": [], "in_progress": [], "finished": [],
        }
        free: list = []
        for game in sorted(
            self.service.games.values(),
            key=lambda one: one.game_number,
            reverse=True,
        ):
            held = coach is not None and seat_of(game, coach.id) is not None
            if held:
                mine[room_status(game)].append(self._listing(game))
            elif not game.is_finished and any(
                game.seat_is_free(number) for number in (1, 2)
            ):
                free.append(self._listing(game))
        return web.json_response({"mine": mine, "open": free})

    def _listing(self, game: D12BallGame) -> dict:
        """One room as the front door lists it."""
        return {
            "id": game.game_id,
            "number": game.game_number,
            "name": game.game_name,
            "status": room_status(game),
            "seats": [
                {
                    key: value
                    for key, value in self._seat(game, number, None).items()
                    if key != "yours"
                }
                for number in (1, 2)
            ],
            "observers": self._observers(game),
            "tutorial": game.tutorial,
            "url": f"/room/{game.game_id}",
        }

    async def open_room(self, request: web.Request) -> web.Response:
        """
        A new room, the creator in seat 1 (`GameService.create_game`,
        as the Discord hub opens one). The page goes to the link this
        answers.

        `{"ai": true}` is "Play against the AI": no lobby and nobody
        in the other seat, which the service fills with its default AI
        -- the AI is the service's to name, not this frontend's.
        `{"tutorial": true}` is the scripted opening, turned on the
        record's way (`configure`), so the record's pins -- Training,
        the 7-space board, one player -- are what it gets; against the
        AI it then leaves the lobby at once (`start_lobby`), which is
        what seats the AI in a tutorial.
        """
        coach = self._required_coach(request)
        body = await _body(request) if request.can_read_body else {}
        against_ai = body.get("ai") is True
        tutorial = body.get("tutorial") is True
        if against_ai and not tutorial:
            # `ai_seats=[2]`: the room says outright which seat the
            # AI holds, as every room's record does.
            game = self.service.create_game(
                player_1_id=coach.id,
                player_1_name=coach.name,
                ai_seats=[2],
            )
        else:
            # `ai_seats=[]`: a room says outright that no seat is
            # the AI's, so a seat nobody holds is empty rather than
            # the AI's.
            game = self.service.create_game(
                player_1_id=coach.id,
                player_1_name=coach.name,
                in_lobby=True,
                ai_seats=[],
            )
            if tutorial:
                self.service.configure(game.game_id, "tutorial")
                if against_ai:
                    self.service.start_lobby(game.game_id)
        self.rooms.first_sight(game.game_id, coach.id)
        return web.json_response(
            {"id": game.game_id, "url": f"/room/{game.game_id}"},
        )

    async def close_room(self, request: web.Request) -> web.Response:
        """
        Close a room whose game never started -- `discard_game`, whose
        refusal (anything played is abandoned, never erased) is the
        service's and answers 409. Asked by somebody seated, or an
        admin.
        """
        game = self._game(request)
        coach = self._required_coach(request)
        if seat_of(game, coach.id) is None and not self.rooms.is_admin(
            game.game_id, coach.id,
        ):
            raise web.HTTPForbidden(
                text="Only a coach in this room, or its admin, may close it.",
            )
        async with self.locks.hold(game.game_id):
            try:
                self.service.discard_game(game.game_id)
            except ValueError as refusal:
                raise web.HTTPConflict(text=str(refusal))
            self.journals.pop(game.game_id, None)
            self.chats.pop(game.game_id, None)
        return web.json_response({"url": "/"})

    async def table(self, request: web.Request) -> web.Response:
        """
        The table before kickoff: `start`, `configure` (`{"setting",
        "value"}`), `pick_team` (`{"team", "seat"?}`), `flip_coin` and
        `choose` (`{"choice": "home" | "visiting"}`) -- each one service
        door over the record's rule, answered with the room's state,
        or with the record's sentence and a 409 when it refuses.

        Only somebody seated sets the table, which is the one thing
        decided here -- the Discord setup views' "either player" gate,
        made with the cookie. Which seat a move is for is the seat the
        reader holds; a test game's one coach holds both, and says
        which. A value off the wire is built into the model's type
        here, where a wire value becomes one (d12ball/wire.py's reason
        for `Action.from_dict`), and one the record cannot read is a
        400: a bug in the page, not a rule.

        **The match is dealt by the toss or by the choice, and `begin`
        runs in the same request**, as the cog runs it straight after
        either: nothing in the match says "dealt, and not yet begun",
        so a separate Begin could only be offered off a reading the
        model does not have.
        """
        game = self._game(request)
        coach = self._required_coach(request)
        move = request.match_info["move"]
        body = await _body(request) if request.can_read_body else {}
        held = seats_held(game, coach.id)
        if not held:
            raise web.HTTPForbidden(
                text="Only a coach in this room may set the table.",
            )

        async with self.locks.hold(game.game_id):
            try:
                if move == "start":
                    self.service.start_lobby(game.game_id)
                elif move == "configure":
                    self._configure(game, body)
                elif move == "pick_team":
                    team = _wire(Team, body.get("team"), "That is not a team.")
                    seat = body.get("seat", held[0])
                    if isinstance(seat, bool) or seat not in (1, 2):
                        raise web.HTTPBadRequest(text="A seat is 1 or 2.")
                    if seat not in held:
                        raise web.HTTPForbidden(text="That is not your seat.")
                    self.service.pick_team(game.game_id, seat, team)
                elif move == "flip_coin":
                    self.service.flip_coin(game.game_id, held[0])
                    self._begin_if_dealt(game)
                elif move == "choose":
                    choice = _wire(
                        HomeChoice, body.get("choice"), "That is not a side.",
                    )
                    # The seat the toss asks, where the reader holds it;
                    # otherwise theirs, and the record says why not.
                    owed = game.home_choice_owed_by
                    seat = owed if owed in held else held[0]
                    self.service.choose_home_or_visiting(
                        game.game_id, seat, choice,
                    )
                    self._begin_if_dealt(game)
                else:
                    raise web.HTTPNotFound()
            except RuleRefusal as refusal:
                return web.json_response(
                    {
                        **self._state(
                            game,
                            self._viewer(request, game),
                            since=_since(request),
                            coach=coach,
                        ),
                        "refusal": str(refusal),
                    },
                    status=409,
                )
            state = self._state(
                game,
                self._viewer(request, game),
                since=_since(request),
                coach=coach,
            )
        return web.json_response(state)

    def _configure(self, game: D12BallGame, body: Mapping[str, Any]) -> None:
        setting = body.get("setting")
        if not isinstance(setting, str):
            raise web.HTTPBadRequest(text="Name the setting.")
        try:
            self.service.configure(game.game_id, setting, body.get("value"))
        except RuleRefusal:
            raise
        except (TypeError, ValueError):
            raise web.HTTPBadRequest(text="That is not a setting this game has.")

    def _begin_if_dealt(self, game: D12BallGame) -> None:
        """The pre-kickoff window, opened once the toss or the choice
        has dealt the match; what it says reaches the journal through
        the service's listeners."""
        if game.match_state is not None:
            self.service.begin(game.game_id)

    async def rematch(self, request: web.Request) -> web.Response:
        """
        The rematch under a finished game (`GameService.rematch`): a new
        room with its settings and the same two seats -- or the AI
        where it sat -- opening at its Start. Asked by a coach of the
        finished game; a second ask finds the first. Everybody in the
        old room is sent on by its state's `rematch`.
        """
        game = self._game(request)
        coach = self._required_coach(request)
        if seat_of(game, coach.id) is None:
            raise web.HTTPForbidden(
                text="Only a coach of this game may start its rematch.",
            )
        async with self.locks.hold(game.game_id):
            try:
                rematch = self.service.rematch(game.game_id, in_lobby=True)
            except RuleRefusal as refusal:
                raise web.HTTPConflict(text=str(refusal))
            for seated in seats_held_by(rematch):
                self.rooms.first_sight(rematch.game_id, seated)
            state = self._state(
                game,
                self._viewer(request, game),
                since=_since(request),
                coach=coach,
            )
        return web.json_response(state)

    async def seat(self, request: web.Request) -> web.Response:
        """
        `take` (the free seat, or `{"seat": n}`), `leave`, `ai`
        (`{"seat": n}`: the AI put in an empty seat, by anybody seated)
        or `kick` (`{"seat": n}`, an admin's: a person or the AI taken
        out) -- each one service door over the record's rule, and the
        record's sentence when it refuses.

        Who may *ask* -- somebody seated, an admin -- is the one thing
        decided here; whether the seat may change is still the
        record's.
        """
        game = self._game(request)
        coach = self._required_coach(request)
        move = request.match_info["move"]
        body = await _body(request) if request.can_read_body else {}
        seat = body.get("seat")
        if seat is not None and (isinstance(seat, bool) or seat not in (1, 2)):
            raise web.HTTPBadRequest(text="A seat is 1 or 2.")

        async with self.locks.hold(game.game_id):
            try:
                if move == "take":
                    self.service.take_seat(
                        game.game_id, coach.id, coach.name, seat,
                    )
                elif move == "leave":
                    self.service.vacate_seat(game.game_id, coach.id)
                elif move == "ai":
                    if seat_of(game, coach.id) is None:
                        raise web.HTTPForbidden(
                            text="Take a seat to put the AI in the other.",
                        )
                    if seat is None:
                        raise web.HTTPBadRequest(text="Name the seat.")
                    self.service.seat_ai(game.game_id, seat)
                elif move == "kick":
                    if not self.rooms.is_admin(game.game_id, coach.id):
                        raise web.HTTPForbidden(
                            text="Only an admin of this room may kick a seat.",
                        )
                    if seat is None:
                        raise web.HTTPBadRequest(text="Name the seat.")
                    held_by = game.player_1_id if seat == 1 else game.player_2_id
                    if game.ai_holds(seat):
                        self.service.unseat_ai(game.game_id, seat)
                    elif held_by is None:
                        raise RuleRefusal("Nobody holds that seat.")
                    else:
                        self.service.vacate_seat(game.game_id, held_by)
                else:
                    raise web.HTTPNotFound()
            except RuleRefusal as refusal:
                return web.json_response(
                    {
                        **self._state(
                            game,
                            self._viewer(request, game),
                            since=_since(request),
                            coach=coach,
                        ),
                        "refusal": str(refusal),
                    },
                    status=409,
                )
            state = self._state(
                game,
                self._viewer(request, game),
                since=_since(request),
                coach=coach,
            )
        return web.json_response(state)

    async def drop_admin(self, request: web.Request) -> web.Response:
        """Give the admin role up. Nobody else's role changes, and the
        room may be left with no admin at all -- anybody can take it
        again."""
        game = self._game(request)
        coach = self._required_coach(request)
        self.rooms.drop_admin(game.game_id, coach.id)
        return web.json_response(
            self._state(
                game,
                self._viewer(request, game),
                since=_since(request),
                coach=coach,
            ),
        )

    async def take_admin(self, request: web.Request) -> web.Response:
        """Anybody in the room may become its admin, by asking -- the
        page confirms first, which is what makes it deliberate."""
        game = self._game(request)
        coach = self._required_coach(request)
        self.rooms.make_admin(game.game_id, coach.id)
        return web.json_response(
            self._state(
                game,
                self._viewer(request, game),
                since=_since(request),
                coach=coach,
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
        # Home first once the coin has settled it; before that, at the
        # table, the two seats in order -- no seat is Home yet.
        first, second = (
            (game.home_player_number, game.visiting_player_number)
            if game.home_and_visiting_selected
            else (1, 2)
        )
        title = (
            f"PBD{game.game_number} - "
            f"{format_player_with_team_name(game, first)}"
            f" vs. "
            f"{format_player_with_team_name(game, second)}"
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
        coach: Optional[Coach] = None,
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
                "coach": None if coach is None else coach.to_dict(),
            },
            "room": self._room(game, viewer, coach),
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
            # Before kickoff the prompt's place is the table's.
            "table": (
                self._table(game, coach) if game.match_state is None else None
            ),
            "rematch": self._rematch_of(game),
            "entries": journal.since(
                since, game, self._snapshot_layout(game),
            ),
            "latest": journal.next_id - 1,
            "chat": chat.since(chat_since),
            "chat_latest": chat.next_id - 1,
        }

    def _room(
        self,
        game: D12BallGame,
        viewer: Viewer,
        coach: Optional[Coach],
    ) -> dict:
        """
        The room as its page draws it: both seats, how many are
        watching, whether this reader is an admin, and what they are.

        Home and visiting are read off the record's
        `home_player_number` / `visiting_player_number`, never worked
        out here: until the coin has settled them the seats are Coach
        1 and Coach 2, because no seat is Home before the toss.
        """
        number = viewer.player_number
        if number is None:
            role = "observer"
        elif number == game.home_player_number:
            role = "home"
        elif number == game.visiting_player_number:
            role = "visiting"
        else:
            role = "coach"
        return {
            "seats": [self._seat(game, one, number) for one in (1, 2)],
            "observers": self._observers(game),
            "admin": self.rooms.is_admin(
                game.game_id, None if coach is None else coach.id,
            ),
            "role": role,
        }

    def _observers(self, game: D12BallGame) -> int:
        """How many have been in the room without holding a seat."""
        seated = {game.player_1_id, game.player_2_id} - {None}
        return len(self.rooms.room(game.game_id).seen - seated)

    def _rematch_of(self, game: D12BallGame) -> Optional[dict]:
        """Where a finished game's rematch is, once somebody opened it
        -- which every page in the room follows."""
        rematch = (
            self.service.games.get(game.rematch_game_id)
            if game.rematch_game_id is not None
            else None
        )
        if rematch is None:
            return None
        return {"id": rematch.game_id, "url": f"/room/{rematch.game_id}"}

    def _table(self, game: D12BallGame, coach: Optional[Coach]) -> dict:
        """
        Everything between two seats claimed and the first prompt, as
        the page draws it in the prompt's place: the settings, both
        seats and the teams this reader may pick for theirs, the coin,
        home or visiting, and Start.

        **Every question on it is the record's.** Which settings are
        open is `open_settings`, which teams a seat may pick is
        `teams_open_to`, whether the coin is owed is `coin_is_owed`,
        who owes the choice is `home_choice_owed_by` and which side
        they may take is `home_choice_rail` -- the same readings the
        Discord setup views draw from and the service's doors refuse
        against. What is decided here is only who may press: somebody
        seated. An observer is sent the same table with every control
        off.
        """
        held = seats_held(game, None if coach is None else coach.id)
        seated = bool(held)
        open_settings = set(game.open_settings())

        def setting(name: str, label: str, value, choices) -> dict:
            return {
                "name": name,
                "label": label,
                "value": value,
                "choices": [
                    {"value": one, "label": text} for one, text in choices
                ],
                "may_change": seated and name in open_settings,
            }

        settings = [
            setting(
                "mode", "Mode", GameMode(game.mode).value,
                [(mode.value, mode.value.title()) for mode in GameMode],
            ),
            setting(
                "board", "Board", str(game.board_size),
                [
                    (str(size), f"{size} spaces")
                    for size in sorted(VALID_BOARD_SIZES)
                ],
            ),
        ]
        if game.is_solo_game:
            # The AI's row where the AI holds a seat, as the Discord
            # settings block draws it only for a solo game.
            settings.append(
                setting(
                    "ai", "AI",
                    AIOpponent(game.ai_opponent or AIOpponent.DINKY).value,
                    [(ai.value, name) for ai, name in AI_OPPONENT_NAMES.items()],
                ),
            )
        settings += [
            setting("test", "Test game", game.test_game, ()),
            setting("tutorial", "Tutorial", game.tutorial, ()),
            setting("name", "Name", game.game_name or "", ()),
        ]

        owed_by = game.home_choice_owed_by
        rail = None if owed_by is None else game.home_choice_rail(owed_by)
        return {
            "lobby": game.in_lobby,
            "settings": settings,
            "seats": [
                self._table_seat(game, number, number in held)
                for number in (1, 2)
            ],
            "start": {
                "owed": game.in_lobby,
                "may": seated and game.in_lobby,
            },
            "coin": {
                "owed": game.coin_is_owed,
                "may": seated and game.coin_is_owed,
                "flipped": game.coin_flipped,
                "face": (
                    None if game.coin_face is None
                    else game.coin_face.value
                ),
                "winner": game.coin_winner_player_number,
            },
            "sides": {
                "owed_by": owed_by,
                "may": owed_by is not None and owed_by in held,
                "choices": [
                    {
                        "value": choice.value,
                        "label": choice.value.title(),
                        "open": rail is None or choice == rail,
                    }
                    for choice in HomeChoice
                ],
            },
            "may_close": (
                seated
                or self.rooms.is_admin(
                    game.game_id, None if coach is None else coach.id,
                )
            ) and game.status == GameStatus.SETUP,
        }

    def _table_seat(self, game: D12BallGame, number: int, yours: bool) -> dict:
        """One seat at the table: who holds it, its team, and -- where
        it is this reader's -- the picker's two rows, each team offered
        or greyed as the record says."""
        seat = self._seat(game, number, number if yours else None)
        coach = self._coach(game, number)
        offered = set(game.teams_open_to(number)) if yours else set()
        seat.update(
            team=coach["team"],
            team_key=coach["team_key"],
            colour=coach["colour"],
            teams=[
                {
                    "key": team.value,
                    "name": team_display_name(team),
                    "colour": TEAM_COLORS[team],
                    "row": row,
                    "open": team in offered,
                }
                for row, teams in enumerate((COLOR_TEAMS, SPECIES_TEAMS))
                for team in teams
            ] if offered else [],
        )
        return seat

    def _seat(
        self, game: D12BallGame, number: int, yours: Optional[int],
    ) -> dict:
        held_by = game.player_1_id if number == 1 else game.player_2_id
        # Whether the AI plays this seat is the record's one reading
        # (`ai_holds`), and the AI is named the way the model names it.
        ai = game.ai_holds(number)
        return {
            "number": number,
            "label": seat_label(game, number),
            "name": (
                coach_name(game, number)
                if held_by is not None or ai
                else None
            ),
            "ai": ai,
            "free": game.seat_is_free(number),
            "yours": number == yours,
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


def seat_of(game: D12BallGame, coach_id: Optional[int]) -> Optional[int]:
    """
    Which seat of this room `coach_id` holds -- the comparison
    `SafeView.may_act_for` makes with a Discord id, made with the
    cookie's. Seat 1 first, which is the one a test game's coach is
    read as.
    """
    if coach_id is None:
        return None
    if coach_id == game.player_1_id:
        return 1
    if coach_id == game.player_2_id:
        return 2
    return None


def seats_held(game: D12BallGame, coach_id: Optional[int]) -> list[int]:
    """
    Every seat `coach_id` holds, in order: one, or both for a test
    game's one coach (who plays both sides), or none. `seat_of` is the
    one a page acts as; this is what the table asks "is it theirs" of.
    """
    if coach_id is None:
        return []
    return [
        number
        for number, held_by in ((1, game.player_1_id), (2, game.player_2_id))
        if held_by == coach_id
    ]


def seats_held_by(game: D12BallGame) -> set[int]:
    """The people seated in a game."""
    return {game.player_1_id, game.player_2_id} - {None}


def room_status(game: D12BallGame) -> str:
    """Where a room stands, as the front door sorts it: the lobby, the
    rest of setup, the game, or finished."""
    if game.in_lobby:
        return "lobby"
    return GameStatus(game.status).value


def seat_label(game: D12BallGame, number: int) -> str:
    """What a seat is called: Coach 1 and Coach 2 until the coin has
    settled home and visiting, then the side the record says."""
    if game.home_player_number == number:
        return "Home Team Coach"
    if game.visiting_player_number == number:
        return "Visitors Team Coach"
    return f"Coach {number}"


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
            if control.get("post"):
                # Not an answer to the match (the rematch): it has a
                # route of its own and is never one here.
                continue
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


def _wire(kind, value, refusal: str):
    """A value off the wire, as the model's type -- or a 400, since a
    value the page was never offered is a bug in the page."""
    try:
        return kind(value)
    except (TypeError, ValueError):
        raise web.HTTPBadRequest(text=refusal)


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
    rooms: Optional[Rooms] = None,
) -> WebApp:
    """Start the server over `service` on this process's event loop."""
    app = WebApp(
        service,
        locks,
        rooms=rooms,
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


async def serve(
    games_file: Path = WEB_GAMES_FILE,
    rooms_file: Path = WEB_ROOMS_FILE,
) -> None:
    """Run the web app over `games_file` (and its rooms over
    `rooms_file`) until cancelled."""
    service = build_service(games_file)
    LOGGER.info(
        "Loaded %d web game(s) from %s.", len(service.games), games_file,
    )
    rooms = Rooms.load(rooms_file, service.games)
    app = await start_web_app(service, GameLocks(), rooms=rooms)
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
