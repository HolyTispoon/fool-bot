"""
The roster as cards, print-ready for the tabletop game.

One card a player -- 2.5 x 3.5 inches at 300dpi, the same poker size
and the same print machinery as `d12ball/cards.py`, which this borrows
`Pen`, the sheet and the palette from. A coach at the table and a coach
playing by Discord should be reading the same card, so the layout
follows the one the bot draws on the board (`build_player_card` in
`d12ball/render.py`): the name, the two skills in their own two
colours, the role's badge, and the portrait under them, inside the
team's colour. The two skills and the role's initials are said again in
the header's left-hand corner, a playing card's index, for a card whose
face is covered (`draw_corner_index`).

**What the printed card adds is the ability**, under the portrait,
behind the role's badge, with the species' badge and its ability's
name under it. The
bot has the board to put it on -- a coach can ask for the roster or the
rules -- where a card on a table is the only thing in front of its
coach, so the sentence has to be on it. It is the full sentence from
`players.json` and never the short form: see "Every ability is imported
twice" in docs/design/rules-and-data.md.

Nothing here is written in the module. The names, roles, skills and
abilities all come from `players.json` through `load_player_catalog`,
so a card cannot claim a stat the bot does not play, and an import
reaches the cards by re-running `scripts/render_player_cards.py`.

**The other side of the card is the same player in advanced mode** --
not a shared back, since these are dealt face up and nothing about
them is hidden. `render_player_card_back` draws it, laid out exactly
as the front: the same header and portrait, **the player's advanced
skills** in the stats row, and **their special ability instead of the
role's** beside the role badge where they have one (Law 21; the
author, 2026-09-25), with the species badge and its ability's name
under it (the author, 2026-09-27).

The special ability replaces the role's *on the card only*: in play a
player keeps both (the author, 2026-09-25), and the role's sentence is
on the front. A player whose sheet sentence only names their higher
skill ("High defensive skill.") prints that sentence, as the sheet words
it; the numbers above it say how high. A player with no special
ability prints their role's sentence on both faces.
"""
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont

from d12ball.cards import (
    CARD_FACE,
    CARD_HEIGHT,
    CARD_WIDTH,
    CORNER,
    DUPLEX_COLUMNS,
    EDGE_WIDTH,
    FRAME,
    INK,
    MARGIN,
    MUTED,
    PANEL_COLOR,
    PANEL_EDGE,
    Pen,
    duplex_order,
    fitted_bold_font,
    font,
    line_height,
)
from d12ball.components import (
    PlayerCatalog,
    PlayerDefinition,
    PlayerRole,
    RoleProfile,
    load_species_abilities,
)
from d12ball.game import COLOR_TEAMS, Team, paired_team
from d12ball.render import (
    CARD_DEFENSE_COLOR,
    CARD_OFFENSE_COLOR,
    ROLE_INITIALS,
    TEAM_COLORS,
    high_contrast_ink,
    load_player_portrait,
    species_icon,
)
from d12ball.role_cards import ROLE_EMOJI_DIR
from d12ball.species_cards import SPECIES_TEAM

# The header band, and the stats panel under it. Both are fixed: the
# portrait takes whatever the ability band leaves, because the ability
# is the one thing on the card whose length is not the layout's to
# choose.
#
# The stats panel is one row, each skill's label on the outside of its
# number rather than over it, and it no longer carries the role: the badge in
# the header and the role's badge in the ability band both say it
# (the author, 2026-09-27). What the panel gave up went to the
# portrait and the ability text.
HEADER_HEIGHT = 132
STATS_TOP_GAP = 16
STATS_HEIGHT = 88
PORTRAIT_GAP = 18

# The role under the name, set large enough to read across a table
# (the author, 2026-09-27). The back's "MIDFIELDER · ADVANCED" is the
# longest line it carries, so it is fitted to the name's room with this
# as the ceiling rather than set at it.
SUBTITLE_SIZE = 26

