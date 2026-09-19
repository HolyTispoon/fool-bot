#!/usr/bin/env python3
"""Cut the studio background out of the player portraits.

The art is JPEG paintings on a white background, and a cut-out that
leaves any of it behind shows twice over: as a pale box behind the
player on every dark image the bot draws, and as a faint checkerboard
on a printed card, because the leftover is not flat white but the
JPEG's own 8x8 blocks. See "The player cards" in docs/design/cards.md.

    python3 scripts/recut_player_portraits.py               # dry run
    python3 scripts/recut_player_portraits.py --in-place
    python3 scripts/recut_player_portraits.py --only Synapse --out /tmp/cut

It reports and writes nothing unless asked, because what it overwrites
is tracked art. Running it twice is safe: a portrait with nothing left
to lose comes back byte for byte the same, so the whole folder can go
through it when one new painting is added.

**Look at the result on black.** White is exactly the background that
hides what this fixes.
"""
import argparse
import sys
from collections import deque
from pathlib import Path

from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_IMAGES = PROJECT_ROOT / "d12ball" / "images" / "player_images"

# A pixel is background when it is this light and this close to grey.
# The background's JPEG blocks run 243-252, and 232 clears them with
# room to spare while leaving the lightest thing anybody is actually
# painted in alone -- a goal net at 191, the cream in Bulwark's armour.
# What keeps a white jersey number is not this number but NEUTRAL: the
# background is the one light thing in these paintings with no colour
# in it at all.
SOLID = 232
NEUTRAL = 14
# Down to here, a pixel against a cut edge is part background and is
# faded rather than kept, which is the feather on the new edge.
FEATHER = 200
# A run of background this big is background even when it is walled in
# and nothing from the border can reach it. Below it, a run is kept
# unless it touches the border -- an eye highlight is a small run of
# light pixels too.
MIN_POCKET = 25
# The grey halo a JPEG leaves where the creature met the background:
# colourless, and darker than any blend with white could be. It is
# what reads as a bright outline once the background behind it goes.
HALO = 140
HALO_NEUTRAL = 20
# Under this much creature in a mixed pixel there is no colour left to
# recover, so it goes with the background rather than being unmixed
# into noise.
MIN_COVERAGE = 0.18
# How many passes to allow before giving up on a picture settling.
# Measured over the roster: four is the median and Bulwark's goal net
# is the worst at fifteen, since every hole in it that clears merges
# with the next. The cap is here so a painting nobody has seen yet
# cannot spin.
MAX_ROUNDS = 30


def extremes(pixel: tuple[int, int, int, int]) -> tuple[int, int]:
    red, green, blue, _ = pixel
    return min(red, green, blue), max(red, green, blue)


def recut(
    image: Image.Image,
    rounds: int = MAX_ROUNDS,
) -> tuple[Image.Image, int]:
    """
    The portrait with its background dropped, and how many opaque
    pixels that was.

    Two things are worth knowing before changing any of it. **What is
    dropped is light and colourless**, not merely light: everything in
    these paintings carries a tint and a gradient, including the white
    jersey numbers and the white net a goalkeeper stands in, and that
    is the whole of what tells them from the studio wall behind them.
    **Reaching the edge of the image is not the test**: most of this
    background is walled in -- between a tentacle and an arm, through
    the holes of a net -- and a flood fill from the border never gets
    into any of it.

    **A pass is not a fixpoint, so this repeats until one clears
    nothing.** The edge pass drops a pixel as it scans, which is a
    neighbour the pixels it has already looked at never saw; without
    the repeat, running the tool again would go on finding those a
    handful at a time, and a tool whose output depends on how often it
    has been run is one nobody can check.
    """
    cleared = 0
    for _ in range(rounds):
        image, pass_cleared = recut_once(image)
        cleared += pass_cleared
        if not pass_cleared:
            break
    return image, cleared


