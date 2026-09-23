"""
The printed things around the game rather than in it: the **box
cover**, the box's **side panel**, the **underside of the box**, the
one-page **sale sheet**, and the **playtest card** whose back carries
the survey QR.

None of these is a component. Nobody plays off them -- but they are
printed the same way `boards.py` and `cards.py` are printed, **dark
ink on white**, and for a reason that outranks how a box looks on a
shelf: a full-bleed dark cover is the most expensive thing a print run
can be asked for, on every panel of the wrap at once. The ground is
white rather than the cards' and boards' cream, because a page is a
page. What carries the game's look is the art, the four team colours
and the type.

**Every claim on them is read from the game.** The counts come from
the catalogs (`players.json`, `maneuvers.json`, `basic_rules.json`),
the component list is the Learn to Play's own "What is in the box",
and every sentence quoted as a rule is quoted verbatim from
`docs/living-rules.md` or `docs/learn-to-play.md` --
`tests/test_d12ball_box_art.py` checks each one is still in one of
them word for word. A box that claims a rule the game does not play is
the failure this is built to make impossible, and it is the same rule
the printed boards are held to.

**What is deliberately not on the box**: a playing time and an age
rating. Both are retail claims and nothing in this repository measures
either -- the "thirty minutes" the game is played over is fifteen
space minutes a half on the game clock, which is not a wall clock and
must not be printed as one. `RetailClaims` is where they go once
somebody has sat at a table with a stopwatch; until then the chips are
left off rather than guessed at.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from math import atan2, cos, hypot, sin, sqrt
from typing import Optional, Sequence

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from d12ball.boards import (
    BLEED_INCHES,
    DEFAULT_PAPER,
    PAPERS,
    PRINT_DPI,
    ZONE_TINTS,
    FieldGeometry,
    Sheet,
    draw_fitted,
    print_font,
    render_field_board,
)
from d12ball.cards import (
    CARD_HEIGHT,
    CARD_WIDTH,
    INK,
    MUTED,
    render_maneuver_card,
)
from d12ball.player_cards import render_player_card
from d12ball.components import (
    MANEUVER_TIER_BASIC,
    BasicRuleset,
    PlayerDefinition,
    ManeuverCatalog,
    MatchState,
    PlayerCatalog,
    TeamSide,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
    load_species_abilities,
)
from d12ball.game import COLOR_TEAMS, Formation, Team
from d12ball.render import (
    ROLE_INITIALS,
    TEAM_COLORS,
    ZONE_COLORS,
    high_contrast_ink,
    load_font,
    load_goal_zone_font,
    load_player_portrait,
    species_icon,
    wrap_text,
)
from d12ball.rules_doc import (
    LOCAL_LINK_PATTERN,
    PROJECT_ROOT,
    load_rules_document,
    parse_rules_document,
)


LEARN_TO_PLAY_PATH = PROJECT_ROOT / "docs" / "learn-to-play.md"

# The label the game is published under -- the one thing on any of
# these panels that is not a fact about the rules, and the only place
# it is written.
PUBLISHER = "Prophetic Fools Games"
TITLE = "D12 Ball"

# The survey the playtest card sends a table to. A constant rather
# than a literal in the drawing code because it is the one thing on
# the card that will be replaced without the card being redesigned,
# and `scripts/render_box_art.py --survey-url` overrides it.
# The game's own page, which is what a sale sheet sends somebody to.
# A second address rather than the survey's: one asks how a game went,
# the other says what the game is.
PAGE_URL = (
    "https://propheticfools.notion.site/"
    "D12-Ball-6c9e1ea7ca61825391e881ec5fbfdca5?pvs=74"
)
SURVEY_URL = (
    "https://app.notion.com/p/3a5e1ea7ca618006b187cd98ebf0c9ff"
    "?v=3a5e1ea7ca6180478080000c31b041d0&source=copy_link"
)


# ------------------------------------------------------------- palette

# **Everything here is printed on white, and nothing is printed dark.**
# A cover in the bot's night palette is a full-bleed solid across every
# panel of the wrap, which is the most expensive thing a print run can
# be asked for and the first thing a quote comes back high on -- the
# author's call, and the same reasoning `printed-boards.md` already
# gives for a board being dark ink on a light face. What carries the
# game's look instead is the art, the team colours and the type.
#
# The ground is **white**, not the cards' and boards' cream: a page is
# a page. `FACE_COLOR` is still what a component is printed on, and is
# deliberately not used here.
PAPER = "#ffffff"
# A panel on the page -- the glance table, the answer box. Neutral
# rather than the cards' warm `PANEL_COLOR`, for the same reason the
# ground is white.
PANEL = "#f1f3f5"
PANEL_EDGE_INK = "#c9d1d9"
# The ink and the grey are the cards' own, so a panel and a card read
# as one family.
PAPER_INK = INK
PAPER_MUTED = MUTED
# The accent, for rules, bullets and the publisher's line. The
# jumbotron's gold (#f0b429) is drawn on a dark board and disappears
# into white paper at text sizes; this is the same hue taken down far
# enough to be read on it.
ACCENT = "#b0770e"


@dataclass(frozen=True)
class CoverPalette:
    """
    The cover is the one panel drawn twice.

    The box itself is printed, so it is the page's: white ground, dark
    ink. The other is for a screen -- a post, a store page, a header
    -- where ink costs nothing and the bot's own night board is what
    the game looks like. Everything below is what differs between
    them; the layout does not, so a change to one is a change to both.
    """

    ground: str
    ink: str
    muted: str
    accent: str
    edge: str
    # What the field strip's three zones are filled with: the boards'
    # print tints on paper, the bot's own zone colours on the screen.
    zones: dict
    # What the back rank is washed towards, and whether the panel
    # carries light at all -- a glow is a screen's, not a printer's.
    haze: tuple
    # How far back the back rank goes. White haze eats a figure much
    # faster than dark does, so the same share that reads as distance
    # on the night cover reads as half a player on the page.
    haze_share: float
    glows: bool
    shadow: str


PAGE_COVER = CoverPalette(
    ground=PAPER,
    ink=PAPER_INK,
    muted=PAPER_MUTED,
    accent=ACCENT,
    edge=PANEL_EDGE_INK,
    zones=ZONE_TINTS,
    haze=(255, 255, 255),
    haze_share=0.55,
    glows=False,
    shadow="#7c8894",
)
NIGHT_COVER = CoverPalette(
    ground="#080e15",
    ink="#ffffff",
    muted="#9aa5b1",
    # The jumbotron's own gold, which is what it is drawn on a dark
    # board for.
    accent="#f0b429",
    edge="#2b3a49",
    zones=ZONE_COLORS,
    haze=(5, 9, 14),
    haze_share=1.0,
    glows=True,
    shadow="#02060a",
)


# ----------------------------------------------------------- the box

# What a board has to drop into. The field board is the biggest thing
# in the box: tabloid, folded once across its long side, so it lands
# at the paper's own short side by half its long one -- 11 x 8.5in.
# The box is square because that is what the wider of those two
# measurements makes it anyway, and a square box is the format a
# manufacturer's stock sizes cluster around.
BOX_CLEARANCE_INCHES = 0.375
# Deep enough for the folded boards, both decks and the dice, and
# deep enough to be seen on a shelf edge-on. The author's call; there
# is nothing in the rules to read it off.
BOX_DEPTH_INCHES = 2.75


def folded_board_inches(paper: str = DEFAULT_PAPER) -> tuple[float, float]:
    """The field board folded once, which is the thing the box is cut for."""
    short, long = PAPERS[paper]
    return short, long / 2


def box_inches(paper: str = DEFAULT_PAPER) -> tuple[float, float, float]:
    """The box: a square footprint, and its depth, in inches."""
    side = max(folded_board_inches(paper)) + BOX_CLEARANCE_INCHES
    return side, side, BOX_DEPTH_INCHES


@dataclass(frozen=True)
class RetailClaims:
    """
    The two things a box carries that the game cannot be asked for.

    A playing time and an age rating are measured at a table, not read
    out of `basic_rules.json`, so neither is something this code can
    answer: `RetailClaims()` carries nothing and a chip with nothing
    behind it is left off rather than invented -- the same call
    `fitted_print_font` makes about a caption it cannot draw legibly.

    **`DEFAULT_CLAIMS` is what the author gave on 2026-09-23**: two
    players, 30-45 minutes, ages 10+. They are printed because
    somebody who has run the table said so, not because anything here
    worked them out, which is why they live in one constant with a
    date on it rather than being written into the panels.
    """

    play_minutes: Optional[tuple[int, int]] = None
    minimum_age: Optional[int] = None

    @property
    def chips(self) -> tuple[str, ...]:
        chips: list[str] = []
        if self.play_minutes is not None:
            low, high = self.play_minutes
            chips.append(
                f"{low}-{high} MINUTES" if low != high else f"{low} MINUTES"
            )
        if self.minimum_age is not None:
            chips.append(f"AGES {self.minimum_age}+")
        return tuple(chips)


NO_CLAIMS = RetailClaims()
DEFAULT_CLAIMS = RetailClaims(play_minutes=(30, 45), minimum_age=10)


# ---------------------------------------------------- what the game is

@dataclass(frozen=True)
class BoxFacts:
    """
    Every number printed on any of these panels, read off the game.

    Nothing here is written down twice: a roster import that adds a
    tenth player to a team changes the box by re-running
    `scripts/render_box_art.py`, exactly as it changes the printed
    boards by re-running `scripts/render_boards.py`.
    """

    coaches: int
    players_per_team: int
    fielded: int
    teams: int
    species: int
    maneuvers: int
    basic_maneuvers: int
    gambits: int
    board_sizes: tuple[int, ...]
    formations: int

    @classmethod
    def read(
        cls,
        catalog: Optional[PlayerCatalog] = None,
        maneuvers: Optional[ManeuverCatalog] = None,
        rules: Optional[BasicRuleset] = None,
    ) -> "BoxFacts":
        catalog = catalog or load_player_catalog()
        maneuvers = maneuvers or load_maneuver_catalog()
        rules = rules or load_basic_ruleset()
        every = tuple(maneuvers.offense) + tuple(maneuvers.defense)
        basic = [one for one in every if one.tier == MANEUVER_TIER_BASIC]
        return cls(
            # Two, because a match has two sides -- asked of the model
            # rather than typed, since "how many coaches" is the same
            # question as "how many sides" and only one of them has an
            # answer in the code.
            coaches=len(TeamSide),
            players_per_team=len(next(iter(catalog.teams.values())).players),
            fielded=sum(len(roles) for roles in rules.standard_setup.values()),
            teams=len(catalog.teams),
            species=len(load_species_abilities()),
            maneuvers=len(every),
            basic_maneuvers=len(basic),
            gambits=len(every) - len(basic),
            board_sizes=tuple(sorted(rules.board_layouts)),
            formations=len(rules.formations),
        )

    @property
    def board_sizes_phrase(self) -> str:
        return " and ".join(str(size) for size in self.board_sizes)


# ------------------------------------------------- what the books say

# A box may not word a rule for itself. Every line below is quoted
# from one of the two books, and `BoxArtQuotesTests` fails if the
# words drift out of them -- which is the same guarantee the printed
# boards get from reading their layouts out of `basic_rules.json`,
# applied to sentences instead of numbers.
HOOK = (
    "Two coaches. Nine players each, six on the field. Thirty minutes "
    "on a clock that never stops. You win on goals -- and a level game "
    "goes to the shootout, so somebody always wins."
)
# The line under the title, and the one piece of copy on any of these
# panels that is not quoted from the books: it is the author's own
# (2026-09-23), and it states no rule -- it says how the game plays,
# which is the one thing a box is allowed to say in its own voice.
# `BoxArtQuotesTests` covers the quoted lines and not this one.
STRAPLINE = (
    "A fast playing fantasy sports game of some strategy, a lot of "
    "tactics, a little luck and a bucket of d12s"
)
CHARTER_LINE = "The Charter settles every question."

# The three beats of a turn, each a sentence of the Learn to Play's
# own and the Law it is taught under.
TURN_BEATS: tuple[tuple[str, str], ...] = (
    (
        "A maneuver is a fight for the ball between two players",
        "Law 6.1",
    ),
    ("Rank decides, not dice.", "Law 6.3"),
    ("A tie is not a draw.", "Law 6.4"),
)

def plain(markdown: str) -> str:
    """
    A line of either book as a box prints it: no emphasis marks, and a
    link to somewhere else in the document reduced to its own words.

    The link substitution is `rules_doc`'s, which is named for Discord
    because that is where it was first needed; a printed panel cannot
    render `[a](#b)` either.
    """
    text = LOCAL_LINK_PATTERN.sub(r"\1", markdown)
    return text.replace("**", "").replace("*", "").strip()


def learn_to_play_section(slug: str) -> str:
    book = parse_rules_document(LEARN_TO_PLAY_PATH.read_text())
    section = book.find(slug)
    if section is None:
        raise ValueError(f"No section {slug!r} in {LEARN_TO_PLAY_PATH.name}.")
    return section.text


def living_rules_section(slug: str) -> str:
    section = load_rules_document().find(slug)
    if section is None:
        raise ValueError(f"No section {slug!r} in the living rules.")
    return section.text


def body_paragraphs(section_text: str) -> tuple[str, ...]:
    """A section's paragraphs, heading and notes dropped."""
    blocks = [block.strip() for block in section_text.split("\n\n")]
    return tuple(
        plain(block)
        for block in blocks
        if block and not block.startswith(("#", ">", "-", "|", "!"))
    )


