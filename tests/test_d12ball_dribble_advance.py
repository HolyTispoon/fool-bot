"""
The Playmaker's choice of 1 or 2 spaces, and what the buttons call it.

A distance is only half an answer: which space a dribble ends on
depends on where the handler is standing and which way their side
attacks, and neither is on a button that says "Advance 2 spaces". The
menu names the destination as well, from
MatchState.relative_move_destination -- the same reading
move_player_relative moves by, so the label cannot promise a space the
move does not go to.

See DribbleAdvanceChoiceView, and "dribble_advance" in
docs/living-rules.md.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

from cogs.d12ball_views import DribbleAdvanceChoiceView
from d12ball.components import (
    MatchState,
    PlayerRole,
    TeamSide,
    Zone,
    load_basic_ruleset,
    load_player_catalog,
)
from d12ball.game import Team


class DribbleAdvanceDestinationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    def build(self, side: TeamSide, zone: Zone, space: int):
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
        )
        setup = match.setup_for_side(side)
        match.active_player_id = next(
            player_id for player_id in setup.field_players
            if self.catalog.player_by_id(player_id).role
            == PlayerRole.PLAYMAKER
        )
        match.move_meeple(match.active_player_id, zone, space)
        match.ball.possession = side
        match.set_ball_space(zone, space)

        game = SimpleNamespace(match_state=match.to_dict(), game_id="g1")
        cog = mock.Mock()
        cog.games = {"g1": game}
        cog.engine.load_match_state = mock.Mock(return_value=match)
        return DribbleAdvanceChoiceView(cog, "g1")

    def labels(self, view: DribbleAdvanceChoiceView) -> list[str]:
        return [item.label for item in view.children]

    def test_the_destination_is_named_on_each_button(self) -> None:
        # Home attacks left to right, so the two dribbles out of M1 end
        # on the next two spaces along.
        self.assertEqual(
            self.labels(self.build(TeamSide.HOME, Zone.MIDFIELD, 0)),
            ["Advance 1 space (M2)", "Advance 2 spaces (M3)"],
        )

    def test_the_visiting_side_advances_the_other_way(self) -> None:
        # The same space, the other direction: "2 spaces" means the
        # opposite end of the board depending on who is dribbling,
        # which is the whole reason the button says where.
        self.assertEqual(
            self.labels(self.build(TeamSide.VISITING, Zone.MIDFIELD, 2)),
            ["Advance 1 space (M2)", "Advance 2 spaces (M1)"],
        )

    def test_a_dribble_that_runs_out_of_field_says_so(self) -> None:
        # Standing on the last space of the board, both distances clamp
        # to where they already are. Two buttons naming one space is
        # the honest answer: the longer dribble buys nothing, which is
        # exactly what a coach cannot tell from "1 or 2".
        self.assertEqual(
            self.labels(self.build(TeamSide.HOME, Zone.VISITORS_GOAL, 1)),
            ["Advance 1 space (V2)", "Advance 2 spaces (V2)"],
        )


if __name__ == "__main__":
    unittest.main()
