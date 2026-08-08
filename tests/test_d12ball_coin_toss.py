import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest import mock

import discord

from cogs.d12ball import D12Ball
from cogs.d12ball_helpers import (
    COIN_EMOJI_FALLBACK,
    COIN_EMOJI_NAMES,
    EXHAUST_EMOJI_FALLBACK,
    EXHAUSTED_EMOJI_FALLBACK,
    INJURED_EMOJI_FALLBACK,
    TEAM_EMOJI_FALLBACKS,
    TEAM_EMOJI_NAMES,
    build_setup_message,
    build_home_choice_message,
    format_coin_emoji,
    get_exhaust_emoji,
    get_exhausted_emoji,
    get_injured_emoji,
    get_team_emoji,
    load_coin_emojis,
    load_condition_emojis,
    load_team_emojis,
)
from cogs.d12ball_views import CoinFlipView, TeamSelectionView
from d12ball.game import (
    CoinFace,
    D12BallGame,
    Team,
)
from d12ball.components import (
    MatchState,
    TeamSide,
    Zone,
    load_basic_ruleset,
    load_player_catalog,
)


def build_game(player_2_id: int = 222) -> D12BallGame:
    return D12BallGame(
        game_id="test-game",
        game_number=1,
        guild_id=1,
        channel_id=2,
        message_id=None,
        player_1_id=111,
        player_2_id=player_2_id,
        player_1_name="Player One",
        player_2_name="Player Two",
        player_1_team=Team.PURPLE,
        player_2_team=Team.TEAL,
    )


class FakeBot:
    """
    Stands in for the bot, which only has to hand back application
    emoji or fail the way discord.py would.

    `emojis` is the *guild* emoji cache, as it is on discord.py's
    Client -- application emoji are not in it, and only
    fetch_application_emojis returns those.
    """

    def __init__(
        self,
        emojis: list = None,
        error: Exception = None,
        guild_emojis: list = None,
    ) -> None:
        self.application_emojis = emojis or []
        self.error = error
        self.emojis = guild_emojis or []

    async def fetch_application_emojis(self) -> list:
        if self.error is not None:
            raise self.error

        return self.application_emojis


# Real emoji ids, because discord.py only reads <:name:id> as a custom
# emoji when the id is a full-length snowflake.
FORTUNE_EMOJI_ID = 1532254775624601701
DOOM_EMOJI_ID = 1532254775624601702


class FakeCog:
    """
    Stands in for the cog when building a view: the games it knows
    about and the coin emoji it has resolved.
    """

    def __init__(self, game, coin_emojis: dict) -> None:
        self.games = {game.game_id: game}
        self.coin_emojis = coin_emojis


def build_coin_emojis() -> dict:
    return {
        CoinFace.FORTUNE: f"<:3_gold_fortune:{FORTUNE_EMOJI_ID}>",
        CoinFace.DOOM: f"<:3_gold_doom:{DOOM_EMOJI_ID}>",
    }


