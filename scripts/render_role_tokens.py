#!/usr/bin/env python3
"""Render D12 Ball 2.0's role tokens as a print-and-play pair of sheets.

    python3 scripts/render_role_tokens.py
    python3 scripts/render_role_tokens.py --out /tmp/role-tokens --team orange

Two letter sheets, `front-sheet.png` and `back-sheet.png`, printed on the
two sides of one piece of paper (duplex, flipped on the long edge): each
token's unique role on the front and its zone's standard role on the
back, every colour team's nine unless `--team` names some. The faces,
the counts and the layout live in `d12ball/role_tokens.py`; see "Role
tokens" in docs/design/printed-tokens.md.
"""
import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from d12ball.boards import PRINT_DPI  # noqa: E402
from d12ball.components import load_basic_ruleset  # noqa: E402
from d12ball.game import COLOR_TEAMS, Team  # noqa: E402
from d12ball.role_tokens import render_role_token_sheets  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render D12 Ball 2.0's role tokens as a duplex pair of print sheets.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=PROJECT_ROOT / "d12ball" / "print" / "role-tokens",
        help="Directory to write the sheets into (default: ./d12ball/print/role-tokens)",
    )
    parser.add_argument(
        "--team",
        choices=[team.value for team in COLOR_TEAMS],
        action="append",
        help="Only this colour team (repeatable; default: all four).",
    )
    args = parser.parse_args()
    teams = tuple(Team(value) for value in args.team) if args.team else COLOR_TEAMS
    args.out.mkdir(parents=True, exist_ok=True)
    sheets = render_role_token_sheets(load_basic_ruleset(), teams)
    for side, sheet in zip(("front", "back"), sheets):
        path = args.out / f"{side}-sheet.png"
        sheet.save(path, dpi=(PRINT_DPI, PRINT_DPI))
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
