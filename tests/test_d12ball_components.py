import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from PIL import Image, ImageFont

from cogs.d12ball import HIGH_PASS_CONTEST_HEADLINE, D12Ball
from d12ball.components import (
    AssignmentEdge,
    AttackDirection,
    BoardState,
    MatchState,
    PlayerRole,
    TeamSide,
    Zone,
    create_standard_setup,
    kickoff_space_index,
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

    def test_every_player_has_a_portrait_image(self) -> None:
        for roster in self.catalog.teams.values():
            for player in roster.players:
                image_path = (
                    PROJECT_ROOT
                    / "d12ball"
                    / "images"
                    / "player_images"
                    / f"{player.name}.png"
                )
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

    def test_validate_tolerates_a_stale_active_player_mid_resolution(
        self,
    ) -> None:
        """
        Once both sides have picked a maneuver, resolving it is free to
        move the ball away from active_player_id (a pass) or flip
        possession without moving the challenger (Steal Intercept) --
        validate() must not treat that as corruption while
        reset_maneuver() hasn't run yet, but it must still catch a
        genuinely stale active_player_id at any other time.
        """
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.TEAL,
        )
        match.select_ball_handler(match.eligible_ball_handlers()[0])
        match.pending_action = "maneuver"
        challenger_id = match.eligible_challengers()[0]
        match.choose_challenger(challenger_id)
        match.choose_offense_maneuver("Low Pass")
        match.choose_defense_maneuver("Steal Intercept")

        # Simulate a turnover moving the ball away from both players.
        match.move_ball_relative(TeamSide.VISITING, 3)
        match.ball.possession = TeamSide.VISITING
        match.validate(self.catalog)  # must not raise

        # Once the maneuver is actually reset, the same stale id must
        # be caught again like any other time.
        match.reset_maneuver()
        match.active_player_id = challenger_id
        with self.assertRaises(ValueError):
            match.validate(self.catalog)

    def standard_match(self, board_size: int = 6) -> MatchState:
        return MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=board_size,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
        )

    def test_substitution_swaps_card_and_meeple_state(self) -> None:
        match = self.standard_match()
        outgoing = "orange_blazebulk"
        incoming = match.home.player_board.bench[0]
        position = match.board.meeple_position(outgoing)

        match.substitute(
            side=TeamSide.HOME,
            fielded_player_id=outgoing,
            incoming_player_id=incoming,
        )

        # The player coming on inherits both the zone assignment and
        # the space, so a substitution never moves anyone by itself.
        self.assertIn(incoming, match.home.zones[Zone.HOME_GOAL])
        self.assertEqual(match.board.meeple_position(incoming), position)
        self.assertIsNone(match.board.meeple_position(outgoing))
        match.validate(self.catalog)

    def test_subbed_out_player_goes_to_the_back_bench(self) -> None:
        match = self.standard_match()
        outgoing = "orange_blazebulk"
        incoming = match.home.player_board.bench[0]

        match.substitute(TeamSide.HOME, outgoing, incoming)

        self.assertIn(outgoing, match.home.player_board.back_bench)
        self.assertNotIn(outgoing, match.home.player_board.bench)
        self.assertNotIn(incoming, match.home.player_board.bench)

        # The bench only ever drains, so it can never be the route
        # back on for someone who has already been subbed out.
        self.assertNotIn(
            outgoing,
            match.substitution_pool(TeamSide.HOME, "orange_kindlefoot"),
        )

    def test_back_bench_is_closed_until_the_bench_empties(self) -> None:
        match = self.standard_match()
        injured = "orange_kindlefoot"
        match.mark_injured(injured)

        # The bench still has people on it, so it is the only pool --
        # even for an injured player's replacement.
        self.assertEqual(
            match.substitution_pool(TeamSide.HOME, injured),
            match.home.player_board.bench,
        )

        for outgoing in ("orange_hellguard", "orange_sizzik", "orange_scorchit"):
            match.substitute(
                TeamSide.HOME,
                outgoing,
                match.home.player_board.bench[0],
            )
        self.assertEqual(match.home.player_board.bench, [])

        # Empty bench: a healthy player has nobody to bring on, but an
        # injured one reopens the back bench.
        self.assertEqual(
            match.substitution_pool(TeamSide.HOME, "orange_flickerwing"),
            [],
        )
        self.assertEqual(
            sorted(match.substitution_pool(TeamSide.HOME, injured)),
            sorted(match.home.player_board.back_bench),
        )

    def test_injured_players_never_come_back(self) -> None:
        match = self.standard_match()
        injured = "orange_kindlefoot"
        match.mark_injured(injured)
        match.substitute(
            TeamSide.HOME, injured, match.home.player_board.bench[0],
        )
        for outgoing in ("orange_hellguard", "orange_sizzik"):
            match.substitute(
                TeamSide.HOME,
                outgoing,
                match.home.player_board.bench[0],
            )

        self.assertEqual(match.home.player_board.bench, [])
        self.assertIn(injured, match.home.player_board.back_bench)

        # A second injury opens the back bench, but not to the player
        # who limped off it.
        match.mark_injured("orange_scorchit")
        pool = match.substitution_pool(TeamSide.HOME, "orange_scorchit")
        self.assertNotIn(injured, pool)
        with self.assertRaises(ValueError):
            match.substitute(TeamSide.HOME, "orange_scorchit", injured)

    def test_returning_player_loses_half_their_tokens(self) -> None:
        match = self.standard_match()
        returning = "orange_hellguard"
        match.add_exhaustion(returning, 5)
        match.mark_exhausted_if_needed(returning, defense_skill=2)
        self.assertIn(returning, match.exhausted)

        match.substitute(
            TeamSide.HOME, returning, match.home.player_board.bench[0],
        )
        for outgoing in ("orange_sizzik", "orange_scorchit"):
            match.substitute(
                TeamSide.HOME,
                outgoing,
                match.home.player_board.bench[0],
            )

        injured = "orange_kindlefoot"
        match.mark_injured(injured)
        match.substitute(TeamSide.HOME, injured, returning)

        # Half of 5 rounded up is 3 removed, leaving 2 -- and 2 is
        # still over a defensive skill of 1, so coming back does not
        # by itself clear Exhausted.
        self.assertEqual(match.exhaustion[returning], 2)
        self.assertNotIn(returning, match.exhausted)
        self.assertTrue(
            match.mark_exhausted_if_needed(returning, defense_skill=1)
        )

    def test_swapping_two_players_keeps_the_formation(self) -> None:
        match = self.standard_match()
        first, second = "orange_hellguard", "orange_kindlefoot"
        first_position = match.board.meeple_position(first)
        second_position = match.board.meeple_position(second)
        self.assertNotEqual(first_position, second_position)

        match.swap_field_positions(TeamSide.HOME, first, second)

        self.assertEqual(match.board.meeple_position(first), second_position)
        self.assertEqual(match.board.meeple_position(second), first_position)
        self.assertEqual(
            match.home.assigned_zone(first), Zone.VISITORS_GOAL,
        )
        self.assertEqual(match.home.assigned_zone(second), Zone.HOME_GOAL)
        self.assertTrue(
            all(len(match.home.zones[zone]) == 2 for zone in Zone)
        )
        self.assertEqual(match.exhaustion, {})
        match.validate(self.catalog)

    def test_a_steals_run_back_exemption_follows_the_position(self) -> None:
        match = self.standard_match()
        stealer = "orange_blazebulk"
        match.pending_run_back_stays_player_id = stealer

        # Subbed off: whoever comes on is standing on the ball now, so
        # running them back would take the ball carrier off the ball.
        incoming = match.home.player_board.bench[0]
        match.substitute(TeamSide.HOME, stealer, incoming)
        self.assertEqual(match.pending_run_back_stays_player_id, incoming)

        # Swapped: the exemption goes to whoever took their place, in
        # either argument order.
        match.swap_field_positions(TeamSide.HOME, incoming, "orange_sizzik")
        self.assertEqual(
            match.pending_run_back_stays_player_id, "orange_sizzik",
        )
        match.swap_field_positions(TeamSide.HOME, incoming, "orange_sizzik")
        self.assertEqual(match.pending_run_back_stays_player_id, incoming)

    def test_an_untouched_exemption_stays_put(self) -> None:
        match = self.standard_match()
        match.pending_run_back_stays_player_id = "orange_blazebulk"

        match.substitute(
            TeamSide.HOME,
            "orange_kindlefoot",
            match.home.player_board.bench[0],
        )
        match.swap_field_positions(
            TeamSide.HOME, "orange_hellguard", "orange_sizzik",
        )

        self.assertEqual(
            match.pending_run_back_stays_player_id, "orange_blazebulk",
        )

    def test_declaration_is_once_a_half_but_a_reply_is_free(self) -> None:
        match = self.standard_match()
        self.assertTrue(match.may_declare_substitution(TeamSide.HOME))

        # Being offered the window spends nothing; passing on it
        # leaves the declaration in hand for a later turnover.
        match.open_substitution_window(TeamSide.HOME)
        self.assertTrue(match.may_declare_substitution(TeamSide.HOME))
        match.close_substitution_window()
        self.assertTrue(match.may_declare_substitution(TeamSide.HOME))

        match.open_substitution_window(TeamSide.HOME)
        match.declare_substitution()
        self.assertEqual(match.substitutions_remaining(), 2)
        match.pending_substitution_used = 2
        self.assertEqual(match.substitutions_remaining(), 0)
        match.close_substitution_window()

        self.assertFalse(match.may_declare_substitution(TeamSide.HOME))

        # Answering the other team's declaration is one sub and costs
        # the answering team nothing, so the visitors can still
        # declare their own later in the half.
        match.open_substitution_window(TeamSide.VISITING, is_response=True)
        match.declare_substitution()
        self.assertEqual(match.substitutions_remaining(), 1)
        match.close_substitution_window()
        self.assertTrue(match.may_declare_substitution(TeamSide.VISITING))

    def test_an_injury_forces_a_declaration_only_while_possible(
        self,
    ) -> None:
        match = self.standard_match()
        self.assertFalse(match.must_declare_substitution(TeamSide.HOME))

        match.mark_injured("orange_kindlefoot")
        self.assertTrue(match.must_declare_substitution(TeamSide.HOME))

        # Already declared this half -- the injured player stays on,
        # disadvantaged, until the next one.
        match.declared_substitution.add(TeamSide.HOME.value)
        self.assertFalse(match.must_declare_substitution(TeamSide.HOME))

    def test_substitution_state_round_trips(self) -> None:
        match = self.standard_match()
        match.declared_substitution.add(TeamSide.HOME.value)
        match.open_substitution_window(TeamSide.VISITING, is_response=True)
        match.declare_substitution()
        match.pending_substitution_used = 1

        restored = MatchState.from_dict(match.to_dict(), self.rules)

        self.assertEqual(
            restored.declared_substitution, {TeamSide.HOME.value},
        )
        self.assertEqual(
            restored.pending_substitution_side, TeamSide.VISITING.value,
        )
        self.assertTrue(restored.pending_substitution_is_response)
        self.assertEqual(restored.substitutions_remaining(), 0)

    def test_saved_games_without_substitution_state_still_load(
        self,
    ) -> None:
        match = self.standard_match()
        data = match.to_dict()
        for key in list(data):
            if "substitution" in key:
                del data[key]

        restored = MatchState.from_dict(data, self.rules)

        self.assertEqual(restored.declared_substitution, set())
        self.assertIsNone(restored.pending_substitution_side)
        self.assertTrue(restored.may_declare_substitution(TeamSide.HOME))

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

        self.assertEqual(match.exhaustion.get("teal_bulwark", 0), 0)
        self.assertNotIn("teal_bulwark", match.exhausted)

        match.add_exhaustion("teal_bulwark", 5)
        self.assertEqual(match.exhaustion.get("teal_bulwark", 0), 0)
        self.assertFalse(
            match.mark_exhausted_if_needed("teal_bulwark", 2)
        )

        restored = MatchState.from_dict(match.to_dict(), self.rules)
        self.assertEqual(restored.exhaustion.get("teal_bulwark", 0), 0)
        self.assertNotIn("teal_bulwark", restored.exhausted)
        self.assertEqual(restored.injured, {"teal_bulwark"})

    def test_old_injured_save_is_normalized_on_load(self) -> None:
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=7,
            home_team=Team.SLIME,
            visiting_team=Team.TEAL,
        )
        saved = match.to_dict()
        saved["injured"] = ["teal_bulwark"]
        saved["exhausted"] = ["teal_bulwark"]
        saved["exhaustion"] = {"teal_bulwark": 6}

        restored = MatchState.from_dict(saved, self.rules)

        self.assertEqual(restored.injured, {"teal_bulwark"})
        self.assertNotIn("teal_bulwark", restored.exhausted)
        self.assertNotIn("teal_bulwark", restored.exhaustion)

    def test_fielded_players_in_zone(self) -> None:
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=9,
            home_team=Team.SLIME,
            visiting_team=Team.TEAL,
        )
        home_players = match.fielded_players_in_zone(
            TeamSide.HOME, Zone.HOME_GOAL,
        )
        self.assertEqual(
            set(home_players), set(match.home.zones[Zone.HOME_GOAL]),
        )

        visiting_players = match.fielded_players_in_zone(
            TeamSide.VISITING, Zone.HOME_GOAL,
        )
        self.assertEqual(
            set(visiting_players),
            set(match.visiting.zones[Zone.HOME_GOAL]),
        )

    def test_loose_ball_picks_round_trip_and_reset(self) -> None:
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=9,
            home_team=Team.SLIME,
            visiting_team=Team.TEAL,
        )
        match.begin_loose_ball(2)
        match.choose_loose_ball_offense_player("slime_goopkeeper")
        match.choose_loose_ball_defense_player("teal_bulwark")

        with self.assertRaises(ValueError):
            match.choose_loose_ball_offense_player("slime_gurgoth")
        with self.assertRaises(ValueError):
            match.choose_loose_ball_defense_player("teal_strider")

        restored = MatchState.from_dict(match.to_dict(), self.rules)
        self.assertTrue(restored.pending_loose_ball)
        self.assertEqual(restored.pending_loose_ball_distance, 2)
        self.assertEqual(
            restored.loose_ball_offense_player, "slime_goopkeeper",
        )
        self.assertEqual(
            restored.loose_ball_defense_player, "teal_bulwark",
        )

        match.reset_maneuver()
        self.assertFalse(match.pending_loose_ball)
        self.assertEqual(match.pending_loose_ball_distance, 1)
        self.assertIsNone(match.loose_ball_offense_player)
        self.assertIsNone(match.loose_ball_defense_player)

    def test_run_back_distance_and_turnover_round_trip(self) -> None:
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=9,
            home_team=Team.SLIME,
            visiting_team=Team.TEAL,
        )
        match.pending_run_back = True
        match.pending_run_back_distance = 3
        match.pending_run_back_turnover = False

        restored = MatchState.from_dict(match.to_dict(), self.rules)
        self.assertEqual(restored.pending_run_back_distance, 3)
        self.assertFalse(restored.pending_run_back_turnover)

        match.reset_maneuver()
        self.assertEqual(match.pending_run_back_distance, 1)
        self.assertTrue(match.pending_run_back_turnover)

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
            self.assertEqual(image.size, (3300, 1920))


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
        match.ball.zone = Zone.MIDFIELD
        match.ball.space_index = 1

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
        match.ball.zone = Zone.MIDFIELD
        match.ball.space_index = 1
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

    def test_is_ball_at_scoring_space(self) -> None:
        match = self.build_match(7)
        match.ball.zone = Zone.HOME_GOAL
        match.ball.space_index = 0
        match.ball.possession = TeamSide.HOME
        self.assertFalse(match.is_ball_at_scoring_space())

        match.ball.possession = TeamSide.VISITING
        self.assertTrue(match.is_ball_at_scoring_space())

    def test_own_goal_restart_space_is_closest_to_that_side_own_goal(
        self,
    ) -> None:
        for board_size in (6, 7, 9):
            match = self.build_match(board_size)

            self.assertEqual(
                match.own_goal_restart_space(TeamSide.HOME),
                (Zone.HOME_GOAL, 0),
            )
            self.assertEqual(
                match.own_goal_restart_space(TeamSide.VISITING),
                (
                    Zone.VISITORS_GOAL,
                    len(match.board.spaces[Zone.VISITORS_GOAL]) - 1,
                ),
            )

    def test_defending_side_follows_possession(self) -> None:
        match = self.build_match(7)

        self.assertEqual(match.defending_side(), TeamSide.VISITING)
        match.ball.possession = TeamSide.VISITING
        self.assertEqual(match.defending_side(), TeamSide.HOME)

    def test_award_goal_credits_whoever_has_the_ball(self) -> None:
        match = self.build_match(7)

        match.award_goal()
        self.assertEqual(match.scoreboard.home_score, 1)
        self.assertEqual(match.scoreboard.visiting_score, 0)

        match.ball.possession = TeamSide.VISITING
        match.award_goal()
        match.award_goal()
        self.assertEqual(match.scoreboard.home_score, 1)
        self.assertEqual(match.scoreboard.visiting_score, 2)

        # Scores have no ceiling, so a goal can never leave the
        # scoreboard in a state that fails to reload.
        for _ in range(20):
            match.award_goal()
        restored = MatchState.from_dict(match.to_dict(), self.rules)
        self.assertEqual(restored.scoreboard.visiting_score, 22)

    def test_concede_own_goal_credits_the_other_side(self) -> None:
        match = self.build_match(7)

        match.concede_own_goal()
        self.assertEqual(match.scoreboard.home_score, 0)
        self.assertEqual(match.scoreboard.visiting_score, 1)

        match.ball.possession = TeamSide.VISITING
        match.concede_own_goal()
        self.assertEqual(match.scoreboard.home_score, 1)
        self.assertEqual(match.scoreboard.visiting_score, 1)

    def test_goal_restart_gives_conceding_team_midfield_and_speed_one(
        self,
    ) -> None:
        for side in TeamSide:
            with self.subTest(side=side):
                match = self.build_match(6)
                match.ball.speed = 9

                match.restart_after_goal(side)

                self.assertEqual(match.ball.possession, side)
                self.assertEqual(match.ball.zone, Zone.MIDFIELD)
                self.assertEqual(
                    match.ball.space_index,
                    kickoff_space_index(
                        len(match.board.spaces[Zone.MIDFIELD]), side,
                    ),
                )
                self.assertEqual(match.ball.speed, 1)

    def test_missed_score_restart_is_a_turnover_at_speed_one(self) -> None:
        match = self.build_match(7)
        match.ball.speed = 8

        match.restart_after_missed_score(TeamSide.VISITING)

        self.assertEqual(match.ball.possession, TeamSide.VISITING)
        self.assertEqual(
            (match.ball.zone, match.ball.space_index),
            match.own_goal_restart_space(TeamSide.VISITING),
        )
        self.assertEqual(match.ball.speed, 1)

    def test_advance_time_clamps_and_flags_last_possession_once(
        self,
    ) -> None:
        match = self.build_match(7)

        self.assertFalse(match.advance_time(3))
        self.assertEqual(match.scoreboard.time, 3)
        self.assertFalse(match.scoreboard.last_possession)

        self.assertTrue(match.advance_time(20))
        self.assertEqual(match.scoreboard.time, 15)
        self.assertTrue(match.scoreboard.last_possession)

        # Once in last possession, further advances are no-ops.
        self.assertFalse(match.advance_time(5))
        self.assertEqual(match.scoreboard.time, 15)

    def test_kickoff_space_index_matches_the_rules_fix(self) -> None:
        # 7/9-boards: true middle regardless of who's kicking off.
        self.assertEqual(kickoff_space_index(3, TeamSide.HOME), 1)
        self.assertEqual(kickoff_space_index(3, TeamSide.VISITING), 1)
        # 6-board: biased toward the kicking team's own goal.
        self.assertEqual(kickoff_space_index(2, TeamSide.HOME), 0)
        self.assertEqual(kickoff_space_index(2, TeamSide.VISITING), 1)

    def test_standard_match_uses_the_fixed_six_board_kickoff(self) -> None:
        match = self.build_match(6)
        self.assertEqual(match.ball.zone, Zone.MIDFIELD)
        self.assertEqual(match.ball.space_index, 0)

    def test_set_ball_space_allows_an_empty_destination(self) -> None:
        match = self.build_match(7)
        # A standard 7v7 has no fully empty space anywhere on the board
        # -- clear one by hand to exercise move_ball's usual blocker.
        match.board.remove_meeple("orange_flickerwing")
        match.board.remove_meeple("teal_voltus")
        self.assertEqual(match.board.spaces[Zone.VISITORS_GOAL][0], [])

        match.set_ball_space(Zone.VISITORS_GOAL, 0)
        self.assertEqual(match.ball.zone, Zone.VISITORS_GOAL)
        self.assertEqual(match.ball.space_index, 0)
        # Possession is untouched -- callers apply a turnover separately.
        self.assertEqual(match.ball.possession, TeamSide.HOME)

    def test_run_back_moves_a_displaced_player_and_reports_distance(
        self,
    ) -> None:
        match = self.build_match(7)
        home_midfielder = match.home.zones[Zone.MIDFIELD][0]

        # Walk them out to the visitors' goal zone.
        match.move_meeple(home_midfielder, Zone.VISITORS_GOAL, 0)
        self.assertIn(home_midfielder, match.displaced_players(TeamSide.HOME))

        open_spaces = match.open_spaces_in_zone(TeamSide.HOME, Zone.MIDFIELD)
        distance = match.run_back_player(
            home_midfielder, Zone.MIDFIELD, open_spaces[0]
        )
        self.assertGreater(distance, 0)
        self.assertNotIn(
            home_midfielder, match.displaced_players(TeamSide.HOME)
        )
        self.assertEqual(
            match.board.meeple_position(home_midfielder),
            (Zone.MIDFIELD, open_spaces[0]),
        )

    def test_open_spaces_in_zone_ignores_opposing_meeples(self) -> None:
        match = self.build_match(7)
        # Standard 7-a-side midfield: space 0 is home-only, space 1 has
        # one of each team, space 2 is visiting-only. Only space 2 has
        # no home meeple, so it's the one "open" for a home player --
        # a visiting occupant never blocks it.
        self.assertEqual(
            set(match.open_spaces_in_zone(TeamSide.HOME, Zone.MIDFIELD)),
            {2},
        )

    def test_run_back_rejects_the_wrong_zone_or_a_taken_space(self) -> None:
        match = self.build_match(7)
        home_midfielder = match.home.zones[Zone.MIDFIELD][0]
        other_home_midfielder = match.home.zones[Zone.MIDFIELD][1]
        match.move_meeple(home_midfielder, Zone.VISITORS_GOAL, 0)

        with self.assertRaises(ValueError):
            match.run_back_player(home_midfielder, Zone.HOME_GOAL, 0)

        occupied_space = match.board.meeple_position(
            other_home_midfielder
        )[1]
        with self.assertRaises(ValueError):
            match.run_back_player(
                home_midfielder, Zone.MIDFIELD, occupied_space
            )

    def test_crowded_players_flags_a_same_zone_double_up(self) -> None:
        match = self.build_match(7)
        home_midfielder, other_home_midfielder = match.home.zones[
            Zone.MIDFIELD
        ][:2]
        # Double them up on the same space -- both are still in their
        # own zone, so displaced_players sees nothing wrong.
        other_position = match.board.meeple_position(other_home_midfielder)
        match.move_meeple(home_midfielder, *other_position)

        self.assertNotIn(
            home_midfielder, match.displaced_players(TeamSide.HOME)
        )
        crowded = match.crowded_players(TeamSide.HOME)
        self.assertEqual(len(crowded), 1)
        self.assertIn(crowded[0], (home_midfielder, other_home_midfielder))

    def test_crowded_players_prefers_the_ball_stealer_to_stay(self) -> None:
        match = self.build_match(7)
        home_midfielder, other_home_midfielder = match.home.zones[
            Zone.MIDFIELD
        ][:2]
        other_position = match.board.meeple_position(other_home_midfielder)
        match.move_meeple(home_midfielder, *other_position)

        match.pending_run_back_stays_player_id = other_home_midfielder
        self.assertEqual(
            match.crowded_players(TeamSide.HOME), [home_midfielder]
        )

    def test_crowded_players_caps_at_the_zone_s_open_spaces(self) -> None:
        match = self.build_match(7)
        home_midfielder, other_home_midfielder = match.home.zones[
            Zone.MIDFIELD
        ][:2]
        other_position = match.board.meeple_position(other_home_midfielder)
        match.move_meeple(home_midfielder, *other_position)
        # Fill every other home-open space in the zone (borrowing two
        # other home fielded players) so there is nowhere left for the
        # doubled-up pair to spread out to.
        borrowed = [
            player_id
            for player_id in match.home.field_players
            if player_id not in (home_midfielder, other_home_midfielder)
        ]
        for player_id, space_index in zip(
            borrowed,
            match.open_spaces_in_zone(TeamSide.HOME, Zone.MIDFIELD),
        ):
            match.move_meeple(player_id, Zone.MIDFIELD, space_index)

        self.assertEqual(
            match.open_spaces_in_zone(TeamSide.HOME, Zone.MIDFIELD), []
        )
        self.assertEqual(match.crowded_players(TeamSide.HOME), [])

    def test_move_ball_relative_respects_attack_direction(self) -> None:
        match = self.build_match(7)
        match.ball.zone = Zone.MIDFIELD
        match.ball.space_index = 1
        origin_flat = match.board.flat_index(Zone.MIDFIELD, 1)

        distance = match.move_ball_relative(TeamSide.HOME, 2)
        self.assertEqual(distance, 2)
        self.assertEqual(
            match.board.flat_index(match.ball.zone, match.ball.space_index),
            origin_flat + 2,
        )

        match.ball.zone = Zone.MIDFIELD
        match.ball.space_index = 1
        distance = match.move_ball_relative(TeamSide.VISITING, 2)
        self.assertEqual(distance, 2)
        self.assertEqual(
            match.board.flat_index(match.ball.zone, match.ball.space_index),
            origin_flat - 2,
        )

    def test_move_ball_relative_clamps_at_the_board_edge(self) -> None:
        match = self.build_match(7)
        match.ball.zone = Zone.VISITORS_GOAL
        match.ball.space_index = 1  # the last space, flat index 6

        distance = match.move_ball_relative(TeamSide.HOME, 5)
        self.assertEqual(distance, 0)
        self.assertEqual(
            (match.ball.zone, match.ball.space_index),
            (Zone.VISITORS_GOAL, 1),
        )

    def test_move_player_relative_moves_the_meeple_only(self) -> None:
        match = self.build_match(7)
        home_midfielder = match.home.zones[Zone.MIDFIELD][0]
        ball_flat_before = match.board.flat_index(
            match.ball.zone, match.ball.space_index
        )

        distance = match.move_player_relative(
            home_midfielder, TeamSide.HOME, 1
        )
        self.assertGreaterEqual(distance, 0)
        self.assertEqual(
            match.board.flat_index(match.ball.zone, match.ball.space_index),
            ball_flat_before,
        )

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