class D12BallCoinTossTests(unittest.TestCase):
    def test_test_game_allows_one_user_to_be_both_players(self) -> None:
        game = D12BallGame(
            game_id="test-game",
            game_number=1,
            guild_id=1,
            channel_id=2,
            message_id=None,
            player_1_id=111,
            player_2_id=111,
            test_game=True,
        )

        reloaded = D12BallGame.from_dict(
            json.loads(json.dumps(game.to_dict()))
        )

        self.assertTrue(reloaded.test_game)
        self.assertEqual(reloaded.player_1_id, reloaded.player_2_id)

    def test_regular_game_still_rejects_the_same_user_twice(self) -> None:
        with self.assertRaises(ValueError):
            D12BallGame(
                game_id="regular-game",
                game_number=1,
                guild_id=1,
                channel_id=2,
                message_id=None,
                player_1_id=111,
                player_2_id=111,
            )

    def test_test_game_setup_has_a_team_row_for_each_player(self) -> None:
        game = D12BallGame(
            game_id="test-game",
            game_number=1,
            guild_id=1,
            channel_id=2,
            message_id=None,
            player_1_id=111,
            player_2_id=111,
            player_1_name="Player 1",
            player_2_name="Player 2",
            test_game=True,
        )
        view = TeamSelectionView(FakeCog(game, {}), game.game_id)
        team_buttons = [
            item for item in view.children
            if item.custom_id and item.custom_id.startswith("d12ball:team:")
        ]

        self.assertEqual(len(team_buttons), 8)
        self.assertEqual({item.row for item in team_buttons}, {0, 1})
        self.assertEqual(
            {item.label.split(":", 1)[0] for item in team_buttons},
            {"Player 1", "Player 2"},
        )
        setup_message = build_setup_message(game)
        self.assertIn("**Player 1:** Player 1", setup_message)
        self.assertIn("**Player 2:** Player 2", setup_message)

    def test_test_game_user_controls_offense_and_defense(self) -> None:
        game = D12BallGame(
            game_id="test-game",
            game_number=1,
            guild_id=1,
            channel_id=2,
            message_id=None,
            player_1_id=111,
            player_2_id=111,
            test_game=True,
            home_player_number=1,
            visiting_player_number=2,
        )
        cog = object.__new__(D12Ball)

        for possession in TeamSide:
            with self.subTest(possession=possession):
                match = SimpleNamespace(
                    ball=SimpleNamespace(possession=possession)
                )
                self.assertTrue(
                    cog.user_controls_possession(111, game, match)
                )
                self.assertTrue(
                    cog.user_controls_defense(111, game, match)
                )

    def test_fortune_wins_the_toss_for_whoever_flipped(self) -> None:
        for flipping_player_number in (1, 2):
            with self.subTest(player=flipping_player_number):
                game = build_game()
                winner = game.resolve_coin_toss(
                    flipping_player_number,
                    CoinFace.FORTUNE,
                )

                self.assertEqual(winner, flipping_player_number)
                self.assertEqual(
                    game.coin_winner_player_number,
                    flipping_player_number,
                )

    def test_doom_loses_the_toss_for_whoever_flipped(self) -> None:
        for flipping_player_number, opponent in ((1, 2), (2, 1)):
            with self.subTest(player=flipping_player_number):
                game = build_game()
                winner = game.resolve_coin_toss(
                    flipping_player_number,
                    CoinFace.DOOM,
                )

                self.assertEqual(winner, opponent)
                self.assertEqual(
                    game.coin_winner_player_number,
                    opponent,
                )

    def test_doom_hands_a_solo_game_to_the_ai(self) -> None:
        game = build_game(player_2_id=None)

        self.assertEqual(
            game.resolve_coin_toss(1, CoinFace.DOOM),
            2,
        )

    def test_the_toss_records_the_face_and_the_flipper(self) -> None:
        game = build_game()
        game.resolve_coin_toss(2, CoinFace.FORTUNE)

        self.assertTrue(game.coin_flipped)
        self.assertEqual(game.coin_face, CoinFace.FORTUNE)
        self.assertEqual(game.coin_flipped_by_player_number, 2)

    def test_flipping_twice_is_rejected(self) -> None:
        game = build_game()
        game.resolve_coin_toss(1, CoinFace.FORTUNE)

        with self.assertRaises(ValueError):
            game.resolve_coin_toss(2, CoinFace.DOOM)

    def test_the_flipper_must_be_a_player_number(self) -> None:
        game = build_game()

        with self.assertRaises(ValueError):
            game.resolve_coin_toss(3, CoinFace.FORTUNE)

        self.assertFalse(game.coin_flipped)

    def test_a_finished_toss_survives_a_save_and_reload(self) -> None:
        game = build_game()
        game.resolve_coin_toss(2, CoinFace.DOOM)

        saved = json.loads(json.dumps(game.to_dict()))
        self.assertEqual(saved["coin_face"], "doom")

        reloaded = D12BallGame.from_dict(saved)
        self.assertEqual(reloaded.coin_face, CoinFace.DOOM)
        self.assertEqual(reloaded.coin_flipped_by_player_number, 2)
        self.assertEqual(reloaded.coin_winner_player_number, 1)

    def test_games_saved_before_coin_faces_still_load(self) -> None:
        game = build_game()
        saved = game.to_dict()
        del saved["coin_face"]
        del saved["coin_flipped_by_player_number"]
        saved["coin_flipped"] = True
        saved["coin_winner_player_number"] = 1

        reloaded = D12BallGame.from_dict(saved)

        self.assertIsNone(reloaded.coin_face)
        self.assertIsNone(reloaded.coin_flipped_by_player_number)
        self.assertEqual(reloaded.coin_winner_player_number, 1)


