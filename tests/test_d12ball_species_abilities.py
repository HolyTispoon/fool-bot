"""
Species abilities: the module switch they ride on, and the abilities
themselves.

Layers, and they fail for different reasons:

- **The switch.** Advanced mode is one setting over two modules, and
  `advanced_maneuvers_apply` / `species_abilities_apply` are the only
  two answers to which of them a game is playing. A rule that reads
  `game.mode` or `game.species_abilities` on its own has skipped one
  half of the question.
- **The gate.** `has_species_ability` is what every ability site asks,
  and it folds the module and the species together so a site cannot
  check one and forget the other.
- **Volatile.** `ignite` is the funnel every d12 in the game comes
  through, and `volatile_raises_tier` plus `resolving_maneuver` are the
  tier rider on top of it.
- **Lithium Powered.** Three separate things sharing one ability: the
  Drained line (`exhaustion_threshold`, which every exhaustion charge
  and every recovery now asks), Overdrive (declared and paid before a
  roll, spent by it), and Charge-up (`charge_up_players`, read off who
  the run back is about to move).
- **Slimey.** Slip in widens `turn_handler_candidates` rather than
  adding to it -- an Ooze on the ball is already an eligible handler --
  and Merge is a sum over the bystanders, not a pick.
- **Mind Pull**, which is the one ability that interrupts a maneuver
  rather than modifying it. Three layers again: the path
  (`ball_path_to`, recorded by `set_ball_space`), who it offers a pull
  to (`mind_pull_candidates`), and the gate actually stopping the turn
  to ask -- that last one through the **real cog**, because a gate
  wired to the wrong function, or one that forgets to spend the path,
  is invisible to a unit test on the engine.

The rules are "Species abilities" in docs/living-rules.md. Nothing here
asserts the wording of a message -- that is prose and will be revised;
what is asserted is every claim the rules make that the code could
contradict.

Players are named by **species**, through `roster.fielded_of_species`,
for the reason every other suite names them by role: which Fire Demon
a deal fields is data the author revises, and no test here is about
which one it was.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

from cogs.d12ball import D12Ball
from cogs.d12ball_views import MindPullView
from d12ball.ai import build_ai_strategies
from d12ball.components import (
    CYBORG_DRAINED_AT,
    MIND_PULL_SUCCESS_FACES,
    MIND_PULL_TOKEN_COST,
    OVERDRIVE_BONUS,
    OVERDRIVE_DRAIN_COST,
    SPECIES_CYBORG,
    SPECIES_FIRE_DEMON,
    SPECIES_OOZE,
    SPECIES_TELEKINETIC,
    MatchState,
    TeamSide,
    Zone,
    duplicate_card_id,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.engine import (
    VOLATILE_IGNITE_FACES,
    VOLATILE_SURGE_MINIMUM,
    IgnitedRoll,
    RulesEngine,
)
from d12ball.game import (
    AIOpponent,
    D12BallGame,
    GameMode,
    GameStatus,
    Team,
)

from roster import field_players, fielded_of_species
from save_patches import suppressed_cog_saves


def build_engine() -> RulesEngine:
    player_catalog = load_player_catalog()
    maneuver_catalog = load_maneuver_catalog()
    basic_ruleset = load_basic_ruleset()
    return RulesEngine(
        player_catalog,
        basic_ruleset,
        maneuver_catalog,
        build_ai_strategies(player_catalog, maneuver_catalog),
    )


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
        # A species side and a colour side, so the same match holds
        # nine of one species and a mix -- which is what lets one
        # fixture answer both "every card has the ability" and "only
        # some do".
        player_1_team=Team.FIRE_DEMONS,
        player_2_team=Team.PURPLE,
        status=GameStatus.IN_PROGRESS,
        home_player_number=1,
        visiting_player_number=2,
        mode=GameMode.ADVANCED,
    )
    fields.update(overrides)
    return D12BallGame(**fields)


def build_match(engine: RulesEngine, game: D12BallGame) -> MatchState:
    return engine.initialize_standard_match(game)


class ModuleSwitchTests(unittest.TestCase):
    """
    "Advanced mode turns on two modules ... Both come on with it, and a
    game may take just one of the two."
    """

    def setUp(self) -> None:
        self.engine = build_engine()

    def test_advanced_mode_brings_both_modules(self):
        game = build_game()
        self.assertTrue(self.engine.advanced_maneuvers_apply(game))
        self.assertTrue(self.engine.species_abilities_apply(game))

    def test_a_basic_game_has_neither(self):
        game = build_game(mode=GameMode.BASIC)
        self.assertFalse(self.engine.advanced_maneuvers_apply(game))
        self.assertFalse(self.engine.species_abilities_apply(game))

    def test_a_basic_game_ignores_the_opt_outs_entirely(self):
        # The two fields mean nothing outside advanced mode: `mode` is
        # the whole answer there, which is what stops a basic game
        # played by somebody's stale settings turning an ability on.
        game = build_game(
            mode=GameMode.BASIC,
            advanced_maneuvers=True,
            species_abilities=True,
        )
        self.assertFalse(self.engine.advanced_maneuvers_apply(game))
        self.assertFalse(self.engine.species_abilities_apply(game))

    def test_a_game_may_take_the_abilities_without_the_maneuvers(self):
        game = build_game(advanced_maneuvers=False)
        self.assertFalse(self.engine.advanced_maneuvers_apply(game))
        self.assertTrue(self.engine.species_abilities_apply(game))

    def test_a_game_may_take_the_maneuvers_without_the_abilities(self):
        game = build_game(species_abilities=False)
        self.assertTrue(self.engine.advanced_maneuvers_apply(game))
        self.assertFalse(self.engine.species_abilities_apply(game))

    def test_the_hand_follows_the_maneuver_module_not_the_mode(self):
        # `maneuver_tiers` used to ask `game.mode` directly, which
        # would deal six cards to a game that opted the maneuvers out.
        engine = self.engine
        game = build_game(advanced_maneuvers=False)
        match = build_match(engine, game)
        self.assertEqual(len(engine.maneuver_tiers(game, match)), 1)

        both = build_game()
        self.assertEqual(len(engine.maneuver_tiers(both, match)), 2)

    def test_a_save_written_before_the_modules_reads_as_both_on(self):
        # Every advanced game played before the opt-out existed was
        # playing both, so that is what its save has to come back as.
        saved = {
            field: value
            for field, value in build_game().to_dict().items()
            if field not in ("advanced_maneuvers", "species_abilities")
        }
        game = D12BallGame.from_dict(saved)
        self.assertTrue(game.advanced_maneuvers)
        self.assertTrue(game.species_abilities)
        self.assertTrue(self.engine.advanced_maneuvers_apply(game))
        self.assertTrue(self.engine.species_abilities_apply(game))


class SpeciesGateTests(unittest.TestCase):
    """
    `has_species_ability` -- the one question an ability site asks.
    """

    def setUp(self) -> None:
        self.engine = build_engine()
        self.game = build_game()
        self.match = build_match(self.engine, self.game)

    def test_a_fire_demon_has_volatile(self):
        demon = fielded_of_species(self.match, SPECIES_FIRE_DEMON)
        self.assertTrue(
            self.engine.has_species_ability(
                self.game, demon, SPECIES_FIRE_DEMON,
            )
        )

    def test_a_fire_demon_does_not_have_another_species_ability(self):
        demon = fielded_of_species(self.match, SPECIES_FIRE_DEMON)
        for other in (SPECIES_CYBORG, SPECIES_TELEKINETIC, SPECIES_OOZE):
            self.assertFalse(
                self.engine.has_species_ability(self.game, demon, other),
                other,
            )

    def test_no_ability_in_a_basic_game(self):
        basic = build_game(mode=GameMode.BASIC)
        demon = fielded_of_species(self.match, SPECIES_FIRE_DEMON)
        self.assertFalse(
            self.engine.has_species_ability(
                basic, demon, SPECIES_FIRE_DEMON,
            )
        )

    def test_no_ability_when_the_module_is_opted_out(self):
        without = build_game(species_abilities=False)
        demon = fielded_of_species(self.match, SPECIES_FIRE_DEMON)
        self.assertFalse(
            self.engine.has_species_ability(
                without, demon, SPECIES_FIRE_DEMON,
            )
        )

    def test_a_card_the_catalog_does_not_know_has_no_ability(self):
        # A stale id left on a match answers "no ability" rather than
        # raising -- the same tolerance `turn_handler_candidates` shows
        # a stale carrier.
        self.assertFalse(
            self.engine.has_species_ability(
                self.game, "nobody_at_all", SPECIES_FIRE_DEMON,
            )
        )
        self.assertEqual(self.engine.species_of("nobody_at_all"), "")

    def test_both_copies_of_a_duplicated_player_carry_it(self):
        # "A player fielded on both sides of one game -- the same
        # person in two kits -- carries it on both cards."
        demon = fielded_of_species(self.match, SPECIES_FIRE_DEMON)
        self.assertEqual(
            self.engine.species_of(duplicate_card_id(demon)),
            self.engine.species_of(demon),
        )


class IgniteTests(unittest.TestCase):
    """
    Volatile's die: "When the die's own face -- before any skill or
    modifier -- comes up a natural 6 or 7, the Fire Demon immediately
    rolls a second d12."
    """

    def setUp(self) -> None:
        self.engine = build_engine()
        self.game = build_game()
        self.match = build_match(self.engine, self.game)
        self.demon = fielded_of_species(self.match, SPECIES_FIRE_DEMON)

    def test_only_a_six_or_a_seven_ignites(self):
        for face in range(1, 13):
            with mock.patch("random.randint", return_value=12):
                result = self.engine.ignite(self.game, self.demon, face)
            self.assertEqual(
                result.ignited,
                face in VOLATILE_IGNITE_FACES,
                f"face {face}",
            )
            self.assertEqual(result.face, face)

    def test_a_surge_adds_the_second_die(self):
        with mock.patch("random.randint", return_value=9):
            result = self.engine.ignite(self.game, self.demon, 6)
        self.assertTrue(result.surge)
        self.assertFalse(result.backfire)
        self.assertEqual(result.second, 9)
        self.assertEqual(result.modifier, 9)

    def test_a_backfire_subtracts_it(self):
        with mock.patch("random.randint", return_value=3):
            result = self.engine.ignite(self.game, self.demon, 7)
        self.assertFalse(result.surge)
        self.assertTrue(result.backfire)
        self.assertEqual(result.second, 3)
        self.assertEqual(result.modifier, -3)

    def test_the_surge_boundary_is_the_rules_number(self):
        # 5-12 surges, 1-4 backfires. Asserted across the whole range
        # rather than at the two sides of the line, since a wrong
        # comparison passes a two-value check half the time.
        for second in range(1, 13):
            with mock.patch("random.randint", return_value=second):
                result = self.engine.ignite(self.game, self.demon, 6)
            self.assertEqual(
                result.surge, second >= VOLATILE_SURGE_MINIMUM, second,
            )

    def test_a_non_fire_demon_never_ignites(self):
        # The visiting side is a colour team -- three of its own
        # species plus two of each other -- so it fields somebody who
        # is not a Fire Demon whatever the roster looks like. Which
        # species are there is the author's to revise, so a missing one
        # is skipped rather than failed; `checked` is what stops the
        # test passing because it found nobody at all.
        checked = 0
        for species in (SPECIES_CYBORG, SPECIES_TELEKINETIC, SPECIES_OOZE):
            try:
                player = fielded_of_species(
                    self.match, species, TeamSide.VISITING,
                )
            except LookupError:
                continue
            checked += 1
            for face in VOLATILE_IGNITE_FACES:
                result = self.engine.ignite(self.game, player, face)
                self.assertFalse(result.ignited, f"{species} on {face}")
                self.assertEqual(result.modifier, 0)
        self.assertGreater(checked, 0, "no non-Fire-Demon was fielded")

    def test_a_die_belonging_to_nobody_never_ignites(self):
        # A score attempt's defensive die is the wall's, not a card's.
        for face in VOLATILE_IGNITE_FACES:
            result = self.engine.ignite(self.game, None, face)
            self.assertFalse(result.ignited)
            self.assertEqual(result.modifier, 0)

    def test_nothing_ignites_in_a_basic_game(self):
        basic = build_game(mode=GameMode.BASIC)
        for face in VOLATILE_IGNITE_FACES:
            self.assertFalse(
                self.engine.ignite(basic, self.demon, face).ignited
            )

    def test_the_second_die_does_not_ignite_in_turn(self):
        # "one reroll, however it falls" -- a second die of 6 or 7 is
        # added or subtracted like any other, and rolls nothing more.
        # One randint call is the whole of the proof.
        with mock.patch("random.randint", return_value=7) as randint:
            result = self.engine.ignite(self.game, self.demon, 6)
        self.assertEqual(randint.call_count, 1)
        self.assertEqual(result.modifier, 7)

    def test_a_roll_that_did_not_ignite_says_nothing(self):
        # "A move that costs nothing says nothing" -- an ordinary die
        # adds no line to the dice image's modifier list.
        self.assertIsNone(self.engine.ignite(self.game, self.demon, 4).detail)
        self.assertIsNone(IgnitedRoll(face=4).detail)

    def test_an_ignite_says_which_way_it_went_and_on_what(self):
        with mock.patch("random.randint", return_value=9):
            surge = self.engine.ignite(self.game, self.demon, 6)
        with mock.patch("random.randint", return_value=2):
            backfire = self.engine.ignite(self.game, self.demon, 6)
        self.assertIn("surge", surge.detail)
        self.assertIn("+9", surge.detail)
        self.assertIn("backfire", backfire.detail)
        self.assertIn("-2", backfire.detail)


class VolatileTierRiderTests(unittest.TestCase):
    """
    "A surge on the winning side resolves that side's maneuver as its
    advanced version ... a backfire on the losing side resolves the
    opponent's."

    Both raise the **winner's** card -- the opponent of the losing side
    is the winning side -- which is why this is one flag and not a
    side.
    """

    def setUp(self) -> None:
        self.engine = build_engine()
        self.game = build_game()
        self.plain = IgnitedRoll(face=3)
        self.surge = IgnitedRoll(face=6, modifier=9, second=9, surge=True)
        self.backfire = IgnitedRoll(face=6, modifier=-2, second=2, surge=False)

    def test_a_surge_on_the_winner_raises_it(self):
        self.assertTrue(
            self.engine.volatile_raises_tier(
                self.game, self.surge, self.plain,
            )
        )

    def test_a_backfire_on_the_loser_raises_it(self):
        self.assertTrue(
            self.engine.volatile_raises_tier(
                self.game, self.plain, self.backfire,
            )
        )

    def test_a_backfire_on_the_winner_raises_nothing(self):
        # They won carrying a penalty; the rider is the loser's to
        # hand over, not theirs to earn.
        self.assertFalse(
            self.engine.volatile_raises_tier(
                self.game, self.backfire, self.plain,
            )
        )

    def test_a_surge_on_the_loser_raises_nothing(self):
        self.assertFalse(
            self.engine.volatile_raises_tier(
                self.game, self.plain, self.surge,
            )
        )

    def test_neither_igniting_raises_nothing(self):
        self.assertFalse(
            self.engine.volatile_raises_tier(
                self.game, self.plain, self.plain,
            )
        )

    def test_no_tier_to_change_without_the_advanced_maneuvers(self):
        # "in a game that took the species abilities without the
        # advanced maneuvers -- there is no tier to change, and the
        # surge or backfire is only the number."
        without = build_game(advanced_maneuvers=False)
        self.assertFalse(
            self.engine.volatile_raises_tier(
                without, self.surge, self.plain,
            )
        )
        self.assertFalse(
            self.engine.volatile_raises_tier(
                without, self.plain, self.backfire,
            )
        )


class ResolvingManeuverTests(unittest.TestCase):
    """
    What the rider actually does to the card that resolves.
    """

    def setUp(self) -> None:
        self.engine = build_engine()
        self.game = build_game()
        self.match = build_match(self.engine, self.game)

    def basic_and_advanced(self, key: str) -> tuple[str, str]:
        maneuver = self.engine.maneuver_catalog.get(key)
        counterpart = self.engine.maneuver_catalog.counterpart(maneuver)
        return key, counterpart.key

    def test_a_raised_basic_card_resolves_as_its_advanced_counterpart(self):
        basic, advanced = self.basic_and_advanced("low_pass")
        self.match.offense_maneuver = basic
        self.match.defense_maneuver = "deflect"
        self.match.volatile_tier_upgrade = True
        self.assertEqual(
            self.engine.resolving_maneuver(self.match, basic), advanced,
        )

    def test_without_the_rider_a_basic_card_stays_basic(self):
        basic, _ = self.basic_and_advanced("low_pass")
        self.match.offense_maneuver = basic
        self.match.defense_maneuver = "deflect"
        self.match.volatile_tier_upgrade = False
        self.assertEqual(
            self.engine.resolving_maneuver(self.match, basic), basic,
        )

    def test_a_card_already_advanced_gains_nothing(self):
        # "It only ever raises a maneuver to advanced; one already
        # resolving at advanced gains nothing."
        _, advanced = self.basic_and_advanced("low_pass")
        self.match.offense_maneuver = advanced
        self.match.defense_maneuver = "deflect"
        self.match.volatile_tier_upgrade = True
        self.assertEqual(
            self.engine.resolving_maneuver(self.match, advanced), advanced,
        )

    def test_the_rider_beats_the_tie_downgrade(self):
        # "even where the cards tied and the basic card would otherwise
        # resolve" -- an advanced card that wins a tie normally drops
        # to its basic counterpart, and the rider keeps it up.
        _, advanced = self.basic_and_advanced("low_pass")
        self.match.offense_maneuver = advanced
        # Same rank on both sides is a tie on the cards.
        self.match.defense_maneuver = self.engine.maneuver_catalog.get(
            "deflect",
        ).key
        tied = self.engine.maneuver_catalog.resolve(
            self.match.offense_maneuver, self.match.defense_maneuver,
        ) == "tie"
        if not tied:
            self.skipTest("that pairing is no longer a tie")
        self.match.volatile_tier_upgrade = False
        self.assertNotEqual(
            self.engine.resolving_maneuver(self.match, advanced), advanced,
        )
        self.match.volatile_tier_upgrade = True
        self.assertEqual(
            self.engine.resolving_maneuver(self.match, advanced), advanced,
        )

    def test_the_flag_survives_a_save(self):
        # The injury tests run between the roll that sets it and the
        # effect that reads it, so a restart in that window has to
        # resolve the maneuver at the tier the dice decided.
        self.match.volatile_tier_upgrade = True
        restored = MatchState.from_dict(
            self.match.to_dict(), self.engine.basic_ruleset,
        )
        self.assertTrue(restored.volatile_tier_upgrade)

    def test_a_save_written_before_the_flag_reads_as_no_upgrade(self):
        saved = self.match.to_dict()
        saved.pop("volatile_tier_upgrade", None)
        restored = MatchState.from_dict(saved, self.engine.basic_ruleset)
        self.assertFalse(restored.volatile_tier_upgrade)

    def test_the_turn_reset_clears_it(self):
        self.match.volatile_tier_upgrade = True
        self.match.reset_maneuver()
        self.assertFalse(self.match.volatile_tier_upgrade)


class DrainThresholdTests(unittest.TestCase):
    """
    "A Cyborg carrying 7 or more drain is Drained ... Below 7 a Cyborg
    is never Exhausted, however low their defensive skill."
    """

    def setUp(self) -> None:
        self.engine = build_engine()
        # Nine Cyborgs a side is the cleanest fixture for a threshold
        # that is about the species and not about the role.
        self.game = build_game(player_1_team=Team.CYBORGS)
        self.match = build_match(self.engine, self.game)
        self.cyborg = fielded_of_species(self.match, SPECIES_CYBORG)

    def defense_of(self, player_id: str) -> int:
        return self.engine.player_catalog.effective_profile(
            self.engine.get_player_definition(player_id),
        ).defense

    def test_a_cyborg_is_drained_at_seven_not_at_their_defence(self):
        self.assertEqual(
            self.engine.exhaustion_threshold(self.game, self.cyborg),
            CYBORG_DRAINED_AT - 1,
        )
        # The threshold is what the count must *exceed*, so 6 tokens is
        # still fine and the 7th is what does it.
        self.match.add_exhaustion(self.cyborg, CYBORG_DRAINED_AT - 1)
        self.assertFalse(
            self.engine.retest_exhausted(self.game, self.match, self.cyborg)
        )
        self.match.add_exhaustion(self.cyborg, 1)
        self.assertTrue(
            self.engine.retest_exhausted(self.game, self.match, self.cyborg)
        )

    def test_a_low_defence_cyborg_survives_well_past_their_skill(self):
        # The whole point of the ability, and the author's reason for
        # simplifying the line to a flat 7. Read off the *lowest*
        # defence on the field rather than whoever comes first: which
        # role that is belongs to the roster, and every side fields a
        # spread.
        weakest = min(
            field_players(self.match), key=self.defense_of,
        )
        skill = self.defense_of(weakest)
        self.assertLess(skill, CYBORG_DRAINED_AT - 1)

        self.match.add_exhaustion(weakest, skill + 1)
        self.assertFalse(
            self.engine.retest_exhausted(self.game, self.match, weakest)
        )
        self.assertNotIn(weakest, self.match.exhausted)

    def test_a_basic_game_gives_a_cyborg_no_such_thing(self):
        basic = build_game(player_1_team=Team.CYBORGS, mode=GameMode.BASIC)
        self.assertEqual(
            self.engine.exhaustion_threshold(basic, self.cyborg),
            self.defense_of(self.cyborg),
        )

    def test_a_non_cyborg_is_exhausted_on_their_defensive_skill(self):
        other = fielded_of_species(
            self.match, SPECIES_FIRE_DEMON, TeamSide.VISITING,
        )
        self.assertEqual(
            self.engine.exhaustion_threshold(self.game, other),
            self.defense_of(other),
        )


class OverdriveTests(unittest.TestCase):
    """
    "Once per roll, before the die is thrown, a Cyborg may take 3 drain
    tokens to add +5 to that roll."
    """

    def setUp(self) -> None:
        self.engine = build_engine()
        self.game = build_game(player_1_team=Team.CYBORGS)
        self.match = build_match(self.engine, self.game)
        self.cyborg = fielded_of_species(self.match, SPECIES_CYBORG)

    def declare(self, player_id=None):
        player_id = player_id or self.cyborg
        self.match.declare_overdrive(
            player_id,
            self.engine.exhaustion_threshold(self.game, player_id),
        )

    def test_declaring_costs_three_drain_and_adds_five(self):
        self.declare()
        self.assertEqual(
            self.match.exhaustion[self.cyborg], OVERDRIVE_DRAIN_COST,
        )
        self.assertEqual(
            self.match.overdrive_modifier(self.cyborg), OVERDRIVE_BONUS,
        )

    def test_once_per_roll(self):
        self.declare()
        with self.assertRaises(ValueError):
            self.declare()
        # And the refusal charged nothing extra.
        self.assertEqual(
            self.match.exhaustion[self.cyborg], OVERDRIVE_DRAIN_COST,
        )

    def test_the_bonus_does_not_carry_to_the_next_roll(self):
        # "A tie that is rolled again is a fresh roll: the +5 does not
        # carry, and the re-roll may be Overdriven for another 3 drain."
        self.declare()
        self.match.consume_overdrive()
        self.assertEqual(self.match.overdrive_modifier(self.cyborg), 0)
        self.declare()
        self.assertEqual(
            self.match.exhaustion[self.cyborg], OVERDRIVE_DRAIN_COST * 2,
        )

    def test_a_drained_cyborg_may_still_overdrive(self):
        # "A Drained Cyborg may still Overdrive -- the drain stacks."
        self.match.add_exhaustion(self.cyborg, CYBORG_DRAINED_AT)
        self.engine.retest_exhausted(self.game, self.match, self.cyborg)
        self.assertIn(self.cyborg, self.match.exhausted)

        self.declare()
        self.assertEqual(
            self.match.exhaustion[self.cyborg],
            CYBORG_DRAINED_AT + OVERDRIVE_DRAIN_COST,
        )
        self.assertEqual(
            self.match.overdrive_modifier(self.cyborg), OVERDRIVE_BONUS,
        )

    def test_declaring_can_be_what_drains_them(self):
        self.match.add_exhaustion(self.cyborg, CYBORG_DRAINED_AT - 3)
        self.declare()
        self.assertIn(self.cyborg, self.match.exhausted)

    def test_an_injured_cyborg_cannot_pay_for_it(self):
        self.match.mark_injured(self.cyborg)
        with self.assertRaises(ValueError):
            self.declare()

    def test_only_cyborgs_are_offered_it(self):
        others = [
            fielded_of_species(self.match, species, TeamSide.VISITING)
            for species in (SPECIES_FIRE_DEMON, SPECIES_OOZE)
            if self.engine.species_of(
                fielded_of_species(self.match, species, TeamSide.VISITING)
            )
        ]
        offered = self.engine.overdrive_candidates(
            self.game, self.match, [self.cyborg] + others,
        )
        self.assertEqual(offered, [self.cyborg])

    def test_nobody_is_offered_it_in_a_basic_game(self):
        basic = build_game(player_1_team=Team.CYBORGS, mode=GameMode.BASIC)
        self.assertEqual(
            self.engine.overdrive_candidates(
                basic, self.match, [self.cyborg],
            ),
            [],
        )

    def test_a_cyborg_who_has_declared_is_not_offered_it_again(self):
        self.declare()
        self.assertEqual(
            self.engine.overdrive_candidates(
                self.game, self.match, [self.cyborg],
            ),
            [],
        )

    def test_a_die_belonging_to_nobody_is_filtered_out(self):
        # A score attempt passes its second roller as None.
        self.assertEqual(
            self.engine.overdrive_candidates(self.game, self.match, [None]),
            [],
        )

    def test_the_declaration_survives_a_save(self):
        # Declaring and rolling are two clicks with a save between
        # them -- that is the whole of declaring blind.
        self.declare()
        restored = MatchState.from_dict(
            self.match.to_dict(), self.engine.basic_ruleset,
        )
        self.assertEqual(
            restored.overdrive_modifier(self.cyborg), OVERDRIVE_BONUS,
        )

    def test_a_save_written_before_the_field_declares_nothing(self):
        saved = self.match.to_dict()
        saved.pop("pending_overdrive", None)
        restored = MatchState.from_dict(saved, self.engine.basic_ruleset)
        self.assertEqual(restored.pending_overdrive, [])

    def test_the_turn_reset_clears_it(self):
        self.declare()
        self.match.reset_maneuver()
        self.assertEqual(self.match.pending_overdrive, [])


class ChargeUpTests(unittest.TestCase):
    """
    "Whenever players run back, a Cyborg who is not moved by it ...
    removes 1 drain token. Once per run back, never below zero."
    """

    def setUp(self) -> None:
        self.engine = build_engine()
        self.game = build_game(player_1_team=Team.CYBORGS)
        self.match = build_match(self.engine, self.game)

    def test_a_cyborg_left_in_place_charges_up(self):
        cyborg = fielded_of_species(self.match, SPECIES_CYBORG)
        self.match.add_exhaustion(cyborg, 4)
        self.assertIn(
            cyborg, self.engine.charge_up_players(self.game, self.match),
        )

    def test_a_cyborg_the_run_back_moves_does_not(self):
        # Drag one out of their own zone: they are displaced, so the
        # run back is about to send them home and they charge nothing.
        cyborg = fielded_of_species(self.match, SPECIES_CYBORG)
        self.match.add_exhaustion(cyborg, 4)
        self.match.board.place_meeple(cyborg, Zone.VISITORS_GOAL, 0)
        self.assertNotIn(
            cyborg, self.engine.charge_up_players(self.game, self.match),
        )

    def test_the_carrier_who_never_runs_back_charges_up(self):
        # The rule names them explicitly: they are displaced but exempt,
        # so `run_back_displaced` already strikes them out.
        cyborg = fielded_of_species(self.match, SPECIES_CYBORG)
        self.match.add_exhaustion(cyborg, 4)
        self.match.board.place_meeple(cyborg, Zone.VISITORS_GOAL, 0)
        self.match.pending_run_back_stays_player_id = cyborg
        self.assertIn(
            cyborg, self.engine.charge_up_players(self.game, self.match),
        )

    def test_never_below_zero(self):
        # A Cyborg carrying nothing has nothing to take off, and says
        # nothing about it either.
        cyborg = fielded_of_species(self.match, SPECIES_CYBORG)
        self.assertEqual(self.match.exhaustion.get(cyborg, 0), 0)
        self.assertNotIn(
            cyborg, self.engine.charge_up_players(self.game, self.match),
        )

    def test_a_basic_game_charges_nobody_up(self):
        basic = build_game(player_1_team=Team.CYBORGS, mode=GameMode.BASIC)
        cyborg = fielded_of_species(self.match, SPECIES_CYBORG)
        self.match.add_exhaustion(cyborg, 4)
        self.assertEqual(
            self.engine.charge_up_players(basic, self.match), [],
        )

    def test_a_non_cyborg_never_charges_up(self):
        for player_id in self.match.visiting.field_players:
            if self.engine.species_of(player_id) == SPECIES_CYBORG:
                continue
            self.match.add_exhaustion(player_id, 4)
        charged = self.engine.charge_up_players(self.game, self.match)
        for player_id in charged:
            self.assertEqual(
                self.engine.species_of(player_id), SPECIES_CYBORG,
            )

    def test_charging_up_can_clear_drained(self):
        # A Cyborg sitting on exactly 7 is Drained; dropping to 6
        # clears it, which is why the removal re-tests rather than
        # decrementing the count by hand.
        cyborg = fielded_of_species(self.match, SPECIES_CYBORG)
        self.match.add_exhaustion(cyborg, CYBORG_DRAINED_AT)
        self.engine.retest_exhausted(self.game, self.match, cyborg)
        self.assertIn(cyborg, self.match.exhausted)

        self.match.recover_exhaustion(
            cyborg, 1, self.engine.exhaustion_threshold(self.game, cyborg),
        )
        self.assertNotIn(cyborg, self.match.exhausted)


class SlipInTests(unittest.TestCase):
    """
    "Where a resolution leaves the ball with a particular player and an
    Ooze of the same side is standing on that space, the coach may hand
    the ball to the Ooze instead."
    """

    def setUp(self) -> None:
        self.engine = build_engine()
        self.game = build_game(player_1_team=Team.OOZES)
        self.match = build_match(self.engine, self.game)

    def put_two_on_the_ball(self) -> tuple[str, str]:
        """A carrier and a teammate sharing the ball's space."""
        carrier = self.match.eligible_ball_handlers()[0]
        teammate = next(
            player_id
            for player_id in field_players(self.match)
            if player_id != carrier
        )
        self.match.board.place_meeple(
            teammate, self.match.ball.zone, self.match.ball.space_index,
        )
        self.match.set_ball_carrier(carrier)
        return carrier, teammate

    def test_an_ooze_on_the_ball_may_take_the_carrier_s_turn(self):
        carrier, teammate = self.put_two_on_the_ball()
        candidates = self.engine.turn_handler_candidates(
            self.game, self.match,
        )
        self.assertIn(carrier, candidates)
        self.assertIn(teammate, candidates)

    def test_the_carrier_is_named_first(self):
        # They won the ball; the slip-in is the option beside them.
        carrier, _ = self.put_two_on_the_ball()
        self.assertEqual(
            self.engine.turn_handler_candidates(self.game, self.match)[0],
            carrier,
        )

    def test_without_the_module_the_carrier_takes_the_turn_alone(self):
        carrier, _ = self.put_two_on_the_ball()
        basic = build_game(player_1_team=Team.OOZES, mode=GameMode.BASIC)
        self.assertEqual(
            self.engine.turn_handler_candidates(basic, self.match),
            [carrier],
        )

    def test_a_non_ooze_teammate_may_not_slip_in(self):
        # A colour side fields two of each other species, so this is a
        # real case rather than a hypothetical.
        game = build_game(player_1_team=Team.PURPLE)
        match = build_match(self.engine, game)
        carrier = match.eligible_ball_handlers()[0]
        teammate = next(
            (
                player_id
                for player_id in field_players(match)
                if player_id != carrier
                and self.engine.species_of(player_id) != SPECIES_OOZE
            ),
            None,
        )
        self.assertIsNotNone(teammate)
        match.board.place_meeple(
            teammate, match.ball.zone, match.ball.space_index,
        )
        match.set_ball_carrier(carrier)
        self.assertEqual(
            self.engine.turn_handler_candidates(game, match), [carrier],
        )

    def test_an_opposing_ooze_may_not_slip_in(self):
        # "Of the same side" -- and `eligible_ball_handlers` is already
        # only the possessing team, which is what makes it safe on a
        # space both sides are standing on.
        carrier, _ = self.put_two_on_the_ball()
        opponent = self.match.visiting.field_players[0]
        self.match.board.place_meeple(
            opponent, self.match.ball.zone, self.match.ball.space_index,
        )
        self.assertNotIn(
            opponent,
            self.engine.turn_handler_candidates(self.game, self.match),
        )

    def test_nothing_to_widen_when_no_carrier_was_named(self):
        # A resolution that named nobody leaves the coach the whole
        # choice already.
        self.match.clear_ball_carrier()
        self.assertEqual(
            self.engine.slip_in_candidates(self.game, self.match), [],
        )

    def test_the_click_accepts_the_slip_in(self):
        # `select_ball_handler` validates against the same list the
        # prompt was built from, or the button would be refused.
        carrier, teammate = self.put_two_on_the_ball()
        self.match.select_ball_handler(
            teammate, self.engine.slip_in_candidates(self.game, self.match),
        )
        self.assertEqual(self.match.active_player_id, teammate)

    def test_the_click_still_refuses_somebody_off_the_ball(self):
        self.put_two_on_the_ball()
        away = next(
            player_id
            for player_id in field_players(self.match)
            if player_id not in self.match.eligible_ball_handlers()
        )
        with self.assertRaises(ValueError):
            self.match.select_ball_handler(
                away,
                self.engine.slip_in_candidates(self.game, self.match),
            )


