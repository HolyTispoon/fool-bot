"""
The guarded read and write of a games file, for both games
(`gamesaves/d12ball/storage.py`, `gamesaves/codex/storage.py`).

What is shared is the file's handling, which turned out identical but
for the game's name: the temporary file renamed over the real one, a
save that never raises, and the two per-file failure flags -- a file
whose last save failed, and a file that was there but could not be read,
which is never written over. What each game keeps is what is in the
file: the record each entry becomes (D12 Ball's legacy migration and
constructor, Codex's `from_dict`), the folder made on load or not, its
own file and its own logger. **Each game also keeps its own two flag
sets** and hands them in on every call, read at call time, so a test
that swaps a game's set (`mock.patch.object(storage, "_save_failing",
set())`) still reaches the write.
"""

import json
import logging
from pathlib import Path
from typing import Any, Mapping, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_FOLDER = PROJECT_ROOT / "data"


def read_games_file(
    path: Path,
    *,
    noun: str,
    logger: logging.Logger,
    load_unreadable: set[Path],
    make_folder: bool,
) -> Optional[dict]:
    """
    The JSON saved at `path`, or `None` where there is nothing to read
    -- no file yet, or one that could not be read, which is marked in
    `load_unreadable` so `save_games` never writes over it. `noun` is
    the game's name in the log lines ("D12 Ball", "Codex").

    `make_folder` makes the folder before looking: D12 Ball's does,
    the Codex bot's does not, since a load that makes the folder creates
    `data/` wherever a cog is built, a test's included, and the first
    write makes it anyway.
    """
    load_unreadable.discard(path)

    try:
        if make_folder:
            path.parent.mkdir(parents=True, exist_ok=True)
        file_exists = path.exists()
    except OSError as error:
        # The folder is not reachable at all -- an unmounted drive, the
        # case in `save_games`. Whether there is a file behind it is
        # unknown, so assume there is: coming up empty and then saving
        # over it when the mount returns is the one outcome that loses
        # games for good.
        logger.error(f"Could not reach the {noun} save folder: %s", error)
        load_unreadable.add(path)
        return None

    if not file_exists:
        return None

    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except (json.JSONDecodeError, OSError) as error:
        # Errors, not warnings: every game the bot knows about has just
        # vanished from its view, and the players will see that as the
        # bot forgetting their match.
        logger.error(f"Could not load {noun} games from %s: %s", path, error)
        load_unreadable.add(path)
        return None


def save_games(
    games: Mapping[str, Any],
    path: Path,
    *,
    noun: str,
    logger: logging.Logger,
    save_failing: set[Path],
    load_unreadable: set[Path],
) -> None:
    """
    Write the games out to `path`, each through its record's own
    `to_dict`, and **never raise doing it.**

    A save is called part-way through resolving a turn, and a raise
    there takes the turn down with it: the click's callback dies
    wherever the save happened to sit, so a player whose move has
    already been announced is told "something went wrong, please try
    again" -- and trying again applies the move twice. The live game is
    the one in memory; this file is what a restart reads. Losing it is
    worth an entry in #logs, not a broken turn.

    Real cause seen in the wild: the checkout lives on a mounted
    network drive (a Windows Google Drive letter) and the mount went
    away mid-game, so `mkdir` walked the whole path up to a drive root
    that no longer existed. Nothing in the bot can fix that, which is
    exactly why it must not be the bot that breaks.

    The write itself is all-or-nothing -- a temporary file renamed over
    the real one -- so a failure part-way through leaves the last good
    save intact rather than a truncated one.

    **A file we could not read is never written over.** The other half
    of the same mount going away is the bot starting up while it is
    gone: the load comes back empty, and the first save after the mount
    returns would replace every saved game with the one or two played
    since. So a load that failed on anything but "there is no file yet"
    blocks writing until the process is restarted, which is the thing
    to do anyway -- the games it needs are in the file.

    Through each record's own `to_dict`, not `asdict`: what a record
    leaves out of its save has to be left out of the file.
    """
    if path in load_unreadable and path.exists():
        if path not in save_failing:
            logger.error(
                f"Not saving {noun} games over %s, which this run could "
                "not read: restart the process now that it is readable, "
                "or these games are lost.",
                path,
            )

        save_failing.add(path)

        return

    serialized_games = {
        game_id: game.to_dict()
        for game_id, game in games.items()
    }

    temporary_file = path.with_suffix(".tmp")

    try:
        path.parent.mkdir(parents=True, exist_ok=True)

        with temporary_file.open("w", encoding="utf-8") as file:
            json.dump(serialized_games, file, indent=2)

        temporary_file.replace(path)
    except OSError as error:
        # The first failure of a run reaches the server, because
        # somebody has to go and remount the drive (or free the disk).
        # The ones behind it are the same fact repeated once or twice a
        # click, so they stay on the console -- see "The level you log
        # at decides who sees it" in docs/design/logging.md.
        if path in save_failing:
            logger.info(f"Still could not save {noun} games: %s", error)
        else:
            logger.error(
                f"Could not save {noun} games to %s, so a restart would "
                "lose everything played since the last successful save: "
                "%s",
                path,
                error,
                exc_info=error,
            )

        save_failing.add(path)

        return

    if path in save_failing:
        logger.info(f"Saving {noun} games to %s again.", path)

    save_failing.discard(path)
