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
played from two pages: the journal (`webapp/journal.py`) is fed by every result the
service produces, through `GameService.listeners`, so a coach watching
a web page sees the other coach's turn as it happens.
"""

from __future__ import annotations

import asyncio
import copy
import logging
import os
import time
from pathlib import Path
from typing import Any, Mapping, Optional

from aiohttp import web

from dotenv import load_dotenv

from d12ball import stats, tutorial
from d12ball.ai import build_ai_strategies
from d12ball.components import (
    MatchState,
    TeamSide,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.engine import RulesEngine
from d12ball.formatting import (
    AI_OPPONENT_NAMES,
    GAME_MODE_NAMES,
    SETTING_DEFINITIONS,
    coach_name,
    configure_warning,
    describe_game_mode,
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
from d12ball.dice_brief import maneuver_challenge_brief
from d12ball.flow import FollowOnStep
from d12ball.prompts import (
    Action,
    PendingPrompt,
    PromptKind,
    asked_sides,
    pending,
)
from d12ball.rules_doc import LIVING_RULES_PATH, RulesDocument, load_rules_document
from d12ball.render import TEAM_COLORS, render_match_image
from gamelocks import GameLocks
from gamesaves.d12ball.service import Batching, GameResult, GameService
from gamesaves.d12ball.storage import WEB_GAMES_FILE, load_games, save_games
from webapp import aids, identity, keys, pictures
from webapp.identity import Coach
from webapp.board import (
    DEFENDED_ENDS, board_layout, clock_note, period_name, side_colour,
)
from webapp.present import (
    PROMPT_PICTURES,
    Viewer,
    controls_for,
    full_time,
    hand_table,
    lit_line,
    plain_text,
    prompt_picture_key,
    render_text,
    reveal,
    shootout_sides,
    split_footnote,
    still_to_answer,
    waiting_on,
)
from webapp.chat import WEB_CHAT_FILE, Chats, MessageRefused, clean_text
from webapp.journal import WEB_JOURNAL_FILE, Journal, Journals
from webapp.names import WEB_NAMES_FILE, Names, NameTaken
from webapp.rooms import WEB_ROOMS_FILE, Rooms

LOGGER = logging.getLogger(__name__)

STATIC = Path(__file__).resolve().parent / "static"

#: How many rendered boards are kept in hand. A board is ~200KB and a
#: page asks for one per entry it draws, so a few are worth keeping
#: and a game's worth is not.
BOARD_CACHE = 24

#: How many rolls' dice are kept in hand. An entry never changes, so
#: its picture is drawn once however many pages ask; a dice image is
#: small, and a game rolls a few dozen times.
DICE_CACHE = 64

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
#: The web app's batching (principle 8): the one step whose lines it
#: closes into a group of their own is the walk-in, so the log can
#: say what the challenge is -- the group tagged
#: `AUTO_RESOLVE_CHALLENGER` names the challenger (`Narration.arguments`),
#: and a walk-in carried into the next step's lead-in would name
#: nobody. Every other line goes where it goes by default; Discord's
#: economy (`DiscordBatching`) is not the web's.
WEB_BATCHING = Batching(
    own_message=frozenset({FollowOnStep.AUTO_RESOLVE_CHALLENGER}),
)

#: What a response says about caching when its handler said nothing.
#: `/static/` is served under unversioned names, and a page and its
#: script change together: with no header, Cloudflare in front of
#: `play.d12ball.com` kept `app.js` and `app.css` for four hours while
#: `game.html` came fresh, and a room drew nothing -- the new page under
#: the old script -- until the edge let go. `no-cache` still lets the
#: edge and the browser keep a copy; they ask with its ETag first, and
#: an unchanged file is a 304. A handler that sets its own (a card, an
#: emoji, a font) keeps it.
DEFAULT_CACHE_CONTROL = "no-cache"


@web.middleware
async def revalidate_by_default(
    request: web.Request, handler,
) -> web.StreamResponse:
    """`DEFAULT_CACHE_CONTROL` on every response that did not say."""
    response = await handler(request)
    response.headers.setdefault("Cache-Control", DEFAULT_CACHE_CONTROL)
    return response


#: What a response over the tunnel's HTTPS tells the browser: use
#: nothing else for this host for a year, so a typed or pasted
#: `play.d12ball.com` never goes out as `http://` again after the first
#: visit. The host alone -- d12ball.com and its other names are the
#: landing pages', not this process's to speak for.
STRICT_TRANSPORT = "max-age=31536000"


@web.middleware
async def https_only(
    request: web.Request, handler,
) -> web.StreamResponse:
    """
    A browser that reached the tunnel over plain `http://` is sent to
    the same path over `https://` before anything answers it: the
    cookie is `Secure`, so that browser would send none and be handed a
    second person -- an observer in their own room (`identity.
    came_over_plain_http`). A 308, so a POST is repeated as a POST. The
    address is `FOOLBOT_WEB_URL`'s where it is `https://`, and the
    request's own host otherwise.

    Over HTTPS through the tunnel, every response says so for the next
    year (`STRICT_TRANSPORT`). A request with no tunnel in front of it
    is neither: a checkout on a laptop stays on `http://localhost`.
    """
    if identity.came_over_plain_http(request):
        base = keys.base_url()
        if not base.startswith("https://"):
            base = f"https://{request.host}"
        raise web.HTTPPermanentRedirect(f"{base}{request.path_qs}")
    response = await handler(request)
    if identity.came_over_https(request) and not request.secure:
        response.headers.setdefault(
            "Strict-Transport-Security", STRICT_TRANSPORT,
        )
    return response


#: How long a room may go with nobody's page open on it before the
#: front door stops offering it to strangers, in seconds: a day, the
#: author's choice (2026-09-26), after the outage left rooms opened by
#: people who saw nothing and never came back. The room is not closed.
OPEN_ROOM_IDLE = 24 * 60 * 60


PORT_VARIABLE = "FOOLBOT_WEB_PORT"
HOST_VARIABLE = "FOOLBOT_WEB_HOST"
DEFAULT_PORT = 8080


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
        chats: Optional[Chats] = None,
        journals: Optional[Journals] = None,
        names: Optional[Names] = None,
        host: str = "0.0.0.0",
        port: int = 8080,
    ) -> None:
        self.service = service
        self.locks = locks
        #: Who is admin in each room and who has been in -- the web
        #: app's own file (`webapp/rooms.py`); in memory when none is
        #: handed in, which is what a test wants.
        self.rooms = rooms if rooms is not None else Rooms()
        #: What the people in each room have said -- the web app's own
        #: file too (`webapp/chat.py`), in memory for a test.
        self.chats = chats if chats is not None else Chats()
        #: What has been said in each game -- the web app's own file
        #: too (`webapp/journal.py`), in memory for a test.
        self.journals = journals if journals is not None else Journals()
        #: Which name each person holds, so no two hold the same one
        #: (`webapp/names.py`) -- in memory for a test.
        self.names = names if names is not None else Names()
        self.host = host
        self.port = port
        #: The kind of question a click on this page is answering, per
        #: game, for as long as the service is answering it -- the
        #: listener hears the result and not the action, and the
        #: journal keeps a coach's own block out of the log by it
        #: (`Journal.add`'s `answered`). Set and cleared under the
        #: game's lock, around a call with no `await` in it.
        self._answering: dict[str, PromptKind] = {}
        self._boards: dict[tuple, bytes] = {}
        self._cards: dict[tuple, bytes] = {}
        self._dice: dict[tuple, bytes] = {}
        self._runner: Optional[web.AppRunner] = None
        #: The time, per game, somebody last had its page open -- every
        #: poll sets it -- which is what takes a room nobody comes back
        #: to off the Open rooms list (`OPEN_ROOM_IDLE`). Memory only:
        #: after a restart a room counts from the restart, which puts
        #: off hiding it and never hides one early.
        self.clock = time.time
        self._started = self.clock()
        self._looked_at: dict[str, float] = {}
        self.app = web.Application(
            middlewares=[https_only, revalidate_by_default],
        )
        self.app.add_routes(
            [
                web.get("/", self.index),
                web.get("/api/me", self.who_am_i),
                web.post("/api/me", self.call_me),
                web.delete("/api/me/games", self.delete_my_games),
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
                web.post("/api/room/{game_id}/abandon", self.abandon),
                web.get("/api/room/{game_id}/stats", self.room_stats),
                web.get("/api/stats", self.all_stats),
                web.get("/stats", self.stats_page),
                web.post("/api/room/{game_id}/admin", self.take_admin),
                web.post("/api/room/{game_id}/chat", self.say),
                web.get(
                    "/api/room/{game_id}/detail/{entry_id}.png", self.dice,
                ),
                web.get(
                    "/api/room/{game_id}/prompt.png", self.prompt_picture,
                ),
                web.delete("/api/room/{game_id}/admin", self.drop_admin),
                web.get("/api/game/{game_id}", self.state),
                web.post("/api/game/{game_id}/action", self.act),
                web.post("/api/game/{game_id}/resume", self.resume),
                web.get("/api/game/{game_id}/board.png", self.board),
                web.get(
                    "/api/game/{game_id}/card/{card_id}.png", self.player_card,
                ),
                web.get(
                    "/api/game/{game_id}/maneuver/{key}.png",
                    self.maneuver_card,
                ),
                web.get(
                    "/api/game/{game_id}/maneuver-back.png",
                    self.maneuver_back,
                ),
                web.get("/api/game/{game_id}/goal/{side}.png", self.goal),
                web.get("/api/room/{game_id}/log.txt", self.log_text),
                # The Reading Room and the Rules tab (step 11 of
                # docs/web-app-next.md, redrawn in step 10 of
                # docs/web-app-redesign.md): the rules, the Learn to Play
                # and the player aids, read-only and open to anybody.
                # No PDF anywhere.
                web.get("/rules", self.rules_page),
                web.get("/api/rules", self.rules_search),
                web.get("/api/rules/charter", self.rules_charter),
                web.get("/api/rules/learn", self.rules_learn),
                web.get("/rules/figures/{name}", self.rules_figure),
                web.get("/api/aids", self.all_aids),
                web.get("/aids/cards/{key}.png", self.card_aid),
                web.get("/aids/maneuvers/{tier}.png", self.maneuver_aid),
                web.get("/aids/roles.png", self.roles_aid),
                web.get("/aids/species/{number}.png", self.species_aid),
                web.get("/aids/team/{team}/{card_id}.png", self.team_aid),
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
            self.journals.add(
                game.game_id,
                result,
                challenge=lambda challenger_id: self._challenge_line(
                    game, challenger_id,
                ),
                answered=self._answering.get(game.game_id),
            )
        except Exception:  # pragma: no cover - a frontend's own bug
            LOGGER.exception(
                "The web journal could not record a result for game %s",
                game.game_id,
            )

    def _challenge_line(self, game: D12BallGame, challenger_id: str) -> str:
        """
        The challenge image in words, for the log: the same brief the
        cog draws it from (`dice_brief.maneuver_challenge_brief`) -- who
        is on the ball, who challenges them, where, and the skill each
        brings. Read off the match as it stands after the run, which is
        the position the cog draws the picture from too.
        """
        match = self._match(game)
        offense, defense, location = maneuver_challenge_brief(
            self.engine, match, challenger_id, game,
        )
        attacker = self.engine.format_player_label(
            match, self.engine.get_player_definition(match.active_player_id),
        )
        challenger = self.engine.format_player_label(
            match, self.engine.get_player_definition(challenger_id),
        )
        return (
            f"**Maneuver challenge**, {location}: {attacker}"
            f" ({offense.skill_name.lower()} skill {offense.skill:+d})"
            f" against {challenger}"
            f" ({defense.skill_name.lower()} skill {defense.skill:+d})."
        )

    def journal(self, game_id: str) -> Journal:
        return self.journals.journal(game_id)

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

    def _person(self, request: web.Request) -> Optional[Coach]:
        """
        Who sent this request, if they have said -- the cookie's id,
        under the name the names file says that id holds
        (`webapp/names.py`), which is the one reading of a person's
        name. The cookie's own name only for an id the file does not
        know yet, which `GET /api/me` settles on the next page load.
        """
        coach = identity.coach_for(request)
        if coach is None:
            return None
        held = self.names.name_of(coach.id)
        return coach if held is None else Coach(coach.id, held)

    def _viewer(self, request: web.Request, game: D12BallGame) -> Viewer:
        """Which seat of this room the reader holds, if either."""
        coach = self._person(request)
        return Viewer(None if coach is None else seat_of(game, coach.id))

    def _required_coach(self, request: web.Request) -> Coach:
        coach = self._person(request)
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
        """
        The person this browser's cookie names -- and somebody new, under
        a made-up name nobody holds (`Names.claim_guest`), when it names
        nobody. Every page asks this first, so a visitor is never asked
        for a name before they may do anything; they may change it after.

        A cookie whose id the names file does not know -- one set before
        the file was, or under a file started afresh -- keeps its name
        if nobody else holds it, and is given a made-up one if somebody
        does, so two people are never called the same.
        """
        coach = identity.coach_for(request)
        if coach is not None and self.names.name_of(coach.id) is not None:
            return web.json_response(self._person(request).to_dict())
        if coach is None:
            lost = identity.unverified_claim(
                request.cookies.get(identity.COOKIE),
            )
            coach = identity.issue(identity.guest_name())
            name = self.names.claim_guest(coach.id)
            if lost is not None:
                # Somebody came back with a cookie this server did not
                # sign -- the secret changed under them -- and is now
                # somebody new: an observer in their own rooms until an
                # admin hands the seat back. Never routine.
                LOGGER.warning(
                    "A cookie for %r (id %r) failed its signature and "
                    "was replaced by %s (id %d): has %s changed?",
                    lost["name"], lost["id"], name, coach.id,
                    keys.SECRET_VARIABLE,
                )
        elif self.names.is_free_for(coach.name, coach.id):
            name = self.names.claim(coach.id, coach.name)
        else:
            name = self.names.claim_guest(coach.id)
        coach = Coach(coach.id, name)
        await self._rename_seats(coach)
        response = web.json_response(coach.to_dict())
        identity.set_cookie(response, request, coach)
        return response

    async def call_me(self, request: web.Request) -> web.Response:
        """
        Take a name: the same id under the new name, refused with 409
        when somebody else holds it (`Names.claim`), and carried to the
        seats the person holds (`GameService.rename_coach`).
        """
        body = await _body(request)
        known = identity.coach_for(request)
        coach_id = identity.issue_id() if known is None else known.id
        try:
            name = self.names.claim(coach_id, body.get("name"))
        except NameTaken as refusal:
            raise web.HTTPConflict(text=str(refusal))
        except identity.NameRefused as refusal:
            raise web.HTTPBadRequest(text=str(refusal))
        coach = Coach(coach_id, name)
        await self._rename_seats(coach)
        response = web.json_response(coach.to_dict())
        identity.set_cookie(response, request, coach)
        return response

    async def _rename_seats(self, coach: Coach) -> None:
        """A person's name carried to every seat they hold, each under
        its game's lock."""
        for game in list(self.service.games.values()):
            if seat_of(game, coach.id) is None:
                continue
            async with self.locks.hold(game.game_id):
                if game.game_id in self.service.games:
                    self.service.rename_coach(game.game_id, coach.id, coach.name)

    async def delete_my_games(self, request: web.Request) -> web.Response:
        """
        "Delete all my games": every game the reader holds a seat in --
        the front door's "Your rooms" -- erased whatever it stands at
        (`GameService.delete_game`), with its journal, chat and room
        state, each under its game's lock; then a new made-up name for
        the reader, on the same id. The page has asked "are you sure"
        before this is sent. The other people in those games lose them
        too, which is what the question says.
        """
        coach = self._required_coach(request)
        deleted = 0
        for game in list(self.service.games.values()):
            if seat_of(game, coach.id) is None:
                continue
            async with self.locks.hold(game.game_id):
                if game.game_id not in self.service.games:
                    continue
                self.service.delete_game(game.game_id)
                self.journals.forget(game.game_id)
                self.chats.forget(game.game_id)
                self.rooms.forget(game.game_id)
                self._answering.pop(game.game_id, None)
                deleted += 1
        renamed = Coach(coach.id, self.names.claim_guest(coach.id))
        response = web.json_response(
            {"coach": renamed.to_dict(), "deleted": deleted},
        )
        identity.set_cookie(response, request, renamed)
        return response

    async def page(self, request: web.Request) -> web.Response:
        """A room's page. Everything on it arrives from the API below,
        so this is the same file for every room; its link is good for
        as long as the game record is."""
        self._game(request)
        return web.FileResponse(STATIC / "game.html")

    async def state(self, request: web.Request) -> web.Response:
        game = self._game(request)
        coach = self._person(request)
        self._looked_at[game.game_id] = self.clock()
        async with self.locks.hold(game.game_id):
            self._arrive(game, coach)
            if coach is not None:
                self.rooms.call(game.game_id, coach.id, coach.name)
            state = self._state(
                game,
                self._viewer(request, game),
                **_cursors(request),
                coach=coach,
            )
        return web.json_response(state)

    # -- Rooms and seats ---------------------------------------------

    async def list_rooms(self, request: web.Request) -> web.Response:
        """
        The front door's three lists, in the order the page draws them:
        this reader's rooms, by where each stands; then every other
        room still being played -- the ones with a seat free, and
        after them the full ones (the author, 2026-09-27: somebody
        seated on one device opens the room from another, which is
        another person until they take their seat back over). A
        finished room is its coaches' alone, and a room nobody has had
        open for `OPEN_ROOM_IDLE` leaves everybody else's lists. Every
        room here is a game in the web app's own file -- the bot's
        games are never in this service.
        """
        coach = self._person(request)
        mine: dict[str, list] = {
            "lobby": [], "setup": [], "in_progress": [], "finished": [],
        }
        free: list = []
        full: list = []
        for game in sorted(
            self.service.games.values(),
            key=lambda one: one.game_number,
            reverse=True,
        ):
            held = coach is not None and seat_of(game, coach.id) is not None
            if held:
                mine[room_status(game)].append(self._listing(game, coach))
            elif not game.is_finished and not self._idle(game):
                (
                    free
                    if any(game.seat_is_free(number) for number in (1, 2))
                    else full
                ).append(self._listing(game, None))
        return web.json_response({"mine": mine, "open": free, "full": full})

    def _listing(self, game: D12BallGame, coach: Optional[Coach]) -> dict:
        """
        One room as the front door draws its card: the number and
        name, where it stands, both seats with their team's colour, the
        mode and the board, the clock or the result once there is a
        match, and whether it is this reader's move -- the gold edge,
        which is the same reading the room's own page makes (`_your_move`).
        """
        match = self._match(game)
        return {
            "id": game.game_id,
            "number": game.game_number,
            "name": game.game_name,
            "status": room_status(game),
            "abandoned": game.abandoned,
            "seats": [
                {
                    **{
                        key: value
                        for key, value in self._seat(game, number, None).items()
                        if key != "yours"
                    },
                    "team": self._coach(game, number)["team"],
                    "colour": self._coach(game, number)["colour"],
                }
                for number in (1, 2)
            ],
            "observers": self._observers(game),
            "tutorial": game.tutorial,
            "mode": GAME_MODE_NAMES[GameMode(game.mode)],
            "board_size": game.board_size,
            # The jumbotron's own words for the clock: the result once
            # it is over, the stage between the halves, the minute and
            # the half otherwise.
            "clock": (
                None if match is None
                else clock_note(game, match)
                or f"{match.scoreboard.time:02d}' {period_name(match)}"
            ),
            "your_move": self._your_move(game, match, coach),
            # The card's way out, so a dead room is cleared from the
            # front door without opening it: Close for a room nothing
            # was played in, Abandon for a game under way -- the same
            # two routes the room's own page calls, which judge again.
            "may_close": self._may_close(game, coach),
            # Whether Close asks "Are you sure?" first: only when it
            # would close a room on somebody else sitting in it.
            "close_asks": others_seated(game, coach),
            "may_abandon": (
                coach is not None
                and seat_of(game, coach.id) is not None
                and game.status == GameStatus.IN_PROGRESS
            ),
            # Leaving a seat from outside the room: the same route the
            # room's own menu calls, offered off the record's answer.
            "may_leave": _may_leave(game, coach),
            "url": f"/room/{game.game_id}",
        }

    def _your_move(
        self,
        game: D12BallGame,
        match: Optional[MatchState],
        coach: Optional[Coach],
    ) -> bool:
        """
        Whether the room is waiting on this reader: at the table, a
        move on it is theirs to make (`_table_moves`); in the game, the
        question up is theirs to answer -- `still_to_answer`, the same
        reading that marks the question box and the tab's title.
        """
        seat = None if coach is None else seat_of(game, coach.id)
        if seat is None or game.is_finished:
            return False
        if match is None:
            return self._table_moves(game, coach)
        waiting = pending(self.engine, game, match)
        if not isinstance(waiting, PendingPrompt):
            return False
        viewer = Viewer(seat)
        wire = waiting.to_dict()
        controls = controls_for(
            self.engine, game, match, waiting, viewer, wire=wire,
        )
        return bool(controls) and still_to_answer(
            self.engine, game, match, waiting, viewer, wire=wire,
        )

    async def open_room(self, request: web.Request) -> web.Response:
        """
        A new room, the creator in seat 1 in its lobby
        (`GameService.create_game`, as the Discord hub opens one). The
        page goes to the link this answers.

        The AI and the tutorial are both the lobby's to decide, not
        this route's: `ai_seats=[]` says outright that no seat is the
        AI's, so a seat nobody holds is empty rather than the AI's,
        and whoever is seated puts the AI in it from there
        (`POST /api/room/{id}/seat/ai`); the tutorial is the table's
        `tutorial` setting (`POST /api/room/{id}/table/configure`),
        open only while nobody else has joined.
        """
        coach = self._required_coach(request)
        game = self.service.create_game(
            player_1_id=coach.id,
            player_1_name=coach.name,
            in_lobby=True,
            ai_seats=[],
        )
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
            self.journals.forget(game.game_id)
            self.chats.forget(game.game_id)
            self.rooms.forget(game.game_id)
        return web.json_response({"url": "/"})

    async def table(self, request: web.Request) -> web.Response:
        """
        The table before kickoff: `start`, `configure` (`{"setting",
        "value"}`), `pick_team` (`{"team", "seat"?}`), `flip_coin` (which
        starts a game still in the lobby first -- the page's one
        control for both) and
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
                    if seat not in pick_seats(game, held):
                        raise web.HTTPForbidden(text="That is not your seat.")
                    self.service.pick_team(game.game_id, seat, team)
                elif move == "flip_coin":
                    # The coin starts the game: flipped in the lobby, it
                    # leaves it first -- `start_lobby`, refused in its
                    # own sentence while a seat or a team is missing --
                    # and the toss follows in the same request (the
                    # author, 2026-09-27: no whistle).
                    if game.in_lobby:
                        self.service.start_lobby(game.game_id)
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
                            **_cursors(request),
                            coach=coach,
                        ),
                        "refusal": str(refusal),
                        "refusal_law": await self._citation(refusal.law),
                    },
                    status=409,
                )
            state = self._state(
                game,
                self._viewer(request, game),
                **_cursors(request),
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
                **_cursors(request),
                coach=coach,
            )
        return web.json_response(state)

    async def abandon(self, request: web.Request) -> web.Response:
        """
        End this room's game with no result -- what `/d12ball
        abandon_game` does, through the same door
        (`GameService.abandon`, over `D12BallGame.abandon`, which
        refuses a game already over and answers 409). A seat may
        abandon, before kickoff or during the game; an observer may
        not. The page asks "Are you sure?" first, which is this
        frontend's version of the command's "confirm".

        The room stays: its number stays taken, its board and its log
        stay readable, and its statistics count it as abandoned.
        """
        game = self._game(request)
        coach = self._required_coach(request)
        if seat_of(game, coach.id) is None:
            raise web.HTTPForbidden(
                text="Only a coach of this game may abandon it.",
            )
        async with self.locks.hold(game.game_id):
            try:
                self.service.abandon(game.game_id)
            except RuleRefusal as refusal:
                raise web.HTTPConflict(text=str(refusal))
            state = self._state(
                game,
                self._viewer(request, game),
                **_cursors(request),
                coach=coach,
            )
        return web.json_response(state)

    async def seat(self, request: web.Request) -> web.Response:
        """
        `take` (the free seat, or `{"seat": n}`), `leave`, `ai`
        (`{"seat": n}`: the AI put in an empty seat, by anybody seated),
        `kick` (`{"seat": n}`: a person taken out, an admin's; the AI
        taken out, anybody seated's, as putting it in is) or `takeover`
        (`{"seat": n}`: whoever holds it out and the reader in, one
        move -- an admin's, and only while they watch) -- each one
        service door over the record's rule, and the record's sentence
        when it refuses.

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
                    if seat is None:
                        raise web.HTTPBadRequest(text="Name the seat.")
                    # The AI is taken out by whoever may put it in --
                    # anybody seated; a person, by an admin alone.
                    may_kick = self.rooms.is_admin(game.game_id, coach.id) or (
                        game.ai_holds(seat) and seat_of(game, coach.id) is not None
                    )
                    if not may_kick:
                        raise web.HTTPForbidden(
                            text="Only an admin of this room may kick a seat.",
                        )
                    held_by = game.player_1_id if seat == 1 else game.player_2_id
                    if game.ai_holds(seat):
                        self.service.unseat_ai(game.game_id, seat)
                    elif held_by is None:
                        raise RuleRefusal("Nobody holds that seat.")
                    else:
                        self.service.vacate_seat(game.game_id, held_by)
                elif move == "takeover":
                    if seat is None:
                        raise web.HTTPBadRequest(text="Name the seat.")
                    # The kick is an admin's, and so is this: somebody
                    # seated on one device takes the seat back from
                    # another by becoming the room's admin there.
                    if not self.rooms.is_admin(game.game_id, coach.id):
                        raise web.HTTPForbidden(
                            text="Only an admin of this room may take "
                            "over a seat.",
                        )
                    self.service.take_over_seat(
                        game.game_id, seat, coach.id, coach.name,
                    )
                else:
                    raise web.HTTPNotFound()
            except RuleRefusal as refusal:
                return web.json_response(
                    {
                        **self._state(
                            game,
                            self._viewer(request, game),
                            **_cursors(request),
                            coach=coach,
                        ),
                        "refusal": str(refusal),
                        "refusal_law": await self._citation(refusal.law),
                    },
                    status=409,
                )
            state = self._state(
                game,
                self._viewer(request, game),
                **_cursors(request),
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
                **_cursors(request),
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
                **_cursors(request),
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
                    **self._state(game, viewer, **_cursors(request)),
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
            self._answering[game.game_id] = action.kind
            try:
                result = self.service.apply_action(game.game_id, action)
            finally:
                self._answering.pop(game.game_id, None)
            state = self._state(game, viewer, **_cursors(request))
        written = result.to_dict()
        state["refusal"] = written["refusal"]
        # The Law the refusal cites, where the model named one
        # (`RuleRefusal.law`), as the Rules tab links it.
        state["refusal_law"] = await self._citation(written["refusal_law"])
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
            state = self._state(game, viewer, **_cursors(request))
        state["resumed"] = found
        return web.json_response(state)

    # -- The statistics -----------------------------------------------

    async def stats_page(self, request: web.Request) -> web.Response:
        """Every web game's numbers, as a page of its own (linked from
        the front door)."""
        return web.FileResponse(STATIC / "stats.html")

    async def room_stats(self, request: web.Request) -> web.Response:
        """
        This game's report -- `/d12ball stats game`, over the same
        `d12ball/stats.py` tables (`stats.game_tables`). Read-only, and
        anybody who can open the room may read it, as anybody in a
        channel may run the command. The page shows it at the end of a
        finished game.
        """
        game = self._game(request)
        match = self._match(game)
        tables = [] if match is None else stats.game_tables(
            [match], self.engine.maneuver_catalog, self.engine.player_catalog,
        )
        return web.json_response(
            {
                "heading": self._stats_heading(game, match),
                "standing": stats.game_standing(game),
                "tables": tables,
            },
        )

    def _stats_heading(
        self, game: D12BallGame, match: Optional[MatchState],
    ) -> str:
        """The "which game is this" line a game's report opens with,
        as the cog's `stats_game_heading` words it, under the room's
        own name."""
        standing = stats.game_standing(game)
        if match is None:
            return f"{self._title(game, match)} ({standing})"
        board = match.scoreboard
        return (
            f"{self._title(game, match)} -- "
            f"{team_display_name(match.home.team)} "
            f"{board.home_score}:{board.visiting_score} "
            f"{team_display_name(match.visiting.team)} "
            f"({standing}, {_period(match)} minute {board.time:02d})"
        )

    async def all_stats(self, request: web.Request) -> web.Response:
        """
        Every web game's numbers, cut by kind -- `/d12ball stats` with
        `source` the web app, over this process's own games (the ones
        `load_games(WEB_GAMES_FILE)` read at start and every save has
        written since). **The page never reads the bot's file**: a
        `source` other than `web` is a 400, not a wider read. The
        tables are `stats.report_tables`, the four reports the bot's
        four scoped commands post.
        """
        kind = request.query.get("kind") or stats.SCOPE_ALL
        source = request.query.get("source") or stats.SOURCE_WEB
        if kind not in (
            stats.SCOPE_ALL, stats.SCOPE_DINKY, stats.SCOPE_TEST,
            stats.SCOPE_HUMAN,
        ):
            raise web.HTTPBadRequest(text="No such kind of game.")
        if source != stats.SOURCE_WEB:
            raise web.HTTPBadRequest(
                text="The web app reports on its own games alone.",
            )
        games = list(self.service.games.values())
        in_scope = stats.games_in_scope(games, kind, stats.SOURCE_WEB)
        pairs, empty = stats.readable_matches(
            in_scope, self.engine.load_match_state,
        )
        return web.json_response(
            {
                "kind": kind,
                "kinds": [
                    {"value": value, "label": stats.SCOPE_LABELS[value]}
                    for value in (
                        stats.SCOPE_ALL, stats.SCOPE_HUMAN,
                        stats.SCOPE_DINKY, stats.SCOPE_TEST,
                    )
                ],
                "source": stats.SOURCE_WEB,
                "heading": stats.format_scope_heading(
                    kind, len(in_scope), empty, stats.SOURCE_WEB,
                    no_web_games=not games,
                ),
                "reports": [
                    {
                        "name": report,
                        "tables": stats.report_tables(
                            report,
                            pairs,
                            self.engine.maneuver_catalog,
                            self.engine.player_catalog,
                        ),
                    }
                    for report in stats.REPORTS
                ] if pairs else [],
            },
        )

    async def say(self, request: web.Request) -> web.Response:
        """
        One chat message, under the name on the poster's cookie.
        Anybody in the room may talk -- both coaches and every observer
        -- and it goes nowhere near the service: talking is not an
        action on the game, and a message is never on the record
        (`webapp/chat.py`). Answered with the room's state, so the
        poster sees their line at once.
        """
        game = self._game(request)
        coach = self._person(request)
        if coach is None:
            raise web.HTTPForbidden(text="Say who you are first.")
        body = await _body(request)
        try:
            text = clean_text(body.get("text"))
        except MessageRefused as refusal:
            raise web.HTTPBadRequest(text=str(refusal))
        async with self.locks.hold(game.game_id):
            self.chats.post(game.game_id, coach.id, coach.name, text)
            state = self._state(
                game,
                self._viewer(request, game),
                **_cursors(request),
                coach=coach,
            )
        return web.json_response(state)

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

    async def dice(self, request: web.Request) -> web.Response:
        """
        The dice one journal entry rolled, as a PNG -- read-only, like
        the board. Drawn by the same `render.py` function the Discord
        view for that roll calls, picked by the shape of the roll
        (`pictures.DICE`), in a worker thread, and kept: an entry never
        changes, so its picture is the same for every page that asks.
        """
        game = self._game(request)
        match = self._match(game)
        entry_id = _int(request.match_info["entry_id"])
        entry = (
            None
            if entry_id is None or match is None
            else self.journal(game.game_id).entry(entry_id)
        )
        if entry is None or pictures.dice_shape(entry.detail) is None:
            raise web.HTTPNotFound(text="Those dice are no longer in hand.")
        key = (game.game_id, entry_id)
        png = self._dice.get(key)
        if png is None:
            png = await asyncio.to_thread(
                pictures.dice_png, self.engine, game, match, entry.detail,
            )
            self._dice[key] = png
            while len(self._dice) > DICE_CACHE:
                self._dice.pop(next(iter(self._dice)))
        return web.Response(
            body=png,
            content_type="image/png",
            headers={"Cache-Control": "public, max-age=31536000"},
        )

    async def prompt_picture(self, request: web.Request) -> web.Response:
        """
        The picture the prompt the match is waiting on is asked over,
        as a PNG -- read-only, like the board: the shot over its roll or
        the challenge over the maneuver pick, by the prompt's kind
        (`present.PROMPT_PICTURES`), drawn in a worker thread by the
        function the cog calls for the same picture.

        What is drawn is the prompt the match is on *now*, whatever the
        URL says: its `v` and `p` are there so a browser asks again
        when the position or the question has moved, and the picture
        is kept with the boards under the same two.
        """
        game = self._game(request)
        match = self._match(game)
        waiting = None if match is None else pending(self.engine, game, match)
        prompt = waiting if isinstance(waiting, PendingPrompt) else None
        picture = prompt_picture_key(prompt, match)
        if picture is None:
            raise web.HTTPNotFound(text="This prompt has no picture.")
        key = (
            game.game_id,
            "prompt",
            self.journal(game.game_id).board_version,
            picture,
        )
        png = self._boards.get(key)
        if png is None:
            png = await asyncio.to_thread(
                PROMPT_PICTURES[prompt.kind], self.engine, game, match, prompt,
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

    async def maneuver_back(self, request: web.Request) -> web.Response:
        """The maneuver cards' back at this game's tier: a hand held
        face down (`present.hand_backs`)."""
        game = self._game(request)
        tier = self.engine.maneuver_reference_tier(game)
        size = request.query.get("size", "small")
        if size not in pictures.CARD_WIDTHS:
            raise web.HTTPBadRequest(text="A size is small or full.")
        return await self._card(
            ("maneuver_back", tier, size),
            lambda: pictures.maneuver_back_png(
                self.engine.maneuver_catalog, tier, size,
            ),
        )

    async def log_text(self, request: web.Request) -> web.Response:
        """
        The room's log as a plain-text file ("the whole log as text" at
        full time, step 5 of docs/web-app-redesign.md): every entry the
        journal holds, oldest first, its lines as the page showed them
        with each token in words (`present.plain_text`) -- the model's
        narration, nothing added but the time each was said. Open to
        anybody who can open the room, as the log is.
        """
        game = self._game(request)
        journal = self.journals.journal(game.game_id)
        blocks = [
            "\n".join([
                time.strftime("%H:%M:%S", time.gmtime(entry.at)) + " UTC",
                *(plain_text(game, line) for line in entry.lines),
            ])
            for entry in journal.entries
        ]
        return web.Response(
            text="\n\n".join(blocks) + ("\n" if blocks else ""),
            content_type="text/plain",
            charset="utf-8",
            headers={
                "Content-Disposition":
                f'inline; filename="d12ball-game-{game.game_number}.txt"',
            },
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

    # -- The reading room ----------------------------------------------

    async def _rules(self) -> RulesDocument:
        """
        The living rules, as `rules_doc` reads them for the bot's two
        commands. The file ships with the checkout, so a deployment
        without it is broken and worth an ERROR, as `load_rules` says
        on Discord; the page is answered 503.
        """
        try:
            return await asyncio.to_thread(load_rules_document)
        except OSError as error:
            LOGGER.error(
                "Could not read the living rules at %s: %s",
                LIVING_RULES_PATH,
                error,
            )
            raise web.HTTPServiceUnavailable(
                text="The rules document is missing from this checkout.",
            )

    async def _citation(self, slug: Optional[str]) -> Optional[dict]:
        """
        A refusal's Law as the page links it (`aids.citation`), or
        `None`. A rules file that cannot be read costs the link and
        never the answer: the refusal is still said.
        """
        if not slug:
            return None
        try:
            document = await asyncio.to_thread(load_rules_document)
        except OSError:
            return None
        return await asyncio.to_thread(aids.citation, document, slug)

    async def rules_page(self, request: web.Request) -> web.Response:
        """The Reading Room: the Laws, the Law text and the References,
        the Charter headed with its numbers (`webapp/aids.py`)."""
        document = await self._rules()
        offered = aids.everything(self.engine)
        text = await asyncio.to_thread(aids.rules_html, document, offered)
        return web.Response(text=text, content_type="text/html")

    async def rules_charter(self, request: web.Request) -> web.Response:
        """The living rules by Law, as the Rules tab lists them."""
        document = await self._rules()
        found = await asyncio.to_thread(aids.charter, document)
        return web.json_response(found)

    async def rules_learn(self, request: web.Request) -> web.Response:
        """The Learn to Play, in the page: the book's own markdown with
        its figures and its Law citations linked. A missing book is an
        ERROR and a 503, as the rules are."""
        document = await self._rules()
        try:
            book = await asyncio.to_thread(aids.cached_learn_to_play, document)
        except OSError as error:
            LOGGER.error("Could not read the Learn to Play: %s", error)
            raise web.HTTPServiceUnavailable(
                text="The Learn to Play is missing from this checkout.",
            )
        return web.json_response(book)

    async def rules_search(self, request: web.Request) -> web.Response:
        """`RulesDocument.search`, the answer `/d12ball rules_search`
        offers, for the reading room's search box."""
        document = await self._rules()
        query = request.query.get("q", "")[:200]
        found = await asyncio.to_thread(aids.search, document, query)
        return web.json_response({"query": query, "sections": found})

    async def rules_figure(self, request: web.Request) -> web.Response:
        """A figure the rules show, from the books' own folder."""
        path = aids.figure_path(request.match_info["name"])
        if path is None:
            raise web.HTTPNotFound()
        return web.FileResponse(
            path, headers={"Cache-Control": f"public, max-age={CARD_MAX_AGE}"},
        )

    async def all_aids(self, request: web.Request) -> web.Response:
        """The front door's reading room: every aid, with no game to
        ask which."""
        return web.json_response(aids.everything(self.engine))

    async def card_aid(self, request: web.Request) -> web.Response:
        """One maneuver card, the printed face the hand shows
        (`pictures.maneuver_card_png`), for the References."""
        key = request.match_info["key"]
        offense = aids.valid_card(self.engine.maneuver_catalog, key)
        if offense is None:
            raise web.HTTPNotFound()
        size = request.query.get("size", "small")
        if size not in pictures.CARD_WIDTHS:
            raise web.HTTPBadRequest(text="A size is small or full.")
        return await self._card(
            ("aid", "card", key, size),
            lambda: pictures.maneuver_card_png(
                self.engine.maneuver_catalog, self.engine.player_catalog,
                key, offense=offense, size=size,
            ),
        )

    async def maneuver_aid(self, request: web.Request) -> web.Response:
        tier = request.match_info["tier"]
        if not aids.valid_tier(tier):
            raise web.HTTPNotFound()
        return await self._card(
            ("aid", "maneuvers", tier),
            lambda: aids.maneuver_reference_png(
                self.engine.maneuver_catalog, tier,
            ),
        )

    async def roles_aid(self, request: web.Request) -> web.Response:
        return await self._card(
            ("aid", "roles"),
            lambda: aids.role_reference_png(self.engine.player_catalog),
        )

    async def species_aid(self, request: web.Request) -> web.Response:
        number = _int(request.match_info["number"])
        if number is None or not 1 <= number <= aids.SPECIES_FACE_COUNT:
            raise web.HTTPNotFound()
        return await self._card(
            ("aid", "species", number),
            lambda: aids.species_face_png(number),
        )

    async def team_aid(self, request: web.Request) -> web.Response:
        """One of a team's printed cards, in the face asked for: the
        front, or the advanced face (`player_cards.render_player_card_back`)."""
        try:
            team = Team(request.match_info["team"])
        except ValueError:
            raise web.HTTPNotFound()
        catalog = self.engine.player_catalog
        card_id = request.match_info["card_id"]
        roster = catalog.teams.get(team)
        if roster is None or card_id not in {
            player.player_id for player in roster.players
        }:
            raise web.HTTPNotFound()
        face = request.query.get("face", aids.FACE_FRONT)
        if face not in aids.FACE_WORDS:
            raise web.HTTPBadRequest(text="A face is front or advanced.")
        advanced = face == aids.FACE_ADVANCED
        return await self._card(
            ("aid", "team", team, card_id, advanced),
            lambda: pictures.player_card_png(
                catalog, card_id, team, advanced=advanced, size="full",
            ),
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
            f"PBW{game.game_number} - "
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
        reader: Optional[int] = None,
        coach: Optional[Coach] = None,
    ) -> dict:
        journal = self.journal(game.game_id)
        chat = self.chats.chat(game.game_id)
        match = self._match(game)
        # The one reading of what the match waits on: a question for
        # somebody, or a step the bot owes (`d12ball.prompts.pending`).
        waiting = None if match is None else pending(self.engine, game, match)
        prompt = waiting if isinstance(waiting, PendingPrompt) else None
        owed = waiting is not None and prompt is None
        return {
            **self._prompt_state(game, match, prompt, viewer, journal),
            "game": {
                "id": game.game_id,
                "number": game.game_number,
                "name": game.game_name,
                "status": GameStatus(game.status).value,
                "abandoned": game.abandoned,
                "tutorial": game.tutorial,
                # The board PNG's own title, which is how the bot
                # names a game everywhere it pins one.
                "title": self._title(game, match),
                # What the top bar puts beside the room's number: the
                # room's own name, or the two coaches and their teams.
                "topic": game.game_name or self._title(
                    game, None,
                ).split(" - ", 1)[-1],
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
            "owed": owed,
            # Before kickoff the prompt's place is the table's -- unless
            # the game was abandoned there, which leaves no table.
            "table": (
                self._table(game, coach)
                if game.match_state is None and not game.is_finished
                else None
            ),
            "rematch": self._rematch_of(game),
            # The reading room's aids for this game, each chosen by the
            # model (`webapp/aids.py`), with the three answers beside
            # them so the page decides none.
            "aids": aids.for_game(self.engine, game, viewer.player_number),
            # The dice just rolled, drawn in the question box until the
            # next thing happens ("The dice", docs/design/web-app.md);
            # the log keeps the words.
            "roll": self._roll(game, journal),
            # The outcome beside them, large and first: the model's own
            # headline ("The outcome banner", docs/design/web-app.md).
            "outcome": self._outcome(game, match, journal),
            # Both cards face up once both are in, until the maneuver
            # is over (`present.reveal`): public once turned over.
            "reveal": reveal(self.engine, game, match),
            # The numbers beside the result once the game is over, and
            # the log as a file (`present.full_time`).
            "full_time": self._full_time(game, match),
            "entries": journal.since(since, game),
            "latest": journal.next_id - 1,
            "chat": [
                self._chat_line(game, message, reader)
                for message in chat.since(chat_since)
            ],
            "chat_latest": chat.latest,
        }

    def _prompt_state(
        self,
        game: D12BallGame,
        match: Optional[MatchState],
        prompt: Optional[PendingPrompt],
        viewer: Viewer,
        journal: Journal,
    ) -> dict:
        """
        The question, as the page is handed it -- read off
        `prompt.to_dict()`, the wire's own shape, which the controls
        are built from too (decision 3 of docs/web-app-next.md): the
        page is that format's consumer, not a second serialiser's.
        """
        if prompt is None:
            return {"prompt": None}
        wire = prompt.to_dict()
        controls = controls_for(
            self.engine, game, match, prompt, viewer, wire=wire,
        )
        owed = bool(controls) and still_to_answer(
            self.engine, game, match, prompt, viewer, wire=wire,
        )
        ask, footnote = split_footnote(
            self.engine, game, match, prompt, wire["ask"],
        )
        return {
            "prompt": {
                "kind": wire["kind"],
                "ask": render_text(game, ask),
                # The Spreadable reminder, said under the whistle rather
                # than under the title (`present.split_footnote`).
                "footnote": render_text(game, footnote) if footnote else None,
                # What the cog puts under the same kind, or null: the
                # same for a coach and an observer, since it is the
                # position's and holds nobody's hand.
                "picture": self._prompt_picture_url(
                    game, match, prompt, journal.board_version,
                ),
                "controls": controls,
                # What is lit on the board and why, and what is dark:
                # read off the controls just built, for the question
                # box's muted line.
                "lit": lit_line(
                    self.engine, game, match, prompt, viewer, controls,
                    wire=wire,
                ),
                # This viewer's to answer: offered controls, and not
                # only waiting on the other side with a card already
                # down (`present.still_to_answer`).
                "yours": owed,
                "state": _box_state(match, prompt, owed),
                # Who a `waiting` box is waiting on, by name, as the
                # record calls them (`present.waiting_on`).
                "waiting_on": waiting_on(
                    self.engine, game, match, prompt, viewer,
                ),
                # The maneuver pick's hands this viewer does not hold,
                # face down -- every one for an observer -- whether or
                # not that side has picked (`present.hand_table`).
                "hand": hand_table(
                    self.engine, game, match, prompt, viewer, wire=wire,
                ),
                # The shootout's secret questions: whether each side
                # has answered, and nothing of what it answered
                # (`present.shootout_sides`) -- the same for everybody.
                "shootout": shootout_sides(
                    self.engine, game, match, prompt, wire=wire,
                ),
                # The maneuver pick's rank reference: the cards' shared
                # back at the game's tier, which carries the defeat
                # cycle, shown while the pointer is on the words under
                # the hand (the author, 2026-09-27). The fuller
                # reference, the hexagon, is in the Rules tab.
                "reference": (
                    f"/api/game/{game.game_id}/maneuver-back.png?size=full"
                    if prompt.kind is PromptKind.MANEUVER_ACTION else None
                ),
            },
        }

    def _outcome(
        self,
        game: D12BallGame,
        match: Optional[MatchState],
        journal: Journal,
    ) -> Optional[dict]:
        """
        The latest result's headlines, as the question box puts them
        up: the model's own words rendered at this door, one after the
        other with a dot between them as the canvas joins them ("STEAL
        · TURNOVER"), in the colour of the first that is a side's, with
        the first line under one and the first arithmetic. Joining is
        presentation; the page words none of it.
        """
        headlines = journal.showing_outcomes
        if not headlines or match is None:
            return None
        side = next(
            (one["side"] for one in headlines if one.get("side")), None,
        )

        def first(key: str) -> str:
            return next(
                (one[key] for one in headlines if one.get(key)), "",
            )

        return {
            "headline": " · ".join(
                render_text(game, one["text"]) for one in headlines
            ),
            "under": render_text(game, first("under")),
            "working": render_text(game, first("working")),
            "colour": (
                None if side is None
                else side_colour(match, TeamSide(side))
            ),
        }

    def _full_time(
        self, game: D12BallGame, match: Optional[MatchState],
    ) -> Optional[dict]:
        block = full_time(game, match)
        if block is None:
            return None
        return {
            **block,
            "home_colour": side_colour(match, TeamSide.HOME),
            "visiting_colour": side_colour(match, TeamSide.VISITING),
            "log": f"/api/room/{game.game_id}/log.txt",
        }

    def _roll(self, game: D12BallGame, journal: Journal) -> Optional[dict]:
        entry = (
            None if journal.showing_roll is None
            else journal.entry(journal.showing_roll)
        )
        if entry is None:
            return None
        return {
            "shape": pictures.dice_shape(entry.detail),
            "url": (
                f"/api/room/{game.game_id}/detail/{entry.id}.png"
                f"?at={entry.at}"
            ),
        }

    def _prompt_picture_url(
        self,
        game: D12BallGame,
        match: MatchState,
        prompt: PendingPrompt,
        version: int,
    ) -> Optional[str]:
        picture = prompt_picture_key(prompt, match)
        if picture is None:
            return None
        return (
            f"/api/room/{game.game_id}/prompt.png"
            f"?v={version}&p={picture}"
        )

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
        admin = self.rooms.is_admin(
            game.game_id, None if coach is None else coach.id,
        )
        if number is None:
            role = "observer"
        elif number == game.home_player_number:
            role = "home"
        elif number == game.visiting_player_number:
            role = "visiting"
        else:
            role = "coach"
        seated = number is not None
        return {
            "seats": [self._seat(game, one, number) for one in (1, 2)],
            "observers": self._observers(game),
            # The sideline: who is watching, by the name each was last
            # seen under (webapp/rooms.py) -- the reader marked.
            "watching": [
                {
                    "name": self.names.name_of(one)
                    or self.rooms.room(game.game_id).names.get(one)
                    or "A guest",
                    "yours": coach is not None and one == coach.id,
                }
                for one in sorted(self._watching(game))
            ],
            # The seats the AI may be put in right now: `seat_ai` asked
            # of a copy, so the Dinky chip is offered off the reading
            # the press is judged by -- and only to somebody seated,
            # who is who may ask (`seat`).
            "ai_seats": [
                one for one in (1, 2) if seated and _ai_may_sit(game, one)
            ],
            "admin": admin,
            "role": role,
            # The menu under the top bar's pill (the author,
            # 2026-09-27): whether "Leave your seat" stands
            # (`vacate_seat` asked of a copy), and the seats an admin
            # who is watching may take over (`take_over_seat` asked of
            # one) -- a seat somebody or the AI holds, since a free
            # one is simply taken.
            "may_leave": _may_leave(game, coach),
            "take_over": [
                one for one in (1, 2)
                if admin
                and not seated
                and not game.seat_is_free(one)
                and _may_take_over(game, one, coach)
            ],
            "may_abandon": (
                seated
                and game.match_state is not None
                and not game.is_finished
            ),
        }

    def _watching(self, game: D12BallGame) -> set[int]:
        """Everybody who has been in the room without holding a seat."""
        seated = {game.player_1_id, game.player_2_id} - {None}
        return self.rooms.room(game.game_id).seen - seated

    def _observers(self, game: D12BallGame) -> int:
        """How many have been in the room without holding a seat."""
        return len(self._watching(game))

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
            open_now = name in open_settings
            # A value `configure` would refuse is dark, with the
            # record's own sentence as the setting's note -- asked of a
            # copy, the way the whistle's note is (`_configure_refusal`).
            refusals = {
                one: _configure_refusal(game, name, one)
                for one, _ in choices
                if one != value and open_now
            }
            toggle = (
                _configure_refusal(game, name, None)
                if isinstance(value, bool) and open_now
                else None
            )
            notes = [one for one in (*refusals.values(), toggle) if one]
            return {
                "name": name,
                "label": label,
                "value": value,
                "choices": [
                    {
                        "value": one,
                        "label": text,
                        "open": refusals.get(one) is None,
                    }
                    for one, text in choices
                ],
                "may_change": seated and open_now,
                "toggle_open": toggle is None,
                "note": notes[0] if notes else None,
            }

        mode = setting(
            "mode", "Mode", GameMode(game.mode).value,
            [(one.value, GAME_MODE_NAMES[one]) for one in GameMode],
        )
        # What each mode plays, in the model's words (`describe_game_mode`,
        # the same sentence the Discord setup screens use): on each pill,
        # and under the row for the mode the game is in, unless the
        # record has a refusal to say there instead.
        for choice in mode["choices"]:
            choice["definition"] = describe_game_mode(
                game, GameMode(choice["value"]),
            )
        mode["definition"] = describe_game_mode(game)
        settings = [
            mode,
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
        # What a setting *is*, in the model's words (`describe_game_mode`,
        # `SETTING_DEFINITIONS`) -- beside the record's refusal, which is
        # `note`, never instead of it.
        for one in settings:
            one.setdefault("definition", SETTING_DEFINITIONS.get(one["name"]))
            # What the change would take away, asked before the press
            # (`configure_warning`): the page confirms it first.
            one["warning"] = configure_warning(game, one["name"])

        owed_by = game.home_choice_owed_by
        rail = None if owed_by is None else game.home_choice_rail(owed_by)
        return {
            "lobby": game.in_lobby,
            # Whether a move on the table is this reader's: the gold
            # edge on the question box, and on the room's card at the
            # front door.
            "yours": self._table_moves(game, coach),
            "settings": settings,
            "seats": [
                self._table_seat(
                    game, number, number in held,
                    picks=number in pick_seats(game, held),
                )
                for number in (1, 2)
            ],
            "start": {
                "owed": game.in_lobby,
                "may": seated and game.in_lobby,
                # Why the whistle is grey, in the record's own sentence.
                "refusal": _start_refusal(game),
            },
            "coin": {
                "owed": game.coin_is_owed,
                "may": seated and game.coin_is_owed,
                # The bot's own gold coin, both faces (the emoji the cog
                # uploads), for the page to draw rather than redraw.
                "faces": {
                    face: f"/emoji/3_gold_{face}.png"
                    for face in ("fortune", "doom")
                },
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
                        # Which end of the miniature field the choice
                        # is: the goal that side defends on the board.
                        "end": DEFENDED_ENDS[choice.value],
                    }
                    for choice in HomeChoice
                ],
                "board_size": game.board_size,
            },
            "may_close": self._may_close(game, coach),
            "close_asks": others_seated(game, coach),
        }

    def _idle(self, game: D12BallGame) -> bool:
        """Whether nobody has had this room open for `OPEN_ROOM_IDLE`:
        it stays in its coaches' own list, where its card can close it,
        and leaves everybody else's Open rooms."""
        seen = self._looked_at.get(game.game_id, self._started)
        return self.clock() - seen > OPEN_ROOM_IDLE

    def _may_close(self, game: D12BallGame, coach: Optional[Coach]) -> bool:
        """Whether this reader is offered "Close this room", on the
        table and on the room's card: somebody seated or the admin, in
        a game still in setup -- `close_room`'s gate, and
        `discard_game`'s refusal is the service's."""
        if coach is None or game.status != GameStatus.SETUP:
            return False
        return seat_of(game, coach.id) is not None or self.rooms.is_admin(
            game.game_id, coach.id,
        )

    def _table_moves(self, game: D12BallGame, coach: Optional[Coach]) -> bool:
        """
        Whether something on the table waits on this reader: Start once
        the record would take it, the coin, the choice of ends, or a
        team for a seat of theirs that has none and is offered one --
        every part the record's own reading (`start_lobby` asked of a
        copy, `coin_is_owed`, `home_choice_owed_by`, `teams_open_to`).
        """
        held = seats_held(game, None if coach is None else coach.id)
        if not held or game.is_finished or game.match_state is not None:
            return False
        if game.in_lobby and _start_refusal(game) is None:
            return True
        if game.coin_is_owed or game.home_choice_owed_by in held:
            return True
        # A team still owed by a side this reader plays -- not the AI's,
        # which the AI draws for itself if nobody picks it.
        return any(
            self._coach(game, number)["team"] is None
            and not game.ai_holds(number)
            and game.teams_open_to(number)
            for number in pick_seats(game, held)
        )

    def _table_seat(
        self, game: D12BallGame, number: int, yours: bool, *, picks: bool,
    ) -> dict:
        """
        One seat at the table: who holds it, its team, and while team
        selection is open the two rows of swatches -- every seat's, so
        each coach sees the other's too. `offered` is the record's
        `teams_open_to` for the seat (a pair greyed where it says so),
        `open` is whether this reader may press it (a seat they pick
        for, `pick_seats`: their own, the AI's, a game for one's second),
        and `picked` the seat's own team. The AI's seat also says who
        picks when nobody has (`picks_itself`: the AI, at Start).
        """
        seat = self._seat(game, number, number if yours else None)
        coach = self._coach(game, number)
        offered = set(game.teams_open_to(number))
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
                    "offered": team in offered,
                    "open": picks and team in offered,
                    "picked": coach["team_key"] == team.value,
                }
                for row, teams in enumerate((COLOR_TEAMS, SPECIES_TEAMS))
                for team in teams
            ] if offered else [],
            # A room's AI draws its own team at Start where nobody has
            # picked one for it (`GameService.start_lobby`).
            picks_itself=(
                game.ai_holds(number)
                and coach["team"] is None
                and game.in_lobby
                and game.picks_teams_in_lobby
            ),
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

    def _chat_line(
        self, game: D12BallGame, message, reader: Optional[int],
    ) -> dict:
        """
        One chat message as a page draws it: the name it was posted
        under, and the colour of the team the poster's seat holds now
        -- `None` for somebody seated in no seat, or before a team is
        picked, which the page draws plain. `yours` is whether the
        reader posted it. The text is exactly what was typed; the page
        sets it as text, never as markup or tokens.
        """
        seat = seat_of(game, message.coach_id)
        return {
            "id": message.id,
            "name": message.name,
            "text": message.text,
            "at": message.at,
            "yours": reader is not None and message.coach_id == reader,
            "colour": None if seat is None else self._coach(game, seat)["colour"],
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


def others_seated(game: D12BallGame, coach: Optional[Coach]) -> bool:
    """Whether a person other than this reader holds a seat -- the AI
    is nobody to warn, and neither is a test game's one coach in both
    seats. What decides if closing the room asks first (the author,
    2026-09-26)."""
    reader = None if coach is None else coach.id
    return any(
        held is not None and held != reader and not game.ai_holds(number)
        for number, held in ((1, game.player_1_id), (2, game.player_2_id))
    )


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


def pick_seats(game: D12BallGame, held: list[int]) -> set[int]:
    """
    The seats a reader holding `held` picks a team for: their own; the
    AI's, where they are seated (the author, 2026-09-26: a seated coach
    may pick Dinky's team, and Dinky draws its own at Start if nobody
    does); and, in a game for one -- a test game, the tutorial -- the
    second seat too, which that one coach answers for. Who may press is
    this frontend's; whether the pick stands is still the record's
    (`pick_team`).
    """
    if not held:
        return set()
    seats = set(held)
    seats.update(number for number in (1, 2) if game.ai_holds(number))
    if (game.test_game or game.tutorial) and 1 in held:
        seats.add(2)
    return seats


def seats_held_by(game: D12BallGame) -> set[int]:
    """The people seated in a game."""
    return {game.player_1_id, game.player_2_id} - {None}


def room_status(game: D12BallGame) -> str:
    """Where a room stands, as the front door sorts it: the lobby, the
    rest of setup, the game, or finished -- finished first, since a
    lobby abandoned before it started is over, not waiting."""
    if game.in_lobby and not game.is_finished:
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


def _start_refusal(game: D12BallGame) -> Optional[str]:
    """
    What Start would be refused with right now, or `None`: the record's
    own `start_lobby`, asked of a copy so nothing is changed. The
    whistle is grey with this sentence under it, where the Discord
    lobby answers the press with the same sentence -- one rule, read
    before the press instead of after it.
    """
    if not game.in_lobby:
        return None
    try:
        copy.deepcopy(game).start_lobby()
    except RuleRefusal as refusal:
        return str(refusal)
    return None


def _configure_refusal(
    game: D12BallGame, setting: str, value: object,
) -> Optional[str]:
    """What `configure(setting, value)` would be refused with now, or
    `None`: the record's own answer, asked of a copy so nothing is
    changed -- a setting's note on the table, as `_start_refusal` is
    the whistle's."""
    try:
        copy.deepcopy(game).configure(setting, value)
    except RuleRefusal as refusal:
        return str(refusal)
    except (TypeError, ValueError):
        return None
    return None


def _may_leave(game: D12BallGame, coach: Optional[Coach]) -> bool:
    """Whether `vacate_seat` would stand for this reader now, asked of
    a copy -- somebody seated, in a game not over, and never a test
    game's one coach once it has started."""
    if coach is None or game.is_finished or seat_of(game, coach.id) is None:
        return False
    try:
        copy.deepcopy(game).vacate_seat(coach.id)
    except RuleRefusal:
        return False
    return True


def _may_take_over(
    game: D12BallGame, seat: int, coach: Optional[Coach],
) -> bool:
    """Whether `take_over_seat(seat)` would stand for this reader now,
    asked of a copy, in a game not over."""
    if coach is None or game.is_finished:
        return False
    try:
        copy.deepcopy(game).take_over_seat(seat, coach.id, coach.name)
    except RuleRefusal:
        return False
    return True


def _ai_may_sit(game: D12BallGame, seat: int) -> bool:
    """Whether `seat_ai(seat)` would stand now, asked of a copy."""
    try:
        copy.deepcopy(game).seat_ai(seat)
    except RuleRefusal:
        return False
    return True


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


def _box_state(
    match: MatchState, prompt: PendingPrompt, yours: bool,
) -> str:
    """
    Which of the question box's four tags this viewer is shown
    ("The question box", docs/design/web-app.md): `full_time` for the
    finished game, `now` for a question nobody in particular is asked
    -- a note, or a roll either coach may take -- and otherwise
    `yours` where this viewer was offered the controls or `waiting`
    where they were not.

    **It reads whose question it is and decides nothing**:
    `asked_sides` is the one reading, the one the service answers an
    AI side by, and `yours` is `controls_for`'s own answer over it.
    """
    if prompt.kind is PromptKind.GAME_OVER:
        return "full_time"
    if not asked_sides(match, prompt):
        return "now"
    return "yours" if yours else "waiting"


def _wire(kind, value, refusal: str):
    """A value off the wire, as the model's type -- or a 400, since a
    value the page was never offered is a bug in the page."""
    try:
        return kind(value)
    except (TypeError, ValueError):
        raise web.HTTPBadRequest(text=refusal)


def _since(request: web.Request) -> int:
    return _int(request.query.get("since")) or 0


def _cursors(request: web.Request) -> dict:
    """
    What a page has already drawn, and who is reading it: the
    journal's `since`, the chat's `chat_since`, and the cookie's id
    that marks a chat line as the reader's own. Every answer that
    hands a page its state reads all three, or a page that acted would
    be handed the whole chat again.
    """
    reader = identity.coach_for(request)
    return {
        "since": _since(request),
        "chat_since": _int(request.query.get("chat_since")) or 0,
        "reader": None if reader is None else reader.id,
    }


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
    chats: Optional[Chats] = None,
    journals: Optional[Journals] = None,
    names: Optional[Names] = None,
) -> WebApp:
    """Start the server over `service` on this process's event loop."""
    app = WebApp(
        service,
        locks,
        rooms=rooms,
        chats=chats,
        journals=journals,
        names=names,
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
    own batching (`WEB_BATCHING` -- the default but for the walk-in;
    Discord's economy is not the web's), and a save that writes
    `games_file` and nothing else.

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
        batching=WEB_BATCHING,
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
    chat_file: Path = WEB_CHAT_FILE,
    journal_file: Path = WEB_JOURNAL_FILE,
    names_file: Path = WEB_NAMES_FILE,
    secret_file: Path = keys.WEB_SECRET_FILE,
) -> None:
    """Run the web app over `games_file` (its rooms over `rooms_file`,
    its chat over `chat_file`, its journal over `journal_file`, the
    names in use over `names_file`, and the secret in `secret_file`
    where the environment names none) until cancelled. The secret
    first: the names file is written under its fingerprint."""
    keys.keep_secret_in(secret_file)
    service = build_service(games_file)
    LOGGER.info(
        "Loaded %d web game(s) from %s.", len(service.games), games_file,
    )
    rooms = Rooms.load(rooms_file, service.games)
    chats = Chats.load(chat_file, service.games)
    journals = Journals.load(journal_file, service.games)
    names = Names.load(names_file)
    app = await start_web_app(
        service, GameLocks(), rooms=rooms, chats=chats, journals=journals,
        names=names,
    )
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
