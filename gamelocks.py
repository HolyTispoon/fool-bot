"""
One lock per game, shared by every frontend in this process.

**Why there is one process.** `gamesaves/d12ball/storage.py` rewrites
the whole save file on every call and reads it once at startup, so a
second process would overwrite the first's file with a stale copy of
every game -- finding 13 of docs/web-app.md, settled by decision 5:
both frontends call one `GameService` over one `games` dict, on one
event loop. A shared store with a row per game is the day the web app
has to outlive a bot restart, and not before.

**What the lock is actually for.** `GameService.apply_action` is
synchronous, so on one event loop it cannot be interleaved: load,
answer, run and save happen with nothing else running. What *is*
interleaved is everything around it -- a Discord click renders images,
uploads them and edits messages, and every one of those is an `await`
that lets the next click through. So two answers can be applied back
to back correctly and then be *presented* in either order, which is a
turn arriving in a channel out of sequence, and a web request
rendering a board that the click after it has already moved.

So the lock is held around **apply plus present**, not around the
apply: from the moment a frontend takes an action to the moment it has
finished showing what came back. It is the frontend's, like every
other ordering decision (CLAUDE.md, principle 8), which is why it
lives here and not on the service -- the model may not be async, and a
lock is nothing but an await.

A game that has never been clicked has no lock; one that has keeps it
for the life of the process, which is a few bytes against a dict of
games already in memory.
"""

from __future__ import annotations

import asyncio


class GameLocks:
    """
    The locks, by game id. `hold(game_id)` is the one call:

        async with locks.hold(game.game_id):
            result = service.apply_action(...)
            await present(result)

    `asyncio.Lock` binds to the running loop on first use rather than
    at construction, so one of these may be built before the bot is
    running -- which is what a cog built in `__init__` does.
    """

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}

    def hold(self, game_id: str) -> asyncio.Lock:
        """The lock for one game, made on first use."""
        lock = self._locks.get(game_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[game_id] = lock
        return lock

    def held(self, game_id: str) -> bool:
        """Whether somebody is holding this game's lock -- for a
        frontend that would rather say "one moment" than queue."""
        lock = self._locks.get(game_id)
        return lock is not None and lock.locked()
