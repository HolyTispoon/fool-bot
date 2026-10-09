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
from typing import Any, Iterable, Iterator, Optional

from codex.game import RuleRefusal
from gamekit.saved import SavedField

__all__ = [
    "HERO",
    "HERO_PREFIX",
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
    "hero_ref",
    "is_hero_ref",
    "upgrade_hero_refs",
]

#: The patrol zone's five slots, left to right (UMR p. 10).
PATROL_SLOTS = ("squad_leader", "elite", "scavenger", "technician", "lookout")

#: A turn's five phases and the main phase's patrol lock (UMR p. 5).
PHASES = ("ready", "upkeep", "main", "patrol", "draw", "tech")

#: The three tech-building slots in a base (UMR p. 8).
TECH_BUILDINGS = ("tech1", "tech2", "tech3")

#: What an attacker or a defender names a hero by, beside a card's
#: `unit:<id>` -- a hero is not a card instance: `hero:<slug>`
#: (`hero_ref`), since a standard game's side has three. A save older
#: than step 10 names its one hero `hero` alone, which reads as the
#: side's first hero (`PlayerState.hero_by_ref`, `upgrade_hero_refs`).
HERO = "hero"
HERO_PREFIX = HERO + ":"


def hero_ref(slug: str) -> str:
    """How an action names a hero: `hero:jaina_stormborne`."""
    return HERO_PREFIX + slug


def is_hero_ref(ref: Optional[str]) -> bool:
    """Whether `ref` names a hero -- `hero:<slug>`, or an older save's
    bare `hero`."""
    return ref == HERO or (isinstance(ref, str) and ref.startswith(HERO_PREFIX))


# `SavedField`, one row of a save table, is `gamekit.saved`'s, shared
# with D12 Ball's model, and imported above.


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


def _copy_optional_dict(value: Optional[dict]) -> Optional[dict]:
    return None if value is None else dict(value)


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
    #: Runes a spell put on it (Bloom's +1/+1, Wither's -1/-1), which
    #: cancel each other (UMR p. 13) and go when it leaves play.
    plus_runes: int = 0
    minus_runes: int = 0
    #: This-turn effects, each `{kind, amount, until}` -- Intimidate's
    #: -4 ATK -- as a card's.
    modifiers: list[dict] = field(default_factory=list)
    #: A printed value replaced (step 11): Chaos Mirror's ATK, `{"atk":
    #: n}`, until the end of the turn. `None` otherwise, and in an older
    #: save.
    printed: Optional[dict] = None
    #: When each band the hero is in play with came to be, by its first
    #: level ("5": 12), from `MatchState.sequence` -- what orders a band's
    #: grant against a card's (Midori's +1/+1 and Behind the Ferns). Empty
    #: in an older save.
    bands: dict[str, int] = field(default_factory=dict)
    #: Time runes on the hero (step 12): Prynn Pasternaak's fading. 0 in
    #: an older save.
    time_runes: int = 0
    #: Disabled (step 12, UMR p. 16): it does not ready at its next ready
    #: phase, which clears this. False in an older save.
    disabled: bool = False
    #: What Prynn Pasternaak's max level ability has trashed (step 12), each
    #: `{slug, owner, controller, id}`, returned to play when she leaves it.
    #: Empty for every other hero, and in an older save.
    trashed: list[dict] = field(default_factory=list)

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
    SavedField("plus_runes", default=0),
    SavedField("minus_runes", default=0),
    SavedField("modifiers", factory=list, write=_copy_dicts, read=_copy_dicts),
    SavedField("printed", write=_copy_optional_dict, read=_copy_optional_dict),
    SavedField("bands", factory=dict, write=dict, read=dict),
    SavedField("time_runes", default=0),
    SavedField("disabled", default=False),
    SavedField("trashed", factory=list, write=_copy_dicts, read=_copy_dicts),
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
    """The one add-on a base holds: the tower, the surplus, the heroes'
    hall or the tech lab (UMR p. 9)."""

    slug: str
    hp: int
    under_construction: bool = True
    #: What this tower has detected this turn -- the `unit:<id>` or
    #: `hero:<slug>` ref -- or `None` while its once-a-turn detection is
    #: unused (UMR p. 9). Emptied when each turn begins.
    detected: Optional[str] = None
    #: A tech lab's spec (UMR p. 9): chosen as it is built where a tech
    #: II's spec is chosen, and with the tech II's otherwise (the
    #: tech_lab ruling). `None` for every other add-on, for a lab still
    #: waiting on its choice, and in a save older than step 10.
    spec: Optional[str] = None

    @property
    def active(self) -> bool:
        return not self.under_construction


