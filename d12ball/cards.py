"""
The six maneuvers as cards.

Two things are drawn from one layout. `render_maneuver_card` is the
print-ready face for the physical game -- 2.5 x 3.5 inches at 300dpi,
optionally with the bleed a printer trims into -- and
`render_maneuver_hand` puts a side's three side by side, which is what
the bot shows a coach who has just clicked "Choose Your Maneuver".
They share the layout on purpose: a coach who has played at the table
and a coach playing by Discord should be reading the same card.

Everything on a face is read from the data the bot plays from --
`maneuvers.json` for the effect, the time cost and who beats whom, and
`players.json` for the role abilities. So a card cannot state a rule
the bot does not, and an import that changes either file changes the
cards without anything here being edited.

Which roles a card lists is mostly matched, not tabulated: a role is on
the card when its ability sentence names that maneuver, so the Fullback
appears on both High Pass and Block Deflect. Abilities are never cut
down here; see "Every ability is imported twice" in CLAUDE.md. The two
things that match cannot find are listed explicitly below, each with
the reason -- see EXTRA_ROLES and EXTRA_NOTES.
"""
from io import BytesIO
from typing import NamedTuple

from PIL import Image, ImageDraw, ImageFont

from d12ball.components import (
    ManeuverCatalog,
    ManeuverDefinition,
    PlayerCatalog,
)
from d12ball.render import draw_dashed_line, load_font, wrap_text


# Poker size -- 2.5 x 3.5 inches at 300dpi -- with the 1/8in bleed a
# printer trims into. Everything below is in trimmed-card pixels;
# SUPERSAMPLE draws it larger and shrinks it down, because Pillow does
# not antialias the rounded rectangles and circles this is mostly made
# of.
CARD_WIDTH = 750
CARD_HEIGHT = 1050
BLEED = 38
SUPERSAMPLE = 2

MARGIN = 34
# The card is drawn as a rounded rectangle inset by FRAME, and what
# lies outside that corner is the sheet, not the card. It used to be
# the maneuver's colour, edge to edge -- a saturated border around
# every card and a black back, which is a lot of ink for a print run
# and the first thing a home printer runs out of. The colour is now
# the outline and the header band; the rest is paper.
FRAME = 6
CORNER = 40
# The rounded edge, drawn in the maneuver's colour, is also the cut
# line: it is what says where the card ends now that the face and the
# sheet are the same white.
EDGE_WIDTH = 5

# The offense/defense colours the maneuver reference image already
# uses, so a coach reading a card and a coach reading the bot's
# hexagon are looking at the same two colours.
OFFENSE_COLOR = "#E24B4A"
DEFENSE_COLOR = "#97C459"
# The paper tone the boards are printed on. The cards are white
# instead -- they are printed nine to a page and a tinted face is a
# full page of ink for nothing, where a board is one sheet a game.
FACE_COLOR = "#f6f1e6"
CARD_FACE = "#ffffff"
PANEL_COLOR = "#e6ded0"
PANEL_EDGE = "#c3b7a3"
INK = "#14202b"
MUTED = "#5d6b78"
# The back is white for the same reason, and is the one card printed
# six times over.
BACK_COLOR = "#ffffff"
BACK_EDGE = "#8c9aa6"
# The tie lines on the back. Lighter than the arrows they cross, so
# the cycle still reads as the first thing on the card.
TIE_COLOR = "#7e8d9a"

# The strip diagram is the standard seven-space board with the ball on
# the third space, which is the only position from which every maneuver
# on every card fits: a High Pass of 4 lands on the last space and a
# Fullback's Block Deflect of 2 on the first.
STRIP_SPACES = 7
BALL_SPACE = 2
ATTACK_RIGHT = True


def font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    return load_font(size * SUPERSAMPLE, bold=bold)


def px(value: float) -> float:
    return value * SUPERSAMPLE


