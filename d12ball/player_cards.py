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
them is hidden. It is not drawn here because advanced mode is
unspecified and the sheet's `Advanced` ability column is empty for
every player, so the cards print one-sided; see "Blocked or deferred"
in docs/rules-log.md.
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
    font,
    line_height,
)
from d12ball.components import PlayerCatalog, PlayerDefinition, RoleProfile
from d12ball.game import Team, team_display_name
from d12ball.render import (
    CARD_DEFENSE_COLOR,
    CARD_OFFENSE_COLOR,
    ROLE_INITIALS,
    TEAM_COLORS,
    load_player_portrait,
)

# The header band, and the stats panel under it. Both are fixed: the
# portrait takes whatever the ability band leaves, because the ability
# is the one thing on the card whose length is not the layout's to
# choose.
HEADER_HEIGHT = 132
STATS_TOP_GAP = 20
STATS_HEIGHT = 132
PORTRAIT_GAP = 18

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
    role badge and the team.
    """
    for size in range(54, 21, -2):
        face = font(size, bold=True)
        if pen.text_size(name, face)[0] <= max_width:
            return face
    return font(22, bold=True)


def draw_header(
    pen: Pen,
    player: PlayerDefinition,
    team: Team,
    color: str,
) -> None:
    """
    The team-coloured band: the role's initials in a badge, the name,
    and the team. The initials are the board's own (`ROLE_INITIALS`),
    so the two letters on the card are the two letters on the meeple's
    card in Discord.
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

    pen.text(
        (CARD_WIDTH - FRAME - 60, FRAME + HEADER_HEIGHT / 2),
        team_display_name(team).upper(),
        font(16, bold=True),
        "#ffffff",
        anchor="mm",
    )

    name_left = FRAME + 132
    name_right = CARD_WIDTH - FRAME - 112
    pen.text(
        ((name_left + name_right) / 2, FRAME + HEADER_HEIGHT / 2),
        player.name,
        fitted_name(pen, player.name, name_right - name_left),
        "#ffffff",
        anchor="mm",
    )


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
# long abilities pay a line's worth. The floor is the suite's
# MIN_PORTRAIT_HEIGHT, which is where the trade stops being one.
ABILITY_SIZE = 30
ABILITY_HEADING_SIZE = 19


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
    pen = Pen((CARD_WIDTH, CARD_HEIGHT), CARD_FACE)

    # The rounded outline in the team's colour is the card's edge and
    # the cut line at once, as it is on a maneuver card -- with the
    # face and the sheet both white there is nothing else to say where
    # the card ends.
    pen.rect(
        (FRAME, FRAME, CARD_WIDTH - FRAME, CARD_HEIGHT - FRAME),
        radius=CORNER,
        fill=CARD_FACE,
        outline=color,
        width=EDGE_WIDTH,
    )

    draw_header(pen, player, team, color)

    stats_top = FRAME + HEADER_HEIGHT + STATS_TOP_GAP
    draw_stats(pen, player, profile, stats_top)

    lines, ability_height = ability_lines(pen, profile.ability)
    ability_top = CARD_HEIGHT - FRAME - 18 - ability_height
    draw_portrait(
        pen,
        player,
        stats_top + STATS_HEIGHT + PORTRAIT_GAP,
        ability_top - PORTRAIT_GAP,
    )
    draw_ability(pen, lines, ability_top)

    return pen.finish(bleed, CARD_FACE)


# A team is nine players, so a team's sheet is three across and three
# down: nine cards to a page, which is what a poker-sized card and an
# A4 or letter sheet come out at. The maneuvers print four across
# because there are seven of them, not because four is the number.
TEAM_SHEET_COLUMNS = 3
