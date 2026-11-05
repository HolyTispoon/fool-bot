"""
Trace map 3.3's areas into `tnp/data/map.json`'s outlines, and measure
which areas touch.

    python3 scripts/trace_tnp_map.py <map3.3-1.png> [--check]

The map is drawn again by code (docs/tnp-bot.md, decision 6), so each
area's outline is data. This reads the map's own picture -- `map3.3-1.png`
in the Drive folder **The New Project** (`Map and territories/`, Drive
id 1gbEjaRHk7H5VRVW2ME6P5EqfmQTMuWio), 2339 x 1654 -- and for each of the
seventeen areas (territories 1 to 15 and the two bases):

1. flood-fills the white space from a seed point inside it, the map's
   black lines being the walls, so each area is the pixels reachable
   from its seed;
2. fills the holes its digits, resource counts and icons leave, so the
   area is its outline and everything inside;
3. traces that outline (Moore-neighbour tracing) and simplifies it
   (Ramer-Douglas-Peucker, `TOLERANCE` pixels) into a polygon.

Two areas are adjacent where their filled shapes, each grown by
`REACH` pixels -- a little more than the thickest line -- overlap: an
outline met across a line. Two pairs meet at a single point, 8 with 10
and 9 with 11, and the author ruled both adjacent (2026-11-05); a point
contact overlaps by a handful of pixels where a shared border overlaps
by hundreds, so both counts are printed.

The adjacency and resources in `map.json` are kept by hand from
docs/tnp-bot.md's table; this script writes only each area's `outline`
and the map's `source`, and refuses (exit 1) when the adjacency it
measures differs from the table's. `--check` measures and compares
without writing.

Needs numpy and Pillow, which the bot already has. Run by hand when the
map changes, never per build. See docs/design/tnp.md, "The data".
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

MAP_JSON = Path(__file__).resolve().parent.parent / "tnp" / "data" / "map.json"

#: A pixel darker than this is a wall. High, because the thin borders
#: are anti-aliased to grey and a gap in one would join two areas.
WALL_BELOW = 200

#: How far, in pixels, each filled area is grown to meet its
#: neighbours across a line. The thick lines are about 6 pixels wide.
REACH = 9

#: The simplified polygon stays within this many pixels of the traced
#: outline.
TOLERANCE = 1.5

#: A point inside each area, in map3.3-1.png's pixels, clear of its
#: digits and icons.
SEEDS = {
    "blue_base": (117, 386),
    "green_base": (2187, 842),
    "1": (1170, 585),
    "2": (655, 526),
    "3": (1637, 1052),
    "4": (1462, 386),
    "5": (889, 1403),
    "6": (1029, 1228),
    "7": (1029, 175),
    "8": (468, 1111),
    "9": (1871, 491),
    "10": (234, 175),
    "11": (1754, 1462),
    "12": (1895, 994),
    "13": (140, 994),
    "14": (351, 748),
    "15": (2105, 678),
}


def walls(image: Image.Image) -> Image.Image:
    """An L image: 0 where the map has a line, 255 where it is open."""
    grey = np.asarray(image.convert("L"))
    return Image.fromarray(np.where(grey < WALL_BELOW, 0, 255).astype(np.uint8)).copy()


def label_areas(open_space: Image.Image) -> dict[str, np.ndarray]:
    """Each area's pixels, flood-filled from its seed."""
    labelled = open_space.copy()
    for index, (name, seed) in enumerate(SEEDS.items(), start=1):
        if labelled.getpixel(seed) != 255:
            raise SystemExit(f"{name}'s seed {seed} is not open space")
        ImageDraw.floodfill(labelled, seed, index)
    labels = np.asarray(labelled)
    return {
        name: labels == index
        for index, name in enumerate(SEEDS, start=1)
    }


def fill_holes(mask: np.ndarray) -> np.ndarray:
    """The area with every enclosed hole filled: everything not reached
    from outside its bounding box."""
    rows = np.flatnonzero(mask.any(axis=1))
    cols = np.flatnonzero(mask.any(axis=0))
    top, bottom, left, right = rows[0], rows[-1], cols[0], cols[-1]
    crop = mask[top:bottom + 1, left:right + 1]
    padded = np.pad(crop, 1)
    # A copy: Pillow's image over a numpy buffer is read-only, and a
    # flood fill on it is silently lost.
    picture = Image.fromarray(np.where(padded, 255, 0).astype(np.uint8)).copy()
    ImageDraw.floodfill(picture, (0, 0), 128)
    filled_crop = np.asarray(picture)[1:-1, 1:-1] != 128
    filled = np.zeros_like(mask)
    filled[top:bottom + 1, left:right + 1] = filled_crop
    return filled


def grow(mask: np.ndarray, reach: int) -> np.ndarray:
    """The mask grown by `reach` pixels in every direction (a square)."""
    grown = mask.copy()
    for _ in range(reach):
        step = grown.copy()
        step[1:, :] |= grown[:-1, :]
        step[:-1, :] |= grown[1:, :]
        step[:, 1:] |= grown[:, :-1]
        step[:, :-1] |= grown[:, 1:]
        grown = step
    return grown


# Moore neighbours, clockwise from west, as (row, column) steps.
_NEIGHBOURS = [(0, -1), (-1, -1), (-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1)]


