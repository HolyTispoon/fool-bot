import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from PIL import Image, ImageDraw, ImageFont

from cogs.d12ball import HIGH_PASS_CONTEST_HEADLINE, D12Ball
from d12ball.cards import (
    HAND_CARD_WIDTH,
    HAND_GAP,
    HAND_MARGIN,
    SHEET_COLUMNS,
    SHEET_MARGIN,
    print_sheet,
    render_maneuver_card,
    render_maneuver_card_back,
    render_maneuver_hand,
    role_abilities,
    tie_pairs,
)
from d12ball.components import (
    SECOND_HALF_START_MINUTE,
    CoachingOccasion,
    AssignmentEdge,
    AttackDirection,
    BoardState,
    MatchPeriod,
    MatchState,
    PlayerRole,
    ScoreboardState,
    TeamSide,
    Zone,
    create_standard_setup,
    kickoff_space_index,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.game import Formation, Team
from d12ball.render import (
    BOARD_BOTTOM,
    EXHAUSTED_ICON_PATH,
    EXHAUST_ICON_PATH,
    INJURED_ICON_PATH,
    BOARD_LEFT,
    BOARD_RIGHT,
    BOARD_TOP,
    CARD_SIZE,
    COACHING_BOARD_LEFT,
    COACHING_BOARD_RIGHT,
    COACHING_CARD_GAP,
    COACHING_HEIGHT,
    COACHING_WIDTH,
    FIELD_MARGIN,
    FONT_BODY,
    FONT_DIR,
    FONT_HEADING,
    FONT_SCORE,
    FONT_SMALL,
    FONT_TITLE,
    BALL_RADIUS,
    MEEPLE_SIZE,
    PORTRAIT_IMAGE_SIZE,
    ball_token_x,
    fit_meeple_labels,
    OWN_GOAL_DIE_RADIUS,
    SKILL_TEST_DIE_RADIUS,
    load_font,
    render_coaching_image,
    render_field_image,
    render_injury_test_die,
    render_own_goal_dice,
    render_skill_test_dice,
    render_maneuver_reference_image,
    render_match_image,
    render_player_portrait,
    zone_bounds_between,
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
            setup.team_board.bench,
            [
                "orange_inferno",
                "orange_blazekick",
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

    def test_team_board_dice(self) -> None:
        team_board = self.rules.team_board
        self.assertEqual(
            (team_board.offense_die.sides, team_board.offense_die.color),
            (6, "crimson"),
        )
        self.assertEqual(
            (team_board.defense_die.sides, team_board.defense_die.color),
            (6, "green"),
        )
        self.assertEqual(
            (team_board.team_die.sides, team_board.team_die.color),
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
                    match.home.team_board.bench
                    + match.visiting.team_board.bench
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

    def test_a_game_saved_as_player_board_still_loads(self) -> None:
        """
        The team board was called a player board, and a game saved
        under the old key outlives the rename -- both developers run the
        bot against their own saves.
        """
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.TEAL,
        )
        legacy = match.to_dict()
        for side in ("home", "visiting"):
            legacy[side]["player_board"] = legacy[side].pop("team_board")

        restored = MatchState.from_dict(legacy, self.rules)

        self.assertEqual(
            restored.home.team_board.bench, match.home.team_board.bench,
        )
        # Read under either name, written under one: the old key does
        # not survive a save, so it dies out on its own.
        self.assertEqual(restored.to_dict(), match.to_dict())
        self.assertNotIn("player_board", restored.to_dict()["home"])

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
        incoming = match.home.team_board.bench[0]
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
        incoming = match.home.team_board.bench[0]

        match.substitute(TeamSide.HOME, outgoing, incoming)

        self.assertIn(outgoing, match.home.team_board.back_bench)
        self.assertNotIn(outgoing, match.home.team_board.bench)
        self.assertNotIn(incoming, match.home.team_board.bench)

        # The bench only ever drains, so it can never be the route
        # back on for someone who has already been subbed out -- not
        # while anyone is still sitting on it.
        self.assertNotIn(
            outgoing, match.substitution_pool(TeamSide.HOME),
        )

    def test_back_bench_is_closed_until_the_bench_empties(self) -> None:
        match = self.standard_match()

        # The bench still has people on it, so it is the only pool.
        self.assertEqual(
            match.substitution_pool(TeamSide.HOME),
            match.home.team_board.bench,
        )

        for outgoing in ("orange_hellguard", "orange_sizzik", "orange_scorchit"):
            match.substitute(
                TeamSide.HOME,
                outgoing,
                match.home.team_board.bench[0],
            )
        self.assertEqual(match.home.team_board.bench, [])

        # Drained, so the back bench opens -- to replace anybody, not
        # only an injured player.
        self.assertEqual(
            sorted(match.substitution_pool(TeamSide.HOME)),
            sorted(match.home.team_board.back_bench),
        )
        match.substitute(
            TeamSide.HOME,
            "orange_flickerwing",
            match.home.team_board.back_bench[0],
        )

    def test_injured_players_never_come_back(self) -> None:
        match = self.standard_match()
        injured = "orange_kindlefoot"
        match.mark_injured(injured)
        match.substitute(
            TeamSide.HOME, injured, match.home.team_board.bench[0],
        )
        for outgoing in ("orange_hellguard", "orange_sizzik"):
            match.substitute(
                TeamSide.HOME,
                outgoing,
                match.home.team_board.bench[0],
            )

        self.assertEqual(match.home.team_board.bench, [])
        self.assertIn(injured, match.home.team_board.back_bench)

        # The back bench is open, but not to the player who limped off
        # it: that is about them, not about which bench they sit on.
        pool = match.substitution_pool(TeamSide.HOME)
        self.assertNotIn(injured, pool)
        self.assertEqual(len(pool), 2)
        with self.assertRaises(ValueError):
            match.substitute(TeamSide.HOME, "orange_scorchit", injured)

    def test_nobody_to_bring_on_takes_both_benches(self) -> None:
        # The only way a side runs out: the bench drained, and every
        # one of the three who came off went off injured.
        match = self.standard_match()
        for outgoing in ("orange_hellguard", "orange_sizzik", "orange_scorchit"):
            match.mark_injured(outgoing)
            match.substitute(
                TeamSide.HOME,
                outgoing,
                match.home.team_board.bench[0],
            )

        self.assertEqual(match.home.team_board.bench, [])
        self.assertEqual(len(match.home.team_board.back_bench), 3)
        self.assertEqual(match.substitution_pool(TeamSide.HOME), [])

    def test_returning_player_loses_half_their_tokens(self) -> None:
        match = self.standard_match()
        returning = "orange_hellguard"
        match.add_exhaustion(returning, 5)
        match.mark_exhausted_if_needed(returning, defense_skill=2)
        self.assertIn(returning, match.exhausted)

        match.substitute(
            TeamSide.HOME, returning, match.home.team_board.bench[0],
        )
        for outgoing in ("orange_sizzik", "orange_scorchit"):
            match.substitute(
                TeamSide.HOME,
                outgoing,
                match.home.team_board.bench[0],
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

        # Only the card-to-zone assignment moves -- the meeples stay
        # exactly where they were until repositioned by hand or by the
        # next run back.
        self.assertEqual(match.board.meeple_position(first), first_position)
        self.assertEqual(match.board.meeple_position(second), second_position)
        self.assertEqual(
            match.home.assigned_zone(first), Zone.VISITORS_GOAL,
        )
        self.assertEqual(match.home.assigned_zone(second), Zone.HOME_GOAL)
        self.assertTrue(
            all(len(match.home.zones[zone]) == 2 for zone in Zone)
        )
        self.assertEqual(match.exhaustion, {})
        match.validate(self.catalog)

    def test_a_substitution_moves_a_run_back_exemption_to_the_replacement(
        self,
    ) -> None:
        match = self.standard_match()
        stealer = "orange_blazebulk"
        match.pending_run_back_stays_player_id = stealer

        # Subbed off: whoever comes on is standing on the ball now, so
        # running them back would take the ball carrier off the ball.
        incoming = match.home.team_board.bench[0]
        match.substitute(TeamSide.HOME, stealer, incoming)

        self.assertEqual(match.pending_run_back_stays_player_id, incoming)

    def test_swapping_two_players_does_not_move_a_run_back_exemption(
        self,
    ) -> None:
        # The exemption belongs to a meeple's physical position (see
        # inherit_run_back_exemption); a swap that only changes card
        # assignments never touches meeples, so it never touches this
        # either -- unlike substitute(), which does move a meeple.
        match = self.standard_match()
        match.pending_run_back_stays_player_id = "orange_blazebulk"

        match.swap_field_positions(
            TeamSide.HOME, "orange_hellguard", "orange_sizzik",
        )

        self.assertEqual(
            match.pending_run_back_stays_player_id, "orange_blazebulk",
        )

    def test_swap_meeple_positions_resolves_a_fully_packed_zone(
        self,
    ) -> None:
        # On a 6-board, 2-2-2 leaves each zone exactly full: after
        # swapping two players' zone assignments, neither zone has an
        # open space for its new member to step into one at a time,
        # since whoever they swapped with hasn't physically left yet.
        # Trading positions directly is the only thing that resolves
        # this without a full run back.
        match = self.standard_match(board_size=6)
        first, second = "orange_hellguard", "orange_kindlefoot"
        match.swap_field_positions(TeamSide.HOME, first, second)
        first_zone = match.home.assigned_zone(first)
        second_zone = match.home.assigned_zone(second)
        self.assertEqual(match.open_spaces_in_zone(TeamSide.HOME, first_zone), [])
        self.assertEqual(match.open_spaces_in_zone(TeamSide.HOME, second_zone), [])

        match.swap_meeple_positions(TeamSide.HOME, first, second)

        self.assertEqual(
            match.board.meeple_position(first)[0], first_zone,
        )
        self.assertEqual(
            match.board.meeple_position(second)[0], second_zone,
        )
        self.assertEqual(match.exhaustion, {})
        match.validate(self.catalog)

    def test_swap_meeple_positions_moves_a_run_back_exemption(self) -> None:
        match = self.standard_match()
        stealer = "orange_hellguard"
        match.pending_run_back_stays_player_id = stealer

        match.swap_meeple_positions(
            TeamSide.HOME, stealer, "orange_kindlefoot",
        )

        self.assertEqual(
            match.pending_run_back_stays_player_id, "orange_kindlefoot",
        )

    def test_declaration_is_once_a_half_but_a_reply_is_free(self) -> None:
        match = self.standard_match()
        self.assertTrue(match.may_declare_coaching(TeamSide.HOME))

        # Being offered the window spends nothing; passing on it
        # leaves the declaration in hand for a later turnover.
        match.open_coaching_window(TeamSide.HOME, CoachingOccasion.NEW_PLAY)
        self.assertTrue(match.may_declare_coaching(TeamSide.HOME))
        match.close_coaching_window()
        self.assertTrue(match.may_declare_coaching(TeamSide.HOME))

        match.open_coaching_window(TeamSide.HOME, CoachingOccasion.NEW_PLAY)
        match.declare_coaching()
        self.assertEqual(match.substitutions_remaining(), 2)
        match.record_substitution()
        match.record_substitution()
        self.assertEqual(match.substitutions_remaining(), 0)
        match.close_coaching_window()

        self.assertFalse(match.may_declare_coaching(TeamSide.HOME))

        # Answering the other team's declaration costs the answering
        # team nothing, so the visitors can still declare their own
        # later in the half -- and they answer with the same two the
        # declaring side had, not a smaller allowance.
        match.open_coaching_window(
            TeamSide.VISITING,
            CoachingOccasion.NEW_PLAY,
            is_response=True,
        )
        match.declare_coaching()
        self.assertEqual(match.substitutions_remaining(), 2)
        match.close_coaching_window()
        self.assertTrue(match.may_declare_coaching(TeamSide.VISITING))

    def test_the_two_substitutions_are_spent_across_the_whole_half(
        self,
    ) -> None:
        # The count is per side per half, not per window: a side that
        # answers someone else's declaration with both of theirs has
        # none left when their own declaration comes round, and gets
        # the rearrangement without the swaps.
        match = self.standard_match()
        match.open_coaching_window(
            TeamSide.VISITING,
            CoachingOccasion.NEW_PLAY,
            is_response=True,
        )
        match.declare_coaching()
        match.record_substitution()
        match.record_substitution()
        match.close_coaching_window()

        match.open_coaching_window(
            TeamSide.VISITING, CoachingOccasion.NEW_PLAY,
        )
        self.assertTrue(match.may_declare_coaching(TeamSide.VISITING))
        self.assertEqual(match.substitutions_remaining(), 0)
        self.assertFalse(match.may_substitute())

    def test_halftime_and_setup_do_not_touch_the_half_count(self) -> None:
        match = self.standard_match()
        match.open_coaching_window(TeamSide.HOME, CoachingOccasion.NEW_PLAY)
        match.record_substitution()
        match.close_coaching_window()

        # Halftime carries its own two, so a side that has already
        # spent one in the half still gets both of halftime's.
        match.open_coaching_window(TeamSide.HOME, CoachingOccasion.HALFTIME)
        self.assertEqual(match.substitutions_remaining(), 2)
        match.record_substitution()
        match.record_substitution()
        self.assertEqual(match.substitutions_remaining(), 0)
        match.close_coaching_window()
        self.assertEqual(match.half_substitutions_used, {"home": 1})

        # Setup has no limit at all, which callers have to tell apart
        # from a limit of zero.
        match.open_coaching_window(TeamSide.HOME, CoachingOccasion.SETUP)
        self.assertIsNone(match.substitutions_remaining())
        self.assertTrue(match.may_substitute())
        match.record_substitution()
        self.assertIsNone(match.substitutions_remaining())
        self.assertEqual(match.half_substitutions_used, {"home": 1})

    def test_an_injury_never_forces_a_declaration(self) -> None:
        # An injured player used to compel their team to sub them off
        # at the next window. They no longer do: the once-a-half
        # declaration is the only gate there is, and a coach may leave
        # them on, disadvantaged, for the rest of the game.
        match = self.standard_match()
        self.assertTrue(match.may_declare_coaching(TeamSide.HOME))

        match.mark_injured("orange_kindlefoot")
        self.assertTrue(match.may_declare_coaching(TeamSide.HOME))
        self.assertEqual(
            match.injured_field_players(TeamSide.HOME), ["orange_kindlefoot"],
        )
        self.assertFalse(hasattr(match, "must_declare_substitution"))

        match.declared_substitution.add(TeamSide.HOME.value)
        self.assertFalse(match.may_declare_coaching(TeamSide.HOME))

    def test_setup_is_the_first_arrangement_a_new_play_restores(
        self,
    ) -> None:
        match = self.standard_match()
        stray = match.home.zones[Zone.HOME_GOAL][0]
        home = match.board.meeple_position(stray)
        self.assertEqual(
            match.assigned_positions[stray], [home[0].value, home[1]],
        )

        match.board.place_meeple(stray, Zone.VISITORS_GOAL, 0)
        moved = match.restore_assigned_positions(TeamSide.HOME)

        self.assertEqual(moved, [(stray, home[0], home[1])])
        self.assertEqual(match.board.meeple_position(stray), home)
        # The restore is the coach's shape reasserting itself, not a
        # player running: it charges nothing.
        self.assertEqual(match.exhaustion, {})

    def test_restoring_reports_only_who_actually_moved(self) -> None:
        match = self.standard_match()

        # Nobody has budged since setup, so a restore is a no-op and
        # says so -- which is what lets the caller skip the message.
        self.assertEqual(
            match.restore_assigned_positions(TeamSide.HOME), [],
        )
        self.assertEqual(
            match.restore_assigned_positions(TeamSide.VISITING), [],
        )

    def test_a_run_back_never_becomes_the_saved_arrangement(self) -> None:
        # Only setup, a substitution window and halftime set an
        # arrangement. A run back is a scramble the coach was forced
        # into, so the shape they chose has to survive it.
        match = self.standard_match()
        stray, teammate = match.home.zones[Zone.HOME_GOAL][:2]
        home = match.board.meeple_position(stray)
        other_space = match.board.meeple_position(teammate)[1]

        # Both out of the zone, so the run back has a real choice of
        # space and can put the stray on the wrong one.
        match.board.place_meeple(stray, Zone.MIDFIELD, 0)
        match.board.place_meeple(teammate, Zone.MIDFIELD, 0)
        match.run_back_player(stray, Zone.HOME_GOAL, other_space)

        self.assertEqual(
            match.assigned_positions[stray], [home[0].value, home[1]],
        )
        match.restore_assigned_positions(TeamSide.HOME)
        self.assertEqual(match.board.meeple_position(stray), home)

    def test_the_saved_arrangement_round_trips(self) -> None:
        match = self.standard_match()
        stray = match.home.zones[Zone.HOME_GOAL][0]
        match.board.place_meeple(stray, Zone.MIDFIELD, 0)
        match.set_assigned_positions(TeamSide.HOME)

        restored = MatchState.from_dict(match.to_dict(), self.rules)

        self.assertEqual(
            restored.assigned_positions[stray],
            [Zone.MIDFIELD.value, 0],
        )

    def test_a_game_saved_before_arrangements_existed_still_loads(
        self,
    ) -> None:
        # Such a game remembers nothing, so a restore moves nobody and
        # it keeps the old behaviour until its next window.
        match = self.standard_match()
        data = match.to_dict()
        del data["assigned_positions"]

        restored = MatchState.from_dict(data, self.rules)

        self.assertEqual(restored.assigned_positions, {})
        self.assertEqual(
            restored.restore_assigned_positions(TeamSide.HOME), [],
        )

    def test_coaching_state_round_trips(self) -> None:
        match = self.standard_match()
        match.declared_substitution.add(TeamSide.HOME.value)
        match.open_coaching_window(
            TeamSide.VISITING,
            CoachingOccasion.NEW_PLAY,
            is_response=True,
        )
        match.declare_coaching()
        match.record_substitution()

        restored = MatchState.from_dict(match.to_dict(), self.rules)

        self.assertEqual(
            restored.declared_substitution, {TeamSide.HOME.value},
        )
        self.assertEqual(
            restored.pending_coaching_side, TeamSide.VISITING.value,
        )
        self.assertEqual(
            restored.coaching_occasion, CoachingOccasion.NEW_PLAY,
        )
        self.assertTrue(restored.pending_coaching_is_response)
        self.assertEqual(restored.half_substitutions_used, {"visiting": 1})
        self.assertEqual(restored.substitutions_remaining(), 1)

    def test_saved_games_without_coaching_state_still_load(
        self,
    ) -> None:
        match = self.standard_match()
        data = match.to_dict()
        for key in list(data):
            if "substitution" in key or "coaching" in key:
                del data[key]

        restored = MatchState.from_dict(data, self.rules)

        self.assertEqual(restored.declared_substitution, set())
        self.assertIsNone(restored.pending_coaching_side)
        self.assertIsNone(restored.coaching_occasion)
        self.assertTrue(restored.may_declare_coaching(TeamSide.HOME))

    def test_a_window_saved_under_the_old_field_names_still_loads(
        self,
    ) -> None:
        # A game saved mid-window before the three occasions became one
        # Coaching Choice. Both developers run the bot from their own
        # tree against their own saves, so a half-finished game outlives
        # the rename. It comes back as a new play's window, the only
        # kind the old code could leave open mid-game.
        match = self.standard_match()
        data = match.to_dict()
        for key in list(data):
            if "coaching" in key:
                del data[key]
        data["pending_substitution_side"] = TeamSide.HOME.value
        data["pending_substitution_declared"] = True
        data["pending_substitution_used"] = 1

        restored = MatchState.from_dict(data, self.rules)

        self.assertEqual(restored.pending_coaching_side, "home")
        self.assertEqual(
            restored.coaching_occasion, CoachingOccasion.NEW_PLAY,
        )
        self.assertTrue(restored.pending_coaching_declared)

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

    def test_contest_candidates_are_the_nearest_either_way(self) -> None:
        # "Sending a player" in docs/living-rules.md: the nearest own
        # player in front of the space and the nearest behind it, plus
        # anyone tied with either, and zone does not come into it.
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=9,
            home_team=Team.SLIME,
            visiting_team=Team.TEAL,
        )
        ball_flat = match.board.flat_index(
            match.ball.zone, match.ball.space_index,
        )
        offsets = {
            player_id: match.board.flat_index(
                *match.board.meeple_position(player_id)
            ) - ball_flat
            for player_id in match.home.field_players
        }

        candidates = match.contest_candidates(TeamSide.HOME)

        for player_id, offset in offsets.items():
            nearest = min(
                abs(other)
                for other in offsets.values()
                if (other > 0) == (offset > 0) and (other < 0) == (offset < 0)
            )
            self.assertEqual(
                player_id in candidates, abs(offset) == nearest,
                f"{player_id} at {offset:+d}",
            )

    def test_contest_candidates_include_anyone_on_the_space(self) -> None:
        # They are never *sent* anywhere -- automatic_challengers and
        # the eligible-handler checks pick them off first -- but they
        # are what those checks filter, so they have to be here.
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=9,
            home_team=Team.SLIME,
            visiting_team=Team.TEAL,
        )
        on_the_ball = match.board.spaces[match.ball.zone][
            match.ball.space_index
        ]
        home_on_the_ball = [
            player_id
            for player_id in match.home.field_players
            if player_id in on_the_ball
        ]

        self.assertTrue(home_on_the_ball)
        self.assertTrue(
            set(home_on_the_ball)
            <= set(match.contest_candidates(TeamSide.HOME))
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

    def test_the_field_image_is_the_board_cut_out_of_the_match_image(
        self,
    ) -> None:
        # A crop rather than a second drawing: the field a coach reads
        # under their maneuver cards is made of the same pixels as the
        # board, so nothing about it can drift from what the board says.
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.TEAL,
        )
        image_data = render_field_image(match, self.catalog)

        with Image.open(image_data) as image:
            self.assertEqual(image.format, "PNG")
            self.assertEqual(
                image.size,
                (
                    BOARD_RIGHT - BOARD_LEFT + 2 * FIELD_MARGIN,
                    BOARD_BOTTOM - BOARD_TOP + 2 * FIELD_MARGIN,
                ),
            )

    def test_the_coaching_image_renders_one_side_only(self) -> None:
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.TEAL,
        )
        image_data = render_coaching_image(
            match, self.catalog, TeamSide.HOME, title="Orange (Home)",
        )

        with Image.open(image_data) as image:
            self.assertEqual(image.format, "PNG")
            self.assertEqual(
                image.size, (COACHING_WIDTH, COACHING_HEIGHT),
            )

    def test_a_zone_of_three_cards_fits_under_its_zone(self) -> None:
        # The coaching image draws each zone's assigned cards under
        # that zone, centred on it. Three in a zone is the most any
        # basic shape allows: midfield holds three under 2-3-1 and
        # 1-3-2 on every board, and a goal zone does under board 9's
        # own 3-2-1 and 1-2-3. So every shape the board plays is asked,
        # of every zone it fills with three.
        row = 3 * CARD_SIZE[0] + 2 * COACHING_CARD_GAP
        for board_size in (6, 7, 9):
            for formation in self.rules.formations_for_board(board_size):
                match = MatchState.standard(
                    catalog=self.catalog,
                    ruleset=self.rules,
                    board_size=board_size,
                    home_team=Team.ORANGE,
                    visiting_team=Team.TEAL,
                    home_formation=formation,
                )
                bounds = zone_bounds_between(
                    match, COACHING_BOARD_LEFT, COACHING_BOARD_RIGHT,
                )
                for zone, players in match.home.zones.items():
                    if len(players) < 3:
                        continue
                    left, right = bounds[zone]
                    with self.subTest(
                        board_size=board_size,
                        formation=formation.value,
                        zone=zone.value,
                    ):
                        self.assertLessEqual(row, right - left)

    def test_a_stacked_coaching_space_still_fits_its_meeples(self) -> None:
        # Board 6's two-space midfield under 2-3-1 is the only place a
        # Coaching Choice can put two of a side's meeples on one space,
        # and the coaching image's width is chosen to fit exactly that
        # -- see COACHING_WIDTH. If a future board or shape stacks more,
        # or the image narrows, the tokens start overlapping the space
        # border and this is the check that notices.
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=6,
            home_team=Team.ORANGE,
            visiting_team=Team.TEAL,
            home_formation=Formation.TWO_THREE_ONE,
        )
        bounds = zone_bounds_between(
            match, COACHING_BOARD_LEFT, COACHING_BOARD_RIGHT,
        )
        deepest = max(
            len(
                [
                    player_id
                    for player_id in occupants
                    if player_id in set(match.home.field_players)
                ]
            )
            for zone in Zone
            for occupants in match.board.spaces[zone]
        )
        self.assertEqual(deepest, 2)

        narrowest = min(
            (right - left) / len(match.board.spaces[zone])
            for zone, (left, right) in bounds.items()
        )
        stack_width = deepest * MEEPLE_SIZE + (deepest - 1) * 3
        self.assertLess(stack_width, narrowest - 20)

    def test_meeple_names_shrink_to_fit_a_stacked_space(self) -> None:
        # A formation can put a whole zone's players on one space, so
        # the label size is chosen per space (see fit_meeple_labels).
        # The test suite cannot see the image, so this checks the sizing
        # rule directly: four names take a smaller size than one, and
        # every one of them fits the width it was given.
        image = Image.new("RGB", (10, 10))
        draw = ImageDraw.Draw(image)
        names = ["Flickerwing", "Hellguard", "Kindlefoot", "Blazebulk"]

        single_font, _ = fit_meeple_labels(draw, names[:1], 400, 300)
        stacked_font, line_height = fit_meeple_labels(draw, names, 400, 90)

        self.assertLess(stacked_font.size, single_font.size)
        self.assertLessEqual(len(names) * line_height, 90)
        for name in names:
            self.assertLessEqual(
                draw.textlength(name, font=stacked_font), 400,
            )

    def test_a_loose_ball_is_drawn_inside_its_own_space(self) -> None:
        # A space with none of the possessing side's meeples on it is
        # exactly the loose ball, and the ball has to be visible there
        # -- anchored to an empty group's bounds it was drawn a radius
        # outside the space, under the next space's tokens. The suite
        # cannot see the image, so this checks the placement rule.
        space_left, space_right = 1000, 1300
        empty_group = (space_left, space_right)

        for home_side in (True, False):
            loose = ball_token_x(
                space_left, space_right, empty_group,
                carrying_side_present=False,
                home_side=home_side,
            )
            self.assertGreater(loose - BALL_RADIUS, space_left)
            self.assertLess(loose + BALL_RADIUS, space_right)

        # Held, it still sits against the side's own group of meeples,
        # on the open side of the row.
        held_group = (space_left + 12, space_left + 12 + MEEPLE_SIZE)
        self.assertGreater(
            ball_token_x(
                space_left, space_right, held_group,
                carrying_side_present=True, home_side=True,
            ),
            held_group[1],
        )
        held_group = (space_right - 12 - MEEPLE_SIZE, space_right - 12)
        self.assertLess(
            ball_token_x(
                space_left, space_right, held_group,
                carrying_side_present=True, home_side=False,
            ),
            held_group[0],
        )


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
            for player_id, _ in match.defenders_between_ball_and_goal()
        ]

    def defender_ids(self, match: MatchState) -> list[str]:
        return [
            player_id
            for player_id, _ in match.defenders_between_ball_and_goal()
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
        # sharing the ball's own space is one of them -- flagged as
        # such, because that is what makes them worth their whole skill.
        defenders = match.defenders_between_ball_and_goal()
        self.assertTrue(
            set(self.defender_ids(match)).issubset(
                set(match.visiting.field_players)
            )
        )
        self.assertIn(
            defenders[0][0],
            match.board.spaces[match.ball.zone][match.ball.space_index],
        )
        self.assertEqual(
            [on_ball for _, on_ball in defenders],
            [True, False, False],
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
            set(self.defender_ids(match)).issubset(
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

                            # Nobody behind the ball is ever counted,
                            # and only the ball's own space counts as
                            # on the ball.
                            for player_id, on_ball in (
                                match.defenders_between_ball_and_goal()
                            ):
                                position = match.board.meeple_position(
                                    player_id
                                )
                                defender_flat = match.board.flat_index(
                                    *position
                                )
                                self.assertEqual(
                                    on_ball,
                                    defender_flat == flat,
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
        home_scorer = match.home.field_players[0]
        visiting_scorer = match.visiting.field_players[0]

        match.award_goal(home_scorer)
        self.assertEqual(match.scoreboard.home_score, 1)
        self.assertEqual(match.scoreboard.visiting_score, 0)

        match.ball.possession = TeamSide.VISITING
        match.award_goal(visiting_scorer)
        match.award_goal(visiting_scorer)
        self.assertEqual(match.scoreboard.home_score, 1)
        self.assertEqual(match.scoreboard.visiting_score, 2)

        # Scores have no ceiling, so a goal can never leave the
        # scoreboard in a state that fails to reload.
        for _ in range(20):
            match.award_goal(visiting_scorer)
        restored = MatchState.from_dict(match.to_dict(), self.rules)
        self.assertEqual(restored.scoreboard.visiting_score, 22)

    def test_concede_own_goal_credits_the_other_side(self) -> None:
        match = self.build_match(7)
        home_player = match.home.field_players[0]
        visiting_player = match.visiting.field_players[0]

        match.concede_own_goal(home_player)
        self.assertEqual(match.scoreboard.home_score, 0)
        self.assertEqual(match.scoreboard.visiting_score, 1)

        match.ball.possession = TeamSide.VISITING
        match.concede_own_goal(visiting_player)
        self.assertEqual(match.scoreboard.home_score, 1)
        self.assertEqual(match.scoreboard.visiting_score, 1)

        # The goal is the other side's and the kick is this player's,
        # which is the one line of a scoresheet where the two disagree.
        own_goals = [goal for goal in match.goals if goal.own_goal]
        self.assertEqual(
            [(goal.side, goal.player_id) for goal in own_goals],
            [
                (TeamSide.VISITING, home_player),
                (TeamSide.HOME, visiting_player),
            ],
        )

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

    def test_goal_restart_flags_pending_kickoff_fill_when_the_space_is_empty(
        self,
    ) -> None:
        # Board size 7 gives midfield 3 spaces for only 2 native
        # players per side, so open play can easily leave the kickoff
        # space (the true middle) uncovered by the time a goal lands.
        match = self.build_match(7)
        visiting_midfield = match.visiting.zones[Zone.MIDFIELD]
        for player_id, space_index in zip(visiting_midfield, (0, 2)):
            match.board.remove_meeple(player_id)
            match.board.place_meeple(player_id, Zone.MIDFIELD, space_index)

        match.restart_after_goal(TeamSide.VISITING)

        self.assertTrue(match.pending_kickoff_fill)
        self.assertEqual(match.eligible_ball_handlers(), [])

    def test_goal_restart_flags_the_kickoff_fill_even_when_covered(
        self,
    ) -> None:
        # The flag means "this restart still owes a kickoff-space
        # check", not "nobody is standing there". Everyone moves
        # between the restart and the check -- the new play's reset,
        # and anything its substitution window placed -- so the
        # question is only worth asking once they have settled, which
        # D12Ball.continue_run_back does.
        match = self.build_match(6)

        match.restart_after_goal(TeamSide.HOME)

        self.assertTrue(match.pending_kickoff_fill)
        self.assertNotEqual(match.eligible_ball_handlers(), [])

    def test_kickoff_fill_candidates_prefers_the_nearest_midfielder(
        self,
    ) -> None:
        match = self.build_match(7)
        visiting_midfield = match.visiting.zones[Zone.MIDFIELD]
        near, far = visiting_midfield
        match.board.remove_meeple(near)
        match.board.remove_meeple(far)
        match.board.place_meeple(near, Zone.MIDFIELD, 0)
        match.board.place_meeple(far, Zone.MIDFIELD, 2)

        match.restart_after_goal(TeamSide.VISITING)
        # Kickoff space on a 7-board is the true middle (index 1),
        # equidistant from 0 and 2 -- move `far` further out so the
        # ordering is unambiguous.
        match.board.remove_meeple(far)
        match.board.place_meeple(far, Zone.HOME_GOAL, 0)

        candidates = match.kickoff_fill_candidates()
        self.assertEqual(candidates[0], near)
        self.assertIn(far, candidates)

    def test_fill_kickoff_moves_the_player_and_clears_the_flag(self) -> None:
        match = self.build_match(7)
        visiting_midfield = match.visiting.zones[Zone.MIDFIELD]
        for player_id, space_index in zip(visiting_midfield, (0, 2)):
            match.board.remove_meeple(player_id)
            match.board.place_meeple(player_id, Zone.MIDFIELD, space_index)

        match.restart_after_goal(TeamSide.VISITING)
        self.assertTrue(match.pending_kickoff_fill)

        mover = match.kickoff_fill_candidates()[0]
        distance = match.fill_kickoff(mover)

        self.assertGreater(distance, 0)
        self.assertEqual(
            match.board.meeple_position(mover),
            (match.ball.zone, match.ball.space_index),
        )
        self.assertFalse(match.pending_kickoff_fill)
        self.assertIn(mover, match.eligible_ball_handlers())

    def test_fill_kickoff_rejects_a_player_outside_midfield(self) -> None:
        match = self.build_match(7)
        match.restart_after_goal(TeamSide.HOME)
        outsider = match.home.zones[Zone.HOME_GOAL][0]

        with self.assertRaises(ValueError):
            match.fill_kickoff(outsider)

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

    def test_advance_time_runs_on_and_flags_last_possession_once(
        self,
    ) -> None:
        match = self.build_match(7)

        self.assertFalse(match.advance_time(3))
        self.assertEqual(match.scoreboard.time, 3)
        self.assertFalse(match.scoreboard.last_possession)

        self.assertTrue(match.advance_time(20))
        self.assertEqual(match.scoreboard.time, 23)
        self.assertTrue(match.scoreboard.last_possession)

        # The clock does not stop there: last possession is charged
        # like any other play, and only the flag ends the period. What
        # does not happen twice is the flag being *raised*, which is
        # what the return value is for.
        self.assertFalse(match.advance_time(5))
        self.assertEqual(match.scoreboard.time, 28)
        self.assertTrue(match.scoreboard.last_possession)

    def test_the_second_half_has_a_last_minute_of_its_own(self) -> None:
        """
        One running clock, so the number that opens last possession is
        the period's rather than the game's -- and the first half's 16,
        17 and 18 are not the second half's.
        """
        match = self.build_match(7)
        match.scoreboard.period = MatchPeriod.SECOND_HALF
        match.scoreboard.time = SECOND_HALF_START_MINUTE

        self.assertEqual(match.scoreboard.last_minute, 30)
        self.assertFalse(match.advance_time(10))
        self.assertFalse(match.scoreboard.last_possession)
        self.assertTrue(match.advance_time(5))
        self.assertTrue(match.scoreboard.last_possession)

    def test_a_saved_clock_past_the_last_minute_still_loads(self) -> None:
        """
        The range check was the clamp restated, and there is no clamp
        now -- a first half that ran to 19 has to reload.
        """
        match = self.build_match(7)
        match.scoreboard.time = 19
        match.scoreboard.last_possession = True

        reloaded = MatchState.from_dict(match.to_dict(), self.rules)
        self.assertEqual(reloaded.scoreboard.time, 19)
        self.assertTrue(reloaded.scoreboard.past_last_minute)

        with self.assertRaises(ValueError):
            ScoreboardState(time=-1)

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

    def test_each_side_gets_a_hand_of_three_cards_and_the_back(self) -> None:
        """
        The suite cannot see the picture, so what it can check is that
        the hand is as wide as a side's three maneuvers plus the shared
        back and no wider -- a fourth maneuver added to a side, or a
        back that stopped being drawn with the hand, would otherwise
        reach a coach's pick silently. The back is what replaced the
        "Maneuver Reference" button on the pick menu, so it is the
        whole of the reference a coach has while choosing.
        """
        players = load_player_catalog()
        expected = (
            HAND_MARGIN * 2 + HAND_CARD_WIDTH * 4 + HAND_GAP * 3
        )
        for side in ("offense", "defense"):
            with self.subTest(side=side):
                hand = render_maneuver_hand(self.catalog, players, side)
                with Image.open(hand) as image:
                    self.assertEqual(image.format, "PNG")
                    self.assertEqual(image.width, expected)

    def test_the_back_joins_every_pair_that_ties(self) -> None:
        """
        The dashed lines on the back are the ties, and they are asked
        of the catalog rather than paired by rank -- so a re-cut cycle
        moves the lines instead of leaving them pointing at the wrong
        maneuvers. Three pairs, each a genuine tie, and every maneuver
        in exactly one.
        """
        pairs = tie_pairs(self.catalog)
        self.assertEqual(len(pairs), len(self.catalog.offense))
        for offense, defense in pairs:
            with self.subTest(pair=(offense.name, defense.name)):
                self.assertEqual(
                    self.catalog.resolve(offense.name, defense.name), "tie"
                )
        named = [maneuver.name for pair in pairs for maneuver in pair]
        self.assertEqual(sorted(named), sorted(
            maneuver.name
            for maneuver in self.catalog.offense + self.catalog.defense
        ))

    def test_a_print_sheet_divides_evenly_into_its_cards(self) -> None:
        """
        The sheet is cut by dividing it into an even grid, by hand or
        by a splitter, so every cell has to be the same size and every
        card centred in one. The old sheet had a gutter round the
        outside as well as between the cards, which put every cut but
        the first off-centre.
        """
        players = load_player_catalog()
        cards = [
            render_maneuver_card(
                self.catalog, players, maneuver, is_offense, bleed=False
            )
            for maneuvers, is_offense in (
                (self.catalog.offense, True),
                (self.catalog.defense, False),
            )
            for maneuver in maneuvers
        ]
        back = render_maneuver_card_back(self.catalog, bleed=False)
        while len(cards) % SHEET_COLUMNS:
            cards.append(back)

        sheet = print_sheet(cards)
        rows = len(cards) // SHEET_COLUMNS
        self.assertEqual(sheet.width % SHEET_COLUMNS, 0)
        self.assertEqual(sheet.height % rows, 0)

        cell = (sheet.width // SHEET_COLUMNS, sheet.height // rows)
        for index in range(len(cards)):
            column, row = index % SHEET_COLUMNS, index // SHEET_COLUMNS
            piece = sheet.crop(
                (
                    column * cell[0],
                    row * cell[1],
                    (column + 1) * cell[0],
                    (row + 1) * cell[1],
                )
            )
            with self.subTest(cell=index):
                # The card sits dead centre: the margin is the same on
                # both sides and on top and bottom.
                self.assertEqual(
                    piece.size,
                    (
                        cards[index].width + SHEET_MARGIN * 2,
                        cards[index].height + SHEET_MARGIN * 2,
                    ),
                )

    def test_a_card_names_every_ability_that_touches_its_maneuver(
        self,
    ) -> None:
        """
        The match is over the ability sentences, so a re-import that
        rewords one silently drops it off the card it belongs to.
        Pressure is the case with two roles and Steal Intercept the one
        with none, which is why it carries a note instead.
        """
        players = load_player_catalog()
        by_maneuver = {
            maneuver.name: {
                label
                for label, _ in role_abilities(players, maneuver)
            }
            for maneuver in self.catalog.offense + self.catalog.defense
        }

        self.assertEqual(by_maneuver["Low Pass"], {"MIDFIELDER", "WINGER"})
        self.assertEqual(by_maneuver["Dribble Advance"], {"PLAYMAKER"})
        self.assertEqual(by_maneuver["High Pass"], {"FULLBACK", "STRIKER"})
        self.assertEqual(by_maneuver["Block Deflect"], {"FULLBACK"})
        self.assertEqual(by_maneuver["Steal Intercept"], {"BALL SPEED"})
        self.assertEqual(by_maneuver["Pressure"], {"DEFENDER", "MIDFIELDER"})

    def reference_skill_test_height(self) -> int:
        """A two-detail-line skill test, the size the others match."""
        image_data = render_skill_test_dice(
            [
                (7, "#f28c28", "Orange", ["Bulwark (Fullback)", "Defense 3"], 10),
                (4, "#19b5a5", "Teal", ["Snarl (Winger)", "Offense 2"], 6),
            ]
        )
        with Image.open(image_data) as image:
            return image.height

    def test_own_goal_dice_are_drawn_at_skill_test_size(self) -> None:
        # This roll used to draw two outsized dice captioned "Rolled".
        # It now matches the skill test's size and carries only the two
        # numbers, a ring on the one the advantage took, and the
        # outcome.
        self.assertEqual(OWN_GOAL_DIE_RADIUS, SKILL_TEST_DIE_RADIUS)

        image_data = render_own_goal_dice([7, 12], "#f28c28", safe=True)

        with Image.open(image_data) as image:
            self.assertEqual(image.format, "PNG")
            self.assertLessEqual(
                image.height, self.reference_skill_test_height(),
            )

    def test_injury_test_die_is_no_bigger_than_a_skill_test_die(self) -> None:
        # The whole point of the injury-test render is that it draws a
        # small die with context beside it.
        image_data = render_injury_test_die(
            5, "#19b5a5", "Teal", "Bulwark", safe=True,
        )

        with Image.open(image_data) as image:
            self.assertEqual(image.format, "PNG")
            self.assertLessEqual(
                image.height, self.reference_skill_test_height(),
            )

    def test_a_player_portrait_renders_on_its_own(self) -> None:
        image_data = render_player_portrait("Bulwark")

        self.assertIsNotNone(image_data)
        with Image.open(image_data) as image:
            self.assertEqual(image.format, "PNG")
            self.assertLessEqual(
                max(image.size), PORTRAIT_IMAGE_SIZE,
            )

    def test_a_player_without_a_portrait_renders_nothing(self) -> None:
        # Callers skip the attachment on None rather than handling an
        # exception, so a missing portrait has to stay silent.
        self.assertIsNone(render_player_portrait("Nobody At All"))


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
        cog.announce_board_update = mock.AsyncMock()
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
        # It goes out with the board, and names the space: "already
        # there" is only readable next to where "there" is.
        cog.announce_board_update.assert_awaited_once()
        announcement = cog.announce_board_update.await_args.args[2]
        self.assertIn("Block Deflect happened.", announcement)
        self.assertIn("# Turnover!", announcement)
        self.assertIn("uncontested", announcement)
        self.assertIn("M3", announcement)


class D12BallLowHighPassTests(unittest.IsolatedAsyncioTestCase):
    """
    Post-playtest revision: Low Pass has no fixed distance (the nearest
    teammate each way within 2 spaces, or one sharing the ball's space)
    and High Pass has a 2-4 space choice instead of a fixed 2. These drive low_pass_candidates(),
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

    def clear_offense_from(
        self, match: MatchState, zone: Zone, space_index: int,
    ) -> None:
        """
        Send any home card standing on a space back to its own goal
        line. A set-up names the landing space's first offense
        occupant, so a test that puts a particular shooter there has
        to empty it of the deal's own first, and board 9's spread
        puts a home card on both ends of the visitors' goal zone.
        """
        for player_id in list(match.board.spaces[zone][space_index]):
            if player_id in match.home.field_players:
                match.move_meeple(player_id, Zone.HOME_GOAL, 0)

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
        handler = home_players[3]
        visitor = match.visiting.field_players[0]

        match.move_meeple(behind, Zone.HOME_GOAL, 2)  # flat 2 (distance -2)
        # The handler and one teammate share the ball's space, so
        # distance 0 has someone other than the passer to reach.
        match.move_meeple(handler, Zone.MIDFIELD, 1)  # flat 4, ball here
        match.move_meeple(here, Zone.MIDFIELD, 1)
        # flat 3 (distance -1) and flat 5 (distance +1, opponent only)
        # are deliberately left without a home teammate.
        match.move_meeple(visitor, Zone.MIDFIELD, 2)
        match.move_meeple(ahead, Zone.VISITORS_GOAL, 0)  # flat 6 (distance +2)

        match.ball.possession = TeamSide.HOME
        match.set_ball_space(Zone.MIDFIELD, 1)
        match.active_player_id = handler

        cog = self.build_cog()
        self.assertEqual(
            cog.low_pass_candidates(match),
            [(-2, behind), (0, here), (2, ahead)],
        )

    def test_low_pass_candidates_only_reach_the_nearest_each_way(
        self,
    ) -> None:
        # 2026-08-07: each direction offers only its closest teammate,
        # so a second one standing further out is not a destination.
        match = self.build_match()
        self.clear_board(match)
        home_players = match.home.field_players
        near_behind, far_behind = home_players[0], home_players[1]
        near_ahead, far_ahead = home_players[2], home_players[3]
        handler = home_players[4]

        match.move_meeple(far_behind, Zone.HOME_GOAL, 2)  # distance -2
        match.move_meeple(near_behind, Zone.MIDFIELD, 0)  # distance -1
        match.move_meeple(handler, Zone.MIDFIELD, 1)
        match.move_meeple(near_ahead, Zone.MIDFIELD, 2)  # distance +1
        match.move_meeple(far_ahead, Zone.VISITORS_GOAL, 0)  # distance +2

        match.ball.possession = TeamSide.HOME
        match.set_ball_space(Zone.MIDFIELD, 1)
        match.active_player_id = handler

        cog = self.build_cog()
        self.assertEqual(
            cog.low_pass_candidates(match),
            [(-1, near_behind), (1, near_ahead)],
        )

    def test_low_pass_candidates_never_offer_the_passer(self) -> None:
        # A pass has to reach a different player, so a handler standing
        # alone on the ball's space is not a destination -- distance 0
        # drops out entirely.
        match = self.build_match()
        self.clear_board(match)
        handler, ahead = match.home.field_players[:2]
        match.move_meeple(handler, Zone.MIDFIELD, 1)
        match.move_meeple(ahead, Zone.MIDFIELD, 2)
        match.ball.possession = TeamSide.HOME
        match.set_ball_space(Zone.MIDFIELD, 1)
        match.active_player_id = handler

        cog = self.build_cog()
        self.assertEqual(cog.low_pass_candidates(match), [(1, ahead)])

    def test_low_pass_candidates_offer_a_teammate_sharing_the_space(
        self,
    ) -> None:
        # Distance 0 survives when a *second* player of the same side
        # is on the ball's space: that is a pass to a different player,
        # which is all the rule asks for.
        match = self.build_match()
        self.clear_board(match)
        handler, sharing = match.home.field_players[:2]
        match.move_meeple(handler, Zone.MIDFIELD, 1)
        match.move_meeple(sharing, Zone.MIDFIELD, 1)
        match.ball.possession = TeamSide.HOME
        match.set_ball_space(Zone.MIDFIELD, 1)
        match.active_player_id = handler

        cog = self.build_cog()
        self.assertEqual(cog.low_pass_candidates(match), [(0, sharing)])

    def test_low_pass_candidates_can_be_empty(self) -> None:
        # Nobody within two spaces and no self-pass allowed: the won
        # maneuver has nowhere to put the ball. resolve_low_pass is
        # what handles that; the candidate list just reports it.
        match = self.build_match()
        self.clear_board(match)
        handler = match.home.field_players[0]
        match.move_meeple(handler, Zone.MIDFIELD, 1)
        match.ball.possession = TeamSide.HOME
        match.set_ball_space(Zone.MIDFIELD, 1)
        match.active_player_id = handler

        cog = self.build_cog()
        self.assertEqual(cog.low_pass_candidates(match), [])

    def test_low_pass_candidates_excludes_distances_clamped_off_the_board(
        self,
    ) -> None:
        match = self.build_match()
        self.clear_board(match)
        handler, sharing = match.home.field_players[:2]
        match.move_meeple(handler, Zone.HOME_GOAL, 0)  # the board's own edge
        match.move_meeple(sharing, Zone.HOME_GOAL, 0)
        match.ball.possession = TeamSide.HOME
        match.set_ball_space(Zone.HOME_GOAL, 0)
        match.active_player_id = handler

        cog = self.build_cog()
        # -1 and -2 would go off the left edge and clamp back to the
        # ball's own space -- not real 1/2-space destinations, so they
        # must not appear even though a teammate is standing there (as
        # distance 0).
        self.assertEqual(cog.low_pass_candidates(match), [(0, sharing)])

    # -- low_pass_receivers -------------------------------------------

    def test_low_pass_receivers_lists_everyone_on_the_space(self) -> None:
        # A formation that stacks makes two or three teammates on one
        # space ordinary, and which of them receives is the passer's
        # choice -- the destination list only names the first.
        match = self.build_match()
        self.clear_board(match)
        handler, first, second = match.home.field_players[:3]
        for player_id in (handler, first, second):
            match.move_meeple(player_id, Zone.MIDFIELD, 1)
        match.ball.possession = TeamSide.HOME
        match.set_ball_space(Zone.MIDFIELD, 1)
        match.active_player_id = handler

        cog = self.build_cog()

        self.assertEqual(cog.low_pass_candidates(match), [(0, first)])
        self.assertEqual(
            cog.low_pass_receivers(match, 0), [first, second],
        )

    def test_low_pass_receivers_never_include_the_passer(self) -> None:
        match = self.build_match()
        self.clear_board(match)
        handler, sharing = match.home.field_players[:2]
        match.move_meeple(handler, Zone.MIDFIELD, 1)
        match.move_meeple(sharing, Zone.MIDFIELD, 1)
        match.ball.possession = TeamSide.HOME
        match.set_ball_space(Zone.MIDFIELD, 1)
        match.active_player_id = handler

        cog = self.build_cog()

        self.assertEqual(cog.low_pass_receivers(match, 0), [sharing])

    def test_low_pass_receivers_ignore_the_other_team(self) -> None:
        match = self.build_match()
        self.clear_board(match)
        handler, teammate = match.home.field_players[:2]
        opponent = match.visiting.field_players[0]
        for player_id in (handler, teammate, opponent):
            match.move_meeple(player_id, Zone.MIDFIELD, 1)
        match.ball.possession = TeamSide.HOME
        match.set_ball_space(Zone.MIDFIELD, 1)
        match.active_player_id = handler

        cog = self.build_cog()

        self.assertEqual(cog.low_pass_receivers(match, 0), [teammate])

    async def test_a_winger_s_set_up_goes_to_the_chosen_receiver(
        self,
    ) -> None:
        # The receiver is what the Winger's ability hands the shot to,
        # which is the whole reason the choice is asked for.
        cog = self.build_cog()
        match = self.build_match()
        self.clear_board(match)
        winger = self.player_with_role(match, TeamSide.HOME, PlayerRole.WINGER)
        first, second = [
            player_id
            for player_id in match.home.field_players
            if player_id != winger
        ][:2]
        # The far midfield space: within home's shooting range, so a
        # shot is legal from it at all (2026-08-09).
        for player_id in (winger, first, second):
            match.move_meeple(player_id, Zone.MIDFIELD, 2)
        match.ball.possession = TeamSide.HOME
        match.set_ball_space(Zone.MIDFIELD, 2)
        match.active_player_id = winger

        game = SimpleNamespace(game_id="g", match_state=None)
        interaction = SimpleNamespace(
            followup=SimpleNamespace(send=mock.AsyncMock()),
        )
        with mock.patch("cogs.d12ball.save_games"):
            await cog.apply_low_pass(
                interaction, game, match, 0, receiver_id=second,
            )

        self.assertEqual(
            cog.offer_scoring_attempt_choice.await_args.kwargs["shooter_id"],
            second,
        )

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
        # Low Pass's own clock cost is a flat 1 space minute regardless
        # of distance (2026-08-16), even though the ball moved 2.
        self.assertEqual(kwargs["distance_moved"], 1)
        self.assertIn("moves 2 spaces forward", kwargs["lead_in"])

    async def test_apply_low_pass_zero_distance_still_costs_its_flat_time(
        self,
    ) -> None:
        # Distance 0 is a pass to a teammate sharing the space, not a
        # hold: the ball doesn't travel, but Low Pass's flat 1 space
        # minute (2026-08-16) is charged regardless.
        cog = self.build_cog()
        match = self.build_match()
        handler = self.player_with_role(
            match, TeamSide.HOME, PlayerRole.DEFENDER,
        )
        sharing = next(
            pid for pid in match.home.field_players if pid != handler
        )
        match.active_player_id = handler
        match.ball.possession = TeamSide.HOME
        match.set_ball_space(Zone.MIDFIELD, 1)
        match.move_meeple(handler, Zone.MIDFIELD, 1)
        match.move_meeple(sharing, Zone.MIDFIELD, 1)
        match.ball.speed = 1

        interaction = SimpleNamespace()
        game = SimpleNamespace(match_state=None)
        with mock.patch("cogs.d12ball.save_games"):
            await cog.apply_low_pass(interaction, game, match, 0)

        self.assertEqual(
            (match.ball.zone, match.ball.space_index), (Zone.MIDFIELD, 1),
        )
        self.assertEqual(match.ball.speed, 2)
        # 2026-08-07: passing across a shared space is what sends the
        # passer forward -- the receiver stays on the ball.
        self.assertEqual(
            match.board.meeple_position(handler), (Zone.MIDFIELD, 2),
        )
        self.assertEqual(
            match.board.meeple_position(sharing), (Zone.MIDFIELD, 1),
        )
        _, kwargs = cog.finish_maneuver_resolution.await_args
        self.assertEqual(kwargs["distance_moved"], 1)
        self.assertIn(
            "goes to a teammate in the same space", kwargs["lead_in"],
        )
        self.assertIn("moves a space forward", kwargs["lead_in"])

    async def test_apply_low_pass_leaves_the_passer_where_a_real_pass_lands(
        self,
    ) -> None:
        # Only the shared-space pass moves the passer: the ball itself
        # travelling is what the other distances buy.
        cog = self.build_cog()
        match = self.build_match()
        self.clear_board(match)
        handler = self.player_with_role(
            match, TeamSide.HOME, PlayerRole.DEFENDER,
        )
        receiver = next(
            pid for pid in match.home.field_players if pid != handler
        )
        match.active_player_id = handler
        match.ball.possession = TeamSide.HOME
        match.set_ball_space(Zone.MIDFIELD, 1)
        match.move_meeple(handler, Zone.MIDFIELD, 1)
        match.move_meeple(receiver, Zone.MIDFIELD, 2)

        interaction = SimpleNamespace()
        game = SimpleNamespace(match_state=None)
        with mock.patch("cogs.d12ball.save_games"):
            await cog.apply_low_pass(interaction, game, match, 1)

        self.assertEqual(
            match.board.meeple_position(handler), (Zone.MIDFIELD, 1),
        )

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
        self.assertEqual(kwargs["distance_moved"], 1)
        self.assertIn("Winger ability", kwargs["lead_in"])

    async def test_a_winger_s_shot_goes_to_the_player_passed_to(
        self,
    ) -> None:
        # A pass across a shared space leaves passer and receiver both
        # standing on the ball, so the shot has to follow the player
        # the pass was aimed at rather than whoever the space lists
        # first -- which here is the passer.
        cog = self.build_cog()
        match = self.build_match()
        handler = self.player_with_role(
            match, TeamSide.HOME, PlayerRole.WINGER,
        )
        receiver = next(
            pid for pid in match.home.field_players if pid != handler
        )
        self.clear_board(match)
        match.active_player_id = handler
        match.ball.possession = TeamSide.HOME
        # The far midfield space: within home's shooting range, so a
        # shot is legal from it at all (2026-08-09).
        match.set_ball_space(Zone.MIDFIELD, 2)
        match.move_meeple(handler, Zone.MIDFIELD, 2)
        match.move_meeple(receiver, Zone.MIDFIELD, 2)
        # The passer is the space's first occupant, so taking the
        # first eligible handler would pick them rather than the
        # player the pass was aimed at.
        self.assertEqual(match.eligible_ball_handlers()[0], handler)

        interaction = SimpleNamespace()
        game = SimpleNamespace(match_state=None)
        with mock.patch("cogs.d12ball.save_games"):
            await cog.apply_low_pass(interaction, game, match, 0)

        _, kwargs = cog.offer_scoring_attempt_choice.await_args
        self.assertEqual(kwargs["shooter_id"], receiver)

    # -- resolve_low_pass ----------------------------------------------

    async def test_a_low_pass_with_nobody_to_pass_to_goes_loose(
        self,
    ) -> None:
        # Winning Low Pass with no teammate in reach is not a licence
        # to keep the ball by passing to yourself: the ball rolls a
        # space forward and is loose (2026-08-07), and still picks up
        # the maneuver's +1 speed on the way.
        cog = self.build_cog()
        cog.side_controlled_by_ai = mock.Mock(return_value=False)
        match = self.build_match()
        self.clear_board(match)
        handler = match.home.field_players[0]
        match.move_meeple(handler, Zone.MIDFIELD, 1)
        match.ball.possession = TeamSide.HOME
        match.set_ball_space(Zone.MIDFIELD, 1)
        match.ball.speed = 4
        match.active_player_id = handler

        interaction = SimpleNamespace(followup=SimpleNamespace(
            send=mock.AsyncMock(),
        ))
        game = SimpleNamespace(match_state=None)
        with mock.patch("cogs.d12ball.save_games"):
            await cog.resolve_low_pass(interaction, game, match)

        # No prompt, and no view to answer it with.
        interaction.followup.send.assert_not_awaited()
        self.assertEqual(
            (match.ball.zone, match.ball.space_index), (Zone.MIDFIELD, 2),
        )
        self.assertEqual(match.ball.speed, 5)
        cog.finish_maneuver_resolution.assert_not_awaited()
        cog.begin_loose_ball.assert_awaited_once()
        _, kwargs = cog.begin_loose_ball.await_args
        self.assertEqual(kwargs["distance_moved"], 1)
        self.assertIn("no teammate within two spaces", kwargs["lead_in"])
        self.assertIn("rolls a space forward", kwargs["lead_in"])

    async def test_a_low_pass_with_nowhere_to_roll_is_loose_where_it_is(
        self,
    ) -> None:
        # The far end of the field has no space to roll into, so the
        # ball is loose where it already sits rather than claiming a
        # move it could not make.
        cog = self.build_cog()
        cog.side_controlled_by_ai = mock.Mock(return_value=False)
        match = self.build_match()
        self.clear_board(match)
        handler = match.home.field_players[0]
        match.move_meeple(handler, Zone.VISITORS_GOAL, 2)
        match.ball.possession = TeamSide.HOME
        match.set_ball_space(Zone.VISITORS_GOAL, 2)  # the board's own edge
        match.active_player_id = handler

        interaction = SimpleNamespace(followup=SimpleNamespace(
            send=mock.AsyncMock(),
        ))
        game = SimpleNamespace(match_state=None)
        with mock.patch("cogs.d12ball.save_games"):
            await cog.resolve_low_pass(interaction, game, match)

        self.assertEqual(
            (match.ball.zone, match.ball.space_index),
            (Zone.VISITORS_GOAL, 2),
        )
        cog.begin_loose_ball.assert_awaited_once()
        _, kwargs = cog.begin_loose_ball.await_args
        self.assertEqual(kwargs["distance_moved"], 1)
        self.assertIn("stays where it is", kwargs["lead_in"])
        # The speed bonus doesn't depend on the ball finding room to
        # roll either.
        self.assertEqual(match.ball.speed, 2)

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
        self.clear_offense_from(match, Zone.VISITORS_GOAL, 2)
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
        cog.begin_loose_ball.assert_not_awaited()

    async def test_apply_high_pass_distance_two_without_a_teammate_becomes_a_loose_ball(
        self,
    ) -> None:
        """
        No offense player standing where the pass lands means there's
        no receiver to force a High Pass skill test for -- this isn't
        the High Pass contest at all, just an ordinary overshoot that
        finish_maneuver_resolution's own loose-ball detour handles,
        same as any other maneuver.
        """
        cog = self.build_cog()
        match = self.build_match()
        handler = self.player_with_role(
            match, TeamSide.HOME, PlayerRole.DEFENDER,
        )
        match.active_player_id = handler
        match.ball.possession = TeamSide.HOME
        match.set_ball_space(Zone.HOME_GOAL, 0)  # flat 0, plenty of room,
        # and nobody is standing on the landing space (flat 2).

        interaction = SimpleNamespace()
        game = SimpleNamespace(match_state=None)
        with mock.patch("cogs.d12ball.save_games"):
            await cog.apply_high_pass(interaction, game, match, 2)

        self.assertEqual(
            (match.ball.zone, match.ball.space_index), (Zone.HOME_GOAL, 2),
        )
        cog.offer_scoring_attempt_choice.assert_not_awaited()
        cog.begin_loose_ball.assert_not_awaited()
        cog.finish_maneuver_resolution.assert_awaited_once()

    async def test_apply_high_pass_with_a_teammate_forces_skill_test(
        self,
    ) -> None:
        """
        A receiver already standing on the landing space still has to
        win a skill test to keep the ball -- unlike any other
        maneuver -- but they're the automatic offense contestant, no
        pick required. A visiting card on that same space (spaces are
        shared between both sides) is likewise automatic rather than
        a zone-wide pick.

        The pass is placed to land two short of the edge: a distance
        of 3 offers no scoring-opportunity setup unless it overshoots
        (2026-08-10), so landing with room to spare is what isolates
        the forced-contest branch from that one. Board 9's deal
        spreads each side's pair to the ends of that zone and leaves
        the middle space empty, so both contestants are put there.
        """
        cog = self.build_cog()
        match = self.build_match()
        handler = self.player_with_role(
            match, TeamSide.HOME, PlayerRole.DEFENDER,
        )
        match.active_player_id = handler
        match.ball.possession = TeamSide.HOME
        match.set_ball_space(Zone.MIDFIELD, 1)  # flat 4, landing on flat 7
        receiver = self.player_with_role(
            match, TeamSide.HOME, PlayerRole.STRIKER,
        )
        defender_on_space = self.player_with_role(
            match, TeamSide.VISITING, PlayerRole.DEFENDER,
        )
        match.move_meeple(receiver, Zone.VISITORS_GOAL, 1)
        match.move_meeple(defender_on_space, Zone.VISITORS_GOAL, 1)

        interaction = SimpleNamespace()
        game = SimpleNamespace(match_state=None)
        with mock.patch("cogs.d12ball.save_games"):
            await cog.apply_high_pass(interaction, game, match, 3)

        self.assertEqual(
            (match.ball.zone, match.ball.space_index),
            (Zone.VISITORS_GOAL, 1),
        )
        cog.offer_scoring_attempt_choice.assert_not_awaited()
        self.assertFalse(match.pending_high_pass_overshoot)
        cog.begin_loose_ball.assert_awaited_once()
        _, kwargs = cog.begin_loose_ball.await_args
        self.assertEqual(kwargs["headline"], HIGH_PASS_CONTEST_HEADLINE)
        self.assertEqual(kwargs["forced_offense_player"], receiver)
        self.assertEqual(kwargs["forced_defense_player"], defender_on_space)

    async def test_apply_high_pass_distance_two_offers_setup_without_overshoot(
        self,
    ) -> None:
        """
        The scoring-opportunity offer no longer requires the pass to
        overshoot the field -- an exact 2-space pass that lands on a
        teammate short of the edge offers it too. It does have to land
        within shooting range, which is where a shot may be taken
        from at all (2026-08-09).
        """
        cog = self.build_cog()
        match = self.build_match()
        handler = self.player_with_role(
            match, TeamSide.HOME, PlayerRole.DEFENDER,
        )
        match.active_player_id = handler
        match.ball.possession = TeamSide.HOME
        match.set_ball_space(Zone.MIDFIELD, 1)  # flat 4, the middle space
        shooter = match.home.field_players[0]
        # flat 6, the landing space: the visitors' half, two short of
        # the edge. The standard setup already has someone there.
        self.clear_offense_from(match, Zone.VISITORS_GOAL, 0)
        match.move_meeple(shooter, Zone.VISITORS_GOAL, 0)

        interaction = SimpleNamespace()
        game = SimpleNamespace(match_state=None)
        with mock.patch("cogs.d12ball.save_games"):
            await cog.apply_high_pass(interaction, game, match, 2)

        self.assertEqual(
            (match.ball.zone, match.ball.space_index),
            (Zone.VISITORS_GOAL, 0),
        )
        cog.begin_loose_ball.assert_not_awaited()
        cog.offer_scoring_attempt_choice.assert_awaited_once()
        _, kwargs = cog.offer_scoring_attempt_choice.await_args
        self.assertEqual(kwargs["shooter_id"], shooter)

    async def test_apply_high_pass_distance_three_overshoot_offers_setup(
        self,
    ) -> None:
        """
        2026-08-10: a distance of 3 offers no set-up on its own, but an
        overshoot offers one whatever distance was asked for, on the
        space closest to the goal -- which is where the clamp puts the
        ball. The ball speed modifier is turned around for it.
        """
        cog = self.build_cog()
        match = self.build_match()
        handler = self.player_with_role(
            match, TeamSide.HOME, PlayerRole.DEFENDER,
        )
        match.active_player_id = handler
        match.ball.possession = TeamSide.HOME
        match.set_ball_space(Zone.VISITORS_GOAL, 1)  # flat 7, 3 overshoots
        match.ball.speed = 4  # a +2 modifier, so the sign is visible
        shooter = match.home.field_players[0]
        self.clear_offense_from(match, Zone.VISITORS_GOAL, 2)
        match.move_meeple(shooter, Zone.VISITORS_GOAL, 2)  # flat 8, landing

        interaction = SimpleNamespace()
        game = SimpleNamespace(match_state=None)
        with mock.patch("cogs.d12ball.save_games"):
            await cog.apply_high_pass(interaction, game, match, 3)

        self.assertEqual(
            (match.ball.zone, match.ball.space_index),
            (Zone.VISITORS_GOAL, 2),
        )
        cog.begin_loose_ball.assert_not_awaited()
        cog.offer_scoring_attempt_choice.assert_awaited_once()
        _, kwargs = cog.offer_scoring_attempt_choice.await_args
        self.assertEqual(kwargs["shooter_id"], shooter)
        # The contest is still owed at 3, so declining lands there
        # rather than settling the ball.
        self.assertTrue(kwargs["contest_on_decline"])
        self.assertTrue(match.pending_high_pass_overshoot)
        self.assertEqual(match.ball_speed_modifier(), -2)
        self.assertEqual(match.ball_carrier_id, shooter)

    async def test_a_moot_high_pass_distance_is_never_asked_for(
        self,
    ) -> None:
        """
        2026-08-10: from 0 or 1 spaces off the end of the field every
        distance lands on the same space, so the pass is an overshoot
        before anyone picks anything and the distance prompt is
        skipped rather than answered -- for a Fullback's 4 as much as
        for the 2.
        """
        cog = self.build_cog()
        cog.apply_high_pass = mock.AsyncMock()
        cog.side_controlled_by_ai = mock.Mock(return_value=False)
        match = self.build_match()
        match.ball.possession = TeamSide.HOME
        match.active_player_id = self.player_with_role(
            match, TeamSide.HOME, PlayerRole.FULLBACK,
        )

        interaction = SimpleNamespace()
        game = SimpleNamespace(match_state=None)
        for space_index in (1, 2):  # flat 7 and flat 8: 1 away, then 0
            match.set_ball_space(Zone.VISITORS_GOAL, space_index)
            self.assertTrue(match.high_pass_distance_is_moot(TeamSide.HOME))
            with mock.patch("cogs.d12ball.save_games"):
                await cog.resolve_high_pass(interaction, game, match)

        self.assertEqual(cog.apply_high_pass.await_count, 2)
        for call in cog.apply_high_pass.await_args_list:
            self.assertEqual(call.args[-1], 2)
        cog.side_controlled_by_ai.assert_not_called()

    def test_a_high_pass_distance_two_spaces_out_is_a_real_choice(
        self,
    ) -> None:
        # The other side of it: from 2 away a 2 lands exactly and only
        # a 3 or a 4 overshoots, so the coach is asked.
        match = self.build_match()
        match.ball.possession = TeamSide.HOME
        match.set_ball_space(Zone.VISITORS_GOAL, 0)  # flat 6 of 0..8
        self.assertFalse(match.high_pass_distance_is_moot(TeamSide.HOME))
        self.assertFalse(match.high_pass_overshoots(TeamSide.HOME, 2))
        self.assertTrue(match.high_pass_overshoots(TeamSide.HOME, 3))

        # And the same reading from the other end of the board, where
        # the attack direction is reversed.
        match.ball.possession = TeamSide.VISITING
        match.set_ball_space(Zone.HOME_GOAL, 1)  # flat 1, 1 away
        self.assertTrue(match.high_pass_distance_is_moot(TeamSide.VISITING))
        match.set_ball_space(Zone.HOME_GOAL, 2)  # flat 2, 2 away
        self.assertFalse(match.high_pass_distance_is_moot(TeamSide.VISITING))

    def test_a_distance_that_runs_off_the_field_is_not_on_offer(self) -> None:
        """
        2026-08-10: a longer pass that lands where a shorter one
        already would is the same pass at a disadvantage, so it is
        dropped from the menu rather than offered. A Fullback's 4 is
        no more protected than anyone's 3.
        """
        match = self.build_match()
        match.ball.possession = TeamSide.HOME  # attacking toward flat 8

        for space, expected_3, expected_4 in (
            ((Zone.MIDFIELD, 1), [2, 3], [2, 3, 4]),      # flat 4, 4 away
            ((Zone.MIDFIELD, 2), [2, 3], [2, 3]),         # flat 5, 3 away
            ((Zone.VISITORS_GOAL, 0), [2], [2]),          # flat 6, 2 away
            ((Zone.VISITORS_GOAL, 1), [], []),            # flat 7, 1 away
            ((Zone.VISITORS_GOAL, 2), [], []),            # flat 8, at the end
        ):
            with self.subTest(space=space):
                match.set_ball_space(*space)
                self.assertEqual(
                    match.high_pass_distances(TeamSide.HOME, 3), expected_3,
                )
                self.assertEqual(
                    match.high_pass_distances(TeamSide.HOME, 4), expected_4,
                )
                # The two readings of "nothing fits" agree, and the
                # cheaper one is what resolve_high_pass asks.
                self.assertEqual(
                    match.high_pass_distance_is_moot(TeamSide.HOME),
                    not match.high_pass_distances(TeamSide.HOME, 4),
                )

    def test_the_menu_reads_the_handler_s_own_maximum(self) -> None:
        # The Fullback's ability raises the maximum, and the field
        # takes it away again three spaces from the end.
        cog = self.build_cog()
        match = self.build_match()
        match.ball.possession = TeamSide.HOME
        match.set_ball_space(Zone.MIDFIELD, 1)  # flat 4, four spaces of room

        match.active_player_id = self.player_with_role(
            match, TeamSide.HOME, PlayerRole.FULLBACK,
        )
        self.assertEqual(cog.high_pass_distance_options(match), [2, 3, 4])
        match.active_player_id = self.player_with_role(
            match, TeamSide.HOME, PlayerRole.DEFENDER,
        )
        self.assertEqual(cog.high_pass_distance_options(match), [2, 3])

        match.set_ball_space(Zone.MIDFIELD, 2)  # flat 5, three of room
        match.active_player_id = self.player_with_role(
            match, TeamSide.HOME, PlayerRole.FULLBACK,
        )
        self.assertEqual(cog.high_pass_distance_options(match), [2, 3])

    async def test_apply_high_pass_overshoot_always_contests_on_decline(
        self,
    ) -> None:
        """
        An overshoot is a shot at a disadvantage or a contest to keep
        the ball -- two halves of one choice, not an offer and a
        fallback -- so declining lands in the contest whatever
        distance reached here. A 2 can only overshoot from a position
        where no distance was offered at all.
        """
        cog = self.build_cog()
        match = self.build_match()
        handler = self.player_with_role(
            match, TeamSide.HOME, PlayerRole.DEFENDER,
        )
        match.active_player_id = handler
        match.ball.possession = TeamSide.HOME
        match.set_ball_space(Zone.VISITORS_GOAL, 1)  # flat 7, 2 overshoots
        shooter = match.home.field_players[0]
        self.clear_offense_from(match, Zone.VISITORS_GOAL, 2)
        match.move_meeple(shooter, Zone.VISITORS_GOAL, 2)  # flat 8, landing

        interaction = SimpleNamespace()
        game = SimpleNamespace(match_state=None)
        with mock.patch("cogs.d12ball.save_games"):
            await cog.apply_high_pass(interaction, game, match, 2)

        cog.offer_scoring_attempt_choice.assert_awaited_once()
        _, kwargs = cog.offer_scoring_attempt_choice.await_args
        self.assertTrue(kwargs["contest_on_decline"])
        self.assertTrue(match.pending_high_pass_overshoot)

    async def test_apply_high_pass_overshoot_with_nobody_there_sets_up_nothing(
        self,
    ) -> None:
        """
        An overshoot with no offense player on the landing space has
        nobody to shoot, so it falls through to the ordinary paths and
        ends as a loose ball or a clean turnover, exactly as it did
        before the rule. Nothing turns the speed modifier around
        either -- there is no set-up for it to apply to.
        """
        cog = self.build_cog()
        match = self.build_match()
        handler = self.player_with_role(
            match, TeamSide.HOME, PlayerRole.DEFENDER,
        )
        match.active_player_id = handler
        match.ball.possession = TeamSide.HOME
        match.set_ball_space(Zone.VISITORS_GOAL, 1)  # flat 7, 3 overshoots
        # Leave only the visiting card the deal puts on flat 8.
        self.clear_offense_from(match, Zone.VISITORS_GOAL, 2)

        interaction = SimpleNamespace()
        game = SimpleNamespace(match_state=None)
        with mock.patch("cogs.d12ball.save_games"):
            await cog.apply_high_pass(interaction, game, match, 3)

        cog.offer_scoring_attempt_choice.assert_not_awaited()
        self.assertFalse(match.pending_high_pass_overshoot)
        cog.finish_maneuver_resolution.assert_awaited_once()

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

    def test_bundled_art_is_named_exactly_as_the_code_asks_for_it(
        self,
    ) -> None:
        """
        The same failure the fonts have, one layer down: every icon
        loader swallows an OSError and returns None so a render can go
        on without the art, so a file the code cannot open is silent --
        the board simply comes out with no exhaustion token on it.

        `Path.exists` is not the test. **One developer's filesystem is
        case-insensitive and the other's is not**, so a path that
        differs from the tracked file only in case opens on macOS and
        misses on Linux, which is exactly how `Exhaust.png` sat in the
        repo against an `exhaust.png` in the code. Comparing against the
        directory's own listing is what fails on both.
        """
        for path in (
            EXHAUST_ICON_PATH,
            EXHAUSTED_ICON_PATH,
            INJURED_ICON_PATH,
        ):
            with self.subTest(icon=path.name):
                self.assertIn(
                    path.name,
                    os.listdir(path.parent),
                    f"{path.name} is not in {path.parent} under that "
                    "exact name",
                )

    def test_render_fonts_keep_their_relative_scale(self) -> None:
        # The bug's signature was every font collapsing to one size.
        self.assertGreater(FONT_SCORE.size, FONT_TITLE.size)
        self.assertGreater(FONT_TITLE.size, FONT_HEADING.size)
        self.assertGreater(FONT_HEADING.size, FONT_BODY.size)
        self.assertGreater(FONT_BODY.size, FONT_SMALL.size)

    def test_bundled_font_covers_board_label_glyphs(self) -> None:
        # The em dash in the team board heading rendered as a tofu box
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
