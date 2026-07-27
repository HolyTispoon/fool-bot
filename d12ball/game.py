from dataclasses import asdict, dataclass
from enum import Enum
from typing import Optional


class Team(str, Enum):
    ORANGE = "orange"
    TEAL = "teal"
    PURPLE = "purple"
    SLIME = "slime"


class GameMode(str, Enum):
    BASIC = "basic"
    ADVANCED = "advanced"


class GameStatus(str, Enum):
    SETUP = "setup"
    IN_PROGRESS = "in_progress"
    FINISHED = "finished"


VALID_BOARD_SIZES = {6, 7, 9}


@dataclass
class D12BallGame:
    # Discord and save-data identifiers
    game_id: str
    game_number: int
    guild_id: int
    channel_id: int
    message_id: Optional[int]

    # Players
    player_1_id: int
    player_2_id: Optional[int]
    # None means Player 2 is controlled by the AI.

    player_1_team: Optional[Team] = None
    player_2_team: Optional[Team] = None

    # Game configuration
    mode: GameMode = GameMode.BASIC
    status: GameStatus = GameStatus.SETUP
    board_size: int = 7

    # Coin-toss information
    coin_flipped: bool = False
    coin_winner: Optional[str] = None

    def __post_init__(self) -> None:
        if self.player_1_team is not None:
            self.player_1_team = Team(self.player_1_team)

        if self.player_2_team is not None:
            self.player_2_team = Team(self.player_2_team)

        self.mode = GameMode(self.mode)
        self.status = GameStatus(self.status)

        if self.board_size not in VALID_BOARD_SIZES:
            raise ValueError(
            f"Board size must be one of {sorted(VALID_BOARD_SIZES)}."
            )

        if (
            self.player_2_id is not None
            and self.player_1_id == self.player_2_id
        ):
            raise ValueError(
                "Player 1 and Player 2 must be different users."
            )

    @property
    def is_solo_game(self) -> bool:
        """
        True when Player 2 is controlled by the AI.
        """
        return self.player_2_id is None

    @property
    def is_in_setup(self) -> bool:
        return self.status == GameStatus.SETUP

    @property
    def is_in_progress(self) -> bool:
        return self.status == GameStatus.IN_PROGRESS

    @property
    def is_finished(self) -> bool:
        return self.status == GameStatus.FINISHED
    
    @property
    def teams_selected(self) -> bool:
        return (
            self.player_1_team is not None
            and self.player_2_team is not None
        )

    def start_game(self) -> None:
        """
        Move the game from setup to in progress.
        """
        if self.status != GameStatus.SETUP:
            raise ValueError(
                "Only a game in setup can be started."
            )

        self.status = GameStatus.IN_PROGRESS

    def finish_game(self) -> None:
        """
        Mark an active game as finished.
        """
        if self.status != GameStatus.IN_PROGRESS:
            raise ValueError(
                "Only a game in progress can be finished."
            )

        self.status = GameStatus.FINISHED

    def to_dict(self) -> dict:
        """
        Convert the game into JSON-friendly data.
        """
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "D12BallGame":
        """
        Recreate a game from saved JSON data.
        """
        return cls(**data)