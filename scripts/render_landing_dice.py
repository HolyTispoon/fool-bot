"""Render a d12 as a shaded solid resting on a table.

A dodecahedron resting on one face, seen from above at a table angle:
bevelled edges, a key and a fill light, a specular highlight, numerals
on every visible face (engraved into a light die, painted on a dark
one) and a soft contact shadow. Written for the landing-page sketch
(docs/landing-pages.md, 2026-09-27) to draw the Fortune and Doom dice
on the studio page; step 4 of that worksheet moves it under landing/.

    python3 scripts/render_landing_dice.py <out dir>

writes die-fortune-real.png (bone, showing 12) and die-doom-real.png
(obsidian, showing 1). Nothing in the game reads it.
"""
import math
import sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

import os
FONT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "d12ball", "fonts", "DejaVuSans-Bold.ttf")
SS = 2  # supersample


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
    # faces: groups of 5 vertices sharing a plane; find via normals of
    # the 12 face centres (the icosahedron directions)
    dirs = []
    for i in (-1, 1):
        for j in (-1, 1):
            dirs += [(0, i * phi, j), (i * phi, j, 0), (j, 0, i * phi)]
    faces = []
    for d in dirs:
        n = np.array(d, dtype=float); n /= np.linalg.norm(n)
        dots = verts @ n
        idx = np.where(dots > dots.max() - 1e-6)[0]
        assert len(idx) == 5, len(idx)
        c = verts[idx].mean(axis=0)
        # order the five around the centre
        u = verts[idx[0]] - c; u /= np.linalg.norm(u)
        v = np.cross(n, u)
        ang = [math.atan2((verts[k] - c) @ v, (verts[k] - c) @ u) for k in idx]
        order = [k for _, k in sorted(zip(ang, idx))]
        faces.append((n, order))
    return verts, faces


def rot_x(t):
    c, s = math.cos(t), math.sin(t)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def rot_y(t):
    c, s = math.cos(t), math.sin(t)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def rot_z(t):
    c, s = math.cos(t), math.sin(t)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def align(a, b):
    """Rotation taking unit vector a onto unit vector b."""
    v = np.cross(a, b); s = np.linalg.norm(v); c = a @ b
    if s < 1e-9:
        return np.eye(3) if c > 0 else -np.eye(3)
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + vx + vx @ vx * ((1 - c) / s ** 2)


