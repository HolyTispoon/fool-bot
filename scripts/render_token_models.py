#!/usr/bin/env python3
"""Turn the condition-token art into 3D-printable, double-sided tokens.

Three tokens, each a different piece of art on each face:

    exhaust          the amber ZZZ triangle  /  the same triangle in Cyborg teal
    exhausted        EXHAUSTED (blue)        /  INJURED (red)
    drained          DRAINED (teal)          /  DAMAGED (amber)

    python3 scripts/render_token_models.py --out /tmp/tokens
    python3 scripts/render_token_models.py --out /tmp/tokens --size 20 --thickness 3

It writes three ways to print each token into `--out`, and a README.txt
that says which is which and how to slice it:

- `<token>.3mf` -- **one piece, flush faces**, for a printer that changes
  filament by itself (an AMS, an MMU, a tool changer). One object of three
  parts: the black body, and a coloured inlay `--inlay` deep in each face.
  The slicer asks nothing but which filament each part gets, and the
  colours are already on the parts.
- `<token>_body.stl`, `_top.stl`, `_bottom.stl` -- the same three parts,
  for a slicer that won't take the 3MF. Load them together as one object.
- `<token>_half_<side>.stl` -- **two halves, raised art**, for a printer
  with one filament. Each half is a black slab with its art standing
  `--relief` proud of it: pause at the height the README gives, swap to
  the colour, finish, and glue the two halves back to back.

**The art is the bot's own**, traced rather than redrawn: the triangle is
`exhaust.png` itself, and the four words are `render_condition_tokens.py`
run with two changes the plastic needs and the PNG does not (below). A
coach reading a line in Discord, a coach at the printed jumbotron and a
coach picking up a token see one icon. Nothing here is a rule.

**What the plastic changes about the square art.** At the size a token has
to be, the PNG's ring is about 0.4 mm wide -- one extrusion line from a
0.4 mm nozzle, which a slicer drops or prints ragged -- and a sunburst ray
is thinner still. So the square tokens are traced from a re-render with
the ring and the black edge widened to `MIN_FEATURE` and the rays taken
out. The word, which is what a coach reads, is untouched. The triangle's
ring and Zs are already wide enough and are traced as they are.

**The bottom face is mirrored** in the one-piece token, because it is seen
from underneath: flipped over its own vertical axis, the art on it reads
the right way round. The triangle flips point-down to point-down.

**Why `--size` defaults to 19 mm.** The jumbotron's token supplies are
silos `SILO_INCHES` wide (`d12ball/boards.py`, 0.8 in = 20.3 mm) -- a
silo is a token wide -- so a token has to sit inside one with a little
room. Printing bigger means reprinting the jumbotron's silos to match.

Needs what the bot does not: `pip install numpy scikit-image shapely
trimesh manifold3d mapbox-earcut`. Nothing printed is tested (CLAUDE.md);
it is checked by `--preview`, which draws both faces as the slicer will
see them, and by looking.
"""
import argparse
import sys
import zipfile
from functools import reduce
from pathlib import Path

import manifold3d
import numpy as np
import trimesh
from PIL import Image, ImageDraw
from shapely import affinity
from shapely.geometry import MultiPolygon, Polygon
from skimage import measure

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import recolor_exhaust_token  # noqa: E402
import render_condition_tokens  # noqa: E402

EXHAUST_PNG = render_condition_tokens.EMOJI_DIR / "exhaust.png"

# The narrowest thing a face may carry: two lines from a 0.4 mm nozzle.
# One line is printable but is the first thing a slicer drops, and a
# ring that prints on one side of the token and not the other is worse
# than a slightly heavier ring.
MIN_FEATURE = 0.8

# The body is one colour for every token -- the art's own near-black.
BODY_COLOR = (10, 10, 10)

