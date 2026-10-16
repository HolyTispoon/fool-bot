"""
The upload queue: what the publisher's record says, put into the bucket
off the click's path (docs/pbd-site.md, decision 9;
docs/design/pbd-site.md, "The queue").

A change is a flag, not a payload. The caller changes the record --
`PublishRecord`, the source -- and says which game changed, handing over
the bytes of any board it named; the queue builds the JSON from the
record when it sends, so a newer change replaces any not yet sent and a
burst of three is one upload. Per game:

- **One send in flight.** A change during a send is sent after it.
- **The order is the page's guarantee**: every board the JSON names that
  is not up yet, then `history.json`, then `live.json`, so a poll that
  lands between two puts never names an object that is not there. A
  failed put stops the send before anything that would name it.
- **A board goes up once**: the record's `uploaded` says what is there.
- **A board nothing names is deleted** once the `live.json` that
  replaced it is up -- the board the game has moved past, unless the
  history keeps it as the board a turn ended on ("What it costs").
- **The JSON goes up only when it changed** from what this process last
  put, so an unchanged history is not written on every action.

`index.json` and `archive.json` have one queue of their own, rebuilt from
the games and the record when sent: every game changes them, and two
games' sends finishing out of order could otherwise put back the older
list.

Nothing raises out of it. A failed call is a WARNING and is retried with
the next change; a run of failures -- `FAILURE_RUN` in a row, or a run
older than `FAILURE_WINDOW` -- is one ERROR, which reaches #logs, and is
said again only after a success has reset the run.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from typing import TYPE_CHECKING, Callable, Iterable, Mapping, Optional

from codex.components import MatchState
from codex.game import GameStatus
from cogs.codex_publish import keys, shapes
from cogs.codex_publish.record import PublishedGame, PublishRecord

if TYPE_CHECKING:
    from botkit.objectstore import ObjectStore
    from codex.game import CodexGame

LOGGER = logging.getLogger(__name__)

#: Failures in a row before the run is an ERROR.
FAILURE_RUN = 10
#: Or how long a run of failures may last, in seconds, before it is one.
FAILURE_WINDOW = 300.0

#: The statuses each list holds; a lobby is on neither (`shapes.on_site`).
BEING_PLAYED = (GameStatus.PLAYING,)
ENDED = (GameStatus.FINISHED, GameStatus.ABANDONED)


def encode(document: dict) -> bytes:
    return json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def named_boards(published: Optional[PublishedGame]) -> list[str]:
    """Every board key the game's JSON names: the current board first,
    then each the history keeps, each once."""
    if published is None:
        return []
    found = [published.board] if published.board else []
    for entry in published.history:
        board = entry.get("board")
        if isinstance(board, str) and board not in found:
            found.append(board)
    return found


class PublishQueue:
    """
    The publisher's sends. `games` hands back the bot's games by
    `game_id` -- the record the cog plays from, read at send time.
    `clock` is `time.monotonic` but for the tests.
    """

    def __init__(self, store: "ObjectStore", record: PublishRecord,
                 games: Callable[[], Mapping[str, "CodexGame"]], *,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.store = store
        self.record = record
        self._games = games
        self._clock = clock
        self._closed = False
        # Per game: the boards handed over and not yet sent, by key; the
        # games with a change not yet sent; the one send in flight.
        self._boards: dict[str, dict[str, bytes]] = {}
        self._changed: set[str] = set()
        self._tasks: dict[str, asyncio.Task] = {}
        # The lists' own queue.
        self._lists_changed = False
        self._lists_task: Optional[asyncio.Task] = None
        # What this process last put under each JSON key, by its digest.
        self._sent: dict[str, str] = {}
        # A match read off its record once per saved state: the record's
        # dict is replaced on every save, so holding it is the check.
        self._matches: dict[str, tuple[dict, Optional[MatchState]]] = {}
        # The run of failures.
        self._failures = 0
        self._run_started: Optional[float] = None
        self._alarmed = False

    # -- What the cog calls ----------------------------------------------

    def game_changed(self, game_id: str, boards: Iterable[bytes] = ()) -> None:
        """
        The record for `game_id` changed; send it. `boards` are the bytes
        of every board the change named -- the current one, and a
        finished turn's -- since the record keeps only their keys.
        """
        if self._closed:
            return
        held = self._boards.setdefault(game_id, {})
        for board in boards:
            held[keys.board_key(game_id, board)] = board
        self._changed.add(game_id)
        if game_id not in self._tasks:
            self._tasks[game_id] = asyncio.create_task(self._run_game(game_id))

    def lists_changed(self) -> None:
        """A game joined, left or moved between the two lists, or what a
        list says of it changed; rebuild both."""
        if self._closed:
            return
        self._lists_changed = True
        if self._lists_task is None:
            self._lists_task = asyncio.create_task(self._run_lists())

    async def drain(self) -> None:
        """Wait until nothing is waiting to be sent or in flight."""
        while True:
            tasks = [*self._tasks.values(), *([self._lists_task] if self._lists_task else [])]
            if not tasks:
                return
            await asyncio.gather(*tasks, return_exceptions=True)

    async def close(self) -> None:
        """Stop: nothing new is taken, and what is in flight is cancelled.
        A put already handed to its thread finishes there; the record
        says only what was confirmed, so the next start sends the rest."""
        self._closed = True
        tasks = [*self._tasks.values(), *([self._lists_task] if self._lists_task else [])]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    # -- A game ------------------------------------------------------------

    async def _run_game(self, game_id: str) -> None:
        try:
            while game_id in self._changed and not self._closed:
                self._changed.discard(game_id)
                boards = self._boards.pop(game_id, {})
                if not await self._send_game(game_id, boards):
                    # Kept for the next change, which sends everything again;
                    # a board handed over since is the same bytes by its key.
                    held = self._boards.setdefault(game_id, {})
                    for key, board in boards.items():
                        held.setdefault(key, board)
        except Exception:  # pragma: no cover - the queue's own bug
            LOGGER.exception("Publishing Codex game %s failed.", game_id)
        finally:
            self._tasks.pop(game_id, None)

    async def _send_game(self, game_id: str, boards: dict[str, bytes]) -> bool:
        """Put the game as the record has it now. False where it stopped
        short, so its boards are kept for the next change."""
        game = self._games().get(game_id)
        published = self.record.games.get(game_id)
        if game is None or published is None or not shapes.on_site(game):
            return True
        match = self._match(game)
        # Everything this send puts is built before its first await, so a
        # change made while it is in flight goes in the next send whole.
        history = encode(shapes.history(game, published))
        live = encode(shapes.live(game, match, published))
        named = named_boards(published)
        uploaded = published.uploaded
        saved = list(uploaded)

        try:
            for key in named:
                if key in uploaded:
                    continue
                board = boards.get(key)
                if board is None:
                    if key == published.board:
                        LOGGER.warning(
                            "Codex game %s's current board is not up and was not handed over; "
                            "the site waits for the next change.", game_id)
                        return False
                    LOGGER.warning(
                        "Codex game %s's history names a board that is not up and was not "
                        "handed over: %s", game_id, key)
                    continue
                if not await self._put(key, board):
                    return False
                uploaded.append(key)
            if not await self._put_json(keys.history_key(game_id), history):
                return False
            if not await self._put_json(keys.live_key(game_id), live):
                return False
            # What a change made in the meantime names is kept too: its
            # send is next, and would only put it back.
            keep = set(named) | set(named_boards(self.record.games.get(game_id)))
            for key in [key for key in uploaded if key not in keep]:
                if await self._delete(key):
                    uploaded.remove(key)
            return True
        finally:
            if uploaded != saved:
                self.record.save()

    def _match(self, game: "CodexGame") -> Optional[MatchState]:
        state = game.match_state
        if state is None:
            return None
        cached = self._matches.get(game.game_id)
        if cached is not None and cached[0] is state:
            return cached[1]
        try:
            match = MatchState.from_dict(state)
        except Exception:
            LOGGER.warning("Codex game %s's match could not be read for the site.", game.game_id,
                           exc_info=True)
            match = None
        self._matches[game.game_id] = (state, match)
        return match

    # -- The lists ---------------------------------------------------------

    async def _run_lists(self) -> None:
        try:
            while self._lists_changed and not self._closed:
                self._lists_changed = False
                index, archive = self.lists()
                await self._put_json(keys.INDEX_KEY, encode(index))
                await self._put_json(keys.ARCHIVE_KEY, encode(archive))
        except Exception:  # pragma: no cover - the queue's own bug
            LOGGER.exception("Publishing the Codex games' lists failed.")
        finally:
            self._lists_task = None

    def lists(self) -> tuple[dict, dict]:
        """`index.json` and `archive.json` as the games and the record
        have them now: every game that started, by its status."""
        playing, ended = [], []
        games = self._games()
        for game_id in [game_id for game_id in self._matches if game_id not in games]:
            del self._matches[game_id]
        for game in games.values():
            if not shapes.on_site(game):
                continue
            published = self.record.games.get(game.game_id)
            updated = published.updated if published is not None else None
            if game.status in BEING_PLAYED:
                playing.append(shapes.index_entry(game, self._match(game), updated))
            elif game.status in ENDED:
                ended.append(shapes.archive_entry(game, self._match(game), updated))
        return shapes.index(playing), shapes.archive(ended)

    # -- The calls, and the run of failures --------------------------------

    async def _put_json(self, key: str, body: bytes) -> bool:
        digest = hashlib.sha256(body).hexdigest()
        if self._sent.get(key) == digest:
            return True
        if not await self._put(key, body):
            return False
        self._sent[key] = digest
        return True

    async def _put(self, key: str, body: bytes) -> bool:
        try:
            await self.store.put(key, body, keys.content_type(key), keys.cache_control(key))
        except Exception as error:
            self._failed("put", key, error)
            return False
        self._succeeded()
        return True

    async def _delete(self, key: str) -> bool:
        try:
            await self.store.delete(key)
        except Exception as error:
            self._failed("delete", key, error)
            return False
        self._succeeded()
        return True

    def _failed(self, operation: str, key: str, error: Exception) -> None:
        now = self._clock()
        if self._failures == 0:
            self._run_started = now
        self._failures += 1
        LOGGER.warning("Could not %s %s in the Codex games' bucket: %s: %s",
                       operation, key, type(error).__name__, error)
        if self._alarmed:
            return
        if self._failures >= FAILURE_RUN or now - self._run_started >= FAILURE_WINDOW:
            self._alarmed = True
            LOGGER.error(
                "The Codex games' web page is not being updated: %d calls to its bucket have "
                "failed in a row (the last: %s: %s). Check the CODEX_PUBLISH_* token and the "
                "bucket.", self._failures, type(error).__name__, error)

    def _succeeded(self) -> None:
        if self._alarmed:
            LOGGER.info("The Codex games' bucket is answering again after %d failures.",
                        self._failures)
        self._failures = 0
        self._run_started = None
        self._alarmed = False
