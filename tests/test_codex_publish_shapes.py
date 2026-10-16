"""
What the Codex publisher writes (docs/pbd-site.md, step 1): the shapes
of `index.json`, `archive.json`, `live.json` and `history.json` for a
staged game, a line with every token kind as segments, a display name
holding markup coming through as text, and the publisher's own record
surviving a round trip and a corrupt file.
"""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from codex import tokens
from codex.formatting import turn_heading
from codex.game import GameStatus
from codex_positions import new_game
from cogs.codex_publish import keys, record, shapes
from cogs.codex_publish.record import PublishedGame, PublishRecord
from cogs.codex_publish.segments import segments

GAME_ID = "0123456789abcdef0123456789abcdef"


def staged(**options):
    engine, game, match = new_game(**options)
    game.game_id = GAME_ID
    game.status = GameStatus.PLAYING
    return engine, game, match


class KeysTests(unittest.TestCase):
    def test_every_key_is_under_codex(self):
        board = b"RIFF board bytes"
        digest = hashlib.sha256(board).hexdigest()
        self.assertEqual(keys.INDEX_KEY, "codex/index.json")
        self.assertEqual(keys.ARCHIVE_KEY, "codex/archive.json")
        self.assertEqual(keys.live_key(GAME_ID), f"codex/games/{GAME_ID}/live.json")
        self.assertEqual(keys.history_key(GAME_ID), f"codex/games/{GAME_ID}/history.json")
        self.assertEqual(keys.board_key(GAME_ID, board), f"codex/games/{GAME_ID}/board-{digest}.webp")
        self.assertEqual(keys.emoji_key("codex_exhaust"), "codex/emoji/codex_exhaust.png")

    def test_a_board_is_named_by_its_bytes(self):
        self.assertEqual(keys.board_key(GAME_ID, b"one"), keys.board_key(GAME_ID, b"one"))
        self.assertNotEqual(keys.board_key(GAME_ID, b"one"), keys.board_key(GAME_ID, b"two"))


class ListShapesTests(unittest.TestCase):
    def test_a_duel_in_the_index(self):
        _, game, match = staged()
        entry = shapes.index_entry(game, match, "2026-10-16T12:00:00Z")
        self.assertEqual(entry, {
            "id": GAME_ID,
            "number": 1,
            "mode": "basic",
            "variant": "duel",
            "seats": [
                {"seat": 1, "name": "basher", "team": "Bashing"},
                {"seat": 2, "name": "fencer", "team": "Finesse"},
            ],
            "sides": [[1], [2]],
            "turn": match.turn,
            "turn_seats": [match.active],
            "updated": "2026-10-16T12:00:00Z",
        })
        json.dumps(entry)

    def test_a_seat_with_no_name_is_its_number(self):
        _, game, match = staged()
        game.seats[1]["name"] = None
        self.assertEqual(shapes.index_entry(game, match)["seats"][1]["name"], "Player 2")

    def test_a_finished_game_names_its_winner(self):
        _, game, match = staged()
        match.winner = 2
        game.status = GameStatus.FINISHED
        entry = shapes.archive_entry(game, match)
        self.assertEqual(entry["status"], "finished")
        self.assertEqual(entry["winner"], [2])

    def test_an_abandoned_game_has_no_winner(self):
        _, game, match = staged()
        game.status = GameStatus.ABANDONED
        entry = shapes.archive_entry(game, match)
        self.assertEqual(entry["status"], "abandoned")
        self.assertIsNone(entry["winner"])

    def test_a_dragon_is_two_sides_of_two_and_wins_as_a_team(self):
        teams = (("bashing",), ("finesse",), ("bashing",), ("finesse",))
        _, game, match = staged(teams=teams, variant="two_headed_dragon")
        match.winner = 3
        entry = shapes.archive_entry(game, match)
        self.assertEqual(entry["sides"], [[1, 2], [3, 4]])
        self.assertEqual(len(entry["turn_seats"]), 2)
        self.assertEqual(entry["winner"], [3, 4])

    def test_a_free_for_all_lists_only_the_seats_dealt_in(self):
        teams = (("bashing",), ("finesse",), ("bashing",))
        _, game, match = staged(teams=teams, variant="free_for_all")
        entry = shapes.index_entry(game, match)
        self.assertEqual([seat["seat"] for seat in entry["seats"]], [1, 2, 3])
        self.assertEqual(entry["sides"], [[1], [2], [3]])

    def test_the_lists_are_newest_first(self):
        listed = shapes.index([
            {"id": "a", "updated": "2026-10-16T10:00:00Z"},
            {"id": "b", "updated": "2026-10-16T12:00:00Z"},
            {"id": "c", "updated": None},
        ])
        self.assertEqual([entry["id"] for entry in listed["games"]], ["b", "a", "c"])
        self.assertEqual(shapes.archive([])["games"], [])


