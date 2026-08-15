"""
The Tethys deck printed -- one card per entry in `tethysdeck/deck.py`,
plus the one back they all share.

Poker size at 300dpi, out of `d12ball/cards.py`'s `Pen`, `print_sheet`
and palette. The two games are unrelated, but a card is a card: the
printing machinery, the 1/8in bleed and the sheet that divides evenly
into its cards are all solved there, and a second copy of them would be
a second set of bugs.

**The layout is a playing card's, not this repo's other cards'.** A
maneuver or a player card is read face up on a table, so it can afford
a header band and a paragraph; a Tethys card is drawn into a hand,
fanned, and discarded, so what it owes its holder is a corner index
they can read with the rest of the card covered. Hence indices at two
opposite corners, a pip count in the middle, and the suit spelled out
along the bottom for a symbol nobody has memorised yet.

**Left and Right are the deck's court cards.** They are the two ranks
with nothing to count, so they get the suit's symbol at ace size and an
arrow saying which way, rather than a pip layout that would have to
invent a number for them.

Nothing here names a card: the suits, the ranks and the names come from
`tethysdeck/deck.py`, which is the same list the bot shuffles into a
channel, so a printed deck and a dealt one cannot drift.
"""
from math import cos, radians, sin

from PIL import Image, ImageFont

from d12ball.cards import (
    BACK_COLOR,
    BACK_EDGE,
    CARD_FACE,
    CARD_HEIGHT,
    CARD_WIDTH,
    CORNER,
    EDGE_WIDTH,
    FRAME,
    INK,
    MUTED,
    Pen,
    font,
)
from tethysdeck.deck import SUITS, Card, Suit

# One hue a suit, far enough apart to tell across a table under bad
# light -- which is most of what a suit colour is for, since the symbol
# is small at pip size and the name is only on the footer.
SUIT_COLORS = {
    "Money": "#2E7D4F",
    "Might": "#B23A3A",
    "Fiends": "#6B4A8C",
    "Tools": "#4F5B66",
    "States": "#2B6CA3",
    "Fools": "#C9901A",
}

# **The bundled font cannot draw Fiends' symbol.** U+3020 is a
# placeholder for a symbol upstream has not filled in (see
# `tethysdeck/deck.py`), and DejaVu has no glyph for it -- Pillow draws
# a hollow box, which prints as a hollow box. Discord renders it from
# the reader's own fonts, so the bot's text is unaffected and only the
# print needs a stand-in. The suit's name is on the card either way,
# which is what actually identifies it; when upstream settles a symbol,
# it replaces the one in `deck.py` and this entry goes.
PRINT_SYMBOLS = {"Fiends": "☠"}

# The corner index: what a rank is called when there is room for one or
# two characters. Numbers say themselves.
RANK_INDICES = {"Left": "L", "Right": "R"}

# The index blocks, at two opposite corners so the card reads the same
# either way up in a hand.
INDEX_X = 92
INDEX_RANK_Y = 104
INDEX_RANK_SIZE = 66
INDEX_SYMBOL_Y = 176
INDEX_SYMBOL_HEIGHT = 52

# What the pips are laid out in. Everything below is a fraction of this
# box, so a change here moves the whole count together.
PIP_LEFT = 212
PIP_RIGHT = CARD_WIDTH - PIP_LEFT
PIP_TOP = 250
PIP_BOTTOM = 820

# A pip shrinks as the count grows, or a ten runs into itself. The ace
# is not a count at all -- one symbol in the middle of the card, the
# way every deck draws it.
ACE_HEIGHT = 250
PIP_HEIGHTS = {5: 96, 8: 84, 10: 70}

FOOTER_Y = 960
FOOTER_SIZE = 27

