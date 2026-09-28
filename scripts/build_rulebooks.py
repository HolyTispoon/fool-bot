#!/usr/bin/env python3
"""Build the two rulebooks as PDFs, and the figures they show.

    python3 scripts/build_rulebooks.py                 # both books -> print/rulebooks/
    python3 scripts/build_rulebooks.py charter --paper a4
    python3 scripts/build_rulebooks.py --outlines      # the plan and outlines as PDFs
    python3 scripts/build_rulebooks.py --figures       # regenerate docs/rulebooks/figures/
    python3 scripts/build_rulebooks.py --cover-dice    # redraw d12ball/images/cover_dice/
    python3 scripts/build_rulebooks.py --renumber      # write the Charter's numbers into its source

The layout lives in `d12ball/rulebooks.py` and the figures in
`d12ball/rulebook_figures.py`; this is the CLI. See
docs/design/rulebooks.md and docs/rulebooks/plan.md.

Until `docs/charter.md` exists the `charter` book is built from
`docs/living-rules.md`. The file carries the printed edition's numbers,
which `--renumber` writes after any Law, section or paragraph is added,
moved or taken out; the test suite fails until it has been run. `learn-to-play` is skipped with a notice
until `docs/learn-to-play.md` is written.
"""
import argparse
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from d12ball.rulebooks import (  # noqa: E402
    BOOKS,
    DEFAULT_PAPER,
    OUTLINE_BOOKS,
    PAPERS,
    PRINT_DIR,
    anchor_moves,
    build_book,
    renumber,
)


def renumber_charter() -> int:
    """
    The Charter's source, renumbered in place; then every markdown file
    that links a heading in it, with the link moved to the heading's
    new anchor.
    """
    source = BOOKS["charter"].source
    before = source.read_text(encoding="utf-8")
    after = renumber(before)
    if after != before:
        source.write_text(after, encoding="utf-8")
        print(f"renumbered {source.relative_to(PROJECT_ROOT)}")
    moves = anchor_moves(before, after)
    link = re.compile(rf"({re.escape(source.name)}#)([\w-]+)")
    for path in [PROJECT_ROOT / "CLAUDE.md", *sorted((PROJECT_ROOT / "docs").rglob("*.md"))]:
        text = path.read_text(encoding="utf-8")
        moved = link.sub(lambda m: m.group(1) + moves.get(m.group(2), m.group(2)), text)
        if moved != text:
            path.write_text(moved, encoding="utf-8")
            print(f"moved links in {path.relative_to(PROJECT_ROOT)}")
    return 0


def shown(path: Path) -> str:
    """
    A path as the report names it: relative to the repository when it is
    inside it, absolute otherwise. `--out` may name a folder anywhere, and
    `Path.relative_to` raises on one outside the repository.
    """
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(resolved)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the D12 Ball rulebooks as PDFs.")
    parser.add_argument(
        "books",
        nargs="*",
        metavar="BOOK",
        help=f"Which books to build (default: both rulebooks). One of: {', '.join([*BOOKS, *OUTLINE_BOOKS])}.",
    )
    parser.add_argument("--paper", default=DEFAULT_PAPER, choices=sorted(PAPERS))
    parser.add_argument("--out", type=Path, default=PRINT_DIR, help="Output folder (default: print/rulebooks/).")
    parser.add_argument(
        "--outlines", action="store_true",
        help="Build the plan and the two outlines in docs/rulebooks/ instead of the books.",
    )
    parser.add_argument(
        "--renumber", action="store_true",
        help="Write the Charter's numbers into its source, and move the links other docs make into it, then exit.",
    )
    parser.add_argument(
        "--figures", action="store_true",
        help="Regenerate docs/rulebooks/figures/ from the bot's renderer, then exit.",
    )
    parser.add_argument(
        "--cover-dice", action="store_true",
        help="Redraw the covers' dice into d12ball/images/cover_dice/, then exit.",
    )
    args = parser.parse_args()

    if args.renumber:
        return renumber_charter()

    if args.figures:
        from d12ball.rulebook_figures import write_figures

        for path in write_figures():
            print(f"wrote {path.relative_to(PROJECT_ROOT)}")
        return 0

    if args.cover_dice:
        from d12ball.rulebooks import write_cover_dice

        for path in write_cover_dice():
            print(f"wrote {path.relative_to(PROJECT_ROOT)}")
        return 0

    catalog = {**BOOKS, **OUTLINE_BOOKS}
    unknown = [name for name in args.books if name not in catalog]
    if unknown:
        parser.error(f"unknown book(s) {', '.join(unknown)}; choose from {', '.join(catalog)}")
    names = args.books or (list(OUTLINE_BOOKS) if args.outlines else list(BOOKS))
    built = 0
    for name in names:
        book = catalog[name]
        if book.source is None:
            print(f"skipped {name}: none of {', '.join(str(p.relative_to(PROJECT_ROOT)) for p in book.sources)} exists yet")
            continue
        path = build_book(book, args.out / f"{name}.pdf", paper=args.paper)
        print(f"wrote {shown(path)} from {shown(book.source)}")
        built += 1
    return 0 if built else 1


if __name__ == "__main__":
    raise SystemExit(main())
