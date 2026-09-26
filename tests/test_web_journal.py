"""
The web journal survives a restart (step 10 of docs/web-app-next.md):
`webapp/journal.py` writes every game's journal to its own file on
every add and reads it at start.

Every file here is in a temporary folder, and a `Journals` handed no
path writes nothing -- which is what every other web test gets -- so a
full run creates no `data/`.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

from gamelocks import GameLocks
from gamesaves.d12ball.service import GameResult
from webapp.journal import JOURNAL_LENGTH, Entry, Journal, Journals
from webapp.server import WebApp
from prompt_fixtures import ENGINE
from test_web_app import as_coach, case, service_over


#: A roll's numbers as the wire writes them -- the shape the journal
#: keeps and draws the dice from.
INJURY = {
    "shape": "injury",
    "player_id": "p1",
    "roll": 4,
    "safe": False,
    "overdrive": 0,
}


def reloaded(journal: Journal) -> Journal:
    """The journal as a restart finds it: through JSON and back."""
    return Journal.from_saved(json.loads(json.dumps(journal.saved())))


class JournalFileTests(unittest.TestCase):
    """What the file keeps, and what it drops."""

    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.path = self.folder / "d12ball_web_journal.json"

    def test_an_entry_keeps_its_words_snapshot_and_roll(self) -> None:
        journal = Journal()
        journal.entries.append(
            Entry(1, ("{team:purple} scores.",), board={"a": 1}, new_play=True),
        )
        journal.entries.append(Entry(2, ("Rolled.",), detail=dict(INJURY)))
        journal.next_id = 3
        journal.showing_roll = 2
        journal.showing_outcome = {
            "text": "GOAL!", "side": "home", "under": "{team:purple} scores.",
        }
        journal.board_version = 7

        back = reloaded(journal)

        self.assertEqual(
            [entry.saved() for entry in back.entries],
            [entry.saved() for entry in journal.entries],
        )
        # The tokens are kept as the model wrote them, and rendered at
        # the door as ever.
        self.assertEqual(back.entry(1).lines, ("{team:purple} scores.",))
        self.assertEqual(back.board_for(1), {"a": 1})
        self.assertEqual(back.entry(2).detail, INJURY)
        self.assertEqual(back.showing_roll, 2)
        # The headline up is still up after a restart, as the dice are.
        self.assertEqual(back.showing_outcome, journal.showing_outcome)
        self.assertEqual(back.next_id, 3)
        # A browser keeps a board by its URL, so the version goes on
        # counting rather than handing an old picture a new position.
        self.assertEqual(back.board_version, 7)

    def test_it_is_bounded_as_in_memory(self) -> None:
        journal = Journal()
        for number in range(1, JOURNAL_LENGTH + 11):
            journal.entries.append(Entry(number, (f"Line {number}.",)))
        journal.next_id = JOURNAL_LENGTH + 11
        saved = journal.saved()
        # A file written longer than the bound -- by hand, or by a
        # checkout with a longer one -- is read to the bound.
        saved["entries"] = [
            {**saved["entries"][0], "id": 0, "lines": ["Older."]},
            *saved["entries"],
        ]

        back = Journal.from_saved(saved)

        self.assertEqual(len(back.entries), JOURNAL_LENGTH)
        self.assertEqual(back.entries[-1].id, JOURNAL_LENGTH + 10)
        self.assertEqual(back.next_id, JOURNAL_LENGTH + 11)

    def test_a_roll_the_bound_dropped_is_no_longer_up(self) -> None:
        journal = Journal()
        journal.entries.append(Entry(5, ("Later.",)))
        journal.next_id = 6
        saved = journal.saved()
        saved["showing_roll"] = 2

        self.assertIsNone(Journal.from_saved(saved).showing_roll)

    def test_a_game_the_service_does_not_know_is_dropped(self) -> None:
        journals = Journals(self.path)
        journals.journal("kept").entries.append(Entry(1, ("Kept.",)))
        journals.journal("gone").entries.append(Entry(1, ("Gone.",)))
        journals.save()

        back = Journals.load(self.path, ["kept"])

        self.assertEqual(set(back.journals), {"kept"})

    def test_a_missing_or_unreadable_file_is_no_history(self) -> None:
        self.assertEqual(Journals.load(self.path, ["x"]).journals, {})
        self.path.write_text("{not json", encoding="utf-8")
        with self.assertLogs("webapp.journal", "WARNING"):
            self.assertEqual(Journals.load(self.path, ["x"]).journals, {})

    def test_a_write_that_fails_is_logged_and_never_raises(self) -> None:
        # A folder that is a file: no user, root included, can write
        # under it.
        blocker = self.folder / "blocker"
        blocker.write_text("", encoding="utf-8")
        journals = Journals(blocker / "d12ball_web_journal.json")

        with self.assertLogs("webapp.journal", "WARNING"):
            journals.add("g", GameResult(answer=("Said.",)))

        self.assertEqual(journals.journal("g").entries[0].lines, ("Said.",))

    def test_every_add_writes_the_file(self) -> None:
        journals = Journals(self.path)

        journals.add("g", GameResult(answer=("One.",)))
        journals.add("g", GameResult(answer=("Two.",)))

        written = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(
            [entry["lines"] for entry in written["g"]["entries"]],
            [["One."], ["Two."]],
        )

    def test_a_closed_room_takes_its_journal_with_it(self) -> None:
        journals = Journals(self.path)
        journals.add("g", GameResult(answer=("One.",)))

        journals.forget("g")

        self.assertEqual(
            json.loads(self.path.read_text(encoding="utf-8")), {},
        )


class JournalRestartTests(unittest.IsolatedAsyncioTestCase):
    """A room's transcript is as good after a restart as its link."""

    async def serve(self, service, journals: Journals) -> TestClient:
        web = WebApp(service, GameLocks(), journals=journals)
        web.watch()
        client = TestClient(TestServer(web.app))
        await client.start_server()
        self.addAsyncCleanup(client.close)
        self.addAsyncCleanup(web.stop)
        return client

    async def test_the_log_and_the_dice_are_there_after_a_restart(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "d12ball_web_journal.json"
        ENGINE.rng.seed(11)
        fixture = case("injury test")
        game = fixture.game
        service = service_over(fixture)
        client = await self.serve(service, Journals(path))

        for coach_id in (game.player_1_id, game.player_2_id):
            headers = as_coach(coach_id)
            state = await (
                await client.get(f"/api/game/{game.game_id}", headers=headers)
            ).json()
            rolls = [
                control["action"]
                for group in state["prompt"]["controls"]
                for control in group["controls"]
                if control["action"]["choice"] == "roll"
            ]
            if rolls:
                break
        await client.post(
            f"/api/game/{game.game_id}/action",
            headers=headers,
            data=json.dumps({"action": rolls[0]}),
        )
        before = await (
            await client.get(f"/api/game/{game.game_id}", headers=headers)
        ).json()
        self.assertIsNotNone(before["roll"])

        # The restart: the same games, a new process's journal read
        # off the file.
        after_client = await self.serve(
            service, Journals.load(path, service.games),
        )
        after = await (
            await after_client.get(
                f"/api/game/{game.game_id}", headers=headers,
            )
        ).json()

        self.assertEqual(after["entries"], before["entries"])
        self.assertEqual(after["latest"], before["latest"])
        self.assertEqual(after["roll"], before["roll"])
        self.assertEqual(after["board"]["version"], before["board"]["version"])
        response = await after_client.get(after["roll"]["url"])
        self.assertEqual(response.status, 200)
        self.assertEqual(response.content_type, "image/png")


if __name__ == "__main__":
    unittest.main()
