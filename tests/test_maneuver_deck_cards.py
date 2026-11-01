"""
D12 Ball 2.1's maneuver cards as the `maneuvers 2.1` tab prints them
(docs/rules-2.1.md sections 2 and 7): which card's special a player
plays -- the one reading, `RulesEngine.card_special` -- and what each of
the twenty-four specials does when its card wins, staged on a 2.1 match
and run through the effect steps. Whole 2.1 games through the driver
are `test_maneuver_deck.WholeGameTests`, which deal these cards.
"""

from __future__ import annotations

import unittest

from d12ball import maneuver_deck
from d12ball.components import PlayerRole, TeamSide
from d12ball.flow import effects
from d12ball.flow.result import FollowOnStep
from d12ball.flow.rolls import score_skill_test
from d12ball.game import Edition, GameMode
from d12ball.prompts import (
    PendingPrompt, PromptKind, effect_choice_prompt, pending_prompt,
)

from prompt_fixtures import ENGINE, build_game, build_match, challenge


def staged(offense_card: str, defense_card: str, board_size: int = 9):
    """A 2.1 match under way -- decks and roles dealt, a challenger
    sent onto the ball -- with these two cards played as themselves."""
    game = build_game(edition=Edition.TWO, mode=GameMode.TRAINING)
    match = build_match(board_size)
    ENGINE.deal_maneuver_decks(game, match)
    ENGINE.deal_formation_roles(game, match)
    challenge(match)
    match.move_meeple(match.challenger_id, match.ball.zone, match.ball.space_index)
    for side, card_id in (("offense", offense_card), ("defense", defense_card)):
        card = ENGINE.maneuver_catalog.deck_card(card_id)
        key = (
            card.maneuver if card.side == side
            else maneuver_deck.plays_as(ENGINE.maneuver_catalog, card_id, side)[0]
        )
        setattr(match, f"{side}_maneuver", key)
        match.maneuver_cards[side] = [card_id]
    return game, match


def make(match, player_id: str, role: PlayerRole) -> None:
    """Give `player_id` the role a special names, for the test alone."""
    for by_card in match.formation_roles.values():
        if player_id in by_card:
            by_card[player_id] = role.value


def holder(match, side: TeamSide, role: PlayerRole) -> str:
    return next(
        player for player in match.setup_for_side(side).field_players
        if ENGINE.role_of(match, player) == role
    )


def flat(match, player_id: str) -> int:
    return match.board.flat_index(*match.board.meeple_position(player_id))


def ball_flat(match) -> int:
    return match.board.flat_index(match.ball.zone, match.ball.space_index)


class SpecialReadingTests(unittest.TestCase):

    def test_a_special_needs_its_role_on_the_player_making_the_maneuver(self) -> None:
        _, match = staged("P3", "F4")
        make(match, match.active_player_id, PlayerRole.PLAYMAKER)
        make(match, match.challenger_id, PlayerRole.WINGER)
        self.assertEqual(ENGINE.card_special(match, "offense"), "P3")
        # F4 names the Playmaker, and the challenger is a Winger.
        self.assertIsNone(ENGINE.card_special(match, "defense"))
        make(match, match.challenger_id, PlayerRole.PLAYMAKER)
        self.assertEqual(ENGINE.card_special(match, "defense"), "F4")

    def test_a_flipped_card_plays_no_special(self) -> None:
        _, match = staged("P3", "F1")
        make(match, match.challenger_id, PlayerRole.PLAYMAKER)
        # P3 flipped to play Deflect, with an extra card discarded.
        match.defense_maneuver = "deflect"
        match.maneuver_cards["defense"] = ["P3", "B1"]
        self.assertIsNone(ENGINE.card_special(match, "defense"))

    def test_one_point_oh_plays_no_specials(self) -> None:
        _, match = staged("P1", "F1")
        match.maneuver_cards = {}
        self.assertIsNone(ENGINE.card_special(match, "offense"))

    def test_the_plays_mark_a_live_special(self) -> None:
        game, match = staged("P1", "F1")
        hand = match.maneuver_decks[match.ball.possession.value]["hand"]
        hand[:] = ["P1", "P2", "P3", "P4", "F1"]
        make(match, match.active_player_id, PlayerRole.WINGER)
        live = {
            play.card_id for play in ENGINE.card_plays(game, match, "offense")
            if play.special
        }
        self.assertEqual(live, {"P1"})

    def test_the_reveal_names_the_card(self) -> None:
        from d12ball.flow.turn import _chose
        _, match = staged("P3", "F1")
        make(match, match.active_player_id, PlayerRole.PLAYMAKER)
        self.assertEqual(
            _chose(ENGINE, match, "offense", "Pass"),
            "**P3 Pass (Pinpoint)**, its special in play",
        )
        match.maneuver_cards["defense"] = ["P2", "B1"]
        match.defense_maneuver = "deflect"
        self.assertEqual(
            _chose(ENGINE, match, "defense", "Deflect"),
            "**P2 Pass (Pass and Run) played as Deflect**",
        )


