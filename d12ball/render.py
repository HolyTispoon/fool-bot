import logging
from dataclasses import dataclass, replace
from io import BytesIO
from math import cos, hypot, pi, radians, sin
from pathlib import Path
from typing import NamedTuple, Optional

from PIL import Image, ImageDraw, ImageFont

from d12ball.components import (
    duplicate_card_id,
    BoardState,
    MIND_PULL_SUCCESS_FACES,
    SPECIES_CYBORG,
    SPECIES_FIRE_DEMON,
    SPECIES_OOZE,
    SPECIES_TELEKINETIC,
    VOLATILE_IGNITE_FACES,
    VOLATILE_BLAZE_MINIMUM,
    MANEUVER_TIER_BASIC,
    MANEUVER_TIER_GAMBIT,
    ManeuverCatalog,
    ManeuverDefinition,
    MatchState,
    MatchPeriod,
    PlayerCatalog,
    PlayerDefinition,
    RoleProfile,
    TeamSetup,
    TeamSide,
    Zone,
)
from d12ball.game import TEAM_PAIRS, Team, team_display_name
from d12ball.space_numbering import (
    FLAT_SPACE_NUMBERING,
    flat_space_number,
)


IMAGE_WIDTH = 2200
IMAGE_HEIGHT = 1302
OUTPUT_SCALE = 1.5
OUTPUT_SIZE = (
    round(IMAGE_WIDTH * OUTPUT_SCALE),
    round(IMAGE_HEIGHT * OUTPUT_SCALE),
)
BOARD_LEFT = 100
BOARD_RIGHT = IMAGE_WIDTH - 100
JUMBOTRON_TOP = 78
JUMBOTRON_BOTTOM = 238
BOARD_TOP = 430
BOARD_BOTTOM = 805
# The labelled shooting-range bracket under the field -- see
# draw_shooting_range_band. It replaced a dashed line drawn through
# the spaces themselves, which nobody could read, so it needs its own
# band rather than overlapping anything already on the board; the
# canvas grew by the same amount everything below it shifted down.
RANGE_BAND_TOP = BOARD_BOTTOM + 8
RANGE_BAND_HEIGHT = 30
RANGE_BAND_BOTTOM = RANGE_BAND_TOP + RANGE_BAND_HEIGHT
HOME_ASSIGNMENT_CARDS_TOP = RANGE_BAND_BOTTOM + 14
CARD_SIZE = (110, 154)
CARD_INTERNAL_SCALE = 3
CARD_INTERNAL_SIZE = (
    CARD_SIZE[0] * CARD_INTERNAL_SCALE,
    CARD_SIZE[1] * CARD_INTERNAL_SCALE,
)
CARD_OFFENSE_COLOR = "#dc143c"
CARD_DEFENSE_COLOR = "#0f7a35"
TEAM_BOARD_TOP = HOME_ASSIGNMENT_CARDS_TOP + CARD_SIZE[1] + 41
TEAM_BOARD_BOTTOM = IMAGE_HEIGHT - 25
TEAM_BOARD_GAP = 30
# Where BENCH and BACK BENCH sit relative to a team board's own left
# edge, when a short team name leaves room for the old fixed offsets.
# A longer name (a species team's) pushes bench_x right of this; see
# draw_team_board.
TEAM_BOARD_BENCH_MIN_X = 220
TEAM_BOARD_BACK_BENCH_MIN_X = 620
TEAM_BOARD_NAME_GAP = 40
TEAM_BOARD_SECTION_GAP = 40
TEAM_BOARD_BENCH_CARD_SPAN = 3 * (CARD_SIZE[0] + 14) - 14

# The end zones, American-football style -- a zone of their own beyond
# H1 and beyond the board's last V space, not squeezed into either
# one's existing space alongside its own meeples. "GOAL" runs the
# length of each in the defending team's own color, with a blank d12
# stamped over it -- the way an end zone carries a team's color and a
# logo underfoot. Drawn in the margin between the board and the
# canvas edge, so its width is what that margin leaves once the gap to
# the board's own outline and a small edge margin are taken out.
GOAL_ZONE_EDGE_MARGIN = 10
GOAL_ZONE_GAP = 8
GOAL_ZONE_WIDTH = BOARD_LEFT - GOAL_ZONE_EDGE_MARGIN - GOAL_ZONE_GAP
GOAL_ZONE_FILL = "#0c141c"
# Extra room between each letter, on top of the font's own advance --
# a word this short otherwise reads as a small cluster in a tall zone
# rather than something that fills it.
GOAL_ZONE_LETTER_SPACING = 27
GOAL_ZONE_BALL_PAD = 6
GOAL_ZONE_BALL_OUTLINE = "#243347"
# Fully opaque and bright -- it stands in for the "O" itself now
# rather than floating over the whole word, so there is no lettering
# underneath it left to show through.
GOAL_ZONE_BALL_COLOR = "#ffffff"

# The field image: the match image's board and nothing else. Drawn on
# a full-size canvas and cut out of it, so it is the same pixels the
# board everyone is reading is made of -- see render_field_image. Wide
# enough to keep the board's rounded corners and its 4px outline, and
# now the end zones hung off it, off the edge of the crop.
FIELD_MARGIN = BOARD_LEFT - GOAL_ZONE_EDGE_MARGIN

# The full width of the field, end zones included -- what the jumbotron
# and the two team boards below now match, rather than stopping at the
# board's own edge and leaving the end zones looking unclaimed by
# either.
FIELD_FAR_LEFT = BOARD_LEFT - GOAL_ZONE_GAP - GOAL_ZONE_WIDTH
FIELD_FAR_RIGHT = BOARD_RIGHT + GOAL_ZONE_GAP + GOAL_ZONE_WIDTH
JUMBOTRON_LEFT = FIELD_FAR_LEFT
JUMBOTRON_RIGHT = FIELD_FAR_RIGHT

# The coaching image: the field cut in half horizontally, showing one
# coach their own band of it. Narrower than the match image on purpose
# -- it carries one row of meeples instead of two, so at the match
# image's 2200 it would arrive in Discord as an unreadable sliver.
# 1280 keeps a meeple legible inline without a click.
#
# The width still has to fit a meeple. At 1280 a space is 171px on
# board 7 and 133px on board 9, the narrowest, so one MEEPLE_SIZE
# token always sits inside its own space. Two side by side are 155px,
# and no shape either board plays overfills a zone, so a stack that
# wide comes only from a coach placing one there by hand.
COACHING_WIDTH = 1280
COACHING_BOARD_LEFT = 40
COACHING_BOARD_RIGHT = COACHING_WIDTH - 40
COACHING_BOARD_TOP = 64
COACHING_BOARD_BOTTOM = COACHING_BOARD_TOP + 250
# The card rows below the board: each zone's assigned cards under that
# zone, then the two benches. Cards are the only place exhaustion
# counts and the Exhausted and Injured badges are drawn, and all three
# decide what a coach does with this menu, so the flow would be asking
# them to remember numbers off a board they cannot see otherwise.
#
# **No shooting-range bracket here, unlike the match image.** A
# Coaching Choice happens with play stopped and shows only one side's
# own half, so there is no ball and no attempt in progress for a range
# to matter to -- the match image carries it because that is the board
# a shot is actually taken from.
COACHING_CARD_GAP = 12
COACHING_ZONE_CARDS_TOP = COACHING_BOARD_BOTTOM + 18
COACHING_BENCH_LABEL_TOP = COACHING_ZONE_CARDS_TOP + CARD_SIZE[1] + 22
COACHING_BENCH_CARDS_TOP = COACHING_BENCH_LABEL_TOP + 40
COACHING_HEIGHT = COACHING_BENCH_CARDS_TOP + CARD_SIZE[1] + 20
# Where the back bench starts. The two benches always hold three cards
# between them -- nine players, six on the field -- so the split never
# needs more room than this.
COACHING_BACK_BENCH_LEFT = COACHING_WIDTH // 2 + 40

TEAM_COLORS = {
    Team.ORANGE: "#FFA500",
    Team.TEAL: "#008080",
    Team.PURPLE: "#9e4dff",
    Team.SLIME: "#66FF00",
}
# A species team shares its paired color team's hex -- see "Team
# colors" in docs/design/teams-and-players.md. Defined from TEAM_PAIRS rather than restated,
# so there is still exactly one hex per color anywhere in the code.
TEAM_COLORS.update(
    {
        species_team: TEAM_COLORS[color_team]
        for color_team, species_team in TEAM_PAIRS.items()
        if color_team in (Team.ORANGE, Team.TEAL, Team.PURPLE, Team.SLIME)
    }
)
# Slime green is bright enough that white loses contrast against it,
# on a meeple token or a die alike -- Oozes shares the same hex (see
# "Team colors" in docs/design/teams-and-players.md), so comparing the color catches both
# without naming either team. Every other team's color keeps white.
SLIME_GREEN = TEAM_COLORS[Team.SLIME]


def high_contrast_ink(color: str) -> str:
    return "#000000" if color == SLIME_GREEN else "#ffffff"


ZONE_COLORS = {
    Zone.HOME_GOAL: "#3b4859",
    Zone.MIDFIELD: "#46554e",
    Zone.VISITORS_GOAL: "#5b4d46",
}
def zone_labels(board_size: int) -> dict[Zone, str]:
    """
    "HOME ZONE" / "MIDFIELD" / "VISITORS ZONE" on the 7-space board;
    "HOME THIRD" / "MIDFIELD" / "VISITORS THIRD" on the 9-space
    board, the only one where the three areas (H/M/V) are all equal --
    see "The field" in the living rules and the 2026-08-24 entry in the
    rules log. Not the same thing as FONT_GOAL_ZONE below, which labels
    the actual goal beyond the edge of the board, not one of these three.
    """
    outer = "THIRD" if board_size == 9 else "ZONE"
    return {
        Zone.HOME_GOAL: f"HOME {outer}",
        Zone.MIDFIELD: "MIDFIELD",
        Zone.VISITORS_GOAL: f"VISITORS {outer}",
    }
# The H1/M1/V1 space codes written in the corner of every space. Kept
# in step with ZONE_LETTERS in cogs/d12ball_helpers.py, which is where
# the same codes are built for button labels and prompts.
ZONE_CODES = {
    Zone.HOME_GOAL: "H",
    Zone.MIDFIELD: "M",
    Zone.VISITORS_GOAL: "V",
}


LOGGER = logging.getLogger(__name__)

# Fonts are bundled rather than looked up by name so that board images render
# identically everywhere. A bare `ImageFont.truetype("DejaVuSans.ttf", size)`
# only searches the host's font directories, and no list of bare names can be
# right on every platform: the same typeface is filed under a different name
# on each. "Arial Bold.ttf" exists on macOS, Windows calls that file
# "arialbd.ttf", and Linux ships neither unless DejaVu is installed. When
# every name misses, Pillow's `load_default()` hands back a built-in face
# pinned to size 10 that ignores the requested size, so every label on the
# board silently collapses to the same tiny text.
FONT_DIR = Path(__file__).resolve().parent / "fonts"


