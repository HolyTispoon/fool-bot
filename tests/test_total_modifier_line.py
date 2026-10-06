"""A contested roll's side sums its modifiers once there are two or more
(`with_total_modifier`), and the written-out arithmetic leaves that sum out."""

import unittest

from d12ball.flow.rolls import roll_working, with_total_modifier


class TotalModifierLineTests(unittest.TestCase):
    def test_two_modifiers_or_more_are_summed_from_the_total(self):
        detail = [
            "Name [WG]",
            "Offensive skill +5",
            "+1 ball speed modifier",
            "-1 Volatile burn (1)",
        ]
        with_total_modifier(detail, 7, 12)
        self.assertEqual(detail[-1], "Total modifier +5")

    def test_one_modifier_is_its_own_total(self):
        detail = ["Name [PM]", "Offensive skill +4"]
        with_total_modifier(detail, 5, 9)
        self.assertEqual(detail, ["Name [PM]", "Offensive skill +4"])

    def test_a_note_or_a_zero_is_not_a_modifier(self):
        detail = [
            "Name [PM]",
            "Injured — no skill modifier",
            "+0 ball speed modifier",
            "+3 Overdrive",
        ]
        with_total_modifier(detail, 5, 8)
        self.assertNotIn("Total", detail[-1])

    def test_the_working_leaves_the_total_out(self):
        working = roll_working(
            [(
                "Name",
                4,
                ["Defensive skill +3", "+3 Midfielder ability",
                 "Total modifier +6"],
                10,
            )],
            "verdict",
        )
        self.assertNotIn("Total", working)
        self.assertIn("+3 Midfielder ability = **10**", working)


if __name__ == "__main__":
    unittest.main()
