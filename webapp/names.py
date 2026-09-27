"""
Which names are in use, so that no two people are called the same at
once.

The cookie (`webapp/identity.py`) is still who somebody is; this is
only which name each id holds right now, kept so that a name given out
or taken is one nobody else holds. It is the one place the web app
remembers a person rather than a room, and it holds no more than that:
an id, a name, and when the cookie carrying it was last set.

**A name is unique ignoring case** (`casefold`): "Ann" and "ann" read
as the same person in a room's sideline, so they are the same name
here.

**An entry lasts as long as its cookie can.** A cookie is kept for
`identity.COOKIE_MAX_AGE` from the last time it was set, so an entry
not set again within that is a name nobody can still be carrying, and
it is dropped on load. And the file is written under the secret the
cookies are signed with: a file written under another secret -- or
under a per-process one, which dies with the process and every cookie
with it -- names people who can no longer be anybody, and is started
afresh (`_fingerprint`).

A write that fails is logged and swallowed, as the rooms file's is:
losing the list costs, at worst, a name given twice until one of the
two renames, and failing somebody's click over it is worse.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from pathlib import Path
from typing import Callable, Optional

from gamesaves.d12ball.storage import DATA_FOLDER
from webapp import identity, keys

LOGGER = logging.getLogger(__name__)

#: The web app's names in use, beside its games: its own file.
WEB_NAMES_FILE = DATA_FOLDER / "d12ball_web_names.json"

#: How many made-up names to try before giving up on one being free.
#: With some ninety thousand numbers per pair, the first is all but
#: always free; the bound only stops a loop that could not end.
GUEST_TRIES = 50


class NameTaken(identity.NameRefused):
    """A name somebody else holds."""


def _fingerprint() -> str:
    """Which secret the file was written under, without writing the
    secret: an HMAC of a fixed word under it."""
    return hmac.new(keys.secret(), b"names", hashlib.sha256).hexdigest()


class Names:
    """
    Every name in use, over one file -- or none, for a test, which keeps
    it in memory and writes nothing.
    """

    def __init__(
        self,
        path: Optional[Path] = None,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.path = path
        self.clock = clock
        #: id -> (name, when its cookie was last set).
        self.held: dict[int, tuple[str, float]] = {}

    @classmethod
    def load(cls, path: Path, *, clock: Callable[[], float] = time.time) -> "Names":
        """The file as it was left, less what no cookie can still carry."""
        names = cls(path, clock=clock)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return names
        except (OSError, ValueError):
            LOGGER.warning(
                "The web names file %s could not be read; starting with "
                "no names in use.", path, exc_info=True,
            )
            return names
        if not isinstance(data, dict) or data.get("secret") != _fingerprint():
            return names
        oldest = clock() - identity.COOKIE_MAX_AGE
        for raw_id, entry in (data.get("names") or {}).items():
            try:
                name, set_at = str(entry["name"]), float(entry["set"])
                coach_id = int(raw_id)
            except (KeyError, TypeError, ValueError):
                continue
            if set_at >= oldest:
                names.held[coach_id] = (name, set_at)
        return names

    # -- Reading ------------------------------------------------------

    def name_of(self, coach_id: Optional[int]) -> Optional[str]:
        """The name `coach_id` holds, if any."""
        entry = self.held.get(coach_id) if coach_id is not None else None
        return None if entry is None else entry[0]

    def holder(self, name: str) -> Optional[int]:
        """Who holds `name`, ignoring case."""
        wanted = name.casefold()
        for coach_id, (held, _) in self.held.items():
            if held.casefold() == wanted:
                return coach_id
        return None

    def is_free_for(self, name: str, coach_id: int) -> bool:
        return self.holder(name) in (None, coach_id)

    # -- Writing ------------------------------------------------------

    def claim(self, coach_id: int, raw: object) -> str:
        """
        Give `coach_id` the name `raw`, cleaned, freeing whatever it
        held; `NameRefused` for a name the app will not take, `NameTaken`
        for one somebody else holds.
        """
        name = identity.clean_name(raw)
        if not self.is_free_for(name, coach_id):
            raise NameTaken("Somebody is already called that.")
        self.held[coach_id] = (name, self.clock())
        self.save()
        return name

    def claim_guest(self, coach_id: int) -> str:
        """A made-up name nobody holds, given to `coach_id`."""
        for _ in range(GUEST_TRIES):
            name = identity.guest_name()
            if self.holder(name) is None:
                return self.claim(coach_id, name)
        raise RuntimeError("No free made-up name was found.")

    def save(self) -> None:
        """Write the file, through a temporary one renamed over it.
        Never raises."""
        if self.path is None:
            return
        temporary = self.path.with_suffix(".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(
                json.dumps(
                    {
                        "secret": _fingerprint(),
                        "names": {
                            str(coach_id): {"name": name, "set": set_at}
                            for coach_id, (name, set_at) in sorted(self.held.items())
                        },
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            os.replace(temporary, self.path)
        except OSError:
            LOGGER.warning(
                "The web names file %s could not be written.",
                self.path,
                exc_info=True,
            )
