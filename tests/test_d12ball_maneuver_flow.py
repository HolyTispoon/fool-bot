"""
The front half of a turn, asked of the model.

Phase 4 of docs/model-discord-split.md moves `auto_resolve_challenger`,
`announce_uncontested_maneuver`, `begin_maneuver_action_selection` and
`resolve_maneuver` out of `cogs/d12ball/core.py`, with the injury
queue that a resolved contest hands out.

**What is worth asserting here is the wording**, because four of the
five things this phase moved are sentences. Which of the four ways a
maneuver lands a position reads as is a rule about the cards and the
injuries -- "A player is never named without their role", "say what
the position is, never what it is not" -- and those are CLAUDE.md's,
settled by the author reading a turn back out of a channel. A frontend
wording them a second time is a second voice.

A test names a player by role (`tests/roster.py`), never by name: the
wording around the name is the assertion, the name inside it is not.
"""

from __future__ import annotations

import unittest

from d12ball.components import PlayerRole, TeamSide
from d12ball.flow import FollowOnStep
from d12ball.flow.maneuver import (
    begin_injury_tests_step,
    challenger_step,
    challenger_walk_in_note,
    continue_injury_tests_step,
    maneuver_action_selection_step,
    resolve_maneuver_step,
    uncontested_maneuver_note,
    uncontested_maneuver_step,
)
from d12ball.prompts import PromptKind

from low_pass_fixtures import ENGINE, build_game, build_match, take_the_ball
from roster import fielded


def stand_the_maneuver_up(match):
    """
    A challenged maneuver with both picks in, which is where
    `resolve_maneuver_step` is asked.
    """
    take_the_ball(match)
    match.challenger_id = fielded(
        match, PlayerRole.DEFENDER, match.defending_side(),
    )
    return match


class ChallengerStepTests(unittest.TestCase):
    def test_a_defender_already_on_the_ball_says_nothing(self) -> None:
        """
        A move that costs nothing says nothing -- see
        docs/design/naming-and-wording.md.
        """
        game = build_game()
        match = build_match()
        take_the_ball(match)
        on_the_ball = [
            player_id
            for player_id in match.board.spaces[match.ball.zone][
                match.ball.space_index
            ]
            if player_id in match.setup_for_side(
                match.defending_side()
            ).field_players
        ]
        if not on_the_ball:
            self.skipTest("the deal put no defender on the ball")

        result = challenger_step(ENGINE, game, match, on_the_ball[0])

        self.assertEqual(result.narration, [])
        self.assertIs(
            result.next.step, FollowOnStep.ANNOUNCE_MANEUVER_CHALLENGE,
        )

    def test_a_walk_in_says_how_far_and_what_it_cost(self) -> None:
        game = build_game()
        match = build_match()
        take_the_ball(match)
        # **A defender standing on the ball narrows the pool to
        # themselves** (see docs/design/sending-a-player.md), so the
        # walk-in only exists once nobody of theirs is there. Cleared
        # rather than skipped, because the branch is the point of the
        # test.
        defense = match.defending_side()
        for player_id in list(
            match.board.spaces[match.ball.zone][match.ball.space_index]
        ):
            if player_id in match.setup_for_side(defense).field_players:
                match.board.remove_meeple(player_id)
        defender = match.challenge_candidates()[0]
        self.assertGreater(match.distance_to_ball(defender), 0)

        result = challenger_step(ENGINE, game, match, defender)

        self.assertEqual(match.challenger_id, defender)
        self.assertTrue(result.board_changed)
        self.assertIn("has moved", result.narration[0])

    def test_the_note_is_empty_when_nobody_moved(self) -> None:
        game = build_game()
        match = build_match()
        take_the_ball(match)
        self.assertEqual(
            challenger_walk_in_note(
                ENGINE, game, match,
                fielded(match, PlayerRole.FULLBACK, match.defending_side()),
                0,
            ),
            "",
        )
        self.assertEqual(
            challenger_walk_in_note(
                ENGINE, game, match,
                fielded(match, PlayerRole.FULLBACK, match.defending_side()),
                -1,
            ),
            "",
        )


