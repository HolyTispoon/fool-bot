"""
The D12 Ball components cut for screentop.gg.

The game on screentop.gg is built in its own web editor and lives
there; nothing about it is checked in. What the repo owns is every
image the module is made of -- the cards, the boards, the meeples,
the dice and the tokens -- all of them drawn by the same modules the
bot and the print-and-play kit draw from. **This module is the cut of
those images a virtual tabletop wants**, which is a different cut from
a printer's, and `scripts/export_screentop_assets.py` is the command
that writes it. Updating the screentop module is: run the script,
upload what changed. See docs/design/screentop.md for the reasoning.

**It draws nothing of its own that the game already draws.** A card
is `cards.render_maneuver_card`, `player_cards.render_player_card` or
`species_cards.render_species_card`; a board is
`boards.render_field_board`, `render_jumbotron_board` or one
`render_team_board_panel`; a condition token is the emoji PNG
`render.py` itself loads. What is drawn here is only what has no
standalone image anywhere else: a meeple as a token on its own (the
board only ever draws one in place, at 76px), and a d12's twelve faces
(the board draws one face, showing one value). Both are the board's
own recipe scaled, reading `render.py`'s constants rather than
restating them, so a change to the disc reaches the token.

**What differs from the print kit, and why:**

- **A sheet is gapless.** `cards.print_sheet` centres every card in a
  cell with a margin round it, because a print is cut by hand and a
  margin is where the knife wanders. A tabletop cuts a sheet by
  dividing it into exactly `columns` x `rows`, so a cell *is* a card,
  edge to edge -- a margin would end up on the card. `tabletop_sheet`
  is that grid. Every card on one sheet must already be one size; it
  refuses rather than stretching one to fit.
- **Backs are in reading order, never `duplex_order`.** A duplex
  printer flips the sheet, so the print kit reverses every row of the
  player backs; a tabletop pairs cell `n` of the front sheet with cell
  `n` of the back sheet and the reversal would land every back behind
  the wrong player.
- **No bleed, ever.** Bleed is the eighth of an inch a trimmer takes
  off; on a screen it is a border.
- **Everything is capped at `MAX_SIDE` pixels a side.** A 300dpi
  tabloid board is 3300 x 5100 and a web canvas has no use for it; an
  upload that big is slow to load and some renderers refuse a texture
  over 4096. The cap scales an image *down* only, and a sheet is capped
  as a whole with its cells kept integer, so the grid still divides
  exactly. `--max-side` on the script changes it; nothing here is ever
  scaled up.
- **The manifest is the contract.** Every file the export writes is
  listed in `manifest.json` with its kind, its size and, for a sheet,
  the grid and the order of the cells -- the numbers a person types
  into the editor, so they are read off the file rather than counted
  by eye.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from math import ceil, floor
from pathlib import Path
from typing import Iterable, Optional

from PIL import Image, ImageDraw

from d12ball import render
from d12ball.boards import (
    DEFAULT_PAPER,
    render_field_board,
    render_jumbotron_board,
    render_team_board_panel,
    sheet_pixels,
)
from d12ball.cards import render_maneuver_card, render_maneuver_card_back
from d12ball.components import (
    MANEUVER_TIERS,
    BasicRuleset,
    ManeuverCatalog,
    PlayerCatalog,
    PlayerDefinition,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.formatting import role_initials
from d12ball.game import COLOR_TEAMS, CoinFace, Team
from d12ball.player_cards import render_player_card, render_player_card_back
from d12ball.render import (
    GOAL_ZONE_BALL_COLOR,
    GOAL_ZONE_BALL_OUTLINE,
    MEEPLE_ROLE_BOTTOM_INSET,
    MEEPLE_SIZE,
    MEEPLE_SPECIES_ICON_SIZE,
    MEEPLE_SPECIES_ICON_TOP,
    TEAM_COLORS,
    high_contrast_ink,
    load_font,
    polygon_points,
    species_icon,
)
from d12ball.species_cards import load_species_abilities, render_species_card_set

# The longest side any exported image may have. 4096 is the texture
# limit the most conservative WebGL renderers still enforce, and well
# past what a card or a board needs on a screen; nothing here is ever
# scaled *up* to it.
MAX_SIDE = 4096

# Grids. A maneuver hand is a side's six cards, three basic over three
# gambits (see "The maneuver cards" in docs/design/cards.md), so a side's
# sheet is three across and the rows are the tiers. A team's nine
# players are three across as on the print sheet. The species set is
# three cards, one row.
MANEUVER_SHEET_COLUMNS = 3
PLAYER_SHEET_COLUMNS = 3
SPECIES_SHEET_COLUMNS = 3
MEEPLE_SHEET_COLUMNS = 3
DIE_SHEET_COLUMNS = 4

# A meeple token's canvas. The board's disc is 76px; a tabletop zooms,
# so the token is drawn at a size that survives it and scaled by the
# same recipe. A die face is the same size, so the two stack on a
# space the way they do on the board.
MEEPLE_TOKEN_SIZE = 256
DIE_FACE_SIZE = 256
CONDITION_TOKEN_SIZE = 256
COIN_SIZE = 256
# Drawn at twice the size and scaled down, because Pillow's ellipse and
# polygon are not antialiased -- the same trick `cards.Pen` uses.
SUPERSAMPLE = 2
D12_SIDES = 12

# The coin toss's two faces, as the bot shows them. The names are the
# application emoji `COIN_EMOJI_NAMES` in cogs/d12ball_helpers.py asks
# for, restated here because this module may not import a cog; the
# test suite holds the two to the same files.
EMOJI_DIR = Path(__file__).resolve().parent / "images" / "emoji"
COIN_FACE_ART: dict[CoinFace, Path] = {
    CoinFace.FORTUNE: EMOJI_DIR / "3_gold_fortune.png",
    CoinFace.DOOM: EMOJI_DIR / "3_gold_doom.png",
}

# The condition tokens, from the same files the board draws its 26px
# badges from -- `render.py` owns the paths, so a renamed file follows.
CONDITION_TOKEN_ART: dict[str, Path] = {
    "exhaust": render.EXHAUST_ICON_PATH,
    "exhaust-cyborg": render.EXHAUST_CYBORG_ICON_PATH,
    "exhausted": render.EXHAUSTED_ICON_PATH,
    "injured": render.INJURED_ICON_PATH,
    "drained": render.DRAINED_ICON_PATH,
    "damaged": render.DAMAGED_ICON_PATH,
}

# The dice a table needs: one d12 a side in that side's colour, and the
# ball, which is a d12 too (see "The ball, the dice, and the tokens" in
# docs/living-rules.md) and is drawn white the way the board draws it.
# A species team shares its colour team's hex, so four coloured dice
# serve all eight teams.
BALL_DIE = "ball"


# ------------------------------------------------------------- sheets


@dataclass(frozen=True)
class SheetLayout:
    """
    What the editor needs to cut a sheet: the grid, how many of its
    cells are cards (a short last row is padded with empty cells,
    which the count says to ignore), the size of a cell, and which
    card is in which cell, reading left to right and top to bottom.
    """

    columns: int
    rows: int
    count: int
    cell: tuple[int, int]
    cells: tuple[str, ...]


def fit_cell(
    cell: tuple[int, int], columns: int, rows: int, max_side: int
) -> tuple[int, int]:
    """
    The cell size at which a `columns` x `rows` sheet of `cell`-sized
    cards fits inside `max_side` -- the card's own size when it already
    does. Floored to whole pixels, because the sheet is `columns` cells
    wide exactly and a fractional cell is a grid that drifts.
    """
    scale = min(
        1.0,
        max_side / (columns * cell[0]),
        max_side / (rows * cell[1]),
    )
    return (
        max(1, floor(cell[0] * scale)),
        max(1, floor(cell[1] * scale)),
    )


def fit_image(image: Image.Image, max_side: int) -> Image.Image:
    """`image` scaled down to fit `max_side`, or itself when it already does."""
    longest = max(image.size)
    if longest <= max_side:
        return image
    scale = max_side / longest
    return image.resize(
        (max(1, floor(image.width * scale)), max(1, floor(image.height * scale))),
        Image.Resampling.LANCZOS,
    )


def tabletop_sheet(
    cells: list[tuple[str, Image.Image]],
    columns: int,
    max_side: int = MAX_SIDE,
) -> tuple[Image.Image, SheetLayout, list[tuple[str, Image.Image]]]:
    """
    The cards as one gapless grid, `columns` across: cell `n` is card
    `n`, edge to edge, and dividing the sheet evenly hands back exactly
    the cards. Returns the sheet, its layout, and the cards themselves
    at the cell size -- so a card written on its own is the same pixels
    as its cell, and the manifest's one `cell` describes both.

    Every card must already be one size. A print sheet centres a
    smaller card in a bigger cell and the margin absorbs it; here the
    cell is the card, so a different size is a mistake to refuse
    rather than stretch.
    """
    if not cells:
        raise ValueError("A sheet needs at least one card.")
    sizes = {image.size for _, image in cells}
    if len(sizes) != 1:
        raise ValueError(
            f"Every card on a tabletop sheet must be one size; got {sorted(sizes)}."
        )
    (source_size,) = sizes
    rows = ceil(len(cells) / columns)
    cell = fit_cell(source_size, columns, rows, max_side)

    sheet = Image.new("RGBA", (columns * cell[0], rows * cell[1]), (0, 0, 0, 0))
    fitted: list[tuple[str, Image.Image]] = []
    for index, (name, image) in enumerate(cells):
        tile = image.convert("RGBA")
        if tile.size != cell:
            tile = tile.resize(cell, Image.Resampling.LANCZOS)
        column, row = index % columns, index // columns
        sheet.paste(tile, (column * cell[0], row * cell[1]))
        fitted.append((name, tile))

    layout = SheetLayout(
        columns=columns,
        rows=rows,
        count=len(cells),
        cell=cell,
        cells=tuple(name for name, _ in cells),
    )
    return sheet, layout, fitted


# ------------------------------------------------------------- tokens


def render_meeple_token(
    player: PlayerDefinition,
    team: Team,
    size: int = MEEPLE_TOKEN_SIZE,
    species_icons: bool = True,
) -> Image.Image:
    """
    One meeple as a token on its own: the board's disc -- the team's
    colour inside an ink ring, the species icon over the role initials,
    or the initials alone when `species_icons` is off (a basic game;
    see the note by `MEEPLE_SIZE` in render.py for who decides that) --
    at `size` pixels, on transparency.

    Every measurement is `render.draw_meeple_face`'s scaled by
    `size / MEEPLE_SIZE`, read from the same constants and the same
    font objects, so the token is the board's disc and not a second
    drawing of it. It is not that function itself only because that
    one draws at the board's 76px with fonts sized for it, in place on
    a canvas it is given.
    """
    scale = size / MEEPLE_SIZE
    inner = size * SUPERSAMPLE
    inner_scale = scale * SUPERSAMPLE
    canvas = Image.new("RGBA", (inner, inner), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    color = TEAM_COLORS[Team(team)]
    ink = high_contrast_ink(color)
    ring = max(1, round(4 * inner_scale))
    # Pillow draws the outline inward from the box, so the box is the
    # whole canvas and the ring stays inside it.
    draw.ellipse((0, 0, inner - 1, inner - 1), fill=color, outline=ink, width=ring)

    # The two letters come through the formatter, the one speller of a
    # role outside the modules that draw it -- see `role_initials`.
    initials = role_initials(player)
    icon = (
        species_icon(player.species, ink, round(MEEPLE_SPECIES_ICON_SIZE * inner_scale))
        if species_icons
        else None
    )
    if icon is None:
        font = load_font(round(_font_size(render.FONT_TOKEN_SOLO) * inner_scale), bold=True)
        bbox = draw.textbbox((0, 0), initials, font=font)
        draw.text(
            (
                (inner - (bbox[2] - bbox[0])) / 2 - bbox[0],
                (inner - (bbox[3] - bbox[1])) / 2 - bbox[1],
            ),
            initials,
            font=font,
            fill=ink,
        )
    else:
        canvas.alpha_composite(
            icon,
            ((inner - icon.width) // 2, round(MEEPLE_SPECIES_ICON_TOP * inner_scale)),
        )
        font = load_font(round(_font_size(render.FONT_TOKEN_ROLE) * inner_scale), bold=True)
        width = draw.textlength(initials, font=font)
        draw.text(
            ((inner - width) / 2, inner - round(MEEPLE_ROLE_BOTTOM_INSET * inner_scale)),
            initials,
            font=font,
            fill=ink,
        )

    return canvas.resize((size, size), Image.Resampling.LANCZOS)


def _font_size(font, fallback: int = 20) -> int:
    # A FreeType face knows its size; Pillow's built-in fallback face
    # (only ever reached with the bundled fonts missing) does not.
    return int(getattr(font, "size", fallback))


def render_die_face(
    value: int,
    color: str,
    size: int = DIE_FACE_SIZE,
    outline: Optional[str] = None,
    text_color: Optional[str] = None,
) -> Image.Image:
    """
    One face of a d12: the board's twelve-sided polygon
    (`render.polygon_points`, the same points `draw_d12_polygon`
    fills) in `color` with `value` on it, at `size` pixels on
    transparency. The default ink is the board's -- white on a team's
    colour, black on Slime green (`high_contrast_ink`) -- and the
    ball's white face passes its own outline and ink, as the board
    does when it draws the ball.
    """
    if not 1 <= value <= D12_SIDES:
        raise ValueError(f"A d12 has faces 1 to {D12_SIDES}; got {value}.")
    inner = size * SUPERSAMPLE
    canvas = Image.new("RGBA", (inner, inner), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    ink = text_color or high_contrast_ink(color)
    edge = outline or "#ffffff"
    # The board's ball is a 27px radius inside a 3px edge; keep that
    # proportion, and keep the polygon's points off the canvas edge by
    # the edge's own width so the outline is not clipped.
    edge_width = max(1, round(inner * 3 / 54))
    radius = inner / 2 - edge_width
    center = inner / 2
    draw.polygon(
        polygon_points(center, center, radius, D12_SIDES),
        fill=color,
        outline=edge,
        width=edge_width,
    )
    label = str(value)
    font = load_font(round(radius * 0.9), bold=True)
    bbox = draw.textbbox((0, 0), label, font=font)
    draw.text(
        (
            center - (bbox[2] - bbox[0]) / 2 - bbox[0],
            center - (bbox[3] - bbox[1]) / 2 - bbox[1],
        ),
        label,
        font=font,
        fill=ink,
    )
    return canvas.resize((size, size), Image.Resampling.LANCZOS)


def render_ball_die_face(value: int, size: int = DIE_FACE_SIZE) -> Image.Image:
    """The ball's face: white, with the board's own outline and ink."""
    return render_die_face(
        value,
        GOAL_ZONE_BALL_COLOR,
        size,
        outline=GOAL_ZONE_BALL_OUTLINE,
        text_color=GOAL_ZONE_BALL_OUTLINE,
    )


def fitted_token(path: Path, size: int) -> Optional[Image.Image]:
    """
    A tracked token PNG at `size` pixels a side, or None when the file
    is missing -- silent for the reason `render.py`'s loaders are (see
    "A bundled file's name is case-sensitive..." in
    docs/design/gotchas.md): the export goes on without it and the
    manifest, which lists only what was written, says so.
    """
    try:
        with Image.open(path) as source:
            image = source.convert("RGBA")
            image.load()
    except OSError:
        return None
    image = fit_image(image, size)
    # Centred on a square, so a token's pivot is its middle whatever
    # shape the art was cut to (the coin faces are not quite square).
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.alpha_composite(image, ((size - image.width) // 2, (size - image.height) // 2))
    return canvas


# ------------------------------------------------------------ the kit


@dataclass(frozen=True)
class Asset:
    """One file the export writes, and its manifest entry."""

    path: str
    image: Image.Image
    entry: dict


def slug(text: str) -> str:
    return text.lower().replace(" ", "-")


def maneuver_assets(
    catalog: ManeuverCatalog, players: PlayerCatalog, max_side: int
) -> list[Asset]:
    """
    A sheet a side -- a coach's whole hand, three basic over three
    gambits -- and the one shared back. Cards are named by key, never
    by name (see "Maneuvers" in CLAUDE.md), with the rank in front so
    a folder lists them in the order the hand shows them.
    """
    assets: list[Asset] = []
    back_path = "maneuver-cards/back.png"
    cell: Optional[tuple[int, int]] = None
    for side, is_offense in (("offense", True), ("defense", False)):
        # A row a tier, the basic three over the gambit of each rank,
        # which is the hand as the bot lays it out -- not the catalog's
        # own order, which interleaves the tiers rank by rank.
        cells = [
            (
                f"{side[0]}{maneuver.rank}-{maneuver.key.replace('_', '-')}",
                render_maneuver_card(catalog, players, maneuver, is_offense, bleed=False),
            )
            for tier in MANEUVER_TIERS
            for maneuver in catalog.for_tier(side, tier)
        ]
        sheet, layout, fitted = tabletop_sheet(cells, MANEUVER_SHEET_COLUMNS, max_side)
        assets.append(
            Asset(
                f"maneuver-cards/{side}-sheet.png",
                sheet,
                _sheet_entry("card_sheet", layout, back=back_path),
            )
        )
        assets.extend(_cell_assets("maneuver-cards", fitted, "card"))
        cell = layout.cell
    # The one back, at the same cell size as the faces it goes behind.
    back = render_maneuver_card_back(catalog, bleed=False).convert("RGBA")
    if cell is not None and back.size != cell:
        back = back.resize(cell, Image.Resampling.LANCZOS)
    assets.append(Asset(back_path, back, _image_entry("card_back", back)))
    return assets


def player_assets(catalog: PlayerCatalog, max_side: int) -> list[Asset]:
    """
    A team's fronts as one sheet and its advanced backs as another, in
    the same order -- cell `n` of one is the back of cell `n` of the
    other, which is what a tabletop pairs and a duplex printer does
    not (see the module note). Numbered as the roster lists them, the
    order the standard deal reads, like the print kit.
    """
    assets: list[Asset] = []
    for team, definition in catalog.teams.items():
        fronts: list[tuple[str, Image.Image]] = []
        backs: list[tuple[str, Image.Image]] = []
        for index, player in enumerate(definition.players, start=1):
            stem = f"{team.value}-{index}-{slug(player.name)}"
            fronts.append((stem, render_player_card(catalog, player, team, bleed=False)))
            backs.append(
                (f"{stem}-advanced", render_player_card_back(catalog, player, team, bleed=False))
            )

        back_path = f"player-cards/{team.value}-backs-sheet.png"
        front_sheet, front_layout, front_fitted = tabletop_sheet(
            fronts, PLAYER_SHEET_COLUMNS, max_side
        )
        back_sheet, back_layout, back_fitted = tabletop_sheet(
            backs, PLAYER_SHEET_COLUMNS, max_side
        )
        assets.append(
            Asset(
                f"player-cards/{team.value}-fronts-sheet.png",
                front_sheet,
                _sheet_entry("card_sheet", front_layout, back_sheet=back_path, team=team.value),
            )
        )
        assets.append(
            Asset(back_path, back_sheet, _sheet_entry("card_back_sheet", back_layout, team=team.value))
        )
        assets.extend(_cell_assets("player-cards", front_fitted, "card"))
        assets.extend(_cell_assets("player-cards", back_fitted, "card_back"))
    return assets


def species_assets(max_side: int) -> list[Asset]:
    """The three double-sided reference cards: a fronts sheet and a backs sheet."""
    faces = render_species_card_set(load_species_abilities())
    fronts = [(f"species-{name}", image) for name, image in faces if name.endswith("-front")]
    backs = [(f"species-{name}", image) for name, image in faces if name.endswith("-back")]
    back_path = "species-cards/backs-sheet.png"
    front_sheet, front_layout, front_fitted = tabletop_sheet(fronts, SPECIES_SHEET_COLUMNS, max_side)
    back_sheet, back_layout, back_fitted = tabletop_sheet(backs, SPECIES_SHEET_COLUMNS, max_side)
    return [
        Asset(
            "species-cards/fronts-sheet.png",
            front_sheet,
            _sheet_entry("card_sheet", front_layout, back_sheet=back_path),
        ),
        Asset(back_path, back_sheet, _sheet_entry("card_back_sheet", back_layout)),
        *_cell_assets("species-cards", front_fitted, "card"),
        *_cell_assets("species-cards", back_fitted, "card_back"),
    ]


def board_assets(
    rules: BasicRuleset,
    players: PlayerCatalog,
    maneuvers: ManeuverCatalog,
    max_side: int,
) -> list[Asset]:
    """
    Every field board the ruleset defines, the jumbotron, and a team
    board *panel* per team -- one coach's, not the print sheet's two,
    since a tabletop places a board a side rather than cutting a sheet
    in half. Plus one uncoloured panel for a table that wants the
    boards alike.
    """
    assets: list[Asset] = []
    for board_size in sorted(rules.board_layouts):
        image = fit_image(render_field_board(rules, board_size), max_side)
        assets.append(
            Asset(
                f"boards/field-board-{board_size}.png",
                image,
                _image_entry("board", image, board_size=board_size),
            )
        )
    jumbotron = fit_image(render_jumbotron_board(), max_side)
    assets.append(Asset("boards/jumbotron-board.png", jumbotron, _image_entry("board", jumbotron)))

    width, height = sheet_pixels(DEFAULT_PAPER, landscape=True)
    panel_height = height // 2
    for team in (None, *Team):
        panel = fit_image(
            render_team_board_panel(rules, players, maneuvers, team, width, panel_height),
            max_side,
        )
        suffix = f"-{team.value}" if team else ""
        assets.append(
            Asset(
                f"boards/team-board{suffix}.png",
                panel,
                _image_entry("board", panel, team=team.value if team else None),
            )
        )
    return assets


def meeple_assets(catalog: PlayerCatalog, max_side: int) -> list[Asset]:
    """
    A token a player a team, in two cuts: `meeples/` carries the
    species icon over the initials, for a game playing species
    abilities; `meeples-basic/` the initials alone, for one that is
    not. Both, always, because which a table wants is the game's
    setting and not the export's to guess. A sheet a team beside the
    single files, three across like the cards.
    """
    assets: list[Asset] = []
    for folder, species_icons in (("meeples", True), ("meeples-basic", False)):
        for team, definition in catalog.teams.items():
            cells = [
                (
                    f"meeple-{team.value}-{index}-{slug(player.name)}",
                    render_meeple_token(player, team, species_icons=species_icons),
                )
                for index, player in enumerate(definition.players, start=1)
            ]
            sheet, layout, fitted = tabletop_sheet(cells, MEEPLE_SHEET_COLUMNS, max_side)
            assets.append(
                Asset(
                    f"tokens/{folder}/{team.value}-sheet.png",
                    sheet,
                    _sheet_entry("token_sheet", layout, team=team.value, species_icons=species_icons),
                )
            )
            assets.extend(
                _cell_assets(f"tokens/{folder}", fitted, "token", team=team.value)
            )
    return assets


def die_assets(max_side: int) -> list[Asset]:
    """
    Twelve faces a die: one die per colour team (a species team shares
    its pair's hex) and the ball's white one. The faces are written
    singly and as a sheet, in face order.
    """
    dice: list[tuple[str, str, Optional[str], Optional[str]]] = [
        (team.value, TEAM_COLORS[team], None, None) for team in COLOR_TEAMS
    ]
    dice.append((BALL_DIE, GOAL_ZONE_BALL_COLOR, GOAL_ZONE_BALL_OUTLINE, GOAL_ZONE_BALL_OUTLINE))
    assets: list[Asset] = []
    for name, color, outline, ink in dice:
        cells = [
            (f"d12-{name}-{value}", render_die_face(value, color, outline=outline, text_color=ink))
            for value in range(1, D12_SIDES + 1)
        ]
        sheet, layout, fitted = tabletop_sheet(cells, DIE_SHEET_COLUMNS, max_side)
        assets.append(
            Asset(f"dice/d12-{name}-sheet.png", sheet, _sheet_entry("die_sheet", layout, sides=D12_SIDES))
        )
        assets.extend(_cell_assets("dice", fitted, "die_face"))
    return assets


def condition_token_assets() -> list[Asset]:
    """The condition tokens, and the coin's two faces."""
    assets: list[Asset] = []
    for name, path in CONDITION_TOKEN_ART.items():
        image = fitted_token(path, CONDITION_TOKEN_SIZE)
        if image is None:
            continue
        assets.append(Asset(f"tokens/conditions/{name}.png", image, _image_entry("token", image)))
    for face, path in COIN_FACE_ART.items():
        image = fitted_token(path, COIN_SIZE)
        if image is None:
            continue
        assets.append(
            Asset(f"tokens/coin-{face.value}.png", image, _image_entry("coin_face", image, face=face.value))
        )
    return assets


def build_assets(
    max_side: int = MAX_SIDE,
    rules: Optional[BasicRuleset] = None,
    players: Optional[PlayerCatalog] = None,
    maneuvers: Optional[ManeuverCatalog] = None,
) -> list[Asset]:
    """Every asset of the screentop module, in the order the manifest lists them."""
    if max_side < 1:
        raise ValueError("max_side must be at least 1 pixel.")
    rules = rules or load_basic_ruleset()
    players = players or load_player_catalog()
    maneuvers = maneuvers or load_maneuver_catalog()
    return [
        *maneuver_assets(maneuvers, players, max_side),
        *player_assets(players, max_side),
        *species_assets(max_side),
        *board_assets(rules, players, maneuvers, max_side),
        *meeple_assets(players, max_side),
        *die_assets(max_side),
        *condition_token_assets(),
    ]


def manifest(assets: Iterable[Asset], max_side: int) -> dict:
    return {
        "game": "D12 Ball",
        "generated": date.today().isoformat(),
        "max_side": max_side,
        "assets": [{"file": asset.path, **asset.entry} for asset in assets],
    }


def write_kit(
    out_dir: Path,
    max_side: int = MAX_SIDE,
    assets: Optional[list[Asset]] = None,
) -> dict:
    """
    Write every asset under `out_dir`, then `manifest.json` listing
    exactly what was written. Returns the manifest.
    """
    assets = build_assets(max_side) if assets is None else assets
    for asset in assets:
        path = out_dir / asset.path
        path.parent.mkdir(parents=True, exist_ok=True)
        asset.image.save(path)
    listing = manifest(assets, max_side)
    (out_dir / "manifest.json").write_text(json.dumps(listing, indent=2) + "\n")
    return listing


# ----------------------------------------------------------- entries


def _sheet_entry(kind: str, layout: SheetLayout, **extra) -> dict:
    entry = {"kind": kind, **asdict(layout)}
    entry["cell"] = list(layout.cell)
    entry["cells"] = list(layout.cells)
    entry["size"] = [layout.columns * layout.cell[0], layout.rows * layout.cell[1]]
    entry.update({key: value for key, value in extra.items() if value is not None})
    return entry


def _image_entry(kind: str, image: Image.Image, **extra) -> dict:
    entry = {"kind": kind, "size": list(image.size)}
    entry.update({key: value for key, value in extra.items() if value is not None})
    return entry


def _cell_assets(
    folder: str, fitted: list[tuple[str, Image.Image]], kind: str, **extra
) -> list[Asset]:
    return [
        Asset(f"{folder}/{name}.png", image, _image_entry(kind, image, **extra))
        for name, image in fitted
    ]
