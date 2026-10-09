#!/usr/bin/env python3
"""
Draw the Codex bot's emoji into codex/images/emoji/.

    python3 scripts/render_codex_emoji.py               # dry run
    python3 scripts/render_codex_emoji.py --out /tmp/codex-emoji
    python3 scripts/render_codex_emoji.py --in-place

`cogs/codex_helpers.py`'s `CodexTokens` draws a card text's `{gold:n}`,
`{exhaust}` and `{target}` with the Codex application's emoji of those
names, and a word where one is not uploaded; this draws them, 128 px on
a transparent ground: `gold` (a gold coin -- the amount is written
beside it), `exhaust` (the cards' ⤵, drawn, white on slate) and `target`
(the cards' own ◎, the ring on red). Each landed hero's face --
`troq_bashar` and `river_montoya`, and from step 10 red's and green's
six -- is cut from its card art in codex/images/cards/ at the square
`FACES` pins. `codex.png`, the medallion,
was cut by hand from the Screentop module's card back and is not this
script's.

It writes nothing unless asked, because what it overwrites is tracked
art. **Uploading is a manual step**: the Codex application's "Emojis"
tab in the Developer Portal, one file per name, the name the file's.
"""

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EMOJI_DIR = PROJECT_ROOT / "codex" / "images" / "emoji"
CARD_DIR = PROJECT_ROOT / "codex" / "images" / "cards"
GLYPH_FONT = PROJECT_ROOT / "d12ball" / "fonts" / "DejaVuSans-Bold.ttf"
SIZE = 128
SUPERSAMPLE = 4

GOLD, GOLD_DARK, GOLD_LIGHT = (232, 178, 46), (150, 98, 18), (255, 226, 130)
SLATE, RED, WHITE = (52, 58, 70), (178, 34, 40), (255, 255, 255)

#: Each hero's face on its 330 by 450 card, as `(left, top, size)` of
#: the square cut into a disc -- pinned after a look at each card, since
#: no one crop finds two faces drawn in two places.
FACES = {
    "troq_bashar": (150, 5, 140),
    "river_montoya": (95, 25, 130),
    # Red and green, landed at step 10.
    "captain_zane": (165, 18, 105),
    "drakk_ramhorn": (95, 35, 90),
    "jaina_stormborne": (75, 30, 100),
    "argagarg_garg": (115, 85, 120),
    "calamandra_moss": (172, 22, 80),
    "master_midori": (105, 45, 115),
}


def canvas() -> tuple[Image.Image, ImageDraw.ImageDraw, int]:
    size = SIZE * SUPERSAMPLE
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    return image, ImageDraw.Draw(image), size


def finish(image: Image.Image) -> Image.Image:
    return image.resize((SIZE, SIZE), Image.LANCZOS)


def disc(draw: ImageDraw.ImageDraw, size: int, fill, outline) -> None:
    margin = size // 32
    draw.ellipse((margin, margin, size - margin, size - margin), fill=outline)
    inner = margin + size // 16
    draw.ellipse((inner, inner, size - inner, size - inner), fill=fill)


def glyph(draw: ImageDraw.ImageDraw, size: int, text: str, fill, scale: float) -> None:
    font = ImageFont.truetype(str(GLYPH_FONT), int(size * scale))
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    draw.text(
        ((size - (right - left)) / 2 - left, (size - (bottom - top)) / 2 - top),
        text, font=font, fill=fill,
    )


def gold() -> Image.Image:
    image, draw, size = canvas()
    disc(draw, size, GOLD, GOLD_DARK)
    ring = size // 5
    draw.ellipse((ring, ring, size - ring, size - ring), outline=GOLD_LIGHT, width=size // 28)
    return finish(image)


def exhaust() -> Image.Image:
    """The cards' ⤵ -- an arrow pointing right, then curving down --
    drawn rather than set, since no bundled face has the glyph."""
    image, draw, size = canvas()
    disc(draw, size, SLATE, WHITE)
    width = size // 11
    radius = size // 5
    left, top = size * 0.25, size * 0.32
    corner = size * 0.62 - radius
    draw.line((left, top, corner, top), fill=WHITE, width=width)
    draw.arc(
        (corner - radius, top, corner + radius, top + 2 * radius),
        start=270, end=360, fill=WHITE, width=width,
    )
    x = corner + radius - width / 2
    draw.line((x, top + radius, x, size * 0.62), fill=WHITE, width=width)
    head = size * 0.13
    tip = size * 0.76
    draw.polygon(
        ((x - head, tip - head * 1.2), (x + head, tip - head * 1.2), (x, tip)),
        fill=WHITE,
    )
    return finish(image)


def target() -> Image.Image:
    image, draw, size = canvas()
    disc(draw, size, RED, WHITE)
    glyph(draw, size, "◎", WHITE, 0.66)
    return finish(image)


def hero(slug: str) -> Image.Image | None:
    """The hero's face, cut from its card's art at `FACES` into a disc."""
    art = CARD_DIR / f"{slug}.jpg"
    if not art.is_file():
        return None
    left, top, size = FACES[slug]
    with Image.open(art) as card:
        face = card.convert("RGBA").crop((left, top, left + size, top + size))
    face = face.resize((SIZE, SIZE), Image.LANCZOS)
    mask = Image.new("L", (SIZE * SUPERSAMPLE,) * 2, 0)
    ImageDraw.Draw(mask).ellipse((0, 0, SIZE * SUPERSAMPLE, SIZE * SUPERSAMPLE), fill=255)
    face.putalpha(mask.resize((SIZE, SIZE), Image.LANCZOS))
    return face


def drawings() -> dict[str, Image.Image | None]:
    return {
        "gold": gold(),
        "exhaust": exhaust(),
        "target": target(),
        **{slug: hero(slug) for slug in FACES},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[1].strip())
    where = parser.add_mutually_exclusive_group()
    where.add_argument("--out", type=Path, help="write the PNGs here")
    where.add_argument("--in-place", action="store_true", help="write them into codex/images/emoji/")
    options = parser.parse_args()
    out = EMOJI_DIR if options.in_place else options.out
    for name, image in drawings().items():
        if image is None:
            print(f"{name}: skipped, its card art is not imported yet", file=sys.stderr)
            continue
        if out is None:
            print(f"{name}: {image.size[0]}x{image.size[1]} (dry run)")
            continue
        out.mkdir(parents=True, exist_ok=True)
        image.save(out / f"{name}.png")
        print(f"wrote {out / f'{name}.png'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