class D12BallRunBackAnnouncementTests(unittest.IsolatedAsyncioTestCase):
    """
    Which turnovers announce a run back, which reset to the coach's own
    arrangement instead, and which do neither. A real MatchState rather
    than a stub: begin_run_back now moves meeples about, and what it
    says depends on who ends up displaced.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    def build_stubs(self, may_declare: bool, displace: bool = True):
        cog = object.__new__(D12Ball)
        cog.games = {}
        cog.player_catalog = self.catalog
        cog.team_emojis = {}
        cog.condition_emojis = {}
        cog.continue_run_back = mock.AsyncMock()
        cog.begin_substitution_window = mock.AsyncMock()
        cog.end_period = mock.AsyncMock()
        cog.finish_maneuver_resolution = mock.AsyncMock()
        cog.refresh_match_image = mock.AsyncMock()
        interaction = SimpleNamespace(
            followup=SimpleNamespace(send=mock.AsyncMock())
        )
        game = SimpleNamespace(match_state=None, game_id="g")
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
        )
        if displace:
            # Drag a home player out of their zone, so there is a real
            # run back to announce (and a real reset to undo).
            stray = match.home.zones[Zone.HOME_GOAL][0]
            match.board.place_meeple(stray, Zone.MIDFIELD, 0)
        if not may_declare:
            match.declared_substitution.add(TeamSide.HOME.value)
        return cog, interaction, game, match

    async def test_a_steal_explains_choices_cost_and_speed(self) -> None:
        # The run-back explainer belongs to steals: that is the only
        # turnover that still sends players scrambling back at a token
        # a space.
        cog, interaction, game, match = self.build_stubs(may_declare=True)

        with mock.patch("cogs.d12ball.save_games"):
            await cog.begin_run_back(
                interaction,
                game,
                match,
                distance_moved=3,
                turnover_occurred=True,
            )

        announcement = interaction.followup.send.await_args.args[0]
        self.assertIn("# Players run back!", announcement)
        self.assertIn("assigned zone", announcement)
        self.assertIn("1 exhaustion token for every space", announcement)
        self.assertIn("prompted to pick a location", announcement)
        self.assertIn("ball speed goes down to **1**", announcement)
        cog.continue_run_back.assert_awaited_once_with(
            interaction, game, match,
        )
        cog.begin_substitution_window.assert_not_awaited()

    async def test_a_new_play_resets_first_then_offers_the_window(
        self,
    ) -> None:
        cog, interaction, game, match = self.build_stubs(may_declare=True)
        stray = match.home.zones[Zone.HOME_GOAL][0]
        home_zone, home_space = match.assigned_positions[stray]
        self.assertEqual(
            match.board.meeple_position(stray), (Zone.MIDFIELD, 0),
        )

        with mock.patch("cogs.d12ball.save_games"):
            await cog.begin_run_back(
                interaction, game, match,
                turnover_occurred=True, new_play=True,
            )

        # The reset comes first, so a coach who declares rearranges
        # from their own formation rather than from wherever open play
        # left them.
        announcement = interaction.followup.send.await_args.args[0]
        self.assertIn("# New play", announcement)
        self.assertEqual(
            match.board.meeple_position(stray),
            (Zone(home_zone), home_space),
        )
        self.assertEqual(match.exhaustion.get(stray, 0), 0)

        cog.begin_substitution_window.assert_awaited_once()
        self.assertEqual(
            cog.begin_substitution_window.await_args.args[3],
            TeamSide.HOME,
        )
        cog.continue_run_back.assert_not_awaited()
        self.assertTrue(match.pending_run_back)

    async def test_a_new_play_without_a_window_still_resets(self) -> None:
        # Passing on the window is not what triggers the reset -- a
        # side with no declaration left never sees a window at all, and
        # still comes back to the arrangement its coach set, free.
        cog, interaction, game, match = self.build_stubs(may_declare=False)
        stray = match.home.zones[Zone.HOME_GOAL][0]
        home_zone, home_space = match.assigned_positions[stray]

        with mock.patch("cogs.d12ball.save_games"):
            await cog.begin_run_back(
                interaction, game, match,
                turnover_occurred=True, new_play=True,
            )

        self.assertEqual(
            match.board.meeple_position(stray),
            (Zone(home_zone), home_space),
        )
        self.assertEqual(match.exhaustion.get(stray, 0), 0)
        cog.begin_substitution_window.assert_not_awaited()

        # Nobody is displaced after a reset, so there is no run back to
        # head -- only the speed note is left to say.
        texts = [
            call.args[0]
            for call in interaction.followup.send.await_args_list
        ]
        self.assertNotIn(
            "# Players run back!", "\n".join(texts),
        )
        self.assertIn("ball speed goes down to **1**", texts[-1])
        cog.continue_run_back.assert_awaited_once()

    async def test_a_steal_runs_back_without_a_window(self) -> None:
        # A steal is a turnover but not a new play: the ball never went
        # dead, so nobody gets to substitute and the run back starts
        # immediately, even though the winning side still holds its
        # declaration.
        cog, interaction, game, match = self.build_stubs(may_declare=True)

        with mock.patch("cogs.d12ball.save_games"):
            await cog.begin_run_back(
                interaction, game, match, turnover_occurred=True,
            )

        cog.begin_substitution_window.assert_not_awaited()
        cog.continue_run_back.assert_awaited_once_with(
            interaction, game, match,
        )
        self.assertTrue(match.pending_run_back)

    async def test_a_maneuver_without_a_turnover_runs_nobody_back(
        self,
    ) -> None:
        # Run backs belong to turnovers. Keeping the ball leaves
        # whoever is out of position where they are, at no exhaustion
        # cost, and goes straight on to the clock.
        cog, interaction, game, match = self.build_stubs(may_declare=True)

        with mock.patch("cogs.d12ball.save_games"):
            await cog.begin_run_back(
                interaction, game, match,
                distance_moved=3, turnover_occurred=False,
            )

        cog.begin_substitution_window.assert_not_awaited()
        cog.continue_run_back.assert_not_awaited()
        interaction.followup.send.assert_not_awaited()
        self.assertFalse(match.pending_run_back)
        cog.finish_maneuver_resolution.assert_awaited_once_with(
            interaction,
            game,
            match,
            distance_moved=3,
            turnover_occurred=False,
            lead_in="",
        )

    async def test_a_turnover_during_last_possession_ends_the_period(
        self,
    ) -> None:
        # No run-back, no substitution window, no steal-intercept
        # speed-choice follow-up -- possession lost while last
        # possession is already in force ends the half immediately.
        cog, interaction, game, match = self.build_stubs(may_declare=True)
        match.scoreboard.last_possession = True

        with mock.patch("cogs.d12ball.save_games"):
            await cog.begin_run_back(
                interaction,
                game,
                match,
                turnover_occurred=True,
                new_play=True,
                speed_choice_after=True,
            )

        cog.end_period.assert_awaited_once_with(
            interaction, game, match, lead_in="",
        )
        cog.begin_substitution_window.assert_not_awaited()
        cog.continue_run_back.assert_not_awaited()
        self.assertFalse(match.pending_run_back)

    async def test_a_non_turnover_during_last_possession_plays_on(
        self,
    ) -> None:
        # Recovering a loose ball uncontested isn't losing possession,
        # so play continues normally even once last possession has
        # been declared -- and, not being a turnover, it runs nobody
        # back on the way there.
        cog, interaction, game, match = self.build_stubs(may_declare=True)
        match.scoreboard.last_possession = True

        with mock.patch("cogs.d12ball.save_games"):
            await cog.begin_run_back(
                interaction, game, match, turnover_occurred=False,
            )

        cog.end_period.assert_not_awaited()
        cog.continue_run_back.assert_not_awaited()
        cog.finish_maneuver_resolution.assert_awaited_once()


class D12BallNewPlayKickoffTests(unittest.IsolatedAsyncioTestCase):
    """
    The kickoff space after a goal, decided *after* the new play's
    reset rather than at the restart. The reset moves everyone, so an
    answer taken at restart_after_goal time is stale by the time
    anything acts on it -- and getting this wrong leaves the kickoff
    space empty and the restart reading as a loose ball.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    async def run_goal_restart(self, match: MatchState):
        cog = object.__new__(D12Ball)
        cog.games = {}
        cog.player_catalog = self.catalog
        cog.team_emojis = {}
        cog.condition_emojis = {}
        cog.refresh_match_image = mock.AsyncMock()
        cog.finish_maneuver_resolution = mock.AsyncMock()
        interaction = SimpleNamespace(
            followup=SimpleNamespace(
                send=mock.AsyncMock(return_value=SimpleNamespace(id=1)),
            )
        )
        game = SimpleNamespace(
            match_state=None, game_id="g", turn_message_id=None,
            home_player_number=1, visiting_player_number=2,
            player_1_id=1, player_2_id=2, is_solo_game=False,
        )
        # Both sides out of declarations, so no window interrupts the
        # flow and the reset runs straight into the kickoff fill.
        match.declared_substitution.update(
            {TeamSide.HOME.value, TeamSide.VISITING.value}
        )
        game.match_state = match.to_dict()

        with mock.patch("cogs.d12ball.save_games"):
            await cog.begin_run_back(
                interaction, game, match,
                distance_moved=2, turnover_occurred=True, new_play=True,
            )
        return cog, interaction

    def build_match(self) -> MatchState:
        return MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
        )

    async def test_the_reset_pulling_a_player_off_it_still_fills_it(
        self,
    ) -> None:
        match = self.build_match()
        midfield = match.visiting.zones[Zone.MIDFIELD]
        # An arrangement with nobody on the kickoff space (the middle
        # of a 3-space midfield)...
        for player_id, space_index in zip(midfield, (0, 2)):
            match.board.place_meeple(player_id, Zone.MIDFIELD, space_index)
        match.set_assigned_positions(TeamSide.VISITING)
        # ...but open play has left one of them standing on it, which
        # is what made the old restart-time answer wrong.
        match.board.place_meeple(midfield[0], Zone.MIDFIELD, 1)

        match.restart_after_goal(TeamSide.VISITING)
        await self.run_goal_restart(match)

        self.assertNotEqual(match.eligible_ball_handlers(), [])
        self.assertFalse(match.pending_kickoff_fill)

    async def test_an_arrangement_that_covers_it_costs_nobody_anything(
        self,
    ) -> None:
        match = self.build_match()
        midfield = match.visiting.zones[Zone.MIDFIELD]
        for player_id, space_index in zip(midfield, (1, 2)):
            match.board.place_meeple(player_id, Zone.MIDFIELD, space_index)
        match.set_assigned_positions(TeamSide.VISITING)
        match.board.place_meeple(midfield[0], Zone.HOME_GOAL, 0)

        match.restart_after_goal(TeamSide.VISITING)
        await self.run_goal_restart(match)

        # The reset put them back on the kickoff space, so the fill
        # settles for nothing rather than moving anyone.
        self.assertNotEqual(match.eligible_ball_handlers(), [])
        self.assertFalse(match.pending_kickoff_fill)
        self.assertEqual(match.exhaustion, {})


