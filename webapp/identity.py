"""
Who is reading a web page: a name, an id, and a signed cookie.

Discord answers this for the bot -- an interaction carries the account
that clicked. A browser carries nothing, so the web app issues its own:
on a first visit the page asks for a name, and the server answers with
a `Coach` in a cookie signed under `keys.secret()`. Coming back with
the cookie is being the same person; another device is another cookie,
which is why a seat is left and taken again rather than shared
(decision 1 of docs/web-app-next.md).

**Nothing is stored.** The cookie is the whole record of who somebody
is: the id and the name in it, and an HMAC that says this server wrote
them. There is no table of coaches to migrate, back up or leak, and the
game record holds the id in a seat the way it holds a Discord id. With
no `FOOLBOT_WEB_SECRET` set, the secret is made per process and every
cookie dies with it, which is the safe default the links had.

**An identity is not permission.** It says which seat of a room this
person holds, if either (`webapp/server.py` compares the id with the
record's two); what a seat may answer is still `asked_sides`, read by
`webapp/present.py`.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from typing import Optional

from aiohttp import web

from webapp import keys

#: The cookie's name, and how long a browser keeps it: a year, since a
#: person is who they said they were until they clear it.
COOKIE = "d12ball_coach"
COOKIE_MAX_AGE = 365 * 24 * 60 * 60

#: How long a name may be, after the spaces around it are dropped.
NAME_LIMIT = 32

#: The largest id `issue` hands out. A Discord id is a 64-bit snowflake,
#: and the record takes either; this stops at 2**53 because the id goes
#: to a browser in `GET /api/me`, and a JavaScript number past that is
#: rounded -- an id that reads back as somebody else's.
MAX_ID = 2**53 - 1


class NameRefused(ValueError):
    """A name the web app will not take, with the sentence to show."""


@dataclass(frozen=True)
class Coach:
    """One person, as their cookie names them."""

    id: int
    name: str

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name}


def clean_name(raw: object) -> str:
    """A name as the web app takes it, or `NameRefused`."""
    name = raw.strip() if isinstance(raw, str) else ""
    if not name:
        raise NameRefused("Say what you want to be called.")
    if len(name) > NAME_LIMIT:
        raise NameRefused(f"A name is at most {NAME_LIMIT} characters.")
    return name


def issue(name: str) -> Coach:
    """
    A new person, under `name`.

    The id is random rather than the next of a sequence because nothing
    stores the last one: the cookie is the only place an id is written
    down, so a counter would start again at every restart and hand out
    ids that are already sitting in somebody's seat.
    """
    return Coach(secrets.randbelow(MAX_ID) + 1, clean_name(name))


def _sign(payload: str) -> str:
    return hmac.new(
        keys.secret(), payload.encode("ascii"), hashlib.sha256,
    ).hexdigest()


def encode(coach: Coach) -> str:
    """
    The cookie's value: the coach as base64 JSON, a dot, the HMAC. The
    base64 goes without its `=` padding, which a cookie would otherwise
    carry quoted.
    """
    payload = base64.urlsafe_b64encode(
        json.dumps(coach.to_dict(), separators=(",", ":")).encode("utf-8"),
    ).decode("ascii").rstrip("=")
    return f"{payload}.{_sign(payload)}"


def decode(value: Optional[str]) -> Optional[Coach]:
    """
    The coach a cookie names, or `None` -- no cookie, a signature this
    server did not make, or a payload that is not a coach.

    The signature is compared with `compare_digest`: the comparison is
    over a secret, and it is the one place the time it takes says
    anything.
    """
    if not value or "." not in value:
        return None
    payload, signature = value.rsplit(".", 1)
    try:
        expected = _sign(payload)
    except UnicodeEncodeError:
        return None
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        padded = payload + "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    coach_id, name = data.get("id"), data.get("name")
    if (
        not isinstance(coach_id, int)
        or isinstance(coach_id, bool)
        or not 0 < coach_id <= MAX_ID
        or not isinstance(name, str)
    ):
        return None
    try:
        return Coach(coach_id, clean_name(name))
    except NameRefused:
        return None


def coach_for(request: web.Request) -> Optional[Coach]:
    """Who sent this request, if they have said."""
    return decode(request.cookies.get(COOKIE))


def set_cookie(
    response: web.StreamResponse, request: web.Request, coach: Coach,
) -> None:
    """
    Hand `coach` to the browser. `Secure` when the request came over
    HTTPS -- behind a tunnel that is the forwarded scheme, which
    aiohttp reads only when told to, so a plain `http://` checkout on
    a laptop still gets a cookie it can send back.
    """
    response.set_cookie(
        COOKIE,
        encode(coach),
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="Lax",
        secure=request.secure,
        path="/",
    )


def clear_cookie(response: web.StreamResponse) -> None:
    """Leaving the app: forget the cookie. Nothing else is stored, so
    this is the whole of it -- the next request is nobody until it
    says a name again."""
    response.del_cookie(COOKIE, path="/")
