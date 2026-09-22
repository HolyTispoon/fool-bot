"""
`GameService`: the one door for a change to a game, shared by every
frontend -- see ARCHITECTURE.md, part 2.

A frontend authorises the person, turns what they did into an
`Action`, and calls `apply_action`. The service loads the match, runs
the answer and everything it starts through `d12ball.flow.driver`,
**saves once**, and hands back a `GameResult` the frontend renders.
It formats nothing: no Discord message, no HTTP response. The steps
it runs save nothing either (principle 9 in CLAUDE.md); this is where
the one write per click lives, and the only place `game.match_state`
is written from a running game.

**What the result carries is richer than a list of strings, on
purpose.** A frontend posts pictures of the position in the middle
of a run -- a loose ball is announced by showing where it is, a new
play's board is pinned -- and where those go is not a free choice:
the goldens pin it. So the result is the run's narration in
**groups**, each tagged with the step that said it and, where the
frontend stopped to draw, carrying the position as a dict. The
Discord cog renders each group as the messages its step earns; a web
page renders the same groups and the same boards. A flat list would
lose the order a coach reads.

**Batching stays the frontend's** (principle 8). `Batching` is the
frontend's answer to "which steps' lines are a message of their own,
where do you stop to draw, what do you do at a stop, and how much of
an AI answer's lines are its own", handed to the service once at
construction. The service never reads a step's name to decide
anything; it asks the `Batching` it was given.

**Setup and the lobby are service methods, not prompt kinds**
(decision 6 of docs/web-app.md; ARCHITECTURE.md, part 2: "lobby
operations can use small service methods"). `create_game`, the four
lobby operations, `configure`, `pick_team`, `flip_coin` and
`choose_home_or_visiting` each load the record, apply one change the
record itself rules on (`D12BallGame`, which refuses with
`RuleRefusal`), draw what the AI or the coin has to add through the
engine and its strategies, and save once. There is no turn to run,
so they hand back the record rather than a `GameResult`, and a
refusal is the exception itself: nothing was written, and the
frontend shows the sentence.

**The AI answers here.** When the run reaches a prompt put to an AI
side, `run` asks the strategy for an `Action` (`driver.ai_action`),
puts it through `driver.answer` like a click, and carries on -- so
the AI mutates the match through the one door everybody else uses
(ARCHITECTURE.md, "AI"; step 7 of docs/architecture-migration.md).
What was said before the question is closed as a group of its own,
tagged with the prompt it opened, the way a coach's prompt message
would have carried it; the AI's own answer is a group tagged with the
action, split by the frontend's `carry_answer` exactly as a view
splits a coach's with `carry_from`. A roll is nobody's question, so
the loop stops there and the AI never rolls.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field, replace
from enum import Enum, auto
from typing import Any, Callable, Mapping, Optional, Sequence, Union

from d12ball.components import MatchState, RuleRefusal, TeamSide
from d12ball.engine import RulesEngine
from d12ball.flow import driver, periods
from d12ball.flow.result import FollowOn, FollowOnStep, StepResult
from d12ball.formatting import format_player
from d12ball.game import (
    AIOpponent,
    D12BallGame,
    GameMode,
    GameStatus,
    HomeChoice,
    Team,
)
from d12ball.prompts import (
    PendingPrompt,
    PromptKind,
    pending,
    pending_prompt,
)
from d12ball.wire import jsonable
from gamesaves.d12ball.storage import save_games


LOGGER = logging.getLogger(__name__)


#: How many of an answer's lines a frontend keeps for itself: `None` for
#: all of them, an index, or a callable asked with the `Answered` -- its
#: detail, its lines and what it hands on to. See `apply_action`.
CarryFrom = Union[None, int, Callable[[driver.Answered], Optional[int]]]


class StopHandling(Enum):
    """What a frontend does where the loop stopped for it."""

    #: Take the picture: the group carries the position as it stands.
    DRAW = auto()
    #: Post the lines plainly, with no picture.
    POST = auto()
    #: Nothing to show here after all: the lines carry on into the
    #: next step as its lead-in.
    CARRY = auto()


@dataclass(frozen=True)
class Batching:
    """
    The frontend's batching, in one object.

    `stop_after` and `own_message` are `driver.advance`'s parameters
    of the same names; `speaks_lines` too. `at_stop` is asked once
    per stop and answers what to do there. The default answers
    "draw", so a frontend with nothing to say gets a snapshot at every
    stop the model makes on its own (a new play).
    """

    stop_after: frozenset = frozenset()
    own_message: frozenset = frozenset()
    speaks_lines: frozenset = frozenset()

    def at_stop(
        self,
        stopped: FollowOn,
        result: StepResult,
        following: Optional[Union[PendingPrompt, FollowOn]],
    ) -> StopHandling:
        return StopHandling.DRAW

    def carry_answer(
        self,
        action: driver.Action,
        answered: driver.Answered,
    ) -> CarryFrom:
        """
        How much of an AI answer's lines are a group of their own, and
        how much carries on into the step that follows as its lead-in
        -- `apply_action`'s `carry_from`, asked of the frontend for
        the answers nobody clicked. The default keeps every line: an
        AI answer is a group of its own (decision 8 of
        docs/web-app.md). A frontend that composes a coach's answer
        into the next step's message answers the same for the AI's.
        """
        return None


@dataclass(frozen=True)
class Narration:
    """
    Lines that belong together, in the order they were said.

    `step` is the step that said them, `None` for lines the caller's
    own step said before the loop ran. `board` is the position where
    the frontend stopped to draw it, as `MatchState.to_dict()` at
    that moment, and `None` everywhere else. `new_play` and
    `board_changed` are the stopped step's own answers, for the
    picture: a new play's board is the one a frontend pins.

    Two more tags, for the AI's turn through the service: `prompt` is
    the question these lines opened, answered by the AI before anybody
    saw it -- the message a coach's prompt would have been, without
    the question -- and `action` is the AI's answer these lines are,
    with `detail` beside it where the answer had a picture's numbers.
    A frontend renders an answer the way its view renders a coach's,
    keyed on the action.
    """

    lines: tuple[str, ...]
    step: Optional[FollowOnStep] = None
    board: Optional[dict] = None
    new_play: bool = False
    board_changed: bool = False
    #: The step's own arguments, where a frontend's picture of the
    #: group depends on one -- the challenger the walk-in named.
    arguments: Mapping[str, Any] = field(default_factory=dict)
    prompt: Optional[PromptKind] = None
    action: Optional[driver.Action] = None
    detail: Optional[object] = None

    @property
    def drawn(self) -> bool:
        return self.board is not None

    def to_dict(self) -> dict:
        """
        One group as JSON -- `d12ball.wire`. The lines carry the
        model's tokens as they stand; a frontend renders them at its
        own door, the way the cog does (`D12Ball.rendered`).

        `board` is the position the frontend stopped to draw, as the
        save's own shape, so a web page renders the same picture the
        bot pins -- it is the one field here that is a whole match, and
        it is only ever set where the frontend asked to stop.
        """
        return {
            "lines": list(self.lines),
            "step": None if self.step is None else self.step.name,
            "board": self.board,
            "new_play": self.new_play,
            "board_changed": self.board_changed,
            "arguments": jsonable(dict(self.arguments)),
            "prompt": None if self.prompt is None else self.prompt.value,
            "action": None if self.action is None else self.action.to_dict(),
            "detail": jsonable(self.detail),
        }


@dataclass(frozen=True)
class GameResult:
    """
    What one call to the service did, for a frontend to render.

    - `answer`: the answer's own lines, where the call was an action
      -- separate from the groups because a Discord prompt is
      *replaced* by its answer, and a web page may do the same.
    - `groups`: every closed group and every stop, in order.
    - `narration`: what the run was still carrying when it stopped;
      it opens the prompt, or is the last thing said.
    - `prompt`: what the match is waiting on now, or `None` for a
      finished run with nothing to ask.
    - `board_changed`: whether anything a board draws moved since the
      last drawn group, so the frontend owes one write of its
      persistent board.
    - `detail`: a roll's numbers, for the picture of the dice.
    - `refusal` and `waiting_on`: why nothing happened, and what the
      match is actually waiting on, where the action was refused.
    - `match`: the position after the call, for a frontend that builds
      its next controls from it.
    """

    answer: tuple[str, ...] = ()
    groups: tuple[Narration, ...] = ()
    narration: tuple[str, ...] = ()
    prompt: Optional[PendingPrompt] = None
    board_changed: bool = False
    detail: Optional[object] = None
    refusal: Optional[str] = None
    waiting_on: Optional[PendingPrompt] = None
    match: Optional[MatchState] = None

    @property
    def refused(self) -> bool:
        return self.refusal is not None

    def to_dict(self, *, match: bool = False) -> dict:
        """
        What the call did, as JSON -- the shape a web frontend answers
        a request with (finding 10 of docs/web-app.md).

        **The position is left out unless it is asked for.** A result
        is what one *person* is shown, and the match holds what the
        game keeps from them: the other side's maneuver pick, a
        shootout order nobody has revealed yet. A frontend that hands
        the save to a browser has handed over both, which is a rule of
        the game broken by a serialiser -- so `match=True` is a
        deliberate word at the call site, for a caller with no second
        person to keep a secret from.
        """
        return {
            "answer": list(self.answer),
            "groups": [group.to_dict() for group in self.groups],
            "narration": list(self.narration),
            "prompt": None if self.prompt is None else self.prompt.to_dict(),
            "board_changed": self.board_changed,
            "detail": jsonable(self.detail),
            "refusal": self.refusal,
            "waiting_on": (
                None if self.waiting_on is None else self.waiting_on.to_dict()
            ),
            "match": (
                self.match.to_dict()
                if match and self.match is not None
                else None
            ),
        }


#: How many answers the AI may give in one run before the loop gives
#: up on it. A turn of the AI's is a dozen at most (its order in the
#: shootout is six of them, one name apiece); a strategy answering a
#: question that leaves the position unchanged would otherwise spin
#: here, and this is one process for every game at once.
MAX_AI_ANSWERS = 100

#: What a resumed Coaching Choice says above the allowance.
RESUME_COACHING_NOTE = (
    "Picking this up where it left off. Nothing you had already done "
    "has been undone."
)

#: What a resume says it found, by the step the bot owed -- the words
#: `/d12ball resume` reports back. A step `owed_step` can name and
#: this table does not is reported by its name, so a new member is
#: never silent.
OWED_STEP_NAMES: Mapping[FollowOnStep, str] = {
    FollowOnStep.ADVANCE_SETUP_STAGE: "the pre-kickoff Coaching Choice",
    FollowOnStep.ADVANCE_HALFTIME_STAGE: "halftime",
    FollowOnStep.ADVANCE_FULL_TIME_STAGE: (
        "the Coaching Choice before the shootout"
    ),
    FollowOnStep.FINISH_TIME_OUT: "the time out",
    FollowOnStep.CONTINUE_RUN_BACK: "the run back",
    FollowOnStep.BEGIN_BALL_RECOVERY: "the out-of-bounds pickup",
    FollowOnStep.RESOLVE_LOOSE_BALL: "the loose ball",
    FollowOnStep.BEGIN_EFFECT_RESOLUTION: "the maneuver's effect",
}


class GameService:
    """
    Load, apply, save once, return. See the module docstring.

    `games` is the live dict every frontend shares, and `save` is what
    writes it -- `save_games` by default, which never raises.
    """

    def __init__(
        self,
        engine: RulesEngine,
        games: dict[str, D12BallGame],
        batching: Batching = Batching(),
        save: Callable[[dict[str, D12BallGame]], None] = None,
    ) -> None:
        self.engine = engine
        self.games = games
        self.batching = batching
        self._save = save
        self.listeners: list[Callable[[D12BallGame, GameResult], None]] = []

    def announce(self, game: D12BallGame, result: GameResult) -> None:
        """
        Hand every result to whoever is watching this game, after the
        save and before the caller renders anything.

        **It is not a second presenter and it formats nothing.** It
        exists because a game is played from two sides and they need
        not be on the same frontend: a coach reading a web page has no
        interaction to be replied to when the other coach clicks a
        button in Discord, so the page's only way to see that turn is
        the result the service produced for it. A listener that raises
        would take somebody's click down with it, so each is called
        inside its own guard and a failure is the watcher's to log --
        see `webapp/server.py`, the one listener today.
        """
        for listener in self.listeners:
            try:
                listener(game, result)
            except Exception:  # pragma: no cover - a frontend's own bug
                LOGGER.exception(
                    "A listener failed on a result for game %s",
                    game.game_id,
                )

    # -- Loading and saving --------------------------------------------

    def game(self, game_id: str) -> D12BallGame:
        return self.games[game_id]

    def load(self, game: D12BallGame) -> MatchState:
        return self.engine.load_match_state(game)

    def persist(self, game: D12BallGame, match: MatchState) -> None:
        """
        Write the match back onto its game record and save.

        The two halves are one step: a save without the `to_dict`
        above it writes whatever the record was already carrying, so
        the file keeps a state the game has moved past, silently,
        until a restart reads it back.
        """
        game.match_state = match.to_dict()
        (self._save or save_games)(self.games)

    def save(self) -> None:
        """Save the game records alone, for a change to one that has
        no match to write -- a status, a tutorial flag."""
        (self._save or save_games)(self.games)

    def waiting_on(
        self, game: D12BallGame, match: MatchState,
    ) -> Optional[PendingPrompt]:
        """What the match asks of somebody, or `None` while the bot
        owes a step (`d12ball.prompts.owed_step`)."""
        return pending_prompt(self.engine, game, match)

    # -- Setup and the lobby ---------------------------------------------
    #
    # Each of these is load, one change to the record, save once. The
    # rules are `D12BallGame`'s -- who may join, what a tutorial pins,
    # which team the other side's pick rules out -- and it refuses with
    # `RuleRefusal`, which comes straight through: nothing was written.
    # What the AI or the coin adds is drawn here, from the engine and
    # its strategies, never by a frontend.

    def next_game_number(self, guild_id: Optional[int]) -> int:
        """The number after the last one given out where this game is
        played -- per server, and one sequence for the games played
        nowhere on Discord."""
        existing = [
            game.game_number
            for game in self.games.values()
            if game.guild_id == guild_id
        ]
        return max(existing, default=0) + 1

    def create_game(
        self,
        *,
        player_1_id: int,
        player_1_name: Optional[str],
        player_2_id: Optional[int] = None,
        player_2_name: Optional[str] = None,
        guild_id: Optional[int] = None,
        channel_id: Optional[int] = None,
        game_number: Optional[int] = None,
        in_lobby: bool = False,
        test_game: bool = False,
        tutorial: bool = False,
        mode: GameMode = GameMode.BASIC,
        advanced_maneuvers: bool = True,
        species_abilities: bool = True,
        board_size: int = 7,
        ai_opponent: Optional[AIOpponent] = None,
        game_name: Optional[str] = None,
    ) -> D12BallGame:
        """
        A new game record, in setup, saved.

        A lobby (`in_lobby`) settles nothing yet -- who takes the other
        side is Start Game's -- so it carries no AI opponent; anything
        else with no second player is a solo game against Dinky unless
        another AI was asked for. The settings arguments exist for the
        rematch, which carries the finished game's configuration over;
        a fresh game takes the defaults and settles them in setup. The
        Discord ids are the frontend's to pass or leave out: a game
        the web app creates has none.
        """
        if game_number is None:
            game_number = self.next_game_number(guild_id)
        game = D12BallGame(
            game_id=uuid.uuid4().hex,
            game_number=game_number,
            guild_id=guild_id,
            channel_id=channel_id,
            message_id=None,
            player_1_id=player_1_id,
            player_2_id=player_2_id,
            player_1_name=player_1_name,
            player_2_name=player_2_name,
            test_game=test_game,
            game_name=game_name,
            mode=mode,
            # Which halves of advanced mode this game plays. They mean
            # nothing in a basic game and are carried anyway, so a
            # rematch of a maneuvers-only game that flips to Advanced
            # in setup comes back as the game it is a rematch of.
            advanced_maneuvers=advanced_maneuvers,
            species_abilities=species_abilities,
            status=GameStatus.SETUP,
            board_size=board_size,
            ai_opponent=(
                None
                if in_lobby or player_2_id is not None
                else ai_opponent or AIOpponent.DINKY
            ),
            tutorial=tutorial,
            # The step is set at kickoff, not here: setup is played
            # exactly as an ordinary game plays it -- teams, the coin
            # toss, home or visiting -- and the script starts with the
            # first turn. `in_tutorial` is False until then, so nothing
            # in setup is on rails.
            tutorial_step=None,
            in_lobby=in_lobby,
        )
        self.games[game.game_id] = game
        self.save()
        return game

    def discard_game(self, game_id: str) -> None:
        """
        Forget a game that never got started -- a frontend that could
        not put its first message up has nothing to hand anybody. Only
        a game still in setup with no match may be discarded; anything
        played is abandoned, not erased.
        """
        game = self.game(game_id)
        if game.status != GameStatus.SETUP or game.match_state is not None:
            raise ValueError("Only a game that never started may be discarded.")
        del self.games[game_id]
        self.save()

    def lobby_join(
        self, game_id: str, user_id: int, user_name: Optional[str],
    ) -> D12BallGame:
        game = self.game(game_id)
        game.lobby_join(user_id, user_name)
        self.save()
        return game

    def lobby_observe(self, game_id: str, user_id: int) -> D12BallGame:
        game = self.game(game_id)
        game.lobby_observe(user_id)
        self.save()
        return game

    def lobby_leave(self, game_id: str, user_id: int) -> D12BallGame:
        game = self.game(game_id)
        game.lobby_leave(user_id)
        self.save()
        return game

    def configure(
        self, game_id: str, setting: str, value: object = None,
    ) -> D12BallGame:
        """One setting changed -- `D12BallGame.configure`, saved."""
        game = self.game(game_id)
        game.configure(setting, value)
        self.save()
        return game

    def start_lobby(self, game_id: str) -> D12BallGame:
        """Leave the lobby with the other side settled
        (`D12BallGame.start_lobby`); team selection follows."""
        game = self.game(game_id)
        game.start_lobby()
        self.save()
        return game

    def reopen_lobby(self, game_id: str) -> D12BallGame:
        """`start_lobby` undone, for a frontend that could not put the
        started game up."""
        game = self.game(game_id)
        game.reopen_lobby()
        self.save()
        return game

    def pick_team(
        self, game_id: str, player_number: int, team: Team,
    ) -> D12BallGame:
        """
        One side's team, and -- once Player 1 of a solo game has
        picked -- the AI's, drawn by its strategy from the pool the
        record leaves it. Saved.
        """
        game = self.game(game_id)
        game.pick_team(player_number, team)
        if player_number == 1 and game.is_solo_game:
            strategy = self.engine.get_ai_strategy(game)
            game.player_2_team = strategy.choose_team(game.ai_team_pool())
        self.save()
        return game

    def flip_coin(self, game_id: str, flipping_player_number: int) -> D12BallGame:
        """
        Throw the coin, record who won it, start the game -- and, in a
        solo game the AI won, take the AI's side for it and deal the
        match, so the coach's next prompt is the pre-kickoff Coaching
        Choice (`begin`) rather than a question the AI has already
        answered.

        The coin is read from the flipping coach's point of view, so
        it has to be flipped *as* somebody; which of the two changes
        nothing but the wording, since the coin is fair either way.
        The tutorial's script is written for a coach with the ball at
        kickoff, so Dinky takes the visiting side and leaves them home
        -- the record's rail (`D12BallGame.home_choice_rail`), which
        is the same reading the coach's own Home button is railed by.

        """
        game = self.game(game_id)
        if game.in_lobby or not game.teams_selected:
            raise RuleRefusal(
                "Both teams must be picked before the coin is flipped."
            )
        winner = game.resolve_coin_toss(
            flipping_player_number, self.engine.flip_coin(),
        )
        game.coin_winner = format_player(game, winner)
        game.start_game()

        if game.is_solo_game and winner == 2:
            choice = (
                game.home_choice_rail(2)
                or self.engine.get_ai_strategy(game).choose_home_or_visiting()
            )
            game.choose_home_or_visiting(2, choice)

            self.engine.initialize_standard_match(game)
        self.save()
        return game

    def choose_home_or_visiting(
        self, game_id: str, player_number: int, choice: HomeChoice,
    ) -> D12BallGame:
        """The coin-toss winner's choice, and the deal that follows
        it. Saved; `begin` opens the pre-kickoff window next."""
        game = self.game(game_id)
        game.choose_home_or_visiting(player_number, HomeChoice(choice))
        self.engine.initialize_standard_match(game)
        self.save()
        return game

    # -- The entry points -----------------------------------------------

    def apply_action(
        self,
        game_id: str,
        action: driver.Action,
        *,
        carry_from: CarryFrom = None,
    ) -> GameResult:
        """
        Answer the question this match is waiting on and run what
        follows; save once; return what happened.

        A `Refusal` comes back as a result with `refusal` set and
        nothing else changed -- the match was not written.

        **`carry_from` is the frontend's batching of the answer's own
        lines** (principle 8). `None` keeps every one of them out of
        the run and hands them back as `answer`, for a frontend that
        replaces the prompt with them. An index `k` hands back the
        first `k` and carries the rest into the first step of the
        chain as its lead-in, where the step composes them into its
        own text -- which is how "a resolved maneuver is one message"
        is written, and why the presenter cannot do it afterwards. A
        callable is asked with the `Answered` itself, for the rolls
        whose split depends on what was rolled and the turn action
        whose depends on where it hands on to.
        """
        game = self.game(game_id)
        match = self.load(game)
        answered = driver.answer(self.engine, game, match, action)
        if isinstance(answered, driver.Refusal):
            return GameResult(
                refusal=answered.reason,
                waiting_on=answered.waiting_on,
                match=match,
            )
        own = answered.result
        split = carry_from
        if callable(split):
            split = split(answered)
        if split is None:
            kept, carried = own.narration, []
        else:
            kept, carried = own.narration[:split], own.narration[split:]
        return self.run(
            game,
            match,
            StepResult(
                narration=list(carried),
                board_changed=own.board_changed,
                next=own.next,
            ),
            answer=kept,
            detail=answered.detail,
        )

    def run_step(
        self,
        game_id: str,
        step: FollowOnStep,
    ) -> GameResult:
        """Run one step by name and everything it starts."""
        game = self.game(game_id)
        match = self.load(game)
        return self.run(game, match, StepResult(next=FollowOn(step)))

    def begin(self, game_id: str) -> GameResult:
        """
        Open the pre-kickoff Coaching Choice once setup has settled
        the teams and the sides -- the first thing a game runs.
        """
        game = self.game(game_id)
        match = self.load(game)
        return self.run(
            game,
            match,
            periods.begin_setup_coaching(self.engine, game, match),
            carry=False,
        )

    def resume(self, game_id: str) -> tuple[str, GameResult]:
        """
        Put a game back in front of whoever it is waiting on, running
        the step the bot itself owes where the next step was nobody's
        click. Returns what it was waiting on, in words, and the
        result.

        **The reading is `d12ball.prompts.owed_step`'s**, the same
        chain `pending_prompt` reads and `driver.answer` refuses
        against, so a resume cannot come to run a different step from
        the one a click is refused for. This used to be a ladder of
        its own -- nine flags in an order of its own, each handed to a
        flow function by name -- which was the second copy of "what is
        this match waiting on" principle 3 in CLAUDE.md is against,
        moved out of the cog and not yet gone. Where nothing is owed
        the result is the prompt and nothing runs; an open Coaching
        Choice comes back with a note above the allowance saying so.
        """
        game = self.game(game_id)
        match = self.load(game)
        engine = self.engine

        waiting = pending(engine, game, match)
        if isinstance(waiting, FollowOn):
            return (
                OWED_STEP_NAMES.get(waiting.step, waiting.step.name),
                self.run(game, match, StepResult(next=waiting)),
            )

        prompt = waiting
        if driver.ai_action(engine, game, match, prompt) is not None:
            # The AI's question, which a restart interrupted before
            # the service answered it: run it on, as the loop would
            # have.
            return "the AI's choice", self.run(
                game, match, StepResult(next=prompt),
            )
        if prompt.kind is PromptKind.TUTORIAL_CONTINUE:
            return "a tutorial note, re-posted above", self._prompt(
                game, match, prompt,
            )
        if prompt.kind in (PromptKind.COACHING_HUB, PromptKind.COACHING_OFFER):
            side = TeamSide(match.pending_coaching_side)
            return "the open Coaching Choice", self._prompt(
                game,
                match,
                replace(
                    prompt,
                    ask=engine.coaching_prompt(
                        game, match, side, RESUME_COACHING_NOTE,
                    ),
                ),
            )
        return "a choice, re-posted above", self._prompt(game, match, prompt)

    def reset_turn(self, game_id: str) -> GameResult:
        """
        Throw the current turn away and ask the offense to choose
        again -- the recovery command's `force`, for a position that
        no longer hangs together. Refused where the position is not a
        turn at all (`RulesEngine.turn_reset_refusal`): setup,
        halftime, the shootout and a time out are walked on by
        `resume` instead.

        `reset_maneuver` clears the whole turn -- ball handler,
        maneuver picks, run back, loose ball, kickoff fill, the
        out-of-bounds pickup -- and the coaching window is closed
        separately because it is not part of a turn.
        """
        game = self.game(game_id)
        match = self.load(game)
        refusal = self.engine.turn_reset_refusal(match)
        if refusal is not None:
            return GameResult(refusal=refusal, match=match)
        match.reset_maneuver()
        match.close_coaching_window()
        return self.run(
            game,
            match,
            StepResult(
                board_changed=True,
                next=FollowOn(FollowOnStep.SEND_TURN_PROMPT),
            ),
        )

    def _prompt(
        self,
        game: D12BallGame,
        match: MatchState,
        prompt: PendingPrompt,
    ) -> GameResult:
        """The prompt the match is waiting on, and nothing run -- told
        to whoever is watching, as every result is."""
        result = GameResult(prompt=prompt, match=match)
        self.announce(game, result)
        return result

    # -- The loop --------------------------------------------------------

    def run(
        self,
        game: D12BallGame,
        match: MatchState,
        result: StepResult,
        *,
        answer: Sequence[str] = (),
        detail: Optional[object] = None,
        carry: bool = True,
    ) -> GameResult:
        """
        Run the chain `result` starts until only a frontend can carry
        on, through every stop the frontend asked for, then save once.

        `carry` says the caller's own lines open the next step as its
        lead-in, which is how a resolved maneuver is one message. A
        caller whose lines are events of their own -- the whistle and
        the run of separate messages behind it -- passes `False`, and
        they come back as the first group, tagged with no step. A
        follow-on in `speaks_lines` takes them either way: they are
        the content of its own message.
        """
        batching = self.batching
        groups: list[Narration] = []
        board_changed = False

        if not carry and result.narration and not (
            isinstance(result.next, FollowOn)
            and result.next.step in batching.speaks_lines
        ):
            groups.append(Narration(tuple(result.narration)))
            result = StepResult(
                board_changed=result.board_changed,
                next=result.next,
                new_play=result.new_play,
            )

        narration: tuple[str, ...] = ()
        prompt: Optional[PendingPrompt] = None
        ai_answers = 0
        while True:
            run = driver.advance(
                self.engine,
                game,
                match,
                result,
                stop_after=batching.stop_after,
                own_message=batching.own_message,
                speaks_lines=batching.speaks_lines,
            )
            groups.extend(
                Narration(group.narration, group.step, arguments=group.arguments)
                for group in run.groups
            )
            board_changed = board_changed or run.board_changed
            following = run.result.next
            stopped = run.stopped_on

            if stopped is None:
                if isinstance(following, PendingPrompt):
                    action = driver.ai_action(
                        self.engine, game, match, following,
                    )
                    if action is not None:
                        ai_answers += 1
                        if ai_answers > MAX_AI_ANSWERS:
                            raise RuntimeError(
                                f"The AI has answered {MAX_AI_ANSWERS} "
                                f"questions in one run of game "
                                f"{game.game_id} and is still being "
                                f"asked ({following.kind.name}); giving "
                                "up on it."
                            )
                        result = self._answer_for_ai(
                            game, match, following, action, run, groups,
                        )
                        continue
                narration = tuple(run.result.narration)
                if isinstance(following, PendingPrompt):
                    prompt = following
                break

            handling = batching.at_stop(stopped, run.result, following)
            if handling is StopHandling.CARRY:
                result = StepResult(
                    narration=list(run.result.narration), next=following,
                )
            else:
                drawn = handling is StopHandling.DRAW
                groups.append(
                    Narration(
                        tuple(run.result.narration),
                        stopped.step,
                        board=match.to_dict() if drawn else None,
                        new_play=run.result.new_play,
                        board_changed=run.result.board_changed,
                        arguments=stopped.kwargs,
                    ),
                )
                if drawn:
                    # The picture wrote the board; what is owed from
                    # here is whatever moves after it.
                    board_changed = False
                result = StepResult(next=following)
            if following is None:
                break

        self.persist(game, match)
        result = GameResult(
            answer=tuple(answer),
            groups=tuple(groups),
            narration=narration,
            prompt=prompt,
            board_changed=board_changed,
            detail=detail,
            match=match,
        )
        self.announce(game, result)
        return result

    def _answer_for_ai(
        self,
        game: D12BallGame,
        match: MatchState,
        prompt: PendingPrompt,
        action: driver.Action,
        run: driver.DriverRun,
        groups: list[Narration],
    ) -> StepResult:
        """
        Answer `prompt` for the AI and hand back the result the loop
        carries on from.

        The answer goes through `driver.answer` -- the same check
        against the question and the position a click gets -- and a
        refusal is a bug in the strategy, raised as one: the prompt
        offered what it offered, and the strategy read the offer.
        Its own lines are split by the frontend's `carry_answer`, as
        a view splits a coach's with `carry_from`: what is kept is a
        group tagged with the action, what is carried opens the next
        step as its lead-in.

        **What was said before the question closes as a group tagged
        with the prompt** -- what a coach's prompt message would have
        opened with, said whether or not anybody is asked. **One
        exception, for the cascade.** Where the answer carries whole
        (`0`) it is a continuation of what led to the question rather
        than an event of its own, so the group the loop had just
        closed after the step that asked -- if it was that step's own,
        and not a picture -- is taken back and carried in front of
        it: the run back closes a message before each question it
        puts, and the AI's placement belongs in that message, not
        after it, composed by `CONTINUE_RUN_BACK` like the forced
        placements around it. That is how an AI side's run back stays
        one message and one board refresh, which
        docs/design/rate-limits.md requires of a cascade.

        An answer that hands on to nothing (the maneuver pick with
        the other side still to choose, a hub note) leaves the loop
        to re-read the position, as the frontend would have.
        """
        reached = run.result
        answered = driver.answer(self.engine, game, match, action)
        if isinstance(answered, driver.Refusal):
            raise RuntimeError(
                f"The AI's answer to {prompt.kind.name} was refused: "
                f"{answered.reason} ({action})"
            )
        own = answered.result
        split = self.batching.carry_answer(action, answered)
        if callable(split):
            split = split(answered)

        lead: list[str] = []
        asked_by = run.steps[-1] if run.steps else None
        if (
            split == 0
            and groups
            and run.groups
            and asked_by is not None
            and groups[-1].step is asked_by
            and not groups[-1].drawn
        ):
            lead.extend(groups.pop().lines)
        if reached.narration:
            groups.append(
                Narration(tuple(reached.narration), prompt=prompt.kind),
            )

        if split is None:
            kept, carried = own.narration, []
        else:
            kept, carried = own.narration[:split], own.narration[split:]
        if kept:
            groups.append(
                Narration(
                    tuple(kept), action=action, detail=answered.detail,
                ),
            )
        following = own.next
        if following is None:
            following = pending(self.engine, game, match)
        return StepResult(
            narration=lead + list(carried),
            board_changed=own.board_changed,
            next=following,
            new_play=own.new_play,
        )