ADD_ON_SAVED_FIELDS = (
    SavedField("slug"),
    SavedField("hp", default=0),
    SavedField("under_construction", default=False),
    SavedField("detected"),
    SavedField("spec"),
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
    #: This-turn effects, each `{kind, amount, until}`: an ATK or HP
    #: change (Intimidate, Discord) or a keyword for the turn (Sneaky
    #: Pig's stealth, `{kind: "keyword", keyword}`), removed at the end
    #: of the turn.
    modifiers: list[dict] = field(default_factory=list)
    #: The ids attached to this: an ongoing spell's -- Two Step's two
    #: dance partners.
    attached: list[int] = field(default_factory=list)
    #: A token flipped to its other face -- a Dancer become an Angry
    #: Dancer, whose slug it then carries.
    flipped: bool = False
    #: What is left of the squad leader's armor this turn.
    armor: int = 0
    #: It has attacked this turn -- what readiness's once a turn reads.
    attacked_this_turn: bool = False
    #: The runes on it besides +1/+1 and -1/-1, by kind (step 11):
    #: Bloodburn's "blood", Might of Leaf and Claw's "growth", Fairie
    #: Dragon's "feather". Empty in an older save.
    runes: dict[str, int] = field(default_factory=dict)
    #: The seat a kidnapped unit goes back to at the end of the turn --
    #: its last controller (Kidnapping's Card FAQ) -- or `None`.
    returns_to: Optional[int] = None
    #: The hero an attaching spell is attached to, as a target names it
    #: ("1:hero:master_midori") -- Final Showdown's. `None` otherwise; a
    #: unit an attaching spell is on is in `attached`.
    attached_hero: Optional[str] = None
    #: A printed value replaced (step 11): Chaos Mirror's ATK, `{"atk": n}`,
    #: until the end of the turn; Polymorph: Squirrel's `{"polymorph":
    #: seat}`, a 1/1 green Squirrel with no abilities until that seat's
    #: next upkeep. `None` otherwise, and in an older save.
    printed: Optional[dict] = None
    #: The order it came into play in (`MatchState.sequence`): what orders
    #: the grants that read each other (the Card FAQ's Behind the Ferns
    #: and Midori). 0 in an older save.
    sequence: int = 0
    #: Time runes on it (step 12): fading's and forecast's countdowns,
    #: Tricycloid's, a rune Time Spiral added. 0 in an older save.
    time_runes: int = 0
    #: Disabled (step 12, UMR p. 16): it does not ready at its next ready
    #: phase, which clears this. False in an older save.
    disabled: bool = False
    #: The units buried in a Graveyard (step 12), each `{slug, owner}`, in
    #: the order they died: out of play and out of the discard pile, their
    #: runes and effects gone. Empty for anything else, and in an older
    #: save.
    buried: list[dict] = field(default_factory=list)
    #: The id of the card whose arrival summoned this token, where that
    #: matters (step 12): Terras Q's four Warlocks shackle him alone. `None`
    #: otherwise, and in an older save.
    made_by: Optional[int] = None

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
    SavedField("runes", factory=dict, write=dict, read=dict),
    SavedField("returns_to"),
    SavedField("attached_hero"),
    SavedField("printed", write=_copy_optional_dict, read=_copy_optional_dict),
    SavedField("sequence", default=0),
    SavedField("time_runes", default=0),
    SavedField("disabled", default=False),
    SavedField("buried", factory=list, write=_copy_dicts, read=_copy_dicts),
    SavedField("made_by"),
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
    """One side of the table (UMR p. 3): one hero in the basic game,
    three in the standard one."""

    seat: int
    #: The deck's specs, in the order the heroes were chosen -- one in
    #: the basic game, three in the standard one. Saved as `specs`; a
    #: save older than step 10 has one `spec`.
    specs: tuple[str, ...]
    #: Each spec's hero, in the same order. Saved as `heroes`; a save
    #: older than step 10 has one `hero`.
    heroes: list[HeroState]
    #: The starting deck's colour (UMR p. 3); "neutral" in an older save.
    deck_color: str = "neutral"
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
    #: The spec chosen as the tech II building was constructed (UMR
    #: p. 8): kept through its destruction and its rebuild. `None` until
    #: then, always in a basic game -- whose one spec the rule chooses --
    #: and in a save older than step 10.
    tech2_spec: Optional[str] = None
    #: Whether this player has constructed a tech building or an add-on
    #: yet, a rebuild for 0 included: what a multicolour team's +1 on its
    #: first is remembered by (UMR pp. 4, 8, 9). False in an older save.
    constructed_once: bool = False
    #: Desperation's "Discard your hand at the end of the main phase":
    #: set as it resolves, read and cleared by the patrol lock that ends
    #: the main phase (step 11). False in an older save.
    discards_at_main_end: bool = False
    #: How many spells this player has played this turn -- Calypso
    #: Vystari's "If you played a spell this turn". Emptied as each of
    #: their turns begins; 0 in an older save.
    spells_played: int = 0
    #: Moment's Peace stands: their units can't patrol and opposing units
    #: can't attack them, until their next turn begins. False in an
    #: older save.
    peace: bool = False
    #: A unit has arrived from this player's hand this turn -- Drakk's "The
    #: first unit that arrives from your hand each turn". Emptied as each
    #: of their turns begins; False in an older save.
    arrived_from_hand: bool = False
    #: What a spell gives all of this side's units for a while, read
    #: continuously -- a unit arriving later has it too, one leaving
    #: their control loses it: Stampede (`{"kind": "stampede", "until":
    #: "end_of_turn"}`) and Ferocity (`"until": "upkeep"`, with its
    #: caster's `seat`) (the author, 2026-10-09).
    lasting: list = field(default_factory=list)
    #: The future (step 12, UMR p. 17): the forecast cards this player
    #: has played, each an instance with its time runes, not in play --
    #: untargetable, unaffected -- until its last rune goes and it
    #: arrives, or a spell resolves. Empty in an older save.
    future: list[CardInstance] = field(default_factory=list)
    #: Prynn Pasternaak at 4 died from fading: this player skips their next
    #: draw/discard step, keeping their hand (step 12). False in an older
    #: save.
    skip_draw: bool = False

    def patroller(self, slot: str) -> Optional[str]:
        """What patrols `slot`: `unit:<id>`, `hero:<slug>`, or `None`."""
        for hero in self.heroes:
            if hero.in_play and hero.patrol_slot == slot:
                return hero_ref(hero.slug)
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

    def hero_by_ref(self, ref: Optional[str]) -> Optional[HeroState]:
        """The hero `ref` names -- `hero:<slug>`, or an older save's bare
        `hero`, the first -- in the command zone or in play; `None` for
        anything else."""
        if ref == HERO:
            return self.heroes[0] if self.heroes else None
        if not is_hero_ref(ref):
            return None
        slug = ref[len(HERO_PREFIX):]
        return next((hero for hero in self.heroes if hero.slug == slug), None)

    def hero_of(self, slug: str) -> Optional[HeroState]:
        return next((hero for hero in self.heroes if hero.slug == slug), None)

    @property
    def heroes_in_play(self) -> list[HeroState]:
        return [hero for hero in self.heroes if hero.in_play]

    @property
    def hero(self) -> HeroState:
        """**The first hero** -- the basic game's one. For a test that
        stages a basic game, and nothing else: the model loops over
        `heroes`, since a standard game's side has three."""
        return self.heroes[0]


def _write_heroes(heroes: list) -> list:
    return [_write_hero(hero) for hero in heroes]


def _read_heroes(data: list) -> list:
    return [_read_hero(hero) for hero in data]


def _write_specs(specs) -> list:
    return list(specs)


def _read_specs(data) -> tuple:
    return tuple(data)


PLAYER_SAVED_FIELDS = (
    SavedField("seat"),
    SavedField("specs", factory=tuple, write=_write_specs, read=_read_specs),
    SavedField("heroes", factory=list, write=_write_heroes, read=_read_heroes),
    SavedField("deck_color", default="neutral"),
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
    SavedField("tech2_spec"),
    SavedField("constructed_once", default=False),
    SavedField("discards_at_main_end", default=False),
    SavedField("spells_played", default=0),
    SavedField("peace", default=False),
    SavedField("arrived_from_hand", default=False),
    SavedField("lasting", factory=list, write=_copy_dicts, read=_copy_dicts),
    SavedField("future", factory=list, write=_write_play, read=_read_play),
    SavedField("skip_draw", default=False),
)


def _write_players(players: list) -> list:
    return [_save(player, PLAYER_SAVED_FIELDS) for player in players]


def _read_player(data: dict) -> PlayerState:
    """A side as saved -- a save older than step 10 holds one `spec`
    and one `hero`, read as a team of one."""
    if "specs" not in data and "spec" in data:
        data = {**data, "specs": [data["spec"]]}
    if "heroes" not in data and "hero" in data:
        data = {**data, "heroes": [data["hero"]]}
    return PlayerState(**_load(PLAYER_SAVED_FIELDS, data))


def _read_players(data: list) -> list:
    return [_read_player(player) for player in data]


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
    #: The seat that conceded, where the game ended that way rather
    #: than on a destroyed base (`codex.flow.turn.concede`); `None`
    #: otherwise, and in a save older than step 8.
    conceded: Optional[int] = None
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
    #: The effects under way, oldest first, while one asks a choice
    #: (`codex.flow.resolve`): each a frame -- a spell's or an
    #: ability's parts with the part it stands at, Appel Stomp's
    #: question, the upkeep's order. Empty between actions.
    resolving: list[dict] = field(default_factory=list)
    #: The last three turn-start positions as dicts, oldest first.
    turn_snapshots: list[dict] = field(default_factory=list)
    #: The actions applied since this turn began, each with the random
    #: outcomes it consumed.
    journal: list[dict] = field(default_factory=list)
    #: The last number handed out to something coming to be -- a card
    #: into play, a hero's band (step 11): the order the Card FAQ's grants
    #: are applied in. 0 in an older save.
    sequence: int = 0

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

    def next_sequence(self) -> int:
        """The next number in the order things come to be."""
        self.sequence += 1
        return self.sequence

    def new_instance(self, slug: str, owner: int) -> CardInstance:
        card = CardInstance(
            id=self.next_instance_id, slug=slug, owner=owner, controller=owner,
            arrived_this_turn=True, sequence=self.next_sequence(),
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
        match = cls(**_load(MATCH_SAVED_FIELDS, data))
        upgrade_hero_refs(match)
        return match

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
        if self.conceded not in (None, 1, 2) or (self.conceded is not None and self.winner is None):
            fail(f"conceded is {self.conceded!r} with winner {self.winner!r}")
        if self.phase not in PHASES:
            fail(f"phase is {self.phase!r}")
        if self.turn < 1:
            fail(f"turn is {self.turn}")
        if len(self.turn_snapshots) > 3:
            fail("more than three turn-start snapshots are kept")

        ids = [card.id for card in self.instances()]
        ids += [card.id for player in self.players for card in player.future]
        if len(ids) != len(set(ids)):
            fail("two cards in play share an id")
        if ids and max(ids) >= self.next_instance_id:
            fail("next_instance_id would reuse an id")

        for player in self.players:
            where = f"seat {player.seat}"
            for name in ("base_hp", "gold", "workers"):
                if getattr(player, name) < 0:
                    fail(f"{where}'s {name} is below zero")
            if not player.heroes or len(player.heroes) != len(player.specs):
                fail(f"{where} has {len(player.heroes)} heroes for {len(player.specs)} specs")
            for hero in player.heroes:
                known(hero.slug, f"{where}'s hero")
            if len({hero.slug for hero in player.heroes}) != len(player.heroes):
                fail(f"{where} has one hero twice")
            for zone in ("hand", "deck", "discard"):
                for slug in getattr(player, zone):
                    known(slug, f"{where}'s {zone}")
            for slug, count in player.codex.items():
                known(slug, f"{where}'s codex")
                if count < 0:
                    fail(f"{where}'s codex holds {count} of {slug}")
            for slug in player.tech_choice or ():
                known(slug, f"{where}'s tech choice")
            slots = []
            for hero in player.heroes:
                for name in ("level", "damage", "summoning_runes", "armor", "plus_runes", "minus_runes",
                             "time_runes"):
                    if getattr(hero, name) < 0:
                        fail(f"{where}'s hero has {name} below zero")
                if hero.zone not in ("command", "play"):
                    fail(f"{where}'s hero is in {hero.zone!r}")
                if hero.patrol_slot is not None:
                    if not hero.in_play:
                        fail(f"{where}'s hero patrols from the command zone")
                    slots.append(hero.patrol_slot)
            for card in player.future:
                known(card.slug, f"{where}'s future")
                if card.time_runes < 0:
                    fail(f"card {card.id} has time runes below zero")
            for card in player.play:
                known(card.slug, f"{where}'s play zone")
                for name in ("damage", "plus_runes", "minus_runes", "armor", "time_runes"):
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
    SavedField("conceded"),
    SavedField("events", factory=list, write=_deep_copy, read=_deep_copy),
    SavedField("next_instance_id", default=1),
    SavedField("attacking"),
    SavedField("combat", write=_copy_optional_combat, read=_copy_optional_combat),
    SavedField("resolving", factory=list, write=_deep_copy, read=_deep_copy),
    SavedField("turn_snapshots", factory=list, write=_deep_copy, read=_deep_copy),
    SavedField("journal", factory=list, write=_deep_copy, read=_deep_copy),
    SavedField("sequence", default=0),
)

def upgrade_hero_refs(match: MatchState) -> None:
    """
    A save older than step 10 names a hero `hero` alone -- its side's one
    hero -- where an attack stands half-resolved, a tower has detected,
    or an effect is under way; each is rewritten `hero:<slug>`, the
    side's first hero, so the engine reads one spelling. Nothing is
    rewritten in a save that has none.
    """
    if len(match.players) != 2 or not all(player.heroes for player in match.players):
        return

    def mine(seat: int, ref):
        if ref == HERO:
            return hero_ref(match.player(seat).heroes[0].slug)
        return ref

    def key(text):
        if isinstance(text, str) and text.endswith(":" + HERO) and text[:1] in ("1", "2"):
            return f"{text[0]}:{mine(int(text[0]), HERO)}"
        return text

    active, other = match.active, (2 if match.active == 1 else 1)
    match.attacking = mine(active, match.attacking)
    if match.combat is not None:
        combat = match.combat
        for name, seat in (("attacker", active), ("defender", other), ("overpower", other)):
            if name in combat:
                combat[name] = mine(seat, combat[name])
        for name in ("obliterated", "sparks"):
            if name in combat:
                combat[name] = [mine(other, ref) for ref in combat[name]]
    for player in match.players:
        if player.add_on is not None:
            player.add_on.detected = mine(2 if player.seat == 1 else 1, player.add_on.detected)
    for frame in match.resolving:
        if "source" in frame and "seat" in frame:
            frame["source"] = mine(frame["seat"], frame["source"])
        if "taken" in frame:
            frame["taken"] = [key(item) for item in frame["taken"]]


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
