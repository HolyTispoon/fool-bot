"""
The kit's boards, each a sheet drawn in inches at 300 dpi:

- **The player board**, two letter sheets a seat laid side by side: the
  four facilities (TNP 2.4) as board v4 has them -- each with its
  production cap, its build cost or that it starts built, a queue for
  what Infrastructure places on it (TNP 5.2), every unit it builds with
  its cost, ratings, initiative, traits and supply, its unit upgrades and
  its infrastructure upgrade, each with a slot for its Built marker.
- **The deployment board**, a letter sheet a seat, behind the screen:
  attack spots A and B and three defense spots, each pile on its
  territory card (`tnpkit.territories`), the base's own spot, and the
  available units (TNP 2.5, 5.3).
- **The battle mat**, tabloid: the round track, the initiative groups,
  and the battle line's four rows -- each seat's front row and its
  flanking row -- in columns (TNP 6).
- **The track sheet**, letter: the harvest track to 49 (TNP 1.3) and
  the four base cards to cut out (TNP 6.9).

Every number is read from the catalog -- a cap, a cost, a rating, a
supply, a conversion rate -- and every rule is cited by its section.
"""

from __future__ import annotations

from typing import Optional

from PIL import Image, ImageDraw

from tnp.catalog import Catalog, Unit, UnitType
from tnp.formatting import TRAIT_NAMES
from tnp.render import (
    HIT, INK, MUTED, RATING_FILLS, RULE, SEAT_COLOURS, SOFT_INK, TYPE_COLOURS, TYPE_WORDS, WHITE, _icon,
    _shield, _wrap, font,
)
from tnpkit.paper import MARGIN, px, sheet
from tnpkit.territories import CARD

SEATS = ("blue", "green")
DASH = (141, 138, 128)
PANEL = (244, 245, 247)


def other(seat: str) -> str:
    return SEATS[1 - SEATS.index(seat)]


# -- Drawing in inches ------------------------------------------------------------

def text(draw, at, words: str, size: float, fill=INK, bold: bool = True, anchor: str = "lt") -> None:
    draw.text((px(at[0]), px(at[1])), words, font=font(px(size), bold), fill=fill, anchor=anchor)


def paragraph(draw, x: float, y: float, width: float, words: str, size: float = 0.115, fill=SOFT_INK,
              bold: bool = False, leading: float = 1.3) -> float:
    """`words` wrapped to `width` inches; the y under them, in inches."""
    face = font(px(size), bold)
    for row in _wrap(words, face, px(width)):
        draw.text((px(x), px(y)), row, font=face, fill=fill, anchor="lt")
        y += size * leading
    return y


def box(draw, x: float, y: float, w: float, h: float, outline=RULE, fill=None, radius: float = 0.08,
        width: float = 0.012) -> None:
    draw.rounded_rectangle((px(x), px(y), px(x + w), px(y + h)), radius=px(radius), fill=fill, outline=outline,
                           width=max(1, px(width)))


def dashed(draw, x: float, y: float, w: float, h: float, colour=DASH, dash: float = 0.06,
           width: float = 0.012) -> None:
    left, top, right, bottom = px(x), px(y), px(x + w), px(y + h)
    step, line = px(dash), max(1, px(width))
    for start in range(left, right, step * 2):
        end = min(start + step, right)
        draw.line((start, top, end, top), fill=colour, width=line)
        draw.line((start, bottom, end, bottom), fill=colour, width=line)
    for start in range(top, bottom, step * 2):
        end = min(start + step, bottom)
        draw.line((left, start, left, end), fill=colour, width=line)
        draw.line((right, start, right, end), fill=colour, width=line)


def marker_slot(draw, x: float, y: float, words: str, size: float = 0.8) -> None:
    """A dashed square a marker is laid on, its words inside."""
    dashed(draw, x, y, size, size)
    face = font(px(0.085), bold=False)
    rows = _wrap(words, face, px(size - 0.1))
    top = y + size / 2 - 0.06 * len(rows)
    for row in rows:
        draw.text((px(x + size / 2), px(top + 0.06)), row, font=face, fill=MUTED, anchor="mm")
        top += 0.12


