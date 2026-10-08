"""
Sirlin's rulings, read from `codex/data/rulings.json`.

They are official rules of the game, collected by the Codex Card
Database with their authors and dates: where the rulebook's text and a
ruling differ, the ruling governs (docs/codex-bot.md, decision 7). The
`General` group rules on keywords; every other group on the card it
names.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

from codex.cards import DATA_DIR


@dataclass(frozen=True)
class Ruling:
    author: Optional[str]
    date: Optional[str]
    text: str


@dataclass(frozen=True)
class RulingEntry:
    """What is ruled on -- a card or a keyword -- and its rulings."""

    slug: str
    name: str
    ability_text: Optional[str]
    rulings: tuple[Ruling, ...]


def _entries(rows: list[dict]) -> dict[str, RulingEntry]:
    return {
        row["slug"]: RulingEntry(
            slug=row["slug"],
            name=row["name"],
            ability_text=row.get("ability_text"),
            rulings=tuple(Ruling(**ruling) for ruling in row["rulings"]),
        )
        for row in rows
    }


@lru_cache(maxsize=1)
def _load(path: Path = DATA_DIR / "rulings.json") -> tuple[dict, dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return _entries(data["general"]), _entries(data["cards"])


def keyword_slug(keyword: str) -> str:
    """A keyword as the `General` group keys it: "Anti-air" is
    `antiair`, "Frenzy X" is `frenzy_x`."""
    return re.sub(r"\W", "", re.sub(r"\s", "_", keyword.strip().lower()))


def keywords() -> list[RulingEntry]:
    """Every keyword the `General` group rules on."""
    return list(_load()[0].values())


def rulings_for(slug: str) -> tuple[Ruling, ...]:
    """A card's or hero's rulings, oldest first as the source lists
    them; none for a card nobody has ruled on."""
    entry = _load()[1].get(slug)
    return entry.rulings if entry else ()


def keyword_entry(keyword: str) -> Optional[RulingEntry]:
    """
    A keyword's entry, by its name or its slug; "frenzy" finds
    "Frenzy X", whose number varies by card.
    """
    general = _load()[0]
    slug = keyword_slug(keyword)
    return general.get(slug) or general.get(f"{slug}_x")


def keyword_rulings(keyword: str) -> tuple[Ruling, ...]:
    entry = keyword_entry(keyword)
    return entry.rulings if entry else ()
