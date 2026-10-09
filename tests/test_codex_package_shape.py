"""
What has to stay true about the shape of the Codex frontend -- the four
ratchets `tests/test_d12ball_package_shape.py` carries for D12 Ball's,
held from the frontend's first commit (docs/codex-bot.md, step 3): no
method defined by two mixins, the views package a DAG that re-exports
every name, every command and parameter description present and under
Discord's 100 characters, and `MODEL_STEPS` covering `FollowOnStep`.
"""

import ast
import importlib
import pkgutil
import unittest
from pathlib import Path

import cogs.codex as pkg
import cogs.codex_views as views
from codex.flow import driver
from codex.flow.result import FollowOnStep

PACKAGE = Path(views.__file__).parent
SUBMODULES = sorted(module.name for module in pkgutil.iter_modules([str(PACKAGE)]))
MIXINS = ("core", "turns", "ending", "lobby", "presentation", "slash_commands", "reference")


class ViewsPackageTests(unittest.TestCase):
    def test_every_public_name_is_re_exported(self) -> None:
        for module in SUBMODULES:
            mod = importlib.import_module(f"cogs.codex_views.{module}")
            for name, value in vars(mod).items():
                if name.startswith("_") or getattr(value, "__module__", "") != mod.__name__:
                    continue
                if name.isupper() and not isinstance(value, (str, dict, tuple)):
                    continue
                with self.subTest(module=module, name=name):
                    self.assertIs(getattr(views, name, None), value)
                    self.assertIn(name, views.__all__)

    def test_the_package_is_a_dag(self) -> None:
        edges: dict[str, set[str]] = {}
        for module in SUBMODULES:
            tree = ast.parse((PACKAGE / f"{module}.py").read_text())
            edges[module] = {
                node.module.rsplit(".", 1)[-1]
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom)
                and (node.module or "").startswith("cogs.codex_views.")
            }
        self.assertEqual(edges.get("base"), set(), "base may import no sibling")

        def visit(node: str, path: tuple[str, ...]) -> None:
            self.assertNotIn(node, path, f"import cycle: {' -> '.join(path + (node,))}")
            for following in edges.get(node, ()):
                visit(following, path + (node,))

        for module in SUBMODULES:
            visit(module, ())

    def test_no_view_saves(self) -> None:
        """A view changes the record through the service, which saves."""
        for module in SUBMODULES:
            with self.subTest(module=module):
                self.assertNotIn(
                    "save_games", vars(importlib.import_module(f"cogs.codex_views.{module}")),
                )


class CogMixinTests(unittest.TestCase):
    def test_no_method_is_defined_by_two_mixins(self) -> None:
        seen: dict[str, str] = {}
        for module in MIXINS:
            mod = importlib.import_module(f"cogs.codex.{module}")
            cls = next(value for name, value in vars(mod).items() if name.endswith("Mixin"))
            for name, value in vars(cls).items():
                if name.startswith("__") or not (callable(value) or hasattr(value, "callback")):
                    continue
                with self.subTest(method=name):
                    self.assertNotIn(name, seen, f"{name} is defined by {seen.get(name)} and {module}")
                seen[name] = module

    def test_the_cog_is_assembled_from_exactly_those_mixins(self) -> None:
        bases = [base.__name__ for base in pkg.Codex.__mro__ if base.__name__.endswith("Mixin")]
        self.assertEqual(len(bases), len(MIXINS))
        names = [base.__name__ for base in pkg.Codex.__bases__]
        self.assertEqual(names[-1], "GroupCog")

    def test_every_description_discord_is_sent_fits(self) -> None:
        def walk(command, path: str):
            yield path, command.description
            for child in getattr(command, "commands", ()):
                yield from walk(child, f"{path} {child.name}")
            for parameter in getattr(command, "parameters", ()):
                yield f"{path}:{parameter.name}", parameter.description

        descriptions = [("codex", pkg.Codex.__cog_group_description__)]
        for command in pkg.Codex.__cog_app_commands__:
            descriptions.extend(walk(command, f"codex {command.name}"))
        for name, description in descriptions:
            with self.subTest(command=name):
                self.assertTrue(description)
                self.assertLessEqual(len(description), 100)


class FollowOnStepTests(unittest.TestCase):
    def test_the_driver_runs_every_member(self) -> None:
        self.assertEqual(set(driver.MODEL_STEPS), set(FollowOnStep))


if __name__ == "__main__":
    unittest.main()
