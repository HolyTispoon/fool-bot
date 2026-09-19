#!/usr/bin/env python3
"""Draw the four species team emoji -- the ring beside a coach's name
for Fire Demons, Cyborgs, Telekinetics and Oozes -- in two sets.

    python3 scripts/render_team_emoji.py                 # dry run
    python3 scripts/render_team_emoji.py --out /tmp/teams --sheet
    python3 scripts/render_team_emoji.py --in-place

**The plain set is the bot's.** `team_fire_demons.png` and its three
siblings carry the species silhouette alone, and those are the names
`TEAM_EMOJI_NAMES` in `cogs/d12ball_helpers.py` looks up -- see "Team
colors" in docs/design/teams-and-players.md for the ring and "The species icons" for the
silhouette. **The lettered set is an alternate**, written beside them
as `team_fire_demons_letter.png` and so on: the same ring with that
species' initial merged into the silhouette. Nothing in the bot reads
those four; they are uploaded under their own names so the application
holds both cuts and either can be switched to by changing one value in
`TEAM_EMOJI_NAMES`.

It writes nothing unless asked, because what it overwrites is tracked
art -- the same reason `render_role_emoji.py` is a dry run by default.
**Uploading is still a manual step**: the Developer Portal's "Emojis"
tab, one file per name. Nothing in the bot reads these files, so a
change here reaches Discord only when the new file is uploaded.

The four color teams' emoji (a letter in a team-coloured ring) are
untouched -- this script only ever writes the four species names. A
species team's ring used to carry a letter picked to stay distinct
from all eight teams' initials (F/C/K/Z); it now carries that species'
own silhouette, the same shape `render_species_icons.py` draws and the
player and species cards already carry, so a coach reads one icon for
"this species" wherever it appears. The ring's own geometry is
measured off the existing color-team PNGs rather than invented, so a
species emoji sits in an identical ring to `team_orange.png`.
"""
import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from d12ball.game import Team  # noqa: E402
from d12ball.render import (  # noqa: E402
    TEAM_COLORS,
    load_species_icon,
    species_icon,
    tint_silhouette,
)

EMOJI_DIR = PROJECT_ROOT / "d12ball" / "images" / "emoji"
FONT_PATH = PROJECT_ROOT / "d12ball" / "fonts" / "DejaVuSans-Bold.ttf"

# Which species silhouette (see `d12ball/images/species/`) goes in
# which team's ring. The four color teams' rings are left alone.
SPECIES_BY_TEAM = {
    Team.FIRE_DEMONS: "fire_demon",
    Team.CYBORGS: "cyborg",
    Team.TELEKINETICS: "telekinetic",
    Team.OOZES: "ooze",
}

# The existing ring emoji (team_orange.png and its seven siblings) are
# 256px, with a 12px margin to the outer edge and a 20px ring, measured
# off the shipped files rather than guessed -- a species emoji has to
# sit in the identical ring or it reads as a different badge shape
# next to the other seven.
CANVAS = 256
MARGIN = 12 / 256
EDGE_WIDTH = 20 / 256

# Pillow does not antialias a circle well at this size, so the ring is
# drawn large and resized down -- the same trick `render_role_emoji.py`
# and `cards.Pen` use.
SUPERSAMPLE = 4

FACE_COLOR = (255, 255, 255, 255)

# --- the plain set ---------------------------------------------------
# The icon fills this much of the face circle's own diameter. A
# letter's bounding box (see the color teams' own rings) runs to about
# 55% of the face by width; a silhouette reads as a smudge at that
# scale where a bold sans letter does not, so this is bigger --
# measured against the four shapes to sit comfortably inside the face
# with the same breathing room the letters keep from the ring. It is
# applied to the icon's whole square, padding included, which is why
# it is smaller than the lettered set's.
ICON_FACE_FRAC = 0.62

# --- the lettered set ------------------------------------------------
# The badge is composed at this resolution and scaled into the ring
# afterwards, so every placement below is a fraction of it and changing
# it moves nothing.
BADGE_WORK_SIZE = 900

# The silhouette is cropped to its own ink first -- the art carries a
# wide transparent margin, and centring the padded square rather than
# the shape leaves the badge small and visibly off-centre in the ring.
# This is what is kept around the ink afterwards.
CROP_PAD_FRAC = 0.04

# With the padding gone the badge can fill much more of the face than
# the plain set's icon does.
BADGE_FACE_FRAC = 0.88


