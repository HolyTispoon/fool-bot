"""
The Codex pictures render: a picture of the expected size for the
opening position in both layouts, a hand and a codex view, each WebP
(`render.WEBP_QUALITY`) -- and nothing about how they look, which is
for the eye (`scripts/render_codex_sample.py`; docs/design/codex.md,
"The board on Discord").
"""

import io
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image, ImageChops, ImageFont

from codex import render
from codex.cards import Card
from codex.components import PATROL_SLOTS, MatchState, hero_ref
from codex.engine import RulesEngine
from codex.flow import board
from tests.codex_positions import hero_in_play, put


def size(png: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(png)) as picture:
        return picture.size


def panel_height(rows: int) -> int:
    """A panel's height with `rows` rows of cards under its patrol zone."""
    body = render.PATROL_HEIGHT + render.CELL_GAP + rows * render.CELL + (rows - 1) * render.CELL_GAP
    return 2 * render.PADDING + body + render.NAMEPLATE_GAP + render.NAMEPLATE_HEIGHT


class RenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = RulesEngine(seed=7)
        cls.match = cls.engine.new_match(("bashing", "finesse"), first=1)

    def panel_height(self, rows: int) -> int:
        return panel_height(rows)

    def test_the_panel_is_the_mats_width(self) -> None:
        """The building column, the command zone -- a slot per hero --
        and the five patrol slots: 2608 in the standard game, its grid
        six columns under them; 2114 in the basic, whose grid is five
        columns, a little wider than its top row (`MIN_GRID_COLUMNS`) --
        2004 and 1625 at a scale of 1, drawn at `DRAW_SCALE`'s 1.3."""
        self.assertEqual(render.DRAW_SCALE, 1.3)
        self.assertEqual((render.panel_width(1), render.panel_width(3)), (2114, 2608))
        self.assertEqual((render.grid_columns(1), render.grid_columns(3)), (5, 6))
        panel = render.render_panel(self.match, 1, "a", self.engine.catalog)
        self.assertEqual(panel.size, (render.panel_width(1), self.panel_height(1)))

    def test_the_heroes_share_one_command_zone(self) -> None:
        """A standard panel is as wide empty as the mat, and its heroes
        in the command zone take no cell of the grid."""
        match = self.engine.new_match((("anarchy", "blood", "fire"),
                                       ("balance", "feral", "growth")), first=1)
        panel = render.render_panel(match, 1, "a", self.engine.catalog)
        self.assertEqual(panel.size, (render.panel_width(3), self.panel_height(1)))
        self.assertEqual(render.grid_cells(match.player(1), self.engine.catalog), [])

    def test_the_building_column_is_one_rows_height(self) -> None:
        """The add-on, the three tech buildings and the base stand as
        tall as the patrol zone and one row, so they never make a panel
        taller than its grid."""
        one_row = render.PATROL_HEIGHT + render.CELL_GAP + render.CELL
        self.assertEqual(render.BUILDING_COLUMN_HEIGHT, one_row)

    def test_the_worker_card_is_the_starting_decks_colour(self) -> None:
        """x4 for the seat that went first and x5 for the other, in the
        starting deck's colour where that face is imported, and the
        neutral card where it is not."""
        self.assertEqual(render.worker_face("neutral", True), ("workers", "worker_x4.png"))
        self.assertEqual(render.worker_face("neutral", False), ("workers", "worker_x5.png"))
        with mock.patch.object(render, "bundled", return_value=False):
            self.assertEqual(render.worker_face("red", True), ("workers", "worker_x4.png"))
        # Every colour's two are imported.
        for color in ("black", "blue", "green", "purple", "red", "white"):
            self.assertEqual((render.worker_face(color, True), render.worker_face(color, False)),
                             (("worker_colors", f"{color}_x4.png"),
                              ("worker_colors", f"{color}_x5.png")))

    def test_a_row_more_is_a_taller_panel(self) -> None:
        match = self.engine.new_match(("bashing", "finesse"), first=1)
        # One more than a row of `grid_columns(1)` holds beside the
        # worker card, which takes the first cell: the hero is in the
        # command zone, not the grid.
        for _ in range(render.grid_columns(1)):
            match.new_instance("older_brother", 1)
        panel = render.render_panel(match, 1, "a", self.engine.catalog)
        self.assertEqual(panel.height, self.panel_height(2))

    def test_the_opening_board_stacked(self) -> None:
        png = render.render_board(self.match, "stacked", {1: "a", 2: "b"}, self.engine.catalog)
        self.assertEqual((png[:4], png[8:12]), (b"RIFF", b"WEBP"))
        height = 2 * self.panel_height(1) + render.DIVIDER_HEIGHT
        self.assertEqual(size(png), (render.panel_width(1), height))

    def test_the_board_says_where_its_cards_are(self) -> None:
        """`render_board_mapped` draws the same bytes as `render_board`,
        and a box for every card it shows -- the near panel's in the
        board's lower half, the far one's, turned, in its upper -- each
        inside the picture, and a box for each tech building with the
        codex cards it opens."""
        match = self.engine.new_match(("bashing", "finesse"), first=1)
        near = match.active
        far = 3 - near
        match.new_instance("older_brother", near)
        tired = match.new_instance("iron_man", near)
        tired.exhausted = True
        match.new_instance("nimble_fencer", far)
        names = {1: "a", 2: "b"}
        webp, drawn = render.render_board_mapped(match, "stacked", names, self.engine.catalog)
        self.assertEqual(webp, render.render_board(match, "stacked", names, self.engine.catalog))
        self.assertEqual((drawn["width"], drawn["height"]), size(webp))
        middle = drawn["height"] / 2
        shown = [(region["card"], region["box"][1] > middle)
                 for region in drawn["regions"] if "card" in region]
        # The heroes too, in the command zones.
        self.assertCountEqual(shown, [("older_brother", True), ("iron_man", True),
                                      ("nimble_fencer", False),
                                      (match.player(near).heroes[0].slug, True),
                                      (match.player(far).heroes[0].slug, False)])
        for region in drawn["regions"]:
            left, top, right, bottom = region["box"]
            self.assertTrue(0 <= left < right <= drawn["width"], region)
            self.assertTrue(0 <= top < bottom <= drawn["height"], region)
        (iron_man,) = [region["box"] for region in drawn["regions"] if region.get("card") == "iron_man"]
        # Exhausted, it lies on its side: wider than tall.
        self.assertGreater(iron_man[2] - iron_man[0], iron_man[3] - iron_man[1])
        # A basic game's duel: every tech building opens its side's whole
        # codex, Tech I too.
        codexes = [region for region in drawn["regions"] if "codex" in region]
        self.assertEqual(len(codexes), 6)
        catalog = self.engine.catalog
        whole = {f"{spec.title()} codex": [card.slug for card in catalog.by_spec(spec)]
                 for spec in (match.player(near).specs[0], match.player(far).specs[0])}
        for region in codexes:
            self.assertEqual(region["codex"], whole[region["title"]])

    def test_a_tech_i_building_opens_its_tech_i_cards_beyond_a_basic_duel(self) -> None:
        """In a standard game, Tech I opens the tech I cards of every spec
        the side has -- never a spell, which prints no tech level -- and
        Tech II and III the spec chosen at Tech II, or nothing before."""
        catalog = self.engine.catalog
        specs = ("anarchy", "blood", "fire")
        match = self.engine.new_match((specs, ("balance", "feral", "growth")), first=1)
        player = match.player(1)
        title, codex = render.tech_codex(player, "tech1", catalog)
        self.assertEqual(title, "Tech I cards: Anarchy, Blood, Fire")
        self.assertEqual(codex, [card.slug for spec in specs for card in catalog.by_spec(spec)
                                 if card.tech_level == 1])
        self.assertFalse([slug for slug in codex if catalog.cards[slug].is_spell])
        self.assertIsNone(render.tech_codex(player, "tech2", catalog))
        player.tech2_spec = "fire"
        self.assertEqual(render.tech_codex(player, "tech3", catalog),
                         ("Fire codex", [card.slug for card in catalog.by_spec("fire")]))

    def test_the_stacked_board_is_seen_from_the_active_players_side(self) -> None:
        """The active player's panel is the lower one -- its nameplate's
        rule in its first hero's colour, Neutral's tan in the basic game
        -- whichever seat is active, and the other player's the upper."""
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
            self.assertEqual(board.getpixel(lower_rule)[:3],
                             render.TURN_COLORS["neutral"][0])

    def test_a_table_of_three_stacks_every_panel_upright(self) -> None:
        """A free-for-all's board (docs/codex-multiplayer.md, decision 14):
        three panels, the active player's at the bottom under the divider,
        the other two above it upright -- nothing turned."""
        match = self.engine.new_match(("bashing", "finesse", "bashing"), first=1,
                                      variant="free_for_all")
        match.active = 2
        board = render.compose_board(match, "stacked", {1: "a", 2: "b", 3: "c"}, self.engine.catalog)
        panel = self.panel_height(1)
        self.assertEqual(board.height, 3 * panel + render.TABLE_GAP + render.DIVIDER_HEIGHT)
        lower_rule = (render.PADDING + 5, board.height - render.PADDING - render.NAMEPLATE_HEIGHT + 1)
        self.assertEqual(board.getpixel(lower_rule)[:3], render.TURN_COLORS["neutral"][0])
        # Upright: the top panel's nameplate is at its foot, not its head.
        upper_rule = (render.PADDING + 5, panel - render.PADDING - render.NAMEPLATE_HEIGHT + 1)
        self.assertEqual(board.getpixel(upper_rule)[:3], render.RULE)

    def test_a_free_for_all_side_by_side_is_rows_of_two(self) -> None:
        """The author, 2026-10-14: side by side, a free-for-all is rows of
        two panels from the bottom -- three players one above two, four two
        above two, five three rows with one at the top."""
        panel = self.panel_height(1)
        width = 2 * render.compose_board(
            self.engine.new_match(("bashing", "finesse"), first=1), "stacked", {}, self.engine.catalog,
        ).width + render.TABLE_GAP
        for count, rows in ((3, 2), (4, 2), (5, 3)):
            with self.subTest(players=count):
                match = self.engine.new_match(("bashing", "finesse", "bashing", "finesse", "bashing")[:count],
                                              first=1, variant="free_for_all")
                board = render.compose_board(match, "side_by_side", {}, self.engine.catalog)
                self.assertEqual(board.width, width)
                self.assertEqual(board.height, rows * panel + (rows - 2) * render.TABLE_GAP
                                 + render.DIVIDER_HEIGHT)

    def test_a_free_for_all_divider_names_the_next_turn(self) -> None:
        """The author, 2026-10-20: a free-for-all's divider names whose
        turn is next beside the turn's pill -- every table size, both
        views -- and nobody once the game is over."""
        from unittest import mock
        for count in (3, 4, 5):
            for layout in ("stacked", "side_by_side"):
                with self.subTest(players=count, layout=layout):
                    match = self.engine.new_match(("bashing", "finesse", "bashing", "finesse", "bashing")[:count],
                                                  first=1, variant="free_for_all")
                    names = {seat: f"p{seat}" for seat in range(1, count + 1)}
                    with mock.patch.object(render, "horizontal_divider",
                                           wraps=render.horizontal_divider) as divider:
                        render.compose_board(match, layout, names, self.engine.catalog)
                    self.assertEqual(divider.call_args.args[3], "p2")
                    # Side by side, over the panel right of the active
                    # player's -- the board's right half; stacked, beside
                    # the turn's pill.
                    upcoming_centre = divider.call_args.args[4]
                    if layout == "side_by_side":
                        self.assertGreater(upcoming_centre, divider.call_args.args[0] / 2)
                    else:
                        self.assertIsNone(upcoming_centre)
        match = self.engine.new_match(("bashing", "finesse", "bashing"), first=1, variant="free_for_all")
        match.winner = 1
        with mock.patch.object(render, "horizontal_divider", wraps=render.horizontal_divider) as divider:
            render.compose_board(match, "side_by_side", {}, self.engine.catalog)
        self.assertIsNone(divider.call_args.args[3])

    def test_the_next_pill_fits_the_divider(self) -> None:
        """A long name is cut with an ellipsis rather than run off the rule."""
        width = 1000
        strip = render.horizontal_divider(width, "A'S TURN 1", upcoming="x" * 32)
        self.assertEqual(strip.size, (width, render.DIVIDER_HEIGHT))
        middle = render.DIVIDER_HEIGHT // 2
        # The rule shows at the right edge, so the pill stops short of it.
        self.assertEqual(strip.getpixel((width - 2, middle))[:3], render.QUIET)

    def test_the_far_panel_is_turned_round(self) -> None:
        """A turned panel's body is the upright one's rotated whole --
        all but the gold's count, drawn to read upright after -- and its
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
        near = near.rotate(180)
        # The coin, between the building column and the worker card, is
        # left out: its box in the upright body, turned round.
        coin = render.GOLD_COIN
        o = render.OVERHANG
        face_left = o + render.BUILDING_WIDTH + render.BUILDING_GAP + (render.CELL - render.CARD[0]) // 2
        left = round((o + render.BUILDING_WIDTH + face_left - coin) / 2)
        top = round(o + render.PATROL_HEIGHT + render.CELL_GAP + render.CELL
                    - render.TILE[1] / 2 - coin / 2)
        box = (near.width - left - coin - 1, near.height - top - coin - 1,
               near.width - left + 1, near.height - top + 1)
        for picture in (near, far):
            picture.paste((0, 0, 0, 0), box)
        self.assertEqual(far.tobytes(), near.tobytes())

    def test_the_opening_board_side_by_side(self) -> None:
        png = render.render_board(self.match, "side_by_side", {1: "a", 2: "b"}, self.engine.catalog)
        self.assertEqual(size(png), (render.panel_width(1) * 2 + render.DIVIDER_WIDTH,
                                     self.panel_height(1)))

    def test_a_hand(self) -> None:
        rows = self.engine.hand_rows(self.match, 1)
        png = render.render_hand([row.slug for row in rows], [row.allowed for row in rows],
                                 [row.cost for row in rows], self.engine.catalog)
        self.assertEqual((png[:4], png[8:12]), (b"RIFF", b"WEBP"))
        self.assertEqual(size(png)[0], 5 * (render.HAND_CARD[0] + 16) + 16)

    def test_the_same_hand_asked_again_is_not_drawn_again(self) -> None:
        """A panel edited in place, **My hand** clicked twice: the bytes
        already drawn (`RENDERED_KEPT`) -- and a hand differing in one
        cost is drawn anew."""
        rows = self.engine.hand_rows(self.match, 1)
        slugs, allowed = [row.slug for row in rows], [row.allowed for row in rows]
        costs = [row.cost for row in rows]
        first = render.render_hand(slugs, allowed, costs, self.engine.catalog)
        self.assertIs(render.render_hand(list(slugs), list(allowed), list(costs), self.engine.catalog),
                      first)
        cheaper = [max(0, costs[0] - 1)] + costs[1:] if costs[0] else [1] + costs[1:]
        self.assertNotEqual(render.render_hand(slugs, allowed, cheaper, self.engine.catalog), first)

    def test_a_standard_codex_groups_tech_ii_and_iii_and_the_spells_by_spec(self) -> None:
        """Every Tech I card, then each spec's Tech II and III, then each
        spec's spells with its ultimate last, each group spec by spec as
        the deck names them and then by cost (the author, 2026-10-10 and
        2026-10-12)."""
        engine = RulesEngine(seed=7)
        specs = ("fire", "anarchy", "blood")
        match = engine.new_match((specs, ("bashing", "finesse", "necromancy")), first=1)
        cards = [engine.catalog.cards[slug] for slug, _ in engine.codex_remaining(match, 1)]
        self.assertEqual(len(cards), 36)
        keys = [(3 if card.is_spell else min(card.tech_level, 2),
                 specs.index(card.spec.strip().lower()),
                 "Ultimate" in card.type if card.is_spell else card.tech_level, card.cost)
                for card in cards]
        self.assertEqual(keys, sorted(keys))
        self.assertEqual([key[1:3] for key in keys if key[0] == 3][3::4],
                         [(0, True), (1, True), (2, True)])

    def test_the_codex_keeps_its_places_as_cards_are_taken(self) -> None:
        """A card with no copies left keeps its place, at 0, so the grid
        stands still while a codex empties; and a view of one spec or one
        tech level is the whole codex's order narrowed, never re-sorted
        (the author, 2026-10-10)."""
        engine = RulesEngine(seed=7)
        match = engine.new_match((("fire", "anarchy", "blood"), ("bashing", "finesse", "necromancy")),
                                 first=1)
        player = match.player(1)
        whole = [slug for slug, _ in engine.codex_remaining(match, 1)]
        player.codex[whole[3]] = 0
        del player.codex[whole[10]]
        rows = engine.codex_remaining(match, 1)
        self.assertEqual([slug for slug, _ in rows], whole)
        self.assertEqual((rows[3][1], rows[10][1]), (0, 0))
        for view in engine.codex_views(player):
            shown = [slug for slug, _ in engine.codex_remaining(match, 1, view)]
            self.assertEqual(shown, [slug for slug in whole if slug in shown], view)

    def test_the_codex_is_laid_out_by_spec(self) -> None:
        """Where a codex is three specs: Tech I runs on, each spec's Tech
        II and III are a block two wide and three high, Tech III last,
        and each spec's four spells a block two wide, two on top and two
        below, the ultimate last, in the same two columns as its tech
        (the author, 2026-10-10, 2026-10-12 and 2026-10-20); the other
        views, and a spec's own, run on; Tech II's view holds Tech III's."""
        engine = RulesEngine(seed=7)
        match = engine.new_match((("fire", "anarchy", "blood"), ("bashing", "finesse", "necromancy")),
                                 first=1)
        rows = engine.codex_remaining(match, 1)
        places = engine.codex_places(rows, "everything")
        cards = [engine.catalog.cards[slug] for slug, _ in rows]
        self.assertEqual(len(set(places)), len(places))
        self.assertEqual({row for (row, _), card in zip(places, cards) if card.tech_level == 1}, {0})
        for spec in {card.spec for card in cards}:
            tech = [place for place, card in zip(places, cards)
                    if card.spec == spec and (card.tech_level or 0) >= 2]
            self.assertEqual(len({column for _, column in tech}), 2, spec)
            self.assertEqual(len({row for row, _ in tech}), 3, spec)
            self.assertEqual(engine.catalog.cards[rows[places.index(max(tech))][0]].tech_level,
                             3, spec)
            spells = [place for place, card in zip(places, cards)
                      if card.spec == spec and card.is_spell]
            self.assertEqual({column for _, column in spells}, {column for _, column in tech}, spec)
            self.assertEqual(len({row for row, _ in spells}), 2, spec)
        self.assertEqual(max(places), (5, 5))
        self.assertTrue("Ultimate" in cards[places.index((5, 5))].type)
        spells = engine.codex_remaining(match, 1, "spells")
        self.assertEqual(engine.codex_places(spells, "spells"),
                         tuple((row - 4, column) for row, column in places[-12:]))
        tech2 = engine.codex_remaining(match, 1, "tech2")
        self.assertEqual(engine.codex_places(tech2, "tech2"),
                         tuple((row - 1, column) for row, column in places[6:24]))
        self.assertEqual(len(tech2), 18)
        for view in ("tech1", "spec:fire"):
            shown = engine.codex_remaining(match, 1, view)
            self.assertEqual(engine.codex_places(shown, view),
                             tuple(divmod(index, 6) for index in range(len(shown))), view)
        png = render.render_codex([slug for slug, _ in rows], [count for _, count in rows],
                                  engine.catalog, None, places)
        self.assertEqual(size(png), (6 * (render.CODEX_CARD[0] + 14) + 14,
                                     6 * (render.CODEX_CARD[1] + 14) + 14))

    def test_a_codex_of_one_spec_runs_on(self) -> None:
        rows = self.engine.codex_remaining(self.match, 1)
        self.assertEqual(self.engine.codex_places(rows, "everything"),
                         tuple(divmod(index, 6) for index in range(len(rows))))

    def test_the_picture_is_as_big_as_the_places_it_uses(self) -> None:
        slugs = [slug for slug, _ in self.engine.codex_remaining(self.match, 1)][:4]
        png = render.render_codex(slugs, [2] * 4, self.engine.catalog, None,
                                  ((0, 0), (0, 1), (1, 0), (2, 1)))
        self.assertEqual(size(png), (2 * (render.CODEX_CARD[0] + 14) + 14,
                                     3 * (render.CODEX_CARD[1] + 14) + 14))

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