def load_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    bundled = FONT_DIR / (
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    )
    candidates = (
        str(bundled),
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
        "Arial Bold.ttf" if bold else "Arial.ttf",
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue

    LOGGER.warning(
        "No scalable font found for size %d (bold=%s); falling back to "
        "Pillow's built-in face. Expected a bundled font at %s.",
        size,
        bold,
        bundled,
    )
    try:
        # Pillow >= 10.1 can scale the built-in face. Without an explicit
        # size it returns a 10px font no matter what was asked for.
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def load_goal_zone_font(size: int) -> ImageFont.ImageFont:
    """
    Racing Sans One -- an uppercase, slightly slanted display face --
    for the goal zone's own "GOAL" lettering, over the
    bundled-path-first chain `load_font` uses and for the same reason
    (see the fonts note above). Falls back to the bundled DejaVu Bold
    rather than Pillow's built-in face, so a missing Racing Sans One
    file degrades to a plainer bold rather than an unreadable size-10
    face.
    """
    bundled = FONT_DIR / "RacingSansOne-Regular.ttf"
    for candidate in (str(bundled), "RacingSansOne-Regular.ttf"):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue

    LOGGER.warning(
        "No scalable Racing Sans One font found for size %d; falling "
        "back to the bundled DejaVu Bold. Expected a bundled font at %s.",
        size,
        bundled,
    )
    return load_font(size, bold=True)


FONT_TITLE = load_font(50, bold=True)
FONT_HEADING = load_font(40, bold=True)
FONT_BODY = load_font(32)
FONT_SMALL = load_font(19)
FONT_MEEPLE = load_font(27, bold=True)
# The goal zone's own "GOAL" watermark -- see the constants above.
FONT_GOAL_ZONE = load_goal_zone_font(95)
# The coaching image draws the same three zone headings across 1280px
# rather than 2200, and "VISITORS ZONE" at FONT_HEADING overruns a
# two-space zone there. Its own smaller size fits every board.
FONT_COACHING_ZONE = load_font(28, bold=True)
FONT_TOKEN = load_font(19, bold=True)
# The role initials on a meeple, under its species icon -- see
# draw_meeple_group. Smaller than FONT_TOKEN because they share the
# disc with the icon now; the ball's "12" keeps FONT_TOKEN.
FONT_TOKEN_ROLE = load_font(18, bold=True)
# The initials alone, when no species icon shares the disc with them:
# a game not playing species abilities, or an icon that failed to
# load. Sized to fill a 76px disc on their own.
FONT_TOKEN_SOLO = load_font(26, bold=True)
FONT_BADGE_COUNT = load_font(16, bold=True)
FONT_MANEUVER_RANK = load_font(34, bold=True)
FONT_MANEUVER_LEGEND = load_font(22)
FONT_DICE_TOTAL = load_font(28, bold=True)
FONT_DICE_VALUE = load_font(26, bold=True)
# A matchup image's own sizes, rather than the shared FONT_SMALL and
# FONT_DICE_TOTAL it used to borrow. The heading is the one line on it
# nobody needs to read -- it names an image a coach is already looking
# at -- so it is set smaller than the dice totals it was sharing a font
# with, and the room that frees goes to the names, skills and abilities,
# which are what the picture is for. Kept apart from the shared fonts
# because those size the board and the dice, which are not on this
# image at all.
FONT_CHALLENGE_TITLE = load_font(21, bold=True)
FONT_CHALLENGE_BODY = load_font(22)
# The ability is a sentence rather than a line of facts, and it wraps:
# a step under the body keeps it from setting the width on its own.
FONT_CHALLENGE_ABILITY = load_font(20)
# The one line on a matchup image that is a sum rather than a fact
# about a player -- see group_text_lines. A size up from the body.
FONT_CHALLENGE_TOTAL = load_font(26, bold=True)
# The value badge a score attempt draws on a defender's portrait, the
# skill it was halved from underneath it, and the label over a band of
# them -- see CHALLENGE_FULL_COLOR.
FONT_CHALLENGE_BADGE = load_font(20, bold=True)
FONT_CHALLENGE_BADGE_NOTE = load_font(13, bold=True)
FONTS_CHALLENGE_BAND = [load_font(size, bold=True) for size in (15, 14, 13, 12, 11)]
FONT_SCORE = load_font(64, bold=True)
FONT_CARD_STAT = load_font(46, bold=True)
FONT_CARD_ROLE = load_font(46, bold=True)
CARD_NAME_MIN_SIZE = 28
CARD_NAME_MAX_SIZE = 60

# The species icon on the stats row, in CARD_INTERNAL_SIZE units --
# about 18px once the card is scaled down to CARD_SIZE, which is the
# size the condition badges are drawn at and as small as one of these
# reads. See `build_player_card` for why it is ink and not a colour.
CARD_SPECIES_ICON_SIZE = 54
CARD_SPECIES_ICON_INK = "#111111"
_CARD_NAME_FONT_CACHE: dict[int, ImageFont.ImageFont] = {}
# Meeple names are sized per space, not once for the board: see
# fit_meeple_labels.
MEEPLE_LABEL_MIN_SIZE = 14
MEEPLE_LABEL_MAX_SIZE = 27
MEEPLE_LABEL_LINE_GAP = 3
_MEEPLE_LABEL_FONT_CACHE: dict[int, ImageFont.ImageFont] = {}
# A meeple is a disc carrying two facts: the species icon over the role
# initials. It was 56px with the initials alone; the icon is what an
# advanced game is played on, and at Discord's size a mark *added* to a
# 56px disc (a corner badge, a watermark, an icon by the name) is the
# first thing to vanish -- tried, in that order. So the disc grew to
# carry both, and the icon is the larger of the two because the
# initials are also in the name label a coach reads anyway.
#
# **The icon is drawn only when the game plays species abilities**
# (the author, 2026-09-18): in a basic game, or an advanced one that
# opted the module out, species is a name on the card and nothing a
# coach acts on, so the disc carries the initials alone -- at a size
# that fills it, since it is still 76px. Whether to draw it is the
# `species_icons` flag every render entry point takes; the cog answers
# it from `RulesEngine.species_abilities_apply`, and this module never
# reads the game's own bools (see "Species abilities in the bot").
MEEPLE_SIZE = 76
MEEPLE_SPECIES_ICON_SIZE = 38
MEEPLE_SPECIES_ICON_TOP = 7
MEEPLE_ROLE_BOTTOM_INSET = 28
BALL_RADIUS = 27
# Where the two rows of meeples sit on the board. The visiting row's
# names stop above the home row's tokens, and the home row's stop at
# the board's foot, so the room for names is about the same either way
# (54px and 51px). The offsets are the ball token's as well.
VISITING_MEEPLE_TOP = BOARD_TOP + 88
HOME_MEEPLE_TOP = BOARD_BOTTOM - 150

ROLE_INITIALS = {
    "fullback": "FB",
    "defender": "DD",
    "midfielder": "MF",
    "playmaker": "PM",
    "winger": "WG",
    "striker": "SK",
}

EXHAUST_ICON_PATH = (
    Path(__file__).resolve().parent / "images" / "emoji" / "exhaust.png"
)
EXHAUST_ICON_SIZE = 26

# A Cyborg's own token count -- the same triangle, recoloured teal by
# `scripts/recolor_exhaust_token.py` so it reads as one thing with their
# Drained badge rather than an amber count sitting beside a teal
# condition. `draw_card`'s `cyborg` flag picks it the same way it picks
# Drained over Exhausted -- see the comment on that flag below.
EXHAUST_CYBORG_ICON_PATH = (
    Path(__file__).resolve().parent / "images" / "emoji" / "exhaust_cyborg.png"
)
EXHAUST_CYBORG_ICON_SIZE = 26

EXHAUSTED_ICON_PATH = (
    Path(__file__).resolve().parent / "images" / "emoji" / "exhausted.png"
)
EXHAUSTED_ICON_SIZE = 26

INJURED_ICON_PATH = (
    Path(__file__).resolve().parent / "images" / "emoji" / "injured.png"
)
INJURED_ICON_SIZE = 26

# A Cyborg's own Exhausted/Injured badges -- see "Lithium Powered" in
# docs/living-rules.md. Same slot on the card, same rule, different
# word and art; `draw_card`'s `cyborg` flag is what picks between the
# two pairs, and this module never asks a species question itself to
# decide which one -- see the `species_icons` comment above.
DRAINED_ICON_PATH = (
    Path(__file__).resolve().parent / "images" / "emoji" / "drained.png"
)
DRAINED_ICON_SIZE = 26

DAMAGED_ICON_PATH = (
    Path(__file__).resolve().parent / "images" / "emoji" / "damaged.png"
)
DAMAGED_ICON_SIZE = 26

PLAYER_IMAGES_DIR = Path(__file__).resolve().parent / "images" / "player_images"
_PLAYER_PORTRAIT_CACHE: dict[str, Optional[Image.Image]] = {}

# The four species icons, drawn by `scripts/render_species_icons.py`.
# They are one flat ink on transparency rather than coloured art,
# because the same file has to sit on three different grounds -- the
# team-coloured header band of a printed player card, the same band on
# a species reference card, and the white face of the card drawn on the
# board -- and no one colour reads on all three. `species_icon` below
# is what supplies the colour, so nothing else may paste one of these
# straight.
SPECIES_ICON_DIR = Path(__file__).resolve().parent / "images" / "species"
_SPECIES_ICON_CACHE: dict[str, Optional[Image.Image]] = {}
_SPECIES_ICON_TINTS: dict[
    tuple[str, str, Optional[int]], Optional[Image.Image]
] = {}

# Lithium Powered's cell, minus the bolt cut out of the bundled
# `cyborg.png` -- Overdrive's own halo, and the one place the author
# asked to leave the bolt off (2026-09-16): behind a die that already
# wears a ring and a bright glow, the cut-out competed with both rather
# than reading as the species. Drawn fresh rather than a second bundled
# file, since `cyborg_no_bolt.png` would be art nobody but this halo
# ever asks for -- see "The shapes are built out of cubic segments" in
# `scripts/render_species_icons.py`.
CYBORG_CELL_SUPERSAMPLE = 4
_CYBORG_CELL_TINTS: dict[tuple[str, int], Image.Image] = {}

# One cache for the three condition-token icons below, keyed by name.
# A key present means the load was already attempted -- including a
# key mapped to None, for a file that turned out missing -- which is
# what stops a missing icon being retried on every render.
_ICON_CACHE: dict[str, Optional[Image.Image]] = {}


def _load_icon(path: Path, size: int, cache_key: str) -> Optional[Image.Image]:
    """
    Load (and cache) a small condition-token icon, thumbnailed to
    `size`. Returns None -- and caches that -- when the file is missing
    or unreadable, so rendering can gracefully skip it; see "A bundled
    file's name is case-sensitive..." in docs/design/gotchas.md for why this stays
    silent rather than raising.
    """
    if cache_key in _ICON_CACHE:
        return _ICON_CACHE[cache_key]

    try:
        with Image.open(path) as source:
            icon = source.convert("RGBA")
            icon.thumbnail((size, size), Image.Resampling.LANCZOS)
            _ICON_CACHE[cache_key] = icon
    except OSError:
        _ICON_CACHE[cache_key] = None

    return _ICON_CACHE[cache_key]


def load_exhaust_icon() -> Optional[Image.Image]:
    """
    Load (and cache) the exhaustion token icon. Returns None if the image
    is not available so rendering can gracefully skip it.
    """
    return _load_icon(EXHAUST_ICON_PATH, EXHAUST_ICON_SIZE, "exhaust")


def load_exhaust_cyborg_icon() -> Optional[Image.Image]:
    """
    Load (and cache) a Cyborg's own exhaustion token icon. Returns None
    if the image is not available so rendering can gracefully skip it.
    """
    return _load_icon(
        EXHAUST_CYBORG_ICON_PATH, EXHAUST_CYBORG_ICON_SIZE, "exhaust_cyborg"
    )


def load_exhausted_icon() -> Optional[Image.Image]:
    """
    Load (and cache) the exhausted-condition icon. Returns None if the
    image is not available so rendering can gracefully skip it.
    """
    return _load_icon(EXHAUSTED_ICON_PATH, EXHAUSTED_ICON_SIZE, "exhausted")


def load_injured_icon() -> Optional[Image.Image]:
    """
    Load (and cache) the injured-condition icon. Returns None if the
    image is not available so rendering can gracefully skip it.
    """
    return _load_icon(INJURED_ICON_PATH, INJURED_ICON_SIZE, "injured")


def load_drained_icon() -> Optional[Image.Image]:
    """
    Load (and cache) a Cyborg's Drained-condition icon. Returns None if
    the image is not available so rendering can gracefully skip it.
    """
    return _load_icon(DRAINED_ICON_PATH, DRAINED_ICON_SIZE, "drained")


def load_damaged_icon() -> Optional[Image.Image]:
    """
    Load (and cache) a Cyborg's Damaged-condition icon. Returns None if
    the image is not available so rendering can gracefully skip it.
    """
    return _load_icon(DAMAGED_ICON_PATH, DAMAGED_ICON_SIZE, "damaged")


def load_player_portrait(name: str) -> Optional[Image.Image]:
    """
    Load (and cache) a player's portrait. Returns None if the image is
    not available so card rendering can gracefully skip it.
    """
    if name in _PLAYER_PORTRAIT_CACHE:
        return _PLAYER_PORTRAIT_CACHE[name]

    try:
        with Image.open(PLAYER_IMAGES_DIR / f"{name}.png") as source:
            portrait = source.convert("RGBA")
            portrait.load()
    except OSError:
        portrait = None

    _PLAYER_PORTRAIT_CACHE[name] = portrait
    return portrait


def load_species_icon(species: str) -> Optional[Image.Image]:
    """
    Load (and cache) a species' silhouette at the size it was drawn.
    Returns None -- and caches that -- when the file is missing, so a
    render skips the icon rather than failing, exactly as the condition
    tokens and the portraits do; see "A bundled file's name is
    case-sensitive..." in docs/design/gotchas.md for why this stays silent.

    Callers want `species_icon`, which colours it. This is the raw ink
    and is only useful to something about to tint it itself.
    """
    if species in _SPECIES_ICON_CACHE:
        return _SPECIES_ICON_CACHE[species]

    try:
        with Image.open(SPECIES_ICON_DIR / f"{species}.png") as source:
            icon = source.convert("RGBA")
            icon.load()
    except OSError:
        icon = None

    _SPECIES_ICON_CACHE[species] = icon
    return icon


def species_icon(
    species: str, color: str, size: Optional[int] = None
) -> Optional[Image.Image]:
    """
    A species' icon drawn in `color`, `size` pixels across -- or at the
    size it was drawn, when no size is asked for.

    The tint keeps the silhouette's own alpha and replaces everything
    under it, which is the whole reason the art is one flat ink. It is
    resized before it is tinted and the answer is cached per
    (species, colour, size): the board draws up to a dozen cards a
    render, and each of them wants the same few pixels.

    A caller drawing at print resolution asks for no size and lets its
    own pen do the resizing -- `cards.Pen.paste` scales onto the
    supersampled canvas, so handing it something already cut down to
    the card's units would throw away most of the icon.
    """
    key = (species, color, size)
    if key in _SPECIES_ICON_TINTS:
        return _SPECIES_ICON_TINTS[key]

    source = load_species_icon(species)
    if source is None:
        _SPECIES_ICON_TINTS[key] = None
        return None

    shape = (
        source
        if size is None
        else source.resize((size, size), Image.Resampling.LANCZOS)
    )
    tinted = tint_silhouette(shape, color)
    _SPECIES_ICON_TINTS[key] = tinted
    return tinted


def tint_silhouette(shape: Image.Image, color: str) -> Image.Image:
    """
    A flat-ink silhouette repainted in `color`, keeping its own alpha.

    Its own function because it has two callers that must not drift:
    `species_icon` above, and `scripts/render_species_icons.py`, which
    writes the coloured copy of each icon that sits beside the ink one
    on disk. Two implementations of this is how a coloured file comes
    to disagree with what the bot draws.
    """
    tinted = Image.new("RGBA", shape.size, color)
    tinted.putalpha(shape.getchannel("A"))
    return tinted


def cyborg_cell_without_bolt(color: str, size: int) -> Image.Image:
    """
    Lithium Powered's cell in `color`, `size` pixels across, without
    the bolt cut out of it -- see the module-level note by
    `_CYBORG_CELL_TINTS` for why this exists as its own drawing rather
    than a second bundled icon.

    The two rounded rectangles are `draw_cell`'s own, from
    `scripts/render_species_icons.py` -- the terminal and the body,
    with no bolt polygon punched out of the body afterwards. Drawn
    supersampled and resized down for the same reason that script's
    shapes are: Pillow does not antialias what `ImageDraw` draws.
    """
    key = (color, size)
    if key in _CYBORG_CELL_TINTS:
        return _CYBORG_CELL_TINTS[key]

    canvas_size = size * CYBORG_CELL_SUPERSAMPLE
    canvas = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    shape_draw = ImageDraw.Draw(canvas)
    shape_draw.rounded_rectangle(
        (
            0.36 * canvas_size, 0.03 * canvas_size,
            0.64 * canvas_size, 0.16 * canvas_size,
        ),
        radius=0.04 * canvas_size,
        fill=(0, 0, 0, 255),
    )
    shape_draw.rounded_rectangle(
        (
            0.17 * canvas_size, 0.13 * canvas_size,
            0.83 * canvas_size, 0.97 * canvas_size,
        ),
        radius=0.12 * canvas_size,
        fill=(0, 0, 0, 255),
    )
    shape = canvas.resize((size, size), Image.Resampling.LANCZOS)
    tinted = tint_silhouette(shape, color)
    _CYBORG_CELL_TINTS[key] = tinted
    return tinted


PORTRAIT_IMAGE_SIZE = 320


def render_player_portrait(
    player_name: str,
    size: int = PORTRAIT_IMAGE_SIZE,
) -> Optional[BytesIO]:
    """
    A player's portrait on its own, scaled to fit a `size` box, for
    posting beside a message about them. Returns None when the player
    has no portrait, so callers can simply skip the attachment.

    Saved as RGBA rather than flattened onto a background: these images
    are cut out, and a transparent PNG sits on whichever background the
    reader's Discord theme gives it.
    """
    portrait = load_player_portrait(player_name)
    if portrait is None:
        return None

    sized = portrait.copy()
    sized.thumbnail((size, size), Image.Resampling.LANCZOS)

    output = BytesIO()
    sized.save(output, format="PNG")
    output.seek(0)
    return output


def card_name_font(size: int) -> ImageFont.ImageFont:
    font = _CARD_NAME_FONT_CACHE.get(size)
    if font is None:
        font = load_font(size, bold=True)
        _CARD_NAME_FONT_CACHE[size] = font
    return font


def meeple_label_font(size: int) -> ImageFont.ImageFont:
    font = _MEEPLE_LABEL_FONT_CACHE.get(size)
    if font is None:
        font = load_font(size, bold=True)
        _MEEPLE_LABEL_FONT_CACHE[size] = font
    return font


def fit_meeple_labels(
    draw: ImageDraw.ImageDraw,
    labels: list[str],
    max_width: int,
    max_height: int,
) -> tuple[ImageFont.ImageFont, int]:
    """
    The largest label size, and the line height to go with it, that
    fits every name of a group inside its own space: the widest name
    within `max_width`, and one line per name within `max_height`.

    A space can hold a whole zone's worth of meeples -- a formation
    that stacks puts them there, and /coach can put them anywhere --
    so the size a stack needs is not something a constant can know:
    one name gets the full size, four share the room between the
    tokens and the bottom of the space. Falls back to
    the smallest size when even that does not fit; the caller shortens
    a name that is still too wide.
    """
    for size in range(MEEPLE_LABEL_MAX_SIZE, MEEPLE_LABEL_MIN_SIZE - 1, -1):
        font = meeple_label_font(size)
        line_height = size + MEEPLE_LABEL_LINE_GAP
        if len(labels) * line_height > max_height:
            continue
        if any(
            draw.textlength(label, font=font) > max_width
            for label in labels
        ):
            continue
        return font, line_height

    return (
        meeple_label_font(MEEPLE_LABEL_MIN_SIZE),
        MEEPLE_LABEL_MIN_SIZE + MEEPLE_LABEL_LINE_GAP,
    )


def shorten_to_width(
    draw: ImageDraw.ImageDraw,
    label: str,
    font: ImageFont.ImageFont,
    max_width: int,
) -> str:
    """Cut a name down until it fits, keeping a trailing ellipsis."""
    if draw.textlength(label, font=font) <= max_width:
        return label

    shortened = label
    while shortened and draw.textlength(
        f"{shortened}...", font=font,
    ) > max_width:
        shortened = shortened[:-1]
    return f"{shortened}..." if shortened else ""


def fit_card_name(
    draw: ImageDraw.ImageDraw,
    name: str,
    max_width: int,
) -> tuple[ImageFont.ImageFont, tuple[int, int, int, int]]:
    """
    Binary-search the largest bold size in [CARD_NAME_MIN_SIZE,
    CARD_NAME_MAX_SIZE] whose rendered width fits max_width, so each
    card's name is as large as the card allows.
    """
    best_size = CARD_NAME_MIN_SIZE
    low, high = CARD_NAME_MIN_SIZE, CARD_NAME_MAX_SIZE
    while low <= high:
        mid = (low + high) // 2
        width = draw.textlength(name, font=card_name_font(mid))
        if width <= max_width:
            best_size = mid
            low = mid + 1
        else:
            high = mid - 1

    font = card_name_font(best_size)
    return font, draw.textbbox((0, 0), name, font=font)


_PLAYER_CARD_CACHE: dict[tuple[str, int, int], tuple[Image.Image, int, int]] = {}


def rendered_player_card(
    player: PlayerDefinition,
    profile: RoleProfile,
) -> tuple[Image.Image, int, int]:
    """
    Build (and cache) a player's card at CARD_SIZE, along with the
    (top, bottom) of the stats/role row in CARD_SIZE coordinates, so
    badges can be centered on that row. A player's role profile does
    not change mid-process, so the same player+profile always produces
    the same pixels; caching skips re-drawing the name, stats and
    portrait and re-running the LANCZOS downscale on every single board
    render, which otherwise happens for every card on every render
    regardless of whether that player's card has changed.
    """
    key = (player.player_id, profile.offense, profile.defense)
    cached = _PLAYER_CARD_CACHE.get(key)
    if cached is None:
        card, row_top, row_bottom = build_player_card(player, profile)
        cached = (
            card.resize(CARD_SIZE, Image.Resampling.LANCZOS),
            round(row_top / CARD_INTERNAL_SCALE),
            round(row_bottom / CARD_INTERNAL_SCALE),
        )
        _PLAYER_CARD_CACHE[key] = cached
    return cached


def build_player_card(
    player: PlayerDefinition,
    profile: RoleProfile,
) -> tuple[Image.Image, int, int]:
    """
    Compose a player's card at CARD_INTERNAL_SIZE: a white rectangle
    (the surrounding team-colored frame is drawn by the caller) holding
    the offense/defense skills, abbreviated role, and portrait. Callers
    scale the result down to CARD_SIZE, which is why this renders at
    CARD_INTERNAL_SCALE. Also returns the (top, bottom) of the stats/role
    row in CARD_INTERNAL_SIZE coordinates.
    """
    width, height = CARD_INTERNAL_SIZE

    card = Image.new("RGBA", (width, height), "#ffffff")
    draw = ImageDraw.Draw(card)

    name_font, name_bbox = fit_card_name(draw, player.name, width - 16)
    name_width = name_bbox[2] - name_bbox[0]
    name_height = name_bbox[3] - name_bbox[1]
    name_top_pad = 8
    draw.text(
        ((width - name_width) / 2, name_top_pad - name_bbox[1]),
        player.name,
        font=name_font,
        fill="#111111",
    )
    name_zone_height = name_top_pad + name_height + 10

    stats_row_height = 116
    draw.text(
        (12, name_zone_height + 4),
        str(profile.offense),
        font=FONT_CARD_STAT,
        fill=CARD_OFFENSE_COLOR,
    )
    draw.text(
        (12, name_zone_height + 60),
        str(profile.defense),
        font=FONT_CARD_STAT,
        fill=CARD_DEFENSE_COLOR,
    )

    role_label = ROLE_INITIALS[player.role.value]
    role_bbox = draw.textbbox((0, 0), role_label, font=FONT_CARD_ROLE)
    role_width = role_bbox[2] - role_bbox[0]
    role_height = role_bbox[3] - role_bbox[1]

    # The species icon answers the role initials, stacked under them
    # as one centered block -- not beside them. Beside left the icon
    # in the same right-edge column the Exhausted, Injured, Drained
    # and Damaged badges are drawn in afterward (see draw_card), which
    # covered it completely on the widest role labels rather than the
    # partial overlap the layout was judged against: that column is
    # for a badge alone now, whatever a card's own role reads.
    #
    # **It is drawn in ink rather than in a colour**, which is what
    # keeps `rendered_player_card`'s cache key honest: that key is the
    # player and their two skills, and a colour would have to be a
    # third thing in it. The shape is the identity here anyway -- and
    # the Oozes' green on a white card is the one colour that could not
    # be read.
    species_icon_gap = 8
    block_height = role_height + species_icon_gap + CARD_SPECIES_ICON_SIZE
    block_top = name_zone_height + (stats_row_height - block_height) / 2
    draw.text(
        ((width - role_width) / 2, block_top - role_bbox[1]),
        role_label,
        font=FONT_CARD_ROLE,
        fill="#111111",
    )

    icon = species_icon(
        player.species, CARD_SPECIES_ICON_INK, CARD_SPECIES_ICON_SIZE
    )
    if icon is not None:
        card.alpha_composite(
            icon,
            (
                round((width - CARD_SPECIES_ICON_SIZE) / 2),
                round(block_top + role_height + species_icon_gap),
            ),
        )

    portrait_zone_top = name_zone_height + stats_row_height
    portrait = load_player_portrait(player.name)
    if portrait is not None:
        max_portrait_size = (
            width - 20,
            height - portrait_zone_top - 10,
        )
        sized = portrait.copy()
        sized.thumbnail(max_portrait_size, Image.Resampling.LANCZOS)
        portrait_x = (width - sized.width) // 2
        portrait_y = height - 10 - sized.height
        card.alpha_composite(sized, (portrait_x, portrait_y))

    return card, name_zone_height, portrait_zone_top


def player_index(
    catalog: PlayerCatalog,
) -> dict[str, PlayerDefinition]:
    """
    Every card id a match can hold, mapped to the player it draws.

    That is each catalog player under their own id *and* under
    `duplicate_card_id`, because both sides of a match can field the
    same person and the visiting copy carries the suffix -- see "One
    player, both sides" in docs/design/teams-and-players.md. Aliased once here rather than
    resolved at each of this module's `players[...]` lookups: they are
    a plain dict index in a dozen places and the two copies draw the
    same portrait, name, role and skills anyway. What tells them apart
    on the board is the team color, which is read off the match.
    """
    return {
        card_id: (
            player
            if card_id == player.player_id
            else replace(player, player_id=card_id)
        )
        for roster in catalog.teams.values()
        for player in roster.players
        for card_id in (
            player.player_id,
            duplicate_card_id(player.player_id),
        )
    }


def space_code(zone: Zone, space_index: int, board=None) -> str:
    """
    The code drawn in a space's corner -- "H1", or the flat "1" while
    the numbering experiment is on.

    `board` is the `BoardState` a match is being drawn from, or the
    `BoardLayout` alone on the printed sheets, and only the experiment
    reads it: a flat number has to count the spaces in the zones to
    its left, which differ by board size. **Drop the parameter when
    the experiment is reverted** -- see
    `d12ball/space_numbering.py`.
    """
    if FLAT_SPACE_NUMBERING:
        return str(flat_space_number(zone, space_index, board))
    return f"{ZONE_CODES[zone]}{space_index + 1}"


def zone_bounds_between(
    match: MatchState,
    left: int,
    right: int,
) -> dict[Zone, tuple[int, int]]:
    """
    Where each zone starts and ends, given the horizontal span the
    board is drawn across. The coaching image draws the same field
    narrower than the match image does, so the span is a parameter.
    """
    space_width = (right - left) / match.board.layout.board_size
    bounds: dict[Zone, tuple[int, int]] = {}
    cursor = left

    for zone in Zone:
        width = match.board.layout.zone_spaces[zone] * space_width
        zone_right = round(cursor + width)
        bounds[zone] = (round(cursor), zone_right)
        cursor += width

    return bounds


def zone_bounds(match: MatchState) -> dict[Zone, tuple[int, int]]:
    return zone_bounds_between(match, BOARD_LEFT, BOARD_RIGHT)


def draw_card(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    player: PlayerDefinition,
    profile: RoleProfile,
    x: int,
    y: int,
    team: Team,
    exhaustion: int = 0,
    exhausted: bool = False,
    injured: bool = False,
    cyborg: bool = False,
) -> None:
    card, row_top, row_bottom = rendered_player_card(player, profile)

    border = TEAM_COLORS[Team(team)]
    draw.rounded_rectangle(
        (x - 3, y - 3, x + CARD_SIZE[0] + 3, y + CARD_SIZE[1] + 3),
        radius=7,
        fill=border,
    )
    canvas.alpha_composite(card, (x, y))

    if exhaustion > 0:
        draw_exhaustion_badge(
            canvas,
            draw,
            x,
            y,
            exhaustion,
            player,
            profile,
            row_top,
            row_bottom,
            cyborg=cyborg,
        )
    # Injured and Exhausted share the same slot on the stats row: a
    # player who becomes injured loses the Exhausted condition (and
    # every token with it), so the two badges can never be drawn at
    # once. The injured badge used to sit in the card's top-left
    # corner, over the name.
    #
    # `cyborg` only ever changes which icon fills that slot (and, on the
    # exhaustion badge above, which triangle), never whether one is
    # drawn -- Drained and Damaged are Exhausted and Injured under a
    # Cyborg's own words (see "Lithium Powered" in docs/living-rules.md),
    # so the caller who already answered `exhausted`/`injured` off the
    # match answers this off `RulesEngine.has_species_ability` the same
    # way `species_icons` is answered, rather than this module reading
    # the player's own species to decide it.
    if injured:
        if cyborg:
            draw_damaged_badge(canvas, draw, x, y, row_top, row_bottom)
        else:
            draw_injured_badge(canvas, draw, x, y, row_top, row_bottom)
    if exhausted:
        if cyborg:
            draw_drained_badge(canvas, draw, x, y, row_top, row_bottom)
        else:
            draw_exhausted_badge(canvas, draw, x, y, row_top, row_bottom)


def draw_exhaustion_badge(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    card_x: int,
    card_y: int,
    exhaustion: int,
    player: PlayerDefinition,
    profile: RoleProfile,
    row_top: int,
    row_bottom: int,
    cyborg: bool = False,
) -> None:
    """
    Draws the exhaust-token badge between the skill numbers and the role
    acronym, on the same row as the role, rather than over the portrait.
    The gap between those two is narrower than the icon on some cards, so
    the horizontal center is computed per-card (from the actual offense
    digit width and role label width) to keep the overlap as small as
    possible instead of guessing a fixed position.

    `cyborg` only ever changes which icon fills the slot, the same as
    `draw_card`'s own flag -- see the comment there.
    """
    icon = load_exhaust_cyborg_icon() if cyborg else load_exhaust_icon()

    offense_bbox = draw.textbbox(
        (0, 0), str(profile.offense), font=FONT_CARD_STAT
    )
    stats_right = 12 + (offense_bbox[2] - offense_bbox[0])

    role_label = ROLE_INITIALS[player.role.value]
    role_bbox = draw.textbbox((0, 0), role_label, font=FONT_CARD_ROLE)
    role_left = (CARD_INTERNAL_SIZE[0] - (role_bbox[2] - role_bbox[0])) / 2

    gap_center = (stats_right + role_left) / 2 / CARD_INTERNAL_SCALE
    badge_x = round(card_x + gap_center - EXHAUST_ICON_SIZE / 2)
    badge_y = card_y + row_top + (row_bottom - row_top - EXHAUST_ICON_SIZE) // 2

    if icon is not None:
        canvas.alpha_composite(icon, (badge_x, badge_y))
    else:
        draw.ellipse(
            (
                badge_x,
                badge_y,
                badge_x + EXHAUST_ICON_SIZE,
                badge_y + EXHAUST_ICON_SIZE,
            ),
            fill="#5a2d2d",
            outline="#ffffff",
            width=1,
        )

    if exhaustion > 1:
        # The icon sits in a narrow gap between the stats and the role
        # label, with no room to print the count beside it, so the count
        # is a small bubble on the bottom of the icon instead -- the
        # same pattern a notification-count badge uses.
        count_label = str(exhaustion)
        count_bbox = draw.textbbox((0, 0), count_label, font=FONT_BADGE_COUNT)
        count_width = count_bbox[2] - count_bbox[0]
        count_height = count_bbox[3] - count_bbox[1]
        bubble_radius = max(count_width, count_height) / 2 + 2
        bubble_cx = badge_x + EXHAUST_ICON_SIZE / 2
        bubble_cy = badge_y + EXHAUST_ICON_SIZE - 4
        draw.ellipse(
            (
                bubble_cx - bubble_radius,
                bubble_cy - bubble_radius,
                bubble_cx + bubble_radius,
                bubble_cy + bubble_radius,
            ),
            fill="#1a1a1a",
            outline="#e8b923",
            width=1,
        )
        draw.text(
            (
                bubble_cx - count_width / 2 - count_bbox[0],
                bubble_cy - count_height / 2 - count_bbox[1],
            ),
            count_label,
            font=FONT_BADGE_COUNT,
            fill="#ffffff",
        )


def draw_exhausted_badge(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    card_x: int,
    card_y: int,
    row_top: int,
    row_bottom: int,
) -> None:
    icon = load_exhausted_icon()
    badge_x = card_x + CARD_SIZE[0] - EXHAUSTED_ICON_SIZE - 1
    badge_y = card_y + row_top + (row_bottom - row_top - EXHAUSTED_ICON_SIZE) // 2

    if icon is not None:
        canvas.alpha_composite(icon, (badge_x, badge_y))
    else:
        draw.ellipse(
            (
                badge_x,
                badge_y,
                badge_x + EXHAUSTED_ICON_SIZE,
                badge_y + EXHAUSTED_ICON_SIZE,
            ),
            fill="#b3701f",
            outline="#ffffff",
            width=1,
        )


def draw_injured_badge(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    card_x: int,
    card_y: int,
    row_top: int,
    row_bottom: int,
) -> None:
    """
    Drawn in the same slot as the Exhausted badge -- see draw_card for
    why the two can never collide.
    """
    icon = load_injured_icon()
    badge_x = card_x + CARD_SIZE[0] - INJURED_ICON_SIZE - 1
    badge_y = card_y + row_top + (row_bottom - row_top - INJURED_ICON_SIZE) // 2

    if icon is not None:
        canvas.alpha_composite(icon, (badge_x, badge_y))
    else:
        draw.ellipse(
            (
                badge_x,
                badge_y,
                badge_x + INJURED_ICON_SIZE,
                badge_y + INJURED_ICON_SIZE,
            ),
            fill="#8a1f1f",
            outline="#ffffff",
            width=1,
        )


def draw_drained_badge(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    card_x: int,
    card_y: int,
    row_top: int,
    row_bottom: int,
) -> None:
    """
    A Cyborg's Exhausted badge -- same slot as `draw_exhausted_badge`,
    which `draw_card`'s `cyborg` flag picks between.
    """
    icon = load_drained_icon()
    badge_x = card_x + CARD_SIZE[0] - DRAINED_ICON_SIZE - 1
    badge_y = card_y + row_top + (row_bottom - row_top - DRAINED_ICON_SIZE) // 2

    if icon is not None:
        canvas.alpha_composite(icon, (badge_x, badge_y))
    else:
        draw.ellipse(
            (
                badge_x,
                badge_y,
                badge_x + DRAINED_ICON_SIZE,
                badge_y + DRAINED_ICON_SIZE,
            ),
            fill="#0e5c5c",
            outline="#ffffff",
            width=1,
        )


def draw_damaged_badge(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    card_x: int,
    card_y: int,
    row_top: int,
    row_bottom: int,
) -> None:
    """
    A Cyborg's Injured badge -- same slot as `draw_injured_badge`,
    which `draw_card`'s `cyborg` flag picks between.
    """
    icon = load_damaged_icon()
    badge_x = card_x + CARD_SIZE[0] - DAMAGED_ICON_SIZE - 1
    badge_y = card_y + row_top + (row_bottom - row_top - DAMAGED_ICON_SIZE) // 2

    if icon is not None:
        canvas.alpha_composite(icon, (badge_x, badge_y))
    else:
        draw.ellipse(
            (
                badge_x,
                badge_y,
                badge_x + DAMAGED_ICON_SIZE,
                badge_y + DAMAGED_ICON_SIZE,
            ),
            fill="#8a5a1f",
            outline="#ffffff",
            width=1,
        )


def draw_assignment_cards(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    setup: TeamSetup,
    players: dict[str, PlayerDefinition],
    catalog: PlayerCatalog,
    bounds: dict[Zone, tuple[int, int]],
    y: int,
    exhaustion: dict[str, int],
    exhausted: set[str] = frozenset(),
    injured: set[str] = frozenset(),
    gap: int = 12,
    cyborg_ids: frozenset[str] = frozenset(),
) -> None:
    for zone in Zone:
        left, right = bounds[zone]
        player_ids = setup.zones[zone]
        total_width = len(player_ids) * CARD_SIZE[0] + (
            len(player_ids) - 1
        ) * gap
        x = left + (right - left - total_width) // 2

        for player_id in player_ids:
            player = players[player_id]
            draw_card(
                canvas,
                draw,
                player,
                catalog.effective_profile(player),
                x,
                y,
                team=setup.team,
                exhaustion=exhaustion.get(player_id, 0),
                exhausted=player_id in exhausted,
                injured=player_id in injured,
                cyborg=player_id in cyborg_ids,
            )
            x += CARD_SIZE[0] + gap


def draw_zone_frame(
    draw: ImageDraw.ImageDraw,
    zone: Zone,
    left: float,
    right: float,
    label: str,
) -> None:
    """A zone's tinted panel, and its name across the top of it."""
    draw.rectangle(
        (left, BOARD_TOP, right, BOARD_BOTTOM),
        fill=ZONE_COLORS[zone],
        outline="#d7dde5",
        width=3,
    )
    label_width = draw.textlength(label, font=FONT_HEADING)
    draw.text(
        (
            left + (right - left - label_width) / 2,
            BOARD_TOP + 14,
        ),
        label,
        font=FONT_HEADING,
        fill="#ffffff",
    )


def draw_space(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    match: MatchState,
    players: dict[str, PlayerDefinition],
    zone: Zone,
    space_index: int,
    occupants: list[str],
    space_left: int,
    space_right: int,
    species_icons: bool = False,
) -> None:
    """
    One space: its frame and code, the visiting side's meeples on the
    upper row and the home side's on the lower, and the ball if it is
    here -- hung off the possessing side's group, or centred when they
    have nobody on it (see `ball_token_x`).
    """
    draw.rectangle(
        (
            space_left + 8,
            BOARD_TOP + 58,
            space_right - 8,
            BOARD_BOTTOM - 12,
        ),
        outline="#9aabbc",
        width=2,
    )
    draw.text(
        (space_left + 15, BOARD_TOP + 66),
        space_code(zone, space_index, match.board),
        font=FONT_SMALL,
        fill="#c8d1dc",
    )

    visiting_occupants = [
        player_id
        for player_id in occupants
        if player_id in match.visiting.field_players
    ]
    home_occupants = [
        player_id
        for player_id in occupants
        if player_id in match.home.field_players
    ]
    ball_is_here = (
        match.ball.zone == zone
        and match.ball.space_index == space_index
    )
    visiting_bounds = draw_meeple_group(
        canvas,
        draw,
        visiting_occupants,
        players,
        match.visiting.team,
        space_left,
        space_right,
        VISITING_MEEPLE_TOP,
        alignment="right",
        reserve_ball=(
            ball_is_here
            and match.ball.possession.value == "visiting"
        ),
        # Stop above the home side's own tokens.
        label_bottom=HOME_MEEPLE_TOP - 5,
        species_icons=species_icons,
    )
    home_bounds = draw_meeple_group(
        canvas,
        draw,
        home_occupants,
        players,
        match.home.team,
        space_left,
        space_right,
        HOME_MEEPLE_TOP,
        alignment="left",
        reserve_ball=(
            ball_is_here
            and match.ball.possession.value == "home"
        ),
        label_bottom=BOARD_BOTTOM - 16,
        species_icons=species_icons,
    )

    if ball_is_here:
        home_has_it = match.ball.possession.value == "home"
        ball_x = ball_token_x(
            space_left,
            space_right,
            home_bounds if home_has_it else visiting_bounds,
            carrying_side_present=bool(
                home_occupants if home_has_it else visiting_occupants
            ),
            home_side=home_has_it,
        )
        ball_y = (
            HOME_MEEPLE_TOP + MEEPLE_SIZE // 2
            if home_has_it
            else VISITING_MEEPLE_TOP + MEEPLE_SIZE // 2
        )
        draw_d12_polygon(
            draw,
            ball_x,
            ball_y,
            BALL_RADIUS,
            "#ffffff",
            str(match.ball.speed),
            font=FONT_SMALL,
            outline="#243347",
            text_color="#243347",
        )


def draw_board(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    match: MatchState,
    players: dict[str, PlayerDefinition],
    species_icons: bool = False,
) -> dict[Zone, tuple[int, int]]:
    bounds = zone_bounds(match)
    draw.rounded_rectangle(
        (BOARD_LEFT, BOARD_TOP, BOARD_RIGHT, BOARD_BOTTOM),
        radius=18,
        fill="#14202b",
        outline="#d7dde5",
        width=4,
    )

    labels = zone_labels(match.board.layout.board_size)
    for zone in Zone:
        left, right = bounds[zone]
        draw_zone_frame(draw, zone, left, right, labels[zone])

        spaces = match.board.spaces[zone]
        space_width = (right - left) / len(spaces)
        for space_index, occupants in enumerate(spaces):
            space_left = round(left + space_index * space_width)
            space_right = round(left + (space_index + 1) * space_width)
            draw_space(
                canvas, draw, match, players, zone, space_index, occupants,
                space_left, space_right, species_icons=species_icons,
            )

    draw_end_zone(
        canvas,
        draw,
        match.home.team,
        BOARD_LEFT - GOAL_ZONE_GAP - GOAL_ZONE_WIDTH,
        BOARD_LEFT - GOAL_ZONE_GAP,
    )
    draw_end_zone(
        canvas,
        draw,
        match.visiting.team,
        BOARD_RIGHT + GOAL_ZONE_GAP,
        BOARD_RIGHT + GOAL_ZONE_GAP + GOAL_ZONE_WIDTH,
        angle=270,
    )
    draw_shooting_range_band(
        draw, match, BOARD_LEFT, BOARD_RIGHT, RANGE_BAND_TOP, RANGE_BAND_BOTTOM,
    )
    return bounds


def draw_end_zone(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    team: Team,
    left: int,
    right: int,
    top: int = BOARD_TOP,
    bottom: int = BOARD_BOTTOM,
    angle: int = 90,
) -> None:
    """
    A goal zone of its own, American-football style, beyond H1 or
    beyond the board's last V space rather than squeezed into either
    one's own space -- see "Formations and occupancy" in
    docs/design/formations-and-occupancy.md for why H1 and the last V
    space are already full at kickoff. "GOAL"
    runs the zone's length in the defending team's color -- rotated
    90°, the way an end zone's lettering reads sideways on a field
    running left to right -- with a blank d12 stamped over it, the way
    a field carries a logo at midfield. `team` is the side that
    defends this zone: the home team to the left of H1, the visitors
    to the right of the board's last V space.

    `angle` is 90 or 270 -- the visitors' end zone is drawn at 270 (the
    author's call), turned a further 180° from the home end zone's, the
    way a real field's two end zones face opposite ways rather than
    both reading the same direction at each end.
    """
    assert angle in (90, 270)
    draw.rectangle(
        (left, top, right, bottom),
        fill=GOAL_ZONE_FILL,
        outline="#d7dde5",
        width=3,
    )

    color = TEAM_COLORS[Team(team)]
    word = "GOAL"
    # A dark outline around each letter for a bolder, more "sports
    # poster" look, on the same bundled bold face rather than a new
    # font asset -- see "Fonts" in docs/design/board-image.md for why a face is loaded
    # from the bundle rather than by name.
    stroke_width = 4
    stroke_color = "#14202b"

    word_bbox = draw.textbbox((0, 0), word, font=FONT_GOAL_ZONE)
    cell_height = word_bbox[3] - word_bbox[1]
    pad = 8 + stroke_width
    widths = [draw.textlength(ch, font=FONT_GOAL_ZONE) for ch in word]
    spacing = GOAL_ZONE_LETTER_SPACING
    total_width = sum(widths) + spacing * (len(word) - 1)

    text_layer = Image.new(
        "RGBA",
        (round(total_width) + pad * 2, round(cell_height) + pad * 2),
        (0, 0, 0, 0),
    )
    text_draw = ImageDraw.Draw(text_layer)

    # The "O" is left undrawn -- the d12 stands in its place instead of
    # floating near the word -- and its slot is remembered so the ball
    # can be centered exactly there, and sized to it, once the word is
    # rotated. Letters are spaced apart (`spacing`, on top of the
    # font's own advance) so a four-letter word reads as something
    # that fills the zone rather than a small cluster inside it.
    o_slot: tuple[float, float] | None = None
    x = float(pad)
    for index, (ch, width) in enumerate(zip(word, widths)):
        if ch == "O":
            o_slot = (x, x + width)
        else:
            text_draw.text(
                (x, pad - word_bbox[1]),
                ch,
                font=FONT_GOAL_ZONE,
                fill=color,
                stroke_width=stroke_width,
                stroke_fill=stroke_color,
            )
        x += width
        if index < len(word) - 1:
            x += spacing
    assert o_slot is not None

    rotated = text_layer.rotate(angle, expand=True)
    paste_x = round(left + (right - left - rotated.width) / 2)
    paste_y = round(top + (bottom - top - rotated.height) / 2)
    canvas.paste(rotated, (paste_x, paste_y), rotated)

    # Where the "O" would have sat, in canvas coordinates. rotate(90)
    # maps an unrotated point (x, y) to (y, layer_width - x); rotate(270)
    # maps it to (layer_height - y, x) -- verified empirically, not
    # derived, since a sign error here is silent (the ball just lands
    # a bit off) rather than loud. Either way the slot's full-height
    # y-range becomes the rotated block's full width (the ball sits
    # centered across its thickness, like every letter), and its
    # x-range becomes a y-band within the block -- reversed at 90,
    # direct at 270.
    ball_center_x = paste_x + rotated.width / 2
    if angle == 90:
        ball_center_y = paste_y + text_layer.width - sum(o_slot) / 2
    else:
        ball_center_y = paste_y + sum(o_slot) / 2

    # Sized to the "O" it replaces, not a fixed constant -- at least as
    # tall as the other letters and at least as wide as the "O"'s own
    # slot, so it reads as a letter in the word rather than a smaller
    # badge dropped onto it.
    ball_radius = round(max(cell_height, o_slot[1] - o_slot[0]) / 2)

    # Its own transparent layer, not the shared `draw` -- the fill has
    # to carry an alpha channel so the lettering behind it still shows
    # through, and painting straight onto `canvas` only ever
    # overwrites a pixel, never blends one.
    ball_span = ball_radius * 2 + GOAL_ZONE_BALL_PAD * 2
    ball_layer = Image.new("RGBA", (ball_span, ball_span), (0, 0, 0, 0))
    ball_draw = ImageDraw.Draw(ball_layer)
    ball_center = ball_span / 2
    ball_draw.polygon(
        polygon_points(ball_center, ball_center, ball_radius, 12),
        fill=GOAL_ZONE_BALL_COLOR,
        outline=GOAL_ZONE_BALL_OUTLINE,
        width=3,
    )
    # "12" rotated the same angle as the lettering, so it reads in the
    # same orientation as the word rather than sideways against it.
    label_bbox = ball_draw.textbbox((0, 0), "12", font=FONT_TOKEN)
    label_width = label_bbox[2] - label_bbox[0]
    label_height = label_bbox[3] - label_bbox[1]
    label_layer = Image.new(
        "RGBA", (round(label_width) + 4, round(label_height) + 4), (0, 0, 0, 0)
    )
    ImageDraw.Draw(label_layer).text(
        (2 - label_bbox[0], 2 - label_bbox[1]),
        "12",
        font=FONT_TOKEN,
        fill=GOAL_ZONE_BALL_OUTLINE,
    )
    rotated_label = label_layer.rotate(angle, expand=True)
    ball_layer.paste(
        rotated_label,
        (
            round(ball_center - rotated_label.width / 2),
            round(ball_center - rotated_label.height / 2),
        ),
        rotated_label,
    )
    ball_x = round(ball_center_x - ball_center)
    ball_y = round(ball_center_y - ball_center)
    canvas.paste(ball_layer, (ball_x, ball_y), ball_layer)


def fit_range_label_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: float,
) -> ImageFont.ImageFont:
    """
    The largest range-label size (down to a floor) that fits a band no
    wider than one space -- the "neither" band on the coaching image,
    which is a third the match image's width and cannot carry
    `FONT_RANGE_LABEL` at its usual size.
    """
    size = 15
    while size > 9:
        font = load_font(size, bold=True)
        if draw.textlength(text, font=font) <= max_width:
            return font
        size -= 1
    return load_font(9, bold=True)


