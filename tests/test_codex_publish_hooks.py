"""
The publisher's hooks in the Codex cog (docs/pbd-site.md, step 3;
docs/design/pbd-site.md, "The hooks"), through `tests/codex_cog_fakes.py`
and a `MemoryStore`: a whole game keeping one history entry per finished
turn with the board its pin carried; an undo to the previous turn
dropping one; a finished game and an abandoned one moving to the
archive, a lobby never listed; `/codex admin reset_channels` leaving
neither list; the turn's lines after a restart and `/codex resume`
added to the record's, not replacing them; the startup publish; the
publisher off where its variables are missing; and no Discord request
spent by it.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from botkit.objectstore import MemoryStore
from codex import history
from codex.game import GameStatus
from codex_cog_fakes import Table, user
from codex_positions import put
from cogs.codex_helpers import TOKEN_EMOJI
from cogs.codex_publish import keys
from cogs.codex_publish import record as record_module
from cogs.codex_publish.publisher import Publisher
from cogs.codex_publish.record import PublishRecord

import test_codex_cog_turn as turn_tests

CHANNEL_REQUESTS = turn_tests.CHANNEL_REQUESTS


def channel_requests(table: Table, mark: int) -> list[tuple[str, int]]:
    return [(kind, message_id) for kind, message_id, _ in table.game_channel.since(mark)
            if kind in CHANNEL_REQUESTS]


class HooksTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.record_file = Path(folder.name) / "codex_pbd.json"
        self.store = MemoryStore()
        self.ticks = itertools.count()
        self.table = Table()
        self.addCleanup(self.table.close)
        self.attach()

    def attach(self, record=None) -> Publisher:
        """A publisher on the table's cog, over the test's store and file."""
        publisher = Publisher(
            self.table.cog, self.store,
            record if record is not None else PublishRecord(path=self.record_file),
            clock=lambda: f"2026-10-16T00:00:{next(self.ticks):02d}+00:00",
        )
        self.table.cog.publisher = publisher
        self.addAsyncCleanup(publisher.close)
        return publisher

    async def restart(self) -> Publisher:
        """`Table.restart` -- the turn's lines gone from memory -- and a
        new publisher over the record as saved."""
        await self.publisher.drain()
        await self.publisher.close()
        self.table.restart()
        return self.attach(PublishRecord.load(self.record_file))

    @property
    def publisher(self) -> Publisher:
        return self.table.cog.publisher

    @property
    def published(self):
        return self.publisher.record.games[self.game.game_id]

    def stored(self, key: str):
        return json.loads(self.store.objects[key].body)

    async def settled(self) -> None:
        await self.table.redrawn()
        await self.publisher.drain()

    async def end_turn(self):
        _, view = await self.table.panel()
        view = (await self.table.press(view, "End main phase")).view()
        return await self.table.press(view, "Lock patrol")

    async def play_a_card(self):
        _, view = await self.table.panel()
        slug = next(row.slug for row in view.prompt.options.playable if row.allowed)
        return await self.table.press(view, ("play", slug))


class StartedTests(HooksTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.game = await self.table.started()
        await self.settled()

    async def test_start_lists_the_game_with_its_board_and_lines(self) -> None:
        index = self.stored(keys.INDEX_KEY)
        self.assertEqual([entry["id"] for entry in index["games"]], [self.game.game_id])
        live = self.stored(keys.live_key(self.game.game_id))
        self.assertEqual(live["turn"], 1)
        self.assertIn(live["board"], self.store.objects)
        board = await self.table.board_png(self.game)
        self.assertEqual(live["board"], keys.board_key(self.game.game_id, board))
        self.assertEqual(self.published.lines, self.table.cog.turn_lines[self.game.game_id])
        self.assertEqual(self.published.head, self.published.lines)

    async def test_an_action_publishes_its_lines_and_board(self) -> None:
        await self.play_a_card()
        await self.settled()
        self.assertEqual(self.published.lines, self.table.cog.turn_lines[self.game.game_id])
        board = await self.table.board_png(self.game)
        live = self.stored(keys.live_key(self.game.game_id))
        self.assertEqual(live["board"], keys.board_key(self.game.game_id, board))
        self.assertEqual(len(live["lines"]), len(self.published.lines))
        # The board the action replaced is gone; the record says what is up.
        boards = [key for key in self.store.objects if key.endswith(".webp")]
        self.assertEqual(boards, [live["board"]])

    async def test_the_publisher_spends_no_discord_request(self) -> None:
        """An action is the turn message's one edit, and a turn's end its
        last edit, its pin and the next one's post, as with it off."""
        message = self.game.turn_message_id
        mark = len(self.table.game_channel.requests)
        await self.play_a_card()
        await self.settled()
        self.assertEqual(channel_requests(self.table, mark), [("edit", message)])
        mark = len(self.table.game_channel.requests)
        await self.end_turn()
        await self.settled()
        self.assertEqual(channel_requests(self.table, mark),
                         [("edit", message), ("pin", message), ("send", self.game.turn_message_id)])

    async def test_show_board_moves_nothing_on_the_site(self) -> None:
        updated = self.published.updated
        await self.table.cog.show_board(self.table.interaction(self.table.active), self.game,
                                        self.table.match.active)
        await self.settled()
        self.assertEqual(self.published.updated, updated)

    async def test_a_board_drawn_for_an_older_change_is_not_current(self) -> None:
        """A drawing still under way when a post hands over a newer board:
        the posted board stays current."""
        gate = asyncio.Event()

        async def slow(game, match=None):
            await gate.wait()
            return b"older"

        self.table.cog.render_match_png = slow
        self.publisher.current(self.game)
        await asyncio.sleep(0)
        self.publisher.current(self.game, board=b"newer")
        gate.set()
        await self.publisher.drain()
        self.assertEqual(self.published.board, keys.board_key(self.game.game_id, b"newer"))

    async def test_a_turns_end_keeps_its_entry_with_the_pins_board(self) -> None:
        old = self.game.turn_message_id
        mark = len(self.table.game_channel.requests)
        await self.end_turn()
        await self.settled()
        pinned_edit = next(kwargs for kind, message_id, kwargs in self.table.game_channel.since(mark)
                           if kind == "edit" and message_id == old)
        (picture,) = pinned_edit["attachments"]
        (entry,) = self.published.history
        self.assertEqual(entry["turn"], 1)
        self.assertEqual(entry["board"], keys.board_key(self.game.game_id, picture.fp.getvalue()))
        self.assertTrue(entry["heading"].startswith("**Turn 1**"))
        stored = self.stored(keys.history_key(self.game.game_id))
        self.assertEqual([turn["turn"] for turn in stored["turns"]], [1])
        self.assertIn(entry["board"], self.store.objects)
        live = self.stored(keys.live_key(self.game.game_id))
        self.assertEqual((live["turn"], live["history_version"]), (2, stored["version"]))
        self.assertEqual(self.published.lines, self.table.cog.turn_lines[self.game.game_id])

    async def test_an_undo_to_the_previous_turn_drops_its_entry(self) -> None:
        first = self.table.active
        await self.end_turn()
        await self.settled()
        version = self.published.history_version
        _, view = await self.table.panel()
        view = (await self.table.press(view, "Undo")).view()
        asked = await self.table.press(view, "To the start of the previous turn")
        confirmation = self.table.game_channel.views[max(self.table.game_channel.views)]
        await self.table.press(confirmation, "Agree", who=first)
        await self.settled()
        self.assertTrue(asked.answers)
        self.assertEqual(self.table.match.turn, 1)
        self.assertEqual(self.published.history, [])
        self.assertEqual(self.published.history_version, version + 1)
        self.assertEqual(self.published.turn, 1)
        self.assertEqual(self.stored(keys.history_key(self.game.game_id))["turns"], [])
        self.assertTrue(self.published.lines[-1].endswith(history.UNDONE))

    async def test_a_finished_game_moves_to_the_archive(self) -> None:
        match = self.table.match
        seat = match.active
        match.player(self.table.cog.engine.opponents(match, seat)[0]).base_hp = 1
        attacker = put(match, seat, "older_brother")
        self.table.cog.service.persist(self.game, match)
        _, view = await self.table.panel()
        defending = (await turn_tests.TurnTestCase.attack(self, view, attacker.ref)).view()
        await self.table.press(defending, ("defend", "base"))
        await self.settled()
        self.assertIs(self.game.status, GameStatus.FINISHED)
        self.assertEqual(self.stored(keys.INDEX_KEY)["games"], [])
        (archived,) = self.stored(keys.ARCHIVE_KEY)["games"]
        self.assertEqual((archived["id"], archived["status"], archived["winner"]),
                         (self.game.game_id, "finished", [seat]))
        live = self.stored(keys.live_key(self.game.game_id))
        self.assertEqual(live["status"], "finished")
        self.assertIn(live["board"], self.store.objects)
        self.assertTrue(any("wins" in "".join(part.get("text", "") for part in line)
                            for line in live["lines"]))

    async def test_an_abandoned_game_moves_to_the_archive(self) -> None:
        await self.play_a_card()
        lines = list(self.table.cog.turn_lines[self.game.game_id])
        call = self.table.interaction(self.table.fencer)
        await self.table.cog.abandon_command.callback(self.table.cog, call)
        await self.settled()
        self.assertEqual(self.stored(keys.INDEX_KEY)["games"], [])
        (archived,) = self.stored(keys.ARCHIVE_KEY)["games"]
        self.assertEqual((archived["status"], archived["winner"]), ("abandoned", None))
        self.assertEqual(self.published.lines, lines)

    async def reset(self) -> None:
        self.table.guild.fetch_channels = mock.AsyncMock(return_value=[])
        cog = self.table.cog
        await cog.reset_channels.callback(cog, self.table.interaction(user(303, "helper", helper=True)),
                                          "confirm")
        await self.settled()
        self.assertEqual(cog.games, {})
        self.assertNotIn(self.game.game_id, self.publisher.record.games)
        self.assertEqual(self.stored(keys.INDEX_KEY)["games"], [])
        self.assertEqual(self.stored(keys.ARCHIVE_KEY)["games"], [])

    async def test_a_reset_takes_a_game_being_played_off_the_index(self) -> None:
        self.assertEqual(len(self.stored(keys.INDEX_KEY)["games"]), 1)
        await self.reset()

    async def test_a_reset_takes_an_abandoned_game_off_the_archive(self) -> None:
        await self.table.cog.abandon_command.callback(self.table.cog, self.table.interaction(self.table.fencer))
        await self.settled()
        self.assertEqual(len(self.stored(keys.ARCHIVE_KEY)["games"]), 1)
        await self.reset()

    async def test_an_action_after_a_restart_adds_to_the_records_lines(self) -> None:
        await self.play_a_card()
        await self.settled()
        before = list(self.published.lines)
        await self.restart()
        self.game = self.table.game
        await self.play_a_card()
        await self.settled()
        self.assertEqual(self.published.lines[:len(before)], before)
        self.assertGreater(len(self.published.lines), len(before))
        self.assertEqual(self.published.lines[len(before):], self.table.cog.turn_lines[self.game.game_id])

    async def test_resume_after_a_restart_keeps_the_records_lines(self) -> None:
        await self.play_a_card()
        await self.settled()
        before = list(self.published.lines)
        await self.restart()
        self.game = self.table.game
        await self.table.cog.resume.callback(self.table.cog, self.table.interaction(self.table.active))
        await self.settled()
        self.assertEqual(self.published.lines[:len(before)], before)
        self.assertEqual(self.published.lines[len(before):], self.table.cog.turn_lines[self.game.game_id])
        await self.play_a_card()
        await self.settled()
        self.assertEqual(self.published.lines[:len(before)], before)
        self.assertGreater(len(self.published.lines), len(before))

    async def test_an_undo_after_a_restart_goes_back_to_the_turns_head(self) -> None:
        head = list(self.published.head)
        await self.play_a_card()
        await self.settled()
        await self.restart()
        self.game = self.table.game
        _, view = await self.table.panel()
        view = (await self.table.press(view, "Undo")).view()
        await self.table.press(view, "To the start of my turn")
        await self.settled()
        self.assertEqual(self.published.lines, [*head, *self.table.cog.turn_lines[self.game.game_id]])
        self.assertTrue(self.published.lines[-1].endswith(history.UNDONE))

    async def test_a_turn_ended_by_resume_is_kept_from_the_record(self) -> None:
        """A turn whose end the bot owed at the restart: `/codex resume`
        runs it with no `roll_over`, so its entry is the record's."""
        await self.play_a_card()
        await self.settled()
        before = list(self.published.lines)
        board = self.published.board
        await self.restart()
        self.game = self.table.game
        match = self.table.match
        match.turn += 1
        self.table.cog.service.persist(self.game, match)
        self.publisher.current(self.game)
        await self.settled()
        (entry,) = self.published.history
        self.assertEqual((entry["turn"], entry["lines"], entry["board"]), (1, before, board))
        self.assertEqual(self.published.turn, 2)

    async def test_startup_draws_no_board_the_site_has(self) -> None:
        await self.restart()
        drawn = []
        board_png = self.table.cog.render_match_png

        async def counted(game, match=None):
            drawn.append(game.game_id)
            return await board_png(game, match)

        self.table.cog.render_match_png = counted
        await self.publisher.start()
        await self.settled()
        self.assertEqual(drawn, [])
        for name in set(TOKEN_EMOJI.values()):
            self.assertIn(keys.emoji_key(name), self.store.objects)
        self.assertEqual(len(self.stored(keys.INDEX_KEY)["games"]), 1)


