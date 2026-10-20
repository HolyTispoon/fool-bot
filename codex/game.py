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
#: them; stacked the same way up, neither turned; or the two side by
#: side -- the game's choice, so everyone sees the same picture
#: (docs/codex-bot.md, decision 5; docs/design/codex.md, "The board on
#: Discord").
BOARD_LAYOUTS = ("stacked", "stacked_upright", "side_by_side")

#: Where on Discord the game is played (docs/design/codex.md, "The lobby
#: and the channel"): a channel of its own under Codex Games, which the
#: bot renames and archives; a thread it opened in the channel the lobby
#: was asked for in, where it may not make channels; or that channel
#: itself, where it may make neither, which it never renames or moves.
VENUES = ("channel", "thread", "here")

#: How many seats there are and how they stand to each other
#: (docs/codex-multiplayer.md, decision 2): the **duel** of two, the
#: **free-for-all** of three to five, every base its own (Rulebook
#: p. 14), and the **two-headed dragon**, two teams of two (p. 13). A
#: third axis beside `MODES`, which says how many heroes a seat holds.
DUEL, FREE_FOR_ALL, TWO_HEADED_DRAGON = "duel", "free_for_all", "two_headed_dragon"
VARIANTS = (DUEL, FREE_FOR_ALL, TWO_HEADED_DRAGON)
#: What the lobby and `/codex games` call each variant.
VARIANT_LABELS = {
    "duel": "Duel",
    "free_for_all": "Free-for-all",
    "two_headed_dragon": "Two-headed dragon",
}
#: The seats each variant has: a free-for-all's five are its most, and
#: it starts from three (`MIN_SEATS`).
VARIANT_SEATS = {"duel": 2, "free_for_all": 5, "two_headed_dragon": 4}
#: The fewest complete seats a variant starts with.
MIN_SEATS = {"duel": 2, "free_for_all": 3, "two_headed_dragon": 4}
#: A two-headed dragon's two teams by seat, as the deal pairs them
#: (`RulesEngine.new_match`): seats 1 and 2 against 3 and 4, each
#: team's first seat its head (docs/codex-multiplayer.md, decision 12).
DRAGON_TEAMS = ((1, 2), (3, 4))


