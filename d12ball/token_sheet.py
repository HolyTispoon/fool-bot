"""
The condition tokens as two sheets of paper, for the print-and-play kit.

The same three double-sided tokens the 3D-printed set is made of (see
docs/design/printed-tokens.md), in the same pairings and the same
shapes as the art `render.py` puts on a player's card. On paper a
token is **printed duplex** (the author, 2026-09-27):
one sheet carries every token's front face and the other its back, and
the two are printed on the two sides of one piece of paper.

A duplex printer flips the paper about its long edge, so the back sheet
is the front sheet mirrored left to right -- each token's back sits at
its front's position reflected about the page's centre line, which is
the same correction `cards.duplex_order` makes for the card sheets.

Every sheet comes in two styles (`STYLES`), and the kit carries both
(the author, 2026-09-28). `dark` is the bot's own art as it is, each
face on a thin black margin (`BLEED_INCHES`) so the two sides coming out
of register by a little leaves black at the cut rather than white paper.
`light` is drawn for paper, since a sheet of black tokens is a cartridge
of ink: a pale tint inside a ring, the word in a deep ink dark enough to
read at 19 mm (`PAPER_FACES`). Its squares are drawn here; its triangle
is the dark art's own regions recoloured, so the Zs are exactly where
the dark one has them. A light front carries a grey hairline to cut on,
`CUT_MARGIN_INCHES` outside the token -- far enough that a back printed a
little out of register still keeps its ring.

`scripts/render_token_sheet.py` is the CLI.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from .boards import PAPERS, PRINT_DPI
from .render import (
    DAMAGED_ICON_PATH,
    DRAINED_ICON_PATH,
    EXHAUST_CYBORG_ICON_PATH,
    EXHAUST_ICON_PATH,
    EXHAUSTED_ICON_PATH,
    FONT_DIR,
    INJURED_ICON_PATH,
)

# Each token's two faces, front and back, in the author's pairings
# (2026-09-25, the 3D-printed set): the exhaustion token with its Cyborg
# drain side, and each condition marker with the one it turns into on a
# failed check.
TOKEN_FACES: dict[str, tuple[str, str]] = {
    "exhaust": ("exhaust", "exhaust_cyborg"),
    "exhausted": ("exhausted", "injured"),
    "drained": ("drained", "damaged"),
}

# The two ways a sheet is printed (the author, 2026-09-28): `light`, drawn
# for paper, and `dark`, the bot's own art as it is. The kit carries both.
STYLES = ("light", "dark")

# Each face's art in the bot, which the dark sheets print as it is.
DARK_ART: dict[str, Path] = {
    "exhaust": EXHAUST_ICON_PATH,
    "exhaust_cyborg": EXHAUST_CYBORG_ICON_PATH,
    "exhausted": EXHAUSTED_ICON_PATH,
    "injured": INJURED_ICON_PATH,
    "drained": DRAINED_ICON_PATH,
    "damaged": DAMAGED_ICON_PATH,
}

# What each face says -- `None` is the triangle, which says ZZZ -- and
# its two inks: the deep one the ring and the word print in, dark
# enough to read on white at 19 mm, and the pale tint inside the ring.
# Each is the hue the bot's own art uses for that face, taken darker or
# lighter; none is that art's own colour, which was chosen to glow on
# black and washes out on paper.
PAPER_FACES: dict[str, tuple[str | None, tuple[int, int, int], tuple[int, int, int]]] = {
    "exhaust": (None, (168, 104, 0), (255, 241, 208)),
    "exhaust_cyborg": (None, (0, 122, 122), (216, 240, 240)),
    "exhausted": ("EXHAUSTED", (168, 104, 0), (255, 241, 208)),
    "injured": ("INJURED", (200, 36, 0), (253, 226, 218)),
    "drained": ("DRAINED", (0, 122, 122), (216, 240, 240)),
    "damaged": ("DAMAGED", (140, 16, 56), (250, 222, 230)),
}

# How many of each the sheet carries: every kind, the exhaustion
# triangles the most, and the page full (the author, 2026-09-27 -- the
# exact count does not matter much, since a table that wants more
# prints the page again). Ten rows of eight on letter: six of
# triangles, two of each marker.
TOKEN_COUNTS: dict[str, int] = {
    "exhaust": 48,
    "exhausted": 16,
    "drained": 16,
}

# A token is 19 mm across, because a jumbotron silo (`SILO_INCHES`) is
# a token wide -- the printed-tokens note's reasoning, unchanged.
TOKEN_INCHES = 19 / 25.4
TOKEN_SHEET_PAPER = "letter"
MARGIN_INCHES = 0.5
# The white between two tokens' cut lines.
GAP_INCHES = 0.1
# How far outside the token the front's cut line runs: about a
# millimetre, which is what a home duplex printer is out by, so a back
# that lands a little off still has its whole ring after the cut.
CUT_MARGIN_INCHES = 0.04
# The cut line itself: a hairline, light, since it is cut away.
CUT_LINE_INCHES = 0.006
CUT_LINE_COLOR = (170, 170, 170, 255)
# A dark face's black margin past its own edge, on both sides: the same
# millimetre, so a back out of register leaves black at the cut rather
# than white paper.
BLEED_INCHES = 0.04

# The squares, as shares of the token's width. The shape is the bot's,
# so a paper token is the thing a coach already knows; the triangle is
# the bot's art itself (`triangle_regions`).
SUPERSAMPLE = 4
RING = 0.075
SQUARE_CORNER = 0.17
# The word, squashed into this box, since Roboto Slab has no condensed
# face; EXHAUSTED and INJURED fill the same box so they read as a set.
WORD_BOX = (0.78, 0.34)

FONT_PATH = FONT_DIR / "RobotoSlab-Bold.ttf"


def pixels(inches: float) -> int:
    return round(inches * PRINT_DPI)


@lru_cache(maxsize=1)
def triangle_regions() -> tuple[Image.Image, Image.Image]:
    """
    The exhaustion triangle as the bot draws it, in two masks cropped to
    its outline: the whole silhouette, and the black face inside the
    ring. Everything in the first and not the second -- the black edge,
    the ring and the three Zs -- is what a light triangle prints deep,
    so its Zs are where the dark one's are, to the pixel (the author,
    2026-09-28). Read off `exhaust.png`; the Cyborg side is its recolour.
    """
    with Image.open(EXHAUST_ICON_PATH) as source:
        art = source.convert("RGBA")
    art = art.crop(art.getchannel("A").getbbox())
    opaque = art.getchannel("A").point(lambda value: 255 if value > 127 else 0)
    # Colour against ink: the art is a near-black and one amber, so the
    # halfway brightness between its darkest and brightest splits them.
    brightness = art.convert("L")
    histogram = brightness.histogram(mask=opaque)
    lit = [level for level, count in enumerate(histogram) if count]
    split = (lit[0] + lit[-1]) // 2
    regions = Image.new("L", art.size, 0)
    regions.paste(1, mask=opaque)
    regions.paste(2, mask=ImageChops.multiply(
        opaque, brightness.point(lambda value: 255 if value > split else 0)
    ))
    # The face is the black the ring encloses: flood it from the middle
    # of the lower half, which no Z reaches.
    seed = (art.width // 2, round(art.height * 0.62))
    if regions.getpixel(seed) != 1:
        raise ValueError(f"{EXHAUST_ICON_PATH.name} has no black face at {seed}")
    ImageDraw.floodfill(regions, seed, 3)
    face = regions.point(lambda value: 255 if value == 3 else 0)
    return art.getchannel("A"), face


def lettering(text: str, box: tuple[int, int], color: tuple[int, int, int]) -> Image.Image:
    """`text` in Roboto Slab Bold, cropped to its ink and squashed to `box`."""
    font = ImageFont.truetype(str(FONT_PATH), 400)
    left, top, right, bottom = font.getbbox(text)
    mask = Image.new("L", (right - left, bottom - top), 0)
    ImageDraw.Draw(mask).text((-left, -top), text, font=font, fill=255)
    mask = mask.crop(mask.getbbox()).resize(box, Image.Resampling.LANCZOS)
    layer = Image.new("RGBA", box, color + (255,))
    layer.putalpha(mask)
    return layer


def paper_face(name: str, width: int) -> Image.Image:
    """
    One face `width` across, drawn for paper: a ring and a word (or the
    three Zs) in its deep ink, on its pale tint.
    """
    word, deep, tint = PAPER_FACES[name]
    if word is None:
        silhouette, inside = triangle_regions()
        size = (width, round(silhouette.height * width / silhouette.width))
        face = Image.new("RGBA", size, deep + (255,))
        face.putalpha(silhouette.resize(size, Image.Resampling.LANCZOS))
        fill = Image.new("RGBA", size, tint + (255,))
        fill.putalpha(inside.resize(size, Image.Resampling.LANCZOS))
        face.alpha_composite(fill)
        return face
    size = width * SUPERSAMPLE
    ring = size * RING
    face = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    pen = ImageDraw.Draw(face)
    corner = size * SQUARE_CORNER
    pen.rounded_rectangle((0, 0, size - 1, size - 1), radius=corner, fill=deep)
    pen.rounded_rectangle(
        (ring, ring, size - 1 - ring, size - 1 - ring), radius=corner - ring, fill=tint
    )
    text = lettering(word, (round(size * WORD_BOX[0]), round(size * WORD_BOX[1])), deep)
    face.alpha_composite(text, ((size - text.width) // 2, (size - text.height) // 2))
    return face.resize((width, width), Image.Resampling.LANCZOS)


def edge_color(art: Image.Image) -> tuple[int, int, int, int]:
    """The colour of the art's outer edge: a few pixels in from where
    it turns opaque, halfway down its left side."""
    middle = art.height // 2
    first = next(x for x in range(art.width) if art.getpixel((x, middle))[3] > 200)
    red, green, blue, _ = art.getpixel((first + 2, middle))
    return (red, green, blue, 255)


def dark_face(name: str, width: int) -> Image.Image:
    """
    One face as the bot draws it, cropped to its own outline, scaled to
    `width`, and set on a black margin `BLEED_INCHES` wide that follows
    its shape.
    """
    with Image.open(DARK_ART[name]) as source:
        art = source.convert("RGBA")
    art = art.crop(art.getchannel("A").getbbox())
    art = art.resize((width, round(art.height * width / art.width)), Image.Resampling.LANCZOS)
    bleed = pixels(BLEED_INCHES)
    face = Image.new("RGBA", (art.width + 2 * bleed, art.height + 2 * bleed), (0, 0, 0, 0))
    face.alpha_composite(art, (bleed, bleed))
    # The margin is the art's own outline grown by the bleed, in the
    # colour of its edge -- read off the art, since each token's black
    # is its own (the triangle's is warm).
    grown = face.getchannel("A").point(lambda value: 255 if value > 127 else 0)
    grown = grown.filter(ImageFilter.MaxFilter(2 * bleed + 1))
    backing = Image.new("RGBA", face.size, edge_color(art))
    backing.putalpha(grown)
    backing.alpha_composite(face)
    return backing


def token_face(name: str, width: int, cut_line: bool) -> Image.Image:
    """
    One face with room around it for the cut line -- drawn when
    `cut_line` is set, `CUT_MARGIN_INCHES` outside the token.
    """
    art = paper_face(name, width)
    margin = pixels(CUT_MARGIN_INCHES) + pixels(CUT_LINE_INCHES)
    face = Image.new("RGBA", (art.width + 2 * margin, art.height + 2 * margin), (0, 0, 0, 0))
    face.alpha_composite(art, (margin, margin))
    if not cut_line:
        return face
    # The line follows the token's own outline, grown by the margin.
    inner = face.getchannel("A").point(lambda value: 255 if value > 127 else 0)
    inner = inner.filter(ImageFilter.MaxFilter(2 * pixels(CUT_MARGIN_INCHES) + 1))
    outer = inner.filter(ImageFilter.MaxFilter(2 * max(1, pixels(CUT_LINE_INCHES)) + 1))
    line = Image.new("RGBA", face.size, CUT_LINE_COLOR)
    line.putalpha(ImageChops.subtract(outer, inner))
    line.alpha_composite(face)
    return line


def render_token_sheets(
    paper: str = TOKEN_SHEET_PAPER, style: str = "light"
) -> tuple[Image.Image, Image.Image]:
    """
    The front sheet and the back sheet in `style`: every token in
    `TOKEN_COUNTS`, row by row in its order, its front on the first and
    its back on the second at the mirrored position.
    """
    if style not in STYLES:
        raise ValueError(f"no token style {style!r}; there are {', '.join(STYLES)}")
    page = (pixels(PAPERS[paper][0]), pixels(PAPERS[paper][1]))
    margin, gap = pixels(MARGIN_INCHES), pixels(GAP_INCHES)
    width = pixels(TOKEN_INCHES)
    # A light token's cut line is on the front alone: cut along it, and a
    # back a little out of register loses only white. A dark one is cut
    # through its black margin.
    faces = {
        name: tuple(
            token_face(face, width, cut_line=not side) if style == "light"
            else dark_face(face, width)
            for side, face in enumerate(pair)
        )
        for name, pair in TOKEN_FACES.items()
        if name in TOKEN_COUNTS
    }
    cell = (
        max(face.width for pair in faces.values() for face in pair),
        max(face.height for pair in faces.values() for face in pair),
    )

    columns = (page[0] - 2 * margin + gap) // (cell[0] + gap)
    tokens = [name for name, count in TOKEN_COUNTS.items() for _ in range(count)]
    rows = -(-len(tokens) // columns)
    used = (
        columns * cell[0] + (columns - 1) * gap,
        rows * cell[1] + (rows - 1) * gap,
    )
    if used[1] > page[1] - 2 * margin:
        raise ValueError(
            f"{len(tokens)} tokens need {rows} rows of {columns}, "
            f"more than a {paper} sheet holds"
        )

    sheets = (Image.new("RGBA", page, "white"), Image.new("RGBA", page, "white"))
    left = (page[0] - used[0]) // 2
    top = (page[1] - used[1]) // 2
    for index, name in enumerate(tokens):
        row, column = divmod(index, columns)
        for side, (sheet, face) in enumerate(zip(sheets, faces[name])):
            x = left + column * (cell[0] + gap) + (cell[0] - face.width) // 2
            if side:
                # Flipped about the long edge: the back of a token is at
                # its front's position mirrored about the centre line.
                x = page[0] - x - face.width
            y = top + row * (cell[1] + gap) + (cell[1] - face.height) // 2
            sheet.alpha_composite(face, (x, y))
    return sheets[0].convert("RGB"), sheets[1].convert("RGB")