# The team's own emoji in the header's right-hand corner -- the letter
# in a team-coloured ring the bot puts beside a team's name in Discord
# (`images/emoji/team_<team>.png`, uploaded under `TEAM_EMOJI_NAMES`).
# On the band of the same colour its ring disappears and what reads is
# a white disc with the letter in it. The left-hand corner is left
# empty and the name stays centred on the card.
HEADER_EMOJI = 104
TEAM_EMOJI_DIR = ROLE_EMOJI_DIR

# A portrait is around 400px on its longest side -- the bot's own art,
# and there is no larger source -- so filling this slot scales it up by
# about half again, printing at roughly 190dpi. That is soft under a
# magnifier and fine on a table, and it is the trade the alternative
# loses: kept to its native size, the same picture prints an inch and a
# third wide on a two-and-a-half-inch card, which is smaller than the
# bot draws it on a phone.
PORTRAIT_MAX_SCALE = 1.6


def fitted_name(
    pen: Pen, name: str, max_width: float
) -> ImageFont.ImageFont:
    """
    The largest bold size the header will carry the name at. Player
    names are one word, so unlike a maneuver's there is nothing to
    break -- the size comes down until "Flickerwing" fits in the room
    the team emoji leaves, kept symmetric about the centre, floored at
    22 even if that still doesn't.
    """
    return (
        fitted_bold_font(pen, name, max_width, max_size=54, min_size=22)
        or font(22, bold=True)
    )


def team_emoji(team: Team) -> Image.Image | None:
    """
    The team's emoji as the bot uploads it, read off disk, or None when
    the file is missing -- the swallowed-`OSError` contract every
    bundled image here follows. A species team's emoji is its species'
    icon in a ring rather than a letter, because that is the emoji the
    bot shows for it.
    """
    if team not in _TEAM_EMOJI:
        try:
            _TEAM_EMOJI[team] = Image.open(
                TEAM_EMOJI_DIR / f"team_{team.value}.png"
            ).convert("RGBA")
        except OSError:
            _TEAM_EMOJI[team] = None
    return _TEAM_EMOJI[team]


_TEAM_EMOJI: dict[Team, Image.Image | None] = {}


def corner_mark(team: Team, color: str) -> Image.Image | None:
    """
    The team's emoji as the header's corner draws it: as the bot
    uploads it, except that on a band whose `high_contrast_ink` is
    black -- Slime green -- the letter is black too (the author,
    2026-09-27), so the corner reads like the name beside it. The ring
    is left alone; it is the band's own colour and disappears into it.

    Only the white disc is recoloured, and the recolouring is exact
    rather than a threshold: the emoji's letter is Slime green
    antialiased onto white, and Slime green's blue channel is 0 where
    white's is 255, so the blue channel alone says how much letter a
    pixel holds. Setting all three channels to it redraws the same
    antialiased letter in black.
    """
    emoji = team_emoji(team)
    if emoji is None or high_contrast_ink(color) == "#ffffff":
        return emoji

    blue = emoji.getchannel("B")
    inked = Image.merge("RGBA", (blue, blue, blue, emoji.getchannel("A")))
    disc = Image.new("L", emoji.size, 0)
    radius = emoji.width * CORNER_DISC_FRAC
    center = emoji.width / 2
    ImageDraw.Draw(disc).ellipse(
        (center - radius, center - radius, center + radius, center + radius),
        fill=255,
    )
    marked = emoji.copy()
    marked.paste(inked, (0, 0), disc)
    return marked


# How much of the emoji's width, as a radius, the recoloured disc
# covers: inside the white face (which ends at 96/256, where the ring
# starts) with room for the ring's antialiased edge, and well outside
# the letter.
CORNER_DISC_FRAC = 88 / 256


