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
import re
from io import BytesIO
from math import ceil
from typing import NamedTuple, Optional, Sequence

from PIL import Image, ImageDraw, ImageFont

from d12ball.components import (
    MANEUVER_TIER_ADVANCED,
    MANEUVER_TIER_BASIC,
    ManeuverCatalog,
    ManeuverDefinition,
    PlayerCatalog,
)
from d12ball.render import (
    MANEUVER_DEFENSE_COLOR as DEFENSE_COLOR,
    MANEUVER_DEFENSE_COLOR_ADVANCED as DEFENSE_COLOR_ADVANCED,
    MANEUVER_OFFENSE_COLOR as OFFENSE_COLOR,
    MANEUVER_OFFENSE_COLOR_ADVANCED as OFFENSE_COLOR_ADVANCED,
    arrowhead_triangle,
    draw_dashed_line,
    load_font,
    wrap_text,
)


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

# OFFENSE_COLOR/DEFENSE_COLOR are imported above, as
# MANEUVER_OFFENSE_COLOR/MANEUVER_DEFENSE_COLOR -- the maneuver
# reference image's own colours, aliased so a coach reading a card and
# a coach reading the bot's hexagon are looking at the same two
# colours by construction, not by two hex literals happening to agree.
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

# Which board a tier's strip diagram is drawn on lives in
# STRIP_GEOMETRY, below the moves it has to hold. The offense always
# attacks right, so a move's offset is along that one axis and never
# "forward" or "back" from anybody's point of view.
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


def fitted_bold_font(
    pen: Pen,
    text: str,
    max_width: float,
    max_size: int = 54,
    min_size: int = 30,
    step: int = 2,
) -> Optional[ImageFont.ImageFont]:
    """
    The largest bold size in [min_size, max_size] (stepping down by
    `step`) whose rendered `text` fits `max_width` on one line, or None
    when even `min_size` doesn't -- the search `fitted_title` (which
    falls back to a two-line title) and `player_cards.fitted_name`
    (which falls back to a smaller floor size regardless) each build
    their own fallback around.
    """
    for size in range(max_size, min_size - 1, -step):
        face = font(size, bold=True)
        if pen.text_size(text, face)[0] <= max_width:
            return face
    return None


def fitted_title(
    pen: Pen, name: str, max_width: float
) -> tuple[list[str], ImageFont.ImageFont]:
    """
    The largest title that fits the header, on one line if it can and
    two if it cannot. "Steal Intercept" and "Dribble Advance" are the
    long ones and both break cleanly at their space.
    """
    face = fitted_bold_font(pen, name, max_width, max_size=54, min_size=30)
    if face is not None:
        return [name], face
    return name.split(" ", 1), font(40, bold=True)


# A role whose ability does not name the maneuver but belongs on its
# card anyway. The Striker's +3 is for scoring off a set-up, one step
# removed from the maneuver that produced the set-up -- three maneuvers
# can produce one, and the author's ruling is that a High Pass is much
# the most common way it happens, so it goes there and nowhere else.
# The sentence still comes from players.json; only the placement is
# here.
EXTRA_ROLES: dict[str, tuple[str, ...]] = {
    "high_pass": ("striker",),
}

# What a maneuver's own rules add to it, where no role ability names it
# and so nothing in the data can be matched against. Steal's is the one
# modifier that decides the maneuver and the only maneuver whose card
# would otherwise be blank; the wording is the author's. None of it can
# live in maneuvers.json, which the sheet import rewrites whole.
BALL_SPEED_NOTE = (
    "BALL SPEED",
    "The defender adds the ball speed modifier to this skill test.",
)
# **Three abilities that reach an advanced card their sentence does not
# name** (the author, 2026-08-19). Each role's sentence is written
# against its basic counterpart and states a *number*; what carries to
# the advanced card is the rule behind the number, which for the
# Fullback is +1 distance and for the Playmaker is one less token. So
# the sentence cannot be matched or reused, and the card says what the
# ability does *there* instead.
EXTRA_NOTES: dict[str, tuple[tuple[str, str], ...]] = {
    "steal": (BALL_SPEED_NOTE,),
    # Intercept is the advanced Steal and settles the same way, so it
    # carries the same modifier -- the sheet's Interactions column says
    # so for both rows.
    "intercept": (BALL_SPEED_NOTE,),
    "clear": (
        ("FULLBACK", "Ball goes back 4 spaces instead of 3."),
    ),
    "setup_pass": (
        ("FULLBACK", "May also set up at 4 spaces."),
    ),
    "dribble_burst": (
        ("PLAYMAKER", "Pays one exhaustion token fewer for the run."),
    ),
}


