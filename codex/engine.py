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

**Every card does what it says since step 6** (decision 7): its
keywords through `codex.keywords`, its triggers, spells and abilities
through `codex.effects`' tables, and the static texts -- the grants,
the cost reductions, the bonuses -- asked here, of the position, where
a frontend and the flow both read them: `unit_stats` and
`body_keywords` take the match, since what a card is depends on what
else is in play. `codex.effects.UNIMPLEMENTED` is empty; `is_vanilla`
still answers for a card with no text at all.

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
    hero_ref,
    is_hero_ref,
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
#: The four add-ons (UMR p. 9), cost and HP the card data's: the basic
#: game constructs the first two alone (UMR p. 3), the standard game all
#: four (`RulesEngine.add_ons`).
ADD_ONS = ("tower", "surplus", "heroes_hall", "tech_lab")
BASIC_ADD_ONS = ("tower", "surplus")
TECH_LAB = "tech_lab"
#: What a multicolour team's first tech building or add-on costs on top
#: (UMR pp. 4, 8, 9).
MULTICOLOR_SURCHARGE = 1
#: The cards a tech choice takes, and the workers from which it may be
#: fewer (UMR p. 5).
TECH_PICKS = 2
TECH_FREE_WORKERS = 10
#: The views a codex is shown through (`RulesEngine.codex_views`): the
#: whole, one tech level, the spells -- and, for a deck of more than one
#: spec, one spec, as `spec:<key>` (`spec_view`).
CODEX_VIEWS = ("everything", "tech1", "tech2", "tech3", "spells")
SPEC_VIEW_PREFIX = "spec:"


def spec_view(spec: str) -> str:
    """The view of one spec's codex: "spec:anarchy"."""
    return SPEC_VIEW_PREFIX + spec.strip().lower()


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
#: The add-on that raises the hero limit (UMR p. 9).
HEROES_HALL = "heroes_hall"
#: What a starting spell of another colour than every hero in play
#: costs on top (UMR pp. 4, 7).
WRONG_COLOR_SURCHARGE = 1


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
    """What the active player may do with one of their heroes: summon it
    for its cost, level it up to `max_levels` levels at a gold each, or
    nothing, and why -- `action` names what the button would do even
    where `why_not` says it may not now."""

    slug: str
    action: Optional[str] = None
    cost: int = 0
    max_levels: int = 0
    why_not: str = ""

    @property
    def allowed(self) -> bool:
        return self.action is not None and not self.why_not

    def to_dict(self) -> dict:
        return {
            "slug": self.slug, "action": self.action, "cost": self.cost,
            "max_levels": self.max_levels, "why_not": self.why_not,
        }


@dataclass(frozen=True)
class OwnDeck:
    """A player's whole deck (`RulesEngine.own_deck`): (slug, copies)
    for every card they own, how many copies of each are in their hand
    (`in_hand`, in the same order), and how many are in each place."""

    cards: tuple[tuple[str, int], ...]
    in_hand: tuple[int, ...]
    hand: int
    draw_pile: int
    discard: int
    in_play: int

    @property
    def size(self) -> int:
        return self.hand + self.draw_pile + self.discard + self.in_play


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
    """
    A building that may be constructed, at the cost it will charge -- a
    multicolour team's surcharge included -- and, in a standard game,
    the spec its construction chooses: `specs`, the choices for a tech
    II's spec or a tech lab's own (empty where nothing is chosen), and
    `lab_specs`, the choices for a lab already standing without one,
    chosen together with the tech II's (the tech_lab ruling).
    """

    building: str
    cost: int
    workers_needed: int = 0
    why_not: str = ""
    specs: tuple[str, ...] = ()
    lab_specs: tuple[str, ...] = ()

    @property
    def allowed(self) -> bool:
        return not self.why_not

    def to_dict(self) -> dict:
        found = {
            "building": self.building, "cost": self.cost,
            "workers_needed": self.workers_needed, "why_not": self.why_not,
        }
        if self.specs or self.lab_specs:
            found["specs"] = list(self.specs)
            found["lab_specs"] = list(self.lab_specs)
        return found


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
class AbilityOption:
    """
    An ability action a card in play offers its controller (UMR p. 7):
    `effect` names it in `codex.effects.EFFECTS` -- River's sideline,
    Maestro's granted damage, Harmony's "stop the music" -- `source` is
    the card or hero offering it, and `why_not` why it may not be used
    now ("" where it may).
    """

    effect: str
    source: str
    why_not: str = ""

    @property
    def allowed(self) -> bool:
        return not self.why_not

    def to_dict(self) -> dict:
        return {"effect": self.effect, "source": self.source, "why_not": self.why_not}


@dataclass(frozen=True)
class TargetRow:
    """
    One thing an effect's part may choose: `key` is how an answer names
    it (`"<seat>:<ref>"`, since a target may be on either side), what
    choosing it costs in resist (UMR p. 18, paid when it is chosen), and
    whether it is offered because the flagbearer rule forces it.
    """

    key: str
    seat: int
    ref: str
    resist: int = 0
    flagbearer: bool = False

    def to_dict(self) -> dict:
        return {
            "key": self.key, "seat": self.seat, "ref": self.ref,
            "resist": self.resist, "flagbearer": self.flagbearer,
        }