class GameShapesTests(unittest.TestCase):
    def setUp(self):
        _, self.game, self.match = staged()
        self.board = keys.board_key(GAME_ID, b"board")
        self.published = PublishedGame(
            turn=self.match.turn,
            heading=turn_heading(self.match),
            lines=[f"{tokens.player(1)} plays {tokens.card('iron_man')}."],
            board=self.board,
            history_version=3,
            updated="2026-10-16T12:00:00Z",
        )

    def test_live(self):
        written = shapes.live(self.game, self.match, self.published)
        self.assertEqual(written["id"], GAME_ID)
        self.assertEqual(written["status"], "playing")
        self.assertEqual(written["board"], self.board)
        self.assertEqual(written["history_version"], 3)
        self.assertEqual(written["history"], keys.history_key(GAME_ID))
        self.assertEqual(written["heading"][0], {"text": f"Turn {self.match.turn}", "bold": True})
        self.assertIn({"player": 1, "name": "basher"}, written["heading"])
        self.assertEqual(written["lines"], [[
            {"player": 1, "name": "basher"},
            {"text": " plays "},
            {"card": "iron_man", "name": "Iron Man"},
            {"text": "."},
        ]])
        json.dumps(written)

    def test_live_before_any_heading(self):
        written = shapes.live(self.game, self.match, PublishedGame())
        self.assertEqual((written["heading"], written["lines"], written["board"]), ([], [], None))

    def test_history_keeps_every_line_whole_and_passes_other_fields_through(self):
        lines = [f"Line {number} of a long turn." for number in range(300)]
        self.published.history = [
            {"turn": 1, "heading": "**Turn 1** -- {to:1} (Bashing)", "lines": lines,
             "board": self.board, "actions": ["kept"]},
        ]
        written = shapes.history(self.game, self.published)
        self.assertEqual(written["id"], GAME_ID)
        self.assertEqual(written["version"], 3)
        (turn,) = written["turns"]
        self.assertEqual(turn["turn"], 1)
        self.assertEqual(turn["board"], self.board)
        self.assertEqual(turn["actions"], ["kept"])
        self.assertEqual(len(turn["lines"]), 300)
        self.assertEqual(turn["lines"][299], [{"text": "Line 299 of a long turn."}])
        self.assertEqual(turn["heading"][2], {"player": 1, "name": "basher"})
        # The record's entry is not changed by writing it.
        self.assertEqual(self.published.history[0]["lines"], lines)


class SegmentsTests(unittest.TestCase):
    def setUp(self):
        _, self.game, _ = staged()

    def test_every_token_kind(self):
        line = (
            f"{tokens.player(1)} {tokens.addressed(2)} {tokens.card('iron_man')} "
            f"{tokens.hero('troq_bashar')} {tokens.gold(3)} {tokens.exhaust()} "
            f"{tokens.target()} {tokens.codex()} {tokens.arrow()}"
        )
        self.assertEqual(segments(line, self.game), [
            {"player": 1, "name": "basher"},
            {"text": " "},
            {"player": 2, "name": "fencer"},
            {"text": " "},
            {"card": "iron_man", "name": "Iron Man"},
            {"text": " "},
            {"card": "troq_bashar", "name": "Troq Bashar", "hero": True},
            {"text": " "},
            {"glyph": "gold", "key": "codex/emoji/gold.png", "n": 3, "alt": "3 gold"},
            {"text": " "},
            {"glyph": "exhaust", "key": "codex/emoji/codex_exhaust.png", "alt": "exhaust"},
            {"text": " "},
            {"glyph": "target", "key": "codex/emoji/target.png", "alt": "target"},
            {"text": " "},
            {"glyph": "codex", "key": "codex/emoji/codex.png", "alt": "Codex"},
            {"text": " ->"},
        ])

    def test_an_addressed_seat_is_its_name_never_a_mention(self):
        (found,) = segments(tokens.addressed(1), self.game)
        self.assertEqual(found, {"player": 1, "name": "basher"})
        self.assertNotIn("<@", json.dumps(found))

    def test_bold_and_italic_are_flags(self):
        line = f"**{tokens.player(1)}'s base is destroyed.** *Then* the end."
        self.assertEqual(segments(line, self.game), [
            {"player": 1, "name": "basher", "bold": True},
            {"text": "'s base is destroyed.", "bold": True},
            {"text": " "},
            {"text": "Then", "italic": True},
            {"text": " the end."},
        ])

    def test_an_unpaired_asterisk_is_text(self):
        self.assertEqual(segments("2*3 gold", self.game), [{"text": "2*3 gold"}])
        self.assertEqual(segments("**open", self.game), [{"text": "**open"}])

    def test_a_display_name_is_text_whatever_it_holds(self):
        self.game.seats[0]["name"] = "<img src=x onerror=alert(1)> **bold** *it*"
        found = segments(f"{tokens.player(1)} draws.", self.game)
        self.assertEqual(found[0], {"player": 1, "name": "<img src=x onerror=alert(1)> **bold** *it*"})
        self.assertEqual(found[1], {"text": " draws."})
        self.assertEqual(len(found), 2)

    def test_no_game_names_a_seat_by_its_number(self):
        self.assertEqual(segments(tokens.player(2)), [{"player": 2, "name": "Player 2"}])

    def test_a_line_with_no_tokens_is_one_text(self):
        self.assertEqual(segments("Nothing happens."), [{"text": "Nothing happens."}])
        self.assertEqual(segments(""), [])