class Pen:
    """
    Draws in trimmed-card coordinates onto the supersampled canvas, so
    the layout below reads in the units the card is actually measured
    in. Every method takes and returns those units.
    """

    def __init__(self, size: tuple[int, int], background: str) -> None:
        self.image = Image.new(
            "RGB",
            (round(px(size[0])), round(px(size[1]))),
            background,
        )
        self.draw = ImageDraw.Draw(self.image)

    def rect(
        self,
        box: tuple[float, float, float, float],
        radius: float = 0,
        fill: str | None = None,
        outline: str | None = None,
        width: float = 1,
    ) -> None:
        scaled = tuple(px(value) for value in box)
        if radius:
            self.draw.rounded_rectangle(
                scaled,
                radius=px(radius),
                fill=fill,
                outline=outline,
                width=round(px(width)),
            )
        else:
            self.draw.rectangle(
                scaled, fill=fill, outline=outline, width=round(px(width))
            )

    def circle(
        self,
        center: tuple[float, float],
        radius: float,
        fill: str | None = None,
        outline: str | None = None,
        width: float = 1,
    ) -> None:
        cx, cy = center
        self.draw.ellipse(
            (
                px(cx - radius),
                px(cy - radius),
                px(cx + radius),
                px(cy + radius),
            ),
            fill=fill,
            outline=outline,
            width=round(px(width)),
        )

    def line(
        self,
        points: list[tuple[float, float]],
        fill: str,
        width: float = 1,
    ) -> None:
        self.draw.line(
            [(px(x), px(y)) for x, y in points],
            fill=fill,
            width=round(px(width)),
            joint="curve",
        )

    def polygon(self, points: list[tuple[float, float]], fill: str) -> None:
        self.draw.polygon([(px(x), px(y)) for x, y in points], fill=fill)

    def paste(
        self,
        image: Image.Image,
        center: tuple[float, float],
        size: tuple[float, float],
    ) -> None:
        """
        A picture centred on a point, `size` card units across.

        Resized straight to the supersampled canvas's pixels rather
        than to the card's: the supersampling is here because Pillow
        does not antialias the shapes the cards are drawn out of, and a
        photograph put through it would be resampled twice on the way
        out of `finish` for nothing. Its own alpha is the mask, so a
        cut-out portrait sits on the face rather than on a box.
        """
        scaled = image.resize(
            (round(px(size[0])), round(px(size[1]))),
            Image.Resampling.LANCZOS,
        )
        self.image.paste(
            scaled,
            (
                round(px(center[0] - size[0] / 2)),
                round(px(center[1] - size[1] / 2)),
            ),
            scaled if scaled.mode == "RGBA" else None,
        )

    def dashed_line(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
        fill: str,
        width: float = 1,
        dash: float = 16,
        gap: float = 12,
    ) -> None:
        draw_dashed_line(
            self.draw,
            px(start[0]),
            px(start[1]),
            px(end[0]),
            px(end[1]),
            fill=fill,
            width=round(px(width)),
            dash_length=round(px(dash)),
            gap_length=round(px(gap)),
        )

    def ink_box(
        self,
        text: str,
        face: ImageFont.ImageFont,
        anchor: str = "mm",
    ) -> tuple[float, float, float, float]:
        """
        Where the marks actually land around an anchor point, in card
        units. Pillow's `m` anchor centres on the font's ascender and
        descender rather than on the glyphs, so a line of capitals is
        drawn low by whatever room its descenders are entitled to and
        never use. Stacking lines by their ink is what centres a block
        of them by eye.
        """
        box = self.draw.textbbox((0, 0), text, font=face, anchor=anchor)
        return tuple(value / SUPERSAMPLE for value in box)

    def text_size(
        self, text: str, face: ImageFont.ImageFont
    ) -> tuple[float, float]:
        box = self.draw.textbbox((0, 0), text, font=face)
        return (
            (box[2] - box[0]) / SUPERSAMPLE,
            (box[3] - box[1]) / SUPERSAMPLE,
        )

    def text(
        self,
        position: tuple[float, float],
        text: str,
        face: ImageFont.ImageFont,
        fill: str,
        anchor: str = "la",
    ) -> None:
        x, y = position
        self.draw.text(
            (px(x), px(y)), text, font=face, fill=fill, anchor=anchor
        )

    def wrapped(
        self,
        text: str,
        face: ImageFont.ImageFont,
        max_width: float,
    ) -> list[str]:
        return wrap_text(self.draw, text, face, px(max_width))

    def finish(self, bleed: bool, background: str) -> Image.Image:
        card = self.image.resize(
            (CARD_WIDTH, CARD_HEIGHT), Image.Resampling.LANCZOS
        )
        if not bleed:
            return card
        sheet = Image.new(
            "RGB",
            (CARD_WIDTH + BLEED * 2, CARD_HEIGHT + BLEED * 2),
            background,
        )
        sheet.paste(card, (BLEED, BLEED))
        return sheet


def line_height(pen: Pen, face: ImageFont.ImageFont) -> float:
    return pen.text_size("Hg", face)[1] * 1.62


def fitted_title(
    pen: Pen, name: str, max_width: float
) -> tuple[list[str], ImageFont.ImageFont]:
    """
    The largest title that fits the header, on one line if it can and
    two if it cannot. "Steal Intercept" and "Dribble Advance" are the
    long ones and both break cleanly at their space.
    """
    for size in range(54, 29, -2):
        face = font(size, bold=True)
        if pen.text_size(name, face)[0] <= max_width:
            return [name], face
    face = font(40, bold=True)
    return name.split(" ", 1), face


# A role whose ability does not name the maneuver but belongs on its
# card anyway. The Striker's +3 is for scoring off a set-up, one step
# removed from the maneuver that produced the set-up -- three maneuvers
# can produce one, and the author's ruling is that a High Pass is much
# the most common way it happens, so it goes there and nowhere else.
# The sentence still comes from players.json; only the placement is
# here.
EXTRA_ROLES: dict[str, tuple[str, ...]] = {
    "High Pass": ("striker",),
}

# What a maneuver's own rules add to it, where no role ability names it
# and so nothing in the data can be matched against. Steal Intercept's
# is the one modifier that decides the maneuver and the only maneuver
# whose card would otherwise be blank; the wording is the author's.
# It cannot live in maneuvers.json, which the sheet import rewrites
# whole.
EXTRA_NOTES: dict[str, tuple[tuple[str, str], ...]] = {
    "Steal Intercept": (
        (
            "BALL SPEED",
            "The defender adds the ball speed modifier to this skill test.",
        ),
    ),
}


def role_abilities(
    catalog: PlayerCatalog, maneuver: ManeuverDefinition
) -> list[tuple[str, str]]:
    """
    What the abilities band says: the roles whose ability names this
    maneuver, then any role placed here by hand, then the maneuver's
    own modifiers. Matching on the name is what keeps the first group
    in step with an import -- a new ability mentioning a maneuver
    reaches the card without anything here being edited.
    """
    needle = maneuver.name.lower()
    extra = EXTRA_ROLES.get(maneuver.name, ())
    rows = [
        (role.value.upper(), profile.ability)
        for role, profile in catalog.role_profiles.items()
        if needle in profile.ability.lower() or role.value in extra
    ]
    rows.extend(EXTRA_NOTES.get(maneuver.name, ()))
    return rows


