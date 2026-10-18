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
- `start`: the startup publish, as a task off `cog_load` -- the bucket
  measured first and reported in #logs against R2's free plan -- and
  after it the old turns' import from the pins (`import_old_turns`).

**The free plan.** Once the bucket nears the free storage, games come
off the site -- the abandoned first, then the finished, never one being
played -- each downloaded whole into `data/codex_pbd_offloaded/`, in the
bucket's layout, before it is deleted (`offload`; docs/design/pbd-site.md,
"The free plan").

Each hook changes the publisher's record at once -- the lines are the
cog's at that moment, and some are gone a line later -- and leaves the
rest to the game's own task: drawing a board where the hook had none,
saving the record, and naming the game to the queue. **Nothing raises
out of a hook, and no hook awaits anything**, so publishing never fails
or slows a click, and spends no Discord request. The only Discord
requests the publisher makes are the old turns' import's: once a game,
at startup, behind the queue.

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
from collections import defaultdict
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Callable, Iterable, Optional

import discord

import botlog
from codex.components import MatchState
from codex.formatting import turn_heading
from codex.game import GameStatus
from cogs.codex_helpers import TOKEN_EMOJI
from cogs.codex_publish import budget, cards, keys, pins, shapes
from cogs.codex_publish.queue import ENDED, PublishQueue, encode
from cogs.codex_publish.record import PublishedGame, PublishRecord
from gamekit.storage import PROJECT_ROOT

if TYPE_CHECKING:
    from botkit.objectstore import ObjectStore
    from codex.game import CodexGame

LOGGER = logging.getLogger(__name__)

#: The glyphs' pictures, as the cog's emoji are drawn from them
#: (`TOKEN_EMOJI`'s files).
EMOJI_FOLDER = PROJECT_ROOT / "codex" / "images" / "emoji"

#: The most pins one listing hands back (Discord's cap on the endpoint).
PIN_PAGE = 50

#: Beside the record's file: the month's write count, and the games
#: taken off the site, in the bucket's layout, so
#: `scripts/serve_pbd.py --data data/codex_pbd_offloaded` shows one.
USAGE_FILE_NAME = "codex_pbd_usage.json"
OFFLOAD_FOLDER_NAME = "codex_pbd_offloaded"


