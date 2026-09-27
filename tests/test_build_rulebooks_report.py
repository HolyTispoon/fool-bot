"""
The build script's report names a written PDF relative to the repository
when it is inside it and by its absolute path otherwise; `--out` may name
a folder anywhere, and `Path.relative_to` raises on one outside the repo.
"""
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "scripts" / "build_rulebooks.py"


def load_script():
    spec = importlib.util.spec_from_file_location("build_rulebooks", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BuildRulebooksReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = load_script()

    def test_in_repo_path_is_shown_relative_to_the_repository(self):
        path = PROJECT_ROOT / "print" / "charter.pdf"
        self.assertEqual(self.script.shown(path), os.path.join("print", "charter.pdf"))

    def test_relative_path_is_resolved_against_the_working_directory(self):
        before = os.getcwd()
        os.chdir(PROJECT_ROOT)
        try:
            shown = self.script.shown(Path("print") / "learn-to-play.pdf")
        finally:
            os.chdir(before)
        self.assertEqual(shown, os.path.join("print", "learn-to-play.pdf"))

    def test_out_of_repo_path_is_shown_absolute(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "learn-to-play.pdf"
            self.assertEqual(self.script.shown(path), str(path.resolve()))
            self.assertTrue(Path(self.script.shown(path)).is_absolute())


if __name__ == "__main__":
    unittest.main()
