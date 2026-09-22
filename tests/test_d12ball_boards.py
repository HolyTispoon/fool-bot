"""
The three printed boards.

The suite cannot see a picture any more than it can see the bot's own
board, so what it checks is the two things a print gets wrong silently:
the geometry it asserts about the rules -- where a range starts, where
a kickoff is -- and whether an area is still big enough to put a card
on. A board that has quietly shrunk its card slots below poker size
still renders, and nobody finds out until it comes off a printer.
"""
import unittest
from pathlib import Path

from PIL import Image

from d12ball import boards

from d12ball.boards import (
    BLEED_INCHES,
    CARD_INCHES,
    CLOCK_COLUMNS,
    CLOCK_MINUTES,
    DEFAULT_PAPER,
    HALFTIME_MINUTE,
    HALF_PAPERS,
    MIN_TOKEN_INCHES,
    PRINT_DPI,
    JUMBOTRON_PAPER,
    SCORE_COLUMNS,
    SCORE_TRACK_MAX,
    TEAM_BOARD_PAPER,
    TEAM_CUT_INCHES,
    TOKEN_SUPPLIES,
    FieldGeometry,
    JumbotronGeometry,
    Sheet,
    TeamBoardGeometry,
    card_slot_inches,
    cell_inches,
    draw_formation_strip,
    fitted_print_font,
    formation_strip_segments,
    half_paper,
    halve_sheet,
    kickoff_marks,
    render_field_board,
    render_field_board_halves,
    render_jumbotron_board,
    load_token_art,
    render_team_board,
    render_team_board_sheet,
    roster_line,
    sheet_pixels,
    shooting_range_bands,
    standard_deal_line,
    team_board_pixels,
    team_reminders,
)
from d12ball.cards import BACK_COLOR, DEFENSE_COLOR, OFFENSE_COLOR
from d12ball.components import (
    BoardState,
    MatchPeriod,
    TeamSide,
    Zone,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
    period_last_minute,
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
                self.assertEqual(board.size, sheet_pixels(DEFAULT_PAPER, False))

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
            7: [(-1, 0, 2), (0, 3, 3), (1, 4, 6)],
            9: [(-1, 0, 3), (0, 4, 4), (1, 5, 8)],
        }
        for board_size, bands in expected.items():
            with self.subTest(board_size=board_size):
                board = BoardState.empty(self.rules.board_layouts[board_size])
                self.assertEqual(shooting_range_bands(board), bands)

    def test_every_board_has_one_space_in_nobody_s_range(self) -> None:
        # Every board has an odd number of spaces, so every board has a
        # true middle, and the middle is in neither side's range -- see
        # "Shooting range" in the living rules.
        for board_size, layout in self.rules.board_layouts.items():
            board = BoardState.empty(layout)
            neither = [
                band for band in shooting_range_bands(board) if band[0] == 0
            ]
            with self.subTest(board_size=board_size):
                self.assertEqual(len(neither), 1)

    def test_every_board_marks_one_kickoff_space_for_both_sides(
        self,
    ) -> None:
        """
        Every midfield has a middle space, so both sides kick off from
        it and the print carries one mark -- which is still drawn from
        a map, because the rule is asked per side.
        """
        for board_size in sorted(self.rules.board_layouts):
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

    def test_a_space_is_big_enough_to_stand_meeples_on(self) -> None:
        """
        Both sides can be on one space, so a space that is only wide
        enough for one meeple is the failure this board exists to
        avoid -- and giving them the room the clock and score used to
        take is why those moved to the jumbotron.

        **The width floor came down from 1.5in to 1.0in** when the
        sheet went portrait to make room for the zone-assignment rows
        (see `FieldGeometry`) -- the author's own call, made knowing
        the 9-space board's spaces come out close to that new floor
        rather than comfortably above the old one. The height floor
        did not move; the strip has far more of it to spare now than
        it used to.
        """
        for board_size in sorted(self.rules.board_layouts):
            sheet = Sheet(*sheet_pixels(DEFAULT_PAPER, False))
            geometry = FieldGeometry.for_sheet(
                sheet, self.rules.board_layouts[board_size]
            )
            width, height = geometry.space_inches
            with self.subTest(board_size=board_size):
                self.assertGreaterEqual(width, 1.0)
                self.assertGreaterEqual(height, 4.0)
                self.assertLessEqual(
                    geometry.range_bottom, geometry.home_zone_top
                )

    def test_the_zone_rows_hold_a_real_card_and_do_not_overlap(self) -> None:
        """
        Each zone-assignment row is a card row, full stop -- see
        "The zone-assignment rows" in docs/design/printed-boards.md -- so it has to clear
        `CARD_INCHES`' own height, and the two rows (visiting's above
        the strip, home's below it) must never reach into the header,
        the strip or each other.
        """
        sheet = Sheet(*sheet_pixels(DEFAULT_PAPER, False))
        geometry = FieldGeometry.for_sheet(
            sheet, self.rules.board_layouts[7]
        )
        row_height = geometry.visiting_zone_bottom - geometry.visiting_zone_top
        self.assertGreaterEqual(row_height / PRINT_DPI, CARD_INCHES[1])
        self.assertAlmostEqual(
            geometry.home_zone_bottom - geometry.home_zone_top, row_height
        )
        self.assertLess(geometry.visiting_zone_bottom, geometry.header_top)
        self.assertLess(geometry.range_bottom, geometry.home_zone_top)
        self.assertLessEqual(geometry.home_zone_bottom, sheet.height)


