#!/usr/bin/env python3
"""Draw the four species team emoji -- the ring beside a coach's name
for Fire Demons, Cyborgs, Telekinetics and Oozes.

One PNG a team, in `d12ball/images/emoji/`, named the way
`TEAM_EMOJI_NAMES` in `cogs/d12ball_helpers.py` asks for them
(`team_fire_demons.png`, ...). They are uploaded to the application's
emoji by hand, the same way the role and condition emoji are -- see
"Team colors" in CLAUDE.md for the ring itself and "The species icons"
for the silhouette this pastes into it.

    python3 scripts/render_team_emoji.py                 # dry run
    python3 scripts/render_team_emoji.py --out /tmp/teams --sheet
    python3 scripts/render_team_emoji.py --in-place

It writes nothing unless asked, because what it overwrites is tracked
art -- the same reason `render_role_emoji.py` is a dry run by default.
**Uploading is still a manual step**: the Developer Portal's "Emojis"
tab, one file per name. Nothing in the bot reads these files, so a
change here reaches Discord only when the new file is uploaded.

The four color teams' emoji (a letter in a team-coloured ring) are
untouched -- this script only ever writes the four species names. A
species team's ring used to carry a letter picked to stay distinct
from all eight teams' initials (F/C/K/Z); it now carries that species'
own silhouette instead, tinted to the ring's own colour, which is the
same shape `render_species_icons.py` draws and the player and species
cards already carry -- a coach reads one icon for "this species"
wherever it appears, rather than a letter here and a shape everywhere
else. The ring's own geometry (margin, edge width, face size) is
measured off the existing color-team PNGs rather than invented, so a
species emoji sits in an identical ring to `team_orange.png` and the
rest.
"""
import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from d12ball.game import Team  # noqa: E402
from d12ball.render import TEAM_COLORS, species_icon  # noqa: E402

EMOJI_DIR = PROJECT_ROOT / "d12ball" / "images" / "emoji"

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

# The icon fills this much of the face circle's own diameter. A
# letter's bounding box (see the color teams' own rings) runs to about
# 55% of the face by width; a silhouette reads as a smudge at that
# scale where a bold sans letter does not, so this is bigger --
# measured against the four shapes to sit comfortably inside the face
# with the same breathing room the letters keep from the ring.
ICON_SCALE = 0.62


def render_ring(team: Team) -> Image.Image:
    size = CANVAS * SUPERSAMPLE
    ring = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    pen = ImageDraw.Draw(ring)

    margin = size * MARGIN
    edge = size * EDGE_WIDTH
    color = TEAM_COLORS[team]

    pen.ellipse((margin, margin, size - margin, size - margin), fill=color)
    face_inset = margin + edge
    pen.ellipse(
        (face_inset, face_inset, size - face_inset, size - face_inset),
        fill=FACE_COLOR,
    )

    ring = ring.resize((CANVAS, CANVAS), Image.LANCZOS)

    face_diameter = CANVAS - 2 * (CANVAS * MARGIN + CANVAS * EDGE_WIDTH)
    icon_size = round(face_diameter * ICON_SCALE)
    icon = species_icon(SPECIES_BY_TEAM[team], color, icon_size)
    if icon is not None:
        offset = ((CANVAS - icon.width) // 2, (CANVAS - icon.height) // 2)
        ring.alpha_composite(icon, offset)

    return ring


def render_all() -> dict[str, Image.Image]:
    return {
        f"team_{team.value}": render_ring(team)
        for team in SPECIES_BY_TEAM
    }


def contact_sheet(rings: dict[str, Image.Image]) -> Image.Image:
    """The four side by side on Discord's dark ground, at the size
    they are drawn and at the size a coach reads them."""
    gap = 24
    small = 22
    width = gap + len(rings) * (CANVAS + gap)
    height = gap + CANVAS + gap + small + gap
    sheet = Image.new("RGBA", (width, height), (49, 51, 56, 255))
    x = gap
    for ring in rings.values():
        sheet.alpha_composite(ring, (x, gap))
        sheet.alpha_composite(
            ring.resize((small, small), Image.LANCZOS),
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
        help="also write team_species_emoji_sheet.png, the four on a "
        "dark ground",
    )
    args = parser.parse_args()

    if args.in_place and args.out:
        parser.error("--in-place and --out ask for two different things")

    destination = EMOJI_DIR if args.in_place else args.out
    if destination is not None:
        destination.mkdir(parents=True, exist_ok=True)

    rings = render_all()
    for name, ring in rings.items():
        if destination is None:
            print(f"{name} ({ring.width}px) -- not written")
            continue
        path = destination / f"{name}.png"
        ring.save(path)
        print(f"{name} -> {path}")

    if args.sheet and destination is not None:
        path = destination / "team_species_emoji_sheet.png"
        contact_sheet(rings).save(path)
        print(f"sheet -> {path}")

    if destination is None:
        print("\nDry run. Pass --in-place to overwrite, or --out to look first.")
    elif args.in_place:
        print(
            "\nWritten. Re-upload all four to the Developer Portal's "
            "Emojis tab under these names; nothing in the bot reads "
            "the files."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
