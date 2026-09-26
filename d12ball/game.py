from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Optional


class RuleRefusal(ValueError):
    """
    The position refusing what was chosen, with the sentence to show.

    **The one channel a refusal travels on.** A step, a `MatchState`
    mutator, an adapter in `d12ball.flow.driver` or a method on the
    game record below raises this where a rule says no -- a space that
    player may not take, a substitution with none left, a swap that
    moves nobody, a coin flipped twice, a lobby nobody may join -- and
    `driver.answer` and the setup methods on `GameService` let this
    through and nothing else, so a frontend shows it and a bug
    propagates. Until step 6 of docs/architecture-migration.md the
    channel was `ValueError`, which caught the interpreter's own
    sentences too: a `TeamSide` built from a bad wire value came back
    as a refusal worded by Python and shown to a person. A
    `ValueError` that is not one of these is a bug again.

    A subclass of `ValueError` so that every caller that already read
    a refusal as one still does; what changed is what the model's own
    door catches. Defined here, the leaf of the model, because the
    record refuses too; `d12ball.components` re-exports it.
    """


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
    """
    The three modes a game is played in (2026-09-25): **training**, the
    game with no ability of any kind (Part I of the Charter alone);
    **basic**, which adds the species abilities; and **advanced**, which
    adds the gambits and the players' individual abilities on top. See
    "Modes" in docs/design/species-abilities.md.

    `basic` is the value every save made before training mode existed
    carries, and it now means the game with species abilities -- the
    value was kept rather than renamed (CLAUDE.md: don't rename saved
    keys), so an unfinished basic game plays on as a basic game.
    """

    TRAINING = "training"
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
    the geometry: a shape too deep for a zone would be dealt anyway,
    stacking, which is what the run back's coverage rule is written for
    (see "Occupancy" in docs/living-rules.md). No shape the two boards
    share stacks. Which board a shape may be picked on is
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


#: The boards a game may be played on. The six-space board was
#: withdrawn on 2026-09-22 -- see that day's entry in docs/rules-log.md
#: -- so a record carrying it no longer loads, which `load_games`
#: reports as an invalid save rather than letting it take every other
#: game down with it.
VALID_BOARD_SIZES = {7, 9}

#: What `D12BallGame.configure` may be asked to set. The lobby and the
#: setup settings block each offer a subset; the record refuses the
#: rest by its state (a game past its lobby has no Test game toggle),
#: never by which screen asked.
GAME_SETTINGS = ("mode", "board", "ai", "test", "tutorial", "name")

