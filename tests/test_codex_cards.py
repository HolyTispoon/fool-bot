"""
The Codex card data: what `scripts/import_codex_cards.py` wrote, read
through `codex.cards`, `codex.rulings` and `codex.formatting`.

The numbers below are the basic set's, as docs/codex-bot.md's card
table gives them -- the scope of the basic game. A re-import that moves
one is a change to the game and fails here first.
"""

import json
import re
import unittest

from codex import tokens
from codex.cards import DATA_DIR, IMAGE_DIR, KIND_BUILDING, KIND_TOKEN, catalog
from codex.formatting import card_label, plain_text
from codex.rulings import keyword_rulings, keywords, rulings_for

#: slug: (cost, tech level, ATK, HP) -- `None` where a spell has none.
BASIC_SET = {
    # The ten starters.
    "timely_messenger": (1, 0, 1, 1),
    "tenderfoot": (1, 0, 1, 2),
    "older_brother": (2, 0, 2, 2),
    "brick_thief": (2, 0, 2, 1),
    "helpful_turtle": (2, 0, 1, 2),
    "granfalloon_flagbearer": (3, 0, 2, 2),
    "fruit_ninja": (3, 0, 2, 2),
    "spark": (1, None, None, None),
    "bloom": (2, None, None, None),
    "wither": (2, None, None, None),
    # Bashing.
    "wrecking_ball": (0, None, None, None),
    "the_boot": (3, None, None, None),
    "intimidate": (1, None, None, None),
    "final_smash": (6, None, None, None),
    "iron_man": (3, 1, 3, 4),
    "revolver_ocelot": (2, 1, 3, 3),
    "hired_stomper": (4, 2, 4, 3),
    "regularsized_rhinoceros": (4, 2, 5, 6),
    "sneaky_pig": (3, 2, 3, 3),
    "eggship": (4, 2, 4, 3),
    "harvest_reaper": (5, 2, 6, 5),
    "trojan_duck": (7, 3, 8, 9),
    # Finesse.
    "harmony": (2, None, None, None),
    "discord": (2, None, None, None),
    "two_step": (2, None, None, None),
    "appel_stomp": (1, None, None, None),
    "nimble_fencer": (2, 1, 2, 3),
    "starcrossed_starlet": (2, 1, 3, 2),
    "grounded_guide": (5, 2, 4, 4),
    "maestro": (3, 2, 3, 5),
    "backstabber": (3, 2, 3, 3),
    "cloud_sprite": (2, 2, 3, 2),
    "leaping_lizard": (1, 2, 3, 5),
    "blademaster": (6, 3, 7, 5),
}

#: slug: (spec, cost, ((min level, ATK, HP), ...))
BASIC_HEROES = {
    "troq_bashar": ("Bashing", 2, ((1, 2, 3), (5, 3, 4), (8, 4, 5))),
    "river_montoya": ("Finesse", 2, ((1, 2, 3), (3, 2, 4), (5, 3, 4))),
}

#: The tokens and add-ons the basic game puts on the table.
BASIC_TOKENS = {"dancer": (0, 1), "angry_dancer": (2, 1)}
BASIC_ADDONS = {"tower": (3, 4), "surplus": (5, 4)}

GLYPH = re.compile("[⤵◎→⓪①-⑳]")