def now() -> str:
    """When a game last changed: ISO 8601 in UTC, to the second."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Publisher:
    """
    One per cog, over the cog's games, its turn's lines and its board
    renderer. `cog` is read for `games`, `turn_lines`, `turn_heads`,
    `service`, `render_match_png` and `board_map` and nothing else -- and `bot`, by
    the old turns' import alone.
    """

    def __init__(self, cog, store: "ObjectStore", record: Optional[PublishRecord] = None, *,
                 clock: Callable[[], str] = now, queue: Optional[PublishQueue] = None) -> None:
        self.cog = cog
        self.record = record if record is not None else PublishRecord.load()
        self.usage = budget.Usage.load(self.record.file.with_name(USAGE_FILE_NAME))
        self.offload_folder = self.record.file.parent / OFFLOAD_FOLDER_NAME
        self.queue = queue or PublishQueue(store, self.record, lambda: self.cog.games)
        self.queue.usage = self.usage
        self.queue.grown = self.check_budget
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
        #: Per game, the maps of the boards handed over, by the map's key,
        #: taken from the cog as each board is handed over.
        self._maps: dict[str, dict[str, bytes]] = {}
        self._owed: set[str] = set()
        self._draw: set[str] = set()
        #: Per game, a count of the changes made: a board drawn for an
        #: older one is not the current board.
        self._changes: dict[str, int] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._starting: Optional[asyncio.Task] = None
        self._offloading: Optional[asyncio.Task] = None
        # Whether a bucket past the mark with nothing left to take off has
        # been said, so it is said once until an offload succeeds.
        self._stuck = False
        # No game comes off before the start has said what the bucket holds.
        self._reported = False
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
        if getattr(self.record.games.get(game.game_id), "offloaded", False):
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
            self._maps.pop(game_id, None)
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
        if draw:
            self._draw.add(game_id)
        else:
            # The board handed over is the newest: nothing to draw.
            self._draw.discard(game_id)
        self._owe_send(game_id, boards)

    def _owe_send(self, game_id: str, boards: Iterable[bytes]) -> None:
        """The game owes a send, with `boards` handed over -- and no
        change to its current board, so a drawing under way stands."""
        boards = list(boards)
        self._boards.setdefault(game_id, []).extend(boards)
        self._take_maps(game_id, boards)
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
                self.queue.game_changed(game_id, self._boards.pop(game_id, []),
                                        self._maps.pop(game_id, {}))
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
        self._take_maps(game_id, [board])

    def _take_maps(self, game_id: str, boards: Iterable[bytes]) -> None:
        """Each board's map, where the cog drew it lately (`board_map`),
        as the page's JSON: taken as the board is handed over, while the
        cog still holds it. A board read back off a pin has none."""
        for board in boards:
            drawn = self.cog.board_map(board)
            if drawn is None:
                continue
            key = keys.board_map_key(keys.board_key(game_id, board))
            self._maps.setdefault(game_id, {})[key] = encode(shapes.board_map(drawn))

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
        error = await self._measure()
        try:
            await self._put_emoji()
            await self._put_cards()
            for game in list(self.cog.games.values()):
                if self._closed:
                    return
                await self._catch_up(game)
            self.queue.lists_changed()
        except Exception:
            LOGGER.exception("Could not publish the Codex games at startup.")
        try:
            await self._settled()
            await self._report(error)
            self._finish_offloads()
            self.check_budget()
            if self._offloading is not None:
                await asyncio.gather(self._offloading, return_exceptions=True)
        except Exception:
            LOGGER.exception("Could not check the Codex games' bucket against R2's free plan.")
        try:
            await self.import_old_turns()
        except Exception:
            LOGGER.exception("Could not import the Codex games' old turns from their pins.")

    async def _settled(self) -> None:
        """Wait until the games' tasks and the queue are idle: the
        import goes behind what the startup publish sent."""
        while self._tasks and not self._closed:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        await self.queue.drain()

    # -- The old turns, from the pins ---------------------------------------

    async def import_old_turns(self) -> None:
        """
        Every game on the site whose import has not run -- being played,
        finished or abandoned, every one the bot has and not only the
        ones the record already had -- gets the turns its channel's pins
        hold before the earliest the record has: one channel at a time,
        its pins listed once for every game in it (a Rematch's earlier
        game, or several `here` games, share one).
        """
        bot = self.cog.bot
        await bot.wait_until_ready()
        bot_id = bot.user.id
        owed: dict[Optional[int], list["CodexGame"]] = defaultdict(list)
        for game in self.cog.games.values():
            if not shapes.on_site(game) or game.status not in (GameStatus.PLAYING, *ENDED):
                continue
            published = self.record.games.get(game.game_id)
            if published is None or not (published.imported or published.offloaded):
                owed[game.channel_id].append(game)
        for channel_id, games in owed.items():
            if self._closed:
                return
            if channel_id is None:
                self._imported(games, {})
                continue
            await self._import_channel(bot, bot_id, channel_id, games)

    async def _import_channel(self, bot, bot_id: int, channel_id: int,
                              games: list["CodexGame"]) -> None:
        requests = 0
        numbers = ", ".join(f"#{game.game_number}" for game in games)
        try:
            channel = bot.get_channel(channel_id)
            if channel is None:
                # An archived thread is not in the cache.
                requests += 1
                channel = await bot.fetch_channel(channel_id)
            pinned = []
            before = None
            while True:
                requests += 1
                page = [message async for message in channel.pins(limit=PIN_PAGE, before=before)]
                pinned.extend(page)
                before = page[-1].pinned_at if page else None
                if len(page) < PIN_PAGE or before is None:
                    break
        except (discord.NotFound, discord.Forbidden) as error:
            # Gone, or not the bot's to read: there is nothing to import,
            # and nothing a later start would find.
            LOGGER.info("No old turns to import for Codex games %s: their channel %s cannot be "
                        "read (%s); %d requests.", numbers, channel_id, type(error).__name__,
                        requests)
            self._imported(games, {})
            return
        except discord.HTTPException as error:
            LOGGER.warning("Could not list the pins of channel %s for Codex games %s: %s; the next "
                           "start tries again.", channel_id, numbers, error)
            return
        pinned.sort(key=lambda message: message.id)

        found: dict[str, list[pins.PinnedTurn]] = {}
        boards: dict[str, list[bytes]] = {}
        for game in games:
            turns: dict[int, pins.PinnedTurn] = {}
            for message in pinned:
                turn = pins.read_turn(message, game, bot_id)
                if turn is not None:
                    # A turn pinned twice -- an undo to it, played again --
                    # is its later pin.
                    turns[turn.turn] = turn
            limit = self._earliest(game.game_id)
            kept = [turns[turn] for turn in sorted(turns) if limit is None or turn < limit]
            try:
                read = []
                for turn in kept:
                    requests += 1
                    read.append(await turn.board.read())
            except (discord.HTTPException, OSError) as error:
                LOGGER.warning("Could not download a pinned board of Codex game #%s: %s; the next "
                               "start tries again.", game.game_number, error)
                continue
            found[game.game_id] = kept
            boards[game.game_id] = read
        self._imported([game for game in games if game.game_id in found], found, boards)
        LOGGER.info("Read the pins of channel %s for Codex games %s: %d old turns imported, "
                    "%d requests.", channel_id, numbers,
                    sum(len(kept) for kept in found.values()), requests)

    def _earliest(self, game_id: str) -> Optional[int]:
        """The earliest turn the record holds -- its history's first, or
        the current turn's -- before which the pins are imported."""
        published = self.record.games.get(game_id)
        if published is None:
            return None
        held = [entry["turn"] for entry in published.history if isinstance(entry.get("turn"), int)]
        if published.turn is not None:
            held.append(published.turn)
        return min(held, default=None)

    def _imported(self, games: list["CodexGame"], found: dict[str, list["pins.PinnedTurn"]],
                  boards: Optional[dict[str, list[bytes]]] = None) -> None:
        """Write each game's pinned turns before the earliest the record
        holds now -- a turn may have ended while the boards downloaded --
        and mark its import done."""
        for game in games:
            if self.cog.games.get(game.game_id) is not game:
                # Dropped while its pins were read.
                continue
            published = self.record.game(game.game_id)
            limit = self._earliest(game.game_id)
            entries = [
                ({"turn": turn.turn, "heading": turn.heading, "lines": turn.lines,
                  "board": keys.board_key(game.game_id, board)}, board)
                for turn, board in zip(found.get(game.game_id, []),
                                       (boards or {}).get(game.game_id, []))
                if limit is None or turn.turn < limit
            ]
            published.imported = True
            if entries:
                published.history = [entry for entry, _ in entries] + published.history
                published.history_version += 1
            self._owe_send(game.game_id, [board for _, board in entries])

    async def _put_emoji(self) -> None:
        for name in sorted(set(TOKEN_EMOJI.values())):
            try:
                body = await asyncio.to_thread((EMOJI_FOLDER / f"{name}.png").read_bytes)
            except OSError as error:
                LOGGER.warning("Could not read the Codex glyph %s: %s", name, error)
                continue
            await self.queue.put_file(keys.emoji_key(name), body)

    async def _put_cards(self) -> None:
        """
        Every card's picture (`cards.pictured`), for the page's hover:
        each put only where the start's listing of the bucket does not
        have it at its size, so the art goes up once and not every start
        (docs/design/pbd-site.md, "The cards' pictures"). Where the
        bucket could not be listed, every one is put.
        """
        listed = self.usage.sizes
        for slug in cards.pictured():
            if self._closed:
                return
            path = cards.picture(slug)
            key = cards.key(slug)
            try:
                size = await asyncio.to_thread(lambda: path.stat().st_size)
                if listed is not None and listed.get(key) == size:
                    continue
                body = await asyncio.to_thread(path.read_bytes)
            except OSError as error:
                LOGGER.warning("Could not read the Codex card %s's picture: %s", slug, error)
                continue
            await self.queue.put_file(key, body)

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

    # -- The free plan ---------------------------------------------------------

    async def _measure(self) -> Optional[str]:
        """List the bucket: every key and its size, the storage meter's
        start. Why it could not be listed, or `None`."""
        try:
            sizes = await self.queue.store.list()
        except Exception as error:
            self.usage.wrote()
            LOGGER.warning("Could not list the Codex games' bucket to measure it: %s: %s",
                           type(error).__name__, error)
            return f"{type(error).__name__}: {error}"
        self.usage.wrote(budget.listing_writes(sizes))
        self.usage.listed(sizes)
        self.usage.save()
        return None

    async def _report(self, error: Optional[str]) -> None:
        """Every start: what the bucket uses against the free plan, on the
        console and in #logs."""
        text = budget.report(self.usage, error)
        LOGGER.info("%s", text.replace("\n", " "))
        await self.cog.bot.wait_until_ready()
        await botlog.post_notice(self.cog.bot, text)
        self._reported = True

    def _finish_offloads(self) -> None:
        """A game taken off whose objects are still in the bucket -- a
        delete that failed before a restart -- has them deleted again:
        it was downloaded before it was marked."""
        sizes = self.usage.sizes
        if sizes is None:
            return
        left = {game_id: budget.game_objects(game_id, sizes)
                for game_id, published in self.record.games.items() if published.offloaded}
        left = {game_id: objects for game_id, objects in left.items() if objects}
        if left:
            self.queue.games_dropped(left)

    def check_budget(self) -> None:
        """Called after every put: once the bucket reaches `OFFLOAD_AT` of
        the free storage, not counting what is already on its way out,
        games come off the site until it is down to `OFFLOAD_TO`."""
        if self._closed or not self._reported:
            return
        if self._offloading is not None and not self._offloading.done():
            return
        if not self.usage.over():
            return
        if not self.usage.over(budget.leaving(self.record, self.usage.sizes)):
            return
        self._offloading = asyncio.create_task(self.offload())

    async def offload(self) -> None:
        """
        Take games off the site, in `budget.offload_order`, until the
        bucket is back under `OFFLOAD_TO`: each downloaded whole -- every
        key the listing has under it, checked against its size -- into
        `offload_folder`, then marked in the record, so it leaves both
        lists, and then deleted from the bucket after the lists without
        it are up. A game whose download fails stays on the site.
        """
        try:
            await self._offload()
        except Exception:
            LOGGER.exception("Could not take Codex games off the site to stay inside R2's free plan.")

    async def _offload(self) -> None:
        sizes = self.usage.sizes
        plan = budget.offload_plan(self.cog.games.values(), self.record, sizes, self.usage.target)
        if not plan:
            if not self._stuck:
                self._stuck = True
                LOGGER.error(
                    "The Codex games' bucket holds %s of R2's free %s and no finished or abandoned "
                    "game is left to take off the site. Past the allowance each GB costs $0.015 a "
                    "month.", budget.size(self.usage.stored), budget.size(budget.FREE_STORAGE))
            return
        taken: dict[str, list[str]] = {}
        failed: list["CodexGame"] = []
        for game, objects in plan:
            if self._closed:
                return
            if await self._download(game, objects):
                taken[game.game_id] = objects
                published = self.record.game(game.game_id)
                published.offloaded = True
                published.uploaded = []
            else:
                failed.append(game)
        if not taken:
            return
        self._stuck = False
        self.record.save()
        freed = sum(sizes.get(key, 0) for objects in taken.values() for key in objects)
        # Off both lists, then out of the bucket.
        self.queue.games_dropped(taken)
        await self.queue.drain()
        await self._announce_offload(plan, taken, failed, freed)

    async def _download(self, game: "CodexGame", objects: list[str]) -> bool:
        bodies: dict[str, bytes] = {}
        sizes = self.usage.sizes or {}
        for key in objects:
            try:
                body = await self.queue.store.get(key)
            except Exception as error:
                LOGGER.warning("Could not download %s to take Codex game #%s off the site: %s: %s",
                               key, game.game_number, type(error).__name__, error)
                return False
            if key in sizes and len(body) != sizes[key]:
                LOGGER.warning("Downloaded %s for Codex game #%s as %d bytes, not the %d listed; "
                               "it stays on the site.", key, game.game_number, len(body), sizes[key])
                return False
            bodies[key] = body
        try:
            await asyncio.to_thread(self._write_offloaded, bodies)
        except OSError as error:
            LOGGER.warning("Could not save Codex game #%s into %s: %s; it stays on the site.",
                           game.game_number, self.offload_folder, error)
            return False
        return True

    def _write_offloaded(self, bodies: dict[str, bytes]) -> None:
        for key, body in bodies.items():
            path = self.offload_folder / key
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(path.name + ".tmp")
            temporary.write_bytes(body)
            temporary.replace(path)

    async def _announce_offload(self, plan, taken: dict[str, list[str]],
                                failed: list["CodexGame"], freed: int) -> None:
        def numbers(status: GameStatus) -> str:
            found = [f"#{game.game_number}" for game, _ in plan
                     if game.game_id in taken and game.status is status]
            return ", ".join(found) or "none"

        lines = [
            f"**Codex site: {len(taken)} game(s) taken off to stay inside R2's free plan**, "
            f"{budget.size(freed)} downloaded into `{self.offload_folder}` and deleted from the "
            f"bucket -- abandoned {numbers(GameStatus.ABANDONED)}; "
            f"finished {numbers(GameStatus.FINISHED)}.",
            f"The bucket now holds {budget.size(self.usage.stored)} of the free "
            f"{budget.size(budget.FREE_STORAGE)}.",
        ]
        if failed:
            lines.append("Could not download, so still on the site: "
                         + ", ".join(f"#{game.game_number}" for game in failed) + ".")
        text = "\n".join(lines)
        LOGGER.info("%s", text.replace("\n", " "))
        await botlog.post_notice(self.cog.bot, text)

    async def close(self) -> None:
        """The cog unloads: nothing new is taken, the tasks are stopped,
        and the queue closed. The record says what was confirmed."""
        self._closed = True
        tasks = [*self._tasks.values(), *([self._starting] if self._starting else []),
                 *([self._offloading] if self._offloading else [])]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.queue.close()

    async def drain(self) -> None:
        """Wait until nothing is owed, drawn or sent -- the tests'."""
        while True:
            tasks = [*self._tasks.values(),
                     *([self._starting] if self._starting and not self._starting.done() else []),
                     *([self._offloading] if self._offloading and not self._offloading.done() else [])]
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
                continue
            await self.queue.drain()
            if not self._tasks:
                return
