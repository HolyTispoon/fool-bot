"""
The arrival group, asked of the model.

Phase 4 of docs/model-discord-split.md moves the three functions every
ball arrival opens with -- Smooth, Mind Pull, "is anybody of the
possessing side standing on it" -- and the loose ball they lead to,
out of `cogs/d12ball/effects.py` and into `d12ball/flow/arrival.py`.
**The group moved whole**, because which of them is asked before which
is a rule, and half an ordering in `cogs/` is a rule decided in the
frontend.

What is asserted here is what the gates *do to the match* and what
they hand back, with no `discord` in scope. What the cog does with the
answer -- a board drawn under a loose ball's announcement and not under
a High Pass contest's -- is asserted where it belongs, in
`tests/test_d12ball_loose_ball.py` and the two goldens.

See "Mind Pull, and the arrival gate" and "Smooth" in
docs/design/species-abilities.md for the ordering, and
docs/design/loose-balls.md for the occupancy rule.
"""

from __future__ import annotations

import unittest

from d12ball.components import (
    MatchState,
    PlayerRole,
    TeamSide,
    Zone,
    load_basic_ruleset,
    load_player_catalog,
)
from d12ball.flow import FollowOnStep
from d12ball.flow.arrival import (
    check_for_ball_arrival,
    check_for_loose_ball,
    check_for_mind_pull,
    check_for_smooth,
    high_pass_contest_step,
    loose_ball_step,
    shooter_choice_step,
)
from d12ball.formatting import HIGH_PASS_CONTEST_HEADLINE
from d12ball.game import Formation, GameMode, Team
from d12ball.prompts import PromptKind

from low_pass_fixtures import ENGINE, build_game, build_match, take_the_ball
from roster import fielded


def telekinetic_match(board_size: int = 7):
    """
    A match whose home side is the Telekinetics, so the two halves of
    the arrival gate have somebody to offer.

    Built here rather than in `low_pass_fixtures` because the species
    is the whole point of it: every other fixture in the suite wants
    a side with no ability in the way.
    """
    return MatchState.standard(
        catalog=load_player_catalog(),
        ruleset=load_basic_ruleset(),
        board_size=board_size,
        home_team=Team.TELEKINETICS,
        visiting_team=Team.CYBORGS,
        home_formation=Formation.TWO_TWO_TWO,
    )


class LooseBallCheckTests(unittest.TestCase):
    """
    The cheapest of the three gates: does the possessing side have
    anybody standing where the ball stopped?
    """

    def test_somebody_of_theirs_on_the_ball_is_not_a_detour(self) -> None:
        match = build_match()
        take_the_ball(match)
        self.assertIsNone(check_for_loose_ball(match, 1))

    def test_an_empty_space_detours_into_the_loose_ball(self) -> None:
        match = build_match()
        take_the_ball(match)
        for player_id in list(match.board.spaces[match.ball.zone][
            match.ball.space_index
        ]):
            match.board.remove_meeple(player_id)

        detour = check_for_loose_ball(match, 3)

        self.assertIsNotNone(detour)
        self.assertIs(detour.next.step, FollowOnStep.BEGIN_LOOSE_BALL)
        self.assertEqual(detour.next.kwargs, {"distance_moved": 3})
        self.assertEqual(detour.narration, [])


class ArrivalGateTests(unittest.TestCase):
    """
    Smooth first, then Mind Pull, and the path spent by the second of
    them whether or not anybody may pull.
    """

    def build(self, board_size: int = 7):
        # The abilities are an advanced-mode module, so the game has
        # to be one -- `species_abilities_apply` reads both.
        game = build_game(mode=GameMode.ADVANCED)
        game.species_abilities = True
        match = telekinetic_match(board_size)
        take_the_ball(match)
        return game, match

    def test_nobody_to_offer_leaves_the_gate_open(self) -> None:
        game, match = self.build()
        match.last_ball_path = []
        match.last_ball_path = []
        self.assertIsNone(
            check_for_ball_arrival(ENGINE, game, match, {}),
        )

    def test_the_path_is_spent_even_when_nobody_may_pull(self) -> None:
        """
        The one thing the gate does unconditionally, and the reason two
        gates in a row do not offer the same movement twice: the second
        of them reaches an empty path.
        """
        game, match = self.build()
        match.last_ball_path = [[Zone.MIDFIELD.value, 1]]
        match.last_ball_movers = [fielded(match, PlayerRole.MIDFIELDER)]
        game.species_abilities = False

        self.assertIsNone(check_for_mind_pull(ENGINE, game, match, {}))
        self.assertEqual(match.last_ball_path, [])
        self.assertEqual(match.last_ball_movers, [])

    def test_smooth_leaves_the_path_for_the_pull(self) -> None:
        """
        The one mechanical difference between the two gate functions:
        a Smooth that nobody wanted must still leave the pull its
        movement, so Smooth does not clear the path and Mind Pull
        does.
        """
        game, match = self.build()
        # A Telekinetic of the possessing side standing on a space the
        # ball ran through, and not the one holding it.
        winger = fielded(match, PlayerRole.WINGER, match.ball.possession)
        zone, space = match.board.meeple_position(winger)
        path = [[zone.value, space]]
        match.last_ball_path = list(path)
        match.last_ball_movers = []

        taken = check_for_smooth(ENGINE, game, match, {"kind": "loose_ball"})

        self.assertIsNotNone(taken)
        self.assertIs(taken.next.step, FollowOnStep.CONTINUE_SMOOTH)
        self.assertIn(winger, match.pending_smooth)
        self.assertEqual(
            match.pending_smooth_resume, {"kind": "loose_ball"},
        )
        # The path is untouched: the pull is the last reader and needs
        # the movement a Smooth nobody wanted has left it.
        self.assertEqual(match.last_ball_path, path)