def header(draw, page: Image.Image, seat: Optional[str], title: str, note: str = "") -> float:
    """A sheet's band: its seat's colour (grey for a shared sheet), its
    shield, the title and a note on the right; the y under it."""
    x, y = MARGIN, MARGIN
    w = page.width / 300 - 2 * MARGIN
    h = 0.5
    fill = SEAT_COLOURS[seat]["strong"] if seat else INK
    box(draw, x, y, w, h, outline=None, fill=fill)
    left = x + 0.15
    if seat:
        _shield(draw, seat, (px(x + 0.12), px(y + 0.07)), px(0.36))
        left = x + 0.55
    words = "THE NEW PROJECT" + (f" · {seat.upper()}" if seat else "")
    text(draw, (left, y + 0.07), words, 0.1, fill=(230, 236, 242))
    text(draw, (left, y + 0.2), title, 0.22, fill=WHITE)
    if note:
        face = font(px(0.11), bold=False)
        rows = _wrap(note, face, px(w * 0.45))
        top = y + h / 2 - 0.075 * len(rows)
        for row in rows:
            draw.text((px(x + w - 0.15), px(top)), row, font=face, fill=WHITE, anchor="rt")
            top += 0.15
    return y + h + 0.12


def plural(name: str) -> str:
    """A unit's name for more than one: "Smart Mines" already is."""
    if name.endswith("s"):
        return name
    if name.endswith("y") and name[-2:-1] not in "aeiou":
        return name[:-1] + "ies"
    return name + "s"


def cost_words(cost) -> list[tuple[str, int]]:
    parts = [("materials", cost.materials)]
    if cost.gold:
        parts.append(("gold", cost.gold))
    return parts


def draw_cost(draw, right: float, middle: float, cost, size: float = 0.16) -> float:
    """A cost, right-aligned at `right`: its materials and gold; the x
    of its left edge."""
    face = font(px(size))
    x = px(right)
    for kind, amount in reversed(cost_words(cost)):
        words = str(amount)
        x -= face.getlength(words)
        draw.text((x, px(middle)), words, font=face, fill=INK, anchor="lm")
        x -= px(size) + px(0.03)
        _icon(draw, kind, (x, px(middle) - px(size) / 2), px(size))
        x -= px(0.08)
    return x / 300


# -- The player board ------------------------------------------------------------

#: The facilities on each of a seat's two board sheets.
BOARD_SHEETS = (("barracks", "factory"), ("airport", "base_defenses"))


def render_player_board(catalog: Catalog, seat: str) -> list[Image.Image]:
    pages = []
    for number, slugs in enumerate(BOARD_SHEETS, start=1):
        page = sheet("letter", landscape=True)
        draw = ImageDraw.Draw(page)
        note = ("Lay the two sheets side by side, behind your screen. Built markers go on the dashed squares; "
                "what you place in Infrastructure goes in a facility's queue (TNP 5.2).")
        top = header(draw, page, seat, f"Player board {number} of 2", note if number == 1 else
                     "Units in a queue are finished at Production and Trade, and join your available units "
                     "(TNP 5.9).")
        width = (11 - 2 * MARGIN - 0.2) / 2
        bottom = 8.5 - MARGIN
        for index, slug in enumerate(slugs):
            x = MARGIN + index * (width + 0.2)
            end = _facility(draw, catalog, seat, slug, x, top, width, bottom - top)
            if number == len(BOARD_SHEETS) and index == 0:
                _board_legend(draw, catalog, x + 0.12, end + 0.15, width - 0.24)
            if slug == "base_defenses":
                _base_upgrades(draw, catalog, x + 0.12, end + 0.12, width - 0.24)
        pages.append(page)
    return pages


