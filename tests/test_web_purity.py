"""
The web app may not reach past the flow.

Principle 10 in CLAUDE.md, made mechanical the way the model's own two
halves are (`tests/test_model_purity.py`): **nothing under `webapp/`
imports `cogs` or `discord`.** A web frontend that reaches into the
Discord one is not a second frontend over the model, it is a second
frontend over the first, and the first rule it borrowed would be the
end of the exercise.

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


if __name__ == "__main__":
    unittest.main()
