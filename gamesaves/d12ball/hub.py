"""
Where each server's D12 Ball game-creation hub lives, in
`data/d12ball_hubs.json`.

The hub is one locked channel carrying a single persistent message with
a "D12 Ball" button (see "The game-creation hub and the lobby" in
CLAUDE.md). `/d12ball setup_hub` registers it; this file is the only
thing that survives a restart, so the button can be re-armed against the
right message. The map is `{guild_id: {"channel_id": int,
"message_id": int}}`.

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
    `{guild_id: {"channel_id": ..., "message_id": ...}}` for every hub
    registered on this machine, or `{}` when there is nothing usable to
    read. Guild ids come back as ints (JSON object keys are strings).
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
            hubs[key] = {
                "channel_id": entry["channel_id"],
                "message_id": entry["message_id"],
            }
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


def set_hub(guild_id: int, channel_id: int, message_id: int) -> None:
    """Register (or move) a guild's hub and write the map back."""
    hubs = load_hubs()
    hubs[guild_id] = {"channel_id": channel_id, "message_id": message_id}
    save_hubs(hubs)


def get_hub(guild_id: int) -> Optional[dict[str, int]]:
    """The hub entry for one guild, or None."""
    return load_hubs().get(guild_id)
