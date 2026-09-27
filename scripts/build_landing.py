#!/usr/bin/env python3
"""Build the two landing pages, d12ball.com and propheticfoolsgames.com.

    python3 scripts/build_landing.py
    python3 scripts/build_landing.py --only d12ball
    python3 scripts/build_landing.py --out /tmp/site
    python3 scripts/build_landing.py --capture-board

Each site is written to `<out>/<site>/` (default `landing/dist/`), a
directory of static files a browser opens as it is:

    python3 -m http.server -d landing/dist/d12ball 8000

Everything on the pages that the game can answer is read from it --
the title, the strapline and the chips from `d12ball/box_art.py`, the
colours from `render.TEAM_COLORS` and the night palette, the pictures
from the renderers the box and the bot use -- so an import or a
rules change reaches the pages by running this again. The one picture
that is not rendered on every build is the web app's board, which is a
committed capture: `--capture-board` takes it again (it needs Chrome),
after a web app change to the board. See docs/design/landing-pages.md.
"""
import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from landing.build import DIST_DIR, SITES, main as build_all  # noqa: E402
from landing.capture import capture_board  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the d12ball.com and propheticfoolsgames.com pages.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DIST_DIR,
        help="Directory each site is written under (default: landing/dist).",
    )
    parser.add_argument(
        "--only",
        choices=SITES,
        action="append",
        help="Build just this site; repeat for both.",
    )
    parser.add_argument(
        "--capture-board",
        action="store_true",
        help=(
            "Take the web app's board again into landing/d12ball/board.png "
            "before building (needs Chrome; LANDING_CHROME names one)."
        ),
    )
    arguments = parser.parse_args()
    if arguments.capture_board:
        path = capture_board()
        print(f"captured the board into {path.relative_to(PROJECT_ROOT)}; commit it")
    build_all(sites=arguments.only or SITES, out_root=arguments.out)


if __name__ == "__main__":
    main()
