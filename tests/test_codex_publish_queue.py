"""
The publisher's store and queue (docs/pbd-site.md, step 2): changes
coalesced into one upload, a failing store never raising and the next
change sending again, a board put once, the order of a game's puts, a
replaced board deleted and a history board kept, the lists' own queue
ending on the newer list, one ERROR for a run of failures, and the
publisher off without its variables or without boto3.
"""

import asyncio
import json
import logging
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from botkit.objectstore import MemoryStore
from codex import tokens
from codex.game import GameStatus
from codex_positions import new_game
from cogs.codex_publish import config, keys, queue as queue_module
from cogs.codex_publish.queue import PublishQueue
from cogs.codex_publish.record import PublishRecord

GAME_ID = "0123456789abcdef0123456789abcdef"
OTHER_ID = "fedcba9876543210fedcba9876543210"
QUEUE_LOG = "cogs.codex_publish.queue"


def staged(game_id=GAME_ID):
    _, game, _ = new_game()
    game.game_id = game_id
    game.status = GameStatus.PLAYING
    return game


class QueueTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.record_file = Path(folder.name) / "codex_pbd.json"
        self.record = PublishRecord(path=self.record_file)
        self.games = {GAME_ID: staged()}
        self.store = MemoryStore()
        self.queue = self.make_queue()

    def make_queue(self, **options):
        queue = PublishQueue(self.store, self.record, lambda: self.games, **options)
        self.addAsyncCleanup(queue.close)
        return queue

    def change(self, board=None, line=None, game_id=GAME_ID, queue=None):
        """What a hook does: the record changed, then the game named --
        with the board's bytes where it is the current one."""
        published = self.record.game(game_id)
        if board is not None:
            published.board = keys.board_key(game_id, board)
        if line is not None:
            published.lines.append(line)
        (queue or self.queue).game_changed(game_id, [board] if board is not None else [])

    def end_turn(self, ended_board, new_board):
        """What `roll_over` does: the turn's board kept in the history, the
        next turn's current."""
        published = self.record.game(GAME_ID)
        published.history.append({
            "turn": len(published.history) + 1, "heading": "", "lines": list(published.lines),
            "board": keys.board_key(GAME_ID, ended_board),
        })
        published.history_version += 1
        published.lines = []
        published.board = keys.board_key(GAME_ID, new_board)
        self.queue.game_changed(GAME_ID, [ended_board, new_board])

    def uploaded(self, game_id=GAME_ID):
        return self.record.games[game_id].uploaded


