"""
What has been said in each web game: the journal a page's log is
read from, and the web app's own file it survives a restart in.

**It is the frontend's memory and nothing to do with the save.**
`MatchState.events` is the game's record of what happened, and nothing
in the game may read it to decide a rule; the journal is the run of
messages a page shows, in the order a coach reads them. It lives in
`data/d12ball_web_journal.json` (`WEB_JOURNAL_FILE`), beside the web
games, the rooms and the chat, written on every `add` and read at
start (step 10 of docs/web-app-next.md), so a room's transcript is as
good after a restart as its link already was. It is never on the game
record: the save format is the contract, and a transcript is not a
fact about the game.

**An entry is kept whole**: its words, the position the run stopped at
where it stopped (which `board.png?entry=` serves, though no page
draws it), and its roll's numbers as the wire writes them, which the
question box draws the dice from. So is the journal's `showing_roll`,
so the dice a restart finds up are still up after it, and its
`board_version`, so a browser that kept a board under its URL is not
handed that picture for a different position after a restart.

**It is bounded like the chat**: `JOURNAL_LENGTH` entries a game, the
oldest dropped, and an entry's id keeps counting past the bound, so a
page's `since` cursor stays good.

A write that fails is logged and swallowed, as `save_games`, the
rooms file and the chat swallow theirs (docs/design/gotchas.md, "the
swallowed save"): losing a transcript line is a nuisance, and failing
somebody's click over it is worse. A game this file knows and the
games file does not is dropped on load.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional

from d12ball.flow import FollowOnStep
from d12ball.game import D12BallGame
from gamesaves.d12ball.service import GameResult
from gamesaves.d12ball.storage import DATA_FOLDER
from webapp import pictures
from webapp.present import render_text

LOGGER = logging.getLogger(__name__)

#: The web app's journal, beside its games, rooms and chat: its own
#: file, never the save.
WEB_JOURNAL_FILE = DATA_FOLDER / "d12ball_web_journal.json"

#: How much of a game's narration a page can scroll back through. A
#: browser that has been open all game holds the rest; this is what a
#: page that has just been opened is given, and what a coach coming
#: back to one catches up on.
JOURNAL_LENGTH = 200


def roll_of(detail: object) -> Optional[dict]:
    """
    A result's `detail` as the journal keeps it: the roll's numbers as
    the wire writes them (`to_dict`), where it is a roll the page has a
    picture for, and `None` for anything else. A dict is what survives
    the file, and it is what the dice are drawn from either way.
    """
    if isinstance(detail, Mapping):
        written = dict(detail)
    else:
        to_dict = getattr(detail, "to_dict", None)
        if to_dict is None:
            return None
        written = to_dict()
    return written if pictures.dice_shape(written) is not None else None


@dataclass
class Entry:
    """One thing that was said, as the journal keeps it."""

    id: int
    lines: tuple[str, ...]
    #: The position the frontend stopped to draw, where it did, as the
    #: save's own shape (`Narration.board`).
    board: Optional[dict] = None
    new_play: bool = False
    #: When it was said, as a Discord message carries its time.
    at: float = field(default_factory=time.time)
    #: The roll these lines are the answer to, where there was one --
    #: the result's `detail` (the answer's own) or the group's (an AI's
    #: answer) -- as its wire dict (`roll_of`), for `detail/{entry}.png`.
    detail: Optional[dict] = None

    def to_dict(self, game: D12BallGame) -> dict:
        """The entry as the page's log reads it: its words, and the
        dice where it was a roll. The log draws no board -- the live
        board is beside it -- so the position an entry stopped at is
        kept for `board.png?entry=` and not sent. The dice are drawn:
        they are the roll, where the board is only where it happened.
        `dice` is the roll's shape where the page has a picture for
        it, and `dice_after` how many of the lines are read above
        it."""
        shape = pictures.dice_shape(self.detail)
        return {
            "id": self.id,
            "lines": [render_text(game, line) for line in self.lines],
            "board": self.board is not None,
            "new_play": self.new_play,
            "at": self.at,
            "dice": shape,
            "dice_after": pictures.LINES_BEFORE_DICE.get(shape, 0),
        }

    def saved(self) -> dict:
        """The entry as the journal's file keeps it: every field, the
        lines with their tokens as the model wrote them."""
        return {
            "id": self.id,
            "lines": list(self.lines),
            "board": self.board,
            "new_play": self.new_play,
            "at": self.at,
            "detail": self.detail,
        }

    @classmethod
    def from_saved(cls, data: Mapping[str, Any]) -> "Entry":
        board = data.get("board")
        detail = data.get("detail")
        return cls(
            id=int(data["id"]),
            lines=tuple(str(line) for line in data.get("lines", ())),
            board=dict(board) if isinstance(board, Mapping) else None,
            new_play=bool(data.get("new_play", False)),
            at=float(data["at"]),
            detail=roll_of(detail) if isinstance(detail, Mapping) else None,
        )


@dataclass
class Journal:
    """
    What has been said in one game -- see the module docstring for why
    it is the frontend's and not the save's.
    """

    entries: deque = field(
        default_factory=lambda: deque(maxlen=JOURNAL_LENGTH),
    )
    next_id: int = 1
    #: Bumped whenever anything a board draws has moved, so a page's
    #: `<img>` asks for the new one rather than the browser's copy.
    board_version: int = 1
    #: The entry whose dice the question box shows: the last roll of
    #: the latest result, or `None` once a result has come after it
    #: with no roll in it, whether or not it said anything -- a roll's
    #: dice stay up until the next thing happens in the game, by either
    #: coach or the AI (`WebApp._state`'s `roll`).
    showing_roll: Optional[int] = None

    def add(
        self,
        result: GameResult,
        challenge: Optional[Callable[[str], str]] = None,
    ) -> None:
        """One result, as the page reads it: the answer's own lines,
        then every group the run closed. `challenge` words the matchup
        a walk-in names, from the challenger's id: on Discord the walk-in
        is followed by the challenge image, and the log draws no
        picture, so it says what the picture shows."""
        rolled = None
        for lines, group, detail in self._blocks(result):
            if (
                group is not None
                and group.step is FollowOnStep.AUTO_RESOLVE_CHALLENGER
                and challenge is not None
                and "challenger_id" in group.arguments
            ):
                lines = [
                    *filter(None, lines),
                    challenge(group.arguments["challenger_id"]),
                ]
            if not lines and group is None and detail is None:
                continue
            roll = roll_of(detail)
            self.entries.append(
                Entry(
                    self.next_id,
                    tuple(lines),
                    board=None if group is None else group.board,
                    new_play=False if group is None else group.new_play,
                    detail=roll,
                ),
            )
            if roll is not None:
                rolled = self.next_id
            self.next_id += 1
        self.showing_roll = rolled
        if result.board_changed or any(
            group.board is not None for group in result.groups
        ):
            self.board_version += 1

    def _blocks(self, result: GameResult):
        """
        What one result is worth reading, in the order it was said:
        the answer's own lines, every group the run closed, and what
        it was still carrying when it stopped.

        **The last of those opens the prompt**, and the Discord cog
        posts it *with* the prompt as one message (`render_prompt`'s
        `lead_in`). A page has no reason to: the ask is a panel of its
        own under the board, so the lines go where every other line
        goes and the panel says what is being asked. Batching is the
        frontend's (principle 8), and this is the frontend.

        **A roll rides on the lines that answer it**: the answer's own
        (the result's `detail`), or an AI's answer inside the run (its
        group's). It is kept even with no line beside it, since the
        dice are what happened.
        """
        if result.answer or result.detail is not None:
            yield list(result.answer), None, result.detail
        for group in result.groups:
            yield list(group.lines), group, group.detail
        if result.narration:
            yield list(result.narration), None, None

    def since(self, entry_id: int, game: D12BallGame) -> list[dict]:
        return [
            entry.to_dict(game)
            for entry in self.entries
            if entry.id > entry_id
        ]

    def board_for(self, entry_id: int) -> Optional[dict]:
        entry = self.entry(entry_id)
        return None if entry is None else entry.board

    def entry(self, entry_id: int) -> Optional[Entry]:
        for entry in self.entries:
            if entry.id == entry_id:
                return entry
        return None

    def saved(self) -> dict:
        return {
            "next_id": self.next_id,
            "board_version": self.board_version,
            "showing_roll": self.showing_roll,
            "entries": [entry.saved() for entry in self.entries],
        }

    @classmethod
    def from_saved(cls, data: Mapping[str, Any]) -> "Journal":
        journal = cls()
        for one in data.get("entries", ()):
            journal.entries.append(Entry.from_saved(one))
        last = journal.entries[-1].id if journal.entries else 0
        journal.next_id = max(int(data.get("next_id", 1)), last + 1)
        journal.board_version = max(int(data.get("board_version", 1)), 1)
        showing = data.get("showing_roll")
        # Only a roll still in hand, and still a roll: an entry the
        # bound dropped has no dice to draw.
        entry = None if showing is None else journal.entry(int(showing))
        journal.showing_roll = (
            entry.id if entry is not None and entry.detail is not None
            else None
        )
        return journal


class Journals:
    """
    Every web game's journal, over one file -- or none, for a test,
    which keeps them in memory and writes nothing.
    """

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path
        self.journals: dict[str, Journal] = {}

    @classmethod
    def load(cls, path: Path, game_ids: Iterable[str]) -> "Journals":
        """The file as it was left, for the games that still exist."""
        journals = cls(path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return journals
        except (OSError, ValueError):
            LOGGER.warning(
                "The web journal file %s could not be read; starting with "
                "no history.", path, exc_info=True,
            )
            return journals
        known = set(game_ids)
        if isinstance(data, dict):
            for game_id, journal in data.items():
                if game_id not in known or not isinstance(journal, dict):
                    continue
                try:
                    journals.journals[game_id] = Journal.from_saved(journal)
                except (KeyError, TypeError, ValueError):
                    LOGGER.warning(
                        "Dropped an unreadable web journal %s.", game_id,
                    )
        return journals

    def journal(self, game_id: str) -> Journal:
        journal = self.journals.get(game_id)
        if journal is None:
            journal = Journal()
            self.journals[game_id] = journal
        return journal

    def add(
        self,
        game_id: str,
        result: GameResult,
        challenge: Optional[Callable[[str], str]] = None,
    ) -> None:
        """One result into that game's journal, written through."""
        self.journal(game_id).add(result, challenge=challenge)
        self.save()

    def forget(self, game_id: str) -> None:
        """A closed room's journal goes with it."""
        if self.journals.pop(game_id, None) is not None:
            self.save()

    def save(self) -> None:
        """Write the file, through a temporary one renamed over it.
        Never raises: a journal that cannot be written costs the
        transcript after a restart, never the click."""
        if self.path is None:
            return
        temporary = self.path.with_suffix(".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(
                json.dumps(
                    {
                        game_id: journal.saved()
                        for game_id, journal in self.journals.items()
                    },
                ),
                encoding="utf-8",
            )
            os.replace(temporary, self.path)
        except (OSError, TypeError, ValueError):
            LOGGER.warning(
                "The web journal file %s could not be written.",
                self.path,
                exc_info=True,
            )
