"""
`GameService`: the one door for a change to a Codex game -- copied from
`gamesaves/d12ball/service.py` (docs/codex-bot.md, decision 2), whose
docstrings tell why each piece is the shape it is
(docs/design/game-service.md).

A frontend authorises the person, turns what they did into an `Action`,
and calls `apply_action`. The service loads the match, runs the action
and everything it starts through `codex.flow.driver`, **saves once**,
and hands back a `GameResult` the frontend renders. It formats nothing.

**The lobby is service methods, not prompt kinds**: `create_game`,
`take_seat`, `set_mode`, `choose_deck`, `leave`, `start`, `abandon`, `set_board_layout`, and after
a game `rematch` and `keep_heroes`, each
load the record, apply one change the record itself rules on
(`CodexGame`, which refuses with `RuleRefusal`), and save once. A
refusal is the exception itself: nothing was written.

What differs from D12 Ball's:

- **An action goes through `driver.apply`, never `driver.answer`.**
  `apply` is where the journal -- what undo is made of -- is written
  (docs/design/codex.md, "Undo's groundwork"), so the service may not
  split the answer from what follows it -- there is no `carry_from`,
  and **an action's run is never stopped part-way**: a stop would cut
  what the journal records as one action in two. `Batching.stop_after`
  is honoured where the bot runs its own steps (`start`, `resume`).
- **The result carries the standing prompts** -- the tech choice the
  other player may answer meanwhile (decision 8) -- beside the one the
  match is waiting on.
- **No AI** (decision 13), so no carry for its answers.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional, Union

from codex import history
from codex.components import MatchState
from codex.engine import RulesEngine
from codex.flow import driver, turn
from codex.flow.result import FollowOn, FollowOnStep, Headline, StepResult
from codex.game import CodexGame, GameStatus, RuleRefusal
from codex.prompts import PendingPrompt, pending, pending_prompt, standing_prompts, tech_stands
from codex.wire import jsonable
from gamekit.service import StopHandling
from gamesaves.codex.storage import save_games


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class Batching:
    """
    The frontend's batching, in one object (`gamesaves.d12ball.service`).
    `own_message` closes a group after a step; `stop_after` stops the
    bot's own run there, and `at_stop` says what to do at a stop.
    """

    stop_after: frozenset = frozenset()
    own_message: frozenset = frozenset()
    #: Close a group after these steps with the position as it stood
    #: there (`driver.advance`'s `draw_after`), without stopping.
    draw_after: frozenset = frozenset()

    def at_stop(
        self,
        stopped: FollowOn,
        result: StepResult,
        following: Optional[Union[PendingPrompt, FollowOn]],
    ) -> StopHandling:
        return StopHandling.DRAW


@dataclass(frozen=True)
class Narration:
    """
    Lines that belong together, in the order they were said, and the
    step that said them (`None` for the action's own). `board` is the
    position where the frontend stopped to draw, as `to_dict()`, and
    `None` everywhere else.
    """

    lines: tuple[str, ...]
    step: Optional[FollowOnStep] = None
    board: Optional[dict] = None
    new_play: bool = False
    board_changed: bool = False
    arguments: Mapping[str, Any] = field(default_factory=dict)
    headlines: tuple[Headline, ...] = ()

    @property
    def drawn(self) -> bool:
        return self.board is not None

    def to_dict(self) -> dict:
        return {
            "lines": list(self.lines),
            "step": None if self.step is None else self.step.name,
            "board": self.board,
            "new_play": self.new_play,
            "board_changed": self.board_changed,
            "arguments": jsonable(dict(self.arguments)),
            "headlines": [one.to_dict() for one in self.headlines],
        }


@dataclass(frozen=True)
class GameResult:
    """
    What one call to the service did, for a frontend to render.

    - `groups`: every closed group and every stop, in order.
    - `narration`: what the run was still carrying when it stopped.
    - `prompt`: what the match is waiting on now -- the active player's
      question -- or `None` while nothing is asked.
    - `standing`: what the other player may answer meanwhile (the tech
      choice). **Each is its asked player's alone**: a tech prompt
      lists their codex, so a frontend shows it to them and nobody else.
    - `board_changed`: whether anything a board draws moved since the
      last drawn group.
    - `refusal`, `cite` and `waiting_on`: why nothing happened, what it
      cites, and what the match is actually waiting on.
    - `match`: the position after the call.
    """

    groups: tuple[Narration, ...] = ()
    narration: tuple[str, ...] = ()
    prompt: Optional[PendingPrompt] = None
    standing: tuple[PendingPrompt, ...] = ()
    board_changed: bool = False
    refusal: Optional[str] = None
    cite: Optional[str] = None
    waiting_on: Optional[PendingPrompt] = None
    match: Optional[MatchState] = None
    headlines: tuple[Headline, ...] = ()

    @property
    def refused(self) -> bool:
        return self.refusal is not None

    @property
    def lines(self) -> tuple[str, ...]:
        """Every line the call said, in order -- the groups', then what
        the run was still carrying."""
        said = [line for group in self.groups for line in group.lines]
        return tuple(line for line in (*said, *self.narration) if line)

    def to_dict(self) -> dict:
        """
        What the call did, as JSON -- `codex.wire`. **No prompt is
        written here**, the active one or a standing one: each lists a
        hand or a codex, which is its asked player's alone, and a
        result is shown to everybody. A frontend sends a prompt to its
        asked player through its own door. The position is left out
        for the same reason.
        """
        return {
            "groups": [group.to_dict() for group in self.groups],
            "narration": list(self.narration),
            "board_changed": self.board_changed,
            "refusal": self.refusal,
            "cite": self.cite,
            "headlines": [one.to_dict() for one in self.headlines],
        }


#: What a resume says it found, by the step the bot owed.
OWED_STEP_NAMES: Mapping[FollowOnStep, str] = {
    FollowOnStep.BEGIN_TURN: "the start of the turn",
    FollowOnStep.DRAW_PHASE: "the draw",
    FollowOnStep.BEGIN_TECH: "the end of the turn",
}


class GameService:
    """
    Load, apply, save once, return. See the module docstring.

    `games` is the live dict the frontend shares, and `save` is what
    writes it -- `save_games` by default, which never raises.
    """

    def __init__(
        self,
        engine: RulesEngine,
        games: dict[str, CodexGame],
        batching: Batching = Batching(),
        save: Optional[Callable[[dict[str, CodexGame]], None]] = None,
    ) -> None:
        self.engine = engine
        self.games = games
        self.batching = batching
        self._save = save
        #: Whoever else is watching a game's results -- a later web
        #: client (`gamesaves.d12ball.service.GameService.announce`).
        self.listeners: list[Callable[[CodexGame, GameResult], None]] = []

    def announce(self, game: CodexGame, result: GameResult) -> None:
        """Hand every result to whoever is watching, after the save;
        a listener that raises is logged, never the click's."""
        for listener in self.listeners:
            try:
                listener(game, result)
            except Exception:  # pragma: no cover - a frontend's own bug
                LOGGER.exception("A listener failed on a result for Codex game %s", game.game_id)

    # -- Loading and saving --------------------------------------------

    def game(self, game_id: str) -> CodexGame:
        return self.games[game_id]

    def load(self, game: CodexGame) -> MatchState:
        """The game's match, checked against itself (`MatchState.validate`)."""
        if game.match_state is None:
            raise RuleRefusal("This game has not started yet.")
        match = MatchState.from_dict(game.match_state)
        match.validate(self.engine.catalog)
        return match

    def persist(self, game: CodexGame, match: MatchState) -> None:
        """Write the match back onto its record and save -- one step,
        or the file keeps a state the game has moved past. A match with
        a winner finishes its record in the same save (`CodexGame.finish`),
        however it ended: a destroyed base or a concession."""
        game.match_state = match.to_dict()
        if match.winner is not None:
            game.finish()
        (self._save or save_games)(self.games)

    def save(self) -> None:
        """Save the records alone, for a change with no match to write."""
        (self._save or save_games)(self.games)

    def waiting_on(self, game: CodexGame, match: MatchState) -> Optional[PendingPrompt]:
        """What the match asks of somebody, or `None` while the bot owes
        a step."""
        return pending_prompt(self.engine, game, match)

    def standing(self, game: CodexGame, match: MatchState) -> tuple[PendingPrompt, ...]:
        return standing_prompts(self.engine, match, game)

    # -- The lobby -------------------------------------------------------

    def next_game_number(self, guild_id: Optional[int]) -> int:
        """The number after the last one given out in this server."""
        existing = [game.game_number for game in self.games.values() if game.guild_id == guild_id]
        return max(existing, default=0) + 1

    def create_game(
        self,
        *,
        guild_id: Optional[int] = None,
        channel_id: Optional[int] = None,
        game_number: Optional[int] = None,
        test_game: bool = False,
    ) -> CodexGame:
        """A new lobby, with nobody seated, saved."""
        if game_number is None:
            game_number = self.next_game_number(guild_id)
        game = CodexGame(
            game_id=uuid.uuid4().hex,
            game_number=game_number,
            guild_id=guild_id,
            channel_id=channel_id,
            test_game=test_game,
        )
        self.games[game.game_id] = game
        self.save()
        return game

    def discard_game(self, game_id: str) -> None:
        """Forget a lobby whose message could not be put up. Only a game
        that never started may be discarded; anything played is
        abandoned."""
        game = self.game(game_id)
        if game.status is not GameStatus.LOBBY or game.match_state is not None:
            raise ValueError("Only a game that never started may be discarded.")
        del self.games[game_id]
        self.save()

    def take_seat(self, game_id: str, user_id: int, user_name: Optional[str], specs,
                  seat: Optional[int] = None) -> CodexGame:
        """Sit down with these heroes (`CodexGame.take_seat`), saved."""
        game = self.game(game_id)
        game.take_seat(user_id, user_name, specs, seat)
        self.save()
        return game

    def set_mode(self, game_id: str, mode: str) -> CodexGame:
        """The basic game or the standard one (`CodexGame.set_mode`),
        saved."""
        game = self.game(game_id)
        game.set_mode(mode)
        self.save()
        return game

    def choose_deck(self, game_id: str, user_id: int, color: str,
                    seat: Optional[int] = None) -> CodexGame:
        """A seat's starting deck, where its heroes' colours differ
        (`CodexGame.choose_deck`), saved."""
        game = self.game(game_id)
        game.choose_deck(user_id, color, seat)
        self.save()
        return game

    def leave(self, game_id: str, user_id: int) -> CodexGame:
        game = self.game(game_id)
        game.leave(user_id)
        self.save()
        return game

    def abandon(self, game_id: str) -> CodexGame:
        game = self.game(game_id)
        game.abandon()
        self.save()
        return game

    def drop_games(self, game_ids) -> None:
        """Forget these games, played or not, in one save -- the test
        server's reset (`/codex admin reset_channels`) and nothing else:
        a real game is abandoned, so its record and its number stay."""
        for game_id in game_ids:
            self.games.pop(game_id, None)
        self.save()

    # -- The end -----------------------------------------------------------

    def concede(self, game_id: str, seat: int) -> GameResult:
        """
        `seat` gives the game up (`codex.flow.turn.concede`): the match
        and its record finished in one save, and the result waiting on
        `GAME_OVER`, as a destroyed base's is. Who may concede for
        which seat is the frontend's: the clicker's own side alone.
        Refused with `RuleRefusal` once the game is over.
        """
        game = self.game(game_id)
        match = self.load(game)
        conceded = turn.concede(self.engine, game, match, seat)
        self.persist(game, match)
        result = GameResult(
            narration=tuple(conceded.narration),
            prompt=conceded.next if isinstance(conceded.next, PendingPrompt) else None,
            board_changed=True,
            match=match,
            headlines=conceded.headlines,
        )
        self.announce(game, result)
        return result

    def rematch(self, game_id: str) -> CodexGame:
        """
        A finished game played again: a new lobby with the same two
        seats, the heroes swapped (`CodexGame.rematch`), in the same
        channel -- remembered on the finished game, so a second press
        finds it rather than opening another. Saved once.
        """
        game = self.game(game_id)
        existing = self.games.get(game.rematch_game_id) if game.rematch_game_id else None
        if existing is not None:
            return existing
        rematch = game.rematch(uuid.uuid4().hex, self.next_game_number(game.guild_id))
        self.games[rematch.game_id] = rematch
        game.rematch_game_id = rematch.game_id
        self.save()
        return rematch

    def keep_heroes(self, game_id: str, user_id: int) -> CodexGame:
        """Keep heroes in a rematch's lobby (`CodexGame.keep_heroes`),
        saved."""
        game = self.game(game_id)
        game.keep_heroes(user_id)
        self.save()
        return game

    def set_board_layout(self, game_id: str, layout: str) -> CodexGame:
        """Swap view: a change to the record, saved."""
        game = self.game(game_id)
        game.set_board_layout(layout)
        self.save()
        return game

    def start(self, game_id: str) -> GameResult:
        """
        Start the game: the record deals the opening position
        (`CodexGame.start`, refused until both seats are taken), and the
        first turn's ready phase and upkeep run, as the bot owes them --
        saved once, after both.
        """
        game = self.game(game_id)
        game.start(self.engine)
        match = self.load(game)
        return self.run(game, match, StepResult(board_changed=True, next=pending(self.engine, game, match)))

    # -- A turn ------------------------------------------------------------

    def apply_action(self, game_id: str, action: driver.Action) -> GameResult:
        """
        Answer the question this match is waiting on -- the active
        player's, or a standing tech choice -- and run what follows,
        through `driver.apply`; save once; return what happened. A
        `Refusal` comes back as a result with `refusal` set, and the
        match is not written.
        """
        game = self.game(game_id)
        match = self.load(game)
        applied = driver.apply(
            self.engine, game, match, action,
            own_message=self.batching.own_message, draw_after=self.batching.draw_after,
        )
        if isinstance(applied, driver.Refusal):
            return GameResult(
                refusal=applied.reason,
                cite=applied.cite,
                waiting_on=applied.waiting_on,
                match=match,
            )
        self.persist(game, match)
        following = applied.result.next
        result = GameResult(
            groups=tuple(
                Narration(group.narration, group.step, board=group.board,
                          arguments=group.arguments, headlines=group.headlines)
                for group in applied.groups
            ),
            narration=tuple(applied.result.narration),
            prompt=following if isinstance(following, PendingPrompt) else None,
            standing=self.standing(game, match),
            board_changed=applied.board_changed,
            match=match,
            headlines=applied.result.headlines,
        )
        self.announce(game, result)
        return result

    def resume(self, game_id: str) -> tuple[str, GameResult]:
        """
        Put a game back in front of whoever it is waiting on, running the
        step the bot owes where there is one. Returns what it found, in
        words, and the result. **The reading is `owed_step`'s** -- the
        chain `driver.answer` refuses against -- so a resume cannot run
        a different step from the one a click is refused for.
        """
        game = self.game(game_id)
        match = self.load(game)
        waiting = pending(self.engine, game, match)
        if isinstance(waiting, FollowOn):
            return (
                OWED_STEP_NAMES.get(waiting.step, waiting.step.name),
                self.run(game, match, StepResult(next=waiting)),
            )
        result = GameResult(
            prompt=waiting, standing=self.standing(game, match), match=match,
        )
        self.announce(game, result)
        return "a choice, put back up", result

    # -- The undos --------------------------------------------------------

    def undo_targets(self, game_id: str) -> dict[str, int]:
        """The undos open on this game's position, each with the turn it
        goes back to (`history.undo_targets`) -- the one reading a
        frontend builds its Undo choices from, with `undo_points`."""
        return history.undo_targets(self.load(self.game(game_id)))

    def undo_points(self, game_id: str) -> tuple[history.UndoPoint, ...]:
        """The points of this turn the fine undo may go back to
        (`history.undo_points`), oldest first, each with what the action
        there said -- the one reading a frontend builds its menu from."""
        game = self.game(game_id)
        return history.undo_points(self.engine, game, self.load(game))

    def undo_to(self, game_id: str, index: int, *, of: Optional[int] = None) -> GameResult:
        """Put the match back to before one of this turn's actions -- a
        point `undo_points` offered, by its `index`, and `of` the
        journal's length then -- save once, and return the turn as it
        now reads: the kept actions' lines, then the undone line. Refused
        with `RuleRefusal` for a point not offered or a turn that has
        moved on. Who may ask is the frontend's: the active player, with
        nobody's consent, as for the start of the turn."""
        game = self.game(game_id)
        return self._undo(
            game_id, lambda match: history.undo_to(self.engine, game, match, index, of=of),
            restarts_tech=False,
        )

    def undo_to_turn_start(self, game_id: str) -> GameResult:
        """Put the match back to the start of this turn's main phase,
        save once, and return what it is waiting on now. Refused with
        `RuleRefusal` where there is no such start. Who may ask is the
        frontend's: the active player, with nobody's consent."""
        return self._undo(game_id, history.undo_to_turn_start)

    def undo_to_previous_turn(self, game_id: str) -> GameResult:
        """Put the match back to the start of the previous turn's main
        phase, unwinding the opponent's turn too -- so a frontend has
        the opponent (or a helper) agree before it calls this."""
        return self._undo(game_id, history.undo_to_previous_turn)

    def _undo(self, game_id: str, undo: Callable[[MatchState], tuple[str, ...]],
              *, restarts_tech: bool = True) -> GameResult:
        """One undo: `undo` changes the match and returns what it says,
        which the result carries as its narration -- for the fine undo
        the kept actions' lines before the undone line, so a frontend's
        record of the turn is `result.lines` after the turn's first
        lines, whichever undo it was. `restarts_tech` is the snapshot
        undos', which start every tech choice over; the fine undo keeps
        the other player's (`history.cut`), so it says nothing to them."""
        game = self.game(game_id)
        match = self.load(game)
        said = undo(match)
        self.persist(game, match)
        # The tech choices the undo started over, said only where a
        # choice stands through the other player's turn: in a test game
        # it is made in its owner's ready phase (`tech_stands`).
        again = ()
        if restarts_tech and tech_stands(game):
            again = tuple(history.tech_again(seat) for seat in history.tech_started_over(match))
        result = GameResult(
            narration=(*said, *again),
            prompt=self.waiting_on(game, match),
            standing=self.standing(game, match),
            board_changed=True,
            match=match,
        )
        self.announce(game, result)
        return result

    # -- The loop --------------------------------------------------------

    def run(self, game: CodexGame, match: MatchState, result: StepResult) -> GameResult:
        """
        Run the chain `result` starts until only somebody's answer can
        carry on, through every stop the frontend asked for, then save
        once. The bot's own steps, never an action (see the module
        docstring), so nothing here is journalled.
        """
        batching = self.batching
        groups: list[Narration] = []
        board_changed = False
        narration: tuple[str, ...] = ()
        headlines: tuple[Headline, ...] = ()
        prompt: Optional[PendingPrompt] = None
        while True:
            ran = driver.advance(
                self.engine, game, match, result,
                stop_after=batching.stop_after,
                own_message=batching.own_message,
                draw_after=batching.draw_after,
            )
            groups.extend(
                Narration(group.narration, group.step, board=group.board,
                          arguments=group.arguments, headlines=group.headlines)
                for group in ran.groups
            )
            board_changed = board_changed or ran.board_changed
            following = ran.result.next
            stopped = ran.stopped_on
            if stopped is None:
                narration = tuple(ran.result.narration)
                headlines = ran.result.headlines
                if isinstance(following, PendingPrompt):
                    prompt = following
                break
            handling = batching.at_stop(stopped, ran.result, following)
            if handling is StopHandling.CARRY:
                result = StepResult(
                    narration=list(ran.result.narration), next=following,
                    headlines=ran.result.headlines,
                )
            else:
                drawn = handling is StopHandling.DRAW
                groups.append(Narration(
                    tuple(ran.result.narration),
                    stopped.step,
                    board=match.to_dict() if drawn else None,
                    new_play=ran.result.new_play,
                    board_changed=ran.result.board_changed,
                    arguments=stopped.kwargs,
                    headlines=ran.result.headlines,
                ))
                if drawn:
                    board_changed = False
                result = StepResult(next=following)
            if following is None:
                break

        self.persist(game, match)
        outcome = GameResult(
            groups=tuple(groups),
            narration=narration,
            prompt=prompt,
            standing=self.standing(game, match),
            board_changed=board_changed,
            match=match,
            headlines=headlines,
        )
        self.announce(game, outcome)
        return outcome