class PassTests(unittest.TestCase):

    def test_pass_adds_one_and_asks_no_step(self) -> None:
        game, match = staged("P1", "R1")
        distance, _ = ENGINE.pass_candidates(match, "low_pass")[0]
        speed = match.ball.speed
        result = effects.low_pass_step(
            ENGINE, match, distance, key="low_pass", game=game,
        )
        self.assertEqual(match.ball.speed, min(12, speed + 1))
        self.assertNotIsInstance(result.next, PendingPrompt)

    def test_p1_a_wingers_pass_sets_up_scoring(self) -> None:
        game, match = staged("P1", "R1")
        make(match, match.active_player_id, PlayerRole.WINGER)
        distance, receiver = ENGINE.pass_candidates(match, "low_pass")[0]
        result = effects.low_pass_step(
            ENGINE, match, distance, receiver, key="low_pass", game=game,
        )
        self.assertEqual(result.next.step, FollowOnStep.OFFER_SCORING_ATTEMPT_CHOICE)

    def test_p2_a_midfielder_or_striker_may_run_forward(self) -> None:
        for role, asked in (
            (PlayerRole.MIDFIELDER, True), (PlayerRole.STRIKER, True),
            (PlayerRole.WINGER, False),
        ):
            with self.subTest(role=role):
                game, match = staged("P2", "R1")
                make(match, match.active_player_id, role)
                distance, receiver = ENGINE.pass_candidates(match, "low_pass")[0]
                result = effects.low_pass_step(
                    ENGINE, match, distance, receiver, key="low_pass", game=game,
                )
                self.assertEqual(
                    isinstance(result.next, PendingPrompt)
                    and result.next.kind is PromptKind.PASSER_ADVANCE,
                    asked,
                )

    def test_p3_a_playmaker_reaches_any_teammate_within_two(self) -> None:
        _, match = staged("P3", "R1")
        make(match, match.active_player_id, PlayerRole.PLAYMAKER)
        offered = {d for d, _ in ENGINE.pass_candidates(match, "low_pass")}
        self.assertTrue(
            {d for d, _ in ENGINE.skilled_pass_candidates(match, 2)} <= offered,
        )
        self.assertTrue(
            {d for d, _ in ENGINE.low_pass_candidates(match, None)} <= offered,
        )

    def test_p4_a_fullback_or_defender_may_pass_to_the_playmaker(self) -> None:
        _, match = staged("P4", "R1")
        playmaker = holder(match, TeamSide(match.ball.possession), PlayerRole.PLAYMAKER)
        if playmaker == match.active_player_id:
            # The deal's Playmaker is on the ball: hand the role on.
            other = next(
                p for p in match.setup_for_side(match.ball.possession).field_players
                if p != playmaker
            )
            make(match, other, PlayerRole.PLAYMAKER)
            playmaker = other
        make(match, match.active_player_id, PlayerRole.DEFENDER)
        offered = dict(ENGINE.pass_candidates(match, "low_pass"))
        distance, _ = ENGINE.playmaker_pass(match)
        self.assertIn(distance, offered)
        self.assertIn(playmaker, ENGINE.low_pass_receivers(match, distance))


