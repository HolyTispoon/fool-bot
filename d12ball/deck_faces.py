"""
**D12 Ball 2.2's maneuver cards as pictures** -- the face, a coach's
hand of three and the face-up discard piles (the author, 2026-10-31
and 2026-11-01; docs/rules-2.2.md, docs/design/maneuver-deck.md, "The
faces").

**A card is split** (the author, 2026-11-01): its offensive half on
top, in red, its defensive half below, in navy, both upright, and
between them the band of what each beats, ties and loses to
(`draw_split_face`). Each half is a header -- the rank badge, the
maneuver as the title and the half's own name, index and time under it
-- the rank's effect, and the role interaction in its tinted box.
2.1's single-faced card, with its spec ability's space and its flip
strip, went with 2.1 (archive/rules-2.1/).

Offense is 1.0's red; defense is navy, `#0B2545` (the author). Every
face is drawn once and kept. Nothing printed is tested (the author,
2026-09-23): render them with `scripts/render_maneuver_cards.py
--edition 2.0` and look.

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

#: The two sides' colours on a 2.2 face: 1.0's offence red, and navy
#: for defence (the author, 2026-10-31).
DEFENSE_NAVY = "#0B2545"
SIDE_COLORS = {"offense": OFFENSE_COLOR, "defense": DEFENSE_NAVY}
#: Each colour's tint for the role-interaction box behind its words.
SIDE_TINTS = {"offense": "#fbe4e3", "defense": "#dfe6f0"}

#: The six roles in full, for the interaction box's heading.
ROLE_WORDS = {
    "fullback": "Fullback",
    "defender": "Defender",
    "midfielder": "Midfielder",
    "playmaker": "Playmaker",
    "winger": "Winger",
    "striker": "Striker",
}

BOX_PAD = 18
BOX_HEADING = 24


def card_color(card: DeckCard) -> str:
    return SIDE_COLORS[card.side]


def rank_label(card: DeckCard) -> str:
    return f"{'O' if card.side == 'offense' else 'D'}{card.rank}"


def _draw_lines(pen: Pen, lines, face, x: float, top: float, fill: str) -> float:
    step = line_height(pen, face)
    for line in lines:
        pen.text((x, top), line, face, fill)
        top += step
    return top


# -- The split card ----------------------------------------------------

#: A split card's three parts, top to bottom: the offensive half, the
#: band of what beats what, the defensive half.
SPLIT_BAND = 176
SPLIT_HALF = (CARD_HEIGHT - 2 * FRAME - SPLIT_BAND) / 2
SPLIT_HEADER = 104
SPLIT_BADGE = 40
#: The band's paper, a warm grey the two halves' white stands off.
BAND_FILL = "#efe8da"
BAND_RULE = "#c9bfad"


def draw_split_header(
    pen: Pen, catalog: ManeuverCatalog, card: DeckCard, top: float,
    corner: bool = False,
) -> None:
    """A half's header: the rank badge, the maneuver as the title, and
    the half's own name with its index and time under it. The top
    half's (`corner`) sits in the card's rounded corner, so its words
    stand a little lower and further in."""
    color = card_color(card)
    pen.rect_in_card(
        (FRAME, top, CARD_WIDTH - FRAME, top + SPLIT_HEADER), color,
        inset=EDGE_WIDTH / 2,
    )
    drop, indent = (8, 22) if corner else (0, 0)
    center = (MARGIN + SPLIT_BADGE + indent, top + SPLIT_HEADER / 2 + drop)
    pen.circle(center, SPLIT_BADGE, fill=CARD_FACE)
    pen.text(center, rank_label(card), rank_font(38), color, anchor="mm")

    left = center[0] + SPLIT_BADGE + 20
    room = CARD_WIDTH - MARGIN - left
    title = catalog.card_title(card)
    minutes = "1 TIME" if card.time == "1" else f"{card.time} TIME"
    tail = f"{card.index}  ·  {minutes}"
    if card.name != title:
        tail = f"{card.name.upper()}  ·  {tail}"
    title_face = fitted_bold_font(pen, title, room, max_size=52, min_size=30) or font(30, bold=True)
    tail_face = fitted_bold_font(pen, tail, room, max_size=26, min_size=18) or font(18, bold=True)
    pen.text((left, center[1] + 8), title, title_face, "#ffffff", anchor="ls")
    pen.text((left, center[1] + 40), tail, tail_face, "#ffffff", anchor="ls")


def draw_split_half(
    pen: Pen, catalog: ManeuverCatalog, card: DeckCard, top: float, bottom: float,
    corner: str = "",
) -> None:
    """One half of a split card between `top` and `bottom`: its header,
    then the rank's effect and the role interaction under it, both from
    the top of the space (the author, 2026-11-01: "align all text to
    the top")."""
    color = card_color(card)
    draw_split_header(pen, catalog, card, top, corner == "top")
    inner_left, inner_right = MARGIN, CARD_WIDTH - MARGIN
    width = inner_right - inner_left
    y = top + SPLIT_HEADER + 18
    # The bottom half ends in the card's rounded corners, which the
    # box's own corners must clear.
    room = bottom - y - (44 if corner == "bottom" else 16)

    heading = " OR ".join(ROLE_WORDS[role.value].upper() for role in card.roles)
    # The effect and the box share the room at one size: the largest
    # at which both fit, so the bonus is never set smaller than the
    # effect above it.
    box_chrome = 14 + BOX_PAD + BOX_HEADING + 12 + BOX_PAD - 10
    for size in range(34, 19, -1):
        effect_face = special_face = font(size)
        effect_lines = pen.wrapped(card.effect, effect_face, width)
        special_lines = pen.wrapped(card.special, special_face, width - BOX_PAD * 2)
        step = line_height(pen, effect_face)
        if (len(effect_lines) + len(special_lines)) * step + box_chrome <= room:
            break
    y = _draw_lines(pen, effect_lines, effect_face, inner_left, y, INK)
    box_top = y + 14
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


def draw_band_row(
    pen: Pen, catalog: ManeuverCatalog, card: DeckCard, top: float, height: float,
) -> None:
    """One row of the band: the half's rank, then what it beats, ties
    and loses to, each the other side's rank badge and maneuver in that
    side's colour, by rank as 1.0's row reads (`matchup_rank_groups`):
    every card of a rank reads the same row, as rank alone decides, and
    2.2 has no advanced cards to name beside it."""
    maneuver = catalog.definition(card.maneuver)
    is_offense = card.side == "offense"
    other = maneuver_deck.OTHER_SIDE[card.side]
    letter = "D" if is_offense else "O"
    other_color = SIDE_COLORS[other]
    groups = matchup_rank_groups(catalog, maneuver, is_offense)
    lead = 96
    left, right = FRAME + EDGE_WIDTH, CARD_WIDTH - FRAME - EDGE_WIDTH
    pen.text(
        (left + lead / 2, top + height / 2), rank_label(card), rank_font(34),
        card_color(card), anchor="mm",
    )
    column = (right - left - lead) / 3
    for index, (label, (rank, _)) in enumerate(zip(("BEATS", "TIES", "LOSES TO"), groups)):
        x0 = left + lead + column * index
        pen.line([(x0, top + 12), (x0, top + height - 12)], fill=BAND_RULE, width=2)
        cx = x0 + column / 2
        name = catalog.display_name(maneuver_deck.basic_on(catalog, other, rank))
        pen.text((cx, top + height / 2 - 16), label, font(17, bold=True), MUTED, anchor="mm")
        words = f"{letter}{rank} {name}"
        face = fitted_bold_font(pen, words, column - 14, max_size=26, min_size=16) or font(16, bold=True)
        pen.text((cx, top + height / 2 + 16), words, face, other_color, anchor="mm")


def draw_split_face(
    pen: Pen, catalog: ManeuverCatalog, offense: DeckCard, defense: DeckCard,
) -> None:
    """**A split card**: the offensive half on top, the band, the
    defensive half below (rules-2.2 1.1; the author's draft of
    2026-11-01). The edge is each half's colour, so a card fanned in a
    hand shows its offense along the top."""
    middle = FRAME + SPLIT_HALF + SPLIT_BAND / 2
    pen.rect_in_card((FRAME, FRAME, CARD_WIDTH - FRAME, middle), card_color(offense))
    pen.rect_in_card((FRAME, middle, CARD_WIDTH - FRAME, CARD_HEIGHT - FRAME), card_color(defense))
    pen.rect_in_card(
        (FRAME, FRAME, CARD_WIDTH - FRAME, CARD_HEIGHT - FRAME), CARD_FACE,
        inset=EDGE_WIDTH,
    )
    band_top = FRAME + SPLIT_HALF
    band_bottom = band_top + SPLIT_BAND
    draw_split_half(pen, catalog, offense, FRAME, band_top, "top")
    pen.rect_in_card((FRAME, band_top, CARD_WIDTH - FRAME, band_bottom), BAND_FILL, inset=EDGE_WIDTH)
    pen.line([(FRAME, band_top), (CARD_WIDTH - FRAME, band_top)], fill=BAND_RULE, width=2)
    pen.line([(FRAME, band_bottom), (CARD_WIDTH - FRAME, band_bottom)], fill=BAND_RULE, width=2)
    row = SPLIT_BAND / 2
    draw_band_row(pen, catalog, offense, band_top, row)
    pen.line([(FRAME + EDGE_WIDTH, band_top + row), (CARD_WIDTH - FRAME - EDGE_WIDTH, band_top + row)], fill=BAND_RULE, width=2)
    draw_band_row(pen, catalog, defense, band_top + row, row)
    draw_split_half(pen, catalog, defense, band_bottom, CARD_HEIGHT - FRAME, "bottom")


@lru_cache(maxsize=None)
def _face(catalog: ManeuverCatalog, card_id: str, bleed: bool) -> Image.Image:
    halves = maneuver_deck.faces(catalog, card_id)
    if not halves:
        raise KeyError(f"Unknown 2.2 card {card_id!r}.")
    pen = Pen((CARD_WIDTH, CARD_HEIGHT), CARD_FACE)
    draw_split_face(pen, catalog, *halves)
    return pen.finish(bleed, CARD_FACE)


def render_deck_card(
    catalog: ManeuverCatalog, card_id: str, bleed: bool = False,
) -> Image.Image:
    """One 2.2 card's face at the printed size, drawn once and kept
    (`draw_split_face`)."""
    return _face(catalog, card_id, bleed)


# -- A coach's hand ----------------------------------------------------

#: A hand is three cards, so each is drawn larger than the five of a
#: 2.1 hand were.
HAND_CARD_WIDTH = 480
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
    **A 2.2 coach's hand**, for their eyes alone: the three cards in one
    row under a heading naming the side being played, by the rank of
    the half played on it (`maneuver_deck.hand_order`). `players` is
    unused, kept so the cog's call reads as before.
    """
    order = maneuver_deck.hand_order(catalog, side)
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
CHIP_GAP = 4
PILE_GAP = 20


@lru_cache(maxsize=None)
def discard_chip(catalog: ManeuverCatalog, card_id: str) -> Image.Image:
    """
    One discarded card as a chip, in the face's colours -- what tells
    one card from another in a pile read for what has gone (the author,
    2026-10-18): its two halves as two rows, offense in red over
    defense in navy, each with its badge, index and label. A card the
    catalog does not have is one grey row with its id.
    """
    halves = maneuver_deck.faces(catalog, card_id)
    row = CHIP_HEIGHT * 0.66
    rows = halves or (None,)
    height = round(row * len(rows))
    pen = Pen((CHIP_WIDTH, height), CARD_FACE)
    for index, half in enumerate(rows):
        top = index * row
        color = MUTED if half is None else SIDE_COLORS[half.side]
        pen.rect((0, top, CHIP_WIDTH, top + row), fill=color)
        badge = row / 2 - 4
        center = (8 + badge, top + row / 2)
        pen.circle(center, badge, fill=CARD_FACE)
        if half is not None:
            pen.text(center, rank_label(half), rank_font(15), color, anchor="mm")
        left = center[0] + badge + 10
        label = card_id if half is None else maneuver_deck.half_words(catalog, half)
        face = fitted_bold_font(pen, label, CHIP_WIDTH - left - 10, max_size=21, min_size=13) or font(13, bold=True)
        pen.text((left, top + row / 2), label, face, "#ffffff", anchor="lm")
    chip = pen.image.resize((CHIP_WIDTH, height), Image.Resampling.LANCZOS).convert("RGBA")
    mask = Image.new("L", pen.image.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, pen.image.width - 1, pen.image.height - 1),
        radius=round(CHIP_RADIUS * pen.image.width / CHIP_WIDTH), fill=255,
    )
    chip.putalpha(mask.resize((CHIP_WIDTH, height), Image.Resampling.LANCZOS))
    return chip


def render_discard_piles(
    catalog: ManeuverCatalog,
    players: PlayerCatalog,
    piles: Sequence[tuple[str, str, Sequence[str]]],
) -> BytesIO:
    """
    **The 2.2 discard piles, face up**, for the public maneuver prompt:
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
        height = sum(chip.height + CHIP_GAP for chip in chips) - CHIP_GAP if chips else 30
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
            y += chip.height + CHIP_GAP
        x += width + PILE_GAP
    buffer = BytesIO()
    canvas.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer
