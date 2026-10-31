"""
**D12 Ball 2.1's maneuver cards as pictures** -- the face, a coach's
hand of five and the face-up discard piles -- redrawn from scratch for
the 2.1 deck (the author, 2026-10-31; docs/rules-2.1.md,
docs/design/maneuver-deck.md, "The faces").

A face reads top to bottom in the order a coach needs it:

- **the header**, the card's name and its rank badge (O1, D2), with
  its index and the maneuver it plays under the name;
- **the main effect**, the rank's own wording, largest;
- **the role interaction**, in a box tinted with the card's colour and
  headed with the roles it names in full;
- **an empty, labelled space for the spec ability** that advanced mode
  will add (the `Spec` column), its name printed small where the tab
  gives one;
- **the flip strip**, green, along the bottom: "Discard an extra card:
  play as Deflect" -- the same rank's maneuver on the other side.

Offense is 1.0's red; defense is navy, `#0B2545` (the author). Every
face is drawn once and kept. Nothing printed is tested (the author,
2026-09-23): render them with `scripts/render_maneuver_cards.py
--edition 2.1` and look.

Pillow, like `cards.py`, whose pen and fonts it draws with; nothing in
the game imports it.
"""

from __future__ import annotations

from functools import lru_cache
from io import BytesIO
from typing import Sequence

from PIL import Image, ImageDraw

from d12ball import maneuver_deck
from d12ball.cards import (
    CARD_FACE,
    CARD_HEIGHT,
    CARD_WIDTH,
    CORNER,
    EDGE_WIDTH,
    FACE_COLOR,
    FRAME,
    INK,
    MARGIN,
    MUTED,
    OFFENSE_COLOR,
    Pen,
    fitted_bold_font,
    font,
    line_height,
    matchup_rank_groups,
    rank_font,
)
from d12ball.components import DeckCard, ManeuverCatalog, PlayerCatalog
from d12ball.render import load_font

#: The two sides' colours on a 2.1 face: 1.0's offence red, and navy
#: for defence (the author, 2026-10-31).
DEFENSE_NAVY = "#0B2545"
SIDE_COLORS = {"offense": OFFENSE_COLOR, "defense": DEFENSE_NAVY}
#: Each colour's tint for the role-interaction box behind its words.
SIDE_TINTS = {"offense": "#fbe4e3", "defense": "#dfe6f0"}
#: The flip strip along the bottom.
FLIP_GREEN = "#2e7d32"

#: The six roles in full, for the interaction box's heading.
ROLE_WORDS = {
    "fullback": "Fullback",
    "defender": "Defender",
    "midfielder": "Midfielder",
    "playmaker": "Playmaker",
    "winger": "Winger",
    "striker": "Striker",
}

HEADER_HEIGHT = 150
BADGE_RADIUS = 48
SECTION_GAP = 22
BOX_PAD = 18
BOX_HEADING = 24
FLIP_HEIGHT = 92
MATCHUP_HEIGHT = 118


def card_color(card: DeckCard) -> str:
    return SIDE_COLORS[card.side]


def flip_target(catalog: ManeuverCatalog, card: DeckCard) -> str:
    """The maneuver a card plays flipped: its rank's on the other side."""
    other = maneuver_deck.OTHER_SIDE[card.side]
    key = maneuver_deck.basic_on(catalog, other, card.rank)
    return catalog.display_name(key)


def rank_label(card: DeckCard) -> str:
    return f"{'O' if card.side == 'offense' else 'D'}{card.rank}"


def _fit_paragraph(
    pen: Pen, text: str, width: float, height: float, largest: int, smallest: int,
) -> tuple[object, list[str]]:
    """The largest size from `largest` down whose wrapped lines fit."""
    for size in range(largest, smallest - 1, -1):
        face = font(size)
        lines = pen.wrapped(text, face, width)
        if len(lines) * line_height(pen, face) <= height:
            return face, lines
    face = font(smallest)
    return face, pen.wrapped(text, face, width)


def _draw_lines(pen: Pen, lines, face, x: float, top: float, fill: str) -> float:
    step = line_height(pen, face)
    for line in lines:
        pen.text((x, top), line, face, fill)
        top += step
    return top


