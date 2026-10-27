"""
D12 Ball 2.0's maneuver cards as the `maneuvers 2.0` tab prints them
(docs/rules-2.0.md section 7): the deck of twelve different two-headed
cards, and what each new card -- and each card whose 2.0 wording
differs from 1.0's -- does when it wins, staged on a 2.0 match and run
through the effect steps. Whole 2.0 games through the driver are
`test_maneuver_deck.WholeGameTests`, which deal these cards.
"""

from __future__ import annotations

import unittest
from collections import Counter
from unittest import mock

from d12ball import maneuver_deck
from d12ball.components import PlayerRole, TeamSide
from d12ball.flow import effects
from d12ball.flow.result import FollowOn, FollowOnStep
from d12ball.flow.rolls import score_skill_test
from d12ball.game import Edition, GameMode
from d12ball.prompts import PendingPrompt, PromptKind, effect_choice_prompt

from prompt_fixtures import ENGINE, MANEUVERS, build_game, build_match, challenge


def staged(offense: str, defense: str, board_size: int = 9):
    """A 2.0 match under way -- decks and roles dealt, a challenger
    sent -- with these two cards played."""
    game = build_game(edition=Edition.TWO, mode=GameMode.TRAINING)
    match = build_match(board_size)
    ENGINE.deal_maneuver_decks(game, match)
    ENGINE.deal_formation_roles(game, match)
    challenge(match)
    # A challenger is sent onto the ball's space (Law 6.1).
    match.move_meeple(match.challenger_id, match.ball.zone, match.ball.space_index)
    match.offense_maneuver = offense
    match.defense_maneuver = defense
    return game, match


def holder(match, side: TeamSide, role: PlayerRole) -> str:
    return next(
        player for player in match.setup_for_side(side).field_players
        if ENGINE.role_of(match, player) == role
    )


def flat(match, player_id: str) -> int:
    return match.board.flat_index(*match.board.meeple_position(player_id))


def ball_flat(match) -> int:
    return match.board.flat_index(match.ball.zone, match.ball.space_index)


class DeckOfTheTabTests(unittest.TestCase):

    def test_twelve_different_two_headed_cards_paired_by_row(self) -> None:
        cards = maneuver_deck.deck_cards(MANEUVERS)
        self.assertEqual(len(cards), 18)
        two_headed = [card for card in cards if maneuver_deck.is_basic_card(card)]
        self.assertEqual(len(two_headed), 12)
        self.assertEqual(len(set(two_headed)), 12)
        for card in two_headed:
            offense = maneuver_deck.plays_as(MANEUVERS, card, "offense")
            defense = maneuver_deck.plays_as(MANEUVERS, card, "defense")
            self.assertEqual(offense.rank, defense.rank)
            self.assertEqual(offense.deck_index, defense.deck_index)
            self.assertEqual(
                offense.deck_index, maneuver_deck.basic_card_row(card),
            )
        self.assertEqual(
            maneuver_deck.plays_as(MANEUVERS, "basic_1_2", "offense").key,
            "curved_pass",
        )
        self.assertEqual(
            maneuver_deck.plays_as(MANEUVERS, "basic_1_2", "defense").key,
            "follow",
        )

    def test_a_deck_saved_with_four_alike_still_plays(self) -> None:
        # `basic_1` is row 1, the id every card had before the tab.
        self.assertEqual(
            maneuver_deck.plays_as(MANEUVERS, "basic_1", "offense").key,
            "low_pass",
        )

    def test_one_point_oh_never_meets_a_variant(self) -> None:
        for side in ("offense", "defense"):
            for tier in ("basic", "advanced"):
                for card in MANEUVERS.for_tier(side, tier):
                    self.assertNotEqual(card.tier, "variant")
            self.assertEqual(len(MANEUVERS.for_tier(side, "basic")), 3)

    def test_every_card_the_deck_plays_has_an_effect(self) -> None:
        for card in dict.fromkeys(maneuver_deck.deck_cards(MANEUVERS)):
            for side in ("offense", "defense"):
                maneuver = maneuver_deck.plays_as(MANEUVERS, card, side)
                if maneuver is not None:
                    self.assertIn(maneuver.key, effects.EFFECT_OFFERS)

    def test_a_variant_costs_the_time_its_card_says(self) -> None:
        _, match = staged("set_up", "steal")
        self.assertEqual(ENGINE.maneuver_clock_cost(match, "set_up"), 2)
        self.assertEqual(ENGINE.maneuver_clock_cost(match, "curved_pass"), 1)


