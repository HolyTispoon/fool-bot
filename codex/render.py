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

A panel (`render_panel`), top to bottom and left to right, at
`DRAW_SCALE` (1.3) times the canvas's pixels:

- a column of buildings on the left, 177 wide -- the add-on slot, Tech
  III, II and I, and the base, each heart carrying the HP it has now;
- across the top, as on the mat, the command zone -- one plate, a slot
  per hero, the hero lying in it while off the field -- and then the
  patrol zone: the mat's own five slots with their bonuses under them,
  each on its own holder of the mat's blue, packed side by side, a
  patroller's card over its slot. That row sets the panel's width;
- the grid under it: square cells of 355, as many columns as fit under
  the top row -- six in the standard game, five in the basic, fixed
  when it starts -- the worker card first, under the command zone, its
  printed count the workers the player has now, then the heroes on the
  field, then the units, each its
  card at 260 by 355 with its chits, and on its side at full size when
  exhausted; rows added as the position needs them;
- the nameplate along the panel's outer edge: the player, their team
  (`codex.formatting.team_name`), and the counts.

`render_board` composes two: stacked, the default -- the active
player's below, the other player's above it turned round whole so the
two patrol zones face each other, its nameplate alone kept the right
way up -- stacked the same way up, the same two panels with neither
turned, or side by side, the first player's on the left, neither
turned.

**Nothing here is tested for how it looks** (CLAUDE.md, "Nothing
rendered is tested"): `scripts/render_codex_sample.py` draws the
opening position, a mid-game one and every state on the canvas's
states board, in every layout; look at them. Every caller renders
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
from typing import Callable, Mapping, Optional, Sequence, Union

import numpy as np
from PIL import (Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps,
                 ImageStat)

from codex import seats
from codex.cards import BOARD_IMAGE_DIR, CARD_IMAGE_DIR, CardCatalog, catalog as load_catalog
from codex.components import (
    PATROL_SLOTS, TECH_BUILDINGS, CardInstance, HeroState, MatchState, PlayerState, is_hero_ref,
    split_lent_ref,
)
from codex.engine import ADD_ONS, CODEX_COLUMNS, TECH_BUILDING_SLUGS
from codex.formatting import copy_number, team_name

#: The fonts are D12 Ball's, bundled, and read by absolute path
#: (docs/design/board-image.md): Roboto Slab for every word and number.
FONT_DIR = Path(__file__).resolve().parent.parent / "d12ball" / "fonts"
#: The emoji the bot uploads, whose pictures the nameplate and an
#: exhausted card's corner borrow.
EMOJI_DIR = Path(__file__).resolve().parent / "images" / "emoji"
#: The two faces every word the pictures carry is drawn in: bold, and
#: regular for the quiet words.
FONT_FILES = ("RobotoSlab-Bold.ttf", "RobotoSlab-Regular.ttf")

#: What every measure the board is drawn at is multiplied by: 1.3, so
#: a card on the board is 260 by 355 of its art's 330 by 450, and every
#: chit, pill, word and gap round it grows with it, the board the same
#: picture a little larger (the author, 2026-10-12: a hero's level bands,
#: the smallest type any card prints, were mush at 200 by 273 when
#: zoomed; not the art's full size, "just a bit bigger so the font is
#: readable"). The board is composed at these pixels rather than scaled
#: after, since a picture scaled up gains no detail. Before it, the
#: composed board was scaled by 0.6 (until 2026-10-09: a card's name read
#: but not its rules) and 0.8 (still soft, Troq Bashar's card), then
#: drawn at 1. Each step up costs bytes: the staged mid-game board 332 KB
#: stacked at 1. Every measure below is written at 1 and passed through
#: `px`; the hand, the codex and the deck have their own and are not
#: scaled.
DRAW_SCALE = 1.3


def px(value):
    """A board measure written at a scale of 1, at `DRAW_SCALE`: a
    whole number of pixels for an integer, a fraction for a fraction."""
    if isinstance(value, int):
        return round(value * DRAW_SCALE)
    return value * DRAW_SCALE


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

# -- The panel's measures, in pixels, as the canvas's plan board gives them,
# at `DRAW_SCALE`.

#: A card: the art (330 by 450) at 61% at a scale of 1, 79% as drawn.
CARD = (px(200), px(273))
#: A grid cell, square so an exhausted card lies in it at full size
#: (the author, 2026-10-08: A of the canvas's three ways).
CELL = CARD[1]
#: Between two columns, two rows, and the patrol zone and the grid.
CELL_GAP = px(16)
#: Around the panel's edge.
PADDING = px(20)
#: The column of buildings, and the gap between it and the grid. The
#: column is the one-row grid's height (629 at a scale of 1), the add-on on top: every
#: building, chit and heart in it drawn at `BUILDING_SCALE` of the 160
#: wide the canvas gave it (the author, 2026-10-09: the buildings a
#: little smaller, so the column is no taller than one row).
BUILDING_WIDTH = px(136)
BUILDING_SCALE = BUILDING_WIDTH / 160
BUILDING_GAP = px(20)
#: A tech building's tile and the base's, in the art's proportions (350
#: by 250).
TILE = (px(136), px(97))
#: Between two places in the building column.
TILE_GAP = px(12)
#: A patrol slot's bonus strip, and the space above it.
BONUS = (CARD[0], px(41))
BONUS_GAP = px(6)
#: A patrol holder's blue padding round its slot and bonus, and the
#: gap between two holders. Each slot is its own holder, packed, rather
#: than one band with the slots spread over the grid's columns (the
#: author, 2026-10-09): a patroller is never exhausted -- exhausting
#: one sidelines it -- so a slot never needs a cell's width.
PATROL_PADDING = px(10)
PATROL_SLOT_GAP = px(12)
#: The add-on's card at the top of the building column, as wide as the
#: tech buildings and aligned with them, in the art's proportions (250
#: by 350). It was 82 by 114, too small to read; a card's size beside
#: the patrol slots was too large, and the add-on stays with the other
#: buildings (the author, 2026-10-09). As tall as leaves the column the
#: one-row grid's height exactly -- 193 rather than 190 at a scale of 1,
#: a stretch nobody sees.
ADD_ON = (TILE[0], 2 * PATROL_PADDING + BONUS_GAP + BONUS[1] + CELL_GAP + 2 * CARD[1]
          - 4 * TILE[1] - 4 * TILE_GAP)
#: A patrol holder's width.
PATROL_HOLDER = CARD[0] + 2 * PATROL_PADDING
#: The nameplate along the panel's outer edge, and the gap between it
#: and the rest.
NAMEPLATE_HEIGHT = px(56)
NAMEPLATE_GAP = px(12)
#: The stacked board's divider, and the side-by-side board's.
#: The divider is taller than the canvas's 36 so its label can be read
#: at a glance (the author, 2026-10-09: the turn more prominent).
DIVIDER_HEIGHT = px(52)
DIVIDER_WIDTH = px(80)
#: How far a chit hangs over a card's edge, which a body is drawn with
#: room for.
OVERHANG = px(12)
#: Where a card's art ends, from the card's top at `CARD`: the name's
#: banner starts below it (a hero's a little higher, at about 129). A
#: unit's or a hero's damage chits stand on the art's foot, clear of the
#: ATK and HP printed at the card's (the author, 2026-10-09).
ART_FOOT = px(122)
#: A unit's or a hero's ATK and HP as they stand now -- what everything
#: in play gives it, its runes, and, for HP, what is left once its damage
#: is taken off -- on a pill at the card's top right, read before
#: anything else on it (the author, 2026-10-11). The cost the card
#: prints top left is no question once it is in play, but stays, as the
#: level chit does on a hero. 38 tall, its two numbers in Roboto Slab
#: at 25, each half about as wide as it is tall.
STAT_HEIGHT = px(38)
STAT_SIZE = px(25)
#: How far the pill hangs over the card's top and right edges, as the
#: chits do, so that it covers less of the art (the author, 2026-10-11:
#: higher up, and a tad smaller, than the first build's 46 inside the
#: corner).
STAT_OVERHANG = px(10)
#: Two Step's chit on a dance partner, this far across -- the damage
#: chits' size (`lay_damage`) -- just left of the stats pill (the author,
#: 2026-10-15: it stood at the card's foot, bottom left, and then a
#: little smaller than the damage chits), and the gap between the two.
PARTNER_CHIT = px(62)
PARTNER_GAP = px(3)
#: The rune chits hang over the card's right edge by this, centred this
#: far down it -- a little below the card's middle, on the end of its
#: name's banner, clear of the stats above and of the damage chits that
#: stand on the art's foot (the author, 2026-10-11: from its top right,
#: which the stats now hold).
RUNE_HANG = px(20)
RUNE_CENTRE = px(150)
#: A named rune's chit -- Bloodburn's, Might of Leaf and Claw's -- across,
#: top right under the stats pill, and the size it is drawn at before.
NAMED_RUNE = px(52)
RUNE_CHIT_DRAWN = 160
#: The rune chits, one a colour (the author, 2026-10-11): the module's
#: blue swirl chit, its blue the colour's own and its yellow swirl the
#: second here -- on white the white cards' frame, and a deep gold, where
#: yellow would not show.
RUNE_CHIT_COLORS: dict[str, tuple[tuple[int, int, int], tuple[int, int, int]]] = {
    "red": ((176, 30, 36), (255, 214, 72)),
    "blue": ((3, 80, 168), (255, 227, 62)),
    "green": ((34, 122, 58), (238, 226, 80)),
    "white": ((232, 233, 229), (208, 156, 30)),
    "purple": ((104, 48, 156), (255, 214, 72)),
    "black": ((32, 32, 36), (232, 196, 64)),
}
#: Each named rune's colour: the colour of the card that puts it there.
#: A rune of a kind not here takes the colour of the card it is on.
RUNE_COLORS = {
    "blood": "red",                                  # Bloodburn
    "growth": "green", "feather": "green",           # Might of Leaf and Claw, Fairie Dragon
    "corpse": "black", "javelin": "black",           # Corpse Catapult, Skeleton Javelineer
    "sword": "white", "focus": "white",              # Grave Stormborne, Focus Master
    # A crumbling rune is Two Lives', which both white Garus Rook and blue
    # Justice Juggernaut have: the colour of the one it is on.
}
#: The swirl chit's own two colours, which `rune_chit` recolours.
SWIRL_BLUE = (3, 80, 168)
SWIRL_YELLOW = (255, 227, 62)
#: How far in from a card's left edge its printed cost reaches, which a
#: copy's number, beside the stats, keeps clear of.
COST_WIDTH = px(50)
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
#: COMMAND ZONE's type on the plate: 19 at a scale of 1, from 13 (the
#: author, 2026-10-12: larger).
COMMAND_LABEL_SIZE = px(19)
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
#: The gold count on its coin (`gold_coin`): the coin's own dark rim.
WORD_ON_GOLD = (74, 46, 6)
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
#: ARRIVED and DISABLED, on grey (the author, 2026-10-11): states, not
#: anything a card of a colour put there; a lent patroller's tag with
#: them -- "Lent from bo" (the author, 2026-10-15) -- the zone it lies
#: in not its owner's (multiplayer, Rulebook p. 14).
STATE_FILL = (104, 106, 112)     # #686a70
#: The widest a lent patroller's tag may be: inside the card, from where
#: `lay_states` stands it (`px(10)` in from the card's left edge) to the
#: same margin on the right. A longer name is cut with an ellipsis
#: (`lent_tag`), since a Discord name runs to 32 characters.
LENT_TAG_WIDTH = CARD[0] - 2 * px(10)
#: A tag on a card -- a feather rune (step 11), a copy, a jail, a number,
#: an oath (step 13), the buried, FUTURE -- is the colour of the card it
#: comes from (the author, 2026-10-11), and this purple where that card
#: is neutral. `MARK_SIZE` is its lettering, `MARK_STEP` a row of them.
MARK_FILL = (122, 74, 160)       # #7a4aa0
MARK_SIZE = px(15)
#: A white card's tag, true white (the author, 2026-10-11) -- whiter than
#: its rune chit, which is the white cards' frame.
WHITE_TAG = (245, 245, 245)
MARK_STEP = px(25)
#: How far below a card's top edge its tags may stand: clear of the
#: stats pill on the right and the cost on the left.
TAG_CEILING = px(46)
#: How far a tag may lie over a chit's edge -- a damage chit's top point
#: -- before either moves.
TAG_SLACK = px(10)
DESTROYED_FILL = (150, 40, 40)   # #962828
#: The stats' pill: ATK on the card's own black, HP on its red -- a step
#: brighter than the print's heart, so maroon stands apart from it --
#: and a stat that is not what the card prints on a colour of its own,
#: close to its plain one: slate for ATK, maroon for HP (the author,
#: 2026-10-11). Up or down is the same colour: the number says which.
STAT_ATK = (22, 22, 22)          # #161616
STAT_HP = (226, 36, 44)          # #e2242c
STAT_ATK_CHANGED = (78, 78, 88)  # #4e4e58, slate
STAT_HP_CHANGED = (122, 14, 30)  # #7a0e1e, maroon
STAT_EDGE = (240, 240, 240)
#: Armor, on a steel-blue shield after the HP (the author, 2026-10-12:
#: a squad leader's 2 HP read as all it could take, when its armor
#: takes the first point). Drawn only while it has any.
STAT_ARMOR = (52, 104, 168)      # #3468a8
STAT_ARMOR_SIZE = px(20)
#: How far the shield overlaps the pill's rounded right end.
STAT_ARMOR_OVERLAP = px(6)
#: A copy's number on a card, "#2" (the author, 2026-10-11): white with
#: dark words, as the divider's pill is, so it reads on any art.
COPY_FILL, COPY_INK = WORD, (24, 18, 14)
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


@lru_cache(maxsize=64)
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


def sized(picture: Image.Image, size: tuple[int, int]) -> Image.Image:
    """`picture` at `size`: a board piece cut at a card's size at a scale
    of 1, drawn at the board's (`DRAW_SCALE`)."""
    return picture if picture.size == size else picture.resize(size, Image.LANCZOS)


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
         fill, anchor: str = "lt", edge: int = 2, ink=INK) -> None:
    """A word on a rounded tag, edged `edge` wide: the tech picker's
    count of picks, and a card's marks on the board."""
    face = font(size)
    left, _, right, _ = draw.textbbox(at, text, font=face, anchor=anchor)
    # The height is a capital's, whatever the words: every tag one height,
    # its words centred on their capitals, a descender hanging into the
    # padding below (the author, 2026-10-12: "Skip draw/discard" sat high).
    _, top, _, bottom = draw.textbbox(at, "H", font=face, anchor=anchor)
    pad = size // 3
    # The box's last row and column are drawn, so it ends a pixel short.
    draw.rounded_rectangle((left - pad, top - pad, right + pad - 1, bottom + pad - 1),
                           radius=pad, fill=fill, outline=SHADOW, width=edge)
    draw.text(at, text, font=face, fill=ink, anchor=anchor)


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