def box_contents() -> tuple[str, ...]:
    """
    What is in the box, from the Learn to Play's own list of it.

    Its sentences addressed to the reader of that book -- "This book
    plays the 7-space board" -- are dropped, because a box is not the
    book and the sentence is false the moment it is read off one. What
    is left is the component and nothing else.
    """
    lines: list[str] = []
    for line in learn_to_play_section("what-is-in-the-box").splitlines():
        if not line.startswith("- "):
            continue
        sentences = [
            sentence.strip()
            for sentence in plain(line[2:]).split(". ")
            if "this book" not in sentence.lower()
        ]
        entry = ". ".join(sentences).strip()
        if entry and not entry.endswith((".", "!")):
            entry += "."
        if entry:
            lines.append(entry)
    return tuple(lines)


# -------------------------------------------------------- the drawing

def inches(value: float) -> float:
    return value * PRINT_DPI


@dataclass(frozen=True)
class Panel:
    """
    One printed face, measured in inches from its own **trim** edge.

    Everything here is a physical object read at arm's length, so the
    unit is the inch throughout, as it is on the team board and for
    the same reason -- `Sheet.u`'s thousandths of a sheet are the
    right unit for a layout that scales whole between paper sizes, and
    the wrong one for a panel whose size is fixed by a box.

    With `bleed` the canvas grows by an eighth of an inch on every
    side and the origin moves into it, so the art is drawn past the
    trim rather than a border being added around a finished panel: a
    flat margin around a gradient is a visible seam where a printer's
    knife lands.
    """

    width: float
    height: float
    bleed: bool = False

    @property
    def margin(self) -> float:
        return BLEED_INCHES if self.bleed else 0.0

    @property
    def margin_pixels(self) -> int:
        return round(inches(self.margin))

    @property
    def pixels(self) -> tuple[int, int]:
        """
        The canvas: the trim, plus the bleed twice.

        Rounded that way round rather than as one measurement, so the
        trimmed panel is the same number of pixels whether a bleed was
        asked for or not -- a printer's knife lands on the trim, and a
        half-pixel of rounding that moves it is a half-pixel that
        moves every measurement inside it.
        """
        return (
            round(inches(self.width)) + self.margin_pixels * 2,
            round(inches(self.height)) + self.margin_pixels * 2,
        )

    def sheet(self, background: str) -> Sheet:
        width, height = self.pixels
        return Sheet(width, height, background=background)

    def x(self, value: float) -> float:
        return self.margin_pixels + inches(value)

    def y(self, value: float) -> float:
        return self.margin_pixels + inches(value)


def vertical_gradient(
    size: tuple[int, int], top: str, bottom: str
) -> Image.Image:
    """
    A two-stop vertical wash.

    Built one pixel tall per stop on a narrow strip and stretched, not
    drawn line by line at print resolution: a panel is eleven inches
    of 300dpi and the strip is a few hundred pixels, which is the same
    picture for a thousandth of the work.
    """
    steps = 256
    strip = Image.new("RGB", (1, steps))
    start = Image.new("RGB", (1, 1), top).getpixel((0, 0))
    end = Image.new("RGB", (1, 1), bottom).getpixel((0, 0))
    for index in range(steps):
        share = index / (steps - 1)
        strip.putpixel(
            (0, index),
            tuple(
                round(start[channel] + (end[channel] - start[channel]) * share)
                for channel in range(3)
            ),
        )
    return strip.resize(size, Image.Resampling.BICUBIC)


def radial_glow(diameter: int, color: str, strength: int = 210) -> Image.Image:
    """
    A soft disc of light, for what the ball and the title sit in.

    Drawn small and scaled up for the same reason as the gradient, and
    because a hundred stepped ellipses at print resolution band
    visibly where the same hundred at 256px do not survive the
    resize.
    """
    small = 256
    layer = Image.new("RGBA", (small, small), (0, 0, 0, 0))
    pen = ImageDraw.Draw(layer)
    rgb = Image.new("RGB", (1, 1), color).getpixel((0, 0))
    steps = 64
    for index in range(steps):
        share = index / steps
        radius = (small / 2) * (1 - share)
        alpha = round(strength * (share ** 2))
        pen.ellipse(
            (
                small / 2 - radius,
                small / 2 - radius,
                small / 2 + radius,
                small / 2 + radius,
            ),
            fill=(*rgb, alpha),
        )
    return layer.resize(
        (max(1, diameter), max(1, diameter)), Image.Resampling.BICUBIC
    )


def paste_rgba(sheet: Sheet, art: Image.Image, position: tuple[float, float]) -> None:
    sheet.image.paste(
        art, (round(position[0]), round(position[1])), art
    )


def paste_glow(
    sheet: Sheet, center: tuple[float, float], diameter: float, color: str,
    strength: int = 210,
) -> None:
    art = radial_glow(round(diameter), color, strength)
    paste_rgba(sheet, art, (center[0] - art.width / 2, center[1] - art.height / 2))


def standing_art(art: Image.Image, height: float) -> Image.Image:
    scale = height / art.height
    return art.resize(
        (max(1, round(art.width * scale)), max(1, round(height))),
        Image.Resampling.LANCZOS,
    )


def hazed(
    art: Image.Image, share: float, toward: tuple[int, int, int]
) -> Image.Image:
    """
    A cut-out pushed back towards the paper, keeping its own alpha.

    The back rank of the cover is washed towards the ground it stands
    on rather than faded: a cut-out at reduced opacity is the panel
    showing through the middle of a player, where the same one washed
    towards white (or, on the night cover, towards the dark) reads as
    somebody standing further away in the same air.
    """
    haze = Image.new("RGBA", art.size, (*toward, 0))
    haze.putalpha(art.getchannel("A").point(lambda value: round(value * share)))
    layered = art.convert("RGBA").copy()
    layered.alpha_composite(haze)
    return layered


def clamp_center(
    center: float, width: float, panel: "Panel", side: float, edge: float
) -> float:
    """A centre moved just enough to keep `width` of art inside the trim."""
    left_limit = panel.x(edge) + width / 2
    right_limit = panel.x(side - edge) - width / 2
    if left_limit > right_limit:
        return panel.x(side / 2)
    return min(max(center, left_limit), right_limit)


def paste_standing(
    sheet: Sheet,
    art: Image.Image,
    center_x: float,
    baseline: float,
    height: float,
) -> tuple[float, float]:
    """
    A cut-out standing on a line rather than centred in a box.

    `Sheet.paste` centres what it fits, which is right for a token in
    a silo and wrong for a player on a field: what has to line up is
    their feet. Returns the left and right edges, so a caller can keep
    the next one clear of this one.
    """
    fitted = standing_art(art, height)
    left = center_x - fitted.width / 2
    paste_rgba(sheet, fitted, (left, baseline - fitted.height))
    return left, left + fitted.width


# The twelve faces of a d12, as the solid actually is: a regular
# dodecahedron's twenty vertices, and its face normals (the dual
# icosahedron's vertices -- the (0, +-PHI, +-1) family, not the
# (0, +-1, +-PHI) one, which is the same solid turned and whose faces
# do not come out planar against these vertices).
PHI = (1 + sqrt(5)) / 2
D12_VERTICES: tuple[tuple[float, float, float], ...] = tuple(
    [(x, y, z) for x in (1, -1) for y in (1, -1) for z in (1, -1)]
    + [(0, y / PHI, z * PHI) for y in (1, -1) for z in (1, -1)]
    + [(y / PHI, z * PHI, 0) for y in (1, -1) for z in (1, -1)]
    + [(y * PHI, 0, z / PHI) for y in (1, -1) for z in (1, -1)]
)
D12_NORMALS: tuple[tuple[float, float, float], ...] = tuple(
    [(0, a * PHI, b) for a in (1, -1) for b in (1, -1)]
    + [(a, 0, b * PHI) for a in (1, -1) for b in (1, -1)]
    + [(a * PHI, b, 0) for a in (1, -1) for b in (1, -1)]
)
# How the die is turned: the numbered face square to the reader with
# five more around it, which is a die on a table rather than a flat
# twelve-sided badge. Less than it was -- turned further, the
# silhouette of a dodecahedron goes lopsided (correctly; it is the
# shape's own outline) and reads as a chipped rock.
D12_TILT = (-0.20, 0.15)
# How far a face is set into the solid, as a share of its own size:
# the gap is the rounded edge between two faces.
D12_FACE_INSET = 0.93
D12_SUPERSAMPLE = 4
_D12_CACHE: dict[tuple, Image.Image] = {}
_D12_GRAIN: dict[int, Image.Image] = {}


@dataclass(frozen=True)
class DieMaterial:
    """
    What the ball is made of.

    It was white, which is what a d12 is in a dice shop and nothing
    this game's art has ever contained: the balls in the players' own
    portraits are dark, dimpled, organic things. So the die is drawn
    as a piece of hard dark rubber -- a lit face, a shadowed one, a
    grain over both, worn seams where the faces meet, and bone
    numerals cut into it.
    """

    body: str
    # The bevel a face is set into. A cast piece has no sharp edges:
    # every face is inset and what shows between two of them is this,
    # which is what a rounded edge looks like from straight on.
    seam: str
    # The silhouette, which does go darker -- it is the edge of the
    # object, not a crease in it.
    edge: str
    numeral: str
    # How deep the grain is, 0 to 1.
    grain: float


# Leather rather than the grey of a dice-shop d12: this ball is the
# one a fire demon kicks. The author's pick from four the material was
# tried in (a stone grey, this, a tyre black and an ooze green).
BALL_MATERIAL = DieMaterial(
    body="#4a3f33",
    seam="#6d5f4c",
    edge="#1d1813",
    numeral="#efe6d2",
    grain=0.40,
)


def _dot(a, b) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _unit(v):
    length = sqrt(_dot(v, v))
    return (v[0] / length, v[1] / length, v[2] / length)


