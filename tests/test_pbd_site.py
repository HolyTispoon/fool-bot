"""
The Codex games' site (docs/pbd-site.md, step 4): the files Pages serves
are there, only `/data/*` reaches the Function, every page and answer
carries the noindex, the game's address is a rewrite onto a page that
exists, the Function's key patterns answer every key the publisher
writes and nothing else, and neither landing site names the site.

Nothing here runs the JavaScript; the page is looked at, through
`scripts/serve_pbd.py` (docs/design/pbd-site.md, "Looking at it").
"""

import importlib.util
import json
import re
import unittest
from pathlib import Path

from codex.game import MODES, VARIANT_LABELS, VARIANTS
from cogs.codex_views.lobby import MODE_LABELS
from cogs.codex_publish import cards, keys

ROOT = Path(__file__).resolve().parents[1]
PBD = ROOT / "pbd"
PUBLIC = PBD / "public"
FUNCTION = PBD / "functions" / "data" / "[[path]].js"
GAME_ID = "0123456789abcdef0123456789abcdef"


def load_server():
    path = ROOT / "scripts" / "serve_pbd.py"
    spec = importlib.util.spec_from_file_location("serve_pbd", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rules(name: str) -> list[list[str]]:
    return [line.split() for line in (PUBLIC / name).read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")]


class FilesTests(unittest.TestCase):
    def test_the_files_are_there(self):
        for name in ("index.html", "game.html", "codex.js", "viewer.js", "codex.css",
                     "_headers", "_redirects", "_routes.json"):
            self.assertTrue((PUBLIC / name).is_file(), name)
        self.assertTrue(FUNCTION.is_file())

    def test_only_the_data_reaches_the_function(self):
        routes = json.loads((PUBLIC / "_routes.json").read_text(encoding="utf-8"))
        self.assertEqual(routes, {"version": 1, "include": ["/data/*"], "exclude": []})

    def test_every_page_is_noindex(self):
        lines = (PUBLIC / "_headers").read_text(encoding="utf-8").splitlines()
        self.assertIn("/*", [line.strip() for line in lines if line and not line[0].isspace()])
        self.assertIn("X-Robots-Tag: noindex", [line.strip() for line in lines])
        for page in ("index.html", "game.html"):
            self.assertIn('<meta name="robots" content="noindex">', (PUBLIC / page).read_text(encoding="utf-8"))
        self.assertFalse((PUBLIC / "robots.txt").exists())
        self.assertIn('"X-Robots-Tag", "noindex"', FUNCTION.read_text(encoding="utf-8"))

    def test_the_game_address_is_a_rewrite_onto_the_game_page(self):
        (rewrite,) = rules("_redirects")
        self.assertEqual(rewrite, ["/game/:id", "/game", "200"])
        self.assertTrue((PUBLIC / "game.html").is_file())

    def test_the_pages_name_their_files_by_absolute_path(self):
        for page in ("index.html", "game.html"):
            text = (PUBLIC / page).read_text(encoding="utf-8")
            for found in re.findall(r'(?:src|href)="([^"]+)"', text):
                self.assertTrue(found.startswith("/"), f"{page}: {found}")

    def test_no_line_is_markup(self):
        for name in ("codex.js", "viewer.js"):
            self.assertNotIn("innerHTML", (PUBLIC / name).read_text(encoding="utf-8"), name)

    def test_modes_and_variants_are_named_as_the_bot_names_them(self):
        text = (PUBLIC / "codex.js").read_text(encoding="utf-8")
        for mode in MODES:
            self.assertIn(f'{mode}: "{MODE_LABELS[mode]}"', text)
        for variant in VARIANTS:
            self.assertIn(f'{variant}: "{VARIANT_LABELS[variant]}"', text)


class FunctionPatternsTests(unittest.TestCase):
    def setUp(self):
        self.server = load_server()
        self.patterns = self.server.function_patterns(FUNCTION)

    def test_every_key_the_publisher_writes_is_answered(self):
        written = [
            keys.INDEX_KEY,
            keys.ARCHIVE_KEY,
            keys.live_key(GAME_ID),
            keys.history_key(GAME_ID),
            keys.board_key(GAME_ID, b"a board"),
            keys.board_map_key(keys.board_key(GAME_ID, b"a board")),
            keys.emoji_key("gold"),
            keys.emoji_key("codex_exhaust"),
            cards.key("brick_thief"),
            cards.key("squirrel"),
            cards.key("tech_ii_building"),
        ]
        self.assertEqual(len(self.patterns), 8)
        for key in written:
            self.assertTrue(self.server.answered(key, self.patterns), key)

    def test_no_other_key_is_answered(self):
        refused = [
            "", "codex/", "index.json", "codex/index.json.bak", "codex/other.json",
            "pbd/codex/index.json", f"codex/games/{GAME_ID}/", f"codex/games/{GAME_ID}/notes.json",
            "codex/games/12/live.json", f"codex/games/{GAME_ID.upper()}/live.json",
            f"codex/games/{GAME_ID}x/live.json", f"codex/games/{GAME_ID}/board-abc.webp",
            f"codex/games/{GAME_ID}/board-{'0' * 64}.png",
            "codex/games/../index.json", "codex/emoji/../index.json", "codex/emoji/a-b.png",
            "codex/emoji/gold.webp", f"codex/games/{GAME_ID}/live.json\n",
            f"codex/games/{GAME_ID}/board-abc.json", "codex/cards/Brick_Thief.jpg",
            "codex/cards/brick-thief.jpg", "codex/cards/brick_thief.webp",
            "codex/cards/../index.json", "codex/cards/brick_thief.jpg.json",
        ]
        for key in refused:
            self.assertFalse(self.server.answered(key, self.patterns), repr(key))


class ServerTests(unittest.TestCase):
    def test_the_rewrite_and_the_pages(self):
        server = load_server()
        self.assertEqual(server.static_file(f"/game/{GAME_ID}"), (PUBLIC / "game.html").resolve())
        self.assertEqual(server.static_file("/"), (PUBLIC / "index.html").resolve())
        self.assertEqual(server.static_file("/codex.js"), (PUBLIC / "codex.js").resolve())
        self.assertIsNone(server.static_file("/_headers"))
        self.assertIsNone(server.static_file("/../README.md"))
        self.assertEqual(server.headers(), {"X-Robots-Tag": "noindex"})


class LandingTests(unittest.TestCase):
    def test_no_landing_site_names_the_site(self):
        for path in (ROOT / "landing").rglob("*"):
            if path.is_file() and path.suffix in (".py", ".html", ".css", ".js", ".txt", ".md", ""):
                text = path.read_text(encoding="utf-8", errors="ignore")
                self.assertNotIn("codex-pbd", text, path)
                self.assertNotIn("pbd/", text, path)


if __name__ == "__main__":
    unittest.main()
