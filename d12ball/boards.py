"""
The boards the physical game is played on: the **field board**, the
**jumbotron board**, and a coach's **team board** and **zone board**,
print-ready.

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

**Only the field board is tabloid**, landscape. The jumbotron and the
coach's two boards are letter, each with a paper of its own
(`JUMBOTRON_PAPER`, `TEAM_BOARD_PAPER`), because letter is the sheet a
printer in the house has in it and none of them carries a field to pay
for anything bigger. The field board is the one that cannot be shrunk
-- its spaces have to hold two sides' meeples -- so instead it prints
either whole on tabloid or as two letter halves taped along the cut;
see `render_field_board_halves`.

**The table is the field board with a coach's strip along each long
side** (the author, 2026-10-05): the zone board and the team board,
each half a letter sheet, laid end to end -- seventeen inches, the
field's own length -- so the whole game is 17 x 22in.

Everything the boards assert is read from the data the bot plays
from -- `basic_rules.json` for the layouts, the formations and the
coach's die, `maneuvers.json` for the six maneuvers, and `players.json`
for the roster -- so a printed board cannot claim a rule the bot does
not play, and an import reaches the boards by re-running
`scripts/render_boards.py`. The one thing deliberately left off is the
selection d6: maneuvers are chosen with the cards, so no die value is
printed anywhere here.

**Zones keep their real names**, on the field and on the zone board
where a card's zone is assigned. The areas are labelled HOME ZONE /
MIDFIELD / VISITORS ZONE exactly as the bot's coaching image labels
them -- HOME THIRD / VISITORS THIRD on the 9- and 10-space boards,
whose outer zones are three spaces deep (see "The field" in the living
rules, and the 2026-08-24 and 2026-10-06 entries in the rules log). See
"Working on the board image" in docs/design/board-image.md for the same
decision taken there, and "The zone board" in
docs/design/printed-boards.md for why each coach's runs in their own
order.
"""
from dataclasses import dataclass
from typing import Optional, Sequence

from PIL import Image, ImageDraw, ImageFont

from d12ball.cards import (
    INK,
    MUTED,
    OFFENSE_COLOR,
    PAPER,
    PAPER_EDGE,
    PAPER_PANEL,
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
    SECOND_HALF_START_MINUTE,
    TeamSide,
    Zone,
    kickoff_space_index,
    period_last_minute,
)
from d12ball.formatting import side_display_name
from d12ball.game import Team
from d12ball.player_cards import team_emoji
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

# Sheet sizes in inches, portrait; `sheet_pixels` turns one.
#
# **Tabloid (11 x 17in, the common US "ledger" print size) is the
# default**, over A3: it is the size a home or copy-shop printer
# actually stocks in the US, where A3 is the size these boards were
# first designed at. It is the field board's, landscape (the author,
# 2026-10-05). Every other board is half a letter sheet or a whole
# one; see `TEAM_BOARD_PAPER` and `JUMBOTRON_PAPER`.
PAPERS: dict[str, tuple[float, float]] = {
    "a3": (11.69, 16.54),
    "a4": (8.27, 11.69),
    "tabloid": (11.0, 17.0),
    "letter": (8.5, 11.0),
}
DEFAULT_PAPER = "tabloid"
# **The jumbotron has a paper of its own -- letter, portrait.** Like
# the team board (see `TEAM_BOARD_PAPER`) it is not the sheet the field
# board is drawn on, and for the same reason: letter is what a printer
# in the house actually has in it, and this is the board with no field
# on it to pay for a bigger sheet.
#
# **Portrait rather than landscape is the clock's doing, not a
# preference.** Letter landscape is eleven inches wide and eight and a
# half tall, which is enough width for the clock only if it runs
# thirteen cells to a row -- and `CLOCK_COLUMNS` is eight precisely so
# that halftime lands at the end of a row and each half is two whole
# bands (see `CLOCK_COLUMNS`). That is a rule about the track.
# Turning the sheet costs nothing and keeps it, so the sheet turns.
JUMBOTRON_PAPER = "letter"

# What a sheet's two halves are, when they are a paper of their own.
#
# A board drawn on one of these prints **either way**: whole on the
# sheet, or as two halves on the paper below it, butted back together
# to the same board. The cut is across the long dimension, so a half
# keeps the sheet's short side and half its long one -- which on both
# of these pairs is exactly the next size down, turned the other way
# (the field board's 17 x 11 halves into two 8.5 x 11 letter sheets,
# portrait; A3's into A4 by the same ISO property). Papers that halve
# into nothing standard are absent rather than approximated: the halves
# still render, they are just not a size a printer stocks.
HALF_PAPERS: dict[str, str] = {
    "tabloid": "letter",
    "a3": "a4",
}

# The field board's margin, in inches: a home printer cannot print to
# the edge of a sheet. It is also what each half keeps of its outer
# edges when the board is printed on two letter sheets.
FIELD_EDGE_INCHES = 0.25
# What a goal zone keeps between itself and the strip's own outline, in
# the sheet's units. **A goal zone is as wide as a space** (the author,
# 2026-10-05): it was a fixed sliver -- a third of an inch, then 0.45,
# then 0.6 -- squeezed in beside the strip, and it is a place a ball
# and a scorer go as much as any space is.
GOAL_GAP = 8

# Poker size, the maneuver cards' own -- the player cards share their
# proportions with it on the bot's board (CARD_SIZE is 110 x 154), so
# the areas that hold them are cut for it.
CARD_INCHES = (2.5, 3.5)
# How many cards a zone on the zone board is guided for: three, which
# is what a zone holds under 2-3-1 and 1-3-2. It is the guide and not a
# limit -- see "The zone board" in docs/design/printed-boards.md.
CARDS_PER_AREA = 3

# The zone colours of the bot's board, lightened for paper. The bot
# draws them dark because they sit under white meeple labels on a
# screen; the same three hues at print weight keep a coach reading one
# board as the other.
ZONE_TINTS = {
    Zone.HOME_ZONE: "#dde5f1",
    Zone.MIDFIELD: "#dfe9e0",
    Zone.VISITORS_ZONE: "#f1e4d9",
}

