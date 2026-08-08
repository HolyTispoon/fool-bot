"""
The end of the game: who gets to play last possession, how full time is
announced, the tie modes, and the rematch button.

Two rules meet here. Last possession is the possession that *starts* at
15 space minutes, so the maneuver that puts the clock there never ends
the period even when it is itself a turnover -- only a later turnover
does. And a level score at full time ends the game in league mode,
where a tournament game would go to the extreme shootout. See
"The clock, halftime and full time" in docs/living-rules.md.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

from cogs.d12ball import D12Ball
from cogs.d12ball_helpers import TIE_MODE_LABELS, build_full_time_summary
from cogs.d12ball_views import (
    CoinFlipView,
    FormationSelectionView,
    RematchView,
    TeamSelectionView,
)
from d12ball.components import (
    MatchPeriod,
    MatchState,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.game import (
    AIOpponent,
    D12BallGame,
    GameStatus,
    Team,
    TieMode,
)


def build_cog() -> D12Ball:
    cog = object.__new__(D12Ball)
    cog.games = {}
    cog.player_catalog = load_player_catalog()
    cog.maneuver_catalog = load_maneuver_catalog()
    cog.basic_ruleset = load_basic_ruleset()
    cog.team_emojis = {}
    cog.condition_emojis = {}
    cog.coin_emojis = {}
    cog.refresh_match_image = mock.AsyncMock()
    cog.build_match_file = mock.AsyncMock(return_value=None)
    cog.check_for_loose_ball = mock.AsyncMock(return_value=False)
    cog.send_turn_prompt = mock.AsyncMock()
    return cog


def build_game(**overrides) -> D12BallGame:
    fields = dict(
        game_id="g1",
        game_number=1,
        guild_id=1,
        channel_id=2,
        message_id=None,
        player_1_id=111,
        player_2_id=222,
        player_1_name="One",
        player_2_name="Two",
        player_1_team=Team.ORANGE,
        player_2_team=Team.PURPLE,
        home_player_number=1,
        visiting_player_number=2,
        status=GameStatus.IN_PROGRESS,
    )
    fields.update(overrides)
    return D12BallGame(**fields)


def build_interaction() -> SimpleNamespace:
    return SimpleNamespace(
        user=SimpleNamespace(id=111, display_name="One"),
        message=SimpleNamespace(edit=mock.AsyncMock()),
        followup=SimpleNamespace(
            send=mock.AsyncMock(return_value=SimpleNamespace(id=999)),
        ),
        response=SimpleNamespace(
            defer=mock.AsyncMock(),
            send_message=mock.AsyncMock(),
            edit_message=mock.AsyncMock(),
        ),
    )


def sent_texts(interaction: SimpleNamespace) -> list[str]:
    return [
        call.args[0] if call.args else call.kwargs.get("content", "")
        for call in interaction.followup.send.await_args_list
    ]


class LastPossessionTests(unittest.IsolatedAsyncioTestCase):
    """
    finish_maneuver_resolution's clock handling: reaching 15 declares
    last possession, and only a turnover under a last possession that
    was already in force ends the period.
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

    async def resolve(self, cog, game, match, **kwargs):
        interaction = build_interaction()
        with mock.patch("cogs.d12ball.save_games"), mock.patch(
            "cogs.d12ball.add_full_image_button", mock.AsyncMock(),
        ):
            await cog.finish_maneuver_resolution(
                interaction, game, match, **kwargs,
            )
        return interaction

    async def test_the_turnover_that_reaches_15_plays_on(self) -> None:
        # The maneuver that brings the clock up to 15 hands the ball
        # over and last possession belongs to whoever received it --
        # the game does not end on the turnover that declared it.
        cog = build_cog()
        cog.end_period = mock.AsyncMock()
        game = build_game()
        match = self.build_match()
        match.scoreboard.time = 14
        game.match_state = match.to_dict()
        cog.games[game.game_id] = game

        interaction = await self.resolve(
            cog, game, match, distance_moved=1, turnover_occurred=True,
        )

        cog.end_period.assert_not_awaited()
        self.assertTrue(match.scoreboard.last_possession)
        cog.send_turn_prompt.assert_awaited_once()
        announcement = sent_texts(interaction)[0]
        self.assertIn("last possession", announcement)
        self.assertIn("doesn't end it", announcement)

    async def test_a_later_turnover_ends_the_period(self) -> None:
        # The next turnover, with last possession already in force, is
        # the one that ends it.
        cog = build_cog()
        cog.end_period = mock.AsyncMock()
        game = build_game()
        match = self.build_match()
        match.scoreboard.time = 15
        match.scoreboard.last_possession = True
        game.match_state = match.to_dict()
        cog.games[game.game_id] = game

        await self.resolve(
            cog, game, match, distance_moved=1, turnover_occurred=True,
        )

        cog.end_period.assert_awaited_once()
        cog.send_turn_prompt.assert_not_awaited()

    async def test_reaching_15_without_a_turnover_reads_the_old_way(
        self,
    ) -> None:
        cog = build_cog()
        cog.end_period = mock.AsyncMock()
        game = build_game()
        match = self.build_match()
        match.scoreboard.time = 14
        game.match_state = match.to_dict()
        cog.games[game.game_id] = game

        interaction = await self.resolve(
            cog, game, match, distance_moved=1, turnover_occurred=False,
        )

        cog.end_period.assert_not_awaited()
        announcement = sent_texts(interaction)[0]
        self.assertIn("Play continues until the ball turns over", announcement)


class FullTimeSummaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    def build_match(self, home_score: int, visiting_score: int) -> MatchState:
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
        )
        match.scoreboard.home_score = home_score
        match.scoreboard.visiting_score = visiting_score
        return match

    def test_the_winning_team_and_player_are_named(self) -> None:
        summary = build_full_time_summary(
            build_game(), self.build_match(3, 1),
        )

        self.assertIn("Final score: Orange 3:1 Purple", summary)
        self.assertIn("# Orange wins!", summary)
        self.assertIn("<@111>", summary)
        self.assertNotIn("<@222>", summary)

    def test_the_visiting_side_can_win_it(self) -> None:
        summary = build_full_time_summary(
            build_game(), self.build_match(1, 2),
        )

        self.assertIn("# Purple wins!", summary)
        self.assertIn("<@222>", summary)

    def test_the_ai_can_win_it(self) -> None:
        game = build_game(
            player_2_id=None,
            player_2_name=None,
            ai_opponent=AIOpponent.DINKY,
        )

        summary = build_full_time_summary(game, self.build_match(0, 1))

        self.assertIn("# Purple wins!", summary)
        self.assertIn("Dinky AI", summary)

    def test_a_league_game_is_allowed_to_end_tied(self) -> None:
        summary = build_full_time_summary(
            build_game(tie_mode=TieMode.LEAGUE), self.build_match(2, 2),
        )

        self.assertIn("It's a tie!", summary)
        self.assertIn("League mode", summary)
        self.assertNotIn("shootout", summary)

    def test_a_tournament_tie_goes_to_the_shootout(self) -> None:
        summary = build_full_time_summary(
            build_game(tie_mode=TieMode.TOURNAMENT), self.build_match(2, 2),
        )

        self.assertIn("It's a tie!", summary)
        self.assertIn("extreme shootout", summary)


class EndPeriodFullTimeTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    async def test_full_time_finishes_the_game_and_offers_a_rematch(
        self,
    ) -> None:
        cog = build_cog()
        game = build_game()
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
        )
        match.scoreboard.period = MatchPeriod.SECOND_HALF
        match.scoreboard.time = 15
        match.scoreboard.last_possession = True
        match.scoreboard.home_score = 2
        match.scoreboard.visiting_score = 1
        game.match_state = match.to_dict()
        cog.games[game.game_id] = game
        interaction = build_interaction()

        with mock.patch("cogs.d12ball.save_games"):
            await cog.end_period(interaction, game, match)

        self.assertTrue(game.is_finished)
        self.assertEqual(game.rematch_message_id, 999)
        announcement = sent_texts(interaction)[0]
        self.assertIn("Full time!", announcement)
        self.assertIn("# Orange wins!", announcement)
        view = interaction.followup.send.await_args.kwargs["view"]
        self.assertIsInstance(view, RematchView)
        self.assertEqual(
            [item.label for item in view.children], ["Rematch"],
        )