class PassRankTests(unittest.TestCase):

    def test_pass_adds_two_and_asks_no_step(self) -> None:
        game, match = staged("low_pass", "pressure")
        distance, _ = ENGINE.pass_candidates(match, "low_pass")[0]
        speed = match.ball.speed
        result = effects.low_pass_step(
            ENGINE, match, distance, key="low_pass", game=game,
        )
        self.assertEqual(match.ball.speed, min(12, speed + 2))
        self.assertNotIsInstance(result.next, PendingPrompt)

    def test_curved_pass_reaches_any_teammate_within_two(self) -> None:
        _, match = staged("curved_pass", "pressure")
        self.assertEqual(
            ENGINE.pass_candidates(match, "curved_pass"),
            ENGINE.skilled_pass_candidates(match, 2),
        )

    def test_pass_and_run_moves_the_passer_and_not_the_speed(self) -> None:
        game, match = staged("pass_and_run", "pressure")
        passer = match.active_player_id
        before, speed = flat(match, passer), match.ball.speed
        distance, _ = ENGINE.pass_candidates(match, "pass_and_run")[0]
        effects.low_pass_step(
            ENGINE, match, distance, key="pass_and_run", game=game,
        )
        self.assertEqual(abs(flat(match, passer) - before), 1)
        self.assertEqual(match.ball.speed, speed)

    def test_reset_play_puts_the_ball_with_the_playmaker(self) -> None:
        game, match = staged("reset_play", "pressure")
        playmaker = holder(match, TeamSide.HOME, PlayerRole.PLAYMAKER)
        effects.reset_play_step(ENGINE, game, match)
        self.assertEqual(match.ball_carrier_id, playmaker)
        self.assertEqual(ball_flat(match), flat(match, playmaker))


class DribbleRankTests(unittest.TestCase):

    def test_dribble_goes_one_and_adds_two(self) -> None:
        game, match = staged("dribble_advance", "deflect")
        speed = match.ball.speed
        result = effects.begin_effect_resolution(
            ENGINE, game, match, "dribble_advance",
        )
        self.assertNotIsInstance(result.next, PendingPrompt)
        self.assertEqual(match.ball.speed, min(12, speed + 2))

    def test_advance_asks_one_or_two_and_leaves_the_speed(self) -> None:
        game, match = staged("advance", "deflect")
        result = effects.begin_effect_resolution(ENGINE, game, match, "advance")
        self.assertIs(result.next.kind, PromptKind.DRIBBLE_ADVANCE_CHOICE)
        handler, speed = match.active_player_id, match.ball.speed
        before = flat(match, handler)
        effects.dribble_advance_step(ENGINE, game, match, 2)
        self.assertEqual(abs(flat(match, handler) - before), 2)
        self.assertEqual(match.ball.speed, speed)

    def test_spin_moves_a_teammate_then_asks_the_speed(self) -> None:
        game, match = staged("spin", "deflect")
        result = effects.begin_effect_resolution(ENGINE, game, match, "spin")
        self.assertIs(result.next.kind, PromptKind.SPIN_MOVE)
        player_id, zone, space_index, _ = ENGINE.spin_moves(match)[0]
        result = effects.spin_move_step(
            ENGINE, game, match, player_id, zone, space_index,
        )
        self.assertEqual(
            match.board.meeple_position(player_id), (zone, space_index),
        )
        self.assertEqual(result.next.step, FollowOnStep.OFFER_SPEED_CHOICE)
        # A restart now asks the speed, not the move again.
        self.assertIs(
            effect_choice_prompt(ENGINE, game, match).kind,
            PromptKind.SPEED_DELTA_CHOICE,
        )

    def test_drive_carries_the_ball_and_the_teammate_may_take_it(self) -> None:
        game, match = staged("drive", "deflect")
        handler = match.active_player_id
        distance, teammate = ENGINE.pass_candidates(match, "drive")[0]
        self.assertIn(
            handler, ENGINE.low_pass_receivers(match, distance, "drive"),
        )
        speed = match.ball.speed
        effects.drive_step(ENGINE, match, distance, teammate, game)
        self.assertEqual(flat(match, handler), flat(match, teammate))
        self.assertEqual(match.ball_carrier_id, teammate)
        self.assertEqual(match.ball.speed, max(1, speed - 2))


class HighBallRankTests(unittest.TestCase):

    def test_high_ball_and_set_up_are_one_distance_each(self) -> None:
        _, match = staged("high_pass", "steal")
        self.assertEqual(ENGINE.high_pass_distance_options(match), [3])
        self.assertTrue(ENGINE.contest_sets_up(match))
        _, match = staged("set_up", "steal")
        self.assertEqual(ENGINE.high_pass_distance_options(match), [2])
        self.assertFalse(ENGINE.contest_sets_up(match))

    def test_long_shot_goes_to_the_striker_and_is_contested(self) -> None:
        game, match = staged("long_shot", "steal")
        striker = holder(match, TeamSide.HOME, PlayerRole.STRIKER)
        result = effects.long_shot_step(ENGINE, game, match)
        self.assertEqual(ball_flat(match), flat(match, striker))
        self.assertEqual(result.next.step, FollowOnStep.BEGIN_HIGH_PASS_CONTEST)
        self.assertTrue(ENGINE.contest_sets_up(match))

    def test_cross_lands_up_to_three_and_vertical_ball_up_to_one(self) -> None:
        _, match = staged("vertical_ball", "steal")
        self.assertTrue(set(ENGINE.setup_pass_distances(match)) <= {0, 1})
        _, match = staged("setup_pass", "steal")
        self.assertIn(2, ENGINE.setup_pass_distances(match))


