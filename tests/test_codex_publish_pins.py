"""
The old turns, imported from the pins (docs/pbd-site.md, step 6;
docs/design/pbd-site.md, "The old turns"): a pinned message read back
into the model's tokens -- a mention as its seat, a glyph and a hero as
their tokens -- and only the bot's own pins carrying the game's board by
its exact name; then, through `tests/codex_cog_fakes.py`, a game played
with the publisher off getting its finished turns from its channel's
pins, a rematch's earlier game's pins and a person's left out, the turns
the record already holds left alone, a channel that is gone marked done,
and a second start importing nothing.
"""

from __future__ import annotations

import io
import logging
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import mock

import discord

from codex.game import CodexGame, GameStatus
from codex_cog_fakes import BOT_USER, GAME_CHANNEL, fake_attachment
from cogs.codex_publish import keys, pins
from cogs.codex_publish.record import PublishRecord

import test_codex_publish_hooks as hooks


def seated() -> CodexGame:
    game = CodexGame("0123456789abcdef0123456789abcdef", 7, channel_id=GAME_CHANNEL)
    game.seats = [{"id": 101, "name": "basher"}, {"id": 202, "name": "fencer"}]
    return game


def pinned(content: str, filename: str = "codex-7-board.webp", author: int = BOT_USER):
    return SimpleNamespace(id=1, author=SimpleNamespace(id=author), content=content,
                           attachments=[SimpleNamespace(filename=filename)])


class ReadTests(unittest.TestCase):
    def test_a_mention_is_its_seat(self) -> None:
        self.assertEqual(pins.as_tokens("<@202> plays. <@!101> waits.", seated()),
                         "{to:2} plays. {to:1} waits.")

    def test_somebody_seated_nowhere_is_no_mention(self) -> None:
        self.assertEqual(pins.as_tokens("<@303> watches.", seated()), "@someone watches.")

    def test_the_glyphs_and_a_hero_are_their_tokens(self) -> None:
        text = ("<:gold:11>4 and <:codex_exhaust:12> <:target:13> <:codex:14> "
                "<:troq_bashar:15> **Troq Bashar** and <:party:16>")
        self.assertEqual(pins.as_tokens(text, seated()),
                         "{gold:4} and {exhaust} {target} {codex} {hero:troq_bashar} and :party:")

    def test_a_turn_is_its_heading_and_lines(self) -> None:
        turn = pins.read_turn(pinned("**Turn 3** -- <@101> (Bashing)\n*and 2 more*\n"
                                     "<@101> plays **Iron Man**.\n"),
                              seated(), BOT_USER)
        self.assertEqual((turn.turn, turn.heading), (3, "**Turn 3** -- {to:1} (Bashing)"))
        self.assertEqual(turn.lines, ["*and 2 more*", "{to:1} plays **Iron Man**."])
        self.assertEqual(turn.board.filename, "codex-7-board.webp")

    def test_only_the_bots_own_board_by_its_exact_name(self) -> None:
        text = "**Turn 3** -- <@101> (Bashing)"
        game = seated()
        self.assertIsNone(pins.read_turn(pinned(text, author=101), game, BOT_USER))
        # A rematch's earlier game in the same channel, and the prefix alone.
        self.assertIsNone(pins.read_turn(pinned(text, "codex-6-board.webp"), game, BOT_USER))
        self.assertIsNone(pins.read_turn(pinned(text, "codex-7-hand.webp"), game, BOT_USER))
        self.assertIsNone(pins.read_turn(pinned("A note."), game, BOT_USER))
        self.assertIsNotNone(pins.read_turn(pinned(text), game, BOT_USER))