class TieModeSetupTests(unittest.IsolatedAsyncioTestCase):
    def tie_buttons(self, view) -> list:
        return [
            item for item in view.children
            if item.custom_id
            and item.custom_id.startswith("d12ball:tie_mode:")
        ]

    def build_cog_with(self, game) -> D12Ball:
        cog = build_cog()
        cog.games[game.game_id] = game
        return cog

    def test_both_tie_modes_are_offered_with_their_own_wording(self) -> None:
        game = build_game(status=GameStatus.SETUP)
        view = TeamSelectionView(self.build_cog_with(game), game.game_id)

        self.assertEqual(
            [item.label for item in self.tie_buttons(view)],
            [
                TIE_MODE_LABELS[TieMode.LEAGUE],
                TIE_MODE_LABELS[TieMode.TOURNAMENT],
            ],
        )

    def test_the_setup_message_names_the_tie_rules(self) -> None:
        from cogs.d12ball_helpers import build_setup_message

        game = build_game(status=GameStatus.SETUP)

        self.assertIn(
            TIE_MODE_LABELS[TieMode.LEAGUE], build_setup_message(game),
        )

    def test_every_setup_button_fits_discord_s_five_rows(self) -> None:
        # The settings block grew a row; a test game's two team rows
        # and a solo game's AI row are what make this tight.
        for game in (
            build_game(status=GameStatus.SETUP),
            build_game(
                status=GameStatus.SETUP,
                player_2_id=None,
                player_2_name=None,
                ai_opponent=AIOpponent.DINKY,
            ),
            build_game(
                status=GameStatus.SETUP,
                player_2_id=111,
                player_1_team=None,
                player_2_team=None,
                home_player_number=None,
                visiting_player_number=None,
                test_game=True,
            ),
        ):
            cog = self.build_cog_with(game)
            for view_type in (
                TeamSelectionView,
                FormationSelectionView,
                CoinFlipView,
            ):
                with self.subTest(game=game.game_id, view=view_type.__name__):
                    view = view_type(cog, game.game_id)
                    rows = [item.row for item in view.children]
                    self.assertLessEqual(max(rows), 4)
                    for row in set(rows):
                        self.assertLessEqual(rows.count(row), 5)

    async def test_tournament_mode_is_refused_for_now(self) -> None:
        game = build_game(status=GameStatus.SETUP)
        cog = self.build_cog_with(game)
        view = TeamSelectionView(cog, game.game_id)
        interaction = build_interaction()

        with mock.patch("cogs.d12ball_views.save_games"):
            await view.select_tie_mode(interaction, TieMode.TOURNAMENT)

        self.assertEqual(game.tie_mode, TieMode.LEAGUE)
        message = interaction.response.send_message.await_args.args[0]
        self.assertIn("tournament mode is not yet ready", message)
        interaction.response.edit_message.assert_not_awaited()


