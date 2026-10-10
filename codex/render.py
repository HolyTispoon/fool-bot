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
  III, II and I, and the base, each heart carrying the HP it has now;
- across the top, as on the mat, the command zone -- one plate, a slot
  per hero, the hero lying in it while off the field -- and then the
  patrol zone: the mat's own five slots with their bonuses under them,
  each on its own holder of the mat's blue, packed side by side, a
  patroller's card over its slot. That row sets the panel's width;
- the grid under it: square cells of 273, as many columns as fit under
  the top row -- six in the standard game, five in the basic, fixed
  when it starts -- the worker card first, under the command zone, its
  printed count the workers the player has now, then the heroes on the
  field, then the units, each its
  card at 200 by 273 with its chits, and on its side at full size when
  exhausted; rows added as the position needs them;
- the nameplate along the panel's outer edge: the player, their team
  (`codex.formatting.team_name`), and the counts.

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

**No render reads a disk.** Every file a picture is drawn from -- the
cards' art, the board's pieces, the emoji the pictures borrow, the two
fonts -- is read into memory once (`bundled_bytes`), the whole set as
the bot starts (`preload_pictures`, which the cog runs off the event
loop) and anything that missed on its first use. The live host's
checkout is a mounted Google Drive letter (docs/design/collaboration.md),
and the bot is restarted on every deploy: without this, the first hand
and the first codex of a game after one read their cards' art through
it, a file at a time (docs/design/codex.md, "The board on Discord").
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Mapping, Optional, Sequence

from PIL import (Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps,
                 ImageStat)

from codex.cards import BOARD_IMAGE_DIR, CARD_IMAGE_DIR, CardCatalog, catalog as load_catalog
from codex.components import (
    PATROL_SLOTS, TECH_BUILDINGS, CardInstance, HeroState, MatchState, PlayerState, is_hero_ref,
)
from codex.engine import ADD_ONS, TECH_BUILDING_SLUGS
from codex.formatting import team_name

#: The fonts are D12 Ball's, bundled, and read by absolute path
#: (docs/design/board-image.md): Roboto Slab for every word and number.
FONT_DIR = Path(__file__).resolve().parent.parent / "d12ball" / "fonts"
#: The emoji the bot uploads, whose pictures the nameplate and an
#: exhausted card's corner borrow.
EMOJI_DIR = Path(__file__).resolve().parent / "images" / "emoji"
#: The two faces every word the pictures carry is drawn in: bold, and
#: regular for the quiet words.
FONT_FILES = ("RobotoSlab-Bold.ttf", "RobotoSlab-Regular.ttf")

#: What the composed board is scaled by before it is saved: 1, the
#: canvas's own pixels, so a card on the board is 200 by 273 and its
#: text reads when the picture is zoomed -- at 0.6 (until 2026-10-09)
#: a card's name read but not its rules or a hero's level bands, and
#: at 0.8 they were still soft (the author asked for "a bit higher res
#: to be able to see" Troq Bashar's card). It costs about two and a
#: half times the bytes: the staged mid-game board 137 KB to 332
#: stacked, 144 to 343 side by side, drawn in the same quarter-second.
BOARD_SCALE = 1.0
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
#: Where a card's art ends, from the card's top at `CARD`: the name's
#: banner starts below it (a hero's a little higher, at about 129). A
#: unit's or a hero's damage chits stand on the art's foot, clear of the
#: ATK and HP printed at the card's (the author, 2026-10-09).
ART_FOOT = 122
#: A building's picture prints its full HP in a red heart, white figures
#: edged black; a damaged building's heart is the picture's own with
#: those figures wiped and the HP it has now written in their place (the
#: author, 2026-10-09: a heart drawn over it did not look like the
#: print's). The heart is the red on the picture's right half; the old
#: figures are its white and black, between these shares of its width
#: and height -- clear of the gloss on its two lobes.
HEART_RED = ((151, 255), (0, 69), (0, 69))
FIGURE_WHITE = ((150, 255),) * 3
FIGURE_BLACK = ((0, 70),) * 3
FIGURE_AREA = (0.05, 0.22, 0.95, 0.8)
#: The print's figures are broader than Roboto Slab's: written, then
#: stretched across by this.
FIGURE_STRETCH = 1.2

#: The worker card (the Screentop module's, "workers/" and
#: "worker_colors/"): the seat that
#: went first holds x4, printed "Player 1", the other x5, "Player 2"
#: (UMR p. 3), in the colour of the starting deck -- the first hero's
#: whose colour the deck is, `PlayerState.deck_color` (the author,
#: 2026-10-10) -- `worker_colors/red_x4.png`, the neutral
#: `workers/worker_x4.png` for the basic game (`worker_face`). The count printed on it -- in
#: the colour's ink, edged, in a pale box at its foot -- is wiped and
#: the workers the player has now written in its place (the author, 2026-10-10: the count on the card
#: under the command zone, not in the nameplate). The box is the
#: picture's at 375 by 525: the count stands within `WORKER_AREA`, the
#: printed "Player n" in `WORKER_PLAYER`, left alone, and the new count
#: is set on `WORKER_BASELINE`, above it, as high as the print's digit
#: and no wider than the box.
WORKER_AREA = (14, 280, 165, 392)
WORKER_PLAYER = (0, 380, 92, 525)
WORKER_BASELINE = 379
WORKER_BOX_RIGHT = 157

#: The command zone: one plate beside the patrol zone, as on the mat,
#: with a slot per hero -- three in the standard game, one in the basic
#: -- rather than a plate per hero in the grid (the author, 2026-10-10).
#: A slot is a card's size, padded as a patrol holder is, the plate as
#: tall as the patrol zone, its name in the strip where a slot's bonus
#: would be.
COMMAND_SLOT_GAP = PATROL_SLOT_GAP
#: Between the command zone and the patrol zone.
ZONE_GAP = CELL_GAP
#: The fewest columns a grid has: the basic game's top row fits four
#: cells, and a fifth card wrapped to a second row cost 289 of height
#: for 45 of width saved (the author, 2026-10-10: five columns).
MIN_GRID_COLUMNS = 5

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
#: A named rune's tag on a card (step 11): Bloodburn's, Might of Leaf and
#: Claw's, a feather rune.
MARK_FILL = (122, 74, 160)       # #7a4aa0
DISABLED_FILL = (150, 40, 40)    # #962828
FIGURE_EDGE = (15, 10, 10)