class MergeTests(unittest.TestCase):
    """
    "An Ooze standing there who is **not** one of the two players
    rolling adds to their own side's total ... Every such Ooze adds --
    two of them add twice. An injured Ooze adds nothing."
    """

    def setUp(self) -> None:
        self.engine = build_engine()
        self.game = build_game(player_1_team=Team.OOZES)
        self.match = build_match(self.engine, self.game)
        self.side = self.match.ball.possession
        self.clear_the_ball_space()

    def clear_the_ball_space(self) -> None:
        """
        Empty the ball's space, so a test puts exactly who it means
        there.

        The standard deal already stands somebody on it -- that is
        where the handler comes from -- and Merge sums *every*
        qualifying Ooze, so a fixture that only adds is a fixture
        counting a player it never mentioned.
        """
        for player_id in list(
            self.match.board.spaces[self.match.ball.zone][
                self.match.ball.space_index
            ]
        ):
            self.match.board.place_meeple(
                player_id, Zone.HOME_GOAL, 0,
            )

    def stand_on_the_ball(self, player_id: str) -> None:
        self.match.board.place_meeple(
            player_id, self.match.ball.zone, self.match.ball.space_index,
        )

    def offense_of(self, player_id: str) -> int:
        return self.engine.player_catalog.effective_profile(
            self.engine.get_player_definition(player_id),
        ).offense

    def test_a_bystanding_ooze_adds_their_skill(self):
        roller, bystander = field_players(self.match)[:2]
        self.stand_on_the_ball(roller)
        self.stand_on_the_ball(bystander)
        bonus, lines = self.engine.merge_bonus(
            self.game, self.match, self.side, (roller,), "offense",
        )
        self.assertEqual(bonus, self.offense_of(bystander))
        self.assertEqual(len(lines), 1)

    def test_the_roller_does_not_add_to_themselves(self):
        roller = field_players(self.match)[0]
        self.stand_on_the_ball(roller)
        bonus, lines = self.engine.merge_bonus(
            self.game, self.match, self.side, (roller,), "offense",
        )
        self.assertEqual(bonus, 0)
        self.assertEqual(lines, [])

    def test_two_of_them_add_twice(self):
        roller, first, second = field_players(self.match)[:3]
        for player_id in (roller, first, second):
            self.stand_on_the_ball(player_id)
        bonus, lines = self.engine.merge_bonus(
            self.game, self.match, self.side, (roller,), "offense",
        )
        self.assertEqual(
            bonus, self.offense_of(first) + self.offense_of(second),
        )
        self.assertEqual(len(lines), 2)

    def test_an_injured_ooze_adds_nothing(self):
        roller, bystander = field_players(self.match)[:2]
        self.stand_on_the_ball(roller)
        self.stand_on_the_ball(bystander)
        self.match.mark_injured(bystander)
        bonus, _ = self.engine.merge_bonus(
            self.game, self.match, self.side, (roller,), "offense",
        )
        self.assertEqual(bonus, 0)

    def test_the_skill_asked_for_is_the_side_of_the_contest(self):
        roller, bystander = field_players(self.match)[:2]
        self.stand_on_the_ball(roller)
        self.stand_on_the_ball(bystander)
        attacking, _ = self.engine.merge_bonus(
            self.game, self.match, self.side, (roller,), "offense",
        )
        defending, _ = self.engine.merge_bonus(
            self.game, self.match, self.side, (roller,), "defense",
        )
        profile = self.engine.player_catalog.effective_profile(
            self.engine.get_player_definition(bystander),
        )
        self.assertEqual(attacking, profile.offense)
        self.assertEqual(defending, profile.defense)

    def test_an_ooze_off_the_ball_s_space_adds_nothing(self):
        roller = field_players(self.match)[0]
        self.stand_on_the_ball(roller)
        bonus, _ = self.engine.merge_bonus(
            self.game, self.match, self.side, (roller,), "offense",
        )
        self.assertEqual(bonus, 0)

    def test_a_basic_game_merges_nobody(self):
        roller, bystander = field_players(self.match)[:2]
        self.stand_on_the_ball(roller)
        self.stand_on_the_ball(bystander)
        basic = build_game(player_1_team=Team.OOZES, mode=GameMode.BASIC)
        bonus, lines = self.engine.merge_bonus(
            basic, self.match, self.side, (roller,), "offense",
        )
        self.assertEqual((bonus, lines), (0, []))

    def test_a_non_ooze_bystander_adds_nothing(self):
        game = build_game(player_1_team=Team.PURPLE)
        match = build_match(self.engine, game)
        side = match.ball.possession
        roller = match.setup_for_side(side).field_players[0]
        bystander = next(
            player_id
            for player_id in match.setup_for_side(side).field_players
            if player_id != roller
            and self.engine.species_of(player_id) != SPECIES_OOZE
        )
        for player_id in (roller, bystander):
            match.board.place_meeple(
                player_id, match.ball.zone, match.ball.space_index,
            )
        bonus, _ = self.engine.merge_bonus(
            game, match, side, (roller,), "offense",
        )
        self.assertEqual(bonus, 0)


