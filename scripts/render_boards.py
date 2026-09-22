#!/usr/bin/env python3
"""Render the three boards of the physical game.

Print-ready at 300dpi. The field board is tabloid (11 x 17) by
default -- a home or copy-shop printer's own size, where A3 is not.
**The jumbotron is a letter sheet and comes out both ways up** --
`jumbotron-board.png` portrait and `jumbotron-board-landscape.png` --
and the team board is half a letter sheet, two coaches to a page: both
have a paper of their own, because letter is the size a printer in the
house actually has in it and neither board has a field on it to pay
for a bigger sheet. See
`PAPERS`, `DEFAULT_PAPER`, `JUMBOTRON_PAPER` and `TEAM_BOARD_PAPER` in
`d12ball/boards.py`:

    python3 scripts/render_boards.py --out print/
    python3 scripts/render_boards.py --teams --bleed --pdf
    python3 scripts/render_boards.py --board-size 9

Every field board the ruleset defines is written unless --board-size
narrows it to one, so a print run comes out with the 7- and 9-space
fields, the jumbotron, and the team board -- **twice**: one
board on its own (`team-board.png`, half a letter sheet) and a letter
page carrying two of them to be cut apart, one for each coach
(`team-board-2up.png`).

A field board also comes out **three ways**: whole on the tabloid
sheet (`field-board-7.png`), and as its own top and bottom halves on
letter (`field-board-7-top.png`, `field-board-7-bottom.png`), which
taped along the cut are that same board at the same size -- for a
house with a letter printer and no tabloid one. --no-halves leaves
them out.

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
    JUMBOTRON_PAPER,
    MIN_TOKEN_INCHES,
    PAPERS,
    PRINT_DPI,
    TEAM_BOARD_PAPER,
    card_slot_inches,
    cell_inches,
    half_paper,
    render_field_board,
    render_field_board_halves,
    render_jumbotron_board,
    render_team_board,
    render_team_board_sheet,
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
            "Render the field, jumbotron and team boards, print-ready."
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
        choices=(7, 9),
        help=(
            "Render only this field board. Every size the ruleset "
            "defines is written otherwise."
        ),
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
            f"Sheet size for the field board (default: {DEFAULT_PAPER}). "
            "The jumbotron and the team board each have a paper of "
            "their own -- see --jumbotron-paper and --team-paper."
        ),
    )
    parser.add_argument(
        "--jumbotron-paper",
        default=JUMBOTRON_PAPER,
        choices=sorted(PAPERS),
        help=(
            f"The sheet the jumbotron is drawn on, portrait (default: "
            f"{JUMBOTRON_PAPER}). Anything smaller takes its cells "
            "under a token; the CLI says so."
        ),
    )
    parser.add_argument(
        "--team-paper",
        default=TEAM_BOARD_PAPER,
        choices=sorted(PAPERS),
        help=(
            f"The sheet a coach's two boards are cut from (default: "
            f"{TEAM_BOARD_PAPER}). One board is half of it: the two-up "
            "page is the whole sheet, cut across."
        ),
    )
    parser.add_argument(
        "--no-halves",
        dest="halves",
        action="store_false",
        help=(
            "Skip the two half-sheet files each field board is also "
            "written as. They are the same board cut in two, for a "
            "printer that does not take the whole sheet."
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

    sizes = (
        (args.board_size,)
        if args.board_size
        else tuple(sorted(rules.board_layouts))
    )
    for board_size in sizes:
        board = render_field_board(
            rules, board_size, paper=args.paper, bleed=args.bleed
        )
        save(board, args.out / f"field-board-{board_size}.png", args.pdf)
        if not args.halves:
            continue
        # The same board, cut in two -- not a second layout for the
        # smaller paper, so the two taped together are the sheet above
        # and a space is the size it is on it.
        halves = render_field_board_halves(
            rules, board_size, paper=args.paper, bleed=args.bleed
        )
        for name, half in zip(("top", "bottom"), halves):
            save(
                half,
                args.out / f"field-board-{board_size}-{name}.png",
                args.pdf,
            )

    # Both ways up. It is one layout on a turned sheet rather than two
    # designs, so a print run takes whichever suits the table --
    # portrait is the roomier, landscape the one that sits across a
    # table in front of two coaches.
    for landscape, suffix in ((False, ""), (True, "-landscape")):
        save(
            render_jumbotron_board(
                paper=args.jumbotron_paper,
                landscape=landscape,
                bleed=args.bleed,
            ),
            args.out / f"jumbotron-board{suffix}.png",
            args.pdf,
        )

    teams = tuple(Team) if args.teams else (None,)
    for team in teams:
        suffix = f"-{team.value}" if team else ""
        # Two files per team: the board itself, and the page a match's
        # two coaches are cut from. They are the same board -- the page
        # pastes it twice -- so a print run picks whichever suits the
        # paper it is going on.
        save(
            render_team_board(
                rules,
                players,
                maneuvers,
                team=team,
                paper=args.team_paper,
                bleed=args.bleed,
            ),
            args.out / f"team-board{suffix}.png",
            args.pdf,
        )
        save(
            render_team_board_sheet(
                rules,
                players,
                maneuvers,
                team=team,
                paper=args.team_paper,
                bleed=args.bleed,
            ),
            args.out / f"team-board-2up{suffix}.png",
            args.pdf,
        )

    if args.halves:
        halved = half_paper(args.paper)
        size = (
            f"{halved} sheets, landscape"
            if halved
            else f"half a {args.paper} sheet, which is no paper size of "
            "its own"
        )
        print(
            f"field board halves are {size}  -- tape the two along the "
            "cut for the whole board"
        )

    slot = card_slot_inches(args.team_paper)
    print(
        f"team board bench guides are {slot[0]:.2f} x {slot[1]:.2f} in"
        + (
            ""
            if slot[0] >= CARD_INCHES[0]
            else "  -- smaller than a poker card, so a bench stacks on "
            "the area rather than inside the guide"
        )
    )
    # Reported for both, because they do not measure the same and
    # landscape is the tight one -- it is where a share redivided too
    # far shows up first.
    for landscape, facing in ((False, "portrait"), (True, "landscape")):
        cells = cell_inches(args.jumbotron_paper, landscape=landscape)
        for name, (width, height) in cells.items():
            note = (
                ""
                if min(width, height) >= MIN_TOKEN_INCHES
                else "  -- too small to stand a token in"
            )
            print(
                f"jumbotron ({facing}) {name} cells are "
                f"{width:.2f} x {height:.2f} in" + note
            )


if __name__ == "__main__":
    main()
