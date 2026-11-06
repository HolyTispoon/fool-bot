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
  the columns, each force's unit, count and damage, the flanking forces
  behind, the round track and, for a base, the base cards.

Each draws what it is handed and decides nothing: a number, a rating's
d12 value or a limit is read from the catalog or the state, never
worked out here. The map and the board are drawn from a brief
(`tnp.briefs`) already filtered for whoever sees it, so nothing hidden
can reach a picture by accident; the battle is public.

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
from typing import Iterable, Optional, Sequence

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

# -- The palette -------------------------------------------------------------

INK = (42, 44, 48)
SOFT_INK = (69, 71, 77)
MUTED = (91, 93, 99)
WHITE = (255, 255, 255)
PAPER = (251, 250, 246)
RULE = (217, 210, 195)
CHIP = (235, 229, 216)
CHIP_LIGHT = (239, 233, 220)
HIT = (176, 42, 30)

#: Each seat's colour, its tint for a territory it holds, its base's
#: fill and the ink of a word in it -- the canvas's blue and green.
SEAT_COLOURS = {
    "blue": {"strong": (47, 95, 158), "held": (213, 225, 242), "base": (184, 203, 232), "ink": (31, 66, 112)},
    "green": {"strong": (47, 122, 69), "held": (211, 233, 214), "base": (179, 216, 187), "ink": (31, 90, 49)},
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

RATING_FILLS = {
    Rating.STRONG: (227, 239, 225),
    Rating.FAIR: (243, 236, 214),
    Rating.WEAK: (246, 226, 220),
    Rating.POOR: (235, 229, 216),
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
    x, y = at
    inner = ((12, 4.5), (12, 24), (7.4, 21.6), (5, 13), (5, 7))
    _shape(draw, inner, (x, y), width, tuple(min(255, c + 70) for c in colours["strong"]), box=24)


def _text_width(text: str, face: ImageFont.FreeTypeFont) -> float:
    return face.getlength(text)


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


# ============================================================================
# The map
# ============================================================================

#: The map is drawn this many output pixels to one of map3.3-1.png's.
MAP_SCALE = 0.72
#: Drawn this many times larger, then reduced, so the traced outlines'
#: edges are smooth.
SUPERSAMPLE = 2
MAP_MARGIN = 40
MAP_HEADER = 96


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

    pile_face = font(20)
    unit_face = font(18, bold=False)
    card_w = (map_w - 2 * 16) / 3
    pile_rows = -(-len(brief.revealed) // 3)
    piles_h = (40 + pile_rows * 100) if brief.revealed else 0
    legend_h = 56
    height = MAP_HEADER + map_h + legend_h + piles_h + MAP_MARGIN

    image = Image.new("RGB", (width * s, height * s), WHITE)
    draw = ImageDraw.Draw(image)

    # The heading.
    draw.text((MAP_MARGIN * s, 26 * s), "THE NEW PROJECT", font=font(15 * s), fill=MUTED, anchor="ls")
    draw.text((MAP_MARGIN * s, 74 * s), "Map 3.3", font=font(44 * s), fill=INK, anchor="ls")
    if brief.caption:
        draw.text(((width - MAP_MARGIN) * s, 74 * s), brief.caption, font=font(22 * s, bold=False),
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
    y = (oy + map_h + 18) * s
    x = ox * s
    face = font(17 * s, bold=False)
    entries = [
        ("blue_minerals", "Blue minerals"), ("orange_minerals", "Orange minerals"), ("gems", "Gems"),
    ]
    for kind, words in entries:
        _icon(draw, kind, (x, y), 22 * s)
        x += 28 * s
        draw.text((x, y + 11 * s), words, font=face, fill=SOFT_INK, anchor="lm")
        x += face.getlength(words) + 28 * s
    for seat in SEATS:
        colours = SEAT_COLOURS[seat]
        draw.rounded_rectangle((x, y, x + 34 * s, y + 22 * s), radius=4 * s, fill=colours["held"],
                               outline=colours["strong"], width=2 * s)
        x += 42 * s
        words = f"Held by {_seat_word(seat)}"
        draw.text((x, y + 11 * s), words, font=face, fill=SOFT_INK, anchor="lm")
        x += face.getlength(words) + 28 * s

    # The piles March has revealed.
    if brief.revealed:
        y0 = oy + map_h + legend_h
        draw.text((ox * s, (y0 + 22) * s), "Revealed in March", font=font(22 * s), fill=INK, anchor="ls")
        for index, pile in enumerate(brief.revealed):
            row, col = divmod(index, 3)
            cx = ox + col * (card_w + 16)
            cy = y0 + 36 + row * 100
            colours = SEAT_COLOURS[pile.seat]
            draw.rounded_rectangle((cx * s, cy * s, (cx + card_w) * s, (cy + 86) * s), radius=10 * s,
                                   fill=PAPER, outline=colours["strong"], width=2 * s)
            _spot_badge(draw, pile, ((cx + 14) * s, (cy + 12) * s), 30 * s)
            draw.text(((cx + 54) * s, (cy + 27) * s), _fit(_pile_words(catalog, pile), pile_face, card_w - 66),
                      font=font(20 * s), fill=colours["ink"], anchor="lm")
            rows = _wrap(_units_words(catalog, pile.units), unit_face, card_w - 28)[:2]
            for line_no, words in enumerate(rows):
                draw.text(((cx + 14) * s, (cy + 56 + line_no * 22) * s), words, font=font(18 * s, bold=False),
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
    draw.text((x + size / 2, y + size / 2), pile.spot, font=font(round(size * 0.58)), fill=WHITE, anchor="mm")


def _draw_area_marks(draw, catalog: Catalog, brief: MapBrief, area: Area, at, s: int) -> None:
    """An area's number, control token, tokens left, Stranded tokens and
    revealed piles, stacked on its widest part."""
    cx, cy = at(_anchor(area.outline))
    rows: list[tuple[float, float, object]] = []  # (width, height, painter)

    if area.is_base:
        colours = SEAT_COLOURS[area.seat]
        face = font(18 * s)

        def base_mark(x, y, area=area, colours=colours, face=face):
            _shield(draw, area.seat, (x + 26 * s, y), 44 * s)
            draw.text((x + 45 * s, y + 62 * s), area.seat.upper(), font=face, fill=colours["ink"], anchor="mm")
            draw.text((x + 45 * s, y + 82 * s), "BASE", font=face, fill=colours["ink"], anchor="mm")

        rows.append((90 * s, 92 * s, base_mark))
    else:
        number = str(area.number)
        face = font((84 if area.number == 1 else 62) * s)
        number_w = face.getlength(number)
        held = brief.controllers.get(area.slug)
        shield_h = 34 * s
        width = number_w + ((shield_h * 24 / 28 + 8 * s) if held else 0)

        def number_mark(x, y, number=number, face=face, held=held, number_w=number_w):
            cursor = x
            if held:
                _shield(draw, held, (cursor, y + (face.size - shield_h) / 2 + 4 * s), shield_h)
                cursor += shield_h * 24 / 28 + 8 * s
            draw.text((cursor + number_w / 2, y + face.size / 2 + 2 * s), number, font=face, fill=INK, anchor="mm")

        rows.append((width, face.size + 4 * s, number_mark))

    left = brief.resources.get(area.slug, {})
    tokens = [(kind, int(left.get(kind, 0))) for kind in RESOURCES if int(left.get(kind, 0)) > 0]
    if tokens:
        pill_h, pill_face, gap = 30 * s, font(17 * s), 8 * s
        widths = [_pill_width(str(count), pill_face, pill_h, icon=True) for _, count in tokens]

        def token_mark(x, y, tokens=tokens, widths=widths):
            for (kind, count), pill_w in zip(tokens, widths):
                fill, ink = RESOURCE_COLOURS[kind]
                _pill(draw, x, y, str(count), pill_face, fill=WHITE, ink=ink, height=pill_h,
                      outline=fill, icon=kind)
                x += pill_w + gap

        rows.append((sum(widths) + gap * (len(widths) - 1), pill_h, token_mark))

    for seat in brief.stranded.get(area.slug, ()):
        pill_h, pill_face = 28 * s, font(15 * s)
        words = f"{_seat_word(seat)} stranded"
        pill_w = _pill_width(words, pill_face, pill_h)

        def stranded_mark(x, y, seat=seat, words=words):
            _pill(draw, x, y, words, pill_face, fill=SEAT_COLOURS[seat]["strong"], ink=WHITE, height=pill_h,
                  outline=WHITE)

        rows.append((pill_w, pill_h, stranded_mark))

    piles = [pile for pile in brief.revealed if pile.area == area.slug]
    if piles:
        size, gap = 30 * s, 6 * s

        def pile_mark(x, y, piles=piles):
            for pile in piles:
                _spot_badge(draw, pile, (x, y), size)
                x += size + gap

        rows.append((len(piles) * (size + gap) - gap, size, pile_mark))

    spacing = 8 * s
    total = sum(h for _, h, _ in rows) + spacing * (len(rows) - 1)
    y = cy - total / 2
    for row_w, row_h, painter in rows:
        painter(cx - row_w / 2, y)
        y += row_h + spacing


# ============================================================================
# The player board
# ============================================================================

BOARD_WIDTH = 1480
BOARD_PAD = 40
BOARD_GAP = 18


def render_board(catalog: Catalog, brief: BoardBrief) -> bytes:
    """A seat's player board as `brief` has it, as PNG bytes."""
    canvas_h = 4000
    image = Image.new("RGB", (BOARD_WIDTH, canvas_h), WHITE)
    # RGBA, so a faded card's veil blends with what is under it.
    draw = ImageDraw.Draw(image, "RGBA")

    y = _board_header(draw, catalog, brief)
    column_w = (BOARD_WIDTH - 2 * BOARD_PAD - 3 * BOARD_GAP) / 4
    bottoms = []
    for index, slug in enumerate(catalog.facilities):
        x = BOARD_PAD + index * (column_w + BOARD_GAP)
        bottoms.append(_facility(draw, catalog, brief, slug, x, y, column_w))
    y = max(bottoms) + BOARD_GAP
    for index, slug in enumerate(catalog.facilities):
        x = BOARD_PAD + index * (column_w + BOARD_GAP)
        draw.rounded_rectangle((x, BOARD_PAD + 116, x + column_w, y - BOARD_GAP), radius=12,
                               outline=RULE, width=1)

    y = _board_footer(draw, catalog, y)
    return _png(image.crop((0, 0, BOARD_WIDTH, y + BOARD_PAD)))


def _board_header(draw, catalog: Catalog, brief: BoardBrief) -> float:
    colours = SEAT_COLOURS[brief.seat]
    top, height = BOARD_PAD, 96
    draw.rounded_rectangle((BOARD_PAD, top, BOARD_WIDTH - BOARD_PAD, top + height), radius=12,
                           fill=colours["strong"])
    _shield(draw, brief.seat, (BOARD_PAD + 24, top + 22), 52)
    words = f"THE NEW PROJECT · {brief.seat.upper()}"
    if brief.caption:
        words += f" · {brief.caption.upper()}"
    draw.text((BOARD_PAD + 84, top + 34), words, font=font(14), fill=(225, 232, 240), anchor="ls")
    draw.text((BOARD_PAD + 84, top + 76), "Human base board", font=font(40), fill=WHITE, anchor="ls")

    # The available resource pool, open information (TNP 2.2).
    names = {
        "materials": ("material", "materials"), "gold": ("gold", "gold"), "blue_minerals": ("blue", "blue"),
        "orange_minerals": ("orange", "orange"), "gems": ("gem", "gems"),
    }
    face, pill_h = font(18), 40
    pills = []
    for key in POOL:
        amount = int(brief.pool.get(key, 0))
        pills.append((key, f"{amount} {names[key][0] if amount == 1 else names[key][1]}"))
    widths = [_pill_width(words, face, pill_h, icon=True) for _, words in pills]
    x = BOARD_WIDTH - BOARD_PAD - 24 - sum(widths) - 10 * (len(widths) - 1)
    draw.text((x, top + 22), "AVAILABLE POOL", font=font(13), fill=(225, 232, 240), anchor="ls")
    for (key, words), pill_w in zip(pills, widths):
        _pill(draw, x, top + 34, words, face, fill=WHITE, ink=INK, height=pill_h, icon=key)
        x += pill_w + 10
    return top + height + 20


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
    draw.text((x + pad, y + 32), facility.name, font=font(32), fill=INK, anchor="ls")
    y += 46

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
    y = _chip_rows(draw, chips, x + pad, y, inner, font(14), 28)
    y += 8

    groups: list[tuple[str, Optional[str], list[str]]] = [
        ("Units", None, [unit for unit in facility.units if catalog.units[unit].upgrade is None]),
    ]
    for upgrade in facility.unit_upgrades:
        groups.append((f"Upgrade: {catalog.name(upgrade).removesuffix(' Upgrade')}", upgrade,
                       [unit for unit in facility.units if catalog.units[unit].upgrade == upgrade]))
    for label, upgrade, units in groups:
        draw.line((x + pad, y, x + width - pad, y), fill=(235, 229, 216), width=1)
        y += 8
        draw.text((x + pad, y + 14), label.upper(), font=font(12), fill=MUTED, anchor="lm")
        if upgrade is not None:
            _upgrade_state(draw, catalog, brief, upgrade, x + width - pad, y + 2)
        y += 32
        for unit in units:
            usable = built and (upgrade is None or upgrade in brief.built)
            y = _unit_card(draw, catalog, brief, catalog.units[unit], x + pad, y, inner, usable) + 10

    # The infrastructure upgrade.
    upgrade = catalog.upgrades[facility.infrastructure_upgrade]
    face = font(15, bold=False)
    rows = _wrap(upgrade.ability.rstrip(".") + ".", face, inner - 24)
    box_h = 44 + 22 * len(rows)
    box = (x + pad, y, x + width - pad, y + box_h)
    _dashed_box(draw, box, (141, 138, 128))
    draw.text((x + pad + 12, y + 20), "INFRASTRUCTURE UPGRADE", font=font(12), fill=MUTED, anchor="lm")
    _upgrade_state(draw, catalog, brief, upgrade.slug, x + width - pad - 10, y + 8)
    for index, words in enumerate(rows):
        draw.text((x + pad + 12, y + 44 + index * 22), words, font=face, fill=INK, anchor="lm")
    return y + box_h + pad


def _upgrade_state(draw, catalog: Catalog, brief: BoardBrief, slug: str, right: float, top: float) -> None:
    """An upgrade's chip, its right edge at `right`: built, queued, or
    its cost."""
    face, height = font(13), 24
    if slug in brief.built:
        words, fill, ink, icon = "Built", (227, 239, 225), (36, 107, 57), None
    elif slug in brief.queued:
        words, fill, ink, icon = "Queued", (243, 236, 214), INK, None
    else:
        words, fill, ink, icon = f"Build {catalog.upgrades[slug].cost.materials}", CHIP_LIGHT, INK, "materials"
    width = _pill_width(words, face, height, icon=icon is not None)
    _pill(draw, right - width, top, words, face, fill=fill, ink=ink, height=height, icon=icon)


def _chip_rows(draw, chips: Sequence[str], x: float, y: float, width: float, face, height: float,
               fill=CHIP_LIGHT, ink=INK, gap: float = 8) -> float:
    """Chips left to right, wrapping; the y under them."""
    cursor = x
    for words in chips:
        chip_w = _pill_width(words, face, height)
        if cursor > x and cursor + chip_w > x + width:
            cursor = x
            y += height + 6
        words = _fit(words, face, width - height * 0.8)
        cursor += _pill(draw, cursor, y, words, face, fill=fill, ink=ink, height=height) + gap
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
    pad = 10
    top = y

    # Measure the traits row first, so the card's height is known.
    trait_face, trait_h = font(12, bold=False), 22
    supply = int(brief.supply_left.get(unit.slug, unit.supply))
    queued = int(brief.queued_units.get(unit.slug, 0))
    tail = f"Supply {supply} left" + (f" · {queued} queued" if queued else "")
    tail_w = font(12).getlength(tail)
    traits = _traits(unit)
    trait_rows, cursor = 1, 0.0
    for words in traits:
        chip_w = _pill_width(words, trait_face, trait_h, pad=8) + 6
        if cursor and cursor + chip_w > width - 2 * pad:
            trait_rows += 1
            cursor = 0
        cursor += chip_w
    tail_own_row = cursor + tail_w + 8 > width - 2 * pad
    rows_h = (trait_rows + (1 if tail_own_row else 0)) * (trait_h + 4)
    height = 2 * pad + 40 + 8 + 64 + 8 + rows_h

    draw.rounded_rectangle((x, top, x + width, top + height), radius=8, fill=PAPER, outline=border, width=2)
    y = top + pad
    draw.text((x + pad, y + 10), _fit(unit.name, font(16), width - 110), font=font(16), fill=INK, anchor="lm")
    draw.text((x + pad, y + 31), f"{TYPE_WORDS[unit.type].upper()} · INITIATIVE {unit.initiative}",
              font=font(11), fill=ink, anchor="lm")
    # The cost, right-aligned: materials, then gold where it asks any.
    cost_face = font(15)
    cursor = x + width - pad
    for kind, amount in (("gold", unit.cost.gold), ("materials", unit.cost.materials)):
        if kind == "gold" and not amount:
            continue
        words = str(amount)
        cursor -= cost_face.getlength(words)
        draw.text((cursor, y + 10), words, font=cost_face, fill=INK, anchor="lm")
        cursor -= 20
        _icon(draw, kind, (cursor, y + 2), 16)
        cursor -= 8
    y += 48

    # The three ratings, as d12 numbers (TNP 4.1).
    cell_w = (width - 2 * pad - 2 * 6) / 3
    for index, kind in enumerate(UnitType):
        rating = unit.rating(kind)
        cell_x = x + pad + index * (cell_w + 6)
        draw.rounded_rectangle((cell_x, y, cell_x + cell_w, y + 64), radius=6, fill=RATING_FILLS[rating])
        middle = cell_x + cell_w / 2
        draw.text((middle, y + 12), f"vs {TYPE_SHORT[kind]}", font=font(11), fill=MUTED, anchor="mm")
        draw.text((middle, y + 34), rating.shown, font=font(24), fill=INK, anchor="mm")
        draw.text((middle, y + 54), rating.value.title(), font=font(11, bold=False), fill=SOFT_INK, anchor="mm")
    y += 72

    cursor = x + pad
    row_y = y
    for words in traits:
        chip_w = _pill_width(words, trait_face, trait_h, pad=8)
        if cursor > x + pad and cursor + chip_w > x + width - pad:
            cursor = x + pad
            row_y += trait_h + 4
        _pill(draw, cursor, row_y, words, trait_face, fill=CHIP, ink=INK, height=trait_h, pad=8)
        cursor += chip_w + 6
    if tail_own_row:
        row_y += trait_h + 4
    draw.text((x + width - pad, row_y + trait_h / 2), tail, font=font(12), fill=MUTED if not queued else INK,
              anchor="rm")

    if not usable:
        draw.rounded_rectangle((x, top, x + width, top + height), radius=8, fill=(255, 255, 255, 130))
    return top + height


def _board_footer(draw, catalog: Catalog, y: float) -> float:
    """The d12's numbers, the limits and the conversion rates."""
    width = (BOARD_WIDTH - 2 * BOARD_PAD - 2 * BOARD_GAP) / 3
    height = 200
    boxes = [BOARD_PAD + index * (width + BOARD_GAP) for index in range(3)]
    for left in boxes:
        draw.rounded_rectangle((left, y, left + width, y + height), radius=12, fill=WHITE, outline=RULE, width=1)
    pad = 16

    # Hits on a d12 (TNP 4.1).
    left = boxes[0]
    draw.text((left + pad, y + 32), "Hits on a d12", font=font(24), fill=INK, anchor="ls")
    cell_w = (width - 2 * pad - 3 * 8) / 4
    for index, rating in enumerate(Rating):
        cell_x = left + pad + index * (cell_w + 8)
        draw.rounded_rectangle((cell_x, y + 46, cell_x + cell_w, y + 106), radius=6, fill=RATING_FILLS[rating])
        draw.text((cell_x + cell_w / 2, y + 60), rating.value.title(), font=font(12, bold=False), fill=SOFT_INK,
                  anchor="mm")
        draw.text((cell_x + cell_w / 2, y + 86), rating.shown, font=font(26), fill=INK, anchor="mm")
    note = ("A 12 always hits and a 1 always misses; modifiers add to the roll. "
            "X: one die for every two units, rounded down, needing a 12.")
    for index, words in enumerate(_wrap(note, font(13, bold=False), width - 2 * pad)):
        draw.text((left + pad, y + 126 + index * 19), words, font=font(13, bold=False), fill=SOFT_INK, anchor="lm")

    # The limits (TNP 2.4), each read from the board's data.
    left = boxes[1]
    draw.text((left + pad, y + 32), "Limits", font=font(24), fill=INK, anchor="ls")
    limits = catalog.board["limits"]
    rows = []
    for group in limits.get("deployed_together", ()):
        names = ", ".join(catalog.name(slug) for slug in group["units"])
        rows.append(f"At most {group['max']} deployed together of {names}")
    rows.append("Supply: how many of each unit a seat may have")
    rows.append(f"Advanced game: one building tech a facility, {limits['tech_facilities']} tech facilities")
    face = font(14, bold=False)
    line_y = y + 56
    for words in rows:
        wrapped = _wrap(words, face, width - 2 * pad - 14)
        draw.ellipse((left + pad, line_y - 3, left + pad + 6, line_y + 3), fill=INK)
        for line_no, part in enumerate(wrapped):
            draw.text((left + pad + 14, line_y + line_no * 20), part, font=face, fill=INK, anchor="lm")
        line_y += 20 * len(wrapped) + 8

    # The conversion rates (TNP 5.9), normal and emergency.
    left = boxes[2]
    draw.text((left + pad, y + 32), "Conversion rates", font=font(24), fill=INK, anchor="ls")
    conversion = catalog.board["conversion"]
    columns = [left + pad + 92, left + pad + 142, left + pad + 222, left + pad + 272]
    for column, kind in zip(columns, ("materials", "gold", "materials", "gold")):
        _icon(draw, kind, (column - 9, y + 50), 18)
    draw.text(((columns[0] + columns[1]) / 2, y + 42), "NORMAL", font=font(11), fill=MUTED, anchor="mm")
    draw.text(((columns[2] + columns[3]) / 2, y + 42), "EMERGENCY", font=font(11), fill=(162, 51, 31), anchor="mm")
    for row_no, (token, words) in enumerate((("mineral", "Mineral"), ("gem", "Gem"))):
        row_y = y + 92 + row_no * 30
        draw.text((left + pad, row_y), words, font=font(15, bold=False), fill=INK, anchor="lm")
        values = (
            conversion["normal"][token]["materials"], conversion["normal"][token]["gold"],
            conversion["emergency"][token]["materials"], conversion["emergency"][token]["gold"],
        )
        for column, value in zip(columns, values):
            draw.text((column, row_y), "—" if value is None else str(value), font=font(17), fill=INK, anchor="mm")
    note = "A token trades for materials or for gold, never both."
    draw.text((left + pad, y + 170), note, font=font(13, bold=False), fill=SOFT_INK, anchor="lm")
    return y + height


# ============================================================================
# The battle
# ============================================================================

BATTLE_WIDTH = 1600
BATTLE_PAD = 40
TILE_H = 118
BASE_CARD_W = 170
#: The rows' names, left of the line.
LABEL_W = 96


def _area_words(catalog: Catalog, slug: str) -> str:
    area = catalog.areas[slug]
    return f"Territory {area.number}" if area.number is not None else area.name


def render_battle(catalog: Catalog, battle: BattleState) -> bytes:
    """A battle as it stands, as PNG bytes."""
    base = catalog.areas[battle.territory].is_base
    top_seat = battle.defender or SEATS[1]
    bottom_seat = battle.attacker or lines.other(top_seat)

    tray_h = 44
    rows_y = {}
    y = BATTLE_PAD + 132
    rows_y["top_tray"] = y
    y += tray_h + 10
    rows_y["top_flank"] = y
    y += TILE_H + 12
    rows_y["top_front"] = y
    y += TILE_H + 6
    rows_y["middle"] = y
    y += 30
    rows_y["bottom_front"] = y
    y += TILE_H + 12
    rows_y["bottom_flank"] = y
    y += TILE_H + 10
    rows_y["bottom_tray"] = y
    y += tray_h + 16
    footer_y = y
    footer_rows = _battle_footer_rows(catalog, battle)
    height = footer_y + 34 * len(footer_rows) + BATTLE_PAD

    image = Image.new("RGB", (BATTLE_WIDTH, height), WHITE)
    draw = ImageDraw.Draw(image)
    _battle_header(draw, catalog, battle, top_seat, bottom_seat)

    # The line's field.
    field_left = BATTLE_PAD + LABEL_W + (BASE_CARD_W + 20 if base else 0)
    field_right = BATTLE_WIDTH - BATTLE_PAD - (BASE_CARD_W + 20 if base else 0)
    draw.rounded_rectangle((BATTLE_PAD, rows_y["top_flank"] - 8, BATTLE_WIDTH - BATTLE_PAD,
                            rows_y["bottom_flank"] + TILE_H + 8), radius=14, fill=(246, 244, 238))
    middle = rows_y["middle"] + 12
    draw.line((BATTLE_PAD + 12, middle, BATTLE_WIDTH - BATTLE_PAD - 12, middle), fill=RULE, width=2)
    # Each row named at its left: whose it is, and which.
    for seat, front_row, flank_row in (
        (top_seat, "top_front", "top_flank"), (bottom_seat, "bottom_front", "bottom_flank"),
    ):
        ink = SEAT_COLOURS[seat]["ink"]
        role = "ATTACKS" if seat == battle.attacker else "DEFENDS" if seat == battle.defender else ""
        for row, words in ((front_row, "IN FRONT"), (flank_row, "FLANKING")):
            middle_y = rows_y[row] + TILE_H / 2
            draw.text((BATTLE_PAD + 14, middle_y - 10), seat.upper(), font=font(13), fill=ink, anchor="lm")
            draw.text((BATTLE_PAD + 14, middle_y + 8), words, font=font(11), fill=MUTED, anchor="lm")
        if role:
            draw.text((BATTLE_PAD + 14, rows_y[front_row] + TILE_H / 2 + 24), role, font=font(11), fill=MUTED,
                      anchor="lm")

    count = max(1, len(battle.line))
    gap = 14
    column_w = min(240, (field_right - field_left - gap * (count - 1)) / count)
    span = column_w * count + gap * (count - 1)
    start = field_left + (field_right - field_left - span) / 2
    for index, column in enumerate(battle.line):
        cx = start + index * (column_w + gap)
        draw.text((cx + column_w / 2, middle), f"  {index + 1}  ", font=font(13), fill=MUTED, anchor="mm")
        for seat, front_row, flank_row in (
            (top_seat, "top_front", "top_flank"), (bottom_seat, "bottom_front", "bottom_flank"),
        ):
            ident = column.front.get(seat)
            if ident is not None:
                _force_tile(draw, catalog, battle, ident, (cx, rows_y[front_row], column_w, TILE_H))
            flankers = column.flankers(seat)
            if flankers:
                share = (column_w - 8 * (len(flankers) - 1)) / len(flankers)
                for number, flanker in enumerate(flankers):
                    _force_tile(draw, catalog, battle, flanker,
                                (cx + number * (share + 8), rows_y[flank_row], share, TILE_H), flanking=True)
    if not battle.line:
        draw.text((BATTLE_WIDTH / 2, middle - 40), "The line is not placed yet", font=font(20, bold=False),
                  fill=MUTED, anchor="mm")

    if base:
        defender_row = "top_front"
        ends = ((BASE_LEFT, BATTLE_PAD + LABEL_W), (BASE_RIGHT, BATTLE_WIDTH - BATTLE_PAD - 10 - BASE_CARD_W))
        for target, left in ends:
            _base_card(draw, battle, target, (left, rows_y[defender_row], BASE_CARD_W, TILE_H))

    # The forces not in the line.
    for seat, row in ((top_seat, "top_tray"), (bottom_seat, "bottom_tray")):
        waiting = [found for found in lines.unplaced(battle, seat)]
        colours = SEAT_COLOURS[seat]
        x = BATTLE_PAD
        label = f"{_seat_word(seat)}, not placed:" if waiting else f"{_seat_word(seat)}: every force placed"
        draw.text((x, rows_y[row] + tray_h / 2), label, font=font(15), fill=colours["ink"], anchor="lm")
        x += font(15).getlength(label) + 12
        for found in waiting:
            words = f"{found.count} {catalog.name(found.unit)}"
            if found.damaged:
                words += f" ({found.damaged} damaged)"
            x += _pill(draw, x, rows_y[row] + 8, words, font(14), fill=colours["held"], ink=colours["ink"],
                       height=28, outline=colours["strong"]) + 8

    for index, (words, ink) in enumerate(footer_rows):
        draw.text((BATTLE_PAD, footer_y + 34 * index + 14), words, font=font(17, bold=index == 0 and ink == HIT),
                  fill=ink, anchor="lm")
    return _png(image)


def _battle_header(draw, catalog: Catalog, battle: BattleState, top_seat: str, bottom_seat: str) -> None:
    draw.text((BATTLE_PAD, BATTLE_PAD + 14), "THE NEW PROJECT · BATTLE", font=font(14), fill=MUTED, anchor="ls")
    draw.text((BATTLE_PAD, BATTLE_PAD + 62), f"The battle for {_area_words(catalog, battle.territory)}",
              font=font(40), fill=INK, anchor="ls")

    # The round track (TNP 6.4): six rounds, this one filled.
    size, gap = 40, 10
    right = BATTLE_WIDTH - BATTLE_PAD
    left = right - ROUNDS * size - (ROUNDS - 1) * gap
    draw.text((left, BATTLE_PAD + 14), "ROUND", font=font(13), fill=MUTED, anchor="ls")
    for number in range(1, ROUNDS + 1):
        x = left + (number - 1) * (size + gap)
        box = (x, BATTLE_PAD + 24, x + size, BATTLE_PAD + 24 + size)
        if number == battle.round and battle.outcome is None:
            draw.ellipse(box, fill=INK)
            ink = WHITE
        elif number < battle.round or (battle.outcome is not None and number <= battle.round):
            draw.ellipse(box, fill=CHIP)
            ink = MUTED
        else:
            draw.ellipse(box, outline=RULE, width=2)
            ink = MUTED
        draw.text(((box[0] + box[2]) / 2, (box[1] + box[3]) / 2), str(number), font=font(18), fill=ink, anchor="mm")

    # Who attacks, who defends, the advantage and the group rolling.
    y = BATTLE_PAD + 100
    x = BATTLE_PAD
    face = font(17)
    parts = []
    if battle.attacker:
        parts.append((f"{_seat_word(battle.attacker)} attacks", SEAT_COLOURS[battle.attacker]))
    if battle.defender:
        parts.append((f"{_seat_word(battle.defender)} defends", SEAT_COLOURS[battle.defender]))
    for words, colours in parts:
        draw.ellipse((x, y - 7, x + 14, y + 7), fill=colours["strong"])
        x += 22
        draw.text((x, y), words, font=face, fill=colours["ink"], anchor="lm")
        x += face.getlength(words) + 26
    extras = []
    if battle.advantage:
        extras.append(f"Scouting advantage: {_seat_word(battle.advantage['seat'])} by {battle.advantage['by']}")
    if battle.group is not None and battle.phase in (lines.DAMAGE, lines.LOSSES):
        extras.append(f"Initiative {battle.group} rolling")
    if extras:
        draw.text((x, y), " · ".join(extras), font=font(17, bold=False), fill=SOFT_INK, anchor="lm")


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
    draw.rounded_rectangle((x + 3, y + 3, x + 11, y + height - 3), radius=4, fill=type_colour)
    count_face = font(34)
    count = str(found.count)
    count_w = count_face.getlength(count)
    draw.text((x + width - 12, y + 26), count, font=count_face, fill=INK, anchor="rm")
    name_face = font(16)
    draw.text((x + 20, y + 20), _fit(unit.name, name_face, width - count_w - 40), font=name_face, fill=INK,
              anchor="lm")
    words = f"{TYPE_WORDS[unit.type]} · init {unit.initiative}" + (" · flanking" if flanking else "")
    draw.text((x + 20, y + 42), _fit(words, font(12), width - count_w - 40), font=font(12), fill=type_ink,
              anchor="lm")

    chips = []
    if found.damaged:
        chips.append((f"{found.damaged} damaged", (246, 226, 220), HIT))
    hits = battle.hits.get(ident, 0)
    if hits:
        chips.append((f"{hits} hit{'s' if hits != 1 else ''}", HIT, WHITE))
    removed = battle.removals.get(ident, 0)
    if removed:
        chips.append((f"{removed} removed", HIT, WHITE))
    leaving = battle.leaving.get(ident, 0)
    if leaving:
        chips.append((f"{leaving} retreating", CHIP, INK))
    if ident in battle.rolled:
        chips.append(("rolled", CHIP, MUTED))
    if found.count == 0:
        chips = [("destroyed", INK, WHITE)]
    cursor, row_y = x + 20, y + 64
    face = font(12)
    for words, fill, ink in chips:
        chip_w = _pill_width(words, face, 22, pad=8)
        if cursor > x + 20 and cursor + chip_w > x + width - 8:
            cursor = x + 20
            row_y += 26
        if row_y + 22 > y + height - 4:
            break
        _pill(draw, cursor, row_y, words, face, fill=fill, ink=ink, height=22, pad=8)
        cursor += chip_w + 6


def _base_card(draw, battle: BattleState, target: str, box) -> None:
    """A base card at an end of the line (TNP 6.9): attacked as
    armored, and this group's hits on it."""
    x, y, width, height = box
    colours = SEAT_COLOURS[battle.defender] if battle.defender else {"strong": INK, "base": CHIP, "ink": INK}
    draw.rounded_rectangle((x, y, x + width, y + height), radius=10, fill=colours["base"],
                           outline=colours["strong"], width=3)
    if battle.defender:
        _shield(draw, battle.defender, (x + 12, y + 12), 34)
    draw.text((x + 50, y + 22), "Base card", font=font(16), fill=colours["ink"], anchor="lm")
    draw.text((x + 50, y + 42), "left end" if target == BASE_LEFT else "right end", font=font(12, bold=False),
              fill=colours["ink"], anchor="lm")
    draw.text((x + 12, y + 66), "Armored", font=font(12), fill=TYPE_COLOURS[UnitType.ARMORED][1], anchor="lm")
    hits = battle.hits.get(target, 0)
    if hits:
        _pill(draw, x + 12, y + 82, f"{hits} hit{'s' if hits != 1 else ''}", font(12), fill=HIT, ink=WHITE,
              height=22, pad=8)


def _battle_footer_rows(catalog: Catalog, battle: BattleState) -> list[tuple[str, tuple]]:
    """The lines under the line: the base's structures, what the base
    card destroyed, the units gone home, and how it ended."""
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
