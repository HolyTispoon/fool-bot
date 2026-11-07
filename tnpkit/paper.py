"""
The paper the kit is printed on: 300 dpi, letter and tabloid, a sheet
as a white Pillow image, the cut grid the pieces are laid out on, and a
tabloid sheet cut into two letter halves.

**A half is a cut of the finished sheet, never a second layout**, as
D12 Ball's field board is (docs/design/printed-boards.md): 17 x 11 in
halves into two 8.5 x 11 in sheets to the pixel, so the two taped
together are the tabloid sheet.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Sequence

from PIL import Image, ImageDraw

from tnp.render import MUTED, font

DPI = 300

#: Each paper's short and long side, in inches.
PAPERS = {
    "letter": (8.5, 11.0),
    "tabloid": (11.0, 17.0),
}

#: How far from the paper's edge anything is drawn: past what a home
#: printer's rollers leave unprinted.
MARGIN = 0.25

#: A cut line between two pieces: a thin grey line, cut on.
CUT = (150, 152, 158)


def px(inches: float) -> int:
    return round(inches * DPI)


def sheet(paper: str, landscape: bool) -> Image.Image:
    short, long = PAPERS[paper]
    width, height = (long, short) if landscape else (short, long)
    return Image.new("RGB", (px(width), px(height)), (255, 255, 255))


def halves(image: Image.Image) -> tuple[Image.Image, Image.Image]:
    """A tabloid landscape sheet as two letter portrait sheets, left and
    right, cut down the middle."""
    middle = image.width // 2
    return image.crop((0, 0, middle, image.height)), image.crop((middle, 0, image.width, image.height))


#: One piece on a cut sheet: draws itself on a blank image the size of
#: the grid's cell.
Piece = Callable[[Image.Image], None]


def cut_sheet(
    pieces: Sequence[Piece],
    cell: tuple[float, float],
    paper: str = "letter",
    landscape: bool = False,
    title: str = "",
    turned: bool = False,
) -> list[Image.Image]:
    """
    `pieces` laid out edge to edge on a grid of `cell` (inches, wide x
    tall), as many sheets as they take, each sheet's grid centred and
    ruled with cut lines -- one cut separates two pieces. `title` is
    printed small in the top margin of each sheet, with its number.
    `turned` lays each piece on its side: it is drawn `cell` tall x
    wide, upright, and turned a quarter onto the grid, so a portrait
    card packs a sheet as tightly as a landscape one.
    """
    page = sheet(paper, landscape)
    cell_w, cell_h = (px(cell[1]), px(cell[0])) if turned else (px(cell[0]), px(cell[1]))
    usable_w = page.width - 2 * px(MARGIN)
    usable_h = page.height - 2 * px(MARGIN) - px(0.2)
    columns, rows = usable_w // cell_w, usable_h // cell_h
    per_sheet = columns * rows
    count = -(-len(pieces) // per_sheet)
    sheets = []
    for number in range(count):
        page = sheet(paper, landscape)
        chunk = pieces[number * per_sheet:(number + 1) * per_sheet]
        used_rows = -(-len(chunk) // columns)
        grid_w, grid_h = columns * cell_w, used_rows * cell_h
        left = (page.width - grid_w) // 2
        top = px(MARGIN) + px(0.2) + (usable_h - rows * cell_h) // 2
        for index, piece in enumerate(chunk):
            row, column = divmod(index, columns)
            tile = Image.new("RGB", (cell_h, cell_w) if turned else (cell_w, cell_h), (255, 255, 255))
            piece(tile)
            if turned:
                tile = tile.transpose(Image.Transpose.ROTATE_90)
            page.paste(tile, (left + column * cell_w, top + row * cell_h))
        draw = ImageDraw.Draw(page)
        # The cut lines: every piece outlined, the shared edges drawn
        # once over each other, so one cut separates two pieces; and a
        # tick into the margin at each end of every line, so the first
        # cut can be lined up by eye.
        for index in range(len(chunk)):
            row, column = divmod(index, columns)
            x, y = left + column * cell_w, top + row * cell_h
            draw.rectangle((x, y, x + cell_w, y + cell_h), outline=CUT, width=2)
        reach = px(0.15)
        bottom = top + used_rows * cell_h
        for row in range(used_rows + 1):
            y = top + row * cell_h
            draw.line((left - reach, y, left, y), fill=CUT, width=2)
            draw.line((left + grid_w, y, left + grid_w + reach, y), fill=CUT, width=2)
        for column in range(columns + 1):
            x = left + column * cell_w
            draw.line((x, top - reach, x, top), fill=CUT, width=2)
            draw.line((x, bottom, x, bottom + reach), fill=CUT, width=2)
        if title:
            words = f"{title} · sheet {number + 1} of {count}" if count > 1 else title
            draw.text((px(MARGIN), px(MARGIN)), words, font=font(px(0.12)), fill=MUTED, anchor="lt")
        sheets.append(page)
    return sheets


def save(images: Sequence[Image.Image], path: Path) -> list[Path]:
    """Each image as a PNG beside `path` (numbered where there are
    several) and all of them as one PDF at `path`; the files written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    written = []
    stem = path.with_suffix("")
    for index, image in enumerate(images):
        name = stem.with_name(f"{stem.name}-{index + 1}.png" if len(images) > 1 else f"{stem.name}.png")
        image.save(name, dpi=(DPI, DPI), optimize=True)
        written.append(name)
    pdf = path.with_suffix(".pdf")
    images[0].save(pdf, "PDF", resolution=DPI, save_all=True, append_images=list(images[1:]))
    written.append(pdf)
    return written
