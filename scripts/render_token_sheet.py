#!/usr/bin/env python3
"""Render the condition tokens as a print-and-play sheet.

    python3 scripts/render_token_sheet.py --out cards/tokens

One letter sheet of fold-over tokens: each token's two faces joined on
an edge, to cut out as one piece, fold on the ticks and glue. The
layout, the pairings and the counts live in `d12ball/token_sheet.py`;
see "Paper tokens" in docs/design/printed-tokens.md.
"""
import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from d12ball.boards import PRINT_DPI  # noqa: E402
from d12ball.token_sheet import render_token_sheet  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render the condition tokens as a print-and-play sheet.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=PROJECT_ROOT / "cards" / "tokens",
        help="Directory to write print-sheet.png into (default: ./cards/tokens)",
    )
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    sheet_path = args.out / "print-sheet.png"
    render_token_sheet().save(sheet_path, dpi=(PRINT_DPI, PRINT_DPI))
    print(f"wrote {sheet_path}")


if __name__ == "__main__":
    main()
