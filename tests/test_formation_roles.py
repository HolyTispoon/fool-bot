"""
D12 Ball 2.0's roles: a role belongs to the formation, assigned to a
player, and no role plays an ability (docs/rules-2.0.md, section 4;
"Roles" in docs/design/maneuver-deck.md).
"""

from __future__ import annotations

import unittest

from d12ball.components import (
    MatchState,
    PlayerRole,
    TeamSide,
    Zone,
    zone_for_area,
)
from d12ball.game import Edition, Formation

from roster import benched, fielded
from test_driver_full_game import RULESET, build_engine, build_game, build_match

ROLES = tuple(PlayerRole)


def kickoff(edition: Edition, board_size: int = 7):
    """A game started the way the bot starts one, and its match."""
    engine = build_engine()
    engine.rng.seed(3)
    game = build_game()
    game.edition = edition
    game.board_size = board_size
    return engine, game, engine.initialize_standard_match(game)


def space_of(match: MatchState, card: str):
    return match.board.meeple_position(card)


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



class StandardDealTests(unittest.TestCase):
    """The 2.0 deal (docs/rules-2.0.md 4.5)."""

    def test_one_point_oh_deals_no_roles(self) -> None:
        engine, _, match = kickoff(Edition.ONE)
        self.assertEqual(match.formation_roles, {})
        card = fielded(match, PlayerRole.FULLBACK)
        self.assertEqual(engine.role_of(match, card), PlayerRole.FULLBACK)
        self.assertTrue(
            engine.has_role_ability(match, card, PlayerRole.FULLBACK),
        )

    def test_each_of_the_six_takes_the_role_their_card_names(self) -> None:
        for board_size in (7, 9, 10):
            engine, _, match = kickoff(Edition.TWO, board_size)
            for side in TeamSide:
                for role in ROLES:
                    with self.subTest(board=board_size, side=side, role=role):
                        card = fielded(match, role, side)
                        self.assertEqual(engine.role_of(match, card), role)

    def test_a_bench_card_plays_no_role(self) -> None:
        engine, _, match = kickoff(Edition.TWO)
        bench = benched(match, PlayerRole.STRIKER)
        self.assertIsNone(engine.role_of(match, bench))

    def test_boards_7_and_9_deal_the_same_spaces_as_one_point_oh(self) -> None:
        for board_size in (7, 9):
            _, _, one = kickoff(Edition.ONE, board_size)
            _, _, two = kickoff(Edition.TWO, board_size)
            for side in TeamSide:
                for card in one.setup_for_side(side).field_players:
                    with self.subTest(board=board_size, card=card):
                        self.assertEqual(space_of(two, card), space_of(one, card))

    def test_board_10_puts_the_playmaker_on_the_kickoff_space(self) -> None:
        _, _, match = kickoff(Edition.TWO, 10)
        for side in TeamSide:
            with self.subTest(side=side):
                kickoff_space = match.kickoff_space_for(side)
                behind = kickoff_space + (-1 if side == TeamSide.HOME else 1)
                self.assertEqual(
                    space_of(match, fielded(match, PlayerRole.PLAYMAKER, side)),
                    (Zone.MIDFIELD, kickoff_space),
                )
                self.assertEqual(
                    space_of(match, fielded(match, PlayerRole.MIDFIELDER, side)),
                    (Zone.MIDFIELD, behind),
                )
                # The arrangement a new play restores is the 2.0 deal's.
                card = fielded(match, PlayerRole.PLAYMAKER, side)
                self.assertEqual(
                    tuple(match.assigned_positions[card]),
                    (Zone.MIDFIELD.value, kickoff_space),
                )

    def test_two_point_oh_plays_no_role_ability(self) -> None:
        engine, _, match = kickoff(Edition.TWO)
        for role in ROLES:
            card = fielded(match, role)
            with self.subTest(role=role):
                self.assertFalse(engine.has_role_ability(match, card, role))
        # The Fullback's High Ball reaches 3, not 4 (docs/rules-2.0.md 4.7a).
        match.active_player_id = fielded(match, PlayerRole.FULLBACK)
        self.assertNotIn(4, engine.high_pass_distance_options(match))

    def test_the_tutorial_stays_one_point_oh(self) -> None:
        engine = build_engine()
        game = build_game()
        game.edition = Edition.TWO
        game.tutorial = True
        self.assertEqual(engine.initialize_standard_match(game).formation_roles, {})


class CarriedRolesTests(unittest.TestCase):
    """A role moves with the place (docs/rules-2.0.md 4.6)."""

    def test_a_substitute_takes_the_outgoing_players_role(self) -> None:
        engine, _, match = kickoff(Edition.TWO)
        outgoing = fielded(match, PlayerRole.FULLBACK)
        incoming = benched(match, PlayerRole.STRIKER)
        match.substitute(TeamSide.HOME, outgoing, incoming)
        self.assertEqual(engine.role_of(match, incoming), PlayerRole.FULLBACK)
        self.assertIsNone(engine.role_of(match, outgoing))

    def test_a_zone_assignment_trades_the_two_roles(self) -> None:
        engine, _, match = kickoff(Edition.TWO)
        fullback = fielded(match, PlayerRole.FULLBACK)
        striker = fielded(match, PlayerRole.STRIKER)
        match.exchange_field_players(TeamSide.HOME, fullback, striker)
        self.assertEqual(engine.role_of(match, fullback), PlayerRole.STRIKER)
        self.assertEqual(engine.role_of(match, striker), PlayerRole.FULLBACK)

    def test_a_formation_change_gives_each_zone_its_roles(self) -> None:
        engine, game, match = kickoff(Edition.TWO, 9)
        engine.apply_formation(match, TeamSide.HOME, Formation.THREE_TWO_ONE, game)
        setup = match.home
        expected = {
            "own_goal": [PlayerRole.FULLBACK] + [PlayerRole.DEFENDER] * 2,
            "midfield": [PlayerRole.PLAYMAKER, PlayerRole.MIDFIELDER],
            "opponent_goal": [PlayerRole.STRIKER],
        }
        for area, wanted in expected.items():
            zone = zone_for_area(TeamSide.HOME, area)
            held = sorted(
                engine.role_of(match, card) for card in setup.zones[zone]
            )
            with self.subTest(area=area):
                self.assertEqual(held, sorted(wanted))


if __name__ == "__main__":
    unittest.main()
