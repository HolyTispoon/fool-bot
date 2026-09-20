"""
The components cut for screentop.gg.

The suite cannot see a picture, so what it checks is what an upload
gets wrong silently: a sheet whose grid does not divide into its
cards, a back sheet that pairs the wrong player with a front (the
print kit's duplex reversal, which is exactly wrong here), an image
over the cap the tabletop refuses, a manifest that lists a file the
export did not write, and the coin the bot flips being a different
coin from the one on the table.

See d12ball/screentop.py, and "The screentop.gg module" in
docs/design/screentop.md.
"""
import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from PIL import Image

from cogs.d12ball_helpers import COIN_EMOJI_NAMES
from d12ball import screentop
from d12ball.cards import CARD_HEIGHT, CARD_WIDTH
from d12ball.components import (
    MANEUVER_TIERS,
    PlayerRole,
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.game import Team
from d12ball.render import MEEPLE_SIZE, TEAM_COLORS
from d12ball.screentop import (
    D12_SIDES,
    MAX_SIDE,
    MEEPLE_TOKEN_SIZE,
    SheetLayout,
    build_assets,
    condition_token_assets,
    die_assets,
    fit_cell,
    fit_image,
    manifest,
    render_ball_die_face,
    render_die_face,
    render_meeple_token,
    tabletop_sheet,
    write_kit,
)


def blank(width: int = 30, height: int = 42) -> Image.Image:
    return Image.new("RGB", (width, height), "#ffffff")


def by_role(catalog, team: Team, role: PlayerRole):
    """A player named by role, never by name -- see tests/roster.py."""
    return next(
        player for player in catalog.teams[team].players if player.role == role
    )


class TabletopSheetTests(unittest.TestCase):
    def test_a_sheet_is_the_grid_exactly_with_no_margin(self) -> None:
        cells = [(f"c{i}", blank()) for i in range(6)]
        sheet, layout, fitted = tabletop_sheet(cells, columns=3)
        self.assertEqual(layout, SheetLayout(3, 2, 6, (30, 42), tuple(f"c{i}" for i in range(6))))
        self.assertEqual(sheet.size, (90, 84))
        self.assertEqual([image.size for _, image in fitted], [(30, 42)] * 6)

    def test_a_short_last_row_is_padded_and_the_count_says_so(self) -> None:
        cells = [(f"c{i}", blank()) for i in range(4)]
        sheet, layout, _ = tabletop_sheet(cells, columns=3)
        self.assertEqual((layout.rows, layout.count), (2, 4))
        self.assertEqual(sheet.size, (90, 84))
        # The padding is empty, not a copy of anything.
        self.assertEqual(sheet.getpixel((89, 83)), (0, 0, 0, 0))

    def test_cell_n_is_card_n_reading_left_to_right(self) -> None:
        colours = ["#ff0000", "#00ff00", "#0000ff", "#ffff00"]
        cells = [
            (f"c{i}", Image.new("RGB", (10, 10), colour))
            for i, colour in enumerate(colours)
        ]
        sheet, _, _ = tabletop_sheet(cells, columns=2)
        self.assertEqual(sheet.getpixel((5, 5))[:3], (255, 0, 0))
        self.assertEqual(sheet.getpixel((15, 5))[:3], (0, 255, 0))
        self.assertEqual(sheet.getpixel((5, 15))[:3], (0, 0, 255))
        self.assertEqual(sheet.getpixel((15, 15))[:3], (255, 255, 0))

    def test_mixed_card_sizes_are_refused_not_stretched(self) -> None:
        with self.assertRaises(ValueError):
            tabletop_sheet([("a", blank()), ("b", blank(31, 42))], columns=2)
        with self.assertRaises(ValueError):
            tabletop_sheet([], columns=2)

    def test_the_cap_scales_the_cell_so_the_grid_still_divides(self) -> None:
        self.assertEqual(fit_cell((750, 1050), 3, 3, MAX_SIDE), (750, 1050))
        cell = fit_cell((750, 1050), 3, 3, 1000)
        self.assertEqual(cell, (238, 333))
        self.assertLessEqual(3 * cell[0], 1000)
        self.assertLessEqual(3 * cell[1], 1000)
        cells = [(f"c{i}", blank(750, 1050)) for i in range(9)]
        sheet, layout, fitted = tabletop_sheet(cells, columns=3, max_side=1000)
        self.assertEqual(sheet.size, (3 * 238, 3 * 333))
        self.assertEqual(layout.cell, (238, 333))
        self.assertTrue(all(image.size == (238, 333) for _, image in fitted))

    def test_the_cap_only_ever_scales_down(self) -> None:
        small = blank(100, 50)
        self.assertIs(fit_image(small, 4096), small)
        big = blank(8000, 2000)
        self.assertEqual(fit_image(big, 4000).size, (4000, 1000))


class TokenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()

    def test_a_meeple_is_a_disc_in_the_team_colour_on_transparency(self) -> None:
        for team in Team:
            player = by_role(self.catalog, team, PlayerRole.FULLBACK)
            token = render_meeple_token(player, team)
            self.assertEqual(token.size, (MEEPLE_TOKEN_SIZE, MEEPLE_TOKEN_SIZE))
            self.assertEqual(token.mode, "RGBA")
            self.assertEqual(token.getpixel((0, 0))[3], 0, "the corner is off the disc")
            # Just inside the ring, on the left edge at mid-height, is the fill.
            fill = TEAM_COLORS[team].lstrip("#")
            expected = tuple(int(fill[i:i + 2], 16) for i in (0, 2, 4))
            ring = round(4 * MEEPLE_TOKEN_SIZE / MEEPLE_SIZE)
            sample = token.getpixel((ring + 6, MEEPLE_TOKEN_SIZE // 2))
            self.assertEqual(sample[:3], expected, team)
            self.assertEqual(sample[3], 255)

    def test_the_two_cuts_of_a_meeple_differ(self) -> None:
        team = Team.OOZES
        player = by_role(self.catalog, team, PlayerRole.STRIKER)
        with_icon = render_meeple_token(player, team, species_icons=True)
        plain = render_meeple_token(player, team, species_icons=False)
        self.assertNotEqual(with_icon.tobytes(), plain.tobytes())

    def test_a_die_has_twelve_faces_and_no_more(self) -> None:
        face = render_die_face(12, TEAM_COLORS[Team.ORANGE])
        self.assertEqual(face.size, (screentop.DIE_FACE_SIZE, screentop.DIE_FACE_SIZE))
        self.assertEqual(face.getpixel((0, 0))[3], 0)
        # Well below the top vertex, which sits an edge-width down from the canvas edge.
        self.assertEqual(face.getpixel((face.width // 2, face.height // 4))[3], 255)
        for value in (0, 13):
            with self.assertRaises(ValueError):
                render_die_face(value, "#ffffff")
        ball = render_ball_die_face(1)
        # Beside the numeral, on the face itself, which is white.
        self.assertEqual(ball.getpixel((ball.width * 3 // 4, ball.height // 2))[:3], (255, 255, 255))

    def test_the_dice_are_one_per_colour_and_the_ball(self) -> None:
        sheets = [a for a in die_assets(MAX_SIDE) if a.entry["kind"] == "die_sheet"]
        self.assertEqual(
            [a.path for a in sheets],
            [f"dice/d12-{name}-sheet.png" for name in ("orange", "teal", "purple", "slime", "ball")],
        )
        for sheet in sheets:
            self.assertEqual(sheet.entry["count"], D12_SIDES)
            self.assertEqual(
                sheet.entry["cells"],
                [f"{sheet.entry['cells'][0].rsplit('-', 1)[0]}-{v}" for v in range(1, D12_SIDES + 1)],
            )

    def test_the_coin_on_the_table_is_the_coin_the_bot_flips(self) -> None:
        for face, path in screentop.COIN_FACE_ART.items():
            self.assertEqual(path.stem, COIN_EMOJI_NAMES[face])
            self.assertTrue(path.exists(), path)

    def test_every_condition_token_and_both_coin_faces_ship(self) -> None:
        paths = [a.path for a in condition_token_assets()]
        self.assertEqual(
            paths,
            [f"tokens/conditions/{name}.png" for name in screentop.CONDITION_TOKEN_ART]
            + ["tokens/coin-fortune.png", "tokens/coin-doom.png"],
        )


class KitTests(unittest.TestCase):
    """The whole export, built once; what the manifest promises is held to."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.assets = build_assets()
        cls.by_path = {asset.path: asset for asset in cls.assets}
        cls.listing = manifest(cls.assets, MAX_SIDE)

    def test_every_file_has_one_path_and_a_manifest_entry(self) -> None:
        counts = Counter(asset.path for asset in self.assets)
        self.assertEqual([p for p, n in counts.items() if n > 1], [])
        self.assertEqual(
            [entry["file"] for entry in self.listing["assets"]],
            [asset.path for asset in self.assets],
        )

    def test_nothing_exceeds_the_cap_and_nothing_was_scaled_up(self) -> None:
        for asset in self.assets:
            self.assertLessEqual(max(asset.image.size), MAX_SIDE, asset.path)
            self.assertEqual(list(asset.image.size), asset.entry["size"], asset.path)
        for kind in ("card", "card_back"):
            for asset in self.assets:
                if asset.entry["kind"] == kind:
                    self.assertEqual(asset.image.size, (CARD_WIDTH, CARD_HEIGHT), asset.path)

    def test_a_sheet_s_grid_divides_into_its_cells(self) -> None:
        sheets = [a for a in self.assets if "columns" in a.entry]
        self.assertTrue(sheets)
        for sheet in sheets:
            entry = sheet.entry
            columns, rows, cell = entry["columns"], entry["rows"], entry["cell"]
            self.assertEqual(sheet.image.size, (columns * cell[0], rows * cell[1]), sheet.path)
            self.assertEqual(len(entry["cells"]), entry["count"], sheet.path)
            self.assertLessEqual(entry["count"], columns * rows, sheet.path)
            self.assertGreater(entry["count"], (rows - 1) * columns, sheet.path)
            folder = sheet.path.rsplit("/", 1)[0]
            for name in entry["cells"]:
                single = self.by_path[f"{folder}/{name}.png"]
                self.assertEqual(list(single.image.size), cell, single.path)

    def test_a_front_sheet_names_its_back_and_they_share_a_grid(self) -> None:
        fronts = [a for a in self.assets if a.entry["kind"] == "card_sheet"]
        self.assertTrue(fronts)
        for front in fronts:
            entry = front.entry
            if "back_sheet" in entry:
                back = self.by_path[entry["back_sheet"]].entry
                self.assertEqual(back["kind"], "card_back_sheet")
                for key in ("columns", "rows", "count", "cell"):
                    self.assertEqual(back[key], entry[key], front.path)
            else:
                back = self.by_path[entry["back"]].entry
                self.assertEqual(back["kind"], "card_back")
                self.assertEqual(back["size"], entry["cell"], front.path)

    def test_a_player_s_back_is_behind_their_own_front_not_duplex_reversed(self) -> None:
        for front in self.assets:
            if front.entry["kind"] != "card_sheet" or "team" not in front.entry:
                continue
            back = self.by_path[front.entry["back_sheet"]].entry
            self.assertEqual(
                back["cells"],
                [f"{name}-advanced" for name in front.entry["cells"]],
                front.path,
            )

    def test_every_team_has_its_cards_and_two_cuts_of_meeples(self) -> None:
        catalog = load_player_catalog()
        for team in Team:
            self.assertIn(f"player-cards/{team.value}-fronts-sheet.png", self.by_path)
            self.assertIn(f"boards/team-board-{team.value}.png", self.by_path)
            for folder in ("meeples", "meeples-basic"):
                sheet = self.by_path[f"tokens/{folder}/{team.value}-sheet.png"]
                self.assertEqual(sheet.entry["count"], len(catalog.teams[team].players))

    def test_a_maneuver_sheet_is_a_side_s_hand_named_by_key(self) -> None:
        offense = self.by_path["maneuver-cards/offense-sheet.png"].entry
        defense = self.by_path["maneuver-cards/defense-sheet.png"].entry
        self.assertEqual((offense["columns"], offense["rows"], offense["count"]), (3, 2, 6))
        self.assertEqual((defense["columns"], defense["rows"], defense["count"]), (3, 2, 6))
        # A row a tier: the basic three, then the gambit of each rank.
        catalog = load_maneuver_catalog()
        for side, entry in (("offense", offense), ("defense", defense)):
            expected = [
                f"{side[0]}{m.rank}-{m.key.replace('_', '-')}"
                for tier in MANEUVER_TIERS
                for m in catalog.for_tier(side, tier)
            ]
            self.assertEqual(entry["cells"], expected)
        self.assertEqual(offense["cells"][0], "o1-low-pass")

    def test_write_kit_lists_exactly_what_it_wrote(self) -> None:
        subset = [
            a for a in self.assets
            if a.path.startswith(("dice/d12-ball", "tokens/coin", "species-cards/"))
        ]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            listing = write_kit(out, MAX_SIDE, subset)
            written = sorted(
                str(p.relative_to(out)) for p in out.rglob("*.png")
            )
            self.assertEqual(written, sorted(a.path for a in subset))
            on_disk = json.loads((out / "manifest.json").read_text())
            self.assertEqual(on_disk, listing)
            self.assertEqual(on_disk["max_side"], MAX_SIDE)
            for entry in on_disk["assets"]:
                with Image.open(out / entry["file"]) as image:
                    self.assertEqual(list(image.size), entry["size"], entry["file"])


if __name__ == "__main__":
    unittest.main()
