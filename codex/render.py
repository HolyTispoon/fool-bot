"""
The Codex bot's pictures: the board, a hand and a codex, drawn with
Pillow -- **the one module under `codex/` that imports it**
(`tests/test_model_purity.py`).

**The board is drawn element by element** (docs/codex-bot.md, decision
5 and step 7; docs/design/codex.md, "The board on Discord"), from the
author's design canvas of 2026-10-08: each player is a panel built from
the Screentop module's pieces and the cards' own art, at the pixels the
canvas was drawn at, so that less of the picture is anything but cards
and nothing is drawn for a place the position does not use. The
playmat stays imported as the reference the layout was taken from;
nothing of it is drawn but the pieces cut from it: the five patrol
slots, and a plain patch of its leather that each panel is laid on.

A panel (`render_panel`), top to bottom and left to right:

- a column of buildings on the left, 136 wide -- the add-on slot, Tech
  III, II and I, and the base, its heart carrying the HP it has now;
- the patrol zone across the top of the grid: the mat's own five slots
  with their bonuses under them, each on its own holder of the mat's
  blue, packed side by side, a patroller's card over its slot;
- the grid: square cells of 273, five columns in the basic game -- the
  count is the game's, fixed when it starts -- the command zone first
  as a plate per hero, then the heroes on the field, then the units,
  each its card at 200 by 273 with its chits, and on its side at full
  size when exhausted; rows added as the position needs them;
- the nameplate along the panel's outer edge: the player, the spec and
  hero, and the counts.

`render_board` composes two: stacked, the default -- the active
player's below, the other player's above it turned round whole so the
two patrol zones face each other, its nameplate alone kept the right
way up -- or side by side, the first player's on the left, neither
turned.

**Nothing here is tested for how it looks** (CLAUDE.md, "Nothing
rendered is tested"): `scripts/render_codex_sample.py` draws the
opening position, a mid-game one and every state on the canvas's
states board, in both layouts; look at them. Every caller renders
through `asyncio.to_thread` -- Pillow is CPU-bound and would block the
heartbeat.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Mapping, Optional, Sequence

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFont, ImageOps

from codex.cards import BOARD_IMAGE_DIR, CardCatalog, catalog as load_catalog
from codex.components import (
    PATROL_SLOTS, TECH_BUILDINGS, CardInstance, HeroState, MatchState, PlayerState,
)
from codex.engine import TECH_BUILDING_SLUGS

#: The fonts are D12 Ball's, bundled, and read by absolute path
#: (docs/design/board-image.md): Roboto Slab for every word and number.
FONT_DIR = Path(__file__).resolve().parent.parent / "d12ball" / "fonts"
#: The emoji the bot uploads, whose pictures the nameplate and an
#: exhausted card's corner borrow.
EMOJI_DIR = Path(__file__).resolve().parent / "images" / "emoji"

#: What the composed board is scaled by before it is saved: big enough
#: to read a card's name on a phone through the full-image link, small
#: enough to upload quickly on every edit.
BOARD_SCALE = 0.6
#: The WebP quality every picture is saved at. Each is mostly card art,
#: which PNG spends four to eight times the bytes on, the two hard to
#: tell apart at 1:1: the board on the mat it used to be about 2 MB
#: against 220 KB (measured 2026-10-08, with JPEG at 85 at about 340 KB
#: between them; the author chose WebP), a twelve-card codex 855 KB
#: against 168 KB and a five-card hand 419 KB against 63 KB (measured
#: 2026-10-09, the card text the same at 1:1). What the smaller file
#: buys is a shorter wait every time a picture goes up, uploaded by the
#: bot and fetched by the client: the board on every edit -- above all
#: the swap between the two layouts, where the client re-lays the
#: message out while the new picture loads -- and the hand, the codex
#: and the tech picker on every click that pictures them. The card files
#: themselves (330 by 450 JPEGs, 65 to 130 KB) are not what is sent, and
#: drawing takes a quarter of a second either way; `/codex card` alone
#: posts a card's own file as it is.
WEBP_QUALITY = 85

# -- The panel's measures, in pixels, as the canvas's plan board gives them.

#: A card: the art (330 by 450) at 61%.
CARD = (200, 273)
#: A grid cell, square so an exhausted card lies in it at full size
#: (the author, 2026-10-08: A of the canvas's three ways).
CELL = 273
#: Between two columns, two rows, and the patrol zone and the grid.
CELL_GAP = 16
#: Around the panel's edge.
PADDING = 20
#: The column of buildings, and the gap between it and the grid. The
#: column is the one-row grid's height (629), the add-on on top: every
#: building, chit and heart in it drawn at `BUILDING_SCALE` of the 160
#: wide the canvas gave it (the author, 2026-10-09: the buildings a
#: little smaller, so the column is no taller than one row).
BUILDING_WIDTH = 136
BUILDING_SCALE = BUILDING_WIDTH / 160
BUILDING_GAP = 20
#: A tech building's tile and the base's, in the art's proportions (350
#: by 250).
TILE = (136, 97)
#: The add-on's card at the top of the building column, as wide as the
#: tech buildings and aligned with them, in the art's proportions (250
#: by 350). It was 82 by 114, too small to read; a card's size beside
#: the patrol slots was too large, and the add-on stays with the other
#: buildings (the author, 2026-10-09). 193 rather than 190 so the
#: column comes out the grid's height exactly, a stretch nobody sees.
ADD_ON = (136, 193)
#: Between two places in the building column.
TILE_GAP = 12
#: A patrol slot's bonus strip, and the space above it.
BONUS = (200, 41)
BONUS_GAP = 6
#: A patrol holder's blue padding round its slot and bonus, and the
#: gap between two holders. Each slot is its own holder, packed, rather
#: than one band with the slots spread over the grid's columns (the
#: author, 2026-10-09): a patroller is never exhausted -- exhausting
#: one sidelines it -- so a slot never needs a cell's width.
PATROL_PADDING = 10
PATROL_SLOT_GAP = 12
#: A patrol holder's width.
PATROL_HOLDER = CARD[0] + 2 * PATROL_PADDING
#: A command-zone plate's hero, which lies on the plate in full.
PLATE_HERO = (184, 251)
#: The nameplate along the panel's outer edge, and the gap between it
#: and the rest.
NAMEPLATE_HEIGHT = 56
NAMEPLATE_GAP = 12
#: The stacked board's divider, and the side-by-side board's.
#: The divider is taller than the canvas's 36 so its label can be read
#: at a glance (the author, 2026-10-09: the turn more prominent).
DIVIDER_HEIGHT = 52
DIVIDER_WIDTH = 80
#: How far a chit hangs over a card's edge, which a body is drawn with
#: room for.
OVERHANG = 12

#: The columns of a panel's grid, by how many heroes the game gives a
#: player: five in the basic game, seven in the standard one (three
#: plates and four cards in the first row). The count is the game's,
#: fixed when it starts, so the picture's width holds from turn to turn
#: (the author, 2026-10-08).
COLUMNS = {1: 5, 3: 7}

# -- The palette, the canvas's.

GROUND = (21, 16, 12)            # #15100c, between the panels
PANEL = (35, 26, 20)             # #231a14
PATROL_BLUE = (36, 73, 144)      # #244990, the mat's own
PLATE_FILL = (58, 42, 28)        # #3a2a1c
PLATE_EDGE = (138, 106, 58)      # #8a6a3a
PLATE_INK = (201, 168, 106)      # #c9a86a
#: No cream anywhere (the author, 2026-10-09): the light words are a
#: neutral white and the quiet ones a neutral grey, where the canvas had
#: them warm.
WORD = (242, 242, 242)           # #f2f2f2
QUIET = (168, 168, 168)          # #a8a8a8
FAINT_INK = (138, 122, 98)       # #8a7a62
RULE = (74, 58, 44)              # #4a3a2c
#: The active nameplate's mark -- its rule and its "<name>'s turn <n>"
#: pill -- is the colour of the active player's first hero (the author,
#: 2026-10-09): the seven colours the cards come in, Neutral as tan,
#: each with the ink that reads on it, and Black with an edge, since a
#: black pill on this ground needs one (and its rule is drawn in the
#: edge, for the same reason). Keyed as `Hero.color` spells them,
#: lowered. The divider's pill is white in every game, with dark words
#: (the author, 2026-10-09: the hero's colour is the pill's alone).
#: Their first day the nameplate's were gold and the divider's teal,
#: and the author asked for both replaced: gold is the currency's, and
#: teal sat between the two patrol zones' blue -- docs/design/codex.md,
#: "The board on Discord".
TurnColors = tuple[tuple[int, int, int], tuple[int, int, int], Optional[tuple[int, int, int]]]
TURN_COLORS: dict[str, TurnColors] = {
    "neutral": ((201, 168, 106), GROUND, None),   # tan, the plates' ink
    "red": ((200, 50, 42), WORD, None),           # #c8322a
    "green": ((78, 154, 70), WORD, None),         # #4e9a46
    "blue": ((63, 127, 196), WORD, None),         # #3f7fc4
    "black": ((38, 38, 38), WORD, QUIET),         # #262626, edged grey
    "white": (WORD, GROUND, None),
    "purple": ((125, 71, 168), WORD, None),       # #7d47a8
}
DIVIDER_TURN: TurnColors = (WORD, GROUND, None)
ARRIVED_FILL = (47, 143, 78)     # #2f8f4e
HEART_FILL = (208, 32, 28)       # #d0201c
HEART_EDGE = (90, 11, 9)         # #5a0b09

# The hand's and the codex's.
INK = (242, 242, 242)
SHADOW = (12, 10, 8)
GOLD = (236, 190, 64)
STRIP_FILL = (24, 20, 16)
ACTIVE_FILL = (64, 46, 18)


# -- Loading -----------------------------------------------------------


@lru_cache(maxsize=32)
def font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    name = "RobotoSlab-Bold.ttf" if bold else "RobotoSlab-Regular.ttf"
    return ImageFont.truetype(str(FONT_DIR / name), size)


@lru_cache(maxsize=256)
def _image(path: str) -> Image.Image:
    with Image.open(path) as opened:
        return opened.convert("RGBA")


def image(path: Path) -> Image.Image:
    """A bundled picture, loaded once; a copy, so a caller may draw on it."""
    return _image(str(path)).copy()


def board_piece(*parts: str) -> Image.Image:
    return image(BOARD_IMAGE_DIR.joinpath(*parts))


def card_picture(slug: str, cards: CardCatalog) -> Image.Image:
    """A card's or a hero's own art, or the card back where it has none."""
    found = cards.by_slug(slug).picture
    if found is None or not found.exists():
        return board_piece("backs", "card.png")
    return image(found)


def fitted(picture: Image.Image, box_size: tuple[int, int]) -> Image.Image:
    """`picture` scaled to fit inside `box_size`, its proportions kept."""
    width, height = box_size
    scale = min(width / picture.width, height / picture.height)
    size = (max(1, round(picture.width * scale)), max(1, round(picture.height * scale)))
    return picture.resize(size, Image.LANCZOS)


def by_width(picture: Image.Image, width: int) -> Image.Image:
    """`picture` scaled to `width`, its proportions kept: a chit, which
    the canvas sizes by its width."""
    height = max(1, round(picture.height * width / picture.width))
    return picture.resize((width, height), Image.LANCZOS)


def rounded(picture: Image.Image, radius: int) -> Image.Image:
    """`picture` with its corners rounded off: a card's white corners,
    a tile's square ones."""
    mask = Image.new("L", picture.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, picture.width - 1, picture.height - 1),
                                           radius=radius, fill=255)
    shaped = picture.convert("RGBA")
    shaped.putalpha(ImageChops.multiply(shaped.getchannel("A"), mask))
    return shaped