class Move(NamedTuple):
    """
    One arc on the strip diagram.

    `offset` is in spaces along the offense's attacking direction, which
    is the diagram's one axis -- so it is where the piece ends up on the
    picture, never "forward" or "back" from anybody's point of view.
    Those two words mean opposite things to the two sides and are what
    got Pressure and Steal Intercept drawn mirrored: a challenger's
    forward is toward the goal *they* attack, and a steal's back is
    toward the new possessor's own goal, which is the goal the offense
    was attacking. Both are verified against `move_player_relative`.

    `start` is the x it leaves from within the ball's space, so an arc
    departs the token that actually moves rather than the middle of the
    space. `caption_at` may sit between two spaces, for a caption that
    covers both. `row` and `lift` keep two arcs out of each other's way.
    """

    offset: int
    label: str
    side: str
    dashed: bool = False
    caption_at: float | None = None
    start: float = 0.0
    end: float = 0.0
    lift: float = 0.0
    row: int | None = None

    @property
    def caption_space(self) -> float:
        return self.offset if self.caption_at is None else self.caption_at

    @property
    def caption_row(self) -> int:
        return (1 if self.dashed else 0) if self.row is None else self.row


def arc_rise(move: Move) -> float:
    """
    How far above the strip a move's arc peaks. It grows with the
    distance so a High Pass's three throws out of one space stay told
    apart, and the diagram is laid out around the tallest of them --
    which is why this is a function and not a number inside the drawing
    loop.
    """
    return 18 + 20 * abs(move.offset) + move.lift


def draw_arrowhead(
    pen: Pen,
    tip: tuple[float, float],
    direction: tuple[float, float],
    size: float,
    fill: str,
) -> None:
    dx, dy = direction
    back = (tip[0] - dx * size, tip[1] - dy * size)
    perp = (-dy, dx)
    half = size * 0.55
    pen.polygon(
        [
            tip,
            (back[0] + perp[0] * half, back[1] + perp[1] * half),
            (back[0] - perp[0] * half, back[1] - perp[1] * half),
        ],
        fill=fill,
    )


# A dashed arc is a role's variant rather than the ordinary move, and
# that is the only thing the dashes mean -- Low Pass's backward option
# is solid because it is a choice any passer has.
STRIP_MOVES: dict[str, tuple[Move, ...]] = {
    "Low Pass": (
        Move(2, "nearest ahead", "offense"),
        Move(-2, "or behind", "offense"),
    ),
    "Dribble Advance": (
        Move(1, "handler + ball", "offense"),
        Move(2, "playmaker", "offense", dashed=True),
    ),
    "High Pass": (
        Move(2, "received\nmay set up scoring", "offense"),
        Move(3, "contested", "offense", caption_at=3.5),
        Move(4, "fullback", "offense", dashed=True),
    ),
    "Block Deflect": (
        Move(-1, "ball back", "defense"),
        Move(-2, "fullback", "defense", dashed=True),
    ),
    # The interceptor falls back toward their own goal, which is the one
    # the offense was attacking -- so a steal moves the ball the way the
    # offense was going, not against it.
    "Steal Intercept": (
        Move(1, "carrier + ball", "defense", start=19),
    ),
    # Both end on the same space: the handler is shoved back and the
    # challenger advances onto them, and a Defender's won Pressure
    # steals, which it could not do from anywhere else.
    # Each arc runs token to token, or the two would share an endpoint
    # and one arrowhead would be drawn under the other.
    "Pressure": (
        Move(-1, "handler + ball", "offense", start=-19, end=-19),
        Move(-1, "challenger", "defense", start=19, end=19, lift=26, row=1),
    ),
}
# What stands on the ball's space to begin with, and what a landing
# space is drawn holding. A blank landing means the ball alone, and the
# space carries the distance instead.
STRIP_ACTORS: dict[str, tuple[str, dict[int, str]]] = {
    "Low Pass": ("H", {2: "R", -2: "R"}),
    "Dribble Advance": ("H", {1: "H", 2: "H"}),
    "High Pass": ("H", {}),
    "Block Deflect": ("H", {}),
    "Steal Intercept": ("HC", {1: "C"}),
    "Pressure": ("HC", {-1: "HC"}),
}