def _facility(draw, catalog: Catalog, seat: str, slug: str, x: float, y: float, w: float, h: float) -> float:
    """One facility's column; the y under its last box, in inches."""
    facility = catalog.facilities[slug]
    box(draw, x, y, w, h)
    pad = 0.12
    inner = w - 2 * pad
    left = x + pad
    text(draw, (left, y + 0.1), facility.name, 0.26)

    # Its state: built at the start, or what it costs and needs.
    if facility.built_at_start:
        state = "Built at the start."
    else:
        cost = facility.build_cost
        state = f"Build it for {cost.materials} materials"
        if facility.requires:
            state += f", once a {catalog.name(facility.requires)} was built in an earlier turn"
        state += "."
    if not facility.destructible:
        state += " A base card cannot destroy it."
    lines_y = paragraph(draw, left, y + 0.47, inner - (0.9 if not facility.built_at_start else 0), state, 0.11,
                        fill=INK)
    cap = (f"Production cap {facility.production_cap}: the most units it produces in a Production and Trade "
           f"phase, {facility.upgraded_production_cap} with its infrastructure upgrade.")
    lines_y = paragraph(draw, left, lines_y + 0.02, inner - (0.9 if not facility.built_at_start else 0), cap,
                        0.11)
    if not facility.built_at_start:
        marker_slot(draw, x + w - pad - 0.8, y + 0.1, f"{facility.name} built")
    cursor = max(lines_y, y + 0.95 if not facility.built_at_start else lines_y) + 0.05

    # The queue.
    queue_h = 0.95
    box(draw, left, cursor, inner, queue_h, outline=None, fill=PANEL)
    text(draw, (left + 0.08, cursor + 0.06), "QUEUE", 0.09, fill=MUTED)
    paragraph(draw, left + 0.6, cursor + 0.06, inner - 0.7,
              "Infrastructure places units here, up to the cap, and the Built marker of whatever is being "
              "built. At Production and Trade the units join your available units and each marker goes on "
              "its square.", 0.09, fill=MUTED)
    cursor += queue_h + 0.1

    # The units, then each unit upgrade with the units it unlocks.
    base_units = [catalog.units[unit] for unit in facility.units if catalog.units[unit].upgrade is None]
    for unit in base_units:
        cursor = _unit_row(draw, unit, left, cursor, inner) + 0.06
    if facility.unit_upgrades:
        allowed = facility.unit_upgrades_allowed
        allowed_up = facility.unit_upgrades_allowed_upgraded
        if allowed != allowed_up:
            cursor = paragraph(draw, left, cursor + 0.02, inner,
                               f"Unit upgrades: {allowed} built at a time, {allowed_up} once its infrastructure "
                               "upgrade is built (TNP 2.4).", 0.1, fill=INK) + 0.02
    for upgrade_slug in facility.unit_upgrades:
        upgrade = catalog.upgrades[upgrade_slug]
        units = [catalog.units[unit] for unit in facility.units if catalog.units[unit].upgrade == upgrade_slug]
        names = ", ".join(unit.name for unit in units)
        group_top = cursor
        dashed(draw, left, group_top, inner, 0.42 + 0.06 + 0.72 * len(units) + 0.06 * (len(units) - 1) + 0.08)
        text(draw, (left + 0.08, cursor + 0.07), f"UPGRADE: {upgrade.name.removesuffix(' Upgrade').upper()}",
             0.1, fill=MUTED)
        paragraph(draw, left + 0.08, cursor + 0.22, inner - 0.6,
                  f"Build {upgrade.cost.materials} material: the {facility.name} may build {names}.", 0.095)
        _mini_slot(draw, left + inner - 0.5, cursor + 0.04)
        cursor += 0.48
        for unit in units:
            cursor = _unit_row(draw, unit, left + 0.06, cursor, inner - 0.12) + 0.06
        cursor += 0.08

    # The infrastructure upgrade.
    upgrade = catalog.upgrades[facility.infrastructure_upgrade]
    infra_h = 0.62
    dashed(draw, left, cursor, inner, infra_h)
    text(draw, (left + 0.08, cursor + 0.07), "INFRASTRUCTURE UPGRADE", 0.1, fill=MUTED)
    paragraph(draw, left + 0.08, cursor + 0.24, inner - 0.6,
              f"Build {upgrade.cost.materials} material: {upgrade.ability.rstrip('.').lower()}.", 0.105, fill=INK)
    _mini_slot(draw, left + inner - 0.5, cursor + 0.08)
    cursor += infra_h + 0.08

    limits = catalog.board["limits"].get("deployed_together", ())
    for group in limits:
        if any(unit in facility.units for unit in group["units"]):
            names = " and ".join(plural(catalog.name(unit)) for unit in group["units"])
            cursor = paragraph(draw, left, cursor, inner,
                               f"At most {group['max']} {names} deployed together (TNP 2.4).", 0.1, fill=INK)
    return cursor


