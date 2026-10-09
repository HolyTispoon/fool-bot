"""
What has to stay true of the two shared packages, `gamekit/` and
`botkit/` (docs/codex-bot.md, step 9; docs/design/codex.md, "What the two
games share").

`gamekit/` is imported by both games' models, so it keeps the model's
rules (CLAUDE.md, "The model and the Discord layer", principle 1): no
`discord`, no `async def`, and no Pillow or reportlab, since the game
imports without them. Both packages are shared *below* the games, so
neither imports either game -- a shared module that reached into one of
them would make the other bot load it. A new ratchet rather than a line
in `tests/test_model_purity.py`, which is one of the six safety-net
tests and is not touched.
"""

import ast
import json
import subprocess
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GAMEKIT = PROJECT_ROOT / "gamekit"
BOTKIT = PROJECT_ROOT / "botkit"

#: The top-level packages a shared module may not import: either game's
#: model, service or frontend.
GAME_PACKAGES = ("d12ball", "codex", "gamesaves", "cogs", "webapp")

PROBE = """
import importlib
import json
import sys

BLOCKED = ("discord", "PIL", "reportlab") + tuple(sys.argv[1].split(","))


class Blocker:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in BLOCKED:
            raise ModuleNotFoundError(f"{name} is blocked", name=name)
        return None


sys.meta_path.insert(0, Blocker())

failures = {}
for module in sys.argv[2:]:
    try:
        importlib.import_module(module)
    except ModuleNotFoundError as exc:
        failures[module] = f"imports {exc.name}"
    except Exception as exc:  # pragma: no cover - a real breakage
        failures[module] = f"{type(exc).__name__}: {exc}"

print(json.dumps(failures))
"""


def modules(root: Path) -> list[str]:
    return [
        ".".join(path.relative_to(PROJECT_ROOT).with_suffix("").parts)
        for path in sorted(root.rglob("*.py"))
    ]


def imported_packages(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split(".")[0])
    return found


class GamekitTests(unittest.TestCase):
    def test_every_module_imports_without_discord_pillow_or_a_game(self) -> None:
        probe = subprocess.run(
            [sys.executable, "-c", PROBE, ",".join(GAME_PACKAGES), *modules(GAMEKIT)],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
            timeout=120,
        )
        self.assertEqual(probe.returncode, 0, probe.stderr)
        self.assertEqual(json.loads(probe.stdout), {})

    def test_nothing_is_async(self) -> None:
        for path in sorted(GAMEKIT.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            with self.subTest(module=path.name):
                self.assertFalse(
                    any(isinstance(node, ast.AsyncFunctionDef) for node in ast.walk(tree)),
                    f"{path.name} defines an async def: the model may not",
                )


class BotkitTests(unittest.TestCase):
    def test_no_module_imports_a_game(self) -> None:
        for path in sorted(BOTKIT.rglob("*.py")):
            with self.subTest(module=path.name):
                self.assertEqual(
                    imported_packages(path) & set(GAME_PACKAGES), set(),
                )


if __name__ == "__main__":
    unittest.main()