# Each token: (top face, bottom face). A face is the art to trace and
# the colour its accent prints in. The body is black on both.
TOKENS = {
    "exhaust": (
        ("exhaust", recolor_exhaust_token.SOURCE_AMBER),
        ("exhaust_cyborg", recolor_exhaust_token.TARGET_TEAL),
    ),
    "exhausted": (
        ("exhausted", render_condition_tokens.TOKENS["exhausted"][1][:3]),
        ("injured", render_condition_tokens.TOKENS["injured"][1][:3]),
    ),
    "drained": (
        ("drained", render_condition_tokens.TOKENS["drained"][1][:3]),
        ("damaged", render_condition_tokens.TOKENS["damaged"][1][:3]),
    ),
}

# How much the square tokens' colour is thickened after tracing. Nine
# condensed letters across a 19 mm face give EXHAUSTED stems of about
# 0.4 mm -- a fifth of its colour under one nozzle line. Half a tenth of
# a millimetre each way takes that under 1% and narrows the black between
# the letters by next to nothing, which is measured, not guessed: the
# script prints both.
BOLDEN = 0.05

# A speck smaller than this after tracing is antialiasing, not art.
SPECK_MM2 = 0.02
# How far a traced outline may move to lose vertices: a hundredth of the
# finest nozzle anyone prints a token with.
SIMPLIFY_MM = 0.01


def square_art(name: str, size_mm: float) -> tuple[Image.Image, tuple]:
    """A condition token re-rendered for plastic: wide ring, no rays."""
    module = render_condition_tokens
    word, accent = module.TOKENS[name]
    badge_fraction = 1 - 2 * module.MARGIN
    minimum = MIN_FEATURE / size_mm * badge_fraction
    saved = (
        module.RAY_COUNT, module.RING_WIDTH, module.EDGE_WIDTH, module.TEXT_WIDTH
    )
    module.RAY_COUNT = 0
    module.RING_WIDTH = max(module.RING_WIDTH, minimum)
    module.EDGE_WIDTH = max(module.EDGE_WIDTH, minimum)
    # The PNG's word runs into its ring, which its black halo breaks.
    # In plastic that break is a sliver, so the word is kept inside the
    # face with a gap of its own either side.
    face = 1 - 2 * (module.MARGIN + module.EDGE_WIDTH + module.RING_WIDTH)
    module.TEXT_WIDTH = min(module.TEXT_WIDTH, face - 2 * minimum)
    try:
        image = module.render_token(word, accent)
    finally:
        (
            module.RAY_COUNT, module.RING_WIDTH, module.EDGE_WIDTH, module.TEXT_WIDTH
        ) = saved
    return image, module.FACE_COLOR[:3]


def triangle_art(name: str) -> tuple[Image.Image, tuple]:
    """The exhaustion triangle, amber off the file, teal by recolour."""
    ink = recolor_exhaust_token.SOURCE_INK
    if name == "exhaust":
        return Image.open(EXHAUST_PNG).convert("RGBA"), ink
    return (
        recolor_exhaust_token.recolor(
            EXHAUST_PNG,
            ink,
            recolor_exhaust_token.SOURCE_AMBER,
            recolor_exhaust_token.TARGET_TEAL,
        ),
        ink,
    )


def masks(image: Image.Image, ink: tuple, accent: tuple) -> tuple:
    """The token's silhouette, and where on it the accent colour is.

    A pixel is accent when it sits past halfway along the line from the
    art's ink to its accent -- the same reading the recolour script
    makes, which is what carries an antialiased edge to the right side.
    """
    pixels = np.asarray(image, dtype=float)
    alpha = pixels[..., 3] / 255
    axis = np.array(accent, dtype=float) - np.array(ink, dtype=float)
    along = (pixels[..., :3] - np.array(ink, dtype=float)) @ axis / (axis @ axis)
    return alpha >= 0.5, (along >= 0.5) & (alpha >= 0.5)


