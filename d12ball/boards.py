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
sharing the field board cost both of them room. The three token
supplies are there for the neighbouring reason -- they are the loose
pieces of the game rather than any part of the position.

Everything the boards assert is read from the data the bot plays
from -- `basic_rules.json` for the layouts, the formations and the
coach's die, `maneuvers.json` for the six maneuvers, and `players.json`
for the roster -- so a printed board cannot claim a rule the bot does
not play, and an import reaches the boards by re-running
`scripts/render_boards.py`. The one thing deliberately left off is the
selection d6: maneuvers are chosen with the cards, so no die value is
printed anywhere here.

**Zones keep their real names on the field board**, which is where a
card's zone is assigned now -- not the team board, which used to carry
that too. A coach's own goal is the home goal for one of them and the
visitors goal for the other, and the same field board is read by both,
so the areas are labelled HOME ZONE / MIDFIELD / VISITORS ZONE exactly
as the bot's coaching image labels them -- HOME THIRD / VISITORS THIRD
on the 9-space board, the only one where the three areas (H/M/V) are
all equal (see "The field" in the living rules, and the 2026-08-24
entry in the rules log). See "Working on the board image" in docs/design/board-image.md
for the same decision taken there, and "The zone-assignment rows" below
for why they moved off the team board.
"""
from dataclasses import dataclass
from typing import Optional, Sequence

from PIL import Image, ImageDraw, ImageFont

from d12ball.cards import (
    FACE_COLOR,
    INK,
    MUTED,
    OFFENSE_COLOR,
    PANEL_COLOR,
    PANEL_EDGE,
    render_maneuver_card_back,
)
# The radius a card's own corners are drawn with -- `CORNER` reads as
# a card's measurement where it is defined and as nothing in
# particular here.
from d12ball.cards import CORNER as CARD_CORNER_RADIUS
from d12ball.components import (
    BasicRuleset,
    BoardLayout,
    BoardState,
    ManeuverCatalog,
    MatchPeriod,
    PlayerCatalog,
    PlayerRole,
    TeamSide,
    Zone,
    kickoff_space_index,
    period_last_minute,
)
from d12ball.game import Team
from d12ball.render import (
    EXHAUSTED_ICON_PATH,
    EXHAUST_ICON_PATH,
    INJURED_ICON_PATH,
    TEAM_COLORS,
    draw_dashed_line,
    load_font,
    load_goal_zone_font,
    polygon_points,
    space_code,
    wrap_text,
    zone_labels,
)


PRINT_DPI = 300
# The bleed a print shop trims into, the same 1/8in the maneuver cards
# carry.
BLEED_INCHES = 0.125

# Sheet sizes in inches, portrait. The field board is drawn portrait
# and the jumbotron landscape, which is what `sheet_pixels` swaps for.
#
# **Tabloid (11 x 17in, the common US "ledger" print size) is the
# default**, over A3: it is the size a home or copy-shop printer
# actually stocks in the US, where A3 is the size these boards were
# first designed at. The team board is the exception and has a paper
# of its own -- half a letter sheet, two coaches to a page; see
# `TEAM_BOARD_PAPER`.
PAPERS: dict[str, tuple[float, float]] = {
    "a3": (11.69, 16.54),
    "a4": (8.27, 11.69),
    "tabloid": (11.0, 17.0),
    "letter": (8.5, 11.0),
}
DEFAULT_PAPER = "tabloid"

# Poker size, the maneuver cards' own -- the player cards share their
# proportions with it on the bot's board (CARD_SIZE is 110 x 154), so
# the areas that hold them are cut for it.
CARD_INCHES = (2.5, 3.5)
# How many cards a zone row on the field board is guided for: three,
# which is what a zone holds under 2-3-1 and 1-3-2. It is the guide
# and not a limit -- see "The zone-assignment rows" in
# docs/design/printed-boards.md. The team board's own benches take one
# guide each now, a card's footprint, and a bench stacks on it.
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

# The clock is one running count over both periods, and both numbers
# are read off the code the bot enforces rather than written here: the
# first half's last minute is where it breaks, the second's is where the
# track ends. The score track runs further than a match is ever likely
# to, because a shootout adds up to six goals to a side that was already
# level.
CLOCK_MINUTES = period_last_minute(MatchPeriod.SECOND_HALF)
HALFTIME_MINUTE = period_last_minute(MatchPeriod.FIRST_HALF)
SCORE_TRACK_MAX = 12
# Eight rather than sixteen across, which is what makes a cell something
# a token stands in -- the reason these tracks came off the field board.
# Eight also puts the halftime break at the end of a row, so each half
# is exactly two rows and the two bands are bands rather than a colour
# change halfway along one.
CLOCK_COLUMNS = 8
# The three token pools a coach draws from all game. They are a supply
# and not a tally: a player's own tokens are stacked on their card, the
# way the bot draws them on the card rather than on the jumbotron.
#
# **Each silo is the token's own art and no words at all.** It is the
# same picture the bot puts on a player's card and the same one uploaded
# to the application emoji (see `scripts/render_condition_tokens.py`), so
# a coach at the table and a coach reading a line of text in Discord are
# looking at one icon -- and a silo captioned "EXHAUSTION" would be
# naming a piece the player is holding a copy of. The printed icon is
# the base of the stack, which is why it sits at the bottom of a silo
# taller than it is wide.
TOKEN_SUPPLY_ICONS = {
    "exhaust": EXHAUST_ICON_PATH,
    "exhausted": EXHAUSTED_ICON_PATH,
    "injured": INJURED_ICON_PATH,
}
TOKEN_SUPPLIES = tuple(TOKEN_SUPPLY_ICONS)
# A silo holds a stack rather than a single piece, so it is a token wide
# and half again as tall.
SILO_INCHES = (0.8, 1.05)
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

    def paste(
        self,
        art: Image.Image,
        box: tuple[float, float, float, float],
    ) -> None:
        """
        Fit an image inside `box`, centred, keeping its proportions.

        Straight to the sheet's own resolution, unlike `cards.Pen.paste`
        and for the same reason in reverse: a sheet does not supersample,
        so there is nothing to scale down to afterwards. The art is its
        own mask, since everything pasted here is a token cut out of its
        background.
        """
        left, top, right, bottom = box
        scale = min(
            (right - left) / art.width, (bottom - top) / art.height
        )
        size = (max(1, round(art.width * scale)),
                max(1, round(art.height * scale)))
        fitted = art.resize(size, Image.Resampling.LANCZOS)
        self.image.paste(
            fitted,
            (
                round(left + ((right - left) - size[0]) / 2),
                round(top + ((bottom - top) - size[1]) / 2),
            ),
            fitted if fitted.mode == "RGBA" else None,
        )

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
    Where the field board's bands sit, and how wide a space is.

    The bands around the strip are a fixed share of the sheet and the
    strip takes what is left, so the spaces -- the only part a meeple
    has to fit in -- get every pixel the rest does not need. **The
    clock and the score are not among them**: they went to the
    [jumbotron board](#the-jumbotron-board), which is what leaves the
    strip nearly half the sheet again taller.

    **`left`/`right` are the full content width and `strip_left`/
    `strip_right` are narrower** -- the header, the direction arrows
    and the shooting-range bracket all read the wide pair, the way the
    bot's own jumbotron and team boards span its end zones and all;
    the spaces themselves, and everything measured off them
    (`space_bounds`, `span_bounds`, `space_width`), read the narrow
    pair, which leaves the gap between the two wide enough for a goal
    zone on each side -- see `draw_field_end_zones`.

    **The sheet is portrait (11 x 17), not landscape, and the strip
    still runs left to right across the narrower dimension.** That is
    the author's own call, made knowing what it costs: a 9-space
    board's spaces come out under an inch wide, well short of the
    1.5in floor two meeples side by side would ask for elsewhere on
    this file, but it is what leaves the 17in length for the two zone-
    assignment rows above and below the strip -- see `zone_row_*`, and
    "The zone-assignment rows" below.
    """

    left: float
    right: float
    strip_left: float
    strip_right: float
    header_top: float
    header_bottom: float
    direction_top: float
    direction_bottom: float
    strip_top: float
    strip_bottom: float
    range_top: float
    range_bottom: float
    visiting_zone_top: float
    visiting_zone_bottom: float
    home_zone_top: float
    home_zone_bottom: float
    space_width: float
    board_size: int

    @classmethod
    def for_sheet(cls, sheet: Sheet, layout: BoardLayout) -> "FieldGeometry":
        margin = sheet.u(28)
        left = margin
        right = sheet.width - margin
        top = margin
        bottom = sheet.height - margin

        # The end zone beyond each end of the strip, and the gap to its
        # own outline -- the print counterpart of `GOAL_ZONE_WIDTH` and
        # `GOAL_ZONE_GAP` in render.py, sized as a share of the sheet
        # rather than a fixed pixel count so it scales with paper size
        # the way every other measurement here does. Narrower than a
        # landscape sheet would carry -- the portrait sheet gives the
        # strip only its own 11in width to divide among spaces, and an
        # end zone eats into that the same as a margin does.
        end_zone_gap = sheet.u(6)
        end_zone_width = sheet.u(30)
        strip_left = left + end_zone_width + end_zone_gap
        strip_right = right - end_zone_width - end_zone_gap

        # A zone-assignment row is a card row, full stop -- it holds a
        # real 2.5 x 3.5in card at its own printed size (`CARD_INCHES`),
        # the same size a card is everywhere else in this codebase, plus
        # a label band across its own top for the zone's name and the
        # "cards assigned to this zone" caption.
        zone_row_gap = sheet.u(14)
        zone_label_height = sheet.u(56)
        zone_row_height = CARD_INCHES[1] * PRINT_DPI + zone_label_height

        visiting_zone_top = top
        visiting_zone_bottom = visiting_zone_top + zone_row_height
        home_zone_bottom = bottom
        home_zone_top = home_zone_bottom - zone_row_height

        content_top = visiting_zone_bottom + zone_row_gap
        content_bottom = home_zone_top - zone_row_gap
        content = content_bottom - content_top

        gap = content * 0.02
        header = content * 0.16
        direction = content * 0.05
        ranges = content * 0.075
        strip = content - header - direction - ranges - 3 * gap

        header_bottom = content_top + header
        direction_top = header_bottom + gap
        direction_bottom = direction_top + direction
        strip_top = direction_bottom + gap
        strip_bottom = strip_top + strip
        range_top = strip_bottom + gap

        return cls(
            left=left,
            right=right,
            strip_left=strip_left,
            strip_right=strip_right,
            header_top=content_top,
            header_bottom=header_bottom,
            direction_top=direction_top,
            direction_bottom=direction_bottom,
            strip_top=strip_top,
            strip_bottom=strip_bottom,
            range_top=range_top,
            range_bottom=range_top + ranges,
            visiting_zone_top=visiting_zone_top,
            visiting_zone_bottom=visiting_zone_bottom,
            home_zone_top=home_zone_top,
            home_zone_bottom=home_zone_bottom,
            space_width=(strip_right - strip_left) / layout.board_size,
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
            self.strip_left + index * self.space_width,
            self.strip_left + (index + 1) * self.space_width,
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
    it, and a zone-assignment row for each coach above and below it --
    see "The zone-assignment rows".

    **Portrait, not landscape** -- the two zone rows need a real 3.5in
    card's worth of height apiece, which the sheet's 17in length holds
    without crowding the strip; see `FieldGeometry` for what that costs
    the strip's own width instead.
    """
    if board_size not in rules.board_layouts:
        raise ValueError(
            f"No board layout of {board_size} spaces; the ruleset has "
            f"{', '.join(str(size) for size in sorted(rules.board_layouts))}."
        )
    layout = rules.board_layouts[board_size]
    board = BoardState.empty(layout)

    width, height = sheet_pixels(paper, landscape=False)
    sheet = Sheet(width, height)
    geometry = FieldGeometry.for_sheet(sheet, layout)

    draw_field_header(sheet, geometry, layout)
    draw_attack_directions(sheet, geometry, board)
    draw_field_strip(sheet, geometry, layout)
    draw_field_end_zones(sheet, geometry)
    draw_shooting_ranges(sheet, geometry, board)
    draw_zone_assignment_rows(sheet, geometry, layout)

    return add_bleed(sheet.image) if bleed else sheet.image


def draw_field_header(
    sheet: Sheet,
    geometry: FieldGeometry,
    layout: BoardLayout,
) -> None:
    """
    The title, stacked in one left-aligned column rather than a title
    on the left and a note on the right -- side by side, the two used
    to overlap in the middle on anything narrower than the old
    landscape sheet, which the portrait sheet always is. Each note
    line is wrapped to the sheet's own content width, so it cannot run
    under the title regardless of paper size or wording length.
    """
    top = geometry.header_top
    left = geometry.left
    width = geometry.right - geometry.left
    sheet.text((left, top), "D12 BALL", sheet.font(40, bold=True), INK)
    sheet.text(
        (left, top + sheet.u(46)),
        f"FIELD BOARD  ·  {layout.board_size} SPACES  ·  BASIC MODE",
        sheet.font(16, bold=True),
        MUTED,
    )

    note_font = sheet.font(15)
    y = top + sheet.u(84)
    for note in (
        f"Two periods on one running clock, 00-{HALFTIME_MINUTE} and "
        f"{HALFTIME_MINUTE + 1}-{CLOCK_MINUTES}. Home kicks off the "
        "first, the visitors the second.",
        "The clock, the score and the token supplies are kept on the "
        "jumbotron board.",
    ):
        for line in wrap_text(sheet.draw, note, note_font, width):
            sheet.text((left, y), line, note_font, MUTED)
            y += sheet.u(21)


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
    labels = zone_labels(layout.board_size)

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
        label = labels[zone]
        sheet.text(
            ((zone_left + zone_right) / 2, (top + band_bottom) / 2),
            label,
            sheet.fitted_font(label, (zone_right - zone_left) * 0.92, 21, bold=True),
            INK,
            anchor="mm",
        )
        index += spaces

    draw_kickoff_marks(sheet, geometry, layout)


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


def draw_field_end_zones(sheet: Sheet, geometry: FieldGeometry) -> None:
    """
    A goal zone of its own beyond each end of the strip, American-
    football style, in the margin `FieldGeometry.for_sheet` set aside
    for it -- the print counterpart of `draw_end_zone` in render.py.

    The field board is a template rather than a match in progress, so
    there is no team to colour a zone by the way the bot's board does;
    "GOAL" is set in ink here, the same as every other label on the
    print, rather than in a team's colour.
    """
    gap = sheet.u(8)
    draw_field_end_zone(
        sheet,
        geometry.left, geometry.strip_left - gap,
        geometry.strip_top, geometry.strip_bottom,
        angle=90,
    )
    draw_field_end_zone(
        sheet,
        geometry.strip_right + gap, geometry.right,
        geometry.strip_top, geometry.strip_bottom,
        angle=270,
    )


def draw_field_end_zone_frame(
    sheet: Sheet, left: float, right: float, top: float, bottom: float,
) -> None:
    """The end zone's own outline, drawn before the "GOAL" lettering."""
    sheet.rect(
        (round(left), round(top), round(right), round(bottom)),
        fill=PANEL_COLOR,
        outline=INK,
        width=sheet.u(2.5),
    )


def goal_word_metrics(
    sheet: Sheet,
    word: str,
    font: ImageFont.ImageFont,
    letter_spacing: float,
) -> tuple[list[float], float, float, tuple[int, int, int, int]]:
    """
    A word's per-letter widths and its total run at this font size --
    with the letter spacing `draw_field_end_zone` adds on top of the
    font's own advance -- plus its cell height and bounding box.
    `fit_goal_word_font` reads this once per candidate size, which is
    what keeps the same four lines from being written twice: once for
    the size the search settles on, once for the size it falls back to.
    """
    bbox = sheet.draw.textbbox((0, 0), word, font=font)
    cell_height = bbox[3] - bbox[1]
    widths = [sheet.draw.textlength(ch, font=font) for ch in word]
    total_width = sum(widths) + letter_spacing * (len(word) - 1)
    return widths, total_width, cell_height, bbox


def fit_goal_word_font(
    sheet: Sheet,
    word: str,
    letter_spacing: float,
    zone_width: float,
    zone_length: float,
) -> tuple[
    ImageFont.ImageFont, list[float], float, float, tuple[int, int, int, int]
]:
    """
    The largest size (in whole pixels, not `sheet.u()` -- this is
    fitted directly against the zone's own measured extent rather
    than eyeballed the way `sheet.font` is elsewhere) that fits the
    word along the zone's length once rotated, and each letter
    within its width.
    """
    size = round(zone_length)
    while size > 24:
        font = load_goal_zone_font(size)
        widths, total_width, cell_height, bbox = goal_word_metrics(
            sheet, word, font, letter_spacing,
        )
        if cell_height <= zone_width * 0.8 and total_width <= zone_length * 0.88:
            return font, widths, total_width, cell_height, bbox
        size = round(size * 0.9)
    font = load_goal_zone_font(24)
    widths, total_width, cell_height, bbox = goal_word_metrics(
        sheet, word, font, letter_spacing,
    )
    return font, widths, total_width, cell_height, bbox


def draw_field_end_zone(
    sheet: Sheet,
    left: float,
    right: float,
    top: float,
    bottom: float,
    angle: int,
) -> None:
    """
    One end zone -- "GOAL" lettered along its length with a blank d12
    standing in for the "O", rotated so the word reads sideways the way
    a real end zone's does. `angle` is 90 or 270, the same pair
    render.py's own end zone takes and for the same reason: the two
    ends of a real field face opposite ways rather than both reading
    the same direction.

    **The block below, from the "O"'s slot through the ball placement,
    moves as one unit or not at all -- see "End zones" in
    docs/design/printed-boards.md.** Its coordinate math was verified
    empirically against Pillow's actual `rotate(90)`/`rotate(270)`
    output, not derived on paper; a sign error in it is silent, not a
    crash.
    """
    assert angle in (90, 270)
    draw_field_end_zone_frame(sheet, left, right, top, bottom)

    word = "GOAL"
    stroke_width = max(1, round(sheet.u(1.2)))
    letter_spacing = sheet.u(10)
    zone_width = right - left
    zone_length = bottom - top

    font, widths, total_width, cell_height, bbox = fit_goal_word_font(
        sheet, word, letter_spacing, zone_width, zone_length,
    )

    pad = 6 + stroke_width
    text_layer = Image.new(
        "RGBA",
        (round(total_width) + pad * 2, round(cell_height) + pad * 2),
        (0, 0, 0, 0),
    )
    text_draw = ImageDraw.Draw(text_layer)

    # The "O" is left undrawn and its slot remembered, so the d12 can
    # be centred exactly there once the word is rotated -- the same
    # trick render.py's own end zone uses, and for the same reason: it
    # stands in for the letter rather than floating near the word.
    o_slot: tuple[float, float] | None = None
    x = float(pad)
    for index, (ch, width) in enumerate(zip(word, widths)):
        if ch == "O":
            o_slot = (x, x + width)
        else:
            text_draw.text(
                (x, pad - bbox[1]),
                ch,
                font=font,
                fill=INK,
                stroke_width=stroke_width,
                stroke_fill=FACE_COLOR,
            )
        x += width
        if index < len(word) - 1:
            x += letter_spacing
    assert o_slot is not None

    rotated = text_layer.rotate(angle, expand=True)
    paste_x = round(left + (zone_width - rotated.width) / 2)
    paste_y = round(top + (zone_length - rotated.height) / 2)
    sheet.image.paste(rotated, (paste_x, paste_y), rotated)

    # Where the "O" would have sat, in sheet coordinates -- the same
    # rotate(90)/rotate(270) mapping render.py's own end zone verified
    # empirically against Pillow's actual output.
    ball_center_x = paste_x + rotated.width / 2
    if angle == 90:
        ball_center_y = paste_y + text_layer.width - sum(o_slot) / 2
    else:
        ball_center_y = paste_y + sum(o_slot) / 2

    ball_radius = round(max(cell_height, o_slot[1] - o_slot[0]) / 2)
    ball_pad = max(2, round(sheet.u(2)))
    ball_span = ball_radius * 2 + ball_pad * 2
    ball_layer = Image.new("RGBA", (ball_span, ball_span), (0, 0, 0, 0))
    ball_draw = ImageDraw.Draw(ball_layer)
    ball_center = ball_span / 2
    ball_draw.polygon(
        polygon_points(ball_center, ball_center, ball_radius, 12),
        fill=FACE_COLOR,
        outline=INK,
        width=max(1, round(sheet.u(1.5))),
    )
    label_font = load_font(max(10, round(ball_radius * 0.6)), bold=True)
    label_bbox = ball_draw.textbbox((0, 0), "12", font=label_font)
    label_width = label_bbox[2] - label_bbox[0]
    label_height = label_bbox[3] - label_bbox[1]
    label_layer = Image.new(
        "RGBA", (round(label_width) + 4, round(label_height) + 4), (0, 0, 0, 0)
    )
    ImageDraw.Draw(label_layer).text(
        (2 - label_bbox[0], 2 - label_bbox[1]),
        "12",
        font=label_font,
        fill=INK,
    )
    rotated_label = label_layer.rotate(angle, expand=True)
    ball_layer.paste(
        rotated_label,
        (
            round(ball_center - rotated_label.width / 2),
            round(ball_center - rotated_label.height / 2),
        ),
        rotated_label,
    )
    ball_x = round(ball_center_x - ball_center)
    ball_y = round(ball_center_y - ball_center)
    sheet.image.paste(ball_layer, (ball_x, ball_y), ball_layer)


# The zone-assignment rows: a card row per zone, above the strip for
# the visiting coach and below it for home, moved here from the team
# board so both coaches stage their own zone's cards on the one board
# between them rather than each reading their own separate sheet.
#
# **Visiting's row is rotated 180 degrees, cell by cell, not the row
# reordered.** The two coaches sit on opposite sides of the table, so
# home's row prints upright to home and would print upside down to
# visiting -- rotating it the other 180 degrees the other way turns it
# upright *for them*, without touching which column is which: HOME
# ZONE (HOME THIRD on the 9-space board) is still the leftmost cell
# either way, directly under and over the strip's own Home column, so
# a coach reading either row left to right is reading the same zone
# order the strip prints.
def draw_zone_assignment_rows(
    sheet: Sheet,
    geometry: FieldGeometry,
    layout: BoardLayout,
) -> None:
    index = 0
    for zone in Zone:
        spaces = layout.zone_spaces[zone]
        zone_left, zone_right = geometry.span_bounds(index, index + spaces - 1)
        draw_zone_assignment_cell(
            sheet, zone, zone_left, zone_right,
            geometry.home_zone_top, geometry.home_zone_bottom,
            flipped=False, board_size=layout.board_size,
        )
        draw_zone_assignment_cell(
            sheet, zone, zone_left, zone_right,
            geometry.visiting_zone_top, geometry.visiting_zone_bottom,
            flipped=True, board_size=layout.board_size,
        )
        index += spaces


def draw_zone_assignment_cell(
    sheet: Sheet,
    zone: Zone,
    left: float,
    right: float,
    top: float,
    bottom: float,
    flipped: bool,
    board_size: int,
) -> None:
    """
    One zone's card row, drawn upright on its own small canvas and
    rotated as a whole when it is the visiting row -- simpler and less
    error-prone than working out where flipped text and flipped dashes
    land by hand, and it is exactly what a physical card laid in the
    row would do if the whole row were spun around.
    """
    width = max(1, round(right - left))
    height = max(1, round(bottom - top))
    cell = Image.new("RGB", (width, height), FACE_COLOR)
    draw = ImageDraw.Draw(cell)

    label = zone_labels(board_size)[zone]
    label_font = sheet.fitted_font(label, width * 0.5, 21, bold=True)
    draw.text((sheet.u(6), sheet.u(8)), label, font=label_font, fill=INK)

    # The caption only fits next to a short zone name (MIDFIELD's own
    # width, mostly) -- HOME ZONE/THIRD and VISITORS ZONE/THIRD are
    # narrower, and a caption that overflows the cell reads worse than
    # one left off.
    caption = "cards assigned to this zone"
    caption_font = sheet.font(12)
    label_width = draw.textlength(label, font=label_font)
    caption_x = sheet.u(6) + label_width + sheet.u(14)
    caption_width = draw.textlength(caption, font=caption_font)
    if caption_x + caption_width <= width - sheet.u(6):
        draw.text(
            (caption_x, sheet.u(15)), caption, font=caption_font, fill=MUTED,
        )

    label_height = sheet.u(56)
    box = (0, label_height, width, height)
    draw.rounded_rectangle(
        box,
        radius=round(sheet.u(6)),
        fill=ZONE_TINTS[zone],
        outline=INK,
        width=max(1, round(sheet.u(2))),
    )
    # A fixed handful of evenly spaced dashed guides, not a strict slot
    # count -- this is a staging area a coach fans any number of cards
    # across, not a fixed set of numbered spaces the way the strip is.
    # `CARDS_PER_AREA` is a visual cue -- what a zone holds under the
    # widest formation -- rather than a limit enforced here.
    slots = CARDS_PER_AREA
    for slot in range(1, slots):
        x = width * slot / slots
        draw_dashed_line(
            draw, x, label_height + sheet.u(6), x, height - sheet.u(6),
            fill=PANEL_EDGE, width=max(1, round(sheet.u(1.4))),
            dash_length=round(sheet.u(8)), gap_length=round(sheet.u(6)),
        )

    if flipped:
        cell = cell.rotate(180)
    sheet.image.paste(cell, (round(left), round(top)))


def range_side(board: BoardState, index: int) -> int:
    if board.is_in_shooting_range(TeamSide.HOME, index):
        return 1
    if board.is_in_shooting_range(TeamSide.VISITING, index):
        return -1
    return 0


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
    outer = zone_labels(board.layout.board_size)
    labels = {
        -1: f"{outer[Zone.VISITORS_GOAL]} - SHOOTING RANGE",
        1: f"{outer[Zone.HOME_GOAL]} - SHOOTING RANGE",
    }
    top = geometry.range_top
    bottom = geometry.range_bottom

    for side, first, last in shooting_range_bands(board):
        left, right = geometry.span_bounds(first, last)
        left += sheet.u(4)
        right -= sheet.u(4)
        if side == 0:
            # No label -- a space in neither range says so by not being
            # bracketed into either one, and "neither side may shoot"
            # was naming an absence rather than a fact worth stating.
            # "the kickoff space" is a different fact and stays, now
            # centred since there is no label above it any more.
            sheet.dashed_rect(
                (left, top, right, bottom),
                outline=MUTED,
                width=sheet.u(1.6),
                dash=sheet.u(9),
            )
            sheet.text(
                ((left + right) / 2, (top + bottom) / 2),
                "the kickoff space",
                sheet.fitted_font("the kickoff space", (right - left) * 0.92, 15),
                MUTED,
                anchor="mm",
            )
            continue
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
            INK,
            anchor="mm",
        )
        sheet.text(
            ((left + right) / 2, (top + bottom) / 2 + sheet.u(13)),
            "shoot only from here",
            sheet.fitted_font(
                "shoot only from here", (right - left) * 0.92, 13,
            ),
            MUTED,
            anchor="mm",
        )