class UncontestedManeuverTests(unittest.TestCase):
    """
    Which of the two ways it happened is read off the candidates,
    never stored -- see docs/design/sending-a-player.md.
    """

    def test_a_defense_that_sent_nobody_is_worded_as_such(self) -> None:
        game = build_game()
        match = build_match()
        take_the_ball(match)
        self.assertTrue(match.eligible_challengers())

        note = uncontested_maneuver_note(ENGINE, match)

        self.assertIn("**Unchallenged!**", note)
        self.assertIn("have sent nobody in to challenge", note)

    def test_a_defense_with_nobody_left_is_worded_differently(
        self,
    ) -> None:
        game = build_game()
        match = build_match()
        take_the_ball(match)
        for player_id in list(
            match.setup_for_side(match.defending_side()).field_players
        ):
            match.board.remove_meeple(player_id)

        note = uncontested_maneuver_note(ENGINE, match)

        self.assertIn("have nobody left to challenge", note)

    def test_it_goes_straight_to_the_pick(self) -> None:
        game = build_game()
        match = build_match()
        take_the_ball(match)

        result = uncontested_maneuver_step(ENGINE, game, match)

        self.assertIs(
            result.next.step,
            FollowOnStep.BEGIN_MANEUVER_ACTION_SELECTION,
        )
        self.assertEqual(len(result.narration), 1)
        # A decline moves nobody and charges nobody, so it is also the
        # one of the three entry points that asks for no board refresh.
        self.assertFalse(result.board_changed)


class ManeuverActionSelectionTests(unittest.TestCase):
    def test_both_picks_in_resolves(self) -> None:
        game = build_game()
        match = stand_the_maneuver_up(build_match())
        match.offense_maneuver = "low_pass"
        match.defense_maneuver = "pressure"

        result = maneuver_action_selection_step(ENGINE, game, match)

        self.assertIs(result.next.step, FollowOnStep.RESOLVE_MANEUVER)

    def test_one_pick_missing_asks(self) -> None:
        game = build_game()
        match = stand_the_maneuver_up(build_match())
        match.offense_maneuver = "low_pass"

        result = maneuver_action_selection_step(ENGINE, game, match)

        self.assertIs(result.next.step, FollowOnStep.ASK_MANEUVER_ACTION)


class ResolveManeuverStepTests(unittest.TestCase):
    def test_a_decisive_win_names_the_card_and_hands_to_its_effect(
        self,
    ) -> None:
        game = build_game()
        match = stand_the_maneuver_up(build_match())
        match.offense_maneuver = "low_pass"
        match.defense_maneuver = "pressure"  # Low Pass beats Pressure.

        result = resolve_maneuver_step(ENGINE, game, match)

        self.assertIs(
            result.next.step, FollowOnStep.BEGIN_EFFECT_RESOLUTION,
        )
        self.assertEqual(result.next.kwargs, {"winner_key": "low_pass"})
        self.assertIn("## **Low Pass** wins!", result.narration[0])
        # Whoever resolves the effect is not named: an effect with a
        # choice in it prompts them by name itself.
        self.assertNotIn("resolves the effect", result.narration[0])

    def test_an_uncontested_maneuver_succeeds_outright(self) -> None:
        game = build_game()
        match = build_match()
        take_the_ball(match)
        match.maneuver_uncontested = True
        match.offense_maneuver = "low_pass"

        result = resolve_maneuver_step(ENGINE, game, match)

        self.assertIs(
            result.next.step, FollowOnStep.BEGIN_EFFECT_RESOLUTION,
        )
        self.assertIn("unchallenged", result.narration[0])
        self.assertIn("## **Low Pass** succeeds!", result.narration[0])

    def test_a_tie_goes_to_a_skill_test_with_the_headline_as_narration(
        self,
    ) -> None:
        """
        **The headline is narration, not an argument.** It is the
        reveal and why the cards did not settle it, and it opens the
        message the skill test posts -- so putting it in
        `FollowOn.kwargs` would have been narration riding in a
        follow-on's arguments, which is the one thing `StepResult` is
        shaped to prevent.
        """
        game = build_game()
        match = stand_the_maneuver_up(build_match())
        match.offense_maneuver = "low_pass"
        match.defense_maneuver = "deflect"  # Ranked the same.
        if ENGINE.maneuver_catalog.resolve("low_pass", "deflect") != "tie":
            self.skipTest("low_pass/deflect is no longer a tie")

        result = resolve_maneuver_step(ENGINE, game, match)

        self.assertIs(
            result.next.step, FollowOnStep.BEGIN_MANEUVER_SKILL_TEST,
        )
        self.assertEqual(result.next.kwargs, {})
        self.assertIn("skill\ntest!", result.narration[0].replace(" ", "\n"))


