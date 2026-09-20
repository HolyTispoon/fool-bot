import dataclasses
import inspect
import itertools
import json
import os
import re
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from PIL import Image, ImageDraw, ImageFont

from cogs.d12ball import HIGH_PASS_CONTEST_HEADLINE, D12Ball
from d12ball.cards import (
    HAND_CARD_WIDTH,
    HAND_GAP,
    HAND_HEADING_GAP,
    HAND_HEADING_SIZE,
    HAND_MARGIN,
    SHEET_COLUMNS,
    SHEET_MARGIN_X,
    SHEET_MARGIN_Y,
    CARD_HEIGHT,
    CARD_WIDTH,
    print_sheet,
    render_maneuver_card,
    render_maneuver_card_back,
    render_maneuver_hands,
    role_abilities,
    tie_pairs,
)
from d12ball.components import (
    MANEUVER_TIER_ADVANCED,
    SPECIES_ORDER,
    MANEUVER_TIER_BASIC,
    MATCH_EXPLICIT_FIELDS,
    MATCH_SAVED_FIELDS,
    catalog_player_id,
    duplicate_card_id,
    DUPLICATE_CARD_SUFFIX,
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
from d12ball.engine import RulesEngine
from d12ball.game import (
    COLOR_TEAMS,
    SPECIES_TEAMS,
    TEAM_PAIRS,
    Formation,
    Team,
    paired_team,
    team_display_name,
)
from d12ball.render import (
    BOARD_BOTTOM,
    EXHAUSTED_ICON_PATH,
    EXHAUST_ICON_PATH,
    INJURED_ICON_PATH,
    SPECIES_ICON_DIR,
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
    BOARD_BOTTOM,
    FONT_TOKEN_ROLE,
    FONT_TOKEN_SOLO,
    draw_meeple_face,
    HOME_MEEPLE_TOP,
    MEEPLE_LABEL_MIN_SIZE,
    MEEPLE_ROLE_BOTTOM_INSET,
    MEEPLE_SIZE,
    MEEPLE_SPECIES_ICON_SIZE,
    MEEPLE_SPECIES_ICON_TOP,
    VISITING_MEEPLE_TOP,
    PORTRAIT_IMAGE_SIZE,
    ball_token_x,
    fit_meeple_labels,
    OWN_GOAL_DIE_RADIUS,
    SKILL_TEST_DIE_RADIUS,
    TEAM_COLORS,
    load_font,
    load_goal_zone_font,
    player_index,
    render_coaching_image,
    render_field_image,
    species_icon,
    INJURY_TEST_PORTRAIT_SIZE,
    MIND_PULL_DIE_RADIUS,
    MIND_PULL_HALO_SCALE,
    VOLATILE_DIE_RADIUS,
    VOLATILE_HALO_SCALE,
    VOLATILE_PORTRAIT_SIZE,
    mind_pull_target_label,
    render_injury_test_die,
    render_mind_pull_die,
    render_volatile_die,
    volatile_explainer_label,
    render_own_goal_dice,
    render_skill_test_dice,
    render_maneuver_reference_image,
    render_match_image,
    render_player_portrait,
    zone_bounds_between,
)
from roster import benched, field_players, fielded, roles
from save_patches import suppressed_cog_saves


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class D12BallComponentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    def test_catalog_contains_eight_nine_player_teams(self) -> None:
        # Since the 2026-08-17 eight-team split: 4 color teams and 4
        # species teams, each 9 players -- but 36 players total, not
        # 72, because every id is named by exactly one of each. See
        # "Team colors" in docs/design/teams-and-players.md.
        self.assertEqual(set(self.catalog.teams), set(Team))

        color_teams = (Team.ORANGE, Team.TEAL, Team.PURPLE, Team.SLIME)
        species_teams = (
            Team.FIRE_DEMONS, Team.CYBORGS, Team.TELEKINETICS, Team.OOZES,
        )
        self.assertEqual(set(TEAM_PAIRS), set(color_teams) | set(species_teams))

        ids_by_color: dict[str, Team] = {}
        for team in color_teams:
            roster = self.catalog.teams[team]
            self.assertEqual(len(roster.players), 9)
            for player in roster.players:
                self.assertNotIn(
                    player.player_id, ids_by_color,
                    f"{player.player_id} is on two color teams.",
                )
                ids_by_color[player.player_id] = team

        ids_by_species: dict[str, Team] = {}
        for team in species_teams:
            roster = self.catalog.teams[team]
            self.assertEqual(len(roster.players), 9)
            for player in roster.players:
                self.assertNotIn(
                    player.player_id, ids_by_species,
                    f"{player.player_id} is on two species teams.",
                )
                ids_by_species[player.player_id] = team

        self.assertEqual(len(ids_by_color), 36)
        self.assertEqual(set(ids_by_color), set(ids_by_species))

        # A player's species-team placement has to agree with their own
        # `species` field -- e.g. every id under Fire Demons is a
        # PlayerDefinition whose species is "fire_demon". (Every
        # species value here happens to pluralize to its team's enum
        # value, which is just English, not a rule to lean on
        # elsewhere.)
        players_by_id = {
            player.player_id: player
            for roster in self.catalog.teams.values()
            for player in roster.players
        }
        for player_id, species_team in ids_by_species.items():
            species = players_by_id[player_id].species
            self.assertEqual(f"{species}s", species_team.value)

        # And the reshuffle's own promise holds: each color team fields
        # exactly 3 of its own paired species (TEAM_PAIRS) and 2 of
        # each of the other three.
        for color_team in color_teams:
            own_species_team = TEAM_PAIRS[color_team]
            species_counts: dict[Team, int] = {}
            for player_id, team in ids_by_color.items():
                if team != color_team:
                    continue
                species = players_by_id[player_id].species
                species_team = Team(f"{species}s")
                species_counts[species_team] = (
                    species_counts.get(species_team, 0) + 1
                )
            for species_team in species_teams:
                expected = 3 if species_team == own_species_team else 2
                self.assertEqual(
                    species_counts.get(species_team, 0),
                    expected,
                    f"{color_team.value}: expected {expected} "
                    f"{species_team.value}, found "
                    f"{species_counts.get(species_team, 0)}.",
                )

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

        # The deal is by role and not by name: one of each of the six
        # the standard setup lists, read from a coach's own goal
        # forward. Asking for the roles is asking for the rule -- the
        # names filling them are the author's to revise.
        self.assertEqual(
            roles(setup.zones[Zone.HOME_GOAL]),
            self.rules.standard_setup["own_goal"],
        )
        self.assertEqual(
            roles(setup.zones[Zone.MIDFIELD]),
            self.rules.standard_setup["midfield"],
        )
        self.assertEqual(
            roles(setup.zones[Zone.VISITORS_GOAL]),
            self.rules.standard_setup["opponent_goal"],
        )

        # Everyone the deal passed over sits down, in roster order,
        # and nobody is in two places at once.
        self.assertEqual(
            sorted(setup.field_players + setup.team_board.bench),
            sorted(player.player_id for player in roster.players),
        )
        self.assertEqual(
            setup.team_board.bench,
            [
                player.player_id
                for player in roster.players
                if player.player_id not in setup.field_players
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

        # The same three areas, dealt from the other end of the field:
        # a visiting coach's own goal is the visitors goal zone, and
        # the one they attack is the home goal.
        self.assertEqual(
            roles(setup.zones[Zone.VISITORS_GOAL]),
            self.rules.standard_setup["own_goal"],
        )
        self.assertEqual(
            roles(setup.zones[Zone.MIDFIELD]),
            self.rules.standard_setup["midfield"],
        )
        self.assertEqual(
            roles(setup.zones[Zone.HOME_GOAL]),
            self.rules.standard_setup["opponent_goal"],
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
        on_cards = set(
            match.home.field_players + match.visiting.field_players
        )
        meeples = {
            player_id
            for spaces in match.board.spaces.values()
            for occupants in spaces
            for player_id in occupants
        }
        self.assertEqual(meeples, on_cards)
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
        # Where the deal puts each of them: a goal zone's pair takes
        # its two end spaces and midfield packs toward that side's own
        # goal (setup_space_order). Named by role, since which card
        # fills a role is the author's to revise.
        expected = {
            (TeamSide.HOME, PlayerRole.FULLBACK): (Zone.HOME_GOAL, 0),
            (TeamSide.HOME, PlayerRole.DEFENDER): (Zone.HOME_GOAL, 1),
            (TeamSide.HOME, PlayerRole.MIDFIELDER): (Zone.MIDFIELD, 0),
            (TeamSide.HOME, PlayerRole.PLAYMAKER): (Zone.MIDFIELD, 1),
            (TeamSide.HOME, PlayerRole.STRIKER): (Zone.VISITORS_GOAL, 1),
            (TeamSide.VISITING, PlayerRole.FULLBACK): (Zone.VISITORS_GOAL, 1),
            (TeamSide.VISITING, PlayerRole.MIDFIELDER): (Zone.MIDFIELD, 2),
            (TeamSide.VISITING, PlayerRole.PLAYMAKER): (Zone.MIDFIELD, 1),
            (TeamSide.VISITING, PlayerRole.STRIKER): (Zone.HOME_GOAL, 0),
        }
        for (side, role), position in expected.items():
            with self.subTest(side=side, role=role):
                self.assertEqual(
                    match.board.meeple_position(fielded(match, role, side)),
                    position,
                )
        self.assertEqual(match.ball.zone, Zone.MIDFIELD)
        self.assertEqual(match.ball.space_index, 1)
        self.assertEqual(match.ball.possession, TeamSide.HOME)
        self.assertEqual(match.ball.speed, 1)
        self.assertEqual(
            match.eligible_ball_handlers(),
            [fielded(match, PlayerRole.PLAYMAKER)],
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
        handler = fielded(match, PlayerRole.MIDFIELDER)
        on_the_ball = fielded(match, PlayerRole.PLAYMAKER)
        match.move_meeple(handler, Zone.MIDFIELD, 1)

        self.assertEqual(
            match.eligible_ball_handlers(),
            [on_the_ball, handler],
        )
        with self.assertRaises(ValueError):
            match.select_ball_handler(
                fielded(match, PlayerRole.PLAYMAKER, TeamSide.VISITING),
            )

        match.select_ball_handler(handler)
        match.validate(self.catalog)
        restored = MatchState.from_dict(
            match.to_dict(),
            self.rules,
        )
        self.assertEqual(restored.active_player_id, handler)

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
        outgoing = fielded(match, PlayerRole.DEFENDER)
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
        outgoing = fielded(match, PlayerRole.DEFENDER)
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

        # Three swaps drain a bench of three; which three go off is
        # immaterial.
        for outgoing in field_players(match)[:3]:
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
            fielded(match, PlayerRole.WINGER),
            match.home.team_board.back_bench[0],
        )

    def test_injured_players_never_come_back(self) -> None:
        match = self.standard_match()
        injured = fielded(match, PlayerRole.STRIKER)
        match.mark_injured(injured)
        match.substitute(
            TeamSide.HOME, injured, match.home.team_board.bench[0],
        )
        # Two more off, to drain what is left of the bench.
        for outgoing in field_players(match)[:2]:
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
            match.substitute(
                TeamSide.HOME, fielded(match, PlayerRole.PLAYMAKER), injured,
            )

    def test_nobody_to_bring_on_takes_both_benches(self) -> None:
        # The only way a side runs out: the bench drained, and every
        # one of the three who came off went off injured.
        match = self.standard_match()
        for outgoing in field_players(match)[:3]:
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
        returning = fielded(match, PlayerRole.FULLBACK)
        match.add_exhaustion(returning, 5)
        match.mark_exhausted_if_needed(returning, defense_skill=2)
        self.assertIn(returning, match.exhausted)

        match.substitute(
            TeamSide.HOME, returning, match.home.team_board.bench[0],
        )
        for outgoing in (
            fielded(match, PlayerRole.MIDFIELDER),
            fielded(match, PlayerRole.PLAYMAKER),
        ):
            match.substitute(
                TeamSide.HOME,
                outgoing,
                match.home.team_board.bench[0],
            )

        injured = fielded(match, PlayerRole.STRIKER)
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
        first = fielded(match, PlayerRole.FULLBACK)
        second = fielded(match, PlayerRole.STRIKER)
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
        stealer = fielded(match, PlayerRole.DEFENDER)
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
        stealer = fielded(match, PlayerRole.DEFENDER)
        match.pending_run_back_stays_player_id = stealer

        match.swap_field_positions(
            TeamSide.HOME,
            fielded(match, PlayerRole.FULLBACK),
            fielded(match, PlayerRole.MIDFIELDER),
        )

        self.assertEqual(match.pending_run_back_stays_player_id, stealer)

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
        first = fielded(match, PlayerRole.FULLBACK)
        second = fielded(match, PlayerRole.STRIKER)
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
        stealer = fielded(match, PlayerRole.FULLBACK)
        swapped_with = fielded(match, PlayerRole.STRIKER)
        match.pending_run_back_stays_player_id = stealer

        match.swap_meeple_positions(TeamSide.HOME, stealer, swapped_with)

        self.assertEqual(
            match.pending_run_back_stays_player_id, swapped_with,
        )

    def test_a_new_play_is_free_and_only_a_time_out_is_once_a_half(
        self,
    ) -> None:
        # The 2026-09-16 split. A new play's window costs nothing
        # however many a side takes; the once-a-half moved onto the
        # time out, which is now the only Coaching Choice a side pays
        # anything for.
        match = self.standard_match()
        self.assertTrue(match.may_take_time_out(TeamSide.HOME))

        # Three new plays, taken up every time, and the time out is
        # still in hand.
        for _ in range(3):
            match.open_coaching_window(
                TeamSide.HOME, CoachingOccasion.NEW_PLAY,
            )
            match.declare_coaching()
            match.close_coaching_window()
            self.assertTrue(match.may_take_time_out(TeamSide.HOME))

        # The time out spends it, and only for the side that called it.
        match.open_coaching_window(TeamSide.HOME, CoachingOccasion.TIME_OUT)
        match.declare_coaching()
        self.assertEqual(match.substitutions_remaining(), 2)
        match.close_coaching_window()
        self.assertFalse(match.may_take_time_out(TeamSide.HOME))

        # A side that has spent its time out still coaches at a new
        # play: what it has run out of is the pause it pays for, not
        # the one the play hands it.
        match.open_coaching_window(TeamSide.HOME, CoachingOccasion.NEW_PLAY)
        match.declare_coaching()
        match.close_coaching_window()
        self.assertFalse(match.may_take_time_out(TeamSide.HOME))

        # Answering the other team's time out costs the answering team
        # nothing, so the visitors still hold their own -- and they
        # answer with the same two substitutions, not a smaller
        # allowance.
        match.open_coaching_window(
            TeamSide.VISITING,
            CoachingOccasion.TIME_OUT,
            is_response=True,
        )
        match.declare_coaching()
        self.assertEqual(match.substitutions_remaining(), 2)
        match.close_coaching_window()
        self.assertTrue(match.may_take_time_out(TeamSide.VISITING))

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
        self.assertTrue(match.may_take_time_out(TeamSide.VISITING))
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
        self.assertTrue(match.may_take_time_out(TeamSide.HOME))

        injured = fielded(match, PlayerRole.STRIKER)
        match.mark_injured(injured)
        self.assertTrue(match.may_take_time_out(TeamSide.HOME))
        self.assertEqual(
            match.injured_field_players(TeamSide.HOME), [injured],
        )
        self.assertFalse(hasattr(match, "must_declare_substitution"))

        match.time_outs_used.add(TeamSide.HOME.value)
        self.assertFalse(match.may_take_time_out(TeamSide.HOME))

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
        match.time_outs_used.add(TeamSide.HOME.value)
        match.open_coaching_window(
            TeamSide.VISITING,
            CoachingOccasion.NEW_PLAY,
            is_response=True,
        )
        match.declare_coaching()
        match.record_substitution()

        restored = MatchState.from_dict(match.to_dict(), self.rules)

        self.assertEqual(
            restored.time_outs_used, {TeamSide.HOME.value},
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

        self.assertEqual(restored.time_outs_used, set())
        self.assertIsNone(restored.pending_coaching_side)
        self.assertIsNone(restored.coaching_occasion)
        self.assertTrue(restored.may_take_time_out(TeamSide.HOME))

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
            match.choose_defense_maneuver("Deflect")

        restored = MatchState.from_dict(match.to_dict(), self.rules)
        self.assertEqual(restored.offense_maneuver, "low_pass")
        self.assertEqual(restored.defense_maneuver, "pressure")

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
        player_id = fielded(match, PlayerRole.FULLBACK, TeamSide.VISITING)

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
        player_id = fielded(match, PlayerRole.FULLBACK, TeamSide.VISITING)
        match.add_exhaustion(player_id, 3)
        match.mark_exhausted_if_needed(player_id, 2)
        match.mark_injured(player_id)

        self.assertEqual(match.exhaustion.get(player_id, 0), 0)
        self.assertNotIn(player_id, match.exhausted)

        match.add_exhaustion(player_id, 5)
        self.assertEqual(match.exhaustion.get(player_id, 0), 0)
        self.assertFalse(match.mark_exhausted_if_needed(player_id, 2))

        restored = MatchState.from_dict(match.to_dict(), self.rules)
        self.assertEqual(restored.exhaustion.get(player_id, 0), 0)
        self.assertNotIn(player_id, restored.exhausted)
        self.assertEqual(restored.injured, {player_id})

    def test_old_injured_save_is_normalized_on_load(self) -> None:
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=7,
            home_team=Team.SLIME,
            visiting_team=Team.TEAL,
        )
        player_id = fielded(match, PlayerRole.FULLBACK, TeamSide.VISITING)
        saved = match.to_dict()
        saved["injured"] = [player_id]
        saved["exhausted"] = [player_id]
        saved["exhaustion"] = {player_id: 6}

        restored = MatchState.from_dict(saved, self.rules)

        self.assertEqual(restored.injured, {player_id})
        self.assertNotIn(player_id, restored.exhausted)
        self.assertNotIn(player_id, restored.exhaustion)

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
        offense = fielded(match, PlayerRole.FULLBACK)
        defense = fielded(match, PlayerRole.FULLBACK, TeamSide.VISITING)
        match.begin_loose_ball(2)
        match.choose_loose_ball_offense_player(offense)
        match.choose_loose_ball_defense_player(defense)

        with self.assertRaises(ValueError):
            match.choose_loose_ball_offense_player(
                fielded(match, PlayerRole.DEFENDER),
            )
        with self.assertRaises(ValueError):
            match.choose_loose_ball_defense_player(
                fielded(match, PlayerRole.MIDFIELDER, TeamSide.VISITING),
            )

        restored = MatchState.from_dict(match.to_dict(), self.rules)
        self.assertTrue(restored.pending_loose_ball)
        self.assertEqual(restored.pending_loose_ball_distance, 2)
        self.assertEqual(
            restored.loose_ball_offense_player, offense,
        )
        self.assertEqual(
            restored.loose_ball_defense_player, defense,
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
            self.assertEqual(image.size, (3300, 1953))

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
        # Four real names, for a representative set of lengths.
        names = [
            player.name
            for player in load_player_catalog().teams[Team.ORANGE].players[:4]
        ]

        single_font, _ = fit_meeple_labels(draw, names[:1], 400, 300)
        stacked_font, line_height = fit_meeple_labels(draw, names, 400, 90)

        self.assertLess(stacked_font.size, single_font.size)
        self.assertLessEqual(len(names) * line_height, 90)
        for name in names:
            self.assertLessEqual(
                draw.textlength(name, font=stacked_font), 400,
            )

    def test_a_meeple_carries_its_species_over_its_role(self) -> None:
        # The disc holds two things now, the species icon over the role
        # initials, and both have to fit inside it -- the icon in the
        # top, the initials clear of the icon and of the disc's foot.
        # The suite cannot see the image, so this checks the geometry.
        for species in SPECIES_ORDER:
            self.assertIsNotNone(
                species_icon(species, "#000000", MEEPLE_SPECIES_ICON_SIZE),
                species,
            )
        icon_bottom = MEEPLE_SPECIES_ICON_TOP + MEEPLE_SPECIES_ICON_SIZE
        initials_top = MEEPLE_SIZE - MEEPLE_ROLE_BOTTOM_INSET
        self.assertLessEqual(icon_bottom, initials_top)
        self.assertLess(initials_top + FONT_TOKEN_ROLE.size, MEEPLE_SIZE)

        # And a bigger disc must still leave each row a line of names:
        # the visiting names stop above the home tokens, the home names
        # at the board's foot.
        line = MEEPLE_LABEL_MIN_SIZE + 3
        self.assertGreaterEqual(
            (HOME_MEEPLE_TOP - 5) - (VISITING_MEEPLE_TOP + MEEPLE_SIZE + 7),
            2 * line,
        )
        self.assertGreaterEqual(
            (BOARD_BOTTOM - 16) - (HOME_MEEPLE_TOP + MEEPLE_SIZE + 7),
            2 * line,
        )

    def test_the_species_icon_is_drawn_only_when_asked_for(self) -> None:
        # The icon is a fact of an advanced game playing species
        # abilities; a basic game's meeple is the initials alone,
        # sized to fill the disc (the author, 2026-09-18). The cog
        # answers the flag from RulesEngine.species_abilities_apply --
        # the renderer never reads the game's own bools.
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.TEAL,
        )
        player = self.catalog.player_by_id(
            fielded(match, PlayerRole.FULLBACK)
        )
        for species_icons, composites, font in (
            (True, 1, FONT_TOKEN_ROLE),
            (False, 0, FONT_TOKEN_SOLO),
        ):
            canvas = mock.MagicMock(spec=Image.Image)
            draw = mock.MagicMock(spec=ImageDraw.ImageDraw)
            draw.textlength.return_value = 20
            draw.textbbox.return_value = (0, 0, 20, 20)
            draw_meeple_face(
                canvas, draw, player, 0, 0, "#000000",
                species_icons=species_icons,
            )
            self.assertEqual(canvas.alpha_composite.call_count, composites)
            self.assertIs(draw.text.call_args.kwargs["font"], font)

        # And every render entry point takes the flag, defaulting to
        # the basic look, so a caller that forgets it draws a basic
        # game rather than an advanced one.
        for renderer in (
            render_match_image, render_field_image, render_coaching_image,
        ):
            parameter = inspect.signature(renderer).parameters["species_icons"]
            self.assertIs(parameter.default, False, renderer.__name__)

    def test_every_cog_render_asks_the_engine_whether_to_draw_species(
        self,
    ) -> None:
        # The default is the basic look, so a render site that forgets
        # the flag draws every advanced game without its species -- and
        # nothing else in the suite can see that. Each call of the three
        # renderers in the cog has to pass the engine's own answer.
        renderers = (
            "render_match_image", "render_field_image",
            "render_coaching_image",
        )
        expected = "species_icons=self.engine.species_abilities_apply(game)"
        seen = 0
        for path in Path("cogs").glob("**/*.py"):
            source = path.read_text()
            for renderer in renderers:
                for index in [
                    m.end() for m in re.finditer(
                        rf"to_thread\(\s*{renderer},", source,
                    )
                ]:
                    # Up to the call's own closing paren, which sits
                    # on a line of its own at the call's indent.
                    call = source[index:source.index("\n        )", index)]
                    self.assertIn(
                        expected, call,
                        f"{path}: {renderer} is called without the flag",
                    )
                    seen += 1
        self.assertEqual(seen, 3)

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


class TeamPairsTests(unittest.TestCase):
    """
    TEAM_PAIRS/paired_team and the two four-tuples they're built from
    -- the plumbing every mutual-exclusion and legacy-migration check
    reads. See "Team colors" in docs/design/teams-and-players.md.
    """

    def test_every_team_is_in_exactly_one_axis(self) -> None:
        self.assertEqual(set(COLOR_TEAMS) | set(SPECIES_TEAMS), set(Team))
        self.assertEqual(set(COLOR_TEAMS) & set(SPECIES_TEAMS), set())
        self.assertEqual(len(COLOR_TEAMS), 4)
        self.assertEqual(len(SPECIES_TEAMS), 4)

    def test_pairing_is_a_involution_across_the_axes(self) -> None:
        # Every team has a pair, the pair is on the other axis, no
        # team pairs with itself, and pairing twice returns the start
        # -- an involution, not merely a function.
        self.assertEqual(set(TEAM_PAIRS), set(Team))
        for team in Team:
            pair = paired_team(team)
            self.assertNotEqual(pair, team)
            self.assertEqual(paired_team(pair), team)
            self.assertNotEqual(
                team in COLOR_TEAMS, pair in COLOR_TEAMS,
                f"{team.value} and its pair {pair.value} are on the "
                "same axis.",
            )

    def test_the_shipped_pairing_matches_the_reshuffle(self) -> None:
        # The four pairings are the author's call (which color a
        # species used to be fielded under, exclusively, before the
        # reshuffle) and not derivable from anything else -- so this
        # is pinned rather than only checked for shape.
        self.assertEqual(paired_team(Team.ORANGE), Team.FIRE_DEMONS)
        self.assertEqual(paired_team(Team.TEAL), Team.CYBORGS)
        self.assertEqual(paired_team(Team.PURPLE), Team.TELEKINETICS)
        self.assertEqual(paired_team(Team.SLIME), Team.OOZES)


class DuplicateCardTests(unittest.TestCase):
    """
    One player, both sides -- `shared_player_ids`, the card-id scheme
    that keeps the two copies apart, and a match built on top of them.
    See "One player, both sides" in docs/design/teams-and-players.md.
    """

    def setUp(self) -> None:
        self.catalog = load_player_catalog()
        self.ruleset = load_basic_ruleset()

    def roster(self, team: Team) -> set:
        return {
            player.player_id
            for player in self.catalog.teams[team].players
        }

    def test_a_color_team_overlaps_every_species_team(self) -> None:
        # 3 of its own species plus 2 of each other. The pairing is the
        # largest of four overlaps, not the only one -- which is why
        # the picker's pair rule is about the color and cannot be read
        # as "the teams that share players".
        for team in COLOR_TEAMS:
            with self.subTest(team=team.value):
                for species in SPECIES_TEAMS:
                    shared = self.catalog.shared_player_ids(team, species)
                    self.assertEqual(
                        len(shared),
                        3 if species == paired_team(team) else 2,
                    )

    def test_teams_on_one_axis_share_nobody(self) -> None:
        for axis in (COLOR_TEAMS, SPECIES_TEAMS):
            for first, second in itertools.combinations(axis, 2):
                with self.subTest(first=first.value, second=second.value):
                    self.assertFalse(
                        self.catalog.shared_player_ids(first, second)
                    )

    def test_a_card_id_round_trips_to_its_player(self) -> None:
        for player_id in self.roster(Team.ORANGE):
            with self.subTest(player=player_id):
                duplicate = duplicate_card_id(player_id)
                self.assertNotEqual(duplicate, player_id)
                self.assertEqual(catalog_player_id(duplicate), player_id)
                # An ordinary id is its own catalog id, so nothing has
                # to know which kind it is holding.
                self.assertEqual(catalog_player_id(player_id), player_id)
                # Same person, looked up under the card's own id --
                # which is what keeps team_for_player(player.player_id)
                # answering for the right side at the ~90 call sites
                # that read an id back off a definition.
                copy = self.catalog.player_by_id(duplicate)
                original = self.catalog.player_by_id(player_id)
                self.assertEqual(copy.player_id, duplicate)
                self.assertEqual(original.player_id, player_id)
                self.assertEqual(copy.name, original.name)
                self.assertEqual(copy.role, original.role)
                self.assertEqual(
                    self.catalog.effective_profile(copy),
                    self.catalog.effective_profile(original),
                )

    def test_no_real_player_id_carries_the_suffix(self) -> None:
        # The scheme rests on this: a suffix that a real id could end
        # with would make catalog_player_id lossy.
        for team in Team:
            for player_id in self.roster(team):
                self.assertFalse(player_id.endswith(DUPLICATE_CARD_SUFFIX))

    def test_an_overlapping_match_fields_both_copies(self) -> None:
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.ruleset,
            board_size=7,
            home_team=Team.PURPLE,
            visiting_team=Team.FIRE_DEMONS,
        )
        shared = self.catalog.shared_player_ids(
            Team.PURPLE, Team.FIRE_DEMONS,
        )
        self.assertTrue(shared)

        home_cards = (
            match.home.field_players + match.home.team_board.bench
        )
        visiting_cards = (
            match.visiting.field_players + match.visiting.team_board.bench
        )
        # Home keeps the catalog ids; the visiting copies carry the
        # suffix, so no card is on both sides even though the people
        # are.
        self.assertFalse(set(home_cards) & set(visiting_cards))
        self.assertEqual(
            {
                catalog_player_id(card)
                for card in visiting_cards
                if card != catalog_player_id(card)
            },
            shared,
        )
        for player_id in shared:
            with self.subTest(player=player_id):
                self.assertIn(player_id, home_cards)
                self.assertIn(duplicate_card_id(player_id), visiting_cards)

    def test_a_duplicate_is_read_as_the_side_it_is_on(self) -> None:
        # The whole point of the two ids: everything downstream asks
        # the match who a card plays for, and gets a different answer
        # for each copy.
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.ruleset,
            board_size=7,
            home_team=Team.PURPLE,
            visiting_team=Team.FIRE_DEMONS,
        )
        for player_id in self.catalog.shared_player_ids(
            Team.PURPLE, Team.FIRE_DEMONS,
        ):
            with self.subTest(player=player_id):
                self.assertEqual(
                    match.team_for_player(player_id), Team.PURPLE,
                )
                self.assertEqual(
                    match.team_for_player(duplicate_card_id(player_id)),
                    Team.FIRE_DEMONS,
                )
                # And the round trip a message actually makes: card id
                # -> definition -> back to the id -> which side.
                for card_id, expected in (
                    (player_id, Team.PURPLE),
                    (duplicate_card_id(player_id), Team.FIRE_DEMONS),
                ):
                    player = self.catalog.player_by_id(card_id)
                    self.assertEqual(
                        match.team_for_player(player.player_id), expected,
                    )

    def test_the_two_copies_carry_their_own_condition(self) -> None:
        # A card, not a person: exhausting or injuring one copy must
        # not touch the other, which is what keeping the ids distinct
        # buys and the reason a shared card was never an option.
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.ruleset,
            board_size=7,
            home_team=Team.PURPLE,
            visiting_team=Team.FIRE_DEMONS,
        )
        shared = sorted(
            self.catalog.shared_player_ids(Team.PURPLE, Team.FIRE_DEMONS)
        )
        player_id = next(
            candidate for candidate in shared
            if candidate in match.home.field_players
            and duplicate_card_id(candidate)
            in match.visiting.field_players
        )
        duplicate = duplicate_card_id(player_id)

        match.injured.add(player_id)
        match.exhaustion[player_id] = 3
        self.assertNotIn(duplicate, match.injured)
        self.assertEqual(match.exhaustion.get(duplicate, 0), 0)

    def test_an_overlapping_match_survives_a_round_trip(self) -> None:
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.ruleset,
            board_size=7,
            home_team=Team.SLIME,
            visiting_team=Team.CYBORGS,
        )
        reloaded = MatchState.from_dict(
            json.loads(json.dumps(match.to_dict())),
            self.ruleset,
        )
        reloaded.validate(self.catalog)
        self.assertEqual(
            reloaded.visiting.field_players, match.visiting.field_players,
        )
        self.assertEqual(
            reloaded.board.spaces, match.board.spaces,
        )

    def test_every_offered_matchup_renders(self) -> None:
        # player_index keys the render by card id, so a duplicate that
        # was not aliased there would KeyError on the first board --
        # after the game had started.
        players = player_index(self.catalog)
        for first in Team:
            for second in Team:
                if second in (first, paired_team(first)):
                    continue
                match = MatchState.standard(
                    catalog=self.catalog,
                    ruleset=self.ruleset,
                    board_size=7,
                    home_team=first,
                    visiting_team=second,
                )
                with self.subTest(home=first.value, visiting=second.value):
                    for setup in (match.home, match.visiting):
                        for card in (
                            setup.field_players
                            + setup.team_board.bench
                        ):
                            self.assertIn(card, players)


