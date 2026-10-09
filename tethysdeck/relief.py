"""The drawn symbols lit as embossed metal: the drawing's own colours, its
alpha as a height map (a bevel at the edge, a dome over the whole), its ink
lines sunk into recesses, lit from the top left with a specular glint.
Fortune is lit brighter than Doom. The shapes are `icons.py`'s.
"""
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from tethysdeck import icons
from tethysdeck.deck import VARIANTS

BIG = icons.SIZE

GOLD = {
    "fortune": {"base": (232, 184, 62), "recess": (96, 66, 14), "spec": (255, 250, 215), "ambient": 0.38},
    "doom": {"base": (176, 136, 52), "recess": (52, 36, 10), "spec": (240, 215, 150), "ambient": 0.30},
}


LIGHT = {
    "fortune": {"spec": (255, 250, 230), "ambient": 0.46, "spec_gain": 0.9},
    "doom": {"spec": (235, 215, 190), "ambient": 0.36, "spec_gain": 0.6},
}


def emboss(suit: str, fate: str, size: int = 512, variant: str | None = None) -> Image.Image:
    """The icon's own colours, lit as a relief: its alpha is the height, its ink lines the recesses."""
    colour_img = icons.render(suit, fate, variant=variant)
    mask_img = icons.render(suit, fate, mask=True, variant=variant)
    colour = np.asarray(colour_img).astype(float) / 255
    mask = np.asarray(mask_img).astype(float) / 255
    alpha = colour[..., 3]
    fillness = mask[..., 0] * mask[..., 3]        # 1 on a raised part, 0 on an engraved line
    height = alpha * (0.45 + 0.55 * fillness)
    h = Image.fromarray((height * 255).astype(np.uint8), "L").filter(ImageFilter.GaussianBlur(BIG / 70))
    height = np.asarray(h).astype(float) / 255
    plateau = np.clip(height * 1.35 - 0.1, 0, 1)
    dome = Image.fromarray((alpha * 255).astype(np.uint8), "L").filter(ImageFilter.GaussianBlur(BIG / 22))
    dome = np.asarray(dome).astype(float) / 255
    height = plateau * 0.7 + dome * 0.6 * alpha
    rng = np.random.default_rng(7)
    grain = Image.fromarray((rng.random((BIG, BIG)) * 255).astype(np.uint8), "L").filter(ImageFilter.GaussianBlur(1.2))
    height = height + (np.asarray(grain).astype(float) / 255 - 0.5) * 0.03 * alpha
    dy, dx = np.gradient(height)
    k = 40.0
    nx, ny, nz = -dx * k, -dy * k, np.ones_like(height)
    norm = np.sqrt(nx * nx + ny * ny + nz * nz)
    nx, ny, nz = nx / norm, ny / norm, nz / norm
    lx, ly, lz = -0.55, -0.6, 0.6
    ln = (lx * lx + ly * ly + lz * lz) ** 0.5
    lx, ly, lz = lx / ln, ly / ln, lz / ln
    diffuse = np.clip(nx * lx + ny * ly + nz * lz, 0, 1)
    hx, hy, hz = lx, ly, lz + 1
    hn = (hx * hx + hy * hy + hz * hz) ** 0.5
    spec = np.clip(nx * hx / hn + ny * hy / hn + nz * hz / hn, 0, 1) ** 24
    p = LIGHT[fate]
    shade = p["ambient"] + (1 - p["ambient"]) * diffuse
    rgb = colour[..., :3] * shade[..., None] + (np.array(p["spec"]) / 255)[None, None, :] * spec[..., None] * p["spec_gain"] * fillness[..., None]
    yy = np.linspace(1.0, 0.0, BIG)[:, None]
    rgb = rgb * (0.9 + 0.2 * yy)[..., None]
    rgb = np.clip(rgb, 0, 1)
    img = Image.fromarray((np.dstack([rgb, alpha]) * 255).astype(np.uint8), "RGBA")
    return img.resize((size, size), Image.LANCZOS)


def sheet(images, out):
    font = ImageFont.truetype(str(icons.FONT), 22)
    cell, gap, label = 256, 24, 36
    cols, rows = 5, 2
    img = Image.new("RGB", (cols * cell + (cols + 1) * gap, rows * (cell + label) + (rows + 1) * gap), "#FFFFFF")
    d = ImageDraw.Draw(img)
    suits = ["might", "fiends", "tools", "states", "fools"]
    for name, icon in images.items():
        suit, fate = name.split("_")
        x = gap + suits.index(suit) * (cell + gap)
        y = gap + (0 if fate == "fortune" else 1) * (cell + label + gap)
        small = icon.resize((cell, cell), Image.LANCZOS)
        img.paste(small, (x, y), small)
        d.text((x + cell // 2, y + cell + label // 2), f"{suit} {fate}", font=font, fill="#333333", anchor="mm")
    img.save(out)




class IconSet:
    """Every picture a card needs, rendered once and kept: a suit's mark and
    its pieces, embossed (Money's are the coin's faces, left as they are)."""

    def __init__(self):
        self._images: dict[str, Image.Image] = {}

    def image(self, suit: str, fate: str, variant: str | None = None) -> Image.Image:
        name = icons.icon_name(suit, variant, fate)
        if name not in self._images:
            if suit == "money":
                self._images[name] = icons.render(suit, fate)
            else:
                self._images[name] = emboss(suit, fate, size=icons.SIZE, variant=variant)
        return self._images[name]

    def mark(self, suit: str, fate: str, size: int) -> Image.Image:
        """The suit's own symbol, for a corner or the back."""
        return self.image(suit, fate).resize((size, size), Image.LANCZOS)

    def piece(self, suit: str, value: int, fate: str, size: int) -> Image.Image:
        """The piece worth `value` in this suit, at `size` pixels."""
        variant = VARIANTS.get(suit, {}).get(value)
        return self.image(suit, fate, variant).resize((size, size), Image.LANCZOS)

    def all(self) -> dict[str, Image.Image]:
        """Every icon by name, for writing out as PNGs."""
        for suit, variant, fate in icons.every_icon():
            self.image(suit, fate, variant)
        return dict(self._images)
