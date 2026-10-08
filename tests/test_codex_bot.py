"""
The Codex bot as far as step 1 of docs/codex-bot.md takes it: the
shared bot class loading `cogs.codex`, `/codex card` and `/codex rules`,
the token resolver, and botlog naming the bot and reading `CODEX_*`.
"""

import os
import unittest
from pathlib import Path
from unittest import mock


import botlog
import gamebot
from botlog import settings
from cogs.codex import Codex
from cogs.codex.reference import MESSAGE_LIMIT, card_answer, keyword_answer
from cogs.codex_helpers import CodexTokens
from codex.cards import Card, catalog
from codex.rulings import keywords


def codex_bot() -> gamebot.GameBot:
    return gamebot.GameBot(
        extensions=("cogs.codex",),
        state_file=Path("/nonexistent/codex_bot_state.json"),
        sync_variable="CODEX_COMMAND_SYNC",
        message_content=False,
    )


class CodexBotLoadsTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_bot_loads_the_codex_cog_alone(self) -> None:
        bot = codex_bot()
        self.assertFalse(bot.intents.message_content)
        with mock.patch.object(gamebot.GameBot, "sync_commands_if_changed") as sync:
            await bot.setup_hook()
        sync.assert_awaited_once()
        group = bot.tree.get_command("codex")
        self.assertIsNotNone(group)
        self.assertLessEqual(len(group.description), 100)
        self.assertEqual(
            {command.name for command in group.commands},
            {"card", "rules", "lobby", "games", "board", "hand", "resume"},
        )
        self.assertEqual([command.name for command in bot.tree.get_commands()], ["codex"])
        await bot.close()

    def card_lookup(self) -> tuple[gamebot.GameBot, Codex, mock.Mock]:
        bot = codex_bot()
        cog = Codex(bot)
        cog.tokens.refresh = mock.AsyncMock()
        interaction = mock.Mock()
        interaction.response.send_message = mock.AsyncMock()
        interaction.followup.send = mock.AsyncMock()
        return bot, cog, interaction

    async def test_a_card_is_answered_with_its_picture_alone(self) -> None:
        bot, cog, interaction = self.card_lookup()
        await cog.card.callback(cog, interaction, "trojan duck")
        args, kwargs = interaction.response.send_message.call_args
        self.assertEqual(args, ())
        self.assertEqual(kwargs["file"].filename, "trojan_duck.jpg")
        interaction.followup.send.assert_not_called()
        await bot.close()

    async def test_the_text_and_the_rulings_go_under_the_picture(self) -> None:
        bot, cog, interaction = self.card_lookup()
        await cog.card.callback(cog, interaction, "trojan duck", text=True, rulings=True)
        args, kwargs = interaction.response.send_message.call_args
        self.assertEqual(args, ())
        self.assertEqual(kwargs["file"].filename, "trojan_duck.jpg")
        (words,), _ = interaction.followup.send.call_args
        self.assertTrue(words.startswith("**Trojan Duck**"))
        self.assertIn("**Rulings** (", words)
        self.assertTrue(words.endswith("<http://codexcarddb.com/card/trojan_duck>"))
        await bot.close()

    async def test_the_rulings_alone_go_under_the_picture(self) -> None:
        bot, cog, interaction = self.card_lookup()
        await cog.card.callback(cog, interaction, "trojan duck", rulings=True)
        (words,), _ = interaction.followup.send.call_args
        self.assertTrue(words.startswith("**Rulings** ("))
        self.assertNotIn("Cost 7", words)
        await bot.close()

    async def test_a_token_is_answered_with_its_face(self) -> None:
        bot, cog, interaction = self.card_lookup()
        await cog.card.callback(cog, interaction, "dancer")
        args, kwargs = interaction.response.send_message.call_args
        self.assertEqual(args, ())
        self.assertEqual(kwargs["file"].filename, "dancer.png")
        interaction.followup.send.assert_not_called()
        await bot.close()

    async def test_a_worker_card_is_its_face(self) -> None:
        bot, cog, interaction = self.card_lookup()
        await cog.card.callback(cog, interaction, "worker_x5")
        args, kwargs = interaction.response.send_message.call_args
        self.assertEqual(args, ())
        self.assertEqual(kwargs["file"].filename, "worker_x5.png")
        interaction.followup.send.assert_not_called()
        await bot.close()

    async def test_a_card_whose_picture_is_missing_is_its_text(self) -> None:
        bot, cog, interaction = self.card_lookup()
        nowhere = mock.PropertyMock(return_value=Path("/nonexistent/trojan_duck.jpg"))
        with mock.patch.object(Card, "picture", nowhere):
            await cog.card.callback(cog, interaction, "trojan duck")
        (words,), kwargs = interaction.response.send_message.call_args
        self.assertTrue(words.startswith("**Trojan Duck**"))
        self.assertNotIn("file", kwargs)
        interaction.followup.send.assert_not_called()
        await bot.close()

    async def test_an_unknown_card_is_refused_privately(self) -> None:
        bot = codex_bot()
        cog = Codex(bot)
        interaction = mock.Mock()
        interaction.response.send_message = mock.AsyncMock()
        await cog.card.callback(cog, interaction, "no such card")
        self.assertTrue(interaction.response.send_message.call_args.kwargs["ephemeral"])
        await bot.close()

    async def test_autocomplete_offers_slugs_by_name(self) -> None:
        bot = codex_bot()
        cog = Codex(bot)
        choices = await cog.card_autocomplete(mock.Mock(), "trojan")
        self.assertEqual([(choice.name, choice.value) for choice in choices], [("Trojan Duck", "trojan_duck")])
        choices = await cog.rules_autocomplete(mock.Mock(), "over")
        self.assertIn("overpower", [choice.value for choice in choices])
        await bot.close()


