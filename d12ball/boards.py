"""
The three boards the physical game is played on: the **field board**,
the **jumbotron board**, and a coach's **team board**, print-ready.

They are the tabletop counterpart of the images the bot posts, and they
follow `d12ball/cards.py` rather than `d12ball/render.py`: a print goes
on paper, so the palette is the maneuver cards' -- dark ink on a light
face, in the same six colours -- and everything is measured in inches
at 300dpi with an optional bleed for a print shop to trim into. The
bot's own board is drawn dark because it is read on a screen; a dark
board is the wrong thing to hand a printer.

**The clock and the score are the jumbotron's**, exactly as they are
the jumbotron's on the bot's board: they are the state of the match
rather than the position, they want a cell a token can stand in, and
sharing the field board cost both of them room.

Everything the boards assert is read from the data the bot plays
from -- `basic_rules.json` for the layouts, the formations and the
coach's die, `maneuvers.json` for the six maneuvers, and `players.json`
for the roster -- so a printed board cannot claim a rule the bot does
not play, and an import reaches the boards by re-running
`scripts/render_boards.py`. The one thing deliberately left off is the
selection d6: maneuvers are chosen with the cards, so no die value is
printed anywhere here.

**Zones keep their real names on the team board.** A coach's own goal
is the home goal for one of them and the visitors goal for the other,
and the same board is printed for both, so the areas are labelled
HOME GOAL / MIDFIELD / VISITORS GOAL exactly as the field board and the
bot's coaching image label them. See "Working on the board image" in
CLAUDE.md for the same decision taken there.
"""
from dataclasses import dataclass
from typing import Optional, Sequence

from PIL import Image, ImageDraw, ImageFont

from d12ball.cards import (
    DEFENSE_COLOR,
    FACE_COLOR,
    INK,
    MUTED,
    OFFENSE_COLOR,
    PANEL_COLOR,
    PANEL_EDGE,
)
from d12ball.components import (
    BasicRuleset,
    BoardLayout,
    BoardState,
    ManeuverCatalog,
    ManeuverDefinition,
    PlayerCatalog,
    PlayerRole,
    TeamSide,
    Zone,
    kickoff_space_index,
)
from d12ball.game import Formation, Team
from d12ball.render import (
    TEAM_COLORS,
    ZONE_LABELS,
    draw_dashed_line,
    load_font,
    polygon_points,
    space_code,
)


PRINT_DPI = 300
# The bleed a print shop trims into, the same 1/8in the maneuver cards
# carry.
BLEED_INCHES = 0.125

# Sheet sizes in inches, portrait. The field board is drawn landscape
# and the team board portrait, which is what `sheet_pixels` swaps for.
#
# **A3 is the size these are designed at**, and the only one whose
# team board takes a real card: two rows of 3.5in cards plus a header
# and a footer is 11.3 inches, so tabloid -- wider, but 0.7in shorter
# -- comes out a card area short however the bands are trimmed, and A4
# is a proof to read rather than a board to lay cards on.
# `card_slot_inches` is what tells a caller which they have.
PAPERS: dict[str, tuple[float, float]] = {
    "a3": (11.69, 16.54),
    "a4": (8.27, 11.69),
    "tabloid": (11.0, 17.0),
    "letter": (8.5, 11.0),
}
DEFAULT_PAPER = "a3"

# Poker size, the maneuver cards' own -- the player cards share their
# proportions with it on the bot's board (CARD_SIZE is 110 x 154), so
# the areas that hold them are cut for it.
CARD_INCHES = (2.5, 3.5)
# Every area on the team board holds three: a zone holds three cards
# under 2-3-1 and 1-3-2, and the two benches hold three between the
# nine players and the six on the field.
CARDS_PER_AREA = 3

# The zone colours of the bot's board, lightened for paper. The bot
# draws them dark because they sit under white meeple labels on a
# screen; the same three hues at print weight keep a coach reading one
# board as the other.
ZONE_TINTS = {
    Zone.HOME_GOAL: "#dde5f1",
    Zone.MIDFIELD: "#dfe9e0",
    Zone.VISITORS_GOAL: "#f1e4d9",
}

# The clock is 15 space-minutes and stops there; the score track runs
# further than a match is ever likely to, because a shootout adds up to
# six goals to a side that was already level.
CLOCK_MINUTES = 15
SCORE_TRACK_MAX = 12
# Two rows of eight rather than one of sixteen. Sixteen across a sheet
# gives a cell an inch wide and a token needs to stand in it, which is
# what took these tracks off the field board in the first place.
CLOCK_COLUMNS = 8
# What a cell has to measure for a token to sit in it without covering
# its neighbours. A meeple's base is about half an inch.
MIN_TOKEN_INCHES = 0.75


def sheet_pixels(paper: str, landscape: bool) -> tuple[int, int]:
    if paper not in PAPERS:
        raise ValueError(
            f"Unknown paper size {paper!r}; expected one of "
            f"{', '.join(sorted(PAPERS))}."
        )
    short, long = PAPERS[paper]
    width, height = (long, short) if landscape else (short, long)
    return round(width * PRINT_DPI), round(height * PRINT_DPI)