#: What a lobby refuses once Start Game has been pressed.
LOBBY_CLOSED = "This lobby is no longer open."


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
    # `player_1_id` is None only in a web room whose first seat has been
    # left (`vacate_seat`); nothing else writes it, so every save made
    # before the rooms reads back with an id here.
    player_1_id: Optional[int]
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

    # Two opt-outs advanced mode carried until 2026-09-25, when it was
    # one switch over two modules (the gambits and the species
    # abilities) and a game could drop either. The modes became three
    # that day and species abilities moved into basic, so the toggles
    # went; nothing sets these to False any more. They stay on the
    # record because they are saved fields (CLAUDE.md: legacy fallbacks
    # stay) and an advanced game started with one module off plays on
    # as it was started.
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

    # -- The lobby ----------------------------------------------------
    #
    # Every rule about who is in a game before it starts, and what its
    # settings may be, is the record's: `GameService` calls one of these
    # and saves, a frontend reports the refusal. See "The game-creation
    # hub and the lobby" in docs/design/hub-and-lobby.md.

    def require_lobby(self) -> None:
        if not self.in_lobby:
            raise RuleRefusal(LOBBY_CLOSED)

    def lobby_join(self, user_id: int, user_name: Optional[str]) -> None:
        """
        Take the second seat. Refused for the creator, for a
        one-player game, and for a lobby that is full; joining
        supersedes observing and settles the opponent, so any AI pick
        the creator made is cleared.
        """
        self.require_lobby()
        if user_id == self.player_1_id:
            raise RuleRefusal("You are already in this lobby.")
        if self.test_game or self.tutorial:
            raise RuleRefusal(
                "This is a one-player game. The creator can switch it to "
                "a two-player game so you can join."
            )
        if self.player_2_id is not None:
            raise RuleRefusal(
                "This lobby is full -- a game is two players. You can "
                "still **Observe**."
            )

        self.player_2_id = user_id
        self.player_2_name = user_name
        if user_id in self.observer_ids:
            self.observer_ids.remove(user_id)
        self.ai_opponent = None

    def lobby_observe(self, user_id: int) -> None:
        """Ask to keep watching once the game locks its channel down.
        A player is never an observer."""
        self.require_lobby()
        if user_id in (self.player_1_id, self.player_2_id):
            raise RuleRefusal(
                "You are playing in this game, not observing it."
            )
        if user_id in self.observer_ids:
            raise RuleRefusal(
                "You are already on the observer list. **Leave** to drop "
                "off it."
            )
        self.observer_ids.append(user_id)

    def lobby_leave(self, user_id: int) -> None:
        """
        Drop off whichever list the person is on. The creator leaving
        with a second player present hands them the lobby; the creator
        leaving alone is refused -- a lobby is never abandoned just
        because it emptied out.
        """
        self.require_lobby()
        if user_id in self.observer_ids:
            self.observer_ids.remove(user_id)
            return
        if user_id == self.player_2_id:
            self.player_2_id = None
            self.player_2_name = None
            return
        if user_id != self.player_1_id:
            raise RuleRefusal("You are not in this lobby.")
        if self.player_2_id is None:
            raise RuleRefusal(
                "You are the only player, so there is nobody to hand the "
                "lobby to -- it stays open. Invite someone to join, or "
                "just start the game to play solo."
            )
        self.player_1_id = self.player_2_id
        self.player_1_name = self.player_2_name
        self.player_2_id = None
        self.player_2_name = None

    # -- Seats ----------------------------------------------------------
    #
    # A web room's two moves (decision 1 of docs/web-app-next.md): a
    # seat changes hands at any time, before kickoff or during the game,
    # and the other seat never moves. The lobby's own moves above stay
    # as they are -- the Discord lobby depends on the creator's seat
    # shifting and on the moves closing at start.
    #
    # Safe mid-game because everything the match keeps about a side is
    # by player *number* (`home_player_number`,
    # `coin_winner_player_number`), never by id: a new id in a seat is
    # the same side, with the same position and the same question.
    #
    # **Seat 2 is never emptied outside the lobby.** An empty
    # `player_2_id` is how the record says the AI plays that side
    # (`is_solo_game`), and older saves say it with `ai_opponent`
    # unset too, so an emptied human seat would be handed to Dinky on
    # the next turn. Until the record can tell the two apart, seat 2
    # holds whoever held it last once the lobby has closed.

    def seat_is_free(self, seat: int) -> bool:
        """Whether nobody holds `seat` and somebody may take it. Seat
        2 is nobody's in a one-player game, and the AI's once a solo
        game has left its lobby."""
        if seat == 1:
            return self.player_1_id is None
        if seat == 2:
            return (
                self.player_2_id is None
                and self.in_lobby
                and not (self.test_game or self.tutorial)
            )
        raise ValueError(f"not a seat: {seat!r}")

    def take_seat(
        self,
        user_id: int,
        user_name: Optional[str],
        seat: Optional[int] = None,
    ) -> None:
        """
        Sit `user_id` in `seat`, or in the first free one. Refused when
        both are held, when the seat named is somebody else's (or the
        AI's, or a one-player game's second), or when the person
        already holds a seat. Taking the second seat settles the
        opponent, so an AI pick made in the lobby is cleared, as
        `lobby_join` clears it.
        """
        if seat not in (None, 1, 2):
            raise ValueError(f"not a seat: {seat!r}")
        if user_id in (self.player_1_id, self.player_2_id):
            raise RuleRefusal("You already hold a seat in this game.")
        if seat is None:
            seat = next(
                (one for one in (1, 2) if self.seat_is_free(one)), None,
            )
            if seat is None:
                raise RuleRefusal(
                    "Both seats are taken. You can still watch."
                )
        elif not self.seat_is_free(seat):
            if seat == 2 and (self.test_game or self.tutorial):
                raise RuleRefusal(
                    "This is a one-player game, so there is no second "
                    "seat to take."
                )
            if seat == 2 and self.player_2_id is None:
                raise RuleRefusal("The other side of this game is the AI's.")
            raise RuleRefusal("That seat is held by somebody else.")

        if seat == 1:
            self.player_1_id = user_id
            self.player_1_name = user_name
        else:
            self.player_2_id = user_id
            self.player_2_name = user_name
            self.ai_opponent = None
        if user_id in self.observer_ids:
            self.observer_ids.remove(user_id)

    def vacate_seat(self, user_id: int) -> None:
        """
        Empty whichever seat `user_id` holds, leaving the other where
        it is. Refused when they hold none -- and, outside the lobby,
        for seat 2 and for a test game's one coach, who holds both
        (see "Seats" above).
        """
        if user_id is None or user_id not in (
            self.player_1_id, self.player_2_id,
        ):
            raise RuleRefusal("You do not hold a seat in this game.")
        if self.test_game and not self.in_lobby:
            raise RuleRefusal(
                "This is a test game and you play both sides, so its "
                "seats cannot be left."
            )
        if user_id == self.player_1_id:
            self.player_1_id = None
            self.player_1_name = None
            return
        if not self.in_lobby:
            raise RuleRefusal(
                "Seat 2 cannot be left once the game is out of its "
                "lobby: an empty second seat is the AI's."
            )
        self.player_2_id = None
        self.player_2_name = None

    def configure(self, setting: str, value: object = None) -> None:
        """
        Change one setting, by the key a button carries (`GAME_SETTINGS`).

        A value arrives as the enum or as its wire string, whichever
        the frontend holds; one the record cannot read is a bug in the
        frontend and raises as one, where a rule about *this* game --
        the tutorial pins Training on a 7-space board, a joined lobby
        has no Test game toggle -- is refused with the sentence to
        show.

        `mode`, `board` and `ai` are open for the whole of setup;
        `test`, `tutorial` and `name` only in the lobby, since each is
        settled by Start Game. Advanced mode's
        extra maneuvers want the room a nine-space board gives them,
        so picking it defaults the board to 9 -- a coach may still
        pick 6 or 7 afterwards.
        """
        if setting not in GAME_SETTINGS:
            raise ValueError(f"Unknown game setting {setting!r}.")
        if self.status != GameStatus.SETUP:
            raise RuleRefusal(
                "Game settings can only be changed during setup."
            )

        if setting in ("test", "tutorial"):
            self.require_lobby()
            if self.player_2_id is not None:
                raise RuleRefusal(
                    "Someone has already joined -- they would have to "
                    "leave first."
                )
            if setting == "test":
                self.test_game = not self.test_game
                if self.test_game:
                    self.tutorial = False
            else:
                self.tutorial = not self.tutorial
                if self.tutorial:
                    # One person against Dinky, and the script is
                    # written for Training on a 7-space board -- see
                    # d12ball/tutorial.py.
                    self.test_game = False
                    self.ai_opponent = AIOpponent.DINKY
                    self.mode = GameMode.TRAINING
                    self.board_size = 7
        elif setting == "name":
            self.require_lobby()
            self.game_name = str(value or "").strip() or None
        elif setting == "mode":
            if self.tutorial:
                raise RuleRefusal(
                    "The tutorial is a Training-mode game. Turn Tutorial "
                    "off to change the mode."
                )
            self.mode = GameMode(value)
            if self.mode == GameMode.ADVANCED:
                self.board_size = 9
        elif setting == "board":
            if self.tutorial:
                raise RuleRefusal(
                    "The tutorial is played on a 7-space board. Turn "
                    "Tutorial off to change the board."
                )
            board_size = int(value)
            if board_size not in VALID_BOARD_SIZES:
                raise ValueError(
                    f"Board size must be one of {sorted(VALID_BOARD_SIZES)}."
                )
            self.board_size = board_size
        elif setting == "ai":
            ai_opponent = AIOpponent(value)
            if ai_opponent == AIOpponent.DECENT:
                raise RuleRefusal(
                    "Decent AI is not ready yet -- play against Dinky AI."
                )
            if (
                self.player_2_id is not None
                or self.test_game
                or self.tutorial
            ):
                raise RuleRefusal(
                    "The other side of this game is already taken."
                )
            self.ai_opponent = ai_opponent

    def start_lobby(self) -> None:
        """
        Settle who takes the other side and leave the lobby: a test
        game seats the creator on both sides (`__post_init__`'s "same
        user" rule holds again from here -- it is relaxed only while
        `in_lobby`), and the tutorial, or any lobby nobody joined, is
        a solo game against Dinky.
        """
        self.require_lobby()
        if self.player_1_id is None:
            # Only a web room can get here, by leaving its first seat.
            raise RuleRefusal(
                "Seat 1 is empty -- somebody has to hold it to start."
            )
        if self.test_game:
            self.player_2_id = self.player_1_id
            self.player_2_name = self.player_1_name
            self.ai_opponent = None
        elif self.tutorial or self.player_2_id is None:
            self.ai_opponent = self.ai_opponent or AIOpponent.DINKY
        self.in_lobby = False

    def reopen_lobby(self) -> None:
        """
        `start_lobby` undone, for a frontend that could not put the
        started game up: the record goes back to the lobby it was, so
        the lobby's own message keeps working.
        """
        if self.in_lobby or self.status != GameStatus.SETUP:
            raise RuleRefusal("This game has left its lobby.")
        if self.test_game:
            self.player_2_id = None
            self.player_2_name = None
        self.in_lobby = True

    # -- Team selection ----------------------------------------------

    def picking_player_number(self) -> Optional[int]:
        """
        Whose team pick is next on a screen that has to say: `None`
        for a normal game's shared row, where whichever coach clicks
        picks their own side; 1 or 2 for a test game's sequential
        screens, the side that has not chosen yet. Player 1 always
        goes first, since nothing else orders them -- and that is the
        order a helper's pick on the shared row lands in too
        (`team_pick_lands_on`).
        """
        if not self.test_game:
            return None
        if self.player_1_team is None:
            return 1
        return 2

    def team_pick_lands_on(self, requested: Optional[int]) -> int:
        """
        Which side a pick made by nobody in particular is for -- a
        game helper holds neither side, so the pick has to be told
        (see "Who may act on a game" in docs/design/permissions.md). A
        test game's button names the side outright; a normal game's
        two sides share one row, so it goes to the side that has not
        chosen yet, Player 1 first. Getting this wrong is silent: an
        `else` would quietly give every helper's pick to Player 2.
        """
        if self.test_game:
            return requested if requested in (1, 2) else 1
        return 1 if self.player_1_team is None else 2

    def excluded_teams(self, player_number: Optional[int]) -> set[Team]:
        """
        Every team a pick for `player_number` must refuse: whichever
        side(s) already have one, and that team's own `paired_team()`.
        `None` is the normal game's shared row, which refuses on
        behalf of either side.

        **The pairing is refused for its color, not for its roster.**
        A color team and its species team share a hex (`TEAM_COLORS`
        gives Fire Demons Orange's own `#FFA500`), so that one match
        would draw both sides' cards, meeples and tokens in the same
        color -- the board is where a coach reads which meeples are
        theirs, and there is nothing else on it that says. Every other
        color/species matchup is offered and playable: the 2 or 3
        players those rosters share are fielded as two cards, one a
        side. See "One player, both sides" in
        docs/design/teams-and-players.md.
        """
        if player_number == 1:
            # The sequential test-game screen for whoever goes first:
            # nothing is chosen yet, by construction.
            already_chosen: list[Team] = []
        elif player_number == 2:
            # The sequential test-game screen for whoever goes second:
            # only the side that has already gone is excluded here.
            already_chosen = (
                [self.player_1_team]
                if self.player_1_team is not None
                else []
            )
        else:
            already_chosen = [
                team
                for team in (self.player_1_team, self.player_2_team)
                if team is not None
            ]

        excluded: set[Team] = set()
        for team in already_chosen:
            excluded.add(team)
            excluded.add(paired_team(team))
        return excluded

    def ai_team_pool(self) -> list[Team]:
        """The teams an AI side may still be drawn from, once Player 1
        has picked: everything but that team and its pair."""
        return [
            team for team in Team
            if team not in self.excluded_teams(None)
        ]

    def pick_team(self, player_number: int, team: Team) -> None:
        """
        Record one side's team. Refused once selection has closed and
        for a team the other side's pick rules out -- a stale click on
        a screen the game has moved past, which the button should
        already have refused, but a second browser tab or a slow
        double-click can still get one through.
        """
        if player_number not in (1, 2):
            raise ValueError("Player numbers must be either 1 or 2.")
        if self.status != GameStatus.SETUP or self.in_lobby:
            raise RuleRefusal("Team selection is already closed.")
        team = Team(team)
        if team in self.excluded_teams(
            player_number if self.test_game else None,
        ):
            raise RuleRefusal("That team is no longer available.")
        if player_number == 1:
            self.player_1_team = team
        else:
            self.player_2_team = team

    # -- The coin toss and the sides ---------------------------------

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
            raise RuleRefusal("The coin has already been flipped.")

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

    def home_choice_rail(self, player_number: int) -> Optional[HomeChoice]:
        """
        The one side the coin's winner may take, or `None` where the
        choice is theirs. A tutorial is scripted from the kickoff
        forward for a coach with the ball, so its coach (player 1) is
        Home whoever wins the toss: the coach is railed onto Home, and
        Dinky, winning, takes Visiting. A frontend greys the other
        button off this; `choose_home_or_visiting` refuses it.
        """
        if not self.tutorial or self.home_and_visiting_selected:
            return None
        return HomeChoice.HOME if player_number == 1 else HomeChoice.VISITING

    def choose_home_or_visiting(
        self,
        player_number: int,
        choice: HomeChoice,
    ) -> None:
        if not self.coin_flipped:
            raise RuleRefusal("The coin must be flipped first.")

        if self.coin_winner_player_number != player_number:
            raise RuleRefusal("Only the coin-toss winner can choose.")

        if self.home_and_visiting_selected:
            raise RuleRefusal("Home and visiting teams are already assigned.")

        choice = HomeChoice(choice)
        rail = self.home_choice_rail(player_number)
        if rail is not None and choice != rail:
            raise RuleRefusal("In the tutorial the coach plays Home.")

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
            raise RuleRefusal(
                "Only a game in setup can be started."
            )

        self.status = GameStatus.IN_PROGRESS

    def finish_game(self) -> None:
        """
        Mark an active game as finished.
        """
        if self.status != GameStatus.IN_PROGRESS:
            raise RuleRefusal(
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
            raise RuleRefusal("This game has already finished.")

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
