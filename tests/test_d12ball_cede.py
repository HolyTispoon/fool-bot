"""
Ceding the ball to coach: the turn a side out of shooting range takes
when it would rather have the window than the possession.

The rule is two predicates and one state change --
MatchState.may_cede_possession and MatchState.cede_possession -- plus
the flow they open: the ceding coach's window, the other coach's reply,
and a tail that runs no run back. See "Ceding the ball" in
docs/living-rules.md.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

from cogs.d12ball import D12Ball
from cogs.d12ball_views import CedeConfirmView, PlayerActionView
from d12ball.components import (
    CoachingOccasion,
    MatchState,
    TeamSide,
    Zone,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.game import D12BallGame, Team


def build_cog() -> D12Ball:
    cog = object.__new__(D12Ball)
    cog.games = {}
    cog.player_catalog = load_player_catalog()
    cog.maneuver_catalog = load_maneuver_catalog()
    cog.basic_ruleset = load_basic_ruleset()
    cog.team_emojis = {}
    cog.condition_emojis = {}
    cog.refresh_match_image = mock.AsyncMock()
    cog.drop_turn_prompt = mock.AsyncMock()
    cog.begin_substitution_window = mock.AsyncMock()
    cog.begin_ball_recovery = mock.AsyncMock()
    cog.finish_maneuver_resolution = mock.AsyncMock()
    cog.announce_run_back = mock.AsyncMock()
    cog.end_period = mock.AsyncMock()
    return cog


def build_game() -> D12BallGame:
    return D12BallGame(
        game_id="g1",
        game_number=1,
        guild_id=1,
        channel_id=1,
        message_id=None,
        player_1_id=111,
        player_2_id=222,
        player_1_team=Team.ORANGE,
        player_2_team=Team.PURPLE,
        player_1_name="One",
        player_2_name="Two",
        home_player_number=1,
        visiting_player_number=2,
    )


def build_interaction() -> SimpleNamespace:
    return SimpleNamespace(
        user=SimpleNamespace(id=111, display_name="One"),
        channel=None,
        guild=None,
        message=SimpleNamespace(content="One, it is your turn."),
        followup=SimpleNamespace(
            send=mock.AsyncMock(return_value=SimpleNamespace(id=999)),
        ),
        response=SimpleNamespace(
            defer=mock.AsyncMock(),
            edit_message=mock.AsyncMock(),
            send_message=mock.AsyncMock(),
        ),
        edit_original_response=mock.AsyncMock(),
    )


class CedeOfferTests(unittest.TestCase):
    """When the choice is on the table at all."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    def build_match(self) -> MatchState:
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
        )
        match.ball.possession = TeamSide.HOME
        match.ball.zone = Zone.MIDFIELD
        match.ball.space_index = 0
        return match

    def test_offered_out_of_shooting_range_and_not_in_it(self) -> None:
        # The same read as the shot, from the other end: a side with a
        # shot on is not stuck, and the rule is for a side that is.
        match = self.build_match()
        self.assertTrue(match.may_cede_possession())

        match.ball.zone = Zone.VISITORS_GOAL
        match.ball.space_index = 0
        self.assertTrue(match.can_attempt_score())
        self.assertFalse(match.may_cede_possession())

    def test_a_spent_declaration_takes_it_away(self) -> None:
        match = self.build_match()
        self.assertTrue(match.may_cede_possession())

        match.declared_substitution.add(TeamSide.HOME.value)
        self.assertFalse(match.may_cede_possession())
        # It is once a half each: the other side still has theirs.
        self.assertTrue(match.may_declare_coaching(TeamSide.VISITING))

    def test_an_empty_bench_does_not_take_it_away(self) -> None:
        # The window is the whole Coaching Choice, not the substitution
        # alone, so a side with nobody to bring on may still want it.
        match = self.build_match()
        match.home.team_board.bench = []
        match.home.team_board.back_bench = []

        self.assertEqual(match.substitution_pool(TeamSide.HOME), [])
        self.assertTrue(match.may_cede_possession())

    def test_the_prompt_says_why_each_button_is_missing(self) -> None:
        cog = build_cog()
        game = build_game()
        match = self.build_match()
        handler = match.home.field_players[0]
        match.move_meeple(handler, Zone.MIDFIELD, 0)
        match.select_ball_handler(handler)
        game.match_state = match.to_dict()
        cog.games[game.game_id] = game

        self.assertIn(
            "cede the ball to coach", cog.build_turn_prompt(game, match),
        )

        match.declared_substitution.add(TeamSide.HOME.value)
        self.assertIn(
            "already called its Coaching Choice this half",
            cog.build_turn_prompt(game, match),
        )

    def test_the_button_goes_with_the_declaration(self) -> None:
        cog = build_cog()
        game = build_game()
        match = self.build_match()
        handler = match.home.field_players[0]
        match.move_meeple(handler, Zone.MIDFIELD, 0)
        match.select_ball_handler(handler)
        match.declared_substitution.add(TeamSide.HOME.value)
        game.match_state = match.to_dict()
        cog.games[game.game_id] = game

        self.assertEqual(
            [
                item.label
                for item in PlayerActionView(cog, game.game_id).children
            ],
            ["Maneuver"],
        )


