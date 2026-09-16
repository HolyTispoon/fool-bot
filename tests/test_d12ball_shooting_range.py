"""
A shot may only be taken from within shooting range.

The rule is one predicate -- MatchState.can_attempt_score -- and these
cover the geometry it rests on and the three places it is enforced: the
turn's own shoot button, a High Pass of 2, and a Winger's Low Pass.
Range is measured from the middle of the *board*, so it is the far part
of midfield plus the goal zone a team attacks, and an odd-sized board's
middle space is in nobody's range.

See "Score attempt" and "Shooting range" in docs/living-rules.md.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

from cogs.d12ball import D12Ball
from cogs.d12ball_views import PlayerActionView
from d12ball.ai import DinkyAI
from d12ball.components import (
    MatchState,
    PlayerRole,
    TeamSide,
    Zone,
    kickoff_space_index,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.engine import RulesEngine
from d12ball.game import D12BallGame, Team
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
    cog.finish_maneuver_resolution = mock.AsyncMock()
    cog.offer_scoring_attempt_choice = mock.AsyncMock()
    cog.begin_loose_ball = mock.AsyncMock()
    cog.begin_score_attempt = mock.AsyncMock()
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


class ShootingRangeGeometryTests(unittest.TestCase):
    """Which spaces each side may shoot from, board by board."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    def build_match(self, board_size: int) -> MatchState:
        return MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=board_size,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
        )

    def shooting_spaces(
        self, match: MatchState, side: TeamSide,
    ) -> list[int]:
        return [
            index
            for index in range(match.board.layout.board_size)
            if match.board.is_in_shooting_range(side, index)
        ]

    def test_each_side_may_shoot_only_from_beyond_the_middle(self) -> None:
        # Home attacks the high indices, the visitors the low ones, and
        # on 7 and 9 the true middle space is in nobody's range.
        expected = {
            6: ([3, 4, 5], [0, 1, 2]),
            7: ([4, 5, 6], [0, 1, 2]),
            9: ([5, 6, 7, 8], [0, 1, 2, 3]),
        }
        for board_size, (home, visiting) in expected.items():
            match = self.build_match(board_size)
            with self.subTest(board_size=board_size):
                self.assertEqual(
                    self.shooting_spaces(match, TeamSide.HOME), home,
                )
                self.assertEqual(
                    self.shooting_spaces(match, TeamSide.VISITING), visiting,
                )

    def test_range_is_more_than_the_zone_a_team_attacks(self) -> None:
        # The edge is the middle of the board, not a zone boundary: the
        # near part of midfield is out of range and its far part is in,
        # so range is never just the goal zone.
        match = self.build_match(7)
        for space_index, home_may_shoot in ((0, False), (1, False), (2, True)):
            with self.subTest(space=space_index):
                self.assertEqual(
                    match.board.is_in_shooting_range(
                        TeamSide.HOME,
                        match.board.flat_index(Zone.MIDFIELD, space_index),
                    ),
                    home_may_shoot,
                )

    def test_no_restart_begins_in_shooting_range(self) -> None:
        # The kickoff space is the middle space (7 and 9), which is in
        # nobody's range, or -- on 6 -- behind the kicking side's own.
        for board_size in (6, 7, 9):
            match = self.build_match(board_size)
            for side in TeamSide:
                with self.subTest(board_size=board_size, side=side):
                    match.ball.possession = side
                    match.ball.zone = Zone.MIDFIELD
                    match.ball.space_index = kickoff_space_index(
                        len(match.board.spaces[Zone.MIDFIELD]), side,
                    )
                    self.assertFalse(match.can_attempt_score())

    def test_can_attempt_score_defaults_to_the_side_in_possession(
        self,
    ) -> None:
        # The maneuver effects pass the offense they read at the top of
        # the effect; everything else asks about whoever holds the ball.
        match = self.build_match(7)
        match.ball.zone = Zone.HOME_GOAL
        match.ball.space_index = 0

        match.ball.possession = TeamSide.HOME
        self.assertFalse(match.can_attempt_score())
        self.assertTrue(match.can_attempt_score(TeamSide.VISITING))

        match.ball.possession = TeamSide.VISITING
        self.assertTrue(match.can_attempt_score())

    def test_the_scoring_space_is_always_within_range(self) -> None:
        # What keeps the AI honest: DinkyAI shoots only from the space
        # closest to the opponent's goal, which the range rule always
        # allows.
        strategy = DinkyAI(self.catalog, load_maneuver_catalog())
        for board_size in (6, 7, 9):
            match = self.build_match(board_size)
            for side in TeamSide:
                with self.subTest(board_size=board_size, side=side):
                    match.ball.possession = side
                    zone, space_index = match.own_goal_restart_space(
                        TeamSide.VISITING
                        if side == TeamSide.HOME
                        else TeamSide.HOME
                    )
                    match.ball.zone = zone
                    match.ball.space_index = space_index

                    self.assertTrue(match.is_ball_at_scoring_space())
                    self.assertTrue(match.can_attempt_score())
                    self.assertEqual(strategy.choose_action(match), "shoot")