# ------------------------------------------------------------ jumbotron


@dataclass(frozen=True)
class JumbotronGeometry:
    """
    The clock, the two score tracks and the three token supplies, on a
    board of their own.

    They were bands on the field board, where sixteen minutes across a
    sheet already carrying the field left a cell too small to stand a
    token in. On their own sheet the clock runs rows of eight instead of
    one long row, which is what turns an inch-wide cell into a two-inch
    one -- `cell_inches` is that measurement, and the suite holds every
    one of them above `MIN_TOKEN_INCHES`.

    **The clock is four rows, not two**, since it now runs the whole
    game rather than one period: 00-15 and 16-30, two rows a half with
    the break falling at the end of a row. That halved the height a row
    had, which is what the panel shares were redivided for -- and it is
    the thing to check first if a band is ever added here, because a
    cell going under a token is silent on the render.
    """

    left: float
    right: float
    header_top: float
    header_bottom: float
    clock_top: float
    clock_bottom: float
    score_top: float
    score_bottom: float
    supply_top: float
    supply_bottom: float
    footer_y: float
    # What a panel keeps clear inside its own edge. It is a field
    # rather than an `sheet.u(18)` at each site because the cell
    # measurements have to subtract it: they used to divide the panel's
    # whole width and start a padding in, which ran the last column of
    # every track that much past the panel's right edge.
    padding: float

    @classmethod
    def for_sheet(cls, sheet: Sheet) -> "JumbotronGeometry":
        margin = sheet.u(28)
        left = margin
        right = sheet.width - margin
        top = margin
        bottom = sheet.height - margin
        content = bottom - top

        # Three panels to the two this board carried, so the header,
        # the footer and the gaps between them are all trimmed: what
        # they gave up is what keeps every cell over MIN_TOKEN_INCHES.
        #
        # Tabloid becoming the default (11in tall in landscape, against
        # A3's 11.69) took the score and supply cells under that floor
        # by a sliver -- the header shrank a further point to give both
        # the room back; the clock has plenty to spare (its own cell is
        # more than double the floor) so its share gives up the rest.
        gap = content * 0.025
        header = content * 0.08
        footer = content * 0.035
        panels = content - header - footer - 3 * gap
        # The clock takes most of it: four rows of cells to the score's
        # two, and its are the ones a minute token sits in all game. The
        # supplies take least -- a well holds a heap of tokens rather
        # than one standing in a square, so it is sized by the two lines
        # of label over it and not by the token.
        clock = panels * 0.53
        supply = panels * 0.20

        header_bottom = top + header
        clock_top = header_bottom + gap
        clock_bottom = clock_top + clock
        score_top = clock_bottom + gap
        score_bottom = score_top + panels - clock - supply
        supply_top = score_bottom + gap

        return cls(
            left=left,
            right=right,
            header_top=top,
            header_bottom=header_bottom,
            clock_top=clock_top,
            clock_bottom=clock_bottom,
            score_top=score_top,
            score_bottom=score_bottom,
            supply_top=supply_top,
            supply_bottom=supply_top + supply,
            footer_y=bottom - footer / 2,
            padding=sheet.u(18),
        )

    @property
    def cells_left(self) -> float:
        return self.left + self.padding

    @property
    def cells_width(self) -> float:
        return self.right - self.left - 2 * self.padding

    @property
    def clock_rows(self) -> int:
        return -(-(CLOCK_MINUTES + 1) // CLOCK_COLUMNS)

    @property
    def clock_band_label_height(self) -> float:
        """
        The strip over each half's two rows, which says which half they
        are. It is charged twice out of the clock panel, so it is here
        rather than inside the drawing -- `clock_cell` has to measure
        what is left after it.
        """
        return self.label_height * 0.7

    def clock_cell(self) -> tuple[float, float]:
        used = self.label_height + 2 * self.clock_band_label_height
        return (
            self.cells_width / CLOCK_COLUMNS,
            (self.clock_bottom - self.clock_top - used) / self.clock_rows,
        )

    def score_cell(self) -> tuple[float, float]:
        return (
            (self.cells_width - self.score_label_width)
            / (SCORE_TRACK_MAX + 1),
            (self.score_bottom - self.score_top - self.label_height) / 2,
        )

    def supply_cell(self) -> tuple[float, float]:
        """
        One silo, which is a fixed measurement rather than a share of
        the panel: it holds a stack of tokens, and a piece does not get
        bigger because the sheet did. It is capped by the room under the
        label all the same, so a smaller paper shrinks it rather than
        running it off the panel.
        """
        available = (
            self.supply_bottom
            - self.supply_top
            - self.supply_label_height
            - self.padding
        )
        height = min(SILO_INCHES[1] * PRINT_DPI, available)
        return (height * SILO_INCHES[0] / SILO_INCHES[1], height)

    @property
    def supply_label_height(self) -> float:
        """
        Shorter than a track's: this panel's label is one word, and the
        silos under it are the smallest thing on the board.
        """
        return self.label_height * 0.6

    @property
    def label_height(self) -> float:
        """
        The strip a panel keeps for its own title. It is a share of the
        header, which the third panel made shorter -- so this is a
        larger share of a smaller number, and the titles clear the cells
        under them by the same margin they always did.
        """
        return (self.header_bottom - self.header_top) * 0.48

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
        "supply": tuple(
            value / PRINT_DPI for value in geometry.supply_cell()
        ),
    }