#: A box on a canvas, (left, top, right, bottom).
Box = tuple[int, int, int, int]


def overlaps(one: Box, other: Box, slack: int = 0) -> bool:
    """Whether two boxes cross by more than `slack` up and down."""
    return (one[0] < other[2] and other[0] < one[2]
            and one[1] < other[3] - slack and other[1] < one[3] - slack)


def lay_row(canvas: Image.Image, chits: Sequence[Image.Image], width: int,
            corner: tuple[int, int], *, leftward: bool = False, upward: bool = False) -> Box:
    """Chits `width` across in a row from `corner` -- a top-left corner,
    or a top-right one going `leftward`, or a bottom one going `upward`
    -- each overlapping the last by a sixth: the box the row covers."""
    left, top = corner
    covered = (canvas.width, canvas.height, 0, 0)
    for chit in chits:
        piece = by_width(chit, width)
        x = left - piece.width if leftward else left
        y = top - piece.height if upward else top
        canvas.alpha_composite(piece, (x, y))
        covered = (min(covered[0], x), min(covered[1], y),
                   max(covered[2], x + piece.width), max(covered[3], y + piece.height))
        step = piece.width - width // 6
        left += -step if leftward else step
    return covered


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


@lru_cache(maxsize=64)
def _rune_chit(color: str, count: int) -> Image.Image:
    size = RUNE_CHIT_DRAWN
    swirl = board_piece("chits", "swirl.png").resize((size, size), Image.LANCZOS)
    pixels = np.asarray(swirl).astype(float)
    rgb, alpha = pixels[..., :3], pixels[..., 3:]
    blue, along = np.array(SWIRL_BLUE, float), np.subtract(SWIRL_YELLOW, SWIRL_BLUE)
    # How far each pixel is from the blue towards the yellow -- the edges
    # of the swirl between -- and the rim's brown, off that line, kept.
    yellow = np.clip(((rgb - blue) @ along) / (along @ along), 0, 1)[..., None]
    off = np.linalg.norm(rgb - (blue + yellow * along), axis=-1)
    rim = np.clip(off / 90 - 0.3, 0, 1)[..., None]
    disc, whirl = (np.array(part, float) for part in RUNE_CHIT_COLORS[color])
    shown = (disc * (1 - yellow) + whirl * yellow) * (1 - rim) + rgb * rim
    chit = Image.fromarray(np.concatenate([shown, alpha], -1).clip(0, 255).astype("uint8"), "RGBA")
    if count:
        # Centred on the disc -- the opaque pixels off the rim, which hangs
        # below and to the right -- by the number's own ink, not the font's.
        rows, cols = np.nonzero((alpha[..., 0] > 128) & (rim[..., 0] < 0.5))
        centre = ((cols.min() + cols.max()) / 2, (rows.min() + rows.max()) / 2)
        text, light = str(count), color == "white"
        # Small enough that the swirl shows round it.
        face, stroke = font(round(size * (0.5 if len(text) < 2 else 0.42))), size // 30
        draw = ImageDraw.Draw(chit)
        left, top, right, bottom = draw.textbbox((0, 0), text, font=face, stroke_width=stroke)
        draw.text((centre[0] - (left + right) / 2, centre[1] - (top + bottom) / 2), text,
                  font=face, fill=(30, 30, 30) if light else (255, 255, 255),
                  stroke_width=stroke, stroke_fill=(255, 255, 255) if light else (20, 20, 20))
    return chit


def rune_chit(color: str, count: int) -> Image.Image:
    """A named rune's chit: the swirl chit in `color` with `count` on it,
    or none where `count` is 0 -- a single rune alone."""
    return _rune_chit(color if color in RUNE_CHIT_COLORS else "blue", count).copy()