class LetterPlacement:
    """Where one species' initial sits on its own silhouette.

    **Every one of these is a judgement call made by looking at the
    render, not a rule a function could derive**, which is why they are
    written down rather than searched for at draw time. Two of the four
    sit at the ink's own mass centroid, which is what a broad solid
    shape wants; the other two have to dodge the hole their art is
    built around, and a centroid puts the letter straight through it.

    `position` and `size` are fractions of `BADGE_WORK_SIZE`.
    `position` of None means the ink's mass centroid.
    """

    def __init__(self, letter, size, position=None, rotation=0):
        self.letter = letter
        self.size = size
        self.position = position
        self.rotation = rotation


LETTER_PLACEMENTS = {
    # A flame is solid through the middle, so the centroid is right and
    # the letter can be big.
    Team.FIRE_DEMONS: LetterPlacement("F", 378 / 900),
    # The cell's own bolt is cut *out* of it, and the cutout is where
    # the middle of the icon is -- so the C is set inside the bolt's
    # widest lobe, found by walking every position in the cutout for
    # the one that admits the largest letter.
    Team.CYBORGS: LetterPlacement("C", 210 / 900, (419 / 900, 474 / 900)),
    # A spiral is mostly the gaps between its arms. The K goes in the
    # channel immediately right of the centre -- between where the
    # inner stroke ends and the next line out -- which is the widest
    # pocket the coil has anywhere near the middle.
    Team.TELEKINETICS: LetterPlacement("K", 165 / 900, (482 / 900, 455 / 900)),
    # The blob's two bubbles are turned into the Z's own gaps rather
    # than left to fall across its strokes; 20 degrees is what lines
    # them up. The letter then takes the centroid like the flame's.
    Team.OOZES: LetterPlacement("Z", 378 / 900, rotation=20),
}

# Each letter is grown past the size that clears the ink entirely until
# it just bites into it. A letter held clear reads as though it is
# hovering over a picture; a letter that overlaps reads as part of one.
# About a fortieth of the glyph is what does that without costing its
# shape -- the C and the K were sized by eye against this, and the F
# and the Z are broad enough that their centroid placement lands there
# on its own.


def tight_crop(image: Image.Image, pad_frac: float) -> Image.Image:
    """`image` cropped to a square around its own ink, plus a pad."""
    bounds = image.getbbox()
    if bounds is None:
        return image
    x0, y0, x1, y1 = bounds
    side = max(x1 - x0, y1 - y0)
    half = side // 2 + int(side * pad_frac)
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    return image.crop((cx - half, cy - half, cx + half, cy + half))


def ink_centroid(image: Image.Image) -> tuple[float, float]:
    """The alpha-weighted centre of the ink -- the point a letter wants
    when the shape is solid enough to take one, which is not the centre
    of the image and not the centre of its bounding box either."""
    alpha = image.getchannel("A")
    width, height = image.size
    total = x_sum = y_sum = 0
    for y in range(height):
        row = alpha.crop((0, y, width, y + 1)).tobytes()
        for x, value in enumerate(row):
            if value > 40:
                total += value
                x_sum += x * value
                y_sum += y * value
    if not total:
        return width / 2, height / 2
    return x_sum / total, y_sum / total


def render_ring(team: Team) -> Image.Image:
    """The coloured ring and its white face, with nothing on it yet."""
    size = CANVAS * SUPERSAMPLE
    ring = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    pen = ImageDraw.Draw(ring)

    margin = size * MARGIN
    edge = size * EDGE_WIDTH

    pen.ellipse(
        (margin, margin, size - margin, size - margin),
        fill=TEAM_COLORS[team],
    )
    face_inset = margin + edge
    pen.ellipse(
        (face_inset, face_inset, size - face_inset, size - face_inset),
        fill=FACE_COLOR,
    )
    return ring.resize((CANVAS, CANVAS), Image.LANCZOS)


def face_diameter() -> float:
    return CANVAS - 2 * (CANVAS * MARGIN + CANVAS * EDGE_WIDTH)


