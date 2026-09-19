"""
Where each server's D12 Ball game-creation hub lives, in
`data/d12ball_hubs.json`.

The hub is one locked channel carrying two persistent messages: the
games message with its "D12 Ball" button, and the roles message with a
toggle button per role (see "The game-creation hub and the lobby" in
docs/design/hub-and-lobby.md). `/d12ball setup_hub` registers both; this file is the only
thing that survives a restart, so the buttons can be re-armed against
the right messages. The map is `{guild_id: {"channel_id": int,
"message_id": int, "roles_message_id": int}}`, with `roles_message_id`
absent from an entry written before the roles message existed -- such
a hub re-arms its games button alone until `setup_hub` is run again.

Untracked runtime state, beside `data/d12ball_games.json` and for the
same reason: the message lives in Discord, this is only a local pointer
at it, and each checkout keeps its own. Nothing here raises -- a
missing, unreadable or corrupt file reads as "no hubs", which is the
safe way round (the worst case is an admin re-running `/d12ball
setup_hub`).
"""

import json
import logging
from pathlib import Path
from typing import Optional


LOGGER = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_FOLDER = PROJECT_ROOT / "data"
HUBS_FILE = DATA_FOLDER / "d12ball_hubs.json"


def load_hubs() -> dict[int, dict[str, int]]:
    """
    `{guild_id: {"channel_id": ..., "message_id": ...,
    "roles_message_id": ...}}` for every hub registered on this machine,
    or `{}` when there is nothing usable to read. Guild ids come back as
    ints (JSON object keys are strings). `roles_message_id` is carried
    only when the entry has one that is an int.
    """
    try:
        with HUBS_FILE.open("r", encoding="utf-8") as file:
            raw = json.load(file)
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as error:
        LOGGER.error("Could not load D12 Ball hubs: %s", error)
        return {}

    if not isinstance(raw, dict):
        return {}

    hubs: dict[int, dict[str, int]] = {}
    for guild_id, entry in raw.items():
        try:
            key = int(guild_id)
        except (TypeError, ValueError):
            continue
        if (
            isinstance(entry, dict)
            and isinstance(entry.get("channel_id"), int)
            and isinstance(entry.get("message_id"), int)
        ):
            hub = {
                "channel_id": entry["channel_id"],
                "message_id": entry["message_id"],
            }
            if isinstance(entry.get("roles_message_id"), int):
                hub["roles_message_id"] = entry["roles_message_id"]
            hubs[key] = hub
    return hubs


def save_hubs(hubs: dict[int, dict[str, int]]) -> None:
    """
    Write the hub map out through a temporary file, and never raise
    doing it -- a folder that cannot be written to (an unmounted drive,
    the case `gamesaves/d12ball/storage.py` was written for) just leaves
    the record unkept, and the next `/d12ball setup_hub` re-creates it.
    """
    serialized = {
        str(guild_id): entry
        for guild_id, entry in hubs.items()
    }
    temporary_file = HUBS_FILE.with_suffix(".tmp")

    try:
        DATA_FOLDER.mkdir(parents=True, exist_ok=True)
        with temporary_file.open("w", encoding="utf-8") as file:
            json.dump(serialized, file, indent=2)
        temporary_file.replace(HUBS_FILE)
    except OSError as error:
        LOGGER.error("Could not save D12 Ball hubs: %s", error)


def set_hub(
    guild_id: int,
    channel_id: int,
    message_id: int,
    roles_message_id: Optional[int] = None,
) -> dict[str, int]:
    """
    Register (or move) a guild's hub, write the map back, and return
    the entry as written -- the same dict the cog keeps in `self.hubs`.
    """
    hubs = load_hubs()
    entry = {"channel_id": channel_id, "message_id": message_id}
    if roles_message_id is not None:
        entry["roles_message_id"] = roles_message_id
    hubs[guild_id] = entry
    save_hubs(hubs)
    return entry


def get_hub(guild_id: int) -> Optional[dict[str, int]]:
    """The hub entry for one guild, or None."""
    return load_hubs().get(guild_id)
