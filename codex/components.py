"""
The Codex position: `MatchState`, the two `PlayerState`s, and what is on
their side of the table.

**The save format is the contract from this first commit on**
(docs/design/codex.md, "The saved fields"): every field of every class
here is written and read back through a `SavedField` table with the
fallback an older save comes back with, and `tests/test_codex_components.py`
walks each dataclass and fails on a field its table does not name -- the
same guard `MATCH_SAVED_FIELDS` is for D12 Ball. A field added later
goes in its table, with its fallback, in the same commit.

Nothing here decides a rule; the engine (`codex.engine`) asks the
position and the flow (`codex.flow`) changes it. What lives here is the
position's own consistency: `MatchState.validate` checks a loaded match
against itself, never against anything outside it.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field, fields
from typing import Any, Callable, Iterable, Iterator, Optional

from codex.game import RuleRefusal

__all__ = [
    "AddOnState",
    "BuildingState",
    "CardInstance",
    "HeroState",
    "MATCH_SAVED_FIELDS",
    "MatchState",
    "PATROL_SLOTS",
    "PHASES",
    "PlayerState",
    "RuleRefusal",
    "SAVED_FIELDS",
    "TECH_BUILDINGS",
]

#: The patrol zone's five slots, left to right (UMR p. 10).
PATROL_SLOTS = ("squad_leader", "elite", "scavenger", "technician", "lookout")

#: A turn's five phases and the main phase's patrol lock (UMR p. 5).
PHASES = ("ready", "upkeep", "main", "patrol", "draw", "tech")

#: The three tech-building slots in a base (UMR p. 8).
TECH_BUILDINGS = ("tech1", "tech2", "tech3")

#: What an attacker or a defender names the hero by, beside a card's
#: `unit:<id>` -- the hero is not a card instance.
HERO = "hero"


@dataclass(frozen=True)
class SavedField:
    """
    One saved field: its key, the fallback a save older than the field
    comes back with (`default` immutable, `factory` mutable, as
    `dataclasses.field` splits them), and the copy each way.
    `d12ball.components.SavedField`'s shape.
    """

    name: str
    default: Any = None
    factory: Optional[Callable[[], Any]] = None
    write: Optional[Callable[[Any], Any]] = None
    read: Optional[Callable[[Any], Any]] = None

    def stored(self, value: Any) -> Any:
        return self.write(value) if self.write is not None else value

    def restored(self, data: dict) -> Any:
        if self.name not in data:
            return self.factory() if self.factory is not None else self.default
        value = data[self.name]
        return self.read(value) if self.read is not None else value


def _save(obj: Any, table: Iterable[SavedField]) -> dict:
    return {saved.name: saved.stored(getattr(obj, saved.name)) for saved in table}


def _load(table: Iterable[SavedField], data: dict) -> dict:
    return {saved.name: saved.restored(data) for saved in table}


def _copy_list(value: list) -> list:
    return list(value)


def _copy_optional_list(value: Optional[list]) -> Optional[list]:
    return None if value is None else list(value)


def _copy_dicts(value: list) -> list:
    return [dict(item) for item in value]


def _copy_optional_combat(value: Optional[dict]) -> Optional[dict]:
    return None if value is None else copy.deepcopy(value)


def _deep_copy(value: list) -> list:
    """A snapshot or a journal entry nests the whole position; a copy
    one level deep would leave the save and the live match sharing it."""
    return copy.deepcopy(value)


@dataclass
class HeroState:
    """A player's hero, in the command zone or in play (UMR p. 6)."""

    slug: str
    zone: str = "command"
    level: int = 1
    damage: int = 0
    summoning_runes: int = 0
    arrived_this_turn: bool = False
    exhausted: bool = False
    #: The hero has been at its maximum level since this turn began --
    #: what an ultimate spell asks (UMR p. 7).
    max_level_since_turn_began: bool = False
    #: A hero may patrol (UMR p. 10).
    patrol_slot: Optional[str] = None
    #: What is left of the squad leader's armor this turn.
    armor: int = 0
    #: It has attacked this turn -- what readiness's once a turn reads
    #: (UMR p. 17).
    attacked_this_turn: bool = False

    @property
    def in_play(self) -> bool:
        return self.zone == "play"