class Sheet:
    """
    A printable sheet, drawn at its final resolution.

    Unlike `cards.Pen` this does not supersample: a board is tens of
    megapixels at 300dpi, where a card is under a megapixel, and a
    stepped edge a third of a tenth of a millimetre across is not
    visible in a print.

    Lengths are given in **units of a thousandth of the sheet's width**,
    which is what makes one layout serve every paper size: `u(12)` is
    the same fraction of an A4 sheet as of an A3 one, so a board scales
    whole rather than being re-laid-out per size.
    """

    def __init__(
        self,
        width: int,
        height: int,
        background: str = FACE_COLOR,
    ) -> None:
        self.width = width
        self.height = height
        self.background = background
        self.unit = width / 1000
        self._image: Optional[Image.Image] = None
        self._draw: Optional[ImageDraw.ImageDraw] = None

    # A board is fifty-odd megabytes of canvas at 300dpi, and the two
    # geometries are pure arithmetic over `u()`. Allocating on first
    # use is what lets `card_slot_inches` ask how big a card slot comes
    # out without drawing a board to find out.
    @property
    def image(self) -> Image.Image:
        if self._image is None:
            self._image = Image.new(
                "RGB", (self.width, self.height), self.background
            )
        return self._image

    @property
    def draw(self) -> ImageDraw.ImageDraw:
        if self._draw is None:
            self._draw = ImageDraw.Draw(self.image)
        return self._draw

    def u(self, value: float) -> float:
        return value * self.unit

    def font(self, size: float, bold: bool = False) -> ImageFont.ImageFont:
        return load_font(max(9, round(self.u(size))), bold=bold)

    def fitted_font(
        self,
        text: str,
        max_width: float,
        size: float,
        bold: bool = False,
        minimum: float = 6,
    ) -> ImageFont.ImageFont:
        """The largest of `size` and below whose `text` fits."""
        while size > minimum:
            face = self.font(size, bold=bold)
            if self.draw.textlength(text, font=face) <= max_width:
                return face
            size -= 1
        return self.font(minimum, bold=bold)

    def rect(
        self,
        box: tuple[float, float, float, float],
        radius: float = 0,
        fill: Optional[str] = None,
        outline: Optional[str] = None,
        width: float = 1,
    ) -> None:
        box = (round(box[0]), round(box[1]), round(box[2]), round(box[3]))
        if radius:
            self.draw.rounded_rectangle(
                box,
                radius=round(radius),
                fill=fill,
                outline=outline,
                width=max(1, round(width)),
            )
        else:
            self.draw.rectangle(
                box, fill=fill, outline=outline, width=max(1, round(width))
            )

    def dashed_rect(
        self,
        box: tuple[float, float, float, float],
        outline: str,
        width: float,
        dash: float,
    ) -> None:
        x0, y0, x1, y1 = box
        for start, end in (
            ((x0, y0), (x1, y0)),
            ((x1, y0), (x1, y1)),
            ((x1, y1), (x0, y1)),
            ((x0, y1), (x0, y0)),
        ):
            draw_dashed_line(
                self.draw,
                start[0],
                start[1],
                end[0],
                end[1],
                fill=outline,
                width=max(1, round(width)),
                dash_length=round(dash),
                gap_length=round(dash * 0.7),
            )

    def text(
        self,
        position: tuple[float, float],
        text: str,
        face: ImageFont.ImageFont,
        fill: str,
        anchor: str = "la",
    ) -> None:
        self.draw.text(position, text, font=face, fill=fill, anchor=anchor)

    def text_width(self, text: str, face: ImageFont.ImageFont) -> float:
        return self.draw.textlength(text, font=face)

    def polygon(
        self,
        points: Sequence[tuple[float, float]],
        fill: Optional[str] = None,
        outline: Optional[str] = None,
        width: float = 1,
    ) -> None:
        self.draw.polygon(
            list(points), fill=fill, outline=outline, width=max(1, round(width))
        )


def add_bleed(image: Image.Image, background: str = FACE_COLOR) -> Image.Image:
    bleed = round(BLEED_INCHES * PRINT_DPI)
    sheet = Image.new(
        "RGB",
        (image.width + bleed * 2, image.height + bleed * 2),
        background,
    )
    sheet.paste(image, (bleed, bleed))
    return sheet


# ---------------------------------------------------------------- field


@dataclass(frozen=True)
class FieldGeometry:
    """
    Where the field board's four bands sit, and how wide a space is.

    The three bands around the strip are a fixed share of the sheet and
    the strip takes what is left, so the spaces -- the only part a
    meeple has to fit in -- get every pixel the rest does not need.
    **The clock and the score are not among them**: they went to the
    [jumbotron board](#the-jumbotron-board), which is what leaves the
    strip nearly half the sheet again taller.
    """

    left: float
    right: float
    header_top: float
    header_bottom: float
    direction_top: float
    direction_bottom: float
    strip_top: float
    strip_bottom: float
    range_top: float
    range_bottom: float
    space_width: float
    board_size: int

    @classmethod
    def for_sheet(cls, sheet: Sheet, layout: BoardLayout) -> "FieldGeometry":
        margin = sheet.u(28)
        left = margin
        right = sheet.width - margin
        top = margin
        bottom = sheet.height - margin
        content = bottom - top

        gap = content * 0.018
        header = content * 0.085
        direction = content * 0.05
        ranges = content * 0.085
        strip = content - header - direction - ranges - 3 * gap

        header_bottom = top + header
        direction_top = header_bottom + gap
        direction_bottom = direction_top + direction
        strip_top = direction_bottom + gap
        strip_bottom = strip_top + strip
        range_top = strip_bottom + gap

        return cls(
            left=left,
            right=right,
            header_top=top,
            header_bottom=header_bottom,
            direction_top=direction_top,
            direction_bottom=direction_bottom,
            strip_top=strip_top,
            strip_bottom=strip_bottom,
            range_top=range_top,
            range_bottom=range_top + ranges,
            space_width=(right - left) / layout.board_size,
            board_size=layout.board_size,
        )

    @property
    def space_inches(self) -> tuple[float, float]:
        """
        How big a space prints, which is what says whether meeples fit
        on it -- the reason the clock and score moved off this board.
        """
        return (
            self.space_width / PRINT_DPI,
            (self.strip_bottom - self.strip_top) / PRINT_DPI,
        )

    def space_bounds(self, index: int) -> tuple[float, float]:
        return (
            self.left + index * self.space_width,
            self.left + (index + 1) * self.space_width,
        )

    def span_bounds(self, first: int, last: int) -> tuple[float, float]:
        return self.space_bounds(first)[0], self.space_bounds(last)[1]


def render_field_board(
    rules: BasicRuleset,
    board_size: int = 7,
    paper: str = DEFAULT_PAPER,
    bleed: bool = False,
) -> Image.Image:
    """
    The field: one row of spaces, split into the three zones, with the
    kickoff space marked and each side's shooting range bracketed under
    it. Nothing else -- the clock and the score are their own board.
    """
    if board_size not in rules.board_layouts:
        raise ValueError(
            f"No board layout of {board_size} spaces; the ruleset has "
            f"{', '.join(str(size) for size in sorted(rules.board_layouts))}."
        )
    layout = rules.board_layouts[board_size]
    board = BoardState.empty(layout)

    width, height = sheet_pixels(paper, landscape=True)
    sheet = Sheet(width, height)
    geometry = FieldGeometry.for_sheet(sheet, layout)

    draw_field_header(sheet, geometry, layout)
    draw_attack_directions(sheet, geometry, board)
    draw_field_strip(sheet, geometry, layout)
    draw_shooting_ranges(sheet, geometry, board)

    return add_bleed(sheet.image) if bleed else sheet.image


