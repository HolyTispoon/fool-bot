"""
The maneuver tiles: a coach's three maneuvers on one flat tile, played by
turning it so the chosen one points at the other coach, in place of a
hand of maneuver cards (the author, 2026-10-03). Nothing hides the
choice; both coaches cover their tile with a hand and reveal on three.

**Two tiles a coach, each printed double-sided, with the ranks aligned
through the tile** (the author, 2026-10-03): tile 1 is the basic
maneuvers, the offense on one face and the defense on the other; tile 2
is the gambits, the same way. Each defense maneuver sits behind the
offense maneuver of its own rank, so the card a maneuver ties is the one
printed behind it -- which is why a face read after turning the tile over
has its ranks in the mirrored order (1, 3, 2 clockwise).

**The dodecagon is the tile; the hexagon is kept as an alternative**
(the author, 2026-10-03), and goes in the print-and-play kit only where
it is built locally, never on the landing page (2026-10-04). Both are the
same layout: each maneuver takes two sides of the shape, its corner
vertex at the reader's edge.

One maneuver's room reads upright from its corner, and from the corner
inward (the author, 2026-10-03 and 2026-10-04):

- the coloured corner -- on the dodecagon it reaches only the two
  vertices beside the corner -- with the rank in a white tab and the
  maneuver's name over it, both prominent; a gambit's ``ADVANCED ...``
  in two small lines beside the name;
- the card's strip diagram, redrawn wide and short to sit on the corner's
  base, with the time as a pill on its top right;
- then, read top down from the d12 in the middle: a basic maneuver's
  effect, its wins/ties/losses, and the role abilities that name it; a
  gambit's success, its failure, and the tie box beside its wins/ties/
  losses. The effect and the success and failure are the most important,
  and are set largest.

**Round the d12, the cycle** (the author, 2026-10-04): a ring of three
arrows, each running out of its maneuver's sector and across the boundary
into the neighbour whose back holds the card it beats, labelled with that
card; and the rule written round them. Seen from the back, an arrow points
the same way through the tile as its partner on the front, because on
either side a rank beats the rank below it. The ring's wording is this
module's own, not the Charter's (6.3.1 states the cycle as a table), so
`check_rule` holds it against the catalog every time it is drawn.

The d12 in the middle is the coach's colour team's pair from
`d12ball/dice.py`: the Fortune on the basic tile, the Doom on the gambits.

Every word on a tile is the card's own, from the catalog -- the effect,
the gambit halves through `cards.gambit_effect_parts`, the time, the role
abilities through `cards.role_abilities` -- and every matchup is
`ManeuverCatalog.resolve`'s. `scripts/render_maneuver_tiles.py` is the
CLI; see "The maneuver tiles" in docs/design/cards.md.
"""

from __future__ import annotations

import math
from functools import lru_cache
from typing import Callable, Optional

from PIL import Image, ImageChops, ImageDraw, ImageFont

from . import cards, dice
from .boards import PAPERS, PRINT_DPI
from .cards import Pen, StripGeometry
from .components import (
    MANEUVER_TIER_BASIC,
    ManeuverCatalog,
    ManeuverDefinition,
    load_maneuver_catalog,
    load_player_catalog,
)
from .game import Team, team_display_name
from .render import load_font, load_rank_font

INK, MUTED, WHITE = cards.INK, cards.MUTED, "#ffffff"

# The two shapes, by their number of sides.
DODECAGON, HEXAGON = 12, 6
SHAPE_NAMES = {DODECAGON: "dodecagon", HEXAGON: "hexagon"}

# The tile's size: 90 mm from the centre to a corner, so 180 mm across the
# corners -- a letter page's width less its margins. It is laid out at
# `TILE_PX` pixels a radius and set onto the page at `PRINT_DPI`.
TILE_RADIUS_MM = 90
TILE_PX = 1400
D12_MM = 20            # the die in the middle
BAND_MM = 12           # the unit the gaps between blocks are reckoned in
MARGIN_MM = 0.9        # everything in from the region's outline
RIM_PAD = 0.15         # of a block's side pad, along the tile's own edge

# The corner. The rank's tab takes `RANK_SHARE` of the corner's height and
# the name the rest; the hexagon's corner reaches up to where its strip is
# `HEX_STRIP_MM` wide, about the dodecagon's, and its tab is at most
# `HB_MAX_MM` tall there.
RANK_SHARE = 0.53
HEX_STRIP_MM = 76
HB_MAX_MM = 7.0
SUB_MM = 2.0           # a gambit's ADVANCED ... beside the name

# The text: the body is searched from the largest size down; a basic
# maneuver's wins/ties/losses and abilities are a step below it, and the
# tie box a step nearer it (the author, 2026-10-03: the tie read too
# small).
BODY_MAX_MM, BODY_MIN_MM = 5.0, 1.4
SECONDARY = 0.74
TIE_SCALE = 0.86

# Round the d12: the arrow ring, then the rule.
ARROW_RING_MM = 4.4
RULE = "EACH RANK BEATS THE RANK ONE BELOW IT  •  1 BEATS 3  •  SAME RANK TIES  •  "

# The strip, redrawn: the legend columns either side and the padding.
STRIP_LEGEND_W = 190
STRIP_PAD = 12

# The page.
TILE_PAPER = "letter"
BOUNDARY = "#c3cad2"


@lru_cache(maxsize=None)
def catalog() -> ManeuverCatalog:
    return load_maneuver_catalog()


@lru_cache(maxsize=None)
def players():
    return load_player_catalog()


def color_of(maneuver: ManeuverDefinition, offense: bool) -> str:
    if maneuver.is_gambit:
        return cards.OFFENSE_COLOR_GAMBIT if offense else cards.DEFENSE_COLOR_GAMBIT
    return cards.OFFENSE_COLOR if offense else cards.DEFENSE_COLOR


