"""
`GameService`: the one door for a change to a TNP game -- copied from
`gamesaves/codex/service.py` (docs/tnp-bot.md, decision 3), whose
docstrings tell why each piece is the shape it is
(docs/design/game-service.md).

A frontend authorises the person, turns what they did into an `Action`
-- naming the seat it is for, which a simultaneous phase's answers must
-- and calls `apply_action`. The service loads the match, runs the
action and everything it starts through `tnp.flow.driver.apply`,
**saves once**, and hands back a `GameResult` the frontend renders. It
formats nothing.

**The lobby is service methods, not prompt kinds**: `create_game`,
`take_seat`, `leave`, `set_advanced`, `start` and `abandon`, each
loading the record, applying one change the record itself rules on
(`TnpGame`, which refuses with `RuleRefusal`), and saving once.

What differs from Codex's:

- **Two seats may be asked at once** (decision 7): `GameResult.prompts`
  lists every question open now, one a seat in a simultaneous phase,
  and **each is its asked seat's alone** -- a plan prompt carries the
  seat's saved plan and its units -- so `to_dict` writes none of them.
- No journal, no undo, no AI (decisions 1 and 10).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Callable, Mapping, Optional

from gamesaves.tnp.storage import save_games
from tnp.components import MatchState
from tnp.engine import RulesEngine
from tnp.flow import driver
from tnp.flow.result import FollowOn, FollowOnStep, StepResult
from tnp.game import GameStatus, RuleRefusal, TnpGame
from tnp.prompts import PendingPrompt, pending_all, pending_prompts
from tnp.wire import jsonable


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class Batching:
    """The frontend's batching (`gamesaves.codex.service.Batching`):
    `own_message` closes a group after a step; `stop_after` stops a run
    there. Step 6 names March's attacks; step 7 the battle's rounds."""

    stop_after: frozenset = frozenset()
    own_message: frozenset = frozenset()


@dataclass(frozen=True)
class Narration:
    """Lines that belong together, and the step that said them (`None`
    for the action's own)."""

    lines: tuple[str, ...]
    step: Optional[FollowOnStep] = None

    def to_dict(self) -> dict:
        return {"lines": list(self.lines), "step": None if self.step is None else self.step.name}


@dataclass(frozen=True)
class GameResult:
    """
    What one call to the service did, for a frontend to render.

    - `groups`: every closed group, in order; `narration` what the run
      was still carrying when it stopped.
    - `prompts`: every question open now -- both seats' in a
      simultaneous phase, one seat's in a battle or in March, none while
      the bot owes a step or the game is over. **Each is its asked
      seat's alone.**
    - `board_changed`: whether anything a picture draws moved.
    - `refusal`, `cite` and `waiting_on`: why nothing happened, what it
      cites, and what the match is actually waiting on.
    - `match`: the position after the call.
    """

    groups: tuple[Narration, ...] = ()
    narration: tuple[str, ...] = ()
    prompts: tuple[PendingPrompt, ...] = ()
    board_changed: bool = False
    refusal: Optional[str] = None
    cite: Optional[str] = None
    waiting_on: Optional[PendingPrompt] = None
    match: Optional[MatchState] = None
    rolls: tuple = ()

    @property
    def refused(self) -> bool:
        return self.refusal is not None

    @property
    def prompt(self) -> Optional[PendingPrompt]:
        """The one question, where only one is asked."""
        return self.prompts[0] if len(self.prompts) == 1 else None

    def prompt_for(self, seat: str) -> Optional[PendingPrompt]:
        for one in self.prompts:
            if one.asked_seat == seat:
                return one
        return None

    @property
    def lines(self) -> tuple[str, ...]:
        said = [line for group in self.groups for line in group.lines]
        return tuple(line for line in (*said, *self.narration) if line)

    def to_dict(self) -> dict:
        """
        What the call did, as JSON. **No prompt is written here** --
        each is its asked seat's alone, and a result is shown to
        everybody -- and the position is left out for the same reason:
        it holds both seats' plans.
        """
        return {
            "groups": [group.to_dict() for group in self.groups],
            "narration": list(self.narration),
            "board_changed": self.board_changed,
            "refusal": self.refusal,
            "cite": self.cite,
            "rolls": [jsonable(roll) for roll in self.rolls],
        }


#: What a resume says it found, by the step the bot owed.
OWED_STEP_NAMES: Mapping[FollowOnStep, str] = {
    FollowOnStep.REVEAL: "both seats locked in",
    FollowOnStep.MARCH: "March",
    FollowOnStep.SETTLE_BATTLE: "a battle's end",
    FollowOnStep.PRODUCE: "Production",
    FollowOnStep.SETTLE_TRADES: "the trades",
    FollowOnStep.CLEANUP: "Cleanup",
    FollowOnStep.BEGIN_ROUND: "a battle round's start",
    FollowOnStep.CLOSE_GROUP: "an initiative group's losses",
    FollowOnStep.END_ROUND: "a battle round's end",
}


class GameService:
    """
    Load, apply, save once, return. `games` is the live dict the
    frontend shares, and `save` is what writes it -- `save_games` by
    default, which never raises.
    """

    def __init__(
        self,
        engine: RulesEngine,
        games: dict[str, TnpGame],
        batching: Batching = Batching(),
        save: Optional[Callable[[dict[str, TnpGame]], None]] = None,
    ) -> None:
        self.engine = engine
        self.games = games
        self.batching = batching
        self._save = save
        self.listeners: list[Callable[[TnpGame, GameResult], None]] = []

    def announce(self, game: TnpGame, result: GameResult) -> None:
        for listener in self.listeners:
            try:
                listener(game, result)
            except Exception:  # pragma: no cover - a frontend's own bug
                LOGGER.exception("A listener failed on a result for TNP game %s", game.game_id)

    # -- Loading and saving --------------------------------------------

    def game(self, game_id: str) -> TnpGame:
        return self.games[game_id]

    def load(self, game: TnpGame) -> MatchState:
        if game.match_state is None:
            raise RuleRefusal("This game has not started yet.")
        return MatchState.from_dict(game.match_state)

    def persist(self, game: TnpGame, match: MatchState) -> None:
        """Write the match back onto its record and save -- one step. A
        match with a winner finishes its record in the same save."""
        game.match_state = match.to_dict()
        if match.winner is not None:
            game.finish()
        (self._save or save_games)(self.games)

    def save(self) -> None:
        (self._save or save_games)(self.games)

    def prompts(self, game: TnpGame, match: MatchState) -> tuple[PendingPrompt, ...]:
        return pending_prompts(self.engine, game, match)

    # -- The lobby -------------------------------------------------------

    def next_game_number(self, guild_id: Optional[int]) -> int:
        existing = [game.game_number for game in self.games.values() if game.guild_id == guild_id]
        return max(existing, default=0) + 1

    def create_game(self, *, guild_id: Optional[int] = None, channel_id: Optional[int] = None,
                    game_number: Optional[int] = None, test_game: bool = False) -> TnpGame:
        """A new lobby, with nobody seated, saved."""
        game = TnpGame(
            game_id=uuid.uuid4().hex,
            game_number=self.next_game_number(guild_id) if game_number is None else game_number,
            guild_id=guild_id,
            channel_id=channel_id,
            test_game=test_game,
        )
        self.games[game.game_id] = game
        self.save()
        return game

    def take_seat(self, game_id: str, user_id: int, user_name: Optional[str],
                  seat: Optional[str] = None) -> TnpGame:
        game = self.game(game_id)
        game.take_seat(user_id, user_name, seat)
        self.save()
        return game

    def leave(self, game_id: str, user_id: int) -> TnpGame:
        game = self.game(game_id)
        game.leave(user_id)
        self.save()
        return game

    def set_advanced(self, game_id: str, advanced: bool) -> TnpGame:
        game = self.game(game_id)
        game.set_advanced(advanced)
        self.save()
        return game

    def abandon(self, game_id: str) -> TnpGame:
        game = self.game(game_id)
        game.abandon()
        self.save()
        return game

    def start(self, game_id: str) -> GameResult:
        """Start the game: the opening position dealt (`TnpGame.start`,
        refused until both seats are taken), saved once, waiting on both
        seats' first plans."""
        game = self.game(game_id)
        game.start(self.engine)
        match = self.load(game)
        return self.run(game, match, StepResult(board_changed=True))

    # -- A turn ------------------------------------------------------------

    def apply_action(self, game_id: str, action: driver.Action) -> GameResult:
        """
        Answer a question the match is waiting on -- a seat's plan or
        trade, or a battle's or March's one question -- and run what
        follows, through `driver.apply`; save once; return what
        happened. A `Refusal` comes back as a result with `refusal` set,
        and the match is not written.
        """
        game = self.game(game_id)
        if game.status is not GameStatus.PLAYING:
            raise RuleRefusal("This game is not being played.")
        match = self.load(game)
        applied = driver.apply(
            self.engine, game, match, action,
            stop_after=self.batching.stop_after, own_message=self.batching.own_message,
        )
        if isinstance(applied, driver.Refusal):
            return GameResult(
                refusal=applied.reason, cite=applied.cite,
                waiting_on=applied.waiting_on, match=match,
            )
        self.persist(game, match)
        result = GameResult(
            groups=tuple(Narration(group.narration, group.step) for group in applied.groups),
            narration=tuple(applied.result.narration),
            prompts=self.prompts(game, match),
            board_changed=applied.board_changed,
            match=match,
            rolls=applied.rolls,
        )
        self.announce(game, result)
        return result

    def resume(self, game_id: str) -> tuple[str, GameResult]:
        """
        Put a game back in front of whoever it is waiting on, running the
        step the bot owes where there is one. **The reading is
        `pending_all`'s** -- the one `driver.answer` refuses against --
        and both seats' saved plans are on the match, so a restart
        mid-phase puts both back as they were.
        """
        game = self.game(game_id)
        match = self.load(game)
        waiting = pending_all(self.engine, game, match)
        if waiting and isinstance(waiting[0], FollowOn):
            return (
                OWED_STEP_NAMES.get(waiting[0].step, waiting[0].step.name),
                self.run(game, match, StepResult(next=waiting[0])),
            )
        result = GameResult(prompts=self.prompts(game, match), match=match)
        self.announce(game, result)
        return "the questions, put back up", result

    def run(self, game: TnpGame, match: MatchState, result: StepResult) -> GameResult:
        """Run the chain `result` starts until only somebody's answer can
        carry on, then save once."""
        ran = driver.advance(
            self.engine, game, match, result,
            own_message=self.batching.own_message,
        )
        while ran.stopped_on is not None:  # pragma: no cover - no stop is named for the bot's own run
            ran = driver.advance(self.engine, game, match, ran.result)
        self.persist(game, match)
        done = GameResult(
            groups=tuple(Narration(group.narration, group.step) for group in ran.groups),
            narration=tuple(ran.result.narration),
            prompts=self.prompts(game, match),
            board_changed=ran.board_changed,
            match=match,
            rolls=ran.rolls,
        )
        self.announce(game, done)
        return done


__all__ = ["Batching", "GameResult", "GameService", "Narration", "OWED_STEP_NAMES"]
