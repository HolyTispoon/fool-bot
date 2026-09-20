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
  through. On top of it the rider has two halves, both read off the
  igniting player's own die: `volatile_raises_tier` plus
  `resolving_maneuver` for the winner's tier, and
  `volatile_loser_cost` plus `advanced_cost` for whether the loser
  pays their advanced card's price.
- **Lithium Powered.** Three separate things sharing one ability: the
  Drained line (`exhaustion_threshold`, which every exhaustion charge
  and every recovery now asks), Overdrive (declared and paid before a
  roll, spent by it), and Charge-up (`charge_up_players`, read off who
  actually *moved* during the run back -- which is what makes a stack
  a decision).
- **Slimey.** Merge is a sum over the bystanders, not a pick, and
  Spreadable is a passive occupancy exemption over every fielded Ooze.
- **Mind Pull**, which is the one ability that interrupts a maneuver
  rather than modifying it. Three layers again: the path
  (`ball_path_to`, recorded by `set_ball_space`), who it offers a pull
  to (`mind_pull_candidates`), and the gate actually stopping the turn
  to ask -- that last one through the **real cog**, because a gate
  wired to the wrong function, or one that forgets to spend the path,
  is invisible to a unit test on the engine. Slip in widens
  `turn_handler_candidates` rather than adding to it -- a Telekinetic
  on the ball is already an eligible handler (moved here from Slimey,
  2026-09-20).

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
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from cogs.d12ball import D12Ball
from cogs.d12ball_views import (
    MindPullView,
    OwnGoalRollView,
    SkillTestView,
    SmoothView,
)
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
from d12ball.flow.effects import shove_pressured_handler
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
from cogs.d12ball_helpers import get_damaged_emoji, get_injured_emoji

from roster import field_players, fielded_of_species
from save_patches import suppressed_cog_saves, suppressed_view_saves


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

    def test_the_explanation_carries_both_dice_and_the_modifier(self):
        # The sentence beside the ignition die. Not asserted as prose
        # -- it will be revised -- but every number in it is one the
        # coach has to be able to check against the image.
        with mock.patch("random.randint", return_value=9):
            surge = self.engine.ignite(self.game, self.demon, 6)
        sentence = surge.explain("Somebody")
        self.assertIn("Somebody", sentence)
        self.assertIn("6", sentence)
        self.assertIn("9", sentence)
        self.assertIn("+9", sentence)
        self.assertIn("surge", sentence)

    def test_a_backfire_explains_itself_as_a_subtraction(self):
        with mock.patch("random.randint", return_value=2):
            backfire = self.engine.ignite(self.game, self.demon, 7)
        sentence = backfire.explain("Somebody")
        self.assertIn("backfire", sentence)
        self.assertIn("-2", sentence)

    def test_a_roll_that_did_not_ignite_explains_nothing(self):
        # The same silence `detail` keeps, and what lets a caller hand
        # both sides of a contest to post_volatile_ignition without
        # asking which of them ignited.
        ordinary = self.engine.ignite(self.game, self.demon, 4)
        self.assertIsNone(ordinary.explain("X"))
        self.assertIsNone(IgnitedRoll(face=4).explain("X"))


def build_ignition_cog() -> D12Ball:
    """
    A cog with enough on it to post an ignition die and to run a real
    skill test into one. Everything past the roll is mocked; the
    posting itself emphatically is not, since it is what these tests
    are about.
    """
    cog = object.__new__(D12Ball)
    cog.games = {}
    cog.player_catalog = load_player_catalog()
    cog.maneuver_catalog = load_maneuver_catalog()
    cog.basic_ruleset = load_basic_ruleset()
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
    cog.begin_injury_tests = mock.AsyncMock()
    return cog


def build_ignition_interaction() -> SimpleNamespace:
    # `channel.send` and `followup.send` share one mock: which route a
    # post takes depends on whether the interaction still had a response
    # to give, and these tests read the ignition posts back off
    # `followup.send` regardless of which route actually carried them.
    send = mock.AsyncMock(return_value=SimpleNamespace(id=999))
    return SimpleNamespace(
        user=SimpleNamespace(id=111, display_name="One"),
        guild=None,
        channel=SimpleNamespace(send=send),
        response=SimpleNamespace(
            defer=mock.AsyncMock(),
            edit_message=mock.AsyncMock(),
            send_message=mock.AsyncMock(),
            is_done=lambda: True,
        ),
        followup=SimpleNamespace(send=send),
        edit_original_response=mock.AsyncMock(),
    )


def followup_messages(interaction) -> list[str]:
    """Every followup's content, in the order they were sent."""
    return [
        (call.args[0] if call.args else call.kwargs.get("content")) or ""
        for call in interaction.followup.send.await_args_list
    ]


class VolatileIgnitionDieTests(unittest.IsolatedAsyncioTestCase):
    """
    The second die a coach watches.

    An ignite used to be a line in the totals column of the roll's own
    dice image and nothing else, which left the face a coach could see
    and the total they were given disagreeing with nothing to explain
    the gap. It is a die of its own now -- see
    `D12Ball.post_volatile_ignition` -- and what is asserted here is
    that it is posted, once per ignited roll, in the order the roll
    happened.
    """

    def setUp(self) -> None:
        self.cog = build_ignition_cog()
        self.game = build_game()
        self.cog.games[self.game.game_id] = self.game
        self.match = build_match(self.cog.engine, self.game)
        self.demon = fielded_of_species(self.match, SPECIES_FIRE_DEMON)

    def ignite(self, face: int, second: int) -> IgnitedRoll:
        with mock.patch("random.randint", return_value=second):
            return self.cog.engine.ignite(self.game, self.demon, face)

    async def test_an_ignited_roll_is_posted_with_its_own_die(self) -> None:
        interaction = build_ignition_interaction()

        await self.cog.post_volatile_ignition(
            interaction, self.match, (self.demon, self.ignite(6, 9)),
        )

        interaction.followup.send.assert_awaited_once()
        call = interaction.followup.send.await_args
        self.assertIn("Volatile", call.args[0])
        self.assertIsNotNone(call.kwargs.get("file"))

    async def test_a_roll_that_did_not_ignite_is_not_posted(self) -> None:
        # Most rolls in an advanced game and every roll in a basic one.
        interaction = build_ignition_interaction()

        await self.cog.post_volatile_ignition(
            interaction, self.match, (self.demon, self.ignite(4, 9)),
        )

        interaction.followup.send.assert_not_awaited()

    async def test_each_side_of_a_contest_gets_its_own(self) -> None:
        # Two Fire Demons rolling means two ignites, each read off its
        # own die -- so two dice, not one image about both.
        other = self.match.home.field_players[1]
        interaction = build_ignition_interaction()

        await self.cog.post_volatile_ignition(
            interaction,
            self.match,
            (self.demon, self.ignite(6, 9)),
            (other, self.ignite(7, 2)),
        )

        self.assertEqual(interaction.followup.send.await_count, 2)

    async def test_a_die_belonging_to_nobody_is_skipped(self) -> None:
        # A score attempt's defensive die has no card behind it, so a
        # caller may pass None rather than branching on it.
        interaction = build_ignition_interaction()

        await self.cog.post_volatile_ignition(
            interaction, self.match, (None, IgnitedRoll(face=6)),
        )

        interaction.followup.send.assert_not_awaited()

    async def test_a_real_skill_test_posts_it_between_roll_and_result(
        self,
    ) -> None:
        # The claim the unit tests above cannot make: a roll site
        # actually hands its ignites over, and does it after the dice
        # image and before the verdict. Every other order reads as the
        # result of a roll the coach has not been shown yet.
        offense = self.match.home.field_players[0]
        zone, space_index = self.match.board.meeple_position(offense)
        self.match.ball.possession = TeamSide.HOME
        self.match.set_ball_space(zone, space_index)
        self.match.active_player_id = offense
        challenger = self.match.visiting.field_players[0]
        self.match.board.place_meeple(challenger, zone, space_index)
        self.match.challenger_id = challenger
        self.match.offense_maneuver = "low_pass"
        self.match.defense_maneuver = "deflect"
        self.game.match_state = self.match.to_dict()

        interaction = build_ignition_interaction()
        view = SkillTestView(self.cog, self.game.game_id)
        # The offense rolls a natural 6 and ignites on a 9; the
        # defense's 1 does not, whoever they are.
        with suppressed_cog_saves(), suppressed_view_saves(), mock.patch(
            "random.randint", side_effect=[6, 1, 9],
        ), mock.patch(
            "cogs.d12ball_views.base.render_skill_test_dice",
        ), mock.patch("discord.File"):
            await view.roll(interaction)

        messages = followup_messages(interaction)
        ignition = [
            index for index, text in enumerate(messages)
            if "Volatile" in text and "ignites" in text
        ]
        result = [
            index for index, text in enumerate(messages)
            if "wins the skill test" in text
        ]
        self.assertEqual(len(ignition), 1, messages)
        self.assertEqual(len(result), 1, messages)
        self.assertLess(ignition[0], result[0], messages)
        # The dice image is on the message the prompt became, which is
        # above both of them.
        interaction.edit_original_response.assert_awaited()


