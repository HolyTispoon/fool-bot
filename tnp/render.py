"""
The New Project's pictures, drawn by code (docs/tnp-bot.md, decision 6)
-- **the one TNP module that imports Pillow** (`tests/test_tnp_purity.py`):

- `render_map`: map 3.3 from `map.json`'s traced outlines, each area
  tinted by who holds it, its number, the resource tokens left, the
  Stranded tokens, the two bases, and the piles March has revealed.
- `render_board`: a seat's player board from `human_board.json` and
  `humans.json`, laid out as the canvas the author has seen (the Human
  base board): the four facilities, their caps, what is built and what
  is queued, the upgrades, every unit's cost, ratings as d12 numbers,
  initiative, traits and supply left, the d12's numbers, the limits
  and the conversion rates.
- `render_battle`: a battle (`tnp.battle.BattleState`) as its line --
  the attacker above, the defender below, each force's unit, count and
  damage, the flanking forces on the outside, the round track and, for
  a base, the base cards.

Each draws what it is handed and decides nothing: a number, a rating's
d12 value or a limit is read from the catalog or the state, never
worked out here. The map and the board are drawn from a brief
(`tnp.briefs`) already filtered for whoever sees it, so nothing hidden
can reach a picture by accident; the battle is public.

**Sizes are for Discord**, which shows a picture a third of its width
or less until it is opened: no word is drawn smaller than `SMALLEST`
pixels, and every fill is white or a colour that says something --
never an off-white (the author, 2026-11-06).

Every call returns PNG bytes. The cog calls them through
`asyncio.to_thread`, since Pillow is CPU-bound and blocks the heartbeat.
Nothing here is tested for how it looks: render it with
`scripts/render_tnp_sample.py` and look (docs/design/board-image.md,
"Look at the image").
"""

from __future__ import annotations

import io
from functools import lru_cache
from pathlib import Path
from typing import Optional, Sequence

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from tnp import battle as lines
from tnp.battle import BASE_LEFT, BASE_RIGHT, ROUNDS, SEATS, BattleState
from tnp.briefs import DEFENSE, POOL, RESOURCES, BoardBrief, MapBrief, Pile
from tnp.catalog import Area, Catalog, Rating, Unit, UnitType
from tnp.formatting import TRAIT_NAMES

#: D12 Ball's bundled fonts, read by absolute path and never copied
#: (CLAUDE.md, "Rendering").
FONT_DIR = Path(__file__).resolve().parent.parent / "d12ball" / "fonts"
BOLD = FONT_DIR / "RobotoSlab-Bold.ttf"
REGULAR = FONT_DIR / "RobotoSlab-Regular.ttf"

#: The smallest word any picture draws, in its own pixels.
SMALLEST = 16

# -- The palette -------------------------------------------------------------

INK = (42, 44, 48)
SOFT_INK = (69, 71, 77)
MUTED = (91, 93, 99)
WHITE = (255, 255, 255)
#: A chip's or a box's outline, on white.
RULE = (196, 199, 205)
#: A round already played, and a unit's veil.
SPENT = (214, 216, 221)
HIT = (176, 42, 30)
DAMAGE_FILL = (246, 205, 195)

#: Each seat's colour, its tint for a territory it holds, its base's
#: fill and the ink of a word in it -- the canvas's blue and green.
SEAT_COLOURS = {
    "blue": {"strong": (47, 95, 158), "held": (205, 220, 242), "base": (176, 198, 232), "ink": (31, 66, 112)},
    "green": {"strong": (47, 122, 69), "held": (202, 230, 207), "base": (168, 212, 178), "ink": (31, 90, 49)},
}

RESOURCE_COLOURS = {
    "blue_minerals": ((30, 127, 200), (21, 90, 142)),
    "orange_minerals": ((217, 122, 6), (143, 79, 0)),
    "gems": ((142, 68, 192), (95, 40, 133)),
}

MATERIAL = (154, 161, 169)
GOLD = (224, 177, 58)

#: A unit type's border and ink, as board v4 colours its cards.
TYPE_COLOURS = {
    UnitType.INFANTRY: ((47, 138, 74), (36, 107, 57)),
    UnitType.ARMORED: ((184, 64, 47), (147, 48, 31)),
    UnitType.AIR: ((47, 116, 184), (34, 89, 143)),
}
TYPE_WORDS = {UnitType.INFANTRY: "Infantry", UnitType.ARMORED: "Armored", UnitType.AIR: "Air"}
TYPE_SHORT = {UnitType.INFANTRY: "Inf", UnitType.ARMORED: "Arm", UnitType.AIR: "Air"}

#: A rating's cell: green for Strong, amber for Fair, red for Weak and
#: grey for Poor, each strong enough to read as a colour.
RATING_FILLS = {
    Rating.STRONG: (196, 228, 196),
    Rating.FAIR: (250, 225, 160),
    Rating.WEAK: (246, 200, 190),
    Rating.POOR: (212, 214, 220),
}

# -- Shapes, in a 20-unit box (the canvas's icons) ----------------------------

CRYSTAL = ((10, 1.5), (15.5, 7), (13, 18.5), (7, 18.5), (4.5, 7))
GEM = ((6.5, 1.5), (13.5, 1.5), (18.5, 6.5), (18.5, 13.5), (13.5, 18.5), (6.5, 18.5), (1.5, 13.5), (1.5, 6.5))
HEXAGON = ((10, 1.5), (17.5, 5.75), (17.5, 14.25), (10, 18.5), (2.5, 14.25), (2.5, 5.75))
#: The control token's shield, in a 24 x 28 box.
SHIELD = ((12, 1), (22.5, 4.5), (22.5, 13), (20.5, 19), (16.5, 23.5), (12, 27), (7.5, 23.5), (3.5, 19), (1.5, 13), (1.5, 4.5))


@lru_cache(maxsize=None)
def font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(BOLD if bold else REGULAR), size)


