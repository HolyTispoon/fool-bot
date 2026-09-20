"""
The out-of-bounds pickup as a flow step, with no Discord in scope.

`ball_recovery_step` is the model half of `D12Ball.begin_ball_recovery`
-- Phase 4 of docs/model-discord-split.md, the spine. The rules it
carries are in docs/design/sending-a-player.md ("a missed shot and an
avoided own goal joined the pickup on 2026-08-24") and
docs/design/possession-and-turnovers.md.

The cog's own tests in `tests/test_d12ball_loose_ball.py` still drive
the wrapper and are what say the two agree; this asks the model the
same three questions with `discord` nowhere in the module, which is
the point of the move.
"""

from __future__ import annotations

import unittest

from d12ball.ai import build_ai_strategies
from d12ball.components import (
    MatchState,
    TeamSide,
    Zone,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.engine import RulesEngine
from d12ball.flow import FollowOn, FollowOnStep
from d12ball.flow.turnovers import ball_recovery_step
from d12ball.game import AIOpponent, D12BallGame, GameStatus, Team
from d12ball.prompts import PendingPrompt, PromptKind

CATALOG = load_player_catalog()
RULES = load_basic_ruleset()
MANEUVERS = load_maneuver_catalog()
ENGINE = RulesEngine(
    CATALOG, RULES, MANEUVERS, build_ai_strategies(CATALOG, MANEUVERS),
)


def build_game(ai: bool = False) -> D12BallGame:
    return D12BallGame(
        game_id="g1",
        game_number=1,
        guild_id=1,
        channel_id=2,
        message_id=None,
        player_1_id=111,
        player_2_id=None if ai else 222,
        player_1_team=Team.ORANGE,
        player_2_team=Team.PURPLE,
        home_player_number=1,
        visiting_player_number=2,
        status=GameStatus.IN_PROGRESS,
        ai_opponent=AIOpponent.DINKY if ai else None,
    )


def build_match() -> MatchState:
    return MatchState.standard(
        catalog=CATALOG,
        ruleset=RULES,
        board_size=7,
        home_team=Team.ORANGE,
        visiting_team=Team.PURPLE,
    )


def clear_the_ball_s_space(match: MatchState) -> None:
    for occupant in list(
        match.board.spaces[match.ball.zone][match.ball.space_index]
    ):
        match.board.remove_meeple(occupant)


class BallRecoveryStepTests(unittest.TestCase):
    """
    Three branches, and which one is taken is the whole of the step:
    nobody to send, an AI to send for itself, and a coach to ask.
    """

    def test_a_reset_that_covers_the_ball_asks_nobody(self) -> None:
        """
        The pickup is owed "unless one of theirs is already on it".
        The flag is cleared and the turn goes straight on to the tail
        of the maneuver, carrying the clock the turnover still owes.
        """
        game, match = build_game(), build_match()
        match.pending_ball_recovery = True
        match.pending_run_back_distance = 3
        self.assertTrue(match.eligible_ball_handlers())

        result = ball_recovery_step(ENGINE, game, match)

        self.assertFalse(match.pending_ball_recovery)
        self.assertEqual(
            result.next,
            FollowOn(
                FollowOnStep.FINISH_MANEUVER_RESOLUTION,
                {"distance_moved": 3, "turnover_occurred": True},
            ),
        )
        self.assertEqual(result.narration, [])
        self.assertFalse(result.board_changed)

    def test_an_ai_side_is_sent_its_nearest_player(self) -> None:
        """
        Nearest, not best: the walk costs a token a space and wins
        nothing, so the only thing worth optimizing is the cost.

        The step names the placement rather than making it -- both
        routes into the pickup meet in `apply_ball_recovery`, so there
        is one placement rather than one per route.
        """
        game, match = build_game(ai=True), build_match()
        match.set_ball_space(Zone.HOME_GOAL, 1)
        clear_the_ball_s_space(match)
        match.ball.possession = TeamSide.VISITING
        match.pending_ball_recovery = True

        travel = {
            player_id: match.distance_to_ball(player_id)
            for player_id in match.contest_candidates(TeamSide.VISITING)
        }
        # A tie would prove nothing about which one it took.
        self.assertGreater(len(set(travel.values())), 1)

        result = ball_recovery_step(ENGINE, game, match)

        self.assertIsInstance(result.next, FollowOn)
        self.assertIs(result.next.step, FollowOnStep.APPLY_BALL_RECOVERY)
        self.assertEqual(
            travel[result.next.kwargs["player_id"]], min(travel.values()),
        )
        # Nothing has moved yet, and the flag is still owed: the
        # placement is the follow-on's.
        self.assertTrue(match.pending_ball_recovery)

    def test_a_human_side_is_asked(self) -> None:
        """
        The prompt a coach is put in front of, as a `PendingPrompt` --
        so the live flow and a restart build the view through one
        table (`view_for_prompt`).

        The ask is the **live** wording rather than
        `pending_prompt`'s: this one is read directly under the reset
        it follows, so it names the coach and says why everybody has
        just moved. Same position, two readings of it.
        """
        game, match = build_game(), build_match()
        clear_the_ball_s_space(match)
        match.ball.possession = TeamSide.VISITING
        match.pending_ball_recovery = True

        result = ball_recovery_step(ENGINE, game, match)

        self.assertIsInstance(result.next, PendingPrompt)
        self.assertIs(result.next.kind, PromptKind.BALL_RECOVERY)
        self.assertIn("everyone is back in position", result.next.ask)
        self.assertIn(f"<@{game.player_2_id}>", result.next.ask)
        self.assertTrue(match.pending_ball_recovery)

    def test_the_step_neither_draws_nor_narrates(self) -> None:
        """
        It asks a question; it does not report a position. The lead-in
        it used to take is the *caller's* narration now, put in front
        of the result by the wrapper -- see principle 8.
        """
        game, match = build_game(), build_match()
        clear_the_ball_s_space(match)
        match.pending_ball_recovery = True

        result = ball_recovery_step(ENGINE, game, match)

        self.assertEqual(result.narration, [])
        self.assertFalse(result.board_changed)


if __name__ == "__main__":
    unittest.main()
