"""
The condition tokens as two sheets of paper, for the print-and-play kit.

The same three double-sided tokens the 3D-printed set is made of (see
docs/design/printed-tokens.md), in the same pairings, drawn from the
same art `render.py` puts on a player's card and the jumbotron's silos
show. On paper a token is **printed duplex** (the author, 2026-09-27):
one sheet carries every token's front face and the other its back, and
the two are printed on the two sides of one piece of paper.

A duplex printer flips the paper about its long edge, so the back sheet
is the front sheet mirrored left to right -- each token's back sits at
its front's position reflected about the page's centre line, which is
the same correction `player_cards.duplex_order` makes for the player
cards. Each face also carries a thin black margin beyond its own edge
(`BLEED_INCHES`), so the two sides coming out of register by a little
leaves black at the cut rather than white paper. No words: a token is
its own art, as a silo is.

`scripts/render_token_sheet.py` is the CLI.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageFilter

from .boards import PAPERS, PRINT_DPI
from .render import (
    DAMAGED_ICON_PATH,
    DRAINED_ICON_PATH,
    EXHAUST_CYBORG_ICON_PATH,
    EXHAUST_ICON_PATH,
    EXHAUSTED_ICON_PATH,
    INJURED_ICON_PATH,
)

# Each token's two faces, front and back, in the author's pairings
# (2026-09-25, the 3D-printed set): the exhaustion token with its Cyborg
# drain side, and each condition marker with the one it turns into on a
# failed check.
TOKEN_FACES: dict[str, tuple[Path, Path]] = {
    "exhaust": (EXHAUST_ICON_PATH, EXHAUST_CYBORG_ICON_PATH),
    "exhausted": (EXHAUSTED_ICON_PATH, INJURED_ICON_PATH),
    "drained": (DRAINED_ICON_PATH, DAMAGED_ICON_PATH),
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
# The white between two tokens' margins, which is where the scissors go.
GAP_INCHES = 0.12
# How far the black runs past a face's own edge, on both sides: about a
# millimetre, which is what a home duplex printer is out by.
BLEED_INCHES = 0.04


def pixels(inches: float) -> int:
    return round(inches * PRINT_DPI)


def edge_color(art: Image.Image) -> tuple[int, int, int, int]:
    """The colour of the art's outer edge: a few pixels in from where
    it turns opaque, halfway down its left side."""
    middle = art.height // 2
    first = next(x for x in range(art.width) if art.getpixel((x, middle))[3] > 200)
    red, green, blue, _ = art.getpixel((first + 2, middle))
    return (red, green, blue, 255)


def token_face(path: Path, width: int) -> Image.Image:
    """
    One face, cropped to its own outline, scaled to `width`, and set on
    a black margin `BLEED_INCHES` wide that follows its shape.
    """
    with Image.open(path) as source:
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


def render_token_sheets(paper: str = TOKEN_SHEET_PAPER) -> tuple[Image.Image, Image.Image]:
    """
    The front sheet and the back sheet: every token in `TOKEN_COUNTS`,
    row by row in its order, its front on the first and its back on the
    second at the mirrored position.
    """
    page = (pixels(PAPERS[paper][0]), pixels(PAPERS[paper][1]))
    margin, gap = pixels(MARGIN_INCHES), pixels(GAP_INCHES)
    width = pixels(TOKEN_INCHES)
    faces = {
        name: tuple(token_face(path, width) for path in paths)
        for name, paths in TOKEN_FACES.items()
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
