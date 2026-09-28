#!/usr/bin/env python3
"""Render the twelve maneuver cards for the physical game.

Twelve faces and their two backs, print-ready at 2.5 x 3.5 inches (poker size):

    python3 scripts/render_maneuver_cards.py --out d12ball/print/maneuver-cards
    python3 scripts/render_maneuver_cards.py --bleed --sheet
    python3 scripts/render_maneuver_cards.py --hands

**Two backs, one a tier** (the author, 2026-09-28). The six basic
maneuvers carry the standard back -- the hexagon with one name on each
node -- and the six advanced maneuvers the advanced back, whose hexagon
carries both tiers (`render_maneuver_card_back`'s `tier`). `--sheet`
writes each tier as a front sheet and a back sheet, six cards to a
sheet, three across, printed duplex.

The layout itself lives in `d12ball/cards.py`, because the bot draws
from it too -- `--hands` writes exactly the images a coach is shown
after clicking "Choose Your Maneuver", which is the way to look at
those without running the bot.
"""
import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from d12ball.cards import (  # noqa: E402
    DUPLEX_COLUMNS,
    duplex_order,
    maneuver_hand_combinations,
    print_sheet,
    render_maneuver_card,
    render_maneuver_card_back,
    render_maneuver_hands,
)
from d12ball.components import (  # noqa: E402
    MANEUVER_TIER_GAMBIT,
    MANEUVER_TIER_WORDS,
    MANEUVER_TIERS,
    load_maneuver_catalog,
    load_player_catalog,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render the twelve maneuver cards and their two backs.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=PROJECT_ROOT / "d12ball" / "print" / "maneuver-cards",
        help="Directory to write the PNGs into (default: ./d12ball/print/maneuver-cards)",
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
            "Also write <tier>-front-sheet.png and <tier>-back-sheet.png "
            "for the basic and the advanced tier: its six cards "
            f"{DUPLEX_COLUMNS} across, and their backs in duplex order."
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
    parser.add_argument(
        "--sheets-only",
        action="store_true",
        help="Write only the print sheets, not a PNG per card. Implies --sheet.",
    )
    args = parser.parse_args()
    args.sheet = args.sheet or args.sheets_only

    catalog = load_maneuver_catalog()
    players = load_player_catalog()
    args.out.mkdir(parents=True, exist_ok=True)

    for tier in MANEUVER_TIERS:
        word = MANEUVER_TIER_WORDS[tier]
        # Offense then defense, rank order within each, so a sheet's
        # top row is the offense and its bottom row the defense.
        fronts = []
        for side, is_offense in (("offense", True), ("defense", False)):
            for maneuver in catalog.for_tier(side, tier):
                card = render_maneuver_card(
                    catalog, players, maneuver, is_offense, args.bleed
                )
                fronts.append(card)
                if not args.sheets_only:
                    slug = maneuver.name.lower().replace(" ", "-")
                    path = args.out / f"{side[0]}{maneuver.rank}-{slug}.png"
                    card.save(path, dpi=(300, 300))
                    print(f"wrote {path}")

        back = render_maneuver_card_back(catalog, args.bleed, tier)
        if not args.sheets_only:
            back_path = args.out / f"back-{word}.png"
            back.save(back_path, dpi=(300, 300))
            print(f"wrote {back_path}")

        if args.sheet:
            front_path = args.out / f"{word}-front-sheet.png"
            print_sheet(fronts, columns=DUPLEX_COLUMNS).save(
                front_path, dpi=(300, 300)
            )
            print(f"wrote {front_path}")
            back_sheet = args.out / f"{word}-back-sheet.png"
            print_sheet(
                duplex_order([back] * len(fronts), DUPLEX_COLUMNS),
                columns=DUPLEX_COLUMNS,
            ).save(back_sheet, dpi=(300, 300))
            print(f"wrote {back_sheet}")

    if args.hands:
        # Every image the maneuver prompt can carry, which is what the
        # bot draws at startup: one `(side, tiers)` pair per hand on the
        # prompt, from the one list the bot itself reads
        # (`maneuver_hand_combinations`). Both sides is the ordinary
        # contested prompt; one alone is an unchallenged maneuver or a
        # solo game against Dinky. The tiers are per side, since a
        # gambit is held only by a coach whose team is behind.
        for hands in maneuver_hand_combinations():
            name = "-".join(
                f"{side}-{'gambits' if MANEUVER_TIER_GAMBIT in tiers else 'basic'}"
                for side, tiers in hands
            )
            hand_path = args.out / f"hand-{name}.png"
            hand_path.write_bytes(
                render_maneuver_hands(catalog, players, hands).getvalue()
            )
            print(f"wrote {hand_path}")

if __name__ == "__main__":
    main()
