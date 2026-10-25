"""
D12 Ball 2.0's new play runs everybody back (docs/rules-2.0.md 4.9, the
author, 2026-10-24): every fielded player goes back to their own zone --
the Fullback, the Playmaker and the Striker to their own spaces,
everyone else to an open space of their zone, their coach choosing --
for nothing, and the Coaching Choice comes after, on the side as it then
stands. A time out's and halftime's Coaching Choice opens with the
unique roles back on their spaces and everybody else where they stand,
for the coach to put right before finishing (4.9d, the author,
2026-10-25). A steal's run back is the Charter's, unique roles and all.
See "2.0: a restart is a run back" in
docs/design/possession-and-turnovers.md.
"""

from __future__ import annotations

import unittest

from d12ball.components import (
    CoachingOccasion,
    MatchState,
    PlayerRole,
    RuleRefusal,
    TeamSide,
    Zone,
)
from d12ball.flow import driver, turnovers, windows
from d12ball.flow.result import FollowOn, FollowOnStep, StepResult
from d12ball.game import AIOpponent, Edition, GameMode
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
    """A steal's run back is the Charter's: everybody out of their zone,
    a unique role included, to an open space of it, a token a space."""

    def test_a_unique_role_runs_back_to_any_open_space(self) -> None:
        engine, game, match = kickoff(Edition.TWO, 9)
        # No species abilities, so nobody is offered a Fly first.
        game.mode = GameMode.TRAINING
        striker = fielded(match, PlayerRole.STRIKER)
        match.board.place_meeple(striker, Zone.MIDFIELD, 0)
        self.assertEqual(
            match.placement_spaces_in_zone(
                HOME, Zone.VISITORS_ZONE, striker,
            ),
            match.open_spaces_in_zone(HOME, Zone.VISITORS_ZONE),
        )
        before = match.exhaustion.get(striker, 0)
        result = turnovers.begin_run_back(engine, game, match)
        run(engine, game, match, result)
        self.assertEqual(space_of(match, striker)[0], Zone.VISITORS_ZONE)
        self.assertGreater(match.exhaustion.get(striker, 0), before)
        self.assertIsNone(match.pending_replace)

    def test_a_steal_reserves_no_space(self) -> None:
        engine, game, match = kickoff(Edition.TWO, 9)
        defender = fielded(match, PlayerRole.DEFENDER)
        fullback = fielded(match, PlayerRole.FULLBACK)
        match.board.place_meeple(fullback, Zone.HOME_ZONE, 1)
        match.board.place_meeple(defender, Zone.MIDFIELD, 0)
        self.assertIn(
            0, match.placement_spaces_in_zone(HOME, Zone.HOME_ZONE, defender),
        )


def unique_spaces_taken(test, match, side) -> None:
    """Each of `side`'s unique roles on their own space."""
    for role, area in (
        (PlayerRole.FULLBACK, "own_goal"),
        (PlayerRole.PLAYMAKER, "midfield"),
        (PlayerRole.STRIKER, "opponent_goal"),
    ):
        test.assertEqual(
            space_of(match, fielded(match, role, side))[1],
            match.unique_role_space(side, area),
            role,
        )


def answer_as_dinky(test, engine, game, match) -> list[str]:
    """Answer every Coaching Choice the way Dinky does until none is
    open, a reload after each; the choices made, in order."""
    dinky = engine.ai_strategies[AIOpponent.DINKY]
    choices = []
    for _ in range(40):
        prompt = pending_prompt(engine, game, match)
        if prompt is None or prompt.kind is not PromptKind.COACHING_HUB:
            return choices
        action = dinky.choose(prompt, game, match, prompt.side)
        outcome = driver.apply(engine, game, match, action)
        test.assertNotIsInstance(outcome, driver.Refusal, outcome)
        while isinstance(outcome.result.next, FollowOn):
            outcome = driver.advance(
                engine, game, match, StepResult(next=outcome.result.next),
            )
        reloaded = MatchState.from_dict(match.to_dict(), RULESET)
        test.assertEqual(
            pending_prompt(engine, game, reloaded),
            pending_prompt(engine, game, match),
        )
        choices.append(action.choice)
    raise AssertionError("the Coaching Choices did not close")


