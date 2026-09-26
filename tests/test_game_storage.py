"""
Saving and loading the games, when the disk under them is not there.

One developer runs the bot out of a checkout on a mounted Google Drive
letter, and the mount went away mid-game: every `save_games` after that
raised FileNotFoundError from `mkdir` walking up to a drive root that
no longer existed. The raise landed in whichever callback was
resolving the turn, so a coach whose maneuver had already been
announced was told the click had failed and invited to make it again.

These cover the two halves of that: a save that cannot write must not
raise, and a run that could not read the file must not write over it.

Every case runs twice: once as the bot calls the store (no path, so
`GAMES_FILE`), and once as the web app does (its own file, named).
The two flags are per file, so the second run is also what shows one
file's trouble says nothing about the other's.
"""

import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import Optional
from unittest import mock

from d12ball.game import D12BallGame

from gamesaves.d12ball import storage


def build_game(game_id: str = "g1") -> D12BallGame:
    return D12BallGame(
        game_id=game_id,
        game_number=1,
        guild_id=1,
        channel_id=2,
        message_id=None,
        player_1_id=3,
        player_2_id=None,
    )


class GameStorageTests(unittest.TestCase):
    """The bot's file, reached the way the bot reaches it: no path."""

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)

        self.folder = Path(directory.name) / "data"
        self.point_at(self.folder)

        # Both flags are module state that outlives a test otherwise.
        self.enter_patch(mock.patch.object(storage, "_save_failing", set()))
        self.enter_patch(
            mock.patch.object(storage, "_load_unreadable", set()),
        )

    def enter_patch(self, patcher: object) -> object:
        started = patcher.start()
        self.addCleanup(patcher.stop)

        return started

    def point_at(self, folder: Path) -> None:
        """Put this case's file in `folder` for the rest of the test."""
        self.enter_patch(mock.patch.object(storage, "DATA_FOLDER", folder))
        self.enter_patch(
            mock.patch.object(
                storage,
                "GAMES_FILE",
                folder / "d12ball_games.json",
            ),
        )
        self.games_file = self.file_in(folder)

    def file_in(self, folder: Path) -> Path:
        return folder / "d12ball_games.json"

    def path_argument(self) -> Optional[Path]:
        return None

    def save(self, games: dict) -> None:
        storage.save_games(games, self.path_argument())

    def load(self) -> dict:
        return storage.load_games(self.path_argument())

    @contextmanager
    def mount_away(self):
        """
        The drive under the file is gone for the block: every `mkdir`
        walks up to a root that is not there. The same file before and
        after, which is the point -- the flags are per file.
        """
        with mock.patch.object(
            Path,
            "mkdir",
            side_effect=FileNotFoundError("the drive is gone"),
        ):
            yield

    def test_a_game_round_trips(self) -> None:
        self.save({"g1": build_game()})

        self.assertEqual(list(self.load()), ["g1"])

    def test_the_discord_ids_read_back_as_they_were_saved(self) -> None:
        """
        `guild_id`, `channel_id` and `message_id` went optional for a
        game with no channel (decision 3 of docs/web-app.md); a save
        that carries them is unchanged by that, and the saved dict
        keeps the same keys in the same order.
        """
        game = build_game()
        game.message_id = 99
        self.save({"g1": game})

        loaded = self.load()["g1"]
        self.assertEqual(
            (loaded.guild_id, loaded.channel_id, loaded.message_id),
            (1, 2, 99),
        )
        self.assertEqual(
            list(loaded.to_dict())[:6],
            [
                "game_id", "game_number", "guild_id", "channel_id",
                "message_id", "player_1_id",
            ],
        )

    def test_a_game_with_no_channel_round_trips(self) -> None:
        """A game the web frontend creates is played nowhere on
        Discord, and the record says so with three `None`s."""
        game = D12BallGame(
            game_id="web", game_number=1, player_1_id=3, player_2_id=None,
        )
        self.assertIsNone(game.guild_id)
        self.save({"web": game})

        loaded = self.load()["web"]
        self.assertEqual(
            (loaded.guild_id, loaded.channel_id, loaded.message_id),
            (None, None, None),
        )
        self.assertEqual(loaded.to_dict(), game.to_dict())

    def test_a_save_onto_an_unreachable_folder_does_not_raise(self) -> None:
        # What the mounted drive did: every component of the path is
        # gone, so mkdir fails rather than the write.
        self.point_at(Path("/nonexistent-mount/fool-bot/data"))

        with self.assertLogs(storage.LOGGER, level="ERROR") as logs:
            self.save({"g1": build_game()})

        self.assertIn("Could not save", logs.output[0])

    def test_only_the_first_failure_of_a_run_reaches_the_server(self) -> None:
        self.point_at(Path("/nonexistent-mount/fool-bot/data"))
        games = {"g1": build_game()}

        with self.assertLogs(storage.LOGGER, level="INFO") as logs:
            self.save(games)
            self.save(games)
            self.save(games)

        levels = [line.split(":", 1)[0] for line in logs.output]
        self.assertEqual(levels, ["ERROR", "INFO", "INFO"])

    def test_a_save_that_lands_arms_the_error_again(self) -> None:
        games = {"g1": build_game()}

        with self.mount_away():
            with self.assertLogs(storage.LOGGER, level="ERROR"):
                self.save(games)

        with self.assertLogs(storage.LOGGER, level="INFO") as logs:
            self.save(games)

        self.assertIn("again", logs.output[0])

        with self.assertLogs(storage.LOGGER, level="ERROR") as logs:
            with self.mount_away():
                self.save(games)

        self.assertIn("Could not save", logs.output[0])

    def test_a_failed_save_leaves_the_last_good_one_alone(self) -> None:
        self.save({"g1": build_game()})

        with mock.patch.object(
            storage.json,
            "dump",
            side_effect=OSError("no space left on device"),
        ):
            with self.assertLogs(storage.LOGGER, level="ERROR"):
                self.save({"g2": build_game("g2")})

        self.assertEqual(list(self.load()), ["g1"])

    def test_an_unreadable_file_is_not_written_over(self) -> None:
        self.save({"g1": build_game()})

        with mock.patch.object(
            Path,
            "open",
            side_effect=OSError("the device is not ready"),
        ):
            with self.assertLogs(storage.LOGGER, level="ERROR"):
                self.assertEqual(self.load(), {})

        with self.assertLogs(storage.LOGGER, level="ERROR") as logs:
            self.save({"g2": build_game("g2")})

        self.assertIn("Not saving", logs.output[0])

        with self.games_file.open(encoding="utf-8") as file:
            self.assertEqual(list(json.load(file)), ["g1"])

    def test_an_unreachable_folder_blocks_the_save_when_it_returns(
        self,
    ) -> None:
        self.save({"g1": build_game()})

        # The process starts while the mount is away...
        with self.mount_away():
            with self.assertLogs(storage.LOGGER, level="ERROR"):
                self.assertEqual(self.load(), {})

        # ...and a game is played once it is back. Saving it now would
        # replace every game in the file with that one.
        with self.assertLogs(storage.LOGGER, level="ERROR"):
            self.save({"g2": build_game("g2")})

        with self.games_file.open(encoding="utf-8") as file:
            self.assertEqual(list(json.load(file)), ["g1"])

    def test_a_first_run_with_no_file_yet_still_saves(self) -> None:
        self.assertEqual(self.load(), {})

        self.save({"g1": build_game()})

        self.assertEqual(list(self.load()), ["g1"])