class RecordTests(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.path = self.folder / "data" / "codex_pbd.json"
        flags = (mock.patch.object(record, "_save_failing", set()),
                 mock.patch.object(record, "_load_unreadable", set()))
        for flag in flags:
            flag.start()
            self.addCleanup(flag.stop)

    def published(self) -> PublishedGame:
        return PublishedGame(
            turn=4,
            heading="**Turn 4** -- {to:2} (Finesse)",
            lines=["{player:2} plays {card:iron_man}."],
            history=[{"turn": 3, "heading": "**Turn 3** -- {to:1} (Bashing)",
                      "lines": ["{player:1} ends the turn."], "board": "codex/games/x/board-a.webp"}],
            board="codex/games/x/board-b.webp",
            uploaded=["codex/games/x/board-a.webp", "codex/games/x/board-b.webp"],
            history_version=2,
            imported=True,
            updated="2026-10-16T12:00:00Z",
        )

    def test_a_round_trip(self):
        saved = PublishRecord(path=self.path)
        saved.games[GAME_ID] = self.published()
        saved.save()
        loaded = PublishRecord.load(self.path)
        self.assertEqual(loaded.games, {GAME_ID: self.published()})

    def test_a_load_makes_no_folder(self):
        loaded = PublishRecord.load(self.path)
        self.assertEqual(loaded.games, {})
        self.assertFalse(self.path.parent.exists())

    def test_the_default_file_is_in_data(self):
        self.assertEqual(record.PUBLISH_FILE.parent.name, "data")
        self.assertEqual(record.PUBLISH_FILE.name, "codex_pbd.json")
        with mock.patch.object(record, "PUBLISH_FILE", self.path):
            self.assertEqual(PublishRecord().file, self.path)

    def test_a_corrupt_file_loads_empty_and_is_never_written_over(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{not json", encoding="utf-8")
        with self.assertLogs(record.LOGGER, "ERROR"):
            loaded = PublishRecord.load(self.path)
        self.assertEqual(loaded.games, {})
        loaded.games[GAME_ID] = self.published()
        with self.assertLogs(record.LOGGER, "ERROR"):
            loaded.save()
        self.assertEqual(self.path.read_text(encoding="utf-8"), "{not json")

    def test_a_save_that_fails_is_logged_not_raised(self):
        blocked = self.folder / "file"
        blocked.write_text("", encoding="utf-8")
        saved = PublishRecord(path=blocked / "codex_pbd.json")
        saved.games[GAME_ID] = self.published()
        with self.assertLogs(record.LOGGER, "ERROR"):
            saved.save()

    def test_a_bad_entry_loads_what_it_holds(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps({
            GAME_ID: {"turn": "four", "lines": ["one", 2], "history": [{"turn": 1}, "x"],
                      "history_version": True, "imported": "yes"},
            "other": ["not", "a", "record"],
        }), encoding="utf-8")
        with self.assertLogs(record.LOGGER, "WARNING"):
            loaded = PublishRecord.load(self.path)
        self.assertEqual(list(loaded.games), [GAME_ID])
        entry = loaded.games[GAME_ID]
        self.assertEqual((entry.turn, entry.lines, entry.history), (None, ["one"], [{"turn": 1}]))
        self.assertEqual((entry.history_version, entry.imported), (0, False))

    def test_game_makes_an_entry_and_drop_takes_it_away(self):
        held = PublishRecord(path=self.path)
        entry = held.game(GAME_ID)
        self.assertIs(held.game(GAME_ID), entry)
        held.drop(GAME_ID)
        held.drop(GAME_ID)
        self.assertEqual(held.games, {})


if __name__ == "__main__":
    unittest.main()
