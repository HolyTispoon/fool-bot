#!/usr/bin/env python3
"""Serve the Codex games' site locally, as Cloudflare Pages would.

`pbd/public/` as Pages serves it -- `index.html` at `/`, `game.html` at
`/game` and its `.html` name redirected there, `_redirects`' rewrites
and `_headers`' headers -- and `/data/<key>` answered from a folder in
the bucket's layout (`<dir>/codex/...`), refusing every key the site's
Function refuses, read off the Function's own patterns
(docs/design/pbd-site.md, "The page"):

    python3 scripts/serve_pbd.py --data /tmp/pbd-bucket
    # then open http://127.0.0.1:8788/

Nothing here is deployed; Pages and the Function are the real thing.
"""

from __future__ import annotations

import argparse
import hashlib
import re
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SITE = PROJECT_ROOT / "pbd"
PUBLIC = SITE / "public"
FUNCTION = SITE / "functions" / "data" / "[[path]].js"

#: A line of the Function's KEYS: a JavaScript regex literal.
_PATTERN_LINE = re.compile(r"^\s*/(\^.*\$)/,?\s*$")

#: The objects' types and Cache-Control, by extension and kind, as the
#: publisher puts them (cogs/codex_publish/keys.py).
TYPES = {".json": "application/json; charset=utf-8", ".webp": "image/webp", ".png": "image/png"}


def function_patterns(function: Path = FUNCTION) -> list[re.Pattern]:
    """The Function's key patterns, compiled as Python regexes: the lines
    between `// KEYS BEGIN` and `// KEYS END` that are regex literals."""
    text = function.read_text(encoding="utf-8")
    block = text.split("// KEYS BEGIN", 1)[1].split("// KEYS END", 1)[0]
    found = [_PATTERN_LINE.match(line) for line in block.splitlines()]
    return [re.compile(match.group(1)) for match in found if match]


def answered(key: str, patterns: list[re.Pattern]) -> bool:
    """Whether the Function answers `/data/<key>` at all."""
    return any(pattern.search(key) for pattern in patterns)


def redirect_rules(public: Path = PUBLIC) -> list[tuple[str, str, int]]:
    """`_redirects`, as (from, to, status) rows."""
    rules = []
    for line in (public / "_redirects").read_text(encoding="utf-8").splitlines():
        parts = line.split("#", 1)[0].split()
        if len(parts) >= 2:
            rules.append((parts[0], parts[1], int(parts[2]) if len(parts) > 2 else 302))
    return rules


def header_rules(public: Path = PUBLIC) -> list[tuple[str, list[tuple[str, str]]]]:
    """`_headers`, as (path pattern, [(name, value)]) blocks."""
    blocks: list[tuple[str, list[tuple[str, str]]]] = []
    for line in (public / "_headers").read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line[0].isspace():
            blocks.append((line.strip(), []))
        elif blocks and ":" in line:
            name, value = line.strip().split(":", 1)
            blocks[-1][1].append((name.strip(), value.strip()))
    return blocks


def _rule_pattern(source: str) -> re.Pattern:
    """A `_redirects` or `_headers` path, `:name` and `*` as wildcards."""
    pattern = re.escape(source).replace(r"\*", "(?P<splat>.*)")
    pattern = re.sub(r":(\w+)", r"(?P<\1>[^/]+)", pattern)
    return re.compile(f"^{pattern}$")


def rewrite(path: str, rules: list[tuple[str, str, int]]) -> tuple[str, int] | None:
    """The first rule matching `path`: its target and status."""
    for source, target, status in rules:
        match = _rule_pattern(source).match(path)
        if match:
            for name, value in match.groupdict().items():
                target = target.replace(":splat" if name == "splat" else f":{name}", value)
            return target, status
    return None


def cache_control(key: str) -> str:
    if key.endswith(".json"):
        return "no-cache"
    if key.startswith("codex/emoji/"):
        return "public, max-age=86400"
    return "public, max-age=31536000, immutable"


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, data: Path, patterns, rules, headers, **kwargs):
        self.data, self.patterns, self.rules, self.headers_rules = data, patterns, rules, headers
        super().__init__(*args, directory=str(PUBLIC), **kwargs)

    def end_headers(self) -> None:
        path = urlsplit(self.path).path
        for source, pairs in self.headers_rules:
            if _rule_pattern(source).match(path):
                for name, value in pairs:
                    self.send_header(name, value)
        super().end_headers()

    def do_HEAD(self) -> None:  # noqa: N802 - http.server's name
        self.do_GET()

    def do_GET(self) -> None:  # noqa: N802 - http.server's name
        path = unquote(urlsplit(self.path).path)
        if path.startswith("/data/"):
            return self.serve_data(path[len("/data/"):])
        if path.startswith("/_") or path.endswith(("/_headers", "/_redirects", "/_routes.json")):
            return self.send_error(HTTPStatus.NOT_FOUND)
        rule = rewrite(path, self.rules)
        if rule is not None:
            target, status = rule
            if status != 200:
                return self.redirect(target, status)
            path = target
        # Pages' pretty URLs: /game is game.html, and game.html is sent
        # to /game.
        if path.endswith(".html"):
            pretty = path[:-len(".html")]
            return self.redirect("/" if pretty == "/index" else pretty, 308)
        if path == "/":
            path = "/index.html"
        elif not Path(path).suffix:
            path = f"{path.rstrip('/')}.html"
        self.path = path
        super().do_GET() if self.command == "GET" else super().do_HEAD()

    def redirect(self, target: str, status: int) -> None:
        self.send_response(status)
        self.send_header("Location", target)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def serve_data(self, key: str) -> None:
        if not answered(key, self.patterns):
            return self.send_error(HTTPStatus.NOT_FOUND)
        file = self.data / key
        if not file.is_file():
            return self.send_error(HTTPStatus.NOT_FOUND)
        body = file.read_bytes()
        etag = f'"{hashlib.md5(body).hexdigest()}"'
        if self.headers.get("If-None-Match") == etag:
            self.send_response(HTTPStatus.NOT_MODIFIED)
            self.send_header("ETag", etag)
            self.send_header("X-Robots-Tag", "noindex")
            self.end_headers()
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", TYPES.get(file.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache_control(key))
        self.send_header("ETag", etag)
        self.send_header("X-Robots-Tag", "noindex")
        self.end_headers()
        if self.command == "GET":
            self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", type=Path, required=True,
                        help="A folder in the bucket's layout: <dir>/codex/index.json and so on")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8788)
    args = parser.parse_args()
    handler = partial(Handler, data=args.data.resolve(), patterns=function_patterns(),
                      rules=redirect_rules(), headers=header_rules())
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Serving {PUBLIC} and /data/ from {args.data} at http://{args.host}:{args.port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
