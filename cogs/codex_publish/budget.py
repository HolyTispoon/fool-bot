"""
Keeping the bucket inside R2's free plan (docs/design/pbd-site.md, "The
free plan").

- `Usage` -- what the bucket holds, key by key, measured by one listing
  as the publisher starts and kept up to date by every put and delete
  after it; and the Class A operations this bot has made this month,
  counted as it makes them and kept in `data/codex_pbd_usage.json`.
- `report` -- what a start says in #logs: each meter against the free
  plan's allowance.
- `offload_plan` -- which games come off the site once the bucket nears
  the free storage: the abandoned games first, then the finished ones,
  the longest untouched first, until it is back under `OFFLOAD_TO`.
  Never a game being played.

The allowances are Cloudflare's pricing page's, read 2026-10-17
(<https://developers.cloudflare.com/r2/pricing/>). A GB is taken as 10^9
bytes, the smaller reading, since the page does not say which.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Iterable, Mapping, Optional

from botkit.objectstore import list_pages
from codex.game import GameStatus
from cogs.codex_publish import keys, shapes

if TYPE_CHECKING:
    from codex.game import CodexGame
    from cogs.codex_publish.record import PublishRecord

LOGGER = logging.getLogger(__name__)

GB = 10**9

#: The free plan, a month: storage, writes and lists (Class A), and
#: reads (Class B). Deletes are free.
FREE_STORAGE = 10 * GB
FREE_CLASS_A = 1_000_000
FREE_CLASS_B = 10_000_000

#: The Workers free plan's Functions requests a day, which every read of
#: the bucket goes through: at most about 3.1 million reads a month, so
#: Class B cannot reach its allowance while the account is on that plan.
FREE_FUNCTION_REQUESTS_A_DAY = 100_000

#: Where the bucket starts giving games up, and how far down it goes: a
#: margin of ten points, so one offload is not followed by another a
#: game later.
OFFLOAD_AT = 0.8
OFFLOAD_TO = 0.7

#: The share of the month's Class A allowance at which a start, or the
#: write that crosses it, is an ERROR: offloading frees storage, not
#: writes, so somebody has to decide.
WRITES_ALARM = 0.8

#: The order games come off the site in: abandoned before finished.
OFFLOAD_ORDER = (GameStatus.ABANDONED, GameStatus.FINISHED)


def this_month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def size(count: int) -> str:
    """Bytes as the report says them: "1.23 GB", "45.6 MB"."""
    if count >= GB:
        return f"{count / GB:.2f} GB"
    return f"{count / 10**6:.1f} MB"


class Usage:
    """
    The bucket's size and the month's Class A operations. `sizes` is
    `None` until the listing has come back, and the storage meter with
    it; the writes are counted from the first call, the listing's
    included. `month` is `this_month` but for the tests.
    """

    def __init__(self, path: Path, *, month: Callable[[], str] = this_month) -> None:
        self.path = path
        self._month = month
        self.sizes: Optional[dict[str, int]] = None
        self._stored = 0
        self.month = month()
        self.writes = 0
        self._dirty = False
        self._alarmed = False

    @classmethod
    def load(cls, path: Path, *, month: Callable[[], str] = this_month) -> "Usage":
        usage = cls(path, month=month)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return usage
        except (OSError, ValueError) as error:
            LOGGER.warning("Could not read %s, so this month's writes are counted from zero: %s",
                           path, error)
            return usage
        if not isinstance(data, dict):
            return usage
        writes = data.get("class_a")
        if data.get("month") == usage.month and isinstance(writes, int) and not isinstance(writes, bool):
            usage.writes = writes
        return usage

    def save(self) -> None:
        """Write the month's count, where it changed; logged and never
        raised on a failure."""
        if not self._dirty:
            return
        temporary = self.path.with_suffix(".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps({"month": self.month, "class_a": self.writes}),
                                 encoding="utf-8")
            temporary.replace(self.path)
        except OSError as error:
            LOGGER.warning("Could not save the Codex bucket's write count to %s: %s",
                           self.path, error)
            return
        self._dirty = False

    # -- The meters, as the calls are made ------------------------------

    def wrote(self, count: int = 1) -> None:
        """`count` Class A operations made -- counted when tried, so a
        failed one counts too: the reading that never undercounts."""
        month = self._month()
        if month != self.month:
            self.month, self.writes, self._alarmed = month, 0, False
        self.writes += count
        self._dirty = True
        if not self._alarmed and self.writes >= WRITES_ALARM * FREE_CLASS_A:
            self._alarmed = True
            LOGGER.error(
                "The Codex games' bucket has had %s writes this month, %d%% of R2's free %s. "
                "Taking games off the site frees storage, not writes: past the allowance each "
                "million costs $4.50 until the month ends.",
                f"{self.writes:,}", 100 * self.writes // FREE_CLASS_A, f"{FREE_CLASS_A:,}")

    def put(self, key: str, body: int) -> None:
        """A put of `body` bytes under `key` succeeded."""
        if self.sizes is not None:
            self._stored += body - self.sizes.get(key, 0)
            self.sizes[key] = body

    def deleted(self, key: str) -> None:
        if self.sizes is not None:
            self._stored -= self.sizes.pop(key, 0)

    def listed(self, sizes: Mapping[str, int]) -> None:
        """The bucket's listing came back: every key and its size."""
        self.sizes = dict(sizes)
        self._stored = sum(self.sizes.values())

    # -- What they say ----------------------------------------------------

    @property
    def stored(self) -> Optional[int]:
        return None if self.sizes is None else self._stored

    def over(self, leaving: int = 0) -> bool:
        """Whether the bucket has reached the point where games come off,
        not counting `leaving` bytes already on their way out."""
        stored = self.stored
        return stored is not None and stored - leaving >= OFFLOAD_AT * FREE_STORAGE

    @property
    def target(self) -> int:
        return int(OFFLOAD_TO * FREE_STORAGE)


