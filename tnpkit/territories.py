"""
Each seat's deck of territory cards: one for every territory, 1 to 15,
and one for the enemy base. A pile in an attack spot sits on the card of
what it attacks, so the card goes with the pile, as the 2018 deployment
board's "territory cards" did (docs/design/tnp-print-kit.md).

A card is 2.5 x 1.7 inches -- 18 to a letter sheet, so a deck is one --, landscape, framed in its seat's colour:
the territory's number, a small map with the territory picked out, and
what it is adjacent to and holds -- all read from `map.json`.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from tnp.catalog import Area, Catalog
from tnp.render import INK, MUTED, SEAT_COLOURS, SOFT_INK, WHITE, _icon, _map_bounds, _ordered_areas, font
from tnpkit.paper import Piece, px

SEATS = ("blue", "green")
#: The card, wide x tall, in inches.
CARD = (2.5, 1.7)

RESOURCE_WORDS = {"blue_minerals": "blue minerals", "orange_minerals": "orange minerals", "gems": "gems"}
OTHER_AREA = (232, 234, 238)


def _label(catalog: Catalog, slug: str) -> str:
    area = catalog.areas[slug]
    return str(area.number) if area.number is not None else f"{area.seat.title()} base"


def territory_card(catalog: Catalog, seat: str, area: Area) -> Piece:
    def draw_it(tile: Image.Image) -> None:
        draw = ImageDraw.Draw(tile)
        colours = SEAT_COLOURS[seat]
        k = tile.width / px(CARD[0])
        frame = px(0.07) * k
        draw.rectangle((0, 0, tile.width, tile.height), fill=colours["strong"])
        draw.rounded_rectangle((frame, frame, tile.width - frame, tile.height - frame), radius=px(0.06) * k,
                               fill=WHITE)
        pad = frame + px(0.07) * k

        # The number, or the base's name, on the left.
        left_w = px(0.85) * k
        if area.number is not None:
            draw.text((pad, pad - px(0.04) * k), str(area.number), font=font(px(0.62) * k), fill=INK, anchor="lt")
            draw.text((pad + px(0.02) * k, pad + px(0.66) * k), "TERRITORY", font=font(px(0.085) * k),
                      fill=MUTED, anchor="lt")
        else:
            base = SEAT_COLOURS[area.seat]
            draw.text((pad, pad), area.seat.upper(), font=font(px(0.2) * k), fill=base["ink"], anchor="lt")
            draw.text((pad, pad + px(0.24) * k), "BASE", font=font(px(0.2) * k), fill=base["ink"], anchor="lt")

        # The map, the territory picked out.
        _mini_map(draw, catalog, area, seat, (pad + left_w, pad, tile.width - pad, tile.height * 0.62))

        # What it is adjacent to, and what it holds.
        y = tile.height * 0.66
        face = font(px(0.095) * k, bold=False)
        bold = font(px(0.095) * k)
        adjacent = [
            _label(catalog, slug) for slug in sorted(
                area.adjacent, key=lambda s: (catalog.areas[s].number is None, catalog.areas[s].number or 0))
        ]
        draw.text((pad, y), "Adjacent", font=bold, fill=INK, anchor="lt")
        draw.text((pad + bold.getlength("Adjacent  "), y), ", ".join(adjacent), font=face, fill=SOFT_INK,
                  anchor="lt")
        y += px(0.15) * k
        held = [(kind, int(count)) for kind, count in area.resources.items() if int(count)]
        if held:
            x = pad
            icon = px(0.12) * k
            for kind, count in held:
                _icon(draw, kind, (x, y), icon)
                x += icon + px(0.04) * k
                words = f"{count} {RESOURCE_WORDS[kind]}"
                draw.text((x, y + icon / 2), words, font=face, fill=SOFT_INK, anchor="lm")
                x += face.getlength(words) + px(0.12) * k
        elif area.is_base:
            draw.text((pad, y), "A won attack here wins the game.", font=face, fill=SOFT_INK, anchor="lt")

    return draw_it


def _mini_map(draw, catalog: Catalog, picked: Area, seat: str, box) -> None:
    areas = _ordered_areas(catalog)
    left, top, right, bottom = _map_bounds(areas)
    bx0, by0, bx1, by1 = box
    scale = min((bx1 - bx0) / (right - left), (by1 - by0) / (bottom - top))
    ox = bx1 - (right - left) * scale
    oy = by0 + ((by1 - by0) - (bottom - top) * scale) / 2
    colours = SEAT_COLOURS[seat]
    for area in areas:
        if area.slug == picked.slug:
            fill = colours["strong"]
        elif area.is_base:
            fill = SEAT_COLOURS[area.seat]["base"]
        else:
            fill = OTHER_AREA
        points = [(ox + (x - left) * scale, oy + (y - top) * scale) for x, y in area.outline]
        draw.polygon(points, fill=fill, outline=WHITE, width=2)


def territory_deck(catalog: Catalog, seat: str) -> list[Piece]:
    """A seat's deck: territories 1 to 15, then the enemy base."""
    territories = sorted((a for a in catalog.areas.values() if not a.is_base), key=lambda a: a.number)
    enemy = [a for a in catalog.areas.values() if a.is_base and a.seat != seat]
    return [territory_card(catalog, seat, area) for area in territories + enemy]
