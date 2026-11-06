"""
The TNP cog as step 1 of docs/tnp-bot.md leaves it: loaded into a bot
through `setup_hook`, `/tnp unit` and `/tnp rules`, the rules document
read by section, and a cog whose data is missing loading anyway
(decision 2).
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

import gamebot
from cogs.tnp import UNAVAILABLE, Tnp
from tnp import rules_doc
from tnp.catalog import CatalogError, catalog
from tnp.formatting import unit_lines


def tnp_bot() -> gamebot.GameBot:
    return gamebot.GameBot(
        extensions=("cogs.tnp",),
        state_file=Path("/nonexistent/bot_state.json"),
        sync_variable="FOOLBOT_COMMAND_SYNC",
        message_content=False,
    )


def tnp_modules() -> dict[str, object]:
    return {name: module for name, module in sys.modules.items() if name.startswith("cogs.tnp")}


def interaction() -> mock.Mock:
    fake = mock.Mock()
    fake.response.send_message = mock.AsyncMock()
    fake.followup.send = mock.AsyncMock()
    return fake


class TnpCogLoadsTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_bot_loads_the_tnp_group(self) -> None:
        """Through `setup_hook`, with `sys.modules` put back after, as
        tests/test_codex_bot.py does (docs/design/testing.md)."""
        imported = tnp_modules()
        bot = tnp_bot()
        with mock.patch.dict(sys.modules), \
                mock.patch.object(gamebot.GameBot, "sync_commands_if_changed"):
            await bot.setup_hook()
            group = bot.tree.get_command("tnp")
            self.assertIsNotNone(group)
            self.assertLessEqual(len(group.description), 100)
            self.assertEqual({command.name for command in group.commands}, {"create_game", "resume", "unit", "rules"})
            for command in group.commands:
                self.assertLessEqual(len(command.description), 100)
            self.assertIsNotNone(bot.get_cog("Tnp").catalog)
            await bot.close()
        self.assertEqual(set(tnp_modules()), set(imported))

    async def test_missing_data_is_logged_and_never_raised(self) -> None:
        bot = tnp_bot()
        cog = Tnp(bot)
        with mock.patch("cogs.tnp.core.load", side_effect=CatalogError("humans.json: gone")), \
                self.assertLogs("cogs.tnp.core", "ERROR"):
            await cog.cog_load()
        self.assertIsNone(cog.catalog)
        fake = interaction()
        await cog.unit.callback(cog, fake, "tank")
        fake.response.send_message.assert_awaited_once_with(UNAVAILABLE, ephemeral=True)
        await bot.close()


class TnpReferenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.bot = tnp_bot()
        self.cog = Tnp(self.bot)
        await self.cog.cog_load()

    async def asyncTearDown(self) -> None:
        await self.bot.close()

    async def test_unit_tank_answers_with_its_d12_numbers(self) -> None:
        fake = interaction()
        await self.cog.unit.callback(self.cog, fake, "tank")
        text = fake.response.send_message.call_args.args[0]
        self.assertTrue(fake.response.send_message.call_args.kwargs["ephemeral"])
        self.assertIn("**Tank**", text)
        self.assertIn("Cost: 3 materials", text)
        self.assertIn("vs infantry Fair (6+)", text)
        self.assertIn("vs armored Strong (3+)", text)
        self.assertIn("vs air Poor (X", text)
        self.assertIn("Initiative: 3", text)
        self.assertIn("Supply: 6", text)
        self.assertIn("Factory", text)
        self.assertLessEqual(len(text), 2000)

    async def test_a_unit_asked_for_in_public_is_posted_for_everyone(self) -> None:
        fake = interaction()
        await self.cog.unit.callback(self.cog, fake, "Viper Spy Plane", public=True)
        self.assertFalse(fake.response.send_message.call_args.kwargs["ephemeral"])
        self.assertIn("Scouting 4", fake.response.send_message.call_args.args[0])

    async def test_an_unknown_unit_is_said_so(self) -> None:
        fake = interaction()
        await self.cog.unit.callback(self.cog, fake, "dragon")
        self.assertIn("No unit is called", fake.response.send_message.call_args.args[0])

    async def test_the_autocomplete_offers_units_by_name(self) -> None:
        choices = await self.cog.unit_autocomplete(interaction(), "ta")
        self.assertIn(("Tank", "tank"), [(c.name, c.value) for c in choices])

    async def test_rules_answers_a_section_by_number(self) -> None:
        fake = interaction()
        await self.cog.rules.callback(self.cog, fake, "6.7")
        text = fake.response.send_message.call_args.args[0]
        self.assertTrue(text.startswith("**TNP 6.7 Damage**"))

    async def test_rules_autocomplete_lists_sections(self) -> None:
        choices = await self.cog.rules_autocomplete(interaction(), "battle")
        self.assertIn("6", [choice.value for choice in choices])


class RulesDocTests(unittest.TestCase):
    def test_the_sections_are_numbered_once_each(self) -> None:
        numbers = [section.number for section in rules_doc.sections()]
        self.assertEqual(len(numbers), len(set(numbers)))
        for law in range(1, 9):
            self.assertIn(str(law), numbers)

    def test_every_section_fits_discord(self) -> None:
        for section in rules_doc.sections():
            for message in rules_doc.messages(section):
                self.assertLessEqual(len(message), rules_doc.MESSAGE_LIMIT, section.label)

    def test_a_table_is_a_code_block(self) -> None:
        text = "\n".join(rules_doc.messages(rules_doc.find("4.1")))
        self.assertIn("```", text)
        self.assertNotIn("| --- |", text)

    def test_find_by_title_and_by_label(self) -> None:
        self.assertEqual(rules_doc.find("TNP 2.4").title, "The player board")
        self.assertEqual(rules_doc.find("cleanup").number, "5.10")
        self.assertIsNone(rules_doc.find("no such thing"))

    def test_a_law_lists_its_sections(self) -> None:
        text = "\n".join(rules_doc.messages(rules_doc.find("6")))
        self.assertIn("- TNP 6.7 Damage", text)

    def test_every_unit_reads_in_one_message(self) -> None:
        for slug in catalog().units:
            self.assertLessEqual(len("\n".join(unit_lines(catalog(), slug))), 2000, slug)


if __name__ == "__main__":
    unittest.main()