def trace(mask: np.ndarray, mm_per_px: float, center: tuple) -> MultiPolygon:
    """A pixel mask as polygons in millimetres, y up, centred on `center`.

    Nested contours (a letter's counter, the ring's inside) are folded
    even-odd, so a hole is whatever an odd number of outlines encloses.
    """
    padded = np.pad(mask.astype(float), 1)
    rings = []
    for contour in measure.find_contours(padded, 0.5):
        rows, cols = contour[:, 0] - 1, contour[:, 1] - 1
        xs = (cols - center[0]) * mm_per_px
        ys = (center[1] - rows) * mm_per_px
        ring = Polygon(np.column_stack([xs, ys])).buffer(0)
        if ring.area > 0:
            rings.append(ring)
    shape = reduce(lambda a, b: a.symmetric_difference(b), rings, Polygon())
    shape = shape.simplify(SIMPLIFY_MM).buffer(0)
    parts = shape.geoms if hasattr(shape, "geoms") else [shape]
    return MultiPolygon(
        [p for p in parts if isinstance(p, Polygon) and p.area >= SPECK_MM2]
    )


def face(name: str, accent: tuple, size_mm: float) -> tuple:
    """(silhouette, accent) for one face, `size_mm` across."""
    if name in ("exhaust", "exhaust_cyborg"):
        image, ink = triangle_art(name)
    else:
        image, ink = square_art(name, size_mm)
    outline_mask, accent_mask = masks(image, ink, accent)
    rows, cols = np.nonzero(outline_mask)
    width_px = cols.max() - cols.min() + 1
    center = ((cols.max() + cols.min()) / 2, (rows.max() + rows.min()) / 2)
    mm_per_px = size_mm / width_px
    outline = trace(outline_mask, mm_per_px, center)
    accent_shape = trace(accent_mask, mm_per_px, center)
    if name not in ("exhaust", "exhaust_cyborg"):
        accent_shape = accent_shape.buffer(BOLDEN, join_style=2).intersection(outline)
    return outline, accent_shape


def thinnest_loss(shape: MultiPolygon, width: float) -> float:
    """How much of `shape` is narrower than `width`, as a share of it."""
    opened = shape.buffer(-width / 2).buffer(width / 2)
    return (shape.area - opened.area) / shape.area if shape.area else 0.0


def extrude(shape, bottom: float, top: float) -> manifold3d.Manifold:
    """A prism of `shape` from `bottom` to `top`, as a solid manifold3d
    can add and cut exactly -- holes and all, filled even-odd."""
    parts = shape.geoms if hasattr(shape, "geoms") else [shape]
    contours = []
    for polygon in parts:
        contours.append(np.asarray(polygon.exterior.coords)[:-1])
        contours += [np.asarray(hole.coords)[:-1] for hole in polygon.interiors]
    section = manifold3d.CrossSection(contours, manifold3d.FillRule.EvenOdd)
    return section.extrude(top - bottom).translate((0, 0, bottom))


def to_mesh(solid: manifold3d.Manifold) -> trimesh.Trimesh:
    mesh = solid.to_mesh()
    return trimesh.Trimesh(
        vertices=np.asarray(mesh.vert_properties)[:, :3],
        faces=np.asarray(mesh.tri_verts),
    )


def one_piece(outline, top_art, bottom_art, thickness, inlay) -> dict:
    """Body and two inlays that fill it exactly, faces flush."""
    bottom_art = affinity.scale(bottom_art, xfact=-1, origin=(0, 0))
    top_art = top_art.intersection(outline)
    bottom_art = bottom_art.intersection(outline)
    top = extrude(top_art, thickness - inlay, thickness)
    bottom = extrude(bottom_art, 0, inlay)
    body = extrude(outline, 0, thickness) - top - bottom
    return {"body": to_mesh(body), "top": to_mesh(top), "bottom": to_mesh(bottom)}


def half(outline, art, slab, relief) -> trimesh.Trimesh:
    """A black slab with the art standing proud: swap filament at `slab`."""
    art = art.intersection(outline)
    return to_mesh(extrude(outline, 0, slab) + extrude(art, slab, slab + relief))