class D12BallHalfSheetTests(unittest.TestCase):
    """
    The field board printed on two small sheets instead of one big one.

    The whole claim of the halves is that they are the board -- print
    them, tape the cut, and a coach has the tabloid board at the size
    it prints at. So what the suite checks is that nothing has been
    re-laid-out behind that claim, and that the cut still lands where
    the halves can be taped without a word across the seam.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.rules = load_basic_ruleset()

    def test_the_two_halves_are_the_board(self) -> None:
        """
        **The invariant the halves exist for**, and the one a second
        layout for the smaller paper would break silently: pasted back
        together they are the sheet, pixel for pixel, so a space is
        the width it is on the tabloid board rather than whatever fits
        a letter one.
        """
        for board_size in sorted(self.rules.board_layouts):
            with self.subTest(board_size=board_size):
                board = render_field_board(self.rules, board_size)
                top, bottom = render_field_board_halves(
                    self.rules, board_size
                )
                joined = Image.new("RGB", board.size)
                joined.paste(top, (0, 0))
                joined.paste(bottom, (0, top.height))
                self.assertEqual(joined.tobytes(), board.tobytes())

    def test_a_half_is_a_sheet_of_the_paper_below(self) -> None:
        """
        Half a tabloid sheet is a letter one turned the other way, to
        the pixel -- which is the only reason this works at all. A half
        that had to be scaled to fit its paper would be a smaller
        board, not the same one.
        """
        halved = half_paper(DEFAULT_PAPER)
        self.assertEqual(halved, "letter")
        for board_size in sorted(self.rules.board_layouts):
            for name, half in zip(
                ("top", "bottom"),
                render_field_board_halves(self.rules, board_size),
            ):
                with self.subTest(board_size=board_size, half=name):
                    self.assertEqual(
                        half.size, sheet_pixels(halved, landscape=True)
                    )

    def test_every_paper_that_names_its_halves_really_halves_into_it(
        self,
    ) -> None:
        for paper, halved in HALF_PAPERS.items():
            with self.subTest(paper=paper):
                width, height = sheet_pixels(paper, landscape=False)
                self.assertEqual(
                    (width, height // 2),
                    sheet_pixels(halved, landscape=True),
                )
                self.assertEqual(height % 2, 0)

    def test_a_paper_that_halves_into_nothing_standard_says_so(
        self,
    ) -> None:
        """Absent rather than approximated -- it still renders."""
        self.assertIsNone(half_paper("letter"))
        with self.assertRaises(ValueError):
            half_paper("a0")

    def test_the_cut_falls_across_the_strip_and_clear_of_its_words(
        self,
    ) -> None:
        """
        Where the cut lands is not a choice -- only the exact middle
        gives two halves that both fit the paper -- so this is a check
        on the *layout*: if a band ever moves so that the middle of the
        sheet crosses the header, a zone-assignment row or the strip's
        own labels, the halves start cutting words in two and somebody
        should look at the picture before shipping them.

        The strip is the safe place for a seam because it is tints and
        outlines: its zone names and space codes are all hung from its
        top, which is what `strip_label_bottom` measures.
        """
        width, height = sheet_pixels(DEFAULT_PAPER, landscape=False)
        seam = height // 2
        for board_size in sorted(self.rules.board_layouts):
            with self.subTest(board_size=board_size):
                geometry = FieldGeometry.for_sheet(
                    Sheet(width, height),
                    self.rules.board_layouts[board_size],
                )
                self.assertLess(seam, geometry.strip_bottom)
                self.assertGreater(
                    (seam - geometry.strip_label_bottom) / PRINT_DPI,
                    MIN_TOKEN_INCHES,
                )

    def test_each_half_gets_its_own_bleed_and_the_cut_gets_none(
        self,
    ) -> None:
        """
        The board is halved first and each half bled after, so the two
        still butt together once a shop has trimmed into the margin --
        bleeding the sheet and then cutting it would put half the
        margin down the seam and none on two of the outer edges.
        """
        plain = render_field_board_halves(self.rules, 7)
        bled = render_field_board_halves(self.rules, 7, bleed=True)
        bleed = 2 * round(BLEED_INCHES * PRINT_DPI)
        for name, before, after in zip(("top", "bottom"), plain, bled):
            with self.subTest(half=name):
                self.assertEqual(after.width - before.width, bleed)
                self.assertEqual(after.height - before.height, bleed)

    def test_a_sheet_is_cut_across_its_longer_side(self) -> None:
        """
        Top and bottom for a portrait sheet, left and right for a
        landscape one -- the cut that leaves two halves of the paper
        below, whichever way the board is drawn.
        """
        portrait = halve_sheet(Image.new("RGB", (10, 20)))
        self.assertEqual([half.size for half in portrait], [(10, 10)] * 2)
        landscape = halve_sheet(Image.new("RGB", (20, 10)))
        self.assertEqual([half.size for half in landscape], [(10, 10)] * 2)

    def test_an_odd_sheet_still_halves_into_the_whole_of_it(self) -> None:
        """The spare pixel goes to the second half rather than nowhere."""
        first, second = halve_sheet(Image.new("RGB", (10, 21)))
        self.assertEqual((first.height, second.height), (10, 11))


class D12BallTeamBoardTests(unittest.TestCase):
    """
    One coach's board, and the page two of them are cut from.

    What the suite can see here is the two things the old board got
    wrong without failing: a band measured one way holding lines
    measured another (the deal and the reminder were drawn below the
    bottom of the panel and cropped away), and an area that quietly
    stopped being the size of the thing it holds.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.rules = load_basic_ruleset()
        cls.players = load_player_catalog()
        cls.maneuvers = load_maneuver_catalog()

    def render(self, **kwargs) -> Image.Image:
        return render_team_board(
            self.rules, self.players, self.maneuvers, **kwargs
        )

    def board_geometry(self, paper: str = TEAM_BOARD_PAPER):
        width, height = team_board_pixels(paper)
        return TeamBoardGeometry.for_sheet(Sheet(width, height))

    def test_a_board_is_rendered_coloured_and_uncoloured(self) -> None:
        for team in (None,) + tuple(Team):
            with self.subTest(team=team):
                self.assertEqual(
                    self.render(team=team).size,
                    team_board_pixels(TEAM_BOARD_PAPER),
                )

    def test_a_board_is_half_a_letter_sheet(self) -> None:
        """
        Which is what makes two of them a page -- the one measurement
        the two files this board is printed as agree on.
        """
        width, height = team_board_pixels(TEAM_BOARD_PAPER)
        self.assertEqual(width / PRINT_DPI, 8.5)
        self.assertEqual(height / PRINT_DPI, 5.5)

    def test_two_boards_are_a_page_and_they_are_the_same_board(
        self,
    ) -> None:
        """
        One sheet, two coaches: the page is the board pasted twice, so
        each half a coach cuts off has to be the board itself, to the
        pixel. Everything but the seam the cut line is drawn down --
        that line is the one mark on the page that belongs to neither
        board.
        """
        board = self.render()
        sheet = render_team_board_sheet(
            self.rules, self.players, self.maneuvers
        )
        self.assertEqual(
            sheet.size, sheet_pixels(TEAM_BOARD_PAPER, landscape=False)
        )
        width, height = sheet.size
        seam = round(TEAM_CUT_INCHES * PRINT_DPI) + 1
        for name, top in (
            ("visiting", 0),
            ("home", height - board.height),
        ):
            with self.subTest(board=name):
                self.assertEqual(
                    sheet.crop(
                        (0, top + seam, width, top + board.height - seam)
                    ).tobytes(),
                    board.crop(
                        (0, seam, width, board.height - seam)
                    ).tobytes(),
                )

    def test_every_band_is_in_order_and_inside_the_board(self) -> None:
        """
        **The regression the whole layout was redone for.** The old
        board measured its header and footer in inches and placed the
        lines inside them in thousandths of the sheet's width, and the
        two disagreed: the standard deal and the closing reminder were
        drawn below the bottom edge and cropped off the panel, on a
        render that looked fine.
        """
        geometry = self.board_geometry()
        line_height = (
            boards.TEAM_SMALL_INCHES * boards.TEAM_LINE_LEADING * PRINT_DPI
        )
        bands = (
            geometry.top,
            geometry.roster_top,
            geometry.rule_top,
            geometry.label_top,
            geometry.caption_top,
            geometry.area_top,
            geometry.area_bottom,
            *geometry.footer_lines,
            geometry.footer_lines[-1] + 2 * line_height,
        )
        self.assertEqual(list(bands), sorted(bands))
        self.assertLessEqual(bands[-1], geometry.bottom)

    def test_a_bench_guide_fits_inside_its_own_area(self) -> None:
        """
        A card's footprint, inside the area it is a footprint of --
        and a real card is no wider than the area, so a bench that
        overflows the guide still squares up inside the cell.
        """
        geometry = self.board_geometry()
        slot_width, slot_height = geometry.slot
        for column in (0, 1):
            left, top, right, bottom = geometry.area(column)
            with self.subTest(column=column):
                self.assertLess(slot_width, right - left)
                self.assertLess(slot_height, bottom - top)
                self.assertGreaterEqual(right - left, CARD_INCHES[0] * PRINT_DPI)
        self.assertAlmostEqual(
            slot_width / slot_height,
            CARD_INCHES[0] / CARD_INCHES[1],
            places=6,
        )

    def test_the_guides_are_under_a_poker_card_and_do_not_shrink_further(
        self,
    ) -> None:
        """
        Half a letter sheet does not leave 3.5 inches between a legible
        header, two legible cell labels and a footer, and the author's
        call was legible over life-size -- so the guide is a card's
        proportions at the height the row has. The floor is what
        catches the next band added above it: a guide that has quietly
        shrunk still renders.
        """
        width, height = card_slot_inches()
        self.assertLess(height, CARD_INCHES[1])
        self.assertGreater(width, 1.9)
        self.assertGreater(height, 2.7)

    def test_the_head_coach_column_is_the_card_that_goes_in_it(
        self,
    ) -> None:
        """
        The reference is the back of the maneuver card at 300dpi, so
        the column is cut to the picture rather than the picture fitted
        to a third of the row: a column any wider is a band of empty
        board beside it.
        """
        geometry = self.board_geometry()
        left, right = geometry.columns[2]
        self.assertAlmostEqual(right - left, geometry.reference[0], places=6)
        self.assertAlmostEqual(
            geometry.reference[0] / geometry.reference[1],
            CARD_INCHES[0] / CARD_INCHES[1],
            places=6,
        )
        self.assertLessEqual(geometry.reference[1], CARD_INCHES[1] * PRINT_DPI)
        self.assertLessEqual(right, geometry.right)

    def test_the_head_coach_cell_carries_the_maneuver_card_s_back(
        self,
    ) -> None:
        """
        The picture a coach reads a matchup off is the one on the card
        in their hand -- pasted, not redrawn, so there is one of it.
        What says it is really there is its own three colours: the
        card's white face, and a node of each side.
        """
        board = self.render()
        geometry = self.board_geometry()
        left, top, right, _ = geometry.area(2)
        cell = board.crop(
            (
                round(left),
                round(top),
                round(right),
                round(top + geometry.reference[1]),
            )
        )
        found = {colour for _, colour in cell.getcolors(maxcolors=1 << 20)}
        for colour in (BACK_COLOR, OFFENSE_COLOR, DEFENSE_COLOR):
            with self.subTest(colour=colour):
                self.assertIn(
                    tuple(
                        int(colour[index:index + 2], 16)
                        for index in (1, 3, 5)
                    ),
                    found,
                )

    def test_no_die_value_is_printed_anywhere(self) -> None:
        """
        Maneuvers are chosen with the cards, so the selection d6 is off
        this board and so is every face it had. The ruleset still
        defines the two d6s -- that is the bot's model and the rules'
        component list -- which is exactly why the board has to be
        checked rather than assumed: it reads `team_board` and could
        pick them up again without anyone noticing.
        """
        source = Path(boards.__file__).read_text(encoding="utf-8")
        for reference in ("offense_die", "defense_die", "die_values"):
            with self.subTest(reference=reference):
                self.assertNotIn(reference, source)

    def test_the_head_coach_keeps_only_the_team_die(self) -> None:
        """
        One die, and it is the d12 every roll in the game is made with.
        The footer says so off the ruleset rather than in words written
        here, so a board cannot claim a die the bot does not roll.
        """
        self.assertEqual(self.rules.team_board.team_die.sides, 12)
        self.assertIn("d12", team_reminders(self.rules)[0])

    def test_the_roster_line_counts_the_nine_cards(self) -> None:
        line = roster_line(self.players)
        self.assertIn("1 Fullback", line)
        self.assertIn("2 Defenders", line)
        self.assertIn("2 Strikers", line)

    def test_the_strip_names_every_shape_and_which_board_plays_it(
        self,
    ) -> None:
        """
        One team board is printed for every field size, so a shape only
        some boards play has to be on it *and* say so. The names alone
        are the counts, which is the loader's own invariant.
        """
        said = [text for text, _, _ in formation_strip_segments(self.rules)]
        for formation, shape in self.rules.formations.items():
            with self.subTest(formation=formation.value):
                self.assertIn(formation.value, said)
                if shape.board_sizes is not None:
                    self.assertIn(
                        f"{shape.board_size_label().upper()} BOARD ONLY",
                        said,
                    )

    def test_the_strip_fits_the_width_it_is_given(self) -> None:
        """
        There is no second row under the strip and nothing to catch an
        overflow, so it measures itself and shrinks. A shape added
        upstream lands there without anybody measuring, which the
        narrowed case stands in for.
        """
        width, height = team_board_pixels()
        sheet = Sheet(width, height)
        geometry = TeamBoardGeometry.for_sheet(sheet)
        for share in (1.0, 0.85):
            with self.subTest(share=share):
                right = geometry.left + (geometry.right - geometry.left) * share
                self.assertLessEqual(
                    draw_formation_strip(
                        sheet,
                        self.rules,
                        geometry.left,
                        geometry.footer_lines[0],
                        right,
                    ),
                    right,
                )

    def test_a_line_that_cannot_be_legible_is_dropped_rather_than_shrunk(
        self,
    ) -> None:
        """
        A caption shrunk until it fits reads as a smudge, and the board
        had several. `fitted_print_font` answers with nothing rather
        than with a size nobody can read, and its callers drop the line.
        """
        sheet = Sheet(*team_board_pixels())
        self.assertIsNotNone(
            fitted_print_font(sheet, "BENCH", 2 * PRINT_DPI, 0.165, bold=True)
        )
        self.assertIsNone(
            fitted_print_font(
                sheet,
                "injured players, and anyone subbed out",
                0.3 * PRINT_DPI,
                0.105,
            )
        )

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