def draw_field_header(
    sheet: Sheet,
    geometry: FieldGeometry,
    layout: BoardLayout,
) -> None:
    top = geometry.header_top
    bottom = geometry.header_bottom
    sheet.text(
        (geometry.left, top),
        "D12 BALL",
        sheet.font(40, bold=True),
        INK,
    )
    sheet.text(
        (geometry.left, top + sheet.u(46)),
        f"FIELD BOARD  ·  {layout.board_size} SPACES  ·  BASIC MODE",
        sheet.font(16, bold=True),
        MUTED,
    )
    sheet.text(
        (geometry.right, bottom - sheet.u(38)),
        "Two periods of 15 space minutes. Home kicks off the first, the "
        "visitors the second.",
        sheet.font(15),
        MUTED,
        anchor="ra",
    )
    sheet.text(
        (geometry.right, bottom - sheet.u(17)),
        "The clock and the score are kept on the jumbotron board.",
        sheet.font(15),
        MUTED,
        anchor="ra",
    )


def draw_attack_directions(
    sheet: Sheet,
    geometry: FieldGeometry,
    board: BoardState,
) -> None:
    """
    Which way each side is playing, over the half of the field it is
    playing into. Home attacks the visitors goal, so its arrow runs to
    the right and sits on the right of the board; the visitors' is the
    mirror of it.
    """
    top = geometry.direction_top
    bottom = geometry.direction_bottom
    middle = (geometry.left + geometry.right) / 2
    head = sheet.u(26)
    face = sheet.font(17, bold=True)

    visitors = (geometry.left, middle - sheet.u(10))
    sheet.polygon(
        [
            (visitors[0], (top + bottom) / 2),
            (visitors[0] + head, top),
            (visitors[1], top),
            (visitors[1], bottom),
            (visitors[0] + head, bottom),
        ],
        fill=PANEL_COLOR,
        outline=PANEL_EDGE,
        width=sheet.u(1.6),
    )
    sheet.text(
        ((visitors[0] + visitors[1]) / 2, (top + bottom) / 2),
        "VISITORS ATTACK THIS WAY",
        face,
        INK,
        anchor="mm",
    )

    home = (middle + sheet.u(10), geometry.right)
    sheet.polygon(
        [
            (home[1], (top + bottom) / 2),
            (home[1] - head, top),
            (home[0], top),
            (home[0], bottom),
            (home[1] - head, bottom),
        ],
        fill=PANEL_COLOR,
        outline=PANEL_EDGE,
        width=sheet.u(1.6),
    )
    sheet.text(
        ((home[0] + home[1]) / 2, (top + bottom) / 2),
        "HOME ATTACK THIS WAY",
        face,
        INK,
        anchor="mm",
    )


def draw_field_strip(
    sheet: Sheet,
    geometry: FieldGeometry,
    layout: BoardLayout,
) -> None:
    top = geometry.strip_top
    bottom = geometry.strip_bottom
    # The zone name goes in a band across the top of its zone rather
    # than free over the spaces, which is where it collided with the
    # space codes -- the same band the bot's board leaves above its
    # spaces, for the same reason.
    band_bottom = top + sheet.u(34)
    code_face = sheet.font(15, bold=True)

    index = 0
    for zone in Zone:
        spaces = layout.zone_spaces[zone]
        zone_left, zone_right = geometry.span_bounds(index, index + spaces - 1)
        sheet.rect(
            (zone_left, top, zone_right, bottom),
            fill=ZONE_TINTS[zone],
            outline=INK,
            width=sheet.u(2.5),
        )

        for space_index in range(spaces):
            space_left, space_right = geometry.space_bounds(index + space_index)
            sheet.rect(
                (space_left, band_bottom, space_right, bottom),
                outline=INK,
                width=sheet.u(1.4),
            )
            sheet.text(
                (space_left + sheet.u(12), band_bottom + sheet.u(10)),
                space_code(zone, space_index),
                code_face,
                MUTED,
            )

        sheet.rect(
            (zone_left, top, zone_right, band_bottom),
            fill=ZONE_TINTS[zone],
            outline=INK,
            width=sheet.u(2),
        )
        label = ZONE_LABELS[zone]
        sheet.text(
            ((zone_left + zone_right) / 2, (top + band_bottom) / 2),
            label,
            sheet.fitted_font(label, (zone_right - zone_left) * 0.92, 21, bold=True),
            INK,
            anchor="mm",
        )
        index += spaces

    draw_kickoff_marks(sheet, geometry, layout)
    draw_range_edges(sheet, geometry, BoardState.empty(layout))


def kickoff_marks(layout: BoardLayout) -> dict[int, list[TeamSide]]:
    """
    Which spaces are kickoff spaces, and whose.

    On boards 7 and 9 both sides kick off from the true middle space
    and the two sides land on one mark; board 6's midfield has no
    middle, so each side kicks off from the space nearer its own goal
    and the marks are separate -- which is why this is a map and not a
    space. `kickoff_space_index` is the rule; this only places it on
    the whole board.
    """
    before_midfield = layout.zone_spaces[Zone.HOME_GOAL]
    marks: dict[int, list[TeamSide]] = {}
    for side in TeamSide:
        flat = before_midfield + kickoff_space_index(
            layout.zone_spaces[Zone.MIDFIELD], side
        )
        marks.setdefault(flat, []).append(side)
    return marks


def draw_kickoff_marks(
    sheet: Sheet,
    geometry: FieldGeometry,
    layout: BoardLayout,
) -> None:
    """Where a restart puts the ball -- see `kickoff_marks`."""
    for flat, sides in kickoff_marks(layout).items():
        left, right = geometry.space_bounds(flat)
        center_x = (left + right) / 2
        # Below the zone-name band, so the mark is centred in the space
        # a coach sees rather than in the zone rectangle.
        center_y = (geometry.strip_top + sheet.u(34) + geometry.strip_bottom) / 2
        radius = min(
            (right - left) * 0.26,
            (geometry.strip_bottom - geometry.strip_top) * 0.22,
        )
        sheet.polygon(
            polygon_points(center_x, center_y, radius, 12),
            fill=FACE_COLOR,
            outline=INK,
            width=sheet.u(2),
        )
        sheet.text(
            (center_x, center_y),
            "1",
            sheet.font(24, bold=True),
            INK,
            anchor="mm",
        )
        label = (
            "KICKOFF"
            if len(sides) == 2
            else f"{sides[0].value.upper()} KICKOFF"
        )
        sheet.text(
            (center_x, center_y + radius + sheet.u(10)),
            label,
            sheet.fitted_font(label, (right - left) * 0.9, 16, bold=True),
            INK,
            anchor="ma",
        )
        sheet.text(
            (center_x, center_y + radius + sheet.u(30)),
            "ball at speed 1",
            sheet.font(13),
            MUTED,
            anchor="ma",
        )


