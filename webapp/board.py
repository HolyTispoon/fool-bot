"""
The board, as the page draws it: the position read off the match the
way `render_match_image` reads it, handed over as data the page lays
out in HTML.

**This is the web frontend's picture of the position.** The page
draws it natively rather than showing the PNG, so that a phone gets a
board it can read rather than a 3300-pixel picture scaled to a
thumbnail, and so that the things on it can be the answers to a
prompt. Since the redesign it is no longer the bot's layout
(docs/design/board-image.md, "The web page's board"); what it shares
with the PNG is every value.

**Nothing here is a rule.** Every value the PNG works out from the
rules is asked of the same function the PNG asks: the space codes
(`render.space_code`, which is what carries the flat-numbering
experiment), the zone labels, the range bands
(`render.shooting_range_bands`, over `BoardState.is_in_shooting_range`),
which players draw a Cyborg's marks (`RulesEngine.cyborg_condition_ids`)
and whether meeples carry a species icon
(`RulesEngine.species_abilities_apply`) -- and what the page adds, the
kickoff space (`kickoff_space_for`) and whether the side on the ball
may shoot from where it stands (`can_attempt_score`). What is left is reading
state -- who stands where, who is tired -- which is what a picture of
a position is.
"""

from __future__ import annotations

from typing import Optional

from d12ball.components import MatchPeriod, MatchState, TeamSide, Zone
from d12ball.engine import RulesEngine
from d12ball.formatting import role_initials
from d12ball.game import D12BallGame, team_display_name
from d12ball.render import (
    BALL_RADIUS,
    FONT_SMALL,
    FONT_TOKEN_ROLE,
    FONT_TOKEN_SOLO,
    card_profile,
    MEEPLE_ICON_CENTER,
    MEEPLE_OUTLINE_WIDTH,
    MEEPLE_PATH,
    MEEPLE_ROLE_CENTER,
    MEEPLE_SIZE,
    MEEPLE_SOLO_CENTER,
    MEEPLE_SPECIES_ICON_SIZE,
    TEAM_COLORS,
    ZONE_COLORS,
    high_contrast_ink,
    meeple_outline,
    shooting_range_bands,
    space_code,
    zone_labels,
)

#: The field left to right, which is the order the bot draws it in.
ZONES = (Zone.HOME_GOAL, Zone.MIDFIELD, Zone.VISITORS_GOAL)

#: How wide the page draws a meeple on the field, in CSS pixels at the
#: stage's own width. Every fan step below is measured against it.
FAN_MEEPLE_WIDTH = 50

#: How far each piece of a fan stands from the one behind it, across
#: and down, by how many of one team share the space -- the design's
#: numbers (2026-09-26), chosen so a four-fan stays inside its space.
FAN_STEPS = {1: (0, 0), 2: (30, 22), 3: (22, 16), 4: (17, 12)}

#: A fan of more than four spreads no wider than a four-fan does.
FAN_SPREAD = (3 * FAN_STEPS[4][0], 3 * FAN_STEPS[4][1])


def fan_step(count: int) -> tuple[float, float]:
    """The step between two pieces of a fan of `count`."""
    if count in FAN_STEPS:
        return FAN_STEPS[count]
    return (FAN_SPREAD[0] / (count - 1), FAN_SPREAD[1] / (count - 1))


def fan(pieces: list[dict], side: str, holder: Optional[str]) -> dict:
    """
    One team's meeples on one space, as the page overlaps them.

    `pieces` come back to front, each with its `x` and `y` in the fan's
    box (pixels at `FAN_MEEPLE_WIDTH`, from the box's top left). A home
    fan runs from the bottom left at the back to the top right at the
    front, and a visiting fan from the top right at the back to the
    bottom left at the front, so each leans toward the goal it attacks.
    `holder`, when it is one of them, is moved to the front, which is
    where the ball is drawn; the rest keep the board's order. `names`
    is the same pieces front first: one line each under the fan.
    """
    ordered = [one for one in pieces if one["id"] != holder]
    ordered += [one for one in pieces if one["id"] == holder]
    count = len(ordered)
    step_x, step_y = fan_step(count) if count else (0, 0)
    last = count - 1
    placed = []
    for index, one in enumerate(ordered):
        across, down = (
            (index, last - index) if side == "home" else (last - index, index)
        )
        placed.append(
            {**one, "x": across * step_x, "y": down * step_y, "front": index == last}
        )
    return {
        "pieces": placed,
        "names": [one["id"] for one in reversed(placed)],
        "step": [step_x, step_y],
        "width": last * step_x + FAN_MEEPLE_WIDTH if count else 0,
    }


def period_name(match: MatchState) -> str:
    """The half, as the board's title and jumbotron word it."""
    return (
        "First Half"
        if match.scoreboard.period == MatchPeriod.FIRST_HALF
        else "Second Half"
    )