# The clock is one running count over both periods, and all three
# numbers are read off the code the bot enforces rather than written
# here: the first half's last minute is where it breaks, the second
# half's first is where it picks up again, and the second's last is
# where the track ends. The score track runs further than a match is
# ever likely to, because a shootout adds up to six goals to a side
# that was already level.
CLOCK_MINUTES = period_last_minute(MatchPeriod.SECOND_HALF)
HALFTIME_MINUTE = period_last_minute(MatchPeriod.FIRST_HALF)
# **Ten** (the author, 2026-09-23). It was twelve, then six when the
# board came off tabloid and the track had nowhere to be that wide,
# and it is ten now that the token supplies are a strip down the side
# rather than a band across the bottom: the row they vacated is what
# the track is standing in. Ten still does not outrun a shootout --
# six pairings can be added to a score that was already level, so a
# match level at full time can finish past the end of it -- and that
# remains a knowing trade, because the track is a printed aid and not
# a component the rules name (see "Rendering" in CLAUDE.md). Running
# off the end costs a coach a note on the sheet; a cell under
# `MIN_TOKEN_INCHES` costs them the use of the board.
SCORE_TRACK_MAX = 10
# How many score cells go in a row before the track wraps. Eleven is
# the whole track, so nothing wraps -- but the wrap is a measurement
# rather than a decision, so a track that grows again breaks into rows
# on its own instead of shrinking its cells, exactly as the clock
# already does.
SCORE_COLUMNS = 11
# Eight rather than sixteen across, which is what makes a cell something
# a token stands in -- the reason these tracks came off the field board.
# Eight also puts the halftime break at the end of a row, so each half
# is exactly two rows and the two bands are bands rather than a colour
# change halfway along one.
CLOCK_COLUMNS = 8
# The largest type any panel title on the jumbotron is set in -- SCORE
# and TOKENS are 17, the clock's own title a size down at 15 -- and
# the leading a line of it wants to sit in a strip of its own. It is
# what `JumbotronGeometry.label_height` is measured from, and the
# point of measuring it from the type is that a label strip stops
# being a share of the header: the header is trimmed for the height
# budget (see `for_sheet`), and trimming it used to drag every label
# strip down with it until the panel title and the half's own label
# touched and read as one paragraph -- the exact fault "The clock
# panel's two label lines" in docs/design/printed-boards.md records as
# already fixed once.
PANEL_TITLE_SIZE = 17
PANEL_TITLE_LEADING = 1.35
# The jumbotron's own chrome -- the header band and the gap between two
# panels -- **measured in the sheet's own units,
# not as a share of its height**. Everything drawn in them is type,
# and type here is sized in `u`, which is a share of the sheet's
# *width*; a band that was a share of the height therefore held a
# different number of lines on every sheet, and on a landscape one it
# held fewer than there are. That is what put the panel's title and
# the half's own label into the same strip.
#
# The type in the header, and what the band is therefore worth. **The
# band is derived from its own contents, never chosen**: a band picked
# by eye and type sized separately is two measurements of one thing,
# and it is the same fault the team board's footer records -- a line
# drawn below the band it belongs to, on a render that looks fine,
# because the crop is silent. The header is the title alone: the two
# notes that stood beside it moved into the clock panel (the author,
# 2026-09-28) -- see `CLOCK_NOTES`.
JUMBOTRON_TITLE_SIZE = 40
JUMBOTRON_HEADER = JUMBOTRON_TITLE_SIZE * 1.1
# **What the clock charges, and when last possession is declared,
# printed in the clock panel under the second half** -- the author's
# own words (2026-09-28), which replaced a footer under the whole board
# that was set too small to read and had fallen behind the rules (it
# still charged a shot a minute per space). They are the Charter's
# 16.2 and 16.3 said the way a coach at the table needs them; a change
# to either Law is a change here.
CLOCK_NOTES = (
    "Maneuvers move the clock by 1, except for High Pass and Cross that "
    "take 2. A scoring Attempt and a Time Out each move the clock by 1.",
    "Last possession is declared when the clock reaches the last time "
    "box of the period. The team that holds the ball after the maneuver "
    "is fully resolved will have the last possession of the period.",
)
# The notes are body text a coach reads across the table, so they are
# set at a size of their own and wrapped to the track, never fitted
# down to one line -- fitting is what made the old footer too small.
CLOCK_NOTE_SIZE = 14
CLOCK_NOTE_LEADING = 1.3
# Between the two notes, over and above a line's own leading, so they
# read as two statements rather than one paragraph.
CLOCK_NOTE_GAP = 5
# The halftime note on the second half's own label strip: smaller than
# the label it shares the strip with, and set in the same muted ink as
# the notes.
HALFTIME_NOTE_SIZE = 12
# What two panels keep between them. It is the one number here still
# chosen rather than measured, because nothing is drawn in it -- and
# it is charged three times, so it is bought out of the cells
# directly.
JUMBOTRON_GAP = 9
# **The token supplies are a strip down the right-hand side**, not a
# band across the bottom. Three silos on a full-width row left most of
# a row of the sheet empty either side of them, and a row of this
# sheet is what the score track needed to run to ten: the strip is a
# silo wide and the tracks take the rest, so the sheet carries the
# same three pieces in the space of a margin.
SUPPLY_STRIP = 112
# The two bands, and the cells under them. **A minute is not a
# position on this track**: the second half starts on the first half's
# last minute (the author, 2026-09-22), so 15 has a cell in each band
# and everything that draws the track counts cells rather than
# counting minutes. Sixteen cells a half is what makes each band two
# whole rows of eight, with nothing left over.
CLOCK_BANDS = (
    (0, HALFTIME_MINUTE),
    (SECOND_HALF_START_MINUTE, CLOCK_MINUTES),
)
CLOCK_CELLS = tuple(
    (band, minute)
    for band, (first, last) in enumerate(CLOCK_BANDS)
    for minute in range(first, last + 1)
)
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

    `unit_width` measures the unit off something other than the width:
    the field board is landscape now, and its type is sized off the
    sheet's short side so that turning the sheet did not make every word
    on it half again as big -- see `field_sheet`.
    """

    def __init__(
        self,
        width: int,
        height: int,
        background: str = PAPER,
        unit_width: Optional[float] = None,
    ) -> None:
        self.width = width
        self.height = height
        self.background = background
        self.unit = (unit_width or width) / 1000
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


def add_bleed(image: Image.Image, background: str = PAPER) -> Image.Image:
    bleed = round(BLEED_INCHES * PRINT_DPI)
    sheet = Image.new(
        "RGB",
        (image.width + bleed * 2, image.height + bleed * 2),
        background,
    )
    sheet.paste(image, (bleed, bleed))
    return sheet


def half_paper(paper: str) -> Optional[str]:
    """The paper a sheet's two halves are, or `None` if it is not one."""
    if paper not in PAPERS:
        raise ValueError(
            f"Unknown paper size {paper!r}; expected one of "
            f"{', '.join(sorted(PAPERS))}."
        )
    return HALF_PAPERS.get(paper)


def halve_sheet(image: Image.Image) -> tuple[Image.Image, Image.Image]:
    """
    Cut a rendered sheet in two across its longer dimension.

    **It is a cut of the finished picture, not a second layout**, which
    is the whole of why it is safe: the two halves butted back together
    are the sheet, pixel for pixel, so a board printed on two small
    sheets is the same board -- the same space width -- as the one
    printed on one big one. Re-laying a board out
    for a smaller paper would print a different game.

    Where the cut lands is not a choice either. A half has to fit the
    paper below, and only the exact middle gives two halves that both
    do, so the seam falls wherever the layout happens to put it -- on
    the field board, down the middle of the strip. See "Printing a
    board on small sheets" in docs/design/printed-boards.md.

    The halves are returned in reading order: top and bottom for a
    portrait sheet, left and right for a landscape one. An odd length
    gives the second half the spare pixel, so the two still sum to the
    whole.
    """
    width, height = image.size
    if height >= width:
        cut = height // 2
        return (
            image.crop((0, 0, width, cut)),
            image.crop((0, cut, width, height)),
        )
    cut = width // 2
    return (
        image.crop((0, 0, cut, height)),
        image.crop((cut, 0, width, height)),
    )


# ---------------------------------------------------------------- field


