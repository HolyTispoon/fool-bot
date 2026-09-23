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
import inspect
import unittest

from d12ball import box_art
from d12ball.box_art import (
    BANNER_INCHES,
    MEEPLE_PATH,
    NIGHT_COVER,
    PAGE_COVER,
    PAGE_URL,
    BOX_DEPTH_INCHES,
    CHARTER_LINE,
    DEFAULT_CLAIMS,
    COVER_CAST,
    PLAYTEST_CARD_INCHES,
    PRINT_DPI,
    QR_MIN_MODULE_INCHES,
    SALE_SHEET_CARDS,
    SALE_SHEET_PLAYER_CARDS,
    SCREENTOP_BANNER_INCHES,
    SCREENTOP_BANNER_PIXELS,
    SURVEY_URL,
    STRAPLINE,
    BoxFacts,
    Panel,
    RetailClaims,
    board_photo,
    box_inches,
    cast_color,
    d12_art,
    d12_faces,
    draw_qr,
    flatten_path,
    folded_board_inches,
    meeple_outline,
    meeple_size,
    plain,
    qr_matrix,
    qr_module_inches,
    render_box_cover,
    render_banner,
    render_box_side,
    render_playtest_card_back,
    render_playtest_card_front,
    render_sale_sheet,
    retail_chips,
    sale_sheet_cards,
    sale_sheet_fan,
)
from d12ball.boards import BLEED_INCHES, DEFAULT_PAPER, PAPERS, Sheet
from d12ball.components import (
    TeamSide,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
    load_species_abilities,
)
from d12ball.game import COLOR_TEAMS, Team
from d12ball.render import ROLE_INITIALS, TEAM_COLORS, load_player_portrait
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

    def test_the_charters_own_line_is_the_books_words(self) -> None:
        self.assert_quoted(CHARTER_LINE)

    def test_the_strapline_is_the_one_line_in_its_own_voice(self) -> None:
        """
        The author's own (2026-09-23), and the only copy on any panel
        that is not quoted. It is allowed because it states no rule --
        it says how the game plays. Anything in it that reads as a
        rule would have to be quoted like everything else, so this
        test holds the shape of the exemption: one line, named, and
        not a sentence out of either book.
        """
        self.assertNotIn(STRAPLINE, self.text)
        self.assertNotIn(".", STRAPLINE)


class BoxFactsTests(unittest.TestCase):
    """Every number on these panels is the game's own."""

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


class RetailClaimsTests(unittest.TestCase):
    """
    A playing time and an age are the author's, not this code's.

    Nothing here measures either, so `RetailClaims()` carries nothing
    and prints nothing; what the panels show is `DEFAULT_CLAIMS`,
    which is what the author gave.
    """

    def test_nothing_is_claimed_without_one(self) -> None:
        self.assertEqual(RetailClaims().chips, ())

    def test_a_claim_becomes_a_chip(self) -> None:
        self.assertEqual(
            RetailClaims(play_minutes=(45, 60), minimum_age=12).chips,
            ("45-60 MINUTES", "AGES 12+"),
        )

    def test_one_number_is_not_printed_as_a_range(self) -> None:
        self.assertEqual(
            RetailClaims(play_minutes=(50, 50)).chips, ("50 MINUTES",)
        )

    def test_the_cover_carries_the_three_a_shopper_checks(self) -> None:
        self.assertEqual(
            retail_chips(BoxFacts.read(), DEFAULT_CLAIMS),
            ["2 PLAYERS", "30-45 MINUTES", "AGES 10+"],
        )


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

    def test_the_sale_sheet_points_at_the_games_own_page(self) -> None:
        """
        A second address, not the survey's: one asks how a game went,
        the other says what the game is. It is on the sheet so that a
        copy handed across a table is not a dead end when nobody has
        written a contact on the line.
        """
        self.assertTrue(PAGE_URL.startswith("https://"))
        self.assertNotEqual(PAGE_URL, SURVEY_URL)
        module = qr_module_inches(PAGE_URL, 1.0)
        self.assertGreaterEqual(
            module,
            QR_MIN_MODULE_INCHES,
            f"the sheet's QR modules are {module * 25.4:.2f}mm",
        )

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


