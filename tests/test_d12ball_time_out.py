"""
The time out: the turn a side out of shooting range takes when it would
rather have the pause than the play.

The rule is two predicates and one state change --
MatchState.may_call_time_out and MatchState.call_time_out -- plus the
flow they open: the calling coach's window, the other coach's reply,
and a tail that runs no run back. See "Time out" in
docs/living-rules.md.

It was **ceding the ball** until 2026-09-16, and the tests that changed
rather than being renamed are the ones that fact was load-bearing for:
possession no longer crosses, last possession refuses a time out
instead of ending the period, the tail is not a turnover, and the
pickup afterwards is free.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

from cogs.d12ball import D12Ball
from cogs.d12ball_views import TimeOutConfirmView, PlayerActionView
from d12ball.components import (
    EVENT_TIME_OUT,
    EVENT_TURN_ACTION,
    CoachingOccasion,
    MatchState,
    TeamSide,
    Zone,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.ai import build_ai_strategies
from d12ball.engine import RulesEngine
from d12ball.game import AIOpponent, D12BallGame, Team
from save_patches import suppressed_cog_saves


def build_cog() -> D12Ball:
    cog = object.__new__(D12Ball)
    cog.games = {}
    cog.player_catalog = load_player_catalog()
    cog.maneuver_catalog = load_maneuver_catalog()
    cog.basic_ruleset = load_basic_ruleset()
    cog.engine = RulesEngine(
        cog.player_catalog, cog.basic_ruleset, cog.maneuver_catalog, {},
    )
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


class TimeOutOfferTests(unittest.TestCase):
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
        self.assertTrue(match.may_call_time_out())

        match.ball.zone = Zone.VISITORS_GOAL
        match.ball.space_index = 0
        self.assertTrue(match.can_attempt_score())
        self.assertFalse(match.may_call_time_out())

    def test_a_spent_declaration_takes_it_away(self) -> None:
        match = self.build_match()
        self.assertTrue(match.may_call_time_out())

        match.time_outs_used.add(TeamSide.HOME.value)
        self.assertFalse(match.may_call_time_out())
        # It is once a half each: the other side still has theirs.
        self.assertTrue(match.may_take_time_out(TeamSide.VISITING))

    def test_an_empty_bench_does_not_take_it_away(self) -> None:
        # The window is the whole Coaching Choice, not the substitution
        # alone, so a side with nobody to bring on may still want it.
        match = self.build_match()
        match.home.team_board.bench = []
        match.home.team_board.back_bench = []

        self.assertEqual(match.substitution_pool(TeamSide.HOME), [])
        self.assertTrue(match.may_call_time_out())

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
            "take a time out", cog.engine.build_turn_prompt(game, match),
        )

        match.time_outs_used.add(TeamSide.HOME.value)
        # Why the cede went too, said once. The prompt names the
        # reason and then what is left; it does not also list the two
        # buttons that are not on it.
        prompt = cog.engine.build_turn_prompt(game, match)
        self.assertIn("no time out available", prompt)
        self.assertNotIn("take a time out", prompt)

    def test_the_button_goes_with_the_declaration(self) -> None:
        cog = build_cog()
        game = build_game()
        match = self.build_match()
        handler = match.home.field_players[0]
        match.move_meeple(handler, Zone.MIDFIELD, 0)
        match.select_ball_handler(handler)
        match.time_outs_used.add(TeamSide.HOME.value)
        game.match_state = match.to_dict()
        cog.games[game.game_id] = game

        self.assertEqual(
            [
                item.label
                for item in PlayerActionView(cog, game.game_id).children
            ],
            ["Maneuver"],
        )


class TimeOutStateTests(unittest.TestCase):
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

    def test_possession_does_not_move_and_neither_does_the_ball(
        self,
    ) -> None:
        # The whole of what a cede stopped being on 2026-09-16. It used
        # to hand the ball to the other team on the space it was given
        # up on; a time out hands them nothing.
        match = self.build_match()
        handler = match.home.field_players[0]
        match.move_meeple(handler, Zone.MIDFIELD, 0)
        match.select_ball_handler(handler)
        match.ball_carrier_id = handler
        match.ball.speed = 3

        calling = match.call_time_out()

        self.assertEqual(calling, TeamSide.HOME)
        self.assertEqual(match.ball.possession, TeamSide.HOME)
        self.assertEqual((match.ball.zone, match.ball.space_index),
                         (Zone.MIDFIELD, 0))
        # Not a turnover, so nothing resets the speed either.
        self.assertEqual(match.ball.speed, 3)
        # The turn being taken is over, carrier included: a Coaching
        # Choice can re-deal the side, so who is on the ball is settled
        # again afterwards rather than held over.
        self.assertIsNone(match.active_player_id)
        self.assertIsNone(match.ball_carrier_id)
        self.assertTrue(match.pending_time_out)

    def test_it_costs_its_flat_space_minute(self) -> None:
        # The clock cost is read back off pending_run_back_distance by
        # whatever the tail still owes, and ceding costs the same flat
        # 1 space minute as any other maneuver (2026-08-16) -- the
        # same 1 reset_maneuver already leaves there, restated
        # explicitly.
        match = self.build_match()
        match.call_time_out()

        self.assertEqual(match.pending_run_back_distance, 1)
        self.assertFalse(match.advance_time(match.pending_run_back_distance))
        self.assertEqual(match.scoreboard.time, 1)

    def test_the_flag_survives_a_save(self) -> None:
        # It has to outlive two coaching windows, which is the whole
        # reason it is on the match rather than in a call.
        match = self.build_match()
        match.call_time_out()

        restored = MatchState.from_dict(match.to_dict(), self.rules)
        self.assertTrue(restored.pending_time_out)

    def test_resetting_the_turn_clears_it(self) -> None:
        match = self.build_match()
        match.call_time_out()
        match.reset_maneuver()

        self.assertFalse(match.pending_time_out)


class CedeOccasionTests(unittest.TestCase):
    """The window a cede opens is charged but never offered."""

    def test_it_is_charged_like_a_new_play_but_not_asked(self) -> None:
        ceded = CoachingOccasion.TIME_OUT
        self.assertTrue(ceded.spends_time_out)
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
        match.open_coaching_window(TeamSide.HOME, CoachingOccasion.TIME_OUT)

        self.assertTrue(match.pending_coaching_declared)
        self.assertFalse(match.may_take_time_out(TeamSide.HOME))

    def test_the_reply_costs_the_answering_side_nothing(self) -> None:
        match = MatchState.standard(
            catalog=load_player_catalog(),
            ruleset=load_basic_ruleset(),
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
        )
        match.open_coaching_window(
            TeamSide.VISITING, CoachingOccasion.TIME_OUT, is_response=True,
        )

        self.assertTrue(match.pending_coaching_declared)
        self.assertTrue(match.may_take_time_out(TeamSide.VISITING))


class TimeOutFlowTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_it_opens_the_calling_coach_s_window(self) -> None:
        cog, game, match = self.build()
        interaction = build_interaction()

        with suppressed_cog_saves():
            await cog.begin_time_out(interaction, game, match)

        cog.drop_turn_prompt.assert_awaited_once()
        cog.begin_substitution_window.assert_awaited_once()
        _, kwargs = cog.begin_substitution_window.call_args
        self.assertEqual(kwargs["occasion"], CoachingOccasion.TIME_OUT)
        self.assertIn("call a time out", kwargs["lead_in"])
        # The side that gave it up coaches first.
        self.assertEqual(
            cog.begin_substitution_window.call_args.args[3], TeamSide.HOME,
        )

    def test_the_clock_boundary_is_the_last_minute_itself(self) -> None:
        # The author, 2026-09-16, in exactly these numbers: "you can do
        # it on minute 29 but not on 30. You can do it on minute 14 but
        # not 15." The flag is what carries it -- reaching the last
        # minute is what raises it -- so the test drives the clock
        # rather than setting the flag by hand.
        _, _, match = self.build()
        match.scoreboard.time = 13

        self.assertFalse(match.advance_time(1))
        self.assertEqual(match.scoreboard.time, 14)
        self.assertTrue(match.may_call_time_out())

        self.assertTrue(match.advance_time(1))
        self.assertEqual(match.scoreboard.time, 15)
        self.assertFalse(match.may_call_time_out())

    def test_the_overrun_refuses_one_too(self) -> None:
        # The clock runs past the last minute during a last
        # possession, so a first half can reach 17 -- and the flag
        # stays up, which is what keeps this refused all the way.
        _, _, match = self.build()
        match.scoreboard.time = 14
        match.advance_time(3)

        self.assertEqual(match.scoreboard.time, 17)
        self.assertTrue(match.scoreboard.last_possession)
        self.assertFalse(match.may_call_time_out())

    def test_last_possession_refuses_it_outright(self) -> None:
        # The author, 2026-09-16: "you can do it on minute 29 but not
        # on 30. You can do it on minute 14 but not 15." Ceding ended
        # the period there, being a turnover; a time out turns nothing
        # over, so it is simply not on offer.
        _, _, match = self.build()
        self.assertTrue(match.may_call_time_out())

        match.scoreboard.last_possession = True

        self.assertFalse(match.may_call_time_out())
        # The half's own count is untouched -- the refusal is about the
        # position, so the time out is still there in the second half.
        self.assertTrue(match.may_take_time_out(match.ball.possession))

    async def test_the_reply_is_the_same_occasion(self) -> None:
        cog, game, match = self.build()
        match.call_time_out()
        match.open_coaching_window(TeamSide.HOME, CoachingOccasion.TIME_OUT)
        interaction = build_interaction()

        with suppressed_cog_saves():
            await cog.finish_substitution_window(interaction, game, match)

        cog.begin_substitution_window.assert_awaited_once()
        _, kwargs = cog.begin_substitution_window.call_args
        self.assertEqual(kwargs["occasion"], CoachingOccasion.TIME_OUT)
        self.assertTrue(kwargs["is_response"])
        cog.announce_run_back.assert_not_awaited()

    async def test_the_reply_closing_runs_no_run_back(self) -> None:
        # Both windows opened on their own coach's arrangement, so
        # there is nothing displaced to run back -- but the time out
        # still costs its own flat space minute (2026-08-16).
        cog, game, match = self.build()
        match.call_time_out()
        match.move_meeple(
            match.visiting.field_players[0], Zone.MIDFIELD, 0,
        )
        match.open_coaching_window(
            TeamSide.VISITING, CoachingOccasion.TIME_OUT, is_response=True,
        )
        interaction = build_interaction()

        with suppressed_cog_saves():
            await cog.finish_substitution_window(interaction, game, match)

        cog.announce_run_back.assert_not_awaited()
        cog.finish_maneuver_resolution.assert_awaited_once()
        _, kwargs = cog.finish_maneuver_resolution.call_args
        self.assertEqual(kwargs["distance_moved"], 1)
        # **Not** a turnover: the side that called it still has the
        # ball, so nothing resets speed and nothing ends the period.
        self.assertFalse(kwargs["turnover_occurred"])
        self.assertFalse(match.pending_time_out)

    async def test_a_ball_nobody_is_standing_on_is_picked_up(self) -> None:
        # A Coaching Choice can re-deal the whole side, so the coach
        # who called the time out can rearrange their own handler off
        # their own ball. Possession stays theirs and they fetch it.
        cog, game, match = self.build()
        match.call_time_out()
        for player_id in list(match.board.spaces[Zone.MIDFIELD][0]):
            match.board.place_meeple(player_id, Zone.HOME_GOAL, 0)
        interaction = build_interaction()

        with suppressed_cog_saves():
            await cog.finish_time_out(interaction, game, match)

        cog.begin_ball_recovery.assert_awaited_once()
        cog.finish_maneuver_resolution.assert_not_awaited()
        self.assertTrue(match.pending_ball_recovery)
        # And it is a time out's pickup, which is the flag that makes
        # it free and keeps it from reading as a turnover.
        self.assertTrue(match.pending_recovery_from_time_out)

    async def test_the_pickup_after_a_time_out_charges_nothing(self) -> None:
        # The one walk to the ball in the game that costs no
        # exhaustion (the author, 2026-09-16): a time out costs a
        # minute, and a coach is not billed for putting somebody back
        # on a ball their side never lost.
        cog, game, match = self.build()
        match.call_time_out()
        for player_id in list(match.board.spaces[Zone.MIDFIELD][0]):
            match.board.place_meeple(player_id, Zone.HOME_GOAL, 0)
        match.pending_ball_recovery = True
        match.pending_recovery_from_time_out = True
        fetcher = match.contest_candidates(TeamSide.HOME)[0]
        interaction = build_interaction()

        with suppressed_cog_saves():
            await cog.apply_ball_recovery(
                interaction, game, match, fetcher,
            )

        self.assertEqual(match.exhaustion.get(fetcher, 0), 0)
        self.assertFalse(match.pending_recovery_from_time_out)
        # Not a turnover either: the side fetching it has had the ball
        # all along, so nothing resets and nothing ends.
        _, kwargs = cog.finish_maneuver_resolution.call_args
        self.assertFalse(kwargs["turnover_occurred"])

    async def test_an_out_of_bounds_pickup_still_charges(self) -> None:
        # The other half of the same branch: without the flag it is the
        # ordinary token a space, and it is a turnover.
        cog, game, match = self.build()
        for player_id in list(match.board.spaces[Zone.MIDFIELD][0]):
            match.board.place_meeple(player_id, Zone.HOME_GOAL, 0)
        match.pending_ball_recovery = True
        fetcher = match.contest_candidates(TeamSide.HOME)[0]
        interaction = build_interaction()

        with suppressed_cog_saves():
            await cog.apply_ball_recovery(
                interaction, game, match, fetcher,
            )

        self.assertGreater(match.exhaustion.get(fetcher, 0), 0)
        _, kwargs = cog.finish_maneuver_resolution.call_args
        self.assertTrue(kwargs["turnover_occurred"])

    async def test_it_is_logged_but_never_as_a_turn_action(self) -> None:
        # A possession is a run of consecutive turn actions by one
        # side, so logging a pause as a turn would invent a turn nobody
        # played -- but a coach still wants to know how often these get
        # called, so it gets its own kind. (The author, 2026-09-16.)
        cog, game, match = self.build()
        handler = match.home.field_players[0]
        match.move_meeple(handler, Zone.MIDFIELD, 0)
        match.select_ball_handler(handler)
        interaction = build_interaction()

        with suppressed_cog_saves():
            await cog.begin_time_out(interaction, game, match)

        kinds = [event.kind for event in match.events]
        self.assertIn(EVENT_TIME_OUT, kinds)
        self.assertNotIn(EVENT_TURN_ACTION, kinds)


class LegacyCedeSaveTests(unittest.TestCase):
    """
    A game saved mid-cede comes back mid-time-out.

    Both developers run the bot from their own tree against their own
    saves, so a half-finished game outlives the change that renamed
    these. The two ran the same window; what differed -- the ball
    crossing -- had already happened before the flag was ever read.

    This is a guard against a specific way it broke while it was being
    written: the fallbacks name the *old* key, and a blanket rename
    across the file rewrote them to the new one, leaving `data.get(x,
    data.get(x))`. That reads as a fallback and is not one.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    def legacy_save(self) -> dict:
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
        )
        saved = match.to_dict()
        for key in (
            "time_outs_used",
            "pending_time_out",
            "pending_recovery_from_time_out",
        ):
            saved.pop(key, None)
        saved["declared_substitution"] = ["home"]
        saved["pending_cede"] = True
        saved["pending_coaching_occasion"] = "ceded"
        saved["pending_coaching_side"] = TeamSide.HOME.value
        return saved

    def test_the_occasion_comes_back_as_a_time_out(self) -> None:
        back = MatchState.from_dict(self.legacy_save(), self.rules)

        self.assertIs(back.coaching_occasion, CoachingOccasion.TIME_OUT)
        self.assertTrue(back.pending_time_out)

    def test_a_spent_declaration_reads_as_a_spent_time_out(self) -> None:
        # The conservative half of the change: a new play's window is
        # free now, so the worst this does is hold back a time out from
        # a coach who only ever declared -- and the half's end clears
        # it either way.
        back = MatchState.from_dict(self.legacy_save(), self.rules)

        self.assertEqual(back.time_outs_used, {"home"})
        self.assertFalse(back.may_take_time_out(TeamSide.HOME))
        self.assertTrue(back.may_take_time_out(TeamSide.VISITING))

    def test_it_is_rewritten_under_the_new_keys_alone(self) -> None:
        # Nothing writes the old names any more, so they die out on
        # their own -- the same retirement `player_board` and
        # `tie_mode` got.
        back = MatchState.from_dict(self.legacy_save(), self.rules)
        saved = back.to_dict()

        self.assertNotIn("declared_substitution", saved)
        self.assertNotIn("pending_cede", saved)
        self.assertEqual(saved["time_outs_used"], ["home"])
        self.assertTrue(saved["pending_time_out"])

        again = MatchState.from_dict(saved, self.rules)
        self.assertEqual(again.time_outs_used, {"home"})
        self.assertTrue(again.pending_time_out)

    def test_a_save_that_predates_the_pickup_flag_is_not_free(self) -> None:
        # Every pickup owed by a game older than the time out is an
        # out-of-bounds ball's, and those charge.
        back = MatchState.from_dict(self.legacy_save(), self.rules)

        self.assertFalse(back.pending_recovery_from_time_out)