class CedeStateTests(unittest.TestCase):
    """What ceding does to the match."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    def build_match(self) -> MatchState:
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
        )
        match.ball.possession = TeamSide.HOME
        match.ball.zone = Zone.MIDFIELD
        match.ball.space_index = 0
        match.ball.speed = 4
        return match

    def test_possession_crosses_where_the_ball_stands(self) -> None:
        match = self.build_match()
        handler = match.home.field_players[0]
        match.move_meeple(handler, Zone.MIDFIELD, 0)
        match.select_ball_handler(handler)
        match.ball_carrier_id = handler

        receiving = match.cede_possession()

        self.assertEqual(receiving, TeamSide.VISITING)
        self.assertEqual(match.ball.possession, TeamSide.VISITING)
        self.assertEqual((match.ball.zone, match.ball.space_index),
                         (Zone.MIDFIELD, 0))
        self.assertEqual(match.ball.speed, 1)
        # The turn that was being taken is over, carrier included: the
        # side handed the ball picks its own handler.
        self.assertIsNone(match.active_player_id)
        self.assertIsNone(match.ball_carrier_id)
        self.assertTrue(match.pending_cede)

    def test_it_costs_its_flat_space_minute(self) -> None:
        # The clock cost is read back off pending_run_back_distance by
        # whatever the tail still owes, and ceding costs the same flat
        # 1 space minute as any other maneuver (2026-08-16) -- the
        # same 1 reset_maneuver already leaves there, restated
        # explicitly.
        match = self.build_match()
        match.cede_possession()

        self.assertEqual(match.pending_run_back_distance, 1)
        self.assertFalse(match.advance_time(match.pending_run_back_distance))
        self.assertEqual(match.scoreboard.time, 1)

    def test_the_flag_survives_a_save(self) -> None:
        # It has to outlive two coaching windows, which is the whole
        # reason it is on the match rather than in a call.
        match = self.build_match()
        match.cede_possession()

        restored = MatchState.from_dict(match.to_dict(), self.rules)
        self.assertTrue(restored.pending_cede)

    def test_resetting_the_turn_clears_it(self) -> None:
        match = self.build_match()
        match.cede_possession()
        match.reset_maneuver()

        self.assertFalse(match.pending_cede)


class CedeOccasionTests(unittest.TestCase):
    """The window a cede opens is charged but never offered."""

    def test_it_is_charged_like_a_new_play_but_not_asked(self) -> None:
        ceded = CoachingOccasion.CEDED
        self.assertTrue(ceded.spends_declaration)
        self.assertFalse(ceded.asks_declaration)
        self.assertTrue(ceded.counts_against_the_half)
        self.assertTrue(ceded.offers_positioning)
        self.assertTrue(ceded.retires_outgoing_players)
        self.assertEqual(ceded.substitution_allowance, 2)

    def test_only_a_new_play_asks(self) -> None:
        for occasion in CoachingOccasion:
            with self.subTest(occasion=occasion):
                self.assertEqual(
                    occasion.asks_declaration,
                    occasion == CoachingOccasion.NEW_PLAY,
                )

    def test_opening_it_spends_the_declaration_without_asking(self) -> None:
        match = MatchState.standard(
            catalog=load_player_catalog(),
            ruleset=load_basic_ruleset(),
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
        )
        match.open_coaching_window(TeamSide.HOME, CoachingOccasion.CEDED)

        self.assertTrue(match.pending_coaching_declared)
        self.assertFalse(match.may_declare_coaching(TeamSide.HOME))

    def test_the_reply_costs_the_answering_side_nothing(self) -> None:
        match = MatchState.standard(
            catalog=load_player_catalog(),
            ruleset=load_basic_ruleset(),
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
        )
        match.open_coaching_window(
            TeamSide.VISITING, CoachingOccasion.CEDED, is_response=True,
        )

        self.assertTrue(match.pending_coaching_declared)
        self.assertTrue(match.may_declare_coaching(TeamSide.VISITING))


class CedeFlowTests(unittest.IsolatedAsyncioTestCase):
    """The cog's half: the two windows, and the tail behind them."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    def build(self):
        cog = build_cog()
        game = build_game()
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
        )
        match.ball.possession = TeamSide.HOME
        match.ball.zone = Zone.MIDFIELD
        match.ball.space_index = 0
        handler = match.home.field_players[0]
        match.move_meeple(handler, Zone.MIDFIELD, 0)
        match.select_ball_handler(handler)
        game.match_state = match.to_dict()
        cog.games[game.game_id] = game
        return cog, game, match

    async def test_ceding_opens_the_ceding_coach_s_window(self) -> None:
        cog, game, match = self.build()
        interaction = build_interaction()

        with mock.patch("cogs.d12ball.save_games"):
            await cog.begin_cede(interaction, game, match)

        cog.drop_turn_prompt.assert_awaited_once()
        cog.begin_substitution_window.assert_awaited_once()
        _, kwargs = cog.begin_substitution_window.call_args
        self.assertEqual(kwargs["occasion"], CoachingOccasion.CEDED)
        self.assertIn("cede the ball", kwargs["lead_in"])
        # The side that gave it up coaches first.
        self.assertEqual(
            cog.begin_substitution_window.call_args.args[3], TeamSide.HOME,
        )

    async def test_under_last_possession_it_ends_the_period(self) -> None:
        cog, game, match = self.build()
        match.scoreboard.last_possession = True
        interaction = build_interaction()

        with mock.patch("cogs.d12ball.save_games"):
            await cog.begin_cede(interaction, game, match)

        cog.end_period.assert_awaited_once()
        cog.begin_substitution_window.assert_not_awaited()
        # Nothing is left set for the second half to trip over.
        self.assertFalse(match.pending_cede)

    async def test_the_reply_is_the_same_occasion(self) -> None:
        cog, game, match = self.build()
        match.cede_possession()
        match.open_coaching_window(TeamSide.HOME, CoachingOccasion.CEDED)
        interaction = build_interaction()

        with mock.patch("cogs.d12ball.save_games"):
            await cog.finish_substitution_window(interaction, game, match)

        cog.begin_substitution_window.assert_awaited_once()
        _, kwargs = cog.begin_substitution_window.call_args
        self.assertEqual(kwargs["occasion"], CoachingOccasion.CEDED)
        self.assertTrue(kwargs["is_response"])
        cog.announce_run_back.assert_not_awaited()

    async def test_the_reply_closing_runs_no_run_back(self) -> None:
        # Both windows opened on their own coach's arrangement, so
        # there is nothing displaced to run back -- but the cede still
        # costs its own flat space minute (2026-08-16).
        cog, game, match = self.build()
        match.cede_possession()
        match.move_meeple(
            match.visiting.field_players[0], Zone.MIDFIELD, 0,
        )
        match.open_coaching_window(
            TeamSide.VISITING, CoachingOccasion.CEDED, is_response=True,
        )
        interaction = build_interaction()

        with mock.patch("cogs.d12ball.save_games"):
            await cog.finish_substitution_window(interaction, game, match)

        cog.announce_run_back.assert_not_awaited()
        cog.finish_maneuver_resolution.assert_awaited_once()
        _, kwargs = cog.finish_maneuver_resolution.call_args
        self.assertEqual(kwargs["distance_moved"], 1)
        self.assertTrue(kwargs["turnover_occurred"])
        self.assertFalse(match.pending_cede)

    async def test_a_ball_nobody_is_standing_on_is_picked_up(self) -> None:
        # The receiving side's arrangement covers their zones, not
        # wherever open play left the ball, so they send somebody --
        # the same step an out-of-bounds ball asks for.
        cog, game, match = self.build()
        match.cede_possession()
        for player_id in list(match.board.spaces[Zone.MIDFIELD][0]):
            match.board.place_meeple(player_id, Zone.HOME_GOAL, 0)
        interaction = build_interaction()

        with mock.patch("cogs.d12ball.save_games"):
            await cog.finish_cede(interaction, game, match)

        cog.begin_ball_recovery.assert_awaited_once()
        cog.finish_maneuver_resolution.assert_not_awaited()
        self.assertTrue(match.pending_ball_recovery)


