#!/usr/bin/env python3
"""Draw the six role emoji -- the `[FB]` after a player's name, as art.

One PNG a role, in `d12ball/images/emoji/`, named the way
`ROLE_EMOJI_NAMES` in `cogs/d12ball_helpers.py` asks for them
(`role_fullback.png`, ...). They are uploaded to the application's
emoji by hand, the same way the team and condition emoji are, and once
they are there every *message* that names a player carries the badge
in place of the bracketed initials -- see "Naming a player" in
CLAUDE.md for which places that is, and which stay text.

    python3 scripts/render_role_emoji.py                 # dry run
    python3 scripts/render_role_emoji.py --out /tmp/roles --sheet
    python3 scripts/render_role_emoji.py --in-place

It writes nothing unless asked, because what it overwrites is tracked
art -- the same reason `render_condition_tokens.py` is a dry run by
default. **Uploading is still a manual step**: the Developer Portal's
"Emojis" tab, one file per name. Nothing in the bot reads these files,
so a change here reaches Discord only when the new files are uploaded.

The badge is a white rounded square with an ink edge and the two
initials in ink. White inside a dark outline is the team emoji's own
recipe -- it reads on Discord's dark theme and its light one alike --
and a *square* is what tells a role badge from a team ring at 22px,
which is the size a coach mostly meets it at: "🟠 Hellguard [FB]" is a
ring and then a square, not two rings. The initials are the board's
own (`ROLE_INITIALS`), so the two letters here are the two letters on
the meeple and the printed card.
"""
import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from d12ball.formatting import ROLE_INITIALS  # noqa: E402

EMOJI_DIR = PROJECT_ROOT / "d12ball" / "images" / "emoji"
FONT_PATH = PROJECT_ROOT / "d12ball" / "fonts" / "DejaVuSans-Bold.ttf"

# The team emoji's own canvas. Discord scales an emoji to 128px on
# upload and shows it at 22px inline, so nothing is gained past this,
# and one size across the set keeps the two kinds of badge the same
# height beside each other.
CANVAS = 256

# Pillow does not antialias a rounded rectangle or a glyph edge well
# at this size, so the badge is drawn large and resized down -- the
# same trick `cards.Pen` and the token script use.
SUPERSAMPLE = 4

# Every measurement is a fraction of the canvas. Two letters have to
# fit where the team ring holds one, so the margin and the edge are
# both thinner than the ring's: at 22px every pixel the outline takes
# is a pixel off the initials, and the first draft (a 24-unit edge, the
# letters at 74% of the face) came out legible at 256 and a smudge
# inline. The edge is still the thickest line that survives the
# downscale as a line rather than a shadow.
MARGIN = 6 / 256
EDGE_WIDTH = 16 / 256
CORNER_RADIUS = 52 / 256

# The initials fill this much of the face's width, measured on the
# widest pair so all six are set at one size -- a set where FB is set
# larger than WG reads as six badges, not one badge six times.
TEXT_WIDTH = 0.88

FACE_COLOR = (255, 255, 255, 255)
# `high_contrast_ink`'s dark, the colour the board draws the initials
# in on a card.
INK = (17, 17, 17, 255)


def fitted_font(size: int) -> ImageFont.FreeTypeFont:
    """One font size for the set: the largest at which the widest pair
    of initials fits the text box."""
    box = size * (1 - 2 * (MARGIN + EDGE_WIDTH)) * TEXT_WIDTH
    measure = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    font_size = size // 2
    while font_size > 8:
        font = ImageFont.truetype(str(FONT_PATH), font_size)
        widest = max(
            measure.textlength(initials, font=font)
            for initials in ROLE_INITIALS.values()
        )
        if widest <= box:
            return font
        font_size -= 2
    return ImageFont.truetype(str(FONT_PATH), font_size)


def render_badge(initials: str, font: ImageFont.FreeTypeFont) -> Image.Image:
    size = CANVAS * SUPERSAMPLE
    badge = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    pen = ImageDraw.Draw(badge)

    margin = size * MARGIN
    radius = size * CORNER_RADIUS
    edge = size * EDGE_WIDTH

    # Outside in: the ink edge is the whole badge filled, and the face
    # is a smaller square drawn over it.
    pen.rounded_rectangle(
        (margin, margin, size - margin, size - margin),
        radius=radius,
        fill=INK,
    )
    face_inset = margin + edge
    pen.rounded_rectangle(
        (face_inset, face_inset, size - face_inset, size - face_inset),
        radius=max(radius - edge, 0),
        fill=FACE_COLOR,
    )

    # Centred on the cap height rather than on the glyph box, so a pair
    # with no descender sits where a coach's eye expects it.
    left, top, right, bottom = pen.textbbox((0, 0), initials, font=font)
    pen.text(
        ((size - (right - left)) / 2 - left, (size - (bottom - top)) / 2 - top),
        initials,
        font=font,
        fill=INK,
    )

    return badge.resize((CANVAS, CANVAS), Image.LANCZOS)


def render_all() -> dict[str, Image.Image]:
    font = fitted_font(CANVAS * SUPERSAMPLE)
    return {
        f"role_{role}": render_badge(initials, font)
        for role, initials in ROLE_INITIALS.items()
    }


def contact_sheet(badges: dict[str, Image.Image]) -> Image.Image:
    """The six side by side on Discord's dark ground, at the size they
    are drawn and at the size a coach reads them."""
    gap = 24
    small = 22
    width = gap + len(badges) * (CANVAS + gap)
    height = gap + CANVAS + gap + small + gap
    sheet = Image.new("RGBA", (width, height), (49, 51, 56, 255))
    x = gap
    for badge in badges.values():
        sheet.alpha_composite(badge, (x, gap))
        sheet.alpha_composite(
            badge.resize((small, small), Image.LANCZOS),
            (x + (CANVAS - small) // 2, gap + CANVAS + gap),
        )
        x += CANVAS + gap
    return sheet


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
        help="write the emoji to this directory instead",
    )
    parser.add_argument(
        "--sheet",
        action="store_true",
        help="also write role_emoji_sheet.png, the six on a dark ground",
    )
    args = parser.parse_args()

    if args.in_place and args.out:
        parser.error("--in-place and --out ask for two different things")

    destination = EMOJI_DIR if args.in_place else args.out
    if destination is not None:
        destination.mkdir(parents=True, exist_ok=True)

    badges = render_all()
    for name, badge in badges.items():
        if destination is None:
            print(f"{name} ({badge.width}px) -- not written")
            continue
        path = destination / f"{name}.png"
        badge.save(path)
        print(f"{name} -> {path}")

    if args.sheet and destination is not None:
        path = destination / "role_emoji_sheet.png"
        contact_sheet(badges).save(path)
        print(f"sheet -> {path}")

    if destination is None:
        print("\nDry run. Pass --in-place to overwrite, or --out to look first.")
    elif args.in_place:
        print(
            "\nWritten. Upload all six to the Developer Portal's Emojis "
            "tab under these names; nothing in the bot reads the files."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
