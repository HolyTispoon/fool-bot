"""
The special abilities and the advanced skill scores (Law 21 of
docs/living-rules.md; "Special abilities" in
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
    SHOT_AS_ON_BALL_NOTE,
    SHOT_PASSED_NOTE,
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
from d12ball.dice_brief import (
    maneuver_challenge_brief,
    maneuver_challenge_notes,
    score_attempt_brief,
)
from d12ball.engine import IgnitedRoll
from d12ball.flow.effects import (
    answer_passer_advance,
    ball_comes_to,
    high_pass_step,
    low_pass_step,
    pressure_step,
    run_onto_pass,
)
from d12ball.flow.arrivals import resolve_loose_ball
from d12ball.flow.injuries import injury_test_step
from d12ball.flow.rolls import (
    after_the_contest,
    score_score_attempt,
    score_skill_test,
)
from d12ball.flow.result import FollowOnStep
from d12ball.flow.turn import (
    begin_maneuver_action_selection,
    force_test_step,
    join_the_ball_step,
    resolve_maneuver,
)
from d12ball.flow.turnovers import begin_run_back, fly_step
from d12ball.prompts import PendingPrompt, PromptKind
from d12ball.formatting import player_with_role
from d12ball.game import GameMode, Team
from d12ball.special_abilities import (
    ADVANCED_SKILL_SENTENCES,
    CLEAR_SHOT_CONDITION,
    FULL_BLOCK_CONDITION,
    INFERNO_BALL_SPEED,
    SCORCHIT_FORCED_TEST_TOKENS,
    VISCOR_MERGE_BONUS,
    VORIX_BALL_SPEED,
    BOOST_BONUS,
    BOOST_DRAIN_COST,
    BULWARK_DRAINED_AT,
    SPECIAL_ABILITIES,
    SPECTRA_PULL_MINIMUM,
    STRIDER_CHARGE_UP,
    VOLTUS_OVERDRIVE_DRAIN_COST,
    QUANTOR_RUN_DRAIN,
    SpecialAbility,
    without_shot_condition,
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
def holding(player_id: str, ability: SpecialAbility):
    """Give `player_id`'s person this ability for the test's length."""
    with mock.patch.dict(
        SPECIAL_ABILITIES,
        {catalog_player_id(player_id): (ability, "test")},
    ):
        yield


def advanced(**overrides):
    return build_game(mode=GameMode.ADVANCED, **overrides)


def role_scores():
    """Every player on their role's scores, since a raised score bears
    on its own (`special_bears`) and the roster is the author's data."""
    skills = ENGINE.skills
    return mock.patch.object(
        ENGINE, "skills", lambda game, player_id: skills(None, player_id),
    )


def reminder(game, player_id: str) -> str:
    """A stand-in for the card's sentence, so a test does not depend on
    which players the sheet gives one."""
    return f"the line of {player_id}"


