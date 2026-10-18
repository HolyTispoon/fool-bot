"""A tied score attempt is a goal (Law 5.2.3; the author, 2026-10-18).

The roll is the real one; only the two totals are made level, since
which dice make them level depends on everything else the shot adds.
"""

import unittest
from unittest import mock

from d12ball.flow import rolls
from prompt_fixtures import ENGINE, score_attempt


class TiedShotTests(unittest.TestCase):
    def shoot(self, attack_total: int, defense_total: int):
        fixture = score_attempt()
        real = rolls.score_score_attempt

        def level(*args, **kwargs):
            contestants, _, _, ignite = real(*args, **kwargs)
            return contestants, attack_total, defense_total, ignite

        with mock.patch.object(rolls, "score_score_attempt", side_effect=level):
            dice, _ = rolls.score_attempt_step(
                ENGINE, fixture.game, fixture.match,
            )
        return dice, fixture.match

    def test_a_tie_scores(self) -> None:
        dice, match = self.shoot(12, 12)
        self.assertTrue(dice.scored)
        self.assertTrue(match.goals)

    def test_a_lower_total_misses(self) -> None:
        dice, match = self.shoot(11, 12)
        self.assertFalse(dice.scored)
        self.assertFalse(match.goals)


if __name__ == "__main__":
    unittest.main()