# The hand's and the codex's.
INK = (242, 242, 242)
SHADOW = (12, 10, 8)
GOLD = (236, 190, 64)
STRIP_FILL = (24, 20, 16)
ACTIVE_FILL = (64, 46, 18)


# -- Loading -----------------------------------------------------------


#: Every bundled file a picture is drawn from, by path, as its bytes:
#: filled whole by `preload_pictures` as the bot starts, and by the
#: first use of anything it missed. About 44 MB, held for the
#: process's life, so that no click reads the host's disk (the module
#: docstring).
_BUNDLED: dict[str, bytes] = {}

#: What `preload_pictures` reads: every file under these folders but
#: the module's sheets and the playmat, which are imported as the
#: references the pieces were cut from and never drawn -- and the two
#: fonts.
PRELOADED_FOLDERS = (CARD_IMAGE_DIR, BOARD_IMAGE_DIR, EMOJI_DIR)
NOT_PRELOADED = ("sheets", "playmat.png")


def bundled_bytes(path: Path) -> bytes:
    """A bundled file's bytes, read from the disk once."""
    key = str(path)
    found = _BUNDLED.get(key)
    if found is None:
        found = _BUNDLED[key] = path.read_bytes()
    return found


def bundled(path: Path) -> bool:
    """Whether a bundled file is there: in memory already, or on disk."""
    return str(path) in _BUNDLED or path.is_file()


def preload_pictures() -> tuple[int, int]:
    """
    Read every file a picture may be drawn from into memory: the files
    read and their bytes. Blocking, and the one read of most of them --
    the cog runs it off the event loop, once, as the bot starts.
    """
    files = size = 0
    for folder in PRELOADED_FOLDERS:
        for path in sorted(folder.rglob("*")):
            if not path.is_file() or set(path.relative_to(folder).parts) & set(NOT_PRELOADED):
                continue
            size += len(bundled_bytes(path))
            files += 1
    for name in FONT_FILES:
        size += len(bundled_bytes(FONT_DIR / name))
        files += 1
    return files, size


@lru_cache(maxsize=32)
def font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    bold_face, regular_face = FONT_FILES
    face = FONT_DIR / (bold_face if bold else regular_face)
    return ImageFont.truetype(io.BytesIO(bundled_bytes(face)), size)


@lru_cache(maxsize=256)
def _image(path: str) -> Image.Image:
    with Image.open(io.BytesIO(bundled_bytes(Path(path)))) as opened:
        return opened.convert("RGBA")


def image(path: Path) -> Image.Image:
    """A bundled picture, loaded once; a copy, so a caller may draw on it."""
    return _image(str(path)).copy()


def board_piece(*parts: str) -> Image.Image:
    return image(BOARD_IMAGE_DIR.joinpath(*parts))


def card_picture(slug: str, cards: CardCatalog) -> Image.Image:
    """A card's or a hero's own art, or the card back where it has none."""
    found = cards.by_slug(slug).picture
    if found is None or not bundled(found):
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


def arrived_tag(canvas: Image.Image, card_left: int, bottom: int) -> None:
    """ARRIVED on a green tag against the card's left edge, standing on
    `bottom` -- the foot of its art: what came this turn."""
    draw = ImageDraw.Draw(canvas)
    face = font(14)
    width = spaced_width("ARRIVED", face, 0.5) + 20
    height = 24
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
    #: The runes besides +1/+1 and -1/-1 (step 11) -- "Blood 2",
    #: "Growth 5", "Feather" -- as tags under the rune chits.
    marks: tuple[str, ...] = ()
    #: Its time runes (step 12): fading on a card in play, Prynn's on
    #: her, forecast on a card in the future -- the module's chit.
    time_runes: int = 0
    #: Disabled (step 12): a mark beside where the exhaust glyph goes.
    disabled: bool = False
    #: A card in the future (step 12): greyed, not yet in play.
    future: bool = False
    #: The units buried in a Graveyard (step 12), counted on its card.
    buried: int = 0


#: What Polymorph: Squirrel shows a unit as while it lasts.
POLYMORPHED = "squirrel"


#: The named runes that are one alone, so a tag of their own needs no
#: count: a feather, a crumbling rune (step 13).
SINGLE_RUNES = ("feather", "crumbling")


def rune_marks(card, cards: Optional[CardCatalog] = None) -> tuple[str, ...]:
    """A card's or a hero's named runes as tags -- "Blood 2", "Feather",
    "Crumbling", "Sword 1" -- and, on a card (step 13), what else it
    carries: "Copy: Fox Viper", "Jail: Iron Man", "Number 3", "Oath: no
    draw"."""
    found = [
        kind.title() + (f" {count}" if count > 1 or kind not in SINGLE_RUNES else "")
        for kind, count in sorted((getattr(card, "runes", None) or {}).items()) if count
    ]
    if not isinstance(card, CardInstance):
        return tuple(found)
    name = cards.name if cards is not None else (lambda slug: slug.replace("_", " ").title())
    if card.copy_of:
        found.append(f"Copy: {name(card.copy_of)}")
    if card.jailed:
        found.append(f"Jail: {name(card.jailed['slug'])}")
    if card.number is not None:
        found.append(f"Number {card.number}")
    if card.oath:
        found.append({"hand": "Oath: workers only", "draw": "Oath: no draw"}.get(card.oath, card.oath))
    return tuple(found)