class ScatteredSideTests(unittest.TestCase):
    """4.9d: a time out's or halftime's Coaching Choice sends the unique
    roles back as it opens; everybody else stays, and the coach puts
    them right, a player at a time, before finishing."""

    def open_halftime(self, board_size: int = 9):
        engine, game, match = kickoff(Edition.TWO, board_size)
        scramble(match)
        result = windows.open_substitution_window(
            engine, game, match, HOME, CoachingOccasion.HALFTIME,
        )
        return engine, game, match, result

    def test_the_unique_roles_go_back_as_the_window_opens(self) -> None:
        engine, game, match = kickoff(Edition.TWO, 9)
        scramble(match)
        standing = {
            fielded(match, role): space_of(match, fielded(match, role))
            for role in STANDARD
        }
        result = windows.open_substitution_window(
            engine, game, match, HOME, CoachingOccasion.HALFTIME,
        )
        self.assertTrue(result.board_changed)
        unique_spaces_taken(self, match, HOME)
        self.assertEqual(
            {card: space_of(match, card) for card in standing}, standing,
        )
        self.assertIn("back on their own spaces", result.next.ask)

    def test_the_window_holds_until_everyone_is_in_place(self) -> None:
        engine, game, match, _ = self.open_halftime()
        self.assertGreater(match.standing_arrangement_faults(HOME), 0)
        self.assertIsNotNone(engine.coaching_finish_refusal(match, HOME, game))
        refused = driver.apply(engine, game, match, driver.Action(
            PromptKind.COACHING_HUB, "done", {"side": "home"},
        ))
        self.assertIsInstance(refused, driver.Refusal)

    def test_each_change_leaves_fewer_out_of_place(self) -> None:
        engine, game, match, _ = self.open_halftime()
        prompt = pending_prompt(engine, game, match)
        arrangement = prompt.options.arrangement
        before = match.standing_arrangement_faults(HOME)
        defender = fielded(match, PlayerRole.DEFENDER)
        changes = arrangement.edits(defender)
        self.assertTrue(changes)
        self.assertTrue(
            all(edit.kind in ("move", "role", "trade") for edit in changes)
        )
        move = next(edit for edit in changes if edit.kind == "move")
        outcome = driver.apply(engine, game, match, driver.Action(
            PromptKind.COACHING_HUB, "arrange",
            {"side": "home", "arrangement": move.answer()},
        ))
        self.assertNotIsInstance(outcome, driver.Refusal, outcome)
        after = match.standing_arrangement_faults(HOME)
        self.assertLess(after, before)
        said = "\n".join(outcome.result.narration)
        self.assertIn("moves to", said)
        self.assertIn(f"{after} still out of place.", said)

    def test_a_change_that_puts_nobody_right_is_refused(self) -> None:
        engine, game, match, _ = self.open_halftime()
        holders, placed = match.current_arrangement(HOME)
        before = match.to_dict()
        # The side as it stands, every stray keeping their role: nobody
        # fewer out of place.
        with self.assertRaises(RuleRefusal):
            match.arrange_side(
                HOME, holders, placed, strays=match.arrangement_strays(HOME),
            )
        self.assertEqual(match.to_dict(), before)

    def stray_defender(self):
        """A Defender open play left in a midfield space with room: out
        of their zone, and nothing else out of place."""
        engine, game, match = kickoff(Edition.TWO, 9)
        defender = fielded(match, PlayerRole.DEFENDER)
        empty = next(
            index for index in range(3)
            if not set(match.board.spaces[Zone.MIDFIELD][index])
            & set(match.home.field_players)
        )
        match.board.place_meeple(defender, Zone.MIDFIELD, empty)
        windows.open_substitution_window(
            engine, game, match, HOME, CoachingOccasion.HALFTIME,
        )
        return engine, game, match, defender

    def test_a_stray_keeps_their_role_until_the_coach_decides(self) -> None:
        engine, game, match, defender = self.stray_defender()
        self.assertEqual(match.arrangement_strays(HOME), [defender])
        self.assertEqual(engine.role_of(match, defender), PlayerRole.DEFENDER)
        self.assertIsNotNone(engine.coaching_finish_refusal(match, HOME, game))
        refused = driver.apply(engine, game, match, driver.Action(
            PromptKind.COACHING_HUB, "done", {"side": "home"},
        ))
        self.assertIsInstance(refused, driver.Refusal)

    def apply_edit(self, engine, game, match, edit):
        outcome = driver.apply(engine, game, match, driver.Action(
            PromptKind.COACHING_HUB, "arrange",
            {"side": "home", "arrangement": edit.answer()},
        ))
        self.assertNotIsInstance(outcome, driver.Refusal, outcome)
        done = driver.apply(engine, game, match, driver.Action(
            PromptKind.COACHING_HUB, "done", {"side": "home"},
        ))
        self.assertNotIsInstance(done, driver.Refusal, done)

    def test_a_stray_sent_back_keeps_their_role(self) -> None:
        engine, game, match, defender = self.stray_defender()
        arrangement = pending_prompt(engine, game, match).options.arrangement
        back = next(
            edit for edit in arrangement.edits(defender)
            if edit.kind == "move" and edit.space.zone == Zone.HOME_ZONE
        )
        self.assertEqual(back.space.takes, PlayerRole.DEFENDER)
        self.apply_edit(engine, game, match, back)
        self.assertEqual(engine.role_of(match, defender), PlayerRole.DEFENDER)
        self.assertEqual(space_of(match, defender)[0], Zone.HOME_ZONE)
        self.assertEqual(engine.shape_name(match, HOME), "2-2-2")

    def test_a_stray_given_a_new_role_stays_where_they_stand(self) -> None:
        engine, game, match, defender = self.stray_defender()
        standing = space_of(match, defender)
        arrangement = pending_prompt(engine, game, match).options.arrangement
        stay = next(
            edit for edit in arrangement.edits(defender)
            if edit.kind == "role"
        )
        self.assertEqual(stay.space.takes, PlayerRole.MIDFIELDER)
        self.apply_edit(engine, game, match, stay)
        self.assertEqual(space_of(match, defender), standing)
        self.assertEqual(engine.role_of(match, defender), PlayerRole.MIDFIELDER)
        self.assertEqual(match.home.assigned_zone(defender), Zone.MIDFIELD)
        self.assertEqual(engine.shape_name(match, HOME), "1-3-2")

    def test_only_a_change_that_deals_with_the_stray_is_offered(self) -> None:
        engine, game, match, defender = self.stray_defender()
        arrangement = pending_prompt(engine, game, match).options.arrangement
        winger = fielded(match, PlayerRole.WINGER)
        # Nothing else is out of place: a change to somebody else is
        # offered only where it deals with the stray too -- a trade with
        # them, each taking the role of where they then stand.
        changes = arrangement.edits(winger)
        self.assertTrue(changes)
        for edit in changes:
            self.assertEqual((edit.kind, edit.other), ("trade", defender))
            self.assertEqual(edit.strays, ())

    def test_dinky_puts_a_scattered_side_right(self) -> None:
        engine, game, match, _ = self.open_halftime()
        choices = answer_as_dinky(self, engine, game, match)
        self.assertIn("arrange", choices)
        self.assertEqual(choices[-1], "done")
        self.assertEqual(match.standing_arrangement_faults(HOME), 0)
        unique_spaces_taken(self, match, HOME)
        setup = match.home
        for card in setup.field_players:
            self.assertEqual(space_of(match, card)[0], setup.assigned_zone(card))

    def test_one_point_oh_still_snaps_back(self) -> None:
        engine, game, match = kickoff(Edition.ONE, 9)
        dealt = {
            card: space_of(match, card) for card in match.home.field_players
        }
        scramble(match)
        windows.open_substitution_window(
            engine, game, match, HOME, CoachingOccasion.HALFTIME,
        )
        self.assertEqual(
            {card: space_of(match, card) for card in dealt}, dealt,
        )