class BallPathTests(unittest.TestCase):
    """
    "It passes over the space on its way somewhere, or comes to rest on
    it ... The ball's own starting space does not count as moved to."
    """

    def setUp(self) -> None:
        self.engine = build_engine()
        self.game = build_game()
        self.match = build_match(self.engine, self.game)

    def flat(self, step) -> int:
        return self.match.board.flat_index(Zone(step[0]), step[1])

    def test_the_path_excludes_the_start_and_includes_the_end(self):
        origin = self.match.board.flat_index(
            self.match.ball.zone, self.match.ball.space_index,
        )
        target_zone, target_index = self.match.board.position_at_flat_index(
            origin + 3,
        )
        path = self.match.ball_path_to(target_zone, target_index)
        self.assertEqual(
            [self.flat(step) for step in path],
            [origin + 1, origin + 2, origin + 3],
        )

    def test_a_move_of_one_space_is_a_path_of_one(self):
        # The broadening from "through" to "to or through" on
        # 2026-09-06 is exactly what makes a 1-space pass pullable.
        origin = self.match.board.flat_index(
            self.match.ball.zone, self.match.ball.space_index,
        )
        zone, index = self.match.board.position_at_flat_index(origin + 1)
        self.assertEqual(len(self.match.ball_path_to(zone, index)), 1)

    def test_a_move_that_goes_nowhere_is_an_empty_path(self):
        self.assertEqual(
            self.match.ball_path_to(
                self.match.ball.zone, self.match.ball.space_index,
            ),
            [],
        )

    def test_a_backward_move_is_walked_backwards(self):
        origin = self.match.board.flat_index(
            self.match.ball.zone, self.match.ball.space_index,
        )
        zone, index = self.match.board.position_at_flat_index(origin - 2)
        path = self.match.ball_path_to(zone, index)
        self.assertEqual(
            [self.flat(step) for step in path], [origin - 1, origin - 2],
        )

    def test_moving_the_ball_records_the_path(self):
        origin = self.match.board.flat_index(
            self.match.ball.zone, self.match.ball.space_index,
        )
        zone, index = self.match.board.position_at_flat_index(origin + 2)
        self.match.set_ball_space(zone, index)
        self.assertEqual(len(self.match.last_ball_path), 2)

    def test_the_path_survives_a_save(self):
        origin = self.match.board.flat_index(
            self.match.ball.zone, self.match.ball.space_index,
        )
        zone, index = self.match.board.position_at_flat_index(origin + 2)
        self.match.set_ball_space(zone, index)
        restored = MatchState.from_dict(
            self.match.to_dict(), self.engine.basic_ruleset,
        )
        self.assertEqual(restored.last_ball_path, self.match.last_ball_path)

    def test_a_restored_path_does_not_share_its_rows(self):
        # A shallow copy would hand the restored match the same inner
        # lists the saved dict holds.
        origin = self.match.board.flat_index(
            self.match.ball.zone, self.match.ball.space_index,
        )
        zone, index = self.match.board.position_at_flat_index(origin + 1)
        self.match.set_ball_space(zone, index)
        saved = self.match.to_dict()
        restored = MatchState.from_dict(saved, self.engine.basic_ruleset)
        restored.last_ball_path[0][1] = 99
        self.assertNotEqual(saved["last_ball_path"][0][1], 99)