class DeckLayoutTests(unittest.TestCase):
    """`deck_layout`: **My deck**'s frames packed so the rows are filled
    (the author, 2026-10-15)."""

    def test_short_parts_share_a_row_and_wrap_to_fill_it(self) -> None:
        """Two in hand, seven discarded, three in the pile: one row two
        cards tall rather than three rows with gaps at their ends -- the
        hand's two side by side."""
        self.assertEqual(render.deck_layout([2, 7, 3]), [(2, [(0, 2), (1, 4), (2, 2)])])

    def test_two_cards_are_never_stacked(self) -> None:
        for sizes in ([2, 7, 3], [2, 2, 12, 9], [2, 20], [2], [5, 2, 2, 8]):
            for _, frames in render.deck_layout(sizes):
                for index, columns in frames:
                    if sizes[index] == 2:
                        self.assertEqual(columns, 2)

    def test_no_row_is_wider_than_the_limit_and_every_card_has_a_place(self) -> None:
        for sizes in ([5, 4, 3, 8], [5, 20], [1], [12, 12, 12, 12], [8, 8]):
            layout = render.deck_layout(sizes)
            self.assertEqual(sorted(i for _, frames in layout for i, _ in frames),
                             list(range(len(sizes))))
            for lines, frames in layout:
                self.assertLessEqual(sum(columns for _, columns in frames), render.DECK_COLUMNS)
                for index, columns in frames:
                    self.assertGreaterEqual(lines * columns, sizes[index])

    def test_a_hand_of_five_lies_in_a_row_where_it_can(self) -> None:
        layout = render.deck_layout([5, 4, 3, 8])
        self.assertIn((1, [(0, 5)]), layout)

    def test_the_picture_is_one_image_with_every_part(self) -> None:
        engine = RulesEngine(seed=7)
        match = engine.new_match(("bashing", "finesse"), first=1)
        put(match, 1, "older_brother")
        deck = engine.own_deck(match, 1)
        picture = Image.open(io.BytesIO(render.render_deck(
            deck.held, deck.played, deck.discarded, deck.pile, engine.catalog)))
        self.assertLessEqual(picture.width,
                             render.DECK_COLUMNS * (render.CODEX_CARD[0] + 14)
                             + 3 * (2 * render.DECK_BOX_PAD + 14) + 14)


