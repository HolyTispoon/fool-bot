"""
The end of the game: who gets to play last possession, how full time is
announced, and the rematch button.

Two rules meet here. Last possession is the possession that *starts* at
the period's last minute -- 15 in the first half, 30 in the second -- so
the maneuver that puts the clock there never ends the period even when
it is itself a turnover; only a later turnover does. The clock does not
stop there either: it runs on for as long as that possession does, and
the second half then starts at 16 whatever the first half ran to.

And full time settles the game only when the scores differ: a level one
opens the extreme shootout, which is covered in
tests/test_d12ball_shootout.py. See "The clock, halftime and full time"
in docs/living-rules.md.
"""

import asyncio
import unittest
from types import SimpleNamespace
from unittest import mock

import discord

from cogs.d12ball import D12Ball
from cogs.d12ball_helpers import (
    FULL_IMAGE_BUTTON_LABEL,
    PBD_ARCHIVE_CATEGORY_NAME,
    build_full_time_summary,
    build_goal_log,
    build_setup_message,
)
from cogs.d12ball_views import (
    CoinFlipView,
    RematchView,
    TeamSelectionView,
)
from d12ball.components import (
    MatchPeriod,
    MatchState,
    TeamSide,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.engine import RulesEngine
from d12ball.game import (
    AIOpponent,
    D12BallGame,
    GameStatus,
    Team,
)
from save_patches import suppressed_cog_saves, suppressed_full_image_links


def build_cog() -> D12Ball:
    cog = object.__new__(D12Ball)
    cog.games = {}
    cog.player_catalog = load_player_catalog()
    cog.maneuver_catalog = load_maneuver_catalog()
    cog.basic_ruleset = load_basic_ruleset()
    # The role emoji live on the engine and the cog's `role_emojis` is
    # a view of them, so the goal log at full time needs one to read.
    cog.engine = RulesEngine(
        cog.player_catalog, cog.basic_ruleset, cog.maneuver_catalog, {},
    )
    cog.team_emojis = {}
    cog.condition_emojis = {}
    cog.coin_emojis = {}
    cog.refresh_match_image = mock.AsyncMock()
    cog.build_match_file = mock.AsyncMock(return_value=None)
    cog.check_for_loose_ball = mock.AsyncMock(return_value=False)
    # Mind Pull's gate is check_for_loose_ball's twin -- it sits
    # one line above it in finish_maneuver_resolution and answers
    # the same way. Nothing in this file is about it.
    cog.check_for_mind_pull = mock.AsyncMock(return_value=False)
    cog.send_turn_prompt = mock.AsyncMock()
    # The board the game ends on, which announce_game_over posts under
    # the result.
    cog.bot = SimpleNamespace(get_channel=lambda channel_id: None)
    cog.render_match_png = mock.AsyncMock(return_value=b"png")
    cog.match_file_from_png = mock.Mock(return_value=None)
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
        message=SimpleNamespace(edit=mock.AsyncMock(), attachments=[]),
        followup=SimpleNamespace(
            send=mock.AsyncMock(
                return_value=SimpleNamespace(
                    id=999,
                    attachments=[],
                    edit=mock.AsyncMock(),
                ),
            ),
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
    finish_maneuver_resolution's clock handling: reaching the period's
    last minute declares last possession, the clock keeps counting past
    it, and only a turnover under a last possession that was already in
    force ends the period.
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
        with suppressed_cog_saves(), suppressed_full_image_links():
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

    async def test_the_clock_keeps_running_under_last_possession(
        self,
    ) -> None:
        """
        The clock used to stop dead at 15, which is how last possession
        was recorded at all. It is a flag now, and the minutes a last
        possession takes are charged like any other -- so a first half
        genuinely ends at 19.
        """
        cog = build_cog()
        cog.end_period = mock.AsyncMock()
        game = build_game()
        match = self.build_match()
        match.scoreboard.time = 15
        match.scoreboard.last_possession = True
        game.match_state = match.to_dict()
        cog.games[game.game_id] = game

        interaction = await self.resolve(
            cog, game, match, distance_moved=4, turnover_occurred=False,
        )

        cog.end_period.assert_not_awaited()
        self.assertEqual(match.scoreboard.time, 19)
        # And it is not re-announced: the flag went up once, four
        # minutes ago.
        self.assertNotIn(
            "last possession", " ".join(sent_texts(interaction)).lower()
        )

    async def test_the_second_half_starts_at_16(self) -> None:
        """
        However far past 15 the first half ran. The number on the clock
        means the same thing in every game, which is the whole reason
        the running count does not simply carry on from where the first
        half stopped.
        """
        cog = build_cog()
        cog.begin_halftime = mock.AsyncMock()
        game = build_game()
        match = self.build_match()
        match.scoreboard.time = 19
        match.scoreboard.last_possession = True
        game.match_state = match.to_dict()
        cog.games[game.game_id] = game

        interaction = build_interaction()
        with suppressed_cog_saves():
            await cog.end_period(interaction, game, match)

        self.assertEqual(match.scoreboard.period, MatchPeriod.SECOND_HALF)
        self.assertEqual(match.scoreboard.time, 16)
        self.assertFalse(match.scoreboard.last_possession)
        self.assertEqual(match.scoreboard.last_minute, 30)
        cog.begin_halftime.assert_awaited_once()
        # The half is reported where it actually ended, since that is
        # no longer the same number for every game.
        self.assertIn("at 19", sent_texts(interaction)[0])

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

    def test_a_level_score_goes_to_the_shootout(self) -> None:
        summary = build_full_time_summary(
            build_game(), self.build_match(2, 2),
        )

        self.assertIn("It's a tie!", summary)
        self.assertIn("extreme shootout", summary)
        self.assertNotIn("wins!", summary)

    def test_a_shootout_win_reports_both_scores(self) -> None:
        match = self.build_match(2, 2)
        match.begin_shootout()
        for _ in range(4):
            match.award_shootout_goal(
                TeamSide.HOME, match.home.field_players[0],
            )
        for _ in range(3):
            match.award_shootout_goal(
                TeamSide.VISITING, match.visiting.field_players[0],
            )

        summary = build_full_time_summary(build_game(), match)

        self.assertIn("Final score: Orange 6:5 Purple", summary)
        self.assertIn("2:2 at full time", summary)
        self.assertIn("settled 4-3 on the extreme shootout", summary)
        self.assertIn("# Orange wins!", summary)


class GoalLogTests(unittest.TestCase):
    """
    Who scored and when, which the scoreboard cannot be read backwards
    for. See "The goal log" in CLAUDE.md.
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

    def name(self, player_id: str) -> str:
        return self.catalog.player_by_id(player_id).name

    def log(self, match: MatchState) -> str:
        return build_goal_log(match, self.catalog, {})

    def test_a_goal_is_logged_with_its_scorer_and_minute(self) -> None:
        match = self.build_match()
        scorer = match.home.field_players[0]
        match.scoreboard.time = 7

        match.award_goal(scorer)

        goal = match.goals[-1]
        self.assertEqual(goal.side, TeamSide.HOME)
        self.assertEqual(goal.player_id, scorer)
        self.assertEqual(goal.time, 7)
        self.assertEqual(goal.period, MatchPeriod.FIRST_HALF)
        self.assertIn(f"`07`  {self.name(scorer)}", self.log(match))

    def test_an_own_goal_is_listed_under_the_side_it_counted_for(
        self,
    ) -> None:
        """
        The one line of a scoresheet where the name and the heading
        disagree, which is what (OG) is there to explain.
        """
        match = self.build_match()
        conceder = match.home.field_players[0]
        match.scoreboard.time = 9

        match.concede_own_goal(conceder)

        self.assertEqual(match.scoreboard.visiting_score, 1)
        self.assertEqual(
            [goal.player_id for goal in match.goals_for(TeamSide.VISITING)],
            [conceder],
        )
        log = self.log(match)
        self.assertIn("Orange (Home)** -- none", log)
        self.assertIn(f"{self.name(conceder)} [FB] (OG)", log)

    def test_a_first_half_goal_past_15_is_marked(self) -> None:
        """
        The clock runs on, and the second half starts at 16, so 17 is a
        minute both halves reach. (FH) is on the one that cannot come
        round again.
        """
        match = self.build_match()
        scorer = match.home.field_players[0]
        match.scoreboard.time = 17

        match.award_goal(scorer)
        self.assertTrue(match.goals[-1].in_first_half_overrun)
        self.assertIn("`17 (FH)`", self.log(match))

        # The same minute in the second half is the ordinary case and
        # carries nothing.
        match.scoreboard.period = MatchPeriod.SECOND_HALF
        match.award_goal(scorer)
        self.assertFalse(match.goals[-1].in_first_half_overrun)
        self.assertIn("`17`", self.log(match))

        # And a first-half goal on 15 itself is unambiguous: the second
        # half never reaches it.
        match.scoreboard.period = MatchPeriod.FIRST_HALF
        match.scoreboard.time = 15
        match.award_goal(scorer)
        self.assertFalse(match.goals[-1].in_first_half_overrun)

    def test_shootout_goals_are_listed_apart(self) -> None:
        match = self.build_match()
        scorer = match.home.field_players[0]
        shooter = match.visiting.field_players[0]
        match.scoreboard.time = 4
        match.award_goal(scorer)

        match.award_shootout_goal(TeamSide.VISITING, shooter)

        log = self.log(match)
        self.assertIn("Extreme shootout", log)
        # The shootout scorer is under the shootout heading and not in
        # the visiting side's own column, which is otherwise empty.
        self.assertIn("Purple (Visiting)** -- none", log)
        self.assertIn(f"Purple: {self.name(shooter)}", log)
        # A shootout goal has no minute worth printing, so it is not
        # stamped with whatever the clock stopped on.
        self.assertNotIn("`04`  " + self.name(shooter), log)

    def test_the_log_survives_a_save(self) -> None:
        match = self.build_match()
        match.scoreboard.time = 16
        match.award_goal(match.home.field_players[0])
        match.concede_own_goal(match.home.field_players[1])

        restored = MatchState.from_dict(match.to_dict(), self.rules)

        self.assertEqual(
            [goal.to_dict() for goal in restored.goals],
            [goal.to_dict() for goal in match.goals],
        )
        self.assertTrue(restored.goals[0].in_first_half_overrun)
        self.assertTrue(restored.goals[1].own_goal)

    def test_a_game_older_than_the_log_still_loads_and_says_so(
        self,
    ) -> None:
        """
        The field was added mid-life, and both developers run the bot
        against their own saves. Such a game keeps playing and logs
        what is left; the count against the scoreboard is what stops a
        part scoresheet reading as the whole one.
        """
        match = self.build_match()
        saved = match.to_dict()
        del saved["goals"]
        saved["scoreboard"]["home_score"] = 2

        restored = MatchState.from_dict(saved, self.rules)

        self.assertEqual(restored.goals, [])
        restored.award_goal(restored.home.field_players[0])
        self.assertIn(
            "2 earlier goal(s) were scored before this game kept a log",
            self.log(restored),
        )


class EndPeriodFullTimeTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    def build_finished_match(self) -> MatchState:
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
        return match

    async def test_full_time_finishes_the_game_and_offers_a_rematch(
        self,
    ) -> None:
        cog = build_cog()
        game = build_game()
        match = self.build_finished_match()
        game.match_state = match.to_dict()
        cog.games[game.game_id] = game
        interaction = build_interaction()

        with suppressed_cog_saves():
            await cog.end_period(interaction, game, match)

        self.assertTrue(game.is_finished)
        self.assertEqual(game.rematch_message_id, 999)
        announcement = sent_texts(interaction)[0]
        self.assertIn("Full time!", announcement)
        self.assertIn("# Orange wins!", announcement)
        view = interaction.followup.send.await_args.kwargs["view"]
        self.assertIsInstance(view, RematchView)
        self.assertEqual(
            [item.label for item in view.children], ["Rematch", "Archive"],
        )

    async def test_the_result_carries_the_board_the_game_ended_on(
        self,
    ) -> None:
        # One render, two uploads: the snapshot under the result, and
        # the persistent board message settled from the same bytes
        # rather than drawn again.
        cog = build_cog()
        game = build_game()
        match = self.build_finished_match()
        game.match_state = match.to_dict()
        cog.games[game.game_id] = game
        interaction = build_interaction()

        with suppressed_cog_saves():
            await cog.end_period(interaction, game, match)

        cog.render_match_png.assert_awaited_once()
        cog.match_file_from_png.assert_called_once_with(game, b"png")
        self.assertIn("file", interaction.followup.send.await_args.kwargs)
        cog.refresh_match_image.assert_awaited_once_with(
            interaction, game, png=b"png",
        )


class GameSetupTests(unittest.IsolatedAsyncioTestCase):
    def build_cog_with(self, game) -> D12Ball:
        cog = build_cog()
        cog.games[game.game_id] = game
        return cog

    def test_setup_offers_no_tie_setting(self) -> None:
        # There is nothing to choose: every tie goes to the extreme
        # shootout, so league mode and the buttons for it are gone.
        game = build_game(status=GameStatus.SETUP)
        view = TeamSelectionView(self.build_cog_with(game), game.game_id)

        self.assertEqual(
            [
                item for item in view.children
                if item.custom_id
                and "tie_mode" in item.custom_id
            ],
            [],
        )
        self.assertNotIn("Ties:", build_setup_message(game))

    def test_every_setup_button_fits_discord_s_five_rows(self) -> None:
        # A test game's two team rows and a solo game's AI row are what
        # make this tight.
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
            for view_type in (TeamSelectionView, CoinFlipView):
                with self.subTest(game=game.game_id, view=view_type.__name__):
                    view = view_type(cog, game.game_id)
                    rows = [item.row for item in view.children]
                    self.assertLessEqual(max(rows), 4)
                    for row in set(rows):
                        self.assertLessEqual(rows.count(row), 5)


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

        with suppressed_cog_saves():
            created = await cog.start_rematch(game)

        self.assertIs(created, rematch)
        self.assertEqual(game.rematch_game_id, "g2")
        cog.archive_game_channel.assert_awaited_once_with(game)
        args, kwargs = cog.open_new_game.await_args
        self.assertEqual(args[1:], (player_1, player_2))
        self.assertEqual(kwargs["board_size"], 9)
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

        with suppressed_cog_saves():
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
        # A rematch archives the channel on its way out, so the archive
        # button greys out in the same edit -- told, not read back off
        # a channel cache that is still a step behind the move.
        rebuilt = interaction.message.edit.await_args.kwargs["view"]
        self.assertTrue(rebuilt.children[1].disabled)

    def test_the_refresh_keeps_the_full_image_link(self) -> None:
        # Editing a view replaces it wholesale, and the link the board
        # under the result carries is not one of the view's children --
        # so rebuilding without re-adding it would strip the link off
        # the last board of the game.
        cog = build_cog()
        game = self.build_finished_game()
        cog.games[game.game_id] = game
        view = RematchView(cog, game.game_id)
        message = SimpleNamespace(
            edit=mock.AsyncMock(),
            attachments=[SimpleNamespace(url="https://cdn/board.png")],
        )

        asyncio.run(view.refresh_buttons(message))

        rebuilt = message.edit.await_args.kwargs["view"]
        self.assertEqual(
            [item.label for item in rebuilt.children],
            ["Rematch", "Archive", FULL_IMAGE_BUTTON_LABEL],
        )


class ArchiveButtonTests(unittest.IsolatedAsyncioTestCase):
    """
    The other button under the result: the pair who are not playing
    again file the channel away without having to abandon a game that
    has already finished.
    """

    def build_finished_game(self, **overrides) -> D12BallGame:
        game = build_game(**overrides)
        game.status = GameStatus.FINISHED
        return game

    def build_cog_with(self, game, archived: bool = False) -> D12Ball:
        cog = build_cog()
        cog.games[game.game_id] = game
        cog.archive_game_channel = mock.AsyncMock()
        category = SimpleNamespace(
            name=PBD_ARCHIVE_CATEGORY_NAME if archived else "PBD Games",
        )
        cog.bot = SimpleNamespace(
            get_channel=lambda channel_id: SimpleNamespace(category=category),
        )
        return cog

    async def test_the_button_moves_the_channel_and_greys_itself_out(
        self,
    ) -> None:
        game = self.build_finished_game()
        cog = self.build_cog_with(game)
        view = RematchView(cog, game.game_id)
        interaction = build_interaction()

        await view.archive_channel(interaction)

        cog.archive_game_channel.assert_awaited_once_with(game)
        self.assertIn(
            "PBD archive", interaction.followup.send.await_args.args[0],
        )
        interaction.message.edit.assert_awaited_once()
        # The button itself, not just that an edit happened. The cog
        # here still reports the channel in the games category, which
        # is exactly what the live client does for a moment after the
        # move -- so reading the state back off the cache would draw
        # this button live again.
        rebuilt = interaction.message.edit.await_args.kwargs["view"]
        self.assertTrue(rebuilt.children[1].disabled)

    async def test_an_archived_channel_offers_no_archive_button(self) -> None:
        game = self.build_finished_game()
        view = RematchView(self.build_cog_with(game, archived=True), game.game_id)

        archive_button = view.children[1]

        self.assertEqual(archive_button.label, "Archive")
        self.assertTrue(archive_button.disabled)

    async def test_a_channel_the_bot_cannot_see_still_offers_it(self) -> None:
        # The move is idempotent, so a button offered when it need not
        # have been costs a no-op; withholding it would leave a pair
        # with no way to archive.
        game = self.build_finished_game()
        cog = self.build_cog_with(game)
        cog.bot = SimpleNamespace(get_channel=lambda channel_id: None)

        self.assertFalse(RematchView(cog, game.game_id).children[1].disabled)

    async def test_a_bystander_cannot_archive_the_channel(self) -> None:
        game = self.build_finished_game()
        cog = self.build_cog_with(game)
        view = RematchView(cog, game.game_id)
        interaction = build_interaction()
        interaction.user = SimpleNamespace(
            id=999,
            display_name="Nobody",
            guild_permissions=SimpleNamespace(manage_channels=False),
        )

        await view.archive_channel(interaction)

        cog.archive_game_channel.assert_not_awaited()
        self.assertIn(
            "Only a player in this game",
            interaction.response.send_message.await_args.args[0],
        )

    async def test_a_moderator_may_archive_it(self) -> None:
        # The same gate as the recovery commands: manage_channels is
        # the blunter version of the same job.
        game = self.build_finished_game()
        cog = self.build_cog_with(game)
        view = RematchView(cog, game.game_id)
        interaction = build_interaction()
        interaction.user = SimpleNamespace(
            id=999,
            display_name="Mod",
            guild_permissions=SimpleNamespace(manage_channels=True),
        )

        await view.archive_channel(interaction)

        cog.archive_game_channel.assert_awaited_once_with(game)

    async def test_a_failed_move_says_so_and_leaves_the_button_alone(
        self,
    ) -> None:
        game = self.build_finished_game()
        cog = self.build_cog_with(game)
        cog.archive_game_channel = mock.AsyncMock(
            side_effect=discord.Forbidden(
                SimpleNamespace(status=403, reason="Forbidden"),
                "nope",
            ),
        )
        view = RematchView(cog, game.game_id)
        interaction = build_interaction()

        await view.archive_channel(interaction)

        self.assertIn(
            "could not archive",
            interaction.followup.send.await_args.args[0],
        )
        interaction.message.edit.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