def listing_writes(sizes: Mapping[str, int]) -> int:
    """The Class A operations a listing of `sizes` took."""
    return list_pages(len(sizes))


def report(usage: Usage, error: Optional[str] = None) -> str:
    """What a start says: storage, writes and reads, each against the
    free plan. `error` is why the bucket could not be listed."""
    if usage.stored is None:
        storage = f"not measured -- the bucket could not be listed ({error})"
    else:
        storage = (f"{size(usage.stored)} of the free {size(FREE_STORAGE)} "
                   f"({100 * usage.stored / FREE_STORAGE:.1f}%, {len(usage.sizes):,} objects); "
                   f"games come off the site from {size(int(OFFLOAD_AT * FREE_STORAGE))}, "
                   f"down to {size(usage.target)}")
    return "\n".join([
        "**Codex site on R2, against the free plan**",
        f"- Storage: {storage}.",
        f"- Writes (Class A) this month: {usage.writes:,} of the free {FREE_CLASS_A:,}, "
        "as this bot counts its own.",
        f"- Reads (Class B): not counted here. Every read goes through the site's Function, "
        f"which the Workers free plan stops at {FREE_FUNCTION_REQUESTS_A_DAY:,} a day -- at most "
        f"about {FREE_FUNCTION_REQUESTS_A_DAY * 31 / 10**6:.1f} million a month of the free "
        f"{FREE_CLASS_B // 10**6} million.",
    ])


def offload_order(games: Iterable["CodexGame"], record: "PublishRecord") -> list["CodexGame"]:
    """The games that may come off the site, in the order they do: the
    abandoned, then the finished, each the longest untouched first (a
    game the site never saw change, with no `updated`, before any).
    Never a game being played, and never one already off."""
    def updated(game: "CodexGame") -> str:
        published = record.games.get(game.game_id)
        return (published.updated if published is not None else None) or ""

    order = []
    for status in OFFLOAD_ORDER:
        found = [game for game in games
                 if game.status is status and shapes.on_site(game)
                 and not getattr(record.games.get(game.game_id), "offloaded", False)]
        order.extend(sorted(found, key=updated))
    return order


def game_objects(game_id: str, sizes: Mapping[str, int]) -> list[str]:
    """Every key of the game's in the bucket, as the listing has it --
    the bucket's word, not the record's, so nothing is left behind."""
    prefix = keys.game_prefix(game_id)
    return sorted(key for key in sizes if key.startswith(prefix))


def leaving(record: "PublishRecord", sizes: Mapping[str, int]) -> int:
    """The bytes still in the bucket of games already taken off: their
    deletes are under way, or failed and are tried again, so they are not
    counted twice towards taking more off."""
    prefixes = tuple(keys.game_prefix(game_id) for game_id, published in record.games.items()
                     if published.offloaded)
    if not prefixes:
        return 0
    return sum(body for key, body in sizes.items() if key.startswith(prefixes))


def offload_plan(games: Iterable["CodexGame"], record: "PublishRecord",
                 sizes: Mapping[str, int], target: int) -> list[tuple["CodexGame", list[str]]]:
    """The games to take off, each with its keys, until what is left is
    at most `target` bytes -- or every game that may come off, where
    that is not enough."""
    stored = sum(sizes.values()) - leaving(record, sizes)
    plan = []
    for game in offload_order(games, record):
        if stored <= target:
            break
        objects = game_objects(game.game_id, sizes)
        if not objects:
            continue
        plan.append((game, objects))
        stored -= sum(sizes[key] for key in objects)
    return plan
