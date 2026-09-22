"""
The printed things around the game rather than in it: the **box
cover**, the box's **side panel**, the **underside of the box**, the
one-page **sale sheet**, and the **playtest card** whose back carries
the survey QR.

None of these is a component. Nobody plays off them, which is what
makes them different from `boards.py` and `cards.py` and is the only
reason the palette differs: a board is printed at home and read at the
table, so it is dark ink on a light face; a box is manufactured once
and has to be found on a shelf, so the cover, its sides and its
underside are drawn in the bot's own night palette -- the same board a
coach already sees in Discord. The sale sheet and the back of the
playtest card go the other way, because both are things somebody
prints on an office printer and hands over.

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

from dataclasses import dataclass
from typing import Optional, Sequence

from PIL import Image, ImageDraw

from d12ball.boards import (
    BLEED_INCHES,
    DEFAULT_PAPER,
    PAPERS,
    PRINT_DPI,
    Sheet,
    draw_fitted,
    print_font,
)
from d12ball.cards import (
    CARD_HEIGHT,
    CARD_WIDTH,
    FACE_COLOR,
    INK,
    MUTED,
    PANEL_COLOR,
    PANEL_EDGE,
    render_maneuver_card,
)
from d12ball.components import (
    MANEUVER_TIER_BASIC,
    BasicRuleset,
    ManeuverCatalog,
    MatchState,
    PlayerCatalog,
    TeamSide,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
    load_species_abilities,
)
from d12ball.game import Formation, Team, team_display_name
from d12ball.render import (
    TEAM_COLORS,
    ZONE_COLORS,
    load_goal_zone_font,
    load_player_portrait,
    polygon_points,
    render_match_image,
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
PUBLISHER = "Prophetic Fool"
TITLE = "D12 Ball"

# The survey the playtest card sends a table to. A constant rather
# than a literal in the drawing code because it is the one thing on
# the card that will be replaced without the card being redesigned,
# and `scripts/render_box_art.py --survey-url` overrides it.
SURVEY_URL = (
    "https://app.notion.com/p/3a5e1ea7ca618006b187cd98ebf0c9ff"
    "?v=3a5e1ea7ca6180478080000c31b041d0&source=copy_link"
)


# ------------------------------------------------------------- palette

# The night side: the bot's own board, which is where this game's look
# already lives. ZONE_COLORS and TEAM_COLORS are imported rather than
# restated, so a cover and a board drawn on the same evening are the
# same three greys and the same four team hues by construction.
NIGHT = "#080e15"
NIGHT_HIGH = "#17232f"
CHALK = "#ffffff"
CHALK_MUTED = "#9aa5b1"
# The gold the jumbotron's clock is drawn in.
GOLD = "#f0b429"
RULE_DARK = "#2b3a49"

# The paper side, for the two pieces somebody prints themselves: the
# maneuver cards' own palette, exactly as the boards borrow it.
PAPER = FACE_COLOR
PAPER_PANEL = PANEL_COLOR
PAPER_PANEL_EDGE = PANEL_EDGE
PAPER_INK = INK
PAPER_MUTED = MUTED


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
    out of `basic_rules.json`, so both default to nothing and the chip
    is left off rather than invented -- the same call
    `fitted_print_font` makes about a caption it cannot draw legibly.
    Fill them in on the command line once somebody has the numbers.
    """

    play_minutes: Optional[tuple[int, int]] = None
    minimum_age: Optional[int] = None

    @property
    def chips(self) -> tuple[str, ...]:
        chips: list[str] = []
        if self.play_minutes is not None:
            low, high = self.play_minutes
            chips.append(f"{low}-{high} MIN" if low != high else f"{low} MIN")
        if self.minimum_age is not None:
            chips.append(f"AGES {self.minimum_age}+")
        return tuple(chips)


