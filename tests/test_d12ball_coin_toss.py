import asyncio
import json
import unittest

import discord

from cogs.d12ball import (
    COIN_EMOJI_FALLBACK,
    COIN_EMOJI_NAMES,
    build_home_choice_message,
    format_coin_emoji,
    load_coin_emojis,
)
from d12ball.game import (
    CoinFace,
    D12BallGame,
    Team,
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
    """

    def __init__(self, emojis: list = None, error: Exception = None) -> None:
        self.emojis = emojis or []
        self.error = error

    async def fetch_application_emojis(self) -> list:
        if self.error is not None:
            raise self.error

        return self.emojis


def build_coin_emojis() -> dict:
    return {
        CoinFace.FORTUNE: "<:1_gold_fortune:101>",
        CoinFace.DOOM: "<:1_gold_doom:102>",
    }


class D12BallCoinTossTests(unittest.TestCase):
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


class D12BallCoinEmojiTests(unittest.TestCase):
    def test_every_coin_face_has_an_emoji_name(self) -> None:
        self.assertEqual(set(COIN_EMOJI_NAMES), set(CoinFace))

    def test_the_names_match_the_uploaded_emoji(self) -> None:
        self.assertEqual(
            COIN_EMOJI_NAMES[CoinFace.FORTUNE],
            "1_gold_fortune",
        )
        self.assertEqual(
            COIN_EMOJI_NAMES[CoinFace.DOOM],
            "1_gold_doom",
        )

    def test_application_emoji_are_looked_up_by_name(self) -> None:
        bot = FakeBot(
            [
                discord.PartialEmoji(name="Exhaust", id=100),
                discord.PartialEmoji(name="1_gold_fortune", id=101),
                discord.PartialEmoji(name="1_gold_doom", id=102),
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
            "<:1_gold_fortune:101>",
        )
        self.assertEqual(
            format_coin_emoji(coin_emojis, CoinFace.DOOM),
            "<:1_gold_doom:102>",
        )

    def test_a_missing_emoji_falls_back_to_a_plain_coin(self) -> None:
        for coin_emojis in ({}, None, {CoinFace.DOOM: "<:1_gold_doom:102>"}):
            with self.subTest(coin_emojis=coin_emojis):
                self.assertEqual(
                    format_coin_emoji(coin_emojis, CoinFace.FORTUNE),
                    COIN_EMOJI_FALLBACK,
                )

    def test_the_result_names_the_flipper_and_the_face(self) -> None:
        game = build_game()
        game.resolve_coin_toss(1, CoinFace.DOOM)

        message = build_home_choice_message(game, build_coin_emojis())

        self.assertIn("<:1_gold_doom:102>", message)
        self.assertIn("Player One (Purple) flipped **Doom**", message)
        self.assertIn("**Player Two (Teal) wins the coin toss!**", message)

    def test_the_result_reads_without_any_emoji(self) -> None:
        game = build_game()
        game.resolve_coin_toss(1, CoinFace.DOOM)

        message = build_home_choice_message(game)

        self.assertIn(COIN_EMOJI_FALLBACK, message)
        self.assertIn("Player One (Purple) flipped **Doom**", message)
        self.assertIn("**Player Two (Teal) wins the coin toss!**", message)

    def test_a_game_without_a_recorded_face_still_reads(self) -> None:
        game = build_game()
        game.coin_flipped = True
        game.coin_winner_player_number = 1

        message = build_home_choice_message(game, build_coin_emojis())

        self.assertIn("The coin has been flipped", message)
        self.assertIn("**Player One (Purple) wins the coin toss!**", message)


if __name__ == "__main__":
    unittest.main()
