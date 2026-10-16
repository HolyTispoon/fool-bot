"""
The publisher's own record: `data/codex_pbd.json`.

What the site shows that the bot keeps nowhere else -- the turn's lines,
which `Codex.turn_lines` holds in memory alone, and every finished
turn's lines whole and the board it ended on -- plus which board keys
are already up, so a restart neither loses the log nor uploads a board
twice. **The bucket is the copy; this file is the source**
(docs/design/pbd-site.md, "The log is the publisher's file").

Keyed by `game_id`, never the game's number, which is counted per guild
and taken again after `/codex admin reset_channels`. Untracked runtime
state, like every file in `data/`. The file's handling is
`gamekit.storage`'s, with this module's own two failure flags: a save
never raises, a file that was there but could not be read is never
written over, and nothing makes `data/` on a load.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from gamekit import storage as games_file
from gamekit.storage import DATA_FOLDER

LOGGER = logging.getLogger(__name__)

PUBLISH_FILE = DATA_FOLDER / "codex_pbd.json"

#: The game's name in the file's log lines: "Could not save published
#: Codex games to ...".
NOUN = "published Codex"

# The files whose last save failed, and the files that were there but
# could not be read -- this record's own, not the games file's.
_save_failing: set[Path] = set()
_load_unreadable: set[Path] = set()


@dataclass
class PublishedGame:
    """
    One game as the publisher knows it.

    - `turn`, `heading`, `lines`: the current turn -- its number, its
      heading and its lines so far, the model's words with their tokens
      intact (`codex.formatting.turn_heading`, `Codex.turn_lines`).
    - `head`: the current turn's first lines, as the cog's
      `turn_heads` keeps them -- what an undo to the turn's start puts
      back, which a restart takes from the cog and not from here.
    - `history`: one dict per finished turn -- `turn`, `heading`,
      `lines`, `board` -- a dict rather than a tuple, so a later
      per-action history adds a field (docs/pbd-site.md, decision 5).
    - `board`: the current board's key; `uploaded`, every board key
      already in the bucket.
    - `history_version`: counted up whenever `history` changes, so a
      page fetches `history.json` only when `live.json` says so.
    - `imported`: whether the import of the old turns from the pins has
      run (docs/pbd-site.md, step 6).
    - `updated`: when the game last changed, ISO 8601 in UTC.
    """

    turn: Optional[int] = None
    heading: Optional[str] = None
    lines: list[str] = field(default_factory=list)
    head: list[str] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)
    board: Optional[str] = None
    uploaded: list[str] = field(default_factory=list)
    history_version: int = 0
    imported: bool = False
    updated: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "turn": self.turn,
            "heading": self.heading,
            "lines": list(self.lines),
            "head": list(self.head),
            "history": [dict(entry) for entry in self.history],
            "board": self.board,
            "uploaded": list(self.uploaded),
            "history_version": self.history_version,
            "imported": self.imported,
            "updated": self.updated,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PublishedGame":
        """Every field read with its default where it is missing or the
        wrong shape: a hand-edited or half-written entry loads as much as
        it holds."""
        def listed(key: str, kind: type) -> list:
            value = data.get(key)
            if not isinstance(value, list):
                return []
            return [item for item in value if isinstance(item, kind)]

        def optional(key: str, kind: type):
            value = data.get(key)
            return value if isinstance(value, kind) and not isinstance(value, bool) else None

        version = data.get("history_version")
        return cls(
            turn=optional("turn", int),
            heading=optional("heading", str),
            lines=listed("lines", str),
            head=listed("head", str),
            history=[dict(entry) for entry in listed("history", dict)],
            board=optional("board", str),
            uploaded=listed("uploaded", str),
            history_version=version if isinstance(version, int) and not isinstance(version, bool) else 0,
            imported=data.get("imported") is True,
            updated=optional("updated", str),
        )


class PublishRecord:
    """Every published game by `game_id`, and the file they are saved to."""

    def __init__(self, games: Optional[dict[str, PublishedGame]] = None,
                 path: Optional[Path] = None) -> None:
        self.games: dict[str, PublishedGame] = games if games is not None else {}
        self.path = path

    @property
    def file(self) -> Path:
        """`path`, or the bot's file -- resolved at call time, so a test
        that points `PUBLISH_FILE` at a tempdir moves the default too."""
        return PUBLISH_FILE if self.path is None else self.path

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "PublishRecord":
        record = cls(path=path)
        raw = games_file.read_games_file(
            record.file,
            noun=NOUN,
            logger=LOGGER,
            load_unreadable=_load_unreadable,
            make_folder=False,
        )
        if raw is None:
            return record
        if not isinstance(raw, dict):
            LOGGER.error("Ignoring %s: it is not a record of published games.", record.file)
            _load_unreadable.add(record.file)
            return record
        for game_id, entry in raw.items():
            if not isinstance(entry, dict):
                LOGGER.warning("Ignoring published Codex game %s: its entry is not a record.", game_id)
                continue
            record.games[game_id] = PublishedGame.from_dict(entry)
        return record

    def save(self) -> None:
        """Write the record out; logged and never raised on a failure."""
        games_file.save_games(
            self.games,
            self.file,
            noun=NOUN,
            logger=LOGGER,
            save_failing=_save_failing,
            load_unreadable=_load_unreadable,
        )

    def game(self, game_id: str) -> PublishedGame:
        """The game's entry, made empty where there is none yet."""
        return self.games.setdefault(game_id, PublishedGame())

    def drop(self, game_id: str) -> None:
        self.games.pop(game_id, None)