def range_side(board: BoardState, index: int) -> int:
    if board.is_in_shooting_range(TeamSide.HOME, index):
        return 1
    if board.is_in_shooting_range(TeamSide.VISITING, index):
        return -1
    return 0


def draw_range_edges(
    sheet: Sheet,
    geometry: FieldGeometry,
    board: BoardState,
) -> None:
    """
    Where each side's shooting range begins, dashed down the field --
    the same line the bot's board draws, and never a zone boundary: on
    every board size the edge falls inside midfield.
    """
    for index in range(1, geometry.board_size):
        if range_side(board, index) == range_side(board, index - 1):
            continue
        x = geometry.space_bounds(index)[0]
        draw_dashed_line(
            sheet.draw,
            x,
            geometry.strip_top + sheet.u(40),
            x,
            geometry.strip_bottom - sheet.u(6),
            fill=OFFENSE_COLOR,
            width=max(1, round(sheet.u(3))),
            dash_length=round(sheet.u(14)),
            gap_length=round(sheet.u(10)),
        )


def shooting_range_bands(
    board: BoardState,
) -> list[tuple[int, int, int]]:
    """
    The field cut into runs of spaces that belong to the same range:
    `(side, first, last)` with side 1 for home, -1 for the visitors and
    0 for the space in nobody's, in left-to-right order. It reads
    `is_in_shooting_range` a space at a time rather than restating the
    geometry, so the bracket printed under the board and the rule the
    bot enforces cannot come apart.
    """
    bands: list[tuple[int, int, int]] = []
    for index in range(board.layout.board_size):
        side = range_side(board, index)
        if bands and bands[-1][0] == side:
            bands[-1] = (side, bands[-1][1], index)
        else:
            bands.append((side, index, index))
    return bands


def draw_shooting_ranges(
    sheet: Sheet,
    geometry: FieldGeometry,
    board: BoardState,
) -> None:
    """
    A bracket under each side's range, and under the space in neither
    of them where the board has one. Shooting range is not a zone --
    it is measured from the middle of the board and cuts across
    midfield -- so it is bracketed rather than coloured into the strip.
    """
    labels = {
        -1: "VISITORS' SHOOTING RANGE",
        1: "HOME'S SHOOTING RANGE",
        0: "NEITHER SIDE MAY SHOOT",
    }
    top = geometry.range_top
    bottom = geometry.range_bottom

    for side, first, last in shooting_range_bands(board):
        left, right = geometry.span_bounds(first, last)
        left += sheet.u(4)
        right -= sheet.u(4)
        if side == 0:
            sheet.dashed_rect(
                (left, top, right, bottom),
                outline=MUTED,
                width=sheet.u(1.6),
                dash=sheet.u(9),
            )
        else:
            sheet.rect(
                (left, top, right, bottom),
                radius=sheet.u(6),
                fill=PANEL_COLOR,
                outline=PANEL_EDGE,
                width=sheet.u(1.6),
            )
        label = labels[side]
        sheet.text(
            ((left + right) / 2, (top + bottom) / 2 - sheet.u(11)),
            label,
            sheet.fitted_font(label, (right - left) * 0.92, 17, bold=True),
            INK if side else MUTED,
            anchor="mm",
        )
        # The neither band is one space wide and the two ranges are
        # three or four, so its note is the short one -- fitted to a
        # single space, the longer wording comes out unreadably small.
        note = "shoot only from here" if side else "the kickoff space"
        sheet.text(
            ((left + right) / 2, (top + bottom) / 2 + sheet.u(13)),
            note,
            sheet.fitted_font(note, (right - left) * 0.92, 13),
            MUTED,
            anchor="mm",
        )


# ------------------------------------------------------------ jumbotron


