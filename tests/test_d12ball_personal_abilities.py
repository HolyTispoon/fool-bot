"""
The personal abilities and the advanced skill scores (Law 21 of
docs/living-rules.md; "Personal abilities" in
docs/design/species-abilities.md).

Two kinds of test. The table's own tests read `players.json` and say
which sheet sentence each row was built from, so a reworded or moved
ability fails here rather than being played as the old one. Everything
else hands an ability to a player by patching the table
(`holding(...)`), so no test depends on who is fielded where -- the
roster is data the author revises.
"""

import json
import pathlib
import sys
import unittest
from contextlib import contextmanager
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from d12ball.components import (
    CYBORG_DRAINED_AT,
    MIND_PULL_TOKEN_COST,
    OVERDRIVE_BONUS,
    OVERDRIVE_DRAIN_COST,
    SPECIES_CYBORG,
    SPECIES_FIRE_DEMON,
    SPECIES_TELEKINETIC,
    RuleRefusal,
    ShotDefender,
    TeamSide,
    catalog_player_id,
    duplicate_card_id,
)
from d12ball.engine import IgnitedRoll
from d12ball.flow.effects import pressure_step
from d12ball.flow.result import FollowOnStep
from d12ball.game import GameMode, Team
from d12ball.personal_abilities import (
    ADVANCED_SKILL_SENTENCES,
    BOOST_BONUS,
    BOOST_DRAIN_COST,
    BULWARK_DRAINED_AT,
    PERSONAL_ABILITIES,
    SPECTRA_PULL_BONUS,
    STRIDER_CHARGE_UP,
    VOLTUS_OVERDRIVE_DRAIN_COST,
    PersonalAbility,
)

from roster import fielded_of_species
from test_d12ball_species_abilities import (
    build_engine,
    build_game,
    build_match,
)
import pressure_fixtures

PLAYERS_JSON = (
    pathlib.Path(__file__).resolve().parents[1]
    / "d12ball" / "data" / "players.json"
)

ENGINE = build_engine()


@contextmanager
def holding(player_id: str, ability: PersonalAbility):
    """Give `player_id`'s person this ability for the test's length."""
    with mock.patch.dict(
        PERSONAL_ABILITIES,
        {catalog_player_id(player_id): (ability, "test")},
    ):
        yield


def advanced(**overrides):
    return build_game(mode=GameMode.ADVANCED, **overrides)


class TableTests(unittest.TestCase):
    """The table against the sheet's own sentences."""

    def setUp(self) -> None:
        self.players = json.loads(
            PLAYERS_JSON.read_text(encoding="utf-8"),
        )["players"]

    def test_every_row_is_built_from_the_sentence_the_sheet_carries(
        self,
    ) -> None:
        for player_id, (_, sentence) in PERSONAL_ABILITIES.items():
            with self.subTest(player_id):
                self.assertEqual(
                    self.players[player_id]["advanced_ability"], sentence,
                    "the sheet's ability changed: look at the row again",
                )

    def test_every_ability_on_the_sheet_has_a_row(self) -> None:
        for player_id, player in self.players.items():
            if not player.get("advanced_ability"):
                continue
            with self.subTest(player_id):
                self.assertTrue(
                    player_id in PERSONAL_ABILITIES
                    or player_id in ADVANCED_SKILL_SENTENCES,
                    "a player has an ability the engine does not play",
                )

    def test_the_skill_sentences_are_the_ones_with_scores(self) -> None:
        for player_id, sentence in ADVANCED_SKILL_SENTENCES.items():
            with self.subTest(player_id):
                player = self.players[player_id]
                self.assertEqual(player["advanced_ability"], sentence)
                self.assertTrue(player["advanced_skills"])