def _png(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue()


def _seat_word(seat: Optional[str]) -> str:
    return (seat or "").title()


def _shape(draw: ImageDraw.ImageDraw, points, at: tuple[float, float], size: float,
           fill, box: float = 20, outline=None, width: int = 0) -> None:
    x, y = at
    scale = size / box
    draw.polygon([(x + px * scale, y + py * scale) for px, py in points],
                 fill=fill, outline=outline, width=width)


def _icon(draw: ImageDraw.ImageDraw, kind: str, at: tuple[float, float], size: float) -> None:
    """A resource's or a currency's mark, its top left at `at`."""
    if kind in ("blue_minerals", "orange_minerals"):
        _shape(draw, CRYSTAL, at, size, RESOURCE_COLOURS[kind][0])
    elif kind == "gems":
        _shape(draw, GEM, at, size, RESOURCE_COLOURS[kind][0])
    elif kind == "materials":
        _shape(draw, HEXAGON, at, size, MATERIAL)
    elif kind == "gold":
        x, y = at
        draw.ellipse((x + size * 0.075, y + size * 0.075, x + size * 0.925, y + size * 0.925), fill=GOLD)


def _shield(draw: ImageDraw.ImageDraw, seat: str, at: tuple[float, float], height: float) -> None:
    colours = SEAT_COLOURS[seat]
    width = height * 24 / 28
    _shape(draw, SHIELD, at, width, colours["strong"], box=24, outline=WHITE, width=max(1, round(height / 18)))
    inner = ((12, 4.5), (12, 24), (7.4, 21.6), (5, 13), (5, 7))
    _shape(draw, inner, at, width, tuple(min(255, c + 70) for c in colours["strong"]), box=24)


def _wrap(text: str, face: ImageFont.FreeTypeFont, width: float) -> list[str]:
    words, rows, row = text.split(), [], ""
    for word in words:
        trial = f"{row} {word}".strip()
        if row and face.getlength(trial) > width:
            rows.append(row)
            row = word
        else:
            row = trial
    if row:
        rows.append(row)
    return rows or [""]


def _fit(text: str, face: ImageFont.FreeTypeFont, width: float) -> str:
    """`text`, cut with an ellipsis to fit `width`."""
    if face.getlength(text) <= width:
        return text
    while text and face.getlength(text + "…") > width:
        text = text[:-1]
    return text.rstrip() + "…"


def _pill(draw: ImageDraw.ImageDraw, x: float, y: float, text: str, face, *, fill, ink,
          height: float, outline=None, icon: Optional[str] = None, pad: Optional[float] = None,
          border: int = 2) -> float:
    """A rounded label, its left edge at `x` and top at `y`; its width."""
    pad = height * 0.4 if pad is None else pad
    icon_size = height * 0.66 if icon else 0
    gap = height * 0.18 if icon else 0
    width = pad * 2 + icon_size + gap + face.getlength(text)
    draw.rounded_rectangle((x, y, x + width, y + height), radius=height / 2, fill=fill,
                           outline=outline, width=border if outline else 0)
    cursor = x + pad
    if icon:
        _icon(draw, icon, (cursor, y + (height - icon_size) / 2), icon_size)
        cursor += icon_size + gap
    draw.text((cursor, y + height / 2), text, font=face, fill=ink, anchor="lm")
    return width


def _pill_width(text: str, face, height: float, icon: bool = False, pad: Optional[float] = None) -> float:
    pad = height * 0.4 if pad is None else pad
    return pad * 2 + (height * 0.84 if icon else 0) + face.getlength(text)


def _chip(draw, x, y, text, face, height, *, icon=None, pad=None) -> float:
    """A plain chip: white, outlined, so nothing on a picture is an
    off-white fill."""
    return _pill(draw, x, y, text, face, fill=WHITE, ink=INK, height=height, outline=RULE,
                 icon=icon, pad=pad)


# ============================================================================
# The map
# ============================================================================

#: The map is drawn this many output pixels to one of map3.3-1.png's.
MAP_SCALE = 0.72
#: Drawn this many times larger, then reduced, so the traced outlines'
#: edges are smooth.
SUPERSAMPLE = 2
MAP_MARGIN = 40
MAP_HEADER = 116
MAP_LEGEND = 76
PILE_CARD_H = 112
PILE_PITCH = 128
PILE_HEADING = 56


@lru_cache(maxsize=1)
def _map_bounds(areas: tuple[Area, ...]) -> tuple[int, int, int, int]:
    xs = [x for area in areas for x, _ in area.outline]
    ys = [y for area in areas for _, y in area.outline]
    return min(xs), min(ys), max(xs), max(ys)


def _ordered_areas(catalog: Catalog) -> tuple[Area, ...]:
    return tuple(catalog.areas[slug] for slug in sorted(catalog.areas))


@lru_cache(maxsize=None)
def _anchor(outline: tuple[tuple[int, int], ...]) -> tuple[float, float]:
    """
    Where an area's number goes, in map3.3-1.png's pixels: the middle
    of the widest part of the area, found by eroding its filled shape a
    pixel at a time (at a quarter of the size) and taking the centre of
    what survives longest -- the "pole of inaccessibility", so a number
    sits clear of every border whatever the outline's shape.
    """
    quarter = 4
    xs = [x for x, _ in outline]
    ys = [y for _, y in outline]
    left, top = min(xs), min(ys)
    width = (max(xs) - left) // quarter + 3
    height = (max(ys) - top) // quarter + 3
    mask = Image.new("L", (width, height), 0)
    ImageDraw.Draw(mask).polygon(
        [((x - left) / quarter + 1, (y - top) / quarter + 1) for x, y in outline], fill=255,
    )
    alive = np.array(mask) > 0
    depth = np.zeros(alive.shape, dtype=np.int32)
    while alive.any():
        depth += alive
        shrunk = np.zeros_like(alive)
        shrunk[1:-1, 1:-1] = (
            alive[1:-1, 1:-1] & alive[:-2, 1:-1] & alive[2:, 1:-1] & alive[1:-1, :-2] & alive[1:-1, 2:]
        )
        alive = shrunk
    deepest = depth.max()
    rows, cols = np.nonzero(depth >= max(1, deepest - 1))
    middle_row, middle_col = rows.mean(), cols.mean()
    nearest = int(np.argmin((rows - middle_row) ** 2 + (cols - middle_col) ** 2))
    return (
        left + (cols[nearest] - 1) * quarter,
        top + (rows[nearest] - 1) * quarter,
    )


def _pile_words(catalog: Catalog, pile: Pile) -> str:
    where = catalog.areas[pile.area]
    place = f"Territory {where.number}" if where.number is not None else where.name
    if pile.spot == DEFENSE:
        return f"{_seat_word(pile.seat)} defends {place}"
    return f"{_seat_word(pile.seat)} attack {pile.spot} on {place}"


def _units_words(catalog: Catalog, units) -> str:
    return " · ".join(f"{count} {catalog.name(slug)}" for slug, count in units.items() if count) or "nobody"


def render_map(catalog: Catalog, brief: MapBrief) -> bytes:
    """The map as `brief` has it, as PNG bytes."""
    s = SUPERSAMPLE
    areas = _ordered_areas(catalog)
    left, top, right, bottom = _map_bounds(areas)
    frame = 6
    map_w = round((right - left + 2 * frame) * MAP_SCALE)
    map_h = round((bottom - top + 2 * frame) * MAP_SCALE)
    width = map_w + 2 * MAP_MARGIN

    card_gap = 16
    card_w = (map_w - 2 * card_gap) / 3
    pile_rows = -(-len(brief.revealed) // 3)
    piles_h = (PILE_HEADING + pile_rows * PILE_PITCH) if brief.revealed else 0
    height = MAP_HEADER + map_h + MAP_LEGEND + piles_h + MAP_MARGIN

    image = Image.new("RGB", (width * s, height * s), WHITE)
    draw = ImageDraw.Draw(image)

    # The heading.
    draw.text((MAP_MARGIN * s, 34 * s), "THE NEW PROJECT", font=font(20 * s), fill=MUTED, anchor="ls")
    draw.text((MAP_MARGIN * s, 92 * s), "Map 3.3", font=font(54 * s), fill=INK, anchor="ls")
    if brief.caption:
        draw.text(((width - MAP_MARGIN) * s, 92 * s), brief.caption, font=font(30 * s, bold=False),
                  fill=SOFT_INK, anchor="rs")

    ox, oy = MAP_MARGIN, MAP_HEADER

    def at(point) -> tuple[float, float]:
        x, y = point
        return ((ox + (x - left + frame) * MAP_SCALE) * s, (oy + (y - top + frame) * MAP_SCALE) * s)

    # The map: the dark ground shows between the traced outlines as the
    # map's own lines, thick and thin as map 3.3 draws them.
    draw.rounded_rectangle((ox * s, oy * s, (ox + map_w) * s, (oy + map_h) * s), radius=8 * s, fill=INK)
    for area in areas:
        if area.is_base:
            fill = SEAT_COLOURS[area.seat]["base"]
        elif area.slug in brief.controllers:
            fill = SEAT_COLOURS[brief.controllers[area.slug]]["held"]
        else:
            fill = WHITE
        draw.polygon([at(point) for point in area.outline], fill=fill)

    for area in areas:
        _draw_area_marks(draw, catalog, brief, area, at, s)

    # The legend.
    y = (oy + map_h + 24) * s
    x = ox * s
    face = font(24 * s, bold=False)
    icon = 32 * s
    entries = [
        ("blue_minerals", "Blue minerals"), ("orange_minerals", "Orange minerals"), ("gems", "Gems"),
    ]
    for kind, words in entries:
        _icon(draw, kind, (x, y), icon)
        x += icon + 8 * s
        draw.text((x, y + icon / 2), words, font=face, fill=SOFT_INK, anchor="lm")
        x += face.getlength(words) + 32 * s
    for seat in SEATS:
        colours = SEAT_COLOURS[seat]
        draw.rounded_rectangle((x, y, x + 46 * s, y + icon), radius=5 * s, fill=colours["held"],
                               outline=colours["strong"], width=2 * s)
        x += 56 * s
        words = f"Held by {_seat_word(seat)}"
        draw.text((x, y + icon / 2), words, font=face, fill=SOFT_INK, anchor="lm")
        x += face.getlength(words) + 32 * s

    # The piles March has revealed.
    if brief.revealed:
        y0 = oy + map_h + MAP_LEGEND
        title_face, unit_face = font(28 * s), font(24 * s, bold=False)
        draw.text((ox * s, (y0 + 34) * s), "Revealed in March", font=font(32 * s), fill=INK, anchor="ls")
        for index, pile in enumerate(brief.revealed):
            row, col = divmod(index, 3)
            cx = ox + col * (card_w + card_gap)
            cy = y0 + PILE_HEADING + row * PILE_PITCH
            colours = SEAT_COLOURS[pile.seat]
            draw.rounded_rectangle((cx * s, cy * s, (cx + card_w) * s, (cy + PILE_CARD_H) * s), radius=10 * s,
                                   fill=WHITE, outline=colours["strong"], width=3 * s)
            _spot_badge(draw, pile, ((cx + 14) * s, (cy + 12) * s), 42 * s)
            draw.text(((cx + 66) * s, (cy + 33) * s),
                      _fit(_pile_words(catalog, pile), title_face, (card_w - 80) * s),
                      font=title_face, fill=colours["ink"], anchor="lm")
            rows = _wrap(_units_words(catalog, pile.units), unit_face, (card_w - 28) * s)[:2]
            for line_no, words in enumerate(rows):
                draw.text(((cx + 14) * s, (cy + 74 + line_no * 28) * s), words, font=unit_face,
                          fill=SOFT_INK, anchor="lm")

    return _png(image.resize((width, height), Image.LANCZOS))


def _spot_badge(draw: ImageDraw.ImageDraw, pile: Pile, at: tuple[float, float], size: float) -> None:
    """A pile's mark, a disc in its seat's colour: its spot's letter, or
    a white shield for a defense spot -- a disc, so it never reads as
    the bare shield that is a control token."""
    x, y = at
    colours = SEAT_COLOURS[pile.seat]
    draw.ellipse((x, y, x + size, y + size), fill=colours["strong"], outline=WHITE, width=max(1, round(size / 14)))
    if pile.spot == DEFENSE:
        glyph = size * 0.56
        _shape(draw, SHIELD, (x + (size - glyph * 24 / 28) / 2, y + (size - glyph) / 2 + size * 0.02),
               glyph * 24 / 28, WHITE, box=24)
        return
    draw.text((x + size / 2, y + size / 2), pile.spot, font=font(round(size * 0.6)), fill=WHITE, anchor="mm")


def _draw_area_marks(draw, catalog: Catalog, brief: MapBrief, area: Area, at, s: int) -> None:
    """An area's number, control token, tokens left, Stranded tokens and
    revealed piles, stacked on its widest part."""
    cx, cy = at(_anchor(area.outline))
    rows: list[tuple[float, float, object]] = []  # (width, height, painter)

    if area.is_base:
        colours = SEAT_COLOURS[area.seat]
        face = font(26 * s)
        shield_h = 60 * s
        label_w = max(face.getlength(area.seat.upper()), face.getlength("BASE"))

        def base_mark(x, y, area=area, colours=colours, face=face):
            middle = x + label_w / 2
            _shield(draw, area.seat, (middle - shield_h * 12 / 28, y), shield_h)
            draw.text((middle, y + shield_h + 22 * s), area.seat.upper(), font=face, fill=colours["ink"], anchor="mm")
            draw.text((middle, y + shield_h + 52 * s), "BASE", font=face, fill=colours["ink"], anchor="mm")

        rows.append((label_w, shield_h + 68 * s, base_mark))
    else:
        number = str(area.number)
        face = font((100 if area.number == 1 else 74) * s)
        number_w = face.getlength(number)
        held = brief.controllers.get(area.slug)
        shield_h = 48 * s
        width = number_w + ((shield_h * 24 / 28 + 10 * s) if held else 0)

        def number_mark(x, y, number=number, face=face, held=held, number_w=number_w):
            cursor = x
            if held:
                _shield(draw, held, (cursor, y + (face.size - shield_h) / 2 + 4 * s), shield_h)
                cursor += shield_h * 24 / 28 + 10 * s
            draw.text((cursor + number_w / 2, y + face.size / 2 + 2 * s), number, font=face, fill=INK, anchor="mm")

        rows.append((width, face.size + 4 * s, number_mark))

    left = brief.resources.get(area.slug, {})
    tokens = [(kind, int(left.get(kind, 0))) for kind in RESOURCES if int(left.get(kind, 0)) > 0]
    if tokens:
        pill_h, pill_face, gap = 46 * s, font(28 * s), 10 * s
        widths = [_pill_width(str(count), pill_face, pill_h, icon=True) for _, count in tokens]

        def token_mark(x, y, tokens=tokens, widths=widths):
            for (kind, count), pill_w in zip(tokens, widths):
                fill, ink = RESOURCE_COLOURS[kind]
                _pill(draw, x, y, str(count), pill_face, fill=WHITE, ink=ink, height=pill_h,
                      outline=fill, icon=kind, border=3 * s)
                x += pill_w + gap

        rows.append((sum(widths) + gap * (len(widths) - 1), pill_h, token_mark))

    for seat in brief.stranded.get(area.slug, ()):
        pill_h, pill_face = 44 * s, font(25 * s)
        words = f"{_seat_word(seat)} stranded"
        pill_w = _pill_width(words, pill_face, pill_h)

        def stranded_mark(x, y, seat=seat, words=words, pill_h=pill_h, pill_face=pill_face):
            _pill(draw, x, y, words, pill_face, fill=SEAT_COLOURS[seat]["strong"], ink=WHITE, height=pill_h,
                  outline=WHITE, border=2 * s)

        rows.append((pill_w, pill_h, stranded_mark))

    piles = [pile for pile in brief.revealed if pile.area == area.slug]
    if piles:
        size, gap = 46 * s, 8 * s

        def pile_mark(x, y, piles=piles):
            for pile in piles:
                _spot_badge(draw, pile, (x, y), size)
                x += size + gap

        rows.append((len(piles) * (size + gap) - gap, size, pile_mark))

    spacing = 10 * s
    total = sum(h for _, h, _ in rows) + spacing * (len(rows) - 1)
    y = cy - total / 2
    for row_w, row_h, painter in rows:
        painter(cx - row_w / 2, y)
        y += row_h + spacing


# ============================================================================
# The player board
# ============================================================================

BOARD_WIDTH = 1640
BOARD_PAD = 40
BOARD_GAP = 18
BOARD_HEADER = 124


def render_board(catalog: Catalog, brief: BoardBrief) -> bytes:
    """A seat's player board as `brief` has it, as PNG bytes."""
    canvas_h = 5000
    image = Image.new("RGB", (BOARD_WIDTH, canvas_h), WHITE)
    # RGBA, so a faded card's veil blends with what is under it.
    draw = ImageDraw.Draw(image, "RGBA")

    y = _board_header(draw, catalog, brief)
    column_w = (BOARD_WIDTH - 2 * BOARD_PAD - 3 * BOARD_GAP) / 4
    bottoms = []
    for index, slug in enumerate(catalog.facilities):
        x = BOARD_PAD + index * (column_w + BOARD_GAP)
        bottoms.append(_facility(draw, catalog, brief, slug, x, y, column_w))
    bottom = max(bottoms)
    for index, slug in enumerate(catalog.facilities):
        x = BOARD_PAD + index * (column_w + BOARD_GAP)
        draw.rounded_rectangle((x, y, x + column_w, bottom), radius=12, outline=RULE, width=2)

    y = _board_footer(draw, catalog, bottom + BOARD_GAP)
    return _png(image.crop((0, 0, BOARD_WIDTH, y + BOARD_PAD)))


def _board_header(draw, catalog: Catalog, brief: BoardBrief) -> float:
    colours = SEAT_COLOURS[brief.seat]
    top = BOARD_PAD
    draw.rounded_rectangle((BOARD_PAD, top, BOARD_WIDTH - BOARD_PAD, top + BOARD_HEADER), radius=12,
                           fill=colours["strong"])
    _shield(draw, brief.seat, (BOARD_PAD + 24, top + 30), 64)
    words = f"THE NEW PROJECT · {brief.seat.upper()}"
    if brief.caption:
        words += f" · {brief.caption.upper()}"
    draw.text((BOARD_PAD + 100, top + 42), words, font=font(18), fill=(230, 236, 242), anchor="ls")
    draw.text((BOARD_PAD + 100, top + 96), "Human base board", font=font(48), fill=WHITE, anchor="ls")

    # The available resource pool, open information (TNP 2.2).
    names = {
        "materials": ("material", "materials"), "gold": ("gold", "gold"), "blue_minerals": ("blue", "blue"),
        "orange_minerals": ("orange", "orange"), "gems": ("gem", "gems"),
    }
    face, pill_h = font(22), 48
    pills = []
    for key in POOL:
        amount = int(brief.pool.get(key, 0))
        pills.append((key, f"{amount} {names[key][0] if amount == 1 else names[key][1]}"))
    widths = [_pill_width(words, face, pill_h, icon=True) for _, words in pills]
    x = BOARD_WIDTH - BOARD_PAD - 24 - sum(widths) - 10 * (len(widths) - 1)
    draw.text((x, top + 38), "AVAILABLE POOL", font=font(17), fill=(230, 236, 242), anchor="ls")
    for (key, words), pill_w in zip(pills, widths):
        _pill(draw, x, top + 52, words, face, fill=WHITE, ink=INK, height=pill_h, icon=key)
        x += pill_w + 10
    return top + BOARD_HEADER + 20


def _cap(catalog: Catalog, brief: BoardBrief, slug: str) -> int:
    facility = catalog.facilities[slug]
    if facility.infrastructure_upgrade in brief.built:
        return facility.upgraded_production_cap
    return facility.production_cap


def _facility(draw, catalog: Catalog, brief: BoardBrief, slug: str, x: float, top: float, width: float) -> float:
    """One facility's column; the y under it."""
    facility = catalog.facilities[slug]
    pad = 16
    inner = width - 2 * pad
    y = top + pad
    draw.text((x + pad, y + 40), facility.name, font=font(40), fill=INK, anchor="ls")
    y += 56

    built = slug in brief.built
    queued_here = sum(int(brief.queued_units.get(unit, 0)) for unit in facility.units)
    chips = [f"Production cap {_cap(catalog, brief, slug)}"]
    if queued_here:
        chips.append(f"Producing {queued_here}")
    if built:
        chips.append("Built")
    elif slug in brief.queued:
        chips.append("Building: ready at Production")
    else:
        cost = facility.build_cost
        words = f"Not built · build {cost.materials}" if cost else "Not built"
        if facility.requires:
            words += f" · needs a {catalog.name(facility.requires)}"
        chips.append(words)
    y = _chip_rows(draw, chips, x + pad, y, inner, font(18), 36)
    y += 12

    groups: list[tuple[str, Optional[str], list[str]]] = [
        ("Units", None, [unit for unit in facility.units if catalog.units[unit].upgrade is None]),
    ]
    for upgrade in facility.unit_upgrades:
        groups.append((f"Upgrade: {catalog.name(upgrade).removesuffix(' Upgrade')}", upgrade,
                       [unit for unit in facility.units if catalog.units[unit].upgrade == upgrade]))
    for label, upgrade, units in groups:
        draw.line((x + pad, y, x + width - pad, y), fill=RULE, width=2)
        y += 10
        draw.text((x + pad, y + 17), _fit(label.upper(), font(SMALLEST), inner - 110), font=font(SMALLEST),
                  fill=MUTED, anchor="lm")
        if upgrade is not None:
            _upgrade_state(draw, catalog, brief, upgrade, x + width - pad, y + 1)
        y += 42
        for unit in units:
            usable = built and (upgrade is None or upgrade in brief.built)
            y = _unit_card(draw, catalog, brief, catalog.units[unit], x + pad, y, inner, usable) + 12

    # The infrastructure upgrade.
    upgrade = catalog.upgrades[facility.infrastructure_upgrade]
    face = font(19, bold=False)
    rows = _wrap(upgrade.ability.rstrip(".") + ".", face, inner - 24)
    box_h = 62 + 27 * len(rows)
    box = (x + pad, y, x + width - pad, y + box_h)
    _dashed_box(draw, box, (141, 138, 128))
    draw.text((x + pad + 12, y + 24), "INFRASTRUCTURE", font=font(SMALLEST), fill=MUTED, anchor="lm")
    _upgrade_state(draw, catalog, brief, upgrade.slug, x + width - pad - 10, y + 8)
    for index, words in enumerate(rows):
        draw.text((x + pad + 12, y + 58 + index * 27), words, font=face, fill=INK, anchor="lm")
    return y + box_h + pad


def _upgrade_state(draw, catalog: Catalog, brief: BoardBrief, slug: str, right: float, top: float) -> None:
    """An upgrade's chip, its right edge at `right`: built, queued, or
    its cost."""
    face, height = font(17), 32
    if slug in brief.built:
        words, fill, ink, icon, outline = "Built", RATING_FILLS[Rating.STRONG], (36, 107, 57), None, None
    elif slug in brief.queued:
        words, fill, ink, icon, outline = "Queued", RATING_FILLS[Rating.FAIR], INK, None, None
    else:
        words, fill, ink, icon, outline = f"Build {catalog.upgrades[slug].cost.materials}", WHITE, INK, "materials", RULE
    width = _pill_width(words, face, height, icon=icon is not None)
    _pill(draw, right - width, top, words, face, fill=fill, ink=ink, height=height, icon=icon, outline=outline)


def _chip_rows(draw, chips: Sequence[str], x: float, y: float, width: float, face, height: float,
               gap: float = 8) -> float:
    """Chips left to right, wrapping; the y under them."""
    cursor = x
    for words in chips:
        chip_w = _pill_width(words, face, height)
        if cursor > x and cursor + chip_w > x + width:
            cursor = x
            y += height + 8
        words = _fit(words, face, width - height * 0.8)
        cursor += _chip(draw, cursor, y, words, face, height) + gap
    return y + height


def _dashed_box(draw, box, colour, dash: int = 8, width: int = 2) -> None:
    left, top, right, bottom = box
    for start in range(int(left), int(right), dash * 2):
        end = min(start + dash, right)
        draw.line((start, top, end, top), fill=colour, width=width)
        draw.line((start, bottom, end, bottom), fill=colour, width=width)
    for start in range(int(top), int(bottom), dash * 2):
        end = min(start + dash, bottom)
        draw.line((left, start, left, end), fill=colour, width=width)
        draw.line((right, start, right, end), fill=colour, width=width)


def _traits(unit: Unit) -> list[str]:
    words = []
    for trait in unit.traits:
        name = TRAIT_NAMES.get(trait, trait.replace("_", " ").title())
        words.append(f"{name} {unit.scouting}" if trait == "scouting" else name)
    return words


def _unit_card(draw, catalog: Catalog, brief: BoardBrief, unit: Unit, x: float, y: float,
               width: float, usable: bool) -> float:
    """One unit's card; the y under it. A unit its seat cannot build yet
    -- its facility or its upgrade not finished -- is drawn faded."""
    border, ink = TYPE_COLOURS[unit.type]
    pad = 12
    top = y
    content = width - 2 * pad

    # Measure the traits rows first, so the card's height is known.
    trait_face, trait_h, trait_pad = font(17, bold=False), 32, 10
    supply = int(brief.supply_left.get(unit.slug, unit.supply))
    queued = int(brief.queued_units.get(unit.slug, 0))
    tail = f"Supply {supply} left" + (f" · {queued} queued" if queued else "")
    tail_face = font(17)
    tail_w = tail_face.getlength(tail)
    traits = _traits(unit)
    trait_rows, cursor = 1, 0.0
    for words in traits:
        chip_w = _pill_width(words, trait_face, trait_h, pad=trait_pad) + 6
        if cursor and cursor + chip_w > content:
            trait_rows += 1
            cursor = 0
        cursor += chip_w
    tail_own_row = bool(traits) and cursor + tail_w + 8 > content
    rows_h = (trait_rows + (1 if tail_own_row else 0)) * (trait_h + 6)
    cell_h = 92
    height = 2 * pad + 60 + 10 + cell_h + 12 + rows_h

    draw.rounded_rectangle((x, top, x + width, top + height), radius=8, fill=WHITE, outline=border, width=3)
    y = top + pad
    name_face = font(23)
    draw.text((x + pad, y + 14), _fit(unit.name, name_face, content - 100), font=name_face, fill=INK, anchor="lm")
    draw.text((x + pad, y + 46), f"{TYPE_WORDS[unit.type].upper()} · INITIATIVE {unit.initiative}",
              font=font(SMALLEST), fill=ink, anchor="lm")
    # The cost, right-aligned: materials, then gold where it asks any.
    cost_face, icon = font(22), 22
    cursor = x + width - pad
    for kind, amount in (("gold", unit.cost.gold), ("materials", unit.cost.materials)):
        if kind == "gold" and not amount:
            continue
        words = str(amount)
        cursor -= cost_face.getlength(words)
        draw.text((cursor, y + 14), words, font=cost_face, fill=INK, anchor="lm")
        cursor -= icon + 4
        _icon(draw, kind, (cursor, y + 14 - icon / 2), icon)
        cursor -= 10
    y += 70

    # The three ratings, as d12 numbers (TNP 4.1).
    cell_w = (content - 2 * 8) / 3
    for index, kind in enumerate(UnitType):
        rating = unit.rating(kind)
        cell_x = x + pad + index * (cell_w + 8)
        draw.rounded_rectangle((cell_x, y, cell_x + cell_w, y + cell_h), radius=6, fill=RATING_FILLS[rating])
        middle = cell_x + cell_w / 2
        draw.text((middle, y + 16), f"vs {TYPE_SHORT[kind]}", font=font(SMALLEST), fill=SOFT_INK, anchor="mm")
        draw.text((middle, y + 47), rating.shown, font=font(34), fill=INK, anchor="mm")
        draw.text((middle, y + 76), rating.value.title(), font=font(SMALLEST, bold=False), fill=INK, anchor="mm")
    y += cell_h + 12

    cursor = x + pad
    row_y = y
    for words in traits:
        chip_w = _pill_width(words, trait_face, trait_h, pad=trait_pad)
        if cursor > x + pad and cursor + chip_w > x + width - pad:
            cursor = x + pad
            row_y += trait_h + 6
        _chip(draw, cursor, row_y, words, trait_face, trait_h, pad=trait_pad)
        cursor += chip_w + 6
    if tail_own_row:
        row_y += trait_h + 6
    draw.text((x + width - pad, row_y + trait_h / 2), tail, font=tail_face, fill=INK if queued else SOFT_INK,
              anchor="rm")

    if not usable:
        draw.rounded_rectangle((x, top, x + width, top + height), radius=8, fill=(255, 255, 255, 140))
    return top + height


def _board_footer(draw, catalog: Catalog, y: float) -> float:
    """The d12's numbers, the limits and the conversion rates."""
    width = (BOARD_WIDTH - 2 * BOARD_PAD - 2 * BOARD_GAP) / 3
    height = 270
    boxes = [BOARD_PAD + index * (width + BOARD_GAP) for index in range(3)]
    for left in boxes:
        draw.rounded_rectangle((left, y, left + width, y + height), radius=12, fill=WHITE, outline=RULE, width=2)
    pad = 18
    title = font(30)
    note_face = font(18, bold=False)

    # Hits on a d12 (TNP 4.1).
    left = boxes[0]
    draw.text((left + pad, y + 40), "Hits on a d12", font=title, fill=INK, anchor="ls")
    cell_w = (width - 2 * pad - 3 * 8) / 4
    for index, rating in enumerate(Rating):
        cell_x = left + pad + index * (cell_w + 8)
        draw.rounded_rectangle((cell_x, y + 58, cell_x + cell_w, y + 136), radius=6, fill=RATING_FILLS[rating])
        draw.text((cell_x + cell_w / 2, y + 76), rating.value.title(), font=font(17, bold=False), fill=INK,
                  anchor="mm")
        draw.text((cell_x + cell_w / 2, y + 110), rating.shown, font=font(34), fill=INK, anchor="mm")
    note = ("A 12 always hits and a 1 always misses; modifiers add to the roll. "
            "X: one die for every two units, rounded down, needing a 12.")
    for index, words in enumerate(_wrap(note, note_face, width - 2 * pad)):
        draw.text((left + pad, y + 162 + index * 25), words, font=note_face, fill=SOFT_INK, anchor="lm")

    # The limits (TNP 2.4), each read from the board's data.
    left = boxes[1]
    draw.text((left + pad, y + 40), "Limits", font=title, fill=INK, anchor="ls")
    limits = catalog.board["limits"]
    rows = []
    for group in limits.get("deployed_together", ()):
        names = ", ".join(catalog.name(slug) for slug in group["units"])
        rows.append(f"At most {group['max']} deployed together of {names}")
    rows.append("Supply: how many of each unit a seat may have")
    rows.append(f"Advanced game: one building tech a facility, {limits['tech_facilities']} tech facilities")
    face = font(19, bold=False)
    line_y = y + 74
    for words in rows:
        wrapped = _wrap(words, face, width - 2 * pad - 18)
        draw.ellipse((left + pad, line_y - 4, left + pad + 8, line_y + 4), fill=INK)
        for line_no, part in enumerate(wrapped):
            draw.text((left + pad + 18, line_y + line_no * 25), part, font=face, fill=INK, anchor="lm")
        line_y += 25 * len(wrapped) + 10

    # The conversion rates (TNP 5.9), normal and emergency.
    left = boxes[2]
    draw.text((left + pad, y + 40), "Conversion rates", font=title, fill=INK, anchor="ls")
    conversion = catalog.board["conversion"]
    columns = [left + pad + 140, left + pad + 210, left + pad + 320, left + pad + 390]
    draw.text(((columns[0] + columns[1]) / 2, y + 66), "NORMAL", font=font(SMALLEST), fill=MUTED, anchor="mm")
    draw.text(((columns[2] + columns[3]) / 2, y + 66), "EMERGENCY", font=font(SMALLEST), fill=HIT, anchor="mm")
    for column, kind in zip(columns, ("materials", "gold", "materials", "gold")):
        _icon(draw, kind, (column - 13, y + 82), 26)
    for row_no, (token, words) in enumerate((("mineral", "Mineral"), ("gem", "Gem"))):
        row_y = y + 140 + row_no * 38
        draw.text((left + pad, row_y), words, font=font(20, bold=False), fill=INK, anchor="lm")
        values = (
            conversion["normal"][token]["materials"], conversion["normal"][token]["gold"],
            conversion["emergency"][token]["materials"], conversion["emergency"][token]["gold"],
        )
        for column, value in zip(columns, values):
            draw.text((column, row_y), "—" if value is None else str(value), font=font(24), fill=INK, anchor="mm")
    note = "A token trades for materials or for gold, never both."
    for index, words in enumerate(_wrap(note, note_face, width - 2 * pad)):
        draw.text((left + pad, y + 222 + index * 25), words, font=note_face, fill=SOFT_INK, anchor="lm")
    return y + height


# ============================================================================
# The battle
# ============================================================================

BATTLE_WIDTH = 1720
BATTLE_PAD = 40
TILE_H = 150
TILE_GAP = 14
BASE_CARD_W = 190
#: The rows' names, left of the line.
LABEL_W = 150
TRAY_H = 60
FOOTER_LINE = 40


def _area_words(catalog: Catalog, slug: str) -> str:
    area = catalog.areas[slug]
    return f"Territory {area.number}" if area.number is not None else area.name


def render_battle(catalog: Catalog, battle: BattleState) -> bytes:
    """A battle as it stands, as PNG bytes: the attacker above the middle
    line and the defender below it (the author, 2026-11-06), each seat's
    flanking forces on the outside of its front row."""
    base = catalog.areas[battle.territory].is_base
    bottom_seat = battle.defender or SEATS[1]
    top_seat = battle.attacker or lines.other(bottom_seat)

    rows_y = {}
    y = BATTLE_PAD + 160
    rows_y["top_tray"] = y
    y += TRAY_H + 12
    rows_y["top_flank"] = y
    y += TILE_H + 12
    rows_y["top_front"] = y
    y += TILE_H + 6
    rows_y["middle"] = y
    y += 36
    rows_y["bottom_front"] = y
    y += TILE_H + 12
    rows_y["bottom_flank"] = y
    y += TILE_H + 12
    rows_y["bottom_tray"] = y
    y += TRAY_H + 20
    footer_y = y
    footer_rows = _battle_footer_rows(catalog, battle)
    height = footer_y + FOOTER_LINE * len(footer_rows) + BATTLE_PAD

    image = Image.new("RGB", (BATTLE_WIDTH, height), WHITE)
    draw = ImageDraw.Draw(image)
    _battle_header(draw, catalog, battle)

    # The line's field.
    field_left = BATTLE_PAD + LABEL_W + (BASE_CARD_W + 20 if base else 0)
    field_right = BATTLE_WIDTH - BATTLE_PAD - 12 - (BASE_CARD_W + 20 if base else 0)
    draw.rounded_rectangle((BATTLE_PAD, rows_y["top_flank"] - 10, BATTLE_WIDTH - BATTLE_PAD,
                            rows_y["bottom_flank"] + TILE_H + 10), radius=14, fill=WHITE, outline=RULE, width=2)
    middle = rows_y["middle"] + 15
    draw.line((BATTLE_PAD + 12, middle, BATTLE_WIDTH - BATTLE_PAD - 12, middle), fill=RULE, width=3)

    # Each row named at its left: whose it is, and which.
    for seat, front_row, flank_row in (
        (top_seat, "top_front", "top_flank"), (bottom_seat, "bottom_front", "bottom_flank"),
    ):
        ink = SEAT_COLOURS[seat]["ink"]
        role = "attacks" if seat == battle.attacker else "defends" if seat == battle.defender else ""
        for row, words in ((front_row, "in front"), (flank_row, "flanking")):
            middle_y = rows_y[row] + TILE_H / 2
            draw.text((BATTLE_PAD + 16, middle_y - 24), seat.title(), font=font(24), fill=ink, anchor="lm")
            draw.text((BATTLE_PAD + 16, middle_y + 6), words, font=font(18, bold=False), fill=SOFT_INK, anchor="lm")
            if role and row == front_row:
                draw.text((BATTLE_PAD + 16, middle_y + 32), role, font=font(18, bold=False), fill=SOFT_INK,
                          anchor="lm")

    count = max(1, len(battle.line))
    column_w = min(280, (field_right - field_left - TILE_GAP * (count - 1)) / count)
    span = column_w * count + TILE_GAP * (count - 1)
    start = field_left + (field_right - field_left - span) / 2
    for index, column in enumerate(battle.line):
        cx = start + index * (column_w + TILE_GAP)
        number = str(index + 1)
        number_face = font(20)
        number_w = number_face.getlength(number) + 20
        draw.rectangle((cx + column_w / 2 - number_w / 2, middle - 14, cx + column_w / 2 + number_w / 2, middle + 14),
                       fill=WHITE)
        draw.text((cx + column_w / 2, middle), number, font=number_face, fill=MUTED, anchor="mm")
        for seat, front_row, flank_row in (
            (top_seat, "top_front", "top_flank"), (bottom_seat, "bottom_front", "bottom_flank"),
        ):
            ident = column.front.get(seat)
            if ident is not None:
                _force_tile(draw, catalog, battle, ident, (cx, rows_y[front_row], column_w, TILE_H))
            flankers = column.flankers(seat)
            if flankers:
                share = (column_w - 8 * (len(flankers) - 1)) / len(flankers)
                for number_in, flanker in enumerate(flankers):
                    _force_tile(draw, catalog, battle, flanker,
                                (cx + number_in * (share + 8), rows_y[flank_row], share, TILE_H), flanking=True)
    if not battle.line:
        draw.text(((field_left + field_right) / 2, middle - 50), "The line is not placed yet",
                  font=font(26, bold=False), fill=MUTED, anchor="mm")

    if base:
        defender_row = "bottom_front" if bottom_seat == battle.defender else "top_front"
        ends = ((BASE_LEFT, BATTLE_PAD + LABEL_W),
                (BASE_RIGHT, BATTLE_WIDTH - BATTLE_PAD - 12 - BASE_CARD_W))
        for target, left in ends:
            _base_card(draw, battle, target, (left, rows_y[defender_row], BASE_CARD_W, TILE_H))

    # The forces not in the line.
    tray_face, pill_face = font(22), font(20)
    for seat, row in ((top_seat, "top_tray"), (bottom_seat, "bottom_tray")):
        waiting = list(lines.unplaced(battle, seat))
        colours = SEAT_COLOURS[seat]
        x = BATTLE_PAD
        label = f"{_seat_word(seat)}, not placed:" if waiting else f"{_seat_word(seat)}: every force placed"
        draw.text((x, rows_y[row] + TRAY_H / 2), label, font=tray_face, fill=colours["ink"], anchor="lm")
        x += tray_face.getlength(label) + 14
        for found in waiting:
            words = f"{found.count} {catalog.name(found.unit)}"
            if found.damaged:
                words += f" ({found.damaged} damaged)"
            x += _pill(draw, x, rows_y[row] + 10, words, pill_face, fill=colours["held"], ink=colours["ink"],
                       height=40, outline=colours["strong"]) + 10

    for index, (words, ink) in enumerate(footer_rows):
        draw.text((BATTLE_PAD, footer_y + FOOTER_LINE * index + 16), words,
                  font=font(24, bold=index == 0 and ink == HIT), fill=ink, anchor="lm")
    return _png(image)


def _battle_header(draw, catalog: Catalog, battle: BattleState) -> None:
    draw.text((BATTLE_PAD, BATTLE_PAD + 18), "THE NEW PROJECT · BATTLE", font=font(20), fill=MUTED, anchor="ls")
    draw.text((BATTLE_PAD, BATTLE_PAD + 78), f"The battle for {_area_words(catalog, battle.territory)}",
              font=font(52), fill=INK, anchor="ls")

    # The round track (TNP 6.4): six rounds, this one filled.
    size, gap = 54, 12
    right = BATTLE_WIDTH - BATTLE_PAD
    left = right - ROUNDS * size - (ROUNDS - 1) * gap
    draw.text((left, BATTLE_PAD + 18), "ROUND", font=font(18), fill=MUTED, anchor="ls")
    for number in range(1, ROUNDS + 1):
        x = left + (number - 1) * (size + gap)
        box = (x, BATTLE_PAD + 30, x + size, BATTLE_PAD + 30 + size)
        if number == battle.round and battle.outcome is None:
            draw.ellipse(box, fill=INK)
            ink = WHITE
        elif number < battle.round or (battle.outcome is not None and number <= battle.round):
            draw.ellipse(box, fill=SPENT)
            ink = SOFT_INK
        else:
            draw.ellipse(box, fill=WHITE, outline=RULE, width=3)
            ink = SOFT_INK
        draw.text(((box[0] + box[2]) / 2, (box[1] + box[3]) / 2), str(number), font=font(24), fill=ink, anchor="mm")

    # Who attacks, who defends, the advantage and the group rolling.
    y = BATTLE_PAD + 126
    x = BATTLE_PAD
    face = font(24)
    parts = []
    if battle.attacker:
        parts.append((f"{_seat_word(battle.attacker)} attacks", SEAT_COLOURS[battle.attacker]))
    if battle.defender:
        parts.append((f"{_seat_word(battle.defender)} defends", SEAT_COLOURS[battle.defender]))
    for words, colours in parts:
        draw.ellipse((x, y - 10, x + 20, y + 10), fill=colours["strong"])
        x += 30
        draw.text((x, y), words, font=face, fill=colours["ink"], anchor="lm")
        x += face.getlength(words) + 32
    extras = []
    if battle.advantage:
        extras.append(f"Scouting advantage: {_seat_word(battle.advantage['seat'])} by {battle.advantage['by']}")
    if battle.group is not None and battle.phase in (lines.DAMAGE, lines.LOSSES):
        extras.append(f"Initiative {battle.group} rolling")
    if extras:
        draw.text((x, y), " · ".join(extras), font=font(24, bold=False), fill=SOFT_INK, anchor="lm")


def _force_tile(draw, catalog: Catalog, battle: BattleState, ident: str,
                box: tuple[float, float, float, float], flanking: bool = False) -> None:
    """A force: its unit, its count, its damage, and this group's hits
    on it."""
    x, y, width, height = box
    found = battle.force(ident)
    unit = catalog.units[found.unit]
    colours = SEAT_COLOURS[found.seat]
    type_colour, type_ink = TYPE_COLOURS[unit.type]
    draw.rounded_rectangle((x, y, x + width, y + height), radius=10, fill=colours["held"],
                           outline=colours["strong"], width=3)
    draw.rounded_rectangle((x + 3, y + 3, x + 13, y + height - 3), radius=4, fill=type_colour)
    count_face = font(48)
    count = str(found.count)
    count_w = count_face.getlength(count)
    draw.text((x + width - 14, y + 34), count, font=count_face, fill=INK, anchor="rm")
    name_face = font(23)
    draw.text((x + 24, y + 24), _fit(unit.name, name_face, width - count_w - 46), font=name_face, fill=INK,
              anchor="lm")
    words = f"{TYPE_WORDS[unit.type]} · init {unit.initiative}"
    draw.text((x + 24, y + 54), _fit(words, font(18), width - count_w - 46), font=font(18), fill=type_ink,
              anchor="lm")

    chips = []
    if found.damaged:
        chips.append((f"{found.damaged} damaged", DAMAGE_FILL, HIT))
    hits = battle.hits.get(ident, 0)
    if hits:
        chips.append((f"{hits} hit{'s' if hits != 1 else ''}", HIT, WHITE))
    removed = battle.removals.get(ident, 0)
    if removed:
        chips.append((f"{removed} removed", HIT, WHITE))
    leaving = battle.leaving.get(ident, 0)
    if leaving:
        chips.append((f"{leaving} retreating", SPENT, INK))
    if ident in battle.rolled:
        chips.append(("rolled", SPENT, INK))
    if found.count == 0:
        chips = [("destroyed", INK, WHITE)]
    cursor, row_y = x + 24, y + 80
    face, chip_h = font(18), 30
    for words, fill, ink in chips:
        chip_w = _pill_width(words, face, chip_h, pad=10)
        if cursor > x + 24 and cursor + chip_w > x + width - 8:
            cursor = x + 24
            row_y += chip_h + 6
        if row_y + chip_h > y + height - 4:
            break
        _pill(draw, cursor, row_y, words, face, fill=fill, ink=ink, height=chip_h, pad=10)
        cursor += chip_w + 6


def _base_card(draw, battle: BattleState, target: str, box) -> None:
    """A base card at an end of the line (TNP 6.9): attacked as
    armored, and this group's hits on it."""
    x, y, width, height = box
    colours = SEAT_COLOURS[battle.defender] if battle.defender else {"strong": INK, "base": SPENT, "ink": INK}
    draw.rounded_rectangle((x, y, x + width, y + height), radius=10, fill=colours["base"],
                           outline=colours["strong"], width=3)
    if battle.defender:
        _shield(draw, battle.defender, (x + 14, y + 14), 42)
    draw.text((x + 60, y + 28), "Base card", font=font(22), fill=colours["ink"], anchor="lm")
    draw.text((x + 60, y + 54), "left end" if target == BASE_LEFT else "right end", font=font(18, bold=False),
              fill=colours["ink"], anchor="lm")
    draw.text((x + 14, y + 88), "Armored", font=font(18), fill=TYPE_COLOURS[UnitType.ARMORED][1], anchor="lm")
    hits = battle.hits.get(target, 0)
    if hits:
        _pill(draw, x + 14, y + 106, f"{hits} hit{'s' if hits != 1 else ''}", font(18), fill=HIT, ink=WHITE,
              height=30, pad=10)


def _battle_footer_rows(catalog: Catalog, battle: BattleState) -> list[tuple[str, tuple]]:
    """The lines under the line: how it ended, the base's structures,
    what the base card destroyed and the units gone home."""
    rows: list[tuple[str, tuple]] = []
    if battle.outcome is not None:
        outcome = battle.outcome
        if outcome.get("winner") is None:
            rows.append(("Both sides destroyed: nobody wins the battle.", HIT))
        elif outcome.get("base_fallen"):
            rows.append((f"{_seat_word(outcome['winner'])} wins, and the base falls.", HIT))
        else:
            rows.append((f"{_seat_word(outcome['winner'])} wins the battle.", HIT))
    if battle.structures is not None:
        names = [catalog.name(slug) for key in ("facilities", "upgrades") for slug in battle.structures.get(key, [])]
        rows.append(("The base: " + (", ".join(names) or "nothing left"), INK))
    if battle.destroyed:
        rows.append((f"Destroyed by the base card: {catalog.name(battle.destroyed)}", HIT))
    for seat, units in battle.withdrawn.items():
        words = _units_words(catalog, {unit: row.get("count", 0) for unit, row in units.items()})
        rows.append((f"{_seat_word(seat)} retreated home: {words}", SEAT_COLOURS[seat]["ink"]))
    return rows


__all__ = ["render_battle", "render_board", "render_map"]