class DinkyTimeOutTests(unittest.TestCase):
    """
    Dinky calls a time out to get an injured player off (the author,
    2026-09-16) -- and does nothing else with one.

    It is the one call Dinky makes that looks like judgement and is
    not. Everything else Dinky declines to do is a weighing-up with no
    right answer; an injured player rolls without their skill modifier
    for the rest of the game and can never recover, so there is nothing
    to weigh.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    def build(self):
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
        strategy = build_ai_strategies(
            self.catalog, load_maneuver_catalog(),
        )[AIOpponent.DINKY]
        return strategy, match

    def test_a_fit_side_just_maneuvers(self) -> None:
        strategy, match = self.build()

        self.assertTrue(match.may_call_time_out())
        self.assertEqual(strategy.choose_action(match), "maneuver")

    def test_an_injured_player_on_the_field_buys_one(self) -> None:
        strategy, match = self.build()
        match.mark_injured(match.home.field_players[0])

        self.assertEqual(strategy.choose_action(match), "time_out")

    def test_it_is_not_taken_when_the_rules_refuse_one(self) -> None:
        # Gated on may_call_time_out like a human's button, so Dinky
        # cannot spend one it does not have or take one under last
        # possession.
        strategy, match = self.build()
        match.mark_injured(match.home.field_players[0])

        match.scoreboard.last_possession = True
        self.assertEqual(strategy.choose_action(match), "maneuver")

        match.scoreboard.last_possession = False
        match.time_outs_used.add(TeamSide.HOME.value)
        self.assertEqual(strategy.choose_action(match), "maneuver")

    def test_a_shot_on_beats_an_injury(self) -> None:
        # Checked after the shot: a shot on is worth more than a
        # substitution, and the time out will still be there next turn.
        strategy, match = self.build()
        match.mark_injured(match.home.field_players[0])
        zone, space_index = match.own_goal_restart_space(TeamSide.VISITING)
        match.ball.zone = zone
        match.ball.space_index = space_index

        self.assertEqual(strategy.choose_action(match), "shoot")


class TimeOutConfirmTests(unittest.IsolatedAsyncioTestCase):
    """The click, and the way back from it."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    def build(self):
        cog = build_cog()
        cog.begin_time_out = mock.AsyncMock()
        cog.engine.user_controls_possession = mock.Mock(return_value=True)
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
        await view.choose_action(interaction, "time_out", "Time out")

        interaction.response.edit_message.assert_awaited_once()
        _, kwargs = interaction.response.edit_message.call_args
        self.assertIn("Take a time out?", kwargs["content"])
        self.assertIsInstance(kwargs["view"], TimeOutConfirmView)
        cog.begin_time_out.assert_not_awaited()

    async def test_opening_the_confirm_is_not_yet_a_turn(self) -> None:
        """
        Ceding is the one turn action that asks before it acts, so it
        is the one that must not be recorded at its button: a coach
        who opens the confirm and presses Back has taken no turn, and
        logging one there would put a cede in the statistics that
        never happened -- followed by a second turn action for
        whatever they did instead. See `D12Ball.record_turn_action`.
        """
        cog, game, _ = self.build()

        view = PlayerActionView(cog, game.game_id)
        await view.choose_action(
            build_interaction(), "time_out", "Time out",
        )

        self.assertEqual(cog.engine.load_match_state(game).events, [])

    async def test_back_puts_the_prompt_back_word_for_word(self) -> None:
        cog, game, _ = self.build()
        interaction = build_interaction()

        view = TimeOutConfirmView(cog, game.game_id, "One, it is your turn.")
        await view.back(interaction)

        _, kwargs = interaction.response.edit_message.call_args
        self.assertEqual(kwargs["content"], "One, it is your turn.")
        self.assertIsInstance(kwargs["view"], PlayerActionView)
        cog.begin_time_out.assert_not_awaited()

    async def test_confirming_cedes(self) -> None:
        cog, game, _ = self.build()
        interaction = build_interaction()

        view = TimeOutConfirmView(cog, game.game_id, "One, it is your turn.")
        await view.confirm(interaction)

        cog.begin_time_out.assert_awaited_once()

    async def test_a_stale_confirmation_is_refused(self) -> None:
        # The prompt underneath stays live while the confirm is up, so
        # the match can have moved on before the second click.
        cog, game, match = self.build()
        match.time_outs_used.add(TeamSide.HOME.value)
        game.match_state = match.to_dict()
        interaction = build_interaction()

        view = TimeOutConfirmView(cog, game.game_id, "One, it is your turn.")
        await view.confirm(interaction)

        cog.begin_time_out.assert_not_awaited()
        interaction.followup.send.assert_awaited_once()

    async def test_a_stale_time_out_click_is_refused(self) -> None:
        cog, game, match = self.build()
        match.ball.zone = Zone.VISITORS_GOAL
        match.ball.space_index = 0
        match.move_meeple(match.active_player_id, Zone.VISITORS_GOAL, 0)
        game.match_state = match.to_dict()
        interaction = build_interaction()

        view = PlayerActionView(cog, game.game_id)
        await view.choose_action(interaction, "time_out", "Time out")

        interaction.response.send_message.assert_awaited_once()
        self.assertIn(
            "shooting range",
            interaction.response.send_message.call_args.args[0],
        )


