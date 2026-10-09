"""
The Codex pictures render: a picture of the expected size for the
opening position in both layouts, a hand and a codex view, each WebP
(`render.WEBP_QUALITY`) -- and nothing about how they look, which is
for the eye (`scripts/render_codex_sample.py`; docs/design/codex.md,
"The board on Discord").
"""

import io
import unittest

from PIL import Image

from codex import render
from codex.engine import RulesEngine


def near(pixel: tuple, fill: tuple) -> bool:
    """Within the board's lossy encoding of a flat fill."""
    return all(abs(a - b) <= 4 for a, b in zip(pixel, fill))


def size(png: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(png)) as picture:
        return picture.size


class RenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = RulesEngine(seed=7)
        cls.match = cls.engine.new_match(("bashing", "finesse"), first=1)

    def test_the_opening_board_stacked(self) -> None:
        side = (render.MAT_SIZE[0], render.MAT_SIZE[1] + render.STRIP_HEIGHT)
        png = render.render_board(self.match, "stacked", {1: "a", 2: "b"}, self.engine.catalog)
        self.assertEqual((png[:4], png[8:12]), (b"RIFF", b"WEBP"))
        self.assertEqual(size(png), (round(side[0] * render.BOARD_SCALE),
                                     round((side[1] * 2 + 16) * render.BOARD_SCALE)))

    def test_the_stacked_board_is_seen_from_the_active_players_side(self) -> None:
        """The active player's mat is the lower one -- its strip lit --
        whichever seat is active, and the other player's the upper."""
        side_height = render.MAT_SIZE[1] + render.STRIP_HEIGHT
        upper_strip = (10, 10)
        lower_strip = (10, round((side_height + render.GAP) * render.BOARD_SCALE) + 10)
        for active in (1, 2):
            match = self.engine.new_match(("bashing", "finesse"), first=1)
            match.active = active
            self.assertEqual(render.stacked_seats(match), (2 if active == 1 else 1, active))
            png = render.render_board(match, "stacked", {1: "a", 2: "b"}, self.engine.catalog)
            with Image.open(io.BytesIO(png)) as picture:
                self.assertTrue(near(picture.getpixel(upper_strip), render.STRIP_FILL))
                self.assertTrue(near(picture.getpixel(lower_strip), render.ACTIVE_FILL))

    def test_the_far_mat_is_turned_round(self) -> None:
        """A turned side is the upright one's mat rotated under the same
        strip: the mat's corners swap, and the strip's corner stays."""
        cards, hp = self.engine.catalog, render.default_building_hp(self.engine.catalog)
        upright = render.render_side(self.match, 2, "b", cards, hp)
        turned = render.render_side(self.match, 2, "b", cards, hp, turned=True)
        top = render.STRIP_HEIGHT
        self.assertEqual(turned.getpixel((0, top)),
                         upright.getpixel((upright.width - 1, upright.height - 1)))
        self.assertEqual(turned.getpixel((0, 0)), upright.getpixel((0, 0)))

    def test_the_opening_board_side_by_side(self) -> None:
        side = (render.MAT_SIZE[0], render.MAT_SIZE[1] + render.STRIP_HEIGHT)
        png = render.render_board(self.match, "side_by_side", {1: "a", 2: "b"}, self.engine.catalog)
        self.assertEqual(size(png), (round((side[0] * 2 + 16) * render.BOARD_SCALE),
                                     round(side[1] * render.BOARD_SCALE)))

    def test_a_hand(self) -> None:
        rows = self.engine.hand_rows(self.match, 1)
        png = render.render_hand([row.slug for row in rows], [row.allowed for row in rows],
                                 [row.cost for row in rows], self.engine.catalog)
        self.assertEqual((png[:4], png[8:12]), (b"RIFF", b"WEBP"))
        self.assertEqual(size(png)[0], 5 * (render.HAND_CARD[0] + 16) + 16)

    def test_a_codex_view(self) -> None:
        rows = self.engine.codex_remaining(self.match, 1)
        png = render.render_codex([slug for slug, _ in rows], [count for _, count in rows],
                                  self.engine.catalog)
        self.assertEqual((png[:4], png[8:12]), (b"RIFF", b"WEBP"))
        self.assertEqual(size(png), (6 * (render.CODEX_CARD[0] + 14) + 14,
                                     2 * (render.CODEX_CARD[1] + 14) + 14))

    def test_the_standard_games_codex_stays_under_the_upload_limit(self) -> None:
        """Thirty-six cards, the standard game's three specs."""
        slugs = [slug for spec in ("bashing", "finesse", "anarchy")
                 for slug in dict.fromkeys(self.engine.catalog.codex_for(spec))]
        png = render.render_codex(slugs, [2] * len(slugs), self.engine.catalog)
        self.assertLess(len(png), 10 * 1024 * 1024)


