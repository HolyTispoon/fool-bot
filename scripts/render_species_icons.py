#!/usr/bin/env python3
"""Draw the four species icons.

One silhouette a species -- a flame for the Fire Demons' Volatile, a
cell for the Cyborgs' Lithium Powered, an inward spiral for the
Telekinetics' Mind Pull, and a wobbling bubbled blob for the Oozes'
Slimey.

    python3 scripts/render_species_icons.py                 # dry run
    python3 scripts/render_species_icons.py --in-place
    python3 scripts/render_species_icons.py --out /tmp/icons
    python3 scripts/render_species_icons.py --out /tmp/icons --sheet

**Two files a species**: `<species>.png` is the ink silhouette every
render reads, and `<species>_color.png` is the same shape painted in
that species' own colour -- the paired colour team's hex out of
`TEAM_COLORS`, so it is the colour the board already draws that
species' meeples in and there is still exactly one hex per colour in
the codebase.

**Nothing in the bot reads the coloured copy**, and it is not a second
source of truth: it is written from the same shape in the same pass,
through the same `tint_silhouette` the renderer tints with, so the two
cannot come to disagree. It is there for the places a file has to
arrive already coloured -- a Developer Portal emoji upload, a document,
a slide -- where the bot's own drawing tints at the moment it draws.
Anything drawing an icon *in code* asks `render.species_icon` for the
colour it needs; see "The species icons" in CLAUDE.md.

Read the Oozes' on something dark. Its hex is Slime green, which is the
one of the four that all but disappears on white -- the same fact
`high_contrast_ink` exists for, and the reason the icon on a card is
never this file.

It writes nothing unless asked, because what it overwrites is tracked
art -- the same reason `render_condition_tokens.py` and
`recut_player_portraits.py` are dry runs by default.

**They are drawn as one flat silhouette, not as coloured art**, and
that is what lets one file serve every place an icon appears. A species
icon sits on three backgrounds -- a team-coloured header band on the
printed player card, the same band on the species reference card, and
the white face of the card the bot draws on the board -- so no single
colour is right for all three. `d12ball/render.py`'s
`load_species_icon` tints a copy at draw time, keeping the alpha and
replacing the ink, which is only possible because there is one ink to
replace.

The shapes are built out of cubic segments rather than pasted from
files for the reason the condition tokens are: art nobody has to own is
art that cannot go missing, and a silhouette regenerates at whatever
canvas the next use wants. Every measurement is a fraction of the
canvas, so changing CANVAS moves nothing.
"""
import argparse
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from d12ball.render import (  # noqa: E402
    SPECIES_ICON_DIR,
    TEAM_COLORS,
    tint_silhouette,
)
from d12ball.species_cards import SPECIES_TEAM  # noqa: E402

# Drawn once at a size larger than anywhere it is shown: the printed
# card wants it at around 100px and the bot's own card at 26, and a
# coach may open either full size.
CANVAS = 512

# Pillow does not antialias the shapes these are made of, so they are
# drawn large and resized down -- the same trick `cards.Pen` and the
# condition tokens use, and for the same reason.
SUPERSAMPLE = 4

# The ink every icon is drawn in. It is replaced wherever one is drawn
# (see the module docstring), so this is the colour of the file and of
# nothing else; black is what makes a stray untinted paste obvious
# rather than invisible.
INK = (0, 0, 0, 255)

# What the coloured copy of an icon is named. Underscored like every
# other bundled image, and a suffix rather than a directory of its own
# so the pair sits together in a listing -- there is no case where you
# want one of these without knowing the other exists.
COLOR_SUFFIX = "_color"

Point = tuple[float, float]


def cubic(p0: Point, p1: Point, p2: Point, p3: Point, steps: int = 24):
    """A cubic bezier as points, without its own start."""
    for step in range(1, steps + 1):
        t = step / steps
        u = 1 - t
        yield (
            u * u * u * p0[0]
            + 3 * u * u * t * p1[0]
            + 3 * u * t * t * p2[0]
            + t * t * t * p3[0],
            u * u * u * p0[1]
            + 3 * u * u * t * p1[1]
            + 3 * u * t * t * p2[1]
            + t * t * t * p3[1],
        )