class GameQueueTests(QueueTestCase):
    async def test_three_changes_are_one_upload(self):
        self.change(b"one", "first")
        self.change(b"two", "second")
        self.change(b"three", "third")
        await self.queue.drain()
        self.assertEqual(self.store.puts(), [
            keys.board_key(GAME_ID, b"three"),
            keys.history_key(GAME_ID),
            keys.live_key(GAME_ID),
        ])
        self.assertEqual(self.uploaded(), [keys.board_key(GAME_ID, b"three")])
        live = json.loads(self.store.objects[keys.live_key(GAME_ID)].body)
        self.assertEqual(live["board"], keys.board_key(GAME_ID, b"three"))
        self.assertEqual(len(live["lines"]), 3)

    async def test_a_change_in_flight_is_sent_after_it(self):
        self.store.gate = asyncio.Event()
        self.change(b"one", "first")
        await asyncio.sleep(0)
        self.change(b"two", "second")
        self.change(b"three", "third")
        self.store.gate.set()
        await self.queue.drain()
        boards = [key for key in self.store.puts() if key.endswith(".webp")]
        self.assertEqual(boards, [keys.board_key(GAME_ID, b"one"), keys.board_key(GAME_ID, b"three")])
        self.assertEqual(self.store.puts().count(keys.live_key(GAME_ID)), 2)

    async def test_a_game_is_put_board_then_history_then_live(self):
        self.change(b"one")
        await self.queue.drain()
        self.store.calls.clear()
        self.end_turn(b"ended", b"next")
        await self.queue.drain()
        self.assertEqual(self.store.puts(), [
            keys.board_key(GAME_ID, b"next"),
            keys.board_key(GAME_ID, b"ended"),
            keys.history_key(GAME_ID),
            keys.live_key(GAME_ID),
        ])
        history = json.loads(self.store.objects[keys.history_key(GAME_ID)].body)
        self.assertEqual(history["version"], 1)
        self.assertEqual([turn["board"] for turn in history["turns"]], [keys.board_key(GAME_ID, b"ended")])

    def change_mapped(self, board):
        """A change whose board was handed over with its map."""
        published = self.record.game(GAME_ID)
        published.board = keys.board_key(GAME_ID, board)
        self.queue.game_changed(GAME_ID, [board], {self.map_key(board): b'{"regions":[]}'})

    @staticmethod
    def map_key(board):
        return keys.board_map_key(keys.board_key(GAME_ID, board))

    async def test_a_map_goes_up_after_its_board_and_before_the_json_naming_it(self):
        self.change_mapped(b"one")
        await self.queue.drain()
        self.assertEqual(self.store.puts(), [
            keys.board_key(GAME_ID, b"one"),
            self.map_key(b"one"),
            keys.history_key(GAME_ID),
            keys.live_key(GAME_ID),
        ])
        board_map = self.store.objects[self.map_key(b"one")]
        self.assertEqual((board_map.content_type, board_map.cache_control),
                         ("application/json; charset=utf-8", "public, max-age=31536000, immutable"))
        live = json.loads(self.store.objects[keys.live_key(GAME_ID)].body)
        self.assertEqual(live["board_map"], self.map_key(b"one"))

    async def test_a_board_with_no_map_names_none(self):
        self.change(b"one")
        await self.queue.drain()
        live = json.loads(self.store.objects[keys.live_key(GAME_ID)].body)
        self.assertIsNone(live["board_map"])

    async def test_a_failed_map_stops_the_json_and_is_sent_with_the_next_change(self):
        self.store.fail = lambda operation, key: key.endswith(".json")
        with self.assertLogs(QUEUE_LOG, logging.WARNING):
            self.change_mapped(b"one")
            await self.queue.drain()
        self.assertEqual(self.store.puts(), [keys.board_key(GAME_ID, b"one"), self.map_key(b"one")])
        self.store.fail = False
        self.change(line="next")
        await self.queue.drain()
        self.assertIn(self.map_key(b"one"), self.store.objects)
        live = json.loads(self.store.objects[keys.live_key(GAME_ID)].body)
        self.assertEqual(live["board_map"], self.map_key(b"one"))

    async def test_a_replaced_board_takes_its_map_with_it(self):
        self.change_mapped(b"one")
        await self.queue.drain()
        self.change_mapped(b"two")
        await self.queue.drain()
        self.assertEqual(sorted(self.store.deletes()),
                         sorted([keys.board_key(GAME_ID, b"one"), self.map_key(b"one")]))
        self.assertEqual(sorted(self.uploaded()),
                         sorted([keys.board_key(GAME_ID, b"two"), self.map_key(b"two")]))

    async def test_every_object_carries_its_type_and_cache(self):
        self.change(b"one")
        await self.queue.drain()
        board = self.store.objects[keys.board_key(GAME_ID, b"one")]
        self.assertEqual((board.content_type, board.cache_control),
                         ("image/webp", "public, max-age=31536000, immutable"))
        live = self.store.objects[keys.live_key(GAME_ID)]
        self.assertEqual((live.content_type, live.cache_control),
                         ("application/json; charset=utf-8", "no-cache"))

    async def test_a_board_is_not_uploaded_twice(self):
        self.change(b"one", "first")
        await self.queue.drain()
        self.change(b"one", "second")
        await self.queue.drain()
        self.assertEqual(self.store.puts().count(keys.board_key(GAME_ID, b"one")), 1)
        self.assertEqual(self.store.puts().count(keys.live_key(GAME_ID)), 2)

    async def test_a_restart_does_not_upload_a_board_the_record_says_is_up(self):
        self.change(b"one", "first")
        await self.queue.drain()
        self.record = PublishRecord.load(self.record_file)
        self.assertEqual(self.uploaded(), [keys.board_key(GAME_ID, b"one")])
        self.store.calls.clear()
        restarted = self.make_queue()
        self.change(b"one", "after the restart", queue=restarted)
        await restarted.drain()
        self.assertEqual(self.store.puts(), [keys.history_key(GAME_ID), keys.live_key(GAME_ID)])

    async def test_unchanged_json_is_not_put_again(self):
        self.change(b"one", "first")
        await self.queue.drain()
        self.store.calls.clear()
        self.queue.game_changed(GAME_ID)
        await self.queue.drain()
        self.assertEqual(self.store.calls, [])

    async def test_a_replaced_board_is_deleted_and_a_history_board_kept(self):
        self.change(b"one")
        await self.queue.drain()
        self.change(b"two")
        await self.queue.drain()
        self.assertEqual(self.store.deletes(), [keys.board_key(GAME_ID, b"one")])
        self.assertNotIn(keys.board_key(GAME_ID, b"one"), self.store.objects)
        # The delete waits for the live.json that stopped naming it.
        self.assertLess(self.store.calls.index(("put", keys.live_key(GAME_ID))),
                        self.store.calls.index(("delete", keys.board_key(GAME_ID, b"one"))))

        self.end_turn(b"two", b"three")
        await self.queue.drain()
        self.change(b"four")
        await self.queue.drain()
        self.assertEqual(self.store.deletes(), [
            keys.board_key(GAME_ID, b"one"),
            keys.board_key(GAME_ID, b"three"),
        ])
        self.assertIn(keys.board_key(GAME_ID, b"two"), self.store.objects)
        self.assertEqual(sorted(self.uploaded()),
                         sorted([keys.board_key(GAME_ID, b"two"), keys.board_key(GAME_ID, b"four")]))

    async def test_an_undo_back_to_a_deleted_board_puts_it_again(self):
        self.change(b"one")
        await self.queue.drain()
        self.change(b"two")
        await self.queue.drain()
        self.change(b"one")
        await self.queue.drain()
        self.assertEqual(self.store.puts().count(keys.board_key(GAME_ID, b"one")), 2)
        self.assertIn(keys.board_key(GAME_ID, b"one"), self.store.objects)

    async def test_a_failing_store_does_not_raise_and_the_next_change_sends_again(self):
        self.store.fail = True
        with self.assertLogs(QUEUE_LOG, logging.WARNING):
            self.change(b"one", "first")
            await self.queue.drain()
        self.assertEqual(self.store.objects, {})
        self.assertEqual(self.uploaded(), [])

        self.store.fail = False
        self.change(line="second")
        await self.queue.drain()
        self.assertEqual(set(self.store.objects), {
            keys.board_key(GAME_ID, b"one"), keys.history_key(GAME_ID), keys.live_key(GAME_ID),
        })
        self.assertEqual(self.uploaded(), [keys.board_key(GAME_ID, b"one")])

    async def test_a_failed_board_stops_the_json_that_would_name_it(self):
        self.store.fail = lambda operation, key: key.endswith(".webp")
        with self.assertLogs(QUEUE_LOG, logging.WARNING):
            self.change(b"one")
            await self.queue.drain()
        self.assertEqual(self.store.puts(), [keys.board_key(GAME_ID, b"one")])

    async def test_a_current_board_neither_up_nor_handed_over_waits(self):
        self.record.game(GAME_ID).board = keys.board_key(GAME_ID, b"one")
        with self.assertLogs(QUEUE_LOG, logging.WARNING):
            self.queue.game_changed(GAME_ID)
            await self.queue.drain()
        self.assertEqual(self.store.calls, [])
        self.change(b"one")
        await self.queue.drain()
        self.assertIn(keys.live_key(GAME_ID), self.store.objects)

    async def test_a_lobby_and_a_game_the_record_lacks_send_nothing(self):
        self.queue.game_changed(GAME_ID, [b"one"])
        await self.queue.drain()
        lobby = staged(OTHER_ID)
        lobby.status = GameStatus.LOBBY
        lobby.match_state = None
        self.games[OTHER_ID] = lobby
        self.change(b"one", game_id=OTHER_ID)
        await self.queue.drain()
        self.assertEqual(self.store.calls, [])

    async def test_the_record_is_saved_with_what_is_up(self):
        self.change(b"one")
        await self.queue.drain()
        saved = json.loads(self.record_file.read_text())
        self.assertEqual(saved[GAME_ID]["uploaded"], [keys.board_key(GAME_ID, b"one")])

    async def test_closed_it_takes_nothing(self):
        await self.queue.close()
        self.change(b"one")
        self.queue.lists_changed()
        await self.queue.drain()
        self.assertEqual(self.store.calls, [])


