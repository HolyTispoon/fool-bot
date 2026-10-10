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
    for every card they own; the same split in three, the copies in
    their hand (`held`), in their discard pile (`discarded`) and
    anywhere else -- the draw pile, in play (`elsewhere`) -- each in the
    deck's order and leaving out a card with none there; and how many
    are in each place."""

    cards: tuple[tuple[str, int], ...]
    held: tuple[tuple[str, int], ...]
    discarded: tuple[tuple[str, int], ...]
    elsewhere: tuple[tuple[str, int], ...]
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
    #: Boost X (UMR p. 16): the gold more it costs played boosted, `None`
    #: for a card with no boost, and why it may not be boosted now.
    boost: Optional[int] = None
    boost_why_not: str = ""

    @property
    def allowed(self) -> bool:
        return not self.why_not

    @property
    def boostable(self) -> bool:
        return self.boost is not None and self.allowed and not self.boost_why_not

    def to_dict(self) -> dict:
        found = {"slug": self.slug, "cost": self.cost, "why_not": self.why_not}
        if self.boost is not None:
            found["boost"] = self.boost
            found["boost_why_not"] = self.boost_why_not
        return found


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
    #: What using it costs, in words: "exhaust", "pay 1 gold and
    #: exhaust" (`RulesEngine.cost_words`).
    pays: str = "exhaust"

    @property
    def allowed(self) -> bool:
        return not self.why_not

    def to_dict(self) -> dict:
        return {"effect": self.effect, "source": self.source, "why_not": self.why_not,
                "pays": self.pays}


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


@dataclass
class Profile:
    """A unit or hero as it stands (`RulesEngine._profile`): ATK and HP
    before the floor, its keywords, and whether it has an ability --
    what Midori's "units with no abilities" reads."""

    atk: int
    hp: int
    keywords: list
    ability: bool

    def grant(self, keyword: str, x: Optional[int] = None) -> None:
        self.keywords.append((keyword, x))
        self.ability = True


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

    def flip_coin(self) -> str:
        """
        "heads" or "tails" (Rickety Mine) -- drawn from `rng`, or, while a
        journal is replayed, taken back from the next of `replaying`,
        where the step recorded it as `[COIN, side]` beside the shuffles
        (`StepResult.drawn`), so a replay lands the same side.
        """
        if self.replaying:
            recorded = self.replaying.pop(0)
            if not recorded or recorded[0] != effects.COIN:
                raise ValueError("a recorded outcome is not a coin")
            return recorded[1]
        return self.rng.choice(("heads", "tails"))

    def pick(self, cards: Sequence[str]) -> str:
        """
        One of `cards` at random (step 12) -- a card discarded at random, a
        unit Second Chances returns -- drawn from `rng`, or, while a
        journal is replayed, taken back as recorded (`[PICK, slug]`
        beside the shuffles), so a replay picks the same one. The caller
        records what it picked in `StepResult.drawn`.
        """
        if self.replaying:
            recorded = self.replaying.pop(0)
            if not recorded or recorded[0] != effects.PICK or recorded[1] not in cards:
                raise ValueError("a recorded outcome is not a pick of these")
            return recorded[1]
        return self.rng.choice(list(cards))

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

    # -- What a unit or hero is, grants and all (step 11) ---------------------

    def texted(self, body) -> bool:
        """Whether a card in play has its printed text -- not Polymorph:
        Squirrel's "1/1 green Squirrel with no abilities"."""
        printed = getattr(body, "printed", None)
        return not (printed and printed.get("polymorph") is not None)

    def text_slug(self, card) -> Optional[str]:
        """The slug whose text a card in play has -- its own, or `None`
        while Polymorph: Squirrel has taken its abilities."""
        return card.slug if self.texted(card) else None

    def _profile(self, body, match: Optional[MatchState]) -> "Profile":
        """
        **A unit or a hero as it stands**: its printed numbers -- or a
        printed value replaced (Chaos Mirror's ATK, Polymorph's 1/1
        Squirrel, a feather rune's 3/1) -- and its keywords, its runes and
        this turn's modifiers, and then, given the match, every grant of
        another card in play, **in the order each came to be** (the Card
        FAQ, Behind the Ferns and Master Midori): a grant applies to a
        unit from whichever came later, the unit or the grant's card or
        band, Midori's first where they came at once (Behind the Ferns'
        ruling: a unit arriving while both exist is a 4/4 with no
        abilities). A grant that reads the unit -- Behind the Ferns' "3 ATK
        or less", Midori's "no abilities" -- reads it as the grants before
        it left it, and Midori's +1/+1 goes again where an ability came
        after it.
        """
        if isinstance(body, HeroState):
            return self._hero_profile(body, match)
        return self._unit_profile(body, match)

    def _unit_profile(self, card: CardInstance, match: Optional[MatchState]) -> "Profile":
        printed = self.catalog.cards[card.slug]
        texted = self.texted(card)
        replaced = card.printed or {}
        atk, hp = ((printed.atk or 0), (printed.hp or 0)) if texted else effects.SQUIRREL_STATS
        found = list(keywords.keywords(card.slug)) if texted else []
        ability = texted and bool(printed.text)
        if match is not None and card.runes.get("feather") and any(
            other.slug == effects.FAIRIE_DRAGON and self.texted(other) for other in match.instances()
        ):
            # "Units with feather runes are 3/1 and have flying" -- the
            # base under the runes, while any Fairie Dragon is in play
            # (its rulings).
            atk, hp = effects.FEATHER_STATS
            found.append(("Flying", None))
            ability = True
        if "atk" in replaced:
            atk = replaced["atk"]
        found.extend(keywords.PATROL_GRANTS.get(card.patrol_slot or "", ()))
        for modifier in card.modifiers:
            if modifier.get("kind") == "keyword":
                found.append((modifier["keyword"], modifier.get("amount")))
                ability = True
        if match is not None and printed.is_unit:
            # Stampede's +3 ATK and Ferocity's keywords, on every unit
            # its caster controls while they last -- continuous, so one
            # arriving later has them too (the author, 2026-10-09).
            for lasting in match.player(card.controller).lasting:
                if lasting.get("kind") == "stampede":
                    atk += effects.STAMPEDE_BONUS
                elif lasting.get("kind") == "ferocity":
                    found.extend((keyword, None) for keyword in effects.FEROCITY_KEYWORDS)
                    ability = True
        changed_atk, changed_hp = self._changes(card)
        atk += changed_atk
        hp += changed_hp
        per_rune = effects.PER_TIME_RUNE.get(card.slug) if texted else None
        if per_rune:
            # Ebbflow Archon's -1/-1 and Tricycloid's +1/+1 for each time
            # rune on it.
            atk += per_rune * card.time_runes
            hp += per_rune * card.time_runes
        if match is not None and printed.is_unit:
            # Abomination: "All other units get -1/-1." -- both sides,
            # stacking (its ruling).
            for other in match.instances():
                change = effects.ALL_OTHER_UNITS.get(other.slug)
                if change is not None and other.id != card.id and self.texted(other):
                    atk += change[0]
                    hp += change[1]
        if texted and card.slug in effects.ATK_PER_DAMAGE:
            atk += card.damage
        profile = Profile(atk, hp, found, ability)
        if match is None or not printed.is_unit:
            return profile
        change = effects.WHILE_PATROLLING.get(self.text_slug(card) or "")
        if change is not None and card.patrol_slot is not None and card.controller != match.active:
            # Ironbark Treant: "-2 ATK / +2 armor while patrolling" -- on
            # the opponents' turns, while in the patrol zone (its rulings);
            # the armor is set as their turn begins.
            profile.atk += change[0]
        if texted:
            profile.keywords.extend(self._conditioned_keywords(match, card, card.controller))
        self._apply_grants(match, card, profile)
        self._lose_keywords(card, profile)
        ceiling = effects.ATK_CEILING.get(self.text_slug(card) or "")
        if ceiling is not None:
            # Pestering Haunt: "Can't have more than 1 ATK."
            profile.atk = min(profile.atk, ceiling)
        return profile

    @staticmethod
    def _lose_keywords(body, profile: "Profile") -> None:
        """A keyword a modifier takes away for a while (step 12):
        `{kind: "lose_keyword", keyword}` -- Gargoyle's "isn't
        indestructible", a flier's flying lost to Crypt Crawler."""
        lost = {m.get("keyword") for m in body.modifiers if m.get("kind") == "lose_keyword"}
        if lost:
            profile.keywords = [(name, x) for name, x in profile.keywords if name not in lost]

    def _grants(self, match: MatchState, card: CardInstance) -> list:
        """The grants on a unit, as `(time, rank, since, grant)`: what
        another card or a hero's band of its controller's gives it, and a
        Spirit of the Panda attached to it."""
        seat = card.controller
        found = []
        for other in match.player(seat).play:
            if not self.texted(other):
                continue
            grant = effects.UNIT_GRANTS.get(other.slug)
            if grant == "guide" and other.id == card.id:
                continue  # "Your *other* units"
            if grant is not None:
                found.append((other.sequence, grant, other))
        for spell in match.instances():
            if spell.slug in effects.ATTACHED_UNIT_GRANTS and card.id in spell.attached:
                found.append((spell.sequence, effects.ATTACHED_UNIT_GRANTS[spell.slug], spell))
        for spell in match.player(seat).play:
            if spell.slug == effects.TWO_STEP and self.partnered(match, card, both_held=True) is spell:
                found.append((spell.sequence, "two_step", spell))
        for hero in match.player(seat).heroes_in_play:
            for (slug, level), grant in effects.BAND_GRANTS.items():
                if hero.slug == slug and hero.level >= level:
                    found.append((hero.bands.get(str(level), 0), grant, hero))
        return [
            (max(since, card.sequence), 0 if grant == "no_abilities" else 1, since, grant, source)
            for since, grant, source in found
        ]

    def _apply_grants(self, match: MatchState, card: CardInstance, profile: "Profile") -> None:
        seat = card.controller
        midori = 0
        for _, _, _, grant, source in sorted(self._grants(match, card), key=lambda row: row[:3]):
            if grant == "guide":
                # Grounded Guide: +1 ATK, or +2/+1 for a Virtuoso,
                # stacking (Sirlin, 2016-03-02).
                if self.is_virtuoso(card.slug):
                    profile.atk += 2
                    profile.hp += 1
                else:
                    profile.atk += 1
            elif grant == "two_step":
                profile.atk += effects.PARTNER_BONUS[0]
                profile.hp += effects.PARTNER_BONUS[1]
            elif grant == "swift_strike":
                profile.grant("Swift strike")
            elif grant == "virtuoso_haste":
                if self.is_virtuoso(card.slug):
                    profile.grant("Haste")
            elif grant == "war_drums":
                # "+X ATK where X is the number of units you have" -- in
                # play, under your control (its ruling).
                profile.atk += sum(
                    1 for other in match.player(seat).play if self.catalog.cards[other.slug].is_unit
                )
            elif grant == "behind_the_ferns":
                # "Your units with 3 ATK or less have stealth" -- the ATK as
                # the grants before this one leave it, frenzy on your own
                # turn included, and no bonus against a building (its
                # rulings, the Card FAQ).
                frenzy = sum(1 if x is None else x for name, x in profile.keywords if name == "Frenzy")
                atk = profile.atk + (frenzy if seat == match.active else 0)
                if atk <= effects.FERNS_ATK:
                    profile.grant("Stealth")
            elif grant == "no_abilities":
                # Midori at 5: "Your units with no abilities get +1/+1."
                if not profile.ability:
                    profile.atk += 1
                    profile.hp += 1
                    midori += 1
            elif grant == "resist":
                profile.grant("Resist", 1)
            elif grant == "frenzy":
                profile.grant("Frenzy", 1)
            elif grant == "rune_overpower":
                if card.plus_runes > 0:
                    profile.grant("Overpower")
            elif grant == "growth":
                if source.runes.get("growth", 0) >= effects.GROWTH_THRESHOLD:
                    profile.atk += effects.GROWTH_BONUS
                    profile.hp += effects.GROWTH_BONUS
            elif grant == "dies":
                profile.ability = True
            elif grant == "squirrels":
                if effects.SQUIRREL in self.subtype_of(card):
                    profile.grant("Haste")
                    profile.grant("Invisible")
            elif grant == "battle_suits":
                # Battle Suits: "Your non-token Soldiers and Mystics get +1
                # ATK." -- the subtype read word by word.
                words = self.subtype_of(card).split()
                if self.catalog.cards[card.slug].kind != "token" and any(
                    word in effects.SUITED for word in words
                ):
                    profile.atk += 1
            elif grant == "black_invisible":
                # Lord of Shadows: "Your black units are invisible." -- the
                # colour read, himself included.
                if self.color_of(card) == effects.INVISIBLE_COLOR.get(source.slug, "black"):
                    profile.grant("Invisible")
            elif grant == "others_invisible":
                # Nebula: "Your other units are invisible."
                if source.id != card.id:
                    profile.grant("Invisible")
            elif grant == "skeletons":
                # Skeletal Lord: "Your Skeletons get +1/+1."
                if effects.SKELETON in self.subtype_of(card).split():
                    profile.atk += 1
                    profile.hp += 1
            elif grant == "skeleton_archery":
                # Skeletal Archery: "Your Skeletons have long-range and
                # anti-air."
                if effects.SKELETON in self.subtype_of(card).split():
                    profile.grant("Long-range")
                    profile.grant("Anti-air")
            elif grant == "soul_stone":
                # Soul Stone: "Attached unit gets +1/+1."
                profile.atk += 1
                profile.hp += 1
            elif grant == "panda":
                profile.atk += effects.PANDA_BONUS
                profile.hp += effects.PANDA_BONUS
                profile.ability = True
        if midori and profile.ability:
            # "If a unit gets an ability ... then it loses +2/+2 from
            # Midori" (his ruling).
            profile.atk -= midori
            profile.hp -= midori

    def _hero_profile(self, hero: HeroState, match: Optional[MatchState]) -> "Profile":
        band = self.hero_band(hero)
        atk, hp = band.atk, band.hp
        if hero.printed and "atk" in hero.printed:
            atk = hero.printed["atk"]
        changed_atk, changed_hp = self._changes(hero)
        found = list(keywords.hero_keywords(hero.slug, hero.level))
        found.extend(keywords.PATROL_GRANTS.get(hero.patrol_slot or "", ()))
        for modifier in hero.modifiers:
            if modifier.get("kind") == "keyword":
                found.append((modifier["keyword"], modifier.get("amount")))
        profile = Profile(atk + changed_atk, hp + changed_hp, found, True)
        if match is None:
            return profile
        seat = self.seat_of(match, hero)
        if seat is None:
            return profile
        mine = match.player(seat).play
        if any(card.slug in effects.GRANTS_SWIFT_STRIKE and self.texted(card) for card in mine):
            profile.grant("Swift strike")
        for card in mine:
            if not self.texted(card):
                continue
            grant = effects.HERO_GRANTS.get(card.slug)
            if grant == "rune_overpower" and hero.plus_runes > 0:
                profile.grant("Overpower")
            elif grant == "growth" and card.runes.get("growth", 0) >= effects.GROWTH_THRESHOLD:
                profile.atk += effects.GROWTH_BONUS
                profile.hp += effects.GROWTH_BONUS
            elif grant == "showdown" and card.attached_hero == f"{seat}:{hero_ref(hero.slug)}":
                # Final Showdown: "He gets +3/+3, readiness, resist 1, and
                # draws a card when he attacks."
                profile.atk += effects.SHOWDOWN_BONUS
                profile.hp += effects.SHOWDOWN_BONUS
                profile.grant("Readiness")
                profile.grant("Resist", 1)
        profile.keywords.extend(self._conditioned_keywords(match, hero, seat))
        self._lose_keywords(hero, profile)
        return profile

    def _hero_raw(self, hero: HeroState, match: Optional[MatchState] = None) -> tuple[int, int]:
        profile = self._hero_profile(hero, match)
        return profile.atk, profile.hp

    def hero_stats(self, hero: HeroState, match: Optional[MatchState] = None) -> tuple[int, int]:
        """The hero's ATK and HP: its level's band, then its runes and
        this turn's modifiers, and -- given the match -- what its
        controller's cards grant it. ATK is never below 0 (Intimidate's
        ruling)."""
        atk, hp = self._hero_raw(hero, match)
        return max(atk, 0), hp

    def _unit_raw(self, card: CardInstance, match: Optional[MatchState]) -> tuple[int, int]:
        """
        A unit's ATK and HP before the floor (`_profile`): printed, its
        runes and this turn's modifiers, and -- given the match -- what
        other cards in play give it, in the order they came: each Grounded
        Guide its controller has (+1 ATK, or +2/+1 for a Virtuoso,
        stacking -- Sirlin, 2016-03-02), Two Step's +2/+2 while its
        controller holds both partners, Star-Crossed Starlet's +1 ATK per
        damage on her, and red and green's (step 11).
        """
        profile = self._unit_profile(card, match)
        return profile.atk, profile.hp

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
        return self.hero_stats(body, match)

    def attack_value(self, match: MatchState, seat: int, ref: str,
                     against: Optional[str] = None) -> int:
        """
        What `ref` on `seat`'s side deals in combat: its ATK, the elite's
        +1 while it patrols there (UMR p. 10), and frenzy X on its
        controller's own turn (UMR p. 16), floored at 0 once everything
        is added -- and, where it attacks a building (`against`, a ref on
        the other side), "+X ATK when attacking buildings" (Steam Tank,
        Makeshift Rambaster). A building deals nothing.
        """
        player = match.player(seat)
        if is_hero_ref(ref):
            body = player.hero_by_ref(ref)
            atk = self._hero_raw(body, match)[0]
        elif ref.startswith("unit:"):
            body = player.instance(int(ref.split(":", 1)[1]))
            atk = self._unit_raw(body, match)[0]
        else:
            return 0
        if body.patrol_slot == "elite":
            atk += ELITE_ATK
        if seat == match.active:
            atk += self.keyword_x(body, "Frenzy", match)
        if against is not None and isinstance(body, CardInstance):
            bonus = effects.ATTACKING_BUILDINGS_ATK.get(self.text_slug(body) or "", 0)
            if bonus and self.is_building_ref(match, 2 if seat == 1 else 1, against):
                atk += bonus
        if isinstance(body, CardInstance):
            ceiling = effects.ATK_CEILING.get(self.text_slug(body) or "")
            if ceiling is not None:
                atk = min(atk, ceiling)
        return max(atk, 0)

    def is_building_ref(self, match: MatchState, seat: int, ref: str) -> bool:
        """Whether `ref` on `seat`'s side is a building: the base, a tech
        building, the add-on, or a building card in play."""
        if ref in TECH_BUILDINGS or ref in ("base", "add_on"):
            return True
        instance_id = unit_ref(ref)
        card = match.player(seat).instance(instance_id) if instance_id is not None else None
        return card is not None and self.catalog.cards[card.slug].is_building_card

    def is_virtuoso(self, slug: str) -> bool:
        card = self.catalog.cards.get(slug)
        return card is not None and effects.VIRTUOSO in (card.subtype or "")

    def is_flagbearer(self, slug: str) -> bool:
        card = self.catalog.cards.get(slug)
        return card is not None and effects.FLAGBEARER in (card.subtype or "")

    def is_flagbearer_body(self, match: MatchState, body) -> bool:
        """A flagbearer in play: printed so, or a unit a Vortoss Emblem is
        attached to (step 12)."""
        if not isinstance(body, CardInstance):
            return False
        if self.texted(body) and self.is_flagbearer(body.slug):
            return True
        return any(spell.slug == effects.VORTOSS_EMBLEM and body.id in spell.attached
                   for spell in match.instances())

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

    # -- What cannot die, and what cannot be sacrificed (step 12) -----------

    def indestructible(self, match: Optional[MatchState], body) -> bool:
        """Indestructible (UMR p. 17): exhausted instead of dying, never
        sacrificed -- while it has the keyword (Gargoyle loses it to its
        own ability, Polymorph takes it away)."""
        return isinstance(body, CardInstance) and self.has_keyword(body, "Indestructible", match)

    def may_sacrifice(self, match: MatchState, card: CardInstance) -> bool:
        """Whether `card` may be sacrificed at all: not indestructible, not
        Pestering Haunt ("Can't be sacrificed"), not a Gilded Glaxx whose
        controller has gold -- each ignored completely when choosing what to
        sacrifice (their rulings)."""
        if self.indestructible(match, card):
            return False
        if self.text_slug(card) in effects.CANT_BE_SACRIFICED:
            return False
        return not self.cant_leave_play(match, card)

    def may_be_destroyed(self, match: MatchState, card: CardInstance) -> bool:
        """Whether a "lowest" or "weakest" choice may take `card`:
        neither indestructible nor unable to leave play (the obliterate,
        Sacrifice the Weak and Death Rites rulings)."""
        return not self.indestructible(match, card) and not self.cant_leave_play(match, card)

    def cant_leave_play(self, match: MatchState, card) -> bool:
        """Gilded Glaxx while its controller has gold: it leaves play only
        by dying from combat damage -- not sacrificed, not destroyed or
        returned or trashed by an effect, and not killed by 0 HP (its
        rulings, the Card FAQ). Polymorph takes the text away."""
        return (
            isinstance(card, CardInstance) and self.text_slug(card) in effects.CANT_LEAVE_WITH_GOLD
            and match is not None and match.player(card.controller).gold > 0
        )

    def levels_frozen(self, match: Optional[MatchState], hero: HeroState) -> bool:
        """Chronofixer: "Opposing heroes can't level up." -- by any means:
        a kill's levels, Nether Drain, Blackhand Resurrector (its rulings)."""
        if match is None:
            return False
        seat = self.seat_of(match, hero)
        if seat is None:
            return False
        return any(card.slug in effects.NO_OPPOSING_LEVELS and self.texted(card)
                   for card in match.opponent(seat).play)

    def rune_damage(self, match: Optional[MatchState], body) -> bool:
        """Whether `body` deals its damage to units and heroes in the form
        of -1/-1 runes (UMR p. 13): Plague Spitter, Orpal Gloor from his
        first band, Poisonblade Rogue while it attacks."""
        if isinstance(body, HeroState):
            return any(body.slug == slug and body.level >= level
                       for slug, level in effects.RUNE_DAMAGE_BANDS)
        if not isinstance(body, CardInstance):
            return False
        if any(m.get("kind") == "rune_damage" for m in body.modifiers):
            return True
        return self.text_slug(body) in effects.RUNE_DAMAGE

    def weakest(self, match: MatchState, seat: int, *, sacrifice: bool) -> list[CardInstance]:
        """
        `seat`'s weakest units, tied (UMR p. 18): "the lowest tech unit with
        the least ATK" -- tech 0 below I below II below III, then the least
        ATK among those -- passing over what the effect cannot take: a unit
        that can't be sacrificed, or (to destroy) an indestructible one and
        one that can't leave play (the rulings). Whoever resolves the
        effect chooses between the tied.
        """
        units = [card for card in self._units_of(match, seat)
                 if (self.may_sacrifice(match, card) if sacrifice
                     else self.may_be_destroyed(match, card))]
        if not units:
            return []
        lowest = min(self.catalog.cards[card.slug].tech_level or 0 for card in units)
        units = [card for card in units if (self.catalog.cards[card.slug].tech_level or 0) == lowest]
        least = min(self.unit_stats(card, match)[0] for card in units)
        return [card for card in units if self.unit_stats(card, match)[0] == least]

    def lowest_tech(self, match: MatchState, seat: int) -> list[CardInstance]:
        """`seat`'s lowest tech units that may be destroyed -- Death Rites'
        and Blackhand Dozer's (the indestructible and obliterate rulings)."""
        units = [card for card in self._units_of(match, seat) if self.may_be_destroyed(match, card)]
        if not units:
            return []
        lowest = min(self.catalog.cards[card.slug].tech_level or 0 for card in units)
        return [card for card in units if (self.catalog.cards[card.slug].tech_level or 0) == lowest]

    def graveyards(self, player: PlayerState) -> list[CardInstance]:
        """The Graveyards a player controls, their text in play."""
        return [card for card in player.play if card.slug == effects.GRAVEYARD and self.texted(card)]

    def why_not_play_top(self, match: MatchState, player: PlayerState, slug: str) -> str:
        """Why Vir may not play the top card of his draw pile now, or "":
        "You still pay for it and must meet the reqs for it" -- the reqs a
        card played from the hand has."""
        return self.why_not_playable(player, slug, match)

    def no_high_tech(self, player: PlayerState, card) -> bool:
        """Twilight Baron: "You can't play tech II or III units." --
        playing alone; putting into play is untouched (its rulings)."""
        return (card.tech_level or 0) >= 2 and any(
            other.slug in effects.NO_HIGH_TECH_UNITS and self.texted(other) for other in player.play
        )

    def why_not_play_buried(self, player: PlayerState, slug: str) -> str:
        """Why a buried unit may not be played from the Graveyard now, or
        "": "You still pay for it and must meet the tech reqs for it" --
        the building of its level, and a tech II or III unit's spec one its
        controller has chosen (the Card FAQ)."""
        card = self.catalog.cards[slug]
        if self.no_high_tech(player, card):
            return "Twilight Baron stops you playing tech II or III units"
        if not self.tech_building_active(player, card.tech_level or 0):
            return f"it needs a finished {_building_name(TECH_LEVEL_BUILDING[card.tech_level])} building"
        why = self._why_not_spec(player, card)
        if why:
            return why
        if player.gold < self.effective_cost(player, slug):
            return "not enough gold"
        return ""

    # -- Time (step 12) --------------------------------------------------------

    def fading(self, body) -> int:
        """Fading X (UMR p. 17): the time runes it arrives with -- 0 for a
        card without it."""
        return self.keyword_x(body, "Fading")

    def forecast(self, slug: str) -> int:
        """Forecast X (UMR p. 17): the time runes it goes into the future
        with -- 0 for a card without it."""
        return next((x or 0 for name, x in keywords.keywords(slug) if name == "Forecast"), 0)

    def time_runes_of(self, match: MatchState, seat: int) -> int:
        """Every time rune on what `seat` controls: the cards in play --
        a Vortoss Emblem wherever it is attached -- their heroes, and the
        cards in their future (Temporal Research's rulings)."""
        player = match.player(seat)
        total = sum(card.time_runes for card in player.play)
        total += sum(hero.time_runes for hero in player.heroes_in_play)
        return total + sum(card.time_runes for card in player.future)

    @staticmethod
    def unbound(body) -> bool:
        """Gargoyle's ability: it can attack and patrol until its
        controller's next upkeep."""
        return any(m.get("kind") == "unbound" for m in getattr(body, "modifiers", ()))

    def shackled(self, match: Optional[MatchState], card: CardInstance) -> bool:
        """Terras Q: "can't attack or patrol while any of those tokens are
        in play" -- the Warlocks his own arrival summoned, by lineage
        (`made_by`), so another copy's or an earlier one's do nothing (his
        rulings)."""
        if match is None or self.text_slug(card) not in effects.SHACKLED:
            return False
        return any(other.made_by == card.id for other in match.instances())

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
        if player.promised:
            # Promise of Payment: "The next card you play this turn costs
            # {gold:0}." -- its printed cost owed at the next upkeep.
            return 0
        if card.is_spell:
            if self.free_spell(player, card):
                return 0
            return cost + self.wrong_color_surcharge(player, slug)
        if not card.is_unit:
            return cost
        if self.free_unit(player, card):
            return 0
        less = effects.LESS_PER_GREEN_UNIT.get(slug)
        if less:
            # Gigadon: 1 less for each green unit its player has -- to play
            # it from the hand alone (its rulings).
            cost -= less * sum(
                1 for other in player.play
                if self.catalog.cards[other.slug].is_unit and self.color_of(other) == "green"
            )
        if self.is_virtuoso(slug) and any(
            other.slug in effects.MAESTROS and self.texted(other) for other in player.play
        ):
            return 0
        if not (card.tech_level or 0):
            for hero in player.heroes_in_play:
                for (hero_slug, level), amount in effects.TECH_0_DISCOUNT.items():
                    if hero.slug == hero_slug and hero.level >= level:
                        cost -= amount
        return max(cost, 0)

    def free_unit(self, player: PlayerState, card) -> bool:
        """Pirategang Commander's "You may play tech I or II Blood units
        for free and without any tech buildings"."""
        for slug, (spec, levels) in effects.FREE_UNITS.items():
            if (
                any(other.slug == slug for other in player.play)
                and (card.spec or "").lower() == spec and (card.tech_level or 0) in levels
            ):
                return True
        return False

    def free_spell(self, player: PlayerState, card) -> bool:
        """Guargum's "You may play Growth spells for free and without
        having a Growth Hero"."""
        for slug, spec in effects.FREE_SPELLS.items():
            if any(other.slug == slug for other in player.play) and (card.spec or "").lower() == spec:
                return True
        return False

    def color_of(self, card: CardInstance) -> str:
        """A card in play's colour, lowered: "green" -- a Squirrel's while
        Polymorph: Squirrel has it."""
        slug = card.slug if self.texted(card) else effects.POLYMORPH_INTO
        return (self.catalog.cards[slug].color or "neutral").lower()

    def subtype_of(self, card: CardInstance) -> str:
        """A card in play's subtype: "Pirate", "Tiger" -- "Squirrel" while
        Polymorph: Squirrel has it."""
        slug = card.slug if self.texted(card) else effects.POLYMORPH_INTO
        return self.catalog.cards[slug].subtype or ""

    def printed_atk(self, body) -> int:
        """What Chaos Mirror swaps: "the ATK actually printed on the card"
        (its ruling) -- a unit's, or a hero's band's -- or what replaced it
        (a mirror's, Polymorph's 1)."""
        replaced = getattr(body, "printed", None) or {}
        if "atk" in replaced:
            return replaced["atk"]
        if isinstance(body, HeroState):
            return self.hero_band(body).atk
        if not self.texted(body):
            return effects.SQUIRREL_STATS[0]
        return self.catalog.cards[body.slug].atk or 0

    def builds_instantly(self, player: PlayerState) -> bool:
        """Whether this player's tech buildings build instantly this turn
        -- a Verdant Tree of theirs used this turn."""
        return any(
            modifier.get("kind") == "instant_build"
            for card in player.play for modifier in card.modifiers
        )

    def hire_cost(self, player: PlayerState) -> int:
        """A worker costs 1 (UMR p. 6), and nothing with Rich Earth --
        whose card still goes, once a turn (its rulings)."""
        if any(card.slug in effects.FREE_HIRE for card in player.play):
            return 0
        return HIRE_COST

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

    def draw_count(self, discarded: int, player: Optional[PlayerState] = None) -> int:
        """Two more than were discarded, to at most five (UMR p. 5) --
        each Shrine of Forbidden Knowledge its player has a card more and a
        hand of one more (its ruling and the Card FAQ)."""
        more = 0 if player is None else sum(
            1 for card in player.play if card.slug in effects.DRAW_MORE and self.texted(card)
        )
        return min(discarded + 2 + more, HAND_SIZE + more)

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
        cost = self.hire_cost(player)
        if player.hired_this_turn:
            return HireOption(False, cost, why_not="a worker has been hired this turn")
        if player.gold < cost:
            return HireOption(False, cost, why_not="not enough gold")
        if not player.hand:
            return HireOption(False, cost, why_not="there is no card in hand to hire with")
        return HireOption(True, cost)

    def hero_options(self, player: PlayerState,
                     match: Optional[MatchState] = None) -> tuple[HeroOption, ...]:
        """One `HeroOption` per hero, in the team's order."""
        return tuple(self.hero_option(player, hero, match) for hero in player.heroes)

    def hero_option(self, player: PlayerState, hero: Optional[HeroState] = None,
                    match: Optional[MatchState] = None) -> HeroOption:
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
        if any(m.get("kind") == "no_level" for m in hero.modifiers):
            return HeroOption(hero.slug, LEVEL, LEVEL_COST, why_not="it can't level up this turn")
        if self.levels_frozen(match, hero):
            return HeroOption(hero.slug, LEVEL, LEVEL_COST,
                              why_not="an opposing Chronofixer stops it levelling up")
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
        if card.is_unit and self.free_unit(player, card):
            pass  # no tech building, and so no spec, needed
        elif card.is_spell and self.free_spell(player, card):
            pass  # no hero needed, an ultimate's included
        elif card.is_unit or card.is_permanent:
            if card.is_unit and self.no_high_tech(player, card):
                return "Twilight Baron stops you playing tech II or III units"
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
                    # Rewind: "Your max level Past hero can cast this no
                    # matter when she arrived or maxed."
                    if not (slug in effects.ANY_TIME_ULTIMATES
                            and hero.level >= self.hero_card(hero).max_level):
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

    def spell_can_resolve(self, match: MatchState, seat: int, slug: str, gold: int,
                          frame: Optional[dict] = None) -> bool:
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
        if frame is None and slug in self.catalog.cards:
            frame = {"spell": slug}
        for part in effect.parts:
            if part.does == "mode" or part.follows:
                # A choice of modes, or a part acting on an earlier part's
                # pick, does nothing by itself (step 12).
                continue
            if part.choose is None:
                return True
            if self.target_rows(match, seat, part, gold=gold, frame=frame):
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
            rows.append(self._playable_row(player, slug, self.why_not_playable(player, slug, match)))
        return tuple(rows)

    def boost_cost(self, slug: str) -> Optional[int]:
        """A card's boost X -- "Boost {gold:4}" -- or `None`."""
        return next((x for name, x in keywords.keywords(slug) if name == "Boost"), None)

    def _playable_row(self, player: PlayerState, slug: str, why: str) -> PlayableCard:
        cost = self.effective_cost(player, slug)
        boost = self.boost_cost(slug)
        boost_why = ""
        if boost is not None and player.gold < cost + boost:
            boost_why = "not enough gold to boost"
        return PlayableCard(slug, cost, why, boost, boost_why)

    def may_attack_with(self, body, match: Optional[MatchState] = None) -> bool:
        """
        Whether a unit or hero in play may attack: ready, and either not
        fatigued from arriving this turn or hasted (UMR p. 10, 16), and
        -- for readiness, which does not exhaust -- not having attacked
        already this turn (UMR p. 17).
        """
        if body.exhausted:
            return False
        if isinstance(body, CardInstance) and self.text_slug(body) in effects.CANT_ATTACK \
                and not self.unbound(body):
            return False
        if isinstance(body, CardInstance) and self.shackled(match, body):
            return False
        if body.arrived_this_turn and not self.has_keyword(body, "Haste", match):
            return False
        # Readiness attacks once a turn; anything else readied after it
        # attacked -- Rampaging Elephant, a kidnapped unit -- may attack
        # again ("If you ready a card after it attacks ... it can attack
        # again", UMR p. 13).
        if body.attacked_this_turn and self.has_keyword(body, "Readiness", match):
            return False
        return True

    def attackers(self, match: MatchState) -> tuple[str, ...]:
        """The active player's units and hero that may attack
        (`may_attack_with`)."""
        player = match.active_player
        # Moment's Peace: "opposing units can't attack you" -- in a game
        # of two, they can't attack at all; heroes still may.
        peace = match.opponent(match.active).peace
        found = [
            card.ref for card in player.play
            if self.catalog.cards[card.slug].is_unit and self.may_attack_with(card, match)
            and not peace
        ]
        for hero in player.heroes_in_play:
            if self.may_attack_with(hero, match):
                found.append(hero_ref(hero.slug))
        return tuple(found)

    def legal_actions(self, match: MatchState) -> LegalActions:
        player = match.active_player
        return LegalActions(
            hire=self.hire_option(player),
            heroes=self.hero_options(player, match),
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
        Every keyword a thing in play has -- **the one reading**: a unit's
        or a hero's as it stands (`_profile`) -- its printed ones and its
        patrol slot's, a keyword it was given (Sneaky Pig's stealth for
        the turn, Sanatorium's haste for good), what the position gives it
        (Stalking Tiger's, Wandering Mimic's, Midori's flying) and, given
        the match, what another card its controller has in play grants
        it, exactly while that card is there under their control:
        Blademaster's swift strike, Nimble Fencer's haste to every
        Virtuoso, herself included (Sirlin, 2016-03-04), and red and
        green's. A card in play that is neither -- an ongoing spell, an
        upgrade, a building card -- has its printed ones.
        """
        if body is None:
            return ()
        if isinstance(body, HeroState) or (
            isinstance(body, CardInstance) and self.catalog.cards[body.slug].is_unit
        ):
            return tuple(self._profile(body, match).keywords)
        found = list(keywords.body_keywords(body, match))
        for modifier in getattr(body, "modifiers", ()):
            if modifier.get("kind") == "keyword":
                found.append((modifier["keyword"], modifier.get("amount")))
        return tuple(found)

    def _conditioned_keywords(self, match: MatchState, body, seat: Optional[int]) -> list:
        """
        The keywords a card has only while the position says so, read off
        it each time (step 11): Midori's flying on his own turn; Stalking
        Tiger's invisibility while its controller has a Feral hero in
        play, and its stealth while it attacks a unit; and Wandering
        Mimic's six, while anything in play that is not a Mimic has one
        (the Card FAQ: "Copies of this card can't gain abilities from
        each other").
        """
        found: list = []
        if isinstance(body, HeroState):
            for slug, level in effects.FLYING_ON_OWN_TURN:
                if body.slug == slug and body.level >= level and seat == match.active:
                    found.append(("Flying", None))
            return found
        if not isinstance(body, CardInstance):
            return found
        slug = body.slug
        spec = effects.INVISIBLE_WITH_HERO.get(slug)
        if spec is not None and seat is not None and any(
            (self.hero_card(hero).spec or "").lower() == spec
            for hero in match.player(seat).heroes_in_play
        ):
            found.append(("Invisible", None))
        if slug in effects.WHEN_ATTACKING_HEROES and seat == match.active:
            # Wight: "Deathtouch when attacking heroes."
            state = match.combat
            if state is not None and state.get("attacker") == body.ref and is_hero_ref(
                state.get("defender") or ""
            ):
                found.extend((keyword, None) for keyword in effects.WHEN_ATTACKING_HEROES[slug])
        if slug in effects.STEALTH_ATTACKING_UNITS and seat == match.active:
            state = match.combat
            defender = None
            if state is not None and state.get("attacker") == body.ref:
                defender = self.body(match, 2 if seat == 1 else 1, state.get("defender") or "")
            if isinstance(defender, CardInstance):
                found.append(("Stealth", None))
        if slug == effects.MIMIC:
            others = [
                other for other in self._bodies_in_play(match)
                if not (isinstance(other, CardInstance) and other.slug == effects.MIMIC)
            ]
            for keyword in effects.MIMICKED:
                if any(self.has_keyword(other, keyword, match) for other in others):
                    found.append((keyword, None))
        return found

    def _bodies_in_play(self, match: MatchState) -> list:
        """Every unit and hero in play, on both sides."""
        found: list = []
        for player in match.players:
            found.extend(card for card in player.play if self.catalog.cards[card.slug].is_unit)
            found.extend(player.heroes_in_play)
        return found

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
        if (
            isinstance(body, CardInstance) and self.text_slug(body) in effects.UNATTACKABLE_BY_TECH_0
            and self.is_tech_0_unit(self.body(match, seat, attacker))
        ):
            # "Tiny Basilisk is unattackable ... by tech 0 units."
            return False
        return True

    def is_tech_0_unit(self, body) -> bool:
        """A unit of tech 0 -- a token is one (UMR p. 13) -- and never a
        hero, which is no unit."""
        if not isinstance(body, CardInstance):
            return False
        card = self.catalog.cards[body.slug]
        return card.is_unit and not (card.tech_level or 0)

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
            if self._unstoppable_by(match, attacker, self.body(match, other, ref)):
                # "... unstoppable by tech 0 units" and the like: it may
                # ignore them.
                continue
            blocking[slot] = ref
        return blocking

    def _unstoppable_by_tech_0(self, match: MatchState, attacker: str) -> bool:
        body = self.body(match, match.active, attacker)
        return isinstance(body, CardInstance) and self.text_slug(body) in effects.UNSTOPPABLE_BY_TECH_0

    def is_demon(self, body) -> bool:
        """A Demon: a unit whose subtype says so, or a hero Metamorphosis
        made one, until it leaves play (step 12)."""
        if isinstance(body, CardInstance):
            return effects.DEMON in self.subtype_of(body).split()
        return isinstance(body, HeroState) and any(
            m.get("kind") == "demon" for m in body.modifiers
        )

    def _unstoppable_by(self, match: MatchState, attacker: str, patroller) -> bool:
        """
        Whether this attacker may ignore one patroller in particular (its
        conditional unstoppable): Predator Tiger's and Tiny Basilisk's tech
        0 units, Cursed Ghoul's units with -1/-1 runes, and the Demons of a
        player with a Shrine of Forbidden Knowledge, which are unstoppable
        by units -- a patrolling hero still stops them (step 12).
        """
        body = self.body(match, match.active, attacker)
        if body is None or patroller is None:
            return False
        unit = isinstance(patroller, CardInstance) and self.catalog.cards[patroller.slug].is_unit
        slug = self.text_slug(body) if isinstance(body, CardInstance) else None
        if slug in effects.UNSTOPPABLE_BY_TECH_0 and self.is_tech_0_unit(patroller):
            return True
        if slug in effects.UNSTOPPABLE_BY_RUNED and unit and patroller.minus_runes > 0:
            return True
        if unit and self.is_demon(body) and any(
            card.slug in effects.DEMONS_UNSTOPPABLE and self.texted(card)
            for card in match.player(match.active).play
        ):
            return True
        return False

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
                rows = [(leader, "squad leader")]
            else:
                rows = [(blocking[slot], "patroller") for slot in PATROL_SLOTS if slot in blocking]
            if self._sneaks_to_units(match, attacker):
                # Stealth while attacking a unit: any of their units, past
                # the patrol zone.
                taken = {ref for ref, _ in rows}
                rows += [
                    (card.ref, "it sneaks past the patrol zone to a unit")
                    for card in self._units_of(match, other)
                    if card.ref not in taken and self.may_be_attacked(match, attacker, card.ref)
                ]
            if self._unstoppable_to_heroes(match, attacker):
                # Wight: "Unstoppable when attacking heroes" -- any of their
                # heroes, past the patrol zone (step 12).
                taken = {ref for ref, _ in rows}
                rows += [
                    (hero_ref(hero.slug), "it is unstoppable when attacking heroes")
                    for hero in match.player(other).heroes_in_play
                    if hero_ref(hero.slug) not in taken
                    and self.may_be_attacked(match, attacker, hero_ref(hero.slug))
                ]
            return tuple(rows)
        why = self._open_why(match, attacker)
        return tuple(
            (ref, why) for ref in self._standing(match, other)
            if self.may_be_attacked(match, attacker, ref)
        )

    def _sneaks_to_units(self, match: MatchState, attacker: str) -> bool:
        """Whether this attacker has stealth while attacking a unit
        (Stalking Tiger) and no detector of theirs sees it, so it may
        sneak past the patrol zone to any of their units."""
        body = self.body(match, match.active, attacker)
        if not isinstance(body, CardInstance) or body.slug not in effects.STEALTH_ATTACKING_UNITS:
            return False
        other = 2 if match.active == 1 else 1
        return not self.detected_by(match, other, attacker)

    def _unstoppable_to_heroes(self, match: MatchState, attacker: str) -> bool:
        body = self.body(match, match.active, attacker)
        return isinstance(body, CardInstance) and self.text_slug(body) in effects.UNSTOPPABLE_ATTACKING_HEROES

    def _open_why(self, match: MatchState, attacker: str) -> str:
        """Why nothing in the patrol zone holds this attacker."""
        other = 2 if match.active == 1 else 1
        if not match.player(other).patrollers():
            return "nothing is patrolling"
        sneaking = self.ignores_patrollers(match, attacker)
        if sneaking == "unstoppable":
            return "it is unstoppable"
        if self._unstoppable_by_tech_0(match, attacker):
            return "it is unstoppable by tech 0 units"
        body = self.body(match, match.active, attacker)
        if isinstance(body, CardInstance) and self.text_slug(body) in effects.UNSTOPPABLE_BY_RUNED:
            return "it is unstoppable by units with -1/-1 runes"
        if self.is_demon(body) and any(
            card.slug in effects.DEMONS_UNSTOPPABLE for card in match.active_player.play
        ):
            return "its Demons are unstoppable by units"
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
        if self.has(match, seat, attacker, "Long-range") and not self.has_keyword(
            body, "Long-range", match,
        ):
            # "When this card attacks, the defender deals no combat damage
            # unless it also has long-range" (UMR p. 17) -- the anti-air
            # it flies over and the tower still shoot (its rulings).
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
        return max(0, self.attack_value(match, seat, attacker) - self.lethal_damage(match, seat, attacker, body))

    def stampedes(self, match: MatchState, body) -> bool:
        """Whether Stampede sends this unit's excess combat damage to the
        base this turn: a unit, its controller's Stampede in play."""
        if not isinstance(body, CardInstance) or not self.catalog.cards[body.slug].is_unit:
            return False
        return any(lasting.get("kind") == "stampede"
                   for lasting in match.player(body.controller).lasting)

    def lethal_damage(self, match: MatchState, seat: int, attacker: str, body) -> int:
        """
        How much of `attacker`'s combat damage destroys `body`: its HP
        left and its armor -- the author's reading of overpower, 2026-10-08
        -- none of the armor where the attacker pierces it, and **one**
        where it has deathtouch: "One deathtouch damage is enough to
        destroy a card, so a deathtouch card with overpower or Stampede
        reapplies all damage after the first damage" (UMR p. 18).
        """
        hitting = self.body(match, seat, attacker)
        if self.has_keyword(hitting, "Deathtouch", match):
            return 1
        hp = self.body_stats(match, body)[1]
        armor = 0 if self.has_keyword(hitting, "Armor piercing", match) else body.armor
        return max(0, hp - body.damage) + armor

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
        if self.stampedes(match, self.body(match, seat, attacker)) and self.body(match, other, defender) is not None:
            # Stampede's excess goes to the base, over overpower's.
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
        # Indestructible units and units that can't leave play are
        # skipped: the next lowest goes instead (the obliterate ruling).
        units = [
            card for card in match.player(other).play
            if self.catalog.cards[card.slug].is_unit and self.may_be_destroyed(match, card)
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
                          taken: Sequence[str] = (), frame: Optional[dict] = None,
                          ) -> list[tuple[int, str]]:
        """
        Everything `choose` names for an effect `seat` controls, the
        opponent's side first: before resist, invisibility and the
        flagbearer narrow it (`target_rows`). `taken` is what this cast
        has already chosen, as keys, for a part that must choose another
        (Brick Thief's repair, Two Step's second partner); `frame` the
        effect under way, for a filter that reads it -- the card it comes
        from ("another unit"), what an earlier part chose (Zane's shove,
        Circle of Life's sacrifice).

        Step 11 added the places that are not on the table: a side's
        workers (`"2:workers"`, all alike), an empty patrol slot
        (`"2:slot:elite"`), and a card in its owner's hand or codex
        (`"1:hand:fire_dart"`, `"1:codex:predator_tiger"`) -- the owner's
        alone, and so the effect's controller's alone.
        """
        other = 2 if seat == 1 else 1
        frame = frame or {}
        found: list[tuple[int, str]] = []

        def tech(card: CardInstance) -> int:
            return self.catalog.cards[card.slug].tech_level or 0

        for side in (other, seat):
            player = match.player(side)
            units = self._units_of(match, side)
            hero = [hero_ref(one.slug) for one in player.heroes_in_play]
            damageable = [
                (side, ref) for ref in self._buildings_of(match, side)
                if not self._under_construction(player, ref)
            ] + [(side, card.ref) for card in self._building_cards_of(match, side)]
            patrollers = [(side, ref) for ref in player.patrollers().values()]

            if choose == "patroller":
                found += patrollers
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
                found += damageable
            elif choose == "other_building":
                found += [(side, ref) for ref in self._buildings_of(match, side)]
                found += [(side, card.ref) for card in self._building_cards_of(match, side)]
            elif choose == "unit":
                found += [(side, card.ref) for card in units]
            elif choose == "unit_or_building":
                found += [(side, card.ref) for card in units] + damageable
            elif choose == "unit_hero_or_building":
                found += [(side, card.ref) for card in units] + [(side, ref) for ref in hero]
                found += damageable
            elif choose == "patroller_or_building":
                found += patrollers + damageable
            elif choose == "patrolling_unit":
                found += [(side, card.ref) for card in units if card.patrol_slot is not None]
            elif choose == "patrolling_unit_or_building":
                found += [(side, card.ref) for card in units if card.patrol_slot is not None]
                found += damageable
            elif choose == "other_unit":
                found += [(side, card.ref) for card in units if card.ref != frame.get("source")]
            elif choose == "own_unit":
                if side == seat:
                    found += [(side, card.ref) for card in units]
            elif choose == "own_green_unit":
                if side == seat:
                    found += [(side, card.ref) for card in units if self.color_of(card) == "green"]
            elif choose == "own_balance_hero":
                if side == seat:
                    found += [(side, hero_ref(one.slug)) for one in player.heroes_in_play
                              if (self.hero_card(one).spec or "").lower() == "balance"]
            elif choose == "opposing_unit_tech_0_2":
                if side != seat:
                    found += [(side, card.ref) for card in units if tech(card) <= 2]
            elif choose == "unit_tech_0_1":
                found += [(side, card.ref) for card in units if tech(card) <= 1]
            elif choose == "unit_tech_1_2":
                found += [(side, card.ref) for card in units if 1 <= tech(card) <= 2]
            elif choose.startswith("unit_tech_") and choose[len("unit_tech_"):].isdigit():
                level = int(choose.rsplit("_", 1)[1])
                found += [(side, card.ref) for card in units if tech(card) == level]
            elif choose == "own_unpartnered":
                if side == seat:
                    found += [(side, card.ref) for card in units
                              if self.partnered(match, card) is None]
            elif choose == "base":
                found.append((side, "base"))
            elif choose == "workers":
                if player.workers > 0:
                    found.append((side, WORKERS))
            elif choose == "worker_or_building_card":
                # "A worker or building card (not add-on)" -- any
                # player's workers, all alike (Detonate's rulings).
                if player.workers > 0:
                    found.append((side, WORKERS))
                found += [(side, card.ref) for card in self._building_cards_of(match, side)]
            elif choose == "upgrade_spell_or_building_card":
                found += [
                    (side, card.ref) for card in player.play
                    if not self.catalog.cards[card.slug].is_unit
                ]
            elif choose == "upgrade_or_ongoing":
                found += [
                    (side, card.ref) for card in player.play
                    if self.catalog.cards[card.slug].is_upgrade
                    or self.catalog.cards[card.slug].is_spell
                ]
            elif choose == "unit_upgrade_or_workers":
                found += [(side, card.ref) for card in units]
                found += [(side, card.ref) for card in player.play
                          if self.catalog.cards[card.slug].is_upgrade]
                if player.workers > 0:
                    found.append((side, WORKERS))
            elif choose == "timed":
                # Time Spiral, Tinkerer, Seer: a card with a time rune, in
                # play or in the future, any player's (their rulings).
                found += [(side, card.ref) for card in player.play if card.time_runes > 0]
                found += [(side, hero_ref(one.slug)) for one in player.heroes_in_play
                          if one.time_runes > 0]
                found += [(side, future_ref(card)) for card in player.future if card.time_runes > 0]
            elif choose == "own_sacrificable":
                # Omegacron's cost: a unit, hero, worker or upgrade of yours
                # -- never one that can't be sacrificed (UMR p. 17).
                if side == seat:
                    found += [(side, card.ref) for card in units if self.may_sacrifice(match, card)]
                    found += [(side, hero_ref(one.slug)) for one in player.heroes_in_play]
                    if player.workers > 0:
                        found.append((side, WORKERS))
                    found += [(side, card.ref) for card in player.play
                              if self.catalog.cards[card.slug].is_upgrade]
            elif choose in ("weakest_own_to_sacrifice", "weakest_opposing_to_sacrifice",
                            "weakest_opposing_to_destroy", "lowest_opposing_to_destroy"):
                mine = choose.startswith("weakest_own")
                if (side == seat) == mine:
                    if choose == "lowest_opposing_to_destroy":
                        chosen = self.lowest_tech(match, side)
                    else:
                        chosen = self.weakest(match, side, sacrifice=choose.endswith("sacrifice"))
                    found += [(side, card.ref) for card in chosen]
            elif choose == "own_unit_to_sacrifice":
                if side == seat:
                    found += [(side, card.ref) for card in units if self.may_sacrifice(match, card)]
            elif choose == "unit_or_hero_tech_0_2":
                found += [(side, card.ref) for card in units if tech(card) <= 2]
                found += [(side, ref) for ref in hero]
            elif choose == "buried_playable":
                if side == seat:
                    for yard in self.graveyards(player):
                        for index, buried in enumerate(yard.buried):
                            if not self.why_not_play_buried(player, buried["slug"]):
                                found.append((side, f"{BURIED}{yard.id}:{index}"))
            elif choose == "anything_destroyable":
                # Zarramonde: "a unit, hero, worker, upgrade, or ongoing
                # spell".
                found += [(side, card.ref) for card in units]
                found += [(side, ref) for ref in hero]
                if player.workers > 0:
                    found.append((side, WORKERS))
                found += [(side, card.ref) for card in player.play
                          if self.catalog.cards[card.slug].is_upgrade
                          or self.catalog.cards[card.slug].is_spell]
            elif choose == "lowest_against_to_destroy":
                if side == frame.get("against"):
                    found += [(side, card.ref) for card in self.lowest_tech(match, side)]
            elif choose == "units_of_against":
                if side == frame.get("against"):
                    found += [(side, card.ref) for card in units]
            elif choose == "runed_card":
                # Plague Lab: a card with runes and a kind of them -- one
                # row per kind, one rune a card (its rulings).
                done = frame.get("lab_done") or []
                bodies = [*player.play, *player.heroes_in_play]
                for body in bodies:
                    ref = body.ref if isinstance(body, CardInstance) else hero_ref(body.slug)
                    if target_key(side, ref) in done:
                        continue
                    for kind in rune_kinds(body):
                        found.append((side, f"{ref}#{kind}"))
            elif choose in ("hero_in_play", "other_hero_in_play"):
                first = (frame.get("taken") or [None])[0]
                found += [(side, ref) for ref in hero
                          if choose == "hero_in_play" or target_key(side, ref) != first]
            elif choose == "own_workers":
                if side == seat and player.workers > 0:
                    found.append((side, WORKERS))
            elif choose == "own_skeleton":
                if side == seat:
                    found += [(side, card.ref) for card in units
                              if effects.SKELETON in self.subtype_of(card).split()
                              and self.may_sacrifice(match, card)]
            elif choose == "own_non_demon_to_sacrifice":
                if side == seat:
                    found += [(side, card.ref) for card in units
                              if not self.is_demon(card) and self.may_sacrifice(match, card)]
            elif choose in ("own_unit_tech_0_1", "opposing_unit_tech_0_1"):
                if (side == seat) == choose.startswith("own"):
                    found += [(side, card.ref) for card in units if tech(card) <= 1]
            elif choose == "flier":
                found += [(side, card.ref) for card in units if self.has_keyword(card, "Flying", match)]
                found += [(side, hero_ref(one.slug)) for one in player.heroes_in_play
                          if self.has_keyword(one, "Flying", match)]
            elif choose == "dead_hero":
                # Blackhand Resurrector: a hero of yours in the command zone
                # that died this game -- summoning runes or none (its ruling),
                # but never past the hero limit (the author, 2026-10-10).
                if side == seat and len(player.heroes_in_play) < self.hero_limit(player):
                    died = {event.get("slug") for event in match.events
                            if event.get("kind") == "hero_died" and event.get("owner") == seat}
                    found += [(side, hero_ref(one.slug)) for one in player.heroes
                              if not one.in_play and one.slug in died]
            elif choose == "own_ready_other":
                # Voidblocker: another of the attacker's side's ready units
                # or heroes.
                if side == seat:
                    attacker = (match.combat or {}).get("attacker") or match.attacking
                    found += [(side, card.ref) for card in units
                              if not card.exhausted and card.ref != attacker]
                    found += [(side, hero_ref(one.slug)) for one in player.heroes_in_play
                              if not one.exhausted and hero_ref(one.slug) != attacker]
            elif choose == "opponent_hand_nonunit":
                # Carrion Curse: the opponent's hand, looked at by the caster
                # alone -- the non-unit cards, each named once.
                if side != seat:
                    found += [(side, HAND + slug) for slug in dict.fromkeys(player.hand)
                              if not self.catalog.cards[slug].is_unit]
            elif choose == "patrolling_weak_unit":
                # Forgotten Fighter: a patrolling tech 0 or I unit with 2 ATK
                # or less.
                found += [(side, card.ref) for card in units
                          if card.patrol_slot is not None and tech(card) <= 1
                          and self.unit_stats(card, match)[0] <= 2]
            elif choose == "unit_tech_upto_2":
                found += [(side, card.ref) for card in units if tech(card) <= 2]
            elif choose == "opposing_upgrade_spell_or_building_card":
                if side != seat:
                    found += [(side, card.ref) for card in player.play
                              if not self.catalog.cards[card.slug].is_unit]
            elif choose == "own_unit_tech_1_2":
                if side == seat:
                    found += [(side, card.ref) for card in units if 1 <= tech(card) <= 2]
            elif choose == "stingers_of_against":
                if side == frame.get("against"):
                    found += [(side, card.ref) for card in units if card.slug == effects.STINGER]
            elif choose == "ground_patroller":
                found += [(side, ref) for ref in player.patrollers().values()
                          if not self.has_keyword(self.body(match, side, ref), "Flying", match)]
            elif choose == "empty_slot":
                # Zane's shove: an empty slot of the shoved patroller's
                # own zone -- the side the frame's first pick was on.
                shoved = (frame.get("taken") or [None])[0]
                if shoved is not None and int(shoved.split(":", 1)[0]) == side:
                    filled = player.patrollers()
                    found += [(side, f"{SLOT}{slot}") for slot in PATROL_SLOTS if slot not in filled]
            elif side == seat and choose in _PRIVATE_FILTERS:
                found += [(side, ref) for ref in self._private_candidates(match, seat, choose, frame)]
            elif choose in _PRIVATE_FILTERS:
                pass
            else:
                raise ValueError(f"not a target filter: {choose!r}")
        if choose in ("other_building", "own_unpartnered"):
            found = [row for row in found if target_key(*row) not in taken]
        return found

    def _private_candidates(self, match: MatchState, seat: int, choose: str,
                            frame: dict) -> list[str]:
        """
        The cards in `seat`'s hand or codex a part may choose, each named
        once (`hand:<slug>`, `codex:<slug>`), in the hand's order and the
        codex's: **its owner's alone** -- which is why only the effect's
        own controller is offered any.
        """
        player = match.player(seat)
        cards = self.catalog.cards
        hand = list(dict.fromkeys(player.hand))
        codex = [slug for slug, left in self.codex_counts(player) if left > 0]

        def level(slug: str) -> int:
            return cards[slug].tech_level or 0

        if choose == "hand_card":
            return [HAND + slug for slug in hand]
        if choose == "hand_unit":
            return [HAND + slug for slug in hand if cards[slug].is_unit]
        if choose == "deck_top":
            # Vir: the top card of his draw pile, to him alone -- nothing on
            # an empty pile, and no reshuffle (his rulings).
            return [DECK + player.deck[-1]] if player.deck else []
        if choose == "hand_card_with_deck":
            return [HAND + slug for slug in hand] if player.deck else []
        if choose == "deck_top_playable":
            if not player.deck:
                return []
            top = player.deck[-1]
            return [] if self.why_not_play_top(match, player, top) else [DECK + top]
        if choose == "discard_fading_unit":
            # Rememberer: a unit with fading from the discard pile, its tech
            # building and spec met (its rulings).
            return [DISCARD + slug for slug in dict.fromkeys(player.discard)
                    if cards[slug].is_unit
                    and any(name == "Fading" for name, _ in keywords.keywords(slug))
                    and self.tech_building_active(player, level(slug))
                    and not self._why_not_spec(player, cards[slug])]
        if choose == "codex_tech_1_2_unit":
            return [CODEX + slug for slug in codex if cards[slug].is_unit and 1 <= level(slug) <= 2]
        if choose == "codex_distortion":
            # Temporal Distortion: a unit of the tech level of the one
            # returned, costing no more, requirements ignored.
            gone = frame.get("distorted")
            if not gone:
                return []
            return [CODEX + slug for slug in codex
                    if cards[slug].is_unit and level(slug) == gone["tech"]
                    and (cards[slug].cost or 0) <= gone["cost"]]
        if choose == "codex_demonology_spell":
            return [CODEX + slug for slug in codex
                    if cards[slug].is_spell and (cards[slug].spec or "").lower() == "demonology"]
        if choose == "discard_tech_1_2_cheap":
            # Garth at 7: a tech I or II unit costing 5 or less, its tech
            # building and spec met (his rulings).
            return [DISCARD + slug for slug in dict.fromkeys(player.discard)
                    if cards[slug].is_unit and 1 <= level(slug) <= 2 and (cards[slug].cost or 0) <= 5
                    and self.tech_building_active(player, level(slug))
                    and not self._why_not_spec(player, cards[slug])]
        if choose == "hand_unit_tech_0_2":
            return [HAND + slug for slug in hand if cards[slug].is_unit and level(slug) <= 2]
        if choose == "hand_unit_built":
            # Feral Strike: "if you have tech buildings of the same tech
            # level as them" -- the spec ignored (its ruling).
            return [HAND + slug for slug in hand
                    if cards[slug].is_unit and self.tech_building_active(player, level(slug))]
        if choose == "codex_unit":
            return [CODEX + slug for slug in codex if cards[slug].is_unit]
        if choose == "codex_tiger":
            return [CODEX + slug for slug in codex
                    if cards[slug].is_unit and "Tiger" in (cards[slug].subtype or "")]
        if choose == "codex_circle":
            # Circle of Life: a green unit one tech higher than the one
            # sacrificed, printed cost 5 or less (its rulings: Gigadon is 9).
            sacrificed = frame.get("sacrificed_tech")
            if sacrificed is None:
                return []
            return [CODEX + slug for slug in codex
                    if cards[slug].is_unit and (cards[slug].color or "").lower() == "green"
                    and level(slug) == sacrificed + 1 and (cards[slug].cost or 0) <= 5]
        if choose == "fire_spell":
            # Cinderblast Dragon: a non-ultimate Fire spell from the hand
            # or the codex, played free -- one that could do something.
            found = []
            for prefix, slugs in ((HAND, hand), (CODEX, codex)):
                for slug in slugs:
                    card = cards[slug]
                    if (card.is_spell and (card.spec or "").lower() == "fire"
                            and "Ultimate" not in card.type
                            and self.spell_can_resolve(match, seat, slug, player.gold)):
                        found.append(prefix + slug)
            return found
        raise ValueError(f"not a target filter: {choose!r}")

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
                    gold: Optional[int] = None, flagbearer_done: bool = False,
                    frame: Optional[dict] = None) -> tuple[TargetRow, ...]:
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
        for side, ref in self.target_candidates(match, seat, part.choose, taken, frame):
            if not part.targeted:
                rows.append(TargetRow(target_key(side, ref), side, ref))
                continue
            if not self.targetable(match, seat, side, ref):
                continue
            if self.has_keyword(self.body(match, side, ref), "Untargetable", match):
                # "This card can't be the target of spells or abilities"
                # -- anybody's, its controller's included (UMR p. 18).
                continue
            if self._shielded_from(match, side, ref, frame):
                continue
            resist = self.resist_cost(match, side, ref) if side != seat else 0
            if resist > gold:
                continue
            body = self.body(match, side, ref)
            flag = side != seat and self.is_flagbearer_body(match, body)
            rows.append(TargetRow(target_key(side, ref), side, ref, resist, flag))
        if part.targeted and not flagbearer_done and any(row.flagbearer for row in rows):
            return tuple(row for row in rows if row.flagbearer)
        return tuple(TargetRow(row.key, row.seat, row.ref, row.resist, False) for row in rows)

    def _shielded_from(self, match: MatchState, side: int, ref: str, frame: Optional[dict]) -> bool:
        """Nullcraft: "Can't be the {target} of Buff or Debuff spells" --
        a spell whose subtype says either (its ruling)."""
        body = self.body(match, side, ref)
        if not isinstance(body, CardInstance) or self.text_slug(body) not in effects.UNTARGETABLE_BY_BUFFS:
            return False
        spell = (frame or {}).get("spell")
        card = self.catalog.cards.get(spell) if spell else None
        if card is None or not card.is_spell:
            return False
        return any(word in effects.BUFF_SUBTYPES for word in (card.subtype or "").split())

    def damage_bonus(self, match: MatchState, frame: dict) -> int:
        """
        What an effect's damage gets on top of what it prints: Hotter
        Fire's "Your red spells and abilities that deal damage deal 1
        damage more" -- a red spell's, a red hero's ability's, any ability
        on a red card -- each copy its controller has (its rulings), and
        never combat damage, which no effect deals. Divided damage gets
        it once, on the total (the Card FAQ).
        """
        origin = frame.get("origin") or frame.get("spell")
        if origin is None:
            source = frame.get("source")
            body = self.body(match, frame["seat"], source) if source else None
            origin = getattr(body, "slug", None)
        if origin is None:
            return 0
        card = self.catalog.by_slug(origin)
        if (card.color or "").lower() != "red":
            return 0
        return sum(
            1 for other in match.player(frame["seat"]).play
            if other.slug == effects.HOTTER_FIRE and self.texted(other)
        )

    def mode_rows(self, match: MatchState, frame: dict, part) -> tuple[tuple[str, str, bool], ...]:
        """
        The modes a "choose one" part offers, each `(key, says, allowed)`:
        Feral Strike's and Murkwood Allies' both always, and Land
        Octopus's sacrifice of two workers only where its controller has
        two -- "do as much as you can" leaves the Octopus itself.
        """
        seat = frame["seat"]
        rows = []
        for key, says in part.modes:
            allowed = True
            if key == "workers":
                allowed = match.player(seat).workers >= 2
            elif key == "boosted":
                # The Graveyard's buried unit, boosted where it has a boost
                # and its controller can pay for both (the boost ruling).
                slug = self.buried_slug(match, seat, frame.get("picked") or "")
                boost = self.boost_cost(slug) if slug else None
                player = match.player(seat)
                allowed = boost is not None and player.gold >= self.effective_cost(player, slug) + boost
            rows.append((key, says, allowed))
        return tuple(rows)

    def buried_slug(self, match: MatchState, seat: int, key: str) -> Optional[str]:
        """The slug a buried pick names ("1:buried:7:0"), or `None`."""
        found = buried_entry(match, key)
        return None if found is None else found[1]["slug"]

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
                found.append(AbilityOption("stop_the_music", card.ref, pays=self.cost_words("stop_the_music")))
        for hero in player.heroes_in_play:
            for when, effect in effects.rows(hero.slug, hero.level):
                if when == "ability":
                    found.append(self._ability(match, seat, hero, hero_ref(hero.slug), effect))
        if any(card.slug in effects.MAESTROS and self.texted(card) for card in player.play):
            for card in player.play:
                if self.catalog.cards[card.slug].is_unit and self.is_virtuoso(card.slug):
                    found.append(self._ability(match, seat, card, card.ref, "maestro"))
        # Red and green's: the abilities printed on a card in play -- a
        # unit's, a building card's, an upgrade's (step 11).
        for card in player.play:
            for when, effect in effects.rows(self.text_slug(card) or ""):
                if when == "ability":
                    found.append(self._ability(match, seat, card, card.ref, effect))
        # The one ability used from the future: Omegacron's (step 12).
        for card in player.future:
            for when, effect in effects.rows(card.slug):
                if when == "future_ability":
                    found.append(self._ability(match, seat, card, future_ref(card), effect))
        return tuple(found)

    def _ability(self, match: MatchState, seat: int, body, source: str, effect: str) -> AbilityOption:
        return AbilityOption(effect, source, self._ability_why_not(match, seat, body, effect, source),
                             self.cost_words(effect))

    def ability_cost(self, effect: str) -> "effects.Cost":
        return effects.COSTS.get(effect, effects.Cost(exhaust=True))

    def ready_skeletons(self, match: MatchState, seat: int) -> list[CardInstance]:
        """`seat`'s ready Skeletons, arrival fatigue no bar -- what Skeletal
        Lord exhausts (its ruling)."""
        return [card for card in match.player(seat).play
                if effects.SKELETON in self.subtype_of(card).split() and not card.exhausted]

    def cost_words(self, effect: str) -> str:
        """What an ability costs, in words for its button: "exhaust",
        "pay 1 gold and exhaust", "sacrifice it"."""
        cost = self.ability_cost(effect)
        words = []
        if cost.gold:
            words.append(f"pay {cost.gold} gold")
        if cost.discard:
            words.append(f"discard {cost.discard} cards")
        if cost.runes:
            kind, count = cost.runes
            rune = "+1/+1" if kind == "plus" else kind
            words.append(f"remove {'a' if count == 1 else count} {rune} rune{'' if count == 1 else 's'}")
        if cost.sacrifice:
            words.append("sacrifice it")
        if cost.skeletons:
            words.append(f"exhaust {cost.skeletons} Skeletons")
        if cost.exhaust:
            words.append("exhaust")
        return " and ".join(words) or "use it"

    def _ability_why_not(self, match: MatchState, seat: int, body, effect: str,
                         source: Optional[str] = None) -> str:
        """Why an ability may not be used now, or "": every part of its
        cost payable (UMR p. 8), and something its text could do with
        what is left."""
        cost = self.ability_cost(effect)
        player = match.player(seat)
        if cost.exhaust:
            why = self.may_exhaust(body, match)
            if why:
                return why
        if cost.gold and player.gold < cost.gold:
            return "not enough gold"
        if cost.runes:
            kind, count = cost.runes
            have = (body.plus_runes if kind == "plus"
                    else body.time_runes if kind == "time" else body.runes.get(kind, 0))
            if have < count:
                rune = "+1/+1" if kind == "plus" else kind
                return f"it needs {count} {rune} rune{'' if count == 1 else 's'}"
        if cost.discard and len(player.hand) < cost.discard:
            return f"it needs {cost.discard} cards in hand to discard"
        if cost.needs_spell and not player.spells_played:
            return "you have not played a spell this turn"
        if cost.once and any(m.get("kind") == "once" and m.get("effect") == effect
                             for m in getattr(body, "modifiers", ())):
            return "it has been used this turn"
        if cost.skeletons and len(self.ready_skeletons(match, seat)) < cost.skeletons:
            return f"it needs {cost.skeletons} ready Skeletons"
        if not self.spell_can_resolve(match, seat, effect, player.gold - cost.gold,
                                      {"source": source}):
            return "there is nothing it could target"
        return ""

    # -- The upkeep -------------------------------------------------------------------

    def upkeep_effects(self, player: PlayerState,
                       match: Optional[MatchState] = None) -> tuple[str, ...]:
        """
        The upkeep effects this player has (UMR p. 5), in the order they
        run unless the order is theirs to choose: the surplus's draw,
        healing (Helpful Turtle), and Star-Crossed Starlet's damage to
        herself.
        """
        found = []
        # A time rune off each fading card and hero, and off each card in
        # the future (UMR p. 17; step 12): a card with none left from the
        # start never fades.
        found += [f"fade:{card.id}" for card in player.play
                  if card.time_runes > 0 and self.fading(card)]
        found += [f"fade_hero:{hero.slug}" for hero in player.heroes_in_play
                  if hero.time_runes > 0 and self.fading(hero)]
        found += [f"forecast:{card.id}" for card in player.future]
        add_on = player.add_on
        if add_on is not None and add_on.active and add_on.slug in effects.UPKEEP_DRAW:
            found.append("draw")
        texts = [self.text_slug(card) for card in player.play]
        # Red and green's gains (step 11): Gemscout Owl's and Galina's.
        if any(slug in effects.UPKEEP_GOLD for slug in texts):
            found.append("owl")
        if any(slug in effects.UPKEEP_GREEN_GOLD for slug in texts):
            found.append("galina")
        if self.healing(player):
            found.append("healing")
        if any(slug in effects.UPKEEP_SELF_DAMAGE for slug in texts):
            found.append("starlet")
        # One each: Land Octopus's choice, Dothram Horselord's side.
        found += [f"octopus:{card.id}" for card in player.play
                  if self.text_slug(card) in effects.UPKEEP_CHOICE]
        found += [f"dothram:{card.id}" for card in player.play
                  if self.text_slug(card) in effects.JOINS_THE_STRONGER]
        if match is not None and self.doomed_by(match, player.seat):
            # Vandy at 5: "They lose +2/+2 and die at your next upkeep."
            found.append("doom")
        # Purple and black's (step 12): Banefire Golem's sacrifice, Plague
        # Lord's runes onto the bases, the Shrine's 1 -- and Promise of
        # Payment's debt, last of all (its rulings).
        found += [f"banefire:{card.id}" for card in player.play
                  if self.text_slug(card) in effects.UPKEEP_SACRIFICE]
        found += [f"plague_lord:{card.id}" for card in player.play
                  if self.text_slug(card) in effects.PLAGUE_UPKEEP]
        found += [f"shrine:{card.id}" for card in player.play
                  if self.text_slug(card) in effects.SELF_BASE_UPKEEP]
        if player.debt:
            found.append("debt")
        return tuple(found)

    @staticmethod
    def doomed_by(match: MatchState, seat: int) -> list:
        """The units Vandy's max level doomed for `seat`'s next upkeep,
        either side's."""
        return [card for card in match.instances()
                if any(m.get("kind") == "doomed" and m.get("seat") == seat for m in card.modifiers)]

    def upkeep_ordered(self, due) -> tuple[str, ...]:
        """
        Which of the upkeep effects due have their order asked: a death or
        a sacrifice beside what it changes -- Starlet's damage and healing
        (her ruling: "you, as the active player, can choose the order of
        your upkeep effects"), Starlet's or Land Octopus's beside Dothram
        Horselord, whose side follows the total ATK.
        """
        deaths = [name for name in due if name == "starlet" or name.startswith(("octopus:", "banefire:"))]
        found = set()
        if "starlet" in due and "healing" in due:
            found |= {"starlet", "healing"}
        dothrams = [name for name in due if name.startswith("dothram:")]
        if dothrams and deaths:
            found |= set(dothrams) | set(deaths)
        # Step 12: a Banefire Golem's sacrifice and its damage change how
        # many -1/-1 runes Plague Lord counts.
        banefires = [name for name in due if name.startswith("banefire:")]
        lords = [name for name in due if name.startswith("plague_lord:")]
        if banefires and lords:
            found |= set(banefires) | set(lords)
        # Promise of Payment's debt beside anything else due: the upkeep's
        # order is the active player's (the author, 2026-10-10), and what
        # comes before the debt -- a gain, or a death that frees Gilded
        # Glaxx's gold -- decides whether it can be paid.
        if "debt" in due and len(due) > 1:
            found |= set(due)
        return tuple(name for name in due if name in found)

    def upkeep_order_matters(self, player: PlayerState) -> bool:
        """Whether the order is a question at all (`upkeep_ordered`)."""
        return bool(self.upkeep_ordered(self.upkeep_effects(player)))

    def total_atk(self, match: MatchState, seat: int) -> int:
        """A player's total ATK -- Dothram Horselord's question: every unit
        and hero they have in play, as each stands."""
        player = match.player(seat)
        units = sum(self.unit_stats(card, match)[0] for card in player.play
                    if self.catalog.cards[card.slug].is_unit)
        return units + sum(self.hero_stats(hero, match)[0] for hero in player.heroes_in_play)

    def patrol_candidates(self, match: MatchState) -> tuple[str, ...]:
        """What the active player may lock into the patrol zone: ready
        units and a ready hero; arrival fatigue does not stop a patroller
        (UMR p. 10)."""
        player = match.active_player
        found = [
            card.ref for card in player.play
            if self.catalog.cards[card.slug].is_unit and not card.exhausted
            and (self.text_slug(card) not in effects.CANT_PATROL or self.unbound(card))
            and not self.shackled(match, card) and not player.peace
        ]
        found.extend(
            hero_ref(hero.slug) for hero in player.heroes_in_play if not hero.exhausted
        )
        return tuple(found)

    def codex_counts(self, player: PlayerState) -> tuple[tuple[str, int], ...]:
        """
        The player's codex, as (slug, copies left), by tech level (the
        author, 2026-10-10): every Tech I card, then Tech II, then
        Tech III, then the spells together -- the ultimates last -- each
        group spec by spec as the deck names them, then by cost and name
        (`codex_order`).
        """
        found: dict[str, int] = {}
        for index, spec in enumerate(player.specs):
            for slug in self.catalog.codex_for(spec):
                found.setdefault(slug, index)
        order = sorted(found, key=lambda slug: self.codex_order(slug, found[slug]))
        return tuple((slug, player.codex.get(slug, 0)) for slug in order)

    def codex_order(self, slug: str, spec: int = 0) -> tuple:
        """Where a card sits in a codex: its tech level, the spells after
        every level and an ultimate after them, then its spec's place in
        the deck (`spec`), its cost and its name."""
        card = self.catalog.cards[slug]
        if card.is_spell:
            group = 5 if "Ultimate" in card.type else 4
        else:
            group = card.tech_level or 0
        return group, spec, card.cost or 0, card.name

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
            rows.append(self._playable_row(player, slug, why))
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
        units -- and split into the copies in the hand, those in the
        discard pile and the rest, which **My deck** shows apart (the
        author, 2026-10-09). A tech choice
        not yet in the discard pile is not in it.
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
        discarded = Counter(player.discard)
        ordered = sorted(counted, key=place)
        return OwnDeck(
            cards=tuple((slug, counted[slug]) for slug in ordered),
            held=tuple((slug, held[slug]) for slug in ordered if held[slug]),
            discarded=tuple((slug, discarded[slug]) for slug in ordered if discarded[slug]),
            elsewhere=tuple((slug, counted[slug] - held[slug] - discarded[slug])
                            for slug in ordered if counted[slug] > held[slug] + discarded[slug]),
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


#: How a card in the future is named (step 12): "future:<id>" -- not in
#: play, so no `unit:` ref, and offered only to what reaches the future.
FUTURE = "future:"


def future_ref(card: CardInstance) -> str:
    return f"{FUTURE}{card.id}"


#: How a unit buried in a Graveyard is named: "buried:<the Graveyard's
#: id>:<its place in the Graveyard>" (step 12).
BURIED = "buried:"


def buried_entry(match: MatchState, key: str):
    """The Graveyard and the entry a buried pick names -- a target key
    "1:buried:7:0", or the ref alone -- or `None`."""
    ref = key.split(":", 1)[1] if key[:2] in ("1:", "2:") else key
    if not ref.startswith(BURIED):
        return None
    try:
        yard_id, index = (int(part) for part in ref[len(BURIED):].split(":"))
    except ValueError:
        return None
    yard = match.instance(yard_id)
    if yard is None or not 0 <= index < len(yard.buried):
        return None
    return yard, yard.buried[index]


#: A card in its owner's discard pile, chosen by its owner alone (Garth's
#: max level, Rememberer): "1:discard:<slug>" (step 12).
DISCARD = "discard:"
#: A card in its owner's draw pile (Vir's top card): "1:deck:<slug>".
DECK = "deck:"


def rune_kinds(body) -> list[str]:
    """The kinds of rune a card or hero carries -- "plus", "minus", "time"
    and the named ones -- for Plague Lab (step 12)."""
    found = []
    if body.plus_runes:
        found.append("plus")
    if body.minus_runes:
        found.append("minus")
    if body.time_runes:
        found.append("time")
    found += [kind for kind, count in sorted((getattr(body, "runes", None) or {}).items()) if count]
    return found


#: How a target names a side's workers, all alike: "2:workers".
WORKERS = "workers"
#: How a target names an empty patrol slot ("2:slot:elite"), a card in
#: its owner's hand ("1:hand:fire_dart") or codex ("1:codex:gigadon").
SLOT = "slot:"
HAND = "hand:"
CODEX = "codex:"
#: The filters whose candidates are in the controller's hand or codex.
_PRIVATE_FILTERS = frozenset({
    "hand_card", "hand_unit_tech_0_2", "hand_unit_built", "codex_unit", "codex_tiger",
    "codex_circle", "fire_spell",
    # Purple and black's (step 12).
    "hand_unit", "codex_demonology_spell", "discard_tech_1_2_cheap",
    "deck_top", "hand_card_with_deck", "deck_top_playable", "discard_fading_unit",
    "codex_tech_1_2_unit", "codex_distortion",
})


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