class D12BallCoinEmojiTests(unittest.TestCase):
    def test_every_coin_face_has_an_emoji_name(self) -> None:
        self.assertEqual(set(COIN_EMOJI_NAMES), set(CoinFace))

    def test_the_names_match_the_uploaded_emoji(self) -> None:
        self.assertEqual(
            COIN_EMOJI_NAMES[CoinFace.FORTUNE],
            "3_gold_fortune",
        )
        self.assertEqual(
            COIN_EMOJI_NAMES[CoinFace.DOOM],
            "3_gold_doom",
        )

    def test_application_emoji_are_looked_up_by_name(self) -> None:
        bot = FakeBot(
            [
                discord.PartialEmoji(name="Exhaust", id=100),
                discord.PartialEmoji(
                    name="1_gold_fortune",
                    id=1532254775624601700,
                ),
                discord.PartialEmoji(
                    name="3_gold_fortune",
                    id=FORTUNE_EMOJI_ID,
                ),
                discord.PartialEmoji(
                    name="3_gold_doom",
                    id=DOOM_EMOJI_ID,
                ),
            ]
        )

        coin_emojis = asyncio.run(load_coin_emojis(bot))

        self.assertEqual(coin_emojis, build_coin_emojis())

    def test_an_application_without_the_emoji_is_not_an_error(self) -> None:
        coin_emojis = asyncio.run(load_coin_emojis(FakeBot([])))

        self.assertEqual(coin_emojis, {})

    def test_a_failed_lookup_is_not_an_error(self) -> None:
        bot = FakeBot(error=discord.DiscordException("no application id"))

        self.assertEqual(asyncio.run(load_coin_emojis(bot)), {})

    def test_coin_faces_use_the_application_emoji(self) -> None:
        coin_emojis = build_coin_emojis()

        self.assertEqual(
            format_coin_emoji(coin_emojis, CoinFace.FORTUNE),
            f"<:3_gold_fortune:{FORTUNE_EMOJI_ID}>",
        )
        self.assertEqual(
            format_coin_emoji(coin_emojis, CoinFace.DOOM),
            f"<:3_gold_doom:{DOOM_EMOJI_ID}>",
        )

    def test_a_missing_emoji_falls_back_to_a_plain_coin(self) -> None:
        only_doom = {CoinFace.DOOM: f"<:3_gold_doom:{DOOM_EMOJI_ID}>"}

        for coin_emojis in ({}, None, only_doom):
            with self.subTest(coin_emojis=coin_emojis):
                self.assertEqual(
                    format_coin_emoji(coin_emojis, CoinFace.FORTUNE),
                    COIN_EMOJI_FALLBACK,
                )

    def test_the_result_names_the_flipper_and_the_face(self) -> None:
        game = build_game()
        game.resolve_coin_toss(1, CoinFace.DOOM)

        message = build_home_choice_message(game)

        self.assertEqual(
            message.splitlines()[0],
            "Player One (Purple) flipped **Doom**!",
        )
        self.assertIn("**Player Two (Teal) wins the coin toss!**", message)

    def test_the_result_does_not_repeat_the_coin(self) -> None:
        # The coin is posted as a message of its own, so that Discord
        # renders it large. Repeating it here would show it twice.
        game = build_game()
        game.resolve_coin_toss(1, CoinFace.DOOM)

        message = build_home_choice_message(game)

        self.assertNotIn(COIN_EMOJI_FALLBACK, message)
        for coin_emoji in build_coin_emojis().values():
            self.assertNotIn(coin_emoji, message)

    def test_the_coin_message_is_only_the_coin(self) -> None:
        # What flip_coin posts on its own line-free message.
        coin_emojis = build_coin_emojis()

        self.assertEqual(
            format_coin_emoji(coin_emojis, CoinFace.DOOM),
            f"<:3_gold_doom:{DOOM_EMOJI_ID}>",
        )
        self.assertEqual(
            format_coin_emoji({}, CoinFace.DOOM),
            COIN_EMOJI_FALLBACK,
        )

    def test_the_flip_button_wears_the_fortune_coin(self) -> None:
        game = build_game()
        view = CoinFlipView(
            cog=FakeCog(game, build_coin_emojis()),
            game_id=game.game_id,
        )

        # The payload Discord receives: a name and id, not the raw
        # <:name:id> text.
        self.assertEqual(
            view.flip_button.to_component_dict()["emoji"],
            {"id": FORTUNE_EMOJI_ID, "name": "3_gold_fortune"},
        )

    def test_the_flip_button_falls_back_to_a_plain_coin(self) -> None:
        game = build_game()
        view = CoinFlipView(
            cog=FakeCog(game, {}),
            game_id=game.game_id,
        )

        self.assertEqual(
            view.flip_button.to_component_dict()["emoji"],
            {"id": None, "name": COIN_EMOJI_FALLBACK},
        )

    def test_a_game_without_a_recorded_face_still_reads(self) -> None:
        game = build_game()
        game.coin_flipped = True
        game.coin_winner_player_number = 1

        message = build_home_choice_message(game)

        self.assertIn("The coin has been flipped", message)
        self.assertIn("**Player One (Purple) wins the coin toss!**", message)


