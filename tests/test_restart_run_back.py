"""
D12 Ball 2.0's restarts run everybody back (docs/rules-2.0.md 4.9, the
author, 2026-10-24): a new play, a time out and halftime send every
fielded player back to their own zone -- the Fullback, the Playmaker
and the Striker to their own spaces, everyone else to an open space of
their zone, their coach choosing -- for nothing, and the Coaching
Choice comes after, on the side as it then stands. A steal's run back
sends a unique role to their own space too. See "Turnovers: steals and
new plays" in docs/design/possession-and-turnovers.md.
"""

from __future__ import annotations

import unittest

from d12ball.components import (
    CoachingOccasion,
    MatchState,
    PlayerRole,
    TeamSide,
    Zone,
)
from d12ball.flow import driver, periods, turnovers, windows
from d12ball.flow.result import FollowOn, FollowOnStep, StepResult
from d12ball.game import Edition, GameMode
from d12ball.prompts import PromptKind, pending_prompt

from roster import fielded
from test_driver_full_game import RULESET
from test_formation_roles import kickoff, space_of

HOME = TeamSide.HOME
VISITING = TeamSide.VISITING
UNIQUE = (PlayerRole.FULLBACK, PlayerRole.PLAYMAKER, PlayerRole.STRIKER)
STANDARD = (PlayerRole.DEFENDER, PlayerRole.MIDFIELDER, PlayerRole.WINGER)


def scramble(match: MatchState) -> None:
    """Everybody of both sides out of their own zone: home's to the
    visitors' end and the visitors' to home's, all on one space."""
    for side, zone in ((HOME, Zone.VISITORS_ZONE), (VISITING, Zone.HOME_ZONE)):
        for card in match.setup_for_side(side).field_players:
            match.board.place_meeple(card, zone, 0)


def run(engine, game, match, result: StepResult) -> list[PromptKind]:
    """
    Drive the restart to its first question that is not the run back,
    answering every run-back question with its first space -- and
    reloading the match after each, as a restart would. Returns the
    run-back kinds answered.
    """
    answered = []
    driver.advance(engine, game, match, result)
    for _ in range(40):
        prompt = pending_prompt(engine, game, match)
        if prompt is None or prompt.kind is not PromptKind.RUN_BACK_SPACE:
            return answered
        answered.append(prompt.kind)
        outcome = driver.apply(engine, game, match, driver.Action(
            PromptKind.RUN_BACK_SPACE, "",
            {"space_index": prompt.options.space_indices[0]},
        ))
        assert not isinstance(outcome, driver.Refusal), outcome
        while isinstance(outcome.result.next, FollowOn):
            outcome = driver.advance(
                engine, game, match, StepResult(next=outcome.result.next),
            )
        reloaded = MatchState.from_dict(match.to_dict(), RULESET)
        assert pending_prompt(engine, game, reloaded) == pending_prompt(
            engine, game, match,
        )
    raise AssertionError("the run back did not settle")


def placed_in_own_zone(test, engine, match) -> None:
    """Every fielded player in their own zone, each unique role on their
    space, and nobody of a side sharing a space with a teammate."""
    for side in (HOME, VISITING):
        setup = match.setup_for_side(side)
        taken = []
        for card in setup.field_players:
            zone, space = space_of(match, card)
            test.assertEqual(zone, setup.assigned_zone(card), card)
            taken.append((zone, space))
        test.assertEqual(len(set(taken)), len(taken), side)
        for role in UNIQUE:
            card = fielded(match, role, side)
            test.assertEqual(
                space_of(match, card)[1],
                match.unique_role_space(
                    side,
                    {
                        PlayerRole.FULLBACK: "own_goal",
                        PlayerRole.PLAYMAKER: "midfield",
                        PlayerRole.STRIKER: "opponent_goal",
                    }[role],
                ),
            )