class MindPullCandidateTests(unittest.TestCase):
    """
    Who is offered a pull, and in what order.
    """

    def setUp(self) -> None:
        self.engine = build_engine()
        # The visiting side is the one that pulls, so give *them* the
        # Telekinetics: home holds the ball off the standard deal.
        self.game = build_game(
            player_1_team=Team.PURPLE, player_2_team=Team.TELEKINETICS,
        )
        self.match = build_match(self.engine, self.game)
        self.defending = self.match.defending_side()

    def clear_the_defence_out_of_the_way(self) -> None:
        """
        Park every defending player behind the ball, so a test puts
        exactly who it means on the path.

        The standard deal already stands defenders across midfield --
        which is the whole point of the ability, and exactly what makes
        a fixture that only *adds* to the path count players it never
        mentioned.
        """
        for player_id in self.defenders():
            self.match.board.place_meeple(player_id, Zone.HOME_GOAL, 0)

    def line_up_on_the_path(self, *player_ids) -> None:
        """
        Stand each player one space further along, and move the ball
        past all of them.
        """
        self.clear_the_defence_out_of_the_way()
        origin = self.match.board.flat_index(
            self.match.ball.zone, self.match.ball.space_index,
        )
        for offset, player_id in enumerate(player_ids, start=1):
            zone, index = self.match.board.position_at_flat_index(
                origin + offset,
            )
            self.match.board.place_meeple(player_id, zone, index)
        zone, index = self.match.board.position_at_flat_index(
            origin + len(player_ids),
        )
        self.match.set_ball_space(zone, index)

    def defenders(self) -> list[str]:
        return list(
            self.match.setup_for_side(self.defending).field_players
        )

    def test_a_telekinetic_the_ball_crosses_may_pull(self):
        defender = self.defenders()[0]
        self.line_up_on_the_path(defender)
        self.assertEqual(
            self.engine.mind_pull_candidates(self.game, self.match),
            [defender],
        )

    def test_they_are_offered_in_the_order_the_ball_reaches_them(self):
        first, second = self.defenders()[:2]
        self.line_up_on_the_path(first, second)
        self.assertEqual(
            self.engine.mind_pull_candidates(self.game, self.match),
            [first, second],
        )

    def test_the_ball_s_own_starting_space_is_not_crossed(self):
        # Somebody standing where the ball already is gets no roll.
        self.clear_the_defence_out_of_the_way()
        defender = self.defenders()[0]
        self.match.board.place_meeple(
            defender, self.match.ball.zone, self.match.ball.space_index,
        )
        self.match.last_ball_path = []
        self.assertEqual(
            self.engine.mind_pull_candidates(self.game, self.match), [],
        )

    def test_a_telekinetic_on_the_possessing_side_may_not_pull(self):
        # "Only the opposing team's ball."
        game = build_game(
            player_1_team=Team.TELEKINETICS, player_2_team=Team.PURPLE,
        )
        match = build_match(self.engine, game)
        teammate = match.setup_for_side(match.ball.possession).field_players[0]
        origin = match.board.flat_index(
            match.ball.zone, match.ball.space_index,
        )
        zone, index = match.board.position_at_flat_index(origin + 1)
        match.board.place_meeple(teammate, zone, index)
        match.set_ball_space(zone, index)
        self.assertEqual(
            self.engine.mind_pull_candidates(game, match), [],
        )

    def test_an_injured_telekinetic_may_not_pull(self):
        # They cannot pay the token, so they are never offered the
        # roll -- `add_exhaustion` would refuse it silently.
        defender = self.defenders()[0]
        self.line_up_on_the_path(defender)
        self.match.mark_injured(defender)
        self.assertEqual(
            self.engine.mind_pull_candidates(self.game, self.match), [],
        )

    def test_a_non_telekinetic_never_pulls(self):
        game = build_game(
            player_1_team=Team.PURPLE, player_2_team=Team.OOZES,
        )
        match = build_match(self.engine, game)
        defender = match.setup_for_side(
            match.defending_side(),
        ).field_players[0]
        origin = match.board.flat_index(
            match.ball.zone, match.ball.space_index,
        )
        zone, index = match.board.position_at_flat_index(origin + 1)
        match.board.place_meeple(defender, zone, index)
        match.set_ball_space(zone, index)
        self.assertEqual(self.engine.mind_pull_candidates(game, match), [])

    def test_a_basic_game_offers_nobody_a_pull(self):
        defender = self.defenders()[0]
        self.line_up_on_the_path(defender)
        basic = build_game(
            player_1_team=Team.PURPLE,
            player_2_team=Team.TELEKINETICS,
            mode=GameMode.BASIC,
        )
        self.assertEqual(
            self.engine.mind_pull_candidates(basic, self.match), [],
        )

    def test_nobody_is_offered_twice_for_one_movement(self):
        defender = self.defenders()[0]
        self.line_up_on_the_path(defender)
        candidates = self.engine.mind_pull_candidates(self.game, self.match)
        self.assertEqual(len(candidates), len(set(candidates)))


