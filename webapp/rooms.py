"""
What the web app keeps about a room that is not the game's: who has
taken the admin role, and who has been in.

**Roles are the frontend's** (decision 1 of docs/web-app-next.md). Who
may kick a seat, and who is watching, is not a fact about the game, so
it is never on the game record -- the save format is the contract, and
a room role would be the first thing on it no rule reads. It lives in
the web app's own file, `data/d12ball_web_rooms.json`, beside its
games and in the same folder, written on every change and read at
start. A kick is this file's authorisation over the record's rule
(`vacate_seat`), the way a Discord helper's `manage_channels` gates a
click the record then judges.

"Seen" is everybody who has opened the room with a name. It is what
makes a seat taken *on arrival* rather than on every poll: the first
time somebody is seen, a free seat is theirs; somebody who has been
seen and left their seat stays an observer until they take one. The
seen who hold no seat are the room's observers.

A write that fails is logged and swallowed, as `save_games` swallows
its own (docs/design/gotchas.md, "the swallowed save"): losing who is
admin is a nuisance, and failing somebody's click over it is worse. A
room this file knows and the games file does not is dropped on load.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from gamesaves.d12ball.storage import DATA_FOLDER

LOGGER = logging.getLogger(__name__)

#: The web app's rooms, beside its games: its own file, never the save.
WEB_ROOMS_FILE = DATA_FOLDER / "d12ball_web_rooms.json"


@dataclass
class Room:
    admins: set[int] = field(default_factory=set)
    seen: set[int] = field(default_factory=set)

    def to_dict(self) -> dict:
        return {"admins": sorted(self.admins), "seen": sorted(self.seen)}

    @classmethod
    def from_dict(cls, data: dict) -> "Room":
        return cls(
            admins={int(one) for one in data.get("admins", ())},
            seen={int(one) for one in data.get("seen", ())},
        )


class Rooms:
    """
    Every room's own state, over one file -- or none, for a test, which
    keeps it in memory and writes nothing.
    """

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path
        self.rooms: dict[str, Room] = {}

    @classmethod
    def load(cls, path: Path, game_ids: Iterable[str]) -> "Rooms":
        """The file as it was left, for the games that still exist."""
        rooms = cls(path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return rooms
        except (OSError, ValueError):
            LOGGER.warning(
                "The web rooms file %s could not be read; starting with "
                "no admins.", path, exc_info=True,
            )
            return rooms
        known = set(game_ids)
        if isinstance(data, dict):
            for game_id, room in data.items():
                if game_id not in known or not isinstance(room, dict):
                    continue
                try:
                    rooms.rooms[game_id] = Room.from_dict(room)
                except (TypeError, ValueError):
                    LOGGER.warning(
                        "Dropped an unreadable web room %s.", game_id,
                    )
        return rooms

    def room(self, game_id: str) -> Room:
        room = self.rooms.get(game_id)
        if room is None:
            room = Room()
            self.rooms[game_id] = room
        return room

    def is_admin(self, game_id: str, coach_id: Optional[int]) -> bool:
        return coach_id is not None and coach_id in self.room(game_id).admins

    def make_admin(self, game_id: str, coach_id: int) -> None:
        room = self.room(game_id)
        if coach_id not in room.admins:
            room.admins.add(coach_id)
            self.save()

    def drop_admin(self, game_id: str, coach_id: int) -> None:
        room = self.room(game_id)
        if coach_id in room.admins:
            room.admins.discard(coach_id)
            self.save()

    def first_sight(self, game_id: str, coach_id: int) -> bool:
        """Mark `coach_id` as having been in the room; True the first
        time."""
        room = self.room(game_id)
        if coach_id in room.seen:
            return False
        room.seen.add(coach_id)
        self.save()
        return True

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
                        game_id: room.to_dict()
                        for game_id, room in self.rooms.items()
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            os.replace(temporary, self.path)
        except OSError:
            LOGGER.warning(
                "The web rooms file %s could not be written.",
                self.path,
                exc_info=True,
            )
