import logging
from dataclasses import dataclass
from io import BytesIO
from math import cos, hypot, pi, radians, sin
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from d12ball.components import (
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
from d12ball.game import Team


IMAGE_WIDTH = 2200
IMAGE_HEIGHT = 1280
OUTPUT_SCALE = 1.5
OUTPUT_SIZE = (
    round(IMAGE_WIDTH * OUTPUT_SCALE),
    round(IMAGE_HEIGHT * OUTPUT_SCALE),
)
BOARD_LEFT = 100
BOARD_RIGHT = IMAGE_WIDTH - 100
JUMBOTRON_LEFT = BOARD_LEFT
JUMBOTRON_RIGHT = BOARD_RIGHT
JUMBOTRON_TOP = 78
JUMBOTRON_BOTTOM = 238
BOARD_TOP = 430
BOARD_BOTTOM = 805
CARD_SIZE = (110, 154)
CARD_INTERNAL_SCALE = 3
CARD_INTERNAL_SIZE = (
    CARD_SIZE[0] * CARD_INTERNAL_SCALE,
    CARD_SIZE[1] * CARD_INTERNAL_SCALE,
)
CARD_OFFENSE_COLOR = "#dc143c"
CARD_DEFENSE_COLOR = "#0f7a35"
PLAYER_BOARD_TOP = 1030
PLAYER_BOARD_BOTTOM = IMAGE_HEIGHT - 25
PLAYER_BOARD_GAP = 30

TEAM_COLORS = {
    Team.ORANGE: "#f28c28",
    Team.TEAL: "#19b5a5",
    Team.PURPLE: "#8950c7",
    Team.SLIME: "#75bd32",
}
ZONE_COLORS = {
    Zone.HOME_GOAL: "#3b4859",
    Zone.MIDFIELD: "#46554e",
    Zone.VISITORS_GOAL: "#5b4d46",
}
ZONE_LABELS = {
    Zone.HOME_GOAL: "HOME GOAL",
    Zone.MIDFIELD: "MIDFIELD",
    Zone.VISITORS_GOAL: "VISITORS GOAL",
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


FONT_TITLE = load_font(50, bold=True)
FONT_HEADING = load_font(40, bold=True)
FONT_BODY = load_font(32)
FONT_SMALL = load_font(19)
FONT_MEEPLE = load_font(27, bold=True)
FONT_TOKEN = load_font(19, bold=True)
FONT_BADGE_COUNT = load_font(16, bold=True)
FONT_MANEUVER_TITLE = load_font(30, bold=True)
FONT_MANEUVER_BODY = load_font(22)
FONT_MANEUVER_LEGEND = load_font(22)
FONT_DICE_TOTAL = load_font(28, bold=True)
FONT_DICE_VALUE = load_font(26, bold=True)
# The one line on a matchup image that is a sum rather than a fact
# about a player -- see group_text_lines.
FONT_CHALLENGE_TOTAL = load_font(23, bold=True)
FONT_SCORE = load_font(64, bold=True)
FONT_CARD_STAT = load_font(46, bold=True)
FONT_CARD_ROLE = load_font(46, bold=True)
CARD_NAME_MIN_SIZE = 28
CARD_NAME_MAX_SIZE = 60
_CARD_NAME_FONT_CACHE: dict[int, ImageFont.ImageFont] = {}
# Meeple names are sized per space, not once for the board: see
# fit_meeple_labels.
MEEPLE_LABEL_MIN_SIZE = 14
MEEPLE_LABEL_MAX_SIZE = 27
MEEPLE_LABEL_LINE_GAP = 3
_MEEPLE_LABEL_FONT_CACHE: dict[int, ImageFont.ImageFont] = {}
MEEPLE_SIZE = 56
BALL_RADIUS = 27

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
_EXHAUST_ICON_CACHE: Optional[Image.Image] = None
_EXHAUST_ICON_LOAD_ATTEMPTED = False

EXHAUSTED_ICON_PATH = (
    Path(__file__).resolve().parent / "images" / "emoji" / "exhausted.png"
)
EXHAUSTED_ICON_SIZE = 26
_EXHAUSTED_ICON_CACHE: Optional[Image.Image] = None
_EXHAUSTED_ICON_LOAD_ATTEMPTED = False

INJURED_ICON_PATH = (
    Path(__file__).resolve().parent / "images" / "emoji" / "injured.png"
)
INJURED_ICON_SIZE = 26
_INJURED_ICON_CACHE: Optional[Image.Image] = None
_INJURED_ICON_LOAD_ATTEMPTED = False

PLAYER_IMAGES_DIR = Path(__file__).resolve().parent / "images" / "player_images"
_PLAYER_PORTRAIT_CACHE: dict[str, Optional[Image.Image]] = {}


def load_exhaust_icon() -> Optional[Image.Image]:
    """
    Load (and cache) the exhaustion token icon. Returns None if the image
    is not available so rendering can gracefully skip it.
    """
    global _EXHAUST_ICON_CACHE, _EXHAUST_ICON_LOAD_ATTEMPTED

    if _EXHAUST_ICON_LOAD_ATTEMPTED:
        return _EXHAUST_ICON_CACHE

    _EXHAUST_ICON_LOAD_ATTEMPTED = True
    try:
        with Image.open(EXHAUST_ICON_PATH) as source:
            icon = source.convert("RGBA")
            icon.thumbnail(
                (EXHAUST_ICON_SIZE, EXHAUST_ICON_SIZE),
                Image.Resampling.LANCZOS,
            )
            _EXHAUST_ICON_CACHE = icon
    except OSError:
        _EXHAUST_ICON_CACHE = None

    return _EXHAUST_ICON_CACHE


def load_exhausted_icon() -> Optional[Image.Image]:
    """
    Load (and cache) the exhausted-condition icon. Returns None if the
    image is not available so rendering can gracefully skip it.
    """
    global _EXHAUSTED_ICON_CACHE, _EXHAUSTED_ICON_LOAD_ATTEMPTED

    if _EXHAUSTED_ICON_LOAD_ATTEMPTED:
        return _EXHAUSTED_ICON_CACHE

    _EXHAUSTED_ICON_LOAD_ATTEMPTED = True
    try:
        with Image.open(EXHAUSTED_ICON_PATH) as source:
            icon = source.convert("RGBA")
            icon.thumbnail(
                (EXHAUSTED_ICON_SIZE, EXHAUSTED_ICON_SIZE),
                Image.Resampling.LANCZOS,
            )
            _EXHAUSTED_ICON_CACHE = icon
    except OSError:
        _EXHAUSTED_ICON_CACHE = None

    return _EXHAUSTED_ICON_CACHE


def load_injured_icon() -> Optional[Image.Image]:
    """
    Load (and cache) the injured-condition icon. Returns None if the
    image is not available so rendering can gracefully skip it.
    """
    global _INJURED_ICON_CACHE, _INJURED_ICON_LOAD_ATTEMPTED

    if _INJURED_ICON_LOAD_ATTEMPTED:
        return _INJURED_ICON_CACHE

    _INJURED_ICON_LOAD_ATTEMPTED = True
    try:
        with Image.open(INJURED_ICON_PATH) as source:
            icon = source.convert("RGBA")
            icon.thumbnail(
                (INJURED_ICON_SIZE, INJURED_ICON_SIZE),
                Image.Resampling.LANCZOS,
            )
            _INJURED_ICON_CACHE = icon
    except OSError:
        _INJURED_ICON_CACHE = None

    return _INJURED_ICON_CACHE


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
    draw.text(
        (
            (width - role_width) / 2,
            name_zone_height
            + (stats_row_height - role_height) / 2
            - role_bbox[1],
        ),
        role_label,
        font=FONT_CARD_ROLE,
        fill="#111111",
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
    return {
        player.player_id: player
        for roster in catalog.teams.values()
        for player in roster.players
    }


def zone_bounds(match: MatchState) -> dict[Zone, tuple[int, int]]:
    space_width = (
        BOARD_RIGHT - BOARD_LEFT
    ) / match.board.layout.board_size
    bounds: dict[Zone, tuple[int, int]] = {}
    cursor = BOARD_LEFT

    for zone in Zone:
        width = match.board.layout.zone_spaces[zone] * space_width
        right = round(cursor + width)
        bounds[zone] = (round(cursor), right)
        cursor += width

    return bounds


def draw_card(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    player: PlayerDefinition,
    profile: RoleProfile,
    x: int,
    y: int,
    exhaustion: int = 0,
    exhausted: bool = False,
    injured: bool = False,
) -> None:
    card, row_top, row_bottom = rendered_player_card(player, profile)

    border = TEAM_COLORS[player.team]
    draw.rounded_rectangle(
        (x - 3, y - 3, x + CARD_SIZE[0] + 3, y + CARD_SIZE[1] + 3),
        radius=7,
        fill=border,
    )
    canvas.alpha_composite(card, (x, y))

    if exhaustion > 0:
        draw_exhaustion_badge(
            canvas, draw, x, y, exhaustion, player, profile, row_top, row_bottom
        )
    # Injured and Exhausted share the same slot on the stats row: a
    # player who becomes injured loses the Exhausted condition (and
    # every token with it), so the two badges can never be drawn at
    # once. The injured badge used to sit in the card's top-left
    # corner, over the name.
    if injured:
        draw_injured_badge(canvas, draw, x, y, row_top, row_bottom)
    if exhausted:
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
) -> None:
    """
    Draws the exhaust-token badge between the skill numbers and the role
    acronym, on the same row as the role, rather than over the portrait.
    The gap between those two is narrower than the icon on some cards, so
    the horizontal center is computed per-card (from the actual offense
    digit width and role label width) to keep the overlap as small as
    possible instead of guessing a fixed position.
    """
    icon = load_exhaust_icon()

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
) -> None:
    for zone in Zone:
        left, right = bounds[zone]
        player_ids = setup.zones[zone]
        total_width = len(player_ids) * CARD_SIZE[0] + (
            len(player_ids) - 1
        ) * 12
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
                exhaustion=exhaustion.get(player_id, 0),
                exhausted=player_id in exhausted,
                injured=player_id in injured,
            )
            x += CARD_SIZE[0] + 12