class TimeOutOffensiveChoiceTests(unittest.IsolatedAsyncioTestCase):
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
        match.pending_time_out = True
        game.match_state = match.to_dict()
        cog.games[game.game_id] = game
        cog.send_turn_prompt = mock.AsyncMock()
        cog.defer_and_get_match = mock.AsyncMock(return_value=(game, match))
        interaction = build_interaction()

        with suppressed_cog_saves():
            await D12Ball.offensive_choice.callback(cog, interaction)

        cog.send_turn_prompt.assert_not_awaited()
        self.assertIn(
            "time out", interaction.followup.send.call_args.args[0],
        )


class TimeOutRecoveryTests(unittest.TestCase):
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
        match.call_time_out()
        game.match_state = match.to_dict()
        cog.games[game.game_id] = game
        return cog, game, match

    def test_an_open_window_comes_back_as_the_hub(self) -> None:
        # Never the offer: ceding is what bought the window, so neither
        # coach is ever asked whether to take it.
        cog, game, match = self.build()
        match.open_coaching_window(TeamSide.HOME, CoachingOccasion.TIME_OUT)
        game.match_state = match.to_dict()

        _, ask = cog.pending_turn_view(game.game_id, match)
        self.assertIn("time out", ask)

    def test_the_tail_is_not_read_as_the_kickoff(self) -> None:
        # A cede resets the turn, so active_player_id is None and the
        # "choose who takes the ball" branch would otherwise answer.
        cog, game, match = self.build()

        _, ask = cog.pending_turn_view(game.game_id, match)
        self.assertIn("time out", ask)


if __name__ == "__main__":
    unittest.main()