def recut_once(image: Image.Image) -> tuple[Image.Image, int]:
    """One pass: drop the background runs, then feather what they left."""
    width, height = image.size
    px = image.load()
    out = image.copy()
    op = out.load()

    def lightness(x: int, y: int) -> int:
        low, high = extremes(px[x, y])
        return low if high - low <= NEUTRAL else -1

    def background(x: int, y: int) -> bool:
        return px[x, y][3] == 0 or lightness(x, y) >= SOLID

    seen = [[False] * width for _ in range(height)]
    removed = [[False] * width for _ in range(height)]
    for start_y in range(height):
        for start_x in range(width):
            if seen[start_y][start_x] or not background(start_x, start_y):
                continue
            queue = deque([(start_x, start_y)])
            seen[start_y][start_x] = True
            run: list[tuple[int, int]] = []
            edged = False
            while queue:
                x, y = queue.popleft()
                run.append((x, y))
                edged = edged or x in (0, width - 1) or y in (0, height - 1)
                for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                    if not (0 <= nx < width and 0 <= ny < height):
                        continue
                    if seen[ny][nx] or not background(nx, ny):
                        continue
                    seen[ny][nx] = True
                    queue.append((nx, ny))
            if edged or len(run) >= MIN_POCKET:
                for x, y in run:
                    removed[y][x] = True
                    op[x, y] = (255, 255, 255, 0)

    # A pixel against a cut edge is part creature and part background.
    # It is faded by how much of it was background and then *unmixed*,
    # the background's white taken back out of what is left: fading
    # alone leaves a white thread along every new edge, which is
    # invisible on the white card it is printed on and a bright
    # outline on the dark images the bot draws.
    for y in range(height):
        for x in range(width):
            # Only a fully opaque pixel is a candidate. Anything
            # already part transparent has been cut before -- by
            # whoever made the file, or by an earlier run of this --
            # and fading it again is how a tool run twice quietly eats
            # a pixel of the creature each time.
            if removed[y][x] or px[x, y][3] != 255:
                continue
            low, high = extremes(px[x, y])
            # A colourless mid-grey against a cut edge is the JPEG's
            # halo, which runs darker than a blend with white ever
            # would; anything with a colour in it is the creature, and
            # is only faded where it is nearly white.
            floor = HALO if high - low <= HALO_NEUTRAL else FEATHER
            if not floor <= low < SOLID:
                continue
            # Diagonals count here, though not in the fill above: a
            # halo pixel touching what went only at a corner is the
            # same halo, and leaving it puts a speck of light on an
            # edge that is otherwise clean.
            if not any(
                0 <= x + dx < width
                and 0 <= y + dy < height
                and removed[y + dy][x + dx]
                for dx in (-1, 0, 1)
                for dy in (-1, 0, 1)
                if dx or dy
            ):
                continue
            coverage = (SOLID - low) / (SOLID - floor)
            if coverage < MIN_COVERAGE:
                op[x, y] = (255, 255, 255, 0)
                removed[y][x] = True
                continue
            unmixed = tuple(
                min(255, max(0, round(
                    (value - 255 * (1 - coverage)) / coverage
                )))
                for value in px[x, y][:3]
            )
            op[x, y] = unmixed + (min(px[x, y][3], round(255 * coverage)),)

    cleared = sum(
        1
        for y in range(height)
        for x in range(width)
        if removed[y][x] and px[x, y][3]
    )
    return out, cleared


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cut the studio background out of the player portraits.",
    )
    parser.add_argument(
        "--images",
        type=Path,
        default=DEFAULT_IMAGES,
        help=f"Folder of portraits to read (default: {DEFAULT_IMAGES}).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="Write the recut portraits here instead of over the originals.",
    )
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Overwrite the originals. Look at the result on black.",
    )
    parser.add_argument(
        "--only",
        action="append",
        help="Recut this portrait by name (Synapse); repeatable.",
    )
    args = parser.parse_args()

    if args.out and args.in_place:
        parser.error("--out and --in-place ask for two different things.")
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)

    paths = sorted(args.images.glob("*.png"))
    if args.only:
        wanted = set(args.only)
        paths = [path for path in paths if path.stem in wanted]
        missing = wanted - {path.stem for path in paths}
        if missing:
            parser.error(f"No such portrait: {', '.join(sorted(missing))}")
    if not paths:
        parser.error(f"No portraits in {args.images}")

    total = 0
    for path in paths:
        with Image.open(path) as source:
            image = source.convert("RGBA")
        cut, cleared = recut(image)
        total += cleared

        destination = None
        if args.out:
            destination = args.out / path.name
        elif args.in_place and cleared:
            destination = path
        if destination is not None:
            cut.save(destination)

        state = "clean" if not cleared else f"{cleared} px"
        print(f"{path.stem:14s} {state}")

    if not (args.out or args.in_place):
        print(
            f"\n{total} px of background found and nothing written. "
            "Pass --in-place to recut the originals, or --out to write "
            "them somewhere to look at first."
        )


if __name__ == "__main__":
    main()
