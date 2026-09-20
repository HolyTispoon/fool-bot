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
    DEFENSE_COLOR,
    FACE_COLOR,
    INK,
    MUTED,
    OFFENSE_COLOR,
    PANEL_COLOR,
    PANEL_EDGE,
)
from d12ball.components import (
    MANEUVER_TIER_BASIC,
    BasicRuleset,
    BoardLayout,
    BoardState,
    ManeuverCatalog,
    ManeuverDefinition,
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

# Sheet sizes in inches, portrait. The field board is drawn landscape
# and the team board portrait, which is what `sheet_pixels` swaps for.
#
# **Tabloid (11 x 17in, the common US "ledger" print size) is the
# default now**, over A3: it is the size a home or copy-shop printer
# actually stocks in the US, where A3 is the size these boards were
# first designed at and is still the only one whose team board takes a
# real card (two rows of 3.5in cards plus a header and a footer is 11.3
# inches, and tabloid's 11in short side comes out a card area short
# however the bands are trimmed -- the author's call, made knowing that
# trade). A4 and letter are proofs to read rather than boards to lay
# cards on at any size. `card_slot_inches` is what tells a caller which
# of the three it has.
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
    # `CARDS_PER_AREA` is a visual cue borrowed from the team board's
    # own areas rather than a limit enforced here.
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
    it from four different bands (the frame, the two half labels, the
    cells and the overrun note) that all have to agree on the same
    cells.

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
    the frame, the two half labels, the cells and the overrun note, in
    that order.
    """
    track = ClockTrackGeometry.for_jumbotron(geometry)
    draw_clock_track_frame(sheet, track)
    draw_clock_half_bands(sheet, track)
    draw_clock_cells(sheet, track)
    draw_clock_overrun_note(sheet, track)


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
    number_face = sheet.font(38, bold=True)
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
        caption = (
            "last possession"
            if last
            else "kickoff"
            if minute == 0
            else "second-half kickoff"
            if minute == HALFTIME_MINUTE + 1
            else None
        )
        # A number sits in the middle of its own cell. Only the four
        # captioned cells lift it, and only far enough to leave the
        # caption a line -- every other minute is a plain box with a
        # plain number centred in it, which is most of the track.
        sheet.text(
            (
                cell_left + track.cell_width / 2,
                cell_top + track.cell_height * (0.4 if caption else 0.5),
            ),
            f"{minute:02d}",
            number_face,
            INK if last else MUTED,
            anchor="mm",
        )
        if caption:
            sheet.text(
                (
                    cell_left + track.cell_width / 2,
                    cell_top + track.cell_height * 0.76,
                ),
                caption,
                sheet.fitted_font(
                    caption, track.cell_width * 0.82, 16, bold=last
                ),
                OFFENSE_COLOR if last else MUTED,
                anchor="mm",
            )


def draw_clock_overrun_note(sheet: Sheet, track: ClockTrackGeometry) -> None:
    """
    **The overrun has no cells.** The clock runs past a period's last
    minute for as long as its last possession does, and a track drawn
    for that would be a row of squares nobody can say the length of; a
    token sitting on 15 or 30 is a period playing itself out, and the
    caption under those two says so in words.

    The second half is a cell short of its second row, which the spare
    slot says outright rather than leaving as a track that ran out --
    at the end of the second half's last row, which is where a coach
    looks when the token is about to run off the track.
    """
    spare_left, spare_top = track.cell_origin(CLOCK_MINUTES)
    spare_left += track.cell_width
    for offset, line in (
        (0.36, "PAST " + f"{CLOCK_MINUTES:02d}"),
        (0.62, "keep the token here;"),
        (0.80, "last possession plays on"),
    ):
        sheet.text(
            (
                spare_left + track.cell_width / 2,
                spare_top + track.cell_height * offset,
            ),
            line,
            sheet.fitted_font(
                line, track.cell_width * 0.86, 22 if offset == 0.36 else 15,
                bold=offset == 0.36,
            ),
            MUTED,
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


@dataclass(frozen=True)
class TeamBoardGeometry:
    """
    The team board's three cells: the bench, the back bench and the
    head coach, in one row.

    **It used to be six -- the three zones across the top as well.**
    Those moved to the field board (see "The zone-assignment rows" in
    docs/design/printed-boards.md), which is what let two of these boards -- one for each
    coach -- share a single sheet instead of each wanting one of its
    own: dropping the zone row cut what a board needs to a single row
    a card tall plus a header and a footer, which is a good deal short
    of half of even the shorter side of an 11 x 17 sheet.

    `slot` is the card guide drawn inside an area, capped at a real
    poker card so a bigger panel gives a roomier area rather than an
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
        # Fixed inches, not a share of `content` -- a panel's own
        # height is now half a landscape sheet's rather than a whole
        # one, and a header sized as a percentage of that shrinks with
        # it for no reason: the title is the same few words at any
        # panel height, and the row below it is the one thing here
        # that actually has to hold a fixed real-world size (a poker
        # card). Sizing the header and footer in inches is what lets
        # the row take the rest, exactly the way the old percentages
        # meant to but stopped doing once panels got much shorter.
        margin = round(0.25 * PRINT_DPI)
        header = round(0.38 * PRINT_DPI)
        footer = round(0.38 * PRINT_DPI)
        gap = round(0.1 * PRINT_DPI)

        left = margin
        right = sheet.width - margin
        top = margin
        bottom = sheet.height - margin
        content = bottom - top
        row_height = content - header - footer - 2 * gap

        header_bottom = top + header
        rows = ((header_bottom + gap, header_bottom + gap + row_height),)
        column_gap = sheet.u(20)
        column_width = (right - left - 2 * column_gap) / 3
        columns = tuple(
            (
                left + index * (column_width + column_gap),
                left + index * (column_width + column_gap) + column_width,
            )
            for index in range(3)
        )

        label_height = round(0.28 * PRINT_DPI)
        padding = round(0.08 * PRINT_DPI)
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

    def area(self, column: int, row: int = 0) -> tuple[float, float, float, float]:
        left, right = self.columns[column]
        top, bottom = self.rows[row]
        return left, top + self.label_height, right, bottom


def card_slot_inches(paper: str = DEFAULT_PAPER) -> tuple[float, float]:
    """
    How big a card the team board's areas are cut for, in inches. The
    CLI prints it, and it is what says whether a print can be laid
    cards on or only read.

    Measured against one panel -- half the sheet's own height, since
    two coaches' boards share the one sheet -- not the whole sheet,
    which is what `render_team_board` actually cuts each area from.
    """
    width, height = sheet_pixels(paper, landscape=True)
    geometry = TeamBoardGeometry.for_sheet(Sheet(width, height // 2))
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
    Two coaches' boards, one sheet: each panel is the bench, the back
    bench and the head coach's cell -- the three zone areas moved to
    the field board (see "The zone-assignment rows" in docs/design/printed-boards.md),
    which is what leaves a panel short enough that two of them, one
    for each side of a match, share a single 11 x 17 sheet cut in
    half rather than each wanting a sheet of its own.

    **Landscape, unlike the field board.** Stacking the two panels top
    to bottom over the sheet's own *short* side (11in) leaves each one
    a real card's width to spare in every column; over the *long* side
    (17in, which is what a portrait sheet's width would give the row
    to divide three ways) a fanned poker card comes out narrower than
    the card itself.

    `team` only colours it, the same on both panels -- a match's two
    boards are printed and cut from the one sheet whichever side is
    on it, so there is nothing here for two different teams to color
    two different panels by.
    """
    width, height = sheet_pixels(paper, landscape=True)
    sheet = Sheet(width, height)
    panel_height = height // 2
    for index in range(2):
        panel = render_team_board_panel(
            rules, players, maneuvers, team, width, panel_height,
        )
        sheet.image.paste(panel, (0, index * panel_height))

    return add_bleed(sheet.image) if bleed else sheet.image


def render_team_board_panel(
    rules: BasicRuleset,
    players: PlayerCatalog,
    maneuvers: ManeuverCatalog,
    team: Optional[Team],
    width: int,
    height: int,
) -> Image.Image:
    """One coach's own panel -- see `render_team_board`."""
    sheet = Sheet(width, height, background=FACE_COLOR)
    geometry = TeamBoardGeometry.for_sheet(sheet)
    accent = TEAM_COLORS[team] if team else INK

    draw_team_header(sheet, geometry, players, team, accent)
    draw_card_area(
        sheet,
        geometry,
        column=0,
        title="BENCH",
        caption="players who have yet to play",
        tint=PANEL_COLOR,
        accent=accent,
    )
    draw_card_area(
        sheet,
        geometry,
        column=1,
        title="BACK BENCH",
        caption="injured players, and anyone subbed out",
        tint=PANEL_COLOR,
        accent=accent,
    )
    draw_head_coach_panel(sheet, geometry, rules, maneuvers, accent)
    draw_team_footer(sheet, geometry, rules)

    return sheet.image


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
    # Sized in fixed points off `load_font` directly, not `sheet.font`
    # -- that scales with the *sheet's* own width, which is still the
    # full 17in a panel spans even though the header above the row
    # shrank to a fixed 0.38in tall. A title sized to the sheet came
    # out taller than the header holding it.
    title_font = load_font(round(0.24 * PRINT_DPI), bold=True)
    sheet.text((geometry.left, top), "TEAM BOARD", title_font, INK)
    sheet.text(
        (geometry.left, top + round(0.24 * PRINT_DPI)),
        roster_line(players),
        load_font(round(0.11 * PRINT_DPI)),
        MUTED,
    )
    # .replace before .upper(), not team_display_name (which title-
    # cases): an underscored team's value needs the same space an
    # ordinary one gets nowhere, but this header is deliberately all
    # caps, unlike everywhere team_display_name is used.
    name = team.value.replace("_", " ").upper() if team else "TEAM"
    sheet.text(
        (geometry.right, top),
        name,
        load_font(round(0.22 * PRINT_DPI), bold=True),
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
    The third cell: the coach's own d12, and the six maneuvers they
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
        title="HEAD COACH",
        caption="your die, and your maneuvers",
    )
    area = geometry.area(2)
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
    the divergence. See "The printed boards" in docs/design/printed-boards.md.
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
    The maneuvers, by the rank the matchup table names them by. This is
    a coach's hand, not a die's faces -- the cards carry the effects, so
    what belongs here is only which is which.

    **Three rows a column, however many cards there are.** A rank
    carries one card per tier and rank alone decides who beats whom, so
    a row is a rank with both its names on it -- the basic card, and
    its gambit under the same number. Twelve rows in a
    panel sized for three is what listing them per card would give, and
    it would print two O1s with nothing saying they are the same rank.

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
    ranks = sorted({m.rank for m in maneuvers.offense})
    row_height = (bottom - rows_top) / len(ranks)
    # Sized to the row rather than to the sheet, so the lines breathe
    # on a board with room and close up on one without. A row now
    # carries two names stacked, so it takes a third of its height
    # rather than a half.
    body_size = min(18, row_height / sheet.unit * 0.34)
    rank_face = sheet.font(body_size * 1.15, bold=True)
    rank_left = sheet.u(44)

    columns = (
        ("WITH THE BALL", maneuvers.offense, OFFENSE_COLOR, "O"),
        ("CHALLENGING", maneuvers.defense, DEFENSE_COLOR, "D"),
    )
    # Every name at one size, fitted to the longest of them. Fitting
    # each on its own left "Double Team" half the height of "Clear"
    # beside it, which reads as emphasis rather than as the accident of
    # length it is.
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
        for row, rank in enumerate(ranks):
            row_y = rows_top + row_height * (row + 0.5)
            sheet.text(
                (column_left, row_y),
                f"{letter}{rank}",
                rank_face,
                color,
                anchor="lm",
            )
            # Basic over gambit, the same order and the same reason
            # as a node on the printed card back.
            on_rank = sorted(
                (m for m in side if m.rank == rank),
                key=lambda m: m.tier != MANEUVER_TIER_BASIC,
            )
            offsets = (
                (0.0,)
                if len(on_rank) == 1
                else (-row_height * 0.22, row_height * 0.22)
            )
            for maneuver, offset in zip(on_rank, offsets):
                sheet.text(
                    (column_left + rank_left, row_y + offset),
                    maneuver.name,
                    name_face,
                    INK if not maneuver.is_gambit else MUTED,
                    anchor="lm",
                )
    return bottom


def formation_strip_segments(
    rules: BasicRuleset,
) -> list[tuple[str, bool, float]]:
    """
    What the strip says, as (text, muted, the gap in units that follows
    it) -- the heading, then the shapes every board plays, then each
    group of shapes that needs a particular board under a label saying
    which.

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
        ("FORMATIONS — READ FROM YOUR OWN GOAL", True, 22)
    ]
    segments.extend((name, False, 24) for name in universal)
    for label, names in restricted.items():
        segments.append((label, True, 14))
        segments.extend((name, False, 24) for name in names)
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
            muted: sheet.font((14 if muted else 16) * scale, bold=True)
            for muted in (True, False)
        }
        width = sum(
            sheet.text_width(text, faces[muted])
            for text, muted, _ in segments
        ) + sum(sheet.u(gap * scale) for _, _, gap in segments[:-1])
        if width <= right - left or scale <= 0.5:
            break
        scale -= 0.05

    cursor = left
    for index, (text, muted, gap) in enumerate(segments):
        sheet.text((cursor, top), text, faces[muted], MUTED if muted else INK)
        cursor += sheet.text_width(text, faces[muted])
        if index < len(segments) - 1:
            cursor += sheet.u(gap * scale)
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


def draw_cell_label(
    sheet: Sheet,
    geometry: TeamBoardGeometry,
    column: int,
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
    top = geometry.rows[0][0]
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
    title: str,
    caption: str,
    tint: str,
    accent: str,
) -> None:
    """
    One area a card can be in, with three card outlines fanned across
    it. Three is what either bench ever has to hold, between them.
    """
    left, right = geometry.columns[column]
    draw_cell_label(sheet, geometry, column, title, caption)

    area = geometry.area(column)
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
    top = geometry.rows[0][1] + sheet.u(16)
    draw_formation_strip(sheet, rules, geometry.left, top, geometry.right)
    sheet.text(
        (geometry.left, top + sheet.u(28)),
        standard_deal_line(rules),
        sheet.font(14),
        INK,
    )
    closing = (
        "A card's zone is assigned on the field board, not here, and "
        "only a Coaching Choice moves it between zones. A player is "
        "Exhausted once their tokens exceed their defence."
    )
    sheet.text(
        (geometry.left, top + sheet.u(50)),
        closing,
        sheet.fitted_font(closing, geometry.right - geometry.left, 14),
        MUTED,
    )