def outline(segments: list[tuple[Point, Point, Point]], start: Point):
    """
    A closed shape from a start point and a run of (c1, c2, end)
    segments, each carrying on from where the last one stopped. Written
    this way because every one of these shapes is a single continuous
    edge, and listing only the handles keeps the shape readable as a
    path rather than as a wall of coordinates.
    """
    points = [start]
    here = start
    for c1, c2, end in segments:
        points.extend(cubic(here, c1, c2, end))
        here = end
    return points


def draw_flame(pen: ImageDraw.ImageDraw, size: float) -> None:
    """
    Volatile. Two tongues rather than one -- the main tip and the
    smaller lobe off its left, with a real valley between them. A
    single tapered tongue is a teardrop, and the Ooze's is the other
    rounded shape in this set.
    """
    shape = outline(
        [
            ((0.50, 0.13), (0.45, 0.21), (0.42, 0.31)),
            ((0.40, 0.24), (0.35, 0.19), (0.29, 0.13)),
            ((0.25, 0.26), (0.16, 0.36), (0.13, 0.52)),
            ((0.10, 0.64), (0.11, 0.73), (0.20, 0.81)),
            ((0.28, 0.91), (0.37, 0.98), (0.50, 0.98)),
            ((0.68, 0.98), (0.85, 0.89), (0.86, 0.68)),
            ((0.87, 0.42), (0.72, 0.22), (0.54, 0.02)),
        ],
        (0.54, 0.02),
    )
    pen.polygon([(x * size, y * size) for x, y in shape], fill=INK)


def draw_cell(pen: ImageDraw.ImageDraw, size: float) -> None:
    """
    Lithium Powered. A cell with its terminal, and the bolt cut out of
    it rather than laid over it -- a hole reads at 26px where a second
    colour cannot, since the icon is one flat ink by design.
    """
    pen.rounded_rectangle(
        (0.36 * size, 0.03 * size, 0.64 * size, 0.16 * size),
        radius=0.04 * size,
        fill=INK,
    )
    pen.rounded_rectangle(
        (0.17 * size, 0.13 * size, 0.83 * size, 0.97 * size),
        radius=0.12 * size,
        fill=INK,
    )
    bolt = [
        (0.58, 0.24),
        (0.31, 0.61),
        (0.46, 0.61),
        (0.41, 0.88),
        (0.69, 0.50),
        (0.53, 0.50),
    ]
    pen.polygon(
        [(x * size, y * size) for x, y in bolt], fill=(0, 0, 0, 0)
    )


def draw_spiral(pen: ImageDraw.ImageDraw, size: float) -> None:
    """
    Mind Pull. An inward spiral, tapering as it goes: the taper is what
    gives it a direction, and the direction is the whole of what the
    ability does -- the ball comes to the Telekinetic.
    """
    turns = 2.15
    outer, inner = 0.46, 0.015
    thick, thin = 0.135, 0.045
    steps = 260

    points = []
    for step in range(steps + 1):
        t = step / steps
        angle = -math.pi / 2 + turns * 2 * math.pi * t
        radius = outer + (inner - outer) * t
        points.append(
            (
                (0.5 + radius * math.cos(angle)) * size,
                (0.5 + radius * math.sin(angle)) * size,
            )
        )

    # Segment by segment, each with its own width, because a stroke of
    # one width cannot taper. The dot at every joint is what keeps the
    # run reading as a single line rather than as a chain of bars.
    for index in range(steps):
        t = index / steps
        width = (thick + (thin - thick) * t) * size
        pen.line(
            [points[index], points[index + 1]], fill=INK, width=round(width)
        )
        half = width / 2
        x, y = points[index]
        pen.ellipse((x - half, y - half, x + half, y + half), fill=INK)


# The Ooze's outline, as a radius that wobbles with the angle: two
# harmonics, which is enough to read as organic and few enough that no
# lobe pinches off into a spike. The bubbles are cut out of it rather
# than laid over it -- a hole reads at 26px where a second colour
# cannot, since the icon is one flat ink by design.
BLOB_WOBBLE = ((3, 0.055, 0.9), (5, 0.035, 2.2))
BLOB_RADIUS = 0.40
BLOB_BUBBLES = ((0.38, 0.40, 0.085), (0.60, 0.58, 0.062))


