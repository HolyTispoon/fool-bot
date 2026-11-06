"""
`RuleRefusal`, the one exception a TNP rule says no with -- the leaf
the rest of the model imports, as `codex.game` and `d12ball.game` hold
theirs -- and `TnpGame`, the game record: its two seats, Blue and
Green, each taken by a person (TNP 1.2, the author, 2026-11-04 -- there
is no AI), the lobby's rules as methods refusing with `RuleRefusal`,
the advanced game a setting from the start, and the match once it has
started, held as its saved dict as Codex's record holds it.

The record's Discord ids -- the guild, the channel, the lobby's message
and the table's -- are optional, since a game is not a Discord thing;
step 5 opens a game's lobby and channel on Discord.
Nothing here imports the components at import time: they import
`RuleRefusal` from this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Mapping, Optional

from gamekit.saved import SavedField

if TYPE_CHECKING:
    from tnp.engine import RulesEngine


class RuleRefusal(ValueError):
    """
    The position refusing what was chosen, with the sentence to show.

    The driver lets this through as a `Refusal` and nothing else, so a
    frontend shows it and a bug propagates. **`cite` is the section of
    docs/tnp-rules.md that says no** ("TNP 6.5"), where one does.
    """

    def __init__(self, message: str, cite: Optional[str] = None) -> None:
        super().__init__(message)
        self.cite = cite


class GameStatus(str, Enum):
    LOBBY = "lobby"
    PLAYING = "playing"
    FINISHED = "finished"
    ABANDONED = "abandoned"


#: The two seats, in the order the lobby shows them (TNP 1.2).
SEAT_NAMES = ("blue", "green")


def _seats_in(data: Optional[Mapping[str, Any]]) -> dict[str, dict]:
    found = {seat: {"id": None, "name": None} for seat in SEAT_NAMES}
    for seat, held in (data or {}).items():
        if seat in found:
            found[seat] = {"id": held.get("id"), "name": held.get("name")}
    return found


def _seats_out(seats: Mapping[str, Mapping]) -> dict:
    return {seat: {"id": held["id"], "name": held["name"]} for seat, held in seats.items()}


def _status_in(value: Optional[str]) -> "GameStatus":
    return GameStatus(value or GameStatus.LOBBY.value)


@dataclass
class TnpGame:
    """
    A TNP game: who sits where, the lobby's settings, and the match.
    Every field is in `GAME_SAVED_FIELDS`, and a saved key is never
    renamed.
    """

    game_id: str
    game_number: int = 0
    guild_id: Optional[int] = None
    channel_id: Optional[int] = None
    #: The lobby's message, and once the game has started the table's --
    #: the one public message, the map, the turn and the phase and who
    #: has locked in (step 5 of docs/tnp-bot.md). Discord's ids, so
    #: optional like the channel's.
    message_id: Optional[int] = None
    table_message_id: Optional[int] = None
    status: GameStatus = GameStatus.LOBBY
    #: Each seat's person, `{"id", "name"}`, or nobody yet.
    seats: dict[str, dict] = field(default_factory=lambda: _seats_in(None))
    #: One person in both seats, to try the game alone.
    test_game: bool = False
    #: The advanced game (TNP 8), a setting from the start; only the
    #: basic game plays until step 9 of docs/tnp-bot.md.
    advanced: bool = False
    #: The match once started, as `MatchState.to_dict` writes it.
    match_state: Optional[dict] = None

    def to_dict(self) -> dict:
        return {row.name: row.stored(getattr(self, row.name)) for row in GAME_SAVED_FIELDS}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TnpGame":
        if "game_id" not in data:
            raise KeyError("game_id")
        return cls(**{row.name: row.restored(dict(data)) for row in GAME_SAVED_FIELDS})

    # -- Who sits where ----------------------------------------------------

    def seat_ids(self) -> list[int]:
        """The people seated -- `cogs.game_auth.game_participant_ids`
        reads a record through this."""
        return [held["id"] for held in self.seats.values() if held["id"] is not None]

    def seat_of(self, user_id: int) -> Optional[str]:
        """The seat a person holds, the first where a test game seats
        them twice; `None` for anybody else."""
        for seat in SEAT_NAMES:
            if self.seats[seat]["id"] == user_id:
                return seat
        return None

    def seats_of(self, user_id: int) -> tuple[str, ...]:
        return tuple(seat for seat in SEAT_NAMES if self.seats[seat]["id"] == user_id)

    @property
    def full(self) -> bool:
        return all(self.seats[seat]["id"] is not None for seat in SEAT_NAMES)

    # -- The lobby -----------------------------------------------------------

    def _in_lobby(self) -> None:
        if self.status is not GameStatus.LOBBY:
            raise RuleRefusal("This game has already started.")

    def take_seat(self, user_id: int, user_name: Optional[str], seat: Optional[str] = None) -> str:
        """Sit down -- in `seat`, or the first one free. A person holds
        one seat, except in a test game. Returns the seat taken."""
        self._in_lobby()
        if seat is not None and seat not in SEAT_NAMES:
            raise RuleRefusal("The seats are Blue and Green.")
        if not self.test_game and self.seat_of(user_id) is not None:
            raise RuleRefusal("You already hold a seat in this game.")
        free = [one for one in SEAT_NAMES if self.seats[one]["id"] is None]
        if seat is None:
            if not free:
                raise RuleRefusal("Both seats are taken.")
            seat = free[0]
        elif self.seats[seat]["id"] is not None:
            raise RuleRefusal(f"The {seat.title()} seat is taken.")
        self.seats[seat] = {"id": user_id, "name": user_name}
        return seat

    def leave(self, user_id: int) -> None:
        self._in_lobby()
        held = self.seats_of(user_id)
        if not held:
            raise RuleRefusal("You hold no seat in this game.")
        for seat in held:
            self.seats[seat] = {"id": None, "name": None}

    def set_advanced(self, advanced: bool) -> None:
        """The basic game or the advanced one -- the advanced game's
        technology cards are step 9's, so only the basic game may be
        chosen until then (TNP 8)."""
        self._in_lobby()
        if advanced:
            raise RuleRefusal("The advanced game, with the technology cards, is not built yet.", cite="TNP 8")
        self.advanced = False

    def start(self, engine: "RulesEngine") -> None:
        """Start the game: both seats taken, the opening position dealt
        (TNP 3), and turn 1's Infrastructure and Deployment open."""
        from tnp.components import opening

        self._in_lobby()
        if not self.full:
            raise RuleRefusal("Both seats need a player before the game starts.")
        self.match_state = opening(engine.catalog, advanced=self.advanced).to_dict()
        self.status = GameStatus.PLAYING

    def finish(self) -> None:
        if self.status is GameStatus.PLAYING:
            self.status = GameStatus.FINISHED

    def abandon(self) -> None:
        if self.status in (GameStatus.FINISHED, GameStatus.ABANDONED):
            raise RuleRefusal("This game is already over.")
        self.status = GameStatus.ABANDONED


GAME_SAVED_FIELDS: tuple[SavedField, ...] = (
    SavedField("game_id"),
    SavedField("game_number", default=0),
    SavedField("guild_id"),
    SavedField("channel_id"),
    SavedField("message_id"),
    SavedField("table_message_id"),
    SavedField("status", default=GameStatus.LOBBY, write=lambda status: status.value, read=_status_in),
    SavedField("seats", factory=lambda: _seats_in(None), write=_seats_out, read=_seats_in),
    SavedField("test_game", default=False),
    SavedField("advanced", default=False),
    SavedField("match_state"),
)