class CodexViewTests(unittest.TestCase):
    """The engine's answer the Codex menu shows."""

    def test_each_view_narrows_the_codex(self) -> None:
        engine = RulesEngine(seed=7)
        match = engine.new_match(("bashing", "finesse"), first=1)
        everything = engine.codex_remaining(match, 1, "everything")
        self.assertEqual(len(everything), 12)
        self.assertEqual({slug for slug, _ in engine.codex_remaining(match, 1, "tech3")},
                         {"trojan_duck"})
        self.assertEqual(len(engine.codex_remaining(match, 1, "spells")), 4)
        self.assertEqual(sum(len(engine.codex_remaining(match, 1, view))
                             for view in ("tech1", "tech2", "tech3", "spells")), 12)

    def test_a_tech_level_is_every_card_printed_with_it(self) -> None:
        """A Tech II building or upgrade is a Tech II card as much as a
        unit is: the four views together are every spec's whole codex,
        and a card is in exactly one of them."""
        engine = RulesEngine(seed=7)
        catalog = engine.catalog
        for spec in sorted({card.spec for card in catalog.cards.values() if card.spec}):
            rows = tuple((slug, 2) for slug in dict.fromkeys(catalog.codex_for(spec)))
            with self.subTest(spec=spec):
                self.assertEqual(len(rows), 12)
                parts = [engine.codex_view_rows(rows, view)
                         for view in ("tech1", "tech2", "tech3", "spells")]
                self.assertEqual(sorted(slug for part in parts for slug, _ in part),
                                 sorted(slug for slug, _ in rows))
                self.assertEqual(engine.codex_view_rows(rows, "everything"), rows)
        anarchy = tuple((slug, 2) for slug in dict.fromkeys(catalog.codex_for("anarchy")))
        tech2 = {slug for slug, _ in engine.codex_view_rows(anarchy, "tech2")}
        self.assertTrue(any(catalog.cards[slug].kind == "card" and not catalog.cards[slug].is_unit
                            for slug in tech2), "Anarchy's Tech II building is a Tech II card")

    def test_a_spec_view_is_its_own_twelve(self) -> None:
        """The standard game's menu: one view per spec of the deck. The
        basic game's deck is one spec, so it offers none."""
        from codex.engine import CODEX_VIEWS, spec_view
        from codex.formatting import codex_view_name
        engine = RulesEngine(seed=7)
        match = engine.new_match(("bashing", "finesse"), first=1)
        self.assertEqual(engine.codex_views(match.player(1)), CODEX_VIEWS)
        catalog = engine.catalog
        rows = tuple((slug, 2) for spec in ("bashing", "anarchy")
                     for slug in dict.fromkeys(catalog.codex_for(spec)))
        anarchy = engine.codex_view_rows(rows, spec_view("Anarchy"))
        self.assertEqual(len(anarchy), 12)
        self.assertTrue(all(catalog.cards[slug].spec == "Anarchy" for slug, _ in anarchy))
        self.assertEqual(codex_view_name(spec_view("Anarchy")), "Anarchy")
        self.assertEqual([codex_view_name(view) for view in CODEX_VIEWS],
                         ["Everything", "Tech I", "Tech II", "Tech III", "Spells"])
        with self.assertRaises(ValueError):
            engine.codex_remaining(match, 1, spec_view("bashing"))
        with self.assertRaises(ValueError):
            engine.codex_view_rows(rows, "tech4")

    def test_nothing_is_playable_off_the_main_phase(self) -> None:
        engine = RulesEngine(seed=7)
        match = engine.new_match(("bashing", "finesse"), first=1)
        self.assertFalse(any(row.allowed for row in engine.hand_rows(match, 2)))


if __name__ == "__main__":
    unittest.main()
