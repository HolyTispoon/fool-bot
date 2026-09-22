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
"""

import json
import tempfile
import unittest
from pathlib import Path
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
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)

        self.folder = Path(directory.name) / "data"
        self.games_file = self.folder / "d12ball_games.json"

        self.use_folder(self.folder)

        # Both flags are module state that outlives a test otherwise.
        self.enter_patch(mock.patch.object(storage, "_save_failing", False))
        self.enter_patch(
            mock.patch.object(storage, "_load_unreadable", False),
        )

    def enter_patch(self, patcher: object) -> object:
        started = patcher.start()
        self.addCleanup(patcher.stop)

        return started

    def use_folder(self, folder: Path) -> None:
        self.enter_patch(mock.patch.object(storage, "DATA_FOLDER", folder))
        self.enter_patch(
            mock.patch.object(
                storage,
                "GAMES_FILE",
                folder / "d12ball_games.json",
            ),
        )

    def test_a_game_round_trips(self) -> None:
        storage.save_games({"g1": build_game()})

        self.assertEqual(list(storage.load_games()), ["g1"])

    def test_the_discord_ids_read_back_as_they_were_saved(self) -> None:
        """
        `guild_id`, `channel_id` and `message_id` went optional for a
        game with no channel (decision 3 of docs/web-app.md); a save
        that carries them is unchanged by that, and the saved dict
        keeps the same keys in the same order.
        """
        game = build_game()
        game.message_id = 99
        storage.save_games({"g1": game})

        loaded = storage.load_games()["g1"]
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
        storage.save_games({"web": game})

        loaded = storage.load_games()["web"]
        self.assertEqual(
            (loaded.guild_id, loaded.channel_id, loaded.message_id),
            (None, None, None),
        )
        self.assertEqual(loaded.to_dict(), game.to_dict())

    def test_a_save_onto_an_unreachable_folder_does_not_raise(self) -> None:
        # What the mounted drive did: every component of the path is
        # gone, so mkdir fails rather than the write.
        self.use_folder(Path("/nonexistent-mount/fool-bot/data"))

        with self.assertLogs(storage.LOGGER, level="ERROR") as logs:
            storage.save_games({"g1": build_game()})

        self.assertIn("Could not save", logs.output[0])

    def test_only_the_first_failure_of_a_run_reaches_the_server(self) -> None:
        self.use_folder(Path("/nonexistent-mount/fool-bot/data"))
        games = {"g1": build_game()}

        with self.assertLogs(storage.LOGGER, level="INFO") as logs:
            storage.save_games(games)
            storage.save_games(games)
            storage.save_games(games)

        levels = [line.split(":", 1)[0] for line in logs.output]
        self.assertEqual(levels, ["ERROR", "INFO", "INFO"])

    def test_a_save_that_lands_arms_the_error_again(self) -> None:
        games = {"g1": build_game()}

        with mock.patch.object(storage, "DATA_FOLDER", Path("/nonexistent")):
            with mock.patch.object(
                storage,
                "GAMES_FILE",
                Path("/nonexistent/d12ball_games.json"),
            ):
                with self.assertLogs(storage.LOGGER, level="ERROR"):
                    storage.save_games(games)

        with self.assertLogs(storage.LOGGER, level="INFO"):
            storage.save_games(games)

        with self.assertLogs(storage.LOGGER, level="ERROR") as logs:
            with mock.patch.object(
                storage,
                "DATA_FOLDER",
                Path("/nonexistent"),
            ):
                with mock.patch.object(
                    storage,
                    "GAMES_FILE",
                    Path("/nonexistent/d12ball_games.json"),
                ):
                    storage.save_games(games)

        self.assertIn("Could not save", logs.output[0])

    def test_a_failed_save_leaves_the_last_good_one_alone(self) -> None:
        storage.save_games({"g1": build_game()})

        with mock.patch.object(
            storage.json,
            "dump",
            side_effect=OSError("no space left on device"),
        ):
            with self.assertLogs(storage.LOGGER, level="ERROR"):
                storage.save_games({"g2": build_game("g2")})

        self.assertEqual(list(storage.load_games()), ["g1"])

    def test_an_unreadable_file_is_not_written_over(self) -> None:
        storage.save_games({"g1": build_game()})

        with mock.patch.object(
            Path,
            "open",
            side_effect=OSError("the device is not ready"),
        ):
            with self.assertLogs(storage.LOGGER, level="ERROR"):
                self.assertEqual(storage.load_games(), {})

        with self.assertLogs(storage.LOGGER, level="ERROR") as logs:
            storage.save_games({"g2": build_game("g2")})

        self.assertIn("Not saving", logs.output[0])

        with self.games_file.open(encoding="utf-8") as file:
            self.assertEqual(list(json.load(file)), ["g1"])

    def test_an_unreachable_folder_blocks_the_save_when_it_returns(
        self,
    ) -> None:
        storage.save_games({"g1": build_game()})
        missing = Path("/nonexistent-mount/fool-bot/data")

        # The bot starts while the mount is away...
        with mock.patch.object(storage, "DATA_FOLDER", missing):
            with mock.patch.object(
                storage,
                "GAMES_FILE",
                missing / "d12ball_games.json",
            ):
                with self.assertLogs(storage.LOGGER, level="ERROR"):
                    self.assertEqual(storage.load_games(), {})

        # ...and a game is played once it is back. Saving it now would
        # replace every game in the file with that one.
        with self.assertLogs(storage.LOGGER, level="ERROR"):
            storage.save_games({"g2": build_game("g2")})

        with self.games_file.open(encoding="utf-8") as file:
            self.assertEqual(list(json.load(file)), ["g1"])

    def test_a_first_run_with_no_file_yet_still_saves(self) -> None:
        self.assertEqual(storage.load_games(), {})

        storage.save_games({"g1": build_game()})

        self.assertEqual(list(storage.load_games()), ["g1"])


if __name__ == "__main__":
    unittest.main()
