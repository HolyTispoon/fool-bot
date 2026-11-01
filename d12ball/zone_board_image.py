"""
**D12 Ball 2.0's board on Discord** (the author, 2026-10-28): the field
with each side's players over and under it as 2.0 player tiles, each
in a slot of the zone whose role it holds, and the role written beside
the slot -- the printed 2.0 zone board's idea (docs/design/
printed-boards.md, "The 2.0 boards") brought to the bot's board.

In 2.0 a role is the formation's, not the card's (docs/rules-2.1.md
section 4): a tile names no role, and the slot says which -- each
zone's unique role, starred, on the label nearest that zone of the
field, and its standard role beside it -- so a coach reads who holds
what without a card claiming a role it was only dealt as. The bench
and the back bench are tiles with no slot, since a player there holds
none.

It draws the same field the 1.0 board does (`render.draw_board`, with
each meeple carrying the role the match gives it) and the same
jumbotron; the field is drawn where the 1.0 board draws it and moved
down under the visitors' row, which is as tall as the tiles need. Who
holds which role is handed in (`roles`, `RulesEngine.board_roles`), as
`card_skills` is: the renderer is given the answer and never asks the
rules.

A separate module rather than a branch of `render.py` because the tile
is `player_cards.py`'s, and `player_cards.py` imports `render.py`.
"""

from dataclasses import dataclass
from io import BytesIO
from math import cos, pi, sin
from typing import Mapping, Optional

from PIL import Image, ImageDraw

from d12ball.cards import FRAME
from d12ball.components import (
    FORMATION_ZONE_ROLES,
    SETUP_AREAS,
    MatchState,
    PlayerCatalog,
    PlayerDefinition,
    PlayerRole,
    TeamSetup,
    TeamSide,
    Zone,
    zone_for_area,
)
from d12ball.game import Team, team_display_name
from d12ball.player_cards import TILE_CORNER, TILE_INCHES, render_player_tile
from d12ball.render import (
    BOARD_BOTTOM,
    BOARD_TOP,
    FIELD_FAR_LEFT,
    FIELD_FAR_RIGHT,
    FONT_BADGE_COUNT,
    FONT_BODY,
    FONT_HEADING,
    FONT_TITLE,
    IMAGE_HEIGHT as BOARD_IMAGE_HEIGHT,
    IMAGE_WIDTH,
    JUMBOTRON_BOTTOM,
    OUTPUT_SCALE,
    TEAM_BOARD_GAP,
    TEAM_COLORS,
    draw_board,
    draw_jumbotron,
    draw_marked_text,
    load_damaged_icon,
    load_drained_icon,
    load_exhaust_cyborg_icon,
    load_exhaust_icon,
    load_exhausted_icon,
    load_font,
    load_injured_icon,
    marked_length,
    player_index,
    png_bytes,
    zone_bounds,
)

# **A tile is as large as its zone allows** (the author, 2026-10-28:
# "should be bigger"): one size for the whole board, the widest that
# puts the busiest zone's slots side by side, up to `TILE_MAX_WIDTH`,
# at the printed tile's own proportions (2.75 x 2.25in). The standard
# deal puts two in a zone, which on board 9 is the maximum; a zone a
# coach has packed with three makes every tile smaller, down to
# `TILE_MIN_WIDTH`, past which the slots overlap rather than shrink.
TILE_ASPECT = TILE_INCHES[1] / TILE_INCHES[0]
TILE_MAX_WIDTH = 300
TILE_MIN_WIDTH = 170
SLOT_GAP = 16
ZONE_PAD = 12
# The role's label: a pill the tile's width, between the tile and the
# field -- under the visitors' tiles and over home's -- so it reads as
# the zone's and is never covered by the tile it names.
LABEL_HEIGHT = 32
LABEL_GAP = 6
FONT_ROLE_LABEL = load_font(23, bold=True)
# **A unique role is told apart in words, not colour** (the author,
# 2026-10-28): every pill is the same dark outline, and a unique role's
# carries a star before its name and a heavier border. Gold, the printed
# zone board's colour for it, read as Orange's beside an orange tile,
# and white was no better; a colour on this board says a team.
LABEL_FILL = "#2b3a4a"
LABEL_OUTLINE = "#d7dde5"
LABEL_BORDER = 2
UNIQUE_LABEL_BORDER = 4
STAR_RADIUS = 10
OPEN_SLOT_OUTLINE = "#4f6072"

# The field as `render.draw_board` draws it, cut out with a little room
# for its outline and pasted under the visitors' row.
FIELD_CROP_TOP = BOARD_TOP - 6
FIELD_CROP_BOTTOM = BOARD_BOTTOM + 6
BAND_GAP = 10

