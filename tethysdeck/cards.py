"""The card faces: a white card, the fate's ink, the value as pieces spread
over the face, the rank and the suit's mark in two corners.

Poker size at 300 dpi, the same 750 x 1050 as `d12ball.cards`, so the
deck prints on the same sheets. Fortune is violet ink with green, Doom coal ink with
orange; the paper is white either way (the author: no cream anywhere).
"""
from PIL import Image, ImageDraw, ImageFont

from tethysdeck import icons
from tethysdeck import deck_2d12
from tethysdeck.deck import RANKS, SUITS, VARIANTS, coins_worth, fate_of, pieces_worth, worth
from tethysdeck.relief import IconSet

# The corner is the Avery 95328 die cut's own, 0.375in at 300 dpi, and every frame
# inside it is concentric with it (`RADIUS - inset`), so a line keeps its inset round
# the corner as along the sides and the cut never takes a corner off it (the author,
# 2026-10-10: at 36 the frames' corners ran out past the cut).
W, H, RADIUS = 750, 1050, 112

# Fortune is violet paired with a deep green, Doom is coal and a dark orange (the author,
# 2026-10-09; before: teal, and black and gold). The grey names the suit and the fate,
# so it is dark enough to print: #A6A4AD all but vanished on paper, and #5E5A68 was still
# too light (the author, 2026-10-11).
PALETTE = {
    "fortune": {"paper": "#FFFFFF", "ink": "#4A2A78", "ink2": "#1E6B34"},
    "doom": {"paper": "#FFFFFF", "ink": "#2A2522", "ink2": "#BE5A12"},
}
# A piece's size on the card by what it is worth, and a coin's by what it is.
PIECE_SIZE = {1: 230, 3: 280, 6: 330, 12: 400}
COIN_SIZE = {("bronze", 1): 200, ("bronze", 3): 225, ("silver", 1): 260,
             ("silver", 3): 290, ("gold", 1): 330, ("gold", 3): 370}
# Where the pieces sit, by how many there are, spread over the face like pips, and
# the room each has: (centre, width, height). A piece is cropped to what it shows and
# scaled to fill its value's size (PIECE_SIZE) across or TALL times that down, whichever
# binds first, cut to the slot's room -- so a sword or a haft stands tall and a crown
# or a disc sits wide, instead of every piece shrinking into a square.
SLOTS = {
    1: [((375, 470), 420, 620)],
    2: [((375, 300), 420, 330), ((375, 650), 420, 330)],
    3: [((375, 290), 420, 320), ((225, 650), 280, 320), ((525, 650), 280, 320)],
    # Four and five pieces are the 2d12 deck's alone (the classic deck's most is three): as three
    # is, the largest across the top and the rest in a row under it, clear of the corners and the value.
    4: [((375, 300), 420, 300), ((200, 640), 165, 290), ((375, 640), 165, 290), ((550, 640), 165, 290)],
    5: [((375, 295), 420, 290), ((165, 640), 140, 290), ((305, 640), 140, 290), ((445, 640), 140, 290),
        ((585, 640), 140, 290)],
}
TALL = 1.6

_coins: dict[tuple, Image.Image] = {}


def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(icons.FONT), size)


def coin_image(metal: str, amount: int, fate: str) -> Image.Image:
    """One of the studio's coins on the face the card's fate asks for."""
    key = (metal, amount, fate)
    if key not in _coins:
        im = Image.open(icons.COINS / f"coin_{metal}_{amount}_{fate}.png").convert("RGBA")
        size = COIN_SIZE[(metal, amount)]
        _coins[key] = im.resize((size, round(size * im.height / im.width)), Image.LANCZOS)
    return _coins[key]


def fit(im: Image.Image, width: int, height: int) -> Image.Image:
    """The picture cropped to what it shows, scaled to fill `width` or `height`, whichever binds."""
    bbox = im.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
    if bbox:
        im = im.crop(bbox)
    scale = min(width / im.width, height / im.height)
    return im.resize((max(1, round(im.width * scale)), max(1, round(im.height * scale))), Image.LANCZOS)


