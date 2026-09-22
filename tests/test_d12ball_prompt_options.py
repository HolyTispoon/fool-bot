"""
What a prompt's options carry beyond the candidates themselves.

A button's label is the frontend's, but what it says is the model's: the
price on a run back, the walk-in a challenger pays, the zone a meeple is
moved within, which side of the board a maneuver hand is. Each used to be
measured by the view (and again by the web page) off the match, which is
the second reading CLAUDE.md forbids -- a distance computed in a view is
one the driver cannot see. These pin that the options carry it, aligned
with the candidates, and that it is the same measure the flow charges.
"""

import unittest

from d12ball.components import TeamSide
from d12ball.prompts import (
    ManeuverOptions,
    PlayerOptions,
    PromptKind,
    SendOptions,
    SpaceOptions,
    CoachingHubOptions,
    DistanceOptions,
    pending_prompt,
)
from prompt_fixtures import CASES, ENGINE


def asked_prompts():
    for case in CASES:
        if not case.asked:
            continue
        fixture = case.build()
        prompt = pending_prompt(ENGINE, fixture.game, fixture.match)
        if prompt is not None and prompt.options is not None:
            yield case.name, fixture.match, prompt


class OptionsCarryTheirMeasureTests(unittest.TestCase):
    def test_every_candidate_with_a_price_carries_it(self) -> None:
        seen = set()
        for name, match, prompt in asked_prompts():
            options = prompt.options
            if isinstance(options, SendOptions) or (
                isinstance(options, PlayerOptions)
                and prompt.kind is PromptKind.BALL_RECOVERY
            ):
                with self.subTest(name):
                    seen.add(prompt.kind)
                    self.assertEqual(
                        len(options.distances), len(options.player_ids),
                    )
                    for player_id, distance in zip(
                        options.player_ids, options.distances,
                    ):
                        self.assertEqual(
                            distance, match.distance_to_ball(player_id),
                        )
        self.assertIn(PromptKind.MANEUVER_CHALLENGE, seen)
        self.assertIn(PromptKind.LOOSE_BALL_PICK, seen)
        self.assertIn(PromptKind.BALL_RECOVERY, seen)

    def test_a_run_back_space_carries_its_zone_and_its_cost(self) -> None:
        seen = False
        for name, match, prompt in asked_prompts():
            if not isinstance(prompt.options, SpaceOptions):
                continue
            seen = True
            options = prompt.options
            with self.subTest(name):
                side = match.side_for_player(prompt.player_id)
                self.assertEqual(
                    options.zone,
                    match.setup_for_side(side).assigned_zone(prompt.player_id),
                )
                self.assertEqual(
                    len(options.distances), len(options.space_indices),
                )
                for space_index, distance in zip(
                    options.space_indices, options.distances,
                ):
                    self.assertEqual(
                        distance,
                        match.run_back_distance(
                            prompt.player_id, options.zone, space_index,
                        ),
                    )
        self.assertTrue(seen)

    def test_a_maneuver_hand_names_its_side_of_the_board(self) -> None:
        seen = False
        for name, match, prompt in asked_prompts():
            if not isinstance(prompt.options, ManeuverOptions):
                continue
            seen = True
            with self.subTest(name):
                for hand in prompt.options.hands:
                    self.assertIsInstance(hand.team_side, TeamSide)
                    expected = (
                        match.ball.possession if hand.side == "offense"
                        else match.defending_side()
                    )
                    self.assertEqual(hand.team_side, expected)
        self.assertTrue(seen)

    def test_a_reposition_names_the_zone_it_is_within(self) -> None:
        seen = False
        for name, match, prompt in asked_prompts():
            if not isinstance(prompt.options, CoachingHubOptions):
                continue
            side = TeamSide(prompt.side)
            for entry in prompt.options.repositions:
                seen = True
                with self.subTest(name, player=entry.player_id):
                    self.assertEqual(
                        entry.zone,
                        match.setup_for_side(side).assigned_zone(
                            entry.player_id,
                        ),
                    )
        self.assertTrue(seen)

    def test_a_pass_out_is_said_rather_than_inferred(self) -> None:
        for name, match, prompt in asked_prompts():
            options = prompt.options
            if not isinstance(options, DistanceOptions):
                continue
            with self.subTest(name):
                if prompt.kind is PromptKind.SETUP_PASS_CHOICE:
                    self.assertEqual(options.may_pass_out, not options.distances)
                else:
                    self.assertFalse(options.may_pass_out)


if __name__ == "__main__":
    unittest.main()
