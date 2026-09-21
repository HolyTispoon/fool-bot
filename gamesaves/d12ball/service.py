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
where do you stop to draw, and what do you do at a stop", handed to
the service once at construction. The service never reads a step's
name to decide anything; it asks the `Batching` it was given.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum, auto
from typing import Any, Callable, Optional, Sequence, Union

from d12ball.components import MatchState, TeamSide
from d12ball.engine import RulesEngine
from d12ball.flow import driver, periods, turnovers, windows
from d12ball.flow.result import FollowOn, FollowOnStep, StepResult
from d12ball.game import D12BallGame
from d12ball.prompts import PendingPrompt, pending_prompt
from gamesaves.d12ball.storage import save_games


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
    """

    lines: tuple[str, ...]
    step: Optional[FollowOnStep] = None
    board: Optional[dict] = None
    new_play: bool = False
    board_changed: bool = False

    @property
    def drawn(self) -> bool:
        return self.board is not None


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


#: What a resumed Coaching Choice says above the allowance.
RESUME_COACHING_NOTE = (
    "Picking this up where it left off. Nothing you had already done "
    "has been undone."
)


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

    def waiting_on(self, game: D12BallGame, match: MatchState) -> PendingPrompt:
        return pending_prompt(self.engine, game, match)

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
        lead_in: str = "",
        **kwargs: Any,
    ) -> GameResult:
        """Run one step by name and everything it starts."""
        game = self.game(game_id)
        match = self.load(game)
        return self.run(
            game,
            match,
            StepResult(
                narration=[lead_in] if lead_in else [],
                next=FollowOn(step, kwargs),
            ),
        )

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

        This is the one reading of "the bot owes a step here", and it
        is the model's for the reason `pending_prompt` is: a second
        frontend that had to keep its own copy would strand the same
        games a restart strands. Where nothing is owed the result is
        the prompt and nothing runs.
        """
        game = self.game(game_id)
        match = self.load(game)
        engine = self.engine

        if game.tutorial_gate:
            # A note held behind Continue outranks every state below:
            # the position underneath is what it was before the note
            # went up, and re-driving it would run the thing the note
            # explains without the note.
            return "a tutorial note, re-posted above", self._prompt(game, match)

        if match.pending_shootout and not match.pending_injury_tests:
            # Two of the shootout's four steps are the bot's own, so a
            # process that died between them leaves nothing to click.
            # An owed injury check is the exception: that is a button.
            return "the extreme shootout", self.run(
                game, match, periods.advance_shootout(engine, game, match),
                carry=False,
            )

        if match.pending_coaching_side is not None:
            # Ahead of the three stage checks below: setup, halftime
            # and full time all run their coaching through this same
            # window, and their own routines would re-open it -- which
            # resets the allowance a coach had already spent.
            side = TeamSide(match.pending_coaching_side)
            if engine.side_is_ai(game, side):
                # No menu to put back up: the AI's window is a routine
                # that runs to completion.
                return "the AI's Coaching Choice", self.run(
                    game,
                    match,
                    windows.run_ai_substitution_window(engine, game, match),
                    carry=False,
                )
            prompt = self.waiting_on(game, match)
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

        if match.pending_setup_stage is not None:
            return "the pre-kickoff Coaching Choice", self.run(
                game, match, periods.advance_setup_stage(engine, game, match),
                carry=False,
            )

        if match.pending_halftime_stage is not None:
            return "halftime", self.run(
                game, match,
                periods.advance_halftime_stage(engine, game, match),
                carry=False,
            )

        if match.pending_full_time_stage is not None:
            return "the Coaching Choice before the shootout", self.run(
                game, match,
                periods.advance_full_time_stage(engine, game, match),
                carry=False,
            )

        if match.pending_time_out:
            # Both windows have closed -- the branch above would have
            # caught one still open -- so what is left is the tail.
            return "the time out", self.run(
                game, match, windows.finish_time_out(engine, game, match),
            )

        if match.pending_run_back:
            return "the run back", self.run(
                game,
                match,
                StepResult(next=FollowOn(FollowOnStep.CONTINUE_RUN_BACK)),
            )

        if match.pending_ball_recovery:
            return "the out-of-bounds pickup", self.run(
                game, match, turnovers.begin_ball_recovery(engine, game, match),
            )

        return "a choice, re-posted above", self._prompt(game, match)

    def _prompt(
        self,
        game: D12BallGame,
        match: MatchState,
        prompt: Optional[PendingPrompt] = None,
    ) -> GameResult:
        """The prompt the match is waiting on, and nothing run."""
        return GameResult(
            prompt=prompt or self.waiting_on(game, match), match=match,
        )

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
                Narration(group.narration, group.step) for group in run.groups
            )
            board_changed = board_changed or run.board_changed
            following = run.result.next
            stopped = run.stopped_on

            if stopped is None:
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
        return GameResult(
            answer=tuple(answer),
            groups=tuple(groups),
            narration=narration,
            prompt=prompt,
            board_changed=board_changed,
            detail=detail,
            match=match,
        )
