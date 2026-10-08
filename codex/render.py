"""
The Codex bot's pictures: the board, a hand and a codex, drawn with
Pillow -- **the one module under `codex/` that imports it**
(`tests/test_model_purity.py`).

**The board is the game's own art** (docs/codex-bot.md, decision 5;
docs/design/codex.md, "The board on Discord"): each side is the
Screentop module's playmat, `codex/images/board/playmat.png`, with the
position laid on it where the mat has a place for it -- the hero as its
own card in the first hero slot with its level chit, or the slot empty
with its summoning runes while it is in the command zone; the patrollers
as their cards in the five labelled slots; the base, Tech I, II and III
tiles and the add-on card in their places, each with its damage chits
and a mark while under construction, the unbuilt places faint; the draw
pile as the card back with its count, the discard and the workers as
counts; the play zone's other units as their cards across the mat's open
middle, each with its damage and rune chits, turned sideways when
exhausted and marked when it arrived this turn. A strip along each
mat's top carries the player's name, spec and hero, gold, hand, codex
and base. Nothing is drawn that the module or a card already shows: the
words this module draws are numbers, names and the three marks.

The two mats are stacked -- the second player's above the first's, as
across a table -- or side by side, the first player's on the left, as
the game's `board_layout` says.

**Nothing here is tested for how it looks** (CLAUDE.md, "Nothing
rendered is tested"): `scripts/render_codex_sample.py` draws the
opening position in both layouts, a hand and a codex view; look at them.
Every caller renders through `asyncio.to_thread` -- Pillow is CPU-bound
and would block the heartbeat.
"""

from __future__ import annotations

import io
from functools import lru_cache
from pathlib import Path
from typing import Mapping, Optional, Sequence

from PIL import Image, ImageDraw, ImageEnhance, ImageFont

from codex.cards import BOARD_IMAGE_DIR, CardCatalog, catalog as load_catalog
from codex.components import PATROL_SLOTS, TECH_BUILDINGS, CardInstance, MatchState, PlayerState
from codex.engine import TECH_BUILDING_SLUGS

#: The fonts are D12 Ball's, bundled, and read by absolute path
#: (docs/design/board-image.md): Roboto Slab for every number and name.
FONT_DIR = Path(__file__).resolve().parent.parent / "d12ball" / "fonts"

#: The playmat's own size, which every box below is measured in.
MAT_SIZE = (1838, 1088)
#: The strip along a mat's top.
STRIP_HEIGHT = 92
#: What the composed board is scaled by before it is saved: big enough
#: to read a card's name on a phone through the full-image link, small
#: enough to upload quickly on every edit.
BOARD_SCALE = 0.6

Box = tuple[int, int, int, int]

#: Where the mat has a place for something, as (left, top, right, bottom)
#: in `MAT_SIZE`, read off the playmat once.
HERO_SLOTS: tuple[Box, ...] = (
    (38, 38, 234, 308), (245, 38, 441, 308), (452, 38, 648, 308),
)
PATROL_BOXES: Mapping[str, Box] = {
    "squad_leader": (690, 40, 886, 310),
    "elite": (918, 40, 1114, 310),
    "scavenger": (1146, 40, 1342, 310),
    "technician": (1373, 40, 1569, 310),
    "lookout": (1599, 40, 1795, 310),
}
ADD_ON_BOX: Box = (38, 328, 167, 513)
BASE_BOX: Box = (38, 530, 248, 760)
TECH_BOXES: Mapping[str, Box] = {
    "tech3": (263, 338, 441, 466),
    "tech2": (263, 486, 441, 613),
    "tech1": (263, 632, 441, 760),
}
WORKERS_BOX: Box = (38, 780, 648, 1048)
DISCARD_BOX: Box = (1600, 388, 1795, 656)
DRAW_BOX: Box = (1600, 778, 1795, 1048)
#: The mat's open middle, where the play zone's other cards lie.
PLAY_BOX: Box = (676, 372, 1584, 1066)

#: A card's printed proportions (the pictures are 330 by 450).
CARD_RATIO = 450 / 330

INK = (245, 238, 220)
SHADOW = (12, 10, 8)
GOLD = (236, 190, 64)
STRIP_FILL = (24, 20, 16)
ACTIVE_FILL = (64, 46, 18)
MARK_FILL = (176, 40, 32)
BUILD_FILL = (40, 96, 170)


# -- Loading -----------------------------------------------------------


@lru_cache(maxsize=16)
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


def faint(picture: Image.Image, amount: float = 0.35) -> Image.Image:
    """Greyed and dimmed: an unbuilt place, an unplayable card, a card
    the codex has none of left."""
    grey = ImageEnhance.Color(picture).enhance(0.15)
    grey = ImageEnhance.Brightness(grey).enhance(amount + 0.25)
    return grey