def every_string(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from every_string(item)
    elif isinstance(value, list):
        for item in value:
            yield from every_string(item)


class CodexCardDataTests(unittest.TestCase):
    def setUp(self):
        self.catalog = catalog()

    def test_the_data_loads_with_its_header(self):
        for name in ("cards.json", "heroes.json", "rulings.json"):
            data = json.loads((DATA_DIR / name).read_text(encoding="utf-8"))
            self.assertIn("never edited by hand", data["note"])
            self.assertIn("codex-cards-gatsby", data["source"])
        self.assertEqual(len(self.catalog.heroes), 20)

    def test_every_slug_is_unique(self):
        cards = json.loads((DATA_DIR / "cards.json").read_text(encoding="utf-8"))["cards"]
        heroes = json.loads((DATA_DIR / "heroes.json").read_text(encoding="utf-8"))["heroes"]
        slugs = [record["slug"] for record in cards + heroes]
        self.assertEqual(len(slugs), len(set(slugs)))
        self.assertEqual(slugs[: len(cards)], sorted(slugs[: len(cards)]))

    def test_the_basic_set_has_the_worksheets_numbers(self):
        for slug, (cost, tech_level, atk, hp) in BASIC_SET.items():
            with self.subTest(slug):
                card = self.catalog.by_slug(slug)
                self.assertEqual(card.cost, cost)
                if atk is not None:
                    self.assertEqual((card.tech_level, card.atk, card.hp), (tech_level, atk, hp))
                else:
                    self.assertTrue(card.is_spell)

    def test_the_basic_heroes_have_the_worksheets_bands(self):
        for slug, (spec, cost, bands) in BASIC_HEROES.items():
            with self.subTest(slug):
                hero = self.catalog.hero_for(spec)
                self.assertEqual(hero.slug, slug)
                self.assertEqual(hero.cost, cost)
                self.assertEqual(
                    tuple((band.min_level, band.atk, band.hp) for band in hero.bands),
                    bands,
                )

    def test_the_tokens_and_addons(self):
        for slug, (atk, hp) in BASIC_TOKENS.items():
            token = self.catalog.token(slug)
            self.assertEqual((token.kind, token.atk, token.hp), (KIND_TOKEN, atk, hp))
        for slug, (cost, hp) in BASIC_ADDONS.items():
            building = self.catalog.building(slug)
            self.assertEqual((building.kind, building.cost, building.hp), (KIND_BUILDING, cost, hp))

    def test_the_starting_deck_and_the_codices(self):
        deck = self.catalog.starting_deck("neutral")
        self.assertEqual(len(deck), 10)
        self.assertEqual(set(deck), {slug for slug, row in BASIC_SET.items()} & set(deck))
        self.assertEqual(len(self.catalog.codex_for("bashing")), 24)
        self.assertEqual(len(self.catalog.codex_for("Finesse")), 24)
        self.assertEqual(len(set(self.catalog.codex_for("bashing"))), 12)

    def test_every_ruling_names_a_card_or_a_keyword(self):
        data = json.loads((DATA_DIR / "rulings.json").read_text(encoding="utf-8"))
        for entry in data["cards"]:
            with self.subTest(entry["name"]):
                self.catalog.by_slug(entry["slug"])
        self.assertIn("overpower", {entry.slug for entry in keywords()})

    def test_rulings_read_by_card_and_by_keyword(self):
        self.assertEqual(len(rulings_for("trojan_duck")), 2)
        self.assertTrue(all(ruling.author and ruling.date for ruling in rulings_for("trojan_duck")))
        self.assertTrue(keyword_rulings("overpower"))
        self.assertEqual(keyword_rulings("Frenzy"), keyword_rulings("frenzy_x"))
        self.assertEqual(rulings_for("tenderfoot"), ())

    def test_no_glyph_is_left_in_any_text(self):
        for name in ("cards.json", "heroes.json", "rulings.json"):
            data = json.loads((DATA_DIR / name).read_text(encoding="utf-8"))
            for text in every_string(data):
                self.assertIsNone(GLYPH.search(text), f"{name}: {text!r}")

    def test_the_glyphs_became_tokens(self):
        river = self.catalog.hero_for("finesse")
        line = river.bands[1].text[0]
        self.assertEqual(tokens.find(line)[:1], [("exhaust", ())])
        self.assertNotIn("{", plain_text(line))

    def test_card_label(self):
        self.assertEqual(card_label(self.catalog.by_slug("trojan_duck")), "Trojan Duck (7) 8/9")
        self.assertEqual(card_label(self.catalog.by_slug("spark")), "Spark (1)")
        self.assertEqual(self.catalog.name("regularsized_rhinoceros"), "Regular-sized Rhinoceros")


BOARD_DIR = IMAGE_DIR / "board"

#: The numbered chits, by folder: what a board counts with.
NUMBERED_CHITS = {
    "damage": [str(n) for n in range(1, 10)],
    "levels": [*(str(n) for n in range(2, 9)), "max"],
    "time_runes": [str(n) for n in range(1, 7)],
}


def pngs(folder: str) -> set[str]:
    return {path.stem for path in (BOARD_DIR / folder).glob("*.png")}


class CodexCardArtTests(unittest.TestCase):
    """
    The art scripts/import_codex_cards.py brings in, in the tree since the
    author imported it on 2026-10-08: the database's picture of every card
    and hero, and the Screentop module's playmat and the pieces cut from
    its sheets (docs/design/codex.md, "The cards are data").
    """

    def setUp(self):
        self.catalog = catalog()

    def test_every_card_and_hero_the_host_pictures_is_there_at_330_by_450(self):
        from PIL import Image

        pictured = [
            card for card in [*self.catalog.cards.values(), *self.catalog.heroes.values()]
            if card.sirlins_filename
        ]
        self.assertEqual(len(pictured), 330)
        missing = [card.slug for card in pictured if not card.picture.is_file()]
        self.assertEqual(missing, [], "run scripts/import_codex_cards.py and commit codex/images/cards/")
        for card in pictured:
            with Image.open(card.picture) as picture:
                self.assertEqual(picture.size, (330, 450), card.slug)

    def test_every_token_and_building_has_its_face_and_nothing_else_is_there(self):
        for kind, folder in ((KIND_TOKEN, "tokens"), (KIND_BUILDING, "buildings")):
            slugs = {card.slug for card in self.catalog.cards.values() if card.kind == kind}
            with self.subTest(folder):
                self.assertEqual(pngs(folder), slugs)

    def test_every_spec_has_its_card(self):
        specs = {
            re.sub(r"\W", "", card.spec.lower())
            for card in self.catalog.cards.values() if card.spec
        }
        self.assertEqual(len(specs), 20)
        self.assertEqual(pngs("specs"), specs)

    def test_the_playmat_the_backs_and_the_patrol_slots(self):
        self.assertTrue((BOARD_DIR / "playmat.png").is_file())
        self.assertEqual(pngs("backs"), {"card", "hero", "token"})
        self.assertEqual(
            pngs("patrol"), {"squad_leader", "elite", "scavenger", "technician", "lookout"},
        )

    def test_the_numbered_chits(self):
        for folder, names in NUMBERED_CHITS.items():
            with self.subTest(folder):
                self.assertEqual(pngs(folder), set(names))

    def test_a_tile_reads_upright(self):
        """The sheet stores the base and the tech buildings on their side;
        the import turns them the way the playmat prints them."""
        from PIL import Image

        for slug in ("base", "tech_i_building", "tech_ii_building", "tech_iii_building"):
            with self.subTest(slug):
                with Image.open(self.catalog.building(slug).picture) as tile:
                    self.assertGreater(tile.width, tile.height)


class CodexEmojiTests(unittest.TestCase):
    def test_the_medallion_is_there(self):
        self.assertTrue((IMAGE_DIR / "emoji" / "codex.png").is_file())


if __name__ == "__main__":
    unittest.main()
