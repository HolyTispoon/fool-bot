"""
The TNP model's purity ratchet, from step 2 of docs/tnp-bot.md, the
commit with the first rule in it: `tnp/` (and `gamesaves/tnp/`, once
step 4 creates it) imports no `discord` and defines no `async def`;
Pillow is `tnp/render.py`'s alone (step 3); nothing in it imports a
cog; and every draw is `engine.rng`, so only `tnp/engine.py` imports
`random`.

The two import checks run in a fresh interpreter for the reason
`tests/test_model_purity.py` gives -- an in-process check would pass
against modules `unittest discover` already imported -- and reuse its
probes.
"""

import ast
import json
import pathlib
import subprocess
import sys
import unittest

from test_model_purity import DRAWING_PROBE, IMPORT_PROBE, PROJECT_ROOT

TNP_ROOTS = tuple(
    root for root in (PROJECT_ROOT / "tnp", PROJECT_ROOT / "gamesaves" / "tnp") if root.is_dir()
)

#: The one module that may draw.
DRAWING = {PROJECT_ROOT / "tnp" / "render.py"}

#: The one module that may hold a `random.Random`.
RANDOM = {PROJECT_ROOT / "tnp" / "engine.py"}


def tnp_modules() -> list[pathlib.Path]:
    found = []
    for root in TNP_ROOTS:
        found.extend(root.rglob("*.py"))
    return sorted(found)


def module_name(path: pathlib.Path) -> str:
    return ".".join(path.relative_to(PROJECT_ROOT).with_suffix("").parts)


def imported(path: pathlib.Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom):
            yield node.lineno, node.module or ""


class TnpPurityTests(unittest.TestCase):
    def _probe(self, script: str, arguments: list[str]) -> dict:
        probe = subprocess.run(
            [sys.executable, "-c", script, *arguments],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=120,
        )
        self.assertEqual(probe.returncode, 0, f"the probe itself failed:\n{probe.stderr}")
        return json.loads(probe.stdout)

    def test_the_model_imports_without_discord(self) -> None:
        failures = self._probe(IMPORT_PROBE, [str(PROJECT_ROOT), *map(str, TNP_ROOTS)])
        self.assertEqual(failures, {}, f"these TNP modules do not import without discord: {failures}")

    def test_only_render_draws(self) -> None:
        modules = [module_name(path) for path in tnp_modules() if path not in DRAWING]
        failures = self._probe(DRAWING_PROBE, modules)
        self.assertEqual(failures, {}, f"these TNP modules reach a drawing library: {failures}")

    def test_no_async_and_no_cog(self) -> None:
        offenders = []
        for path in tnp_modules():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            offenders.extend(
                f"{path.relative_to(PROJECT_ROOT)}:{node.lineno} async {node.name}"
                for node in ast.walk(tree) if isinstance(node, ast.AsyncFunctionDef)
            )
            offenders.extend(
                f"{path.relative_to(PROJECT_ROOT)}:{line} imports {name}"
                for line, name in imported(path) if name == "cogs" or name.startswith("cogs.")
            )
        self.assertEqual(offenders, [])

    def test_every_draw_is_the_engines(self) -> None:
        offenders = [
            f"{path.relative_to(PROJECT_ROOT)}:{line}"
            for path in tnp_modules() if path not in RANDOM
            for line, name in imported(path) if name == "random"
        ]
        self.assertEqual(offenders, [], "only tnp/engine.py holds a random.Random")


if __name__ == "__main__":
    unittest.main()
