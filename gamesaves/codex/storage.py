"""
Persistence for the Codex bot's games: `data/codex_games.json`, or the
file named.

Copied from `gamesaves/d12ball/storage.py` (docs/codex-bot.md, decision
2), whose docstrings tell the stories behind each guard: the temporary
file renamed over the real one, `save_games` never raising, and the two
per-file failure flags -- a file whose last save failed, and a file that
was there but could not be read, which is never written over. **There is
no legacy migration**: the save format is the contract from step 2 on
(docs/design/codex.md, "The saved fields"), and every field that is
added later comes with its fallback in the record or the match's
`SavedField` table, not with a pass here.
"""

import json
import logging
from dataclasses import fields
from pathlib import Path
from typing import Optional

from codex.game import CodexGame


LOGGER = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_FOLDER = PROJECT_ROOT / "data"
GAMES_FILE = DATA_FOLDER / "codex_games.json"

# The files whose last save failed to reach the disk. Only the first
# failure of a run is worth waking anyone for -- see `save_games`.
_save_failing: set[Path] = set()

# The files that were there but could not be read; `save_games` refuses
# to write over them until the process is restarted.
_load_unreadable: set[Path] = set()


def load_games(path: Optional[Path] = None) -> dict[str, CodexGame]:
    """
    Read the games saved at `path`, the bot's file unless another is
    named -- resolved at call time, so a test that points `GAMES_FILE`
    at a tempdir moves the default too.
    """
    path = GAMES_FILE if path is None else path

    _load_unreadable.discard(path)

    # No `mkdir` here, unlike D12 Ball's: a load that makes the folder
    # would create data/ wherever a cog is built, a test's included, and
    # `save_games` makes it on the first write anyway.
    try:
        file_exists = path.exists()
    except OSError as error:
        # An unreachable folder may still hold a file: assume it does,
        # since coming up empty and saving over it is the one outcome
        # that loses games for good.
        LOGGER.error("Could not reach the Codex save folder: %s", error)
        _load_unreadable.add(path)
        return {}

    if not file_exists:
        return {}

    try:
        with path.open("r", encoding="utf-8") as file:
            raw_data = json.load(file)
    except (json.JSONDecodeError, OSError) as error:
        LOGGER.error("Could not load Codex games from %s: %s", path, error)
        _load_unreadable.add(path)
        return {}

    games: dict[str, CodexGame] = {}
    known_fields = {field.name for field in fields(CodexGame)}

    for game_id, game_data in raw_data.items():
        # A key the record no longer has is a retired field; dropping it
        # keeps the game loading (gamesaves/d12ball/storage.py).
        retired = sorted(set(game_data) - known_fields)
        if retired:
            LOGGER.info(
                "Ignoring retired field(s) %s on saved Codex game %s.",
                ", ".join(retired),
                game_id,
            )
            game_data = {
                key: value for key, value in game_data.items() if key in known_fields
            }

        # One unreadable game must not take the file's others with it.
        try:
            games[game_id] = CodexGame.from_dict(game_data)
        except (TypeError, ValueError, KeyError) as error:
            LOGGER.error("Skipping invalid saved Codex game %s: %s", game_id, error)

    return games


def save_games(
    games: dict[str, CodexGame],
    path: Optional[Path] = None,
) -> None:
    """
    Write the games out to `path` (the bot's file unless another is
    named), and **never raise doing it**: a save is called part-way
    through a click, and a raise there would take the turn down with it
    and invite the click again. The write is a temporary file renamed
    over the real one, so a failure leaves the last good save intact.
    A file this run could not read is never written over.
    """
    path = GAMES_FILE if path is None else path

    if path in _load_unreadable and path.exists():
        if path not in _save_failing:
            LOGGER.error(
                "Not saving Codex games over %s, which this run could not "
                "read: restart the process now that it is readable, or "
                "these games are lost.",
                path,
            )
        _save_failing.add(path)
        return

    serialized_games = {game_id: game.to_dict() for game_id, game in games.items()}

    temporary_file = path.with_suffix(".tmp")

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with temporary_file.open("w", encoding="utf-8") as file:
            json.dump(serialized_games, file, indent=2)
        temporary_file.replace(path)
    except OSError as error:
        if path in _save_failing:
            LOGGER.info("Still could not save Codex games: %s", error)
        else:
            LOGGER.error(
                "Could not save Codex games to %s, so a restart would lose "
                "everything played since the last successful save: %s",
                path,
                error,
                exc_info=error,
            )
        _save_failing.add(path)
        return

    if path in _save_failing:
        LOGGER.info("Saving Codex games to %s again.", path)

    _save_failing.discard(path)