def hex_color(rgb) -> str:
    return "#{:02X}{:02X}{:02X}FF".format(*rgb)


def write_3mf(path: Path, name: str, parts: list) -> None:
    """One object whose components are the parts, each with its colour.

    Components rather than separate build items is what makes PrusaSlicer,
    Bambu Studio and OrcaSlicer load the parts as one object instead of
    three to be arranged apart on the plate.
    """
    materials = "".join(
        f'<base name="{label}" displaycolor="{hex_color(rgb)}"/>'
        for label, rgb, _ in parts
    )
    objects = []
    for index, (label, _, mesh) in enumerate(parts):
        vertices = "".join(
            f'<vertex x="{x:.4f}" y="{y:.4f}" z="{z:.4f}"/>' for x, y, z in mesh.vertices
        )
        triangles = "".join(
            f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in mesh.faces
        )
        objects.append(
            f'<object id="{index + 2}" type="model" name="{label}" pid="1" '
            f'pindex="{index}"><mesh><vertices>{vertices}</vertices>'
            f"<triangles>{triangles}</triangles></mesh></object>"
        )
    whole = len(parts) + 2
    components = "".join(
        f'<component objectid="{index + 2}"/>' for index in range(len(parts))
    )
    model = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<model unit="millimeter" xml:lang="en-US" '
        'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
        f'<metadata name="Title">{name}</metadata>'
        f'<resources><basematerials id="1">{materials}</basematerials>'
        + "".join(objects)
        + f'<object id="{whole}" type="model" name="{name}">'
        f"<components>{components}</components></object></resources>"
        f'<build><item objectid="{whole}"/></build></model>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
        "</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Target="/3D/3dmodel.model" Id="rel0" '
        'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
        "</Relationships>"
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("3D/3dmodel.model", model)


def preview(path: Path, faces: list, size_mm: float) -> None:
    """Every face as the plastic will have it, side by side, 40 px/mm."""
    scale, pad = 40, 2.0
    cell = int((size_mm + 2 * pad) * scale)
    sheet = Image.new("RGB", (cell * len(faces), cell), (255, 255, 255))
    pen = ImageDraw.Draw(sheet)

    def draw(shape, fill, hole_fill, offset):
        parts = shape.geoms if hasattr(shape, "geoms") else [shape]
        for polygon in parts:
            points = lambda ring: [
                (offset + (x + size_mm / 2 + pad) * scale, (size_mm / 2 + pad - y) * scale)
                for x, y in ring.coords
            ]
            pen.polygon(points(polygon.exterior), fill=fill)
            for hole in polygon.interiors:
                pen.polygon(points(hole), fill=hole_fill)

    for index, (outline, art, color) in enumerate(faces):
        draw(outline, BODY_COLOR, (255, 255, 255), index * cell)
        draw(art, tuple(color), BODY_COLOR, index * cell)
    sheet.save(path)


