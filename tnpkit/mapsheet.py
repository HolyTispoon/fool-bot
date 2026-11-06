"""
Map 3.3 for the table, on a tabloid sheet (and its two letter halves):
the traced outlines `tnp.render` draws the bot's map from, filled over a
dark ground so the gaps between them are the map's own lines, at
whatever size the sheet gives them.

Each territory carries its number and **what is put on it at setup** --
its resource tokens, as a pill a resource (TNP 2.1, 3) -- placed on its
widest part by the bot map's own reading (`tnp.render._fit_centre`), so
nothing is positioned by hand and a new map's outlines are drawn the
same way. The bases carry their seat's shield. A column beside the map
holds the legend and the two point contacts, which a printed map cannot
show by itself (TNP 2.1).
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from tnp.catalog import Catalog
from tnp.render import (
    INK, MUTED, RESOURCE_COLOURS, SEAT_COLOURS, SOFT_INK, WHITE, _anchor, _fit_centre, _icon, _map_bounds,
    _ordered_areas, _pill, _pill_width, _shield, _wrap, font,
)
from tnpkit.paper import MARGIN, px, sheet

RESOURCE_WORDS = {"blue_minerals": "blue minerals", "orange_minerals": "orange minerals", "gems": "gems"}

#: The map's frame, in traced pixels, around the outlines' bounds.
FRAME = 6
#: The column beside the map for the legend, in inches.
SIDE = 1.55
HEADER = 0.5


def render_map_sheet(catalog: Catalog) -> Image.Image:
    page = sheet("tabloid", landscape=True)
    draw = ImageDraw.Draw(page)
    areas = _ordered_areas(catalog)
    left, top, right, bottom = _map_bounds(areas)
    span_w, span_h = right - left + 2 * FRAME, bottom - top + 2 * FRAME

    room_w = page.width - 2 * px(MARGIN) - px(SIDE) - px(0.2)
    room_h = page.height - 2 * px(MARGIN) - px(HEADER)
    scale = min(room_w / span_w, room_h / span_h)
    map_w, map_h = span_w * scale, span_h * scale
    ox, oy = px(MARGIN), px(MARGIN) + px(HEADER)

    # The heading.
    draw.text((ox, oy - px(0.12)), "Map 3.3", font=font(px(0.34)), fill=INK, anchor="ls")
    draw.text((ox + font(px(0.34)).getlength("Map 3.3") + px(0.2), oy - px(0.14)),
              "THE NEW PROJECT", font=font(px(0.16)), fill=MUTED, anchor="ls")

    def at(point) -> tuple[float, float]:
        x, y = point
        return ox + (x - left + FRAME) * scale, oy + (y - top + FRAME) * scale

    draw.rounded_rectangle((ox, oy, ox + map_w, oy + map_h), radius=px(0.05), fill=INK)
    for area in areas:
        fill = SEAT_COLOURS[area.seat]["base"] if area.is_base else WHITE
        draw.polygon([at(point) for point in area.outline], fill=fill)

    for area in areas:
        _area_marks(draw, area, at, scale)

    _legend(draw, catalog, ox + map_w + px(0.25), oy, page.width - px(MARGIN))
    return page


def _area_marks(draw: ImageDraw.ImageDraw, area, at, scale: float) -> None:
    """An area's number, or a base's shield, over its setup tokens, on
    the area's widest part -- smaller where they would cross its border."""
    for shrink in (1.0, 0.85, 0.7, 0.55):
        rows = _rows(draw, area, shrink)
        gap = px(0.06) * shrink
        width = max(w for w, _, _ in rows)
        height = sum(h for _, h, _ in rows) + gap * (len(rows) - 1)
        clearance = px(0.06)
        centre = _fit_centre(area.outline, round((width + 2 * clearance) / scale),
                             round((height + 2 * clearance) / scale))
        if centre is not None:
            break
    else:
        centre = _anchor(area.outline)
    cx, cy = at(centre)
    y = cy - height / 2
    for row_w, row_h, painter in rows:
        painter(cx - row_w / 2, y)
        y += row_h + gap


