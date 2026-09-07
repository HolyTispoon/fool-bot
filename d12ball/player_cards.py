"""
The roster as cards, print-ready for the tabletop game.

One card a player -- 2.5 x 3.5 inches at 300dpi, the same poker size
and the same print machinery as `d12ball/cards.py`, which this borrows
`Pen`, the sheet and the palette from. A coach at the table and a coach
playing by Discord should be reading the same card, so the layout
follows the one the bot draws on the board (`build_player_card` in
`d12ball/render.py`): the name, the two skills in their own two
colours, the role, and the portrait under them, inside the team's
colour.

**What the printed card adds is the ability**, under the portrait. The
bot has the board to put it on -- a coach can ask for the roster or the
rules -- where a card on a table is the only thing in front of its
coach, so the sentence has to be on it. It is the full sentence from
`players.json` and never the short form: see "Every ability is imported
twice" in CLAUDE.md.

Nothing here is written in the module. The names, roles, skills and
abilities all come from `players.json` through `load_player_catalog`,
so a card cannot claim a stat the bot does not play, and an import
reaches the cards by re-running `scripts/render_player_cards.py`.

**The other side of the card is the same player in advanced mode** --
not a shared back, since these are dealt face up and nothing about
them is hidden. `render_player_card_back` draws it: the same header,
skills and portrait, with the keyword of the player's species ability
set beside their role ability and the species' short form under it
where the card has room for it.

What the back is still waiting on is an *advanced role* ability. The
sheet's `Advanced` column is empty for all thirty-six, so the band
repeats the basic sentence rather than inventing one; see "Blocked or
deferred" in docs/rules-log.md. When that column fills, the role half
of the band is the only thing that changes.
"""
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
    RoleProfile,
    load_species_abilities,
)
from d12ball.game import Team, team_display_name
from d12ball.render import (
    CARD_DEFENSE_COLOR,
    CARD_OFFENSE_COLOR,
    ROLE_INITIALS,
    TEAM_COLORS,
    high_contrast_ink,
    load_player_portrait,
    species_icon,
)
from d12ball.species_cards import SPECIES_TEAM

# The header band, and the stats panel under it. Both are fixed: the
# portrait takes whatever the ability band leaves, because the ability
# is the one thing on the card whose length is not the layout's to
# choose.
HEADER_HEIGHT = 132
STATS_TOP_GAP = 20
STATS_HEIGHT = 132
PORTRAIT_GAP = 18

# The species icon in the header, mirroring the role badge across the
# band: the two things about a player that are not their name are the
# job they do and what they are, and both are read at a glance from
# the same row. It is drawn in the band's own ink rather than the
# species' colour, because the band is already a colour -- see
# `high_contrast_ink`, which is what keeps a Slime-green band legible.
HEADER_ICON = 84

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
    break -- the size comes down until "Flickerwing" fits between the
    role badge and the species icon, floored at 22 even if that still
    doesn't.
    """
    return (
        fitted_bold_font(pen, name, max_width, max_size=54, min_size=22)
        or font(22, bold=True)
    )


def draw_header(
    pen: Pen,
    player: PlayerDefinition,
    team: Team,
    color: str,
    subtitle: str,
) -> None:
    """
    The team-coloured band: the role's initials in a badge on the left,
    the species icon answering it on the right, and the name over
    `subtitle` between them. The initials are the board's own
    (`ROLE_INITIALS`), so the two letters on the card are the two
    letters on the meeple's card in Discord.

    The name and the subtitle are stacked because the icon took the
    room the team used to sit in, and the two lines are what tell a
    front from its advanced back at a glance -- see
    `header_subtitle`.

    A player with no species draws no icon and the layout does not
    close up around it, because `players.json` written before the
    species column loads with an empty one (see "Player species" in
    CLAUDE.md) and a set of cards where some names are centred
    differently from others reads as a mistake.
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

    badge_center = (FRAME + 78, FRAME + HEADER_HEIGHT / 2)
    pen.circle(badge_center, 44, fill=CARD_FACE)
    pen.text(
        badge_center,
        ROLE_INITIALS[player.role.value],
        font(36, bold=True),
        color,
        anchor="mm",
    )

    icon = species_icon(player.species, high_contrast_ink(color))
    if icon is not None:
        pen.paste(
            icon,
            (CARD_WIDTH - FRAME - 78, FRAME + HEADER_HEIGHT / 2),
            (HEADER_ICON, HEADER_ICON),
        )

    name_left = FRAME + 132
    name_right = CARD_WIDTH - FRAME - 132
    pen.text(
        ((name_left + name_right) / 2, FRAME + 54),
        player.name,
        fitted_name(pen, player.name, name_right - name_left),
        "#ffffff",
        anchor="mm",
    )
    pen.text(
        ((name_left + name_right) / 2, FRAME + 104),
        subtitle,
        font(16, bold=True),
        "#ffffff",
        anchor="mm",
    )