class DribbleTests(unittest.TestCase):

    def test_dribble_goes_one_and_adds_two(self) -> None:
        game, match = staged("B1", "F1")
        make(match, match.active_player_id, PlayerRole.WINGER)
        speed = match.ball.speed
        result = effects.begin_effect_resolution(
            ENGINE, game, match, "dribble_advance",
        )
        self.assertNotIsInstance(result.next, PendingPrompt)
        self.assertEqual(match.ball.speed, min(12, speed + 2))

    def test_b1_a_striker_may_attempt_scoring(self) -> None:
        from d12ball.flow import arrivals, rolls
        game, match = staged("B1", "F1")
        make(match, match.active_player_id, PlayerRole.STRIKER)
        shooter = match.active_player_id
        result = effects.dribble_advance_step(ENGINE, game, match, 1)
        self.assertEqual(result.next.step, FollowOnStep.OFFER_SCORING_ATTEMPT_CHOICE)
        self.assertEqual(result.next.kwargs["shooter_id"], shooter)
        # A scoring opportunity, but not off a set-up (the author,
        # 2026-10-31) -- and like every 2.1 score attempt it exhausts
        # the shooter 1 after the roll (2026-11-01).
        self.assertIs(result.next.kwargs["set_up"], False)
        arrivals.offer_scoring_attempt_choice(
            ENGINE, game, match, lead_in="", **result.next.kwargs,
        )
        arrivals.take_scoring_opportunity(ENGINE, game, match, shooter_id=shooter)
        self.assertTrue(match.pending_shot_is_set_up)
        self.assertFalse(match.shot_is_set_up)
        saved = type(match).from_dict(match.to_dict(), ENGINE.basic_ruleset)
        self.assertFalse(saved.shot_is_set_up)
        before = match.exhaustion.get(shooter, 0)
        rolls.score_attempt_step(ENGINE, game, match)
        self.assertEqual(match.exhaustion.get(shooter, 0), before + 1)

    def test_b1_a_step_back_offers_the_same_opportunity(self) -> None:
        from d12ball.flow import arrivals, rolls
        game, match = staged("B1", "F1")
        make(match, match.active_player_id, PlayerRole.STRIKER)
        shooter = match.active_player_id
        result = effects.dribble_advance_step(ENGINE, game, match, 1)
        arrivals.offer_scoring_attempt_choice(
            ENGINE, game, match, lead_in="", **result.next.kwargs,
        )
        arrivals.take_scoring_opportunity(ENGINE, game, match, shooter_id=shooter)
        rolls.retract_shot_step(ENGINE, game, match)
        self.assertIs(match.pending_scoring_opportunity["set_up"], False)
        self.assertIsNone(match.pending_shot_offer)

    def test_b2_a_midfielder_or_playmaker_may_advance_two(self) -> None:
        game, match = staged("B2", "F1")
        make(match, match.active_player_id, PlayerRole.MIDFIELDER)
        result = effects.begin_effect_resolution(ENGINE, game, match, "dribble_advance")
        self.assertIs(result.next.kind, PromptKind.DRIBBLE_ADVANCE_CHOICE)
        handler, speed = match.active_player_id, match.ball.speed
        before = flat(match, handler)
        effects.dribble_advance_step(ENGINE, game, match, 2)
        self.assertEqual(abs(flat(match, handler) - before), 2)
        self.assertEqual(match.ball.speed, min(12, speed + 2))

    def test_b3_a_fullback_or_defender_sets_the_speed_by_defensive_skill(self) -> None:
        game, match = staged("B3", "F1")
        make(match, match.active_player_id, PlayerRole.FULLBACK)
        result = effects.dribble_advance_step(ENGINE, game, match, 1)
        self.assertEqual(result.next.step, FollowOnStep.OFFER_SPEED_CHOICE)
        self.assertEqual(result.next.kwargs["skill_type"], "defense")
        # A restart asks the same speed choice.
        restored = effect_choice_prompt(ENGINE, game, match)
        self.assertIs(restored.kind, PromptKind.SPEED_DELTA_CHOICE)
        self.assertEqual(restored.skill_type, "defense")

    def test_b4_a_wingers_teammate_on_the_space_may_take_it(self) -> None:
        game, match = staged("B4", "F1")
        handler = match.active_player_id
        make(match, handler, PlayerRole.WINGER)
        side = match.ball.possession
        destination = match.relative_move_destination(handler, side, 1)
        teammate = next(
            p for p in match.setup_for_side(side).field_players if p != handler
        )
        match.move_meeple(teammate, *destination)
        effects.dribble_advance_step(ENGINE, game, match, 1)
        self.assertIsNone(match.ball_carrier_id)
        self.assertIn(teammate, match.turn_handler_candidates())
        self.assertIn(handler, match.turn_handler_candidates())


