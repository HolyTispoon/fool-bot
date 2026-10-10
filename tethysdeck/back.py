"""The card back: white, the double frame over a faint violet lattice, a
ring of the twelve suit marks round an orange dodecagon, and in the
dodecagon the studio's orange Doom d12 (the author, 2026-10-08).

Each suit's Fortune mark sits straight across from its Doom mark and both
point outward, so the back has the same silhouette either way up. Nothing
on it is lettered.
"""
import math

import numpy as np
from PIL import Image, ImageDraw

from d12ball.dice import ORANGE, die_mark
from tethysdeck.cards import H, RADIUS, W
from tethysdeck.deck import SUITS
from tethysdeck.relief import IconSet

VIOLET, ORANGE_INK = "#4A2A78", "#BE5A12"   # Fortune's violet and Doom's orange, as the card faces


def back(icon_set: IconSet) -> Image.Image:
    S = 2
    img = Image.new("RGBA", (W * S, H * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, W * S - 1, H * S - 1), RADIUS * S, fill="#FFFFFF")
    d.rounded_rectangle((18 * S, 18 * S, (W - 19) * S, (H - 19) * S), (RADIUS - 18) * S, outline=VIOLET, width=5 * S)
    d.rounded_rectangle((30 * S, 30 * S, (W - 31) * S, (H - 31) * S), (RADIUS - 30) * S, outline=ORANGE_INK, width=2 * S)

    # A fine lattice of violet diagonals inside the frame, kept light.
    lattice = Image.new("RGBA", (W * S, H * S), (0, 0, 0, 0))
    ld = ImageDraw.Draw(lattice)
    step = 26 * S
    for k in range(-H * S, W * S + H * S, step):
        ld.line([(k, 0), (k + H * S, H * S)], fill=(28, 74, 79, 60), width=S)
        ld.line([(k, H * S), (k + H * S, 0)], fill=(28, 74, 79, 60), width=S)
    mask = Image.new("L", (W * S, H * S), 0)
    ImageDraw.Draw(mask).rounded_rectangle((48 * S, 48 * S, (W - 49) * S, (H - 49) * S), (RADIUS - 48) * S, fill=255)
    lattice.putalpha(Image.fromarray(np.minimum(np.asarray(lattice.getchannel("A")), np.asarray(mask))))
    img.alpha_composite(lattice)

    # The centre: a white disc, an orange dodecagon with a violet one inside it.
    cx, cy = W * S // 2, H * S // 2
    r_disc = 300 * S
    d.ellipse((cx - r_disc, cy - r_disc, cx + r_disc, cy + r_disc), fill="#FFFFFF", outline=VIOLET, width=6 * S)
    r_dodeca = 150 * S
    for r, colour, width in ((r_dodeca, ORANGE_INK, 5 * S), (0.78 * r_dodeca, VIOLET, 3 * S)):
        d.polygon([(cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a))) for a in range(-90, 270, 30)],
                  fill="#FFFFFF" if colour == ORANGE_INK else None, outline=colour, width=width)

    # Twelve marks: a suit's Fortune at angle a, its Doom straight across, each pointing out.
    r_ring, size = 236 * S, 108 * S
    for i, suit in enumerate(SUITS):
        for fate, offset in (("fortune", 0), ("doom", 180)):
            a = -90 + i * 30 + offset
            icon = icon_set.mark(suit, fate, size).rotate(-(a + 90), resample=Image.BICUBIC)
            x = cx + r_ring * math.cos(math.radians(a)) - size // 2
            y = cy + r_ring * math.sin(math.radians(a)) - size // 2
            img.alpha_composite(icon, (round(x), round(y)))

    # The orange Doom die, the darker of the studio's orange pair, in the middle.
    die = die_mark(ORANGE.doom, 190 * S)
    img.alpha_composite(die, (cx - 95 * S, cy - 95 * S))
    return img.resize((W, H), Image.LANCZOS)
