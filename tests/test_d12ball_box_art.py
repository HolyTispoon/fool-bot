"""
The box, the sale sheet and the playtest card.

The suite cannot look at a picture, so what it holds is the two things
these panels would get wrong silently. One is a **claim**: every
sentence printed as a rule is quoted from the Charter or the Learn to
Play, and every number is read off the catalogs, so a rules change
that the box has not caught up with fails here rather than on a pallet
of boxes. The other is the **survey code**: a QR is unreadable to
everyone who looks at this render, so the modules are read back off
the drawn panel and compared with the encoder's own matrix.

Looking at the images is still the job -- see "Look at the image" in
CLAUDE.md, and `scripts/render_box_art.py`.
"""
import unittest

from d12ball import box_art
from d12ball.box_art import (
    BARCODE_INCHES,
    BOX_DEPTH_INCHES,
    CHARTER_LINE,
    COVER_CAST,
    HOOK,
    PLAYTEST_CARD_INCHES,
    PRINT_DPI,
    QR_MIN_MODULE_INCHES,
    SELLING_LINES,
    SURVEY_URL,
    TAGLINE,
    TURN_BEATS,
    BoxFacts,
    Panel,
    RetailClaims,
    box_contents,
    box_inches,
    cast_color,
    draw_qr,
    folded_board_inches,
    game_in_brief,
    plain,
    qr_matrix,
    qr_module_inches,
    render_box_bottom,
    render_box_cover,
    render_box_side,
    render_playtest_card_back,
    render_playtest_card_front,
    render_sale_sheet,
)
from d12ball.boards import BLEED_INCHES, DEFAULT_PAPER, PAPERS, Sheet
from d12ball.components import (
    TeamSide,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
    load_species_abilities,
)
from d12ball.render import TEAM_COLORS, load_player_portrait
from d12ball.rules_doc import LIVING_RULES_PATH


LEARN_TO_PLAY_PATH = box_art.LEARN_TO_PLAY_PATH


def books() -> str:
    """Both books as one body of plain text, the way a panel prints them."""
    return "\n".join(
        plain(path.read_text())
        for path in (LIVING_RULES_PATH, LEARN_TO_PLAY_PATH)
    )


class BoxArtQuotesTests(unittest.TestCase):
    """Nothing on these panels states a rule in words of its own."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = books()

    def assert_quoted(self, line: str) -> None:
        self.assertIn(
            line,
            self.text,
            f"{line!r} is printed on the box but is not in either book "
            "word for word. Quote the books, or change them first.",
        )

    def test_the_hook_and_the_tagline_are_the_books_own_words(self) -> None:
        self.assert_quoted(HOOK)
        self.assert_quoted(TAGLINE)
        self.assert_quoted(CHARTER_LINE)

    def test_every_beat_of_a_turn_is_quoted(self) -> None:
        for line, _ in TURN_BEATS:
            self.assert_quoted(line)

    def test_every_beat_names_a_law_the_charter_has(self) -> None:
        laws = plain(LIVING_RULES_PATH.read_text())
        for _, law in TURN_BEATS:
            number = law.split()[1].split(".")[0]
            self.assertRegex(
                laws,
                rf"Law {number}\.",
                f"{law} is cited on the box and the Charter has no Law "
                f"{number}.",
            )

    def test_every_selling_line_is_quoted(self) -> None:
        for line in SELLING_LINES:
            self.assert_quoted(line)

    def test_the_blurb_is_the_charters_own_first_law(self) -> None:
        paragraphs = game_in_brief()
        self.assertTrue(paragraphs)
        for paragraph in paragraphs:
            self.assert_quoted(paragraph)


class BoxContentsTests(unittest.TestCase):
    """The component list is the Learn to Play's, minus the book itself."""

    def test_every_component_of_the_books_own_list_is_on_the_box(self) -> None:
        section = box_art.learn_to_play_section("what-is-in-the-box")
        bullets = [line for line in section.splitlines() if line.startswith("- ")]
        self.assertEqual(len(bullets), len(box_contents()))

    def test_no_entry_still_addresses_the_reader_of_the_book(self) -> None:
        for entry in box_contents():
            self.assertNotIn("this book", entry.lower())

    def test_every_entry_is_a_sentence(self) -> None:
        for entry in box_contents():
            self.assertTrue(entry.endswith("."), entry)