def d12_faces() -> list[tuple[tuple[float, float, float], list]]:
    """
    The solid, as twelve (normal, five vertices) pentagons.

    A face is the five vertices furthest along its own normal, wound
    around it so the polygon is convex -- worked out rather than
    written down, because a table of sixty indices is sixty chances to
    transpose two of them and no way to notice.
    """
    built = []
    for normal in D12_NORMALS:
        unit = _unit(normal)
        corners = sorted(D12_VERTICES, key=lambda v: -_dot(v, unit))[:5]
        helper = (0, 0, 1) if abs(unit[2]) < 0.9 else (1, 0, 0)
        across = _unit(_cross(unit, helper))
        up = _unit(_cross(unit, across))
        corners.sort(key=lambda v: atan2(_dot(v, up), _dot(v, across)))
        built.append((unit, corners))
    return built


def _turned(v, tilt: tuple[float, float]):
    x, y, z = v
    ax, ay = tilt
    y, z = y * cos(ax) - z * sin(ax), y * sin(ax) + z * cos(ax)
    x, z = x * cos(ay) + z * sin(ay), -x * sin(ay) + z * cos(ay)
    return (x, y, z)


def die_grain(size: int, depth: float) -> Image.Image:
    """
    The mottling of the die's own surface, as a grey to be overlaid.

    Hashed off each pixel's coordinates rather than drawn from
    `random`: a render of this panel is the same bytes every time,
    which is what lets a drawing change be checked by hash (see "Look
    at the image" in CLAUDE.md). Two scales of it, because one is
    noise and two is a material -- a coarse blotch under a fine
    speckle.
    """
    if size in _D12_GRAIN:
        return _D12_GRAIN[size]

    def value(x: int, y: int, salt: int) -> int:
        seed = (x * 73856093) ^ (y * 19349663) ^ (salt * 83492791)
        seed = (seed ^ (seed >> 13)) * 1274126177
        return (seed >> 16) & 0xFF

    coarse = Image.new("L", (max(4, size // 24), max(4, size // 24)))
    coarse.putdata(
        [
            value(x, y, 1)
            for y in range(coarse.height)
            for x in range(coarse.width)
        ]
    )
    fine = Image.new("L", (max(8, size // 6), max(8, size // 6)))
    fine.putdata(
        [value(x, y, 2) for y in range(fine.height) for x in range(fine.width)]
    )
    grain = Image.blend(
        coarse.resize((size, size), Image.Resampling.BICUBIC)
        .filter(ImageFilter.GaussianBlur(size / 90)),
        fine.resize((size, size), Image.Resampling.BILINEAR)
        .filter(ImageFilter.GaussianBlur(size / 400)),
        0.45,
    )
    # Pulled towards mid-grey, which is what `overlay` leaves alone:
    # `depth` is then how far the surface varies from its own colour.
    grain = Image.eval(grain, lambda v: round(128 + (v - 128) * depth))
    _D12_GRAIN[size] = grain
    return grain


def d12_art(
    size: int,
    face: str = "12",
    material: DieMaterial = BALL_MATERIAL,
) -> Image.Image:
    """
    A d12 -- the die itself, drawn as a solid and as a material.

    Six of the twelve faces are towards the reader at any angle; each
    is filled by how square it is to them, which is what makes it read
    as a die rather than as a wireframe, and the whole is then grained
    and seamed so it reads as something cast rather than something
    printed. Drawn four times over and scaled down, because Pillow
    does not antialias a polygon edge and a die is nothing but polygon
    edges.
    """
    key = (size, face, material)
    if key in _D12_CACHE:
        return _D12_CACHE[key]

    span = max(8, size) * D12_SUPERSAMPLE
    body = Image.new("RGB", (span, span), material.body)
    mask = Image.new("L", (span, span), 0)
    shading = ImageDraw.Draw(body)
    silhouette = ImageDraw.Draw(mask)

    turned = [
        (_turned(normal, D12_TILT), [_turned(v, D12_TILT) for v in corners])
        for normal, corners in d12_faces()
    ]
    extent = max(
        max(abs(v[0]), abs(v[1])) for _, corners in turned for v in corners
    )
    scale = span * 0.47 / extent

    def flat(v) -> tuple[float, float]:
        return (span / 2 + v[0] * scale, span / 2 - v[1] * scale)

    # A face barely off edge-on projects as a sliver, which reads as a
    # chip out of the solid rather than as a face. Dropped, it is
    # bevel like any other rounded edge.
    towards = [(n, corners) for n, corners in turned if n[2] > 0.12]
    tone = Image.new("RGB", (1, 1), material.body).getpixel((0, 0))

    # The solid's own outline is the hull of **every** vertex, not of
    # the faces turned towards the reader: a face seen edge-on still
    # holds part of the silhouette, so a hull of the visible ones
    # alone cuts a flat notch out of the shape. Filled in the bevel
    # colour first; every face is then inset into it, so what shows
    # between two faces is a rounded edge rather than a drawn line.
    outline = silhouette_outline(turned, flat)
    shading.polygon(outline, fill=material.seam)
    silhouette.polygon(outline, fill=255)
    for normal, corners in sorted(
        towards, key=lambda one: sum(v[2] for v in one[1])
    ):
        # A face square to the reader is lit; one turning away falls
        # off to a little over half. Rubber has no specular to speak
        # of, so the range is narrow and there is no white in it.
        shade = 0.55 + 0.75 * max(0.0, normal[2])
        points = [flat(v) for v in corners]
        middle = (
            sum(p[0] for p in points) / 5,
            sum(p[1] for p in points) / 5,
        )
        inset = [
            (
                middle[0] + (p[0] - middle[0]) * D12_FACE_INSET,
                middle[1] + (p[1] - middle[1]) * D12_FACE_INSET,
            )
            for p in points
        ]
        shading.polygon(
            inset, fill=tuple(min(255, round(c * shade)) for c in tone)
        )

    if material.grain:
        body = ImageChops.overlay(
            body, Image.merge("RGB", (die_grain(span, material.grain),) * 3)
        )
    seams = ImageDraw.Draw(body)

    # The number, cut in: a shadow a hair below it and the bone face
    # over that.
    front = max(towards, key=lambda one: one[0][2])
    points = [flat(v) for v in front[1]]
    middle = (
        sum(p[0] for p in points) / 5,
        sum(p[1] for p in points) / 5,
    )
    room = min(hypot(p[0] - middle[0], p[1] - middle[1]) for p in points)
    numerals = round(room * 1.4)
    while numerals > 6:
        numeral_font = load_font(numerals, bold=True)
        if seams.textlength(face, font=numeral_font) <= room * 1.5:
            break
        numerals -= 2
    seams.text(
        (middle[0], middle[1] + span * 0.006),
        face,
        font=numeral_font,
        fill=material.edge,
        anchor="mm",
    )
    seams.text(
        middle, face, font=numeral_font, fill=material.numeral, anchor="mm"
    )

    art = Image.new("RGBA", (span, span), (0, 0, 0, 0))
    art.paste(body, (0, 0), mask)
    # The silhouette last, so the object has an edge against whatever
    # it is standing on.
    ImageDraw.Draw(art).polygon(
        outline, outline=material.edge, width=max(1, round(span * 0.008))
    )

    _D12_CACHE[key] = art.resize(
        (max(8, size), max(8, size)), Image.Resampling.LANCZOS
    )
    return _D12_CACHE[key]


def silhouette_outline(faces, flat) -> list[tuple[float, float]]:
    """
    The die's own outline: the convex hull of every projected vertex,
    which for a convex solid is exactly its silhouette.

    Drawn as one polygon rather than as twelve outlined faces, so the
    edge of the object is one weight and what is inside it another.
    """
    points = [flat(v) for _, corners in faces for v in corners]
    points.sort()
    def half(order):
        built: list[tuple[float, float]] = []
        for point in order:
            while len(built) >= 2:
                (ax, ay), (bx, by) = built[-2], built[-1]
                if (bx - ax) * (point[1] - ay) - (by - ay) * (point[0] - ax) > 0:
                    break
                built.pop()
            built.append(point)
        return built
    return half(points)[:-1] + half(reversed(points))[:-1]


def draw_d12(
    sheet: Sheet,
    center: tuple[float, float],
    radius: float,
    face: str = "12",
    material: DieMaterial = BALL_MATERIAL,
) -> None:
    """The ball, which is a d12, centred on a point."""
    art = d12_art(round(radius * 2), face, material)
    paste_rgba(sheet, art, (center[0] - art.width / 2, center[1] - art.height / 2))


def draw_chip(
    sheet: Sheet,
    left: float,
    center_y: float,
    text: str,
    size_inches: float,
    ink: str,
    edge: str,
    fill: Optional[str] = None,
) -> float:
    """One of the small outlined facts along a cover's foot. Returns its right edge."""
    face = print_font(size_inches, bold=True)
    padding = inches(0.16)
    height = inches(size_inches * 2.1)
    width = sheet.text_width(text, face) + padding * 2
    sheet.rect(
        (left, center_y - height / 2, left + width, center_y + height / 2),
        radius=height / 2,
        fill=fill,
        outline=edge,
        width=max(2, round(inches(0.012))),
    )
    sheet.text((left + width / 2, center_y), text, face, ink, anchor="mm")
    return left + width


def draw_wrapped(
    sheet: Sheet,
    left: float,
    top: float,
    width: float,
    text: str,
    size_inches: float,
    fill: str,
    bold: bool = False,
    leading: float = 1.35,
) -> float:
    """A paragraph, wrapped to `width`. Returns the y below its last line."""
    face = print_font(size_inches, bold=bold)
    step = inches(size_inches * leading)
    for line in wrap_text(sheet.draw, text, face, round(width)):
        sheet.text((left, top), line, face, fill)
        top += step
    return top


def draw_centered(
    sheet: Sheet,
    center_x: float,
    top: float,
    width: float,
    text: str,
    size_inches: float,
    fill: str,
    leading: float = 1.3,
) -> float:
    """A centred paragraph, wrapped to `width`. Returns the y below it."""
    face = print_font(size_inches)
    step = inches(size_inches * leading)
    for line in wrap_text(sheet.draw, text, face, round(width)):
        sheet.text((center_x, top), line, face, fill, anchor="ma")
        top += step
    return top


def draw_heading(
    sheet: Sheet,
    left: float,
    top: float,
    width: float,
    text: str,
    size_inches: float,
    ink: str,
    rule: Optional[str] = None,
) -> float:
    """A small caps-style section heading over a hairline. Returns the y below it."""
    draw_fitted(sheet, (left, top), text, width, size_inches, ink, bold=True)
    below = top + inches(size_inches * 1.5)
    if rule is not None:
        sheet.rect((left, below, left + width, below + inches(0.012)), fill=rule)
        below += inches(0.14)
    return below


def letterspaced_width(
    sheet: Sheet, text: str, size_inches: float, spacing: float
) -> float:
    """
    How wide `letterspaced` will draw that line.

    Its own function because the spacing is most of the width of a
    short line -- the publisher's name carries twenty gaps -- and a
    caller that measured it with `text_width` instead would lay the
    rest of the panel out around a line an inch narrower than the one
    that gets drawn.
    """
    face = print_font(size_inches, bold=True)
    return (
        sum(sheet.text_width(letter, face) for letter in text)
        + inches(spacing) * (len(text) - 1)
    )


def letterspaced(
    sheet: Sheet,
    center: tuple[float, float],
    text: str,
    size_inches: float,
    fill: str,
    spacing: float,
    anchor: str = "center",
) -> float:
    """
    A line of type with air between the letters, centred on a point.

    Pillow has no tracking, so the string is measured letter by letter
    and drawn the same way -- the same thing `draw_field_end_zone`
    does for GOAL, for the same reason: a short line at display size
    reads as a cluster without it.
    """
    face = print_font(size_inches, bold=True)
    gap = inches(spacing)
    widths = [sheet.text_width(letter, face) for letter in text]
    total = sum(widths) + gap * (len(text) - 1)
    starts = {
        "center": center[0] - total / 2,
        "left": center[0],
        "right": center[0] - total,
    }
    x = starts[anchor]
    for letter, width in zip(text, widths):
        sheet.text((x, center[1]), letter, face, fill, anchor="lm")
        x += width + gap
    return total


# ------------------------------------------------------------- the cast

# Who is on the cover. One player of each species, because four
# species is what the game has, and two facing each way because the
# art is not mirrored: these portraits carry squad numbers, and a
# flipped number is a number nobody wears. Facing is the whole reason
# a name is written down here rather than taken off the top of each
# species' roster -- everything else about them is read from the
# catalog.
# Where the four stand and how tall they come out: the pair nearer
# the middle is the taller, so the group reads as a line closing on
# the ball rather than as four cut-outs in a row. A share is of the
# cover's own width, so nothing here changes if the box does.
# Each entry is (share of the width, height in inches, how far back).
# The back rank is smaller and darkened rather than moved further out:
# these cut-outs are as wide as they are tall, so there is no further
# out to move them to on a square panel.
COVER_PLACES: tuple[tuple[tuple[float, float, float], ...], ...] = (
    ((0.165, 3.5, 0.45), (0.35, 4.6, 0.0)),
    ((0.835, 3.5, 0.45), (0.65, 4.6, 0.0)),
)
# How close to the trim a figure may come. It is not a bleed
# measurement: the art may run off the edge, but a head that leaves
# half of itself outside the box reads as a mistake rather than as a
# crop.
COVER_EDGE = 0.1

COVER_CAST: tuple[tuple[str, str], ...] = (
    ("Voltus", "right"),
    ("Vorix", "right"),
    ("Inferno", "left"),
    ("Slitheron", "left"),
)


def cast_portraits(
    catalog: PlayerCatalog,
) -> tuple[tuple[Image.Image, str, str], ...]:
    """
    The cover's four, each with the colour of a team they play for.

    A portrait that will not load is dropped rather than drawn as a
    hole -- the same silence `load_player_portrait` keeps for a card,
    and for the same reason (see "A bundled file's name is
    case-sensitive..." in docs/design/gotchas.md).
    """
    found: list[tuple[Image.Image, str, str]] = []
    for name, facing in COVER_CAST:
        portrait = load_player_portrait(name)
        if portrait is None:
            continue
        found.append((portrait, facing, cast_color(catalog, name)))
    return tuple(found)


def cast_color(catalog: PlayerCatalog, name: str) -> str:
    """
    The hex of the first team whose sheet this player is on.

    A player appears on a colour team and on their species' team, and
    the two share a hex (see "Team colors" in
    docs/design/teams-and-players.md), so which one is found first
    cannot change the answer.
    """
    for team, definition in catalog.teams.items():
        if any(player.name == name for player in definition.players):
            return TEAM_COLORS[team]
    return ACCENT


def fitted_display(
    sheet: Sheet, text: str, max_width: float, inches_high: float
):
    """The display face at the largest size whose `text` fits `max_width`."""
    size = inches_high
    while size > 0.2:
        face = load_goal_zone_font(max(6, round(inches(size))))
        if sheet.text_width(text, face) <= max_width:
            return face
        size -= 0.02
    return load_goal_zone_font(max(6, round(inches(0.2))))


def draw_cover_field(
    sheet: Sheet,
    panel: Panel,
    rules: BasicRuleset,
    top: float,
    bottom: float,
    palette: "CoverPalette",
) -> None:
    """
    The field the cover's players are standing on: the 7-space board,
    drawn the way the bot draws it rather than the way it prints.

    The spaces and the zones they fall in are read from the ruleset's
    own layout, so the cover cannot show a board the game does not
    play. It carries no space codes and no range bracket: this is the
    field as a picture, and every mark on it that a coach would read
    is a mark the actual board has to be trusted for.
    """
    layout = rules.board_layouts[min(rules.board_layouts)]
    left = panel.x(0.0)
    right = panel.x(panel.width)
    zones = [
        (zone, count)
        for zone, count in layout.zone_spaces.items()
        if count
    ]
    spaces = sum(count for _, count in zones)
    width = (right - left) / spaces
    x = left
    for zone, count in zones:
        for index in range(count):
            sheet.rect(
                (x, top, x + width, bottom),
                fill=palette.zones[zone],
                outline=palette.edge,
                width=max(2, round(inches(0.014))),
            )
            x += width


def render_box_cover(
    facts: Optional[BoxFacts] = None,
    catalog: Optional[PlayerCatalog] = None,
    rules: Optional[BasicRuleset] = None,
    claims: RetailClaims = DEFAULT_CLAIMS,
    bleed: bool = False,
    palette: CoverPalette = PAGE_COVER,
) -> Image.Image:
    """
    The lid's top face: the title, the four, the ball and the facts.

    `palette` is the only thing that changes between the printed cover
    and the night one a post or a store page wants -- see
    `CoverPalette`.
    """
    catalog = catalog or load_player_catalog()
    rules = rules or load_basic_ruleset()
    facts = facts or BoxFacts.read(catalog=catalog, rules=rules)
    side = box_inches()[0]
    panel = Panel(side, side, bleed=bleed)
    sheet = panel.sheet(palette.ground)
    if palette.glows:
        sheet.image.paste(
            vertical_gradient(panel.pixels, "#05090e", "#16242f"), (0, 0)
        )

    margin = 0.75
    content = panel.x(side - margin) - panel.x(margin)
    middle = panel.x(side / 2)

    # The publisher's line, then the title under it.
    letterspaced(
        sheet,
        (middle, panel.y(0.72)),
        PUBLISHER.upper(),
        0.155,
        palette.accent,
        0.075,
    )

    if palette.glows:
        paste_glow(sheet, (middle, panel.y(2.1)), inches(9.0), "#2f6fb0", 120)
    title = fitted_display(sheet, TITLE.upper(), content, 2.15)
    sheet.text(
        (middle, panel.y(1.95)), TITLE.upper(), title, palette.ink, anchor="mm"
    )

    rule_width = inches(2.2)
    for direction in (-1, 1):
        start = middle + direction * inches(0.35)
        sheet.rect(
            (
                min(start, start + direction * rule_width),
                panel.y(3.02),
                max(start, start + direction * rule_width),
                panel.y(3.02) + inches(0.02),
            ),
            fill=palette.accent,
        )
    draw_centered(
        sheet, middle, panel.y(3.22), content * 0.82, STRAPLINE, 0.225,
        palette.muted,
    )

    # The scene. The field is the bottom of the picture, the four
    # stand on it, and the ball is in front of all of it.
    field_top = panel.y(8.6)
    field_bottom = panel.y(9.6)
    if palette.glows:
        paste_glow(sheet, (middle, field_top), inches(13.0), "#3f7fb8", 90)
    draw_cover_field(sheet, panel, rules, field_top, field_bottom, palette)

    baseline = panel.y(9.3)
    cast = cast_portraits(catalog)
    facing_right = [one for one in cast if one[1] == "right"]
    facing_left = [one for one in cast if one[1] == "left"]
    for group, places in zip((facing_right, facing_left), COVER_PLACES):
        for (portrait, _, color), (share, height, depth) in zip(group, places):
            portrait = (
                hazed(portrait, depth * palette.haze_share, palette.haze)
                if depth
                else portrait
            )
            fitted = standing_art(portrait, inches(height))
            # Kept inside the trim by measuring the art first: these
            # cut-outs are as wide as they are tall and a share of the
            # panel's width says nothing about where an arm ends.
            # Pillow crops what falls off the canvas without a word,
            # so a figure that does not fit is moved rather than lost.
            center = clamp_center(
                panel.x(side * share), fitted.width, panel, side, COVER_EDGE
            )
            # A wash of the team's own colour under each figure. On
            # the page it is a tint where the art already is, rather
            # than a colour laid behind the whole panel; on a screen
            # it is the light the figure is standing in.
            paste_glow(
                sheet,
                (
                    center,
                    baseline - inches(height * 0.4 if palette.glows else 0.1),
                ),
                inches(height * (1.1 if palette.glows else 0.55)),
                color,
                80 if palette.glows else 40,
            )
            # The ground they are standing on, so nobody floats over
            # the strip.
            shadow = radial_glow(
                round(fitted.width * 1.1), palette.shadow, 150
            )
            shadow = shadow.resize(
                (shadow.width, max(1, round(shadow.height * 0.22))),
                Image.Resampling.BICUBIC,
            )
            paste_rgba(
                sheet,
                shadow,
                (center - shadow.width / 2, baseline - shadow.height * 0.62),
            )
            paste_standing(sheet, portrait, center, baseline, inches(height))

    # Drawn last, so it is in front of the four rather than between
    # them: it is the thing they are all playing for.
    ball_center = (middle, panel.y(6.15))
    if palette.glows:
        paste_glow(sheet, ball_center, inches(3.9), palette.accent, 170)
    draw_d12(sheet, ball_center, inches(0.7))

    # What a shopper checks before anything else: how many of them,
    # how long, and how old. Nothing else -- the rest of what is in
    # the box is on the underside, where somebody who has already
    # picked it up will read it.
    draw_chip_row(
        sheet, retail_chips(facts, claims), middle, panel.y(10.4), content,
        palette.ink, palette.edge, size_inches=0.185,
    )
    return sheet.image


def retail_chips(facts: BoxFacts, claims: RetailClaims) -> list[str]:
    """The three facts a box is bought on."""
    return [f"{facts.coaches} PLAYERS", *claims.chips]


# Banners. The same art as the cover, laid out wide with the title
# beside the players rather than above them.
#
# `BANNER_INCHES` is 10 x 4in at 300dpi -- 3000 x 1200, twice a Notion
# page cover, so it still reads when that crops it.
# `SCREENTOP_BANNER_PIXELS` is what a Screentop table asks for
# exactly: 1280 x 720, which is 16:9 rather than 2.5:1, so the layout
# is written in **shares of the panel** and not in inches. Two shapes,
# one composition.
BANNER_INCHES = (10.0, 4.0)
SCREENTOP_BANNER_PIXELS = (1280, 720)
SCREENTOP_BANNER_INCHES = (
    SCREENTOP_BANNER_PIXELS[0] / PRINT_DPI,
    SCREENTOP_BANNER_PIXELS[1] / PRINT_DPI,
)
# What a figure is measured against on a banner: its share of the
# height, capped by this share of the width, so the group takes the
# same slice of the panel whatever shape it is.
BANNER_FIGURE_SHARE = 0.4

# Where the four stand on a banner, as shares: the group in the right
# half, so the title has the left to itself. Each is (share of the
# width, share of the height, how far back).
BANNER_PLACES: tuple[tuple[tuple[float, float, float], ...], ...] = (
    ((0.580, 0.65, 0.45), (0.705, 0.79, 0.0)),
    ((0.950, 0.65, 0.45), (0.830, 0.79, 0.0)),
)


def render_banner(
    facts: Optional[BoxFacts] = None,
    catalog: Optional[PlayerCatalog] = None,
    rules: Optional[BasicRuleset] = None,
    bleed: bool = False,
    palette: CoverPalette = NIGHT_COVER,
    size: tuple[float, float] = BANNER_INCHES,
) -> Image.Image:
    """
    The cover's art at banner proportions: the four on the right, the
    title hard beside them on the left.

    A banner is not a cropped cover. A cover's title sits over the
    players with a field of sky between; crop that to a strip and what
    survives is either the words or the art. So the two are one
    composition read two ways -- same cast, same palettes, same
    strapline -- and the only thing that moves is where the title
    goes.

    Everything below is a share of the panel rather than an inch, so
    the same picture comes out at 2.5:1 for a Notion page and at 16:9
    for a Screentop table. It defaults to the night palette, because a
    banner is read on a screen and never printed; `PAGE_COVER` gives
    the white one for a page that wants it.
    """
    catalog = catalog or load_player_catalog()
    rules = rules or load_basic_ruleset()
    facts = facts or BoxFacts.read(catalog=catalog, rules=rules)
    width, height = size
    panel = Panel(width, height, bleed=bleed)
    sheet = panel.sheet(palette.ground)
    if palette.glows:
        sheet.image.paste(
            vertical_gradient(panel.pixels, "#05090e", "#16242f"), (0, 0)
        )

    field_top = panel.y(height * 0.855)
    if palette.glows:
        paste_glow(
            sheet,
            (panel.x(width * 0.7), field_top),
            inches(width * 0.9),
            "#3f7fb8",
            90,
        )
    draw_cover_field(sheet, panel, rules, field_top, panel.y(height), palette)

    baseline = panel.y(height * 0.955)
    cast = cast_portraits(catalog)
    facing_right = [one for one in cast if one[1] == "right"]
    facing_left = [one for one in cast if one[1] == "left"]
    for group, places in zip((facing_right, facing_left), BANNER_PLACES):
        for (portrait, _, color), (across, tall, depth) in zip(group, places):
            # A figure is sized against the panel's height, but never
            # past what keeps the group inside its own share of the
            # width: a 16:9 panel is half again as tall for its width
            # as a 2.5:1 one, and four players scaled to its height
            # fill it end to end.
            figure = tall * min(height, width * BANNER_FIGURE_SHARE)
            portrait = (
                hazed(portrait, depth * palette.haze_share, palette.haze)
                if depth
                else portrait
            )
            fitted = standing_art(portrait, inches(figure))
            center = clamp_center(
                panel.x(width * across), fitted.width, panel, width, COVER_EDGE
            )
            paste_glow(
                sheet,
                (
                    center,
                    baseline - inches(figure * (0.4 if palette.glows else 0.1)),
                ),
                inches(figure * (1.1 if palette.glows else 0.5)),
                color,
                80 if palette.glows else 40,
            )
            shadow = radial_glow(round(fitted.width * 1.1), palette.shadow, 150)
            shadow = shadow.resize(
                (shadow.width, max(1, round(shadow.height * 0.22))),
                Image.Resampling.BICUBIC,
            )
            paste_rgba(
                sheet,
                shadow,
                (center - shadow.width / 2, baseline - shadow.height * 0.62),
            )
            paste_standing(sheet, portrait, center, baseline, inches(figure))

    # The ball is **on the ground between the two nearest players**,
    # not in the air over them: at head height it lands on somebody's
    # face, and a ball on a field is where a ball is anyway.
    ball_radius = min(height, width * BANNER_FIGURE_SHARE) * 0.115
    ball_center = (
        panel.x(width * 0.768),
        baseline - inches(ball_radius * 0.9),
    )
    if palette.glows:
        paste_glow(sheet, ball_center, inches(height * 0.7), palette.accent, 150)
    draw_d12(sheet, ball_center, inches(ball_radius))

    # The title block, hard against the group rather than over it.
    left = panel.x(width * 0.055)
    words = width * 0.36
    letterspaced(
        sheet,
        (left, panel.y(height * 0.26)),
        PUBLISHER.upper(),
        height * 0.035,
        palette.accent,
        height * 0.015,
        anchor="left",
    )
    title = fitted_display(sheet, TITLE.upper(), inches(words), height * 0.34)
    sheet.text(
        (left, panel.y(height * 0.455)),
        TITLE.upper(),
        title,
        palette.ink,
        anchor="lm",
    )
    sheet.rect(
        (
            left,
            panel.y(height * 0.585),
            left + inches(width * 0.15),
            panel.y(height * 0.585) + inches(height * 0.005),
        ),
        fill=palette.accent,
    )
    draw_wrapped(
        sheet,
        left,
        panel.y(height * 0.635),
        inches(words),
        STRAPLINE,
        height * 0.042,
        palette.muted,
        leading=1.3,
    )
    return sheet.image


def draw_chip_row(
    sheet: Sheet,
    chips: Sequence[str],
    center_x: float,
    center_y: float,
    max_width: float,
    ink: str,
    edge: str,
    size_inches: float = 0.145,
) -> None:
    """
    A row of chips, centred, shrunk together until the row fits.

    The row is measured before it is drawn rather than wrapped: these
    are four short facts on one line, and a fact that has fallen onto
    a second line has stopped being a chip.
    """
    gap = inches(0.16)
    while size_inches > 0.09:
        face = print_font(size_inches, bold=True)
        widths = [
            sheet.text_width(chip, face) + inches(0.16) * 2 for chip in chips
        ]
        total = sum(widths) + gap * (len(chips) - 1)
        if total <= max_width:
            break
        size_inches -= 0.005
    left = center_x - total / 2
    for chip in chips:
        left = draw_chip(
            sheet, left, center_y, chip, size_inches, ink, edge
        ) + gap


def render_box_side(
    facts: Optional[BoxFacts] = None,
    bleed: bool = False,
) -> Image.Image:
    """
    One side of the box -- and all four of them, since the box is
    square and every wall is the same rectangle. It is the only panel
    of the five that is read edge-on off a shelf, so it carries the
    title, the ball and nothing that needs more than a glance.
    """
    facts = facts or BoxFacts.read()
    side, _, depth = box_inches()
    panel = Panel(side, depth, bleed=bleed)
    sheet = panel.sheet(PAPER)

    middle_y = panel.y(depth / 2)
    ball_center = (panel.x(0.95), middle_y)
    draw_d12(sheet, ball_center, inches(0.5))

    title_left = panel.x(1.75)
    facts_line = (
        f"{facts.coaches} coaches · {facts.players_per_team} players a "
        f"team · basic & advanced"
    )
    tail = print_font(0.16, bold=True)
    tail_width = max(
        sheet.text_width(facts_line, tail),
        letterspaced_width(sheet, PUBLISHER.upper(), 0.15, 0.055),
    )
    room = panel.x(side - 0.7) - title_left - tail_width - inches(0.5)
    title = fitted_display(sheet, TITLE.upper(), room, 1.15)
    sheet.text((title_left, middle_y), TITLE.upper(), title, PAPER_INK, anchor="lm")

    right = panel.x(side - 0.7)
    letterspaced(
        sheet,
        (right, middle_y - inches(0.22)),
        PUBLISHER.upper(),
        0.15,
        ACCENT,
        0.055,
        anchor="right",
    )
    sheet.text(
        (right, middle_y + inches(0.28)), facts_line, tail, PAPER_MUTED, anchor="rm"
    )
    return sheet.image


# ------------------------------------------------------- the underside

# The area a retail barcode is printed in, at the nominal size of an
# EAN-13 symbol (37.29 x 25.93mm). Reserved and labelled rather than
# drawn: the number belongs to whoever publishes the game, and a
# barcode that scans as something else is worse than a blank.
BARCODE_INCHES = (1.47, 1.02)


# The meeple, as the Screentop table draws it -- the author's own
# path, so a piece on a printed panel and a piece on the virtual table
# are one shape rather than two drawings of the same idea. It is an
# SVG path with the origin at the middle of the piece; `meeple_outline`
# flattens it once and everything else scales that.
MEEPLE_PATH = (
    "M 0 -29.62 C -3.98 -29.62 -6.83 -27.5 -8.5 -24.86 C -9.96 -22.51 "
    "-10.58 -19.75 -10.7 -17.34 C -15.22 -15.13 -20.2 -12.87 -24.22 "
    "-10.58 C -26.34 -9.4 -28.17 -8.17 -29.56 -6.87 C -30.95 -5.55 "
    "-31.97 -4.08 -31.97 -2.35 C -31.97 -1.62 -31.61 -1.02 -31.19 -0.58 "
    "C -30.78 -0.13 -30.32 0.2 -29.76 0.51 C -28.63 1.18 -27.24 1.69 "
    "-25.73 2.15 C -23.44 2.84 -20.88 3.36 -18.67 3.56 C -20.88 7.36 "
    "-23.82 10.86 -26.39 14.23 C -29.38 18.09 -31.97 21.8 -31.97 25.95 "
    "C -31.97 26.52 -31.97 26.96 -31.93 27.44 C -31.88 27.91 -31.73 "
    "28.5 -31.28 28.94 C -30.8 29.39 -30.25 29.52 -29.76 29.56 C -29.31 "
    "29.64 -28.84 29.62 -28.25 29.62 L -11.82 29.62 C -10.62 29.62 "
    "-9.76 29.69 -8.85 29.11 C -7.94 28.53 -7.63 27.74 -6.98 26.57 "
    "L -6.96 26.55 L -6.95 26.51 S -5.51 23.58 -3.82 20.73 C -2.95 "
    "19.28 -2.04 17.84 -1.22 16.81 C -0.81 16.3 -0.45 15.91 -0.16 15.67 "
    "C -0.09 15.6 -0.06 15.6 0 15.56 C 0.06 15.6 0.09 15.6 0.17 15.67 "
    "C 0.42 15.91 0.82 16.3 1.22 16.81 C 2.04 17.84 2.96 19.28 3.82 "
    "20.73 C 5.52 23.58 6.95 26.51 6.95 26.51 L 6.97 26.55 L 6.98 26.57 "
    "C 7.63 27.74 7.94 28.53 8.84 29.11 C 9.72 29.69 10.59 29.62 11.78 "
    "29.62 L 28.3 29.62 C 28.88 29.62 29.34 29.64 29.79 29.56 C 30.28 "
    "29.52 30.82 29.39 31.29 28.93 C 31.75 28.48 31.89 27.91 31.93 "
    "27.44 C 31.98 26.96 31.98 26.52 31.98 25.95 C 31.98 21.8 29.39 "
    "18.09 26.4 14.23 C 23.82 10.86 20.88 7.36 18.67 3.56 C 20.88 3.36 "
    "23.45 2.84 25.73 2.15 C 27.23 1.69 28.63 1.18 29.76 0.51 C 30.32 "
    "0.2 30.79 -0.13 31.2 -0.58 C 31.62 -1.01 31.98 -1.6 31.98 -2.35 "
    "C 31.98 -4.08 30.95 -5.53 29.56 -6.86 C 28.18 -8.17 26.34 -9.39 "
    "24.22 -10.57 C 20.21 -12.87 15.23 -15.13 10.71 -17.34 C 10.59 "
    "-19.75 9.97 -22.49 8.5 -24.86 C 6.83 -27.5 3.98 -29.62 0 -29.62 Z"
)
# Where the role's two letters sit on the piece, in the path's own
# units: below the arms, on the chest, which is where the Screentop
# table puts them.
MEEPLE_CODE_CENTER = 11.0
MEEPLE_CODE_WIDTH = 26.0
_PATH_TOKEN = re.compile(r"[MCSLZ]|-?\d+(?:\.\d+)?")
_MEEPLE_OUTLINE: list[tuple[float, float]] = []


def flatten_path(path: str, steps: int = 14) -> list[tuple[float, float]]:
    """
    An SVG path as a polygon, for the subset the meeple is written in
    (absolute `M`, `L`, `C`, `S`, `Z`).

    Pillow draws polygons, not curves, so every cubic is sampled --
    fourteen segments each, which at any size these panels print at is
    under a printed dot. It is a reader rather than a rewrite of the
    path because the path is the author's: retyping it as a list of
    points is how the piece on the box would come to differ from the
    piece on the table.
    """
    tokens = _PATH_TOKEN.findall(path)
    points: list[tuple[float, float]] = []
    index = 0
    command = ""
    current = start = (0.0, 0.0)
    control: Optional[tuple[float, float]] = None
    while index < len(tokens):
        if tokens[index] in "MCSLZ":
            command = tokens[index]
            index += 1
            if command == "Z":
                points.append(start)
                control = None
                continue
        numbers = []
        for _ in range({"M": 2, "L": 2, "C": 6, "S": 4}[command]):
            numbers.append(float(tokens[index]))
            index += 1
        if command in ("M", "L"):
            current = (numbers[0], numbers[1])
            if command == "M":
                start = current
            points.append(current)
            control = None
            continue
        if command == "C":
            first = (numbers[0], numbers[1])
            second = (numbers[2], numbers[3])
            end = (numbers[4], numbers[5])
        else:
            # `S` reflects the previous curve's second control point,
            # which is the whole of what makes it smooth.
            first = (
                (2 * current[0] - control[0], 2 * current[1] - control[1])
                if control
                else current
            )
            second = (numbers[0], numbers[1])
            end = (numbers[2], numbers[3])
        for step in range(1, steps + 1):
            t = step / steps
            u = 1 - t
            points.append(
                (
                    u ** 3 * current[0] + 3 * u * u * t * first[0]
                    + 3 * u * t * t * second[0] + t ** 3 * end[0],
                    u ** 3 * current[1] + 3 * u * u * t * first[1]
                    + 3 * u * t * t * second[1] + t ** 3 * end[1],
                )
            )
        control = second
        current = end
    return points


def meeple_outline() -> list[tuple[float, float]]:
    """The path, flattened once and kept."""
    if not _MEEPLE_OUTLINE:
        _MEEPLE_OUTLINE.extend(flatten_path(MEEPLE_PATH))
    return _MEEPLE_OUTLINE


def meeple_size() -> tuple[float, float]:
    """How wide and tall the piece is in the path's own units."""
    outline = meeple_outline()
    xs = [x for x, _ in outline]
    ys = [y for _, y in outline]
    return max(xs) - min(xs), max(ys) - min(ys)


def draw_meeple(
    sheet: Sheet,
    center_x: float,
    base: float,
    height: float,
    fill: str,
    code: Optional[str] = None,
    outline: str = PAPER_INK,
) -> None:
    """
    A meeple: the piece a coach pushes around the printed board, in
    its team's colour with the player's **role** on its chest.

    The bot draws a player as a coloured disc because a screen token
    is a label; what stands on a table is a pawn, so the picture of
    the game shows the pawn -- and it shows the author's own outline
    (`MEEPLE_PATH`), the one the Screentop table draws, rather than a
    silhouette redrawn from a screenshot. The two letters are
    `ROLE_INITIALS`, the spelling every other drawing of a role reads
    (see `role_initials` in `d12ball/formatting.py`), and their colour
    is `high_contrast_ink`, because white disappears on slime green.
    """
    outline_points = meeple_outline()
    _, path_height = meeple_size()
    scale = height / path_height
    bottom = max(y for _, y in outline_points)
    sheet.polygon(
        [
            (center_x + x * scale, base + (y - bottom) * scale)
            for x, y in outline_points
        ],
        fill=fill,
        outline=outline,
        width=max(1, round(height * 0.03)),
    )
    if not code:
        return
    # Fitted to the chest rather than set at a share of the height: a
    # role is two letters and some of them are wider than others.
    size = round(height * 0.3)
    while size > 4:
        face = load_font(size, bold=True)
        if sheet.text_width(code, face) <= MEEPLE_CODE_WIDTH * scale:
            break
        size -= 1
    sheet.text(
        (center_x, base + (MEEPLE_CODE_CENTER - bottom) * scale),
        code,
        face,
        high_contrast_ink(fill),
        anchor="mm",
    )


def board_photo(
    rules: Optional[BasicRuleset] = None,
    catalog: Optional[PlayerCatalog] = None,
    home: Team = Team.PURPLE,
    visiting: Team = Team.TEAL,
    strip_only: bool = False,
) -> Image.Image:
    """
    The picture of the game: **the printed field board**, with meeples
    standing on it at the standard deal and the ball on the kickoff
    space.

    It is `boards.render_field_board`'s own board, not a second
    drawing of one and not the bot's screen board -- what somebody
    buying this game will have on their table is the printed one, so
    that is what the box shows. The deal is `MatchState.standard`'s,
    and where each space sits is `FieldGeometry`'s, so a layout change
    upstream moves the meeples with it.

    Cropped to the strip and the bands around it: the board is
    portrait and most of its length is the two zone-assignment card
    rows, which say nothing in a picture an inch and a half tall.
    """
    rules = rules or load_basic_ruleset()
    catalog = catalog or load_player_catalog()
    board_size = min(rules.board_layouts)
    layout = rules.board_layouts[board_size]

    printed = render_field_board(rules, board_size=board_size)
    sheet = Sheet(printed.width, printed.height, background=PAPER)
    sheet.image.paste(printed, (0, 0))
    geometry = FieldGeometry.for_sheet(sheet, layout)

    match = MatchState.standard(
        catalog=catalog,
        ruleset=rules,
        board_size=board_size,
        home_team=home,
        visiting_team=visiting,
        home_formation=Formation.TWO_TWO_TWO,
        visiting_formation=Formation.TWO_TWO_TWO,
    )
    draw_meeples_on_board(sheet, geometry, match, catalog)

    # **Nothing draws a ball here.** `boards.draw_kickoff_marks`
    # already prints one on the kickoff space -- a twelve-sided mark
    # with the ball's speed on it and "KICKOFF / ball at speed 1"
    # under it -- and a second one laid over it came out as two balls,
    # the board's showing round the edge of this module's. Covering it
    # instead would mean a copy of that mark's own placement here,
    # which is the kind of second reading that drifts; the board is
    # the thing being photographed, so the board's ball is the ball.
    strip_height = geometry.strip_bottom - geometry.strip_top

    # Cut to the board itself: the title, the arrows, the strip and
    # the range bracket. The two zone-assignment rows are most of this
    # sheet's length and the visiting coach's is printed upside down
    # for them, which is right on the table and is a mistake in a
    # picture, so the crop stops inside both of them.
    pad = strip_height * 0.12
    # `strip_only` drops the title and the arrows as well, for a panel
    # that is much wider than it is tall: what is left is the row of
    # spaces and the range bracket under it, which is the game.
    top = geometry.direction_top if strip_only else geometry.header_top
    return sheet.image.crop(
        (
            0,
            round(max(geometry.visiting_zone_bottom, top - pad)),
            printed.width,
            round(min(geometry.home_zone_top, geometry.range_bottom + pad)),
        )
    )


def draw_meeples_on_board(
    sheet: Sheet,
    geometry: FieldGeometry,
    match: MatchState,
    catalog: PlayerCatalog,
) -> None:
    """
    Each side's pieces where the deal put them: home along the front
    of a space and the visitors behind them, which is how two coaches
    sitting opposite each other actually fill one space.
    """
    strip_height = geometry.strip_bottom - geometry.strip_top
    for index, space in enumerate(match.board.spaces_in_order()):
        left, right = geometry.space_bounds(index)
        by_side: dict[TeamSide, list[str]] = {
            TeamSide.HOME: [], TeamSide.VISITING: []
        }
        for player_id in space:
            by_side[match.side_for_player(player_id)].append(player_id)
        for side, players in by_side.items():
            if not players:
                continue
            color = TEAM_COLORS[match.setup_for_side(side).team]
            # Home stands on the near half of the space and the
            # visitors on the far half: a space belongs to nobody,
            # so the only thing dividing it is which coach is
            # reaching across the table for it.
            base = geometry.strip_top + strip_height * (
                0.92 if side == TeamSide.HOME else 0.46
            )
            height = min(strip_height * 0.4, (right - left) * 0.62)
            span = (right - left) * 0.78
            step = span / max(1, len(players))
            start = (left + right) / 2 - span / 2 + step / 2
            for slot, player_id in enumerate(players):
                draw_meeple(
                    sheet,
                    start + slot * step,
                    base,
                    height,
                    color,
                    code=ROLE_INITIALS[
                        catalog.player_by_id(player_id).role.value
                    ],
                )


def draw_framed(
    sheet: Sheet,
    art: Image.Image,
    box: tuple[float, float, float, float],
    edge: str,
    width: float = 0.02,
) -> None:
    """A picture fitted into `box` with a hairline around what it fills."""
    left, top, right, bottom = box
    scale = min((right - left) / art.width, (bottom - top) / art.height)
    size = (max(1, round(art.width * scale)), max(1, round(art.height * scale)))
    fitted = art.resize(size, Image.Resampling.LANCZOS)
    x = left + ((right - left) - size[0]) / 2
    y = top + ((bottom - top) - size[1]) / 2
    sheet.image.paste(fitted, (round(x), round(y)))
    sheet.rect(
        (x, y, x + size[0], y + size[1]),
        outline=edge,
        width=max(1, round(inches(width))),
    )


def render_box_bottom(
    facts: Optional[BoxFacts] = None,
    catalog: Optional[PlayerCatalog] = None,
    rules: Optional[BasicRuleset] = None,
    maneuvers: Optional[ManeuverCatalog] = None,
    bleed: bool = False,
) -> Image.Image:
    """
    The underside of the box: what is in it, how a turn goes, and a
    picture of the game being played.

    Every list on it is read rather than written -- the components are
    the Learn to Play's own, the counts are the catalogs', and the
    three beats are quoted from the books with their Laws beside them.
    """
    catalog = catalog or load_player_catalog()
    rules = rules or load_basic_ruleset()
    maneuvers = maneuvers or load_maneuver_catalog()
    facts = facts or BoxFacts.read(catalog=catalog, maneuvers=maneuvers, rules=rules)
    side = box_inches()[0]
    panel = Panel(side, side, bleed=bleed)
    sheet = panel.sheet(PAPER)

    margin = 0.75
    left = panel.x(margin)
    right = panel.x(side - margin)
    content = right - left

    # The header, and the hook under it.
    title = fitted_display(sheet, TITLE.upper(), content * 0.45, 0.78)
    sheet.text((left, panel.y(0.95)), TITLE.upper(), title, PAPER_INK, anchor="lm")
    letterspaced(
        sheet, (right, panel.y(0.95)), PUBLISHER.upper(), 0.15, ACCENT, 0.06,
        anchor="right",
    )
    sheet.rect(
        (left, panel.y(1.38), right, panel.y(1.38) + inches(0.02)), fill=ACCENT
    )
    draw_wrapped(
        sheet, left, panel.y(1.62), content, HOOK, 0.235, PAPER_INK, leading=1.45
    )

    # The game itself, and one card from each side of a maneuver --
    # because a maneuver is two of them.
    photo_top = panel.y(2.7)
    photo_bottom = photo_top + inches(2.35)
    photo_right = left + inches(4.6)
    draw_framed(
        sheet,
        board_photo(rules, catalog),
        (left, photo_top, photo_right, photo_bottom),
        PANEL_EDGE_INK,
    )
    pair = (first_basic(maneuvers.offense), first_basic(maneuvers.defense))
    card_width = (photo_bottom - photo_top) * CARD_WIDTH / CARD_HEIGHT
    x = right - card_width * 2 - inches(0.35)
    for definition, is_offense in zip(pair, (True, False)):
        draw_framed(
        sheet,
        render_maneuver_card(maneuvers, catalog, definition, is_offense, False),
        (x, photo_top, x + card_width, photo_bottom),
        PANEL_EDGE_INK,
        )
        x += card_width + inches(0.35)
    draw_fitted(
        sheet,
        (left, photo_bottom + inches(0.22)),
        "The printed field board at kickoff, and two of the twelve cards.",
        inches(4.6),
        0.145,
        PAPER_MUTED,
    )
    draw_species_row(
        sheet, right, photo_bottom + inches(0.1), inches(5.0)
    )

    # Two columns: what is in the box, and what a turn is.
    column = (content - inches(0.7)) / 2
    second = left + column + inches(0.7)
    top = photo_bottom + inches(1.05)

    y = draw_heading(
        sheet, left, top, column, "WHAT IS IN THE BOX", 0.2, ACCENT, PANEL_EDGE_INK
    )
    for entry in box_contents():
        y = draw_bullet(sheet, left, y, column, entry, 0.14, PAPER_MUTED, ACCENT)
    draw_fitted(
        sheet,
        (left, y + inches(0.14)),
        f"{facts.basic_maneuvers} basic cards and {facts.gambits} gambits · "
        f"{facts.teams} teams · {facts.species} species · "
        f"{facts.players_per_team} players a team",
        column,
        0.145,
        ACCENT,
        bold=True,
    )

    right_y = draw_heading(
        sheet, second, top, column, "HOW A TURN GOES", 0.2, ACCENT, PANEL_EDGE_INK
    )
    for index, (line, law) in enumerate(TURN_BEATS, start=1):
        right_y = draw_beat(sheet, second, right_y, column, index, line, law)
    right_y = draw_heading(
        sheet,
        second,
        right_y + inches(0.12),
        column,
        "TWO MODES",
        0.2,
        ACCENT,
        PANEL_EDGE_INK,
    )
    draw_wrapped(
        sheet,
        second,
        right_y,
        column,
        "Basic mode is the whole game on its own. Advanced mode adds a "
        "second card to every maneuver and gives each of the "
        f"{facts.species} species an ability.",
        0.145,
        PAPER_MUTED,
    )

    # The footer: the one sentence that outranks everything printed
    # anywhere, and the space the barcode goes in.
    footer = panel.y(side - margin + 0.05)
    sheet.rect(
        (left, footer - inches(1.1), right, footer - inches(1.08)),
        fill=PANEL_EDGE_INK,
    )
    words = content - inches(BARCODE_INCHES[0] + 0.45)
    draw_fitted(
        sheet,
        (left, footer - inches(0.92)),
        CHARTER_LINE,
        words,
        0.185,
        PAPER_INK,
        bold=True,
    )
    draw_wrapped(
        sheet,
        left,
        footer - inches(0.58),
        words,
        f"{TITLE} is published by {PUBLISHER}. The rules are the D12Ball "
        "Charter, and the Charter is what settles a table's argument -- "
        "it outranks this box, the cards and the boards.",
        0.13,
        PAPER_MUTED,
    )
    draw_barcode_area(sheet, right, footer)
    return sheet.image


def first_basic(definitions: Sequence):
    """The first card of a side that a basic game is played with."""
    for definition in definitions:
        if definition.tier == MANEUVER_TIER_BASIC:
            return definition
    return definitions[0]


def draw_bullet(
    sheet: Sheet,
    left: float,
    top: float,
    width: float,
    text: str,
    size_inches: float,
    fill: str,
    marker: str,
) -> float:
    indent = inches(0.22)
    sheet.rect(
        (
        left,
        top + inches(size_inches * 0.42),
        left + inches(0.07),
        top + inches(size_inches * 0.42) + inches(0.07),
        ),
        fill=marker,
    )
    below = draw_wrapped(
        sheet, left + indent, top, width - indent, text, size_inches, fill
    )
    return below + inches(0.05)


def draw_beat(
    sheet: Sheet,
    left: float,
    top: float,
    width: float,
    number: int,
    line: str,
    law: str,
) -> float:
    """One of the three beats: a numbered disc, the sentence, its Law."""
    radius = inches(0.17)
    center = (left + radius, top + radius)
    sheet.draw.ellipse(
        (
        center[0] - radius,
        center[1] - radius,
        center[0] + radius,
        center[1] + radius,
        ),
        fill=ACCENT,
    )
    sheet.text(
        center, str(number), print_font(0.16, bold=True), "#101822", anchor="mm"
    )
    indent = inches(0.52)
    below = draw_wrapped(
        sheet, left + indent, top, width - indent, line, 0.165, PAPER_INK, bold=True
    )
    below = draw_wrapped(
        sheet, left + indent, below, width - indent, law, 0.12, ACCENT
    )
    return below + inches(0.1)


def draw_species_row(
    sheet: Sheet, right: float, top: float, width: float
) -> float:
    """
    The four species, as the icons the cards and the meeples wear,
    hung off the right edge with their caption under them.

    The icons are `render.species_icon`'s, coloured through it rather
    than pasted from the coloured files on disk -- see "Anything
    drawing a species icon asks render.species_icon" in CLAUDE.md.
    """
    names = list(load_species_abilities())
    # Each species' own team, so the four icons come out in the four
    # team hues rather than in one ink.
    colors = [
        TEAM_COLORS[team]
        for team in (
            Team.FIRE_DEMONS, Team.CYBORGS, Team.TELEKINETICS, Team.OOZES
        )
    ]
    size = inches(0.46)
    gap = inches(0.3)
    span = size * len(names) + gap * (len(names) - 1)
    x = right - span
    for name, color in zip(names, colors):
        icon = species_icon(name, color, size=round(size))
        if icon is not None:
            paste_rgba(sheet, icon, (x, top))
        x += size + gap
    draw_fitted(
        sheet,
        (right, top + size + inches(0.18)),
        "four species, each with an ability in advanced mode",
        width,
        0.145,
        PAPER_MUTED,
        anchor="ra",
    )
    return top + size


def draw_barcode_area(sheet: Sheet, right: float, bottom: float) -> None:
    box = (
        right - inches(BARCODE_INCHES[0]),
        bottom - inches(BARCODE_INCHES[1]),
        right,
        bottom,
    )
    sheet.rect(box, fill="#ffffff")
    draw_fitted(
        sheet,
        ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2),
        "BARCODE",
        inches(BARCODE_INCHES[0]) * 0.8,
        0.13,
        "#8c9aa6",
        bold=True,
        anchor="mm",
    )


# ------------------------------------------------------- the sale sheet

SALE_SHEET_PAPER = "letter"
# How many player cards are fanned across the sheet, and how far each
# one is slid over the last: enough of a card to read its name and
# its art, which is what a fan is for.
SALE_SHEET_CARDS = 8
# Of those, how many are players; the rest are maneuvers, which is
# what a coach is actually holding.
SALE_SHEET_PLAYER_CARDS = 6


def sale_sheet_cards(
    catalog: PlayerCatalog, count: int = SALE_SHEET_CARDS
) -> list[tuple[PlayerDefinition, Team]]:
    """
    Which cards are fanned across the sheet: taken from the four
    colour teams in turn, and from a different part of each roster.

    Read rather than listed, so an import that revises the roster
    revises the fan. The offset per team is what keeps the species
    mixed: a roster is grouped by species, so the first player of all
    four teams is four of the same monster, and a fan of four fire
    demons says the game has one.
    """
    chosen: list[tuple[PlayerDefinition, Team]] = []
    # Rounded up, so a count that is not a multiple of four still
    # visits every team before it runs out.
    per_team = max(1, -(-count // len(COLOR_TEAMS)))
    for index in range(per_team):
        for position, team in enumerate(COLOR_TEAMS):
            players = catalog.teams[team].players
            start = position * len(players) // len(COLOR_TEAMS)
            step = index * len(players) // per_team
            chosen.append((players[(start + step) % len(players)], team))
    return chosen[:count]


def sale_sheet_fan(
    catalog: PlayerCatalog,
    maneuvers: ManeuverCatalog,
    count: int = SALE_SHEET_CARDS,
    players: int = SALE_SHEET_PLAYER_CARDS,
) -> list[Image.Image]:
    """
    What the fan holds: player cards, then one maneuver card from
    each side of a maneuver.

    Both are what a coach picks up -- a player card is who is on the
    field and a maneuver card is what they do -- so the sheet shows
    both rather than a row of one and a mention of the other. They are
    the same size, which is why they fan together at all.
    """
    cards = [
        render_player_card(catalog, player, team, False)
        for player, team in sale_sheet_cards(catalog, players)
    ]
    pair = (first_basic(maneuvers.offense), first_basic(maneuvers.defense))
    for definition, is_offense in zip(pair, (True, False)):
        if len(cards) >= count:
            break
        cards.append(
            render_maneuver_card(maneuvers, catalog, definition, is_offense, False)
        )
    return cards


def render_sale_sheet(
    facts: Optional[BoxFacts] = None,
    catalog: Optional[PlayerCatalog] = None,
    rules: Optional[BasicRuleset] = None,
    maneuvers: Optional[ManeuverCatalog] = None,
    contact: Sequence[str] = (),
    claims: RetailClaims = DEFAULT_CLAIMS,
    bleed: bool = False,
) -> Image.Image:
    """
    One letter page for a buyer, a distributor or a convention table:
    **the components, and almost no words**.

    The first version was three columns of prose -- the game in Law
    1's words, four quoted lines, the whole component list -- which is
    a page nobody reads at a booth. What sells a game across a table
    is what is in the box, so the sheet is the printed board, a fan of
    player cards, a pair of maneuver cards and the three facts a
    shopper checks; everything a reader would have to be sitting down
    for is on the box's own underside and in the rulebooks.

    Light, unlike a banner: this is the piece somebody prints on an
    office printer and hands over. `contact` is whatever lines it
    should be answered on; with none given the space is left ruled and
    empty, since an address nobody has supplied is the one thing here
    that could be wrong in a way nothing could catch.
    """
    catalog = catalog or load_player_catalog()
    rules = rules or load_basic_ruleset()
    maneuvers = maneuvers or load_maneuver_catalog()
    facts = facts or BoxFacts.read(
        catalog=catalog, maneuvers=maneuvers, rules=rules
    )
    width, height = PAPERS[SALE_SHEET_PAPER]
    panel = Panel(width, height, bleed=bleed)
    sheet = panel.sheet(PAPER)

    margin = 0.45
    left = panel.x(margin)
    right = panel.x(width - margin)
    content = right - left

    # The header: the name, the line under it, and who makes it.
    title = fitted_display(sheet, TITLE.upper(), content * 0.62, 1.0)
    sheet.text((left, panel.y(0.95)), TITLE.upper(), title, PAPER_INK, anchor="lm")
    letterspaced(
        sheet, (right, panel.y(0.62)), PUBLISHER.upper(), 0.13, ACCENT, 0.05,
        anchor="right",
    )
    ball_center = (right - inches(0.42), panel.y(1.2))
    draw_d12(sheet, ball_center, inches(0.38))
    draw_wrapped(
        sheet, left, panel.y(1.42), content * 0.72, STRAPLINE, 0.165, PAPER_MUTED,
    )
    sheet.rect(
        (left, panel.y(2.0), right, panel.y(2.0) + inches(0.025)), fill=PAPER_INK
    )

    # The three facts a shopper checks, and then nothing else in words.
    draw_chip_row(
        sheet,
        retail_chips(facts, claims),
        (left + right) / 2,
        panel.y(2.3),
        content,
        PAPER_INK,
        PANEL_EDGE_INK,
        size_inches=0.16,
    )

    # The board, across the sheet.
    photo = board_photo(rules, catalog, strip_only=True)
    photo_top = panel.y(2.7)
    # Cut to the room between the chips and the fan rather than to the
    # sheet's width: the board is the tallest thing here for its
    # width, and at full width it pushes the cards off the page.
    photo_height = inches(3.6)
    photo_width = photo_height * photo.width / photo.height
    photo_left = (left + right) / 2 - photo_width / 2
    draw_framed(
        sheet,
        photo,
        (photo_left, photo_top, photo_left + photo_width, photo_top + photo_height),
        PANEL_EDGE_INK,
        width=0.012,
    )
    caption_y = photo_top + photo_height + inches(0.14)
    draw_fitted(
        sheet,
        (left, caption_y),
        "The field board at kickoff.",
        content * 0.6,
        0.13,
        PAPER_MUTED,
    )

    # The cards, fanned: a player card is the thing somebody picks up
    # first, so the sheet shows as many as it can hold.
    fan_top = caption_y + inches(0.38)
    fan_height = inches(2.2)
    fan_cards(
        sheet, sale_sheet_fan(catalog, maneuvers), left, fan_top, content,
        fan_height,
    )

    # The foot: where an answer goes, and the code that answers it
    # without one -- the game's own page, so a sheet handed across a
    # table is not a dead end when nobody has filled the line in.
    foot_top = panel.y(height - margin - 1.25)
    foot_bottom = panel.y(height - margin)
    sheet.rect(
        (left, foot_top, right, foot_bottom),
        radius=inches(0.09),
        fill=PANEL,
        outline=PANEL_EDGE_INK,
        width=max(1, round(inches(0.012))),
    )
    code = 1.0
    code_left = right - inches(code + 0.16)
    sheet.rect(
        (
            code_left - inches(0.05),
            foot_top + inches(0.1),
            code_left + inches(code + 0.05),
            foot_top + inches(code + 0.2),
        ),
        radius=inches(0.04),
        fill="#ffffff",
        outline=PANEL_EDGE_INK,
        width=max(1, round(inches(0.01))),
    )
    draw_qr(sheet, PAGE_URL, code_left, foot_top + inches(0.15), code)

    words = code_left - inches(0.4) - (left + inches(0.28))
    draw_fitted(
        sheet,
        (left + inches(0.28), foot_top + inches(0.24)),
        "For a playtest copy, a demo or the rulebooks:",
        words,
        0.15,
        PAPER_INK,
        bold=True,
    )
    line_y = foot_top + inches(0.62)
    if contact:
        for entry in contact:
            line_y = draw_wrapped(
                sheet, left + inches(0.28), line_y, words, entry, 0.13,
                PAPER_INK,
            )
    else:
        sheet.rect(
            (
                left + inches(0.28),
                line_y + inches(0.14),
                left + inches(0.28) + words,
                line_y + inches(0.15),
            ),
            fill=PANEL_EDGE_INK,
        )
    return sheet.image


def fan_cards(
    sheet: Sheet,
    cards: Sequence[Image.Image],
    left: float,
    top: float,
    width: float,
    height: float,
) -> None:
    """
    Cards laid across the sheet, each sliding over the last.

    Overlapped rather than tiled: a card small enough for eight of
    them to sit side by side is a stamp, where eight fanned are eight
    cards of which the first seven show their name and their art --
    which is what somebody looks at anyway. The last one is whole, so
    at least one card is on the page in full.
    """
    card_width = height * CARD_WIDTH / CARD_HEIGHT
    step = (width - card_width) / max(1, len(cards) - 1)
    for index, art in enumerate(cards):
        fitted = art.resize(
            (max(1, round(card_width)), max(1, round(height))),
            Image.Resampling.LANCZOS,
        )
        x = round(left + index * step)
        sheet.image.paste(fitted, (x, round(top)))
        sheet.rect(
            (x, top, x + card_width, top + height),
            outline=PANEL_EDGE_INK,
            width=max(1, round(inches(0.01))),
        )


# ---------------------------------------------------- the playtest card

# A postcard, landscape, because the picture on its front is the
# board and the board is wider than it is tall.
PLAYTEST_CARD_INCHES = (6.0, 4.0)
# The smallest module a printed QR may be drawn at. 0.4mm is the
# floor a phone camera reads reliably off an office printer at arm's
# length; the card's own code comes out well above it, and
# `BoxArtSurveyTests` fails if a longer URL ever pushes it under.
QR_MIN_MODULE_INCHES = 0.4 / 25.4


def qr_matrix(data: str) -> list[list[bool]]:
    """
    The survey URL as a grid of modules, quiet zone included.

    `qrcode` is imported here rather than at the top of the module so
    that a checkout that has not reinstalled its requirements still
    loads everything else -- the bot imports this package, and the
    only thing in it that needs a QR encoder is a card nobody renders
    from the bot.
    """
    try:
        import qrcode
    except ModuleNotFoundError as error:  # pragma: no cover - environment
        raise ModuleNotFoundError(
            "Rendering the playtest card needs the `qrcode` package: "
            "pip install -r requirements.txt"
        ) from error

    code = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        border=4,
    )
    code.add_data(data)
    code.make(fit=True)
    return code.get_matrix()


def qr_module_inches(data: str, size_inches: float) -> float:
    """How big one module comes out at that printed size."""
    return size_inches / len(qr_matrix(data))


def draw_qr(
    sheet: Sheet,
    data: str,
    left: float,
    top: float,
    size_inches: float,
    dark: str = "#101822",
    light: str = "#ffffff",
) -> None:
    """
    The code, drawn module by module onto the panel.

    Not a generated PNG scaled to fit: a resize lands module edges
    between pixels and softens exactly the contrast a scanner is
    looking for. Each module is rounded to whole pixels off the same
    grid, so every one of them is the same size and the quiet zone
    around them is the white the specification asks for.
    """
    matrix = qr_matrix(data)
    span = inches(size_inches)
    modules = len(matrix)
    sheet.rect((left, top, left + span, top + span), fill=light)
    for row, line in enumerate(matrix):
        for column, is_dark in enumerate(line):
            if not is_dark:
                continue
            sheet.rect(
                (
                    left + span * column / modules,
                    top + span * row / modules,
                    left + span * (column + 1) / modules,
                    top + span * (row + 1) / modules,
                ),
                fill=dark,
            )


def draw_hard_wrapped(
    sheet: Sheet,
    left: float,
    top: float,
    width: float,
    text: str,
    size_inches: float,
    fill: str,
) -> float:
    """
    A line broken wherever it has to be, for text with nothing to
    break on.

    `wrap_text` breaks on spaces, which a URL does not have: handed
    one, it returns the whole address as a single line and Pillow
    draws it straight off the edge of the panel without a word.
    """
    face = print_font(size_inches, bold=False)
    step = inches(size_inches * 1.3)
    line = ""
    for character in text:
        if sheet.text_width(line + character, face) > width and line:
            sheet.text((left, top), line, face, fill)
            top += step
            line = character
        else:
            line += character
    if line:
        sheet.text((left, top), line, face, fill)
        top += step
    return top


def render_playtest_card_front(
    catalog: Optional[PlayerCatalog] = None,
    rules: Optional[BasicRuleset] = None,
    bleed: bool = False,
) -> Image.Image:
    """
    The front of the card handed to a table: the board they have just
    played on, and what it is called.

    The picture sits on the card rather than bleeding off it. It used
    to be full-bleed with the title over a scrim, which was a whole
    card of ink for a caption -- and the board is a light picture now,
    so there is nothing for white type to sit on anyway.
    """
    catalog = catalog or load_player_catalog()
    rules = rules or load_basic_ruleset()
    width, height = PLAYTEST_CARD_INCHES
    panel = Panel(width, height, bleed=bleed)
    sheet = panel.sheet(PAPER)

    margin = 0.32
    left = panel.x(margin)
    right = panel.x(width - margin)

    draw_framed(
        sheet,
        board_photo(rules, catalog, strip_only=True),
        (left, panel.y(margin), right, panel.y(height - 1.15)),
        PANEL_EDGE_INK,
        width=0.014,
    )

    title = fitted_display(sheet, TITLE.upper(), (right - left) * 0.5, 0.62)
    sheet.text(
        (left, panel.y(height - 0.78)), TITLE.upper(), title, PAPER_INK, anchor="lm"
    )
    # The two share a line, so the note is cut to what the name
    # leaves rather than to a share of the card: the publisher's line
    # is letterspaced, and its width is most of that spacing.
    name_width = letterspaced_width(sheet, PUBLISHER.upper(), 0.125, 0.045)
    letterspaced(
        sheet,
        (right, panel.y(height - 0.78)),
        PUBLISHER.upper(),
        0.125,
        ACCENT,
        0.045,
        anchor="right",
    )
    draw_fitted(
        sheet,
        (left, panel.y(height - 0.45)),
        "Playtest copy -- the rules are still moving.",
        right - left - name_width - inches(0.3),
        0.145,
        PAPER_MUTED,
    )
    return sheet.image


def render_playtest_card_back(
    survey_url: str = SURVEY_URL,
    bleed: bool = False,
) -> Image.Image:
    """
    The back: the survey, as a code and as the address under it.

    The address is printed as well as encoded because a code is one
    smudge away from being nothing, and a card whose only route to the
    survey is optical is a card that fails quietly.
    """
    width, height = PLAYTEST_CARD_INCHES
    panel = Panel(width, height, bleed=bleed)
    sheet = panel.sheet(PAPER)

    margin = 0.4
    left = panel.x(margin)
    right = panel.x(width - margin)

    qr_size = 1.8
    qr_left = right - inches(qr_size)
    qr_top = panel.y(0.75)
    sheet.rect(
        (
            qr_left - inches(0.08),
            qr_top - inches(0.08),
            qr_left + inches(qr_size) + inches(0.08),
            qr_top + inches(qr_size) + inches(0.08),
        ),
        radius=inches(0.06),
        fill="#ffffff",
        outline=PANEL_EDGE_INK,
        width=max(1, round(inches(0.014))),
    )
    draw_qr(sheet, survey_url, qr_left, qr_top, qr_size)
    draw_fitted(
        sheet,
        (qr_left + inches(qr_size / 2), panel.y(0.58)),
        "SCAN FOR THE SURVEY",
        inches(qr_size),
        0.145,
        PAPER_INK,
        bold=True,
        anchor="ms",
    )

    words = qr_left - inches(0.4) - left
    draw_fitted(
        sheet, (left, panel.y(0.55)), "How did it play?", words, 0.34,
        PAPER_INK, bold=True,
    )
    below = draw_wrapped(
        sheet,
        left,
        panel.y(1.05),
        words,
        "You have just played a version of this game that will not "
        "exist next month. Tell us what happened: what you had to "
        "look up, what you argued about, and whether you would play "
        "it again.",
        0.135,
        PAPER_INK,
    )
    below += inches(0.12)
    for prompt in PLAYTEST_PROMPTS:
        below = draw_bullet(
            sheet, left, below, words, prompt, 0.12, PAPER_MUTED, ACCENT
        )

    # The address the code carries, small but printed: a code is one
    # smudge away from nothing.
    url_top = panel.y(height - margin - 0.62)
    sheet.rect(
        (left, url_top - inches(0.06), right, url_top - inches(0.05)),
        fill=PANEL_EDGE_INK,
    )
    draw_hard_wrapped(
        sheet, left, url_top + inches(0.06), right - left, survey_url, 0.095,
        PAPER_MUTED,
    )
    letterspaced(
        sheet,
        (right, panel.y(height - margin + 0.02)),
        PUBLISHER.upper(),
        0.115,
        PAPER_INK,
        0.04,
        anchor="right",
    )
    draw_fitted(
        sheet,
        (left, panel.y(height - margin + 0.02)),
        CHARTER_LINE,
        (right - left) * 0.6,
        0.115,
        PAPER_MUTED,
        anchor="lm",
    )
    return sheet.image


# What the survey is actually after, as three things a table can
# answer from the game they just finished rather than in the
# abstract.
PLAYTEST_PROMPTS: tuple[str, ...] = (
    "Which rule did you have to look up mid-turn?",
    "What did the table argue about?",
    "Basic or advanced -- and would you play the other one?",
)