class MindPullOutcomeTests(unittest.TestCase):
    """
    What a pull that lands does to the match.
    """

    def setUp(self) -> None:
        self.engine = build_engine()
        self.game = build_game(
            player_1_team=Team.PURPLE, player_2_team=Team.TELEKINETICS,
        )
        self.match = build_match(self.engine, self.game)
        self.puller = self.match.setup_for_side(
            self.match.defending_side(),
        ).field_players[0]
        origin = self.match.board.flat_index(
            self.match.ball.zone, self.match.ball.space_index,
        )
        self.zone, self.index = self.match.board.position_at_flat_index(
            origin + 1,
        )
        self.match.board.place_meeple(self.puller, self.zone, self.index)

    def test_the_ball_stops_on_their_space(self):
        self.match.apply_mind_pull(self.puller)
        self.assertEqual(
            (self.match.ball.zone, self.match.ball.space_index),
            (self.zone, self.index),
        )

    def test_their_side_takes_possession_and_they_hold_it(self):
        was = self.match.ball.possession
        self.match.apply_mind_pull(self.puller)
        self.assertNotEqual(self.match.ball.possession, was)
        self.assertEqual(
            self.match.ball.possession,
            self.match.side_for_player(self.puller),
        )
        self.assertEqual(self.match.ball_carrier_id, self.puller)

    def test_the_carrier_is_what_exempts_them_from_running_back(self):
        # `begin_run_back` reads the exemption off `ball_carrier_id`,
        # so setting it is the whole of arranging that -- the puller
        # must not be run off the ball they just took.
        self.match.apply_mind_pull(self.puller)
        self.match.pending_run_back_stays_player_id = (
            self.match.ball_carrier_id
        )
        self.assertNotIn(
            self.puller,
            self.engine.run_back_displaced(
                self.match, self.match.side_for_player(self.puller),
            ),
        )

    def test_the_pull_clears_the_path_and_the_queue(self):
        # Or the same movement would offer the same pull again at the
        # next arrival point.
        self.match.last_ball_path = [[self.zone.value, self.index]]
        self.match.pending_mind_pull = [self.puller]
        self.match.apply_mind_pull(self.puller)
        self.assertEqual(self.match.last_ball_path, [])
        self.assertEqual(self.match.pending_mind_pull, [])

    def test_the_queue_and_the_resume_survive_a_save(self):
        # A coach may take minutes over the offer, and between the
        # interrupt and the answer these are the only thing on the
        # match saying what the ball was about to do.
        self.match.pending_mind_pull = [self.puller]
        self.match.pending_mind_pull_resume = {
            "kind": "finish_maneuver", "distance_moved": 2,
        }
        restored = MatchState.from_dict(
            self.match.to_dict(), self.engine.basic_ruleset,
        )
        self.assertEqual(restored.pending_mind_pull, [self.puller])
        self.assertEqual(
            restored.pending_mind_pull_resume["distance_moved"], 2,
        )

    def test_a_save_written_before_the_fields_pulls_nothing(self):
        saved = self.match.to_dict()
        for field_name in (
            "last_ball_path", "pending_mind_pull", "pending_mind_pull_resume",
        ):
            saved.pop(field_name, None)
        restored = MatchState.from_dict(saved, self.engine.basic_ruleset)
        self.assertEqual(restored.last_ball_path, [])
        self.assertEqual(restored.pending_mind_pull, [])
        self.assertIsNone(restored.pending_mind_pull_resume)

    def test_the_turn_reset_clears_all_three(self):
        self.match.last_ball_path = [[self.zone.value, self.index]]
        self.match.pending_mind_pull = [self.puller]
        self.match.pending_mind_pull_resume = {"kind": "finish_maneuver"}
        self.match.reset_maneuver()
        self.assertEqual(self.match.last_ball_path, [])
        self.assertEqual(self.match.pending_mind_pull, [])
        self.assertIsNone(self.match.pending_mind_pull_resume)

    def test_the_success_faces_are_the_rules_numbers(self):
        self.assertEqual(MIND_PULL_SUCCESS_FACES, (1, 2))
        self.assertEqual(MIND_PULL_TOKEN_COST, 1)


