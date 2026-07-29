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


class HomeChoice(str, Enum):
    HOME = "home"
    VISITING = "visiting"


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

    player_1_name: Optional[str] = None
    player_2_name: Optional[str] = None
    player_1_team: Optional[Team] = None
    player_2_team: Optional[Team] = None

    # Game configuration
    mode: GameMode = GameMode.BASIC
    status: GameStatus = GameStatus.SETUP
    board_size: int = 7

    # Coin-toss information
    coin_flipped: bool = False
    coin_winner: Optional[str] = None
    coin_winner_player_number: Optional[int] = None

    # Home and visiting assignments (1 = Player 1, 2 = Player 2/AI)
    home_player_number: Optional[int] = None
    visiting_player_number: Optional[int] = None

    def __post_init__(self) -> None:
        if self.player_1_team is not None:
            self.player_1_team = Team(self.player_1_team)

        if self.player_2_team is not None:
            self.player_2_team = Team(self.player_2_team)

        self.mode = GameMode(self.mode)
        self.status = GameStatus(self.status)

        if (
            self.coin_flipped
            and self.coin_winner_player_number is None
            and self.coin_winner is not None
        ):
            if self.coin_winner == f"<@{self.player_1_id}>":
                self.coin_winner_player_number = 1
            elif (
                self.player_2_id is None
                and self.coin_winner == "the AI opponent"
            ):
                self.coin_winner_player_number = 2
            elif self.coin_winner == f"<@{self.player_2_id}>":
                self.coin_winner_player_number = 2

        for player_number in (
            self.coin_winner_player_number,
            self.home_player_number,
            self.visiting_player_number,
        ):
            if player_number is not None and player_number not in {1, 2}:
                raise ValueError("Player numbers must be either 1 or 2.")

        if (
            (self.home_player_number is None)
            != (self.visiting_player_number is None)
        ):
            raise ValueError(
                "Home and visiting players must be assigned together."
            )

        if (
            self.home_player_number is not None
            and self.home_player_number == self.visiting_player_number
        ):
            raise ValueError(
                "Home and visiting players must be different."
            )

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

    @property
    def home_and_visiting_selected(self) -> bool:
        return (
            self.home_player_number is not None
            and self.visiting_player_number is not None
        )

    def choose_home_or_visiting(
        self,
        player_number: int,
        choice: HomeChoice,
    ) -> None:
        if not self.coin_flipped:
            raise ValueError("The coin must be flipped first.")

        if self.coin_winner_player_number != player_number:
            raise ValueError("Only the coin-toss winner can choose.")

        if self.home_and_visiting_selected:
            raise ValueError("Home and visiting teams are already assigned.")

        choice = HomeChoice(choice)
        other_player_number = 2 if player_number == 1 else 1

        if choice == HomeChoice.HOME:
            self.home_player_number = player_number
            self.visiting_player_number = other_player_number
        else:
            self.home_player_number = other_player_number
            self.visiting_player_number = player_number

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
