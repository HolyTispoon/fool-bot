#!/usr/bin/env python3
"""Backfill transcript.html for archive exports written before that page
existed -- see "Export a page a person can read" in the git log of
gamesaves/d12ball/archive_export.py. Those older exports still have
game.json (and usually transcript.jsonl and board.png); this rebuilds
transcript.html from exactly those files, off disk, with no bot process
or live Discord channel involved.

    python3 scripts/backfill_archive_html.py /path/to/export/dir
    python3 scripts/backfill_archive_html.py            # uses .env's
                                                          # FOOLBOT_D12BALL_ARCHIVE_EXPORT_DIR

A game played against the Dinky AI is skipped by default -- pass
--include-dinky to rebuild those too. A folder that already has a
transcript.html is left alone -- pass --force to rebuild it anyway.
"""
import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from gamesaves.d12ball.archive_export import (  # noqa: E402
    BOARD_FILENAME,
    GAME_FILENAME,
    TRANSCRIPT_FILENAME,
    TRANSCRIPT_PAGE_FILENAME,
    archive_export_dir,
    render_transcript_html,
)
from gamesaves.d12ball.storage import migrate_legacy_game_data  # noqa: E402


def is_dinky_game(game_data: dict) -> bool:
    """
    True for a solo game against the easy AI. `ai_opponent` says so
    directly on any game saved after that field existed; a game from
    before it -- `player_2_id` unset and the legacy `coin_winner` string
    "the Dinky AI", the same fallback `D12BallGame.__post_init__` reads
    to backfill `coin_winner_player_number` -- is Dinky too.
    """
    if game_data.get("ai_opponent") == "dinky":
        return True
    return (
        game_data.get("player_2_id") is None
        and game_data.get("coin_winner") == "the Dinky AI"
    )


def load_transcript(dest: Path) -> list[dict]:
    transcript_file = dest / TRANSCRIPT_FILENAME
    if not transcript_file.exists():
        return []

    entries = []
    with transcript_file.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "export_dir",
        nargs="?",
        type=Path,
        help="The archive export directory (default: "
        "FOOLBOT_D12BALL_ARCHIVE_EXPORT_DIR from .env).",
    )
    parser.add_argument(
        "--include-dinky",
        action="store_true",
        help="Also rebuild games played against the Dinky AI.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild transcript.html even for a folder that already has one.",
    )
    args = parser.parse_args()

    if args.export_dir is None:
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass
    export_dir = args.export_dir or archive_export_dir()
    if export_dir is None:
        parser.error(
            "No export directory given, and FOOLBOT_D12BALL_ARCHIVE_EXPORT_DIR "
            "is not set."
        )
    if not export_dir.is_dir():
        parser.error(f"{export_dir} is not a directory.")

    rebuilt = skipped_dinky = skipped_other = 0

    for dest in sorted(path for path in export_dir.iterdir() if path.is_dir()):
        game_file = dest / GAME_FILENAME
        if not game_file.exists():
            continue

        game_data = json.loads(game_file.read_text(encoding="utf-8"))
        try:
            # An export from before the 2026-08-17 eight-team reshuffle
            # names players by their old ids; this is the same remap
            # `load_games` applies, so a goal log reads with today's
            # names instead of `prettify_player_id`'s best guess at a
            # retired one. A game already in the new shape comes back
            # untouched.
            game_data = migrate_legacy_game_data(game_data)
        except Exception as error:
            print(f"warn ({dest.name}): legacy id remap failed: {error}")

        if is_dinky_game(game_data) and not args.include_dinky:
            skipped_dinky += 1
            print(f"skip (Dinky): {dest.name}")
            continue

        html_file = dest / TRANSCRIPT_PAGE_FILENAME
        if html_file.exists() and not args.force:
            skipped_other += 1
            print(f"skip (already has transcript.html): {dest.name}")
            continue

        transcript = load_transcript(dest)
        has_board = (dest / BOARD_FILENAME).exists()
        html_file.write_text(
            render_transcript_html(game_data, transcript, has_board),
            encoding="utf-8",
        )
        rebuilt += 1
        print(f"rebuilt: {dest.name}")

    print(
        f"\n{rebuilt} rebuilt, {skipped_dinky} skipped (Dinky), "
        f"{skipped_other} skipped (other)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
