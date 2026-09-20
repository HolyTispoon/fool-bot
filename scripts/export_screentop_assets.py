#!/usr/bin/env python3
"""Export every image the screentop.gg module of D12 Ball is built from.

    python3 scripts/export_screentop_assets.py
    python3 scripts/export_screentop_assets.py --out /tmp/screentop --zip
    python3 scripts/export_screentop_assets.py --max-side 2048

The game on screentop.gg is built in its own editor and is not checked
in; what the repo owns is every picture on its table. Updating the
module is running this and uploading what changed -- the cards, the
boards, the meeples, the dice and the tokens all come out of the same
modules the bot and the print-and-play kit draw from, cut the way a
virtual tabletop wants them rather than a printer (gapless sheets,
backs in reading order, no bleed, nothing over `--max-side` pixels).
`d12ball/screentop.py` is that cut and the reasoning; this is only the
command line round it, plus a README the folder can leave the repo
with. See "The screentop.gg module" in docs/design/screentop.md.

`manifest.json` in the output lists every file with its kind and size
and, for a sheet, the grid to cut it on and which card is in which
cell. Read the grid off the manifest rather than counting it by eye.

`screentop/` is generated output and gitignored, like `print-and-play/`.
"""
import argparse
import shutil
import sys
import zipfile
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from d12ball.screentop import MAX_SIDE, build_assets, write_kit  # noqa: E402

README_TEMPLATE = """\
# D12 Ball -- screentop.gg assets

Generated {generated} by `scripts/export_screentop_assets.py`, from
the same data and rules the Discord bot plays from. Every image here is
capped at {max_side}px a side. `manifest.json` lists every file with its
size and, for a sheet, the grid it is cut on -- read the numbers off it.

## What's in the folder

- **maneuver-cards/** -- a sheet a side (`offense-sheet.png`,
  `defense-sheet.png`: a coach's whole hand, the three basic maneuvers
  over the three gambits), the one shared `back.png`, and every card on
  its own.
- **player-cards/** -- a fronts sheet and a backs sheet per team, in
  the same order: cell *n* of the backs is the advanced side of cell *n*
  of the fronts. Plus every card on its own.
- **species-cards/** -- the three double-sided species-ability
  reference cards, a fronts sheet and a backs sheet.
- **boards/** -- the field board at every size the rules define, the
  jumbotron (clock, score, token supplies), and a team board panel per
  team plus an uncoloured one. One panel is one coach's board.
- **tokens/meeples/** -- a token a player a team, the species icon over
  the role initials, for a game playing species abilities;
  **tokens/meeples-basic/** the same with the initials alone. A sheet a
  team beside the single files.
- **tokens/conditions/** -- the exhaustion token and the Exhausted,
  Injured, Drained and Damaged markers; **tokens/coin-*.png** the two
  faces of the coin the toss is flipped with.
- **dice/** -- a d12 per team colour and the ball's white d12, twelve
  faces each, singly and as a sheet in face order.

## Cutting a sheet

Every sheet is gapless: divide it into the manifest's `columns` x
`rows` and each cell is one card, edge to edge. `count` is how many
cells are cards -- a short last row is padded with empty cells, which
are to be ignored. `cells` names what is in each cell, reading left to
right and top to bottom.

## Rebuilding

    python3 scripts/export_screentop_assets.py

Re-run this after a rules change, an import or an art fix rather than
keeping an old copy around; the rules are `docs/living-rules.md` in the
repo, and `/d12ball rules_*` in Discord.
"""


def write_readme(out_dir: Path, max_side: int) -> None:
    readme = README_TEMPLATE.format(
        generated=date.today().isoformat(), max_side=max_side,
    )
    (out_dir / "README.md").write_text(readme)
    print(f"wrote {out_dir / 'README.md'}")


def zip_kit(out_dir: Path) -> Path:
    zip_path = out_dir.with_suffix(".zip")
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(out_dir.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(out_dir.parent))
    print(f"wrote {zip_path}")
    return zip_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Export every card, board, meeple, die and token of D12 "
            "Ball, cut for screentop.gg."
        ),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=PROJECT_ROOT / "screentop",
        help="Directory to write into (default: ./screentop). Replaced whole.",
    )
    parser.add_argument(
        "--max-side",
        type=int,
        default=MAX_SIDE,
        help=(
            f"Longest side any image may have, in pixels (default: "
            f"{MAX_SIDE}). Images are only ever scaled down to it."
        ),
    )
    parser.add_argument(
        "--zip",
        action="store_true",
        help="Also bundle the finished folder into <out>.zip.",
    )
    args = parser.parse_args()
    if args.max_side < 1:
        parser.error("--max-side must be at least 1")

    if args.out.exists():
        shutil.rmtree(args.out)
    args.out.mkdir(parents=True)

    assets = build_assets(args.max_side)
    listing = write_kit(args.out, args.max_side, assets)
    for entry in listing["assets"]:
        if entry["kind"].endswith("sheet") or entry["kind"] == "board":
            grid = (
                f"  {entry['columns']} x {entry['rows']}, {entry['count']} cells"
                if "columns" in entry
                else ""
            )
            print(f"wrote {args.out / entry['file']}  {entry['size']}{grid}")
    print(f"wrote {args.out / 'manifest.json'}  ({len(listing['assets'])} files)")

    write_readme(args.out, args.max_side)

    if args.zip:
        zip_kit(args.out)

    print(f"\nscreentop.gg assets written to {args.out}")


if __name__ == "__main__":
    main()