def write_stl(mesh: trimesh.Trimesh, path: Path) -> None:
    mesh.export(path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--size", type=float, default=19.0, help="mm across (default 19)")
    parser.add_argument("--thickness", type=float, default=3.0, help="one-piece token, mm (default 3.0)")
    parser.add_argument("--inlay", type=float, default=0.6, help="colour depth per face, mm (default 0.6)")
    parser.add_argument("--slab", type=float, default=1.2, help="black slab of a half, mm (default 1.2)")
    parser.add_argument("--relief", type=float, default=0.4, help="raised art on a half, mm (default 0.4)")
    parser.add_argument("--preview", action="store_true", help="also draw every face as a PNG")
    args = parser.parse_args()

    if 2 * args.inlay >= args.thickness:
        parser.error("two inlays would meet in the middle; lower --inlay")

    args.out.mkdir(parents=True, exist_ok=True)
    report = []
    faces_seen = []
    for token, ((top_name, top_rgb), (bottom_name, bottom_rgb)) in TOKENS.items():
        top_outline, top_art = face(top_name, top_rgb, args.size)
        bottom_outline, bottom_art = face(bottom_name, bottom_rgb, args.size)
        faces_seen += [
            (top_outline, top_art, top_rgb),
            (bottom_outline, bottom_art, bottom_rgb),
        ]
        for name, art in ((top_name, top_art), (bottom_name, bottom_art)):
            black = top_outline.difference(art)
            report.append(
                f"  {name}: {thinnest_loss(art, 0.4):.1%} of its colour and "
                f"{thinnest_loss(black, 0.4):.1%} of the black on its face is "
                "under 0.4 mm wide"
            )

        parts = one_piece(top_outline, top_art, bottom_art, args.thickness, args.inlay)
        colored = [
            ("body", BODY_COLOR, parts["body"]),
            (f"top-{top_name}", top_rgb, parts["top"]),
            (f"bottom-{bottom_name}", bottom_rgb, parts["bottom"]),
        ]
        write_3mf(args.out / f"{token}.3mf", token, colored)
        for label, mesh in parts.items():
            write_stl(mesh, args.out / f"{token}_{label}.stl")
        for name, outline, art in (
            (top_name, top_outline, top_art),
            (bottom_name, bottom_outline, bottom_art),
        ):
            write_stl(
                half(outline, art, args.slab, args.relief),
                args.out / f"{token}_half_{name}.stl",
            )
        if not parts["body"].is_watertight:
            report.append(f"  WARNING: {token} body is not watertight")

    if args.preview:
        preview(args.out / "preview.png", faces_seen, args.size)

    (args.out / "README.txt").write_text(readme(args))
    print(f"Written to {args.out}")
    print("Detail finer than one line from a 0.4 mm nozzle:")
    print("\n".join(report))
    return 0


def readme(args) -> str:
    colors = []
    for token, faces in TOKENS.items():
        sides = " / ".join(f"{name} {hex_color(rgb)[:7]}" for name, rgb in faces)
        colors.append(f"  {token}: body {hex_color(BODY_COLOR)[:7]}, {sides}")
    return f"""D12 Ball condition tokens -- {args.size:g} mm, generated by
scripts/render_token_models.py. Three tokens; print as many of each as
the table needs.

  exhaust    amber ZZZ triangle  /  Cyborg teal triangle
  exhausted  EXHAUSTED (blue)    /  INJURED (red)
  drained    DRAINED (teal)      /  DAMAGED (amber)

Colours (pick the nearest filament; the two ambers differ on purpose --
the exhaust amber is pale, Damaged's is deeper):
{chr(10).join(colors)}

A. MULTI-MATERIAL PRINTER (AMS, MMU, tool changer) -- <token>.3mf
   One piece, {args.thickness:g} mm thick, colour {args.inlay:g} mm deep in both faces,
   both faces flat. Open the 3MF: it is one object of three parts.
   Give each part its filament, slice at 0.2 mm layers (the inlay is
   then {args.inlay / 0.2:g} layers) and print it as it lies. The bottom face prints
   against the plate, so it takes the plate's finish -- a smooth plate
   gives the cleanest art. Ironing the top face evens the two faces out.
   A slicer that won't read the 3MF: load <token>_body/_top/_bottom.stl
   together and answer "yes" to loading them as one multi-part object.

B. ONE FILAMENT -- <token>_half_<face>.stl, two per token
   Each half is a {args.slab:g} mm black slab with its art raised {args.relief:g} mm.
   Print it face up in black and add a filament change (Bambu Studio:
   "Add pause" / "Change filament"; PrusaSlicer: "Add color change") at
   the first layer above {args.slab:g} mm, then load the face's colour.
   The two halves of a token go back to back, plain sides together, with
   CA glue or a thin layer of epoxy -- lined up by their edges. A token
   is then {2 * args.slab:g} mm of black with {args.relief:g} mm of art on each face.

Either way, keep to one plastic (all PLA, say): a colour change fuses
only between filaments of the same kind.
"""


if __name__ == "__main__":
    raise SystemExit(main())
