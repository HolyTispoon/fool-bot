"""
Persistence for the Codex bot's games: `data/codex_games.json`, or the
file named.

The file's handling is `gamekit.storage`'s, shared with D12 Ball
(docs/design/codex.md, "What the two games share"), whose docstrings
tell the stories behind each guard: the temporary file renamed over the
real one, `save_games` never raising, and the two per-file failure flags
-- a file whose last save failed, and a file that was there but could
not be read, which is never written over. The flags are this module's,
handed in on every call. **There is
no legacy migration**: the save format is the contract from step 2 on
(docs/design/codex.md, "The saved fields"), and every field that is
added later comes with its fallback in the record or the match's
`SavedField` table, not with a pass here.
"""

import logging
from dataclasses import fields
from pathlib import Path
from typing import Optional

from codex.game import CodexGame
from gamekit import storage as games_file
from gamekit.storage import DATA_FOLDER, PROJECT_ROOT  # noqa: F401 -- re-exported


LOGGER = logging.getLogger(__name__)

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

    # No folder made here, unlike D12 Ball's: a load that makes the
    # folder would create data/ wherever a cog is built, a test's
    # included, and `save_games` makes it on the first write anyway.
    raw_data = games_file.read_games_file(
        path,
        noun="Codex",
        logger=LOGGER,
        load_unreadable=_load_unreadable,
        make_folder=False,
    )
    if raw_data is None:
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
    named), and **never raise doing it** -- `gamekit.storage.save_games`,
    with this module's two flag sets.
    """
    games_file.save_games(
        games,
        GAMES_FILE if path is None else path,
        noun="Codex",
        logger=LOGGER,
        save_failing=_save_failing,
        load_unreadable=_load_unreadable,
    )
