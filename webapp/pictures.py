"""
The pictures a page draws the game with, other than the board's own
layout: the player cards, the maneuver cards and the bot's emoji.

**Every one is the model's own drawing**, never a second one. A player
card is `player_cards.render_player_card` (its advanced face,
`render_player_card_back`, in a game with the species abilities on),
a maneuver card is `cards.render_maneuver_card`, and the role badges,
team marks and condition marks are the PNGs the bot uploads as its
application emoji. A page that drew its own card would be a third
layout to keep right beside the printed one and the board's -- see
docs/design/cards.md, "One layout for print and Discord".

Nothing here reads a rule. What a card *is* is the catalog's; which
face a game shows is `RulesEngine.species_abilities_apply`, asked by
the caller. Pillow is CPU-bound, so every render is the caller's to
put in a worker thread (`asyncio.to_thread`), as every render on
Discord is.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw

from d12ball.cards import render_maneuver_card
from d12ball.components import ManeuverCatalog, PlayerCatalog
from d12ball.game import Team
from d12ball.player_cards import render_player_card, render_player_card_back
from d12ball.render import (
    BOARD_BOTTOM,
    BOARD_TOP,
    CARD_SIZE,
    GOAL_ZONE_WIDTH,
    draw_card,
    draw_end_zone,
)

#: The bot's emoji, as it uploads them (docs/design/teams-and-players.md,
#: "the emoji PNGs"). Served as they are: a page's role badge is the
#: same picture a Discord message's is.
EMOJI_DIR = Path(__file__).resolve().parent.parent / "d12ball" / "images" / "emoji"

#: The width a printed card is served at. The model draws one at
#: 750x1050 for print; a page shows it at a few hundred pixels at
#: most, and a third of the bytes is what a phone on a slow line
#: notices. `full` is the size the enlarged card is shown at.
CARD_WIDTHS = {"small": 250, "full": 500}

#: The species icons, ink and coloured, as `render.species_icon` reads
#: them. The page tints the ink one with a CSS mask, which is the tint
#: `species_icon` applies with Pillow.
SPECIES_DIR = EMOJI_DIR.parent / "species"

#: The board's own typefaces -- DejaVu for every word on it, Racing
#: Sans One for the goals -- so the page's board reads as the bot's.
FONT_DIR = EMOJI_DIR.parent.parent / "fonts"

#: `draw_card`'s frame: the team colour drawn this far outside the
#: card on every side.
CARD_FRAME = 3


def emoji_path(name: str) -> Optional[Path]:
    """
    One of the bundled emoji by its file name, or `None` for anything
    that is not one -- compared against the directory listing, never
    joined blind, so a request cannot walk out of the folder (and so a
    name's case is checked the way Linux would check it; see
    docs/design/gotchas.md, "the case-sensitive name").
    """
    return _listed(EMOJI_DIR, name, ".png")


def species_path(name: str) -> Optional[Path]:
    """A species icon by file name, checked the way `emoji_path` is."""
    return _listed(SPECIES_DIR, name, ".png")


def font_path(name: str) -> Optional[Path]:
    """A bundled font by file name, checked the way `emoji_path` is."""
    return _listed(FONT_DIR, name, ".ttf")


def _listed(folder: Path, name: str, suffix: str) -> Optional[Path]:
    for path in folder.iterdir():
        if path.name == name and path.suffix == suffix:
            return path
    return None


def board_card_png(
    catalog: PlayerCatalog,
    card_id: str,
    team: Team,
    *,
    exhaustion: int,
    exhausted: bool,
    injured: bool,
    cyborg: bool,
) -> bytes:
    """
    A player's card exactly as the bot's board draws it:
    `render.draw_card`, frame and marks and all -- the exhaustion token
    in the gap between that card's offense and its role, with its
    count, and the Exhausted or Injured badge (a Cyborg's Drained or
    Damaged) in its slot on the same row. Those are measured per card
    off the card's own fonts, which is why the page is handed this
    picture rather than laying the marks over a bare card itself.
    """
    player = catalog.player_by_id(card_id)
    width, height = CARD_SIZE
    canvas = Image.new(
        "RGBA", (width + 2 * CARD_FRAME, height + 2 * CARD_FRAME), (0, 0, 0, 0),
    )
    draw_card(
        canvas,
        ImageDraw.Draw(canvas),
        player,
        catalog.effective_profile(player),
        CARD_FRAME,
        CARD_FRAME,
        team,
        exhaustion=exhaustion,
        exhausted=exhausted,
        injured=injured,
        cyborg=cyborg,
    )
    return _encode(canvas)


def goal_png(team: Team, angle: int) -> bytes:
    """
    One end zone as the bot's board draws it (`render.draw_end_zone`):
    GOAL in the defending team's colour, turned 90 degrees at the home
    end and 270 at the visitors', with the d12 standing in for the O.
    """
    height = BOARD_BOTTOM - BOARD_TOP
    canvas = Image.new("RGBA", (GOAL_ZONE_WIDTH, height), (0, 0, 0, 0))
    draw_end_zone(
        canvas,
        ImageDraw.Draw(canvas),
        team,
        0,
        GOAL_ZONE_WIDTH - 1,
        top=0,
        bottom=height - 1,
        angle=angle,
    )
    return _encode(canvas)


def _encode(image: Image.Image) -> bytes:
    out = BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue()


def player_card_png(
    catalog: PlayerCatalog,
    card_id: str,
    team: Team,
    *,
    advanced: bool,
    size: str,
) -> bytes:
    """One player's card, as the team this match fields them for."""
    player = catalog.player_by_id(card_id)
    draw = render_player_card_back if advanced else render_player_card
    return _png(draw(catalog, player, team, False), size)


def maneuver_card_png(
    maneuvers: ManeuverCatalog,
    catalog: PlayerCatalog,
    key: str,
    *,
    offense: bool,
    size: str,
) -> bytes:
    """One maneuver card, in the colour of the side holding it."""
    maneuver = maneuvers.get(key)
    if maneuver is None:
        raise KeyError(key)
    return _png(
        render_maneuver_card(maneuvers, catalog, maneuver, offense, False),
        size,
    )


def _png(image: Image.Image, size: str) -> bytes:
    width = CARD_WIDTHS[size]
    height = round(image.height * width / image.width)
    out = BytesIO()
    image.convert("RGB").resize((width, height), Image.LANCZOS).save(
        out, format="PNG", optimize=True,
    )
    return out.getvalue()
