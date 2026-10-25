#!/usr/bin/env python3
"""Render the players as standees, a colour team a letter page.

    python3 scripts/render_standees.py
    python3 scripts/render_standees.py --out /tmp/standees --team orange

One page a colour team, `<team>-standees.png`, printed one-sided: each
player's strip carries both faces, to be cut out, folded, glued back to
back and stood in a 1in slotted base. The faces and the layout live in
`d12ball/standees.py`; see docs/design/standees.md.
"""
import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from d12ball.boards import PRINT_DPI  # noqa: E402
from d12ball.components import load_player_catalog  # noqa: E402
from d12ball.game import COLOR_TEAMS, Team  # noqa: E402
from d12ball.standees import render_standee_pages  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render the players as standees, a colour team a letter page.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=PROJECT_ROOT / "d12ball" / "print" / "standees",
        help="Directory to write the pages into (default: ./d12ball/print/standees)",
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
    for team, page in render_standee_pages(load_player_catalog(), teams).items():
        path = args.out / f"{team.value}-standees.png"
        page.save(path, dpi=(PRINT_DPI, PRINT_DPI))
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
