"""
Who is reading a web page: a name, an id, and a signed cookie.

Discord answers this for the bot -- an interaction carries the account
that clicked. A browser carries nothing, so the web app issues its own:
on a first visit the server makes up a name (`guest_name`,
`bright_otter_48213`) and answers with a `Coach` in a cookie signed
under `keys.secret()`; the reader may change the name after. Coming back with
the cookie is being the same person; another device is another cookie,
which is why a seat is left and taken again rather than shared
(decision 1 of docs/web-app-next.md).

**The cookie is who somebody is**: the id and the name in it, and an
HMAC that says this server wrote them. There is no table of coaches to
migrate, back up or leak, and the game record holds the id in a seat
the way it holds a Discord id. The one thing kept beside it is which
name each id holds right now (`webapp/names.py`), so that no two people
are called the same at once; that file is the reading of a name, and
the cookie's copy is only what it was when the cookie was set. With
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
import ipaddress
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


#: What a made-up name is built from: a kind word and a creature, so a
#: stranger's name reads as a friendly one. Short enough that the
#: longest pair and its number stay under `NAME_LIMIT`.
GUEST_ADJECTIVES = (
    "brave", "bright", "bold", "calm", "cheery", "clever", "cosmic",
    "daring", "dapper", "eager", "fearless", "gallant", "gentle",
    "glad", "golden", "happy", "hardy", "honest", "jolly", "keen",
    "kind", "lively", "lucky", "merry", "mighty", "nimble", "noble",
    "plucky", "proud", "quick", "radiant", "sharp", "shiny", "snappy",
    "spry", "steady", "stellar", "sunny", "swift", "trusty", "valiant",
    "wise", "witty", "zesty",
)
GUEST_CREATURES = (
    "badger", "bear", "beaver", "bison", "falcon", "ferret", "fox",
    "gecko", "heron", "ibex", "jaguar", "koala", "lemur", "lynx",
    "moose", "narwhal", "newt", "ocelot", "otter", "owl", "panda",
    "puffin", "raven", "stoat", "tapir", "tiger", "walrus", "wombat",
    "basilisk", "centaur", "dragon", "dryad", "goblin", "golem",
    "griffin", "hydra", "kraken", "phoenix", "pixie", "sphinx",
    "sprite", "troll", "unicorn", "wyvern", "yeti",
)


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


def guest_name() -> str:
    """
    A name for somebody who has not given one: `adjective_creature_#####`,
    the number always five digits. Drawn from `secrets` rather than the
    engine's `rng`, which is the game's and is seeded by the tests; a
    name is nothing the game draws. Whether somebody already holds it
    is `webapp/names.py`'s question, which draws again when they do.
    """
    return "_".join((
        secrets.choice(GUEST_ADJECTIVES),
        secrets.choice(GUEST_CREATURES),
        str(10000 + secrets.randbelow(90000)),
    ))


def issue_id() -> int:
    """
    A new person's id. Random rather than the next of a sequence
    because nothing stores the last one: the cookie is the only place
    an id is written down, so a counter would start again at every
    restart and hand out ids that are already sitting in somebody's
    seat.
    """
    return secrets.randbelow(MAX_ID) + 1


def issue(name: str) -> Coach:
    """A new person, under `name`."""
    return Coach(issue_id(), clean_name(name))


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


def unverified_claim(value: Optional[str]) -> Optional[dict]:
    """
    What a cookie `decode` refused says it is, read without its
    signature -- for the log line that says who was lost, and never
    for anything else: an unsigned claim is anybody's to write.
    `None` where there is no cookie or nothing readable in it.
    """
    if not value or "." not in value:
        return None
    payload = value.rsplit(".", 1)[0]
    try:
        padded = payload + "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return {"id": data.get("id"), "name": data.get("name")}


def _from_this_machine(request: web.Request) -> bool:
    """Whether the request came from a process on this machine -- the
    tunnel's own client, when there is one."""
    try:
        address = ipaddress.ip_address(request.remote or "")
    except ValueError:
        return False
    mapped = getattr(address, "ipv4_mapped", None)
    return (mapped or address).is_loopback


def _forwarded_scheme(request: web.Request) -> Optional[str]:
    """The scheme the browser used, as the tunnel on this machine says
    it in `X-Forwarded-Proto` -- or `None` where nothing on this
    machine said (see `came_over_https` for why only this machine)."""
    if not _from_this_machine(request):
        return None
    forwarded = request.headers.get("X-Forwarded-Proto", "")
    # A chain of proxies writes a list; the first is the browser's.
    return forwarded.split(",")[0].strip().lower() or None


def came_over_plain_http(request: web.Request) -> bool:
    """
    Whether the browser reached the tunnel over plain `http://` -- which
    the tunnel carries rather than refuses. The cookie is `Secure`, so a
    browser there sends none, and would be handed a second person in the
    same browser; `webapp/server.py`'s `https_only` sends it to the
    `https://` address instead. A request with no tunnel in front of it
    (a checkout on a laptop, over `http://localhost`) is none of this.
    """
    return not request.secure and _forwarded_scheme(request) == "http"


def came_over_https(request: web.Request) -> bool:
    """
    Whether the browser reached us over HTTPS.

    Behind a tunnel it did, but the last hop -- the tunnel's client on
    this machine to this process -- is plain HTTP, so `request.secure`
    says no. The tunnel says what the browser used in
    `X-Forwarded-Proto`, and that header is believed **only from this
    machine**: anybody who can reach the port directly can write it,
    and with `FOOLBOT_WEB_HOST=127.0.0.1` nobody but the tunnel can.
    It only ever upgrades; a request that is HTTPS already stays so.
    See docs/design/collaboration.md, "Only ever over HTTPS".
    """
    if request.secure:
        return True
    return _forwarded_scheme(request) == "https"


def set_cookie(
    response: web.StreamResponse, request: web.Request, coach: Coach,
) -> None:
    """
    Hand `coach` to the browser. `Secure` when the browser came over
    HTTPS (`came_over_https`, which reads the tunnel's forwarded
    scheme), so a plain `http://` checkout on a laptop still gets a
    cookie it can send back.
    """
    response.set_cookie(
        COOKIE,
        encode(coach),
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="Lax",
        secure=came_over_https(request),
        path="/",
    )