def draw_board(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    match: MatchState,
    players: dict[str, PlayerDefinition],
) -> dict[Zone, tuple[int, int]]:
    bounds = zone_bounds(match)
    draw.rounded_rectangle(
        (BOARD_LEFT, BOARD_TOP, BOARD_RIGHT, BOARD_BOTTOM),
        radius=18,
        fill="#14202b",
        outline="#d7dde5",
        width=4,
    )

    for zone in Zone:
        left, right = bounds[zone]
        draw.rectangle(
            (left, BOARD_TOP, right, BOARD_BOTTOM),
            fill=ZONE_COLORS[zone],
            outline="#d7dde5",
            width=3,
        )
        label_width = draw.textlength(ZONE_LABELS[zone], font=FONT_HEADING)
        draw.text(
            (
                left + (right - left - label_width) / 2,
                BOARD_TOP + 14,
            ),
            ZONE_LABELS[zone],
            font=FONT_HEADING,
            fill="#ffffff",
        )

        spaces = match.board.spaces[zone]
        space_width = (right - left) / len(spaces)
        for space_index, occupants in enumerate(spaces):
            space_left = round(left + space_index * space_width)
            space_right = round(left + (space_index + 1) * space_width)
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
            zone_letter = {
                Zone.HOME_GOAL: "H",
                Zone.MIDFIELD: "M",
                Zone.VISITORS_GOAL: "V",
            }[zone]
            draw.text(
                (space_left + 15, BOARD_TOP + 66),
                f"{zone_letter}{space_index + 1}",
                font=FONT_SMALL,
                fill="#c8d1dc",
            )

            visiting_occupants = [
                player_id
                for player_id in occupants
                if players[player_id].team == match.visiting.team
            ]
            home_occupants = [
                player_id
                for player_id in occupants
                if players[player_id].team == match.home.team
            ]
            ball_is_here = (
                match.ball.zone == zone
                and match.ball.space_index == space_index
            )
            visiting_bounds = draw_meeple_group(
                draw,
                visiting_occupants,
                players,
                space_left,
                space_right,
                BOARD_TOP + 88,
                alignment="right",
                reserve_ball=(
                    ball_is_here
                    and match.ball.possession.value == "visiting"
                ),
                # Stop above the home side's own tokens.
                label_bottom=BOARD_BOTTOM - 145,
            )
            home_bounds = draw_meeple_group(
                draw,
                home_occupants,
                players,
                space_left,
                space_right,
                BOARD_BOTTOM - 135,
                alignment="left",
                reserve_ball=(
                    ball_is_here
                    and match.ball.possession.value == "home"
                ),
                label_bottom=BOARD_BOTTOM - 16,
            )

            if ball_is_here:
                if match.ball.possession.value == "home":
                    ball_x = home_bounds[1] + BALL_RADIUS + 3
                    ball_y = BOARD_BOTTOM - 135 + MEEPLE_SIZE // 2
                else:
                    ball_x = visiting_bounds[0] - BALL_RADIUS - 3
                    ball_y = BOARD_TOP + 88 + MEEPLE_SIZE // 2
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

    draw_half_boundaries(draw, match, bounds)
    return bounds