def draw_strip(
    pen: Pen,
    maneuver: ManeuverDefinition,
    top: float,
    height: float,
) -> None:
    """
    The seven-space board with the maneuver drawn on it: who moves,
    where the ball goes, and how far. The diagram is what a card can
    say that a die face cannot, so it carries the geometry and the
    effect text below carries the wording.

    Distances are labelled under the space they land on rather than on
    the arc itself. High Pass draws three arcs out of one space, and
    labelling those at their peaks stacked three captions on top of
    each other; hung off the destination they cannot collide, because
    no two of a maneuver's moves land on the same space.
    """
    left = MARGIN + 18
    right = CARD_WIDTH - MARGIN - 18
    pen.rect(
        (MARGIN, top, CARD_WIDTH - MARGIN, top + height),
        radius=18,
        fill=PANEL_COLOR,
        outline=PANEL_EDGE,
        width=2,
    )

    moves = STRIP_MOVES[maneuver.name]
    standing, landings = STRIP_ACTORS[maneuver.name]

    space_width = (right - left) / STRIP_SPACES
    strip_height = 76
    # How deep the caption block is depends on the maneuver: High Pass
    # says two lines about its 2-space landing and still needs a row
    # below for the Fullback's. The strip floats up to make room rather
    # than the captions being squeezed.
    caption_line = 25
    rows = sorted({move.caption_row for move in moves})
    row_lines = {
        row: max(
            len(move.label.split("\n"))
            for move in moves
            if move.caption_row == row
        )
        for row in rows
    }
    row_top = {}
    cursor = 0.0
    for row in rows:
        row_top[row] = cursor
        cursor += row_lines[row] * caption_line
    label_room = cursor + 12

    # The diagram is centred in the panel rather than sitting on its
    # floor. How tall it is varies a lot -- High Pass's longest arc
    # rises four spaces' worth above the strip and Steal Intercept's
    # one arc barely leaves it -- so a fixed anchor leaves one card or
    # the other with a band of empty panel.
    tallest = max(arc_rise(move) for move in moves)
    ink_above = strip_height / 2 - 30 - tallest - 12
    block = strip_height + label_room - ink_above
    strip_top = top + 46 + ((height - 54) - block) / 2 - ink_above
    for index in range(STRIP_SPACES):
        space_left = left + index * space_width
        pen.rect(
            (
                space_left + 3,
                strip_top,
                space_left + space_width - 3,
                strip_top + strip_height,
            ),
            radius=8,
            fill="#f1ebdd",
            outline=PANEL_EDGE,
            width=2,
        )

    colors = {"offense": OFFENSE_COLOR, "defense": DEFENSE_COLOR}
    forward = 1 if ATTACK_RIGHT else -1
    here = BALL_SPACE

    def center(index: float) -> tuple[float, float]:
        return (
            left + (index + 0.5) * space_width,
            strip_top + strip_height / 2,
        )

    def token(
        index: int,
        color: str,
        label: str,
        ghost: bool = False,
        offset: float = 0,
        radius: float = 23,
    ) -> None:
        cx, cy = center(index)
        cx += offset
        if ghost:
            pen.circle((cx, cy), radius, fill="#f1ebdd", outline=color, width=3)
        else:
            pen.circle((cx, cy), radius, fill=color, outline="#f1ebdd", width=2)
        pen.text(
            (cx, cy + 1),
            label,
            font(20, bold=True),
            color if ghost else "#ffffff",
            anchor="mm",
        )

    def arc(move: Move, color: str) -> None:
        x0, y0 = center(here)
        x1, y1 = center(here + move.offset * forward)
        x0 += move.start
        x1 += move.end
        y0 -= 30
        y1 -= 30
        peak = min(y0, y1) - arc_rise(move)
        steps = 30
        points = []
        for step in range(steps + 1):
            t = step / steps
            x = (1 - t) ** 2 * x0 + 2 * (1 - t) * t * (x0 + x1) / 2 + t**2 * x1
            y = (1 - t) ** 2 * y0 + 2 * (1 - t) * t * peak + t**2 * y1
            points.append((x, y))
        if move.dashed:
            for step in range(0, steps - 3, 3):
                pen.line(points[step : step + 2], fill=color, width=5)
        else:
            pen.line(points[:-1], fill=color, width=5)
        tail, tip = points[-3], points[-1]
        dx, dy = tip[0] - tail[0], tip[1] - tail[1]
        length = max((dx * dx + dy * dy) ** 0.5, 0.001)
        draw_arrowhead(pen, tip, (dx / length, dy / length), 19, color)

    def caption(move: Move, color: str) -> None:
        """
        Hung under the space the move lands on -- or between two of
        them, where one caption covers both, as a High Pass's contested
        3 and 4 do. A second row keeps two captions on neighbouring
        spaces off each other; a role's variant takes it by default.
        """
        cx, _ = center(here + move.caption_space * forward)
        # How much room this caption has is how far the next caption on
        # its row is: High Pass lands on consecutive spaces and gets a
        # space's width each, while a lone caption may run wide.
        neighbours = [
            abs(other.caption_space - move.caption_space)
            for other in moves
            if other is not move and other.caption_row == move.caption_row
        ]
        room = space_width * (min(neighbours) if neighbours else 2.4) - 8
        lines = move.label.split("\n")
        for size in range(17, 11, -1):
            face = font(size, bold=True)
            width = max(pen.text_size(line, face)[0] for line in lines)
            if width <= room:
                break
        # A caption on the first or last space would otherwise hang off
        # the panel, so it slides back inside rather than being cut.
        cx = min(max(cx, left + width / 2), right - width / 2)
        y = strip_top + strip_height + 8 + row_top[move.caption_row]
        for line in lines:
            pen.text((cx, y), line, face, color, anchor="ma")
            y += caption_line

    def ghosts(index: float, who: str) -> None:
        if len(who) == 1:
            token(index, colors["offense" if who in "HR" else "defense"], who,
                  ghost=True)
            return
        for label, offset in zip(who, (-19, 19)):
            token(
                index,
                colors["offense" if label in "HR" else "defense"],
                label,
                ghost=True,
                offset=offset,
                radius=20,
            )

    for move in moves:
        arc(move, colors[move.side])

    drawn: set[int] = set()
    for move in moves:
        who = landings.get(move.offset)
        if who is not None:
            # Pressure's two moves land on one space, so its pair of
            # ghosts is drawn once rather than once per arc.
            if move.offset not in drawn:
                ghosts(here + move.offset * forward, who)
                drawn.add(move.offset)
        else:
            # Nothing lands here but the ball, so the space carries how
            # far it came instead -- the distance is the choice on a
            # High Pass and the ability on a Block Deflect.
            cx, cy = center(here + move.offset * forward)
            pen.text(
                (cx, cy + 1),
                str(abs(move.offset)),
                font(30, bold=True),
                PANEL_EDGE,
                anchor="mm",
            )
        caption(move, colors[move.side])

    # The ball's own space last, so its tokens sit over the arcs that
    # leave it. Pressure is the one maneuver with both players on it.
    if standing == "HC":
        token(here, colors["offense"], "H", offset=-19, radius=20)
        token(here, colors["defense"], "C", offset=19, radius=20)
        # On the handler's outside shoulder: between the two tokens the
        # ball would read as the challenger's, and it is not until the
        # steal resolves.
        ball_x, ball_y = center(here)
        ball_x -= 36
    else:
        token(here, colors["offense" if standing == "H" else "defense"], standing)
        ball_x, ball_y = center(here)
        ball_x += 17
    pen.circle((ball_x, ball_y - 19), 12, fill=INK)
    pen.circle((ball_x, ball_y - 19), 12, outline="#f1ebdd", width=2)

    pen.text(
        (right, top + 16),
        f"offense attacks {'→' if ATTACK_RIGHT else '←'}",
        font(16),
        MUTED,
        anchor="ra",
    )
    pen.text(
        (left, top + 16),
        "H handler   C challenger",
        font(16),
        MUTED,
        anchor="la",
    )


