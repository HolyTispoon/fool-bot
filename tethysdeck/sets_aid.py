"""The six-card sets drawn two ways, from `sets.census`: the player aid
-- every set, rarest first, a mixed hand of the deck's own cards beside
it and its chance, mixed and uniform -- and the chart, the same chances
as dots on a log scale, for seeing how far apart they are.

Both are drawn at twice their layout size, in the bundled Roboto Slab, on
white (the author: no cream anywhere). A chance is a percentage with two
significant figures below 1% and one decimal above it.
"""
import math

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from tethysdeck.icons import PROJECT_ROOT
from tethysdeck.sets import SETS, Count, total_hands

SCALE = 2
FONTS = {"regular": "RobotoSlab-Regular.ttf", "bold": "RobotoSlab-Bold.ttf"}

INK, INK2, MUTED = "#1D1B18", "#5D5850", "#8FA3A5"
RULE, BAND, PAPER = "#DFE3E3", "#F2F4F4", "#FFFFFF"
UNIFORM_INK = "#8A6A1A"
# The chart's two series, the dataviz skill's first two categorical
# slots, checked for colour-blind separation on white.
MIXED_DOT, UNIFORM_DOT, CONNECTOR, GRID = "#2A78D6", "#EB6834", "#B8B7B0", "#E4E3DE"

_fonts: dict = {}


def _font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    key = (weight, size)
    if key not in _fonts:
        path = PROJECT_ROOT / "d12ball" / "fonts" / FONTS[weight]
        _fonts[key] = ImageFont.truetype(str(path), round(size * SCALE))
    return _fonts[key]


def percent(hands: int) -> str:
    p = 100 * hands / total_hands()
    if p >= 1:
        return f"{p:.1f}%"
    return f"{p:.{1 - math.floor(math.log10(p))}f}%"