# The team boards: a bench is the tiles alone, with no label, since
# nobody there holds a role. Nine to a squad leaves three off the field
# between the two pools.
BENCH_TILE_WIDTH = 220
BENCH_TILE_GAP = 14
# The side's name heads the board on a line of its own and the two
# pools sit under it, so the pools have the board's whole width -- a
# coach's name beside them pushed the back bench off the board.
TEAM_BOARD_POOLS_OFFSET = 70
TEAM_BOARD_TILES_OFFSET = 116
TEAM_BOARD_PAD = 18
IMAGE_BOTTOM_MARGIN = 25

CONDITION_ICON_SIZE = 34

# Every tile drawn so far, at each width: a tile is a portrait and a
# few lines of type at print resolution, so it is drawn once a card
# and size per process and kept, as `render.rendered_player_card` is.
_TILES: dict[tuple, Image.Image] = {}


def tile_height(width: int) -> int:
    return round(width * TILE_ASPECT)


def board_tile(
    catalog: PlayerCatalog,
    player: PlayerDefinition,
    team: Team,
    advanced: bool,
    width: int,
) -> Image.Image:
    """
    One player's 2.0 tile, `width` across, the face the game plays --
    the advanced face, with the advanced skills in its index, where the
    special abilities apply (`advanced`), as the printed kit has it.

    **Cut to its own rounded edge**: the printed tile is drawn on a
    white sheet with its outline `FRAME` in from the trim, so the
    sheet's square corners are cut away and the outline's rounded ones
    kept (the author, 2026-10-28: "if they are rounded they should be
    rounded, not leave the white corner"). The mask is drawn at the
    print size, so the corner is as smooth as the outline under it.
    """
    key = (player.player_id, Team(team), advanced, width)
    tile = _TILES.get(key)
    if tile is None:
        full = render_player_tile(
            catalog, player, team, bleed=False, advanced=advanced,
        ).convert("RGBA")
        scale = full.width / TILE_INCHES[0] / 300
        inset = round(FRAME * scale)
        full = full.crop(
            (inset, inset, full.width - inset, full.height - inset)
        )
        mask = Image.new("L", full.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            (0, 0, full.width - 1, full.height - 1),
            radius=round(TILE_CORNER * scale),
            fill=255,
        )
        full.putalpha(mask)
        tile = full.resize(
            (width, round(width * full.height / full.width)),
            Image.Resampling.LANCZOS,
        )
        _TILES[key] = tile
    return tile


def draw_tile_conditions(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    width: int,
    height: int,
    exhaustion: int,
    exhausted: bool,
    injured: bool,
    cyborg: bool,
) -> None:
    """
    A tile's marks in its bottom-right corner -- where the role token
    lies at the table (`player_cards.TILE_TOKEN_SPOT`), over the
    portrait's foot -- the exhaust tokens with their count, and the
    condition beside them: the same icons, and the same Cyborg's own
    words for them, as the 1.0 board card (`render.draw_card`).
    """
    right = x + width - 10
    bottom = y + height - 10
    marks = []
    if exhaustion > 0:
        marks.append(
            (load_exhaust_cyborg_icon() if cyborg else load_exhaust_icon(),
             exhaustion)
        )
    if exhausted:
        marks.append(
            (load_drained_icon() if cyborg else load_exhausted_icon(), 0)
        )
    if injured:
        marks.append(
            (load_damaged_icon() if cyborg else load_injured_icon(), 0)
        )
    left = right
    for icon, count in marks:
        left -= CONDITION_ICON_SIZE
        top = bottom - CONDITION_ICON_SIZE
        draw.ellipse(
            (left - 2, top - 2, left + CONDITION_ICON_SIZE + 2,
             top + CONDITION_ICON_SIZE + 2),
            fill="#1a1a1a",
        )
        if icon is not None:
            canvas.alpha_composite(
                icon.resize(
                    (CONDITION_ICON_SIZE, CONDITION_ICON_SIZE),
                    Image.Resampling.LANCZOS,
                ),
                (left, top),
            )
        if count > 1:
            label = str(count)
            box = draw.textbbox((0, 0), label, font=FONT_BADGE_COUNT)
            radius = max(box[2] - box[0], box[3] - box[1]) / 2 + 3
            cx = left + CONDITION_ICON_SIZE - 2
            cy = top + 2
            draw.ellipse(
                (cx - radius, cy - radius, cx + radius, cy + radius),
                fill="#1a1a1a",
                outline=LABEL_OUTLINE,
                width=1,
            )
            draw.text(
                (cx, cy), label, font=FONT_BADGE_COUNT, fill="#ffffff",
                anchor="mm",
            )
        left -= 6