class GateTests(unittest.TestCase):
    """Advanced mode alone, and never a tutorial (Law 21)."""

    def setUp(self) -> None:
        self.player_id = next(iter(PERSONAL_ABILITIES))
        self.ability = PERSONAL_ABILITIES[self.player_id][0]

    def test_only_advanced_mode_plays_them(self) -> None:
        for mode, expected in (
            (GameMode.TRAINING, False),
            (GameMode.BASIC, False),
            (GameMode.ADVANCED, True),
        ):
            with self.subTest(mode.value):
                self.assertEqual(
                    ENGINE.has_personal_ability(
                        build_game(mode=mode), self.player_id, self.ability,
                    ),
                    expected,
                )

    def test_a_tutorial_never_does(self) -> None:
        self.assertFalse(ENGINE.has_personal_ability(
            advanced(tutorial=True), self.player_id, self.ability,
        ))

    def test_the_second_sides_card_is_the_same_person(self) -> None:
        self.assertTrue(ENGINE.has_personal_ability(
            advanced(), duplicate_card_id(self.player_id), self.ability,
        ))

    def test_nobody_holds_an_ability_that_is_not_theirs(self) -> None:
        other = next(
            ability for ability in PersonalAbility
            if ability != self.ability
        )
        self.assertFalse(ENGINE.has_personal_ability(
            advanced(), self.player_id, other,
        ))


class AdvancedSkillTests(unittest.TestCase):
    def setUp(self) -> None:
        self.players = json.loads(
            PLAYERS_JSON.read_text(encoding="utf-8"),
        )["players"]
        self.scored = next(
            player_id for player_id, player in self.players.items()
            if player["advanced_skills"]
        )

    def test_advanced_mode_plays_the_advanced_scores(self) -> None:
        scores = self.players[self.scored]["advanced_skills"]
        skills = ENGINE.skills(advanced(), self.scored)
        for kind, value in scores.items():
            self.assertEqual(skills.of(kind), value)

    def test_other_modes_play_the_roles(self) -> None:
        player = ENGINE.get_player_definition(self.scored)
        profile = ENGINE.player_catalog.effective_profile(player)
        skills = ENGINE.skills(build_game(mode=GameMode.BASIC), self.scored)
        self.assertEqual(
            (skills.offense, skills.defense),
            (profile.offense, profile.defense),
        )

    def test_a_threshold_reads_the_advanced_defence(self) -> None:
        # A non-Cyborg's Exhausted line is their defensive skill.
        player_id = next(
            player_id for player_id, player in self.players.items()
            if "defense" in player["advanced_skills"]
            and player["species"] != SPECIES_CYBORG
        )
        self.assertEqual(
            ENGINE.exhaustion_threshold(advanced(), player_id),
            self.players[player_id]["advanced_skills"]["defense"],
        )


class CardSkillTests(unittest.TestCase):
    """
    The numbers the board's cards print (`RulesEngine.card_skills`):
    the advanced scores in an advanced game, for every card of both
    sides whose scores differ from the role's, and nothing otherwise.
    """

    def setUp(self) -> None:
        self.players = json.loads(
            PLAYERS_JSON.read_text(encoding="utf-8"),
        )["players"]

    def build(self, mode: GameMode):
        game = build_game(
            mode=mode,
            player_1_team=Team.FIRE_DEMONS,
            player_2_team=Team.CYBORGS,
        )
        return game, build_match(ENGINE, game)

    def test_an_advanced_game_prints_every_advanced_score(self) -> None:
        game, match = self.build(GameMode.ADVANCED)
        answer = ENGINE.card_skills(game, match)
        on_the_teams = {
            player_id
            for setup in (match.home, match.visiting)
            for player_id in (
                *setup.field_players,
                *setup.team_board.bench,
                *setup.team_board.back_bench,
            )
        }
        scored = {
            player_id for player_id in on_the_teams
            if self.players[catalog_player_id(player_id)]["advanced_skills"]
        }
        self.assertTrue(scored)
        self.assertEqual(set(answer), scored)
        for player_id in scored:
            skills = ENGINE.skills(game, player_id)
            self.assertEqual(
                answer[player_id], (skills.offense, skills.defense),
            )

    def test_no_other_mode_prints_anything_but_the_role(self) -> None:
        for mode in (GameMode.TRAINING, GameMode.BASIC):
            with self.subTest(mode.value):
                game, match = self.build(mode)
                self.assertEqual(ENGINE.card_skills(game, match), {})


class FireDemonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.game = advanced(player_1_team=Team.FIRE_DEMONS)
        self.match = build_match(ENGINE, self.game)
        self.demon = fielded_of_species(self.match, SPECIES_FIRE_DEMON)

    def ignite(self, face: int, second: int) -> IgnitedRoll:
        with mock.patch.object(ENGINE.rng, "randint", return_value=second):
            return ENGINE.ignite(self.game, self.demon, face)

    def test_sizzifizik_ignites_on_five_to_eight(self) -> None:
        self.assertFalse(self.ignite(5, 9).ignited)
        with holding(self.demon, PersonalAbility.WIDE_IGNITION):
            for face in (5, 6, 7, 8):
                with self.subTest(face=face):
                    self.assertTrue(self.ignite(face, 9).ignited)
            self.assertFalse(self.ignite(9, 9).ignited)
            self.assertIn("5 to 8", self.ignite(5, 9).rule)

    def test_blazebulk_never_burns(self) -> None:
        self.assertTrue(self.ignite(6, 2).burn)
        with holding(self.demon, PersonalAbility.ALWAYS_BLAZES):
            roll = self.ignite(6, 2)
        self.assertTrue(roll.blaze)
        self.assertEqual(roll.modifier, 2)
        self.assertIn("always blaze", roll.explain("Them"))

    def test_brightburn_s_burn_upgrades_nothing(self) -> None:
        winner = IgnitedRoll(face=3)
        with holding(self.demon, PersonalAbility.BRIGHT_BURN):
            burn = self.ignite(6, 2)
        self.assertTrue(burn.burn)
        self.assertFalse(
            ENGINE.volatile_raises_tier(self.game, winner, burn),
        )
        plain = self.ignite(6, 2)
        self.assertTrue(ENGINE.volatile_raises_tier(self.game, winner, plain))

    def test_brightburn_sheds_a_token_on_every_burn(self) -> None:
        self.match.exhaustion[self.demon] = 2
        with holding(self.demon, PersonalAbility.BRIGHT_BURN):
            burn = ENGINE.settle_burn(
                self.game, self.match, self.demon, self.ignite(6, 2),
            )
        self.assertEqual(burn.recovered, 1)
        self.assertEqual(self.match.exhaustion[self.demon], 1)
        self.assertIn("sheds 1 token", burn.explain("Them"))

    def test_a_burn_sheds_nothing_for_anybody_else(self) -> None:
        self.match.exhaustion[self.demon] = 2
        burn = ENGINE.settle_burn(
            self.game, self.match, self.demon, self.ignite(6, 2),
        )
        self.assertEqual(burn.recovered, 0)
        self.assertEqual(self.match.exhaustion[self.demon], 2)


