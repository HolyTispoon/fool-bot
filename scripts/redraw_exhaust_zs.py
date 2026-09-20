#!/usr/bin/env python3
"""Redraw the exhaustion-token triangle's "ZZZ" as three large, amber Zs.

`exhaust.png` is the amber triangle `render.py` draws on every card that is
carrying exhaustion tokens (`load_exhaust_icon`, `draw_exhaustion_badge`).
Until now its center held a small amber pill with the word "ZZZ" stamped
into it in the same near-black ink as the triangle's own edge and face --
readable at the token's full size, but at the 26px the board actually draws
it the pill read as little more than a dashed amber bar.

This keeps the triangle -- the edge, the ring and the face are untouched
pixels, not regenerated geometry, for the same reason
`scripts/recolor_exhaust_token.py` never redraws the shape it recolors: a
reconstruction risks a triangle that doesn't quite match the one it used to
be. Only the content inside the ring changes: the pill and its lettering are
erased back to the face's own ink, and three bold "Z" glyphs are drawn
straight onto the face in the ring's own amber (`SOURCE_AMBER`, sampled off
the art, same as the recolor script uses) -- stepped down in size top-right
to bottom-left, the largest tucked into the triangle's own top-right corner
as closely as it can sit without touching the ring, each one clear of its
neighbours rather than overlapping.

**The first draft overlapped the three Zs and undersold the corner.** It
read as one interlocking zigzag rather than three letters, and its largest
Z sat well short of the top-right corner because it was placed by eye
rather than measured against where the ring actually is. The second draft
placed every glyph by search instead, scoring the biggest Z's spot by how
far into the corner a plain "maximise x, minimise y" reading put it -- and
still landed short, since that score has no way to know a position further
into the corner exists along a slightly different path than straight up
and right. **The author moved it the rest of the way by hand**, and the
other two Zs are built out from that spot rather than the search's: the
smallest as close as it can get to the first draft's own position, the
middle roughly between its neighbours, both while keeping a 10px gap from
every other glyph's actual ink, not just its bounding box, so letters that
lean past their own rectangle (the shear, or a stroke's own diagonal)
still can't touch.

    python3 scripts/redraw_exhaust_zs.py                 # dry run
    python3 scripts/redraw_exhaust_zs.py --in-place
    python3 scripts/redraw_exhaust_zs.py --out /tmp/tokens

It writes nothing unless asked, same as `recolor_exhaust_token.py` and
`render_condition_tokens.py` -- what it would overwrite is tracked art.
**Run `recolor_exhaust_token.py` again afterward**: `exhaust_cyborg.png` is
derived from `exhaust.png` by that script, not by this one, and the two
drift apart the moment only one of them is regenerated.

The erase position, the glyph positions and sizes below are all measured
off this specific piece of art (the pill's own bounding box, the face's
row-by-row width as the triangle narrows) the same way `SOURCE_INK` and
`SOURCE_AMBER` are -- they hold only because nothing about the triangle's
outer geometry has moved. A future redraw of the outer shape needs these
re-measured, not reused.
"""
import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

EMOJI_DIR = PROJECT_ROOT / "d12ball" / "images" / "emoji"
SOURCE = EMOJI_DIR / "exhaust.png"
FONT_PATH = PROJECT_ROOT / "d12ball" / "fonts" / "DejaVuSans-Bold.ttf"

# The source's own two flat colours -- the same ones
# `recolor_exhaust_token.py` samples, since the Zs are drawn in the ring's
# own amber and the erased pill is filled with the face's own ink.
SOURCE_INK = (25, 16, 7, 255)
SOURCE_AMBER = (253, 209, 100, 255)

# A point inside the old pill's amber fill (not on a letter stroke) and one
# inside the face below it, both read off the source art. `thresh` is wide
# enough to sweep in the pill's own antialiased border along with its fill.
PILL_SEED = (400, 300)
PILL_ERASE_BOUNDS = (320, 260, 935, 530)
PILL_ERASE_THRESH = 140
PILL_ERASE_DILATE = 9

# Pillow does not antialias text it draws, so each glyph is rendered at this
# multiple and downsized -- the same trick `render_condition_tokens.py`
# uses for its word.
SUPERSAMPLE = 4

