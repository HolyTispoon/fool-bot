"""
The six basic role abilities as a reference card, print-ready for the
tabletop game.

Every player's role ability is in play for both coaches every game --
unlike a species ability, only two of which are ever on the field at
once (see "The species cards" in docs/design/cards.md), both sides
field all six roles. So there is no pairing to solve and no split to
make either: **both faces carry all six**, laid out two columns of
three rather than the tall single-role strips a smaller set would use,
so either side up is the whole reference and a coach never has to flip
the card to find a role.

Same poker size and the same print machinery as `d12ball/cards.py`
(`Pen`, the sheet, the palette). The badge in each panel is the bot's
own role emoji -- `d12ball/images/emoji/role_<role>.png`, the plain
(team-less) badge `scripts/render_role_emoji.py` draws and the bot
uploads to Discord under `ROLE_EMOJI_NAMES` -- read straight off disk
rather than redrawn, so the two letters on the card and the two
letters next to a name in Discord are the same art. Nothing else here
is written in the module: the ability text and the offense/defense
numbers come from `players.json`'s `role_profiles` through
`PlayerCatalog`, so a card cannot claim a stat the bot does not play,
and a sheet revision reaches the card by re-importing and re-running
`scripts/render_role_cards.py`.
"""
from pathlib import Path

from PIL import Image, ImageFont

from d12ball.cards import (
    CARD_FACE,
    CARD_HEIGHT,
    CARD_WIDTH,
    CORNER,
    EDGE_WIDTH,
    FRAME,
    INK,
    MARGIN,
    MUTED,
    PANEL_COLOR,
    PANEL_EDGE,
    Pen,
    SUPERSAMPLE,
    fitted_bold_font,
    font,
)
from d12ball.components import PlayerRole, RoleProfile
from d12ball.render import CARD_DEFENSE_COLOR, CARD_OFFENSE_COLOR

HEADER_HEIGHT = 44
HEADER_TITLE = "ROLE ABILITIES"

# Two columns of three, not six strips: six abilities are too many for
# one full-width row apiece on a poker card, and splitting every row in
# two is what buys back the room without shrinking the card set to
# fewer than all six.
GRID_COLUMNS = 2
GRID_ROWS = 3
COLUMN_GAP = 20
ROW_GAP = 20

# Row-major over `PlayerRole`'s own order (offense 1 through 6), read
# off rather than re-decided here -- the same order the enum and the
# roster listing already use.
GRID_ROLES: tuple[tuple[PlayerRole, PlayerRole], ...] = (
    (PlayerRole.FULLBACK, PlayerRole.DEFENDER),
    (PlayerRole.MIDFIELDER, PlayerRole.PLAYMAKER),
    (PlayerRole.WINGER, PlayerRole.STRIKER),
)

# The band is two rows: the badge and the role's name (tall, so the
# badge can nearly fill it), then offense and defense side by side on
# one row under it -- a pair of one-digit numbers doesn't need a row
# each, and keeping the band to two rows is what leaves the panel's
# own room to the ability text below rather than to a second stat row.
NAME_ROW_HEIGHT = 76
STAT_ROW_HEIGHT = 28
STAT_ROW_GAP = 2
BAND_HEIGHT = NAME_ROW_HEIGHT + STAT_ROW_GAP + STAT_ROW_HEIGHT

# The badge nearly fills its own row rather than sitting small beside
# the name -- it is the same art a coach already reads at a glance in
# Discord, so making it the size of the thing it is a picture of is
# what a print reference should do with the room a card this size has.
BADGE_SIZE = round(NAME_ROW_HEIGHT * 0.82)
BADGE_GAP = 14

# Every role's ability is one sentence (the sheet's `basic_abilities`
# tab, unlike a species' which sometimes names sub-actions on their own
# lines), so the panel needs no paragraph handling -- just the largest
# size that wraps the whole thing into the room left under the band.
# The cap is a search bound, not a target: it only has to sit above
# what any role's own sentence could naturally reach in the room a
# panel has, so Defender's own fit (below, the ceiling every panel's
# ability text is actually drawn at) is found unclipped rather than
# flattened against an arbitrary size all six would otherwise hit.
BODY_MAX_SIZE = 56
BODY_MIN_SIZE = 14

