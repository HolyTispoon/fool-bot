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
from cogs.d12ball_helpers import HIGH_PASS_CONTEST_HEADLINE, space_label
from d12ball.components import (
    MatchState,
    TeamSide,
    Zone,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
)
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

    def go_out_of_bounds(self, match: MatchState) -> None:
        """
        The ball lying in an empty space with both coaches sending
        nobody -- which since 2026-08-16 is the whole of how a ball
        goes out. Emptying the ball's *zone* used to do it; distance
        replaced the zone as the measure, so both sides now have
        somebody to send wherever the ball lands.
        """
        self.clear_the_ball_s_space(match)
        match.decline_loose_ball(match.ball.possession)
        match.decline_loose_ball(match.defending_side())

    def test_the_side_that_lost_the_ball_answers_first(self) -> None:
        cog = build_cog()
        match = self.build_match()
        match.begin_loose_ball(2)

        self.assertEqual(
            cog.engine.loose_ball_side_on_the_clock(match), "offense",
        )
        self.assertEqual(
            cog.engine.loose_ball_prompt_side(match), match.ball.possession,
        )

        match.choose_loose_ball_offense_player(
            cog.engine.loose_ball_candidates(match, match.ball.possession)[0],
        )
        self.assertEqual(
            cog.engine.loose_ball_side_on_the_clock(match), "defense",
        )

        match.choose_loose_ball_defense_player(
            cog.engine.loose_ball_candidates(match, match.defending_side())[0],
        )
        self.assertIsNone(cog.engine.loose_ball_side_on_the_clock(match))

    def test_declining_settles_a_side_without_picking_anyone(self) -> None:
        cog = build_cog()
        match = self.build_match()
        match.begin_loose_ball(2)

        match.decline_loose_ball(match.ball.possession)
        self.assertEqual(
            cog.engine.loose_ball_side_on_the_clock(match), "defense",
        )
        self.assertIsNone(match.loose_ball_offense_player)

        match.decline_loose_ball(match.defending_side())
        self.assertIsNone(cog.engine.loose_ball_side_on_the_clock(match))

    def send_the_ball_to_the_far_end(self, match: MatchState) -> None:
        """
        The ball on the last space of the visitors' goal zone, with
        nobody on it: nothing at all lies beyond the ball, so each side
        is down to whoever is nearest behind it.
        """
        zone = Zone.VISITORS_GOAL
        match.set_ball_space(zone, len(match.board.spaces[zone]) - 1)
        self.clear_the_ball_s_space(match)
        # Clearing the space stacks that zone's pair on one space, and
        # two players the same distance away are two candidates, not
        # one -- spread them so the nearest really is alone.
        for side in (TeamSide.HOME, TeamSide.VISITING):
            stacked = [
                player_id
                for player_id in match.setup_for_side(side).field_players
                if match.board.meeple_position(player_id) == (zone, 0)
            ]
            for player_id in stacked[1:]:
                match.board.remove_meeple(player_id)
                match.board.place_meeple(player_id, Zone.MIDFIELD, 0)

    def test_a_lone_candidate_is_still_asked(self) -> None:
        # Sending them is optional, so it isn't auto-picked the way a
        # forced run back is -- declining is what puts the ball out of
        # bounds, and that has to stay reachable.
        cog = build_cog()
        game = build_game()
        match = self.build_match()
        self.send_the_ball_to_the_far_end(match)

        self.assertEqual(
            len(cog.engine.loose_ball_candidates(match, match.ball.possession)), 1,
        )
        match.begin_loose_ball(2)
        cog.engine.auto_resolve_loose_ball_picks(game, match)

        self.assertIsNone(match.loose_ball_offense_player)
        self.assertEqual(
            cog.engine.loose_ball_side_on_the_clock(match), "offense",
        )

    def offsets_from_the_ball(self, match: MatchState, side) -> dict[str, int]:
        ball_flat = match.board.flat_index(
            match.ball.zone, match.ball.space_index,
        )
        return {
            player_id: match.board.flat_index(
                *match.board.meeple_position(player_id)
            ) - ball_flat
            for player_id in match.setup_for_side(side).field_players
        }

    def test_candidates_are_the_nearest_player_either_side(self) -> None:
        # Zone does not come into it: the pool is the nearest player
        # in front of the ball and the nearest behind it, wherever
        # they are assigned. See "Sending a player" in the living
        # rules.
        cog = build_cog()
        match = self.build_match()
        self.clear_the_ball_s_space(match)

        for side in (match.ball.possession, match.defending_side()):
            offsets = self.offsets_from_the_ball(match, side)
            expected = {
                player_id
                for direction in (1, -1)
                for player_id, offset in offsets.items()
                if offset * direction > 0
                and abs(offset) == min(
                    abs(other)
                    for other in offsets.values()
                    if other * direction > 0
                )
            }
            self.assertEqual(
                set(cog.engine.loose_ball_candidates(match, side)), expected,
            )
            # Two directions, and a tie on one of them is every player
            # tied -- the coach picks between them.
            self.assertGreaterEqual(len(expected), 2)
            self.assertLess(len(expected), 6)

    def test_a_candidate_may_come_from_another_zone(self) -> None:
        # The whole of the change: with the ball in midfield and the
        # midfielders moved out of the way, the pool reaches into the
        # goal zones rather than coming back empty.
        cog = build_cog()
        match = self.build_match()
        side = match.ball.possession
        for player_id, _ in list(self.offsets_from_the_ball(match, side).items()):
            if match.board.meeple_position(player_id)[0] == match.ball.zone:
                match.board.remove_meeple(player_id)
                match.board.place_meeple(player_id, Zone.HOME_GOAL, 0)

        candidates = cog.engine.loose_ball_candidates(match, side)

        self.assertTrue(candidates)
        self.assertTrue(
            all(
                match.board.meeple_position(player_id)[0] != match.ball.zone
                for player_id in candidates
            )
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
        with suppressed_cog_saves():
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
        self.go_out_of_bounds(match)
        losing_side = match.ball.possession
        winning_side = match.defending_side()
        match.begin_loose_ball(3)
        game.match_state = match.to_dict()
        cog.games[game.game_id] = game

        with suppressed_cog_saves():
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
        # opponent on it. **The ball is simply theirs** -- it never went
        # loose, because only an empty space is loose (the author,
        # 2026-08-26), and the side that lost it is never offered a
        # send. Between 2026-08-18 and then it was a loose ball like
        # any other and they could walk somebody in to fight for it.
        self.clear_the_ball_s_space(match)
        opponent = match.setup_for_side(winning_side).field_players[0]
        match.board.remove_meeple(opponent)
        match.board.place_meeple(
            opponent, match.ball.zone, match.ball.space_index,
        )
        game.match_state = match.to_dict()
        cog.games[game.game_id] = game

        interaction = build_interaction()
        with suppressed_cog_saves():
            handled = await cog.check_for_loose_ball(
                interaction, game, match, 2,
            )

        # The defender standing on it is put up without being asked;
        # the side that lost it is pre-declined and never put on the
        # clock, so the whole thing settles in that one call.
        self.assertEqual(match.loose_ball_defense_player, opponent)
        self.assertTrue(match.loose_ball_offense_declined)
        self.assertIsNone(cog.engine.loose_ball_side_on_the_clock(match))

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
        self.go_out_of_bounds(match)
        match.ball.possession = match.defending_side()
        match.pending_ball_recovery = True
        match.pending_run_back_distance = 3
        game.match_state = match.to_dict()
        cog.games[game.game_id] = game

        recoverer = max(
            match.contest_candidates(match.ball.possession),
            key=match.distance_to_ball,
        )
        travel = match.distance_to_ball(recoverer)
        self.assertGreater(travel, 0)

        with suppressed_cog_saves():
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
        # Deep in the home goal zone, where the visitors' nearest
        # either way are different distances off -- the middle of the
        # board has them symmetrical, and a tie would prove nothing.
        match.set_ball_space(Zone.HOME_GOAL, 1)
        self.go_out_of_bounds(match)
        # Player 2 is the AI and holds the visiting side.
        match.ball.possession = TeamSide.VISITING
        match.pending_ball_recovery = True
        game.match_state = match.to_dict()
        cog.games[game.game_id] = game

        # Nearest of the two it is offered, not best: the walk costs a
        # token a space and wins nothing.
        travel = {
            player_id: match.distance_to_ball(player_id)
            for player_id in match.contest_candidates(TeamSide.VISITING)
        }
        self.assertGreater(len(set(travel.values())), 1)

        with suppressed_cog_saves():
            await cog.begin_ball_recovery(build_interaction(), game, match)

        self.assertFalse(match.pending_ball_recovery)
        recoverer = match.eligible_ball_handlers()[0]
        self.assertEqual(travel.get(recoverer), min(travel.values()))

    async def test_a_reset_that_covers_the_ball_needs_no_pickup(
        self,
    ) -> None:
        # The pickup is owed "unless one of theirs is already on it",
        # and the new play's reset runs between the flag being set and
        # this being asked -- so it is asked here and nowhere earlier.
        cog = build_cog()
        game = build_game()
        match = self.build_match()
        match.pending_ball_recovery = True
        match.pending_run_back_distance = 3
        game.match_state = match.to_dict()
        cog.games[game.game_id] = game
        self.assertTrue(match.eligible_ball_handlers())
        standing = [list(s) for s in match.board.spaces[match.ball.zone]]

        with suppressed_cog_saves():
            await cog.begin_ball_recovery(build_interaction(), game, match)

        self.assertFalse(match.pending_ball_recovery)
        self.assertEqual(match.exhaustion, {})
        self.assertEqual(
            [list(s) for s in match.board.spaces[match.ball.zone]], standing,
        )
        cog.finish_maneuver_resolution.assert_awaited_once()

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

        with suppressed_cog_saves():
            await cog.continue_run_back(build_interaction(), game, match)

        cog.begin_ball_recovery.assert_awaited_once()
        cog.finish_maneuver_resolution.assert_not_awaited()

    def test_the_recovery_window_survives_validate(self) -> None:
        # Between the turnover and the pickup the ball has nobody on
        # it at all, which every other phase would reject.
        cog = build_cog()
        match = self.build_match()
        self.go_out_of_bounds(match)
        match.ball.possession = match.defending_side()
        match.pending_ball_recovery = True

        match.validate(self.catalog)
        round_tripped = MatchState.from_dict(match.to_dict(), self.rules)
        self.assertTrue(round_tripped.pending_ball_recovery)


class ContestantOnTheBallTests(unittest.IsolatedAsyncioTestCase):
    """
    A loose ball is contested by whoever is standing on it -- the
    author, 2026-08-18. See "The loose ball" in docs/living-rules.md.

    It used to be that a ball landing on a player settled itself: the
    possessing team kept it, or the other team took it outright. Both
    are now the same contest every other loose ball gets, and the
    player standing there is simply a contestant who costs their side
    nothing and whom their side may not withhold.
    """

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

    def stand_on_the_ball(
        self, match: MatchState, side: TeamSide, count: int,
    ) -> list[str]:
        """Clear the ball's space and put `count` of `side` on it."""
        for occupant in list(
            match.board.spaces[match.ball.zone][match.ball.space_index]
        ):
            match.board.remove_meeple(occupant)
        chosen = match.setup_for_side(side).field_players[:count]
        for player_id in chosen:
            match.board.remove_meeple(player_id)
            match.board.place_meeple(
                player_id, match.ball.zone, match.ball.space_index,
            )
        return chosen

    def test_a_lone_player_on_the_ball_contests_without_being_asked(
        self,
    ) -> None:
        # One of them is nothing to ask about: they contest for
        # nothing and may not be held back, so the only choice a
        # prompt could offer is one the rules refuse.
        cog = build_cog()
        game = build_game()
        match = self.build_match()
        defense = match.defending_side()
        (defender,) = self.stand_on_the_ball(match, defense, 1)
        match.begin_loose_ball(1)

        cog.engine.auto_resolve_loose_ball_picks(game, match)

        self.assertEqual(match.loose_ball_defense_player, defender)
        self.assertFalse(match.may_decline_loose_ball(defense))
        # The side that lost it is still a free choice, and still first.
        self.assertEqual(
            cog.engine.loose_ball_side_on_the_clock(match), "offense",
        )
        self.assertTrue(match.may_decline_loose_ball(match.ball.possession))

    def test_several_on_the_ball_is_the_coach_s_pick(self) -> None:
        # The same call as the maneuver challenge's (2026-08-17): they
        # differ only in who they are, and that is the coach's to
        # decide.
        cog = build_cog()
        game = build_game()
        match = self.build_match()
        defense = match.defending_side()
        stack = self.stand_on_the_ball(match, defense, 2)
        match.begin_loose_ball(1)

        cog.engine.auto_resolve_loose_ball_picks(game, match)

        self.assertIsNone(match.loose_ball_defense_player)
        self.assertEqual(
            cog.engine.loose_ball_candidates(match, defense), stack,
        )
        # Nobody may be walked in past them, either -- the pool is one
        # of two and never a mixture.
        for player_id in cog.engine.loose_ball_candidates(match, defense):
            self.assertEqual(match.distance_to_ball(player_id), 0)

    def test_the_stack_s_prompt_offers_no_way_out(self) -> None:
        cog = build_cog()
        game = build_game()
        match = self.build_match()
        defense = match.defending_side()
        self.stand_on_the_ball(match, defense, 2)
        match.begin_loose_ball(1)
        match.decline_loose_ball(match.ball.possession)
        game.match_state = match.to_dict()
        cog.games[game.game_id] = game

        self.assertEqual(
            cog.engine.loose_ball_side_on_the_clock(match), "defense",
        )
        view = cog.build_loose_ball_view(game.game_id, match)
        labels = [item.label for item in view.children]
        self.assertNotIn("Send nobody", labels)
        self.assertEqual(len(labels), 2)
        # And the prompt says which question it is asking.
        prompt = cog.engine.build_loose_ball_prompt(game, match, {})
        self.assertIn("which of them contests", prompt)

    def test_both_sides_on_the_ball_go_straight_to_the_test(self) -> None:
        cog = build_cog()
        game = build_game()
        match = self.build_match()
        offense, defense = match.ball.possession, match.defending_side()
        (attacker,) = self.stand_on_the_ball(match, offense, 1)
        match.board.remove_meeple(
            defender := match.setup_for_side(defense).field_players[0]
        )
        match.board.place_meeple(
            defender, match.ball.zone, match.ball.space_index,
        )
        match.begin_loose_ball(1)

        cog.engine.auto_resolve_loose_ball_picks(game, match)

        self.assertEqual(match.loose_ball_offense_player, attacker)
        self.assertEqual(match.loose_ball_defense_player, defender)
        self.assertIsNone(cog.engine.loose_ball_side_on_the_clock(match))

    async def test_a_deflect_onto_a_teammate_is_still_loose(
        self,
    ) -> None:
        """
        The rule this change is named for. The deflection knocks the
        ball out of the handler's possession, and a teammate a space
        back is no longer enough to keep it -- they contest for it.
        """
        cog = build_cog()
        cog.begin_loose_ball = mock.AsyncMock()
        game = build_game()
        match = self.build_match()
        match.ball.possession = TeamSide.HOME
        match.set_ball_space(Zone.MIDFIELD, 1)
        match.challenger_id = match.visiting.field_players[0]
        # HOME attacks left to right, so the deflection lands one space
        # lower: put a home card there to be deflected onto.
        landing = (Zone.MIDFIELD, 0)
        teammate = match.home.field_players[0]
        match.move_meeple(teammate, *landing)

        with suppressed_cog_saves():
            await cog.resolve_deflect(
                SimpleNamespace(), game, match,
            )

        self.assertEqual(
            (match.ball.zone, match.ball.space_index), landing,
        )
        # The teammate is standing on it and possession has not moved,
        # but it is a contest all the same.
        self.assertIn(teammate, match.eligible_ball_handlers())
        cog.finish_maneuver_resolution.assert_not_awaited()
        cog.begin_loose_ball.assert_awaited_once()
        self.assertEqual(cog.begin_loose_ball.await_args.args[3], 1)

    def test_the_headline_names_which_of_the_three_arrivals_it_is(
        self,
    ) -> None:
        """
        **Only an empty space is a loose ball** (the author,
        2026-08-26), so the headline reads the position and the word
        "loose" is reserved for the one arrival it is true of.
        """
        cog = build_cog()
        match = self.build_match()
        # The standard deal stands somebody on the kickoff space, which
        # is where the ball starts -- clear it for the empty case.
        for occupant in list(
            match.board.spaces[match.ball.zone][match.ball.space_index]
        ):
            match.board.remove_meeple(occupant)
        empty = cog.engine.build_loose_ball_headline(match)
        self.assertIn("Loose ball!", empty)
        self.assertIn("empty space", empty)

        self.stand_on_the_ball(match, match.defending_side(), 1)
        one_side = cog.engine.build_loose_ball_headline(match)
        self.assertNotIn("Loose ball!", one_side)
        # Says whose it is, rather than which of the other two
        # positions this is not (the author, 2026-08-27).
        self.assertIn("so they get the ball", one_side)
        self.assertNotIn("Not loose", one_side)
        self.assertNotIn("may be sent", one_side)

        # Placed directly rather than through stand_on_the_ball, which
        # clears the space first -- both sides have to be there at once.
        attacker = match.setup_for_side(match.ball.possession).field_players[0]
        match.board.remove_meeple(attacker)
        match.board.place_meeple(
            attacker, match.ball.zone, match.ball.space_index,
        )
        both = cog.engine.build_loose_ball_headline(match)
        self.assertNotIn("Loose ball!", both)
        self.assertIn("Contest!", both)


class OccupancyDecidesTests(unittest.IsolatedAsyncioTestCase):
    """
    **What the ball comes down on decides how it is won**, which since
    2026-08-26 is every arrival's rule rather than Deflect/Clear's own
    flag. Three positions:

    - an empty space is a **loose ball**, and each side may send;
    - a space only one side occupies is simply **theirs**, with the
      other pre-declined rather than offered a send;
    - a space both occupy is a **contest** between the players already
      there.

    A High Pass is the one exemption: the ball is in the air, which
    gives players time to run at it, so a landing space holding only
    one side's players may still be contested by the other.

    See "The loose ball" in docs/living-rules.md and begin_loose_ball
    in cogs/d12ball.py.
    """

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

    def clear_the_ball(self, match: MatchState) -> None:
        for occupant in list(
            match.board.spaces[match.ball.zone][match.ball.space_index]
        ):
            match.board.remove_meeple(occupant)

    def stand_on_the_ball(
        self, match: MatchState, side: TeamSide, count: int = 1,
    ) -> list[str]:
        chosen = match.setup_for_side(side).field_players[:count]
        for player_id in chosen:
            match.board.remove_meeple(player_id)
            match.board.place_meeple(
                player_id, match.ball.zone, match.ball.space_index,
            )
        return chosen

    async def begin(self, cog, game, match):
        with suppressed_cog_saves():
            await cog.begin_loose_ball(
                build_interaction(), game, match, 1,
            )

    async def test_an_empty_landing_space_is_an_ordinary_loose_ball(
        self,
    ) -> None:
        cog = build_cog()
        cog.resolve_loose_ball = mock.AsyncMock()
        game = build_game()
        match = self.build_match()
        self.clear_the_ball(match)
        game.match_state = match.to_dict()
        cog.games[game.game_id] = game

        await self.begin(cog, game, match)

        self.assertFalse(match.loose_ball_offense_declined)
        self.assertFalse(match.loose_ball_defense_declined)
        self.assertEqual(
            cog.engine.loose_ball_side_on_the_clock(match), "offense",
        )
        cog.resolve_loose_ball.assert_not_awaited()

    async def test_only_the_defense_present_keeps_it_uncontested(
        self,
    ) -> None:
        cog = build_cog()
        cog.resolve_loose_ball = mock.AsyncMock()
        game = build_game()
        match = self.build_match()
        self.clear_the_ball(match)
        defense = match.defending_side()
        (defender,) = self.stand_on_the_ball(match, defense)
        game.match_state = match.to_dict()
        cog.games[game.game_id] = game

        await self.begin(cog, game, match)

        # The offense has nobody there, and is pre-declined rather than
        # put on the clock -- never offered a send.
        self.assertTrue(match.loose_ball_offense_declined)
        self.assertFalse(match.loose_ball_defense_declined)
        self.assertEqual(match.loose_ball_defense_player, defender)
        self.assertIsNone(cog.engine.loose_ball_side_on_the_clock(match))
        cog.resolve_loose_ball.assert_awaited_once()
        # The one message this posts says the ball is theirs, not the
        # ordinary "each side may send" wording -- and it is never
        # called loose, since it never was: only an empty landing space
        # is (the author, 2026-08-26). It does not mention the send
        # that was not offered either, which is a question no coach
        # reading this has asked (the author, 2026-08-27).
        content = cog.announce_board_update.await_args.args[2]
        self.assertIn("so they get the ball", content)
        self.assertNotIn("Loose ball!", content)
        self.assertNotIn("may be sent", content)

    async def test_a_high_pass_may_still_be_run_at(self) -> None:
        """
        **The one exemption** (the author, 2026-08-26): a High Pass is
        high in the air, which gives players time to run towards it,
        so the other side gets a chance at a landing space holding
        only the passer's own teammates. Every other arrival on that
        same position is simply theirs.

        Asserted symmetrically -- the justification is about the ball
        rather than about which side threw it, so the same position
        with only the *defense* standing there is contestable too.
        """
        for occupied_side in ("offense", "defense"):
            with self.subTest(occupied=occupied_side):
                cog = build_cog()
                cog.resolve_loose_ball = mock.AsyncMock()
                game = build_game()
                match = self.build_match()
                self.clear_the_ball(match)
                side = (
                    match.ball.possession
                    if occupied_side == "offense"
                    else match.defending_side()
                )
                self.stand_on_the_ball(match, side)
                game.match_state = match.to_dict()
                cog.games[game.game_id] = game

                with suppressed_cog_saves():
                    await cog.begin_loose_ball(
                        build_interaction(), game, match, 3,
                        headline=HIGH_PASS_CONTEST_HEADLINE,
                        is_high_pass=True,
                    )

                # Nobody is pre-declined, and the empty side is put on
                # the clock to send somebody after it.
                self.assertFalse(match.loose_ball_offense_declined)
                self.assertFalse(match.loose_ball_defense_declined)
                self.assertIsNotNone(
                    cog.engine.loose_ball_side_on_the_clock(match),
                )
                cog.resolve_loose_ball.assert_not_awaited()

    async def test_only_the_offense_present_keeps_it_uncontested(
        self,
    ) -> None:
        # The same rule from the other side: it is about occupancy, not
        # about who last had the ball.
        cog = build_cog()
        cog.resolve_loose_ball = mock.AsyncMock()
        game = build_game()
        match = self.build_match()
        self.clear_the_ball(match)
        offense = match.ball.possession
        (attacker,) = self.stand_on_the_ball(match, offense)
        game.match_state = match.to_dict()
        cog.games[game.game_id] = game

        await self.begin(cog, game, match)

        self.assertFalse(match.loose_ball_offense_declined)
        self.assertTrue(match.loose_ball_defense_declined)
        self.assertEqual(match.loose_ball_offense_player, attacker)
        self.assertIsNone(cog.engine.loose_ball_side_on_the_clock(match))
        cog.resolve_loose_ball.assert_awaited_once()

    async def test_both_sides_present_is_still_a_forced_contest(
        self,
    ) -> None:
        # Neither an occupant may withhold themselves, restricted or
        # not -- this branch is unaffected by the new rule.
        cog = build_cog()
        cog.resolve_loose_ball = mock.AsyncMock()
        game = build_game()
        match = self.build_match()
        self.clear_the_ball(match)
        offense, defense = match.ball.possession, match.defending_side()
        (attacker,) = self.stand_on_the_ball(match, offense)
        (defender,) = self.stand_on_the_ball(match, defense)
        game.match_state = match.to_dict()
        cog.games[game.game_id] = game

        await self.begin(cog, game, match)

        self.assertFalse(match.loose_ball_offense_declined)
        self.assertFalse(match.loose_ball_defense_declined)
        self.assertEqual(match.loose_ball_offense_player, attacker)
        self.assertEqual(match.loose_ball_defense_player, defender)
        cog.resolve_loose_ball.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
