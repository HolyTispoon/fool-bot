"""
The little the bot remembers about itself between runs, in
`data/bot_state.json`.

Everything in here exists for one reason: something at startup is
expensive or noisy to repeat, and the only way to know whether it needs
doing at all is to remember what was done last time. Two things
qualify so far -- the build already announced to #logs (see
`botlog/deploy_notice.py`) and the command tree already registered with
Discord (see `foolbot.py`) -- and both are keys in the same file rather
than files of their own, because they are the same kind of fact and
both are written once, in sequence, at startup.

Untracked, and beside `data/d12ball_games.json` for the same reason
that is: it is runtime state, and each machine's is its own. Two
developers deploying the same commit each announce it, and each syncs
their own tree; neither file is the repository's history.

Nothing here raises. A missing, unreadable or corrupt file reads as "no
record", which makes the caller do the work again -- the safe way round
for both callers, since the cost of being wrong is one extra notice or
one extra sync.
"""

import json
from pathlib import Path
from typing import Optional


# The repository the running code was imported from; this module sits
# at the top of it.
REPO_DIR = Path(__file__).resolve().parent

STATE_FILE = REPO_DIR / "data" / "bot_state.json"


def read_key(
    key: str,
    state_file: Optional[Path] = None,
) -> Optional[str]:
    """
    The string stored under `key`, or None when there is nothing usable
    there -- no file, unreadable file, not JSON, not an object, key
    absent, or a value that is not a string.

    `state_file` defaults to STATE_FILE, read here rather than bound as
    the default so that pointing the module at a temporary file in a
    test moves both functions together.
    """
    state_file = STATE_FILE if state_file is None else state_file

    try:
        with state_file.open("r", encoding="utf-8") as file:
            state = json.load(file)
    except (OSError, json.JSONDecodeError):
        return None

    if not isinstance(state, dict):
        return None

    value = state.get(key)

    return value if isinstance(value, str) else None


def write_key(
    key: str,
    value: str,
    state_file: Optional[Path] = None,
) -> None:
    """
    Store `value` under `key`, leaving every other key alone.

    Written through a temporary file, the way the saved games are, so
    an interrupted write cannot leave a truncated file behind -- which
    would read as "no record" and cost a duplicate notice or sync.

    A folder that cannot be written to at all -- a checkout on a drive
    that has been unmounted -- reads the same way round: the record is
    simply not kept, and the next startup does the work again. This is
    on the startup path, and taking `setup_hook` down over a note to
    self would cost the bot rather than the notice.
    """
    state_file = STATE_FILE if state_file is None else state_file

    state: dict[str, object] = {}

    try:
        with state_file.open("r", encoding="utf-8") as file:
            loaded = json.load(file)

        if isinstance(loaded, dict):
            state = loaded
    except (OSError, json.JSONDecodeError):
        state = {}

    state[key] = value
    temporary_file = state_file.with_suffix(".tmp")

    try:
        state_file.parent.mkdir(parents=True, exist_ok=True)

        with temporary_file.open("w", encoding="utf-8") as file:
            json.dump(state, file, indent=2)

        temporary_file.replace(state_file)
    except OSError:
        # Deliberately silent, and deliberately not logged: the one
        # caller that would care is the deploy notice, and the whole
        # point of this file is to keep #logs quiet.
        return
