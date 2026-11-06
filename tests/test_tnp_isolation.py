"""
Decision 2 of docs/tnp-bot.md, held: TNP is a cog in fool-bot, so an
exception in it stays in it. **A corrupt `data/tnp_games.json` leaves
`cogs.d12ball` loaded and its commands answering** -- the bot is built
with both extensions, in fool-bot's order, through `setup_hook`, every
games file pointed at a temporary folder (docs/design/tnp.md, "A cog in
fool-bot, not a bot of its own").
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import gamebot
from cogs.d12ball import core as d12ball_core
from gamesaves.d12ball import hub as d12ball_hub
from gamesaves.d12ball import storage as d12ball_storage
from gamesaves.tnp import storage as tnp_storage


def loaded_cogs() -> dict[str, object]:
    return {name: module for name, module in sys.modules.items() if name.startswith("cogs.")}


class CorruptTnpGamesTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_corrupt_tnp_games_file_leaves_d12ball_answering(self) -> None:
        imported = loaded_cogs()
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            corrupt = folder / "tnp_games.json"
            corrupt.write_text("{ this is not json", encoding="utf-8")
            bot = gamebot.GameBot(
                extensions=("cogs.d12ball", "cogs.tnp"),
                state_file=folder / "bot_state.json",
                sync_variable="FOOLBOT_COMMAND_SYNC",
                message_content=False,
            )
            with mock.patch.dict(sys.modules), \
                    mock.patch.object(gamebot.GameBot, "sync_commands_if_changed"), \
                    mock.patch.object(tnp_storage, "GAMES_FILE", corrupt), \
                    mock.patch.object(d12ball_storage, "GAMES_FILE", folder / "d12ball_games.json"), \
                    mock.patch.object(d12ball_hub, "HUBS_FILE", folder / "d12ball_hubs.json"), \
                    mock.patch.object(bot, "fetch_application_emojis", side_effect=RuntimeError("offline")), \
                    mock.patch.object(d12ball_core.CoreMixin, "prerender_maneuver_images"), \
                    self.assertLogs("gamesaves.tnp.storage", "ERROR"):
                await bot.setup_hook()
                d12ball = bot.get_cog("D12Ball")
                tnp = bot.get_cog("Tnp")
                self.assertIsNotNone(d12ball)
                self.assertIsNotNone(tnp)
                self.assertEqual(tnp.games, {})
                self.assertIsNotNone(bot.tree.get_command("d12ball"))

                # A D12 Ball command answers: a section of the rules,
                # read from the living rules document.
                rules = next(command for command in d12ball.walk_app_commands()
                             if command.name == "rules_search")
                fake = mock.MagicMock()
                fake.response.send_message = mock.AsyncMock()
                fake.followup.send = mock.AsyncMock()
                fake.response.is_done.return_value = False
                await rules.callback(d12ball, fake, "1")
                self.assertTrue(fake.response.send_message.await_count
                                + fake.followup.send.await_count)
                await bot.close()
            # The corrupt file is never written over (gamekit.storage).
            self.assertEqual(corrupt.read_text(encoding="utf-8"), "{ this is not json")
        self.assertEqual(set(loaded_cogs()), set(imported))