def draw_star(
    draw: ImageDraw.ImageDraw, cx: float, cy: float, radius: float, fill: str,
) -> None:
    """A five-pointed star, drawn rather than set: the bundled faces
    carry no star glyph."""
    points = [
        (
            cx + (radius if step % 2 == 0 else radius * 0.42)
            * cos(-pi / 2 + step * pi / 5),
            cy + (radius if step % 2 == 0 else radius * 0.42)
            * sin(-pi / 2 + step * pi / 5),
        )
        for step in range(10)
    ]
    draw.polygon(points, fill=fill)


def draw_role_label(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    width: int,
    role: PlayerRole,
    unique: bool,
) -> None:
    """The role a slot gives, on a pill the slot's width -- a unique
    role with a star before its name and a heavier border, otherwise
    the same as a standard one."""
    draw.rounded_rectangle(
        (x, y, x + width, y + LABEL_HEIGHT),
        radius=LABEL_HEIGHT // 2,
        fill=LABEL_FILL,
        outline=LABEL_OUTLINE,
        width=UNIQUE_LABEL_BORDER if unique else LABEL_BORDER,
    )
    name = PlayerRole(role).value.upper()
    text_width = draw.textlength(name, font=FONT_ROLE_LABEL)
    star_width = STAR_RADIUS * 2 + 8 if unique else 0
    left = x + (width - text_width - star_width) / 2
    middle = y + LABEL_HEIGHT / 2
    if unique:
        draw_star(draw, left + STAR_RADIUS, middle, STAR_RADIUS, "#ffffff")
    draw.text(
        (left + star_width, middle + 1),
        name,
        font=FONT_ROLE_LABEL,
        fill="#ffffff",
        anchor="lm",
    )


def zone_slots(
    match: MatchState,
    setup: TeamSetup,
    players: Mapping[str, PlayerDefinition],
    roles: Mapping[str, PlayerRole],
    area: str,
) -> list[tuple[PlayerRole, bool, Optional[str]]]:
    """
    One zone's slots for a side, as `(role, unique, player or None)`:
    a slot for each player holding the zone's unique or standard role,
    left to right as their meeples stand, and an open slot for a role
    of the zone nobody holds, so every zone shows both its roles.
    """
    unique, standard = FORMATION_ZONE_ROLES[area]

    def role(player_id: str) -> PlayerRole:
        return PlayerRole(roles.get(player_id) or players[player_id].role)

    zone_order = {zone: number for number, zone in enumerate(Zone)}

    def standing(player_id: str) -> tuple[int, int]:
        position = match.board.meeple_position(player_id)
        if position is None:
            return (len(zone_order), 0)
        return (zone_order[Zone(position[0])], position[1])

    held = sorted(
        (
            player_id for player_id in setup.field_players
            if role(player_id) in (unique, standard)
        ),
        key=standing,
    )
    slots = [
        (role(player_id), role(player_id) == unique, player_id)
        for player_id in held
    ]
    for each, is_unique in ((unique, True), (standard, False)):
        if not any(slot[0] == each for slot in slots):
            slots.append((each, is_unique, None))
    return slots


@dataclass(frozen=True)
class ZoneBoardLayout:
    """Where each band of the 2.0 board goes, worked out once from the
    tile size the busiest zone allows."""

    tile_width: int
    visiting_tiles_top: int
    visiting_labels_top: int
    field_top: int
    home_labels_top: int
    home_tiles_top: int
    team_board_top: int
    team_board_bottom: int
    height: int

    @property
    def tile_height(self) -> int:
        return tile_height(self.tile_width)

    @classmethod
    def for_slots(
        cls,
        bounds: Mapping[Zone, tuple[int, int]],
        slots: Mapping[tuple[TeamSide, Zone], int],
    ) -> "ZoneBoardLayout":
        width = TILE_MAX_WIDTH
        for (_, zone), count in slots.items():
            left, right = bounds[zone]
            room = (right - left - ZONE_PAD - SLOT_GAP * (count - 1)) / count
            width = min(width, int(room))
        width = max(width, TILE_MIN_WIDTH)
        height = tile_height(width)
        visiting_tiles_top = JUMBOTRON_BOTTOM + BAND_GAP
        visiting_labels_top = visiting_tiles_top + height + LABEL_GAP
        field_top = visiting_labels_top + LABEL_HEIGHT + LABEL_GAP
        field_bottom = field_top + FIELD_CROP_BOTTOM - FIELD_CROP_TOP
        home_labels_top = field_bottom + LABEL_GAP
        home_tiles_top = home_labels_top + LABEL_HEIGHT + LABEL_GAP
        team_board_top = home_tiles_top + height + 2 * BAND_GAP
        team_board_bottom = (
            team_board_top + TEAM_BOARD_TILES_OFFSET
            + tile_height(BENCH_TILE_WIDTH) + TEAM_BOARD_PAD
        )
        return cls(
            tile_width=width,
            visiting_tiles_top=visiting_tiles_top,
            visiting_labels_top=visiting_labels_top,
            field_top=field_top,
            home_labels_top=home_labels_top,
            home_tiles_top=home_tiles_top,
            team_board_top=team_board_top,
            team_board_bottom=team_board_bottom,
            height=team_board_bottom + IMAGE_BOTTOM_MARGIN,
        )


