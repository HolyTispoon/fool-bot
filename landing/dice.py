"""
A d12 as a shaded solid resting on a table, for the studio page.

A dodecahedron resting on one face, seen from above at a table angle:
bevelled edges, a key and a fill light, a specular highlight, numerals
on every visible face (engraved or painted), a soft contact shadow, and
the finishes of a resin die -- the light coming through it, the swirl
poured into it, and the shine of a polished face. Prophetic Folly's
dice are three `DicePair`s, `ORANGE`, `TEAL` and `PURPLE`;
`landing/build.py` composes the still the studio page's card shows from
them and the bot's coins.

Written for the landing-page sketch the author reviewed (2026-09-27)
as `scripts/render_landing_dice.py` and moved here with its output
unchanged; the resin finishes came after, when the author asked for
dice like the ones they play with. A die with none of them draws what
the sketch's did, pixel for pixel. Nothing in the game reads it, and it
shades per pixel with numpy. See docs/design/landing-pages.md, "The
studio page".
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from d12ball.render import FONT_DIR

FONT = FONT_DIR / "DejaVuSans-Bold.ttf"
SS = 2  # supersample

# The window a shiny die mirrors (view space: overhead and a little to
# the left, where the top face -- the face the die shows -- reflects),
# how far off its centre a reflection still catches it, how soft its
# edge is, how far away the eye is in the die's own units, and the
# share of sheen at a grazing edge.
SHINE_WINDOW = np.array([-0.3, 0.95, 0.1]) / np.linalg.norm([-0.3, 0.95, 0.1])
SHINE_WINDOW_EDGE = 0.965
SHINE_WINDOW_SOFTNESS = 0.02
SHINE_EYE_DISTANCE = 5.0
SHINE_GRAZING = 0.35


@dataclass(frozen=True)
class Die:
    """How one die looks: its body and numerals, the face it shows, how
    it is turned on the table, and its finish."""
    body: tuple[int, int, int]
    numeral: tuple[int, int, int]
    top_face_value: int
    yaw_deg: float
    engraved: bool
    spec_power: float
    spec_strength: float
    gloss_tint: tuple[int, int, int] | None = None
    # Translucent resin: light that passes through the die glows in
    # `glow`, most on the faces turned from the light and along the
    # silhouette, where the body is thinnest. None is an opaque die.
    glow: tuple[int, int, int] | None = None
    glow_strength: float = 0.0
    # How far the body's colour swirls, as in a resin poured in two
    # shades: 0 is one flat colour. The swirl is the same on every build.
    swirl: float = 0.0
    # A polished die: how strongly it mirrors a soft window above and to
    # the left of the table, a highlight that slides across each face as
    # the angle to the eye changes, with a sheen at the grazing edges.
    # 0 is a die that mirrors nothing.
    shine: float = 0.0


# The dice are pairs of resin d12s, after the orange pair the author
# plays with (a photo, 2026-09-27): a bright Fortune, shiny, with white
# numerals, showing 12, and a dark Doom swirled with a lighter shade,
# with gold numerals, showing 1. The author asked for three pairs --
# orange, teal and purple -- and for the bright one to shine.
WHITE = (255, 255, 255)
GOLD = (236, 184, 76)


@dataclass(frozen=True)
class DicePair:
    fortune: Die
    doom: Die


def resin_pair(bright, bright_glow, dark, dark_glow, yaws) -> DicePair:
    """A Fortune and a Doom in one colour: `bright` and `dark` are the
    bodies, each glow the light that comes through that body, and `yaws`
    how each die is turned on the table."""
    fortune_yaw, doom_yaw = yaws
    return DicePair(
        fortune=Die(bright, WHITE, 12, fortune_yaw, False, 90, 1.1,
                    gloss_tint=WHITE, glow=bright_glow, glow_strength=0.35,
                    shine=0.8),
        doom=Die(dark, GOLD, 1, doom_yaw, False, 60, 0.7,
                 gloss_tint=(235, 235, 245), glow=dark_glow, glow_strength=0.3,
                 swirl=0.7),
    )


ORANGE = resin_pair((255, 128, 30), (255, 196, 110), (118, 42, 14), (214, 104, 30), (30, -20))
TEAL = resin_pair((40, 232, 216), (190, 255, 246), (12, 74, 76), (38, 150, 146), (18, -31))
PURPLE = resin_pair((176, 104, 255), (226, 196, 255), (52, 20, 86), (128, 70, 190), (5, -45))


def dodecahedron():
    phi = (1 + 5 ** 0.5) / 2
    a, b = 1.0, 1.0 / phi
    verts = []
    for x in (-a, a):
        for y in (-a, a):
            for z in (-a, a):
                verts.append((x, y, z))
    for i in (-b, b):
        for j in (-phi, phi):
            verts += [(0, i, j), (i, j, 0), (j, 0, i)]
    verts = np.array(verts, dtype=float)
    # The faces are the groups of five vertices sharing a plane, found
    # from the normals of the twelve face centres (the icosahedron's
    # directions).
    dirs = []
    for i in (-1, 1):
        for j in (-1, 1):
            dirs += [(0, i * phi, j), (i * phi, j, 0), (j, 0, i * phi)]
    faces = []
    for d in dirs:
        n = np.array(d, dtype=float)
        n /= np.linalg.norm(n)
        dots = verts @ n
        idx = np.where(dots > dots.max() - 1e-6)[0]
        assert len(idx) == 5, len(idx)
        c = verts[idx].mean(axis=0)
        # order the five around the centre
        u = verts[idx[0]] - c
        u /= np.linalg.norm(u)
        v = np.cross(n, u)
        ang = [math.atan2((verts[k] - c) @ v, (verts[k] - c) @ u) for k in idx]
        order = [k for _, k in sorted(zip(ang, idx))]
        faces.append((n, order))
    return verts, faces


def rot_x(t):
    c, s = math.cos(t), math.sin(t)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def rot_z(t):
    c, s = math.cos(t), math.sin(t)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def align(a, b):
    """Rotation taking unit vector a onto unit vector b."""
    v = np.cross(a, b)
    s = np.linalg.norm(v)
    c = a @ b
    if s < 1e-9:
        return np.eye(3) if c > 0 else -np.eye(3)
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + vx + vx @ vx * ((1 - c) / s ** 2)


def swirl_field(span: int) -> np.ndarray:
    """Broad streaks in [-1, 1] across a `span` square: seeded noise,
    coarse, stretched along a diagonal and blurred, so a resin's swirl
    is the same picture on every build."""
    noise = np.random.default_rng(12).random((span // 48, span // 48))
    field = Image.fromarray((noise * 255).astype(np.uint8)).resize(
        (span, span // 5), Image.Resampling.BICUBIC,
    ).resize((span, span), Image.Resampling.BICUBIC).rotate(35, resample=Image.Resampling.BICUBIC)
    field = field.filter(ImageFilter.GaussianBlur(span / 60))
    values = np.array(field, dtype=float) / 255.0
    values = (values - values.mean()) / (values.std() + 1e-9)
    return np.clip(values / 2, -1, 1)


def render_die(die: Die, size: int, elev_deg: float = 52) -> Image.Image:
    """`die` as a `size`-pixel RGBA square, its shadow included."""
    verts, faces = dodecahedron()
    # rest a face on the table: face 0 is the bottom
    R = align(faces[0][0], np.array([0, 0, -1.0]))
    R = rot_z(math.radians(die.yaw_deg)) @ R
    verts_w = verts @ R.T
    normals_w = [R @ n for n, _ in faces]
    # the camera looks down at `elev`: view space is the world turned
    # by -elev about x, so +z (world up) leans toward the viewer
    elev = math.radians(elev_deg)
    V = rot_x(-(math.pi / 2 - elev))
    verts_v = verts_w @ V.T
    normals_v = [V @ n for n in normals_w]
    light = np.array([-0.55, 0.65, 0.9])
    light /= np.linalg.norm(light)  # view space
    fill = np.array([0.7, -0.2, 0.6])
    fill /= np.linalg.norm(fill)
    view = np.array([0, 0, 1.0])
    half = light + view
    half /= np.linalg.norm(half)

    span = size * SS
    extent = np.abs(verts_v[:, :2]).max()
    scale = span * 0.36 / extent
    cx, cy = span / 2, span / 2 - span * 0.03

    def to_screen(p):
        return (cx + p[0] * scale, cy - p[1] * scale)

    body_rgb = np.array(die.body, dtype=float)
    num_rgb = np.array(die.numeral, dtype=float)
    img = np.zeros((span, span, 4), dtype=float)
    yy, xx = np.mgrid[0:span, 0:span].astype(float)
    swirl = swirl_field(span) if die.swirl else None

    # the face values: the top-most face shows the die's value, the
    # bottom face its opposite, and the rest the others in turn
    top_i = int(np.argmax([n[2] for n in normals_w]))
    values = {}
    pool = [v for v in range(1, 13) if v not in (die.top_face_value, 13 - die.top_face_value)]
    for i in range(12):
        if i == top_i:
            values[i] = die.top_face_value
        elif i == 0:
            values[i] = 13 - die.top_face_value
        else:
            values[i] = pool.pop(0)

    def mirrored(n, nrm, centre):
        """How much of the window a face shows at each pixel: the eye is
        a finite distance away, so the reflected ray turns across a flat
        face and the highlight has an edge rather than one flat tone."""
        x = (xx - cx) / scale
        y = (cy - yy) / scale
        z = (n @ centre - n[0] * x - n[1] * y) / n[2]
        to_eye = np.stack([-x, -y, SHINE_EYE_DISTANCE - z], axis=2)
        to_eye /= np.linalg.norm(to_eye, axis=2, keepdims=True)
        facing = np.sum(nrm * to_eye, axis=2, keepdims=True)
        reflected = 2 * facing * nrm - to_eye
        along = reflected @ SHINE_WINDOW
        window = np.clip((along - SHINE_WINDOW_EDGE) / SHINE_WINDOW_SOFTNESS, 0, 1) ** 2
        grazing = (1 - np.clip(facing[..., 0], 0, 1)) ** 3
        return window + SHINE_GRAZING * grazing

    for fi, (n0, order) in enumerate(faces):
        n = normals_v[fi]
        if n[2] <= 0.02:
            continue
        pts = [to_screen(verts_v[k]) for k in order]
        mask_im = Image.new("L", (span, span), 0)
        ImageDraw.Draw(mask_im).polygon(pts, fill=255)
        mask = np.array(mask_im, dtype=float) / 255.0
        if mask.sum() == 0:
            continue
        # bevel: distance to the nearest edge, and which neighbour it borders
        bevel_w = span * 0.028
        best_d = np.full((span, span), 1e9)
        best_nb = np.zeros((span, span, 3))
        for e in range(5):
            a = np.array(pts[e])
            b = np.array(pts[(e + 1) % 5])
            ab = b - a
            L2 = ab @ ab
            t = ((xx - a[0]) * ab[0] + (yy - a[1]) * ab[1]) / L2
            t = np.clip(t, 0, 1)
            px = a[0] + t * ab[0]
            py = a[1] + t * ab[1]
            d = np.hypot(xx - px, yy - py)
            # the neighbour face across this edge shares both vertices
            va, vb = order[e], order[(e + 1) % 5]
            nb = None
            for fj, (_, o2) in enumerate(faces):
                if fj != fi and va in o2 and vb in o2:
                    nb = normals_v[fj]
                    break
            upd = d < best_d
            best_d = np.where(upd, d, best_d)
            for c in range(3):
                best_nb[..., c] = np.where(upd, nb[c], best_nb[..., c])
        t = np.clip(1 - best_d / bevel_w, 0, 1) ** 1.6 * 0.55
        nrm = n[None, None, :] * (1 - t[..., None]) + best_nb * t[..., None]
        nrm /= np.linalg.norm(nrm, axis=2, keepdims=True)
        diff = np.clip(nrm @ light, 0, 1)
        fil = np.clip(nrm @ fill, 0, 1)
        spec = np.clip(nrm @ half, 0, 1) ** die.spec_power
        # softer inner shading: faces darken slightly toward their edges
        shade = 0.30 + 0.62 * diff + 0.18 * fil
        col = body_rgb[None, None, :] * shade[..., None]
        if die.swirl:
            # the lighter streaks run toward the glow's colour, the
            # darker ones deepen the body
            lighter = np.clip(swirl, 0, 1) * die.swirl
            darker = np.clip(-swirl, 0, 1) * die.swirl
            streak = np.array(die.glow or die.body, dtype=float)[None, None, :] * shade[..., None]
            col = col * (1 - lighter[..., None]) + streak * lighter[..., None]
            col = col * (1 - 0.5 * darker[..., None])
        if die.glow is not None:
            through = die.glow_strength * (0.35 + 0.65 * (1 - diff)) * (0.6 + 0.8 * t)
            col = col * (1 - through[..., None]) + np.array(die.glow, dtype=float)[None, None, :] * through[..., None]
        tint = np.array(die.gloss_tint if die.gloss_tint else (255, 250, 240), dtype=float)
        col = col + tint[None, None, :] * (spec * die.spec_strength)[..., None]
        if die.shine:
            col = col + tint[None, None, :] * (die.shine * mirrored(n, nrm, verts_v[order].mean(axis=0)))[..., None]

        # the numeral, engraved or painted, mapped affinely onto the face
        c3 = verts_v[order].mean(axis=0)
        u3 = verts_v[order[0]] - c3
        u3 -= (u3 @ n) * n
        u3 /= np.linalg.norm(u3)
        v3 = np.cross(n, u3)
        inr = min(
            np.linalg.norm((verts_v[order[e]] + verts_v[order[(e + 1) % 5]]) / 2 - c3)
            for e in range(5)
        )
        # a face-local image, L pixels square for 2 * inr
        L = 400
        loc = Image.new("L", (L, L), 0)
        d = ImageDraw.Draw(loc)
        txt = str(values[fi])
        fs = 200 if len(txt) == 1 else 170
        f = ImageFont.truetype(str(FONT), fs)
        bb = d.textbbox((0, 0), txt, font=f)
        d.text(((L - (bb[2] - bb[0])) / 2 - bb[0], (L - (bb[3] - bb[1])) / 2 - bb[1]), txt, font=f, fill=255)
        if txt in ("6", "9"):
            d.line([(L / 2 - 45, L * 0.80), (L / 2 + 45, L * 0.80)], fill=255, width=14)
        # local pixel -> 3D: p = c3 + ((px-L/2)/(L/2))*inr*u3 - ((py-L/2)/(L/2))*inr*v3,
        # and screen = to_screen(p). M is that, local to screen; Pillow
        # wants its inverse.
        k = inr / (L / 2)
        sx_u, sy_u = u3[0] * k * scale, -u3[1] * k * scale
        sx_v, sy_v = -v3[0] * k * scale, v3[1] * k * scale
        c_s = to_screen(c3)
        M = np.array([[sx_u, sx_v, c_s[0] - (L / 2) * (sx_u + sx_v)],
                      [sy_u, sy_v, c_s[1] - (L / 2) * (sy_u + sy_v)],
                      [0, 0, 1]])
        Mi = np.linalg.inv(M)
        num_mask = loc.transform(
            (span, span), Image.Transform.AFFINE, data=tuple(Mi[:2].ravel()),
            resample=Image.Resampling.BICUBIC,
        )
        nm = np.array(num_mask, dtype=float) / 255.0 * mask
        if die.engraved:
            # cut: darker, with a thin lit lip offset away from the light
            lip = np.array(
                num_mask.transform((span, span), Image.Transform.AFFINE, (1, 0, 2.5 * SS, 0, 1, 2.5 * SS)),
                dtype=float,
            ) / 255.0 * mask
            lip = np.clip(lip - nm, 0, 1)
            col = col * (1 - nm[..., None] * 0.55) + num_rgb[None, None, :] * (nm * 0.55 * shade)[..., None]
            col = col + (255 - col) * (lip * 0.35)[..., None]
        else:
            col = col * (1 - nm[..., None]) + (num_rgb[None, None, :] * (0.55 + 0.5 * shade)[..., None]) * nm[..., None]
        img[..., :3] = np.where(mask[..., None] > 0, col, img[..., :3])
        img[..., 3] = np.maximum(img[..., 3], mask * 255)

    # the silhouette's edge, darkened
    alpha = Image.fromarray(np.clip(img[..., 3], 0, 255).astype(np.uint8))
    eroded = alpha.filter(ImageFilter.MinFilter(int(4 * SS) | 1))
    rim = (np.array(alpha, dtype=float) - np.array(eroded, dtype=float)) / 255.0
    if die.glow is None:
        img[..., :3] *= (1 - rim * 0.35)[..., None]
    else:
        # a translucent die's edge is where the light comes through
        glow_rgb = np.array(die.glow, dtype=float)[None, None, :]
        img[..., :3] += (glow_rgb - img[..., :3]) * (rim * die.glow_strength)[..., None]

    rendered = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8), "RGBA")
    # the contact shadow on the table: an ellipse under the die, offset
    # from the light
    sh = Image.new("L", (span, span), 0)
    ys = [p[1] for f in faces for p in [to_screen(verts_v[k]) for k in f[1]]]
    xs = [p[0] for f in faces for p in [to_screen(verts_v[k]) for k in f[1]]]
    w = max(xs) - min(xs)
    bottom = max(ys)
    ImageDraw.Draw(sh).ellipse(
        [cx - w * 0.52 + span * 0.03, bottom - w * 0.22, cx + w * 0.52 + span * 0.03, bottom + w * 0.10],
        fill=190,
    )
    sh = sh.filter(ImageFilter.GaussianBlur(span * 0.035))
    shadow = Image.new("RGBA", (span, span), (0, 0, 0, 0))
    shadow.putalpha(sh)
    out = Image.alpha_composite(shadow, rendered)
    return out.resize((size, size), Image.Resampling.LANCZOS)