class IgnitionIsShownEverywhereTests(unittest.TestCase):
    """
    A roll site may not swallow its second die.

    `RulesEngine.ignite` is the funnel every d12 comes through, and
    every one of its callers now owes the coach the die it rolled --
    which is a claim about *all* of them and so cannot be made by a
    test that drives one. A new roll site is written by copying an old
    one, and the arithmetic works perfectly well with the image left
    out, so nothing else would notice.
    """

    def source_files(self) -> list:
        root = Path(__file__).resolve().parent.parent / "cogs"
        return sorted(root.rglob("*.py"))

    def test_every_module_that_ignites_also_posts_the_die(self) -> None:
        asked = []
        for path in self.source_files():
            source = path.read_text(encoding="utf-8")
            if ".ignite(" not in source:
                continue
            asked.append(path.name)
            self.assertIn(
                "post_volatile_ignition",
                source,
                f"{path.name} rolls an ignite and never shows it",
            )
        # The funnel's six roll sites live in five modules; a count
        # that drops is a site that stopped asking rather than one
        # that stopped showing, and is worth a look either way.
        self.assertGreaterEqual(len(asked), 5, asked)


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

    def test_a_surge_that_loses_pays_no_advanced_cost(self):
        # "If a player loses a skill test on the surge, they do not
        # resolve the advanced maneuver cost." A surge protects its
        # player even where the cards would have charged them.
        self.assertIs(
            self.engine.volatile_loser_cost(self.game, self.surge), False,
        )

    def test_a_backfire_that_loses_pays_it(self):
        # "However, if a volatile player loses on a backfire, they
        # resolve the cost of the advanced maneuver" -- the one thing
        # in the game that puts a cost in force off the dice.
        self.assertIs(
            self.engine.volatile_loser_cost(self.game, self.backfire), True,
        )

    def test_a_loser_who_did_not_ignite_falls_back_to_the_cards(self):
        self.assertIsNone(
            self.engine.volatile_loser_cost(self.game, self.plain),
        )

    def test_no_cost_to_change_without_the_advanced_maneuvers(self):
        without = build_game(advanced_maneuvers=False)
        for ignite in (self.surge, self.backfire, self.plain):
            self.assertIsNone(
                self.engine.volatile_loser_cost(without, ignite),
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

    def test_a_surge_that_lost_suppresses_a_cost_the_cards_would_charge(self):
        # The cards were decisive and the loser played an advanced
        # card, so `advanced_cost_applies` would charge them -- the
        # surge is what takes it off.
        self.match.offense_maneuver = "dribble_advance"
        self.match.defense_maneuver = "clear"
        self.assertTrue(
            self.engine.advanced_cost_applies(self.match, "clear"),
        )
        self.assertEqual(
            self.engine.advanced_cost(self.match, "dribble_advance"), "clear",
        )

        self.match.volatile_loser_cost = False
        self.assertIsNone(
            self.engine.advanced_cost(self.match, "dribble_advance"),
        )

    def test_a_backfire_that_lost_pays_where_the_cards_would_not(self):
        # A tie carries no advanced effect at all, so nothing here is
        # chargeable off the cards -- the backfire is the whole reason
        # a cost applies.
        self.match.offense_maneuver = "low_pass"
        self.match.defense_maneuver = "clear"
        if self.engine.maneuver_catalog.resolve(
            "low_pass", "clear",
        ) != "tie":
            self.skipTest("that pairing is no longer a tie")
        self.assertFalse(
            self.engine.advanced_cost_applies(self.match, "clear"),
        )
        self.assertIsNone(self.engine.advanced_cost(self.match, "low_pass"))

        self.match.volatile_loser_cost = True
        self.assertEqual(
            self.engine.advanced_cost(self.match, "low_pass"), "clear",
        )

    def test_a_basic_losing_card_carries_no_cost_either_way(self):
        # The override decides *whether* an advanced cost applies, not
        # whether there is one: a basic card has none to pay.
        self.match.offense_maneuver = "dribble_advance"
        self.match.defense_maneuver = "deflect"
        for override in (True, False, None):
            self.match.volatile_loser_cost = override
            self.assertIsNone(
                self.engine.advanced_cost(self.match, "dribble_advance"),
                override,
            )

    def test_the_cost_override_survives_a_save(self):
        for override in (True, False, None):
            self.match.volatile_loser_cost = override
            restored = MatchState.from_dict(
                self.match.to_dict(), self.engine.basic_ruleset,
            )
            self.assertIs(restored.volatile_loser_cost, override)

    def test_a_save_written_before_the_cost_field_falls_back_to_the_cards(self):
        saved = self.match.to_dict()
        saved.pop("volatile_loser_cost", None)
        restored = MatchState.from_dict(saved, self.engine.basic_ruleset)
        self.assertIsNone(restored.volatile_loser_cost)

    def test_the_turn_reset_clears_the_cost_override(self):
        self.match.volatile_loser_cost = True
        self.match.reset_maneuver()
        self.assertIsNone(self.match.volatile_loser_cost)

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


class DamagedWordingTests(unittest.TestCase):
    """
    "A Cyborg who fails an injury check is Damaged, not Injured ...
    Only the word (and the token art) is a Cyborg's own." Nothing here
    asserts a message's prose -- only that the Damaged/Injured choice
    tracks `has_species_ability` the same way Drained/Exhausted already
    does, and that the underlying condition (`match.injured`) is
    unaffected either way.
    """

    def setUp(self) -> None:
        self.cog = build_ignition_cog()
        self.game = build_game(player_1_team=Team.CYBORGS)
        self.match = build_match(self.cog.engine, self.game)
        self.cyborg = fielded_of_species(self.match, SPECIES_CYBORG)
        self.other = fielded_of_species(
            self.match, SPECIES_FIRE_DEMON, TeamSide.VISITING,
        )

    def test_a_cyborg_reads_as_damaged(self) -> None:
        word, emoji = self.cog.injured_word_and_emoji(self.game, self.cyborg)
        self.assertEqual(word, "damaged")
        self.assertEqual(emoji, get_damaged_emoji(self.cog.condition_emojis))

    def test_a_non_cyborg_reads_as_injured(self) -> None:
        word, emoji = self.cog.injured_word_and_emoji(self.game, self.other)
        self.assertEqual(word, "injured")
        self.assertEqual(emoji, get_injured_emoji(self.cog.condition_emojis))

    def test_a_basic_game_gives_a_cyborg_no_such_thing(self) -> None:
        basic = build_game(player_1_team=Team.CYBORGS, mode=GameMode.BASIC)
        word, _ = self.cog.injured_word_and_emoji(basic, self.cyborg)
        self.assertEqual(word, "injured")

    def test_the_underlying_condition_is_untouched(self) -> None:
        # Damaged is a word, not a second condition -- mark_injured
        # writes the one `match.injured` set either way.
        self.match.mark_injured(self.cyborg)
        self.assertIn(self.cyborg, self.match.injured)

    def test_describe_exhaustion_gain_calls_a_damaged_cyborg_damaged(
        self,
    ) -> None:
        self.match.mark_injured(self.cyborg)
        text = self.cog.describe_exhaustion_gain(
            self.game, self.match, self.cyborg, 1,
        )
        self.assertIn("damaged", text)
        self.assertIn("drain tokens", text)
        self.assertNotIn("injured", text)

    def test_cyborg_condition_ids_answers_off_exhausted_and_injured(
        self,
    ) -> None:
        self.match.exhaustion[self.cyborg] = CYBORG_DRAINED_AT
        self.match.exhausted.add(self.cyborg)
        self.assertEqual(
            self.cog.cyborg_condition_ids(self.game, self.match),
            frozenset({self.cyborg}),
        )
        # A non-Cyborg who is Exhausted/Injured never joins the set.
        self.match.exhaustion[self.other] = 99
        self.match.exhausted.add(self.other)
        self.assertNotIn(
            self.other, self.cog.cyborg_condition_ids(self.game, self.match),
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
    "Whenever players run back, a Cyborg who **does not move** removes
    1 drain token. Once per run back, never below zero."

    **It is about movement, not about being obliged to move** (the
    author, 2026-09-07). The first build read it as the complement of
    `run_back_displaced` -- who *had* to return -- which charged up
    both players of a stack whichever one the coach then sent. What it
    reads now is `run_back_moved`, which `run_back_player` fills in as
    it places people.
    """

    def setUp(self) -> None:
        self.engine = build_engine()
        self.game = build_game(player_1_team=Team.CYBORGS)
        self.match = build_match(self.engine, self.game)

    def charged(self) -> list[str]:
        return self.engine.charge_up_players(self.game, self.match)

    def test_a_cyborg_who_did_not_move_charges_up(self):
        cyborg = fielded_of_species(self.match, SPECIES_CYBORG)
        self.match.add_exhaustion(cyborg, 4)
        self.assertIn(cyborg, self.charged())

    def test_a_cyborg_who_moved_does_not(self):
        cyborg = fielded_of_species(self.match, SPECIES_CYBORG)
        self.match.add_exhaustion(cyborg, 4)
        self.match.run_back_moved = [cyborg]
        self.assertNotIn(cyborg, self.charged())

    def test_being_displaced_is_not_what_decides_it(self):
        # The correction, stated as a test: a player standing outside
        # their own zone has not charged anything up *yet* -- they have
        # to return, and it is the returning that costs them. Until
        # they actually move, they are simply someone who has not
        # moved.
        cyborg = fielded_of_species(self.match, SPECIES_CYBORG)
        self.match.add_exhaustion(cyborg, 4)
        self.match.board.place_meeple(cyborg, Zone.VISITORS_GOAL, 0)
        self.assertIn(cyborg, self.charged())

        self.match.run_back_moved = [cyborg]
        self.assertNotIn(cyborg, self.charged())

    def test_a_stack_is_the_coach_s_decision(self):
        # "In the case of a stacked player, charging up may be a
        # consideration for the coach." Two Cyborgs on one space, one
        # of whom must go: the one sent loses their token, the one left
        # keeps theirs -- so holding a Cyborg still is a real reason to
        # send somebody else.
        first, second = field_players(self.match)[:2]
        for player_id in (first, second):
            self.match.add_exhaustion(player_id, 4)

        # Nobody has moved yet, so both would charge up.
        charged = self.charged()
        self.assertIn(first, charged)
        self.assertIn(second, charged)

        # The coach sends the first; only the second still charges up.
        self.match.run_back_moved = [first]
        charged = self.charged()
        self.assertNotIn(first, charged)
        self.assertIn(second, charged)

    def test_the_carrier_who_never_runs_back_charges_up(self):
        # They are named in the rules, and they fall out for free:
        # nothing moves them, so they are not in `run_back_moved`.
        cyborg = fielded_of_species(self.match, SPECIES_CYBORG)
        self.match.add_exhaustion(cyborg, 4)
        self.match.board.place_meeple(cyborg, Zone.VISITORS_GOAL, 0)
        self.match.pending_run_back_stays_player_id = cyborg
        self.assertIn(cyborg, self.charged())

    def test_run_back_player_records_the_move(self):
        # The recording is what the whole rule now rests on, so it is
        # asserted on the model rather than only through the cog.
        mover = field_players(self.match)[0]
        zone = self.match.home.assigned_zone(mover)
        space = self.match.placement_spaces_in_zone(
            TeamSide.HOME, zone, mover,
        )[0]
        self.match.run_back_player(mover, zone, space)
        self.assertIn(mover, self.match.run_back_moved)

    def test_never_below_zero(self):
        # A Cyborg carrying nothing has nothing to take off, and says
        # nothing about it either.
        cyborg = fielded_of_species(self.match, SPECIES_CYBORG)
        self.assertEqual(self.match.exhaustion.get(cyborg, 0), 0)
        self.assertNotIn(cyborg, self.charged())

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
        for player_id in self.charged():
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

    def test_the_record_survives_a_save_and_the_turn_reset_clears_it(self):
        # A run back spans interactions, so who moved has to outlive
        # them.
        mover = field_players(self.match)[0]
        self.match.run_back_moved = [mover]
        self.match.pending_run_back_charge_up = True
        restored = MatchState.from_dict(
            self.match.to_dict(), self.engine.basic_ruleset,
        )
        self.assertEqual(restored.run_back_moved, [mover])
        self.assertTrue(restored.pending_run_back_charge_up)

        restored.reset_maneuver()
        self.assertEqual(restored.run_back_moved, [])
        self.assertFalse(restored.pending_run_back_charge_up)


class SmoothCandidateTests(unittest.TestCase):
    """
    **Smooth**: "When your team has possession and the ball moves to
    or through your space, you may take it over instead."

    It replaced Slip in on 2026-09-20 and is a different shape: Slip
    in narrowed *who may take the turn* after a resolution had already
    left the ball somewhere, where Smooth reads the ball's own path and
    stops it. So these are `mind_pull_candidates`' tests with the side
    flipped, not `turn_handler_candidates`' tests.
    """

    def setUp(self) -> None:
        self.engine = build_engine()
        self.game = build_game(player_1_team=Team.TELEKINETICS)
        self.match = build_match(self.engine, self.game)
        self.taker = fielded_of_species(
            self.match, SPECIES_TELEKINETIC, self.match.ball.possession,
        )

    def cross(self, player_id: str) -> None:
        """Move the ball one space onto `player_id`, recording a path."""
        origin = self.match.board.flat_index(
            self.match.ball.zone, self.match.ball.space_index,
        )
        zone, index = self.match.board.position_at_flat_index(origin + 1)
        self.match.board.place_meeple(player_id, zone, index)
        self.match.set_ball_space(zone, index)

    def test_a_telekinetic_the_ball_reaches_may_take_it_over(self):
        self.cross(self.taker)
        self.assertEqual(
            self.engine.smooth_candidates(self.game, self.match),
            [self.taker],
        )

    def test_the_ball_s_own_starting_space_is_not_moved_to(self):
        # The path excludes where the ball starts, so standing on it
        # when the movement begins offers nothing -- the same sentence
        # of the rule the pull is held to.
        self.match.board.place_meeple(
            self.taker, self.match.ball.zone, self.match.ball.space_index,
        )
        origin = self.match.board.flat_index(
            self.match.ball.zone, self.match.ball.space_index,
        )
        zone, index = self.match.board.position_at_flat_index(origin + 1)
        self.match.set_ball_space(zone, index)
        self.assertNotIn(
            self.taker,
            self.engine.smooth_candidates(self.game, self.match),
        )

    def test_an_opposing_telekinetic_is_never_a_smooth(self):
        # "When your team has possession" -- the other side's
        # Telekinetic on that space is a Mind Pull, and the two lists
        # can never share a name on one movement.
        opponent = fielded_of_species(
            self.match, SPECIES_TELEKINETIC, self.match.defending_side(),
        )
        self.cross(opponent)
        self.assertEqual(
            self.engine.smooth_candidates(self.game, self.match), [],
        )
        self.assertIn(
            opponent,
            self.engine.mind_pull_candidates(self.game, self.match),
        )

    def test_a_non_telekinetic_teammate_may_not(self):
        # A colour side fields two of each other species, so this is a
        # real case rather than a hypothetical.
        game = build_game(player_1_team=Team.SLIME)
        match = build_match(self.engine, game)
        teammate = next(
            player_id
            for player_id in field_players(match, match.ball.possession)
            if self.engine.species_of(player_id) != SPECIES_TELEKINETIC
        )
        origin = match.board.flat_index(
            match.ball.zone, match.ball.space_index,
        )
        zone, index = match.board.position_at_flat_index(origin + 1)
        match.board.place_meeple(teammate, zone, index)
        match.set_ball_space(zone, index)
        self.assertEqual(self.engine.smooth_candidates(game, match), [])

    def test_without_the_module_nobody_may(self):
        self.cross(self.taker)
        basic = build_game(
            player_1_team=Team.TELEKINETICS, mode=GameMode.BASIC,
        )
        self.assertEqual(
            self.engine.smooth_candidates(basic, self.match), [],
        )

    def test_an_injured_telekinetic_may_still_take_it(self):
        # Unlike a pull. The pull excludes the injured because it costs
        # a token they cannot gain; Smooth costs nothing, so that
        # reasoning does not reach here.
        self.cross(self.taker)
        self.match.injured.add(self.taker)
        self.assertEqual(
            self.engine.smooth_candidates(self.game, self.match),
            [self.taker],
        )
        self.assertEqual(
            self.engine.mind_pull_candidates(self.game, self.match), [],
        )

    def test_a_dead_ball_crosses_nobody(self):
        # `restart_ball_at` clears the path, so a kickoff offers no
        # Smooth however far it travels -- the same exemption the pull
        # has, and for the same reason.
        self.match.board.place_meeple(self.taker, Zone.MIDFIELD, 0)
        self.match.restart_ball_at(Zone.MIDFIELD, 0)
        self.assertEqual(
            self.engine.smooth_candidates(self.game, self.match), [],
        )

    def test_taking_it_over_is_not_a_turnover(self):
        # The one place Smooth parts company with a landed pull:
        # possession never changed hands, so there is nothing to run
        # back from.
        self.cross(self.taker)
        was = self.match.ball.possession
        self.match.apply_smooth(self.taker)
        self.assertEqual(self.match.ball.possession, was)
        self.assertEqual(self.match.ball_carrier_id, self.taker)
        self.assertEqual(
            (self.match.ball.zone, self.match.ball.space_index),
            self.match.board.meeple_position(self.taker),
        )
        # Spent, so the next arrival point cannot offer the same ball
        # again -- and the opposing side's queue goes with it.
        self.assertEqual(self.match.last_ball_path, [])
        self.assertEqual(self.match.pending_smooth, [])
        self.assertEqual(self.match.pending_mind_pull, [])

    def test_the_turn_reset_clears_the_queue(self):
        self.match.pending_smooth = [self.taker]
        self.match.pending_smooth_resume = {"kind": "finish_maneuver"}
        self.match.reset_maneuver()
        self.assertEqual(self.match.pending_smooth, [])
        self.assertIsNone(self.match.pending_smooth_resume)

    def test_the_queue_survives_a_save(self):
        self.match.pending_smooth = [self.taker]
        self.match.pending_smooth_resume = {
            "kind": "own_goal", "distance_moved": 1,
        }
        restored = MatchState.from_dict(
            self.match.to_dict(), self.engine.basic_ruleset,
        )
        self.assertEqual(restored.pending_smooth, [self.taker])
        self.assertEqual(
            restored.pending_smooth_resume,
            {"kind": "own_goal", "distance_moved": 1},
        )

    def test_a_save_written_before_smooth_existed_still_loads(self):
        # The fallback the save format owes every added field: a
        # half-finished game outlives the commit, and both developers
        # run the bot against their own saves.
        saved = self.match.to_dict()
        del saved["pending_smooth"]
        del saved["pending_smooth_resume"]
        restored = MatchState.from_dict(
            saved, self.engine.basic_ruleset,
        )
        self.assertEqual(restored.pending_smooth, [])
        self.assertIsNone(restored.pending_smooth_resume)


class TurnHandlerNarrowingTests(unittest.TestCase):
    """
    What is left of `turn_handler_candidates` now that Smooth has taken
    Slip in's job: a named carrier is the whole list, and nobody widens
    past them.
    """

    def setUp(self) -> None:
        self.engine = build_engine()
        self.game = build_game(player_1_team=Team.TELEKINETICS)
        self.match = build_match(self.engine, self.game)

    def test_a_named_carrier_takes_the_turn_alone(self):
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
        self.assertEqual(
            self.engine.turn_handler_candidates(self.game, self.match),
            [carrier],
        )

    def test_no_carrier_leaves_the_whole_choice(self):
        self.match.clear_ball_carrier()
        teammate = next(
            player_id
            for player_id in field_players(self.match)
            if player_id != self.match.eligible_ball_handlers()[0]
        )
        self.match.board.place_meeple(
            teammate, self.match.ball.zone, self.match.ball.space_index,
        )
        candidates = self.engine.turn_handler_candidates(
            self.game, self.match,
        )
        self.assertGreater(len(candidates), 1)

    def test_the_click_still_refuses_somebody_off_the_ball(self):
        away = next(
            player_id
            for player_id in field_players(self.match)
            if player_id not in self.match.eligible_ball_handlers()
        )
        with self.assertRaises(ValueError):
            self.match.select_ball_handler(away)


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
        bonus, lines, contributors = self.engine.merge_bonus(
            self.game, self.match, self.side, (roller,), "offense",
        )
        self.assertEqual(bonus, self.offense_of(bystander))
        self.assertEqual(len(lines), 1)
        self.assertEqual(
            contributors,
            [(self.engine.get_player_definition(bystander).name,
              self.offense_of(bystander))],
        )

    def test_the_roller_does_not_add_to_themselves(self):
        roller = field_players(self.match)[0]
        self.stand_on_the_ball(roller)
        bonus, lines, contributors = self.engine.merge_bonus(
            self.game, self.match, self.side, (roller,), "offense",
        )
        self.assertEqual(bonus, 0)
        self.assertEqual(lines, [])
        self.assertEqual(contributors, [])

    def test_two_of_them_add_twice(self):
        roller, first, second = field_players(self.match)[:3]
        for player_id in (roller, first, second):
            self.stand_on_the_ball(player_id)
        bonus, lines, contributors = self.engine.merge_bonus(
            self.game, self.match, self.side, (roller,), "offense",
        )
        self.assertEqual(
            bonus, self.offense_of(first) + self.offense_of(second),
        )
        self.assertEqual(len(lines), 2)
        self.assertEqual(len(contributors), 2)

    def test_an_injured_ooze_adds_nothing(self):
        roller, bystander = field_players(self.match)[:2]
        self.stand_on_the_ball(roller)
        self.stand_on_the_ball(bystander)
        self.match.mark_injured(bystander)
        bonus, _, _ = self.engine.merge_bonus(
            self.game, self.match, self.side, (roller,), "offense",
        )
        self.assertEqual(bonus, 0)

    def test_the_skill_asked_for_is_the_side_of_the_contest(self):
        roller, bystander = field_players(self.match)[:2]
        self.stand_on_the_ball(roller)
        self.stand_on_the_ball(bystander)
        attacking, _, _ = self.engine.merge_bonus(
            self.game, self.match, self.side, (roller,), "offense",
        )
        defending, _, _ = self.engine.merge_bonus(
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
        bonus, _, _ = self.engine.merge_bonus(
            self.game, self.match, self.side, (roller,), "offense",
        )
        self.assertEqual(bonus, 0)

    def test_a_basic_game_merges_nobody(self):
        roller, bystander = field_players(self.match)[:2]
        self.stand_on_the_ball(roller)
        self.stand_on_the_ball(bystander)
        basic = build_game(player_1_team=Team.OOZES, mode=GameMode.BASIC)
        bonus, lines, contributors = self.engine.merge_bonus(
            basic, self.match, self.side, (roller,), "offense",
        )
        self.assertEqual((bonus, lines, contributors), (0, [], []))

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
        bonus, _, _ = self.engine.merge_bonus(
            game, match, side, (roller,), "offense",
        )
        self.assertEqual(bonus, 0)


class SpreadableTests(unittest.TestCase):
    """
    "Spreadable ... it counts as 0 [[toward occupancy]]" -- fully
    passive: every fielded Ooze, always, with nothing for a coach to
    declare. `RulesEngine.spread_exempt_ids` is the whole of who is
    exempt; `open_spaces_in_zone`, `placement_spaces_in_zone` and
    `crowded_candidates` are the three readings that take it.

    A stack sharing a space with an exempt Ooze is a stack of one (or
    zero) once the Ooze is disregarded, so `crowded_candidates` never
    offers it -- neither the Ooze nor whoever it is stacked with runs
    back for it, and that is the only place the exemption reaches
    beyond occupancy.
    """

    def setUp(self) -> None:
        self.engine = build_engine()
        self.game = build_game(player_1_team=Team.OOZES)
        self.match = build_match(self.engine, self.game)

    def test_every_fielded_ooze_is_exempt(self):
        self.assertEqual(
            self.engine.spread_exempt_ids(
                self.game, self.match, TeamSide.HOME,
            ),
            set(field_players(self.match)),
        )

    def test_a_non_ooze_side_exempts_only_its_oozes(self):
        game = build_game(player_1_team=Team.PURPLE)
        match = build_match(self.engine, game)
        ooze = fielded_of_species(match, SPECIES_OOZE)
        exempt = self.engine.spread_exempt_ids(game, match, TeamSide.HOME)
        self.assertIn(ooze, exempt)
        self.assertTrue(
            all(
                self.engine.species_of(player_id) == SPECIES_OOZE
                for player_id in exempt
            )
        )

    def test_without_the_module_nobody_is_exempt(self):
        basic = build_game(player_1_team=Team.OOZES, mode=GameMode.BASIC)
        self.assertEqual(
            self.engine.spread_exempt_ids(basic, self.match, TeamSide.HOME),
            set(),
        )

    def test_a_fielded_ooze_counts_as_zero_in_open_spaces_in_zone(self):
        ooze = field_players(self.match)[0]
        zone, own_index = self.match.board.meeple_position(ooze)
        # Clear the space down to the Ooze alone, so its own presence
        # is the only thing standing between this space and reading as
        # uncovered.
        for player_id in list(self.match.board.spaces[zone][own_index]):
            if player_id != ooze:
                self.match.board.remove_meeple(player_id)
        self.assertNotIn(
            own_index,
            self.match.open_spaces_in_zone(TeamSide.HOME, zone),
        )
        self.assertIn(
            own_index,
            self.engine.open_spaces_in_zone(
                self.game, self.match, TeamSide.HOME, zone,
            ),
        )

    def test_a_fielded_ooze_counts_as_zero_in_placement_spaces_in_zone(self):
        ooze = field_players(self.match)[0]
        setup = self.match.setup_for_side(TeamSide.HOME)
        zone = setup.assigned_zone(ooze)
        own_index = self.match.board.meeple_position(ooze)[1]
        mover = next(
            player_id
            for player_id in field_players(self.match)
            if player_id != ooze and setup.assigned_zone(player_id) == zone
        )
        for player_id in list(self.match.board.spaces[zone][own_index]):
            if player_id not in (ooze, mover):
                self.match.board.remove_meeple(player_id)
        self.match.board.remove_meeple(mover)
        self.assertNotIn(
            own_index,
            self.match.placement_spaces_in_zone(TeamSide.HOME, zone, mover),
        )
        self.assertIn(
            own_index,
            self.engine.placement_spaces_in_zone(
                self.game, self.match, TeamSide.HOME, zone, mover,
            ),
        )

    def stack_onto(self, match: MatchState, mover: str, target: str) -> None:
        """Force `mover` to physically share `target`'s space."""
        position = match.board.meeple_position(target)
        match.board.remove_meeple(mover)
        match.board.place_meeple(mover, *position)

    def test_an_ooze_and_its_stacked_teammate_are_never_offered_to_run_back(self):
        # A mixed side, so the stack is a real Ooze plus a real
        # non-Ooze rather than two Oozes disappearing together.
        game = build_game(player_1_team=Team.PURPLE)
        match = build_match(self.engine, game)
        setup = match.setup_for_side(TeamSide.HOME)
        ooze = fielded_of_species(match, SPECIES_OOZE)
        zone = setup.assigned_zone(ooze)
        teammate = next(
            player_id
            for player_id in field_players(match)
            if player_id != ooze
            and self.engine.species_of(player_id) != SPECIES_OOZE
        )
        # Force the teammate into the Ooze's own zone and onto its
        # space, whatever the deal actually gave them -- the scenario
        # under test is the stack, not how it arose.
        for zone_players in setup.zones.values():
            if teammate in zone_players:
                zone_players.remove(teammate)
        setup.zones[zone].append(teammate)
        self.stack_onto(match, teammate, ooze)

        self.assertEqual(
            self.engine.run_back_crowded(game, match, TeamSide.HOME), [],
        )

    def test_a_stack_of_two_non_oozes_is_still_offered_normally(self):
        # A species side with no Oozes at all, so nothing here is
        # exempt and the ordinary stack-breaking rule is unaffected.
        game = build_game(player_1_team=Team.FIRE_DEMONS)
        match = build_match(self.engine, game)
        setup = match.setup_for_side(TeamSide.HOME)
        one, other = field_players(match)[:2]
        zone = setup.assigned_zone(one)
        for zone_players in setup.zones.values():
            if other in zone_players:
                zone_players.remove(other)
        setup.zones[zone].append(other)
        self.stack_onto(match, other, one)

        candidates = self.engine.run_back_crowded(game, match, TeamSide.HOME)
        self.assertIn(one, candidates)
        self.assertIn(other, candidates)

    def test_run_back_player_accepts_the_same_exempt_ids_the_prompt_used(self):
        # placement_spaces_in_zone's exempt-widened result has to be
        # what run_back_player itself re-validates against, or a
        # legitimately offered space is refused on the click.
        ooze = field_players(self.match)[0]
        setup = self.match.setup_for_side(TeamSide.HOME)
        zone = setup.assigned_zone(ooze)
        own_index = self.match.board.meeple_position(ooze)[1]
        mover = next(
            player_id
            for player_id in field_players(self.match)
            if player_id != ooze and setup.assigned_zone(player_id) == zone
        )
        for player_id in list(self.match.board.spaces[zone][own_index]):
            if player_id not in (ooze, mover):
                self.match.board.remove_meeple(player_id)
        self.match.board.remove_meeple(mover)
        exempt_ids = self.engine.spread_exempt_ids(
            self.game, self.match, TeamSide.HOME,
        )
        self.assertIn(
            own_index,
            self.match.placement_spaces_in_zone(
                TeamSide.HOME, zone, mover, exempt_ids,
            ),
        )
        self.match.run_back_player(mover, zone, own_index, exempt_ids)
        self.assertEqual(
            self.match.board.meeple_position(mover), (zone, own_index),
        )


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


class DeadBallPathTests(unittest.TestCase):
    """
    A restart is the ball being carried back into play, not travelling
    through it, so it crosses nobody -- the author, 2026-09-07.

    Every one of these went through `set_ball_space` before that
    ruling, and the path each recorded outlived the arrival gate that
    would have spent it: a goal reached `finish_maneuver_resolution` at
    the tail of the new play still carrying the ball's journey back to
    the middle of the field, and offered the **scoring** side's
    Telekinetics a pull on it.
    """

    def setUp(self) -> None:
        self.engine = build_engine()
        self.game = build_game()
        self.match = build_match(self.engine, self.game)

    def send_the_ball_downfield(self) -> None:
        """Put the ball at the visitors' end, so a restart is a long trip."""
        self.match.set_ball_space(
            Zone.VISITORS_GOAL,
            len(self.match.board.spaces[Zone.VISITORS_GOAL]) - 1,
        )
        self.assertTrue(self.match.last_ball_path)

    def test_the_kickoff_after_a_goal_crosses_nobody(self):
        self.send_the_ball_downfield()
        self.match.restart_after_goal(TeamSide.VISITING)
        self.assertEqual(self.match.last_ball_path, [])

    def test_the_restart_after_a_missed_shot_crosses_nobody(self):
        # From where the deal leaves the ball, not from downfield: a
        # shot that missed restarts beside the goal it was aimed at,
        # so a ball already sitting there would travel nowhere and the
        # test would pass on the geometry rather than on the rule.
        self.assertTrue(
            self.match.ball_path_to(
                *self.match.own_goal_restart_space(TeamSide.VISITING)
            )
        )
        self.match.restart_after_missed_score(TeamSide.VISITING)
        self.assertEqual(self.match.last_ball_path, [])

    def test_a_dead_ball_still_lands_where_it_was_put(self):
        # The placement is the whole of what a restart still does.
        self.send_the_ball_downfield()
        self.match.restart_ball_at(Zone.MIDFIELD, 0)
        self.assertEqual(
            (self.match.ball.zone, self.match.ball.space_index),
            (Zone.MIDFIELD, 0),
        )

    def test_a_dead_ball_drops_the_movement_before_it(self):
        # Cleared rather than merely unrecorded: a restart must not
        # hand the last live movement on to the next arrival gate.
        self.send_the_ball_downfield()
        self.match.restart_ball_at(
            self.match.ball.zone, self.match.ball.space_index,
        )
        self.assertEqual(self.match.last_ball_path, [])

    def test_a_dead_ball_is_still_refused_a_space_off_the_board(self):
        with self.assertRaises(ValueError):
            self.match.restart_ball_at(Zone.MIDFIELD, 99)


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
        self.assertEqual(MIND_PULL_SUCCESS_FACES, (11, 12))
        self.assertEqual(MIND_PULL_TOKEN_COST, 1)


def a_face_that_misses() -> int:
    """
    A d12 face that is **not** a pull, read off the rule rather than
    written down -- the twin of the success tests' own
    `MIND_PULL_SUCCESS_FACES[0]`. The faces moved from 1-2 to 11-12 on
    2026-09-20 and a hard-coded 12 silently turned a miss into a hit,
    which is the whole reason this is derived.
    """
    return next(
        face for face in range(1, 13)
        if face not in MIND_PULL_SUCCESS_FACES
    )


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
    # `channel.send` and `followup.send` share one mock: a post's route
    # depends on whether the interaction still had a response to give,
    # and `sent_views` below reads back "everything this posted" without
    # caring which route carried which message.
    send = mock.AsyncMock(return_value=sent)
    return SimpleNamespace(
        user=SimpleNamespace(id=222, display_name="Two"),
        guild=None,
        channel=SimpleNamespace(send=send),
        response=SimpleNamespace(
            defer=mock.AsyncMock(),
            edit_message=mock.AsyncMock(),
            send_message=mock.AsyncMock(),
            is_done=lambda: True,
        ),
        followup=SimpleNamespace(send=send),
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
            "random.randint", return_value=a_face_that_misses(),
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

    async def test_the_offer_becomes_the_die(self):
        # The roll is shown, not summarised: the offer message is
        # edited into the die image, the same way every other roll in
        # the game reports itself.
        self.match.pending_mind_pull = [self.puller]
        self.match.pending_mind_pull_resume = {
            "kind": "finish_maneuver", "distance_moved": 1,
        }
        self.cog.finish_maneuver_resolution = mock.AsyncMock()
        with suppressed_cog_saves(), mock.patch(
            "random.randint", return_value=a_face_that_misses(),
        ):
            await self.cog.run_mind_pull(
                self.interaction, self.game, self.match, self.puller,
            )
        edit = self.interaction.edit_original_response
        edit.assert_awaited()
        attachments = edit.await_args.kwargs["attachments"]
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0].filename, "mind_pull_die.png")
        # The image carries the face, so the message must not also be
        # the place a coach reads it.
        self.assertIsNone(edit.await_args.kwargs["content"])

    async def test_a_pull_that_lands_reads_as_a_turnover(self):
        # The author's own wording, and at the skill test's own size:
        # a roll that has just taken the ball off the other side is
        # not something to find in the middle of a paragraph.
        self.match.pending_mind_pull = [self.puller]
        self.match.pending_mind_pull_resume = {
            "kind": "finish_maneuver", "distance_moved": 1,
        }
        with suppressed_cog_saves(), mock.patch(
            "random.randint", return_value=MIND_PULL_SUCCESS_FACES[0],
        ):
            await self.cog.run_mind_pull(
                self.interaction, self.game, self.match, self.puller,
            )
        lead_in = self.cog.begin_run_back.await_args.kwargs["lead_in"]
        player = self.cog.engine.get_player_definition(self.puller)
        self.assertIn(
            f"## {self.cog.player_label(self.match, player)} grabs the "
            "ball with their telekinetic powers!",
            lead_in,
        )
        self.assertIn("Turnover!", lead_in)
        self.assertNotIn("pull it in", lead_in)

    async def test_a_restart_mid_offer_puts_the_same_question_back(self):
        self.match.pending_mind_pull = [self.puller]
        view, prompt = self.cog.pending_turn_view(
            self.game.game_id, self.match,
        )
        self.assertIsInstance(view, MindPullView)
        self.assertIn("reach", prompt)


class RunBackGatesMindPullTests(unittest.IsolatedAsyncioTestCase):
    """
    Steal, Intercept, a Defender's pressure steal, and an own goal
    avoided all move the ball with `set_ball_space` and call
    `begin_run_back` directly, never passing through any of the three
    ordinary arrival gates. Before 2026-09-20 that left
    `last_ball_path` sitting unread until `finish_run_back`'s own tail
    call into `finish_maneuver_resolution` -- by which point run-back
    had already repositioned players, so a Telekinetic who merely ran
    back onto a crossed space was wrongly offered a pull that belonged
    to whoever was actually standing there when the ball moved.
    """

    def setUp(self) -> None:
        self.cog = build_mind_pull_cog()
        # This class asserts `begin_run_back` itself, not the stand-in
        # `build_mind_pull_cog` mocks out for the tests above.
        self.cog.begin_run_back = D12Ball.begin_run_back.__get__(self.cog)
        self.cog.announce_run_back = mock.AsyncMock()
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
        self.crossed_zone, self.crossed_index = (
            self.match.board.position_at_flat_index(origin + 1)
        )

    def sent_views(self) -> list:
        return [
            call.kwargs.get("view")
            for call in self.interaction.followup.send.await_args_list
        ]

    async def test_a_steal_style_movement_offers_a_crossed_telekinetic(self):
        # Mirrors what `apply_steal`/`take_ball_by_steal` does: the ball
        # moves via `set_ball_space` and `begin_run_back` is called
        # directly, with nothing else having gated it first.
        self.match.board.place_meeple(
            self.puller, self.crossed_zone, self.crossed_index,
        )
        self.match.set_ball_space(self.crossed_zone, self.crossed_index)
        with suppressed_cog_saves():
            await self.cog.begin_run_back(
                self.interaction, self.game, self.match,
                turnover_occurred=True,
            )
        self.assertTrue(
            any(isinstance(view, MindPullView) for view in self.sent_views()),
        )
        self.assertEqual(self.match.pending_mind_pull, [self.puller])
        self.assertEqual(
            self.match.pending_mind_pull_resume["kind"], "run_back",
        )
        self.cog.announce_run_back.assert_not_awaited()

    async def test_a_telekinetic_reaching_the_space_only_via_run_back_is_never_offered(
        self,
    ):
        # Nobody is standing on the crossed space when the ball moves --
        # the puller is still back on their own goal line, exactly where
        # a run-back might later send them if that space is open. The
        # gate has to read occupancy now, not whatever run-back leaves
        # there afterwards.
        self.match.set_ball_space(self.crossed_zone, self.crossed_index)
        with suppressed_cog_saves():
            await self.cog.begin_run_back(
                self.interaction, self.game, self.match,
                turnover_occurred=True,
            )
        self.assertFalse(
            any(isinstance(view, MindPullView) for view in self.sent_views()),
        )
        self.assertEqual(self.match.pending_mind_pull, [])
        self.assertEqual(self.match.last_ball_path, [])
        self.cog.announce_run_back.assert_awaited()

        # Even once a run-back moves the puller onto that same space --
        # exactly what the reported bug had happen -- the path is
        # already spent, so the arrival that eventually runs
        # (`finish_run_back`'s own tail call) must not retroactively
        # offer them the pull.
        self.match.board.place_meeple(
            self.puller, self.crossed_zone, self.crossed_index,
        )
        with suppressed_cog_saves():
            interrupted = await self.cog.check_for_mind_pull(
                self.interaction, self.game, self.match,
                {"kind": "finish_maneuver", "distance_moved": 1},
            )
        self.assertFalse(interrupted)
        self.assertEqual(self.match.pending_mind_pull, [])


class PressureOvershootGatesMindPullTests(unittest.IsolatedAsyncioTestCase):
    """
    **The fifth gate: a shove that overshoots into an own-goal roll.**

    `shove_pressured_handler` drives the ball back through
    `set_ball_space`, so an overshot Pressure has a recorded path like
    any other ball movement -- but `apply_pressure`'s overshoot branch
    used to hand straight to `begin_own_goal_roll` without gating it.
    That left the pull in the wrong place both ways round: after the
    roll when the own goal was avoided (too late to pre-empt anything,
    where the rules say "a pull that lands pre-empts whatever the
    movement would have led to"), and nowhere at all when it was
    conceded, because `restart_after_goal` clears `last_ball_path` on
    its way to the kickoff.

    **Only a Double Team can reach the branch with a path.** A plain
    Pressure overshoots only from the space closest to the offense's
    own goal, where the handler does not move at all and
    `ball_path_to` answers empty; a Double Team pushing 2 from one
    space short of it shoves them a real space first. Both are asserted
    here, because "the gate is a no-op for the common case" is the
    claim that makes adding it safe.
    """

    def setUp(self) -> None:
        self.cog = build_mind_pull_cog()
        # `begin_own_goal_roll` is emphatically not mocked: since the
        # Phase 3d lift made `pressure_step` the model's, the gate
        # lives inside it, and stubbing it out would stub out the
        # thing under test. Whether the roll was reached is read off
        # `pending_own_goal` and the view that was posted instead.
        self.game = build_game(
            player_1_team=Team.PURPLE, player_2_team=Team.ORANGE,
        )
        self.cog.games[self.game.game_id] = self.game
        self.match = self.cog.engine.initialize_standard_match(self.game)
        self.interaction = build_mind_pull_interaction()

        offense = self.match.ball.possession
        defense = self.match.defending_side()
        board = self.match.board

        # A colour team fields a species mix, which is what lets the
        # puller be somebody other than the two defenders the shove
        # itself places on the arrival space -- the point of the test is
        # a Telekinetic who was *already standing there*.
        self.puller = fielded_of_species(
            self.match, SPECIES_TELEKINETIC, defense,
        )
        others = [
            player_id
            for player_id in field_players(self.match, defense)
            if player_id != self.puller
        ]
        self.challenger, self.partner = others[0], others[1]

        # Everyone else out of the way, so `double_team_partner` -- the
        # nearest defender to the ball that is not the challenger -- is
        # the one this fixture named.
        for player_id in others[2:]:
            board.place_meeple(player_id, Zone.VISITORS_GOAL, 1)

        self.handler = field_players(self.match, offense)[0]
        # One space short of the offense's own goal: far enough back
        # that a 2-space Double Team overshoots, near enough that it
        # still moves them a real space first.
        board.place_meeple(self.handler, Zone.HOME_GOAL, 1)
        board.place_meeple(self.challenger, Zone.HOME_GOAL, 1)
        board.place_meeple(self.partner, Zone.HOME_GOAL, 1)
        board.place_meeple(self.puller, Zone.HOME_GOAL, 0)

        self.match.active_player_id = self.handler
        self.match.challenger_id = self.challenger
        # `restart_ball_at` rather than `set_ball_space`: placing the
        # ball for a fixture must not leave a path behind for the gate
        # under test to read.
        self.match.restart_ball_at(Zone.HOME_GOAL, 1)

    def sent_views(self) -> list:
        return [
            call.kwargs.get("view")
            for call in self.interaction.followup.send.await_args_list
        ]

    def offered_a_pull(self) -> bool:
        return any(
            isinstance(view, MindPullView) for view in self.sent_views()
        )

    async def test_an_overshooting_double_team_offers_the_pull_before_the_roll(
        self,
    ):
        with suppressed_cog_saves():
            await self.cog.apply_pressure(
                self.interaction, self.game, self.match, "double_team",
            )

        self.assertTrue(self.offered_a_pull())
        self.assertEqual(self.match.pending_mind_pull, [self.puller])
        self.assertEqual(
            self.match.pending_mind_pull_resume["kind"], "own_goal",
        )
        # The whole point of the gate's position: the roll has not been
        # set up yet, so a pull that lands still pre-empts it -- and a
        # restart here reads the offer rather than the roll.
        self.assertFalse(self.match.pending_own_goal)
        self.assertFalse(
            any(isinstance(v, OwnGoalRollView) for v in self.sent_views()),
        )
        # Spent on the way through, like every other gate.
        self.assertEqual(self.match.last_ball_path, [])

    async def test_the_shove_really_moved_the_ball_a_space(self):
        # The fixture's own claim, asserted rather than assumed: a
        # Double Team from here overshoots *and* moves the ball, which
        # is what gives the gate a path to read.
        with suppressed_cog_saves():
            await self.cog.apply_pressure(
                self.interaction, self.game, self.match, "double_team",
            )
        self.assertEqual(
            self.match.board.meeple_position(self.handler),
            (Zone.HOME_GOAL, 0),
        )
        self.assertEqual(self.match.ball.zone, Zone.HOME_GOAL)
        self.assertEqual(self.match.ball.space_index, 0)

    async def test_declining_the_pull_hands_the_own_goal_roll_back(self):
        with suppressed_cog_saves():
            await self.cog.apply_pressure(
                self.interaction, self.game, self.match, "double_team",
            )
            # What the decline button does: drop this Telekinetic and
            # let the one exit from the queue run.
            self.match.pending_mind_pull.remove(self.puller)
            await self.cog.continue_mind_pull(
                self.interaction, self.game, self.match,
            )

        # The arrival the gate interrupted, put back exactly where it
        # was -- the roll the shove was about to ask for. Re-entering
        # the gate on the way is a no-op, because the path is spent.
        self.assertTrue(self.match.pending_own_goal)
        self.assertEqual(self.match.pending_own_goal_distance, 1)
        self.assertTrue(
            any(isinstance(v, OwnGoalRollView) for v in self.sent_views()),
        )
        self.assertIsNone(self.match.pending_mind_pull_resume)

    async def test_a_plain_pressure_overshoot_offers_nobody(self):
        # Already on the space closest to their own goal, which is the
        # only way a 1-space Pressure overshoots at all: the handler
        # does not move, so there is no path and nothing to gate. The
        # puller is standing right on them.
        self.match.board.place_meeple(self.handler, Zone.HOME_GOAL, 0)
        self.match.restart_ball_at(Zone.HOME_GOAL, 0)

        with suppressed_cog_saves():
            await self.cog.apply_pressure(
                self.interaction, self.game, self.match, "pressure",
            )

        self.assertFalse(self.offered_a_pull())
        self.assertEqual(self.match.pending_mind_pull, [])
        self.assertTrue(self.match.pending_own_goal)

    async def test_the_gate_is_silent_when_the_module_is_off(self):
        # Species abilities off is the ordinary game, and the branch has
        # to behave exactly as it did before the gate existed.
        self.game.species_abilities = False

        with suppressed_cog_saves():
            await self.cog.apply_pressure(
                self.interaction, self.game, self.match, "double_team",
            )

        self.assertFalse(self.offered_a_pull())
        self.assertEqual(self.match.pending_mind_pull, [])
        self.assertTrue(self.match.pending_own_goal)


class SmoothGateTests(unittest.IsolatedAsyncioTestCase):
    """
    **The Smooth gate, through the real cog.** Smooth is asked first at
    every arrival, and a Smooth that is taken pre-empts what the
    movement was going to lead to -- including, and this is the case
    the author settled on 2026-09-20, the own-goal roll an overshot
    Double Team was about to ask for.

    The gate is emphatically **not** mocked here; what stands in for
    itself is only what the gate defers to.
    """

    def setUp(self) -> None:
        self.cog = build_mind_pull_cog()
        self.cog.begin_own_goal_roll = mock.AsyncMock()
        self.cog.finish_maneuver_resolution = mock.AsyncMock()
        self.game = build_game(
            player_1_team=Team.ORANGE, player_2_team=Team.PURPLE,
        )
        self.cog.games[self.game.game_id] = self.game
        self.match = self.cog.engine.initialize_standard_match(self.game)
        self.interaction = build_mind_pull_interaction()

        offense = self.match.ball.possession
        self.taker = fielded_of_species(
            self.match, SPECIES_TELEKINETIC, offense,
        )

        origin = self.match.board.flat_index(
            self.match.ball.zone, self.match.ball.space_index,
        )
        self.crossed = self.match.board.position_at_flat_index(origin + 1)

    def sent_views(self) -> list:
        return [
            call.kwargs.get("view")
            for call in self.interaction.followup.send.await_args_list
        ]

    def cross(self, player_id: str) -> None:
        self.match.board.place_meeple(player_id, *self.crossed)
        self.match.set_ball_space(*self.crossed)

    async def test_the_arrival_gate_offers_the_smooth(self):
        self.cross(self.taker)
        with suppressed_cog_saves():
            took_over = await self.cog.check_for_ball_arrival(
                self.interaction, self.game, self.match,
                {"kind": "finish_maneuver", "distance_moved": 1},
            )
        self.assertTrue(took_over)
        self.assertTrue(
            any(isinstance(v, SmoothView) for v in self.sent_views()),
        )
        self.assertEqual(self.match.pending_smooth, [self.taker])
        self.assertEqual(
            self.match.pending_smooth_resume["kind"], "finish_maneuver",
        )

    async def test_the_smooth_gate_leaves_the_path_for_the_pull(self):
        # The one mechanical difference between the two gates: the
        # pull spends the path, Smooth must not, or a movement that
        # crossed both sides' Telekinetics would offer only the first.
        self.cross(self.taker)
        with suppressed_cog_saves():
            await self.cog.check_for_smooth(
                self.interaction, self.game, self.match,
                {"kind": "finish_maneuver", "distance_moved": 1},
            )
        self.assertNotEqual(self.match.last_ball_path, [])

    async def test_declining_hands_the_movement_to_the_pull(self):
        # A Telekinetic of each side on the same crossed space: the
        # teammate is asked first, and letting it run must still leave
        # the opponent their roll.
        opponent = fielded_of_species(
            self.match, SPECIES_TELEKINETIC, self.match.defending_side(),
        )
        self.cross(self.taker)
        self.match.board.place_meeple(opponent, *self.crossed)

        with suppressed_cog_saves():
            await self.cog.check_for_ball_arrival(
                self.interaction, self.game, self.match,
                {"kind": "finish_maneuver", "distance_moved": 1},
            )
            self.match.pending_smooth.remove(self.taker)
            await self.cog.continue_smooth(
                self.interaction, self.game, self.match,
            )

        self.assertEqual(self.match.pending_mind_pull, [opponent])
        self.assertTrue(
            any(isinstance(v, MindPullView) for v in self.sent_views()),
        )
        self.cog.finish_maneuver_resolution.assert_not_awaited()

    async def test_nobody_wanting_it_falls_through_to_the_arrival(self):
        self.cross(self.taker)
        with suppressed_cog_saves():
            await self.cog.check_for_ball_arrival(
                self.interaction, self.game, self.match,
                {"kind": "finish_maneuver", "distance_moved": 1},
            )
            self.match.pending_smooth.remove(self.taker)
            await self.cog.continue_smooth(
                self.interaction, self.game, self.match,
            )
        self.cog.finish_maneuver_resolution.assert_awaited()
        # And the path is spent on the way past, by the pull.
        self.assertEqual(self.match.last_ball_path, [])

    async def test_taking_it_is_not_a_turnover(self):
        self.cross(self.taker)
        was = self.match.ball.possession
        with suppressed_cog_saves():
            await self.cog.check_for_ball_arrival(
                self.interaction, self.game, self.match,
                {"kind": "finish_maneuver", "distance_moved": 1},
            )
            await self.cog.run_smooth(
                self.interaction, self.game, self.match, self.taker,
            )
        self.assertEqual(self.match.ball.possession, was)
        self.assertEqual(self.match.ball_carrier_id, self.taker)
        self.cog.begin_run_back.assert_not_awaited()
        self.cog.finish_maneuver_resolution.assert_awaited()
        self.assertFalse(
            self.cog.finish_maneuver_resolution.await_args.kwargs[
                "turnover_occurred"
            ],
        )

    async def test_a_turnover_driven_arrival_still_runs_back(self):
        # The one arrival a Smooth cannot pre-empt: `begin_run_back` is
        # not a question about where the ball settles, it is the
        # consequence of a turnover that already happened. Smooth only
        # changes who is holding it when everyone runs back.
        self.cross(self.taker)
        with suppressed_cog_saves():
            await self.cog.run_smooth(
                self.interaction, self.game, self.match, self.taker,
            )
        self.cog.finish_maneuver_resolution.assert_awaited()

        self.cog.finish_maneuver_resolution.reset_mock()
        self.cross(self.taker)
        self.match.pending_smooth_resume = {
            "kind": "run_back", "distance_moved": 2,
        }
        with suppressed_cog_saves():
            await self.cog.run_smooth(
                self.interaction, self.game, self.match, self.taker,
            )
        self.cog.begin_run_back.assert_awaited()
        self.assertEqual(
            self.cog.begin_run_back.await_args.kwargs["distance_moved"], 2,
        )
        self.cog.finish_maneuver_resolution.assert_not_awaited()

    async def test_taking_it_skips_the_own_goal_roll(self):
        # The author's ruling, 2026-09-20: if the offense's own
        # Telekinetic takes the ball during the shove, before the roll,
        # there is no own-goal risk at all. It falls out of "a Smooth
        # pre-empts what the movement led to" rather than being a case
        # of its own -- which is why there is no "own_goal" branch in
        # run_smooth to read.
        self.cross(self.taker)
        self.match.pending_smooth_resume = {
            "kind": "own_goal", "distance_moved": 1,
        }
        with suppressed_cog_saves():
            await self.cog.run_smooth(
                self.interaction, self.game, self.match, self.taker,
            )
        self.cog.begin_own_goal_roll.assert_not_awaited()
        self.cog.finish_maneuver_resolution.assert_awaited()
        self.assertFalse(self.match.pending_own_goal)

    async def test_an_ai_side_is_never_offered_one(self):
        # Dinky never takes a Smooth, the same call as never ceding and
        # never pulling.
        self.game.ai_opponent = AIOpponent.DINKY
        # An AI side is one with no Discord user behind it, which is
        # what `controlling_user_id` actually reads -- see
        # `continue_smooth`'s skip.
        number = (
            self.game.home_player_number
            if self.match.ball.possession is TeamSide.HOME
            else self.game.visiting_player_number
        )
        setattr(self.game, f"player_{number}_id", None)
        self.cross(self.taker)
        with suppressed_cog_saves():
            await self.cog.check_for_ball_arrival(
                self.interaction, self.game, self.match,
                {"kind": "finish_maneuver", "distance_moved": 1},
            )
        self.assertFalse(
            any(isinstance(v, SmoothView) for v in self.sent_views()),
        )
        self.assertEqual(self.match.pending_smooth, [])


class MovedWithTheBallTests(unittest.IsolatedAsyncioTestCase):
    """
    **Nobody the resolution moved is offered either half of the
    ability.** The author, 2026-09-20, ruling out the case found while
    gating the overshoot branch: *"they move with the ball while mind
    pull only works when the ball moves after"*.

    A player the maneuver carried never had the ball move *to or
    through* their space -- they and it arrived together. That reaches
    three players a Pressure touches (the shoved handler, the
    challenger, a Double Team's partner) and the handler of every
    dribble, and it is `MatchState.last_ball_movers` in all of them.
    """

    def setUp(self) -> None:
        self.cog = build_mind_pull_cog()
        self.cog.begin_own_goal_roll = mock.AsyncMock()
        self.cog.finish_maneuver_resolution = mock.AsyncMock()
        self.game = build_game(
            player_1_team=Team.TELEKINETICS,
            player_2_team=Team.TELEKINETICS,
        )
        self.cog.games[self.game.game_id] = self.game
        self.match = self.cog.engine.initialize_standard_match(self.game)
        self.interaction = build_mind_pull_interaction()

        self.offense = self.match.ball.possession
        self.defense = self.match.defending_side()
        self.handler = field_players(self.match, self.offense)[0]
        self.challenger = field_players(self.match, self.defense)[0]

    def test_a_telekinetic_challenger_gets_no_pull_on_the_ball_they_shoved(
        self,
    ):
        # The reported case, end to end. Both sides are Telekinetics,
        # so every player here has the ability and nothing is excluded
        # for lack of it.
        board = self.match.board
        board.place_meeple(self.handler, Zone.MIDFIELD, 1)
        board.place_meeple(self.challenger, Zone.MIDFIELD, 1)
        self.match.active_player_id = self.handler
        self.match.challenger_id = self.challenger
        self.match.restart_ball_at(Zone.MIDFIELD, 1)

        shove_pressured_handler(self.match, 1, None)

        # The shove really does leave the challenger standing on the
        # ball -- the card says "onto the same space" -- so this is the
        # exclusion doing the work, not the geometry.
        self.assertEqual(
            board.meeple_position(self.challenger),
            (self.match.ball.zone, self.match.ball.space_index),
        )
        self.assertIn(self.challenger, self.match.last_ball_movers)
        self.assertEqual(
            self.cog.engine.mind_pull_candidates(self.game, self.match), [],
        )

    def test_a_double_team_s_partner_gets_no_pull_either(self):
        board = self.match.board
        partner = field_players(self.match, self.defense)[1]
        board.place_meeple(self.handler, Zone.MIDFIELD, 2)
        board.place_meeple(self.challenger, Zone.MIDFIELD, 2)
        board.place_meeple(partner, Zone.MIDFIELD, 2)
        self.match.active_player_id = self.handler
        self.match.challenger_id = self.challenger
        self.match.restart_ball_at(Zone.MIDFIELD, 2)

        shove_pressured_handler(self.match, 2, partner)

        candidates = self.cog.engine.mind_pull_candidates(
            self.game, self.match,
        )
        self.assertNotIn(self.challenger, candidates)
        self.assertNotIn(partner, candidates)

    def test_the_shoved_handler_gets_no_smooth_on_their_own_ball(self):
        # The same rule on the other half, where it matters more: the
        # handler is on the possessing side and ends up standing on the
        # ball, so without the exclusion they would be offered a Smooth
        # on a ball they are already holding.
        board = self.match.board
        board.place_meeple(self.handler, Zone.MIDFIELD, 1)
        board.place_meeple(self.challenger, Zone.MIDFIELD, 1)
        self.match.active_player_id = self.handler
        self.match.challenger_id = self.challenger
        self.match.restart_ball_at(Zone.MIDFIELD, 1)

        shove_pressured_handler(self.match, 1, None)

        self.assertIn(self.handler, self.match.last_ball_movers)
        self.assertNotIn(
            self.handler,
            self.cog.engine.smooth_candidates(self.game, self.match),
        )

    def test_a_telekinetic_standing_still_is_still_offered(self):
        # The exclusion must not swallow the case the ability is for: a
        # player who was already there and did not move.
        board = self.match.board
        bystander = field_players(self.match, self.defense)[2]
        board.place_meeple(self.handler, Zone.MIDFIELD, 1)
        board.place_meeple(self.challenger, Zone.MIDFIELD, 1)
        board.place_meeple(bystander, Zone.MIDFIELD, 0)
        self.match.active_player_id = self.handler
        self.match.challenger_id = self.challenger
        self.match.restart_ball_at(Zone.MIDFIELD, 1)

        shove_pressured_handler(self.match, 1, None)

        # The ball arrived on MIDFIELD 0, where the bystander was
        # standing before the play and stayed.
        self.assertEqual(
            (self.match.ball.zone, self.match.ball.space_index),
            (Zone.MIDFIELD, 0),
        )
        self.assertNotIn(bystander, self.match.last_ball_movers)
        self.assertIn(
            bystander,
            self.cog.engine.mind_pull_candidates(self.game, self.match),
        )

    def test_a_move_that_goes_nowhere_is_not_a_move(self):
        # A clamped shove leaves the handler exactly where they stood,
        # which has carried them nowhere -- the same reading the path
        # itself makes of a ball that does not travel.
        self.match.board.place_meeple(self.handler, Zone.HOME_GOAL, 0)
        self.match.restart_ball_at(Zone.HOME_GOAL, 0)
        self.match.move_player_relative(self.handler, self.offense, -1)
        self.assertEqual(self.match.last_ball_movers, [])

    def test_the_turn_reset_clears_the_movers(self):
        # They are disqualified from the movement that moved them, not
        # from the turn: the end-of-turn reset lets them back in.
        self.match.last_ball_movers = [self.handler]
        self.match.reset_maneuver()
        self.assertEqual(self.match.last_ball_movers, [])

    async def test_the_gate_clears_them_with_the_path(self):
        self.match.last_ball_movers = [self.handler]
        self.match.last_ball_path = [[Zone.MIDFIELD.value, 1]]
        with suppressed_cog_saves():
            await self.cog.check_for_mind_pull(
                self.interaction, self.game, self.match,
                {"kind": "finish_maneuver", "distance_moved": 1},
            )
        self.assertEqual(self.match.last_ball_path, [])
        self.assertEqual(self.match.last_ball_movers, [])

    def test_the_movers_survive_a_save(self):
        self.match.last_ball_movers = [self.handler]
        restored = MatchState.from_dict(
            self.match.to_dict(), self.cog.engine.basic_ruleset,
        )
        self.assertEqual(restored.last_ball_movers, [self.handler])

    def test_a_save_written_before_the_field_existed_still_loads(self):
        saved = self.match.to_dict()
        del saved["last_ball_movers"]
        restored = MatchState.from_dict(
            saved, self.cog.engine.basic_ruleset,
        )
        self.assertEqual(restored.last_ball_movers, [])


if __name__ == "__main__":
    unittest.main()
