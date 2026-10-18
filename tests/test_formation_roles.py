"""
D12 Ball 2.0's roles: a role belongs to the formation, assigned to a
player, and no role plays an ability (docs/rules-2.0.md, section 4;
"Roles" in docs/design/maneuver-deck.md).
"""

from __future__ import annotations

import pathlib
import unittest

from d12ball.components import (
    MatchState,
    PlayerRole,
    TeamSide,
    Zone,
    zone_for_area,
)
from d12ball.flow.periods import finish_halftime, finish_setup_coaching
from d12ball.flow.turnovers import run_back_kickoff_fill
from d12ball.game import Edition, Formation, team_display_name

from roster import benched, fielded
from test_driver_full_game import RULESET, build_engine, build_game, build_match

ROLES = tuple(PlayerRole)
# The recommended arrangement's columns (docs/rules-2.0.md 4.5).
ARRANGEMENT_ROLES = (
    PlayerRole.FULLBACK, PlayerRole.DEFENDER, PlayerRole.PLAYMAKER,
    PlayerRole.MIDFIELDER, PlayerRole.STRIKER, PlayerRole.WINGER,
)
PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent


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


class RecommendedArrangementTests(unittest.TestCase):
    """docs/rules-2.0.md 4.5 names each team's recommended six, and the
    standard deal is what sets it up -- so the table is the deal's,
    and a roster change in the sheet shows up here until it is."""

    def test_the_rules_table_is_the_standard_deal(self) -> None:
        text = (PROJECT_ROOT / "docs" / "rules-2.0.md").read_text(
            encoding="utf-8",
        )
        section = text[text.index("**4.5**"):text.index("**4.6**")]
        rows = {
            cells[0]: cells[1:]
            for line in section.splitlines()
            if line.startswith("| ") and not line.startswith("| ---")
            for cells in [[cell.strip() for cell in line.strip("|").split("|")]]
        }
        header = rows.pop("Team")
        self.assertEqual(
            header, [role.value.title() for role in ARRANGEMENT_ROLES],
        )
        catalog = build_engine().player_catalog
        expected = {}
        for team, roster in catalog.teams.items():
            first = {}
            for player in roster.players:
                first.setdefault(player.role, player.name)
            expected[team_display_name(team)] = [
                first[role] for role in ARRANGEMENT_ROLES
            ]
        self.assertEqual(rows, expected)


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



class KickoffTests(unittest.TestCase):
    """The Playmaker takes the kickoff (docs/rules-2.0.md 4.4)."""

    def crowd_the_kickoff(self, match: MatchState) -> str:
        """A teammate onto the Playmaker's space, as an Ooze may stand,
        so the kickoff has two handlers to choose between."""
        side = match.ball.possession
        other = fielded(match, PlayerRole.MIDFIELDER, side)
        match.board.place_meeple(
            other, Zone.MIDFIELD, match.kickoff_space_for(side),
        )
        self.assertEqual(len(match.eligible_ball_handlers()), 2)
        return fielded(match, PlayerRole.PLAYMAKER, side)

    def test_the_first_kickoff_is_the_playmakers(self) -> None:
        engine, game, match = kickoff(Edition.TWO)
        playmaker = self.crowd_the_kickoff(match)
        finish_setup_coaching(engine, game, match)
        self.assertEqual(engine.turn_handler_candidates(game, match), [playmaker])

    def test_a_goals_restart_is_the_playmakers(self) -> None:
        engine, game, match = kickoff(Edition.TWO)
        match.restart_after_goal(TeamSide.VISITING)
        playmaker = self.crowd_the_kickoff(match)
        run_back_kickoff_fill(engine, game, match)
        self.assertEqual(match.ball_carrier_id, playmaker)

    def test_the_second_half_kickoff_is_the_playmakers(self) -> None:
        engine, game, match = kickoff(Edition.TWO)
        match.restart_ball_at(
            Zone.MIDFIELD, match.kickoff_space_for(TeamSide.VISITING),
        )
        match.ball.possession = TeamSide.VISITING
        playmaker = self.crowd_the_kickoff(match)
        finish_halftime(engine, game, match)
        self.assertEqual(match.ball_carrier_id, playmaker)

    def test_one_point_oh_leaves_the_coach_the_choice(self) -> None:
        engine, game, match = kickoff(Edition.ONE)
        self.crowd_the_kickoff(match)
        finish_setup_coaching(engine, game, match)
        self.assertIsNone(match.ball_carrier_id)
        self.assertEqual(len(engine.turn_handler_candidates(game, match)), 2)


if __name__ == "__main__":
    unittest.main()