def draw_matchups(
    pen: Pen,
    catalog: ManeuverCatalog,
    maneuver: ManeuverDefinition,
    is_offense: bool,
    top: float,
    height: float,
) -> None:
    """
    Who this beats, ties and loses to. All three opponents are on the
    other side of the ball, so the labels carry the meaning rather than
    the colour -- an offense card's three names are all defense
    maneuvers, and colouring them would say nothing.
    """
    side = "offense" if is_offense else "defense"
    defeats, defeated_by, ties = catalog.relationships(maneuver.name, side)
    column_width = (CARD_WIDTH - MARGIN * 2) / 3

    pen.line(
        [(MARGIN + 10, top), (CARD_WIDTH - MARGIN - 10, top)],
        fill=PANEL_EDGE,
        width=2,
    )

    columns = (
        ("BEATS", defeats, INK),
        ("TIES", ties, MUTED),
        ("LOSES TO", defeated_by, MUTED),
    )
    for index, (label, name, color) in enumerate(columns):
        cx = MARGIN + column_width * (index + 0.5)
        pen.text((cx, top + 26), label, font(17, bold=True), MUTED, anchor="mm")
        for line_index, line in enumerate(name.split(" ")):
            pen.text(
                (cx, top + 56 + line_index * 26),
                line,
                font(21, bold=True),
                color,
                anchor="mm",
            )
        if index:
            pen.line(
                [
                    (MARGIN + column_width * index, top + 14),
                    (MARGIN + column_width * index, top + height - 8),
                ],
                fill=PANEL_EDGE,
                width=2,
            )


def laid_out_abilities(
    pen: Pen, abilities: list[tuple[str, str]]
) -> tuple[list[tuple[str, float, list[str]]], float]:
    """
    Each row as (label, label width, wrapped lines), and the height the
    band needs. Measured in one place because the band is drawn from
    the bottom of the card up: the layout has to know how tall it is
    before it knows where it starts, and a second measurement that
    disagreed would push the effect text off centre.
    """
    label_font = font(19, bold=True)
    body = font(19)
    height = 62.0
    rows: list[tuple[str, float, list[str]]] = []

    if not abilities:
        return rows, height + 34

    for label, text in abilities:
        label_width = pen.text_size(label, label_font)[0] + 12
        lines = pen.wrapped(
            text, body, CARD_WIDTH - MARGIN * 2 - label_width - 8
        )
        rows.append((label, label_width, lines))
        height += len(lines) * line_height(pen, body) + 6
    return rows, height


def draw_abilities(
    pen: Pen,
    abilities: list[tuple[str, str]],
    top: float,
) -> None:
    pen.line(
        [(MARGIN + 10, top), (CARD_WIDTH - MARGIN - 10, top)],
        fill=PANEL_EDGE,
        width=2,
    )
    pen.text(
        (CARD_WIDTH / 2, top + 24),
        "ABILITIES IN PLAY",
        font(17, bold=True),
        MUTED,
        anchor="mm",
    )

    body = font(19)
    label_font = font(19, bold=True)
    rows, _ = laid_out_abilities(pen, abilities)
    y = top + 46

    if not rows:
        pen.text(
            (CARD_WIDTH / 2, y + 18),
            "No role ability changes this maneuver.",
            body,
            MUTED,
            anchor="mm",
        )
        return

    for label, label_width, lines in rows:
        pen.text((MARGIN + 4, y), label, label_font, INK)
        for line in lines:
            pen.text((MARGIN + 4 + label_width, y), line, body, INK)
            y += line_height(pen, body)
        y += 6


