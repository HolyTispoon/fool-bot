import json
import logging
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Optional
from d12ball.game import D12BallGame


LOGGER = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_FOLDER = PROJECT_ROOT / "data"
GAMES_FILE = DATA_FOLDER / "d12ball_games.json"

# Whether the last save failed to reach the disk, refused or rejected.
# A run of failures is one thing wrong repeated once or twice a click,
# so only the first of them is worth waking anyone for; see
# `save_games`.
_save_failing = False

# Whether the file was there but could not be read. The games in
# memory are then not the games on disk, and `save_games` refuses to
# write over it -- see "A file we could not read is never written
# over" in that function.
_load_unreadable = False

def load_games() -> dict[str, D12BallGame]:
    global _load_unreadable

    _load_unreadable = False

    try:
        DATA_FOLDER.mkdir(parents=True, exist_ok=True)
        file_exists = GAMES_FILE.exists()
    except OSError as error:
        # The folder is not reachable at all -- an unmounted drive, the
        # case in `save_games`. Whether there is a file behind it is
        # unknown, so assume there is: coming up empty and then saving
        # over it when the mount returns is the one outcome that loses
        # games for good.
        LOGGER.error("Could not reach the D12 Ball save folder: %s", error)
        _load_unreadable = True

        return {}

    if not file_exists:
        return {}

    try:
        with GAMES_FILE.open("r", encoding="utf-8") as file:
            raw_data = json.load(file)
    except (json.JSONDecodeError, OSError) as error:
        # Errors, not warnings: every game the bot knows about has just
        # vanished from its view, and the players will see that as the
        # bot forgetting their match.
        LOGGER.error("Could not load D12 Ball games: %s", error)
        _load_unreadable = True

        return {}

    games: dict[str, D12BallGame] = {}
    known_fields = {field.name for field in fields(D12BallGame)}

    for game_id, game_data in raw_data.items():
        # A key the record no longer has is a field that was removed
        # while games saved under it were still half-played --
        # `tie_mode`, when league mode went. Dropping it keeps those
        # games loading; passing it through would raise TypeError and
        # take the whole game out of the bot's view. Console-only,
        # because nobody can act on it and every restart would repeat
        # it.
        retired = sorted(set(game_data) - known_fields)
        if retired:
            LOGGER.info(
                "Ignoring retired field(s) %s on saved game %s.",
                ", ".join(retired),
                game_id,
            )
            game_data = {
                key: value
                for key, value in game_data.items()
                if key in known_fields
            }

        try:
            games[game_id] = D12BallGame(**game_data)
        except TypeError as error:
            LOGGER.error("Skipping invalid saved game %s: %s", game_id, error)

    return games


def save_games(games: dict[str, D12BallGame]) -> None:
    """
    Write the games out, and **never raise doing it.**

    This is called from about a hundred and fifty places, most of them
    part-way through resolving a turn, and a raise there takes the turn
    down with it: the click's callback dies wherever the save happened
    to sit, so a coach whose maneuver has already been announced and
    whose board has already been redrawn is told "something went wrong,
    please try again" -- and trying again applies the turn twice. The
    live game is the one in memory; this file is what a restart reads.
    Losing it is worth an entry in #logs, not a broken turn.

    Real cause seen in the wild: the checkout lives on a mounted
    network drive (a Windows Google Drive letter) and the mount went
    away mid-game, so `mkdir` walked the whole path up to a drive root
    that no longer existed. Nothing in the bot can fix that, which is
    exactly why it must not be the bot that breaks.

    The write itself is already all-or-nothing -- a temporary file
    renamed over the real one -- so a failure part-way through leaves
    the last good save intact rather than a truncated one.

    **A file we could not read is never written over.** The other half
    of the same mount going away is the bot starting up while it is
    gone: `load_games` comes back empty, and the first save after the
    mount returns would replace every saved game with the one or two
    played since. So a load that failed on anything but "there is no
    file yet" blocks writing until the process is restarted, which is
    the thing to do anyway -- the games it needs are in the file.
    """
    global _save_failing

    if _load_unreadable and GAMES_FILE.exists():
        if not _save_failing:
            LOGGER.error(
                "Not saving D12 Ball games over %s, which this run could "
                "not read: restart the bot now that it is readable, or "
                "these games are lost.",
                GAMES_FILE,
            )

        _save_failing = True

        return

    serialized_games = {
        game_id: asdict(game)
        for game_id, game in games.items()
    }

    temporary_file = GAMES_FILE.with_suffix(".tmp")

    try:
        DATA_FOLDER.mkdir(parents=True, exist_ok=True)

        with temporary_file.open("w", encoding="utf-8") as file:
            json.dump(serialized_games, file, indent=2)

        temporary_file.replace(GAMES_FILE)
    except OSError as error:
        # The first failure of a run reaches the server, because
        # somebody has to go and remount the drive (or free the disk).
        # The ones behind it are the same fact repeated once or twice a
        # click, so they stay on the console -- see "The level you log
        # at decides who sees it" in CLAUDE.md.
        if _save_failing:
            LOGGER.info("Still could not save D12 Ball games: %s", error)
        else:
            LOGGER.error(
                "Could not save D12 Ball games, so a restart would lose "
                "everything played since the last successful save: %s",
                error,
                exc_info=error,
            )

        _save_failing = True

        return

    if _save_failing:
        LOGGER.info("Saving D12 Ball games again.")

    _save_failing = False