def faint(picture: Image.Image, amount: float = 0.35) -> Image.Image:
    """Greyed and dimmed: an unplayable card, a card the codex has none
    of left."""
    grey = ImageEnhance.Color(picture).enhance(0.15)
    grey = ImageEnhance.Brightness(grey).enhance(amount + 0.25)
    return grey


def greyed(picture: Image.Image, brightness: float, opacity: float = 1.0) -> Image.Image:
    """Grayscale and dimmed, and see-through by `opacity`: an unbuilt
    tech building (half bright, half seen) or a destroyed one (dark)."""
    alpha = picture.getchannel("A")
    grey = ImageOps.grayscale(picture.convert("RGB")).convert("RGBA")
    grey = ImageEnhance.Brightness(grey).enhance(brightness)
    grey.putalpha(alpha.point(lambda value: round(value * opacity)))
    return grey


def dimmed(picture: Image.Image, brightness: float) -> Image.Image:
    alpha = picture.getchannel("A")
    dark = ImageEnhance.Brightness(picture.convert("RGB")).enhance(brightness).convert("RGBA")
    dark.putalpha(alpha)
    return dark


# -- Drawing helpers -----------------------------------------------------


def paste_centred(canvas: Image.Image, picture: Image.Image, box) -> tuple[int, int]:
    left = box[0] + (box[2] - box[0] - picture.width) // 2
    top = box[1] + (box[3] - box[1] - picture.height) // 2
    canvas.alpha_composite(picture, (left, top))
    return left, top