class D12BallConditionEmojiTests(unittest.TestCase):
    def test_application_emoji_are_looked_up_by_name(self) -> None:
        bot = FakeBot(
            [
                discord.PartialEmoji(name="exhaust", id=100),
                discord.PartialEmoji(name="exhausted", id=101),
                discord.PartialEmoji(
                    name="3_gold_fortune",
                    id=FORTUNE_EMOJI_ID,
                ),
            ]
        )

        condition_emojis = asyncio.run(load_condition_emojis(bot))

        self.assertEqual(
            condition_emojis,
            {"exhaust": "<:exhaust:100>", "exhausted": "<:exhausted:101>"},
        )

    def test_an_application_without_the_emoji_is_not_an_error(self) -> None:
        condition_emojis = asyncio.run(load_condition_emojis(FakeBot([])))

        self.assertEqual(condition_emojis, {})

    def test_a_failed_lookup_is_not_an_error(self) -> None:
        bot = FakeBot(error=discord.DiscordException("no application id"))

        self.assertEqual(asyncio.run(load_condition_emojis(bot)), {})

    def test_a_guild_emoji_stands_in_for_a_missing_upload(self) -> None:
        # The condition art is as often uploaded to a server by hand as
        # to the application, and either beats showing a stock emoji
        # next to a board that draws the condition as a picture.
        bot = FakeBot(
            [],
            guild_emojis=[discord.PartialEmoji(name="injured", id=104)],
        )

        condition_emojis = asyncio.run(load_condition_emojis(bot))

        self.assertEqual(condition_emojis, {"injured": "<:injured:104>"})

    def test_an_application_emoji_wins_over_a_guild_one(self) -> None:
        bot = FakeBot(
            [discord.PartialEmoji(name="injured", id=105)],
            guild_emojis=[discord.PartialEmoji(name="injured", id=104)],
        )

        condition_emojis = asyncio.run(load_condition_emojis(bot))

        self.assertEqual(condition_emojis["injured"], "<:injured:105>")

    def test_a_failed_lookup_still_reads_the_guild_emoji(self) -> None:
        bot = FakeBot(
            error=discord.DiscordException("no application id"),
            guild_emojis=[discord.PartialEmoji(name="injured", id=104)],
        )

        condition_emojis = asyncio.run(load_condition_emojis(bot))

        self.assertEqual(condition_emojis, {"injured": "<:injured:104>"})

    def test_missing_conditions_fall_back_to_a_plain_emoji(self) -> None:
        self.assertEqual(get_exhaust_emoji({}), EXHAUST_EMOJI_FALLBACK)
        self.assertEqual(get_exhausted_emoji({}), EXHAUSTED_EMOJI_FALLBACK)
        self.assertEqual(get_injured_emoji({}), INJURED_EMOJI_FALLBACK)

    def test_resolved_conditions_use_the_application_emoji(self) -> None:
        condition_emojis = {
            "exhaust": "<:exhaust:100>",
            "exhausted": "<:exhausted:101>",
            "injured": "<:injured:102>",
        }

        self.assertEqual(
            get_exhaust_emoji(condition_emojis), "<:exhaust:100>",
        )
        self.assertEqual(
            get_exhausted_emoji(condition_emojis), "<:exhausted:101>",
        )
        self.assertEqual(
            get_injured_emoji(condition_emojis), "<:injured:102>",
        )


