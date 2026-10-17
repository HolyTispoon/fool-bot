#!/usr/bin/env python3
"""Serve the Codex games' site locally, as Cloudflare Pages would.

`pbd/public/` as it stands, with its `_redirects` rewrite and its
`_headers`, and `/data/<key>` answered from a folder in the bucket's
layout, refusing every key the site's Function refuses -- the patterns
are read out of `pbd/functions/data/[[path]].js` itself, so the two
cannot drift (docs/design/pbd-site.md, "Looking at it"):

    python3 scripts/serve_pbd.py --data /tmp/pbd-data

`--stage <dir>` first writes a sample folder there -- three games, one
being played with a history, one finished and one abandoned, through
the publisher's own shapes and boards drawn by `codex.render` -- and
serves it:

    python3 scripts/serve_pbd.py --stage /tmp/pbd-data

Nothing here talks to Cloudflare, and nothing writes into `data/`.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

PUBLIC = PROJECT_ROOT / "pbd" / "public"
FUNCTION = PROJECT_ROOT / "pbd" / "functions" / "data" / "[[path]].js"
DATA_PREFIX = "/data/"

#: A regex literal alone on a line of the Function's `KEYS`.
_PATTERN_LINE = re.compile(r"^\s*/(\^.*\$)/,\s*$")

#: What a file under `pbd/public/` is served as.
TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".js": "text/javascript; charset=utf-8", ".json": "application/json; charset=utf-8",
         ".webp": "image/webp", ".png": "image/png"}


def function_patterns(source: Path = FUNCTION) -> list[re.Pattern]:
    """The keys the Function answers, as Python regexes: each `KEYS`
    entry is a plain literal on a line of its own."""
    return [re.compile(found.group(1))
            for found in map(_PATTERN_LINE.match, source.read_text(encoding="utf-8").splitlines())
            if found]


def answered(key: str, patterns: list[re.Pattern]) -> bool:
    """Whether the Function answers `key`. `fullmatch`, because Python's
    `$` also matches before a final newline and JavaScript's does not."""
    return any(pattern.fullmatch(key) for pattern in patterns)