def copy_tag(canvas: Image.Image, centre: int, middle: int, number: int, turned: bool) -> None:
    """A copy's number, "#2", on a white tag centred on `centre` and on
    `middle` -- the stats pill's line, across the card's top edge (the
    author, 2026-10-11: on one line with the pill, and smaller) -- the
    right way up whether the card stands or lies exhausted, and on the
    far side of the table, `turned`, drawn upside down here so it reads
    the right way up once the panel is turned round: a number is matched
    to its button, so nobody should have to read it upside down."""
    face = font(px(21))
    text = f"#{number}"
    width, height = round(face.getlength(text)) + px(18), px(30)
    tag = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(tag)
    draw.rounded_rectangle((0, 0, width - 1, height - 1), radius=px(8), fill=COPY_FILL,
                           outline=SHADOW, width=px(2))
    draw.text((width / 2, height / 2), text, font=face, fill=COPY_INK, anchor="mm")
    canvas.alpha_composite(tag.rotate(180) if turned else tag,
                           (centre - width // 2, middle - height // 2))


def armor_shield(armor: int, height: int) -> Image.Image:
    """`armor` on a steel-blue shield `height` tall -- the pill's, top
    and bottom level with its middle -- edged white as the pill is:
    flat across the top, its sides straight to halfway and curving in
    to a point, wider for a number of two figures. Drawn four times
    over and shrunk, so its curve is smooth."""
    scale = 4
    width = max(round(height * 0.82),
                round(font(STAT_ARMOR_SIZE).getlength(str(armor))) + px(14))
    big_w, big_h = width * scale, height * scale
    edge = px(2) * scale
    # Edge to edge of the picture: the outline is drawn inside the shape.
    right, foot, shoulder = big_w - 1, big_h - 1, big_h * 0.48
    points = [(0, 0), (right, 0), (right, shoulder)]
    steps = 12
    for index in range(1, steps + 1):
        # A quarter ellipse from the right side's foot to the point.
        angle = index / steps * (math.pi / 2)
        x = right / 2 + right / 2 * math.cos(angle)
        y = shoulder + (foot - shoulder) * math.sin(angle)
        points.append((x, y))
    points += [(right - x, y) for x, y in reversed(points[3:-1])]
    points.append((0, shoulder))
    big = Image.new("RGBA", (big_w, big_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(big)
    draw.polygon(points, fill=STAT_ARMOR, outline=STAT_EDGE, width=edge)
    shield = big.resize((width, height), Image.LANCZOS)
    ImageDraw.Draw(shield).text((width / 2, height * 0.44), str(armor),
                                font=font(STAT_ARMOR_SIZE), fill=WORD, anchor="mm",
                                stroke_width=px(2), stroke_fill=SHADOW)
    return shield


def pill_rise(height: int) -> int:
    """How far a picture `height` tall that holds the stats pill rises
    above the pill (`beside_pill`): centred on the pill's line, but no
    higher than the room the card's drawing leaves above the pill, which
    `OVERHANG` round the card bounds -- a damage chit's size rises past
    it, so it hangs a little lower than the pill's line."""
    return min((height - STAT_HEIGHT) // 2, OVERHANG - STAT_OVERHANG)


def beside_pill(pill: Image.Image, chit: Image.Image) -> Image.Image:
    """`chit` at `PARTNER_CHIT` just left of the stats `pill`, as one
    picture: placed where the pill alone would be, less `pill_rise` of
    its height, the pill stands where it did and the chit beside it."""
    piece = by_width(chit, PARTNER_CHIT)
    height = max(piece.height, pill.height)
    whole = Image.new("RGBA", (piece.width + PARTNER_GAP + pill.width, height), (0, 0, 0, 0))
    whole.alpha_composite(piece, (0, 0 if height == piece.height else (height - piece.height) // 2))
    whole.alpha_composite(pill, (piece.width + PARTNER_GAP, pill_rise(height)))
    return whole


def stat_pill(stats: "Stats") -> Image.Image:
    """A unit's or a hero's ATK and HP as they stand, on one pill in two
    halves -- ATK on the card's black, HP on its red, either on its own
    colour where it is not what the card prints -- edged white, so it
    reads on any art, and its armor, while it has any, on a shield
    after the HP (`armor_shield`). Its foot is toward its player's edge
    of the table -- upside down on the far side, as the cards are --
    and stays there when the card is exhausted and lies on its side
    (the author, 2026-10-11)."""
    face = font(STAT_SIZE)
    height = STAT_HEIGHT
    atk_width, hp_width = (max(round(face.getlength(str(value))) + px(16), height - px(4))
                           for value in (stats.atk, stats.hp))
    width = atk_width + hp_width
    atk_fill = STAT_ATK_CHANGED if stats.atk_changed else STAT_ATK
    hp_fill = STAT_HP_CHANGED if stats.hp_changed else STAT_HP
    tag = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(tag)
    radius = height // 2
    draw.rounded_rectangle((0, 0, width - 1, height - 1), radius, fill=hp_fill)
    draw.rounded_rectangle((0, 0, atk_width + radius, height - 1), radius, fill=atk_fill)
    draw.rectangle((atk_width, 0, atk_width + radius, height - 1), fill=hp_fill)
    draw.rounded_rectangle((0, 0, width - 1, height - 1), radius, outline=STAT_EDGE, width=px(2))
    for centre, value in ((atk_width / 2 + px(2), stats.atk),
                          (atk_width + hp_width / 2 - px(2), stats.hp)):
        draw.text((centre, height / 2), str(value), font=face, fill=WORD, anchor="mm",
                  stroke_width=px(2), stroke_fill=SHADOW)
    if stats.armor <= 0:
        return tag
    shield = armor_shield(stats.armor, height)
    whole = Image.new("RGBA", (width - STAT_ARMOR_OVERLAP + shield.width, height),
                      (0, 0, 0, 0))
    whole.alpha_composite(tag, (0, 0))
    whole.alpha_composite(shield, (width - STAT_ARMOR_OVERLAP, 0))
    return whole


def tag_size(text: str) -> tuple[int, int]:
    """A card's tag's width and height as `pill` draws it: its words'
    width, a capital's height, and the padding round both."""
    face, pad = font(MARK_SIZE), MARK_SIZE // 3
    _, top, _, bottom = face.getbbox("H", anchor="ls")
    return round(face.getlength(text)) + 2 * pad, bottom - top + 2 * pad


def tag_at(draw: ImageDraw.ImageDraw, x: int, top: int, text: str, fill, ink,
           leftward: bool = False) -> None:
    """A card's tag with its box's top at `top`, from `x` -- its left
    edge, or its right going `leftward`."""
    face, pad = font(MARK_SIZE), MARK_SIZE // 3
    cap = -face.getbbox("H", anchor="ls")[1]
    pill(draw, (x - pad if leftward else x + pad, top + pad + cap), text, MARK_SIZE, fill,
         anchor="rs" if leftward else "ls", edge=px(2), ink=ink)


def tag_rows_lowest(foot: int) -> int:
    """The box top of a card's lowest row of tags, standing on `foot`,
    the foot of its art: the rows are `MARK_STEP` apart up from it, a
    row's box top `lowest - row * MARK_STEP`, a negative row under it."""
    return foot - px(4) - tag_size("H")[1]


def plan_marks(column_right: int, column_top: int, ceiling: int, foot: int,
               marks: Sequence[tuple[str, Optional[str]]]) -> list[tuple[str, Optional[str], Box]]:
    """Where a card's marks go: down its right edge, a row each, from the
    first row at or below `column_top` (under its rune chits) and not
    above `ceiling` (the stats)."""
    lowest = tag_rows_lowest(foot)
    row = (lowest - max(column_top, ceiling)) // MARK_STEP
    placed = []
    for mark, colour in marks:
        width, height = tag_size(mark)
        top = lowest - (row - len(placed)) * MARK_STEP
        placed.append((mark, colour, (column_right - width, top, column_right, top + height)))
    return placed


def lay_states(canvas: Image.Image, card_left: int, ceiling: int, foot: int,
               states: Sequence[str], clear_of: Sequence[Box]) -> None:
    """
    A lent card's tag, ARRIVED and DISABLED up a card's left edge from the
    foot of its art, on the marks' rows, each in the lowest row clear of `clear_of` -- the
    marks, the rune chits and the damage chits -- and not above
    `ceiling` (the cost); with none free, the lowest left (the author,
    2026-10-12: "Skip draw/discard" lay over DISABLED).
    """
    draw = ImageDraw.Draw(canvas)
    lowest = tag_rows_lowest(foot)
    highest = (lowest - ceiling) // MARK_STEP
    left = card_left + px(10)
    slack = TAG_SLACK
    placed: list[Box] = []
    for state in reversed(states):
        width, height = tag_size(state)
        boxes = {row: (left, lowest - row * MARK_STEP, left + width + px(4),
                       lowest - row * MARK_STEP + height) for row in range(highest + len(states) + 1)}
        free = [row for row in range(highest + 1)
                if not any(overlaps(boxes[row], other, slack) for other in clear_of)
                and not any(overlaps(boxes[row], other) for other in placed)]
        row = free[0] if free else min(row for row in boxes
                                       if not any(overlaps(boxes[row], other) for other in placed))
        placed.append(boxes[row])
    # The rows they found, lowest first, so ARRIVED stays under DISABLED
    # and a lent card's tag under both.
    for state, top in zip(reversed(states), sorted((box[1] for box in placed), reverse=True)):
        tag_at(draw, left, top, state, STATE_FILL, INK)


def lay_damage(canvas: Image.Image, damage: int, right: int, foot: int,
               clear_of: Sequence[Box]) -> Optional[Box]:
    """A card's damage chits standing on the foot of its art, from its
    right edge leftward, clear of the ATK and HP the card prints -- and,
    where its rune chits or marks stand beside the foot, from the left
    of them (the author, 2026-10-12: a rune chit hid the damage); a tag
    over no more than a chit's top point, `TAG_SLACK`, leaves it be."""
    if not damage:
        return None
    chits = damage_chits(damage)
    height = by_width(chits[0], px(62)).height
    band = (0, foot - height, canvas.width, foot)
    start = min([right - px(10)] + [box[0] - px(4) for box in clear_of
                                     if overlaps(box, band, TAG_SLACK)])
    return lay_row(canvas, chits, px(62), (start, foot), leftward=True, upward=True)


# -- A card as it lies ---------------------------------------------------------


@dataclass(frozen=True)
class Stats:
    """A unit's or a hero's ATK and HP as the board shows them: as they
    stand, HP what is left, and whether each is other than the card's
    face prints -- a hero's, its level's band."""

    atk: int
    hp: int
    atk_changed: bool
    hp_changed: bool
    #: What is left of its armor this turn (`armor` on the body), on a
    #: shield after the HP; none drawn at 0.
    armor: int = 0
    #: The effects across a side that reach it, by the slug of the card
    #: that makes them (`RulesEngine.auras_on`): each a tag by its name.
    auras: tuple[str, ...] = ()
    #: The card that keeps a unit from attacking and patrolling for now,
    #: by its slug (`RulesEngine.barred_by`): a tag in its colour,
    #: `BARRED_TAGS`. Never a card's own printed "can't patrol".
    barred_by: Optional[str] = None


#: Where a body's ATK and HP as they stand come from -- the engine's
#: `board_reading`, which the frontend hands in, and which names the
#: effects across a side that reach it and what keeps it from attacking
#: and patrolling for now too (`body_stats`, its ATK and HP alone, does as well): the renderer
#: reads a position and decides no rule.
StatsOf = Callable[[MatchState, Union[CardInstance, HeroState]], "tuple"]


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
    #: The named runes besides +1/+1 and -1/-1 (step 11) -- blood,
    #: growth, a feather -- as (colour, count), each a swirl chit in
    #: its colour with its count on it, unnamed (the author, 2026-10-11);
    #: a count of 0 is a single rune alone, a chit with no number.
    named_runes: tuple[tuple[str, int], ...] = ()
    #: What a chit cannot say, as tags under them -- "Feather",
    #: "Copy: Fox Viper", "Number 3" -- each with the colour of the card
    #: it comes from (`label_colors`).
    marks: tuple[tuple[str, Optional[str]], ...] = ()
    #: Its time runes (step 12): fading on a card in play, Prynn's on
    #: her, forecast on a card in the future -- the module's chit.
    time_runes: int = 0
    #: Disabled (step 12): a mark beside where the exhaust glyph goes.
    disabled: bool = False
    #: Lent into another player's patrol zone at a free-for-all's lock
    #: (Rulebook p. 14) -- a unit with `lent` set, a hero with `lent_to`
    #: -- the tag it carries beside ARRIVED and DISABLED: "Lent from
    #: bo", or "Lent" where the frontend gave no name (`lent_tag`),
    #: since the card lies in a zone that is not its owner's, which the
    #: board says nowhere else. `None` while it is its owner's.
    lent: Optional[str] = None
    #: A card in the future (step 12): greyed, not yet in play.
    future: bool = False
    #: Which of its player's copies in play it is, "#2" on its top edge
    #: -- the number its buttons carry (`formatting.copy_number`); 0
    #: where it is the only one.
    copy: int = 0
    #: Its ATK and HP as they stand (`Stats`), on a pill top right: a
    #: unit's or a hero's on the field, given the engine's reading.
    stats: Optional[Stats] = None


#: What Polymorph: Squirrel shows a unit as while it lasts.
POLYMORPHED = "squirrel"


#: The named runes that are one alone, so a tag of their own needs no
#: count: a feather, a crumbling rune (step 13).
SINGLE_RUNES = ("feather", "crumbling")


#: The runes a chit alone does not name: a feather, on a unit whose
#: own text never mentions one. Blood, growth, a crumbling rune and the
#: rest sit on the card whose text says what they are.
NAMED_ON_THE_CHIT = ("feather",)


def rune_color(card, kind: str, cards: Optional[CardCatalog] = None) -> str:
    """A named rune's colour: `RUNE_COLORS`', or the card's it is on."""
    if kind in RUNE_COLORS:
        return RUNE_COLORS[kind]
    return card_color(card.slug, cards) or "blue"


def rune_counts(card, cards: Optional[CardCatalog] = None) -> tuple[tuple[str, int], ...]:
    """A card's or a hero's named runes as (colour, count) for
    `rune_chit`: its count, or 0 for a single rune alone."""
    return tuple(
        (rune_color(card, kind, cards), 0 if count == 1 and kind in SINGLE_RUNES else count)
        for kind, count in sorted((getattr(card, "runes", None) or {}).items()) if count
    )


#: The card a tag on another card comes from, where it is not the card
#: it is on: a copy is Manufactured Truth's. A jail's, a number's, an
#: oath's tag is on the card that holds it -- Jail, Reputable Newsman,
#: Oathkeeper of Kor Mountain.
COPY_FROM = "manufactured_truth"
#: Oathkeeper of Kor Mountain's two oaths, as its tag says them.
OATH_TAGS = {"hand": "Play no cards", "draw": "Skip draw/discard"}


def card_color(slug: str, cards: Optional[CardCatalog]) -> Optional[str]:
    """A card's or a hero's colour, lowered -- "blue", "neutral" -- or
    `None` with no catalog or no such card."""
    found = (cards.cards.get(slug) or cards.heroes.get(slug)) if cards else None
    return (getattr(found, "color", None) or "").strip().lower() or None


def label_colors(colour: Optional[str]) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """A tag's fill and lettering in a card's colour: its rune chit's
    disc, dark letters on white; the plain purple for a neutral card."""
    if colour not in RUNE_CHIT_COLORS:
        return MARK_FILL, INK
    if colour == "white":
        return WHITE_TAG, (30, 30, 30)
    return RUNE_CHIT_COLORS[colour][0], INK


def rune_marks(card, cards: Optional[CardCatalog] = None) -> tuple[tuple[str, Optional[str]], ...]:
    """What a card's or a hero's chits cannot say, as tags, each with the
    colour of the card it comes from: a feather rune's name, its chit's
    green, and, on a card (step 13), "Copy: Fox Viper", "Jail: Iron
    Man", "3" (Reputable Newsman's number), "Skip draw/discard", and a
    Graveyard's units by name. Its runes are chits (`rune_counts`)."""
    found: list[tuple[str, Optional[str]]] = [
        (kind.title(), rune_color(card, kind, cards))
        for kind, count in sorted((getattr(card, "runes", None) or {}).items())
        if count and kind in NAMED_ON_THE_CHIT
    ]
    if not isinstance(card, CardInstance):
        return tuple(found)
    name = cards.name if cards is not None else (lambda slug: slug.replace("_", " ").title())
    own = card_color(card.slug, cards)
    if card.copy_of:
        found.append((f"Copy: {name(card.copy_of)}", card_color(COPY_FROM, cards)))
    if card.jailed:
        found.append((f"Jail: {name(card.jailed['slug'])}", own))
    if card.number is not None:
        found.append((str(card.number), own))
    if card.oath:
        found.append((OATH_TAGS.get(card.oath, card.oath), own))
    # The units a Graveyard holds, by name (the author, 2026-10-11).
    found.extend((name(buried["slug"]), own) for buried in card.buried or ())
    return tuple(found)


#: The modifiers an effect leaves on a unit or a hero for a while -- to
#: the end of the turn, a seat's next upkeep, Vandy's doom -- that the
#: stats pill cannot show, as their tags: the effect's name alone, never
#: how long it lasts (the author, 2026-10-12). A keyword is its own name.
#: ATK, HP and armor are the pill's; a copy, a polymorph and DISABLED are
#: shown already.
LASTING_UNTIL = ("end_of_turn", "upkeep", "doom")
MODIFIER_TAGS = {
    "doomed": "Doomed",                  # Vandy Anadrose at max
    "illusion": "Illusion",              # Hallucination
    "cant_attack": "Can't attack",       # Sparring Partner
    "no_level": "Can't level up",        # Nether Drain
    "bloodlust": "Bloodlust",            # its damage at the end of the turn
}
#: The cards whose modifiers come together, so one tag says them all, or
#: none is needed (the author, 2026-10-12): Gargoyle's flying, ATK and
#: attacking come with its not being indestructible; Kidnapping's haste
#: with being kidnapped (`returns_to`, tagged on its own); Poisonblade
#: Rogue's own attack needs none. Rampant Growth's +2 ATK and +2 armor
#: and Dinosize's +6 and +6, which the pill shows, are tagged by name all
#: the same.
TAGGED_AS = {
    "rampant_growth": "Rampant Growth",
    "dinosize": "Dinosize",
    "gargoyle": "Not indestructible",
    "kidnapping": None,
    "poisonblade_rogue": None,
}
#: What keeps a unit from attacking and patrolling for now, by the card
#: that does (`RulesEngine.barred_by`), as its tag: each card's own word
#: for it (the author, 2026-10-13).
BARRED_TAGS = {
    "terras_q_the_shackled": "Shackled",
    "entangling_vines": "Entangled",
}
#: A kidnapped unit, back to its controller at the end of the turn.
KIDNAPPED_FROM = "kidnapping"


def effect_tags(body, cards: Optional[CardCatalog], auras: Sequence[str] = (),
                barred_by: Optional[str] = None) -> tuple[tuple[str, Optional[str]], ...]:
    """What lasting effects a unit or a hero carries, as tags in the
    colour of the card each comes from (its modifier's `from`): the
    keywords and the rest an effect gave it for a while, Kidnapping's
    hold, the effects across a side that reach it, `auras`, by the
    name of the card that makes each -- Ferocity, Stampede, Dreamscape --
    and what keeps it from attacking and patrolling for now, `barred_by`:
    "Shackled" on Terras Q, "Entangled" under Entangling Vines."""
    found: list[tuple[str, Optional[str]]] = []
    for modifier in body.modifiers:
        if modifier.get("until") not in LASTING_UNTIL:
            continue
        kind, source = modifier.get("kind"), modifier.get("from") or ""
        if source in TAGGED_AS:
            if TAGGED_AS[source]:
                found.append((TAGGED_AS[source], card_color(source, cards)))
            continue
        if kind == "keyword":
            amount = modifier.get("amount")
            text = modifier["keyword"] + (f" {amount}" if amount else "")
        elif kind == "lose_keyword":
            text = f"Not {modifier['keyword'].lower()}"
        else:
            text = MODIFIER_TAGS.get(kind)
        if text:
            found.append((text, card_color(source, cards)))
    if getattr(body, "returns_to", None) is not None:
        found.append(("Kidnapped", card_color(KIDNAPPED_FROM, cards)))
    for slug in auras:
        found.append((cards.name(slug) if cards else slug.replace("_", " ").title(),
                      card_color(slug, cards)))
    if barred_by is not None:
        found.append((BARRED_TAGS.get(barred_by, "Can't attack or patrol"),
                      card_color(barred_by, cards)))
    seen: set[str] = set()
    return tuple(tag for tag in found if not (tag[0] in seen or seen.add(tag[0])))


def shown_slug(card: CardInstance) -> str:
    """The card whose face a card in play shows: a Squirrel's while
    Polymorph: Squirrel has it (step 11)."""
    return POLYMORPHED if (card.printed or {}).get("polymorph") is not None else card.slug


def shown_stats(match: MatchState, body: Union[CardInstance, HeroState], cards: CardCatalog,
                stats_of: Optional[StatsOf]) -> Optional[Stats]:
    """A unit's or a hero's `Stats`, against what the face it shows
    prints -- none for anything else, or with no `stats_of`."""
    if stats_of is None:
        return None
    if isinstance(body, CardInstance):
        printed = cards.cards[shown_slug(body)]
        if not cards.cards[body.slug].is_unit:
            return None
        printed_atk, printed_hp = printed.atk or 0, printed.hp or 0
    else:
        band = cards.heroes[body.slug].band(body.level)
        printed_atk, printed_hp = band.atk, band.hp
    reading = stats_of(match, body)
    atk, hp = reading[0], reading[1]
    left = hp - body.damage
    return Stats(atk, left, atk != printed_atk, left != printed_hp, body.armor,
                 tuple(reading[2]) if len(reading) > 2 else (),
                 reading[3] if len(reading) > 3 else None)


def lent_tag(lender: Optional[str]) -> str:
    """The tag a lent patroller carries: "Lent from bo", the lender's
    name as the frontend gives it and the nameplate spells it (the
    author, 2026-10-15: whose it is, not only that it is not the
    borrower's, and said as a sentence rather than the possessive
    "BO'S"), the name cut with an ellipsis to `LENT_TAG_WIDTH`; "Lent"
    where the frontend gave no name."""
    if not lender:
        return "Lent"
    name = lender
    while len(name) > 1 and tag_size(f"Lent from {name}")[0] > LENT_TAG_WIDTH:
        name = name[:-2 if name.endswith("…") else -1].rstrip() + "…"
    return f"Lent from {name}"


def unit_lying(card: CardInstance, partnered: bool, cards: Optional[CardCatalog] = None,
               copy: int = 0, stats: Optional[Stats] = None,
               lender: Optional[str] = None) -> Lying:
    """A card in play as it lies -- a Squirrel's art while Polymorph:
    Squirrel has it (step 11) -- `copy`, its number among its
    player's copies, `stats`, its ATK and HP as they stand and the
    effects across a side that reach it, and `lender`, its owner's name
    as the frontend gives it, read only where the card is lent."""
    return Lying(shown_slug(card), damage=card.damage, plus_runes=card.plus_runes,
                 minus_runes=card.minus_runes, partnered=partnered,
                 arrived=card.arrived_this_turn, exhausted=card.exhausted,
                 named_runes=rune_counts(card, cards),
                 marks=rune_marks(card, cards)
                 + effect_tags(card, cards, stats.auras if stats is not None else (),
                               stats.barred_by if stats is not None else None),
                 time_runes=card.time_runes,
                 disabled=card.disabled, lent=lent_tag(lender) if card.lent else None,
                 copy=copy, stats=stats)


def future_lying(card: CardInstance) -> Lying:
    """A card in the future (step 12, UMR p. 17) as it waits: greyed, its
    time runes on it."""
    return Lying(card.slug, time_runes=card.time_runes, future=True)


def hero_lying(hero: HeroState, cards: CardCatalog, stats: Optional[Stats] = None,
               lender: Optional[str] = None) -> Lying:
    """A hero in play as it lies; `lender`, its owner's name as the
    frontend gives it, read only where the hero is lent."""
    return Lying(hero.slug, level=level_chit(hero, cards), damage=hero.damage,
                 plus_runes=hero.plus_runes, minus_runes=hero.minus_runes,
                 arrived=hero.arrived_this_turn, exhausted=hero.exhausted,
                 time_runes=hero.time_runes, disabled=hero.disabled,
                 lent=lent_tag(lender) if hero.lent_to is not None else None,
                 named_runes=rune_counts(hero, cards),
                 marks=rune_marks(hero)
                 + effect_tags(hero, cards, stats.auras if stats is not None else ()),
                 stats=stats)


def card_face(slug: str, cards: CardCatalog, size: tuple[int, int] = CARD) -> Image.Image:
    return rounded(card_picture(slug, cards).convert("RGBA").resize(size, Image.LANCZOS),
                   round(size[0] / 20))


def lying_card(lying: Lying, cards: CardCatalog, turned: bool = False) -> Image.Image:
    """
    One card as it lies in a cell, on a transparent square of `CELL`
    with `OVERHANG` round it, the card's centre the square's: its own
    art at `CARD`, its ATK and HP as they stand top right, a level
    chit top left (a hero), its rune chits over its right edge a little
    below its middle, its damage chits on the foot of its art, Two
    Step's chit on a dance partner just left of its stats, ARRIVED on
    its art's foot the turn it came and its lender's name while it
    patrols for another player, a copy's number on its top edge -- and,
    exhausted, the
    whole of it turned on its side at full size, lying across the cell,
    with the exhaust glyph on the cell's top corner and its stats on
    the turned card's top right, both level with the table -- left of
    a hero's level chit, which the turn carries to that corner.
    """
    margin = OVERHANG
    # Wider at the sides than `OVERHANG`, for the rune chits that hang
    # over the right edge.
    side = RUNE_HANG + px(4)
    upright = Image.new("RGBA", (CARD[0] + 2 * side, CARD[1] + 2 * margin), (0, 0, 0, 0))
    face = card_face(lying.slug, cards)
    if lying.exhausted:
        face = dimmed(face, 0.75)
    if lying.future:
        face = greyed(face, 0.7)
    upright.alpha_composite(face, (side, margin))
    right, bottom = side + CARD[0], margin + CARD[1]
    level_box = None
    if lying.level is not None:
        level_box = lay_row(upright, [lying.level], px(62), (side - px(10), margin - px(10)))
    runes = rune_chits(lying.plus_runes, lying.minus_runes)
    if runes:
        lay_row(upright, runes, px(50), (right + RUNE_HANG, margin + RUNE_CENTRE - px(25)),
                leftward=True)
    stats = stat_pill(lying.stats) if lying.stats is not None else None
    if lying.partnered and stats is not None:
        stats = beside_pill(stats, board_piece("chits", "two_step.png"))
    elif lying.partnered:
        lay_row(upright, [board_piece("chits", "two_step.png")], px(50),
                (side - px(8), bottom + px(8)), upward=True)
    # How far the pill's picture rises above the pill: a partner's chit
    # is taller than the pill it stands beside.
    stats_rise = pill_rise(stats.height) if stats is not None else 0
    # Every rune in one column under the stats pill, its tags under it
    # (the author, 2026-10-11): the time runes first -- a purple card's,
    # in its colour -- then the named runes; FUTURE under the time runes.
    own = card_color(lying.slug, cards)
    named = list(lying.named_runes)
    marks = list(lying.marks)
    if lying.time_runes:
        named.insert(0, (own if own in RUNE_CHIT_COLORS else "purple", lying.time_runes))
    if lying.future:
        marks.insert(0, ("FUTURE", own))
    top = margin + px(60)
    column: list[Box] = []
    for colour, count in named:
        column.append(lay_row(upright, [rune_chit(colour, count)], NAMED_RUNE, (right - px(6), top),
                              leftward=True))
        top += NAMED_RUNE + px(4)
    foot = margin + ART_FOOT
    planned = plan_marks(right - px(6), top if named else margin, margin + TAG_CEILING, foot, marks)
    column += [box for _, _, box in planned]
    damage = lay_damage(upright, lying.damage, right, foot, column)
    column += [damage] if damage else []
    draw = ImageDraw.Draw(upright)
    for mark, colour, box in planned:
        tag_at(draw, box[2], box[1], mark, *label_colors(colour), leftward=True)
    # Lowest last: "Lent from <name>" on the foot, ARRIVED over it,
    # DISABLED over that.
    states = [state for state, on in (("DISABLED", lying.disabled), ("ARRIVED", lying.arrived),
                                      (lying.lent, lying.lent is not None)) if on]
    lay_states(upright, side, margin + TAG_CEILING, foot, states, column)
    if stats is not None and not lying.exhausted:
        upright.alpha_composite(stats, (right + STAT_OVERHANG - stats.width,
                                        margin - STAT_OVERHANG - stats_rise))

    tile = Image.new("RGBA", (CELL + 2 * margin, CELL + 2 * margin), (0, 0, 0, 0))
    if not lying.exhausted:
        laid = upright
    else:
        # Turned a quarter clockwise, as a card is exhausted on a table.
        laid = upright.transpose(Image.ROTATE_270)
    left, top = paste_centred(tile, laid, (0, 0, tile.width, tile.height))
    card_top = top + (side if lying.exhausted else margin)
    if stats is not None and lying.exhausted:
        # Level with the table, on the turned card's top right -- over
        # its cost, the card's own top left once turned.
        # A hero's level chit turns with the card to that same corner,
        # so the pill stands just left of it (the author, 2026-10-15).
        stats_right = left + margin + CARD[1] + STAT_OVERHANG
        if level_box is not None:
            stats_right = min(stats_right, left + upright.height - level_box[3] - px(4))
        tile.alpha_composite(stats, (stats_right - stats.width,
                                     card_top - STAT_OVERHANG - stats_rise))
    copy_centre = left + laid.width // 2
    if stats is not None and not lying.exhausted:
        # A standing card's top edge holds the cost top left and the
        # stats top right: its copy's number goes between them.
        copy_centre = left + side + (COST_WIDTH + CARD[0] + STAT_OVERHANG - stats.width) // 2
    if lying.copy:
        copy_tag(tile, copy_centre, card_top - STAT_OVERHANG + STAT_HEIGHT // 2, lying.copy,
                 turned)
    if lying.exhausted:
        glyph = by_width(image(EMOJI_DIR / "codex_exhaust.png"), px(48))
        tile.alpha_composite(glyph, (margin + px(8), margin + px(8)))
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
    and COMMAND ZONE along its foot. The slots stand in the plate's
    middle, its edge showing round them on every side, so a hero lying
    in one reads as in the zone from either end of the table, the far
    panel's turned round (the author, 2026-10-12: it stood at the top,
    the plate's edge hidden behind it), and COMMAND ZONE is set in the
    plate's margin under them at `COMMAND_LABEL_SIZE`. Drawn with
    `OVERHANG` round it for the chits.
    """
    margin = OVERHANG
    width = command_zone_width(len(heroes_in_zone))
    tile = Image.new("RGBA", (width + 2 * margin, PATROL_HEIGHT + 2 * margin), (0, 0, 0, 0))
    draw = ImageDraw.Draw(tile)
    draw.rounded_rectangle((margin, margin, margin + width - 1, margin + PATROL_HEIGHT - 1),
                           radius=px(14), fill=PLATE_FILL, outline=PLATE_EDGE, width=px(2))
    top = margin + (PATROL_HEIGHT - CARD[1]) // 2
    face = font(COMMAND_LABEL_SIZE, bold=False)
    label = "COMMAND ZONE"
    # Centred in the margin between the slots' foot and the plate's.
    spaced_text(draw, (margin + (width - spaced_width(label, face, px(2))) / 2,
                       (top + CARD[1] + margin + PATROL_HEIGHT) / 2),
                label, face, PLATE_INK, px(2))
    for index, hero in enumerate(heroes_in_zone):
        left = margin + PATROL_PADDING + index * (CARD[0] + COMMAND_SLOT_GAP)
        if hero is None:
            dashed_box(draw, (left, top, left + CARD[0], top + CARD[1]), PLATE_EDGE)
            word = "HERO"
            hero_face = font(px(18), bold=False)
            spaced_text(draw, (left + (CARD[0] - spaced_width(word, hero_face, px(2))) / 2,
                               top + CARD[1] / 2 - px(11)),
                        word, hero_face, FAINT_INK, px(2))
            continue
        tile.alpha_composite(card_face(hero.slug, cards, CARD), (left, top))
        if hero.summoning_runes:
            lay_row(tile, [time_rune_chit(hero.summoning_runes)], px(54),
                    (left - px(8), top - px(8)))
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
DESTROYED_STRIP = ("DESTROYED", DESTROYED_FILL, WORD)
#: A two-headed dragon team's one base, on each teammate's column.
JOINT_STRIP = ("JOINT", PATROL_BLUE, WORD)
#: A strip's height, how far it runs past the picture's edges on either
#: side, as tape wrapped round it, and its slope: rising from the
#: bottom left to the top right, close to level with a little slant (the author,
#: 2026-10-10), long enough for UNDER CONSTRUCTION in a type that reads
#: at Discord's scale.
STRIP_HEIGHT = px(22)
STRIP_OUT = px(5)
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
    draw.rectangle((0, 0, length - 1, STRIP_HEIGHT - 1), outline=SHADOW, width=px(2))
    face = font(px(11))
    width = spaced_width(word, face, px(0.3))
    spaced_text(draw, ((length - width) / 2, STRIP_HEIGHT / 2), word, face, ink, px(0.3))
    band = band.rotate(STRIP_ANGLE, resample=Image.BICUBIC, expand=True)
    canvas.alpha_composite(band, ((left + right - band.width) // 2,
                                  (top + bottom - band.height) // 2))


def lay_band(canvas: Image.Image, box: tuple[int, int, int, int],
             strip: tuple[str, tuple, tuple]) -> None:
    """A level band along the bottom of the picture at `box`, inset from
    its edges, its word centred: a label that leaves the picture's name
    and its heart clear, where `lay_strip`'s diagonal would cross them."""
    word, fill, ink = strip
    left, top, right, bottom = box
    inset = px(6)
    band = (left + inset, bottom - inset - STRIP_HEIGHT, right - inset, bottom - inset)
    draw = ImageDraw.Draw(canvas)
    draw.rectangle(band, fill=fill + (255,), outline=SHADOW, width=px(2))
    face = font(px(11))
    width = spaced_width(word, face, px(0.3))
    spaced_text(draw, ((band[0] + band[2] - width) / 2, (band[1] + band[3]) / 2), word, face, ink,
                px(0.3))


def damaged(hp: int, full: int) -> Optional[int]:
    """The HP a building's heart carries in place of its printed one:
    none while it is whole."""
    return hp if hp < full else None


def draw_building_column(body: Image.Image, player: PlayerState, base: int,
                         building_hp: Mapping[str, int], left: int, bottom: int,
                         joint: bool = False) -> None:
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
    `joint`, the base is a two-headed dragon team's one base, drawn on
    both teammates' columns with JOINT along its foot (`JOINT_STRIP`,
    `lay_band`; the author, 2026-10-15).
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
            # The spec chosen at Tech II, its card drawn on the tile
            # (UMR p. 8: "Place that card on your base"), large enough
            # to read at Discord's scale. It lies over the tile's lower
            # right -- the cost and the heart left clear -- and hangs
            # into the gap before the grid as far as an upright card in
            # the first column leaves free; the grid is drawn after it.
            mark = spec_mark(player.tech2_spec, SPEC_ON_TILE)
            body.alpha_composite(mark, (left + TILE[0] + SPEC_OUT - SPEC_ON_TILE[0],
                                        y + TILE[1] + TILE_GAP - px(2) - SPEC_ON_TILE[1]))
        if state is not None and (state.destroyed or state.under_construction):
            lay_row(body, [house], HOUSE_CHIT, (left - CHIT_OUT, y - CHIT_OUT))
            lay_strip(body, (left, y, left + TILE[0], y + TILE[1]),
                      DESTROYED_STRIP if state.destroyed else CONSTRUCTION_STRIP)
        y += TILE[1] + TILE_GAP

    # The heart carries the base's HP wherever it is not the 20 printed:
    # below it, as any building's; above it, a dragon team's 30
    # (Rulebook p. 13).
    tile = building_tile("base", base if base != building_hp["base"] else None)
    if base <= 0:
        tile = greyed(tile, 0.35)
    body.alpha_composite(tile, (left, y))
    if base <= 0:
        lay_strip(body, (left, y, left + TILE[0], y + TILE[1]), DESTROYED_STRIP)
    elif joint:
        lay_band(body, (left, y, left + TILE[0], y + TILE[1]), JOINT_STRIP)


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
                  font=font(px(18), bold=False), fill=FAINT_INK, anchor="mm")
        return
    hp = damaged(add_on.hp, building_hp.get(add_on.slug, add_on.hp))
    card = rounded(building_picture(add_on.slug, hp).resize(ADD_ON, Image.LANCZOS),
                   round(ADD_ON[0] / 20))
    body.alpha_composite(card, slot[:2])
    if add_on.spec:
        # A tech lab's spec card, drawn small on its card (UMR p. 9).
        mark = spec_mark(add_on.spec, SPEC_ON_LAB)
        body.alpha_composite(mark, (slot[0] + (ADD_ON[0] - SPEC_ON_LAB[0]) // 2,
                                    slot[3] - SPEC_ON_LAB[1] - px(8)))
    if add_on.under_construction:
        lay_row(body, [board_piece("chits", "house.png")], HOUSE_CHIT,
                (slot[0] - CHIT_OUT, slot[1] - CHIT_OUT))
        lay_strip(body, slot, CONSTRUCTION_STRIP)


#: A chosen spec's card as it lies on the tech II tile and on a tech
#: lab's card: the module's spec card. On the tile it was 70 by 50 at
#: the column's scale, too small to read on Discord (the author,
#: 2026-10-13); `SPEC_OUT` is how far it hangs past the tile's right
#: edge, to just short of where an upright card in the grid's first
#: column begins.
SPEC_ON_TILE = (round(120 * BUILDING_SCALE), round(86 * BUILDING_SCALE))
SPEC_OUT = BUILDING_GAP + (CELL - CARD[0]) // 2 - px(6)
SPEC_ON_LAB = (px(96), px(69))


def spec_mark(spec: str, size: tuple[int, int]) -> Image.Image:
    """A spec's card (`specs/<spec>.png`, cut at step 1) at `size`,
    rounded and edged so it reads on the tile under it."""
    picture = board_piece("specs", f"{spec}.png").resize(size, Image.LANCZOS)
    mark = rounded(picture, px(5))
    ImageDraw.Draw(mark).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=px(5),
                                           outline=(20, 16, 12, 255), width=px(2))
    return mark


def dashed_box(draw: ImageDraw.ImageDraw, box, fill, dash: int = px(6),
               width: int = px(2)) -> None:
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


def grid_cells(player: PlayerState, cards: CardCatalog, turned: bool = False,
               stats: Optional[Callable[[Union[CardInstance, HeroState]], Optional[Stats]]] = None,
               names: Optional[Mapping[int, str]] = None) -> list[Image.Image]:
    """The grid, in order: the heroes on the field, then the units,
    every one not patrolling, then the building cards and upgrades,
    which never patrol (step 10), then the cards in the future, greyed
    with their time runes (step 12). The heroes off the field are in
    the command zone, above. `stats`, each unit's and hero's `Stats`;
    `names`, the seats' names, for a lent unit's tag (one sidelined
    off its slot waits here for the upkeep that sends it home)."""
    stats = stats or (lambda body: None)
    names = names or {}
    field = [lying_card(hero_lying(hero, cards, stats(hero)), cards, turned)
             for hero in heroes(player) if hero.in_play and hero.patrol_slot is None]
    partners = partner_ids(player)
    lying = [card for card in player.play if card.patrol_slot is None]
    lying.sort(key=lambda card: cards.cards[card.slug].is_permanent)
    units = [lying_card(unit_lying(card, card.id in partners, cards, copy_number(player, card),
                                   stats(card), lender=names.get(card.owner)),
                        cards, turned) for card in lying]
    future = [lying_card(future_lying(card), cards) for card in player.future]
    return field + units + future


PATROL_HEIGHT = 2 * PATROL_PADDING + CARD[1] + BONUS_GAP + BONUS[1]


def body_height(cells: int, columns: int) -> int:
    rows = max(1, -(-cells // columns))
    grid = PATROL_HEIGHT + CELL_GAP + rows * CELL + (rows - 1) * CELL_GAP
    return max(grid, BUILDING_COLUMN_HEIGHT)


def render_body(match: MatchState, seat: int, cards: CardCatalog,
                building_hp: Mapping[str, int], turned: bool = False,
                stats: Optional[StatsOf] = None,
                names: Optional[Mapping[int, str]] = None) -> Image.Image:
    """
    One panel's body, the nameplate aside, on a transparent ground with
    `OVERHANG` round it for the chits that hang over an edge -- so the
    far panel's is turned round whole about its own centre. `turned`,
    it is about to be: a copy's number is drawn to read upright after.
    `stats`, the engine's `board_reading`. `names`, what the frontend
    calls each seat: a lent patroller's tag is its lender's.
    """
    player = match.player(seat)
    columns = panel_columns(player)
    names = names or {}

    def shown(body):
        return shown_stats(match, body, cards, stats)

    cells = grid_cells(player, cards, turned, shown, names)
    inner_width = panel_width(len(heroes(player))) - 2 * PADDING
    height = body_height(1 + len(cells), columns)
    body = Image.new("RGBA", (inner_width + 2 * OVERHANG, height + 2 * OVERHANG), (0, 0, 0, 0))
    o = OVERHANG
    # A dragon team's one base is drawn on both teammates' columns, marked
    # JOINT (the author, 2026-10-15).
    draw_building_column(body, player, match.base_of(seat), building_hp, o, o + height,
                         joint=match.is_dragon)

    grid_left = o + BUILDING_WIDTH + BUILDING_GAP
    # The gold, a coin filling the gap between the base -- the column's
    # foot -- and the grid, level with the base.
    coin = gold_coin(player.gold, BUILDING_GAP, turned)
    body.alpha_composite(coin, (o + BUILDING_WIDTH,
                                round(o + height - TILE[1] / 2 - coin.height / 2)))
    draw = ImageDraw.Draw(body)
    partners = partner_ids(player)
    card_top = o + PATROL_PADDING
    # The command zone first, beside the buildings, as on the mat.
    zone = command_zone([None if hero.in_play else hero for hero in heroes(player)], cards)
    body.alpha_composite(zone, (grid_left - OVERHANG, o - OVERHANG))
    holder_left = grid_left + command_zone_width(len(heroes(player))) + ZONE_GAP
    # The zone as it stands, a hero another player lent into it included
    # (`<owner seat>:hero:<slug>`, Rulebook p. 14): the player's own
    # reading, `PlayerState.patroller`, leaves a lent hero out, and its
    # owner's grid and slots do too, so this is the one place it is
    # drawn (docs/design/codex.md, "The board" under Multiplayer).
    patrolling = match.patrollers(seat)
    for slot in PATROL_SLOTS:
        # Each slot on its own holder, packed against the last.
        draw.rounded_rectangle(
            (holder_left, o, holder_left + PATROL_HOLDER - 1, o + PATROL_HEIGHT - 1),
            radius=px(14), fill=PATROL_BLUE,
        )
        card_left = holder_left + PATROL_PADDING
        holder_left += PATROL_HOLDER + PATROL_SLOT_GAP
        body.alpha_composite(rounded(sized(board_piece("patrol_slots", f"{slot}.png"), CARD),
                                     px(12)),
                             (card_left, card_top))
        body.alpha_composite(sized(board_piece("patrol_slots", f"{slot}_bonus.png"), BONUS),
                             (card_left, card_top + CARD[1] + BONUS_GAP))
        ref = patrolling.get(slot)
        if ref is None:
            continue
        if is_hero_ref(ref):
            # Either spelling of a hero's ref: the player's own, or one
            # lent to them, whose owner the ref carries; its stats the
            # engine's for a hero on this side (`controller_of` is the
            # borrower while it is lent).
            hero = match.hero_on(seat, ref)
            lying = hero_lying(hero, cards, shown(hero), lender=names.get(split_lent_ref(ref)[0]))
        else:
            instance_id = int(ref.split(":", 1)[1])
            card = match.instance(instance_id)
            lying = unit_lying(card, instance_id in partners, cards, copy_number(player, card),
                               shown(card), lender=names.get(card.owner))
        # The patroller covers its slot, chits and all; the bonus stays
        # printed under it.
        paste_centred(body, lying_card(lying, cards, turned),
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


def gold_coin(gold: int, width: int, turned: bool = False) -> Image.Image:
    """The player's gold: the gold emoji's coin `width` across with the
    count on it -- the one place the board shows gold. `turned`, the
    picture is about to be turned round with its panel, so the count is
    drawn upside down to read upright after."""
    coin = by_width(image(EMOJI_DIR / "gold.png"), width).copy()
    text = str(gold)
    size = round(width * 0.62)
    while size > 6 and font(size).getlength(text) > width * 0.72:
        size -= 1
    ImageDraw.Draw(coin).text((coin.width / 2, coin.height / 2), text, font=font(size),
                              fill=WORD_ON_GOLD, anchor="mm")
    return coin.rotate(180) if turned else coin


def turn_label(match: MatchState, name: str) -> str:
    """"<name>'s turn <n>", `name` the active player's as the frontend
    names them -- "perrytom's turn 7". The player and not a hero,
    since a standard game's deck has three (the author, 2026-10-09)."""
    return f"{name}'s turn {match.turn}"


def is_to_act(match: MatchState, seat: int) -> bool:
    return seat in seats.turn_seats(match) and match.winner is None


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
                           outline=edge, width=px(2) if edge else 0)


def render_nameplate(match: MatchState, seat: int, name: str, cards: CardCatalog,
                     width: int, rule_at_top: bool,
                     ground: Optional[Image.Image] = None) -> Image.Image:
    """
    The nameplate, `NAMEPLATE_HEIGHT` tall: the player, then right beside
    the name hand, deck, discard and codex, a word and a count each --
    the gold is a coin in the body (`gold_coin`) -- then their team (`team_name`: a
    colour's deck by its name, "Blood Anarchs", any other team by its
    specs, "Fire/Feral/Bashing"). The active player's carries a rule and
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
    rule_y = 0 if rule_at_top else NAMEPLATE_HEIGHT - px(3)
    draw.rectangle((0, rule_y, width, rule_y + px(2)), fill=rule)
    middle = NAMEPLATE_HEIGHT / 2 + px(1.5 if rule_at_top else -1.5)

    x = 0
    draw.text((x, middle), name, font=font(px(26)), fill=WORD, anchor="lm")
    x += font(px(26)).getlength(name) + px(18)

    number, word = font(px(20)), font(px(15), bold=False)
    counts = (
        ("HAND", len(player.hand)), ("DECK", len(player.deck)),
        ("DISCARD", len(player.discard)), ("CODEX", sum(player.codex.values())),
    )
    for label, count in counts:
        draw.text((x, middle), label, font=word, fill=QUIET, anchor="lm")
        x += word.getlength(label) + px(6)
        text = str(count)
        draw.text((x, middle), text, font=number, fill=WORD, anchor="lm")
        x += number.getlength(text) + px(18)

    spec = team_name(player.specs)
    draw.text((x, middle), spec, font=font(px(18), bold=False), fill=QUIET, anchor="lm")
    x += font(px(18), bold=False).getlength(spec) + px(18)
    if colors:
        label = turn_label(match, name)
        face = font(px(15))
        pill_width = face.getlength(label) + px(24)
        turn_pill(draw, (x, middle - px(13), x + pill_width, middle + px(13)), px(10), colors)
        draw.text((x + px(12), middle), label, font=face, fill=colors[1], anchor="lm")
    return plate


def render_panel(match: MatchState, seat: int, name: str,
                 cards: Optional[CardCatalog] = None,
                 building_hp: Optional[Mapping[str, int]] = None, *,
                 turned: bool = False, height: Optional[int] = None,
                 stats: Optional[StatsOf] = None,
                 names: Optional[Mapping[int, str]] = None) -> Image.Image:
    """
    One player as a panel: the body -- the buildings, the patrol zone,
    the grid -- and the nameplate along the panel's outer edge, below
    it. `turned`, the body is turned round whole to face the other way,
    as the far side of a table is, and the nameplate is above it, still
    the right way up: a name and its counts nobody should have to turn
    a phone for. `height`, where taller than the panel needs, is filled
    between the body and the nameplate, which stays on the outer edge.
    `stats`, the engine's `board_reading`: each unit's and hero's ATK and
    HP as they stand, on its card. `names`, every seat's name, which a
    lent patroller's tag reads its lender's from; `name` is this seat's.
    """
    cards = cards or load_catalog()
    building_hp = building_hp or default_building_hp(cards)
    body = render_body(match, seat, cards, building_hp, turned, stats, names)
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
    patch = sized(patch, (px(patch.width), px(patch.height)))
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
    return seats.sole_opponent(match, near), near


def divider_label(match: MatchState, name: str) -> str:
    return turn_label(match, name).upper()


def horizontal_divider(width: int, label: str, centre: Optional[float] = None) -> Image.Image:
    """
    The stacked board's divider: "<NAME>'S TURN <N>", the active player
    by name, bold and dark on a white pill (`DIVIDER_TURN`) between two
    rules, so whose turn it is reads at a glance (the author,
    2026-10-09: more prominent, and neither gold nor cream). `centre`
    puts the pill over the acting player's panel where that is not the
    board's middle -- a free-for-all side by side (the author,
    2026-10-14).
    """
    strip = Image.new("RGBA", (width, DIVIDER_HEIGHT), GROUND)
    draw = ImageDraw.Draw(strip)
    face = font(px(24))
    text_width = spaced_width(label, face, px(2))
    middle = DIVIDER_HEIGHT // 2
    left = (width - text_width) / 2 if centre is None else centre - text_width / 2
    pad, half = px(18), px(18)
    draw.line((0, middle, left - pad - px(14), middle), fill=QUIET, width=px(2))
    draw.line((left + text_width + pad + px(14), middle, width, middle), fill=QUIET, width=px(2))
    turn_pill(draw, (left - pad, middle - half, left + text_width + pad, middle + half),
              half, DIVIDER_TURN)
    spaced_text(draw, (left, middle), label, face, DIVIDER_TURN[1], px(2))
    return strip


def vertical_divider(height: int, label: str) -> Image.Image:
    """The side-by-side board's, `DIVIDER_WIDTH` wide: the same, standing, read top
    to bottom."""
    lying = Image.new("RGBA", (height, DIVIDER_WIDTH), GROUND)
    lying.alpha_composite(horizontal_divider(height, label),
                          (0, (DIVIDER_WIDTH - DIVIDER_HEIGHT) // 2))
    return lying.transpose(Image.ROTATE_270)


def compose_board(match: MatchState, layout: str = "stacked",
                  names: Optional[Mapping[int, str]] = None,
                  cards: Optional[CardCatalog] = None,
                  near: Optional[int] = None,
                  stats: Optional[StatsOf] = None) -> Image.Image:
    """The whole table at the canvas's pixels, before it is scaled and
    encoded -- `render_board`'s picture. `near`, for the stacked board,
    is the seat looked from: the active player's by default.
    "stacked_upright" stacks the panels the same way, neither turned."""
    cards = cards or load_catalog()
    names = names or {}
    building_hp = default_building_hp(cards)

    def name(seat: int) -> str:
        return names.get(seat) or f"Player {seat}"

    def panels(row, turned: bool = False) -> list[Image.Image]:
        return _even_panels(match, row, name, cards, building_hp, stats, turned, names)

    # Whose turn the divider names: the active player, or both of a
    # dragon's teammates, or the one seat taking an extra turn.
    label = divider_label(match, " and ".join(name(seat) for seat in seats.turn_seats(match)))

    if match.is_dragon:
        return _compose_dragon(match, layout, panels, label, near)
    if match.is_free_for_all:
        if layout == "side_by_side":
            return _compose_rows(match, panels, label, near)
        return _compose_table(match, panels, label, near)
    if layout == "side_by_side":
        first = match.first
        left, right = panels((first, seats.sole_opponent(match, first)))
        board = Image.new("RGBA", (left.width + DIVIDER_WIDTH + right.width, left.height), GROUND)
        board.alpha_composite(left, (0, 0))
        board.alpha_composite(vertical_divider(left.height, label), (left.width, 0))
        board.alpha_composite(right, (left.width + DIVIDER_WIDTH, 0))
        return board

    far_seat, near_seat = stacked_seats(match)
    if near is not None:
        far_seat, near_seat = seats.sole_opponent(match, near), near
    far = render_panel(match, far_seat, name(far_seat), cards, building_hp,
                       turned=layout != "stacked_upright", stats=stats, names=names)
    bottom = render_panel(match, near_seat, name(near_seat), cards, building_hp, stats=stats,
                          names=names)
    return _stack([far], bottom, label)


#: The rule between two opponents' panels on a table of several: quieter
#: than the turn's divider, which stays between the acting seat and the
#: rest (docs/codex-multiplayer.md, decision 14).
TABLE_GAP = px(14)


def _even_panels(match: MatchState, row, name, cards: CardCatalog, building_hp: dict,
                 stats: Optional[StatsOf], turned: bool = False,
                 names: Optional[Mapping[int, str]] = None) -> list[Image.Image]:
    """The panels of `row`'s seats drawn side by side at one height, the
    tallest's: a shorter one is drawn again at that height, so a row of
    panels lines up -- the duel's side by side, a free-for-all's rows of
    two, a dragon's teams."""
    natural = [render_panel(match, seat, name(seat), cards, building_hp, turned=turned, stats=stats,
                            names=names)
               for seat in row]
    height = max(panel.height for panel in natural)
    return [panel if panel.height == height
            else render_panel(match, seat, name(seat), cards, building_hp, turned=turned,
                              height=height, stats=stats, names=names)
            for seat, panel in zip(row, natural)]


def _pair_strip(panels: Sequence[Image.Image], column: int) -> Image.Image:
    """One or two panels of one height as a strip two `column`s wide, a
    quiet rule between them; a lone panel centred."""
    height = panels[0].height
    width = 2 * column + TABLE_GAP
    strip = Image.new("RGBA", (width, height), GROUND)
    if len(panels) == 1:
        strip.alpha_composite(panels[0], ((width - panels[0].width) // 2, 0))
        return strip
    strip.alpha_composite(panels[0], (0, 0))
    middle = column + TABLE_GAP // 2
    ImageDraw.Draw(strip).line((middle, 0, middle, height), fill=QUIET, width=px(1))
    strip.alpha_composite(panels[1], (column + TABLE_GAP, 0))
    return strip


def _stack(above: Sequence[Image.Image], bottom: Image.Image, label: str,
           centre: Optional[float] = None) -> Image.Image:
    """`above` stacked top to bottom, a quiet rule between each two, over
    the turn's divider and `bottom` -- each centred on the board, the
    pill at `centre` (`horizontal_divider`)."""
    width = max(part.width for part in (*above, bottom))
    height = (sum(part.height for part in above) + TABLE_GAP * (len(above) - 1)
              + DIVIDER_HEIGHT + bottom.height)
    board = Image.new("RGBA", (width, height), GROUND)
    draw = ImageDraw.Draw(board)
    top = 0
    for index, part in enumerate(above):
        if index:
            middle = top - TABLE_GAP // 2
            draw.line((0, middle, width, middle), fill=QUIET, width=px(1))
        board.alpha_composite(part, ((width - part.width) // 2, top))
        top += part.height + TABLE_GAP
    top -= TABLE_GAP
    board.alpha_composite(horizontal_divider(width, label, centre), (0, top))
    board.alpha_composite(bottom, ((width - bottom.width) // 2, top + DIVIDER_HEIGHT))
    return board


def _compose_table(match: MatchState, panels, label: str, near: Optional[int]) -> Image.Image:
    """
    A free-for-all's board stacked (decision 14): the seat looked from
    (the active player's) at the bottom under the turn's divider, and
    every other seat above it **upright**, in turn order with the next to
    play nearest -- a table of five has no "across", so no panel is
    turned.
    """
    near_seat = match.active if near is None else near
    others = seats.turn_order(match, near_seat, inclusive=False)[:-1]
    return _stack([panels((seat,))[0] for seat in reversed(others)], panels((near_seat,))[0], label)


def _compose_rows(match: MatchState, panels, label: str, near: Optional[int]) -> Image.Image:
    """
    A free-for-all's board side by side: rows of two panels, every one
    upright (the author, 2026-10-14). Seats go in turn order from the seat
    looked from, two a row from the bottom -- the acting seat's row at the
    bottom under the turn's divider, the active player on its left and the
    next to play beside them -- so three players are one panel above two,
    four are two above two, as a dragon's board is, and five are three
    rows with one panel at the top. A lone panel is centred.
    """
    near_seat = match.active if near is None else near
    order = seats.turn_order(match, near_seat)
    rows = [panels(order[at:at + 2]) for at in range(0, len(order), 2)]
    column = max(panel.width for row in rows for panel in row)
    drawn = [_pair_strip(row, column) for row in rows]
    # The pill over the active player's own panel, the bottom row's left
    # (the author, 2026-10-14).
    return _stack(list(reversed(drawn[1:])), drawn[0], label, centre=column / 2)


def _compose_dragon(match: MatchState, layout: str, panels, label: str,
                    near: Optional[int]) -> Image.Image:
    """
    A two-headed dragon's board, **two rows of two** (the author,
    2026-10-14; decision 14): the team looked from -- the acting team's,
    or `near`'s -- at the bottom under the turn's divider, its head on the
    left, and the other team above it, turned round to face it as the
    duel's far panel is -- the row turned whole, as one mat is, so its
    head's panel is on the right, its buildings at the board's far corner
    where the duel's far base is. "stacked_upright" -- and the
    side-by-side layout, which a dragon has none of -- draws the far row
    the same way up, its head on the left. Each team's one base is drawn on
    both teammates' columns with JOINT along its foot (`render_body`). The divider
    names whose turn it is: both teammates, or the one seat taking an
    extra turn.
    """
    near_seat = match.active if near is None else near
    turned = layout == "stacked"

    def row(team, turn: bool) -> Image.Image:
        drawn = panels(team, turn)
        if turn:
            # The row turned whole: the head across from the near head.
            drawn.reverse()
        return _pair_strip(drawn, max(panel.width for panel in drawn))

    far = row(seats.other_team(match, near_seat), turned)
    bottom = row(seats.dragon_of(match, near_seat), False)
    width = max(far.width, bottom.width)
    board = Image.new("RGBA", (width, far.height + DIVIDER_HEIGHT + bottom.height), GROUND)
    board.alpha_composite(far, (0, 0))
    board.alpha_composite(horizontal_divider(width, label), (0, far.height))
    board.alpha_composite(bottom, (0, far.height + DIVIDER_HEIGHT))
    return board


def render_board(match: MatchState, layout: str = "stacked",
                 names: Optional[Mapping[int, str]] = None,
                 cards: Optional[CardCatalog] = None,
                 near: Optional[int] = None,
                 stats: Optional[StatsOf] = None) -> bytes:
    """
    The whole table as WebP bytes: both panels, stacked -- seen from the
    active player's side, the other player's above theirs and turned
    round to face them, a divider between naming whose turn it is --
    stacked the same way up ("stacked_upright"), the same with neither
    turned, or side by side, the first player's on the left, neither
    turned, as `layout` says. `names` is what each seat's nameplate calls its
    player -- the frontend's to give, since a name is not the model's.
    The picture's size follows the position: a row of cards more is a
    taller panel. `near` looks at the stacked board from that seat
    rather than the active player's: a target prompt's picture where the
    targets are on both sides, seen from the player choosing. `stats`,
    the engine's `board_reading`, puts each unit's and hero's ATK and HP as
    they stand on its card.
    """
    return _webp(compose_board(match, layout, names, cards, near, stats))


def render_side(match: MatchState, seat: int, name: str,
                cards: Optional[CardCatalog] = None,
                stats: Optional[StatsOf] = None,
                names: Optional[Mapping[int, str]] = None) -> bytes:
    """
    One player's side of the table as WebP bytes, upright and at the
    board's scale: the panel `render_board` draws for `seat`, alone. A
    target prompt's picture (docs/design/codex.md, "The panel"), where
    what is chosen from is on the board rather than in the hand.
    `names`, every seat's, as `render_board` takes them: a patroller
    lent into this side is tagged with its lender's.
    """
    cards = cards or load_catalog()
    return _webp(render_panel(match, seat, name, cards, default_building_hp(cards), stats=stats,
                              names=names))


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


#: Where a hand card's printed cost coin ends and its middle sits, at
#: `HAND_CARD`'s size: what a cost that differs is written beside.
HAND_COST_RIGHT, HAND_COST_MIDDLE = 58, 38
#: A cost reduced and a cost raised, beside the printed coin, as fill
#: and ink: a light grey and a dark one, never the coin's gold, so
#: neither reads as the printed cost, and not green or red, which the
#: game already uses (the author, 2026-10-15).
COST_LESS, COST_LESS_INK = (205, 205, 205), SHADOW   # #cdcdcd
COST_MORE, COST_MORE_INK = (78, 78, 78), INK         # #4e4e4e


def cost_note(picture: Image.Image, printed: int, cost: int) -> None:
    """How much a hand card's cost is changed, beside its printed cost
    and in a small font, where it is -- "−1" on light grey for River's
    discount, "+1" on dark grey for a wrong colour's surcharge. The printed
    coin stays in view (the author, 2026-10-15: a coin over it read as
    the printed cost, so a discount looked missing)."""
    if cost == printed:
        return
    draw = ImageDraw.Draw(picture)
    text = f"−{printed - cost}" if cost < printed else f"+{cost - printed}"
    face = font(21)
    left, top, right, bottom = draw.textbbox((0, 0), text, font=face, anchor="lm")
    x = HAND_COST_RIGHT + 8
    fill, ink = (COST_LESS, COST_LESS_INK) if cost < printed else (COST_MORE, COST_MORE_INK)
    draw.rounded_rectangle((x - 6, HAND_COST_MIDDLE + top - 4, x + right + 6, HAND_COST_MIDDLE + bottom + 4),
                           radius=8, fill=fill, outline=SHADOW, width=2)
    draw.text((x, HAND_COST_MIDDLE), text, font=face, fill=ink, anchor="lm")


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
    each with its printed cost and, where `costs` differs, by how much
    beside it (`cost_note`), greyed where it may not be
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
        cost_note(picture, cards.cards[slug].cost or 0, costs[index])
        if not playable[index]:
            picture = faint(picture)
        canvas.alpha_composite(picture, (left, top + label))
    return _webp(canvas)


def render_codex(cards_in_codex: Sequence[str], counts: Sequence[int],
                 cards: Optional[CardCatalog] = None,
                 picked: Optional[Sequence[int]] = None,
                 places: Optional[Sequence[tuple[int, int]]] = None) -> bytes:
    """
    A codex view as WebP bytes: a grid of its cards' own pictures, each
    with a badge of how many copies remain, a card with none left faint.
    Sized so the standard game's thirty-six stay well under Discord's
    upload limit. `picked`, where given, is how many copies of each the
    tech choice has taken so far: such a card is framed in gold with
    the count on a pill over its art -- the tech picker's picture.
    `places`, where given, is each card's (row, column) -- the engine's
    `codex_places`: Tech II and III a line per spec, the spells a block
    per spec -- the grid as wide and as tall as the places it uses;
    without them the cards run on, `CODEX_COLUMNS` a row. The same
    picture asked again is the bytes already drawn (`RENDERED_KEPT`).
    """
    return _render_codex(tuple(cards_in_codex), tuple(counts), cards or load_catalog(),
                         None if picked is None else tuple(picked),
                         None if places is None else tuple(map(tuple, places)))


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
                  places: Optional[tuple[tuple[int, int], ...]] = None) -> bytes:
    if places is None:
        across = max(1, min(CODEX_COLUMNS, len(cards_in_codex)))
        places = tuple(divmod(index, across) for index in range(len(cards_in_codex)))
    columns = max([column for _, column in places] or [0]) + 1
    rows = max([row for row, _ in places] or [0]) + 1
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


def render_deck(held: Sequence[tuple[str, int]], played: Sequence[tuple[str, int]],
                discarded: Sequence[tuple[str, int]], pile: Sequence[tuple[str, int]],
                cards: Optional[CardCatalog] = None) -> bytes:
    """
    A player's whole deck as WebP bytes -- **My deck**'s picture: four
    parts, each in a frame headed with its name -- the cards in the
    hand, those in play, those in the discard pile and those in the
    draw pile ("Deck") -- in one picture (the author, 2026-10-10: "one
    image but with the frames around separating the different parts";
    2026-10-15: "show what's in play as a zone"). The frames are packed
    by `deck_layout` so the rows are filled rather than a frame left
    alone on a row of its own (the author, 2026-10-15: "should fill the
    rows"). Each card shows once per part with its copies there on its
    badge, so a card with copies in two places shows in both (the
    author, 2026-10-09). The hand's frame is the neutral white the words
    are, the others the quiet grey -- never gold, which is the tech
    picker's mark and the currency's. A part with no cards is left out.
    The same deck asked again is the bytes already drawn
    (`RENDERED_KEPT`).
    """
    return _render_deck(tuple(held), tuple(played), tuple(discarded), tuple(pile),
                        cards or load_catalog())


#: The deck picture's height above a frame's cards, for its name.
DECK_HEADING = 44
#: The room inside a frame around its cards.
DECK_BOX_PAD = 14
#: The widest the deck picture grows, in cards: no row of frames holds
#: more columns of cards than this.
DECK_COLUMNS = 8


def deck_layout(sizes: Sequence[int], columns: int = DECK_COLUMNS,
                ) -> list[tuple[int, list[tuple[int, int]]]]:
    """
    The deck picture's frames packed into rows: for each row, its height
    in lines of cards and, for each frame in it in order, (which frame,
    its columns). Every frame in a row is that many lines tall, its cards
    in as few columns as fit them, and no row holds more than `columns`.
    Of every way to cut the frames, in order, into rows, the one taken
    is the shortest picture, then the one with the fewest empty card
    places in it -- a row's own and those its frames leave on their
    last line -- then the one whose frames wrap least, so a hand of
    five lies in a row where it can. A frame of two cards always lies
    them side by side, whatever its row's height (the author,
    2026-10-15) -- two stacked read as a column, not a pair.
    """
    def across(size: int, lines: int) -> int:
        return size if size <= 2 else -(-size // lines)

    count = len(sizes)
    best, chosen = None, []
    for cuts in range(1 << max(count - 1, 0)):
        rows, row = [], [0] if count else []
        for index in range(1, count):
            if cuts >> (index - 1) & 1:
                rows.append(row)
                row = []
            row.append(index)
        if row:
            rows.append(row)
        laid = []
        for members in rows:
            lines = 1
            while sum(across(sizes[i], lines) for i in members) > columns:
                lines += 1
            laid.append((lines, [(i, across(sizes[i], lines)) for i in members]))
        width = max(sum(c for _, c in frames) for _, frames in laid) if laid else 0
        height = sum(lines for lines, _ in laid)
        empty = width * height - sum(sizes)
        wrapped = sum(lines * len(frames) for lines, frames in laid)
        score = (height, empty, wrapped)
        if best is None or score < best:
            best, chosen = score, laid
    return chosen


@lru_cache(maxsize=RENDERED_KEPT)
def _render_deck(held: tuple[tuple[str, int], ...], played: tuple[tuple[str, int], ...],
                 discarded: tuple[tuple[str, int], ...], pile: tuple[tuple[str, int], ...],
                 cards: CardCatalog) -> bytes:
    gap, pad = 14, DECK_BOX_PAD
    card_w, card_h = CODEX_CARD
    face = font(26)
    parts = [
        (title, rows, edge) for title, rows, edge in (
            ("Hand", held, WORD), ("In play", played, QUIET),
            ("Discard pile", discarded, QUIET), ("Deck", pile, QUIET),
        ) if rows
    ]
    layout = deck_layout([len(rows) for _, rows, _ in parts])
    # Each row's frames left to right, each as wide as its cards (or its
    # name); the picture as wide as the widest row, and the last frame of
    # every narrower row stretched to it, so the right edges line up.
    placed = []
    for lines, frames in layout:
        x, row = gap, []
        for index, columns in frames:
            title = parts[index][0]
            grid = columns * card_w + (columns - 1) * gap
            width = max(grid, round(face.getlength(title))) + 2 * pad
            row.append([x, width, index, columns])
            x += width + gap
        placed.append((lines, row, x))
    width = max((right for _, _, right in placed), default=0)
    for _, row, right in placed:
        row[-1][1] += width - right
    height = gap + sum(DECK_HEADING + lines * card_h + (lines - 1) * gap + pad + gap
                       for lines, _, _ in placed)
    if not parts:
        width, height = card_w * 2, card_h // 2
    canvas = Image.new("RGBA", (width, height), STRIP_FILL)
    draw = ImageDraw.Draw(canvas)
    if not parts:
        text_centred(draw, (width // 2, height // 2), "Nothing here", 32)
    top = gap
    for lines, row, _ in placed:
        row_height = DECK_HEADING + lines * card_h + (lines - 1) * gap + pad
        for left, frame_width, index, columns in row:
            title, rows, edge = parts[index]
            draw.rounded_rectangle((left, top, left + frame_width - 1, top + row_height - 1),
                                   radius=12, fill=PANEL, outline=edge, width=3)
            draw.text((left + pad, top + DECK_HEADING // 2), title, font=face,
                      fill=edge, anchor="lm")
            for position, (slug, count) in enumerate(rows):
                line, column = divmod(position, columns)
                canvas.alpha_composite(
                    codex_tile(slug, count, cards),
                    (left + pad + column * (card_w + gap),
                     top + DECK_HEADING + line * (card_h + gap)),
                )
        top += row_height + gap
    return _webp(canvas)
