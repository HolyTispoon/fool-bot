"""
D12 Ball 2.0's role tokens, as a duplex pair of sheets for the
print-and-play kit.

In 2.0 a player has no role: the formation does, and a role moves from
card to card in a Coaching Choice (docs/rules-2.2.md section 4). The
printed player card still says its 1.0 role, so a table marks who holds
which role now with a token laid on the card (the author, 2026-10-24).

**A token is a zone's, not a role's** (the author, 2026-10-24): its
front is the zone's unique role and its back the zone's standard one --
Fullback over Defender, Playmaker over Midfielder, Striker over Winger,
`FORMATION_ZONE_ROLES`' pairs -- so turning a token over is the trade
between the two roles of one zone. A team has as many of a zone's
tokens as any formation puts players in that zone (`tokens_per_zone`,
read off the ruleset's formations: three each today), which is nine.

A face is the bot's role badge (`scripts/render_role_emoji.py`) drawn
at the condition tokens' 19 mm and in their rounded square
(`token_sheet.SQUARE_CORNER`, `RING`): the initials the board and the
card use (`ROLE_INITIALS`), and the role's name under them, since a
coach new to 2.0 reads "PLAYMAKER" sooner than "PM". **Every face is
the badge's own recipe** -- white inside a ring of the team's colour,
the letters in ink -- unique and standard alike (the author,
2026-10-24): the words say which side is up.

The sheets print like the condition tokens' (`token_sheet`): the front
sheet every token's unique side with a grey cut line a millimetre
outside it, the back sheet its standard side at the mirrored position,
printed duplex and flipped on the long edge. Each colour team is a
block of its own -- a zone a row -- with its name over it on the front.

`scripts/render_role_tokens.py` is the CLI; see "Role tokens" in
docs/design/printed-tokens.md.
"""

from __future__ import annotations

from PIL import Image, ImageColor, ImageDraw, ImageFont

from .boards import PAPERS
from .components import FORMATION_ZONE_ROLES, UNIQUE_ROLE_VALUES, BasicRuleset, PlayerRole
from .game import COLOR_TEAMS, Team, team_display_name
from .render import ROLE_INITIALS, TEAM_COLORS
from .token_sheet import (
    FONT_PATH,
    GAP_INCHES,
    MARGIN_INCHES,
    RING,
    SQUARE_CORNER,
    SUPERSAMPLE,
    TOKEN_INCHES,
    TOKEN_SHEET_PAPER,
    pixels,
    with_cut_line,
)

# The zones in the order a team's block lists them, from the coach's
# own goal forward -- the order rules-2.2 4.2 reads a formation in.
ZONE_ORDER = ("own_goal", "midfield", "opponent_goal")

# The role badge's ink and white (`render_role_emoji.INK`, `FACE_COLOR`).
INK = (17, 17, 17)
WHITE = (255, 255, 255)

# Where the initials and the name sit, as shares of the token's width:
# the initials' cap height and the centre of each line. The initials
# are set at one size for all six, fitted to the widest pair, and the
# names at one size fitted to the longest -- six sizes would read as
# six tokens rather than one token six ways (the role badge's reason).
INITIALS_HEIGHT = 0.34
INITIALS_CENTRE = 0.42
INITIALS_WIDTH = 0.70
NAME_HEIGHT = 0.095
NAME_CENTRE = 0.76
NAME_WIDTH = 0.74
# Without the name -- a badge on a board, too small for it to read --
# the initials alone, centred and larger.
BARE_INITIALS_HEIGHT = 0.40
BARE_INITIALS_WIDTH = 0.76

# The team's name over its block, on the front sheet alone.
LABEL_INCHES = 0.13
LABEL_GAP_INCHES = 0.06
LABEL_COLOR = (90, 90, 90)
# The white between two teams' blocks.
BLOCK_GAP_INCHES = 0.35
BLOCK_COLUMNS = 2


def tokens_per_zone(rules: BasicRuleset) -> dict[str, int]:
    """How many of each zone's tokens a team needs: the most players
    any formation puts in that zone, since each holds one of its two
    roles."""
    return {
        zone: max(getattr(shape, zone) for shape in rules.formations.values())
        for zone in ZONE_ORDER
    }


def fitted_font(texts: list[str], cap_height: float, max_width: float) -> ImageFont.FreeTypeFont:
    """Roboto Slab Bold at the cap height asked, or smaller where the
    widest of `texts` would run past `max_width`."""
    probe = ImageFont.truetype(str(FONT_PATH), 1000)
    cap = probe.getbbox("H")[3] - probe.getbbox("H")[1]
    size = round(1000 * cap_height / cap)
    widest = max(probe.getlength(text) for text in texts) * size / 1000
    if widest > max_width:
        size = int(size * max_width / widest)
    return ImageFont.truetype(str(FONT_PATH), size)


def centred_text(
    pen: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    centre: tuple[float, float],
    fill: tuple[int, int, int],
) -> None:
    """`text` centred on its cap height, so a line with no descender
    sits where the eye expects it (the role badge does the same)."""
    width = font.getlength(text)
    _, cap_top, _, cap_bottom = font.getbbox("H")
    pen.text(
        (centre[0] - width / 2, centre[1] - (cap_top + cap_bottom) / 2),
        text,
        font=font,
        fill=fill,
    )