# The court cards' block: the symbol at ace size, the arrow under it,
# and the word under that.
COURT_SYMBOL_HEIGHT = 210
COURT_SYMBOL_Y = 400
COURT_ARROW_Y = 610
COURT_ARROW_WIDTH = 260
COURT_ARROW_HEIGHT = 88
COURT_WORD_Y = 740
COURT_WORD_SIZE = 62

# Standard playing-card pip positions, as fractions of the pip box: x
# across (0 left, 1 right), y down. Counts up to eight sit on quarters
# and the two big ones on thirds, which is what keeps a nine and a ten
# from crowding the middle.
_COLUMN_ROWS = {
    "quarters": (0.0, 0.25, 0.5, 0.75, 1.0),
    "thirds": (0.0, 1 / 3, 2 / 3, 1.0),
}
PIP_LAYOUTS: dict[int, tuple[tuple[float, float], ...]] = {
    1: ((0.5, 0.5),),
    2: ((0.5, 0.0), (0.5, 1.0)),
    3: ((0.5, 0.0), (0.5, 0.5), (0.5, 1.0)),
    4: ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)),
    5: ((0.0, 0.0), (1.0, 0.0), (0.5, 0.5), (0.0, 1.0), (1.0, 1.0)),
    6: (
        (0.0, 0.0), (1.0, 0.0),
        (0.0, 0.5), (1.0, 0.5),
        (0.0, 1.0), (1.0, 1.0),
    ),
    7: (
        (0.0, 0.0), (1.0, 0.0),
        (0.5, 0.25),
        (0.0, 0.5), (1.0, 0.5),
        (0.0, 1.0), (1.0, 1.0),
    ),
    8: (
        (0.0, 0.0), (1.0, 0.0),
        (0.5, 0.25),
        (0.0, 0.5), (1.0, 0.5),
        (0.5, 0.75),
        (0.0, 1.0), (1.0, 1.0),
    ),
    9: (
        (0.0, 0.0), (1.0, 0.0),
        (0.0, 1 / 3), (1.0, 1 / 3),
        (0.5, 0.5),
        (0.0, 2 / 3), (1.0, 2 / 3),
        (0.0, 1.0), (1.0, 1.0),
    ),
    10: (
        (0.0, 0.0), (1.0, 0.0),
        (0.5, 1 / 6),
        (0.0, 1 / 3), (1.0, 1 / 3),
        (0.0, 2 / 3), (1.0, 2 / 3),
        (0.5, 5 / 6),
        (0.0, 1.0), (1.0, 1.0),
    ),
}


def print_symbol(suit: Suit) -> str:
    """The symbol this suit is printed with; see PRINT_SYMBOLS."""
    return PRINT_SYMBOLS.get(suit.name, suit.symbol)


def rank_index(card: Card) -> str:
    return RANK_INDICES.get(card.rank, card.rank)


def pip_height(count: int) -> float:
    for limit in sorted(PIP_HEIGHTS):
        if count <= limit:
            return PIP_HEIGHTS[limit]
    return PIP_HEIGHTS[max(PIP_HEIGHTS)]


_SYMBOL_FONTS: dict[tuple[str, float], ImageFont.ImageFont] = {}


def symbol_font(pen: Pen, symbol: str, height: float) -> ImageFont.ImageFont:
    """
    The largest face that draws `symbol` no taller than `height`.

    Measured rather than calculated, because the six symbols are not one
    typeface's worth of design: `$` is tall and narrow where `⚔` is wide
    and short, so a size that suits one draws another half again too
    big. Cached, since a deck asks for the same handful of sizes 72
    times over.
    """
    key = (symbol, height)
    if key not in _SYMBOL_FONTS:
        size = round(height * 1.6)
        while size > 8:
            face = font(size)
            box = pen.ink_box(symbol, face)
            if box[3] - box[1] <= height:
                break
            size -= 2
        _SYMBOL_FONTS[key] = face
    return _SYMBOL_FONTS[key]


