"""
The two printed boards.

The suite cannot see a picture any more than it can see the bot's own
board, so what it checks is the two things a print gets wrong silently:
the geometry it asserts about the rules -- where a range starts, where
a kickoff is -- and whether an area is still big enough to put a card
on. A board that has quietly shrunk its card slots below poker size
still renders, and nobody finds out until it comes off a printer.
"""
import unittest

from PIL import Image

from d12ball.boards import (
    BLEED_INCHES,
    CARD_INCHES,
    CARDS_PER_AREA,
    CLOCK_MINUTES,
    PRINT_DPI,
    Sheet,
    TeamBoardGeometry,
    card_slot_inches,
    die_face_label,
    kickoff_marks,
    render_field_board,
    render_team_board,
    roster_line,
    sheet_pixels,
    shooting_range_bands,
    standard_deal_line,
)
from d12ball.components import (
    BoardState,
    TeamSide,
    Zone,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.game import Team


class D12BallFieldBoardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rules = load_basic_ruleset()

    def test_a_board_is_rendered_for_every_layout_the_bot_plays(self) -> None:
        for board_size in sorted(self.rules.board_layouts):
            with self.subTest(board_size=board_size):
                board = render_field_board(self.rules, board_size)
                self.assertEqual(board.size, sheet_pixels("a3", True))

    def test_an_unknown_board_size_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            render_field_board(self.rules, 8)

    def test_the_range_brackets_are_the_living_rules_table(self) -> None:
        """
        The bracket printed under the field is the one thing on it a
        coach reads a rule off, so it is checked against the table in
        "Field, direction, and shooting range" space by space. -1 is
        the visitors' range, 1 home's, 0 the space in neither.
        """
        expected = {
            6: [(-1, 0, 2), (1, 3, 5)],
            7: [(-1, 0, 2), (0, 3, 3), (1, 4, 6)],
            9: [(-1, 0, 3), (0, 4, 4), (1, 5, 8)],
        }
        for board_size, bands in expected.items():
            with self.subTest(board_size=board_size):
                board = BoardState.empty(self.rules.board_layouts[board_size])
                self.assertEqual(shooting_range_bands(board), bands)

    def test_only_an_odd_board_has_a_space_in_nobody_s_range(self) -> None:
        for board_size, layout in self.rules.board_layouts.items():
            board = BoardState.empty(layout)
            neither = [
                band for band in shooting_range_bands(board) if band[0] == 0
            ]
            with self.subTest(board_size=board_size):
                self.assertEqual(len(neither), board_size % 2)

    def test_board_six_marks_a_kickoff_space_for_each_side(self) -> None:
        """
        Board 6's midfield has no middle space, so the two sides kick
        off from different ones and the print has to say which is
        whose. Every other board marks one space for both.
        """
        marks = kickoff_marks(self.rules.board_layouts[6])
        self.assertEqual(
            marks, {2: [TeamSide.HOME], 3: [TeamSide.VISITING]}
        )

        for board_size in (7, 9):
            with self.subTest(board_size=board_size):
                marks = kickoff_marks(self.rules.board_layouts[board_size])
                self.assertEqual(len(marks), 1)
                (flat, sides), = marks.items()
                self.assertEqual(sides, [TeamSide.HOME, TeamSide.VISITING])
                # The true middle, which is what leaves it in neither
                # side's range.
                self.assertEqual(flat, (board_size - 1) // 2)

    def test_a_kickoff_space_is_in_nobody_s_shooting_range(self) -> None:
        for board_size, layout in self.rules.board_layouts.items():
            board = BoardState.empty(layout)
            for flat, sides in kickoff_marks(layout).items():
                for side in sides:
                    with self.subTest(board_size=board_size, side=side):
                        self.assertFalse(
                            board.is_in_shooting_range(side, flat)
                        )

    def test_the_clock_track_is_a_period(self) -> None:
        self.assertEqual(CLOCK_MINUTES, 15)


class D12BallTeamBoardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rules = load_basic_ruleset()
        cls.players = load_player_catalog()
        cls.maneuvers = load_maneuver_catalog()

    def render(self, **kwargs) -> Image.Image:
        return render_team_board(
            self.rules, self.players, self.maneuvers, **kwargs
        )

    def test_a_board_is_rendered_coloured_and_uncoloured(self) -> None:
        for team in (None,) + tuple(Team):
            with self.subTest(team=team):
                self.assertEqual(
                    self.render(team=team).size, sheet_pixels("a3", True)
                )

    def test_the_card_areas_hold_a_real_card_at_print_size(self) -> None:
        """
        The point of the sheet is that cards go on it. A3's areas are
        cut for a poker card, and the layout is tight enough that a
        band added above them takes them under one -- which is exactly
        the change that renders fine and prints useless.
        """
        width, height = card_slot_inches("a3")
        self.assertGreaterEqual(width, CARD_INCHES[0])
        self.assertGreaterEqual(height, CARD_INCHES[1])

    def test_a_smaller_sheet_says_so_rather_than_overflowing(self) -> None:
        """
        Every other size is a proof to read rather than a board to lay
        cards on -- tabloid included, which is wider than A3 but 0.7in
        shorter, and two rows of cards is what the shorter side has to
        hold. The slots scale down with the sheet instead of the areas
        overflowing it, and `card_slot_inches` is what the CLI reads to
        say which of the two a print is.
        """
        for paper in ("a4", "letter", "tabloid"):
            with self.subTest(paper=paper):
                self.assertLess(card_slot_inches(paper)[0], CARD_INCHES[0])
                self.assertEqual(
                    self.render(paper=paper).size, sheet_pixels(paper, True)
                )

    def test_every_area_holds_three_cards_side_by_side(self) -> None:
        """
        Three is what an area ever has to hold -- a zone holds three
        under 2-3-1 and 1-3-2, and the benches three between them -- so
        the fan has to fit the area it is drawn in.
        """
        sheet = Sheet(*sheet_pixels("a3", True))
        geometry = TeamBoardGeometry.for_sheet(sheet)
        fan = (
            geometry.slot[0] + geometry.slot_pitch * (CARDS_PER_AREA - 1)
        )
        for column in range(3):
            for row in range(2):
                left, top, right, bottom = geometry.area(column, row)
                with self.subTest(column=column, row=row):
                    self.assertLessEqual(fan, right - left)
                    self.assertLessEqual(geometry.slot[1], bottom - top)
                    self.assertLessEqual(right, sheet.width)
                    self.assertLessEqual(bottom, sheet.height)
        # And the guides are a fan rather than a stack: each card
        # behind the front one still shows an edge to pick it up by.
        self.assertGreater(geometry.slot_pitch, geometry.slot[0] * 0.3)

    def test_a_zone_has_an_area_and_so_does_each_bench(self) -> None:
        """
        Six cells for the six places a card can be. The three zones
        come from the Zone enum, so a fourth zone would need a cell of
        its own rather than silently going undrawn.
        """
        sheet = Sheet(*sheet_pixels("a3", True))
        geometry = TeamBoardGeometry.for_sheet(sheet)
        self.assertEqual(
            len(geometry.columns) * len(geometry.rows),
            len(Zone) + len(("bench", "back bench")) + 1,
        )

    def test_the_die_faces_are_the_catalog_s(self) -> None:
        """
        The legend is the whole reason the head coach cell is there,
        and it is read off the catalog: an import that re-cut the die
        would change the board rather than leaving it wrong.
        """
        labels = {
            maneuver.name: die_face_label(maneuver)
            for maneuver in self.maneuvers.offense + self.maneuvers.defense
        }
        self.assertEqual(
            labels,
            {
                "Low Pass": "1–2",
                "Dribble Advance": "3–4",
                "High Pass": "5–6",
                "Block Deflect": "1–2",
                "Steal Intercept": "3–4",
                "Pressure": "5–6",
            },
        )

    def test_the_roster_line_counts_the_nine_cards(self) -> None:
        line = roster_line(self.players)
        self.assertIn("1 Fullback", line)
        self.assertIn("2 Defenders", line)
        self.assertIn("2 Strikers", line)

    def test_the_standard_deal_names_every_zone_s_pair(self) -> None:
        line = standard_deal_line(self.rules)
        for role in (
            "Fullback",
            "Defender",
            "Midfielder",
            "Playmaker",
            "Winger",
            "Striker",
        ):
            self.assertIn(role, line)


class D12BallPrintSizeTests(unittest.TestCase):
    def test_a_sheet_is_its_paper_size_at_three_hundred_dpi(self) -> None:
        width, height = sheet_pixels("a3", landscape=True)
        self.assertEqual(round(width / PRINT_DPI), 17)
        self.assertGreater(width, height)
        self.assertEqual(
            sheet_pixels("a3", landscape=False), (height, width)
        )

    def test_an_unknown_paper_size_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            sheet_pixels("a0", landscape=True)

    def test_bleed_adds_an_eighth_of_an_inch_all_round(self) -> None:
        rules = load_basic_ruleset()
        plain = render_field_board(rules, 7)
        bled = render_field_board(rules, 7, bleed=True)
        bleed = 2 * round(BLEED_INCHES * PRINT_DPI)
        self.assertEqual(bled.width - plain.width, bleed)
        self.assertEqual(bled.height - plain.height, bleed)


if __name__ == "__main__":
    unittest.main()