ROLE_EMOJI_DIR = Path(__file__).resolve().parent / "images" / "emoji"


def _role_badge(role: PlayerRole) -> Image.Image | None:
    """
    The plain (team-less) role badge the bot uploads as an application
    emoji, read straight off disk. It is the same art a coach sees
    beside a name in Discord once the upload exists -- see "The
    brackets have an emoji form" in docs/design/naming-and-wording.md
    -- but the message path never opens the file itself; this is that
    file's first reader. A missing file draws nothing, the swallowed-
    OSError contract every other bundled image in this package
    follows.
    """
    if role not in _ROLE_BADGES:
        path = ROLE_EMOJI_DIR / f"role_{role.value}.png"
        try:
            _ROLE_BADGES[role] = Image.open(path).convert("RGBA")
        except OSError:
            _ROLE_BADGES[role] = None
    return _ROLE_BADGES[role]


_ROLE_BADGES: dict[PlayerRole, Image.Image | None] = {}


def _name_available_width(role: PlayerRole, column_width: float) -> float:
    """The room a panel's name row leaves for the name itself, mirroring
    `_draw_panel`'s own badge-offset arithmetic so the ceiling below is
    measured the same way every panel's own name is."""
    name_left = 12
    if _role_badge(role) is not None:
        name_left = 12 + BADGE_SIZE + BADGE_GAP
    return column_width - 12 - name_left


def _fitted_ability(
    pen: Pen,
    text: str,
    max_width: float,
    max_height: float,
    max_size: int = BODY_MAX_SIZE,
) -> tuple[ImageFont.ImageFont, list[str], float]:
    """The largest body size at which the ability's lines fit the panel."""
    def measure(size: int):
        face = font(size)
        lines = pen.wrapped(text, face, max_width)
        step = pen.text_size("Hg", face)[1] * 1.5
        return face, lines, step

    for size in range(max_size, BODY_MIN_SIZE - 1, -1):
        face, lines, step = measure(size)
        if step * len(lines) <= max_height:
            return face, lines, step
    return measure(BODY_MIN_SIZE)


def _draw_panel(
    pen: Pen,
    role: PlayerRole,
    profile: RoleProfile,
    left: float,
    top: float,
    right: float,
    bottom: float,
    name_max_size: int,
    body_max_size: int,
) -> None:
    band_bottom = top + BAND_HEIGHT
    pen.rect(
        (left, top, right, band_bottom),
        radius=14,
        fill=PANEL_COLOR,
        outline=PANEL_EDGE,
        width=2,
    )

    name_row_center = top + NAME_ROW_HEIGHT / 2
    name_left = left + 12
    icon = _role_badge(role)
    if icon is not None:
        pen.paste(
            icon,
            (left + 12 + BADGE_SIZE / 2, name_row_center),
            (BADGE_SIZE, BADGE_SIZE),
        )
        name_left = left + 12 + BADGE_SIZE + BADGE_GAP

    name_face = fitted_bold_font(
        pen, role.value.upper(), right - 12 - name_left,
        max_size=name_max_size, min_size=20,
    ) or font(20, bold=True)
    pen.text(
        (name_left, name_row_center),
        role.value.upper(),
        name_face,
        INK,
        anchor="lm",
    )

    # Offense and defense side by side on the one row under the name,
    # right-anchored as a pair -- a one-digit number doesn't need a row
    # of its own, and freeing the second row hands its height to the
    # ability text below. Right-anchored rather than left is what keeps
    # the pair reading as a column when the six panels sit side by
    # side. Same two colours `player_cards.draw_stats` and the bot's
    # own card draw them in, so a printed 6 and a drawn 6 are the same
    # red or green. "basic skill values:" fills the width the row would
    # otherwise leave blank to the numbers' left, in the same face and
    # size as OFF/DEF but plain and in ink, so the row still reads as
    # one row of small print rather than a second heading.
    stat_face = font(18, bold=True)
    label_face = font(18)
    stat_gap = 14
    stat_left = left + 12
    stat_right = right - 12
    stat_row_center = top + NAME_ROW_HEIGHT + STAT_ROW_GAP + STAT_ROW_HEIGHT / 2
    off_text = f"OFF {profile.offense}"
    def_text = f"DEF {profile.defense}"
    off_width = pen.text_size(off_text, stat_face)[0]
    def_width = pen.text_size(def_text, stat_face)[0]
    block_left = stat_right - off_width - stat_gap - def_width
    pen.text(
        (stat_left, stat_row_center),
        "basic skill values:", label_face, INK,
        anchor="lm",
    )
    pen.text(
        (block_left, stat_row_center),
        off_text, stat_face, CARD_OFFENSE_COLOR,
        anchor="lm",
    )
    pen.text(
        (block_left + off_width + stat_gap, stat_row_center),
        def_text, stat_face, CARD_DEFENSE_COLOR,
        anchor="lm",
    )

    # Top-aligned, not centred: every panel is the same fixed height
    # regardless of how long its own sentence runs, so centring would
    # put six abilities at six different starting heights and read as
    # unaligned rather than as a grid.
    body_top = band_bottom + 14
    body_face, lines, step = _fitted_ability(
        pen, profile.ability, right - left, bottom - body_top,
        max_size=body_max_size,
    )
    y = body_top
    for line in lines:
        pen.text((left, y), line, body_face, INK, anchor="la")
        y += step