def render_jumbotron_board(
    paper: str = DEFAULT_PAPER,
    bleed: bool = False,
) -> Image.Image:
    """
    The jumbotron: the game clock, both scores and the three token
    supplies, each cell big enough to stand a token in.

    Like the bot's own jumbotron this is the state of the match rather
    than the position -- which is why it comes off the field board
    rather than sharing it. The tracks are printed aids and not
    components the rules name; everything they count is a rule.

    **The supplies are silos, not tallies.** A player's own tokens go on
    their card, where the bot draws them; what a coach has no other home
    for is the stock they come out of and the two markers they turn
    into, which used to be a pile beside the sheet.
    """
    sheet = Sheet(*sheet_pixels(paper, landscape=True))
    geometry = JumbotronGeometry.for_sheet(sheet)

    draw_jumbotron_header(sheet, geometry)
    draw_clock_track(sheet, geometry)
    draw_score_tracks(sheet, geometry)
    draw_token_supplies(sheet, geometry)
    footer = (
        "Every turn costs at least one minute, and a score attempt one "
        "per space to the attacked end. The clock never stops: it runs "
        f"past {HALFTIME_MINUTE} and {CLOCK_MINUTES} for as long as last "
        "possession does."
    )
    sheet.text(
        ((geometry.left + geometry.right) / 2, geometry.footer_y),
        footer,
        # Fitted rather than sized: this line grew when the clock did,
        # and at a fixed size it ran off both edges of the sheet.
        sheet.fitted_font(footer, geometry.cells_width, 15),
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
    # No period boxes, and no subtitle either. The boxes were two ticked
    # squares up here while the clock counted one period twice; the clock
    # now runs the whole game in two labelled bands, so where the minute
    # token is standing is already which half it is -- and each panel
    # names itself, which is what the subtitle was doing over the top.
    sheet.text(
        (geometry.right, bottom - sheet.u(48)),
        f"00-{HALFTIME_MINUTE} in the first half, "
        f"{HALFTIME_MINUTE + 1}-{CLOCK_MINUTES} in the second.",
        sheet.font(16),
        MUTED,
        anchor="ra",
    )
    sheet.text(
        (geometry.right, bottom - sheet.u(24)),
        "The second half starts at "
        f"{HALFTIME_MINUTE + 1} however far past {HALFTIME_MINUTE} the "
        "first ran.",
        sheet.font(16),
        MUTED,
        anchor="ra",
    )


@dataclass(frozen=True)
class ClockTrackGeometry:
    """
    Where a minute's cell sits, on the clock panel `JumbotronGeometry`
    already laid out -- its own record because `draw_clock_track` reads
    it from three different bands (the frame, the two half labels and
    the cells) that all have to agree on the same cells.

    `cell_origin` is the one place that turns a minute into a row and
    column. The band label above each half is charged once per half
    rather than once per row, which is the only reason it is arithmetic
    rather than a nested loop -- the break falls at the end of a row by
    construction (see `CLOCK_COLUMNS`), so a minute knows its own band.
    """

    left: float
    right: float
    top: float
    bottom: float
    cells_left: float
    cells_top: float
    cell_width: float
    cell_height: float
    band_label: float

    @classmethod
    def for_jumbotron(cls, geometry: JumbotronGeometry) -> "ClockTrackGeometry":
        cell_width, cell_height = geometry.clock_cell()
        return cls(
            left=geometry.left,
            right=geometry.right,
            top=geometry.clock_top,
            bottom=geometry.clock_bottom,
            cells_left=geometry.cells_left,
            cells_top=geometry.clock_top + geometry.label_height,
            cell_width=cell_width,
            cell_height=cell_height,
            band_label=geometry.clock_band_label_height,
        )

    def cell_origin(self, minute: int) -> tuple[float, float]:
        row = minute // CLOCK_COLUMNS
        band = 0 if minute <= HALFTIME_MINUTE else 1
        return (
            self.cells_left + (minute % CLOCK_COLUMNS) * self.cell_width,
            self.cells_top + (band + 1) * self.band_label
            + row * self.cell_height,
        )


def draw_clock_track(sheet: Sheet, geometry: JumbotronGeometry) -> None:
    """
    The whole game's minutes, in rows of eight under a band per half --
    the frame, the two half labels and the cells, in that order.

    **The overrun has no cells, and no note either.** The clock runs
    past a period's last minute for as long as its last possession
    does, and a track drawn for that would be a row of squares nobody
    can say the length of. The second half's last row is a cell short
    and that slot is left empty: what it used to spell out is already
    said twice over, by the caption under 15 and 30 and by the footer
    under the whole board.
    """
    track = ClockTrackGeometry.for_jumbotron(geometry)
    draw_clock_track_frame(sheet, track)
    draw_clock_half_bands(sheet, track)
    draw_clock_cells(sheet, track)


def draw_clock_track_frame(sheet: Sheet, track: ClockTrackGeometry) -> None:
    sheet.rect(
        (
            track.left,
            track.top,
            track.right,
            track.bottom,
        ),
        radius=sheet.u(10),
        fill=PANEL_COLOR,
        outline=PANEL_EDGE,
        width=sheet.u(2),
    )
    sheet.text(
        (track.cells_left, track.top + sheet.u(10)),
        "CLOCK  ·  SPACE MINUTES",
        sheet.font(17, bold=True),
        MUTED,
    )


def draw_clock_half_bands(sheet: Sheet, track: ClockTrackGeometry) -> None:
    band_face = sheet.font(17, bold=True)
    for band, (first, last_minute) in enumerate(
        ((0, HALFTIME_MINUTE), (HALFTIME_MINUTE + 1, CLOCK_MINUTES))
    ):
        label_top = track.cell_origin(first)[1] - track.band_label
        sheet.text(
            (track.cells_left, label_top + track.band_label * 0.1),
            f"{'FIRST' if not band else 'SECOND'} HALF  ·  "
            f"{first:02d}-{last_minute:02d}",
            band_face,
            INK,
        )


def draw_clock_cells(sheet: Sheet, track: ClockTrackGeometry) -> None:
    """
    Each half's **last** minute is bordered and captioned, because
    reaching it is the one thing on this board that changes what a coach
    may do -- see "Last possession".
    """
    number_face = sheet.font(28, bold=True)
    for minute in range(CLOCK_MINUTES + 1):
        cell_left, cell_top = track.cell_origin(minute)
        last = minute in (HALFTIME_MINUTE, CLOCK_MINUTES)
        sheet.rect(
            (
                cell_left + sheet.u(4),
                cell_top + sheet.u(4),
                cell_left + track.cell_width - sheet.u(4),
                cell_top + track.cell_height - sheet.u(4),
            ),
            radius=sheet.u(8),
            fill=FACE_COLOR,
            outline=OFFENSE_COLOR if last else PANEL_EDGE,
            width=sheet.u(3.5 if last else 1.6),
        )
        # A number sits in the middle of its own cell. Only the two
        # captioned cells lift it, and only far enough to leave the
        # caption a line -- every other minute is a plain box with a
        # plain number centred in it, which is most of the track. The
        # size is what the *captioned* cells hold: a number tall enough
        # to crowd its own border is the one thing this panel cannot
        # afford, since the border is what says "last possession".
        sheet.text(
            (
                cell_left + track.cell_width / 2,
                cell_top + track.cell_height * (0.40 if last else 0.5),
            ),
            f"{minute:02d}",
            number_face,
            INK if last else MUTED,
            anchor="mm",
        )
        if last:
            caption = "last possession"
            sheet.text(
                (
                    cell_left + track.cell_width / 2,
                    cell_top + track.cell_height * 0.71,
                ),
                caption,
                sheet.fitted_font(
                    caption, track.cell_width * 0.78, 14, bold=True
                ),
                OFFENSE_COLOR,
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
        (geometry.cells_left, geometry.score_top + sheet.u(10)),
        "SCORE",
        sheet.font(17, bold=True),
        MUTED,
    )

    label_width = geometry.score_label_width
    cells_left = geometry.cells_left + label_width
    cell_width, row_height = geometry.score_cell()
    rows_top = geometry.score_top + geometry.label_height
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
            (geometry.cells_left, row_top + row_height / 2),
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


def draw_token_supplies(sheet: Sheet, geometry: JumbotronGeometry) -> None:
    """
    Three silos: the exhaustion stock, and the two markers a player's
    tokens turn them into. They are the game's loose pieces and the one
    thing on the table that had nowhere printed to live -- unlike a
    minute or a goal, which have a track, or a player's own tokens,
    which go on their card.

    **A silo is a token wide, half again as tall, and says nothing.**
    It is a place to stand a stack, not a cell to read: the token's own
    art is printed at the bottom as the base of the stack, and a coach
    piles the pieces on top of it. A caption would be naming a piece the
    coach is holding a copy of, and a well the width of a third of the
    sheet would be a heap rather than a stack.

    The trio is centred, so the space either side reads as the tray it
    is rather than as a list that stopped early.
    """
    sheet.rect(
        (
            geometry.left,
            geometry.supply_top,
            geometry.right,
            geometry.supply_bottom,
        ),
        radius=sheet.u(10),
        fill=PANEL_COLOR,
        outline=PANEL_EDGE,
        width=sheet.u(2),
    )
    sheet.text(
        (geometry.cells_left, geometry.supply_top + sheet.u(8)),
        "TOKENS",
        sheet.font(17, bold=True),
        MUTED,
    )

    silo_width, silo_height = geometry.supply_cell()
    gap = silo_width * 0.5
    span = len(TOKEN_SUPPLIES) * silo_width + (len(TOKEN_SUPPLIES) - 1) * gap
    silos_left = (geometry.left + geometry.right - span) / 2
    silos_top = geometry.supply_bottom - geometry.padding - silo_height

    for index, name in enumerate(TOKEN_SUPPLIES):
        left = silos_left + index * (silo_width + gap)
        sheet.rect(
            (left, silos_top, left + silo_width, silos_top + silo_height),
            radius=sheet.u(8),
            fill=FACE_COLOR,
            outline=PANEL_EDGE,
            width=sheet.u(1.6),
        )
        art = load_token_art(name)
        if art is None:
            continue
        inset = silo_width * 0.08
        sheet.paste(
            art,
            (
                left + inset,
                silos_top + silo_height - silo_width + inset,
                left + silo_width - inset,
                silos_top + silo_height - inset,
            ),
        )


def load_token_art(name: str) -> Optional[Image.Image]:
    """
    A condition token at its own resolution, for print.

    `render.py`'s loaders thumbnail these to 26 pixels for the bot's
    board and cache them there, so a print has to open the file itself
    -- the same art, at a size a printer can use. A missing file leaves
    the silo empty rather than failing the board: it is a place to put
    a stack either way.
    """
    try:
        with Image.open(TOKEN_SUPPLY_ICONS[name]) as source:
            return source.convert("RGBA")
    except OSError:
        return None


# ----------------------------------------------------------- team board

# **A coach's board is half a sheet, cut across: two boards to a page,
# one for each coach.** The old board stacked two panels on a tabloid
# sheet for the same reason, and the reason it is letter now is that
# letter is the one size every printer in the house has in it; the
# board that came off the tabloid sheet was laid out in a mix of
# sheet-relative and fixed-inch measurements, which is what put a title
# through a line and a caption on top of its neighbour. See "The team
# board" in docs/design/printed-boards.md.
TEAM_BOARD_PAPER = "letter"

# **Every size on this board is an inch of printed paper**, never a
# share of the sheet. The board is one physical thing a coach reads at
# arm's length, so what matters is how big a word comes off a printer,
# and a band measured in inches with the text in it measured as a share
# of the sheet's width is exactly how a line of type came to be drawn
# through the rule under it.
#
# Six sizes, and nothing between them: the board's own title, a team's
# name, a cell's title, a cell's caption, body text, and the small
# print in the footer. A seventh size is a change to this list, not a
# number written into a call.
TEAM_TITLE_INCHES = 0.26
TEAM_NAME_INCHES = 0.20
TEAM_CELL_TITLE_INCHES = 0.165
TEAM_CAPTION_INCHES = 0.105
TEAM_BODY_INCHES = 0.12
TEAM_SMALL_INCHES = 0.115

# The margin the board keeps to the cut, and the gaps between its three
# bands.
TEAM_MARGIN_INCHES = 0.26
TEAM_HEADER_GAP_INCHES = 0.10
TEAM_FOOTER_GAP_INCHES = 0.16
TEAM_COLUMN_GAP_INCHES = 0.16
TEAM_AREA_PADDING_INCHES = 0.11
# The rule under the header, in the team's own colour, and the air
# over it: a line of type is measured from its own ascender, so a rule
# set at the leading of the line above it lands on that line's
# descenders. The old header drew it straight through them.
TEAM_RULE_INCHES = 0.018
TEAM_RULE_GAP_INCHES = 0.055
# Between the footer's three blocks -- the shapes, the deal, and the
# two reminders -- over and above each block's own leading.
TEAM_FOOTER_LINE_GAP_INCHES = 0.05
# Leading, as a multiple of a line's own size. A heading sits closer to
# what it heads than body copy does to the next line of itself.
TEAM_TITLE_LEADING = 1.15
TEAM_LINE_LEADING = 1.4
# The d12 badge in the footer, drawn rather than named: it is the one
# component a coach keeps beside the cards.
TEAM_DIE_INCHES = 0.17
# The dashed line down the seam of the two-up page. It is on the seam
# and so on the edge of both boards, which is the one place a mark
# belongs on a sheet that is about to be cut in half.
TEAM_CUT_INCHES = 0.01


def print_font(inches: float, bold: bool = False) -> ImageFont.ImageFont:
    """
    A font at a printed height, in inches. `Sheet.font` sizes against
    the sheet's own width, which is the right unit for a board whose
    layout scales whole and the wrong one for a board sized in inches
    -- see `TEAM_TITLE_INCHES`.
    """
    return load_font(max(6, round(inches * PRINT_DPI)), bold=bold)


def fitted_print_font(
    sheet: Sheet,
    text: str,
    max_width: float,
    inches: float,
    bold: bool = False,
    minimum: float = 0.085,
) -> Optional[ImageFont.ImageFont]:
    """
    The largest printed size at or below `inches` whose `text` fits,
    or **None** if it would have to go below `minimum` to fit.

    Returning nothing rather than something illegible is the rule the
    old board broke: a caption shrunk until it fit read as a smudge,
    and a smudge is a worse answer than a caption the layout has to be
    changed to carry. Every caller either drops the line or wraps it.
    """
    size = inches
    while size >= minimum:
        face = print_font(size, bold=bold)
        if sheet.text_width(text, face) <= max_width:
            return face
        size -= 0.005
    return None


def draw_fitted(
    sheet: Sheet,
    position: tuple[float, float],
    text: str,
    max_width: float,
    inches: float,
    fill: str,
    bold: bool = False,
    anchor: str = "la",
    minimum: float = 0.085,
) -> None:
    """
    A line that has to be drawn, at the largest printed size that fits
    it -- and at `minimum` if nothing does, which is the last resort
    rather than the layout: every line here is measured against the
    room it has, and one that only fits at the floor is a line the
    band has to be re-cut for.
    """
    face = fitted_print_font(
        sheet, text, max_width, inches, bold=bold, minimum=minimum
    ) or print_font(minimum, bold=bold)
    sheet.text(position, text, face, fill, anchor=anchor)


@dataclass(frozen=True)
class TeamBoardGeometry:
    """
    One coach's board: a header, a row of three cells -- the bench, the
    back bench and the head coach -- and a footer.

    **The three cells are one row of equal columns**, and the row takes
    whatever the header and the footer leave. Both of those are a fixed
    number of lines at a fixed printed size, so they are measured off
    their own type rather than given a share of the sheet: a header is
    the same two lines on any paper, and a line that does not fit its
    band is the bug this layout replaced.

    `slot` is the card guide drawn inside a bench, capped at a real
    poker card so a bigger sheet gives a roomier area rather than an
    outsized guide. `card_slot_inches` reports it, and at half a letter
    sheet it comes out under a poker card: the head, the footer and two
    legible cell labels do not leave 3.5 inches between them, and the
    author's call was legible over life-size. A coach stacks their
    bench on the area, which is a real card wide either way.
    """

    left: float
    right: float
    top: float
    bottom: float
    roster_top: float
    rule_top: float
    columns: tuple[tuple[float, float], ...]
    label_top: float
    caption_top: float
    area_top: float
    area_bottom: float
    slot: tuple[float, float]
    reference: tuple[float, float]
    footer_top: float
    footer_lines: tuple[float, float, float]

    @classmethod
    def for_sheet(cls, sheet: Sheet) -> "TeamBoardGeometry":
        def inches(value: float) -> float:
            return value * PRINT_DPI

        margin = inches(TEAM_MARGIN_INCHES)
        left = margin
        right = sheet.width - margin
        top = margin
        bottom = sheet.height - margin

        # The header is its two lines and the rule under them.
        roster_top = top + inches(TEAM_TITLE_INCHES * TEAM_TITLE_LEADING)
        rule_top = roster_top + inches(
            TEAM_BODY_INCHES * TEAM_LINE_LEADING + TEAM_RULE_GAP_INCHES
        )

        # **The footer's own lines are measured here**, not in the
        # routine that draws them: the band and the lines in it are one
        # measurement, and the old footer was two -- a band in inches
        # and lines placed in sheet units, which is how the deal and
        # the reminder came to be drawn below the bottom of the board
        # and cropped away without a mark on the render.
        deal_offset = inches(
            TEAM_BODY_INCHES * TEAM_LINE_LEADING + TEAM_FOOTER_LINE_GAP_INCHES
        )
        reminder_offset = deal_offset + inches(
            TEAM_BODY_INCHES * TEAM_LINE_LEADING + TEAM_FOOTER_LINE_GAP_INCHES
        )
        footer_height = reminder_offset + inches(
            2 * TEAM_SMALL_INCHES * TEAM_LINE_LEADING
        )
        footer_top = bottom - footer_height

        label_top = rule_top + inches(
            TEAM_RULE_INCHES + TEAM_HEADER_GAP_INCHES
        )
        caption_top = label_top + inches(
            TEAM_CELL_TITLE_INCHES * TEAM_TITLE_LEADING
        )
        # **The row is never taller than the cards in it.** On half a
        # letter sheet it is shorter, and the cells take what there is;
        # on a bigger sheet the leftover goes under the row as air
        # rather than into the cells, because a cell taller than the
        # card it holds is a card at the top of an empty box -- and the
        # reference is capped at the card's own size regardless, since
        # it is drawn at 300dpi and printing it larger only softens it.
        area_top = caption_top + inches(
            TEAM_CAPTION_INCHES * TEAM_LINE_LEADING
        )
        area_bottom = min(
            footer_top - inches(TEAM_FOOTER_GAP_INCHES),
            area_top
            + inches(CARD_INCHES[1] + 2 * TEAM_AREA_PADDING_INCHES),
        )

        # **The head coach's column is the width of the card in it**,
        # and the two benches divide what is left. The reference is the
        # back of the maneuver card at the height the row leaves it,
        # capped at a real card (it is drawn at 300dpi and printing it
        # larger than the card would only soften it) -- so sizing the
        # column to anything else leaves either a band of empty board
        # beside the picture or a picture wider than its own cell.
        column_gap = inches(TEAM_COLUMN_GAP_INCHES)
        row_width = right - left - 2 * column_gap
        reference_height = min(area_bottom - area_top, inches(CARD_INCHES[1]))
        reference_width = (
            reference_height * CARD_INCHES[0] / CARD_INCHES[1]
        )
        bench_width = (row_width - reference_width) / 2
        columns = (
            (left, left + bench_width),
            (
                left + bench_width + column_gap,
                left + 2 * bench_width + column_gap,
            ),
            (right - reference_width, right),
        )

        padding = inches(TEAM_AREA_PADDING_INCHES)
        slot_height = min(
            area_bottom - area_top - 2 * padding,
            inches(CARD_INCHES[1]),
            (bench_width - 2 * padding) * CARD_INCHES[1] / CARD_INCHES[0],
        )
        slot_width = slot_height * CARD_INCHES[0] / CARD_INCHES[1]

        return cls(
            left=left,
            right=right,
            top=top,
            bottom=bottom,
            roster_top=roster_top,
            rule_top=rule_top,
            columns=columns,
            label_top=label_top,
            caption_top=caption_top,
            area_top=area_top,
            area_bottom=area_bottom,
            slot=(slot_width, slot_height),
            reference=(reference_width, reference_height),
            footer_top=footer_top,
            footer_lines=(
                footer_top,
                footer_top + deal_offset,
                footer_top + reminder_offset,
            ),
        )

    def area(self, column: int) -> tuple[float, float, float, float]:
        left, right = self.columns[column]
        return left, self.area_top, right, self.area_bottom


def team_board_pixels(paper: str = TEAM_BOARD_PAPER) -> tuple[int, int]:
    """
    One coach's board: half a portrait sheet, cut across its width.
    Two of them are a page -- see `render_team_board_sheet`.
    """
    width, height = sheet_pixels(paper, landscape=False)
    return width, height // 2


def card_slot_inches(paper: str = TEAM_BOARD_PAPER) -> tuple[float, float]:
    """
    How big a card the bench areas' guides are cut for, in inches. The
    CLI prints it, and it is what says whether a print can be laid
    cards on or only read.
    """
    width, height = team_board_pixels(paper)
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
    paper: str = TEAM_BOARD_PAPER,
    bleed: bool = False,
) -> Image.Image:
    """
    **One coach's board**: the bench, the back bench and the head
    coach's cell, under a header and over a footer.

    Half a letter sheet (8.5 x 5.5in), which is what makes two of them
    a page -- `render_team_board_sheet` is that page, and this is the
    board a coach who wants one per sheet prints. The three zone areas
    are the field board's (see "The zone-assignment rows" in
    docs/design/printed-boards.md), which is what leaves a board this
    short in the first place.

    `team` colours the rule under the header, the cell outlines and the
    team's own name in the corner; with no team it is all ink.
    """
    width, height = team_board_pixels(paper)
    sheet = Sheet(width, height)
    accent = TEAM_COLORS[team] if team else INK

    geometry = TeamBoardGeometry.for_sheet(sheet)

    draw_team_header(sheet, geometry, players, team, accent)
    draw_card_area(
        sheet,
        geometry,
        column=0,
        title="BENCH",
        caption="players who have yet to play",
        accent=accent,
    )
    draw_card_area(
        sheet,
        geometry,
        column=1,
        title="BACK BENCH",
        caption="injured players, and anyone subbed out",
        accent=accent,
    )
    draw_head_coach_panel(sheet, geometry, maneuvers)
    draw_team_footer(sheet, geometry, rules, accent)

    return add_bleed(sheet.image) if bleed else sheet.image