class D12BallCheckForLooseBallTests(unittest.IsolatedAsyncioTestCase):
    """
    check_for_loose_ball is the general post-maneuver check every
    maneuver funnels through via finish_maneuver_resolution -- these
    drive it directly against a real MatchState, mocking out only the
    Discord-facing/persistence side effects, the same way
    D12BallRunBackAnnouncementTests exercises begin_run_back.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    def build_cog(self) -> D12Ball:
        cog = object.__new__(D12Ball)
        cog.games = {}
        cog.player_catalog = self.catalog
        cog.team_emojis = {}
        cog.refresh_match_image = mock.AsyncMock()
        cog.begin_loose_ball = mock.AsyncMock()
        cog.begin_run_back = mock.AsyncMock()
        return cog

    def build_match(self) -> MatchState:
        return MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=9,
            home_team=Team.SLIME,
            visiting_team=Team.TEAL,
        )

    async def test_does_nothing_when_the_possessing_team_is_already_there(
        self,
    ) -> None:
        cog = self.build_cog()
        match = self.build_match()
        # Sanity: kickoff drops the ball where a home player already
        # stands, so this is the ordinary case -- no detour.
        self.assertTrue(match.eligible_ball_handlers())

        interaction = SimpleNamespace(
            followup=SimpleNamespace(send=mock.AsyncMock())
        )
        game = SimpleNamespace(match_state=None)

        with mock.patch("cogs.d12ball.save_games"):
            detoured = await cog.check_for_loose_ball(
                interaction, game, match, distance_moved=1,
            )

        self.assertFalse(detoured)
        cog.begin_loose_ball.assert_not_awaited()
        cog.begin_run_back.assert_not_awaited()
        interaction.followup.send.assert_not_awaited()

    async def test_detours_into_begin_loose_ball_when_the_space_is_empty(
        self,
    ) -> None:
        cog = self.build_cog()
        match = self.build_match()
        for player_id in list(match.board.spaces[Zone.MIDFIELD][2]):
            match.board.remove_meeple(player_id)
        match.set_ball_space(Zone.MIDFIELD, 2)
        self.assertFalse(match.eligible_ball_handlers())

        interaction = SimpleNamespace(
            followup=SimpleNamespace(send=mock.AsyncMock())
        )
        game = SimpleNamespace(match_state=None)

        with mock.patch("cogs.d12ball.save_games"):
            detoured = await cog.check_for_loose_ball(
                interaction, game, match, distance_moved=2, lead_in="Lead-in.",
            )

        self.assertTrue(detoured)
        cog.begin_loose_ball.assert_awaited_once_with(
            interaction, game, match, 2, lead_in="Lead-in.",
        )
        cog.begin_run_back.assert_not_awaited()

    async def test_opposing_player_alone_on_the_space_wins_it_uncontested(
        self,
    ) -> None:
        cog = self.build_cog()
        match = self.build_match()
        # Index 2 is never a home space under the standard formation
        # (home only ever occupies index 0 or 1), so clearing it and
        # placing a single visiting player there leaves the ball on a
        # space with only an opposing player -- not empty, but not the
        # possessing team either.
        for player_id in list(match.board.spaces[Zone.MIDFIELD][2]):
            match.board.remove_meeple(player_id)
        visiting_player_id = match.visiting.field_players[0]
        match.move_meeple(visiting_player_id, Zone.MIDFIELD, 2)
        match.set_ball_space(Zone.MIDFIELD, 2)
        self.assertEqual(
            match.board.spaces[Zone.MIDFIELD][2], [visiting_player_id],
        )
        self.assertFalse(match.eligible_ball_handlers())
        self.assertEqual(match.ball.possession, TeamSide.HOME)

        interaction = SimpleNamespace(
            followup=SimpleNamespace(send=mock.AsyncMock())
        )
        game = SimpleNamespace(match_state=None)

        with mock.patch("cogs.d12ball.save_games"):
            detoured = await cog.check_for_loose_ball(
                interaction, game, match, distance_moved=1,
                lead_in="Block Deflect happened.",
            )

        self.assertTrue(detoured)
        self.assertEqual(match.ball.possession, TeamSide.VISITING)
        self.assertEqual(match.ball.speed, 1)
        cog.begin_loose_ball.assert_not_awaited()
        cog.begin_run_back.assert_awaited_once_with(
            interaction, game, match,
            distance_moved=1, turnover_occurred=True,
        )
        announcement = interaction.followup.send.await_args.args[0]
        self.assertIn("Block Deflect happened.", announcement)
        self.assertIn("# Turnover!", announcement)
        self.assertIn("uncontested", announcement)


class D12BallLowHighPassTests(unittest.IsolatedAsyncioTestCase):
    """
    Post-playtest revision: Low Pass has no fixed distance (0-2 spaces
    to a teammate, either direction) and High Pass has a 2-4 space
    choice instead of a fixed 2. These drive low_pass_candidates(),
    apply_low_pass(), apply_high_pass() and the Fullback's Block
    Deflect bonus directly against a real MatchState, mocking out only
    the Discord-facing/persistence side effects -- the same pattern
    D12BallCheckForLooseBallTests uses.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    def build_cog(self) -> D12Ball:
        cog = object.__new__(D12Ball)
        cog.games = {}
        cog.player_catalog = self.catalog
        cog.team_emojis = {}
        cog.refresh_match_image = mock.AsyncMock()
        cog.finish_maneuver_resolution = mock.AsyncMock()
        cog.offer_scoring_attempt_choice = mock.AsyncMock()
        cog.begin_loose_ball = mock.AsyncMock()
        cog.begin_shooter_choice = mock.AsyncMock()
        return cog

    def build_match(self) -> MatchState:
        return MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=9,
            home_team=Team.SLIME,
            visiting_team=Team.TEAL,
        )

    def clear_board(self, match: MatchState) -> None:
        for player_id in match.home.field_players + match.visiting.field_players:
            match.board.remove_meeple(player_id, required=False)

    def player_with_role(
        self, match: MatchState, side: TeamSide, role: PlayerRole,
    ) -> str:
        for player_id in match.setup_for_side(side).field_players:
            if self.catalog.player_by_id(player_id).role == role:
                return player_id
        raise AssertionError(f"no {role} fielded for {side}")

    # -- low_pass_candidates ------------------------------------------

    def test_low_pass_candidates_only_teammate_occupied_spaces(self) -> None:
        match = self.build_match()
        self.clear_board(match)
        home_players = match.home.field_players
        behind, here, ahead = home_players[0], home_players[1], home_players[2]
        visitor = match.visiting.field_players[0]

        match.move_meeple(behind, Zone.HOME_GOAL, 2)  # flat 2 (distance -2)
        match.move_meeple(here, Zone.MIDFIELD, 1)  # flat 4 (distance 0, ball here)
        # flat 3 (distance -1) and flat 5 (distance +1, opponent only)
        # are deliberately left without a home teammate.
        match.move_meeple(visitor, Zone.MIDFIELD, 2)
        match.move_meeple(ahead, Zone.VISITORS_GOAL, 0)  # flat 6 (distance +2)

        match.ball.possession = TeamSide.HOME
        match.set_ball_space(Zone.MIDFIELD, 1)

        cog = self.build_cog()
        self.assertEqual(
            cog.low_pass_candidates(match),
            [(-2, behind), (0, here), (2, ahead)],
        )

    def test_low_pass_candidates_excludes_distances_clamped_off_the_board(
        self,
    ) -> None:
        match = self.build_match()
        self.clear_board(match)
        handler = match.home.field_players[0]
        match.move_meeple(handler, Zone.HOME_GOAL, 0)  # the board's own edge
        match.ball.possession = TeamSide.HOME
        match.set_ball_space(Zone.HOME_GOAL, 0)

        cog = self.build_cog()
        # -1 and -2 would go off the left edge and clamp back to the
        # handler's own space -- not real 1/2-space destinations, so
        # they must not appear even though a teammate is standing
        # there (as distance 0).
        self.assertEqual(cog.low_pass_candidates(match), [(0, handler)])

    # -- apply_low_pass ------------------------------------------------

    async def test_apply_low_pass_moves_ball_for_non_winger(self) -> None:
        cog = self.build_cog()
        match = self.build_match()
        handler = self.player_with_role(
            match, TeamSide.HOME, PlayerRole.DEFENDER,
        )
        match.active_player_id = handler
        match.ball.possession = TeamSide.HOME
        match.set_ball_space(Zone.HOME_GOAL, 0)
        match.ball.speed = 3

        interaction = SimpleNamespace()
        game = SimpleNamespace(match_state=None)
        with mock.patch("cogs.d12ball.save_games"):
            await cog.apply_low_pass(interaction, game, match, 2)

        self.assertEqual(
            (match.ball.zone, match.ball.space_index), (Zone.HOME_GOAL, 2),
        )
        self.assertEqual(match.ball.speed, 4)
        cog.offer_scoring_attempt_choice.assert_not_awaited()
        cog.finish_maneuver_resolution.assert_awaited_once()
        _, kwargs = cog.finish_maneuver_resolution.await_args
        self.assertEqual(kwargs["distance_moved"], 2)
        self.assertIn("moves 2 spaces forward", kwargs["lead_in"])

    async def test_apply_low_pass_zero_distance_still_costs_minimum_time(
        self,
    ) -> None:
        cog = self.build_cog()
        match = self.build_match()
        handler = self.player_with_role(
            match, TeamSide.HOME, PlayerRole.DEFENDER,
        )
        match.active_player_id = handler
        match.ball.possession = TeamSide.HOME
        match.set_ball_space(Zone.MIDFIELD, 1)
        match.ball.speed = 1

        interaction = SimpleNamespace()
        game = SimpleNamespace(match_state=None)
        with mock.patch("cogs.d12ball.save_games"):
            await cog.apply_low_pass(interaction, game, match, 0)

        self.assertEqual(
            (match.ball.zone, match.ball.space_index), (Zone.MIDFIELD, 1),
        )
        self.assertEqual(match.ball.speed, 2)
        _, kwargs = cog.finish_maneuver_resolution.await_args
        self.assertEqual(kwargs["distance_moved"], 1)
        self.assertIn("stays with the same player", kwargs["lead_in"])

    async def test_apply_low_pass_offers_scoring_attempt_for_winger(
        self,
    ) -> None:
        cog = self.build_cog()
        match = self.build_match()
        handler = self.player_with_role(
            match, TeamSide.HOME, PlayerRole.WINGER,
        )
        match.active_player_id = handler
        match.ball.possession = TeamSide.HOME
        match.set_ball_space(Zone.MIDFIELD, 1)
        receiver = next(
            pid for pid in match.home.field_players if pid != handler
        )
        match.move_meeple(receiver, Zone.MIDFIELD, 2)

        interaction = SimpleNamespace()
        game = SimpleNamespace(match_state=None)
        with mock.patch("cogs.d12ball.save_games"):
            await cog.apply_low_pass(interaction, game, match, 1)

        self.assertEqual(
            (match.ball.zone, match.ball.space_index), (Zone.MIDFIELD, 2),
        )
        cog.finish_maneuver_resolution.assert_not_awaited()
        cog.offer_scoring_attempt_choice.assert_awaited_once()
        _, kwargs = cog.offer_scoring_attempt_choice.await_args
        self.assertEqual(kwargs["shooter_id"], receiver)
        self.assertEqual(kwargs["decline_kind"], "regular_pass")
        self.assertEqual(kwargs["distance_moved"], 1)
        self.assertIn("Winger ability", kwargs["lead_in"])

    # -- apply_high_pass ------------------------------------------------

    async def test_apply_high_pass_distance_two_overshoot_offers_setup(
        self,
    ) -> None:
        cog = self.build_cog()
        match = self.build_match()
        handler = self.player_with_role(
            match, TeamSide.HOME, PlayerRole.DEFENDER,
        )
        match.active_player_id = handler
        match.ball.possession = TeamSide.HOME
        match.set_ball_space(Zone.VISITORS_GOAL, 1)  # flat 7, 2 overshoots
        shooter = match.home.field_players[0]
        match.move_meeple(shooter, Zone.VISITORS_GOAL, 2)  # flat 8, landing

        interaction = SimpleNamespace()
        game = SimpleNamespace(match_state=None)
        with mock.patch("cogs.d12ball.save_games"):
            await cog.apply_high_pass(interaction, game, match, 2)

        self.assertEqual(
            (match.ball.zone, match.ball.space_index),
            (Zone.VISITORS_GOAL, 2),
        )
        cog.offer_scoring_attempt_choice.assert_awaited_once()
        _, kwargs = cog.offer_scoring_attempt_choice.await_args
        self.assertEqual(kwargs["shooter_id"], shooter)
        self.assertEqual(kwargs["decline_kind"], "skill_test")
        cog.begin_loose_ball.assert_not_awaited()

    async def test_apply_high_pass_distance_two_without_overshoot_forces_skill_test(
        self,
    ) -> None:
        cog = self.build_cog()
        match = self.build_match()
        handler = self.player_with_role(
            match, TeamSide.HOME, PlayerRole.DEFENDER,
        )
        match.active_player_id = handler
        match.ball.possession = TeamSide.HOME
        match.set_ball_space(Zone.HOME_GOAL, 0)  # flat 0, plenty of room

        interaction = SimpleNamespace()
        game = SimpleNamespace(match_state=None)
        with mock.patch("cogs.d12ball.save_games"):
            await cog.apply_high_pass(interaction, game, match, 2)

        self.assertEqual(
            (match.ball.zone, match.ball.space_index), (Zone.HOME_GOAL, 2),
        )
        cog.offer_scoring_attempt_choice.assert_not_awaited()
        cog.begin_loose_ball.assert_awaited_once()
        _, kwargs = cog.begin_loose_ball.await_args
        self.assertEqual(kwargs["headline"], HIGH_PASS_CONTEST_HEADLINE)

    async def test_apply_high_pass_distance_three_never_offers_setup(
        self,
    ) -> None:
        cog = self.build_cog()
        match = self.build_match()
        handler = self.player_with_role(
            match, TeamSide.HOME, PlayerRole.DEFENDER,
        )
        match.active_player_id = handler
        match.ball.possession = TeamSide.HOME
        match.set_ball_space(Zone.VISITORS_GOAL, 1)  # flat 7
        # A shooter candidate is standing right where a 3-space pass
        # would overshoot to -- still shouldn't matter at distance 3.
        shooter = match.home.field_players[0]
        match.move_meeple(shooter, Zone.VISITORS_GOAL, 2)

        interaction = SimpleNamespace()
        game = SimpleNamespace(match_state=None)
        with mock.patch("cogs.d12ball.save_games"):
            await cog.apply_high_pass(interaction, game, match, 3)

        cog.offer_scoring_attempt_choice.assert_not_awaited()
        cog.begin_loose_ball.assert_awaited_once()

    async def test_apply_high_pass_fullback_ability_note_at_distance_four(
        self,
    ) -> None:
        cog = self.build_cog()
        match = self.build_match()
        handler = self.player_with_role(
            match, TeamSide.HOME, PlayerRole.FULLBACK,
        )
        match.active_player_id = handler
        match.ball.possession = TeamSide.HOME
        match.set_ball_space(Zone.HOME_GOAL, 0)  # flat 0, no overshoot at 4

        interaction = SimpleNamespace()
        game = SimpleNamespace(match_state=None)
        with mock.patch("cogs.d12ball.save_games"):
            await cog.apply_high_pass(interaction, game, match, 4)

        self.assertEqual(
            (match.ball.zone, match.ball.space_index), (Zone.MIDFIELD, 1),
        )
        cog.begin_loose_ball.assert_awaited_once()
        _, kwargs = cog.begin_loose_ball.await_args
        self.assertIn("Fullback ability", kwargs["lead_in"])

    # -- Block Deflect's Fullback bonus ---------------------------------

    async def test_resolve_block_deflect_fullback_deflects_two_spaces(
        self,
    ) -> None:
        cog = self.build_cog()
        match = self.build_match()
        match.ball.possession = TeamSide.HOME
        match.set_ball_space(Zone.MIDFIELD, 1)  # flat 4, room to spare
        defender = self.player_with_role(
            match, TeamSide.VISITING, PlayerRole.FULLBACK,
        )
        match.challenger_id = defender

        interaction = SimpleNamespace()
        game = SimpleNamespace(match_state=None)
        with mock.patch("cogs.d12ball.save_games"):
            await cog.resolve_block_deflect(interaction, game, match)

        # HOME attacks left-to-right, so "back" is toward lower flat
        # indices: flat 4 - 2 = flat 2, HOME_GOAL space 2.
        self.assertEqual(
            (match.ball.zone, match.ball.space_index), (Zone.HOME_GOAL, 2),
        )
        cog.finish_maneuver_resolution.assert_awaited_once()
        _, kwargs = cog.finish_maneuver_resolution.await_args
        self.assertIn("Fullback ability", kwargs["lead_in"])
        self.assertIn("2 spaces back", kwargs["lead_in"])


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