def draw_header(
    pen: Pen,
    player: PlayerDefinition,
    team: Team,
    color: str,
    subtitle: str,
) -> None:
    """
    The team-coloured band: the name over `subtitle`, centred, and the
    team's emoji in the right-hand corner (the author, 2026-09-27).

    The role is the subtitle, in words, where it used to be two letters
    in a badge on the left: the badge beside the role ability in the
    band at the bottom carries the initials, and the header says the
    role once in full. The species is the badge beside the species
    ability; the header no longer carries its icon. The name's room is
    kept symmetric about the card's centre, so the empty left corner
    does not pull the name off-centre.
    """
    pen.rect(
        (FRAME, FRAME, CARD_WIDTH - FRAME, FRAME + HEADER_HEIGHT),
        radius=CORNER,
        fill=color,
    )
    pen.rect(
        (
            FRAME,
            FRAME + HEADER_HEIGHT - CORNER,
            CARD_WIDTH - FRAME,
            FRAME + HEADER_HEIGHT,
        ),
        fill=color,
    )

    emoji = corner_mark(team, color)
    if emoji is not None:
        pen.paste(
            emoji,
            (CARD_WIDTH - FRAME - 78, FRAME + HEADER_HEIGHT / 2),
            (HEADER_EMOJI, HEADER_EMOJI),
        )

    # Black on Slime green and white on every other band (the author,
    # 2026-09-27): white on Slime could not be read.
    ink = high_contrast_ink(color)
    name_left = FRAME + 132
    name_right = CARD_WIDTH - FRAME - 132
    pen.text(
        ((name_left + name_right) / 2, FRAME + 50),
        player.name,
        fitted_name(pen, player.name, name_right - name_left),
        ink,
        anchor="mm",
    )
    pen.text(
        ((name_left + name_right) / 2, FRAME + 102),
        subtitle,
        fitted_bold_font(
            pen,
            subtitle,
            name_right - name_left,
            max_size=SUBTITLE_SIZE,
            min_size=14,
        )
        or font(14, bold=True),
        ink,
        anchor="mm",
    )


# The corner index in the header's left-hand corner (the author,
# 2026-10-03): the offence over the defence, and the role's initials
# beside them rather than under them, on one white panel. The panel
# ends short of the name's room (`FRAME + 132`), which stays symmetric.
INDEX_LEFT = FRAME + 18
INDEX_RIGHT = FRAME + 126
INDEX_PAD = 8
INDEX_VALUE_SIZE = 44
INDEX_ROLE_SIZE = 28
# Where the skills' column, the rule between and the role's column
# fall, as shares of the panel's width -- the role is two letters to
# the skills' one digit, so it gets the wider column -- and where the
# two skills sit in its height.
INDEX_SKILLS_X = 0.24
INDEX_DIVIDER_X = 0.45
INDEX_ROLE_X = 0.73
INDEX_SKILL_ROWS = (0.29, 0.71)


def draw_corner_index(
    pen: Pen,
    player: PlayerDefinition,
    skills: "RoleProfile | CardSkills",
) -> None:
    """
    **The card's corner index**, like a playing card's: the two skills
    and the role, top left, where they still show on a card whose face
    is covered -- a bench is three cards cascaded so only each one's
    left edge shows (see "The team board" in
    docs/design/printed-boards.md), and a hand fanned in a coach's grip
    shows the same corner. The stats row under the header still says
    the two skills with their labels; this is the same two numbers in
    the same two colours, for the card that is not lying face up.

    The skills are a column, offence over defence, and the role sits
    beside them (the author, 2026-10-03) -- side by side reads as one
    mark where three lines stacked read as a list, and it lets each be
    set larger in the header's height.

    The panel is white because the numbers are red and green and the
    band is the team's colour: neither reads on orange or purple. The
    role is the badge's initials (`ROLE_INITIALS`), since the role in
    words is under the name and does not fit the corner.
    """
    top = FRAME + INDEX_PAD
    bottom = FRAME + HEADER_HEIGHT - INDEX_PAD
    width = INDEX_RIGHT - INDEX_LEFT
    pen.rect(
        (INDEX_LEFT, top, INDEX_RIGHT, bottom),
        radius=18,
        fill=CARD_FACE,
    )
    value_face = font(INDEX_VALUE_SIZE, bold=True)
    skills_x = INDEX_LEFT + width * INDEX_SKILLS_X
    for value, color, share in zip(
        (skills.offense, skills.defense),
        (CARD_OFFENSE_COLOR, CARD_DEFENSE_COLOR),
        INDEX_SKILL_ROWS,
    ):
        pen.text(
            (skills_x, top + (bottom - top) * share),
            str(value),
            value_face,
            color,
            anchor="mm",
        )
    divider_x = INDEX_LEFT + width * INDEX_DIVIDER_X
    pen.line(
        [(divider_x, top + 16), (divider_x, bottom - 16)],
        fill=PANEL_EDGE,
        width=2,
    )
    pen.text(
        (INDEX_LEFT + width * INDEX_ROLE_X, (top + bottom) / 2),
        ROLE_INITIALS[player.role.value],
        font(INDEX_ROLE_SIZE, bold=True),
        INK,
        anchor="mm",
    )


