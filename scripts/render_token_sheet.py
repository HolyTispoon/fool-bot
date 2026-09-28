#!/usr/bin/env python3
"""Render the condition tokens as a print-and-play pair of sheets.

    python3 scripts/render_token_sheet.py --out d12ball/print/tokens

Two letter sheets per style, `<style>-front-sheet.png` and
`<style>-back-sheet.png`, printed on the two sides of one piece of paper
(duplex, flipped on the long edge): every token's front face on one and
its back on the other, in the mirrored position. `light` is drawn for
paper and `dark` is the bot's own art; both are written unless `--style`
names one. The layout, the pairings and the counts live in
`d12ball/token_sheet.py`; see "Paper tokens" in
docs/design/printed-tokens.md.
"""
import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from d12ball.boards import PRINT_DPI  # noqa: E402
from d12ball.token_sheet import STYLES, render_token_sheets  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render the condition tokens as a duplex pair of print sheets.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=PROJECT_ROOT / "d12ball" / "print" / "tokens",
        help="Directory to write the sheets into (default: ./d12ball/print/tokens)",
    )
    parser.add_argument(
        "--style",
        choices=STYLES,
        action="append",
        help="Only this style (repeatable; default: every style).",
    )
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    for style in args.style or STYLES:
        sheets = render_token_sheets(style=style)
        for side, sheet in zip(("front", "back"), sheets):
            path = args.out / f"{style}-{side}-sheet.png"
            sheet.save(path, dpi=(PRINT_DPI, PRINT_DPI))
            print(f"wrote {path}")


if __name__ == "__main__":
    main()