def shooting_range_bands(match: MatchState) -> list[tuple[int, int, int]]:
    """
    The board's spaces cut into runs that share a shooting range side:
    `(side, first_index, last_index)`, left to right -- 1 for home,
    -1 for the visitors, 0 for the space in neither's, which only ever
    exists on an odd-sized board (see "Field, direction, and shooting
    range" in the living rules). The same reading `boards.py`'s printed
    bracket makes off `is_in_shooting_range`, so the two brackets
    cannot disagree about where the line falls.
    """
    def range_side(index: int) -> int:
        if match.board.is_in_shooting_range(TeamSide.HOME, index):
            return 1
        if match.board.is_in_shooting_range(TeamSide.VISITING, index):
            return -1
        return 0

    bands: list[tuple[int, int, int]] = []
    for index in range(match.board.layout.board_size):
        side = range_side(index)
        if bands and bands[-1][0] == side:
            bands[-1] = (side, bands[-1][1], index)
        else:
            bands.append((side, index, index))
    return bands


def draw_dashed_rect_outline(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    fill: str,
    width: int = 2,
) -> None:
    left, top, right, bottom = box
    for x1, y1, x2, y2 in (
        (left, top, right, top),
        (right, top, right, bottom),
        (right, bottom, left, bottom),
        (left, bottom, left, top),
    ):
        draw_dashed_line(draw, x1, y1, x2, y2, fill, width, 8, 6)


def draw_shooting_range_band(
    draw: ImageDraw.ImageDraw,
    match: MatchState,
    left: int,
    right: int,
    top: int,
    bottom: int,
) -> None:
    """
    A labelled bracket under the field, one per run of
    `shooting_range_bands` -- what decides whether a team may shoot
    from here, replacing a dashed line drawn straight through the
    spaces themselves that said nothing about what it meant. The same
    marking as the printed field board's own bracket (`boards.py`,
    `draw_shooting_ranges`), so a coach reading either reads the same
    rule.
    """
    space_width = (right - left) / match.board.layout.board_size
    outer = zone_labels(match.board.layout.board_size)
    labels = {
        1: f"{outer[Zone.HOME_GOAL]} - SHOOTING RANGE",
        -1: f"{outer[Zone.VISITORS_GOAL]} - SHOOTING RANGE",
    }

    for side, first, last in shooting_range_bands(match):
        band_left = round(left + first * space_width) + 4
        band_right = round(left + (last + 1) * space_width) - 4
        box = (band_left, top, band_right, bottom)
        if side == 0:
            # No label -- a space in neither range says so by not
            # being bracketed into either one, and "neither's range"
            # was a name for an absence rather than a fact worth
            # stating.
            draw_dashed_rect_outline(draw, box, fill="#5d6b78", width=2)
            continue
        draw.rounded_rectangle(
            box,
            radius=6,
            fill="#1a2836",
            outline="#9aabbc",
            width=2,
        )
        label = labels[side]
        font = fit_range_label_font(draw, label, band_right - band_left - 12)
        draw_centered_text(
            draw,
            (band_left + band_right) / 2,
            (top + bottom) / 2 - 8,
            label,
            font,
            "#e7edf3",
        )


def ball_token_x(
    space_left: int,
    space_right: int,
    group_bounds: tuple[int, int],
    carrying_side_present: bool,
    home_side: bool,
) -> int:
    """
    Where the ball token sits on its space, horizontally.

    Normally it is tucked against the possessing side's meeples, on the
    open side of the row -- the home side reads left to right and the
    visitors right to left, so the ball is on the right of one group
    and the left of the other, and stays next to whoever is holding it
    however many of them are on the space.

    **A space with none of that side's meeples on it centres the
    ball.** An empty group reports the whole space as its bounds, so
    anchoring to its edge draws the ball a radius *outside* the space,
    on top of the next space's tokens or off the board -- which meant a
    loose ball, the one position whose whole question is where the ball
    is lying, was the one thing the board did not show. Centred,
    it is unmistakably in the space it is in, and there are no meeples
    of that side there for it to collide with.
    """
    if not carrying_side_present:
        return (space_left + space_right) // 2
    if home_side:
        return group_bounds[1] + BALL_RADIUS + 3
    return group_bounds[0] - BALL_RADIUS - 3


