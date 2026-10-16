"""
The bucket's keys (docs/pbd-site.md, "The bucket's layout"): everything
the publisher writes is under `codex/` in the private bucket, and the
page reads each at `/data/<key>` through the site's one Function, which
answers only these shapes.

A key in the JSON is the whole key, `codex/` included, so the page
fetches `/data/` plus what it was handed and builds no key of its own.
A game's keys hold its `game_id` -- a uuid4's 32 hex characters, never
its number, which is reused -- and a board's its bytes' SHA-256, so a
board's key names one picture for good and is cached as immutable.
"""

import hashlib

PREFIX = "codex/"

INDEX_KEY = f"{PREFIX}index.json"
ARCHIVE_KEY = f"{PREFIX}archive.json"


def live_key(game_id: str) -> str:
    return f"{PREFIX}games/{game_id}/live.json"


def history_key(game_id: str) -> str:
    return f"{PREFIX}games/{game_id}/history.json"


def board_key(game_id: str, board: bytes) -> str:
    """A board's key, named by its bytes: the same picture is the same
    key, and a key is never written twice."""
    return f"{PREFIX}games/{game_id}/board-{hashlib.sha256(board).hexdigest()}.webp"


def emoji_key(name: str) -> str:
    """A glyph's picture, by its file's name under `codex/images/emoji/`."""
    return f"{PREFIX}emoji/{name}.png"


#: How long a browser and Cloudflare may keep each kind of object
#: (docs/pbd-site.md, "The bucket's layout"). The JSON is asked again on
#: every poll; a board is named by its bytes, so it never changes; a
#: glyph's picture changes only when the emoji are redrawn.
NO_CACHE = "no-cache"
IMMUTABLE = "public, max-age=31536000, immutable"
A_DAY = "public, max-age=86400"


def content_type(key: str) -> str:
    """The object's type, by its key's extension."""
    if key.endswith(".json"):
        return "application/json; charset=utf-8"
    if key.endswith(".webp"):
        return "image/webp"
    if key.endswith(".png"):
        return "image/png"
    raise ValueError(f"Not a key the publisher writes: {key}")


def cache_control(key: str) -> str:
    """The object's `Cache-Control`, by which kind of key it is."""
    if key.endswith(".json"):
        return NO_CACHE
    if key.startswith(f"{PREFIX}emoji/"):
        return A_DAY
    if key.endswith(".webp"):
        return IMMUTABLE
    raise ValueError(f"Not a key the publisher writes: {key}")