def meeple_geometry() -> dict:
    """
    How the bot draws a meeple, in the numbers `render.py` draws it
    with, for the page to draw the same piece: the path and its box in
    the path's own units, where the species icon and the role letters
    sit on it (`MEEPLE_ICON_CENTER`, `MEEPLE_ROLE_CENTER`, and
    `MEEPLE_SOLO_CENTER` for the letters alone), and every size as a
    share of the piece's width -- the icon, the two sizes of letters,
    the outline, and the ball beside it, with the ball's label. The
    page picks how wide a meeple is; everything else follows from
    these, so the face cannot drift from `draw_meeple_face`.
    """
    outline = meeple_outline()
    xs = [x for x, _ in outline]
    ys = [y for _, y in outline]
    left, top = min(xs), min(ys)
    width, height = max(xs) - left, max(ys) - top
    units = width / MEEPLE_SIZE  # path units per pixel of a 76px meeple

    def down(path_y: float) -> float:
        return (path_y - top) / height

    return {
        "path": MEEPLE_PATH,
        "box": [left, top, width, height],
        "icon_center": down(MEEPLE_ICON_CENTER),
        "role_center": down(MEEPLE_ROLE_CENTER),
        "solo_center": down(MEEPLE_SOLO_CENTER),
        "icon_size": MEEPLE_SPECIES_ICON_SIZE / MEEPLE_SIZE,
        "role_font": FONT_TOKEN_ROLE.size / MEEPLE_SIZE,
        "solo_font": FONT_TOKEN_SOLO.size / MEEPLE_SIZE,
        "stroke": MEEPLE_OUTLINE_WIDTH * units,
        "ball": 2 * BALL_RADIUS / MEEPLE_SIZE,
        "ball_font": FONT_SMALL.size / (2 * BALL_RADIUS),
    }


