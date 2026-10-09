#!/usr/bin/env python3
"""Render the Tethys deck: the icons, the 72 cards and the back, the contact
sheets, and the two print PDFs.

    python3 scripts/render_tethys_deck.py --out tethysdeck/print

Writes under `--out`: `icons/` (every suit mark and piece, transparent
PNG), `cards/` (every card and `back.png`), `icon_sheet.png`,
`might_ladder.png`, `tools_ladder.png`, `fools_ladder.png`, `deck_sheet.png`, `closeup_sheet.png`, and the PDFs
`print_sheet.pdf` (letter, nine a page, crop marks) and `avery_95328.pdf`
(Avery Presta 95328, six a page), each with a backs page after every
fronts page for a duplex print. `--only` picks some of icons, cards,
sheets and pdf. See docs/design/tethys-deck.md.
"""
import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from tethysdeck import icons  # noqa: E402
from tethysdeck.back import back  # noqa: E402
from tethysdeck.cards import closeup_sheet, deck_cards, deck_sheet, ladder_sheet  # noqa: E402
from tethysdeck.deck import SUITS  # noqa: E402
from tethysdeck.print_sheets import PAGE_SIZES, avery_pages, grid_pages, write_pdf  # noqa: E402
from tethysdeck.relief import IconSet  # noqa: E402

STEPS = ("icons", "cards", "sheets", "pdf")
CLOSEUP = [("money", "1"), ("money", "2"), ("might", "Left"), ("fiends", "1"), ("states", "Right"), ("fools", "10")]


def icon_sheet(icon_set: IconSet) -> Image.Image:
    """The twelve suit marks, Fortune over Doom, labelled."""
    cell, gap, label = 256, 24, 36
    img = Image.new("RGB", (6 * cell + 7 * gap, 2 * (cell + label) + 3 * gap), "white")
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(str(icons.FONT), 22)
    for col, suit in enumerate(SUITS):
        for row, fate in enumerate(("fortune", "doom")):
            im = icon_set.mark(suit, fate, cell)
            x, y = gap + col * (cell + gap), gap + row * (cell + label + gap)
            img.paste(im, (x, y), im)
            d.text((x + cell // 2, y + cell + label // 2), f"{suit} {fate}", font=font, fill="#333333", anchor="mm")
    return img


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "tethysdeck" / "print")
    parser.add_argument("--only", default=",".join(STEPS), help="a comma-separated subset of " + ", ".join(STEPS))
    args = parser.parse_args()
    steps = {s.strip() for s in args.only.split(",")}
    unknown = steps - set(STEPS)
    if unknown:
        parser.error(f"unknown step(s): {', '.join(sorted(unknown))}")
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    icon_set = IconSet()

    if "icons" in steps:
        folder = out / "icons"
        folder.mkdir(exist_ok=True)
        for name, image in icon_set.all().items():
            image.save(folder / f"{name}.png")
        print(f"icons: {len(icon_set.all())} -> {folder}")

    cards = None
    back_image = None
    if steps & {"cards", "sheets", "pdf"}:
        cards = deck_cards(icon_set)
        back_image = back(icon_set)
    if "cards" in steps:
        folder = out / "cards"
        folder.mkdir(exist_ok=True)
        for (suit, rank), image in cards.items():
            image.save(folder / f"{suit}_{rank.lower()}.png")
        back_image.save(folder / "back.png")
        print(f"cards: {len(cards)} and the back -> {folder}")
    if "sheets" in steps:
        icon_sheet(icon_set).save(out / "icon_sheet.png")
        ladder_sheet(icon_set, "might").save(out / "might_ladder.png")
        ladder_sheet(icon_set, "tools").save(out / "tools_ladder.png")
        ladder_sheet(icon_set, "fools").save(out / "fools_ladder.png")
        deck_sheet(cards).save(out / "deck_sheet.png")
        closeup_sheet(cards, CLOSEUP).save(out / "closeup_sheet.png")
        print(f"sheets -> {out}")
    if "pdf" in steps:
        ordered = list(cards.values())
        pages = grid_pages(ordered, back_image)
        write_pdf(pages, out / "print_sheet.pdf", PAGE_SIZES["grid"])
        pages[0].save(out / "print_sheet_page1.png")
        pages = avery_pages(ordered, back_image)
        write_pdf(pages, out / "avery_95328.pdf", PAGE_SIZES["avery"])
        pages[0].save(out / "avery_95328_page1.png")
        print(f"pdf: print_sheet.pdf and avery_95328.pdf -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