class WholeGameTests(HooksTestCase):
    """A seeded whole game through the panels, under the turn tests'
    policy: one history entry per finished turn, each with the board its
    pinned message carries, and the game in the archive at the end."""

    policy = turn_tests.WholeGameTests.policy
    attack = turn_tests.TurnTestCase.attack
    assertNothingWentWrong = turn_tests.TurnTestCase.assertNothingWentWrong

    async def test_one_entry_per_finished_turn_with_the_pins_board(self) -> None:
        table = self.table
        self.game = await table.started()
        with mock.patch("cogs.codex_views.turn_message.render_hand", return_value=b"hand"), \
                mock.patch("cogs.codex.core.render_codex", return_value=b"codex"), \
                mock.patch("cogs.codex.core.render_hand", return_value=b"hand"):
            for _ in range(200):
                if table.match.winner is not None:
                    break
                _, view = await table.panel()
                while table.match.winner is None:
                    turn = table.match.turn
                    call = await self.policy(view)
                    self.assertNothingWentWrong(call)
                    if table.match.turn != turn:
                        picker = call.view()
                        if isinstance(picker, turn_tests.TechChoiceView) and table.match.winner is None:
                            await self.policy(picker)
                        break
                    view = call.view()
        await self.settled()
        self.assertIsNotNone(table.match.winner)

        # Every pinned turn's last edit carried its board; the last pin
        # is the final turn's, which is current on the site, not history.
        boards = {}
        for kind, message_id, kwargs in table.game_channel.requests:
            if kind == "edit" and kwargs.get("view", "unset") is None and kwargs.get("attachments"):
                boards[message_id] = kwargs["attachments"][0].fp.getvalue()
        pins = [message_id for kind, message_id, _ in table.game_channel.requests if kind == "pin"]
        expected = [keys.board_key(self.game.game_id, boards[message_id]) for message_id in pins]
        entries = self.published.history
        final = table.match.turn
        self.assertEqual([entry["turn"] for entry in entries], list(range(1, final)))
        self.assertEqual([entry["board"] for entry in entries], expected[:-1])
        self.assertEqual(self.published.board, expected[-1])
        for entry in entries:
            self.assertTrue(entry["heading"].startswith(f"**Turn {entry['turn']}**"), entry["heading"])
            self.assertIn(entry["board"], self.store.objects)
        stored = self.stored(keys.history_key(self.game.game_id))
        self.assertEqual(len(stored["turns"]), final - 1)
        self.assertEqual(self.stored(keys.INDEX_KEY)["games"], [])
        (archived,) = self.stored(keys.ARCHIVE_KEY)["games"]
        self.assertEqual(archived["winner"], [table.match.winner])
        # Only the boards something names are left in the bucket.
        named = {self.published.board, *(entry["board"] for entry in entries)}
        self.assertEqual({key for key in self.store.objects if key.endswith(".webp")}, named)