class HighBallTests(unittest.TestCase):

    def test_high_ball_goes_three_and_sets_up_after_its_contest(self) -> None:
        game, match = staged("H1", "S1")
        make(match, match.active_player_id, PlayerRole.WINGER)
        self.assertEqual(ENGINE.high_pass_distance_options(match), [3])
        self.assertFalse(ENGINE.high_pass_asks(game, match))
        self.assertTrue(ENGINE.contest_sets_up(match))

    def test_h1_a_fullback_or_defender_may_throw_four(self) -> None:
        game, match = staged("H1", "S1")
        make(match, match.active_player_id, PlayerRole.DEFENDER)
        self.assertEqual(ENGINE.high_pass_distance_options(match), [3, 4])
        self.assertTrue(ENGINE.high_pass_asks(game, match))

    def test_h2_a_playmaker_may_throw_to_the_striker(self) -> None:
        game, match = staged("H2", "S1")
        make(match, match.active_player_id, PlayerRole.PLAYMAKER)
        self.assertTrue(ENGINE.long_shot_offered(match))
        striker = holder(match, TeamSide(match.ball.possession), PlayerRole.STRIKER)
        result = effects.long_shot_step(ENGINE, game, match)
        self.assertEqual(ball_flat(match), flat(match, striker))
        self.assertEqual(result.next.step, FollowOnStep.BEGIN_HIGH_PASS_CONTEST)
        self.assertTrue(ENGINE.contest_sets_up(match))

    def test_h2_long_shot_through_the_driver(self) -> None:
        from d12ball.flow import driver
        from d12ball.flow.driver import Action
        game, match = staged("H2", "S1")
        make(match, match.active_player_id, PlayerRole.PLAYMAKER)
        match.skill_test_winner = "high_pass"
        prompt = PendingPrompt(PromptKind.HIGH_PASS_CHOICE, "")
        from d12ball.prompts import with_options
        prompt = with_options(ENGINE, game, match, prompt)
        self.assertTrue(prompt.options.long_shot)
        step = driver._answer_high_pass_choice(
            ENGINE, game, match, prompt, "long_shot",
        )
        self.assertEqual(step.next.step, FollowOnStep.BEGIN_HIGH_PASS_CONTEST)
        # Refused where the special is not in play.
        make(match, match.active_player_id, PlayerRole.WINGER)
        prompt = with_options(ENGINE, game, match, PendingPrompt(PromptKind.HIGH_PASS_CHOICE, ""))
        self.assertFalse(prompt.options.long_shot)

    def test_h3_a_midfielder_may_throw_two_with_no_contest(self) -> None:
        game, match = staged("H3", "S1")
        make(match, match.active_player_id, PlayerRole.MIDFIELDER)
        self.assertEqual(ENGINE.high_pass_distance_options(match), [2, 3])
        self.assertEqual(ENGINE.uncontested_throws(match), (2,))

    def test_h4_a_winger_or_striker_may_throw_none_or_one(self) -> None:
        game, match = staged("H4", "S1")
        make(match, match.active_player_id, PlayerRole.STRIKER)
        self.assertEqual(ENGINE.high_pass_distance_options(match), [0, 1, 3])
        # Still contested (the author, 2026-10-31).
        self.assertEqual(ENGINE.uncontested_throws(match), ())

    def test_h4_thrown_none_is_the_passers_to_contest_then_set_up(self) -> None:
        from d12ball.flow import arrivals
        game, match = staged("H4", "S1")
        make(match, match.active_player_id, PlayerRole.STRIKER)
        passer, before = match.active_player_id, ball_flat(match)
        result = effects.high_pass_step(ENGINE, match, 0, game=game)
        self.assertEqual(ball_flat(match), before)
        self.assertTrue(match.vertical_ball)
        self.assertEqual(result.next.step, FollowOnStep.BEGIN_HIGH_PASS_CONTEST)
        arrivals.begin_high_pass_contest(ENGINE, game, match, 2)
        # The passer receives it, against the challenger on the space.
        self.assertEqual(
            ENGINE.loose_ball_candidates(match, match.ball.possession), [passer],
        )
        self.assertIn(
            match.challenger_id,
            ENGINE.loose_ball_candidates(match, match.defending_side()),
        )
        # Having won it, they may set up scoring.
        self.assertTrue(ENGINE.contest_sets_up(match))
        saved = type(match).from_dict(match.to_dict(), ENGINE.basic_ruleset)
        self.assertTrue(saved.vertical_ball)
        match.reset_maneuver()
        self.assertFalse(match.vertical_ball)

    def test_h4_thrown_one_is_contested_by_whoever_is_there(self) -> None:
        game, match = staged("H4", "S1")
        make(match, match.active_player_id, PlayerRole.WINGER)
        offense = match.ball.possession
        ahead = match.relative_flat_index(ball_flat(match), offense, 1)
        teammate = next(
            player for player in match.setup_for_side(offense).field_players
            if player != match.active_player_id
        )
        match.move_meeple(teammate, *match.board.position_at_flat_index(ahead))
        result = effects.high_pass_step(ENGINE, match, 1, game=game)
        self.assertFalse(match.vertical_ball)
        self.assertEqual(result.next.step, FollowOnStep.BEGIN_HIGH_PASS_CONTEST)