class LooseBallStepTests(unittest.TestCase):
    """What the loose ball sets up, and what it asks."""

    def build(self, board_size: int = 7):
        game = build_game()
        game.species_abilities = False
        match = build_match(board_size)
        take_the_ball(match)
        return game, match

    def clear_the_landing_space(self, match) -> None:
        for player_id in list(match.board.spaces[match.ball.zone][
            match.ball.space_index
        ]):
            match.board.remove_meeple(player_id)

    def test_an_empty_space_is_announced_with_where_the_ball_is(
        self,
    ) -> None:
        game, match = self.build()
        self.clear_the_landing_space(match)

        result = loose_ball_step(ENGINE, game, match, 2)

        self.assertTrue(match.pending_loose_ball)
        self.assertEqual(match.pending_loose_ball_distance, 2)
        self.assertIsNone(match.ball_carrier_id)
        # One block, and the space is named inside it: the ball is
        # lying somewhere nothing in the channel has named.
        self.assertEqual(len(result.narration), 1)
        self.assertIn("The ball is at", result.narration[0])

    def test_the_caller_s_lines_are_a_block_of_their_own(self) -> None:
        """
        The pass said what it did and this says where the ball ended
        up. Two blocks rather than one string, so the frontend decides
        how they go together -- the cog puts a blank line between them.
        """
        game, match = self.build()
        self.clear_the_landing_space(match)

        result = loose_ball_step(
            ENGINE, game, match, 1, lead_in="**Deflect:** knocked back.",
        )

        self.assertEqual(len(result.narration), 2)
        self.assertEqual(result.narration[0], "**Deflect:** knocked back.")

    def test_a_high_pass_says_so_and_names_no_space(self) -> None:
        """
        A High Pass is not a loose ball: the ball is on a receiver both
        coaches watched catch it, so the headline is the caller's and
        the board is not drawn under it.
        """
        game, match = self.build()

        result = high_pass_contest_step(ENGINE, game, match, 3)

        self.assertTrue(match.pending_loose_ball_is_high_pass)
        self.assertEqual(result.narration, [HIGH_PASS_CONTEST_HEADLINE])
        self.assertNotIn("The ball is at", result.narration[0])

    def test_the_side_with_nobody_there_is_never_put_on_the_clock(
        self,
    ) -> None:
        """
        Occupancy decides who may be sent, and there is no flag for it
        (the author, 2026-08-26): where one side is already standing on
        the ball, nobody walks in past them.
        """
        game, match = self.build()
        defense = match.defending_side()
        for player_id in match.setup_for_side(defense).field_players:
            if player_id in match.board.spaces[match.ball.zone][
                match.ball.space_index
            ]:
                match.board.remove_meeple(player_id)
        self.assertTrue(match.loose_ball_occupants(match.ball.possession))
        self.assertFalse(match.loose_ball_occupants(defense))

        loose_ball_step(ENGINE, game, match, 1)

        declined = (
            match.loose_ball_defense_declined
            if defense is match.defending_side()
            else match.loose_ball_offense_declined
        )
        self.assertTrue(declined)

    def test_nobody_left_to_ask_settles_instead_of_prompting(self) -> None:
        game, match = self.build()

        result = loose_ball_step(ENGINE, game, match, 1)

        if ENGINE.loose_ball_side_on_the_clock(match) is None:
            self.assertIs(
                result.next.step, FollowOnStep.RESOLVE_LOOSE_BALL,
            )
        else:
            self.assertIs(result.next.kind, PromptKind.LOOSE_BALL_PICK)


class ShooterChoiceStepTests(unittest.TestCase):
    """
    Whether anybody is being asked at all, which is the whole of the
    step -- the two answers reach a channel differently and that part
    stays the cog's.
    """

    def test_one_candidate_is_nobody_s_choice(self) -> None:
        game = build_game()
        match = build_match()
        take_the_ball(match)
        shooter = match.active_player_id

        result = shooter_choice_step(ENGINE, game, match, [shooter])

        self.assertIs(result.next.step, FollowOnStep.START_SET_UP_SHOT)
        self.assertEqual(result.next.kwargs, {"shooter_id": shooter})

    def test_two_candidates_are_the_coach_s(self) -> None:
        game = build_game()
        match = build_match()
        take_the_ball(match)
        candidates = [
            fielded(match, PlayerRole.STRIKER),
            fielded(match, PlayerRole.WINGER),
        ]

        result = shooter_choice_step(ENGINE, game, match, candidates)

        self.assertIs(result.next.step, FollowOnStep.ASK_SHOOTER_CHOICE)
        self.assertEqual(result.next.kwargs, {"candidates": candidates})


if __name__ == "__main__":
    unittest.main()