class NewPlayTests(unittest.TestCase):
    """A 2.0 new play runs everybody back, free, before its window."""

    def new_play(self, board_size: int = 9):
        engine, game, match = kickoff(Edition.TWO, board_size)
        scramble(match)
        before = dict(match.exhaustion)
        result = turnovers.begin_run_back(engine, game, match, new_play=True)
        return engine, game, match, result, before

    def test_the_unique_roles_go_straight_to_their_spaces(self) -> None:
        engine, game, match, result, _ = self.new_play()
        self.assertIsNotNone(match.pending_replace)
        self.assertEqual(
            sorted(match.run_back_placing()),
            sorted(
                fielded(match, role, side)
                for side in (HOME, VISITING) for role in STANDARD
            ),
        )
        for side in (HOME, VISITING):
            for role in UNIQUE:
                card = fielded(match, role, side)
                self.assertEqual(
                    space_of(match, card)[0],
                    match.setup_for_side(side).assigned_zone(card),
                )
        self.assertIn("Fullback, the Playmaker and the Striker", result.narration[0])

    def test_every_other_player_is_placed_for_nothing(self) -> None:
        engine, game, match, result, before = self.new_play()
        answered = run(engine, game, match, result)
        self.assertTrue(answered)
        placed_in_own_zone(self, engine, match)
        self.assertEqual(match.exhaustion, before)
        self.assertIsNone(match.pending_replace)

    def test_the_space_question_carries_no_price(self) -> None:
        engine, game, match, result, _ = self.new_play()
        driver.advance(engine, game, match, result)
        prompt = pending_prompt(engine, game, match)
        self.assertIs(prompt.kind, PromptKind.RUN_BACK_SPACE)
        self.assertTrue(prompt.options.free)
        self.assertNotIn("away", prompt.ask)

    def test_the_coaching_choice_comes_after_the_run_back(self) -> None:
        engine, game, match, result, _ = self.new_play()
        run(engine, game, match, result)
        prompt = pending_prompt(engine, game, match)
        self.assertIs(prompt.kind, PromptKind.COACHING_OFFER)
        self.assertEqual(prompt.side, TeamSide(match.ball.possession))

    def test_the_window_opens_on_the_side_as_it_stands(self) -> None:
        engine, game, match, result, _ = self.new_play()
        run(engine, game, match, result)
        standing = {
            card: space_of(match, card) for card in match.home.field_players
        }
        # A saved arrangement somewhere else is never snapped back to.
        for card in match.home.field_players:
            match.assigned_positions[card] = [Zone.HOME_ZONE.value, 0]
        windows.open_substitution_window(
            engine, game, match, HOME, CoachingOccasion.NEW_PLAY,
        )
        self.assertEqual(
            {card: space_of(match, card) for card in match.home.field_players},
            standing,
        )

    def test_one_point_oh_still_resets_and_offers_the_window(self) -> None:
        engine, game, match = kickoff(Edition.ONE, 9)
        scramble(match)
        result = turnovers.begin_run_back(engine, game, match, new_play=True)
        self.assertIsNone(match.pending_replace)
        self.assertIsInstance(result.next, FollowOn)
        self.assertIs(result.next.step, FollowOnStep.BEGIN_SUBSTITUTION_WINDOW)
        self.assertNotIn("pending_replace", match.to_dict())


class DiscordButtonTests(unittest.TestCase):
    """The run-back buttons quote a price only where there is one."""

    def test_a_free_run_back_names_the_space_alone(self) -> None:
        from cogs.d12ball_views import RunBackChoiceView
        from test_d12ball_formations import build_cog

        engine, game, match = kickoff(Edition.TWO, 9)
        scramble(match)
        result = turnovers.begin_run_back(engine, game, match, new_play=True)
        driver.advance(engine, game, match, result)
        prompt = pending_prompt(engine, game, match)
        cog = build_cog()
        cog.engine = engine
        game.match_state = match.to_dict()
        cog.games[game.game_id] = game
        labels = [
            item.label
            for item in RunBackChoiceView(
                cog, game.game_id, prompt.player_id,
            ).children
            if isinstance(getattr(item, "label", None), str)
        ]
        self.assertTrue(labels)
        self.assertFalse(any("away" in label for label in labels), labels)


