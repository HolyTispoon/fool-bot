"""
The players as standees, for the print-and-play kit.

D12 Ball 2.0 takes the role off the player (docs/rules-2.2.md section
4), so a meeple coloured or labelled by role no longer says who is
standing on a space, and nine plain meeples a team say nothing at all.
A standee is the player's own portrait -- the bot's art, the picture on
their card -- so the field and the cards are read as one set of people
(the author, 2026-10-24). Nothing on a standee is edition-bound -- no
role, no skill, which an advanced card changes -- so 1.0 plays with
them too.

**Flat, for a slotted plastic base** (the author, 2026-10-24): one
strip a player, the front face and the back face end to end with the
fold between them at the top of the two portraits. Cut it out, fold it,
glue it back to back -- with a card from a cereal box between the
halves where a base's slot wants it thicker -- and push the foot into a
1in (25 mm) base. The back is the front's picture again, not its
mirror image: a mirrored painting turns every jersey number and every
d12's numbers backwards, and a rectangle has no outline for a mirror to
keep true. It is drawn upside down on the sheet, so the fold stands it
up.

A face is `FACE_WIDTH` across because the narrowest space on a printed
field is 1.36in (`FieldGeometry.space_inches` on board 10), and two
sides' standees on one space stand along its length, not across it.
The portrait stands on the name band, in front of a pale tint of the
team's colour, so which side a standee is on reads from across the
table; the band is the team's colour with the name in
`high_contrast_ink` and the species' icon beside it, as a card's badge
carries it.

A colour team is one letter page, its nine in roster order: printed
one-sided, since both faces are on the strip. `scripts/render_standees.py`
is the CLI; see docs/design/standees.md.
"""

from __future__ import annotations

from PIL import Image, ImageColor, ImageDraw, ImageFont

from .boards import PAPERS, PRINT_DPI
from .components import PlayerCatalog, PlayerDefinition
from .game import COLOR_TEAMS, Team, team_display_name
from .render import FONT_DIR, TEAM_COLORS, high_contrast_ink, load_player_portrait, species_icon

# One face, in inches: the portrait, the band under it with the name,
# and the foot under that, which goes into the base's slot. The
# paintings are mostly wider than they are tall, so the width decides
# their size and the portrait's height is kept to what they fill.
FACE_WIDTH = 1.25
PORTRAIT_HEIGHT = 1.15
BAND_HEIGHT = 0.26
FOOT_HEIGHT = 0.30
# The room left round a portrait inside its panel. It stands on the
# band, so there is none under it.
PORTRAIT_PAD = 0.03
# The species icon in the band, and the room round it and the name.
ICON_SIZE = 0.18
BAND_PAD = 0.05
NAME_CAP = 0.11

# How much of the team's colour the portrait's ground carries, against
# white: enough to say whose a standee is, little enough that the
# painting stays in front of it. The foot is a step deeper, so the line
# a base covers to shows.
GROUND_TINT = 0.22
FOOT_TINT = 0.45

# The colour runs this far past the cut line, so a cut a little outside
# it leaves colour at the edge rather than white paper.
BLEED_INCHES = 0.04
CUT_LINE_COLOR = (130, 130, 130)
FOLD_LINE_COLOR = (60, 60, 60)
FOLD_DASH_INCHES = 0.06

# The page: letter, portrait, a team on it, five across.
STANDEE_PAPER = "letter"
STANDEE_COLUMNS = 5
COLUMN_GAP_INCHES = 0.14
ROW_GAP_INCHES = 0.35
TITLE_INCHES = 0.16
NOTE_INCHES = 0.11
HEADING_GAP_INCHES = 0.2
MARGIN_INCHES = 0.5
HEADING_COLOR = (60, 60, 60)
NOTE = (
    "Cut on the grey line. Fold on the dashed line and glue the halves "
    "back to back. Push the foot into a 1in (25 mm) standee base."
)

FONT_PATH = FONT_DIR / "RobotoSlab-Bold.ttf"
NOTE_FONT_PATH = FONT_DIR / "RobotoSlab-Regular.ttf"


