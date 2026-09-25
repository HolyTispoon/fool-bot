"""
The web frontend's door: an asyncio server over the same
`GameService` the bot plays through.

**It runs inside the bot's process, on the bot's event loop**
(decision 5 of docs/web-app.md). `gamesaves/d12ball/storage.py`
rewrites the whole save file on every call and reads it once at
startup, so a second process would overwrite the first's file with a
stale copy of every game; one process over one `games` dict is what
makes two frontends possible at all, and `gamelocks.GameLocks` is
what keeps their answers in order.

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
played from two sides, and one of them may be on Discord: the journal
below is fed by every result the service produces, through
`GameService.listeners`, so a coach watching a web page sees the
other coach's turn as it happens.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional

from aiohttp import web

from d12ball.components import MatchState
from d12ball.engine import RulesEngine
from d12ball.formatting import coach_name, format_player_with_team_name
from d12ball.game import D12BallGame, GameStatus, team_display_name
from d12ball.prompts import Action, PendingPrompt, pending
from d12ball.render import TEAM_COLORS, render_match_image
from gamelocks import GameLocks
from gamesaves.d12ball.service import GameResult, GameService
from webapp import keys
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

#: The environment this reads. `FOOLBOT_WEB_PORT` is the switch: with
#: none set, no server is started and the bot is exactly what it was.
PORT_VARIABLE = "FOOLBOT_WEB_PORT"
HOST_VARIABLE = "FOOLBOT_WEB_HOST"


@dataclass
class Entry:
    """One thing that was said, as the journal keeps it."""

    id: int
    lines: tuple[str, ...]
    #: The position the frontend stopped to draw, where it did.
    board: Optional[dict] = None
    new_play: bool = False

    def to_dict(self, game: D12BallGame) -> dict:
        return {
            "id": self.id,
            "lines": [render_text(game, line) for line in self.lines],
            "board": self.board is not None,
            "new_play": self.new_play,
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

    def since(self, entry_id: int, game: D12BallGame) -> list[dict]:
        return [
            entry.to_dict(game)
            for entry in self.entries
            if entry.id > entry_id
        ]

    def board_for(self, entry_id: int) -> Optional[dict]:
        for entry in self.entries:
            if entry.id == entry_id:
                return entry.board
        return None


class WebApp:
    """
    The aiohttp application, and the state one process keeps for it.

    It owns nothing about the game: the engine, the games and the
    service are the bot's own, handed in. What is its own is what a
    frontend's is -- who is reading a page, what has been said, and
    the pictures it has drawn.
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
        self._boards: dict[tuple, bytes] = {}
        self._runner: Optional[web.AppRunner] = None
        self.app = web.Application()
        self.app.add_routes(
            [
                web.get("/", self.index),
                web.get("/game/{game_id}", self.page),
                web.get("/api/game/{game_id}", self.state),
                web.post("/api/game/{game_id}/action", self.act),
                web.post("/api/game/{game_id}/resume", self.resume),
                web.get("/api/game/{game_id}/board.png", self.board),
                web.static("/static", STATIC),
            ],
        )

    # -- The bot's side ----------------------------------------------

    @property
    def engine(self) -> RulesEngine:
        return self.service.engine

    def watch(self) -> None:
        """
        Listen to every result the service produces, from either
        frontend. Without this a web page would see its own turns and
        none of the ones taken on Discord.
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
                "D12 Ball. A game is opened with its own link -- ask the "
                "bot for yours with /d12ball web_link in its channel."
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

    def _render_board(self, game: D12BallGame, match: MatchState) -> bytes:
        """Pillow, in a worker thread: the same picture the bot pins,
        off the same renderer."""
        period = _period(match)
        title = (
            f"PBD{game.game_number} - "
            f"{format_player_with_team_name(game, game.home_player_number)}"
            f" vs. "
            f"{format_player_with_team_name(game, game.visiting_player_number)}"
            f", {period}"
        )
        return render_match_image(
            match,
            self.engine.player_catalog,
            title=title,
            species_icons=self.engine.species_abilities_apply(game),
            cyborg_ids=self.engine.cyborg_condition_ids(game, match),
            card_skills=self.engine.card_skills(game, match),
        ).getvalue()

    # -- What a page is handed ---------------------------------------

    def _state(
        self, game: D12BallGame, viewer: Viewer, *, since: int = 0,
    ) -> dict:
        journal = self.journal(game.game_id)
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
            "entries": journal.since(since, game),
            "latest": journal.next_id - 1,
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
            "colour": None if team is None else TEAM_COLORS[team],
            "side": side,
        }


def _period(match: MatchState) -> str:
    """The half a coach reads, worded as the board's own title words
    it."""
    return (
        "First Half"
        if match.scoreboard.period.value == "first_half"
        else "Second Half"
    )


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


def configured_port() -> Optional[int]:
    """The port the environment asks for, or `None` -- which is the
    switch: with none set, no server is started."""
    return _int(os.environ.get(PORT_VARIABLE, "").strip() or None)


async def start_web_app(
    service: GameService,
    locks: GameLocks,
    *,
    port: Optional[int] = None,
    host: Optional[str] = None,
) -> Optional[WebApp]:
    """
    Start the server on this process's event loop, or answer `None`
    where the environment has not asked for one.

    The service and the locks are the bot's own: one `GameService`
    over one `games` dict, and one lock per game shared by both
    frontends (decision 5 of docs/web-app.md).
    """
    port = port if port is not None else configured_port()
    if port is None:
        return None
    app = WebApp(
        service,
        locks,
        host=host or os.environ.get(HOST_VARIABLE, "0.0.0.0"),
        port=port,
    )
    app.watch()
    await app.start()
    return app