class PrintedInWhiteTests(unittest.TestCase):
    """
    Nothing printed is flooded with ink.

    A dark cover is a solid across every panel of the wrap at once,
    which is the most expensive thing a print run can be asked for --
    the author's call, and the reason this whole set is drawn on
    white. A gradient or a scrim creeping back in is exactly the kind
    of change that looks fine on a screen and turns up on a quote, so
    the corners of every printed panel are checked for paper.
    """

    def assert_paper(self, image, panel: str) -> None:
        for corner in (
            (2, 2),
            (image.width - 3, 2),
            (2, image.height - 3),
            (image.width - 3, image.height - 3),
        ):
            pixel = image.convert("RGB").getpixel(corner)
            self.assertGreater(
                min(pixel),
                235,
                f"{panel} is inked into its corner at {corner}: {pixel}",
            )

    def test_every_printed_panel_is_paper_in_the_corners(self) -> None:
        self.assert_paper(render_box_cover(), "the cover")
        self.assert_paper(render_box_side(), "the side")
        self.assert_paper(render_sale_sheet(), "the sale sheet")
        self.assert_paper(render_playtest_card_front(), "the card front")
        self.assert_paper(render_playtest_card_back(), "the card back")

    def test_the_night_cover_is_the_one_that_is_not_printed(self) -> None:
        """It is for a screen, so it may flood -- and it is a different picture."""
        night = render_box_cover(palette=NIGHT_COVER)
        self.assertLess(min(night.convert("RGB").getpixel((2, 2))), 60)
        self.assertNotEqual(
            night.tobytes(), render_box_cover(palette=PAGE_COVER).tobytes()
        )


class DieTests(unittest.TestCase):
    """The d12 on these panels is the solid, not a twelve-sided badge."""

    def test_the_board_photo_draws_no_ball_of_its_own(self) -> None:
        """
        `boards.draw_kickoff_marks` already prints one on the kickoff
        space -- twelve-sided, with the ball's speed on it -- and a
        second one laid over it came out as two balls, the board's
        showing round the edge of this module's. The board is the
        thing being photographed, so the board's ball is the ball.
        """
        source = inspect.getsource(box_art.board_photo)
        self.assertNotIn("draw_d12", source)
        self.assertNotIn(
            "draw_d12", inspect.getsource(box_art.draw_meeples_on_board)
        )

    def test_the_ball_is_made_of_something(self) -> None:
        """
        It was white, which is what a d12 is in a dice shop and what
        nothing else in this game's art is: the balls in the players'
        own portraits are dark, dimpled things. The die is drawn as a
        material now, so nothing on it is paper-white.
        """
        art = d12_art(120)
        self.assertEqual(art.mode, "RGBA")
        opaque = [
            pixel[:3]
            for pixel in art.convert("RGBA").get_flattened_data()
            if pixel[3] > 250
        ]
        self.assertTrue(opaque)
        body = [
            pixel for pixel in opaque
            # The numerals are bone and are meant to be pale; what
            # must not be white is the die itself.
            if not (min(pixel) > 200)
        ]
        self.assertGreater(len(body), len(opaque) * 0.8)
        self.assertEqual(
            [pixel for pixel in opaque if pixel == (255, 255, 255)], []
        )

    def test_it_is_the_same_die_every_render(self) -> None:
        """
        The grain is hashed off each pixel rather than drawn from
        `random`, so a panel is the same bytes twice -- which is what
        lets a drawing change be checked by hash.
        """
        self.assertEqual(d12_art(64).tobytes(), d12_art(64).tobytes())

    def test_it_has_twelve_pentagons(self) -> None:
        faces = d12_faces()
        self.assertEqual(len(faces), 12)
        for _, corners in faces:
            self.assertEqual(len(corners), 5)

    def test_every_face_is_flat(self) -> None:
        """
        Five vertices on one plane, which is what says the face list is
        right: a dodecahedron built against the wrong dual has five
        vertices that are merely near each other, and comes out as a
        lump nobody recognises.
        """
        for normal, corners in d12_faces():
            depths = [
                sum(axis * part for axis, part in zip(normal, corner))
                for corner in corners
            ]
            self.assertAlmostEqual(min(depths), max(depths), places=6)

    def test_every_vertex_is_on_the_same_sphere(self) -> None:
        radii = {
            round(sum(axis ** 2 for axis in corner) ** 0.5, 6)
            for _, corners in d12_faces()
            for corner in corners
        }
        self.assertEqual(len(radii), 1)


