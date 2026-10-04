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
from d12ball.flow import driver
from d12ball.prompts import (
    Action,
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

    def test_a_coaching_window_says_what_it_has_left(self) -> None:
        """The allowance is the window's own count, in the words the
        Discord caption heads the hub with: setup's unlimited, the
        shootout's one, a half's two."""
        said = {}
        for name, match, prompt in asked_prompts():
            if not isinstance(prompt.options, CoachingHubOptions):
                continue
            with self.subTest(name):
                self.assertEqual(
                    prompt.options.allowance,
                    ENGINE.substitution_allowance_label(match),
                )
                self.assertEqual(
                    prompt.options.to_dict()["allowance"],
                    prompt.options.allowance,
                )
                said[name] = prompt.options.allowance
        self.assertEqual(said["setup coaching"], "No substitution limit")
        self.assertEqual(said["full-time coaching"], "1 substitution left")

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

    def test_a_pickup_carries_what_each_candidate_would_be_charged(
        self,
    ) -> None:
        """Every pickup charges a token a space, a time out's included
        (the author, 2026-09-26), and the prompt says so per player --
        the same amount the pickup then charges."""
        played = 0
        for case in CASES:
            fixture = case.build()
            prompt = pending_prompt(ENGINE, fixture.game, fixture.match)
            if prompt is None or prompt.kind is not PromptKind.BALL_RECOVERY:
                continue
            options = prompt.options
            self.assertEqual(options.costs, options.distances)
            for player_id, cost in zip(options.player_ids, options.costs):
                for from_time_out in (False, True):
                    with self.subTest(case.name, player_id=player_id,
                                      from_time_out=from_time_out):
                        game, match = _built(case)
                        match.pending_recovery_from_time_out = from_time_out
                        before = match.exhaustion.get(player_id, 0)
                        run = driver.apply(
                            ENGINE, game, match,
                            Action(prompt.kind, "", {"player_id": player_id}),
                        )
                        self.assertNotIsInstance(run, driver.Refusal)
                        self.assertEqual(
                            match.exhaustion.get(player_id, 0), before + cost,
                        )
                        played += 1
        self.assertTrue(played)

    def test_a_pickup_cannot_be_declined(self) -> None:
        """A pickup offers nobody the choice to send nobody: its options
        are a pick among players with no decline, and the driver
        refuses one (the Charter's "Sending nobody")."""
        seen = False
        for case in CASES:
            game, match = _built(case)
            prompt = pending_prompt(ENGINE, game, match)
            if prompt is None or prompt.kind is not PromptKind.BALL_RECOVERY:
                continue
            seen = True
            with self.subTest(case.name):
                self.assertIsInstance(prompt.options, PlayerOptions)
                for action in (
                    Action(prompt.kind, "decline", {}),
                    Action(prompt.kind, "", {}),
                ):
                    self.assertIsInstance(
                        driver.apply(ENGINE, game, match, action),
                        driver.Refusal,
                    )
        self.assertTrue(seen)

    def test_a_distance_names_the_space_it_lands_on(self) -> None:
        """
        A coach choosing a distance is choosing a space, and which way
        a kind moves is the prompt's to say -- a pass forward, the push
        back the other way, a dribble the handler rather than the
        ball -- so a button's label and a web page's lit space read
        one measure and no frontend decides the direction.
        """
        seen = set()
        for name, match, prompt in asked_prompts():
            options = prompt.options
            if not isinstance(options, DistanceOptions) or not options.distances:
                continue
            seen.add(prompt.kind)
            with self.subTest(name):
                self.assertEqual(len(options.landings), len(options.distances))
                for distance, landing in zip(options.distances, options.landings):
                    self.assertEqual(options.landing(distance), landing)
                    if prompt.kind in (
                        PromptKind.DRIBBLE_ADVANCE_CHOICE,
                        PromptKind.DRIBBLE_BURST_CHOICE,
                    ):
                        expected = match.relative_move_destination(
                            match.active_player_id, match.ball.possession,
                            distance,
                        )
                    else:
                        expected = match.ball_destination(
                            match.ball.possession, distance,
                        )
                    self.assertEqual(landing, expected)
        self.assertIn(PromptKind.HIGH_PASS_CHOICE, seen)
        self.assertIn(PromptKind.DRIBBLE_ADVANCE_CHOICE, seen)
        self.assertIn(PromptKind.SETUP_PASS_CHOICE, seen)

    def test_the_move_ends_where_the_landing_said(self) -> None:
        """The dribble and the Cross, played: the handler, and the
        ball, end on the space the prompt named."""
        played = set()
        for case in CASES:
            if case.name not in ("dribble advance", "setup pass"):
                continue
            played.add(case.name)
            prompt = pending_prompt(ENGINE, *_built(case))
            for distance, landing in zip(
                prompt.options.distances, prompt.options.landings,
            ):
                with self.subTest(case.name, distance=distance):
                    game, match = _built(case)
                    mover = match.active_player_id
                    run = driver.apply(
                        ENGINE, game, match,
                        Action(prompt.kind, "", {"distance": distance}),
                    )
                    self.assertNotIsInstance(run, driver.Refusal)
                    if prompt.kind is PromptKind.DRIBBLE_ADVANCE_CHOICE:
                        self.assertEqual(
                            match.board.meeple_position(mover), landing,
                        )
                    else:
                        self.assertEqual(
                            (match.ball.zone, match.ball.space_index), landing,
                        )
        self.assertEqual(len(played), 2)


def _built(case):
    fixture = case.build()
    return fixture.game, fixture.match


if __name__ == "__main__":
    unittest.main()
