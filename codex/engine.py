"""
`RulesEngine` -- every question about a Codex position that a frontend
or the flow may ask, with no Discord in it.

D12 Ball's engine shape (`d12ball/engine.py`): the catalog, **`rng`, the
one `random.Random` every draw the game makes comes from**, and the
answers -- what the active player may do (`legal_actions`), who an
attacker may take (`legal_defenders`), who may patrol, how many cards a
draw is, how many a tech choice is. A rule is a question this answers
and the cog asks (docs/codex-bot.md, decision 3); nothing in `cogs/`
works any of these out for itself.

**The engine is vanilla in this step** (decision 7): every card is
played for its cost and its numbers, and the text of every card in
`codex.effects.UNIMPLEMENTED` is ignored -- and said to be, by the flow,
whenever such a card is played. `is_vanilla` is the question.

The rules are the Unofficial Manual Rewrite v1.3's, cited by page
(`UMR p. 8`), with Sirlin's rulings (`codex/data/rulings.json`)
governing where the two differ.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from random import Random  # the one Random; nothing reads the module's functions
from typing import Iterable, Optional, Sequence

from codex import effects
from codex.cards import CardCatalog, Hero, HeroBand, catalog as load_catalog
from codex.components import (
    HERO,
    PATROL_SLOTS,
    TECH_BUILDINGS,
    CardInstance,
    HeroState,
    MatchState,
    PlayerState,
)

#: Gold is capped (UMR p. 5).
GOLD_CAP = 20
#: A base's HP (UMR p. 3).
BASE_HP = 20
#: The opening hand, and the most a draw ever brings a hand up to
#: (UMR p. 3, 5).
HAND_SIZE = 5
#: The workers each seat starts with: the first player four, the second
#: five (UMR p. 3).
STARTING_WORKERS = {True: 4, False: 5}
#: Hiring a worker, once a turn (UMR p. 6).
HIRE_COST = 1
#: A hero level costs a gold (UMR p. 6).
LEVEL_COST = 1
#: The workers each tech building needs, and the building below it
#: that has to be standing (UMR p. 8). The costs and the HP are the
#: card data's (`tech_i_building` and its neighbours).
TECH_REQUIREMENTS = {
    "tech1": (6, None),
    "tech2": (8, "tech1"),
    "tech3": (10, "tech2"),
}
TECH_BUILDING_SLUGS = {
    "tech1": "tech_i_building",
    "tech2": "tech_ii_building",
    "tech3": "tech_iii_building",
}
#: The level of tech card each building lets its owner play.
TECH_LEVEL_BUILDING = {1: "tech1", 2: "tech2", 3: "tech3"}
#: The two add-ons of the basic game (UMR p. 9); cost and HP are the
#: card data's.
ADD_ONS = ("tower", "surplus")
#: The cards a tech choice takes, and the workers from which it may be
#: fewer (UMR p. 5).
TECH_PICKS = 2
TECH_FREE_WORKERS = 10
#: What a hero's death costs and gives (UMR p. 7).
SUMMONING_RUNES_ON_DEATH = 2
LEVELS_FOR_A_KILL = 2
#: What a destroyed tech building or add-on deals to its base (UMR p. 8).
BUILDING_DESTROYED_DAMAGE = 2
#: The patrol slots' bonuses (UMR p. 10).
SQUAD_LEADER_ARMOR = 1
ELITE_ATK = 1
SCAVENGER_GOLD = 1
TECHNICIAN_CARDS = 1

#: How the main phase's actions are named.
SUMMON = "summon"
LEVEL = "level"


# -- The engine's answers, as data --------------------------------------
#
# Frozen and made of tuples, so a prompt built from them is hashable and
# two readings of one position compare equal. `codex.prompts` carries
# them in `MainActionOptions`.


@dataclass(frozen=True)
class HireOption:
    allowed: bool
    cost: int = HIRE_COST
    why_not: str = ""

    def to_dict(self) -> dict:
        return {"allowed": self.allowed, "cost": self.cost, "why_not": self.why_not}


@dataclass(frozen=True)
class HeroOption:
    """What the active player may do with their hero: summon it for its
    cost, level it up to `max_levels` levels at a gold each, or nothing,
    and why."""

    slug: str
    action: Optional[str] = None
    cost: int = 0
    max_levels: int = 0
    why_not: str = ""

    def to_dict(self) -> dict:
        return {
            "slug": self.slug, "action": self.action, "cost": self.cost,
            "max_levels": self.max_levels, "why_not": self.why_not,
        }


@dataclass(frozen=True)
class PlayableCard:
    """A card in the hand: what it costs now, and why it may not be
    played, where it may not (`why_not` empty means it may)."""

    slug: str
    cost: int
    why_not: str = ""

    @property
    def allowed(self) -> bool:
        return not self.why_not

    def to_dict(self) -> dict:
        return {"slug": self.slug, "cost": self.cost, "why_not": self.why_not}


@dataclass(frozen=True)
class BuildOption:
    building: str
    cost: int
    workers_needed: int = 0
    why_not: str = ""

    @property
    def allowed(self) -> bool:
        return not self.why_not

    def to_dict(self) -> dict:
        return {
            "building": self.building, "cost": self.cost,
            "workers_needed": self.workers_needed, "why_not": self.why_not,
        }


@dataclass(frozen=True)
class LegalActions:
    hire: HireOption
    hero: HeroOption
    playable: tuple[PlayableCard, ...]
    buildings: tuple[BuildOption, ...]
    attackers: tuple[str, ...]
    end_main: bool = True


class RulesEngine:
    def __init__(self, catalog: Optional[CardCatalog] = None, seed: Optional[int] = None) -> None:
        self.catalog = catalog or load_catalog()
        self.rng = Random(seed)
        #: Shuffle orders handed back in place of drawing, while a
        #: journal is replayed (`codex.history.replay`). Set and emptied
        #: by `codex.flow.driver.apply`; nothing else touches it.
        self.replaying: list[list[str]] = []

    # -- Randomness ----------------------------------------------------

    def shuffle(self, cards: Sequence[str], recorded: Optional[Sequence[str]] = None) -> list[str]:
        """
        `cards` in a new order -- **the only shuffle**. Drawn from `rng`,
        or taken back from `recorded` (or the next of `replaying`), so a
        replayed turn deals exactly what it dealt (decision 11).
        """
        if recorded is None and self.replaying:
            recorded = self.replaying.pop(0)
        if recorded is not None:
            if Counter(recorded) != Counter(cards):
                raise ValueError("a recorded shuffle is not an order of these cards")
            return list(recorded)
        order = list(cards)
        self.rng.shuffle(order)
        return order

    # -- The opening -----------------------------------------------------

    def new_match(self, seats: Sequence[str], first: Optional[int] = None) -> MatchState:
        """
        The opening position of the basic game (UMR p. 3): each seat's
        hero in the command zone, the ten neutral starters shuffled as
        its deck and five dealt, its spec's codex of twenty-four, a base
        at 20, and four workers for whoever goes first and five for the
        other -- who goes first drawn at random unless given.
        """
        if first is None:
            first = self.rng.choice((1, 2))
        players = []
        for seat, spec in enumerate(seats, start=1):
            hero = self.catalog.hero_for(spec)
            deck = self.shuffle(self.catalog.starting_deck("neutral"))
            hand = [deck.pop() for _ in range(HAND_SIZE)]
            players.append(PlayerState(
                seat=seat,
                spec=spec.lower(),
                hero=HeroState(slug=hero.slug),
                base_hp=BASE_HP,
                workers=STARTING_WORKERS[seat == first],
                hand=hand,
                deck=deck,
                codex=dict(Counter(self.catalog.codex_for(spec))),
            ))
        return MatchState(players=players, first=first, active=first)

    # -- Numbers ---------------------------------------------------------

    def hero_card(self, hero: HeroState) -> Hero:
        return self.catalog.heroes[hero.slug]

    def hero_band(self, hero: HeroState) -> HeroBand:
        return self.hero_card(hero).band(hero.level)

    def hero_stats(self, hero: HeroState) -> tuple[int, int]:
        """The hero's ATK and HP at its level's band."""
        band = self.hero_band(hero)
        return band.atk, band.hp

    def unit_stats(self, card: CardInstance) -> tuple[int, int]:
        """
        A unit's ATK and HP: printed, then its runes -- a +1/+1 and a
        -1/-1 cancel (UMR p. 13) -- then this turn's modifiers (none
        until step 6). ATK is never below 0.
        """
        printed = self.catalog.cards[card.slug]
        runes = card.plus_runes - card.minus_runes
        atk = (printed.atk or 0) + runes
        hp = (printed.hp or 0) + runes
        for modifier in card.modifiers:
            if modifier.get("kind") == "atk":
                atk += modifier.get("amount", 0)
            elif modifier.get("kind") == "hp":
                hp += modifier.get("amount", 0)
        return max(atk, 0), hp

    def attack_value(self, match: MatchState, seat: int, ref: str) -> int:
        """
        What `ref` on `seat`'s side deals in combat: its ATK, and the
        elite's +1 while it patrols there (UMR p. 10). A building deals
        nothing.
        """
        player = match.player(seat)
        if ref == HERO:
            atk = self.hero_stats(player.hero)[0]
            slot = player.hero.patrol_slot
        elif ref.startswith("unit:"):
            card = player.instance(int(ref.split(":", 1)[1]))
            atk = self.unit_stats(card)[0]
            slot = card.patrol_slot
        else:
            return 0
        return atk + (ELITE_ATK if slot == "elite" else 0)

    def is_vanilla(self, slug: str) -> bool:
        """Whether the engine plays this card for its numbers alone:
        its text is in `effects.UNIMPLEMENTED`, or it has none."""
        if slug in effects.UNIMPLEMENTED:
            return True
        card = self.catalog.by_slug(slug)
        if isinstance(card, Hero):
            return not any(band.text for band in card.bands)
        return not card.text

    def effective_cost(self, player: PlayerState, slug: str) -> int:
        """What a card costs this player now: its printed cost, until
        step 6 brings the reductions."""
        return self.catalog.cards[slug].cost or 0

    def draw_count(self, discarded: int) -> int:
        """Two more than were discarded, to at most five (UMR p. 5)."""
        return min(discarded + 2, HAND_SIZE)

    def tech_bounds(self, player: PlayerState) -> tuple[int, int]:
        """
        How many cards a tech choice takes: exactly two, or anything from
        none to two once the player has ten workers (UMR p. 5) -- never
        more than the codex still holds.
        """
        left = sum(player.codex.values())
        most = min(TECH_PICKS, left)
        if player.workers >= TECH_FREE_WORKERS:
            return 0, most
        return most, most

    # -- Buildings --------------------------------------------------------

    def tech_building_active(self, player: PlayerState, level: int) -> bool:
        """Whether `player` may play tech `level` cards: tech 0 always,
        otherwise the building of that level finished and standing."""
        if not level:
            return True
        building = player.buildings.get(TECH_LEVEL_BUILDING[level])
        return building is not None and building.active

    def building_cost(self, player: PlayerState, building: str) -> int:
        if building in TECH_BUILDINGS:
            existing = player.buildings[building]
            if existing is not None and existing.destroyed:
                return 0  # rebuilt for nothing (UMR p. 8)
            return self.catalog.building(TECH_BUILDING_SLUGS[building]).cost or 0
        return self.catalog.building(building).cost or 0

    def building_hp(self, building: str) -> int:
        slug = TECH_BUILDING_SLUGS.get(building, building)
        return self.catalog.building(slug).hp or 0

    def build_option(self, player: PlayerState, building: str) -> BuildOption:
        cost = self.building_cost(player, building)
        if building in TECH_BUILDINGS:
            workers, below = TECH_REQUIREMENTS[building]
            existing = player.buildings[building]
            why = ""
            if existing is not None and not existing.destroyed:
                why = "it is already built"
            elif player.workers < workers:
                why = f"it needs {workers} workers"
            elif below is not None and not (
                player.buildings[below] is not None and player.buildings[below].active
            ):
                why = f"it needs a finished {_building_name(below)} building"
            elif player.gold < cost:
                why = "not enough gold"
            return BuildOption(building, cost, workers, why)
        why = ""
        if player.add_on is not None:
            why = "the add-on slot is taken"
        elif player.gold < cost:
            why = "not enough gold"
        return BuildOption(building, cost, 0, why)

    # -- The main phase -----------------------------------------------------

    def hire_option(self, player: PlayerState) -> HireOption:
        if player.hired_this_turn:
            return HireOption(False, why_not="a worker has been hired this turn")
        if player.gold < HIRE_COST:
            return HireOption(False, why_not="not enough gold")
        if not player.hand:
            return HireOption(False, why_not="there is no card in hand to hire with")
        return HireOption(True)

    def hero_option(self, player: PlayerState) -> HeroOption:
        hero = player.hero
        card = self.hero_card(hero)
        if not hero.in_play:
            if hero.summoning_runes:
                return HeroOption(
                    hero.slug, why_not=f"it has {hero.summoning_runes} summoning rune"
                    + ("s" if hero.summoning_runes != 1 else ""),
                )
            if player.gold < card.cost:
                return HeroOption(hero.slug, SUMMON, card.cost, why_not="not enough gold")
            return HeroOption(hero.slug, SUMMON, card.cost)
        room = card.max_level - hero.level
        if not room:
            return HeroOption(hero.slug, why_not="it is at its maximum level")
        levels = min(room, player.gold // LEVEL_COST)
        if not levels:
            return HeroOption(hero.slug, LEVEL, LEVEL_COST, why_not="not enough gold")
        return HeroOption(hero.slug, LEVEL, LEVEL_COST, levels)

    def why_not_playable(self, player: PlayerState, slug: str) -> str:
        """Why `player` may not play `slug` from their hand now, or ""."""
        card = self.catalog.cards[slug]
        cost = self.effective_cost(player, slug)
        if card.is_unit:
            if not self.tech_building_active(player, card.tech_level or 0):
                return f"it needs a finished {_building_name(TECH_LEVEL_BUILDING[card.tech_level])} building"
        elif card.is_spell:
            hero = player.hero
            if not hero.in_play:
                return "a spell needs a hero in play"
            spec = self.hero_card(hero).spec
            if card.spec and (spec or "").lower() != card.spec.lower():
                return f"it needs the {card.spec} hero"
            if "Ultimate" in card.type and not hero.max_level_since_turn_began:
                return "an ultimate needs a hero at maximum level since the turn began"
        else:
            return "it is not a card that is played"
        if player.gold < cost:
            return "not enough gold"
        return ""

    def playable(self, player: PlayerState) -> tuple[PlayableCard, ...]:
        """Every card in the hand once, in the hand's order, with its cost
        and whether it may be played."""
        seen = []
        rows = []
        for slug in player.hand:
            if slug in seen:
                continue
            seen.append(slug)
            rows.append(PlayableCard(slug, self.effective_cost(player, slug),
                                     self.why_not_playable(player, slug)))
        return tuple(rows)

    def attackers(self, match: MatchState) -> tuple[str, ...]:
        """The active player's units and hero that may attack: in play,
        ready, and not fatigued from arriving this turn (UMR p. 10)."""
        player = match.active_player
        found = [
            card.ref for card in player.play
            if self.catalog.cards[card.slug].is_unit
            and not card.exhausted and not card.arrived_this_turn
        ]
        hero = player.hero
        if hero.in_play and not hero.exhausted and not hero.arrived_this_turn:
            found.append(HERO)
        return tuple(found)

    def legal_actions(self, match: MatchState) -> LegalActions:
        player = match.active_player
        return LegalActions(
            hire=self.hire_option(player),
            hero=self.hero_option(player),
            playable=self.playable(player),
            buildings=tuple(
                self.build_option(player, building)
                for building in (*TECH_BUILDINGS, *ADD_ONS)
            ),
            attackers=self.attackers(match),
        )

    # -- Combat ---------------------------------------------------------------

    def legal_defenders(self, match: MatchState, attacker: str) -> tuple[str, ...]:
        """
        Who `attacker` may take, in the three priorities (UMR p. 10): the
        squad leader alone while there is one; otherwise any patroller;
        otherwise anything with HP -- the units and hero in play, the tech
        buildings and add-on standing, and the base. Flying, stealth and
        the rest change this in step 5.
        """
        defending = match.opponent(match.active)
        leader = defending.patroller("squad_leader")
        if leader is not None:
            return (leader,)
        patrollers = defending.patrollers()
        if patrollers:
            return tuple(patrollers[slot] for slot in PATROL_SLOTS if slot in patrollers)
        found = [card.ref for card in defending.play if self.catalog.cards[card.slug].is_unit]
        if defending.hero.in_play:
            found.append(HERO)
        found.extend(
            name for name in TECH_BUILDINGS
            if defending.buildings[name] is not None and not defending.buildings[name].destroyed
        )
        if defending.add_on is not None:
            found.append("add_on")
        found.append("base")
        return tuple(found)

    def patrol_candidates(self, match: MatchState) -> tuple[str, ...]:
        """What the active player may lock into the patrol zone: ready
        units and a ready hero; arrival fatigue does not stop a patroller
        (UMR p. 10)."""
        player = match.active_player
        found = [
            card.ref for card in player.play
            if self.catalog.cards[card.slug].is_unit and not card.exhausted
        ]
        if player.hero.in_play and not player.hero.exhausted:
            found.append(HERO)
        return tuple(found)

    def codex_counts(self, player: PlayerState) -> tuple[tuple[str, int], ...]:
        """The player's codex, as (slug, copies left), in the data's order."""
        order = list(dict.fromkeys(self.catalog.codex_for(player.spec)))
        return tuple((slug, player.codex.get(slug, 0)) for slug in order)

    def name(self, slug: str) -> str:
        return self.catalog.name(slug)


def _building_name(building: str) -> str:
    return {"tech1": "Tech I", "tech2": "Tech II", "tech3": "Tech III"}.get(building, building)


def building_name(building: str) -> str:
    """A building slot in words: "Tech II", "tower", "base"."""
    if building in TECH_BUILDINGS:
        return _building_name(building)
    return {"add_on": "add-on", "base": "base"}.get(building, building)


def unit_ref(ref: str) -> Optional[int]:
    """The instance id of a `unit:<id>` ref, or `None` for anything else."""
    if ref.startswith("unit:"):
        try:
            return int(ref.split(":", 1)[1])
        except ValueError:
            return None
    return None


def refs(cards: Iterable[CardInstance]) -> tuple[str, ...]:
    return tuple(card.ref for card in cards)