def role_abilities(
    catalog: PlayerCatalog,
    maneuver: ManeuverDefinition,
    maneuvers: Optional[ManeuverCatalog] = None,
) -> list[tuple[str, str]]:
    """
    What the abilities band says: the roles whose ability names this
    maneuver, then any role placed here by hand, then the maneuver's
    own modifiers. Matching on the name is what keeps the first group
    in step with an import -- a new ability mentioning a maneuver
    reaches the card without anything here being edited.

    **No role ability names an advanced maneuver, and that is the
    data being honest rather than a gap in the match.** Advanced mode
    has two halves -- the second set of maneuvers and a unique ability
    per player -- and only the first is built; the sheet's `Abilities`
    column for the advanced roster is empty for all thirty-six. So an
    advanced card lists the one thing that *is* settled about how it
    resolves: what it does when a skill test decides it.
    """
    # Matched on **whole words**, not as a substring. It was a
    # substring while every maneuver name was two words: the author
    # renamed the basic D2 card to "Steal" on 2026-08-18, and "steal"
    # is inside "Steals the ball when resolving Pressure" -- so the
    # Defender's ability, which is Pressure's, silently appeared on
    # Steal's card as well.
    needle = re.compile(
        r"\b" + r"\s+".join(
            re.escape(word) for word in maneuver.name.lower().split()
        ) + r"\b"
    )
    extra = EXTRA_ROLES.get(maneuver.key, ())
    rows = [
        (role.value.upper(), profile.ability)
        for role, profile in catalog.role_profiles.items()
        if needle.search(profile.ability.lower()) or role.value in extra
    ]
    rows.extend(EXTRA_NOTES.get(maneuver.key, ()))
    if maneuver.is_advanced and maneuvers is not None:
        rows.append(tie_note(maneuvers, maneuver))
    return rows


def tie_note(
    catalog: ManeuverCatalog, maneuver: ManeuverDefinition
) -> tuple[str, str]:
    """
    The line every advanced card carries: **an advanced effect follows
    the cards, not the dice.**

    A tie on the cards carries no advanced effect either way and
    resolves as the basic card on the same rank instead. A skill test
    the cards did *not* tie -- one an injured player's disadvantage
    forced -- is still an outright result, so it carries the effects
    and the roll only decides which way (the author, 2026-08-19). That
    is the same reading that makes an injured player's automatic loss
    of a tie carry nothing: what matters is the tie on the cards.

    The counterpart is looked up by rank rather than written down,
    because rank is what pairs the two cards -- see
    `ManeuverCatalog.counterpart`.
    """
    counterpart = catalog.counterpart(maneuver)
    return (
        "TIE",
        f"A tie resolves as {counterpart.name}, with no advanced "
        "effect either way. A skill test forced by injury still carries "
        "them.",
    )


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
    pen.polygon(
        arrowhead_triangle(tip, direction, length=size, half_width=size * 0.55),
        fill=fill,
    )