class WebGamesFileStorageTests(GameStorageTests):
    """
    The same cases over the web app's own file, named explicitly the
    way `python3 -m webapp` names it -- and not one of them may touch
    the bot's file on the way.
    """

    def file_in(self, folder: Path) -> Path:
        return folder / storage.WEB_GAMES_FILE.name

    def path_argument(self) -> Optional[Path]:
        return self.games_file

    def tearDown(self) -> None:
        self.assertFalse(storage.GAMES_FILE.exists())


class TwoFilesTests(unittest.TestCase):
    def test_the_web_games_file_is_not_the_bots(self) -> None:
        self.assertNotEqual(storage.WEB_GAMES_FILE, storage.GAMES_FILE)
        self.assertEqual(
            storage.WEB_GAMES_FILE.parent, storage.GAMES_FILE.parent,
        )

    def test_one_files_trouble_is_not_the_others(self) -> None:
        """
        The bot reading the web file for the statistics (step 6 of
        docs/web-app-next.md) and finding it unreadable must not stop
        the bot saving its own games.
        """
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            bot_file = folder / "d12ball_games.json"
            web_file = folder / "d12ball_web_games.json"
            web_file.write_text("{not json", encoding="utf-8")

            with mock.patch.object(storage, "_save_failing", set()), \
                 mock.patch.object(storage, "_load_unreadable", set()):
                with self.assertLogs(storage.LOGGER, level="ERROR"):
                    self.assertEqual(storage.load_games(web_file), {})

                storage.save_games({"g1": build_game()}, bot_file)

            self.assertEqual(
                list(json.loads(bot_file.read_text(encoding="utf-8"))),
                ["g1"],
            )


if __name__ == "__main__":
    unittest.main()
