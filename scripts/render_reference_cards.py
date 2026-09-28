#!/usr/bin/env python3
"""Render the table's reference cards as two sheets printed duplex.

The three double-sided species-ability cards and the double-sided
role-ability card: `front-sheet.png` is every card's front and
`back-sheet.png` every card's back, three across, the backs in duplex
order so each lands behind its own front:

    python3 scripts/render_reference_cards.py --out d12ball/print/reference-cards
    python3 scripts/render_reference_cards.py --bleed

This is what the print-and-play kit prints (the author, 2026-09-27: the
species and the role reference cards together; 2026-09-28: as a front
and a back sheet for double-sided printing, where they had been one
sheet of faces to cut out in pairs and glue). The layouts are
`d12ball/species_cards.py` and `d12ball/role_cards.py`, unchanged;
`render_species_cards.py` and `render_role_cards.py` still render each
set on its own.
"""
import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from d12ball.cards import DUPLEX_COLUMNS, duplex_order, print_sheet  # noqa: E402
from d12ball.components import load_player_catalog  # noqa: E402
from d12ball.role_cards import render_role_card_set  # noqa: E402
from d12ball.species_cards import (  # noqa: E402
    load_species_abilities,
    render_species_card_set,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Render the species and role reference cards as a front "
            "sheet and a back sheet for duplex printing."
        ),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=PROJECT_ROOT / "d12ball" / "print" / "reference-cards",
        help=(
            "Directory to write front-sheet.png and back-sheet.png into "
            "(default: ./d12ball/print/reference-cards)"
        ),
    )
    parser.add_argument(
        "--bleed",
        action="store_true",
        help="Add a 1/8in bleed margin for a print shop to trim into.",
    )
    args = parser.parse_args()

    # Both sets hand back a card's faces as a front and then its back.
    faces = [
        card
        for _, card in render_species_card_set(load_species_abilities(), args.bleed)
    ] + [
        card
        for _, card in render_role_card_set(load_player_catalog().role_profiles, args.bleed)
    ]
    fronts, backs = faces[0::2], faces[1::2]

    args.out.mkdir(parents=True, exist_ok=True)
    front_path = args.out / "front-sheet.png"
    print_sheet(fronts, columns=DUPLEX_COLUMNS).save(front_path, dpi=(300, 300))
    print(f"wrote {front_path}")
    back_path = args.out / "back-sheet.png"
    print_sheet(
        duplex_order(backs, DUPLEX_COLUMNS), columns=DUPLEX_COLUMNS,
    ).save(back_path, dpi=(300, 300))
    print(f"wrote {back_path}")


if __name__ == "__main__":
    main()