class EffectTagTests(unittest.TestCase):
    """The lasting effects a unit or a hero carries, as tags: the
    effect's name alone, in the colour of the card it came from."""

    def setUp(self) -> None:
        self.cards = RulesEngine().catalog

    def unit(self, **fields):
        from codex.components import CardInstance
        card = CardInstance(id=1, slug="tiger_cub", owner=1, controller=1)
        for name, value in fields.items():
            setattr(card, name, value)
        return card

    def test_a_keyword_for_a_while_is_its_own_name(self) -> None:
        card = self.unit(modifiers=[
            {"kind": "keyword", "keyword": "Haste", "until": "end_of_turn", "from": "charge"},
            {"kind": "atk", "amount": 1, "until": "end_of_turn", "from": "charge"},
        ])
        self.assertEqual(render.effect_tags(card, self.cards), (("Haste", "red"),))

    def test_a_keyword_for_good_is_not_tagged(self) -> None:
        card = self.unit(modifiers=[{"kind": "keyword", "keyword": "Haste", "until": None}])
        self.assertEqual(render.effect_tags(card, self.cards), ())

    def test_the_same_name_twice_is_one_tag(self) -> None:
        card = self.unit(modifiers=[
            {"kind": "keyword", "keyword": "Haste", "until": "end_of_turn", "from": "charge"},
            {"kind": "keyword", "keyword": "Haste", "until": "end_of_turn", "from": "now"},
        ])
        self.assertEqual(len(render.effect_tags(card, self.cards)), 1)

    def test_an_effect_across_a_side_is_its_cards_name(self) -> None:
        self.assertEqual(render.effect_tags(self.unit(), self.cards, ("ferocity", "dreamscape")),
                         (("Ferocity", "green"), ("Dreamscape", "blue")))

    def test_a_unit_barred_from_attacking_and_patrolling_is_tagged_by_what_bars_it(
            self) -> None:
        self.assertEqual(render.effect_tags(self.unit(), self.cards, barred_by="entangling_vines"),
                         (("Entangled", "white"),))
        self.assertEqual(render.effect_tags(self.unit(), self.cards,
                                            barred_by="terras_q_the_shackled"),
                         (("Shackled", "black"),))

    def test_gargoyles_effects_are_one_tag(self) -> None:
        until = {"until": "upkeep", "seat": 1, "from": "gargoyle"}
        card = self.unit(modifiers=[{"kind": "lose_keyword", "keyword": "Indestructible", **until},
                                    {"kind": "keyword", "keyword": "Flying", **until},
                                    {"kind": "unbound", **until}])
        self.assertEqual(render.effect_tags(card, self.cards), (("Not indestructible", "black"),))

    def test_rampant_growth_is_tagged_by_name(self) -> None:
        card = self.unit(modifiers=[{"kind": "atk", "amount": 2, "until": "end_of_turn",
                                     "from": "rampant_growth"}])
        self.assertEqual(render.effect_tags(card, self.cards), (("Rampant Growth", "green"),))

    def test_dinosize_is_tagged_by_name(self) -> None:
        card = self.unit(modifiers=[{"kind": "atk", "amount": 6, "until": "end_of_turn",
                                     "from": "dinosize"}])
        self.assertEqual(render.effect_tags(card, self.cards), (("Dinosize", "green"),))

    def test_a_kidnapped_unit_is_kidnapped_alone(self) -> None:
        card = self.unit(returns_to=2, modifiers=[
            {"kind": "keyword", "keyword": "Haste", "until": "end_of_turn", "from": "kidnapping"}])
        self.assertEqual(render.effect_tags(card, self.cards), (("Kidnapped", "red"),))

    def test_a_lost_keyword_is_not_it(self) -> None:
        card = self.unit(modifiers=[{"kind": "lose_keyword", "keyword": "Flying",
                                     "until": "end_of_turn", "from": "crypt_crawler"}])
        self.assertEqual(render.effect_tags(card, self.cards), (("Not flying", "black"),))

    def test_an_older_saves_modifier_is_tagged_without_a_colour(self) -> None:
        card = self.unit(modifiers=[{"kind": "doomed", "until": "doom", "seat": 1}])
        self.assertEqual(render.effect_tags(card, self.cards), (("Doomed", None),))

    def test_prynn_names_each_unit_she_has_trashed_saying_trashed_once(self) -> None:
        from codex.components import HeroState
        prynn = HeroState(slug="prynn_pasternaak", trashed=[
            {"slug": "iron_man", "owner": 2, "controller": 2, "id": 4},
            {"slug": "tiger_cub", "owner": 2, "controller": 2, "id": 5},
        ])
        self.assertEqual(render.rune_marks(prynn, self.cards),
                         (("Trashed: Iron Man", "purple"), ("Tiger Cub", "purple")))

    def test_a_long_trashed_name_is_cut_to_the_cards_width(self) -> None:
        from codex.components import HeroState
        prynn = HeroState(slug="prynn_pasternaak", trashed=[
            {"slug": "jefferson_degrey_ghostly_diplomat", "owner": 2, "controller": 2, "id": 4}])
        (tag, _), = render.rune_marks(prynn, self.cards)
        self.assertTrue(tag.startswith("Trashed: Jefferson") and tag.endswith("…"))
        self.assertLessEqual(render.tag_size(tag)[0], render.CARD[0])