# A dashed arc is a role's variant rather than the ordinary move, and
# that is the only thing the dashes mean -- Low Pass's backward option
# is solid because it is a choice any passer has.
STRIP_MOVES: dict[str, tuple[Move, ...]] = {
    "low_pass": (
        Move(2, "nearest ahead", "offense"),
        Move(-2, "or behind", "offense"),
    ),
    "dribble_advance": (
        Move(1, "handler + ball", "offense"),
        Move(2, "playmaker", "offense", dashed=True),
    ),
    "high_pass": (
        Move(2, "received\nmay set up scoring", "offense"),
        Move(3, "contested", "offense", caption_at=3.5),
        Move(4, "fullback", "offense", dashed=True),
    ),
    "block_deflect": (
        Move(-1, "ball back", "defense"),
        Move(-2, "fullback", "defense", dashed=True),
    ),
    # The interceptor falls back toward their own goal, which is the one
    # the offense was attacking -- so a steal moves the ball the way the
    # offense was going, not against it.
    "steal": (
        Move(1, "carrier + ball", "defense", start=19),
    ),
    # Both end on the same space: the handler is shoved back and the
    # challenger advances onto them, and a Defender's won Pressure
    # steals, which it could not do from anywhere else.
    # Each arc runs token to token, or the two would share an endpoint
    # and one arrowhead would be drawn under the other.
    "pressure": (
        Move(-1, "handler + ball", "offense", start=-19, end=-19),
        Move(-1, "challenger", "defense", start=19, end=19, lift=26, row=1),
    ),
    # -- advanced ------------------------------------------------------
    # "Any teammate" has no distance, so the two arcs are drawn to the
    # ends of the strip: the card says *any*, and the picture says the
    # whole field either way rather than picking a number out of the
    # air.
    "precise_pass": (
        Move(4, "any teammate ahead", "offense", caption_at=3.4),
        Move(-4, "or behind", "offense"),
    ),
    # One arc, to the last space of the goal they attack -- the run is
    # not a distance the coach picks, which is why nothing is captioned
    # with a number.
    "dribble_burst": (
        Move(4, "handler + ball,\n1 token a space", "offense", caption_at=3.2),
    ),
    # 0 is a teammate already sharing the passer's space, so its arc
    # runs shoulder to shoulder rather than to a neighbouring space.
    "setup_pass": (
        Move(0, "same space", "offense", start=-19, end=19, lift=8),
        Move(1, "or 1", "offense", lift=18),
        Move(3, "or 3", "offense"),
        Move(4, "fullback", "offense", dashed=True),
    ),
    "clear": (
        Move(-3, "ball back", "defense"),
        Move(-4, "fullback", "defense", dashed=True),
    ),
    # Intercept is the one card that moves the ball *against* the way
    # the offense was going: the interceptor carries it toward the goal
    # they now attack, which is the opposite of the basic steal's fall
    # back. Verified against `move_player_relative`, not reasoned about.
    "intercept": (
        Move(-1, "interceptor + ball", "defense", start=-19, end=-19),
    ),
    # Three pieces end on one space: the handler shoved back two, the
    # challenger, and the teammate nearest where the play started, who
    # joins from wherever they are -- dashed, because how far they come
    # is not a number on the card.
    "double_team": (
        Move(-2, "handler + ball", "offense", start=-19, end=-19),
        Move(-2, "challenger", "defense", start=19, end=19, lift=26, row=1),
        Move(
            -2,
            "+ nearest teammate",
            "defense",
            dashed=True,
            start=57,
            end=19,
            lift=54,
            row=2,
        ),
    ),
}
# What stands on the ball's space to begin with, and what a landing
# space is drawn holding. A blank landing means the ball alone, and the
# space carries the distance instead.
STRIP_ACTORS: dict[str, tuple[str, dict[int, str]]] = {
    "low_pass": ("H", {2: "R", -2: "R"}),
    "dribble_advance": ("H", {1: "H", 2: "H"}),
    "high_pass": ("H", {}),
    "block_deflect": ("H", {}),
    "steal": ("HC", {1: "C"}),
    "pressure": ("HC", {-1: "HC"}),
    "precise_pass": ("H", {4: "R", -4: "R"}),
    "dribble_burst": ("H", {4: "H"}),
    # 0 lands on the passer's own space, which already carries the
    # handler's token, so only 1 and 3 name a receiver.
    "setup_pass": ("H", {1: "R", 3: "R", 4: "R"}),
    "clear": ("H", {}),
    "intercept": ("HC", {-1: "C"}),
    "double_team": ("HC", {-2: "HCC"}),
}

