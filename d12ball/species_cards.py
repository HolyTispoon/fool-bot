"""
The four species abilities as a reference card, print-ready for the
tabletop game.

Every player of a species carries that species' ability, so there is
one card per *pairing* of species rather than one per player: a
species-vs-species game only ever needs the two abilities in play, and
the three double-sided cards below cover all six pairings, each face
carrying two abilities. Lay the card whose face matches the two teams
between the coaches -- its back happens to carry the other two, which
is harmless.

    card 1   Volatile · Lithium powered   /   Mind Pull · Slimey
    card 2   Volatile · Mind Pull         /   Lithium powered · Slimey
    card 3   Volatile · Slimey            /   Lithium powered · Mind Pull

A mixed colour team fields all four species -- hand that coach the
whole set.

Same poker size and the same print machinery as `d12ball/cards.py`
(`Pen`, the sheet, the palette). Nothing here is written in the module:
the names and text come from `d12ball/data/species.json`, which
`scripts/import_d12ball_species.py` regenerates from the sheet's
`spec_abilities` tab -- so a revision reaches the cards by re-importing
and re-running `scripts/render_species_cards.py`.
"""
import json
from pathlib import Path

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
    Pen,
    font,
)
from d12ball.game import Team
from d12ball.render import (
    TEAM_COLORS,
    high_contrast_ink,
    load_goal_zone_font,
)

DATA_FILE = Path(__file__).resolve().parent / "data" / "species.json"

# The species order the card set is built in, and the colour each
# panel's header band is drawn in -- the paired colour team's hex, the
# same one the board draws that species' meeples in. See "Team colors"
# in CLAUDE.md.
SPECIES_ORDER = ("fire_demon", "cyborg", "telekinetic", "ooze")
SPECIES_LABEL = {
    "fire_demon": "Fire Demon",
    "cyborg": "Cyborg",
    "telekinetic": "Telekinetic",
    "ooze": "Ooze",
}
SPECIES_TEAM = {
    "fire_demon": Team.FIRE_DEMONS,
    "cyborg": Team.CYBORGS,
    "telekinetic": Team.TELEKINETICS,
    "ooze": Team.OOZES,
}

# The three double-sided cards: the three ways to split the four
# abilities into two disjoint pairs, which together name every pairing
# exactly once.
CARD_FACES: tuple[tuple[tuple[str, str], tuple[str, str]], ...] = (
    (("fire_demon", "cyborg"), ("telekinetic", "ooze")),
    (("fire_demon", "telekinetic"), ("cyborg", "ooze")),
    (("fire_demon", "ooze"), ("cyborg", "telekinetic")),
)

HEADER_HEIGHT = 44
BAND_HEIGHT = 96
PANEL_GAP = 22


def load_species_abilities() -> dict[str, dict[str, str]]:
    """The four species abilities, keyed `fire_demon` / `cyborg` / ..."""
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    return data["species"]


def _fitted_display(
    pen: Pen, text: str, max_width: float
) -> ImageFont.ImageFont:
    for size in range(52, 23, -2):
        face = load_goal_zone_font(size * 2)
        if pen.text_size(text, face)[0] <= max_width:
            return face
    return load_goal_zone_font(24 * 2)


def _fitted_body(
    pen: Pen, lines_text: str, max_width: float, max_height: float
) -> tuple[ImageFont.ImageFont, list[str], float]:
    """The largest body size whose wrapped sentence fits the panel."""
    for size in range(40, 17, -1):
        face = font(size)
        lines = pen.wrapped(lines_text, face, max_width)
        step = pen.text_size("Hg", face)[1] * 1.5
        block = step * len(lines)
        if block <= max_height:
            return face, lines, step
    face = font(18)
    return face, pen.wrapped(lines_text, face, max_width), (
        pen.text_size("Hg", face)[1] * 1.5
    )


def _draw_panel(
    pen: Pen,
    species: str,
    ability: dict[str, str],
    top: float,
    bottom: float,
) -> None:
    color = TEAM_COLORS[SPECIES_TEAM[species]]
    band_ink = high_contrast_ink(color)
    left = MARGIN
    right = CARD_WIDTH - MARGIN

    pen.rect(
        (left, top, right, top + BAND_HEIGHT),
        radius=18,
        fill=color,
    )

    name = ability["name"].upper()
    name_face = _fitted_display(pen, name, right - left - 220)
    pen.text(
        (left + 22, top + BAND_HEIGHT / 2),
        name,
        name_face,
        band_ink,
        anchor="lm",
    )
    pen.text(
        (right - 22, top + BAND_HEIGHT / 2),
        SPECIES_LABEL[species],
        font(19),
        band_ink,
        anchor="rm",
    )

    # Only the full sentence -- a card on a table is the whole of what
    # its coach has, and `ability_short` sitting under it in the same
    # panel is the same words a size smaller. It stays in species.json
    # for anywhere the sentence does not fit.
    body_top = top + BAND_HEIGHT + 24
    sentence = " ".join(ability["ability"].split())
    body_face, body_lines, body_step = _fitted_body(
        pen, sentence, right - left, bottom - body_top
    )

    y = body_top
    for line in body_lines:
        pen.text((left, y), line, body_face, INK, anchor="la")
        y += body_step


def render_species_card(
    abilities: dict[str, dict[str, str]],
    pair: tuple[str, str],
    bleed: bool = False,
) -> Image.Image:
    """One face: the two species abilities in `pair`, stacked."""
    pen = Pen((CARD_WIDTH, CARD_HEIGHT), CARD_FACE)
    pen.rect(
        (FRAME, FRAME, CARD_WIDTH - FRAME, CARD_HEIGHT - FRAME),
        radius=CORNER,
        fill=CARD_FACE,
        outline=INK,
        width=EDGE_WIDTH,
    )
    pen.text(
        (CARD_WIDTH / 2, FRAME + 30),
        "SPECIES ABILITIES",
        font(17),
        MUTED,
        anchor="mm",
    )

    top = FRAME + HEADER_HEIGHT + 14
    usable = CARD_HEIGHT - FRAME - 40 - top
    panel_height = (usable - PANEL_GAP) / 2
    for index, species in enumerate(pair):
        panel_top = top + index * (panel_height + PANEL_GAP)
        _draw_panel(
            pen, species, abilities[species], panel_top,
            panel_top + panel_height,
        )

    return pen.finish(bleed, CARD_FACE)


def render_species_card_set(
    abilities: dict[str, dict[str, str]],
    bleed: bool = False,
) -> list[tuple[str, Image.Image]]:
    """Every face of the three-card set, named `<n>-front` / `<n>-back`."""
    out: list[tuple[str, Image.Image]] = []
    for number, (front, back) in enumerate(CARD_FACES, start=1):
        out.append(
            (f"{number}-front", render_species_card(abilities, front, bleed))
        )
        out.append(
            (f"{number}-back", render_species_card(abilities, back, bleed))
        )
    return out