class PreloadTests(unittest.TestCase):
    """Every file a picture is drawn from, read into memory once, so no
    click reads the host's disk (docs/design/codex.md, "The board on
    Discord")."""

    def test_the_pictures_are_read_into_memory_once(self) -> None:
        files, size = render.preload_pictures()
        self.assertGreaterEqual(files, 440)
        self.assertGreater(size, 40 * 2 ** 20)
        cards = RulesEngine().catalog
        for slug in ("trojan_duck", "troq_bashar", "dancer", "worker_x5", "tower"):
            self.assertIn(str(cards.by_slug(slug).picture), render._BUNDLED)
        self.assertIn(str(render.BOARD_IMAGE_DIR / "ground" / "leather.png"), render._BUNDLED)
        self.assertIn(str(render.EMOJI_DIR / "gold.png"), render._BUNDLED)
        for name in render.FONT_FILES:
            self.assertIn(str(render.FONT_DIR / name), render._BUNDLED)
        # The sheets the pieces were cut from and the playmat are never
        # drawn, so they are not held.
        self.assertFalse([key for key in render._BUNDLED if "sheets" in key or "playmat" in key])
        # Read once: a second preload reads nothing from the disk.
        with mock.patch.object(Path, "read_bytes", side_effect=AssertionError("read the disk")):
            self.assertEqual(render.preload_pictures(), (files, size))

    def test_no_render_reads_the_disk_once_preloaded(self) -> None:
        """The hand, the codex and the board drawn from memory alone:
        with every cache cleared, every picture and font is opened from
        the bytes held, and a read of the disk fails the test."""
        render.preload_pictures()
        engine = RulesEngine(seed=7)
        match = engine.new_match(("bashing", "finesse"), first=1)
        for cached in (render.font, render._image, render._scaled_card,
                       render._render_hand, render._render_codex):
            cached.cache_clear()
        rows = engine.hand_rows(match, 1)
        codex = engine.codex_remaining(match, 1)
        with mock.patch.object(Path, "read_bytes", side_effect=AssertionError("read the disk")), \
                mock.patch("PIL.Image.open", wraps=Image.open) as opened, \
                mock.patch("PIL.ImageFont.truetype", wraps=ImageFont.truetype) as faces:
            render.render_hand([row.slug for row in rows], [row.allowed for row in rows],
                               [row.cost for row in rows], engine.catalog)
            render.render_codex([slug for slug, _ in codex], [count for _, count in codex],
                                engine.catalog)
            render.render_board(match, "stacked", {1: "a", 2: "b"}, engine.catalog)
        self.assertTrue(opened.call_args_list)
        self.assertTrue(all(isinstance(call.args[0], io.BytesIO) for call in opened.call_args_list))
        self.assertTrue(faces.call_args_list)
        self.assertTrue(all(isinstance(call.args[0], io.BytesIO) for call in faces.call_args_list))

    def test_a_card_whose_picture_is_missing_is_the_back(self) -> None:
        """`bundled` asks the disk only for what is not held, and a card
        whose picture is nowhere is drawn as the card back."""
        back = render.BOARD_IMAGE_DIR / "backs" / "card.png"
        render.bundled_bytes(back)
        with mock.patch.object(Path, "is_file", return_value=False):
            self.assertTrue(render.bundled(back))
            self.assertFalse(render.bundled(Path("/nonexistent/trojan_duck.jpg")))
        cards = RulesEngine().catalog
        nowhere = mock.PropertyMock(return_value=Path("/nonexistent/trojan_duck.jpg"))
        with mock.patch.object(Card, "picture", nowhere):
            picture = render.card_picture("trojan_duck", cards)
        self.assertEqual(picture.size, render.image(back).size)


