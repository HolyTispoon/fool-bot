"""
The six basic role abilities as a reference card, drawn from
`players.json`'s `role_profiles`.

The suite cannot see a picture, so what this checks is what a print
gets wrong silently -- a face that is no longer poker size, or a role
left off the grid entirely. See d12ball/role_cards.py.
"""
import unittest

from d12ball.cards import BLEED, CARD_HEIGHT, CARD_WIDTH
from d12ball.components import PlayerRole, load_player_catalog
from d12ball.role_cards import (
    GRID_ROLES,
    render_role_card,
    render_role_card_set,
)


class RoleCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.role_profiles = load_player_catalog().role_profiles

    def test_every_role_appears_exactly_once_in_the_grid(self) -> None:
        roles = [role for row in GRID_ROLES for role in row]
        self.assertEqual(len(roles), 6)
        self.assertEqual(set(roles), set(PlayerRole))

    def test_a_face_is_poker_size(self) -> None:
        card = render_role_card(self.role_profiles)
        self.assertEqual(card.size, (CARD_WIDTH, CARD_HEIGHT))

    def test_bleed_adds_a_trim_margin(self) -> None:
        card = render_role_card(self.role_profiles, bleed=True)
        self.assertEqual(
            card.size, (CARD_WIDTH + BLEED * 2, CARD_HEIGHT + BLEED * 2)
        )

    def test_the_set_is_one_double_sided_card_with_matching_faces(
        self,
    ) -> None:
        faces = render_role_card_set(self.role_profiles)
        self.assertEqual(len(faces), 2)
        self.assertEqual([name for name, _ in faces], ["front", "back"])
        self.assertIs(faces[0][1], faces[1][1])


if __name__ == "__main__":
    unittest.main()
