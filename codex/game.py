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


#: The two specs of the first basic game (UMR p. 3), the neutral heroes.
BASIC_SPECS = ("bashing", "finesse")

#: The two games the rulebook names (UMR p. 3): one hero a side, or
#: three -- and how many heroes a seat holds in each.
MODES = ("basic", "standard")
HEROES_PER_SEAT = {"basic": 1, "standard": 3}

#: How the board image lays the two panels out: stacked, seen from the
#: active player's side with the other player's panel turned to face
#: them, or the two side by side -- the game's choice, so everyone sees
#: the same picture (docs/codex-bot.md, decision 5).
BOARD_LAYOUTS = ("stacked", "side_by_side")

#: Where on Discord the game is played (docs/design/codex.md, "The lobby
#: and the channel"): a channel of its own under Codex Games, which the
#: bot renames and archives; a thread it opened in the channel the lobby
#: was asked for in, where it may not make channels; or that channel
#: itself, where it may make neither, which it never renames or moves.
VENUES = ("channel", "thread", "here")


@dataclass
class CodexGame:
    game_id: str
    game_number: int

    guild_id: Optional[int] = field(default=None, kw_only=True)
    channel_id: Optional[int] = field(default=None, kw_only=True)
    message_id: Optional[int] = field(default=None, kw_only=True)
    #: The current turn's public message, which step 3 posts and edits.
    turn_message_id: Optional[int] = field(default=None, kw_only=True)
    #: The turn message before it, standing as that turn's summary: what
    #: an undo to the start of the previous turn edits back and pins
    #: again. `None` in a save older than step 4, and after that undo.
    previous_turn_message_id: Optional[int] = field(default=None, kw_only=True)
    #: One of `VENUES`: what `channel_id` is. "channel" in a save older
    #: than the thread and the in-place lobby, which knew no other.
    venue: str = field(default="channel", kw_only=True)

    player_1_id: Optional[int] = None
    player_2_id: Optional[int] = None
    player_1_name: Optional[str] = None
    player_2_name: Optional[str] = None
    test_game: bool = False
    observer_ids: list[int] = field(default_factory=list)

    #: The basic game or the standard one (`MODES`): one hero a seat,
    #: or three. "basic" in a save older than step 10.
    mode: str = "basic"
    #: Seat number to its heroes, as their specs, in the order chosen --
    #: one in the basic game, three in the standard one. A hero is its
    #: spec's one hero (`CardCatalog.hero_for`), so a spec names a hero
    #: and nothing is saved twice. Saved with string keys, since JSON
    #: has no other kind; a save older than step 10 holds one spec as a
    #: string, read as a list of one.
    player_specs: dict[int, list[str]] = field(default_factory=dict)
    #: Seat number to its starting deck's colour ("neutral", "red"):
    #: the first hero's, as soon as the seat has heroes (UMR pp. 3-4;
    #: `_settle_deck`). A lobby saved before 2026-10-10 may hold a
    #: player's choice of another of their heroes' colours, which stands.
    #: A save older than step 10 has none, and every seat it seats
    #: plays the neutral deck.
    player_decks: dict[int, str] = field(default_factory=dict)
    status: GameStatus = GameStatus.LOBBY
    #: `MatchState.to_dict()`; `None` until Start.
    match_state: Optional[dict] = None
    #: One of `BOARD_LAYOUTS`; the turn message's **Swap view** flips it.
    #: A record field, not the match's: it is how the table is looked
    #: at, and an undo does not take it back.
    board_layout: str = "stacked"

    #: The public line a finished game ended on -- the winner and the
    #: final board, with **Rematch** under it -- which the startup
    #: sweep re-arms while no rematch has been opened. `None` until the
    #: game is over, and in a save older than step 8.
    final_message_id: Optional[int] = field(default=None, kw_only=True)
    #: The rematch opened from this finished game, so a second press
    #: finds it rather than opening another.
    rematch_game_id: Optional[str] = None
    #: The finished game this lobby is the rematch of, and the teams it
    #: was played with by seat -- each seat's heroes as specs -- and
    #: their decks: what **Keep heroes** keeps. Empty for a lobby
    #: `/codex lobby` opened.
    rematch_of: Optional[str] = None
    rematch_specs: dict[int, list[str]] = field(default_factory=dict)
    rematch_decks: dict[int, str] = field(default_factory=dict)
    #: The seats whose player has pressed **Keep heroes** in a rematch's
    #: lobby; the heroes are kept only while both have.
    kept_heroes: list[int] = field(default_factory=list)

    # -- Reading the seats -------------------------------------------

    def seats_of(self, user_id: Optional[int]) -> tuple[int, ...]:
        """Every seat `user_id` holds: one, or both in a test game."""
        if user_id is None:
            return ()
        return tuple(
            seat for seat, held in ((1, self.player_1_id), (2, self.player_2_id))
            if held == user_id
        )

    def seat_of(self, user_id: Optional[int]) -> Optional[int]:
        """The seat `user_id` holds, 1 or 2, or `None` -- the first of
        the two where a test game seats one person in both (`seats_of`)."""
        if user_id is None:
            return None
        if user_id == self.player_1_id:
            return 1
        if user_id == self.player_2_id:
            return 2
        return None

    def seat_for(self, user_id: Optional[int], active: int) -> Optional[int]:
        """
        The seat a click of `user_id`'s acts for: their seat -- or, in a
        test game where they hold both, the one whose turn it is.
        """
        seats = self.seats_of(user_id)
        if active in seats:
            return active
        return seats[0] if seats else None

    def seat_name(self, seat: int) -> Optional[str]:
        return self.player_1_name if seat == 1 else self.player_2_name

    # -- The lobby ---------------------------------------------------

    def _require_lobby(self) -> None:
        if self.status is not GameStatus.LOBBY:
            raise RuleRefusal("This game has already started.")

    @property
    def heroes_per_seat(self) -> int:
        """How many heroes a seat holds: one in the basic game, three in
        the standard one (UMR p. 3)."""
        return HEROES_PER_SEAT[self.mode]

    def set_mode(self, mode: str) -> None:
        """
        Play the basic game or the standard one. The lobby's until Start;
        every seat keeps its player and loses its heroes, since a team of
        one is no team of three -- each picks again. In a rematch's lobby
        the last game's teams go with them, and so does **Keep heroes**.
        """
        self._require_lobby()
        if mode not in MODES:
            raise RuleRefusal(f"A Codex game is basic or standard, not {mode}.", cite="UMR p. 3")
        if mode == self.mode:
            return
        self.mode = mode
        self.player_specs = {}
        self.player_decks = {}
        self.rematch_specs = {}
        self.rematch_decks = {}
        self.kept_heroes = []

    def _check_team(self, specs: list[str]) -> list[str]:
        """
        A seat's heroes, as specs, checked against the lobby's rules
        (UMR pp. 3-4): as many as the game takes, each a hero, no hero
        twice, and every one of a colour the bot has landed.
        """
        from codex.cards import LANDED_COLORS, catalog

        cards = catalog()
        wanted = self.heroes_per_seat
        if len(specs) != wanted:
            game = "the basic game" if self.mode == "basic" else "a standard game"
            count = "one hero" if wanted == 1 else f"{wanted} heroes"
            raise RuleRefusal(f"In {game} each player chooses {count}.", cite="UMR p. 3")
        if len(set(specs)) != len(specs):
            raise RuleRefusal("A team's heroes are three different heroes.", cite="UMR p. 3")
        for spec in specs:
            try:
                hero = cards.hero_for(spec)
            except KeyError:
                raise RuleRefusal(f"There is no hero of {spec}.") from None
            color = (hero.color or "").lower()
            if color not in LANDED_COLORS:
                # No page to cite: the rulebook allows it, this bot does
                # not play the colour yet (docs/codex-bot.md, steps 10-13).
                raise RuleRefusal(
                    f"{hero.name} is a {hero.color} hero, and {hero.color} is not in this bot yet."
                )
        return specs

    def deck_choices(self, seat: int) -> tuple[str, ...]:
        """
        The starting decks `seat` may take: its heroes' colours, in the
        order the heroes were chosen (UMR pp. 3-4) -- a basic game's
        one, a standard game's one to three, the neutral heroes' colour
        a deck the three may take. Empty while the seat has no heroes.
        """
        from codex.cards import catalog

        found = []
        for spec in self.player_specs.get(seat, ()):
            color = (catalog().hero_for(spec).color or "neutral").lower()
            if color not in found:
                found.append(color)
        return tuple(found)

    def _settle_deck(self, seat: int) -> None:
        """
        The deck the rule settles: **the first hero's colour** -- a
        team's heroes are held in the order chosen, and the first chosen
        names the starting deck among their colours (UMR p. 3; the
        author, 2026-10-10: which hero is first decides the deck, and
        the lobby says so). None while the seat has no heroes.
        """
        choices = self.deck_choices(seat)
        if choices:
            self.player_decks[seat] = choices[0]
        else:
            self.player_decks.pop(seat, None)

    def take_seat(self, user_id: int, user_name: Optional[str], specs,
                  seat: Optional[int] = None) -> int:
        """
        Sit down with these heroes -- `specs`, one or three as the game
        takes, a single spec as a string for the basic game. A seated
        player choosing again changes their heroes; somebody new takes
        the first free seat. In a **test game** one person plays both
        sides: `seat` names which one they choose for, and without it a
        second choice sits them down on the other side. Returns the seat.
        """
        self._require_lobby()
        if isinstance(specs, str):
            specs = [specs]
        specs = self._check_team([spec.strip().lower() for spec in specs])
        mine = self.seats_of(user_id)
        if seat is not None:
            if seat not in (1, 2):
                raise RuleRefusal("A game has seats 1 and 2.")
            held = self.player_1_id if seat == 1 else self.player_2_id
            if held is not None and held != user_id:
                raise RuleRefusal("Somebody else is sitting there.")
            if held is None and mine and not self.test_game:
                raise RuleRefusal("You are already seated -- a game is two players.")
            target = seat
        elif mine and (not self.test_game or len(mine) == 2):
            target = mine[0]
        elif self.player_1_id is None:
            target = 1
        elif self.player_2_id is None:
            target = 2
        else:
            raise RuleRefusal("Both seats are taken -- a game is two players.")
        if target == 1:
            self.player_1_id, self.player_1_name = user_id, user_name
        else:
            self.player_2_id, self.player_2_name = user_id, user_name
        self.player_specs[target] = specs
        self._settle_deck(target)
        if user_id in self.observer_ids:
            self.observer_ids.remove(user_id)
        return target

    def choose_deck(self, user_id: int, color: str, seat: Optional[int] = None) -> int:
        """
        `user_id`'s seat -- or `seat`, one of theirs in a test game --
        takes the starting deck of `color`, one of its heroes' colours
        (UMR p. 3: "the 10 starting cards that match one of your three
        heroes' colors"): the first hero of that colour moves to the
        front of the team, since the first hero names the deck
        (`_settle_deck`). Returns the seat.
        """
        self._require_lobby()
        seats = self.seats_of(user_id)
        if seat is None:
            seat = seats[0] if seats else None
        if seat is None or seat not in seats:
            raise RuleRefusal("You are not seated in this lobby.")
        color = color.strip().lower()
        if color not in self.deck_choices(seat):
            raise RuleRefusal(
                "Your starting deck is the colour of one of your heroes.", cite="UMR p. 3",
            )
        from codex.cards import catalog

        specs = self.player_specs[seat]
        first = next(spec for spec in specs
                     if (catalog().hero_for(spec).color or "neutral").lower() == color)
        self.player_specs[seat] = [first, *(spec for spec in specs if spec != first)]
        self._settle_deck(seat)
        return seat

    def seat_complete(self, seat: int) -> bool:
        """The seat is taken, with as many heroes as the game takes and
        its deck settled."""
        held = self.player_1_id if seat == 1 else self.player_2_id
        return (
            held is not None
            and len(self.player_specs.get(seat, ())) == self.heroes_per_seat
            and self.player_decks.get(seat) in self.deck_choices(seat)
        )

    def leave(self, user_id: int) -> None:
        """Give up a seat in the lobby -- both, in a test game where one
        person holds the two."""
        self._require_lobby()
        seats = self.seats_of(user_id)
        if not seats:
            raise RuleRefusal("You are not seated in this lobby.")
        for seat in seats:
            if seat == 1:
                self.player_1_id, self.player_1_name = None, None
            else:
                self.player_2_id, self.player_2_name = None, None
            self.player_specs.pop(seat, None)
            self.player_decks.pop(seat, None)
            if seat in self.kept_heroes:
                self.kept_heroes.remove(seat)

    def may_start(self) -> bool:
        """Both seats complete -- each taken, with its heroes and its
        deck -- in a lobby."""
        return (
            self.status is GameStatus.LOBBY
            and self.seat_complete(1)
            and self.seat_complete(2)
        )

    def start(self, engine: "RulesEngine") -> None:
        """Deal the opening position: the engine shuffles, deals and
        picks who goes first (UMR p. 3)."""
        self._require_lobby()
        if not self.may_start():
            raise RuleRefusal(
                "Both seats have to be taken, each with its heroes and its deck, "
                "before the game can start.",
                cite="UMR p. 3",
            )
        match = engine.new_match(
            (self.player_specs[1], self.player_specs[2]),
            decks=(self.player_decks[1], self.player_decks[2]),
        )
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

    # -- The end ---------------------------------------------------------

    def finish(self) -> None:
        """The match has a winner: the record says the game is over, so
        nothing re-arms its turn message and a rematch may be opened.
        Once only; a game already over stays as it ended."""
        if self.status is GameStatus.PLAYING:
            self.status = GameStatus.FINISHED

    @property
    def is_over(self) -> bool:
        return self.status in (GameStatus.FINISHED, GameStatus.ABANDONED)

    def rematch(self, game_id: str, game_number: int) -> "CodexGame":
        """
        The lobby of this finished game played again: the same two
        seats -- the same people, or the one person of a test game --
        in the same channel, in the same game, **the teams swapped**
        whole (each seat plays the heroes and the deck the other played)
        until both press **Keep heroes**
        (`keep_heroes`). Who goes first is drawn again at Start, as
        every game's is (`RulesEngine.new_match`). Refused for a game
        that is not finished: an abandoned game is not played again.
        """
        if self.status is not GameStatus.FINISHED:
            raise RuleRefusal("Only a finished game can be played again.")
        played = {seat: list(specs) for seat, specs in self.player_specs.items()}
        decks = dict(self.player_decks)
        return CodexGame(
            game_id=game_id,
            game_number=game_number,
            guild_id=self.guild_id,
            channel_id=self.channel_id,
            venue=self.venue,
            player_1_id=self.player_1_id,
            player_2_id=self.player_2_id,
            player_1_name=self.player_1_name,
            player_2_name=self.player_2_name,
            test_game=self.test_game,
            mode=self.mode,
            player_specs={1: list(played[2]), 2: list(played[1])},
            player_decks={1: decks[2], 2: decks[1]},
            board_layout=self.board_layout,
            rematch_of=self.game_id,
            rematch_specs=played,
            rematch_decks=decks,
        )

    def keep_heroes(self, user_id: int) -> bool:
        """
        **Keep heroes** in a rematch's lobby: `user_id`'s seat -- both,
        in a test game -- asks to play the hero it played last game, or,
        pressed again, takes that back. The heroes are the last game's
        while both seats have asked, and swapped otherwise. Returns
        whether they are kept now.
        """
        self._require_lobby()
        if not self.rematch_specs:
            raise RuleRefusal("Only a rematch has heroes to keep.")
        seats = self.seats_of(user_id)
        if not seats:
            raise RuleRefusal("You are not seated in this lobby.")
        asking = not all(seat in self.kept_heroes for seat in seats)
        for seat in seats:
            if asking and seat not in self.kept_heroes:
                self.kept_heroes.append(seat)
            elif not asking and seat in self.kept_heroes:
                self.kept_heroes.remove(seat)
        self.kept_heroes.sort()
        kept = self.heroes_kept
        if self.player_1_id is not None and self.player_2_id is not None:
            last, decks = self.rematch_specs, self.rematch_decks
            order = (1, 2) if kept else (2, 1)
            self.player_specs = {1: list(last[order[0]]), 2: list(last[order[1]])}
            if decks:
                self.player_decks = {1: decks[order[0]], 2: decks[order[1]]}
            else:
                self._settle_deck(1)
                self._settle_deck(2)
        return kept

    @property
    def heroes_kept(self) -> bool:
        """Whether both seats have pressed Keep heroes."""
        return set(self.kept_heroes) >= {1, 2}

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
        data["player_specs"] = {str(seat): list(specs) for seat, specs in self.player_specs.items()}
        data["player_decks"] = {str(seat): deck for seat, deck in self.player_decks.items()}
        data["rematch_specs"] = {str(seat): list(specs) for seat, specs in self.rematch_specs.items()}
        data["rematch_decks"] = {str(seat): deck for seat, deck in self.rematch_decks.items()}
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "CodexGame":
        data = dict(data)
        data["status"] = GameStatus(data.get("status", GameStatus.LOBBY.value))
        if data.get("mode") not in MODES:
            data["mode"] = "basic"
        data["player_specs"] = _read_teams(data.get("player_specs"))
        if "player_decks" in data:
            data["player_decks"] = {
                int(seat): deck for seat, deck in (data.get("player_decks") or {}).items()
            }
        else:
            # Older than step 10: every seat played the neutral deck.
            data["player_decks"] = {seat: "neutral" for seat in data["player_specs"]}
        data["observer_ids"] = list(data.get("observer_ids") or [])
        data["rematch_specs"] = _read_teams(data.get("rematch_specs"))
        if "rematch_decks" in data:
            data["rematch_decks"] = {
                int(seat): deck for seat, deck in (data.get("rematch_decks") or {}).items()
            }
        else:
            data["rematch_decks"] = {seat: "neutral" for seat in data["rematch_specs"]}
        data["kept_heroes"] = [int(seat) for seat in (data.get("kept_heroes") or [])]
        if data.get("venue") not in VENUES:
            data["venue"] = "channel"
        if data.get("board_layout") not in BOARD_LAYOUTS:
            data["board_layout"] = "stacked"
        return cls(**data)


def _read_teams(data: Optional[dict]) -> dict[int, list[str]]:
    """Seat to its heroes' specs -- a save older than step 10 holds one
    spec as a string, read as a list of one."""
    return {
        int(seat): [specs] if isinstance(specs, str) else list(specs)
        for seat, specs in (data or {}).items()
    }