def read_rules(name: str) -> list[list[str]]:
    """A `_redirects` or `_headers` file as its lines' words, comments
    and blank lines left out."""
    path = PUBLIC / name
    if not path.exists():
        return []
    return [line.split() for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")]


def rewrites() -> list[tuple[re.Pattern, str]]:
    """`_redirects`' 200s, each source's `:name` placeholders as one
    path segment. A 3xx would be a redirect; the site has none."""
    found = []
    for words in read_rules("_redirects"):
        if len(words) >= 3 and words[2] == "200":
            pattern = re.sub(r":[a-z]+", "[^/]+", re.escape(words[0]).replace(r"\:", ":"))
            found.append((re.compile(f"^{pattern}/?$"), words[1]))
    return found


def headers() -> dict[str, str]:
    """`_headers`' headers on `/*`, the only path it names."""
    found, under_all = {}, False
    for line in (PUBLIC / "_headers").read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line[0].isspace():
            under_all = line.strip() == "/*"
        elif under_all and ":" in line:
            name, value = line.split(":", 1)
            found[name.strip()] = value.strip()
    return found


def static_file(path: str) -> Path | None:
    """The file Pages serves at `path`: `/` is `index.html`, `/game` is
    `game.html`, and nothing outside `pbd/public/`."""
    for pattern, target in rewrites():
        if pattern.match(path):
            path = target
            break
    relative = path.lstrip("/")
    candidates = [relative or "index.html", f"{relative}.html", f"{relative}/index.html"]
    for candidate in candidates:
        found = (PUBLIC / candidate).resolve()
        if found.is_file() and PUBLIC.resolve() in found.parents and not found.name.startswith("_"):
            return found
    return None


def make_app(data: Path):
    from aiohttp import web

    patterns = function_patterns()
    extra = headers()

    async def serve(request: web.Request) -> web.StreamResponse:
        path = request.path
        if path.startswith(DATA_PREFIX):
            key = path[len(DATA_PREFIX):]
            target = (data / key).resolve()
            if not answered(key, patterns) or not target.is_file():
                return web.Response(status=404, text="Not found", headers={"X-Robots-Tag": "noindex"})
            body = target.read_bytes()
            etag = f'"{hashlib.md5(body).hexdigest()}"'
            sent = {"ETag": etag, "X-Robots-Tag": "noindex",
                    "Content-Type": TYPES.get(target.suffix, "application/octet-stream"),
                    "Cache-Control": "no-cache" if key.endswith(".json") else "public, max-age=86400"}
            if request.headers.get("If-None-Match") == etag:
                return web.Response(status=304, headers=sent)
            return web.Response(body=body, headers=sent)
        found = static_file(path)
        if found is None:
            return web.Response(status=404, text="Not found", headers=extra)
        return web.Response(body=found.read_bytes(),
                            headers={**extra, "Content-Type": TYPES.get(found.suffix, "application/octet-stream"),
                                     "Cache-Control": "no-cache"})

    app = web.Application()
    app.router.add_route("GET", "/{tail:.*}", serve)
    return app


# -- A sample folder -----------------------------------------------------------


def _sample_module():
    spec = importlib.util.spec_from_file_location("render_codex_sample", PROJECT_ROOT / "scripts" / "render_codex_sample.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def stage(folder: Path) -> list[str]:
    """
    A sample of the bucket in `folder`, written with the publisher's own
    shapes: a duel being played on turn 9 with three finished turns, a
    free-for-all of three finished, and a duel abandoned. Hands back
    the games' ids.
    """
    from codex import tokens
    from codex.engine import RulesEngine
    from codex.formatting import turn_heading
    from codex.game import CodexGame, GameStatus
    from codex.render import render_board
    from cogs.codex_helpers import TOKEN_EMOJI, seat_label
    from cogs.codex_publish import keys, shapes
    from cogs.codex_publish.record import PublishedGame

    engine = RulesEngine(seed=7)
    now = datetime.now(timezone.utc)

    def ago(hours: float) -> str:
        return (now - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")

    sample = _sample_module()

    def write(key: str, body) -> None:
        target = folder / key
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(body, bytes):
            target.write_bytes(body)
        else:
            target.write_text(json.dumps(body, indent=1), encoding="utf-8")

    def seated(number: int, names: list[str], teams: list[str], variant: str = "duel") -> CodexGame:
        game = CodexGame(hashlib.md5(f"sample {number}".encode()).hexdigest(), number, variant=variant)
        for seat, (name, team) in enumerate(zip(names, teams), start=1):
            game.take_seat(1000 + seat, name, [team])
        return game

    def board(game: CodexGame, match) -> tuple[str, bytes]:
        names = {seat: seat_label(game, seat) for seat in range(1, game.seat_count + 1)}
        drawn = render_board(match, game.board_layout, names, engine.catalog, stats=engine.board_reading)
        return keys.board_key(game.game_id, drawn), drawn

    def turn_lines(seat: int, other: int) -> list[str]:
        one, two = tokens.player(seat), tokens.player(other)
        return [
            f"{one} collects {tokens.gold(5)} from 5 workers: now {tokens.gold(5)}.",
            f"{one} hires a worker for {tokens.gold(1)}: 6 workers. {tokens.gold(4)} left.",
            f"{one} plays {tokens.card('iron_man')} 3/4 for {tokens.gold(2)}. {tokens.gold(2)} left.",
            f"{one} attacks {two}'s base with {tokens.card('iron_man')} {tokens.exhaust()}: "
            f"{tokens.card('nimble_fencer')} blocks {tokens.target()} and is destroyed.",
            f"{one} patrols with {tokens.hero('troq_bashar')} as squad leader. "
            f"{one} discards 3 and draws 5. **End of turn** -- {one}.",
        ]

    ids = []

    # Being played: Bashing against Finesse, turn 9, three turns behind it.
    game = seated(12, ["basher", "fencer <b>not bold</b>"], ["bashing", "finesse"])
    game.status = GameStatus.PLAYING
    opening = engine.new_match(("bashing", "finesse"), first=1)
    middle = sample.staged(engine)
    game.match_state = middle.to_dict()
    history, boards = [], {}
    for turn, match in ((6, opening), (7, opening), (8, middle)):
        key, drawn = board(game, match)
        boards[key] = drawn
        seat = 1 if turn % 2 else 2
        history.append({"turn": turn, "heading": f"**Turn {turn}** -- {tokens.addressed(seat)} ({'Bashing' if seat == 1 else 'Finesse'})",
                        "lines": turn_lines(seat, 3 - seat), "board": key})
    key, drawn = board(game, middle)
    boards[key] = drawn
    published = PublishedGame(
        turn=middle.turn, heading=turn_heading(middle),
        lines=turn_lines(1, 2)[:4] + [f"{tokens.player(1)} opens {tokens.codex()} and *thinks* about **Tech II**."],
        history=history, board=key, history_version=3, updated=ago(0.2),
    )
    for key, drawn in boards.items():
        write(key, drawn)
    write(keys.live_key(game.game_id), shapes.live(game, middle, published))
    write(keys.history_key(game.game_id), shapes.history(game, published))
    playing = [shapes.index_entry(game, middle, published.updated)]
    ids.append(game.game_id)

    # Finished: a free-for-all of three, won by seat 2.
    archived = []
    finished = seated(9, ["ann", "bo", "cy"], ["bashing", "finesse", "bashing"], variant="free_for_all")
    finished.status = GameStatus.FINISHED
    match = engine.new_match(("bashing", "finesse", "bashing"), first=1, variant="free_for_all")
    match.turn, match.winner = 21, 2
    finished.match_state = match.to_dict()
    key, drawn = board(finished, match)
    write(key, drawn)
    published = PublishedGame(turn=21, heading=turn_heading(match),
                              lines=[f"{tokens.player(2)} destroys {tokens.player(3)}'s base. {tokens.player(2)} wins."],
                              board=key, history_version=0, updated=ago(30))
    write(keys.live_key(finished.game_id), shapes.live(finished, match, published))
    write(keys.history_key(finished.game_id), shapes.history(finished, published))
    archived.append(shapes.archive_entry(finished, match, published.updated))
    ids.append(finished.game_id)

    # Abandoned on turn 4.
    abandoned = seated(7, ["dee", "eli"], ["finesse", "bashing"])
    abandoned.status = GameStatus.ABANDONED
    match = engine.new_match(("finesse", "bashing"), first=1)
    match.turn = 4
    abandoned.match_state = match.to_dict()
    key, drawn = board(abandoned, match)
    write(key, drawn)
    published = PublishedGame(turn=4, heading=turn_heading(match), lines=[], board=key,
                              updated=ago(100))
    write(keys.live_key(abandoned.game_id), shapes.live(abandoned, match, published))
    write(keys.history_key(abandoned.game_id), shapes.history(abandoned, published))
    archived.append(shapes.archive_entry(abandoned, match, published.updated))
    ids.append(abandoned.game_id)

    write(keys.INDEX_KEY, shapes.index(playing))
    write(keys.ARCHIVE_KEY, shapes.archive(archived))
    for name in set(TOKEN_EMOJI.values()):
        write(keys.emoji_key(name), (PROJECT_ROOT / "codex" / "images" / "emoji" / f"{name}.png").read_bytes())
    return ids


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    where = parser.add_mutually_exclusive_group(required=True)
    where.add_argument("--data", type=Path, help="A folder in the bucket's layout, served at /data/")
    where.add_argument("--stage", type=Path, help="Write a sample folder here first, then serve it")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8788)
    arguments = parser.parse_args()

    data = arguments.data or arguments.stage
    if arguments.stage is not None:
        if data.exists():
            shutil.rmtree(data / "codex", ignore_errors=True)
        for game_id in stage(data):
            print(f"http://{arguments.host}:{arguments.port}/game/{game_id}")

    from aiohttp import web

    print(f"Serving pbd/public/ and {data} at http://{arguments.host}:{arguments.port}/")
    web.run_app(make_app(data.resolve()), host=arguments.host, port=arguments.port, print=None)


if __name__ == "__main__":
    main()