class RematchTests(unittest.IsolatedAsyncioTestCase):
    def build_finished_game(self, **overrides) -> D12BallGame:
        game = build_game(**overrides)
        game.status = GameStatus.FINISHED
        return game

    async def test_a_rematch_reuses_the_players_and_the_settings(
        self,
    ) -> None:
        cog = build_cog()
        game = self.build_finished_game(board_size=9)
        cog.games[game.game_id] = game
        rematch = build_game(game_id="g2", game_number=2, channel_id=22)
        cog.open_new_game = mock.AsyncMock(return_value=rematch)
        cog.archive_game_channel = mock.AsyncMock()
        player_1 = SimpleNamespace(id=111)
        player_2 = SimpleNamespace(id=222)
        guild = SimpleNamespace(
            get_member=lambda user_id: {
                111: player_1, 222: player_2,
            }[user_id],
        )
        cog.bot = SimpleNamespace(get_guild=lambda guild_id: guild)

        with mock.patch("cogs.d12ball.save_games"):
            created = await cog.start_rematch(game)

        self.assertIs(created, rematch)
        self.assertEqual(game.rematch_game_id, "g2")
        cog.archive_game_channel.assert_awaited_once_with(game)
        args, kwargs = cog.open_new_game.await_args
        self.assertEqual(args[1:], (player_1, player_2))
        self.assertEqual(kwargs["board_size"], 9)
        self.assertEqual(kwargs["tie_mode"], game.tie_mode)
        self.assertEqual(kwargs["mode"], game.mode)

    async def test_a_solo_rematch_keeps_playing_the_ai(self) -> None:
        cog = build_cog()
        game = self.build_finished_game(
            player_2_id=None,
            player_2_name=None,
            ai_opponent=AIOpponent.DINKY,
        )
        cog.games[game.game_id] = game
        cog.open_new_game = mock.AsyncMock(
            return_value=build_game(game_id="g2", game_number=2),
        )
        cog.archive_game_channel = mock.AsyncMock()
        cog.bot = SimpleNamespace(
            get_guild=lambda guild_id: SimpleNamespace(
                get_member=lambda user_id: SimpleNamespace(id=user_id),
            ),
        )

        with mock.patch("cogs.d12ball.save_games"):
            await cog.start_rematch(game)

        args, kwargs = cog.open_new_game.await_args
        self.assertIsNone(args[2])
        self.assertEqual(kwargs["ai_opponent"], AIOpponent.DINKY)

    async def test_only_a_player_can_ask_for_the_rematch(self) -> None:
        cog = build_cog()
        game = self.build_finished_game()
        cog.games[game.game_id] = game
        cog.start_rematch = mock.AsyncMock()
        view = RematchView(cog, game.game_id)
        interaction = build_interaction()
        interaction.user = SimpleNamespace(id=999, display_name="Nobody")

        await view.start_rematch(interaction)

        cog.start_rematch.assert_not_awaited()
        self.assertIn(
            "Only a player in this game",
            interaction.response.send_message.await_args.args[0],
        )

    async def test_a_second_click_points_at_the_rematch_already_open(
        self,
    ) -> None:
        cog = build_cog()
        game = self.build_finished_game()
        rematch = build_game(game_id="g2", game_number=2, channel_id=22)
        game.rematch_game_id = rematch.game_id
        cog.games[game.game_id] = game
        cog.games[rematch.game_id] = rematch
        cog.start_rematch = mock.AsyncMock()
        view = RematchView(cog, game.game_id)
        interaction = build_interaction()

        await view.start_rematch(interaction)

        cog.start_rematch.assert_not_awaited()
        self.assertIn(
            "<#22>",
            interaction.response.send_message.await_args.args[0],
        )
        # And the button itself comes back disabled, so the rematch
        # message stops inviting the click at all.
        self.assertTrue(view.children[0].disabled)

    async def test_the_button_opens_the_rematch_and_reports_it(self) -> None:
        cog = build_cog()
        game = self.build_finished_game()
        cog.games[game.game_id] = game
        rematch = build_game(game_id="g2", game_number=2, channel_id=22)
        cog.start_rematch = mock.AsyncMock(return_value=rematch)
        view = RematchView(cog, game.game_id)
        interaction = build_interaction()

        await view.start_rematch(interaction)

        cog.start_rematch.assert_awaited_once_with(game, interaction.user)
        interaction.message.edit.assert_awaited_once()
        self.assertIn(
            "<#22>", interaction.followup.send.await_args.args[0],
        )


if __name__ == "__main__":
    unittest.main()
