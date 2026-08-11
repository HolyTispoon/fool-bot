#!/usr/bin/env python3
"""Render the six maneuver cards for the physical game.

Six faces and one shared back, print-ready at 2.5 x 3.5 inches (poker size):

    python3 scripts/render_maneuver_cards.py --out cards/
    python3 scripts/render_maneuver_cards.py --bleed --sheet

Everything on a face is read from the same data the bot plays from --
`maneuvers.json` for the effect, the time cost and who beats whom, and
`players.json` for the role abilities. So a card cannot state a rule the
bot does not, and an import that changes either file changes the cards
by re-running this.

Which roles a card lists is mostly matched, not tabulated: a role is on
the card when its ability sentence names that maneuver, so the Fullback
appears on both High Pass and Block Deflect. Abilities are never cut
down here; see "Every ability is imported twice" in CLAUDE.md. The two
things that match cannot find are listed explicitly below, each with
the reason -- see EXTRA_ROLES and EXTRA_NOTES.
"""
import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from d12ball.components import (  # noqa: E402
    ManeuverCatalog,
    ManeuverDefinition,
    PlayerCatalog,
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.render import load_font, wrap_text  # noqa: E402


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
FRAME = 16
CORNER = 34

# The offense/defense colours the maneuver reference image already
# uses, so a coach reading a card and a coach reading the bot's
# hexagon are looking at the same two colours.
OFFENSE_COLOR = "#E24B4A"
DEFENSE_COLOR = "#97C459"
FACE_COLOR = "#f6f1e6"
PANEL_COLOR = "#e6ded0"
PANEL_EDGE = "#c3b7a3"
INK = "#14202b"
MUTED = "#5d6b78"
BACK_COLOR = "#111820"

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


# Where each maneuver goes on the strip, as (offset in spaces from the
# ball, what lands there, colour, dashed) -- dashed being the variant a
# role ability unlocks rather than the ordinary move. Offsets are in
# spaces forward for the attacking side, so a defensive push is
# negative on every card and the diagrams read against each other.
STRIP_MOVES: dict[str, tuple[tuple[int, str, str, bool], ...]] = {
    "Low Pass": (
        (2, "nearest ahead", "offense", False),
        (-2, "or behind", "offense", False),
    ),
    "Dribble Advance": (
        (1, "handler + ball", "offense", False),
        (2, "playmaker", "offense", True),
    ),
    "High Pass": (
        (2, "received", "offense", False),
        (3, "contested", "offense", False),
        (4, "fullback", "offense", True),
    ),
    "Block Deflect": (
        (-1, "ball back", "defense", False),
        (-2, "fullback", "defense", True),
    ),
    "Steal Intercept": (
        (-1, "carrier + ball", "defense", False),
    ),
    "Pressure": (
        (-1, "handler + ball", "offense", False),
        (1, "challenger", "defense", False),
    ),
}
# What stands on the ball's space to begin with, and what a landing
# space is drawn holding. A blank landing means the ball alone.
STRIP_ACTORS: dict[str, tuple[str, dict[int, str]]] = {
    "Low Pass": ("H", {2: "R", -2: "R"}),
    "Dribble Advance": ("H", {1: "H", 2: "H"}),
    "High Pass": ("H", {}),
    "Block Deflect": ("H", {}),
    "Steal Intercept": ("HC", {-1: "C"}),
    "Pressure": ("HC", {-1: "H", 1: "C"}),
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

    space_width = (right - left) / STRIP_SPACES
    strip_height = 76
    label_room = 56
    strip_top = top + height - label_room - strip_height - 10
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

    def center(index: int) -> tuple[float, float]:
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

    def arc(offset: int, color: str, dashed: bool) -> None:
        x0, y0 = center(here)
        x1, y1 = center(here + offset * forward)
        y0 -= 30
        y1 -= 30
        peak = min(y0, y1) - (24 + 15 * abs(offset))
        steps = 30
        points = []
        for step in range(steps + 1):
            t = step / steps
            x = (1 - t) ** 2 * x0 + 2 * (1 - t) * t * (x0 + x1) / 2 + t**2 * x1
            y = (1 - t) ** 2 * y0 + 2 * (1 - t) * t * peak + t**2 * y1
            points.append((x, y))
        if dashed:
            for step in range(0, steps - 3, 3):
                pen.line(points[step : step + 2], fill=color, width=5)
        else:
            pen.line(points[:-1], fill=color, width=5)
        tail, tip = points[-3], points[-1]
        dx, dy = tip[0] - tail[0], tip[1] - tail[1]
        length = max((dx * dx + dy * dy) ** 0.5, 0.001)
        draw_arrowhead(pen, tip, (dx / length, dy / length), 19, color)

    def caption(offset: int, text: str, color: str, row: int) -> None:
        """
        Hung under the landing space, on the second row when the move
        is a role's variant. Two rows is what keeps High Pass legible:
        its three landings are on consecutive spaces, so three captions
        on one row have less than a space's width each.
        """
        cx, _ = center(here + offset * forward)
        # How much room this caption has is how far the next caption on
        # its row is: High Pass lands on consecutive spaces and gets a
        # space's width each, while a lone caption may run wide.
        neighbours = [
            abs(other - offset)
            for other, _, _, other_dashed in STRIP_MOVES[maneuver.name]
            if other != offset and (1 if other_dashed else 0) == row
        ]
        room = space_width * (min(neighbours) if neighbours else 2.4) - 8
        for size in range(17, 11, -1):
            face = font(size, bold=True)
            width = pen.text_size(text, face)[0]
            if width <= room:
                break
        # A caption on the first or last space would otherwise hang off
        # the panel, so it slides back inside rather than being cut.
        cx = min(max(cx, left + width / 2), right - width / 2)
        pen.text(
            (cx, strip_top + strip_height + 8 + row * 26),
            text,
            face,
            color,
            anchor="ma",
        )

    moves = STRIP_MOVES[maneuver.name]
    standing, landings = STRIP_ACTORS[maneuver.name]

    for offset, _, side, dashed in moves:
        arc(offset, colors[side], dashed)

    for offset, label, side, dashed in moves:
        who = landings.get(offset)
        if who is not None:
            token(
                here + offset * forward,
                colors["offense"] if who in "HR" else colors["defense"],
                who,
                ghost=True,
            )
        else:
            # Nothing lands here but the ball, so the space carries how
            # far it came instead -- the distance is the choice on a
            # High Pass and the ability on a Block Deflect.
            cx, cy = center(here + offset * forward)
            pen.text(
                (cx, cy + 1),
                str(abs(offset)),
                font(30, bold=True),
                PANEL_EDGE,
                anchor="mm",
            )
        caption(offset, label, colors[side], 1 if dashed else 0)

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
        (right, top + 20),
        f"offense attacks {'→' if ATTACK_RIGHT else '←'}",
        font(17),
        MUTED,
        anchor="ra",
    )
    pen.text(
        (left, top + 20),
        "H handler   C challenger",
        font(17),
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


def render_card(
    catalog: ManeuverCatalog,
    players: PlayerCatalog,
    maneuver: ManeuverDefinition,
    is_offense: bool,
    bleed: bool,
) -> Image.Image:
    color = OFFENSE_COLOR if is_offense else DEFENSE_COLOR
    pen = Pen((CARD_WIDTH, CARD_HEIGHT), color)

    pen.rect(
        (FRAME, FRAME, CARD_WIDTH - FRAME, CARD_HEIGHT - FRAME),
        radius=CORNER,
        fill=FACE_COLOR,
    )

    # Header: the rank badge, the name, and the die faces this card
    # stands in for -- printed small, so a table with the selection die
    # and a table with these cards are playing the same game.
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
    pen.circle(badge_center, 46, fill=FACE_COLOR)
    pen.text(badge_center, rank_label, font(38, bold=True), color, anchor="mm")

    die_faces = "–".join(str(value) for value in maneuver.die_values)
    pen.text(
        (CARD_WIDTH - FRAME - 26, header_top + header_height / 2),
        f"die\n{die_faces}",
        font(20, bold=True),
        "#ffffff",
        anchor="mm",
    )

    title_left = FRAME + 140
    title_right = CARD_WIDTH - FRAME - 82
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
    strip_height = 250
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

    return pen.finish(bleed, color)


def render_back(catalog: ManeuverCatalog, bleed: bool) -> Image.Image:
    """
    One back for all six, because a coach holding both sets must not
    show which side of the ball they are reading. It carries the defeat
    cycle, which is public information every coach is entitled to see
    at any time.
    """
    from d12ball.render import _maneuver_cycle_order

    pen = Pen((CARD_WIDTH, CARD_HEIGHT), BACK_COLOR)
    pen.rect(
        (FRAME, FRAME, CARD_WIDTH - FRAME, CARD_HEIGHT - FRAME),
        radius=CORNER,
        fill=BACK_COLOR,
        outline="#2b3b4a",
        width=4,
    )
    pen.text(
        (CARD_WIDTH / 2, 118),
        "D12 BALL",
        font(46, bold=True),
        "#f6f1e6",
        anchor="mm",
    )
    pen.text(
        (CARD_WIDTH / 2, 166),
        "MANEUVERS",
        font(22, bold=True),
        "#7d8e9c",
        anchor="mm",
    )

    order = _maneuver_cycle_order(catalog)
    center = (CARD_WIDTH / 2, 600)
    radius = 218
    from math import cos, radians, sin

    angles = [270 + 360 * index / len(order) for index in range(len(order))]
    points = [
        (
            center[0] + radius * cos(radians(angle)),
            center[1] + radius * sin(radians(angle)),
        )
        for angle in angles
    ]

    for index, point in enumerate(points):
        nxt = points[(index + 1) % len(points)]
        dx, dy = nxt[0] - point[0], nxt[1] - point[1]
        length = (dx * dx + dy * dy) ** 0.5
        ux, uy = dx / length, dy / length
        start = (point[0] + ux * 58, point[1] + uy * 58)
        end = (nxt[0] - ux * 62, nxt[1] - uy * 62)
        pen.line([start, end], fill="#3f5162", width=5)
        draw_arrowhead(pen, end, (ux, uy), 20, "#3f5162")

    for (maneuver, is_offense), point in zip(order, points):
        color = OFFENSE_COLOR if is_offense else DEFENSE_COLOR
        pen.circle(point, 58, fill=color)
        pen.text(
            (point[0], point[1] - 14),
            f"{'O' if is_offense else 'D'}{maneuver.rank}",
            font(26, bold=True),
            "#14202b",
            anchor="mm",
        )
        for line_index, word in enumerate(maneuver.name.split(" ")):
            pen.text(
                (point[0], point[1] + 10 + line_index * 19),
                word,
                font(14, bold=True),
                "#14202b",
                anchor="mm",
            )

    pen.text(
        (CARD_WIDTH / 2, CARD_HEIGHT - 118),
        "each beats what it points to · same rank ties",
        font(20),
        "#7d8e9c",
        anchor="mm",
    )
    return pen.finish(bleed, BACK_COLOR)


def contact_sheet(cards: list[Image.Image]) -> Image.Image:
    gap = 30
    columns = 4
    rows = (len(cards) + columns - 1) // columns
    width = cards[0].width
    height = cards[0].height
    sheet = Image.new(
        "RGB",
        (
            columns * width + gap * (columns + 1),
            rows * height + gap * (rows + 1),
        ),
        "#333c45",
    )
    for index, card in enumerate(cards):
        column, row = index % columns, index // columns
        sheet.paste(
            card,
            (
                gap + column * (width + gap),
                gap + row * (height + gap),
            ),
        )
    return sheet


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render the six maneuver cards and their shared back.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=PROJECT_ROOT / "cards",
        help="Directory to write the PNGs into (default: ./cards)",
    )
    parser.add_argument(
        "--bleed",
        action="store_true",
        help="Add a 1/8in bleed margin for a print shop to trim into.",
    )
    parser.add_argument(
        "--sheet",
        action="store_true",
        help="Also write contact-sheet.png with all seven side by side.",
    )
    args = parser.parse_args()

    catalog = load_maneuver_catalog()
    players = load_player_catalog()
    args.out.mkdir(parents=True, exist_ok=True)

    cards: list[Image.Image] = []
    for maneuvers, is_offense in ((catalog.offense, True), (catalog.defense, False)):
        for maneuver in maneuvers:
            card = render_card(catalog, players, maneuver, is_offense, args.bleed)
            slug = maneuver.name.lower().replace(" ", "-")
            side = "o" if is_offense else "d"
            path = args.out / f"{side}{maneuver.rank}-{slug}.png"
            card.save(path, dpi=(300, 300))
            cards.append(card)
            print(f"wrote {path}")

    back = render_back(catalog, args.bleed)
    back_path = args.out / "back.png"
    back.save(back_path, dpi=(300, 300))
    cards.append(back)
    print(f"wrote {back_path}")

    if args.sheet:
        sheet_path = args.out / "contact-sheet.png"
        contact_sheet(cards).save(sheet_path)
        print(f"wrote {sheet_path}")


if __name__ == "__main__":
    main()
