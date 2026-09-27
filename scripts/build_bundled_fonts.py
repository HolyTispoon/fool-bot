#!/usr/bin/env python3
"""Build the bundled Roboto Slab faces every word of the game is set in.

    pip install fonttools ttfautohint-py   # this script's only extra dependencies
    curl -LO 'https://raw.githubusercontent.com/google/fonts/main/apache/robotoslab/RobotoSlab%5Bwght%5D.ttf'
    python3 scripts/build_bundled_fonts.py 'RobotoSlab[wght].ttf'

Writes `d12ball/fonts/RobotoSlab-Regular.ttf` and `RobotoSlab-Bold.ttf`.

**Two static weights cut from the variable font**, 400 and 700, because
`render.load_font` asks for a face by `bold=` and reportlab registers a
file per weight -- neither wants to know about a weight axis.

**The four arrows are DejaVu Sans's, copied in.** Roboto Slab has no
arrows, and text drawn with Pillow does not fall back glyph by glyph:
a missing character prints as a box. The game draws `→` -- on the
maneuver card's field strip, in the shot image's caption, and in the
species sheet's own ability text, which is imported data and cannot be
reworded here -- so the bundled face carries the arrows itself. Both
fonts are TrueType outlines at 2048 units per em, so a glyph copies
across unscaled; each weight takes the arrows of the matching DejaVu
weight. A copied glyph's own hinting instructions are dropped: they
call functions in DejaVu's font program, which the Roboto Slab file
does not carry.

**Then the whole face is hinted with ttfautohint.** Roboto Slab ships
unhinted, and under Pillow's layout an unhinted face sets each letter
at a fractional position that is rounded on its own, so small text
spaces unevenly -- "FOOLSGAMES", "Comp rehensive" at 7 to 11 pixels,
which is the size of a board's smallest labels and of the rulebook
covers on d12ball.com. DejaVu never showed it because it is hinted.
ttfautohint hints up to 200 pixels by default, so the emoji and token
art -- drawn large and scaled down -- moves by an edge pixel here and
there too: rebuild the fonts, then rerun the art scripts, never one
without the other. See "Fonts" in docs/design/board-image.md.
"""
import argparse
import copy
import sys
import tempfile
from pathlib import Path

try:
    from fontTools.ttLib import TTFont
    from fontTools.ttLib.tables import ttProgram
    from fontTools.varLib.instancer import instantiateVariableFont
    from ttfautohint import ttfautohint
except ImportError:  # pragma: no cover - a build tool, not the bot
    sys.exit("This script needs fontTools and ttfautohint: pip install fonttools ttfautohint-py")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FONT_DIR = PROJECT_ROOT / "d12ball" / "fonts"

# Weight -> (output file, the DejaVu face its arrows come from).
WEIGHTS = {
    400: ("RobotoSlab-Regular.ttf", "DejaVuSans.ttf"),
    700: ("RobotoSlab-Bold.ttf", "DejaVuSans-Bold.ttf"),
}
# ← ↑ → ↓
BORROWED = (0x2190, 0x2191, 0x2192, 0x2193)
# The Apache licence asks a modified file to say it was changed; the
# name table's description is where a font says so.
MODIFIED_NOTICE = (
    "Modified for fool-bot: a static instance of the Roboto Slab variable "
    "font, with the arrows U+2190-U+2193 added from DejaVu Sans, hinted "
    "with ttfautohint."
)


def borrow_glyphs(font: TTFont, donor: TTFont, codepoints) -> None:
    if font["head"].unitsPerEm != donor["head"].unitsPerEm:
        raise SystemExit("The donor font's units per em differ; the copy would need scaling.")
    donor_cmap = donor.getBestCmap()
    order = font.getGlyphOrder()
    glyf, hmtx = font["glyf"], font["hmtx"]
    for codepoint in codepoints:
        if codepoint in font.getBestCmap():
            continue
        source = donor_cmap[codepoint]
        glyph = copy.deepcopy(donor["glyf"][source])
        if glyph.isComposite():
            raise SystemExit(f"U+{codepoint:04X} is a composite in the donor; copy its parts first.")
        glyph.program = ttProgram.Program()
        glyph.program.fromBytecode(b"")
        name = f"uni{codepoint:04X}"
        order.append(name)
        glyf[name] = glyph
        hmtx[name] = donor["hmtx"][source]
        for table in font["cmap"].tables:
            if table.isUnicode():
                table.cmap[codepoint] = name
    font.setGlyphOrder(order)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("variable_font", type=Path, help="RobotoSlab[wght].ttf from google/fonts")
    parser.add_argument("--out", type=Path, default=FONT_DIR)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as work:
        for weight, (name, donor_name) in WEIGHTS.items():
            font = instantiateVariableFont(
                TTFont(args.variable_font), {"wght": weight}, updateFontNames=True
            )
            borrow_glyphs(font, TTFont(FONT_DIR / donor_name), BORROWED)
            unhinted = Path(work) / name
            font.save(unhinted)

            hinted = Path(work) / f"hinted-{name}"
            ttfautohint(in_file=str(unhinted), out_file=str(hinted))
            font = TTFont(hinted)
            font["name"].setName(MODIFIED_NOTICE, 10, 3, 1, 0x409)
            path = args.out / name
            font.save(path)
            print(f"wrote {path}")


if __name__ == "__main__":
    main()