def draw_side_slots(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    match: MatchState,
    setup: TeamSetup,
    catalog: PlayerCatalog,
    slots_by_zone: Mapping[Zone, list[tuple[PlayerRole, bool, Optional[str]]]],
    bounds: Mapping[Zone, tuple[int, int]],
    tile_width: int,
    tiles_top: int,
    labels_top: int,
    advanced: bool,
    cyborg_ids: frozenset[str],
    players: Mapping[str, PlayerDefinition],
) -> None:
    """
    One side's row of slots, a zone's under (or over) that zone of the
    field: each slot its role's label nearest the field and its
    player's tile beyond it.
    """
    height = tile_height(tile_width)
    for zone, slots in slots_by_zone.items():
        left, right = bounds[zone]
        count = len(slots)
        # Spread across the zone; where the zone is too narrow for the
        # slots side by side even at the smallest tile they overlap,
        # the later over the earlier, rather than spill into the next.
        step = tile_width + SLOT_GAP
        if count > 1:
            step = min(step, (right - left - ZONE_PAD - tile_width) / (count - 1))
        total = tile_width + step * (count - 1)
        x = left + (right - left - total) / 2
        for role, unique, player_id in slots:
            slot_x = round(x)
            draw_role_label(
                draw, slot_x, labels_top, tile_width, role, unique,
            )
            if player_id is None:
                draw.rounded_rectangle(
                    (slot_x, tiles_top, slot_x + tile_width,
                     tiles_top + height),
                    radius=14,
                    outline=OPEN_SLOT_OUTLINE,
                    width=UNIQUE_LABEL_BORDER if unique else LABEL_BORDER,
                )
                draw.text(
                    (slot_x + tile_width / 2, tiles_top + height / 2),
                    "OPEN",
                    font=FONT_ROLE_LABEL,
                    fill=OPEN_SLOT_OUTLINE,
                    anchor="mm",
                )
            else:
                tile = board_tile(
                    catalog, players[player_id], setup.team, advanced,
                    tile_width,
                )
                canvas.alpha_composite(tile, (slot_x, tiles_top))
                draw_tile_conditions(
                    canvas, draw, slot_x, tiles_top, tile.width, tile.height,
                    match.exhaustion.get(player_id, 0),
                    player_id in match.exhausted,
                    player_id in match.injured,
                    player_id in cyborg_ids,
                )
            x += step


def draw_team_board_tiles(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    match: MatchState,
    setup: TeamSetup,
    players: Mapping[str, PlayerDefinition],
    catalog: PlayerCatalog,
    x: int,
    width: int,
    layout: ZoneBoardLayout,
    advanced: bool,
    cyborg_ids: frozenset[str],
    name: Optional[str] = None,
) -> None:
    """
    One side's bench and back bench under the field, as tiles: headed
    by `name` -- the side the short way -- and under it each pool
    labelled, the back bench starting where the bench's own tiles end.
    """
    color = TEAM_COLORS[setup.team]
    y = layout.team_board_top
    draw.rounded_rectangle(
        (x, y, x + width, layout.team_board_bottom),
        radius=18,
        fill="#202a35",
        outline=color,
        width=5,
    )
    name = name or team_display_name(setup.team)
    draw_marked_text(canvas, draw, (x + 22, y + 14), name, FONT_HEADING, color)
    pools_left = x + 22
    bench_height = tile_height(BENCH_TILE_WIDTH)
    for label, player_ids in (
        ("BENCH", setup.team_board.bench),
        ("BACK BENCH", setup.team_board.back_bench),
    ):
        draw.text(
            (pools_left, y + TEAM_BOARD_POOLS_OFFSET), label, font=FONT_BODY,
            fill="#ffffff",
        )
        label_width = draw.textlength(label, font=FONT_BODY)
        tile_x = pools_left
        tiles_top = y + TEAM_BOARD_TILES_OFFSET
        if not player_ids:
            draw.text(
                (tile_x, tiles_top + bench_height / 2 - 16),
                "Empty",
                font=FONT_BODY,
                fill="#9eabb8",
            )
            tile_x += label_width
        for player_id in player_ids:
            tile = board_tile(
                catalog, players[player_id], setup.team, advanced,
                BENCH_TILE_WIDTH,
            )
            canvas.alpha_composite(tile, (round(tile_x), tiles_top))
            draw_tile_conditions(
                canvas, draw, round(tile_x), tiles_top, tile.width,
                tile.height,
                match.exhaustion.get(player_id, 0),
                player_id in match.exhausted,
                player_id in match.injured,
                player_id in cyborg_ids,
            )
            tile_x += BENCH_TILE_WIDTH + BENCH_TILE_GAP
        pools_left = round(max(tile_x, pools_left + label_width) + 36)


