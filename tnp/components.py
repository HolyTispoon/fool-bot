"""
`MatchState`, a TNP game as it stands, with its `SavedField` table --
**the save format is the contract from the first commit** (the
preamble's save rule): every field is in `MATCH_SAVED_FIELDS` (and each
class's in its own table), and a saved key is never renamed.

Step 2 gave it the battle (`tnp.battle.BattleState`, saved whole under
`battle`); step 4 adds the turn around it: the turn and the phase, each
area of the map, each seat (`SeatState`), the spots units are deployed
into, the attack being resolved in March, and the winner. See
docs/design/tnp.md, "The turn".

**A seat's plan is held here** -- `SeatState.plan` and `locked` -- so a
restart mid-phase keeps both seats' plans, and **it is that seat's
alone** (TNP 5.2, 5.3): nothing public reads it until the phase that
reveals it.

A `MatchState()` with no `phase` is a battle staged on its own, as step
2's tests stage one: nothing but the battle is read.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from gamekit.saved import SavedField
from tnp.battle import SEATS, BattleState, _copy

#: The resource tokens on the map, as `tnp.briefs.RESOURCES` names them
#: (TNP 2.1, 2.2).
RESOURCES = ("blue_minerals", "orange_minerals", "gems")

#: What a seat's pool holds (TNP 2.2).
POOL = ("materials", "gold") + RESOURCES

#: The faction a seat plays; the Humans alone for now (TNP 1.2), a field
#: from the first commit so the others come in as data.
HUMANS = "humans"

#: Every faction of the game, in the order the lobby shows them (TNP
#: 1.2), and the ones that can be played: the XzzzX and the Space
#: Dragons are shown, greyed out, until their rules come in.
FACTIONS = (HUMANS, "xzzzx", "space_dragons")
PLAYABLE_FACTIONS = (HUMANS,)

# The turn's phases, as saved (TNP 5.1). Infrastructure and Deployment
# are one phase, done at the same time; Production and Trade one phase,
# its production run as it opens.
PLAN = "plan"              # TNP 5.2, 5.3: both seats plan, then lock in
MARCH = "march"            # TNP 5.4 to 5.8
PRODUCTION = "production"  # owed: TNP 5.9's production
TRADE = "trade"            # TNP 5.9's trade: both seats trade, then lock in
CLEANUP = "cleanup"        # owed: TNP 5.10
OVER = "over"

PHASES = (PLAN, MARCH, PRODUCTION, TRADE, CLEANUP, OVER)

#: The attack spots (TNP 2.5): A and B, and C with Command and Control
#: CPU in the advanced game (step 9's).
ATTACK_SPOTS = ("A", "B", "C")
BASIC_ATTACK_SPOTS = ("A", "B")
#: How many territories a seat defends a turn, beside its base (TNP 2.5).
DEFENSE_SPOTS = 3

#: How a seat wins (TNP 1.3).
WON_BY_BASE = "base"
WON_BY_HARVEST = "harvest"
#: The other seat gave the game up (step 8 of docs/tnp-bot.md): not a
#: rule of the game's, a player's own choice, as in Codex's.
WON_BY_CONCESSION = "concession"

#: Tokens a seat must harvest to win: 51% of map 3.3's 96 (TNP 1.3).
HARVEST_TO_WIN = 49


def _counts(value: Optional[Mapping[str, Any]]) -> dict[str, int]:
    """A count by slug, its zeros dropped."""
    return {slug: int(count) for slug, count in (value or {}).items() if int(count)}


# -- An area of the map ---------------------------------------------------------


@dataclass
class AreaState:
    """
    One area as it stands (TNP 2.1): who holds it, its resource tokens
    left, and the seats with a Stranded token on it (TNP 5.7). A base is
    its seat's always, and holds no tokens.
    """

    controller: Optional[str] = None
    resources: dict[str, int] = field(default_factory=dict)
    stranded: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {row.name: row.stored(getattr(self, row.name)) for row in AREA_SAVED_FIELDS}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AreaState":
        return cls(**{row.name: row.restored(data) for row in AREA_SAVED_FIELDS})

    def tokens_left(self) -> int:
        return sum(self.resources.values())


AREA_SAVED_FIELDS: tuple[SavedField, ...] = (
    SavedField("controller"),
    SavedField("resources", factory=dict, write=dict, read=dict),
    SavedField("stranded", factory=list, write=list, read=list),
)


# -- A pile of units in a spot -----------------------------------------------------


@dataclass
class Pile:
    """
    A seat's units in one spot (TNP 2.5): by unit, with how many of each
    carry a damage token (Tough, TNP 6.8) -- a battle's survivors keep
    theirs for the rest of March.
    """

    units: dict[str, int] = field(default_factory=dict)
    damaged: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"units": dict(self.units), "damaged": dict(self.damaged)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Pile":
        return cls(_counts(data.get("units")), _counts(data.get("damaged")))

    def add(self, units: Mapping[str, int], damaged: Optional[Mapping[str, int]] = None) -> None:
        for slug, count in units.items():
            if count:
                self.units[slug] = self.units.get(slug, 0) + int(count)
        for slug, count in (damaged or {}).items():
            if count:
                self.damaged[slug] = self.damaged.get(slug, 0) + int(count)

    def empty(self) -> bool:
        return not any(self.units.values())


# -- A seat ---------------------------------------------------------------------


@dataclass
class SeatState:
    """
    One seat (TNP 2): its faction, its base's facilities and upgrades,
    its pool, its units by state, what its Infrastructure placed, the
    tokens it has harvested, and its plan for the phase being played.

    A unit is **available** (at the base, deployable), **queued** (placed
    in this turn's Infrastructure, finished at Production), or in a spot
    -- an attack pile on the match's `attacks`, a defense pile on its
    `spots` (stranded where the area's Stranded token is the seat's).
    """

    faction: str = HUMANS
    #: The facilities and upgrades finished, by slug (TNP 2.4).
    built: list[str] = field(default_factory=list)
    #: The available resource pool, by `POOL` key (TNP 2.2).
    pool: dict[str, int] = field(default_factory=dict)
    #: The units at the base, ready to deploy.
    available: dict[str, int] = field(default_factory=dict)
    #: What this turn's Infrastructure placed, paid for and finished at
    #: Production and Trade (TNP 5.2, 5.9).
    queued_units: dict[str, int] = field(default_factory=dict)
    queued: list[str] = field(default_factory=list)
    #: The tokens this seat has taken off the map (TNP 1.3, 5.8).
    harvested: int = 0
    #: The seat's plan for the phase being played -- in Infrastructure
    #: and Deployment its queue and its deployment, in Production and
    #: Trade its trade -- and whether it has locked in. **Its own alone**
    #: until the phase reveals it.
    plan: Optional[dict] = None
    locked: bool = False
    #: The advanced game's cards (TNP 8): the hand, by card slug with how
    #: many -- **the seat's own**, the minerals and gems it has harvested
    #: (TNP 8.1) -- its tech facilities in play (TNP 8.4), its building
    #: techs by the production facility each is attached to (TNP 8.3), and
    #: what this turn's Infrastructure put into play, finished at
    #: Production: `{"attach": {facility: card}, "build": [card],
    #: "discard": [card]}`.
    hand: dict[str, int] = field(default_factory=dict)
    tech: list[str] = field(default_factory=list)
    attached: dict[str, str] = field(default_factory=dict)
    queued_techs: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {row.name: row.stored(getattr(self, row.name)) for row in SEAT_SAVED_FIELDS}

    def cards(self) -> int:
        return sum(self.hand.values())

    def take_card(self, slug: str, count: int = 1) -> None:
        """Cards out of the hand; the caller has checked they are there."""
        left = self.hand.get(slug, 0) - count
        if left < 0:
            raise ValueError(f"the hand holds no {slug!r} to take")
        if left:
            self.hand[slug] = left
        else:
            self.hand.pop(slug, None)

    def give_card(self, slug: str, count: int = 1) -> None:
        if count:
            self.hand[slug] = self.hand.get(slug, 0) + count

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SeatState":
        return cls(**{row.name: row.restored(data) for row in SEAT_SAVED_FIELDS})


SEAT_SAVED_FIELDS: tuple[SavedField, ...] = (
    SavedField("faction", default=HUMANS),
    SavedField("built", factory=list, write=list, read=list),
    SavedField("pool", factory=dict, write=dict, read=dict),
    SavedField("available", factory=dict, write=dict, read=_counts),
    SavedField("queued_units", factory=dict, write=dict, read=_counts),
    SavedField("queued", factory=list, write=list, read=list),
    SavedField("harvested", default=0),
    SavedField("plan", write=_copy, read=_copy),
    SavedField("locked", default=False),
    SavedField("hand", factory=dict, write=dict, read=_counts),
    SavedField("tech", factory=list, write=list, read=list),
    SavedField("attached", factory=dict, write=dict, read=dict),
    SavedField("queued_techs", factory=dict, write=_copy, read=_copy),
)


# -- Saving the tables ---------------------------------------------------------------


def _battle_out(battle: Optional[BattleState]) -> Optional[dict]:
    return None if battle is None else battle.to_dict()


def _battle_in(data: Optional[Mapping[str, Any]]) -> Optional[BattleState]:
    return None if data is None else BattleState.from_dict(data)


def _areas_out(areas: Mapping[str, AreaState]) -> dict:
    return {slug: area.to_dict() for slug, area in areas.items()}


def _areas_in(data: Mapping[str, Any]) -> dict[str, AreaState]:
    return {slug: AreaState.from_dict(row) for slug, row in data.items()}


def _seats_out(seats: Mapping[str, SeatState]) -> dict:
    return {seat: state.to_dict() for seat, state in seats.items()}


def _seats_in(data: Mapping[str, Any]) -> dict[str, SeatState]:
    return {seat: SeatState.from_dict(row) for seat, row in data.items()}


def _spots_out(spots: Mapping[str, Mapping[str, Pile]]) -> dict:
    return {
        area: {seat: pile.to_dict() for seat, pile in piles.items() if not pile.empty()}
        for area, piles in spots.items()
        if any(not pile.empty() for pile in piles.values())
    }


def _spots_in(data: Mapping[str, Any]) -> dict[str, dict[str, Pile]]:
    return {
        area: {seat: Pile.from_dict(row) for seat, row in piles.items()}
        for area, piles in data.items()
    }


@dataclass
class MatchState:
    #: The battle being fought, or the last one fought, until March puts
    #: its outcome on the map and clears it.
    battle: Optional[BattleState] = None
    #: The turn, from 1, and the phase being played (`PHASES`); `None`
    #: for a battle staged alone.
    turn: int = 0
    phase: Optional[str] = None
    #: Every area of the map, by slug (TNP 2.1).
    areas: dict[str, AreaState] = field(default_factory=dict)
    #: Both seats, by name (TNP 1.2).
    seats: dict[str, SeatState] = field(default_factory=dict)
    #: The defense spots (TNP 2.5): by area -- a territory or a base --
    #: then by seat, the pile there. A battle's attacker who wins leaves
    #: its survivors in the territory's spot for the rest of March
    #: (TNP 5.7), and stranded units stay through Cleanup (TNP 5.10).
    spots: dict[str, dict[str, Pile]] = field(default_factory=dict)
    #: The attack piles not yet resolved this March: by seat, then by
    #: spot, `{"target": area, "units": {...}}` (TNP 5.3, 5.4). Face
    #: down: **each seat's alone** until March reveals it.
    attacks: dict[str, dict[str, dict]] = field(default_factory=dict)
    #: The attack March is resolving (`tnp.flow.turn`): its spot, its
    #: area, each seat's pile in it and where it stands.
    resolving: Optional[dict] = None
    #: What March has revealed this turn, in the order it revealed it:
    #: each `{"seat", "area", "spot", "units"}` -- the public record the
    #: map's piles are drawn from (`tnp.briefs.Pile`).
    revealed: list[dict] = field(default_factory=list)
    #: The seat that won, and how (`WON_BY_BASE`, `WON_BY_HARVEST`).
    winner: Optional[str] = None
    won_by: Optional[str] = None
    #: The advanced game (TNP 8), a setting from the start.
    advanced: bool = False
    #: The three technology decks (TNP 8.1), by deck, each a list of card
    #: slugs with the top card first -- face down, nobody's to see -- and
    #: each deck's discard pile, played and traded cards on top last.
    decks: dict[str, list[str]] = field(default_factory=dict)
    discards: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {row.name: row.stored(getattr(self, row.name)) for row in MATCH_SAVED_FIELDS}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MatchState":
        return cls(**{row.name: row.restored(data) for row in MATCH_SAVED_FIELDS})

    # -- Lookups -------------------------------------------------------------

    @property
    def playing(self) -> bool:
        """Whether this is a game's turn rather than a battle staged alone."""
        return self.phase is not None

    def seat(self, name: str) -> SeatState:
        return self.seats[name]

    def pile(self, area: str, seat: str) -> Pile:
        """The seat's pile in an area's defense spot, made empty where
        there is none."""
        return self.spots.setdefault(area, {}).setdefault(seat, Pile())

    def standing(self, area: str, seat: str) -> Optional[Pile]:
        """The seat's pile in an area's defense spot, `None` where empty."""
        found = self.spots.get(area, {}).get(seat)
        return None if found is None or found.empty() else found

    def controller(self, area: str) -> Optional[str]:
        return self.areas[area].controller


MATCH_SAVED_FIELDS: tuple[SavedField, ...] = (
    SavedField("battle", write=_battle_out, read=_battle_in),
    SavedField("turn", default=0),
    SavedField("phase"),
    SavedField("areas", factory=dict, write=_areas_out, read=_areas_in),
    SavedField("seats", factory=dict, write=_seats_out, read=_seats_in),
    SavedField("spots", factory=dict, write=_spots_out, read=_spots_in),
    SavedField("attacks", factory=dict, write=_copy, read=_copy),
    SavedField("resolving", write=_copy, read=_copy),
    SavedField("revealed", factory=list, write=_copy, read=_copy),
    SavedField("winner"),
    SavedField("won_by"),
    SavedField("advanced", default=False),
    SavedField("decks", factory=dict, write=_copy, read=_copy),
    SavedField("discards", factory=dict, write=_copy, read=_copy),
)


def opening(catalog, *, advanced: bool = False, rng=None) -> MatchState:
    """
    The position at setup (TNP 3): every territory neutral with its
    tokens, each seat's Barracks and Base Defenses built, 3 Workers, 3
    Mercenaries and 5 materials, and turn 1's Infrastructure and
    Deployment open -- and in the advanced game the three technology
    decks, each card as many times as its count, shuffled from `rng`,
    the engine's (TNP 8.1).
    """
    starting = catalog.board["starting"]
    match = MatchState(turn=1, phase=PLAN, advanced=advanced)
    if advanced:
        if rng is None:
            raise ValueError("the advanced game's decks are shuffled from the engine's rng")
        for deck in RESOURCES:
            cards = [
                slug for slug, tech in catalog.techs.items() if tech.deck == deck
                for _ in range(tech.count)
            ]
            rng.shuffle(cards)
            match.decks[deck] = cards
            match.discards[deck] = []
    for slug, area in catalog.areas.items():
        match.areas[slug] = AreaState(
            controller=area.seat if area.is_base else None,
            resources={} if area.is_base else {
                key: int(area.resources.get(key, 0)) for key in RESOURCES
            },
        )
    for seat in SEATS:
        match.seats[seat] = SeatState(
            built=[slug for slug, facility in catalog.facilities.items() if facility.built_at_start],
            pool={key: int(starting["pool"].get(key, 0)) for key in POOL},
            available=_counts(starting["units"]),
        )
    return match
