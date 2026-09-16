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
from save_patches import (
    LINKING_COG_MODULES,
    SAVING_COG_MODULES,
    SAVING_MODULES,
    SAVING_VIEW_MODULES,
    refuse_stray_save,
    suppressed_view_saves,
)

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

    def test_every_description_discord_is_sent_fits(self) -> None:
        """
        Discord refuses a description over 100 characters with a 400,
        and `tree.sync()` raises it out of `setup_hook` -- so the bot
        does not start at all. The group's own description is the one
        nobody writes deliberately: discord.py falls back to the class
        docstring for it, which is how the package split broke a
        startup that had been fine for as long as the class had no
        docstring to fall back to.
        """
        import cogs.d12ball as pkg

        def walk(command, path: str):
            yield path, command.description
            for child in getattr(command, "commands", ()):
                yield from walk(child, f"{path} {child.name}")
            for parameter in getattr(command, "parameters", ()):
                yield f"{path}:{parameter.name}", parameter.description

        descriptions = [("d12ball", pkg.D12Ball.__cog_group_description__)]
        for command in pkg.D12Ball.__cog_app_commands__:
            descriptions.extend(walk(command, f"d12ball {command.name}"))

        for name, description in descriptions:
            with self.subTest(command=name):
                self.assertTrue(description)
                self.assertLessEqual(len(description), 100)

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


class StraySaveGuardTests(unittest.TestCase):
    """
    What keeps the suppression helpers from being quietly optional.

    A patch on the wrong binding is invisible: it applies, the test
    passes, and the real `save_games` writes
    `data/d12ball_games.json` underneath it -- which is a developer's
    own saved games, since `PROJECT_ROOT` is resolved per checkout.
    Nineteen call sites were doing exactly that, on `main`, and
    nothing in the suite said so. `save_patches.guard_stray_saves`
    makes it raise instead; these are what stop the guard itself
    going missing.
    """

    def test_every_module_that_saves_is_named_in_saving_modules(self) -> None:
        """
        The guard arms a list, so a binding the list does not name is
        a binding the guard cannot see -- and `cogs/debug.py` is the
        reminder that they are not all in the two packages.
        """
        binding = {
            path
            for path in Path("cogs").rglob("*.py")
            if "save_games" in vars(
                importlib.import_module(
                    str(path.with_suffix("")).replace("/", ".")
                )
            )
        }
        named = {
            Path(module.replace(".", "/")).with_suffix(".py")
            for module in SAVING_MODULES
        }
        self.assertEqual(binding, named)

    def test_the_guard_is_armed_on_every_one_of_them(self) -> None:
        """
        Importing `save_patches` is what arms it. A test module that
        never imports it is still covered, because `unittest discover`
        imports every module before running any test -- but only for
        as long as the call at the foot of that file is there.
        """
        for module in SAVING_MODULES:
            with self.subTest(module=module):
                self.assertIs(
                    vars(importlib.import_module(module))["save_games"],
                    refuse_stray_save,
                )

    def test_a_suppression_helper_puts_the_guard_back(self) -> None:
        """
        `mock.patch` restores what it replaced, which is what lets the
        guard survive the four hundred-odd suppressions in the suite.
        """
        module = importlib.import_module(SAVING_VIEW_MODULES[0])
        with suppressed_view_saves():
            self.assertIsNot(vars(module)["save_games"], refuse_stray_save)
        self.assertIs(vars(module)["save_games"], refuse_stray_save)

    def test_an_unsuppressed_save_raises_where_it_happens(self) -> None:
        """
        The point of the whole thing: the failure names the test that
        owes the suppression, rather than being found by a script
        months later.
        """
        module = importlib.import_module(SAVING_COG_MODULES[0])
        with self.assertRaises(AssertionError) as caught:
            vars(module)["save_games"]({})
        self.assertIn("suppressed_cog_saves", str(caught.exception))

    def test_every_mixin_that_links_is_named_in_linking_modules(self) -> None:
        """
        `suppressed_full_image_links` patches a list of bindings, and
        `mock.patch` of a name a module does not bind raises rather
        than doing nothing -- so a mixin dropping its last
        `add_full_image_button` call breaks every test that suppresses
        one, and a mixin gaining a call is an unsuppressed Discord
        edit. Either way the list has to track the imports, which is
        what this reads.
        """
        binding = {
            module
            for module in SAVING_COG_MODULES
            if "add_full_image_button" in vars(
                importlib.import_module(module)
            )
        }
        self.assertEqual(binding, set(LINKING_COG_MODULES))

    def test_the_storage_module_itself_is_left_alone(self) -> None:
        """
        `tests/test_game_storage.py` is the one place that means to
        reach the disk, and it goes through `storage.save_games` with
        `GAMES_FILE` pointed at a tempdir. Arming that would break the
        tests for the thing being guarded.
        """
        from gamesaves.d12ball import storage

        self.assertIsNot(storage.save_games, refuse_stray_save)