def _base_upgrades(draw, catalog: Catalog, x: float, y: float, w: float) -> float:
    """The upgrades of the base itself, of no facility -- the Command and
    Control CPU (TNP 2.4) -- each with its Built marker's slot; the y
    under them."""
    for upgrade in catalog.upgrades.values():
        if upgrade.kind != "base":
            continue
        cost = upgrade.cost
        price = f"{cost.materials} material{'s' if cost.materials != 1 else ''}"
        if cost.gold:
            price += f" and {cost.gold} gold"
        h = 0.62
        dashed(draw, x, y, w, h)
        text(draw, (x + 0.08, y + 0.07), f"BASE UPGRADE: {upgrade.name.upper()}", 0.1, fill=MUTED)
        paragraph(draw, x + 0.08, y + 0.24, w - 0.6,
                  f"Build {price}: attack spot C on your deployment board (TNP 2.5).", 0.105, fill=INK)
        _mini_slot(draw, x + w - 0.5, y + 0.08)
        y += h + 0.08
    return y


def _board_legend(draw, catalog: Catalog, x: float, y: float, w: float) -> None:
    """What the unit rows' marks mean, in the space the Airport leaves."""
    text(draw, (x, y), "Reading a unit", 0.15)
    y += 0.3
    size = 0.16
    cursor = x
    for kind, words in (("materials", "materials,"), ("gold", "gold: its cost, paid in Infrastructure (TNP 5.2).")):
        _icon(draw, kind, (px(cursor), px(y)), px(size))
        cursor += size + 0.06
        text(draw, (cursor, y + size / 2), words, 0.11, fill=INK, bold=False, anchor="lm")
        cursor += font(px(0.11), False).getlength(words) / 300 + 0.1
    y += size + 0.06
    y = paragraph(draw, x, y + 0.04, w,
                  "vs Inf, vs Arm, vs Air: what a d12 needs to hit that type: 3+ Strong, 6+ Fair, 12 Weak. "
                  "X is Poor: one die for every two units, rounded down, needing a 12. A 12 always hits and a 1 "
                  "always misses; modifiers add to the roll (TNP 4).", 0.11, fill=INK)
    y = paragraph(draw, x, y + 0.04, w,
                  "Initiative: the group a unit shoots in, 1 first. Supply: the most of that unit a player may "
                  "have, and how many counters it has (TNP 2.3).", 0.11, fill=INK)


def _mini_slot(draw, x: float, y: float) -> None:
    """A Built marker's slot at the right of an upgrade's box: smaller
    than the marker, which covers it."""
    dashed(draw, x, y, 0.42, 0.42)
    draw.text((px(x + 0.21), px(y + 0.21)), "BUILT", font=font(px(0.075), bold=False), fill=MUTED, anchor="mm")


def traits_words(unit: Unit) -> str:
    words = []
    for trait in unit.traits:
        name = TRAIT_NAMES.get(trait, trait.replace("_", " ").title())
        words.append(f"{name} {unit.scouting}" if trait == "scouting" else name)
    return ", ".join(words)


def _unit_row(draw, unit: Unit, x: float, y: float, w: float) -> float:
    """One unit, as a row: its name, type and initiative, its traits,
    its cost, its three ratings and its supply; the y under it."""
    h = 0.72
    band, ink = TYPE_COLOURS[unit.type]
    box(draw, x, y, w, h, outline=band, fill=WHITE, width=0.014)
    draw.rectangle((px(x), px(y + 0.02), px(x + 0.07), px(y + h - 0.02)), fill=band)

    ratings_w = 3 * 0.5 + 2 * 0.04
    supply_w = 0.55
    ratings_x = x + w - supply_w - ratings_w - 0.06
    name_w = ratings_x - x - 0.2
    text(draw, (x + 0.14, y + 0.06), unit.name, 0.15)
    text(draw, (x + 0.14, y + 0.27), f"{TYPE_WORDS[unit.type].upper()} · INITIATIVE {unit.initiative}", 0.085,
         fill=ink)
    traits = traits_words(unit)
    if traits:
        paragraph(draw, x + 0.14, y + 0.42, name_w - 0.55, traits, 0.09, fill=SOFT_INK, leading=1.2)
    draw_cost(draw, ratings_x - 0.08, y + 0.15, unit.cost, size=0.14)

    for index, kind in enumerate(UnitType):
        rating = unit.rating(kind)
        cx = ratings_x + index * 0.54
        box(draw, cx, y + 0.06, 0.5, h - 0.12, outline=None, fill=RATING_FILLS[rating], radius=0.04)
        middle = cx + 0.25
        label = {UnitType.INFANTRY: "vs Inf", UnitType.ARMORED: "vs Arm", UnitType.AIR: "vs Air"}[kind]
        text(draw, (middle, y + 0.15), label, 0.075, fill=SOFT_INK, anchor="mm")
        text(draw, (middle, y + 0.38), rating.shown, 0.19, anchor="mm")
        text(draw, (middle, y + 0.57), rating.value.title(), 0.07, fill=INK, bold=False, anchor="mm")

    sx = x + w - supply_w / 2 - 0.03
    text(draw, (sx, y + 0.22), "SUPPLY", 0.075, fill=MUTED, anchor="mm")
    text(draw, (sx, y + 0.45), str(unit.supply), 0.2, anchor="mm")
    return y + h


