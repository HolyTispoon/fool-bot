#!/usr/bin/env python3
"""Recolor the exhaustion-token triangle teal, for a Cyborg's own tokens.

`exhaust.png` is the amber "ZZZ" triangle `render.py` draws on every
card that is carrying exhaustion tokens (`load_exhaust_icon`,
`draw_exhaustion_badge`), human and Cyborg alike. The Cyborg's own
*conditions* already get their own art -- Drained and Damaged, teal and
amber, standing in for Exhausted and Injured (see "Lithium Powered" in
docs/design/species-abilities.md) -- but until now the token counter
itself stayed amber for everyone, which put a teal Drained badge next
to an amber tally of the very tokens that badge is counting. This is
the same swap one level down: a Cyborg's own token count in the same
teal `TOKENS["drained"]` in `render_condition_tokens.py` already uses.

    python3 scripts/recolor_exhaust_token.py                 # dry run
    python3 scripts/recolor_exhaust_token.py --in-place
    python3 scripts/recolor_exhaust_token.py --out /tmp/tokens

It writes nothing unless asked, for the same reason
`render_condition_tokens.py` doesn't: what it would overwrite is
tracked art.

**This is a recolour, not a redraw**, unlike the four condition tokens.
`exhaust.png` has no generator in `scripts/` -- it predates
`render_condition_tokens.py` and nothing here needs its geometry to
change, only its one accent colour -- so reconstructing the triangle
from scratch would risk a shape that doesn't quite match the art it is
supposed to sit beside on the same card. Instead every pixel is read as
a point on the line between the source's two flat colours (a near-black
edge/text ink and the amber fill/ring, sampled off the art itself
rather than assumed as pure `#000`/`#fff`) and re-expressed as the same
point on the line between that same ink and the target teal -- which
carries every anti-aliased edge across unchanged, since those pixels
are just partway blends of the same two colours to begin with.

**No numpy.** This project's `requirements.txt` doesn't carry it and no
other script does either, so the recolour is a plain-Python pass over
`getdata()` rather than a vectorised one -- slower, but this runs by
hand and not in the bot's own path.
"""
import argparse
import sys
from pathlib import Path

from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

EMOJI_DIR = PROJECT_ROOT / "d12ball" / "images" / "emoji"
SOURCE = EMOJI_DIR / "exhaust.png"

# The source's own two flat colours, read off its most common opaque
# pixels rather than assumed -- it is a warm near-black, not `#000`.
SOURCE_INK = (25, 16, 7)
SOURCE_AMBER = (253, 209, 100)

# The same teal `render_condition_tokens.py` draws Drained in --
# TOKENS["drained"] there -- so a Cyborg's token count and their
# Drained badge are one colour, not two shades of "teal".
TARGET_TEAL = (0, 158, 158)


def recolor(
    source: Path,
    ink: tuple[int, int, int],
    from_color: tuple[int, int, int],
    to_color: tuple[int, int, int],
) -> Image.Image:
    """
    Re-express every pixel's position on the ink-to-`from_color` line as
    the same position on the ink-to-`to_color` line. Alpha is untouched,
    so a fully or partially transparent pixel stays exactly as
    transparent.
    """
    image = Image.open(source).convert("RGBA")

    axis = tuple(f - i for f, i in zip(from_color, ink))
    axis_length_sq = sum(component * component for component in axis)
    target_axis = tuple(t - i for t, i in zip(to_color, ink))

    # A lookup table over every colour actually used beats recomputing
    # the projection per pixel -- most of a token's 1.5M pixels repeat
    # one of a handful of colours (the flat fill and a run of
    # antialiased edges), and `Image.getcolors` is exact here since a
    # bicolour token has far fewer than the default 256-colour cap.
    palette = image.getcolors(maxcolors=1_000_000) or []
    remap: dict[tuple[int, int, int, int], tuple[int, int, int, int]] = {}
    for _, pixel in palette:
        r, g, b, a = pixel
        offset = (r - ink[0], g - ink[1], b - ink[2])
        dot = sum(o * c for o, c in zip(offset, axis))
        position = 0.0 if axis_length_sq == 0 else dot / axis_length_sq
        position = max(0.0, min(1.0, position))
        new_rgb = tuple(
            round(i + position * t) for i, t in zip(ink, target_axis)
        )
        remap[pixel] = (*new_rgb, a)

    pixels = image.load()
    width, height = image.size
    for y in range(height):
        for x in range(width):
            pixels[x, y] = remap[pixels[x, y]]
    return image


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

    token = recolor(SOURCE, SOURCE_INK, SOURCE_AMBER, TARGET_TEAL)
    if destination is None:
        print(f"exhaust_cyborg: teal {TARGET_TEAL} -- not written")
        print("\nDry run. Pass --in-place to overwrite, or --out to look first.")
        return 0

    path = destination / "exhaust_cyborg.png"
    token.save(path)
    print(f"exhaust_cyborg: teal {TARGET_TEAL} -> {path}")
    if args.in_place:
        print(
            "\nWritten. Restart the bot (render.py caches the icons at first "
            "use) and upload it to the Developer Portal's Emojis tab if it "
            "is wired up to its own application emoji."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
