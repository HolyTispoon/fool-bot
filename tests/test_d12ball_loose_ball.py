"""
Loose ball: who is asked, in what order, and what happens when nobody
goes after it.

The rules are in docs/living-rules.md under "Loose ball". Three of them are load-bearing here and easy to get
subtly wrong:

- the side that last had possession answers first, and alone;
- either coach may send nobody, which is a move rather than a way out
  of the prompt;
- with nobody sent, the ball is out of bounds -- a turnover, and the
  side that wins it places a player on the ball *after* the run back,
  which is the only ordering that leaves that player standing on it.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

from cogs.d12ball import D12Ball
from cogs.d12ball_helpers import space_label
from d12ball.components import (
    MatchState,
    TeamSide,
    Zone,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.game import AIOpponent, D12BallGame, Team


def build_cog() -> D12Ball:
    cog = object.__new__(D12Ball)
    cog.games = {}
    cog.player_catalog = load_player_catalog()
    cog.maneuver_catalog = load_maneuver_catalog()
    cog.basic_ruleset = load_basic_ruleset()
    cog.team_emojis = {}
    cog.condition_emojis = {}
    cog.refresh_match_image = mock.AsyncMock()
    cog.announce_board_update = mock.AsyncMock()
    cog.finish_maneuver_resolution = mock.AsyncMock()
    cog.begin_run_back = mock.AsyncMock()
    cog.begin_substitution_window = mock.AsyncMock()
    return cog


def build_game(ai: bool = False) -> D12BallGame:
    return D12BallGame(
        game_id="g1",
        game_number=1,
        guild_id=1,
        channel_id=1,
        message_id=None,
        player_1_id=111,
        player_2_id=None if ai else 222,
        player_1_name="One",
        player_2_name="Two",
        player_1_team=Team.ORANGE,
        player_2_team=Team.PURPLE,
        home_player_number=1,
        visiting_player_number=2,
        ai_opponent=AIOpponent.DINKY if ai else None,
    )


def build_interaction() -> SimpleNamespace:
    return SimpleNamespace(
        user=SimpleNamespace(id=111, display_name="One"),
        channel=None,
        guild=None,
        followup=SimpleNamespace(
            send=mock.AsyncMock(return_value=SimpleNamespace(id=999)),
        ),
        response=SimpleNamespace(
            defer=mock.AsyncMock(),
            edit_message=mock.AsyncMock(),
            send_message=mock.AsyncMock(),
        ),
    )


class LooseBallTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    def build_match(self) -> MatchState:
        return MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
        )

    def empty_the_ball_zone(self, match: MatchState) -> None:
        """Clear the ball's zone of both sides -- "out of bounds"."""
        zone = match.ball.zone
        elsewhere = next(z for z in Zone if z != zone)
        for side in (TeamSide.HOME, TeamSide.VISITING):
            for player_id in list(
                match.fielded_players_in_zone(side, zone)
            ):
                match.board.remove_meeple(player_id)
                match.board.place_meeple(player_id, elsewhere, 0)

    def test_the_side_that_lost_the_ball_answers_first(self) -> None:
        cog = build_cog()
        match = self.build_match()
        match.begin_loose_ball(2)

        self.assertEqual(
            cog.loose_ball_side_on_the_clock(match), "offense",
        )
        self.assertEqual(
            cog.loose_ball_prompt_side(match), match.ball.possession,
        )

        match.choose_loose_ball_offense_player(
            cog.loose_ball_candidates(match, match.ball.possession)[0],
        )
        self.assertEqual(
            cog.loose_ball_side_on_the_clock(match), "defense",
        )

        match.choose_loose_ball_defense_player(
            cog.loose_ball_candidates(match, match.defending_side())[0],
        )
        self.assertIsNone(cog.loose_ball_side_on_the_clock(match))

    def test_declining_settles_a_side_without_picking_anyone(self) -> None:
        cog = build_cog()
        match = self.build_match()
        match.begin_loose_ball(2)

        match.decline_loose_ball(match.ball.possession)
        self.assertEqual(
            cog.loose_ball_side_on_the_clock(match), "defense",
        )
        self.assertIsNone(match.loose_ball_offense_player)

        match.decline_loose_ball(match.defending_side())
        self.assertIsNone(cog.loose_ball_side_on_the_clock(match))

    def test_a_lone_candidate_is_still_asked(self) -> None:
        # Sending them is optional, so it isn't auto-picked the way a
        # forced run back is -- declining is what puts the ball out of
        # bounds, and that has to stay reachable.
        cog = build_cog()
        game = build_game()
        match = self.build_match()
        zone = match.ball.zone
        elsewhere = next(z for z in Zone if z != zone)
        possession = match.ball.possession
        for player_id in list(
            match.fielded_players_in_zone(possession, zone)
        )[1:]:
            match.board.remove_meeple(player_id)
            match.board.place_meeple(player_id, elsewhere, 0)

        self.assertEqual(
            len(cog.loose_ball_candidates(match, possession)), 1,
        )
        match.begin_loose_ball(2)
        cog.auto_resolve_loose_ball_picks(game, match)

        self.assertIsNone(match.loose_ball_offense_player)
        self.assertEqual(
            cog.loose_ball_side_on_the_clock(match), "offense",
        )

    def test_candidates_never_reach_outside_the_ball_s_zone(self) -> None:
        cog = build_cog()
        match = self.build_match()
        self.empty_the_ball_zone(match)

        self.assertEqual(
            cog.loose_ball_candidates(match, match.ball.possession), [],
        )
        self.assertEqual(
            cog.loose_ball_candidates(match, match.defending_side()), [],
        )

    def clear_the_ball_s_space(self, match: MatchState) -> None:
        """
        Move everyone off the space the ball is on, without taking
        them out of the zone -- which is what a pass into an empty
        space leaves behind, and the only position from which both
        sides still have somebody to send.
        """
        zone = match.ball.zone
        elsewhere = next(
            index
            for index in range(len(match.board.spaces[zone]))
            if index != match.ball.space_index
        )
        for player_id in list(
            match.board.spaces[zone][match.ball.space_index]
        ):
            match.move_meeple(player_id, zone, elsewhere)

    async def test_a_loose_ball_is_announced_with_the_board_and_the_space(
        self,
    ) -> None:
        """
        Where the ball came to rest is the whole of what the coach
        being asked has to decide on, and it is the one thing nothing
        else in the channel says: the announcement names the space and
        carries the board it is standing on, and the pick prompt names
        it again, since a resume puts that prompt back up on its own.
        """
        cog = build_cog()
        game = build_game()
        match = self.build_match()
        self.clear_the_ball_s_space(match)
        game.match_state = match.to_dict()
        cog.games[game.game_id] = game
        where = space_label(match.ball.zone, match.ball.space_index)

        interaction = build_interaction()
        with mock.patch("cogs.d12ball.save_games"):
            await cog.begin_loose_ball(interaction, game, match, 2)

        cog.announce_board_update.assert_awaited_once()
        announcement = cog.announce_board_update.await_args.args[2]
        self.assertIn("Loose ball!", announcement)
        self.assertIn(where, announcement)
        self.assertIn("Midfield", announcement)
        # The board goes out with that message rather than as a bare
        # refresh, or the space it names is not on anything a coach
        # can see.
        cog.refresh_match_image.assert_not_awaited()

        self.assertIn(where, interaction.followup.send.await_args.args[0])

    async def test_nobody_contesting_is_an_out_of_bounds_turnover(
        self,
    ) -> None:
        cog = build_cog()
        game = build_game()
        match = self.build_match()
        self.empty_the_ball_zone(match)
        losing_side = match.ball.possession
        winning_side = match.defending_side()
        match.begin_loose_ball(3)
        game.match_state = match.to_dict()
        cog.games[game.game_id] = game

        with mock.patch("cogs.d12ball.save_games"):
            await cog.resolve_loose_ball(build_interaction(), game, match)

        self.assertEqual(match.ball.possession, winning_side)
        self.assertNotEqual(match.ball.possession, losing_side)
        self.assertEqual(match.ball.speed, 1)
        self.assertFalse(match.pending_loose_ball)
        self.assertTrue(match.pending_ball_recovery)
        # The run back comes first; the pickup waits for it.
        cog.begin_run_back.assert_awaited_once()
        self.assertTrue(
            cog.begin_run_back.await_args.kwargs["turnover_occurred"]
        )
        # Out of bounds is the one loose ball that is a new play, so it
        # is also the one that opens a substitution window.
        self.assertTrue(cog.begin_run_back.await_args.kwargs["new_play"])

    async def test_the_other_team_picking_the_ball_up_is_a_steal(
        self,
    ) -> None:
        # A loose ball won by the side that did not have it is a steal:
        # a turnover and a run back, but no substitution window, since
        # the ball never went dead.
        cog = build_cog()
        game = build_game()
        match = self.build_match()
        losing_side = match.ball.possession
        winning_side = match.defending_side()

        # Clear the ball's space of the possessing side and stand an
        # opponent on it, which is the uncontested-turnover case.
        for player_id in list(
            match.fielded_players_in_zone(losing_side, match.ball.zone)
        ):
            match.board.remove_meeple(player_id)
            match.board.place_meeple(
                player_id, next(z for z in Zone if z != match.ball.zone), 0,
            )
        opponent = match.fielded_players_in_zone(
            winning_side, match.ball.zone,
        )[0]
        match.board.remove_meeple(opponent)
        match.board.place_meeple(
            opponent, match.ball.zone, match.ball.space_index,
        )
        game.match_state = match.to_dict()
        cog.games[game.game_id] = game

        with mock.patch("cogs.d12ball.save_games"):
            handled = await cog.check_for_loose_ball(
                build_interaction(), game, match, 2,
            )

        self.assertTrue(handled)
        self.assertEqual(match.ball.possession, winning_side)
        cog.begin_run_back.assert_awaited_once()
        kwargs = cog.begin_run_back.await_args.kwargs
        self.assertTrue(kwargs["turnover_occurred"])
        self.assertFalse(kwargs.get("new_play", False))

    async def test_the_recovering_player_ends_up_on_the_ball(self) -> None:
        # The whole point of deferring the pickup past the run back:
        # placed before it, this player was immediately run back off
        # the ball, which left it loose all over again.
        cog = build_cog()
        game = build_game()
        match = self.build_match()
        self.empty_the_ball_zone(match)
        match.ball.possession = match.defending_side()
        match.pending_ball_recovery = True
        match.pending_run_back_distance = 3
        game.match_state = match.to_dict()
        cog.games[game.game_id] = game

        recoverer = match.setup_for_side(match.ball.possession).field_players[0]
        travel = match.distance_to_ball(recoverer)
        self.assertGreater(travel, 0)

        with mock.patch("cogs.d12ball.save_games"):
            await cog.apply_ball_recovery(
                build_interaction(), game, match, recoverer,
            )

        self.assertEqual(
            match.board.meeple_position(recoverer),
            (match.ball.zone, match.ball.space_index),
        )
        self.assertIn(recoverer, match.eligible_ball_handlers())
        self.assertFalse(match.pending_ball_recovery)
        self.assertEqual(match.exhaustion.get(recoverer), travel)
        # The clock cost is the maneuver's own travel, not the walk.
        self.assertEqual(
            cog.finish_maneuver_resolution.await_args.kwargs[
                "distance_moved"
            ],
            3,
        )

    async def test_an_ai_side_picks_its_nearest_player_up(self) -> None:
        cog = build_cog()
        game = build_game(ai=True)
        match = self.build_match()
        self.empty_the_ball_zone(match)
        # Player 2 is the AI and holds the visiting side.
        match.ball.possession = TeamSide.VISITING
        match.pending_ball_recovery = True
        game.match_state = match.to_dict()
        cog.games[game.game_id] = game

        nearest = min(
            match.visiting.field_players, key=match.distance_to_ball,
        )

        with mock.patch("cogs.d12ball.save_games"):
            await cog.begin_ball_recovery(build_interaction(), game, match)

        self.assertFalse(match.pending_ball_recovery)
        self.assertIn(nearest, match.eligible_ball_handlers())

    async def test_the_run_back_hands_over_to_the_pickup(self) -> None:
        # The join between the two: once nobody is left to run back,
        # continue_run_back owes the pickup before the clock moves.
        cog = build_cog()
        cog.begin_ball_recovery = mock.AsyncMock()
        game = build_game()
        match = self.build_match()
        # Straight off a kickoff nobody is out of position, so the run
        # back is already finished the moment it starts.
        match.pending_run_back = True
        match.pending_run_back_distance = 2
        match.pending_run_back_turnover = True
        match.pending_ball_recovery = True
        game.match_state = match.to_dict()
        cog.games[game.game_id] = game

        with mock.patch("cogs.d12ball.save_games"):
            await cog.continue_run_back(build_interaction(), game, match)

        cog.begin_ball_recovery.assert_awaited_once()
        cog.finish_maneuver_resolution.assert_not_awaited()

    def test_the_recovery_window_survives_validate(self) -> None:
        # Between the turnover and the pickup the ball has nobody on
        # it at all, which every other phase would reject.
        cog = build_cog()
        match = self.build_match()
        self.empty_the_ball_zone(match)
        match.ball.possession = match.defending_side()
        match.pending_ball_recovery = True

        match.validate(self.catalog)
        round_tripped = MatchState.from_dict(match.to_dict(), self.rules)
        self.assertTrue(round_tripped.pending_ball_recovery)


if __name__ == "__main__":
    unittest.main()
