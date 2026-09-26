"""
What the people in a room have said to each other: one bounded list
of messages per room, in the web app's own file.

**It is frontend state, like the room roles** (`webapp/rooms.py`).
People talking beside a game is not a fact about the game, so it is
never on the game record, never read by the model, and never handed
to the service -- talking is not an action. It lives in
`data/d12ball_web_chat.json`, beside the web games and the rooms,
written on every post and read at start, so a restart no longer
empties it.

**It is not the model's voice.** A message is plain text: nothing in
it is rendered as markdown or as a token, and the page sets it with
`textContent`. A line that reads "X scored" is the journal's, which
already says it.

**It is bounded like the journal**: `CHAT_LENGTH` messages a room, the
oldest dropped. A message's id keeps counting past the bound, so a
page's `chat_since` cursor stays good.

A write that fails is logged and swallowed, as `save_games` and the
rooms file swallow theirs (docs/design/gotchas.md): losing a chat line
is a nuisance, failing somebody's post over it is worse. A room this
file knows and the games file does not is dropped on load.

Nothing here imports the model: a room is its game id and nothing
more.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from gamesaves.d12ball.storage import DATA_FOLDER

LOGGER = logging.getLogger(__name__)

#: The web app's chat, beside its games and rooms: its own file, never
#: the save.
WEB_CHAT_FILE = DATA_FOLDER / "d12ball_web_chat.json"

#: How many messages a room keeps -- the journal's bound.
CHAT_LENGTH = 200

#: The longest message taken, after stripping.
CHAT_MESSAGE_LIMIT = 500


class MessageRefused(ValueError):
    """A message that is empty or too long -- a 400, not a rule."""


def clean_text(text: object) -> str:
    """The text a message is posted as, or `MessageRefused`."""
    if not isinstance(text, str):
        raise MessageRefused("Say something.")
    text = text.strip()
    if not text:
        raise MessageRefused("Say something.")
    if len(text) > CHAT_MESSAGE_LIMIT:
        raise MessageRefused(
            f"A message is at most {CHAT_MESSAGE_LIMIT} characters.",
        )
    return text


@dataclass
class Message:
    """One thing a person said in the room, under the name on their
    cookie when they said it."""

    id: int
    coach_id: int
    name: str
    text: str
    at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "coach_id": self.coach_id,
            "name": self.name,
            "text": self.text,
            "at": self.at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Message":
        return cls(
            id=int(data["id"]),
            coach_id=int(data["coach_id"]),
            name=str(data["name"]),
            text=str(data["text"]),
            at=float(data["at"]),
        )


@dataclass
class Chat:
    """One room's messages, the newest last."""

    messages: deque = field(default_factory=lambda: deque(maxlen=CHAT_LENGTH))
    next_id: int = 1

    @property
    def latest(self) -> int:
        return self.next_id - 1

    def add(self, coach_id: int, name: str, text: str) -> Message:
        message = Message(self.next_id, coach_id, name, text)
        self.messages.append(message)
        self.next_id += 1
        return message

    def since(self, message_id: int) -> list[Message]:
        return [one for one in self.messages if one.id > message_id]

    def to_dict(self) -> dict:
        return {
            "next_id": self.next_id,
            "messages": [one.to_dict() for one in self.messages],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Chat":
        chat = cls()
        for one in data.get("messages", ()):
            chat.messages.append(Message.from_dict(one))
        last = chat.messages[-1].id if chat.messages else 0
        chat.next_id = max(int(data.get("next_id", 1)), last + 1)
        return chat


class Chats:
    """
    Every room's chat, over one file -- or none, for a test, which
    keeps it in memory and writes nothing.
    """

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path
        self.chats: dict[str, Chat] = {}

    @classmethod
    def load(cls, path: Path, game_ids: Iterable[str]) -> "Chats":
        """The file as it was left, for the rooms that still exist."""
        chats = cls(path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return chats
        except (OSError, ValueError):
            LOGGER.warning(
                "The web chat file %s could not be read; starting with "
                "no chat.", path, exc_info=True,
            )
            return chats
        known = set(game_ids)
        if isinstance(data, dict):
            for game_id, chat in data.items():
                if game_id not in known or not isinstance(chat, dict):
                    continue
                try:
                    chats.chats[game_id] = Chat.from_dict(chat)
                except (KeyError, TypeError, ValueError):
                    LOGGER.warning(
                        "Dropped an unreadable web chat %s.", game_id,
                    )
        return chats

    def chat(self, game_id: str) -> Chat:
        chat = self.chats.get(game_id)
        if chat is None:
            chat = Chat()
            self.chats[game_id] = chat
        return chat

    def post(self, game_id: str, coach_id: int, name: str, text: str) -> Message:
        """One message, written through. `text` is `clean_text`'s."""
        message = self.chat(game_id).add(coach_id, name, text)
        self.save()
        return message

    def forget(self, game_id: str) -> None:
        """A closed room's chat goes with it."""
        if self.chats.pop(game_id, None) is not None:
            self.save()

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
                        game_id: chat.to_dict()
                        for game_id, chat in self.chats.items()
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            os.replace(temporary, self.path)
        except OSError:
            LOGGER.warning(
                "The web chat file %s could not be written.",
                self.path,
                exc_info=True,
            )
