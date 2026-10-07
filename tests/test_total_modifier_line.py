"""A contested roll's side sums its modifiers once there are two or more
(`with_total_modifier`), and the written-out arithmetic leaves that sum out.
The score attempt's matchup image sums the shooter's the same way before
the roll (`score_attempt_brief`), and a lone roll on the web page does
(`summed_modifier_line`). The dice picture draws a line's tokens as text
(`drawn_line`)."""

import unittest

from d12ball.dice_brief import drawn_line, score_attempt_brief
from d12ball.flow.rolls import roll_working, with_total_modifier
from d12ball.formatting import summed_modifier_line
from prompt_fixtures import ENGINE, score_attempt


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

    def test_a_lone_roll_sums_two_lines_or_more(self):
        self.assertEqual(
            summed_modifier_line(["Offensive skill +4", "+2 Overdrive"], 6),
            "Total modifier +6",
        )
        self.assertIsNone(summed_modifier_line(["Offensive skill +4"], 4))
        self.assertIsNone(summed_modifier_line(["+2 Overdrive"], 2))


class DrawnLineTests(unittest.TestCase):
    def test_a_named_player_is_drawn_with_brackets(self):
        self.assertEqual(
            drawn_line("{team:slime} Ooze {role:midfielder:slime} +3 (Merge)"),
            "Ooze [MF] +3 (Merge)",
        )

    def test_a_line_with_no_token_is_drawn_as_it_is(self):
        for line in ("+1 ball speed modifier", "Total modifier  +5", ""):
            self.assertEqual(drawn_line(line), line)


class ScoreAttemptTotalTests(unittest.TestCase):
    def test_the_shooter_with_ball_speed_shows_the_sum(self):
        fixture = score_attempt()
        match = fixture.match
        match.ball.speed = 4
        [shooter], _, _ = score_attempt_brief(ENGINE, match, fixture.game)
        speed = match.shot_speed_modifier()
        self.assertNotEqual(speed, 0)
        self.assertEqual(shooter.total_modifier, shooter.skill + speed)

    def test_the_shooter_alone_is_their_own_total(self):
        fixture = score_attempt()
        match = fixture.match
        match.ball.speed = 0
        [shooter], _, _ = score_attempt_brief(ENGINE, match, fixture.game)
        self.assertIsNone(shooter.total_modifier)


if __name__ == "__main__":
    unittest.main()