def header_subtitle(player: PlayerDefinition, advanced: bool) -> str:
    """
    The line under the name: the player's role, and on the back the
    word that says which side of the card this is.

    The back has to announce itself in words rather than by a shade or
    a border, because it is otherwise the same card -- same colour,
    same portrait, same role -- and a coach turning a stack over has
    nothing else to read. The team is the corner emoji and the edge
    colour on both faces.
    """
    role = player.role.value.upper()
    return f"{role} \u00b7 ADVANCED" if advanced else role


@dataclass(frozen=True)
class CardSkills:
    """
    The two numbers a card's stats row prints. Not a `RoleProfile`,
    because an advanced skill is not held to 1-6 (Hellguard's offence is
    0) and a `RoleProfile` refuses one.
    """

    offense: int
    defense: int


def advanced_card_skills(
    catalog: PlayerCatalog, player: PlayerDefinition,
) -> CardSkills:
    """
    The skills the advanced face prints: the role's, with the player's
    own advanced scores laid over them where they have any -- the same
    overlay `RulesEngine.skills` plays in an advanced game (Law 21,
    "Advanced skills").
    """
    profile = catalog.effective_profile(player)
    return CardSkills(
        offense=player.advanced_skills.get("offense", profile.offense),
        defense=player.advanced_skills.get("defense", profile.defense),
    )


def advanced_card_ability(
    catalog: PlayerCatalog, player: PlayerDefinition,
) -> str:
    """
    The sentence the advanced face prints: the player's special
    ability as the sheet words it, or the role's where they have none.
    Never shortened here -- see "Every ability is imported twice".
    """
    return (
        player.advanced_ability
        or catalog.effective_profile(player).ability
    )


