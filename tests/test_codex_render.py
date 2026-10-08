"""
The Codex pictures render: a PNG of the expected size for the opening
position in both layouts, a hand and a codex view -- and nothing about
how they look, which is for the eye (`scripts/render_codex_sample.py`;
docs/design/codex.md, "The board on Discord").
"""

import io
import unittest

from PIL import Image

from codex import render
from codex.engine import RulesEngine


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
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
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
                self.assertEqual(picture.getpixel(upper_strip), render.STRIP_FILL)
                self.assertEqual(picture.getpixel(lower_strip), render.ACTIVE_FILL)

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
        self.assertEqual(size(png)[0], 5 * (render.HAND_CARD[0] + 16) + 16)

    def test_a_codex_view(self) -> None:
        rows = self.engine.codex_remaining(self.match, 1)
        png = render.render_codex([slug for slug, _ in rows], [count for _, count in rows],
                                  self.engine.catalog)
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

    def test_nothing_is_playable_off_the_main_phase(self) -> None:
        engine = RulesEngine(seed=7)
        match = engine.new_match(("bashing", "finesse"), first=1)
        self.assertFalse(any(row.allowed for row in engine.hand_rows(match, 2)))


if __name__ == "__main__":
    unittest.main()