def centre_on_face(ring: Image.Image, badge: Image.Image, frac: float) -> Image.Image:
    """Scale `badge` to `frac` of the face's diameter and centre it."""
    target = round(face_diameter() * frac)
    scale = target / max(badge.size)
    badge = badge.resize(
        (max(1, round(badge.width * scale)), max(1, round(badge.height * scale))),
        Image.LANCZOS,
    )
    ring.alpha_composite(
        badge,
        ((CANVAS - badge.width) // 2, (CANVAS - badge.height) // 2),
    )
    return ring


def plain_emoji(team: Team) -> Image.Image:
    """The species silhouette alone, in the ring's own colour."""
    ring = render_ring(team)
    icon = species_icon(
        SPECIES_BY_TEAM[team],
        TEAM_COLORS[team],
        round(face_diameter() * ICON_FACE_FRAC),
    )
    if icon is None:
        return ring
    ring.alpha_composite(
        icon,
        ((CANVAS - icon.width) // 2, (CANVAS - icon.height) // 2),
    )
    return ring


def lettered_emoji(team: Team) -> Image.Image:
    """The silhouette with the species' initial merged into it."""
    ring = render_ring(team)
    ink = load_species_icon(SPECIES_BY_TEAM[team])
    if ink is None:
        return ring

    placement = LETTER_PLACEMENTS[team]
    shape = tight_crop(ink, 0.15)
    if placement.rotation:
        shape = shape.rotate(
            placement.rotation, resample=Image.BICUBIC, expand=True
        )
    shape = tight_crop(shape, CROP_PAD_FRAC).resize(
        (BADGE_WORK_SIZE, BADGE_WORK_SIZE), Image.LANCZOS
    )

    badge = tint_silhouette(shape, "#000000")
    if placement.position is None:
        cx, cy = ink_centroid(badge)
    else:
        cx = placement.position[0] * BADGE_WORK_SIZE
        cy = placement.position[1] * BADGE_WORK_SIZE

    font = ImageFont.truetype(
        str(FONT_PATH), round(placement.size * BADGE_WORK_SIZE)
    )
    pen = ImageDraw.Draw(badge)
    left, top, right, bottom = pen.textbbox((0, 0), placement.letter, font=font)
    pen.text(
        (cx - (right + left) / 2, cy - (bottom + top) / 2),
        placement.letter,
        font=font,
        fill=TEAM_COLORS[team],
    )

    # Cropped to the merged shape's own bounds -- the letter's and the
    # silhouette's together -- so what gets centred in the ring is the
    # badge rather than the square it was drawn on.
    return centre_on_face(ring, badge.crop(badge.getbbox()), BADGE_FACE_FRAC)


def render_all() -> dict[str, Image.Image]:
    emoji = {}
    for team in SPECIES_BY_TEAM:
        emoji[f"team_{team.value}"] = plain_emoji(team)
    for team in SPECIES_BY_TEAM:
        emoji[f"team_{team.value}_letter"] = lettered_emoji(team)
    return emoji


def contact_sheet(emoji: dict[str, Image.Image]) -> Image.Image:
    """Both sets on Discord's dark ground, at the size they are drawn
    and at the size a coach reads them."""
    gap = 24
    small = 22
    columns = len(emoji) // 2
    row_height = gap + CANVAS + gap + small
    width = gap + columns * (CANVAS + gap)
    sheet = Image.new(
        "RGBA", (width, gap + 2 * row_height), (49, 51, 56, 255)
    )
    for index, badge in enumerate(emoji.values()):
        column, row = index % columns, index // columns
        x = gap + column * (CANVAS + gap)
        y = gap + row * row_height
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
        help="also write team_species_emoji_sheet.png, both sets on a "
        "dark ground",
    )
    args = parser.parse_args()

    if args.in_place and args.out:
        parser.error("--in-place and --out ask for two different things")

    destination = EMOJI_DIR if args.in_place else args.out
    if destination is not None:
        destination.mkdir(parents=True, exist_ok=True)

    emoji = render_all()
    for name, badge in emoji.items():
        if destination is None:
            print(f"{name} ({badge.width}px) -- not written")
            continue
        path = destination / f"{name}.png"
        badge.save(path)
        print(f"{name} -> {path}")

    if args.sheet and destination is not None:
        path = destination / "team_species_emoji_sheet.png"
        contact_sheet(emoji).save(path)
        print(f"sheet -> {path}")

    if destination is None:
        print("\nDry run. Pass --in-place to overwrite, or --out to look first.")
    elif args.in_place:
        print(
            "\nWritten. Upload all eight to the Developer Portal's Emojis "
            "tab under these names; the bot reads the four plain ones, "
            "through TEAM_EMOJI_NAMES."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