class ListQueueTests(QueueTestCase):
    def setUp(self):
        super().setUp()
        self.games[OTHER_ID] = staged(OTHER_ID)

    def listed(self, key):
        listed = json.loads(self.store.objects[key].body)
        sections = listed["finished"] + listed["abandoned"] if key == keys.ARCHIVE_KEY else listed["games"]
        return [entry["id"] for entry in sections]

    async def test_the_lists_are_built_from_the_games(self):
        self.games[OTHER_ID].status = GameStatus.FINISHED
        lobby = staged("00000000000000000000000000000000")
        lobby.status = GameStatus.LOBBY
        lobby.match_state = None
        self.games[lobby.game_id] = lobby
        self.queue.lists_changed()
        await self.queue.drain()
        self.assertEqual(self.listed(keys.INDEX_KEY), [GAME_ID])
        self.assertEqual(self.listed(keys.ARCHIVE_KEY), [OTHER_ID])

    async def test_two_games_changing_the_lists_end_with_the_newer(self):
        self.store.gate = asyncio.Event()
        self.queue.lists_changed()
        await asyncio.sleep(0)
        # While the first list is in flight, one game ends and the other
        # changes twice: one more send, with both lists as they are now.
        self.games[OTHER_ID].status = GameStatus.FINISHED
        self.queue.lists_changed()
        self.queue.lists_changed()
        self.store.gate.set()
        await self.queue.drain()
        self.assertEqual(self.store.puts().count(keys.INDEX_KEY), 2)
        self.assertEqual(self.listed(keys.INDEX_KEY), [GAME_ID])
        self.assertEqual(self.listed(keys.ARCHIVE_KEY), [OTHER_ID])

    async def test_a_dropped_game_is_deleted_after_the_lists(self):
        self.change(b"one", line="said")
        await self.queue.drain()
        board = keys.board_key(GAME_ID, b"one")
        self.assertIn(keys.live_key(GAME_ID), self.store.objects)
        del self.games[GAME_ID]
        self.record.drop(GAME_ID)
        self.store.fail = lambda operation, key: operation == "delete" and key == board
        self.queue.games_dropped({GAME_ID: [board]})
        await self.queue.drain()
        self.assertNotIn(keys.live_key(GAME_ID), self.store.objects)
        self.assertNotIn(keys.history_key(GAME_ID), self.store.objects)
        self.assertIn(board, self.store.objects)
        self.assertEqual(self.listed(keys.INDEX_KEY), [OTHER_ID])
        # The failed delete is tried again with the lists' next change.
        self.store.fail = False
        self.queue.lists_changed()
        await self.queue.drain()
        self.assertNotIn(board, self.store.objects)

    async def test_the_lists_are_not_on_a_games_queue(self):
        self.change(b"one")
        await self.queue.drain()
        self.assertNotIn(keys.INDEX_KEY, self.store.puts())
        self.assertNotIn(keys.ARCHIVE_KEY, self.store.puts())