@dataclass(frozen=True)
class FieldGeometry:
    """
    Where the field board's bands sit, and how wide a space is.

    The bands around the strip are a fixed share of the sheet and the
    strip takes what is left, so the spaces -- the only part a meeple
    has to fit in -- get every pixel the rest does not need. **The
    clock and the score are not among them**: they went to the
    [jumbotron board](#the-jumbotron-board), and **the zone-assignment
    rows are not either**: they are a coach's own zone board now, laid
    beside their team board along their side of the field (the author,
    2026-10-05) -- see `render_zone_board`.

    **`left`/`right` are the full content width and `strip_left`/
    `strip_right` are narrower** -- the header, the direction arrows
    and the shooting-range bracket all read the wide pair, the way the
    bot's own jumbotron and team boards span its end zones and all;
    the spaces themselves, and everything measured off them
    (`space_bounds`, `span_bounds`, `space_width`), read the narrow
    pair, which leaves the gap between the two wide enough for a goal
    zone on each side -- see `draw_field_end_zones`.

    **The sheet is landscape (17 x 11), and the strip runs its long
    side** (the author, 2026-10-05). It was portrait for as long as the
    two zone rows were on it, since they wanted the 17in length; with
    them off, the strip has the length instead: the width is shared out
    over the spaces and the two goal zones alike, a goal as wide as a
    space, and a 9-space board's space comes out nearly an inch and a
    half wide where it was just over one.
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
    strip_label_bottom: float
    strip_bottom: float
    range_top: float
    range_bottom: float
    space_width: float
    board_size: int

    @classmethod
    def for_sheet(cls, sheet: Sheet, layout: BoardLayout) -> "FieldGeometry":
        # **The full width of the sheet, less what a printer cannot
        # reach.**
        edge = FIELD_EDGE_INCHES * PRINT_DPI
        left = edge
        right = sheet.width - edge

        # **The goal zone beyond each end of the strip is a space
        # wide**, so the width is shared out over the spaces and the
        # two goals alike -- the print counterpart of `GOAL_ZONE_WIDTH`
        # in render.py, which is narrower because the bot's board has
        # no meeple to stand in a goal.
        goal_gap = sheet.u(GOAL_GAP)
        space_width = (right - left - 2 * goal_gap) / (layout.board_size + 2)
        strip_left = left + space_width + goal_gap
        strip_right = right - space_width - goal_gap

        content_top = edge
        content_bottom = sheet.height - edge
        content = content_bottom - content_top

        # The header is its type: the title, the subtitle, and one
        # line of note (see `draw_field_header`). The shooting-range
        # band is one line of label since "shoot only from here" came
        # off it. The strip takes the rest.
        gap = content * 0.02
        header = sheet.u(FIELD_NOTE_TOP + FIELD_NOTE_LEADING)
        direction = content * 0.05
        ranges = sheet.u(44)
        strip = content - header - direction - ranges - 3 * gap

        header_bottom = content_top + header
        direction_top = header_bottom + gap
        direction_bottom = direction_top + direction
        strip_top = direction_bottom + gap
        strip_bottom = strip_top + strip
        range_top = strip_bottom + gap

        # The band across the top of the strip that carries the zone
        # names, with the space codes hung immediately under it. It is
        # measured here rather than in `draw_field_strip` because the
        # kickoff mark is centred in what is left under it.
        strip_label_bottom = strip_top + sheet.u(34)

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
            strip_label_bottom=strip_label_bottom,
            strip_bottom=strip_bottom,
            range_top=range_top,
            range_bottom=range_top + ranges,
            space_width=space_width,
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


def field_sheet(width: int, height: int, background: str = PAPER) -> Sheet:
    """
    A sheet the field board is drawn on, or photographed on (see
    `box_art.board_photo`): its unit is measured off the **short** side,
    so the landscape board's type prints at the size the portrait one's
    did, rather than half again as big because the sheet turned.
    """
    return Sheet(
        width, height, background=background, unit_width=min(width, height)
    )


def render_field_board(
    rules: BasicRuleset,
    board_size: int = 7,
    paper: str = DEFAULT_PAPER,
    bleed: bool = False,
) -> Image.Image:
    """
    The field: one row of spaces, split into the three zones, with the
    kickoff space marked and each side's shooting range bracketed under
    it.

    **Landscape, and the field alone** (the author, 2026-10-05). The
    zone-assignment rows that used to stand above and below it are each
    coach's own zone board, laid beside their team board along their
    side of the table -- see `render_zone_board`.
    """
    if board_size not in rules.board_layouts:
        raise ValueError(
            f"No board layout of {board_size} spaces; the ruleset has "
            f"{', '.join(str(size) for size in sorted(rules.board_layouts))}."
        )
    layout = rules.board_layouts[board_size]
    board = BoardState.empty(layout)

    width, height = sheet_pixels(paper, landscape=True)
    sheet = field_sheet(width, height)
    geometry = FieldGeometry.for_sheet(sheet, layout)

    draw_field_header(sheet, geometry, layout)
    draw_attack_directions(sheet, geometry, board)
    draw_field_strip(sheet, geometry, layout)
    draw_field_end_zones(sheet, geometry)
    draw_shooting_ranges(sheet, geometry, board)

    return add_bleed(sheet.image) if bleed else sheet.image


def render_field_board_halves(
    rules: BasicRuleset,
    board_size: int = 7,
    paper: str = DEFAULT_PAPER,
    bleed: bool = False,
) -> tuple[Image.Image, Image.Image]:
    """
    **The same field board, on two sheets of the paper below** -- the
    left half and the right half, taped along the cut to make the board
    `render_field_board` draws whole.

    It is for the printer a house actually has: the field board is
    tabloid, and a letter printer cannot print it at all otherwise,
    where scaling it to fit would hand a coach a board whose spaces are
    too small to stand two meeples on. Two letter sheets, portrait,
    print it at its real size.

    The cut is `halve_sheet`'s -- the finished board, halved, never
    re-laid-out for the smaller paper -- so the seam runs down the
    middle of the field, through midfield's middle space. That is the
    cost of both halves fitting the paper; nothing is moved to dodge
    it, because moving it would change the board the tabloid sheet
    prints.

    **The board is halved before any bleed, and each half gets its
    own.** A half is a sheet a printer trims like any other, and
    trimming into the bleed takes the added margin back off the seam,
    so the two still butt together.
    """
    first, second = halve_sheet(
        render_field_board(rules, board_size, paper=paper)
    )
    return (add_bleed(first), add_bleed(second)) if bleed else (first, second)


# Where the header's note sits under the title, and the line it takes:
# the header band is measured from these (`FieldGeometry.for_sheet`).
FIELD_NOTE_TOP = 84
FIELD_NOTE_LEADING = 24


def draw_field_header(
    sheet: Sheet,
    geometry: FieldGeometry,
    layout: BoardLayout,
) -> None:
    """
    The title, stacked in one left-aligned column rather than a title
    on the left and a note on the right -- side by side, the two used
    to overlap in the middle on anything narrower than the old
    landscape sheet, which the portrait one that followed it was. Each note
    line is wrapped to the sheet's own content width, so it cannot run
    under the title regardless of paper size or wording length.
    """
    top = geometry.header_top
    left = geometry.left
    width = geometry.right - geometry.left
    sheet.text((left, top), "D12 BALL", sheet.font(40, bold=True), INK)
    # No mode: the board is the same in every mode, so naming one says
    # the board is that mode's (the author, 2026-09-27).
    sheet.text(
        (left, top + sheet.u(46)),
        f"FIELD BOARD  ·  {layout.board_size} SPACES",
        sheet.font(16, bold=True),
        MUTED,
    )

    # One note. The second -- that the clock, the score and the token
    # supplies are kept on the jumbotron -- came off (the author,
    # 2026-09-28): the jumbotron is on the table beside it and says so
    # itself. The note has to fit one line, since the band is measured
    # for one (`FieldGeometry.for_sheet`), so it is fitted, not wrapped.
    note = (
        f"Two periods on one running clock, 00-{HALFTIME_MINUTE} and "
        f"{SECOND_HALF_START_MINUTE}-{CLOCK_MINUTES}. Home kicks off the "
        "first, the visitors the second."
    )
    sheet.text(
        (left, top + sheet.u(FIELD_NOTE_TOP)),
        note,
        sheet.fitted_font(note, width, 15),
        MUTED,
    )


def draw_attack_directions(
    sheet: Sheet,
    geometry: FieldGeometry,
    board: BoardState,
) -> None:
    """
    Which way each side is playing, over the half of the field it is
    playing into. Home attacks the Visitors Goal, so its arrow runs to
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
        fill=PAPER_PANEL,
        outline=PAPER_EDGE,
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
        fill=PAPER_PANEL,
        outline=PAPER_EDGE,
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
    band_bottom = geometry.strip_label_bottom
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
                space_code(zone, space_index, layout),
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

    On a board whose midfield has a true middle both sides kick off
    from it and the two land on one mark; board 10's has two, one a
    side. It is a map rather than a space because the rule is asked
    per side --
    `kickoff_space_index` is that rule; this only places its answer on
    the whole board.
    """
    before_midfield = layout.zone_spaces[Zone.HOME_ZONE]
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
            fill=PAPER,
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
            else f"{side_display_name(sides[0]).upper()} KICKOFF"
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
    draw_field_end_zone(
        sheet,
        geometry.left, geometry.left + geometry.space_width,
        geometry.strip_top, geometry.strip_bottom,
        angle=90,
    )
    draw_field_end_zone(
        sheet,
        geometry.right - geometry.space_width, geometry.right,
        geometry.strip_top, geometry.strip_bottom,
        angle=270,
    )


def draw_field_end_zone_frame(
    sheet: Sheet, left: float, right: float, top: float, bottom: float,
) -> None:
    """The end zone's own outline, drawn before the "GOAL" lettering."""
    sheet.rect(
        (round(left), round(top), round(right), round(bottom)),
        fill=PAPER_PANEL,
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
    moves as one unit or not at all -- see "Goal zones" in
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
                stroke_fill=PAPER,
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
        fill=PAPER,
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
        -1: f"{outer[Zone.VISITORS_ZONE]} - SHOOTING RANGE",
        1: f"{outer[Zone.HOME_ZONE]} - SHOOTING RANGE",
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
            # Board 10's middle is two spaces, one each side's.
            said = "the kickoff spaces" if last > first else "the kickoff space"
            sheet.text(
                ((left + right) / 2, (top + bottom) / 2),
                said,
                sheet.fitted_font(said, (right - left) * 0.92, 15),
                MUTED,
                anchor="mm",
            )
            continue
        sheet.rect(
            (left, top, right, bottom),
            radius=sheet.u(6),
            fill=PAPER_PANEL,
            outline=PAPER_EDGE,
            width=sheet.u(1.6),
        )
        label = labels[side]
        # The label alone: "shoot only from here" under it came off (the
        # author, 2026-09-28) -- a bracket named SHOOTING RANGE already
        # says where a shot is taken from.
        sheet.text(
            ((left + right) / 2, (top + bottom) / 2),
            label,
            sheet.fitted_font(label, (right - left) * 0.92, 17, bold=True),
            INK,
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
    one -- `cell_inches` is that measurement, and every one of them
    stays above `MIN_TOKEN_INCHES`.

    **The clock is four rows, not two**, since it now runs the whole
    game rather than one period: 00-15 and 15-30, two rows a half with
    the break falling at the end of a row. That halved the height a row
    had, which is what the panel shares were redivided for -- and it is
    the thing to check first if a band is ever added here, because a
    cell going under a token is silent on the render.

    **The score is four rows too**, two a side, since this board went
    to letter: thirteen cells in one row is ten inches of track and a
    letter sheet has not got it. The panel shares and the chrome around
    them were redivided again for that -- see `for_sheet` and
    `SCORE_COLUMNS`.
    """

    left: float
    right: float
    # Where the clock and the score panels end. It is short of `right`
    # by the supply strip -- see `SUPPLY_STRIP`. Everything measured
    # off the cells reads this; the header and the footer read `right`
    # and span the sheet.
    tracks_right: float
    header_top: float
    header_bottom: float
    clock_top: float
    clock_bottom: float
    score_top: float
    score_bottom: float
    supply_left: float
    supply_top: float
    supply_bottom: float
    # The clock notes, wrapped to the track, and the height the block
    # takes at the bottom of the clock panel -- measured here so the
    # cells above it are what is left, not a share it may overrun.
    clock_note_lines: tuple[tuple[str, ...], ...]
    clock_notes_height: float
    # The strip a panel keeps for its own title, measured off the type
    # that goes in it rather than off the header's share -- see
    # `PANEL_TITLE_SIZE`.
    label_height: float
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
        # **The chrome is trimmed to what letter leaves, and only the
        # chrome.** The header, the footer and the three gaps between
        # panels are the only things on this board that are not a cell,
        # so when it came off tabloid they are what paid: every one is
        # a smaller share than the tabloid board used. It is the same
        # trade the tabloid switch itself made when the score and
        # supply cells went under the floor by a sliver, one rank
        # further along.
        #
        # These hold for **either orientation** -- this is the one
        # board drawn both ways (see `render_jumbotron_board`), and a
        # letter sheet turned landscape has two and a half inches less
        # height to divide while its type is *bigger*, being a share of
        # the longer side. Landscape is the binding case for every
        # number here; portrait has room to spare.
        gap = sheet.u(JUMBOTRON_GAP)
        header = sheet.u(JUMBOTRON_HEADER)
        # One gap under the header; the one between the two tracks is
        # inside `panels` and charged where the rows are divided. The
        # supply strip runs beside the tracks rather than under them,
        # so it costs none, and there is no footer any more.
        panels = content - header - gap
        # The strip is the full height of the two tracks beside it, so
        # the panels below divide what is left of the *height* only --
        # the supplies no longer take a share of it at all.
        supply_left = right - sheet.u(SUPPLY_STRIP)
        tracks_right = supply_left - gap
        padding = sheet.u(18)
        label_height = sheet.u(PANEL_TITLE_SIZE * PANEL_TITLE_LEADING)
        band_label = label_height * 0.7

        note_face = sheet.font(CLOCK_NOTE_SIZE)
        note_lines = tuple(
            tuple(
                wrap_text(
                    sheet.draw,
                    note,
                    note_face,
                    round(tracks_right - left - 2 * padding),
                )
            )
            for note in CLOCK_NOTES
        )
        notes_height = (
            sum(len(lines) for lines in note_lines)
            * sheet.u(CLOCK_NOTE_SIZE * CLOCK_NOTE_LEADING)
            + (len(note_lines) - 1) * sheet.u(CLOCK_NOTE_GAP)
            + padding
        )

        # **A clock cell and a score cell come out the same height**,
        # measured rather than a chosen share: both panels carry a
        # title and two band labels, the clock the notes as well, and
        # what is left is split over the clock's four rows and the
        # score's four (two a side).
        chrome = label_height + 2 * band_label
        score_rows = 2 * -(-(SCORE_TRACK_MAX + 1) // SCORE_COLUMNS)
        clock_rows = -(-len(CLOCK_CELLS) // CLOCK_COLUMNS)
        row = (panels - gap - 2 * chrome - notes_height) / (
            clock_rows + score_rows
        )
        clock = chrome + clock_rows * row + notes_height

        header_bottom = top + header
        clock_top = header_bottom + gap
        clock_bottom = clock_top + clock
        score_top = clock_bottom + gap
        score_bottom = clock_top + panels

        return cls(
            left=left,
            right=right,
            tracks_right=tracks_right,
            header_top=top,
            header_bottom=header_bottom,
            clock_top=clock_top,
            clock_bottom=clock_bottom,
            score_top=score_top,
            score_bottom=score_bottom,
            supply_left=supply_left,
            supply_top=clock_top,
            supply_bottom=score_bottom,
            clock_note_lines=note_lines,
            clock_notes_height=notes_height,
            label_height=label_height,
            padding=padding,
        )

    @property
    def cells_left(self) -> float:
        return self.left + self.padding

    @property
    def cells_width(self) -> float:
        """The width a track has, which stops short of the strip."""
        return self.tracks_right - self.left - 2 * self.padding

    @property
    def clock_rows(self) -> int:
        return -(-len(CLOCK_CELLS) // CLOCK_COLUMNS)

    @property
    def band_label_height(self) -> float:
        """
        The strip over a band of rows, saying what the band is -- which
        half of the clock, or whose score. **Both tracks charge it
        twice**, so it is here rather than inside either drawing:
        `clock_cell` and `score_cell` both have to measure what is left
        after it.

        The score's side labels went from beside its rows to over them
        when the track grew to eleven cells: beside, the HOME/VISITORS
        column was an inch of the width that eleven cells needed, and
        over them the label reads the way the clock's own band labels
        already do.
        """
        return self.label_height * 0.7

    def clock_cell(self) -> tuple[float, float]:
        used = (
            self.label_height
            + 2 * self.band_label_height
            + self.clock_notes_height
        )
        return (
            self.cells_width / CLOCK_COLUMNS,
            (self.clock_bottom - self.clock_top - used) / self.clock_rows,
        )

    @property
    def score_rows(self) -> int:
        """
        How many rows one side's track wraps into -- see
        `SCORE_COLUMNS`. Both sides wrap the same way, so the panel
        holds twice this.
        """
        return -(-(SCORE_TRACK_MAX + 1) // SCORE_COLUMNS)

    def score_cell(self) -> tuple[float, float]:
        used = self.label_height + 2 * self.band_label_height
        return (
            self.cells_width / SCORE_COLUMNS,
            (self.score_bottom - self.score_top - used)
            / (2 * self.score_rows),
        )

    def supply_cell(self) -> tuple[float, float]:
        """
        One silo, which is a fixed measurement rather than a share of
        the strip: it holds a stack of tokens, and a piece does not get
        bigger because the sheet did.

        **It is capped by the strip's width now, not by its height.**
        The three silos stand one above another down the side, so the
        strip is as tall as the tracks beside it and there is height to
        spare; what a smaller paper takes away is the width, and a silo
        shrinks to it rather than running off the edge.
        """
        available = (
            self.supply_right - self.supply_left - 2 * self.padding
        )
        width = min(SILO_INCHES[0] * PRINT_DPI, available)
        return (width, width * SILO_INCHES[1] / SILO_INCHES[0])

    @property
    def supply_right(self) -> float:
        return self.right


def cell_inches(
    paper: str = JUMBOTRON_PAPER,
) -> dict[str, tuple[float, float]]:
    """
    How big the clock's and the score's cells print. This is the whole
    reason the jumbotron is its own board, so it is a number the CLI
    reports rather than something read off a render.

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
    paper: str = JUMBOTRON_PAPER,
    bleed: bool = False,
) -> Image.Image:
    """
    The jumbotron: the game clock, both scores and the three token
    supplies, each cell big enough to stand a token in.

    Like the bot's own jumbotron this is the state of the match rather
    than the position -- which is why it comes off the field board
    rather than sharing it. The tracks are printed aids and not
    components the rules name; everything they count is a rule.

    **One letter sheet** -- `JUMBOTRON_PAPER`, not the field board's
    tabloid. It is the sheet a house printer takes, and this is the
    board that can be fitted onto it, having no field to lay out.

    **Landscape, and only landscape** (the author, 2026-09-23). It was
    drawn portrait as well for a while; a board that sits across the
    table in front of two coaches is a landscape thing, and a second
    orientation was a second picture to look at for no one's benefit.
    What made landscape workable was moving the token supplies off
    their full-width band and down the side -- see
    `draw_token_supplies` -- which is also what left the score track
    room to run to ten.

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

    return add_bleed(sheet.image) if bleed else sheet.image


def draw_jumbotron_header(sheet: Sheet, geometry: JumbotronGeometry) -> None:
    """
    The board's title, and nothing beside it.

    No period boxes, no subtitle and no notes. The boxes were two ticked
    squares up here while the clock counted one period twice; the clock
    now runs the whole game in two labelled bands, so where the minute
    token is standing is already which half it is. The two notes that
    stood on the right went too (the author, 2026-09-28): which minutes
    are whose half is what the band labels already say, and when the
    second half starts is said between the two halves, where it is
    read -- see `draw_clock_half_bands`.
    """
    sheet.text(
        (geometry.left, geometry.header_top),
        "JUMBOTRON",
        sheet.font(JUMBOTRON_TITLE_SIZE, bold=True),
        INK,
    )


@dataclass(frozen=True)
class ClockTrackGeometry:
    """
    Where a minute's cell sits, on the clock panel `JumbotronGeometry`
    already laid out -- its own record because `draw_clock_track` reads
    it from three different bands (the frame, the two half labels and
    the cells) that all have to agree on the same cells.

    `cell_origin` is the one place that turns a **cell** into a row and
    column, and it takes a cell rather than a minute because the second
    half opens on the first half's last minute: 15 has a cell in each
    band, so a minute no longer names a position (see `CLOCK_CELLS`).
    The band label above each half is charged once per half rather than
    once per row, which is the only reason it is arithmetic rather than
    a nested loop -- the break falls at the end of a row by
    construction (see `CLOCK_COLUMNS`), so a cell knows its own band.
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
    note_lines: tuple[tuple[str, ...], ...]
    notes_height: float

    @classmethod
    def for_jumbotron(cls, geometry: JumbotronGeometry) -> "ClockTrackGeometry":
        cell_width, cell_height = geometry.clock_cell()
        return cls(
            left=geometry.left,
            right=geometry.tracks_right,
            top=geometry.clock_top,
            bottom=geometry.clock_bottom,
            cells_left=geometry.cells_left,
            cells_top=geometry.clock_top + geometry.label_height,
            cell_width=cell_width,
            cell_height=cell_height,
            band_label=geometry.band_label_height,
            note_lines=geometry.clock_note_lines,
            notes_height=geometry.clock_notes_height,
        )

    def cell_origin(self, position: int) -> tuple[float, float]:
        row = position // CLOCK_COLUMNS
        band = CLOCK_CELLS[position][0]
        return (
            self.cells_left + (position % CLOCK_COLUMNS) * self.cell_width,
            self.cells_top + (band + 1) * self.band_label
            + row * self.cell_height,
        )


def draw_clock_track(sheet: Sheet, geometry: JumbotronGeometry) -> None:
    """
    The whole game's minutes, in rows of eight under a band per half --
    the frame, the two half labels and the cells, in that order.

    **The overrun has no cells.** The clock runs past a period's last
    minute for as long as its last possession does, and a track drawn
    for that would be a row of squares nobody can say the length of.
    What that used to want spelling out in the track's spare slot is
    said by the caption under 15 and 30 and by the notes under the
    second half -- and since the second half starts on 15 there is no
    spare slot left anyway: each band is sixteen cells, two full rows.

    **The notes are the clock's own**, at the bottom of its panel: what
    moves the clock and when last possession is declared, at a size
    that reads across the table (see `CLOCK_NOTES`).

    **The two 15s are two cells and mean different things.** The first
    half's is its last minute, bordered and captioned like 30; the
    second half's is where that half kicks off, and is a plain cell.
    """
    track = ClockTrackGeometry.for_jumbotron(geometry)
    draw_clock_track_frame(sheet, track)
    draw_clock_half_bands(sheet, track)
    draw_clock_cells(sheet, track)
    draw_clock_notes(sheet, track)


def draw_clock_track_frame(sheet: Sheet, track: ClockTrackGeometry) -> None:
    sheet.rect(
        (
            track.left,
            track.top,
            track.right,
            track.bottom,
        ),
        radius=sheet.u(10),
        fill=PAPER_PANEL,
        outline=PAPER_EDGE,
        width=sheet.u(2),
    )
    # Centred in the strip the panel keeps for its title, not hung off
    # the top of it: hung, the line sat two hundredths of an inch over
    # the half's own label, and the two read as one paragraph.
    sheet.text(
        (track.cells_left, (track.top + track.cells_top) / 2),
        "CLOCK",
        sheet.font(15, bold=True),
        MUTED,
        anchor="lm",
    )


def draw_clock_half_bands(sheet: Sheet, track: ClockTrackGeometry) -> None:
    """
    Each half's label over its rows, and **when the second half starts,
    said between the two halves** -- on the right of the second half's
    own strip, where a coach moving the minute token over at halftime
    is already looking.
    """
    band_face = sheet.font(14, bold=True)
    for band, (first, last_minute) in enumerate(CLOCK_BANDS):
        label_top = (
            track.cell_origin(CLOCK_CELLS.index((band, first)))[1]
            - track.band_label
        )
        # Centred in its own strip, for the reason the panel title is:
        # a label that clears the row under it by a hair and the line
        # over it by less is a label neither of them owns.
        sheet.text(
            (track.cells_left, label_top + track.band_label / 2),
            f"{'FIRST' if not band else 'SECOND'} HALF  ·  "
            f"{first:02d}-{last_minute:02d}",
            band_face,
            INK,
            anchor="lm",
        )
        if band:
            note = (
                f"The second half starts at {SECOND_HALF_START_MINUTE} "
                "however far the first half's last possession ran."
            )
            sheet.text(
                (
                    track.cells_left + CLOCK_COLUMNS * track.cell_width,
                    label_top + track.band_label / 2,
                ),
                note,
                sheet.font(HALFTIME_NOTE_SIZE),
                MUTED,
                anchor="rm",
            )


def draw_clock_cells(sheet: Sheet, track: ClockTrackGeometry) -> None:
    """
    Each half's **last** minute is bordered and captioned, because
    reaching it is the one thing on this board that changes what a coach
    may do -- see "Last possession".
    """
    number_face = sheet.font(28, bold=True)
    for position, (band, minute) in enumerate(CLOCK_CELLS):
        cell_left, cell_top = track.cell_origin(position)
        # Its own band's last minute, not "15 or 30": the second
        # half's first cell is also a 15, and it is a plain one.
        last = minute == CLOCK_BANDS[band][1]
        sheet.rect(
            (
                cell_left + sheet.u(4),
                cell_top + sheet.u(4),
                cell_left + track.cell_width - sheet.u(4),
                cell_top + track.cell_height - sheet.u(4),
            ),
            radius=sheet.u(8),
            fill=PAPER,
            outline=OFFENSE_COLOR if last else PAPER_EDGE,
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


def draw_clock_notes(sheet: Sheet, track: ClockTrackGeometry) -> None:
    """The notes under the second half, in the block the geometry measured."""
    face = sheet.font(CLOCK_NOTE_SIZE)
    line = sheet.u(CLOCK_NOTE_SIZE * CLOCK_NOTE_LEADING)
    # The text is centred in the block, which leaves the padding
    # `for_sheet` charged it split evenly: half clear of the row above,
    # half clear of the panel's bottom edge.
    gap = sheet.u(CLOCK_NOTE_GAP)
    text_height = (
        sum(len(lines) for lines in track.note_lines) * line
        + (len(track.note_lines) - 1) * gap
    )
    y = track.bottom - (track.notes_height + text_height) / 2
    for index, lines in enumerate(track.note_lines):
        if index:
            y += gap
        for text in lines:
            sheet.text((track.cells_left, y), text, face, MUTED)
            y += line


def draw_score_tracks(sheet: Sheet, geometry: JumbotronGeometry) -> None:
    """
    A row each, running to `SCORE_TRACK_MAX` -- ten, standing in the
    row the token supplies vacated when they went to the side; see the
    constant for what it still gives up.

    **It wraps rather than shrinking**, and at eleven cells across the
    width the strip left it, it does not have to.
    A track too long for the sheet breaks at `SCORE_COLUMNS` and runs
    on underneath -- the same answer the clock already gives, for the
    same reason -- rather than taking a cell under the token this whole
    board exists to give a cell to. A side's label sits beside its
    whole block rather than beside its first row, so it still names the
    side and not the row if the track ever does wrap again.
    """
    sheet.rect(
        (
            geometry.left,
            geometry.score_top,
            geometry.tracks_right,
            geometry.score_bottom,
        ),
        radius=sheet.u(10),
        fill=PAPER_PANEL,
        outline=PAPER_EDGE,
        width=sheet.u(2),
    )
    # Centred in the strip the panel keeps for its title, exactly as
    # the clock's is: hung from the top at a fixed offset it reached
    # past the strip and into the HOME band's own label, which is the
    # same collision `band_label_height` records for the clock.
    sheet.text(
        (
            geometry.cells_left,
            geometry.score_top + geometry.label_height / 2,
        ),
        "SCORE",
        sheet.font(PANEL_TITLE_SIZE, bold=True),
        MUTED,
        anchor="lm",
    )

    cells_left = geometry.cells_left
    cell_width, row_height = geometry.score_cell()
    band_label = geometry.band_label_height
    rows_top = geometry.score_top + geometry.label_height
    number_face = sheet.fitted_font(
        str(SCORE_TRACK_MAX), cell_width * 0.5, 34, bold=True
    )
    label_face = sheet.font(14, bold=True)

    rows = geometry.score_rows
    for side, label in enumerate(("HOME", "VISITORS")):
        band_top = rows_top + side * (band_label + rows * row_height)
        # Centred in its own strip over the side's rows, the way the
        # clock's half labels are -- see `band_label_height` for why
        # the word came off the side of the track and went over it.
        sheet.text(
            (cells_left, band_top + band_label / 2),
            label,
            label_face,
            INK,
            anchor="lm",
        )
        block_top = band_top + band_label
        for value in range(SCORE_TRACK_MAX + 1):
            row, column = divmod(value, SCORE_COLUMNS)
            row_top = block_top + row * row_height
            cell_left = cells_left + column * cell_width
            sheet.rect(
                (
                    cell_left + sheet.u(3),
                    row_top + sheet.u(4),
                    cell_left + cell_width - sheet.u(3),
                    row_top + row_height - sheet.u(4),
                ),
                radius=sheet.u(6),
                fill=PAPER,
                outline=PAPER_EDGE,
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

    **It is a strip down the side of the sheet, not a band across the
    bottom.** Three silos on a full-width row left most of that row
    empty either side of them, and a row of this sheet is what the
    score track needed to reach ten. Beside the tracks the same three
    pieces take the width of a margin, and stand one above another the
    way a tray of pieces sits beside a board rather than under it.

    The trio is spread down the strip rather than stacked at one end,
    so the space between them reads as the tray it is.
    """
    sheet.rect(
        (
            geometry.supply_left,
            geometry.supply_top,
            geometry.supply_right,
            geometry.supply_bottom,
        ),
        radius=sheet.u(10),
        fill=PAPER_PANEL,
        outline=PAPER_EDGE,
        width=sheet.u(2),
    )
    silos_left = geometry.supply_left + geometry.padding
    silo_width, minimum = geometry.supply_cell()
    # The strip is a silo wide, so the title is fitted to it rather
    # than set: at the size the other panel titles use it ran off both
    # edges of a column this narrow. Centred in its strip like theirs.
    sheet.text(
        (silos_left, geometry.supply_top + geometry.label_height / 2),
        "TOKENS",
        sheet.fitted_font("TOKENS", silo_width, PANEL_TITLE_SIZE, bold=True),
        MUTED,
        anchor="lm",
    )

    top = geometry.supply_top + geometry.label_height
    room = geometry.supply_bottom - geometry.padding - top
    gap = geometry.padding
    # **A silo's width is the piece; its height is stack room.** The
    # width is fixed, because a token does not get bigger because the
    # sheet did -- but down the side of the sheet there is height to
    # spare, and a well a coach piles pieces into may as well be as
    # deep as the strip allows. Never shorter than `SILO_INCHES` makes
    # it, so a narrower strip shrinks the well rather than squaring it.
    count = len(TOKEN_SUPPLIES)
    silo_height = max(minimum, (room - (count - 1) * gap) / count)

    for index, name in enumerate(TOKEN_SUPPLIES):
        left = silos_left
        silos_top = top + index * (silo_height + gap)
        sheet.rect(
            (left, silos_top, left + silo_width, silos_top + silo_height),
            radius=sheet.u(8),
            fill=PAPER,
            outline=PAPER_EDGE,
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
# Five sizes, and nothing between them: the board's own title, a
# cell's title, a cell's caption, body text, and the small print in the
# footer. A sixth size is a change to this list, not a number written
# into a call. The team is named by its emoji, not a word -- see
# `draw_team_header`.
TEAM_TITLE_INCHES = 0.26
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
# Between the footer's three lines -- the shapes, the standard
# formation, and the reminder -- over and above each line's own leading.
TEAM_FOOTER_LINE_GAP_INCHES = 0.05
# Leading, as a multiple of a line's own size. A heading sits closer to
# what it heads than body copy does to the next line of itself.
TEAM_TITLE_LEADING = 1.15
TEAM_LINE_LEADING = 1.4
# A bench is three cards stacked sideways (the author, 2026-09-28): each
# card sits this share of its own width to the right of the one behind
# it, so the left edge of every card shows and a coach counts three
# without lifting one.
TEAM_BENCH_CARDS = 3
TEAM_BENCH_CASCADE = 0.2
# The dashed line down the seam of the two-up page. It is on the seam
# and so on the edge of both boards, which is the one place a mark
# belongs on a sheet that is about to be cut in half.
TEAM_CUT_INCHES = 0.01
# **A coloured two-up page is two colour teams, one a half** (the
# author, 2026-10-03): Teal over Orange and Purple over Slime, so the
# four colour teams' boards are two pages rather than four, and a run
# that wants one of each prints just those two. The standard board is
# nobody's, and its page is the one board twice.
TEAM_BOARD_PAGES: tuple[tuple[Team, Team], ...] = (
    (Team.TEAL, Team.ORANGE),
    (Team.PURPLE, Team.SLIME),
)


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
    back bench and the maneuvers -- and a footer.

    **The three cells are one row of equal columns**, and the row takes
    whatever the header and the footer leave. Both of those are a fixed
    number of lines at a fixed printed size, so they are measured off
    their own type rather than given a share of the sheet: a header is
    the same two lines on any paper, and a line that does not fit its
    band is the bug this layout replaced.

    `slot` is one card of the cascade drawn inside a bench -- three of
    them, each `TEAM_BENCH_CASCADE` of a card right of the last -- capped
    at a real poker card so a bigger sheet gives a roomier area rather
    than an outsized guide. `card_slot_inches` reports it, and at half a
    letter sheet it comes out under a poker card: a bench column is not
    the width of three cascaded cards, nor the row a card's height,
    once the head, the footer and two legible cell labels are paid for,
    and the author's call was legible over life-size. A coach stacks their bench on the area the way the guide
    shows, overhanging it.
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
        # and cropped away without a mark on the render. Three lines:
        # the shapes, the standard formation, and the one reminder.
        deal_offset = inches(
            TEAM_BODY_INCHES * TEAM_LINE_LEADING + TEAM_FOOTER_LINE_GAP_INCHES
        )
        reminder_offset = deal_offset + inches(
            TEAM_BODY_INCHES * TEAM_LINE_LEADING + TEAM_FOOTER_LINE_GAP_INCHES
        )
        footer_height = reminder_offset + inches(
            TEAM_SMALL_INCHES * TEAM_LINE_LEADING
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

        # **The maneuvers column is the width of the card in it**,
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

        # The cascade is one card's width plus an offset per card
        # behind it, so the card is what is left of the column over
        # that -- or of the row's height, whichever binds first.
        padding = inches(TEAM_AREA_PADDING_INCHES)
        cascade = 1 + (TEAM_BENCH_CARDS - 1) * TEAM_BENCH_CASCADE
        slot_height = min(
            area_bottom - area_top - 2 * padding,
            inches(CARD_INCHES[1]),
            (bench_width - 2 * padding)
            / cascade
            * CARD_INCHES[1]
            / CARD_INCHES[0],
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
    How big a card the bench areas' guides are cut for, in inches --
    one card of the three cascaded. The CLI prints it, and it is what
    says whether a print can be laid cards on or only read.
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
    **One coach's board**: the bench, the back bench and the
    maneuvers cell, under a header and over a footer.

    Half a letter sheet (8.5 x 5.5in), which is what makes two of them
    a page -- `render_team_board_sheet` is that page, and this is the
    board a coach who wants one per sheet prints. The three zone areas
    are the zone board's, its other half of the coach's strip (see
    `render_zone_board`), which is what leaves a board this short in
    the first place.

    `team` colours the rule under the header and the cell outlines, and
    puts the team's emoji in the corner; with no team it is all ink and the
    corner is empty -- the standard board is nobody's, so it names
    nobody.
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
    draw_maneuvers_panel(sheet, geometry, maneuvers)
    draw_team_footer(sheet, geometry, rules)

    return add_bleed(sheet.image) if bleed else sheet.image


def render_team_board_sheet(
    rules: BasicRuleset,
    players: PlayerCatalog,
    maneuvers: ManeuverCatalog,
    teams: tuple[Optional[Team], Optional[Team]] = (None, None),
    paper: str = TEAM_BOARD_PAPER,
    bleed: bool = False,
) -> Image.Image:
    """
    **Two boards on one page**, cut across the middle: `teams` is the
    top half's and the bottom half's. A coloured page is one of
    `TEAM_BOARD_PAGES` -- two colour teams, so the four print on two
    pages -- and the standard page is the uncoloured board twice.

    Each board is drawn once and pasted, and a board on both halves is
    one render pasted twice, which is what makes the two halves of the
    standard page the same picture by construction rather than by
    hoping two renders agree.
    """
    width, height = sheet_pixels(paper, landscape=False)
    sheet = Sheet(width, height)
    boards: dict[Optional[Team], Image.Image] = {}
    for team in teams:
        if team not in boards:
            boards[team] = render_team_board(
                rules, players, maneuvers, team=team, paper=paper
            )
    top, bottom = (boards[team] for team in teams)
    sheet.image.paste(top, (0, 0))
    sheet.image.paste(bottom, (0, height - bottom.height))
    draw_cut_line(sheet, top.height)

    return add_bleed(sheet.image) if bleed else sheet.image


# ---------------------------------------------------------- zone board
#
# **A coach's zone board** (the author, 2026-10-05): the three
# zone-assignment cells that used to be card rows above and below the
# field, as half a letter sheet of their own -- the same paper as the
# team board, so a coach lays the two end to end along their side of
# the field, zone board on their left. Each zone is a card's width,
# with its three cards cascaded down it rather than across: across, a
# zone a card wide has nowhere to put them.

# Each card in a zone sits this share of a card's height below the one
# behind it, so the top of every card -- its name -- shows.
ZONE_CASCADE = 0.1
# The zone board's own chrome, tighter than the team board's: it is
# what leaves a zone a real card's height of three cascaded.
ZONE_MARGIN_INCHES = 0.25
ZONE_COLUMN_GAP_INCHES = 0.1
ZONE_AREA_PADDING_INCHES = 0.04
# Between a zone's name and its area: the name's leading alone sets its
# descenders on the area's outline.
ZONE_LABEL_GAP_INCHES = 0.05


@dataclass(frozen=True)
class ZoneBoardGeometry:
    """
    One coach's zone board: a header and a row of three zone cells.

    Measured in inches, like the team board, and for the same reason:
    it is one physical thing on the table. The header is one line --
    the title, where it goes, and whose it is -- and the rule under it,
    and each cell's label is one line, because every line here is
    paid for out of a card's height.
    """

    left: float
    right: float
    top: float
    bottom: float
    rule_top: float
    columns: tuple[tuple[float, float], ...]
    label_top: float
    area_top: float
    area_bottom: float
    slot: tuple[float, float]

    @classmethod
    def for_sheet(cls, sheet: Sheet) -> "ZoneBoardGeometry":
        def inches(value: float) -> float:
            return value * PRINT_DPI

        margin = inches(ZONE_MARGIN_INCHES)
        left = margin
        right = sheet.width - margin
        top = margin
        bottom = sheet.height - margin

        rule_top = top + inches(
            TEAM_TITLE_INCHES * TEAM_TITLE_LEADING + TEAM_RULE_GAP_INCHES
        )
        label_top = rule_top + inches(
            TEAM_RULE_INCHES + TEAM_HEADER_GAP_INCHES
        )
        area_top = label_top + inches(
            TEAM_CELL_TITLE_INCHES * TEAM_TITLE_LEADING + ZONE_LABEL_GAP_INCHES
        )
        area_bottom = bottom

        gap = inches(ZONE_COLUMN_GAP_INCHES)
        width = (right - left - 2 * gap) / 3
        columns = tuple(
            (left + index * (width + gap), left + index * (width + gap) + width)
            for index in range(3)
        )

        padding = inches(ZONE_AREA_PADDING_INCHES)
        cascade = 1 + (CARDS_PER_AREA - 1) * ZONE_CASCADE
        slot_height = min(
            inches(CARD_INCHES[1]),
            (area_bottom - area_top - 2 * padding) / cascade,
            (width - 2 * padding) * CARD_INCHES[1] / CARD_INCHES[0],
        )
        return cls(
            left=left,
            right=right,
            top=top,
            bottom=bottom,
            rule_top=rule_top,
            columns=columns,
            label_top=label_top,
            area_top=area_top,
            area_bottom=area_bottom,
            slot=(slot_height * CARD_INCHES[0] / CARD_INCHES[1], slot_height),
        )


def zone_order(side: TeamSide) -> tuple[Zone, ...]:
    """
    The zones left to right **from this coach's own seat**. The two
    coaches sit on opposite sides of the table, so home reads the field
    from its Home Zone and the visitors from theirs -- each coach's own
    end is on their left, which is the end their zone board is laid at.
    """
    zones = tuple(Zone)
    return zones if side == TeamSide.HOME else zones[::-1]


def zone_slot_inches(paper: str = TEAM_BOARD_PAPER) -> tuple[float, float]:
    """How big a card the zone board's guides are cut for, in inches."""
    width, height = team_board_pixels(paper)
    geometry = ZoneBoardGeometry.for_sheet(Sheet(width, height))
    return geometry.slot[0] / PRINT_DPI, geometry.slot[1] / PRINT_DPI


def render_zone_board(
    board_size: int,
    side: TeamSide,
    paper: str = TEAM_BOARD_PAPER,
    bleed: bool = False,
) -> Image.Image:
    """
    **One coach's zone board**: a cell per zone, in the order that
    coach reads the field from their own seat, each tinted the field's
    own colour for that zone and guided for three cards.

    Half a letter sheet (8.5 x 5.5in), the team board's own size: the
    two are laid end to end along the coach's side of the field, the
    zone board on their left, and are seventeen inches together -- the
    field board's length. `render_zone_board_sheet` is the page both
    coaches' are cut from.

    It is per board size because the 9- and 10-space boards' outer
    zones are thirds (see `zone_labels`), and per side because the order
    is.
    """
    width, height = team_board_pixels(paper)
    sheet = Sheet(width, height)
    geometry = ZoneBoardGeometry.for_sheet(sheet)
    labels = zone_labels(board_size)

    title_font = print_font(TEAM_TITLE_INCHES, bold=True)
    sheet.text((geometry.left, geometry.top), "ZONE BOARD", title_font, INK)
    side_name = side_display_name(side).upper()
    sheet.text(
        (geometry.right, geometry.top), side_name, title_font, INK, anchor="ra"
    )
    # Where it goes, between the two: the one thing about this board a
    # coach needs telling, said where they will read it.
    note_left = geometry.left + sheet.text_width("ZONE BOARD", title_font)
    note_right = geometry.right - sheet.text_width(side_name, title_font)
    gutter = TEAM_COLUMN_GAP_INCHES * PRINT_DPI * 2
    note = "lay it on your left, your team board on your right"
    note_font = fitted_print_font(
        sheet, note, note_right - note_left - 2 * gutter, TEAM_BODY_INCHES
    )
    if note_font is not None:
        sheet.text(
            (
                (note_left + note_right) / 2,
                geometry.top + TEAM_TITLE_INCHES * PRINT_DPI * 0.55,
            ),
            note,
            note_font,
            MUTED,
            anchor="mm",
        )
    sheet.rect(
        (
            geometry.left,
            geometry.rule_top,
            geometry.right,
            geometry.rule_top + TEAM_RULE_INCHES * PRINT_DPI,
        ),
        fill=INK,
    )

    for (left, right), zone in zip(geometry.columns, zone_order(side)):
        draw_fitted(
            sheet,
            (left, geometry.label_top),
            labels[zone],
            right - left,
            TEAM_CELL_TITLE_INCHES,
            INK,
            bold=True,
        )
        draw_zone_cell(sheet, geometry, left, right, zone)

    return add_bleed(sheet.image) if bleed else sheet.image


def draw_zone_cell(
    sheet: Sheet,
    geometry: ZoneBoardGeometry,
    left: float,
    right: float,
    zone: Zone,
) -> None:
    """
    One zone's area, tinted the field's own colour for it, with **three
    cards dashed inside it, cascaded downward**: each `ZONE_CASCADE` of
    a card below the one behind it. A card behind shows only its top
    strip -- its top edge, and its two sides down to where the next
    card covers it -- never a line across the front card's face, the
    way the team board's benches draw theirs sideways.
    """
    area = (left, geometry.area_top, right, geometry.area_bottom)
    sheet.rect(
        area,
        radius=0.08 * PRINT_DPI,
        fill=ZONE_TINTS[zone],
        outline=INK,
        width=max(1, round(0.012 * PRINT_DPI)),
    )
    slot_width, slot_height = geometry.slot
    step = slot_height * ZONE_CASCADE
    stack_height = slot_height + (CARDS_PER_AREA - 1) * step
    card_left = (left + right - slot_width) / 2
    card_right = card_left + slot_width
    stack_top = (area[1] + area[3] - stack_height) / 2
    line = max(1, round(0.01 * PRINT_DPI))
    dash = 0.055 * PRINT_DPI
    for index in range(CARDS_PER_AREA):
        top = stack_top + index * step
        if index == CARDS_PER_AREA - 1:
            sheet.dashed_rect(
                (card_left, top, card_right, top + slot_height),
                outline=MUTED,
                width=line,
                dash=dash,
            )
            continue
        covered = top + step
        for x0, y0, x1, y1 in (
            (card_left, top, card_right, top),
            (card_left, top, card_left, covered),
            (card_right, top, card_right, covered),
        ):
            draw_dashed_line(
                sheet.draw,
                round(x0),
                round(y0),
                round(x1),
                round(y1),
                fill=MUTED,
                width=line,
                dash_length=round(dash),
                gap_length=round(dash * 0.7),
            )


def render_zone_board_sheet(
    board_size: int,
    paper: str = TEAM_BOARD_PAPER,
    bleed: bool = False,
) -> Image.Image:
    """
    **Both coaches' zone boards on one page**, home over the visitors,
    cut across the middle -- the zone boards' counterpart of
    `render_team_board_sheet`, which a match prints beside it. Both are
    printed upright: each is a board of its own, picked up and laid at
    its coach's seat.
    """
    width, height = sheet_pixels(paper, landscape=False)
    sheet = Sheet(width, height)
    home = render_zone_board(board_size, TeamSide.HOME, paper=paper)
    visitors = render_zone_board(board_size, TeamSide.VISITING, paper=paper)
    sheet.image.paste(home, (0, 0))
    sheet.image.paste(visitors, (0, height - visitors.height))
    draw_cut_line(sheet, home.height)

    return add_bleed(sheet.image) if bleed else sheet.image


def draw_cut_line(sheet: Sheet, y: float) -> None:
    """Where to cut the page in two, and nothing else on the seam."""
    draw_dashed_line(
        sheet.draw,
        0,
        round(y),
        sheet.width,
        round(y),
        fill=PAPER_EDGE,
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
    The board's own title, the team's emoji in the corner -- none on
    the standard board, which is no team's -- the roster under the
    title, and the rule under that.

    **The team is its emoji, not its name** (the author, 2026-10-04):
    the ringed letter the bot puts beside a team in Discord and the
    player cards carry in their corner (`player_cards.team_emoji`), so
    the board and the cards laid on it are marked the same way. It
    stands as tall as the header's two lines.

    **The roster line is wrapped to what the title leaves**, not fitted
    to it: the line names nine cards by role and is the first thing on
    the board a coach actually reads. It used to be drawn at whatever
    width it came out at and ran straight through the rule below.
    """
    title_font = print_font(TEAM_TITLE_INCHES, bold=True)
    sheet.text((geometry.left, geometry.top), "TEAM BOARD", title_font, INK)

    roster_right = geometry.right
    emoji = team_emoji(team) if team is not None else None
    if emoji is not None:
        side = round(
            geometry.rule_top - geometry.top - TEAM_RULE_GAP_INCHES * PRINT_DPI
        )
        mark = emoji.resize((side, side), Image.LANCZOS)
        sheet.image.paste(
            mark, (round(geometry.right) - side, round(geometry.top)), mark
        )
        roster_right -= side + TEAM_COLUMN_GAP_INCHES * PRINT_DPI
    draw_fitted(
        sheet,
        (geometry.left, geometry.roster_top),
        roster_line(players),
        roster_right - geometry.left,
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
    return " · ".join(parts)


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
    One area a coach's cards sit in, with **three cards dashed inside
    it, stacked sideways** -- the stack a bench is.

    Each card sits `TEAM_BENCH_CASCADE` of a card to the right of the
    one behind it (the author, 2026-09-28, over a first cut that
    stacked them downward). A card behind is drawn only where the one
    in front leaves it showing -- its top, left and bottom edges out to
    where the next card covers it -- never a line across the front
    card's face. Side by side without overlapping does not fit: half a
    letter sheet gives a column two and a half inches wide. A single
    outline, which is what this replaced, said nothing about there
    being three.
    """
    left, right = geometry.columns[column]
    draw_cell_label(sheet, geometry, column, title, caption)

    area = geometry.area(column)
    sheet.rect(
        area,
        radius=0.08 * PRINT_DPI,
        fill=PAPER_PANEL,
        outline=accent,
        width=max(1, round(0.012 * PRINT_DPI)),
    )

    slot_width, slot_height = geometry.slot
    step = slot_width * TEAM_BENCH_CASCADE
    stack_width = slot_width + (TEAM_BENCH_CARDS - 1) * step
    stack_left = (left + right - stack_width) / 2
    top = (area[1] + area[3] - slot_height) / 2
    bottom = top + slot_height
    line = max(1, round(0.01 * PRINT_DPI))
    dash = 0.055 * PRINT_DPI
    for index in range(TEAM_BENCH_CARDS):
        card_left = stack_left + index * step
        if index == TEAM_BENCH_CARDS - 1:
            sheet.dashed_rect(
                (card_left, top, card_left + slot_width, bottom),
                outline=PAPER_EDGE,
                width=line,
                dash=dash,
            )
            continue
        # A card behind shows only its left strip: its left edge, and
        # its top and bottom edges out to where the next card covers it.
        covered = card_left + step
        for x0, y0, x1, y1 in (
            (card_left, top, card_left, bottom),
            (card_left, top, covered, top),
            (card_left, bottom, covered, bottom),
        ):
            draw_dashed_line(
                sheet.draw,
                round(x0),
                round(y0),
                round(x1),
                round(y1),
                fill=PAPER_EDGE,
                width=line,
                dash_length=round(dash),
                gap_length=round(dash * 0.7),
            )


def draw_maneuvers_panel(
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
    corners are cut instead, so the board's own ground shows around it
    the way it does around a real card lying on the board rather than
    leaving four white squares.
    """
    draw_cell_label(
        sheet,
        geometry,
        column=2,
        title="MANEUVERS",
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
        ("FORMATIONS", True, 0.13)
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
    return "Standard Formation (2-2-2): " + " · ".join(parts) + "."


def team_reminder() -> str:
    """
    The last line of the footer: the two things about a card on this
    board that are not on it.
    """
    return (
        "A card's zone is assigned on the zone board beside this one. A "
        "player is Exhausted once their tokens exceed their defence."
    )


def draw_team_footer(
    sheet: Sheet,
    geometry: TeamBoardGeometry,
    rules: BasicRuleset,
) -> None:
    """
    The shapes, the standard formation, and the reminder.

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
    draw_fitted(
        sheet,
        (geometry.left, reminder_line),
        team_reminder(),
        geometry.right - geometry.left,
        TEAM_SMALL_INCHES,
        MUTED,
    )