HERO_SAVED_FIELDS = (
    SavedField("slug"),
    SavedField("zone", default="command"),
    SavedField("level", default=1),
    SavedField("damage", default=0),
    SavedField("summoning_runes", default=0),
    SavedField("arrived_this_turn", default=False),
    SavedField("exhausted", default=False),
    SavedField("max_level_since_turn_began", default=False),
    SavedField("patrol_slot"),
    SavedField("armor", default=0),
    SavedField("attacked_this_turn", default=False),
)


@dataclass
class BuildingState:
    """A tech building: built, possibly still under construction (it is
    finished at the end of the turn), or destroyed and rebuildable for 0
    (UMR p. 8)."""

    hp: int
    under_construction: bool = True
    destroyed: bool = False

    @property
    def active(self) -> bool:
        return not self.under_construction and not self.destroyed


BUILDING_SAVED_FIELDS = (
    SavedField("hp", default=0),
    SavedField("under_construction", default=False),
    SavedField("destroyed", default=False),
)


@dataclass
class AddOnState:
    """The one add-on a base holds: the tower or the surplus (UMR p. 9)."""

    slug: str
    hp: int
    under_construction: bool = True
    #: What this tower has detected this turn -- the `unit:<id>` or
    #: `hero` ref -- or `None` while its once-a-turn detection is unused
    #: (UMR p. 9). Emptied when each turn begins.
    detected: Optional[str] = None

    @property
    def active(self) -> bool:
        return not self.under_construction


ADD_ON_SAVED_FIELDS = (
    SavedField("slug"),
    SavedField("hp", default=0),
    SavedField("under_construction", default=False),
    SavedField("detected"),
)


@dataclass
class CardInstance:
    """A card in play: a unit, or (from step 6) an ongoing spell or a
    token. `id` is unique across the match and never reused."""

    id: int
    slug: str
    owner: int
    controller: int
    damage: int = 0
    plus_runes: int = 0
    minus_runes: int = 0
    exhausted: bool = False
    arrived_this_turn: bool = True
    patrol_slot: Optional[str] = None
    #: This-turn effects, each `{kind, amount, until}`; empty until step 6.
    modifiers: list[dict] = field(default_factory=list)
    #: The ids attached to this; empty until step 6.
    attached: list[int] = field(default_factory=list)
    #: A token's flip (the Dancer); False until step 6.
    flipped: bool = False
    #: What is left of the squad leader's armor this turn.
    armor: int = 0
    #: It has attacked this turn -- what readiness's once a turn reads.
    attacked_this_turn: bool = False

    @property
    def ref(self) -> str:
        """How an action names this card: `unit:<id>`."""
        return f"unit:{self.id}"


INSTANCE_SAVED_FIELDS = (
    SavedField("id"),
    SavedField("slug"),
    SavedField("owner"),
    SavedField("controller"),
    SavedField("damage", default=0),
    SavedField("plus_runes", default=0),
    SavedField("minus_runes", default=0),
    SavedField("exhausted", default=False),
    SavedField("arrived_this_turn", default=False),
    SavedField("patrol_slot"),
    SavedField("modifiers", factory=list, write=_copy_dicts, read=_copy_dicts),
    SavedField("attached", factory=list, write=_copy_list, read=_copy_list),
    SavedField("flipped", default=False),
    SavedField("armor", default=0),
    SavedField("attacked_this_turn", default=False),
)


def _write_buildings(buildings: dict) -> dict:
    return {
        name: None if state is None else _save(state, BUILDING_SAVED_FIELDS)
        for name, state in buildings.items()
    }


def _read_buildings(data: dict) -> dict:
    return {
        name: None if data.get(name) is None
        else BuildingState(**_load(BUILDING_SAVED_FIELDS, data[name]))
        for name in TECH_BUILDINGS
    }


def _no_buildings() -> dict:
    return {name: None for name in TECH_BUILDINGS}


def _write_add_on(add_on: Optional[AddOnState]) -> Optional[dict]:
    return None if add_on is None else _save(add_on, ADD_ON_SAVED_FIELDS)


