"""
`RulesEngine`: the fixed catalog the rules read, and **`rng`, the one
`random.Random` every draw the game makes comes from** -- every d12 is
`engine.d12()`, and nothing under `tnp/` reads the module `random`. A
test seeds `engine.rng`, or patches `engine.rng.randint` with the rolls
it wants (docs/tnp-bot.md, the preamble's dice rule).

The battle's readings are `tnp.battle`'s, over the state it holds; this
is the catalog and the dice they stand on. Step 4 grows it the turn's.
"""

from __future__ import annotations

import random
from typing import Optional

from tnp.catalog import Catalog, Rating, Unit, UnitType, catalog as committed_catalog


class RulesEngine:
    def __init__(self, catalog: Optional[Catalog] = None, rng: Optional[random.Random] = None) -> None:
        self.catalog = catalog if catalog is not None else committed_catalog()
        self.rng = rng if rng is not None else random.Random()

    def d12(self) -> int:
        """One die (TNP 4.1)."""
        return self.rng.randint(1, 12)

    def unit(self, slug: str) -> Unit:
        return self.catalog.units[slug]

    def has_trait(self, slug: str, trait: str) -> bool:
        return trait in self.catalog.units[slug].traits

    def rating(self, slug: str, against: UnitType) -> Rating:
        return self.catalog.units[slug].rating(against)

    @staticmethod
    def hits(rolled: int, modifier: int, rating: Rating) -> bool:
        """
        Whether one die hits (TNP 4.1, 4.2): the number rolled plus every
        modifier, with no cap, against the rating's number -- and a
        rolled 12 always hits and a rolled 1 always misses.
        """
        if rolled == 12:
            return True
        if rolled == 1:
            return False
        return rolled + modifier >= rating.target