class StartupTests(HooksTestCase):
    async def test_a_game_that_ended_unseen_is_archived_with_its_board(self) -> None:
        """A game abandoned while the publisher was off is in the archive
        after the next start, with its last board."""
        self.table.cog.publisher = None
        game = await self.table.started()
        await self.table.cog.abandon_command.callback(self.table.cog, self.table.interaction(self.table.fencer))
        publisher = self.attach()
        await publisher.start()
        await publisher.drain()
        (archived,) = self.stored(keys.ARCHIVE_KEY)["games"]
        self.assertEqual(archived["id"], game.game_id)
        live = self.stored(keys.live_key(game.game_id))
        self.assertIn(live["board"], self.store.objects)

    async def test_a_lobby_abandoned_is_never_on_the_site(self) -> None:
        await self.table.cog.lobby.callback(self.table.cog, self.table.interaction(self.table.basher,
                                                                                   self.table.lobby_channel))
        call = self.table.interaction(user(303, "helper", helper=True))
        await self.table.cog.abandon_command.callback(self.table.cog, call)
        (game,) = self.table.cog.games.values()
        self.assertIs(game.status, GameStatus.ABANDONED)
        await self.publisher.drain()
        self.assertEqual(self.publisher.record.games, {})
        self.assertNotIn(keys.ARCHIVE_KEY, self.store.objects)


class TurnedOnTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.table = Table()
        self.addCleanup(self.table.close)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        patch = mock.patch.object(record_module, "PUBLISH_FILE", Path(folder.name) / "codex_pbd.json")
        patch.start()
        self.addCleanup(patch.stop)
        self.table.cog.preload_pictures = mock.AsyncMock()

    async def test_off_without_its_variables(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            await self.table.cog.cog_load()
        self.assertIsNone(self.table.cog.publisher)
        game = await self.table.started()
        self.assertIs(game.status, GameStatus.PLAYING)
        await self.table.cog.cog_unload()

    async def test_on_with_them(self) -> None:
        store = MemoryStore()
        variables = {"CODEX_PUBLISH_ACCOUNT_ID": "a", "CODEX_PUBLISH_ACCESS_KEY_ID": "b",
                     "CODEX_PUBLISH_SECRET_ACCESS_KEY": "c"}
        with mock.patch.dict(os.environ, variables, clear=True), \
                mock.patch("cogs.codex_publish.config.R2Store", return_value=store):
            await self.table.cog.cog_load()
        publisher = self.table.cog.publisher
        self.assertIsNotNone(publisher)
        await publisher.drain()
        self.assertIn(keys.emoji_key("gold"), store.objects)
        await self.table.cog.cog_unload()


if __name__ == "__main__":
    unittest.main()
