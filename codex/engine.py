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

from codex import effects, keywords
from codex.cards import CardCatalog, Hero, HeroBand, catalog as load_catalog
from codex.components import (
    HERO,
    AddOnState,
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
#: The views a codex is shown through (`RulesEngine.codex_views`).
CODEX_VIEWS = ("everything", "tech1", "tech2", "tech3", "spells")
#: What a hero's death costs and gives (UMR p. 7).
SUMMONING_RUNES_ON_DEATH = 2
LEVELS_FOR_A_KILL = 2
#: What a destroyed tech building or add-on deals to its base (UMR p. 8).
BUILDING_DESTROYED_DAMAGE = 2
#: What the tower does on its owner's behalf (UMR p. 9): one damage to
#: each attacker it can see, and one detection a turn.
TOWER = "tower"
TOWER_DAMAGE = 1
#: Sparkshot's damage to a neighbouring patroller (UMR p. 18).
SPARKSHOT_DAMAGE = 1
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
class DetectOption:
    """The tower's detection on its owner's own turn (UMR p. 9): one
    opposing stealth or invisible card named for the rest of the turn,
    once a turn."""

    allowed: bool = False
    candidates: tuple[str, ...] = ()
    why_not: str = ""
    #: Whether this player has a finished tower at all -- whether the
    #: action is theirs to be offered, disabled or not.
    tower: bool = False

    def to_dict(self) -> dict:
        return {
            "allowed": self.allowed, "candidates": list(self.candidates),
            "why_not": self.why_not, "tower": self.tower,
        }


@dataclass(frozen=True)
class LegalActions:
    hire: HireOption
    hero: HeroOption
    playable: tuple[PlayableCard, ...]
    buildings: tuple[BuildOption, ...]
    attackers: tuple[str, ...]
    end_main: bool = True
    detect: DetectOption = DetectOption()


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
        What `ref` on `seat`'s side deals in combat: its ATK, the elite's
        +1 while it patrols there (UMR p. 10), and frenzy X on its
        controller's own turn (UMR p. 16). A building deals nothing.
        """
        player = match.player(seat)
        if ref == HERO:
            body = player.hero
            atk = self.hero_stats(body)[0]
        elif ref.startswith("unit:"):
            body = player.instance(int(ref.split(":", 1)[1]))
            atk = self.unit_stats(body)[0]
        else:
            return 0
        if body.patrol_slot == "elite":
            atk += ELITE_ATK
        if seat == match.active:
            atk += self.keyword_x(body, "Frenzy")
        return atk

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
        # A new add-on replaces the one in the slot, which deals its 2 to
        # the base (UMR p. 9; the author, 2026-10-08) -- the same one again
        # is no replacement.
        why = ""
        if player.add_on is not None and player.add_on.slug == building:
            why = "it is already built"
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

    def may_attack_with(self, body) -> bool:
        """
        Whether a unit or hero in play may attack: ready, and either not
        fatigued from arriving this turn or hasted (UMR p. 10, 16), and
        -- for readiness, which does not exhaust -- not having attacked
        already this turn (UMR p. 17).
        """
        if body.exhausted:
            return False
        if body.arrived_this_turn and not self.has_keyword(body, "Haste"):
            return False
        if body.attacked_this_turn:
            return False
        return True

    def attackers(self, match: MatchState) -> tuple[str, ...]:
        """The active player's units and hero that may attack
        (`may_attack_with`)."""
        player = match.active_player
        found = [
            card.ref for card in player.play
            if self.catalog.cards[card.slug].is_unit and self.may_attack_with(card)
        ]
        hero = player.hero
        if hero.in_play and self.may_attack_with(hero):
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
            detect=self.detect_option(match),
        )

    # -- The keywords -----------------------------------------------------------
    #
    # The closed table of decision 7 (`codex.keywords`), read here and
    # nowhere else: a keyword is a question this engine answers about a
    # position, and the flow and the frontend ask it. The rules are UMR
    # p. 14, 16-18, with Sirlin's rulings governing (docs/design/codex.md,
    # "The keywords").

    def body(self, match: MatchState, seat: int, ref: str):
        """
        The unit or hero `ref` names on `seat`'s side -- `None` for a
        building, the base and the add-on, which have no keywords of
        their own (the tower's are the add-on's, read where it acts).
        """
        player = match.player(seat)
        if ref == HERO:
            return player.hero if player.hero.in_play else None
        instance_id = unit_ref(ref)
        if instance_id is None:
            return None
        return player.instance(instance_id)

    def has_keyword(self, body, keyword: str) -> bool:
        """Whether a thing in play has `keyword` -- the one reading, over
        `codex.keywords`."""
        return body is not None and keywords.has_keyword(body, keyword)

    def keyword_x(self, body, keyword: str) -> int:
        return 0 if body is None else keywords.keyword_x(body, keyword)

    def has(self, match: MatchState, seat: int, ref: str, keyword: str) -> bool:
        """Whether what `ref` names on `seat`'s side has `keyword`."""
        return self.has_keyword(self.body(match, seat, ref), keyword)

    def resist_cost(self, match: MatchState, seat: int, ref: str) -> int:
        """
        What an opponent pays to target what `ref` names on `seat`'s side
        (UMR p. 18): its resist, the lookout's 1 among it, and it stacks.
        The payment itself is step 6's targeting.
        """
        return self.keyword_x(self.body(match, seat, ref), "Resist")

    def healing(self, player: PlayerState) -> int:
        """How much damage this player's upkeep heals off each of their
        units and heroes (UMR p. 17): every healing X they control,
        each healing once."""
        total = sum(self.keyword_x(card, "Healing") for card in player.play)
        if player.hero.in_play:
            total += self.keyword_x(player.hero, "Healing")
        return total

    # -- The tower ------------------------------------------------------------

    def tower(self, player: PlayerState) -> Optional[AddOnState]:
        """This player's tower, finished and standing, or `None`
        (UMR p. 9)."""
        add_on = player.add_on
        if add_on is not None and add_on.slug == TOWER and add_on.active:
            return add_on
        return None

    def hidden(self, match: MatchState, seat: int, ref: str) -> str:
        """`"invisible"`, `"stealth"` or `""` -- how what `ref` names on
        `seat`'s side is hidden (UMR p. 17, 18)."""
        body = self.body(match, seat, ref)
        if self.has_keyword(body, "Invisible"):
            return "invisible"
        if self.has_keyword(body, "Stealth"):
            return "stealth"
        return ""

    def detected_by(self, match: MatchState, watcher: int, ref: str) -> bool:
        """
        Whether `watcher`'s detector sees what `ref` names: their tower
        has detected that card this turn, and a detection lasts the rest
        of the turn (Sirlin, 2016-03-14).

        A tower whose detection is still unspent already sees the
        opponent's attackers, because "on an opponent's turn, your tower
        uses its detect ability the first time it can" (Sirlin,
        2016-03-14) -- so a hidden attacker cannot sneak past a tower that
        has not detected yet, and the attack spends the detection
        (`tower_detects`). On its owner's own turn a tower sees only what
        it has detected, which is the `detect` action's to name.
        """
        tower = self.tower(match.player(watcher))
        if tower is None:
            return False
        if tower.detected == ref:
            return True
        return tower.detected is None and watcher != match.active

    def tower_detects(self, match: MatchState, attacker: str) -> bool:
        """
        Whether the defending tower uses its detection on this attacker:
        the attacker is hidden and the tower has not detected anything
        this turn. "On an opponent's turn, your tower uses its detect
        ability the first time it can" (Sirlin, 2016-03-14) -- so it
        fires even on an attacker that is also unstoppable, which it then
        damages without stopping (Sirlin, 2016-03-19).
        """
        other = 2 if match.active == 1 else 1
        tower = self.tower(match.player(other))
        if tower is None or tower.detected is not None:
            return False
        return bool(self.hidden(match, match.active, attacker))

    def tower_sees(self, match: MatchState, attacker: str) -> bool:
        """Whether the defending tower can see this attacker, and so
        deals its damage to it (UMR p. 9): anything not hidden, and a
        hidden thing it detected this turn."""
        other = 2 if match.active == 1 else 1
        if self.tower(match.player(other)) is None:
            return False
        if not self.hidden(match, match.active, attacker):
            return True
        return self.detected_by(match, other, attacker)

    def detect_option(self, match: MatchState) -> DetectOption:
        """
        The tower's detection as an action on its owner's own turn
        (UMR p. 9): one opposing stealth or invisible card, named for the
        rest of the turn, once a turn.
        """
        seat = match.active
        other = 2 if seat == 1 else 1
        tower = self.tower(match.active_player)
        if tower is None:
            return DetectOption(why_not="you have no finished tower")
        if tower.detected is not None:
            return DetectOption(why_not="your tower has detected this turn", tower=True)
        candidates = []
        for ref in self._things_in_play(match, other):
            if self.hidden(match, other, ref) and not self.detected_by(match, seat, ref):
                candidates.append(ref)
        if not candidates:
            return DetectOption(why_not="nothing of theirs is hidden", tower=True)
        return DetectOption(True, tuple(candidates), tower=True)

    # -- Combat ---------------------------------------------------------------

    def _things_in_play(self, match: MatchState, seat: int) -> tuple[str, ...]:
        """The units and the hero on `seat`'s side, as refs."""
        player = match.player(seat)
        found = [card.ref for card in player.play if self.catalog.cards[card.slug].is_unit]
        if player.hero.in_play:
            found.append(HERO)
        return tuple(found)

    def _standing(self, match: MatchState, seat: int) -> tuple[str, ...]:
        """Everything on `seat`'s side with HP: the units and hero in
        play, the tech buildings and add-on standing, and the base."""
        player = match.player(seat)
        found = list(self._things_in_play(match, seat))
        found.extend(
            name for name in TECH_BUILDINGS
            if player.buildings[name] is not None and not player.buildings[name].destroyed
        )
        if player.add_on is not None:
            found.append("add_on")
        found.append("base")
        return tuple(found)

    def may_be_attacked(self, match: MatchState, attacker: str, target: str) -> bool:
        """
        Whether the active player's `attacker` may attack `target` on the
        other side: a building always; a flier only by a flier or an
        anti-air attacker (UMR p. 16); an invisible card not patrolling
        only by somebody with a detector (UMR p. 17).
        """
        seat = match.active
        other = 2 if seat == 1 else 1
        body = self.body(match, other, target)
        if body is None:
            return True
        if (
            self.has_keyword(body, "Invisible")
            and body.patrol_slot is None
            and not self.detected_by(match, seat, target)
        ):
            return False
        if self.has_keyword(body, "Flying"):
            hitting = self.body(match, seat, attacker)
            if not (self.has_keyword(hitting, "Flying") or self.has_keyword(hitting, "Anti-air")):
                return False
        return True

    def ignores_patrollers(self, match: MatchState, attacker: str) -> str:
        """
        Why this attacker may ignore the patrol zone altogether, or `""`:
        `"unstoppable"` (UMR p. 18), or `"stealth"` / `"invisible"` while
        no detector of theirs sees it -- "sneaking past" (Sirlin,
        2016-03-14). Flying is not here: a flier is stopped by a flying
        patroller.
        """
        seat = match.active
        other = 2 if seat == 1 else 1
        body = self.body(match, seat, attacker)
        if body is None:
            return ""
        if self.has_keyword(body, "Unstoppable"):
            return "unstoppable"
        hidden = self.hidden(match, seat, attacker)
        if hidden and not self.detected_by(match, other, attacker):
            return hidden
        return ""

    def blocking_patrollers(self, match: MatchState, attacker: str) -> dict[str, str]:
        """
        Slot to patroller, for the patrollers that stop this attacker: a
        flier is stopped by flying patrollers alone, a ground attacker by
        ground ones alone -- "you only stop an attacker if it's on the
        same level as you" (Sirlin, 2016-03-14) -- and nothing stops one
        that sneaks past or is unstoppable. An anti-air ground patroller
        may attack a flier but is not forced to, so it stops none.
        """
        if self.ignores_patrollers(match, attacker):
            return {}
        seat = match.active
        other = 2 if seat == 1 else 1
        flying = self.has(match, seat, attacker, "Flying")
        blocking = {}
        for slot, ref in match.player(other).patrollers().items():
            if self.has(match, other, ref, "Flying") != flying:
                continue
            if not self.may_be_attacked(match, attacker, ref):
                continue
            blocking[slot] = ref
        return blocking

    def legal_defenders(self, match: MatchState, attacker: str) -> tuple[str, ...]:
        """Who `attacker` may take, in the three priorities (UMR p. 10),
        as the keywords change them (`defender_rows`)."""
        return tuple(ref for ref, _ in self.defender_rows(match, attacker))

    def defender_rows(self, match: MatchState, attacker: str) -> tuple[tuple[str, str], ...]:
        """
        `legal_defenders`, each with why it is legal -- the priority that
        makes it so (UMR p. 10), for a frontend to say beside it: the
        squad leader alone while one stops this attacker, then any
        patroller that stops it, then anything of theirs with HP it can
        attack, with why the patrol zone does not hold it.
        """
        other = 2 if match.active == 1 else 1
        blocking = self.blocking_patrollers(match, attacker)
        if blocking:
            leader = blocking.get("squad_leader")
            if leader is not None:
                return ((leader, "squad leader"),)
            return tuple(
                (blocking[slot], "patroller") for slot in PATROL_SLOTS if slot in blocking
            )
        why = self._open_why(match, attacker)
        return tuple(
            (ref, why) for ref in self._standing(match, other)
            if self.may_be_attacked(match, attacker, ref)
        )

    def _open_why(self, match: MatchState, attacker: str) -> str:
        """Why nothing in the patrol zone holds this attacker."""
        other = 2 if match.active == 1 else 1
        if not match.player(other).patrollers():
            return "nothing is patrolling"
        sneaking = self.ignores_patrollers(match, attacker)
        if sneaking == "unstoppable":
            return "it is unstoppable"
        if sneaking:
            return "it sneaks past the patrol zone"
        if self.has(match, match.active, attacker, "Flying"):
            return "it flies over the patrol zone"
        return "no patroller can stop it"

    def flown_over(self, match: MatchState, attacker: str, defender: str) -> tuple[str, ...]:
        """
        The patrollers this flier flew over to reach `defender`, each of
        which deals its combat damage to it if it has anti-air (Sirlin,
        2016-03-14). A flier flies over the ground patrollers it had to
        get past: every one of them when it attacks something that is not
        patrolling, and the squad leader alone when it attacks another
        patroller -- the patrollers of its own priority were never in its
        way. Nothing is flown over where the attacker could ignore the
        patrol zone without flying: "no fly over happened there".
        """
        seat = match.active
        other = 2 if seat == 1 else 1
        if not self.has(match, seat, attacker, "Flying"):
            return ()
        if self.ignores_patrollers(match, attacker):
            return ()
        patrollers = match.player(other).patrollers()
        slot_of = {ref: slot for slot, ref in patrollers.items()}
        taken = slot_of.get(defender)
        over = []
        for slot, ref in patrollers.items():
            if ref == defender or self.has(match, other, ref, "Flying"):
                continue
            if taken is not None and slot != "squad_leader":
                continue
            over.append(ref)
        return tuple(over)

    def damage_back(self, match: MatchState, attacker: str, defender: str) -> int:
        """
        What the defender deals back (UMR p. 11): its ATK -- nothing for a
        building, and nothing at all to a flier from a ground defender
        without anti-air, which "cannot even attack a flier" (Sirlin,
        2016-03-14).
        """
        seat = match.active
        other = 2 if seat == 1 else 1
        body = self.body(match, other, defender)
        if body is None:
            return 0
        if self.has(match, seat, attacker, "Flying") and not (
            self.has_keyword(body, "Flying") or self.has_keyword(body, "Anti-air")
        ):
            return 0
        return self.attack_value(match, other, defender)

    def patrol_slot_of(self, match: MatchState, seat: int, ref: str) -> Optional[str]:
        body = self.body(match, seat, ref)
        return None if body is None else body.patrol_slot

    def sparkshot_candidates(self, match: MatchState, attacker: str,
                             defender: str) -> tuple[str, ...]:
        """
        The patrollers a sparkshot attacker's 1 damage may go to: the
        filled slots one over from the slot it attacked, and no further
        -- "It can't hit something two slots away even if it's the
        closest patroller" (Sirlin, 2016-03-11). A flier among them is
        included, anti-air or not (Sirlin, 2016-03-14).
        """
        seat = match.active
        other = 2 if seat == 1 else 1
        if not self.has(match, seat, attacker, "Sparkshot"):
            return ()
        slot = self.patrol_slot_of(match, other, defender)
        if slot is None:
            return ()
        patrollers = match.player(other).patrollers()
        index = PATROL_SLOTS.index(slot)
        found = []
        for step in (-1, 1):
            beside = index + step
            if 0 <= beside < len(PATROL_SLOTS):
                ref = patrollers.get(PATROL_SLOTS[beside])
                if ref is not None:
                    found.append(ref)
        return tuple(found)

    def overpower_excess(self, match: MatchState, attacker: str, defender: str) -> int:
        """
        The combat damage beyond the remaining HP of what was attacked
        (Sirlin, 2016-03-14) -- counted whether it dies or not, and only
        against a patroller, since "overpower does nothing when you
        attack a non-patroller".
        """
        seat = match.active
        other = 2 if seat == 1 else 1
        if not self.has(match, seat, attacker, "Overpower"):
            return 0
        if self.patrol_slot_of(match, other, defender) is None:
            return 0
        body = self.body(match, other, defender)
        if body is None:
            return 0
        hp = (self.unit_stats(body)[1] if isinstance(body, CardInstance)
              else self.hero_stats(body)[1])
        # The excess is counted against its remaining HP, whether it dies
        # or not and whatever armour prevents (Sirlin, 2016-03-14).
        left = max(0, hp - body.damage)
        return max(0, self.attack_value(match, seat, attacker) - left)

    def overpower_candidates(self, match: MatchState, attacker: str,
                             defender: str) -> tuple[str, ...]:
        """
        Where overpower's excess may go: one other thing this attacker
        could have attacked, the other patrollers it could have taken
        first and anything of theirs with HP only where there are none
        (Sirlin, 2016-09-13). It never cascades past one (Sirlin,
        2016-03-14).
        """
        seat = match.active
        other = 2 if seat == 1 else 1
        if not self.overpower_excess(match, attacker, defender):
            return ()
        patrollers = [
            ref for slot, ref in match.player(other).patrollers().items()
            if ref != defender and self.may_be_attacked(match, attacker, ref)
        ]
        if patrollers:
            return tuple(patrollers)
        return tuple(
            ref for ref in self._standing(match, other)
            if ref != defender and self.may_be_attacked(match, attacker, ref)
        )

    def obliterate_count(self, match: MatchState, attacker: str) -> int:
        """Obliterate's X on this attacker (UMR p. 17)."""
        return self.keyword_x(self.body(match, match.active, attacker), "Obliterate")

    def obliterate_candidates(self, match: MatchState) -> tuple[str, ...]:
        """
        The defending player's lowest-tech units -- what obliterate
        destroys, the attacker choosing between equals (UMR p. 17).
        Obliterate never targets, so resist and invisibility do not help
        against it (Sirlin, 2016-03-14), and heroes are not units.
        """
        other = 2 if match.active == 1 else 1
        units = [
            card for card in match.player(other).play
            if self.catalog.cards[card.slug].is_unit
        ]
        if not units:
            return ()
        lowest = min(self.catalog.cards[card.slug].tech_level or 0 for card in units)
        return tuple(
            card.ref for card in units
            if (self.catalog.cards[card.slug].tech_level or 0) == lowest
        )

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

    # -- What a player is shown of their own cards ------------------------

    def codex_views(self, player: PlayerState) -> tuple[str, ...]:
        """
        The views a player's codex is shown through -- everything, a
        tech level, or the spells (the author, 2026-10-08: "a lot of
        cards", so a menu rather than one picture). The standard game
        adds one per spec (step 9).
        """
        return CODEX_VIEWS

    def codex_remaining(self, match: MatchState, seat: int,
                        view: str = "everything") -> tuple[tuple[str, int], ...]:
        """
        What `seat`'s codex still holds -- (slug, copies left), every
        card of it, in the data's order, a card with none left at 0 --
        narrowed to `view` (`codex_views`). **Its owner's alone**: which
        cards are still in a codex is fog of war (UMR p. 5).
        """
        if view not in CODEX_VIEWS:
            raise ValueError(f"not a codex view: {view!r}")
        rows = self.codex_counts(match.player(seat))
        if view == "everything":
            return rows

        def shown(slug: str) -> bool:
            card = self.catalog.cards[slug]
            if view == "spells":
                return card.is_spell
            return card.is_unit and card.tech_level == int(view[-1])

        return tuple(row for row in rows if shown(row[0]))

    def hand_rows(self, match: MatchState, seat: int) -> tuple[PlayableCard, ...]:
        """
        `seat`'s hand, card by card in its order with duplicates kept,
        each with its cost after reductions and why it may not be played
        now -- "" where it may. Nothing is playable but in the active
        player's main phase. **Its owner's alone.**
        """
        player = match.player(seat)
        mine = match.active == seat and match.phase == "main" and match.winner is None
        rows = []
        for slug in player.hand:
            why = self.why_not_playable(player, slug) if mine else "it is not your main phase"
            rows.append(PlayableCard(slug, self.effective_cost(player, slug), why))
        return tuple(rows)

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
