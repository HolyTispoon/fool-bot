#!/usr/bin/env python3
"""The Tethys deck's pieces as photoreal objects, from the local FLUX model.

    python3 scripts/generate_tethys_pieces.py generate [name ...]   # raw renders into tethysdeck/print/pieces/raw/
    python3 scripts/generate_tethys_pieces.py key [name ...]        # keyed onto transparency into tethysdeck/images/
    python3 scripts/generate_tethys_pieces.py sheet                 # a contact sheet of tethysdeck/images/

Each piece is one object on a pure white background -- a sword, a smith's
hammer, a demon mask -- rendered by FLUX.1-schnell through `mflux-generate`
(installed by hand on the author's Mac; a render is a minute or two), then
keyed: the near-white connected to the border is the background, the edge
is feathered and its white fringe un-blended, an elongated piece is stood
upright by its long axis with the end `WIDE_END` names up, and the object
is trimmed and centred on a square with a margin. The keyed PNGs are
committed under `tethysdeck/images/`, named as `icons.icon_name` names a
piece, and `relief.IconSet` takes them over the drawings. Run once, by
hand, like the rulebooks' cover dice -- never per build. See
docs/design/tethys-deck.md, "The pieces are pictures".
"""
import math
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tethysdeck import icons  # noqa: E402
from tethysdeck.relief import PICTURES  # noqa: E402

RAW = ROOT / "tethysdeck" / "print" / "pieces" / "raw"
MFLUX = Path.home() / ".local/bin/mflux-generate"
MODEL = "mflux-community/flux-1-schnell-mflux-q4"

STUDIO = ("isolated on a pure white seamless background, soft diffused studio lighting, "
          "photorealistic product photograph, sharp focus, centered, the whole object in frame "
          "with white margin around it, no shadow on the background, no text, no lettering, "
          "no smoke, no dust, no debris")

# Doom is "ruined or rusty or nasty or deserted or neglected or foul", never broken in two (the author).
RUIN = "ruined, rusted, neglected and foul, grimy and pitted, long abandoned"

