"""
The Codex games' site (docs/pbd-site.md, step 4; docs/design/pbd-site.md,
"The page"): its files are there, only `/data/*` reaches the Function,
every page is noindex, `/game/<id>` is a rewrite onto a page that is
there, every key the publisher writes is one the Function answers at
`/data/<key>` and nothing else is, and nothing under `landing/` names the site.

The Function's patterns are read out of the `.js` itself
(`scripts/serve_pbd.py`'s `function_patterns`), so the publisher's keys,
the Function and the local server cannot drift apart. What the page looks
like is not tested: it is looked at, at three widths.
"""

import importlib.util
import json
import re
import unittest
from pathlib import Path

from cogs.codex_helpers import TOKEN_EMOJI
from cogs.codex_publish import keys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SITE = PROJECT_ROOT / "pbd"
PUBLIC = SITE / "public"
GAME_ID = "0123456789abcdef0123456789abcdef"

_spec = importlib.util.spec_from_file_location("serve_pbd", PROJECT_ROOT / "scripts" / "serve_pbd.py")
serve_pbd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(serve_pbd)


class FilesTests(unittest.TestCase):
    def test_the_files_are_there(self):
        for name in ("index.html", "game.html", "codex.js", "viewer.js", "codex.css",
                     "_headers", "_redirects", "_routes.json"):
            self.assertTrue((PUBLIC / name).is_file(), name)
        self.assertTrue(serve_pbd.FUNCTION.is_file())

    def test_no_robots_txt(self):
        # A crawler barred from a page never reads its noindex, and a
        # robots.txt prints what it hides (decision 2).
        self.assertFalse((PUBLIC / "robots.txt").exists())

    def test_only_the_data_reaches_the_function(self):
        routes = json.loads((PUBLIC / "_routes.json").read_text())
        self.assertEqual(routes, {"version": 1, "include": ["/data/*"], "exclude": []})

    def test_every_static_file_is_noindex(self):
        self.assertIn(("/*", [("X-Robots-Tag", "noindex")]), serve_pbd.header_rules())

    def test_both_pages_say_noindex(self):
        for name in ("index.html", "game.html"):
            self.assertIn('<meta name="robots" content="noindex">', (PUBLIC / name).read_text(), name)

    def test_the_function_says_noindex(self):
        self.assertIn('"X-Robots-Tag", "noindex"', serve_pbd.FUNCTION.read_text())

    def test_the_game_address_is_a_rewrite_onto_a_page(self):
        rules = serve_pbd.redirect_rules()
        self.assertIn(("/game/:id", "/game", 200), rules)
        target, status = serve_pbd.rewrite(f"/game/{GAME_ID}", rules)
        self.assertEqual((target, status), ("/game", 200))
        # Pages serves game.html at /game.
        self.assertTrue((PUBLIC / f"{target.lstrip('/')}.html").is_file())

    def test_the_pages_name_their_files_by_absolute_path(self):
        for name in ("index.html", "game.html"):
            text = (PUBLIC / name).read_text()
            for asset in ("codex.css", "codex.js"):
                self.assertIn(f'"/{asset}"', text, name)

    def test_no_line_is_built_as_markup(self):
        for name in ("codex.js", "viewer.js"):
            text = (PUBLIC / name).read_text()
            found = re.search(r"\.(innerHTML|outerHTML|insertAdjacentHTML)\b|document\.write", text)
            self.assertIsNone(found, name)


class FunctionKeysTests(unittest.TestCase):
    def setUp(self):
        self.patterns = serve_pbd.function_patterns()

    def test_the_patterns_are_read(self):
        self.assertEqual(len(self.patterns), 6)

    def test_every_key_the_publisher_writes_is_answered(self):
        written = [
            keys.INDEX_KEY,
            keys.ARCHIVE_KEY,
            keys.live_key(GAME_ID),
            keys.history_key(GAME_ID),
            keys.board_key(GAME_ID, b"a board's bytes"),
            *(keys.emoji_key(name) for name in TOKEN_EMOJI.values()),
        ]
        for key in written:
            self.assertTrue(serve_pbd.answered(key, self.patterns), key)

    def test_nothing_else_is(self):
        refused = [
            "",
            "codex/",
            "index.json",
            "codex/codex/index.json",
            "codex/index.json.bak",
            "codex/xindex.json",
            "other/index.json",
            f"codex/games/{GAME_ID}/",
            f"codex/games/{GAME_ID}/other.json",
            f"codex/games/{GAME_ID.upper()}/live.json",
            f"codex/games/{GAME_ID[:-1]}/live.json",
            f"codex/games/../{GAME_ID}/live.json",
            f"codex/games/{GAME_ID}/board-{'a' * 63}.webp",
            f"codex/games/{GAME_ID}/board-{'a' * 64}.png",
            f"codex/games/{GAME_ID}/live.json/extra",
            "codex/emoji/../index.json",
            "codex/emoji/gold.webp",
            "codex/emoji/go-ld.png",
        ]
        for path in refused:
            self.assertFalse(serve_pbd.answered(path, self.patterns), path)


class LandingTests(unittest.TestCase):
    def test_nothing_under_landing_names_the_site(self):
        for file in (PROJECT_ROOT / "landing").rglob("*"):
            if not file.is_file() or file.suffix not in (".py", ".html", ".css", ".js", ".txt", ".md"):
                continue
            text = file.read_text(encoding="utf-8", errors="ignore")
            for name in ("codex-pbd", "pbd/"):
                self.assertNotIn(name, text, file)


if __name__ == "__main__":
    unittest.main()