class FailureRunTests(QueueTestCase):
    async def fail_times(self, count):
        for n in range(count):
            self.change(line=f"line {n}")
            await self.queue.drain()

    async def test_a_run_of_failures_is_one_error(self):
        self.store.fail = True
        with self.assertLogs(QUEUE_LOG, logging.WARNING) as logged:
            self.change(b"one")
            await self.queue.drain()
            await self.fail_times(queue_module.FAILURE_RUN + 5)
        errors = [record for record in logged.records if record.levelno == logging.ERROR]
        self.assertEqual(len(errors), 1)

    async def test_a_success_resets_the_run(self):
        self.store.fail = True
        with self.assertLogs(QUEUE_LOG, logging.WARNING) as logged:
            self.change(b"one")
            await self.queue.drain()
            await self.fail_times(queue_module.FAILURE_RUN)
            self.store.fail = False
            await self.fail_times(1)
            self.store.fail = True
            await self.fail_times(queue_module.FAILURE_RUN)
        errors = [record for record in logged.records if record.levelno == logging.ERROR]
        self.assertEqual(len(errors), 2)

    async def test_a_long_run_is_an_error_before_ten(self):
        now = [0.0]
        self.queue = self.make_queue(clock=lambda: now[0])
        self.store.fail = True
        with self.assertLogs(QUEUE_LOG, logging.WARNING) as logged:
            self.change(b"one")
            await self.queue.drain()
            now[0] = queue_module.FAILURE_WINDOW + 1
            await self.fail_times(1)
        errors = [record for record in logged.records if record.levelno == logging.ERROR]
        self.assertEqual(len(errors), 1)
        self.assertLess(len(logged.records), queue_module.FAILURE_RUN)