class ScoreAttemptTests(unittest.TestCase):

    def test_every_score_attempt_exhausts_one_in_two_point_one(self) -> None:
        # "Attempting a score -- whether off set up or not -- always
        # exhausts 1" (the author, 2026-11-01); 1.0's plain shot is free.
        from d12ball.flow import rolls
        for edition, cost in ((Edition.TWO, 1), (Edition.ONE, 0)):
            with self.subTest(edition=edition):
                game = build_game(edition=edition, mode=GameMode.TRAINING)
                match = build_match(9)
                if edition is Edition.TWO:
                    ENGINE.deal_maneuver_decks(game, match)
                    ENGINE.deal_formation_roles(game, match)
                shooter = match.eligible_ball_handlers()[0]
                match.select_ball_handler(shooter)
                match.pending_action = "shoot"
                before = match.exhaustion.get(shooter, 0)
                rolls.score_attempt_step(ENGINE, game, match)
                self.assertEqual(match.exhaustion.get(shooter, 0), before + cost)


class DeflectTests(unittest.TestCase):

    def test_deflect_goes_one_and_takes_one_off(self) -> None:
        game, match = staged("H1", "F2")
        make(match, match.challenger_id, PlayerRole.WINGER)
        before, speed = ball_flat(match), match.ball.speed
        effects.deflection_step(ENGINE, match, "deflect", game)
        self.assertEqual(abs(ball_flat(match) - before), 1)
        self.assertEqual(match.ball.speed, max(1, speed - 1))

    def test_f1_a_fullbacks_deflect_goes_a_space_further(self) -> None:
        game, match = staged("H1", "F1")
        make(match, match.challenger_id, PlayerRole.FULLBACK)
        before = ball_flat(match)
        effects.deflection_step(ENGINE, match, "deflect", game)
        self.assertEqual(abs(ball_flat(match) - before), 2)

    def test_f2_a_defender_or_midfielder_may_follow_the_ball(self) -> None:
        for follow in (True, False):
            with self.subTest(follow=follow):
                game, match = staged("H1", "F2")
                make(match, match.challenger_id, PlayerRole.DEFENDER)
                origin = flat(match, match.challenger_id)
                result = effects.deflection_step(ENGINE, match, "deflect", game)
                # "May follow" is asked, and a restart asks it again.
                self.assertIs(result.next.kind, PromptKind.FOLLOW_BALL)
                self.assertIs(
                    pending_prompt(ENGINE, game, match).kind,
                    PromptKind.FOLLOW_BALL,
                )
                landed = effects.answer_follow(ENGINE, game, match, follow)
                self.assertIsNone(match.pending_follow)
                self.assertEqual(
                    flat(match, match.challenger_id),
                    ball_flat(match) if follow else origin,
                )
                self.assertEqual(landed.next.step, FollowOnStep.BEGIN_LOOSE_BALL)

    def test_a_deflect_into_the_goal_zone_sets_up_scoring_not_may(self) -> None:
        # The rank's Effect, corrected 2026-10-31: "If reaches goal zone,
        # set up scoring" -- taken, not offered: the ball changes hands
        # and the challenger shoots, as in 1.0.
        game, match = staged("H1", "F1")
        make(match, match.challenger_id, PlayerRole.WINGER)
        defense = match.defending_side()
        result = effects.deflection_lands(ENGINE, match, "", True)
        self.assertEqual(result.next.step, FollowOnStep.BEGIN_SHOOTER_CHOICE)
        self.assertEqual(result.next.kwargs["candidates"], [match.challenger_id])
        self.assertEqual(match.ball.possession, defense)
        self.assertEqual(match.ball.speed, 1)

    def test_f3_a_winger_or_striker_may_set_up_scoring_wherever_it_lands(self) -> None:
        from d12ball.flow import arrivals
        game, match = staged("H1", "F3")
        make(match, match.challenger_id, PlayerRole.STRIKER)
        offense, defense = match.ball.possession, match.defending_side()
        result = effects.deflection_step(ENGINE, match, "deflect", game)
        self.assertEqual(result.next.step, FollowOnStep.OFFER_SCORING_ATTEMPT_CHOICE)
        self.assertEqual(result.next.kwargs["shooter_id"], match.challenger_id)
        # Offered: the ball is still the offense's while they choose.
        self.assertEqual(match.ball.possession, offense)
        offered = arrivals.offer_scoring_attempt_choice(
            ENGINE, game, match, lead_in="", **result.next.kwargs,
        )
        self.assertIs(offered.next.kind, PromptKind.SET_UP_ATTEMPT)
        from d12ball.prompts import asked_sides
        self.assertEqual(asked_sides(match, offered.next), (defense,))
        # Declined, the ball lands by the ordinary rule.
        declined = arrivals.decline_scoring_attempt(ENGINE, game, match, 1)
        self.assertEqual(declined.next.step, FollowOnStep.BEGIN_LOOSE_BALL)
        self.assertEqual(match.ball.possession, offense)

    def test_f3_shot_taken_changes_hands(self) -> None:
        from d12ball.flow import arrivals
        game, match = staged("H1", "F3")
        make(match, match.challenger_id, PlayerRole.STRIKER)
        defense = match.defending_side()
        effects.deflection_step(ENGINE, match, "deflect", game)
        arrivals.offer_scoring_attempt_choice(
            ENGINE, game, match, shooter_id=match.challenger_id,
            distance_moved=1, lead_in="", loose_on_decline=True,
        )
        arrivals.take_scoring_opportunity(
            ENGINE, game, match, shooter_id=match.challenger_id,
        )
        self.assertEqual(match.ball.possession, defense)
        self.assertEqual(match.ball.speed, 1)

    def test_f3_a_step_back_from_the_shot_gives_the_ball_back(self) -> None:
        from d12ball.flow import arrivals, rolls
        game, match = staged("H1", "F3")
        make(match, match.challenger_id, PlayerRole.STRIKER)
        offense = match.ball.possession
        result = effects.deflection_step(ENGINE, match, "deflect", game)
        speed = match.ball.speed
        arrivals.offer_scoring_attempt_choice(
            ENGINE, game, match, lead_in="", **result.next.kwargs,
        )
        arrivals.take_scoring_opportunity(
            ENGINE, game, match, shooter_id=match.challenger_id,
        )
        self.assertNotEqual(match.ball.possession, offense)
        rolls.retract_shot_step(ENGINE, game, match)
        self.assertEqual(match.ball.possession, offense)
        self.assertEqual(match.ball.speed, speed)
        self.assertTrue(match.pending_scoring_opportunity["loose_on_decline"])
        declined = arrivals.decline_scoring_attempt(ENGINE, game, match, 1)
        self.assertEqual(declined.next.step, FollowOnStep.BEGIN_LOOSE_BALL)

    def test_f4_a_playmaker_contests_it_on_the_spot(self) -> None:
        game, match = staged("H1", "F4")
        make(match, match.challenger_id, PlayerRole.PLAYMAKER)
        before, speed = ball_flat(match), match.ball.speed
        result = effects.deflection_step(ENGINE, match, "deflect", game)
        self.assertEqual(ball_flat(match), before)
        self.assertEqual(match.ball.speed, speed)
        self.assertEqual(result.next.step, FollowOnStep.BEGIN_LOOSE_BALL)