NO_CLAIMS = RetailClaims()


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

    def glance_rows(self) -> tuple[tuple[str, str], ...]:
        """The at-a-glance table on the sale sheet."""
        return (
            ("Coaches", str(self.coaches)),
            (
                "Players",
                f"{self.players_per_team} a team, "
                f"{self.fielded} on the field",
            ),
            ("Teams", f"{self.teams}, across {self.species} species"),
            (
                "Maneuver cards",
                f"{self.maneuvers} -- {self.basic_maneuvers} basic, "
                f"{self.gambits} gambits",
            ),
            ("Field boards", f"{self.board_sizes_phrase} spaces"),
            ("Formations", str(self.formations)),
            ("Dice", "d12, and the ball is one"),
            ("Modes", "Basic and advanced"),
        )


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
TAGLINE = "The ball is a d12, and the face it shows is its speed."
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

# What makes it worth a shelf, in the books' own words.
SELLING_LINES: tuple[str, ...] = (
    "Rank decides, not dice.",
    "The ball is a d12, and the face it shows is its speed.",
    "A tie is not a draw.",
    "A level score goes to the extreme shootout, so every game is settled.",
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


def game_in_brief() -> tuple[str, ...]:
    """Law 1, which is the back of the box whether it meant to be or not."""
    return body_paragraphs(living_rules_section("the-game-in-brief"))


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


def into_the_dark(art: Image.Image, share: float) -> Image.Image:
    """
    A cut-out pushed back into the night, keeping its own alpha.

    The back rank of the cover is darkened rather than faded: a
    cut-out at reduced opacity shows the sky through the middle of a
    player, where the same one darkened reads as somebody standing
    further away in the same light.
    """
    darker = Image.new("RGBA", art.size, (5, 9, 14, 0))
    darker.putalpha(art.getchannel("A").point(lambda value: round(value * share)))
    layered = art.convert("RGBA").copy()
    layered.alpha_composite(darker)
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


def draw_ball(
    sheet: Sheet,
    center: tuple[float, float],
    radius: float,
    face: str = "12",
    fill: str = CHALK,
    outline: str = "#243347",
    text_color: str = "#101822",
) -> None:
    """
    The ball: a d12 showing a face, drawn as the bot's own goal-zone
    ball is -- twelve sides, the number upright in the middle.
    """
    sheet.polygon(
        polygon_points(center[0], center[1], radius, 12),
        fill=fill,
        outline=outline,
        width=max(2, round(radius * 0.05)),
    )
    draw_fitted(
        sheet,
        center,
        face,
        radius * 1.15,
        radius / PRINT_DPI * 1.1,
        text_color,
        bold=True,
        anchor="mm",
    )


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
    return GOLD


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
                fill=ZONE_COLORS[zone],
                outline=RULE_DARK,
                width=max(2, round(inches(0.014))),
            )
            x += width
    # A wash of the night over the far half of the strip, so the
    # field reads as lit from the front rather than as a flat band of
    # three greys under everybody's feet.
    shade = Image.new(
        "RGBA",
        (round(right - left), max(1, round((bottom - top) * 0.55))),
        (0, 0, 0, 0),
    )
    pen = ImageDraw.Draw(shade)
    for row in range(shade.height):
        alpha = round(150 * (1 - row / shade.height))
        pen.line((0, row, shade.width, row), fill=(8, 14, 21, alpha))
    paste_rgba(sheet, shade, (left, top))