class ConfigTests(unittest.TestCase):
    CREDENTIALS = {
        config.ACCOUNT_ID: "account",
        config.ACCESS_KEY_ID: "key",
        config.SECRET_ACCESS_KEY: "secret",
    }

    def test_off_without_the_variables(self):
        with self.assertLogs(config.LOGGER, logging.INFO) as logged:
            self.assertIsNone(config.store_from_env({}))
        self.assertIn(config.SECRET_ACCESS_KEY, logged.output[0])

    def test_off_with_one_missing(self):
        partial = dict(self.CREDENTIALS, **{config.SECRET_ACCESS_KEY: " "})
        with self.assertLogs(config.LOGGER, logging.INFO):
            self.assertIsNone(config.store_from_env(partial))

    def test_off_without_boto3(self):
        with mock.patch.dict(sys.modules, {"boto3": None}), \
                self.assertLogs(config.LOGGER, logging.INFO) as logged:
            self.assertIsNone(config.store_from_env(self.CREDENTIALS))
        self.assertIn("boto3", logged.output[0])

    def test_on_with_the_variables(self):
        try:
            import boto3  # noqa: F401
        except ImportError:
            self.skipTest("boto3 is not installed")
        with self.assertLogs(config.LOGGER, logging.INFO):
            store = config.store_from_env(self.CREDENTIALS)
        self.assertEqual(store.bucket, config.DEFAULT_BUCKET)
        self.assertEqual(store._client.meta.endpoint_url, "https://account.r2.cloudflarestorage.com")
        with self.assertLogs(config.LOGGER, logging.INFO):
            named = config.store_from_env(dict(self.CREDENTIALS, **{config.BUCKET: "other"}))
        self.assertEqual(named.bucket, "other")


class KeyKindTests(unittest.TestCase):
    def test_each_kind_of_key_has_its_cache(self):
        self.assertEqual(keys.cache_control(keys.INDEX_KEY), "no-cache")
        self.assertEqual(keys.cache_control(keys.live_key(GAME_ID)), "no-cache")
        self.assertEqual(keys.cache_control(keys.board_key(GAME_ID, b"x")),
                         "public, max-age=31536000, immutable")
        self.assertEqual(keys.cache_control(keys.emoji_key("codex_gold")), "public, max-age=86400")
        self.assertEqual(keys.content_type(keys.emoji_key("codex_gold")), "image/png")
        self.assertEqual(keys.cache_control(keys.history_key(GAME_ID)), "no-cache")
        self.assertEqual(keys.cache_control(keys.board_map_key(keys.board_key(GAME_ID, b"x"))),
                         "public, max-age=31536000, immutable")
        self.assertEqual(keys.cache_control(keys.card_key("iron_man", ".jpg")), "public, max-age=86400")
        self.assertEqual(keys.content_type(keys.card_key("iron_man", ".jpg")), "image/jpeg")
        with self.assertRaises(ValueError):
            keys.cache_control("codex/anything.txt")


if __name__ == "__main__":
    unittest.main()