class StealTests(unittest.TestCase):

    def test_steal_falls_back_and_changes_no_speed(self) -> None:
        game, match = staged("P1", "S3")
        make(match, match.challenger_id, PlayerRole.WINGER)
        result = effects.steal_step(ENGINE, match, "steal", game)
        self.assertEqual(match.ball.possession, TeamSide.VISITING)
        self.assertEqual(match.ball.speed, 1)
        self.assertFalse(result.next.kwargs["speed_choice_after"])

    def test_s1_a_playmaker_sets_the_speed_by_offensive_skill(self) -> None:
        game, match = staged("P1", "S1")
        make(match, match.challenger_id, PlayerRole.PLAYMAKER)
        result = effects.steal_step(ENGINE, match, "steal", game)
        self.assertTrue(result.next.kwargs["speed_choice_after"])
        restored = effect_choice_prompt(ENGINE, game, match)
        self.assertIs(restored.kind, PromptKind.SPEED_DELTA_CHOICE)
        self.assertEqual(restored.skill_type, "offense")

    def test_s2_a_midfielder_keeps_it_where_it_is(self) -> None:
        game, match = staged("P1", "S2")
        make(match, match.challenger_id, PlayerRole.MIDFIELDER)
        before = ball_flat(match)
        effects.steal_step(ENGINE, match, "steal", game)
        self.assertEqual(match.ball.possession, TeamSide.VISITING)
        self.assertEqual(ball_flat(match), before)
        self.assertEqual(flat(match, match.challenger_id), before)

    def test_s3_a_fullback_or_defender_adds_three_to_the_test(self) -> None:
        for role, bonus in ((PlayerRole.DEFENDER, True), (PlayerRole.WINGER, False)):
            with self.subTest(role=role):
                game, match = staged("P1", "S3")
                make(match, match.challenger_id, role)
                contestants, *_ = score_skill_test(
                    ENGINE, game, match,
                    ENGINE.get_player_definition(match.active_player_id),
                    ENGINE.get_player_definition(match.challenger_id),
                )
                defense_detail = contestants[1][2]
                self.assertEqual(
                    any("My Turf!" in line for line in defense_detail), bonus,
                    defense_detail,
                )

    def test_s4_a_winger_or_striker_tosses_it_behind(self) -> None:
        game, match = staged("P1", "S4")
        make(match, match.challenger_id, PlayerRole.WINGER)
        origin = flat(match, match.challenger_id)
        effects.steal_step(ENGINE, match, "steal", game)
        self.assertEqual(flat(match, match.challenger_id), origin)
        self.assertNotEqual(match.ball_carrier_id, match.challenger_id)


