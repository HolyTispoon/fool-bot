import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_FOLDER = PROJECT_ROOT / "data"
GAMES_FILE = DATA_FOLDER / "d12ball_games.json"


@dataclass
class D12BallGame:
    game_id: str
    game_number: int
    guild_id: int
    channel_id: int
    message_id: Optional[int]
    player_1_id: int
    player_2_id: Optional[int]
    coin_flipped: bool = False
    coin_winner: Optional[str] = None


def load_games() -> dict[str, D12BallGame]:
    DATA_FOLDER.mkdir(parents=True, exist_ok=True)

    if not GAMES_FILE.exists():
        return {}

    try:
        with GAMES_FILE.open("r", encoding="utf-8") as file:
            raw_data = json.load(file)
    except (json.JSONDecodeError, OSError) as error:
        print(f"Could not load D12 Ball games: {error}")
        return {}

    games: dict[str, D12BallGame] = {}

    for game_id, game_data in raw_data.items():
        try:
            games[game_id] = D12BallGame(**game_data)
        except TypeError as error:
            print(f"Skipping invalid saved game {game_id}: {error}")

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