class ShootButtonTests(unittest.IsolatedAsyncioTestCase):
    """The turn's own choice: the button is there or it is not."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    def build_turn(self, zone: Zone, space_index: int):
        """
        Home in possession with the ball at a given space, and a
        handler standing on it.
        """
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
        match.ball.zone = zone
        match.ball.space_index = space_index

        handler = match.home.field_players[0]
        match.move_meeple(handler, zone, space_index)
        match.select_ball_handler(handler)

        game.match_state = match.to_dict()
        cog.games[game.game_id] = game
        return cog, game, match

    def test_the_shoot_button_is_offered_only_within_range(self) -> None:
        cog, game, _ = self.build_turn(Zone.VISITORS_GOAL, 0)
        self.assertEqual(
            [item.label for item in PlayerActionView(
                cog, game.game_id,
            ).children],
            ["Shoot to score", "Maneuver"],
        )

        # Out of range the cede takes the shot's place -- the two are
        # the same read, so a coach never sees both.
        cog, game, _ = self.build_turn(Zone.MIDFIELD, 0)
        self.assertEqual(
            [item.label for item in PlayerActionView(
                cog, game.game_id,
            ).children],
            ["Maneuver", "Time out"],
        )

    def test_the_prompt_says_why_the_shot_is_missing(self) -> None:
        cog, game, match = self.build_turn(Zone.MIDFIELD, 0)
        # The reason, then what is left -- the prompt does not also
        # spell out that there is no shot, which is the button that
        # is not on the message.
        self.assertIn(
            "Out of shooting range",
            cog.engine.build_turn_prompt(game, match, {}),
        )

        cog, game, match = self.build_turn(Zone.VISITORS_GOAL, 0)
        self.assertIn(
            "Choose an action:",
            cog.engine.build_turn_prompt(game, match, {}),
        )

    async def test_a_stale_shoot_click_is_refused(self) -> None:
        # The button is never built out of range, so reaching
        # choose_action("shoot") means the ball moved under a prompt
        # somebody was still looking at.
        cog, game, _ = self.build_turn(Zone.MIDFIELD, 0)
        cog.engine.user_controls_possession = mock.Mock(return_value=True)
        interaction = build_interaction()

        view = PlayerActionView(cog, game.game_id)
        await view.choose_action(interaction, "shoot", "Shoot to score")

        interaction.response.send_message.assert_awaited_once()
        self.assertIn(
            "out of shooting range",
            interaction.response.send_message.await_args.args[0],
        )
        cog.begin_score_attempt.assert_not_awaited()


class SetUpShotRangeTests(unittest.IsolatedAsyncioTestCase):
    """
    A set-up buys a shot out of turn, not a shot from anywhere: it is
    offered only where an ordinary score attempt would be legal.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    def build_pass(self, handler_role: PlayerRole, ball_flat: int):
        """
        Home in possession with the ball at `ball_flat`, a handler of
        `handler_role` on it, and a teammate two spaces ahead ready to
        receive.
        """
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
        zone, space_index = match.board.position_at_flat_index(ball_flat)
        match.ball.zone = zone
        match.ball.space_index = space_index

        handler = next(
            player_id
            for player_id in match.home.field_players
            if self.catalog.player_by_id(player_id).role == handler_role
        )
        receiver = next(
            player_id
            for player_id in match.home.field_players
            if player_id != handler
        )
        match.move_meeple(handler, zone, space_index)
        match.move_meeple(
            receiver,
            *match.board.position_at_flat_index(ball_flat + 2),
        )
        match.select_ball_handler(handler)

        game.match_state = match.to_dict()
        cog.games[game.game_id] = game
        return cog, game, match, receiver

    async def apply_high_pass(self, cog, game, match) -> None:
        with suppressed_cog_saves():
            await cog.apply_high_pass(build_interaction(), game, match, 2)

    async def test_a_high_pass_of_two_sets_up_only_within_range(
        self,
    ) -> None:
        # Landing on M3 (flat 4) is in range for home; the same pass
        # landing on M1 (flat 2) is not.
        cog, game, match, _ = self.build_pass(PlayerRole.MIDFIELDER, 2)
        await self.apply_high_pass(cog, game, match)
        cog.offer_scoring_attempt_choice.assert_awaited_once()

        cog, game, match, _ = self.build_pass(PlayerRole.MIDFIELDER, 0)
        await self.apply_high_pass(cog, game, match)
        cog.offer_scoring_attempt_choice.assert_not_awaited()

    async def test_a_two_space_pass_short_of_range_is_still_received(
        self,
    ) -> None:
        # The range rule takes away the shot, not the catch. A pass of 2
        # has never had to win a contest, so it must not fall through
        # to the long-pass one.
        cog, game, match, _ = self.build_pass(PlayerRole.MIDFIELDER, 0)
        await self.apply_high_pass(cog, game, match)

        cog.begin_loose_ball.assert_not_awaited()
        cog.finish_maneuver_resolution.assert_awaited_once()

    async def test_a_winger_low_pass_sets_up_only_within_range(
        self,
    ) -> None:
        # The Winger's ability frees the set-up from a distance, not
        # from where a goal can be scored from.
        cog, game, match, receiver = self.build_pass(PlayerRole.WINGER, 2)
        with suppressed_cog_saves():
            await cog.apply_low_pass(
                build_interaction(), game, match, 2, receiver_id=receiver,
            )
        cog.offer_scoring_attempt_choice.assert_awaited_once()

        cog, game, match, receiver = self.build_pass(PlayerRole.WINGER, 0)
        with suppressed_cog_saves():
            await cog.apply_low_pass(
                build_interaction(), game, match, 2, receiver_id=receiver,
            )
        cog.offer_scoring_attempt_choice.assert_not_awaited()
        cog.finish_maneuver_resolution.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
