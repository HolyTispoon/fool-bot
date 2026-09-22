"""
Who is on the other end of a web request.

Discord answers this for the bot: an interaction carries the account
that clicked, and `SafeView.may_act_for` reads it. A browser carries
nothing, so the link itself is the credential -- one per coach per
game, handed to that coach in a channel only they can read.

**A key is derived, never stored** (principle 6: the save format is
the contract, and a web session is not a fact about the game). It is
an HMAC of the game id and the player number under one process
secret, so the two links for a game can always be worked out again
and nothing has to be written down or migrated. `FOOLBOT_WEB_SECRET`
keeps them valid across restarts; with none set, a random secret is
made at startup and every link dies with the process -- which is the
safe default for a bot whose `.env` nobody has edited yet.

**A key names a coach; it is not permission to do anything.** What a
coach may answer is the prompt's, read off `asked_sides` the same way
the AI's side is (`webapp/present.py`), and what the *position*
allows is the driver's. This module only answers "which of the two
coaches is this, if either".
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from typing import Optional

#: How much of the digest a link carries. 16 hex characters is 64 bits
#: of a keyed hash: not worth guessing at for a prototype's game of
#: football, and short enough to read out over a voice channel.
KEY_LENGTH = 16

#: Where the link points. The bot posts it, so it has to be the
#: address a person's browser can reach -- which is not something the
#: server can know about itself behind a tunnel or a proxy.
BASE_URL_VARIABLE = "FOOLBOT_WEB_URL"
SECRET_VARIABLE = "FOOLBOT_WEB_SECRET"

_process_secret: Optional[bytes] = None


def secret() -> bytes:
    """
    The secret the keys are derived under: the environment's, or one
    made for this process and kept for as long as it runs.
    """
    global _process_secret
    configured = os.environ.get(SECRET_VARIABLE, "").strip()
    if configured:
        return configured.encode("utf-8")
    if _process_secret is None:
        _process_secret = secrets.token_bytes(32)
    return _process_secret


def key_for(game_id: str, player_number: int) -> str:
    """One coach's key for one game."""
    if player_number not in (1, 2):
        raise ValueError(f"not a player number: {player_number!r}")
    digest = hmac.new(
        secret(), f"{game_id}:{player_number}".encode("utf-8"), hashlib.sha256,
    ).hexdigest()
    return digest[:KEY_LENGTH]


def player_number_for(game_id: str, key: Optional[str]) -> Optional[int]:
    """
    Which coach this key names, or `None` -- a spectator, a stale
    link, or a link for another game.

    Compared with `compare_digest` rather than `==`: the comparison is
    over a secret, and this is the one place in the bot where the time
    a comparison takes says anything.
    """
    if not key:
        return None
    for player_number in (1, 2):
        if hmac.compare_digest(key, key_for(game_id, player_number)):
            return player_number
    return None


def base_url() -> str:
    """Where a link points, without its trailing slash."""
    return os.environ.get(BASE_URL_VARIABLE, "http://localhost:8080").rstrip("/")


def link_for(game_id: str, player_number: int) -> str:
    """The whole link one coach opens."""
    return (
        f"{base_url()}/game/{game_id}?key={key_for(game_id, player_number)}"
    )