class BoxFactsTests(unittest.TestCase):
    """Every number on the box is the game's own."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()
        cls.maneuvers = load_maneuver_catalog()
        cls.facts = BoxFacts.read(
            catalog=cls.catalog, maneuvers=cls.maneuvers, rules=cls.rules
        )

    def test_the_counts_are_read_from_the_catalogs(self) -> None:
        self.assertEqual(self.facts.coaches, len(TeamSide))
        self.assertEqual(self.facts.teams, len(self.catalog.teams))
        self.assertEqual(self.facts.species, len(load_species_abilities()))
        self.assertEqual(
            self.facts.players_per_team,
            len(next(iter(self.catalog.teams.values())).players),
        )
        self.assertEqual(
            self.facts.maneuvers,
            len(self.maneuvers.offense) + len(self.maneuvers.defense),
        )
        self.assertEqual(
            self.facts.basic_maneuvers + self.facts.gambits,
            self.facts.maneuvers,
        )
        self.assertEqual(
            self.facts.board_sizes, tuple(sorted(self.rules.board_layouts))
        )

    def test_the_fielded_count_is_the_standard_deal(self) -> None:
        self.assertEqual(
            self.facts.fielded,
            sum(len(roles) for roles in self.rules.standard_setup.values()),
        )
        self.assertLess(self.facts.fielded, self.facts.players_per_team)

    def test_the_glance_table_says_something_for_every_row(self) -> None:
        for label, value in self.facts.glance_rows():
            self.assertTrue(label and value, (label, value))


class RetailClaimsTests(unittest.TestCase):
    """A playing time and an age are printed only when somebody has one."""

    def test_nothing_is_claimed_by_default(self) -> None:
        self.assertEqual(RetailClaims().chips, ())

    def test_a_measured_claim_becomes_a_chip(self) -> None:
        self.assertEqual(
            RetailClaims(play_minutes=(45, 60), minimum_age=12).chips,
            ("45-60 MIN", "AGES 12+"),
        )

    def test_one_number_is_not_printed_as_a_range(self) -> None:
        self.assertEqual(RetailClaims(play_minutes=(50, 50)).chips, ("50 MIN",))


class BoxGeometryTests(unittest.TestCase):
    """The box is cut for the board, and a panel comes out at its size."""

    def test_the_box_holds_the_field_board_folded(self) -> None:
        side, other, depth = box_inches()
        self.assertEqual(side, other)
        self.assertGreater(side, max(folded_board_inches(DEFAULT_PAPER)))
        self.assertEqual(depth, BOX_DEPTH_INCHES)

    def test_every_paper_the_boards_print_on_still_folds_into_a_box(self) -> None:
        for paper in PAPERS:
            short, long = folded_board_inches(paper)
            self.assertAlmostEqual(short, PAPERS[paper][0])
            self.assertAlmostEqual(long, PAPERS[paper][1] / 2)
            self.assertGreater(box_inches(paper)[0], max(short, long))

    def test_a_panel_is_its_own_size_and_grows_by_the_bleed(self) -> None:
        trimmed = Panel(6.0, 4.0)
        self.assertEqual(
            trimmed.pixels, (round(6.0 * PRINT_DPI), round(4.0 * PRINT_DPI))
        )
        bled = Panel(6.0, 4.0, bleed=True)
        bleed = round(BLEED_INCHES * PRINT_DPI)
        self.assertEqual(
            bled.pixels,
            (trimmed.pixels[0] + bleed * 2, trimmed.pixels[1] + bleed * 2),
        )

    def test_the_bleed_moves_the_origin_rather_than_the_layout(self) -> None:
        """The trim's own corner is where a panel's inch zero is."""
        self.assertEqual(Panel(6.0, 4.0).x(0), 0)
        self.assertAlmostEqual(
            Panel(6.0, 4.0, bleed=True).x(0), round(BLEED_INCHES * PRINT_DPI)
        )

    def test_the_barcode_area_is_a_real_symbols_size(self) -> None:
        """EAN-13 at its nominal 37.29 x 25.93mm."""
        width, height = BARCODE_INCHES
        self.assertAlmostEqual(width * 25.4, 37.29, delta=0.3)
        self.assertAlmostEqual(height * 25.4, 25.93, delta=0.3)


class CoverCastTests(unittest.TestCase):
    """The four on the cover are four players the game has."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()

    def test_every_one_of_them_is_on_a_roster(self) -> None:
        names = {
            player.name
            for definition in self.catalog.teams.values()
            for player in definition.players
        }
        for name, _ in COVER_CAST:
            self.assertIn(name, names, f"{name} is on the cover and on no team.")

    def test_every_one_of_them_has_a_portrait(self) -> None:
        for name, _ in COVER_CAST:
            self.assertIsNotNone(
                load_player_portrait(name), f"No portrait for {name}."
            )

    def test_two_of_them_face_each_way(self) -> None:
        facings = [facing for _, facing in COVER_CAST]
        self.assertEqual(facings.count("left"), 2)
        self.assertEqual(facings.count("right"), 2)

    def test_each_is_drawn_in_a_colour_a_team_actually_wears(self) -> None:
        for name, _ in COVER_CAST:
            self.assertIn(cast_color(self.catalog, name), set(TEAM_COLORS.values()))


