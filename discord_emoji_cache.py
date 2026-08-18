"""
The one piece of "fetch this application's emoji, retry while any are
missing, but not on every call" logic, shared by every cog that caches
application emoji -- cogs/coins.py and cogs/d12ball.py today.

Each cog still owns *what* it loads and *how* (a coin's faces, a
condition token, a team ring -- different names, different fallback
emoji, and d12ball's loaders share one upstream fetch across three
lookups where coins.py only has the one). What was identical between
them was the caching shape around that: a dict plus a monotonic
timestamp, refreshed only when short of the expected count and only
once every EMOJI_REFETCH_INTERVAL. That shape is `ensure_cached_emojis`;
the cog still holds the dict and the timestamp as its own attributes
(so an existing `cog.coin_emojis = {}` in a test, or a `del` between
games, still works exactly as before), and hands both in and gets both
back.
"""

import time
from typing import Awaitable, Callable, Optional


# An application with nothing uploaded is short of every emoji on every
# call that asks, so without a cooldown the retry becomes an HTTP
# request per call, forever, for an answer that has not changed since
# startup. Long enough that an upload during testing still takes effect
# well inside a session; short enough nobody restarts the bot to see it
# land.
EMOJI_REFETCH_INTERVAL = 300.0


async def ensure_cached_emojis(
    cache: dict,
    checked_at: Optional[float],
    expected_count: int,
    loader: Callable[[], Awaitable[dict]],
    interval: float = EMOJI_REFETCH_INTERVAL,
) -> tuple[dict, Optional[float]]:
    """
    `(cache, checked_at)`, refreshed through `loader` when `cache` is
    short of `expected_count` entries and the last check was more than
    `interval` seconds ago on the monotonic clock -- otherwise the
    inputs, unchanged, so a cog already at capacity or still in
    cooldown pays nothing.

    `loader` decides what a short-of-capacity cache still returns on a
    failed fetch (some callers keep the old cache; see
    D12Ball.ensure_coin_emojis, which falls back to `cache` itself
    inside its loader when the application emoji fetch comes back
    empty).
    """
    if len(cache) >= expected_count:
        return cache, checked_at

    now = time.monotonic()
    if checked_at is not None and now - checked_at < interval:
        return cache, checked_at

    return await loader(), now