def trace(mask: np.ndarray) -> list[tuple[int, int]]:
    """The outline of a filled mask as (x, y) pixels, clockwise,
    by Moore-neighbour tracing from its top-left pixel."""
    rows, cols = np.nonzero(mask)
    order = np.lexsort((cols, rows))
    start = (int(rows[order[0]]), int(cols[order[0]]))
    height, width = mask.shape

    def inside(r: int, c: int) -> bool:
        return 0 <= r < height and 0 <= c < width and bool(mask[r, c])

    outline = [start]
    current = start
    backtrack = 0  # entered the start from the west
    while True:
        for turn in range(8):
            direction = (backtrack + turn) % 8
            dr, dc = _NEIGHBOURS[direction]
            nxt = (current[0] + dr, current[1] + dc)
            if inside(*nxt):
                # The next search starts from the neighbour before the
                # one found, seen from the new pixel.
                backtrack = (direction + 5) % 8
                current = nxt
                break
        else:
            break  # a single pixel
        if current == start:
            break
        outline.append(current)
    return [(c, r) for r, c in outline]


def simplify(points: list[tuple[int, int]], tolerance: float) -> list[tuple[int, int]]:
    """Ramer-Douglas-Peucker over a closed outline, split at its two
    farthest-apart points so the ends are corners worth keeping."""
    if len(points) < 4:
        return points
    array = np.asarray(points, dtype=float)
    first = 0
    second = int(np.argmax(((array - array[first]) ** 2).sum(axis=1)))
    half_one = _rdp(array[first:second + 1], tolerance)
    half_two = _rdp(np.vstack([array[second:], array[:1]]), tolerance)
    kept = np.vstack([half_one[:-1], half_two[:-1]])
    return [(int(x), int(y)) for x, y in kept]


def _rdp(points: np.ndarray, tolerance: float) -> np.ndarray:
    keep = np.zeros(len(points), dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        start, end = stack.pop()
        if end - start < 2:
            continue
        a, b = points[start], points[end]
        segment = b - a
        length = np.hypot(*segment)
        middle = points[start + 1:end]
        if length == 0:
            distances = np.hypot(*(middle - a).T)
        else:
            distances = np.abs(
                segment[0] * (middle[:, 1] - a[1]) - segment[1] * (middle[:, 0] - a[0])
            ) / length
        worst = int(np.argmax(distances))
        if distances[worst] > tolerance:
            split = start + 1 + worst
            keep[split] = True
            stack.extend([(start, split), (split, end)])
    return points[keep]


def measure(path: Path):
    image = Image.open(path)
    areas = {name: fill_holes(mask) for name, mask in label_areas(walls(image)).items()}
    grown = {name: grow(mask, REACH) for name, mask in areas.items()}
    touching: dict[frozenset, int] = {}
    names = list(areas)
    for i, one in enumerate(names):
        for other in names[i + 1:]:
            overlap = int((grown[one] & grown[other]).sum())
            if overlap:
                touching[frozenset((one, other))] = overlap
    outlines = {name: simplify(trace(mask), TOLERANCE) for name, mask in areas.items()}
    sizes = {name: int(mask.sum()) for name, mask in areas.items()}
    return image.size, outlines, touching, sizes


def table_pairs(data: dict) -> set[frozenset]:
    return {
        frozenset((area["id"], neighbour))
        for area in data["areas"]
        for neighbour in area["adjacent"]
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("image", type=Path, help="map3.3-1.png")
    parser.add_argument("--check", action="store_true", help="measure and compare, write nothing")
    options = parser.parse_args()

    size, outlines, touching, sizes = measure(options.image)
    data = json.loads(MAP_JSON.read_text(encoding="utf-8"))

    print("Area sizes (pixels, holes filled):")
    for name, count in sizes.items():
        print(f"  {name:>10}: {count:>8}  outline {len(outlines[name])} points")
    print(f"Touching pairs, grown by {REACH} px (overlap in pixels):")
    for pair, overlap in sorted(touching.items(), key=lambda item: item[1]):
        print(f"  {' with '.join(sorted(pair)):>24}: {overlap}")

    table = table_pairs(data)
    measured = set(touching)
    missing = table - measured
    extra = measured - table
    for pair in sorted(missing, key=sorted):
        print(f"In the table, not measured: {' with '.join(sorted(pair))}")
    for pair in sorted(extra, key=sorted):
        print(f"Measured, not in the table: {' with '.join(sorted(pair))}")
    if missing or extra:
        print("The measured adjacency differs from the table; nothing written.")
        return 1
    print("The measured adjacency matches the table.")

    if options.check:
        return 0
    data["source"] = {
        "file": options.image.name,
        "drive_id": "1gbEjaRHk7H5VRVW2ME6P5EqfmQTMuWio",
        "size": list(size),
        "traced_by": "scripts/trace_tnp_map.py",
    }
    for area in data["areas"]:
        area["outline"] = [list(point) for point in outlines[area["id"]]]
    MAP_JSON.write_text(_dump(data), encoding="utf-8")
    print(f"Wrote {MAP_JSON}")
    return 0


def _dump(data: dict) -> str:
    """JSON with each outline on one line, so a diff of the file reads
    by area rather than by point."""
    marker = "@@OUTLINE:{}@@"
    staged = json.loads(json.dumps(data))
    flat = {}
    for area in staged["areas"]:
        key = marker.format(area["id"])
        flat[key] = json.dumps(area["outline"], separators=(",", ":"))
        area["outline"] = key
    text = json.dumps(staged, indent=2, ensure_ascii=False)
    for key, value in flat.items():
        text = text.replace(json.dumps(key), value)
    return text + "\n"


if __name__ == "__main__":
    sys.exit(main())
