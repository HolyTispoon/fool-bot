import unittest
from pathlib import Path
from unittest import mock

from PIL import Image, ImageFont

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
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.game import Team
from d12ball.render import (
    FONT_BODY,
    FONT_DIR,
    FONT_HEADING,
    FONT_SCORE,
    FONT_SMALL,
    FONT_TITLE,
    load_font,
    render_dice_row,
    render_maneuver_reference_image,
    render_match_image,
)


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

    def test_maneuver_choice_round_trip_and_reset(self) -> None:
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=9,
            home_team=Team.SLIME,
            visiting_team=Team.TEAL,
        )
        match.choose_offense_maneuver("Low Pass")
        match.choose_defense_maneuver("Pressure")

        with self.assertRaises(ValueError):
            match.choose_offense_maneuver("High Pass")
        with self.assertRaises(ValueError):
            match.choose_defense_maneuver("Block Deflect")

        restored = MatchState.from_dict(match.to_dict(), self.rules)
        self.assertEqual(restored.offense_maneuver, "Low Pass")
        self.assertEqual(restored.defense_maneuver, "Pressure")

        match.reset_maneuver()
        self.assertIsNone(match.active_player_id)
        self.assertIsNone(match.pending_action)
        self.assertIsNone(match.challenger_id)
        self.assertIsNone(match.offense_maneuver)
        self.assertIsNone(match.defense_maneuver)

    def test_mark_exhausted_if_needed_transitions_once(self) -> None:
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=9,
            home_team=Team.SLIME,
            visiting_team=Team.TEAL,
        )
        player_id = "teal_bulwark"

        match.add_exhaustion(player_id, 2)
        self.assertFalse(match.mark_exhausted_if_needed(player_id, 2))
        self.assertNotIn(player_id, match.exhausted)

        match.add_exhaustion(player_id, 1)
        self.assertTrue(match.mark_exhausted_if_needed(player_id, 2))
        self.assertIn(player_id, match.exhausted)

        # Already exhausted: further calls report no new transition.
        match.add_exhaustion(player_id, 1)
        self.assertFalse(match.mark_exhausted_if_needed(player_id, 2))

    def test_mark_injured_and_round_trip(self) -> None:
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=9,
            home_team=Team.SLIME,
            visiting_team=Team.TEAL,
        )
        match.add_exhaustion("teal_bulwark", 3)
        match.mark_exhausted_if_needed("teal_bulwark", 2)
        match.mark_injured("teal_bulwark")

        restored = MatchState.from_dict(match.to_dict(), self.rules)
        self.assertEqual(restored.exhausted, {"teal_bulwark"})
        self.assertEqual(restored.injured, {"teal_bulwark"})

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


