"""The drawn symbols lit as the stuff they are made of -- steel, gold, wood,
leather, gem, velvet, stone, cloth -- the way the coin art is lit.

Each drawing is rendered three times at `icons.py`'s size: in its colours,
as a mask (white parts, black ink lines) and as a material map (one grey
per material, from `MATERIAL_OF`). The height of every part rises from its
edge by its material's profile, scaled to the part's own width -- so a
blade is a ridge, a haft a half-round, a block a bevelled slab -- with
each material's surface on top (hammered dents and grain on metal, streaks
on wood, mottling on stone) and the whole thing bowed a little. The ink
lines are the grooves between parts, coloured as their neighbours and
darkened. Then the normals are lit from the top left: metals reflect an
environment (sky above, ground below, a bright horizon) and glint; the
rest are matte with a soft sheen; gems glow at their rims; velvet lights
at grazing angles. Doom is lit lower, its gold tarnished and Tools' steel
rusted. Money is not lit here: its pieces are the coins themselves.
"""
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from tethysdeck import icons
from tethysdeck.deck import VARIANTS

WORK = 2048              # the lighting's working resolution
SQ2 = 2 ** 0.5

# What each colour key in `icons.COLOURS` is made of.
MATERIAL_OF = {
    "blade": "steel", "edge": "steel", "shine": "steel", "steel": "steel", "shade": "steel", "wrench": "steel", "face": "steel",
    "guard": "gold", "guard2": "gold", "pommel": "gold", "band": "gold", "bell": "gold", "spark": "gold", "bolt": "gold",
    "wood": "wood", "grain": "wood",
    "grip": "leather", "rubber": "leather",
    "gem": "gem", "gem2": "gem", "eye": "gem",
    "velvet": "velvet", "pearl": "pearl",
    "horn": "horn", "fang": "bone",
    "dark": "stone", "light": "stone",
    "red": "cloth", "green": "cloth", "purple": "cloth", "white": "cloth",
}
MATERIALS = ["steel", "gold", "wood", "leather", "gem", "velvet", "pearl", "lacquer", "horn", "bone", "stone", "cloth", "paint"]

# How each material's height rises from a part's edge: the profile, how far
# in it reaches (px at WORK) and how high (as a share of the reach).
SHAPE = {
    "steel": ("ridge", 44, 0.42), "gold": ("round", 34, 0.85), "wood": ("round", 30, 0.95), "leather": ("round", 30, 0.9),
    "gem": ("round", 60, 0.95), "velvet": ("round", 90, 0.6), "pearl": ("round", 40, 1.0), "lacquer": ("round", 120, 0.5),
    "horn": ("round", 40, 0.9), "bone": ("round", 30, 0.9), "stone": ("bevel", 36, 0.5), "cloth": ("round", 60, 0.6),
    "paint": ("bevel", 30, 0.4),
}

LIGHT = {
    "fortune": {"L": (-0.5, -0.65, 0.57), "sky": (0.96, 0.975, 1.0), "horizon": (0.98, 0.95, 0.88), "ground": (0.30, 0.28, 0.27),
                "ambient": 0.40, "spec": (1.0, 1.0, 1.0), "gain": 1.0},
    "doom": {"L": (-0.5, -0.65, 0.57), "sky": (0.66, 0.62, 0.60), "horizon": (0.62, 0.55, 0.48), "ground": (0.10, 0.09, 0.09),
             "ambient": 0.42, "spec": (0.92, 0.86, 0.80), "gain": 0.8},
}


def material_of(suit, key):
    if suit == "fiends" and key == "face":
        return "lacquer"
    return MATERIAL_OF.get(key, "paint")


class MaterialPalette(dict):
    """A grey per material in place of each colour, so one render says what every pixel is made of."""

    def __init__(self, suit):
        super().__init__()
        self.suit = suit

    def __getitem__(self, key):
        if key == "ink":
            return (0, 0, 0, 255)
        i = MATERIALS.index(material_of(self.suit, key)) + 1
        return (i * 16, i * 16, i * 16, 255)


