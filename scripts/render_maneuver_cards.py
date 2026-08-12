#!/usr/bin/env python3
"""Render the six maneuver cards for the physical game.

Six faces and one shared back, print-ready at 2.5 x 3.5 inches (poker size):

    python3 scripts/render_maneuver_cards.py --out cards/
    python3 scripts/render_maneuver_cards.py --bleed --sheet
    python3 scripts/render_maneuver_cards.py --hands

The layout itself lives in `d12ball/cards.py`, because the bot draws
from it too -- `--hands` writes exactly the images a coach is shown
after clicking "Choose Your Maneuver", which is the way to look at
those without running the bot.
"""
import argparse
import sys
from pathlib import Path

from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from d12ball.cards import (  # noqa: E402
    contact_sheet,
    render_maneuver_card,
    render_maneuver_card_back,
    render_maneuver_hand,
)
from d12ball.components import (  # noqa: E402
    load_maneuver_catalog,
    load_player_catalog,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render the six maneuver cards and their shared back.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=PROJECT_ROOT / "cards",
        help="Directory to write the PNGs into (default: ./cards)",
    )
    parser.add_argument(
        "--bleed",
        action="store_true",
        help="Add a 1/8in bleed margin for a print shop to trim into.",
    )
    parser.add_argument(
        "--sheet",
        action="store_true",
        help="Also write contact-sheet.png with all seven side by side.",
    )
    parser.add_argument(
        "--hands",
        action="store_true",
        help=(
            "Also write the two hand images the bot shows a coach "
            "choosing a maneuver."
        ),
    )
    args = parser.parse_args()

    catalog = load_maneuver_catalog()
    players = load_player_catalog()
    args.out.mkdir(parents=True, exist_ok=True)

    cards: list[Image.Image] = []
    for maneuvers, is_offense in (
        (catalog.offense, True),
        (catalog.defense, False),
    ):
        for maneuver in maneuvers:
            card = render_maneuver_card(
                catalog, players, maneuver, is_offense, args.bleed
            )
            slug = maneuver.name.lower().replace(" ", "-")
            side = "o" if is_offense else "d"
            path = args.out / f"{side}{maneuver.rank}-{slug}.png"
            card.save(path, dpi=(300, 300))
            cards.append(card)
            print(f"wrote {path}")

    back = render_maneuver_card_back(catalog, args.bleed)
    back_path = args.out / "back.png"
    back.save(back_path, dpi=(300, 300))
    cards.append(back)
    print(f"wrote {back_path}")

    if args.sheet:
        sheet_path = args.out / "contact-sheet.png"
        contact_sheet(cards).save(sheet_path)
        print(f"wrote {sheet_path}")

    if args.hands:
        for side in ("offense", "defense"):
            hand_path = args.out / f"hand-{side}.png"
            hand_path.write_bytes(
                render_maneuver_hand(catalog, players, side).getvalue()
            )
            print(f"wrote {hand_path}")


if __name__ == "__main__":
    main()
