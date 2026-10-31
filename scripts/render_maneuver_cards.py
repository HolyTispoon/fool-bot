#!/usr/bin/env python3
"""Render the twelve maneuver cards for the physical game.

Twelve faces and their two backs, print-ready at 2.5 x 3.5 inches (poker size):

    python3 scripts/render_maneuver_cards.py --out d12ball/print/maneuver-cards
    python3 scripts/render_maneuver_cards.py --bleed --sheet
    python3 scripts/render_maneuver_cards.py --hands
    python3 scripts/render_maneuver_cards.py --edition 2.0 --sheet

**`--edition 2.0` draws D12 Ball 2.1's deck** (the edition's saved
value is still "2.0") into `d12ball/print/maneuver-cards-2.1/` unless
`--out` names another folder: the twenty-four cards of one coach's deck
(`maneuver_deck.deck_cards`), each its 2.1 face
(`deck_faces.render_deck_card`). Every card takes the basic back, the
six basic maneuvers' hexagon (the author, 2026-10-28), in the 2.x
back's style (`EDITION_TWO_BACK`): larger words throughout, each rank
inside its node above the name, and the caption calling the beats line
an arrow. `--sheet` writes them as three Avery 95328 pages and their
backs; `--hands` is 1.0's alone.

**Two backs, one a tier** (the author, 2026-09-28). The six basic
maneuvers carry the standard back -- the hexagon with one name on each
node -- and the six advanced maneuvers the advanced back, whose hexagon
carries both tiers (`render_maneuver_card_back`'s `tier`). `--sheet`
writes each tier as a front sheet and a back sheet, six cards to a
sheet on one Avery Presta 95328 page, printed duplex (flip on the short
edge: the page is landscape).

The layout itself lives in `d12ball/cards.py`, because the bot draws
from it too -- `--hands` writes exactly the images a coach is shown
after clicking "Choose Your Maneuver", which is the way to look at
those without running the bot.
"""
import argparse
import re
import sys
from pathlib import Path

from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from d12ball import maneuver_deck  # noqa: E402
from d12ball.cards import (  # noqa: E402
    BLEED,
    CARD_FACE,
    DUPLEX_COLUMNS,
    EDITION_TWO_BACK,
    avery_95328_pages,
    avery_95328_sheet,
    duplex_order,
    maneuver_hand_combinations,
    render_maneuver_card,
    render_maneuver_card_back,
    render_maneuver_hands,
)
from d12ball.deck_faces import render_deck_card  # noqa: E402
from d12ball.components import (  # noqa: E402
    MANEUVER_TIER_BASIC,
    MANEUVER_TIER_GAMBIT,
    MANEUVER_TIER_WORDS,
    MANEUVER_TIERS,
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.game import Edition  # noqa: E402

PRINT_FOLDER = PROJECT_ROOT / "d12ball" / "print"


def with_bleed(card: Image.Image) -> Image.Image:
    """A card drawn without a bleed given one, as `Pen.finish` gives it:
    the card's own white round it."""
    sheet = Image.new(
        "RGB", (card.width + BLEED * 2, card.height + BLEED * 2), CARD_FACE,
    )
    sheet.paste(card, (BLEED, BLEED))
    return sheet


def render_edition_two(args, catalog, players) -> None:
    """The 2.1 deck: one coach's twenty-four cards, a PNG each, and with
    `--sheet` the Avery 95328 pages and their backs."""
    fronts = []
    for card_id in maneuver_deck.deck_cards(catalog):
        card = catalog.deck_card(card_id)
        face = render_deck_card(catalog, card_id, args.bleed)
        fronts.append(face)
        if not args.sheets_only:
            slug = re.sub(r"[^a-z0-9]+", "-", card.name.lower()).strip("-")
            path = args.out / f"{card_id.lower()}-{slug}.png"
            face.save(path, dpi=(300, 300))
            print(f"wrote {path}")

    back = render_maneuver_card_back(
        catalog, args.bleed, MANEUVER_TIER_BASIC,
        style=EDITION_TWO_BACK,
    )
    if not args.sheets_only:
        back_path = args.out / "back.png"
        back.save(back_path, dpi=(300, 300))
        print(f"wrote {back_path}")

    if args.sheet:
        for kind, pages in (
            ("front", avery_95328_pages(fronts)),
            ("back", avery_95328_pages([back] * len(fronts), backs=True)),
        ):
            for number, page in enumerate(pages, start=1):
                path = args.out / f"deck-{kind}-sheet-{number}.png"
                page.save(path, dpi=(300, 300))
                print(f"wrote {path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render the twelve maneuver cards and their two backs.",
    )
    parser.add_argument(
        "--edition",
        choices=[edition.value for edition in Edition],
        default=Edition.ONE.value,
        help="The edition the cards are for (default: 1.0). 2.0 draws the 2.1 deck of twenty-four.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help=(
            "Directory to write the PNGs into (default: "
            "./d12ball/print/maneuver-cards, or maneuver-cards-2.1 for 2.1)"
        ),
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
            "for the basic and the advanced tier: its six cards on an "
            "Avery Presta 95328 page, and their backs in duplex order."
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
    edition = Edition(args.edition)
    if args.out is None:
        args.out = PRINT_FOLDER / (
            "maneuver-cards" if edition == Edition.ONE else "maneuver-cards-2.1"
        )
    if args.hands and edition != Edition.ONE:
        parser.error("--hands draws 1.0's hands alone")

    catalog = load_maneuver_catalog()
    players = load_player_catalog()
    args.out.mkdir(parents=True, exist_ok=True)

    if edition != Edition.ONE:
        render_edition_two(args, catalog, players)
        return

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
            avery_95328_sheet(fronts).save(front_path, dpi=(300, 300))
            print(f"wrote {front_path}")
            back_sheet = args.out / f"{word}-back-sheet.png"
            avery_95328_sheet(
                duplex_order([back] * len(fronts), DUPLEX_COLUMNS),
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