def rank_label(maneuver: ManeuverDefinition, offense: bool) -> str:
    return f"{'O' if offense else 'D'}{maneuver.rank}"


def opponents(maneuver: ManeuverDefinition, offense: bool) -> list[tuple[str, ManeuverDefinition]]:
    """The other side's three basic cards as BEATS, TIES and LOSES TO,
    each as `ManeuverCatalog.resolve` has it -- a gambit's are its basic
    card's, since rank alone decides."""
    cat = catalog()
    other = "defense" if offense else "offense"
    mine = "offense" if offense else "defense"
    out = {}
    for o in cat.for_tier(other, MANEUVER_TIER_BASIC):
        result = cat.resolve(maneuver.key, o.key) if offense else cat.resolve(o.key, maneuver.key)
        out["TIES" if result == "tie" else ("BEATS" if result == mine else "LOSES TO")] = o
    return [(k, out[k]) for k in ("BEATS", "TIES", "LOSES TO")]


def check_rule() -> None:
    """`RULE` is this module's wording, so it is held against the catalog:
    on either side each rank beats the other side's rank below it, 1 beats
    3, and a rank ties itself."""
    for side in ("offense", "defense"):
        for m in catalog().for_tier(side, MANEUVER_TIER_BASIC):
            got = {k: o.rank for k, o in opponents(m, side == "offense")}
            want = {"BEATS": (m.rank - 2) % 3 + 1, "TIES": m.rank, "LOSES TO": m.rank % 3 + 1}
            if got != want:
                raise ValueError(f"the tiles' cycle no longer holds for {m.name}: {got}")


# ---- geometry ----------------------------------------------------------------
Point = tuple[float, float]


def inset_edges(poly: list[Point], amounts: list[float]) -> list[Point]:
    """A convex polygon with its edge i (poly[i] to poly[i+1]) moved in by amounts[i]."""
    n = len(poly)
    cx = sum(p[0] for p in poly) / n
    cy = sum(p[1] for p in poly) / n
    lines = []
    for i in range(n):
        (x0, y0), (x1, y1) = poly[i], poly[(i + 1) % n]
        dx, dy = x1 - x0, y1 - y0
        length = math.hypot(dx, dy)
        nx, ny = -dy / length, dx / length
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        if (cx - mx) * nx + (cy - my) * ny < 0:
            nx, ny = -nx, -ny
        lines.append(((x0 + nx * amounts[i], y0 + ny * amounts[i]), (dx, dy)))
    out = []
    for i in range(n):
        (p, d1), (q, d2) = lines[i - 1], lines[i]
        den = d1[0] * d2[1] - d1[1] * d2[0]
        s = ((q[0] - p[0]) * d2[1] - (q[1] - p[1]) * d2[0]) / den
        out.append((p[0] + d1[0] * s, p[1] + d1[1] * s))
    return out


def xspan(poly: list[Point], y: float) -> Optional[tuple[float, float]]:
    xs = []
    n = len(poly)
    for i in range(n):
        (x0, y0), (x1, y1) = poly[i], poly[(i + 1) % n]
        if (y0 - y) * (y1 - y) <= 0 and y0 != y1:
            xs.append(x0 + (y - y0) * (x1 - x0) / (y1 - y0))
    return (min(xs), max(xs)) if len(xs) >= 2 else None


def _clip(pts: list[Point], keep, cross) -> list[Point]:
    out = []
    for i in range(len(pts)):
        a, b = pts[i - 1], pts[i]
        if keep(b):
            if not keep(a):
                out.append(cross(a, b))
            out.append(b)
        elif keep(a):
            out.append(cross(a, b))
    return out


def clip_slab(poly: list[Point], ytop: float, ybot: float) -> list[Point]:
    """A polygon cut to the band ytop <= y <= ybot."""
    at = lambda yv: lambda a, b: (a[0] + (yv - a[1]) * (b[0] - a[0]) / (b[1] - a[1]), yv)
    pts = _clip(poly, lambda p: p[1] >= ytop, at(ytop))
    return _clip(pts, lambda p: p[1] <= ybot, at(ybot)) if pts else []


def clip_x(poly: list[Point], xmin: float, xmax: float) -> list[Point]:
    """A polygon cut to the band xmin <= x <= xmax."""
    at = lambda xv: lambda a, b: (xv, a[1] + (xv - a[0]) * (b[1] - a[1]) / (b[0] - a[0]))
    pts = _clip(poly, lambda q: q[0] >= xmin, at(xmin))
    return _clip(pts, lambda q: q[0] <= xmax, at(xmax)) if pts else []


