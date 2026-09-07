#!/usr/bin/env python3
"""Render the species-ability reference cards for the physical game.

Three double-sided cards, print-ready at 2.5 x 3.5 inches (poker size),
each face carrying two of the four species abilities so that every
species pairing appears on some face:

    python3 scripts/render_species_cards.py --out cards/species
    python3 scripts/render_species_cards.py --sheet --bleed

The layout lives in `d12ball/species_cards.py` and the text comes from
`d12ball/data/species.json`, so a re-import
(`scripts/import_d12ball_species.py`) reaches the cards by re-running
this.
"""
import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from d12ball.cards import SHEET_COLUMNS, print_sheet  # noqa: E402
from d12ball.species_cards import (  # noqa: E402
    load_species_abilities,
    render_species_card_set,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render the three species-ability reference cards.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=PROJECT_ROOT / "cards" / "species",
        help="Directory to write the PNGs into (default: ./cards/species)",
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

    abilities = load_species_abilities()
    args.out.mkdir(parents=True, exist_ok=True)

    faces = render_species_card_set(abilities, args.bleed)
    for name, card in faces:
        path = args.out / f"card-{name}.png"
        card.save(path, dpi=(300, 300))
        print(f"wrote {path}")

    if args.sheet:
        cards = [card for _, card in faces]
        while len(cards) % SHEET_COLUMNS:
            cards.append(cards[0])
        sheet_path = args.out / "print-sheet.png"
        print_sheet(cards).save(sheet_path, dpi=(300, 300))
        print(f"wrote {sheet_path}")


if __name__ == "__main__":
    main()