class CodexReferenceTests(unittest.TestCase):
    def test_the_card_answer(self) -> None:
        answer = card_answer("trojan_duck", text=True, rulings=True)
        self.assertIn("Cost 7 · 8/9", answer)
        self.assertIn("Tech III", answer)
        self.assertIn("*Sirlin, 2016-03-19*", answer)
        self.assertTrue(answer.endswith("<http://codexcarddb.com/card/trojan_duck>"))

    def test_the_answer_is_what_was_asked_for(self) -> None:
        self.assertIsNone(card_answer("trojan_duck", text=False, rulings=False))
        text = card_answer("trojan_duck", text=True, rulings=False)
        self.assertTrue(text.startswith("**Trojan Duck**"))
        self.assertNotIn("Rulings", text)
        self.assertTrue(text.endswith("<http://codexcarddb.com/card/trojan_duck>"))
        rulings = card_answer("trojan_duck", text=False, rulings=True)
        self.assertTrue(rulings.startswith("**Rulings** ("))
        self.assertNotIn("Cost 7", rulings)
        self.assertTrue(rulings.endswith("<http://codexcarddb.com/card/trojan_duck>"))

    def test_a_hero_answer_carries_its_three_bands(self) -> None:
        answer = card_answer("river_montoya", text=True, rulings=False)
        for band in ("**Level 1+** 2/3", "**Level 3+** 2/4", "**Level 5+** 3/4"):
            self.assertIn(band, answer)

    def test_the_keyword_answer_is_the_rulings(self) -> None:
        answer = keyword_answer("Overpower")
        self.assertIn("official rules", answer)
        self.assertIn("**Rulings** (6)", answer)
        self.assertIsNone(keyword_answer("no such keyword"))

    def test_every_answer_fits_a_message_once_rendered(self) -> None:
        long_emoji = lambda text: text.replace("{", "<:emoji_named_long:123456789012345678>{")  # noqa: E731
        everything = catalog()
        for slug in [*everything.cards, *everything.heroes]:
            answer = card_answer(slug, long_emoji, text=True, rulings=True)
            self.assertLessEqual(len(answer), MESSAGE_LIMIT, slug)
        for entry in keywords():
            self.assertLessEqual(len(keyword_answer(entry.slug, long_emoji)), MESSAGE_LIMIT, entry.slug)


class CodexTokensTests(unittest.TestCase):
    def test_a_token_is_a_word_until_its_emoji_is_uploaded(self) -> None:
        resolver = CodexTokens(mock.Mock())
        line = "{exhaust} {arrow} Sideline it. {target} Costs {gold:1} less."
        self.assertEqual(resolver.render(line), "[exhaust] -> Sideline it. [target] Costs (1) less.")
        resolver.emojis = {"exhaust": "<:exhaust:1>", "gold": "<:gold:2>"}
        self.assertEqual(
            resolver.render(line), "<:exhaust:1> -> Sideline it. [target] Costs <:gold:2>1 less.",
        )


