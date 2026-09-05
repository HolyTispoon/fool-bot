"""
Writing a finished game's export to local disk, before `/debug
export_archived_games` deletes its channel -- see "Freeing up the PBD
Archive" in CLAUDE.md.

This module knows nothing about Discord. The cog does the fetching (the
channel, its message history, each attachment's bytes) and hands this
module plain data to write down; that split is what lets a write
failure here be caught and acted on -- a channel must never be deleted
until its export is confirmed on disk -- without this module needing a
`discord.Client` to do it.
"""

import json
import logging
import os
from pathlib import Path
from typing import Optional


LOGGER = logging.getLogger(__name__)

TRANSCRIPT_FILENAME = "transcript.jsonl"
GAME_FILENAME = "game.json"
BOARD_FILENAME = "board.png"
ATTACHMENTS_DIRNAME = "attachments"


def archive_export_dir() -> Optional[Path]:
    """
    Where finished games are exported before their channel is deleted,
    from FOOLBOT_D12BALL_ARCHIVE_EXPORT_DIR.

    Unset or blank means the feature is off, the same opt-in-by-.env
    shape as FOOLBOT_LOG_MIRROR: a fresh checkout should not delete
    anybody's channels just because the command exists, and both
    developers run this bot against their own checkout. For the live
    bot this would point at a folder inside the mounted Google Drive
    letter (see "Two of those machines" in CLAUDE.md) -- there is no
    Google Drive API call anywhere in this bot, so "downloaded to
    Google Drive" means written to a path that Drive itself is already
    syncing, exactly the way the checkout and its saved games already
    reach that drive today.
    """
    raw = os.environ.get("FOOLBOT_D12BALL_ARCHIVE_EXPORT_DIR", "").strip()
    return Path(raw).expanduser() if raw else None


def write_game_export(
    dest: Path,
    *,
    game_data: dict,
    board_png: Optional[bytes],
    transcript: list[dict],
    attachments: list[tuple[str, bytes]],
) -> None:
    """
    Write one game's whole export to `dest`, a folder of its own under
    `archive_export_dir()`.

    Deliberately **raises** on an `OSError` rather than swallowing it
    the way `save_games` does. `save_games` must never take a turn down
    with it, but this runs nowhere near a turn -- it is the one write
    the caller has to know succeeded before it does something
    genuinely irreversible (deleting the channel this data came from),
    so the failure belongs to whoever is about to make that call, not
    to a log line.

    Four files: the game/match record as `save_games` would have
    written it (`game.json`), the final board so a coach can see the
    position without opening the JSON (`board.png`, only when the game
    reached one), every message in the channel in the order it was
    posted (`transcript.jsonl`, one JSON object a line), and the
    attachments those messages carried, under `attachments/` and named
    by the message they came from -- two different turns can each post
    a file called the same thing, so the message id is what keeps them
    from colliding.
    """
    dest.mkdir(parents=True, exist_ok=True)

    game_file = dest / GAME_FILENAME
    temporary_game_file = game_file.with_suffix(".tmp")
    with temporary_game_file.open("w", encoding="utf-8") as file:
        json.dump(game_data, file, indent=2)
    temporary_game_file.replace(game_file)

    if board_png is not None:
        (dest / BOARD_FILENAME).write_bytes(board_png)

    with (dest / TRANSCRIPT_FILENAME).open("w", encoding="utf-8") as file:
        for entry in transcript:
            file.write(json.dumps(entry))
            file.write("\n")

    if attachments:
        attachments_dir = dest / ATTACHMENTS_DIRNAME
        attachments_dir.mkdir(parents=True, exist_ok=True)
        for filename, data in attachments:
            (attachments_dir / filename).write_bytes(data)

    LOGGER.info(
        "Exported D12 Ball game to %s (%d message(s), %d attachment(s)).",
        dest,
        len(transcript),
        len(attachments),
    )
