"""
The Midfielder's role ability (Law 6.4): +3 on a skill test for their
own Low Pass or their own Steal, and by rank for the two gambits on
those ranks, Pinpoint and Intercept (Law 18.3). It was Pressure's
and Double Team's until 2026-09-27 (docs/rules-log.md).
"""

import pathlib
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from d12ball.components import PlayerRole, TeamSide
from d12ball.flow.rolls import score_skill_test
from d12ball.game import GameMode

from roster import fielded
from test_d12ball_species_abilities import (
    build_engine,
    build_game,
    build_match,
)

ENGINE = build_engine()
BONUS = "+3 Midfielder ability"


class MidfielderBonusTests(unittest.TestCase):

    def setUp(self) -> None:
        # Training mode, so no species or personal ability adds to
        # either side and the +3 is the only thing being read.
        self.game = build_game(mode=GameMode.TRAINING)
        self.match = build_match(ENGINE, self.game)
        self.match.ball.possession = TeamSide.HOME
        # Speed 1: the Steal's ball speed modifier is 0.
        self.match.ball.speed = 1

    def details(self, offense_role, offense_card, defense_role, defense_card):
        self.match.offense_maneuver = offense_card
        self.match.defense_maneuver = defense_card
        offense = fielded(self.match, offense_role, TeamSide.HOME)
        defense = fielded(self.match, defense_role, TeamSide.VISITING)
        with mock.patch.object(ENGINE.rng, "randint", return_value=5):
            sides, _, _, _, _ = score_skill_test(
                ENGINE, self.game, self.match,
                ENGINE.get_player_definition(offense),
                ENGINE.get_player_definition(defense),
            )
        return sides[0][2], sides[1][2]

    def test_on_defence_for_steal_and_intercept(self) -> None:
        for card in ("steal", "intercept"):
            with self.subTest(card=card):
                _, defense = self.details(
                    PlayerRole.PLAYMAKER, "dribble_advance",
                    PlayerRole.MIDFIELDER, card,
                )
                self.assertIn(BONUS, defense)

    def test_not_for_pressure_or_double_team_any_more(self) -> None:
        for card in ("pressure", "double_team", "deflect", "clear"):
            with self.subTest(card=card):
                _, defense = self.details(
                    PlayerRole.PLAYMAKER, "low_pass",
                    PlayerRole.MIDFIELDER, card,
                )
                self.assertNotIn(BONUS, defense)

    def test_on_offence_for_low_pass_and_skilled_pass(self) -> None:
        for card in ("low_pass", "skilled_pass"):
            with self.subTest(card=card):
                offense, _ = self.details(
                    PlayerRole.MIDFIELDER, card,
                    PlayerRole.DEFENDER, "steal",
                )
                self.assertIn(BONUS, offense)

    def test_only_a_midfielder(self) -> None:
        _, defense = self.details(
            PlayerRole.PLAYMAKER, "dribble_advance",
            PlayerRole.DEFENDER, "steal",
        )
        self.assertNotIn(BONUS, defense)


if __name__ == "__main__":
    unittest.main()