def _rows(draw, area, shrink: float):
    rows = []
    if area.is_base:
        colours = SEAT_COLOURS[area.seat]
        shield_h = px(0.55) * shrink
        face = font(px(0.2) * shrink)
        label_w = max(face.getlength(area.seat.upper()), face.getlength("BASE"))

        def base_mark(x, y):
            middle = x + label_w / 2
            _shield(draw, area.seat, (middle - shield_h * 12 / 28, y), shield_h)
            draw.text((middle, y + shield_h + face.size * 0.75), area.seat.upper(), font=face,
                      fill=colours["ink"], anchor="mm")
            draw.text((middle, y + shield_h + face.size * 1.95), "BASE", font=face, fill=colours["ink"], anchor="mm")

        rows.append((label_w, shield_h + face.size * 2.5, base_mark))
        return rows

    face = font(px(0.62 if area.number == 1 else 0.46) * shrink)
    number = str(area.number)

    def number_mark(x, y, number=number, face=face):
        draw.text((x + face.getlength(number) / 2, y + face.size / 2), number, font=face, fill=INK, anchor="mm")

    rows.append((face.getlength(number), face.size, number_mark))
    pill_h = px(0.3) * shrink
    pill_face = font(px(0.19) * shrink)
    for kind, count in area.resources.items():
        if not count:
            continue
        words = f"{count}"
        width = _pill_width(words, pill_face, pill_h, icon=True)

        def token_mark(x, y, kind=kind, words=words):
            fill, ink = RESOURCE_COLOURS[kind]
            _pill(draw, x, y, words, pill_face, fill=WHITE, ink=ink, height=pill_h, outline=fill, icon=kind,
                  border=px(0.02))

        rows.append((width, pill_h, token_mark))
    return rows


def _legend(draw: ImageDraw.ImageDraw, catalog: Catalog, x: float, y: float, right: float) -> None:
    width = right - x
    title = font(px(0.17))
    body = font(px(0.125), bold=False)
    line = px(0.18)

    def heading(words: str, y: float) -> float:
        draw.text((x, y), words, font=title, fill=INK, anchor="lt")
        return y + px(0.3)

    def paragraph(words: str, y: float) -> float:
        for row in _wrap(words, body, width):
            draw.text((x, y), row, font=body, fill=SOFT_INK, anchor="lt")
            y += line
        return y + px(0.08)

    y = heading("Setup", y)
    icon = px(0.22)
    totals: dict[str, int] = {}
    for area in catalog.areas.values():
        for kind, count in area.resources.items():
            totals[kind] = totals.get(kind, 0) + int(count)
    for kind, words in RESOURCE_WORDS.items():
        _icon(draw, kind, (x, y), icon)
        draw.text((x + icon + px(0.08), y + icon / 2), words, font=body, fill=SOFT_INK, anchor="lm")
        y += icon + px(0.08)
    y += px(0.04)
    y = paragraph(
        f"Put each territory's tokens on it, as its pill says: {sum(totals.values())} in all. "
        "Every territory starts neutral (TNP 3).", y,
    )
    y += px(0.1)
    y = heading("Adjacent", y)
    y = paragraph("Two areas are adjacent where their borders meet.", y)
    y = paragraph("8 and 10 meet at a point, and so do 9 and 11: both pairs are adjacent.", y)
    y = paragraph("3 and 12 do not meet.", y)
    y += px(0.1)
    y = heading("Held", y)
    y = paragraph(
        "A control token on a territory says who holds it. It stays held with nobody in it, "
        "until an enemy takes it (TNP 2.1).", y,
    )
    y = paragraph("A Stranded token: that seat's units there are cut off from its base (TNP 5.7).", y)
