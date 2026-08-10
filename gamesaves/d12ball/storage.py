import json
import logging
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Optional
from d12ball.game import D12BallGame


LOGGER = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_FOLDER = PROJECT_ROOT / "data"
GAMES_FILE = DATA_FOLDER / "d12ball_games.json"

def load_games() -> dict[str, D12BallGame]:
    DATA_FOLDER.mkdir(parents=True, exist_ok=True)

    if not GAMES_FILE.exists():
        return {}

    try:
        with GAMES_FILE.open("r", encoding="utf-8") as file:
            raw_data = json.load(file)
    except (json.JSONDecodeError, OSError) as error:
        # Errors, not warnings: every game the bot knows about has just
        # vanished from its view, and the players will see that as the
        # bot forgetting their match.
        LOGGER.error("Could not load D12 Ball games: %s", error)
        return {}

    games: dict[str, D12BallGame] = {}
    known_fields = {field.name for field in fields(D12BallGame)}

    for game_id, game_data in raw_data.items():
        # A key the record no longer has is a field that was removed
        # while games saved under it were still half-played --
        # `tie_mode`, when league mode went. Dropping it keeps those
        # games loading; passing it through would raise TypeError and
        # take the whole game out of the bot's view. Console-only,
        # because nobody can act on it and every restart would repeat
        # it.
        retired = sorted(set(game_data) - known_fields)
        if retired:
            LOGGER.info(
                "Ignoring retired field(s) %s on saved game %s.",
                ", ".join(retired),
                game_id,
            )
            game_data = {
                key: value
                for key, value in game_data.items()
                if key in known_fields
            }

        try:
            games[game_id] = D12BallGame(**game_data)
        except TypeError as error:
            LOGGER.error("Skipping invalid saved game %s: %s", game_id, error)

    return games


def save_games(games: dict[str, D12BallGame]) -> None:
    DATA_FOLDER.mkdir(parents=True, exist_ok=True)

    serialized_games = {
        game_id: asdict(game)
        for game_id, game in games.items()
    }

    temporary_file = GAMES_FILE.with_suffix(".tmp")

    with temporary_file.open("w", encoding="utf-8") as file:
        json.dump(serialized_games, file, indent=2)

    temporary_file.replace(GAMES_FILE)