def draw_symbol(
    pen: Pen,
    center: tuple[float, float],
    symbol: str,
    height: float,
    color: str,
) -> None:
    """
    A suit symbol centred on its own ink. Pillow's `m` anchor centres on
    the font's ascender and descender, which for a symbol that uses
    neither leaves it sitting visibly high in the space it was given --
    and a pip layout is nothing but the eye reading a grid.
    """
    face = symbol_font(pen, symbol, height)
    box = pen.ink_box(symbol, face)
    pen.text(
        (center[0], center[1] - (box[1] + box[3]) / 2),
        symbol,
        face,
        color,
        anchor="mm",
    )


def draw_index(
    pen: Pen,
    card: Card,
    color: str,
    rotated: bool,
) -> None:
    """
    The rank over the symbol, in the top-left corner -- and again in the
    bottom-right, turned around, so a card held either way up shows one.
    Drawn on its own transparent layer for the rotated copy, since text
    is the one thing on the card that cannot be drawn upside down.
    """
    label = rank_index(card)
    symbol = print_symbol(card.suit)

    if not rotated:
        rank_face = font(INDEX_RANK_SIZE, bold=True)
        pen.text(
            (INDEX_X, INDEX_RANK_Y), label, rank_face, color, anchor="mm"
        )
        draw_symbol(
            pen,
            (INDEX_X, INDEX_SYMBOL_Y),
            symbol,
            INDEX_SYMBOL_HEIGHT,
            color,
        )
        return

    corner = Pen((CARD_WIDTH, CARD_HEIGHT), CARD_FACE)
    draw_index(corner, card, color, rotated=False)
    turned = corner.image.rotate(180)
    pen.image.paste(turned, (0, 0), _corner_mask(turned))


def _corner_mask(turned: Image.Image) -> Image.Image:
    """
    The rotated index carries a whole card's worth of face colour with
    it, so only the marks are pasted: anything that is not the face.
    """
    return turned.convert("L").point(lambda value: 255 if value < 250 else 0)


def draw_pips(pen: Pen, card: Card, color: str) -> None:
    count = int(card.rank)
    symbol = print_symbol(card.suit)

    if count == 1:
        draw_symbol(
            pen,
            (CARD_WIDTH / 2, (PIP_TOP + PIP_BOTTOM) / 2),
            symbol,
            ACE_HEIGHT,
            color,
        )
        return

    height = pip_height(count)
    for x_fraction, y_fraction in PIP_LAYOUTS[count]:
        draw_symbol(
            pen,
            (
                PIP_LEFT + (PIP_RIGHT - PIP_LEFT) * x_fraction,
                PIP_TOP + (PIP_BOTTOM - PIP_TOP) * y_fraction,
            ),
            symbol,
            height,
            color,
        )


def draw_arrow(pen: Pen, center: tuple[float, float], rightward: bool, color: str) -> None:
    """
    Which way a Left or a Right points. A shaft and a head rather than a
    glyph, because the arrows in the bundled font are a text size and
    this is the second-largest thing on the card.
    """
    x, y = center
    half = COURT_ARROW_WIDTH / 2
    head = COURT_ARROW_HEIGHT
    shaft = COURT_ARROW_HEIGHT / 3
    tip = x + half if rightward else x - half
    base = x - half if rightward else x + half
    shoulder = tip - head if rightward else tip + head

    pen.rect((min(base, shoulder), y - shaft / 2, max(base, shoulder), y + shaft / 2), fill=color)
    pen.polygon(
        [(tip, y), (shoulder, y - head / 2), (shoulder, y + head / 2)],
        fill=color,
    )


def draw_court(pen: Pen, card: Card, color: str) -> None:
    rightward = card.rank == "Right"
    draw_symbol(
        pen,
        (CARD_WIDTH / 2, COURT_SYMBOL_Y),
        print_symbol(card.suit),
        COURT_SYMBOL_HEIGHT,
        color,
    )
    draw_arrow(pen, (CARD_WIDTH / 2, COURT_ARROW_Y), rightward, color)
    pen.text(
        (CARD_WIDTH / 2, COURT_WORD_Y),
        card.rank.upper(),
        font(COURT_WORD_SIZE, bold=True),
        color,
        anchor="mm",
    )