class TimeOutTests(unittest.TestCase):
    """A 2.0 time out sends each side's unique roles back as its window
    opens, and resets nothing after the windows."""

    def test_both_windows_put_their_side_right(self) -> None:
        engine, game, match = kickoff(Edition.TWO, 9)
        driver.advance(
            engine, game, match,
            StepResult(next=FollowOn(FollowOnStep.FINISH_SETUP_COACHING)),
        )
        scramble(match)
        driver.advance(
            engine, game, match, windows.begin_time_out(engine, game, match),
        )
        self.assertIsNone(match.pending_replace)
        prompt = pending_prompt(engine, game, match)
        self.assertIs(prompt.kind, PromptKind.COACHING_HUB)
        self.assertEqual(match.coaching_occasion, CoachingOccasion.TIME_OUT)
        unique_spaces_taken(self, match, prompt.side)
        choices = answer_as_dinky(self, engine, game, match)
        self.assertEqual(choices.count("done"), 2)
        for side in (HOME, VISITING):
            unique_spaces_taken(self, match, side)
            self.assertEqual(match.standing_arrangement_faults(side), 0)


class WholeGameTests(unittest.TestCase):
    """Whole 2.0 games with their roles dealt, through the driver with a
    reload after every click (`test_driver_full_game.play`): every new
    play runs back, in every mode."""

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