class Region:
    """
    One maneuver's room, drawn as if it were at the bottom of the tile:
    the centre, then the tile's vertices round to its corner and on to the
    boundary with its other neighbour. `t` counts up from the corner.
    `outer` is the outline in by the margin; `inner` is where a block's
    text may go -- its sides a pad in from the boundaries with the
    neighbours, and only a little of one from the tile's own edge, so the
    boxes run out to the rim.
    """

    def __init__(self, c: float, radius: float, poly: list[Point], margin: float, pad: float):
        self.c, self.margin, self.pad = c, margin, pad
        self.yC = c + radius
        n = len(poly)
        rim = [0 < i < n - 1 for i in range(n)]
        self.outer = inset_edges(poly, [margin] * n)
        self.inner = inset_edges(poly, [margin + (pad * RIM_PAD if r else pad) for r in rim])
        self.tip = self.outer[n // 2]

    def y(self, t: float) -> float:
        return self.yC - t

    def _half(self, poly: list[Point], t: float) -> float:
        sp = xspan(poly, self.y(t))
        return 0.0 if sp is None else (sp[1] - sp[0]) / 2

    def half(self, t: float) -> float:
        return self._half(self.inner, t)

    def half_outer(self, t: float) -> float:
        return self._half(self.outer, t)

    def span(self, tb: float, tt: float) -> float:
        return 2 * min(self.half(tb), self.half(tt))

    def band(self, t0: float, t1: float) -> list[Point]:
        """The region's inner outline between t0 and t1: a box's shape."""
        return clip_slab(self.inner, self.y(t1), self.y(t0))


# ---- words -------------------------------------------------------------------
Word = tuple[str, ImageFont.ImageFont, str, bool]   # the word, its font, its fill, a break before it


def plain_words(text: str, size: int, fill: str = INK) -> list[Word]:
    f = load_font(size)
    return [(w, f, fill, False) for w in text.split()]


def ability_words(maneuver: ManeuverDefinition, size: int) -> list[Word]:
    reg, bold = load_font(size), load_font(size, bold=True)
    out: list[Word] = []
    for i, (role, text) in enumerate(cards.role_abilities(players(), maneuver)):
        out.append((role, bold, INK, i > 0))
        out.extend((w, reg, MUTED, False) for w in text.split())
    return out


def wrap_widths(draw: ImageDraw.ImageDraw, words: list[Word], widths: list[float]):
    """Greedy wrap into lines as wide as `widths`; None if it overflows them."""
    lines, cur, w_cur, li = [], [], 0, 0
    space = lambda f: draw.textlength(" ", font=f)
    for word, f, fill, brk in words:
        wl = draw.textlength(word, font=f)
        add = wl if not cur else w_cur + space(f) + wl
        if cur and (brk or add > widths[li]):
            lines.append(cur)
            li += 1
            if li >= len(widths):
                return None
            cur, w_cur = [], 0
            add = wl
        if add > widths[li]:
            return None
        cur.append((word, f, fill))
        w_cur = add
    lines.append(cur)
    return lines


def draw_line(draw: ImageDraw.ImageDraw, line, cx: float, y: float) -> None:
    """One wrapped line, centred on cx, on its baseline y."""
    sp = lambda f: draw.textlength(" ", font=f)
    total = sum(draw.textlength(w, font=f) for w, f, _ in line) + sum(sp(f) for _, f, _ in line[1:])
    x = cx - total / 2
    for w, f, fill in line:
        draw.text((x, y), w, font=f, fill=fill, anchor="ls")
        x += draw.textlength(w, font=f) + sp(f)


def gambit_texts(maneuver: ManeuverDefinition) -> dict[str, str]:
    """A gambit's three boxes' words: the card's own success and failure,
    and the tie, which resolves as the basic card on its rank (Law 19.4)."""
    success, failure = cards.gambit_effect_parts(maneuver)
    basic = catalog().counterpart(maneuver)
    return {"success": success, "failure": failure or "",
            "tie": f"Resolves as {basic.name}: {basic.effect}"}


# ---- the strip ---------------------------------------------------------------
@lru_cache(maxsize=None)
def tile_strip(key: str) -> Image.Image:
    """The card's strip diagram redrawn wide and short for a tile, the
    legend beside the spaces rather than above them, with no outline of
    its own so it is one field with the band it sits in."""
    maneuver = catalog().by_key()[key]
    moves = cards.STRIP_MOVES[key]
    spaces, ball = cards.STRIP_GEOMETRY[maneuver.tier]
    space_w, strip_h, caption_line = 92, 76, 25
    rows = sorted({mv.caption_row for mv in moves})
    row_lines = {r: max(len(mv.label.split("\n")) for mv in moves if mv.caption_row == r) for r in rows}
    row_top, cursor = {}, 0.0
    for r in rows:
        row_top[r] = cursor
        cursor += row_lines[r] * caption_line
    label_room = cursor + 10
    tallest = max(cards.arc_rise(mv) for mv in moves)
    above = max(0.0, tallest / 2 + 12 + 30 - strip_h / 2) + 6
    left = STRIP_PAD + STRIP_LEGEND_W
    right = left + spaces * space_w
    width = right + STRIP_LEGEND_W + STRIP_PAD
    strip_top = STRIP_PAD + above
    height = strip_top + strip_h + label_room + STRIP_PAD
    pen = Pen((width, height), cards.PANEL_COLOR)
    geo = StripGeometry(left=left, right=right, space_width=space_w, strip_top=strip_top,
                        strip_height=strip_h, ball_space=ball, forward=1 if cards.ATTACK_RIGHT else -1,
                        spaces=spaces, caption_line=caption_line, row_top=row_top)
    standing, landings = cards.STRIP_ACTORS[key]
    cards.draw_strip_spaces(pen, geo)
    for mv in moves:
        cards.draw_strip_arc(pen, geo, mv, cards.SIDE_COLORS[mv.side])
    cards.draw_strip_landings(pen, geo, moves, landings)
    cards.draw_strip_ball_space(pen, geo, standing)
    mid = strip_top + strip_h / 2
    lf = cards.font(26)
    pen.text((left - 14, mid - 17), "H handler", lf, MUTED, anchor="rm")
    pen.text((left - 14, mid + 17), "C challenger", lf, MUTED, anchor="rm")
    pen.text((right + 14, mid - 17), "offense", lf, MUTED, anchor="lm")
    pen.text((right + 14, mid + 17), "attacks →" if cards.ATTACK_RIGHT else "← attacks", lf, MUTED, anchor="lm")
    return pen.image.convert("RGB")


@lru_cache(maxsize=None)
def strip_ink(key: str) -> Image.Image:
    """Where the strip has anything drawn, so the time pill keeps off it."""
    s = tile_strip(key)
    diff = ImageChops.difference(s, Image.new("RGB", s.size, cards.PANEL_COLOR)).convert("L")
    return diff.point(lambda v: 255 if v > 18 else 0)


# ---- the blocks above the strip -------------------------------------------------
# Each measures itself from t upward and returns (height, painter), or None
# where it does not fit at that size.
Block = Optional[tuple[float, Callable[[Image.Image], None]]]


def block_effect(draw, d: Region, maneuver, offense, t, s) -> Block:
    """A basic maneuver's effect, plain, in lines that follow the region's outline."""
    words = plain_words(maneuver.effect, s)
    lh = s * 1.28
    for n in range(1, 16):
        widths = [d.span(t + (n - k - 1) * lh, t + (n - k) * lh) for k in range(n)]
        if min(widths) <= 0:
            return None
        lines = wrap_widths(draw, words, widths)
        if lines:
            def paint(img, lines=lines, n=n):
                dd = ImageDraw.Draw(img)
                for k, line in enumerate(lines):
                    draw_line(dd, line, d.c, d.y(t + (n - k - 1) * lh + lh * 0.28))
            return n * lh, paint
    return None


def block_box(draw, d: Region, t, s, words_fn, heading=None, head_fill=MUTED, fill=WHITE, outline=None) -> Block:
    """A band across the region, its sides the region's, a heading over wrapped text."""
    lh = s * 1.28
    inner = s * 0.55
    hs = max(8, int(s * 0.66))
    hh = hs * 1.45 if heading else 0
    words = words_fn(s)
    for n in range(1, 16):
        h = inner * 2 + hh + n * lh
        spans = [d.span(t + inner + (n - k - 1) * lh, t + inner + (n - k) * lh) - 2 * inner for k in range(n)]
        if min(spans) <= s * 5 or d.half(t + h) <= s * 3:
            return None
        lines = wrap_widths(draw, words, spans)
        if lines:
            def paint(img, lines=lines, h=h, n=n):
                dd = ImageDraw.Draw(img)
                dd.polygon(d.band(t, t + h), fill=fill, outline=outline or cards.PAPER_EDGE, width=4)
                if heading:
                    dd.text((d.c, d.y(t + h - inner - hh * 0.5)), heading, font=load_font(hs, bold=True),
                            fill=head_fill, anchor="mm")
                for k, line in enumerate(lines):
                    draw_line(dd, line, d.c, d.y(t + inner + (n - k - 1) * lh + lh * 0.28))
            return h, paint
    return None


def block_matchups(draw, d: Region, maneuver, offense, t, s) -> Block:
    """BEATS / TIES / LOSES TO, a column each: the label, then the rank large
    beside the basic card's name and its gambit's."""
    ls, rs, ns = max(8, int(s * 0.72)), int(s * 1.9), max(8, int(s * 0.95))
    inner = s * 0.45
    body = max(rs * 1.0, ns * 1.2 * 2)
    h = inner * 2 + ls * 1.35 + body
    w = 2 * d.half(t + h) - 2 * inner
    cols = opponents(maneuver, offense)
    col_w = w / 3
    nf = load_font(ns, bold=True)
    rf = load_rank_font(rs)
    cat = catalog()
    need = max(draw.textlength(f"O{o.rank}", font=rf) + ns * 0.5
               + max(draw.textlength(o.name, font=nf), draw.textlength(cat.counterpart(o).name, font=nf))
               for _, o in cols) + inner
    if need > col_w:
        return None

    def paint(img):
        dd = ImageDraw.Draw(img)
        dd.polygon(d.band(t, t + h), fill=cards.PAPER_PANEL, outline=cards.PAPER_EDGE, width=4)
        x0 = d.c - w / 2
        y0 = d.y(t + h) + inner
        for i, (k, o) in enumerate(cols):
            cx = x0 + col_w * (i + 0.5)
            if i:
                dd.line([(x0 + col_w * i, y0), (x0 + col_w * i, d.y(t) - inner)], fill=cards.PAPER_EDGE, width=3)
            dd.text((cx, y0), k, font=load_font(ls, bold=True), fill=MUTED, anchor="ma")
            o_off = not offense
            rank = rank_label(o, o_off)
            g = cat.counterpart(o)
            rw = dd.textlength(rank, font=rf)
            nw = max(dd.textlength(o.name, font=nf), dd.textlength(g.name, font=nf))
            left = cx - (rw + ns * 0.5 + nw) / 2
            mid = y0 + ls * 1.35 + body / 2
            dd.text((left, mid), rank, font=rf, fill=color_of(o, o_off), anchor="lm")
            nx = left + rw + ns * 0.5
            dd.text((nx, mid - ns * 0.62), o.name, font=nf, fill=INK, anchor="lm")
            dd.text((nx, mid + ns * 0.62), g.name, font=nf, fill=color_of(g, o_off), anchor="lm")
    return h, paint


def matchup_layouts(draw, maneuver, offense, s):
    """The ways BEATS / TIES / LOSES TO can sit beside the tie box:
    (height, width it needs, painter, its padding) -- the rank beside its
    two names, or everything in a column."""
    ls, rs, ns = max(8, int(s * 0.72)), int(s * 1.9), max(8, int(s * 0.95))
    inner = s * 0.45
    cols = opponents(maneuver, offense)
    lf, rf, nf = load_font(ls, bold=True), load_rank_font(rs), load_font(ns, bold=True)
    o_off = not offense
    cat = catalog()
    out = []
    body = max(rs * 1.0, ns * 1.2 * 2)
    h = inner * 2 + ls * 1.35 + body
    col = max(draw.textlength(rank_label(o, o_off), font=rf) + ns * 0.5
              + max(draw.textlength(o.name, font=nf), draw.textlength(cat.counterpart(o).name, font=nf))
              for _, o in cols) + ns * 0.8

    def beside(dd, x0, y0, x1):
        cw = (x1 - x0) / 3
        for i, (k, o) in enumerate(cols):
            cx = x0 + cw * (i + 0.5)
            if i:
                dd.line([(x0 + cw * i, y0), (x0 + cw * i, y0 + h - 2 * inner)], fill=cards.PAPER_EDGE, width=3)
            dd.text((cx, y0), k, font=lf, fill=MUTED, anchor="ma")
            g = cat.counterpart(o)
            rw = dd.textlength(rank_label(o, o_off), font=rf)
            nw = max(dd.textlength(o.name, font=nf), dd.textlength(g.name, font=nf))
            left = cx - (rw + ns * 0.5 + nw) / 2
            mid = y0 + ls * 1.35 + body / 2
            dd.text((left, mid), rank_label(o, o_off), font=rf, fill=color_of(o, o_off), anchor="lm")
            nx = left + rw + ns * 0.5
            dd.text((nx, mid - ns * 0.62), o.name, font=nf, fill=INK, anchor="lm")
            dd.text((nx, mid + ns * 0.62), g.name, font=nf, fill=color_of(g, o_off), anchor="lm")
    out.append((h, 3 * col + 2 * inner, beside, inner))
    h2 = inner * 2 + ls * 1.35 + rs * 1.1 + ns * 1.25 * 2
    col2 = max(max(draw.textlength(k, font=lf), draw.textlength(rank_label(o, o_off), font=rf),
                   draw.textlength(o.name, font=nf), draw.textlength(cat.counterpart(o).name, font=nf))
               for k, o in cols) + ns * 0.8

    def stacked(dd, x0, y0, x1):
        cw = (x1 - x0) / 3
        for i, (k, o) in enumerate(cols):
            cx = x0 + cw * (i + 0.5)
            if i:
                dd.line([(x0 + cw * i, y0), (x0 + cw * i, y0 + h2 - 2 * inner)], fill=cards.PAPER_EDGE, width=3)
            g = cat.counterpart(o)
            y = y0
            dd.text((cx, y), k, font=lf, fill=MUTED, anchor="ma")
            y += ls * 1.35
            dd.text((cx, y), rank_label(o, o_off), font=rf, fill=color_of(o, o_off), anchor="ma")
            y += rs * 1.1
            dd.text((cx, y), o.name, font=nf, fill=INK, anchor="ma")
            y += ns * 1.25
            dd.text((cx, y), g.name, font=nf, fill=color_of(g, o_off), anchor="ma")
    out.append((h2, 3 * col2 + 2 * inner, stacked, inner))
    return out


def block_tie_matchups(draw, d: Region, maneuver, offense, t, s) -> Block:
    """A gambit's tie box and its BEATS / TIES / LOSES TO side by side in one
    band, the tie first as it is read (the author, 2026-10-03)."""
    st = max(8, int(s * TIE_SCALE))
    sm = max(8, int(s * SECONDARY / 0.9))
    words = plain_words(gambit_texts(maneuver)["tie"], st)
    lh, inner_t = st * 1.28, st * 0.55
    hs = max(8, int(st * 0.66))
    hh = hs * 1.45
    g = s * 0.35
    best = None
    for mh, mneed, mpaint, minner in matchup_layouts(draw, maneuver, offense, sm):
        for n in range(1, 14):
            tie_h = 2 * inner_t + hh + n * lh
            h = max(tie_h, mh)
            width = d.span(t, t + h)
            xl, xr = d.c - width / 2, d.c + width / 2
            xs = xr - mneed - g / 2
            tie_w = xs - g / 2 - xl - 2 * inner_t
            if tie_w < st * 6:
                break
            lines = wrap_widths(draw, words, [tie_w] * n)
            if lines:
                if best is None or h < best[0]:
                    best = (h, xs, xl, xr, lines, tie_h, mh, mpaint, minner)
                break
    if best is None:
        return None
    h, xs, xl, xr, lines, tie_h, mh, mpaint, minner = best

    def paint(img):
        dd = ImageDraw.Draw(img)
        poly = d.band(t, t + h)
        dd.polygon(clip_x(poly, -1e9, xs - g / 2), fill=WHITE, outline=cards.PAPER_EDGE, width=4)
        dd.polygon(clip_x(poly, xs + g / 2, 1e9), fill=cards.PAPER_PANEL, outline=cards.PAPER_EDGE, width=4)
        tx = (xl + xs - g / 2) / 2
        top = d.y(t + h) + (h - tie_h) / 2 + inner_t
        dd.text((tx, top + hh * 0.5), "TIE", font=load_font(hs, bold=True), fill=MUTED, anchor="mm")
        y = top + hh + lh * 0.78
        for line in lines:
            draw_line(dd, line, tx, y)
            y += lh
        mtop = d.y(t + h) + (h - mh) / 2 + minner
        mpaint(dd, xs + g / 2 + minner, mtop, xr - minner)
    return h, paint


def make_block(kind, draw, d: Region, maneuver, offense, t, s) -> Block:
    if kind == "effect":
        return block_effect(draw, d, maneuver, offense, t, s)
    if kind == "matchups":
        return block_matchups(draw, d, maneuver, offense, t, int(s * SECONDARY / 0.9))
    if kind == "abilities":
        if not cards.role_abilities(players(), maneuver):
            return 0, lambda img: None
        return block_box(draw, d, t, int(s * SECONDARY), lambda z: ability_words(maneuver, z), fill=cards.PAPER_PANEL)
    if kind == "tie+matchups":
        return block_tie_matchups(draw, d, maneuver, offense, t, s)
    texts = gambit_texts(maneuver)
    col = color_of(maneuver, offense)
    if kind == "success":
        return block_box(draw, d, t, s, lambda z: plain_words(texts["success"], z), "SUCCESS", col, WHITE, col)
    if kind == "failure":
        return block_box(draw, d, t, s, lambda z: plain_words(texts["failure"], z), "FAILURE", MUTED,
                         cards.PAPER_PANEL, cards.PAPER_EDGE)
    raise KeyError(kind)


# Stacked from the strip inward, so the last block is the top of the room as
# it is read: effect, wins/ties/losses, abilities; success, failure, then the
# tie beside the wins/ties/losses (the author, 2026-10-03).
ARRANGEMENTS = {
    False: ("abilities", "matchups", "effect"),
    True: ("tie+matchups", "failure", "success"),
}


def stack(draw, d: Region, maneuver, offense, t0, t_max, s, gap, lift=0.0):
    """The blocks from t0 up, the last raised by `lift`; their painters, or
    None where they do not fit under t_max at size s."""
    kinds = ARRANGEMENTS[maneuver.is_gambit]
    t, paints = t0, []
    for i, kind in enumerate(kinds):
        if i == len(kinds) - 1:
            t += lift
        r = make_block(kind, draw, d, maneuver, offense, t, s)
        if r is None:
            return None
        h, paint = r
        paints.append(paint)
        t += h + (gap if h else 0)
    if t - gap > t_max:
        return None
    return paints


# ---- the corner, and the strip band on it -------------------------------------------
def corner(draw, d: Region, maneuver, offense, mm, vertex_line) -> float:
    """
    The coloured corner: the rank's white tab in the tip and the name over
    it, about level with each other (the author, 2026-10-04: neither too
    small), and a gambit's ADVANCED ... in two lines left of the name. On
    the dodecagon the colour stops at the line between the two vertices
    beside the corner (2026-10-03); on the hexagon it reaches up to where
    the strip on it is as wide as the dodecagon's. Returns that height.
    """
    col = color_of(maneuver, offense)
    t_tip = d.yC - d.tip[1]
    g_lo, g_mid, g_hi = 0.45 * mm, 0.35 * mm, 0.35 * mm
    n_o = len(d.outer)

    def edge_gap(p):
        out = []
        for q in (d.outer[n_o // 2 - 1], d.outer[n_o // 2 + 1]):
            (x0, y0), (x1, y1) = d.tip, q
            out.append(abs((x1 - x0) * (y0 - p[1]) - (x0 - p[0]) * (y1 - y0)) / math.hypot(x1 - x0, y1 - y0))
        return min(out)

    def seat(hb):
        """The tab of height hb, as low as it sits with colour all round it."""
        rf = load_rank_font(int(hb * 0.92))
        # every tab as wide as the widest rank's, so all six corners match
        tab_w = max(draw.textlength(f"{s}{k}", font=rf) for s in "OD" for k in "123") + hb * 0.62
        r = hb * 0.42
        t_b = t_tip + g_lo
        while edge_gap((d.c + tab_w / 2 - r, d.y(t_b + r))) < r + 0.55 * mm:
            t_b += 0.1 * mm
        return rf, tab_w, t_b

    if vertex_line:
        t1 = d.yC - d.outer[n_o // 2 - 1][1]
    else:
        t1 = t_tip
        while 2 * d.half_outer(t1) < HEX_STRIP_MM * mm:
            t1 += 0.1 * mm
    hb = min((t1 - t_tip) * 0.7, HB_MAX_MM * mm)
    while True:
        rf, tab_w, t_b = seat(hb)
        row_h = min(t1 - g_hi - (t_b + hb + g_mid), hb * (1 - RANK_SHARE) / RANK_SHARE * 1.15)
        if row_h >= hb * (1 - RANK_SHARE) / RANK_SHARE:
            break
        hb -= 0.1 * mm
    t_b += (t1 - g_hi - (t_b + hb + g_mid + row_h)) / 2
    row_b = t_b + hb + g_mid
    row_t = row_b + row_h
    size = int(row_h * 0.98)
    nf = load_font(size, bold=True)
    while draw.textlength(maneuver.name, font=nf) > 2 * d.half_outer(row_b) - 2.5 * mm:
        size -= 2
        nf = load_font(size, bold=True)
    if vertex_line:
        draw.polygon([d.outer[n_o // 2 + 1], d.tip, d.outer[n_o // 2 - 1]], fill=col)
    else:
        draw.polygon(clip_slab(d.outer, d.y(t1), d.y(0)), fill=col)
    draw.rounded_rectangle((d.c - tab_w / 2, d.y(t_b + hb), d.c + tab_w / 2, d.y(t_b)), radius=hb * 0.42, fill=WHITE)
    draw.text((d.c, d.y(t_b + hb / 2)), rank_label(maneuver, offense), font=rf, fill=col, anchor="mm")
    ny = d.y((row_b + row_t) / 2)
    nx = d.c
    if maneuver.is_gambit:
        # right-aligned against the name; where the corner is too narrow
        # there the name moves right, and shrinks only if it must
        sub = ["ADVANCED", catalog().counterpart(maneuver).name.upper()]
        sf = load_font(int(SUB_MM * mm), bold=True)
        sub_w = max(draw.textlength(x, font=sf) for x in sub)
        lh = SUB_MM * 1.12 * mm
        gap = 1.3 * mm
        low = (row_b + row_t) / 2 - lh
        while True:
            nw = draw.textlength(maneuver.name, font=nf)
            shift = max(0.0, sub_w + gap + nw / 2 - (d.half_outer(low) - 1.4 * mm))
            if shift + nw / 2 <= d.half_outer(row_b) - 1.2 * mm:
                break
            size -= 2
            nf = load_font(size, bold=True)
        nx = d.c + shift
        sx = nx - nw / 2 - gap
        draw.text((sx, ny - lh / 2), sub[0], font=sf, fill=WHITE, anchor="rm")
        draw.text((sx, ny + lh / 2), sub[1], font=sf, fill=WHITE, anchor="rm")
    draw.text((nx, ny), maneuver.name, font=nf, fill=WHITE, anchor="mm")
    return t1


def strip_band(img, d: Region, maneuver, offense, t1, mm) -> float:
    """The strip on the corner's base, as wide as the corner there, in a
    band that follows the region out; the time a pill on its top right
    (the author, 2026-10-04), raised clear of the drawing where it must
    be. Returns the band's top."""
    draw = ImageDraw.Draw(img)
    col = color_of(maneuver, offense)
    strip, inked = tile_strip(maneuver.key), strip_ink(maneuver.key)
    sw = 2 * d.half_outer(t1)
    k = strip.width / sw
    sh = strip.height / k
    tf = load_font(int(2.2 * mm), bold=True)
    tt = f"TIME · {cards.time_cost(maneuver)}"
    pw, ph = draw.textlength(tt, font=tf) + 2.4 * mm, 3.5 * mm
    x0, ystrip = d.c - sw / 2, d.y(t1 + sh)

    def clear(box):
        bx0, by0 = max(0, (box[0] - x0) * k), max(0, (box[1] - ystrip) * k)
        bx1, by1 = min(strip.width, (box[2] - x0) * k), min(strip.height, (box[3] - ystrip) * k)
        if bx1 <= bx0 or by1 <= by0:
            return True
        return inked.crop((int(bx0), int(by0), int(bx1), int(by1))).getbbox() is None

    extra = 0.0
    while True:
        top = t1 + sh + extra
        pb = top - 0.8 * mm - ph
        xr = d.c + d.half_outer(pb) - 1.2 * mm
        pill = (xr - pw, d.y(pb + ph), xr, d.y(pb))
        if clear(pill):
            break
        extra += 0.2 * mm
    draw.polygon(clip_slab(d.outer, d.y(top), d.y(t1)), fill=cards.PANEL_COLOR)
    img.paste(strip.resize((round(sw), round(sh)), Image.LANCZOS), (round(x0), round(ystrip)))
    draw.rounded_rectangle(pill, radius=ph / 2, fill=col)
    draw.text(((pill[0] + pill[2]) / 2, (pill[1] + pill[3]) / 2), tt, font=tf, fill=WHITE, anchor="mm")
    return top


def region(img, maneuver, offense, d: Region, t_max, mm, vertex_line) -> float:
    """One maneuver's room, drawn at the bottom of `img`; its body size."""
    draw = ImageDraw.Draw(img)
    gap = BAND_MM * mm * 0.14
    t1 = corner(draw, d, maneuver, offense, mm, vertex_line)
    t0 = strip_band(img, d, maneuver, offense, t1, mm) + gap
    for s in range(int(BODY_MAX_MM * mm), int(BODY_MIN_MM * mm) - 1, -1):
        if stack(draw, d, maneuver, offense, t0, t_max, s, gap) is not None:
            # the top block into the middle of whatever room is left over it
            lo, hi = 0.0, t_max - t0
            for _ in range(24):
                mid = (lo + hi) / 2
                lo, hi = (mid, hi) if stack(draw, d, maneuver, offense, t0, t_max, s, gap, mid) else (lo, mid)
            for paint in stack(draw, d, maneuver, offense, t0, t_max, s, gap, lo / 2):
                paint(img)
            return s / mm
    raise ValueError(f"{maneuver.name} does not fit on its tile")


# ---- round the d12 -------------------------------------------------------------
def arc_text(img, text, font, r_base, a_start, fill, spacing=0.0) -> None:
    """Text round the tile's centre, tops towards it, reading anticlockwise
    on screen -- upright for a reader outside the circle, as a region's own
    text is from its corner. Its baseline is on r_base; it starts at
    a_start, in degrees clockwise from three o'clock."""
    c = img.width / 2
    a = math.radians(a_start)
    for ch in text:
        w = font.getlength(ch) + spacing
        am = a - (w / 2) / r_base
        if ch.strip():
            size = int(font.size * 3)
            g = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            ImageDraw.Draw(g).text((size / 2, size / 2), ch, font=font, fill=fill, anchor="ms")
            g = g.rotate(90 - math.degrees(am), resample=Image.BICUBIC)
            x, y = c + r_base * math.cos(am), c + r_base * math.sin(am)
            img.alpha_composite(g, (round(x - g.width / 2), round(y - g.height / 2)))
        a -= w / r_base


def text_length(text, font) -> float:
    return sum(font.getlength(ch) for ch in text)


def arrow(img, maneuver, offense, back, i, r0, r1, mm) -> None:
    """Region i's arrow, drawn as if the region were at the bottom: out of
    its own sector and across the boundary into the neighbour whose back
    holds the card it beats -- found from where that card is on the back,
    not assumed -- labelled BEATS D3 or the like."""
    beaten = dict(opponents(maneuver, offense))["BEATS"]
    j = [o.rank for o in back].index(beaten.rank)   # a gambit beats what its basic card beats
    # the back's region j shows through at 90 - 120j; in region i's own frame
    delta = (-120 * j - 120 * i) % 360
    if delta not in (120, 240):
        raise ValueError(f"{maneuver.name} beats the card behind itself")
    sense = 1 if delta == 120 else -1          # +1 clockwise on screen
    a_in = 90 - sense * 60
    rm = (r0 + r1) / 2
    past, gap = 13, 17                         # degrees: the head past the boundary, the tail's gap
    c = img.width / 2
    at = lambda phi: math.radians(a_in + sense * phi)
    P = lambda r, phi: (c + r * math.cos(at(phi)), c + r * math.sin(at(phi)))
    col = color_of(maneuver, offense)
    dr = ImageDraw.Draw(img)
    dr.polygon([P(r1, p) for p in range(gap, 121)] + [P(r0, p) for p in range(120, gap - 1, -1)], fill=col)
    dr.polygon([P(r0 - 0.5 * mm, 120), P(rm, 120 + past), P(r1 + 0.5 * mm, 120)], fill=col)
    label = f"BEATS {rank_label(beaten, not offense)}"
    f = load_font(int((r1 - r0) * 0.56), bold=True)
    rb = rm + f.size * 0.36
    length = text_length(label, f) + 0.25 * mm * (len(label) - 1)
    mid = a_in + sense * (gap + 120) / 2
    arc_text(img, label, f, rb, mid + math.degrees(length / 2 / rb), WHITE, 0.25 * mm)


# ---- a face, and a page ------------------------------------------------------------
def face_order(side: str, tier: str) -> list[ManeuverDefinition]:
    """A face's three maneuvers clockwise from the bottom: the offense in
    rank order, the defense, read from the back, 1, 3, 2."""
    ms = list(catalog().for_tier(side, tier))
    return ms if side == "offense" else [ms[j] for j in (0, 2, 1)]


def tile_face(sides: int, side: str, tier: str, die: Image.Image) -> Image.Image:
    """One face of a tile as an RGBA image `2 * TILE_PX` across, the outside
    transparent: `sides` is `DODECAGON` or `HEXAGON`, `side` offense or
    defense, `tier` basic or advanced, `die` the d12 in the middle."""
    check_rule()
    offense = side == "offense"
    ms = face_order(side, tier)
    back = face_order("defense" if offense else "offense", tier)
    mm = TILE_PX / TILE_RADIUS_MM
    c = TILE_PX
    V = lambda a: (c + TILE_PX * math.cos(math.radians(a)), c + TILE_PX * math.sin(math.radians(a)))
    step = 360 / sides
    verts = [V(90 + step * j) for j in range(sides)]
    img = Image.new("RGBA", (2 * TILE_PX, 2 * TILE_PX), (0, 0, 0, 0))
    ImageDraw.Draw(img).polygon(verts, fill=WHITE)
    # region 0: the centre and the vertices from 30 to 150 degrees, its corner at 90
    poly = [(c, c)] + [V(a) for a in range(30, 151, int(step))]
    r_a0 = (D12_MM / 2 + 0.6) * mm
    r_a1 = r_a0 + ARROW_RING_MM * mm
    rule_size = 2 * math.pi * (r_a1 + 1.6 * mm) * 0.97 / (text_length(RULE, load_font(100, bold=True)) / 100)
    rule_font = load_font(int(rule_size), bold=True)
    r_rule = r_a1 + 0.6 * mm + rule_font.size * 0.72
    r_regions = r_rule + 0.9 * mm
    t_max = TILE_PX - r_regions - 0.6 * mm
    for i, m in enumerate(ms):
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        d = Region(c, TILE_PX, poly, MARGIN_MM * mm, BAND_MM * mm * 0.3)
        region(layer, m, offense, d, t_max, mm, sides == DODECAGON)
        arrow(layer, m, offense, back, i, r_a0, r_a1, mm)
        img.alpha_composite(layer.rotate(-120 * i, center=(c, c), resample=Image.BICUBIC))
    dr = ImageDraw.Draw(img)
    for a in (150, 270, 30):
        p0 = (c + r_regions * math.cos(math.radians(a)), c + r_regions * math.sin(math.radians(a)))
        dr.line([p0, V(a)], fill=BOUNDARY, width=int(mm * 0.5))
    # the rule starts just inside the bottom sector, so rank 1's corner reads its beginning
    spacing = (2 * math.pi * r_rule - text_length(RULE, rule_font)) / len(RULE)
    arc_text(img, RULE, rule_font, r_rule, 147, INK, spacing)
    die = die.resize((round(D12_MM * mm),) * 2, Image.LANCZOS)
    img.alpha_composite(die, (round(c - die.width / 2), round(c - die.height / 2)))
    clip = Image.new("L", img.size, 0)
    ImageDraw.Draw(clip).polygon(verts, fill=255)
    img.putalpha(Image.composite(img.getchannel("A"), clip, clip))
    ImageDraw.Draw(img).line(verts + [verts[0]], fill=color_of(ms[0], offense), width=int(mm * 1.0))
    return img


TEAM_DICE = {"orange": dice.ORANGE, "teal": dice.TEAL, "purple": dice.PURPLE, "slime": dice.SLIME}
TIERS = (("basic", "basic", 1, "basic maneuvers"), ("advanced", "gambits", 2, "gambits"))


def team_dice(team: Team) -> tuple[Image.Image, Image.Image]:
    """The colour team's Fortune and Doom, each cropped to itself."""
    pair = TEAM_DICE[team.value]
    return dice.die_mark(pair.fortune, 400), dice.die_mark(pair.doom, 400)


def tile_page(face: Image.Image, title: str, note: str) -> Image.Image:
    """A face at its printed size in the middle of a letter page, a title
    over it and a note under it. Centred both ways, so a page and the one
    printed on its back (duplex, flipped on the long edge) put the two
    faces back to back."""
    width, height = (round(v * PRINT_DPI) for v in PAPERS[TILE_PAPER])
    page = Image.new("RGB", (width, height), WHITE)
    across = round(2 * TILE_RADIUS_MM / 25.4 * PRINT_DPI)
    tile = face.resize((across, across), Image.LANCZOS)
    page.paste(tile, ((width - across) // 2, (height - across) // 2), tile)
    dr = ImageDraw.Draw(page)
    dr.text((width / 2, (height - across) / 4), title, font=load_font(46, bold=True), fill=INK, anchor="mm")
    dr.text((width / 2, height - (height - across) / 4), note, font=load_font(30), fill=MUTED, anchor="mm")
    return page


def render_tile_pages(sides: int, team: Team) -> dict[str, Image.Image]:
    """A colour team's two tiles of one shape as four letter pages, keyed
    by file name: each tile's offense as its front sheet and its defense
    as its back sheet."""
    fortune, doom = team_dice(team)
    shape = SHAPE_NAMES[sides]
    pages = {}
    for tier, word, number, what in TIERS:
        die = fortune if tier == "basic" else doom
        for side, which in (("offense", "front"), ("defense", "back")):
            face = tile_face(sides, side, tier, die)
            title = f"D12 Ball · {team_display_name(team)} maneuver tile {number}, {what} · {side}"
            if sides != DODECAGON:
                title += f" ({shape})"
            note = (
                f"The front of tile {number}: print it with its back sheet duplex (flip on the long edge) "
                "at actual size, then cut along the tile's edge."
                if which == "front" else
                f"The back of tile {number}: print it on the back of its front sheet (duplex, flip on the "
                "long edge) at actual size."
            )
            pages[f"{team.value}-{word}-{which}-sheet.png"] = tile_page(face, title, note)
    return pages

