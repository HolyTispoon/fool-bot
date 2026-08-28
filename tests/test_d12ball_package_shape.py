"""
What has to stay true about the shape of `cogs/d12ball_views`.

The package replaced one 6,531-line module, and the two things that
would quietly undo that are a name going missing from the re-export --
which breaks an import nobody notices until that view is reached -- and
a cycle between submodules, which breaks the whole package on import.
Neither is visible in a test of any one view.
"""

import ast
import importlib
import pkgutil
import unittest
from pathlib import Path

import cogs.d12ball_views as views
from save_patches import SAVING_COG_MODULES, SAVING_VIEW_MODULES, suppressed_view_saves

PACKAGE = Path(views.__file__).parent
SUBMODULES = sorted(
    m.name for m in pkgutil.iter_modules([str(PACKAGE)])
)


class ViewsPackageTests(unittest.TestCase):
    def test_every_public_name_is_re_exported(self) -> None:
        """
        `from cogs.d12ball_views import X` has to keep working for
        every X the single module used to hold, which is what let the
        split move no call site.
        """
        for module in SUBMODULES:
            mod = importlib.import_module(f"cogs.d12ball_views.{module}")
            for name, value in vars(mod).items():
                if name.startswith("_") or getattr(value, "__module__", "") != mod.__name__:
                    continue
                with self.subTest(module=module, name=name):
                    self.assertIs(getattr(views, name, None), value)
                    self.assertIn(name, views.__all__)

    def test_the_package_is_a_dag(self) -> None:
        """
        A cycle between two submodules is an ImportError for the whole
        package, so it cannot be left to be found by whoever imports it
        next. `base` is the one every other module may lean on.
        """
        edges: dict[str, set[str]] = {}
        for module in SUBMODULES:
            tree = ast.parse((PACKAGE / f"{module}.py").read_text())
            edges[module] = {
                node.module.rsplit(".", 1)[-1]
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom)
                and (node.module or "").startswith("cogs.d12ball_views.")
            }

        self.assertEqual(edges.get("base"), set(), "base may import no sibling")

        seen: set[str] = set()

        def visit(node: str, path: tuple[str, ...]) -> None:
            self.assertNotIn(node, path, f"import cycle: {' -> '.join(path + (node,))}")
            if node in seen:
                return
            seen.add(node)
            for nxt in edges.get(node, ()):
                visit(nxt, path + (node,))

        for module in SUBMODULES:
            visit(module, ())

    def test_every_saving_submodule_is_patched_in_tests(self) -> None:
        """
        `suppressed_view_saves` names the submodules that call
        `save_games` themselves. A view moving into a module not on
        that list would write `data/d12ball_games.json` during the
        suite -- and pass, because not one of those forty-odd patches
        is ever asserted on. See tests/view_patches.py.
        """
        saving = {
            f"cogs.d12ball_views.{module}"
            for module in SUBMODULES
            if "save_games" in vars(
                importlib.import_module(f"cogs.d12ball_views.{module}")
            )
        }
        self.assertEqual(saving, set(SAVING_VIEW_MODULES))


if __name__ == "__main__":
    unittest.main()


class CogPackageTests(unittest.TestCase):
    """
    `cogs/d12ball` is six mixins assembled into one class, so the two
    things that would go wrong quietly are a method defined in two of
    them -- where the MRO silently picks one -- and a mixin that starts
    saving without being named in `save_patches`.
    """

    MIXINS = (
        "core", "effects", "turnovers", "periods",
        "presentation", "slash_commands",
    )

    def test_no_method_is_defined_by_two_mixins(self) -> None:
        """
        The mixin order is the order the single file read in and is
        meant to carry no resolution. A name in two of them means one
        of the two is dead, and which one is decided by the MRO rather
        than by anybody.
        """
        seen: dict[str, str] = {}
        for module in self.MIXINS:
            mod = importlib.import_module(f"cogs.d12ball.{module}")
            cls = next(
                value for name, value in vars(mod).items()
                if name.endswith("Mixin")
            )
            for name, value in vars(cls).items():
                if name.startswith("__") or not callable(value):
                    continue
                with self.subTest(method=name):
                    self.assertNotIn(
                        name, seen,
                        f"{name} is defined by both {seen.get(name)} "
                        f"and {module}",
                    )
                seen[name] = module

    def test_every_saving_mixin_is_patched_in_tests(self) -> None:
        """
        The same silent failure the views have: a suppression patch
        that no longer intercepts leaves the real save writing
        `data/d12ball_games.json` while the test goes on passing.
        """
        saving = {
            f"cogs.d12ball.{module}"
            for module in self.MIXINS
            if "save_games" in vars(
                importlib.import_module(f"cogs.d12ball.{module}")
            )
        }
        self.assertEqual(saving, set(SAVING_COG_MODULES))

    def test_the_cog_is_assembled_from_exactly_those_mixins(self) -> None:
        """
        A mixin added to the package but left out of the class is a
        module of dead code that imports and tests clean.
        """
        import cogs.d12ball as pkg

        bases = [
            base.__name__ for base in pkg.D12Ball.__mro__
            if base.__name__.endswith("Mixin")
        ]
        self.assertEqual(len(bases), len(self.MIXINS))
