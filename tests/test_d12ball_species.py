"""
The four species abilities: the import off the sheet's `spec_abilities`
tab, and the reference cards drawn from what it writes.

The suite cannot see a picture, so what the card test checks is what a
print gets wrong silently -- a face that is no longer poker size, and a
pairing that never made it onto a card. The import test covers the
formula-guard strip (shared with the player import) and the "every
species present" check.

See scripts/import_d12ball_species.py and d12ball/species_cards.py.
"""
import csv
import importlib.util
import io
import unittest
from pathlib import Path

from d12ball.cards import BLEED, CARD_HEIGHT, CARD_WIDTH
from d12ball.species_cards import (
    CARD_FACES,
    SPECIES_ORDER,
    load_species_abilities,
    render_species_card,
    render_species_card_set,
)


def load_import_script():
    path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "import_d12ball_species.py"
    )
    spec = importlib.util.spec_from_file_location(
        "import_d12ball_species", path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


importer = load_import_script()

SPEC_CSV = (
    "Spec,Name,Ability,Abbreviated\r\n"
    "Fire Demon,Volatile,Roll again on a 6 or 7.,Nat 6-7 reroll.\r\n"
    "Cyborg,Lithium powered,\"`+5 for 3 drain before a roll.\",3 drain +5.\r\n"
    "Telekinetic,Mind Pull,Pull a passing ball.,Pull a passing ball.\r\n"
    "Ooze,Slimey,Any Ooze on the ball can take it.,Any Ooze takes it.\r\n"
)


class SpeciesImportTests(unittest.TestCase):
    def _import(self, text: str) -> dict:
        reader = csv.DictReader(io.StringIO(text))
        reader.fieldnames = [n.strip() for n in reader.fieldnames]
        return importer.import_species(list(reader), data_version=1)

    def test_reads_all_four_species(self) -> None:
        out = self._import(SPEC_CSV)
        self.assertEqual(
            list(out["species"]),
            ["fire_demon", "cyborg", "telekinetic", "ooze"],
        )

    def test_strips_the_formula_guard_backtick(self) -> None:
        out = self._import(SPEC_CSV)
        self.assertEqual(
            out["species"]["cyborg"]["ability"],
            "+5 for 3 drain before a roll.",
        )

    def test_a_missing_species_is_rejected(self) -> None:
        rows = list(csv.DictReader(io.StringIO(SPEC_CSV)))[:3]
        with self.assertRaises(ValueError):
            importer.import_species(rows, data_version=1)

    def test_an_unknown_species_is_rejected(self) -> None:
        bad = SPEC_CSV.replace("Ooze,Slimey", "Sprite,Shimmer")
        with self.assertRaises(ValueError):
            self._import(bad)


class SpeciesDataTests(unittest.TestCase):
    def test_shipped_data_has_every_species(self) -> None:
        abilities = load_species_abilities()
        self.assertEqual(set(abilities), set(SPECIES_ORDER))
        for species, entry in abilities.items():
            self.assertTrue(entry["name"], species)
            self.assertTrue(entry["ability"], species)
            self.assertTrue(entry["ability_short"], species)

    def test_no_shipped_ability_carries_a_formula_escape(self) -> None:
        for species, entry in load_species_abilities().items():
            for field in ("ability", "ability_short"):
                self.assertFalse(
                    entry[field][:1] in ("`", "'")
                    and entry[field][1:2] in ("+", "-", "="),
                    f"{species}.{field} still escaped",
                )


class SpeciesCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.abilities = load_species_abilities()

    def test_every_pairing_appears_on_exactly_one_face(self) -> None:
        faces = [frozenset(pair) for card in CARD_FACES for pair in card]
        every_pair = {
            frozenset((a, b))
            for i, a in enumerate(SPECIES_ORDER)
            for b in SPECIES_ORDER[i + 1:]
        }
        self.assertEqual(len(faces), 6)
        self.assertEqual(len(set(faces)), 6)
        self.assertEqual(set(faces), every_pair)

    def test_a_face_is_poker_size(self) -> None:
        card = render_species_card(self.abilities, ("fire_demon", "cyborg"))
        self.assertEqual(card.size, (CARD_WIDTH, CARD_HEIGHT))

    def test_bleed_adds_a_trim_margin(self) -> None:
        card = render_species_card(
            self.abilities, ("fire_demon", "cyborg"), bleed=True
        )
        self.assertEqual(
            card.size, (CARD_WIDTH + BLEED * 2, CARD_HEIGHT + BLEED * 2)
        )

    def test_the_set_is_three_double_sided_cards(self) -> None:
        faces = render_species_card_set(self.abilities)
        self.assertEqual(len(faces), 6)
        self.assertEqual(
            [name for name, _ in faces],
            ["1-front", "1-back", "2-front", "2-back", "3-front", "3-back"],
        )


if __name__ == "__main__":
    unittest.main()
