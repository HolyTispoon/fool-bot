"""
The four species abilities: the import off the sheet's `spec_abilities`
tab, the reference cards drawn from what it writes, and the icons.

The suite cannot see a picture, so what the card test checks is what a
print gets wrong silently -- a face that is no longer poker size, and a
pairing that never made it onto a card. The import test covers the
formula-guard strip (shared with the player import) and the "every
species present" check.

The icon tests are the same shape and for the same reason. An icon is
loaded through a swallowed OSError so a render can go on without it,
and it is drawn in three different inks on three different grounds --
so a species with no art, or a tint that quietly did nothing, comes out
as a card that simply has no icon on it. That is invisible to a test
that only asks whether the card rendered.

See scripts/import_d12ball_species.py, scripts/render_species_icons.py
and d12ball/species_cards.py.
"""
import csv
import importlib.util
import io
import os
import unittest
from pathlib import Path

from PIL import Image

from d12ball.cards import BLEED, CARD_HEIGHT, CARD_WIDTH
from d12ball.render import (
    SPECIES_ICON_DIR,
    TEAM_COLORS,
    high_contrast_ink,
    load_species_icon,
    species_icon,
)
from d12ball.species_cards import (
    CARD_FACES,
    SPECIES_ORDER,
    SPECIES_TEAM,
    load_species_abilities,
    render_species_card,
    render_species_card_set,
)


def load_script(name: str):
    path = Path(__file__).resolve().parents[1] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rgb(color: str) -> tuple[int, int, int]:
    value = color.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def load_import_script():
    return load_script("import_d12ball_species")


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


class D12BallSpeciesIconTests(unittest.TestCase):
    """
    The four silhouettes, and the tint every card puts them through.
    """

    def test_every_species_has_an_icon(self) -> None:
        for species in SPECIES_ORDER:
            with self.subTest(species=species):
                self.assertIsNotNone(
                    load_species_icon(species),
                    f"No icon for {species} -- run "
                    "scripts/render_species_icons.py --in-place",
                )

    def test_an_unknown_species_draws_nothing_rather_than_raising(
        self,
    ) -> None:
        # A players.json written before the species column loads with
        # an empty species; every caller here is drawing something
        # optional, so the answer is None and the card goes on without
        # it. See "Player species" in docs/design/teams-and-players.md.
        self.assertIsNone(load_species_icon(""))
        self.assertIsNone(species_icon("", "#ffffff", 32))

    def test_the_tint_paints_the_ink_and_keeps_the_shape(self) -> None:
        """
        The art is one flat ink on transparency precisely so that one
        file can sit on a team-coloured band, on a species-coloured
        pill and on the bot's white card. A tint that returned the
        source unchanged would leave black icons on a black-ish band
        and nothing would fail.
        """
        for species in SPECIES_ORDER:
            for color in ("#ffffff", "#000000"):
                with self.subTest(species=species, color=color):
                    icon = species_icon(species, color, 64)
                    self.assertEqual(icon.size, (64, 64))
                    opaque = [
                        icon.getpixel((x, y))
                        for x in range(64)
                        for y in range(64)
                        if icon.getpixel((x, y))[3] > 200
                    ]
                    self.assertTrue(opaque, "the icon drew nothing")
                    expected = (
                        (255, 255, 255) if color == "#ffffff" else (0, 0, 0)
                    )
                    self.assertEqual(
                        {pixel[:3] for pixel in opaque}, {expected}
                    )

    def test_the_script_draws_every_species(self) -> None:
        icons = load_script("render_species_icons")
        self.assertEqual(set(icons.ICONS), set(SPECIES_ORDER))

    def test_every_species_icon_has_a_coloured_copy(self) -> None:
        """
        The coloured copy is not read by the bot -- it is there for the
        places a file has to arrive already coloured, an emoji upload
        or a document. Nothing would notice one missing, which is why
        the check is here.

        Compared against the directory's own listing rather than asked
        with `Path.exists`, for the reason the bundled-art check is:
        one developer's filesystem is case-insensitive and the other's
        is not.
        """
        suffix = load_script("render_species_icons").COLOR_SUFFIX
        listing = os.listdir(SPECIES_ICON_DIR)
        for species in SPECIES_ORDER:
            with self.subTest(species=species):
                self.assertIn(f"{species}{suffix}.png", listing)

    def test_the_coloured_copy_cannot_drift_from_the_silhouette(
        self,
    ) -> None:
        """
        Both files are written from one shape in one pass, so the way
        they come apart is somebody regenerating the art and shipping
        half of it -- a coloured icon that is still last month's shape,
        beside an ink one that is not. The alpha channel is the shape,
        so comparing it is the whole check.
        """
        suffix = load_script("render_species_icons").COLOR_SUFFIX
        for species in SPECIES_ORDER:
            with self.subTest(species=species):
                ink = Image.open(
                    SPECIES_ICON_DIR / f"{species}.png"
                ).convert("RGBA")
                colored = Image.open(
                    SPECIES_ICON_DIR / f"{species}{suffix}.png"
                ).convert("RGBA")
                self.assertEqual(ink.size, colored.size)
                self.assertEqual(
                    ink.getchannel("A").tobytes(),
                    colored.getchannel("A").tobytes(),
                    "the coloured copy is a different shape -- rerun "
                    "scripts/render_species_icons.py --in-place",
                )

    def test_the_coloured_copy_is_the_species_own_colour(self) -> None:
        """
        The paired colour team's hex out of `TEAM_COLORS`, so there is
        still exactly one hex per colour in the codebase and a palette
        change reaches these by re-running the script -- see "Team
        colors" in docs/design/teams-and-players.md.
        """
        suffix = load_script("render_species_icons").COLOR_SUFFIX
        for species in SPECIES_ORDER:
            with self.subTest(species=species):
                icon = Image.open(
                    SPECIES_ICON_DIR / f"{species}{suffix}.png"
                ).convert("RGBA")
                opaque = {
                    pixel[:3]
                    for _count, pixel in icon.getcolors(maxcolors=1 << 24)
                    if pixel[3] > 250
                }
                self.assertEqual(
                    opaque, {rgb(TEAM_COLORS[SPECIES_TEAM[species]])}
                )

    def test_a_band_ink_is_readable_against_every_species_colour(
        self,
    ) -> None:
        # The icon is drawn in the band's ink rather than the species'
        # colour wherever it sits on a filled band -- which is what
        # keeps the Oozes' green one legible. Asserting the pairing
        # here is what stops somebody "simplifying" it to white.
        self.assertEqual(
            high_contrast_ink(TEAM_COLORS[SPECIES_TEAM["ooze"]]), "#000000"
        )
        for species in ("fire_demon", "cyborg", "telekinetic"):
            with self.subTest(species=species):
                self.assertEqual(
                    high_contrast_ink(TEAM_COLORS[SPECIES_TEAM[species]]),
                    "#ffffff",
                )


if __name__ == "__main__":
    unittest.main()
