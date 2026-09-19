#!/usr/bin/env python3
"""Draw the Injured, Exhausted, Drained and Damaged condition tokens.

These four PNGs are read in two places and have to be one file each:
`render.py` loads them as the badges it draws on a player's card
(`load_injured_icon` / `load_exhausted_icon` / `load_drained_icon` /
`load_damaged_icon`), and the same art is uploaded to the application's
emoji so a line of text and the badge on the board show a coach the
same icon -- see "Logging and the #logs channel" for how application
emoji are looked up, and `cogs/d12ball_helpers.py` for the names they
must be uploaded under.

    python3 scripts/render_condition_tokens.py                 # dry run
    python3 scripts/render_condition_tokens.py --in-place
    python3 scripts/render_condition_tokens.py --out /tmp/tokens

It writes nothing unless asked, because what it overwrites is tracked
art -- the same reason `recut_player_portraits.py` is a dry run by
default. **Uploading is still a manual step**: the Developer Portal's
"Emojis" tab, under the names in `CONDITION_EMOJI_NAMES`. Re-running
this changes what the board draws immediately, and what Discord shows
not at all until the new files are uploaded, so do both together or the
two disagree.

The layout is measured off the art this replaces, so a token stays the
thing coaches already recognise at 26px: a black face inside a thin
coloured ring inside a thicker black edge, a sunburst behind the word,
and the word itself condensed to the full width of the face. What
changed is the colour, which is the whole point of the rewrite --
**injury is red and exhaustion is blue**, where it used to be the other
way round.

**Drained and Damaged are a Cyborg's own words for Exhausted and
Injured** (see "Lithium Powered" in docs/living-rules.md) -- the same
mechanic under a different name, so they get their own art rather than
a recolour of the human tokens standing in for a different word. Both
are teal/amber rather than the human pair's blue/red, since teal is the
Cyborgs' own team colour (`TEAM_COLORS[Team.TEAL]`, see "Team colors" in
docs/design/teams-and-players.md) and amber reads as a mechanical
warning light beside it -- deliberately brighter than a literal
`TEAM_COLORS` teal, which the author found too muted a fill at 26px
once it was next to the sunburst rays it shares its own colour with.
"""
import argparse
import math
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

EMOJI_DIR = PROJECT_ROOT / "d12ball" / "images" / "emoji"
FONT_PATH = PROJECT_ROOT / "d12ball" / "fonts" / "DejaVuSans-Bold.ttf"

# The size the art this replaces was drawn at. Discord takes anything
# and `render.py` resizes to 26px, but a token is also the one image a
# coach may open full size, so it is drawn once at the larger size
# rather than at either of the sizes it is shown.
CANVAS = 1254

# Pillow does not antialias the shapes a token is made of, so it is
# drawn large and resized down -- the same trick `cards.Pen` uses, and
# for the same reason.
SUPERSAMPLE = 4

# Every measurement below is a fraction of the canvas, read off the art
# this replaces (a scan across the badge gives 85px of margin, 41px of
# black edge and 23px of coloured ring at 1254). Keeping them
# proportional is what lets the canvas change without the design moving.
MARGIN = 85 / 1254
EDGE_WIDTH = 41 / 1254
RING_WIDTH = 23 / 1254
CORNER_RADIUS = 0.10

FACE_COLOR = (10, 10, 10, 255)
EDGE_COLOR = (10, 10, 10, 255)

# The sunburst behind the word. The rays are wedges from the middle of
# the badge, so they are drawn long and clipped to the face.
RAY_COUNT = 28
RAY_HALF_ANGLE = 1.4  # degrees

# The word is drawn at whatever size fits and then squashed to this box,
# which is what gives it the condensed face the bundled DejaVu does not
# have. Both words fill the same box, so INJURED and EXHAUSTED read as
# one set rather than as two sizes.
TEXT_WIDTH = 0.72
TEXT_HEIGHT = 0.19

# The word sits on the sunburst and is the same colour as it, so it
# carries a face-coloured halo -- without it a letter crossing a ray
# disappears into it, which is the one thing this art cannot afford at
# 26px.
TEXT_HALO = 0.07  # of the font size

# The swap. These were the other way round until 2026-08-15; red for
# injury and blue for exhaustion is the pairing coaches expect, and the
# board and the emoji both follow from here.
TOKENS = {
    "injured": ("INJURED", (255, 52, 0, 255)),
    "exhausted": ("EXHAUSTED", (0, 164, 255, 255)),
    # A Cyborg's own pair -- Damaged reads with Injured's own urgency
    # and Drained with Exhausted's, so each keeps its human
    # counterpart's role in the pairing and picks up a Cyborg-flavoured
    # hue instead of red/blue.
    "damaged": ("DAMAGED", (255, 176, 0, 255)),
    "drained": ("DRAINED", (0, 158, 158, 255)),
}


