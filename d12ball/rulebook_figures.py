"""
The illustrations for the Learn to Play book, drawn off the bot's own
renderer -- see "The two rulebooks" in docs/design/rulebooks.md.

Every board in a figure is a real `MatchState`, rendered by
`render.render_field_image` exactly as a coach in Discord sees it, and
then annotated: a band of arrows and numbered markers above the field,
and the numbered notes under it. Nothing here draws a space, a meeple
or the ball itself -- a figure that drew its own board could show a
position the game cannot reach, and would drift from the board the
moment `render.py` changed.

**The positions are set by hand, from the tutorial's script.** The
five-beat walkthrough (`walkthrough_figures`) reproduces the opening
`d12ball/tutorial.py` plays, one figure per beat, with each meeple
moved to where that beat's lesson text says it ends up. That is a
sketch's accuracy, not a proof: the plan in docs/rulebooks/plan.md
proposes capturing the final figures from the golden playthrough in
`tests/test_golden_transcript.py` instead, so a picture in the book can
never disagree with the game.

`scripts/build_rulebooks.py --figures` writes every figure to
`docs/rulebooks/figures/`, which is committed -- like `d12ball/data/`,
regenerated whole by the script and never edited by hand -- so the
outlines can show them on GitHub.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Callable, Optional

from PIL import Image, ImageDraw

from . import render
from .cards import FACE_COLOR, INK, PANEL_COLOR, render_maneuver_card
from .components import (
    MANEUVER_TIER_BASIC,
    MANEUVER_TIER_GAMBIT,
    MatchState,
    PlayerCatalog,
    PlayerRole,
    TeamSide,
    Zone,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
)
from .game import Formation, Team

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIGURES_DIR = PROJECT_ROOT / "docs" / "rulebooks" / "figures"

# The figures are written at this width. The field renders at 2180px,
# which is more than a page needs and more than a repository wants to
# carry fifteen of.
FIGURE_WIDTH = 1400

# The colours are the printed cards', so a figure sits on the same page
# as the rulebook text without a second palette -- see cards.py.
ACCENT = "#b8452b"
MARKER_FILL = "#14202b"
MARKER_INK = "#ffffff"
ARROW_WIDTH = 9

TITLE_BAND = 96
ANNOTATION_BAND = 240
NOTE_LINE_HEIGHT = 46
NOTE_MARGIN = 40

ZONE_LETTERS = {"H": Zone.HOME_GOAL, "M": Zone.MIDFIELD, "V": Zone.VISITORS_GOAL}


def parse_space(code: str) -> tuple[Zone, int]:
    """`M2` -> (Zone.MIDFIELD, 1): the codes the living rules use."""
    return ZONE_LETTERS[code[0].upper()], int(code[1:]) - 1


def standard_match(
    board_size: int = 7,
    home: Team = Team.PURPLE,
    visiting: Team = Team.TEAL,
) -> MatchState:
    """The position every game kicks off from: both sides in 2-2-2."""
    return MatchState.standard(
        catalog=load_player_catalog(),
        ruleset=load_basic_ruleset(),
        board_size=board_size,
        home_team=home,
        visiting_team=visiting,
        home_formation=Formation.TWO_TWO_TWO,
        visiting_formation=Formation.TWO_TWO_TWO,
    )


def fielded(
    match: MatchState,
    catalog: PlayerCatalog,
    role: PlayerRole,
    side: TeamSide = TeamSide.HOME,
) -> str:
    """The player the standard deal fields in `role` for that side."""
    players = render.player_index(catalog)
    setup = match.home if side == TeamSide.HOME else match.visiting
    for player_id in setup.field_players:
        if players[player_id].role == role:
            return player_id
    raise LookupError(f"No fielded {role.value} on {side.value}.")


def field_image(match: MatchState, catalog: PlayerCatalog) -> Image.Image:
    return Image.open(render.render_field_image(match, catalog)).convert("RGB")


def space_centre_x(match: MatchState, code: str) -> float:
    """
    Where a space's centre lands across the field crop, read off the
    same `zone_bounds` `draw_board` divides -- never a second guess at
    the geometry.
    """
    zone, index = parse_space(code)
    left, right = render.zone_bounds(match)[zone]
    width = (right - left) / len(match.board.spaces[zone])
    crop_left = render.BOARD_LEFT - render.FIELD_MARGIN
    return left + (index + 0.5) * width - crop_left


@dataclass
class Arrow:
    start: str
    end: str
    label: str = ""
    # Stacks arrows that would otherwise overlap: 0 is the lowest row.
    row: int = 0


@dataclass
class Marker:
    space: str
    number: int
    # Nudges a second marker on the same space sideways.
    offset: int = 0


@dataclass
class Sketch:
    """One annotated field: what is above it, and what is said under it."""

    title: Optional[str]
    match: MatchState
    arrows: list[Arrow] = field(default_factory=list)
    markers: list[Marker] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def render(self, catalog: PlayerCatalog) -> Image.Image:
        board = field_image(self.match, catalog)
        width = board.width
        note_font = render.load_font(34)
        note_lines: list[tuple[str, str]] = []
        for number, note in enumerate(self.notes, start=1):
            wrapped = wrap(note, note_font, width - 2 * NOTE_MARGIN - 70)
            note_lines.append((str(number), wrapped[0]))
            note_lines.extend(("", line) for line in wrapped[1:])
        notes_height = (
            NOTE_MARGIN + len(note_lines) * NOTE_LINE_HEIGHT + NOTE_MARGIN
            if note_lines else 0
        )

        title_band = TITLE_BAND if self.title else 0
        canvas = Image.new(
            "RGB",
            (width, title_band + ANNOTATION_BAND + board.height + notes_height),
            FACE_COLOR,
        )
        draw = ImageDraw.Draw(canvas)
        if self.title:
            draw_title(draw, self.title, width)
        band_top = title_band
        canvas.paste(board, (0, band_top + ANNOTATION_BAND))

        for arrow in self.arrows:
            y = band_top + ANNOTATION_BAND - 30 - arrow.row * 62
            x1 = space_centre_x(self.match, arrow.start)
            x2 = space_centre_x(self.match, arrow.end)
            draw_arrow(draw, x1, x2, y, arrow.label)
        for marker in self.markers:
            x = space_centre_x(self.match, marker.space) + marker.offset
            draw_marker(draw, x, band_top + 42, marker.number)

        y = band_top + ANNOTATION_BAND + board.height + NOTE_MARGIN
        for number, line in note_lines:
            if number:
                draw_marker(draw, NOTE_MARGIN + 24, y + 20, int(number), radius=22)
            draw.text((NOTE_MARGIN + 70, y), line, font=note_font, fill=INK)
            y += NOTE_LINE_HEIGHT
        return canvas


def wrap(text: str, font, max_width: int) -> list[str]:
    measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if current and measure.textlength(candidate, font=font) > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines or [""]


def draw_title(draw: ImageDraw.ImageDraw, title: str, width: int) -> None:
    font = render.load_font(52, bold=True)
    draw.rectangle((0, 0, width, TITLE_BAND), fill=PANEL_COLOR)
    draw.text((NOTE_MARGIN, 22), title, font=font, fill=INK)


def draw_marker(
    draw: ImageDraw.ImageDraw,
    x: float,
    y: float,
    number: int,
    radius: int = 30,
) -> None:
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=MARKER_FILL)
    font = render.load_font(int(radius * 1.2), bold=True)
    label = str(number)
    text_width = draw.textlength(label, font=font)
    draw.text(
        (x - text_width / 2, y - radius * 0.72), label, font=font, fill=MARKER_INK,
    )


def draw_arrow(
    draw: ImageDraw.ImageDraw,
    x1: float,
    x2: float,
    y: float,
    label: str,
) -> None:
    """A straight arrow along the band, pointing the way the move went."""
    direction = 1 if x2 >= x1 else -1
    head = 26
    draw.line((x1, y, x2 - direction * head * 0.6, y), fill=ACCENT, width=ARROW_WIDTH)
    draw.polygon(
        [(x2, y), (x2 - direction * head, y - head * 0.65), (x2 - direction * head, y + head * 0.65)],
        fill=ACCENT,
    )
    draw.ellipse((x1 - 12, y - 12, x1 + 12, y + 12), fill=ACCENT)
    if label:
        font = render.load_font(30, bold=True)
        text_width = draw.textlength(label, font=font)
        centre = (x1 + x2) / 2
        draw.text((centre - text_width / 2, y - 48), label, font=font, fill=ACCENT)


def scaled(image: Image.Image, width: int = FIGURE_WIDTH) -> Image.Image:
    if image.width <= width:
        return image
    height = round(image.height * width / image.width)
    return image.resize((width, height), Image.LANCZOS)


# --- The figures ----------------------------------------------------------


def kickoff_figure(catalog: PlayerCatalog) -> Image.Image:
    match = standard_match()
    sketch = Sketch(
        title="Figure 1 - The field at kickoff",
        match=match,
        markers=[Marker("H1", 1), Marker("M2", 2), Marker("V2", 3), Marker("M3", 4)],
        arrows=[
            Arrow("M1", "M3", "Home attacks this way", row=1),
        ],
        notes=[
            "Home Zone (H1-H2), Midfield (M1-M3) and Visitors Zone (V1-V2). "
            "Purple is home and attacks to the right; teal is the visitors and attacks to the left.",
            "The kickoff space, with the ball on it. Both sides start in 2-2-2: two players in each zone, "
            "and the ball at speed 1 in home's hands.",
            "A meeple stands for a player card. The letters are the role (SK = Striker, FB = Fullback, "
            "DD = Defender, MF = Midfielder, PM = Playmaker, WG = Winger). The card itself, on the team board, "
            "carries the two skills: offensive and defensive, which always total 7.",
            "The dashed edge under the field is shooting range: home may shoot from M3 onward, "
            "the visitors from M1 back. The middle space belongs to neither.",
        ],
    )
    return scaled(sketch.render(catalog))


def walkthrough_positions(catalog: PlayerCatalog) -> list[Sketch]:
    """
    The tutorial's five beats, one position after each -- the same play
    `d12ball/tutorial.py` scripts, with the meeples moved by hand to
    where each lesson says they end up.
    """
    match = standard_match()
    home_pm = fielded(match, catalog, PlayerRole.PLAYMAKER)
    home_st = fielded(match, catalog, PlayerRole.STRIKER)
    away_mf = fielded(match, catalog, PlayerRole.MIDFIELDER, TeamSide.VISITING)
    sketches: list[Sketch] = []

    # Beat 1: Dribble Advance beats Deflect; the Playmaker carries the
    # ball two spaces, M2 -> V1.
    match.move_meeple(home_pm, *parse_space("V1"))
    match.set_ball_space(*parse_space("V1"))
    match.set_ball_carrier(home_pm)
    match.ball.speed = 3
    sketches.append(Sketch(
        title="Figure 5 - Beat 1: Dribble Advance beats Deflect",
        match=MatchState.from_dict(match.to_dict(), load_basic_ruleset()),
        arrows=[Arrow("M2", "V1", "Dribble Advance, 2 spaces")],
        markers=[Marker("V1", 1)],
        notes=[
            "Home played Dribble Advance and the visitors played Deflect. Dribble Advance beats Deflect on rank "
            "alone, so nothing was rolled. The Playmaker carried the ball from M2 to V1 - two spaces, "
            "the Playmaker's own ability - and set its speed.",
            "V1 is inside home's shooting range, so next turn a shot would be offered.",
        ],
    ))

    # Beat 2: Low Pass ties Deflect, the visitors win the skill test,
    # the Deflect knocks the ball back to M3 onto their Midfielder.
    # Home's Playmaker runs back to M2.
    match.set_ball_space(*parse_space("M3"))
    match.set_possession(TeamSide.VISITING)
    match.set_ball_carrier(away_mf)
    match.ball.speed = 1
    match.move_meeple(home_pm, *parse_space("M2"))
    sketches.append(Sketch(
        title="Figure 6 - Beat 2: a tie, a skill test, and a Deflect",
        match=MatchState.from_dict(match.to_dict(), load_basic_ruleset()),
        arrows=[
            Arrow("V1", "M3", "Deflect: ball back 1"),
            Arrow("V1", "M2", "Run back, 1 token", row=1),
        ],
        markers=[Marker("M3", 1), Marker("M2", 2)],
        notes=[
            "Low Pass and Deflect are both rank 1, so they tie and go to a skill test: d12 + offensive skill "
            "against d12 + defensive skill, and a token to each. The visitors won it, and their Deflect knocked "
            "the ball back one space to M3 - where their Midfielder was already standing. A ball that lands on "
            "one side's player is simply theirs: no roll, and never loose.",
            "That is a turnover, so everybody outside their own zone runs back. Home's Playmaker walks from V1 "
            "to M2 and pays one exhaustion token for the space.",
        ],
    ))

    # Beat 3: home sends the Playmaker M2 -> M3 to challenge; Pressure
    # beats Dribble Advance; handler and ball go back to V1 and the
    # challenger follows onto it.
    match.move_meeple(away_mf, *parse_space("V1"))
    match.set_ball_space(*parse_space("V1"))
    match.set_ball_carrier(away_mf)
    match.move_meeple(home_pm, *parse_space("V1"))
    sketches.append(Sketch(
        title="Figure 7 - Beat 3: a challenger is sent; Pressure wins",
        match=MatchState.from_dict(match.to_dict(), load_basic_ruleset()),
        arrows=[
            Arrow("M2", "M3", "Sent to challenge, 1 token"),
            Arrow("M3", "V1", "Pressure: handler and ball back 1", row=1),
        ],
        markers=[Marker("V1", 1)],
        notes=[
            "Nobody of home's was standing on the ball at M3, so home sent the nearest player to it - the "
            "Playmaker from M2, one token for the one space. The visitors played Dribble Advance and home "
            "played Pressure, which beats it: the handler and the ball are shoved back one space to V1, "
            "and the challenger moves forward onto them. Possession does not change.",
        ],
    ))

    # Beat 4: Steal beats Low Pass. Possession flips, speed resets, the
    # stealer and the ball go back 1 for home (to M3), then the stealer
    # sets the speed up to their defensive skill (3 -> speed 4).
    match.move_meeple(home_pm, *parse_space("M3"))
    match.set_ball_space(*parse_space("M3"))
    match.set_possession(TeamSide.HOME)
    match.set_ball_carrier(home_pm)
    match.ball.speed = 4
    match.move_meeple(away_mf, *parse_space("M3"))
    sketches.append(Sketch(
        title="Figure 8 - Beat 4: Steal beats Low Pass, and everyone runs back",
        match=MatchState.from_dict(match.to_dict(), load_basic_ruleset()),
        arrows=[
            Arrow("V1", "M3", "Steal: ball and stealer back 1"),
            Arrow("V1", "M3", "Visitors' Midfielder runs back, 2 tokens", row=1),
        ],
        markers=[Marker("M3", 1)],
        notes=[
            "The visitors played Low Pass and home played Steal, which beats it. Possession flips and the "
            "ball's speed resets to 1; the stealer carries it one space back toward their own goal, to M3. "
            "Then everyone outside their own zone runs back - the visitors' Midfielder to M3, two tokens - "
            "and the stealer sets the ball's speed by up to their defensive skill: 1 + 3 = 4, worth +2 on a shot.",
        ],
    ))

    # Beat 5: High Pass of 2 from M3 lands on V2, the Striker, with the
    # visitors' Fullback on the same space.
    match.set_ball_space(*parse_space("V2"))
    match.set_ball_carrier(home_st)
    sketches.append(Sketch(
        title="Figure 9 - Beat 5: a 2-space High Pass sets up the shot",
        match=MatchState.from_dict(match.to_dict(), load_basic_ruleset()),
        arrows=[Arrow("M3", "V2", "High Pass, 2 spaces")],
        markers=[Marker("V2", 1)],
        notes=[
            "High Pass beats the visitors' Steal. A pass of exactly 2 spaces is caught cleanly, and a catch "
            "inside shooting range is a scoring opportunity: the Striker shoots at once, out of turn. "
            "Attack: d12 + 6 (skill) + 3 (Striker off a set-up) + 2 (ball speed 4). Defense: d12 + 6, "
            "the Fullback standing on the ball adding their whole defensive skill. Equal totals score.",
        ],
    ))
    return sketches


def walkthrough_figures(catalog: PlayerCatalog) -> list[Image.Image]:
    return [scaled(sketch.render(catalog)) for sketch in walkthrough_positions(catalog)]


def score_attempt_figure(catalog: PlayerCatalog) -> Image.Image:
    """
    Beat 4's position read as a shot: one defender on the ball, two
    beyond it, one behind it.
    """
    match = standard_match()
    home_pm = fielded(match, catalog, PlayerRole.PLAYMAKER)
    away_mf = fielded(match, catalog, PlayerRole.MIDFIELDER, TeamSide.VISITING)
    match.move_meeple(home_pm, *parse_space("M3"))
    match.move_meeple(away_mf, *parse_space("M3"))
    match.set_ball_space(*parse_space("M3"))
    match.set_ball_carrier(home_pm)
    match.ball.speed = 4
    sketch = Sketch(
        title="Figure 10 - What a shot is up against",
        match=match,
        arrows=[Arrow("M3", "V2", "Shot at the visitors' goal")],
        markers=[Marker("M3", 1), Marker("V1", 2), Marker("V2", 2, offset=0), Marker("M2", 3)],
        notes=[
            "On the ball: the visitors' Midfielder adds their whole defensive skill, 4.",
            "Between the ball and the goal: the Defender on V1 adds half of 5, rounded up to 3, and the "
            "Fullback on V2 adds half of 6, which is 3. Halving is per player, so the two add 6 together.",
            "Behind the ball: the Playmaker on M2 adds nothing. The attack is d12 + 4 (skill) + 2 (speed 4) "
            "against d12 + 10, and equal totals score - so this is a shot to think twice about.",
        ],
    )
    return scaled(sketch.render(catalog))


def ball_at_rest_figures(catalog: PlayerCatalog) -> Image.Image:
    """Three landings of the same Deflect, stacked: nobody, one side, both."""
    panels: list[Image.Image] = []
    cases = [
        ("Nobody there: the ball is loose. Each side may send a player after it, or send nobody.", "M1", None, None),
        ("One side there: the ball is simply theirs. No roll, and the other side may not send anybody.", "M1", TeamSide.VISITING, None),
        ("Both sides there: the players already standing there roll for it, and nobody else may be sent.", "M1", TeamSide.VISITING, TeamSide.HOME),
    ]
    for note, landing, first, second in cases:
        match = standard_match()
        home_mf = fielded(match, catalog, PlayerRole.MIDFIELDER)
        home_pm = fielded(match, catalog, PlayerRole.PLAYMAKER)
        away_pm = fielded(match, catalog, PlayerRole.PLAYMAKER, TeamSide.VISITING)
        away_st = fielded(match, catalog, PlayerRole.STRIKER, TeamSide.VISITING)
        # The Deflect: home's Playmaker had the ball on M2 with the
        # visitors' Playmaker challenging; it goes back 1 to M1. Home's
        # Midfielder starts on M1, so they are moved off it to make the
        # empty and one-side cases.
        match.move_meeple(home_mf, *parse_space("H2"))
        if first is not None:
            match.move_meeple(away_st, *parse_space(landing))
        if second is not None:
            match.move_meeple(home_mf, *parse_space(landing))
        match.set_ball_space(*parse_space(landing))
        match.clear_ball_carrier()
        sketch = Sketch(
            title=None,
            match=match,
            arrows=[Arrow("M2", "M1", "Deflect: ball back 1")],
            markers=[Marker("M1", 1)],
            notes=[note],
        )
        panels.append(sketch.render(catalog))
    width = max(panel.width for panel in panels)
    canvas = Image.new("RGB", (width, TITLE_BAND + sum(p.height for p in panels)), FACE_COLOR)
    draw_title(ImageDraw.Draw(canvas), "Figure 11 - Where the ball comes to rest", width)
    y = TITLE_BAND
    for panel in panels:
        canvas.paste(panel, (0, y))
        y += panel.height
    return scaled(canvas)


def cycle_figure(tier: str = MANEUVER_TIER_BASIC) -> Image.Image:
    image = Image.open(
        render.render_maneuver_reference_image(load_maneuver_catalog(), tier=tier)
    ).convert("RGB")
    return scaled(image)


def hand_figure(tier: str = MANEUVER_TIER_BASIC) -> Image.Image:
    """The three offense cards over the three defense cards."""
    catalog = load_maneuver_catalog()
    players = load_player_catalog()
    rows = []
    for side, is_offense in (("offense", True), ("defense", False)):
        faces = [
            render_maneuver_card(catalog, players, maneuver, is_offense, bleed=False)
            for maneuver in catalog.for_tier(side, tier)
        ]
        rows.append(faces)
    gap = 40
    card_w, card_h = rows[0][0].size
    columns = max(len(row) for row in rows)
    canvas = Image.new(
        "RGB",
        (columns * card_w + (columns + 1) * gap, 2 * card_h + 3 * gap),
        FACE_COLOR,
    )
    for r, row in enumerate(rows):
        for c, face in enumerate(row):
            canvas.paste(face, (gap + c * (card_w + gap), gap + r * (card_h + gap)))
    return scaled(canvas)


def turn_figure() -> Image.Image:
    """The turn as six boxes, left to right, and the arrow back round."""
    steps = [
        "1. Choose\nthe handler",
        "2. Choose the action:\nshoot, maneuver\nor time out",
        "3. Resolve it",
        "4. Settle a ball\nnobody holds",
        "5. Turnover?\nSteal: run back.\nNew play: reset.",
        "6. Advance\nthe clock",
    ]
    box_w, box_h, gap = 360, 220, 40
    width = len(steps) * box_w + (len(steps) + 1) * gap
    canvas = Image.new("RGB", (width, TITLE_BAND + box_h + 3 * gap + 60), FACE_COLOR)
    draw = ImageDraw.Draw(canvas)
    draw_title(draw, "Figure 4 - One turn, in order", width)
    font = render.load_font(28, bold=True)
    top = TITLE_BAND + gap
    for index, text in enumerate(steps):
        left = gap + index * (box_w + gap)
        draw.rounded_rectangle(
            (left, top, left + box_w, top + box_h), radius=24, outline=INK, width=5, fill="#ffffff",
        )
        lines = text.split("\n")
        y = top + (box_h - len(lines) * 40) / 2
        for line in lines:
            w = draw.textlength(line, font=font)
            draw.text((left + (box_w - w) / 2, y), line, font=font, fill=INK)
            y += 40
        if index < len(steps) - 1:
            draw_arrow(draw, left + box_w + 4, left + box_w + gap - 4, top + box_h / 2, "")
    y = top + box_h + gap
    caption = "Whoever has the ball when step 6 is done takes the next turn."
    cap_font = render.load_font(34)
    draw.text((gap, y), caption, font=cap_font, fill=ACCENT)
    return scaled(canvas)


def coaching_figure(catalog: PlayerCatalog) -> Image.Image:
    match = standard_match()
    image = Image.open(
        render.render_coaching_image(match, catalog, TeamSide.HOME, "Coaching Choice - Home")
    ).convert("RGB")
    return scaled(image)


def speed_figure() -> Image.Image:
    """The ball's twelve faces and what each is worth to a shot."""
    cell, gap = 100, 12
    width = 12 * cell + 13 * gap + 2 * NOTE_MARGIN + 220
    canvas = Image.new("RGB", (width, TITLE_BAND + 2 * cell + 4 * gap + 130), FACE_COLOR)
    draw = ImageDraw.Draw(canvas)
    draw_title(draw, "Figure 13 - Ball speed and its modifier", width)
    label_font = render.load_font(30, bold=True)
    cell_font = render.load_font(40, bold=True)
    top = TITLE_BAND + 2 * gap
    left0 = NOTE_MARGIN + 220
    draw.text((NOTE_MARGIN, top + 30), "Speed", font=label_font, fill=INK)
    draw.text((NOTE_MARGIN, top + cell + gap + 30), "Modifier", font=label_font, fill=INK)
    for speed in range(1, 13):
        left = left0 + (speed - 1) * (cell + gap)
        draw.rounded_rectangle((left, top, left + cell, top + cell), radius=16, fill="#ffffff", outline=INK, width=4)
        text = str(speed)
        draw.text((left + (cell - draw.textlength(text, font=cell_font)) / 2, top + 24), text, font=cell_font, fill=INK)
        modifier = speed // 2
        y = top + cell + gap
        draw.rounded_rectangle((left, y, left + cell, y + cell), radius=16, fill=PANEL_COLOR, outline=INK, width=4)
        text = f"+{modifier}" if modifier else "0"
        draw.text((left + (cell - draw.textlength(text, font=cell_font)) / 2, y + 24), text, font=cell_font, fill=ACCENT)
    caption = ("The modifier is half the speed, rounded down. It is added to a score attempt, "
               "to a Steal's skill test, and to a High Pass contest - and every turnover resets the speed to 1.")
    cap_font = render.load_font(30)
    y = top + 2 * cell + 2 * gap + 20
    for line in wrap(caption, cap_font, width - 2 * NOTE_MARGIN):
        draw.text((NOTE_MARGIN, y), line, font=cap_font, fill=INK)
        y += 40
    return scaled(canvas)