def draw_stats(
    pen: Pen,
    profile: "RoleProfile | CardSkills",
    top: float,
) -> None:
    """
    The two skills on one row, each number centred in its half with
    its label on the outside: `OFFENSE 2 | 5 DEFENSE`.

    The bot's card stacks the bare numbers in the corner, unlabelled,
    because a coach reads them off a board they have been looking at
    all game -- but they are the same two numbers in the same two
    colours (`CARD_OFFENSE_COLOR` and `CARD_DEFENSE_COLOR`), so a
    printed 6 and a drawn 6 are the same red.

    The role is not here: the header's badge carries it, and the
    ability band's badge sits beside the ability it grants.
    """
    pen.rect(
        (MARGIN, top, CARD_WIDTH - MARGIN, top + STATS_HEIGHT),
        radius=18,
        fill=PANEL_COLOR,
        outline=PANEL_EDGE,
        width=2,
    )

    column_width = (CARD_WIDTH - MARGIN * 2) / 2
    label_face = font(STATS_LABEL_SIZE, bold=True)
    value_face = font(STATS_VALUE_SIZE, bold=True)
    center_y = top + STATS_HEIGHT / 2
    # Each number is centred in its half, and its label sits on the
    # outside of it -- OFFENSE to the left of the offence, DEFENSE to
    # the right of the defence (the author, 2026-09-27) -- so the two
    # numbers read as a pair either side of the divider.
    columns = (
        ("OFFENSE", str(profile.offense), CARD_OFFENSE_COLOR, -1),
        ("DEFENSE", str(profile.defense), CARD_DEFENSE_COLOR, 1),
    )
    for index, (label, value, color, side) in enumerate(columns):
        cx = MARGIN + column_width * (index + 0.5)
        pen.text((cx, center_y), value, value_face, color, anchor="mm")
        value_half = pen.text_size(value, value_face)[0] / 2
        pen.text(
            (cx + side * (value_half + STATS_LABEL_GAP), center_y),
            label,
            label_face,
            MUTED,
            anchor="rm" if side < 0 else "lm",
        )
    pen.line(
        [
            (MARGIN + column_width, top + 14),
            (MARGIN + column_width, top + STATS_HEIGHT - 14),
        ],
        fill=PANEL_EDGE,
        width=2,
    )


STATS_LABEL_SIZE = 19
STATS_VALUE_SIZE = 70
STATS_LABEL_GAP = 16


# The ability is set larger than a maneuver card's effect, because it
# is the same thing read at a worse angle: the rule the card exists to
# state, on a card lying on a table rather than held up to a face. It
# went from 30 to 36 when the badges replaced the band's heading (the
# author, 2026-09-27: "the font should be larger even if the portrait
# becomes a bit smaller").
#
# **The portrait gives up whatever this takes**, which is the trade the
# author asked for: the picture gets smaller where it has to. Most
# cards do not pay at all, since the art is capped at
# PORTRAIT_MAX_SCALE and was leaving white under itself anyway; the
# long abilities pay a line's worth. The floor is MIN_PORTRAIT_HEIGHT
# below, which is where the trade stops being one: a sentence that
# would cross it is set smaller instead (`ability_band`), down to
# ABILITY_MIN_SIZE.
ABILITY_SIZE = 36
ABILITY_MIN_SIZE = 24
BAND_BADGE = 64
BAND_BADGE_GAP = 18
BAND_TOP_PAD = 22
BAND_ROW_GAP = 18

# The portrait is the reason a player card is a picture at all, so a
# layout leaving it less than this much of a 1050-unit card has stopped
# being a player card and become a paragraph. Both faces are held to
# it; the back's longest special ability is the one that comes
# nearest.
MIN_PORTRAIT_HEIGHT = 380

PORTRAIT_TOP = FRAME + HEADER_HEIGHT + STATS_TOP_GAP + STATS_HEIGHT
ABILITY_BOTTOM_PAD = 18


def portrait_room(ability_height: float) -> float:
    """
    What the portrait is left once an ability band that tall is taken
    off the bottom. The bands are laid out from the two edges in and
    the picture takes what is between them, so this is the one
    arithmetic that says whether a card still works.
    """
    ability_top = CARD_HEIGHT - FRAME - ABILITY_BOTTOM_PAD - ability_height
    return ability_top - PORTRAIT_GAP * 2 - PORTRAIT_TOP


def role_badge(role: PlayerRole, team: Team) -> Image.Image | None:
    """
    The bot's own role emoji with its edge in the card's team colour --
    `role_defender_purple.png`, the badge a message puts beside a
    player fielded for Purple. A species team has no file of its own
    and shares its colour team's, as it shares its hex in `TEAM_COLORS`;
    the plain badge stands in if a file is missing, and nothing at all
    if that is missing too, the swallowed-`OSError` contract every
    bundled image here follows.
    """
    colour = team if team in COLOR_TEAMS else paired_team(team)
    key = (role, colour)
    if key not in _ROLE_BADGES:
        badge = None
        for name in (f"role_{role.value}_{colour.value}", f"role_{role.value}"):
            try:
                badge = Image.open(ROLE_EMOJI_DIR / f"{name}.png").convert(
                    "RGBA"
                )
                break
            except OSError:
                continue
        _ROLE_BADGES[key] = badge
    return _ROLE_BADGES[key]