class D12BallScoreAttemptTests(unittest.TestCase):
    """
    The geometry a score attempt is built on: which defenders stand
    between the ball and the goal, and how many spaces the ball travels
    to get there.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    def build_match(self, board_size: int) -> MatchState:
        return MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=board_size,
            home_team=Team.ORANGE,
            visiting_team=Team.TEAL,
        )

    def defender_roles(self, match: MatchState) -> list[PlayerRole]:
        return [
            self.catalog.player_by_id(player_id).role
            for player_id in match.defenders_between_ball_and_goal()
        ]

    def test_spaces_in_order_matches_flat_index(self) -> None:
        match = self.build_match(7)
        ordered = match.board.spaces_in_order()

        self.assertEqual(len(ordered), 7)
        for zone in Zone:
            for space_index in range(len(match.board.spaces[zone])):
                flat = match.board.flat_index(zone, space_index)
                self.assertIs(
                    ordered[flat],
                    match.board.spaces[zone][space_index],
                )

    def test_home_shot_counts_spaces_and_defenders_to_the_high_end(
        self,
    ) -> None:
        """
        The rules' worked example: a home shot from the third space of a
        6-board travels 3 spaces and faces every visiting meeple from
        the ball's own space outwards.
        """
        match = self.build_match(6)

        self.assertEqual(match.ball.possession, TeamSide.HOME)
        self.assertEqual(
            match.board.flat_index(
                match.ball.zone,
                match.ball.space_index,
            ),
            3,
        )
        self.assertEqual(match.spaces_to_goal(), 3)
        self.assertEqual(
            self.defender_roles(match),
            [
                PlayerRole.MIDFIELDER,
                PlayerRole.DEFENDER,
                PlayerRole.FULLBACK,
            ],
        )

        # Every defender counted is a visiting player, and the meeple
        # sharing the ball's own space is one of them.
        defenders = match.defenders_between_ball_and_goal()
        self.assertTrue(
            set(defenders).issubset(set(match.visiting.field_players))
        )
        self.assertIn(
            defenders[0],
            match.board.spaces[match.ball.zone][match.ball.space_index],
        )

    def test_visiting_shot_runs_the_other_way(self) -> None:
        """
        From the same space, the visitors shoot towards the low end of
        the board, so both the distance and the defenders differ.
        """
        match = self.build_match(6)
        match.ball.possession = TeamSide.VISITING

        self.assertEqual(match.spaces_to_goal(), 4)
        self.assertEqual(
            self.defender_roles(match),
            [
                PlayerRole.PLAYMAKER,
                PlayerRole.MIDFIELDER,
                PlayerRole.DEFENDER,
                PlayerRole.FULLBACK,
            ],
        )
        self.assertTrue(
            set(match.defenders_between_ball_and_goal()).issubset(
                set(match.home.field_players)
            )
        )

    def test_spaces_to_goal_spans_exactly_the_defenders_scanned(
        self,
    ) -> None:
        """
        A score attempt's time cost and its defender search cover the
        same run of spaces, from every space of every board size and for
        either team in possession.
        """
        for board_size in (6, 7, 9):
            match = self.build_match(board_size)
            for zone in Zone:
                for space_index in range(len(match.board.spaces[zone])):
                    for side in TeamSide:
                        with self.subTest(
                            board_size=board_size,
                            space=(zone.value, space_index),
                            possession=side.value,
                        ):
                            match.ball.zone = zone
                            match.ball.space_index = space_index
                            match.ball.possession = side

                            flat = match.board.flat_index(zone, space_index)
                            expected = (
                                board_size - flat
                                if side == TeamSide.HOME
                                else flat + 1
                            )
                            self.assertEqual(
                                match.spaces_to_goal(),
                                expected,
                            )

                            # Nobody behind the ball is ever counted.
                            for player_id in (
                                match.defenders_between_ball_and_goal()
                            ):
                                position = match.board.meeple_position(
                                    player_id
                                )
                                defender_flat = match.board.flat_index(
                                    *position
                                )
                                if side == TeamSide.HOME:
                                    self.assertGreaterEqual(
                                        defender_flat,
                                        flat,
                                    )
                                else:
                                    self.assertLessEqual(
                                        defender_flat,
                                        flat,
                                    )

    def test_an_empty_path_leaves_the_defence_with_no_skill(self) -> None:
        match = self.build_match(6)
        match.ball.zone = Zone.VISITORS_GOAL
        match.ball.space_index = 1

        fullback_id = next(
            player_id
            for player_id in match.visiting.field_players
            if self.catalog.player_by_id(player_id).role
            == PlayerRole.FULLBACK
        )
        match.move_meeple(fullback_id, Zone.HOME_GOAL, 0)

        self.assertEqual(match.defenders_between_ball_and_goal(), [])
        self.assertEqual(match.spaces_to_goal(), 1)
        match.validate(self.catalog)

    def test_defending_side_follows_possession(self) -> None:
        match = self.build_match(7)

        self.assertEqual(match.defending_side(), TeamSide.VISITING)
        match.ball.possession = TeamSide.VISITING
        self.assertEqual(match.defending_side(), TeamSide.HOME)

    def test_a_pending_shoot_survives_a_save_and_reload(self) -> None:
        """
        The cog restores the roll button on startup from a pending
        "shoot", so it has to round-trip, and resolving has to clear it.
        """
        match = self.build_match(7)
        match.select_ball_handler(match.eligible_ball_handlers()[0])
        match.pending_action = "shoot"

        restored = MatchState.from_dict(match.to_dict(), self.rules)
        restored.validate(self.catalog)
        self.assertEqual(restored.pending_action, "shoot")
        self.assertIsNotNone(restored.active_player_id)

        restored.reset_maneuver()
        self.assertIsNone(restored.pending_action)
        self.assertIsNone(restored.active_player_id)


class D12BallManeuverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_maneuver_catalog()

    def test_catalog_has_three_offense_and_defense_maneuvers(self) -> None:
        self.assertEqual(len(self.catalog.offense), 3)
        self.assertEqual(len(self.catalog.defense), 3)

    def test_die_faces_cover_one_through_six_with_no_overlap(self) -> None:
        for value in range(1, 7):
            self.catalog.offense_for_die(value)
            self.catalog.defense_for_die(value)

    def test_matchup_triangle_resolves_as_expected(self) -> None:
        expected = {
            ("Low Pass", "Block Deflect"): "tie",
            ("Low Pass", "Steal Intercept"): "defense",
            ("Low Pass", "Pressure"): "offense",
            ("Dribble Advance", "Block Deflect"): "offense",
            ("Dribble Advance", "Steal Intercept"): "tie",
            ("Dribble Advance", "Pressure"): "defense",
            ("High Pass", "Block Deflect"): "defense",
            ("High Pass", "Steal Intercept"): "offense",
            ("High Pass", "Pressure"): "tie",
        }
        for (offense_name, defense_name), outcome in expected.items():
            self.assertEqual(
                self.catalog.resolve(offense_name, defense_name),
                outcome,
                f"{offense_name} vs {defense_name}",
            )

    def test_reference_image_renders_as_png(self) -> None:
        image_data = render_maneuver_reference_image(self.catalog)

        with Image.open(image_data) as image:
            self.assertEqual(image.format, "PNG")

    def test_dice_row_renders_one_die_per_entry(self) -> None:
        image_data = render_dice_row(
            [(7, "#f28c28", "Orange"), (12, "#19b5a5", "Teal")]
        )

        with Image.open(image_data) as image:
            self.assertEqual(image.format, "PNG")
            self.assertEqual(image.width, 480)


class D12BallFontTests(unittest.TestCase):
    """Guard the bundled fonts.

    A host without system fonts used to fall through to Pillow's built-in
    face, which is pinned to size 10 and ignores the requested size, so
    every label on the board rendered at the same tiny size.
    """

    def test_bundled_font_files_exist(self) -> None:
        for file_name in ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf"):
            self.assertTrue(
                (FONT_DIR / file_name).is_file(),
                f"Missing bundled font {FONT_DIR / file_name}",
            )

    def test_load_font_honours_requested_size(self) -> None:
        for size in (14, 28, 44, 52):
            for bold in (False, True):
                with self.subTest(size=size, bold=bold):
                    font = load_font(size, bold=bold)
                    self.assertEqual(font.size, size)

    def test_load_font_uses_bundled_files_not_system_fonts(self) -> None:
        # Simulate a host where every lookup by bare name misses, as it
        # does anywhere the installed fonts are filed under other names.
        real_truetype = ImageFont.truetype

        def only_absolute_paths(font=None, size=10, *args, **kwargs):
            if isinstance(font, str) and not Path(font).is_absolute():
                raise OSError("cannot open resource")
            return real_truetype(font, size, *args, **kwargs)

        with mock.patch.object(
            ImageFont, "truetype", side_effect=only_absolute_paths
        ):
            font = load_font(44, bold=True)

        self.assertEqual(font.size, 44)
        self.assertEqual(
            Path(font.path).name,
            "DejaVuSans-Bold.ttf",
        )

    def test_render_fonts_keep_their_relative_scale(self) -> None:
        # The bug's signature was every font collapsing to one size.
        self.assertGreater(FONT_SCORE.size, FONT_TITLE.size)
        self.assertGreater(FONT_TITLE.size, FONT_HEADING.size)
        self.assertGreater(FONT_HEADING.size, FONT_BODY.size)
        self.assertGreater(FONT_BODY.size, FONT_SMALL.size)

    def test_bundled_font_covers_board_label_glyphs(self) -> None:
        # The em dash in the player board heading rendered as a tofu box
        # under the fallback face.
        font = load_font(28)
        for character in "—:!":
            with self.subTest(character=character):
                self.assertTrue(
                    font.getmask(character).getbbox(),
                    f"No glyph for {character!r}",
                )


if __name__ == "__main__":
    unittest.main()