# Three Zs, largest at the top right and smallest at the bottom left. Each
# is (font size, (center x, center y)) at the canvas's own 1254px scale,
# found by search rather than guessed: for the largest, every position that
# clears the face's row-by-row width (the triangle narrowing toward its
# point) without touching the ring, scored by how far into the top-right
# corner it sits; for the other two, the position nearest the previous
# draft's spot (the smallest) or the midpoint between its neighbours (the
# middle) that both clears the ring and keeps a 10px gap from the other
# glyphs' own ink, not just their boxes -- the first draft let them touch.
# The biggest Z's own spot is the author's, not the search's: a plain
# top-right-ness score (maximise x, minimise y) still left it well short of
# the actual corner, short enough that the author moved it by hand and had
# the rest built out from there -- (901, 327), 4px clear of the ring at its
# closest, is that position read back off the art.
ZS = [
    (300, (900, 327)),
    (220, (686, 480)),
    (170, (524, 635)),
]

# A horizontal shear (not a rotation, so the strokes across each Z stay
# straight) that leans the top of every glyph toward the upper right --
# what makes the group of three read as one diagonal running top-right to
# bottom-left rather than three Zs stacked straight down. Lighter than the
# first draft's 0.30: that shear widened each glyph enough to force them
# into touching once they were spaced apart to clear the ring and each
# other.
SHEAR = 0.15


def erase_pill(image: Image.Image) -> Image.Image:
    """Flood-fill the old pill back to the face's own ink.

    The fill is done on a throwaway marker copy so the source's exact pixel
    values are never blended into -- the marked pixels are then dilated a
    few pixels and painted solid ink on the real image, which also takes
    the pill's own thin antialiased border with it (the flood fill alone,
    at a threshold tight enough not to leak into the face, stops just
    short of that border and leaves a faint outline behind).
    """
    left, top, right, bottom = PILL_ERASE_BOUNDS
    marker = image.copy()
    ImageDraw.floodfill(marker, PILL_SEED, (0, 255, 0, 255), thresh=PILL_ERASE_THRESH)
    mpx = marker.load()

    mask = Image.new("L", image.size, 0)
    mask_px = mask.load()
    for y in range(top, bottom):
        for x in range(left, right):
            if mpx[x, y][:3] == (0, 255, 0):
                mask_px[x, y] = 255
    mask = mask.filter(ImageFilter.MaxFilter(PILL_ERASE_DILATE))

    erased = image.copy()
    erased.paste(Image.new("RGBA", image.size, SOURCE_INK), (0, 0), mask)
    return erased


def make_z(size: int) -> Image.Image:
    """One sheared "Z" glyph, drawn big and downsized for antialiasing."""
    big = size * SUPERSAMPLE
    font = ImageFont.truetype(str(FONT_PATH), big)
    measure = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    left, top, right, bottom = measure.textbbox((0, 0), "Z", font=font)
    pad = int(big * 0.3)
    layer = Image.new(
        "RGBA", (right - left + pad * 2, bottom - top + pad * 2), (0, 0, 0, 0)
    )
    ImageDraw.Draw(layer).text(
        (pad - left, pad - top), "Z", font=font, fill=SOURCE_AMBER
    )

    width, height = layer.size
    mid_y = height / 2
    sheared = layer.transform(
        (int(width + SHEAR * height), height),
        Image.AFFINE,
        (1, SHEAR, -SHEAR * mid_y, 0, 1, 0),
        resample=Image.BICUBIC,
    )
    return sheared.resize(
        (sheared.width // SUPERSAMPLE, sheared.height // SUPERSAMPLE), Image.LANCZOS
    )


def redraw(source: Path) -> Image.Image:
    token = erase_pill(Image.open(source).convert("RGBA"))
    for size, (center_x, center_y) in ZS:
        glyph = make_z(size)
        token.alpha_composite(
            glyph,
            (int(center_x - glyph.width / 2), int(center_y - glyph.height / 2)),
        )
    return token


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="overwrite the tracked art in d12ball/images/emoji",
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="write the token to this directory instead",
    )
    args = parser.parse_args()

    if args.in_place and args.out:
        parser.error("--in-place and --out ask for two different things")

    destination = EMOJI_DIR if args.in_place else args.out
    if destination is not None:
        destination.mkdir(parents=True, exist_ok=True)

    token = redraw(SOURCE)
    if destination is None:
        print("exhaust: three diagonal Zs -- not written")
        print("\nDry run. Pass --in-place to overwrite, or --out to look first.")
        return 0

    path = destination / "exhaust.png"
    token.save(path)
    print(f"exhaust: three diagonal Zs -> {path}")
    if args.in_place:
        print(
            "\nWritten. Run scripts/recolor_exhaust_token.py --in-place next -- "
            "exhaust_cyborg.png is derived from this art and is now stale. "
            "Restart the bot (render.py caches icons at first use) and upload "
            "exhaust.png to the Developer Portal's Emojis tab if it is wired up "
            "to its own application emoji."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
