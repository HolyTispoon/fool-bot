"""
Cutting the studio background out of a portrait.

The suite cannot see a picture, so what it checks is the judgement the
tool rests on -- **light and colourless is background; light and tinted
is paint** -- and the one thing about the roster nobody would notice
by looking: that the tracked portraits are already cut, which is what
would catch a new painting arriving with its background still on it.

See scripts/recut_player_portraits.py, and "The player cards" in
docs/design/cards.md.
"""

import importlib.util
import unittest
from pathlib import Path

from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PORTRAITS = PROJECT_ROOT / "d12ball" / "images" / "player_images"


def load_recut_script():
    """
    scripts/ is a folder of tools rather than a package, so the module
    is loaded by path.
    """
    path = PROJECT_ROOT / "scripts" / "recut_player_portraits.py"
    spec = importlib.util.spec_from_file_location(
        "recut_player_portraits", path,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


recut_script = load_recut_script()


def walled(patch: tuple[int, int, int], size: int = 12) -> Image.Image:
    """
    A patch of colour walled in by a dark ring, on a white background:
    the shape of every question here, since what the tool has to decide
    is whether something it cannot reach from the edge is background.
    """
    image = Image.new("RGBA", (40, 40), (255, 255, 255, 255))
    px = image.load()
    for y in range(10, 12 + size + 2):
        for x in range(10, 12 + size + 2):
            px[x, y] = (20, 30, 40, 255)
    for y in range(12, 12 + size):
        for x in range(12, 12 + size):
            px[x, y] = patch + (255,)
    return image


class D12BallPortraitRecutTests(unittest.TestCase):
    def test_a_walled_in_pocket_of_background_goes(self) -> None:
        """
        Most of what was left behind is walled in -- between a tentacle
        and an arm, or in the holes of a goal net -- so reaching the
        edge of the image cannot be the test.
        """
        cut, cleared = recut_script.recut(walled((248, 248, 248)))

        self.assertEqual(cut.load()[18, 18][3], 0)
        self.assertGreater(cleared, 0)

    def test_a_painted_light_area_stays(self) -> None:
        """
        The white jersey numbers and the white net a goalkeeper stands
        in are as light as the background and are not it. What tells
        them apart is that paint carries a tint: this patch is lighter
        than SOLID and would go if lightness were the whole test.
        """
        patch = (255, 255, 235)
        cut, _ = recut_script.recut(walled(patch))

        self.assertEqual(cut.load()[18, 18], patch + (255,))

    def test_a_highlight_too_small_to_be_background_stays(self) -> None:
        """
        An eye highlight is a small run of light colourless pixels too,
        so a walled-in run has to be bigger than one to be dropped.
        """
        patch = (248, 248, 248)
        cut, _ = recut_script.recut(walled(patch, size=3))

        self.assertEqual(cut.load()[13, 13], patch + (255,))

    def test_a_cut_edge_keeps_no_light_thread(self) -> None:
        """
        A pixel against a cut edge is part background, and left at full
        strength it is a white thread round everything -- invisible on
        the card and a bright outline on the dark images the bot draws.
        """
        image = walled((248, 248, 248))
        px = image.load()
        for x in range(12, 24):
            px[x, 12] = (210, 210, 210, 255)

        cut, _ = recut_script.recut(image)

        self.assertLess(cut.load()[18, 12][3], 255)

    def test_recutting_a_cut_portrait_changes_nothing(self) -> None:
        """
        A pass drops pixels as it scans, which the pixels it has
        already looked at never saw, so one pass is not a fixpoint --
        `recut` repeats until one clears nothing. Without that, output
        would depend on how many times the tool had been run.
        """
        once, _ = recut_script.recut(walled((248, 248, 248)))
        twice, cleared = recut_script.recut(once)

        self.assertEqual(cleared, 0)
        self.assertEqual(once.tobytes(), twice.tobytes())

    def test_every_tracked_portrait_is_already_cut(self) -> None:
        """
        The roster was recut in one go, and the thing to catch is the
        next painting: art arrives from outside the repo with its
        studio background on it, and on the white card nothing about
        that looks wrong.
        """
        for path in sorted(PORTRAITS.glob("*.png")):
            with self.subTest(portrait=path.stem):
                with Image.open(path) as source:
                    image = source.convert("RGBA")
                _, cleared = recut_script.recut(image)
                self.assertEqual(cleared, 0)


if __name__ == "__main__":
    unittest.main()
