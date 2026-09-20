"""
The injury-test queue as a flow step -- no Discord, nothing saved.

The model-side half of what Phase 4 lifted out of
`cogs/d12ball/core.py`. The cog's own behaviour is covered by
`tests/test_d12ball_injury.py`, which drives the views; this asserts
the three things the lift is allowed to be judged on: the queue is
filtered the same way, the prompt is the same question, and the step
writes nothing to disk.
"""

import unittest

from d12ball.flow import FollowOn, FollowOnStep
from d12ball.flow.injuries import (
    begin_injury_tests,
    continue_injury_tests,
    dispatch_injury_resume,
)
from d12ball.prompts import PromptKind

from d12ball.components import PlayerRole

from roster import fielded
from test_d12ball_tutorial import build_cog, build_game, build_match


class InjuryTestFlowTests(unittest.TestCase):
    """The queue, the filter, and the one exit."""

    def setUp(self) -> None:
        self.cog = build_cog()
        self.game = build_game(tutorial=False, tutorial_step=None)
        self.match = build_match()
        self.engine = self.cog.engine
        self.resume = {"kind": "maneuver_effect", "winner_key": "low_pass"}

    def players(self, *player_ids):
        return [
            self.engine.get_player_definition(player_id)
            for player_id in player_ids
        ]

    def test_a_contest_that_owes_nothing_hands_straight_on(self) -> None:
        """
        The common case, and it writes nothing: no queue, no resume,
        and the continuation comes straight back out.
        """
        result = begin_injury_tests(
            self.engine, self.game, self.match, [], self.resume,
        )
        # Phase 5 lifted the dispatcher too, so the continuation is
        # answered here rather than named: a `maneuver_effect` resume
        # is the one of the three kinds still dispatched by the cog.
        self.assertEqual(
            result.next,
            FollowOn(
                FollowOnStep.BEGIN_EFFECT_RESOLUTION,
                {"winner_key": "low_pass"},
            ),
        )
        self.assertEqual(self.match.pending_injury_tests, [])
        self.assertIsNone(self.match.pending_injury_resume)

    def test_an_owed_test_is_queued_and_asked(self) -> None:
        player_id = fielded(self.match, PlayerRole.MIDFIELDER)
        result = begin_injury_tests(
            self.engine,
            self.game,
            self.match,
            self.players(player_id),
            self.resume,
        )
        self.assertEqual(self.match.pending_injury_tests, [player_id])
        self.assertEqual(self.match.pending_injury_resume, self.resume)
        self.assertEqual(result.next.kind, PromptKind.INJURY_TEST)
        self.assertEqual(result.next.player_id, player_id)

    def test_an_already_injured_player_owes_nothing(self) -> None:
        """
        Filtered into the queue rather than refused at the prompt: an
        injured player gains no exhaustion tokens, so they can never be
        asked again.
        """
        injured_id = fielded(self.match, PlayerRole.MIDFIELDER)
        healthy_id = fielded(self.match, PlayerRole.FULLBACK)
        self.match.injured.add(injured_id)

        begin_injury_tests(
            self.engine,
            self.game,
            self.match,
            self.players(injured_id, healthy_id),
            self.resume,
        )
        self.assertEqual(self.match.pending_injury_tests, [healthy_id])

    def test_a_player_injured_since_the_queue_was_built_is_skipped(
        self,
    ) -> None:
        """
        The drain is the one exit, so a player who can no longer be
        asked leaves by it rather than stalling the queue.
        """
        first_id = fielded(self.match, PlayerRole.MIDFIELDER)
        second_id = fielded(self.match, PlayerRole.FULLBACK)
        self.match.pending_injury_tests = [first_id, second_id]
        self.match.pending_injury_resume = self.resume
        self.match.injured.add(first_id)

        result = continue_injury_tests(self.engine, self.game, self.match)
        self.assertEqual(self.match.pending_injury_tests, [second_id])
        self.assertEqual(result.next.player_id, second_id)

    def test_the_drained_queue_drops_the_resume_and_names_it(self) -> None:
        self.match.pending_injury_tests = []
        self.match.pending_injury_resume = self.resume

        result = continue_injury_tests(self.engine, self.game, self.match)
        self.assertEqual(
            result.next,
            FollowOn(
                FollowOnStep.BEGIN_EFFECT_RESOLUTION,
                {"winner_key": "low_pass"},
            ),
        )
        self.assertIsNone(self.match.pending_injury_resume)

    def test_a_run_back_resume_names_the_step_and_keeps_its_arguments(
        self,
    ) -> None:
        """
        The second of the three resume kinds. It is **named** rather
        than called, unlike the shootout's: `D12Ball.begin_run_back`
        is what decides whether a new play's board is posted and
        pinned, which the model may not know.
        """
        resume = {
            "kind": "run_back",
            "distance_moved": 3,
            "turnover_occurred": True,
        }
        result = dispatch_injury_resume(
            self.engine, self.game, self.match, resume,
        )
        self.assertEqual(
            result.next,
            FollowOn(
                FollowOnStep.BEGIN_RUN_BACK,
                {"distance_moved": 3, "turnover_occurred": True},
            ),
        )

    def test_a_resume_it_cannot_read_stops_rather_than_guessing(
        self,
    ) -> None:
        """
        A game in this state needs `/d12ball resume`, and the step has
        nothing true to say about a position it cannot find. It is
        logged at ERROR, which is what reaches #logs.
        """
        with self.assertLogs(
            "d12ball.flow.injuries", level="ERROR",
        ) as logs:
            result = dispatch_injury_resume(
                self.engine, self.game, self.match, None,
            )
        self.assertIsNone(result.next)
        self.assertIn("needs /d12ball resume", logs.output[0])

    def test_the_ask_names_the_player_and_their_tokens(self) -> None:
        """
        The wording is the model's (principle 5), so it is asserted
        here rather than in the cog: the token count is what tells a
        coach what the d12 is chasing.
        """
        player_id = fielded(self.match, PlayerRole.MIDFIELDER)
        self.match.exhaustion[player_id] = 1
        result = begin_injury_tests(
            self.engine,
            self.game,
            self.match,
            self.players(player_id),
            self.resume,
        )
        self.assertIn("1 exhaustion token.", result.next.ask)

        self.match.pending_injury_tests = [player_id]
        self.match.exhaustion[player_id] = 3
        again = continue_injury_tests(self.engine, self.game, self.match)
        self.assertIn("3 exhaustion tokens.", again.next.ask)

    def test_nothing_in_the_step_saves(self) -> None:
        """
        Principle 9: a step mutates and returns, and the driver writes
        it down.

        Asserted by **not** suppressing anything. The suite arms
        `save_patches.guard_stray_saves`, so a step that reached
        `save_games` would raise `StraySaveError` here rather than
        writing `data/` -- which makes "no suppression needed" the
        assertion itself. See docs/design/testing.md.
        """
        player_id = fielded(self.match, PlayerRole.MIDFIELDER)
        begin_injury_tests(
            self.engine,
            self.game,
            self.match,
            self.players(player_id),
            self.resume,
        )
        continue_injury_tests(self.engine, self.game, self.match)


if __name__ == "__main__":
    unittest.main()
