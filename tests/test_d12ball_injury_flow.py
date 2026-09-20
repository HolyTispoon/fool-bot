"""
The injury queue as flow steps, with no Discord in scope.

`begin_injury_tests_step` and `continue_injury_tests_step` in
`d12ball/flow/rolls.py` are the model half of the two cog methods of
the same name -- Phase 4 of docs/model-discord-split.md. The rules
they carry are "Every roll is a coach's" in
docs/design/maneuvers.md: the queue, its one exit, and the
continuation that has to outlive the wait.

The cog's own tests still drive the wrappers; this asks the model the
same questions with `discord` nowhere in the module.
"""

from __future__ import annotations

import unittest

from d12ball.ai import build_ai_strategies
from d12ball.components import (
    MatchState,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.engine import RulesEngine
from d12ball.flow import FollowOn, FollowOnStep
from d12ball.flow.rolls import (
    begin_injury_tests_step,
    continue_injury_tests_step,
)
from d12ball.game import D12BallGame, GameStatus, Team
from d12ball.prompts import PendingPrompt, PromptKind, pending_prompt

CATALOG = load_player_catalog()
RULES = load_basic_ruleset()
MANEUVERS = load_maneuver_catalog()
ENGINE = RulesEngine(
    CATALOG, RULES, MANEUVERS, build_ai_strategies(CATALOG, MANEUVERS),
)

RESUME = {"kind": "run_back", "distance_moved": 2, "turnover_occurred": True}


def build_game() -> D12BallGame:
    return D12BallGame(
        game_id="g1",
        game_number=1,
        guild_id=1,
        channel_id=2,
        message_id=None,
        player_1_id=111,
        player_2_id=222,
        player_1_team=Team.ORANGE,
        player_2_team=Team.PURPLE,
        home_player_number=1,
        visiting_player_number=2,
        status=GameStatus.IN_PROGRESS,
    )


def build_match() -> MatchState:
    return MatchState.standard(
        catalog=CATALOG,
        ruleset=RULES,
        board_size=7,
        home_team=Team.ORANGE,
        visiting_team=Team.PURPLE,
    )


def definitions(match: MatchState, *player_ids: str):
    return [ENGINE.get_player_definition(pid) for pid in player_ids]


class BeginInjuryTestsStepTests(unittest.TestCase):

    def test_nothing_owed_goes_straight_to_the_continuation(self) -> None:
        """
        The common case. A player who is not exhausted past their
        threshold is simply not in the queue, and nothing about the
        match changes -- the contest carries on into its effect.
        """
        game, match = build_game(), build_match()
        already_injured = match.home.field_players[0]
        match.injured.add(already_injured)

        result = begin_injury_tests_step(
            ENGINE, game, match, definitions(match, already_injured), RESUME,
        )

        self.assertEqual(
            result.next,
            FollowOn(FollowOnStep.DISPATCH_INJURY_RESUME, {"resume": RESUME}),
        )
        # Nothing about the match changed, which is what "the common
        # case has to stay free" meant before the driver's own write
        # made it one save either way.
        self.assertEqual(match.pending_injury_tests, [])
        self.assertIsNone(match.pending_injury_resume)
        self.assertEqual(result.narration, [])

    def test_an_owed_test_queues_and_asks_for_the_first(self) -> None:
        """
        The queue and its continuation are both set, and the step
        falls straight through into `continue_injury_tests_step` --
        one door in as well as one door out.
        """
        game, match = build_game(), build_match()
        first, second = match.home.field_players[:2]

        result = begin_injury_tests_step(
            ENGINE, game, match, definitions(match, first, second), RESUME,
        )

        self.assertEqual(match.pending_injury_tests, [first, second])
        self.assertEqual(match.pending_injury_resume, RESUME)
        self.assertIsInstance(result.next, PendingPrompt)
        self.assertIs(result.next.kind, PromptKind.INJURY_TEST)
        self.assertEqual(result.next.player_id, first)

    def test_an_already_injured_player_is_filtered_out(self) -> None:
        """
        Filtered at the queue rather than refused at the prompt: an
        injured player gains no exhaustion tokens and can never be
        asked again.
        """
        game, match = build_game(), build_match()
        first, second = match.home.field_players[:2]
        match.injured.add(first)

        result = begin_injury_tests_step(
            ENGINE, game, match, definitions(match, first, second), RESUME,
        )

        self.assertEqual(match.pending_injury_tests, [second])
        self.assertEqual(result.next.player_id, second)


class ContinueInjuryTestsStepTests(unittest.TestCase):

    def test_the_empty_queue_is_the_one_exit(self) -> None:
        """
        A test that was rolled and a test that turned out not to be
        owed leave by the same door, and the continuation is cleared
        off the match as it goes.
        """
        game, match = build_game(), build_match()
        match.pending_injury_tests = []
        match.pending_injury_resume = RESUME

        result = continue_injury_tests_step(ENGINE, game, match)

        self.assertEqual(
            result.next,
            FollowOn(FollowOnStep.DISPATCH_INJURY_RESUME, {"resume": RESUME}),
        )
        self.assertIsNone(match.pending_injury_resume)

    def test_a_player_injured_since_the_queue_was_built_is_skipped(
        self,
    ) -> None:
        """
        Not reachable today -- one test cannot injure the other
        participant -- but a player who cannot be injured twice should
        never be asked to roll for it.
        """
        game, match = build_game(), build_match()
        first, second = match.home.field_players[:2]
        match.pending_injury_tests = [first, second]
        match.pending_injury_resume = RESUME
        match.injured.add(first)

        result = continue_injury_tests_step(ENGINE, game, match)

        self.assertEqual(match.pending_injury_tests, [second])
        self.assertEqual(result.next.player_id, second)

    def test_the_ask_names_the_tokens_it_has_to_beat(self) -> None:
        """
        A d12 means nothing until you know what it was chasing, so the
        count is in the sentence as well as on the die image.
        """
        game, match = build_game(), build_match()
        player_id = match.home.field_players[0]
        match.exhaustion[player_id] = 1
        match.pending_injury_tests = [player_id]

        ask = continue_injury_tests_step(ENGINE, game, match).next.ask
        self.assertIn("1 exhaustion token.", ask)

        match.exhaustion[player_id] = 4
        match.pending_injury_tests = [player_id]
        self.assertIn(
            "4 exhaustion tokens.",
            continue_injury_tests_step(ENGINE, game, match).next.ask,
        )

    def test_a_restart_comes_back_to_the_same_question(self) -> None:
        """
        The queue is persisted, so `pending_prompt` reads the same
        player back off the match -- one reading of what a match is
        waiting on, which is principle 3.
        """
        game, match = build_game(), build_match()
        player_id = match.home.field_players[0]
        match.pending_injury_tests = [player_id]
        match.pending_injury_resume = RESUME

        live = continue_injury_tests_step(ENGINE, game, match).next
        restored = pending_prompt(
            ENGINE, game, MatchState.from_dict(match.to_dict(), RULES),
        )

        self.assertIs(live.kind, restored.kind)
        self.assertEqual(live.player_id, restored.player_id)


if __name__ == "__main__":
    unittest.main()
