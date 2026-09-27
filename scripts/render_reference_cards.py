#!/usr/bin/env python3
"""Render the table's reference cards as one print sheet.

The three double-sided species-ability cards and the double-sided
role-ability card, every face, each card's front beside its back so a
pair is cut out together and glued back to back -- eight faces, which
is two full rows of the sheet:

    python3 scripts/render_reference_cards.py --out cards/reference
    python3 scripts/render_reference_cards.py --bleed

This is what the print-and-play kit prints (the author, 2026-09-27: the
species and the role reference cards together). The layouts are
`d12ball/species_cards.py` and `d12ball/role_cards.py`, unchanged;
`render_species_cards.py` and `render_role_cards.py` still render each
set on its own.
"""
import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from d12ball.cards import SHEET_COLUMNS, print_sheet  # noqa: E402
from d12ball.components import load_player_catalog  # noqa: E402
from d12ball.role_cards import render_role_card_set  # noqa: E402
from d12ball.species_cards import (  # noqa: E402
    load_species_abilities,
    render_species_card_set,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render the species and role reference cards as one print sheet.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=PROJECT_ROOT / "cards" / "reference",
        help="Directory to write print-sheet.png into (default: ./cards/reference)",
    )
    parser.add_argument(
        "--bleed",
        action="store_true",
        help="Add a 1/8in bleed margin for a print shop to trim into.",
    )
    args = parser.parse_args()

    faces = [
        card
        for _, card in render_species_card_set(load_species_abilities(), args.bleed)
    ] + [
        card
        for _, card in render_role_card_set(load_player_catalog().role_profiles, args.bleed)
    ]
    # Padded like the species sheet, a whole card (front and back) at a
    # time, should the sets ever stop filling their rows exactly.
    cards = list(faces)
    while len(cards) % SHEET_COLUMNS:
        cards.append(faces[len(cards) % len(faces)])
    args.out.mkdir(parents=True, exist_ok=True)
    sheet_path = args.out / "print-sheet.png"
    print_sheet(cards).save(sheet_path, dpi=(300, 300))
    print(f"wrote {sheet_path}")


if __name__ == "__main__":
    main()
