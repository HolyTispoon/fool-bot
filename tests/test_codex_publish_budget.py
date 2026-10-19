"""
Keeping the Codex games' bucket inside R2's free plan
(docs/design/pbd-site.md, "The free plan"): the meters -- the bucket's
size from one listing and every put and delete after it, the month's
writes counted and carried over a restart -- the report a start makes;
the order games come off the site in, the abandoned before the finished
and never one being played; and, through the cog, a game downloaded
whole before it is deleted, off both lists, a failed download leaving it
up, and a delete a restart interrupted finished.
"""

from __future__ import annotations

import json
import logging
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from botkit.objectstore import MemoryStore, list_pages
from codex.game import GameStatus
from cogs.codex_publish import budget, keys
from cogs.codex_publish.budget import Usage
from cogs.codex_publish.publisher import OFFLOAD_FOLDER_NAME, USAGE_FILE_NAME
from cogs.codex_publish.record import PublishedGame, PublishRecord

import test_codex_publish_hooks as hooks


def game(number: int, status: GameStatus) -> SimpleNamespace:
    return SimpleNamespace(game_id=f"{number:032x}", game_number=number, status=status,
                           match_state={})


class UsageTests(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / USAGE_FILE_NAME
        self.month = "2026-10"

    def usage(self) -> Usage:
        return Usage.load(self.path, month=lambda: self.month)

    def test_the_listing_then_every_put_and_delete_move_the_size(self) -> None:
        usage = self.usage()
        self.assertIsNone(usage.stored)
        usage.put("ignored", 5)
        usage.listed({"a": 10, "b": 20})
        usage.put("c", 5)
        usage.put("a", 15)
        usage.deleted("b")
        usage.deleted("never-there")
        self.assertEqual(usage.stored, 20)
        self.assertEqual(usage.stored, sum(usage.sizes.values()))

    def test_the_months_writes_survive_a_restart_and_not_the_month(self) -> None:
        usage = self.usage()
        usage.wrote(3)
        usage.save()
        self.assertEqual(self.usage().writes, 3)
        self.month = "2026-11"
        self.assertEqual(self.usage().writes, 0)
        usage.wrote()
        self.assertEqual((usage.month, usage.writes), ("2026-11", 1))

    def test_a_corrupt_file_counts_from_zero(self) -> None:
        self.path.write_text("[1, 2", encoding="utf-8")
        with self.assertLogs(budget.LOGGER, logging.WARNING):
            self.assertEqual(self.usage().writes, 0)

    def test_the_writes_alarm_once(self) -> None:
        usage = self.usage()
        with self.assertLogs(budget.LOGGER, logging.ERROR) as logged:
            usage.wrote(int(budget.WRITES_ALARM * budget.FREE_CLASS_A))
            usage.wrote()
        self.assertEqual(len(logged.records), 1)

    def test_over_from_the_mark_and_not_counting_what_is_leaving(self) -> None:
        usage = self.usage()
        mark = int(budget.OFFLOAD_AT * budget.FREE_STORAGE)
        usage.listed({"a": mark - 1})
        self.assertFalse(usage.over())
        usage.put("b", 1)
        self.assertTrue(usage.over())
        self.assertFalse(usage.over(leaving=1))

    def test_a_listing_is_a_write_a_thousand_keys(self) -> None:
        self.assertEqual([list_pages(count) for count in (0, 1, 1000, 1001)], [1, 1, 1, 2])

    def test_the_report_says_each_meter_against_the_free_plan(self) -> None:
        usage = self.usage()
        usage.listed({"a": 1_234_000_000, "b": 0})
        usage.wrote(12_345)
        text = budget.report(usage)
        self.assertIn("1.23 GB of the free 10.00 GB (12.3%).", text)
        self.assertIn("12,345 of the free 1,000,000.", text)
        self.assertIn("Reads (Class B): not counted here.", text)
        self.assertIn("not measured (the bucket could not be listed: down)",
                      budget.report(self.usage(), "down"))


class OrderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.record = PublishRecord()
        self.games = [
            game(1, GameStatus.FINISHED), game(2, GameStatus.ABANDONED), game(3, GameStatus.PLAYING),
            game(4, GameStatus.ABANDONED), game(5, GameStatus.FINISHED), game(6, GameStatus.LOBBY),
        ]
        for number, updated in ((1, "2026-10-03"), (2, "2026-10-05"), (4, "2026-10-01"), (5, None)):
            self.record.game(f"{number:032x}").updated = updated

    def numbers(self, games) -> list[int]:
        return [found.game_number for found in games]

    def test_abandoned_then_finished_the_longest_untouched_first(self) -> None:
        self.assertEqual(self.numbers(budget.offload_order(self.games, self.record)), [4, 2, 5, 1])

    def test_a_game_already_off_is_not_taken_again(self) -> None:
        self.record.game(f"{4:032x}").offloaded = True
        self.assertEqual(self.numbers(budget.offload_order(self.games, self.record)), [2, 5, 1])

    def test_the_plan_stops_at_the_target(self) -> None:
        sizes = {keys.live_key(f"{number:032x}"): 10 for number in (1, 2, 3, 4, 5)}
        sizes[keys.INDEX_KEY] = 1
        plan = budget.offload_plan(self.games, self.record, sizes, target=31)
        self.assertEqual(self.numbers(found for found, _ in plan), [4, 2])
        self.assertEqual(plan[0][1], [keys.live_key(f"{4:032x}")])

    def test_what_is_already_leaving_is_not_counted_again(self) -> None:
        sizes = {keys.live_key(f"{number:032x}"): 10 for number in (1, 2, 3, 4, 5)}
        self.record.game(f"{4:032x}").offloaded = True
        self.assertEqual(budget.leaving(self.record, sizes), 10)
        plan = budget.offload_plan(self.games, self.record, sizes, target=30)
        self.assertEqual(self.numbers(found for found, _ in plan), [2])

    def test_the_record_keeps_the_flag(self) -> None:
        entry = PublishedGame(offloaded=True)
        self.assertTrue(PublishedGame.from_dict(entry.to_dict()).offloaded)
        self.assertFalse(PublishedGame.from_dict({}).offloaded)


class OffloadTests(hooks.HooksTestCase):
    """A game played and abandoned with the site on; the publisher then
    restarted with the free storage shrunk under what the bucket holds."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        notice = mock.patch("botlog.post_notice", new=mock.AsyncMock(return_value=True))
        self.notices = notice.start()
        self.addCleanup(notice.stop)
        self.game = await self.table.started()
        await self.settled()
        await self.table.cog.abandon_command.callback(self.table.cog,
                                                      self.table.interaction(self.table.fencer))
        await self.settled()
        self.objects = {key: stored.body for key, stored in self.store.objects.items()
                        if key.startswith(keys.game_prefix(self.game.game_id))}
        self.assertTrue(self.objects)

    def shrunk(self, free: int):
        return mock.patch.object(budget, "FREE_STORAGE", free)

    async def started(self):
        publisher = await self.restart()
        await publisher.start()
        await publisher.drain()
        return publisher

    @property
    def folder(self) -> Path:
        return self.record_file.parent / OFFLOAD_FOLDER_NAME

    def notice_texts(self) -> list[str]:
        return [call.args[1] for call in self.notices.await_args_list]

    async def test_every_start_reports_against_the_free_plan(self) -> None:
        await self.started()
        (report,) = self.notice_texts()
        self.assertIn("of the free 10.00 GB", report)
        self.assertIn("of the free 1,000,000", report)
        self.assertEqual(self.publisher.usage.stored,
                         sum(len(stored.body) for stored in self.store.objects.values()))
        self.assertIn(("list", ""), self.store.calls)
        counted = json.loads((self.record_file.parent / USAGE_FILE_NAME).read_text())
        self.assertEqual(counted["class_a"], len(self.store.puts()) + 1)

    async def test_an_abandoned_game_is_downloaded_whole_then_deleted(self) -> None:
        with self.shrunk(1000):
            await self.started()
        for key, body in self.objects.items():
            self.assertEqual((self.folder / key).read_bytes(), body)
            self.assertNotIn(key, self.store.objects)
        self.assertTrue(self.published.offloaded)
        self.assertEqual(self.published.uploaded, [])
        self.assertEqual(self.stored(keys.ARCHIVE_KEY), {"finished": [], "abandoned": []})
        # The lists without it went up before anything of it was deleted.
        calls = self.store.calls
        last_archive = max(index for index, call in enumerate(calls) if call == ("put", keys.ARCHIVE_KEY))
        first_delete = min(index for index, (operation, key) in enumerate(calls)
                           if operation == "delete" and key in self.objects)
        self.assertLess(last_archive, first_delete)
        report, offloaded = self.notice_texts()
        self.assertIn("1 game(s) taken off", offloaded)
        self.assertIn(f"abandoned #{self.game.game_number}", offloaded)
        # A second start takes nothing more and puts nothing of it back.
        self.store.calls.clear()
        with self.shrunk(1000), self.assertLogs("cogs.codex_publish.publisher", logging.ERROR):
            await self.started()
        self.assertFalse(any(key in self.objects for _, key in self.store.calls))

    async def test_a_failed_download_leaves_the_game_on_the_site(self) -> None:
        self.store.fail = lambda operation, key: operation == "get"
        with self.shrunk(1000), self.assertLogs("cogs.codex_publish.publisher", logging.WARNING):
            await self.started()
        self.assertFalse(self.published.offloaded)
        for key in self.objects:
            self.assertIn(key, self.store.objects)
        self.assertFalse(self.folder.exists())
        (archived,) = self.stored(keys.ARCHIVE_KEY)["abandoned"]
        self.assertEqual(archived["id"], self.game.game_id)

    async def test_a_delete_a_restart_interrupted_is_finished(self) -> None:
        self.store.fail = lambda operation, key: operation == "delete" and key in self.objects
        with self.shrunk(1000), self.assertLogs("cogs.codex_publish.queue", logging.WARNING):
            await self.started()
        self.assertTrue(self.published.offloaded)
        self.assertTrue(all(key in self.store.objects for key in self.objects))
        self.store.fail = False
        await self.started()
        self.assertFalse(any(key in self.store.objects for key in self.objects))


class BeingPlayedTests(hooks.HooksTestCase):
    async def test_a_game_being_played_is_never_taken_off(self) -> None:
        notice = mock.patch("botlog.post_notice", new=mock.AsyncMock(return_value=True))
        notice.start()
        self.addCleanup(notice.stop)
        self.game = await self.table.started()
        await self.settled()
        publisher = await self.restart()
        with mock.patch.object(budget, "FREE_STORAGE", 1000), \
                self.assertLogs("cogs.codex_publish.publisher", logging.ERROR) as logged:
            await publisher.start()
            await publisher.drain()
        self.assertFalse(self.published.offloaded)
        self.assertIn(keys.live_key(self.game.game_id), self.store.objects)
        self.assertEqual(len(self.stored(keys.INDEX_KEY)["games"]), 1)
        self.assertIn("no finished or abandoned game is left", logged.output[-1])


if __name__ == "__main__":
    unittest.main()