_ROLE_BADGES: dict[tuple[PlayerRole, Team], Image.Image | None] = {}


def ability_text_width() -> float:
    """The room a band row leaves its text, right of the badge."""
    return CARD_WIDTH - MARGIN * 2 - 20 - BAND_BADGE - BAND_BADGE_GAP


@dataclass(frozen=True)
class AbilityBand:
    """
    The ability band as measured: the sentence wrapped beside its
    badge, the size it is set at, and the height the whole band needs.
    """

    lines: list[str]
    size: int
    height: float


def ability_band(
    pen: Pen, ability: str, species_name: str
) -> AbilityBand:
    """
    The sentence wrapped beside its badge at the largest size, up to
    ABILITY_SIZE, that still leaves the portrait MIN_PORTRAIT_HEIGHT,
    and the height of the whole band -- the sentence's row, and the
    species' row under it where the player has a species. Measured
    before anything is drawn, because the band is laid out from the
    bottom edge up and the portrait above it takes what is left.

    Almost every card is set at ABILITY_SIZE. The few whose sentence
    runs to five lines or more -- special abilities on the back, today
    -- come down a point at a time until the portrait keeps its floor,
    and stop at ABILITY_MIN_SIZE whatever that leaves.
    """
    for size in range(ABILITY_SIZE, ABILITY_MIN_SIZE - 1, -1):
        lines = pen.wrapped(ability, font(size), ability_text_width())
        height = BAND_TOP_PAD + row_height(pen, size, len(lines))
        if species_name:
            height += BAND_ROW_GAP + BAND_BADGE
        if portrait_room(height) >= MIN_PORTRAIT_HEIGHT:
            break
    return AbilityBand(lines, size, height)


def first_line_offset(pen: Pen, size: int) -> float:
    """
    How far below its row's top the sentence's first line starts, so
    that line is centred on the badge: a three-line ability reads as
    one entry hanging off its label, not as a paragraph the badge sits
    beside the middle of.
    """
    return (BAND_BADGE - line_height(pen, font(size))) / 2


def row_height(pen: Pen, size: int, line_count: int) -> float:
    step = line_height(pen, font(size))
    return max(BAND_BADGE, first_line_offset(pen, size) + line_count * step)


def draw_species_badge(
    pen: Pen, species: str, center: tuple[float, float]
) -> None:
    """
    The species icon on a rounded square of the species' colour, the
    same size and shape as the role badge above it. Filled rather than
    the icon set in the colour, for the reason the header band is:
    Slime green on a white face cannot be read, and `high_contrast_ink`
    on a fill answers all four species at once.
    """
    color = TEAM_COLORS[SPECIES_TEAM[species]]
    half = BAND_BADGE / 2
    pen.rect(
        (center[0] - half, center[1] - half, center[0] + half, center[1] + half),
        radius=BAND_BADGE * 0.22,
        fill=color,
    )
    icon = species_icon(species, high_contrast_ink(color))
    if icon is not None:
        size = BAND_BADGE * 0.72
        pen.paste(icon, center, (size, size))


