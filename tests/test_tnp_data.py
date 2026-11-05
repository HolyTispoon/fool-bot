"""
TNP's data, step 1 of docs/tnp-bot.md: the imported unit sheet
(`tnp/data/humans.json`, `technology.json`), the hand-kept player board
(`human_board.json`) and map (`map.json`), checked against each other
and against docs/tnp-rules.md, and the catalog that reads them.
"""

import json
import tempfile
import unittest
from pathlib import Path

from tnp.catalog import DATA_DIR, CatalogError, Rating, UnitType, catalog, load

#: The half turn the map is its own mirror under (docs/tnp-rules.md, 2.1).
MIRROR = {
    "blue_base": "green_base",
    "10": "11", "14": "12", "13": "15", "8": "9", "2": "3", "5": "4", "7": "6",
    "1": "1",
}
MIRROR.update({other: one for one, other in list(MIRROR.items())})


class UnitDataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = catalog()

    def test_every_unit_a_facility_builds_is_in_the_unit_sheet(self) -> None:
        for facility in self.catalog.facilities.values():
            for unit in facility.units:
                self.assertIn(unit, self.catalog.units, facility.slug)

    def test_every_unit_has_the_facility_that_lists_it(self) -> None:
        for unit in self.catalog.units.values():
            self.assertIn(unit.facility, self.catalog.facilities, unit.slug)
            self.assertIn(unit.slug, self.catalog.facilities[unit.facility].units, unit.slug)

    def test_an_upgraded_unit_names_an_upgrade_of_its_own_facility(self) -> None:
        for unit in self.catalog.units.values():
            if unit.upgrade is None:
                continue
            upgrade = self.catalog.upgrades[unit.upgrade]
            self.assertEqual(upgrade.kind, "unit", unit.slug)
            self.assertEqual(upgrade.facility, unit.facility, unit.slug)
            self.assertIn(unit.slug, upgrade.units, unit.slug)
            self.assertIn(unit.upgrade, self.catalog.facilities[unit.facility].unit_upgrades)

    def test_every_rating_is_one_of_the_four(self) -> None:
        """TNP 4.1: Strong, Fair, Weak, Poor -- the sheet's Can't read as Poor."""
        raw = json.loads((DATA_DIR / "humans.json").read_text(encoding="utf-8"))
        for slug, unit in raw["units"].items():
            self.assertEqual(set(unit["attack"]), {"infantry", "armored", "air"}, slug)
            for value in unit["attack"].values():
                self.assertIn(value, {"strong", "fair", "weak", "poor"}, slug)
        for unit in self.catalog.units.values():
            self.assertEqual(set(unit.attack), set(UnitType))

    def test_the_supply_on_the_board_is_the_sheets_count(self) -> None:
        """Board v4's "max supply" against the unit sheet's Count."""
        board = self.catalog.board["max_supply"]
        self.assertEqual(set(board), set(self.catalog.units))
        for slug, unit in self.catalog.units.items():
            self.assertEqual(board[slug], unit.supply, slug)

    def test_the_infrastructure_upgrades_agree_with_the_board(self) -> None:
        """The sheet's upgrade rows: 1 material each, and the cap each
        names is the board's upgraded cap (TNP 2.4)."""
        for facility in self.catalog.facilities.values():
            upgrade = self.catalog.upgrades[facility.infrastructure_upgrade]
            self.assertEqual(upgrade.kind, "infrastructure")
            self.assertEqual(upgrade.facility, facility.slug)
            self.assertEqual((upgrade.cost.materials, upgrade.cost.gold), (1, 0))
            self.assertIn(f"cap to {facility.upgraded_production_cap}", upgrade.ability)

    def test_the_board_as_the_rules_give_it(self) -> None:
        """TNP 2.4 and 3: the caps, the build costs, which start built."""
        facilities = self.catalog.facilities
        self.assertEqual(
            {slug: (f.production_cap, f.upgraded_production_cap) for slug, f in facilities.items()},
            {"barracks": (4, 8), "factory": (3, 6), "airport": (2, 4), "base_defenses": (4, 8)},
        )
        self.assertEqual(
            {slug for slug, f in facilities.items() if f.built_at_start},
            {"barracks", "base_defenses"},
        )
        self.assertEqual(facilities["factory"].build_cost.materials, 2)
        self.assertEqual(facilities["airport"].build_cost.materials, 3)
        self.assertEqual(facilities["airport"].requires, "factory")
        self.assertEqual(facilities["barracks"].unit_upgrades_allowed, 1)
        self.assertEqual(facilities["barracks"].unit_upgrades_allowed_upgraded, 2)
        for slug in facilities["barracks"].unit_upgrades + facilities["factory"].unit_upgrades:
            self.assertEqual(self.catalog.upgrades[slug].cost.materials, 1)
        starting = self.catalog.board["starting"]
        self.assertEqual(starting["pool"], {"materials": 5, "gold": 0})
        self.assertEqual(starting["units"], {"worker": 3, "mercenary": 3})
        self.assertEqual(self.catalog.board["limits"]["tech_facilities"], 2)

    def test_the_conversion_rates(self) -> None:
        """TNP 5.9 and 6.2."""
        rates = self.catalog.board["conversion"]
        self.assertEqual(rates["normal"]["mineral"], {"materials": 2, "gold": 1})
        self.assertEqual(rates["normal"]["gem"], {"materials": 3, "gold": 2})
        self.assertEqual(rates["emergency"]["mineral"], {"materials": 1, "gold": None})
        self.assertEqual(rates["emergency"]["gem"], {"materials": 1, "gold": 1})

    def test_the_technology_rows_with_no_count_are_left_out(self) -> None:
        techs = self.catalog.techs
        for slug in ("shields", "positioning", "air_cover"):
            self.assertNotIn(slug, techs)
        for tech in techs.values():
            self.assertGreater(tech.count, 0, tech.slug)
            self.assertIn(tech.deck, {"blue_minerals", "orange_minerals", "gems"})
            self.assertIn(tech.type, {"tactic", "building_tech", "tech_facility"})

    def test_name_is_the_one_way_back(self) -> None:
        self.assertEqual(self.catalog.name("stealth_sniper"), "Stealth Sniper")
        self.assertEqual(self.catalog.name("factory"), "Factory")
        self.assertEqual(self.catalog.name("7"), "Territory 7")
        self.assertEqual(self.catalog.find_unit("Tank"), "tank")
        self.assertEqual(self.catalog.find_unit("the transformer"), "the_transformer")
        self.assertIsNone(self.catalog.find_unit("dragon"))


