"""
Writing a finished game's export to local disk, before `/debug
export_archived_games` deletes its channel -- see "Freeing up the PBD
Archive" in docs/design/channels-and-archive.md.

This module knows nothing about Discord. The cog does the fetching (the
channel, its message history, each attachment's bytes) and hands this
module plain data to write down; that split is what lets a write
failure here be caught and acted on -- a channel must never be deleted
until its export is confirmed on disk -- without this module needing a
`discord.Client` to do it.
"""

import html
import json
import re
import logging
import os
from pathlib import Path
from typing import Optional


LOGGER = logging.getLogger(__name__)

TRANSCRIPT_FILENAME = "transcript.jsonl"
TRANSCRIPT_PAGE_FILENAME = "transcript.html"
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
    letter (see "Two of those machines" in docs/design/collaboration.md) -- there is no
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

    Five files. `transcript.html` is the one anybody opens: the game's
    summary, its goal log, the final board and every message with its
    images shown rather than named. The other four are the record it is
    rendered from -- the game/match record as `save_games` would have
    written it (`game.json`), the final board (`board.png`, only when
    the game reached one), every message in the order it was posted
    (`transcript.jsonl`, one JSON object a line, lossless and meant for
    a machine), and the attachments those messages carried, under
    `attachments/` and named by the message they came from, since two
    turns can each post a file called the same thing.

    **The folder is the unit**, because the page references its images
    by relative path. Inlining them as data URIs would put a hundred
    board renders in one file, which is hundreds of megabytes no
    browser opens happily -- and the images are the whole reason the
    page is worth having.
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

    # The one file in here a person opens. JSONL is the lossless record
    # and unreadable without a tool; this is the same messages, in the
    # same order, with the board renders shown instead of named. Both
    # are written from the same list in the same call, so they cannot
    # come to disagree about what the channel said.
    (dest / TRANSCRIPT_PAGE_FILENAME).write_text(
        render_transcript_html(game_data, transcript, board_png is not None),
        encoding="utf-8",
    )

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


# What the browser will show inline rather than link to. A game channel
# is mostly board renders and card images, so inlining them is most of
# what makes the page readable at all.
INLINE_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp")

# The suffix MatchState puts on a visiting card when both sides field
# the same player -- see "One player, both sides" in docs/design/teams-and-players.md. Spelled
# out here rather than imported: this module writes files and knows
# nothing about the game model, and a prettified name that gets this
# wrong is cosmetic, where an import would tie the exporter to the
# model's own loading.
DUPLICATE_CARD_MARK = "~2"


def plain(value: object) -> str:
    """
    A value as it reads, not as it reprs.

    `game.to_dict()` is `dataclasses.asdict`, which leaves enum
    *members* in place -- `json.dump` writes `Team.ORANGE` out as
    "orange" because it is a `str, Enum`, but `str()` on it gives
    "Team.ORANGE". So a page built off the dict in memory says
    `GameStatus.FINISHED` where the same page built off the file says
    "finished". Caught by looking at a real export rather than by a
    test, whose fixture had honest strings in it.
    """
    return str(getattr(value, "value", value))