def board_layout(
    engine: RulesEngine,
    game: D12BallGame,
    match: MatchState,
    *,
    card_url: str,
    goal_url: str,
) -> dict:
    """
    Everything the page needs to draw one position. `card_url` is the
    route a card's picture is served from, with `{card}` where the
    card id goes, and `goal_url` an end zone's, with `{side}` -- the
    server's to say, since a snapshot and the live board are drawn
    from the same game's cards. A card's URL carries the marks the
    match puts on it, since the picture is drawn with them.
    """
    board = match.board
    cyborgs = engine.cyborg_condition_ids(game, match)
    skills = engine.card_skills(game, match)
    catalog = engine.player_catalog
    home_ids = set(match.home.field_players)
    visiting_ids = set(match.visiting.field_players)

    def card(card_id: str) -> dict:
        player = catalog.player_by_id(card_id)
        profile = card_profile(catalog, player, skills)
        team = match.team_for_player(card_id)
        return {
            "id": card_id,
            "name": player.name,
            "role": role_initials(player),
            "offense": profile.offense,
            "defense": profile.defense,
            "colour": TEAM_COLORS[team],
            "image": card_url.format(card=card_id) + (
                f"?x={match.exhaustion.get(card_id, 0)}"
                f"&e={int(card_id in match.exhausted)}"
                f"&i={int(card_id in match.injured)}"
                f"&c={int(card_id in cyborgs)}"
                # The skills it prints, so a card whose numbers change
                # is a new address rather than a browser's old copy.
                f"&s={profile.offense}-{profile.defense}"
            ),
            "exhaustion": match.exhaustion.get(card_id, 0),
            "exhausted": card_id in match.exhausted,
            "injured": card_id in match.injured,
            "cyborg": card_id in cyborgs,
        }

    def meeple(card_id: str) -> dict:
        player = catalog.player_by_id(card_id)
        colour = TEAM_COLORS[match.team_for_player(card_id)]
        return {
            "id": card_id,
            "name": player.name,
            "role": role_initials(player),
            "colour": colour,
            "ink": high_contrast_ink(colour),
            "species": player.species,
            **badges(card_id),
        }

    def badges(card_id: str) -> dict:
        """
        The marks a piece carries, as the emoji the bot draws them
        with: the exhaustion token and its count off the bottom right,
        and the condition off the bottom left -- a Cyborg's own under
        its own words, the way `draw_card` picks them. Injured wins the
        slot, as it does on the card.
        """
        cyborg = card_id in cyborgs
        count = match.exhaustion.get(card_id, 0)
        if card_id in match.injured:
            condition = "damaged" if cyborg else "injured"
        elif card_id in match.exhausted:
            condition = "drained" if cyborg else "exhausted"
        else:
            condition = None
        return {
            "exhaustion": (
                {"count": count, "emoji": "exhaust_cyborg" if cyborg else "exhaust"}
                if count > 0
                else None
            ),
            "condition": condition,
        }

    labels = zone_labels(board.layout.board_size)
    band_sides = {1: "home", -1: "visiting", 0: None}
    kickoff = {match.kickoff_space_for(side) for side in TeamSide}
    ball_side = TeamSide(match.ball.possession).value
    # Who the ball is drawn on: the carrier the last resolution left it
    # with, or the player taking the turn -- whoever the match names.
    named = [
        one for one in (match.ball_carrier_id, match.active_player_id) if one
    ]
    spaces = []
    for zone in ZONES:
        for index, occupants in enumerate(board.spaces[zone]):
            has_ball = (
                match.ball.zone == zone and match.ball.space_index == index
            )
            lanes = {
                "visiting": [
                    meeple(one) for one in occupants if one in visiting_ids
                ],
                "home": [meeple(one) for one in occupants if one in home_ids],
            }
            holder = None
            if has_ball and lanes[ball_side]:
                on_space = [one["id"] for one in lanes[ball_side]]
                holder = next(
                    (one for one in named if one in on_space), on_space[-1],
                )
            spaces.append(
                {
                    "code": space_code(zone, index, board),
                    "zone": zone.value,
                    # The end zones in the colour of the side defending
                    # them, as the goal beyond them is.
                    "tint": _defender_colour(match, zone),
                    "kickoff": zone == Zone.MIDFIELD and index in kickoff,
                    **lanes,
                    "fans": {
                        side: fan(lanes[side], side, holder)
                        for side in ("visiting", "home")
                    },
                    "ball": (
                        {
                            "speed": match.ball.speed,
                            "side": ball_side,
                            "holder": holder,
                        }
                        if has_ball
                        else None
                    ),
                }
            )

    in_range = match.can_attempt_score()

    return {
        "jumbotron": {
            "home": _team(match.home.team),
            "visiting": _team(match.visiting.team),
            "score": {
                "home": match.scoreboard.home_score,
                "visiting": match.scoreboard.visiting_score,
            },
            "minute": f"{match.scoreboard.time:02d}",
            "period": period_name(match),
        },
        "zones": [
            {
                "zone": zone.value,
                "label": labels[zone],
                "fill": ZONE_COLORS[zone],
                "colour": _defender_colour(match, zone),
                "spaces": len(board.spaces[zone]),
                "home": [card(one) for one in match.home.zones.get(zone, [])],
                "visiting": [
                    card(one) for one in match.visiting.zones.get(zone, [])
                ],
            }
            for zone in ZONES
        ],
        "spaces": spaces,
        "goals": {
            # Each drawn by `draw_end_zone`, in the colour of the side
            # defending it.
            "home": goal_url.format(side="home"),
            "visiting": goal_url.format(side="visiting"),
        },
        "bands": [
            {
                "side": band_sides[side],
                "first": first,
                "last": last,
                "label": _band_label(side),
                "colour": (
                    TEAM_COLORS[match.setup_for_side(TeamSide(band_sides[side])).team]
                    if band_sides[side]
                    else None
                ),
                # Lit while the side on the ball stands where it may
                # shoot from -- the model's own answer, `can_attempt_score`.
                "lit": band_sides[side] == ball_side and in_range,
            }
            for side, first, last in shooting_range_bands(match)
        ],
        "team_boards": [
            {
                "side": setup.side.value,
                **_team(setup.team),
                "bench": [card(one) for one in setup.team_board.bench],
                "back_bench": [
                    card(one) for one in setup.team_board.back_bench
                ],
            }
            for setup in (match.home, match.visiting)
        ],
        "species_icons": engine.species_abilities_apply(game),
        "meeple": {**meeple_geometry(), "width": FAN_MEEPLE_WIDTH},
    }


def _defender_colour(match: MatchState, zone: Zone) -> Optional[str]:
    """The colour of the side whose goal an end zone is in front of."""
    if zone == Zone.HOME_GOAL:
        return TEAM_COLORS[match.home.team]
    if zone == Zone.VISITORS_GOAL:
        return TEAM_COLORS[match.visiting.team]
    return None


def _team(team) -> dict:
    return {
        "name": team_display_name(team),
        "colour": TEAM_COLORS[team],
        # What the team's emoji is filed under (`/emoji/team_<key>.png`).
        "key": team.value,
    }


def _band_label(side: int) -> str:
    """
    What a band says. A side's band is where that side shoots *from*,
    so home's sits on the visitors' half and points at the goal it
    attacks; the space in neither side's range is the kickoff space,
    the one true middle of an odd board (`is_in_shooting_range`).
    """
    if side == 1:
        return "HOME SHOOTS FROM HERE \u25b6"
    if side == -1:
        return "\u25c0 VISITORS SHOOT FROM HERE"
    return "KICKOFF"
