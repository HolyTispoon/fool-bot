#!/usr/bin/env python3
"""Render the field board and the team board for the physical game.

Print-ready at 300dpi, A3 landscape by default -- which is the size the
team board's card areas take a real poker card at:

    python3 scripts/render_boards.py --out print/
    python3 scripts/render_boards.py --all-boards --teams --bleed --pdf
    python3 scripts/render_boards.py --board-size 9 --paper tabloid

The layout lives in `d12ball/boards.py`. Everything on either board is
read from the same data the bot plays from, so re-running this is how a
rules or component import reaches the printed boards.
"""
import argparse
import sys
from pathlib import Path

from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from d12ball.boards import (  # noqa: E402
    CARD_INCHES,
    DEFAULT_PAPER,
    PAPERS,
    PRINT_DPI,
    card_slot_inches,
    render_field_board,
    render_team_board,
)
from d12ball.components import (  # noqa: E402
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.game import Team  # noqa: E402


def save(image: Image.Image, path: Path, pdf: bool) -> None:
    image.save(path, dpi=(PRINT_DPI, PRINT_DPI))
    print(f"wrote {path}  ({size_note(image)})")
    if pdf:
        pdf_path = path.with_suffix(".pdf")
        image.save(pdf_path, "PDF", resolution=PRINT_DPI)
        print(f"wrote {pdf_path}")


def size_note(image: Image.Image) -> str:
    return (
        f"{image.width / PRINT_DPI:.2f} x "
        f"{image.height / PRINT_DPI:.2f} in at {PRINT_DPI}dpi"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Render the field board and the team board, print-ready."
        ),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=PROJECT_ROOT / "print",
        help="Directory to write into (default: ./print)",
    )
    parser.add_argument(
        "--board-size",
        type=int,
        default=7,
        choices=(6, 7, 9),
        help="Which field board to render (default: 7)",
    )
    parser.add_argument(
        "--all-boards",
        action="store_true",
        help="Render a field board for all three board sizes.",
    )
    parser.add_argument(
        "--teams",
        action="store_true",
        help=(
            "Render a team board per team colour instead of one "
            "uncoloured board."
        ),
    )
    parser.add_argument(
        "--paper",
        default=DEFAULT_PAPER,
        choices=sorted(PAPERS),
        help=(
            "Sheet size (default: a3). The team board's card areas "
            "are cut for a poker card at a3; every other size scales "
            "the whole board, and its areas, down with it."
        ),
    )
    parser.add_argument(
        "--bleed",
        action="store_true",
        help="Add a 1/8in bleed margin for a print shop to trim into.",
    )
    parser.add_argument(
        "--pdf",
        action="store_true",
        help="Also write a PDF of each board, at the same print size.",
    )
    args = parser.parse_args()

    rules = load_basic_ruleset()
    players = load_player_catalog()
    maneuvers = load_maneuver_catalog()
    args.out.mkdir(parents=True, exist_ok=True)

    sizes = (6, 7, 9) if args.all_boards else (args.board_size,)
    for board_size in sizes:
        board = render_field_board(
            rules, board_size, paper=args.paper, bleed=args.bleed
        )
        save(board, args.out / f"field-board-{board_size}.png", args.pdf)

    teams = tuple(Team) if args.teams else (None,)
    for team in teams:
        board = render_team_board(
            rules,
            players,
            maneuvers,
            team=team,
            paper=args.paper,
            bleed=args.bleed,
        )
        suffix = f"-{team.value}" if team else ""
        save(board, args.out / f"team-board{suffix}.png", args.pdf)

    slot = card_slot_inches(args.paper)
    print(
        f"team board card areas hold a {slot[0]:.2f} x {slot[1]:.2f} in "
        "card"
        + (
            ""
            if slot[0] >= CARD_INCHES[0]
            else "  -- smaller than a poker card, so this print reads "
            "rather than plays"
        )
    )


if __name__ == "__main__":
    main()
