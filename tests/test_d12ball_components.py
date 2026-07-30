import unittest
from pathlib import Path

from PIL import Image

from d12ball.components import (
    AssignmentEdge,
    AttackDirection,
    BoardState,
    MatchState,
    PlayerRole,
    TeamSide,
    Zone,
    create_standard_setup,
    load_basic_ruleset,
    load_player_catalog,
)
from d12ball.game import Team
from d12ball.render import render_match_image


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class D12BallComponentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    def test_catalog_contains_four_nine_player_teams(self) -> None:
        self.assertEqual(set(self.catalog.teams), set(Team))

        all_ids = []
        for roster in self.catalog.teams.values():
            self.assertEqual(len(roster.players), 9)
            all_ids.extend(player.player_id for player in roster.players)

        self.assertEqual(len(all_ids), 36)
        self.assertEqual(len(set(all_ids)), 36)

    def test_every_player_has_a_card_image(self) -> None:
        for roster in self.catalog.teams.values():
            for player in roster.players:
                image_path = PROJECT_ROOT / "d12ball" / player.card_image
                self.assertTrue(
                    image_path.is_file(),
                    f"Missing {image_path}",
                )

    def test_basic_role_profiles_are_symmetric(self) -> None:
        expected_skills = {
            PlayerRole.FULLBACK: (1, 6),
            PlayerRole.DEFENDER: (2, 5),
            PlayerRole.MIDFIELDER: (3, 4),
            PlayerRole.PLAYMAKER: (4, 3),
            PlayerRole.WINGER: (5, 2),
            PlayerRole.STRIKER: (6, 1),
        }

        for role, skills in expected_skills.items():
            profile = self.catalog.role_profiles[role]
            self.assertEqual(
                (profile.offense, profile.defense),
                skills,
            )

    def test_board_layouts_match_confirmed_zone_sizes(self) -> None:
        expected = {
            6: (2, 2, 2),
            7: (2, 3, 2),
            9: (3, 3, 3),
        }

        for board_size, zone_counts in expected.items():
            layout = self.rules.board_layouts[board_size]
            self.assertEqual(
                tuple(layout.zone_spaces[zone] for zone in Zone),
                zone_counts,
            )
            board = BoardState.empty(layout)
            self.assertEqual(
                tuple(len(board.spaces[zone]) for zone in Zone),
                zone_counts,
            )

    def test_home_standard_setup(self) -> None:
        roster = self.catalog.teams[Team.ORANGE]
        setup = create_standard_setup(
            roster,
            TeamSide.HOME,
            self.rules,
        )

        self.assertEqual(
            setup.zones[Zone.HOME_GOAL],
            ["orange_hellguard", "orange_blazebulk"],
        )
        self.assertEqual(
            setup.zones[Zone.MIDFIELD],
            ["orange_sizzik", "orange_scorchit"],
        )
        self.assertEqual(
            setup.zones[Zone.VISITORS_GOAL],
            ["orange_flickerwing", "orange_kindlefoot"],
        )
        self.assertEqual(
            setup.player_board.bench,
            [
                "orange_blazekick",
                "orange_inferno",
                "orange_emberdash",
            ],
        )
        self.assertEqual(setup.assignment_edge, AssignmentEdge.BELOW)
        self.assertEqual(
            setup.attack_direction,
            AttackDirection.LEFT_TO_RIGHT,
        )

    def test_visiting_setup_reverses_canonical_field_direction(self) -> None:
        roster = self.catalog.teams[Team.TEAL]
        setup = create_standard_setup(
            roster,
            TeamSide.VISITING,
            self.rules,
        )

        self.assertEqual(
            setup.zones[Zone.VISITORS_GOAL],
            ["teal_bulwark", "teal_voltus"],
        )
        self.assertEqual(
            setup.zones[Zone.MIDFIELD],
            ["teal_strider", "teal_synapse"],
        )
        self.assertEqual(
            setup.zones[Zone.HOME_GOAL],
            ["teal_quantor", "teal_pulsar"],
        )
        self.assertEqual(setup.assignment_edge, AssignmentEdge.ABOVE)
        self.assertEqual(
            setup.attack_direction,
            AttackDirection.RIGHT_TO_LEFT,
        )

    def test_player_board_dice(self) -> None:
        player_board = self.rules.player_board
        self.assertEqual(
            (player_board.offense_die.sides, player_board.offense_die.color),
            (6, "crimson"),
        )
        self.assertEqual(
            (player_board.defense_die.sides, player_board.defense_die.color),
            (6, "green"),
        )
        self.assertEqual(
            (player_board.team_die.sides, player_board.team_die.color),
            (12, "team"),
        )

    def test_standard_match_synchronizes_cards_and_meeples(self) -> None:
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.TEAL,
        )

        match.validate(self.catalog)
        fielded = set(
            match.home.field_players + match.visiting.field_players
        )
        meeples = {
            player_id
            for spaces in match.board.spaces.values()
            for occupants in spaces
            for player_id in occupants
        }
        self.assertEqual(meeples, fielded)
        self.assertEqual(len(meeples), 12)
        self.assertTrue(
            all(
                match.board.meeple_position(player_id) is None
                for player_id in (
                    match.home.player_board.bench
                    + match.visiting.player_board.bench
                )
            )
        )
        self.assertEqual(
            match.board.meeple_position("orange_hellguard"),
            (Zone.HOME_GOAL, 0),
        )
        self.assertEqual(
            match.board.meeple_position("orange_blazebulk"),
            (Zone.HOME_GOAL, 1),
        )
        self.assertEqual(
            match.board.meeple_position("orange_sizzik"),
            (Zone.MIDFIELD, 0),
        )
        self.assertEqual(
            match.board.meeple_position("orange_scorchit"),
            (Zone.MIDFIELD, 1),
        )
        self.assertEqual(
            match.board.meeple_position("orange_kindlefoot"),
            (Zone.VISITORS_GOAL, 1),
        )
        self.assertEqual(
            match.board.meeple_position("teal_bulwark"),
            (Zone.VISITORS_GOAL, 1),
        )
        self.assertEqual(
            match.board.meeple_position("teal_strider"),
            (Zone.MIDFIELD, 2),
        )
        self.assertEqual(
            match.board.meeple_position("teal_synapse"),
            (Zone.MIDFIELD, 1),
        )
        self.assertEqual(
            match.board.meeple_position("teal_pulsar"),
            (Zone.HOME_GOAL, 0),
        )
        self.assertEqual(match.ball.zone, Zone.MIDFIELD)
        self.assertEqual(match.ball.space_index, 1)
        self.assertEqual(match.ball.possession, TeamSide.HOME)
        self.assertEqual(match.ball.speed, 1)
        self.assertEqual(
            match.eligible_ball_handlers(),
            ["orange_scorchit"],
        )
        self.assertEqual(match.scoreboard.home_score, 0)
        self.assertEqual(match.scoreboard.visiting_score, 0)
        self.assertEqual(match.scoreboard.time, 0)

    def test_ball_handler_must_share_ball_space_and_possession(self) -> None:
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.TEAL,
        )
        match.move_meeple(
            "orange_sizzik",
            Zone.MIDFIELD,
            1,
        )

        self.assertEqual(
            match.eligible_ball_handlers(),
            ["orange_scorchit", "orange_sizzik"],
        )
        with self.assertRaises(ValueError):
            match.select_ball_handler("teal_synapse")

        match.select_ball_handler("orange_sizzik")
        match.validate(self.catalog)
        restored = MatchState.from_dict(
            match.to_dict(),
            self.rules,
        )
        self.assertEqual(restored.active_player_id, "orange_sizzik")

    def test_substitution_swaps_card_and_meeple_state(self) -> None:
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=6,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
        )

        match.substitute(
            side=TeamSide.HOME,
            fielded_player_id="orange_blazebulk",
            bench_player_id="orange_inferno",
            zone=Zone.HOME_GOAL,
            space_index=1,
        )

        self.assertIn(
            "orange_inferno",
            match.home.zones[Zone.HOME_GOAL],
        )
        self.assertIn(
            "orange_blazebulk",
            match.home.player_board.bench,
        )
        self.assertIsNone(
            match.board.meeple_position("orange_blazebulk")
        )
        self.assertEqual(
            match.board.meeple_position("orange_inferno"),
            (Zone.HOME_GOAL, 1),
        )
        match.validate(self.catalog)

    def test_match_state_round_trip(self) -> None:
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=9,
            home_team=Team.SLIME,
            visiting_team=Team.TEAL,
        )
        restored = MatchState.from_dict(match.to_dict(), self.rules)
        restored.validate(self.catalog)
        self.assertEqual(restored.to_dict(), match.to_dict())

    def test_setup_overview_renders_as_png(self) -> None:
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.TEAL,
        )
        image_data = render_match_image(match, self.catalog)

        with Image.open(image_data) as image:
            self.assertEqual(image.format, "PNG")
            self.assertEqual(image.size, (2200, 1280))


if __name__ == "__main__":
    unittest.main()
