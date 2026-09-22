from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Optional


class Team(str, Enum):
    """
    Eight rosters along two axes, since the 2026-08-17 reshuffle: the
    original four **color** teams (mixed roster, 3 of their own species
    plus 2 of each other) and the four **species** teams the reshuffle
    drew them from (Fire Demons, Cyborgs, Telekinetics, Oozes -- each
    the pre-reshuffle grouping, unchanged in membership). A player now
    belongs to exactly one of each, never two of the same axis -- see
    `TEAM_PAIRS` for which color and which species go together, and
    `PlayerCatalog`/`TeamDefinition` in `d12ball/components.py` for how
    that dual membership is stored (a flat player table plus a roster
    of ids per team, rather than a `team` field on the player).
    """

    ORANGE = "orange"
    TEAL = "teal"
    PURPLE = "purple"
    SLIME = "slime"
    FIRE_DEMONS = "fire_demons"
    CYBORGS = "cyborgs"
    TELEKINETICS = "telekinetics"
    OOZES = "oozes"


# Color <-> species, both directions readable off one dict rather than
# two, since a game is only ever asking "what is this team's pair" and
# never cares which axis it started from. This is the one source of
# truth `TEAM_COLORS` (d12ball/render.py) and the legacy-save migration
# (gamesaves/d12ball/storage.py) both read.
#
# It **is** what says who may not play whom, for the color and not for
# the roster: a pair shares a hex, so that one match would draw both
# sides the same. Every other color/species matchup shares players too
# -- 2 of them -- and is played with those fielded as two cards. See
# "Team colors" and "One player, both sides" in docs/design/teams-and-players.md.
TEAM_PAIRS: dict[Team, Team] = {
    Team.ORANGE: Team.FIRE_DEMONS,
    Team.FIRE_DEMONS: Team.ORANGE,
    Team.TEAL: Team.CYBORGS,
    Team.CYBORGS: Team.TEAL,
    Team.PURPLE: Team.TELEKINETICS,
    Team.TELEKINETICS: Team.PURPLE,
    Team.SLIME: Team.OOZES,
    Team.OOZES: Team.SLIME,
}


def paired_team(team: Team) -> Team:
    """
    The team on the other axis that shares this one's hex color -- a
    color team's own species team, or a species team's own color team.
    """
    return TEAM_PAIRS[Team(team)]


# The two axes, each in the order they are offered in -- the team
# picker's two button rows (cogs/d12ball_views.py) and the importer's
# canonical team ordering both read these rather than writing the
# four-tuples out again.
COLOR_TEAMS: tuple[Team, ...] = (
    Team.ORANGE, Team.TEAL, Team.PURPLE, Team.SLIME,
)
SPECIES_TEAMS: tuple[Team, ...] = (
    Team.FIRE_DEMONS, Team.CYBORGS, Team.TELEKINETICS, Team.OOZES,
)


