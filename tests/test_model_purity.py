"""
The model may not import `discord`, and may not be `async`.

Both halves of that already hold -- `d12ball/` has no `discord` import
and no `async def` in it anywhere, and neither does `gamesaves/d12ball/`
-- so this file is a **ratchet on something already true** rather than a
cleanup with work behind it. That is exactly why it is worth having: the
purity is currently kept by habit, and habit is what erodes one
convenience at a time once a refactor starts moving flow code across the
line. See `docs/design/model-discord-split.md`.

**`gamesaves/d12ball/` is a second root, not an afterthought.** The plan
calls `gamesaves/d12ball/storage.py` already portable and
`MatchState.to_dict` already a wire format -- both are claims about code
this file did not check until now. `gamesaves/tethysdeck/` is a different
prototype's save and outside what this plan is about, so it is left out.

**Not-async is the half that gets given away quietly.** No-discord is
obvious and a reviewer would catch it; the first `await` in a model
function looks harmless and is not, because it drags an event loop, an
interaction and a rate-limit bucket in behind it. A function that wants
to be async wants to send something, and sending is the frontend's.

**The import check runs in a subprocess, and that is load-bearing.**
`unittest discover` imports every test module before running anything,
so by the time this test runs, half of `d12ball/` is already in
`sys.modules` -- and `import_module` on an already-imported module
returns the cached object without re-executing it, so an in-process
check would pass against modules it never actually imported. A fresh
interpreter with `discord` blocked is the only version of this test
that tests anything.
"""

import ast
import pathlib
import subprocess
import sys
import unittest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
MODEL_ROOTS = (PROJECT_ROOT / "d12ball", PROJECT_ROOT / "gamesaves" / "d12ball")

# Run the import check in a fresh interpreter with `discord` refused by a
# meta_path finder, which is what makes it a real import rather than a
# lookup in an already-populated sys.modules.
IMPORT_PROBE = """
import importlib
import json
import pathlib
import sys

BLOCKED = ("discord",)


class Blocker:
    def find_spec(self, name, path=None, target=None):
        if name in BLOCKED or name.startswith("discord."):
            raise ModuleNotFoundError(
                f"{name} is blocked: the model may not import it",
                name=name,
            )
        return None


sys.meta_path.insert(0, Blocker())

# argv[1] is the project root every module name is computed relative to
# (it is on sys.path), and argv[2:] are the roots to walk -- module names
# have to be relative to the project root rather than to each root's own
# parent, or a nested root like gamesaves/d12ball resolves to the wrong
# dotted name and imports something else entirely.
project_root = pathlib.Path(sys.argv[1])
failures = {}
for root_arg in sys.argv[2:]:
    root = pathlib.Path(root_arg)
    for path in sorted(root.rglob("*.py")):
        module = ".".join(path.relative_to(project_root).with_suffix("").parts)
        try:
            importlib.import_module(module)
        except ModuleNotFoundError as exc:
            if exc.name == "discord" or str(exc.name or "").startswith("discord"):
                failures[module] = "imports discord"
            else:
                failures[module] = f"missing dependency: {exc.name}"
        except Exception as exc:  # pragma: no cover - a real breakage
            failures[module] = f"{type(exc).__name__}: {exc}"

print(json.dumps(failures))
"""


def model_modules() -> list[pathlib.Path]:
    modules = []
    for root in MODEL_ROOTS:
        modules.extend(root.rglob("*.py"))
    return sorted(modules)


class ModelPurityTests(unittest.TestCase):
    """`d12ball/` and `gamesaves/d12ball/` are the model, and these are
    the two rules they keep."""

    def test_every_model_module_imports_without_discord(self) -> None:
        """
        A fresh interpreter can import all of `d12ball/` and
        `gamesaves/d12ball/` with `discord` refused outright.

        The failure message names the module that reached for it, since
        that is the whole of the diagnosis -- the import is transitive
        as often as not, and a bare "something imports discord" sends
        the next reader grepping.
        """
        probe = subprocess.run(
            [sys.executable, "-c", IMPORT_PROBE, str(PROJECT_ROOT)]
            + [str(root) for root in MODEL_ROOTS],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
            timeout=120,
        )
        self.assertEqual(
            probe.returncode,
            0,
            f"the import probe itself failed:\n{probe.stderr}",
        )

        import json

        failures = json.loads(probe.stdout)
        self.assertEqual(
            failures,
            {},
            "these modules do not import cleanly without discord: "
            f"{failures}",
        )

    def test_no_model_module_defines_an_async_function(self) -> None:
        """
        The second half of the rule, and the one that erodes quietly.

        Asserted over the AST rather than by grepping for `async def`,
        so a definition inside a class, a nested function or a string
        is read the same way the interpreter reads it.
        """
        offenders = []
        for path in model_modules():
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.AsyncFunctionDef):
                    offenders.append(
                        f"{path.relative_to(PROJECT_ROOT)}:{node.lineno} "
                        f"{node.name}"
                    )
        self.assertEqual(
            offenders,
            [],
            "the model may not be async -- a step that wants to await "
            f"wants to send something: {offenders}",
        )

    def test_the_model_imports_nothing_from_the_cog(self) -> None:
        """
        The layering, read from the other end: cogs import from
        `d12ball`, never the other way around (CLAUDE.md, "Team
        colors"). A model module that reaches into `cogs/` would import
        discord transitively and fail the first test -- but it would
        fail it naming a module nobody would expect, so this asserts the
        direction directly and reports it as what it is.
        """
        offenders = []
        for path in model_modules():
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                for name in names:
                    if name == "cogs" or name.startswith("cogs."):
                        offenders.append(
                            f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}"
                            f" imports {name}"
                        )
        self.assertEqual(offenders, [], f"model imports a cog: {offenders}")


if __name__ == "__main__":
    unittest.main()