def render_box_cover(
    facts: Optional[BoxFacts] = None,
    catalog: Optional[PlayerCatalog] = None,
    rules: Optional[BasicRuleset] = None,
    claims: RetailClaims = NO_CLAIMS,
    bleed: bool = False,
) -> Image.Image:
    """The lid's top face: the title, the four, the ball and the facts."""
    catalog = catalog or load_player_catalog()
    rules = rules or load_basic_ruleset()
    facts = facts or BoxFacts.read(catalog=catalog, rules=rules)
    side = box_inches()[0]
    panel = Panel(side, side, bleed=bleed)
    sheet = panel.sheet(NIGHT)
    sheet.image.paste(vertical_gradient(panel.pixels, "#05090e", "#16242f"), (0, 0))

    margin = 0.75
    content = panel.x(side - margin) - panel.x(margin)
    middle = panel.x(side / 2)

    # The publisher's line, then the title under it.
    letterspaced(
        sheet,
        (middle, panel.y(0.72)),
        f"A {PUBLISHER.upper()} GAME",
        0.155,
        GOLD,
        0.075,
    )

    paste_glow(sheet, (middle, panel.y(2.1)), inches(9.0), "#2f6fb0", 120)
    title = fitted_display(sheet, TITLE.upper(), content, 2.15)
    sheet.text((middle, panel.y(1.95)), TITLE.upper(), title, CHALK, anchor="mm")

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
            fill=GOLD,
        )
    draw_fitted(
        sheet,
        (middle, panel.y(3.35)),
        TAGLINE,
        content,
        0.235,
        CHALK_MUTED,
        anchor="mm",
    )

    # The scene. The field is the bottom of the picture, the four
    # stand on it, and the ball is in front of all of it.
    field_top = panel.y(8.6)
    field_bottom = panel.y(9.6)
    paste_glow(
        sheet, (middle, field_top), inches(13.0), "#3f7fb8", 90
    )
    draw_cover_field(sheet, panel, rules, field_top, field_bottom)

    baseline = panel.y(9.3)
    cast = cast_portraits(catalog)
    facing_right = [one for one in cast if one[1] == "right"]
    facing_left = [one for one in cast if one[1] == "left"]
    for group, places in zip((facing_right, facing_left), COVER_PLACES):
        for (portrait, _, color), (share, height, depth) in zip(group, places):
            portrait = into_the_dark(portrait, depth) if depth else portrait
            fitted = standing_art(portrait, inches(height))
            # Kept inside the trim by measuring the art first: these
            # cut-outs are as wide as they are tall and a share of the
            # panel's width says nothing about where an arm ends.
            # Pillow crops what falls off the canvas without a word,
            # so a figure that does not fit is moved rather than lost.
            center = clamp_center(
                panel.x(side * share), fitted.width, panel, side, COVER_EDGE
            )
            paste_glow(
                sheet,
                (center, baseline - inches(height * 0.4)),
                inches(height * 1.1),
                color,
                80,
            )
            # The ground they are standing on, so nobody floats over
            # the strip.
            shadow = radial_glow(round(fitted.width * 1.1), "#02060a", 200)
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
    paste_glow(sheet, ball_center, inches(3.9), GOLD, 170)
    draw_ball(sheet, ball_center, inches(0.7))

    # The facts, and then the one line about where it is played.
    chips = [
        f"{facts.coaches} COACHES",
        f"{facts.players_per_team} A TEAM · {facts.fielded} ON THE FIELD",
        f"{facts.maneuvers} MANEUVER CARDS",
        "BASIC & ADVANCED",
        *claims.chips,
    ]
    draw_chip_row(sheet, chips, middle, panel.y(10.15), content, CHALK, RULE_DARK)

    draw_fitted(
        sheet,
        (middle, panel.y(10.78)),
        "Play it at the table, or on Discord.",
        content,
        0.2,
        CHALK_MUTED,
        anchor="mm",
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
    sheet = panel.sheet(NIGHT)
    sheet.image.paste(vertical_gradient(panel.pixels, "#0a121b", "#05090e"), (0, 0))

    middle_y = panel.y(depth / 2)
    ball_center = (panel.x(0.95), middle_y)
    paste_glow(sheet, ball_center, inches(2.4), GOLD, 150)
    draw_ball(sheet, ball_center, inches(0.5))

    title_left = panel.x(1.75)
    facts_line = (
        f"{facts.coaches} coaches · {facts.players_per_team} players a "
        f"team · basic & advanced"
    )
    tail = print_font(0.16, bold=True)
    tail_width = max(
        sheet.text_width(facts_line, tail),
        sheet.text_width(PUBLISHER.upper(), print_font(0.15, bold=True)),
    )
    room = panel.x(side - 0.7) - title_left - tail_width - inches(0.5)
    title = fitted_display(sheet, TITLE.upper(), room, 1.15)
    sheet.text((title_left, middle_y), TITLE.upper(), title, CHALK, anchor="lm")

    right = panel.x(side - 0.7)
    letterspaced(
        sheet,
        (right - tail_width / 2, middle_y - inches(0.22)),
        PUBLISHER.upper(),
        0.15,
        GOLD,
        0.055,
    )
    sheet.text(
        (right, middle_y + inches(0.28)), facts_line, tail, CHALK_MUTED, anchor="rm"
    )
    return sheet.image


# ------------------------------------------------------- the underside

# The area a retail barcode is printed in, at the nominal size of an
# EAN-13 symbol (37.29 x 25.93mm). Reserved and labelled rather than
# drawn: the number belongs to whoever publishes the game, and a
# barcode that scans as something else is worse than a blank.
BARCODE_INCHES = (1.47, 1.02)


def game_photo(
    catalog: Optional[PlayerCatalog] = None,
    rules: Optional[BasicRuleset] = None,
    home: Team = Team.PURPLE,
    visiting: Team = Team.TEAL,
) -> Image.Image:
    """
    A picture of the game in play: the board the bot itself posts, for
    a standard deal at kickoff.

    It is `render_match_image`'s own output rather than a photograph
    or a second drawing of the same position, so what is printed on
    the box is what a coach actually sees, and a change to the board
    reaches the box by re-rendering it.
    """
    catalog = catalog or load_player_catalog()
    rules = rules or load_basic_ruleset()
    match = MatchState.standard(
        catalog=catalog,
        ruleset=rules,
        board_size=min(rules.board_layouts),
        home_team=home,
        visiting_team=visiting,
        home_formation=Formation.TWO_TWO_TWO,
        visiting_formation=Formation.TWO_TWO_TWO,
    )
    title = (
        f"{team_display_name(home)} vs. {team_display_name(visiting)}, "
        "kickoff"
    )
    png = render_match_image(match, catalog, title=title, species_icons=True)
    photo = Image.open(png)
    photo.load()
    return photo.convert("RGB")


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
    sheet = panel.sheet(NIGHT)
    sheet.image.paste(vertical_gradient(panel.pixels, "#070d14", "#131f2a"), (0, 0))

    margin = 0.75
    left = panel.x(margin)
    right = panel.x(side - margin)
    content = right - left

    # The header, and the hook under it.
    title = fitted_display(sheet, TITLE.upper(), content * 0.45, 0.78)
    sheet.text((left, panel.y(0.95)), TITLE.upper(), title, CHALK, anchor="lm")
    letterspaced(
        sheet, (right, panel.y(0.95)), PUBLISHER.upper(), 0.15, GOLD, 0.06,
        anchor="right",
    )
    sheet.rect(
        (left, panel.y(1.38), right, panel.y(1.38) + inches(0.02)), fill=GOLD
    )
    draw_wrapped(
        sheet, left, panel.y(1.62), content, HOOK, 0.235, CHALK, leading=1.45
    )

    # The game itself, and one card from each side of a maneuver --
    # because a maneuver is two of them.
    photo_top = panel.y(2.7)
    photo_bottom = photo_top + inches(2.35)
    photo_right = left + inches(4.6)
    draw_framed(
        sheet,
        game_photo(catalog, rules),
        (left, photo_top, photo_right, photo_bottom),
        RULE_DARK,
    )
    pair = (first_basic(maneuvers.offense), first_basic(maneuvers.defense))
    card_width = (photo_bottom - photo_top) * CARD_WIDTH / CARD_HEIGHT
    x = right - card_width * 2 - inches(0.35)
    for definition, is_offense in zip(pair, (True, False)):
        draw_framed(
            sheet,
            render_maneuver_card(maneuvers, catalog, definition, is_offense, False),
            (x, photo_top, x + card_width, photo_bottom),
            RULE_DARK,
        )
        x += card_width + inches(0.35)
    draw_fitted(
        sheet,
        (left, photo_bottom + inches(0.22)),
        "The board as the bot draws it, and two of the twelve cards.",
        inches(4.6),
        0.145,
        CHALK_MUTED,
    )
    draw_species_row(
        sheet, right, photo_bottom + inches(0.1), inches(5.0)
    )

    # Two columns: what is in the box, and what a turn is.
    column = (content - inches(0.7)) / 2
    second = left + column + inches(0.7)
    top = photo_bottom + inches(1.05)

    y = draw_heading(
        sheet, left, top, column, "WHAT IS IN THE BOX", 0.2, GOLD, RULE_DARK
    )
    for entry in box_contents():
        y = draw_bullet(sheet, left, y, column, entry, 0.14, CHALK_MUTED, GOLD)
    draw_fitted(
        sheet,
        (left, y + inches(0.14)),
        f"{facts.basic_maneuvers} basic cards and {facts.gambits} gambits · "
        f"{facts.teams} teams · {facts.species} species · "
        f"{facts.players_per_team} players a team",
        column,
        0.145,
        GOLD,
        bold=True,
    )

    right_y = draw_heading(
        sheet, second, top, column, "HOW A TURN GOES", 0.2, GOLD, RULE_DARK
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
        GOLD,
        RULE_DARK,
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
        CHALK_MUTED,
    )

    # The footer: the one sentence that outranks everything printed
    # anywhere, and the space the barcode goes in.
    footer = panel.y(side - margin + 0.05)
    sheet.rect(
        (left, footer - inches(1.1), right, footer - inches(1.08)),
        fill=RULE_DARK,
    )
    words = content - inches(BARCODE_INCHES[0] + 0.45)
    draw_fitted(
        sheet,
        (left, footer - inches(0.92)),
        CHARTER_LINE,
        words,
        0.185,
        CHALK,
        bold=True,
    )
    draw_wrapped(
        sheet,
        left,
        footer - inches(0.58),
        words,
        f"{TITLE} is a {PUBLISHER} game. The rules are the D12Ball "
        "Charter, and the Charter is what settles a table's argument -- "
        "it outranks this box, the cards and the boards.",
        0.13,
        CHALK_MUTED,
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
        fill=GOLD,
    )
    sheet.text(
        center, str(number), print_font(0.16, bold=True), "#101822", anchor="mm"
    )
    indent = inches(0.52)
    below = draw_wrapped(
        sheet, left + indent, top, width - indent, line, 0.165, CHALK, bold=True
    )
    below = draw_wrapped(
        sheet, left + indent, below, width - indent, law, 0.12, GOLD
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
        CHALK_MUTED,
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


def render_sale_sheet(
    facts: Optional[BoxFacts] = None,
    catalog: Optional[PlayerCatalog] = None,
    rules: Optional[BasicRuleset] = None,
    contact: Sequence[str] = (),
    claims: RetailClaims = NO_CLAIMS,
    bleed: bool = False,
) -> Image.Image:
    """
    One letter page for a buyer, a distributor or a convention table.

    Light, unlike the box: this is the piece somebody prints on an
    office printer and hands over, and the boards are drawn on a light
    face for exactly that reason. Only the header band is the box's
    night, so the two are recognisably one game.

    `contact` is whatever lines the sheet should be answered on. There
    is no default: an address nobody has given is the one thing on
    this page that could be wrong in a way nothing here could catch,
    so the space is left ruled and empty instead.
    """
    catalog = catalog or load_player_catalog()
    rules = rules or load_basic_ruleset()
    facts = facts or BoxFacts.read(catalog=catalog, rules=rules)
    width, height = PAPERS[SALE_SHEET_PAPER]
    panel = Panel(width, height, bleed=bleed)
    sheet = panel.sheet(PAPER)

    margin = 0.55
    left = panel.x(margin)
    right = panel.x(width - margin)
    content = right - left

    # The header band: the box's own night, so the page and the box
    # read as one thing.
    band_bottom = panel.y(2.0)
    sheet.rect((0, 0, panel.pixels[0], band_bottom), fill=NIGHT)
    sheet.image.paste(
        vertical_gradient((panel.pixels[0], round(band_bottom)), "#0a121b", "#1b2b3a"),
        (0, 0),
    )
    title = fitted_display(sheet, TITLE.upper(), content * 0.62, 1.05)
    sheet.text((left, panel.y(0.92)), TITLE.upper(), title, CHALK, anchor="lm")
    letterspaced(
        sheet, (right, panel.y(0.72)), PUBLISHER.upper(), 0.13, GOLD, 0.05,
        anchor="right",
    )
    ball_center = (right - inches(0.45), panel.y(1.3))
    paste_glow(sheet, ball_center, inches(1.9), GOLD, 150)
    draw_ball(sheet, ball_center, inches(0.4))
    draw_fitted(
        sheet,
        (left, panel.y(1.55)),
        TAGLINE,
        content * 0.7,
        0.185,
        CHALK_MUTED,
    )

    top = band_bottom + inches(0.3)
    top = draw_wrapped(
        sheet, left, top, content, HOOK, 0.175, PAPER_INK, bold=True, leading=1.4
    )

    columns_top = top + inches(0.3)
    left_column = inches(4.55)
    right_left = left + left_column + inches(0.45)
    right_column = right - right_left
    # Where the answer panel starts. Measured before either column is
    # drawn, because both of them stop where it does: a line that runs
    # under it is a line nobody reads.
    foot_top = panel.y(height - margin - 1.15)

    # The left column: what the game is, what is unusual about it, and
    # what a buyer is getting in the box.
    y = draw_heading(
        sheet, left, columns_top, left_column, "THE GAME", 0.17,
        PAPER_INK, PAPER_PANEL_EDGE,
    )
    for paragraph in game_in_brief()[:2]:
        y = draw_wrapped(
            sheet, left, y, left_column, paragraph, 0.135, PAPER_INK
        ) + inches(0.1)

    y = draw_heading(
        sheet, left, y + inches(0.16), left_column,
        "WHAT MAKES IT DIFFERENT", 0.17, PAPER_INK, PAPER_PANEL_EDGE,
    )
    for line in SELLING_LINES:
        y = draw_bullet(
            sheet, left, y, left_column, line, 0.135, PAPER_INK, GOLD
        )

    y = draw_heading(
        sheet, left, y + inches(0.16), left_column,
        "WHAT IS IN THE BOX", 0.17, PAPER_INK, PAPER_PANEL_EDGE,
    )
    for entry in box_contents():
        y = draw_bullet(
            sheet, left, y, left_column, entry, 0.12, PAPER_MUTED, PAPER_PANEL_EDGE
        )

    # The right column: the table a buyer reads first, then the game.
    glance_bottom = draw_glance_panel(
        sheet, right_left, columns_top, right_column, facts, claims
    )
    photo_top = glance_bottom + inches(0.3)
    photo = game_photo(catalog, rules)
    photo_height = right_column * photo.height / photo.width
    draw_framed(
        sheet,
        photo,
        (right_left, photo_top, right, photo_top + photo_height),
        PAPER_PANEL_EDGE,
        width=0.014,
    )
    caption_y = draw_wrapped(
        sheet,
        right_left,
        photo_top + photo_height + inches(0.1),
        right_column,
        "The same game on Discord: the bot deals, keeps the clock and "
        "draws the board.",
        0.115,
        PAPER_MUTED,
    )
    species_top = caption_y + inches(0.18)
    if species_top + inches(0.75) < foot_top:
        draw_species_row(sheet, right, species_top, right_column)

    # The foot: where an answer goes.
    sheet.rect(
        (left, foot_top, right, panel.y(height - margin)),
        radius=inches(0.1),
        fill=PAPER_PANEL,
        outline=PAPER_PANEL_EDGE,
        width=max(1, round(inches(0.014))),
    )
    draw_fitted(
        sheet,
        (left + inches(0.3), foot_top + inches(0.22)),
        "For a playtest copy, a demo or the rulebooks:",
        content - inches(0.6),
        0.155,
        PAPER_INK,
        bold=True,
    )
    line_y = foot_top + inches(0.62)
    if contact:
        for entry in contact:
            line_y = draw_wrapped(
                sheet, left + inches(0.3), line_y, content - inches(0.6),
                entry, 0.135, PAPER_INK,
            )
    else:
        sheet.rect(
            (
                left + inches(0.3),
                line_y + inches(0.16),
                right - inches(0.3),
                line_y + inches(0.17),
            ),
            fill=PAPER_PANEL_EDGE,
        )
    draw_fitted(
        sheet,
        (right - inches(0.3), panel.y(height - margin) - inches(0.28)),
        CHARTER_LINE,
        content * 0.5,
        0.125,
        PAPER_MUTED,
        anchor="rs",
    )
    return sheet.image


def draw_glance_panel(
    sheet: Sheet,
    left: float,
    top: float,
    width: float,
    facts: BoxFacts,
    claims: RetailClaims,
) -> float:
    """
    The table a buyer reads before anything else on the page.

    Every row is `BoxFacts`, which is every row read off the game. A
    playing time and an age rating are rows here only once somebody
    has measured them -- see `RetailClaims`.
    """
    rows = list(facts.glance_rows())
    if claims.play_minutes is not None:
        low, high = claims.play_minutes
        rows.insert(
            1, ("Playing time", f"{low}-{high} min" if low != high else f"{low} min")
        )
    if claims.minimum_age is not None:
        rows.insert(2, ("Ages", f"{claims.minimum_age}+"))

    padding = inches(0.18)
    label_width = width * 0.47
    y = top + padding + inches(0.42)
    heights = []
    for _, value in rows:
        lines = wrap_text(
            sheet.draw,
            value,
            print_font(0.125),
            round(width - label_width - padding * 2),
        )
        heights.append(max(1, len(lines)) * inches(0.125 * 1.35) + inches(0.06))
    bottom = y + sum(heights) + padding - inches(0.06)

    sheet.rect(
        (left, top, left + width, bottom),
        radius=inches(0.1),
        fill=PAPER_PANEL,
        outline=PAPER_PANEL_EDGE,
        width=max(1, round(inches(0.014))),
    )
    draw_fitted(
        sheet,
        (left + padding, top + padding),
        "AT A GLANCE",
        width - padding * 2,
        0.155,
        PAPER_INK,
        bold=True,
    )
    for (label, value), step in zip(rows, heights):
        sheet.text(
            (left + padding, y),
            label,
            print_font(0.115, bold=True),
            PAPER_INK,
        )
        draw_wrapped(
            sheet,
            left + padding + label_width,
            y,
            width - label_width - padding * 2,
            value,
            0.125,
            PAPER_MUTED,
        )
        y += step
    return bottom


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
    """The front of the card handed to a table: the game, and what it is called."""
    catalog = catalog or load_player_catalog()
    rules = rules or load_basic_ruleset()
    width, height = PLAYTEST_CARD_INCHES
    panel = Panel(width, height, bleed=bleed)
    sheet = panel.sheet(NIGHT)
    canvas_width, canvas_height = panel.pixels
    # The board across the full width and hung from the top, rather
    # than filled to the card's own shape: a crop that fits this
    # picture to a postcard takes the ends of the field off, and the
    # ends of the field are where the goals are. What the scrim below
    # covers is the two team boards, which are the one part of the
    # picture that says nothing at a glance.
    photo = game_photo(catalog, rules)
    board = photo.resize(
        (
            canvas_width,
            max(1, round(canvas_width * photo.height / photo.width)),
        ),
        Image.Resampling.LANCZOS,
    )
    sheet.image.paste(board, (0, 0))

    # A scrim under the title, so the words hold whatever the board
    # happens to be doing behind them.
    scrim_top = round(canvas_height - inches(1.95))
    scrim = Image.new("RGBA", (canvas_width, canvas_height - scrim_top), (0, 0, 0, 0))
    pen = ImageDraw.Draw(scrim)
    for row in range(scrim.height):
        pen.line(
            (0, row, scrim.width, row),
            fill=(
                5,
                9,
                14,
                round(255 * min(1.0, (row / scrim.height * 2.0) ** 0.8)),
            ),
        )
    paste_rgba(sheet, scrim, (0, scrim_top))

    margin = 0.4
    left = panel.x(margin)
    right = panel.x(width - margin)
    title = fitted_display(sheet, TITLE.upper(), (right - left) * 0.62, 0.72)
    sheet.text(
        (left, panel.y(height - 0.85)), TITLE.upper(), title, CHALK, anchor="lm"
    )
    draw_fitted(
        sheet,
        (left, panel.y(height - 0.52)),
        "Playtest copy -- the rules are still moving.",
        (right - left) * 0.7,
        0.145,
        CHALK_MUTED,
    )
    letterspaced(
        sheet,
        (right, panel.y(height - 0.52)),
        PUBLISHER.upper(),
        0.125,
        GOLD,
        0.045,
        anchor="right",
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
        outline=PAPER_PANEL_EDGE,
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
            sheet, left, below, words, prompt, 0.12, PAPER_MUTED, GOLD
        )

    # The address the code carries, small but printed: a code is one
    # smudge away from nothing.
    url_top = panel.y(height - margin - 0.62)
    sheet.rect(
        (left, url_top - inches(0.06), right, url_top - inches(0.05)),
        fill=PAPER_PANEL_EDGE,
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