class ImportTests(hooks.HooksTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        # Played with the site off, as every game before step 5.
        self.table.cog.publisher = None
        self.game = await self.table.started()
        await self.end_turn()
        await self.table.redrawn()

    def pinned_boards(self) -> list[str]:
        channel = self.table.game_channel
        return [keys.board_key(self.game.game_id, channel.pinned_message(message_id, None).attachments[0].body)
                for message_id in channel.pin_order if message_id in channel.pinned]

    def pin_listings(self) -> int:
        return sum(1 for kind, _, _ in self.table.game_channel.requests if kind == "pins")

    async def start(self, record=None):
        publisher = self.attach(record)
        await publisher.start()
        await publisher.drain()
        return publisher

    async def test_the_pins_become_the_history(self) -> None:
        await self.end_turn()
        await self.table.redrawn()
        with self.assertLogs("cogs.codex_publish.publisher", logging.INFO) as logged:
            await self.start()
        self.assertEqual([entry["turn"] for entry in self.published.history], [1, 2])
        self.assertEqual([entry["board"] for entry in self.published.history], self.pinned_boards())
        self.assertTrue(self.published.imported)
        self.assertEqual(self.published.turn, 3)
        for entry in self.published.history:
            self.assertTrue(entry["heading"].startswith(f"**Turn {entry['turn']}** -- {{to:"),
                            entry["heading"])
            self.assertIn(entry["board"], self.store.objects)
            self.assertFalse(any("<@" in line for line in entry["lines"]))
        # The mention is the seat's name on the web.
        stored = self.stored(keys.history_key(self.game.game_id))
        seats = [part for part in stored["turns"][0]["heading"] if "player" in part]
        self.assertEqual([part["name"] for part in seats], ["fencer"])
        live = self.stored(keys.live_key(self.game.game_id))
        self.assertEqual(live["history_version"], stored["version"])
        # One listing, two boards: three requests, said at INFO.
        self.assertEqual(self.pin_listings(), 1)
        self.assertTrue(any("2 old turns imported, 3 requests" in line for line in logged.output),
                        logged.output)

    async def test_other_pins_in_the_channel_are_left_out(self) -> None:
        heading = f"**Turn 1** -- <@{self.table.basher.id}> (Bashing)\nA line of another game's."
        board = discord.File(io.BytesIO(b"other"), filename="codex-99-board.webp")
        ours = discord.File(io.BytesIO(b"theirs"), filename=f"codex-{self.game.game_number}-board.webp")
        self.table.game_channel.foreign_pins = [
            # A rematch's earlier game, in the same channel.
            SimpleNamespace(id=9001, author=SimpleNamespace(id=BOT_USER), content=heading,
                            pinned_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
                            attachments=[fake_attachment(board)]),
            # Somebody's own pin, with the game's board's name.
            SimpleNamespace(id=9002, author=SimpleNamespace(id=self.table.basher.id), content=heading,
                            pinned_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
                            attachments=[fake_attachment(ours)]),
        ]
        await self.start()
        self.assertEqual([entry["board"] for entry in self.published.history], self.pinned_boards())
        self.assertFalse(any("another game" in line for entry in self.published.history
                             for line in entry["lines"]))

    async def test_the_turns_the_record_holds_are_left_alone(self) -> None:
        # The site went live during turn 2: its end is the record's.
        self.attach()
        await self.end_turn()
        await self.settled()
        (kept,) = self.published.history
        self.assertEqual(kept["turn"], 2)
        await self.publisher.close()
        await self.start(PublishRecord.load(self.record_file))
        self.assertEqual([entry["turn"] for entry in self.published.history], [1, 2])
        self.assertEqual(self.published.history[1], kept)
        self.assertEqual(self.published.history[0]["board"], self.pinned_boards()[0])

    async def test_a_channel_that_is_gone_is_marked_done(self) -> None:
        self.table.bot.get_channel.side_effect = lambda channel_id: None
        response = mock.MagicMock(status=404, reason="Not Found")
        self.table.bot.fetch_channel = mock.AsyncMock(
            side_effect=discord.NotFound(response, "Unknown Channel"))
        await self.start()
        self.assertTrue(self.published.imported)
        self.assertEqual(self.published.history, [])
        self.table.bot.fetch_channel.assert_awaited_once_with(GAME_CHANNEL)

    async def test_a_second_start_imports_nothing(self) -> None:
        await self.start()
        history = list(self.published.history)
        await self.publisher.close()
        await self.start(PublishRecord.load(self.record_file))
        self.assertEqual(self.published.history, history)
        self.assertEqual(self.pin_listings(), 1)

    async def test_a_failed_listing_is_tried_again(self) -> None:
        response = mock.MagicMock(status=500, reason="Server Error")

        def failing(**kwargs):
            raise discord.HTTPException(response, "down")

        with mock.patch.object(self.table.game_channel, "pins", side_effect=failing):
            await self.start()
        self.assertFalse(self.published.imported)
        await self.publisher.close()
        await self.start(PublishRecord.load(self.record_file))
        self.assertEqual([entry["turn"] for entry in self.published.history], [1])

    async def test_a_finished_game_keeps_its_last_turn_current(self) -> None:
        await self.table.cog.abandon_command.callback(self.table.cog,
                                                      self.table.interaction(self.table.fencer))
        await self.start()
        self.assertIs(self.game.status, GameStatus.ABANDONED)
        self.assertEqual([entry["turn"] for entry in self.published.history], [1])
        self.assertEqual(self.published.turn, 2)


if __name__ == "__main__":
    unittest.main()