def draw_meeple_group(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    occupants: list[str],
    players: dict[str, PlayerDefinition],
    team: Team,
    space_left: int,
    space_right: int,
    token_y: int,
    alignment: str,
    reserve_ball: bool,
    label_bottom: int,
    species_icons: bool = False,
) -> tuple[int, int]:
    """
    One team's meeples on one space: a row of tokens, with their names
    listed under them, one per line.

    **A token is the species icon over the role initials.** The icon is
    the bigger of the two and sits in the top of the disc, in the same
    ink as the initials and the outline -- a species colour would be
    the team's own (see "Team colors" in docs/design/teams-and-players.md), so the shape is
    the whole signal, and the four silhouettes were drawn to survive
    18px for exactly this. `canvas` is what the icon is composited
    onto; everything else here is drawn with `draw`. `species_icons`
    is whether the game plays species abilities at all -- off, the
    disc carries the initials alone (see MEEPLE_SIZE). A species whose
    icon is missing falls back to the initials alone, centred, which is
    the token as it was before the icon -- the loader is silent on
    purpose (see load_species_icon).

    `label_bottom` is the lowest y the names may reach -- the bottom of
    the space for the home side, the top of the home side's tokens for
    the visiting one. Names are sized to fit that and the space's own
    width (fit_meeple_labels), because a formation can put a whole
    zone's players on one space and a size that suits one name is
    unreadable spread over four.
    """
    if not occupants:
        return space_left, space_right

    token_size = MEEPLE_SIZE
    gap = 3
    total_width = len(occupants) * token_size + (
        len(occupants) - 1
    ) * gap
    edge_margin = 2 if reserve_ball else 12
    if alignment == "left":
        token_x = space_left + edge_margin
    else:
        token_x = (
            space_right
            - edge_margin
            - total_width
        )
    group_left = token_x

    label_top = token_y + token_size + 7
    # Keep names inside the space's own border, which is drawn 8px in
    # on each side.
    label_left_limit = space_left + 10
    label_right_limit = space_right - 10
    label_width_limit = label_right_limit - label_left_limit
    label_font, line_height = fit_meeple_labels(
        draw,
        [players[player_id].name for player_id in occupants],
        label_width_limit,
        max(label_bottom - label_top, MEEPLE_LABEL_MIN_SIZE),
    )

    color = TEAM_COLORS[Team(team)]
    token_ink = high_contrast_ink(color)
    for player_index, player_id in enumerate(occupants):
        player = players[player_id]
        draw.ellipse(
            (
                token_x,
                token_y,
                token_x + token_size,
                token_y + token_size,
            ),
            fill=color,
            outline=token_ink,
            width=4,
        )
        draw_meeple_face(
            canvas, draw, player, token_x, token_y, token_ink,
            species_icons=species_icons,
        )
        label = shorten_to_width(
            draw, player.name, label_font, label_width_limit,
        )
        label_width = draw.textlength(label, font=label_font)
        label_x = token_x + (token_size - label_width) / 2
        label_x = max(label_left_limit, label_x)
        label_x = min(label_right_limit - label_width, label_x)
        draw.text(
            (
                label_x,
                label_top + player_index * line_height,
            ),
            label,
            font=label_font,
            fill="#ffffff",
        )
        token_x += token_size + gap

    return group_left, group_left + total_width


def draw_meeple_face(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    player: PlayerDefinition,
    token_x: int,
    token_y: int,
    ink: str,
    species_icons: bool,
) -> None:
    """
    What is written on a meeple: the species icon over the role
    initials, both in `ink`, when `species_icons` is set -- and the
    initials alone, centred and larger, when it is not. See
    draw_meeple_group for why the disc carries both and why the icon
    is the larger, and the note by MEEPLE_SIZE for who decides the
    flag.
    """
    initials = ROLE_INITIALS[player.role.value]
    icon = (
        species_icon(player.species, ink, MEEPLE_SPECIES_ICON_SIZE)
        if species_icons
        else None
    )
    if icon is None:
        # Nothing shares the disc with the initials: a game not playing
        # species abilities, or an icon that failed to load. Either way
        # the initials take the whole face.
        initials_width = draw.textlength(initials, font=FONT_TOKEN_SOLO)
        bbox = draw.textbbox((0, 0), initials, font=FONT_TOKEN_SOLO)
        draw.text(
            (
                token_x + (MEEPLE_SIZE - initials_width) / 2,
                token_y + (MEEPLE_SIZE - (bbox[3] - bbox[1])) / 2 - bbox[1],
            ),
            initials,
            font=FONT_TOKEN_SOLO,
            fill=ink,
        )
        return

    canvas.alpha_composite(
        icon,
        (
            token_x + (MEEPLE_SIZE - MEEPLE_SPECIES_ICON_SIZE) // 2,
            token_y + MEEPLE_SPECIES_ICON_TOP,
        ),
    )
    initials_width = draw.textlength(initials, font=FONT_TOKEN_ROLE)
    draw.text(
        (
            token_x + (MEEPLE_SIZE - initials_width) / 2,
            token_y + MEEPLE_SIZE - MEEPLE_ROLE_BOTTOM_INSET,
        ),
        initials,
        font=FONT_TOKEN_ROLE,
        fill=ink,
    )


def polygon_points(
    center_x: float,
    center_y: float,
    radius: float,
    sides: int,
) -> list[tuple[float, float]]:
    return [
        (
            center_x + radius * cos(-pi / 2 + 2 * pi * index / sides),
            center_y + radius * sin(-pi / 2 + 2 * pi * index / sides),
        )
        for index in range(sides)
    ]