class PressureTests(unittest.TestCase):

    def test_r1_a_defenders_pressure_turns_it_over_with_nobody_moving(self) -> None:
        game, match = staged("B1", "R1")
        make(match, match.challenger_id, PlayerRole.DEFENDER)
        handler, before = match.active_player_id, ball_flat(match)
        result = effects.pressure_step(ENGINE, match, "pressure", game)
        self.assertEqual(match.ball.possession, TeamSide.VISITING)
        self.assertEqual(ball_flat(match), before)
        self.assertEqual(flat(match, handler), before)
        self.assertEqual(result.next.step, FollowOnStep.BEGIN_RUN_BACK)

    def test_r2_a_fullback_or_playmaker_sends_it_behind_and_may_follow(self) -> None:
        for follow in (True, False):
            with self.subTest(follow=follow):
                game, match = staged("B1", "R2")
                make(match, match.challenger_id, PlayerRole.FULLBACK)
                handler = match.active_player_id
                origin = flat(match, match.challenger_id)
                result = effects.pressure_step(ENGINE, match, "pressure", game)
                self.assertNotEqual(match.ball_carrier_id, handler)
                if result.next.kind is PromptKind.FOLLOW_BALL:
                    finished = effects.answer_follow(ENGINE, game, match, follow)
                    self.assertEqual(
                        finished.next.step, FollowOnStep.FINISH_MANEUVER_RESOLUTION,
                    )
                    self.assertEqual(
                        flat(match, match.challenger_id),
                        ball_flat(match) if follow else origin,
                    )

    def test_r3_a_midfielders_pressure_exhausts_the_handler_too(self) -> None:
        for role, extra in ((PlayerRole.MIDFIELDER, 1), (PlayerRole.WINGER, 0)):
            with self.subTest(role=role):
                game, match = staged("B1", "R3")
                make(match, match.challenger_id, role)
                handler = match.active_player_id
                effects.pressure_step(ENGINE, match, "pressure", game)
                # The shove is a space, a token; R3's Midfielder adds one.
                self.assertEqual(match.exhaustion.get(handler, 0), 1 + extra)

    def test_r4_a_striker_or_winger_contests_it_in_place(self) -> None:
        game, match = staged("B1", "R4")
        make(match, match.challenger_id, PlayerRole.STRIKER)
        before = ball_flat(match)
        result = effects.pressure_step(ENGINE, match, "pressure", game)
        self.assertEqual(ball_flat(match), before)
        self.assertEqual(result.next.step, FollowOnStep.BEGIN_LOOSE_BALL)


if __name__ == "__main__":
    unittest.main()
