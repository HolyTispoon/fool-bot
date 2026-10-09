"""
The Codex pictures render: a picture of the expected size for the
opening position in both layouts (the board is WebP), a hand and a
codex view (PNG) -- and nothing about
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

    def panel_height(self, rows: int) -> int:
        body = render.PATROL_HEIGHT + render.CELL_GAP + rows * render.CELL + (rows - 1) * render.CELL_GAP
        return 2 * render.PADDING + body + render.NAMEPLATE_GAP + render.NAMEPLATE_HEIGHT

    def test_the_panel_is_the_canvas_size(self) -> None:
        """Five columns in the basic game, seven in the standard one."""
        self.assertEqual((render.panel_width(5), render.panel_width(7)), (1649, 2227))
        panel = render.render_panel(self.match, 1, "a", self.engine.catalog)
        self.assertEqual(panel.size, (1649, self.panel_height(1)))

    def test_a_row_more_is_a_taller_panel(self) -> None:
        match = self.engine.new_match(("bashing", "finesse"), first=1)
        for _ in range(5):
            match.new_instance("older_brother", 1)
        panel = render.render_panel(match, 1, "a", self.engine.catalog)
        self.assertEqual(panel.height, self.panel_height(2))

    def test_the_opening_board_stacked(self) -> None:
        png = render.render_board(self.match, "stacked", {1: "a", 2: "b"}, self.engine.catalog)
        self.assertEqual((png[:4], png[8:12]), (b"RIFF", b"WEBP"))
        height = 2 * self.panel_height(1) + render.DIVIDER_HEIGHT
        self.assertEqual(size(png), (round(1649 * render.BOARD_SCALE),
                                     round(height * render.BOARD_SCALE)))

    def test_the_stacked_board_is_seen_from_the_active_players_side(self) -> None:
        """The active player's panel is the lower one -- its nameplate's
        rule gold -- whichever seat is active, and the other player's
        the upper."""
        panel = self.panel_height(1)
        upper_rule = (render.PADDING + 5, render.PADDING + render.NAMEPLATE_HEIGHT - 2)
        lower_rule = (render.PADDING + 5,
                      panel + render.DIVIDER_HEIGHT + panel - render.PADDING - render.NAMEPLATE_HEIGHT + 1)
        for active in (1, 2):
            match = self.engine.new_match(("bashing", "finesse"), first=1)
            match.active = active
            self.assertEqual(render.stacked_seats(match), (2 if active == 1 else 1, active))
            board = render.compose_board(match, "stacked", {1: "a", 2: "b"}, self.engine.catalog)
            self.assertEqual(board.getpixel(upper_rule)[:3], render.RULE)
            self.assertEqual(board.getpixel(lower_rule)[:3], render.TURN_GOLD)

    def test_the_far_panel_is_turned_round(self) -> None:
        """A turned panel's body is the upright one's rotated whole; its
        nameplate moves to the outer edge, above, the right way up."""
        cards, hp = self.engine.catalog, render.default_building_hp(self.engine.catalog)
        upright = render.render_panel(self.match, 2, "b", cards, hp)
        turned = render.render_panel(self.match, 2, "b", cards, hp, turned=True)
        edge = render.PADDING - render.OVERHANG
        body = upright.height - 2 * render.PADDING - render.NAMEPLATE_GAP - render.NAMEPLATE_HEIGHT
        span = body + 2 * render.OVERHANG
        near = upright.crop((edge, edge, upright.width - edge, edge + span))
        far_top = turned.height - edge - span
        far = turned.crop((edge, far_top, turned.width - edge, far_top + span))
        self.assertEqual(far.tobytes(), near.rotate(180).tobytes())

    def test_the_opening_board_side_by_side(self) -> None:
        png = render.render_board(self.match, "side_by_side", {1: "a", 2: "b"}, self.engine.catalog)
        self.assertEqual(size(png), (round((1649 * 2 + render.DIVIDER_WIDTH) * render.BOARD_SCALE),
                                     round(self.panel_height(1) * render.BOARD_SCALE)))

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