def unit_lying(card: CardInstance, partnered: bool, cards: Optional[CardCatalog] = None) -> Lying:
    """A card in play as it lies -- a Squirrel's art while Polymorph:
    Squirrel has it (step 11)."""
    slug = POLYMORPHED if (card.printed or {}).get("polymorph") is not None else card.slug
    return Lying(slug, damage=card.damage, plus_runes=card.plus_runes,
                 minus_runes=card.minus_runes, partnered=partnered,
                 arrived=card.arrived_this_turn, exhausted=card.exhausted,
                 marks=rune_marks(card, cards), time_runes=card.time_runes,
                 disabled=card.disabled, buried=len(card.buried or ()))


def future_lying(card: CardInstance) -> Lying:
    """A card in the future (step 12, UMR p. 17) as it waits: greyed, its
    time runes on it."""
    return Lying(card.slug, time_runes=card.time_runes, future=True)


def hero_lying(hero: HeroState, cards: CardCatalog) -> Lying:
    return Lying(hero.slug, level=level_chit(hero, cards), damage=hero.damage,
                 plus_runes=hero.plus_runes, minus_runes=hero.minus_runes,
                 arrived=hero.arrived_this_turn, exhausted=hero.exhausted,
                 time_runes=hero.time_runes, disabled=hero.disabled, marks=rune_marks(hero))


def card_face(slug: str, cards: CardCatalog, size: tuple[int, int] = CARD) -> Image.Image:
    return rounded(card_picture(slug, cards).convert("RGBA").resize(size, Image.LANCZOS),
                   round(size[0] / 20))