def draw_ability(
    pen: Pen,
    player: PlayerDefinition,
    team: Team,
    band: AbilityBand,
    species_name: str,
    top: float,
) -> None:
    """
    The ability band, the same on both faces: the role's badge beside
    the sentence the face prints, and the species' badge beside the
    species ability's name under it (the author, 2026-09-27). The two
    badges are the labels, so the band carries no heading.

    The sentence is the role's on the front and the player's advanced
    ability on the back (`advanced_card_ability`) -- the badge in front
    of it is the role's on both, since a special ability belongs to a
    player of that role. Only the species ability's *name* is here; its
    rules are on the species reference cards.

    The band is laid out from the bottom edge up, so the species row is
    in the same place on every card of either face, whatever the
    sentence above it runs to.
    """
    pen.line(
        [(MARGIN + 10, top), (CARD_WIDTH - MARGIN - 10, top)],
        fill=PANEL_EDGE,
        width=2,
    )

    body = font(band.size)
    step = line_height(pen, body)
    badge_x = MARGIN + 10 + BAND_BADGE / 2
    text_x = MARGIN + 10 + BAND_BADGE + BAND_BADGE_GAP
    y = top + BAND_TOP_PAD

    badge = role_badge(player.role, team)
    if badge is not None:
        pen.paste(
            badge, (badge_x, y + BAND_BADGE / 2), (BAND_BADGE, BAND_BADGE)
        )
    text_y = y + first_line_offset(pen, band.size)
    for line in band.lines:
        pen.text((text_x, text_y), line, body, INK, anchor="la")
        text_y += step

    if not species_name:
        return
    y += row_height(pen, band.size, len(band.lines)) + BAND_ROW_GAP
    center_y = y + BAND_BADGE / 2
    draw_species_badge(pen, player.species, (badge_x, center_y))
    pen.text(
        (text_x, center_y),
        species_name,
        font(ABILITY_SIZE, bold=True),
        INK,
        anchor="lm",
    )


def species_ability(species: str) -> dict[str, str]:
    """
    One species' entry from `species.json`, or an empty one for a
    player whose species the catalog does not carry -- which is a
    `players.json` written before the column existed, not a fifth kind
    of species. Every caller here is drawing something optional, so an
    empty answer draws nothing rather than raising.
    """
    return _species_abilities().get(species, {})


#: The sentence of a species' short ability that is about a skill test
#: alone -- Volatile's upgrade. A reminder beside any other roll (a
#: shot, a contest) drops it, since it says nothing there (the author,
#: 2026-09-30); the card and the reference keep the whole text.
SKILL_TEST_SENTENCE = "In a skill test"


def species_ability_reminder(species: str, skill_test: bool) -> str:
    """
    A species' short ability as a roll reminds of it: the sheet's own
    words, with the sentence that opens "In a skill test" dropped
    unless the roll is one. Nothing is reworded; a text without that
    sentence comes back whole.
    """
    text = species_ability(species).get("ability_short", "")
    if skill_test:
        return text
    head, found, _ = text.partition(f" {SKILL_TEST_SENTENCE}")
    return head.rstrip() if found else text


def _species_abilities() -> dict[str, dict[str, str]]:
    global _SPECIES_ABILITIES
    if _SPECIES_ABILITIES is None:
        _SPECIES_ABILITIES = load_species_abilities()
    return _SPECIES_ABILITIES


# Read once and kept, rather than at import: this module is imported by
# the render scripts and by the box art, and a card is drawn seventy-two
# times a run.
_SPECIES_ABILITIES: dict[str, dict[str, str]] | None = None


def draw_portrait(
    pen: Pen,
    player: PlayerDefinition,
    top: float,
    bottom: float,
) -> None:
    """
    The portrait, centred in what the two bands leave. Skipped without
    complaint when the player has no art, exactly as the bot's card
    does -- a card naming a player the roster knows is worth more than
    no card at all.
    """
    portrait = load_player_portrait(player.name)
    if portrait is None:
        return

    # A card unit is a printed pixel, so the cap is read against the
    # portrait's own pixels: 1.6 is how much larger than the file the
    # picture is allowed to print.
    scale = min(
        (CARD_WIDTH - MARGIN * 2 - 16) / portrait.width,
        (bottom - top) / portrait.height,
        PORTRAIT_MAX_SCALE,
    )
    size = (portrait.width * scale, portrait.height * scale)
    pen.paste(portrait, (CARD_WIDTH / 2, (top + bottom) / 2), size)