# The slice of Discord's markdown the bot actually writes. Its messages
# are full of **bold**, and a page that prints the asterisks is a page
# that reads worse than the channel it replaced. Applied *after* the
# text is HTML-escaped, so markup somebody typed stays escaped and only
# these patterns ever become tags.
MARKDOWN_PATTERNS = (
    (re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", re.S), r"<strong>\1</strong>"),
    (re.compile(r"__(?=\S)(.+?)(?<=\S)__", re.S), r"<u>\1</u>"),
    (re.compile(r"`([^`\n]+)`"), r"<code>\1</code>"),
    (re.compile(r"(?<![*\w])\*(?=\S)([^*\n]+?)(?<=\S)\*(?!\*)"), r"<em>\1</em>"),
)


def render_message_content(content: str) -> str:
    """
    One message's text as HTML: escaped first, then the handful of
    markdown patterns above turned into tags.

    Escaping first is the whole of the safety here. Every message is
    somebody's typing and this page is opened straight off disk with
    nothing sandboxing it, so `<script>` has already become `&lt;script&gt;`
    by the time any pattern is applied, and no pattern can put back a
    tag the escape took out.
    """
    rendered = html.escape(content, quote=True)

    for pattern, replacement in MARKDOWN_PATTERNS:
        rendered = pattern.sub(replacement, rendered)

    return rendered


def prettify_player_id(player_id: str) -> str:
    """
    `hellguard_fullback` -> `Hellguard (Fullback)`, and the visiting
    copy of a shared player as `Hellguard (Fullback, 2nd)`.

    Deliberately a string transform and not a catalog lookup. The exact
    ids are in game.json and transcript.jsonl either way, so the worst
    a wrong guess here can do is read oddly in a summary -- where a
    lookup would make writing an export depend on loading the player
    catalog, and would fail outright on a game whose roster has since
    been reshuffled. That is precisely the failure this file exists to
    avoid: an export is written once, and has to still open in a year.
    """
    duplicate = player_id.endswith(DUPLICATE_CARD_MARK)
    if duplicate:
        player_id = player_id[: -len(DUPLICATE_CARD_MARK)]

    name, _, role = player_id.rpartition("_")

    if not name:
        return player_id

    label = f"{name.replace('_', ' ').title()} ({role.title()}"
    return f"{label}, 2nd)" if duplicate else f"{label})"


def summarise_game(game_data: dict) -> list[tuple[str, str]]:
    """
    The handful of facts about a game worth reading, as label/value
    pairs for the page's header.

    Every read is defensive. This has to cope with a game abandoned
    during setup (no match state at all), a game saved before a field
    existed, and whatever shape a future save takes -- an export that
    raises is an export that does not get written, and the channel it
    came from is about to be deleted.
    """
    match_state = game_data.get("match_state") or {}
    scoreboard = match_state.get("scoreboard") or {}

    home_number = game_data.get("home_player_number")
    names = {
        1: game_data.get("player_1_name") or "Player 1",
        2: game_data.get("player_2_name") or "Player 2",
    }
    teams = {
        1: game_data.get("player_1_team"),
        2: game_data.get("player_2_team"),
    }

    def side_label(number: Optional[int]) -> str:
        if number not in names:
            return "unknown"
        team = teams.get(number)
        return f"{names[number]} ({plain(team)})" if team else names[number]

    visiting_number = 2 if home_number == 1 else 1 if home_number == 2 else None

    rows = [
        ("Game", f"PBD{game_data.get('game_number', '?')}"),
        ("Name", game_data.get("game_name") or "--"),
        ("Home", side_label(home_number)),
        ("Visitors", side_label(visiting_number)),
        ("Mode", plain(game_data.get("mode") or "--")),
        ("Board", plain(game_data.get("board_size") or "--")),
        ("Status", plain(game_data.get("status") or "--")),
    ]

    if game_data.get("abandoned"):
        # A scoreboard read off a game nobody finished is a result
        # nobody earned -- see "The event log" in docs/design/clock-and-records.md.
        rows.append(("Result", "Abandoned before full time"))
    elif scoreboard:
        rows.append((
            "Final score",
            f"{scoreboard.get('home_score', 0)} - "
            f"{scoreboard.get('visiting_score', 0)}",
        ))
        rows.append((
            "Clock",
            f"{scoreboard.get('time', 0):02d}, "
            f"{plain(scoreboard.get('period', '')).replace('_', ' ')}",
        ))

    return rows


def describe_goals(game_data: dict) -> list[str]:
    """
    The goal log as sentences -- who scored, for whom, and when.

    An own goal is stored as two facts and reads as one line: `side` is
    who it counted for and `player_id` is the defender who put it in,
    which is the one line of a scoresheet where the name and the column
    disagree. See "The goal log" in docs/design/clock-and-records.md.
    """
    match_state = game_data.get("match_state") or {}
    lines = []

    for goal in match_state.get("goals") or []:
        if not isinstance(goal, dict):
            continue

        scorer = prettify_player_id(plain(goal.get("player_id", "")))
        side = plain(goal.get("side", "")).replace("_", " ")
        marks = []

        if goal.get("own_goal"):
            marks.append("own goal")
        if goal.get("shootout"):
            marks.append("shootout")

        # A shootout goal has no minute and no run of play, so it is
        # not stamped with whatever the clock stopped on.
        when = (
            "shootout"
            if goal.get("shootout")
            else f"{goal.get('time', 0):02d} "
            f"({plain(goal.get('period', '')).replace('_', ' ')})"
        )
        suffix = f" [{', '.join(marks)}]" if marks else ""
        lines.append(f"{when} -- {scorer} for {side}{suffix}")

    return lines


def render_transcript_html(
    game_data: dict,
    transcript: list[dict],
    has_board: bool,
) -> str:
    """
    The export a person actually opens: one self-contained HTML page
    with the game's summary, its goals, the final board and every
    message in the order it was posted, with the images shown rather
    than named.

    `transcript.jsonl` stays beside it and is still the lossless record
    -- this page drops nothing but is shaped for reading, and a machine
    should parse the JSON. The two are written from the same list in
    the same call, so they cannot disagree.

    Attachments are referenced by relative path, so the export folder
    is the unit that has to be kept together. That is deliberate: the
    alternative is a base64 page holding a hundred board renders, which
    is hundreds of megabytes of one file that no browser opens happily.
    """
    def escape(value: object) -> str:
        return html.escape(str(value), quote=True)

    title = (
        f"PBD{game_data.get('game_number', '?')}"
        + (f" - {game_data['game_name']}" if game_data.get("game_name") else "")
    )

    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{escape(title)}</title>",
        "<style>",
        ":root{color-scheme:light dark}",
        "body{font:16px/1.55 system-ui,sans-serif;margin:0 auto;padding:24px;"
        "max-width:52rem}",
        "h1{font-size:1.5rem;margin:0 0 .25rem}",
        "h2{font-size:1.1rem;margin:2rem 0 .5rem;"
        "border-bottom:1px solid #8883;padding-bottom:.25rem}",
        "dl{display:grid;grid-template-columns:max-content 1fr;gap:.15rem .75rem;"
        "margin:.5rem 0}",
        "dt{font-weight:600;opacity:.75}dd{margin:0}",
        "ol.goals{margin:.5rem 0;padding-left:1.25rem}",
        ".msg{padding:.6rem 0;border-top:1px solid #8882}",
        ".meta{font-size:.8rem;opacity:.65}",
        ".author{font-weight:600;opacity:1}",
        ".content{white-space:pre-wrap;overflow-wrap:anywhere;margin:.2rem 0}",
        ".files{margin:.4rem 0 0}",
        ".files img{max-width:100%;height:auto;border-radius:6px;"
        "display:block;margin:.4rem 0}",
        ".empty{opacity:.6;font-style:italic}",
        "</style></head><body>",
        f"<h1>{escape(title)}</h1>",
        '<p class="meta">Exported from the PBD Archive before the channel '
        "was deleted. The files beside this page are the same game as "
        "JSON.</p>",
        "<h2>Game</h2><dl>",
    ]

    for label, value in summarise_game(game_data):
        parts.append(f"<dt>{escape(label)}</dt><dd>{escape(value)}</dd>")

    parts.append("</dl>")

    goals = describe_goals(game_data)
    if goals:
        parts.append("<h2>Goals</h2><ol class='goals'>")
        parts.extend(f"<li>{escape(goal)}</li>" for goal in goals)
        parts.append("</ol>")

    if has_board:
        parts.append("<h2>Final board</h2>")
        parts.append(
            f'<img src="{BOARD_FILENAME}" alt="The final board position">'
        )

    parts.append(f"<h2>Channel ({len(transcript)} messages)</h2>")

    if not transcript:
        parts.append('<p class="empty">No messages were readable.</p>')

    for entry in transcript:
        parts.append('<div class="msg">')
        parts.append(
            '<div class="meta"><span class="author">'
            f"{escape(entry.get('author', 'unknown'))}</span> &middot; "
            f"{escape(entry.get('created_at', ''))}</div>"
        )

        content = entry.get("content") or ""
        if content:
            parts.append(
                f'<div class="content">{render_message_content(content)}</div>'
            )

        files = entry.get("attachments") or []
        if files:
            parts.append('<div class="files">')
            for filename in files:
                href = f"{ATTACHMENTS_DIRNAME}/{filename}"
                if filename.lower().endswith(INLINE_IMAGE_SUFFIXES):
                    parts.append(
                        f'<img src="{escape(href)}" '
                        f'alt="{escape(filename)}" loading="lazy">'
                    )
                else:
                    parts.append(
                        f'<a href="{escape(href)}">{escape(filename)}</a>'
                    )
            parts.append("</div>")

        if not content and not files:
            parts.append('<div class="empty">(no text)</div>')

        parts.append("</div>")

    parts.append("</body></html>")

    return "\n".join(parts)
