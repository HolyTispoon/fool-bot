import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest import mock

import discord

from cogs.d12ball import (
    COIN_EMOJI_FALLBACK,
    COIN_EMOJI_NAMES,
    EXHAUST_EMOJI_FALLBACK,
    EXHAUSTED_EMOJI_FALLBACK,
    TEAM_EMOJI_FALLBACKS,
    TEAM_EMOJI_NAMES,
    CoinFlipView,
    D12Ball,
    TeamSelectionView,
    build_setup_message,
    build_home_choice_message,
    format_coin_emoji,
    get_exhaust_emoji,
    get_exhausted_emoji,
    get_team_emoji,
    load_coin_emojis,
    load_condition_emojis,
    load_team_emojis,
)
from d12ball.game import (
    CoinFace,
    D12BallGame,
    Team,
)
from d12ball.components import TeamSide


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
    """

    def __init__(self, emojis: list = None, error: Exception = None) -> None:
        self.emojis = emojis or []
        self.error = error

    async def fetch_application_emojis(self) -> list:
        if self.error is not None:
            raise self.error

        return self.emojis


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
    async def test_begin_run_back_explains_choices_cost_and_speed(self) -> None:
        cog = object.__new__(D12Ball)
        cog.games = {}
        cog.continue_run_back = mock.AsyncMock()
        interaction = SimpleNamespace(
            followup=SimpleNamespace(send=mock.AsyncMock())
        )
        game = SimpleNamespace(match_state=None)
        match = SimpleNamespace(
            ball=SimpleNamespace(speed=1),
            pending_run_back=False,
            pending_run_back_distance=1,
            pending_run_back_turnover=False,
            to_dict=lambda: {"pending_run_back": True},
        )

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

    def test_missing_conditions_fall_back_to_a_plain_emoji(self) -> None:
        self.assertEqual(get_exhaust_emoji({}), EXHAUST_EMOJI_FALLBACK)
        self.assertEqual(get_exhausted_emoji({}), EXHAUSTED_EMOJI_FALLBACK)

    def test_resolved_conditions_use_the_application_emoji(self) -> None:
        condition_emojis = {
            "exhaust": "<:exhaust:100>",
            "exhausted": "<:exhausted:101>",
        }

        self.assertEqual(
            get_exhaust_emoji(condition_emojis), "<:exhaust:100>",
        )
        self.assertEqual(
            get_exhausted_emoji(condition_emojis), "<:exhausted:101>",
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