def build_mind_pull_cog() -> D12Ball:
    """
    A cog with just enough on it to drive an arrival through the real
    `finish_maneuver_resolution`.

    The gate is the whole point of these tests, so it is emphatically
    **not** mocked -- unlike the fixtures in the suites that are about
    something else.
    """
    cog = object.__new__(D12Ball)
    cog.games = {}
    cog.player_catalog = load_player_catalog()
    cog.maneuver_catalog = load_maneuver_catalog()
    cog.basic_ruleset = load_basic_ruleset()
    cog.team_emojis = {}
    cog.condition_emojis = {}
    cog.coin_emojis = {}
    cog.ai_strategies = build_ai_strategies(
        cog.player_catalog, cog.maneuver_catalog,
    )
    cog.engine = RulesEngine(
        cog.player_catalog,
        cog.basic_ruleset,
        cog.maneuver_catalog,
        cog.ai_strategies,
    )
    cog.refresh_match_image = mock.AsyncMock()
    cog.send_turn_prompt = mock.AsyncMock()
    cog.check_for_loose_ball = mock.AsyncMock(return_value=False)
    cog.begin_run_back = mock.AsyncMock()
    cog.render_match_png = mock.AsyncMock(return_value=b"png")
    cog.match_file_from_png = mock.Mock(return_value=None)
    cog.build_match_file = mock.AsyncMock(return_value=None)
    cog.bot = SimpleNamespace(get_channel=lambda channel_id: None)
    return cog