class TableTests(unittest.TestCase):
    """The table against the sheet's own sentences."""

    def setUp(self) -> None:
        self.players = json.loads(
            PLAYERS_JSON.read_text(encoding="utf-8"),
        )["players"]

    def test_every_row_is_built_from_the_sentence_the_sheet_carries(
        self,
    ) -> None:
        for player_id, (_, sentence) in SPECIAL_ABILITIES.items():
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
                    player_id in SPECIAL_ABILITIES
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
        self.player_id = next(iter(SPECIAL_ABILITIES))
        self.ability = SPECIAL_ABILITIES[self.player_id][0]

    def test_only_advanced_mode_plays_them(self) -> None:
        for mode, expected in (
            (GameMode.TRAINING, False),
            (GameMode.STANDARD, False),
            (GameMode.ADVANCED, True),
        ):
            with self.subTest(mode.value):
                self.assertEqual(
                    ENGINE.has_special_ability(
                        build_game(mode=mode), self.player_id, self.ability,
                    ),
                    expected,
                )

    def test_a_tutorial_never_does(self) -> None:
        self.assertFalse(ENGINE.has_special_ability(
            advanced(tutorial=True), self.player_id, self.ability,
        ))

    def test_the_second_sides_card_is_the_same_person(self) -> None:
        self.assertTrue(ENGINE.has_special_ability(
            advanced(), duplicate_card_id(self.player_id), self.ability,
        ))

    def test_nobody_holds_an_ability_that_is_not_theirs(self) -> None:
        other = next(
            ability for ability in SpecialAbility
            if ability != self.ability
        )
        self.assertFalse(ENGINE.has_special_ability(
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
        skills = ENGINE.skills(build_game(mode=GameMode.STANDARD), self.scored)
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
        for mode in (GameMode.TRAINING, GameMode.STANDARD):
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
        with holding(self.demon, SpecialAbility.WIDE_IGNITION):
            for face in (5, 6, 7, 8):
                with self.subTest(face=face):
                    self.assertTrue(self.ignite(face, 9).ignited)
            self.assertFalse(self.ignite(9, 9).ignited)
            self.assertIn("5 to 8", self.ignite(5, 9).rule)

    def test_blazebulk_never_burns(self) -> None:
        self.assertTrue(self.ignite(6, 2).burn)
        with holding(self.demon, SpecialAbility.ALWAYS_BLAZES):
            roll = self.ignite(6, 2)
        self.assertTrue(roll.blaze)
        self.assertEqual(roll.modifier, 2)
        self.assertIn("always blaze", roll.explain("Them"))

    def test_brightburn_s_burn_upgrades_nothing(self) -> None:
        winner = IgnitedRoll(face=3)
        with holding(self.demon, SpecialAbility.BRIGHT_BURN):
            burn = self.ignite(6, 2)
        self.assertTrue(burn.burn)
        self.assertFalse(
            ENGINE.volatile_raises_tier(self.game, winner, burn),
        )
        plain = self.ignite(6, 2)
        self.assertTrue(ENGINE.volatile_raises_tier(self.game, winner, plain))

    def test_brightburn_sheds_a_token_on_every_burn(self) -> None:
        self.match.exhaustion[self.demon] = 2
        with holding(self.demon, SpecialAbility.BRIGHT_BURN):
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
        with holding(self.cyborg, SpecialAbility.HIGH_DRAIN_THRESHOLD):
            self.assertEqual(
                ENGINE.exhaustion_threshold(self.game, self.cyborg),
                BULWARK_DRAINED_AT - 1,
            )

    def test_voltus_overdrives_for_two(self) -> None:
        self.assertEqual(
            ENGINE.overdrive_cost(self.game, self.cyborg),
            OVERDRIVE_DRAIN_COST,
        )
        with holding(self.cyborg, SpecialAbility.CHEAP_OVERDRIVE):
            self.assertEqual(
                ENGINE.overdrive_cost(self.game, self.cyborg),
                VOLTUS_OVERDRIVE_DRAIN_COST,
            )

    def test_only_gearclaw_may_boost(self) -> None:
        self.assertEqual(
            ENGINE.boost_candidates(self.game, self.match, [self.cyborg]),
            [],
        )
        with holding(self.cyborg, SpecialAbility.BOOST):
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
            ENGINE.overdrive_details(self.match, self.cyborg),
            [f"+{BOOST_BONUS} Boost"],
        )
        self.match.consume_overdrive()
        self.assertEqual(self.match.overdrive_modifier(self.cyborg), 0)

    def test_boost_and_overdrive_stack_on_one_roll(self) -> None:
        with holding(self.cyborg, SpecialAbility.BOOST):
            self.match.declare_overdrive(self.cyborg, CYBORG_DRAINED_AT - 1)
            # An Overdrive leaves Boost open on the same roll, and the
            # other way round (Law 21) ...
            self.assertEqual(
                ENGINE.boost_candidates(
                    self.game, self.match, [self.cyborg],
                ),
                [self.cyborg],
            )
            self.match.declare_boost(self.cyborg, CYBORG_DRAINED_AT - 1)
            self.assertEqual(
                self.match.exhaustion.get(self.cyborg, 0),
                OVERDRIVE_DRAIN_COST + BOOST_DRAIN_COST,
            )
            self.assertEqual(
                self.match.overdrive_modifier(self.cyborg),
                OVERDRIVE_BONUS + BOOST_BONUS,
            )
            self.assertEqual(
                ENGINE.overdrive_details(self.match, self.cyborg),
                [f"+{OVERDRIVE_BONUS} Overdrive", f"+{BOOST_BONUS} Boost"],
            )
            # ... but each is once per roll.
            self.assertEqual(
                ENGINE.boost_candidates(
                    self.game, self.match, [self.cyborg],
                ),
                [],
            )
            self.assertEqual(
                ENGINE.overdrive_candidates(
                    self.game, self.match, [self.cyborg],
                ),
                [],
            )
            with self.assertRaises(RuleRefusal):
                self.match.declare_boost(self.cyborg, CYBORG_DRAINED_AT - 1)
            with self.assertRaises(RuleRefusal):
                self.match.declare_overdrive(
                    self.cyborg, CYBORG_DRAINED_AT - 1,
                )
            # A re-rolled tie is a fresh roll: both are open again.
            self.match.consume_overdrive()
            self.assertEqual(self.match.overdrive_modifier(self.cyborg), 0)
            self.assertEqual(
                ENGINE.boost_candidates(
                    self.game, self.match, [self.cyborg],
                ),
                [self.cyborg],
            )

    def test_boost_first_leaves_overdrive_open(self) -> None:
        self.match.declare_boost(self.cyborg, CYBORG_DRAINED_AT - 1)
        self.assertEqual(
            ENGINE.overdrive_candidates(self.game, self.match, [self.cyborg]),
            [self.cyborg],
        )

    def test_strider_charges_up_two(self) -> None:
        self.assertEqual(ENGINE.charge_up_amount(self.game, self.cyborg), 1)
        with holding(self.cyborg, SpecialAbility.EFFICIENT_RUN):
            self.assertEqual(
                ENGINE.charge_up_amount(self.game, self.cyborg),
                STRIDER_CHARGE_UP,
            )

    def test_strider_s_run_back_drains_one_at_most(self) -> None:
        self.assertEqual(ENGINE.run_back_cost(self.game, self.cyborg, 3), 3)
        with holding(self.cyborg, SpecialAbility.EFFICIENT_RUN):
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
        with holding(self.cyborg, SpecialAbility.OVERDRIVE_UPGRADE):
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
        with holding(self.puller, SpecialAbility.FREE_PULL):
            self.assertEqual(ENGINE.mind_pull_cost(self.game, self.puller), 0)

    def test_spectra_succeeds_on_nine(self) -> None:
        self.assertEqual(ENGINE.mind_pull_minimum(self.game, self.puller), 11)
        with holding(self.puller, SpecialAbility.STRONG_PULL):
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
        with holding(self.puller, SpecialAbility.ADJACENT_PULL):
            self.assertIn(
                self.puller, ENGINE.mind_pull_candidates(self.game, match),
            )
            self.assertNotIn(
                self.puller,
                ENGINE.mind_pull_candidates(
                    build_game(mode=GameMode.STANDARD), match,
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
        with holding(self.handler, SpecialAbility.FREE_BURST):
            self.assertEqual(
                ENGINE.dribble_advance_distances(self.game, self.match),
                (1, 2, 3),
            )

    def test_a_dribble_burst_costs_nothing(self) -> None:
        self.assertGreater(
            ENGINE.dribble_burst_cost(self.match, 3, self.game), 0,
        )
        with holding(self.handler, SpecialAbility.FREE_BURST):
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
            SpecialAbility.DEFENSIVE_GAMBITS, "defense", self.gambit,
        ))

    def test_a_basic_card_is_not_upgraded(self) -> None:
        self.assertFalse(self.asked(
            SpecialAbility.DEFENSIVE_GAMBITS, "defense", self.basic,
        ))

    def test_each_reads_their_own_side_of_the_ball(self) -> None:
        self.assertFalse(self.asked(
            SpecialAbility.OFFENSIVE_GAMBITS, "defense", self.gambit,
        ))
        self.assertFalse(self.asked(
            SpecialAbility.DEFENSIVE_GAMBITS, "offense", self.gambit,
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
        with holding(self.runner, SpecialAbility.RUN_ON):
            runner, _ = ENGINE.pass_runner(self.game, self.match, (2, 3))
        self.assertEqual(runner, self.runner)

    def test_never_on_their_own_pass(self) -> None:
        with holding(self.passer, SpecialAbility.RUN_ON):
            runner, _ = ENGINE.pass_runner(self.game, self.match, (2, 3))
        self.assertIsNone(runner)

    def test_never_to_a_space_off_the_field(self) -> None:
        with holding(self.runner, SpecialAbility.RUN_ON):
            _, distances = ENGINE.pass_runner(
                self.game, self.match, (2, 3, 40),
            )
        self.assertNotIn(40, distances)

    def test_the_run_drains_three_and_takes_the_pass(self) -> None:
        with holding(self.runner, SpecialAbility.RUN_ON):
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
        player = ENGINE.get_player_definition(next(iter(SPECIAL_ABILITIES)))
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
        with holding(self.challenger, SpecialAbility.PRESSURE_SHOT):
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
        with holding(self.challenger, SpecialAbility.PRESSURE_SHOT):
            result = pressure_step(
                ENGINE, self.match, "pressure",
                build_game(mode=GameMode.STANDARD),
            )
        self.assertIs(result.next.step, FollowOnStep.BEGIN_OWN_GOAL_ROLL)


class ZorchTests(unittest.TestCase):
    """Zorch adds the ball speed modifier to every roll they make, once
    (Law 21)."""

    def setUp(self) -> None:
        self.game = advanced()
        self.match = build_match(ENGINE, self.game)
        self.offense = self.match.home.field_players[0]
        self.defense = self.match.visiting.field_players[0]
        self.match.ball.speed = 7  # Zorch's +3: half of 7, rounded down
        self.match.offense_maneuver = "low_pass"
        self.match.defense_maneuver = "pressure"

    def skill_test(self):
        with mock.patch.object(ENGINE.rng, "randint", return_value=5):
            _, offense, defense, _, _ = score_skill_test(
                ENGINE, self.game, self.match,
                ENGINE.get_player_definition(self.offense),
                ENGINE.get_player_definition(self.defense),
            )
        return offense, defense

    def test_nobody_else_adds_it(self) -> None:
        self.assertEqual(
            ENGINE.speed_roll_bonus(self.game, self.match, self.offense),
            (0, ""),
        )

    def test_it_is_half_the_speed_and_nothing_at_speed_one(self) -> None:
        with holding(self.offense, SpecialAbility.SPEED_ROLLS):
            self.assertEqual(
                ENGINE.speed_roll_bonus(self.game, self.match, self.offense),
                (3, "+3 ball speed modifier"),
            )
            self.match.ball.speed = 1
            self.assertEqual(
                ENGINE.speed_roll_bonus(self.game, self.match, self.offense),
                (0, ""),
            )

    def test_only_in_advanced_mode(self) -> None:
        game = build_game(mode=GameMode.STANDARD)
        with holding(self.offense, SpecialAbility.SPEED_ROLLS):
            self.assertEqual(
                ENGINE.speed_roll_bonus(game, self.match, self.offense),
                (0, ""),
            )

    def test_a_skill_test_adds_it_on_either_side(self) -> None:
        plain = self.skill_test()
        with holding(self.offense, SpecialAbility.SPEED_ROLLS):
            attacking = self.skill_test()
        with holding(self.defense, SpecialAbility.SPEED_ROLLS):
            defending = self.skill_test()
        self.assertEqual(attacking, (plain[0] + 3, plain[1]))
        self.assertEqual(defending, (plain[0], plain[1] + 3))

    def test_a_steal_already_adds_it_so_zorch_adds_nothing_more(self) -> None:
        self.match.defense_maneuver = "steal"
        plain = self.skill_test()
        with holding(self.defense, SpecialAbility.SPEED_ROLLS):
            self.assertEqual(self.skill_test(), plain)

    def test_an_injury_check_is_rolled_bare(self) -> None:
        """
        Law 15.3.4 (the author, 2026-10-02): nothing modifies an injury
        check but an ability that names it, and Zorch's does not -- 3
        against 4 tokens fails with the ball at a speed that gives
        every other roll of theirs +3.
        """
        self.match.exhaustion[self.offense] = 4
        with holding(self.offense, SpecialAbility.SPEED_ROLLS), \
                mock.patch.object(ENGINE.rng, "randint", return_value=3):
            zorch, result = injury_test_step(
                ENGINE, self.game, self.match, self.offense,
            )
        self.assertFalse(zorch.safe)
        self.assertNotIn("ball speed modifier", " ".join(result.narration))

    def test_tests_are_no_longer_free(self) -> None:
        with holding(self.offense, SpecialAbility.SPEED_ROLLS):
            self.assertEqual(
                ENGINE.re_roll_tokens(self.game, self.offense), 1,
            )
            self.assertEqual(
                ENGINE.skill_test_tokens(
                    self.game, self.match, self.offense,
                ),
                1,
            )


class ScorchitTests(unittest.TestCase):
    """A card Scorchit lost may go to a skill test anyway (Law 21)."""

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

    def reveal(self):
        return resolve_maneuver(ENGINE, self.game, self.match)

    def test_anybody_else_loses_on_the_cards(self) -> None:
        self.assertIsNone(ENGINE.force_test_offer(self.game, self.match))
        result = self.reveal()
        self.assertIs(result.next.step, FollowOnStep.BEGIN_EFFECT_RESOLUTION)

    def test_scorchit_is_asked_at_the_reveal(self) -> None:
        with holding(self.offense, SpecialAbility.FORCES_THE_TEST):
            result = self.reveal()
        self.assertIsInstance(result.next, PendingPrompt)
        self.assertIs(result.next.kind, PromptKind.FORCE_TEST)
        self.assertEqual(result.next.player_id, self.offense)
        self.assertEqual(self.match.pending_force_test, self.offense)

    def test_forcing_it_owes_the_test_at_two_tokens_to_none(self) -> None:
        with holding(self.offense, SpecialAbility.FORCES_THE_TEST):
            self.reveal()
            result = force_test_step(
                ENGINE, self.game, self.match, self.offense, True,
            )
        self.assertIs(
            result.next.step, FollowOnStep.BEGIN_MANEUVER_SKILL_TEST,
        )
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

    def test_letting_it_stand_resolves_the_winner(self) -> None:
        with holding(self.offense, SpecialAbility.FORCES_THE_TEST):
            self.reveal()
            result = force_test_step(
                ENGINE, self.game, self.match, self.offense, False,
            )
        self.assertIs(result.next.step, FollowOnStep.BEGIN_EFFECT_RESOLUTION)
        self.assertEqual(result.next.kwargs["winner_key"], "steal")
        self.assertIsNone(self.match.pending_force_test)

    def test_not_off_a_card_they_won(self) -> None:
        with holding(self.defense, SpecialAbility.FORCES_THE_TEST):
            self.assertIsNone(ENGINE.force_test_offer(self.game, self.match))

    def test_an_injured_winner_s_test_is_the_injury_s(self) -> None:
        self.match.mark_injured(self.defense)
        with holding(self.offense, SpecialAbility.FORCES_THE_TEST):
            self.assertIsNone(ENGINE.force_test_offer(self.game, self.match))

    def test_an_injured_scorchit_is_not_asked(self) -> None:
        # Forcing the test exhausts Scorchit 2, and an injured player
        # uses no ability that would exhaust them (Law 15.4.2 c).
        self.match.mark_injured(self.offense)
        with holding(self.offense, SpecialAbility.FORCES_THE_TEST):
            self.assertIsNone(ENGINE.force_test_offer(self.game, self.match))

    def test_nothing_once_the_stealer_has_the_ball(self) -> None:
        # A beaten Pinpoint owes the stealer a free Low Pass, which
        # makes them the handler: the cards now name one player twice,
        # and the settled maneuver must stay settled.
        self.match.offense_maneuver = "skilled_pass"
        self.match.defense_maneuver = "steal"
        self.match.active_player_id = self.defense
        with holding(self.defense, SpecialAbility.FORCES_THE_TEST):
            self.assertIsNone(ENGINE.force_test_offer(self.game, self.match))
            self.assertEqual(
                ENGINE.settled_maneuver_winner(self.match, self.game),
                "steal",
            )

    def test_the_gambits_follow_the_cards(self) -> None:
        # Scorchit wins the forced test: their card lost on the cards,
        # so it is no gambit's benefit and the winner on the cards
        # pays no cost.
        self.match.defense_maneuver = "intercept"
        self.match.forced_test_player = self.offense
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
        with holding(self.player, SpecialAbility.DEFENSIVE_THROW):
            self.assertEqual(self.asked("own_goal"), self.skills.defense)
            self.match.offense_maneuver = "low_pass"
            self.assertEqual(self.asked("skill_test"), self.skills.offense)
            self.match.offense_maneuver = "high_pass"
            self.assertEqual(self.asked("skill_test"), self.skills.defense)
            self.assertEqual(self.asked("contest"), self.skills.offense)
            # Not the High Pass contest (the author, 2026-09-26).
            self.match.pending_loose_ball_is_high_pass = True
            self.assertEqual(self.asked("contest"), self.skills.offense)

    def named(self, roll: str) -> str:
        return ENGINE.attacking_skill_name(
            self.game, self.match, self.player, roll,
        )

    def test_the_skill_is_named_as_the_one_added(self) -> None:
        # A line that names one skill and adds the other would be a
        # coach reading the wrong number (the author, 2026-09-28).
        self.match.offense_maneuver = "high_pass"
        self.assertEqual(self.named("own_goal"), "Offensive")
        with holding(self.player, SpecialAbility.DEFENSIVE_THROW):
            self.assertEqual(self.named("own_goal"), "Defensive")
            self.assertEqual(self.named("skill_test"), "Defensive")
            self.assertEqual(self.named("contest"), "Offensive")
            self.match.offense_maneuver = "low_pass"
            self.assertEqual(self.named("skill_test"), "Offensive")


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
        with holding(self.demon, SpecialAbility.INJURY_IGNITION):
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
        with holding(self.demon, SpecialAbility.INJURY_IGNITION):
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

    def test_every_contest_for_the_ball(self) -> None:
        # A ball come down between both sides too -- "a deflect
        # bouncing the ball to a space with Slitheron and another
        # player" (the author, 2026-09-26).
        with holding(self.defense, SpecialAbility.WINS_CONTESTS):
            self.match.pending_loose_ball_on_empty_space = False
            self.match.pending_loose_ball_is_high_pass = False
            self.assertEqual(self.winner(), self.defense)
            self.match.pending_loose_ball_on_empty_space = True
            self.assertEqual(self.winner(), self.defense)
            self.match.pending_loose_ball_on_empty_space = False
            self.match.pending_loose_ball_is_high_pass = True
            self.assertEqual(self.winner(), self.defense)

    def test_nobody_else_and_not_against_each_other(self) -> None:
        self.match.pending_loose_ball_on_empty_space = True
        self.assertIsNone(self.winner())
        with mock.patch.dict(SPECIAL_ABILITIES, {
            catalog_player_id(self.offense): (
                SpecialAbility.WINS_CONTESTS, "test",
            ),
            catalog_player_id(self.defense): (
                SpecialAbility.WINS_CONTESTS, "test",
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
        with holding(defense, SpecialAbility.WINS_CONTESTS):
            result = resolve_loose_ball(ENGINE, game, match)
        self.assertIs(result.next.step, FollowOnStep.BEGIN_RUN_BACK)
        self.assertTrue(result.next.kwargs["turnover_occurred"])
        self.assertEqual(match.ball_carrier_id, defense)
        self.assertEqual(match.ball.possession, TeamSide.VISITING)
        self.assertFalse(match.pending_loose_ball)
        self.assertIn("without a roll", result.narration[0])
        # Why, as the special ability it is (the author, 2026-09-28).
        self.assertIn("special ability", result.narration[0])


class KindlefingerFlowTests(unittest.TestCase):
    """The injury check itself, through `injury_test_step`."""

    def test_a_blaze_saves_them_and_clears_a_token(self) -> None:
        game = advanced(player_1_team=Team.FIRE_DEMONS)
        match = build_match(ENGINE, game)
        demon = fielded_of_species(match, SPECIES_FIRE_DEMON)
        match.exhaustion[demon] = 8
        match.pending_injury_tests = [demon]
        with holding(demon, SpecialAbility.INJURY_IGNITION), \
                mock.patch.object(ENGINE.rng, "randint", side_effect=[6, 9]):
            roll, result = injury_test_step(ENGINE, game, match, demon)
        # 6 + 9 = 15 beats 8 tokens, where a plain 6 would not have.
        self.assertTrue(roll.safe)
        self.assertNotIn(demon, match.injured)
        self.assertEqual(match.exhaustion[demon], 7)
        self.assertIn("ignites", result.narration[0])

    def test_the_token_moves_before_the_check_is_read(self) -> None:
        # 6 + 5 = 11 against 11 tokens is not higher, so the check would
        # fail -- but the blaze clears one first, and 11 beats 10.
        game = advanced(player_1_team=Team.FIRE_DEMONS)
        match = build_match(ENGINE, game)
        demon = fielded_of_species(match, SPECIES_FIRE_DEMON)
        match.exhaustion[demon] = 11
        match.pending_injury_tests = [demon]
        with holding(demon, SpecialAbility.INJURY_IGNITION), \
                mock.patch.object(ENGINE.rng, "randint", side_effect=[6, 5]):
            roll, _ = injury_test_step(ENGINE, game, match, demon)
        self.assertTrue(roll.safe)
        self.assertEqual(match.exhaustion[demon], 10)


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

    def sheet_sentence(self) -> str:
        """The shooter's special ability as the shot says it: the
        sheet's own words, not a paraphrase (the author, 2026-09-30)."""
        sentence = ENGINE.get_player_definition(self.shooter).advanced_ability
        self.assertTrue(sentence)
        return f"Special ability: {without_shot_condition(sentence)}"

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

    def test_goopkeeper_blocks_in_full_beyond_the_ball(self) -> None:
        with holding(self.beyond, SpecialAbility.FULL_BLOCK):
            wall = self.defending()
        self.assertFalse(wall[self.beyond].halved)
        self.assertEqual(
            wall[self.beyond].value,
            ENGINE.skills(self.game, self.beyond).defense,
        )

    def test_goopkeeper_behind_the_ball_adds_nothing(self) -> None:
        with holding(self.behind, SpecialAbility.FULL_BLOCK):
            self.assertNotIn(self.behind, self.defending())

    def test_flickerwing_shoots_past_the_wall_every_time(self) -> None:
        # "Every time Flickerwing makes a scoring attempt, off a setup
        # or without it" (the author, 2026-09-26).
        for set_up in (False, True):
            with self.subTest(set_up=set_up):
                self.match.pending_shot_is_set_up = set_up
                with holding(self.shooter, SpecialAbility.CLEAR_SHOT):
                    wall = self.defending()
                    counted = {
                        player_id for player_id, defender in wall.items()
                        if defender.value
                    }
                    self.assertEqual(counted, {self.on_ball})
                    with holding(self.beyond, SpecialAbility.FULL_BLOCK):
                        wall = self.defending()
                        self.assertFalse(wall[self.beyond].passed)
                        self.assertEqual(
                            wall[self.beyond].value,
                            ENGINE.skills(self.game, self.beyond).defense,
                        )

    def test_flickerwing_leaves_the_passed_in_the_way(self) -> None:
        # Still in the way, so both pictures can say so, and worth
        # nothing (the author, 2026-09-30).
        with holding(self.shooter, SpecialAbility.CLEAR_SHOT):
            wall = self.defending()
        self.assertEqual(set(wall), {self.on_ball, self.beyond})
        self.assertTrue(wall[self.beyond].passed)
        self.assertFalse(wall[self.beyond].halved)
        self.assertEqual(wall[self.beyond].value, 0)
        self.assertFalse(wall[self.on_ball].passed)
        self.assertEqual(
            ENGINE.clear_shot_note(
                self.game, self.shooter, list(wall.values()),
            ),
            self.sheet_sentence(),
        )

    def test_flickerwing_says_nothing_when_nobody_is_passed(self) -> None:
        self.at(self.beyond, 0)
        with holding(self.shooter, SpecialAbility.CLEAR_SHOT):
            wall = self.defending()
        self.assertEqual(set(wall), {self.on_ball})
        self.assertEqual(
            ENGINE.clear_shot_note(
                self.game, self.shooter, list(wall.values()),
            ),
            "",
        )

    def test_the_shot_announces_the_ability_and_the_passed(self) -> None:
        with holding(self.shooter, SpecialAbility.CLEAR_SHOT):
            [shooter, *_], defenders, _ = score_attempt_brief(
                ENGINE, self.match, self.game,
            )
        self.assertIn(self.sheet_sentence(), shooter.modifiers)
        passed = [side for side in defenders if side.passed]
        self.assertEqual(len(passed), 1)
        self.assertEqual(passed[0].value, 0)
        self.assertEqual(passed[0].band, "passed")

    def test_flickerwings_reminder_drops_the_condition(self) -> None:
        # "It only appears when Flickerwing attempts to score" (the
        # author, 2026-09-30): the reminder is the rest of the sheet's
        # sentence, and the card keeps all of it.
        flickerwing = next(
            player_id for player_id, (ability, _) in SPECIAL_ABILITIES.items()
            if ability == SpecialAbility.CLEAR_SHOT
        )
        sentence = ENGINE.special_ability_text(self.game, flickerwing)
        self.assertTrue(sentence.startswith(CLEAR_SHOT_CONDITION))
        self.assertEqual(
            ENGINE.special_ability_reminder(self.game, flickerwing),
            "Only defenders on the ball contribute their skill scores.",
        )

    def test_goopkeepers_reminder_drops_the_condition(self) -> None:
        # The same reasoning as Flickerwing's (the author, 2026-09-30).
        goopkeeper = next(
            player_id for player_id, (ability, _) in SPECIAL_ABILITIES.items()
            if ability == SpecialAbility.FULL_BLOCK
        )
        sentence = ENGINE.special_ability_text(self.game, goopkeeper)
        self.assertTrue(sentence.endswith(FULL_BLOCK_CONDITION))
        self.assertEqual(
            ENGINE.special_ability_reminder(self.game, goopkeeper),
            "Counts as 'on the ball' when standing between the ball and "
            "the goal.",
        )

    def test_a_frontend_with_its_own_reminder_leaves_the_line_off(
        self,
    ) -> None:
        with holding(self.shooter, SpecialAbility.CLEAR_SHOT):
            [shooter, *_], defenders, _ = score_attempt_brief(
                ENGINE, self.match, self.game, ability_note=False,
            )
        self.assertNotIn(self.sheet_sentence(), shooter.modifiers)
        self.assertTrue(any(side.passed for side in defenders))

    def test_goopkeeper_beyond_the_ball_is_said_on_the_dice(self) -> None:
        # Only beyond the ball, where the ability changes the shot (the
        # author, 2026-09-30); against Flickerwing too (21.3.5).
        for flickerwing in (False, True):
            with self.subTest(flickerwing=flickerwing):
                abilities = {
                    catalog_player_id(self.beyond): (
                        SpecialAbility.FULL_BLOCK, "test",
                    ),
                    catalog_player_id(self.on_ball): (
                        SpecialAbility.FULL_BLOCK, "test",
                    ),
                }
                if flickerwing:
                    abilities[catalog_player_id(self.shooter)] = (
                        SpecialAbility.CLEAR_SHOT, "test",
                    )
                with mock.patch.dict(SPECIAL_ABILITIES, abilities):
                    wall = self.defending()
                    (_, defence), _, _, _ = score_score_attempt(
                        ENGINE, self.game, self.match,
                        ENGINE.get_player_definition(self.shooter),
                        self.match.home, self.match.visiting,
                    )
                self.assertTrue(wall[self.beyond].as_on_ball)
                self.assertFalse(wall[self.on_ball].as_on_ball)
                lines = defence[2]
                beyond = player_with_role(
                    ENGINE.get_player_definition(self.beyond),
                )
                on_ball = player_with_role(
                    ENGINE.get_player_definition(self.on_ball),
                )
                self.assertTrue(any(
                    line.startswith(beyond)
                    and line.endswith(SHOT_AS_ON_BALL_NOTE)
                    for line in lines
                ))
                self.assertFalse(any(
                    line.startswith(on_ball)
                    and line.endswith(SHOT_AS_ON_BALL_NOTE)
                    for line in lines
                ))

    def test_the_shot_image_says_flickerwings_ability_once(self) -> None:
        # The modifier is the sentence when somebody is passed, so the
        # line under the shooter is left off; a frontend with its own
        # reminder gets it there instead (the author, 2026-10-02).
        with holding(self.shooter, SpecialAbility.CLEAR_SHOT), \
                mock.patch.object(
                    ENGINE, "special_ability_reminder", reminder,
                ), role_scores():
            [noted, *_], _, _ = score_attempt_brief(
                ENGINE, self.match, self.game,
            )
            [bare, *_], _, _ = score_attempt_brief(
                ENGINE, self.match, self.game, ability_note=False,
            )
        self.assertEqual(noted.special, "")
        self.assertEqual(bare.special, reminder(self.game, self.shooter))

    def test_the_shot_image_says_goopkeeper_beyond_the_ball_alone(
        self,
    ) -> None:
        abilities = {
            catalog_player_id(player_id): (SpecialAbility.FULL_BLOCK, "test")
            for player_id in (self.beyond, self.on_ball)
        }
        with mock.patch.dict(SPECIAL_ABILITIES, abilities, clear=True), \
                mock.patch.object(
                    ENGINE, "special_ability_reminder", reminder,
                ), role_scores():
            _, wall, _ = score_attempt_brief(ENGINE, self.match, self.game)
        said = {side.special for side in wall if side.special}
        self.assertEqual(said, {reminder(self.game, self.beyond)})

    def test_the_dice_list_the_passed_at_nothing(self) -> None:
        with holding(self.shooter, SpecialAbility.CLEAR_SHOT):
            (attack, defence), _, defense_total, _ = score_score_attempt(
                ENGINE, self.game, self.match,
                ENGINE.get_player_definition(self.shooter),
                self.match.home, self.match.visiting,
            )
        self.assertIn(self.sheet_sentence(), attack[2])
        beyond = player_with_role(ENGINE.get_player_definition(self.beyond))
        self.assertIn(f"{beyond} +0{SHOT_PASSED_NOTE}", defence[2])
        on_ball = ENGINE.skills(self.game, self.on_ball).defense
        self.assertEqual(defense_total, defence[0] + on_ball)


class MatchupReminderTests(unittest.TestCase):
    """The bot's challenge image reminds of the special abilities that
    bear on the skill test, off the table the web page reads
    (`d12ball/bearings.py`; the author, 2026-10-02)."""

    def setUp(self) -> None:
        self.match = build_match(ENGINE, advanced())
        self.match.ball.possession = TeamSide.HOME
        self.attacker = self.match.home.field_players[0]
        self.challenger = self.match.visiting.field_players[0]
        self.match.active_player_id = self.attacker

    def specials(self, game, player_id: str, ability: SpecialAbility):
        # The one ability granted is the only one the table holds, and
        # nobody's score is raised, so it is the only one said.
        with role_scores(), mock.patch.dict(
            SPECIAL_ABILITIES,
            {catalog_player_id(player_id): (ability, "test")},
            clear=True,
        ), mock.patch.object(
            ENGINE, "special_ability_reminder", reminder,
        ):
            offense, defense, _ = maneuver_challenge_brief(
                ENGINE, self.match, self.challenger, game,
            )
        return offense[0].special, defense[0].special

    def test_a_maneuvers_ability_is_said_on_the_attack_alone(self) -> None:
        # What a card does once won is named on the side that plays it.
        game = advanced()
        self.assertEqual(
            self.specials(game, self.attacker, SpecialAbility.FREE_BURST),
            (reminder(game, self.attacker), ""),
        )
        self.assertEqual(
            self.specials(game, self.challenger, SpecialAbility.FREE_BURST),
            ("", ""),
        )

    def test_an_ability_on_the_die_is_said_on_either_side(self) -> None:
        game = advanced()
        self.assertEqual(
            self.specials(game, self.challenger, SpecialAbility.BOOST),
            ("", reminder(game, self.challenger)),
        )

    def test_an_ability_that_does_not_bear_is_not_said(self) -> None:
        # Quantor's run on is a teammate's pass, never his own roll.
        self.assertEqual(
            self.specials(advanced(), self.attacker, SpecialAbility.RUN_ON),
            ("", ""),
        )

    def notes(self, game, player_id: str):
        with mock.patch.dict(
            SPECIAL_ABILITIES,
            {catalog_player_id(player_id): (SpecialAbility.RUN_ON, "test")},
            clear=True,
        ), mock.patch.object(ENGINE, "special_ability_text", reminder):
            return maneuver_challenge_notes(ENGINE, self.match, game)

    def test_a_teammate_who_may_run_onto_the_pass_is_a_note(self) -> None:
        # Quantor, while a teammate is on the ball: not in the roll, so
        # not under either side, but the coach choosing the card is
        # told (the author, 2026-10-02).
        runner = next(
            player_id for player_id in self.match.home.field_players
            if player_id != self.attacker
        )
        (note,) = self.notes(advanced(), runner)
        self.assertEqual(note.text, reminder(advanced(), runner))
        self.assertEqual(
            self.specials(advanced(), runner, SpecialAbility.RUN_ON),
            ("", ""),
        )

    def test_no_note_for_the_handler_the_other_side_or_another_mode(
        self,
    ) -> None:
        self.assertEqual(self.notes(advanced(), self.attacker), [])
        self.assertEqual(self.notes(advanced(), self.challenger), [])
        runner = self.match.home.field_players[1]
        for mode in (GameMode.TRAINING, GameMode.STANDARD):
            with self.subTest(mode.value):
                self.assertEqual(
                    self.notes(build_game(mode=mode), runner), [],
                )

    def test_only_an_advanced_game_says_any(self) -> None:
        for mode in (GameMode.TRAINING, GameMode.STANDARD):
            with self.subTest(mode.value):
                self.assertEqual(
                    self.specials(
                        build_game(mode=mode), self.attacker,
                        SpecialAbility.BOOST,
                    ),
                    ("", ""),
                )


class ViscorTests(unittest.TestCase):
    """Viscor adds 3 more when Merging (Law 21)."""

    def test_three_on_top_of_the_merge(self) -> None:
        game = advanced(player_1_team=Team.OOZES)
        match = build_match(ENGINE, game)
        side = match.ball.possession
        ooze = fielded_of_species(match, SPECIES_OOZE, side)
        match.move_meeple(ooze, match.ball.zone, match.ball.space_index)
        plain, _, _ = ENGINE.merge_bonus(game, match, side, (), "offense")
        with holding(ooze, SpecialAbility.MERGES_HARDER):
            harder, lines, _ = ENGINE.merge_bonus(
                game, match, side, (), "offense",
            )
        self.assertEqual(harder, plain + VISCOR_MERGE_BONUS)
        self.assertTrue(lines)


class ShpritzTests(unittest.TestCase):
    """Shpritz has the Telekinetics' Smooth (Law 21)."""

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
        # A Smooth takes the ball off somebody, so the pass is aimed at
        # a teammate standing beside the Ooze.
        receiver = next(
            player_id
            for player_id in self.match.setup_for_side(
                self.match.ball.possession,
            ).field_players
            if player_id != self.taker
        )
        self.match.board.place_meeple(receiver, zone, index)
        self.match.set_ball_carrier(receiver)

    def test_only_shpritz_may_take_it_over(self) -> None:
        self.assertEqual(ENGINE.smooth_candidates(self.game, self.match), [])
        with holding(self.taker, SpecialAbility.SMOOTH):
            self.assertEqual(
                ENGINE.smooth_candidates(self.game, self.match),
                [self.taker],
            )
            self.assertEqual(
                ENGINE.smooth_candidates(
                    build_game(
                        mode=GameMode.STANDARD, player_1_team=Team.OOZES,
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
        with holding(passer, SpecialAbility.LONG_SET_UP):
            result = high_pass_step(ENGINE, self.match, 3, game=self.game)
        self.assertIs(
            result.next.step, FollowOnStep.OFFER_SCORING_ATTEMPT_CHOICE,
        )
        self.assertEqual(result.next.kwargs["shooter_id"], receiver)
        self.assertEqual(self.match.ball.speed, VORIX_BALL_SPEED)

    def test_vorix_out_of_range_is_simply_received(self) -> None:
        passer, receiver = self.pass_from(0, 3)
        with holding(passer, SpecialAbility.LONG_SET_UP):
            result = high_pass_step(ENGINE, self.match, 3, game=self.game)
        self.assertIs(
            result.next.step, FollowOnStep.FINISH_MANEUVER_RESOLUTION,
        )
        self.assertEqual(self.match.ball_carrier_id, receiver)
        self.assertEqual(self.match.ball.speed, VORIX_BALL_SPEED)

    def test_zytheris_s_long_pass_is_contested_first(self) -> None:
        # "Contest comes first and shooting is possible only if
        # Zytheris wins it" (the author, 2026-09-26).
        _, receiver = self.pass_from(2, 5)
        with holding(receiver, SpecialAbility.SHOOTS_OFF_ANY_PASS):
            result = high_pass_step(ENGINE, self.match, 3, game=self.game)
        self.assertIs(
            result.next.step, FollowOnStep.BEGIN_HIGH_PASS_CONTEST,
        )

    def test_zytheris_shoots_once_they_keep_it(self) -> None:
        _, receiver = self.pass_from(2, 5)
        match = self.match
        match.set_ball_space(*match.board.meeple_position(receiver))
        with holding(receiver, SpecialAbility.SHOOTS_OFF_ANY_PASS):
            kept = after_the_contest(
                ENGINE, self.game, match, receiver, True, False, 2,
            )
            lost = after_the_contest(
                ENGINE, self.game, match, receiver, True, True, 2,
            )
            loose = after_the_contest(
                ENGINE, self.game, match, receiver, False, False, 2,
            )
        self.assertEqual(kept["kind"], "scoring_attempt")
        self.assertEqual(kept["shooter_id"], receiver)
        self.assertEqual(lost["kind"], "run_back")
        self.assertEqual(loose["kind"], "run_back")

    def test_an_uncontested_long_pass_is_kept_and_shot(self) -> None:
        _, receiver = self.pass_from(2, 5)
        match = self.match
        match.set_ball_space(*match.board.meeple_position(receiver))
        match.pending_loose_ball = True
        match.pending_loose_ball_is_high_pass = True
        match.pending_loose_ball_distance = 2
        match.loose_ball_offense_player = receiver
        with holding(receiver, SpecialAbility.SHOOTS_OFF_ANY_PASS):
            result = resolve_loose_ball(ENGINE, self.game, match)
        self.assertIs(
            result.next.step, FollowOnStep.OFFER_SCORING_ATTEMPT_CHOICE,
        )
        self.assertEqual(result.next.kwargs["shooter_id"], receiver)

    def passed(self, distance: int):
        """A Low Pass played, and its passer kept where they are when
        asked (Law 6.5.3): what the pass leads to after that."""
        result = low_pass_step(ENGINE, self.match, distance, game=self.game)
        if (
            isinstance(result.next, PendingPrompt)
            and result.next.kind is PromptKind.PASSER_ADVANCE
        ):
            result = answer_passer_advance(
                ENGINE, self.game, self.match, advance=False,
            )
        return result

    def test_zytheris_shoots_off_a_low_pass(self) -> None:
        _, receiver = self.pass_from(3, 4)
        plain = self.passed(1)
        self.assertIs(
            plain.next.step, FollowOnStep.FINISH_MANEUVER_RESOLUTION,
        )
        self.pass_from(3, 4)
        with holding(receiver, SpecialAbility.SHOOTS_OFF_ANY_PASS):
            result = self.passed(1)
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
        with holding(self.player, SpecialAbility.LIGHTS_THE_BALL):
            said = self.comes()
        self.assertEqual(self.match.ball.speed, INFERNO_BALL_SPEED)
        # Said as the special ability it is (the author, 2026-09-28).
        self.assertIn("special ability", said[0])

    def test_only_when_it_comes_to_them(self) -> None:
        self.match.set_ball_carrier(self.player)
        with holding(self.player, SpecialAbility.LIGHTS_THE_BALL):
            self.assertEqual(
                ball_comes_to(ENGINE, self.game, self.match, self.player),
                [],
            )
        self.assertEqual(self.match.ball.speed, 3)

    def test_being_chosen_to_handle_it_is_not_receiving_it(self) -> None:
        # The choice consumes the carry: the handler is who the turn
        # chose, not who the ball was left with.
        before = ENGINE.ball_holder(self.match)
        self.match.clear_ball_carrier()
        self.match.active_player_id = self.player
        with holding(self.player, SpecialAbility.LIGHTS_THE_BALL):
            self.assertEqual(
                ball_comes_to(ENGINE, self.game, self.match, before), [],
            )
        self.assertEqual(self.match.ball.speed, 3)

    def test_a_pickup_is_receiving_it(self) -> None:
        # "A steal, a pickup, or a pass" (the author, 2026-09-26). A
        # pickup leaves nobody holding the ball, so it asks itself.
        from d12ball.flow.turnovers import recover_ball_step

        self.match.clear_ball_carrier()
        self.match.pending_ball_recovery = True
        picker = self.match.contest_candidates(self.match.ball.possession)[0]
        with holding(picker, SpecialAbility.LIGHTS_THE_BALL):
            result = recover_ball_step(
                ENGINE, self.game, self.match, player_id=picker,
            )
        self.assertEqual(self.match.ball.speed, INFERNO_BALL_SPEED)
        self.assertIn("ball speed", result.narration[0])

    def test_pulsar_charges_up(self) -> None:
        self.match.exhaustion[self.player] = 2
        with holding(self.player, SpecialAbility.CHARGES_ON_THE_BALL):
            said = self.comes()
        self.assertEqual(self.match.exhaustion[self.player], 1)
        self.assertIn("special ability", said[0])


class GlompexTests(unittest.TestCase):
    """Glompex steps onto the ball before the cards (Law 21)."""

    def setUp(self) -> None:
        # Only the player a test hands the ability to holds it: the
        # deal fields the real Glompex, who would be asked as well.
        cleared = mock.patch.dict(SPECIAL_ABILITIES, {}, clear=True)
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
        with holding(self.joiner, SpecialAbility.JOINS_THE_BALL):
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

    def test_not_an_injured_glompex(self) -> None:
        # Joining exhausts 1, and an injured player uses no ability
        # that would exhaust them (Law 15.4.2 c).
        self.match.mark_injured(self.joiner)
        with holding(self.joiner, SpecialAbility.JOINS_THE_BALL):
            self.assertEqual(
                ENGINE.join_candidates(self.game, self.match), [],
            )

    def test_asked_before_the_cards_once(self) -> None:
        with holding(self.joiner, SpecialAbility.JOINS_THE_BALL):
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
        cleared = mock.patch.dict(SPECIAL_ABILITIES, {}, clear=True)
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
        with holding(self.flier, SpecialAbility.FLY):
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
        with holding(holder, SpecialAbility.FLY):
            self.assertEqual(
                ENGINE.fly_candidates(self.game, self.match), [],
            )

    def test_never_injured(self) -> None:
        self.match.mark_injured(self.flier)
        with holding(self.flier, SpecialAbility.FLY):
            self.assertEqual(
                ENGINE.fly_candidates(self.game, self.match), [],
            )

    def test_not_a_new_play(self) -> None:
        with holding(self.flier, SpecialAbility.FLY):
            result = begin_run_back(
                ENGINE, self.game, self.match, new_play=True,
            )
        self.assertNotIsInstance(result.next, PendingPrompt)


if __name__ == "__main__":
    unittest.main()