class SurveyCodeTests(unittest.TestCase):
    """The card's QR is the survey, and is big enough to be read."""

    def test_the_code_carries_the_survey_address(self) -> None:
        self.assertTrue(SURVEY_URL.startswith("https://"))
        # Not a decode -- that needs a reader the suite does not have.
        # What it checks is that the encoder was handed the address
        # whole, which is the failure a shortened or re-escaped URL
        # would cause: a URL one character longer needs a bigger code.
        self.assertGreater(len(qr_matrix(SURVEY_URL)), len(qr_matrix("x")))

    def test_a_module_is_big_enough_to_scan(self) -> None:
        module = qr_module_inches(SURVEY_URL, 1.8)
        self.assertGreaterEqual(
            module,
            QR_MIN_MODULE_INCHES,
            f"The card's QR modules are {module * 25.4:.2f}mm, under the "
            f"{QR_MIN_MODULE_INCHES * 25.4:.2f}mm a phone reads reliably. "
            "Shorten the URL or make the code bigger.",
        )

    def test_what_is_drawn_is_what_was_encoded(self) -> None:
        """Every module read back off the panel, at its own centre."""
        size = 2.0
        pixels = round(size * PRINT_DPI)
        sheet = Sheet(pixels, pixels, background="#ffffff")
        draw_qr(sheet, SURVEY_URL, 0, 0, size)
        matrix = qr_matrix(SURVEY_URL)
        step = pixels / len(matrix)
        image = sheet.image.convert("L")
        for row, line in enumerate(matrix):
            for column, is_dark in enumerate(line):
                pixel = image.getpixel(
                    (
                        round(step * (column + 0.5)),
                        round(step * (row + 0.5)),
                    )
                )
                self.assertEqual(
                    pixel < 128,
                    is_dark,
                    f"module {row},{column} came out wrong",
                )


class PanelRenderTests(unittest.TestCase):
    """Every panel renders, at the size the printer is told to expect."""

    def assert_size(self, image, inches_wide: float, inches_high: float) -> None:
        self.assertEqual(
            image.size,
            (round(inches_wide * PRINT_DPI), round(inches_high * PRINT_DPI)),
        )

    def test_the_box_panels(self) -> None:
        side, _, depth = box_inches()
        self.assert_size(render_box_cover(), side, side)
        self.assert_size(render_box_side(), side, depth)
        self.assert_size(render_box_bottom(), side, side)

    def test_the_sale_sheet_is_a_letter_page(self) -> None:
        self.assert_size(render_sale_sheet(), *PAPERS[box_art.SALE_SHEET_PAPER])

    def test_the_sale_sheet_prints_the_contact_it_is_given(self) -> None:
        # Nothing here can read the words back off the page; what it
        # holds is that a contact line is not quietly dropped for want
        # of room, which is what the empty rule is there for.
        with_contact = render_sale_sheet(contact=("you@example.com",))
        self.assertNotEqual(
            with_contact.tobytes(), render_sale_sheet().tobytes()
        )

    def test_the_playtest_card(self) -> None:
        width, height = PLAYTEST_CARD_INCHES
        self.assert_size(render_playtest_card_front(), width, height)
        self.assert_size(render_playtest_card_back(), width, height)

    def test_a_bled_panel_is_bigger_than_the_trimmed_one(self) -> None:
        trimmed = render_box_side()
        bled = render_box_side(bleed=True)
        self.assertEqual(
            bled.width - trimmed.width, round(BLEED_INCHES * PRINT_DPI) * 2
        )


if __name__ == "__main__":
    unittest.main()
