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
    CARDS_PER_AREA,
    CLOCK_COLUMNS,
    CLOCK_MINUTES,
    DEFAULT_PAPER,
    HALFTIME_MINUTE,
    MIN_TOKEN_INCHES,
    PRINT_DPI,
    SCORE_TRACK_MAX,
    TOKEN_SUPPLIES,
    FieldGeometry,
    Sheet,
    TeamBoardGeometry,
    card_slot_inches,
    cell_inches,
    draw_formation_strip,
    formation_strip_segments,
    kickoff_marks,
    render_field_board,
    render_jumbotron_board,
    load_token_art,
    render_team_board,
    roster_line,
    sheet_pixels,
    shooting_range_bands,
    standard_deal_line,
)
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

    def panel_geometry(self, paper: str) -> TeamBoardGeometry:
        """
        One coach's own panel, at the size `render_team_board` actually
        cuts each area from -- half the sheet's height, since two
        coaches' boards share the one sheet now. See `TeamBoardGeometry`.
        """
        width, height = sheet_pixels(paper, landscape=True)
        return TeamBoardGeometry.for_sheet(Sheet(width, height // 2))

    def test_a_board_is_rendered_coloured_and_uncoloured(self) -> None:
        for team in (None,) + tuple(Team):
            with self.subTest(team=team):
                self.assertEqual(
                    self.render(team=team).size,
                    sheet_pixels(DEFAULT_PAPER, True),
                )

    def test_the_sheet_is_two_identical_panels(self) -> None:
        """
        One sheet, two coaches: with no team to tell them apart the top
        half (visiting's) and the bottom half (home's) have to be the
        same picture, or the two boards a match actually needs would
        not be interchangeable the way a coach expects.
        """
        image = self.render()
        width, height = image.size
        half = height // 2
        top = image.crop((0, 0, width, half))
        bottom = image.crop((0, half, width, half * 2))
        self.assertEqual(top.tobytes(), bottom.tobytes())

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
        A4 and letter are a proof to read rather than a board to lay
        cards on. The slots scale down with the panel instead of the
        areas overflowing it, and `card_slot_inches` is what the CLI
        reads to say which of the two a print is.

        **Tabloid holds a real card too now**, unlike before the two
        zone rows moved off this board: with only the bench, the back
        bench and the head coach's cell left, tabloid's own panel has
        room to spare rather than falling 0.7in short the way a whole
        unhalved sheet used to. See `test_the_card_areas_hold_a_real_card_at_print_size`.
        """
        for paper in ("a4", "letter"):
            with self.subTest(paper=paper):
                self.assertLess(card_slot_inches(paper)[0], CARD_INCHES[0])
        for paper in ("a4", "letter", "tabloid"):
            with self.subTest(paper=paper):
                self.assertEqual(
                    self.render(paper=paper).size,
                    sheet_pixels(paper, True),
                )

    def test_every_area_holds_three_cards_side_by_side(self) -> None:
        """
        Three is what a bench ever has to hold, between them -- so the
        fan has to fit the area it is drawn in.
        """
        geometry = self.panel_geometry("a3")
        fan = (
            geometry.slot[0] + geometry.slot_pitch * (CARDS_PER_AREA - 1)
        )
        for column in range(3):
            left, top, right, bottom = geometry.area(column)
            with self.subTest(column=column):
                self.assertLessEqual(fan, right - left)
                self.assertLessEqual(geometry.slot[1], bottom - top)
                self.assertLessEqual(right, geometry.right)
                self.assertLessEqual(bottom, geometry.rows[0][1])
        # And the guides are a fan rather than a stack: each card
        # behind the front one still shows an edge to pick it up by.
        self.assertGreater(geometry.slot_pitch, geometry.slot[0] * 0.3)

    def test_the_bench_and_the_head_coach_each_have_an_area(self) -> None:
        """
        Three cells for the three places a card or the coach's own
        d12 can be -- the bench, the back bench and the head coach.
        The three zone areas moved to the field board (see "The
        zone-assignment rows" in docs/design/printed-boards.md), which is what let two of
        these panels share a sheet in the first place.
        """
        geometry = self.panel_geometry("a3")
        self.assertEqual(len(geometry.columns) * len(geometry.rows), 3)

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
        """
        self.assertEqual(self.rules.team_board.team_die.sides, 12)

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
        width, height = sheet_pixels("a3", landscape=True)
        sheet = Sheet(width, height // 2)
        geometry = TeamBoardGeometry.for_sheet(sheet)
        for share in (1.0, 0.85):
            with self.subTest(share=share):
                right = geometry.left + (geometry.right - geometry.left) * share
                self.assertLessEqual(
                    draw_formation_strip(
                        sheet,
                        self.rules,
                        geometry.left,
                        geometry.rows[0][1],
                        right,
                    ),
                    right,
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
    def test_the_board_is_rendered_at_print_size(self) -> None:
        self.assertEqual(
            render_jumbotron_board().size, sheet_pixels(DEFAULT_PAPER, True)
        )

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