def build_mind_pull_interaction() -> SimpleNamespace:
    sent = SimpleNamespace(id=999, attachments=[])
    return SimpleNamespace(
        user=SimpleNamespace(id=222, display_name="Two"),
        guild=None,
        channel=None,
        response=SimpleNamespace(
            defer=mock.AsyncMock(),
            edit_message=mock.AsyncMock(),
            send_message=mock.AsyncMock(),
        ),
        followup=SimpleNamespace(send=mock.AsyncMock(return_value=sent)),
        edit_original_response=mock.AsyncMock(),
    )


class MindPullInterruptTests(unittest.IsolatedAsyncioTestCase):
    """
    The gate itself, through the real cog.

    `mind_pull_candidates` answering correctly is not the same claim as
    the turn actually stopping to ask -- the interrupt is three gates
    and a resume, and a gate wired to the wrong function, or one that
    forgets to spend the path, is invisible to a unit test on the
    engine.
    """

    def setUp(self) -> None:
        self.cog = build_mind_pull_cog()
        self.game = build_game(
            player_1_team=Team.PURPLE, player_2_team=Team.TELEKINETICS,
        )
        self.cog.games[self.game.game_id] = self.game
        self.match = self.cog.engine.initialize_standard_match(self.game)
        self.interaction = build_mind_pull_interaction()

        defending = self.match.defending_side()
        for player_id in self.match.setup_for_side(defending).field_players:
            self.match.board.place_meeple(player_id, Zone.HOME_GOAL, 0)
        self.puller = self.match.setup_for_side(defending).field_players[0]

        origin = self.match.board.flat_index(
            self.match.ball.zone, self.match.ball.space_index,
        )
        zone, index = self.match.board.position_at_flat_index(origin + 1)
        self.match.board.place_meeple(self.puller, zone, index)
        self.match.set_ball_space(zone, index)

    def sent_views(self) -> list:
        return [
            call.kwargs.get("view")
            for call in self.interaction.followup.send.await_args_list
        ]

    async def test_a_crossed_telekinetic_stops_the_turn_to_ask(self):
        with suppressed_cog_saves():
            await self.cog.finish_maneuver_resolution(
                self.interaction, self.game, self.match, distance_moved=1,
            )
        self.assertTrue(
            any(isinstance(view, MindPullView) for view in self.sent_views()),
        )
        self.assertEqual(self.match.pending_mind_pull, [self.puller])
        # The arrival it interrupted is remembered, not lost.
        self.assertEqual(
            self.match.pending_mind_pull_resume["kind"], "finish_maneuver",
        )
        # And the turn did not carry on underneath the question.
        self.cog.send_turn_prompt.assert_not_awaited()

    async def test_the_path_is_spent_so_one_movement_asks_once(self):
        # `finish_maneuver_resolution` gates and then calls
        # `check_for_loose_ball`, which reaches the second gate; the
        # spent path is what stops that asking again.
        with suppressed_cog_saves():
            await self.cog.finish_maneuver_resolution(
                self.interaction, self.game, self.match, distance_moved=1,
            )
        self.assertEqual(self.match.last_ball_path, [])
        self.assertFalse(
            self.cog.engine.mind_pull_candidates(self.game, self.match),
        )

    async def test_a_movement_crossing_nobody_does_not_interrupt(self):
        self.match.board.place_meeple(self.puller, Zone.HOME_GOAL, 0)
        self.match.last_ball_path = []
        with suppressed_cog_saves():
            interrupted = await self.cog.check_for_mind_pull(
                self.interaction, self.game, self.match, {"kind": "x"},
            )
        self.assertFalse(interrupted)
        self.assertEqual(self.match.pending_mind_pull, [])

    async def test_a_basic_game_never_interrupts(self):
        basic = build_game(
            player_1_team=Team.PURPLE,
            player_2_team=Team.TELEKINETICS,
            mode=GameMode.BASIC,
        )
        self.cog.games[basic.game_id] = basic
        with suppressed_cog_saves():
            interrupted = await self.cog.check_for_mind_pull(
                self.interaction, basic, self.match, {"kind": "x"},
            )
        self.assertFalse(interrupted)

    async def test_declining_the_last_offer_resumes_the_arrival(self):
        # The queue's one exit: a coach who declines has to leave the
        # turn exactly where the pull found it.
        self.match.pending_mind_pull = []
        self.match.pending_mind_pull_resume = {
            "kind": "finish_maneuver", "distance_moved": 1,
        }
        self.cog.finish_maneuver_resolution = mock.AsyncMock()
        with suppressed_cog_saves():
            await self.cog.continue_mind_pull(
                self.interaction, self.game, self.match,
            )
        # The dispatch itself is the claim, not whatever
        # `finish_maneuver_resolution` goes on to do with it.
        self.cog.finish_maneuver_resolution.assert_awaited()
        self.assertIsNone(self.match.pending_mind_pull_resume)

    async def test_dinky_is_never_asked(self):
        # "Dinky never pulls" -- an AI side's Telekinetics are skipped
        # rather than prompted, which is also what keeps this flow free
        # of an AI branch.
        solo = build_game(
            player_1_team=Team.PURPLE,
            player_2_team=Team.TELEKINETICS,
            player_2_id=None,
            ai_opponent=AIOpponent.DINKY,
        )
        self.cog.games[solo.game_id] = solo
        self.cog.finish_maneuver_resolution = mock.AsyncMock()
        self.match.pending_mind_pull = [self.puller]
        self.match.pending_mind_pull_resume = {
            "kind": "finish_maneuver", "distance_moved": 1,
        }
        with suppressed_cog_saves():
            await self.cog.continue_mind_pull(
                self.interaction, solo, self.match,
            )
        self.assertFalse(
            any(isinstance(view, MindPullView) for view in self.sent_views()),
        )
        self.assertEqual(self.match.pending_mind_pull, [])
        self.cog.finish_maneuver_resolution.assert_awaited()

    async def test_a_pull_that_lands_turns_the_ball_over(self):
        self.match.pending_mind_pull = [self.puller]
        self.match.pending_mind_pull_resume = {
            "kind": "finish_maneuver", "distance_moved": 2,
        }
        was = self.match.ball.possession
        with suppressed_cog_saves(), mock.patch(
            "random.randint", return_value=MIND_PULL_SUCCESS_FACES[0],
        ):
            await self.cog.run_mind_pull(
                self.interaction, self.game, self.match, self.puller,
            )

        self.assertNotEqual(self.match.ball.possession, was)
        self.assertEqual(self.match.ball_carrier_id, self.puller)
        self.assertEqual(self.match.ball.speed, 1)
        self.assertEqual(
            self.match.exhaustion.get(self.puller), MIND_PULL_TOKEN_COST,
        )
        # A pull is a steal, so it runs everyone back -- and carries the
        # interrupted maneuver's own clock cost with it.
        self.cog.begin_run_back.assert_awaited()
        self.assertEqual(
            self.cog.begin_run_back.await_args.kwargs["distance_moved"], 2,
        )
        # The arrival it pre-empted never happens.
        self.assertIsNone(self.match.pending_mind_pull_resume)

    async def test_a_pull_that_misses_still_costs_the_token(self):
        self.match.pending_mind_pull = [self.puller]
        self.match.pending_mind_pull_resume = {
            "kind": "finish_maneuver", "distance_moved": 1,
        }
        was = self.match.ball.possession
        self.cog.finish_maneuver_resolution = mock.AsyncMock()
        with suppressed_cog_saves(), mock.patch(
            "random.randint", return_value=12,
        ):
            await self.cog.run_mind_pull(
                self.interaction, self.game, self.match, self.puller,
            )

        self.assertEqual(self.match.ball.possession, was)
        self.assertEqual(
            self.match.exhaustion.get(self.puller), MIND_PULL_TOKEN_COST,
        )
        self.cog.begin_run_back.assert_not_awaited()
        # And the arrival it was holding back goes ahead.
        self.cog.finish_maneuver_resolution.assert_awaited()

    async def test_a_restart_mid_offer_puts_the_same_question_back(self):
        self.match.pending_mind_pull = [self.puller]
        view, prompt = self.cog.pending_turn_view(
            self.game.game_id, self.match,
        )
        self.assertIsInstance(view, MindPullView)
        self.assertIn("reach", prompt)


if __name__ == "__main__":
    unittest.main()