@dataclass(frozen=True)
class LegalActions:
    hire: HireOption
    #: One per hero, in the team's order.
    heroes: tuple[HeroOption, ...]
    playable: tuple[PlayableCard, ...]
    buildings: tuple[BuildOption, ...]
    attackers: tuple[str, ...]
    end_main: bool = True
    detect: DetectOption = DetectOption()
    abilities: tuple[AbilityOption, ...] = ()


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

    def new_match(self, teams: Sequence, first: Optional[int] = None,
                  decks: Optional[Sequence[str]] = None) -> MatchState:
        """
        The opening position (UMR p. 3): each seat's heroes in the
        command zone -- `teams`, a list of specs per seat, or one spec as
        a string for the basic game -- the ten starters of its deck's
        colour (`decks`, the neutral deck where not given) shuffled as
        its deck and five dealt, the codex of every one of its specs,
        twenty-four a spec, a base at 20, and four workers for whoever
        goes first and five for the other -- who goes first drawn at
        random unless given.
        """
        if first is None:
            first = self.rng.choice((1, 2))
        players = []
        for seat, specs in enumerate(teams, start=1):
            if isinstance(specs, str):
                specs = (specs,)
            specs = tuple(spec.lower() for spec in specs)
            color = (decks[seat - 1] if decks is not None else "neutral").lower()
            deck = self.shuffle(self.catalog.starting_deck(color))
            hand = [deck.pop() for _ in range(HAND_SIZE)]
            codex = Counter()
            for spec in specs:
                codex.update(self.catalog.codex_for(spec))
            players.append(PlayerState(
                seat=seat,
                specs=specs,
                heroes=[HeroState(slug=self.catalog.hero_for(spec).slug) for spec in specs],
                deck_color=color,
                base_hp=BASE_HP,
                workers=STARTING_WORKERS[seat == first],
                hand=hand,
                deck=deck,
                codex=dict(codex),
            ))
        return MatchState(players=players, first=first, active=first)

    # -- Numbers ---------------------------------------------------------

    def hero_card(self, hero: HeroState) -> Hero:
        return self.catalog.heroes[hero.slug]

    def hero_band(self, hero: HeroState) -> HeroBand:
        return self.hero_card(hero).band(hero.level)

    @staticmethod
    def _changes(body) -> tuple[int, int]:
        """What a body's runes -- a +1/+1 and a -1/-1 cancel (UMR p. 13)
        -- and this turn's modifiers add to its ATK and HP."""
        runes = body.plus_runes - body.minus_runes
        atk = hp = runes
        for modifier in body.modifiers:
            if modifier.get("kind") == "atk":
                atk += modifier.get("amount", 0)
            elif modifier.get("kind") == "hp":
                hp += modifier.get("amount", 0)
        return atk, hp

    def _hero_raw(self, hero: HeroState) -> tuple[int, int]:
        band = self.hero_band(hero)
        atk, hp = self._changes(hero)
        return band.atk + atk, band.hp + hp

    def hero_stats(self, hero: HeroState) -> tuple[int, int]:
        """The hero's ATK and HP: its level's band, then its runes and
        this turn's modifiers. ATK is never below 0 (Intimidate's
        ruling)."""
        atk, hp = self._hero_raw(hero)
        return max(atk, 0), hp

    def _unit_raw(self, card: CardInstance, match: Optional[MatchState]) -> tuple[int, int]:
        """
        A unit's ATK and HP before the floor: printed, its runes and this
        turn's modifiers, and -- given the match -- what other cards in
        play give it: each Grounded Guide its controller has (+1 ATK, or
        +2/+1 for a Virtuoso, stacking -- Sirlin, 2016-03-02), Two Step's
        +2/+2 while its controller holds both partners, and Star-Crossed
        Starlet's +1 ATK per damage on her.
        """
        printed = self.catalog.cards[card.slug]
        changed_atk, changed_hp = self._changes(card)
        atk = (printed.atk or 0) + changed_atk
        hp = (printed.hp or 0) + changed_hp
        if card.slug in effects.ATK_PER_DAMAGE:
            atk += card.damage
        if match is not None and printed.is_unit:
            mine = match.player(card.controller).play
            for other in mine:
                if other.id == card.id or other.slug not in effects.GUIDES:
                    continue
                if self.is_virtuoso(card.slug):
                    atk += 2
                    hp += 1
                else:
                    atk += 1
            if self.partnered(match, card, both_held=True):
                atk += effects.PARTNER_BONUS[0]
                hp += effects.PARTNER_BONUS[1]
        return atk, hp

    def unit_stats(self, card: CardInstance, match: Optional[MatchState] = None) -> tuple[int, int]:
        """
        A unit's ATK and HP as it stands (`_unit_raw`) -- pass the match,
        or what other cards give it is left out. ATK is never below 0
        ("0 is the lowest ATK a unit can have").
        """
        atk, hp = self._unit_raw(card, match)
        return max(atk, 0), hp

    def body_stats(self, match: MatchState, body) -> tuple[int, int]:
        """A unit's or a hero's ATK and HP."""
        if isinstance(body, CardInstance):
            return self.unit_stats(body, match)
        return self.hero_stats(body)

    def attack_value(self, match: MatchState, seat: int, ref: str) -> int:
        """
        What `ref` on `seat`'s side deals in combat: its ATK, the elite's
        +1 while it patrols there (UMR p. 10), and frenzy X on its
        controller's own turn (UMR p. 16), floored at 0 once everything
        is added. A building deals nothing.
        """
        player = match.player(seat)
        if is_hero_ref(ref):
            body = player.hero_by_ref(ref)
            atk = self._hero_raw(body)[0]
        elif ref.startswith("unit:"):
            body = player.instance(int(ref.split(":", 1)[1]))
            atk = self._unit_raw(body, match)[0]
        else:
            return 0
        if body.patrol_slot == "elite":
            atk += ELITE_ATK
        if seat == match.active:
            atk += self.keyword_x(body, "Frenzy", match)
        return max(atk, 0)

    def is_virtuoso(self, slug: str) -> bool:
        card = self.catalog.cards.get(slug)
        return card is not None and effects.VIRTUOSO in (card.subtype or "")

    def is_flagbearer(self, slug: str) -> bool:
        card = self.catalog.cards.get(slug)
        return card is not None and effects.FLAGBEARER in (card.subtype or "")

    def seat_of(self, match: MatchState, body) -> Optional[int]:
        """Who controls a unit or a hero in play."""
        if isinstance(body, CardInstance):
            return body.controller
        for player in match.players:
            if any(hero is body for hero in player.heroes):
                return player.seat
        return None

    def partnered(self, match: MatchState, card: CardInstance, *, both_held: bool = False):
        """
        The Two Step `card` is a dance partner of, or `None`; with
        `both_held`, only while its controller holds both partners --
        when the +2/+2 is given.
        """
        for spell in match.instances():
            if spell.slug != effects.TWO_STEP or card.id not in spell.attached:
                continue
            if not both_held:
                return spell
            mine = match.player(spell.controller)
            held = [mine.instance(i) for i in spell.attached]
            if len(spell.attached) == 2 and all(found is not None for found in held):
                return spell
        return None

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
        """
        What a card costs this player now: its printed cost, then the
        reductions they hold -- a Maestro makes their Virtuosos cost 0,
        River at 5 their tech 0 units 1 less -- to 0 at the least ("You
        can only reduce the gold cost of something to 0", Sirlin,
        2016-03-02).
        """
        card = self.catalog.cards[slug]
        cost = card.cost or 0
        if card.is_spell:
            return cost + self.wrong_color_surcharge(player, slug)
        if not card.is_unit:
            return cost
        if self.is_virtuoso(slug) and any(
            other.slug in effects.MAESTROS for other in player.play
        ):
            return 0
        if not (card.tech_level or 0):
            for hero in player.heroes_in_play:
                for (hero_slug, level), amount in effects.TECH_0_DISCOUNT.items():
                    if hero.slug == hero_slug and hero.level >= level:
                        cost -= amount
        return max(cost, 0)

    # -- Heroes and colours -----------------------------------------------

    def hero_color(self, hero: HeroState) -> str:
        """A hero's colour, lowered: "neutral", "red"."""
        return (self.hero_card(hero).color or "neutral").lower()

    def team_colors(self, player: PlayerState) -> tuple[str, ...]:
        """
        The colours a team counts for the multicolour penalties (UMR
        pp. 4, 8): its heroes' colours less neutral -- "the neutral
        heroes, Troq and River, don't count as an additional color" --
        in the team's order.
        """
        found = []
        for hero in player.heroes:
            color = self.hero_color(hero)
            if color != "neutral" and color not in found:
                found.append(color)
        return tuple(found)

    def is_starting_spell(self, slug: str) -> bool:
        card = self.catalog.cards[slug]
        return card.is_spell and not card.spec

    def wrong_color_surcharge(self, player: PlayerState, slug: str) -> int:
        """
        What a starting spell costs on top where no hero of its colour
        is in play to cast it: "A starting spell costs +1 gold when
        played by a hero of the wrong color" (UMR p. 4), never for a
        neutral one ("neutral starting spells never cost extra gold to
        play"), and never for a spec spell, which only its own hero casts.
        The caster is the engine's (`caster`): a hero of the spell's
        colour wherever there is one, so the surcharge is paid only
        where there is none.
        """
        card = self.catalog.cards[slug]
        if not self.is_starting_spell(slug):
            return 0
        color = (card.color or "neutral").lower()
        if color == "neutral":
            return 0
        heroes = player.heroes_in_play
        if not heroes or any(self.hero_color(hero) == color for hero in heroes):
            return 0
        return WRONG_COLOR_SURCHARGE

    def caster(self, player: PlayerState, slug: str) -> Optional[HeroState]:
        """
        The hero that casts a spell (UMR p. 7: "the hero actually casts
        the spell"): a spec spell's own hero; a starting spell's, a hero
        of its colour where there is one in play, otherwise the first in
        play -- **nobody is asked**, since nothing in the sets this bot
        plays turns on which hero cast a starting spell, and the cheapest
        caster is the one a player would choose. `None` with no hero in
        play.
        """
        card = self.catalog.cards[slug]
        heroes = player.heroes_in_play
        if card.spec:
            key = card.spec.lower()
            return next((hero for hero in heroes
                         if (self.hero_card(hero).spec or "").lower() == key), None)
        color = (card.color or "neutral").lower()
        return next((hero for hero in heroes if self.hero_color(hero) == color),
                    heroes[0] if heroes else None)

    def hero_limit(self, player: PlayerState) -> int:
        """
        How many heroes this player may have in play when summoning one
        (UMR p. 6, p. 9) -- **the heroes_hall ruling is the one reading**:
        "If you have an active Tech 3 building, or you have an active
        Tech 2 building and an active Heroes' Hall, you can play all 3
        heroes. If you have an active Tech 2 building or an active
        Heroes' Hall, you can play 2 heroes. Otherwise, you can play only
        1 hero." Active is built, finished and standing.
        """
        hall = (
            player.add_on is not None and player.add_on.slug == HEROES_HALL
            and player.add_on.active
        )
        tech2 = self.tech_building_active(player, 2)
        if self.tech_building_active(player, 3) or (tech2 and hall):
            return 3
        if tech2 or hall:
            return 2
        return 1

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
        """What constructing `building` costs now: its printed cost, 0 to
        rebuild a destroyed tech building (UMR p. 8), and a multicolour
        team's +1 on the first tech building or add-on it constructs, a
        rebuild included (`multicolor_surcharge`)."""
        if building in TECH_BUILDINGS:
            existing = player.buildings[building]
            if existing is not None and existing.destroyed:
                cost = 0  # rebuilt for nothing (UMR p. 8)
            else:
                cost = self.catalog.building(TECH_BUILDING_SLUGS[building]).cost or 0
        else:
            cost = self.catalog.building(building).cost or 0
        return cost + self.multicolor_surcharge(player)

    def multicolor_surcharge(self, player: PlayerState) -> int:
        """
        "If your team has multiple hero colors, then your first tech
        building or add-on costs +1 gold" (UMR p. 8; p. 4, p. 9) --
        neutral heroes not counting as a colour (`team_colors`) -- until
        the player has constructed one (`PlayerState.constructed_once`).
        """
        if player.constructed_once or len(self.team_colors(player)) < 2:
            return 0
        return MULTICOLOR_SURCHARGE

    def is_standard(self, player: PlayerState) -> bool:
        """A standard game's side has three heroes; the basic game's one
        (UMR p. 3)."""
        return len(player.specs) > 1

    def add_ons(self, player: PlayerState) -> tuple[str, ...]:
        """The add-ons this player may construct: the tower and the
        surplus in the basic game, all four in the standard one (UMR
        p. 3)."""
        return ADD_ONS if self.is_standard(player) else BASIC_ADD_ONS

    def tech_lab(self, player: PlayerState) -> Optional[AddOnState]:
        add_on = player.add_on
        return add_on if add_on is not None and add_on.slug == TECH_LAB else None

    def chosen_specs(self, player: PlayerState) -> tuple[str, ...]:
        """
        The specs whose tech II and III cards this player may play (UMR
        pp. 8-9): the basic game's one, chosen by the rule; in a standard
        game the tech II's, once chosen, and a finished tech lab's --
        "You can't immediately play cards of the new tech when you
        construct this".
        """
        if not self.is_standard(player):
            return tuple(player.specs)
        found = [player.tech2_spec] if player.tech2_spec else []
        lab = self.tech_lab(player)
        if lab is not None and lab.active and lab.spec and lab.spec not in found:
            found.append(lab.spec)
        return tuple(found)

    def spec_choices(self, player: PlayerState, building: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """
        What constructing `building` chooses in a standard game (UMR
        pp. 8-9): for a tech II whose spec is not yet chosen, one of the
        heroes' specs -- and, where a tech lab stands without one, the
        lab's too, a different one (the tech_lab ruling); for a tech lab
        where the tech II's spec is chosen, one of the other specs.
        Nothing is chosen in a basic game, or for anything else.
        """
        if not self.is_standard(player):
            return (), ()
        specs = tuple(player.specs)
        if building == "tech2" and player.tech2_spec is None:
            lab = self.tech_lab(player)
            waiting = specs if lab is not None and lab.spec is None else ()
            return specs, waiting
        if building == TECH_LAB and player.tech2_spec is not None:
            return tuple(spec for spec in specs if spec != player.tech2_spec), ()
        return (), ()

    def building_hp(self, building: str) -> int:
        slug = TECH_BUILDING_SLUGS.get(building, building)
        return self.catalog.building(slug).hp or 0

    def build_option(self, player: PlayerState, building: str) -> BuildOption:
        cost = self.building_cost(player, building)
        specs, lab_specs = self.spec_choices(player, building)
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
            return BuildOption(building, cost, workers, why, specs, lab_specs)
        # A new add-on replaces the one in the slot, which deals its 2 to
        # the base (UMR p. 9; the author, 2026-10-08) -- the same one again
        # is no replacement.
        why = ""
        if building not in self.add_ons(player):
            why = "the basic game builds the tower and the surplus alone"
        elif player.add_on is not None and player.add_on.slug == building:
            why = "it is already built"
        elif player.gold < cost:
            why = "not enough gold"
        return BuildOption(building, cost, 0, why, specs, lab_specs)

    # -- The main phase -----------------------------------------------------

    def hire_option(self, player: PlayerState) -> HireOption:
        if player.hired_this_turn:
            return HireOption(False, why_not="a worker has been hired this turn")
        if player.gold < HIRE_COST:
            return HireOption(False, why_not="not enough gold")
        if not player.hand:
            return HireOption(False, why_not="there is no card in hand to hire with")
        return HireOption(True)

    def hero_options(self, player: PlayerState) -> tuple[HeroOption, ...]:
        """One `HeroOption` per hero, in the team's order."""
        return tuple(self.hero_option(player, hero) for hero in player.heroes)

    def hero_option(self, player: PlayerState, hero: Optional[HeroState] = None) -> HeroOption:
        """
        What the player may do with `hero` (their first by default):
        summon it from the command zone for its cost -- not while it has
        summoning runes, and not past the hero limit (UMR p. 6), a dead
        hero in the command zone not counting against it -- or level it
        up in play, a gold a level, to its maximum.
        """
        hero = player.heroes[0] if hero is None else hero
        card = self.hero_card(hero)
        if not hero.in_play:
            if hero.summoning_runes:
                return HeroOption(
                    hero.slug, SUMMON, card.cost,
                    why_not=f"it has {hero.summoning_runes} summoning rune"
                    + ("s" if hero.summoning_runes != 1 else ""),
                )
            limit = self.hero_limit(player)
            if len(player.heroes_in_play) >= limit:
                return HeroOption(
                    hero.slug, SUMMON, card.cost,
                    why_not=f"your hero limit is {limit}",
                )
            if player.gold < card.cost:
                return HeroOption(hero.slug, SUMMON, card.cost, why_not="not enough gold")
            return HeroOption(hero.slug, SUMMON, card.cost)
        room = card.max_level - hero.level
        if not room:
            return HeroOption(hero.slug, LEVEL, LEVEL_COST, why_not="it is at its maximum level")
        levels = min(room, player.gold // LEVEL_COST)
        if not levels:
            return HeroOption(hero.slug, LEVEL, LEVEL_COST, why_not="not enough gold")
        return HeroOption(hero.slug, LEVEL, LEVEL_COST, levels)

    def why_not_playable(self, player: PlayerState, slug: str,
                         match: Optional[MatchState] = None) -> str:
        """Why `player` may not play `slug` from their hand now, or "".
        Given the match, a spell with a {target} and nothing it could
        target is not playable -- "do as much as you can" plays a spell
        any of whose parts can resolve (Final Smash's ruling)."""
        card = self.catalog.cards[slug]
        cost = self.effective_cost(player, slug)
        if card.is_unit or card.is_permanent:
            if not self.tech_building_active(player, card.tech_level or 0):
                return f"it needs a finished {_building_name(TECH_LEVEL_BUILDING[card.tech_level])} building"
            why = self._why_not_spec(player, card)
            if why:
                return why
        elif card.is_spell:
            if not player.heroes_in_play:
                return "a spell needs a hero in play"
            if card.spec:
                hero = self.caster(player, slug)
                if hero is None:
                    return f"it needs the {card.spec} hero"
                if "Ultimate" in card.type and not hero.max_level_since_turn_began:
                    return "an ultimate needs its hero at maximum level since the turn began"
        else:
            return "it is not a card that is played"
        if player.gold < cost:
            return "not enough gold"
        if match is not None and card.is_spell and not self.spell_can_resolve(
            match, player.seat, slug, player.gold - cost,
        ):
            return "it has nothing it could target"
        return ""

    def _why_not_spec(self, player: PlayerState, card) -> str:
        """A tech II or III card is played only of a spec the player has
        chosen -- their tech II's, or their tech lab's (UMR pp. 8-9)."""
        if (card.tech_level or 0) < 2 or not card.spec:
            return ""
        key = card.spec.lower()
        if key in self.chosen_specs(player):
            return ""
        if not self.is_standard(player):
            return f"it is not a card of your {player.specs[0].title()} codex"
        if player.tech2_spec is None:
            return f"it needs {card.spec} chosen as your Tech II spec"
        return f"your Tech II spec is {player.tech2_spec.title()}, and no tech lab has {card.spec}"

    def spell_can_resolve(self, match: MatchState, seat: int, slug: str, gold: int) -> bool:
        """Whether a spell has a part that can resolve: one choosing
        nothing, or one with something it could choose, paying any
        resist out of the gold left once the spell is paid for."""
        effect = effects.EFFECTS.get(slug)
        if effect is None or not effect.parts:
            return True
        if effect.whole:
            # Every part, each a different target of the one filter:
            # Two Step's two partners.
            first = effect.parts[0]
            return len(self.target_rows(match, seat, first, gold=gold)) >= len(effect.parts)
        for part in effect.parts:
            if part.choose is None:
                return True
            if self.target_rows(match, seat, part, gold=gold):
                return True
        return False

    def playable(self, player: PlayerState, match: Optional[MatchState] = None) -> tuple[PlayableCard, ...]:
        """Every card in the hand once, in the hand's order, with its cost
        and whether it may be played."""
        seen = []
        rows = []
        for slug in player.hand:
            if slug in seen:
                continue
            seen.append(slug)
            rows.append(PlayableCard(slug, self.effective_cost(player, slug),
                                     self.why_not_playable(player, slug, match)))
        return tuple(rows)

    def may_attack_with(self, body, match: Optional[MatchState] = None) -> bool:
        """
        Whether a unit or hero in play may attack: ready, and either not
        fatigued from arriving this turn or hasted (UMR p. 10, 16), and
        -- for readiness, which does not exhaust -- not having attacked
        already this turn (UMR p. 17).
        """
        if body.exhausted:
            return False
        if body.arrived_this_turn and not self.has_keyword(body, "Haste", match):
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
            if self.catalog.cards[card.slug].is_unit and self.may_attack_with(card, match)
        ]
        for hero in player.heroes_in_play:
            if self.may_attack_with(hero, match):
                found.append(hero_ref(hero.slug))
        return tuple(found)

    def legal_actions(self, match: MatchState) -> LegalActions:
        player = match.active_player
        return LegalActions(
            hire=self.hire_option(player),
            heroes=self.hero_options(player),
            playable=self.playable(player, match),
            buildings=tuple(
                self.build_option(player, building)
                for building in (*TECH_BUILDINGS, *self.add_ons(player))
            ),
            attackers=self.attackers(match),
            detect=self.detect_option(match),
            abilities=self.abilities(match),
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
        if is_hero_ref(ref):
            hero = player.hero_by_ref(ref)
            return hero if hero is not None and hero.in_play else None
        instance_id = unit_ref(ref)
        if instance_id is None:
            return None
        return player.instance(instance_id)

    def body_keywords(self, body, match: Optional[MatchState] = None) -> tuple:
        """
        Every keyword a thing in play has -- **the one reading**: its
        printed ones and its patrol slot's (`codex.keywords.body_keywords`),
        a keyword it was given for the turn (Sneaky Pig's stealth, a
        modifier), and -- given the match -- what another card its
        controller has in play grants it, exactly while that card is
        there under their control: Blademaster's swift strike to every
        unit and hero, Nimble Fencer's haste to every Virtuoso, herself
        included (Sirlin, 2016-03-04).
        """
        if body is None:
            return ()
        found = list(keywords.body_keywords(body, match))
        for modifier in getattr(body, "modifiers", ()):
            if modifier.get("kind") == "keyword":
                found.append((modifier["keyword"], modifier.get("amount")))
        if match is not None:
            seat = self.seat_of(match, body)
            if seat is not None:
                mine = match.player(seat).play
                if any(card.slug in effects.GRANTS_SWIFT_STRIKE for card in mine):
                    found.append(("Swift strike", None))
                if (
                    isinstance(body, CardInstance) and self.is_virtuoso(body.slug)
                    and any(card.slug in effects.GRANTS_VIRTUOSO_HASTE for card in mine)
                ):
                    found.append(("Haste", None))
        return tuple(found)

    def has_keyword(self, body, keyword: str, match: Optional[MatchState] = None) -> bool:
        """Whether a thing in play has `keyword` (`body_keywords`)."""
        return any(name == keyword for name, _ in self.body_keywords(body, match))

    def keyword_x(self, body, keyword: str, match: Optional[MatchState] = None) -> int:
        """`keyword`'s X on this thing: summed where it stacks and the
        highest otherwise (`codex.keywords.STACKING`), 1 for a keyword
        written without a number, 0 where it is missing."""
        values = [
            1 if x is None else x
            for name, x in self.body_keywords(body, match) if name == keyword
        ]
        if not values:
            return 0
        return sum(values) if keyword in keywords.STACKING else max(values)

    def has(self, match: MatchState, seat: int, ref: str, keyword: str) -> bool:
        """Whether what `ref` names on `seat`'s side has `keyword`."""
        return self.has_keyword(self.body(match, seat, ref), keyword, match)

    def resist_cost(self, match: MatchState, seat: int, ref: str) -> int:
        """
        What an opponent pays to target what `ref` names on `seat`'s side
        (UMR p. 18): its resist, the lookout's 1 among it, and it stacks.
        It is paid when the target is chosen (`target_rows`).
        """
        return self.keyword_x(self.body(match, seat, ref), "Resist", match)

    def healing(self, player: PlayerState) -> int:
        """How much damage this player's upkeep heals off each of their
        units and heroes (UMR p. 17): every healing X they control,
        each healing once."""
        total = sum(self.keyword_x(card, "Healing") for card in player.play)
        for hero in player.heroes_in_play:
            total += self.keyword_x(hero, "Healing")
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
        if self.has_keyword(body, "Invisible", match):
            return "invisible"
        if self.has_keyword(body, "Stealth", match):
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
        found.extend(hero_ref(hero.slug) for hero in player.heroes_in_play)
        return tuple(found)

    def _standing(self, match: MatchState, seat: int) -> tuple[str, ...]:
        """Everything on `seat`'s side with HP: the units and hero in
        play, the tech buildings and add-on standing, and the base."""
        player = match.player(seat)
        found = list(self._things_in_play(match, seat))
        found.extend(card.ref for card in self._building_cards_of(match, seat))
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
            self.has_keyword(body, "Invisible", match)
            and body.patrol_slot is None
            and not self.detected_by(match, seat, target)
        ):
            return False
        if self.has_keyword(body, "Flying", match):
            hitting = self.body(match, seat, attacker)
            if not (self.has_keyword(hitting, "Flying", match)
                    or self.has_keyword(hitting, "Anti-air", match)):
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
        if self.has_keyword(body, "Unstoppable", match):
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
            self.has_keyword(body, "Flying", match) or self.has_keyword(body, "Anti-air", match)
        ):
            return 0
        return self.attack_value(match, other, defender)

    def patrol_slot_of(self, match: MatchState, seat: int, ref: str) -> Optional[str]:
        body = self.body(match, seat, ref)
        return None if body is None else body.patrol_slot

    def sparkshot_count(self, match: MatchState, attacker: str) -> int:
        """How many instances of sparkshot this attacker has: each deals 1,
        and they stack (Sirlin, 2016-09-16)."""
        return self.keyword_x(self.body(match, match.active, attacker), "Sparkshot", match)

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
        The combat damage beyond what destroys the patroller attacked --
        its remaining HP and its armor (the author, 2026-10-08: "if the
        overpowering attacker destroys a patroller with armor, the excess
        damage goes to anything else it could attack") -- counted whether
        it dies or not (Sirlin, 2016-03-14), and only against a
        patroller, since "overpower does nothing when you attack a
        non-patroller".
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
        hp = self.body_stats(match, body)[1]
        needed = max(0, hp - body.damage) + body.armor
        return max(0, self.attack_value(match, seat, attacker) - needed)

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
        return self.keyword_x(self.body(match, match.active, attacker), "Obliterate", match)

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

    # -- Targeting ----------------------------------------------------------------
    #
    # What an effect's part may choose (`codex.effects.Part.choose`), from
    # both sides of the table: a target is `(seat, ref)`, written
    # `"<seat>:<ref>"` in an answer. Docs: docs/design/codex.md,
    # "Targeting and the effects".

    def _buildings_of(self, match: MatchState, seat: int) -> list[str]:
        player = match.player(seat)
        found = [
            name for name in TECH_BUILDINGS
            if player.buildings[name] is not None and not player.buildings[name].destroyed
        ]
        if player.add_on is not None:
            found.append("add_on")
        found.append("base")
        return found

    @staticmethod
    def _under_construction(player: PlayerState, ref: str) -> bool:
        if ref == "add_on":
            return player.add_on is not None and player.add_on.under_construction
        if ref in TECH_BUILDINGS:
            building = player.buildings[ref]
            return building is not None and building.under_construction
        return False

    def _units_of(self, match: MatchState, seat: int) -> list[CardInstance]:
        return [card for card in match.player(seat).play if self.catalog.cards[card.slug].is_unit]

    def _building_cards_of(self, match: MatchState, seat: int) -> list[CardInstance]:
        """The building cards `seat` has in play -- things with HP besides
        the base, the tech buildings and the add-on (UMR p. 7)."""
        return [card for card in match.player(seat).play
                if self.catalog.cards[card.slug].is_building_card]

    def has_hp(self, card: CardInstance) -> bool:
        """Whether a card in play has HP, and so can be damaged and
        destroyed: a unit or a building card -- not an upgrade, not an
        ongoing spell."""
        printed = self.catalog.cards[card.slug]
        return printed.is_unit or printed.is_building_card

    def target_candidates(self, match: MatchState, seat: int, choose: str,
                          taken: Sequence[str] = ()) -> list[tuple[int, str]]:
        """
        Everything `choose` names for an effect `seat` controls, the
        opponent's side first: before resist, invisibility and the
        flagbearer narrow it (`target_rows`). `taken` is what this cast
        has already chosen, as keys, for a part that must choose another
        (Brick Thief's repair, Two Step's second partner).
        """
        other = 2 if seat == 1 else 1
        found: list[tuple[int, str]] = []
        for side in (other, seat):
            player = match.player(side)
            units = self._units_of(match, side)
            hero = [hero_ref(one.slug) for one in player.heroes_in_play]

            def tech(card: CardInstance) -> int:
                return self.catalog.cards[card.slug].tech_level or 0

            if choose == "patroller":
                found += [(side, ref) for ref in player.patrollers().values()]
            elif choose == "patroller_tech_0_1":
                found += [(side, card.ref) for card in units
                          if card.patrol_slot is not None and tech(card) <= 1]
            elif choose == "unit_or_hero":
                found += [(side, card.ref) for card in units] + [(side, ref) for ref in hero]
            elif choose == "friendly_unbloomed":
                if side == seat:
                    found += [(side, card.ref) for card in units if not card.plus_runes]
                    found += [(side, hero_ref(one.slug)) for one in player.heroes_in_play
                              if not one.plus_runes]
            elif choose == "building":
                # A building being constructed can't be dealt damage the
                # turn it was started (UMR p. 8, and p. 9 for add-ons); a
                # building card is a building as much as the base is.
                found += [(side, ref) for ref in self._buildings_of(match, side)
                          if not self._under_construction(player, ref)]
                found += [(side, card.ref) for card in self._building_cards_of(match, side)]
            elif choose == "other_building":
                found += [(side, ref) for ref in self._buildings_of(match, side)]
                found += [(side, card.ref) for card in self._building_cards_of(match, side)]
            elif choose == "unit":
                found += [(side, card.ref) for card in units]
            elif choose == "unit_tech_0_1":
                found += [(side, card.ref) for card in units if tech(card) <= 1]
            elif choose.startswith("unit_tech_"):
                level = int(choose.rsplit("_", 1)[1])
                found += [(side, card.ref) for card in units if tech(card) == level]
            elif choose == "own_unpartnered":
                if side == seat:
                    found += [(side, card.ref) for card in units
                              if self.partnered(match, card) is None]
            else:
                raise ValueError(f"not a target filter: {choose!r}")
        if choose in ("other_building", "own_unpartnered"):
            found = [row for row in found if target_key(*row) not in taken]
        return found

    def targetable(self, match: MatchState, seat: int, side: int, ref: str) -> bool:
        """
        Whether `seat` may {target} what `ref` names on `side`'s side: an
        opponent's invisible card only once their detector has seen it --
        patrolling or not, for "untargetable" is the whole of invisible to
        an opponent without one -- and your own invisible cards always
        ("You can target your own invisible things", the invisible
        ruling).
        """
        if side == seat:
            return True
        body = self.body(match, side, ref)
        if body is None:
            return True
        if self.has_keyword(body, "Invisible", match):
            return self.detected_by(match, seat, ref) and match.active == seat
        return True

    def target_rows(self, match: MatchState, seat: int, part, *, taken: Sequence[str] = (),
                    gold: Optional[int] = None, flagbearer_done: bool = False) -> tuple[TargetRow, ...]:
        """
        What `part` of an effect `seat` controls may choose, as the
        question offers it: what it names (`target_candidates`) that
        `seat` may target, each with the resist an opponent's card
        charges -- left out where `seat` cannot pay it, out of `gold`
        (their gold by default) -- and, **where an opposing flagbearer
        is among them and this cast has not targeted one yet, the
        flagbearers alone**: "it must target a flagbearer at least once"
        -- per part, as it resolves (Final Smash's ruling) -- and "if you
        cannot target a flagbearer, then you don't have to" (the
        flagbearer ruling), so one whose resist cannot be paid forces
        nothing. A part that is not targeted takes none of this.
        """
        gold = match.player(seat).gold if gold is None else gold
        rows: list[TargetRow] = []
        for side, ref in self.target_candidates(match, seat, part.choose, taken):
            if not part.targeted:
                rows.append(TargetRow(target_key(side, ref), side, ref))
                continue
            if not self.targetable(match, seat, side, ref):
                continue
            resist = self.resist_cost(match, side, ref) if side != seat else 0
            if resist > gold:
                continue
            body = self.body(match, side, ref)
            flag = (
                side != seat and isinstance(body, CardInstance)
                and self.is_flagbearer(body.slug)
            )
            rows.append(TargetRow(target_key(side, ref), side, ref, resist, flag))
        if part.targeted and not flagbearer_done and any(row.flagbearer for row in rows):
            return tuple(row for row in rows if row.flagbearer)
        return tuple(TargetRow(row.key, row.seat, row.ref, row.resist, False) for row in rows)

    # -- Abilities -------------------------------------------------------------------

    def may_exhaust(self, body, match: MatchState) -> str:
        """Why `body` may not exhaust to use an ability, or "": exhausted
        already, or arrived this turn without haste -- "you can't exhaust
        a unit as a cost to use its ability unless you controlled that
        unit at the start of your turn or if it has haste" (Maestro's
        ruling)."""
        if body.exhausted:
            return "it is exhausted"
        if body.arrived_this_turn and not self.has_keyword(body, "Haste", match):
            return "it arrived this turn"
        return ""

    def abilities(self, match: MatchState) -> tuple[AbilityOption, ...]:
        """
        The ability actions the active player's cards offer (UMR p. 7):
        Harmony's "stop the music" (a sacrifice, so arrival fatigue does
        not stop it), River's sideline from level 3, and the damage
        Maestro gives each of their Virtuosos -- each with why it may not
        be used now, a targeted one also when it has nothing to target.
        """
        seat = match.active
        player = match.active_player
        found: list[AbilityOption] = []
        for card in player.play:
            if card.slug == effects.HARMONY:
                found.append(AbilityOption("stop_the_music", card.ref))
        for hero in player.heroes_in_play:
            for when, effect in effects.rows(hero.slug, hero.level):
                if when == "ability":
                    found.append(AbilityOption(
                        effect, hero_ref(hero.slug),
                        self._ability_why_not(match, seat, hero, effect),
                    ))
        if any(card.slug in effects.MAESTROS for card in player.play):
            for card in player.play:
                if self.catalog.cards[card.slug].is_unit and self.is_virtuoso(card.slug):
                    found.append(AbilityOption(
                        "maestro", card.ref, self._ability_why_not(match, seat, card, "maestro"),
                    ))
        return tuple(found)

    def _ability_why_not(self, match: MatchState, seat: int, body, effect: str) -> str:
        why = self.may_exhaust(body, match)
        if why:
            return why
        part = effects.EFFECTS[effect].parts[0]
        if part.choose is not None and not self.target_rows(match, seat, part):
            return "there is nothing it could target"
        return ""

    # -- The upkeep -------------------------------------------------------------------

    def upkeep_effects(self, player: PlayerState) -> tuple[str, ...]:
        """
        The upkeep effects this player has (UMR p. 5), in the order they
        run unless the order is theirs to choose: the surplus's draw,
        healing (Helpful Turtle), and Star-Crossed Starlet's damage to
        herself.
        """
        found = []
        add_on = player.add_on
        if add_on is not None and add_on.active and add_on.slug in effects.UPKEEP_DRAW:
            found.append("draw")
        if self.healing(player):
            found.append("healing")
        if any(card.slug in effects.UPKEEP_SELF_DAMAGE for card in player.play):
            found.append("starlet")
        return tuple(found)

    def upkeep_order_matters(self, player: PlayerState) -> bool:
        """Whether the order is a question: healing and Starlet's damage
        both due, so healing her first or after changes what she is left
        with (Starlet's ruling: "you, as the active player, can choose the
        order of your upkeep effects")."""
        due = self.upkeep_effects(player)
        return "healing" in due and "starlet" in due

    def patrol_candidates(self, match: MatchState) -> tuple[str, ...]:
        """What the active player may lock into the patrol zone: ready
        units and a ready hero; arrival fatigue does not stop a patroller
        (UMR p. 10)."""
        player = match.active_player
        found = [
            card.ref for card in player.play
            if self.catalog.cards[card.slug].is_unit and not card.exhausted
        ]
        found.extend(
            hero_ref(hero.slug) for hero in player.heroes_in_play if not hero.exhausted
        )
        return tuple(found)

    def codex_counts(self, player: PlayerState) -> tuple[tuple[str, int], ...]:
        """The player's codex, as (slug, copies left), in the data's order."""
        order = list(dict.fromkeys(
            slug for spec in player.specs for slug in self.catalog.codex_for(spec)
        ))
        return tuple((slug, player.codex.get(slug, 0)) for slug in order)

    # -- What a player is shown of their own cards ------------------------

    def codex_views(self, player: PlayerState) -> tuple[str, ...]:
        """
        The views a player's codex is shown through -- everything, a
        tech level, or the spells (the author, 2026-10-08: "a lot of
        cards", so a menu rather than one picture) -- and, where the
        deck is more than one spec (the standard game's three, step 10),
        one view per spec, since a seventy-two card codex is three
        binders. The Codex button's menu and the tech picker's are both
        this list, so the two narrow the same way.
        """
        specs = player.specs
        if len(specs) < 2:
            return CODEX_VIEWS
        return CODEX_VIEWS + tuple(spec_view(spec) for spec in specs)

    def codex_view_rows(self, rows: Sequence[tuple[str, int]],
                        view: str) -> tuple[tuple[str, int], ...]:
        """
        `rows` -- (slug, copies), a codex as `codex_counts` lists it or
        as `TechOptions.codex` carries it -- narrowed to `view`, in the
        order given. **The one reading of which cards a view holds**: a
        tech level is every card printed with it, a building or an
        upgrade as much as a unit; the spells are the rest of a codex,
        so the four together are the whole; a spec's view is its own
        twelve. A view nothing offers raises.
        """
        if view == "everything":
            return tuple(rows)
        if view.startswith(SPEC_VIEW_PREFIX):
            key = view[len(SPEC_VIEW_PREFIX):]
            return tuple(
                row for row in rows
                if (self.catalog.cards[row[0]].spec or "").strip().lower() == key
            )
        if view not in CODEX_VIEWS:
            raise ValueError(f"not a codex view: {view!r}")

        def shown(slug: str) -> bool:
            card = self.catalog.cards[slug]
            if view == "spells":
                return card.is_spell
            return card.tech_level == int(view[-1])

        return tuple(row for row in rows if shown(row[0]))

    def codex_remaining(self, match: MatchState, seat: int,
                        view: str = "everything") -> tuple[tuple[str, int], ...]:
        """
        What `seat`'s codex still holds -- (slug, copies left), every
        card of it, in the data's order, a card with none left at 0 --
        narrowed to `view`, one of `codex_views` for that player.
        **Its owner's alone**: which cards are still in a codex is fog
        of war (UMR p. 5).
        """
        player = match.player(seat)
        if view not in self.codex_views(player):
            raise ValueError(f"not a codex view: {view!r}")
        return self.codex_view_rows(self.codex_counts(player), view)

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
            why = self.why_not_playable(player, slug, match) if mine else "it is not your main phase"
            rows.append(PlayableCard(slug, self.effective_cost(player, slug), why))
        return tuple(rows)

    def own_deck(self, match: MatchState, seat: int) -> "OwnDeck":
        """
        Every card `seat` owns, wherever it is now -- the hand, the draw
        pile, the discard pile, in play on either side, or a spell of
        theirs being cast -- which is the starting deck, plus what tech
        has added, less what was trashed: a card hired as a worker, a
        token gone (the author, 2026-10-09: "all the cards that are in
        your deck"). Counted per card, in the starting deck's order
        first, then each tech level's, the spells after their level's
        units, with each card's copies in the hand beside it, which **My
        deck** marks (the author, 2026-10-09). A tech choice not yet in
        the discard pile is not in it.
        **Its owner's alone**: the draw pile is told as a count, never
        an order.
        """
        from codex.flow.resolve import APPEL_TOP  # the flow imports the engine

        player = match.player(seat)
        cards = self.catalog.cards
        in_play = [
            card.slug for side in match.players for card in side.play
            if card.owner == seat and cards[card.slug].kind != "token"
        ]
        for frame in match.resolving:
            if frame.get("seat") != seat:
                continue
            if frame.get("kind") == APPEL_TOP:
                in_play.append(effects.APPEL_STOMP)
            elif frame.get("spell"):
                in_play.append(frame["spell"])
        counted = Counter([*player.hand, *player.deck, *player.discard, *in_play])
        order = {slug: index for index, slug in enumerate(cards)}

        def place(slug: str) -> tuple:
            card = cards[slug]
            return (card.starting_zone != "deck", card.tech_level or 0, card.is_spell,
                    order.get(slug, len(order)))

        held = Counter(player.hand)
        ordered = sorted(counted, key=place)
        return OwnDeck(
            cards=tuple((slug, counted[slug]) for slug in ordered),
            in_hand=tuple(held[slug] for slug in ordered),
            hand=len(player.hand), draw_pile=len(player.deck),
            discard=len(player.discard), in_play=len(in_play),
        )

    def name(self, slug: str) -> str:
        return self.catalog.name(slug)


def _building_name(building: str) -> str:
    return {"tech1": "Tech I", "tech2": "Tech II", "tech3": "Tech III"}.get(building, building)


def building_name(building: str) -> str:
    """A building slot in words: "Tech II", "tower", "base"."""
    if building in TECH_BUILDINGS:
        return _building_name(building)
    return {"add_on": "add-on", "base": "base"}.get(building, building)


def target_key(seat: int, ref: str) -> str:
    """How an answer names a target: `"2:unit:7"`, `"1:hero"`, `"2:base"`."""
    return f"{seat}:{ref}"


def parse_target(key: str) -> tuple[int, str]:
    """A target key back into `(seat, ref)`; `ValueError` if it is not one."""
    seat, _, ref = key.partition(":")
    if seat not in ("1", "2") or not ref:
        raise ValueError(f"not a target: {key!r}")
    return int(seat), ref


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
