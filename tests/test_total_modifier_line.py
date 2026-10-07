"""A contested roll's side sums its modifiers once there are two or more
(`with_total_modifier`), the written-out arithmetic leaves that sum out,
and the dice picture draws a line's tokens as text (`drawn_line`)."""

import unittest

from d12ball.dice_brief import drawn_line
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

    def test_a_player_named_with_their_badge_is_counted(self):
        # What an Ooze adds by Merge, after their name and badge.
        detail = [
            "Name [PM]",
            "Offensive skill +4",
            "{team:slime} Ooze {role:midfielder:slime} +3 (Merge)",
        ]
        with_total_modifier(detail, 5, 12)
        self.assertEqual(detail[-1], "Total modifier +7")

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
        )
        self.assertEqual(
            working,
            ((
                "Name rolled **4**",
                "Defensive skill +3",
                "+3 Midfielder ability",
                "= **10**",
            ),),
        )


class DrawnLineTests(unittest.TestCase):
    def test_a_named_player_is_drawn_with_brackets(self):
        self.assertEqual(
            drawn_line("{team:slime} Ooze {role:midfielder:slime} +3 (Merge)"),
            "Ooze [MF] +3 (Merge)",
        )

    def test_a_line_with_no_token_is_drawn_as_it_is(self):
        for line in ("+1 ball speed modifier", "Total modifier  +5", ""):
            self.assertEqual(drawn_line(line), line)


if __name__ == "__main__":
    unittest.main()