def draw_header(pen: Pen, catalog: ManeuverCatalog, card: DeckCard) -> None:
    color = card_color(card)
    pen.rect_in_card(
        (FRAME, FRAME, CARD_WIDTH - FRAME, FRAME + HEADER_HEIGHT), color,
        inset=EDGE_WIDTH / 2,
    )
    center = (MARGIN + BADGE_RADIUS + 6, FRAME + HEADER_HEIGHT / 2)
    pen.circle(center, BADGE_RADIUS, fill=CARD_FACE)
    pen.text(center, rank_label(card), rank_font(44), color, anchor="mm")

    left = center[0] + BADGE_RADIUS + 22
    room = CARD_WIDTH - MARGIN - left
    name_face = fitted_bold_font(pen, card.name, room, max_size=56, min_size=30) or font(30, bold=True)
    pen.text((left, FRAME + HEADER_HEIGHT / 2 + 4), card.name, name_face, "#ffffff", anchor="ls")
    maneuver = catalog.display_name(card.maneuver).upper()
    minutes = "1 TIME" if card.time == "1" else f"{card.time} TIME"
    pen.text(
        (left, FRAME + HEADER_HEIGHT / 2 + 16),
        f"{card.index}  ·  {maneuver}  ·  {minutes}",
        font(22, bold=True), "#ffffff", anchor="lt",
    )


def draw_face(pen: Pen, catalog: ManeuverCatalog, card: DeckCard) -> None:
    color = card_color(card)
    pen.rect(
        (FRAME, FRAME, CARD_WIDTH - FRAME, CARD_HEIGHT - FRAME),
        radius=CORNER, fill=CARD_FACE, outline=color, width=EDGE_WIDTH,
    )
    draw_header(pen, catalog, card)

    inner_left, inner_right = MARGIN, CARD_WIDTH - MARGIN
    width = inner_right - inner_left
    flip_top = CARD_HEIGHT - FRAME - FLIP_HEIGHT
    top = FRAME + HEADER_HEIGHT + SECTION_GAP

    # The effect first and largest, then the interaction box under it,
    # each as tall as its own words; the spec ability's space takes
    # whatever is left above the flip strip, which is room for the
    # ability it will carry.
    effect_face, effect_lines = _fit_paragraph(
        pen, card.effect, width, 200, 44, 26,
    )
    top = _draw_lines(pen, effect_lines, effect_face, inner_left, top, INK)

    heading = " OR ".join(ROLE_WORDS[role.value].upper() for role in card.roles)
    special_face, special_lines = _fit_paragraph(
        pen, card.special, width - BOX_PAD * 2, 170, 32, 22,
    )
    box_top = top + SECTION_GAP - 6
    box_height = (
        BOX_PAD + BOX_HEADING + 12
        + len(special_lines) * line_height(pen, special_face) + BOX_PAD - 10
    )
    pen.rect(
        (inner_left, box_top, inner_right, box_top + box_height),
        radius=16, fill=SIDE_TINTS[card.side], outline=color, width=3,
    )
    pen.text(
        (inner_left + BOX_PAD, box_top + BOX_PAD), f"IF {heading}",
        font(BOX_HEADING - 2, bold=True), color,
    )
    _draw_lines(
        pen, special_lines, special_face, inner_left + BOX_PAD,
        box_top + BOX_PAD + BOX_HEADING + 12, INK,
    )

    # The spec ability's space: empty until advanced mode is written,
    # labelled, with the ability's name where the tab gives one.
    spec_top = box_top + box_height + SECTION_GAP
    matchup_top = flip_top - MATCHUP_HEIGHT
    spec_bottom = matchup_top - SECTION_GAP
    pen.rect(
        (inner_left, spec_top, inner_right, spec_bottom),
        radius=16, outline=MUTED, width=2,
    )
    pen.text(
        (inner_left + BOX_PAD, spec_top + BOX_PAD), "SPEC ABILITY",
        font(18, bold=True), MUTED,
    )
    if card.spec:
        pen.text(
            (inner_right - BOX_PAD, spec_top + BOX_PAD), card.spec,
            font(20), MUTED, anchor="ra",
        )

    draw_matchup_row(pen, catalog, card, matchup_top)

    pen.rect_in_card(
        (FRAME, flip_top, CARD_WIDTH - FRAME, CARD_HEIGHT - FRAME), FLIP_GREEN,
        inset=EDGE_WIDTH / 2,
    )
    flip_text = f"Discard an extra card: play as {flip_target(catalog, card)}"
    flip_face = fitted_bold_font(pen, flip_text, width, max_size=30, min_size=18) or font(18, bold=True)
    pen.text(
        (CARD_WIDTH / 2, flip_top + FLIP_HEIGHT / 2 - 4), flip_text,
        flip_face, "#ffffff", anchor="mm",
    )