def team_display_name(team: Team) -> str:
    """
    A team's name the way it is shown to a coach -- "Fire Demons", not
    "Fire_Demons". `str.title()` alone doesn't turn an underscore into
    a space, so every `team.value.title()` call site was silently wrong
    the moment a team's value carried one; this is the one place that
    turns a `Team` into words and every such call site reads it now.
    Lives here, next to `Team` itself, rather than in a cog module,
    since `d12ball/components.py` needs it too and cogs import from
    `d12ball`, never the other way around.
    """
    return Team(team).value.replace("_", " ").title()


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
    # Save-data identifiers
    game_id: str
    game_number: int

    # Where the game is played on Discord: the server, the channel, and
    # the message every board refresh edits. **All three are optional**,
    # because a game is not a Discord thing (ARCHITECTURE.md, part 1): a
    # game the web frontend creates has no channel, and the startup
    # sweep skips one rather than being handed a fake. Keyword-only so
    # the fields that follow keep their place in the saved dict -- the
    # record is the wire format (principle 6 in CLAUDE.md) and every
    # existing save reads back exactly as it was; a missing id reads as
    # `None`, which is what a game that never had a channel carries.
    guild_id: Optional[int] = field(default=None, kw_only=True)
    channel_id: Optional[int] = field(default=None, kw_only=True)
    message_id: Optional[int] = field(default=None, kw_only=True)

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

    # The scripted opening -- see d12ball/tutorial.py. `tutorial` is
    # what the game was created as and never changes; `tutorial_step`
    # is the beat in progress and is cleared when the script runs out
    # or the coach skips it, which is what turns the rails off. Both
    # live here rather than on MatchState because a tutorial is a
    # property of the *game*, the way test_game and ai_opponent are,
    # and because the rails are read by views that hold a game id and
    # may not have loaded a match yet.
    #
    # `tutorial_staged` says whether the current beat's position and
    # lesson have been applied. It is what makes staging idempotent:
    # `send_turn_prompt` is called once a turn and advances the step,
    # but `/d12ball offensive_choice` and `/d12ball resume force:true`
    # call it too, and neither of those is a new turn.
    tutorial: bool = False
    tutorial_step: Optional[int] = None
    tutorial_staged: bool = False
    # Whether the Coaching Choice note has been posted. The script does
    # not stage a beat for it -- the goal at the end of beat 5 is a new
    # play, and a new play offers the window itself -- so this is what
    # keeps the note to the first window the coach is offered rather
    # than every one of them.
    tutorial_coaching_explained: bool = False
    # The tutorial note the coach has not yet pressed Continue on, and
    # what pressing it runs -- `{"note": <key>, "then": <FollowOn as
    # saved> | None}`, or None, which is nearly always. See
    # `d12ball/flow/gates.py`. Every other tutorial note is posted
    # plainly; the gated ones are the notes with a live prompt behind
    # them, which used to be held on a `TutorialContinueView` closure
    # and nowhere else -- so a restart lost the button, and the model
    # had no way to say the match was waiting on a click that changed
    # nothing. Now `pending_prompt` reads it first: the gate *is* what
    # the match is waiting on. Absent from an older save it reads as
    # None, which is a game with no note up.
    tutorial_gate: Optional[dict] = None

    # Game configuration
    mode: GameMode = GameMode.BASIC
    status: GameStatus = GameStatus.SETUP
    board_size: int = 7

    # The two modules advanced mode turns on -- the gambits
    # and the species abilities. "Turning it on brings both; a game may
    # take just one of the two" (the author, PR #177 review), so these
    # are opt-*outs* rather than opt-ins: both default True and mean
    # nothing at all in a basic game, where `mode` is the whole answer.
    #
    # That is why they are two bools rather than a third GameMode value
    # or a set of enabled modules. A game is basic or advanced -- one
    # switch, which is what a coach picks in the lobby and what every
    # existing save carries -- and these two say what an advanced game
    # left behind. Defaulting True is what makes a game saved before
    # them (and every advanced game played so far) read as both modules
    # on, which is what those games actually were.
    #
    # Nothing may read either of these directly to decide a rule:
    # `RulesEngine.gambits_apply` and
    # `RulesEngine.species_abilities_apply` are the two answers, and
    # they fold `mode` in so a caller cannot forget it.
    advanced_maneuvers: bool = True
    species_abilities: bool = True

    # Whether the game record exists but is still sitting in its
    # pre-game lobby -- players joining or leaving, settings being
    # picked, nobody having pressed Start Game yet. See "The
    # game-creation hub and the lobby" in docs/design/hub-and-lobby.md.
    #
    # A lobby is an ordinary SETUP game (no GameStatus value of its
    # own), so `start_game`, the stats scoping and the startup sweep are
    # all untouched. While this is True the game has `player_2_id = None`
    # and `ai_opponent = None` even for a game two humans will play, and
    # `test_game` may be set with `player_2_id` still None -- all of it
    # is settled when Start Game is pressed, so nothing may read
    # `is_solo_game` off a lobby, and `__post_init__` relaxes its "a
    # test game uses one user for both sides" check while this holds.
    # `restore_saved_views` re-arms the lobby view rather than the team
    # picker while it is set.
    in_lobby: bool = False

    # User ids who asked to watch this game from its lobby. A lobby
    # channel is visible to the whole server; when Start Game locks it
    # down to the two players, everyone in this list keeps read-only
    # access. Players are never in here -- joining as a player removes
    # you. Only meaningful up to kickoff; carried afterwards only so a
    # restart still knows who to keep visible.
    observer_ids: list[int] = field(default_factory=list)

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

    # Whether this game was given up rather than played out. Both
    # `finish_game` and `abandon` leave the status FINISHED, which is
    # right -- neither is coming back -- but only one of them produced
    # a result. Nothing in the flow needs to tell them apart; the
    # statistics do, since a scoreboard read off a game nobody
    # finished is a win nobody earned. Defaults False, so a game saved
    # before this counts as played out: that is what almost all of
    # them are, and the alternative is throwing away every finished
    # game older than the field.
    abandoned: bool = False

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

        if (
            self.test_game
            and not self.in_lobby
            and self.player_1_id != self.player_2_id
        ):
            # A test-game lobby carries the flag before Start Game
            # assigns Player 2 -- `lobby_start` sets `player_2_id =
            # player_1_id` on the way out, so the record is consistent
            # for the whole of the game itself.
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
    def in_tutorial(self) -> bool:
        """
        Whether the scripted opening is still running -- which is what
        every rail in the views asks. A tutorial game that has finished
        its script, or whose coach skipped it, answers False and plays
        exactly like any other solo game; `tutorial` stays True so the
        channel and the game record still say what it was created as.
        """
        return self.tutorial and self.tutorial_step is not None

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
        self.abandoned = True

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
