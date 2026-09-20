#!/usr/bin/env python3
"""Render the twelve maneuver cards for the physical game.

Twelve faces and one shared back, print-ready at 2.5 x 3.5 inches (poker size):

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
    SHEET_COLUMNS,
    print_sheet,
    render_maneuver_card,
    render_maneuver_card_back,
    render_maneuver_hands,
)
from d12ball.components import (  # noqa: E402
    MANEUVER_TIER_BASIC,
    MANEUVER_TIER_GAMBIT,
    load_maneuver_catalog,
    load_player_catalog,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render the twelve maneuver cards and their shared back.",
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
        help=(
            "Also write print-sheet.png: every card in an even grid "
            f"{SHEET_COLUMNS} across, each centred in its own cell."
        ),
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
        # Padded to a full grid with spare backs: the six faces and one
        # back leave a hole in a 4-wide sheet, and a splitter cutting
        # it into equal cells would hand back a blank. Backs are what
        # you need more of anyway.
        while len(cards) % SHEET_COLUMNS:
            cards.append(back)
        sheet_path = args.out / "print-sheet.png"
        print_sheet(cards).save(sheet_path, dpi=(300, 300))
        print(f"wrote {sheet_path}")

    if args.hands:
        # Every image the maneuver prompt can carry, which is the six
        # the bot draws at startup: the sides a person still picks for
        # (`RulesEngine.maneuver_pick_sides`) against the tiers they may
        # play (`RulesEngine.maneuver_tiers`). Both sides is the
        # ordinary contested prompt; one alone is an unchallenged
        # maneuver or a solo game against Dinky.
        for sides in (("offense",), ("defense",), ("offense", "defense")):
            for label, tiers in (
                ("basic", (MANEUVER_TIER_BASIC,)),
                (
                    "gambits",
                    (MANEUVER_TIER_BASIC, MANEUVER_TIER_GAMBIT),
                ),
            ):
                hand_path = args.out / f"hand-{'-'.join(sides)}-{label}.png"
                hand_path.write_bytes(
                    render_maneuver_hands(
                        catalog, players, sides, tiers,
                    ).getvalue()
                )
                print(f"wrote {hand_path}")


if __name__ == "__main__":
    main()