# -- The deployment board ----------------------------------------------------------

#: The territory defense spots a deployment board has: a player defends
#: at most three territories a turn, its base's spot besides, and a
#: territory its stranded units hold keeps one of the three (the author,
#: 2026-11-06).
DEFENSE_SPOTS = 3


def render_deployment_board(catalog: Catalog, seat: str) -> Image.Image:
    page = sheet("letter", landscape=True)
    draw = ImageDraw.Draw(page)
    top = header(draw, page, seat, "Deployment board",
                 "Behind your screen. Nobody sees anything of a deployment until March reveals it (TNP 5.3).")
    colours = SEAT_COLOURS[seat]
    card_w, card_h = CARD
    full = 11 - 2 * MARGIN
    gap = 0.14

    def card_slot(x: float, y: float) -> None:
        dashed(draw, x, y, card_w, card_h)
        draw.text((px(x + card_w / 2), px(y + card_h / 2)), "Territory card: the pile goes on it",
                  font=font(px(0.1), bold=False), fill=MUTED, anchor="mm")

    # The attack spots.
    spot_w, spot_h = (full - gap) / 2, 2.4
    y = top
    for index, (spot, words) in enumerate((
        ("A", "Resolves first in March: both players' A, then both players' B (TNP 5.4)."),
        ("B", "Resolves second. A player may plan an attack it cannot reach yet, in the hope that A takes "
              "the way (TNP 5.3)."),
    )):
        x = MARGIN + index * (spot_w + gap)
        box(draw, x, y, spot_w, spot_h, outline=colours["strong"], width=0.02)
        text(draw, (x + 0.12, y + 0.08), f"Attack spot {spot}", 0.2, fill=colours["ink"])
        card_slot(x + 0.12, y + 0.5)
        paragraph(draw, x + card_w + 0.28, y + 0.52, spot_w - card_w - 0.4, words, 0.1)
    y += spot_h + 0.1

    # The defense spots.
    text(draw, (MARGIN, y + 0.02), "DEFENSE SPOTS", 0.12, fill=MUTED)
    paragraph(draw, MARGIN + 1.45, y + 0.025, full - 1.45,
              f"At most {DEFENSE_SPOTS} a turn, each a territory you hold that your held territories join to "
              "your base. Stranded units keep theirs. Never attack a territory you defend (TNP 2.5).", 0.1,
              fill=INK)
    y += 0.42
    defense_w, defense_h = (full - (DEFENSE_SPOTS - 1) * gap) / DEFENSE_SPOTS, 2.2
    for index in range(DEFENSE_SPOTS):
        x = MARGIN + index * (defense_w + gap)
        box(draw, x, y, defense_w, defense_h)
        text(draw, (x + 0.12, y + 0.08), f"Defense spot {index + 1}", 0.16, fill=INK)
        card_slot(x + (defense_w - card_w) / 2, y + 0.4)
    y += defense_h + gap

    # The base's spot, and the available units.
    bottom = 8.5 - MARGIN
    base_w = defense_w
    box(draw, MARGIN, y, base_w, bottom - y, outline=colours["strong"], fill=colours["held"], width=0.02)
    text(draw, (MARGIN + 0.12, y + 0.08), "YOUR BASE", 0.14, fill=colours["ink"])
    paragraph(draw, MARGIN + 0.12, y + 0.34, base_w - 0.24,
              "Its own defense spot, besides the three. Base Defense units go here, and only here (TNP 7).",
              0.1, fill=colours["ink"])
    x = MARGIN + base_w + gap
    box(draw, x, y, 11 - MARGIN - x, bottom - y, outline=None, fill=PANEL)
    text(draw, (x + 0.12, y + 0.08), "AVAILABLE UNITS", 0.14, fill=MUTED)
    paragraph(draw, x + 0.12, y + 0.34, 11 - MARGIN - x - 0.24,
              "Units ready to deploy. Cleanup brings every unit back here but the stranded (TNP 5.10). Ground "
              "units attack along a path of held territories from your base; air units, and a stack Chopper "
              "Carriers carry, need none (TNP 5.3, 7).", 0.1, fill=SOFT_INK)
    return page