def text_centred(draw: ImageDraw.ImageDraw, centre: tuple[int, int], text: str,
                 size: int, fill=INK) -> None:
    draw.text(centre, text, font=font(size), fill=fill, anchor="mm",
              stroke_width=max(2, size // 12), stroke_fill=SHADOW)


def pill(draw: ImageDraw.ImageDraw, at: tuple[int, int], text: str, size: int,
         fill, anchor: str = "lt") -> None:
    """A word on a rounded tag: the tech picker's count of picks."""
    face = font(size)
    left, top, right, bottom = draw.textbbox(at, text, font=face, anchor=anchor)
    pad = size // 3
    draw.rounded_rectangle((left - pad, top - pad, right + pad, bottom + pad),
                           radius=pad, fill=fill, outline=SHADOW, width=2)
    draw.text(at, text, font=face, fill=INK, anchor=anchor)


def spaced_width(text: str, face: ImageFont.FreeTypeFont, spacing: float) -> int:
    return round(sum(face.getlength(char) for char in text) + spacing * max(0, len(text) - 1))


def spaced_text(draw: ImageDraw.ImageDraw, at: tuple[float, float], text: str,
                face: ImageFont.FreeTypeFont, fill, spacing: float) -> None:
    """`text` from its left middle at `at`, a letter at a time with
    `spacing` between: the canvas's tracked capitals, which Pillow
    does not track itself."""
    left, middle = at
    for char in text:
        draw.text((left, middle), char, font=face, fill=fill, anchor="lm")
        left += face.getlength(char) + spacing


def chit_stack(amount: int, folder: str, largest: int) -> list[Image.Image]:
    """The fewest of a numbered chit (`damage/1` to `damage/9`) that add
    up to `amount`, largest first."""
    chits = []
    while amount > 0:
        piece = min(amount, largest)
        chits.append(board_piece(folder, f"{piece}.png"))
        amount -= piece
    return chits


def lay_row(canvas: Image.Image, chits: Sequence[Image.Image], width: int,
            corner: tuple[int, int], *, leftward: bool = False, upward: bool = False) -> None:
    """Chits `width` across in a row from `corner` -- a top-left corner,
    or a top-right one going `leftward`, or a bottom one going `upward`
    -- each overlapping the last by a sixth."""
    left, top = corner
    for chit in chits:
        piece = by_width(chit, width)
        x = left - piece.width if leftward else left
        y = top - piece.height if upward else top
        canvas.alpha_composite(piece, (x, y))
        step = piece.width - width // 6
        left += -step if leftward else step


def damage_chits(damage: int) -> list[Image.Image]:
    return chit_stack(damage, "damage", 9)


def rune_chits(plus: int, minus: int) -> list[Image.Image]:
    """A unit's or a hero's +1/+1 and -1/-1 runes, as the module's chits."""
    return ([board_piece("chits", "plus_rune.png")] * plus
            + [board_piece("chits", "minus_rune.png")] * minus)


def level_chit(hero: HeroState, cards: CardCatalog) -> Image.Image:
    card = cards.heroes[hero.slug]
    if hero.level >= card.max_level:
        return board_piece("levels", "max.png")
    if hero.level == 1:
        return board_piece("chits", "level_1.png")
    return board_piece("levels", f"{hero.level}.png")


def time_rune_chit(runes: int) -> Image.Image:
    return board_piece("time_runes", f"{min(runes, 6)}.png")


def arrived_tag(canvas: Image.Image, card_left: int, card_bottom: int) -> None:
    """ARRIVED on a green tag against the card's left edge, 44 above its
    foot: what came this turn."""
    draw = ImageDraw.Draw(canvas)
    face = font(14)
    width = spaced_width("ARRIVED", face, 0.5) + 20
    height = 24
    bottom = card_bottom - 44
    box = (card_left, bottom - height, card_left + width, bottom)
    draw.rounded_rectangle(box, radius=8, fill=ARRIVED_FILL,
                           corners=(False, True, True, False))
    spaced_text(draw, (card_left + 10, bottom - height / 2), "ARRIVED", face, WORD, 0.5)


# -- A card as it lies ---------------------------------------------------------


@dataclass(frozen=True)
class Lying:
    """What the board shows on one card: its art and every mark on it."""

    slug: str
    level: Optional[Image.Image] = None
    damage: int = 0
    plus_runes: int = 0
    minus_runes: int = 0
    partnered: bool = False
    arrived: bool = False
    exhausted: bool = False


def unit_lying(card: CardInstance, partnered: bool) -> Lying:
    return Lying(card.slug, damage=card.damage, plus_runes=card.plus_runes,
                 minus_runes=card.minus_runes, partnered=partnered,
                 arrived=card.arrived_this_turn, exhausted=card.exhausted)


def hero_lying(hero: HeroState, cards: CardCatalog) -> Lying:
    return Lying(hero.slug, level=level_chit(hero, cards), damage=hero.damage,
                 plus_runes=hero.plus_runes, minus_runes=hero.minus_runes,
                 arrived=hero.arrived_this_turn, exhausted=hero.exhausted)


def card_face(slug: str, cards: CardCatalog, size: tuple[int, int] = CARD) -> Image.Image:
    return rounded(card_picture(slug, cards).convert("RGBA").resize(size, Image.LANCZOS),
                   round(size[0] / 20))


def lying_card(lying: Lying, cards: CardCatalog) -> Image.Image:
    """
    One card as it lies in a cell, on a transparent square of `CELL`
    with `OVERHANG` round it, the card's centre the square's: its own
    art at 200 by 273, a level chit top left (a hero), its rune chits
    top right, its damage over the stats at the foot, Two Step's chit on
    a dance partner, ARRIVED the turn it came -- and, exhausted, the
    whole of it turned on its side at full size, lying across the cell,
    with the exhaust glyph on the cell's top corner, the right way up.
    """
    margin = OVERHANG
    upright = Image.new("RGBA", (CARD[0] + 2 * margin, CARD[1] + 2 * margin), (0, 0, 0, 0))
    face = card_face(lying.slug, cards)
    if lying.exhausted:
        face = dimmed(face, 0.75)
    upright.alpha_composite(face, (margin, margin))
    right, bottom = margin + CARD[0], margin + CARD[1]
    if lying.level is not None:
        lay_row(upright, [lying.level], 62, (margin - 10, margin - 10))
    runes = rune_chits(lying.plus_runes, lying.minus_runes)
    if runes:
        lay_row(upright, runes, 50, (right + 8, margin - 8), leftward=True)
    if lying.damage:
        lay_row(upright, damage_chits(lying.damage), 62, (right + 8, bottom + 8),
                leftward=True, upward=True)
    if lying.partnered:
        lay_row(upright, [board_piece("chits", "two_step.png")], 50, (margin - 8, bottom + 8),
                upward=True)
    if lying.arrived:
        arrived_tag(upright, margin, bottom)

    tile = Image.new("RGBA", (CELL + 2 * margin, CELL + 2 * margin), (0, 0, 0, 0))
    if not lying.exhausted:
        paste_centred(tile, upright, (0, 0, tile.width, tile.height))
        return tile
    # Turned a quarter clockwise, as a card is exhausted on a table.
    paste_centred(tile, upright.transpose(Image.ROTATE_270), (0, 0, tile.width, tile.height))
    glyph = by_width(image(EMOJI_DIR / "exhaust.png"), 48)
    tile.alpha_composite(glyph, (margin + 8, margin + 8))
    return tile


def command_zone_plate(hero: Optional[HeroState], cards: CardCatalog) -> Image.Image:
    """
    A command-zone plate filling its cell, on the same square as
    `lying_card`: dark, edged, labelled -- with the hero lying on it in
    full while off the field, and its time-rune chit for its summoning
    runes; empty while the hero is on the field.
    """
    margin = OVERHANG
    tile = Image.new("RGBA", (CELL + 2 * margin, CELL + 2 * margin), (0, 0, 0, 0))
    draw = ImageDraw.Draw(tile)
    draw.rounded_rectangle((margin, margin, margin + CELL - 1, margin + CELL - 1), radius=14,
                           fill=PLATE_FILL, outline=PLATE_EDGE, width=2)
    face = font(12, bold=False)
    label = "COMMAND ZONE"
    spaced_text(draw, (margin + (CELL - spaced_width(label, face, 1.5)) / 2, margin + 15),
                label, face, PLATE_INK, 1.5)
    if hero is None:
        return tile
    picture = card_face(hero.slug, cards, PLATE_HERO)
    left = margin + (CELL - PLATE_HERO[0]) // 2
    top = margin + (CELL - PLATE_HERO[1]) // 2 + 9
    tile.alpha_composite(picture, (left, top))
    if hero.summoning_runes:
        lay_row(tile, [time_rune_chit(hero.summoning_runes)], 54, (margin - 8, margin - 8))
    return tile


# -- The buildings -----------------------------------------------------------


def heart(number: int, size: float = 1.0) -> Image.Image:
    """The base's heart, red and edged as the tile prints its own, with
    `number` on it: drawn, since the number changes (the tile prints 20).
    The canvas's path, a cubic Bezier at a time, drawn four times over
    and scaled down for a smooth edge; `size` times 68 by 64."""
    scale = 4
    width, height = round(68 * size), round(64 * size)
    sx, sy = width / 64 * scale, height / 60 * scale

    def curve(p0, p1, p2, p3, steps=24):
        for step in range(1, steps + 1):
            t = step / steps
            u = 1 - t
            yield (u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
                   u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1])

    points = [(32, 58), (6, 30)]
    points += curve((6, 30), (-2, 20), (6, 4), (20, 6))
    points += curve((20, 6), (26, 7), (30, 11), (32, 15))
    points += curve((32, 15), (34, 11), (38, 7), (44, 6))
    points += curve((44, 6), (58, 4), (66, 20), (58, 30))
    points.append((32, 58))
    pad = 3 * scale
    big = Image.new("RGBA", (width * scale + 2 * pad, height * scale + 2 * pad), (0, 0, 0, 0))
    ImageDraw.Draw(big).polygon([(x * sx + pad, y * sy + pad) for x, y in points],
                                fill=HEART_FILL, outline=HEART_EDGE, width=3 * scale)
    shape = big.resize((big.width // scale, big.height // scale), Image.LANCZOS)
    ImageDraw.Draw(shape).text((shape.width / 2, shape.height / 2 - 4 * size), str(number),
                               font=font(round(30 * size)), fill=(255, 255, 255), anchor="mm")
    return shape


def building_tile(slug: str) -> Image.Image:
    return rounded(board_piece("buildings", f"{slug}.png").resize(TILE, Image.LANCZOS),
                   round(10 * BUILDING_SCALE))


def draw_building_column(body: Image.Image, player: PlayerState,
                         building_hp: Mapping[str, int], left: int, bottom: int) -> None:
    """
    The column of buildings, bottom-aligned from `bottom`, top to
    bottom: the add-on slot (`draw_add_on`), Tech III, II and I, the
    base. A tech
    building is greyed and half seen until built, in colour once built,
    the house chit on a top corner while under construction (UMR p. 8),
    dark with the house chit when destroyed, a damage chit on a damaged
    one. The base's heart carries the HP it has now.
    """
    house = board_piece("chits", "house.png")
    top = bottom - BUILDING_COLUMN_HEIGHT
    draw_add_on(body, player, building_hp, left, top)
    y = top + ADD_ON[1] + TILE_GAP
    for name in reversed(TECH_BUILDINGS):
        state = player.buildings.get(name)
        tile = building_tile(TECH_BUILDING_SLUGS[name])
        if state is None:
            tile = greyed(tile, 0.55, 0.5)
        elif state.destroyed:
            tile = greyed(tile, 0.35)
        body.alpha_composite(tile, (left, y))
        if state is not None and (state.destroyed or state.under_construction):
            lay_row(body, [house], HOUSE_CHIT, (left - CHIT_OUT, y - CHIT_OUT))
        if state is not None and not state.destroyed:
            damage = building_hp[name] - state.hp
            if damage > 0:
                lay_row(body, damage_chits(damage), DAMAGE_CHIT,
                        (left + TILE[0] + CHIT_OUT, y - CHIT_OUT), leftward=True)
        y += TILE[1] + TILE_GAP

    base = building_tile("base")
    body.alpha_composite(base, (left, y))
    mark = heart(player.base_hp, BUILDING_SCALE)
    body.alpha_composite(mark, (left + TILE[0] - round(79 * BUILDING_SCALE),
                                y + round(19 * BUILDING_SCALE)))


#: A building's house and damage chits, and how far they hang over its
#: corner, at the column's scale.
HOUSE_CHIT = round(50 * BUILDING_SCALE)
DAMAGE_CHIT = round(54 * BUILDING_SCALE)
CHIT_OUT = round(8 * BUILDING_SCALE)


BUILDING_COLUMN_HEIGHT = ADD_ON[1] + 4 * TILE[1] + 4 * TILE_GAP


def draw_add_on(body: Image.Image, player: PlayerState,
                building_hp: Mapping[str, int], left: int, top: int) -> None:
    """
    The add-on slot, its top left at (`left`, `top`): a dashed outline,
    or the add-on's card -- the house chit on its top corner while under
    construction, a damage chit on a damaged one, as a tech building's.
    """
    slot = (left, top, left + ADD_ON[0], top + ADD_ON[1])
    add_on = player.add_on
    if add_on is None:
        draw = ImageDraw.Draw(body)
        dashed_box(draw, slot, FAINT_INK)
        draw.text(((slot[0] + slot[2]) / 2, (slot[1] + slot[3]) / 2), "Add-on",
                  font=font(18, bold=False), fill=FAINT_INK, anchor="mm")
        return
    card = rounded(board_piece("buildings", f"{add_on.slug}.png").resize(ADD_ON, Image.LANCZOS),
                   round(ADD_ON[0] / 20))
    body.alpha_composite(card, slot[:2])
    if add_on.under_construction:
        lay_row(body, [board_piece("chits", "house.png")], HOUSE_CHIT,
                (slot[0] - CHIT_OUT, slot[1] - CHIT_OUT))
    damage = building_hp.get(add_on.slug, add_on.hp) - add_on.hp
    if damage > 0:
        lay_row(body, damage_chits(damage), DAMAGE_CHIT,
                (slot[2] + CHIT_OUT, slot[1] - CHIT_OUT), leftward=True)


def dashed_box(draw: ImageDraw.ImageDraw, box, fill, dash: int = 6, width: int = 2) -> None:
    left, top, right, bottom = box
    for x in range(left, right, dash * 2):
        draw.line((x, top, min(x + dash, right), top), fill=fill, width=width)
        draw.line((x, bottom - 1, min(x + dash, right), bottom - 1), fill=fill, width=width)
    for y in range(top, bottom, dash * 2):
        draw.line((left, y, left, min(y + dash, bottom)), fill=fill, width=width)
        draw.line((right - 1, y, right - 1, min(y + dash, bottom)), fill=fill, width=width)


# -- One player's panel -------------------------------------------------------------


def partner_ids(player: PlayerState) -> set[int]:
    """The ids Two Step has partnered on this side: each carries the
    module's Two Step chit."""
    return {
        partner for card in player.play if card.slug == "two_step" for partner in card.attached
    }


def heroes(player: PlayerState) -> list[HeroState]:
    """A player's heroes: one in the basic game, three in the standard
    one once it is played."""
    return [player.hero]


def panel_columns(player: PlayerState) -> int:
    """The grid's column count, the game's -- by how many heroes it gives
    a player, so it is fixed when the game starts."""
    return COLUMNS.get(len(heroes(player)), COLUMNS[3])


def panel_width(columns: int) -> int:
    return (2 * PADDING + BUILDING_WIDTH + BUILDING_GAP
            + columns * CELL + (columns - 1) * CELL_GAP)


def grid_cells(player: PlayerState, cards: CardCatalog) -> list[Image.Image]:
    """The grid, in order: a command-zone plate per hero, then the
    heroes on the field, then the units, every one not patrolling."""
    plates = [command_zone_plate(None if hero.in_play else hero, cards)
              for hero in heroes(player)]
    field = [lying_card(hero_lying(hero, cards), cards)
             for hero in heroes(player) if hero.in_play and hero.patrol_slot is None]
    partners = partner_ids(player)
    units = [lying_card(unit_lying(card, card.id in partners), cards)
             for card in player.play if card.patrol_slot is None]
    return plates + field + units


PATROL_HEIGHT = 2 * PATROL_PADDING + CARD[1] + BONUS_GAP + BONUS[1]


def body_height(cells: int, columns: int) -> int:
    rows = max(1, -(-cells // columns))
    grid = PATROL_HEIGHT + CELL_GAP + rows * CELL + (rows - 1) * CELL_GAP
    return max(grid, BUILDING_COLUMN_HEIGHT)


def render_body(match: MatchState, seat: int, cards: CardCatalog,
                building_hp: Mapping[str, int]) -> Image.Image:
    """
    One panel's body, the nameplate aside, on a transparent ground with
    `OVERHANG` round it for the chits that hang over an edge -- so the
    far panel's is turned round whole about its own centre.
    """
    player = match.player(seat)
    columns = panel_columns(player)
    cells = grid_cells(player, cards)
    inner_width = panel_width(columns) - 2 * PADDING
    height = body_height(len(cells), columns)
    body = Image.new("RGBA", (inner_width + 2 * OVERHANG, height + 2 * OVERHANG), (0, 0, 0, 0))
    o = OVERHANG
    draw_building_column(body, player, building_hp, o, o + height)

    grid_left = o + BUILDING_WIDTH + BUILDING_GAP
    draw = ImageDraw.Draw(body)
    partners = partner_ids(player)
    card_top = o + PATROL_PADDING
    holder_left = grid_left - PATROL_PADDING
    for slot in PATROL_SLOTS:
        # Each slot on its own holder, packed against the last.
        draw.rounded_rectangle(
            (holder_left, o, holder_left + PATROL_HOLDER - 1, o + PATROL_HEIGHT - 1),
            radius=14, fill=PATROL_BLUE,
        )
        card_left = holder_left + PATROL_PADDING
        holder_left += PATROL_HOLDER + PATROL_SLOT_GAP
        body.alpha_composite(rounded(board_piece("patrol_slots", f"{slot}.png"), 12),
                             (card_left, card_top))
        body.alpha_composite(board_piece("patrol_slots", f"{slot}_bonus.png"),
                             (card_left, card_top + CARD[1] + BONUS_GAP))
        ref = player.patroller(slot)
        if ref is None:
            continue
        if ref == "hero":
            lying = hero_lying(player.hero, cards)
        else:
            instance_id = int(ref.split(":", 1)[1])
            lying = unit_lying(match.instance(instance_id), instance_id in partners)
        # The patroller covers its slot, chits and all; the bonus stays
        # printed under it.
        paste_centred(body, lying_card(lying, cards),
                      (card_left, card_top, card_left + CARD[0], card_top + CARD[1]))

    top = o + PATROL_HEIGHT + CELL_GAP
    for index, cell in enumerate(cells):
        row, column = divmod(index, columns)
        left = grid_left + column * (CELL + CELL_GAP)
        cell_top = top + row * (CELL + CELL_GAP)
        body.alpha_composite(cell, (left - OVERHANG, cell_top - OVERHANG))
    return body


def hero_name(hero: HeroState, cards: CardCatalog) -> str:
    return cards.heroes[hero.slug].name


def turn_label(match: MatchState, name: str) -> str:
    """"<name>'s turn <n>", `name` the active player's as the frontend
    names them -- "perrytom's turn 7". The player and not a hero,
    since a standard game's deck has three (the author, 2026-10-09)."""
    return f"{name}'s turn {match.turn}"


def is_to_act(match: MatchState, seat: int) -> bool:
    return match.active == seat and match.winner is None


def turn_colors(match: MatchState, cards: CardCatalog) -> TurnColors:
    """The fill, the ink and the edge of the active nameplate's mark:
    the colour of the active player's first hero -- Neutral's tan for a
    Bashing deck, Red's red for a Fire one."""
    player = match.player(match.active)
    hero = cards.hero_for(player.specs[0])
    return TURN_COLORS[(hero.color or "neutral").strip().lower()]


def turn_pill(draw: ImageDraw.ImageDraw, box: tuple[float, float, float, float],
              radius: int, colors: TurnColors) -> None:
    """The rounded tag behind a turn's words, edged where its colour
    needs one."""
    fill, _, edge = colors
    draw.rounded_rectangle(box, radius=radius, fill=fill,
                           outline=edge, width=2 if edge else 0)


def render_nameplate(match: MatchState, seat: int, name: str, cards: CardCatalog,
                     width: int, rule_at_top: bool,
                     ground: Optional[Image.Image] = None) -> Image.Image:
    """
    The nameplate, 56 tall: the player, the spec and hero, then gold
    (the gold emoji's picture), workers, hand, deck, discard and codex,
    a word and a count each. The active player's carries a rule and
    "<name>'s turn <n>" in a pill, both in its first hero's colour
    (`turn_colors`). The rule is on the side the rest of the panel is
    on. Drawn straight onto `ground`, the piece of
    leather it lies on, so its words are smoothed against the leather.
    """
    player = match.player(seat)
    plate = (ground.copy() if ground is not None
             else Image.new("RGBA", (width, NAMEPLATE_HEIGHT), PANEL))
    draw = ImageDraw.Draw(plate)
    to_act = is_to_act(match, seat)
    colors = turn_colors(match, cards) if to_act else None
    rule = (colors[2] or colors[0]) if colors else RULE
    rule_y = 0 if rule_at_top else NAMEPLATE_HEIGHT - 3
    draw.rectangle((0, rule_y, width, rule_y + 2), fill=rule)
    middle = NAMEPLATE_HEIGHT / 2 + (1.5 if rule_at_top else -1.5)

    x = 0
    draw.text((x, middle), name, font=font(26), fill=WORD, anchor="lm")
    x += font(26).getlength(name) + 18
    spec = f"{player.spec.title()} · {hero_name(player.hero, cards)}"
    draw.text((x, middle), spec, font=font(18, bold=False), fill=QUIET, anchor="lm")
    x += font(18, bold=False).getlength(spec) + 18
    if colors:
        label = turn_label(match, name)
        face = font(15)
        pill_width = face.getlength(label) + 24
        turn_pill(draw, (x, middle - 13, x + pill_width, middle + 13), 10, colors)
        draw.text((x + 12, middle), label, font=face, fill=colors[1], anchor="lm")

    counts = (
        ("WORKERS", player.workers), ("HAND", len(player.hand)), ("DECK", len(player.deck)),
        ("DISCARD", len(player.discard)), ("CODEX", sum(player.codex.values())),
    )
    number, word = font(20), font(15, bold=False)
    right = width
    for label, count in reversed(counts):
        text = str(count)
        draw.text((right, middle), text, font=number, fill=WORD, anchor="rm")
        right -= number.getlength(text) + 6
        draw.text((right, middle), label, font=word, fill=QUIET, anchor="rm")
        right -= word.getlength(label) + 18
    text = str(player.gold)
    draw.text((right, middle), text, font=number, fill=WORD, anchor="rm")
    right -= number.getlength(text) + 6
    coin = by_width(image(EMOJI_DIR / "gold.png"), 26)
    plate.alpha_composite(coin, (round(right - coin.width), round(middle - coin.height / 2)))
    return plate


def render_panel(match: MatchState, seat: int, name: str,
                 cards: Optional[CardCatalog] = None,
                 building_hp: Optional[Mapping[str, int]] = None, *,
                 turned: bool = False, height: Optional[int] = None) -> Image.Image:
    """
    One player as a panel: the body -- the buildings, the patrol zone,
    the grid -- and the nameplate along the panel's outer edge, below
    it. `turned`, the body is turned round whole to face the other way,
    as the far side of a table is, and the nameplate is above it, still
    the right way up: a name and its counts nobody should have to turn
    a phone for. `height`, where taller than the panel needs, is filled
    between the body and the nameplate, which stays on the outer edge.
    """
    cards = cards or load_catalog()
    building_hp = building_hp or default_building_hp(cards)
    body = render_body(match, seat, cards, building_hp)
    width = body.width - 2 * OVERHANG + 2 * PADDING
    natural = (2 * PADDING + body.height - 2 * OVERHANG + NAMEPLATE_GAP + NAMEPLATE_HEIGHT)
    total = max(natural, height or 0)
    # Laid out the right way up on the leather, then, for the far side,
    # turned round whole -- leather and all, so it reads as one mat
    # turned rather than a turned patch on an upright one.
    panel = leather_ground((width, total))
    panel.alpha_composite(body, (PADDING - OVERHANG, PADDING - OVERHANG))
    if turned:
        panel = panel.rotate(180)
    plate_top = PADDING if turned else total - PADDING - NAMEPLATE_HEIGHT
    box = (PADDING, plate_top, width - PADDING, plate_top + NAMEPLATE_HEIGHT)
    plate = render_nameplate(match, seat, name, cards, width - 2 * PADDING,
                             rule_at_top=not turned, ground=panel.crop(box))
    panel.alpha_composite(plate, box[:2])
    return panel


@lru_cache(maxsize=1)
def leather_tile() -> Image.Image:
    """The mat's leather -- a plain patch of it cut from the playmat
    (`ground/leather.png`) -- mirrored across and down into a tile whose
    edges meet themselves, so it repeats with no seam."""
    patch = board_piece("ground", "leather.png")
    row = Image.new("RGBA", (patch.width * 2, patch.height))
    row.paste(patch, (0, 0))
    row.paste(ImageOps.mirror(patch), (patch.width, 0))
    tile = Image.new("RGBA", (row.width, row.height * 2))
    tile.paste(row, (0, 0))
    tile.paste(ImageOps.flip(row), (0, row.height))
    return tile


def leather_ground(size: tuple[int, int]) -> Image.Image:
    """A panel's ground, `size`, the leather tiled from its top left
    (the author, 2026-10-09: leather, so long as the board does not load
    much slower -- it costs about a fifth more bytes)."""
    tile = leather_tile()
    ground = Image.new("RGBA", size)
    for left in range(0, size[0], tile.width):
        for top in range(0, size[1], tile.height):
            ground.paste(tile, (left, top))
    return ground


def default_building_hp(cards: CardCatalog) -> dict[str, int]:
    """Each building's full HP, from the card data: what its damage chits
    are counted against."""
    found = {name: cards.building(slug).hp or 0 for name, slug in TECH_BUILDING_SLUGS.items()}
    for slug in ("tower", "surplus"):
        found[slug] = cards.building(slug).hp or 0
    found["base"] = 20
    return found


# -- The board ---------------------------------------------------------------


def _webp(picture: Image.Image) -> bytes:
    """Every picture's encoding -- see `WEBP_QUALITY`."""
    buffer = io.BytesIO()
    picture.convert("RGB").save(buffer, format="WEBP", quality=WEBP_QUALITY)
    return buffer.getvalue()


def stacked_seats(match: MatchState) -> tuple[int, int]:
    """
    The stacked board's two seats as (far, near). The table is looked
    at from the active player's side (the author, 2026-10-08): their
    panel is the near one, at the bottom, and the other player's the far
    one, above it and turned to face them. A game that is over is
    looked at from where it was left.
    """
    near = match.active
    return (2 if near == 1 else 1), near


def divider_label(match: MatchState, name: str) -> str:
    return turn_label(match, name).upper()


def horizontal_divider(width: int, label: str) -> Image.Image:
    """
    The stacked board's divider: "<NAME>'S TURN <N>", the active player
    by name, bold and dark on a white pill (`DIVIDER_TURN`) between two
    rules, so whose turn it is reads at a glance (the author,
    2026-10-09: more prominent, and neither gold nor cream).
    """
    strip = Image.new("RGBA", (width, DIVIDER_HEIGHT), GROUND)
    draw = ImageDraw.Draw(strip)
    face = font(24)
    text_width = spaced_width(label, face, 2)
    middle = DIVIDER_HEIGHT // 2
    left = (width - text_width) / 2
    pad, half = 18, 18
    draw.line((0, middle, left - pad - 14, middle), fill=QUIET, width=2)
    draw.line((left + text_width + pad + 14, middle, width, middle), fill=QUIET, width=2)
    turn_pill(draw, (left - pad, middle - half, left + text_width + pad, middle + half),
              half, DIVIDER_TURN)
    spaced_text(draw, (left, middle), label, face, DIVIDER_TURN[1], 2)
    return strip


def vertical_divider(height: int, label: str) -> Image.Image:
    """The side-by-side board's, 80 wide: the same, standing, read top
    to bottom."""
    lying = Image.new("RGBA", (height, DIVIDER_WIDTH), GROUND)
    lying.alpha_composite(horizontal_divider(height, label),
                          (0, (DIVIDER_WIDTH - DIVIDER_HEIGHT) // 2))
    return lying.transpose(Image.ROTATE_270)


def compose_board(match: MatchState, layout: str = "stacked",
                  names: Optional[Mapping[int, str]] = None,
                  cards: Optional[CardCatalog] = None,
                  near: Optional[int] = None) -> Image.Image:
    """The whole table at the canvas's pixels, before it is scaled and
    encoded -- `render_board`'s picture. `near`, for the stacked board,
    is the seat looked from: the active player's by default."""
    cards = cards or load_catalog()
    names = names or {}
    building_hp = default_building_hp(cards)

    def name(seat: int) -> str:
        return names.get(seat) or f"Player {seat}"

    label = divider_label(match, name(match.active))

    if layout == "side_by_side":
        first = match.first
        second = 2 if first == 1 else 1
        natural = [render_panel(match, seat, name(seat), cards, building_hp)
                   for seat in (first, second)]
        height = max(panel.height for panel in natural)
        left, right = (render_panel(match, seat, name(seat), cards, building_hp, height=height)
                       if panel.height < height else panel
                       for seat, panel in zip((first, second), natural))
        board = Image.new("RGBA", (left.width + DIVIDER_WIDTH + right.width, height), GROUND)
        board.alpha_composite(left, (0, 0))
        board.alpha_composite(vertical_divider(height, label), (left.width, 0))
        board.alpha_composite(right, (left.width + DIVIDER_WIDTH, 0))
        return board

    far_seat, near_seat = stacked_seats(match)
    if near is not None:
        far_seat, near_seat = (2 if near == 1 else 1), near
    far = render_panel(match, far_seat, name(far_seat), cards, building_hp, turned=True)
    near = render_panel(match, near_seat, name(near_seat), cards, building_hp)
    width = max(far.width, near.width)
    board = Image.new("RGBA", (width, far.height + DIVIDER_HEIGHT + near.height), GROUND)
    board.alpha_composite(far, ((width - far.width) // 2, 0))
    board.alpha_composite(horizontal_divider(width, label), (0, far.height))
    board.alpha_composite(near, ((width - near.width) // 2, far.height + DIVIDER_HEIGHT))
    return board


def render_board(match: MatchState, layout: str = "stacked",
                 names: Optional[Mapping[int, str]] = None,
                 cards: Optional[CardCatalog] = None,
                 near: Optional[int] = None) -> bytes:
    """
    The whole table as WebP bytes: both panels, stacked -- seen from the
    active player's side, the other player's above theirs and turned
    round to face them, a divider between naming whose turn it is -- or
    side by side, the first player's on the left, neither turned, as
    `layout` says. `names` is what each seat's nameplate calls its
    player -- the frontend's to give, since a name is not the model's.
    The picture's size follows the position: a row of cards more is a
    taller panel. `near` looks at the stacked board from that seat
    rather than the active player's: a target prompt's picture where the
    targets are on both sides, seen from the player choosing.
    """
    board = compose_board(match, layout, names, cards, near)
    scaled = board.resize(
        (round(board.width * BOARD_SCALE), round(board.height * BOARD_SCALE)), Image.LANCZOS,
    )
    return _webp(scaled)


def render_side(match: MatchState, seat: int, name: str,
                cards: Optional[CardCatalog] = None) -> bytes:
    """
    One player's side of the table as WebP bytes, upright and at the
    board's scale: the panel `render_board` draws for `seat`, alone. A
    target prompt's picture (docs/design/codex.md, "The panel"), where
    what is chosen from is on the board rather than in the hand.
    """
    cards = cards or load_catalog()
    panel = render_panel(match, seat, name, cards, default_building_hp(cards))
    scaled = panel.resize(
        (round(panel.width * BOARD_SCALE), round(panel.height * BOARD_SCALE)), Image.LANCZOS,
    )
    return _webp(scaled)


# -- A hand, a codex -----------------------------------------------------------


#: A card in a hand or a codex picture, in pixels.
HAND_CARD = (264, 360)
CODEX_CARD = (198, 270)
CODEX_COLUMNS = 6


def cost_badge(picture: Image.Image, cost: int, size: int) -> None:
    """A card's cost after reductions, on a gold coin at its corner."""
    draw = ImageDraw.Draw(picture)
    draw.ellipse((6, 6, 6 + size, 6 + size), fill=GOLD, outline=SHADOW, width=3)
    draw.text((6 + size // 2, 6 + size // 2), str(cost), font=font(size * 2 // 3),
              fill=SHADOW, anchor="mm")


def scaled_card(slug: str, size: tuple[int, int], cards: CardCatalog) -> Image.Image:
    """A card's own art at `size`, scaled once per card and size: a copy,
    so a caller may draw on it. A game's hands and codex views draw a
    few dozen cards at two sizes; 128 holds them in tens of megabytes."""
    return _scaled_card(slug, size, cards).copy()


@lru_cache(maxsize=128)
def _scaled_card(slug: str, size: tuple[int, int], cards: CardCatalog) -> Image.Image:
    return card_picture(slug, cards).resize(size, Image.LANCZOS)


#: How many hands and codex pictures are kept, drawn, for the next click
#: that asks for the same one (`render_hand`, `render_codex`).
RENDERED_KEPT = 32


def render_hand(cards_in_hand: Sequence[str], playable: Sequence[bool],
                costs: Sequence[int], cards: Optional[CardCatalog] = None) -> bytes:
    """
    A hand as WebP bytes: the cards' own pictures in a row, numbered,
    each with its cost after reductions, greyed where it may not be
    played -- the picture **My hand** and the panel attach. The same hand
    asked again is the bytes already drawn (`RENDERED_KEPT`).
    """
    return _render_hand(tuple(cards_in_hand), tuple(playable), tuple(costs),
                        cards or load_catalog())


@lru_cache(maxsize=RENDERED_KEPT)
def _render_hand(cards_in_hand: tuple[str, ...], playable: tuple[bool, ...],
                 costs: tuple[int, ...], cards: CardCatalog) -> bytes:
    count = max(1, len(cards_in_hand))
    columns = min(count, 6)
    rows = -(-count // columns)
    gap, label = 16, 46
    width = columns * (HAND_CARD[0] + gap) + gap
    height = rows * (HAND_CARD[1] + label + gap) + gap
    canvas = Image.new("RGBA", (width, height), STRIP_FILL)
    draw = ImageDraw.Draw(canvas)
    if not cards_in_hand:
        text_centred(draw, (width // 2, height // 2), "No cards in hand", 36)
    for index, slug in enumerate(cards_in_hand):
        row, column = divmod(index, columns)
        left = gap + column * (HAND_CARD[0] + gap)
        top = gap + row * (HAND_CARD[1] + label + gap)
        text_centred(draw, (left + HAND_CARD[0] // 2, top + label // 2), str(index + 1), 34)
        picture = scaled_card(slug, HAND_CARD, cards)
        cost_badge(picture, costs[index], 62)
        if not playable[index]:
            picture = faint(picture)
        canvas.alpha_composite(picture, (left, top + label))
    return _webp(canvas)


def render_codex(cards_in_codex: Sequence[str], counts: Sequence[int],
                 cards: Optional[CardCatalog] = None,
                 picked: Optional[Sequence[int]] = None) -> bytes:
    """
    A codex view as WebP bytes: a grid of its cards' own pictures, each
    with a badge of how many copies remain, a card with none left faint.
    Sized so the standard game's thirty-six stay well under Discord's
    upload limit. `picked`, where given, is how many copies of each the
    tech choice has taken so far: such a card is framed in gold with
    the count on a pill over its art -- the tech picker's picture. The
    same picture asked again is the bytes already drawn (`RENDERED_KEPT`).
    """
    return _render_codex(tuple(cards_in_codex), tuple(counts), cards or load_catalog(),
                         None if picked is None else tuple(picked))


@lru_cache(maxsize=RENDERED_KEPT)
def _render_codex(cards_in_codex: tuple[str, ...], counts: tuple[int, ...],
                  cards: CardCatalog, picked: Optional[tuple[int, ...]]) -> bytes:
    count = max(1, len(cards_in_codex))
    columns = min(count, CODEX_COLUMNS)
    rows = -(-count // columns)
    gap = 14
    width = columns * (CODEX_CARD[0] + gap) + gap
    height = rows * (CODEX_CARD[1] + gap) + gap
    canvas = Image.new("RGBA", (width, height), STRIP_FILL)
    draw = ImageDraw.Draw(canvas)
    if not cards_in_codex:
        text_centred(draw, (width // 2, height // 2), "Nothing here", 32)
    for index, slug in enumerate(cards_in_codex):
        row, column = divmod(index, columns)
        left = gap + column * (CODEX_CARD[0] + gap)
        top = gap + row * (CODEX_CARD[1] + gap)
        picture = scaled_card(slug, CODEX_CARD, cards)
        if counts[index] <= 0:
            picture = faint(picture)
        badge = ImageDraw.Draw(picture)
        size = 56
        x0, y0 = CODEX_CARD[0] - size - 6, 6
        badge.ellipse((x0, y0, x0 + size, y0 + size), fill=INK, outline=SHADOW, width=3)
        badge.text((x0 + size // 2, y0 + size // 2), f"x{counts[index]}", font=font(26),
                   fill=SHADOW, anchor="mm")
        taken = picked[index] if picked is not None else 0
        if taken:
            badge.rectangle((0, 0, CODEX_CARD[0] - 1, CODEX_CARD[1] - 1), outline=GOLD, width=8)
            pill(badge, (CODEX_CARD[0] // 2, CODEX_CARD[1] * 2 // 5), f"picked {taken}", 26,
                 ACTIVE_FILL, anchor="mm")
        canvas.alpha_composite(picture, (left, top))
    return _webp(canvas)
