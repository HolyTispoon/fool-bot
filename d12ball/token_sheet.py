"""
The condition tokens as a sheet of paper, for the print-and-play kit.

The same three double-sided tokens the 3D-printed set is made of (see
docs/design/printed-tokens.md), in the same pairings, drawn from the
same art `render.py` puts on a player's card and the jumbotron's silos
show. On paper a token is a **fold-over pair**: its two faces printed
joined along one straight edge, cut out as one piece, folded on that
edge and glued. That needs no duplex printer and cannot come out of
register, which a 19 mm piece printed on two sides of a sheet would.

The back face is drawn flipped top to bottom, so that once it is folded
under it reads the right way up. Short grey ticks outside each pair mark
the fold. No words: a token is its own art, as a silo is.

`scripts/render_token_sheet.py` is the CLI.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from .boards import PAPERS, PRINT_DPI
from .render import (
    DAMAGED_ICON_PATH,
    DRAINED_ICON_PATH,
    EXHAUST_CYBORG_ICON_PATH,
    EXHAUST_ICON_PATH,
    EXHAUSTED_ICON_PATH,
    INJURED_ICON_PATH,
)

# Each token's two faces, in the author's pairings (2026-09-25, the
# 3D-printed set): the exhaustion token with its Cyborg drain side, and
# each condition marker with the one it turns into on a failed check.
TOKEN_FACES: dict[str, tuple[Path, Path]] = {
    "exhaust": (EXHAUST_ICON_PATH, EXHAUST_CYBORG_ICON_PATH),
    "exhausted": (EXHAUSTED_ICON_PATH, INJURED_ICON_PATH),
    "drained": (DRAINED_ICON_PATH, DAMAGED_ICON_PATH),
}

# How many of each a sheet carries, which is what fills one letter sheet
# at this size: the rules count no stock, so this is a first guess
# (2026-09-27) -- plenty of exhaustion, and a marker of each kind for
# most of a side's six fielded players.
TOKEN_COUNTS: dict[str, int] = {
    "exhaust": 32,
    "exhausted": 8,
    "drained": 8,
}

# A token is 19 mm across, because a jumbotron silo (`SILO_INCHES`) is
# a token wide -- the printed-tokens note's reasoning, unchanged.
TOKEN_INCHES = 19 / 25.4
TOKEN_SHEET_PAPER = "letter"
MARGIN_INCHES = 0.5
GAP_INCHES = 0.2
FOLD_MARK_INCHES = 0.08
FOLD_MARK_CLEARANCE_INCHES = 0.02
FOLD_MARK_COLOR = "#9aa5b1"
FOLD_MARK_WIDTH = 3


def pixels(inches: float) -> int:
    return round(inches * PRINT_DPI)


def token_face(path: Path, width: int) -> Image.Image:
    """One face, cropped to its own outline and scaled to `width`."""
    with Image.open(path) as source:
        art = source.convert("RGBA")
    art = art.crop(art.getchannel("A").getbbox())
    height = round(art.height * width / art.width)
    return art.resize((width, height), Image.Resampling.LANCZOS)


def token_pair(name: str, width: int) -> tuple[Image.Image, int]:
    """
    The token `name` as a fold-over pair, and the height of its fold
    from the pair's top: the back face above, flipped so it reads right
    once folded under, the front face below, the two sharing the front's
    top edge.
    """
    front_path, back_path = TOKEN_FACES[name]
    front = token_face(front_path, width)
    back = token_face(back_path, width).transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    pair = Image.new("RGBA", (width, back.height + front.height), (0, 0, 0, 0))
    pair.alpha_composite(back, (0, 0))
    pair.alpha_composite(front, (0, back.height))
    return pair, back.height


def render_token_sheet(paper: str = TOKEN_SHEET_PAPER) -> Image.Image:
    """Every token in `TOKEN_COUNTS`, row by row in its order, on one sheet."""
    page = (pixels(PAPERS[paper][0]), pixels(PAPERS[paper][1]))
    margin, gap = pixels(MARGIN_INCHES), pixels(GAP_INCHES)
    width = pixels(TOKEN_INCHES)
    pairs = {name: token_pair(name, width) for name in TOKEN_COUNTS}
    cell_height = max(pair.height for pair, _ in pairs.values())

    columns = (page[0] - 2 * margin + gap) // (width + gap)
    tokens = [name for name, count in TOKEN_COUNTS.items() for _ in range(count)]
    rows = -(-len(tokens) // columns)
    used = (
        columns * width + (columns - 1) * gap,
        rows * cell_height + (rows - 1) * gap,
    )
    if used[1] > page[1] - 2 * margin:
        raise ValueError(
            f"{len(tokens)} tokens need {rows} rows of {columns}, "
            f"more than a {paper} sheet holds"
        )

    sheet = Image.new("RGBA", page, "white")
    draw = ImageDraw.Draw(sheet)
    left = (page[0] - used[0]) // 2
    top = (page[1] - used[1]) // 2
    mark, clearance = pixels(FOLD_MARK_INCHES), pixels(FOLD_MARK_CLEARANCE_INCHES)
    for index, name in enumerate(tokens):
        pair, fold = pairs[name]
        row, column = divmod(index, columns)
        x = left + column * (width + gap)
        y = top + row * (cell_height + gap) + (cell_height - pair.height) // 2
        sheet.alpha_composite(pair, (x, y))
        for start in (x - clearance - mark, x + width + clearance):
            draw.line(
                (start, y + fold, start + mark, y + fold),
                fill=FOLD_MARK_COLOR, width=FOLD_MARK_WIDTH,
            )
    return sheet.convert("RGB")
