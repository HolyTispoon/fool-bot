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
        "fortune": {"ink": "#2A2F38", "blade": "#DCE3EA", "edge": "#9AA7B5", "shine": "#F4F7FA", "guard": "#E2B53A",
                    "guard2": "#B8892A", "grip": "#8B1E2D", "pommel": "#E2B53A", "wood": "#A2683A", "grain": "#7A4E2A",
                    "gem": "#A51E36", "gem2": "#17606A", "velvet": "#7A1F3A", "pearl": "#F4F2EC"},
        "doom": {"ink": "#1E1A18", "blade": "#7D7068", "edge": "#4F4540", "shine": "#9A8D83", "guard": "#8C6B2A",
                 "guard2": "#5E4718", "grip": "#4A1F24", "pommel": "#8C6B2A", "wood": "#5A3A22", "grain": "#3E2816",
                 "gem": "#4A1F24", "gem2": "#1E3A40", "velvet": "#3A1420", "pearl": "#8C847A"},
    },
    "fiends": {
        "fortune": {"ink": "#2B0F18", "face": "#A51E36", "horn": "#3A1F24", "eye": "#F2C14E", "gem": "#F2C14E"},
        "doom": {"ink": "#120C10", "face": "#33272E", "horn": "#1C1317", "eye": "#FF6A1F", "fang": "#E8E2D8"},
    },
    "tools": {
        "fortune": {"ink": "#2A2420", "steel": "#C9D2DA", "shade": "#8E99A3", "shine": "#EEF2F5", "wood": "#A2683A",
                    "grain": "#7A4E2A", "wrench": "#B9C3CC", "spark": "#F2C14E"},
        "doom": {"ink": "#1B1512", "steel": "#7A5A3A", "shade": "#5A4634", "shine": "#9A7A5A", "wood": "#5A3A22",
                 "grain": "#3E2816", "wrench": "#6E5236", "spark": "#F2C14E"},
    },
    "states": {
        "fortune": {"ink": "#123A40", "dark": "#17606A", "light": "#BFE3E6"},
        "doom": {"ink": "#1E1426", "dark": "#3A2A4A", "light": "#9C95A8", "bolt": "#F2C14E"},
    },
    "fools": {
        "fortune": {"ink": "#2A1A2E", "red": "#D7263D", "green": "#2E9E5B", "purple": "#6A3FA0", "band": "#F2C14E",
                    "bell": "#F2C14E", "white": "#FFFFFF", "wood": "#A2683A", "skin": "#F2F2F2"},
        "doom": {"ink": "#1A1020", "red": "#7A1F2A", "green": "#245A3A", "purple": "#3E2A5E", "band": "#8C6B2A",
                 "bell": "#8C6B2A", "white": "#B8B2BC", "wood": "#5A3A22", "skin": "#8E8278"},
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
    """A longsword: a blade tapering from a ricasso to the point with a fuller and
    two bevel planes, curved quillons with finials, a wire-wrapped grip, a disc
    pommel with its peen block."""
    ink = W(10)
    # Quillons: a bar that bows down toward its ends, in gold, with a darker underside and knobs.
    top = bezier((300, 588), (500, 548), (700, 588))
    under = bezier((700, 618), (500, 604), (300, 618))
    d.polygon(pts(top + under), fill=c["guard"], outline=c["ink"], width=ink)
    d.line(pts(bezier((320, 606), (500, 590), (680, 606))), fill=c["guard2"], width=W(7))
    for x in (300, 700):
        d.ellipse(box(x, 603, 24), fill=c["guard"], outline=c["ink"], width=W(8))
        d.ellipse(box(x - 6, 596, 7), fill=c["shine"])
    # Grip: tapered leather with a wire wrap crossing both ways.
    d.polygon(pts([(468, 618), (532, 618), (538, 800), (462, 800)]), fill=c["grip"], outline=c["ink"], width=ink)
    for y in range(632, 800, 26):
        d.line(pts([(466, y), (534, y + 16)]), fill=c["ink"], width=W(4))
        d.line(pts([(534, y), (466, y + 16)]), fill=c["ink"], width=W(4))
    # Pommel: a disc with a turned ring and the peen block above it.
    d.rectangle(pts([(482, 796), (518, 812)]), fill=c["guard2"], outline=c["ink"], width=W(6))
    d.ellipse(box(500, 858, 52), fill=c["pommel"], outline=c["ink"], width=ink)
    d.ellipse(box(500, 858, 30), outline=c["guard2"], width=W(7))
    d.ellipse(box(488, 844, 9), fill=c["shine"])
    # Blade: wider at the ricasso, a long taper, two planes meeting on a ridge, a fuller.
    outline = [(500, 40), (541, 150), (548, 560), (452, 560), (459, 150)]
    if fate == "fortune":
        d.polygon(pts(outline), fill=c["blade"], outline=c["ink"], width=ink)
        d.polygon(pts([(500, 40), (541, 150), (548, 560), (500, 560)]), fill=c["edge"])
        d.rounded_rectangle(pts([(488, 180), (512, 470)]), radius=W(12), fill=c["edge"], outline=c["ink"], width=W(4))
        d.line(pts([(500, 60), (500, 175)]), fill=c["ink"], width=W(3))
        d.line(pts([(500, 475), (500, 556)]), fill=c["ink"], width=W(3))
        d.rectangle(pts([(466, 520), (534, 560)]), fill=c["edge"], outline=c["ink"], width=W(5))
        d.line(pts([(468, 150), (462, 500)]), fill=c["shine"], width=W(5))
        d.polygon(pts(outline), outline=c["ink"], width=ink)
        return
    brk = [(452, 330), (478, 300), (500, 345), (526, 300), (548, 330)]
    d.polygon(pts([(452, 560), (548, 560)] + brk[::-1]), fill=c["blade"], outline=c["ink"], width=ink)
    d.polygon(pts([(500, 345), (526, 300), (548, 330), (548, 560), (500, 560)]), fill=c["edge"])
    d.rounded_rectangle(pts([(488, 370), (512, 470)]), radius=W(12), fill=c["edge"], outline=c["ink"], width=W(4))
    d.rectangle(pts([(466, 520), (534, 560)]), fill=c["edge"], outline=c["ink"], width=W(5))
    d.polygon(pts([(452, 560), (548, 560)] + brk[::-1]), outline=c["ink"], width=ink)
    piece = new_layer()
    pd = ImageDraw.Draw(piece)
    upper = brk + [(548, 240), (541, 150), (500, 40), (459, 150), (452, 240)]
    pd.polygon(pts(upper), fill=c["blade"], outline=c["ink"], width=ink)
    pd.polygon(pts([(500, 40), (541, 150), (548, 240), (548, 330), (526, 300), (500, 345), (500, 60)]), fill=c["edge"])
    pd.rounded_rectangle(pts([(488, 180), (512, 290)]), radius=W(12), fill=c["edge"], outline=c["ink"], width=W(4))
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
    """A claw hammer: a tapered hickory handle with grain and a dark grip, an eye
    block with its wedge, a round poll with a bevelled face, a curved split claw."""
    layer = new_layer()
    d = ImageDraw.Draw(layer)
    ink = W(10)

    def grain(draw, top, bottom):
        for off in (-12, 2, 14):
            draw.line(pts([(500 + off, top), (500 + off * 1.3, bottom)]), fill=c["grain"], width=W(3))

    if not broken:
        d.polygon(pts([(474, 320), (526, 320), (540, 880), (460, 880)]), fill=c["wood"], outline=c["ink"], width=ink)
        grain(d, 340, 780)
        d.rounded_rectangle(pts([(452, 790), (548, 892)]), radius=W(18), fill=c["ink"])
        for y in range(812, 880, 22):
            d.line(pts([(458, y), (542, y)]), fill=c["shade"], width=W(3))
    else:
        d.polygon(pts([(474, 320), (526, 320), (532, 600), (512, 640), (534, 660), (468, 640)]), fill=c["wood"], outline=c["ink"], width=ink)
        grain(d, 340, 590)
        piece = new_layer()
        pd = ImageDraw.Draw(piece)
        pd.polygon(pts([(468, 660), (512, 640), (534, 680), (540, 880), (460, 880)]), fill=c["wood"], outline=c["ink"], width=ink)
        pd.rounded_rectangle(pts([(452, 790), (548, 892)]), radius=W(18), fill=c["ink"])
        piece = piece.rotate(28, resample=Image.BICUBIC, center=pt(500, 660))
        layer.alpha_composite(piece, (W(45), W(0)))
    # The claw: two curved prongs with the V between them.
    claw = bezier((445, 235), (330, 215), (255, 335))
    d.polygon(pts(tapered(claw, 92, 22)), fill=c["steel"], outline=c["ink"], width=ink)
    d.polygon(pts([(395, 262), (330, 262), (262, 330), (300, 300)]), fill=c["shade"])
    d.line(pts(bezier((400, 252), (330, 245), (262, 328))), fill=c["ink"], width=W(6))
    # The eye block with the wedge showing on top, the poll and its bevelled face.
    d.rounded_rectangle(pts([(430, 185), (570, 320)]), radius=W(14), fill=c["steel"], outline=c["ink"], width=ink)
    d.rectangle(pts([(482, 186), (518, 200)]), fill=c["wood"], outline=c["ink"], width=W(4))
    d.line(pts([(500, 186), (500, 200)]), fill=c["ink"], width=W(4))
    d.rounded_rectangle(pts([(560, 205), (748, 300)]), radius=W(10), fill=c["steel"], outline=c["ink"], width=ink)
    d.line(pts([(570, 292), (740, 292)]), fill=c["shade"], width=W(6))
    d.rounded_rectangle(pts([(735, 192), (775, 313)]), radius=W(8), fill=c["steel"], outline=c["ink"], width=ink)
    d.rounded_rectangle(pts([(745, 206), (765, 299)]), radius=W(6), fill=c["shade"], outline=c["ink"], width=W(3))
    d.line(pts([(448, 203), (738, 220)]), fill=c["shine"], width=W(8))
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
    """A bearded axe: a tapered haft with grain and a leather grip, a socketed head
    with langets riveted down the haft, a poll behind the eye, a curved edge with
    its hardened band and a beard."""
    ink = W(10)
    broken = fate == "doom"

    def grain(draw, x0, y0, x1, y1):
        for off in (-10, 4, 14):
            draw.line(pts([(x0 + off, y0), (x1 + off, y1)]), fill=c["grain"], width=W(3))

    if not broken:
        d.polygon(pts([(478, 110), (522, 110), (534, 900), (466, 900)]), fill=c["wood"], outline=c["ink"], width=ink)
        grain(d, 500, 400, 500, 740)
    else:
        d.polygon(pts([(478, 110), (522, 110), (530, 600), (508, 640), (532, 660), (468, 640)]), fill=c["wood"], outline=c["ink"], width=ink)
        grain(d, 500, 400, 500, 590)
        piece = new_layer()
        pd = ImageDraw.Draw(piece)
        pd.polygon(pts([(468, 660), (508, 640), (532, 680), (534, 900), (466, 900)]), fill=c["wood"], outline=c["ink"], width=ink)
        for y in range(760, 880, 24):
            pd.line(pts([(466, y), (534, y + 12)]), fill=c["ink"], width=W(4))
        piece = piece.rotate(26, resample=Image.BICUBIC, center=pt(500, 680))
        layer.alpha_composite(piece, (W(40), W(0)))
    if not broken:
        for y in range(760, 880, 24):
            d.line(pts([(466, y), (534, y + 12)]), fill=c["ink"], width=W(4))
    # Head.
    edge = bezier((770, 150), (850, 340), (735, 540))
    beard = bezier((735, 540), (600, 470), (562, 350))
    blade = [(548, 200), (690, 160), (770, 150)] + edge + beard + [(548, 345)]
    d.polygon(pts(blade), fill=c["blade"], outline=c["ink"], width=ink)
    bevel = edge + [(x - 46, y) for (x, y) in reversed(edge)]
    d.polygon(pts(bevel), fill=c["edge"])
    d.line(pts([(x - 46, y) for (x, y) in edge]), fill=c["ink"], width=W(3))
    d.line(pts([(x - 12, y + 10) for (x, y) in edge[3:-3]]), fill=c["shine"], width=W(5))
    d.line(pts([(560, 185), (745, 160)]), fill=c["shine"], width=W(6))
    d.polygon(pts(blade), outline=c["ink"], width=ink)
    # The poll behind the eye, the socket round the haft, and the langets with their rivets.
    d.rounded_rectangle(pts([(392, 215), (450, 330)]), radius=W(10), fill=c["edge"], outline=c["ink"], width=ink)
    d.rounded_rectangle(pts([(438, 190), (562, 352)]), radius=W(16), fill=c["blade"], outline=c["ink"], width=ink)
    d.line(pts([(448, 205), (552, 205)]), fill=c["shine"], width=W(5))
    for x0, x1 in ((466, 480), (520, 534)):
        d.rectangle(pts([(x0, 352), (x1, 470)]), fill=c["blade"], outline=c["ink"], width=W(5))
    for y in (380, 420, 455):
        d.ellipse(box(473, y, 6), fill=c["ink"])
        d.ellipse(box(527, y, 6), fill=c["ink"])
    if broken:
        d.line(pts([(700, 170), (660, 260), (720, 340), (670, 430), (700, 530)]), fill=c["ink"], width=W(12), joint="curve")


def might_sceptre(d, c, fate, layer):
    """A sceptre: a slender rod with a spiral, a faceted knop, a flared foot, a
    collar, and a banded gem held in four prongs under an orb and a spike."""
    ink = W(9)
    d.polygon(pts([(482, 310), (518, 310), (524, 860), (476, 860)]), fill=c["guard"], outline=c["ink"], width=ink)
    for y in range(340, 850, 34):
        d.line(pts([(484, y), (518, y + 18)]), fill=c["guard2"], width=W(4))
    d.line(pts([(490, 330), (490, 850)]), fill=c["shine"], width=W(3))
    # The knop, faceted.
    knop = [(500 + 40 * math.cos(math.radians(a)), 470 + 40 * math.sin(math.radians(a))) for a in range(0, 360, 60)]
    d.polygon(pts(knop), fill=c["guard"], outline=c["ink"], width=ink)
    d.line(pts([(470, 470), (530, 470)]), fill=c["guard2"], width=W(4))
    # The foot and the collar.
    d.polygon(pts([(470, 860), (530, 860), (548, 905), (452, 905)]), fill=c["guard"], outline=c["ink"], width=ink)
    d.line(pts([(462, 884), (538, 884)]), fill=c["guard2"], width=W(4))
    d.polygon(pts([(462, 310), (538, 310), (552, 270), (448, 270)]), fill=c["guard"], outline=c["ink"], width=ink)
    d.line(pts([(455, 290), (545, 290)]), fill=c["guard2"], width=W(4))
    # The gem, with a gold band across its middle, and the prongs.
    d.ellipse(box(500, 190, 80), fill=c["gem"], outline=c["ink"], width=ink)
    d.line(pts([(424, 196), (576, 196)]), fill=c["guard"], width=W(10))
    d.line(pts([(424, 196), (576, 196)]), fill=c["ink"], width=W(2))
    for a in (45, 135, 225, 315):
        ax, ay = math.cos(math.radians(a)), math.sin(math.radians(a))
        px, py = -ay, ax
        d.polygon(pts([(500 + ax * 56, 190 + ay * 56), (500 + ax * 98 + px * 16, 190 + ay * 98 + py * 16),
                       (500 + ax * 98 - px * 16, 190 + ay * 98 - py * 16)]), fill=c["guard"], outline=c["ink"], width=W(6))
    d.ellipse(box(500, 92, 22), fill=c["guard"], outline=c["ink"], width=W(8))
    d.ellipse(box(493, 85, 6), fill=c["shine"])
    d.polygon(pts([(500, 28), (514, 72), (486, 72)]), fill=c["guard"], outline=c["ink"], width=W(8))
    if fate == "fortune":
        d.ellipse(box(474, 162, 16), fill="#FFFFFF")
        d.ellipse(box(528, 220, 7), fill="#FFFFFF")
    else:
        d.line(pts([(455, 150), (500, 195), (470, 240), (540, 255)]), fill=c["ink"], width=W(10), joint="curve")


def might_crown(d, c, fate, layer):
    """A crown: a velvet cap behind five curved points, pearls on their tips, a
    jewelled circlet with a beaded upper edge and a turned lower rim."""
    ink = W(10)
    broken = fate == "doom"
    base_y = 575
    # The cap, a dome of velvet behind the points, down to the band.
    d.pieslice(box(500, base_y + 40, 290), 180, 360, fill=c["velvet"], outline=c["ink"], width=W(6))
    bases = [(205, 325), (325, 445), (445, 555), (555, 675), (675, 795)]
    tips = [(245, 300), (385, 410), (500, 180), (615, 410), (755, 300)]
    outline = [(205, base_y)]
    for (x0, x1), (tx, ty) in zip(bases, tips):
        if broken and x0 == 675:
            outline += [(700, 470), (725, 500), (745, 450), (795, base_y)]
            continue
        outline += bezier((x0, base_y), (x0 + (tx - x0) * 0.25, ty + (base_y - ty) * 0.4), (tx, ty))[1:]
        outline += bezier((tx, ty), (x1 - (x1 - tx) * 0.25, ty + (base_y - ty) * 0.4), (x1, base_y))[1:]
    d.polygon(pts(outline + [(795, 700), (205, 700)]), fill=c["guard"], outline=c["ink"], width=ink)
    # Each point's inner edge in the darker gold, so the points read as separate leaves.
    for (x0, x1), (tx, ty) in zip(bases, tips):
        if broken and x0 == 675:
            continue
        d.line(pts(bezier((x0 + 22, base_y), (x0 + 22 + (tx - x0) * 0.25, ty + (base_y - ty) * 0.45), (tx, ty + 30))), fill=c["guard2"], width=W(4))
    # The circlet: a beaded upper edge, the jewels, and a turned rim below.
    d.rounded_rectangle(pts([(205, 575), (795, 770)]), radius=W(22), fill=c["guard"], outline=c["ink"], width=ink)
    for x in range(222, 795, 24):
        d.ellipse(box(x, 592, 7), fill=c["guard2"], outline=c["ink"], width=W(2))
    d.line(pts([(205, 735), (795, 735)]), fill=c["ink"], width=W(5))
    d.line(pts([(215, 752), (785, 752)]), fill=c["guard2"], width=W(5))
    for x, key, r in ((300, "gem", 36), (400, "gem2", 18), (500, "gem2", 36), (600, "gem2", 18), (700, "gem", 36)):
        d.ellipse(box(x, 660, r), fill=c[key], outline=c["ink"], width=W(7))
        d.ellipse(box(x - r * 0.35, 660 - r * 0.35, max(4, r * 0.18)), fill="#FFFFFF" if not broken else c["pearl"])
    # Pearls on the tips.
    for (tx, ty) in tips[:4] + ([tips[4]] if not broken else []):
        d.ellipse(box(tx, ty - 6, 20), fill=c["pearl"], outline=c["ink"], width=W(6))
    if broken:
        d.line(pts([(600, 575), (570, 650), (620, 700), (590, 770)]), fill=c["ink"], width=W(12), joint="curve")


def tools_hammer(d, c, fate, layer):
    """The claw hammer on its own: the 1 of Tools."""
    layer.alpha_composite(_hammer(c, fate == "doom"))


def tools_pick(d, c, fate, layer):
    """A pickaxe: a haft with grain and a steel ferrule, an eye socket with its
    wedge, a long arm drawn to a point and a shorter one to a chisel."""
    ink = W(10)
    broken = fate == "doom"

    def grain(draw, top, bottom):
        for off in (-10, 4, 14):
            draw.line(pts([(500 + off, top), (500 + off, bottom)]), fill=c["grain"], width=W(3))

    if not broken:
        d.polygon(pts([(480, 250), (520, 250), (528, 900), (472, 900)]), fill=c["wood"], outline=c["ink"], width=ink)
        grain(d, 320, 860)
        d.rectangle(pts([(468, 860), (532, 900)]), fill=c["steel"], outline=c["ink"], width=W(6))
    else:
        d.polygon(pts([(480, 250), (520, 250), (524, 580), (502, 620), (526, 640), (478, 620)]), fill=c["wood"], outline=c["ink"], width=ink)
        grain(d, 320, 570)
        piece = new_layer()
        pd = ImageDraw.Draw(piece)
        pd.polygon(pts([(478, 640), (502, 620), (526, 660), (528, 900), (472, 900)]), fill=c["wood"], outline=c["ink"], width=ink)
        pd.rectangle(pts([(468, 860), (532, 900)]), fill=c["steel"], outline=c["ink"], width=W(6))
        piece = piece.rotate(24, resample=Image.BICUBIC, center=pt(500, 660))
        layer.alpha_composite(piece, (W(40), W(0)))
    # The head: the point arm and the chisel arm, each curving down from the socket.
    left = bezier((500, 215), (300, 165), (110, 310))
    right = bezier((500, 215), (690, 170), (860, 290))
    d.polygon(pts(tapered(left, 120, 12)), fill=c["steel"], outline=c["ink"], width=W(9))
    d.polygon(pts(tapered(right, 120, 46)), fill=c["steel"], outline=c["ink"], width=W(9))
    d.polygon(pts([(846, 268), (878, 262), (884, 312), (852, 312)]), fill=c["shade"], outline=c["ink"], width=W(6))
    d.line(pts([(x, y - 22) for (x, y) in left[4:-6]]), fill=c["shine"], width=W(5))
    d.line(pts([(x, y - 22) for (x, y) in right[4:-6]]), fill=c["shine"], width=W(5))
    d.line(pts([(x, y + 26) for (x, y) in left[6:-4]]), fill=c["shade"], width=W(5))
    d.line(pts([(x, y + 26) for (x, y) in right[6:-4]]), fill=c["shade"], width=W(5))
    d.rounded_rectangle(pts([(438, 160), (562, 290)]), radius=W(16), fill=c["steel"], outline=c["ink"], width=ink)
    d.rectangle(pts([(484, 162), (516, 178)]), fill=c["wood"], outline=c["ink"], width=W(4))
    d.line(pts([(452, 276), (548, 276)]), fill=c["shade"], width=W(6))
    if broken:
        d.line(pts([(640, 170), (610, 215), (660, 250), (630, 280)]), fill=c["ink"], width=W(12), joint="curve")


def tools_spade(d, c, fate, layer):
    """A spade: a D-handle, a shaft with grain, a riveted socket, a pointed blade
    with its treads, a centre ridge and a worn edge."""
    ink = W(10)
    broken = fate == "doom"
    # The D-handle: a loop with a grip across the top.
    d.rounded_rectangle(pts([(420, 30), (580, 150)]), radius=W(40), fill=c["wood"], outline=c["ink"], width=ink)
    d.rounded_rectangle(pts([(452, 68), (548, 128)]), radius=W(24), fill=(0, 0, 0, 0))
    d.rounded_rectangle(pts([(452, 68), (548, 128)]), radius=W(24), outline=c["ink"], width=W(6))
    d.line(pts([(440, 50), (560, 50)]), fill=c["grain"], width=W(3))

    def grain(draw, top, bottom):
        for off in (-8, 4, 12):
            draw.line(pts([(500 + off, top), (500 + off, bottom)]), fill=c["grain"], width=W(3))

    if not broken:
        d.polygon(pts([(478, 150), (522, 150), (526, 560), (474, 560)]), fill=c["wood"], outline=c["ink"], width=ink)
        grain(d, 170, 540)
    else:
        d.polygon(pts([(478, 150), (522, 150), (524, 330), (502, 360), (524, 380), (476, 360)]), fill=c["wood"], outline=c["ink"], width=ink)
        grain(d, 170, 320)
        piece = new_layer()
        pd = ImageDraw.Draw(piece)
        pd.polygon(pts([(476, 380), (502, 360), (524, 400), (526, 560), (474, 560)]), fill=c["wood"], outline=c["ink"], width=ink)
        piece = piece.rotate(18, resample=Image.BICUBIC, center=pt(500, 400))
        layer.alpha_composite(piece, (W(30), W(10)))
    # The socket, riveted, and the blade.
    d.polygon(pts([(452, 540), (548, 540), (556, 600), (444, 600)]), fill=c["steel"], outline=c["ink"], width=ink)
    for y in (556, 584):
        d.ellipse(box(470, y, 6), fill=c["ink"])
        d.ellipse(box(530, y, 6), fill=c["ink"])
    blade = [(370, 592), (630, 592), (632, 740), (500, 930), (368, 740)]
    d.polygon(pts(blade), fill=c["steel"], outline=c["ink"], width=ink)
    # Treads along the shoulders, the ridge, the worn bright edge.
    d.polygon(pts([(370, 592), (444, 592), (444, 616), (370, 616)]), fill=c["shade"], outline=c["ink"], width=W(4))
    d.polygon(pts([(556, 592), (630, 592), (630, 616), (556, 616)]), fill=c["shade"], outline=c["ink"], width=W(4))
    d.polygon(pts([(500, 600), (514, 740), (500, 900), (486, 740)]), fill=c["shade"])
    d.line(pts([(500, 600), (500, 900)]), fill=c["ink"], width=W(3))
    d.line(pts([(392, 620), (392, 736)]), fill=c["shine"], width=W(6))
    d.line(pts([(380, 745), (496, 912)]), fill=c["shine"], width=W(6))
    d.line(pts([(504, 912), (620, 745)]), fill=c["shine"], width=W(6))
    if broken:
        d.line(pts([(560, 600), (530, 680), (585, 760), (545, 880)]), fill=c["ink"], width=W(12), joint="curve")


def tools_anvil(d, c, fate, layer):
    """An anvil: the horn, the step down to the table, the face with a hardy hole
    and a pritchel hole, the waist, the feet with their bolt holes."""
    ink = W(10)
    broken = fate == "doom"
    body = [(330, 320), (880, 320), (880, 440), (730, 455), (730, 640), (850, 700), (850, 780),
            (150, 780), (150, 700), (270, 640), (270, 455), (200, 445), (105, 400), (200, 352), (330, 352)]
    d.polygon(pts(body), fill=c["steel"], outline=c["ink"], width=ink)
    # The underside of the face and the table in shadow; the face's edge lit.
    d.polygon(pts([(270, 455), (730, 455), (880, 440), (880, 420), (730, 436), (270, 436)]), fill=c["shade"])
    d.polygon(pts([(200, 352), (330, 352), (330, 366), (210, 366)]), fill=c["shade"])
    d.line(pts([(340, 334), (868, 334)]), fill=c["shine"], width=W(9))
    d.line(pts([(115, 400), (195, 360)]), fill=c["shine"], width=W(5))
    d.line(pts([(330, 320), (330, 352)]), fill=c["ink"], width=W(5))
    # The hardy hole, the pritchel hole, and the feet's bolt holes.
    d.rectangle(pts([(790, 362), (830, 402)]), fill=c["ink"])
    d.ellipse(box(735, 382, 14), fill=c["ink"])
    for x in (205, 795):
        d.ellipse(box(x, 740, 12), fill=c["ink"])
        d.ellipse(box(x - 3, 737, 4), fill=c["shade"])
    d.line(pts([(150, 700), (850, 700)]), fill=c["ink"], width=W(5))
    d.line(pts([(160, 764), (840, 764)]), fill=c["shade"], width=W(5))
    d.line(pts([(285, 470), (285, 630)]), fill=c["shine"], width=W(5))
    if broken:
        d.line(pts([(520, 320), (480, 420), (540, 520), (490, 640), (530, 780)]), fill=c["ink"], width=W(12), joint="curve")


def fools_cap(d, c, fate, layer):
    """The cap on its own: the 1 of Fools."""
    fools(d, c, fate, layer)


def fools_marotte(d, c, fate, layer):
    """A marotte, the fool's bauble: a little jester's head on a stick with ribbons: the 3 of Fools."""
    ink = W(10)
    up = fate == "fortune"
    # The stick, with a collar under the head.
    if up:
        d.polygon(pts([(484, 330), (516, 330), (522, 900), (478, 900)]), fill=c["wood"], outline=c["ink"], width=ink)
    else:
        d.polygon(pts([(484, 330), (516, 330), (518, 600), (498, 630), (520, 650), (482, 630)]), fill=c["wood"], outline=c["ink"], width=ink)
        piece = new_layer()
        pd = ImageDraw.Draw(piece)
        pd.polygon(pts([(482, 650), (498, 630), (520, 670), (522, 900), (478, 900)]), fill=c["wood"], outline=c["ink"], width=ink)
        piece = piece.rotate(22, resample=Image.BICUBIC, center=pt(500, 670))
        layer.alpha_composite(piece, (W(30), W(0)))
    # Ribbons off the collar.
    for sign, colour in ((-1, c["red"]), (1, c["green"])):
        ribbon = bezier((500 + sign * 30, 330), (500 + sign * 160, 420 if up else 380), (500 + sign * 130, 560 if up else 640))
        d.polygon(pts(tapered(ribbon, 34, 14)), fill=colour, outline=c["ink"], width=W(6))
    d.rounded_rectangle(pts([(440, 300), (560, 340)]), radius=W(14), fill=c["band"], outline=c["ink"], width=ink)
    # The head: a round face in a two-pointed cap with bells.
    d.ellipse(box(500, 215, 95), fill=c["skin"], outline=c["ink"], width=ink)
    for sign, colour in ((-1, c["purple"]), (1, c["red"])):
        if up:
            point = bezier((500 + sign * 60, 150), (500 + sign * 190, 120), (500 + sign * 200, 40))
        else:
            point = bezier((500 + sign * 60, 150), (500 + sign * 200, 160), (500 + sign * 200, 290))
        d.polygon(pts(tapered(point, 80, 16)), fill=colour, outline=c["ink"], width=W(7))
        tip = point[-1]
        d.ellipse(box(tip[0], tip[1], 22), fill=c["bell"], outline=c["ink"], width=W(6))
    d.chord(box(500, 215, 95), 180, 360, fill=c["purple"], outline=c["ink"], width=ink)
    d.line(pts([(405, 215), (595, 215)]), fill=c["ink"], width=W(6))
    # The face: grinning for Fortune, glum for Doom.
    for sign in (-1, 1):
        d.ellipse(box(500 + sign * 34, 240, 9), fill=c["ink"])
    if up:
        d.arc(box(500, 250, 48), 15, 165, fill=c["ink"], width=W(8))
    else:
        d.arc(box(500, 300, 44), 200, 340, fill=c["ink"], width=W(8))
    d.ellipse(box(500, 262, 11), fill=c["red"], outline=c["ink"], width=W(3))


def fools_tambourine(d, c, fate, layer):
    """A tambourine: a wooden hoop, a skin, pairs of jingles round the rim: the 6 of Fools."""
    ink = W(10)
    up = fate == "fortune"
    cx, cy, r = 500, 500, 340
    d.ellipse(box(cx, cy, r), fill=c["wood"], outline=c["ink"], width=ink)
    d.ellipse(box(cx, cy, r - 60), fill=c["skin"], outline=c["ink"], width=W(6))
    d.arc(box(cx, cy, r - 30), 200, 320, fill=c["shine"] if "shine" in c else c["band"], width=W(5))
    # Jingles in pairs round the hoop, one pair missing and one hanging for Doom.
    angles = list(range(0, 360, 45))
    for i, a in enumerate(angles):
        if not up and i in (1, 5):
            continue
        ax, ay = math.cos(math.radians(a)), math.sin(math.radians(a))
        for off in (-14, 14):
            jx = cx + (r - 30) * ax + off * -ay
            jy = cy + (r - 30) * ay + off * ax
            d.ellipse(box(jx, jy, 20), fill=c["bell"], outline=c["ink"], width=W(5))
    if up:
        for a in (300, 340, 60):
            ax, ay = math.cos(math.radians(a)), math.sin(math.radians(a))
            for rr in (r + 40, r + 66):
                d.arc(box(cx, cy, rr), a - 10, a + 10, fill=c["ink"], width=W(6))
    else:
        # The skin torn open.
        d.polygon(pts([(380, 420), (470, 470), (430, 560), (520, 540), (560, 640), (600, 520), (660, 560),
                       (620, 440), (560, 400), (500, 440), (440, 380)]), fill=c["ink"])
        d.polygon(pts([(400, 430), (470, 470), (440, 540), (520, 530), (548, 600), (590, 520), (630, 540),
                       (610, 450), (560, 420), (500, 455), (450, 400)]), fill=c["skin"])


def fools_mask(d, c, fate, layer):
    """A theatre mask with ribbons: comedy for Fortune, tragedy for Doom: the 12 of Fools."""
    ink = W(10)
    up = fate == "fortune"
    # Ribbons behind.
    for sign, colour in ((-1, c["purple"]), (1, c["green"])):
        ribbon = bezier((500 + sign * 250, 420), (500 + sign * 420, 520), (500 + sign * 360, 820))
        d.polygon(pts(tapered(ribbon, 44, 18)), fill=colour, outline=c["ink"], width=W(6))
    face = [(290, 300), (330, 230), (420, 180), (500, 168), (580, 180), (670, 230), (710, 300),
            (720, 470), (690, 620), (610, 760), (500, 840), (390, 760), (310, 620), (280, 470)]
    d.polygon(pts(face), fill=c["skin"], outline=c["ink"], width=ink)
    d.polygon(pts([(x + (500 - x) * 0.08, y + (500 - y) * 0.08) for (x, y) in face]), outline=c["band"], width=W(5))
    # Eye holes, brows and the mouth, each turned the mask's way.
    for sign in (-1, 1):
        cx = 500 + sign * 100
        if up:
            d.polygon(pts([(cx - sign * 70, 430), (cx + sign * 60, 400), (cx + sign * 50, 455), (cx - sign * 55, 465)]), fill=c["ink"])
            d.arc(box(cx, 400, 85), 200, 340, fill=c["ink"], width=W(10))
        else:
            d.polygon(pts([(cx - sign * 70, 400), (cx + sign * 60, 430), (cx + sign * 50, 475), (cx - sign * 55, 450)]), fill=c["ink"])
            d.line(pts([(cx - sign * 80, 340), (cx + sign * 40, 380)]), fill=c["ink"], width=W(10))
    if up:
        d.chord(box(500, 600, 130), 10, 170, fill=c["ink"])
        d.chord(box(500, 600, 130), 10, 170, outline=c["ink"], width=W(6))
        d.chord(box(500, 606, 110), 20, 160, fill=c["white"])
    else:
        d.chord(box(500, 720, 130), 190, 350, fill=c["ink"])
    d.ellipse(box(500, 540, 18), fill=c["red"], outline=c["ink"], width=W(4))


# The drawing behind each of Might's, Tools' and Fools' denominations (deck.VARIANTS names them).
DRAWINGS = {"might_sword": might, "might_axe": might_axe, "might_sceptre": might_sceptre, "might_crown": might_crown,
            "tools_hammer": tools_hammer, "tools_pick": tools_pick, "tools_spade": tools_spade, "tools_anvil": tools_anvil,
            "fools_cap": fools_cap, "fools_marotte": fools_marotte, "fools_tambourine": fools_tambourine, "fools_mask": fools_mask}


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