# Medieval throughout: "if the weapons are medieval style, so should the tools be" (the author).
SUBJECTS = {
    "might_sword_fortune": "a medieval arming sword standing perfectly vertical with the point up, mirror-polished steel blade with "
                           "a fuller, gilded gold crossguard and round gold pommel, red leather wrapped grip",
    "might_sword_doom": f"a medieval arming sword standing perfectly vertical with the point up, {RUIN}, the steel blade dark, "
                        "pitted and rust-streaked, the crossguard dulled, the leather grip rotten",
    "might_axe_fortune": "a medieval bearded battle axe standing vertical with the head at the top, polished forged steel head with "
                         "a curved edge, plain oak haft with a leather wrapped grip",
    "might_axe_doom": f"a medieval bearded battle axe standing vertical with the head at the top, {RUIN}, the steel head notched "
                      "and rusted, the oak haft grey and weathered",
    "might_sceptre_fortune": "a medieval royal sceptre standing vertical, a gold rod with a faceted knop, a large red ruby set in gold "
                             "prongs at the top, gleaming",
    "might_sceptre_doom": f"a medieval royal sceptre standing vertical with its jewelled head at the top, {RUIN}, the gold "
                          "tarnished black, the ruby at the top dull and cracked",
    "might_crown_fortune": "a medieval royal gold crown with pointed tips topped with pearls, red and teal gemstones round the circlet, "
                           "a deep red velvet cap inside, gleaming",
    "might_crown_doom": f"a medieval royal crown, {RUIN}, the gold tarnished black and dented, gemstones missing from their "
                        "settings, the velvet cap faded and moth-eaten",
    "tools_hammer_fortune": "a medieval blacksmith's forging hammer standing vertical with the head at the top, a heavy hand-forged "
                            "iron head with a flat face and a cross peen, a plain unmarked ash wood haft with a leather strip bound "
                            "round the grip",
    "tools_hammer_doom": f"a medieval blacksmith's forging hammer standing vertical with the head at the top, {RUIN}, the forged "
                         "iron head a crust of rust, the plain wooden haft grey, cracked and weathered",
    "tools_pick_fortune": "a medieval miner's pickaxe standing vertical with the head at the top, a hand-forged iron head with one "
                          "pointed arm and one chisel arm, a plain unmarked ash wood haft",
    "tools_pick_doom": f"a medieval miner's pickaxe standing vertical with the head at the top, {RUIN}, the forged iron head "
                       "rusted through, the plain wooden haft grey and weathered",
    "tools_spade_fortune": "a medieval wooden spade standing vertical with the blade at the bottom and a T-shaped wooden handle at "
                           "the top, a plain unmarked carved oak blade shod with a hand-forged iron edge, a plain ash wood shaft",
    "tools_spade_doom": f"a medieval wooden spade standing vertical with the blade at the bottom and a T-shaped wooden handle at "
                        f"the top, {RUIN}, the carved oak blade grey and rotten, its iron edge rusted, the shaft weathered",
    "tools_anvil_fortune": "a medieval blacksmith's anvil, London pattern, seen from the front and a little above, the horn pointing "
                           "left, a worn bright steel face over a dark hand-forged iron body, a square hardy hole and a round "
                           "pritchel hole in the face",
    "tools_anvil_doom": f"a medieval blacksmith's anvil, London pattern, seen from the front and a little above, the horn pointing "
                        f"left, {RUIN}, deeply rusted all over, the face pitted and dull",
    # The suit marks: the piece name is the suit's own, `might_fortune`.
    "might_fortune": "two medieval arming swords crossed over each other like a letter X, points up, mirror-polished steel "
                     "blades, gilded gold crossguards and round gold pommels, red leather wrapped grips, lying flat on white, "
                     "nothing else",
    "might_doom": f"two medieval arming swords crossed over each other like a letter X, points up, {RUIN}, the steel blades "
                  "dark, pitted and rust-streaked, the crossguards dulled, the leather grips rotten, lying flat on white, "
                  "nothing else",
    "tools_fortune": "a medieval blacksmith's hammer and a pair of long hand-forged iron blacksmith's tongs crossed over each "
                     "other like a letter X, the tongs as long as the hammer, the hammer's plain ash wood haft, lying flat on "
                     "white, nothing else",
    "tools_doom": f"a medieval blacksmith's hammer and a pair of blacksmith's tongs crossed in an X, {RUIN}, the iron a "
                  "crust of rust, the haft grey and weathered, lying flat",
    "fiends_fortune": "a medieval demon mask standing upright on its own, glossy crimson lacquered wood with two long curved "
                      "black horns, a menacing face with narrowed eyes and a small gold jewel on the brow, no string, no tag, "
                      "no label",
    "fiends_doom": f"a medieval demon mask hanging upright, two long curved black horns, {RUIN}, the lacquer blackened and "
                   "flaking, the eyes hollow, the face foul and grimy",
    "states_fortune": "a round stone disc carved with a complete yin-yang symbol facing the camera, the whole symbol visible, "
                      "polished dark green serpentine and white marble inlaid, a raised stone rim, no stand",
    "states_doom": f"a round carved stone yin-yang disc standing upright, {RUIN}, the stone weathered grey and cracked, "
                   "moss and grime in the cracks",
    "fools_fortune": "a jester's cap standing upright with three perky points in purple, red and green velvet, a gold bell on "
                     "each tip, a zigzag gold band round the brim",
    "fools_doom": f"an empty jester's cap lying on its own with no head and no face in it, {RUIN}, the three points sagging "
                  "and drooping, the velvet faded, filthy and moth-eaten, the bells tarnished black",
}
PROMPTS = {name: f"{subject}, {STUDIO}" for name, subject in SUBJECTS.items()}
SEEDS = {name: 1000 + i * 7 for i, name in enumerate(SUBJECTS)}
# Re-rolls: the first ruined hammer was "weird" and the first ruined sword had a wisp at the tip; the first
# ruined sceptre carried debris and stood on its head, the first Tools mark's tongs fell apart, the first
# whole spade was lettered, the first whole disc hid half its symbol on a stand, the first ruined cap had a
# face in it, the first whole demon mask hung from a shop tag; the Might mark was one sword, a sliver in a
# corner, and became two crossed.
SEEDS.update({"might_sword_doom": 4101, "tools_hammer_doom": 4108, "might_sceptre_doom": 5101,               "tools_spade_fortune": 5103, "states_fortune": 5104, "fools_doom": 5105, "fiends_fortune": 5106,
              "tools_fortune": 5107, "might_fortune": 5108, "might_doom": 5109})