@dataclass(frozen=True)
class JumbotronGeometry:
    """
    The clock and the two score tracks, on a board of their own.

    They were bands on the field board, where sixteen minutes across a
    sheet already carrying the field left a cell too small to stand a
    token in. On their own sheet the clock runs two rows of eight
    instead of one of sixteen, which is what turns an inch-wide cell
    into a two-inch one -- `cell_inches` is that measurement, and the
    suite holds it above `MIN_TOKEN_INCHES`.
    """

    left: float
    right: float
    header_top: float
    header_bottom: float
    clock_top: float
    clock_bottom: float
    score_top: float
    score_bottom: float
    footer_y: float

    @classmethod
    def for_sheet(cls, sheet: Sheet) -> "JumbotronGeometry":
        margin = sheet.u(28)
        left = margin
        right = sheet.width - margin
        top = margin
        bottom = sheet.height - margin
        content = bottom - top

        gap = content * 0.03
        header = content * 0.1
        footer = content * 0.04
        panels = content - header - footer - 2 * gap
        # The clock is two rows to the score's two, but its cells are
        # the ones a minute token sits in all game.
        clock = panels * 0.56

        header_bottom = top + header
        clock_top = header_bottom + gap
        clock_bottom = clock_top + clock
        score_top = clock_bottom + gap

        return cls(
            left=left,
            right=right,
            header_top=top,
            header_bottom=header_bottom,
            clock_top=clock_top,
            clock_bottom=clock_bottom,
            score_top=score_top,
            score_bottom=score_top + panels - clock,
            footer_y=bottom - footer / 2,
        )

    def clock_cell(self) -> tuple[float, float]:
        rows = -(-(CLOCK_MINUTES + 1) // CLOCK_COLUMNS)
        return (
            (self.right - self.left) / CLOCK_COLUMNS,
            (self.clock_bottom - self.clock_top - self.label_height) / rows,
        )

    def score_cell(self) -> tuple[float, float]:
        return (
            (self.right - self.left - self.score_label_width)
            / (SCORE_TRACK_MAX + 1),
            (self.score_bottom - self.score_top - self.label_height) / 2,
        )

    @property
    def label_height(self) -> float:
        return (self.header_bottom - self.header_top) * 0.42

    @property
    def score_label_width(self) -> float:
        return (self.right - self.left) * 0.11


def cell_inches(paper: str = DEFAULT_PAPER) -> dict[str, tuple[float, float]]:
    """
    How big the clock's and the score's cells print. This is the whole
    reason the jumbotron is its own board, so it is a number the CLI
    reports and the suite asserts rather than something read off a
    render.
    """
    geometry = JumbotronGeometry.for_sheet(
        Sheet(*sheet_pixels(paper, landscape=True))
    )
    return {
        "clock": tuple(value / PRINT_DPI for value in geometry.clock_cell()),
        "score": tuple(value / PRINT_DPI for value in geometry.score_cell()),
    }


def render_jumbotron_board(
    paper: str = DEFAULT_PAPER,
    bleed: bool = False,
) -> Image.Image:
    """
    The jumbotron: the game clock and both scores, each cell big enough
    to stand a token in.

    Like the bot's own jumbotron this is the state of the match rather
    than the position -- which is why it comes off the field board
    rather than sharing it. The tracks are printed aids and not
    components the rules name; everything they count is a rule.
    """
    sheet = Sheet(*sheet_pixels(paper, landscape=True))
    geometry = JumbotronGeometry.for_sheet(sheet)

    draw_jumbotron_header(sheet, geometry)
    draw_clock_track(sheet, geometry)
    draw_score_tracks(sheet, geometry)
    sheet.text(
        ((geometry.left + geometry.right) / 2, geometry.footer_y),
        "Every turn costs at least one minute, and a score attempt one "
        "per space to the attacked end. The clock stops at 15.",
        sheet.font(15),
        MUTED,
        anchor="mm",
    )

    return add_bleed(sheet.image) if bleed else sheet.image


def draw_jumbotron_header(sheet: Sheet, geometry: JumbotronGeometry) -> None:
    top = geometry.header_top
    bottom = geometry.header_bottom
    sheet.text(
        (geometry.left, top),
        "JUMBOTRON",
        sheet.font(40, bold=True),
        INK,
    )
    sheet.text(
        (geometry.left, top + sheet.u(46)),
        "CLOCK AND SCORE  ·  BASIC MODE",
        sheet.font(16, bold=True),
        MUTED,
    )

    # The period, as two boxes rather than a track: a game has two of
    # them and nothing moves between them.
    face = sheet.font(19, bold=True)
    box = sheet.u(34)
    cursor = geometry.right
    for label in ("2ND HALF", "1ST HALF"):
        sheet.text(
            (cursor, (top + bottom) / 2),
            label,
            face,
            INK,
            anchor="rm",
        )
        cursor -= sheet.text_width(label, face) + sheet.u(12)
        sheet.rect(
            (
                cursor - box,
                (top + bottom) / 2 - box / 2,
                cursor,
                (top + bottom) / 2 + box / 2,
            ),
            radius=sheet.u(4),
            fill=FACE_COLOR,
            outline=INK,
            width=sheet.u(2),
        )
        cursor -= box + sheet.u(34)


def draw_clock_track(sheet: Sheet, geometry: JumbotronGeometry) -> None:
    """
    Sixteen minutes in two rows of eight. The last is bordered and
    captioned, because reaching it is the one thing on this board that
    changes what a coach may do -- see "Last possession".
    """
    sheet.rect(
        (
            geometry.left,
            geometry.clock_top,
            geometry.right,
            geometry.clock_bottom,
        ),
        radius=sheet.u(10),
        fill=PANEL_COLOR,
        outline=PANEL_EDGE,
        width=sheet.u(2),
    )
    sheet.text(
        (geometry.left + sheet.u(18), geometry.clock_top + sheet.u(12)),
        "CLOCK  ·  SPACE MINUTES",
        sheet.font(17, bold=True),
        MUTED,
    )

    cells_left = geometry.left + sheet.u(18)
    cells_right = geometry.right - sheet.u(18)
    cells_top = geometry.clock_top + geometry.label_height
    cell_width = (cells_right - cells_left) / CLOCK_COLUMNS
    rows = -(-(CLOCK_MINUTES + 1) // CLOCK_COLUMNS)
    cell_height = (geometry.clock_bottom - sheet.u(14) - cells_top) / rows
    number_face = sheet.font(52, bold=True)

    for minute in range(CLOCK_MINUTES + 1):
        column = minute % CLOCK_COLUMNS
        row = minute // CLOCK_COLUMNS
        cell_left = cells_left + column * cell_width
        cell_top = cells_top + row * cell_height
        last = minute == CLOCK_MINUTES
        sheet.rect(
            (
                cell_left + sheet.u(4),
                cell_top + sheet.u(4),
                cell_left + cell_width - sheet.u(4),
                cell_top + cell_height - sheet.u(4),
            ),
            radius=sheet.u(8),
            fill=FACE_COLOR,
            outline=OFFENSE_COLOR if last else PANEL_EDGE,
            width=sheet.u(3.5 if last else 1.6),
        )
        sheet.text(
            (cell_left + cell_width / 2, cell_top + cell_height * 0.46),
            f"{minute:02d}",
            number_face,
            INK if last else MUTED,
            anchor="mm",
        )
        caption = (
            "kickoff"
            if minute == 0
            else "last possession"
            if last
            else None
        )
        if caption:
            sheet.text(
                (cell_left + cell_width / 2, cell_top + cell_height * 0.78),
                caption,
                sheet.fitted_font(
                    caption, cell_width * 0.8, 16, bold=last
                ),
                OFFENSE_COLOR if last else MUTED,
                anchor="mm",
            )


def draw_score_tracks(sheet: Sheet, geometry: JumbotronGeometry) -> None:
    """
    A row each. It runs to 12 because a shootout goal is a goal: six
    pairings can be added to a score that was already level, so a track
    cut to what a match alone reaches would run out exactly when the
    game is being decided.
    """
    sheet.rect(
        (
            geometry.left,
            geometry.score_top,
            geometry.right,
            geometry.score_bottom,
        ),
        radius=sheet.u(10),
        fill=PANEL_COLOR,
        outline=PANEL_EDGE,
        width=sheet.u(2),
    )
    sheet.text(
        (geometry.left + sheet.u(18), geometry.score_top + sheet.u(12)),
        "SCORE  ·  SHOOTOUT GOALS COUNT",
        sheet.font(17, bold=True),
        MUTED,
    )

    label_width = geometry.score_label_width
    cells_left = geometry.left + sheet.u(18) + label_width
    cells_right = geometry.right - sheet.u(18)
    rows_top = geometry.score_top + geometry.label_height
    cell_width = (cells_right - cells_left) / (SCORE_TRACK_MAX + 1)
    row_height = (geometry.score_bottom - sheet.u(14) - rows_top) / 2
    number_face = sheet.fitted_font(
        str(SCORE_TRACK_MAX), cell_width * 0.5, 34, bold=True
    )
    # "VISITORS" is the long one and the cells start where the label
    # column ends, so it is fitted rather than sized -- an overrun here
    # runs the word straight through the 0 cell.
    label_face = sheet.fitted_font(
        "VISITORS", label_width - sheet.u(16), 22, bold=True
    )

    for row, label in enumerate(("HOME", "VISITORS")):
        row_top = rows_top + row * row_height
        sheet.text(
            (geometry.left + sheet.u(18), row_top + row_height / 2),
            label,
            label_face,
            INK,
            anchor="lm",
        )
        for value in range(SCORE_TRACK_MAX + 1):
            cell_left = cells_left + value * cell_width
            sheet.rect(
                (
                    cell_left + sheet.u(3),
                    row_top + sheet.u(4),
                    cell_left + cell_width - sheet.u(3),
                    row_top + row_height - sheet.u(4),
                ),
                radius=sheet.u(6),
                fill=FACE_COLOR,
                outline=PANEL_EDGE,
                width=sheet.u(1.6),
            )
            sheet.text(
                (cell_left + cell_width / 2, row_top + row_height / 2),
                str(value),
                number_face,
                MUTED,
                anchor="mm",
            )


# ----------------------------------------------------------- team board


@dataclass(frozen=True)
class TeamBoardGeometry:
    """
    The team board's six cells: the three zones across the top, the two
    benches under them, and the head coach in the sixth.

    **The head coach is a cell rather than a band of its own**, which
    is what makes the sheet work at all. Five of the six areas have to
    hold a 3.5in card, so two rows of them plus a header is already
    most of an A3's shorter side; a band across the top for the dice
    would take the areas below a card and turn a board to lay cards on
    into a picture of one. `card_slot_inches` is what says which of
    those a print is.

    `slot` is the card guide drawn inside an area, capped at a real
    poker card so a bigger sheet gives a roomier area rather than an
    outsized guide.
    """

    left: float
    right: float
    header_top: float
    header_bottom: float
    columns: tuple[tuple[float, float], ...]
    rows: tuple[tuple[float, float], ...]
    slot: tuple[float, float]
    slot_pitch: float
    label_height: float

    @classmethod
    def for_sheet(cls, sheet: Sheet) -> "TeamBoardGeometry":
        margin = sheet.u(26)
        left = margin
        right = sheet.width - margin
        top = margin
        bottom = sheet.height - margin
        content = bottom - top

        gap = content * 0.016
        header = content * 0.092
        # The footer carries the formation table, which is a strip of
        # numbers rather than a panel: the head coach cell holds the
        # dice and the die faces and has nothing left to give.
        footer = content * 0.075
        rows_total = content - header - footer - 3 * gap
        row_height = rows_total / 2

        header_bottom = top + header
        rows = tuple(
            (
                header_bottom + gap + index * (row_height + gap),
                header_bottom + gap + index * (row_height + gap) + row_height,
            )
            for index in range(2)
        )
        column_gap = sheet.u(20)
        column_width = (right - left - 2 * column_gap) / 3
        columns = tuple(
            (
                left + index * (column_width + column_gap),
                left + index * (column_width + column_gap) + column_width,
            )
            for index in range(3)
        )

        label_height = sheet.u(24)
        padding = sheet.u(10)
        available_height = row_height - label_height - padding * 2
        available_width = column_width - padding * 2
        slot_height = min(
            available_height,
            CARD_INCHES[1] * PRINT_DPI,
            # The fan needs room for the two cards behind the front
            # one: a card shows at least four tenths of its width.
            available_width
            / (1 + 0.4 * (CARDS_PER_AREA - 1))
            * CARD_INCHES[1]
            / CARD_INCHES[0],
        )
        slot_width = slot_height * CARD_INCHES[0] / CARD_INCHES[1]
        pitch = (available_width - slot_width) / (CARDS_PER_AREA - 1)

        return cls(
            left=left,
            right=right,
            header_top=top,
            header_bottom=header_bottom,
            columns=columns,
            rows=rows,
            slot=(slot_width, slot_height),
            slot_pitch=pitch,
            label_height=label_height,
        )

    def area(self, column: int, row: int) -> tuple[float, float, float, float]:
        left, right = self.columns[column]
        top, bottom = self.rows[row]
        return left, top + self.label_height, right, bottom


def card_slot_inches(paper: str = DEFAULT_PAPER) -> tuple[float, float]:
    """
    How big a card the team board's areas are cut for, in inches. The
    CLI prints it, and it is what says whether a print can be laid
    cards on or only read: at A3 and tabloid it is a poker card, and a
    smaller sheet scales it down with everything else.
    """
    width, height = sheet_pixels(paper, landscape=True)
    geometry = TeamBoardGeometry.for_sheet(Sheet(width, height))
    return (
        geometry.slot[0] / PRINT_DPI,
        geometry.slot[1] / PRINT_DPI,
    )


def render_team_board(
    rules: BasicRuleset,
    players: PlayerCatalog,
    maneuvers: ManeuverCatalog,
    team: Optional[Team] = None,
    paper: str = DEFAULT_PAPER,
    bleed: bool = False,
) -> Image.Image:
    """
    One coach's board: the five areas a card can be in -- the three
    zones across the top, the bench and the back bench under them --
    and the head coach in the sixth cell, holding the coach's d12 and
    the six maneuvers they choose between.

    `team` only colours it. The areas and their names are the same for
    every side, which is what lets one design be printed four times.
    """
    width, height = sheet_pixels(paper, landscape=True)
    sheet = Sheet(width, height)
    geometry = TeamBoardGeometry.for_sheet(sheet)
    accent = TEAM_COLORS[team] if team else INK

    draw_team_header(sheet, geometry, players, team, accent)

    for column, zone in enumerate(Zone):
        draw_card_area(
            sheet,
            geometry,
            column=column,
            row=0,
            title=ZONE_LABELS[zone],
            caption="cards assigned to this zone",
            tint=ZONE_TINTS[zone],
            accent=accent,
        )
    draw_card_area(
        sheet,
        geometry,
        column=0,
        row=1,
        title="BENCH",
        caption="players who have yet to play",
        tint=PANEL_COLOR,
        accent=accent,
    )
    draw_card_area(
        sheet,
        geometry,
        column=1,
        row=1,
        title="BACK BENCH",
        caption="injured players, and anyone subbed out",
        tint=PANEL_COLOR,
        accent=accent,
    )
    draw_head_coach_panel(sheet, geometry, rules, maneuvers, accent)
    draw_team_footer(sheet, geometry, rules)

    return add_bleed(sheet.image) if bleed else sheet.image


def draw_team_header(
    sheet: Sheet,
    geometry: TeamBoardGeometry,
    players: PlayerCatalog,
    team: Optional[Team],
    accent: str,
) -> None:
    top = geometry.header_top
    bottom = geometry.header_bottom
    sheet.rect(
        (geometry.left, bottom - sheet.u(4), geometry.right, bottom),
        fill=accent,
    )
    sheet.text(
        (geometry.left, top),
        "TEAM BOARD",
        sheet.font(30, bold=True),
        INK,
    )
    sheet.text(
        (geometry.left, top + sheet.u(38)),
        roster_line(players),
        sheet.font(13),
        MUTED,
    )
    name = team.value.upper() if team else "TEAM"
    sheet.text(
        (geometry.right, top + sheet.u(2)),
        name,
        sheet.font(28, bold=True),
        accent,
        anchor="ra",
    )


def roster_line(players: PlayerCatalog) -> str:
    """
    The nine cards a coach starts with, counted off the roster rather
    than written out here, so a team that changes shape upstream
    changes the line.
    """
    roster = next(iter(players.teams.values())).players
    counts = {role: 0 for role in PlayerRole}
    for player in roster:
        counts[player.role] += 1
    parts = [
        f"{count} {role.value.title()}{'s' if count > 1 else ''}"
        for role, count in counts.items()
        if count
    ]
    return (
        f"Six of your {len(roster)} on the field, three on the bench:  "
        + " · ".join(parts)
    )


def draw_head_coach_panel(
    sheet: Sheet,
    geometry: TeamBoardGeometry,
    rules: BasicRuleset,
    maneuvers: ManeuverCatalog,
    accent: str,
) -> None:
    """
    The sixth cell: the coach's own d12, and the six maneuvers they
    choose between.

    **No selection die, and no die faces anywhere on this board.** The
    maneuver cards are how a maneuver is chosen -- a coach holds three
    of each and plays one face down -- so printing "3-4 Dribble
    Advance" beside them would name a component the table does not use.
    What is left is the roster of maneuvers under the rank the matchup
    table calls them by.
    """
    draw_cell_label(
        sheet,
        geometry,
        column=2,
        row=1,
        title="HEAD COACH",
        caption="your die, and your maneuvers",
    )
    area = geometry.area(2, 1)
    sheet.rect(
        area,
        radius=sheet.u(10),
        fill=FACE_COLOR,
        outline=accent,
        width=sheet.u(2.2),
    )

    inner_left = area[0] + sheet.u(20)
    inner_right = area[2] - sheet.u(20)
    cursor = draw_die_slot(
        sheet, rules, inner_left, area[1] + sheet.u(24), inner_right, accent
    )
    draw_maneuver_legend(
        sheet,
        maneuvers,
        inner_left,
        cursor + sheet.u(10),
        inner_right,
        area[3] - sheet.u(16),
    )


def draw_die_slot(
    sheet: Sheet,
    rules: BasicRuleset,
    left: float,
    top: float,
    right: float,
    accent: str,
) -> float:
    """
    The die a coach keeps, read from `basic_rules.json`: how many faces
    it has and whose colour it is -- the team's, which is what `accent`
    stands in for.

    **Only the team die is drawn.** The ruleset still defines the two
    selection d6s beside it, because that data is the bot's model and
    the rules' component list; the printed board is where they have
    stopped being used, and drawing an unused component is worse than
    the divergence. See "The printed boards" in CLAUDE.md.
    """
    die = rules.team_board.team_die
    size = min((right - left) * 0.10, sheet.u(40))
    center_x = left + size + sheet.u(6)
    center_y = top + size

    sheet.polygon(
        polygon_points(center_x, center_y, size, die.sides),
        fill=FACE_COLOR,
        outline=accent,
        width=sheet.u(3),
    )
    sheet.text(
        (center_x, center_y),
        f"d{die.sides}",
        sheet.fitted_font(f"d{die.sides}", size * 1.3, 22, bold=True),
        accent,
        anchor="mm",
    )
    sheet.text(
        (center_x + size + sheet.u(22), center_y - sheet.u(20)),
        "YOUR TEAM DIE",
        sheet.font(19, bold=True),
        INK,
    )
    note = "Every roll in the game is a d12: skill tests, shots, injury checks."
    sheet.text(
        (center_x + size + sheet.u(22), center_y + sheet.u(6)),
        note,
        sheet.fitted_font(
            note, right - center_x - size - sheet.u(22), 15
        ),
        MUTED,
    )
    return top + 2 * size + sheet.u(6)


def draw_maneuver_legend(
    sheet: Sheet,
    maneuvers: ManeuverCatalog,
    left: float,
    top: float,
    right: float,
    bottom: float,
) -> float:
    """
    The six maneuvers, by the rank the matchup table names them by.
    This is a coach's hand, not a die's faces -- the cards carry the
    effects, so what belongs here is only which three are which.

    **The rows divide what is left of the cell rather than measuring a
    fixed height.** Three rows at a size that fits one sheet run off
    the bottom of the panel on another, and the panel is the only thing
    on this board a reader would take for a mistake rather than a
    layout that scaled.
    """
    heading = "MANEUVER CARDS  ·  BOTH COACHES PLAY ONE FACE DOWN"
    sheet.text(
        (left, top),
        heading,
        sheet.fitted_font(heading, right - left, 14, bold=True),
        MUTED,
    )
    column_width = (right - left) / 2
    rows_top = top + sheet.u(58)
    row_height = (bottom - rows_top) / len(maneuvers.offense)
    # Sized to the row rather than to the sheet, so the three lines
    # breathe on a board with room and close up on one without.
    body_size = min(20, row_height / sheet.unit * 0.5)
    rank_face = sheet.font(body_size, bold=True)
    rank_left = sheet.u(44)

    columns = (
        ("WITH THE BALL", maneuvers.offense, OFFENSE_COLOR, "O"),
        ("CHALLENGING", maneuvers.defense, DEFENSE_COLOR, "D"),
    )
    # All six names at one size, fitted to the longest of them. Fitting
    # each on its own left "Steal Intercept" half the height of
    # "Pressure" beside it, which reads as emphasis rather than as the
    # accident of length it is.
    name_width = column_width - rank_left - sheet.u(10)
    name_face = sheet.font(body_size)
    for maneuver in maneuvers.offense + maneuvers.defense:
        candidate = sheet.fitted_font(maneuver.name, name_width, body_size)
        if candidate.size < name_face.size:
            name_face = candidate

    for index, (heading, side, color, letter) in enumerate(columns):
        column_left = left + index * column_width
        sheet.text(
            (column_left, top + sheet.u(28)),
            heading,
            sheet.fitted_font(heading, column_width * 0.9, 15, bold=True),
            color,
        )
        for row, maneuver in enumerate(sorted(side, key=lambda m: m.rank)):
            row_y = rows_top + row_height * (row + 0.5)
            sheet.text(
                (column_left, row_y),
                f"{letter}{maneuver.rank}",
                rank_face,
                color,
                anchor="lm",
            )
            sheet.text(
                (column_left + rank_left, row_y),
                maneuver.name,
                name_face,
                INK,
                anchor="lm",
            )
    return bottom


def draw_formation_strip(
    sheet: Sheet,
    rules: BasicRuleset,
    left: float,
    top: float,
    right: float,
) -> None:
    """
    The three shapes, as a strip rather than a table -- there is no
    cell left to put a table in, and three numbers a shape reads
    perfectly well in a line.

    A formation is read from a coach's own goal forward, which is the
    one thing on this board that is not absolute, and is why the label
    says so.
    """
    heading = "FORMATIONS — READ FROM YOUR OWN GOAL"
    heading_face = sheet.font(14, bold=True)
    sheet.text((left, top), heading, heading_face, MUTED)

    cursor = left + sheet.text_width(heading, heading_face) + sheet.u(22)
    row_face = sheet.font(16, bold=True)
    detail_face = sheet.font(15)
    for formation in Formation:
        shape = rules.formations[formation]
        sheet.text((cursor, top), formation.value, row_face, INK)
        cursor += sheet.text_width(formation.value, row_face) + sheet.u(8)
        counts = (
            f"({shape.own_goal} / {shape.midfield} / "
            f"{shape.opponent_goal})"
        )
        sheet.text((cursor, top), counts, detail_face, MUTED)
        cursor += sheet.text_width(counts, detail_face) + sheet.u(24)


def standard_deal_line(rules: BasicRuleset) -> str:
    """
    The deal every game starts from, off the ruleset rather than
    written out here, so a change to `basic_rules.json` reaches the
    board.
    """
    parts = [
        f"{area.replace('_', ' ')} "
        + " + ".join(role.value.title() for role in roles)
        for area, roles in rules.standard_setup.items()
    ]
    return "Standard deal (2-2-2): " + " · ".join(parts) + "."


def draw_cell_label(
    sheet: Sheet,
    geometry: TeamBoardGeometry,
    column: int,
    row: int,
    title: str,
    caption: str,
) -> None:
    """
    A cell's name, with what belongs in it to the right of it. The two
    share one line and the caption is what gives: a title is the name
    of an area a coach has to find, and "injured players, and anyone
    subbed out" is a reminder they read once.
    """
    left, right = geometry.columns[column]
    top = geometry.rows[row][0]
    title_face = sheet.fitted_font(title, (right - left) * 0.52, 19, bold=True)
    title_width = sheet.text_width(title, title_face)
    sheet.text((left + sheet.u(4), top), title, title_face, INK)
    sheet.text(
        (right - sheet.u(4), top + sheet.u(6)),
        caption,
        sheet.fitted_font(
            caption,
            right - left - title_width - sheet.u(24),
            13,
        ),
        MUTED,
        anchor="ra",
    )


def draw_card_area(
    sheet: Sheet,
    geometry: TeamBoardGeometry,
    column: int,
    row: int,
    title: str,
    caption: str,
    tint: str,
    accent: str,
) -> None:
    """
    One area a card can be in, with three card outlines fanned across
    it. Three is what any of them ever has to hold: a zone holds three
    under 2-3-1 and 1-3-2, and the two benches hold three between them.
    """
    left, right = geometry.columns[column]
    draw_cell_label(sheet, geometry, column, row, title, caption)

    area = geometry.area(column, row)
    sheet.rect(
        area,
        radius=sheet.u(10),
        fill=tint,
        outline=accent,
        width=sheet.u(2.2),
    )

    slot_width, slot_height = geometry.slot
    slot_top = (area[1] + area[3] - slot_height) / 2
    slot_left = area[0] + (
        area[2] - area[0] - slot_width - geometry.slot_pitch * (CARDS_PER_AREA - 1)
    ) / 2
    for index in range(CARDS_PER_AREA):
        card_left = slot_left + index * geometry.slot_pitch
        sheet.dashed_rect(
            (
                card_left,
                slot_top,
                card_left + slot_width,
                slot_top + slot_height,
            ),
            outline=PANEL_EDGE,
            width=sheet.u(1.6),
            dash=sheet.u(10),
        )


def draw_team_footer(
    sheet: Sheet,
    geometry: TeamBoardGeometry,
    rules: BasicRuleset,
) -> None:
    top = geometry.rows[1][1] + sheet.u(16)
    draw_formation_strip(sheet, rules, geometry.left, top, geometry.right)
    sheet.text(
        (geometry.left, top + sheet.u(28)),
        standard_deal_line(rules),
        sheet.font(14),
        INK,
    )
    closing = (
        "A card's zone is where its meeple must stand, and only a "
        "Coaching Choice moves a card between these areas. A player is "
        "Exhausted once their tokens exceed their defence."
    )
    sheet.text(
        (geometry.left, top + sheet.u(50)),
        closing,
        sheet.fitted_font(closing, geometry.right - geometry.left, 14),
        MUTED,
    )
