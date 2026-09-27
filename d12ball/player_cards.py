"""
The roster as cards, print-ready for the tabletop game.

One card a player -- 2.5 x 3.5 inches at 300dpi, the same poker size
and the same print machinery as `d12ball/cards.py`, which this borrows
`Pen`, the sheet and the palette from. A coach at the table and a coach
playing by Discord should be reading the same card, so the layout
follows the one the bot draws on the board (`build_player_card` in
`d12ball/render.py`): the name, the two skills in their own two
colours, the role's badge, and the portrait under them, inside the
team's colour.

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
them is hidden. `render_player_card_back` draws it: the same header and
portrait, **the player's advanced skills** in the stats row, and **their
personal ability instead of the role's** where they have one (Law 21;
the author, 2026-09-25), with the keyword of their species ability
beside it and the species' short form under it where the card has room.

The personal ability replaces the role's *on the card only*: in play a
player keeps both (the author, 2026-09-25), and the role's sentence is
on the front. A player whose sheet sentence only names their higher
skill ("High defensive skill.") prints that sentence, as the sheet words
it; the numbers above it say how high. A player with no personal
ability prints their role's sentence on both faces.
"""
from dataclasses import dataclass

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

    emoji = team_emoji(team)
    if emoji is not None:
        pen.paste(
            emoji,
            (CARD_WIDTH - FRAME - 78, FRAME + HEADER_HEIGHT / 2),
            (HEADER_EMOJI, HEADER_EMOJI),
        )

    name_left = FRAME + 132
    name_right = CARD_WIDTH - FRAME - 132
    pen.text(
        ((name_left + name_right) / 2, FRAME + 50),
        player.name,
        fitted_name(pen, player.name, name_right - name_left),
        "#ffffff",
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
        "#ffffff",
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
    The sentence the advanced face prints: the player's personal
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


# The ability is set a shade larger than a maneuver card's effect,
# because it is the same thing read at a worse angle: the rule the card
# exists to state, on a card lying on a table rather than held up to a
# face. It started at the size a maneuver card lists a *role's* ability
# at -- but there it is a footnote under the effect, and here there is
# nothing else on the card to be a footnote to.
#
# **The portrait gives up whatever this takes**, which is the trade the
# author asked for: the picture gets smaller where it has to. Most
# cards do not pay at all, since the art is capped at
# PORTRAIT_MAX_SCALE and was leaving white under itself anyway; the
# long abilities pay a line's worth. The floor is MIN_PORTRAIT_HEIGHT
# below, which is where the trade stops being one.
ABILITY_SIZE = 30
ABILITY_HEADING_SIZE = 19

# The front's band is set larger again, with a badge in front of each
# row in place of a heading (the author, 2026-09-27: "the font should
# be larger even if the portrait becomes a bit smaller"). The one-row
# stats panel paid for most of it; the longest role ability, three
# lines, still leaves the portrait well above MIN_PORTRAIT_HEIGHT.
FRONT_ABILITY_SIZE = 36
BAND_BADGE = 64
BAND_BADGE_GAP = 18
BAND_TOP_PAD = 22
BAND_ROW_GAP = 18

# The species half of the advanced card. The keyword rides in a pill on
# the ability band's heading row -- literally next to the role ability,
# which is what the author asked for -- and the pill is filled with the
# species' own colour for the reason the header band is: Slime green on
# a white face is unreadable, and `high_contrast_ink` on a filled pill
# solves all four species at once rather than three of them.
SPECIES_KEYWORD_SIZE = 26
SPECIES_CHIP_ICON = 38
SPECIES_CHIP_PAD = 16
SPECIES_CHIP_HEIGHT = 50

# The species' short form, under the role ability where there is room
# for it. This is the one place a card is allowed to carry an
# abbreviation, and it is not the role's: `ability_short` in
# species.json exists for "anywhere the sentence does not fit" (see
# "The species cards" in docs/design/cards.md), and a player's card carrying two
# full ability paragraphs is exactly that. The role's own sentence is
# never cut -- see "Every ability is imported twice".
SPECIES_SHORT_SIZE = 23
SPECIES_SHORT_GAP = 18

# The portrait is the reason a player card is a picture at all, so a
# layout leaving it less than this much of a 1050-unit card has stopped
# being a player card and become a paragraph.
MIN_PORTRAIT_HEIGHT = 380

PORTRAIT_TOP = FRAME + HEADER_HEIGHT + STATS_TOP_GAP + STATS_HEIGHT
ABILITY_BOTTOM_PAD = 18

# **The back's ability band starts at a fixed height, where the front's
# floats.** The species badge rides that band's heading row, and the
# author's call is that it be in the same place on every card -- a
# marker a coach finds by looking at one spot cannot be a marker that
# moves with how long the player's role ability happens to run.
#
# That costs the thing the front's design is built on: on the front the
# portrait takes whatever the ability leaves, so a short ability buys a
# bigger picture. Here it cannot, because the picture's bottom edge is
# what the badge's position *is*. Every back gets the same portrait
# slot and the same band, and a card whose text does not fill the band
# leaves white under it.
#
# The height is what today's fullest back needs with a few units over
# -- and it is not tuned to stay ahead of the data, because nothing
# overflows it: a species whose short form no longer fits simply stops
# carrying one (`species_short_fits`). What has to fit unconditionally
# is the role ability alone, which is 153 units against 340.
ADVANCED_BAND_TOP = 686
ADVANCED_BAND_HEIGHT = CARD_HEIGHT - FRAME - ABILITY_BOTTOM_PAD - (
    ADVANCED_BAND_TOP
)

# The back's own floor, and lower than the front's on purpose. The
# front is the picture face and the back is the rules face -- it
# carries a second ability where the front carries one -- so the
# 20-unit difference is what buys every species its short form on a
# band that no longer moves. Anything below this and the portrait has
# stopped being the point of the card, on either face.
MIN_BACK_PORTRAIT_HEIGHT = 360


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
    """The room a front-band row leaves its text, right of the badge."""
    return CARD_WIDTH - MARGIN * 2 - 20 - BAND_BADGE - BAND_BADGE_GAP


def ability_lines(
    pen: Pen, ability: str, species_name: str
) -> tuple[list[str], float]:
    """
    The role ability wrapped beside its badge, and the height the whole
    band needs -- the role's row, and the species' row under it where
    the player has a species. Measured before anything is drawn,
    because the band is laid out from the bottom edge up and the
    portrait above it takes what is left: a two-line ability and a
    four-line one are different cards.
    """
    body = font(FRONT_ABILITY_SIZE)
    lines = pen.wrapped(ability, body, ability_text_width())
    height = BAND_TOP_PAD + role_row_height(pen, len(lines))
    if species_name:
        height += BAND_ROW_GAP + BAND_BADGE
    return lines, height


def first_line_offset(pen: Pen) -> float:
    """
    How far below its row's top the role ability's first line starts,
    so that line is centred on the badge: a three-line ability reads as
    one entry hanging off its label, not as a paragraph the badge sits
    beside the middle of.
    """
    return (BAND_BADGE - line_height(pen, font(FRONT_ABILITY_SIZE))) / 2


def role_row_height(pen: Pen, line_count: int) -> float:
    step = line_height(pen, font(FRONT_ABILITY_SIZE))
    return max(BAND_BADGE, first_line_offset(pen) + line_count * step)


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
    lines: list[str],
    species_name: str,
    top: float,
) -> None:
    """
    The front's ability band: the role's badge beside the role's
    sentence, and the species' badge beside the species ability's name
    under it (the author, 2026-09-27). The two badges are the labels,
    so the band carries no heading: a coach reads which ability is the
    role's and which the species' off the same two pictures the header
    and the board carry.

    Only the species ability's *name* is here. Its rules are on the
    species reference cards, and the front is the picture face; the
    back is where a player's abilities are spelled out.
    """
    pen.line(
        [(MARGIN + 10, top), (CARD_WIDTH - MARGIN - 10, top)],
        fill=PANEL_EDGE,
        width=2,
    )

    body = font(FRONT_ABILITY_SIZE)
    step = line_height(pen, body)
    badge_x = MARGIN + 10 + BAND_BADGE / 2
    text_x = MARGIN + 10 + BAND_BADGE + BAND_BADGE_GAP
    y = top + BAND_TOP_PAD

    badge = role_badge(player.role, team)
    if badge is not None:
        pen.paste(
            badge, (badge_x, y + BAND_BADGE / 2), (BAND_BADGE, BAND_BADGE)
        )
    text_y = y + first_line_offset(pen)
    for line in lines:
        pen.text((text_x, text_y), line, body, INK, anchor="la")
        text_y += step

    if not species_name:
        return
    y += role_row_height(pen, len(lines)) + BAND_ROW_GAP
    center_y = y + BAND_BADGE / 2
    draw_species_badge(pen, player.species, (badge_x, center_y))
    pen.text(
        (text_x, center_y),
        species_name,
        font(FRONT_ABILITY_SIZE, bold=True),
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


def _species_abilities() -> dict[str, dict[str, str]]:
    global _SPECIES_ABILITIES
    if _SPECIES_ABILITIES is None:
        _SPECIES_ABILITIES = load_species_abilities()
    return _SPECIES_ABILITIES


# Read once and kept, rather than at import: this module is imported by
# the render scripts and by the box art, and a card is drawn seventy-two
# times a run.
_SPECIES_ABILITIES: dict[str, dict[str, str]] | None = None


def advanced_ability_lines(
    pen: Pen, ability: str, short: str
) -> tuple[list[str], list[str], float]:
    """
    The advanced band's two halves and the height they need: the role
    ability, and the species' short form under it when `short` is
    given.

    The caller decides whether to ask for the short form at all --
    `render_player_card_back` measures the band both ways and keeps the
    fuller one the portrait can still afford. Measuring here and
    deciding there is what keeps the floor a single number: this
    function only ever answers how tall a given band is.
    """
    body = font(ABILITY_SIZE)
    role_lines = pen.wrapped(ability, body, CARD_WIDTH - MARGIN * 2 - 12)
    height = 50 + len(role_lines) * line_height(pen, body) + 12

    short_lines: list[str] = []
    if short:
        small = font(SPECIES_SHORT_SIZE)
        short_lines = pen.wrapped(short, small, CARD_WIDTH - MARGIN * 2 - 12)
        height += (
            SPECIES_SHORT_GAP * 2
            + 2
            + len(short_lines) * line_height(pen, small)
        )

    return role_lines, short_lines, height


def species_players(catalog: PlayerCatalog, species: str):
    """
    Every player of a species, once each. A player is on two rosters
    (their colour team and their species team), so the walk dedupes by
    id -- see "One player, both sides" in docs/design/teams-and-players.md.
    """
    seen: set[str] = set()
    for roster in catalog.teams.values():
        for player in roster.players:
            if player.species == species and player.player_id not in seen:
                seen.add(player.player_id)
                yield player


def species_short_fits(
    pen: Pen, catalog: PlayerCatalog, species: str
) -> bool:
    """
    Whether every card of this species can carry the species' short
    form and still leave MIN_PORTRAIT_HEIGHT to the portrait.

    **Asked of the species rather than of the card**, which is the
    whole point: how much of the band a card has left depends on how
    long the ability it prints runs (`advanced_card_ability`), so asked per card the answer comes
    out differently for a Fire Demon fullback and a Fire Demon striker
    -- and a set where two cards carrying the same species line
    disagree about whether it is on there reads as a misprint rather
    than as a layout that scaled. The longest role ability of the
    species decides for all of them.

    It is measured against the band rather than against the portrait,
    because the band is fixed now (see `ADVANCED_BAND_TOP`) and the
    portrait no longer moves to make room. So this cannot overflow a
    card: a species whose short form stops fitting stops carrying one,
    and the cards go on printing.

    Cached per species: the data does not move inside a run, and this
    walks the whole roster.
    """
    if species in _SPECIES_SHORT_FITS:
        return _SPECIES_SHORT_FITS[species]

    short = species_ability(species).get("ability_short", "")
    players = list(species_players(catalog, species))
    fits = bool(short and players) and all(
        advanced_ability_lines(
            pen, advanced_card_ability(catalog, player), short
        )[2]
        <= ADVANCED_BAND_HEIGHT
        for player in players
    )

    _SPECIES_SHORT_FITS[species] = fits
    return fits


_SPECIES_SHORT_FITS: dict[str, bool] = {}


def draw_species_chip(
    pen: Pen, species: str, keyword: str, center_y: float
) -> None:
    """
    The keyword in a pill on the right of the heading row, with the
    species icon in front of it -- the same icon the front's species badge carries, so
    a coach matches the two without reading either.

    Measured out from the right edge rather than laid out left to
    right, because the pill is what has to end flush with the band
    above and below it; "LITHIUM POWERED" and "SLIMEY" are very
    different widths and neither may drift off the edge.
    """
    color = TEAM_COLORS[SPECIES_TEAM[species]]
    ink = high_contrast_ink(color)
    face = font(SPECIES_KEYWORD_SIZE, bold=True)

    text_width = pen.text_size(keyword, face)[0]
    width = (
        SPECIES_CHIP_PAD * 2 + SPECIES_CHIP_ICON + 12 + text_width
    )
    right = CARD_WIDTH - MARGIN - 10
    left = right - width

    pen.rect(
        (
            left,
            center_y - SPECIES_CHIP_HEIGHT / 2,
            right,
            center_y + SPECIES_CHIP_HEIGHT / 2,
        ),
        radius=SPECIES_CHIP_HEIGHT / 2,
        fill=color,
    )

    icon = species_icon(species, ink)
    if icon is not None:
        pen.paste(
            icon,
            (left + SPECIES_CHIP_PAD + SPECIES_CHIP_ICON / 2, center_y),
            (SPECIES_CHIP_ICON, SPECIES_CHIP_ICON),
        )
    pen.text(
        (right - SPECIES_CHIP_PAD, center_y),
        keyword,
        face,
        ink,
        anchor="rm",
    )


def draw_advanced_ability(
    pen: Pen,
    player: PlayerDefinition,
    role_lines: list[str],
    short_lines: list[str],
    top: float,
) -> None:
    """
    The back's ability band: "ABILITY" and the species keyword on one
    row, the role's own sentence under them, and the species' short
    form under a divider where the card had room for it.

    The role ability is left-aligned here where the front centres it,
    because the heading row above it is now two things at two edges and
    a centred paragraph under that reads as belonging to neither.
    """
    pen.line(
        [(MARGIN + 10, top), (CARD_WIDTH - MARGIN - 10, top)],
        fill=PANEL_EDGE,
        width=2,
    )
    pen.text(
        (MARGIN + 10, top + 26),
        "ABILITY",
        font(ABILITY_HEADING_SIZE, bold=True),
        MUTED,
        anchor="lm",
    )

    keyword = species_ability(player.species).get("name", "")
    if keyword:
        draw_species_chip(pen, player.species, keyword.upper(), top + 26)

    body = font(ABILITY_SIZE)
    y = top + 50
    for line in role_lines:
        pen.text((MARGIN + 10, y), line, body, INK, anchor="la")
        y += line_height(pen, body)

    if not short_lines:
        return

    y += SPECIES_SHORT_GAP
    pen.line(
        [(MARGIN + 10, y), (CARD_WIDTH - MARGIN - 10, y)],
        fill=PANEL_EDGE,
        width=2,
    )
    y += SPECIES_SHORT_GAP + 2

    small = font(SPECIES_SHORT_SIZE)
    for line in short_lines:
        pen.text((MARGIN + 10, y), line, small, MUTED, anchor="la")
        y += line_height(pen, small)


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
    color = TEAM_COLORS[Team(team)]
    pen = start_card(color)

    draw_header(pen, player, team, color, header_subtitle(player, False))
    draw_stats(pen, profile, FRAME + HEADER_HEIGHT + STATS_TOP_GAP)

    species_name = species_ability(player.species).get("name", "")
    lines, ability_height = ability_lines(pen, profile.ability, species_name)
    ability_top = (
        CARD_HEIGHT - FRAME - ABILITY_BOTTOM_PAD - ability_height
    )
    draw_portrait(
        pen, player, PORTRAIT_TOP + PORTRAIT_GAP, ability_top - PORTRAIT_GAP
    )
    draw_ability(pen, player, team, lines, species_name, ability_top)

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
    player: their advanced skills in the stats row, and their personal
    ability in the band where they have one (`advanced_card_skills`,
    `advanced_card_ability`; see the module docstring), with the
    species keyword beside it.

    **The ability band starts at a fixed height on this face**, so the
    species badge on its heading row is in the same place on every card
    in the set -- see `ADVANCED_BAND_TOP` for what that costs. The
    portrait slot is therefore the same on every back too, rather than
    being whatever the ability left.

    **The short form is carried only where the band has room for it**,
    and that is decided for the whole species at once rather than card
    by card -- see `species_short_fits`. Which species carry the extra
    line is decided by the data rather than by a list here.
    """
    color = TEAM_COLORS[Team(team)]
    pen = start_card(color)

    draw_header(pen, player, team, color, header_subtitle(player, True))
    draw_stats(
        pen,
        advanced_card_skills(catalog, player),
        FRAME + HEADER_HEIGHT + STATS_TOP_GAP,
    )

    short = (
        species_ability(player.species)["ability_short"]
        if species_short_fits(pen, catalog, player.species)
        else ""
    )
    role_lines, short_lines, _ = advanced_ability_lines(
        pen, advanced_card_ability(catalog, player), short
    )

    draw_portrait(
        pen,
        player,
        PORTRAIT_TOP + PORTRAIT_GAP,
        ADVANCED_BAND_TOP - PORTRAIT_GAP,
    )
    draw_advanced_ability(
        pen, player, role_lines, short_lines, ADVANCED_BAND_TOP
    )

    return pen.finish(bleed, CARD_FACE)


# A team is nine players, so a team's sheet is three across and three
# down: nine cards to a page, which is what a poker-sized card and an
# A4 or letter sheet come out at. The maneuvers print four across
# because there are seven of them, not because four is the number.
TEAM_SHEET_COLUMNS = 3


def duplex_order(
    cards: list[Image.Image], columns: int = TEAM_SHEET_COLUMNS
) -> list[Image.Image]:
    """
    The backs in the order a duplex printer wants them: each row
    reversed, and the rows themselves left alone.

    A sheet printed on both sides comes out of the printer flipped
    about the paper's long edge, so the leftmost cell of a row on the
    front is the rightmost cell of that row on the back. Reversing
    every row is the whole of the correction -- a maneuver deck never
    needed it because all thirteen of its backs are the same picture,
    where every one of these is a different player and landing the
    wrong one behind a card is not something a print run recovers
    from.

    A short last row is reversed as it stands, which is right:
    `print_sheet` pads a short row at its *end*, so on the back that
    padding lands at the start of the row and the cards keep their
    columns. A team is nine cards three across, so this does not come
    up today.
    """
    rows = [
        cards[start:start + columns]
        for start in range(0, len(cards), columns)
    ]
    return [card for row in rows for card in reversed(row)]