def render_team_board_sheet(
    rules: BasicRuleset,
    players: PlayerCatalog,
    maneuvers: ManeuverCatalog,
    team: Optional[Team] = None,
    paper: str = TEAM_BOARD_PAPER,
    bleed: bool = False,
) -> Image.Image:
    """
    **A match's two boards on one page**, cut across the middle -- the
    same board twice, since the two coaches' boards are
    interchangeable: `team` colours both or neither, and a match whose
    two sides want their own colours prints two pages.

    The board is drawn once and pasted twice rather than rendered
    twice, which is what makes the two halves the same picture by
    construction rather than by hoping two renders agree.
    """
    width, height = sheet_pixels(paper, landscape=False)
    sheet = Sheet(width, height)
    board = render_team_board(
        rules, players, maneuvers, team=team, paper=paper
    )
    sheet.image.paste(board, (0, 0))
    sheet.image.paste(board, (0, height - board.height))
    draw_cut_line(sheet, board.height)

    return add_bleed(sheet.image) if bleed else sheet.image


def draw_cut_line(sheet: Sheet, y: float) -> None:
    """Where to cut the page in two, and nothing else on the seam."""
    draw_dashed_line(
        sheet.draw,
        0,
        round(y),
        sheet.width,
        round(y),
        fill=PANEL_EDGE,
        width=max(1, round(TEAM_CUT_INCHES * PRINT_DPI)),
        dash_length=round(0.10 * PRINT_DPI),
        gap_length=round(0.08 * PRINT_DPI),
    )