def draw_matchup_row(
    pen: Pen, catalog: ManeuverCatalog, card: DeckCard, top: float,
) -> None:
    """
    **What the card beats, ties and loses to** (the author, 2026-10-31:
    "Need the matchup row"), by rank as 1.0's row reads (`matchup_rank_groups`)
    -- the other side's rank badge in its own colour and the basic
    maneuver on it, since 2.1 has no advanced cards to name beside it.
    Every card of a rank reads the same row, as rank alone decides.
    """
    maneuver = catalog.definition(card.maneuver)
    is_offense = card.side == "offense"
    other = maneuver_deck.OTHER_SIDE[card.side]
    letter = "D" if is_offense else "O"
    color = SIDE_COLORS[other]
    groups = matchup_rank_groups(catalog, maneuver, is_offense)
    left, right = MARGIN, CARD_WIDTH - MARGIN
    column = (right - left) / 3
    pen.line([(left + 10, top + 4), (right - 10, top + 4)], fill=MUTED, width=2)
    for index, (label, (rank, _)) in enumerate(
        zip(("BEATS", "TIES", "LOSES TO"), groups)
    ):
        cx = left + column * (index + 0.5)
        name = catalog.display_name(maneuver_deck.basic_on(catalog, other, rank))
        pen.text((cx, top + 24), label, font(18, bold=True), MUTED, anchor="mm")
        pen.text((cx, top + 58), f"{letter}{rank}", rank_font(36), color, anchor="mm")
        name_face = fitted_bold_font(
            pen, name, column - 14, max_size=24, min_size=16,
        ) or font(16, bold=True)
        pen.text((cx, top + 94), name, name_face, color, anchor="mm")
        if index:
            pen.line(
                [(left + column * index, top + 16), (left + column * index, top + MATCHUP_HEIGHT - 10)],
                fill=MUTED, width=2,
            )


@lru_cache(maxsize=None)
def _face(catalog: ManeuverCatalog, card_id: str, bleed: bool) -> Image.Image:
    card = catalog.deck_card(card_id)
    if card is None:
        raise KeyError(f"Unknown 2.1 card {card_id!r}.")
    pen = Pen((CARD_WIDTH, CARD_HEIGHT), CARD_FACE)
    draw_face(pen, catalog, card)
    return pen.finish(bleed, CARD_FACE)


def render_deck_card(
    catalog: ManeuverCatalog, card_id: str, bleed: bool = False,
) -> Image.Image:
    """One 2.1 card's face at the printed size, drawn once and kept."""
    return _face(catalog, card_id, bleed)


# -- A coach's hand ----------------------------------------------------

HAND_CARD_WIDTH = 360
HAND_GAP = 16
HAND_MARGIN = 20
HAND_HEADINGS = {"offense": "YOUR HAND -- ON OFFENSE", "defense": "YOUR HAND -- ON DEFENSE"}


def render_deck_hand(
    catalog: ManeuverCatalog,
    players: PlayerCatalog,
    held: Sequence[str],
    side: str,
) -> BytesIO:
    """
    **A 2.1 coach's hand**, for their eyes alone: the five cards in one
    row under a heading naming the side being played, this side's cards
    first by rank, then the other side's -- each playable here only
    flipped, which its green strip says. `players` is unused, kept so
    the cog's call reads as before.
    """
    def order(card_id: str) -> tuple:
        card = catalog.deck_card(card_id)
        if card is None:
            return (2, 0, 0)
        return (0 if card.side == side else 1, card.rank, card.number)

    faces = [render_deck_card(catalog, card_id) for card_id in sorted(held, key=order)]
    scale = HAND_CARD_WIDTH / CARD_WIDTH
    card_height = round(CARD_HEIGHT * scale)
    heading_font = load_font(30, bold=True)
    heading_band = 46
    width = HAND_MARGIN * 2 + len(faces) * HAND_CARD_WIDTH + max(0, len(faces) - 1) * HAND_GAP
    # White, the faces' own paper, so their rounded corners do not show.
    canvas = Image.new("RGB", (max(width, 400), HAND_MARGIN * 2 + heading_band + card_height), CARD_FACE)
    draw = ImageDraw.Draw(canvas)
    draw.text((HAND_MARGIN, HAND_MARGIN), HAND_HEADINGS[side], font=heading_font, fill=SIDE_COLORS[side])
    x = HAND_MARGIN
    for face in faces:
        canvas.paste(
            face.resize((HAND_CARD_WIDTH, card_height), Image.Resampling.LANCZOS),
            (x, HAND_MARGIN + heading_band),
        )
        x += HAND_CARD_WIDTH + HAND_GAP
    buffer = BytesIO()
    canvas.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


