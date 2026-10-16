"""
The publisher: the Codex cog's second door out, beside Discord
(docs/pbd-site.md, step 3; docs/design/pbd-site.md, "The hooks").

The cog calls it from its own methods -- never from `BoardRefresher`,
which D12 Ball shares -- at the places a turn message's picture is made
or a game moves between the lists:

- `current`: the current turn's lines and board -- every action through
  the gate (`refresh_match_image`), and every turn message posted
  (`post_turn_message`), which hands over the bytes it posted;
- `turn_ended`: the ended turn kept as a history entry, with the bytes
  `roll_over` drew for its standing message;
- `previous_turn_back`: an undo to the previous turn, its entry dropped;
- `turn_undone`: an undo within the turn, its lines back to its head;
- `head_noted`: the turn's first lines, as the cog notes them;
- `game_over`: a game finished or abandoned, with its last board;
- `dropped`: games `/codex admin reset_channels` forgot;
- `start`: the startup publish, as a task off `cog_load`.

Each hook changes the publisher's record at once -- the lines are the
cog's at that moment, and some are gone a line later -- and leaves the
rest to the game's own task: drawing a board where the hook had none,
saving the record, and naming the game to the queue. **Nothing raises
out of a hook, and no hook awaits anything**, so publishing never fails
or slows a click, and spends no Discord request.

**The lines after a restart.** `Codex.turn_lines` is in memory, so a
restarted process has not seen the current turn's lines; where it then
says more of the turn -- an action, or `/codex resume`'s reset -- the
site's lines are the record's for that turn followed by what this
process has seen since, never the latter alone (`carried`), until the
turn ends. Nothing on Discord holds them, so the record is the one copy.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Callable, Iterable, Optional

from codex.components import MatchState
from codex.formatting import turn_heading
from codex.game import GameStatus
from cogs.codex_helpers import TOKEN_EMOJI
from cogs.codex_publish import keys, shapes
from cogs.codex_publish.queue import ENDED, PublishQueue
from cogs.codex_publish.record import PublishedGame, PublishRecord
from gamekit.storage import PROJECT_ROOT

if TYPE_CHECKING:
    from botkit.objectstore import ObjectStore
    from codex.game import CodexGame

LOGGER = logging.getLogger(__name__)

#: The glyphs' pictures, as the cog's emoji are drawn from them
#: (`TOKEN_EMOJI`'s files).
EMOJI_FOLDER = PROJECT_ROOT / "codex" / "images" / "emoji"


def now() -> str:
    """When a game last changed: ISO 8601 in UTC, to the second."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Publisher:
    """
    One per cog, over the cog's games, its turn's lines and its board
    renderer. `cog` is read for `games`, `turn_lines`, `turn_heads`,
    `service` and `render_match_png` and nothing else.
    """

    def __init__(self, cog, store: "ObjectStore", record: Optional[PublishRecord] = None, *,
                 clock: Callable[[], str] = now, queue: Optional[PublishQueue] = None) -> None:
        self.cog = cog
        self.record = record if record is not None else PublishRecord.load()
        self.queue = queue or PublishQueue(store, self.record, lambda: self.cog.games)
        self._clock = clock
        #: Per game, the turn's lines this process never saw, for the
        #: turn they belong to: everything the record had at startup.
        self.carried: dict[str, tuple[int, list[str]]] = {}
        #: Per game, what `carried` was when the turn's head was noted:
        #: what an undo to the turn's start goes back to.
        self.head_carried: dict[str, tuple[int, list[str]]] = {}
        # The boards handed over and not yet given to the queue, the
        # games owed a send, those whose board is still to be drawn, and
        # each game's one task.
        self._boards: dict[str, list[bytes]] = {}
        self._owed: set[str] = set()
        self._draw: set[str] = set()
        #: Per game, a count of the changes made: a board drawn for an
        #: older one is not the current board.
        self._changes: dict[str, int] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._starting: Optional[asyncio.Task] = None
        self._closed = False
        for game_id, published in self.record.games.items():
            if published.turn is not None:
                self.carried[game_id] = (published.turn, list(published.lines))
                self.head_carried[game_id] = (published.turn, list(published.head))

    # -- The lines -------------------------------------------------------

    def lines_of(self, game: "CodexGame", turn: int) -> list[str]:
        """
        Turn `turn`'s lines as the site shows them: what this process
        never saw of it (`carried`), then the cog's `turn_lines` -- or,
        where the cog has not seen the turn at all, the record's lines
        as they stand.
        """
        published = self.record.games.get(game.game_id)
        seen = self.cog.turn_lines.get(game.game_id)
        if seen is None:
            if published is not None and published.turn == turn:
                return list(published.lines)
            return []
        carried = self.carried.get(game.game_id)
        prefix = carried[1] if carried is not None and carried[0] == turn else []
        return [*prefix, *seen]

    def _new_turn(self, game_id: str) -> None:
        """The turn this process carried lines for is over."""
        self.carried.pop(game_id, None)
        self.head_carried.pop(game_id, None)

    # -- The hooks ---------------------------------------------------------

    def current(self, game: "CodexGame", match: Optional[MatchState] = None,
                board: Optional[bytes] = None) -> None:
        """The current turn as the turn message has it: its heading and
        lines now, and `board` -- the bytes posted -- or, where none is
        handed over, the board drawn by the game's task."""
        self._guarded(self._current, game, match, board)

    def _current(self, game: "CodexGame", match: Optional[MatchState], board: Optional[bytes]) -> None:
        if not shapes.on_site(game):
            return
        if match is None:
            match = self.cog.service.load(game)
        published = self.record.game(game.game_id)
        if published.turn is not None and match.turn > published.turn:
            # A turn ended with no `roll_over` -- `/codex resume` ran the
            # end of it -- so the turn as the record had it is its entry.
            self._keep_turn(published, published.turn, published.heading, list(published.lines),
                            published.board)
            self._new_turn(game.game_id)
        before = self._shown(published)
        published.turn = match.turn
        published.heading = turn_heading(match)
        published.lines = self.lines_of(game, match.turn)
        if board is not None:
            published.board = keys.board_key(game.game_id, board)
        if self._shown(published) != before or game.status is not GameStatus.PLAYING:
            published.updated = self._clock()
        if board is not None:
            self._owe(game.game_id, [board])
        else:
            self._owe(game.game_id, (), draw=True)

    @staticmethod
    def _shown(published: PublishedGame) -> tuple:
        """What the site shows of the current turn: a change to it is
        what moves the game's `updated`, and a post of the same board
        and lines -- **Show board** -- moves nothing."""
        return (published.turn, published.heading, list(published.lines), published.board)

    def turn_ended(self, game: "CodexGame", ended: MatchState, closing: Iterable[str],
                   board: bytes) -> None:
        """
        `roll_over`: the ended turn -- `ended`, the position its message
        stands on, seated as it was -- kept as a history entry with its
        lines, `closing` after them, and `board`, the bytes its standing
        message carries. Called before `turn_lines` becomes the next
        turn's; the next turn is made current by the post after it.
        """
        self._guarded(self._turn_ended, game, ended, list(closing), board)

    def _turn_ended(self, game: "CodexGame", ended: MatchState, closing: list[str],
                    board: bytes) -> None:
        if not shapes.on_site(game):
            return
        published = self.record.game(game.game_id)
        lines = [*self.lines_of(game, ended.turn), *closing]
        self._keep_turn(published, ended.turn, turn_heading(ended), lines,
                        keys.board_key(game.game_id, board))
        self._new_turn(game.game_id)
        # The next turn's, until the post after this makes it current:
        # nothing is sent between the two.
        published.turn = ended.turn + 1
        published.lines = []
        published.head = []
        self._owe(game.game_id, [board])

    def previous_turn_back(self, game: "CodexGame", restored: MatchState) -> None:
        """An undo to the previous turn, or of the previous turn's end:
        the restored turn's entry, and any after it, dropped from the
        history. The restored turn is made current by the post after."""
        self._guarded(self._previous_turn_back, game, restored)

    def _previous_turn_back(self, game: "CodexGame", restored: MatchState) -> None:
        published = self.record.games.get(game.game_id)
        if published is None:
            return
        kept = [entry for entry in published.history
                if not isinstance(entry.get("turn"), int) or entry["turn"] < restored.turn]
        if len(kept) != len(published.history):
            published.history = kept
            published.history_version += 1
        self._new_turn(game.game_id)
        published.turn = restored.turn
        published.lines = []
        published.head = list(self.cog.turn_heads.get(game.game_id, {}).get(restored.turn, []))

    def turn_undone(self, game: "CodexGame", turn: int) -> None:
        """An undo within turn `turn`: the cog's lines are its head and
        what the undo said, so what this process carries goes back to
        what it carried when the head was noted."""
        self._guarded(self._turn_undone, game, turn)

    def _turn_undone(self, game: "CodexGame", turn: int) -> None:
        head = self.head_carried.get(game.game_id)
        if head is not None and head[0] == turn:
            self.carried[game.game_id] = (turn, list(head[1]))
        else:
            self.carried.pop(game.game_id, None)

    def head_noted(self, game: "CodexGame", match: MatchState) -> None:
        """The cog noted the turn's first lines (`note_turn_head`)."""
        self._guarded(self._head_noted, game, match)

    def _head_noted(self, game: "CodexGame", match: MatchState) -> None:
        if not shapes.on_site(game):
            return
        carried = self.carried.get(game.game_id)
        prefix = list(carried[1]) if carried is not None and carried[0] == match.turn else []
        self.head_carried[game.game_id] = (match.turn, prefix)
        published = self.record.game(game.game_id)
        published.head = [*prefix, *self.cog.turn_lines.get(game.game_id, [])]

    def game_over(self, game: "CodexGame", match: Optional[MatchState] = None,
                  board: Optional[bytes] = None) -> None:
        """A game finished -- a fallen base, a concession -- or abandoned
        after its Start: its last lines and board current, and the game
        moved from `index.json` to `archive.json`. Called before the cog
        forgets the turn's lines."""
        self._guarded(self._current, game, match, board)

    def dropped(self, game_ids: Iterable[str]) -> None:
        """Games the bot no longer has (`/codex admin reset_channels`):
        off the record, and so off both lists, and then out of the bucket.
        Called after the cog has dropped them, since the lists are read
        off its games."""
        self._guarded(self._dropped, list(game_ids))

    def _dropped(self, game_ids: list[str]) -> None:
        boards = {}
        for game_id in game_ids:
            published = self.record.games.get(game_id)
            boards[game_id] = list(published.uploaded) if published is not None else []
            self.record.drop(game_id)
            self._new_turn(game_id)
            self._owed.discard(game_id)
            self._draw.discard(game_id)
            self._boards.pop(game_id, None)
            task = self._tasks.get(game_id)
            if task is not None:
                task.cancel()
        self.record.save()
        # Off both lists, then out of the bucket (the author, 2026-10-16).
        self.queue.games_dropped(boards)

    def _guarded(self, hook, *arguments) -> None:
        if self._closed:
            return
        try:
            hook(*arguments)
        except Exception:
            LOGGER.exception("Could not publish a change to a Codex game.")

    # -- The game's task -----------------------------------------------------

    def _owe(self, game_id: str, boards: Iterable[bytes], draw: bool = False) -> None:
        self._changes[game_id] = self._changes.get(game_id, 0) + 1
        self._boards.setdefault(game_id, []).extend(boards)
        if draw:
            self._draw.add(game_id)
        else:
            # The board handed over is the newest: nothing to draw.
            self._draw.discard(game_id)
        self._owed.add(game_id)
        if game_id not in self._tasks:
            self._tasks[game_id] = asyncio.create_task(self._run(game_id))

    async def _run(self, game_id: str) -> None:
        try:
            while game_id in self._owed and not self._closed:
                self._owed.discard(game_id)
                if game_id in self._draw:
                    self._draw.discard(game_id)
                    await self._draw_board(game_id)
                self.record.save()
                self.queue.game_changed(game_id, self._boards.pop(game_id, []))
                self.queue.lists_changed()
        except Exception:
            LOGGER.exception("Could not publish Codex game %s.", game_id)
        finally:
            self._tasks.pop(game_id, None)

    async def _draw_board(self, game_id: str) -> None:
        """The board as the gate draws it -- the same call, so usually
        the drawing the gate made already (`render_match_png`)."""
        game = self.cog.games.get(game_id)
        published = self.record.games.get(game_id)
        if game is None or published is None or not shapes.on_site(game):
            return
        change = self._changes.get(game_id)
        match = self.cog.service.load(game)
        board = await self.cog.render_match_png(game, match)
        if self._changes.get(game_id) != change:
            # A newer change came while this was drawn: its board -- the
            # one it handed over, or the one drawn for it next -- is the
            # current one.
            return
        key = keys.board_key(game_id, board)
        if key != published.board:
            published.board = key
            published.updated = self._clock()
        self._boards.setdefault(game_id, []).append(board)

    @staticmethod
    def _keep_turn(published: PublishedGame, turn: Optional[int], heading: Optional[str],
                   lines: list[str], board: Optional[str]) -> None:
        if turn is None:
            return
        published.history = [entry for entry in published.history if entry.get("turn") != turn]
        published.history.append({"turn": turn, "heading": heading, "lines": lines, "board": board})
        published.history_version += 1

    # -- Startup and shutdown ------------------------------------------------

    def start(self) -> asyncio.Task:
        """The startup publish, as a task: the glyphs' pictures, and the
        lists from the bot's games, with a board for every game the site
        does not have one for yet."""
        self._starting = asyncio.create_task(self._start())
        return self._starting

    async def _start(self) -> None:
        try:
            await self._put_emoji()
            for game in list(self.cog.games.values()):
                if self._closed:
                    return
                await self._catch_up(game)
            self.queue.lists_changed()
        except Exception:
            LOGGER.exception("Could not publish the Codex games at startup.")

    async def _put_emoji(self) -> None:
        for name in sorted(set(TOKEN_EMOJI.values())):
            try:
                body = await asyncio.to_thread((EMOJI_FOLDER / f"{name}.png").read_bytes)
            except OSError as error:
                LOGGER.warning("Could not read the Codex glyph %s: %s", name, error)
                continue
            await self.queue.put_file(keys.emoji_key(name), body)

    async def _catch_up(self, game: "CodexGame") -> None:
        """
        A game as the site should have it at startup: one being played
        whose current board is up needs nothing -- the next change sends
        a new one -- and an ended one the record already has needs
        nothing either. Anything else on the site gets its board drawn
        and sent: a game the record never saw, or one whose board did
        not go up before the restart.
        """
        if not shapes.on_site(game):
            return
        published = self.record.games.get(game.game_id)
        if game.status in ENDED and published is not None:
            return
        if game.status is not GameStatus.PLAYING and game.status not in ENDED:
            return
        if published is not None and published.board is not None and published.board in published.uploaded:
            return
        match = self.cog.service.load(game)
        board = await self.cog.render_match_png(game, match)
        published = self.record.game(game.game_id)
        if published.turn != match.turn:
            published.turn = match.turn
            published.lines = []
            published.head = []
        published.heading = turn_heading(match)
        published.board = keys.board_key(game.game_id, board)
        self._owe(game.game_id, [board])

    async def close(self) -> None:
        """The cog unloads: nothing new is taken, the tasks are stopped,
        and the queue closed. The record says what was confirmed."""
        self._closed = True
        tasks = [*self._tasks.values(), *([self._starting] if self._starting else [])]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.queue.close()

    async def drain(self) -> None:
        """Wait until nothing is owed, drawn or sent -- the tests'."""
        while True:
            tasks = [*self._tasks.values(),
                     *([self._starting] if self._starting and not self._starting.done() else [])]
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
                continue
            await self.queue.drain()
            if not self._tasks:
                return