# -- The battle mat ------------------------------------------------------------------

BATTLE_COLUMNS = 11


def render_battle_mat(catalog: Catalog) -> Image.Image:
    page = sheet("tabloid", landscape=True)
    draw = ImageDraw.Draw(page)
    top = header(draw, page, None, "Battle mat",
                 "A battle is up to six rounds over one territory or a base. Each round: scouting, placing, "
                 "retreats, damage by initiative group, victory (TNP 6).")
    width = 17 - 2 * MARGIN

    # The round track and the initiative groups.
    cell = 0.8
    text(draw, (MARGIN, top + 0.02), "ROUND", 0.12, fill=MUTED)
    for index in range(6):
        x = MARGIN + 0.75 + index * (cell + 0.06)
        box(draw, x, top, cell, cell)
        text(draw, (x + cell / 2, top + cell / 2), str(index + 1), 0.3, fill=(170, 173, 180), anchor="mm")
    paragraph(draw, MARGIN + 0.75, top + cell + 0.06, 6 * (cell + 0.06),
              "After round 6 the defender wins if it still has units (TNP 6.10).", 0.115)
    groups = max(unit.initiative for unit in catalog.units.values())
    gx = MARGIN + 0.75 + 6 * (cell + 0.06) + 0.5
    text(draw, (gx, top + 0.02), "GROUP", 0.12, fill=MUTED)
    for index in range(groups):
        x = gx + 0.75 + index * (cell + 0.06)
        box(draw, x, top, cell, cell)
        text(draw, (x + cell / 2, top + cell / 2), str(index + 1), 0.3, fill=(170, 173, 180), anchor="mm")
    paragraph(draw, gx + 0.75, top + cell + 0.06, groups * (cell + 0.06),
              "Initiative 1 first. In a group the attacker rolls, then the defender; losses come off once the "
              "whole group has rolled (TNP 6.7).", 0.115)
    sx = gx + 0.75 + groups * (cell + 0.06) + 0.3
    paragraph(draw, sx, top, 17 - MARGIN - sx,
              "Scouting: each player adds its units' Scouting numbers. With an advantage of N, the other player "
              "places N forces first; with none, the defender places first (TNP 6.4, 6.5).", 0.12, fill=INK)

    # The battle line.
    y = top + cell + 0.5
    label_w = 1.25
    col_w = (width - label_w) / BATTLE_COLUMNS
    row_h = 1.42
    rows = (
        ("ATTACKER", "flanking", (232, 234, 238)),
        ("ATTACKER", "front", WHITE),
        ("DEFENDER", "front", WHITE),
        ("DEFENDER", "flanking", (232, 234, 238)),
    )
    for index, (who, which, fill) in enumerate(rows):
        ry = y + index * row_h + (0.14 if index >= 2 else 0)
        text(draw, (MARGIN, ry + 0.45), who, 0.13)
        text(draw, (MARGIN, ry + 0.66), which, 0.12, fill=SOFT_INK, bold=False)
        for column in range(BATTLE_COLUMNS):
            x = MARGIN + label_w + column * col_w
            box(draw, x + 0.03, ry + 0.03, col_w - 0.06, row_h - 0.06, outline=RULE, fill=fill, radius=0.06)
    middle = y + 2 * row_h + 0.07
    draw.line((px(MARGIN), px(middle), px(17 - MARGIN), px(middle)), fill=INK, width=px(0.02))
    y += 4 * row_h + 0.14 + 0.15

    # The modifiers and the hits.
    third = (width - 0.4) / 3
    notes = (
        ("Position and flanking", (
            "A force attacking another column takes −1 a column (TNP 6.7).",
            "A flanking force, behind a force of its own, adds +1: +1 in its own column, 0 one away, −1 two "
            "away (TNP 6.5). Base Defense units never flank.",
        )),
        ("Base cards", (
            "Defending a base, a base card stands at each end of the defender's line, a column of its own: "
            "attacked with the armored rating, never engaged, so at least −1 (TNP 6.9).",
        )),
        ("Hits", (
            "A hit removes a unit. Tough: damaged first, then removed; a damaged one takes the next hit. "
            "Repair: remove a Worker from an adjacent force to ignore a hit on a Mechanical unit. Splash: for "
            "each roll that hits, also remove an infantry unit from a force adjacent to the one hit "
            "(TNP 6.8).",
        )),
    )
    for index, (title, lines) in enumerate(notes):
        x = MARGIN + index * (third + 0.2)
        text(draw, (x, y), title, 0.17)
        ny = y + 0.3
        for words in lines:
            ny = paragraph(draw, x, ny, third, words, 0.125, fill=INK) + 0.04
    return page


