"""
A 2.0 player is named with the role the match gives them, and a bench
player by their skills; the 2.0 board draws them as tiles in their
zones' role slots ("Naming a player" in docs/design/naming-and-wording.md;
"The 2.0 board" in docs/design/board-image.md).
"""

from __future__ import annotations

import unittest

from PIL import Image

from d12ball.components import PlayerRole, TeamSide
from d12ball.game import Edition
from d12ball.zone_board_image import render_zone_board, zone_slots
from d12ball.render import IMAGE_WIDTH

from roster import benched, fielded
from test_formation_roles import kickoff


class TwoPointOhNamingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine, self.game, self.match = kickoff(Edition.TWO)

    def test_a_fielded_card_is_named_by_the_role_it_holds(self) -> None:
        card = fielded(self.match, PlayerRole.DEFENDER)
        # The zone gives the card a role it was not dealt as.
        self.match.formation_roles["home"][card] = PlayerRole.FULLBACK.value
        name = self.engine.get_player_definition(card).name
        self.assertEqual(
            self.engine.player_name(self.match, card), f"{name} [FB]",
        )
        self.assertEqual(
            self.engine.format_roster_player(card, self.match), f"{name} [FB]",
        )
        self.assertIn(
            "{role:fullback:",
            self.engine.format_player_label(
                self.match, self.engine.get_player_definition(card),
            ),
        )

    def test_a_bench_card_holds_no_role_and_is_named_by_its_skills(self) -> None:
        card = benched(self.match, PlayerRole.STRIKER)
        skills = self.engine.skills(self.game, card)
        name = self.engine.get_player_definition(card).name
        self.assertEqual(
            self.engine.player_name(self.match, card, game=self.game),
            f"{name} [{skills.offense}|{skills.defense}]",
        )

    def test_board_roles_are_the_matchs(self) -> None:
        roles = self.engine.board_roles(self.match)
        self.assertEqual(
            set(roles), set(self.match.home.field_players)
            | set(self.match.visiting.field_players),
        )
        for card, role in roles.items():
            self.assertEqual(role, self.engine.role_of(self.match, card))


class OnePointOhNamingTests(unittest.TestCase):
    def test_a_card_keeps_its_own_role(self) -> None:
        engine, _, match = kickoff(Edition.ONE)
        card = benched(match, PlayerRole.STRIKER)
        name = engine.get_player_definition(card).name
        self.assertEqual(engine.player_name(match, card), f"{name} [SK]")
        self.assertEqual(engine.board_roles(match), {})


class ZoneBoardImageTests(unittest.TestCase):
    """Nothing here sees a pixel -- look at the image
    (`scripts/render_sample.py --edition 2.0`)."""

    def test_the_board_renders_at_its_size(self) -> None:
        for board_size in (7, 9, 10):
            with self.subTest(board_size=board_size):
                engine, _, match = kickoff(Edition.TWO, board_size)
                png = render_zone_board(
                    match, engine.player_catalog, "Test",
                    engine.board_roles(match), scale=1,
                )
                width, height = Image.open(png).size
                self.assertEqual(width, IMAGE_WIDTH)
                self.assertGreater(height, width / 2)

    def test_a_role_nobody_holds_still_has_its_slot(self) -> None:
        from d12ball.render import player_index

        engine, _, match = kickoff(Edition.TWO)
        roles = engine.board_roles(match)
        winger = next(
            card for card, role in roles.items()
            if role == PlayerRole.WINGER
            and card in match.home.field_players
        )
        roles[winger] = PlayerRole.STRIKER
        slots = zone_slots(
            match, match.home, player_index(engine.player_catalog), roles,
            "opponent_goal",
        )
        self.assertIn((PlayerRole.WINGER, False, None), slots)
        self.assertEqual(
            sum(1 for role, _, card in slots if role == PlayerRole.STRIKER),
            2,
        )


if __name__ == "__main__":
    unittest.main()
