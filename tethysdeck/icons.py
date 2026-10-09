"""The six suits' symbols, drawn flat in colour: whole for Fortune, broken for Doom.

Each is drawn in a 1000 x 1000 design space at 4x and downsampled. `relief.py`
takes the colour render and the ink mask (`render(..., mask=True)`) and lights
them as embossed metal. Money is the studio's own coin, its two faces.
"""
import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

from tethysdeck.deck import VARIANTS

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SIZE = 1024          # every drawing comes out this big; the cards scale it down
S = 4                # supersampling
CANVAS = SIZE * S
COINS = PROJECT_ROOT / "d12ball" / "images" / "emoji"
FONT = PROJECT_ROOT / "d12ball" / "fonts" / "RobotoSlab-Bold.ttf"

# Each suit's material colours, by fate. "ink" is the engraved line, dark everywhere.
COLOURS = {
    "might": {
        "fortune": {"ink": "#2A2F38", "blade": "#DCE3EA", "edge": "#9AA7B5", "guard": "#E2B53A", "grip": "#8B1E2D", "pommel": "#E2B53A",
                    "wood": "#A2683A", "gem": "#A51E36", "gem2": "#17606A"},
        "doom": {"ink": "#1E1A18", "blade": "#7D7068", "edge": "#4F4540", "guard": "#8C6B2A", "grip": "#4A1F24", "pommel": "#8C6B2A",
                 "wood": "#5A3A22", "gem": "#4A1F24", "gem2": "#1E3A40"},
    },
    "fiends": {
        "fortune": {"ink": "#2B0F18", "face": "#A51E36", "horn": "#3A1F24", "eye": "#F2C14E", "gem": "#F2C14E"},
        "doom": {"ink": "#120C10", "face": "#33272E", "horn": "#1C1317", "eye": "#FF6A1F", "fang": "#E8E2D8"},
    },
    "tools": {
        "fortune": {"ink": "#2A2420", "steel": "#C9D2DA", "shine": "#EEF2F5", "wood": "#A2683A", "wrench": "#B9C3CC", "spark": "#F2C14E"},
        "doom": {"ink": "#1B1512", "steel": "#7A5A3A", "shine": "#9A7A5A", "wood": "#5A3A22", "wrench": "#6E5236", "spark": "#F2C14E"},
    },
    "states": {
        "fortune": {"ink": "#123A40", "dark": "#17606A", "light": "#BFE3E6"},
        "doom": {"ink": "#1E1426", "dark": "#3A2A4A", "light": "#9C95A8", "bolt": "#F2C14E"},
    },
    "fools": {
        "fortune": {"ink": "#2A1A2E", "red": "#D7263D", "green": "#2E9E5B", "purple": "#6A3FA0", "band": "#F2C14E", "bell": "#F2C14E"},
        "doom": {"ink": "#1A1020", "red": "#7A1F2A", "green": "#245A3A", "purple": "#3E2A5E", "band": "#8C6B2A", "bell": "#8C6B2A"},
    },
}


class Mask(dict):
    """The same keys as a colour dict, white for every part and black for the ink."""
    def __getitem__(self, key):
        return "#000000" if key == "ink" else "#FFFFFF"


def u(v):
    return v * CANVAS / 1000


def pt(x, y):
    return (u(x), u(y))


def pts(seq):
    return [pt(x, y) for x, y in seq]


def box(cx, cy, r):
    return [pt(cx - r, cy - r), pt(cx + r, cy + r)]


def new_layer():
    return Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))


def arc_points(cx, cy, r, a0, a1, n=48):
    return [(cx + r * math.cos(math.radians(a0 + (a1 - a0) * i / n)),
             cy + r * math.sin(math.radians(a0 + (a1 - a0) * i / n))) for i in range(n + 1)]