class D12BallTeamEmojiTests(unittest.TestCase):
    def test_every_team_has_an_emoji_name(self) -> None:
        self.assertEqual(set(TEAM_EMOJI_NAMES), set(Team))

    def test_application_emoji_are_looked_up_by_name(self) -> None:
        # Regression test: these are uploaded via the Developer Portal's
        # "Emojis" tab, which makes them application emoji, not guild
        # emoji -- they must come from fetch_application_emojis(), not
        # from a guild's emoji cache. FakeBot only implements the
        # former, so this would fail if the lookup ever went back to
        # reading a guild emoji cache instead.
        bot = FakeBot(
            [
                discord.PartialEmoji(name="team_purple", id=100),
                discord.PartialEmoji(name="team_orange", id=101),
                discord.PartialEmoji(name="team_teal", id=102),
                discord.PartialEmoji(name="team_slime", id=103),
            ]
        )

        team_emojis = asyncio.run(load_team_emojis(bot))

        self.assertEqual(
            team_emojis,
            {
                Team.PURPLE: "<:team_purple:100>",
                Team.ORANGE: "<:team_orange:101>",
                Team.TEAL: "<:team_teal:102>",
                Team.SLIME: "<:team_slime:103>",
            },
        )

    def test_an_application_without_the_emoji_is_not_an_error(self) -> None:
        team_emojis = asyncio.run(load_team_emojis(FakeBot([])))

        self.assertEqual(team_emojis, {})

    def test_a_failed_lookup_is_not_an_error(self) -> None:
        bot = FakeBot(error=discord.DiscordException("no application id"))

        self.assertEqual(asyncio.run(load_team_emojis(bot)), {})

    def test_missing_teams_fall_back_to_a_colored_circle(self) -> None:
        for team in Team:
            with self.subTest(team=team):
                self.assertEqual(
                    get_team_emoji({}, team),
                    TEAM_EMOJI_FALLBACKS[team],
                )

    def test_resolved_teams_use_the_application_emoji(self) -> None:
        team_emojis = {Team.PURPLE: "<:team_purple:100>"}

        self.assertEqual(
            get_team_emoji(team_emojis, Team.PURPLE), "<:team_purple:100>",
        )


if __name__ == "__main__":
    unittest.main()