def draw_team_header(
    sheet: Sheet,
    geometry: TeamBoardGeometry,
    players: PlayerCatalog,
    team: Optional[Team],
    accent: str,
) -> None:
    """
    The board's own title and the team's name on one line, the roster
    under them, and the rule under that.

    **The roster line is wrapped to what the title leaves**, not fitted
    to it: the line names nine cards by role and is the first thing on
    the board a coach actually reads. It used to be drawn at whatever
    width it came out at and ran straight through the rule below.
    """
    title_font = print_font(TEAM_TITLE_INCHES, bold=True)
    sheet.text((geometry.left, geometry.top), "TEAM BOARD", title_font, INK)

    # .replace before .upper(), not team_display_name (which title-
    # cases): an underscored team's value needs the same space an
    # ordinary one gets nowhere, but this header is deliberately all
    # caps, unlike everywhere team_display_name is used.
    name = team.value.replace("_", " ").upper() if team else "TEAM"
    title_width = sheet.text_width("TEAM BOARD", title_font)
    draw_fitted(
        sheet,
        (geometry.right, geometry.top + 0.04 * PRINT_DPI),
        name,
        geometry.right - geometry.left - title_width - 0.3 * PRINT_DPI,
        TEAM_NAME_INCHES,
        accent,
        bold=True,
        anchor="ra",
    )
    draw_fitted(
        sheet,
        (geometry.left, geometry.roster_top),
        roster_line(players),
        geometry.right - geometry.left,
        TEAM_BODY_INCHES,
        MUTED,
    )

    sheet.rect(
        (
            geometry.left,
            geometry.rule_top,
            geometry.right,
            geometry.rule_top + TEAM_RULE_INCHES * PRINT_DPI,
        ),
        fill=accent,
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
        f"Six of your {len(roster)} on the field, three on the bench: "
        + " · ".join(parts)
    )


