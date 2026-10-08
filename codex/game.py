"""
The Codex game record: who sits where, the lobby's rules, and the match
once it has started.

`CodexGame` is `D12BallGame`'s shape (docs/design/codex.md, "The model,
before a line of Discord"): its three Discord ids optional, since a game
is not a Discord thing, and its seat fields -- `player_1_id`,
`player_2_id`, their names, `observer_ids`, `test_game` -- spelt exactly
as D12 Ball spells them, so the authorisation predicates step 3 moves
into a shared module read either record. Every rule about the lobby is
a method that refuses with `RuleRefusal`.

This module is the leaf of the Codex model: `codex.components` imports
`RuleRefusal` from here, so nothing here imports the components. The
match is held as its saved dict, as D12 Ball's record holds it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from codex.engine import RulesEngine


class RuleRefusal(ValueError):
    """
    The position refusing what was chosen, with the sentence to show.

    The one exception a Codex rule says no with, as `d12ball.game`'s is
    for D12 Ball: the driver and the service let this through and
    nothing else, so a frontend shows it and a bug propagates.

    **`cite` is what says no**, where something does: a page of the
    Unofficial Manual Rewrite (`"UMR p. 6"`) or a card's slug, the way
    D12 Ball's refusal carries a Law. Optional: a stale click or the
    lobby's bookkeeping cites nothing rather than guessing.
    """

    def __init__(self, message: str, cite: Optional[str] = None) -> None:
        super().__init__(message)
        self.cite = cite


class GameStatus(str, Enum):
    LOBBY = "lobby"
    PLAYING = "playing"
    FINISHED = "finished"
    ABANDONED = "abandoned"


#: The two specs of the basic game, which are the lobby's two seats.
BASIC_SPECS = ("bashing", "finesse")

#: How the board image lays the two mats out: the second player's above
#: the first player's, or the two side by side -- the game's choice, so
#: everyone sees the same picture (docs/codex-bot.md, decision 5).
BOARD_LAYOUTS = ("stacked", "side_by_side")


@dataclass
class CodexGame:
    game_id: str
    game_number: int

    guild_id: Optional[int] = field(default=None, kw_only=True)
    channel_id: Optional[int] = field(default=None, kw_only=True)
    message_id: Optional[int] = field(default=None, kw_only=True)
    #: The current turn's public message, which step 3 posts and edits.
    turn_message_id: Optional[int] = field(default=None, kw_only=True)

    player_1_id: Optional[int] = None
    player_2_id: Optional[int] = None
    player_1_name: Optional[str] = None
    player_2_name: Optional[str] = None
    test_game: bool = False
    observer_ids: list[int] = field(default_factory=list)

    #: Seat number to spec ("bashing", "finesse"). Saved with string
    #: keys, since JSON has no other kind.
    player_specs: dict[int, str] = field(default_factory=dict)
    status: GameStatus = GameStatus.LOBBY
    #: `MatchState.to_dict()`; `None` until Start.
    match_state: Optional[dict] = None
    #: One of `BOARD_LAYOUTS`; the turn message's **Swap view** flips it.
    #: A record field, not the match's: it is how the table is looked
    #: at, and an undo does not take it back.
    board_layout: str = "stacked"

    # -- Reading the seats -------------------------------------------

    def seat_of(self, user_id: Optional[int]) -> Optional[int]:
        """The seat `user_id` holds, 1 or 2, or `None`."""
        if user_id is None:
            return None
        if user_id == self.player_1_id:
            return 1
        if user_id == self.player_2_id:
            return 2
        return None

    def seat_name(self, seat: int) -> Optional[str]:
        return self.player_1_name if seat == 1 else self.player_2_name

    # -- The lobby ---------------------------------------------------

    def _require_lobby(self) -> None:
        if self.status is not GameStatus.LOBBY:
            raise RuleRefusal("This game has already started.")

    def take_seat(self, user_id: int, user_name: Optional[str], spec: str) -> int:
        """
        Sit down to play `spec`. A seated player choosing the other spec
        moves to it while it is free. The first to sit holds seat 1.
        Returns the seat taken.
        """
        self._require_lobby()
        spec = spec.lower()
        if spec not in BASIC_SPECS:
            raise RuleRefusal(f"The basic game is Bashing against Finesse, not {spec}.")
        holder = next(
            (seat for seat, held in self.player_specs.items() if held == spec), None,
        )
        mine = self.seat_of(user_id)
        if holder is not None and holder == mine:
            raise RuleRefusal("You are already playing that side.")
        if holder is not None:
            raise RuleRefusal("Somebody is already playing that side.")
        if mine is not None:
            self.player_specs[mine] = spec
            return mine
        if self.player_1_id is None:
            seat = 1
        elif self.player_2_id is None:
            seat = 2
        else:
            raise RuleRefusal("Both seats are taken -- a game is two players.")
        if seat == 1:
            self.player_1_id, self.player_1_name = user_id, user_name
        else:
            self.player_2_id, self.player_2_name = user_id, user_name
        self.player_specs[seat] = spec
        if user_id in self.observer_ids:
            self.observer_ids.remove(user_id)
        return seat

    def leave(self, user_id: int) -> None:
        """Give up a seat in the lobby."""
        self._require_lobby()
        seat = self.seat_of(user_id)
        if seat is None:
            raise RuleRefusal("You are not seated in this lobby.")
        if seat == 1:
            self.player_1_id, self.player_1_name = None, None
        else:
            self.player_2_id, self.player_2_name = None, None
        self.player_specs.pop(seat, None)

    def may_start(self) -> bool:
        """Both seats taken, each with its spec, in a lobby."""
        return (
            self.status is GameStatus.LOBBY
            and self.player_1_id is not None
            and self.player_2_id is not None
            and set(self.player_specs) == {1, 2}
        )

    def start(self, engine: "RulesEngine") -> None:
        """Deal the opening position: the engine shuffles, deals and
        picks who goes first (UMR p. 3)."""
        self._require_lobby()
        if not self.may_start():
            raise RuleRefusal("Both seats have to be taken before the game can start.")
        match = engine.new_match((self.player_specs[1], self.player_specs[2]))
        self.match_state = match.to_dict()
        self.status = GameStatus.PLAYING

    def set_board_layout(self, layout: str) -> None:
        """Lay the board out `layout` -- refused for one there is not,
        or once the game is over."""
        if layout not in BOARD_LAYOUTS:
            raise RuleRefusal(f"The board is laid out stacked or side by side, not {layout}.")
        if self.status is not GameStatus.PLAYING:
            raise RuleRefusal("Only a game being played has a board to lay out.")
        self.board_layout = layout

    def abandon(self) -> None:
        """End a game nobody is going to finish. Refused for one already
        over; the record stays, so its number stays taken."""
        if self.status in (GameStatus.FINISHED, GameStatus.ABANDONED):
            raise RuleRefusal("This game is already over.")
        self.status = GameStatus.ABANDONED

    # -- Saving --------------------------------------------------------

    def to_dict(self) -> dict:
        data = asdict(self)
        data["status"] = self.status.value
        data["player_specs"] = {str(seat): spec for seat, spec in self.player_specs.items()}
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "CodexGame":
        data = dict(data)
        data["status"] = GameStatus(data.get("status", GameStatus.LOBBY.value))
        data["player_specs"] = {
            int(seat): spec for seat, spec in (data.get("player_specs") or {}).items()
        }
        data["observer_ids"] = list(data.get("observer_ids") or [])
        if data.get("board_layout") not in BOARD_LAYOUTS:
            data["board_layout"] = "stacked"
        return cls(**data)