# How wide the strip is and where the ball stands on it, per tier.
#
# **The basic strip is the standard seven-space board with the ball on
# the third space, which is the only position from which every basic
# maneuver fits**: a High Pass of 4 lands on the last space and a
# Fullback's Block Deflect of 2 on the first. The advanced cards do not
# fit it -- a Fullback's Clear drives the ball back 4 and Dribble Burst
# runs it to the far end -- so they are drawn on the **nine-space
# board**, which is a real board and not a made-up strip, with the ball
# in the middle. That gives 4 either way, which is exactly the range
# the six advanced cards need once the Fullback is allowed near a Clear
# and a Setup Pass: before that ruling the ball sat a space back and a
# Fullback's clearance ran off the end of the panel.
STRIP_GEOMETRY: dict[str, tuple[int, int]] = {
    MANEUVER_TIER_BASIC: (7, 2),
    MANEUVER_TIER_ADVANCED: (9, 4),
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

    moves = STRIP_MOVES[maneuver.key]
    standing, landings = STRIP_ACTORS[maneuver.key]
    strip_spaces, ball_space = STRIP_GEOMETRY[maneuver.tier]

    space_width = (right - left) / strip_spaces
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
    for index in range(strip_spaces):
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
    here = ball_space

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
        """
        The pieces a space is drawn holding, spread evenly across it.
        One is centred; two straddle the middle; Double Team's three --
        the handler, the challenger and the teammate who joined -- pack
        tighter still, which is what the shrinking radius is for.
        """
        if len(who) == 1:
            token(index, colors["offense" if who in "HR" else "defense"], who,
                  ghost=True)
            return
        gap = 38 if len(who) == 2 else 32
        radius = 20 if len(who) == 2 else 16
        first = -gap * (len(who) - 1) / 2
        for position, label in enumerate(who):
            token(
                index,
                colors["offense" if label in "HR" else "defense"],
                label,
                ghost=True,
                offset=first + gap * position,
                radius=radius,
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


def matchup_rank_groups(
    catalog: ManeuverCatalog,
    maneuver: ManeuverDefinition,
    is_offense: bool,
) -> tuple[
    tuple[int, tuple[ManeuverDefinition, ManeuverDefinition]],
    tuple[int, tuple[ManeuverDefinition, ManeuverDefinition]],
    tuple[int, tuple[ManeuverDefinition, ManeuverDefinition]],
]:
    """
    The three opposing ranks this maneuver beats, ties and loses to,
    each as `(rank, (basic, advanced))` -- **both tiers of that rank**,
    because rank alone decides who beats whom (the author,
    2026-08-18) and a card naming only its own tier's opponent reads
    as though the twelve maneuvers were two separate cycles rather
    than one, which is exactly backwards: a tie between two advanced
    cards resolves as their basic counterparts, so the basic pair is
    never not in play.

    Read off `maneuver`'s own rank and `defeats_rank` -- identical
    between a rank's basic and advanced card, so it makes no
    difference which tier `maneuver` itself is.
    """
    side = "offense" if is_offense else "defense"
    opposing_side = "defense" if is_offense else "offense"
    opposing_basic = catalog.for_tier(opposing_side, MANEUVER_TIER_BASIC)

    beats_rank = maneuver.defeats_rank
    defeated_by_rank = next(
        m.rank for m in opposing_basic if m.defeats_rank == maneuver.rank
    )
    tie_rank = next(
        m.rank
        for m in opposing_basic
        if m.rank != beats_rank and m.defeats_rank != maneuver.rank
    )

    def pair(rank: int) -> tuple[ManeuverDefinition, ManeuverDefinition]:
        basic = next(m for m in opposing_basic if m.rank == rank)
        return basic, catalog.counterpart(basic)

    return (
        (beats_rank, pair(beats_rank)),
        (tie_rank, pair(tie_rank)),
        (defeated_by_rank, pair(defeated_by_rank)),
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
    Who this beats, ties and loses to -- named by **rank**, with both
    the basic and advanced card on it, since rank rather than the card
    itself is what a matchup is decided by. All three opponents are on
    the other side of the ball, so the column headers carry the
    "beats/ties/loses to" meaning and the rank badge is coloured the
    opposing side's colour rather than this card's own.

    It used to name only this card's own tier's opponent, which reads
    naturally for a basic card but makes an advanced card look like it
    belongs to a cycle of its own -- see `matchup_rank_groups`.
    """
    opposing_letter = "D" if is_offense else "O"
    groups = matchup_rank_groups(catalog, maneuver, is_offense)
    column_width = (CARD_WIDTH - MARGIN * 2) / 3
    rank_color = DEFENSE_COLOR if is_offense else OFFENSE_COLOR

    pen.line(
        [(MARGIN + 10, top), (CARD_WIDTH - MARGIN - 10, top)],
        fill=PANEL_EDGE,
        width=2,
    )

    labels = ("BEATS", "TIES", "LOSES TO")
    for index, (label, (rank, (basic, advanced))) in enumerate(
        zip(labels, groups)
    ):
        cx = MARGIN + column_width * (index + 0.5)
        max_width = column_width - 14
        pen.text((cx, top + 22), label, font(16, bold=True), MUTED, anchor="mm")
        pen.text(
            (cx, top + 47),
            f"{opposing_letter}{rank}",
            font(21, bold=True),
            rank_color,
            anchor="mm",
        )
        name_y = top + 74
        name_font = font(19, bold=True)
        for name, color in (
            (basic.name, INK),
            (advanced.name, DEFENSE_COLOR_ADVANCED if is_offense else OFFENSE_COLOR_ADVANCED),
        ):
            for line in pen.wrapped(name, name_font, max_width):
                pen.text((cx, name_y), line, name_font, color, anchor="mm")
                name_y += line_height(pen, name_font)
        if index:
            pen.line(
                [
                    (MARGIN + column_width * index, top + 12),
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
    label_font = font(21, bold=True)
    body = font(21)
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
    # A distinct shade for an advanced card, not a tint of the basic
    # one -- the two sit side by side in a coach's hand and back to
    # back in the print run, so they have to read as two cards at a
    # glance rather than as the same colour under different light. The
    # "ADVANCED MANEUVER" corner label is the only other thing on the
    # face that says so; the back cannot, since one back serves both.
    if maneuver.is_advanced:
        color = OFFENSE_COLOR_ADVANCED if is_offense else DEFENSE_COLOR_ADVANCED
    else:
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
    # selection die had to coexist; naming the mode is what still means
    # something now that the second set of maneuvers exists -- and this
    # is the one thing on the *face* that tells the two sets apart,
    # since the back cannot (see `render_maneuver_card_back`).
    pen.text(
        (CARD_WIDTH - FRAME - 62, header_top + header_height / 2),
        f"{maneuver.tier.upper()}\nMANEUVER",
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
    abilities = role_abilities(players, maneuver, catalog)
    _, ability_height = laid_out_abilities(pen, abilities)

    abilities_top = CARD_HEIGHT - FRAME - 18 - ability_height
    # Taller than a single-tier row needs, now that each column carries
    # a rank badge and both tiers' names rather than one name -- see
    # matchup_rank_groups.
    matchup_height = 188
    matchup_top = abilities_top - matchup_height

    draw_matchups(
        pen, catalog, maneuver, is_offense, matchup_top, matchup_height
    )
    draw_abilities(pen, abilities, abilities_top)

    # The effect, centred in what is left, with the time cost pinned
    # under it -- the clock is part of what the maneuver costs, so it
    # belongs to the effect rather than to the diagram, where it used
    # to sit and collide with the board strip.
    #
    # **The size is searched, not set.** The effects run from Block
    # Deflect's twenty words to Double Team's seventy, and the band
    # they share is whatever the strip, the matchups and the abilities
    # leave behind -- so a fixed size fits the short cards and runs the
    # long ones straight over the matchup row. Which it did: Double
    # Team's paragraph overran three bands at once, silently, because
    # nothing here measured what it was given. The largest size that
    # fits is what is drawn, and 17 is the floor rather than a fit,
    # since a card nobody can read is a different failure from one that
    # overflows.
    time_font = font(19, bold=True)
    time_text = f"TIME · {maneuver.time}"
    time_width = pen.text_size(time_text, time_font)[0] + 34
    room = matchup_top - (strip_top + strip_height) - 16

    for size in range(29, 16, -1):
        effect_font = font(size)
        lines = pen.wrapped(
            maneuver.effect, effect_font, CARD_WIDTH - MARGIN * 2 - 20
        )
        step = line_height(pen, effect_font)
        block_height = step * len(lines) + 26 + 38
        if block_height <= room:
            break

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
# deck between them, so it is drawn as wide as the card will carry.
# The vertical radius is the shorter of the two because the heading and
# the caption bound it there and the width is what was asked for -- a
# tenth of an ellipse, which reads as a hexagon.
#
# **A node carries both cards on its rank, which is what keeps this
# one back for all twelve.** A coach in advanced mode holds six -- the
# three basic cards and the three advanced ones -- and must not show
# which they are reading, so a second back is not available as a way
# out. What is available is that the two tiers are the same cycle:
# rank alone decides (the author, 2026-08-18), so an advanced card
# sits exactly where its basic counterpart does and the node is one
# position with two names on it rather than two positions.
#
# That is what the node radius grew for, and the ring shrank to pay
# for it. The horizontal radius is still the wider of the two -- the
# heading and the caption bound the vertical one -- so the ring still
# reads as a hexagon rather than a circle.
CYCLE_NODE_RADIUS = 98
CYCLE_RADIUS_X = 262
CYCLE_RADIUS_Y = 250
CYCLE_CENTER_Y = 560

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
# How much of the chord a line has to leave alone. It was 8 while a
# node carried one name on one or two lines near the middle of the
# circle, where the chord is nearly the diameter and 8 is plenty. A
# node carrying both tiers is four lines, and the outer two sit where
# the circle is curving away hardest -- at 8 the longest of them
# cleared the chord by under two pixels a side, which is arithmetically
# inside the circle and reads as bursting out of it.
CYCLE_LABEL_MARGIN = 24

# The advanced half of a node: how far under the basic name it sits,
# and the hairline that separates the two. Without the rule the four
# lines read as one four-word name.
CYCLE_TIER_GAP = 13
CYCLE_TIER_RULE_WIDTH = 3

# The rank badge outside each node -- O1, D2, and so on -- in the same
# green/red as the node itself. Placed past the node's own edge rather
# than inside it, since the circle is already carrying two names.
CYCLE_RANK_LABEL_GAP = 34
CYCLE_RANK_FONT_SIZE = 30

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

    Asked of the basic six alone, because the hexagon has six nodes
    and each node is a rank: an advanced card ties exactly what its
    basic counterpart ties, so walking all twelve would return the same
    three lines four times over.

    On the current six they are the ranks facing each other -- O1/D1,
    O2/D2, O3/D3 -- which the cycle happens to draw as the three
    diagonals of the hexagon. That is a property of a six-node cycle
    and not a rule, so a seventh maneuver would move the lines without
    moving what they mean; matching on `resolve` is what keeps the
    picture honest either way.
    """
    return [
        (offense, defense)
        for offense in catalog.for_tier("offense", MANEUVER_TIER_BASIC)
        for defense in catalog.for_tier("defense", MANEUVER_TIER_BASIC)
        if catalog.resolve(offense.key, defense.key) == "tie"
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
    return fit_node_block(pen, [words], radius, max_size)


def fit_node_block(
    pen: Pen,
    stacks: list[list[str]],
    radius: float,
    max_size: int = 64,
) -> tuple[list[tuple[str, ImageFont.ImageFont]], list[float], int]:
    """
    The same fit over **several** stacks of words, kept apart by
    `CYCLE_TIER_GAP` -- a node carrying a rank's basic name over its
    advanced one is two stacks, and both are set at one size so
    neither reads as the more important of the two.

    The chord test is what makes this worth doing rather than measuring
    against a square: four lines in a circle put the outer two on very
    short chords, and a square would refuse a size those two actually
    clear.
    """
    words = [word for stack in stacks for word in stack]
    breaks = set()
    seen = 0
    for stack in stacks[:-1]:
        seen += len(stack)
        breaks.add(seen - 1)

    for size in range(max_size, 13, -1):
        face = font(size, bold=True)
        boxes = [pen.ink_box(word, face) for word in words]
        heights = [box[3] - box[1] for box in boxes]
        gaps = [
            CYCLE_TIER_GAP if index in breaks else CYCLE_LINE_GAP
            for index in range(len(words) - 1)
        ]
        total_height = sum(heights) + sum(gaps)
        if total_height > radius * 2 - CYCLE_LABEL_MARGIN:
            continue
        top = -total_height / 2
        fits = True
        for index, (word, box, height) in enumerate(zip(words, boxes, heights)):
            mid = top + height / 2
            span = radius * radius - mid * mid
            chord = 2 * span**0.5 if span > 0 else 0
            if (box[2] - box[0]) > chord - CYCLE_LABEL_MARGIN:
                fits = False
                break
            top += height + (gaps[index] if index < len(gaps) else 0)
        if fits:
            return [(word, face) for word in words], heights, size

    face = font(13, bold=True)
    boxes = [pen.ink_box(word, face) for word in words]
    return (
        [(word, face) for word in words],
        [box[3] - box[1] for box in boxes],
        13,
    )


def render_maneuver_card_back(catalog: ManeuverCatalog, bleed: bool) -> Image.Image:
    """
    One back for all **twelve**, because a coach holding both sets must
    not show which side of the ball -- or which tier -- they are
    reading. In advanced mode the offense holds six: the three basic
    cards and the three advanced ones. It carries the defeat cycle,
    which is public information every coach is entitled to see at any
    time.

    **The cycle is six nodes however many cards there are**, because
    rank alone decides who beats whom (the author, 2026-08-18). Each
    node is a rank and carries the two cards on it -- the basic name
    over its advanced counterpart -- so the picture a coach reads a
    matchup off is one hexagon rather than one per tier.

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
        (CARD_WIDTH / 2, 96),
        "D12 BALL",
        font(44, bold=True),
        INK,
        anchor="mm",
    )
    pen.text(
        (CARD_WIDTH / 2, 138),
        "MANEUVERS",
        font(21, bold=True),
        MUTED,
        anchor="mm",
    )

    # The basic tier gives the six positions; the advanced card on each
    # rank is looked up rather than walked, because it is the same
    # cycle and walking it twice would only prove that again.
    order = _maneuver_cycle_order(catalog, MANEUVER_TIER_BASIC)
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
        (maneuver.key, is_offense): point
        for (maneuver, is_offense), point in zip(order, points)
    }
    for offense, defense in tie_pairs(catalog):
        draw_tie_line(
            pen, node_at[(offense.key, True)], node_at[(defense.key, False)]
        )

    for index, point in enumerate(points):
        nxt = points[(index + 1) % len(points)]
        dx, dy = nxt[0] - point[0], nxt[1] - point[1]
        length = (dx * dx + dy * dy) ** 0.5
        ux, uy = dx / length, dy / length
        start = (point[0] + ux * CYCLE_NODE_RADIUS, point[1] + uy * CYCLE_NODE_RADIUS)
        tip = (
            nxt[0] - ux * (CYCLE_NODE_RADIUS + 4),
            nxt[1] - uy * (CYCLE_NODE_RADIUS + 4),
        )
        # The line stops where the arrowhead's own base is, not at its
        # tip -- a stroked line's end cap is flat, so a line run all the
        # way to the tip poked its own width out past the triangle's
        # point, which is exactly zero wide there. Stopping at the base
        # leaves the line's cap inside the triangle's much wider base
        # instead, where the fill already covers it.
        arrow_size = 24
        line_end = (tip[0] - ux * arrow_size, tip[1] - uy * arrow_size)
        pen.line([start, line_end], fill=MUTED, width=6)
        draw_arrowhead(pen, tip, (ux, uy), arrow_size, MUTED)

    # **One size for all six nodes, and it is the tightest of them.**
    # Sized independently they read as six different alphabets: "Low
    # Pass" over "Precise Pass" has short words and grows to fill the
    # circle, where "Pressure" over "Double Team" is held back by
    # "Pressure" alone -- a spread of a third at the same radius.
    #
    # This used to cap at one named pairing's fit instead, because with
    # one name to a node the tightest fit was a single long word and
    # capping there shrank every other node for nothing. With both
    # tiers on a node that is no longer true: all six are four lines of
    # much the same length, so the tightest is a real constraint rather
    # than one outlier, and matching it costs the roomiest node three
    # points to make the cycle read as one picture.
    stacks = [
        [
            maneuver.name.split(" "),
            catalog.counterpart(maneuver).name.split(" "),
        ]
        for maneuver, _ in order
    ]
    cap_size = min(
        fit_node_block(pen, stack, CYCLE_NODE_RADIUS)[2] for stack in stacks
    )

    for (maneuver, is_offense), point in zip(order, points):
        color = OFFENSE_COLOR if is_offense else DEFENSE_COLOR
        pen.circle(point, CYCLE_NODE_RADIUS, fill=color)

        # The rank, outside the circle rather than inside it -- a node
        # already carries two names, and O1/D2 is what says the two
        # cards on it resolve by rank rather than as six basic and six
        # advanced maneuvers with no relation to each other. Placed
        # along the spoke from the ellipse's own centre through the
        # node, so it sits wherever has room on that node's own side of
        # the ring rather than colliding with a neighbour.
        spoke_x, spoke_y = point[0] - center[0], point[1] - center[1]
        spoke_length = (spoke_x * spoke_x + spoke_y * spoke_y) ** 0.5
        ux, uy = spoke_x / spoke_length, spoke_y / spoke_length
        rank_label = f"{'O' if is_offense else 'D'}{maneuver.rank}"
        pen.text(
            (
                point[0] + ux * (CYCLE_NODE_RADIUS + CYCLE_RANK_LABEL_GAP),
                point[1] + uy * (CYCLE_NODE_RADIUS + CYCLE_RANK_LABEL_GAP),
            ),
            rank_label,
            font(CYCLE_RANK_FONT_SIZE, bold=True),
            color,
            anchor="mm",
        )

        # The label is centred as a block rather than line by line, so a
        # one-word name and a two-word one both sit in the middle of the
        # circle. Written as fixed offsets it was measured against the
        # two-line case and left the whole stack low in the circle.
        basic_words = maneuver.name.split(" ")
        advanced = catalog.counterpart(maneuver)
        advanced_words = advanced.name.split(" ")
        lines, heights, _ = fit_node_block(
            pen,
            [basic_words, advanced_words],
            CYCLE_NODE_RADIUS,
            max_size=cap_size,
        )
        boxes = [pen.ink_box(text, face) for text, face in lines]
        split = len(basic_words)
        gaps = [
            CYCLE_TIER_GAP if index == split - 1 else CYCLE_LINE_GAP
            for index in range(len(lines) - 1)
        ]
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
            top += heights[index]
            if index < len(gaps):
                # The hairline between the two tiers, drawn in the gap
                # it is the reason for -- without it the four lines read
                # as one four-word name.
                if index == split - 1:
                    rule_y = top + gaps[index] / 2
                    rule_half = CYCLE_NODE_RADIUS * 0.52
                    pen.line(
                        [
                            (point[0] - rule_half, rule_y),
                            (point[0] + rule_half, rule_y),
                        ],
                        fill=CARD_FACE,
                        width=CYCLE_TIER_RULE_WIDTH,
                    )
                top += gaps[index]

    # Pushed lower than the two captions used to sit, to clear the D1
    # rank badge below the bottom node -- the one node whose spoke runs
    # straight down into where the caption block used to start.
    pen.text(
        (CARD_WIDTH / 2, CARD_HEIGHT - 76),
        "each node is one rank: basic maneuvers above advanced",
        font(19),
        MUTED,
        anchor="mm",
    )
    pen.text(
        (CARD_WIDTH / 2, CARD_HEIGHT - 48),
        "solid: beats what it points to · dashed: ties",
        font(19),
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
# Four across is the basic hand -- three cards and the back -- and it
# is also the widest row this draws. An advanced hand is seven, which
# on one row arrives in Discord at about 75px a card against 131px
# today; two rows of four and three keep every card the size a coach
# already reads.
HAND_MAX_COLUMNS = 4


def render_maneuver_hand(
    catalog: ManeuverCatalog,
    players: PlayerCatalog,
    side: str,
    tiers: Sequence[str] = (MANEUVER_TIER_BASIC,),
) -> BytesIO:
    """
    One side's maneuvers, in rank order, with the shared card back
    beside them -- the hand a coach is choosing from, and what beats
    what.

    It is the same layout as the printed card rather than a second
    design, so a coach who has played at the table recognises what the
    bot is showing them. The bot builds every hand once at startup; see
    `D12Ball.__init__`.

    **The back is the last card, and it replaced a button.** The pick
    menu carried a "Maneuver Reference" button that posted the defeat
    cycle as a second ephemeral message: a click, a round trip and an
    upload to see the one thing a coach needs *while* they are choosing.
    The back carries that same cycle, it is public information either
    coach may look at whenever they like, and at the table it is face
    up on the deck in front of them -- so it belongs in the hand rather
    than behind a button.

    **`tiers` is what a coach may actually play, not a display
    option.** A basic game is the three basic cards; an advanced game
    is all six, and an *unchallenged* maneuver in an advanced game is
    the three basic ones again -- an advanced maneuver can only be
    played when a maneuver is challenged (the author). So the caller
    passes the hand, and this draws it.

    **Seven cards do not fit one row.** Discord scales an inline image
    to the message's width, so a row of seven arrives about 75px a card
    against 131px for a row of four -- small print at the size the
    abilities band already needs a full-image link for. Anything past
    four cards is laid out in two rows instead, which keeps every card
    the width it has always been.
    """
    maneuvers = [
        maneuver
        for maneuver in catalog.side(side)
        if maneuver.tier in tiers
    ]
    cards = [
        render_maneuver_card(
            catalog, players, maneuver, side == "offense", bleed=False
        )
        for maneuver in sorted(
            maneuvers,
            key=lambda item: (item.rank, item.tier != MANEUVER_TIER_BASIC),
        )
    ]
    cards.append(render_maneuver_card_back(catalog, bleed=False))

    scale = HAND_CARD_WIDTH / CARD_WIDTH
    height = round(CARD_HEIGHT * scale)
    sized = [
        card.resize((HAND_CARD_WIDTH, height), Image.Resampling.LANCZOS)
        for card in cards
    ]

    columns = min(len(sized), HAND_MAX_COLUMNS)
    rows = ceil(len(sized) / columns)
    canvas = Image.new(
        "RGB",
        (
            HAND_MARGIN * 2
            + HAND_CARD_WIDTH * columns
            + HAND_GAP * (columns - 1),
            HAND_MARGIN * 2 + height * rows + HAND_GAP * (rows - 1),
        ),
        FACE_COLOR,
    )
    for index, card in enumerate(sized):
        column, row = index % columns, index // columns
        canvas.paste(
            card,
            (
                HAND_MARGIN + column * (HAND_CARD_WIDTH + HAND_GAP),
                HAND_MARGIN + row * (height + HAND_GAP),
            ),
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
