#!/usr/bin/env python3
"""Build The New Project's print-and-play kit, the basic game.

    python3 scripts/render_tnp_kit.py
    python3 scripts/render_tnp_kit.py --out /some/folder
    python3 scripts/render_tnp_kit.py --zip

Writes into `tnp/print/` (gitignored) unless `--out` names somewhere
else: the map, the battle mat, the track sheet, each seat's screen,
player board, deployment board and unit counters, the tokens, the
rules as a PDF and a README -- docs/design/tnp-print-kit.md. Look at
what it draws; nothing tests how it looks.
"""
import argparse
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from tnpkit.kit import DEFAULT_OUT, write_kit  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="the folder to write the kit into")
    parser.add_argument("--zip", action="store_true", help="also zip the folder, beside it")
    args = parser.parse_args()
    print(f"Building the kit into {args.out} ...", flush=True)
    write_kit(args.out, report=lambda path: print(path, flush=True))
    if args.zip:
        archive = shutil.make_archive(str(args.out), "zip", root_dir=args.out.parent, base_dir=args.out.name)
        print(archive)


if __name__ == "__main__":
    main()