# -- The track sheet -----------------------------------------------------------------

def render_track_sheet(catalog: Catalog) -> Image.Image:
    page = sheet("letter", landscape=True)
    draw = ImageDraw.Draw(page)
    total = sum(int(count) for area in catalog.areas.values() for count in area.resources.values())
    goal = total // 2 + 1
    top = header(draw, page, None, "Harvest track and base cards",
                 f"Each player's marker counts the tokens it has taken off the map: {goal} of the map's {total} "
                 "wins, checked at Cleanup (TNP 1.3).")
    columns = 10
    cell = 0.86
    # 0 to the winning count, one cell each.
    rows = -(-(goal + 1) // columns)
    left = (11 - columns * cell) / 2
    for index in range(goal + 1):
        row, column = divmod(index, columns)
        x, y = left + column * cell, top + 0.05 + row * cell
        last = index == goal
        box(draw, x + 0.02, y + 0.02, cell - 0.04, cell - 0.04, outline=HIT if last else RULE,
            fill=(250, 226, 221) if last else WHITE, radius=0.05, width=0.02 if last else 0.012)
        text(draw, (x + 0.09, y + 0.07), str(index), 0.14, fill=HIT if last else (150, 153, 160))
        if last:
            text(draw, (x + cell / 2, y + cell * 0.62), "WINS", 0.12, fill=HIT, anchor="mm")
    y = top + 0.05 + rows * cell + 0.25

    # The base cards, to cut out.
    text(draw, (left, y), "Base cards: cut out, two a player (TNP 6.9)", 0.13)
    y += 0.3
    card_w, card_h = 1.3, 2.2
    gap = (columns * cell - 4 * card_w) / 3
    for index, seat in enumerate(("blue", "blue", "green", "green")):
        x = left + index * (card_w + gap)
        _base_card(draw, seat, x, y, card_w, card_h)
    return page


def _base_card(draw, seat: str, x: float, y: float, w: float, h: float) -> None:
    colours = SEAT_COLOURS[seat]
    draw.rectangle((px(x), px(y), px(x + w), px(y + h)), fill=colours["held"], outline=(150, 152, 158),
                   width=2)
    _shield(draw, seat, (px(x + w / 2 - 0.17), px(y + 0.12)), px(0.4))
    text(draw, (x + w / 2, y + 0.65), f"{seat.upper()} BASE", 0.12, fill=colours["ink"], anchor="mm")
    text(draw, (x + w / 2, y + 0.82), "BASE CARD", 0.1, fill=colours["ink"], anchor="mm")
    paragraph(draw, x + 0.1, y + 1.0, w - 0.2,
              "Attacked with the armored rating. 2 hits from one force destroy one thing: an upgrade, then "
              "the Factory or Airport. One thing an attack.", 0.088, fill=INK, leading=1.25)
