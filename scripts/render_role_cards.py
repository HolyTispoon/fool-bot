#!/usr/bin/env python3
"""Render the role-ability reference card for the physical game.

One double-sided card, print-ready at 2.5 x 3.5 inches (poker size),
three of the six basic role abilities a face:

    python3 scripts/render_role_cards.py --out cards/roles
    python3 scripts/render_role_cards.py --sheet --bleed

The layout lives in `d12ball/role_cards.py` and the text comes from
`d12ball/data/players.json`'s `role_profiles`, so a sheet revision
(`scripts/import_d12ball_players.py`) reaches the card by re-running
this.
"""
import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from d12ball.cards import SHEET_COLUMNS, print_sheet  # noqa: E402
from d12ball.components import load_player_catalog  # noqa: E402
from d12ball.role_cards import render_role_card_set  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render the role-ability reference card.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=PROJECT_ROOT / "cards" / "roles",
        help="Directory to write the PNGs into (default: ./cards/roles)",
    )
    parser.add_argument(
        "--bleed",
        action="store_true",
        help="Add a 1/8in bleed margin for a print shop to trim into.",
    )
    parser.add_argument(
        "--sheet",
        action="store_true",
        help="Also write print-sheet.png: every face in an even grid.",
    )
    args = parser.parse_args()

    role_profiles = load_player_catalog().role_profiles
    args.out.mkdir(parents=True, exist_ok=True)

    faces = render_role_card_set(role_profiles, args.bleed)
    for name, card in faces:
        path = args.out / f"card-{name}.png"
        card.save(path, dpi=(300, 300))
        print(f"wrote {path}")

    if args.sheet:
        cards = [card for _, card in faces]
        # Padded to a full grid by cycling back through the set, a
        # whole card at a time -- see the same comment in
        # render_species_cards.py. Two faces leave a 4-wide sheet two
        # cells short, and there is no shared back to spare, so the pad
        # repeats front-then-back.
        while len(cards) % SHEET_COLUMNS:
            cards.append(cards[len(cards) % len(faces)])
        sheet_path = args.out / "print-sheet.png"
        print_sheet(cards).save(sheet_path, dpi=(300, 300))
        print(f"wrote {sheet_path}")


if __name__ == "__main__":
    main()
