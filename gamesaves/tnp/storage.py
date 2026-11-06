"""
Persistence for TNP's games: `data/tnp_games.json`, or the file named
(docs/tnp-bot.md, decision 2).

The file's handling is `gamekit.storage`'s, shared with D12 Ball and
Codex, whose docstrings tell the stories behind each guard: the
temporary file renamed over the real one, `save_games` never raising,
and the two per-file failure flags -- a file whose last save failed, and
a file that was there but could not be read, which is never written
over. The flags are this module's own, handed in on every call. There
is no legacy migration: the save format is the contract from the first
commit, and a field added later comes with its fallback in its
`SavedField` table.
"""

import logging
from pathlib import Path
from typing import Optional

from gamekit import storage as games_file
from gamekit.storage import DATA_FOLDER, PROJECT_ROOT  # noqa: F401 -- re-exported
from tnp.game import TnpGame


LOGGER = logging.getLogger(__name__)

GAMES_FILE = DATA_FOLDER / "tnp_games.json"

# The files whose last save failed to reach the disk.
_save_failing: set[Path] = set()

# The files that were there but could not be read; `save_games` refuses
# to write over them until the process is restarted.
_load_unreadable: set[Path] = set()


def load_games(path: Optional[Path] = None) -> dict[str, TnpGame]:
    """
    Read the games saved at `path`, the bot's file unless another is
    named -- resolved at call time, so a test that points `GAMES_FILE`
    at a tempdir moves the default too. No folder is made here: a load
    that made one would create data/ wherever a cog is built, a test's
    included. **One unreadable game is logged and skipped**, so it takes
    none of the file's others with it -- and nothing raises out of here,
    which is what keeps a broken TNP save from stopping fool-bot loading
    D12 Ball (decision 2).
    """
    path = GAMES_FILE if path is None else path
    raw_data = games_file.read_games_file(
        path,
        noun="TNP",
        logger=LOGGER,
        load_unreadable=_load_unreadable,
        make_folder=False,
    )
    if not isinstance(raw_data, dict):
        if raw_data is not None:
            LOGGER.error("The TNP games file %s does not hold a table of games.", path)
            _load_unreadable.add(path)
        return {}

    games: dict[str, TnpGame] = {}
    for game_id, game_data in raw_data.items():
        try:
            games[game_id] = TnpGame.from_dict(game_data)
        except (TypeError, ValueError, KeyError, AttributeError) as error:
            LOGGER.error("Skipping invalid saved TNP game %s: %s", game_id, error)
    return games


def save_games(games: dict[str, TnpGame], path: Optional[Path] = None) -> None:
    """Write the games out to `path` (the bot's file unless another is
    named), and **never raise doing it** -- `gamekit.storage.save_games`,
    with this module's two flag sets."""
    games_file.save_games(
        games,
        GAMES_FILE if path is None else path,
        noun="TNP",
        logger=LOGGER,
        save_failing=_save_failing,
        load_unreadable=_load_unreadable,
    )
