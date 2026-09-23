#!/usr/bin/env python3
"""Render the box, the sale sheet and the playtest card, print-ready.

    python3 scripts/render_box_art.py --out box/
    python3 scripts/render_box_art.py --bleed --pdf
    python3 scripts/render_box_art.py --only sale-sheet --contact "you@example.com"

Five panels at 300dpi: the box cover, one side of the box (the box is
square, so the same panel is all four), the underside of the box, a
one-page sale sheet, and the two faces of the playtest card whose back
carries the survey QR.

Everything printed on them is read from the game -- the counts from
the catalogs, the component list from the Learn to Play, and every
quoted rule from the Charter or the Learn to Play, word for word. So
an import or a rules change reaches the box the way it reaches the
printed boards: by running this again.

**A playing time and an age rating are not printed unless you pass
them.** Nothing in this repository measures either, and a box that
guesses is a box that lies; see `RetailClaims` in `d12ball/box_art.py`.
"""
import argparse
import sys
from pathlib import Path

from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from d12ball.box_art import (  # noqa: E402
    NIGHT_COVER,
    PAGE_COVER,
    PRINT_DPI,
    QR_MIN_MODULE_INCHES,
    SURVEY_URL,
    BoxFacts,
    RetailClaims,
    box_inches,
    folded_board_inches,
    qr_module_inches,
    render_box_bottom,
    render_box_cover,
    render_box_side,
    render_banner,
    render_playtest_card_back,
    render_playtest_card_front,
    render_sale_sheet,
)
from d12ball.components import (  # noqa: E402
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
)


PANELS = (
    "cover",
    "banner",
    "side",
    "bottom",
    "sale-sheet",
    "playtest-card",
)


def save(image: Image.Image, path: Path, pdf: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, dpi=(PRINT_DPI, PRINT_DPI))
    print(
        f"wrote {path}  ({image.width / PRINT_DPI:.2f} x "
        f"{image.height / PRINT_DPI:.2f} in at {PRINT_DPI}dpi)"
    )
    if pdf:
        pdf_path = path.with_suffix(".pdf")
        image.save(pdf_path, "PDF", resolution=PRINT_DPI)
        print(f"wrote {pdf_path}")


def minutes(text: str) -> tuple[int, int]:
    """`45-60`, or `50` for a single number."""
    if "-" in text:
        low, high = text.split("-", 1)
        return int(low), int(high)
    return int(text), int(text)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Render the box cover, its side and underside, the sale "
            "sheet and the playtest card."
        ),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=PROJECT_ROOT / "box",
        help="Directory to write into (default: ./box).",
    )
    parser.add_argument(
        "--only",
        choices=PANELS,
        action="append",
        help="Render just this panel; repeat for several.",
    )
    parser.add_argument(
        "--bleed",
        action="store_true",
        help="Add the print-shop 1/8in bleed to every panel.",
    )
    parser.add_argument(
        "--pdf",
        action="store_true",
        help="Also write a PDF of each panel.",
    )
    parser.add_argument(
        "--survey-url",
        default=SURVEY_URL,
        help="What the playtest card's QR points at.",
    )
    parser.add_argument(
        "--contact",
        action="append",
        default=[],
        help=(
            "A line for the sale sheet's answer panel -- an address, a "
            "phone number. Repeatable. Left ruled and empty if none is "
            "given."
        ),
    )
    parser.add_argument(
        "--play-minutes",
        type=minutes,
        help=(
            "Printed playing time, e.g. 45-60. Only pass it once "
            "somebody has timed a real game; nothing here can check it."
        ),
    )
    parser.add_argument(
        "--min-age",
        type=int,
        help="Printed minimum age. The same caveat as --play-minutes.",
    )
    arguments = parser.parse_args()

    wanted = set(arguments.only or PANELS)
    catalog = load_player_catalog()
    rules = load_basic_ruleset()
    maneuvers = load_maneuver_catalog()
    facts = BoxFacts.read(catalog=catalog, maneuvers=maneuvers, rules=rules)
    claims = RetailClaims(
        play_minutes=arguments.play_minutes,
        minimum_age=arguments.min_age,
    )

    side, _, depth = box_inches()
    folded = folded_board_inches()
    print(
        f"box {side:.2f} x {side:.2f} x {depth:.2f}in "
        f"(the field board folds to {folded[0]:.2f} x {folded[1]:.2f}in)"
    )

    out = arguments.out
    if "cover" in wanted:
        save(
            render_box_cover(
                facts=facts, catalog=catalog, rules=rules, claims=claims,
                bleed=arguments.bleed,
            ),
            out / "box-cover.png",
            arguments.pdf,
        )
        # The same cover in the bot's night palette. It is not for the
        # printer -- a full-bleed dark cover is the expensive thing
        # this set is drawn on white to avoid -- it is for a post, a
        # store page or a header, where ink costs nothing.
        save(
            render_box_cover(
                facts=facts, catalog=catalog, rules=rules, claims=claims,
                bleed=arguments.bleed, palette=NIGHT_COVER,
            ),
            out / "box-cover-night.png",
            arguments.pdf,
        )
        print("  box-cover-night.png is for screens, not for the printer")
    if "banner" in wanted:
        # Wide, for the top of a Notion page or a Screentop table --
        # the cover's art with the title beside the players rather
        # than above them. The night one is the default there; the
        # page one is for a white page that wants it.
        save(
            render_banner(
                facts=facts, catalog=catalog, rules=rules,
                bleed=arguments.bleed, palette=NIGHT_COVER,
            ),
            out / "banner-night.png",
            arguments.pdf,
        )
        save(
            render_banner(
                facts=facts, catalog=catalog, rules=rules,
                bleed=arguments.bleed, palette=PAGE_COVER,
            ),
            out / "banner.png",
            arguments.pdf,
        )
        print("  banners are 3000 x 1200 -- twice a Notion page cover")

    if "side" in wanted:
        save(
            render_box_side(facts=facts, bleed=arguments.bleed),
            out / "box-side.png",
            arguments.pdf,
        )
        print("  the box is square, so this one panel is all four sides")
    if "bottom" in wanted:
        save(
            render_box_bottom(
                facts=facts, catalog=catalog, rules=rules,
                maneuvers=maneuvers, bleed=arguments.bleed,
            ),
            out / "box-bottom.png",
            arguments.pdf,
        )
    if "sale-sheet" in wanted:
        save(
            render_sale_sheet(
                facts=facts, catalog=catalog, rules=rules,
                contact=arguments.contact, claims=claims,
                bleed=arguments.bleed,
            ),
            out / "sale-sheet.png",
            arguments.pdf,
        )
        if not arguments.contact:
            print("  no --contact given; the answer panel is left ruled and empty")
    if "playtest-card" in wanted:
        save(
            render_playtest_card_front(
                catalog=catalog, rules=rules, bleed=arguments.bleed
            ),
            out / "playtest-card-front.png",
            arguments.pdf,
        )
        save(
            render_playtest_card_back(
                survey_url=arguments.survey_url, bleed=arguments.bleed
            ),
            out / "playtest-card-back.png",
            arguments.pdf,
        )
        module = qr_module_inches(arguments.survey_url, 1.8)
        print(
            f"  QR module {module * 25.4:.2f}mm "
            f"(floor {QR_MIN_MODULE_INCHES * 25.4:.2f}mm) -- "
            f"{arguments.survey_url}"
        )

    if claims.play_minutes is None or claims.minimum_age is None:
        print(
            "note: no playing time or age rating is printed unless "
            "--play-minutes / --min-age are given."
        )


if __name__ == "__main__":
    main()
