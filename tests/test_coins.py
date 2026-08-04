import asyncio
import unittest
from types import SimpleNamespace
from unittest import mock

from cogs.coins import (
    COINS,
    CoinCommands,
    CoinFace,
    coin_flip_result,
    find_coin,
    load_coin_emojis,
)


class FakeBot:
    def __init__(self, emojis=None, error=None):
        self.emojis = emojis or []
        self.error = error

    async def fetch_application_emojis(self):
        if self.error is not None:
            raise self.error
        return self.emojis


class FakeEmoji:
    def __init__(self, name, rendered):
        self.name = name
        self.rendered = rendered

    def __str__(self):
        return self.rendered


class CoinsTests(unittest.TestCase):
    def test_all_six_coins_have_both_expected_emoji_names(self):
        names = {
            coin.emoji_name(face)
            for coin in COINS
            for face in CoinFace
        }

        self.assertEqual(len(COINS), 6)
        self.assertEqual(len(names), 12)
        self.assertIn("1_bronze_fortune", names)
        self.assertIn("3_gold_doom", names)

    def test_coin_keys_and_labels_cover_all_six_options(self):
        self.assertEqual(
            [coin.label for coin in COINS],
            [
                "1 Bronze",
                "1 Silver",
                "1 Gold",
                "3 Bronze",
                "3 Silver",
                "3 Gold",
            ],
        )
        self.assertEqual(
            [coin.key for coin in COINS],
            [
                "1_bronze",
                "1_silver",
                "1_gold",
                "3_bronze",
                "3_silver",
                "3_gold",
            ],
        )

    def test_find_coin_resolves_autocomplete_value(self):
        self.assertEqual(find_coin("3_silver"), COINS[4])
        self.assertIsNone(find_coin("2_gold"))

    def test_fortune_result_uses_win_text(self):
        self.assertEqual(
            coin_flip_result(CoinFace.FORTUNE),
            "You have won the coin toss!",
        )

    def test_doom_result_uses_loss_text(self):
        self.assertEqual(
            coin_flip_result(CoinFace.DOOM),
            "You have lost the coin toss.",
        )

    def test_load_coin_emojis_finds_all_matching_application_emojis(self):
        emojis = [
            FakeEmoji(
                "1_bronze_fortune",
                "<:1_bronze_fortune:1532254775624601701>",
            ),
            FakeEmoji("not_a_coin", "<:not_a_coin:1532254775624601702>"),
        ]

        result = asyncio.run(load_coin_emojis(FakeBot(emojis)))

        self.assertEqual(
            result,
            {
                "1_bronze_fortune":
                    "<:1_bronze_fortune:1532254775624601701>"
            },
        )

    def test_flip_with_selected_coin_sends_emoji_and_result_separately(self):
        coin_emojis = {
            "1_bronze_fortune":
                "<:1_bronze_fortune:1532254775624601701>"
        }
        cog = SimpleNamespace(
            coin_emojis=coin_emojis,
            ensure_coin_emojis=mock.AsyncMock(return_value=coin_emojis),
        )
        interaction = SimpleNamespace(
            response=SimpleNamespace(send_message=mock.AsyncMock()),
            followup=SimpleNamespace(send=mock.AsyncMock()),
        )

        with mock.patch("cogs.coins.random.choice", return_value=CoinFace.FORTUNE):
            asyncio.run(
                CoinCommands.flip.callback(cog, interaction, "1_bronze")
            )

        interaction.response.send_message.assert_awaited_once_with(
            "<:1_bronze_fortune:1532254775624601701>"
        )
        interaction.followup.send.assert_awaited_once_with(
            "You have won the coin toss!"
        )

    def test_flip_without_coin_randomly_selects_a_coin(self):
        coin_emojis = {
            "3_gold_doom": "<:3_gold_doom:1532254775624601702>"
        }
        cog = SimpleNamespace(
            coin_emojis=coin_emojis,
            ensure_coin_emojis=mock.AsyncMock(return_value=coin_emojis),
        )
        interaction = SimpleNamespace(
            response=SimpleNamespace(send_message=mock.AsyncMock()),
            followup=SimpleNamespace(send=mock.AsyncMock()),
        )

        with mock.patch(
            "cogs.coins.random.choice",
            side_effect=(COINS[-1], CoinFace.DOOM),
        ):
            asyncio.run(CoinCommands.flip.callback(cog, interaction, None))

        interaction.response.send_message.assert_awaited_once_with(
            "<:3_gold_doom:1532254775624601702>"
        )
        interaction.followup.send.assert_awaited_once_with(
            "You have lost the coin toss."
        )

    def test_autocomplete_offers_all_six_coins(self):
        choices = asyncio.run(
            CoinCommands.coin_autocomplete(
                SimpleNamespace(),
                SimpleNamespace(),
                "",
            )
        )

        self.assertEqual([choice.name for choice in choices], [
            "1 Bronze",
            "1 Silver",
            "1 Gold",
            "3 Bronze",
            "3 Silver",
            "3 Gold",
        ])


if __name__ == "__main__":
    unittest.main()
