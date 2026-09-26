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
from PIL import Image, ImageFont

from d12ball.cards import (
    CARD_HEIGHT,
    CARD_WIDTH,
    CORNER,
    DARK_REFERENCE,
    EDGE_WIDTH,
    FRAME,
    MARGIN,
    PRINT_REFERENCE,
    Pen,
    ReferencePalette,
    font,
    screen_cutout,
)
from d12ball.components import SPECIES_ORDER, load_species_abilities
from d12ball.game import Team
from d12ball.render import (
    TEAM_COLORS,
    high_contrast_ink,
    load_goal_zone_font,
    species_icon,
)

# The species order the card set is built in, and the colour each
# panel's header band is drawn in -- the paired colour team's hex, the
# same one the board draws that species' meeples in. See "Team colors"
# in docs/design/teams-and-players.md.
#
# `SPECIES_ORDER` is `d12ball/components.py`'s now, since the engine
# reads species to play the abilities and cannot import this module.
# It is re-exported here so `from d12ball.species_cards import
# SPECIES_ORDER` keeps working.
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

# The species icon at the head of its own panel, in the band's ink for
# the reason the printed player card's is: the band is already a
# colour, and `high_contrast_ink` is what keeps the Oozes' green one
# readable. It is the same silhouette the player cards and the board
# carry, so a coach matches this panel to the cards in front of them
# without reading either.
BAND_ICON = 62
BAND_ICON_GAP = 18


def _fitted_display(
    pen: Pen, text: str, max_width: float
) -> ImageFont.ImageFont:
    for size in range(52, 23, -2):
        face = load_goal_zone_font(size * 2)
        if pen.text_size(text, face)[0] <= max_width:
            return face
    return load_goal_zone_font(24 * 2)


def _paragraphs(ability: str) -> list[str]:
    """
    The ability split into the paragraphs the sheet wrote it in.

    Two of the four abilities name their sub-actions -- the Cyborg's
    Overdrive and Charge-up, the Telekinetic's Mind Pull and Smooth --
    and put
    each on its own line in `spec_abilities`. Run together into one
    block they stop scanning as separate things, so the line breaks are
    kept and only the wrapping inside a paragraph is the card's to
    decide.
    """
    return [
        " ".join(line.split())
        for line in ability.splitlines()
        if line.strip()
    ]


def _fitted_body(
    pen: Pen,
    paragraphs: list[str],
    max_width: float,
    max_height: float,
) -> tuple[ImageFont.ImageFont, list[list[str]], float, float]:
    """The largest body size at which every paragraph fits the panel."""
    def measure(size: int):
        face = font(size)
        blocks = [pen.wrapped(text, face, max_width) for text in paragraphs]
        step = pen.text_size("Hg", face)[1] * 1.5
        gap = step * 0.45
        height = step * sum(len(b) for b in blocks) + gap * (len(blocks) - 1)
        return face, blocks, step, gap, height

    for size in range(40, 17, -1):
        face, blocks, step, gap, height = measure(size)
        if height <= max_height:
            return face, blocks, step, gap
    face, blocks, step, gap, _ = measure(18)
    return face, blocks, step, gap


def _draw_panel(
    pen: Pen,
    species: str,
    ability: dict[str, str],
    top: float,
    bottom: float,
    palette: ReferencePalette,
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

    icon = species_icon(species, band_ink)
    name_left = left + 22
    if icon is not None:
        pen.paste(
            icon,
            (name_left + BAND_ICON / 2, top + BAND_HEIGHT / 2),
            (BAND_ICON, BAND_ICON),
        )
        name_left += BAND_ICON + BAND_ICON_GAP

    name = ability["name"].upper()
    name_face = _fitted_display(pen, name, right - name_left - 198)
    pen.text(
        (name_left, top + BAND_HEIGHT / 2),
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
    body_face, blocks, body_step, para_gap = _fitted_body(
        pen, _paragraphs(ability["ability"]), right - left,
        bottom - body_top,
    )

    y = body_top
    for index, lines in enumerate(blocks):
        if index:
            y += para_gap
        for line in lines:
            pen.text((left, y), line, body_face, palette.ink, anchor="la")
            y += body_step


def render_species_card(
    abilities: dict[str, dict[str, str]],
    pair: tuple[str, str],
    bleed: bool = False,
    palette: ReferencePalette = PRINT_REFERENCE,
) -> Image.Image:
    """One face: the two species abilities in `pair`, stacked."""
    pen = Pen((CARD_WIDTH, CARD_HEIGHT), palette.face)
    pen.rect(
        (FRAME, FRAME, CARD_WIDTH - FRAME, CARD_HEIGHT - FRAME),
        radius=CORNER,
        fill=palette.face,
        outline=palette.edge,
        width=EDGE_WIDTH,
    )
    pen.text(
        (CARD_WIDTH / 2, FRAME + 30),
        "SPECIES ABILITIES",
        font(17),
        palette.muted,
        anchor="mm",
    )

    top = FRAME + HEADER_HEIGHT + 14
    usable = CARD_HEIGHT - FRAME - 40 - top
    panel_height = (usable - PANEL_GAP) / 2
    for index, species in enumerate(pair):
        panel_top = top + index * (panel_height + PANEL_GAP)
        _draw_panel(
            pen, species, abilities[species], panel_top,
            panel_top + panel_height, palette,
        )

    return pen.finish(bleed, palette.face)


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


# The gap between the two faces on the on-screen reference. It is
# transparent, like the cut-out corners, so the two faces read as two
# cards side by side on whatever the channel is drawn in.
REFERENCE_GAP = 24


def render_species_reference(
    abilities: dict[str, dict[str, str]],
) -> Image.Image:
    """
    All four abilities as one image, for a screen: the two faces of
    the set's first card side by side. Between them they carry every
    ability once; the other two cards only pair the same four
    differently, which matters on a table and not on a screen.

    One image rather than two because Discord crops two attachments on
    one message to a pair of tiles, cutting off each card's text; one
    image is shown whole and opens full-size.

    Drawn in `DARK_REFERENCE` with the corners cut out, because it is
    only ever posted, never printed.
    """
    faces = [
        screen_cutout(
            render_species_card(abilities, pair, palette=DARK_REFERENCE)
        )
        for pair in CARD_FACES[0]
    ]
    sheet = Image.new(
        "RGBA",
        (CARD_WIDTH * len(faces) + REFERENCE_GAP * (len(faces) - 1),
         CARD_HEIGHT),
        (0, 0, 0, 0),
    )
    for index, face in enumerate(faces):
        sheet.paste(face, (index * (CARD_WIDTH + REFERENCE_GAP), 0))
    return sheet