class RatingTests(unittest.TestCase):
    def test_the_d12_numbers(self) -> None:
        """TNP 4.1."""
        self.assertEqual(
            {rating: (rating.target, rating.shown) for rating in Rating},
            {
                Rating.STRONG: (3, "3+"),
                Rating.FAIR: (6, "6+"),
                Rating.WEAK: (12, "12"),
                Rating.POOR: (12, "X"),
            },
        )

    def test_poor_rolls_a_die_for_every_two_units_rounded_down(self) -> None:
        """TNP 4.3: a lone Poor unit rolls none, and three roll one."""
        self.assertEqual([Rating.POOR.dice(n) for n in (1, 2, 3, 4)], [0, 1, 1, 2])
        self.assertEqual(Rating.FAIR.dice(3), 3)


class MapDataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.areas = catalog().areas

    def test_seventeen_areas(self) -> None:
        self.assertEqual(
            set(self.areas),
            {"blue_base", "green_base", *(str(number) for number in range(1, 16))},
        )

    def test_the_adjacency_is_symmetric(self) -> None:
        for slug, area in self.areas.items():
            self.assertNotIn(slug, area.adjacent)
            for other in area.adjacent:
                self.assertIn(other, self.areas, slug)
                self.assertIn(slug, self.areas[other].adjacent, f"{slug} with {other}")

    def test_the_map_is_its_own_mirror_under_a_half_turn(self) -> None:
        """TNP 2.1: every border matches its partner's."""
        for slug, area in self.areas.items():
            mirrored = {MIRROR[other] for other in area.adjacent}
            self.assertEqual(mirrored, set(self.areas[MIRROR[slug]].adjacent), slug)

    def test_the_point_contacts_are_adjacent_and_3_and_12_are_not(self) -> None:
        """TNP 2.1: 8 with 10 and 9 with 11 meet at a point (the author, 2026-11-05)."""
        self.assertIn("10", self.areas["8"].adjacent)
        self.assertIn("11", self.areas["9"].adjacent)
        self.assertNotIn("12", self.areas["3"].adjacent)

    def test_the_resources_total_96_tokens(self) -> None:
        """TNP 1.3 and 2.1: 40 blue minerals, 40 orange, 16 gems."""
        totals = {"blue_minerals": 0, "orange_minerals": 0, "gems": 0}
        for area in self.areas.values():
            self.assertEqual(set(area.resources), set(totals), area.slug)
            for kind, count in area.resources.items():
                totals[kind] += count
        self.assertEqual(totals, {"blue_minerals": 40, "orange_minerals": 40, "gems": 16})
        self.assertEqual(sum(totals.values()), 96)

    def test_the_mirror_swaps_the_minerals(self) -> None:
        for slug, area in self.areas.items():
            partner = self.areas[MIRROR[slug]].resources
            self.assertEqual(area.resources["gems"], partner["gems"], slug)
            self.assertEqual(area.resources["blue_minerals"], partner["orange_minerals"], slug)

    def test_each_base_touches_one_blue_and_one_orange_territory(self) -> None:
        for base in ("blue_base", "green_base"):
            beside = [self.areas[slug].resources for slug in self.areas[base].adjacent]
            self.assertEqual(sum(1 for r in beside if r["blue_minerals"]), 1, base)
            self.assertEqual(sum(1 for r in beside if r["orange_minerals"]), 1, base)

    def test_every_area_has_a_traced_outline(self) -> None:
        for area in self.areas.values():
            self.assertGreaterEqual(len(area.outline), 4, area.slug)


class CatalogLoadTests(unittest.TestCase):
    def test_missing_data_is_a_catalog_error(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(CatalogError):
                load(Path(folder))

    def test_a_slug_in_two_tables_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)
            for name in ("humans.json", "technology.json", "human_board.json", "map.json"):
                (target / name).write_text((DATA_DIR / name).read_text(encoding="utf-8"), encoding="utf-8")
            technology = json.loads((target / "technology.json").read_text(encoding="utf-8"))
            technology["techs"]["tank"] = next(iter(technology["techs"].values()))
            (target / "technology.json").write_text(json.dumps(technology), encoding="utf-8")
            with self.assertRaises(CatalogError):
                load(target)


if __name__ == "__main__":
    unittest.main()
