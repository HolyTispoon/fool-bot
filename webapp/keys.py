"""
The web app's one secret, and where its links point.

A browser carries nothing, so the web app signs what it hands one: a
person's cookie (`webapp/identity.py`) is an HMAC under this secret.
`FOOLBOT_WEB_SECRET` keeps a cookie good across restarts; with none
set, a random secret is made at startup and every cookie dies with the
process -- which is the safe default for a checkout whose `.env` nobody
has edited yet.

It used to derive a key per coach per game for the links the bot
handed out; the rooms of step 2 of docs/web-app-next.md replaced those
with a person's own cookie and a seat in the room's record.
"""

from __future__ import annotations

import os
import secrets
from typing import Optional

#: Where the app is reached from -- which is not something the server
#: can know about itself behind a tunnel or a proxy.
BASE_URL_VARIABLE = "FOOLBOT_WEB_URL"
SECRET_VARIABLE = "FOOLBOT_WEB_SECRET"

_process_secret: Optional[bytes] = None


def secret() -> bytes:
    """
    The secret a cookie is signed under: the environment's, or one
    made for this process and kept for as long as it runs.
    """
    global _process_secret
    configured = os.environ.get(SECRET_VARIABLE, "").strip()
    if configured:
        return configured.encode("utf-8")
    if _process_secret is None:
        _process_secret = secrets.token_bytes(32)
    return _process_secret


def base_url() -> str:
    """Where a link points, without its trailing slash."""
    return os.environ.get(BASE_URL_VARIABLE, "http://localhost:8080").rstrip("/")
