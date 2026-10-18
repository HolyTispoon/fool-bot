"""
D12 Ball 2.0's roles: a role belongs to the formation, assigned to a
player, and no role plays an ability (docs/rules-2.0.md, section 4;
"Roles" in docs/design/maneuver-deck.md).
"""

from __future__ import annotations

import unittest

from d12ball.components import MatchState

from test_driver_full_game import RULESET, build_match


class SavedRolesTests(unittest.TestCase):
    """`formation_roles` is saved only where a match has any."""

    def test_a_match_with_no_roles_saves_without_the_key(self) -> None:
        self.assertNotIn("formation_roles", build_match().to_dict())

    def test_roles_are_saved_and_read_back(self) -> None:
        match = build_match()
        match.formation_roles = {
            "home": {card: "midfielder" for card in match.home.field_players},
        }
        saved = match.to_dict()
        self.assertEqual(saved["formation_roles"], match.formation_roles)
        self.assertEqual(
            MatchState.from_dict(saved, RULESET).formation_roles,
            match.formation_roles,
        )
        saved["formation_roles"]["home"].clear()
        self.assertTrue(match.formation_roles["home"])


if __name__ == "__main__":
    unittest.main()