class TeamDisplayNameTests(unittest.TestCase):
    """
    team_display_name -- the fix for team.value.title() silently
    mangling an underscored team ("fire_demons".title() ==
    "Fire_Demons"). See "Team colors" in docs/design/teams-and-players.md.
    """

    def test_a_single_word_team_reads_the_same_as_title(self) -> None:
        self.assertEqual(team_display_name(Team.ORANGE), "Orange")
        self.assertEqual(team_display_name(Team.TEAL), "Teal")

    def test_an_underscored_team_gets_a_space_not_an_underscore(self) -> None:
        self.assertEqual(team_display_name(Team.FIRE_DEMONS), "Fire Demons")
        self.assertEqual(team_display_name(Team.TELEKINETICS), "Telekinetics")
        # The literal bug this replaced, so a regression here is loud
        # rather than merely "wrong-looking in Discord".
        self.assertNotEqual(
            team_display_name(Team.FIRE_DEMONS),
            Team.FIRE_DEMONS.value.title(),
        )


class TeamForPlayerTests(unittest.TestCase):
    """
    MatchState.team_for_player -- the one reading of "which of a
    player's two rosters is this match fielding them as", now that
    PlayerDefinition carries no team of its own. See "Team colors" and
    "Team colors" in docs/design/teams-and-players.md.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    def build_match(self) -> MatchState:
        return MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.TEAL,
        )

    def test_a_fielded_player_resolves_to_their_side(self) -> None:
        match = self.build_match()

        for player_id in match.home.field_players:
            with self.subTest(player_id=player_id):
                self.assertEqual(
                    match.team_for_player(player_id), Team.ORANGE,
                )
        for player_id in match.visiting.field_players:
            with self.subTest(player_id=player_id):
                self.assertEqual(
                    match.team_for_player(player_id), Team.TEAL,
                )

    def test_a_benched_player_still_resolves(self) -> None:
        match = self.build_match()

        for player_id in match.home.team_board.bench:
            with self.subTest(player_id=player_id):
                self.assertEqual(
                    match.team_for_player(player_id), Team.ORANGE,
                )

    def test_a_player_on_neither_side_is_a_clear_error(self) -> None:
        match = self.build_match()

        with self.assertRaises(ValueError):
            match.team_for_player("not_a_real_player_id")


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
        match.board.remove_meeple(fielded(match, PlayerRole.WINGER))
        match.board.remove_meeple(
            fielded(match, PlayerRole.DEFENDER, TeamSide.VISITING),
        )
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

    def test_crowded_candidates_offers_a_same_zone_double_up(self) -> None:
        # Both of them, not a pick between them: which of two players
        # sharing a space runs back is the coach's call (2026-08-17).
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
        self.assertEqual(
            sorted(match.crowded_candidates(TeamSide.HOME)),
            sorted([home_midfielder, other_home_midfielder]),
        )

    def test_crowded_candidates_leave_the_ball_holder_out(self) -> None:
        # The player holding the ball never runs back, so a pair with
        # the ball between them is one candidate and no question.
        match = self.build_match(7)
        home_midfielder, other_home_midfielder = match.home.zones[
            Zone.MIDFIELD
        ][:2]
        other_position = match.board.meeple_position(other_home_midfielder)
        match.move_meeple(home_midfielder, *other_position)

        match.pending_run_back_stays_player_id = other_home_midfielder
        self.assertEqual(
            match.crowded_candidates(TeamSide.HOME), [home_midfielder]
        )

    def test_crowded_candidates_caps_at_the_zone_s_open_spaces(self) -> None:
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
        self.assertEqual(match.crowded_candidates(TeamSide.HOME), [])

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

    def test_each_side_has_three_maneuvers_per_tier(self) -> None:
        for side in ("offense", "defense"):
            with self.subTest(side=side):
                self.assertEqual(len(self.catalog.side(side)), 6)
                for tier in (MANEUVER_TIER_BASIC, MANEUVER_TIER_ADVANCED):
                    self.assertEqual(
                        sorted(
                            m.rank
                            for m in self.catalog.for_tier(side, tier)
                        ),
                        [1, 2, 3],
                    )

    def test_every_card_is_paired_with_its_counterpart_by_rank(self) -> None:
        """
        The pairing is what "a skill test resolves it as the basic
        card" is read off, and what the shared back's nodes carry. It
        has to be an involution: a card's counterpart's counterpart is
        the card itself, on the same side and rank.
        """
        for maneuver in self.catalog.offense + self.catalog.defense:
            with self.subTest(maneuver=maneuver.key):
                other = self.catalog.counterpart(maneuver)
                self.assertNotEqual(other.tier, maneuver.tier)
                self.assertEqual(other.rank, maneuver.rank)
                self.assertEqual(
                    self.catalog.counterpart(other).key, maneuver.key
                )

    def test_die_faces_cover_one_through_six_with_no_overlap(self) -> None:
        # The die is off the rules (2026-08-17) but the data and
        # DinkyAI still carry it -- see "The printed boards". Only the
        # basic rows have to cover the six: an advanced card sits on
        # its counterpart's rank and reuses its faces, which is why the
        # importer stopped validating them for uniqueness.
        for side in ("offense", "defense"):
            faces = [
                value
                for maneuver in self.catalog.for_tier(
                    side, MANEUVER_TIER_BASIC,
                )
                for value in maneuver.die_values
            ]
            self.assertEqual(sorted(faces), list(range(1, 7)))

    def test_matchup_triangle_resolves_as_expected(self) -> None:
        expected = {
            ("low_pass", "deflect"): "tie",
            ("low_pass", "steal"): "defense",
            ("low_pass", "pressure"): "offense",
            ("dribble_advance", "deflect"): "offense",
            ("dribble_advance", "steal"): "tie",
            ("dribble_advance", "pressure"): "defense",
            ("high_pass", "deflect"): "defense",
            ("high_pass", "steal"): "offense",
            ("high_pass", "pressure"): "tie",
        }
        for (offense_key, defense_key), outcome in expected.items():
            self.assertEqual(
                self.catalog.resolve(offense_key, defense_key),
                outcome,
                f"{offense_key} vs {defense_key}",
            )

    def test_an_advanced_card_resolves_exactly_as_its_counterpart(
        self,
    ) -> None:
        """
        **Advanced mode adds no new way to win a maneuver** -- the
        author, 2026-08-18: "Rank alone decides." So the 6x6 grid is
        the basic 3x3 cycle repeated four times, and swapping either
        card for its counterpart cannot change the outcome. Asserted
        over the whole grid rather than the nine advanced-on-advanced
        cells, because it is the *mixed* pairings a rank-blind
        resolution would get wrong.
        """
        for offense in self.catalog.offense:
            for defense in self.catalog.defense:
                with self.subTest(pair=(offense.key, defense.key)):
                    self.assertEqual(
                        self.catalog.resolve(offense.key, defense.key),
                        self.catalog.resolve(
                            self.catalog.counterpart(offense).key,
                            self.catalog.counterpart(defense).key,
                        ),
                    )

    def test_reference_image_renders_as_png(self) -> None:
        image_data = render_maneuver_reference_image(self.catalog)

        with Image.open(image_data) as image:
            self.assertEqual(image.format, "PNG")

    def test_an_advanced_hand_is_a_row_a_tier(self) -> None:
        """
        The basic three above their advanced counterparts, three
        columns wide either way, so every advanced card sits under the
        basic card it shares a rank with (the author). The suite cannot
        see the picture, so the claim is checked as the shape of the
        canvas: three columns and two card rows, where a hand wrapped
        at `HAND_MAX_COLUMNS` would be four columns and a ragged
        second row -- which is the layout this replaced.

        A basic hand is the other half of the same reading: one row,
        and four columns because the shared back is on the end of it.
        """
        players = load_player_catalog()
        scale = HAND_CARD_WIDTH / CARD_WIDTH
        card_height = round(CARD_HEIGHT * scale)
        band = HAND_HEADING_SIZE + HAND_HEADING_GAP

        def width(columns: int) -> int:
            return (
                HAND_MARGIN * 2
                + HAND_CARD_WIDTH * columns
                + HAND_GAP * (columns - 1)
            )

        def height(card_rows: int) -> int:
            return (
                HAND_MARGIN * 2
                + card_height * card_rows
                + HAND_GAP * (card_rows - 1)
                + band
            )

        # tiers, columns, card rows -- one side, so one caption band.
        cases = (
            ((MANEUVER_TIER_BASIC,), 4, 1),
            ((MANEUVER_TIER_BASIC, MANEUVER_TIER_ADVANCED), 3, 2),
        )
        for side in ("offense", "defense"):
            for tiers, columns, card_rows in cases:
                with self.subTest(side=side, tiers=tiers):
                    hand = render_maneuver_hands(
                        self.catalog, players, (side,), tiers,
                    )
                    with Image.open(hand) as image:
                        self.assertEqual(image.format, "PNG")
                        self.assertEqual(image.width, width(columns))
                        self.assertEqual(image.height, height(card_rows))

    def test_only_a_lone_basic_hand_carries_the_back(self) -> None:
        """
        Both basic hands together are the whole game -- all six cards,
        each carrying its own beats/ties/loses row -- so the back's
        hexagon is those same six relations drawn a second time, for
        the width of a card (the author). An advanced hand drops it for
        a second reason: it is what lets the two tiers line up three
        columns wide instead of being squeezed to fit a fourth.

        So the back belongs to a lone basic hand and nothing else --
        half a cycle, and the one hand that cannot read the relations
        off the cards in front of it. Checked as a width rather than a
        card count: a back creeping back in is a column, and a column
        is what makes every card on the image smaller.
        """
        players = load_player_catalog()

        def width(columns: int) -> int:
            return (
                HAND_MARGIN * 2
                + HAND_CARD_WIDTH * columns
                + HAND_GAP * (columns - 1)
            )

        both = ("offense", "defense")
        advanced = (MANEUVER_TIER_BASIC, MANEUVER_TIER_ADVANCED)
        cases = (
            # sides, tiers, columns -- the widest row of the image
            (both, (MANEUVER_TIER_BASIC,), 3),
            (both, advanced, 3),
            (("offense",), advanced, 3),
            (("offense",), (MANEUVER_TIER_BASIC,), 4),
        )
        for sides, tiers, columns in cases:
            with self.subTest(sides=sides, tiers=tiers):
                hand = render_maneuver_hands(
                    self.catalog, players, sides, tiers,
                )
                with Image.open(hand) as image:
                    self.assertEqual(image.width, width(columns))

    def test_each_side_block_reserves_a_caption_band(self) -> None:
        """
        Each side's rows are captioned ("OFFENSE HAND" / "DEFENSE
        HAND") so a coach finds their own row before reading a card.
        The suite cannot read the words, but every captioned block adds
        a fixed band above its first row, so the image is exactly that
        much taller than the same cards laid out with no captions --
        one band per side, and none for the lone shared back.
        """
        players = load_player_catalog()
        scale = HAND_CARD_WIDTH / CARD_WIDTH
        card_height = round(CARD_HEIGHT * scale)
        band = HAND_HEADING_SIZE + HAND_HEADING_GAP

        def bare_height(card_rows: int) -> int:
            return (
                HAND_MARGIN * 2
                + card_height * card_rows
                + HAND_GAP * (card_rows - 1)
            )

        # sides, tiers, total card rows across the image
        cases = (
            (("offense",), (MANEUVER_TIER_BASIC,), 1),
            (("offense", "defense"), (MANEUVER_TIER_BASIC,), 2),
            (
                ("offense", "defense"),
                (MANEUVER_TIER_BASIC, MANEUVER_TIER_ADVANCED),
                4,
            ),
        )
        for sides, tiers, card_rows in cases:
            with self.subTest(sides=sides, tiers=tiers):
                hand = render_maneuver_hands(
                    self.catalog, players, sides, tiers,
                )
                with Image.open(hand) as image:
                    self.assertEqual(
                        image.height,
                        bare_height(card_rows) + band * len(sides),
                    )

    def test_the_back_joins_every_pair_that_ties(self) -> None:
        """
        The dashed lines on the back are the ties, and they are asked
        of the catalog rather than paired by rank -- so a re-cut cycle
        moves the lines instead of leaving them pointing at the wrong
        maneuvers. Three pairs, each a genuine tie, and every maneuver
        in exactly one.
        """
        # Six nodes, so three lines: an advanced card ties exactly what
        # its basic counterpart ties, and drawing all twelve would put
        # the same three diagonals down four times over.
        basic = self.catalog.for_tier(
            "offense", MANEUVER_TIER_BASIC,
        ) + self.catalog.for_tier("defense", MANEUVER_TIER_BASIC)
        pairs = tie_pairs(self.catalog)
        self.assertEqual(len(pairs), 3)
        for offense, defense in pairs:
            with self.subTest(pair=(offense.key, defense.key)):
                self.assertEqual(
                    self.catalog.resolve(offense.key, defense.key), "tie"
                )
        named = [maneuver.key for pair in pairs for maneuver in pair]
        self.assertEqual(
            sorted(named), sorted(maneuver.key for maneuver in basic)
        )

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
                        cards[index].width + SHEET_MARGIN_X * 2,
                        cards[index].height + SHEET_MARGIN_Y * 2,
                    ),
                )

    def test_a_print_sheet_fits_a_letter_page_across(self) -> None:
        """
        Four poker cards across is 10in of card, and a letter page
        turned landscape has about 10.5in of printable width -- so the
        gutter is the whole of what decides whether a sheet printed at
        100% keeps its outside columns or loses them. Nothing about
        the image says how wide it is meant to be, so the arithmetic
        is asserted rather than looked at.
        """
        card = Image.new("RGB", (CARD_WIDTH, CARD_HEIGHT), "white")
        sheet = print_sheet([card] * SHEET_COLUMNS)
        # The cards are drawn at 300dpi, and a letter page turned
        # landscape is 11in less the quarter-inch a printer cannot
        # reach on each side.
        self.assertLessEqual(sheet.width / 300, 11.0 - 0.25 * 2)

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
            maneuver.key: {
                label
                for label, _ in role_abilities(players, maneuver, self.catalog)
            }
            for maneuver in self.catalog.offense + self.catalog.defense
        }

        self.assertEqual(by_maneuver["low_pass"], {"MIDFIELDER", "WINGER"})
        self.assertEqual(by_maneuver["dribble_advance"], {"PLAYMAKER"})
        self.assertEqual(by_maneuver["high_pass"], {"FULLBACK", "STRIKER"})
        self.assertEqual(by_maneuver["deflect"], {"FULLBACK"})
        self.assertEqual(by_maneuver["steal"], {"BALL SPEED"})
        self.assertEqual(by_maneuver["pressure"], {"DEFENDER", "MIDFIELDER"})

        # **No role ability names an advanced maneuver**, which is the
        # data being honest rather than a gap: advanced mode's other
        # half is a unique ability per player and the sheet's column
        # for it is empty for all thirty-six. What every advanced card
        # does carry is the skill-test line, and Intercept carries the
        # ball speed modifier its rank has always carried.
        self.assertEqual(by_maneuver["skilled_pass"], {"CARDS"})
        self.assertEqual(by_maneuver["double_team"], {"CARDS"})
        self.assertEqual(by_maneuver["intercept"], {"BALL SPEED", "CARDS"})

        # **Three abilities reach a card their sentence does not name**
        # (the author, 2026-08-19), so they cannot be matched and are
        # placed by hand. The card says what the ability does *there*:
        # the Fullback's +1 distance, the Playmaker's token off.
        self.assertEqual(by_maneuver["clear"], {"FULLBACK", "CARDS"})
        self.assertEqual(by_maneuver["setup_pass"], {"FULLBACK", "CARDS"})
        self.assertEqual(by_maneuver["dribble_burst"], {"PLAYMAKER", "CARDS"})

    def reference_skill_test_height(self) -> int:
        """A two-detail-line skill test, the size the others match."""
        image_data = render_skill_test_dice(
            [
                (
                    7,
                    TEAM_COLORS[Team.ORANGE],
                    "Orange",
                    ["Defender A (Fullback)", "Defense 3"],
                    10,
                    False,
                    [],
                ),
                (
                    4,
                    TEAM_COLORS[Team.TEAL],
                    "Teal",
                    ["Shooter (Winger)", "Offense 2"],
                    6,
                    False,
                    [],
                ),
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

        image_data = render_own_goal_dice(
            [7, 12], TEAM_COLORS[Team.ORANGE], safe=True,
        )

        with Image.open(image_data) as image:
            self.assertEqual(image.format, "PNG")
            self.assertLessEqual(
                image.height, self.reference_skill_test_height(),
            )

    def test_injury_test_die_is_no_bigger_than_a_skill_test_die(self) -> None:
        # The whole point of the injury-test render is that it draws a
        # small die with context beside it.
        image_data = render_injury_test_die(
            5, TEAM_COLORS[Team.TEAL], "Teal", "Defender A", safe=True,
        )

        with Image.open(image_data) as image:
            self.assertEqual(image.format, "PNG")
            self.assertLessEqual(
                image.height, self.reference_skill_test_height(),
            )

    def test_a_mind_pull_die_is_wider_than_the_die_it_draws(self) -> None:
        # The aura is drawn larger than the polygon, so the die column
        # has to be sized to the halo -- measured rather than looked
        # at, since nothing in the suite can see the image.
        image_data = render_mind_pull_die(
            2, TEAM_COLORS[Team.TEAL], "Teal", "Defender A", pulled=True,
        )

        with Image.open(image_data) as image:
            self.assertEqual(image.format, "PNG")
            self.assertGreater(image.height, MIND_PULL_DIE_RADIUS * 2)
            self.assertGreater(image.width, image.height)

    def test_a_mind_pull_die_says_what_it_was_chasing(self) -> None:
        # Read off the rule, so a face added upstream reaches the image
        # with the roll rather than leaving the caption behind.
        self.assertEqual(mind_pull_target_label(), "pulls on 11-12")

    def test_a_volatile_die_is_wider_than_the_die_it_draws(self) -> None:
        # The flame, like the Mind Pull spiral, is drawn larger than
        # the polygon, so the die column is sized to the halo --
        # measured rather than looked at, since nothing in the suite
        # can see the image.
        image_data = render_volatile_die(
            9, 6, TEAM_COLORS[Team.ORANGE], "Orange", "Defender A",
            surge=True, modifier=9,
        )

        with Image.open(image_data) as image:
            self.assertEqual(image.format, "PNG")
            self.assertGreater(image.height, VOLATILE_DIE_RADIUS * 2)
            self.assertGreater(image.width, image.height)

    def test_the_portrait_is_what_sets_a_volatile_die_s_row(self) -> None:
        # The author's call (2026-09-16): this image has room the
        # injury test does not, because its explainer is wider than
        # any row of three columns -- so the portrait is the tallest
        # thing in the row and the flame sits inside it, rather than a
        # 96px picture marooned in a band of black under a wide
        # sentence. (The Mind Pull die reaches the same 168 by a
        # different road: its own halo, not an explainer, is what
        # already reserves the height.) Both halves are asserted
        # because the way they come undone is somebody making this
        # image consistent with the one it borrows its layout from.
        self.assertGreater(VOLATILE_PORTRAIT_SIZE, INJURY_TEST_PORTRAIT_SIZE)
        self.assertLess(VOLATILE_HALO_SCALE, MIND_PULL_HALO_SCALE)
        # The flame fills that row and does not grow it: the ceiling is
        # the portrait, and the scale is deliberately just under it --
        # a flame smaller than this reads as a smudge behind the die
        # and one larger is what makes the canvas taller than its own
        # content.
        halo_size = 2 * VOLATILE_DIE_RADIUS * VOLATILE_HALO_SCALE
        self.assertGreater(VOLATILE_PORTRAIT_SIZE, halo_size)
        self.assertGreater(halo_size, VOLATILE_PORTRAIT_SIZE * 0.9)

        image_data = render_volatile_die(
            9, 6, TEAM_COLORS[Team.ORANGE], "Orange", "Defender A",
            surge=True, modifier=9,
        )

        with Image.open(image_data) as image:
            self.assertGreater(image.height, VOLATILE_PORTRAIT_SIZE)

    def test_a_volatile_die_draws_a_backfire_too(self) -> None:
        # The other half of the ability, and the one a coach is most
        # likely to want explaining.
        image_data = render_volatile_die(
            3, 7, TEAM_COLORS[Team.TEAL], "Teal", "Defender A",
            surge=False, modifier=-3,
        )

        with Image.open(image_data) as image:
            self.assertEqual(image.format, "PNG")

    def test_a_volatile_die_explains_the_rule_it_is_chasing(self) -> None:
        # Read off VOLATILE_IGNITE_FACES and VOLATILE_SURGE_MINIMUM,
        # so a number settled upstream reaches the image with the roll
        # rather than leaving the caption behind -- the same claim
        # mind_pull_target_label answers.
        self.assertEqual(
            volatile_explainer_label(),
            "a natural 6 or 7 ignites \u2014 the second d12 adds on 5-12, "
            "subtracts on 1-4",
        )

    def test_the_explainer_is_what_sizes_a_volatile_die(self) -> None:
        # It is the widest thing on the image and the half a coach
        # meeting their first ignite actually needs, so the canvas is
        # sized to it rather than the sentence cut to the row.
        image_data = render_volatile_die(
            9, 6, TEAM_COLORS[Team.ORANGE], "Orange", "Defender A",
            surge=True, modifier=9,
        )

        measure = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        explainer = volatile_explainer_label()
        with Image.open(image_data) as image:
            self.assertGreater(
                image.width,
                measure.textlength(explainer, font=FONT_SMALL),
            )

    def test_a_player_portrait_renders_on_its_own(self) -> None:
        # Any player will do -- every one of them has art, which
        # test_every_player_has_a_portrait_image is the check on.
        somebody = load_player_catalog().teams[Team.TEAL].players[0]

        image_data = render_player_portrait(somebody.name)

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
        cog.basic_ruleset = self.rules
        cog.engine = RulesEngine(
            cog.player_catalog,
            cog.basic_ruleset,
            load_maneuver_catalog(),
            {},
        )
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

        with suppressed_cog_saves():
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

        with suppressed_cog_saves():
            detoured = await cog.check_for_loose_ball(
                interaction, game, match, distance_moved=2, lead_in="Lead-in.",
            )

        self.assertTrue(detoured)
        cog.begin_loose_ball.assert_awaited_once_with(
            interaction, game, match, 2, lead_in="Lead-in.",
        )
        cog.begin_run_back.assert_not_awaited()

    async def test_opposing_player_alone_on_the_space_is_contested(
        self,
    ) -> None:
        """
        This used to be a clean steal -- no movement, no roll, the ball
        simply theirs. Since 2026-08-18 it is a loose ball like any
        other: the defender standing there contests for nothing, and the
        side that lost the ball may send somebody after it. See "The
        loose ball" in docs/living-rules.md.
        """
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

        with suppressed_cog_saves():
            detoured = await cog.check_for_loose_ball(
                interaction, game, match, distance_moved=1,
                lead_in="Deflect happened.",
            )

        self.assertTrue(detoured)
        # Nothing is settled here any more: possession does not move
        # until somebody wins the contest.
        self.assertEqual(match.ball.possession, TeamSide.HOME)
        cog.begin_run_back.assert_not_awaited()
        cog.begin_loose_ball.assert_awaited_once_with(
            interaction, game, match, 1, lead_in="Deflect happened.",
        )


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
        cog.basic_ruleset = self.rules
        cog.engine = RulesEngine(
            cog.player_catalog,
            cog.basic_ruleset,
            load_maneuver_catalog(),
            {},
        )
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
            cog.engine.low_pass_candidates(match),
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
            cog.engine.low_pass_candidates(match),
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
        self.assertEqual(cog.engine.low_pass_candidates(match), [(1, ahead)])

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
        self.assertEqual(cog.engine.low_pass_candidates(match), [(0, sharing)])

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
        self.assertEqual(cog.engine.low_pass_candidates(match), [])

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
        self.assertEqual(cog.engine.low_pass_candidates(match), [(0, sharing)])

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

        self.assertEqual(cog.engine.low_pass_candidates(match), [(0, first)])
        self.assertEqual(
            cog.engine.low_pass_receivers(match, 0), [first, second],
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

        self.assertEqual(cog.engine.low_pass_receivers(match, 0), [sharing])

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

        self.assertEqual(cog.engine.low_pass_receivers(match, 0), [teammate])

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
        with suppressed_cog_saves():
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
        with suppressed_cog_saves():
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
        with suppressed_cog_saves():
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
        with suppressed_cog_saves():
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
        with suppressed_cog_saves():
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
        with suppressed_cog_saves():
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
        cog.engine.side_controlled_by_ai = mock.Mock(return_value=False)
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
        with suppressed_cog_saves():
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
        cog.engine.side_controlled_by_ai = mock.Mock(return_value=False)
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
        with suppressed_cog_saves():
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
        with suppressed_cog_saves():
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
        with suppressed_cog_saves():
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

        Since 2026-08-18 neither is forced by this call site: both are
        standing on the ball, which is the ordinary loose-ball rule, so
        the pools are read off the position. What this asserts is that
        they come out the same.

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
        with suppressed_cog_saves():
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
        self.assertTrue(kwargs["is_high_pass"])

        # begin_loose_ball is mocked, so raise the flag it would have
        # raised and ask the pools the real one asks.
        match.begin_loose_ball(3, is_high_pass=True)
        self.assertEqual(
            cog.engine.loose_ball_candidates(match, TeamSide.HOME),
            [receiver],
        )
        self.assertEqual(
            cog.engine.loose_ball_candidates(match, TeamSide.VISITING),
            [defender_on_space],
        )
        # Neither may be held back, and neither is asked for.
        self.assertFalse(match.may_decline_loose_ball(TeamSide.HOME))
        self.assertFalse(match.may_decline_loose_ball(TeamSide.VISITING))

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
        with suppressed_cog_saves():
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
        with suppressed_cog_saves():
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
        cog.engine.side_controlled_by_ai = mock.Mock(return_value=False)
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
            with suppressed_cog_saves():
                await cog.resolve_high_pass(interaction, game, match)

        self.assertEqual(cog.apply_high_pass.await_count, 2)
        for call in cog.apply_high_pass.await_args_list:
            self.assertEqual(call.args[-1], 2)
        cog.engine.side_controlled_by_ai.assert_not_called()

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
        self.assertEqual(cog.engine.high_pass_distance_options(match), [2, 3, 4])
        match.active_player_id = self.player_with_role(
            match, TeamSide.HOME, PlayerRole.DEFENDER,
        )
        self.assertEqual(cog.engine.high_pass_distance_options(match), [2, 3])

        match.set_ball_space(Zone.MIDFIELD, 2)  # flat 5, three of room
        match.active_player_id = self.player_with_role(
            match, TeamSide.HOME, PlayerRole.FULLBACK,
        )
        self.assertEqual(cog.engine.high_pass_distance_options(match), [2, 3])

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
        with suppressed_cog_saves():
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
        with suppressed_cog_saves():
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
        with suppressed_cog_saves():
            await cog.apply_high_pass(interaction, game, match, 4)

        self.assertEqual(
            (match.ball.zone, match.ball.space_index), (Zone.MIDFIELD, 1),
        )
        cog.begin_loose_ball.assert_awaited_once()
        _, kwargs = cog.begin_loose_ball.await_args
        self.assertIn("Fullback ability", kwargs["lead_in"])

    # -- Deflect's Fullback bonus ---------------------------------

    async def test_resolve_deflect_fullback_deflects_two_spaces(
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
        with suppressed_cog_saves():
            await cog.resolve_deflect(interaction, game, match)

        # HOME attacks left-to-right, so "back" is toward lower flat
        # indices: flat 4 - 2 = flat 2, HOME_GOAL space 2.
        self.assertEqual(
            (match.ball.zone, match.ball.space_index), (Zone.HOME_GOAL, 2),
        )
        # A Deflect knocks the ball out of possession, so it goes
        # straight to the contest rather than through the loose-ball
        # check on the end of an ordinary maneuver (2026-08-18).
        cog.finish_maneuver_resolution.assert_not_awaited()
        cog.begin_loose_ball.assert_awaited_once()
        args, kwargs = cog.begin_loose_ball.await_args
        # Its clock cost is a flat 1 whatever the deflection travelled.
        self.assertEqual(args[3], 1)
        self.assertIn("Fullback ability", kwargs["lead_in"])
        self.assertIn("2 spaces back", kwargs["lead_in"])


class D12BallFontTests(unittest.TestCase):
    """Guard the bundled fonts.

    A host without system fonts used to fall through to Pillow's built-in
    face, which is pinned to size 10 and ignores the requested size, so
    every label on the board rendered at the same tiny size.
    """

    def test_bundled_font_files_exist(self) -> None:
        for file_name in (
            "DejaVuSans.ttf",
            "DejaVuSans-Bold.ttf",
            "RacingSansOne-Regular.ttf",
        ):
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

    def test_load_goal_zone_font_honours_requested_size(self) -> None:
        for size in (40, 68, 90):
            with self.subTest(size=size):
                font = load_goal_zone_font(size)
                self.assertEqual(font.size, size)

    def test_load_goal_zone_font_uses_bundled_file_not_system_fonts(
        self,
    ) -> None:
        real_truetype = ImageFont.truetype

        def only_absolute_paths(font=None, size=10, *args, **kwargs):
            if isinstance(font, str) and not Path(font).is_absolute():
                raise OSError("cannot open resource")
            return real_truetype(font, size, *args, **kwargs)

        with mock.patch.object(
            ImageFont, "truetype", side_effect=only_absolute_paths
        ):
            font = load_goal_zone_font(68)

        self.assertEqual(font.size, 68)
        self.assertEqual(Path(font.path).name, "RacingSansOne-Regular.ttf")

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
        paths = [
            EXHAUST_ICON_PATH,
            EXHAUSTED_ICON_PATH,
            INJURED_ICON_PATH,
        ]
        # The species icons load the same silent way, and a missing one
        # is quieter still: a card simply comes out with no icon beside
        # the role initials, which reads as a design rather than as a
        # fault.
        paths.extend(
            SPECIES_ICON_DIR / f"{species}.png"
            for species in SPECIES_ORDER
        )

        for path in paths:
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


class MatchStateSerializationTests(unittest.TestCase):
    """
    That the save covers the match, and goes on covering it.

    A field added to MatchState and forgotten in to_dict or from_dict
    is invisible while the bot is up -- the live game is the one in
    memory -- and shows only as state quietly missing after a restart,
    which is the hardest kind of bug to trace back to its commit.
    """

    def setUp(self) -> None:
        self.rules = load_basic_ruleset()
        self.catalog = load_player_catalog()

    def match(self) -> MatchState:
        return MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.TEAL,
        )

    def test_every_field_is_either_tabled_or_deliberately_explicit(
        self,
    ) -> None:
        """
        The guard this table exists for. A new field has to be added
        to MATCH_SAVED_FIELDS, or -- when it needs a conversion or a
        legacy fallback the table cannot express -- written into
        to_dict and from_dict and named in MATCH_EXPLICIT_FIELDS.
        Doing neither fails here rather than in a game.
        """
        declared = {
            saved_field.name for saved_field in MATCH_SAVED_FIELDS
        } | MATCH_EXPLICIT_FIELDS
        actual = {
            match_field.name
            for match_field in dataclasses.fields(MatchState)
        }

        self.assertEqual(
            actual - declared,
            set(),
            "MatchState fields that are saved nowhere -- add them to "
            "MATCH_SAVED_FIELDS, or to to_dict/from_dict and "
            "MATCH_EXPLICIT_FIELDS.",
        )
        self.assertEqual(
            declared - actual,
            set(),
            "Saved names that are not MatchState fields any more.",
        )

    def test_the_table_and_the_explicit_set_do_not_overlap(self) -> None:
        # A field in both would be written twice, and the second
        # writer would silently win.
        self.assertEqual(
            {saved_field.name for saved_field in MATCH_SAVED_FIELDS}
            & MATCH_EXPLICIT_FIELDS,
            set(),
        )

    def test_every_tabled_field_reaches_the_save_and_comes_back(
        self,
    ) -> None:
        match = self.match()
        saved = match.to_dict()

        for saved_field in MATCH_SAVED_FIELDS:
            with self.subTest(field=saved_field.name):
                self.assertIn(saved_field.name, saved)

        restored = MatchState.from_dict(saved, self.rules)
        self.assertEqual(restored.to_dict(), saved)

    def test_a_save_predating_a_field_falls_back_rather_than_raising(
        self,
    ) -> None:
        """
        The ordinary case, not an error: both developers run the bot
        from their own tree against their own games, so a
        half-finished match routinely outlives the change that added a
        field to it.
        """
        saved = self.match().to_dict()
        for saved_field in MATCH_SAVED_FIELDS:
            with self.subTest(field=saved_field.name):
                without = {
                    key: value
                    for key, value in saved.items()
                    if key != saved_field.name
                }
                restored = MatchState.from_dict(without, self.rules)
                expected = (
                    saved_field.factory()
                    if saved_field.factory is not None
                    else saved_field.default
                )
                self.assertEqual(
                    getattr(restored, saved_field.name), expected,
                )

    def test_a_mutable_field_is_copied_in_both_directions(self) -> None:
        """
        A container written straight into the dict is one the live
        match can go on mutating between to_dict and the file being
        written; one read straight out is a match holding a reference
        into the loaded JSON.
        """
        match = self.match()
        match.pending_injury_tests = ["a", "b"]
        match.assigned_positions = {"a": ["midfield", 1]}
        match.shootout_orders = {"home": ["a"]}

        saved = match.to_dict()
        match.pending_injury_tests.append("c")
        match.assigned_positions["b"] = ["home_goal", 0]
        match.shootout_orders["home"].append("b")

        self.assertEqual(saved["pending_injury_tests"], ["a", "b"])
        self.assertEqual(saved["assigned_positions"], {"a": ["midfield", 1]})
        self.assertEqual(saved["shootout_orders"], {"home": ["a"]})

        restored = MatchState.from_dict(saved, self.rules)
        restored.pending_injury_tests.append("z")
        restored.assigned_positions["z"] = ["midfield", 0]
        restored.shootout_orders["home"].append("z")

        self.assertEqual(saved["pending_injury_tests"], ["a", "b"])
        self.assertEqual(saved["assigned_positions"], {"a": ["midfield", 1]})
        self.assertEqual(saved["shootout_orders"], {"home": ["a"]})

    def test_a_mutable_fallback_is_not_shared_between_games(self) -> None:
        # The reason the table splits `default` from `factory`.
        saved = self.match().to_dict()
        bare = {
            key: value
            for key, value in saved.items()
            if key not in {"pending_injury_tests", "assigned_positions"}
        }

        first = MatchState.from_dict(bare, self.rules)
        second = MatchState.from_dict(bare, self.rules)
        first.pending_injury_tests.append("a")
        first.assigned_positions["a"] = ["midfield", 1]

        self.assertEqual(second.pending_injury_tests, [])
        self.assertEqual(second.assigned_positions, {})

    def test_time_outs_used_is_stored_sorted_and_read_as_a_set(
        self,
    ) -> None:
        # The one field whose two directions differ: sorted so a save
        # file is stable, a set so membership is the question asked.
        match = self.match()
        match.time_outs_used = {"visiting", "home"}

        saved = match.to_dict()
        self.assertEqual(saved["time_outs_used"], ["home", "visiting"])

        restored = MatchState.from_dict(saved, self.rules)
        self.assertEqual(restored.time_outs_used, {"home", "visiting"})


if __name__ == "__main__":
    unittest.main()