def species_figure() -> Image.Image:
    """The four species icons, one line each, for the appendix."""
    entries = [
        ("fire_demon", render.TEAM_COLORS[Team.FIRE_DEMONS], "Fire Demon - Volatile", "A natural 6 or 7 on any d12 ignites: roll again and add it (5-12) or subtract it (1-4)."),
        ("cyborg", render.TEAM_COLORS[Team.CYBORGS], "Cyborg - Lithium Powered", "Tokens are drain, Drained at 7. Overdrive: 3 drain for +5 before a roll. Charge-up: -1 drain for standing still in a run back."),
        ("telekinetic", render.TEAM_COLORS[Team.TELEKINETICS], "Telekinetic - Mind Pull", "The opponent's ball crossing your space: 1 token, roll a d12, 11-12 pulls it in. Your own ball: take it over for free (Smooth)."),
        ("ooze", render.TEAM_COLORS[Team.OOZES], "Ooze - Slimey", "Merge: an Ooze on the ball who is not rolling adds their skill to their side. Spreadable: counts as 0 toward occupancy."),
    ]
    icon = 160
    row_h = icon + 50
    width = 1800
    canvas = Image.new("RGB", (width, TITLE_BAND + len(entries) * row_h + 40), FACE_COLOR)
    draw = ImageDraw.Draw(canvas)
    draw_title(draw, "Figure 15 - The four species (advanced mode)", width)
    name_font = render.load_font(38, bold=True)
    text_font = render.load_font(30)
    y = TITLE_BAND + 30
    for species, colour, name, text in entries:
        art = render.species_icon(species, colour, icon)
        if art is not None:
            canvas.paste(art.convert("RGB"), (NOTE_MARGIN, y), art if art.mode == "RGBA" else None)
        draw.text((NOTE_MARGIN + icon + 40, y), name, font=name_font, fill=INK)
        line_y = y + 56
        for line in wrap(text, text_font, width - NOTE_MARGIN * 2 - icon - 40):
            draw.text((NOTE_MARGIN + icon + 40, line_y), line, font=text_font, fill=INK)
            line_y += 38
        y += row_h
    return scaled(canvas)


