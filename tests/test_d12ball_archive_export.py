"""
gamesaves.d12ball.archive_export -- the pure file-writing half of
/debug export_archived_games. No Discord objects here, only plain data
and a real (tmpdir) filesystem, the same split test_game_storage.py
uses for save_games.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gamesaves.d12ball.archive_export import (
    ATTACHMENTS_DIRNAME,
    BOARD_FILENAME,
    GAME_FILENAME,
    TRANSCRIPT_FILENAME,
    archive_export_dir,
    write_game_export,
)


class ArchiveExportDirTests(unittest.TestCase):
    def test_unset_means_the_feature_is_off(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(archive_export_dir())

    def test_blank_means_the_feature_is_off(self) -> None:
        with mock.patch.dict(
            "os.environ", {"FOOLBOT_D12BALL_ARCHIVE_EXPORT_DIR": "   "},
        ):
            self.assertIsNone(archive_export_dir())

    def test_a_set_path_is_returned_expanded(self) -> None:
        with mock.patch.dict(
            "os.environ", {"FOOLBOT_D12BALL_ARCHIVE_EXPORT_DIR": "~/drive/pbd"},
        ):
            self.assertEqual(
                archive_export_dir(), Path("~/drive/pbd").expanduser(),
            )


class WriteGameExportTests(unittest.TestCase):
    def test_writes_the_game_board_transcript_and_attachments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "pbd7-cup-final"
            write_game_export(
                dest,
                game_data={"game_id": "g1", "game_number": 7},
                board_png=b"PNGDATA",
                transcript=[
                    {"id": 1, "content": "kickoff", "attachments": []},
                    {
                        "id": 2,
                        "content": "board",
                        "attachments": ["2-d12ball-pbd7.png"],
                    },
                ],
                attachments=[("2-d12ball-pbd7.png", b"img-bytes")],
            )

            self.assertEqual(
                json.loads((dest / GAME_FILENAME).read_text()),
                {"game_id": "g1", "game_number": 7},
            )
            self.assertEqual(
                (dest / BOARD_FILENAME).read_bytes(), b"PNGDATA",
            )

            lines = (
                (dest / TRANSCRIPT_FILENAME).read_text().splitlines()
            )
            self.assertEqual(len(lines), 2)
            self.assertEqual(json.loads(lines[0])["content"], "kickoff")
            self.assertEqual(json.loads(lines[1])["content"], "board")

            self.assertEqual(
                (dest / ATTACHMENTS_DIRNAME / "2-d12ball-pbd7.png").read_bytes(),
                b"img-bytes",
            )

    def test_no_board_means_no_board_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "pbd8"
            write_game_export(
                dest,
                game_data={"game_id": "g2"},
                board_png=None,
                transcript=[],
                attachments=[],
            )

            self.assertFalse((dest / BOARD_FILENAME).exists())
            self.assertFalse((dest / ATTACHMENTS_DIRNAME).exists())

    def test_an_unwritable_destination_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            blocked = Path(tmp) / "not-a-directory"
            blocked.write_text("i am a file, not a folder")

            with self.assertRaises(OSError):
                write_game_export(
                    blocked / "pbd9",
                    game_data={},
                    board_png=None,
                    transcript=[],
                    attachments=[],
                )


if __name__ == "__main__":
    unittest.main()