class CodexViewTests(unittest.TestCase):
    """The engine's answer the Codex menu shows."""

    def test_each_view_narrows_the_codex(self) -> None:
        engine = RulesEngine(seed=7)
        match = engine.new_match(("bashing", "finesse"), first=1)
        everything = engine.codex_remaining(match, 1, "everything")
        self.assertEqual(len(everything), 12)
        self.assertIn("trojan_duck", {slug for slug, _ in engine.codex_view_rows(everything, "tech2")})
        self.assertEqual(len(engine.codex_view_rows(everything, "tech2")), 6)
        self.assertEqual(len(engine.codex_view_rows(everything, "spells")), 4)
        self.assertEqual(sum(len(engine.codex_view_rows(everything, view))
                             for view in ("tech1", "tech2", "spells")), 12)
        # A basic codex is shown whole, always: nothing narrower is offered
        # for it (the author, 2026-10-20).
        for view in ("tech1", "tech2", "spells"):
            with self.assertRaises(ValueError):
                engine.codex_remaining(match, 1, view)

    def test_a_tech_level_is_every_card_printed_with_it(self) -> None:
        """A Tech II building or upgrade is a Tech II card as much as a
        unit is, and Tech III's are in Tech II's view (the author,
        2026-10-12): the three views together are every spec's whole
        codex, and a card is in exactly one of them."""
        engine = RulesEngine(seed=7)
        catalog = engine.catalog
        for spec in sorted({card.spec for card in catalog.cards.values() if card.spec}):
            rows = tuple((slug, 2) for slug in dict.fromkeys(catalog.codex_for(spec)))
            with self.subTest(spec=spec):
                self.assertEqual(len(rows), 12)
                parts = [engine.codex_view_rows(rows, view)
                         for view in ("tech1", "tech2", "spells")]
                self.assertEqual(sorted(slug for part in parts for slug, _ in part),
                                 sorted(slug for slug, _ in rows))
                self.assertEqual(engine.codex_view_rows(rows, "everything"), rows)
        anarchy = tuple((slug, 2) for slug in dict.fromkeys(catalog.codex_for("anarchy")))
        tech2 = {slug for slug, _ in engine.codex_view_rows(anarchy, "tech2")}
        self.assertTrue(any(catalog.cards[slug].kind == "card" and not catalog.cards[slug].is_unit
                            for slug in tech2), "Anarchy's Tech II building is a Tech II card")

    def test_a_spec_view_is_its_own_twelve(self) -> None:
        """The standard game's menu: one view per spec of the deck. The
        basic game's deck is one spec, shown whole, always: Everything
        alone (the author, 2026-10-20)."""
        from codex.engine import CODEX_VIEWS, spec_view
        from codex.formatting import codex_view_name
        engine = RulesEngine(seed=7)
        match = engine.new_match(("bashing", "finesse"), first=1)
        self.assertEqual(engine.codex_views(match.player(1)), ("everything",))
        standard = engine.new_match((("fire", "anarchy", "blood"), ("bashing", "finesse", "necromancy")),
                                    first=1)
        self.assertEqual(engine.codex_views(standard.player(1)),
                         CODEX_VIEWS + tuple(spec_view(spec) for spec in ("fire", "anarchy", "blood")))
        catalog = engine.catalog
        rows = tuple((slug, 2) for spec in ("bashing", "anarchy")
                     for slug in dict.fromkeys(catalog.codex_for(spec)))
        anarchy = engine.codex_view_rows(rows, spec_view("Anarchy"))
        self.assertEqual(len(anarchy), 12)
        self.assertTrue(all(catalog.cards[slug].spec == "Anarchy" for slug, _ in anarchy))
        self.assertEqual(codex_view_name(spec_view("Anarchy")), "Anarchy")
        self.assertEqual([codex_view_name(view) for view in CODEX_VIEWS],
                         ["Everything", "Tech I", "Tech II & III", "Spells"])
        with self.assertRaises(ValueError):
            engine.codex_remaining(match, 1, spec_view("bashing"))
        with self.assertRaises(ValueError):
            engine.codex_view_rows(rows, "tech4")

    def test_the_tech_pickers_opening_view(self) -> None:
        """In the standard game the picker opens on Tech I and the spells
        until a Tech II is built; then on its spec's Tech II and III and
        the spells. The basic game's codex opens whole, always, and its
        Show menu is Everything alone (the author, 2026-10-20)."""
        from codex.components import BuildingState
        from codex.engine import TECH1_SPELLS_VIEW, tech2_spec_view
        from codex.formatting import codex_view_name
        engine = RulesEngine(seed=7)
        basic = engine.new_match(("bashing", "finesse"), first=1).player(1)
        self.assertEqual(engine.tech_opening_view(basic), "everything")
        self.assertEqual(engine.tech_views(basic), ("everything",))
        basic.buildings["tech2"] = BuildingState(hp=5)
        self.assertEqual(engine.tech_opening_view(basic), "everything")
        self.assertEqual(engine.tech_views(basic), ("everything",))
        match = engine.new_match((("fire", "anarchy", "blood"), ("bashing", "finesse", "necromancy")),
                                 first=1)
        player = match.player(1)
        self.assertEqual(engine.tech_opening_view(player), TECH1_SPELLS_VIEW)
        self.assertEqual(engine.tech_views(player)[0], TECH1_SPELLS_VIEW)
        self.assertEqual(engine.tech_views(player)[1:], engine.codex_views(player))
        self.assertEqual(codex_view_name(TECH1_SPELLS_VIEW), "Tech I & Spells")
        player.buildings["tech2"] = BuildingState(hp=5)
        player.tech2_spec = "anarchy"
        self.assertEqual(engine.tech_opening_view(player), tech2_spec_view("anarchy"))
        self.assertEqual(codex_view_name(tech2_spec_view("anarchy")), "Anarchy Tech II & III, Spells")
        catalog = engine.catalog
        rows = tuple((slug, 2) for spec in ("bashing", "anarchy")
                     for slug in dict.fromkeys(catalog.codex_for(spec)))
        early = engine.codex_view_rows(rows, TECH1_SPELLS_VIEW)
        self.assertEqual(sorted(early),
                         sorted(engine.codex_view_rows(rows, "tech1") + engine.codex_view_rows(rows, "spells")))
        late = engine.codex_view_rows(rows, tech2_spec_view("Anarchy"))
        self.assertEqual(sorted(late), sorted(
            tuple(row for row in engine.codex_view_rows(rows, "tech2")
                  if catalog.cards[row[0]].spec == "Anarchy")
            + engine.codex_view_rows(rows, "spells")))
        self.assertEqual(len(engine.codex_places(late, tech2_spec_view("Anarchy"))), len(late))
        # Nothing left to pick there: the picker opens on the whole codex,
        # and the focused view stays first on its Show menu.
        player.codex = {slug: 0 for slug in player.codex}
        self.assertEqual(engine.tech_opening_view(player), "everything")
        self.assertEqual(engine.tech_views(player)[0], tech2_spec_view("anarchy"))

    def test_nothing_is_playable_off_the_main_phase(self) -> None:
        engine = RulesEngine(seed=7)
        match = engine.new_match(("bashing", "finesse"), first=1)
        self.assertFalse(any(row.allowed for row in engine.hand_rows(match, 2)))


    def test_the_stats_are_what_stands_against_what_is_printed(self) -> None:
        """A unit's and a hero's pill: the engine's ATK and HP, HP less its
        damage, each marked changed where it is not what the face prints
        (a hero's, its level's band) -- and none for a spell, or with no
        engine reading handed in (docs/design/codex.md, "The board on
        Discord")."""
        from tests.codex_positions import hero_in_play, put
        engine = RulesEngine(seed=7)
        match = engine.new_match(("bashing", "finesse"), first=1)
        cards, stats_of = engine.catalog, engine.body_stats
        brother = put(match, 1, "older_brother")
        self.assertEqual(render.shown_stats(match, brother, cards, stats_of),
                         render.Stats(2, 2, False, False))
        brother.damage = 1
        self.assertEqual(render.shown_stats(match, brother, cards, stats_of),
                         render.Stats(2, 1, False, True))
        brother.plus_runes = 1
        self.assertEqual(render.shown_stats(match, brother, cards, stats_of),
                         render.Stats(3, 2, True, False))
        brother.armor = 1
        self.assertEqual(render.shown_stats(match, brother, cards, stats_of),
                         render.Stats(3, 2, True, False, 1))
        # The shield goes after the HP, so the pill is wider with armor.
        self.assertGreater(render.stat_pill(render.Stats(3, 2, True, False, 1)).width,
                           render.stat_pill(render.Stats(3, 2, True, False)).width)
        self.assertIsNone(render.shown_stats(match, brother, cards, None))
        self.assertIsNone(render.shown_stats(match, put(match, 2, "harmony"), cards, stats_of))
        hero_in_play(match, 1, level=5)
        hero = match.player(1).heroes[0]
        band = cards.heroes[hero.slug].band(5)
        self.assertEqual(render.shown_stats(match, hero, cards, stats_of),
                         render.Stats(band.atk, band.hp, False, False))
        panel = render.render_panel(match, 1, "a", cards, stats=stats_of)
        self.assertEqual(panel.width, render.panel_width(1))


