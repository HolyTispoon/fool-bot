#!/usr/bin/env python3
"""Render the maneuver tiles as print-and-play pages.

    python3 scripts/render_maneuver_tiles.py --out d12ball/print/maneuver-tiles
    python3 scripts/render_maneuver_tiles.py --team purple --no-hexagons

Each colour team's two tiles -- tile 1 the basic maneuvers, tile 2 the
gambits -- as letter pages: `<team>-basic-front-sheet.png` is tile 1's
offense and `<team>-basic-back-sheet.png` its defense, printed on the two
sides of one piece of paper (duplex, flipped on the long edge), and the
same for `<team>-gambits-...`. The dodecagon is the tile and goes in the
folder itself; the hexagon, kept as an alternative, goes in `hexagon/`
under it unless `--no-hexagons` leaves it out, as the landing page's kit
does (the author, 2026-10-04). The layout lives in
`d12ball/maneuver_tiles.py`; see "The maneuver tiles" in
docs/design/cards.md.
"""
import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from d12ball.boards import PRINT_DPI  # noqa: E402
from d12ball.game import COLOR_TEAMS, Team  # noqa: E402
from d12ball.maneuver_tiles import DODECAGON, HEXAGON, render_tile_pages  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render the maneuver tiles as duplex pairs of letter pages.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=PROJECT_ROOT / "d12ball" / "print" / "maneuver-tiles",
        help="Directory to write the pages into (default: ./d12ball/print/maneuver-tiles)",
    )
    parser.add_argument(
        "--team",
        choices=[team.value for team in COLOR_TEAMS],
        action="append",
        help="Only this colour team's tiles (repeatable; default: all four).",
    )
    parser.add_argument(
        "--no-hexagons",
        action="store_true",
        help="Leave out the hexagon, the alternative shape (the landing page's kit).",
    )
    args = parser.parse_args()
    teams = [Team(value) for value in args.team] if args.team else list(COLOR_TEAMS)
    shapes = [(DODECAGON, args.out)]
    if not args.no_hexagons:
        shapes.append((HEXAGON, args.out / "hexagon"))
    for sides, folder in shapes:
        folder.mkdir(parents=True, exist_ok=True)
        for team in teams:
            for name, page in render_tile_pages(sides, team).items():
                path = folder / name
                page.save(path, dpi=(PRINT_DPI, PRINT_DPI))
                print(f"wrote {path}")


if __name__ == "__main__":
    main()