def by_variant(variant: str, *, duel, free_for_all, dragon):
    """The one of three that `variant` -- the record's or the match's --
    names: what a line says, or a label, where the duel, the free-for-all
    and the dragon word it differently ("your opponent's", "the others'",
    "the other team's"). So a line that branches by variant names all
    three, and none is left to fall through to the duel's wording, which
    is how several reached a table before (the review of 2026-10-15)."""
    if variant == TWO_HEADED_DRAGON:
        return dragon
    if variant == FREE_FOR_ALL:
        return free_for_all
    return duel


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

    #: Who sits where, in lobby order: seat *n* is `seats[n - 1]`, a
    #: `{"id", "name"}` with both `None` while the seat is empty. As long
    #: as `seat_count` seats, so a seat left empty keeps its number.
    #: Saved as "seats"; a save older than the multiplayer worksheet has
    #: the four `player_1_*` / `player_2_*` keys instead, which are read
    #: where "seats" is missing and still written for the first two seats
    #: (docs/design/codex.md, "Multiplayer").
    seats: list[dict] = field(default_factory=lambda: _empty_seats(SEAT_COUNT))
    test_game: bool = False
    observer_ids: list[int] = field(default_factory=list)

    #: The basic game or the standard one (`MODES`): one hero a seat,
    #: or three. "basic" in a save older than step 10.
    mode: str = "basic"
    #: One of `VARIANTS`: the duel, a free-for-all or a two-headed
    #: dragon. "duel" in a save older than multiplayer step 2. The rules
    #: read the match's own copy (`MatchState.variant`), never this one.
    variant: str = "duel"
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
    #: One of `BOARD_LAYOUTS`; the turn message's **Swap view** flips
    #: the two stacked ones, `/codex side_by_side` the side-by-side one.
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
    #: The finished game this lobby is the rematch of. `None` for a lobby
    #: `/codex create_game` opened. A save from before 2026-10-20 may
    #: also hold `rematch_specs`, `rematch_decks` and `kept_heroes`, the
    #: last game's teams and **Keep heroes**, which are dropped as it is
    #: read (`from_dict`).
    rematch_of: Optional[str] = None

    def __post_init__(self) -> None:
        # A record made for a free-for-all has its five seats from the
        # start, so seat *n* is always `seats[n - 1]`.
        if len(self.seats) < self.seat_count:
            self.seats = self.seats + _empty_seats(self.seat_count - len(self.seats))

    # -- Reading the seats -------------------------------------------

    @property
    def seat_count(self) -> int:
        """How many seats the game has: two in a duel, five in a
        free-for-all (which starts from three), four in a dragon."""
        return VARIANT_SEATS.get(self.variant, SEAT_COUNT)

    # The variant, read one way -- the record's as the match's
    # (`MatchState.is_duel` and the rest).

    @property
    def is_duel(self) -> bool:
        return self.variant == DUEL

    @property
    def is_free_for_all(self) -> bool:
        return self.variant == FREE_FOR_ALL

    @property
    def is_dragon(self) -> bool:
        return self.variant == TWO_HEADED_DRAGON

    def _seat(self, seat: int) -> dict:
        return self.seats[seat - 1]

    def _set_seat(self, seat: int, user_id: Optional[int], name: Optional[str]) -> None:
        self.seats[seat - 1] = {"id": user_id, "name": name}

    @property
    def player_1_id(self) -> Optional[int]:
        return self._seat(1)["id"]

    @player_1_id.setter
    def player_1_id(self, value: Optional[int]) -> None:
        self._seat(1)["id"] = value

    @property
    def player_2_id(self) -> Optional[int]:
        return self._seat(2)["id"]

    @player_2_id.setter
    def player_2_id(self, value: Optional[int]) -> None:
        self._seat(2)["id"] = value

    @property
    def player_1_name(self) -> Optional[str]:
        return self._seat(1)["name"]

    @player_1_name.setter
    def player_1_name(self, value: Optional[str]) -> None:
        self._seat(1)["name"] = value

    @property
    def player_2_name(self) -> Optional[str]:
        return self._seat(2)["name"]

    @player_2_name.setter
    def player_2_name(self, value: Optional[str]) -> None:
        self._seat(2)["name"] = value

    def seat_user_id(self, seat: int) -> Optional[int]:
        """The Discord id sitting in `seat`, or `None`."""
        if not 1 <= seat <= len(self.seats):
            return None
        return self._seat(seat)["id"]

    def seat_ids(self) -> tuple[int, ...]:
        """Every id seated, in seat order, once each -- one person
        holding two seats of a test game counted once."""
        found: list[int] = []
        for held in self.seats:
            if held["id"] is not None and held["id"] not in found:
                found.append(held["id"])
        return tuple(found)

    def seats_of(self, user_id: Optional[int]) -> tuple[int, ...]:
        """Every seat `user_id` holds: one, or all of them in a test game."""
        if user_id is None:
            return ()
        return tuple(
            number for number, held in enumerate(self.seats, 1) if held["id"] == user_id
        )

    def seat_of(self, user_id: Optional[int]) -> Optional[int]:
        """The seat `user_id` holds, or `None` -- the first of them where
        a test game seats one person in several (`seats_of`)."""
        seats = self.seats_of(user_id)
        return seats[0] if seats else None

    def seat_for(self, user_id: Optional[int], active: int) -> Optional[int]:
        """
        The seat a click of `user_id`'s acts for: their seat -- or, in a
        test game where they hold both, the one whose turn it is.
        """
        seats = self.seats_of(user_id)
        if active in seats:
            return active
        return seats[0] if seats else None

    def teams(self) -> tuple[tuple[int, ...], ...]:
        """The seats as the lobby and the channel's name group them: a
        dragon's two teams (`DRAGON_TEAMS`), and every other game's seats
        each a side of its own."""
        if self.is_dragon:
            return DRAGON_TEAMS
        return tuple((seat,) for seat in range(1, self.seat_count + 1))

    def seat_name(self, seat: int) -> Optional[str]:
        if not 1 <= seat <= len(self.seats):
            return None
        return self._seat(seat)["name"]

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
        one is no team of three -- each picks again.
        """
        self._require_lobby()
        if mode not in MODES:
            raise RuleRefusal(f"A Codex game is basic or standard, not {mode}.", cite="UMR p. 3")
        if mode == self.mode:
            return
        self.mode = mode
        self.player_specs = {}
        self.player_decks = {}

    def set_variant(self, variant: str) -> None:
        """
        Play a duel, a free-for-all or a two-headed dragon
        (docs/codex-multiplayer.md, decisions 2 and 12). The lobby's until
        Start, as the mode is: every seated player that still fits keeps
        their seat and their heroes, and the rest are cleared. A dragon's
        four seats are two teams, seats 1 and 2 against 3 and 4 (Rulebook
        p. 13; decision 12): a player who wants the other team leaves and
        sits again.
        """
        self._require_lobby()
        if variant not in VARIANTS:
            raise RuleRefusal(
                f"A Codex game is a duel, a free-for-all or a two-headed dragon, not {variant}.",
                cite="Rulebook p. 13-14",
            )
        if variant == self.variant:
            return
        self.variant = variant
        count = self.seat_count
        for seat in range(count + 1, len(self.seats) + 1):
            self.player_specs.pop(seat, None)
            self.player_decks.pop(seat, None)
        self.seats = [dict(held) for held in self.seats[:count]]
        self.seats += _empty_seats(count - len(self.seats))
        if self.is_free_for_all:
            self._close_gaps()

    def _close_gaps(self) -> None:
        """A free-for-all's seats are taken in order with no gap -- turn
        order is seat order (Rulebook p. 14) -- so an empty seat among
        taken ones closes up: each seat after it moves up one, with its
        heroes and deck."""
        taken = [seat for seat in range(1, self.seat_count + 1)
                 if self.seat_user_id(seat) is not None]
        moved = {old: new for new, old in enumerate(taken, start=1)}
        self.seats = [dict(self._seat(old)) for old in taken]
        self.seats += _empty_seats(self.seat_count - len(self.seats))
        self.player_specs = {moved[old]: specs for old, specs in self.player_specs.items() if old in moved}
        self.player_decks = {moved[old]: deck for old, deck in self.player_decks.items() if old in moved}

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
            if not 1 <= seat <= self.seat_count:
                raise RuleRefusal(
                    f"This game has {self.seat_count} seats, numbered 1 to {self.seat_count}."
                )
            held = self.seat_user_id(seat)
            if held is not None and held != user_id:
                raise RuleRefusal("Somebody else is sitting there.")
            if held is None and mine and not self.test_game:
                raise RuleRefusal(
                    f"You are already seated. This game is {self.seat_count} players."
                )
            if held is None and self.is_free_for_all and any(
                self.seat_user_id(earlier) is None for earlier in range(1, seat)
            ):
                raise RuleRefusal(
                    "A free-for-all's seats are taken in order: turn order is seat order.",
                    cite="Rulebook p. 14",
                )
            target = seat
        elif mine and (not self.test_game or len(mine) == self.seat_count):
            target = mine[0]
        else:
            free = [number for number in range(1, self.seat_count + 1)
                    if self.seat_user_id(number) is None]
            if not free:
                raise RuleRefusal(
                    f"All the seats are taken. This game is {self.seat_count} players."
                )
            target = free[0]
        self._set_seat(target, user_id, user_name)
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
                "Your starting deck is the color of one of your heroes.", cite="UMR p. 3",
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
        return (
            self.seat_user_id(seat) is not None
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
            self._set_seat(seat, None, None)
            self.player_specs.pop(seat, None)
            self.player_decks.pop(seat, None)
        if self.is_free_for_all:
            # Turn order is seat order: the seats after move up.
            self._close_gaps()

    def taken_seats(self) -> tuple[int, ...]:
        """The seats somebody sits in, in order."""
        return tuple(seat for seat in range(1, self.seat_count + 1)
                     if self.seat_user_id(seat) is not None)

    def may_start(self) -> bool:
        """
        In a lobby, every seat complete -- each taken, with its heroes
        and its deck -- or, in a free-for-all, at least three seats and
        every one taken complete (Rulebook p. 14: three to five players).
        """
        if self.status is not GameStatus.LOBBY:
            return False
        if self.is_free_for_all:
            taken = self.taken_seats()
            return len(taken) >= MIN_SEATS[self.variant] and all(
                self.seat_complete(seat) for seat in taken
            )
        return all(self.seat_complete(seat) for seat in range(1, self.seat_count + 1))

    def playing_seats(self) -> tuple[int, ...]:
        """The seats a match is dealt to: a free-for-all's taken ones, and
        every seat of any other game."""
        if self.is_free_for_all:
            return self.taken_seats()
        return tuple(range(1, self.seat_count + 1))

    def start_refusal(self) -> RuleRefusal:
        """What Start says while the seats are not ready -- the lobby
        shows it as the game's own refusal does."""
        if self.is_dragon:
            return RuleRefusal(
                "A two-headed dragon needs four players, two a team, each with their heroes "
                "and their deck, before it can start.",
                cite="Rulebook p. 13",
            )
        if self.is_free_for_all:
            return RuleRefusal(
                "A free-for-all needs three to five players, each with their heroes and "
                "their deck, before it can start.",
                cite="Rulebook p. 14",
            )
        return RuleRefusal(
            "Both seats have to be taken, each with its heroes and its deck, "
            "before the game can start.",
            cite="UMR p. 3",
        )

    def start(self, engine: "RulesEngine") -> None:
        """Deal the opening position: the engine shuffles, deals and
        picks who goes first (UMR p. 3)."""
        self._require_lobby()
        if not self.may_start():
            raise self.start_refusal()
        seats = self.playing_seats()
        match = engine.new_match(
            tuple(self.player_specs[seat] for seat in seats),
            decks=tuple(self.player_decks[seat] for seat in seats),
            variant=self.variant,
        )
        self.match_state = match.to_dict()
        self.status = GameStatus.PLAYING
        if self.is_free_for_all:
            # The author, 2026-10-14: three or four players open side by
            # side, two panels a row; five open stacked. Swap view
            # toggles the two (docs/codex-multiplayer.md, decision 14).
            self.board_layout = "side_by_side" if len(seats) <= 4 else "stacked"
        elif self.is_dragon:
            # Two rows of two, the far team's turned to face the near one,
            # as the duel's far panel is (the author, 2026-10-14; decision
            # 14); Swap view flips them the same way up.
            self.board_layout = "stacked"

    def set_board_layout(self, layout: str) -> None:
        """Lay the board out `layout` -- refused for one there is not,
        or once the game is over."""
        if layout not in BOARD_LAYOUTS:
            raise RuleRefusal(f"The board is laid out stacked, stacked the same way up or side by side, not {layout}.")
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
        The lobby of this finished game played again: the same seats --
        the same people, or the one person of a test game -- in the same
        channel, the same mode and variant, and every seat choosing its
        heroes and deck again, as in any new lobby (the author,
        2026-10-20; docs/codex-multiplayer.md, decision 16). Who goes
        first is drawn again at Start, as every game's is
        (`RulesEngine.new_match`). Refused for a game that is not
        finished: an abandoned game is not played again.
        """
        if self.status is not GameStatus.FINISHED:
            raise RuleRefusal("Only a finished game can be played again.")
        return CodexGame(
            game_id=game_id,
            game_number=game_number,
            guild_id=self.guild_id,
            channel_id=self.channel_id,
            venue=self.venue,
            seats=[dict(held) for held in self.seats],
            test_game=self.test_game,
            mode=self.mode,
            variant=self.variant,
            board_layout=self.board_layout,
            rematch_of=self.game_id,
        )

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
        # The first two seats are also written as the keys every older
        # save, and D12 Ball's record, spell them with.
        for number in (1, 2):
            held = self.seats[number - 1]
            data[f"player_{number}_id"] = held["id"]
            data[f"player_{number}_name"] = held["name"]
        data["player_specs"] = {str(seat): list(specs) for seat, specs in self.player_specs.items()}
        data["player_decks"] = {str(seat): deck for seat, deck in self.player_decks.items()}
        if self.is_duel:
            # Written only for a multiplayer game, so a duel's record is the
            # record it always was -- and still reads on a checkout older
            # than the variant, between a pull and a restart.
            del data["variant"]
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "CodexGame":
        data = dict(data)
        data["status"] = GameStatus(data.get("status", GameStatus.LOBBY.value))
        legacy = {key: data.pop(key, None) for key in LEGACY_SEAT_KEYS}
        if data.get("variant") not in VARIANTS:
            data["variant"] = "duel"
        count = VARIANT_SEATS[data["variant"]]
        if data.get("seats"):
            data["seats"] = _read_seats(data["seats"], count)
        else:
            data["seats"] = _pad_seats([
                {"id": legacy["player_1_id"], "name": legacy["player_1_name"]},
                {"id": legacy["player_2_id"], "name": legacy["player_2_name"]},
            ], count)
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
        # A rematch's lobby saved before 2026-10-20 held the last game's
        # teams and who had pressed Keep heroes; its seats' picks stand.
        for key in ("rematch_specs", "rematch_decks", "kept_heroes"):
            data.pop(key, None)
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


#: How many seats a duel has, and a game whose variant is unknown.
SEAT_COUNT = 2

#: The keys a save older than "seats" seats its two players with, which
#: `from_dict` reads where "seats" is missing. Not fields -- they are
#: properties over `seats` now -- so the loader must not drop them as
#: retired (gamesaves/codex/storage.py).
LEGACY_SEAT_KEYS = ("player_1_id", "player_1_name", "player_2_id", "player_2_name")


def _empty_seats(count: int) -> list[dict]:
    return [{"id": None, "name": None} for _ in range(count)]


def _pad_seats(seats: list[dict], count: int = SEAT_COUNT) -> list[dict]:
    """The seats as a list of exactly the game's count, an empty one
    where the list was short."""
    seats = [dict(held) for held in seats[:count]]
    return seats + _empty_seats(count - len(seats))


def _read_seats(data: list, count: int = SEAT_COUNT) -> list[dict]:
    return _pad_seats([
        {"id": held.get("id"), "name": held.get("name")} for held in data
    ], count)