def _spread(img: Image.Image, items: list[Image.Image]) -> None:
    for im, ((cx, cy), _, _) in zip(items, SLOTS[len(items)]):
        img.alpha_composite(im, (cx - im.width // 2, cy - im.height // 2))


def card(icon_set: IconSet, suit: str, rank: str) -> Image.Image:
    """A classic card: a number, or a ruler worth 12 named in words."""
    ruler = rank in ("Left", "Right")
    return face(icon_set, suit, fate_of(suit, rank), worth(suit, rank),
                {"Left": "L", "Right": "R"}.get(rank, rank), rank.upper() if ruler else rank, 80 if ruler else 120)


def card_2d12(icon_set: IconSet, c: deck_2d12.Card) -> Image.Image:
    """A 2d12 card: its value, made of pieces like any other."""
    return face(icon_set, c.suit, c.fate, c.value, str(c.value), str(c.value), 120)


def face(icon_set: IconSet, suit: str, fate: str, value: int, short: str, label: str, label_size: int) -> Image.Image:
    """A face worth `value` under `fate`: `short` in the corners, `label` large under the pieces."""
    p = PALETTE[fate]
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, W - 1, H - 1), RADIUS, fill=p["paper"])
    d.rounded_rectangle((18, 18, W - 19, H - 19), RADIUS - 18, outline=p["ink"], width=5)
    d.rounded_rectangle((30, 30, W - 31, H - 31), RADIUS - 30, outline=p["ink2"], width=2)

    corner = Image.new("RGBA", (130, 150), (0, 0, 0, 0))
    ImageDraw.Draw(corner).text((65, 0), short, font=font(66), fill=p["ink"], anchor="ma")
    mark = fit(icon_set.image(suit, fate), 62, 62)
    corner.alpha_composite(mark, (34 + (62 - mark.width) // 2, 84 + (62 - mark.height) // 2))
    img.alpha_composite(corner, (42, 40))
    img.alpha_composite(corner.rotate(180), (W - 172, H - 190))

    d.text((W // 2, 88), suit.upper(), font=font(56), fill=p["ink2"], anchor="mm")
    if suit == "money":
        _spread(img, [coin_image(metal, amount, fate) for metal, amount in coins_worth(value)])
    else:
        values = pieces_worth(value)
        items = []
        for piece, (_, room_w, room_h) in zip(values, SLOTS[len(values)]):
            size = PIECE_SIZE[piece]
            items.append(fit(icon_set.image(suit, fate, VARIANTS.get(suit, {}).get(piece)),
                             min(size, room_w), min(round(size * TALL), room_h)))
        _spread(img, items)
    d.text((W // 2, 862), label, font=font(label_size), fill=p["ink"], anchor="mm")
    d.text((W // 2, 966), fate.upper(), font=font(38), fill=p["ink2"], anchor="mm")
    return img


def deck_cards(icon_set: IconSet) -> dict[tuple[str, str], Image.Image]:
    """Every card, keyed by (suit, rank), in the deck's order."""
    return {(suit, rank): card(icon_set, suit, rank) for suit in SUITS for rank in RANKS}


def deck_2d12_cards(icon_set: IconSet) -> dict[deck_2d12.Card, Image.Image]:
    """Every different 2d12 card once, keyed by its `Card`, in the deck's order;
    `deck_2d12.cards()` names the 72 with their repeats."""
    return {c: card_2d12(icon_set, c) for c in deck_2d12.faces()}


def flatten(card_image: Image.Image) -> Image.Image:
    """A card on white, for a sheet."""
    page = Image.new("RGB", card_image.size, "white")
    page.paste(card_image, (0, 0), card_image)
    return page


# --- contact sheets, for looking at the deck -------------------------------

def deck_sheet(cards: list[Image.Image], scale: float = 0.2) -> Image.Image:
    """All 72 in the deck's order, twelve a row -- a suit a row, either deck."""
    cw, ch, gap = round(W * scale), round(H * scale), 10
    img = Image.new("RGB", (12 * cw + 13 * gap, 6 * ch + 7 * gap), "#5a5a5a")
    for i, c in enumerate(cards):
        x = gap + (i % 12) * (cw + gap)
        y = gap + (i // 12) * (ch + gap)
        small = c.resize((cw, ch), Image.LANCZOS)
        img.paste(small, (x, y), small)
    return img


def closeup_sheet(cards: dict, picks: list[tuple[str, str]], scale: float = 0.45, columns: int = 3) -> Image.Image:
    cw, ch, gap = round(W * scale), round(H * scale), 16
    rows = (len(picks) + columns - 1) // columns
    img = Image.new("RGB", (columns * cw + (columns + 1) * gap, rows * ch + (rows + 1) * gap), "#5a5a5a")
    for i, key in enumerate(picks):
        x = gap + (i % columns) * (cw + gap)
        y = gap + (i // columns) * (ch + gap)
        small = cards[key].resize((cw, ch), Image.LANCZOS)
        img.paste(small, (x, y), small)
    return img


def ladder_sheet(icon_set: IconSet, suit: str = "might") -> Image.Image:
    """A suit's four denominations, Fortune over Doom, labelled."""
    from tethysdeck.deck import VARIANTS
    names = list(VARIANTS[suit].items())
    cell, gap, label = 256, 24, 36
    img = Image.new("RGB", (len(names) * cell + (len(names) + 1) * gap, 2 * (cell + label) + 3 * gap), "white")
    d = ImageDraw.Draw(img)
    for row, fate in enumerate(("fortune", "doom")):
        for col, (value, variant) in enumerate(names):
            im = icon_set.piece(suit, value, fate, cell)
            x, y = gap + col * (cell + gap), gap + row * (cell + label + gap)
            img.paste(im, (x, y), im)
            d.text((x + cell // 2, y + cell + label // 2), f"{variant} ({value}) {fate}", font=font(22), fill="#333333", anchor="mm")
    return img