def render(size, body, numeral, top_face_value, yaw_deg, engraved,
           spec_power, spec_strength, out_path, elev_deg=52, gloss_tint=None):
    verts, faces = dodecahedron()
    # rest a face on the table: pick face 0 as the bottom
    R = align(faces[0][0], np.array([0, 0, -1.0]))
    R = rot_z(math.radians(yaw_deg)) @ R
    verts_w = verts @ R.T
    normals_w = [R @ n for n, _ in faces]
    # camera: looks down at elev; view space = rotate world by -elev about x
    elev = math.radians(elev_deg)
    V = rot_x(-(math.pi / 2 - elev))  # tilt so +z(world up) leans toward viewer
    verts_v = verts_w @ V.T
    normals_v = [V @ n for n in normals_w]
    light = np.array([-0.55, 0.65, 0.9]); light /= np.linalg.norm(light)  # view space
    fill = np.array([0.7, -0.2, 0.6]); fill /= np.linalg.norm(fill)
    view = np.array([0, 0, 1.0])
    half = light + view; half /= np.linalg.norm(half)

    span = size * SS
    extent = np.abs(verts_v[:, :2]).max()
    scale = span * 0.36 / extent
    cx, cy = span / 2, span / 2 - span * 0.03

    def to_screen(p):
        return (cx + p[0] * scale, cy - p[1] * scale)

    body_rgb = np.array(body, dtype=float)
    num_rgb = np.array(numeral, dtype=float)
    img = np.zeros((span, span, 4), dtype=float)
    yy, xx = np.mgrid[0:span, 0:span].astype(float)

    # the face values: bottom face 0 gets 13-top; top-most gets top value
    top_i = int(np.argmax([n[2] for n in normals_w]))
    values = {}
    pool = [v for v in range(1, 13) if v not in (top_face_value, 13 - top_face_value)]
    for i in range(12):
        if i == top_i:
            values[i] = top_face_value
        elif i == 0:
            values[i] = 13 - top_face_value
        else:
            values[i] = pool.pop(0)

    font = ImageFont.truetype(FONT, 200)
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
        # bevel: distance to nearest edge, and which neighbour it borders
        bevel_w = span * 0.028
        best_d = np.full((span, span), 1e9)
        best_nb = np.zeros((span, span, 3))
        for e in range(5):
            a = np.array(pts[e]); b = np.array(pts[(e + 1) % 5])
            ab = b - a; L2 = ab @ ab
            t = ((xx - a[0]) * ab[0] + (yy - a[1]) * ab[1]) / L2
            t = np.clip(t, 0, 1)
            px = a[0] + t * ab[0]; py = a[1] + t * ab[1]
            d = np.hypot(xx - px, yy - py)
            # neighbour face across this edge: shares both vertices
            va, vb = order[e], order[(e + 1) % 5]
            nb = None
            for fj, (_, o2) in enumerate(faces):
                if fj != fi and va in o2 and vb in o2:
                    nb = normals_v[fj]; break
            upd = d < best_d
            best_d = np.where(upd, d, best_d)
            for c in range(3):
                best_nb[..., c] = np.where(upd, nb[c], best_nb[..., c])
        t = np.clip(1 - best_d / bevel_w, 0, 1) ** 1.6 * 0.55
        nrm = n[None, None, :] * (1 - t[..., None]) + best_nb * t[..., None]
        nrm /= np.linalg.norm(nrm, axis=2, keepdims=True)
        diff = np.clip(nrm @ light, 0, 1)
        fil = np.clip(nrm @ fill, 0, 1)
        spec = np.clip(nrm @ half, 0, 1) ** spec_power
        # softer inner shading: faces darken slightly toward their edges
        shade = 0.30 + 0.62 * diff + 0.18 * fil
        col = body_rgb[None, None, :] * shade[..., None]
        tint = np.array(gloss_tint if gloss_tint else (255, 250, 240), dtype=float)
        col = col + tint[None, None, :] * (spec * spec_strength)[..., None]

        # numeral, engraved or painted, mapped affinely onto the face
        c3 = verts_v[order].mean(axis=0)
        u3 = verts_v[order[0]] - c3; u3 -= (u3 @ n) * n; u3 /= np.linalg.norm(u3)
        v3 = np.cross(n, u3)
        inr = min(np.linalg.norm(((verts_v[order[e]] + verts_v[order[(e + 1) % 5]]) / 2 - c3)) for e in range(5))
        # face-local image: 400px square = 2*inr
        L = 400
        loc = Image.new("L", (L, L), 0)
        d = ImageDraw.Draw(loc)
        txt = str(values[fi])
        fs = 200 if len(txt) == 1 else 170
        f = ImageFont.truetype(FONT, fs)
        bb = d.textbbox((0, 0), txt, font=f)
        d.text(((L - (bb[2] - bb[0])) / 2 - bb[0], (L - (bb[3] - bb[1])) / 2 - bb[1]), txt, font=f, fill=255)
        if txt in ("6", "9"):
            d.line([(L / 2 - 45, L * 0.80), (L / 2 + 45, L * 0.80)], fill=255, width=14)
        # local px -> 3D: p = c3 + ((px-L/2)/(L/2))*inr*u3 - ((py-L/2)/(L/2))*inr*v3
        # screen = to_screen(p). Build forward affine M (local->screen), invert for PIL.
        k = inr / (L / 2)
        sx_u, sy_u = u3[0] * k * scale, -u3[1] * k * scale
        sx_v, sy_v = -v3[0] * k * scale, v3[1] * k * scale
        c_s = to_screen(c3)
        # screen = c_s + (px-L/2)*(sx_u, sy_u) + (py-L/2)*(sx_v, sy_v)
        M = np.array([[sx_u, sx_v, c_s[0] - (L / 2) * (sx_u + sx_v)],
                      [sy_u, sy_v, c_s[1] - (L / 2) * (sy_u + sy_v)],
                      [0, 0, 1]])
        Mi = np.linalg.inv(M)
        num_mask = loc.transform((span, span), Image.AFFINE, data=tuple(Mi[:2].ravel()), resample=Image.BICUBIC)
        nm = np.array(num_mask, dtype=float) / 255.0 * mask
        if engraved:
            # cut: darker, with a thin lit lip offset away from the light
            lip = np.array(num_mask.transform((span, span), Image.AFFINE, (1, 0, 2.5 * SS, 0, 1, 2.5 * SS)), dtype=float) / 255.0 * mask
            lip = np.clip(lip - nm, 0, 1)
            col = col * (1 - nm[..., None] * 0.55) + num_rgb[None, None, :] * (nm * 0.55 * shade)[..., None]
            col = col + (255 - col) * (lip * 0.35)[..., None]
        else:
            col = col * (1 - nm[..., None]) + (num_rgb[None, None, :] * (0.55 + 0.5 * shade)[..., None]) * nm[..., None]
        img[..., :3] = np.where(mask[..., None] > 0, col, img[..., :3])
        img[..., 3] = np.maximum(img[..., 3], mask * 255)

    # silhouette edge darkening (object edge)
    alpha = Image.fromarray(np.clip(img[..., 3], 0, 255).astype(np.uint8))
    eroded = alpha.filter(ImageFilter.MinFilter(int(4 * SS) | 1))
    rim = (np.array(alpha, dtype=float) - np.array(eroded, dtype=float)) / 255.0
    img[..., :3] *= (1 - rim * 0.35)[..., None]

    die = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8), "RGBA")
    # contact shadow on the table: an ellipse under the die, offset from the light
    sh = Image.new("L", (span, span), 0)
    ys = [p[1] for f in faces for p in [to_screen(verts_v[k]) for k in f[1]]]
    xs = [p[0] for f in faces for p in [to_screen(verts_v[k]) for k in f[1]]]
    w = (max(xs) - min(xs)); bottom = max(ys)
    ImageDraw.Draw(sh).ellipse([cx - w * 0.52 + span * 0.03, bottom - w * 0.22, cx + w * 0.52 + span * 0.03, bottom + w * 0.10], fill=190)
    sh = sh.filter(ImageFilter.GaussianBlur(span * 0.035))
    shadow = Image.new("RGBA", (span, span), (0, 0, 0, 0)); shadow.putalpha(sh)
    out = Image.alpha_composite(shadow, die)
    out = out.resize((size, size), Image.LANCZOS)
    out.save(out_path)
    print("wrote", out_path)


if __name__ == "__main__":
    out = sys.argv[1]
    # Fortune: bone-ivory, engraved umber numerals, a soft satin sheen
    render(640, (236, 226, 204), (58, 44, 30), 12, 18, True, 26, 0.35, f"{out}/die-fortune-real.png")
    # Doom: obsidian, painted bone numerals, hard glossy highlight
    render(640, (26, 22, 20), (232, 220, 196), 1, -31, False, 60, 0.85, f"{out}/die-doom-real.png", gloss_tint=(200, 215, 235))
