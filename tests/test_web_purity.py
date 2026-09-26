"""
The web app may not reach past the flow, and the bot may not reach
into the web app.

Principle 10 in CLAUDE.md, made mechanical the way the model's own two
halves are (`tests/test_model_purity.py`): **nothing under `webapp/`
imports `cogs` or `discord`.** A web frontend that reaches into the
Discord one is not a second frontend over the model, it is a second
frontend over the first, and the first rule it borrowed would be the
end of the exercise.

**The fence runs both ways** (docs/web-app-next.md, step 1): the two
are separate systems that share the model and nothing at runtime, so
nothing under `cogs/`, and not `foolbot.py`, imports `webapp` -- the
bot must start with the `webapp/` directory deleted. And the web app
never names the bot's games file: `storage`'s default is the bot's, so
the web app passes its own, `WEB_GAMES_FILE`, every time.

The check is the same AST walk `test_model_purity` uses for its
`async def` ratchet -- a read of the source rather than of an import
graph, so it is honest about a lazy import inside a function, which is
exactly where this one would arrive.
"""

from __future__ import annotations

import ast
import pathlib
import unittest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
WEB_ROOT = PROJECT_ROOT / "webapp"
BOT_SOURCES = (PROJECT_ROOT / "foolbot.py", *(PROJECT_ROOT / "cogs").rglob("*.py"))

#: What a frontend may not have of another frontend. `aiohttp` is this
#: one's own business, and `d12ball`, `gamesaves` and `gamelocks` are
#: what it is a frontend over.
FORBIDDEN = ("discord", "cogs")


def imports(tree: ast.AST) -> list[str]:
    """Every module name a file imports, wherever the import sits."""
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


class WebAppPurityTests(unittest.TestCase):
    def test_the_web_app_imports_no_frontend_but_its_own(self) -> None:
        for path in sorted(WEB_ROOT.rglob("*.py")):
            with self.subTest(path.relative_to(PROJECT_ROOT).as_posix()):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                for name in imports(tree):
                    root = name.split(".")[0]
                    self.assertNotIn(
                        root,
                        FORBIDDEN,
                        f"{path.name} imports {name}: the web app is a "
                        "frontend over the model, not over the bot.",
                    )

    def test_there_is_something_to_check(self) -> None:
        """A ratchet over an empty directory ratchets nothing."""
        self.assertGreater(len(list(WEB_ROOT.rglob("*.py"))), 1)
        self.assertGreater(len(BOT_SOURCES), 1)

    def test_the_bot_imports_nothing_of_the_web_app(self) -> None:
        for path in BOT_SOURCES:
            with self.subTest(path.relative_to(PROJECT_ROOT).as_posix()):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                for name in imports(tree):
                    self.assertNotEqual(
                        name.split(".")[0],
                        "webapp",
                        f"{path.name} imports {name}: the bot and the web "
                        "app share the model and nothing else.",
                    )

    def test_the_web_app_never_names_the_bots_games_file(self) -> None:
        for path in sorted(WEB_ROOT.rglob("*.py")):
            with self.subTest(path.relative_to(PROJECT_ROOT).as_posix()):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                named = {
                    node.id for node in ast.walk(tree)
                    if isinstance(node, ast.Name)
                } | {
                    node.attr for node in ast.walk(tree)
                    if isinstance(node, ast.Attribute)
                } | {
                    alias.name for node in ast.walk(tree)
                    if isinstance(node, ast.ImportFrom)
                    for alias in node.names
                }
                self.assertNotIn(
                    "GAMES_FILE",
                    named,
                    f"{path.name} names the bot's games file; the web app "
                    "writes WEB_GAMES_FILE and nothing else.",
                )


if __name__ == "__main__":
    unittest.main()