# Which end of an elongated piece goes up: its wide end or its narrow end; the rest are left as rendered.
WIDE_END = {"sword": "down", "axe": "up", "sceptre": "up", "hammer": "up", "pick": "up", "spade": "down"}
# Pieces with polished metal in them keep a cautious shadow pass, because a blade's
# highlight is light and unsaturated like a shadow on the backdrop; every other piece's
# soft shadow is keyed loosely, and the backdrop showing through it (between a crown's
# points) is taken as background too.
BRIGHT_METAL = {"might_sword_fortune", "might_sword_doom", "might_axe_fortune", "might_sceptre_fortune", "tools_anvil_fortune",
                "might_fortune", "might_doom", "tools_fortune"}
SENTINEL = (255, 0, 255)


def generate(names):
    RAW.mkdir(parents=True, exist_ok=True)
    for name in names:
        target = RAW / f"{name}.png"
        if target.exists():
            print(f"skip {name}", flush=True)
            continue
        t0 = time.time()
        side = os.environ.get("TETHYS_PIECE_SIDE", "768")
        cmd = [str(MFLUX), "--model", MODEL, "--base-model", "schnell", "--steps", "4", "--width", side, "--height", side,
               "--mlx-cache-limit-gb", "4", "--seed", str(SEEDS[name]), "--prompt", PROMPTS[name], "--output", str(target)]
        print(f"== {name} seed {SEEDS[name]}", flush=True)
        r = subprocess.run(cmd, capture_output=True, text=True)
        if not target.exists():
            print(r.stdout[-1200:], r.stderr[-1200:], flush=True)
        print(f"-- {name}: {'ok' if target.exists() else 'FAILED'} in {time.time() - t0:.0f}s", flush=True)