def draw_cell_label(
    sheet: Sheet,
    geometry: TeamBoardGeometry,
    column: int,
    title: str,
    caption: str,
) -> None:
    """
    A cell's name, with what belongs in it on the line under it.

    **The caption is a second line, not the right-hand end of the
    first.** Sharing one line is what put "players who have yet to
    play" hard against the next cell's title, and a caption squeezed
    into what a title leaves has no width of its own to be legible in.
    A column is wide enough for either line on its own.
    """
    left, right = geometry.columns[column]
    draw_fitted(
        sheet,
        (left, geometry.label_top),
        title,
        right - left,
        TEAM_CELL_TITLE_INCHES,
        INK,
        bold=True,
    )

    caption_font = fitted_print_font(
        sheet, caption, right - left, TEAM_CAPTION_INCHES
    )
    if caption_font is not None:
        sheet.text(
            (left, geometry.caption_top), caption, caption_font, MUTED
        )


def draw_card_area(
    sheet: Sheet,
    geometry: TeamBoardGeometry,
    column: int,
    title: str,
    caption: str,
    accent: str,
) -> None:
    """
    One area a coach's cards sit in, with a card's own footprint
    dashed inside it.

    **One guide, not a fan of three.** A bench holds three cards
    between them and the old board fanned three outlines across a
    column five inches wide; half a letter sheet gives a column two
    and a half, which is one card and no fan. The cards stack -- the
    guide is where the stack goes, and the area around it is the room
    to square them up.
    """
    left, right = geometry.columns[column]
    draw_cell_label(sheet, geometry, column, title, caption)

    area = geometry.area(column)
    sheet.rect(
        area,
        radius=0.08 * PRINT_DPI,
        fill=PANEL_COLOR,
        outline=accent,
        width=max(1, round(0.012 * PRINT_DPI)),
    )

    slot_width, slot_height = geometry.slot
    slot_left = (left + right - slot_width) / 2
    slot_top = (area[1] + area[3] - slot_height) / 2
    sheet.dashed_rect(
        (slot_left, slot_top, slot_left + slot_width, slot_top + slot_height),
        outline=PANEL_EDGE,
        width=max(1, round(0.01 * PRINT_DPI)),
        dash=0.055 * PRINT_DPI,
    )