def slot_tile(hero_count: int, slot: str) -> tuple[int, int, int, int]:
    """Where a patroller's tile lies on an upright panel of a side with
    `hero_count` heroes: the card's box in `slot`'s holder, as
    `render_body` lays the row out, grown to the square `lying_card`
    returns, centred on it -- every chit and tag a patroller carries is
    inside that square."""
    index = PATROL_SLOTS.index(slot)
    edge = render.PADDING - render.OVERHANG   # the body's corner on the panel
    grid_left = render.OVERHANG + render.BUILDING_WIDTH + render.BUILDING_GAP
    holder_left = (grid_left + render.command_zone_width(hero_count) + render.ZONE_GAP
                   + index * (render.PATROL_HOLDER + render.PATROL_SLOT_GAP))
    card_left = holder_left + render.PATROL_PADDING
    card_top = render.OVERHANG + render.PATROL_PADDING
    tile = render.CELL + 2 * render.OVERHANG
    left = edge + card_left + (render.CARD[0] - tile) // 2
    top = edge + card_top + (render.CARD[1] - tile) // 2
    return (left, top, left + tile, top + tile)


#: What the frontend calls the three seats of `LentPatrollerTests`' table.
NAMES = {1: "perrytom", 2: "ann", 3: "bo"}


class LentPatrollerTests(unittest.TestCase):
    """A patroller lent at a free-for-all's lock (Rulebook p. 14) is
    drawn in the borrower's slot, tagged with its lender's name, and
    nowhere on its owner's side (docs/design/codex.md, "The board"
    under Multiplayer). Seat 3's hero is lent to seat 2 as technician."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = RulesEngine(seed=7)
        cls.cards = cls.engine.catalog

    def table(self) -> MatchState:
        """A free-for-all of three with seat 3's hero in play, in their
        grid, and a unit of seat 2's on the lookout."""
        match = self.engine.new_match(("bashing", "finesse", "fire"), first=1,
                                      variant="free_for_all")
        match.turn, match.phase = 13, "main"
        put(match, 2, "tenderfoot", patrol="lookout")
        hero_in_play(match, 3, level=2)
        return match

    def lent(self) -> MatchState:
        match = self.table()
        board.lend(match, 3, hero_ref(match.player(3).heroes[0].slug), 2, "technician")
        return match

    def panel(self, match: MatchState, seat: int) -> Image.Image:
        return render.render_panel(match, seat, NAMES[seat], self.cards,
                                   stats=self.engine.board_reading, names=NAMES)

    def test_a_lent_hero_is_drawn_in_the_borrowers_slot_and_nowhere_else(self) -> None:
        """The borrower's slot carries the hero (`MatchState.patrollers`,
        `hero_on`); both sides render at a panel's size; the borrower's
        panel is not the one without the loan; and the hero goes through
        `hero_lying` once, for the borrower, with its lender's name,
        never for its owner."""
        match = self.lent()
        jaina = match.player(3).heroes[0]
        self.assertEqual(match.patrollers(2)["technician"], f"3:{hero_ref(jaina.slug)}")
        for seat in (2, 3):
            with self.subTest(seat=seat):
                side = render.render_side(match, seat, NAMES[seat], self.cards,
                                          self.engine.board_reading, NAMES)
                self.assertEqual(size(side), (render.panel_width(1), panel_height(1)))
        with mock.patch.object(render, "hero_lying", wraps=render.hero_lying) as lying:
            borrower = self.panel(match, 2)
            self.assertEqual(len(lying.call_args_list), 1)
            self.assertIs(lying.call_args_list[0].args[0], jaina)
            self.assertEqual(lying.call_args_list[0].kwargs.get("lender"), "bo")
            lying.reset_mock()
            self.panel(match, 3)
            self.assertEqual(lying.call_args_list, [])
        self.assertNotEqual(borrower.tobytes(), self.panel(self.table(), 2).tobytes())

    def test_the_owners_side_is_the_same_panel_with_the_hero_gone(self) -> None:
        """The owner's panel with the hero lent differs from the one with
        the hero in the owner's own technician slot only inside that
        slot's tile, and there it is the empty slot."""
        lent = self.lent()
        home = self.table()
        home.player(3).heroes[0].patrol_slot = "technician"
        empty = self.table()
        panels = {name: self.panel(match, 3) for name, match in
                  (("lent", lent), ("home", home), ("empty", empty))}
        tile = slot_tile(1, "technician")
        # In RGB: an RGBA difference's `getbbox` trims by alpha alone, and
        # both panels are opaque everywhere.
        differs = ImageChops.difference(panels["lent"].convert("RGB"),
                                        panels["home"].convert("RGB")).getbbox()
        self.assertIsNotNone(differs)
        self.assertTrue(tile[0] <= differs[0] and tile[1] <= differs[1]
                        and differs[2] <= tile[2] and differs[3] <= tile[3], (tile, differs))
        self.assertEqual(panels["lent"].crop(tile).tobytes(), panels["empty"].crop(tile).tobytes())

    def test_a_lent_card_is_tagged_with_its_lenders_name(self) -> None:
        """"Lent from <name>", the name as the frontend spells it, on a
        lent unit (`CardInstance.lent`) as on a lent hero
        (`HeroState.lent_to`) -- "Lent" where the frontend gave no name,
        nothing while they are their owner's -- a tag that changes the
        card's tile; a Discord name's 32 characters cut to the card with
        an ellipsis."""
        match = self.lent()
        thief = put(match, 3, "brick_thief")
        self.assertIsNone(render.unit_lying(thief, False, self.cards, lender="bo").lent)
        board.lend(match, 3, thief.ref, 2, "elite")
        self.assertEqual(render.unit_lying(thief, False, self.cards, lender="bo").lent,
                         "Lent from bo")
        self.assertEqual(render.unit_lying(thief, False, self.cards).lent, "Lent")
        self.assertEqual(render.hero_lying(match.player(3).heroes[0], self.cards, lender="bo").lent,
                         "Lent from bo")
        self.assertIsNone(render.hero_lying(self.table().player(3).heroes[0], self.cards,
                                            lender="bo").lent)
        self.assertEqual(render.lent_tag("PerryTom"), "Lent from PerryTom")
        long = render.lent_tag("w" * 32)
        self.assertTrue(long.startswith("Lent from www") and long.endswith("…"), long)
        self.assertLessEqual(render.tag_size(long)[0], render.LENT_TAG_WIDTH)
        self.assertGreater(render.tag_size("Lent from " + "w" * 32)[0], render.LENT_TAG_WIDTH)
        marked = render.lying_card(render.Lying("brick_thief", lent="Lent from bo"), self.cards)
        self.assertNotEqual(marked.tobytes(),
                            render.lying_card(render.Lying("brick_thief"), self.cards).tobytes())


if __name__ == "__main__":
    unittest.main()