class CyborgTests(unittest.TestCase):
    def setUp(self) -> None:
        self.game = advanced(player_1_team=Team.CYBORGS)
        self.match = build_match(ENGINE, self.game)
        self.cyborg = fielded_of_species(self.match, SPECIES_CYBORG)

    def test_bulwark_is_drained_at_ten(self) -> None:
        with holding(self.cyborg, PersonalAbility.HIGH_DRAIN_THRESHOLD):
            self.assertEqual(
                ENGINE.exhaustion_threshold(self.game, self.cyborg),
                BULWARK_DRAINED_AT - 1,
            )

    def test_voltus_overdrives_for_two(self) -> None:
        self.assertEqual(
            ENGINE.overdrive_cost(self.game, self.cyborg),
            OVERDRIVE_DRAIN_COST,
        )
        with holding(self.cyborg, PersonalAbility.CHEAP_OVERDRIVE):
            self.assertEqual(
                ENGINE.overdrive_cost(self.game, self.cyborg),
                VOLTUS_OVERDRIVE_DRAIN_COST,
            )

    def test_only_gearclaw_may_boost(self) -> None:
        self.assertEqual(
            ENGINE.boost_candidates(self.game, self.match, [self.cyborg]),
            [],
        )
        with holding(self.cyborg, PersonalAbility.BOOST):
            self.assertEqual(
                ENGINE.boost_candidates(
                    self.game, self.match, [self.cyborg],
                ),
                [self.cyborg],
            )

    def test_boost_drains_one_for_three(self) -> None:
        self.match.declare_boost(self.cyborg, CYBORG_DRAINED_AT - 1)
        self.assertEqual(
            self.match.exhaustion.get(self.cyborg, 0), BOOST_DRAIN_COST,
        )
        self.assertEqual(
            self.match.overdrive_modifier(self.cyborg), BOOST_BONUS,
        )
        self.assertEqual(
            ENGINE.overdrive_detail(self.match, self.cyborg),
            f"+{BOOST_BONUS} Boost",
        )
        self.match.consume_overdrive()
        self.assertEqual(self.match.overdrive_modifier(self.cyborg), 0)

    def test_boost_or_overdrive_never_both(self) -> None:
        self.match.declare_boost(self.cyborg, CYBORG_DRAINED_AT - 1)
        with self.assertRaises(RuleRefusal):
            self.match.declare_overdrive(self.cyborg, CYBORG_DRAINED_AT - 1)
        self.match.consume_overdrive()
        self.match.declare_overdrive(self.cyborg, CYBORG_DRAINED_AT - 1)
        with self.assertRaises(RuleRefusal):
            self.match.declare_boost(self.cyborg, CYBORG_DRAINED_AT - 1)
        self.assertEqual(
            self.match.overdrive_modifier(self.cyborg), OVERDRIVE_BONUS,
        )
        with holding(self.cyborg, PersonalAbility.BOOST):
            self.assertEqual(
                ENGINE.boost_candidates(
                    self.game, self.match, [self.cyborg],
                ),
                [],
            )

    def test_strider_charges_up_two(self) -> None:
        self.assertEqual(ENGINE.charge_up_amount(self.game, self.cyborg), 1)
        with holding(self.cyborg, PersonalAbility.EFFICIENT_RUN):
            self.assertEqual(
                ENGINE.charge_up_amount(self.game, self.cyborg),
                STRIDER_CHARGE_UP,
            )

    def test_strider_runs_back_one_token_cheaper(self) -> None:
        self.assertEqual(ENGINE.run_back_cost(self.game, self.cyborg, 3), 3)
        with holding(self.cyborg, PersonalAbility.EFFICIENT_RUN):
            for distance, cost in ((3, 2), (1, 0), (0, 0)):
                with self.subTest(distance=distance):
                    self.assertEqual(
                        ENGINE.run_back_cost(
                            self.game, self.cyborg, distance,
                        ),
                        cost,
                    )

    def test_synapse_s_overdriven_win_raises_the_tier(self) -> None:
        overdriven = {self.cyborg}
        self.assertFalse(
            ENGINE.overdrive_raises_tier(self.game, self.cyborg, overdriven),
        )
        with holding(self.cyborg, PersonalAbility.OVERDRIVE_UPGRADE):
            self.assertTrue(ENGINE.overdrive_raises_tier(
                self.game, self.cyborg, overdriven,
            ))
            self.assertFalse(ENGINE.overdrive_raises_tier(
                self.game, self.cyborg, set(),
            ))


