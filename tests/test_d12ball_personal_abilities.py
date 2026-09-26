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
    SPECIES_OOZE,
    SPECIES_TELEKINETIC,
    RuleRefusal,
    ShotDefender,
    TeamSide,
    catalog_player_id,
    duplicate_card_id,
)
from d12ball.engine import IgnitedRoll
from d12ball.flow.effects import (
    ball_comes_to,
    high_pass_step,
    low_pass_step,
    pressure_step,
    run_onto_pass,
)
from d12ball.flow.arrivals import resolve_loose_ball
from d12ball.flow.injuries import injury_test_step
from d12ball.flow.result import FollowOnStep
from d12ball.flow.turn import (
    begin_maneuver_action_selection,
    join_the_ball_step,
)
from d12ball.flow.turnovers import begin_run_back, fly_step
from d12ball.prompts import PendingPrompt, PromptKind
from d12ball.game import GameMode, Team
from d12ball.personal_abilities import (
    ADVANCED_SKILL_SENTENCES,
    INFERNO_BALL_SPEED,
    SCORCHIT_FORCED_TEST_TOKENS,
    VORIX_BALL_SPEED,
    BOOST_BONUS,
    BOOST_DRAIN_COST,
    BULWARK_DRAINED_AT,
    PERSONAL_ABILITIES,
    SPECTRA_PULL_MINIMUM,
    STRIDER_CHARGE_UP,
    VOLTUS_OVERDRIVE_DRAIN_COST,
    QUANTOR_RUN_DRAIN,
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

    def test_strider_s_run_back_drains_one_at_most(self) -> None:
        self.assertEqual(ENGINE.run_back_cost(self.game, self.cyborg, 3), 3)
        with holding(self.cyborg, PersonalAbility.EFFICIENT_RUN):
            for distance, cost in ((3, 1), (1, 1), (0, 0)):
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

    def test_spectra_succeeds_on_eight(self) -> None:
        self.assertEqual(ENGINE.mind_pull_minimum(self.game, self.puller), 11)
        with holding(self.puller, PersonalAbility.STRONG_PULL):
            self.assertEqual(
                ENGINE.mind_pull_minimum(self.game, self.puller),
                SPECTRA_PULL_MINIMUM,
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


class EmberdashTests(unittest.TestCase):
    def setUp(self) -> None:
        self.game = advanced(player_1_team=Team.FIRE_DEMONS)
        self.match = build_match(ENGINE, self.game)
        self.match.active_player_id = self.match.home.field_players[0]
        self.handler = self.match.active_player_id

    def test_a_dribble_advance_goes_up_to_three(self) -> None:
        self.assertEqual(
            ENGINE.dribble_advance_distances(self.game, self.match), (1, 2),
        )
        with holding(self.handler, PersonalAbility.FREE_BURST):
            self.assertEqual(
                ENGINE.dribble_advance_distances(self.game, self.match),
                (1, 2, 3),
            )

    def test_a_dribble_burst_costs_nothing(self) -> None:
        self.assertGreater(
            ENGINE.dribble_burst_cost(self.match, 3, self.game), 0,
        )
        with holding(self.handler, PersonalAbility.FREE_BURST):
            self.assertEqual(
                ENGINE.dribble_burst_cost(self.match, 3, self.game), 0,
            )


class DiceGambitTests(unittest.TestCase):
    """Dravox and Hexis: a gambit they played resolves as one on the dice."""

    def setUp(self) -> None:
        self.game = advanced()
        self.match = build_match(ENGINE, self.game)
        self.player = self.match.home.field_players[0]
        catalog = ENGINE.maneuver_catalog
        self.gambit = next(
            key for key in ("intercept", "double_team", "clear")
            if catalog.get(key) is not None and catalog.get(key).is_gambit
        )
        self.basic = next(
            key for key in ("steal", "pressure", "deflect")
            if catalog.get(key) is not None
            and not catalog.get(key).is_gambit
        )

    def asked(self, ability, outcome, key) -> bool:
        with holding(self.player, ability):
            return ENGINE.dice_resolve_gambit(
                self.game, self.match, self.player, outcome, key,
            )

    def test_dravox_s_defensive_gambit_resolves(self) -> None:
        self.assertTrue(self.asked(
            PersonalAbility.DEFENSIVE_GAMBITS, "defense", self.gambit,
        ))

    def test_a_basic_card_is_not_upgraded(self) -> None:
        self.assertFalse(self.asked(
            PersonalAbility.DEFENSIVE_GAMBITS, "defense", self.basic,
        ))

    def test_each_reads_their_own_side_of_the_ball(self) -> None:
        self.assertFalse(self.asked(
            PersonalAbility.OFFENSIVE_GAMBITS, "defense", self.gambit,
        ))
        self.assertFalse(self.asked(
            PersonalAbility.DEFENSIVE_GAMBITS, "offense", self.gambit,
        ))

    def test_nobody_else_does(self) -> None:
        self.assertFalse(ENGINE.dice_resolve_gambit(
            self.game, self.match, self.player, "defense", self.gambit,
        ))


class QuantorTests(unittest.TestCase):
    """Quantor runs onto a teammate's pass (Law 21)."""

    def setUp(self) -> None:
        self.game = advanced()
        self.match = build_match(ENGINE, self.game)
        home = self.match.home.field_players
        self.passer, self.runner = home[0], home[-1]
        self.match.active_player_id = self.passer
        self.match.ball.possession = TeamSide.HOME
        self.match.set_ball_space(
            *self.match.board.meeple_position(self.passer),
        )

    def test_only_quantor_is_offered_the_run(self) -> None:
        self.assertEqual(
            ENGINE.pass_runner(self.game, self.match, (2, 3)), (None, ()),
        )
        with holding(self.runner, PersonalAbility.RUN_ON):
            runner, _ = ENGINE.pass_runner(self.game, self.match, (2, 3))
        self.assertEqual(runner, self.runner)

    def test_never_on_their_own_pass(self) -> None:
        with holding(self.passer, PersonalAbility.RUN_ON):
            runner, _ = ENGINE.pass_runner(self.game, self.match, (2, 3))
        self.assertIsNone(runner)

    def test_never_to_a_space_off_the_field(self) -> None:
        with holding(self.runner, PersonalAbility.RUN_ON):
            _, distances = ENGINE.pass_runner(
                self.game, self.match, (2, 3, 40),
            )
        self.assertNotIn(40, distances)

    def test_the_run_drains_three_and_takes_the_pass(self) -> None:
        with holding(self.runner, PersonalAbility.RUN_ON):
            _, distances = ENGINE.pass_runner(self.game, self.match, (3,))
            self.assertEqual(distances, (3,))
            before = self.match.exhaustion.get(self.runner, 0)
            run_onto_pass(ENGINE, self.game, self.match, self.runner, 3)
            result = high_pass_step(ENGINE, self.match, 3, self.runner)
        self.assertEqual(
            self.match.exhaustion.get(self.runner, 0) - before,
            QUANTOR_RUN_DRAIN,
        )
        self.assertEqual(
            self.match.board.meeple_position(self.runner),
            (self.match.ball.zone, self.match.ball.space_index),
        )
        self.assertEqual(self.match.ball_carrier_id, self.runner)
        self.assertIsNot(
            result.next.step, FollowOnStep.BEGIN_HIGH_PASS_CONTEST,
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


class ZorchTests(unittest.TestCase):
    """Zorch pays no token for a skill test or any re-roll (Law 21)."""

    def setUp(self) -> None:
        self.game = advanced()
        self.match = build_match(ENGINE, self.game)
        self.player = self.match.home.field_players[0]

    def test_every_test_is_free(self) -> None:
        self.assertEqual(ENGINE.re_roll_tokens(self.game, self.player), 1)
        self.assertEqual(
            ENGINE.skill_test_tokens(self.game, self.match, self.player), 1,
        )
        with holding(self.player, PersonalAbility.FREE_TESTS):
            self.assertEqual(
                ENGINE.re_roll_tokens(self.game, self.player), 0,
            )
            self.assertEqual(
                ENGINE.skill_test_tokens(self.game, self.match, self.player),
                0,
            )


class ScorchitTests(unittest.TestCase):
    """A card Scorchit lost goes to a skill test anyway (Law 21)."""

    def setUp(self) -> None:
        self.game = advanced()
        self.match = build_match(ENGINE, self.game)
        self.offense = self.match.home.field_players[0]
        self.defense = self.match.visiting.field_players[0]
        self.match.active_player_id = self.offense
        self.match.challenger_id = self.defense
        # Steal beats Low Pass on the cards: the offense lost.
        self.match.offense_maneuver = "low_pass"
        self.match.defense_maneuver = "steal"

    def test_anybody_else_loses_on_the_cards(self) -> None:
        self.assertEqual(
            ENGINE.settled_maneuver_winner(self.match, self.game), "steal",
        )
        self.assertIsNone(ENGINE.forced_test_by(self.game, self.match))

    def test_scorchit_forces_the_test_and_pays_for_it(self) -> None:
        with holding(self.offense, PersonalAbility.FORCES_THE_TEST):
            self.assertIsNone(
                ENGINE.settled_maneuver_winner(self.match, self.game),
            )
            forced_by = ENGINE.forced_test_by(self.game, self.match)
            self.assertEqual(forced_by, self.offense)
            self.assertEqual(
                ENGINE.skill_test_tokens(
                    self.game, self.match, self.offense, forced_by,
                ),
                SCORCHIT_FORCED_TEST_TOKENS,
            )
            self.assertEqual(
                ENGINE.skill_test_tokens(
                    self.game, self.match, self.defense, forced_by,
                ),
                0,
            )

    def test_not_off_a_card_they_won(self) -> None:
        with holding(self.defense, PersonalAbility.FORCES_THE_TEST):
            self.assertIsNone(ENGINE.forced_test_by(self.game, self.match))
            self.assertEqual(
                ENGINE.settled_maneuver_winner(self.match, self.game),
                "steal",
            )

    def test_an_injured_winner_s_test_is_the_injury_s(self) -> None:
        self.match.mark_injured(self.defense)
        with holding(self.offense, PersonalAbility.FORCES_THE_TEST):
            self.assertIsNone(ENGINE.forced_test_by(self.game, self.match))
            self.assertIsNone(
                ENGINE.settled_maneuver_winner(self.match, self.game),
            )

    def test_nothing_once_the_stealer_has_the_ball(self) -> None:
        # A beaten Skilled Pass owes the stealer a free Low Pass, which
        # makes them the handler: the cards now name one player twice,
        # and the settled maneuver must stay settled.
        self.match.offense_maneuver = "skilled_pass"
        self.match.defense_maneuver = "steal"
        self.match.active_player_id = self.defense
        with holding(self.defense, PersonalAbility.FORCES_THE_TEST):
            self.assertIsNone(ENGINE.forced_test_by(self.game, self.match))
            self.assertEqual(
                ENGINE.settled_maneuver_winner(self.match, self.game),
                "steal",
            )

    def test_the_gambits_follow_the_cards(self) -> None:
        # Scorchit wins the forced test: their card lost on the cards,
        # so it is no gambit's benefit and the winner on the cards
        # pays no cost.
        self.match.defense_maneuver = "intercept"
        with holding(self.offense, PersonalAbility.FORCES_THE_TEST):
            self.match.skill_test_winner = "low_pass"
            self.assertIsNone(ENGINE.gambit_cost(self.match, "low_pass"))


class UmbrikTests(unittest.TestCase):
    """Umbrik adds defensive skill where the sheet says (Law 21)."""

    def setUp(self) -> None:
        self.game = advanced()
        self.match = build_match(ENGINE, self.game)
        self.player = self.match.home.field_players[0]
        self.skills = ENGINE.skills(self.game, self.player)

    def asked(self, roll: str) -> int:
        return ENGINE.attacking_skill(
            self.game, self.match, self.player, roll,
        )

    def test_everybody_else_attacks_with_offense(self) -> None:
        self.match.offense_maneuver = "high_pass"
        self.assertEqual(self.asked("own_goal"), self.skills.offense)
        self.assertEqual(self.asked("skill_test"), self.skills.offense)

    def test_umbrik_uses_defense_on_the_three_rolls(self) -> None:
        with holding(self.player, PersonalAbility.DEFENSIVE_THROW):
            self.assertEqual(self.asked("own_goal"), self.skills.defense)
            self.match.offense_maneuver = "low_pass"
            self.assertEqual(self.asked("skill_test"), self.skills.offense)
            self.match.offense_maneuver = "high_pass"
            self.assertEqual(self.asked("skill_test"), self.skills.defense)
            self.assertEqual(self.asked("contest"), self.skills.offense)
            self.match.pending_loose_ball_is_high_pass = True
            self.assertEqual(self.asked("contest"), self.skills.defense)


class KindlefingerTests(unittest.TestCase):
    """Kindlefinger's injury check ignites (Law 21)."""

    def setUp(self) -> None:
        self.game = advanced(player_1_team=Team.FIRE_DEMONS)
        self.match = build_match(ENGINE, self.game)
        self.demon = fielded_of_species(self.match, SPECIES_FIRE_DEMON)

    def ignite(self, face: int, second: int) -> IgnitedRoll:
        with mock.patch.object(ENGINE.rng, "randint", return_value=second):
            return ENGINE.injury_ignite(self.game, self.demon, face)

    def test_nobody_else_s_check_ignites(self) -> None:
        self.assertFalse(self.ignite(6, 9).ignited)

    def test_a_blaze_clears_a_token_and_a_burn_adds_one(self) -> None:
        with holding(self.demon, PersonalAbility.INJURY_IGNITION):
            blaze = self.ignite(6, 9)
            burn = self.ignite(7, 2)
            self.assertFalse(self.ignite(5, 9).ignited)
            self.assertEqual(blaze.modifier, 9)
            self.assertEqual(burn.modifier, -2)
            self.match.exhaustion[self.demon] = 3
            ENGINE.settle_injury_ignite(
                self.game, self.match, self.demon, blaze,
            )
            self.assertEqual(self.match.exhaustion[self.demon], 2)
            ENGINE.settle_injury_ignite(
                self.game, self.match, self.demon, burn,
            )
            self.assertEqual(self.match.exhaustion[self.demon], 3)

    def test_an_injured_player_s_tokens_are_left_alone(self) -> None:
        with holding(self.demon, PersonalAbility.INJURY_IGNITION):
            burn = self.ignite(7, 2)
        self.match.mark_injured(self.demon)
        self.assertEqual(
            ENGINE.settle_injury_ignite(
                self.game, self.match, self.demon, burn,
            ),
            "",
        )
        self.assertEqual(self.match.exhaustion.get(self.demon, 0), 0)


class SlitheronTests(unittest.TestCase):
    """Slitheron takes a High Pass or loose ball without a roll."""

    def setUp(self) -> None:
        self.game = advanced()
        self.match = build_match(ENGINE, self.game)
        self.offense = self.match.home.field_players[0]
        self.defense = self.match.visiting.field_players[0]

    def winner(self):
        return ENGINE.contest_auto_winner(
            self.game, self.match, self.offense, self.defense,
        )

    def test_only_a_loose_ball_or_a_high_pass(self) -> None:
        with holding(self.defense, PersonalAbility.WINS_CONTESTS):
            self.match.pending_loose_ball_on_empty_space = False
            self.match.pending_loose_ball_is_high_pass = False
            self.assertIsNone(self.winner())
            self.match.pending_loose_ball_on_empty_space = True
            self.assertEqual(self.winner(), self.defense)
            self.match.pending_loose_ball_on_empty_space = False
            self.match.pending_loose_ball_is_high_pass = True
            self.assertEqual(self.winner(), self.defense)

    def test_nobody_else_and_not_against_each_other(self) -> None:
        self.match.pending_loose_ball_on_empty_space = True
        self.assertIsNone(self.winner())
        with mock.patch.dict(PERSONAL_ABILITIES, {
            catalog_player_id(self.offense): (
                PersonalAbility.WINS_CONTESTS, "test",
            ),
            catalog_player_id(self.defense): (
                PersonalAbility.WINS_CONTESTS, "test",
            ),
        }):
            self.assertIsNone(self.winner())


class SlitheronFlowTests(unittest.TestCase):
    """The contest itself, through `resolve_loose_ball`."""

    def test_the_ball_is_slitheron_s_and_nobody_rolls(self) -> None:
        game = advanced()
        match = build_match(ENGINE, game)
        offense = match.home.field_players[0]
        defense = match.visiting.field_players[0]
        match.pending_loose_ball = True
        match.pending_loose_ball_on_empty_space = True
        match.pending_loose_ball_distance = 1
        match.loose_ball_offense_player = offense
        match.loose_ball_defense_player = defense
        with holding(defense, PersonalAbility.WINS_CONTESTS):
            result = resolve_loose_ball(ENGINE, game, match)
        self.assertIs(result.next.step, FollowOnStep.BEGIN_RUN_BACK)
        self.assertTrue(result.next.kwargs["turnover_occurred"])
        self.assertEqual(match.ball_carrier_id, defense)
        self.assertEqual(match.ball.possession, TeamSide.VISITING)
        self.assertFalse(match.pending_loose_ball)
        self.assertIn("without a roll", result.narration[0])


class KindlefingerFlowTests(unittest.TestCase):
    """The injury check itself, through `injury_test_step`."""

    def test_a_blaze_saves_them_and_clears_a_token(self) -> None:
        game = advanced(player_1_team=Team.FIRE_DEMONS)
        match = build_match(ENGINE, game)
        demon = fielded_of_species(match, SPECIES_FIRE_DEMON)
        match.exhaustion[demon] = 8
        match.pending_injury_tests = [demon]
        with holding(demon, PersonalAbility.INJURY_IGNITION), \
                mock.patch.object(ENGINE.rng, "randint", side_effect=[6, 9]):
            roll, result = injury_test_step(ENGINE, game, match, demon)
        # 6 + 9 = 15 beats 8 tokens, where a plain 6 would not have.
        self.assertTrue(roll.safe)
        self.assertNotIn(demon, match.injured)
        self.assertEqual(match.exhaustion[demon], 7)
        self.assertIn("ignites", result.narration[0])


class ShotDefenseTests(unittest.TestCase):
    """Goopkeeper and Flickerwing, in the score attempt (Law 21)."""

    def setUp(self) -> None:
        self.game = advanced()
        self.match = build_match(ENGINE, self.game)
        match = self.match
        match.ball.possession = TeamSide.HOME
        # The ball on flat 4, a home shooter on it; home attacks toward
        # flat 6.
        self.shooter = match.home.field_players[0]
        self.at(self.shooter, 4)
        match.set_ball_space(*match.board.position_at_flat_index(4))
        match.active_player_id = self.shooter
        visitors = match.visiting.field_players
        for player_id in visitors:
            self.at(player_id, 0)
        self.on_ball, self.beyond, self.behind = visitors[:3]
        self.at(self.on_ball, 4)
        self.at(self.beyond, 6)
        self.at(self.behind, 2)

    def at(self, player_id: str, flat: int) -> None:
        self.match.move_meeple(
            player_id, *self.match.board.position_at_flat_index(flat),
        )

    def defending(self) -> dict:
        return {
            defender.player.player_id: defender
            for defender in ENGINE.intervening_defenders(
                self.match, self.game,
            )
        }

    def test_the_ordinary_wall(self) -> None:
        wall = self.defending()
        self.assertEqual(set(wall), {self.on_ball, self.beyond})
        self.assertTrue(wall[self.beyond].halved)

    def test_goopkeeper_counts_from_behind_the_ball(self) -> None:
        with holding(self.behind, PersonalAbility.FULL_BLOCK):
            wall = self.defending()
        self.assertIn(self.behind, wall)
        self.assertFalse(wall[self.behind].halved)
        self.assertEqual(
            wall[self.behind].value,
            ENGINE.skills(self.game, self.behind).defense,
        )

    def test_flickerwing_s_set_up_is_shot_past_the_wall(self) -> None:
        self.match.pending_shot_is_set_up = True
        with holding(self.shooter, PersonalAbility.CLEAR_SHOT):
            self.assertEqual(set(self.defending()), {self.on_ball})
            with holding(self.beyond, PersonalAbility.FULL_BLOCK):
                self.assertEqual(
                    set(self.defending()), {self.on_ball, self.beyond},
                )
            # An ordinary shot is unchanged.
            self.match.pending_shot_is_set_up = False
            self.assertEqual(
                set(self.defending()), {self.on_ball, self.beyond},
            )


class SpritzTests(unittest.TestCase):
    """Spritz has the Telekinetics' Smooth (Law 21)."""

    def setUp(self) -> None:
        self.game = advanced(player_1_team=Team.OOZES)
        self.match = build_match(ENGINE, self.game)
        self.taker = fielded_of_species(
            self.match, SPECIES_OOZE, self.match.ball.possession,
        )
        origin = self.match.board.flat_index(
            self.match.ball.zone, self.match.ball.space_index,
        )
        zone, index = self.match.board.position_at_flat_index(origin + 1)
        self.match.board.place_meeple(self.taker, zone, index)
        self.match.set_ball_space(zone, index)

    def test_only_spritz_may_take_it_over(self) -> None:
        self.assertEqual(ENGINE.smooth_candidates(self.game, self.match), [])
        with holding(self.taker, PersonalAbility.SMOOTH):
            self.assertEqual(
                ENGINE.smooth_candidates(self.game, self.match),
                [self.taker],
            )
            self.assertEqual(
                ENGINE.smooth_candidates(
                    build_game(
                        mode=GameMode.BASIC, player_1_team=Team.OOZES,
                    ),
                    self.match,
                ),
                [],
            )


class LongPassTests(unittest.TestCase):
    """Vorix's pass of 3 and Zytheris's catch (Law 21)."""

    def setUp(self) -> None:
        self.game = advanced()
        self.match = build_match(ENGINE, self.game)
        self.match.ball.possession = TeamSide.HOME

    def pass_from(self, passer_flat: int, receiver_flat: int):
        match = self.match
        home = match.home.field_players
        passer, receiver = home[0], home[1]
        for player_id in home:
            match.move_meeple(
                player_id, *match.board.position_at_flat_index(0),
            )
        match.move_meeple(
            passer, *match.board.position_at_flat_index(passer_flat),
        )
        match.move_meeple(
            receiver, *match.board.position_at_flat_index(receiver_flat),
        )
        match.set_ball_space(*match.board.meeple_position(passer))
        match.active_player_id = passer
        match.ball.speed = 1
        return passer, receiver

    def test_anybody_else_s_pass_of_three_is_contested(self) -> None:
        self.pass_from(2, 5)
        result = high_pass_step(ENGINE, self.match, 3, game=self.game)
        self.assertIs(
            result.next.step, FollowOnStep.BEGIN_HIGH_PASS_CONTEST,
        )

    def test_vorix_sets_up_at_twelve(self) -> None:
        passer, receiver = self.pass_from(2, 5)
        with holding(passer, PersonalAbility.LONG_SET_UP):
            result = high_pass_step(ENGINE, self.match, 3, game=self.game)
        self.assertIs(
            result.next.step, FollowOnStep.OFFER_SCORING_ATTEMPT_CHOICE,
        )
        self.assertEqual(result.next.kwargs["shooter_id"], receiver)
        self.assertEqual(self.match.ball.speed, VORIX_BALL_SPEED)

    def test_vorix_out_of_range_is_simply_received(self) -> None:
        passer, receiver = self.pass_from(0, 3)
        with holding(passer, PersonalAbility.LONG_SET_UP):
            result = high_pass_step(ENGINE, self.match, 3, game=self.game)
        self.assertIs(
            result.next.step, FollowOnStep.FINISH_MANEUVER_RESOLUTION,
        )
        self.assertEqual(self.match.ball_carrier_id, receiver)
        self.assertEqual(self.match.ball.speed, VORIX_BALL_SPEED)

    def test_zytheris_shoots_in_place_of_the_contest(self) -> None:
        _, receiver = self.pass_from(2, 5)
        with holding(receiver, PersonalAbility.SHOOTS_OFF_ANY_PASS):
            result = high_pass_step(ENGINE, self.match, 3, game=self.game)
        self.assertIs(
            result.next.step, FollowOnStep.OFFER_SCORING_ATTEMPT_CHOICE,
        )
        self.assertTrue(result.next.kwargs["contest_on_decline"])
        self.assertEqual(result.next.kwargs["shooter_id"], receiver)

    def test_zytheris_shoots_off_a_low_pass(self) -> None:
        _, receiver = self.pass_from(3, 4)
        plain = low_pass_step(ENGINE, self.match, 1, game=self.game)
        self.assertIs(
            plain.next.step, FollowOnStep.FINISH_MANEUVER_RESOLUTION,
        )
        self.pass_from(3, 4)
        with holding(receiver, PersonalAbility.SHOOTS_OFF_ANY_PASS):
            result = low_pass_step(ENGINE, self.match, 1, game=self.game)
        self.assertIs(
            result.next.step, FollowOnStep.OFFER_SCORING_ATTEMPT_CHOICE,
        )
        self.assertEqual(result.next.kwargs["shooter_id"], receiver)


class BallComesToTests(unittest.TestCase):
    """Inferno lights the ball and Pulsar charges up on it (Law 21)."""

    def setUp(self) -> None:
        self.game = advanced()
        self.match = build_match(ENGINE, self.game)
        self.player = self.match.home.field_players[0]
        self.other = self.match.home.field_players[1]
        self.match.set_ball_carrier(self.other)
        self.match.ball.speed = 3

    def comes(self) -> list[str]:
        before = ENGINE.ball_holder(self.match)
        self.match.set_ball_carrier(self.player)
        return ball_comes_to(ENGINE, self.game, self.match, before)

    def test_nothing_for_anybody_else(self) -> None:
        self.assertEqual(self.comes(), [])
        self.assertEqual(self.match.ball.speed, 3)

    def test_inferno_lights_the_ball(self) -> None:
        with holding(self.player, PersonalAbility.LIGHTS_THE_BALL):
            self.assertTrue(self.comes())
        self.assertEqual(self.match.ball.speed, INFERNO_BALL_SPEED)

    def test_only_when_it_comes_to_them(self) -> None:
        self.match.set_ball_carrier(self.player)
        with holding(self.player, PersonalAbility.LIGHTS_THE_BALL):
            self.assertEqual(
                ball_comes_to(ENGINE, self.game, self.match, self.player),
                [],
            )
        self.assertEqual(self.match.ball.speed, 3)

    def test_pulsar_charges_up(self) -> None:
        self.match.exhaustion[self.player] = 2
        with holding(self.player, PersonalAbility.CHARGES_ON_THE_BALL):
            self.assertTrue(self.comes())
        self.assertEqual(self.match.exhaustion[self.player], 1)


class GlompexTests(unittest.TestCase):
    """Glompex steps onto the ball before the cards (Law 21)."""

    def setUp(self) -> None:
        # Only the player a test hands the ability to holds it: the
        # deal fields the real Glompex, who would be asked as well.
        cleared = mock.patch.dict(PERSONAL_ABILITIES, {}, clear=True)
        cleared.start()
        self.addCleanup(cleared.stop)
        self.game = advanced()
        match = self.match = build_match(ENGINE, self.game)
        match.ball.possession = TeamSide.HOME
        home = match.home.field_players
        self.handler, self.joiner = home[0], home[1]
        self.challenger = match.visiting.field_players[0]
        for player_id, flat in (
            (self.handler, 3), (self.challenger, 3), (self.joiner, 2),
        ):
            match.move_meeple(
                player_id, *match.board.position_at_flat_index(flat),
            )
        match.set_ball_space(*match.board.position_at_flat_index(3))
        match.active_player_id = self.handler
        match.challenger_id = self.challenger

    def test_only_glompex_beside_the_ball_against_a_challenge(self) -> None:
        self.assertEqual(ENGINE.join_candidates(self.game, self.match), [])
        with holding(self.joiner, PersonalAbility.JOINS_THE_BALL):
            self.assertEqual(
                ENGINE.join_candidates(self.game, self.match),
                [self.joiner],
            )
            self.match.move_meeple(
                self.joiner, *self.match.board.position_at_flat_index(1),
            )
            self.assertEqual(
                ENGINE.join_candidates(self.game, self.match), [],
            )

    def test_asked_before_the_cards_once(self) -> None:
        with holding(self.joiner, PersonalAbility.JOINS_THE_BALL):
            asked = begin_maneuver_action_selection(
                ENGINE, self.game, self.match,
            )
            self.assertIsInstance(asked.next, PendingPrompt)
            self.assertIs(asked.next.kind, PromptKind.JOIN_THE_BALL)
            result = join_the_ball_step(
                ENGINE, self.game, self.match, self.joiner, True,
            )
            self.assertIs(
                result.next.step, FollowOnStep.SEND_MANEUVER_ACTION_PROMPT,
            )
            # Answered: the cards come next, not the offer again.
            again = begin_maneuver_action_selection(
                ENGINE, self.game, self.match,
            )
        self.assertIs(
            again.next.step, FollowOnStep.SEND_MANEUVER_ACTION_PROMPT,
        )
        self.assertEqual(
            self.match.board.meeple_position(self.joiner),
            (self.match.ball.zone, self.match.ball.space_index),
        )
        self.assertEqual(self.match.exhaustion[self.joiner], 1)

    def test_staying_moves_nobody(self) -> None:
        where = self.match.board.meeple_position(self.joiner)
        self.match.pending_join = [self.joiner]
        join_the_ball_step(ENGINE, self.game, self.match, self.joiner, False)
        self.assertEqual(self.match.board.meeple_position(self.joiner), where)
        self.assertEqual(self.match.exhaustion.get(self.joiner, 0), 0)


class ZenithTests(unittest.TestCase):
    """Zenith flies before a steal's run back (Law 21)."""

    def setUp(self) -> None:
        cleared = mock.patch.dict(PERSONAL_ABILITIES, {}, clear=True)
        cleared.start()
        self.addCleanup(cleared.stop)
        self.game = advanced()
        match = self.match = build_match(ENGINE, self.game)
        self.flier = match.visiting.field_players[0]
        match.set_ball_carrier(match.home.field_players[0])
        match.last_ball_path = []

    def test_asked_first_then_left_out_of_the_run_back(self) -> None:
        match = self.match
        here = match.board.flat_index(*match.board.meeple_position(self.flier))
        target = 0 if here > 2 else 6
        zone, index = match.board.position_at_flat_index(target)
        with holding(self.flier, PersonalAbility.FLY):
            asked = begin_run_back(ENGINE, self.game, match)
            self.assertIs(asked.next.kind, PromptKind.FLY)
            flown = fly_step(
                ENGINE, self.game, match, self.flier, (zone, index),
            )
            self.assertIs(flown.next.step, FollowOnStep.BEGIN_RUN_BACK)
            self.assertEqual(
                match.exhaustion[self.flier], abs(target - here),
            )
            self.assertIn(self.flier, match.run_back_flown)
            self.assertNotIn(
                self.flier,
                ENGINE.run_back_displaced(match, match.visiting.side),
            )
            resumed = begin_run_back(
                ENGINE, self.game, match, **flown.next.kwargs,
            )
        self.assertIs(resumed.next.step, FollowOnStep.ANNOUNCE_RUN_BACK)

    def test_nobody_else_and_never_the_ball_s_holder(self) -> None:
        self.assertEqual(ENGINE.fly_candidates(self.game, self.match), [])
        holder = self.flier
        self.match.set_ball_carrier(holder)
        with holding(holder, PersonalAbility.FLY):
            self.assertEqual(
                ENGINE.fly_candidates(self.game, self.match), [],
            )

    def test_not_a_new_play(self) -> None:
        with holding(self.flier, PersonalAbility.FLY):
            result = begin_run_back(
                ENGINE, self.game, self.match, new_play=True,
            )
        self.assertNotIsInstance(result.next, PendingPrompt)


if __name__ == "__main__":
    unittest.main()