def draw_head_coach_panel(
    sheet: Sheet,
    geometry: TeamBoardGeometry,
    maneuvers: ManeuverCatalog,
) -> None:
    """
    The third cell: **the back of the maneuver card, printed on the
    board**.

    It is the same picture `render_maneuver_card_back` draws for the
    deck -- the six ranks on one cycle, each node carrying the basic
    card over its gambit, with a solid arrow to what it beats and a
    dashed one to what it ties. A coach reading a matchup off the board
    and a coach reading it off the card in their hand are reading one
    picture, which is the whole reason it is pasted rather than redrawn
    here: a second drawing of the cycle is a second thing to keep true
    when a rank changes.

    It replaces the two columns of names the cell used to carry, which
    said which maneuver was which rank and nothing about what beat
    what, in type a third the size of the heading over it.

    **No frame around it.** The card has its own, and the cell's would
    be a second border a tenth of an inch outside the first -- the
    corners are cut instead, so the board's own cream shows around it
    the way it does around a real card lying on the board rather than
    leaving four white squares.
    """
    draw_cell_label(
        sheet,
        geometry,
        column=2,
        title="HEAD COACH",
        caption="both coaches play one face down",
    )
    art = rounded_corners(
        render_maneuver_card_back(maneuvers, bleed=False),
        CARD_CORNER_RADIUS,
    )
    left, top, right, _ = geometry.area(2)
    sheet.paste(art, (left, top, right, top + geometry.reference[1]))


