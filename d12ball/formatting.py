"""
Pure text formatting over D12 Ball's domain objects -- zone/space
codes, player and team names, AI opponent names -- with no Discord
dependency and no cog state. Moved out of cogs/d12ball_helpers.py so
d12ball/engine.py's RulesEngine can build prompt text without cogs
importing from d12ball, never the other way around: a helper that only
formats a Zone or a MatchState belongs down here, next to the things
it formats, and cogs/d12ball_helpers.py re-imports every name below
for the many call sites (and other cog-level helpers, like
format_role_bracket) that already read them from there.

What stayed behind in cogs/d12ball_helpers.py either needs live
Discord data (team_emojis, condition_emojis) or touches discord.py
directly -- format_role_bracket needs an emoji dict this module has no
business holding, which is the whole difference between the two files.
"""

from typing import Optional

from d12ball.components import MatchState, Zone
from d12ball.game import AIOpponent, D12BallGame, team_display_name


ROLE_INITIALS = {
    "fullback": "FB",
    "defender": "DD",
    "midfielder": "MF",
    "playmaker": "PM",
    "winger": "WG",
    "striker": "SK",
}

# Matches the H1/M1/V1-style space labels drawn on the board in render.py.
ZONE_LETTERS = {
    Zone.HOME_GOAL: "H",
    Zone.MIDFIELD: "M",
    Zone.VISITORS_GOAL: "V",
}

BENCH_DESTINATIONS = ("bench", "back_bench")

# The 9-space board is the only one whose three areas (H/M/V) are equal, which
# is what earns its outer two the more literal "Third" -- see "The field" in
# the living rules and the 2026-08-24 entry in the rules log. Midfield's name
# never changes, so it carries no entry here.
OUTER_ZONE_WORD_BY_BOARD_SIZE = {
    6: "Zone",
    7: "Zone",
    9: "Third",
}

AI_OPPONENT_NAMES = {
    AIOpponent.DINKY: "Dinky AI",
    AIOpponent.DECENT: "Decent AI",
}


def contest_noun(match: MatchState) -> str:
    """
    What to call the contest currently pending -- "high pass" or
    "loose ball".

    They share the machinery and nothing else. A loose ball is the
    ball sitting in a space the possessing side doesn't hold, and
    whoever wins it takes possession from wherever it lies. A High
    Pass is a completed pass to a player who is already standing
    there, defending the ball they just received; losing it is a
    turnover, winning it changes nothing. Calling one by the other's
    name in front of a coach who is deciding what to do misreads the
    position, so every message on the shared path asks for the noun
    rather than assuming.
    """
    return "high pass" if match.pending_loose_ball_is_high_pass else "loose ball"


def format_ai_name(ai_opponent: Optional[AIOpponent]) -> str:
    return AI_OPPONENT_NAMES[ai_opponent or AIOpponent.DINKY]


def zone_display_name(zone: Zone, board_size: int) -> str:
    """
    "Home Zone", "Midfield", "Visitors Third" -- whichever a board's own
    size calls the outer two areas. See the module-level comment on
    OUTER_ZONE_WORD_BY_BOARD_SIZE for why the 9-space board differs.
    """
    if zone is Zone.MIDFIELD:
        return "Midfield"
    side = "Home" if zone is Zone.HOME_GOAL else "Visitors"
    return f"{side} {OUTER_ZONE_WORD_BY_BOARD_SIZE[board_size]}"


def destination_display_name(destination: str, board_size: int) -> str:
    if destination in BENCH_DESTINATIONS:
        return destination.replace("_", " ").title()
    return zone_display_name(Zone(destination), board_size)


def format_team_side_label(setup) -> str:
    return f"{team_display_name(setup.team)} ({setup.side.value.title()})"


def space_label(zone: Zone, space_index: int) -> str:
    return f"{ZONE_LETTERS[zone]}{space_index + 1}"


def travel_space_label(zone: Zone, space_index: int, distance: int) -> str:
    """
    A destination with what reaching it costs -- "H1 (2 spaces)".

    A run back is charged a token a space, so the distance *is* the
    price, and a coach picking between the spaces of a zone is picking
    between prices. The number is on the button as well as in the list
    beside it, because the button is the thing being pressed.
    """
    unit = "space" if distance == 1 else "spaces"
    return f"{space_label(zone, space_index)} ({distance} {unit})"


def ball_space_label(match: MatchState) -> str:
    """Where the ball is standing, as a space code -- e.g. "M2"."""
    return space_label(match.ball.zone, match.ball.space_index)


def format_player(
    game: D12BallGame,
    player_number: Optional[int],
    mention: bool = False,
) -> str:
    if player_number == 1:
        if game.test_game:
            return "Player 1"
        if mention:
            return f"<@{game.player_1_id}>"
        return game.player_1_name or "Player 1"

    if player_number == 2:
        if game.test_game:
            return "Player 2"
        if game.player_2_id is None:
            return format_ai_name(game.ai_opponent)
        if mention:
            return f"<@{game.player_2_id}>"
        return game.player_2_name or "Player 2"

    return "Unknown player"


def format_player_with_team(
    game: D12BallGame,
    player_number: Optional[int],
    mention: bool = False,
) -> str:
    player = format_player(game, player_number, mention=mention)
    team = (
        game.player_1_team
        if player_number == 1
        else game.player_2_team
    )
    team_name = team_display_name(team) if team else "Unknown team"
    return f"{player} ({team_name})"