def draw_half_boundaries(
    draw: ImageDraw.ImageDraw,
    match: MatchState,
    bounds: dict[Zone, tuple[int, int]],
) -> None:
    """
    The halfway line, dashed down the field, because where a team may
    shoot from now depends on it -- see "Halves" in the living rules.

    It never falls on a zone boundary: on every board size the field
    splits somewhere inside midfield. An odd-sized board has a middle
    space that is in neither half, so it gets two lines, one either
    side of that space, rather than one drawn through it.
    """
    def half(index: int) -> int:
        if match.board.is_in_attacking_half(TeamSide.HOME, index):
            return 1
        if match.board.is_in_attacking_half(TeamSide.VISITING, index):
            return -1
        return 0

    for index in range(1, match.board.layout.board_size):
        if half(index) == half(index - 1):
            continue

        zone, space_index = match.board.position_at_flat_index(index)
        left, right = bounds[zone]
        space_width = (right - left) / len(match.board.spaces[zone])
        x = round(left + space_index * space_width)

        y = BOARD_TOP + 50
        while y < BOARD_BOTTOM - 4:
            draw.line(
                (x, y, x, min(y + 16, BOARD_BOTTOM - 4)),
                fill="#f2f6fa",
                width=3,
            )
            y += 30


def draw_meeple_group(
    draw: ImageDraw.ImageDraw,
    occupants: list[str],
    players: dict[str, PlayerDefinition],
    space_left: int,
    space_right: int,
    token_y: int,
    alignment: str,
    reserve_ball: bool,
    label_bottom: int,
) -> tuple[int, int]:
    """
    One team's meeples on one space: a row of tokens, with their names
    listed under them, one per line.

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

    for player_index, player_id in enumerate(occupants):
        player = players[player_id]
        color = TEAM_COLORS[player.team]
        draw.ellipse(
            (
                token_x,
                token_y,
                token_x + token_size,
                token_y + token_size,
            ),
            fill=color,
            outline="#ffffff",
            width=4,
        )
        initials = ROLE_INITIALS[player.role.value]
        initials_width = draw.textlength(initials, font=FONT_TOKEN)
        draw.text(
            (
                token_x + (token_size - initials_width) / 2,
                token_y + 16,
            ),
            initials,
            font=FONT_TOKEN,
            fill="#ffffff",
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


SKILL_TEST_CELL_WIDTH = 230
SKILL_TEST_DIE_RADIUS = 36
SKILL_TEST_CENTER_Y = SKILL_TEST_DIE_RADIUS + 20
SKILL_TEST_LABEL_GAP = 10
SKILL_TEST_DETAIL_LINE_HEIGHT = 22
SKILL_TEST_DETAIL_TOP_GAP = 34
SKILL_TEST_TOTAL_GAP = 10
SKILL_TEST_TOTAL_LINE_HEIGHT = 32
SKILL_TEST_BOTTOM_PADDING = 12


def render_skill_test_dice(
    dice: list[tuple[int, str, str, list[str], int]],
) -> BytesIO:
    """
    Render one or more d12 results side by side, each annotated with the
    team, the player(s) behind that side of the roll, the skill and
    modifiers that built the total, and the total itself -- used for
    skill tests and score (shooting) attempts, where a bare
    team-colored die isn't enough to show who rolled it, why, or what
    it added up to.

    Each entry is (rolled value, team color, team label, detail lines,
    total), where detail lines are pre-formatted strings -- player name
    and role, skill applied, any other modifiers -- stacked one per
    line under the team label, and total is the final modified result,
    drawn large underneath so the number that actually decided the
    roll doesn't require reading the accompanying message.
    """
    max_lines = max((len(detail) for _, _, _, detail, _ in dice), default=0)
    detail_block_height = max_lines * SKILL_TEST_DETAIL_LINE_HEIGHT
    total_y = (
        SKILL_TEST_CENTER_Y + SKILL_TEST_DIE_RADIUS + SKILL_TEST_DETAIL_TOP_GAP
        + detail_block_height + SKILL_TEST_TOTAL_GAP
    )
    height = total_y + SKILL_TEST_TOTAL_LINE_HEIGHT + SKILL_TEST_BOTTOM_PADDING
    width = SKILL_TEST_CELL_WIDTH * len(dice)
    canvas = Image.new("RGBA", (width, height), "#111820")
    draw = ImageDraw.Draw(canvas)
    center_y = SKILL_TEST_CENTER_Y

    for index, (value, color, label, detail_lines, total) in enumerate(dice):
        center_x = index * SKILL_TEST_CELL_WIDTH + SKILL_TEST_CELL_WIDTH // 2
        draw_d12_polygon(
            draw,
            center_x,
            center_y,
            SKILL_TEST_DIE_RADIUS,
            color,
            str(value),
            font=FONT_DICE_VALUE,
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

        # Aligned on max_lines rather than this entry's own line count,
        # so the totals line up across dice even when one side has more
        # modifiers listed than the other.
        total_label = f"= {total}"
        total_width = draw.textlength(total_label, font=FONT_DICE_TOTAL)
        draw.text(
            (center_x - total_width / 2, total_y),
            total_label,
            font=FONT_DICE_TOTAL,
            fill=color,
        )

    output = BytesIO()
    canvas.convert("RGB").save(output, format="PNG")
    output.seek(0)
    return output


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


def render_injury_test_die(
    value: int,
    color: str,
    team_label: str,
    player_name: str,
    safe: bool,
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
    """
    verdict = "SAFE" if safe else "INJURED"
    verdict_color = (
        INJURY_TEST_SAFE_COLOR if safe else INJURY_TEST_INJURED_COLOR
    )

    # Measured on a throwaway canvas: the real one can't be created
    # until these widths have decided how big it needs to be.
    measure = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    portrait = load_player_portrait(player_name)
    portrait_width = INJURY_TEST_PORTRAIT_SIZE
    portrait_height = INJURY_TEST_PORTRAIT_SIZE
    if portrait is not None:
        sized = portrait.copy()
        sized.thumbnail(
            (INJURY_TEST_PORTRAIT_SIZE, INJURY_TEST_PORTRAIT_SIZE),
            Image.Resampling.LANCZOS,
        )
        portrait_width, portrait_height = sized.size
    else:
        sized = None

    die_column = max(
        2 * INJURY_TEST_DIE_RADIUS,
        measure.textlength(team_label, font=FONT_SMALL),
    )
    portrait_column = max(
        portrait_width,
        measure.textlength(player_name, font=FONT_SMALL),
    )
    verdict_bbox = measure.textbbox((0, 0), verdict, font=FONT_DICE_TOTAL)
    verdict_column = verdict_bbox[2] - verdict_bbox[0]

    row_height = max(
        2 * INJURY_TEST_DIE_RADIUS,
        portrait_height,
    ) + INJURY_TEST_LABEL_GAP + INJURY_TEST_LABEL_HEIGHT
    width = round(
        INJURY_TEST_SIDE_PADDING * 2
        + die_column
        + portrait_column
        + verdict_column
        + INJURY_TEST_COLUMN_GAP * 2
    )
    height = INJURY_TEST_ROW_TOP + row_height + INJURY_TEST_BOTTOM_PADDING

    canvas = Image.new("RGBA", (width, height), "#111820")
    draw = ImageDraw.Draw(canvas)

    title_width = draw.textlength(INJURY_TEST_TITLE, font=FONT_DICE_TOTAL)
    draw.text(
        ((width - title_width) / 2, INJURY_TEST_TITLE_TOP),
        INJURY_TEST_TITLE,
        font=FONT_DICE_TOTAL,
        fill="#ffffff",
    )

    # Each column is centered on its own share of the row, and the
    # labels under the die and the portrait share a baseline so the
    # team name and the player's name read as one line.
    label_y = (
        INJURY_TEST_ROW_TOP
        + row_height
        - INJURY_TEST_LABEL_HEIGHT
    )
    content_center_y = (
        INJURY_TEST_ROW_TOP
        + (row_height - INJURY_TEST_LABEL_GAP - INJURY_TEST_LABEL_HEIGHT) / 2
    )

    die_center_x = INJURY_TEST_SIDE_PADDING + die_column / 2
    draw_d12_polygon(
        draw,
        round(die_center_x),
        round(content_center_y),
        INJURY_TEST_DIE_RADIUS,
        color,
        str(value),
        font=FONT_DICE_VALUE,
    )
    team_width = draw.textlength(team_label, font=FONT_SMALL)
    draw.text(
        (die_center_x - team_width / 2, label_y),
        team_label,
        font=FONT_SMALL,
        fill="#c7ced6",
    )

    portrait_center_x = (
        INJURY_TEST_SIDE_PADDING
        + die_column
        + INJURY_TEST_COLUMN_GAP
        + portrait_column / 2
    )
    if sized is not None:
        canvas.alpha_composite(
            sized,
            (
                round(portrait_center_x - sized.width / 2),
                round(content_center_y - sized.height / 2),
            ),
        )
    name_width = draw.textlength(player_name, font=FONT_SMALL)
    draw.text(
        (portrait_center_x - name_width / 2, label_y),
        player_name,
        font=FONT_SMALL,
        fill="#ffffff",
    )

    verdict_center_x = (
        INJURY_TEST_SIDE_PADDING
        + die_column
        + portrait_column
        + INJURY_TEST_COLUMN_GAP * 2
        + verdict_column / 2
    )
    draw.text(
        (
            verdict_center_x - verdict_column / 2 - verdict_bbox[0],
            content_center_y
            - (verdict_bbox[3] - verdict_bbox[1]) / 2
            - verdict_bbox[1],
        ),
        verdict,
        font=FONT_DICE_TOTAL,
        fill=verdict_color,
    )

    output = BytesIO()
    canvas.convert("RGB").save(output, format="PNG")
    output.seek(0)
    return output


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
    center_y = OWN_GOAL_TOP_PADDING + mark_radius
    outcome_y = center_y + mark_radius + OWN_GOAL_OUTCOME_GAP
    height = round(outcome_y + outcome_height + OWN_GOAL_BOTTOM_PADDING)
    width = round(
        max(
            OWN_GOAL_CELL_WIDTH * len(rolls),
            outcome_width + OWN_GOAL_SIDE_PADDING * 2,
        )
    )

    canvas = Image.new("RGBA", (width, height), "#111820")
    draw = ImageDraw.Draw(canvas)

    taken = max(rolls)
    dice_left = (width - OWN_GOAL_CELL_WIDTH * len(rolls)) / 2

    for index, value in enumerate(rolls):
        center_x = round(
            dice_left
            + index * OWN_GOAL_CELL_WIDTH
            + OWN_GOAL_CELL_WIDTH / 2
        )
        counted = value == taken
        draw_d12_polygon(
            draw,
            center_x,
            center_y,
            OWN_GOAL_DIE_RADIUS,
            color if counted else OWN_GOAL_DROPPED_COLOR,
            str(value),
            font=FONT_DICE_VALUE,
            outline=(
                "#ffffff" if counted else OWN_GOAL_DROPPED_OUTLINE
            ),
            text_color=(
                "#ffffff" if counted else OWN_GOAL_DROPPED_TEXT
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

    output = BytesIO()
    canvas.convert("RGB").save(output, format="PNG")
    output.seek(0)
    return output


CHALLENGE_TITLE = "MANEUVER CHALLENGE"
SCORE_ATTEMPT_TITLE = "SCORE ATTEMPT"
SCORE_ATTEMPT_UNDEFENDED = "No one in the way"
# A group's text is wrapped to its own width, which grows with what it
# has to say and is held between these. The minimum is what a lone
# player's block has always been drawn at; the maximum is where a line
# of names stops fitting a Discord message legibly and starts wrapping
# instead.
CHALLENGE_MIN_GROUP_WIDTH = 300
CHALLENGE_MAX_GROUP_WIDTH = 560
# The same size the injury test draws a portrait at, which is the only
# other image that shows one beside a caption. It is a step up from the
# diameter of a skill test's dice, where this started: the abbreviated
# abilities freed the height, and a portrait is what a coach picks a
# player out by.
CHALLENGE_PORTRAIT_SIZE = INJURY_TEST_PORTRAIT_SIZE
CHALLENGE_PORTRAIT_SPACING = 10
CHALLENGE_GUTTER = 64
CHALLENGE_TITLE_TOP = 14
CHALLENGE_LOCATION_TOP = 46
CHALLENGE_PORTRAIT_TOP = 82
CHALLENGE_PORTRAIT_GAP = 12
CHALLENGE_LINE_HEIGHT = 24
CHALLENGE_ABILITY_GAP = 8
CHALLENGE_ABILITY_LINE_HEIGHT = 21
CHALLENGE_TEXT_PADDING = 14
CHALLENGE_BOTTOM_PADDING = 16
CHALLENGE_VERSUS_TEXT = "vs"
CHALLENGE_VERSUS_COLOR = "#8b96a2"
CHALLENGE_NAME_COLOR = "#ffffff"
CHALLENGE_SKILL_COLOR = "#c7ced6"
CHALLENGE_ABILITY_COLOR = "#9aa5b1"
CHALLENGE_TOTAL_COLOR = "#ffffff"
CHALLENGE_TOTAL_LINE_HEIGHT = 30


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
    """

    name: str
    role: str
    team_color: str
    team_label: str
    skill_name: str
    skill: int
    ability: str
    modifiers: tuple[str, ...] = ()


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
    a line, and their skills added up, because that sum is the only
    number the roll uses and nobody is choosing between them. The sum
    is set bold and a size up for that reason -- it is the one line
    here that is a result rather than a fact about a player, and it is
    what the shot is actually up against.
    """
    if not sides:
        return []

    sized = [
        (
            sides[0].team_label,
            sides[0].team_color,
            FONT_SMALL,
            CHALLENGE_LINE_HEIGHT,
        ),
        (
            join_names([f"{side.name} [{side.role}]" for side in sides]),
            CHALLENGE_NAME_COLOR,
            FONT_SMALL,
            CHALLENGE_LINE_HEIGHT,
        ),
    ]

    skill_name = sides[0].skill_name
    if len(sides) == 1:
        sized.append(
            (
                f"{skill_name} skill +{sides[0].skill}",
                CHALLENGE_SKILL_COLOR,
                FONT_SMALL,
                CHALLENGE_LINE_HEIGHT,
            ),
        )
        sized.extend(
            (modifier, CHALLENGE_SKILL_COLOR, FONT_SMALL, CHALLENGE_LINE_HEIGHT)
            for modifier in sides[0].modifiers
        )
    else:
        skills = " + ".join(str(side.skill) for side in sides)
        total = sum(side.skill for side in sides)
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
        sized.append(("", CHALLENGE_ABILITY_COLOR, FONT_SMALL, CHALLENGE_ABILITY_GAP))
        sized.append(
            (
                sides[0].ability,
                CHALLENGE_ABILITY_COLOR,
                FONT_SMALL,
                CHALLENGE_ABILITY_LINE_HEIGHT,
            ),
        )
    return sized


def render_matchup(
    title: str,
    location: str,
    attacking: list[ChallengeSide],
    defending: list[ChallengeSide],
    defending_note: str = "",
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

    Both images replace prose that named the same players and said
    nothing about them: what a coach needs in front of them is the
    other side's skills and abilities, which the board shows only as
    numbers on a card too small to read the ability off.
    """
    # Measured on a throwaway canvas: how wide each group wants to be,
    # and how many lines its text wraps to at that width, decide the
    # size of the real one.
    measure = ImageDraw.Draw(Image.new("RGBA", (1, 1)))

    def group_width(sides: list[ChallengeSide], note: str, ability: bool) -> int:
        """
        Wide enough for the portraits, and for the text up to the point
        where wrapping it is better than growing.
        """
        portraits = (
            len(sides) * CHALLENGE_PORTRAIT_SIZE
            + max(len(sides) - 1, 0) * CHALLENGE_PORTRAIT_SPACING
        )
        # The ability is left out of this: it is a sentence, and sizing
        # a group to fit one on a line would make the image unreadably
        # wide. It wraps to whatever the rest of the group settles on.
        texts = [
            (text, font)
            for text, _, font, _ in group_text_lines(sides, False)
        ]
        if not sides and note:
            texts = [(note, FONT_SMALL)]
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

    attacking_width = group_width(attacking, "", True)
    defending_width = group_width(
        defending, defending_note, defending_abilities,
    )

    def wrapped(
        sides: list[ChallengeSide],
        note: str,
        ability: bool,
        width: int,
    ) -> list[tuple[str, str, ImageFont.ImageFont, int]]:
        if not sides:
            return (
                [(note, CHALLENGE_SKILL_COLOR, FONT_SMALL, CHALLENGE_LINE_HEIGHT)]
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

    attacking_lines = wrapped(attacking, "", True, attacking_width)
    defending_lines = wrapped(
        defending, defending_note, defending_abilities, defending_width,
    )

    text_top = (
        CHALLENGE_PORTRAIT_TOP
        + CHALLENGE_PORTRAIT_SIZE
        + CHALLENGE_PORTRAIT_GAP
    )
    body_bottom = text_top + max(
        sum(line_height for _, _, _, line_height in lines)
        for lines in (attacking_lines, defending_lines)
    )
    height = round(body_bottom + CHALLENGE_BOTTOM_PADDING)
    width = attacking_width + CHALLENGE_GUTTER + defending_width

    canvas = Image.new("RGBA", (width, height), "#111820")
    draw = ImageDraw.Draw(canvas)

    draw_centered_text(
        draw, width / 2, CHALLENGE_TITLE_TOP, title, FONT_DICE_TOTAL, "#ffffff",
    )
    draw_centered_text(
        draw, width / 2, CHALLENGE_LOCATION_TOP, location, FONT_SMALL,
        CHALLENGE_SKILL_COLOR,
    )
    draw_centered_text(
        draw,
        attacking_width + CHALLENGE_GUTTER / 2,
        CHALLENGE_PORTRAIT_TOP + CHALLENGE_PORTRAIT_SIZE / 2 - 14,
        CHALLENGE_VERSUS_TEXT,
        FONT_DICE_TOTAL,
        CHALLENGE_VERSUS_COLOR,
    )

    def draw_group(
        left: int,
        group_width_px: int,
        sides: list[ChallengeSide],
        lines: list[tuple[str, str, ImageFont.ImageFont, int]],
    ) -> None:
        center_x = left + group_width_px / 2
        strip = (
            len(sides) * CHALLENGE_PORTRAIT_SIZE
            + max(len(sides) - 1, 0) * CHALLENGE_PORTRAIT_SPACING
        )
        portrait_x = center_x - strip / 2
        for side in sides:
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
                            CHALLENGE_PORTRAIT_TOP
                            + (CHALLENGE_PORTRAIT_SIZE - sized.height) / 2
                        ),
                    ),
                )
            portrait_x += CHALLENGE_PORTRAIT_SIZE + CHALLENGE_PORTRAIT_SPACING

        y = text_top
        for text, color, font, line_height in lines:
            draw_centered_text(draw, center_x, y, text, font, color)
            y += line_height

    draw_group(0, attacking_width, attacking, attacking_lines)
    draw_group(
        attacking_width + CHALLENGE_GUTTER,
        defending_width,
        defending,
        defending_lines,
    )

    output = BytesIO()
    canvas.convert("RGB").save(output, format="PNG")
    output.seek(0)
    return output


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
        defending_abilities=False,
    )


MANEUVER_DIAGRAM_WIDTH = 1360
MANEUVER_DIAGRAM_HEIGHT = 1410
MANEUVER_DIAGRAM_CENTER = (680, 680)
MANEUVER_DIAGRAM_NODE_RADIUS = 450
MANEUVER_DIAGRAM_ARC_RADIUS = 180
MANEUVER_DIAGRAM_BOX_SIZE = (340, 300)
MANEUVER_OFFENSE_COLOR = "#E24B4A"
MANEUVER_DEFENSE_COLOR = "#97C459"
MANEUVER_CARD_TEXT_COLOR = "#14202b"


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
    tip_x = cx + radius * cos(theta)
    tip_y = cy + radius * sin(theta)
    tangent_x, tangent_y = -sin(theta), cos(theta)
    perp_x, perp_y = -tangent_y, tangent_x

    arrow_length = 34
    arrow_half_width = 20
    back_x = tip_x - tangent_x * arrow_length
    back_y = tip_y - tangent_y * arrow_length
    left = (
        back_x + perp_x * arrow_half_width,
        back_y + perp_y * arrow_half_width,
    )
    right = (
        back_x - perp_x * arrow_half_width,
        back_y - perp_y * arrow_half_width,
    )
    draw.polygon([(tip_x, tip_y), left, right], fill=fill)


def _maneuver_cycle_order(
    catalog: ManeuverCatalog,
) -> list[tuple[ManeuverDefinition, bool]]:
    """
    Walk the single defeat cycle formed by the maneuver catalog,
    alternating offense/defense, starting from the lowest-rank offense
    maneuver. Returns (maneuver, is_offense) pairs in cycle order,
    matching the hexagon diagram's node order.
    """
    offense_by_name = catalog.offense_by_name()
    defense_by_name = catalog.defense_by_name()
    start = min(catalog.offense, key=lambda item: item.rank)

    order: list[tuple[ManeuverDefinition, bool]] = [(start, True)]
    current, is_offense = start, True
    node_count = len(catalog.offense) + len(catalog.defense)
    for _ in range(node_count - 1):
        if is_offense:
            current = defense_by_name[current.defeats]
            is_offense = False
        else:
            current = offense_by_name[current.defeats]
            is_offense = True
        order.append((current, is_offense))
    return order


def render_maneuver_reference_image(catalog: ManeuverCatalog) -> BytesIO:
    """
    Render the maneuvers arranged in their defeat cycle: arrows trace
    who beats whom, dashed diameters connect the tie pairs (opposite
    nodes), and each card carries its die range and full effect text.
    """
    canvas = Image.new(
        "RGBA",
        (MANEUVER_DIAGRAM_WIDTH, MANEUVER_DIAGRAM_HEIGHT),
        "#111820",
    )
    draw = ImageDraw.Draw(canvas)
    cx, cy = MANEUVER_DIAGRAM_CENTER
    node_radius = MANEUVER_DIAGRAM_NODE_RADIUS
    box_width, box_height = MANEUVER_DIAGRAM_BOX_SIZE

    order = _maneuver_cycle_order(catalog)
    node_count = len(order)
    angles = [270 + 360 * index / node_count for index in range(node_count)]
    centers = [
        (
            cx + node_radius * cos(radians(angle)),
            cy + node_radius * sin(radians(angle)),
        )
        for angle in angles
    ]

    # Tie diameters (opposite nodes), drawn first so cards sit on top.
    half = node_count // 2
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

    # Defeat-cycle arrows.
    for index in range(node_count):
        start_angle = angles[index]
        end_angle = (
            angles[index + 1]
            if index + 1 < node_count
            else angles[0] + 360
        )
        draw_arc_arrow(
            draw,
            (cx, cy),
            MANEUVER_DIAGRAM_ARC_RADIUS,
            start_angle,
            end_angle,
            fill="#808080",
            width=6,
        )

    for (maneuver, is_offense), (center_x, center_y) in zip(
        order, centers
    ):
        color = (
            MANEUVER_OFFENSE_COLOR if is_offense else MANEUVER_DEFENSE_COLOR
        )
        box_left = center_x - box_width / 2
        box_top = center_y - box_height / 2
        draw.rounded_rectangle(
            (
                box_left,
                box_top,
                box_left + box_width,
                box_top + box_height,
            ),
            radius=16,
            fill=color,
            outline="#ffffff",
            width=2,
        )

        text_y = box_top + 20
        draw_centered_text(
            draw,
            center_x,
            text_y,
            maneuver.name,
            FONT_MANEUVER_TITLE,
            MANEUVER_CARD_TEXT_COLOR,
        )
        text_y += 42
        for line in wrap_text(
            draw, maneuver.effect, FONT_MANEUVER_BODY, box_width - 48
        ):
            draw_centered_text(
                draw,
                center_x,
                text_y,
                line,
                FONT_MANEUVER_BODY,
                MANEUVER_CARD_TEXT_COLOR,
            )
            text_y += 30

    legend_y = MANEUVER_DIAGRAM_HEIGHT - 70
    swatch_size = 32
    draw.rounded_rectangle(
        (120, legend_y, 120 + swatch_size, legend_y + swatch_size),
        radius=6,
        fill=MANEUVER_OFFENSE_COLOR,
    )
    draw.text(
        (168, legend_y + 4),
        "Offense",
        font=FONT_MANEUVER_LEGEND,
        fill="#ffffff",
    )
    draw.rounded_rectangle(
        (320, legend_y, 320 + swatch_size, legend_y + swatch_size),
        radius=6,
        fill=MANEUVER_DEFENSE_COLOR,
    )
    draw.text(
        (368, legend_y + 4),
        "Defense",
        font=FONT_MANEUVER_LEGEND,
        fill="#ffffff",
    )
    arrow_y = legend_y + swatch_size / 2
    draw.line((560, arrow_y, 660, arrow_y), fill="#808080", width=6)
    draw.polygon(
        [(660, arrow_y - 12), (660, arrow_y + 12), (682, arrow_y)],
        fill="#808080",
    )
    draw.text(
        (700, legend_y + 4),
        "Defeats",
        font=FONT_MANEUVER_LEGEND,
        fill="#ffffff",
    )
    draw_dashed_line(
        draw, 900, arrow_y, 1000, arrow_y, fill="#808080", width=5
    )
    draw.text(
        (1020, legend_y + 4),
        "Ties (skill test)",
        font=FONT_MANEUVER_LEGEND,
        fill="#ffffff",
    )

    output = BytesIO()
    canvas.convert("RGB").save(output, format="PNG")
    output.seek(0)
    return output


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
        match.home.team.value.title(),
        FONT_HEADING,
        TEAM_COLORS[match.home.team],
    )
    draw_centered_text(
        draw,
        visiting_center,
        JUMBOTRON_TOP + 20,
        match.visiting.team.value.title(),
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


def draw_player_board(
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
) -> None:
    color = TEAM_COLORS[setup.team]
    draw.rounded_rectangle(
        (x, y, x + width, PLAYER_BOARD_BOTTOM),
        radius=18,
        fill="#202a35",
        outline=color,
        width=5,
    )
    draw.text(
        (x + 22, y + 16),
        setup.team.value.title(),
        font=FONT_HEADING,
        fill=color,
    )

    bench_x = x + 220
    draw.text(
        (bench_x, y + 20),
        "BENCH",
        font=FONT_BODY,
        fill="#ffffff",
    )
    card_x = bench_x
    for player_id in setup.player_board.bench:
        player = players[player_id]
        draw_card(
            canvas,
            draw,
            player,
            catalog.effective_profile(player),
            card_x,
            y + 68,
            exhaustion=exhaustion.get(player_id, 0),
            exhausted=player_id in exhausted,
            injured=player_id in injured,
        )
        card_x += CARD_SIZE[0] + 14

    back_bench_x = x + 620
    draw.text(
        (back_bench_x, y + 20),
        "BACK BENCH",
        font=FONT_BODY,
        fill="#ffffff",
    )
    if not setup.player_board.back_bench:
        draw.text(
            (back_bench_x, y + 105),
            "Empty",
            font=FONT_BODY,
            fill="#9eabb8",
        )
    else:
        card_x = back_bench_x
        for player_id in setup.player_board.back_bench:
            player = players[player_id]
            draw_card(
                canvas,
                draw,
                player,
                catalog.effective_profile(player),
                card_x,
                y + 68,
                exhaustion=exhaustion.get(player_id, 0),
                exhausted=player_id in exhausted,
                injured=player_id in injured,
            )
            card_x += CARD_SIZE[0] + 14


def render_match_image(
    match: MatchState,
    catalog: PlayerCatalog,
    title: str | None = None,
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
            f"{match.home.team.value.title()} vs "
            f"{match.visiting.team.value.title()}, {period}"
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
    )
    draw_board(canvas, draw, match, players)
    draw_assignment_cards(
        canvas,
        draw,
        match.home,
        players,
        catalog,
        bounds,
        835,
        match.exhaustion,
        match.exhausted,
        match.injured,
    )
    player_board_width = (
        BOARD_RIGHT - BOARD_LEFT - PLAYER_BOARD_GAP
    ) // 2
    draw_player_board(
        canvas,
        draw,
        match.home,
        players,
        catalog,
        BOARD_LEFT,
        PLAYER_BOARD_TOP,
        player_board_width,
        match.exhaustion,
        match.exhausted,
        match.injured,
    )
    draw_player_board(
        canvas,
        draw,
        match.visiting,
        players,
        catalog,
        BOARD_LEFT + player_board_width + PLAYER_BOARD_GAP,
        PLAYER_BOARD_TOP,
        player_board_width,
        match.exhaustion,
        match.exhausted,
        match.injured,
    )

    output = BytesIO()
    # BILINEAR here, not LANCZOS: this is a pure 1.5x upscale of an
    # already-antialiased raster (unlike the card build, which downscales
    # from a supersampled source and needs LANCZOS's quality), so the
    # cheaper filter costs no visible sharpness but is significantly
    # faster.
    enlarged = canvas.resize(OUTPUT_SIZE, Image.Resampling.BILINEAR)
    enlarged.convert("RGB").save(output, format="PNG")
    output.seek(0)
    return output
