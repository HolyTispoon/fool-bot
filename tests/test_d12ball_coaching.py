"""
The four actions a Coaching Choice offers, at the model layer:
substitution, zone assignment, space positioning, and the whole-side
deployment a formation change is made of. See "Coaching Choice" in
docs/living-rules.md.
"""

import unittest

from d12ball.components import (
    CoachingOccasion,
    MatchState,
    TeamSide,
    Zone,
    load_basic_ruleset,
    load_player_catalog,
)
from d12ball.game import Formation, Team


class CoachingModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    def build_match(
        self,
        board_size: int = 7,
        home_formation: Formation = Formation.TWO_TWO_TWO,
    ) -> MatchState:
        return MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=board_size,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
            home_formation=home_formation,
        )

    # -- Substitution --------------------------------------------------

    def test_setup_sends_an_outgoing_player_back_to_the_bench(self) -> None:
        match = self.build_match()
        outgoing = match.home.field_players[0]
        incoming = match.home.player_board.bench[0]

        match.substitute(
            TeamSide.HOME, outgoing, incoming, retire_outgoing=False,
        )

        self.assertIn(outgoing, match.home.player_board.bench)
        self.assertEqual(match.home.player_board.back_bench, [])
        # And so they can come straight back on, which is the whole
        # point of setup's exception.
        self.assertIn(
            outgoing, match.substitution_pool(TeamSide.HOME, incoming),
        )

    def test_every_other_occasion_retires_them(self) -> None:
        match = self.build_match()
        outgoing = match.home.field_players[0]
        incoming = match.home.player_board.bench[0]

        match.substitute(TeamSide.HOME, outgoing, incoming)

        self.assertIn(outgoing, match.home.player_board.back_bench)
        self.assertNotIn(outgoing, match.home.player_board.bench)

    def test_the_occasion_decides_which_way(self) -> None:
        self.assertFalse(
            CoachingOccasion.SETUP.retires_outgoing_players,
        )
        for occasion in (
            CoachingOccasion.NEW_PLAY,
            CoachingOccasion.HALFTIME,
        ):
            self.assertTrue(occasion.retires_outgoing_players)

    # -- Zone assignment -----------------------------------------------

    def test_exchanging_two_players_moves_their_meeples_too(self) -> None:
        match = self.build_match()
        setup = match.home
        first = setup.zones[Zone.HOME_GOAL][0]
        second = setup.zones[Zone.VISITORS_GOAL][0]
        first_position = match.board.meeple_position(first)
        second_position = match.board.meeple_position(second)

        match.exchange_field_players(TeamSide.HOME, first, second)

        self.assertEqual(setup.assigned_zone(first), Zone.VISITORS_GOAL)
        self.assertEqual(setup.assigned_zone(second), Zone.HOME_GOAL)
        self.assertEqual(
            match.board.meeple_position(first), second_position,
        )
        self.assertEqual(
            match.board.meeple_position(second), first_position,
        )

    def test_an_exchange_leaves_nobody_outside_their_own_zone(self) -> None:
        match = self.build_match()
        setup = match.home
        first = setup.zones[Zone.MIDFIELD][0]
        second = setup.zones[Zone.HOME_GOAL][1]

        match.exchange_field_players(TeamSide.HOME, first, second)

        for player_id in setup.field_players:
            position = match.board.meeple_position(player_id)
            self.assertEqual(position[0], setup.assigned_zone(player_id))

    # -- Space positioning ---------------------------------------------

    def test_moving_to_an_empty_space_is_an_ordinary_move(self) -> None:
        # Board 9's three-space zones hold two cards under 2-2-2, so
        # there is always an empty space to step onto.
        match = self.build_match(board_size=9)
        player_id = match.home.zones[Zone.HOME_GOAL][0]

        self.assertEqual(
            match.positioning_swap_candidates(TeamSide.HOME, player_id, 2),
            [],
        )
        partner = match.position_meeple(TeamSide.HOME, player_id, 2)

        self.assertIsNone(partner)
        self.assertEqual(
            match.board.meeple_position(player_id), (Zone.HOME_GOAL, 2),
        )

    def test_a_sole_occupant_moving_onto_a_teammate_trades(self) -> None:
        match = self.build_match()
        first, second = match.home.zones[Zone.HOME_GOAL]
        first_position = match.board.meeple_position(first)
        second_position = match.board.meeple_position(second)

        partner = match.position_meeple(
            TeamSide.HOME, first, second_position[1],
        )

        self.assertEqual(partner, second)
        self.assertEqual(
            match.board.meeple_position(first), second_position,
        )
        self.assertEqual(
            match.board.meeple_position(second), first_position,
        )

    def test_leaving_a_teammate_behind_stacks_instead_of_trading(
        self,
    ) -> None:
        # Board 6 under 2-3-1 puts two of the three midfielders on one
        # space. Either of them can step across onto the third without
        # trading, because the space they leave stays covered.
        match = self.build_match(
            board_size=6, home_formation=Formation.TWO_THREE_ONE,
        )
        stacked = [
            occupants
            for occupants in match.board.spaces[Zone.MIDFIELD]
            if len(
                [
                    player_id
                    for player_id in occupants
                    if player_id in set(match.home.field_players)
                ]
            )
            > 1
        ]
        self.assertTrue(stacked, "expected 2-3-1 on board 6 to stack")
        mover = [
            player_id
            for player_id in stacked[0]
            if player_id in set(match.home.field_players)
        ][0]
        origin = match.board.meeple_position(mover)
        target = 1 - origin[1]

        self.assertEqual(
            match.positioning_swap_candidates(TeamSide.HOME, mover, target),
            [],
        )
        partner = match.position_meeple(TeamSide.HOME, mover, target)

        self.assertIsNone(partner)
        self.assertEqual(
            match.board.meeple_position(mover), (Zone.MIDFIELD, target),
        )

    def test_more_than_one_on_the_target_has_to_be_picked_between(
        self,
    ) -> None:
        match = self.build_match(
            board_size=6, home_formation=Formation.TWO_THREE_ONE,
        )
        # Pile all three midfielders onto M1, then bring the odd one
        # out back: the trade is now ambiguous.
        midfielders = list(match.home.zones[Zone.MIDFIELD])
        for player_id in midfielders:
            match.board.place_meeple(player_id, Zone.MIDFIELD, 0)
        loner = midfielders[0]
        match.board.place_meeple(loner, Zone.MIDFIELD, 1)

        candidates = match.positioning_swap_candidates(
            TeamSide.HOME, loner, 0,
        )
        self.assertEqual(sorted(candidates), sorted(midfielders[1:]))

        with self.assertRaises(ValueError):
            match.position_meeple(TeamSide.HOME, loner, 0)

        partner = match.position_meeple(
            TeamSide.HOME, loner, 0, swap_with=midfielders[2],
        )
        self.assertEqual(partner, midfielders[2])
        self.assertEqual(
            match.board.meeple_position(midfielders[2]),
            (Zone.MIDFIELD, 1),
        )

    def test_an_opponent_on_the_space_is_not_traded_with(self) -> None:
        # Occupancy is per team and opposing meeples share spaces
        # freely, so a space holding only an opponent is an ordinary
        # empty one as far as this side is concerned.
        match = self.build_match(board_size=9)
        player_id = match.home.zones[Zone.MIDFIELD][0]
        opponent = match.visiting.zones[Zone.MIDFIELD][0]
        match.board.place_meeple(opponent, Zone.MIDFIELD, 2)

        self.assertEqual(
            match.positioning_swap_candidates(TeamSide.HOME, player_id, 2),
            [],
        )
        self.assertIsNone(
            match.position_meeple(TeamSide.HOME, player_id, 2),
        )
        self.assertEqual(
            match.board.meeple_position(opponent), (Zone.MIDFIELD, 2),
        )

    def test_positioning_refuses_a_space_outside_the_assigned_zone(
        self,
    ) -> None:
        match = self.build_match()
        player_id = match.home.zones[Zone.HOME_GOAL][0]

        # Home goal has two spaces on board 7, so index 2 is not one.
        with self.assertRaises(ValueError):
            match.position_meeple(TeamSide.HOME, player_id, 2)

    # -- Whole-side deployment -----------------------------------------

    def test_deploying_a_side_sets_zones_and_spaces_together(self) -> None:
        match = self.build_match()
        players = list(match.home.field_players)
        placement = [
            (players[0], Zone.HOME_GOAL, 0),
            (players[1], Zone.HOME_GOAL, 1),
            (players[2], Zone.MIDFIELD, 0),
            (players[3], Zone.MIDFIELD, 1),
            (players[4], Zone.MIDFIELD, 2),
            (players[5], Zone.VISITORS_GOAL, 0),
        ]

        match.deploy_side(TeamSide.HOME, placement)

        self.assertEqual(len(match.home.zones[Zone.MIDFIELD]), 3)
        self.assertEqual(len(match.home.zones[Zone.VISITORS_GOAL]), 1)
        for player_id, zone, space_index in placement:
            self.assertEqual(
                match.home.assigned_zone(player_id), zone,
            )
            self.assertEqual(
                match.board.meeple_position(player_id), (zone, space_index),
            )

    def test_a_deployment_has_to_name_exactly_the_fielded_six(self) -> None:
        match = self.build_match()
        players = list(match.home.field_players)

        with self.assertRaises(ValueError):
            match.deploy_side(
                TeamSide.HOME,
                [(players[0], Zone.HOME_GOAL, 0)],
            )

        with self.assertRaises(ValueError):
            match.deploy_side(
                TeamSide.HOME,
                [(players[0], Zone.HOME_GOAL, index) for index in range(6)],
            )


if __name__ == "__main__":
    unittest.main()