class InjuryQueueTests(unittest.TestCase):
    """
    The queue, and its one exit.
    """

    def build(self):
        game = build_game()
        match = stand_the_maneuver_up(build_match())
        return game, match

    def test_nothing_owed_writes_nothing_and_carries_on(self) -> None:
        game, match = self.build()
        players = [
            ENGINE.get_player_definition(match.active_player_id),
        ]
        match.injured = {match.active_player_id}

        result = begin_injury_tests_step(
            ENGINE, game, match, players, {"kind": "maneuver_effect"},
        )

        self.assertIs(
            result.next.step, FollowOnStep.DISPATCH_INJURY_RESUME,
        )
        self.assertEqual(match.pending_injury_tests, [])
        self.assertIsNone(match.pending_injury_resume)

    def test_a_test_owed_queues_it_with_its_continuation(self) -> None:
        game, match = self.build()
        players = [
            ENGINE.get_player_definition(match.active_player_id),
        ]

        result = begin_injury_tests_step(
            ENGINE, game, match, players,
            {"kind": "maneuver_effect", "winner_key": "low_pass"},
        )

        self.assertIs(
            result.next.step, FollowOnStep.CONTINUE_INJURY_TESTS,
        )
        self.assertEqual(
            match.pending_injury_tests, [match.active_player_id],
        )
        self.assertEqual(
            match.pending_injury_resume["winner_key"], "low_pass",
        )

    def test_the_next_test_is_a_prompt_naming_its_player(self) -> None:
        """
        The player is in the prompt as well as in the queue, so a
        coach who scrolls back to the first of two cannot roll the
        second player's test with it.
        """
        game, match = self.build()
        match.pending_injury_tests = [match.active_player_id]
        match.pending_injury_resume = {"kind": "maneuver_effect"}

        result = continue_injury_tests_step(ENGINE, game, match)

        self.assertIs(result.next.kind, PromptKind.INJURY_TEST)
        self.assertEqual(result.next.player_id, match.active_player_id)
        self.assertIn("owes an injury test", result.next.ask)

    def test_an_empty_queue_leaves_by_the_same_door(self) -> None:
        game, match = self.build()
        match.pending_injury_tests = []
        match.pending_injury_resume = {"kind": "run_back"}

        result = continue_injury_tests_step(ENGINE, game, match)

        self.assertIs(
            result.next.step, FollowOnStep.DISPATCH_INJURY_RESUME,
        )
        self.assertEqual(
            result.next.kwargs["resume"], {"kind": "run_back"},
        )
        self.assertIsNone(match.pending_injury_resume)

    def test_a_player_injured_since_the_queue_was_built_is_skipped(
        self,
    ) -> None:
        game, match = self.build()
        match.pending_injury_tests = [match.active_player_id]
        match.injured = {match.active_player_id}
        match.pending_injury_resume = {"kind": "run_back"}

        result = continue_injury_tests_step(ENGINE, game, match)

        self.assertIs(
            result.next.step, FollowOnStep.DISPATCH_INJURY_RESUME,
        )


if __name__ == "__main__":
    unittest.main()
