from io import BytesIO
from math import cos, pi, sin
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from d12ball.components import (
    MatchState,
    MatchPeriod,
    PlayerCatalog,
    PlayerDefinition,
    TeamSetup,
    Zone,
)
from d12ball.game import Team


IMAGE_WIDTH = 2200
IMAGE_HEIGHT = 1280
MARGIN = 70
BOARD_LEFT = 100
BOARD_RIGHT = 1710
CONTENT_RIGHT = 1750
JUMBOTRON_LEFT = 1800
JUMBOTRON_RIGHT = IMAGE_WIDTH - 55
BOARD_TOP = 440
BOARD_BOTTOM = 825
CARD_SIZE = (76, 106)

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


def load_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    font_names = (
        ("DejaVuSans-Bold.ttf", "Arial Bold.ttf")
        if bold
        else ("DejaVuSans.ttf", "Arial.ttf")
    )
    for font_name in font_names:
        try:
            return ImageFont.truetype(font_name, size)
        except OSError:
            continue
    return ImageFont.load_default()


FONT_TITLE = load_font(34, bold=True)
FONT_HEADING = load_font(24, bold=True)
FONT_BODY = load_font(18)
FONT_SMALL = load_font(14)
FONT_MEEPLE = load_font(20, bold=True)
FONT_TOKEN = load_font(16, bold=True)
FONT_SCORE = load_font(52, bold=True)
MEEPLE_SIZE = 46
BALL_RADIUS = 20

ROLE_INITIALS = {
    "fullback": "FB",
    "defender": "DD",
    "midfielder": "MF",
    "playmaker": "PM",
    "winger": "WG",
    "striker": "SK",
}


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
    x: int,
    y: int,
) -> None:
    image_path = Path(__file__).resolve().parent / player.card_image
    with Image.open(image_path) as source:
        card = source.convert("RGBA")
        card.thumbnail(CARD_SIZE, Image.Resampling.LANCZOS)

    border = TEAM_COLORS[player.team]
    draw.rounded_rectangle(
        (x - 3, y - 3, x + CARD_SIZE[0] + 3, y + CARD_SIZE[1] + 3),
        radius=7,
        fill=border,
    )
    canvas.alpha_composite(card, (x, y))


def draw_assignment_cards(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    setup: TeamSetup,
    players: dict[str, PlayerDefinition],
    bounds: dict[Zone, tuple[int, int]],
    y: int,
) -> None:
    for zone in Zone:
        left, right = bounds[zone]
        player_ids = setup.zones[zone]
        total_width = len(player_ids) * CARD_SIZE[0] + (
            len(player_ids) - 1
        ) * 12
        x = left + (right - left - total_width) // 2

        for player_id in player_ids:
            draw_card(canvas, draw, players[player_id], x, y)
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

    return bounds


def draw_meeple_group(
    draw: ImageDraw.ImageDraw,
    occupants: list[str],
    players: dict[str, PlayerDefinition],
    space_left: int,
    space_right: int,
    token_y: int,
    alignment: str,
    reserve_ball: bool,
) -> tuple[int, int]:
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
        label = player.name
        label_width = draw.textlength(label, font=FONT_MEEPLE)
        label_x = token_x + (token_size - label_width) / 2
        label_x = max(space_left + 4, label_x)
        label_x = min(space_right - label_width - 4, label_x)
        name_y = token_y + token_size + 7
        if len(occupants) > 1:
            name_y += player_index * 23
        draw.text(
            (
                label_x,
                name_y,
            ),
            label,
            font=FONT_MEEPLE,
            fill="#ffffff",
        )
        token_x += token_size + gap

    return group_left, group_left + total_width


