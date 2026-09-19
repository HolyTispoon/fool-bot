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

from d12ball.game import GameMode, GameStatus, Team
from gamesaves.d12ball.archive_export import (
    ATTACHMENTS_DIRNAME,
    BOARD_FILENAME,
    GAME_FILENAME,
    TRANSCRIPT_FILENAME,
    TRANSCRIPT_PAGE_FILENAME,
    archive_export_dir,
    describe_goals,
    prettify_player_id,
    render_message_content,
    render_transcript_html,
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


class TranscriptPageTests(unittest.TestCase):
    """
    transcript.html -- the one file in an export a person opens. The
    JSONL beside it is the lossless record and unreadable without a
    tool, which is the whole reason this exists.
    """

    def build_game(self, **overrides) -> dict:
        game = {
            "game_number": 12,
            "game_name": "The Cup Final",
            "player_1_name": "Alice",
            "player_2_name": "Bob",
            "player_1_team": "orange",
            "player_2_team": "purple",
            "home_player_number": 1,
            "mode": "basic",
            "board_size": 7,
            "status": "finished",
            "match_state": {
                "scoreboard": {
                    "home_score": 2,
                    "visiting_score": 1,
                    "time": 27,
                    "period": "second_half",
                },
                "goals": [
                    {
                        "side": "home",
                        "player_id": "hellguard_striker",
                        "time": 7,
                        "period": "first_half",
                        "own_goal": False,
                        "shootout": False,
                    },
                    {
                        "side": "home",
                        "player_id": "riftwarden_fullback~2",
                        "time": 19,
                        "period": "second_half",
                        "own_goal": True,
                        "shootout": False,
                    },
                ],
            },
        }
        game.update(overrides)
        return game

    def test_the_page_carries_the_summary_the_json_hides(self) -> None:
        page = render_transcript_html(self.build_game(), [], has_board=False)

        self.assertIn("PBD12 - The Cup Final", page)
        self.assertIn("Alice (orange)", page)
        self.assertIn("Bob (purple)", page)
        self.assertIn("2 - 1", page)

    def test_an_own_goal_names_the_defender_and_the_side_it_counted_for(
        self,
    ) -> None:
        """
        The one line of a scoresheet where the name and the column
        disagree -- `side` is who it counted for, `player_id` is who
        put it in. See "The goal log" in docs/design/clock-and-records.md.
        """
        goals = describe_goals(self.build_game())

        self.assertIn("Hellguard (Striker) for home", goals[0])
        self.assertIn("Riftwarden (Fullback, 2nd) for home", goals[1])
        self.assertIn("own goal", goals[1])

    def test_images_are_shown_and_other_files_are_linked(self) -> None:
        transcript = [
            {
                "author": "fool-bot",
                "created_at": "2026-01-01T00:00:00+00:00",
                "content": "The board:",
                "attachments": ["1-d12ball-pbd.png", "2-notes.txt"],
            },
        ]

        page = render_transcript_html(
            self.build_game(), transcript, has_board=False,
        )

        self.assertIn(
            f'<img src="{ATTACHMENTS_DIRNAME}/1-d12ball-pbd.png"', page,
        )
        self.assertIn(f'<a href="{ATTACHMENTS_DIRNAME}/2-notes.txt"', page)

    def test_a_message_cannot_inject_markup(self) -> None:
        """
        Every message in the channel is somebody's typing, and this
        page is opened straight off disk with no sandbox around it.
        """
        transcript = [
            {
                "author": "<script>alert(1)</script>",
                "created_at": "2026-01-01T00:00:00+00:00",
                "content": "<img src=x onerror=alert(2)>",
                "attachments": [],
            },
        ]

        page = render_transcript_html(
            self.build_game(), transcript, has_board=False,
        )

        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertNotIn("<img src=x onerror", page)
        self.assertIn("&lt;script&gt;", page)

    def test_a_game_with_no_match_state_still_renders(self) -> None:
        """
        A game abandoned during setup never had a scoreboard. An export
        that raises is an export that is not written, and the channel it
        came from is about to be deleted.
        """
        page = render_transcript_html(
            {"game_number": 3, "abandoned": True}, [], has_board=False,
        )

        self.assertIn("PBD3", page)
        self.assertIn("Abandoned", page)

    def test_it_is_written_beside_the_jsonl_from_the_same_messages(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "pbd12-the-cup-final"
            write_game_export(
                dest,
                game_data=self.build_game(),
                board_png=b"PNG",
                transcript=[
                    {
                        "author": "Alice",
                        "created_at": "2026-01-01T00:00:00+00:00",
                        "content": "good game",
                        "attachments": [],
                    },
                ],
                attachments=[],
            )

            page = (dest / TRANSCRIPT_PAGE_FILENAME).read_text(encoding="utf-8")
            lines = (dest / TRANSCRIPT_FILENAME).read_text(
                encoding="utf-8",
            ).strip().splitlines()

        self.assertEqual(len(lines), 1)
        self.assertIn("good game", page)
        self.assertIn(json.loads(lines[0])["author"], page)
        # The board is drawn on the page only when there is one.
        self.assertIn(f'src="{BOARD_FILENAME}"', page)


class PrettifyPlayerIdTests(unittest.TestCase):
    def test_a_card_id_reads_as_a_name_and_a_role(self) -> None:
        self.assertEqual(
            prettify_player_id("hellguard_fullback"), "Hellguard (Fullback)",
        )

    def test_the_visiting_copy_of_a_shared_player_is_marked(self) -> None:
        """
        Both sides can field the same person -- see "One player, both
        sides" in docs/design/teams-and-players.md -- and a scoresheet naming them twice with
        nothing to tell them apart is a scoresheet nobody can read.
        """
        self.assertEqual(
            prettify_player_id("hellguard_fullback~2"),
            "Hellguard (Fullback, 2nd)",
        )

    def test_an_id_it_cannot_parse_is_left_alone(self) -> None:
        self.assertEqual(prettify_player_id("mystery"), "mystery")


class RealSaveDataTests(unittest.TestCase):
    """
    `game.to_dict()` is `dataclasses.asdict`, which leaves enum members
    in place. `json.dump` writes a `str, Enum` out as its value, so the
    file reads "finished" -- but `str()` on the member in memory gives
    "GameStatus.FINISHED", and this page is built from the dict, not
    the file.

    The first version of these tests used a fixture of honest strings
    and passed while the real export said `Home: Tomer (Team.ORANGE)`.
    So this one carries the enums a real save carries.
    """

    def test_enums_read_as_their_values_not_their_reprs(self) -> None:
        page = render_transcript_html(
            {
                "game_number": 12,
                "player_1_name": "Tomer",
                "player_2_name": "Dinky AI",
                "player_1_team": Team.ORANGE,
                "player_2_team": Team.PURPLE,
                "home_player_number": 1,
                "mode": GameMode.BASIC,
                "status": GameStatus.FINISHED,
            },
            [],
            has_board=False,
        )

        self.assertIn("Tomer (orange)", page)
        self.assertIn("<dd>basic</dd>", page)
        self.assertIn("<dd>finished</dd>", page)
        self.assertNotIn("Team.ORANGE", page)
        self.assertNotIn("GameStatus.", page)
        self.assertNotIn("GameMode.", page)


class MessageContentTests(unittest.TestCase):
    def test_the_markdown_the_bot_writes_becomes_tags(self) -> None:
        """
        Nearly every message the bot posts is **bold** somewhere, and a
        page printing the asterisks reads worse than the channel it
        replaced.
        """
        rendered = render_message_content(
            "**GOAL!** Striker scores. *narrowly* `M2`",
        )

        self.assertIn("<strong>GOAL!</strong>", rendered)
        self.assertIn("<em>narrowly</em>", rendered)
        self.assertIn("<code>M2</code>", rendered)

    def test_escaping_happens_before_any_pattern_is_applied(self) -> None:
        """
        The order is the whole of the safety: by the time a pattern
        runs, a typed tag is already `&lt;...&gt;`, so no pattern can
        put back what the escape took out.
        """
        rendered = render_message_content("**<script>alert(1)</script>**")

        self.assertIn("<strong>", rendered)
        self.assertNotIn("<script>", rendered)
        self.assertIn("&lt;script&gt;", rendered)

    def test_bold_is_not_mistaken_for_two_italics(self) -> None:
        rendered = render_message_content("**bold** and not*this*")

        self.assertIn("<strong>bold</strong>", rendered)
        self.assertNotIn("<em>bold</em>", rendered)

    def test_a_lone_asterisk_is_left_alone(self) -> None:
        self.assertEqual(render_message_content("2 * 3"), "2 * 3")