def draw_d12_polygon(
    draw: ImageDraw.ImageDraw,
    center_x: int,
    center_y: int,
    radius: int,
    color: str,
    label: str,
    font: ImageFont.ImageFont = FONT_BODY,
    outline: str = "#ffffff",
    text_color: str = "#ffffff",
) -> None:
    points = polygon_points(center_x, center_y, radius, 12)
    draw.polygon(points, fill=color, outline=outline, width=3)

    bbox = draw.textbbox((0, 0), label, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    draw.text(
        (
            center_x - text_width / 2 - bbox[0],
            center_y - text_height / 2 - bbox[1],
        ),
        label,
        font=font,
        fill=text_color,
    )


def draw_species_die_aura(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    center_x: float,
    center_y: float,
    die_radius: float,
    species: str,
    color: str,
    halo_scale: float,
    halo_alpha: int,
    ring_gap: float,
    ring_width: int,
    draw_ring: bool = True,
    halo_override: Optional[Image.Image] = None,
) -> None:
    """
    The halo-and-ring recipe every species die wears: that species' own
    silhouette drawn faint behind the face, and a ring of the same
    colour around it, so a d12 that is not an ordinary roll is
    recognisable before a word of the message beside it is read.

    Shared by Volatile's ignition, Mind Pull's attempt, Overdrive's
    charge and Merge's contribution -- one drawing, four calls, rather
    than the same two steps written out each time a fifth species
    wants a die of its own. Draws the halo and the ring only; the face
    itself is still `draw_d12_polygon`, called after this so the polygon
    lands on top of the glow rather than under it.

    `draw_ring=False` is the own-goal roll's escape: the kept die there
    already wears its own ring (which of two dice the advantage took),
    and a second ring at almost the same radius would read as one ring
    badly drawn rather than two facts.

    `halo_override` is Overdrive's escape: a caller that has already
    drawn its own halo image (Lithium Powered's cell without the bolt
    cut out of it -- see `cyborg_cell_without_bolt`) hands it over
    pre-sized to `2 * die_radius * halo_scale`, and this composites it
    exactly as it would `species_icon`'s own answer rather than looking
    one up.
    """
    halo_size = round(2 * die_radius * halo_scale)
    halo = (
        halo_override
        if halo_override is not None
        else species_icon(species, color, halo_size)
    )
    if halo is not None:
        faded = halo.copy()
        faded.putalpha(
            faded.getchannel("A").point(lambda level: level * halo_alpha // 255)
        )
        canvas.alpha_composite(
            faded,
            (
                round(center_x - halo_size / 2),
                round(center_y - halo_size / 2),
            ),
        )
    if not draw_ring:
        return
    ring_radius = die_radius + ring_gap
    draw.ellipse(
        (
            center_x - ring_radius,
            center_y - ring_radius,
            center_x + ring_radius,
            center_y + ring_radius,
        ),
        outline=color,
        width=ring_width,
    )


SKILL_TEST_CELL_WIDTH = 230
SKILL_TEST_DIE_RADIUS = 36
SKILL_TEST_CENTER_Y = SKILL_TEST_DIE_RADIUS + 20
SKILL_TEST_LABEL_GAP = 10
SKILL_TEST_DETAIL_LINE_HEIGHT = 22
SKILL_TEST_DETAIL_TOP_GAP = 34
SKILL_TEST_TOTAL_GAP = 10
SKILL_TEST_TOTAL_LINE_HEIGHT = 32
SKILL_TEST_BOTTOM_PADDING = 12

# **Overdrive**: the Cyborgs' own teal, on the same halo-and-ring a
# roll's die already knows how to wear -- brighter and thicker than
# Volatile's, which is explaining a second die nobody watched land;
# this one is celebrating the one die a coach can already see.
# **Close to Volatile's own scale, not identical to it** (the author,
# 2026-09-16) -- a coach who already reads one species' aura reads the
# other, and a smaller one read as an afterthought rather than an
# ability, but the bolt-free cell (see `cyborg_cell_without_bolt`) is a
# plainer shape than a flame and read as slightly too large at
# Volatile's own 2.3. Each image that can carry Overdrive grows its own
# headroom to fit it (`render_skill_test_dice`'s top margin,
# `render_own_goal_dice`'s widened cell) rather than the halo being
# shrunk to whatever already fit -- `render_injury_test_die`'s row
# already grows to fit whatever is biggest in it, so that one needed no
# change at all.
OVERDRIVE_AURA_COLOR = TEAM_COLORS[Team.CYBORGS]
OVERDRIVE_HALO_SCALE = 1.9
OVERDRIVE_HALO_ALPHA = 130
OVERDRIVE_RING_GAP = 6
OVERDRIVE_RING_WIDTH = 5
# Every die Overdrive can reach shares one radius (SKILL_TEST_DIE_RADIUS,
# aliased by the injury test's and the own-goal roll's own radius
# constants), so there is one halo size to reserve room for rather than
# a fresh calculation at each site.
OVERDRIVE_HALO_SIZE = round(2 * SKILL_TEST_DIE_RADIUS * OVERDRIVE_HALO_SCALE)

# **Merge**: the Oozes' own slime green, drawn as a second die beside a
# roller's own -- there is no second roll to show (Merge is a flat
# skill number, not a d12), so the token's face is the bonus itself
# rather than a face 1-12. The portrait beside it is what answers
# "which Ooze", the way a score attempt's wall of defenders names
# itself rather than only totalling. **Volatile's own halo scale**
# (2026-09-16) -- a smaller aura on a smaller die read as decoration
# rather than the same ability shown twice, so the die and the
# portrait both grew to keep the token from swallowing the face beside
# it, and the gap between them grew to keep the glow off the portrait
# rather than bleeding onto it. **Its own constant, not an alias of
# Overdrive's** -- the blob reads fine at Volatile's 2.3 where the
# bolt-free cell does not, and the two auras are sized on their own
# merits even though they happened to start equal.
MERGE_AURA_COLOR = TEAM_COLORS[Team.OOZES]
MERGE_DIE_RADIUS = 24
MERGE_HALO_SCALE = 2.3
MERGE_HALO_ALPHA = 130
MERGE_RING_GAP = 6
MERGE_RING_WIDTH = 4
MERGE_HALO_SIZE = round(2 * MERGE_DIE_RADIUS * MERGE_HALO_SCALE)
MERGE_PORTRAIT_SIZE = 56
# Wide enough that the halo's own edge (MERGE_HALO_SIZE / 2 out from
# the die's centre) lands at or before the portrait's own left edge --
# see the arithmetic in `draw_merge_contributors`.
MERGE_ITEM_GAP = 32
MERGE_NAME_GAP = 4
MERGE_NAME_HEIGHT = 16
MERGE_LABEL_TEXT = "MERGE"
MERGE_LABEL_HEIGHT = 20
MERGE_LABEL_GAP = 6
MERGE_CONTRIBUTOR_SPACING = 8
MERGE_ROW_GAP = 10


def merge_block_height(contributors: list[tuple[str, int]]) -> int:
    """
    The extra height a side's Merge contributors need below its detail
    lines, or 0 when nobody merged -- so an ordinary roll's canvas is
    exactly the size it always was.

    `render_skill_test_dice` takes the max of this across both sides,
    the same alignment `detail_block_height` already uses for the
    detail lines themselves, so the two totals still sit on one line
    even when only one side merged.
    """
    if not contributors:
        return 0
    contributor_row = (
        max(MERGE_HALO_SIZE, MERGE_PORTRAIT_SIZE)
        + MERGE_NAME_GAP + MERGE_NAME_HEIGHT
    )
    return (
        MERGE_LABEL_HEIGHT + MERGE_LABEL_GAP
        + len(contributors) * contributor_row
        + (len(contributors) - 1) * MERGE_CONTRIBUTOR_SPACING
    )


def draw_merge_contributors(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    center_x: float,
    top_y: float,
    contributors: list[tuple[str, int]],
) -> None:
    """
    Merge, drawn rather than only totalled: the word itself once, then
    each contributing Ooze as a small die -- haloed and ringed in slime
    green, the same recipe Volatile's own die wears, showing what they
    added rather than a rolled face -- beside their own portrait, so a
    coach reads who merged and not only how much.
    """
    if not contributors:
        return
    label_width = draw.textlength(MERGE_LABEL_TEXT, font=FONT_SMALL)
    draw.text(
        (center_x - label_width / 2, top_y),
        MERGE_LABEL_TEXT,
        font=FONT_SMALL,
        fill=MERGE_AURA_COLOR,
    )
    row_y = top_y + MERGE_LABEL_HEIGHT + MERGE_LABEL_GAP
    slot_height = max(MERGE_HALO_SIZE, MERGE_PORTRAIT_SIZE)
    item_width = 2 * MERGE_DIE_RADIUS + MERGE_ITEM_GAP + MERGE_PORTRAIT_SIZE

    for name, value in contributors:
        row_center_y = row_y + slot_height / 2
        left = center_x - item_width / 2
        die_center_x = left + MERGE_DIE_RADIUS

        draw_species_die_aura(
            canvas, draw, die_center_x, row_center_y, MERGE_DIE_RADIUS,
            SPECIES_OOZE, MERGE_AURA_COLOR,
            MERGE_HALO_SCALE, MERGE_HALO_ALPHA,
            MERGE_RING_GAP, MERGE_RING_WIDTH,
        )
        draw_d12_polygon(
            draw,
            round(die_center_x),
            round(row_center_y),
            MERGE_DIE_RADIUS,
            MERGE_AURA_COLOR,
            f"+{value}",
            font=FONT_SMALL,
            text_color=high_contrast_ink(MERGE_AURA_COLOR),
        )

        portrait_center_x = (
            left + 2 * MERGE_DIE_RADIUS + MERGE_ITEM_GAP + MERGE_PORTRAIT_SIZE / 2
        )
        portrait = load_player_portrait(name)
        if portrait is not None:
            sized = portrait.copy()
            sized.thumbnail(
                (MERGE_PORTRAIT_SIZE, MERGE_PORTRAIT_SIZE),
                Image.Resampling.LANCZOS,
            )
            canvas.alpha_composite(
                sized,
                (
                    round(portrait_center_x - sized.width / 2),
                    round(row_center_y - sized.height / 2),
                ),
            )
        name_width = draw.textlength(name, font=FONT_SMALL)
        draw.text(
            (
                center_x - name_width / 2,
                row_y + slot_height + MERGE_NAME_GAP,
            ),
            name,
            font=FONT_SMALL,
            fill="#c7ced6",
        )
        row_y += slot_height + MERGE_NAME_GAP + MERGE_NAME_HEIGHT + MERGE_CONTRIBUTOR_SPACING


@dataclass(frozen=True)
class SkillTestRowLayout:
    """
    What every die in the row has to agree on, measured across all of
    them before the canvas exists -- `max_lines`, the tallest Merge
    block and whether anyone is overdriven all come from the whole
    row, not one die, which is what keeps every total on one line even
    when only one side has the longer detail list or the Merge block.
    """

    center_y: float
    total_y: float
    detail_block_height: float
    merge_extra_height: float
    merge_gap: float
    width: int
    height: int

    @classmethod
    def measure(
        cls,
        dice: list[
            tuple[int, str, str, list[str], int, bool, list[tuple[str, int]]]
        ],
    ) -> "SkillTestRowLayout":
        max_lines = max(
            (len(detail) for _, _, _, detail, _, _, _ in dice), default=0,
        )
        detail_block_height = max_lines * SKILL_TEST_DETAIL_LINE_HEIGHT
        merge_extra_height = max(
            (merge_block_height(merge) for _, _, _, _, _, _, merge in dice),
            default=0,
        )
        merge_gap = MERGE_ROW_GAP if merge_extra_height else 0
        # An overdriven die's halo is wider than SKILL_TEST_CENTER_Y's own
        # headroom, so the row is pushed down to give it room -- only when
        # one is actually there, so an ordinary roll's canvas is exactly
        # the size it always was.
        has_overdrive = any(
            overdriven for _, _, _, _, _, overdriven, _ in dice
        )
        top_margin = (
            round(max(0, OVERDRIVE_HALO_SIZE / 2 - SKILL_TEST_CENTER_Y))
            if has_overdrive
            else 0
        )
        center_y = SKILL_TEST_CENTER_Y + top_margin
        total_y = (
            center_y + SKILL_TEST_DIE_RADIUS + SKILL_TEST_DETAIL_TOP_GAP
            + detail_block_height + merge_gap + merge_extra_height
            + SKILL_TEST_TOTAL_GAP
        )
        height = (
            total_y + SKILL_TEST_TOTAL_LINE_HEIGHT + SKILL_TEST_BOTTOM_PADDING
        )
        width = SKILL_TEST_CELL_WIDTH * len(dice)
        return cls(
            center_y=center_y,
            total_y=total_y,
            detail_block_height=detail_block_height,
            merge_extra_height=merge_extra_height,
            merge_gap=merge_gap,
            width=width,
            height=height,
        )


def draw_skill_test_die(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    layout: SkillTestRowLayout,
    index: int,
    value: int,
    color: str,
    label: str,
    detail_lines: list[str],
    total: int,
    overdriven: bool,
    merge: list[tuple[str, int]],
) -> None:
    """
    One die: the polygon (haloed and ringed when `overdriven`), the
    team label, the detail lines, the Merge row when `merge` carries
    contributors, and the total -- every one of them placed off the
    row's own measured `layout` rather than this die's own content, so
    every die in the row lines its total up on the same y.

    `overdriven` supercharges the die with the Cyborgs' own halo and
    ring -- **the actual roll, not a second one**, since Overdrive is a
    flat bonus with nothing of its own to show. `merge` draws the Oozes
    who added to this side below the detail lines, each as its own
    small haloed die beside its own portrait -- **both dice**, the
    roller's own and the Ooze's, on one image, the way the rest of
    this row already reads two dice as one contest.
    """
    center_x = index * SKILL_TEST_CELL_WIDTH + SKILL_TEST_CELL_WIDTH // 2
    center_y = layout.center_y
    if overdriven:
        draw_species_die_aura(
            canvas, draw, center_x, center_y, SKILL_TEST_DIE_RADIUS,
            SPECIES_CYBORG, OVERDRIVE_AURA_COLOR,
            OVERDRIVE_HALO_SCALE, OVERDRIVE_HALO_ALPHA,
            OVERDRIVE_RING_GAP, OVERDRIVE_RING_WIDTH,
            halo_override=cyborg_cell_without_bolt(
                OVERDRIVE_AURA_COLOR, OVERDRIVE_HALO_SIZE,
            ),
        )
    draw_d12_polygon(
        draw,
        center_x,
        center_y,
        SKILL_TEST_DIE_RADIUS,
        color,
        str(value),
        font=FONT_DICE_VALUE,
        text_color=high_contrast_ink(color),
    )
    label_width = draw.textlength(label, font=FONT_SMALL)
    draw.text(
        (
            center_x - label_width / 2,
            center_y + SKILL_TEST_DIE_RADIUS + SKILL_TEST_LABEL_GAP,
        ),
        label,
        font=FONT_SMALL,
        fill="#ffffff",
    )

    detail_y = center_y + SKILL_TEST_DIE_RADIUS + SKILL_TEST_DETAIL_TOP_GAP
    for line in detail_lines:
        line_width = draw.textlength(line, font=FONT_SMALL)
        draw.text(
            (center_x - line_width / 2, detail_y),
            line,
            font=FONT_SMALL,
            fill="#c7ced6",
        )
        detail_y += SKILL_TEST_DETAIL_LINE_HEIGHT

    if merge:
        draw_merge_contributors(
            canvas,
            draw,
            center_x,
            center_y + SKILL_TEST_DIE_RADIUS + SKILL_TEST_DETAIL_TOP_GAP
            + layout.detail_block_height + MERGE_ROW_GAP,
            merge,
        )

    # Aligned on max_lines rather than this entry's own line count,
    # so the totals line up across dice even when one side has more
    # modifiers listed than the other -- and now even when only one
    # side merged.
    total_label = f"= {total}"
    total_width = draw.textlength(total_label, font=FONT_DICE_TOTAL)
    draw.text(
        (center_x - total_width / 2, layout.total_y),
        total_label,
        font=FONT_DICE_TOTAL,
        fill=color,
    )


def render_skill_test_dice(
    dice: list[tuple[int, str, str, list[str], int, bool, list[tuple[str, int]]]],
) -> BytesIO:
    """
    Render one or more d12 results side by side, each annotated with the
    team, the player(s) behind that side of the roll, the skill and
    modifiers that built the total, and the total itself -- used for
    skill tests and score (shooting) attempts, where a bare
    team-colored die isn't enough to show who rolled it, why, or what
    it added up to.

    Each entry is (rolled value, team color, team label, detail lines,
    total, overdriven, merge contributors), where detail lines are
    pre-formatted strings -- player name and role, skill applied, any
    other modifiers -- stacked one per line under the team label, and
    total is the final modified result, drawn large underneath so the
    number that actually decided the roll doesn't require reading the
    accompanying message.
    """
    layout = SkillTestRowLayout.measure(dice)
    canvas = Image.new("RGBA", (layout.width, layout.height), "#111820")
    draw = ImageDraw.Draw(canvas)

    for index, (
        value, color, label, detail_lines, total, overdriven, merge,
    ) in enumerate(dice):
        draw_skill_test_die(
            canvas, draw, layout, index,
            value, color, label, detail_lines, total, overdriven, merge,
        )

    return png_bytes(canvas)


INJURY_TEST_DIE_RADIUS = SKILL_TEST_DIE_RADIUS
INJURY_TEST_TITLE = "INJURY TEST"
INJURY_TEST_TITLE_TOP = 14
INJURY_TEST_ROW_TOP = 58
INJURY_TEST_PORTRAIT_SIZE = 96
INJURY_TEST_LABEL_GAP = 8
INJURY_TEST_LABEL_HEIGHT = 24
INJURY_TEST_COLUMN_GAP = 26
INJURY_TEST_SIDE_PADDING = 22
INJURY_TEST_BOTTOM_PADDING = 14
INJURY_TEST_SAFE_COLOR = "#5ac36a"
INJURY_TEST_INJURED_COLOR = "#e2564b"


@dataclass(frozen=True)
class VerdictRow:
    """
    The three-column row -- a die, the player who rolled it, the
    verdict -- that the injury test, Mind Pull and Volatile all draw,
    measured before the canvas exists so the widths can size it.

    The three images share the row and not their proportions: each
    passes its own radius, portrait size, gaps and paddings, which is
    what keeps Volatile's 168px portrait and spread columns Volatile's
    (see "The ignition die" in docs/design/species-abilities.md) while the arithmetic that
    places a column is written once. Each column is centred on its own
    share of the row, and the labels under the die and the portrait
    share a baseline so the team name and the player's name read as
    one line.
    """

    portrait: Optional[Image.Image]
    die_column: float
    portrait_column: float
    verdict: str
    verdict_bbox: tuple[int, int, int, int]
    row_height: float
    row_left: float
    row_top: float
    column_gap: float
    label_gap: float
    label_height: float

    @property
    def verdict_column(self) -> int:
        return self.verdict_bbox[2] - self.verdict_bbox[0]

    @property
    def label_y(self) -> float:
        return self.row_top + self.row_height - self.label_height

    @property
    def content_center_y(self) -> float:
        return (
            self.row_top
            + (self.row_height - self.label_gap - self.label_height) / 2
        )

    @property
    def die_center_x(self) -> float:
        return self.row_left + self.die_column / 2

    @property
    def portrait_center_x(self) -> float:
        return (
            self.row_left
            + self.die_column
            + self.column_gap
            + self.portrait_column / 2
        )

    @property
    def verdict_center_x(self) -> float:
        return (
            self.row_left
            + self.die_column
            + self.portrait_column
            + self.column_gap * 2
            + self.verdict_column / 2
        )


def thumbnail_portrait(
    player_name: str, size: int,
) -> tuple[Optional[Image.Image], int, int]:
    """
    A player's portrait fit inside `size`, with the width and height
    it came out at -- or the full square and no image when there is no
    art for them, so the column is still reserved.
    """
    portrait = load_player_portrait(player_name)
    if portrait is None:
        return None, size, size
    sized = portrait.copy()
    sized.thumbnail((size, size), Image.Resampling.LANCZOS)
    return sized, sized.width, sized.height


def measure_verdict_columns(
    measure: ImageDraw.ImageDraw,
    die_extents: list[float],
    die_labels: list[str],
    player_name: str,
    portrait_size: int,
    verdict: str,
    label_gap: float,
    label_height: float,
) -> tuple[Optional[Image.Image], float, float, tuple[int, int, int, int], float]:
    """
    The three column widths and the row's height, from what each
    column has to hold. `die_extents` is whatever is drawn around the
    die -- the halo is wider than the die whenever a species aura is
    on it, so it, not the bare polygon, is what the die column and the
    row have to hold.
    """
    portrait, portrait_width, portrait_height = thumbnail_portrait(
        player_name, portrait_size,
    )
    die_column = max(
        *die_extents,
        *(measure.textlength(label, font=FONT_SMALL) for label in die_labels),
    )
    portrait_column = max(
        portrait_width,
        measure.textlength(player_name, font=FONT_SMALL),
    )
    verdict_bbox = measure.textbbox((0, 0), verdict, font=FONT_DICE_TOTAL)
    row_height = max(*die_extents, portrait_height) + label_gap + label_height
    return portrait, die_column, portrait_column, verdict_bbox, row_height


def draw_title_across(
    draw: ImageDraw.ImageDraw,
    width: int,
    y: float,
    text: str,
    font: ImageFont.ImageFont,
    fill: str,
) -> None:
    """A line centred across the whole image."""
    text_width = draw.textlength(text, font=font)
    draw.text(((width - text_width) / 2, y), text, font=font, fill=fill)


def draw_verdict_die(
    draw: ImageDraw.ImageDraw,
    row: VerdictRow,
    radius: int,
    color: str,
    value: int,
    labels: list[tuple[str, str]],
) -> None:
    """
    The face, and the lines under it -- the team first, and any second
    line the image explains itself with (Mind Pull's target band,
    Volatile's trigger) on the line below.
    """
    draw_d12_polygon(
        draw,
        round(row.die_center_x),
        round(row.content_center_y),
        radius,
        color,
        str(value),
        font=FONT_DICE_VALUE,
        text_color=high_contrast_ink(color),
    )
    y = row.label_y
    for text, fill in labels:
        draw_centered_text(draw, row.die_center_x, y, text, FONT_SMALL, fill)
        y += 22


def draw_verdict_portrait(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    row: VerdictRow,
    player_name: str,
) -> None:
    if row.portrait is not None:
        canvas.alpha_composite(
            row.portrait,
            (
                round(row.portrait_center_x - row.portrait.width / 2),
                round(row.content_center_y - row.portrait.height / 2),
            ),
        )
    draw_centered_text(
        draw, row.portrait_center_x, row.label_y, player_name, FONT_SMALL, "#ffffff",
    )


def draw_verdict_text(
    draw: ImageDraw.ImageDraw, row: VerdictRow, color: str,
) -> None:
    """The verdict, centred on its column by its ink box rather than its advance."""
    bbox = row.verdict_bbox
    draw.text(
        (
            row.verdict_center_x - row.verdict_column / 2 - bbox[0],
            row.content_center_y - (bbox[3] - bbox[1]) / 2 - bbox[1],
        ),
        row.verdict,
        font=FONT_DICE_TOTAL,
        fill=color,
    )


def render_injury_test_die(
    value: int,
    color: str,
    team_label: str,
    player_name: str,
    safe: bool,
    overdriven: bool = False,
    injured_word: str = "injured",
    title: str = INJURY_TEST_TITLE,
) -> BytesIO:
    """
    Render an injury test as one small d12 -- the same size as a skill
    test's dice rather than the outsized single die render_dice_row
    draws -- beside the portrait and name of the player taking it, and
    the verdict it produced.

    The roll on its own says nothing: the number only means something
    against the token count of a specific player, and "Teal" alone
    doesn't name them. Everything needed to read the result is in the
    image, which is what makes it worth posting as one.

    `overdriven` is "any d12 the Cyborg themselves rolls" reaching an
    injury check -- the same supercharged halo-and-ring
    `render_skill_test_dice` wears on the die it was spent on.

    `injured_word` is the caller's answer to what a failed check makes
    this player -- "damaged" for a Cyborg -- so the verdict is theirs
    and never decided here; `title` is the same for what the check is
    called -- "DAMAGE TEST" for a Cyborg.
    """
    verdict = "SAFE" if safe else injured_word.upper()
    verdict_color = (
        INJURY_TEST_SAFE_COLOR if safe else INJURY_TEST_INJURED_COLOR
    )
    # Measured on a throwaway canvas: the real one can't be created
    # until these widths have decided how big it needs to be.
    measure = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    overdrive_halo_size = (
        round(2 * INJURY_TEST_DIE_RADIUS * OVERDRIVE_HALO_SCALE)
        if overdriven
        else 0
    )
    portrait, die_column, portrait_column, verdict_bbox, row_height = (
        measure_verdict_columns(
            measure,
            [2 * INJURY_TEST_DIE_RADIUS, overdrive_halo_size],
            [team_label],
            player_name,
            INJURY_TEST_PORTRAIT_SIZE,
            verdict,
            INJURY_TEST_LABEL_GAP,
            INJURY_TEST_LABEL_HEIGHT,
        )
    )
    row = VerdictRow(
        portrait, die_column, portrait_column, verdict, verdict_bbox, row_height,
        row_left=INJURY_TEST_SIDE_PADDING,
        row_top=INJURY_TEST_ROW_TOP,
        column_gap=INJURY_TEST_COLUMN_GAP,
        label_gap=INJURY_TEST_LABEL_GAP,
        label_height=INJURY_TEST_LABEL_HEIGHT,
    )
    width = round(
        INJURY_TEST_SIDE_PADDING * 2
        + die_column
        + portrait_column
        + row.verdict_column
        + INJURY_TEST_COLUMN_GAP * 2
    )
    height = INJURY_TEST_ROW_TOP + row_height + INJURY_TEST_BOTTOM_PADDING
    canvas = Image.new("RGBA", (width, height), "#111820")
    draw = ImageDraw.Draw(canvas)

    draw_title_across(
        draw, width, INJURY_TEST_TITLE_TOP, title,
        FONT_DICE_TOTAL, "#ffffff",
    )
    if overdriven:
        draw_species_die_aura(
            canvas, draw, row.die_center_x, row.content_center_y,
            INJURY_TEST_DIE_RADIUS,
            SPECIES_CYBORG, OVERDRIVE_AURA_COLOR,
            OVERDRIVE_HALO_SCALE, OVERDRIVE_HALO_ALPHA,
            OVERDRIVE_RING_GAP, OVERDRIVE_RING_WIDTH,
            halo_override=cyborg_cell_without_bolt(
                OVERDRIVE_AURA_COLOR, OVERDRIVE_HALO_SIZE,
            ),
        )
    draw_verdict_die(
        draw, row, INJURY_TEST_DIE_RADIUS, color, value,
        [(team_label, "#c7ced6")],
    )
    draw_verdict_portrait(canvas, draw, row, player_name)
    draw_verdict_text(draw, row, verdict_color)
    return png_bytes(canvas)


MIND_PULL_DIE_RADIUS = SKILL_TEST_DIE_RADIUS
MIND_PULL_TITLE = "MIND PULL"
MIND_PULL_TITLE_TOP = 14
MIND_PULL_ROW_TOP = 58
# The same 168 Volatile's own portrait is drawn at (the author,
# 2026-09-16) -- a coach reading the two side by side should not have
# to wonder why one Telekinetic's face is smaller than one Fire
# Demon's. Volatile earned that size by needing the width its
# explainer line forces anyway; this image has no explainer, but its
# own halo (MIND_PULL_HALO_SCALE, wider than Volatile's) already
# reserves a row tall enough to hold a portrait this size for free --
# see the row_height arithmetic below, which the halo still sets.
MIND_PULL_PORTRAIT_SIZE = 168
MIND_PULL_LABEL_GAP = 8
# Two lines under the die where the injury test has one: the team, and
# the faces the pull lands on. A d12 showing 9 says nothing until you
# know what it was chasing.
MIND_PULL_LABEL_HEIGHT = 44
MIND_PULL_COLUMN_GAP = 26
MIND_PULL_SIDE_PADDING = 22
MIND_PULL_BOTTOM_PADDING = 14
# The psychic purple every part of this image that is *not* the team's
# is drawn in -- the aura, the title and a landed pull. It is the
# Telekinetics' own team colour, which is what makes the image read as
# this ability rather than as a d12 with a caption.
MIND_PULL_AURA_COLOR = TEAM_COLORS[Team.TELEKINETICS]
# The halo behind the die, and the ring around it. Dim enough that the
# face stays the brightest thing in the column.
MIND_PULL_HALO_ALPHA = 70
MIND_PULL_HALO_SCALE = 2.9
MIND_PULL_RING_GAP = 8
MIND_PULL_RING_WIDTH = 3
MIND_PULL_LANDED_TEXT = "PULLED IN"
MIND_PULL_MISSED_TEXT = "MISSED"
MIND_PULL_MISSED_COLOR = "#98a3af"


def mind_pull_target_label() -> str:
    """
    "pulls on 1-2" -- read off the rule rather than written down, so a
    face added upstream reaches the image with the roll.
    """
    faces = "-".join(str(face) for face in MIND_PULL_SUCCESS_FACES)
    return f"pulls on {faces}"


def render_mind_pull_die(
    value: int,
    color: str,
    team_label: str,
    player_name: str,
    pulled: bool,
) -> BytesIO:
    """
    A Mind Pull attempt as one die, the Telekinetic taking it, and the
    verdict -- the same three-column row `render_injury_test_die`
    draws, so a coach reads it without learning a second layout.

    **What makes it a distinct die is the aura, not a different
    shape.** The Telekinetics' own spiral is drawn faint behind the
    face and a ring of the same purple around it, so the one d12 in
    the game that is nobody's skill test is recognisable before a word
    of it is read. The face itself stays the roller's team colour,
    because a Telekinetic plays for any of the eight teams (see "One
    player, both sides") and whose roll it is still has to be legible.

    The target band is on the image for the reason the injury test's
    token count is: a bare face means nothing until you know what it
    was chasing, and 1-2 out of 12 is the whole of why a coach might
    let the ball go instead.
    """
    verdict = MIND_PULL_LANDED_TEXT if pulled else MIND_PULL_MISSED_TEXT
    verdict_color = (
        MIND_PULL_AURA_COLOR if pulled else MIND_PULL_MISSED_COLOR
    )
    target_label = mind_pull_target_label()
    # Measured on a throwaway canvas: the real one cannot be created
    # until these widths have decided how big it needs to be. The halo
    # is wider than the die, so it -- not the polygon -- is what the
    # die column has to hold.
    measure = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    halo_size = round(2 * MIND_PULL_DIE_RADIUS * MIND_PULL_HALO_SCALE)
    portrait, die_column, portrait_column, verdict_bbox, row_height = (
        measure_verdict_columns(
            measure,
            [halo_size],
            [team_label, target_label],
            player_name,
            MIND_PULL_PORTRAIT_SIZE,
            verdict,
            MIND_PULL_LABEL_GAP,
            MIND_PULL_LABEL_HEIGHT,
        )
    )
    row = VerdictRow(
        portrait, die_column, portrait_column, verdict, verdict_bbox, row_height,
        row_left=MIND_PULL_SIDE_PADDING,
        row_top=MIND_PULL_ROW_TOP,
        column_gap=MIND_PULL_COLUMN_GAP,
        label_gap=MIND_PULL_LABEL_GAP,
        label_height=MIND_PULL_LABEL_HEIGHT,
    )
    width = round(
        MIND_PULL_SIDE_PADDING * 2
        + die_column
        + portrait_column
        + row.verdict_column
        + MIND_PULL_COLUMN_GAP * 2
    )
    height = MIND_PULL_ROW_TOP + row_height + MIND_PULL_BOTTOM_PADDING
    canvas = Image.new("RGBA", (width, height), "#111820")
    draw = ImageDraw.Draw(canvas)

    draw_title_across(
        draw, width, MIND_PULL_TITLE_TOP, MIND_PULL_TITLE,
        FONT_DICE_TOTAL, MIND_PULL_AURA_COLOR,
    )
    # The spiral goes down first and the die over it, so the face is
    # never competing with the art behind it. A missing icon file
    # leaves the die plain rather than failing the render, the same as
    # everywhere else a bundled image is read.
    draw_species_die_aura(
        canvas, draw, row.die_center_x, row.content_center_y,
        MIND_PULL_DIE_RADIUS,
        SPECIES_TELEKINETIC, MIND_PULL_AURA_COLOR,
        MIND_PULL_HALO_SCALE, MIND_PULL_HALO_ALPHA,
        MIND_PULL_RING_GAP, MIND_PULL_RING_WIDTH,
    )
    draw_verdict_die(
        draw, row, MIND_PULL_DIE_RADIUS, color, value,
        [(team_label, "#c7ced6"), (target_label, MIND_PULL_AURA_COLOR)],
    )
    draw_verdict_portrait(canvas, draw, row, player_name)
    draw_verdict_text(draw, row, verdict_color)
    return png_bytes(canvas)


VOLATILE_DIE_RADIUS = SKILL_TEST_DIE_RADIUS
VOLATILE_TITLE = "VOLATILE IGNITION"
VOLATILE_TITLE_TOP = 14
VOLATILE_EXPLAINER_TOP = 48
VOLATILE_ROW_TOP = 86
# Bigger than the injury test's and the Mind Pull die's 96, because
# this image has room the others do not: its explainer line is wider
# than any row of three columns, so a portrait at that size left the
# middle column a small picture in a lot of black. The portrait is now
# what sets the row's height, and the flame sits inside it.
VOLATILE_PORTRAIT_SIZE = 168
VOLATILE_LABEL_GAP = 8
# Two lines under the die, as the Mind Pull die has: the team, and the
# natural face that ignited. The second die on its own says nothing
# about which roll it belongs to.
VOLATILE_LABEL_HEIGHT = 44
VOLATILE_COLUMN_GAP = 26
VOLATILE_SIDE_PADDING = 22
VOLATILE_BOTTOM_PADDING = 14
# The Fire Demons' own team colour, which is what makes this read as
# Volatile rather than as a d12 with a caption -- the same call
# MIND_PULL_AURA_COLOR makes for the Telekinetics.
VOLATILE_AURA_COLOR = TEAM_COLORS[Team.FIRE_DEMONS]
# The flame behind the die, and the ring around it. Dim enough that the
# face stays the brightest thing in the column.
#
# **The flame is drawn as large as the row already is, and no larger.**
# The row's height is the portrait's, so a halo up to that size costs
# nothing; past it the flame is what grows the canvas, which is what
# the Mind Pull halo's 2.9 did here -- a wide orange blob with a die
# lost in the middle of a band of black. It cannot be the same number
# as that one either way, since the two shapes are not alike: a spiral
# is mostly the gaps between its arms and needs room to read as one,
# where a flame is solid. So the scale is whatever fills the portrait's
# height, and `test_the_portrait_is_what_sets_a_volatile_die_s_row` is
# the ceiling on it.
VOLATILE_HALO_ALPHA = 70
VOLATILE_HALO_SCALE = 2.3
VOLATILE_RING_GAP = 8
VOLATILE_RING_WIDTH = 3
VOLATILE_BLAZE_TEXT = "BLAZE"
VOLATILE_BURN_TEXT = "BURN"
# A burn is not a miss -- it takes the roll *down* -- so it is
# drawn in the injury test's red rather than the Mind Pull's "nothing
# happened" grey.
VOLATILE_BURN_COLOR = INJURY_TEST_INJURED_COLOR
# The die is a d12, so the blaze band runs from VOLATILE_BLAZE_MINIMUM
# to its top face.
VOLATILE_DIE_FACES = 12


def volatile_explainer_label() -> str:
    """
    "a natural 6 or 7 ignites — the second d12 adds on 5-12, subtracts
    on 1-4": the whole rule, read off `VOLATILE_IGNITE_FACES` and
    `VOLATILE_BLAZE_MINIMUM` rather than written down, so a number
    settled upstream reaches the image with the roll.

    It is on the image for the reason the Mind Pull die's target band
    is: a coach who has just been handed a second die has no way to
    tell whether it was a good one, and a caption that lives only in
    the message scrolls away from the picture it explains.
    """
    faces = " or ".join(str(face) for face in VOLATILE_IGNITE_FACES)
    return (
        f"a natural {faces} ignites — the second d12 adds on "
        f"{VOLATILE_BLAZE_MINIMUM}-{VOLATILE_DIE_FACES}, subtracts on "
        f"1-{VOLATILE_BLAZE_MINIMUM - 1}"
    )


def render_volatile_die(
    second: int,
    face: int,
    color: str,
    team_label: str,
    player_name: str,
    blaze: bool,
    modifier: int,
) -> BytesIO:
    """
    The extra die an ignite rolled, on an image of its own: the second
    d12, the Fire Demon who set it off, and which way it went.

    **It is a separate die because it is a separate roll.** Every other
    modifier in the game is arithmetic a coach can check against the
    board or a card; this one is a die nobody watched being thrown, and
    folding it into the totals column of the roll's own dice image --
    which is all it was before -- left the number on the face and the
    number in the total disagreeing with nothing to explain the gap.

    It follows `render_mind_pull_die`'s three-column row (die,
    portrait, verdict) for the same reason that one follows the injury
    test's: a coach should not have to learn a layout per ability.
    **What makes it distinct is the aura**, the Fire Demons' own flame
    drawn faint behind the face with a ring of their orange around it.
    The face itself stays the roller's *team* colour, because a Fire
    Demon plays for any of the eight teams (see "One player, both
    sides") and whose roll it is still has to be legible.
    """
    verdict = VOLATILE_BLAZE_TEXT if blaze else VOLATILE_BURN_TEXT
    verdict = f"{verdict} {modifier:+d}"
    verdict_color = VOLATILE_AURA_COLOR if blaze else VOLATILE_BURN_COLOR
    trigger_label = f"ignited on {face}"
    explainer = volatile_explainer_label()
    # Measured on a throwaway canvas: the real one cannot be created
    # until these widths have decided how big it needs to be. The halo
    # is wider than the die, so it -- not the polygon -- is what the
    # die column has to hold.
    measure = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    halo_size = round(2 * VOLATILE_DIE_RADIUS * VOLATILE_HALO_SCALE)
    portrait, die_column, portrait_column, verdict_bbox, row_height = (
        measure_verdict_columns(
            measure,
            [halo_size],
            [team_label, trigger_label],
            player_name,
            VOLATILE_PORTRAIT_SIZE,
            verdict,
            VOLATILE_LABEL_GAP,
            VOLATILE_LABEL_HEIGHT,
        )
    )
    verdict_column = verdict_bbox[2] - verdict_bbox[0]
    # The explainer is the widest thing on most of these images, and it
    # is the half a coach reading their first ignite actually needs --
    # so the canvas is sized to whichever of the two is wider rather
    # than the sentence being cut to the row.
    columns_width = die_column + portrait_column + verdict_column
    explainer_width = measure.textlength(explainer, font=FONT_SMALL)
    content_width = max(
        columns_width + VOLATILE_COLUMN_GAP * 2, explainer_width,
    )
    width = round(VOLATILE_SIDE_PADDING * 2 + content_width)
    # **The slack the explainer creates goes between the columns, not
    # around them.** Three columns centred under a wider sentence left
    # a band of black down each side of the row and the portrait
    # marooned in the middle of it; spread across the whole content
    # width they read as the row the sentence is about.
    # `VOLATILE_COLUMN_GAP` is the floor, for the image narrow enough
    # that the row is what sets the width.
    column_gap = max(
        VOLATILE_COLUMN_GAP, (content_width - columns_width) / 2,
    )
    row = VerdictRow(
        portrait, die_column, portrait_column, verdict, verdict_bbox, row_height,
        row_left=VOLATILE_SIDE_PADDING,
        row_top=VOLATILE_ROW_TOP,
        column_gap=column_gap,
        label_gap=VOLATILE_LABEL_GAP,
        label_height=VOLATILE_LABEL_HEIGHT,
    )
    height = VOLATILE_ROW_TOP + row_height + VOLATILE_BOTTOM_PADDING
    canvas = Image.new("RGBA", (width, height), "#111820")
    draw = ImageDraw.Draw(canvas)

    draw_title_across(
        draw, width, VOLATILE_TITLE_TOP, VOLATILE_TITLE,
        FONT_DICE_TOTAL, VOLATILE_AURA_COLOR,
    )
    draw.text(
        ((width - explainer_width) / 2, VOLATILE_EXPLAINER_TOP),
        explainer,
        font=FONT_SMALL,
        fill="#c7ced6",
    )
    # The flame goes down first and the die over it, so the face is
    # never competing with the art behind it. A missing icon file leaves
    # the die plain rather than failing the render, the same as
    # everywhere else a bundled image is read.
    draw_species_die_aura(
        canvas, draw, row.die_center_x, row.content_center_y,
        VOLATILE_DIE_RADIUS,
        SPECIES_FIRE_DEMON, VOLATILE_AURA_COLOR,
        VOLATILE_HALO_SCALE, VOLATILE_HALO_ALPHA,
        VOLATILE_RING_GAP, VOLATILE_RING_WIDTH,
    )
    draw_verdict_die(
        draw, row, VOLATILE_DIE_RADIUS, color, second,
        [(team_label, "#c7ced6"), (trigger_label, VOLATILE_AURA_COLOR)],
    )
    draw_verdict_portrait(canvas, draw, row, player_name)
    draw_verdict_text(draw, row, verdict_color)
    return png_bytes(canvas)


OWN_GOAL_DIE_RADIUS = SKILL_TEST_DIE_RADIUS
OWN_GOAL_CELL_WIDTH = 108
OWN_GOAL_TOP_PADDING = 20
# The ring marking the die that counted sits outside it, so the top
# padding and the cell have to leave room for both it and its width.
OWN_GOAL_MARK_GAP = 7
OWN_GOAL_MARK_WIDTH = 4
OWN_GOAL_MARK_COLOR = "#e8b923"
OWN_GOAL_OUTCOME_GAP = 20
OWN_GOAL_BOTTOM_PADDING = 16
OWN_GOAL_SIDE_PADDING = 22
# The die that wasn't taken keeps its shape but drops out of the team's
# color, so which number the roll used is legible without a caption.
OWN_GOAL_DROPPED_COLOR = "#37414d"
OWN_GOAL_DROPPED_OUTLINE = "#5f6b78"
OWN_GOAL_DROPPED_TEXT = "#98a3af"
OWN_GOAL_AVOIDED_TEXT = "Own goal avoided!"
OWN_GOAL_CONCEDED_TEXT = "Own goal!"
# Shared with the injury test: green for the roll that got away with
# it, red for the one that didn't.
OWN_GOAL_AVOIDED_COLOR = INJURY_TEST_SAFE_COLOR
OWN_GOAL_CONCEDED_COLOR = INJURY_TEST_INJURED_COLOR


def render_own_goal_dice(
    rolls: list[int],
    color: str,
    safe: bool,
    overdriven: bool = False,
) -> BytesIO:
    """
    Render an own-goal roll: the dice at skill-test size, a ring around
    the one the advantage took, and the outcome underneath.

    Nothing else is drawn on it. The arithmetic behind the verdict --
    which player rolled, their offensive skill, the total -- is in the
    message the image is attached to, and the roll's own captions were
    only ever the word "Rolled" twice, which said nothing the dice
    didn't. What the picture is for is the two numbers and which of
    them counted.

    Every die matching the highest result is ringed, so a pair that
    rolled the same number doesn't arbitrarily favour one of them.

    `overdriven` supercharges the kept die alone -- the discarded one
    never counted, and Overdrive was spent on the total that did.
    Drawn without its own ring (`draw_ring=False`): the kept die
    already wears the "this one counted" mark, and a second ring at
    nearly the same radius would blur into it rather than read as two
    facts.
    """
    outcome = OWN_GOAL_AVOIDED_TEXT if safe else OWN_GOAL_CONCEDED_TEXT
    outcome_color = (
        OWN_GOAL_AVOIDED_COLOR if safe else OWN_GOAL_CONCEDED_COLOR
    )

    # Measured on a throwaway canvas: the real one can't be created
    # until the outcome's width has decided how wide it needs to be.
    measure = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    outcome_bbox = measure.textbbox((0, 0), outcome, font=FONT_DICE_TOTAL)
    outcome_width = outcome_bbox[2] - outcome_bbox[0]
    outcome_height = outcome_bbox[3] - outcome_bbox[1]

    mark_radius = OWN_GOAL_DIE_RADIUS + OWN_GOAL_MARK_GAP
    # An overdriven kept die's halo is both taller and wider than the
    # ordinary "this one counted" mark reserves room for, so both the
    # top padding and the cell a die sits in grow to fit it -- applied
    # to every cell rather than only the counted one, so the two dice
    # stay evenly spaced whichever one the advantage took.
    overdrive_radius = (OVERDRIVE_HALO_SIZE / 2) if overdriven else 0
    center_y = OWN_GOAL_TOP_PADDING + max(mark_radius, overdrive_radius)
    cell_width = max(OWN_GOAL_CELL_WIDTH, OVERDRIVE_HALO_SIZE if overdriven else 0)
    outcome_y = center_y + mark_radius + OWN_GOAL_OUTCOME_GAP
    height = round(outcome_y + outcome_height + OWN_GOAL_BOTTOM_PADDING)
    width = round(
        max(
            cell_width * len(rolls),
            outcome_width + OWN_GOAL_SIDE_PADDING * 2,
        )
    )

    canvas = Image.new("RGBA", (width, height), "#111820")
    draw = ImageDraw.Draw(canvas)

    taken = max(rolls)
    dice_left = (width - cell_width * len(rolls)) / 2

    for index, value in enumerate(rolls):
        center_x = round(
            dice_left
            + index * cell_width
            + cell_width / 2
        )
        counted = value == taken
        if counted and overdriven:
            draw_species_die_aura(
                canvas, draw, center_x, center_y, OWN_GOAL_DIE_RADIUS,
                SPECIES_CYBORG, OVERDRIVE_AURA_COLOR,
                OVERDRIVE_HALO_SCALE, OVERDRIVE_HALO_ALPHA,
                OVERDRIVE_RING_GAP, OVERDRIVE_RING_WIDTH,
                draw_ring=False,
                halo_override=cyborg_cell_without_bolt(
                    OVERDRIVE_AURA_COLOR, OVERDRIVE_HALO_SIZE,
                ),
            )
        draw_d12_polygon(
            draw,
            center_x,
            center_y,
            OWN_GOAL_DIE_RADIUS,
            color if counted else OWN_GOAL_DROPPED_COLOR,
            str(value),
            font=FONT_DICE_VALUE,
            outline="#ffffff" if counted else OWN_GOAL_DROPPED_OUTLINE,
            text_color=(
                high_contrast_ink(color) if counted else OWN_GOAL_DROPPED_TEXT
            ),
        )
        if counted:
            draw.polygon(
                polygon_points(center_x, center_y, mark_radius, 12),
                outline=OWN_GOAL_MARK_COLOR,
                width=OWN_GOAL_MARK_WIDTH,
            )

    draw.text(
        (
            (width - outcome_width) / 2 - outcome_bbox[0],
            outcome_y - outcome_bbox[1],
        ),
        outcome,
        font=FONT_DICE_TOTAL,
        fill=outcome_color,
    )

    return png_bytes(canvas)


CHALLENGE_TITLE = "MANEUVER CHALLENGE"
SCORE_ATTEMPT_TITLE = "SCORE ATTEMPT"
SCORE_ATTEMPT_UNDEFENDED = "No one in the way"
# A group's text is wrapped to its own width, which grows with what it
# has to say and is held between these. The minimum is a floor under a
# group carrying an ability, so a sentence under a short name does not
# wrap into a narrow column.
#
# It was 300, which on a maneuver challenge -- two lone
# players, both under it -- was most of the image's width and none of
# its content: a two-word name and a skill line, centred in a column
# they came nowhere near filling, with the same black either side of
# them again. Discord scales the whole image to the message's width, so
# every pixel of that was spent making the writing smaller. It is now
# little more than the portrait it sits under.
CHALLENGE_MIN_GROUP_WIDTH = 248
# The maximum is where a line of names stops earning the width it costs
# and should wrap instead. It came down with the bigger body type: a
# wall of three defenders names them on one line, and at 22px that line
# alone was stretching a score attempt wider than it had been before
# any of this. The sum underneath still overrides it -- a total broken
# over two lines is unreadable at any width -- so this is a cap on the
# names, not on the image.
CHALLENGE_MAX_GROUP_WIDTH = 450
# The same size the injury test draws a portrait at, which is the only
# other image that shows one beside a caption. It is a step up from the
# diameter of a skill test's dice, where this started: the abbreviated
# abilities freed the height, and a portrait is what a coach picks a
# player out by.
CHALLENGE_PORTRAIT_SIZE = INJURY_TEST_PORTRAIT_SIZE
CHALLENGE_PORTRAIT_SPACING = 10
# Wide enough for the "vs" and a breath either side of it. It was 64,
# which stood the two sides further apart than either of them was wide.
CHALLENGE_GUTTER = 44
CHALLENGE_TITLE_TOP = 12
CHALLENGE_LOCATION_TOP = 38
CHALLENGE_PORTRAIT_TOP = 72
CHALLENGE_PORTRAIT_GAP = 12
CHALLENGE_LINE_HEIGHT = 27
CHALLENGE_ABILITY_GAP = 8
CHALLENGE_ABILITY_LINE_HEIGHT = 23
CHALLENGE_TEXT_PADDING = 14
CHALLENGE_BOTTOM_PADDING = 16
CHALLENGE_VERSUS_TEXT = "vs"
CHALLENGE_VERSUS_COLOR = "#8b96a2"
CHALLENGE_NAME_COLOR = "#ffffff"
CHALLENGE_SKILL_COLOR = "#c7ced6"
CHALLENGE_ABILITY_COLOR = "#9aa5b1"
CHALLENGE_TOTAL_COLOR = "#ffffff"
CHALLENGE_TOTAL_LINE_HEIGHT = 34
# A score attempt's defenders are worth their skill on the ball's own
# space and half of it further along (see ShotDefender), so the group is
# two kinds of number stood in a row. The value each one contributes is
# drawn on their own portrait -- a solid disc for a full one, an outline
# and the skill it was halved from for the rest -- because the sum
# underneath is unreadable otherwise: nothing in "6 + 3 + 1" says which
# term was halved or whose it is.
CHALLENGE_FULL_COLOR = "#f0b429"
CHALLENGE_HALF_COLOR = "#7fa8c9"
CHALLENGE_BADGE_TEXT_COLOR = "#111820"
CHALLENGE_BADGE_RADIUS = 19
CHALLENGE_BADGE_INSET = 2
CHALLENGE_BADGE_OUTLINE = 3
# What a banded group costs the layout: a label above the portraits, and
# room under them for the "1/2 of 5" that hangs off a halved badge.
CHALLENGE_BAND_GAP = 26
CHALLENGE_BADGE_NOTE_GAP = 16
CHALLENGE_BAND_UNDERLINE_GAP = 20
# Longest first: a band gives up words only once shrinking the type has
# run out, because "FULL" over a gold badge says less than "ON THE BALL"
# does about why it is gold. A band of one has 96px to say it in.
CHALLENGE_BAND_FULL = ("ON THE BALL — FULL", "ON THE BALL", "FULL")
CHALLENGE_BAND_HALF = (
    "IN THE WAY — HALF, ROUNDED UP",
    "IN THE WAY — HALVED",
    "HALVED",
)


@dataclass(frozen=True)
class ChallengeSide:
    """
    One player in a matchup, ready to draw: who they are, the skill
    their side of it is measured on, whatever else is being added to
    that, and the ability they bring.

    `skill_name` and `skill` are the whole of the offense/defense
    distinction -- every player is drawn identically otherwise, and
    which of their two skills matters is exactly what a coach is
    weighing. They are kept apart so a group of players can add its
    numbers up into one line. `modifiers` are the extras that only some
    rolls have (a ball speed bonus, a role ability that applies to this
    one), listed under the skill in the order they should be read.

    `contribution` is what this player actually adds when that is not
    their whole skill -- a score attempt's defenders, half of whom are
    halved. None means the skill itself, which is every other player on
    every other image, and nothing extra is drawn about it. `halved`
    cannot be inferred from the two numbers: a defensive skill of 1
    halves to 1, and drawing that as a full value would say the
    defender is on the ball when they are not.
    """

    name: str
    role: str
    team_color: str
    team_label: str
    skill_name: str
    skill: int
    ability: str
    modifiers: tuple[str, ...] = ()
    contribution: Optional[int] = None
    halved: bool = False

    @property
    def value(self) -> int:
        """What this player's side adds for them."""
        return self.skill if self.contribution is None else self.contribution


def join_names(names: list[str]) -> str:
    if len(names) <= 2:
        return " and ".join(names)
    return f"{', '.join(names[:-1])}, and {names[-1]}"


def group_text_lines(
    sides: list[ChallengeSide],
    with_ability: bool,
) -> list[tuple[str, str, ImageFont.ImageFont, int]]:
    """
    The (text, color, font, line height) under a group's portraits,
    still unwrapped -- the width they are wrapped to is decided from
    how wide they want to be.

    One player reads as themselves: name, the skill they roll on, and
    their ability. Several read as a wall: the team once, the names in
    a line, and their contributions added up, because that sum is the
    only number the roll uses and nobody is choosing between them. The
    sum is set bold and a size up for that reason -- it is the one line
    here that is a result rather than a fact about a player, and it is
    what the shot is actually up against.

    A lone player carrying a halved contribution says where it came
    from, since a "+2" with no second term to read it against is a
    number out of nowhere. In a group the badges on the portraits do
    that job -- see CHALLENGE_FULL_COLOR.
    """
    if not sides:
        return []

    sized = [
        (
            sides[0].team_label,
            sides[0].team_color,
            FONT_CHALLENGE_BODY,
            CHALLENGE_LINE_HEIGHT,
        ),
        (
            join_names([f"{side.name} [{side.role}]" for side in sides]),
            CHALLENGE_NAME_COLOR,
            FONT_CHALLENGE_BODY,
            CHALLENGE_LINE_HEIGHT,
        ),
    ]

    skill_name = sides[0].skill_name
    if len(sides) == 1:
        only = sides[0]
        halved_from = f" (half of {only.skill})" if only.halved else ""
        sized.append(
            (
                f"{skill_name} skill +{only.value}{halved_from}",
                CHALLENGE_SKILL_COLOR,
                FONT_CHALLENGE_BODY,
                CHALLENGE_LINE_HEIGHT,
            ),
        )
        sized.extend(
            (
                modifier,
                CHALLENGE_SKILL_COLOR,
                FONT_CHALLENGE_BODY,
                CHALLENGE_LINE_HEIGHT,
            )
            for modifier in sides[0].modifiers
        )
    else:
        skills = " + ".join(str(side.value) for side in sides)
        total = sum(side.value for side in sides)
        sized.append(
            (
                f"{skill_name} skill: {skills} = {total}",
                CHALLENGE_TOTAL_COLOR,
                FONT_CHALLENGE_TOTAL,
                CHALLENGE_TOTAL_LINE_HEIGHT,
            ),
        )

    if with_ability and len(sides) == 1 and sides[0].ability:
        # An empty line is a spacer: it sets the ability apart from the
        # numbers above it without needing a second y-cursor.
        sized.append(
            (
                "",
                CHALLENGE_ABILITY_COLOR,
                FONT_CHALLENGE_ABILITY,
                CHALLENGE_ABILITY_GAP,
            ),
        )
        sized.append(
            (
                sides[0].ability,
                CHALLENGE_ABILITY_COLOR,
                FONT_CHALLENGE_ABILITY,
                CHALLENGE_ABILITY_LINE_HEIGHT,
            ),
        )
    return sized


def draw_contribution_badge(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    x: float,
    y: float,
    side: ChallengeSide,
) -> None:
    """
    The number this player adds, on the portrait it belongs to.

    A full value is a solid disc and a halved one is an outline
    carrying the skill it was halved from, so every term of the sum
    below can be checked against a face -- which is the whole reason
    the badge exists rather than a longer arithmetic line.
    """
    radius = CHALLENGE_BADGE_RADIUS
    center_x = x + CHALLENGE_PORTRAIT_SIZE - radius - CHALLENGE_BADGE_INSET
    center_y = y + CHALLENGE_PORTRAIT_SIZE - radius - CHALLENGE_BADGE_INSET
    box = (
        center_x - radius,
        center_y - radius,
        center_x + radius,
        center_y + radius,
    )
    if side.halved:
        draw.ellipse(
            box,
            fill="#111820",
            outline=CHALLENGE_HALF_COLOR,
            width=CHALLENGE_BADGE_OUTLINE,
        )
        text_color = CHALLENGE_HALF_COLOR
    else:
        draw.ellipse(
            box,
            fill=CHALLENGE_FULL_COLOR,
            outline="#111820",
            width=CHALLENGE_BADGE_OUTLINE,
        )
        text_color = CHALLENGE_BADGE_TEXT_COLOR
    draw_centered_text(
        draw,
        center_x,
        center_y - 13,
        str(side.value),
        FONT_CHALLENGE_BADGE,
        text_color,
    )
    if side.halved:
        draw_centered_text(
            draw,
            center_x,
            center_y + radius + 2,
            f"½ of {side.skill}",
            FONT_CHALLENGE_BADGE_NOTE,
            CHALLENGE_HALF_COLOR,
        )


def draw_contribution_bands(
    draw: ImageDraw.ImageDraw,
    placed: list[tuple[ChallengeSide, float]],
    band_top: float,
) -> None:
    """
    Label each run of like-valued portraits: the ones on the ball,
    worth their whole skill, and the ones further along, worth half.

    The runs come out of the order the portraits are already in, which
    is the order the shot travels -- so the ball space is the first run
    and there are never more than two. Labelling the runs rather than
    the players is what keeps the rule on the image once a badge alone
    would have to be read one at a time.
    """
    banded = [(side, x) for side, x in placed if side.contribution is not None]
    if not banded:
        return

    spans: list[tuple[bool, float, float]] = []
    for side, x in banded:
        right = x + CHALLENGE_PORTRAIT_SIZE
        if spans and spans[-1][0] == side.halved:
            halved, start, _ = spans.pop()
            spans.append((halved, start, right))
        else:
            spans.append((side.halved, x, right))

    for halved, start, end in spans:
        color = CHALLENGE_HALF_COLOR if halved else CHALLENGE_FULL_COLOR
        labels = CHALLENGE_BAND_HALF if halved else CHALLENGE_BAND_FULL
        # A label may lean into the gap beside its band, but not so far
        # that two of them touch.
        room = (end - start) + (
            CHALLENGE_PORTRAIT_SPACING
            if len(spans) > 1
            else CHALLENGE_TEXT_PADDING * 2
        )
        text, font = labels[-1], FONTS_CHALLENGE_BAND[-1]
        for candidate in labels:
            fits = next(
                (
                    option
                    for option in FONTS_CHALLENGE_BAND
                    if draw.textlength(candidate, font=option) <= room
                ),
                None,
            )
            if fits is not None:
                text, font = candidate, fits
                break
        draw_centered_text(
            draw,
            (start + end) / 2,
            band_top,
            shorten_to_width(draw, text, font, room),
            font,
            color,
        )
        draw.line(
            (
                start,
                band_top + CHALLENGE_BAND_UNDERLINE_GAP,
                end,
                band_top + CHALLENGE_BAND_UNDERLINE_GAP,
            ),
            fill=color,
            width=2,
        )


def portrait_row_width(sides: list[ChallengeSide]) -> int:
    """How wide a group's portraits are, laid side by side."""
    return (
        len(sides) * CHALLENGE_PORTRAIT_SIZE
        + max(len(sides) - 1, 0) * CHALLENGE_PORTRAIT_SPACING
    )


def matchup_group_width(
    measure: ImageDraw.ImageDraw,
    sides: list[ChallengeSide],
    note: str,
    ability: bool,
) -> int:
    """
    Wide enough for the portraits, and for the text up to the point
    where wrapping it is better than growing.
    """
    portraits = portrait_row_width(sides)
    # The ability is left out of this: it is a sentence, and sizing
    # a group to fit one on a line would make the image unreadably
    # wide. It wraps to whatever the rest of the group settles on.
    texts = [
        (text, font)
        for text, _, font, _ in group_text_lines(sides, False)
    ]
    if not sides and note:
        texts = [(note, FONT_CHALLENGE_BODY)]
    text_width = max(
        (measure.textlength(text, font=font) for text, font in texts),
        default=0,
    )
    # The sum is the one line that must not wrap: a total broken
    # over two lines, with the number stranded on the second, is
    # unreadable however wide the alternative makes the image. So
    # it sets a floor the maximum width does not get to override.
    sum_width = max(
        (
            measure.textlength(text, font=font)
            for text, font in texts
            if font is FONT_CHALLENGE_TOTAL
        ),
        default=0,
    )
    wanted = max(
        portraits,
        text_width + CHALLENGE_TEXT_PADDING * 2,
    )
    if ability:
        # A group carrying an ability holds a minimum width, so a
        # sentence under one short name doesn't wrap into a narrow
        # column. A group without one is as narrow as its own
        # content allows, which is what packs a wall of defenders
        # together instead of spreading them over a fixed grid.
        wanted = max(wanted, CHALLENGE_MIN_GROUP_WIDTH)
    return round(
        max(
            min(wanted, CHALLENGE_MAX_GROUP_WIDTH),
            portraits + CHALLENGE_TEXT_PADDING * 2,
            sum_width + CHALLENGE_TEXT_PADDING * 2,
        )
    )


def matchup_group_lines(
    measure: ImageDraw.ImageDraw,
    sides: list[ChallengeSide],
    note: str,
    ability: bool,
    width: int,
) -> list[tuple[str, str, ImageFont.ImageFont, int]]:
    """A group's text, wrapped to the width the group settled on."""
    if not sides:
        return (
            [(note, CHALLENGE_SKILL_COLOR, FONT_CHALLENGE_BODY, CHALLENGE_LINE_HEIGHT)]
            if note
            else []
        )
    lines = []
    for text, color, font, line_height in group_text_lines(sides, ability):
        if not text:
            lines.append((text, color, font, line_height))
            continue
        for piece in wrap_text(
            measure, text, font, width - CHALLENGE_TEXT_PADDING * 2,
        ):
            lines.append((piece, color, font, line_height))
    return lines


@dataclass(frozen=True)
class MatchupLayout:
    """
    Every measurement a matchup image is drawn against, settled before
    the canvas exists -- its width is content, not a canvas, so the
    groups have to be measured before there is anything to draw on.
    """

    attacking_width: int
    defending_width: int
    attacking_lines: list[tuple[str, str, ImageFont.ImageFont, int]]
    defending_lines: list[tuple[str, str, ImageFont.ImageFont, int]]
    portrait_top: float
    text_top: float
    width: int
    height: int

    @property
    def defending_left(self) -> int:
        return self.attacking_width + CHALLENGE_GUTTER


def matchup_layout(
    attacking: list[ChallengeSide],
    defending: list[ChallengeSide],
    defending_note: str,
    attacking_abilities: bool,
    defending_abilities: bool,
) -> MatchupLayout:
    # Measured on a throwaway canvas: how wide each group wants to be,
    # and how many lines its text wraps to at that width, decide the
    # size of the real one.
    measure = ImageDraw.Draw(Image.new("RGBA", (1, 1)))

    attacking_width = matchup_group_width(
        measure, attacking, "", attacking_abilities,
    )
    defending_width = matchup_group_width(
        measure, defending, defending_note, defending_abilities,
    )
    attacking_lines = matchup_group_lines(
        measure, attacking, "", attacking_abilities, attacking_width,
    )
    defending_lines = matchup_group_lines(
        measure, defending, defending_note, defending_abilities, defending_width,
    )

    # Badges and their band labels are drawn around the portraits, so
    # an image carrying them starts its portrait row lower and its text
    # lower again. Both groups move together: the two rows of portraits
    # are read as one line and the "vs" sits between them.
    banded = any(
        side.contribution is not None for side in attacking + defending
    )
    portrait_top = CHALLENGE_PORTRAIT_TOP + (CHALLENGE_BAND_GAP if banded else 0)
    text_top = (
        portrait_top
        + CHALLENGE_PORTRAIT_SIZE
        + CHALLENGE_PORTRAIT_GAP
        + (CHALLENGE_BADGE_NOTE_GAP if banded else 0)
    )
    body_bottom = text_top + max(
        sum(line_height for _, _, _, line_height in lines)
        for lines in (attacking_lines, defending_lines)
    )
    return MatchupLayout(
        attacking_width=attacking_width,
        defending_width=defending_width,
        attacking_lines=attacking_lines,
        defending_lines=defending_lines,
        portrait_top=portrait_top,
        text_top=text_top,
        width=attacking_width + CHALLENGE_GUTTER + defending_width,
        height=round(body_bottom + CHALLENGE_BOTTOM_PADDING),
    )


def draw_matchup_heading(
    draw: ImageDraw.ImageDraw,
    layout: MatchupLayout,
    title: str,
    location: str,
) -> None:
    """The title, the space it is happening on, and the "vs" between the groups."""
    draw_centered_text(
        draw, layout.width / 2, CHALLENGE_TITLE_TOP, title, FONT_CHALLENGE_TITLE, "#ffffff",
    )
    draw_centered_text(
        draw, layout.width / 2, CHALLENGE_LOCATION_TOP, location, FONT_CHALLENGE_BODY,
        CHALLENGE_SKILL_COLOR,
    )
    draw_centered_text(
        draw,
        layout.attacking_width + CHALLENGE_GUTTER / 2,
        layout.portrait_top + CHALLENGE_PORTRAIT_SIZE / 2 - 14,
        CHALLENGE_VERSUS_TEXT,
        FONT_CHALLENGE_TITLE,
        CHALLENGE_VERSUS_COLOR,
    )


def draw_matchup_group(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    layout: MatchupLayout,
    left: int,
    group_width_px: int,
    sides: list[ChallengeSide],
    lines: list[tuple[str, str, ImageFont.ImageFont, int]],
) -> None:
    """One side of the matchup: its portraits in a row, and its text under them."""
    center_x = left + group_width_px / 2
    portrait_x = center_x - portrait_row_width(sides) / 2
    placed: list[tuple[ChallengeSide, float]] = []
    for side in sides:
        placed.append((side, portrait_x))
        portrait = load_player_portrait(side.name)
        if portrait is not None:
            sized = portrait.copy()
            sized.thumbnail(
                (CHALLENGE_PORTRAIT_SIZE, CHALLENGE_PORTRAIT_SIZE),
                Image.Resampling.LANCZOS,
            )
            canvas.alpha_composite(
                sized,
                (
                    round(
                        portrait_x
                        + (CHALLENGE_PORTRAIT_SIZE - sized.width) / 2
                    ),
                    round(
                        layout.portrait_top
                        + (CHALLENGE_PORTRAIT_SIZE - sized.height) / 2
                    ),
                ),
            )
        portrait_x += CHALLENGE_PORTRAIT_SIZE + CHALLENGE_PORTRAIT_SPACING

    for side, x in placed:
        if side.contribution is not None:
            draw_contribution_badge(canvas, draw, x, layout.portrait_top, side)
    draw_contribution_bands(draw, placed, layout.portrait_top - CHALLENGE_BAND_GAP)

    y = layout.text_top
    for text, color, font, line_height in lines:
        draw_centered_text(draw, center_x, y, text, font, color)
        y += line_height


def render_matchup(
    title: str,
    location: str,
    attacking: list[ChallengeSide],
    defending: list[ChallengeSide],
    defending_note: str = "",
    attacking_abilities: bool = True,
    defending_abilities: bool = True,
) -> BytesIO:
    """
    Render a contest about to happen: who is on each side, with
    portraits, names and roles, the skill each side rolls on, and where
    on the board it is happening.

    Shared by the maneuver challenge and the score attempt, which is
    why either side is a list -- a maneuver is always one against one,
    but a shot is one against however many defenders stand between the
    ball and the goal, sometimes none, and those defenders are drawn as
    a single group: portraits in a row, the team named once, the names
    on one line and the skills added up on the next. `defending_note`
    is drawn in place of an empty defending side, for a shot at an open
    goal.

    `defending_abilities` is what tells that wall from a single
    challenger. A maneuver's challenger is one player being weighed,
    ability and all; a shot's defenders are a number in the way, and
    printing an ability apiece for players nobody is choosing between
    spread them across the image and buried the skills that decide it.

    `attacking_abilities` is off for a shot for a different reason: an
    ability that bears on the attempt is already a modifier line above,
    so the sentence only repeats it, and one that doesn't bear on the
    attempt is not what the shot is about. A maneuver keeps it, because
    there the ability is a fact about a player being weighed rather
    than a number already in the sum.

    Both images replace prose that named the same players and said
    nothing about them: what a coach needs in front of them is the
    other side's skills and abilities, which the board shows only as
    numbers on a card too small to read the ability off.
    """
    layout = matchup_layout(
        attacking, defending, defending_note,
        attacking_abilities, defending_abilities,
    )
    canvas = Image.new("RGBA", (layout.width, layout.height), "#111820")
    draw = ImageDraw.Draw(canvas)

    draw_matchup_heading(draw, layout, title, location)
    draw_matchup_group(
        canvas, draw, layout, 0, layout.attacking_width,
        attacking, layout.attacking_lines,
    )
    draw_matchup_group(
        canvas, draw, layout, layout.defending_left, layout.defending_width,
        defending, layout.defending_lines,
    )

    return png_bytes(canvas)


def render_maneuver_challenge(
    offense: ChallengeSide,
    defense: ChallengeSide,
    location: str,
) -> BytesIO:
    """The two players about to contest a maneuver, one against one."""
    return render_matchup(
        CHALLENGE_TITLE, location, [offense], [defense],
    )


def render_score_attempt(
    shooter: ChallengeSide,
    defenders: list[ChallengeSide],
    location: str,
) -> BytesIO:
    """
    The shooter, and everyone between them and the goal as one group.

    The defenders carry a `contribution` apiece, so the group is drawn
    with a badge on each portrait and a band label over each run of
    them: on the ball is worth a whole defensive skill and the rest are
    worth half, and a coach reading "6 + 3 + 1" has no way to tell
    which was which. See CHALLENGE_FULL_COLOR and ShotDefender.

    Nothing here says what the dice did -- this is the composition of
    the attempt, posted before anyone rolls, and the roll gets its own
    image afterwards.
    """
    return render_matchup(
        SCORE_ATTEMPT_TITLE,
        location,
        [shooter],
        defenders,
        defending_note=SCORE_ATTEMPT_UNDEFENDED,
        attacking_abilities=False,
        defending_abilities=False,
    )


MANEUVER_DIAGRAM_WIDTH = 2080
MANEUVER_DIAGRAM_HEIGHT = 2060
MANEUVER_DIAGRAM_CENTER = (1040, 980)
MANEUVER_DIAGRAM_NODE_RADIUS = 760
MANEUVER_DIAGRAM_ARC_RADIUS = 250
# One rank's own pair of boxes -- basic on the left, advanced on the
# right, the same rank the two are on rather than two unrelated cards
# next to each other. `MANEUVER_DIAGRAM_BOX_SIZE` is a single box, the
# same for all twelve regardless of how long that card's own effect
# runs -- `_TIER_GAP` is the seam between the pair, `_RANK_LABEL_HEIGHT`
# the room the rank badge takes above it.
MANEUVER_DIAGRAM_BOX_SIZE = (296, 330)
MANEUVER_DIAGRAM_TIER_GAP = 14
MANEUVER_DIAGRAM_RANK_LABEL_HEIGHT = 56
# d12ball/cards.py imports these four (as OFFENSE_COLOR/DEFENSE_COLOR
# and their _GAMBIT counterparts) rather than restating the hexes,
# the same reason TEAM_COLORS below is one dict instead of a hex per
# call site. Don't add a second definition there.
#
# **Deliberately a different shade, not a tint of the same one.** A
# basic and a gambit on the same rank sit side by side on the
# reference image and back to back on the printed card's own edge, so
# they have to read as two cards at a glance -- a lighter or darker
# version of the same hue reads as the same card under different
# lighting instead.
MANEUVER_OFFENSE_COLOR = "#E24B4A"
MANEUVER_DEFENSE_COLOR = "#97C459"
MANEUVER_OFFENSE_COLOR_GAMBIT = "#7A2038"
MANEUVER_DEFENSE_COLOR_GAMBIT = "#2F5D3A"
MANEUVER_CARD_TEXT_COLOR = "#14202b"
MANEUVER_CARD_TEXT_COLOR_GAMBIT = "#f4efe4"


def wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


class FittedManeuverBox(NamedTuple):
    name_lines: list[str]
    effect_lines: list[str]
    effect_font: ImageFont.ImageFont
    effect_line_height: int


# The title is one fixed size on every box, not a size that tracks
# whatever the effect text lands on -- a name is a name and all twelve
# read at the same size regardless of how long that card's own effect
# is. It is set once, a point above `MANEUVER_EFFECT_CEILING` (the
# largest the search below is ever allowed to reach), which is what
# guarantees the title is always the bigger of the two on every box
# without the two having to be fit jointly.
MANEUVER_EFFECT_CEILING = 32
FONT_MANEUVER_TITLE = load_font(MANEUVER_EFFECT_CEILING + 1, bold=True)
MANEUVER_TITLE_LINE_HEIGHT = MANEUVER_EFFECT_CEILING + 1 + 6


def fit_maneuver_box_text(
    draw: ImageDraw.ImageDraw,
    name: str,
    effect: str,
    max_width: float,
    max_height: float,
    min_size: int = 10,
) -> FittedManeuverBox:
    """
    The name at the one fixed title size, and the largest effect size
    (down to a floor, never above `MANEUVER_EFFECT_CEILING`) whose
    wrapped effect text fits what the title leaves in a reference box
    -- searched per box, against one fixed box size all twelve share
    (see `render_maneuver_reference_image`), so Deflect's one
    line reads much larger than Double Team's paragraph rather than
    both sharing a size picked for the longer of the two.
    """
    name_lines = wrap_text(draw, name, FONT_MANEUVER_TITLE, max_width)
    effect_room = max_height - len(name_lines) * MANEUVER_TITLE_LINE_HEIGHT - 8

    size = MANEUVER_EFFECT_CEILING
    while size >= min_size:
        effect_font = load_font(size)
        effect_line_height = size + 6
        effect_lines = wrap_text(draw, effect, effect_font, max_width)
        if len(effect_lines) * effect_line_height <= effect_room:
            return FittedManeuverBox(
                name_lines, effect_lines, effect_font, effect_line_height,
            )
        size -= 1

    effect_font = load_font(min_size)
    return FittedManeuverBox(
        name_lines,
        wrap_text(draw, effect, effect_font, max_width),
        effect_font,
        min_size + 6,
    )


def png_bytes(image: Image.Image) -> BytesIO:
    """
    An image as the PNG every render hands back, flattened to RGB --
    Discord shows the alpha channel's transparency as a checkerboard,
    and nothing here is meant to be see-through.
    """
    output = BytesIO()
    image.convert("RGB").save(output, format="PNG")
    output.seek(0)
    return output


def draw_centered_text(
    draw: ImageDraw.ImageDraw,
    center_x: float,
    y: float,
    text: str,
    font: ImageFont.ImageFont,
    fill: str,
) -> None:
    width = draw.textlength(text, font=font)
    draw.text((center_x - width / 2, y), text, font=font, fill=fill)


def draw_dashed_line(
    draw: ImageDraw.ImageDraw,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    fill: str,
    width: int,
    dash_length: int = 22,
    gap_length: int = 16,
) -> None:
    total_length = hypot(x2 - x1, y2 - y1)
    if total_length == 0:
        return
    direction = ((x2 - x1) / total_length, (y2 - y1) / total_length)
    distance = 0.0
    drawing = True
    while distance < total_length:
        segment = dash_length if drawing else gap_length
        next_distance = min(distance + segment, total_length)
        if drawing:
            draw.line(
                (
                    x1 + direction[0] * distance,
                    y1 + direction[1] * distance,
                    x1 + direction[0] * next_distance,
                    y1 + direction[1] * next_distance,
                ),
                fill=fill,
                width=width,
            )
        distance = next_distance
        drawing = not drawing


def arrowhead_triangle(
    tip: tuple[float, float],
    direction: tuple[float, float],
    length: float,
    half_width: float,
) -> list[tuple[float, float]]:
    """
    The three points of an arrowhead triangle at `tip`, pointing along
    the unit vector `direction`: `length` back from the tip along that
    direction, `half_width` either side of it on the perpendicular.
    Shared by this function's own arrowhead and cards.py's
    draw_arrowhead, which draw the same triangle through two different
    drawing interfaces -- raw ImageDraw here, cards.Pen there.
    """
    dx, dy = direction
    back_x = tip[0] - dx * length
    back_y = tip[1] - dy * length
    perp_x, perp_y = -dy, dx
    left = (back_x + perp_x * half_width, back_y + perp_y * half_width)
    right = (back_x - perp_x * half_width, back_y - perp_y * half_width)
    return [tip, left, right]


def draw_arc_arrow(
    draw: ImageDraw.ImageDraw,
    center: tuple[int, int],
    radius: int,
    start_deg: float,
    end_deg: float,
    fill: str,
    width: int,
) -> None:
    cx, cy = center
    draw.arc(
        (cx - radius, cy - radius, cx + radius, cy + radius),
        start=start_deg,
        end=end_deg,
        fill=fill,
        width=width,
    )

    theta = radians(end_deg)
    tip = (cx + radius * cos(theta), cy + radius * sin(theta))
    tangent = (-sin(theta), cos(theta))
    draw.polygon(
        arrowhead_triangle(tip, tangent, length=34, half_width=20),
        fill=fill,
    )


def _maneuver_cycle_order(
    catalog: ManeuverCatalog,
    tier: str = MANEUVER_TIER_BASIC,
) -> list[tuple[ManeuverDefinition, bool]]:
    """
    Walk the single defeat cycle formed by one tier of the maneuver
    catalog, alternating offense/defense, starting from the lowest-rank
    offense maneuver. Returns (maneuver, is_offense) pairs in cycle
    order, matching the hexagon diagram's node order.

    **One tier at a time, and the two hexagons are the same shape.**
    Rank alone decides who beats whom (the author, 2026-08-18), so an
    gambit sits exactly where its basic counterpart does; the
    advanced diagram is the basic one with six names swapped. Walking
    both tiers at once would be walking two cycles laid on top of each
    other, which is not a hexagon.
    """
    offense = {m.rank: m for m in catalog.for_tier("offense", tier)}
    defense = {m.rank: m for m in catalog.for_tier("defense", tier)}
    start = offense[min(offense)]

    order: list[tuple[ManeuverDefinition, bool]] = [(start, True)]
    current, is_offense = start, True
    node_count = len(offense) + len(defense)
    for _ in range(node_count - 1):
        if is_offense:
            current = defense[current.defeats_rank]
            is_offense = False
        else:
            current = offense[current.defeats_rank]
            is_offense = True
        order.append((current, is_offense))
    return order


def draw_reference_ties(
    draw: ImageDraw.ImageDraw,
    centers: list[tuple[float, float]],
) -> None:
    """Tie diameters (opposite nodes), drawn first so the boxes sit on top."""
    half = len(centers) // 2
    near = MANEUVER_DIAGRAM_ARC_RADIUS + 40
    for index in range(half):
        start_x, start_y = centers[index]
        end_x, end_y = centers[index + half]
        length = hypot(end_x - start_x, end_y - start_y)
        ux, uy = (end_x - start_x) / length, (end_y - start_y) / length
        draw_dashed_line(
            draw,
            start_x + ux * near,
            start_y + uy * near,
            end_x - ux * near,
            end_y - uy * near,
            fill="#808080",
            width=5,
        )


def draw_reference_arrows(
    draw: ImageDraw.ImageDraw,
    center: tuple[float, float],
    angles: list[float],
) -> None:
    """The defeat cycle, an arc from each node round to the next."""
    node_count = len(angles)
    for index in range(node_count):
        start_angle = angles[index]
        end_angle = (
            angles[index + 1]
            if index + 1 < node_count
            else angles[0] + 360
        )
        draw_arc_arrow(
            draw,
            center,
            MANEUVER_DIAGRAM_ARC_RADIUS,
            start_angle,
            end_angle,
            fill="#808080",
            width=6,
        )


def draw_reference_box(
    draw: ImageDraw.ImageDraw,
    box_left: float,
    box_top: float,
    maneuver: ManeuverDefinition,
    fill: str,
    text_color: str,
) -> None:
    """One maneuver's box: its name at a fixed size, its effect fit under it."""
    box_width, box_height = MANEUVER_DIAGRAM_BOX_SIZE
    draw.rounded_rectangle(
        (box_left, box_top, box_left + box_width, box_top + box_height),
        radius=14,
        fill=fill,
        outline="#ffffff",
        width=2,
    )
    box_center_x = box_left + box_width / 2

    # No BASIC/ADVANCED tag any more -- the legend at the foot
    # of the image already carries that distinction (by
    # colour), so repeating it in words on every box was
    # spending a line for nothing. The title is one fixed size
    # on every box; the effect text is fit per box under it --
    # see fit_maneuver_box_text.
    fitted = fit_maneuver_box_text(
        draw, maneuver.name, maneuver.effect, box_width - 32, box_height - 24,
    )
    text_y = box_top + 12
    for line in fitted.name_lines:
        draw_centered_text(
            draw, box_center_x, text_y, line, FONT_MANEUVER_TITLE, text_color,
        )
        text_y += MANEUVER_TITLE_LINE_HEIGHT
    text_y += 8
    for line in fitted.effect_lines:
        draw_centered_text(
            draw, box_center_x, text_y, line, fitted.effect_font, text_color,
        )
        text_y += fitted.effect_line_height


def draw_reference_rank(
    draw: ImageDraw.ImageDraw,
    catalog: ManeuverCatalog,
    center: tuple[float, float],
    basic: ManeuverDefinition,
    is_offense: bool,
    both_tiers: bool,
) -> None:
    """
    One rank on the cycle: its badge, and the box for each card on it
    -- the basic card alone, or the basic beside its advanced
    counterpart.
    """
    center_x, center_y = center
    box_width, box_height = MANEUVER_DIAGRAM_BOX_SIZE
    group_width = (
        box_width * 2 + MANEUVER_DIAGRAM_TIER_GAP if both_tiers else box_width
    )
    pair_height = box_height + MANEUVER_DIAGRAM_RANK_LABEL_HEIGHT
    rank_letter = "O" if is_offense else "D"
    rank_color = (
        MANEUVER_OFFENSE_COLOR if is_offense else MANEUVER_DEFENSE_COLOR
    )

    pair_top = center_y - pair_height / 2
    pair_left = center_x - group_width / 2
    draw_centered_text(
        draw,
        center_x,
        pair_top,
        f"{rank_letter}{basic.rank}",
        FONT_MANEUVER_RANK,
        rank_color,
    )

    box_top = pair_top + MANEUVER_DIAGRAM_RANK_LABEL_HEIGHT
    boxes = [
        (
            basic,
            MANEUVER_OFFENSE_COLOR if is_offense else MANEUVER_DEFENSE_COLOR,
            MANEUVER_CARD_TEXT_COLOR,
        ),
    ]
    if both_tiers:
        advanced = catalog.counterpart(basic)
        boxes.append((
            advanced,
            MANEUVER_OFFENSE_COLOR_GAMBIT
            if is_offense
            else MANEUVER_DEFENSE_COLOR_GAMBIT,
            MANEUVER_CARD_TEXT_COLOR_GAMBIT,
        ))
    for offset, (maneuver, fill, text_color) in enumerate(boxes):
        box_left = pair_left + offset * (box_width + MANEUVER_DIAGRAM_TIER_GAP)
        draw_reference_box(draw, box_left, box_top, maneuver, fill, text_color)


def draw_reference_legend(draw: ImageDraw.ImageDraw, both_tiers: bool) -> None:
    """The colour swatches, and the two relations the lines draw."""
    legend_y = MANEUVER_DIAGRAM_HEIGHT - 96
    swatch_size = 30
    legend_x = 100

    def legend_swatch(fill: str, label: str) -> None:
        nonlocal legend_x
        draw.rounded_rectangle(
            (legend_x, legend_y, legend_x + swatch_size, legend_y + swatch_size),
            radius=6,
            fill=fill,
        )
        draw.text(
            (legend_x + swatch_size + 12, legend_y + 3),
            label,
            font=FONT_MANEUVER_LEGEND,
            fill="#ffffff",
        )
        legend_x += swatch_size + 12 + round(
            draw.textlength(label, font=FONT_MANEUVER_LEGEND)
        ) + 44

    if both_tiers:
        legend_swatch(MANEUVER_OFFENSE_COLOR, "Offense (basic)")
        legend_swatch(MANEUVER_OFFENSE_COLOR_GAMBIT, "Offense (gambit)")
        legend_swatch(MANEUVER_DEFENSE_COLOR, "Defense (basic)")
        legend_swatch(MANEUVER_DEFENSE_COLOR_GAMBIT, "Defense (gambit)")
    else:
        legend_swatch(MANEUVER_OFFENSE_COLOR, "Offense")
        legend_swatch(MANEUVER_DEFENSE_COLOR, "Defense")

    relation_y = MANEUVER_DIAGRAM_HEIGHT - 48
    relation_x = 100
    draw.line(
        (relation_x, relation_y + 15, relation_x + 100, relation_y + 15),
        fill="#808080", width=6,
    )
    draw.polygon(
        [
            (relation_x + 100, relation_y + 3),
            (relation_x + 100, relation_y + 27),
            (relation_x + 122, relation_y + 15),
        ],
        fill="#808080",
    )
    draw.text(
        (relation_x + 140, relation_y + 3),
        "Defeats",
        font=FONT_MANEUVER_LEGEND,
        fill="#ffffff",
    )
    tie_x = relation_x + 320
    draw_dashed_line(
        draw, tie_x, relation_y + 15, tie_x + 100, relation_y + 15,
        fill="#808080", width=5,
    )
    draw.text(
        (tie_x + 120, relation_y + 3),
        "Ties -- a skill test, or the rank's basic card if either side is injured"
        if both_tiers
        else "Ties -- a skill test",
        font=FONT_MANEUVER_LEGEND,
        fill="#ffffff",
    )


def render_maneuver_reference_image(
    catalog: ManeuverCatalog,
    tier: str = MANEUVER_TIER_GAMBIT,
) -> BytesIO:
    """
    Every maneuver arranged in the defeat cycle its rank sits on: arrows
    trace who beats whom, dashed diameters connect the tie pairs
    (opposite nodes), and each of the six rank positions carries one
    prominent rank badge (O1, D2, ...).

    **`tier` picks how many maneuvers a rank shows.**
    `MANEUVER_TIER_GAMBIT` (the default) draws both -- the basic card
    and its gambit side by side -- since rank alone
    decides who beats whom (2026-08-18), so a gambit sits
    exactly where its basic counterpart does and the two cannot be
    drawn as two unrelated cycles without implying a second rule that
    does not exist. `MANEUVER_TIER_BASIC` draws one box a rank instead:
    a basic-mode coach has no gambits to read a matchup for, so
    showing them anyway would be describing a rule this game is not
    playing by. The one box keeps the same shape it always had rather
    than stretching to the width the pair would have shared.
    """
    both_tiers = tier == MANEUVER_TIER_GAMBIT
    canvas = Image.new(
        "RGBA",
        (MANEUVER_DIAGRAM_WIDTH, MANEUVER_DIAGRAM_HEIGHT),
        "#111820",
    )
    draw = ImageDraw.Draw(canvas)
    cx, cy = MANEUVER_DIAGRAM_CENTER
    node_radius = MANEUVER_DIAGRAM_NODE_RADIUS

    order = _maneuver_cycle_order(catalog, MANEUVER_TIER_BASIC)
    node_count = len(order)
    angles = [270 + 360 * index / node_count for index in range(node_count)]
    centers = [
        (
            cx + node_radius * cos(radians(angle)),
            cy + node_radius * sin(radians(angle)),
        )
        for angle in angles
    ]

    draw_reference_ties(draw, centers)
    draw_reference_arrows(draw, (cx, cy), angles)
    for (basic, is_offense), center in zip(order, centers):
        draw_reference_rank(draw, catalog, center, basic, is_offense, both_tiers)
    draw_reference_legend(draw, both_tiers)

    return png_bytes(canvas)


def draw_jumbotron(
    draw: ImageDraw.ImageDraw,
    match: MatchState,
) -> None:
    draw.rounded_rectangle(
        (
            JUMBOTRON_LEFT,
            JUMBOTRON_TOP,
            JUMBOTRON_RIGHT,
            JUMBOTRON_BOTTOM,
        ),
        radius=22,
        fill="#161d26",
        outline="#c7d0da",
        width=5,
    )

    title_center = JUMBOTRON_LEFT + 225
    draw_centered_text(
        draw,
        title_center,
        JUMBOTRON_TOP + 48,
        "D12 BALL!",
        FONT_TITLE,
        "#ffffff",
    )

    match_left = JUMBOTRON_LEFT + 450
    match_right = JUMBOTRON_RIGHT - 480
    match_center = (match_left + match_right) / 2
    home_center = match_center - 320
    visiting_center = match_center + 320
    draw_centered_text(
        draw,
        home_center,
        JUMBOTRON_TOP + 20,
        team_display_name(match.home.team),
        FONT_HEADING,
        TEAM_COLORS[match.home.team],
    )
    draw_centered_text(
        draw,
        visiting_center,
        JUMBOTRON_TOP + 20,
        team_display_name(match.visiting.team),
        FONT_HEADING,
        TEAM_COLORS[match.visiting.team],
    )
    draw_centered_text(
        draw,
        match_center,
        JUMBOTRON_TOP + 66,
        (
            f"{match.scoreboard.home_score}  :  "
            f"{match.scoreboard.visiting_score}"
        ),
        FONT_SCORE,
        "#ffffff",
    )

    clock_center = JUMBOTRON_RIGHT - 240
    draw_centered_text(
        draw,
        clock_center,
        JUMBOTRON_TOP + 12,
        f"{match.scoreboard.time:02d}",
        FONT_SCORE,
        "#f5d76e",
    )
    period = (
        "First Half"
        if match.scoreboard.period == MatchPeriod.FIRST_HALF
        else "Second Half"
    )
    draw_centered_text(
        draw,
        clock_center,
        JUMBOTRON_TOP + 100,
        period,
        FONT_BODY,
        "#ffffff",
    )


def draw_team_board(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    setup: TeamSetup,
    players: dict[str, PlayerDefinition],
    catalog: PlayerCatalog,
    x: int,
    y: int,
    width: int,
    exhaustion: dict[str, int],
    exhausted: set[str] = frozenset(),
    injured: set[str] = frozenset(),
    cyborg_ids: frozenset[str] = frozenset(),
) -> None:
    color = TEAM_COLORS[setup.team]
    draw.rounded_rectangle(
        (x, y, x + width, TEAM_BOARD_BOTTOM),
        radius=18,
        fill="#202a35",
        outline=color,
        width=5,
    )
    name = team_display_name(setup.team)
    draw.text(
        (x + 22, y + 16),
        name,
        font=FONT_HEADING,
        fill=color,
    )

    # A name's own width decides where the bench starts -- "Purple" and
    # "Fire Demons" are not the same number of pixels, and a fixed
    # offset put the longer species names underneath "BENCH" instead of
    # beside it. TEAM_BOARD_BENCH_MIN_X is what a short name already
    # left in place, so nothing shifts for the common case.
    name_width = draw.textlength(name, font=FONT_HEADING)
    bench_x = x + max(
        TEAM_BOARD_BENCH_MIN_X,
        round(name_width) + 22 + TEAM_BOARD_NAME_GAP,
    )
    draw.text(
        (bench_x, y + 20),
        "BENCH",
        font=FONT_BODY,
        fill="#ffffff",
    )
    card_x = bench_x
    for player_id in setup.team_board.bench:
        player = players[player_id]
        draw_card(
            canvas,
            draw,
            player,
            catalog.effective_profile(player),
            card_x,
            y + 68,
            team=setup.team,
            exhaustion=exhaustion.get(player_id, 0),
            exhausted=player_id in exhausted,
            injured=player_id in injured,
            cyborg=player_id in cyborg_ids,
        )
        card_x += CARD_SIZE[0] + 14

    # Same reasoning as bench_x, from the other side: the bench itself
    # is up to three cards wide, and a bench pushed right by a long
    # name must clear its own cards before "BACK BENCH" starts.
    back_bench_x = max(
        x + TEAM_BOARD_BACK_BENCH_MIN_X,
        bench_x + TEAM_BOARD_BENCH_CARD_SPAN + TEAM_BOARD_SECTION_GAP,
    )
    draw.text(
        (back_bench_x, y + 20),
        "BACK BENCH",
        font=FONT_BODY,
        fill="#ffffff",
    )
    if not setup.team_board.back_bench:
        draw.text(
            (back_bench_x, y + 105),
            "Empty",
            font=FONT_BODY,
            fill="#9eabb8",
        )
    else:
        card_x = back_bench_x
        for player_id in setup.team_board.back_bench:
            player = players[player_id]
            draw_card(
                canvas,
                draw,
                player,
                catalog.effective_profile(player),
                card_x,
                y + 68,
                team=setup.team,
                exhaustion=exhaustion.get(player_id, 0),
                exhausted=player_id in exhausted,
                injured=player_id in injured,
                cyborg=player_id in cyborg_ids,
            )
            card_x += CARD_SIZE[0] + 14


def draw_coaching_space(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    players: dict[str, PlayerDefinition],
    team_players: set[str],
    team: Team,
    side: TeamSide,
    zone: Zone,
    space_index: int,
    occupants: list[str],
    space_left: int,
    space_right: int,
    board: Optional[BoardState] = None,
    species_icons: bool = False,
) -> None:
    """
    One space on a coach's own half: its frame and code, and that
    side's own meeples on it -- one row, not two, and no ball. A
    Coaching Choice happens with play stopped, and none of its four
    actions turns on where the ball is.
    """
    draw.rectangle(
        (
            space_left + 8,
            COACHING_BOARD_TOP + 46,
            space_right - 8,
            COACHING_BOARD_BOTTOM - 12,
        ),
        outline="#9aabbc",
        width=2,
    )
    draw.text(
        (space_left + 15, COACHING_BOARD_TOP + 52),
        space_code(zone, space_index, board),
        font=FONT_SMALL,
        fill="#c8d1dc",
    )

    draw_meeple_group(
        canvas,
        draw,
        [
            player_id
            for player_id in occupants
            if player_id in team_players
        ],
        players,
        team,
        space_left,
        space_right,
        COACHING_BOARD_TOP + 78,
        alignment="left" if side == TeamSide.HOME else "right",
        reserve_ball=False,
        label_bottom=COACHING_BOARD_BOTTOM - 14,
        species_icons=species_icons,
    )


def render_coaching_image(
    match: MatchState,
    catalog: PlayerCatalog,
    side: TeamSide,
    title: str,
    species_icons: bool = False,
    cyborg_ids: frozenset[str] = frozenset(),
) -> BytesIO:
    """
    One coach's own half of the field, for the
    [Coaching Choice](docs/living-rules.md) flow: the same board, cut
    horizontally through the middle so only that side's band of it is
    drawn, and only that side's meeples on it.

    Deliberately *not* mirrored. The zones keep their real names and
    the spaces their real numbers, left to right, so a coach reads the
    same field here as on the match image and on the board they are
    both looking at -- flipping it for the visiting coach would make
    "V1" the space on the right in one image and the left in the
    other.

    The ball is left off. Where it is has no bearing on any of the
    four actions, and a Coaching Choice happens with play stopped.
    """
    side = TeamSide(side)
    players = player_index(catalog)
    setup = match.setup_for_side(side)
    team_players = set(setup.field_players)

    canvas = Image.new(
        "RGBA",
        (COACHING_WIDTH, COACHING_HEIGHT),
        "#111820",
    )
    draw = ImageDraw.Draw(canvas)
    draw.text((COACHING_BOARD_LEFT, 16), title, font=FONT_HEADING, fill="#ffffff")
    draw_coaching_clock(draw, match)

    bounds = zone_bounds_between(
        match, COACHING_BOARD_LEFT, COACHING_BOARD_RIGHT,
    )
    draw.rounded_rectangle(
        (
            COACHING_BOARD_LEFT,
            COACHING_BOARD_TOP,
            COACHING_BOARD_RIGHT,
            COACHING_BOARD_BOTTOM,
        ),
        radius=18,
        fill="#14202b",
        outline="#d7dde5",
        width=4,
    )

    labels = zone_labels(match.board.layout.board_size)
    for zone in Zone:
        left, right = bounds[zone]
        draw.rectangle(
            (left, COACHING_BOARD_TOP, right, COACHING_BOARD_BOTTOM),
            fill=ZONE_COLORS[zone],
            outline="#d7dde5",
            width=3,
        )
        label_width = draw.textlength(
            labels[zone], font=FONT_COACHING_ZONE,
        )
        draw.text(
            (
                left + (right - left - label_width) / 2,
                COACHING_BOARD_TOP + 10,
            ),
            labels[zone],
            font=FONT_COACHING_ZONE,
            fill="#ffffff",
        )

        spaces = match.board.spaces[zone]
        space_width = (right - left) / len(spaces)
        for space_index, occupants in enumerate(spaces):
            space_left = round(left + space_index * space_width)
            space_right = round(left + (space_index + 1) * space_width)
            draw_coaching_space(
                canvas, draw, players, team_players, setup.team, side,
                zone, space_index, occupants, space_left, space_right,
                board=match.board, species_icons=species_icons,
            )

    draw_assignment_cards(
        canvas,
        draw,
        setup,
        players,
        catalog,
        bounds,
        COACHING_ZONE_CARDS_TOP,
        match.exhaustion,
        match.exhausted,
        match.injured,
        gap=COACHING_CARD_GAP,
        cyborg_ids=cyborg_ids,
    )
    draw_coaching_benches(
        canvas, draw, setup, players, catalog, match, cyborg_ids=cyborg_ids,
    )

    return png_bytes(canvas)


def draw_coaching_clock(
    draw: ImageDraw.ImageDraw,
    match: MatchState,
) -> None:
    """
    The clock, right-aligned in the title row: the minute in the
    jumbotron's yellow, the period beside it in white.

    **It reads the match's clock, and that is the minute the window
    opened on**, because nothing moves the clock while a window is
    open: a time out charges its minute in `finish_time_out`, after
    both coaches are done, and halftime puts the clock on 15 before
    either window opens. So every re-render of the half-field as the
    coach works shows the same minute, and no saved field is needed
    to remember it.
    """
    minute = f"{match.scoreboard.time:02d}"
    period = (
        "First Half"
        if match.scoreboard.period == MatchPeriod.FIRST_HALF
        else "Second Half"
    )
    minute_left = COACHING_BOARD_RIGHT - draw.textlength(
        minute, font=FONT_HEADING,
    )
    draw.text((minute_left, 16), minute, font=FONT_HEADING, fill="#f5d76e")
    # Baseline-matched to the minute: the body face is 8px shorter.
    period_left = minute_left - 16 - draw.textlength(period, font=FONT_BODY)
    draw.text((period_left, 24), period, font=FONT_BODY, fill="#ffffff")


def draw_coaching_benches(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    setup: TeamSetup,
    players: dict[str, PlayerDefinition],
    catalog: PlayerCatalog,
    match: MatchState,
    cyborg_ids: frozenset[str] = frozenset(),
) -> None:
    """
    The coach's two pools under the card rows. Which pool a player is
    in is the whole of who may come on -- the bench while it has
    anyone, the back bench once it has drained -- so a coach choosing
    a substitution needs to see both.
    """
    for left, label, player_ids in (
        (COACHING_BOARD_LEFT, "BENCH", setup.team_board.bench),
        (
            COACHING_BACK_BENCH_LEFT,
            "BACK BENCH",
            setup.team_board.back_bench,
        ),
    ):
        draw.text(
            (left, COACHING_BENCH_LABEL_TOP),
            label,
            font=FONT_BODY,
            fill="#ffffff",
        )
        if not player_ids:
            draw.text(
                (left, COACHING_BENCH_CARDS_TOP + 40),
                "Empty",
                font=FONT_BODY,
                fill="#9eabb8",
            )
            continue

        card_x = left
        for player_id in player_ids:
            player = players[player_id]
            draw_card(
                canvas,
                draw,
                player,
                catalog.effective_profile(player),
                card_x,
                COACHING_BENCH_CARDS_TOP,
                team=setup.team,
                exhaustion=match.exhaustion.get(player_id, 0),
                exhausted=player_id in match.exhausted,
                injured=player_id in match.injured,
                cyborg=player_id in cyborg_ids,
            )
            card_x += CARD_SIZE[0] + COACHING_CARD_GAP


def render_field_image(
    match: MatchState,
    catalog: PlayerCatalog,
    species_icons: bool = False,
) -> BytesIO:
    """
    The field on its own -- both sides' meeples, the ball, the space
    codes and the shooting range edges -- with none of the match image
    around it: no title, no jumbotron, no assignment cards, no team
    boards, no benches.

    It is a **crop of the match image's board**, not a second drawing
    of one: the canvas is the full match image's, `draw_board` puts the
    field where it always goes, and the board's own rectangle plus
    `FIELD_MARGIN` is cut out of it. So this cannot drift from the
    board both coaches are reading -- a change to a space, a meeple or
    the ball token reaches it without being made twice -- which is the
    whole point of an image whose job is to answer "where is everybody
    standing?" while a coach is looking at something else.

    Not upscaled, unlike the match image. `OUTPUT_SCALE` is there so a
    2200px board holds up when Discord's client blows it up; a strip a
    third of that height is shown at its own size or smaller, and the
    upscale would only be payload.
    """
    players = player_index(catalog)
    canvas = Image.new(
        "RGBA",
        (IMAGE_WIDTH, IMAGE_HEIGHT),
        "#111820",
    )
    draw = ImageDraw.Draw(canvas)
    draw_board(canvas, draw, match, players, species_icons=species_icons)

    field = canvas.crop(
        (
            BOARD_LEFT - FIELD_MARGIN,
            BOARD_TOP - FIELD_MARGIN,
            BOARD_RIGHT + FIELD_MARGIN,
            BOARD_BOTTOM + FIELD_MARGIN,
        )
    )

    return png_bytes(field)


def render_match_image(
    match: MatchState,
    catalog: PlayerCatalog,
    title: str | None = None,
    species_icons: bool = False,
    cyborg_ids: frozenset[str] = frozenset(),
) -> BytesIO:
    players = player_index(catalog)
    canvas = Image.new(
        "RGBA",
        (IMAGE_WIDTH, IMAGE_HEIGHT),
        "#111820",
    )
    draw = ImageDraw.Draw(canvas)

    if title is None:
        period = (
            "First Half"
            if match.scoreboard.period == MatchPeriod.FIRST_HALF
            else "Second Half"
        )
        title = (
            f"{team_display_name(match.home.team)} vs "
            f"{team_display_name(match.visiting.team)}, {period}"
        )
    title_width = draw.textlength(title, font=FONT_TITLE)
    draw.text(
        ((IMAGE_WIDTH - title_width) / 2, 18),
        title,
        font=FONT_TITLE,
        fill="#ffffff",
    )

    draw_jumbotron(draw, match)
    bounds = zone_bounds(match)
    draw_assignment_cards(
        canvas,
        draw,
        match.visiting,
        players,
        catalog,
        bounds,
        260,
        match.exhaustion,
        match.exhausted,
        match.injured,
        cyborg_ids=cyborg_ids,
    )
    draw_board(canvas, draw, match, players, species_icons=species_icons)
    draw_assignment_cards(
        canvas,
        draw,
        match.home,
        players,
        catalog,
        bounds,
        HOME_ASSIGNMENT_CARDS_TOP,
        match.exhaustion,
        match.exhausted,
        match.injured,
        cyborg_ids=cyborg_ids,
    )
    team_board_width = (
        FIELD_FAR_RIGHT - FIELD_FAR_LEFT - TEAM_BOARD_GAP
    ) // 2
    draw_team_board(
        canvas,
        draw,
        match.home,
        players,
        catalog,
        FIELD_FAR_LEFT,
        TEAM_BOARD_TOP,
        team_board_width,
        match.exhaustion,
        match.exhausted,
        match.injured,
        cyborg_ids=cyborg_ids,
    )
    draw_team_board(
        canvas,
        draw,
        match.visiting,
        players,
        catalog,
        FIELD_FAR_LEFT + team_board_width + TEAM_BOARD_GAP,
        TEAM_BOARD_TOP,
        team_board_width,
        match.exhaustion,
        match.exhausted,
        match.injured,
        cyborg_ids=cyborg_ids,
    )

    # BILINEAR here, not LANCZOS: this is a pure 1.5x upscale of an
    # already-antialiased raster (unlike the card build, which downscales
    # from a supersampled source and needs LANCZOS's quality), so the
    # cheaper filter costs no visible sharpness but is significantly
    # faster.
    return png_bytes(canvas.resize(OUTPUT_SIZE, Image.Resampling.BILINEAR))