def start_card(color: str) -> Pen:
    """
    A blank card with its edge drawn. The rounded outline in the team's
    colour is the card's edge and the cut line at once, as it is on a
    maneuver card -- with the face and the sheet both white there is
    nothing else to say where the card ends.
    """
    pen = Pen((CARD_WIDTH, CARD_HEIGHT), CARD_FACE)
    pen.rect(
        (FRAME, FRAME, CARD_WIDTH - FRAME, CARD_HEIGHT - FRAME),
        radius=CORNER,
        fill=CARD_FACE,
        outline=color,
        width=EDGE_WIDTH,
    )
    return pen


def draw_face(
    pen: Pen,
    player: PlayerDefinition,
    team: Team,
    subtitle: str,
    skills: "RoleProfile | CardSkills",
    ability: str,
) -> None:
    """
    Everything on a face but its edge, top to bottom: the header, the
    stats, the ability band measured first and pinned to the bottom,
    and the portrait in what is left between them. The two faces
    differ only in the three things they are handed.
    """
    color = TEAM_COLORS[Team(team)]
    draw_header(pen, player, team, color, subtitle)
    draw_corner_index(pen, player, skills)
    draw_stats(pen, skills, FRAME + HEADER_HEIGHT + STATS_TOP_GAP)

    species_name = species_ability(player.species).get("name", "")
    band = ability_band(pen, ability, species_name)
    ability_top = CARD_HEIGHT - FRAME - ABILITY_BOTTOM_PAD - band.height
    draw_portrait(
        pen, player, PORTRAIT_TOP + PORTRAIT_GAP, ability_top - PORTRAIT_GAP
    )
    draw_ability(pen, player, team, band, species_name, ability_top)


def render_player_card(
    catalog: PlayerCatalog,
    player: PlayerDefinition,
    team: Team,
    bleed: bool,
) -> Image.Image:
    """
    One player's card, printed as a member of `team`. A dual-membership
    player -- every player, since the 2026-08-17 eight-team split -- has
    no team of their own to read this off (`PlayerDefinition` carries
    none), so which of their two rosters the card is drawn for is the
    caller's to say. Printing one card per (player, team) pair a player
    belongs to is just calling this twice with the two teams
    `PlayerCatalog.teams` names them under -- no special-casing.
    """
    profile = catalog.effective_profile(player)
    pen = start_card(TEAM_COLORS[Team(team)])
    draw_face(
        pen,
        player,
        team,
        header_subtitle(player, False),
        profile,
        profile.ability,
    )
    return pen.finish(bleed, CARD_FACE)


def render_player_card_back(
    catalog: PlayerCatalog,
    player: PlayerDefinition,
    team: Team,
    bleed: bool,
) -> Image.Image:
    """
    The same player's advanced card -- the other side of the card
    above, not a shared back: these are dealt face up and there is
    nothing about a player to hide.

    What makes it the advanced one is what advanced mode plays for this
    player: their advanced skills in the stats row, and their special
    ability in the band where they have one (`advanced_card_skills`,
    `advanced_card_ability`; see the module docstring). Otherwise it is
    laid out exactly as the front (the author, 2026-09-27).
    """
    pen = start_card(TEAM_COLORS[Team(team)])
    draw_face(
        pen,
        player,
        team,
        header_subtitle(player, True),
        advanced_card_skills(catalog, player),
        advanced_card_ability(catalog, player),
    )
    return pen.finish(bleed, CARD_FACE)


# A team is nine players, so a team's sheet is three across and three
# down: nine cards to a page, which is what a poker-sized card and an
# A4 or letter sheet come out at. It is printed duplex, so it is the
# duplex width; `duplex_order` (in `cards.py`, beside `print_sheet`,
# since the maneuver and reference sheets print duplex too) is imported
# here so the name a team's sheet was built with still answers.
TEAM_SHEET_COLUMNS = DUPLEX_COLUMNS