def header_subtitle(team: Team, advanced: bool) -> str:
    """
    The line under the name: the team, and on the back the word that
    says which side of the card this is.

    The back has to announce itself in words rather than by a shade or
    a border, because it is otherwise the same card -- same colour,
    same portrait, same skills -- and a coach turning a stack over has
    nothing else to read. The team stays on both faces: the edge colour
    says it too, but a card printed for one of a player's two rosters
    should say which on whichever side is showing.
    """
    name = team_display_name(team).upper()
    return f"{name} \u00b7 ADVANCED" if advanced else name


def draw_stats(
    pen: Pen,
    player: PlayerDefinition,
    profile: RoleProfile,
    top: float,
) -> None:
    """
    The two skills either side of the role, each under its own label.

    The bot's card stacks the bare numbers in the corner, unlabelled,
    because a coach reads them off a board they have been looking at
    all game -- but they are the same two numbers in the same two
    colours (`CARD_OFFENSE_COLOR` and `CARD_DEFENSE_COLOR`), so a
    printed 6 and a drawn 6 are the same red.
    """
    pen.rect(
        (MARGIN, top, CARD_WIDTH - MARGIN, top + STATS_HEIGHT),
        radius=18,
        fill=PANEL_COLOR,
        outline=PANEL_EDGE,
        width=2,
    )

    column_width = (CARD_WIDTH - MARGIN * 2) / 3
    columns = (
        ("OFFENSE", str(profile.offense), CARD_OFFENSE_COLOR),
        ("ROLE", player.role.value.upper(), INK),
        ("DEFENSE", str(profile.defense), CARD_DEFENSE_COLOR),
    )
    for index, (label, value, color) in enumerate(columns):
        cx = MARGIN + column_width * (index + 0.5)
        pen.text(
            (cx, top + 32), label, font(17, bold=True), MUTED, anchor="mm"
        )
        # The role is a word where the skills are a digit, so it is set
        # small enough for "MIDFIELDER" to clear the dividers.
        face = font(24 if index == 1 else 64, bold=True)
        pen.text((cx, top + 84), value, face, color, anchor="mm")
        if index:
            pen.line(
                [
                    (MARGIN + column_width * index, top + 16),
                    (MARGIN + column_width * index, top + STATS_HEIGHT - 16),
                ],
                fill=PANEL_EDGE,
                width=2,
            )


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
# "The species cards" in CLAUDE.md), and a player's card carrying two
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


def ability_lines(pen: Pen, ability: str) -> tuple[list[str], float]:
    """
    The ability wrapped to the card, and the height the band it sits in
    needs. Measured before anything is drawn, because the band is laid
    out from the bottom edge up and the portrait above it takes what is
    left: a two-line ability and a four-line one are different cards.
    """
    body = font(ABILITY_SIZE)
    lines = pen.wrapped(ability, body, CARD_WIDTH - MARGIN * 2 - 12)
    height = 50 + len(lines) * line_height(pen, body) + 12
    return lines, height


def draw_ability(pen: Pen, lines: list[str], top: float) -> None:
    pen.line(
        [(MARGIN + 10, top), (CARD_WIDTH - MARGIN - 10, top)],
        fill=PANEL_EDGE,
        width=2,
    )
    pen.text(
        (CARD_WIDTH / 2, top + 26),
        "ABILITY",
        font(ABILITY_HEADING_SIZE, bold=True),
        MUTED,
        anchor="mm",
    )

    body = font(ABILITY_SIZE)
    y = top + 50
    for line in lines:
        pen.text((CARD_WIDTH / 2, y), line, body, INK, anchor="ma")
        y += line_height(pen, body)


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
# the render scripts and by the suite, and a card is drawn seventy-two
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
    id -- see "One player, both sides" in CLAUDE.md.
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
    long its *role* ability runs, so asked per card the answer comes
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
            pen, catalog.effective_profile(player).ability, short
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
    species icon in front of it -- the same icon the header carries, so
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

    draw_header(pen, player, team, color, header_subtitle(team, False))
    draw_stats(pen, player, profile, FRAME + HEADER_HEIGHT + STATS_TOP_GAP)

    lines, ability_height = ability_lines(pen, profile.ability)
    ability_top = (
        CARD_HEIGHT - FRAME - ABILITY_BOTTOM_PAD - ability_height
    )
    draw_portrait(
        pen, player, PORTRAIT_TOP + PORTRAIT_GAP, ability_top - PORTRAIT_GAP
    )
    draw_ability(pen, lines, ability_top)

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

    What makes it the advanced one is the species keyword beside the
    role ability, since a species ability is only ever in play in an
    advanced game (see "Species abilities in the bot" in CLAUDE.md).
    The role sentence itself is still the basic one, because the
    sheet's `Advanced` ability column is empty for all thirty-six --
    the band's role half is what changes when it fills.

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
    profile = catalog.effective_profile(player)
    color = TEAM_COLORS[Team(team)]
    pen = start_card(color)

    draw_header(pen, player, team, color, header_subtitle(team, True))
    draw_stats(pen, player, profile, FRAME + HEADER_HEIGHT + STATS_TOP_GAP)

    short = (
        species_ability(player.species)["ability_short"]
        if species_short_fits(pen, catalog, player.species)
        else ""
    )
    role_lines, short_lines, _ = advanced_ability_lines(
        pen, profile.ability, short
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