class DeflectRankTests(unittest.TestCase):

    def test_a_fullbacks_deflect_goes_a_space_further(self) -> None:
        _, match = staged("high_pass", "deflect")
        fullback = holder(match, TeamSide.VISITING, PlayerRole.FULLBACK)
        defender = ENGINE.get_player_definition(fullback)
        self.assertEqual(
            effects.deflection_numbers(ENGINE, match, defender, "deflect")[0],
            2,
        )

    def test_follow_takes_the_defender_with_the_ball(self) -> None:
        game, match = staged("high_pass", "follow")
        speed = match.ball.speed
        effects.deflection_step(ENGINE, match, "follow", game)
        self.assertEqual(flat(match, match.challenger_id), ball_flat(match))
        self.assertEqual(match.ball.speed, min(12, speed + 3))

    def test_boot_goes_two_and_block_nowhere(self) -> None:
        game, match = staged("high_pass", "boot")
        before = ball_flat(match)
        effects.deflection_step(ENGINE, match, "boot", game)
        self.assertEqual(abs(ball_flat(match) - before), 2)
        game, match = staged("high_pass", "block")
        before = ball_flat(match)
        result = effects.deflection_step(ENGINE, match, "block", game)
        self.assertEqual(ball_flat(match), before)
        self.assertEqual(result.next.step, FollowOnStep.BEGIN_LOOSE_BALL)


class StealRankTests(unittest.TestCase):

    def test_pickpocket_turns_it_over_where_it_is(self) -> None:
        game, match = staged("low_pass", "pickpocket")
        before = ball_flat(match)
        result = effects.steal_step(ENGINE, match, "pickpocket", game)
        self.assertEqual(match.ball.possession, TeamSide.VISITING)
        self.assertEqual(ball_flat(match), before)
        self.assertEqual(result.next.step, FollowOnStep.BEGIN_RUN_BACK)
        self.assertFalse(result.next.kwargs["speed_choice_after"])

    def test_toss_hands_it_to_the_nearest_teammate_behind(self) -> None:
        game, match = staged("low_pass", "toss")
        thief = match.challenger_id
        effects.steal_step(ENGINE, match, "toss", game)
        self.assertEqual(match.ball.possession, TeamSide.VISITING)
        self.assertNotEqual(match.ball_carrier_id, thief)
        self.assertEqual(ball_flat(match), flat(match, match.ball_carrier_id))

    def test_a_pickpocket_that_beats_a_pinpoint_owes_its_pass(self) -> None:
        game, match = staged("skilled_pass", "pickpocket")
        effects.steal_step(ENGINE, match, "pickpocket", game)
        self.assertEqual(
            match.pending_effect_continuation["kind"],
            effects.FREE_LOW_PASS_OWED,
        )

    def test_my_turf_adds_three_for_a_defender_or_midfielder(self) -> None:
        game, match = staged("dribble_advance", "my_turf")
        match.ball.speed = 1
        offense = ENGINE.get_player_definition(match.active_player_id)
        for role, bonus in (
            (PlayerRole.DEFENDER, True),
            (PlayerRole.MIDFIELDER, True),
            (PlayerRole.STRIKER, False),
        ):
            with self.subTest(role=role):
                defense = ENGINE.get_player_definition(
                    holder(match, TeamSide.VISITING, role),
                )
                with mock.patch.object(ENGINE.rng, "randint", return_value=5):
                    sides, *_ = score_skill_test(
                        ENGINE, game, match, offense, defense,
                    )
                self.assertEqual(
                    "+3 My Turf!" in sides[1][2], bonus, sides[1][2],
                )


class PressureRankTests(unittest.TestCase):

    def test_control_steals_for_a_defender_alone(self) -> None:
        for role, stolen in (
            (PlayerRole.DEFENDER, True), (PlayerRole.MIDFIELDER, False),
        ):
            with self.subTest(role=role):
                game, match = staged("dribble_advance", "control")
                match.challenger_id = holder(match, TeamSide.VISITING, role)
                match.move_meeple(
                    match.challenger_id, match.ball.zone, match.ball.space_index,
                )
                effects.pressure_step(ENGINE, match, "control", game)
                self.assertEqual(
                    match.ball.possession == TeamSide.VISITING, stolen,
                )

    def test_stay_close_exhausts_the_handler_and_slows_the_ball(self) -> None:
        game, match = staged("dribble_advance", "stay_close")
        match.ball.speed = 5
        handler = match.active_player_id
        before = match.exhaustion.get(handler, 0)
        effects.stay_close_step(ENGINE, match, game)
        self.assertEqual(match.exhaustion.get(handler, 0), before + 1)
        self.assertEqual(match.ball.speed, 3)

    def test_stress_plays_it_back_and_the_defender_follows(self) -> None:
        game, match = staged("dribble_advance", "stress")
        handler = match.active_player_id
        result = effects.stress_step(ENGINE, match, game)
        if result.next.step is FollowOnStep.BEGIN_OWN_GOAL_ROLL:
            self.assertEqual(match.ball_carrier_id, handler)
            return
        self.assertNotEqual(match.ball_carrier_id, handler)
        self.assertEqual(flat(match, match.challenger_id), ball_flat(match))


if __name__ == "__main__":
    unittest.main()