def render_tethys_card(card: Card, bleed: bool = False) -> Image.Image:
    """
    One card, print-ready. `bleed` adds the 1/8in a print shop trims
    into; without it the rounded outline is the cut line, as on every
    other card in this repo.
    """
    color = SUIT_COLORS[card.suit.name]
    pen = Pen((CARD_WIDTH, CARD_HEIGHT), CARD_FACE)
    pen.rect(
        (FRAME, FRAME, CARD_WIDTH - FRAME, CARD_HEIGHT - FRAME),
        radius=CORNER,
        fill=CARD_FACE,
        outline=color,
        width=EDGE_WIDTH,
    )

    if card.is_number:
        draw_pips(pen, card, color)
    else:
        draw_court(pen, card, color)

    # The suit spelled out. A symbol nobody has played with yet names
    # nothing on its own, and the bot's own text says "of ⚒ Tools" --
    # so the card a player matches to a Discord message says both.
    pen.text(
        (CARD_WIDTH / 2, FOOTER_Y),
        card.suit.name.upper(),
        font(FOOTER_SIZE, bold=True),
        color,
        anchor="mm",
    )

    draw_index(pen, card, color, rotated=False)
    draw_index(pen, card, color, rotated=True)
    return pen.finish(bleed, CARD_FACE)


# The six suits on the back, as a ring: the one thing worth printing
# there is what the deck is made of, since a player holding a Tethys
# card is holding a suit they cannot see.
BACK_RING_RADIUS_X = 250
BACK_RING_RADIUS_Y = 250
BACK_RING_CENTER_Y = 570
BACK_NODE_RADIUS = 84
BACK_NODE_SYMBOL_HEIGHT = 58


def render_tethys_card_back(bleed: bool = False) -> Image.Image:
    """
    One back for all seventy-two, for the ordinary reason: a card in a
    hand must not say which one it is.
    """
    pen = Pen((CARD_WIDTH, CARD_HEIGHT), BACK_COLOR)
    pen.rect(
        (FRAME, FRAME, CARD_WIDTH - FRAME, CARD_HEIGHT - FRAME),
        radius=CORNER,
        fill=BACK_COLOR,
        outline=BACK_EDGE,
        width=EDGE_WIDTH,
    )
    pen.text(
        (CARD_WIDTH / 2, 128), "TETHYS", font(58, bold=True), INK, anchor="mm"
    )
    pen.text(
        (CARD_WIDTH / 2, 182),
        "SIX SUITS OF TWELVE",
        font(22, bold=True),
        MUTED,
        anchor="mm",
    )

    center = (CARD_WIDTH / 2, BACK_RING_CENTER_Y)
    for index, suit in enumerate(SUITS):
        angle = 270 + 360 * index / len(SUITS)
        point = (
            center[0] + BACK_RING_RADIUS_X * cos(radians(angle)),
            center[1] + BACK_RING_RADIUS_Y * sin(radians(angle)),
        )
        pen.circle(point, BACK_NODE_RADIUS, fill=SUIT_COLORS[suit.name])
        draw_symbol(
            pen,
            (point[0], point[1] - 16),
            print_symbol(suit),
            BACK_NODE_SYMBOL_HEIGHT,
            "#ffffff",
        )
        pen.text(
            (point[0], point[1] + 46),
            suit.name.upper(),
            font(20, bold=True),
            "#ffffff",
            anchor="mm",
        )

    pen.text(
        (CARD_WIDTH / 2, CARD_HEIGHT - 116),
        "1-10 · Left · Right",
        font(24),
        MUTED,
        anchor="mm",
    )
    return pen.finish(bleed, BACK_COLOR)