class _Canvas:
    """Layout coordinates in, pixels out."""

    def __init__(self, width: int, height: int):
        self.img = Image.new("RGBA", (width * SCALE, height * SCALE), PAPER)
        self.d = ImageDraw.Draw(self.img)

    @staticmethod
    def px(*values):
        return [round(v * SCALE) for v in values]

    def text(self, x, y, s, size, weight="regular", fill=INK, anchor="la"):
        self.d.text(self.px(x, y), s, font=_font(weight, size), fill=fill, anchor=anchor)

    def width(self, s, size, weight="regular") -> float:
        return self.d.textlength(s, font=_font(weight, size)) / SCALE

    def rect(self, box, fill):
        self.d.rectangle(self.px(*box), fill=fill)

    def line(self, box, fill, width):
        self.d.line(self.px(*box), fill=fill, width=round(width * SCALE))

    def card(self, image: Image.Image, x, y, w, h):
        """A card with a soft shadow, since the paper is the page's white."""
        size = self.px(w, h)
        small = image.resize(size, Image.LANCZOS)
        shadow = Image.new("RGBA", (size[0] + 16, size[1] + 16), (0, 0, 0, 0))
        alpha = small.getchannel("A").point(lambda a: a * 70 // 255)
        shadow.paste((0, 0, 0, 255), (8, 10), alpha)
        shadow = shadow.filter(ImageFilter.GaussianBlur(4))
        left, top = self.px(x, y)
        self.img.alpha_composite(shadow, (left - 8, top - 8))
        self.img.alpha_composite(small, (left, top))

    def done(self, height) -> Image.Image:
        return self.img.crop((0, 0, self.img.width, round(height * SCALE))).convert("RGB")


# --- the player aid ---------------------------------------------------------

AID_WIDTH, MARGIN = 1240, 40
CARD_W, CARD_H, CARD_GAP = 86, 120, 11
ROW_H = CARD_H + 26
# The key's two cards: which ink is which fate.
KEY = ((("money", "1"), "Fortune card: teal"), (("money", "2"), "Doom card: black and gold"))
COLUMNS = {"num": 52, "name": 100, "hand": 366, "mixed": 1050, "uniform": 1198}


def faces_shown() -> set[tuple[str, str]]:
    """The (suit, rank) of every card the player aid draws."""
    return {key for key, _ in KEY} | {key for s in SETS for key in s.example}


def player_aid(census: dict[str, Count], cards: dict) -> Image.Image:
    """Every set, rarest first, with a mixed example from `cards`, the
    deck's own faces keyed by (suit, rank)."""
    c = _Canvas(AID_WIDTH, 260 + ROW_H * len(SETS) + 120)
    c.text(MARGIN, 36, "Tethys Poker", 34, "bold")
    c.text(MARGIN, 88, "Your best set counts. Sets are listed from rarest to most common, and no set last.", 16, fill=INK2)

    y, x = 120, MARGIN
    for key, label in KEY:
        c.card(cards[key], x, y, 57, 80)
        c.text(x + 70, y + 40, label, 14, fill=INK2, anchor="lm")
        x += 70 + c.width(label, 14) + 34
    c.text(x, y + 40, "A hand is ", 14, fill=INK2, anchor="lm")
    x += c.width("A hand is ", 14)
    c.text(x, y + 40, "uniform", 14, "bold", anchor="lm")
    x += c.width("uniform ", 14, "bold")
    c.text(x, y + 40, "when all six cards are Fortune, or all six are Doom.", 14, fill=INK2, anchor="lm")

    y = 222
    c.text(COLUMNS["name"], y + 18, "Set", 13, fill=INK2)
    c.text(COLUMNS["hand"], y + 18, "Example", 13, fill=INK2)
    for column, word in (("mixed", "mixed"), ("uniform", "uniform")):
        c.text(COLUMNS[column], y, "Chance,", 13, fill=INK2, anchor="ra")
        c.text(COLUMNS[column], y + 17, word, 13, fill=INK2, anchor="ra")
    y += 42
    c.line((MARGIN, y, AID_WIDTH - MARGIN, y), INK, 2)

    for i, s in enumerate(SETS):
        top = y + 1 + i * ROW_H
        mid = top + ROW_H / 2
        if i % 2:
            c.rect((MARGIN, top, AID_WIDTH - MARGIN, top + ROW_H), BAND)
        c.line((MARGIN, top + ROW_H, AID_WIDTH - MARGIN, top + ROW_H), RULE, 1)
        last = s.key == "no_set"
        c.text(COLUMNS["num"], mid, str(i + 1), 22, "bold", fill=MUTED, anchor="lm")
        c.text(COLUMNS["name"], mid - 11, s.name, 19, "bold", fill=INK2 if last else INK, anchor="ls")
        c.text(COLUMNS["name"], mid + 15, s.rule, 13, fill=INK2, anchor="ls")
        for j, key in enumerate(s.example):
            c.card(cards[key], COLUMNS["hand"] + j * (CARD_W + CARD_GAP), top + 13, CARD_W, CARD_H)
        count = census[s.key]
        c.text(COLUMNS["mixed"], mid, percent(count.mixed), 18, fill=INK2 if last else INK, anchor="rm")
        if count.uniform:
            c.text(COLUMNS["uniform"], mid, percent(count.uniform), 18, fill=UNIFORM_INK, anchor="rm")
    y += 1 + ROW_H * len(SETS)
    c.line((MARGIN, y, AID_WIDTH - MARGIN, y), INK, 2)

    y += 22
    c.text(MARGIN, y, "Left and Right", 13, "bold", fill=INK2)
    c.text(MARGIN + c.width("Left and Right ", 13, "bold"), y,
           "pair only with each other: a Left and a Right are a pair, two Lefts are not. Either "
           "follows 10 in a straight (6-7-8-9-10-Left). Straights don't wrap.", 13, fill=INK2)
    c.text(MARGIN, y + 20, "Three of a kind with a pair counts as three of a kind, and four of a kind "
           "with a pair as four of a kind.", 13, fill=INK2)
    c.text(MARGIN, y + 40, "Uniform chances are for all Fortune or all Doom together; each alone is half.",
           13, fill=INK2)
    return c.done(y + 76)


# --- the chart --------------------------------------------------------------

CHART_WIDTH, PLOT_LEFT, PLOT_RIGHT, PLOT_TOP, CHART_ROW = 980, 250, 920, 118, 50


def odds_chart(census: dict[str, Count]) -> Image.Image:
    """Mixed and uniform chances per set, rarest first, on a log scale."""
    values = [100 * n / total_hands() for s in SETS for n in (census[s.key].mixed, census[s.key].uniform) if n]
    low, high = math.floor(math.log10(min(values))), math.ceil(math.log10(max(values)))

    def x_of(p: float) -> float:
        return PLOT_LEFT + (math.log10(p) - low) / (high - low) * (PLOT_RIGHT - PLOT_LEFT)

    bottom = PLOT_TOP + CHART_ROW * len(SETS)
    c = _Canvas(CHART_WIDTH, bottom + 110)
    c.text(24, 22, "Tethys Poker: the odds", 24, "bold")
    c.text(24, 52, "Chance of each set when all six cards count, rarest first and no set last. Log scale.", 14, fill=INK2)

    _diamond(c, PLOT_LEFT, 92, 6, MIXED_DOT, circle=True)
    c.text(PLOT_LEFT + 12, 92, "Mixed Fortune and Doom", 14, anchor="lm")
    _diamond(c, PLOT_LEFT + 224, 92, 6, UNIFORM_DOT)
    c.text(PLOT_LEFT + 236, 92, "Uniform: all six Fortune, or all six Doom", 14, anchor="lm")

    for i in range(len(SETS)):
        if i % 2 == 0:
            top = PLOT_TOP + CHART_ROW * i
            c.rect((16, top, CHART_WIDTH - 16, top + CHART_ROW), BAND)
    for e in range(low, high + 1):
        x = x_of(10 ** e)
        c.line((x, PLOT_TOP - 8, x, bottom), GRID, 1)
        label = f"{10 ** e:.0f}%" if e >= 0 else f"{10 ** e:.{-e}f}%"
        c.text(x, bottom + 14, label, 12, fill=INK2, anchor="ma")

    for i, s in enumerate(SETS):
        y = PLOT_TOP + CHART_ROW * i + CHART_ROW / 2
        c.text(24, y, str(i + 1), 13, fill=INK2, anchor="lm")
        c.text(48, y, s.name, 15, anchor="lm")
        count = census[s.key]
        xm = x_of(100 * count.mixed / total_hands())
        if count.uniform:
            xu = x_of(100 * count.uniform / total_hands())
            c.line((xu, y, xm, y), CONNECTOR, 2)
            _diamond(c, xu, y, 7, UNIFORM_DOT, ring=True)
            c.text(xu, y - 13, percent(count.uniform), 12, anchor="ms")
        _diamond(c, xm, y, 7, MIXED_DOT, circle=True, ring=True)
        c.text(xm, y - 13, percent(count.mixed), 12, anchor="ms")

    c.text(24, bottom + 50, f"All {total_hands():,} hands of six from the 72-card deck, counted exactly. "
           "A Left pairs only with a Right. Each hand counts once, under its best set.", 12, fill=INK2)
    c.text(24, bottom + 68, "Uniform is either all Fortune or all Doom; each one alone is half the figure shown.",
           12, fill=INK2)
    return c.done(bottom + 96)


def _diamond(c: _Canvas, x, y, r, fill, circle=False, ring=False):
    """A dot for mixed, a diamond for uniform, ringed in the paper's white
    where it sits on the connector."""
    outline = PAPER if ring else None
    width = round(2 * SCALE) if ring else 0
    if circle:
        c.d.ellipse(c.px(x - r, y - r, x + r, y + r), fill=fill, outline=outline, width=width)
    else:
        r *= 1.15
        c.d.polygon(c.px(x, y - r, x + r, y, x, y + r, x - r, y), fill=fill, outline=outline, width=width)