def render_maneuver_card(
    catalog: ManeuverCatalog,
    players: PlayerCatalog,
    maneuver: ManeuverDefinition,
    is_offense: bool,
    bleed: bool,
) -> Image.Image:
    color = OFFENSE_COLOR if is_offense else DEFENSE_COLOR
    pen = Pen((CARD_WIDTH, CARD_HEIGHT), CARD_FACE)

    # The card is a rounded rectangle on the sheet's white, outlined in
    # the maneuver's colour: the outline is the card's edge and the cut
    # line at once.
    pen.rect(
        (FRAME, FRAME, CARD_WIDTH - FRAME, CARD_HEIGHT - FRAME),
        radius=CORNER,
        fill=CARD_FACE,
        outline=color,
        width=EDGE_WIDTH,
    )

    # Header: the rank badge and the name, in a band whose top corners
    # follow the card's own.
    header_top = FRAME
    header_height = 152
    pen.rect(
        (FRAME, header_top, CARD_WIDTH - FRAME, header_top + header_height),
        radius=CORNER,
        fill=color,
    )
    pen.rect(
        (
            FRAME,
            header_top + header_height - CORNER,
            CARD_WIDTH - FRAME,
            header_top + header_height,
        ),
        fill=color,
    )

    rank_label = f"{'O' if is_offense else 'D'}{maneuver.rank}"
    badge_center = (FRAME + 82, header_top + header_height / 2)
    pen.circle(badge_center, 46, fill=CARD_FACE)
    pen.text(badge_center, rank_label, font(38, bold=True), color, anchor="mm")

    # What kind of card this is, rather than which die faces it stands
    # in for. The faces were printed here while the cards and the
    # selection die had to coexist; naming the mode is what will still
    # mean something once a second set of maneuvers exists.
    pen.text(
        (CARD_WIDTH - FRAME - 62, header_top + header_height / 2),
        "BASIC\nMANEUVER",
        font(15, bold=True),
        "#ffffff",
        anchor="mm",
    )

    title_left = FRAME + 140
    title_right = CARD_WIDTH - FRAME - 118
    lines, title_font = fitted_title(pen, maneuver.name, title_right - title_left)
    title_center = (title_left + title_right) / 2
    title_step = line_height(pen, title_font)
    title_y = (
        header_top
        + header_height / 2
        - title_step * (len(lines) - 1) / 2
    )
    for line in lines:
        pen.text(
            (title_center, title_y), line, title_font, "#ffffff", anchor="mm"
        )
        title_y += title_step

    strip_top = header_top + header_height + 22
    strip_height = 288
    draw_strip(pen, maneuver, strip_top, strip_height)

    # The two bands below are placed from the bottom edge up, so the
    # effect gets the whole of the remaining middle and stays the thing
    # in the centre of the card whatever length the other two run to.
    abilities = role_abilities(players, maneuver)
    _, ability_height = laid_out_abilities(pen, abilities)

    abilities_top = CARD_HEIGHT - FRAME - 18 - ability_height
    matchup_height = 118
    matchup_top = abilities_top - matchup_height

    draw_matchups(
        pen, catalog, maneuver, is_offense, matchup_top, matchup_height
    )
    draw_abilities(pen, abilities, abilities_top)

    # The effect, centred in what is left, with the time cost pinned
    # under it -- the clock is part of what the maneuver costs, so it
    # belongs to the effect rather than to the diagram, where it used
    # to sit and collide with the board strip.
    effect_font = font(29)
    time_font = font(19, bold=True)
    lines = pen.wrapped(maneuver.effect, effect_font, CARD_WIDTH - MARGIN * 2 - 20)
    step = line_height(pen, effect_font)
    time_text = f"TIME · {maneuver.time}"
    time_width = pen.text_size(time_text, time_font)[0] + 34
    block_height = step * len(lines) + 26 + 38

    y = (strip_top + strip_height + matchup_top) / 2 - block_height / 2
    for line in lines:
        pen.text((CARD_WIDTH / 2, y), line, effect_font, INK, anchor="ma")
        y += step

    y += 26
    pen.rect(
        (
            (CARD_WIDTH - time_width) / 2,
            y,
            (CARD_WIDTH + time_width) / 2,
            y + 38,
        ),
        radius=19,
        fill=PANEL_COLOR,
        outline=PANEL_EDGE,
        width=2,
    )
    pen.text(
        (CARD_WIDTH / 2, y + 20), time_text, time_font, MUTED, anchor="mm"
    )

    return pen.finish(bleed, CARD_FACE)


# The cycle on the back, sized to the card rather than to itself. It
# is the whole of what that side says, and a coach reads it off the
# deck between them, so it is drawn as wide as the card will carry: the
# side vertices clear the cut line by CYCLE_SIDE_MARGIN and nothing
# else on the card is wider. The vertical radius is the shorter of the
# two because the heading and the caption bound it there and the width
# is what was asked for -- a tenth of an ellipse, which reads as a
# hexagon.
CYCLE_NODE_RADIUS = 76
CYCLE_RADIUS_X = 315
CYCLE_RADIUS_Y = 284
CYCLE_CENTER_Y = 548

# A node's label is the maneuver's name alone, one word to a line --
# the O1/D1 rank badge that used to sit above it named the selection
# die, and the team board's own cell already carries that (see "The
# printed boards" in CLAUDE.md), so it was the one thing on this card
# a coach never needed to look up. Dropping it freed the whole circle
# for the name, which is why the size below is a search rather than a
# constant: "Intercept" has to clear the circle where it sits, which
# is below the middle and so on a shorter chord than the diameter, and
# "Pressure" is a single line with the whole circle to itself.
CYCLE_LINE_GAP = 6
CYCLE_LABEL_MARGIN = 8

# Sized independently every node would grow to whatever its own name
# allows, and "Low Pass"/"High Pass" have nothing holding them back --
# so the six read as different alphabets rather than one. This is the
# name that pins the ceiling instead: the widest pairing that still
# only asks for two lines, so it is the most any node can carry
# without the short names ballooning past it. Named rather than
# computed as the tightest fit across all six, because the tightest is
# "Steal Intercept" -- "Intercept" alone -- and capping there would
# shrink "Block Deflect" for no reason; the two constraints happen to
# be close but are not the same one.
CYCLE_LABEL_REFERENCE = "Block Deflect"

# How far short of a node's edge a tie line stops, and how it is
# drawn. Stopping outside the circle keeps the dashes from running
# under a label, and the line is thinner than an arrow because it is
# the quieter relation.
TIE_NODE_GAP = CYCLE_NODE_RADIUS + 7
TIE_WIDTH = 6
TIE_DASH = 18
TIE_GAP = 15


def draw_tie_line(
    pen: Pen,
    start: tuple[float, float],
    end: tuple[float, float],
) -> None:
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = (dx * dx + dy * dy) ** 0.5
    if not length:
        return
    ux, uy = dx / length, dy / length
    pen.dashed_line(
        (start[0] + ux * TIE_NODE_GAP, start[1] + uy * TIE_NODE_GAP),
        (end[0] - ux * TIE_NODE_GAP, end[1] - uy * TIE_NODE_GAP),
        fill=TIE_COLOR,
        width=TIE_WIDTH,
        dash=TIE_DASH,
        gap=TIE_GAP,
    )


