"""
The cards, read from `codex/data/`.

Every card, token, building, worker and hero the Codex Card Database
holds, imported whole by `scripts/import_codex_cards.py` and never
edited by hand. A card is keyed by its slug (`trojan_duck`) and is never
held or compared by its name; `CardCatalog.name` is the one way back
from a slug to a name, for wording alone (docs/design/codex.md, "The
cards are data").
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

DATA_DIR = Path(__file__).resolve().parent / "data"
IMAGE_DIR = Path(__file__).resolve().parent / "images"
CARD_IMAGE_DIR = IMAGE_DIR / "cards"

KIND_CARD = "card"
KIND_TOKEN = "token"
KIND_BUILDING = "building"
KIND_WORKER = "worker"

#: The spec every starting deck comes from: the ten neutral cards.
NEUTRAL = "neutral"


@dataclass(frozen=True)
class Card:
    slug: str
    name: str
    kind: str
    type: str
    subtype: Optional[str]
    color: Optional[str]
    spec: Optional[str]
    starting_zone: Optional[str]
    cost: Optional[int]
    tech_level: Optional[int]
    atk: Optional[int]
    hp: Optional[int]
    target_icon: bool
    text: tuple[str, ...]
    flavor_text: Optional[str]
    sirlins_filename: Optional[str]

    @property
    def is_unit(self) -> bool:
        return "Unit" in self.type

    @property
    def is_spell(self) -> bool:
        return "Spell" in self.type

    @property
    def picture(self) -> Optional[Path]:
        """The card's own art, where the database has one."""
        return CARD_IMAGE_DIR / f"{self.slug}.jpg" if self.sirlins_filename else None


@dataclass(frozen=True)
class HeroBand:
    min_level: int
    atk: int
    hp: int
    text: tuple[str, ...]


@dataclass(frozen=True)
class Hero:
    slug: str
    name: str
    color: Optional[str]
    spec: Optional[str]
    subtype: Optional[str]
    cost: int
    max_level: int
    bands: tuple[HeroBand, ...]
    sirlins_filename: Optional[str]

    def band(self, level: int) -> HeroBand:
        """The band a hero of `level` is in."""
        return [band for band in self.bands if band.min_level <= level][-1]

    @property
    def picture(self) -> Optional[Path]:
        return CARD_IMAGE_DIR / f"{self.slug}.jpg" if self.sirlins_filename else None


def _spec_key(spec: str) -> str:
    return spec.strip().lower()


class CardCatalog:
    """Every card and hero, by slug."""

    def __init__(self, cards: list[Card], heroes: list[Hero]) -> None:
        self.cards = {card.slug: card for card in cards}
        self.heroes = {hero.slug: hero for hero in heroes}
        self._order = [card.slug for card in cards]

    @classmethod
    def load(cls, data_dir: Path = DATA_DIR) -> "CardCatalog":
        cards = json.loads((data_dir / "cards.json").read_text(encoding="utf-8"))["cards"]
        heroes = json.loads((data_dir / "heroes.json").read_text(encoding="utf-8"))["heroes"]
        return cls(
            [Card(**{**card, "text": tuple(card["text"])}) for card in cards],
            [
                Hero(**{
                    **hero,
                    "bands": tuple(
                        HeroBand(**{**band, "text": tuple(band["text"])})
                        for band in hero["bands"]
                    ),
                })
                for hero in heroes
            ],
        )

    def by_slug(self, slug: str) -> Card | Hero:
        """A card or a hero; `KeyError` for neither."""
        if slug in self.cards:
            return self.cards[slug]
        return self.heroes[slug]

    def name(self, slug: str) -> str:
        """The one way back from a slug to a name."""
        return self.by_slug(slug).name

    def by_spec(self, spec: str) -> list[Card]:
        """A spec's twelve codex cards, in the data's order."""
        key = _spec_key(spec)
        return [
            card for card in self.cards.values()
            if card.kind == KIND_CARD and card.starting_zone == "codex"
            and card.spec and _spec_key(card.spec) == key
        ]

    def starting_deck(self, color: str) -> list[str]:
        """
        A colour's ten starting cards, as slugs in the data's order. The
        basic game deals the neutral ten to both sides.
        """
        key = _spec_key(color)
        return [
            card.slug for card in self.cards.values()
            if card.kind == KIND_CARD and card.starting_zone == "deck"
            and card.color and _spec_key(card.color) == key
        ]

    def codex_for(self, spec: str) -> list[str]:
        """A spec's codex: two copies of each of its twelve cards."""
        return [slug for card in self.by_spec(spec) for slug in (card.slug, card.slug)]

    def hero_for(self, spec: str) -> Hero:
        key = _spec_key(spec)
        for hero in self.heroes.values():
            if hero.spec and _spec_key(hero.spec) == key:
                return hero
        raise KeyError(spec)

    def token(self, slug: str) -> Card:
        card = self.cards[slug]
        if card.kind != KIND_TOKEN:
            raise KeyError(slug)
        return card

    def building(self, slug: str) -> Card:
        card = self.cards[slug]
        if card.kind != KIND_BUILDING:
            raise KeyError(slug)
        return card


@lru_cache(maxsize=1)
def catalog() -> CardCatalog:
    """The catalog the bot reads, loaded once."""
    return CardCatalog.load()
