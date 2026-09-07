"""
Species abilities: the module switch they ride on, and Volatile.

Three layers, and they fail for different reasons:

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
from unittest import mock

from d12ball.ai import build_ai_strategies
from d12ball.components import (
    SPECIES_CYBORG,
    SPECIES_FIRE_DEMON,
    SPECIES_OOZE,
    SPECIES_TELEKINETIC,
    MatchState,
    TeamSide,
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
    D12BallGame,
    GameMode,
    GameStatus,
    Team,
)

from roster import fielded_of_species


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


if __name__ == "__main__":
    unittest.main()