# -- Drawing helpers -----------------------------------------------------


def paste_centred(canvas: Image.Image, picture: Image.Image, box: Box) -> tuple[int, int]:
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
    """A word on a rounded tag: the three marks the board draws --
    arrived this turn, under construction, destroyed."""
    face = font(size)
    left, top, right, bottom = draw.textbbox(at, text, font=face, anchor=anchor)
    pad = size // 3
    draw.rounded_rectangle((left - pad, top - pad, right + pad, bottom + pad),
                           radius=pad, fill=fill, outline=SHADOW, width=2)
    draw.text(at, text, font=face, fill=INK, anchor=anchor)


def chit_stack(amount: int, folder: str, largest: int) -> list[Image.Image]:
    """The fewest of a numbered chit (`damage/1` to `damage/9`) that add
    up to `amount`, largest first."""
    chits = []
    while amount > 0:
        piece = min(amount, largest)
        chits.append(board_piece(folder, f"{piece}.png"))
        amount -= piece
    return chits


def lay_chits(canvas: Image.Image, chits: Sequence[Image.Image], at: tuple[int, int],
              size: int) -> None:
    """Chits in a row from `at`, each `size` across."""
    left, top = at
    for chit in chits:
        piece = fitted(chit, (size, size))
        canvas.alpha_composite(piece, (left, top))
        left += piece.width - size // 6


def damage_chits(canvas: Image.Image, damage: int, at: tuple[int, int], size: int) -> None:
    lay_chits(canvas, chit_stack(damage, "damage", 9), at, size)


def rune_chits(canvas: Image.Image, card: CardInstance, at: tuple[int, int], size: int) -> None:
    chits = [board_piece("chits", "plus_rune.png")] * card.plus_runes
    chits += [board_piece("chits", "minus_rune.png")] * card.minus_runes
    lay_chits(canvas, chits, at, size)


# -- One side --------------------------------------------------------------