# -- The discard piles -------------------------------------------------

CHIP_WIDTH = 270
CHIP_HEIGHT = 58
CHIP_RADIUS = 12
CHIP_BADGE = 21
CHIP_GAP = 4
PILE_GAP = 20


@lru_cache(maxsize=None)
def discard_chip(catalog: ManeuverCatalog, card_id: str) -> Image.Image:
    """
    One discarded card as a chip, in the new face's colours: its rank
    badge, and its index and name -- what tells one card from another
    in a pile read for what has gone (the author, 2026-10-18).
    """
    card = catalog.deck_card(card_id)
    color = SIDE_COLORS[card.side] if card is not None else MUTED
    pen = Pen((CHIP_WIDTH, CHIP_HEIGHT), CARD_FACE)
    pen.rect((0, 0, CHIP_WIDTH, CHIP_HEIGHT), radius=CHIP_RADIUS, fill=color)
    center = (8 + CHIP_BADGE, CHIP_HEIGHT / 2)
    pen.circle(center, CHIP_BADGE, fill=CARD_FACE)
    if card is not None:
        pen.text(center, rank_label(card), rank_font(19), color, anchor="mm")
        left = center[0] + CHIP_BADGE + 12
        label = f"{card.index} {card.name}"
        face = fitted_bold_font(pen, label, CHIP_WIDTH - left - 10, max_size=26, min_size=15) or font(15, bold=True)
        pen.text((left, CHIP_HEIGHT / 2), label, face, "#ffffff", anchor="lm")
    chip = pen.image.resize((CHIP_WIDTH, CHIP_HEIGHT), Image.Resampling.LANCZOS).convert("RGBA")
    mask = Image.new("L", pen.image.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, pen.image.width - 1, pen.image.height - 1),
        radius=round(CHIP_RADIUS * pen.image.width / CHIP_WIDTH), fill=255,
    )
    chip.putalpha(mask.resize((CHIP_WIDTH, CHIP_HEIGHT), Image.Resampling.LANCZOS))
    return chip


def render_discard_piles(
    catalog: ManeuverCatalog,
    players: PlayerCatalog,
    piles: Sequence[tuple[str, str, Sequence[str]]],
) -> BytesIO:
    """
    **The 2.1 discard piles, face up**, for the public maneuver prompt:
    one `(heading, colour, card ids)` per coach, each a column of chips
    (`discard_chip`) in the order the cards went down, the columns side
    by side (the author, 2026-10-20). Every card is one of a kind, so a
    pile holds each at most once. An empty pile says so. `players` is
    unused, kept so the cog's call reads as before.
    """
    heading_font = load_font(26, bold=True)
    empty_font = load_font(22)
    heading_band = 34
    empty_text = "Nothing discarded yet."
    columns = []
    for heading, colour, cards in piles:
        chips = [discard_chip(catalog, card_id) for card_id in cards]
        title = f"{heading} ({len(cards)})"
        width = max(
            CHIP_WIDTH, round(heading_font.getlength(title)),
            0 if chips else round(empty_font.getlength(empty_text)),
        )
        height = len(chips) * (CHIP_HEIGHT + CHIP_GAP) - CHIP_GAP if chips else 30
        columns.append((title, colour, chips, width, height))
    canvas = Image.new(
        "RGB",
        (
            HAND_MARGIN * 2 + sum(c[3] for c in columns) + PILE_GAP * (len(columns) - 1),
            HAND_MARGIN * 2 + heading_band + max(c[4] for c in columns),
        ),
        FACE_COLOR,
    )
    draw = ImageDraw.Draw(canvas)
    x = HAND_MARGIN
    for title, colour, chips, width, _ in columns:
        y = HAND_MARGIN
        draw.text((x, y), title, font=heading_font, fill=colour)
        y += heading_band
        if not chips:
            draw.text((x, y), empty_text, font=empty_font, fill=MUTED)
        for chip in chips:
            canvas.paste(chip, (x, y), chip)
            y += CHIP_HEIGHT + CHIP_GAP
        x += width + PILE_GAP
    buffer = BytesIO()
    canvas.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer
