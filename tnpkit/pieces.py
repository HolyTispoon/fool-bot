"""
The kit's pieces, each drawn in one cell of a cut sheet
(`tnpkit.paper.cut_sheet`):

- **Unit counters**, 1 inch square, a seat's units as many as their
  supply (TNP 2.3) -- 80 a seat, one letter sheet. Each is framed in its
  seat's colour and banded in its type's, board v4's colours, with its
  name, type, initiative (the white disc) and three ratings as the d12
  numbers it needs (TNP 4.1), and its traits underneath.
- **Tokens and markers**, 3/4 inch square: the 96 resource tokens map
  3.3 holds (TNP 2.1), materials and gold, control tokens, Stranded
  tokens, damage tokens, the Built markers for the player board, each
  harvest track's markers, the battle's round and group markers, and
  each seat's target chips, which name what an attack spot attacks.

Every count is read from the data -- a unit's supply, a territory's
tokens -- or is the kit's own and says so in `TOKEN_COUNTS`.
"""

from __future__ import annotations

from typing import Optional

from PIL import Image, ImageDraw

from tnp.catalog import Catalog, Unit, UnitType
from tnp.render import (
    DAMAGE_FILL, HIT, INK, MUTED, RATING_FILLS, SEAT_COLOURS, TYPE_COLOURS, TYPE_WORDS, WHITE, _icon, _shield,
    _wrap, font,
)
from tnpkit.paper import Piece

SEATS = ("blue", "green")

#: Each resource's tint, the ground its token is printed on.
RESOURCE_TINTS = {
    "blue_minerals": (214, 233, 248),
    "orange_minerals": (252, 228, 196),
    "gems": (233, 218, 244),
}
MATERIAL_TINT = (228, 231, 235)
GOLD_TINT = (250, 236, 196)

#: A trait as a counter spells it: short, since the counter is an inch.
#: The player board spells each in full.
TRAIT_SHORT = {
    "base_defense": "Base def.",
    "mechanical": "Mech.",
    "harvest": "Harvest",
    "repair": "Repair",
    "scouting": "Scout",
    "tough": "Tough",
    "splash": "Splash",
    "transformation": "Transf.",
    "transport": "Transport",
}

#: How many of each token the kit prints. The resources are the map's
#: (read from `map.json`); the rest are the kit's own: enough for a long
#: game, and the README says a table that runs out uses anything.
TOKEN_COUNTS = {
    "materials_1": 24,
    "materials_5": 8,
    "gold_1": 16,
    "gold_5": 6,
    # Per seat: every territory held at once, and a Stranded token for
    # a third of them.
    "control": 15,
    "stranded": 6,
    # Shared: a battle's worth of damaged Tough units.
    "damage": 16,
}


def _centred(draw: ImageDraw.ImageDraw, xy, text: str, size: float, fill, bold: bool = True) -> None:
    draw.text(xy, text, font=font(size, bold), fill=fill, anchor="mm")


def _fill(tile: Image.Image, colour) -> ImageDraw.ImageDraw:
    draw = ImageDraw.Draw(tile)
    draw.rectangle((0, 0, tile.width, tile.height), fill=colour)
    return draw


# -- Unit counters -------------------------------------------------------------

def unit_traits(unit: Unit) -> str:
    words = []
    for trait in unit.traits:
        word = TRAIT_SHORT.get(trait, trait.replace("_", " ").title())
        words.append(f"{word} {unit.scouting}" if trait == "scouting" else word)
    return " · ".join(words)