def tie_pairs(
    catalog: ManeuverCatalog,
) -> list[tuple[ManeuverDefinition, ManeuverDefinition]]:
    """
    The maneuvers that tie, asked of the catalog rather than read off
    the diagram.

    On the current six they are the ranks facing each other -- O1/D1,
    O2/D2, O3/D3 -- which the cycle happens to draw as the three
    diagonals of the hexagon. That is a property of a six-node cycle
    and not a rule, so a seventh maneuver would move the lines without
    moving what they mean; matching on `resolve` is what keeps the
    picture honest either way.
    """
    return [
        (offense, defense)
        for offense in catalog.offense
        for defense in catalog.defense
        if catalog.resolve(offense.name, defense.name) == "tie"
    ]


def fit_node_label(
    pen: Pen, words: list[str], radius: float, max_size: int = 64
) -> tuple[list[tuple[str, ImageFont.ImageFont]], list[float], int]:
    """
    The largest font, no bigger than `max_size`, a maneuver's name fits
    its node circle at -- one word to a line, searched rather than
    picked once, because "Pressure" has the whole circle and "Steal"
    over "Intercept" only has what a chord below the middle allows.

    Checked against the circle rather than a bounding square: a line
    is only as wide as the chord at its own vertical offset from the
    centre, which is what lets "Intercept" claim a size a square would
    have refused.

    Returns the size alongside the fitted lines, which is what lets a
    caller measure one name and cap the rest of the cycle at it -- see
    `render_maneuver_card_back`'s use of "Block Deflect" as the ceiling.
    """
    for size in range(max_size, 13, -1):
        face = font(size, bold=True)
        boxes = [pen.ink_box(word, face) for word in words]
        heights = [box[3] - box[1] for box in boxes]
        total_height = sum(heights) + CYCLE_LINE_GAP * (len(words) - 1)
        if total_height > radius * 2 - CYCLE_LABEL_MARGIN:
            continue
        top = -total_height / 2
        fits = True
        for word, box, height in zip(words, boxes, heights):
            mid = top + height / 2
            span = radius * radius - mid * mid
            chord = 2 * span**0.5 if span > 0 else 0
            if (box[2] - box[0]) > chord - CYCLE_LABEL_MARGIN:
                fits = False
                break
            top += height + CYCLE_LINE_GAP
        if fits:
            return [(word, face) for word in words], heights, size

    face = font(13, bold=True)
    boxes = [pen.ink_box(word, face) for word in words]
    return [(word, face) for word in words], [box[3] - box[1] for box in boxes], 13


def render_maneuver_card_back(catalog: ManeuverCatalog, bleed: bool) -> Image.Image:
    """
    One back for all six, because a coach holding both sets must not
    show which side of the ball they are reading. It carries the defeat
    cycle, which is public information every coach is entitled to see
    at any time.

    The cycle is two relations, not one: a solid arrow to what a
    maneuver beats, and a dashed line to the one it ties with. The ties
    used to be left to the caption -- "same rank ties" -- which is the
    one thing on the card a coach had to work out rather than look up,
    and a tie is the branch that costs a skill test and a token each.
    """
    from d12ball.render import _maneuver_cycle_order

    pen = Pen((CARD_WIDTH, CARD_HEIGHT), BACK_COLOR)
    pen.rect(
        (FRAME, FRAME, CARD_WIDTH - FRAME, CARD_HEIGHT - FRAME),
        radius=CORNER,
        fill=BACK_COLOR,
        outline=BACK_EDGE,
        width=EDGE_WIDTH,
    )
    pen.text(
        (CARD_WIDTH / 2, 104),
        "D12 BALL",
        font(46, bold=True),
        INK,
        anchor="mm",
    )
    pen.text(
        (CARD_WIDTH / 2, 150),
        "BASIC MANEUVERS",
        font(22, bold=True),
        MUTED,
        anchor="mm",
    )

    order = _maneuver_cycle_order(catalog)
    center = (CARD_WIDTH / 2, CYCLE_CENTER_Y)
    from math import cos, radians, sin

    angles = [270 + 360 * index / len(order) for index in range(len(order))]
    points = [
        (
            center[0] + CYCLE_RADIUS_X * cos(radians(angle)),
            center[1] + CYCLE_RADIUS_Y * sin(radians(angle)),
        )
        for angle in angles
    ]

    # The ties first, so the arrows and the nodes sit over them: a
    # dashed line is the quieter of the two relations and reads as the
    # background of the cycle rather than a step in it.
    node_at = {
        (maneuver.name, is_offense): point
        for (maneuver, is_offense), point in zip(order, points)
    }
    for offense, defense in tie_pairs(catalog):
        draw_tie_line(
            pen, node_at[(offense.name, True)], node_at[(defense.name, False)]
        )

    for index, point in enumerate(points):
        nxt = points[(index + 1) % len(points)]
        dx, dy = nxt[0] - point[0], nxt[1] - point[1]
        length = (dx * dx + dy * dy) ** 0.5
        ux, uy = dx / length, dy / length
        start = (point[0] + ux * CYCLE_NODE_RADIUS, point[1] + uy * CYCLE_NODE_RADIUS)
        end = (
            nxt[0] - ux * (CYCLE_NODE_RADIUS + 4),
            nxt[1] - uy * (CYCLE_NODE_RADIUS + 4),
        )
        pen.line([start, end], fill=MUTED, width=6)
        draw_arrowhead(pen, end, (ux, uy), 24, MUTED)

    # Sized independently, "Low Pass" and "High Pass" balloon past
    # every other node -- two short words leave them almost the whole
    # circle to grow into, where "Steal Intercept" and "Block Deflect"
    # are held back by "Intercept" and "Deflect" alone. "Block Deflect"
    # is the widest pairing that still only asks for two lines, so its
    # own best fit is the most any node can carry without the two short
    # names reading oversized next to the rest of the cycle; every node
    # is capped there, even the ones that already fit smaller.
    reference = next(
        maneuver for maneuver, _ in order if maneuver.name == CYCLE_LABEL_REFERENCE
    )
    _, _, cap_size = fit_node_label(
        pen, reference.name.split(" "), CYCLE_NODE_RADIUS
    )

    for (maneuver, is_offense), point in zip(order, points):
        color = OFFENSE_COLOR if is_offense else DEFENSE_COLOR
        pen.circle(point, CYCLE_NODE_RADIUS, fill=color)

        # The label is centred as a block rather than line by line, so a
        # one-word name and a two-word one both sit in the middle of the
        # circle. Written as fixed offsets it was measured against the
        # two-line case and left the whole stack low in the circle.
        words = maneuver.name.split(" ")
        lines, heights, _ = fit_node_label(
            pen, words, CYCLE_NODE_RADIUS, max_size=cap_size
        )
        boxes = [pen.ink_box(text, face) for text, face in lines]
        gaps = [CYCLE_LINE_GAP] * (len(lines) - 1)
        top = point[1] - (sum(heights) + sum(gaps)) / 2
        for index, (text, face) in enumerate(lines):
            middle = top + heights[index] / 2
            pen.text(
                (point[0], middle - (boxes[index][1] + boxes[index][3]) / 2),
                text,
                face,
                INK,
                anchor="mm",
            )
            top += heights[index] + (gaps[index] if index < len(gaps) else 0)

    pen.text(
        (CARD_WIDTH / 2, CARD_HEIGHT - 108),
        "solid: beats what it points to · dashed: ties",
        font(20),
        MUTED,
        anchor="mm",
    )
    return pen.finish(bleed, BACK_COLOR)


