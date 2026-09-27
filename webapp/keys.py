"""
The web app's one secret, and where its links point.

A browser carries nothing, so the web app signs what it hands one: a
person's cookie (`webapp/identity.py`) is an HMAC under this secret.
`FOOLBOT_WEB_SECRET` keeps a cookie good across restarts. With none
set, the running web app makes one once and keeps it in
`data/d12ball_web_secret` (`keep_secret_in`, called by `serve`), so a
restart that somehow comes up without the `.env` line still reads
everybody's cookie; only a process that never named a file -- a test,
a script -- makes one per process that dies with it. The file is
`data/`'s like every other runtime file: per checkout, untracked, and
a credential.

It used to derive a key per coach per game for the links the bot
handed out; the rooms of step 2 of docs/web-app-next.md replaced those
with a person's own cookie and a seat in the room's record.
"""

from __future__ import annotations

import logging
import os
import secrets
from pathlib import Path
from typing import Optional

from gamesaves.d12ball.storage import DATA_FOLDER

LOGGER = logging.getLogger(__name__)

#: Where the secret is kept when the environment names none (`serve`
#: passes it to `keep_secret_in`; nothing else writes it).
WEB_SECRET_FILE = DATA_FOLDER / "d12ball_web_secret"

#: Where the app is reached from -- which is not something the server
#: can know about itself behind a tunnel or a proxy.
BASE_URL_VARIABLE = "FOOLBOT_WEB_URL"
SECRET_VARIABLE = "FOOLBOT_WEB_SECRET"

_process_secret: Optional[bytes] = None


def configured() -> bool:
    """Whether the environment names the secret."""
    return bool(os.environ.get(SECRET_VARIABLE, "").strip())


def secret() -> bytes:
    """
    The secret a cookie is signed under: the environment's, or the one
    `keep_secret_in` read or made, or one made for this process and kept
    for as long as it runs.
    """
    global _process_secret
    named = os.environ.get(SECRET_VARIABLE, "").strip()
    if named:
        return named.encode("utf-8")
    if _process_secret is None:
        _process_secret = secrets.token_bytes(32)
    return _process_secret


def keep_secret_in(path: Path) -> None:
    """
    Where the secret lives when the environment names none: read from
    `path`, or made and written there the first time, so it outlives
    the process. Nothing to do when the environment names one -- that
    is the secret, and a file beside it would only disagree.

    A file that cannot be read or written leaves the per-process secret
    in place, said at WARNING: the web app still runs, and everybody's
    cookie dies with it as it always did.
    """
    global _process_secret
    if configured():
        return
    try:
        kept = path.read_text(encoding="ascii").strip()
    except FileNotFoundError:
        kept = ""
    except (OSError, UnicodeDecodeError):
        LOGGER.warning(
            "%s is not set and %s cannot be read: cookies will not "
            "outlive this process.", SECRET_VARIABLE, path, exc_info=True,
        )
        return
    if kept:
        _process_secret = kept.encode("ascii")
        LOGGER.warning(
            "%s is not set; cookies are signed under the secret kept in %s.",
            SECRET_VARIABLE, path,
        )
        return
    made = secrets.token_hex(32)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(made + "\n", encoding="ascii")
        path.chmod(0o600)
    except OSError:
        LOGGER.warning(
            "%s is not set and %s cannot be written: cookies will not "
            "outlive this process.", SECRET_VARIABLE, path, exc_info=True,
        )
        return
    _process_secret = made.encode("ascii")
    LOGGER.warning(
        "%s is not set; made a secret and kept it in %s, so cookies "
        "outlive a restart.", SECRET_VARIABLE, path,
    )


def base_url() -> str:
    """Where a link points, without its trailing slash."""
    return os.environ.get(BASE_URL_VARIABLE, "http://localhost:8080").rstrip("/")