def _read_add_on(data: Optional[dict]) -> Optional[AddOnState]:
    return None if data is None else AddOnState(**_load(ADD_ON_SAVED_FIELDS, data))


def _write_play(play: list) -> list:
    return [_save(card, INSTANCE_SAVED_FIELDS) for card in play]


def _read_play(data: list) -> list:
    return [CardInstance(**_load(INSTANCE_SAVED_FIELDS, card)) for card in data]


def _write_hero(hero: HeroState) -> dict:
    return _save(hero, HERO_SAVED_FIELDS)


def _read_hero(data: dict) -> HeroState:
    return HeroState(**_load(HERO_SAVED_FIELDS, data))


@dataclass
class PlayerState:
    """One side of the table (UMR p. 3)."""

    seat: int
    spec: str
    hero: HeroState
    base_hp: int = 20
    gold: int = 0
    workers: int = 4
    hired_this_turn: bool = False
    #: Slugs. The hand is its owner's alone.
    hand: list[str] = field(default_factory=list)
    #: Slugs, **the top last**. Nobody knows its order.
    deck: list[str] = field(default_factory=list)
    #: Slugs, face-down: its owner knows it, the opponent its size.
    discard: list[str] = field(default_factory=list)
    #: Slug to how many copies are still in the codex.
    codex: dict[str, int] = field(default_factory=dict)
    #: The slugs picked in the tech phase and not yet in the discard;
    #: `None` while nothing has been picked.
    tech_choice: Optional[list[str]] = None
    #: The tech phase has been reached and its picks are not settled.
    tech_owed: bool = False
    #: Set by TECH_CONFIRM, cleared when the picks reach the discard.
    tech_confirmed: bool = False
    buildings: dict[str, Optional[BuildingState]] = field(default_factory=_no_buildings)
    add_on: Optional[AddOnState] = None
    play: list[CardInstance] = field(default_factory=list)
    reshuffled_this_phase: bool = False

    def patroller(self, slot: str) -> Optional[str]:
        """What patrols `slot`: `unit:<id>`, `hero`, or `None`."""
        if self.hero.in_play and self.hero.patrol_slot == slot:
            return HERO
        for card in self.play:
            if card.patrol_slot == slot:
                return card.ref
        return None

    def patrollers(self) -> dict[str, str]:
        """Slot to what patrols it, for the slots that are filled."""
        found = {slot: self.patroller(slot) for slot in PATROL_SLOTS}
        return {slot: ref for slot, ref in found.items() if ref is not None}

    def instance(self, instance_id: int) -> Optional[CardInstance]:
        return next((card for card in self.play if card.id == instance_id), None)

    @property
    def specs(self) -> tuple[str, ...]:
        """The deck's specs, in order: one in the basic game. The
        standard game's three (step 9) widen this, not its callers."""
        return (self.spec,)


PLAYER_SAVED_FIELDS = (
    SavedField("seat"),
    SavedField("spec"),
    SavedField("hero", write=_write_hero, read=_read_hero),
    SavedField("base_hp", default=20),
    SavedField("gold", default=0),
    SavedField("workers", default=4),
    SavedField("hired_this_turn", default=False),
    SavedField("hand", factory=list, write=_copy_list, read=_copy_list),
    SavedField("deck", factory=list, write=_copy_list, read=_copy_list),
    SavedField("discard", factory=list, write=_copy_list, read=_copy_list),
    SavedField("codex", factory=dict, write=dict, read=dict),
    SavedField("tech_choice", write=_copy_optional_list, read=_copy_optional_list),
    SavedField("tech_owed", default=False),
    SavedField("tech_confirmed", default=False),
    SavedField(
        "buildings", factory=_no_buildings,
        write=_write_buildings, read=_read_buildings,
    ),
    SavedField("add_on", write=_write_add_on, read=_read_add_on),
    SavedField("play", factory=list, write=_write_play, read=_read_play),
    SavedField("reshuffled_this_phase", default=False),
)


def _write_players(players: list) -> list:
    return [_save(player, PLAYER_SAVED_FIELDS) for player in players]