class StealTests(unittest.TestCase):
    """A steal still charges and still leaves alone whoever is home."""

    def test_a_unique_role_runs_back_to_their_own_space(self) -> None:
        engine, game, match = kickoff(Edition.TWO, 9)
        # No species abilities, so nobody is offered a Fly first.
        game.mode = GameMode.TRAINING
        striker = fielded(match, PlayerRole.STRIKER)
        match.board.place_meeple(striker, Zone.MIDFIELD, 0)
        before = match.exhaustion.get(striker, 0)
        result = turnovers.begin_run_back(engine, game, match)
        run(engine, game, match, result)
        self.assertEqual(
            space_of(match, striker), (Zone.VISITORS_ZONE, 2),
        )
        self.assertGreater(match.exhaustion.get(striker, 0), before)

    def test_a_standard_role_is_never_sent_onto_a_unique_space(self) -> None:
        engine, game, match = kickoff(Edition.TWO, 9)
        defender = fielded(match, PlayerRole.DEFENDER)
        fullback = fielded(match, PlayerRole.FULLBACK)
        match.board.place_meeple(fullback, Zone.HOME_ZONE, 1)
        match.board.place_meeple(defender, Zone.MIDFIELD, 0)
        spaces = match.placement_spaces_in_zone(
            HOME, Zone.HOME_ZONE, defender,
        )
        self.assertNotIn(0, spaces)


class TimeOutTests(unittest.TestCase):
    """A 2.0 time out runs everybody back, then both windows."""

    def test_the_run_back_comes_before_the_windows(self) -> None:
        engine, game, match = kickoff(Edition.TWO, 9)
        driver.advance(
            engine, game, match,
            StepResult(next=FollowOn(FollowOnStep.FINISH_SETUP_COACHING)),
        )
        scramble(match)
        result = windows.begin_time_out(engine, game, match)
        self.assertIsNotNone(match.pending_replace)
        run(engine, game, match, result)
        placed_in_own_zone(self, engine, match)
        prompt = pending_prompt(engine, game, match)
        self.assertIs(prompt.kind, PromptKind.COACHING_HUB)
        self.assertEqual(
            match.coaching_occasion, CoachingOccasion.TIME_OUT,
        )


class HalftimeTests(unittest.TestCase):
    """2.0's halftime runs everybody back, then its own sequence."""

    def test_the_run_back_comes_before_the_halftime_stages(self) -> None:
        engine, game, match = kickoff(Edition.TWO, 9)
        scramble(match)
        result = periods.begin_halftime(engine, game, match)
        self.assertIsNone(match.pending_halftime_stage)
        self.assertIsNotNone(match.pending_replace)
        run(engine, game, match, result)
        placed_in_own_zone(self, engine, match)
        self.assertIsNotNone(match.pending_halftime_stage)
        self.assertFalse(match.pending_run_back)


class WholeGameTests(unittest.TestCase):
    """Whole 2.0 games with their roles dealt, through the driver with a
    reload after every click (`test_driver_full_game.play`): every new
    play, time out and halftime runs back, in every mode."""

    def test_whole_games_finish_in_every_mode(self) -> None:
        from test_driver_full_game import play
        from test_maneuver_deck import build_engine, build_match, two_point_oh

        for mode in (GameMode.TRAINING, GameMode.STANDARD, GameMode.ADVANCED):
            for seed in (11, 13):
                with self.subTest(mode=mode, seed=seed):
                    game = two_point_oh(mode)
                    match = build_match()
                    dealer = build_engine()
                    dealer.rng.seed(seed)
                    dealer.deal_maneuver_decks(game, match)
                    dealer.deal_formation_roles(game, match)
                    game, match, answered = play(seed, game, match)
                    self.assertTrue(game.is_finished)
                    self.assertIn(PromptKind.RUN_BACK_SPACE, answered)
                    self.assertIsNone(match.pending_replace)


class SaveTests(unittest.TestCase):
    def test_a_restart_under_way_is_saved_and_read_back(self) -> None:
        engine, game, match = kickoff(Edition.TWO, 9)
        scramble(match)
        turnovers.begin_run_back(engine, game, match, new_play=True)
        saved = match.to_dict()
        self.assertEqual(
            MatchState.from_dict(saved, RULESET).pending_replace,
            match.pending_replace,
        )

    def test_a_match_with_no_restart_under_way_saves_no_key(self) -> None:
        _, _, match = kickoff(Edition.TWO, 9)
        self.assertNotIn("pending_replace", match.to_dict())


if __name__ == "__main__":
    unittest.main()