class BotlogNamesTheBotTests(unittest.TestCase):
    def tearDown(self) -> None:
        settings.configure()

    def test_codex_variables_fall_back_to_foolbots(self) -> None:
        settings.configure(prefix="CODEX", bot_name="Codex bot")
        environment = {"FOOLBOT_LOG_CHANNEL_ID": "42", "CODEX_LOG_LEVEL": "debug", "FOOLBOT_LOG_LEVEL": "warning"}
        with mock.patch.dict(os.environ, environment, clear=False):
            os.environ.pop("CODEX_LOG_CHANNEL_ID", None)
            self.assertEqual(settings.env("LOG_CHANNEL_ID"), "42")
            self.assertEqual(settings.env("LOG_LEVEL"), "debug")
            self.assertEqual(settings.variable("LOG_MIRROR"), "CODEX_LOG_MIRROR")

    def test_the_deploy_notice_names_the_bot(self) -> None:
        build = botlog.deploy_notice.Build(sha="a" * 40, short="aaaaaaa", subject="Codex step 1")
        message = botlog.deploy_notice.deploy_message(build, None, first_run=True, bot_name="Codex bot")
        self.assertTrue(message.startswith("**Codex bot restarted** -- now running"))

    def test_the_recovery_names_the_bot(self) -> None:
        reconnects = botlog.gateway.GatewayReconnectFilter(bot_name="Codex bot")
        reconnects._escalated = True
        reconnects._run_started = 0.0
        self.assertIn("**Back on Discord's gateway** (Codex bot)", reconnects.note_recovery())

    def test_the_state_file_is_the_one_configured(self) -> None:
        state_file = Path("/nonexistent/codex_bot_state.json")
        settings.configure(prefix="CODEX", bot_name="Codex bot", state_file=state_file)
        with mock.patch.object(botlog.deploy_notice.botstate, "read_key") as read_key:
            botlog.deploy_notice.last_announced()
        read_key.assert_called_once_with(botlog.deploy_notice.LAST_SHA_KEY, state_file)


if __name__ == "__main__":
    unittest.main()


class CommandIdsTests(unittest.IsolatedAsyncioTestCase):
    """`data/codex_command_ids.json`: written by the Codex bot after a
    sync, read by fool-bot's hub for `</codex lobby:ID>`."""

    async def test_a_sync_writes_the_ids_and_the_hub_mentions_the_lobby(self) -> None:
        import tempfile

        from cogs.d12ball_helpers import codex_lobby_mention

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "codex_command_ids.json"
            self.assertEqual(codex_lobby_mention(path), "`/codex lobby`")
            bot = codex_bot()
            bot.command_ids_file = path
            group, other = mock.Mock(id=1234), mock.Mock(id=99)
            group.name, other.name = "codex", "other"
            await bot.record_command_ids([group, other])
            self.assertEqual(gamebot.read_command_ids(path), {"codex": 1234, "other": 99})
            await bot.close()

    async def test_the_mention_carries_the_groups_id(self) -> None:
        import tempfile

        from cogs.d12ball_helpers import codex_lobby_mention

        command = mock.Mock(id=1234)
        command.name = "codex"
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "codex_command_ids.json"
            gamebot.write_command_ids([command], path)
            self.assertEqual(gamebot.read_command_ids(path), {"codex": 1234})
            self.assertEqual(codex_lobby_mention(path), "</codex lobby:1234>")

    async def test_a_skipped_sync_fetches_only_when_the_file_is_missing(self) -> None:
        import tempfile

        command = mock.Mock(id=7)
        command.name = "codex"
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "codex_command_ids.json"
            bot = codex_bot()
            bot.command_ids_file = path
            with mock.patch.object(bot.tree, "fetch_commands", mock.AsyncMock(return_value=[command])) as fetch:
                await bot.record_command_ids(None)
                await bot.record_command_ids(None)
            fetch.assert_awaited_once()
            self.assertEqual(gamebot.read_command_ids(path), {"codex": 7})
            await bot.close()

    def test_an_unreadable_file_reads_as_none(self) -> None:
        self.assertEqual(gamebot.read_command_ids(Path("/nonexistent/ids.json")), {})


class HubCodexButtonTests(unittest.IsolatedAsyncioTestCase):
    """fool-bot's hub carries a Codex button beside D12 Ball's. It cannot
    open a Codex lobby -- the Codex bot is another application -- so it
    answers privately with the command to send."""

    async def test_the_button_answers_privately_with_the_command(self) -> None:
        from cogs.d12ball_views import NewGameHubView

        cog = mock.MagicMock()
        cog.d12_button_emoji, cog.codex_emoji = None, None
        view = NewGameHubView(cog)
        self.assertEqual([item.label for item in view.children], ["D12 Ball", "Codex"])
        codex = view.children[1]
        self.assertEqual(codex.custom_id, "d12ball:hub:codex")
        interaction = mock.Mock()
        interaction.response.send_message = mock.AsyncMock()
        await codex.callback(interaction)
        (text,), kwargs = interaction.response.send_message.call_args
        self.assertTrue(kwargs["ephemeral"])
        self.assertIn("/codex lobby", text)

    def test_the_prompt_carries_the_mention_once_the_ids_are_written(self) -> None:
        import tempfile

        from cogs.d12ball_helpers import codex_lobby_prompt

        command = mock.Mock(id=1234)
        command.name = "codex"
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "codex_command_ids.json"
            self.assertIn("`/codex lobby`", codex_lobby_prompt(path))
            gamebot.write_command_ids([command], path)
            self.assertIn("</codex lobby:1234>", codex_lobby_prompt(path))