class TelekineticTests(unittest.TestCase):
    def setUp(self) -> None:
        self.game = advanced(player_1_team=Team.TELEKINETICS)
        self.match = build_match(ENGINE, self.game)
        self.puller = fielded_of_species(
            self.match, SPECIES_TELEKINETIC, TeamSide.HOME,
        )

    def test_quillon_pulls_for_nothing(self) -> None:
        self.assertEqual(
            ENGINE.mind_pull_cost(self.game, self.puller),
            MIND_PULL_TOKEN_COST,
        )
        with holding(self.puller, PersonalAbility.FREE_PULL):
            self.assertEqual(ENGINE.mind_pull_cost(self.game, self.puller), 0)

    def test_spectra_adds_three(self) -> None:
        self.assertEqual(ENGINE.mind_pull_bonus(self.game, self.puller), 0)
        with holding(self.puller, PersonalAbility.STRONG_PULL):
            self.assertEqual(
                ENGINE.mind_pull_bonus(self.game, self.puller),
                SPECTRA_PULL_BONUS,
            )

    def test_noxar_is_offered_a_ball_beside_them(self) -> None:
        match = self.match
        # The visitors have the ball, so the home Telekinetic defends.
        match.ball.possession = TeamSide.VISITING
        board = match.board
        zone, index = board.meeple_position(self.puller)
        flat = board.flat_index(zone, index)
        beside = flat + 1 if flat + 1 < len(board.spaces_in_order()) else flat - 1
        beside_zone, beside_index = board.position_at_flat_index(beside)
        match.last_ball_path = [[beside_zone.value, beside_index]]
        match.last_ball_movers = []
        self.assertNotIn(
            self.puller, ENGINE.mind_pull_candidates(self.game, match),
        )
        with holding(self.puller, PersonalAbility.ADJACENT_PULL):
            self.assertIn(
                self.puller, ENGINE.mind_pull_candidates(self.game, match),
            )
            self.assertNotIn(
                self.puller,
                ENGINE.mind_pull_candidates(
                    build_game(mode=GameMode.BASIC), match,
                ),
            )


class GoopkeeperTests(unittest.TestCase):
    def test_a_full_block_counts_all_of_it_beyond_the_ball(self) -> None:
        player = ENGINE.get_player_definition(next(iter(PERSONAL_ABILITIES)))
        self.assertEqual(ShotDefender(player, 5, on_ball=False).value, 3)
        blocking = ShotDefender(player, 5, on_ball=False, full_block=True)
        self.assertEqual(blocking.value, 5)
        self.assertFalse(blocking.halved)


class AcidelTests(unittest.TestCase):
    """A won Pressure that would risk an own goal is a shot instead."""

    def setUp(self) -> None:
        self.fixture = pressure_fixtures.pressure_that_overshoots()
        self.match = self.fixture.match
        self.challenger = self.fixture.challenger_id

    def test_anybody_else_risks_the_own_goal(self) -> None:
        result = pressure_step(
            ENGINE, self.match, "pressure", advanced(),
        )
        self.assertIs(result.next.step, FollowOnStep.BEGIN_OWN_GOAL_ROLL)

    def test_acidel_takes_the_ball_and_the_shot(self) -> None:
        defending = self.match.defending_side()
        with holding(self.challenger, PersonalAbility.PRESSURE_SHOT):
            result = pressure_step(
                ENGINE, self.match, "pressure", advanced(),
            )
        self.assertIs(result.next.step, FollowOnStep.BEGIN_SHOOTER_CHOICE)
        self.assertEqual(
            result.next.kwargs["candidates"], [self.challenger],
        )
        self.assertEqual(self.match.ball.possession, defending)
        self.assertEqual(self.match.ball_carrier_id, self.challenger)
        self.assertEqual(self.match.ball.speed, 1)

    def test_not_outside_advanced_mode(self) -> None:
        with holding(self.challenger, PersonalAbility.PRESSURE_SHOT):
            result = pressure_step(
                ENGINE, self.match, "pressure",
                build_game(mode=GameMode.BASIC),
            )
        self.assertIs(result.next.step, FollowOnStep.BEGIN_OWN_GOAL_ROLL)


if __name__ == "__main__":
    unittest.main()