class CedeConfirmTests(unittest.IsolatedAsyncioTestCase):
    """The click, and the way back from it."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    def build(self):
        cog = build_cog()
        cog.begin_cede = mock.AsyncMock()
        cog.user_controls_possession = mock.Mock(return_value=True)
        game = build_game()
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
        )
        match.ball.possession = TeamSide.HOME
        match.ball.zone = Zone.MIDFIELD
        match.ball.space_index = 0
        handler = match.home.field_players[0]
        match.move_meeple(handler, Zone.MIDFIELD, 0)
        match.select_ball_handler(handler)
        game.match_state = match.to_dict()
        cog.games[game.game_id] = game
        return cog, game, match

    async def test_the_button_asks_before_it_acts(self) -> None:
        cog, game, _ = self.build()
        interaction = build_interaction()

        view = PlayerActionView(cog, game.game_id)
        await view.choose_action(interaction, "cede", "Cede ball to coach")

        interaction.response.edit_message.assert_awaited_once()
        _, kwargs = interaction.response.edit_message.call_args
        self.assertIn("Cede the ball?", kwargs["content"])
        self.assertIsInstance(kwargs["view"], CedeConfirmView)
        cog.begin_cede.assert_not_awaited()

    async def test_back_puts_the_prompt_back_word_for_word(self) -> None:
        cog, game, _ = self.build()
        interaction = build_interaction()

        view = CedeConfirmView(cog, game.game_id, "One, it is your turn.")
        await view.back(interaction)

        _, kwargs = interaction.response.edit_message.call_args
        self.assertEqual(kwargs["content"], "One, it is your turn.")
        self.assertIsInstance(kwargs["view"], PlayerActionView)
        cog.begin_cede.assert_not_awaited()

    async def test_confirming_cedes(self) -> None:
        cog, game, _ = self.build()
        interaction = build_interaction()

        view = CedeConfirmView(cog, game.game_id, "One, it is your turn.")
        await view.confirm(interaction)

        cog.begin_cede.assert_awaited_once()

    async def test_a_stale_confirmation_is_refused(self) -> None:
        # The prompt underneath stays live while the confirm is up, so
        # the match can have moved on before the second click.
        cog, game, match = self.build()
        match.declared_substitution.add(TeamSide.HOME.value)
        game.match_state = match.to_dict()
        interaction = build_interaction()

        view = CedeConfirmView(cog, game.game_id, "One, it is your turn.")
        await view.confirm(interaction)

        cog.begin_cede.assert_not_awaited()
        interaction.followup.send.assert_awaited_once()

    async def test_a_stale_cede_click_is_refused(self) -> None:
        cog, game, match = self.build()
        match.ball.zone = Zone.VISITORS_GOAL
        match.ball.space_index = 0
        match.move_meeple(match.active_player_id, Zone.VISITORS_GOAL, 0)
        game.match_state = match.to_dict()
        interaction = build_interaction()

        view = PlayerActionView(cog, game.game_id)
        await view.choose_action(interaction, "cede", "Cede ball to coach")

        interaction.response.send_message.assert_awaited_once()
        self.assertIn(
            "shooting range",
            interaction.response.send_message.call_args.args[0],
        )


class CedeOffensiveChoiceTests(unittest.IsolatedAsyncioTestCase):
    """`/d12ball offensive_choice` must not walk over an open cede."""

    async def test_it_refuses_and_points_at_resume(self) -> None:
        # The turn was reset before either window opened, so none of
        # the command's other refusals would notice -- and its reset
        # would drop a coach's window and the pick-up the ball may
        # still owe.
        cog = build_cog()
        game = build_game()
        match = MatchState.standard(
            catalog=load_player_catalog(),
            ruleset=load_basic_ruleset(),
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
        )
        match.pending_cede = True
        game.match_state = match.to_dict()
        cog.games[game.game_id] = game
        cog.send_turn_prompt = mock.AsyncMock()
        cog.defer_and_get_match = mock.AsyncMock(return_value=(game, match))
        interaction = build_interaction()

        with mock.patch("cogs.d12ball.save_games"):
            await D12Ball.offensive_choice.callback(cog, interaction)

        cog.send_turn_prompt.assert_not_awaited()
        self.assertIn(
            "ceded", interaction.followup.send.call_args.args[0],
        )


class CedeRecoveryTests(unittest.TestCase):
    """What a restart mid-cede comes back to."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    def build(self):
        cog = build_cog()
        game = build_game()
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
        )
        match.ball.possession = TeamSide.HOME
        match.ball.zone = Zone.MIDFIELD
        match.ball.space_index = 0
        match.cede_possession()
        game.match_state = match.to_dict()
        cog.games[game.game_id] = game
        return cog, game, match

    def test_an_open_window_comes_back_as_the_hub(self) -> None:
        # Never the offer: ceding is what bought the window, so neither
        # coach is ever asked whether to take it.
        cog, game, match = self.build()
        match.open_coaching_window(TeamSide.HOME, CoachingOccasion.CEDED)
        game.match_state = match.to_dict()

        _, ask = cog.pending_turn_view(game.game_id, match)
        self.assertIn("ceded ball", ask)

    def test_the_tail_is_not_read_as_the_kickoff(self) -> None:
        # A cede resets the turn, so active_player_id is None and the
        # "choose who takes the ball" branch would otherwise answer.
        cog, game, match = self.build()

        _, ask = cog.pending_turn_view(game.game_id, match)
        self.assertIn("ceded ball", ask)


if __name__ == "__main__":
    unittest.main()
