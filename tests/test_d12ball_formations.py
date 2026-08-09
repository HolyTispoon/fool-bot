"""
Formations: the three shapes basic mode allows, how a coach moves
between them in a substitution window, and the coverage rule that
decides where a meeple may stand once a zone holds more players than it
has spaces.

Every game kicks off in 2-2-2, so setup has nothing to ask and nothing
here drives it. The run back's own flow is covered in
test_d12ball_components; this is about the shapes themselves, and about
what stacking changes for the coach -- including who receives a Low
Pass into a space several teammates share.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

from cogs.d12ball import D12Ball
from cogs.d12ball_views import (
    LowPassChoiceView,
    LowPassReceiverView,
    SubstitutionFormationView,
    SubstitutionMenuView,
)
from d12ball.components import (
    SETUP_AREAS,
    MatchState,
    PlayerRole,
    TeamSide,
    Zone,
    create_standard_setup,
    default_formation_deal,
    fill_forced_areas,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
    next_unfilled_area,
    setup_space_order,
    validate_assignment,
)
from d12ball.game import (
    D12BallGame,
    Formation,
    GameStatus,
    Team,
)


def build_cog() -> D12Ball:
    cog = object.__new__(D12Ball)
    cog.games = {}
    cog.player_catalog = load_player_catalog()
    cog.maneuver_catalog = load_maneuver_catalog()
    cog.basic_ruleset = load_basic_ruleset()
    cog.team_emojis = {}
    cog.condition_emojis = {}
    cog.coin_emojis = {}
    cog.ensure_coin_emojis = mock.AsyncMock()
    cog.refresh_match_image = mock.AsyncMock()
    return cog


def build_game(**overrides) -> D12BallGame:
    fields = dict(
        game_id="g1",
        game_number=1,
        guild_id=1,
        channel_id=2,
        message_id=None,
        player_1_id=111,
        player_2_id=222,
        player_1_name="One",
        player_2_name="Two",
        player_1_team=Team.ORANGE,
        player_2_team=Team.PURPLE,
        status=GameStatus.SETUP,
    )
    fields.update(overrides)
    return D12BallGame(**fields)


def build_interaction(user_id: int = 111) -> SimpleNamespace:
    return SimpleNamespace(
        user=SimpleNamespace(id=user_id, display_name="One"),
        response=SimpleNamespace(
            edit_message=mock.AsyncMock(),
            send_message=mock.AsyncMock(),
        ),
        followup=SimpleNamespace(send=mock.AsyncMock()),
        message=SimpleNamespace(content="", edit=mock.AsyncMock()),
    )


class FormationShapeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    def test_every_formation_fields_six_players(self) -> None:
        self.assertEqual(set(self.rules.formations), set(Formation))
        for formation, shape in self.rules.formations.items():
            with self.subTest(formation=formation.value):
                self.assertEqual(shape.total, 6)
                self.assertEqual(
                    [shape.count(area) for area in SETUP_AREAS],
                    [int(part) for part in formation.value.split("-")],
                )

    def test_the_default_deal_reads_the_roles_back_to_front(self) -> None:
        roster = self.catalog.teams[Team.ORANGE]
        two_two_two = default_formation_deal(
            roster, self.rules, Formation.TWO_TWO_TWO,
        )
        two_three_one = default_formation_deal(
            roster, self.rules, Formation.TWO_THREE_ONE,
        )

        # 2-3-1 pulls the winger back out of the front pair, so the
        # same six cards come out in the same order.
        self.assertEqual(
            [
                player_id
                for area in SETUP_AREAS
                for player_id in two_two_two[area]
            ],
            [
                player_id
                for area in SETUP_AREAS
                for player_id in two_three_one[area]
            ],
        )
        self.assertEqual(
            two_three_one["midfield"],
            two_two_two["midfield"] + two_two_two["opponent_goal"][:1],
        )

    def test_the_bench_is_the_same_three_whatever_the_shape(self) -> None:
        benches = set()
        for formation in Formation:
            setup = create_standard_setup(
                self.catalog.teams[Team.TEAL],
                TeamSide.HOME,
                self.rules,
                formation=formation,
            )
            self.assertEqual(len(setup.field_players), 6)
            benches.add(tuple(setup.player_board.bench))

        self.assertEqual(len(benches), 1)

    def test_a_formation_puts_its_numbers_in_each_zone(self) -> None:
        setup = create_standard_setup(
            self.catalog.teams[Team.SLIME],
            TeamSide.VISITING,
            self.rules,
            formation=Formation.ONE_THREE_TWO,
        )

        # The visiting side defends the visitors goal, so 1-3-2's two
        # attackers stand in the *home* goal zone.
        self.assertEqual(len(setup.zones[Zone.VISITORS_GOAL]), 1)
        self.assertEqual(len(setup.zones[Zone.MIDFIELD]), 3)
        self.assertEqual(len(setup.zones[Zone.HOME_GOAL]), 2)

    def test_an_assignment_has_to_match_its_formation(self) -> None:
        roster = self.catalog.teams[Team.ORANGE]
        shape = self.rules.formations[Formation.TWO_THREE_ONE]
        deal = default_formation_deal(
            roster, self.rules, Formation.TWO_TWO_TWO,
        )

        with self.assertRaises(ValueError):
            validate_assignment(roster, shape, deal)

    def test_an_assignment_cannot_field_a_player_twice(self) -> None:
        roster = self.catalog.teams[Team.ORANGE]
        shape = self.rules.formations[Formation.TWO_TWO_TWO]
        deal = default_formation_deal(
            roster, self.rules, Formation.TWO_TWO_TWO,
        )
        deal["midfield"] = list(deal["own_goal"])

        with self.assertRaises(ValueError):
            validate_assignment(roster, shape, deal)

    def test_setup_covers_every_space_before_stacking(self) -> None:
        # Four players into a two-space zone: both spaces first, then
        # round again, rather than four on one space.
        self.assertEqual(setup_space_order(TeamSide.HOME, 2, 4), [0, 1, 0, 1])
        # The visiting side fills from its own end, so its order is the
        # mirror image.
        self.assertEqual(
            setup_space_order(TeamSide.VISITING, 3, 4), [2, 1, 0, 2],
        )

    def test_a_stacking_formation_starts_with_every_space_taken(
        self,
    ) -> None:
        # Board 6's two-space midfield is the only zone any of the
        # three shapes overfills: 2-3-1 puts three cards in it.
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=6,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
            home_formation=Formation.TWO_THREE_ONE,
        )

        home_players = set(match.home.field_players)
        occupancy = [
            [
                player_id
                for player_id in occupants
                if player_id in home_players
            ]
            for occupants in match.board.spaces[Zone.MIDFIELD]
        ]

        self.assertEqual([len(space) for space in occupancy], [2, 1])
        self.assertEqual(
            match.open_spaces_in_zone(TeamSide.HOME, Zone.MIDFIELD), [],
        )


class CoverageRuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    def build_match(self, **overrides) -> MatchState:
        fields = dict(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
        )
        fields.update(overrides)
        return MatchState.standard(**fields)

    def test_only_uncovered_spaces_are_offered_while_one_is_free(
        self,
    ) -> None:
        # Board 9's three-space zones leave 2-2-2 a space spare.
        match = self.build_match(board_size=9)
        player_id = match.home.zones[Zone.HOME_GOAL][0]

        spaces = match.placement_spaces_in_zone(
            TeamSide.HOME, Zone.HOME_GOAL, player_id,
        )
        teammate_space = match.board.meeple_position(
            match.home.zones[Zone.HOME_GOAL][1]
        )[1]

        self.assertNotIn(teammate_space, spaces)

    def test_a_covered_zone_opens_every_space_for_the_surplus(
        self,
    ) -> None:
        match = self.build_match(
            board_size=6, home_formation=Formation.TWO_THREE_ONE,
        )
        # A 2-3-1 defender, sent out of position and running back into
        # a midfield whose two spaces its three cards already cover,
        # may stand on either of them.
        stray = match.home.zones[Zone.HOME_GOAL][0]

        self.assertEqual(
            match.placement_spaces_in_zone(
                TeamSide.HOME, Zone.MIDFIELD, stray,
            ),
            [0, 1],
        )

    def test_the_mover_does_not_count_as_covering_a_space(self) -> None:
        match = self.build_match(board_size=9)
        player_id = match.home.zones[Zone.HOME_GOAL][0]
        own_space = match.board.meeple_position(player_id)[1]

        self.assertIn(
            own_space,
            match.placement_spaces_in_zone(
                TeamSide.HOME, Zone.HOME_GOAL, player_id,
            ),
        )

    def test_an_opponent_never_blocks_a_space(self) -> None:
        match = self.build_match()
        home_player = match.home.zones[Zone.MIDFIELD][0]
        visiting_player = match.visiting.zones[Zone.MIDFIELD][0]
        zone, space_index = match.board.meeple_position(visiting_player)

        self.assertIn(
            space_index,
            match.placement_spaces_in_zone(TeamSide.HOME, zone, home_player),
        )

    def test_running_back_may_stack_once_the_zone_is_covered(self) -> None:
        match = self.build_match(
            board_size=6, home_formation=Formation.TWO_THREE_ONE,
        )
        stray = match.home.zones[Zone.MIDFIELD][0]
        match.board.remove_meeple(stray)
        match.board.place_meeple(stray, Zone.VISITORS_GOAL, 1)

        self.assertIn(stray, match.displaced_players(TeamSide.HOME))

        match.run_back_player(stray, Zone.MIDFIELD, 1)

        self.assertEqual(
            match.board.meeple_position(stray), (Zone.MIDFIELD, 1),
        )
        match.validate(self.catalog)

    def test_running_back_refuses_to_leave_a_space_uncovered(self) -> None:
        match = self.build_match(board_size=9)
        stray = match.home.zones[Zone.HOME_GOAL][0]
        teammate_space = match.board.meeple_position(
            match.home.zones[Zone.HOME_GOAL][1]
        )[1]
        match.board.remove_meeple(stray)
        match.board.place_meeple(stray, Zone.MIDFIELD, 1)

        with self.assertRaises(ValueError):
            match.run_back_player(stray, Zone.HOME_GOAL, teammate_space)

    def test_a_stack_only_breaks_up_while_a_space_is_free(self) -> None:
        # 2-3-1's midfield fills board 6's two spaces, so its pair
        # stays paired: nobody is asked to move somewhere that does
        # not help.
        match = self.build_match(
            board_size=6, home_formation=Formation.TWO_THREE_ONE,
        )

        self.assertEqual(match.crowded_players(TeamSide.HOME), [])

        # Pile all three onto one space of board 9's three-space
        # midfield and two of them are crowded -- as many as the free
        # spaces they can spread into, no more.
        roomier = self.build_match(
            board_size=9, home_formation=Formation.TWO_THREE_ONE,
        )
        for player_id in roomier.home.zones[Zone.MIDFIELD]:
            roomier.board.remove_meeple(player_id)
            roomier.board.place_meeple(player_id, Zone.MIDFIELD, 0)

        self.assertEqual(len(roomier.crowded_players(TeamSide.HOME)), 2)

    def test_halftime_placement_answers_to_coverage_too(self) -> None:
        match = self.build_match(board_size=9)
        player_id = match.home.zones[Zone.MIDFIELD][0]
        occupied = match.board.meeple_position(
            match.home.zones[Zone.HOME_GOAL][0]
        )[1]

        with self.assertRaises(ValueError):
            match.reposition_meeple_anywhere(
                TeamSide.HOME, player_id, Zone.HOME_GOAL, occupied,
            )


class FormationReassignmentTests(unittest.TestCase):
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
            visiting_team=Team.PURPLE,
        )

    def test_a_reassignment_rewrites_every_zone_and_moves_nobody(
        self,
    ) -> None:
        match = self.build_match()
        before = {
            player_id: match.board.meeple_position(player_id)
            for player_id in match.home.field_players
        }
        fielded = list(match.home.field_players)

        match.reassign_field_zones(
            TeamSide.HOME,
            {
                Zone.HOME_GOAL: fielded[:2],
                Zone.MIDFIELD: fielded[2:3],
                Zone.VISITORS_GOAL: fielded[3:],
            },
        )

        self.assertEqual(len(match.home.zones[Zone.VISITORS_GOAL]), 3)
        for player_id, position in before.items():
            self.assertEqual(
                match.board.meeple_position(player_id), position,
            )
        match.validate(self.catalog)

    def test_a_reassignment_has_to_place_exactly_the_fielded_six(
        self,
    ) -> None:
        match = self.build_match()
        fielded = list(match.home.field_players)
        benched = match.home.player_board.bench[0]

        with self.assertRaises(ValueError):
            match.reassign_field_zones(
                TeamSide.HOME,
                {
                    Zone.HOME_GOAL: fielded[:2],
                    Zone.MIDFIELD: fielded[2:3],
                    Zone.VISITORS_GOAL: fielded[3:5] + [benched],
                },
            )

    def test_the_cog_rejects_a_shape_no_formation_allows(self) -> None:
        cog = build_cog()
        match = self.build_match()
        fielded = list(match.home.field_players)

        with self.assertRaises(ValueError):
            cog.apply_formation_change(
                match,
                TeamSide.HOME,
                Formation.TWO_THREE_ONE,
                {
                    "own_goal": fielded[:3],
                    "midfield": fielded[3:4],
                    "opponent_goal": fielded[4:],
                },
            )

    def test_the_current_formation_is_read_off_the_zones(self) -> None:
        cog = build_cog()
        match = self.build_match()

        self.assertEqual(
            cog.current_formation(match, TeamSide.HOME),
            Formation.TWO_TWO_TWO,
        )

        fielded = list(match.home.field_players)
        cog.apply_formation_change(
            match,
            TeamSide.HOME,
            Formation.ONE_THREE_TWO,
            {
                "own_goal": fielded[:1],
                "midfield": fielded[1:4],
                "opponent_goal": fielded[4:],
            },
        )

        self.assertEqual(
            cog.current_formation(match, TeamSide.HOME),
            Formation.ONE_THREE_TWO,
        )
        self.assertEqual(
            match.home.assigned_zone(fielded[5]), Zone.VISITORS_GOAL,
        )


class AssignmentStepTests(unittest.TestCase):
    def test_forced_areas_fill_themselves(self) -> None:
        rules = load_basic_ruleset()
        shape = rules.formations[Formation.TWO_TWO_TWO]
        candidates = [f"p{index}" for index in range(6)]

        # Nothing is forced up front: 2 of 6 is a real choice.
        self.assertEqual(fill_forced_areas({}, shape, candidates), {})

        # Once four are placed, the last two have only one home left.
        filled = fill_forced_areas(
            {"own_goal": candidates[:2], "midfield": candidates[2:4]},
            shape,
            candidates,
        )
        self.assertEqual(filled["opponent_goal"], candidates[4:])
        self.assertIsNone(next_unfilled_area(filled))


class SubstitutionFormationFlowTests(unittest.IsolatedAsyncioTestCase):
    def build(self) -> tuple[D12Ball, D12BallGame, MatchState]:
        cog = build_cog()
        game = build_game(
            status=GameStatus.IN_PROGRESS,
            home_player_number=1,
            visiting_player_number=2,
        )
        cog.games[game.game_id] = game
        match = cog.initialize_standard_match(game)
        match.open_substitution_window(TeamSide.HOME)
        game.match_state = match.to_dict()
        return cog, game, match

    def test_every_game_kicks_off_in_2_2_2(self) -> None:
        cog, _, match = self.build()

        for side in (TeamSide.HOME, TeamSide.VISITING):
            self.assertEqual(
                cog.current_formation(match, side),
                Formation.TWO_TWO_TWO,
            )

    def test_the_menu_offers_a_formation_change(self) -> None:
        cog, game, _ = self.build()

        labels = [
            item.label
            for item in SubstitutionMenuView(cog, game.game_id).children
        ]

        self.assertIn("Change formation (currently 2-2-2)", labels)

    async def test_a_change_applies_once_every_zone_is_filled(self) -> None:
        cog, game, _ = self.build()
        view = SubstitutionFormationView(cog, game.game_id)

        with mock.patch("cogs.d12ball_views.save_games"):
            await view.pick_formation(
                build_interaction(), Formation.TWO_THREE_ONE,
            )
            match = cog.load_match_state(game)
            # Nothing is written until the whole shape is filled in.
            self.assertEqual(
                cog.current_formation(match, TeamSide.HOME),
                Formation.TWO_TWO_TWO,
            )

            fielded = match.setup_for_side(TeamSide.HOME).field_players
            await view.pick_cards(
                build_interaction(), "own_goal", fielded[:2],
            )
            await view.pick_cards(
                build_interaction(), "midfield", fielded[2:5],
            )

        match = cog.load_match_state(game)
        self.assertEqual(
            cog.current_formation(match, TeamSide.HOME),
            Formation.TWO_THREE_ONE,
        )
        self.assertEqual(
            match.home.assigned_zone(fielded[5]), Zone.VISITORS_GOAL,
        )


class LowPassIntoAStackTests(unittest.IsolatedAsyncioTestCase):
    """
    Passing into a space several teammates share -- which is what a
    stacking formation makes ordinary, and why the passer is asked who
    receives rather than handed the first occupant.
    """

    def build(self, extras: int = 3):
        cog = build_cog()
        cog.finish_maneuver_resolution = mock.AsyncMock()
        cog.offer_scoring_attempt_choice = mock.AsyncMock()
        game = build_game(
            status=GameStatus.IN_PROGRESS,
            home_player_number=1,
            visiting_player_number=2,
        )
        cog.games[game.game_id] = game
        match = cog.initialize_standard_match(game)

        winger = next(
            player_id
            for player_id in match.home.field_players
            if cog.get_player_definition(player_id).role == PlayerRole.WINGER
        )
        # The far midfield space, M3: past the midline, which is where
        # a Winger's set-up can offer a shot at all (2026-08-09). The
        # standard setup leaves it empty, so every receiver here is put
        # there deliberately -- one more than `extras`, since a stack
        # of one is still a space with a teammate on it.
        others = [
            player_id
            for player_id in match.home.field_players
            if player_id != winger
        ][:extras + 1]
        for player_id in [winger] + others:
            match.board.remove_meeple(player_id)
            match.board.place_meeple(player_id, Zone.MIDFIELD, 2)
        match.ball.possession = TeamSide.HOME
        match.set_ball_space(Zone.MIDFIELD, 2)
        match.active_player_id = winger
        game.match_state = match.to_dict()
        return cog, game, match, cog.low_pass_receivers(match, 0)

    def test_a_shared_destination_is_labelled_by_its_count(self) -> None:
        cog, game, _, others = self.build()

        labels = [
            item.label
            for item in LowPassChoiceView(cog, game.game_id).children
        ]

        # Naming one of three would misread what is being picked.
        self.assertIn(f"{len(others)} players -- M3", labels)

    async def test_the_passer_is_asked_which_teammate_receives(
        self,
    ) -> None:
        cog, game, _, others = self.build()
        interaction = build_interaction()

        with mock.patch("cogs.d12ball_views.save_games"):
            await LowPassChoiceView(cog, game.game_id).choose(interaction, 0)

        view = interaction.response.edit_message.call_args.kwargs["view"]
        self.assertIsInstance(view, LowPassReceiverView)
        self.assertEqual(len(view.children), len(others))

    async def test_the_chosen_receiver_takes_the_winger_s_set_up(
        self,
    ) -> None:
        cog, game, _, others = self.build()
        chosen = others[-1]

        with mock.patch("cogs.d12ball_views.save_games"), \
                mock.patch("cogs.d12ball.save_games"):
            await LowPassReceiverView(cog, game.game_id, 0).choose(
                build_interaction(), chosen,
            )

        self.assertEqual(
            cog.offer_scoring_attempt_choice.await_args.kwargs["shooter_id"],
            chosen,
        )

    async def test_a_single_teammate_is_passed_to_without_a_prompt(
        self,
    ) -> None:
        cog, game, _, others = self.build(extras=0)
        interaction = build_interaction()

        with mock.patch("cogs.d12ball_views.save_games"), \
                mock.patch("cogs.d12ball.save_games"):
            await LowPassChoiceView(cog, game.game_id).choose(interaction, 0)

        self.assertIsNone(
            interaction.response.edit_message.call_args.kwargs["view"]
        )
        self.assertEqual(
            cog.offer_scoring_attempt_choice.await_args.kwargs["shooter_id"],
            others[0],
        )

    async def test_only_the_side_in_possession_may_choose(self) -> None:
        cog, game, _, others = self.build()
        interaction = build_interaction(user_id=999)

        with mock.patch("cogs.d12ball_views.save_games"):
            await LowPassReceiverView(cog, game.game_id, 0).choose(
                interaction, others[0],
            )

        interaction.response.send_message.assert_awaited_once()
        cog.offer_scoring_attempt_choice.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
