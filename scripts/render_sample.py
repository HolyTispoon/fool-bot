#!/usr/bin/env python3
"""Render a D12 Ball board image to a file, without running the bot.

Renders either a fresh standard match:

    python3 scripts/render_sample.py --home purple --visiting teal

or a real saved game, so a board someone reported a problem with can be
reproduced exactly:

    python3 scripts/render_sample.py --list-games
    python3 scripts/render_sample.py --game <game_id>
"""
import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from d12ball.components import (  # noqa: E402
    MatchState,
    load_basic_ruleset,
    load_player_catalog,
)
from d12ball.game import VALID_BOARD_SIZES, Formation, Team  # noqa: E402
from d12ball.render import render_match_image  # noqa: E402
from gamesaves.d12ball.storage import load_games  # noqa: E402


DEFAULT_OUTPUT = PROJECT_ROOT / "board.png"


def period_label(match: MatchState) -> str:
    return (
        "First Half"
        if match.scoreboard.period.value == "first_half"
        else "Second Half"
    )


def list_games() -> int:
    games = load_games()
    if not games:
        print("No saved games in data/d12ball_games.json.")
        return 1

    for game_id, game in sorted(games.items()):
        state = "no match state" if game.match_state is None else "renderable"
        print(
            f"  {game_id}  PBD{game.game_number}  "
            f"{game.status.value:12} board={game.board_size}  {state}"
        )
    return 0


def match_from_saved_game(game_id: str) -> tuple[MatchState, str]:
    games = load_games()
    game = games.get(game_id)
    if game is None:
        raise SystemExit(
            f"No saved game {game_id!r}. Use --list-games to see the options."
        )
    if game.match_state is None:
        raise SystemExit(
            f"Game {game_id!r} has no match state yet; it is still in setup."
        )

    match = MatchState.from_dict(game.match_state, load_basic_ruleset())
    return match, f"PBD{game.game_number}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render a D12 Ball board image to a file.",
    )
    parser.add_argument(
        "--game",
        help="Render this saved game from data/d12ball_games.json.",
    )
    parser.add_argument(
        "--list-games",
        action="store_true",
        help="List saved games that can be rendered, then exit.",
    )
    parser.add_argument(
        "--home",
        default="purple",
        choices=[team.value for team in Team],
        help="Home team for a fresh match (default: purple).",
    )
    parser.add_argument(
        "--visiting",
        default="teal",
        choices=[team.value for team in Team],
        help="Visiting team for a fresh match (default: teal).",
    )
    parser.add_argument(
        "--home-formation",
        default=Formation.TWO_TWO_TWO.value,
        choices=[formation.value for formation in Formation],
        help="Home formation for a fresh match (default: 2-2-2).",
    )
    parser.add_argument(
        "--visiting-formation",
        default=Formation.TWO_TWO_TWO.value,
        choices=[formation.value for formation in Formation],
        help="Visiting formation for a fresh match (default: 2-2-2).",
    )
    parser.add_argument(
        "--board-size",
        type=int,
        default=7,
        choices=sorted(VALID_BOARD_SIZES),
        help="Board size for a fresh match (default: 7).",
    )
    parser.add_argument(
        "--title",
        help="Override the title drawn across the top of the image.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Where to write the PNG (default: {DEFAULT_OUTPUT.name}).",
    )
    arguments = parser.parse_args()

    if arguments.list_games:
        raise SystemExit(list_games())

    catalog = load_player_catalog()

    if arguments.game:
        match, label = match_from_saved_game(arguments.game)
    else:
        if arguments.home == arguments.visiting:
            raise SystemExit("--home and --visiting must be different teams.")
        match = MatchState.standard(
            catalog=catalog,
            ruleset=load_basic_ruleset(),
            board_size=arguments.board_size,
            home_team=Team(arguments.home),
            visiting_team=Team(arguments.visiting),
            home_formation=Formation(arguments.home_formation),
            visiting_formation=Formation(arguments.visiting_formation),
        )
        label = "Sample"

    title = arguments.title or (
        f"{label} - {match.home.team.value.title()} vs. "
        f"{match.visiting.team.value.title()}, {period_label(match)}"
    )
    image = render_match_image(match, catalog, title=title)

    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_bytes(image.getvalue())
    print(f"Wrote {arguments.out} ({arguments.out.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