def bezier(p0, p1, p2, n=40):
    out = []
    for i in range(n + 1):
        t = i / n
        out.append(((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t ** 2 * p2[0],
                    (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t ** 2 * p2[1]))
    return out


def tapered(curve, w0, w1):
    left, right = [], []
    n = len(curve) - 1
    for i, (x, y) in enumerate(curve):
        a, b = curve[max(i - 1, 0)], curve[min(i + 1, n)]
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dy) or 1
        nx, ny = -dy / L, dx / L
        w = (w0 + (w1 - w0) * i / n) / 2
        left.append((x + nx * w, y + ny * w))
        right.append((x - nx * w, y - ny * w))
    return left + right[::-1]


def W(v):
    return round(u(v))


# --- the six symbols -------------------------------------------------------

def money(d, c, fate, layer):
    coin = Image.open(COINS / f"coin_gold_1_{fate}.png").convert("RGBA")
    side = round(u(900))
    scale = side / max(coin.size)
    coin = coin.resize((round(coin.width * scale), round(coin.height * scale)), Image.LANCZOS)
    layer.alpha_composite(coin, ((CANVAS - coin.width) // 2, (CANVAS - coin.height) // 2))


def might(d, c, fate, layer):
    """A longsword: tapered blade with a fuller, dipped quillons, a wrapped grip, a disc pommel."""
    ink = W(12)
    d.polygon(pts([(318, 572), (500, 556), (682, 572), (690, 600), (660, 618), (500, 600), (340, 618), (310, 600)]),
              fill=c["guard"], outline=c["ink"], width=ink)
    d.ellipse(box(314, 600, 26), fill=c["guard"], outline=c["ink"], width=W(8))
    d.ellipse(box(686, 600, 26), fill=c["guard"], outline=c["ink"], width=W(8))
    d.polygon(pts([(470, 616), (530, 616), (536, 800), (464, 800)]), fill=c["grip"], outline=c["ink"], width=ink)
    for y in range(640, 800, 32):
        d.line(pts([(468, y), (532, y + 20)]), fill=c["ink"], width=W(6))
    d.ellipse(box(500, 846, 50), fill=c["pommel"], outline=c["ink"], width=ink)
    d.ellipse(box(500, 846, 16), fill=c["ink"])
    tip = [(500, 40), (538, 130), (546, 240)]
    if fate == "fortune":
        d.polygon(pts(tip + [(546, 556), (454, 556), (454, 240), (462, 130)]), fill=c["blade"], outline=c["ink"], width=ink)
        d.polygon(pts(tip + [(546, 556), (500, 556)]), fill=c["edge"])
        d.rounded_rectangle(pts([(490, 170), (510, 480)]), radius=W(10), fill=c["ink"])
        d.polygon(pts(tip + [(546, 556), (454, 556), (454, 240), (462, 130)]), outline=c["ink"], width=ink)
        return
    brk = [(454, 330), (480, 300), (500, 345), (525, 300), (546, 330)]
    d.polygon(pts([(454, 556), (546, 556)] + brk[::-1]), fill=c["blade"], outline=c["ink"], width=ink)
    d.polygon(pts([(500, 345), (525, 300), (546, 330), (546, 556), (500, 556)]), fill=c["edge"])
    d.rounded_rectangle(pts([(490, 370), (510, 480)]), radius=W(10), fill=c["ink"])
    piece = new_layer()
    pd = ImageDraw.Draw(piece)
    upper = brk + [(546, 240)] + tip[::-1] + [(462, 130), (454, 240)]
    pd.polygon(pts(upper), fill=c["blade"], outline=c["ink"], width=ink)
    pd.polygon(pts([(500, 40), (538, 130), (546, 240), (546, 330), (525, 300), (500, 345), (500, 60)]), fill=c["edge"])
    pd.rounded_rectangle(pts([(490, 170), (510, 290)]), radius=W(10), fill=c["ink"])
    pd.polygon(pts(upper), outline=c["ink"], width=ink)
    piece = piece.rotate(-38, resample=Image.BICUBIC, center=pt(500, 330))
    layer.alpha_composite(piece, (W(85), W(35)))


def fiends(d, c, fate, layer):
    # Long swept horns, then a mask of a face: wide brow, hollow cheeks, pointed chin.
    for sign in (-1, 1):
        base = (500 + sign * 175, 370)
        ctrl = (500 + sign * 380, 260)
        tip = (500 + sign * 265, 60)
        d.polygon(pts(tapered(bezier(base, ctrl, tip), 150, 10)), fill=c["horn"], outline=c["ink"], width=W(18))
    face = [(300, 330), (330, 300), (420, 275), (500, 268), (580, 275), (670, 300), (700, 330),
            (705, 470), (670, 600), (600, 730), (500, 830), (400, 730), (330, 600), (295, 470)]
    d.polygon(pts(face), fill=c["face"], outline=c["ink"], width=W(24))
    # Brow ridge.
    d.line(pts([(360, 420), (440, 400)]), fill=c["ink"], width=W(16))
    d.line(pts([(640, 420), (560, 400)]), fill=c["ink"], width=W(16))
    if fate == "fortune":
        # Serene: eyes closed in two long lids, a gem on the brow, a level mouth.
        for sign in (-1, 1):
            cx = 500 + sign * 95
            d.line(pts([(cx - sign * 70, 480), (cx + sign * 15, 505), (cx + sign * 55, 480)]), fill=c["ink"], width=W(18), joint="curve")
        d.polygon(pts([(500, 330), (528, 368), (500, 406), (472, 368)]), fill=c["gem"], outline=c["ink"], width=W(10))
        d.line(pts([(445, 650), (555, 650)]), fill=c["ink"], width=W(16))
        return
    # Wrathful: hollow eye sockets with ember pupils, a jaw of fangs.
    for sign in (-1, 1):
        cx = 500 + sign * 95
        d.polygon(pts([(cx - sign * 80, 455), (cx + sign * 55, 480), (cx + sign * 30, 530), (cx - sign * 60, 520)]), fill=c["ink"])
        d.ellipse(box(cx - sign * 10, 495, 16), fill=c["eye"])
    d.line(pts([(380, 640), (620, 640)]), fill=c["ink"], width=W(14))
    for x in (405, 455, 545, 595):
        d.polygon(pts([(x - 22, 640), (x + 22, 640), (x, 705)]), fill=c["fang"], outline=c["ink"], width=W(6))


def _hammer(c, broken):
    """A claw hammer: tapered handle with a dark grip, an eye block, a round poll, a curved split claw."""
    layer = new_layer()
    d = ImageDraw.Draw(layer)
    ink = W(12)
    if not broken:
        d.polygon(pts([(474, 320), (526, 320), (540, 880), (460, 880)]), fill=c["wood"], outline=c["ink"], width=ink)
    else:
        d.polygon(pts([(474, 320), (526, 320), (532, 600), (512, 640), (534, 660), (468, 640)]), fill=c["wood"], outline=c["ink"], width=ink)
        piece = new_layer()
        pd = ImageDraw.Draw(piece)
        pd.polygon(pts([(468, 660), (512, 640), (534, 680), (540, 880), (460, 880)]), fill=c["wood"], outline=c["ink"], width=ink)
        pd.rounded_rectangle(pts([(452, 790), (548, 892)]), radius=W(18), fill=c["ink"])
        piece = piece.rotate(28, resample=Image.BICUBIC, center=pt(500, 660))
        layer.alpha_composite(piece, (W(45), W(0)))
    if not broken:
        d.rounded_rectangle(pts([(452, 790), (548, 892)]), radius=W(18), fill=c["ink"])
    claw = bezier((445, 235), (330, 215), (255, 335))
    d.polygon(pts(tapered(claw, 92, 22)), fill=c["steel"], outline=c["ink"], width=ink)
    d.line(pts(bezier((400, 252), (330, 245), (262, 328))), fill=c["ink"], width=W(7))
    d.rounded_rectangle(pts([(430, 185), (570, 320)]), radius=W(14), fill=c["steel"], outline=c["ink"], width=ink)
    d.rounded_rectangle(pts([(560, 205), (748, 300)]), radius=W(10), fill=c["steel"], outline=c["ink"], width=ink)
    d.rounded_rectangle(pts([(735, 192), (775, 313)]), radius=W(8), fill=c["steel"], outline=c["ink"], width=ink)
    d.line(pts([(448, 203), (738, 220)]), fill=c["shine"], width=W(10))
    if broken:
        d.line(pts([(600, 190), (570, 240), (620, 270), (590, 320)]), fill=c["ink"], width=W(12), joint="curve")
    return layer


def _wrench(c, broken):
    """A combination wrench: an open end on top, a box end below, an I-beam handle between."""
    layer = new_layer()
    d = ImageDraw.Draw(layer)
    ink = W(12)
    d.polygon(pts([(455, 330), (545, 330), (535, 740), (465, 740)]), fill=c["wrench"], outline=c["ink"], width=ink)
    d.rounded_rectangle(pts([(490, 370), (510, 700)]), radius=W(10), fill=c["ink"])
    cx, cy, r = 500, 235, 140
    head = arc_points(cx, cy, r, 300, 600) + [(448, 100), (448, 235), (552, 235), (552, 100)]
    d.polygon(pts(head), fill=c["wrench"], outline=c["ink"], width=ink)
    d.ellipse(box(500, 820, 95), fill=c["wrench"], outline=c["ink"], width=ink)
    d.ellipse(box(500, 820, 46), fill=(0, 0, 0, 0))
    d.ellipse(box(500, 820, 46), outline=c["ink"], width=W(8))
    if broken:
        d.line(pts([(575, 150), (610, 210), (570, 260)]), fill=c["ink"], width=W(12), joint="curve")
    return layer


def tools(d, c, fate, layer):
    broken = fate == "doom"
    hammer = _hammer(c, broken).rotate(35, resample=Image.BICUBIC, center=pt(500, 560))
    wrench = _wrench(c, broken).rotate(-35, resample=Image.BICUBIC, center=pt(500, 560))
    layer.alpha_composite(wrench)
    layer.alpha_composite(hammer)
    if not broken:
        sd = ImageDraw.Draw(layer)
        for (sx, sy, sr) in ((520, 95, 34), (610, 150, 22)):
            sd.polygon(pts([(sx, sy - sr), (sx + sr * 0.3, sy - sr * 0.3), (sx + sr, sy), (sx + sr * 0.3, sy + sr * 0.3),
                            (sx, sy + sr), (sx - sr * 0.3, sy + sr * 0.3), (sx - sr, sy), (sx - sr * 0.3, sy - sr * 0.3)]),
                       fill=c["spark"], outline=c["ink"], width=W(6))


def states(d, c, fate, layer):
    cx, cy, r = 500, 500, 380
    if fate == "fortune":
        d.ellipse(box(cx, cy, r), fill=c["light"])
        d.pieslice(box(cx, cy, r), 90, 270, fill=c["dark"])
        d.ellipse(box(cx, cy - r / 2, r / 2), fill=c["dark"])
        d.ellipse(box(cx, cy + r / 2, r / 2), fill=c["light"])
        d.ellipse(box(cx, cy - r / 2, 55), fill=c["light"])
        d.ellipse(box(cx, cy + r / 2, 55), fill=c["dark"])
        d.ellipse(box(cx, cy, r), outline=c["ink"], width=W(26))
        return
    bolt = [(500, 120), (590, 320), (440, 470), (575, 610), (470, 770), (500, 880)]
    d.polygon(pts(bolt + arc_points(cx, cy, r, 90, 270)), fill=c["dark"])
    d.polygon(pts(bolt + arc_points(cx, cy, r, 90, -90)), fill=c["light"])
    d.line(pts(bolt), fill=c["bolt"], width=W(30), joint="curve")
    d.line(pts(bolt), fill=c["ink"], width=W(10), joint="curve")
    d.ellipse(box(cx, cy, r), outline=c["ink"], width=W(26))
    d.ellipse(box(cx - 170, cy - 140, 55), fill=c["light"])
    d.ellipse(box(cx + 170, cy + 140, 55), fill=c["dark"])


def fools(d, c, fate, layer):
    """A jester's cap. Fortune: the points up and the bells ringing. Doom: everything sags."""
    ink = W(12)
    up = fate == "fortune"
    d.polygon(pts([(265, 700), (300, 560), (400, 495), (500, 475), (600, 495), (700, 560), (735, 700)]),
              fill=c["purple"], outline=c["ink"], width=ink)
    if up:
        points = [((345, 600), (150, 540), (140, 320), c["red"]),
                  ((500, 560), (520, 300), (575, 140), c["purple"]),
                  ((655, 600), (850, 540), (860, 320), c["green"])]
    else:
        points = [((345, 600), (140, 690), (165, 920), c["red"]),
                  ((500, 560), (600, 520), (640, 790), c["purple"]),
                  ((655, 600), (860, 690), (835, 920), c["green"])]

    def point(base, ctrl, tip, colour):
        d.polygon(pts(tapered(bezier(base, ctrl, tip), 180, 24)), fill=colour, outline=c["ink"], width=ink)

    def bell(tip):
        d.ellipse(box(tip[0], tip[1], 46), fill=c["bell"], outline=c["ink"], width=W(10))
        d.line(pts([(tip[0], tip[1] + 6), (tip[0], tip[1] + 32)]), fill=c["ink"], width=W(7))

    if up:
        for base, ctrl, tip, colour in points:
            point(base, ctrl, tip, colour)
        d.rounded_rectangle(pts([(240, 690), (760, 780)]), radius=W(30), fill=c["band"], outline=c["ink"], width=ink)
        zig = [(265 + i * 52, 702 if i % 2 == 0 else 768) for i in range(10)]
        d.line(pts(zig), fill=c["ink"], width=W(8), joint="curve")
        # The bells, each with the marks of its ringing on its outer side.
        for (base, ctrl, tip, colour), arcs in zip(points, ((200, 250), (250, 290), (290, 340))):
            bell(tip)
            for radius in (72, 96):
                d.arc(box(tip[0], tip[1], radius), arcs[0], arcs[1], fill=c["ink"], width=W(7))
        return
    # Doom: the side points hang from under the band, the middle one flops over its front.
    for base, ctrl, tip, colour in (points[0], points[2]):
        point(base, ctrl, tip, colour)
    d.polygon(pts([(240, 690), (760, 690), (770, 768), (500, 800), (230, 768)]), fill=c["band"], outline=c["ink"], width=ink)
    zig = [(265 + i * 52, 702 if i % 2 == 0 else 760 + (6 if 2 < i < 7 else 0)) for i in range(10)]
    d.line(pts(zig), fill=c["ink"], width=W(8), joint="curve")
    point(*points[1])
    for base, ctrl, tip, colour in points:
        bell(tip)


def might_axe(d, c, fate, layer):
    """A bearded axe: a tapered haft wrapped at the grip, a socketed head with a curved edge and a beard."""
    ink = W(12)
    broken = fate == "doom"
    if not broken:
        d.polygon(pts([(476, 110), (524, 110), (534, 900), (466, 900)]), fill=c["wood"], outline=c["ink"], width=ink)
    else:
        d.polygon(pts([(476, 110), (524, 110), (530, 600), (508, 640), (532, 660), (468, 640)]), fill=c["wood"], outline=c["ink"], width=ink)
        piece = new_layer()
        pd = ImageDraw.Draw(piece)
        pd.polygon(pts([(468, 660), (508, 640), (532, 680), (534, 900), (466, 900)]), fill=c["wood"], outline=c["ink"], width=ink)
        for y in range(760, 880, 26):
            pd.line(pts([(468, y), (532, y + 14)]), fill=c["ink"], width=W(5))
        piece = piece.rotate(26, resample=Image.BICUBIC, center=pt(500, 680))
        layer.alpha_composite(piece, (W(40), W(0)))
    if not broken:
        for y in range(760, 880, 26):
            d.line(pts([(468, y), (532, y + 14)]), fill=c["ink"], width=W(5))
    edge = bezier((770, 150), (850, 340), (735, 540))
    beard = bezier((735, 540), (600, 470), (562, 350))
    blade = [(548, 200), (690, 160), (770, 150)] + edge + beard + [(548, 345)]
    d.polygon(pts(blade), fill=c["blade"], outline=c["ink"], width=ink)
    bevel = edge + [(x - 40, y) for (x, y) in reversed(edge)]
    d.polygon(pts(bevel), fill=c["edge"])
    d.polygon(pts(blade), outline=c["ink"], width=ink)
    d.rounded_rectangle(pts([(438, 190), (562, 352)]), radius=W(18), fill=c["blade"], outline=c["ink"], width=ink)
    d.line(pts([(438, 240), (562, 240)]), fill=c["ink"], width=W(6))
    d.line(pts([(438, 300), (562, 300)]), fill=c["ink"], width=W(6))
    if broken:
        d.line(pts([(700, 170), (660, 260), (720, 340), (670, 430), (700, 530)]), fill=c["ink"], width=W(12), joint="curve")


def might_sceptre(d, c, fate, layer):
    """A sceptre: a slender rod with a knop and a flared foot, a gem in four prongs under an orb and spike."""
    ink = W(10)
    d.polygon(pts([(482, 310), (518, 310), (524, 860), (476, 860)]), fill=c["guard"], outline=c["ink"], width=ink)
    d.ellipse(box(500, 470, 34), fill=c["guard"], outline=c["ink"], width=ink)
    d.polygon(pts([(470, 860), (530, 860), (548, 905), (452, 905)]), fill=c["guard"], outline=c["ink"], width=ink)
    d.polygon(pts([(462, 310), (538, 310), (552, 270), (448, 270)]), fill=c["guard"], outline=c["ink"], width=ink)
    d.ellipse(box(500, 190, 80), fill=c["gem"], outline=c["ink"], width=ink)
    for a in (45, 135, 225, 315):
        ax, ay = math.cos(math.radians(a)), math.sin(math.radians(a))
        px, py = -ay, ax
        d.polygon(pts([(500 + ax * 56, 190 + ay * 56), (500 + ax * 98 + px * 16, 190 + ay * 98 + py * 16),
                       (500 + ax * 98 - px * 16, 190 + ay * 98 - py * 16)]), fill=c["guard"], outline=c["ink"], width=W(6))
    d.ellipse(box(500, 92, 22), fill=c["guard"], outline=c["ink"], width=W(8))
    d.polygon(pts([(500, 28), (514, 72), (486, 72)]), fill=c["guard"], outline=c["ink"], width=W(8))
    if fate == "fortune":
        d.ellipse(box(474, 166, 16), fill="#FFFFFF")
    else:
        d.line(pts([(455, 150), (500, 195), (470, 240), (540, 255)]), fill=c["ink"], width=W(10), joint="curve")


def might_crown(d, c, fate, layer):
    """A crown: five curved points, tall and short by turns, on a jewelled circlet."""
    ink = W(12)
    broken = fate == "doom"
    base_y = 575
    bases = [(205, 325), (325, 445), (445, 555), (555, 675), (675, 795)]
    tips = [(245, 300), (385, 410), (500, 180), (615, 410), (755, 300)]
    outline = [(205, base_y)]
    for (x0, x1), (tx, ty) in zip(bases, tips):
        if broken and x0 == 675:
            outline += [(700, 470), (725, 500), (745, 450), (795, base_y)]
            continue
        outline += bezier((x0, base_y), (x0 + (tx - x0) * 0.25, ty + (base_y - ty) * 0.4), (tx, ty))[1:]
        outline += bezier((tx, ty), (x1 - (x1 - tx) * 0.25, ty + (base_y - ty) * 0.4), (x1, base_y))[1:]
    d.polygon(pts(outline + [(795, 760), (205, 760)]), fill=c["guard"], outline=c["ink"], width=ink)
    d.rounded_rectangle(pts([(205, 575), (795, 770)]), radius=W(22), fill=c["guard"], outline=c["ink"], width=ink)
    d.line(pts([(205, 735), (795, 735)]), fill=c["ink"], width=W(6))
    for x, key, r in ((300, "gem", 36), (400, "gem2", 18), (500, "gem2", 36), (600, "gem2", 18), (700, "gem", 36)):
        d.ellipse(box(x, 655, r), fill=c[key], outline=c["ink"], width=W(8))
    for (tx, ty) in ((245, 300), (500, 180)) + (((755, 300),) if not broken else ()):
        d.ellipse(box(tx, ty, 22), fill=c["gem"], outline=c["ink"], width=W(8))
    if broken:
        d.line(pts([(600, 575), (570, 650), (620, 700), (590, 770)]), fill=c["ink"], width=W(12), joint="curve")



def tools_hammer(d, c, fate, layer):
    """The claw hammer on its own: the 1 of Tools."""
    layer.alpha_composite(_hammer(c, fate == "doom"))


def tools_pick(d, c, fate, layer):
    """A pickaxe, a point one side and a chisel the other: the 3 of Tools."""
    ink = W(12)
    broken = fate == "doom"
    if not broken:
        d.polygon(pts([(480, 250), (520, 250), (528, 900), (472, 900)]), fill=c["wood"], outline=c["ink"], width=ink)
    else:
        d.polygon(pts([(480, 250), (520, 250), (524, 580), (502, 620), (526, 640), (478, 620)]), fill=c["wood"], outline=c["ink"], width=ink)
        piece = new_layer()
        pd = ImageDraw.Draw(piece)
        pd.polygon(pts([(478, 640), (502, 620), (526, 660), (528, 900), (472, 900)]), fill=c["wood"], outline=c["ink"], width=ink)
        piece = piece.rotate(24, resample=Image.BICUBIC, center=pt(500, 660))
        layer.alpha_composite(piece, (W(40), W(0)))
    # The head: two tapered arms curving down from the socket, one to a point, one to a chisel.
    left = bezier((500, 215), (320, 170), (120, 300))
    right = bezier((500, 215), (680, 170), (880, 290))
    d.polygon(pts(tapered(left, 110, 14)), fill=c["steel"], outline=c["ink"], width=W(10))
    d.polygon(pts(tapered(right, 110, 40)), fill=c["steel"], outline=c["ink"], width=W(10))
    d.rounded_rectangle(pts([(438, 160), (562, 290)]), radius=W(16), fill=c["steel"], outline=c["ink"], width=ink)
    d.line(pts([(330, 195), (670, 195)]), fill=c["shine"], width=W(8))
    if broken:
        d.line(pts([(640, 170), (610, 215), (660, 250), (630, 280)]), fill=c["ink"], width=W(12), joint="curve")


def tools_spade(d, c, fate, layer):
    """A spade, blade down: the 6 of Tools."""
    ink = W(12)
    broken = fate == "doom"
    # The T-handle and the shaft.
    d.rounded_rectangle(pts([(410, 40), (590, 100)]), radius=W(24), fill=c["wood"], outline=c["ink"], width=ink)
    if not broken:
        d.polygon(pts([(478, 100), (522, 100), (526, 560), (474, 560)]), fill=c["wood"], outline=c["ink"], width=ink)
    else:
        d.polygon(pts([(478, 100), (522, 100), (524, 300), (502, 330), (524, 350), (476, 330)]), fill=c["wood"], outline=c["ink"], width=ink)
        piece = new_layer()
        pd = ImageDraw.Draw(piece)
        pd.polygon(pts([(476, 350), (502, 330), (524, 370), (526, 560), (474, 560)]), fill=c["wood"], outline=c["ink"], width=ink)
        piece = piece.rotate(18, resample=Image.BICUBIC, center=pt(500, 370))
        layer.alpha_composite(piece, (W(30), W(10)))
    # The blade: a socket, shoulders, a pointed face with a ridge.
    d.polygon(pts([(455, 540), (545, 540), (545, 590), (455, 590)]), fill=c["steel"], outline=c["ink"], width=ink)
    blade = [(370, 585), (630, 585), (630, 740), (500, 930), (370, 740)]
    d.polygon(pts(blade), fill=c["steel"], outline=c["ink"], width=ink)
    d.line(pts([(500, 600), (500, 900)]), fill=c["ink"], width=W(6))
    d.line(pts([(395, 600), (395, 735)]), fill=c["shine"], width=W(8))
    if broken:
        d.line(pts([(560, 590), (530, 680), (585, 760), (545, 880)]), fill=c["ink"], width=W(12), joint="curve")


def tools_anvil(d, c, fate, layer):
    """An anvil, horn to the left: the 12 of Tools."""
    ink = W(12)
    broken = fate == "doom"
    body = [(300, 330), (880, 330), (880, 440), (730, 455), (730, 640), (850, 700), (850, 780),
            (150, 780), (150, 700), (270, 640), (270, 455), (200, 445), (105, 400), (200, 345)]
    d.polygon(pts(body), fill=c["steel"], outline=c["ink"], width=ink)
    # The face's top edge lit, a hardy hole, the foot's edge.
    d.line(pts([(310, 345), (870, 345)]), fill=c["shine"], width=W(10))
    d.rectangle(pts([(790, 365), (830, 405)]), fill=c["ink"])
    d.line(pts([(150, 700), (850, 700)]), fill=c["ink"], width=W(5))
    d.line(pts([(270, 455), (730, 455)]), fill=c["ink"], width=W(5))
    if broken:
        d.line(pts([(520, 330), (480, 420), (540, 520), (490, 640), (530, 780)]), fill=c["ink"], width=W(12), joint="curve")

# The drawing behind each of Might's and Tools' denominations (deck.VARIANTS names them).
DRAWINGS = {"might_sword": might, "might_axe": might_axe, "might_sceptre": might_sceptre, "might_crown": might_crown,
            "tools_hammer": tools_hammer, "tools_pick": tools_pick, "tools_spade": tools_spade, "tools_anvil": tools_anvil}


SUITS = {"money": money, "might": might, "fiends": fiends, "tools": tools, "states": states, "fools": fools}


def render(suit: str, fate: str, mask: bool = False, variant: str | None = None) -> Image.Image:
    layer = new_layer()
    d = ImageDraw.Draw(layer)
    c = Mask() if mask else COLOURS.get(suit, {}).get(fate, {})
    draw = DRAWINGS[f"{suit}_{variant}"] if variant else SUITS[suit]
    draw(d, c, fate, layer)
    return layer.resize((SIZE, SIZE), Image.LANCZOS)


def every_icon():
    """(suit, variant, fate) for every file the deck needs; variant None is the suit's own mark."""
    for suit in SUITS:
        for fate in ("fortune", "doom"):
            yield suit, None, fate
            for variant in VARIANTS.get(suit, {}).values():
                yield suit, variant, fate


def icon_name(suit, variant, fate):
    return f"{suit}_{variant}_{fate}" if variant else f"{suit}_{fate}"


def sheet(images: dict, out: Path) -> None:
    font = ImageFont.truetype(str(FONT), 22)
    cell, gap, label = 256, 24, 36
    img = Image.new("RGB", (6 * cell + 7 * gap, 2 * (cell + label) + 3 * gap), "#FFFFFF")
    d = ImageDraw.Draw(img)
    for name, icon in images.items():
        suit, fate = name.split("_")
        x = gap + list(SUITS).index(suit) * (cell + gap)
        y = gap + (0 if fate == "fortune" else 1) * (cell + label + gap)
        small = icon.resize((cell, cell), Image.LANCZOS)
        img.paste(small, (x, y), small)
        d.text((x + cell // 2, y + cell + label // 2), f"{suit} {fate}", font=font, fill="#333333", anchor="mm")
    img.save(out)
