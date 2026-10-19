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

#: The site's address (docs/design/pbd-site.md, "Deploying"): the Pages
#: project's, which Cloudflare gave without a suffix.
SITE = "https://codex-pbd.pages.dev"

INDEX_KEY = f"{PREFIX}index.json"
ARCHIVE_KEY = f"{PREFIX}archive.json"


def game_page(game_id: str) -> str:
    """The game's page on the site, `/game/<game_id>`, which `_redirects`
    rewrites onto `game.html` -- the link under the turn message."""
    return f"{SITE}/game/{game_id}"


def game_prefix(game_id: str) -> str:
    """Everything of one game's is under this: its `live.json`, its
    `history.json` and its boards."""
    return f"{PREFIX}games/{game_id}/"


def live_key(game_id: str) -> str:
    return f"{game_prefix(game_id)}live.json"


def history_key(game_id: str) -> str:
    return f"{game_prefix(game_id)}history.json"


def board_key(game_id: str, board: bytes) -> str:
    """A board's key, named by its bytes: the same picture is the same
    key, and a key is never written twice."""
    return f"{game_prefix(game_id)}board-{hashlib.sha256(board).hexdigest()}.webp"


def board_map_key(board: str) -> str:
    """Where the cards are on a board (`codex.render.render_board_mapped`),
    beside it, by the board's own key: the same drawing is the same map."""
    return board[: -len(".webp")] + ".json"


def card_key(slug: str, suffix: str) -> str:
    """A card's picture, by its slug and its file's suffix -- ".jpg" for
    the database's art, ".png" for the module's tokens, buildings and
    worker cards."""
    return f"{PREFIX}cards/{slug}{suffix}"


def emoji_key(name: str) -> str:
    """A glyph's picture, by its file's name under `codex/images/emoji/`."""
    return f"{PREFIX}emoji/{name}.png"


#: How long a browser and Cloudflare may keep each kind of object
#: (docs/pbd-site.md, "The bucket's layout"). The JSON is asked again on
#: every poll; a board and its map are named by the board's bytes, so
#: neither ever changes; a glyph's picture and a card's change only when
#: the emoji are redrawn or the art imported again.
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
    if key.endswith(".jpg"):
        return "image/jpeg"
    raise ValueError(f"Not a key the publisher writes: {key}")


def cache_control(key: str) -> str:
    """The object's `Cache-Control`, by which kind of key it is."""
    if key.startswith(f"{PREFIX}games/") and "/board-" in key:
        return IMMUTABLE
    if key.endswith(".json"):
        return NO_CACHE
    if key.startswith((f"{PREFIX}emoji/", f"{PREFIX}cards/")):
        return A_DAY
    if key.endswith(".webp"):
        return IMMUTABLE
    raise ValueError(f"Not a key the publisher writes: {key}")