def _read_players(data: list) -> list:
    return [PlayerState(**_load(PLAYER_SAVED_FIELDS, player)) for player in data]


@dataclass
class MatchState:
    """
    The whole position: two players in seat order, whose turn it is and
    which phase, and the two fields decision 11 lays down for undo --
    the last three turn-start positions and the journal of this turn's
    actions (`codex.history`).
    """

    players: list[PlayerState]
    #: The seat that went first (UMR p. 3).
    first: int = 1
    #: The seat whose turn it is.
    active: int = 1
    turn: int = 1
    phase: str = "ready"
    winner: Optional[int] = None
    #: What happened, in order, for the statistics and the summary --
    #: written by `record_event` alone, and never read to decide a rule.
    events: list[dict] = field(default_factory=list)
    next_instance_id: int = 1
    #: The attacker the active player has declared, `unit:<id>` or
    #: `hero`, while the defender is asked (`CHOOSE_DEFENDER`).
    attacking: Optional[str] = None
    #: The attack under way once its defender is chosen and before its
    #: damage is dealt, while a choice it needs is asked
    #: (`codex.flow.combat`): `{defender, stage, obliterated, sparks,
    #: overpower, overpower_settled}`. `None` between attacks.
    combat: Optional[dict] = None
    #: The last three turn-start positions as dicts, oldest first.
    turn_snapshots: list[dict] = field(default_factory=list)
    #: The actions applied since this turn began, each with the random
    #: outcomes it consumed.
    journal: list[dict] = field(default_factory=list)

    # -- Reading -------------------------------------------------------

    def player(self, seat: int) -> PlayerState:
        return self.players[seat - 1]

    def opponent(self, seat: int) -> PlayerState:
        return self.players[2 - seat]

    @property
    def active_player(self) -> PlayerState:
        return self.player(self.active)

    def instance(self, instance_id: int) -> Optional[CardInstance]:
        for player in self.players:
            found = player.instance(instance_id)
            if found is not None:
                return found
        return None

    def instances(self) -> Iterator[CardInstance]:
        for player in self.players:
            yield from player.play

    # -- Writing -------------------------------------------------------

    def new_instance(self, slug: str, owner: int) -> CardInstance:
        card = CardInstance(
            id=self.next_instance_id, slug=slug, owner=owner, controller=owner,
            arrived_this_turn=True,
        )
        self.next_instance_id += 1
        self.player(owner).play.append(card)
        return card

    def record_event(self, kind: str, **details: Any) -> None:
        """The one writer of the event log."""
        self.events.append({"turn": self.turn, "seat": self.active, "kind": kind, **details})

    def enter_phase(self, phase: str) -> None:
        """Move to `phase`; the once-a-phase reshuffle is anybody's
        again (UMR p. 5)."""
        self.phase = phase
        for player in self.players:
            player.reshuffled_this_phase = False

    # -- Saving --------------------------------------------------------

    def to_dict(self) -> dict:
        return _save(self, MATCH_SAVED_FIELDS)

    @classmethod
    def from_dict(cls, data: dict) -> "MatchState":
        return cls(**_load(MATCH_SAVED_FIELDS, data))

    def validate(self, catalog) -> None:
        """
        The position checked against itself: ids unique, every slug in
        the catalog, at most one patroller a slot, no count below zero.
        Raises `ValueError` naming the first thing wrong -- a corrupt
        save, never a rule.
        """
        def fail(reason: str) -> None:
            raise ValueError(f"Codex match is inconsistent: {reason}")

        def known(slug: str, where: str) -> None:
            try:
                catalog.by_slug(slug)
            except KeyError:
                fail(f"{where} holds {slug!r}, which is not a card")

        if len(self.players) != 2 or [p.seat for p in self.players] != [1, 2]:
            fail("a match is two players in seat order")
        if self.first not in (1, 2) or self.active not in (1, 2):
            fail("first and active are seats 1 and 2")
        if self.winner not in (None, 1, 2):
            fail(f"winner is {self.winner!r}")
        if self.phase not in PHASES:
            fail(f"phase is {self.phase!r}")
        if self.turn < 1:
            fail(f"turn is {self.turn}")
        if len(self.turn_snapshots) > 3:
            fail("more than three turn-start snapshots are kept")

        ids = [card.id for card in self.instances()]
        if len(ids) != len(set(ids)):
            fail("two cards in play share an id")
        if ids and max(ids) >= self.next_instance_id:
            fail("next_instance_id would reuse an id")

        for player in self.players:
            where = f"seat {player.seat}"
            for name in ("base_hp", "gold", "workers"):
                if getattr(player, name) < 0:
                    fail(f"{where}'s {name} is below zero")
            known(player.hero.slug, f"{where}'s hero")
            for zone in ("hand", "deck", "discard"):
                for slug in getattr(player, zone):
                    known(slug, f"{where}'s {zone}")
            for slug, count in player.codex.items():
                known(slug, f"{where}'s codex")
                if count < 0:
                    fail(f"{where}'s codex holds {count} of {slug}")
            for slug in player.tech_choice or ():
                known(slug, f"{where}'s tech choice")
            hero = player.hero
            for name in ("level", "damage", "summoning_runes", "armor"):
                if getattr(hero, name) < 0:
                    fail(f"{where}'s hero has {name} below zero")
            if hero.zone not in ("command", "play"):
                fail(f"{where}'s hero is in {hero.zone!r}")
            slots = []
            if hero.patrol_slot is not None:
                if not hero.in_play:
                    fail(f"{where}'s hero patrols from the command zone")
                slots.append(hero.patrol_slot)
            for card in player.play:
                known(card.slug, f"{where}'s play zone")
                for name in ("damage", "plus_runes", "minus_runes", "armor"):
                    if getattr(card, name) < 0:
                        fail(f"card {card.id} has {name} below zero")
                if card.controller != player.seat:
                    fail(f"card {card.id} is in seat {player.seat}'s play but not theirs")
                if card.patrol_slot is not None:
                    slots.append(card.patrol_slot)
            for slot in slots:
                if slot not in PATROL_SLOTS:
                    fail(f"{where} patrols {slot!r}")
            if len(slots) != len(set(slots)):
                fail(f"{where} has two patrollers in one slot")
            for name, building in player.buildings.items():
                if name not in TECH_BUILDINGS:
                    fail(f"{where} has a building called {name!r}")
                if building is not None and building.hp < 0:
                    fail(f"{where}'s {name} is below zero")
            if player.add_on is not None:
                known(player.add_on.slug, f"{where}'s add-on")
                if player.add_on.hp < 0:
                    fail(f"{where}'s add-on is below zero")


