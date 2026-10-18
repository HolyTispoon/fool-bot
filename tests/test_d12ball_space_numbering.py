"""
The spaces' numbers (Law 2.1.3): a number line whose zero is the
middle of the field -- the kickoff space on boards 7 and 9, the
halfway line on board 10, which so has no space 0
(`d12ball/space_numbering.py`; the author, 2026-10-17).
"""

import unittest

from d12ball.components import Zone, load_basic_ruleset
from d12ball.formatting import space_label
from d12ball.render import space_code
from d12ball.space_numbering import MINUS, space_name, space_number


def every_space(layout):
    return [
        (zone, index)
        for zone in Zone
        for index in range(layout.zone_spaces[zone])
    ]


class SpaceNumberingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.layouts = load_basic_ruleset().board_layouts

    def numbers(self, size: int) -> list[int]:
        layout = self.layouts[size]
        return [space_number(*one, layout) for one in every_space(layout)]

    def test_boards_7_and_9_count_out_from_a_middle_space_of_0(self) -> None:
        self.assertEqual(self.numbers(7), list(range(-3, 4)))
        self.assertEqual(self.numbers(9), list(range(-4, 5)))

    def test_board_10_has_no_space_0(self) -> None:
        self.assertEqual(
            self.numbers(10), [-5, -4, -3, -2, -1, 1, 2, 3, 4, 5],
        )

    def test_the_middle_space_is_0(self) -> None:
        for size in (7, 9):
            with self.subTest(board=size):
                layout = self.layouts[size]
                middle = layout.zone_spaces[Zone.MIDFIELD] // 2
                self.assertEqual(
                    space_number(Zone.MIDFIELD, middle, layout), 0,
                )

    def test_a_negative_number_takes_the_minus_sign(self) -> None:
        layout = self.layouts[10]
        self.assertEqual(space_name(Zone.HOME_ZONE, 0, layout), f"{MINUS}5")
        self.assertNotIn("-", space_name(Zone.HOME_ZONE, 0, layout))

    def test_the_sentence_and_the_board_name_one_number(self) -> None:
        for size, layout in self.layouts.items():
            for zone, index in every_space(layout):
                with self.subTest(board=size, zone=zone, index=index):
                    self.assertEqual(
                        space_label(zone, index, layout),
                        f"space {space_code(zone, index, layout)}",
                    )


if __name__ == "__main__":
    unittest.main()
