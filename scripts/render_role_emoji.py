#!/usr/bin/env python3
"""Draw the six role emoji -- the `[FB]` after a player's name, as art.

One PNG a role, in `d12ball/images/emoji/`, named the way
`ROLE_EMOJI_NAMES` in `cogs/d12ball_helpers.py` asks for them
(`role_fullback.png`, ...). They are uploaded to the application's
emoji by hand, the same way the team and condition emoji are, and once
they are there every *message* that names a player carries the badge
in place of the bracketed initials -- see "Naming a player" in
docs/design/naming-and-wording.md for which places that is, and which stay text.

    python3 scripts/render_role_emoji.py                 # dry run
    python3 scripts/render_role_emoji.py --out /tmp/roles --sheet
    python3 scripts/render_role_emoji.py --in-place

It writes nothing unless asked, because what it overwrites is tracked
art -- the same reason `render_condition_tokens.py` is a dry run by
default. **Uploading is still a manual step**: the Developer Portal's
"Emojis" tab, one file per name -- nothing in the *message* path reads
these files, so a change here reaches Discord only when the new files
are uploaded. `d12ball/role_cards.py` is the one exception: it opens
the plain badge straight off disk to draw the print reference card, so
a change here reaches that card by re-running
`scripts/render_role_cards.py`, with no upload needed.

The badge is a white rounded square with an ink edge and the two
initials in ink. White inside a dark outline is the team emoji's own
recipe -- it reads on Discord's dark theme and its light one alike --
and a *square* is what tells a role badge from a team ring at 22px,
which is the size a coach mostly meets it at: "🟠 Hellguard [FB]" is a
ring and then a square, not two rings. The initials are the board's
own (`ROLE_INITIALS`), so the two letters here are the two letters on
the meeple and the printed card.

**There are five cuts of each role, not one**: the plain badge above
and one in each of the four team colours (`role_fullback_orange`,
...), which is 30 files. A colour cut is the same badge with the
*edge* in that team's hex and nothing else changed -- the face stays
white and the initials stay ink.

That is the whole of the design, and the alternatives were drawn and
looked at before it was picked. Filling the *face* with the colour and
setting the initials in `high_contrast_ink` -- the board's own recipe
for a meeple token -- reads strongest at full size and worst where it
matters: at 22px two letters knocked out of orange or slime green are
a smudge, where black on white is still two letters (the author,
2026-09-17). Putting the colour on the initials as well as the edge,
which is what the *team* emoji does with its one big glyph, loses the
same way for the same reason. So the colour is on the edge alone: the
one part of the badge carrying no information, and the part a coach
reads as a colour rather than as a shape.

A colour cut serves **both** teams that share the hex -- Orange and
Fire Demons are one file, the way `TEAM_COLORS` is one hex (see "Team
colors" in docs/design/teams-and-players.md). There are four files a role and not eight.
"""
import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from d12ball.formatting import ROLE_INITIALS  # noqa: E402
from d12ball.game import COLOR_TEAMS  # noqa: E402
from d12ball.render import TEAM_COLORS  # noqa: E402

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
# in on a card. It is the plain cut's edge as well as every cut's
# initials -- see the module docstring for why the colour cuts move
# the edge and leave the letters alone.
INK = (17, 17, 17, 255)

# The four hexes, read off `TEAM_COLORS` rather than written here --
# there is exactly one hex per colour anywhere in the code, and a
# species team shares its colour team's, which is why these are keyed
# by the colour team alone. See "Team colors" in docs/design/teams-and-players.md.
EDGE_COLORS = {team.value: TEAM_COLORS[team] for team in COLOR_TEAMS}


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


def render_badge(
    initials: str,
    font: ImageFont.FreeTypeFont,
    edge_color=INK,
) -> Image.Image:
    """
    One badge. `edge_color` is the only thing a colour cut changes --
    the face and the initials are the same on all five.
    """
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
        fill=edge_color,
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
    """
    Every file the set holds, keyed by the name it is uploaded under:
    the plain badge a role, then one per team colour. The names are
    what `ROLE_EMOJI_NAMES` and `ROLE_TEAM_EMOJI_NAMES` in
    `cogs/d12ball_helpers.py` look up, and
    `D12BallRoleEmojiTests` fails if the two spellings part company.
    """
    font = fitted_font(CANVAS * SUPERSAMPLE)
    badges: dict[str, Image.Image] = {}
    for role, initials in ROLE_INITIALS.items():
        badges[f"role_{role}"] = render_badge(initials, font)
        for colour, edge in EDGE_COLORS.items():
            badges[f"role_{role}_{colour}"] = render_badge(
                initials, font, edge,
            )
    return badges


def contact_sheet(
    badges: dict[str, Image.Image],
    background=(49, 51, 56, 255),
) -> Image.Image:
    """
    The whole set as a grid -- a role a column, a cut a row -- at the
    size it is drawn and at the 22px a coach reads it.

    The small row is the one worth looking at, and is the reason the
    sheet exists: everything here is legible at 256px, including the
    treatments that were rejected. Drawn on Discord's dark ground by
    default, and `--sheet-light` writes the same grid on its light
    one -- a badge has to hold both, which is what the white face is
    for and what a coloured *face* would have given up.
    """
    gap = 24
    small = 22
    cut_height = CANVAS + gap + small + gap
    cuts = ["plain", *EDGE_COLORS]
    width = gap + len(ROLE_INITIALS) * (CANVAS + gap)
    height = gap + len(cuts) * cut_height
    sheet = Image.new("RGBA", (width, height), background)
    for row, cut in enumerate(cuts):
        y = gap + row * cut_height
        for column, role in enumerate(ROLE_INITIALS):
            name = f"role_{role}" if cut == "plain" else f"role_{role}_{cut}"
            badge = badges[name]
            x = gap + column * (CANVAS + gap)
            sheet.alpha_composite(badge, (x, y))
            sheet.alpha_composite(
                badge.resize((small, small), Image.LANCZOS),
                (x + (CANVAS - small) // 2, y + CANVAS + gap),
            )
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
        help="also write role_emoji_sheet.png, the set on a dark ground",
    )
    parser.add_argument(
        "--sheet-light",
        action="store_true",
        help="also write role_emoji_sheet_light.png, the same on a light one",
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

    if args.sheet_light and destination is not None:
        path = destination / "role_emoji_sheet_light.png"
        contact_sheet(badges, (255, 255, 255, 255)).save(path)
        print(f"sheet -> {path}")

    if destination is None:
        print("\nDry run. Pass --in-place to overwrite, or --out to look first.")
    elif args.in_place:
        print(
            f"\nWritten. Upload all {len(badges)} to the Developer "
            "Portal's Emojis tab under these names; nothing in the bot "
            "reads the files."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