MATCH_SAVED_FIELDS = (
    SavedField("players", write=_write_players, read=_read_players),
    SavedField("first", default=1),
    SavedField("active", default=1),
    SavedField("turn", default=1),
    SavedField("phase", default="ready"),
    SavedField("winner"),
    SavedField("events", factory=list, write=_deep_copy, read=_deep_copy),
    SavedField("next_instance_id", default=1),
    SavedField("attacking"),
    SavedField("combat", write=_copy_optional_combat, read=_copy_optional_combat),
    SavedField("turn_snapshots", factory=list, write=_deep_copy, read=_deep_copy),
    SavedField("journal", factory=list, write=_deep_copy, read=_deep_copy),
)

#: Every saved class and its table, which the coverage test walks.
SAVED_FIELDS = {
    MatchState: MATCH_SAVED_FIELDS,
    PlayerState: PLAYER_SAVED_FIELDS,
    HeroState: HERO_SAVED_FIELDS,
    CardInstance: INSTANCE_SAVED_FIELDS,
    BuildingState: BUILDING_SAVED_FIELDS,
    AddOnState: ADD_ON_SAVED_FIELDS,
}


def unsaved_fields() -> dict[str, list[str]]:
    """The fields of a saved class its table does not name -- empty, or
    a restart drops them."""
    missing = {}
    for cls, table in SAVED_FIELDS.items():
        named = {saved.name for saved in table}
        gaps = [f.name for f in fields(cls) if f.name not in named]
        if gaps:
            missing[cls.__name__] = gaps
    return missing