def render_role_card(
    role_profiles: dict[PlayerRole, RoleProfile],
    bleed: bool = False,
) -> Image.Image:
    """The reference face: all six roles, two columns of three."""
    pen = Pen((CARD_WIDTH, CARD_HEIGHT), CARD_FACE)
    pen.rect(
        (FRAME, FRAME, CARD_WIDTH - FRAME, CARD_HEIGHT - FRAME),
        radius=CORNER,
        fill=CARD_FACE,
        outline=INK,
        width=EDGE_WIDTH,
    )
    pen.text(
        (CARD_WIDTH / 2, FRAME + 30),
        HEADER_TITLE,
        font(17),
        MUTED,
        anchor="mm",
    )

    top = FRAME + HEADER_HEIGHT + 14
    left = MARGIN
    right = CARD_WIDTH - MARGIN
    usable_height = CARD_HEIGHT - FRAME - 40 - top
    usable_width = right - left

    row_height = (usable_height - ROW_GAP * (GRID_ROWS - 1)) / GRID_ROWS
    column_width = (
        usable_width - COLUMN_GAP * (GRID_COLUMNS - 1)
    ) / GRID_COLUMNS

    # Every panel is the same size, so one role's own fitted size can
    # stand as the ceiling for all six, rather than each panel growing
    # its name or its sentence as large as its own shorter text would
    # allow. Fullback sets the name ceiling and Defender the body
    # ceiling -- each measured against the same geometry every panel's
    # own name row and body use, so a shorter name (Winger, Striker) or
    # a longer one (Fullback, Striker) is capped to that size instead.
    name_ceiling_width = _name_available_width(PlayerRole.FULLBACK, column_width)
    name_ceiling_face = fitted_bold_font(
        pen, PlayerRole.FULLBACK.value.upper(), name_ceiling_width,
        max_size=48, min_size=20,
    ) or font(20, bold=True)
    name_ceiling = round(name_ceiling_face.size / SUPERSAMPLE)

    body_available_height = row_height - BAND_HEIGHT - 14
    body_ceiling_face, _, _ = _fitted_ability(
        pen, role_profiles[PlayerRole.DEFENDER].ability,
        column_width, body_available_height,
    )
    body_ceiling = round(body_ceiling_face.size / SUPERSAMPLE)

    for row_index, row_roles in enumerate(GRID_ROLES):
        row_top = top + row_index * (row_height + ROW_GAP)
        for col_index, role in enumerate(row_roles):
            col_left = left + col_index * (column_width + COLUMN_GAP)
            _draw_panel(
                pen, role, role_profiles[role],
                col_left, row_top,
                col_left + column_width, row_top + row_height,
                name_ceiling, body_ceiling,
            )

    return pen.finish(bleed, CARD_FACE)


def render_role_card_set(
    role_profiles: dict[PlayerRole, RoleProfile],
    bleed: bool = False,
) -> list[tuple[str, Image.Image]]:
    """
    Both faces of the card. They are the same image: with all six
    roles on every face there is nothing left for a second face to add,
    and a coach reaching for either side of the card still finds the
    whole reference.
    """
    card = render_role_card(role_profiles, bleed)
    return [("front", card), ("back", card)]
