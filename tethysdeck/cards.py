"""The card faces: a white card, the fate's ink, the value as pieces spread
over the face, the rank and the suit's mark in two corners.

Poker size at 300 dpi, the same 750 x 1050 as `d12ball.cards`, so the
deck prints on the same sheets. Fortune is violet ink, Doom coal ink with
orange; the paper is white either way (the author: no cream anywhere).
"""
from PIL import Image, ImageDraw, ImageFont

from tethysdeck import icons
from tethysdeck.deck import RANKS, SUITS, fate_of, money_coins, pieces
from tethysdeck.relief import IconSet

W, H, RADIUS = 750, 1050, 36

# Fortune is violet paired with a light grey, Doom is coal and a dark orange (the author,
# 2026-10-09; before: teal, and black and gold).
PALETTE = {
    "fortune": {"paper": "#FFFFFF", "ink": "#4A2A78", "ink2": "#A6A4AD"},
    "doom": {"paper": "#FFFFFF", "ink": "#2A2522", "ink2": "#BE5A12"},
}
# A piece's size on the card by what it is worth, and a coin's by what it is.
PIECE_SIZE = {1: 230, 3: 280, 6: 330, 12: 400}
COIN_SIZE = {("bronze", 1): 200, ("bronze", 3): 225, ("silver", 1): 260,
             ("silver", 3): 290, ("gold", 1): 330, ("gold", 3): 370}
# Where the pieces sit, by how many there are: spread over the face like pips.
SPREAD = {
    1: [(375, 490)],
    2: [(375, 320), (375, 660)],
    3: [(375, 300), (225, 660), (525, 660)],
    4: [(225, 320), (525, 320), (225, 660), (525, 660)],
}

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


def _spread(img: Image.Image, items: list[Image.Image]) -> None:
    for im, (cx, cy) in zip(items, SPREAD[len(items)]):
        img.alpha_composite(im, (cx - im.width // 2, cy - im.height // 2))


def card(icon_set: IconSet, suit: str, rank: str) -> Image.Image:
    fate = fate_of(suit, rank)
    p = PALETTE[fate]
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, W - 1, H - 1), RADIUS, fill=p["paper"])
    d.rounded_rectangle((18, 18, W - 19, H - 19), RADIUS - 12, outline=p["ink"], width=5)
    d.rounded_rectangle((30, 30, W - 31, H - 31), RADIUS - 20, outline=p["ink2"], width=2)

    short = {"Left": "L", "Right": "R"}.get(rank, rank)
    corner = Image.new("RGBA", (130, 150), (0, 0, 0, 0))
    ImageDraw.Draw(corner).text((65, 0), short, font=font(66), fill=p["ink"], anchor="ma")
    corner.alpha_composite(icon_set.mark(suit, fate, 62), (34, 84))
    img.alpha_composite(corner, (42, 40))
    img.alpha_composite(corner.rotate(180), (W - 172, H - 190))

    d.text((W // 2, 96), suit.upper(), font=font(40), fill=p["ink2"], anchor="mm")
    if suit == "money":
        _spread(img, [coin_image(metal, amount, fate) for metal, amount in money_coins(rank)])
    else:
        _spread(img, [icon_set.piece(suit, value, fate, PIECE_SIZE[value]) for value in pieces(suit, rank)])
    if rank in ("Left", "Right"):
        d.text((W // 2, 862), rank.upper(), font=font(80), fill=p["ink"], anchor="mm")
    else:
        d.text((W // 2, 862), rank, font=font(120), fill=p["ink"], anchor="mm")
    d.text((W // 2, 962), fate.upper(), font=font(24), fill=p["ink2"], anchor="mm")
    return img


def deck_cards(icon_set: IconSet) -> dict[tuple[str, str], Image.Image]:
    """Every card, keyed by (suit, rank), in the deck's order."""
    return {(suit, rank): card(icon_set, suit, rank) for suit in SUITS for rank in RANKS}


def flatten(card_image: Image.Image) -> Image.Image:
    """A card on white, for a sheet."""
    page = Image.new("RGB", card_image.size, "white")
    page.paste(card_image, (0, 0), card_image)
    return page


# --- contact sheets, for looking at the deck -------------------------------

def deck_sheet(cards: dict, scale: float = 0.2) -> Image.Image:
    """All 72, a suit a row, in rank order."""
    cw, ch, gap = round(W * scale), round(H * scale), 10
    img = Image.new("RGB", (12 * cw + 13 * gap, 6 * ch + 7 * gap), "#5a5a5a")
    for (suit, rank), c in cards.items():
        x = gap + RANKS.index(rank) * (cw + gap)
        y = gap + SUITS.index(suit) * (ch + gap)
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