def rounded_corners(art: Image.Image, radius: float) -> Image.Image:
    """
    A card's corners cut out of its own background, at the radius the
    card itself is drawn with -- `Sheet.paste` takes an RGBA image as
    its own mask, so what is cut here is what the board shows through.
    """
    cut = art.convert("RGBA")
    mask = Image.new("L", cut.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, cut.width - 1, cut.height - 1),
        radius=round(radius),
        fill=255,
    )
    cut.putalpha(mask)
    return cut


def formation_strip_segments(
    rules: BasicRuleset,
) -> list[tuple[str, bool, float]]:
    """
    What the strip says, as (text, muted, the gap in **inches** that
    follows it) -- the heading, then the shapes every board plays, then
    each group of shapes that needs a particular board under a label
    saying which.

    **A shape's name is its counts**, which `load_basic_ruleset`
    checks, so the strip prints the names alone: the `(2 / 3 / 1)` that
    used to follow each one restated the same three digits, and five
    shapes with it no longer fit the strip.

    One team board is printed for every field size, so the shapes only
    some boards play are on it, grouped, rather than left off --
    `board_sizes` in `basic_rules.json`, never a size written out here.
    """
    universal: list[str] = []
    restricted: dict[str, list[str]] = {}
    for formation, shape in rules.formations.items():
        if shape.board_sizes is None:
            universal.append(formation.value)
        else:
            restricted.setdefault(
                f"{shape.board_size_label().upper()} BOARD ONLY", []
            ).append(formation.value)

    segments: list[tuple[str, bool, float]] = [
        ("FORMATIONS — READ FROM YOUR OWN GOAL", True, 0.13)
    ]
    segments.extend((name, False, 0.14) for name in universal)
    for label, names in restricted.items():
        segments.append((label, True, 0.08))
        segments.extend((name, False, 0.14) for name in names)
    return segments


def draw_formation_strip(
    sheet: Sheet,
    rules: BasicRuleset,
    left: float,
    top: float,
    right: float,
) -> float:
    """
    The shapes, as a strip rather than a table -- there is no cell left
    to put a table in, and three numbers a shape reads perfectly well
    in a line. Returns the x it drew out to, which is what says it fit.

    A formation is read from a coach's own goal forward, which is the
    one thing on this board that is not absolute, and is why the label
    says so.

    **The strip is measured before it is drawn**, and shrinks whole
    rather than running off the edge of the board: a shape added
    upstream lands here without anybody measuring, and there is no
    second row to give it.
    """
    segments = formation_strip_segments(rules)

    scale = 1.0
    while True:
        faces = {
            muted: print_font(
                TEAM_BODY_INCHES * (0.92 if muted else 1.0) * scale, bold=True
            )
            for muted in (True, False)
        }
        width = sum(
            sheet.text_width(text, faces[muted])
            for text, muted, _ in segments
        ) + sum(gap * PRINT_DPI * scale for _, _, gap in segments[:-1])
        if width <= right - left or scale <= 0.5:
            break
        scale -= 0.05

    cursor = left
    for index, (text, muted, gap) in enumerate(segments):
        sheet.text((cursor, top), text, faces[muted], MUTED if muted else INK)
        cursor += sheet.text_width(text, faces[muted])
        if index < len(segments) - 1:
            cursor += gap * PRINT_DPI * scale
    return cursor


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


def team_reminders(rules: BasicRuleset) -> tuple[str, str]:
    """
    The two lines beside the die badge: what the die is for, and the
    two things about a card on this board that are not on it.

    **The die's faces are read from the ruleset**, never written here
    -- the board may not claim a component the bot does not play. It is
    the one die a coach keeps: the selection d6s the ruleset still
    defines are not on this board and are not in the rules any more
    (see "The printed boards" in docs/design/printed-boards.md).
    """
    die = rules.team_board.team_die
    return (
        f"Every roll in the game is a d{die.sides}: "
        "skill tests, shots, injury checks.",
        "A card's zone is assigned on the field board. A player is "
        "Exhausted once their tokens exceed their defence.",
    )


def draw_die_badge(
    sheet: Sheet,
    rules: BasicRuleset,
    center: tuple[float, float],
    accent: str,
) -> None:
    """
    The die a coach keeps, drawn at the size of the two lines it sits
    beside: a shape on the board rather than a word in a sentence,
    because it is a component they have to find in the box.
    """
    die = rules.team_board.team_die
    radius = TEAM_DIE_INCHES * PRINT_DPI
    sheet.polygon(
        polygon_points(center[0], center[1], radius, die.sides),
        fill=FACE_COLOR,
        outline=accent,
        width=max(1, round(0.012 * PRINT_DPI)),
    )
    draw_fitted(
        sheet,
        center,
        f"d{die.sides}",
        radius * 1.4,
        TEAM_BODY_INCHES,
        accent,
        bold=True,
        anchor="mm",
    )


def draw_team_footer(
    sheet: Sheet,
    geometry: TeamBoardGeometry,
    rules: BasicRuleset,
    accent: str = INK,
) -> None:
    """
    The shapes, the deal, and the two reminders beside the die.

    **Every line is drawn at a printed size and the band is measured
    off those sizes**, so the last line lands above the bottom of the
    board rather than off it -- the old footer put the deal and the
    reminder below the edge of the panel, where they were silently
    cut away by the crop.
    """
    strip_line, deal_line, reminder_line = geometry.footer_lines
    draw_formation_strip(
        sheet, rules, geometry.left, strip_line, geometry.right
    )

    draw_fitted(
        sheet,
        (geometry.left, deal_line),
        standard_deal_line(rules),
        geometry.right - geometry.left,
        TEAM_BODY_INCHES,
        INK,
    )

    pitch = TEAM_SMALL_INCHES * TEAM_LINE_LEADING * PRINT_DPI
    indent = geometry.left + TEAM_DIE_INCHES * 2.6 * PRINT_DPI
    draw_die_badge(
        sheet,
        rules,
        (
            geometry.left + TEAM_DIE_INCHES * PRINT_DPI,
            reminder_line + pitch * 0.85,
        ),
        accent,
    )
    for index, text in enumerate(team_reminders(rules)):
        draw_fitted(
            sheet,
            (indent, reminder_line + index * pitch),
            text,
            geometry.right - indent,
            TEAM_SMALL_INCHES,
            MUTED,
        )