def pixels(inches: float) -> int:
    return round(inches * PRINT_DPI)


def tint(colour: tuple[int, int, int], share: float) -> tuple[int, int, int]:
    return tuple(round(255 + (channel - 255) * share) for channel in colour)


def cap_font(path, cap_height: float) -> ImageFont.FreeTypeFont:
    """The font at the size whose capitals are `cap_height` pixels tall."""
    probe = ImageFont.truetype(str(path), 1000)
    _, top, _, bottom = probe.getbbox("H")
    return ImageFont.truetype(str(path), max(1, round(1000 * cap_height / (bottom - top))))


def name_font(name: str, cap_height: float, max_width: float) -> ImageFont.FreeTypeFont:
    """The name at `cap_height`, or smaller where it would run past
    `max_width` -- "Flickerwing" is the long one."""
    face = cap_font(FONT_PATH, cap_height)
    width = face.getlength(name)
    if width > max_width:
        face = ImageFont.truetype(str(FONT_PATH), int(face.size * max_width / width))
    return face


def standee_face(player: PlayerDefinition, team: Team) -> Image.Image:
    """
    One face, foot down, at 300dpi: the portrait on the team's tint,
    the band with the name and the species' icon, the foot.
    """
    colour = ImageColor.getrgb(TEAM_COLORS[team])
    ink = ImageColor.getrgb(high_contrast_ink(TEAM_COLORS[team]))
    width = pixels(FACE_WIDTH)
    portrait_height = pixels(PORTRAIT_HEIGHT)
    band = pixels(BAND_HEIGHT)
    foot = pixels(FOOT_HEIGHT)
    face = Image.new("RGB", (width, portrait_height + band + foot), tint(colour, GROUND_TINT))
    pen = ImageDraw.Draw(face)

    portrait = load_player_portrait(player.name)
    if portrait is not None:
        portrait = portrait.crop(portrait.getchannel("A").getbbox())
        pad = pixels(PORTRAIT_PAD)
        scale = min((width - 2 * pad) / portrait.width, (portrait_height - pad) / portrait.height)
        portrait = portrait.resize(
            (round(portrait.width * scale), round(portrait.height * scale)),
            Image.Resampling.LANCZOS,
        )
        face.paste(
            portrait,
            ((width - portrait.width) // 2, portrait_height - portrait.height),
            portrait,
        )

    band_top = portrait_height
    pen.rectangle((0, band_top, width, band_top + band - 1), fill=colour)
    pen.rectangle((0, band_top + band, width, face.height), fill=tint(colour, FOOT_TINT))

    pad = pixels(BAND_PAD)
    icon_size = pixels(ICON_SIZE)
    icon = species_icon(player.species, high_contrast_ink(TEAM_COLORS[team]))
    name_left = pad
    if icon is not None:
        icon = icon.resize((icon_size, icon_size), Image.Resampling.LANCZOS)
        face.paste(icon, (pad, band_top + (band - icon_size) // 2), icon)
        name_left = pad + icon_size + pad
    # The name is centred on the face where it fits beside the icon,
    # and pushed right of the icon where it does not.
    font = name_font(player.name, pixels(NAME_CAP), width - name_left - pad)
    text_width = font.getlength(player.name)
    x = max(name_left, (width - text_width) / 2)
    _, cap_top, _, cap_bottom = font.getbbox("H")
    pen.text(
        (x, band_top + band / 2 - (cap_top + cap_bottom) / 2),
        player.name,
        font=font,
        fill=ink,
    )
    return face


def standee_strip(player: PlayerDefinition, team: Team) -> Image.Image:
    """
    The whole standee as printed, with its bleed: the back face upside
    down above the fold, the front face under it, the grey cut line
    round the two and the dashed fold between them.
    """
    front = standee_face(player, team)
    back = front.rotate(180)
    bleed = pixels(BLEED_INCHES)
    strip = Image.new("RGB", (front.width + 2 * bleed, 2 * front.height + 2 * bleed), "white")
    # The bleed is each face's own edge drawn outward: the foot's colour
    # at the two ends and the face's colours down the sides.
    for image, top in ((back, bleed), (front, bleed + back.height)):
        stretched = image.resize((image.width + 2 * bleed, image.height), Image.Resampling.NEAREST)
        strip.paste(stretched, (0, top))
        strip.paste(image, (bleed, top))
    strip.paste(strip.crop((0, bleed, strip.width, bleed + 1)).resize((strip.width, bleed)), (0, 0))
    strip.paste(
        strip.crop((0, strip.height - bleed - 1, strip.width, strip.height - bleed)).resize(
            (strip.width, bleed)
        ),
        (0, strip.height - bleed),
    )

    pen = ImageDraw.Draw(strip)
    line = max(1, pixels(0.006))
    pen.rectangle(
        (bleed, bleed, strip.width - bleed - 1, strip.height - bleed - 1),
        outline=CUT_LINE_COLOR,
        width=line,
    )
    fold = bleed + back.height
    dash = pixels(FOLD_DASH_INCHES)
    for x in range(bleed, strip.width - bleed, 2 * dash):
        pen.line((x, fold, min(x + dash, strip.width - bleed), fold), fill=FOLD_LINE_COLOR, width=line * 2)
    return strip


def wrapped(text: str, font: ImageFont.FreeTypeFont, width: float) -> list[str]:
    """`text` broken into lines no wider than `width`."""
    lines = [""]
    for word in text.split():
        trial = f"{lines[-1]} {word}".strip()
        if lines[-1] and font.getlength(trial) > width:
            lines.append(word)
        else:
            lines[-1] = trial
    return lines


def render_standee_page(catalog: PlayerCatalog, team: Team, paper: str = STANDEE_PAPER) -> Image.Image:
    """A colour team's nine on one page, `STANDEE_COLUMNS` across, in
    roster order, under the team's name and how to make them."""
    page = (pixels(PAPERS[paper][0]), pixels(PAPERS[paper][1]))
    sheet = Image.new("RGB", page, "white")
    pen = ImageDraw.Draw(sheet)
    strips = [standee_strip(player, team) for player in catalog.teams[team].players]
    cell = strips[0].size
    column_gap, row_gap = pixels(COLUMN_GAP_INCHES), pixels(ROW_GAP_INCHES)
    columns = min(STANDEE_COLUMNS, len(strips))
    rows = -(-len(strips) // columns)

    title_font = cap_font(FONT_PATH, pixels(TITLE_INCHES))
    note_font = cap_font(NOTE_FONT_PATH, pixels(NOTE_INCHES))
    heading = round(pixels(TITLE_INCHES) * 1.8 + pixels(NOTE_INCHES) * 1.9 * 2) + pixels(
        HEADING_GAP_INCHES
    )
    used = (
        columns * cell[0] + (columns - 1) * column_gap,
        heading + rows * cell[1] + (rows - 1) * row_gap,
    )
    margin = pixels(MARGIN_INCHES)
    if used[0] > page[0] - 2 * margin or used[1] > page[1] - 2 * margin:
        raise ValueError(f"{team.value}'s {len(strips)} standees do not fit a {paper} page")

    left = (page[0] - used[0]) // 2
    top = (page[1] - used[1]) // 2
    pen.text(
        (left, top), f"{team_display_name(team).upper()} · STANDEES", font=title_font, fill=HEADING_COLOR
    )
    note_top = top + round(pixels(TITLE_INCHES) * 1.8)
    for line in wrapped(NOTE, note_font, used[0]):
        pen.text((left, note_top), line, font=note_font, fill=HEADING_COLOR)
        note_top += round(pixels(NOTE_INCHES) * 1.9)
    for index, strip in enumerate(strips):
        row, column = divmod(index, columns)
        sheet.paste(
            strip,
            (
                left + column * (cell[0] + column_gap),
                top + heading + row * (cell[1] + row_gap),
            ),
        )
    return sheet


def render_standee_pages(
    catalog: PlayerCatalog, teams: tuple[Team, ...] = COLOR_TEAMS
) -> dict[Team, Image.Image]:
    return {team: render_standee_page(catalog, team) for team in teams}