def chamfer(inside):
    """Each inside pixel's distance to the nearest outside one (chamfer 1, sqrt 2; two sweeps)."""
    H, W = inside.shape
    d = np.where(inside, 1e6, 0.0)
    j = np.arange(W, dtype=float)
    jr = (W - 1) - j

    def sweep(row):
        row = np.minimum(row, j + np.minimum.accumulate(row - j))
        return np.minimum(row, jr + np.minimum.accumulate((row - jr)[::-1])[::-1])

    for i in range(H):
        row = d[i]
        if i:
            prev = d[i - 1]
            row = np.minimum(row, prev + 1)
            row[1:] = np.minimum(row[1:], prev[:-1] + SQ2)
            row[:-1] = np.minimum(row[:-1], prev[1:] + SQ2)
        d[i] = sweep(row)
    for i in range(H - 1, -1, -1):
        row = d[i]
        if i < H - 1:
            nxt = d[i + 1]
            row = np.minimum(row, nxt + 1)
            row[1:] = np.minimum(row[1:], nxt[:-1] + SQ2)
            row[:-1] = np.minimum(row[:-1], nxt[1:] + SQ2)
        d[i] = sweep(row)
    return d


def local_max(a, w):
    """The maximum over a (2w+1)-square window round each pixel, separably (van Herk)."""
    def along_rows(x):
        k = 2 * w + 1
        H, W = x.shape
        pad = (-(W + 2 * w)) % k
        xp = np.pad(x, ((0, 0), (w, w + pad)), mode="edge")
        blocks = xp.reshape(H, xp.shape[1] // k, k)
        prefix = np.maximum.accumulate(blocks, axis=2).reshape(H, -1)
        suffix = np.maximum.accumulate(blocks[:, :, ::-1], axis=2)[:, :, ::-1].reshape(H, -1)
        return np.maximum(suffix[:, :W], prefix[:, k - 1:k - 1 + W])
    return along_rows(along_rows(a).T).T


def _box(a, w, axis):
    """The mean over a window of 2w+1 along one axis, edges held."""
    pad = [(0, 0), (0, 0)]
    pad[axis] = (w, w)
    c = np.cumsum(np.pad(a, pad, mode="edge"), axis=axis)
    c = np.concatenate([np.zeros_like(np.take(c, [0], axis=axis)), c], axis=axis)
    n, k = a.shape[axis], 2 * w + 1
    return (np.take(c, np.arange(k, k + n), axis=axis) - np.take(c, np.arange(0, n), axis=axis)) / k


def blur(a, radius):
    """About a Gaussian blur of `radius` sigma: three box blurs, separably."""
    w = max(int(round(((4 * radius * radius + 1) ** 0.5 - 1) / 2)), 1)
    out = a.astype(float)
    for _ in range(3):
        out = _box(_box(out, w, 0), w, 1)
    return out


def noise(rng, radius, stretch_y=1):
    """Smooth noise, zero mean, about 0.17 deviation; `stretch_y` > 1 pulls it into vertical streaks."""
    n = rng.random((max(WORK // stretch_y, 8), WORK))
    if stretch_y > 1:
        n = np.asarray(Image.fromarray((n * 255).astype(np.uint8), "L").resize((WORK, WORK), Image.BICUBIC)).astype(float) / 255
    a = blur(n, radius)
    a -= a.mean()
    return a / (a.std() or 1) * 0.17


_TEXTURES = {}


def textures():
    """The surfaces, made once: fine grain, hammered dents, wood streaks, mottling."""
    if not _TEXTURES:
        rng = np.random.default_rng(11)
        _TEXTURES["t"] = (noise(rng, 1.1), noise(rng, 7), noise(rng, 1.4, stretch_y=24), noise(rng, 3.5))
    return _TEXTURES["t"]


def smoothstep(x):
    x = np.clip(x, 0, 1)
    return x * x * (3 - 2 * x)


def unit(v):
    v = np.asarray(v, float)
    return v / np.linalg.norm(v)


def emboss(suit: str, fate: str, size: int = 512, variant: str | None = None) -> Image.Image:
    """The drawing lit as what it is made of, `size` pixels square."""
    R = WORK
    colour = np.asarray(icons.render(suit, fate, variant=variant, size=R)).astype(float) / 255
    mask = np.asarray(icons.render(suit, fate, mask=True, variant=variant, size=R)).astype(float) / 255
    mat = np.asarray(icons.render(suit, fate, variant=variant, palette=MaterialPalette(suit), size=R, resample=Image.NEAREST))
    alpha = colour[..., 3]
    albedo = colour[..., :3]
    inside = mask[..., 0] * mask[..., 3] > 0.5          # a part, rather than ink or outside
    silhouette = alpha > 0.5

    # What each pixel is made of: a weight per material, soft at the seams; the
    # grooves take their neighbours' stuff, and their colour darkened.
    allowed = np.array(sorted({MATERIALS.index(material_of(suit, k)) + 1
                               for k in icons.COLOURS.get(suit, {}).get(fate, {}) if k != "ink"}) or [MATERIALS.index("paint") + 1])
    nearest = np.argmin(np.abs(mat[..., 0].astype(np.int16)[..., None] - (allowed * 16).astype(np.int16)[None, None, :]), axis=-1)
    idx = allowed[nearest] * (mat[..., 3] > 127)
    present = [m for m in MATERIALS if (idx == MATERIALS.index(m) + 1).any()]
    cover = np.maximum(blur(inside.astype(float), 6), 1e-3)
    weights = {}
    for m in present:
        own = (idx == MATERIALS.index(m) + 1).astype(float) * inside
        weights[m] = np.where(inside, blur(own, 1.2), blur(own, 6) / cover)
    total = np.maximum(sum(weights.values()), 1e-3)
    weights = {m: w / total for m, w in weights.items()}
    filled = np.dstack([blur(albedo[..., k] * inside, 6) for k in range(3)]) / cover[..., None]
    albedo = np.where(inside[..., None], albedo, filled * 0.55)

    # The height: each part rises from its edge by its material's profile, scaled
    # to the part's own width, with the material's surface on it; every part bows
    # a little, and the whole thing sits on a soft dome.
    d_part = chamfer(inside)
    fine, hammered, streaks, mottle = textures()
    height = np.zeros((R, R))
    for m in present:
        profile, cap, amp = SHAPE[m]
        reach = np.clip(local_max(np.minimum(d_part, cap * 3), cap), 2.0, cap)
        r = np.clip(d_part / reach, 0, 1)
        if profile == "ridge":
            h = r * reach * amp
        elif profile == "round":
            h = np.sqrt(np.clip(1 - (1 - r) ** 2, 0, 1)) * reach * amp
        else:
            h = smoothstep(r) * reach * amp
        if m == "steel":
            h = h + fine * 0.5 + hammered * 1.8
        elif m == "gold":
            h = h + fine * 1.2 + hammered * 3.4
        elif m == "wood":
            h = h + streaks * 2.0 + fine * 0.4
        elif m == "leather":
            h = h + mottle * 1.6 + fine * 0.6
        elif m == "stone":
            h = h + mottle * 3.0 + fine * 1.2
        elif m == "cloth":
            h = h + fine * 0.8
        else:
            h = h + fine * 0.2
        height += weights[m] * h
    height = blur((height + blur(inside.astype(float), 22) * 5.0) * inside, 1.0)
    small = Image.fromarray((silhouette * 255).astype(np.uint8), "L").resize((R // 4, R // 4), Image.BOX)
    dome = blur(np.asarray(small).astype(float) / 255, 10)
    dome = np.asarray(Image.fromarray((dome * 255).astype(np.uint8), "L").resize((R, R), Image.BILINEAR)).astype(float) / 255
    height = height + dome * 6.0 * alpha

    # The normals, and the light: diffuse, a glint, and the environment a polished
    # surface reflects -- sky above, ground below, a bright horizon.
    gy, gx = np.gradient(height)
    nz = 1 / np.sqrt(gx * gx + gy * gy + 1)
    nx, ny = -gx * nz, -gy * nz
    p = LIGHT[fate]
    L = unit(p["L"])
    Hh = unit(L + np.array([0, 0, 1.0]))
    diffuse = np.clip(nx * L[0] + ny * L[1] + nz * L[2], 0, 1)[..., None]
    ndoth = np.clip(nx * Hh[0] + ny * Hh[1] + nz * Hh[2], 0, 1)
    ry = 2 * nz * ny
    t = np.clip(0.5 - 0.5 * ry, 0, 1)
    sky, horizon, ground = (np.array(p[k]) for k in ("sky", "horizon", "ground"))
    env = ground[None, None, :] + (sky - ground)[None, None, :] * t[..., None]
    hw = np.exp(-(ry / 0.14) ** 2)
    env = env * (1 - 0.3 * hw[..., None]) + horizon[None, None, :] * (0.3 * hw)[..., None]
    env = env * (1 - 0.18 * np.clip(nx, 0, 1))[..., None]
    fresnel = (1 + 1.4 * (1 - nz) ** 3)[..., None]
    ao = (1 - np.clip((blur(height, 9) - height) * 0.12, 0, 0.6))[..., None]
    spec_col = np.array(p["spec"])
    amb = p["ambient"]
    fine3, hammered3, streaks3, mottle3 = (x[..., None] for x in (fine, hammered, streaks, mottle))
    rim = (1 - nz)[..., None]

    def glint(shin, gain, colour=spec_col):
        return colour * (ndoth ** shin * gain)[..., None]

    def matte(a):
        return a * (amb + (1 - amb) * diffuse)

    rgb = np.zeros((R, R, 3))
    for m in present:
        a = albedo
        if m == "steel":
            tarnish, rusty = fate == "doom", fate == "doom" and suit == "tools"
            if rusty:
                c = a * (0.55 + 0.55 * diffuse) + a * env * (0.12 * fresnel) + glint(10, 0.08)
                c = c * (1 + mottle3 * 0.6 + fine3 * 0.45)
            elif tarnish:
                c = (a * (0.4 + 0.42 * diffuse) + a * env * (0.42 * fresnel) + glint(30, 0.35)) * (1 + fine3 * 0.05)
            else:
                c = (a * (0.2 + 0.34 * diffuse) + a * env * (0.72 * fresnel) + glint(70, 0.95)) * (1 + fine3 * 0.05)
        elif m == "gold":
            tarnish = fate == "doom"
            tint = np.clip(a * 1.25, 0, 1)
            c = a * ((0.42 if tarnish else 0.3) + 0.4 * diffuse) + tint * env * ((0.45 if tarnish else 0.7) * fresnel)
            c = (c + glint(*((24, 0.3) if tarnish else (44, 0.7)), colour=np.array((1.0, 0.95, 0.8)))) * (1 + fine3 * 0.1)
        elif m == "gem":
            c = a * (0.42 + 0.58 * diffuse) + np.clip(a * 1.7 + 0.1, 0, 1) * env * 0.3 + glint(90, 1.0) + a * 0.35 * rim
        elif m == "velvet":
            c = a * (0.28 + 0.5 * diffuse) + np.clip(a * 1.5, 0, 1) * 0.55 * rim ** 1.4
        elif m == "pearl":
            c = a * (0.55 + 0.45 * diffuse) + glint(10, 0.4) + env * 0.2
        elif m == "lacquer":
            c = matte(a) + glint(50, 0.6) + a * env * 0.15
        elif m == "horn":
            c = (matte(a) + glint(30, 0.35)) * (1 + streaks3 * 0.5)
        elif m == "bone":
            c = matte(a) + glint(24, 0.25)
        elif m == "wood":
            c = (matte(a) + glint(18, 0.14)) * (1 + streaks3 * 0.55 + fine3 * 0.1)
        elif m == "leather":
            c = (matte(a) + glint(12, 0.12)) * (1 + mottle3 * 0.3 + fine3 * 0.15)
        elif m == "stone":
            c = (matte(a) + glint(16, 0.1)) * (1 + mottle3 * 0.5 + fine3 * 0.35)
        elif m == "cloth":
            c = (matte(a) + glint(8, 0.06)) * (1 + fine3 * 0.18)
        else:
            c = matte(a) + glint(20, 0.2)
        rgb += weights[m][..., None] * c
    rgb = np.clip(rgb * ao * p["gain"] ** 0.4, 0, 1)
    img = Image.fromarray((np.dstack([rgb, alpha]) * 255).astype(np.uint8), "RGBA")
    return img.resize((size, size), Image.LANCZOS)


def sheet(images, out):
    font = ImageFont.truetype(str(icons.FONT), 22)
    cell, gap, label = 256, 24, 36
    cols, rows = 5, 2
    img = Image.new("RGB", (cols * cell + (cols + 1) * gap, rows * (cell + label) + (rows + 1) * gap), "#FFFFFF")
    d = ImageDraw.Draw(img)
    suits = ["tools", "might", "fiends", "states", "fools"]
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
    its pieces, lit (Money's are the coin's faces, left as they are)."""

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