def draw_blob(pen: ImageDraw.ImageDraw, size: float) -> None:
    """
    Slimey. A wobbling blob with bubbles in it.

    A centred, compact shape, which is what puts it in the same set as
    the other three rather than beside them. The versions that read
    most obviously as *slime* -- a ledge with drips hanging off it, a
    ball with a highlight -- were the two that lost: the first is
    top-heavy where every other icon here is centred, and the second's
    highlight reads as an eye by the time it is 26px across, which
    makes the icon a creature instead of a substance.
    """
    points = []
    for step in range(360):
        angle = math.radians(step)
        radius = BLOB_RADIUS + sum(
            amplitude * math.sin(harmonic * angle + phase)
            for harmonic, amplitude, phase in BLOB_WOBBLE
        )
        points.append(
            (
                (0.5 + radius * math.cos(angle)) * size,
                (0.5 + radius * math.sin(angle)) * size,
            )
        )
    pen.polygon(points, fill=INK)

    for cx, cy, radius in BLOB_BUBBLES:
        pen.ellipse(
            (
                (cx - radius) * size,
                (cy - radius) * size,
                (cx + radius) * size,
                (cy + radius) * size,
            ),
            fill=(0, 0, 0, 0),
        )


ICONS = {
    "fire_demon": ("Volatile", draw_flame),
    "cyborg": ("Lithium Powered", draw_cell),
    "telekinetic": ("Mind Pull", draw_spiral),
    "ooze": ("Slimey", draw_blob),
}


def render_icon(draw_shape) -> Image.Image:
    size = CANVAS * SUPERSAMPLE
    icon = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw_shape(ImageDraw.Draw(icon), size)
    return icon.resize((CANVAS, CANVAS), Image.LANCZOS)


def contact_sheet(rows: list[list[Image.Image]]) -> Image.Image:
    """
    The icons on a ground dark enough to read both rows on.

    Dark rather than light because the ink row is black and the Oozes'
    coloured one is Slime green: there is no single ground both rows
    read on, and this is the one that fails on the row you are least
    likely to be checking.
    """
    pad = CANVAS // 8
    width = max(len(row) for row in rows) * (CANVAS + pad) + pad
    height = len(rows) * (CANVAS + pad) + pad
    sheet = Image.new("RGBA", (width, height), (32, 34, 38, 255))
    for row_index, row in enumerate(rows):
        for index, icon in enumerate(row):
            sheet.alpha_composite(
                icon,
                (
                    pad + index * (CANVAS + pad),
                    pad + row_index * (CANVAS + pad),
                ),
            )
    return sheet


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="overwrite the tracked art in d12ball/images/species",
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="write the icons to this directory instead",
    )
    parser.add_argument(
        "--sheet",
        action="store_true",
        help="also write species-icons.png, the four side by side",
    )
    args = parser.parse_args()

    if args.in_place and args.out:
        parser.error("--in-place and --out ask for two different things")

    destination = SPECIES_ICON_DIR if args.in_place else args.out
    if destination is not None:
        destination.mkdir(parents=True, exist_ok=True)

    ink_row = []
    color_row = []
    for species, (keyword, draw_shape) in ICONS.items():
        icon = render_icon(draw_shape)
        color = TEAM_COLORS[SPECIES_TEAM[species]]
        colored = tint_silhouette(icon, color)
        ink_row.append(icon)
        color_row.append(colored)

        if destination is None:
            print(
                f"{species}: {keyword} {color} ({icon.width}px) "
                "-- not written"
            )
            continue

        path = destination / f"{species}.png"
        color_path = destination / f"{species}{COLOR_SUFFIX}.png"
        icon.save(path)
        colored.save(color_path)
        print(f"{species}: {keyword} -> {path}")
        print(f"{species}: {keyword} {color} -> {color_path}")

    if destination is not None and args.sheet:
        path = destination / "species-icons.png"
        contact_sheet([ink_row, color_row]).save(path)
        print(f"sheet -> {path}")

    if destination is None:
        print("\nDry run. Pass --in-place to overwrite, or --out to look first.")
    elif args.in_place:
        print("\nWritten. Restart the bot -- render.py caches icons at first use.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