def lying_card(lying: Lying, cards: CardCatalog) -> Image.Image:
    """
    One card as it lies in a cell, on a transparent square of `CELL`
    with `OVERHANG` round it, the card's centre the square's: its own
    art at 200 by 273, a level chit top left (a hero), its rune chits
    top right, its damage chits on the foot of its art, Two Step's chit on
    a dance partner, ARRIVED on its art's foot the turn it came -- and, exhausted, the
    whole of it turned on its side at full size, lying across the cell,
    with the exhaust glyph on the cell's top corner, the right way up.
    """
    margin = OVERHANG
    upright = Image.new("RGBA", (CARD[0] + 2 * margin, CARD[1] + 2 * margin), (0, 0, 0, 0))
    face = card_face(lying.slug, cards)
    if lying.exhausted:
        face = dimmed(face, 0.75)
    if lying.future:
        face = greyed(face, 0.7)
    upright.alpha_composite(face, (margin, margin))
    right, bottom = margin + CARD[0], margin + CARD[1]
    if lying.level is not None:
        lay_row(upright, [lying.level], 62, (margin - 10, margin - 10))
    if lying.time_runes:
        # Under a hero's level chit, or in its place on a card.
        top = margin - 10 + (66 if lying.level is not None else 0)
        lay_row(upright, [time_rune_chit(lying.time_runes)], 62, (margin - 10, top))
    runes = rune_chits(lying.plus_runes, lying.minus_runes)
    if runes:
        lay_row(upright, runes, 50, (right + 8, margin - 8), leftward=True)
    if lying.damage:
        lay_row(upright, damage_chits(lying.damage), 62, (right - 10, margin + ART_FOOT),
                leftward=True, upward=True)
    if lying.partnered:
        lay_row(upright, [board_piece("chits", "two_step.png")], 50, (margin - 8, bottom + 8),
                upward=True)
    if lying.marks:
        draw = ImageDraw.Draw(upright)
        for index, mark in enumerate(lying.marks):
            pill(draw, (right - 6, margin + 60 + index * 30), mark, 18, MARK_FILL, anchor="rt")
    if lying.buried:
        draw = ImageDraw.Draw(upright)
        pill(draw, (margin + CARD[0] // 2, margin + ART_FOOT - 40), f"Buried {lying.buried}",
             20, MARK_FILL, anchor="mt")
    if lying.future:
        draw = ImageDraw.Draw(upright)
        pill(draw, (margin + CARD[0] // 2, bottom - 44), "FUTURE", 18, MARK_FILL, anchor="mb")
    if lying.arrived:
        # On its art's foot, opposite the damage chits, clear of the
        # card's text (the author, 2026-10-10).
        arrived_tag(upright, margin, margin + ART_FOOT)

    tile = Image.new("RGBA", (CELL + 2 * margin, CELL + 2 * margin), (0, 0, 0, 0))
    if not lying.exhausted:
        paste_centred(tile, upright, (0, 0, tile.width, tile.height))
    else:
        # Turned a quarter clockwise, as a card is exhausted on a table.
        paste_centred(tile, upright.transpose(Image.ROTATE_270), (0, 0, tile.width, tile.height))
        glyph = by_width(image(EMOJI_DIR / "exhaust.png"), 48)
        tile.alpha_composite(glyph, (margin + 8, margin + 8))
    if lying.disabled:
        # Beside the exhaust glyph's corner, where it would be.
        draw = ImageDraw.Draw(tile)
        pill(draw, (margin + (64 if lying.exhausted else 8), margin + 16), "DISABLED", 16,
             DISABLED_FILL, anchor="lt")
    return tile


def command_zone_width(count: int) -> int:
    """The command zone's plate, for `count` heroes."""
    return 2 * PATROL_PADDING + count * CARD[0] + (count - 1) * COMMAND_SLOT_GAP


def command_zone(heroes_in_zone: Sequence[Optional[HeroState]],
                 cards: CardCatalog) -> Image.Image:
    """
    The command zone: one dark, edged plate as tall as the patrol zone,
    a slot per hero -- the hero lying in it in full while off the field,
    with its time-rune chit for its summoning runes; the slot empty,
    marked HERO as the mat marks it, while the hero is on the field --
    and COMMAND ZONE along its foot. Drawn with `OVERHANG` round it for
    the chits.
    """
    margin = OVERHANG
    width = command_zone_width(len(heroes_in_zone))
    tile = Image.new("RGBA", (width + 2 * margin, PATROL_HEIGHT + 2 * margin), (0, 0, 0, 0))
    draw = ImageDraw.Draw(tile)
    draw.rounded_rectangle((margin, margin, margin + width - 1, margin + PATROL_HEIGHT - 1),
                           radius=14, fill=PLATE_FILL, outline=PLATE_EDGE, width=2)
    face = font(13, bold=False)
    label = "COMMAND ZONE"
    strip_top = margin + PATROL_PADDING + CARD[1] + BONUS_GAP
    spaced_text(draw, (margin + (width - spaced_width(label, face, 1.5)) / 2,
                       strip_top + (BONUS[1] - 13) / 2 - 2),
                label, face, PLATE_INK, 1.5)
    top = margin + PATROL_PADDING
    for index, hero in enumerate(heroes_in_zone):
        left = margin + PATROL_PADDING + index * (CARD[0] + COMMAND_SLOT_GAP)
        if hero is None:
            dashed_box(draw, (left, top, left + CARD[0], top + CARD[1]), PLATE_EDGE)
            word = "HERO"
            hero_face = font(18, bold=False)
            spaced_text(draw, (left + (CARD[0] - spaced_width(word, hero_face, 2)) / 2,
                               top + CARD[1] / 2 - 11),
                        word, hero_face, FAINT_INK, 2)
            continue
        tile.alpha_composite(card_face(hero.slug, cards, CARD), (left, top))
        if hero.summoning_runes:
            lay_row(tile, [time_rune_chit(hero.summoning_runes)], 54, (left - 8, top - 8))
    return tile


def worker_face(color: str, went_first: bool) -> tuple[str, str]:
    """The worker card's folder and file under `codex/images/board/`:
    the starting deck's colour's, `worker_colors/red_x4.png`, or the
    neutral one, `workers/worker_x4.png`, for neutral and for a colour
    with none."""
    count = 4 if went_first else 5
    coloured = f"{color}_x{count}.png"
    if color != "neutral" and bundled(BOARD_IMAGE_DIR / "worker_colors" / coloured):
        return "worker_colors", coloured
    return "workers", f"worker_x{count}.png"


@lru_cache(maxsize=2)
def worker_figures(went_first: bool) -> Image.Image:
    """
    Where the printed count stands on a worker card, as a mask at the
    picture's own size: found by its rosy ink on the neutral card,
    whose layout every colour's card shares -- the same box, the same
    figures in the same place, each colour's in its own ink, which no
    one band of colour finds on all seven.
    """
    picture = board_piece(*worker_face("neutral", went_first))
    red, green, _ = picture.convert("RGB").split()
    rosy = ImageChops.multiply(ImageChops.subtract(red, green).point(lambda v: 255 if v >= 20 else 0),
                               red.point(lambda v: 255 if v > 90 else 0))
    figures = Image.new("L", picture.size, 0)
    figures.paste(rosy.crop(WORKER_AREA), WORKER_AREA[:2])
    return figures


@lru_cache(maxsize=16)
def wiped_workers(face: tuple[str, str],
                  went_first: bool) -> tuple[Image.Image, int, int, tuple[int, int, int]]:
    """
    The worker card's face, `face` its folder and file, with its printed
    count wiped -- the pixels round its figures (`worker_figures`)
    blended into the box -- the left of those figures, their top, and
    the face's own ink under them, at the picture's own size.
    """
    picture = board_piece(*face)
    figures = worker_figures(went_first)
    left, top, _, _ = figures.getbbox()
    ink = ImageStat.Stat(picture.convert("RGB"), figures).median
    # Wide enough to take the figures' edge with them; never into the
    # "Player n" printed under the x.
    figures = figures.filter(ImageFilter.MaxFilter(11))
    figures.paste(0, WORKER_PLAYER)
    wiped = picture.copy()
    for _ in range(40):
        wiped.paste(wiped.filter(ImageFilter.GaussianBlur(3)), mask=figures)
    return wiped, left, top, tuple(round(v) for v in ink)


@lru_cache(maxsize=32)
def worker_card(workers: int, color: str, went_first: bool) -> Image.Image:
    """The worker card in `color`, the starting deck's, at a card's
    size, with `workers` -- "x8" -- where the print has its starting
    count."""
    wiped, left, top, ink = wiped_workers(worker_face(color, went_first), went_first)
    picture = wiped.copy()
    text = f"x{workers}"
    _, glyph_top, _, glyph_bottom = font(100, bold=False).getbbox("4", anchor="ls")
    size = round((WORKER_BASELINE - top) * 100 / (glyph_bottom - glyph_top))
    while size > 20 and font(size, bold=False).getlength(text) > WORKER_BOX_RIGHT - left:
        size -= 2
    ImageDraw.Draw(picture).text((left, WORKER_BASELINE), text, font=font(size, bold=False),
                                 fill=ink, anchor="ls", stroke_width=2, stroke_fill=FIGURE_EDGE)
    return rounded(picture.resize(CARD, Image.LANCZOS), round(CARD[0] / 20))


# -- The buildings -----------------------------------------------------------


def colour_mask(picture: Image.Image, bands) -> Image.Image:
    """White where each of the picture's red, green and blue lies in its
    band, black elsewhere."""
    mask = Image.new("L", picture.size, 255)
    for channel, (low, high) in zip(picture.convert("RGB").split(), bands):
        mask = ImageChops.multiply(mask, channel.point(lambda v: 255 if low <= v <= high else 0))
    return mask


@lru_cache(maxsize=16)
def wiped_heart(slug: str) -> tuple[Image.Image, tuple[float, float], int]:
    """
    A building's picture with the figures in its heart wiped -- filled
    with the heart's own red and blended into it -- the heart's centre,
    and how tall the figures stood, at the picture's own size.
    """
    picture = board_piece("buildings", f"{slug}.png")
    red = colour_mask(picture, HEART_RED)
    red.paste(0, (0, 0, picture.width // 2, picture.height))
    left, top, right, bottom = red.getbbox()
    width, height = right - left, bottom - top
    a, b, c, d = FIGURE_AREA
    area = (left + round(width * a), top + round(height * b),
            left + round(width * c), top + round(height * d))
    figures = Image.new("L", picture.size, 0)
    figures.paste(ImageChops.lighter(colour_mask(picture, FIGURE_WHITE),
                                     colour_mask(picture, FIGURE_BLACK)).crop(area), area[:2])
    _, figure_top, _, figure_bottom = figures.getbbox()
    figures = figures.filter(ImageFilter.MaxFilter(5))
    fill = ImageStat.Stat(picture.crop(area).convert("RGB"), red.crop(area)).median
    wiped = picture.copy()
    wiped.paste(tuple(round(v) for v in fill) + (255,), mask=figures)
    for _ in range(30):
        wiped.paste(wiped.filter(ImageFilter.GaussianBlur(3)), mask=figures)
    return wiped, ((left + right) / 2, (top + bottom) / 2), figure_bottom - figure_top


def building_picture(slug: str, hp: Optional[int] = None) -> Image.Image:
    """A building's picture at its own size -- with `hp` in its heart in
    place of the full HP it prints, where given."""
    if hp is None:
        return board_piece("buildings", f"{slug}.png")
    wiped, (centre_x, centre_y), height = wiped_heart(slug)
    picture = wiped.copy()
    stroke = max(2, round(height * 0.1))
    probe = font(100)
    _, glyph_top, _, glyph_bottom = probe.getbbox("0", anchor="ls")
    face = font(round((height - 2 * stroke) * 100 / (glyph_bottom - glyph_top)))
    text = str(hp)
    figures = Image.new("RGBA", (round(face.getlength(text)) + 4 * stroke, 2 * height), (0, 0, 0, 0))
    ImageDraw.Draw(figures).text((figures.width / 2, figures.height / 2), text, font=face,
                                 fill=(255, 255, 255), anchor="mm",
                                 stroke_width=stroke, stroke_fill=FIGURE_EDGE)
    figures = figures.crop(figures.getbbox())
    figures = figures.resize((round(figures.width * FIGURE_STRETCH), figures.height), Image.LANCZOS)
    # The ink centred on the heart, as the print centres its own.
    picture.alpha_composite(figures, (round(centre_x - figures.width / 2),
                                      round(centre_y - figures.height / 2)))
    return picture


def building_tile(slug: str, hp: Optional[int] = None) -> Image.Image:
    return rounded(building_picture(slug, hp).resize(TILE, Image.LANCZOS),
                   round(10 * BUILDING_SCALE))


#: The strip across a building under construction and a destroyed one,
#: beside the house chit, so neither is read from the chit alone (the
#: author, 2026-10-10): its word, fill and ink.
CONSTRUCTION_STRIP = ("UNDER CONSTRUCTION", GOLD, SHADOW)
DESTROYED_STRIP = ("DESTROYED", DISABLED_FILL, WORD)
#: A strip's height, how far it runs past the picture's edges on either
#: side, as tape wrapped round it, and its slope: rising from the
#: bottom left to the top right, close to level with a little slant (the author,
#: 2026-10-10), long enough for UNDER CONSTRUCTION in a type that reads
#: at Discord's scale.
STRIP_HEIGHT = 22
STRIP_OUT = 5
STRIP_ANGLE = 10


def lay_strip(canvas: Image.Image, box: tuple[int, int, int, int],
              strip: tuple[str, tuple, tuple]) -> None:
    """A strip across the middle of the picture at `box`, rising to the
    right by `STRIP_ANGLE`, past its edges by `STRIP_OUT`, edged dark,
    its word centred along it."""
    word, fill, ink = strip
    left, top, right, bottom = box
    length = round((right - left) / math.cos(math.radians(STRIP_ANGLE))) + 2 * STRIP_OUT
    band = Image.new("RGBA", (length, STRIP_HEIGHT), fill + (255,))
    draw = ImageDraw.Draw(band)
    draw.rectangle((0, 0, length - 1, STRIP_HEIGHT - 1), outline=SHADOW, width=2)
    face = font(11)
    width = spaced_width(word, face, 0.3)
    spaced_text(draw, ((length - width) / 2, STRIP_HEIGHT / 2), word, face, ink, 0.3)
    band = band.rotate(STRIP_ANGLE, resample=Image.BICUBIC, expand=True)
    canvas.alpha_composite(band, ((left + right - band.width) // 2,
                                  (top + bottom - band.height) // 2))


def damaged(hp: int, full: int) -> Optional[int]:
    """The HP a building's heart carries in place of its printed one:
    none while it is whole."""
    return hp if hp < full else None


def draw_building_column(body: Image.Image, player: PlayerState,
                         building_hp: Mapping[str, int], left: int, bottom: int) -> None:
    """
    The column of buildings, bottom-aligned from `bottom`, top to
    bottom: the add-on slot (`draw_add_on`), Tech III, II and I, the
    base. A tech
    building is greyed and half seen until built, in colour once built,
    the house chit on a top corner and UNDER CONSTRUCTION across it while
    under construction (UMR p. 8), dark with the house chit and
    DESTROYED across it when destroyed -- the base too, on a finished
    game's board. A damaged one's heart
    carries the HP it has now in place of the full HP it prints.
    """
    house = board_piece("chits", "house.png")
    top = bottom - BUILDING_COLUMN_HEIGHT
    draw_add_on(body, player, building_hp, left, top)
    y = top + ADD_ON[1] + TILE_GAP
    for name in reversed(TECH_BUILDINGS):
        state = player.buildings.get(name)
        standing = state is not None and not state.destroyed
        hp = damaged(state.hp, building_hp[name]) if standing else None
        tile = building_tile(TECH_BUILDING_SLUGS[name], hp)
        if state is None:
            tile = greyed(tile, 0.55, 0.5)
        elif state.destroyed:
            tile = greyed(tile, 0.35)
        body.alpha_composite(tile, (left, y))
        if name == "tech2" and player.tech2_spec:
            # The spec chosen at Tech II, its card drawn small on the tile
            # (UMR p. 8: "Place that card on your base").
            # It hangs off the tile's right edge into the gap before the
            # grid, so the tile's own words stay readable.
            mark = spec_mark(player.tech2_spec, SPEC_ON_TILE)
            body.alpha_composite(mark, (left + TILE[0] - SPEC_ON_TILE[0] // 2,
                                        y + TILE[1] - SPEC_ON_TILE[1] + 2))
        if state is not None and (state.destroyed or state.under_construction):
            lay_row(body, [house], HOUSE_CHIT, (left - CHIT_OUT, y - CHIT_OUT))
            lay_strip(body, (left, y, left + TILE[0], y + TILE[1]),
                      DESTROYED_STRIP if state.destroyed else CONSTRUCTION_STRIP)
        y += TILE[1] + TILE_GAP

    base = building_tile("base", damaged(player.base_hp, building_hp["base"]))
    if player.base_hp <= 0:
        base = greyed(base, 0.35)
    body.alpha_composite(base, (left, y))
    if player.base_hp <= 0:
        lay_strip(body, (left, y, left + TILE[0], y + TILE[1]), DESTROYED_STRIP)


#: A building's house chit, and how far it hangs over its corner, at
#: the column's scale.
HOUSE_CHIT = round(50 * BUILDING_SCALE)
CHIT_OUT = round(8 * BUILDING_SCALE)


BUILDING_COLUMN_HEIGHT = ADD_ON[1] + 4 * TILE[1] + 4 * TILE_GAP


def draw_add_on(body: Image.Image, player: PlayerState,
                building_hp: Mapping[str, int], left: int, top: int) -> None:
    """
    The add-on slot, its top left at (`left`, `top`): a dashed outline,
    or the add-on's card -- the house chit on its top corner and UNDER
    CONSTRUCTION across it while under construction, and on a damaged one the HP it has now in its heart,
    as a tech building's.
    """
    slot = (left, top, left + ADD_ON[0], top + ADD_ON[1])
    add_on = player.add_on
    if add_on is None:
        draw = ImageDraw.Draw(body)
        dashed_box(draw, slot, FAINT_INK)
        draw.text(((slot[0] + slot[2]) / 2, (slot[1] + slot[3]) / 2), "Add-on",
                  font=font(18, bold=False), fill=FAINT_INK, anchor="mm")
        return
    hp = damaged(add_on.hp, building_hp.get(add_on.slug, add_on.hp))
    card = rounded(building_picture(add_on.slug, hp).resize(ADD_ON, Image.LANCZOS),
                   round(ADD_ON[0] / 20))
    body.alpha_composite(card, slot[:2])
    if add_on.spec:
        # A tech lab's spec card, drawn small on its card (UMR p. 9).
        mark = spec_mark(add_on.spec, SPEC_ON_LAB)
        body.alpha_composite(mark, (slot[0] + (ADD_ON[0] - SPEC_ON_LAB[0]) // 2,
                                    slot[3] - SPEC_ON_LAB[1] - 8))
    if add_on.under_construction:
        lay_row(body, [board_piece("chits", "house.png")], HOUSE_CHIT,
                (slot[0] - CHIT_OUT, slot[1] - CHIT_OUT))
        lay_strip(body, slot, CONSTRUCTION_STRIP)


#: A chosen spec's card as it lies on the tech II tile and on a tech
#: lab's card: the module's spec card, small.
SPEC_ON_TILE = (round(70 * BUILDING_SCALE), round(50 * BUILDING_SCALE))
SPEC_ON_LAB = (96, 69)


def spec_mark(spec: str, size: tuple[int, int]) -> Image.Image:
    """A spec's card (`specs/<spec>.png`, cut at step 1) at `size`,
    rounded and edged so it reads on the tile under it."""
    picture = board_piece("specs", f"{spec}.png").resize(size, Image.LANCZOS)
    mark = rounded(picture, 5)
    ImageDraw.Draw(mark).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=5,
                                           outline=(20, 16, 12, 255), width=2)
    return mark


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
    one."""
    return list(player.heroes)


def top_row_width(hero_count: int) -> int:
    """The command zone, then the five patrol holders: the mat's top
    row, which sets the panel's width (the author, 2026-10-10: the
    board as wide as the mat -- the building column, three heroes, five
    patrol slots)."""
    patrol = len(PATROL_SLOTS) * PATROL_HOLDER + (len(PATROL_SLOTS) - 1) * PATROL_SLOT_GAP
    return command_zone_width(hero_count) + ZONE_GAP + patrol


def grid_columns(hero_count: int) -> int:
    """The grid's column count: as many cells as fit under the top row,
    never fewer than `MIN_GRID_COLUMNS` -- six in the standard game,
    five in the basic, whose grid runs 45 past its top row rather than
    wrapping a fifth card (the author, 2026-10-10). Fixed by how many
    heroes the game gives a player, so the picture's width holds from
    turn to turn (the author, 2026-10-08)."""
    fit = (top_row_width(hero_count) + CELL_GAP) // (CELL + CELL_GAP)
    return max(MIN_GRID_COLUMNS, fit)


def panel_columns(player: PlayerState) -> int:
    """The grid's column count, the game's (`grid_columns`)."""
    return grid_columns(len(heroes(player)))


def panel_width(hero_count: int) -> int:
    """A panel's width for a game of `hero_count` heroes a side: the
    building column and the top row, which the grid fits under."""
    columns = grid_columns(hero_count)
    grid = columns * CELL + (columns - 1) * CELL_GAP
    return 2 * PADDING + BUILDING_WIDTH + BUILDING_GAP + max(top_row_width(hero_count), grid)


def grid_cells(player: PlayerState, cards: CardCatalog) -> list[Image.Image]:
    """The grid, in order: the heroes on the field, then the units,
    every one not patrolling, then the building cards and upgrades,
    which never patrol (step 10), then the cards in the future, greyed
    with their time runes (step 12). The heroes off the field are in
    the command zone, above."""
    field = [lying_card(hero_lying(hero, cards), cards)
             for hero in heroes(player) if hero.in_play and hero.patrol_slot is None]
    partners = partner_ids(player)
    lying = [card for card in player.play if card.patrol_slot is None]
    lying.sort(key=lambda card: cards.cards[card.slug].is_permanent)
    units = [lying_card(unit_lying(card, card.id in partners, cards), cards) for card in lying]
    future = [lying_card(future_lying(card), cards) for card in player.future]
    return field + units + future


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
    inner_width = panel_width(len(heroes(player))) - 2 * PADDING
    height = body_height(1 + len(cells), columns)
    body = Image.new("RGBA", (inner_width + 2 * OVERHANG, height + 2 * OVERHANG), (0, 0, 0, 0))
    o = OVERHANG
    draw_building_column(body, player, building_hp, o, o + height)

    grid_left = o + BUILDING_WIDTH + BUILDING_GAP
    draw = ImageDraw.Draw(body)
    partners = partner_ids(player)
    card_top = o + PATROL_PADDING
    # The command zone first, beside the buildings, as on the mat.
    zone = command_zone([None if hero.in_play else hero for hero in heroes(player)], cards)
    body.alpha_composite(zone, (grid_left - OVERHANG, o - OVERHANG))
    holder_left = grid_left + command_zone_width(len(heroes(player))) + ZONE_GAP
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
        if is_hero_ref(ref):
            lying = hero_lying(player.hero_by_ref(ref), cards)
        else:
            instance_id = int(ref.split(":", 1)[1])
            lying = unit_lying(match.instance(instance_id), instance_id in partners, cards)
        # The patroller covers its slot, chits and all; the bonus stays
        # printed under it.
        paste_centred(body, lying_card(lying, cards),
                      (card_left, card_top, card_left + CARD[0], card_top + CARD[1]))

    top = o + PATROL_HEIGHT + CELL_GAP
    # The worker card in the grid's first cell, under the command zone.
    paste_centred(body, worker_card(player.workers, player.deck_color, seat == match.first),
                  (grid_left, top, grid_left + CELL, top + CELL))
    for index, cell in enumerate(cells, start=1):
        row, column = divmod(index, columns)
        left = grid_left + column * (CELL + CELL_GAP)
        cell_top = top + row * (CELL + CELL_GAP)
        body.alpha_composite(cell, (left - OVERHANG, cell_top - OVERHANG))
    return body


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
    The nameplate, 56 tall: the player, their team (`team_name`: a
    colour's deck by its name, "Blood Anarchs", any other team by its
    specs, "Fire/Feral/Bashing"), then gold
    (the gold emoji's picture), hand, deck, discard and codex,
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
    spec = team_name(player.specs)
    draw.text((x, middle), spec, font=font(18, bold=False), fill=QUIET, anchor="lm")
    x += font(18, bold=False).getlength(spec) + 18
    if colors:
        label = turn_label(match, name)
        face = font(15)
        pill_width = face.getlength(label) + 24
        turn_pill(draw, (x, middle - 13, x + pill_width, middle + 13), 10, colors)
        draw.text((x + 12, middle), label, font=face, fill=colors[1], anchor="lm")

    counts = (
        ("HAND", len(player.hand)), ("DECK", len(player.deck)),
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
    """Each building's full HP, from the card data -- what its picture
    prints in its heart: below it, the heart carries the HP it has now."""
    found = {name: cards.building(slug).hp or 0 for name, slug in TECH_BUILDING_SLUGS.items()}
    for slug in ADD_ONS:
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


#: A card in a hand or a codex picture, in pixels: the art (330 by 450)
#: at 0.7, and at 8/15 -- from 0.8 and 0.6 (264 by 360, 198 by 270)
#: until the author asked for the cards a bit smaller (2026-10-09),
#: which takes about a sixth off each picture's bytes: the staged
#: mid-game hand 87 KB to 72, the twelve-card codex 164 to 134, the
#: standard game's seventy-two 590 to 477. The badges, the numbers and
#: the picked pill keep their size, so they read a little larger on
#: the card.
HAND_CARD = (231, 315)
CODEX_CARD = (176, 240)
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
#: that asks for the same one (`render_hand`, `render_codex`, `render_deck`).
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
                 picked: Optional[Sequence[int]] = None,
                 row_starts: Sequence[int] = ()) -> bytes:
    """
    A codex view as WebP bytes: a grid of its cards' own pictures, each
    with a badge of how many copies remain, a card with none left faint.
    Sized so the standard game's thirty-six stay well under Discord's
    upload limit. `picked`, where given, is how many copies of each the
    tech choice has taken so far: such a card is framed in gold with
    the count on a pill over its art -- the tech picker's picture.
    `row_starts` are the cards that begin a new row (the engine's
    `codex_row_starts`: the Tech II view's specs, a line each), the grid
    as wide as its longest line. The same picture asked again is the
    bytes already drawn (`RENDERED_KEPT`).
    """
    return _render_codex(tuple(cards_in_codex), tuple(counts), cards or load_catalog(),
                         None if picked is None else tuple(picked), tuple(row_starts))


def codex_tile(slug: str, count: int, cards: CardCatalog) -> Image.Image:
    """One card of a codex or a deck: its picture with a badge of its
    copies, faint where none are left."""
    picture = scaled_card(slug, CODEX_CARD, cards)
    if count <= 0:
        picture = faint(picture)
    badge = ImageDraw.Draw(picture)
    size = 56
    x0, y0 = CODEX_CARD[0] - size - 6, 6
    badge.ellipse((x0, y0, x0 + size, y0 + size), fill=INK, outline=SHADOW, width=3)
    badge.text((x0 + size // 2, y0 + size // 2), f"x{count}", font=font(26),
               fill=SHADOW, anchor="mm")
    return picture


@lru_cache(maxsize=RENDERED_KEPT)
def _render_codex(cards_in_codex: tuple[str, ...], counts: tuple[int, ...],
                  cards: CardCatalog, picked: Optional[tuple[int, ...]],
                  row_starts: tuple[int, ...] = ()) -> bytes:
    bounds = [0, *sorted(set(row_starts) - {0}), len(cards_in_codex)]
    lines = [range(start, end) for start, end in zip(bounds, bounds[1:]) if end > start]
    columns = min(CODEX_COLUMNS, max([len(line) for line in lines] or [1]))
    places, rows = {}, 0
    for line in lines:
        for at, index in enumerate(line):
            places[index] = (rows + at // columns, at % columns)
        rows += -(-len(line) // columns)
    rows = max(1, rows)
    gap = 14
    width = columns * (CODEX_CARD[0] + gap) + gap
    height = rows * (CODEX_CARD[1] + gap) + gap
    canvas = Image.new("RGBA", (width, height), STRIP_FILL)
    draw = ImageDraw.Draw(canvas)
    if not cards_in_codex:
        text_centred(draw, (width // 2, height // 2), "Nothing here", 32)
    for index, slug in enumerate(cards_in_codex):
        row, column = places[index]
        left = gap + column * (CODEX_CARD[0] + gap)
        top = gap + row * (CODEX_CARD[1] + gap)
        picture = codex_tile(slug, counts[index], cards)
        taken = picked[index] if picked is not None else 0
        if taken:
            badge = ImageDraw.Draw(picture)
            badge.rectangle((0, 0, CODEX_CARD[0] - 1, CODEX_CARD[1] - 1), outline=GOLD, width=8)
            pill(badge, (CODEX_CARD[0] // 2, CODEX_CARD[1] * 2 // 5), f"picked {taken}", 26,
                 ACTIVE_FILL, anchor="mm")
        canvas.alpha_composite(picture, (left, top))
    return _webp(canvas)


def render_deck(held: Sequence[tuple[str, int]], discarded: Sequence[tuple[str, int]],
                elsewhere: Sequence[tuple[str, int]],
                cards: Optional[CardCatalog] = None) -> bytes:
    """
    A player's whole deck as WebP bytes -- **My deck**'s picture: three
    parts **side by side**, each in a frame headed with its name -- the
    cards in the hand, those in the discard pile, and the rest of the
    deck -- a part going to a new row only where it would make the
    picture wider than `DECK_COLUMNS` cards (the author, 2026-10-10:
    "one image but with the frames around separating the different
    parts"). Each card shows once per part with its copies there on its
    badge, so a card with copies in two places shows in both (the
    author, 2026-10-09). The hand's frame is the neutral white the words
    are, the others the quiet grey -- never gold, which is the tech
    picker's mark and the currency's. A part with no cards is left out.
    The same deck asked again is the bytes already drawn
    (`RENDERED_KEPT`).
    """
    return _render_deck(tuple(held), tuple(discarded), tuple(elsewhere),
                        cards or load_catalog())


#: The deck picture's height above a frame's cards, for its name.
DECK_HEADING = 44
#: The room inside a frame around its cards.
DECK_BOX_PAD = 14
#: The widest the deck picture grows, in cards: a part that would pass
#: it starts a new row of frames, and no one part is wider.
DECK_COLUMNS = 8


@lru_cache(maxsize=RENDERED_KEPT)
def _render_deck(held: tuple[tuple[str, int], ...], discarded: tuple[tuple[str, int], ...],
                 elsewhere: tuple[tuple[str, int], ...], cards: CardCatalog) -> bytes:
    gap, pad = 14, DECK_BOX_PAD
    card_w, card_h = CODEX_CARD
    face = font(26)
    limit = DECK_COLUMNS * (card_w + gap) + gap
    # Each frame: its name, its cards, its edge, and its size, cards
    # in as many columns as it has cards up to the limit.
    frames = []
    for title, rows, edge in (
        ("Hand", held, WORD), ("Discard pile", discarded, QUIET), ("Rest of deck", elsewhere, QUIET),
    ):
        if not rows:
            continue
        columns = min(len(rows), DECK_COLUMNS)
        lines = -(-len(rows) // columns)
        grid = columns * card_w + (columns - 1) * gap
        width = max(grid, round(face.getlength(title))) + 2 * pad
        height = DECK_HEADING + lines * card_h + (lines - 1) * gap + pad
        frames.append((title, rows, edge, columns, width, height))
    # Frames placed left to right, a new row where the next would pass
    # the limit; a row is as tall as its tallest frame, and every frame
    # in it is stretched to that height so the edges line up.
    placed, row, x = [], [], gap
    for frame in frames:
        if row and x + frame[4] + gap > limit:
            placed.append(row)
            row, x = [], gap
        row.append((x, frame))
        x += frame[4] + gap
    if row:
        placed.append(row)
    width = max((left + frame[4] for row in placed for left, frame in [row[-1]]), default=0) + gap
    heights = [max(frame[5] for _, frame in row) for row in placed]
    height = gap + sum(row_height + gap for row_height in heights)
    if not frames:
        width, height = card_w * 2, card_h // 2
    canvas = Image.new("RGBA", (width, height), STRIP_FILL)
    draw = ImageDraw.Draw(canvas)
    if not frames:
        text_centred(draw, (width // 2, height // 2), "Nothing here", 32)
    top = gap
    for row, row_height in zip(placed, heights):
        for left, (title, rows, edge, columns, frame_width, _) in row:
            draw.rounded_rectangle((left, top, left + frame_width - 1, top + row_height - 1),
                                   radius=12, fill=PANEL, outline=edge, width=3)
            draw.text((left + pad, top + DECK_HEADING // 2), title, font=face,
                      fill=edge, anchor="lm")
            for index, (slug, count) in enumerate(rows):
                line, column = divmod(index, columns)
                canvas.alpha_composite(
                    codex_tile(slug, count, cards),
                    (left + pad + column * (card_w + gap),
                     top + DECK_HEADING + line * (card_h + gap)),
                )
        top += row_height + gap
    return _webp(canvas)
