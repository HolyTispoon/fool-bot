"""
Each seat's deck of territory cards: one for every territory, 1 to 15,
and one for the enemy base. A pile in an attack spot sits on the card of
what it attacks, so the card goes with the pile, as the 2018 deployment
board's "territory cards" did (docs/design/tnp-print-kit.md).

A card is 2.5 x 3.5 inches, portrait, a playing card's size -- eight
to a letter sheet, laid on their sides, so a deck is two -- white to its edges, with the
player's shield in its corner: the territory's number, a small map with
the territory picked out, and what it is adjacent to and holds -- all
read from `map.json`.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from tnp.catalog import Area, Catalog
from tnp.render import (
    INK, MUTED, SEAT_COLOURS, SOFT_INK, WHITE, _icon, _map_bounds, _ordered_areas, _shield, _wrap, font,
)
from tnpkit.paper import Piece, px

SEATS = ("blue", "green")
#: The card, wide x tall, in inches.
CARD = (2.5, 3.5)

RESOURCE_WORDS = {"blue_minerals": "blue minerals", "orange_minerals": "orange minerals", "gems": "gems"}
OTHER_AREA = (232, 234, 238)


def _label(catalog: Catalog, slug: str) -> str:
    area = catalog.areas[slug]
    return str(area.number) if area.number is not None else f"{area.seat.title()} base"


def territory_card(catalog: Catalog, seat: str, area: Area) -> Piece:
    def draw_it(tile: Image.Image) -> None:
        draw = ImageDraw.Draw(tile)
        k = tile.width / px(CARD[0])
        # White to the edge, no frame: a cut a little off the line leaves
        # no sliver of colour. The player's shield says whose deck it is.
        draw.rectangle((0, 0, tile.width, tile.height), fill=WHITE)
        pad = px(0.16) * k
        right = tile.width - pad

        shield_h = px(0.5) * k
        _shield(draw, seat, (right - shield_h * 24 / 28, pad), shield_h)

        # The number, or the base's name.
        if area.number is not None:
            draw.text((pad, pad - px(0.06) * k), str(area.number), font=font(px(0.95) * k), fill=INK, anchor="lt")
            draw.text((pad + px(0.03) * k, pad + px(0.88) * k), "TERRITORY", font=font(px(0.13) * k),
                      fill=MUTED, anchor="lt")
        else:
            base = SEAT_COLOURS[area.seat]
            draw.text((pad, pad), area.seat.upper(), font=font(px(0.36) * k), fill=base["ink"], anchor="lt")
            draw.text((pad, pad + px(0.44) * k), "BASE", font=font(px(0.36) * k), fill=base["ink"], anchor="lt")
        y = pad + px(1.16) * k

        # The map, the territory picked out.
        map_h = px(1.25) * k
        _mini_map(draw, catalog, area, seat, (pad, y, right, y + map_h))
        y += map_h + px(0.16) * k

        # What it is adjacent to, and what it holds.
        size = px(0.15) * k
        face = font(size, bold=False)
        bold = font(size)
        adjacent = [
            _label(catalog, slug) for slug in sorted(
                area.adjacent, key=lambda s: (catalog.areas[s].number is None, catalog.areas[s].number or 0))
        ]
        draw.text((pad, y), "Adjacent", font=bold, fill=INK, anchor="lt")
        y += size * 1.3
        for row in _wrap(", ".join(adjacent), face, right - pad):
            draw.text((pad, y), row, font=face, fill=SOFT_INK, anchor="lt")
            y += size * 1.3
        y += px(0.06) * k
        held = [(kind, int(count)) for kind, count in area.resources.items() if int(count)]
        icon = px(0.17) * k
        for kind, count in held:
            _icon(draw, kind, (pad, y), icon)
            draw.text((pad + icon + px(0.06) * k, y + icon / 2), f"{count} {RESOURCE_WORDS[kind]}", font=face,
                      fill=SOFT_INK, anchor="lm")
            y += icon + px(0.07) * k
        if not held and area.is_base:
            for row in _wrap("A won attack here wins the game.", face, right - pad):
                draw.text((pad, y), row, font=face, fill=SOFT_INK, anchor="lt")
                y += size * 1.3

    return draw_it


def _mini_map(draw, catalog: Catalog, picked: Area, seat: str, box) -> None:
    areas = _ordered_areas(catalog)
    left, top, right, bottom = _map_bounds(areas)
    bx0, by0, bx1, by1 = box
    scale = min((bx1 - bx0) / (right - left), (by1 - by0) / (bottom - top))
    ox = bx0 + ((bx1 - bx0) - (right - left) * scale) / 2
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