class MeepleTests(unittest.TestCase):
    """What stands on the board in a picture of it is a piece with a role on it."""

    def test_the_outline_is_the_authors_own_path(self) -> None:
        """
        Flattened from `MEEPLE_PATH`, the path the Screentop table
        draws, rather than a silhouette redrawn from a screenshot --
        so a piece on a panel and a piece on the table are one shape.
        """
        outline = meeple_outline()
        self.assertGreater(len(outline), 200)
        self.assertEqual(outline[0], outline[-1], "the path is not closed")
        width, height = meeple_size()
        # The piece as the path draws it: a shade wider than it is
        # tall, arms out.
        self.assertAlmostEqual(width, 63.95, places=2)
        self.assertAlmostEqual(height, 59.24, places=2)

    def test_a_smooth_curve_reflects_the_control_point(self) -> None:
        """
        `S` is the one command in the path that is not self-contained:
        its first control point is the previous curve's second one,
        mirrored through the join. Read as if it carried its own, the
        outline kinks where the curves meet.
        """
        self.assertIn(" S ", MEEPLE_PATH)
        # After `C 0 10 10 10 10 0` the join is at (10, 0) with the
        # last control at (10, 10), so the reflection is (10, -10).
        smooth = flatten_path("M 0 0 C 0 10 10 10 10 0 S 20 -10 20 0")
        spelled = flatten_path(
            "M 0 0 C 0 10 10 10 10 0 C 10 -10 20 -10 20 0"
        )
        unreflected = flatten_path(
            "M 0 0 C 0 10 10 10 10 0 C 10 10 20 -10 20 0"
        )
        self.assertEqual(smooth, spelled)
        self.assertNotEqual(smooth, unreflected)

    def test_every_role_has_two_letters_to_wear(self) -> None:
        catalog = load_player_catalog()
        for definition in catalog.teams.values():
            for player in definition.players:
                self.assertIn(player.role.value, ROLE_INITIALS)

    def test_the_picture_is_the_printed_board_with_both_sides_on_it(self) -> None:
        photo = board_photo().convert("RGB")
        colors = {color for _, color in photo.getcolors(maxcolors=1 << 20)}
        for team in (Team.PURPLE, Team.TEAL):
            wanted = tuple(
                int(TEAM_COLORS[team][index:index + 2], 16)
                for index in (1, 3, 5)
            )
            self.assertIn(
                wanted,
                colors,
                f"no {team.value} meeple on the board picture",
            )


class SaleSheetCardsTests(unittest.TestCase):
    """The sheet is components, and the fan is not four of one monster."""

    def test_the_fan_holds_maneuver_cards_as_well(self) -> None:
        """
        A player card is who is on the field and a maneuver card is
        what they do; the sheet shows both rather than a row of one
        and a mention of the other.
        """
        cards = sale_sheet_fan(load_player_catalog(), load_maneuver_catalog())
        self.assertEqual(len(cards), SALE_SHEET_CARDS)
        self.assertGreater(len(cards), SALE_SHEET_PLAYER_CARDS)
        self.assertEqual({card.size for card in cards}, {(750, 1050)})

    def test_the_fan_is_drawn_from_every_colour_team(self) -> None:
        catalog = load_player_catalog()
        chosen = sale_sheet_cards(catalog)
        self.assertEqual(len(chosen), SALE_SHEET_CARDS)
        self.assertEqual(
            {team for _, team in chosen}, set(COLOR_TEAMS)
        )

    def test_the_fan_is_not_all_one_species(self) -> None:
        """
        A roster is grouped by species, so taking the first player of
        each team is four of the same monster -- which is what the
        first fan came out as.
        """
        species = {
            player.species for player, _ in sale_sheet_cards(load_player_catalog())
        }
        self.assertGreaterEqual(len(species), 3)

    def test_every_card_is_a_player_of_the_team_it_is_printed_for(self) -> None:
        catalog = load_player_catalog()
        for player, team in sale_sheet_cards(catalog):
            self.assertIn(player, catalog.teams[team].players)


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

    def test_the_banner_is_twice_a_notion_cover(self) -> None:
        banner = render_banner()
        self.assert_size(banner, *BANNER_INCHES)
        self.assertEqual(banner.size, (3000, 1200))

    def test_the_screentop_banner_is_what_that_table_asks_for(self) -> None:
        """1280 x 720 to the pixel, which is why the layout is in shares."""
        self.assertEqual(
            render_banner(size=SCREENTOP_BANNER_INCHES).size,
            SCREENTOP_BANNER_PIXELS,
        )

    def test_the_banner_is_the_covers_art_laid_out_wide(self) -> None:
        """Same palettes, different placement -- not a cropped cover."""
        self.assertNotEqual(
            render_banner(palette=PAGE_COVER).tobytes(),
            render_banner(palette=NIGHT_COVER).tobytes(),
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