def unit_counter(unit: Unit, seat: str) -> Piece:
    def draw_it(tile: Image.Image) -> None:
        size = tile.width
        k = size / 300  # drawn for 300 pixels, the inch at 300 dpi
        colours = SEAT_COLOURS[seat]
        band, band_ink = TYPE_COLOURS[unit.type]
        draw = _fill(tile, colours["strong"])
        inset = 15 * k
        inner = (inset, inset, size - inset, size - inset)
        draw.rounded_rectangle(inner, radius=10 * k, fill=WHITE)
        left, top, right, bottom = inner
        pad = 9 * k

        # The band, inset so a white edge parts it from the seat's frame
        # -- Green's infantry is green on green otherwise: the name, the
        # type, and the initiative disc.
        edge = 6 * k
        band_h = 88 * k
        draw.rounded_rectangle((left + edge, top + edge, right - edge, top + band_h), radius=7 * k, fill=band)
        disc = 50 * k
        disc_x = right - pad - disc
        disc_y = top + (band_h - disc) / 2
        draw.ellipse((disc_x, disc_y, disc_x + disc, disc_y + disc), fill=WHITE)
        _centred(draw, (disc_x + disc / 2, disc_y + disc / 2 + 1 * k), str(unit.initiative), 32 * k, band_ink)
        name_w = disc_x - left - 2 * pad
        name_face = font(27 * k)
        rows = _wrap(unit.name, name_face, name_w)
        if len(rows) > 1 or name_face.getlength(rows[0]) > name_w:
            name_face = font(22 * k)
            rows = _wrap(unit.name, name_face, name_w)[:2]
        line_h = name_face.size * 1.02
        type_size = 15 * k
        block = line_h * len(rows) + type_size + 3 * k
        y = top + edge + (band_h - edge - block) / 2
        for row in rows:
            draw.text((left + pad, y), row, font=name_face, fill=WHITE, anchor="lt")
            y += line_h
        draw.text((left + pad, y + 3 * k), TYPE_WORDS[unit.type].upper(), font=font(type_size), fill=WHITE,
                  anchor="lt")

        # The three ratings, as the d12 number each needs (TNP 4.1).
        y = top + band_h + 8 * k
        cell_h = 80 * k
        gap = 5 * k
        cell_w = (right - left - 2 * pad - 2 * gap) / 3
        for index, kind in enumerate(UnitType):
            rating = unit.rating(kind)
            x = left + pad + index * (cell_w + gap)
            draw.rounded_rectangle((x, y, x + cell_w, y + cell_h), radius=6 * k, fill=RATING_FILLS[rating])
            label = {UnitType.INFANTRY: "INF", UnitType.ARMORED: "ARM", UnitType.AIR: "AIR"}[kind]
            _centred(draw, (x + cell_w / 2, y + 15 * k), label, 17 * k, MUTED)
            _centred(draw, (x + cell_w / 2, y + 50 * k), rating.shown, 40 * k, INK)

        # The seat's shield, and the traits beside it, under the ratings.
        y = top + band_h + 8 * k + cell_h + 8 * k
        space = bottom - pad / 2 - y
        shield_h = 42 * k
        _shield(draw, seat, (left + pad, y + (space - shield_h) / 2), shield_h)
        traits = unit_traits(unit)
        if traits:
            face = font(20 * k, bold=False)
            text_left = left + pad + shield_h + 6 * k
            rows = _wrap(traits, face, right - pad - text_left)
            line_h = min(25 * k, space / max(1, len(rows)))
            y += (space - line_h * len(rows)) / 2
            for row in rows:
                draw.text(((text_left + right - pad) / 2, y + line_h / 2), row, font=face, fill=INK, anchor="mm")
                y += line_h

    return draw_it


def unit_counters(catalog: Catalog, seat: str) -> list[Piece]:
    """A seat's counters: each unit as many times as its supply, in the
    player board's order -- facility by facility."""
    pieces = []
    for facility in catalog.facilities.values():
        for slug in facility.units:
            unit = catalog.units[slug]
            pieces.extend(unit_counter(unit, seat) for _ in range(unit.supply))
    return pieces


# -- Tokens ----------------------------------------------------------------------

def resource_token(kind: str) -> Piece:
    def draw_it(tile: Image.Image) -> None:
        draw = _fill(tile, RESOURCE_TINTS[kind])
        size = tile.width * 0.62
        _icon(draw, kind, ((tile.width - size) / 2, (tile.height - size) / 2), size)

    return draw_it


def currency_token(kind: str, amount: int) -> Piece:
    def draw_it(tile: Image.Image) -> None:
        draw = _fill(tile, MATERIAL_TINT if kind == "materials" else GOLD_TINT)
        size = tile.width * 0.78
        at = ((tile.width - size) / 2, (tile.height - size) / 2)
        _icon(draw, kind, at, size)
        middle = (tile.width / 2, tile.height / 2)
        _centred(draw, middle, str(amount), tile.width * (0.42 if amount < 10 else 0.32),
                 WHITE if kind == "materials" else (110, 76, 0))
        word = "MATERIAL" if kind == "materials" and amount == 1 else kind.upper()
        _centred(draw, (tile.width / 2, tile.height * 0.93), word, tile.width * 0.075, MUTED)

    return draw_it


def control_token(seat: str) -> Piece:
    def draw_it(tile: Image.Image) -> None:
        draw = _fill(tile, SEAT_COLOURS[seat]["held"])
        height = tile.height * 0.72
        _shield(draw, seat, ((tile.width - height * 24 / 28) / 2, (tile.height - height) / 2), height)

    return draw_it


def word_token(words: tuple[str, ...], fill, ink, scale: float = 0.15) -> Piece:
    def draw_it(tile: Image.Image) -> None:
        draw = _fill(tile, fill)
        size = tile.width * scale
        face = font(size)
        widest = max(face.getlength(word) for word in words)
        if widest > tile.width * 0.86:
            size *= tile.width * 0.86 / widest
        line = size * 1.15
        y = tile.height / 2 - line * (len(words) - 1) / 2
        for word in words:
            _centred(draw, (tile.width / 2, y), word, size, ink)
            y += line

    return draw_it