def role_face(role: PlayerRole, ring: str, width: int, named: bool = True) -> Image.Image:
    """One face `width` across: white inside a ring of `ring` -- a
    team's colour on a token, ink on the 2.0 boards that show which
    role goes where (`boards.draw_role_marks`) -- the initials and the
    name in ink. A board's badge is `named=False`, the initials alone:
    it is a third of a token's size, and the board writes the name
    beside it."""
    size = width * SUPERSAMPLE
    colour = ImageColor.getrgb(ring)

    face = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    pen = ImageDraw.Draw(face)
    corner = size * SQUARE_CORNER
    ring = size * RING
    pen.rounded_rectangle((0, 0, size - 1, size - 1), radius=corner, fill=colour)
    pen.rounded_rectangle(
        (ring, ring, size - 1 - ring, size - 1 - ring),
        radius=corner - ring,
        fill=WHITE,
    )

    if not named:
        bare_font = fitted_font(
            list(ROLE_INITIALS.values()),
            size * BARE_INITIALS_HEIGHT,
            size * BARE_INITIALS_WIDTH,
        )
        centred_text(pen, ROLE_INITIALS[role.value], bare_font, (size / 2, size / 2), INK)
        return face.resize((width, width), Image.Resampling.LANCZOS)
    initials_font = fitted_font(
        list(ROLE_INITIALS.values()), size * INITIALS_HEIGHT, size * INITIALS_WIDTH
    )
    name_font = fitted_font(
        [member.value.upper() for member in PlayerRole], size * NAME_HEIGHT, size * NAME_WIDTH
    )
    centred_text(pen, ROLE_INITIALS[role.value], initials_font, (size / 2, size * INITIALS_CENTRE), INK)
    centred_text(pen, role.value.upper(), name_font, (size / 2, size * NAME_CENTRE), INK)
    return face.resize((width, width), Image.Resampling.LANCZOS)


def team_tokens(rules: BasicRuleset) -> list[list[tuple[PlayerRole, PlayerRole]]]:
    """A team's tokens as rows, a zone a row: each token its (front,
    back) pair, as many as `tokens_per_zone` says."""
    counts = tokens_per_zone(rules)
    return [[FORMATION_ZONE_ROLES[zone]] * counts[zone] for zone in ZONE_ORDER]


def render_role_token_sheets(
    rules: BasicRuleset,
    teams: tuple[Team, ...] = COLOR_TEAMS,
    paper: str = TOKEN_SHEET_PAPER,
) -> tuple[Image.Image, Image.Image]:
    """
    The front sheet and the back sheet: every team in `teams` as a
    block, `BLOCK_COLUMNS` across, its unique sides on the first and its
    standard sides on the second at the mirrored position.
    """
    page = (pixels(PAPERS[paper][0]), pixels(PAPERS[paper][1]))
    margin, gap = pixels(MARGIN_INCHES), pixels(GAP_INCHES)
    block_gap = pixels(BLOCK_GAP_INCHES)
    width = pixels(TOKEN_INCHES)
    rows = team_tokens(rules)

    faces = {
        team: {
            role: with_cut_line(role_face(role, TEAM_COLORS[team], width), cut_line=role.value in UNIQUE_ROLE_VALUES)
            for pair in FORMATION_ZONE_ROLES.values()
            for role in pair
        }
        for team in teams
    }
    cell = next(iter(next(iter(faces.values())).values())).size
    columns = max(len(row) for row in rows)
    label = pixels(LABEL_INCHES) + pixels(LABEL_GAP_INCHES)
    block = (
        columns * cell[0] + (columns - 1) * gap,
        label + len(rows) * cell[1] + (len(rows) - 1) * gap,
    )
    block_rows = -(-len(teams) // BLOCK_COLUMNS)
    across = min(len(teams), BLOCK_COLUMNS)
    used = (
        across * block[0] + (across - 1) * block_gap,
        block_rows * block[1] + (block_rows - 1) * block_gap,
    )
    if used[0] > page[0] - 2 * margin or used[1] > page[1] - 2 * margin:
        raise ValueError(f"{len(teams)} teams' role tokens do not fit a {paper} sheet")

    sheets = (Image.new("RGBA", page, "white"), Image.new("RGBA", page, "white"))
    label_font = fitted_font(["X"], pixels(LABEL_INCHES) * 0.72, page[0])
    left = (page[0] - used[0]) // 2
    top = (page[1] - used[1]) // 2
    for index, team in enumerate(teams):
        block_row, block_column = divmod(index, BLOCK_COLUMNS)
        block_left = left + block_column * (block[0] + block_gap)
        block_top = top + block_row * (block[1] + block_gap)
        # The team's name, on the front alone: it is cut away, and on
        # the back it would only print mirrored.
        ImageDraw.Draw(sheets[0]).text(
            (block_left, block_top),
            f"{team_display_name(team).upper()} · ROLE TOKENS",
            font=label_font,
            fill=LABEL_COLOR,
        )
        for row, tokens in enumerate(rows):
            for column, pair in enumerate(tokens):
                x = block_left + column * (cell[0] + gap)
                y = block_top + label + row * (cell[1] + gap)
                for side, (sheet, role) in enumerate(zip(sheets, pair)):
                    face = faces[team][role]
                    # Flipped about the long edge: a token's back is at
                    # its front's position mirrored about the centre line.
                    sheet.alpha_composite(face, (page[0] - x - face.width if side else x, y))
    return sheets[0].convert("RGB"), sheets[1].convert("RGB")