class D12BallJumbotronTests(unittest.TestCase):
    def jumbotron_geometry(self) -> JumbotronGeometry:
        return JumbotronGeometry.for_sheet(
            Sheet(*sheet_pixels(JUMBOTRON_PAPER, landscape=False))
        )

    def test_the_board_is_a_letter_sheet_portrait(self) -> None:
        """
        A paper of its own, like the team board, and not the field
        board's tabloid: this is the board with no field on it, so it
        is the one that can be fitted onto the sheet a house printer
        has in it.
        """
        self.assertEqual(JUMBOTRON_PAPER, "letter")
        self.assertEqual(
            render_jumbotron_board().size,
            sheet_pixels(JUMBOTRON_PAPER, landscape=False),
        )

    def test_the_smaller_sheet_did_not_reach_the_clock(self) -> None:
        """
        **Portrait is the clock's doing.** Letter landscape has the
        width for the clock only at thirteen cells to a row, which
        would put halftime in the middle of one -- so the sheet turned
        instead, and the track is the four rows of eight it always was.
        The score is what paid for the smaller sheet, not this.
        """
        self.assertEqual(CLOCK_COLUMNS, 8)
        self.assertEqual(self.jumbotron_geometry().clock_rows, 4)

    def test_the_score_track_wraps_rather_than_shrinking(self) -> None:
        """
        Thirteen cells across a letter sheet would be two-thirds of an
        inch each, under the token this board exists to give a cell to.
        Wrapped, every value still has exactly one cell and no row runs
        past the column count.
        """
        geometry = self.jumbotron_geometry()
        self.assertEqual(geometry.score_rows, 2)
        seen = {}
        for value in range(SCORE_TRACK_MAX + 1):
            row, column = divmod(value, SCORE_COLUMNS)
            self.assertLess(row, geometry.score_rows)
            self.assertLess(column, SCORE_COLUMNS)
            self.assertNotIn((row, column), seen)
            seen[(row, column)] = value
        self.assertEqual(len(seen), SCORE_TRACK_MAX + 1)

    def test_both_sides_tracks_fit_inside_the_score_panel(self) -> None:
        """
        The panel grew from two rows to four on a sheet that got
        smaller, which is exactly where a row would come to be drawn
        below the panel it belongs to -- silently, the way the team
        board's footer once was.
        """
        geometry = self.jumbotron_geometry()
        _, row_height = geometry.score_cell()
        bottom = (
            geometry.score_top
            + geometry.label_height
            + 2 * geometry.score_rows * row_height
        )
        self.assertLessEqual(bottom, geometry.score_bottom)

    def test_every_panel_is_in_order_and_inside_the_sheet(self) -> None:
        """The three panels and the footer, top to bottom, on the page."""
        geometry = self.jumbotron_geometry()
        _, height = sheet_pixels(JUMBOTRON_PAPER, landscape=False)
        edges = (
            geometry.header_top,
            geometry.header_bottom,
            geometry.clock_top,
            geometry.clock_bottom,
            geometry.score_top,
            geometry.score_bottom,
            geometry.supply_top,
            geometry.supply_bottom,
            geometry.footer_y,
        )
        self.assertGreater(edges[0], 0)
        self.assertLess(edges[-1], height)
        for earlier, later in zip(edges, edges[1:]):
            self.assertLessEqual(earlier, later)

    def test_every_cell_can_hold_a_token(self) -> None:
        """
        The whole reason the clock and the score are a board of their
        own. On the field board the clock was sixteen cells across one
        sheet with the field already on it, which is an inch a cell
        with nothing to spare; rows of eight on a sheet of their own is
        what makes a cell something a token stands in.

        It covers the token supplies as well, which are much bigger
        than this -- what it is really watching is the panel shares:
        the clock went from two rows to four and a third panel joined
        them, and a cell squeezed under a token is silent on a render.
        """
        for name, (width, height) in cell_inches().items():
            with self.subTest(cell=name):
                self.assertGreaterEqual(width, MIN_TOKEN_INCHES)
                self.assertGreaterEqual(height, MIN_TOKEN_INCHES)

    def test_the_clock_is_the_game_and_the_halves_are_whole_rows(
        self,
    ) -> None:
        """
        The track is one running clock over both periods, and it breaks
        where the game does: the first half has to fill whole rows, or
        halftime falls in the middle of one and the two bands cannot be
        drawn as bands.

        The second half's own last row is a cell short, which the board
        fills with a note rather than a square -- see draw_clock_track.
        """
        self.assertEqual(HALFTIME_MINUTE, 15)
        self.assertEqual(CLOCK_MINUTES, 30)
        self.assertEqual((HALFTIME_MINUTE + 1) % CLOCK_COLUMNS, 0)

    def test_the_clock_track_is_read_off_the_rules(self) -> None:
        """
        Both numbers come from the code the bot plays by, so a period
        length settled upstream reaches the print by re-rendering
        rather than by somebody editing the module.
        """
        self.assertEqual(
            HALFTIME_MINUTE, period_last_minute(MatchPeriod.FIRST_HALF)
        )
        self.assertEqual(
            CLOCK_MINUTES, period_last_minute(MatchPeriod.SECOND_HALF)
        )

    def test_the_supplies_are_the_three_a_coach_handles(self) -> None:
        """
        The exhaustion stock and the two markers it turns into. A
        player's own tokens are not here -- they are stacked on the
        player's own card.
        """
        self.assertEqual(
            list(TOKEN_SUPPLIES), ["exhaust", "exhausted", "injured"]
        )

    def test_a_silo_prints_the_token_s_own_art(self) -> None:
        """
        The silos carry no words at all, so the art is the whole of what
        says which is which -- and it has to be the same picture the bot
        draws on a player's card and uploads as the application emoji,
        or the table and Discord show a coach two different icons.
        """
        for name in TOKEN_SUPPLIES:
            with self.subTest(token=name):
                art = load_token_art(name)
                self.assertIsNotNone(art)
                # Its own resolution, not render.py's 26px thumbnail.
                self.assertGreater(art.width, 300)

    def test_the_score_track_outruns_a_shootout(self) -> None:
        """
        A shootout adds six pairings to a score that was already level,
        so a track has to hold a plausible match score plus six.
        """
        self.assertGreaterEqual(SCORE_TRACK_MAX, 6 + 6)


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