def both_boards_figure(catalog: PlayerCatalog) -> Image.Image:
    """The 7- and 9-space boards at kickoff, stacked, for the Charter's Appendix C."""
    panels = [field_image(standard_match(size), catalog) for size in (7, 9)]
    width = max(panel.width for panel in panels)
    gap = 30
    canvas = Image.new("RGB", (width, sum(p.height for p in panels) + gap * (len(panels) - 1)), FACE_COLOR)
    y = 0
    for panel in panels:
        canvas.paste(panel, ((width - panel.width) // 2, y))
        y += panel.height + gap
    return scaled(canvas)


FigureBuilder = Callable[[PlayerCatalog], Image.Image]


def walkthrough_figure(beat: int) -> FigureBuilder:
    """One beat of the walkthrough, 1 to 5, as a builder of its own."""
    return lambda catalog: scaled(walkthrough_positions(catalog)[beat - 1].render(catalog))


# Every figure by the file stem it is written under. The outlines
# reference these names, and a test holds the committed files to them.
FIGURES: dict[str, FigureBuilder] = {
    "fig-01-the-field": kickoff_figure,
    "fig-02-the-cycle": lambda catalog: cycle_figure(MANEUVER_TIER_BASIC),
    "fig-03-the-six-cards": lambda catalog: hand_figure(MANEUVER_TIER_BASIC),
    "fig-04-one-turn": lambda catalog: turn_figure(),
    "fig-05-beat-1": walkthrough_figure(1),
    "fig-06-beat-2": walkthrough_figure(2),
    "fig-07-beat-3": walkthrough_figure(3),
    "fig-08-beat-4": walkthrough_figure(4),
    "fig-09-beat-5": walkthrough_figure(5),
    "fig-10-the-shot": score_attempt_figure,
    "fig-11-where-the-ball-lands": ball_at_rest_figures,
    "fig-12-coaching-choice": coaching_figure,
    "fig-13-ball-speed": lambda catalog: speed_figure(),
    "fig-14-the-gambits": lambda catalog: cycle_figure(MANEUVER_TIER_GAMBIT),
    "fig-15-the-species": lambda catalog: species_figure(),
    "fig-16-the-boards": both_boards_figure,
}


def all_figures(catalog: Optional[PlayerCatalog] = None) -> dict[str, Image.Image]:
    """Every figure rendered, by the file stem it is written under."""
    catalog = catalog or load_player_catalog()
    return {stem: build(catalog) for stem, build in FIGURES.items()}


def write_figures(out_dir: Path = FIGURES_DIR) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for stem, image in all_figures().items():
        path = out_dir / f"{stem}.png"
        image.save(path, "PNG", optimize=True)
        written.append(path)
    return written