def background_mask(img, soft_shadow=False):
    """The near-white connected to the border, and the faint shadow next to it.

    The model's "pure white" is sometimes a light grey vignette, so the flood's
    tolerance and the shadow pass follow how white the corners actually are: a
    pure white backdrop keeps them tight (a polished blade's highlight must not
    read as shadow), a grey one loosens them."""
    W, H = img.size
    seeds = [(0, 0), (W - 1, 0), (0, H - 1), (W - 1, H - 1), (W // 2, 0), (W // 2, H - 1), (0, H // 2), (W - 1, H // 2)]
    corner = sum(sum(img.getpixel(seed)) / 3 for seed in seeds) / len(seeds)
    thresh = 18 + 3 * max(0, 250 - corner)
    shadow_lum, shadow_sat = (200, 16) if soft_shadow else (min(236, corner - 6), 12)
    # Nothing brighter than the backdrop's corners is the object's edge, so clamp
    # it to the corner colour and the flood reaches a vignette's white middle too.
    ceiling = np.array([max(img.getpixel(seed)[k] for seed in seeds) for k in range(3)], dtype=np.uint8)
    flood = Image.fromarray(np.minimum(np.asarray(img), ceiling[None, None, :]))
    for seed in seeds:
        if flood.getpixel(seed) != SENTINEL and min(flood.getpixel(seed)) > 200:
            ImageDraw.floodfill(flood, seed, SENTINEL, thresh=thresh)
    bg = np.all(np.asarray(flood) == SENTINEL, axis=-1)
    rgb = np.asarray(img).astype(float)
    shadowish = (rgb.mean(axis=-1) > shadow_lum) & (rgb.max(axis=-1) - rgb.min(axis=-1) < shadow_sat)
    for _ in range(60 if soft_shadow else 24):
        ring = np.asarray(Image.fromarray(bg.astype(np.uint8) * 255).filter(ImageFilter.MaxFilter(3))) > 0
        new = ring & shadowish & ~bg
        if not new.any():
            break
        bg |= new
    if soft_shadow:
        bg |= holes(img, bg, corner)
    return bg


def holes(img, bg, corner):
    """Backdrop enclosed by the piece -- seen between a crown's points -- which no
    flood from the border reaches: a flat, light, unsaturated patch the colour of
    the corners. A pearl is light too, but shaded, so its spread gives it away."""
    rgb = np.asarray(img).astype(float)
    lum = rgb.mean(axis=-1)
    candidate = (lum > corner - 14) & (rgb.max(axis=-1) - rgb.min(axis=-1) < 10) & ~bg
    label = Image.fromarray(candidate.astype(np.uint8) * 255)
    found = np.zeros_like(bg)
    for _ in range(400):
        ys, xs = np.nonzero(np.asarray(label) == 255)
        if len(ys) == 0:
            break
        ImageDraw.floodfill(label, (int(xs[0]), int(ys[0])), 128)
        patch = np.asarray(label) == 128
        if patch.sum() >= 120 and lum[patch].std() < 7:
            found |= patch
        arr = np.asarray(label).copy()
        arr[patch] = 0
        label = Image.fromarray(arr)
    return found


def upright(im, wide_end):
    """Turn an elongated RGBA piece so its long axis is vertical, its wide end where asked."""
    a = np.asarray(im)[..., 3] > 128
    ys, xs = np.nonzero(a)
    if len(xs) < 100:
        return im
    vals, vecs = np.linalg.eigh(np.cov(np.vstack([xs - xs.mean(), ys - ys.mean()])))
    if math.sqrt(vals[1] / max(vals[0], 1e-6)) < 1.6:
        return im
    vx, vy = vecs[:, 1]
    im = im.rotate(math.degrees(math.atan2(vy, vx)) - 90, resample=Image.BICUBIC, expand=True)
    a = np.asarray(im)[..., 3] > 128
    rows = np.nonzero(a.any(axis=1))[0]
    top, bottom = rows[0], rows[-1]
    span = bottom - top
    widths = a.sum(axis=1)
    wide_is_up = widths[top:top + int(span * 0.4)].max() > widths[bottom - int(span * 0.4):bottom + 1].max()
    if (wide_end == "up") != wide_is_up:
        im = im.rotate(180)
    return im


def key(path, wide_end=None, soft_shadow=False, size=1024):
    img = Image.open(path).convert("RGB")
    bg = background_mask(img, soft_shadow)
    rgb = np.asarray(img).astype(float)
    alpha = np.asarray(Image.fromarray(((~bg) * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.8))).astype(float) / 255
    a = np.clip(alpha, 0.02, 1)[..., None]
    obj = np.clip((rgb - (1 - a) * 255) / a, 0, 255)                 # un-blend the white fringe
    im = Image.fromarray(np.dstack([obj, alpha * 255]).astype(np.uint8), "RGBA")
    if wide_end:
        im = upright(im, wide_end)
    im = im.crop(Image.fromarray((np.asarray(im)[..., 3] > 25).astype(np.uint8) * 255).getbbox())
    side = int(max(im.size) * 1.12)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(im, ((side - im.width) // 2, (side - im.height) // 2))
    return canvas.resize((size, size), Image.LANCZOS)


def wide_end_for(name):
    parts = name.split("_")
    return WIDE_END.get(parts[1]) if len(parts) == 3 else None


def key_all(names):
    PICTURES.mkdir(parents=True, exist_ok=True)
    for name in names:
        raw = RAW / f"{name}.png"
        if not raw.exists():
            print(f"no raw render for {name}", flush=True)
            continue
        key(raw, wide_end_for(name), name not in BRIGHT_METAL).save(PICTURES / f"{name}.png", optimize=True)
        print(f"keyed {name} -> {PICTURES / (name + '.png')}", flush=True)


def sheet(out):
    names = [n for n in SUBJECTS if (PICTURES / f"{n}.png").exists()]
    font = ImageFont.truetype(str(icons.FONT), 20)
    cell, gap, label, cols = 240, 16, 28, 6
    rows = (len(names) + cols - 1) // cols
    img = Image.new("RGB", (cols * cell + (cols + 1) * gap, rows * (cell + label) + (rows + 1) * gap), "white")
    d = ImageDraw.Draw(img)
    for i, name in enumerate(names):
        im = Image.open(PICTURES / f"{name}.png").convert("RGBA").resize((cell, cell), Image.LANCZOS)
        x, y = gap + (i % cols) * (cell + gap), gap + (i // cols) * (cell + label + gap)
        img.paste(im, (x, y), im)
        d.text((x + cell // 2, y + cell + label // 2), name, font=font, fill="#333333", anchor="mm")
    img.save(out)
    print(f"sheet -> {out}")


if __name__ == "__main__":
    what, names = (sys.argv[1] if len(sys.argv) > 1 else "sheet"), sys.argv[2:] or list(SUBJECTS)
    if what == "generate":
        generate(names)
    elif what == "key":
        key_all(names)
    elif what == "sheet":
        sheet(ROOT / "tethysdeck" / "print" / "pieces_sheet.png")
    else:
        raise SystemExit(__doc__)