def card_tile(card: CardInstance, cards: CardCatalog, size: tuple[int, int]) -> Image.Image:
    """A card in play as it lies: its own art, its damage and rune chits,
    the arrival mark, turned sideways when exhausted."""
    picture = fitted(card_picture(card.slug, cards), size)
    chit = max(28, picture.width // 3)
    if card.damage:
        damage_chits(picture, card.damage, (picture.width - chit - 4, 4), chit)
    if card.plus_runes or card.minus_runes:
        rune_chits(picture, card, (4, picture.height - chit - 4), chit)
    if card.arrived_this_turn:
        pill(ImageDraw.Draw(picture), (picture.width // 2, picture.height * 2 // 5),
             "arrived", max(14, picture.width // 9), MARK_FILL, anchor="mm")
    if card.exhausted:
        picture = picture.rotate(90, expand=True)
    return picture


def hero_tile(player: PlayerState, cards: CardCatalog, size: tuple[int, int]) -> Image.Image:
    hero = player.hero
    picture = fitted(card_picture(hero.slug, cards), size)
    chit = max(32, picture.width // 3)
    card = cards.heroes[hero.slug]
    if hero.level >= card.max_level:
        level = board_piece("levels", "max.png")
    elif hero.level == 1:
        level = board_piece("chits", "level_1.png")
    else:
        level = board_piece("levels", f"{hero.level}.png")
    lay_chits(picture, [level], (picture.width - chit - 4, picture.height - chit - 4), chit)
    if hero.damage:
        damage_chits(picture, hero.damage, (picture.width - chit - 4, 4), chit)
    if hero.arrived_this_turn:
        pill(ImageDraw.Draw(picture), (picture.width // 2, picture.height * 2 // 5),
             "arrived", max(14, picture.width // 9), MARK_FILL, anchor="mm")
    if hero.exhausted:
        picture = picture.rotate(90, expand=True)
    return picture


def box_size(box: Box, margin: int = 0) -> tuple[int, int]:
    return box[2] - box[0] - 2 * margin, box[3] - box[1] - 2 * margin


def draw_buildings(canvas: Image.Image, player: PlayerState, building_hp: Mapping[str, int]) -> None:
    draw = ImageDraw.Draw(canvas)
    # The base: the mat prints it, so only its damage is laid on it.
    damage = building_hp["base"] - player.base_hp
    if damage > 0:
        damage_chits(canvas, damage, (BASE_BOX[0] + 14, BASE_BOX[1] + 14), 64)

    for name in TECH_BUILDINGS:
        box = TECH_BOXES[name]
        state = player.buildings.get(name)
        tile = fitted(board_piece("buildings", f"{TECH_BUILDING_SLUGS[name]}.png"), box_size(box))
        if state is None or state.destroyed:
            tile = faint(tile)
        left, top = paste_centred(canvas, tile, box)
        if state is None:
            continue
        if state.destroyed:
            pill(draw, ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2), "destroyed", 22,
                 MARK_FILL, anchor="mm")
            continue
        if state.under_construction:
            pill(draw, ((box[0] + box[2]) // 2, box[3] - 18), "building", 20, BUILD_FILL,
                 anchor="mm")
        damage = building_hp[name] - state.hp
        if damage > 0:
            damage_chits(canvas, damage, (left + 4, top + 4), 48)

    add_on = player.add_on
    if add_on is None:
        canvas.alpha_composite(
            Image.new("RGBA", box_size(ADD_ON_BOX), (0, 0, 0, 110)), ADD_ON_BOX[:2],
        )
        return
    tile = fitted(board_piece("buildings", f"{add_on.slug}.png"), box_size(ADD_ON_BOX, 4))
    left, top = paste_centred(canvas, tile, ADD_ON_BOX)
    if add_on.under_construction:
        pill(draw, ((ADD_ON_BOX[0] + ADD_ON_BOX[2]) // 2, ADD_ON_BOX[3] - 18), "building",
             16, BUILD_FILL, anchor="mm")
    damage = building_hp[add_on.slug] - add_on.hp
    if damage > 0:
        damage_chits(canvas, damage, (left + 4, top + 4), 44)


def draw_play_zone(canvas: Image.Image, cards_in_play: Sequence[CardInstance],
                   cards: CardCatalog) -> None:
    """The units that are not patrolling, in a grid across the mat's open
    middle, each cell square so a card turned sideways fits it too."""
    if not cards_in_play:
        return
    width, height = box_size(PLAY_BOX)
    count = len(cards_in_play)
    cell = 0
    columns = 1
    for columns_tried in range(1, count + 1):
        rows = -(-count // columns_tried)
        side = min(width // columns_tried, height // rows)
        if side > cell:
            cell, columns = side, columns_tried
    cell = min(cell, 340)
    card_height = cell - 12
    size = (round(card_height / CARD_RATIO), card_height)
    rows = -(-count // columns)
    left0 = PLAY_BOX[0] + (width - columns * cell) // 2
    top0 = PLAY_BOX[1] + (height - rows * cell) // 2
    for index, card in enumerate(cards_in_play):
        row, column = divmod(index, columns)
        box = (left0 + column * cell, top0 + row * cell,
               left0 + (column + 1) * cell, top0 + (row + 1) * cell)
        paste_centred(canvas, card_tile(card, cards, size), box)


def draw_strip(player: PlayerState, name: str, active: bool, hero_name: str,
               width: int) -> Image.Image:
    strip = Image.new("RGBA", (width, STRIP_HEIGHT), ACTIVE_FILL if active else STRIP_FILL)
    draw = ImageDraw.Draw(strip)
    middle = STRIP_HEIGHT // 2
    who = f"{name} -- {player.spec.title()}, {hero_name}"
    draw.text((28, middle), who, font=font(40), fill=GOLD if active else INK, anchor="lm")
    counts = (
        f"Gold {player.gold}    Hand {len(player.hand)}    "
        f"Codex {sum(player.codex.values())}    Base {player.base_hp}"
    )
    draw.text((width - 28, middle), counts, font=font(36, bold=False), fill=INK, anchor="rm")
    return strip


def render_side(match: MatchState, seat: int, name: str,
                cards: Optional[CardCatalog] = None,
                building_hp: Optional[Mapping[str, int]] = None) -> Image.Image:
    """One player's mat with their position laid on it, and the strip
    above it."""
    cards = cards or load_catalog()
    building_hp = building_hp or default_building_hp(cards)
    player = match.player(seat)
    mat = board_piece("playmat.png")
    draw = ImageDraw.Draw(mat)

    hero = player.hero
    slot_size = box_size(HERO_SLOTS[0], 4)
    if hero.in_play and hero.patrol_slot is None:
        paste_centred(mat, hero_tile(player, cards, slot_size), HERO_SLOTS[0])
    elif not hero.in_play and hero.summoning_runes:
        rune = fitted(board_piece("time_runes", f"{min(hero.summoning_runes, 6)}.png"), (120, 120))
        paste_centred(mat, rune, HERO_SLOTS[0])

    for slot in PATROL_SLOTS:
        ref = player.patroller(slot)
        if ref is None:
            continue
        box = PATROL_BOXES[slot]
        if ref == "hero":
            tile = hero_tile(player, cards, box_size(box, 4))
        else:
            tile = card_tile(match.instance(int(ref.split(":", 1)[1])), cards, box_size(box, 4))
        paste_centred(mat, tile, box)

    draw_buildings(mat, player, building_hp)
    draw_play_zone(mat, [card for card in player.play if card.patrol_slot is None], cards)

    workers = (WORKERS_BOX[0] + WORKERS_BOX[2]) // 2, WORKERS_BOX[1] + 190
    text_centred(draw, workers, str(player.workers), 72)
    discard = (DISCARD_BOX[0] + DISCARD_BOX[2]) // 2, DISCARD_BOX[1] + 190
    text_centred(draw, discard, str(len(player.discard)), 72)
    if player.deck:
        back = fitted(board_piece("backs", "card.png"), box_size(DRAW_BOX, 14))
        paste_centred(mat, back, DRAW_BOX)
    # The count on a tag below the back's medallion, so it does not read
    # as part of the back.
    pill(draw, ((DRAW_BOX[0] + DRAW_BOX[2]) // 2, DRAW_BOX[3] - 44), str(len(player.deck)),
         56, STRIP_FILL, anchor="mm")

    side = Image.new("RGBA", (MAT_SIZE[0], MAT_SIZE[1] + STRIP_HEIGHT), STRIP_FILL)
    hero_name = cards.heroes[hero.slug].name
    side.alpha_composite(draw_strip(player, name, match.active == seat and match.winner is None,
                                    hero_name, MAT_SIZE[0]), (0, 0))
    side.alpha_composite(mat, (0, STRIP_HEIGHT))
    return side


def default_building_hp(cards: CardCatalog) -> dict[str, int]:
    """Each building's full HP, from the card data: what its damage chits
    are counted against."""
    found = {name: cards.building(slug).hp or 0 for name, slug in TECH_BUILDING_SLUGS.items()}
    for slug in ("tower", "surplus"):
        found[slug] = cards.building(slug).hp or 0
    found["base"] = 20
    return found


# -- The board, a hand, a codex -----------------------------------------------


def _png(picture: Image.Image) -> bytes:
    buffer = io.BytesIO()
    picture.convert("RGB").save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def render_board(match: MatchState, layout: str = "stacked",
                 names: Optional[Mapping[int, str]] = None,
                 cards: Optional[CardCatalog] = None) -> bytes:
    """
    The whole table as PNG bytes: both mats, stacked (the second
    player's above the first's) or side by side (the first player's on
    the left), as `layout` says. `names` is what each seat's strip calls
    its player -- the frontend's to give, since a name is not the
    model's.
    """
    cards = cards or load_catalog()
    names = names or {}
    building_hp = default_building_hp(cards)
    first = match.first
    second = 2 if first == 1 else 1
    sides = {
        seat: render_side(match, seat, names.get(seat) or f"Player {seat}", cards, building_hp)
        for seat in (1, 2)
    }
    width, height = sides[1].size
    gap = 16
    if layout == "side_by_side":
        board = Image.new("RGBA", (width * 2 + gap, height), SHADOW)
        board.alpha_composite(sides[first], (0, 0))
        board.alpha_composite(sides[second], (width + gap, 0))
    else:
        board = Image.new("RGBA", (width, height * 2 + gap), SHADOW)
        board.alpha_composite(sides[second], (0, 0))
        board.alpha_composite(sides[first], (0, height + gap))
    scaled = board.resize(
        (round(board.width * BOARD_SCALE), round(board.height * BOARD_SCALE)), Image.LANCZOS,
    )
    return _png(scaled)


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


def render_hand(cards_in_hand: Sequence[str], playable: Sequence[bool],
                costs: Sequence[int], cards: Optional[CardCatalog] = None) -> bytes:
    """
    A hand as PNG bytes: the cards' own pictures in a row, numbered,
    each with its cost after reductions, greyed where it may not be
    played -- the picture **My hand** and the panel attach.
    """
    cards = cards or load_catalog()
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
        picture = card_picture(slug, cards).resize(HAND_CARD, Image.LANCZOS)
        cost_badge(picture, costs[index], 62)
        if not playable[index]:
            picture = faint(picture)
        canvas.alpha_composite(picture, (left, top + label))
    return _png(canvas)


def render_codex(cards_in_codex: Sequence[str], counts: Sequence[int],
                 cards: Optional[CardCatalog] = None) -> bytes:
    """
    A codex view as PNG bytes: a grid of its cards' own pictures, each
    with a badge of how many copies remain, a card with none left faint.
    Sized so the standard game's thirty-six stay well under Discord's
    upload limit.
    """
    cards = cards or load_catalog()
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
        picture = card_picture(slug, cards).resize(CODEX_CARD, Image.LANCZOS)
        if counts[index] <= 0:
            picture = faint(picture)
        badge = ImageDraw.Draw(picture)
        size = 56
        x0, y0 = CODEX_CARD[0] - size - 6, 6
        badge.ellipse((x0, y0, x0 + size, y0 + size), fill=INK, outline=SHADOW, width=3)
        badge.text((x0 + size // 2, y0 + size // 2), f"x{counts[index]}", font=font(26),
                   fill=SHADOW, anchor="mm")
        canvas.alpha_composite(picture, (left, top))
    return _png(canvas)