def stranded_token(seat: str) -> Piece:
    return word_token(("STRANDED",), SEAT_COLOURS[seat]["strong"], WHITE)


def damage_token() -> Piece:
    return word_token(("DAMAGED",), DAMAGE_FILL, HIT)


def built_marker(seat: str) -> Piece:
    return word_token(("BUILT",), SEAT_COLOURS[seat]["held"], SEAT_COLOURS[seat]["ink"], scale=0.2)


def disc_marker(fill, ink, text: str, under: Optional[str] = None, ground=WHITE) -> Piece:
    def draw_it(tile: Image.Image) -> None:
        draw = _fill(tile, ground)
        size = tile.width * 0.74
        x, y = (tile.width - size) / 2, (tile.height - size) / 2
        draw.ellipse((x, y, x + size, y + size), fill=fill)
        _centred(draw, (tile.width / 2, tile.height / 2 - (size * 0.08 if under else 0)), text,
                 size * (0.5 if len(text) < 3 else 0.24), ink)
        if under:
            _centred(draw, (tile.width / 2, tile.height / 2 + size * 0.24), under, size * 0.13, ink)

    return draw_it


def target_chip(seat: str, target: str) -> Piece:
    """A seat's target chip: laid on an attack spot's slot, it names
    the territory -- or the enemy base -- the spot attacks."""
    colours = SEAT_COLOURS[seat]

    def draw_it(tile: Image.Image) -> None:
        draw = _fill(tile, WHITE)
        inset = tile.width * 0.07
        draw.rounded_rectangle((inset, inset, tile.width - inset, tile.height - inset), radius=tile.width * 0.1,
                               fill=WHITE, outline=colours["strong"], width=round(tile.width * 0.05))
        _centred(draw, (tile.width / 2, tile.height * 0.25), "TARGET", tile.width * 0.1, colours["ink"])
        size = 0.42 if target.isdigit() else 0.2
        _centred(draw, (tile.width / 2, tile.height * 0.58), target, tile.width * size, colours["ink"])

    return draw_it


#: Each seat's target chips: every territory and the enemy's base,
#: twice, so attack spots A and B may name the same one.
TARGETS = tuple(str(number) for number in range(1, 16)) + ("BASE",)
TARGET_SETS = 2


def harvest_marker(seat: str) -> Piece:
    colours = SEAT_COLOURS[seat]
    return disc_marker(colours["strong"], WHITE, seat.upper(), "HARVESTED", ground=colours["held"])


def round_marker() -> Piece:
    return disc_marker(INK, WHITE, "ROUND", ground=(228, 231, 235))


def group_marker() -> Piece:
    return disc_marker(INK, WHITE, "GROUP", ground=(228, 231, 235))


def resource_tokens(catalog: Catalog) -> list[Piece]:
    """The map's tokens, exactly: 40 blue minerals, 40 orange and 16
    gems on map 3.3 (TNP 2.1)."""
    totals = {kind: 0 for kind in RESOURCE_TINTS}
    for area in catalog.areas.values():
        for kind, count in area.resources.items():
            totals[kind] += int(count)
    return [resource_token(kind) for kind, count in totals.items() for _ in range(count)]


def built_markers_per_seat(catalog: Catalog) -> int:
    """Everything a seat can build onto its board: the facilities that
    do not start built, and every upgrade."""
    facilities = sum(1 for facility in catalog.facilities.values() if not facility.built_at_start)
    return facilities + len(catalog.upgrades)


def other_tokens(catalog: Catalog) -> list[Piece]:
    pieces: list[Piece] = []
    for kind in ("materials", "gold"):
        for amount in (1, 5):
            pieces.extend(currency_token(kind, amount) for _ in range(TOKEN_COUNTS[f"{kind}_{amount}"]))
    for seat in SEATS:
        pieces.extend(control_token(seat) for _ in range(TOKEN_COUNTS["control"]))
    for seat in SEATS:
        pieces.extend(stranded_token(seat) for _ in range(TOKEN_COUNTS["stranded"]))
    pieces.extend(damage_token() for _ in range(TOKEN_COUNTS["damage"]))
    for seat in SEATS:
        pieces.extend(built_marker(seat) for _ in range(built_markers_per_seat(catalog)))
    for seat in SEATS:
        pieces.append(harvest_marker(seat))
    pieces.extend((round_marker(), group_marker()))
    return pieces


def target_chips() -> list[Piece]:
    return [target_chip(seat, target) for seat in SEATS for _ in range(TARGET_SETS) for target in TARGETS]