# What the bot sends a coach who has just clicked "Choose Your
# Maneuver". Discord scales an inline image down to a few hundred
# pixels whatever it is sent, so the hand is drawn at a third of the
# print card's width -- enough that the effect and the matchup row are
# readable inline, small enough that an ephemeral send is not a
# megabyte of PNG for a click a coach makes several times a turn.
# Anyone who wants to read the small print opens the full image.
HAND_CARD_WIDTH = 520
HAND_GAP = 22
HAND_MARGIN = 22


def render_maneuver_hand(
    catalog: ManeuverCatalog,
    players: PlayerCatalog,
    side: str,
) -> BytesIO:
    """
    One side's three maneuvers, side by side and in rank order, with
    the shared card back beside them -- the hand a coach is choosing
    from, and what beats what.

    It is the same layout as the printed card rather than a second
    design, so a coach who has played at the table recognises what the
    bot is showing them. The bot builds both sides once at startup;
    see `D12Ball.__init__`.

    **The back is the fourth card, and it replaced a button.** The pick
    menu carried a "Maneuver Reference" button that posted the defeat
    cycle as a second ephemeral message: a click, a round trip and an
    upload to see the one thing a coach needs *while* they are choosing.
    The back carries that same cycle, it is public information either
    coach may look at whenever they like, and at the table it is face
    up on the deck in front of them -- so it belongs in the hand rather
    than behind a button.
    """
    maneuvers = catalog.offense if side == "offense" else catalog.defense
    cards = [
        render_maneuver_card(
            catalog, players, maneuver, side == "offense", bleed=False
        )
        for maneuver in sorted(maneuvers, key=lambda item: item.rank)
    ]
    cards.append(render_maneuver_card_back(catalog, bleed=False))

    scale = HAND_CARD_WIDTH / CARD_WIDTH
    height = round(CARD_HEIGHT * scale)
    sized = [
        card.resize((HAND_CARD_WIDTH, height), Image.Resampling.LANCZOS)
        for card in cards
    ]

    canvas = Image.new(
        "RGB",
        (
            HAND_MARGIN * 2
            + HAND_CARD_WIDTH * len(sized)
            + HAND_GAP * (len(sized) - 1),
            HAND_MARGIN * 2 + height,
        ),
        FACE_COLOR,
    )
    for index, card in enumerate(sized):
        canvas.paste(
            card,
            (HAND_MARGIN + index * (HAND_CARD_WIDTH + HAND_GAP), HAND_MARGIN),
        )

    buffer = BytesIO()
    canvas.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


# A cell is a card plus this much white on every side, so cards are
# evenly spaced and there is something to cut through.
SHEET_MARGIN = 24
SHEET_COLUMNS = 4


def print_sheet(
    cards: list[Image.Image],
    columns: int = SHEET_COLUMNS,
) -> Image.Image:
    """
    The cards laid out as an exact grid, for a print run or for the
    splitters that cut a sheet into cards by dividing it evenly.

    **Every cell is the same size and every card is centred in its
    own**, which is the whole point: divide the sheet into `columns`
    across and as many rows as it has, and each piece is one card with
    an even white margin round it. The old sheet put a gutter between
    the cards *and* around the outside, so a quarter of its width was a
    card and a quarter of a gutter -- every cut but the first came out
    off-centre, and the last card was clipped.

    A short last row is padded with blank cells rather than a narrower
    row, for the same reason.
    """
    width = max(card.width for card in cards)
    height = max(card.height for card in cards)
    cell = (width + SHEET_MARGIN * 2, height + SHEET_MARGIN * 2)
    rows = -(-len(cards) // columns)

    sheet = Image.new(
        "RGB", (columns * cell[0], rows * cell[1]), CARD_FACE
    )
    for index, card in enumerate(cards):
        column, row = index % columns, index // columns
        sheet.paste(
            card,
            (
                column * cell[0] + (cell[0] - card.width) // 2,
                row * cell[1] + (cell[1] - card.height) // 2,
            ),
        )
    return sheet
