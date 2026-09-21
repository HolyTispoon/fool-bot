#!/usr/bin/env python3
"""Build the two rulebooks as PDFs, and the figures they show.

    python3 scripts/build_rulebooks.py                 # both books -> print/
    python3 scripts/build_rulebooks.py charter --paper a4
    python3 scripts/build_rulebooks.py --outlines      # the plan and outlines as PDFs
    python3 scripts/build_rulebooks.py --figures       # regenerate docs/rulebooks/figures/

The layout lives in `d12ball/rulebooks.py` and the figures in
`d12ball/rulebook_figures.py`; this is the CLI. See
docs/design/rulebooks.md and docs/rulebooks/plan.md.

Until `docs/charter.md` exists the `charter` book is built from
`docs/living-rules.md` with build-time numbering, which is what the
numbered draft will look like. `learn-to-play` is skipped with a notice
until `docs/learn-to-play.md` is written.
"""
import argparse
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
    build_book,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the D12 Ball rulebooks as PDFs.")
    parser.add_argument(
        "books",
        nargs="*",
        metavar="BOOK",
        help=f"Which books to build (default: both rulebooks). One of: {', '.join([*BOOKS, *OUTLINE_BOOKS])}.",
    )
    parser.add_argument("--paper", default=DEFAULT_PAPER, choices=sorted(PAPERS))
    parser.add_argument("--out", type=Path, default=PRINT_DIR, help="Output folder (default: print/).")
    parser.add_argument(
        "--outlines", action="store_true",
        help="Build the plan and the two outlines in docs/rulebooks/ instead of the books.",
    )
    parser.add_argument(
        "--figures", action="store_true",
        help="Regenerate docs/rulebooks/figures/ from the bot's renderer, then exit.",
    )
    args = parser.parse_args()

    if args.figures:
        from d12ball.rulebook_figures import write_figures

        for path in write_figures():
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
        print(f"wrote {path.relative_to(PROJECT_ROOT)} from {book.source.relative_to(PROJECT_ROOT)}")
        built += 1
    return 0 if built else 1


if __name__ == "__main__":
    raise SystemExit(main())
