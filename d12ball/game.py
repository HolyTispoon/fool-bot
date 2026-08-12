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


class Formation(str, Enum):
    """
    How many of a team's six fielded cards sit in each zone, read own
    goal / midfield / opponent's goal. Every game kicks off in 2-2-2;
    the others are reached by rearranging in a substitution window.
    The shapes themselves (and the check that each fields six) live in
    `basic_rules.json`, so the two have to be changed together.

    **Not every shape is played on every board.** The first three are,
    and `basic_rules.json` says so by giving them no `board_sizes`;
    3-2-1 and 1-2-3 put three cards in a goal zone, which only the
    nine-space board has three spaces for, so those two are listed for
    board 9 alone. That is the author's call and not a consequence of
    the geometry -- 2-3-1 and 1-3-2 overfill a six-space board's
    midfield and are played there anyway, stacking, which is what the
    run back's coverage rule is written for (see "Occupancy" in
    docs/living-rules.md). Which board a shape may be picked on is
    `BasicRuleset.formations_for_board`, never a size test written out
    somewhere else.
    """

    TWO_TWO_TWO = "2-2-2"
    TWO_THREE_ONE = "2-3-1"
    ONE_THREE_TWO = "1-3-2"
    THREE_TWO_ONE = "3-2-1"
    ONE_TWO_THREE = "1-2-3"


class AIOpponent(str, Enum):
    DINKY = "dinky"
    DECENT = "decent"


class GameStatus(str, Enum):
    SETUP = "setup"
    IN_PROGRESS = "in_progress"
    FINISHED = "finished"


class HomeChoice(str, Enum):
    HOME = "home"
    VISITING = "visiting"


class CoinFace(str, Enum):
    FORTUNE = "fortune"
    DOOM = "doom"


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
    test_game: bool = False

    # Which AI template controls Player 2. Only meaningful when
    # player_2_id is None; unused (and left None) in two-player games.
    ai_opponent: Optional[AIOpponent] = None

    # The name the game was created with, if one was given. It only
    # decides what the channel is called (see build_game_channel_name);
    # a game created without one gets the players' names instead.
    game_name: Optional[str] = None

    # Game configuration
    mode: GameMode = GameMode.BASIC
    status: GameStatus = GameStatus.SETUP
    board_size: int = 7

    # Coin-toss information
    coin_flipped: bool = False
    coin_winner: Optional[str] = None
    coin_winner_player_number: Optional[int] = None
    coin_flipped_by_player_number: Optional[int] = None
    coin_face: Optional[CoinFace] = None

    # Home and visiting assignments (1 = Player 1, 2 = Player 2/AI)
    home_player_number: Optional[int] = None
    visiting_player_number: Optional[int] = None

    # Standard board, team-board, card, and meeple state
    ruleset_id: Optional[str] = None
    player_data_version: Optional[int] = None
    match_state: Optional[dict] = None
    turn_message_id: Optional[int] = None

    # The full-time message carrying the rematch button, and the game
    # that button created. The id restores the button after a restart;
    # the game id is what keeps a second click from opening a second
    # rematch channel.
    rematch_message_id: Optional[int] = None
    rematch_game_id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.player_1_team is not None:
            self.player_1_team = Team(self.player_1_team)

        if self.player_2_team is not None:
            self.player_2_team = Team(self.player_2_team)

        self.mode = GameMode(self.mode)
        self.status = GameStatus(self.status)

        if self.ai_opponent is not None:
            self.ai_opponent = AIOpponent(self.ai_opponent)

        if self.coin_face is not None:
            self.coin_face = CoinFace(self.coin_face)

        if (
            self.coin_flipped
            and self.coin_winner_player_number is None
            and self.coin_winner is not None
        ):
            if self.coin_winner == f"<@{self.player_1_id}>":
                self.coin_winner_player_number = 1
            elif (
                self.player_2_id is None
                and self.coin_winner == "the Dinky AI"
            ):
                self.coin_winner_player_number = 2
            elif self.coin_winner == f"<@{self.player_2_id}>":
                self.coin_winner_player_number = 2

        for player_number in (
            self.coin_winner_player_number,
            self.coin_flipped_by_player_number,
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
            and not self.test_game
        ):
            raise ValueError(
                "Player 1 and Player 2 must be different users."
            )

        if self.test_game and self.player_1_id != self.player_2_id:
            raise ValueError(
                "A test game must use the same user for both players."
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

    def resolve_coin_toss(
        self,
        flipping_player_number: int,
        face: CoinFace,
    ) -> int:
        """
        Record a coin toss and return the winning player number.

        The coin is read from the point of view of the player who
        flipped it: a fortune side wins them the toss, a doom side
        hands it to their opponent.
        """
        if self.coin_flipped:
            raise ValueError("The coin has already been flipped.")

        if flipping_player_number not in {1, 2}:
            raise ValueError("Player numbers must be either 1 or 2.")

        face = CoinFace(face)
        other_player_number = 2 if flipping_player_number == 1 else 1
        winner_player_number = (
            flipping_player_number
            if face == CoinFace.FORTUNE
            else other_player_number
        )

        self.coin_flipped = True
        self.coin_face = face
        self.coin_flipped_by_player_number = flipping_player_number
        self.coin_winner_player_number = winner_player_number

        return winner_player_number

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

    def abandon(self) -> None:
        """
        End a game nobody is going to finish -- see
        D12Ball.abandon_game.

        Unlike `finish_game` this accepts a game still in setup: a
        game gets stuck before kickoff as easily as after it, and a
        half-configured game is exactly the kind nobody comes back to.
        Only a game that has already ended is refused, so that
        abandoning twice cannot un-finish a real result.
        """
        if self.status == GameStatus.FINISHED:
            raise ValueError("This game has already finished.")

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
