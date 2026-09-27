"""
The rulebooks' covers as pictures, for the d12ball page's rulebooks card.

The words are the books' own (`rulebooks.BOOKS[...].cover`) and the layout
is `rulebooks.cover_layout`, the one the PDF's first page is drawn from;
this is the second drawing of it, in Pillow, so the card shows the page a
download opens on. See docs/design/landing-pages.md, "The downloads".
"""
from __future__ import annotations

from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

from d12ball.box_art import d12_art
from d12ball.rulebooks import COVER_FACES, FONT_DIR, PAPERS, Cover, cover_layout


@lru_cache(maxsize=None)
def cover_font(face: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_DIR / COVER_FACES[face]), size)


def render_cover(cover: Cover, width: int, paper: str = "letter") -> Image.Image:
    """`cover` drawn `width` pixels wide, in the paper's proportions."""
    page_width, page_height = PAPERS[paper]
    height = round(width * page_height / page_width)
    layout = cover_layout(
        cover, width, height,
        lambda text, face, size: cover_font(face, round(size)).getlength(text),
    )
    image = Image.new("RGB", (width, height), layout.ground)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width, round(layout.band)), fill=layout.gold)
    x0, x1, y, weight = layout.rule
    draw.line((x0, y, x1, y), fill=layout.gold, width=max(1, round(weight)))
    for text in layout.texts:
        draw.text(
            (text.x, text.baseline), text.text, fill=text.colour,
            font=cover_font(text.face, round(text.size)), anchor="ls",
        )
    left, top, size = layout.die
    die = d12_art(round(size))
    image.paste(die, (round(left), round(top)), die if die.mode == "RGBA" else None)
    return image