def draw_die(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    size: int,
    color: str,
    label: str,
) -> None:
    draw.rounded_rectangle(
        (x, y, x + size, y + size),
        radius=10,
        fill=color,
        outline="#ffffff",
        width=2,
    )
    label_width = draw.textlength(label, font=FONT_BODY)
    draw.text(
        (x + (size - label_width) / 2, y + size / 2 - 12),
        label,
        font=FONT_BODY,
        fill="#ffffff",
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

    label_width = draw.textlength(label, font=font)
    draw.text(
        (center_x - label_width / 2, center_y - 12),
        label,
        font=font,
        fill=text_color,
    )


def draw_jumbotron(
    draw: ImageDraw.ImageDraw,
    match: MatchState,
) -> None:
    top = 250
    bottom = BOARD_BOTTOM
    draw.rounded_rectangle(
        (JUMBOTRON_LEFT, top, JUMBOTRON_RIGHT, bottom),
        radius=22,
        fill="#161d26",
        outline="#c7d0da",
        width=5,
    )

    jumbotron_title = "D12 BALL!"
    jumbotron_title_width = draw.textlength(
        jumbotron_title,
        font=FONT_TITLE,
    )
    draw.text(
        (
            JUMBOTRON_LEFT
            + (
                JUMBOTRON_RIGHT
                - JUMBOTRON_LEFT
                - jumbotron_title_width
            )
            / 2,
            top + 32,
        ),
        jumbotron_title,
        font=FONT_TITLE,
        fill="#ffffff",
    )

    draw.text(
        (JUMBOTRON_LEFT + 30, top + 115),
        match.home.team.value.title(),
        font=FONT_HEADING,
        fill=TEAM_COLORS[match.home.team],
    )
    visiting_label = match.visiting.team.value.title()
    visiting_width = draw.textlength(
        visiting_label,
        font=FONT_HEADING,
    )
    draw.text(
        (JUMBOTRON_RIGHT - 30 - visiting_width, top + 115),
        visiting_label,
        font=FONT_HEADING,
        fill=TEAM_COLORS[match.visiting.team],
    )
    score = (
        f"{match.scoreboard.home_score}:"
        f"{match.scoreboard.visiting_score}"
    )
    score_width = draw.textlength(score, font=FONT_SCORE)
    draw.text(
        (
            JUMBOTRON_LEFT
            + (JUMBOTRON_RIGHT - JUMBOTRON_LEFT - score_width) / 2,
            top + 175,
        ),
        score,
        font=FONT_SCORE,
        fill="#ffffff",
    )

    time_text = f"{match.scoreboard.time:02d}"
    time_width = draw.textlength(time_text, font=FONT_SCORE)
    draw.text(
        (
            JUMBOTRON_LEFT
            + (JUMBOTRON_RIGHT - JUMBOTRON_LEFT - time_width) / 2,
            top + 290,
        ),
        time_text,
        font=FONT_SCORE,
        fill="#f5d76e",
    )
    period = (
        "First Half"
        if match.scoreboard.period == MatchPeriod.FIRST_HALF
        else "Second Half"
    )
    period_width = draw.textlength(period, font=FONT_HEADING)
    draw.text(
        (
            JUMBOTRON_LEFT
            + (JUMBOTRON_RIGHT - JUMBOTRON_LEFT - period_width) / 2,
            top + 410,
        ),
        period,
        font=FONT_HEADING,
        fill="#ffffff",
    )


def draw_player_board(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    setup: TeamSetup,
    players: dict[str, PlayerDefinition],
    y: int,
) -> None:
    color = TEAM_COLORS[setup.team]
    draw.rounded_rectangle(
        (MARGIN, y, CONTENT_RIGHT, y + 190),
        radius=18,
        fill="#202a35",
        outline=color,
        width=5,
    )
    draw.text(
        (MARGIN + 20, y + 14),
        f"{setup.side.value.title()} Player Board — "
        f"{setup.team.value.title()}",
        font=FONT_HEADING,
        fill="#ffffff",
    )

    bench_x = MARGIN + 500
    draw.text(
        (bench_x, y + 14),
        "BENCH",
        font=FONT_BODY,
        fill="#ffffff",
    )
    card_x = bench_x
    for player_id in setup.player_board.bench:
        draw_card(canvas, draw, players[player_id], card_x, y + 48)
        card_x += CARD_SIZE[0] + 12

    back_bench_x = MARGIN + 850
    draw.text(
        (back_bench_x, y + 14),
        "BACK BENCH",
        font=FONT_BODY,
        fill="#ffffff",
    )
    if not setup.player_board.back_bench:
        draw.text(
            (back_bench_x, y + 75),
            "Empty",
            font=FONT_BODY,
            fill="#9eabb8",
        )

    coach_x = CONTENT_RIGHT - 390
    draw.text(
        (coach_x, y + 14),
        "HEAD COACH",
        font=FONT_BODY,
        fill="#ffffff",
    )
    draw_die(draw, coach_x, y + 55, 66, "#9f2637", "d6")
    draw_die(draw, coach_x + 86, y + 55, 66, "#2d8b57", "d6")
    draw_d12_polygon(
        draw,
        coach_x + 211,
        y + 88,
        48,
        color,
        "d12",
    )


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

    draw_player_board(canvas, draw, match.visiting, players, 65)
    bounds = zone_bounds(match)
    draw_assignment_cards(
        canvas,
        draw,
        match.visiting,
        players,
        bounds,
        290,
    )
    draw_board(canvas, draw, match, players)
    draw_assignment_cards(
        canvas,
        draw,
        match.home,
        players,
        bounds,
        850,
    )
    draw_player_board(canvas, draw, match.home, players, 1080)
    draw_jumbotron(draw, match)

    output = BytesIO()
    canvas.convert("RGB").save(output, format="PNG", optimize=True)
    output.seek(0)
    return output
