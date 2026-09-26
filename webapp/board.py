"""
The board, as the page draws it: the position read off the match the
way `render_match_image` reads it, handed over as data the page lays
out in HTML.

**This is the web frontend's picture of the position, and its layout
is the bot's.** The jumbotron over the field; the visitors' cards
above each zone and the home side's below; the spaces with the
visitors' meeples in the upper row and the home side's in the lower,
the ball beside whoever has it; the two shooting-range bands under
the field; the two team boards at the foot, home on the left. A coach
who has played in a channel should find everything where the pinned
board put it (docs/design/board-image.md). The page draws it natively
rather than showing the PNG so that the cards are cards -- each one
the model's own card image, which opens full size on a click -- and so
that a phone gets a board it can read rather than a 3300-pixel
picture scaled to a thumbnail.

**Nothing here is a rule.** Every value the PNG works out from the
rules is asked of the same function the PNG asks: the space codes
(`render.space_code`, which is what carries the flat-numbering
experiment), the zone labels, the range bands
(`render.shooting_range_bands`, over `BoardState.is_in_shooting_range`),
which players draw a Cyborg's marks (`RulesEngine.cyborg_condition_ids`)
and whether meeples carry a species icon
(`RulesEngine.species_abilities_apply`). What is left is reading
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
        }

    labels = zone_labels(board.layout.board_size)
    spaces = []
    for zone in ZONES:
        for index, occupants in enumerate(board.spaces[zone]):
            has_ball = (
                match.ball.zone == zone and match.ball.space_index == index
            )
            spaces.append(
                {
                    "code": space_code(zone, index, board),
                    "zone": zone.value,
                    "visiting": [
                        meeple(one) for one in occupants if one in visiting_ids
                    ],
                    "home": [
                        meeple(one) for one in occupants if one in home_ids
                    ],
                    "ball": (
                        {
                            "speed": match.ball.speed,
                            "side": TeamSide(match.ball.possession).value,
                        }
                        if has_ball
                        else None
                    ),
                }
            )

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
                "side": {1: "home", -1: "visiting", 0: None}[side],
                "first": first,
                "last": last,
                "label": _band_label(side, labels),
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
        "meeple": meeple_geometry(),
    }


def _team(team) -> dict:
    return {
        "name": team_display_name(team),
        "colour": TEAM_COLORS[team],
        # What the team's emoji is filed under (`/emoji/team_<key>.png`).
        "key": team.value,
    }


def _band_label(side: int, labels: dict) -> Optional[str]:
    """
    What a band says, as `draw_shooting_range_band` words it: a side's
    band is named for the zone it shoots *from*, so home's sits on the
    visitors' half under the home zone's name.
    """
    if side == 1:
        return f"{labels[Zone.HOME_GOAL]} - SHOOTING RANGE"
    if side == -1:
        return f"{labels[Zone.VISITORS_GOAL]} - SHOOTING RANGE"
    return None