def draw_sunburst(size: int, color: tuple[int, int, int, int]) -> Image.Image:
    """The rays, on their own layer so the face can clip them."""
    rays = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    pen = ImageDraw.Draw(rays)
    center = size / 2
    reach = size  # past every corner, so a ray is cut by the face alone
    for index in range(RAY_COUNT):
        middle = index * (360 / RAY_COUNT)
        start = math.radians(middle - RAY_HALF_ANGLE)
        end = math.radians(middle + RAY_HALF_ANGLE)
        pen.polygon(
            [
                (center, center),
                (center + reach * math.cos(start), center + reach * math.sin(start)),
                (center + reach * math.cos(end), center + reach * math.sin(end)),
            ],
            fill=color,
        )
    return rays


def draw_word(
    word: str, size: int, color: tuple[int, int, int, int]
) -> Image.Image:
    """The word, condensed to the text box.

    Drawn at a size that is only ever too big and then resized to the
    box, so a longer word comes out narrower rather than smaller: it is
    the squash that has to do the work, or EXHAUSTED would set two
    thirds the height of INJURED and the pair would not read as a set.
    """
    font_size = size // 4
    halo = int(font_size * TEXT_HALO)
    font = ImageFont.truetype(str(FONT_PATH), font_size)
    measure = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    left, top, right, bottom = measure.textbbox(
        (0, 0), word, font=font, stroke_width=halo
    )
    layer = Image.new("RGBA", (right - left, bottom - top), (0, 0, 0, 0))
    ImageDraw.Draw(layer).text(
        (-left, -top),
        word,
        font=font,
        fill=color,
        stroke_width=halo,
        stroke_fill=FACE_COLOR,
    )
    return layer.resize(
        (int(size * TEXT_WIDTH), int(size * TEXT_HEIGHT)), Image.LANCZOS
    )


def render_token(word: str, accent: tuple[int, int, int, int]) -> Image.Image:
    size = CANVAS * SUPERSAMPLE
    token = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    pen = ImageDraw.Draw(token)

    margin = size * MARGIN
    radius = size * CORNER_RADIUS
    edge = size * EDGE_WIDTH
    ring = size * RING_WIDTH

    # Outside in: the black edge is the whole badge filled, the ring is
    # an outline drawn inside it, and the face is what the ring encloses.
    pen.rounded_rectangle(
        (margin, margin, size - margin, size - margin),
        radius=radius,
        fill=EDGE_COLOR,
    )
    ring_inset = margin + edge
    pen.rounded_rectangle(
        (ring_inset, ring_inset, size - ring_inset, size - ring_inset),
        radius=max(radius - edge, 0),
        fill=accent,
    )
    face_inset = ring_inset + ring
    pen.rounded_rectangle(
        (face_inset, face_inset, size - face_inset, size - face_inset),
        radius=max(radius - edge - ring, 0),
        fill=FACE_COLOR,
    )

    # The face is also the sunburst's mask, so a ray stops exactly where
    # the ring begins rather than needing its own geometry.
    face_mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(face_mask).rounded_rectangle(
        (face_inset, face_inset, size - face_inset, size - face_inset),
        radius=max(radius - edge - ring, 0),
        fill=255,
    )
    # Masked into the rays' own alpha rather than pasted through the
    # mask: a paste copies the layer's transparency as well, which
    # takes the black face away everywhere a ray is not.
    rays = draw_sunburst(size, accent)
    rays.putalpha(ImageChops.multiply(rays.getchannel("A"), face_mask))
    token.alpha_composite(rays)

    word_layer = draw_word(word, size, accent)
    token.alpha_composite(
        word_layer,
        ((size - word_layer.width) // 2, (size - word_layer.height) // 2),
    )

    return token.resize((CANVAS, CANVAS), Image.LANCZOS)


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
        help="write the tokens to this directory instead",
    )
    args = parser.parse_args()

    if args.in_place and args.out:
        parser.error("--in-place and --out ask for two different things")

    destination = EMOJI_DIR if args.in_place else args.out
    if destination is not None:
        destination.mkdir(parents=True, exist_ok=True)

    for name, (word, accent) in TOKENS.items():
        token = render_token(word, accent)
        if destination is None:
            print(f"{name}: {word} {accent[:3]} ({token.width}px) -- not written")
            continue
        path = destination / f"{name}.png"
        token.save(path)
        print(f"{name}: {word} {accent[:3]} -> {path}")

    if destination is None:
        print("\nDry run. Pass --in-place to overwrite, or --out to look first.")
    elif args.in_place:
        print(
            "\nWritten. Restart the bot (render.py caches the icons at first "
            "use) and upload both to the Developer Portal's Emojis tab."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
