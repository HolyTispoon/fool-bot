"""The deck laid out for a printer, as PDF pages at 300 dpi.

`grid_pages`: letter upright, nine cards a page (three by three, 7.5 x
10.5 in) with crop marks in the margins, and a page of backs after every
page of fronts, so a duplex print flipped on the long edge puts each back
behind its front. The backs are one picture, so only the page order
matters, but they still go in `duplex_order` for the habit.

`avery_pages`: Avery Presta 95328, the pre-cut rounded-corner poker cards
the D12 Ball cards print on, with the geometry `d12ball.cards` holds:
letter landscape, six a page. Backs page after each fronts page, each row
reversed as the duplex flip needs -- `avery_95328_pages(backs=True)`.
"""
from pathlib import Path

from PIL import Image, ImageDraw
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from d12ball.cards import avery_95328_pages, duplex_order
from tethysdeck.cards import H, W, flatten

LETTER_PX = (2550, 3300)
CROP_MARK, CROP_GAP, CROP_COLOUR = 60, 12, "#888888"
GRID = (3, 3)


def grid_page(cards: list[Image.Image | None]) -> Image.Image:
    """Up to nine cards centred on a letter page, with crop marks."""
    columns, rows = GRID
    img = Image.new("RGB", LETTER_PX, "white")
    d = ImageDraw.Draw(img)
    grid_w, grid_h = columns * W, rows * H
    x0, y0 = (LETTER_PX[0] - grid_w) // 2, (LETTER_PX[1] - grid_h) // 2
    for index, card in enumerate(cards):
        if card is not None:
            img.paste(card, (x0 + (index % columns) * W, y0 + (index // columns) * H))
    for c in range(columns + 1):
        x = x0 + c * W
        d.line([(x, y0 - CROP_GAP - CROP_MARK), (x, y0 - CROP_GAP)], fill=CROP_COLOUR, width=2)
        d.line([(x, y0 + grid_h + CROP_GAP), (x, y0 + grid_h + CROP_GAP + CROP_MARK)], fill=CROP_COLOUR, width=2)
    for r in range(rows + 1):
        y = y0 + r * H
        d.line([(x0 - CROP_GAP - CROP_MARK, y), (x0 - CROP_GAP, y)], fill=CROP_COLOUR, width=2)
        d.line([(x0 + grid_w + CROP_GAP, y), (x0 + grid_w + CROP_GAP + CROP_MARK, y)], fill=CROP_COLOUR, width=2)
    return img


def grid_pages(cards: list[Image.Image], back: Image.Image) -> list[Image.Image]:
    """Fronts and backs, a page of each by turns."""
    per_page = GRID[0] * GRID[1]
    fronts = [flatten(c) for c in cards]
    back_flat = flatten(back)
    pages = []
    for start in range(0, len(fronts), per_page):
        page = fronts[start:start + per_page]
        pages.append(grid_page(page))
        pages.append(grid_page(duplex_order([back_flat] * len(page), GRID[0])))
    return pages


def avery_pages(cards: list[Image.Image], back: Image.Image) -> list[Image.Image]:
    """Avery 95328 fronts and backs, a page of each by turns."""
    fronts = avery_95328_pages([flatten(c) for c in cards])
    backs = avery_95328_pages([flatten(back)] * len(cards), backs=True)
    pages = []
    for front, back_page in zip(fronts, backs):
        pages += [front, back_page]
    return pages


def write_pdf(pages: list[Image.Image], path: Path, size=letter) -> None:
    c = canvas.Canvas(str(path), pagesize=size)
    for page in pages:
        c.drawImage(ImageReader(page), 0, 0, width=size[0], height=size[1])
        c.showPage()
    c.save()


PAGE_SIZES = {"grid": letter, "avery": landscape(letter)}