def render_zone_board(
    match: MatchState,
    catalog: PlayerCatalog,
    title: str,
    roles: Mapping[str, PlayerRole],
    species_icons: bool = False,
    cyborg_ids: frozenset[str] = frozenset(),
    advanced: bool = False,
    coaches: Mapping[TeamSide, str] = {},
    tie_coin: Optional[tuple[str, str]] = None,
    scale: float = OUTPUT_SCALE,
) -> BytesIO:
    """
    **The 2.0 board**: the title and the jumbotron, the visitors'
    slots over the field and home's under it -- each zone's roles
    beside the tiles of whoever holds them -- and each side's bench
    under that, as tiles holding no role. `roles` is each fielded
    card's role in the match (`RulesEngine.board_roles`); a card it
    leaves out reads its own, which only a 2.0 game saved before the
    formation held the roles has. `advanced` draws the tiles' advanced
    face. `scale` is the upscale the board message wants
    (`render.OUTPUT_SCALE`); the Coaching Choice's message, which is
    re-uploaded with every change, takes it at 1.
    """
    players = player_index(catalog)
    bounds = zone_bounds(match)
    slots = {
        setup.side: {
            zone_for_area(setup.side, area): zone_slots(
                match, setup, players, roles, area,
            )
            for area in SETUP_AREAS
        }
        for setup in (match.home, match.visiting)
    }
    layout = ZoneBoardLayout.for_slots(
        bounds,
        {
            (side, zone): len(zone_slots_)
            for side, by_zone in slots.items()
            for zone, zone_slots_ in by_zone.items()
        },
    )

    # The field where the 1.0 board draws it, then moved into place.
    field = Image.new("RGBA", (IMAGE_WIDTH, BOARD_IMAGE_HEIGHT), "#111820")
    draw_board(
        field, ImageDraw.Draw(field), match, players,
        species_icons=species_icons, cyborg_ids=cyborg_ids,
        shooting_range=False, roles=roles,
    )

    canvas = Image.new("RGBA", (IMAGE_WIDTH, layout.height), "#111820")
    draw = ImageDraw.Draw(canvas)
    title_width = marked_length(draw, title, FONT_TITLE)
    draw_marked_text(
        canvas, draw, ((IMAGE_WIDTH - title_width) / 2, 18), title,
        FONT_TITLE, "#ffffff",
    )
    draw_jumbotron(canvas, draw, match, coaches, tie_coin)
    canvas.alpha_composite(
        field.crop((0, FIELD_CROP_TOP, IMAGE_WIDTH, FIELD_CROP_BOTTOM)),
        (0, layout.field_top),
    )
    for setup, tiles_top, labels_top in (
        (match.visiting, layout.visiting_tiles_top, layout.visiting_labels_top),
        (match.home, layout.home_tiles_top, layout.home_labels_top),
    ):
        draw_side_slots(
            canvas, draw, match, setup, catalog, slots[setup.side], bounds,
            layout.tile_width, tiles_top, labels_top, advanced, cyborg_ids,
            players,
        )
    team_board_width = (FIELD_FAR_RIGHT - FIELD_FAR_LEFT - TEAM_BOARD_GAP) // 2
    for setup, x in (
        (match.home, FIELD_FAR_LEFT),
        (match.visiting, FIELD_FAR_LEFT + team_board_width + TEAM_BOARD_GAP),
    ):
        draw_team_board_tiles(
            canvas, draw, match, setup, players, catalog, x,
            team_board_width, layout, advanced, cyborg_ids,
            name=coaches.get(setup.side),
        )

    if scale != 1:
        canvas = canvas.resize(
            (round(IMAGE_WIDTH * scale), round(layout.height * scale)),
            Image.Resampling.BILINEAR,
        )
    return png_bytes(canvas)
