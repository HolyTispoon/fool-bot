"""
The extreme shootout, which settles every game left level at full time.

Six players a side, in a secret order, rolling one skill test against
each other at a time. A win scores; a tie scores for nobody; a level
round goes to sudden death, where the shooter is chosen rather than
read off an order. See "Extreme shootout" in docs/living-rules.md.

The rules the tests below pin down that nothing else would:

- a shootout skill test **costs no exhaustion** but an Exhausted
  shooter still owes an injury check for taking part in one;
- an **injured** shooter adds no skill modifier and rolls the bare d12;
- shootout goals go on the **scoreboard**, and the separate tally is
  what decides when there is no point rolling on.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

from cogs.d12ball import D12Ball
from cogs.d12ball_views import (
    CoachingHubView,
    ShootoutOrderPromptView,
    ShootoutOrderSelectView,
    ShootoutPickPromptView,
    ShootoutPickSelectView,
    ShootoutTestView,
)
from d12ball.components import (
    CoachingOccasion,
    MatchPeriod,
    MatchState,
    TeamSide,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.ai import build_ai_strategies
from d12ball.engine import RulesEngine
from d12ball.game import AIOpponent, D12BallGame, GameStatus, Team
from save_patches import suppressed_cog_saves, suppressed_view_saves


def by_role(match: MatchState, side: TeamSide) -> list[str]:
    """
    A side's six in role order, which is how both sides' orders are set
    in these tests: it puts the same role at the same position on both
    sides, so equal dice make a genuine tie rather than a roll decided
    by whichever roles happened to line up.
    """
    catalog = load_player_catalog()
    return sorted(
        match.shootout_squad(side),
        key=lambda player_id: catalog.player_by_id(player_id).role.value,
    )


def build_cog() -> D12Ball:
    cog = object.__new__(D12Ball)
    cog.games = {}
    cog.player_catalog = load_player_catalog()
    cog.maneuver_catalog = load_maneuver_catalog()
    cog.basic_ruleset = load_basic_ruleset()
    cog.ai_strategies = build_ai_strategies(
        cog.player_catalog, cog.maneuver_catalog,
    )
    cog.engine = RulesEngine(
        cog.player_catalog, cog.basic_ruleset, cog.maneuver_catalog,
        cog.ai_strategies,
    )
    cog.team_emojis = {}
    cog.condition_emojis = {}
    cog.coin_emojis = {}
    cog.refresh_match_image = mock.AsyncMock()
    # The board the game ends on, which announce_game_over posts under
    # the result.
    cog.bot = SimpleNamespace(get_channel=lambda channel_id: None)
    cog.render_match_png = mock.AsyncMock(return_value=b"png")
    cog.match_file_from_png = mock.Mock(return_value=None)
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
        home_player_number=1,
        visiting_player_number=2,
        status=GameStatus.IN_PROGRESS,
    )
    fields.update(overrides)
    return D12BallGame(**fields)


def build_interaction(user_id: int = 111) -> SimpleNamespace:
    return SimpleNamespace(
        user=SimpleNamespace(id=user_id, display_name="One"),
        channel=SimpleNamespace(
            get_partial_message=lambda message_id: SimpleNamespace(
                delete=mock.AsyncMock(),
            ),
        ),
        followup=SimpleNamespace(
            send=mock.AsyncMock(
                return_value=SimpleNamespace(
                    id=999,
                    attachments=[],
                    edit=mock.AsyncMock(),
                ),
            ),
        ),
        response=SimpleNamespace(
            defer=mock.AsyncMock(),
            send_message=mock.AsyncMock(),
            edit_message=mock.AsyncMock(),
        ),
        edit_original_response=mock.AsyncMock(),
    )


def sent_texts(interaction: SimpleNamespace) -> list[str]:
    return [
        call.args[0] if call.args else call.kwargs.get("content", "")
        for call in interaction.followup.send.await_args_list
    ]


class ShootoutStateTests(unittest.TestCase):
    """MatchState's half of the shootout, with no Discord in sight."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    def build_match(self, home_score: int = 2, visiting_score: int = 2):
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
        )
        match.scoreboard.home_score = home_score
        match.scoreboard.visiting_score = visiting_score
        match.begin_shootout()
        return match

    def order_both_sides(self, match: MatchState) -> None:
        for side in (TeamSide.HOME, TeamSide.VISITING):
            match.set_shootout_order(side, match.shootout_squad(side))

    def test_the_six_who_shoot_are_the_six_on_the_field(self) -> None:
        match = self.build_match()

        self.assertEqual(
            match.shootout_squad(TeamSide.HOME),
            match.home.field_players,
        )
        self.assertEqual(len(match.shootout_squad(TeamSide.HOME)), 6)

    def test_an_order_is_built_one_player_at_a_time(self) -> None:
        match = self.build_match()
        squad = match.shootout_squad(TeamSide.HOME)

        match.add_to_shootout_order(TeamSide.HOME, squad[3])
        match.add_to_shootout_order(TeamSide.HOME, squad[0])

        self.assertEqual(
            match.shootout_order(TeamSide.HOME), [squad[3], squad[0]],
        )
        self.assertFalse(match.shootout_order_complete(TeamSide.HOME))
        self.assertNotIn(
            squad[3], match.shootout_order_remaining(TeamSide.HOME),
        )

    def test_the_same_player_cannot_be_ordered_twice(self) -> None:
        match = self.build_match()
        squad = match.shootout_squad(TeamSide.HOME)
        match.add_to_shootout_order(TeamSide.HOME, squad[0])

        with self.assertRaises(ValueError):
            match.add_to_shootout_order(TeamSide.HOME, squad[0])

    def test_a_part_built_order_survives_a_save(self) -> None:
        # The menu is ephemeral, so the order cannot live on the view:
        # a coach who ordered two and lost the bot comes back to two.
        match = self.build_match()
        squad = match.shootout_squad(TeamSide.HOME)
        match.add_to_shootout_order(TeamSide.HOME, squad[2])
        match.add_to_shootout_order(TeamSide.HOME, squad[1])

        restored = MatchState.from_dict(match.to_dict(), self.rules)

        self.assertEqual(
            restored.shootout_order(TeamSide.HOME), [squad[2], squad[1]],
        )
        self.assertTrue(restored.pending_shootout)
        self.assertEqual(restored.shootout_round, 1)

    def test_the_first_round_reads_its_shooter_off_the_order(self) -> None:
        match = self.build_match()
        self.order_both_sides(match)
        squad = match.shootout_squad(TeamSide.HOME)

        self.assertEqual(match.shootout_shooter(TeamSide.HOME), squad[0])
        self.assertTrue(match.shootout_shooters_complete)

        match.finish_shootout_test()

        self.assertEqual(match.shootout_shooter(TeamSide.HOME), squad[1])
        self.assertEqual(match.shootout_tests_taken(TeamSide.HOME), 1)

    def test_a_goal_goes_on_the_scoreboard_as_well(self) -> None:
        match = self.build_match(2, 2)

        match.award_shootout_goal(
            TeamSide.HOME, match.home.field_players[0],
        )

        self.assertEqual(match.scoreboard.home_score, 3)
        self.assertEqual(match.shootout_goals_for(TeamSide.HOME), 1)
        self.assertEqual(match.scoreboard.visiting_score, 2)

    def test_a_lead_bigger_than_the_tests_left_ends_the_round(self) -> None:
        # 4-1 with two still to shoot: the trailing side can reach 3 at
        # best, so there is no point rolling either of them.
        match = self.build_match()
        self.order_both_sides(match)

        match.award_shootout_goal(
            TeamSide.VISITING, match.visiting.field_players[0],
        )
        for test_number in range(4):
            match.award_shootout_goal(
            TeamSide.HOME, match.home.field_players[0],
        )
            match.finish_shootout_test()
            if test_number < 3:
                self.assertIsNone(
                    match.shootout_winner(),
                    f"settled too early, after test {test_number + 1}",
                )

        self.assertEqual(match.shootout_tests_taken(TeamSide.HOME), 4)
        self.assertEqual(match.shootout_winner(), TeamSide.HOME)

    def test_a_lead_that_can_still_be_caught_rolls_on(self) -> None:
        match = self.build_match()
        self.order_both_sides(match)

        for _ in range(3):
            match.award_shootout_goal(
            TeamSide.HOME, match.home.field_players[0],
        )
            match.finish_shootout_test()

        # 3-0 with three still to shoot is exactly catchable.
        self.assertIsNone(match.shootout_winner())

    def test_a_level_round_opens_sudden_death(self) -> None:
        match = self.build_match()
        self.order_both_sides(match)

        for _ in range(6):
            match.finish_shootout_test()

        self.assertIsNone(match.shootout_winner())
        self.assertEqual(match.shootout_round, 2)
        # Everybody is eligible again, and nobody is out until a coach
        # sends them.
        self.assertEqual(
            len(match.shootout_eligible(TeamSide.HOME)), 6,
        )
        self.assertIsNone(match.shootout_shooter(TeamSide.HOME))
        self.assertFalse(match.shootout_shooters_complete)

    def test_sudden_death_is_decided_by_the_first_test_won(self) -> None:
        match = self.build_match()
        self.order_both_sides(match)
        for _ in range(6):
            match.finish_shootout_test()

        squad = match.shootout_squad(TeamSide.VISITING)
        match.set_shootout_shooter(
            TeamSide.HOME, match.shootout_squad(TeamSide.HOME)[4],
        )
        match.set_shootout_shooter(TeamSide.VISITING, squad[4])
        match.award_shootout_goal(
            TeamSide.VISITING, match.visiting.field_players[0],
        )
        match.finish_shootout_test()

        self.assertEqual(match.shootout_winner(), TeamSide.VISITING)

    def test_a_tied_sudden_death_test_settles_nothing(self) -> None:
        match = self.build_match()
        self.order_both_sides(match)
        for _ in range(6):
            match.finish_shootout_test()

        for side in (TeamSide.HOME, TeamSide.VISITING):
            match.set_shootout_shooter(
                side, match.shootout_squad(side)[0],
            )
        match.finish_shootout_test()

        self.assertIsNone(match.shootout_winner())
        self.assertEqual(match.shootout_round, 2)
        self.assertEqual(len(match.shootout_eligible(TeamSide.HOME)), 5)

    def test_a_sudden_death_round_resets_when_everyone_has_gone(
        self,
    ) -> None:
        match = self.build_match()
        self.order_both_sides(match)
        for _ in range(6):
            match.finish_shootout_test()

        for _ in range(6):
            for side in (TeamSide.HOME, TeamSide.VISITING):
                match.set_shootout_shooter(
                    side, match.shootout_eligible(side)[0],
                )
            match.finish_shootout_test()

        self.assertEqual(match.shootout_round, 3)
        self.assertEqual(len(match.shootout_eligible(TeamSide.HOME)), 6)

    def test_a_player_cannot_shoot_twice_in_one_round(self) -> None:
        match = self.build_match()
        self.order_both_sides(match)
        for _ in range(6):
            match.finish_shootout_test()

        squad = match.shootout_squad(TeamSide.HOME)
        match.set_shootout_shooter(TeamSide.HOME, squad[0])
        match.set_shootout_shooter(
            TeamSide.VISITING, match.shootout_squad(TeamSide.VISITING)[0],
        )
        match.finish_shootout_test()

        with self.assertRaises(ValueError):
            match.set_shootout_shooter(TeamSide.HOME, squad[0])

    def test_the_retirement_rides_in_the_roll_s_own_save(self) -> None:
        # It is the roll that retires the shooters, and it does so in
        # the save that records the goal -- so a restart between the
        # roll and what follows it comes back to the next test, never
        # to the one already paid for.
        match = self.build_match()
        self.order_both_sides(match)
        match.award_shootout_goal(
            TeamSide.HOME, match.home.field_players[0],
        )
        match.finish_shootout_test()

        restored = MatchState.from_dict(match.to_dict(), self.rules)

        self.assertEqual(restored.shootout_tests_taken(TeamSide.HOME), 1)
        self.assertEqual(restored.shootout_goals_for(TeamSide.HOME), 1)
        self.assertEqual(restored.scoreboard.home_score, 3)


class ShootoutFlowTests(unittest.IsolatedAsyncioTestCase):
    """The cog's half: who is asked for what, and in which order."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    def build_match(self, home_score: int = 2, visiting_score: int = 2):
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
        )
        match.scoreboard.period = MatchPeriod.SECOND_HALF
        match.scoreboard.time = 15
        match.scoreboard.last_possession = True
        match.scoreboard.home_score = home_score
        match.scoreboard.visiting_score = visiting_score
        return match

    async def test_a_level_full_time_opens_the_last_window(self) -> None:
        cog = build_cog()
        game = build_game()
        match = self.build_match()
        game.match_state = match.to_dict()
        cog.games[game.game_id] = game
        interaction = build_interaction()

        with suppressed_cog_saves():
            await cog.end_period(interaction, game, match)

        # The game is not over: it is the shootout that ends it, and
        # one substitution a side comes before the shooting starts.
        self.assertFalse(game.is_finished)
        self.assertIsNone(game.rematch_message_id)
        self.assertEqual(match.pending_full_time_stage, "coaching_home")
        self.assertFalse(match.pending_shootout)
        texts = sent_texts(interaction)
        self.assertIn("Full time!", texts[0])
        self.assertIn("Before the shootout", texts[1])

    async def test_the_whistle_recovers_no_exhaustion(self) -> None:
        # Halftime takes a token off every fielded player; full time
        # takes nothing off anybody, so a side goes to the shootout
        # still holding what the second half left it with -- and its
        # Exhausted players still owe a check on every test.
        cog = build_cog()
        game = build_game()
        match = self.build_match()
        tired = match.home.field_players[0]
        match.add_exhaustion(tired, 4)
        match.exhausted.add(tired)
        game.match_state = match.to_dict()
        cog.games[game.game_id] = game
        interaction = build_interaction()

        with suppressed_cog_saves():
            await cog.end_period(interaction, game, match)

        reloaded = cog.engine.load_match_state(game)
        self.assertEqual(reloaded.exhaustion.get(tired), 4)
        self.assertIn(tired, reloaded.exhausted)

    async def test_an_uneven_full_time_still_just_ends(self) -> None:
        cog = build_cog()
        game = build_game()
        match = self.build_match(3, 1)
        game.match_state = match.to_dict()
        cog.games[game.game_id] = game
        interaction = build_interaction()

        with suppressed_cog_saves():
            await cog.end_period(interaction, game, match)

        self.assertTrue(game.is_finished)
        self.assertFalse(match.pending_shootout)
        self.assertIn("# Orange wins!", sent_texts(interaction)[0])

    async def test_the_ai_orders_its_own_six(self) -> None:
        cog = build_cog()
        game = build_game(
            player_2_id=None,
            player_2_name=None,
            ai_opponent=AIOpponent.DINKY,
        )
        match = self.build_match()
        game.match_state = match.to_dict()
        cog.games[game.game_id] = game
        interaction = build_interaction()

        with suppressed_cog_saves():
            await cog.begin_shootout(interaction, game, match)

        self.assertTrue(match.shootout_order_complete(TeamSide.VISITING))
        self.assertFalse(match.shootout_order_complete(TeamSide.HOME))
        # Its own six in some order, and only the human is waited on.
        order = match.shootout_order(TeamSide.VISITING)
        self.assertCountEqual(order, match.shootout_squad(TeamSide.VISITING))
        self.assertIn("<@111>", sent_texts(interaction)[-1])

    async def test_both_orders_in_reveals_the_first_test(self) -> None:
        cog = build_cog()
        game = build_game()
        match = self.build_match()
        match.begin_shootout()
        match.set_shootout_order(
            TeamSide.VISITING, match.shootout_squad(TeamSide.VISITING),
        )
        game.match_state = match.to_dict()
        cog.games[game.game_id] = game
        interaction = build_interaction()

        squad = match.shootout_squad(TeamSide.HOME)
        view = ShootoutOrderSelectView(cog, game.game_id, TeamSide.HOME)
        with suppressed_view_saves(), suppressed_cog_saves():
            for player_id in squad:
                await view.pick(interaction, player_id)

        reloaded = cog.engine.load_match_state(game)
        self.assertEqual(reloaded.shootout_order(TeamSide.HOME), squad)
        self.assertIn("Either player can roll", sent_texts(interaction)[-1])
        posted = interaction.followup.send.await_args.kwargs["view"]
        self.assertIsInstance(posted, ShootoutTestView)

    async def test_the_prompt_names_the_state_a_restart_comes_back_to(
        self,
    ) -> None:
        cog = build_cog()
        game = build_game()
        match = self.build_match()
        match.begin_shootout()

        view, ask = cog.pending_turn_view(game.game_id, match)
        self.assertIsInstance(view, ShootoutOrderPromptView)
        self.assertIn("shooting order", ask)

        for side in (TeamSide.HOME, TeamSide.VISITING):
            match.set_shootout_order(side, match.shootout_squad(side))

        # Round 1 needs no pick: the order says who is next.
        view, ask = cog.pending_turn_view(game.game_id, match)
        self.assertIsInstance(view, ShootoutTestView)

        for _ in range(6):
            match.finish_shootout_test()

        view, ask = cog.pending_turn_view(game.game_id, match)
        self.assertIsInstance(view, ShootoutPickPromptView)
        self.assertIn("shoots next", ask)

    async def test_an_owed_injury_test_is_asked_for_first(self) -> None:
        cog = build_cog()
        game = build_game()
        match = self.build_match()
        match.begin_shootout()
        for side in (TeamSide.HOME, TeamSide.VISITING):
            match.set_shootout_order(side, match.shootout_squad(side))
        match.pending_injury_tests = [match.home.field_players[0]]

        view, ask = cog.pending_turn_view(game.game_id, match)

        self.assertIn("injury test", ask)


class PreShootoutCoachingTests(unittest.IsolatedAsyncioTestCase):
    """
    The Coaching Choice between the whistle and the shooting: one
    substitution a side, home first, and nothing else offered. See
    "Full time" in docs/living-rules.md.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    def build(self, **game_overrides):
        cog = build_cog()
        game = build_game(**game_overrides)
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
        )
        match.scoreboard.period = MatchPeriod.SECOND_HALF
        match.scoreboard.home_score = 2
        match.scoreboard.visiting_score = 2
        game.match_state = match.to_dict()
        cog.games[game.game_id] = game
        return cog, game, match

    async def test_home_coaches_first_then_the_visitors_then_the_shooting(
        self,
    ) -> None:
        cog, game, match = self.build()

        with suppressed_cog_saves():
            await cog.begin_full_time_coaching(
                build_interaction(), game, match,
            )
            self.assertEqual(match.pending_coaching_side, "home")
            self.assertEqual(
                match.coaching_occasion, CoachingOccasion.FULL_TIME,
            )
            self.assertFalse(match.pending_shootout)

            await cog.finish_substitution_window(
                build_interaction(), game, match,
            )
            self.assertEqual(match.pending_coaching_side, "visiting")
            self.assertFalse(match.pending_shootout)

            await cog.finish_substitution_window(
                build_interaction(), game, match,
            )

        self.assertIsNone(match.pending_full_time_stage)
        self.assertIsNone(match.pending_coaching_side)
        self.assertTrue(match.pending_shootout)

    async def test_one_substitution_and_it_is_the_window_s_own(self) -> None:
        cog, game, match = self.build()
        # Both halves' allowances are already spent, which changes
        # nothing here: full time's one is counted inside the window.
        match.half_substitutions_used = {"home": 2}

        with suppressed_cog_saves():
            await cog.begin_full_time_coaching(
                build_interaction(), game, match,
            )

            self.assertEqual(match.substitutions_remaining(), 1)
            self.assertEqual(
                cog.engine.substitution_button_label(match),
                "1 left before the shootout",
            )

            cog.apply_substitution(
                match,
                TeamSide.HOME,
                match.home.field_players[0],
                match.home.team_board.bench[0],
            )

        self.assertEqual(match.substitutions_remaining(), 0)
        self.assertFalse(match.may_substitute())
        self.assertEqual(match.half_substitutions_used, {"home": 2})

    async def test_the_menu_offers_the_substitution_alone(self) -> None:
        # A shootout is played by who is on the field and by nothing
        # about where they stand, so the three positional actions are
        # not built at all -- not built and disabled, since there is
        # nothing a coach could do to enable them.
        cog, game, match = self.build()

        with suppressed_cog_saves():
            await cog.begin_full_time_coaching(
                build_interaction(), game, match,
            )

        labels = [
            item.label
            for item in CoachingHubView(cog, game.game_id).children
        ]
        self.assertEqual(
            labels,
            [
                "Substitution (1 left before the shootout)",
                "Team roster",
                "Done coaching",
            ],
        )

    async def test_a_side_with_nobody_to_bring_on_is_passed_over(
        self,
    ) -> None:
        cog, game, match = self.build()
        # It takes both benches: three substitutions to drain the
        # bench, and every one of the three who came off injured, so
        # the back bench has nothing to offer back. The menu would
        # otherwise be a Done button with extra steps.
        for outgoing in match.home.field_players[:3]:
            match.mark_injured(outgoing)
            match.substitute(
                TeamSide.HOME, outgoing, match.home.team_board.bench[0],
            )
        self.assertEqual(match.substitution_pool(TeamSide.HOME), [])
        game.match_state = match.to_dict()

        with suppressed_cog_saves():
            await cog.begin_full_time_coaching(
                build_interaction(), game, match,
            )

        self.assertEqual(match.pending_coaching_side, "visiting")
        self.assertEqual(match.pending_full_time_stage, "coaching_visiting")

    async def test_the_window_leaves_the_arrangement_alone(self) -> None:
        # Nothing is played from a position after this, so the window
        # neither opens on the coach's arrangement -- which would
        # rearrange the last board of the game -- nor records where the
        # second half left them over the top of it.
        cog, game, match = self.build()
        match.set_assigned_positions(TeamSide.HOME)
        arrangement = {
            player_id: list(position)
            for player_id, position in match.assigned_positions.items()
        }
        strayed = match.home.field_players[0]
        zone, space = match.board.meeple_position(strayed)
        match.board.remove_meeple(strayed)
        match.board.place_meeple(strayed, zone, 1 - space)

        with suppressed_cog_saves():
            await cog.begin_full_time_coaching(
                build_interaction(), game, match,
            )
            self.assertEqual(
                match.board.meeple_position(strayed), (zone, 1 - space),
            )
            await cog.finish_substitution_window(
                build_interaction(), game, match,
            )

        self.assertEqual(match.assigned_positions, arrangement)

    async def test_a_substitute_shoots(self) -> None:
        # The six who shoot are the six on the field when the shootout
        # starts, which is after this window and not before it.
        cog, game, match = self.build()

        with suppressed_cog_saves():
            await cog.begin_full_time_coaching(
                build_interaction(), game, match,
            )
            outgoing = match.home.field_players[0]
            incoming = match.home.team_board.bench[0]
            cog.apply_substitution(
                match, TeamSide.HOME, outgoing, incoming,
            )
            await cog.finish_substitution_window(
                build_interaction(), game, match,
            )
            await cog.finish_substitution_window(
                build_interaction(), game, match,
            )

        squad = match.shootout_squad(TeamSide.HOME)
        self.assertIn(incoming, squad)
        self.assertNotIn(outgoing, squad)
        self.assertEqual(len(squad), 6)

    async def test_a_restart_comes_back_to_the_hub(self) -> None:
        cog, game, match = self.build()

        with suppressed_cog_saves():
            await cog.begin_full_time_coaching(
                build_interaction(), game, match,
            )

        # Through a save and back, since this is what a restart reads.
        reloaded = cog.engine.load_match_state(game)
        self.assertEqual(reloaded.pending_full_time_stage, "coaching_home")
        view, ask = cog.pending_turn_view(game.game_id, reloaded)
        self.assertIsInstance(view, CoachingHubView)
        self.assertIn("before the shootout", ask)

    async def test_a_restart_between_the_two_coaches_is_driven_on(
        self,
    ) -> None:
        # The visitors' window is the bot's own next step, so a process
        # that died after the home coach finished left nothing to
        # click. Resume hands it back to the sequence.
        cog, game, match = self.build()
        match.pending_full_time_stage = "coaching_visiting"
        game.match_state = match.to_dict()

        with suppressed_cog_saves():
            where = await cog.resume_pending_prompt(
                build_interaction(222), game, cog.engine.load_match_state(game),
            )

        self.assertIn("before the shootout", where)
        reloaded = cog.engine.load_match_state(game)
        self.assertEqual(reloaded.pending_coaching_side, "visiting")

    async def test_the_ai_takes_its_own_window(self) -> None:
        # Dinky only ever substitutes to get an injured player off, so
        # a healthy side simply finishes -- and either way the shootout
        # is what it hands on to.
        cog, game, match = self.build(
            player_2_id=None,
            player_2_name=None,
            ai_opponent=AIOpponent.DINKY,
        )
        hurt = match.visiting.field_players[0]
        match.injured.add(hurt)
        interaction = build_interaction()

        with suppressed_cog_saves():
            await cog.begin_full_time_coaching(interaction, game, match)
            self.assertEqual(match.pending_coaching_side, "home")
            await cog.finish_substitution_window(interaction, game, match)

        self.assertNotIn(hurt, match.visiting.field_players)
        self.assertTrue(match.pending_shootout)


class ShootoutRollTests(unittest.IsolatedAsyncioTestCase):
    """The roll itself: what is added, what is charged, what is owed."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    def build_shootout(self, cog, **game_overrides):
        game = build_game(**game_overrides)
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
        )
        match.scoreboard.period = MatchPeriod.SECOND_HALF
        match.scoreboard.home_score = 1
        match.scoreboard.visiting_score = 1
        match.begin_shootout()
        for side in (TeamSide.HOME, TeamSide.VISITING):
            match.set_shootout_order(side, by_role(match, side))
        game.match_state = match.to_dict()
        cog.games[game.game_id] = game
        return game, match

    async def roll(self, cog, game, rolls: list[int]):
        interaction = build_interaction()
        view = ShootoutTestView(cog, game.game_id)
        with suppressed_view_saves(), suppressed_cog_saves(), mock.patch(
            "cogs.d12ball_views.base.render_skill_test_dice",
            return_value=b"",
        ), mock.patch(
            "discord.File", return_value=None,
        ), mock.patch(
            "random.randint", side_effect=rolls,
        ):
            await view.roll(interaction)
        return interaction

    async def test_the_higher_total_scores_a_goal(self) -> None:
        cog = build_cog()
        cog.begin_injury_tests = mock.AsyncMock()
        game, match = self.build_shootout(cog)
        home_shooter = match.shootout_shooter(TeamSide.HOME)

        interaction = await self.roll(cog, game, [12, 1])

        reloaded = cog.engine.load_match_state(game)
        self.assertEqual(reloaded.shootout_goals_for(TeamSide.HOME), 1)
        self.assertEqual(reloaded.scoreboard.home_score, 2)
        self.assertEqual(reloaded.scoreboard.visiting_score, 1)
        self.assertIn(
            cog.engine.get_player_definition(home_shooter).name,
            sent_texts(interaction)[0],
        )
        # The shooters are retired in the same save as the goal.
        self.assertEqual(reloaded.shootout_tests_taken(TeamSide.HOME), 1)

    async def test_a_tie_scores_for_nobody_and_is_not_re_rolled(
        self,
    ) -> None:
        # Both sides field the same six in the same order, so equal
        # dice are equal totals.
        cog = build_cog()
        cog.begin_injury_tests = mock.AsyncMock()
        game, match = self.build_shootout(cog)

        interaction = await self.roll(cog, game, [7, 7])

        reloaded = cog.engine.load_match_state(game)
        self.assertEqual(reloaded.shootout_goals, {})
        self.assertEqual(reloaded.scoreboard.home_score, 1)
        self.assertEqual(reloaded.shootout_tests_taken(TeamSide.HOME), 1)
        self.assertIn("A tie", sent_texts(interaction)[0])
        cog.refresh_match_image.assert_not_awaited()

    async def test_an_injured_shooter_adds_no_skill_modifier(self) -> None:
        cog = build_cog()
        cog.begin_injury_tests = mock.AsyncMock()
        game, match = self.build_shootout(cog)
        # The home shooter is injured, so their skill is withheld; the
        # visiting one keeps theirs. Equal dice must therefore lose.
        match.mark_injured(match.shootout_shooter(TeamSide.HOME))
        game.match_state = match.to_dict()

        await self.roll(cog, game, [7, 7])

        reloaded = cog.engine.load_match_state(game)
        self.assertEqual(reloaded.shootout_goals_for(TeamSide.VISITING), 1)
        self.assertEqual(reloaded.shootout_goals_for(TeamSide.HOME), 0)

    async def test_a_test_costs_no_exhaustion(self) -> None:
        cog = build_cog()
        cog.begin_injury_tests = mock.AsyncMock()
        game, match = self.build_shootout(cog)
        shooter = match.shootout_shooter(TeamSide.HOME)
        match.add_exhaustion(shooter, 2)
        game.match_state = match.to_dict()

        await self.roll(cog, game, [9, 3])

        reloaded = cog.engine.load_match_state(game)
        self.assertEqual(reloaded.exhaustion.get(shooter), 2)

    async def test_an_exhausted_shooter_owes_no_injury_check(
        self,
    ) -> None:
        # 2026-08-15: a shootout test costs no exhaustion and owes no
        # check either, so an Exhausted shooter carries the condition
        # through the shootout unchanged. It reverses half of the
        # 2026-08-10 ruling -- see the rules log.
        cog = build_cog()
        cog.begin_injury_tests = mock.AsyncMock()
        cog.continue_shootout = mock.AsyncMock()
        game, match = self.build_shootout(cog)
        shooter = match.shootout_shooter(TeamSide.HOME)
        match.exhausted.add(shooter)
        game.match_state = match.to_dict()

        await self.roll(cog, game, [9, 3])

        cog.begin_injury_tests.assert_not_awaited()
        cog.continue_shootout.assert_awaited_once()
        self.assertNotIn(shooter, cog.engine.load_match_state(game).injured)

    async def test_the_last_test_of_the_shootout_ends_the_game(
        self,
    ) -> None:
        cog = build_cog()
        game, match = self.build_shootout(cog)
        # Everybody has shot but one, and the home side leads 3-2, so
        # the visiting side has to win this to stay in it.
        for _ in range(5):
            match.finish_shootout_test()
        for _ in range(3):
            match.award_shootout_goal(
            TeamSide.HOME, match.home.field_players[0],
        )
        for _ in range(2):
            match.award_shootout_goal(
            TeamSide.VISITING, match.visiting.field_players[0],
        )
        game.match_state = match.to_dict()

        interaction = await self.roll(cog, game, [12, 1])

        self.assertTrue(game.is_finished)
        reloaded = cog.engine.load_match_state(game)
        self.assertFalse(reloaded.pending_shootout)
        final = sent_texts(interaction)[-1]
        self.assertIn("extreme shootout is settled, 4-2", final)
        self.assertIn("# Orange wins!", final)
        self.assertEqual(game.rematch_message_id, 999)

    async def test_a_level_sixth_test_goes_to_sudden_death(self) -> None:
        cog = build_cog()
        cog.begin_injury_tests = mock.AsyncMock()
        game, match = self.build_shootout(cog)
        for _ in range(5):
            match.finish_shootout_test()
        game.match_state = match.to_dict()

        interaction = await self.roll(cog, game, [7, 7])
        # Nothing scored, so the roll's continuation is the one the
        # injury queue would have made.
        with suppressed_cog_saves():
            await cog.continue_shootout(
                interaction, game, cog.engine.load_match_state(game),
            )

        self.assertFalse(game.is_finished)
        reloaded = cog.engine.load_match_state(game)
        self.assertEqual(reloaded.shootout_round, 2)
        self.assertIn("sudden death", sent_texts(interaction)[-1])
        posted = interaction.followup.send.await_args.kwargs["view"]
        self.assertIsInstance(posted, ShootoutPickPromptView)


class ShootoutMenuRestoreTests(unittest.IsolatedAsyncioTestCase):
    """
    The shooting order and the sudden-death shooter are the game's only
    ephemeral views now that the maneuver pick has gone public -- a
    coach must not see the other side's order before it is shot, and
    ephemeral is the only thing Discord offers that hides it. So they
    are also the only views a restart cannot re-attach to their message:
    the bot never holds a durable handle to an ephemeral message.

    `add_view` without a message id is the way round it, and discord.py
    dispatching such a view by custom_id alone is the load-bearing
    claim -- exercised against a real ViewStore rather than asserted
    about, because the whole restore rests on that fallback surviving a
    library upgrade.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    def build(self):
        cog = build_cog()
        cog.bot = SimpleNamespace(add_view=mock.Mock())
        game = build_game()
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
        )
        match.begin_shootout()
        game.match_state = match.to_dict()
        cog.games[game.game_id] = game
        return cog, game, match

    def test_both_sides_are_restored_while_both_owe_an_order(self) -> None:
        cog, game, match = self.build()

        self.assertEqual(cog.restore_shootout_menus(game, match), 2)

    def test_a_side_that_has_set_its_order_is_not_restored(self) -> None:
        cog, game, match = self.build()
        match.set_shootout_order(
            TeamSide.HOME, match.shootout_squad(TeamSide.HOME),
        )

        self.assertEqual(cog.restore_shootout_menus(game, match), 1)
        self.assertEqual(
            cog.bot.add_view.call_args.args[0].side, TeamSide.VISITING,
        )

    def test_the_restored_menu_is_registered_with_no_message_id(
        self,
    ) -> None:
        """
        The whole trick: there is no id to give, because the bot never
        holds a durable handle to an ephemeral message.
        """
        cog, game, match = self.build()

        cog.restore_shootout_menus(game, match)

        for call in cog.bot.add_view.call_args_list:
            self.assertNotIn("message_id", call.kwargs)
            self.assertTrue(call.args[0].is_persistent())

    async def test_discord_dispatches_it_by_custom_id_alone(self) -> None:
        """
        `add_view` with no message_id lands under a None key, and
        `dispatch_view` falls back to that key when the message it was
        clicked on is unknown -- which every ephemeral message is. Run
        through discord.py's own store, because the whole restore rests
        on that fallback surviving an upgrade.
        """
        import asyncio

        import discord
        from discord.ui.view import ViewStore

        cog, game, match = self.build()
        store = ViewStore(SimpleNamespace(loop=asyncio.get_running_loop()))
        cog.bot = SimpleNamespace(
            add_view=lambda view, message_id=None: store.add_view(
                view, message_id,
            ),
        )

        cog.restore_shootout_menus(game, match)
        custom_id = next(
            item.custom_id
            for item in ShootoutOrderSelectView(
                cog, game.game_id, TeamSide.HOME,
            ).children
        )

        # Stopping at _dispatch_item rather than letting the callback
        # run: what is under test is the lookup, and everything past
        # this point is discord.py driving a real interaction.
        dispatched: list = []
        with mock.patch.object(
            ShootoutOrderSelectView,
            "_dispatch_item",
            lambda self, item, interaction: dispatched.append(item),
        ):
            store.dispatch_view(
                discord.ComponentType.button.value,
                custom_id,
                # An id no view was registered under: an ephemeral
                # message the bot has never seen before.
                SimpleNamespace(message=SimpleNamespace(id=123456789)),
            )

        self.assertEqual(len(dispatched), 1, "the None-keyed fallback is gone")


class ShootoutMenuTests(unittest.IsolatedAsyncioTestCase):
    """The two ephemeral menus, and what a stale click does."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    def build_shootout(self, cog, sudden_death: bool = False):
        game = build_game()
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
        )
        match.begin_shootout()
        if sudden_death:
            for side in (TeamSide.HOME, TeamSide.VISITING):
                match.set_shootout_order(side, match.shootout_squad(side))
            for _ in range(6):
                match.finish_shootout_test()
        game.match_state = match.to_dict()
        cog.games[game.game_id] = game
        return game, match

    async def test_a_set_order_is_shown_rather_than_reopened(self) -> None:
        cog = build_cog()
        game, match = self.build_shootout(cog)
        match.set_shootout_order(
            TeamSide.HOME, match.shootout_squad(TeamSide.HOME),
        )
        game.match_state = match.to_dict()
        interaction = build_interaction(user_id=111)

        await ShootoutOrderPromptView(cog, game.game_id).open_menu(
            interaction,
        )

        kwargs = interaction.response.send_message.await_args.kwargs
        self.assertTrue(kwargs["ephemeral"])
        self.assertNotIn("view", kwargs)
        self.assertIn(
            "Your order is set",
            interaction.response.send_message.await_args.args[0],
        )

    async def test_only_a_coach_in_the_game_is_offered_the_menu(
        self,
    ) -> None:
        cog = build_cog()
        game, _ = self.build_shootout(cog)
        interaction = build_interaction(user_id=999)

        await ShootoutOrderPromptView(cog, game.game_id).open_menu(
            interaction,
        )

        self.assertIn(
            "Only a coach",
            interaction.response.send_message.await_args.args[0],
        )

    async def test_sudden_death_offers_only_the_unused(self) -> None:
        cog = build_cog()
        game, match = self.build_shootout(cog, sudden_death=True)
        squad = match.shootout_squad(TeamSide.HOME)
        match.set_shootout_shooter(TeamSide.HOME, squad[0])
        match.finish_shootout_test()
        game.match_state = match.to_dict()

        view = ShootoutPickSelectView(cog, game.game_id, TeamSide.HOME)

        self.assertEqual(len(view.children), 5)
        self.assertNotIn(
            squad[0],
            [item.custom_id.rsplit(":", 1)[-1] for item in view.children],
        )

    async def test_a_stale_order_click_is_answered_not_acted_on(
        self,
    ) -> None:
        # The registration that keeps an open menu alive across a
        # restart outlives the order it was set for.
        cog = build_cog()
        game, match = self.build_shootout(cog)
        squad = match.shootout_squad(TeamSide.HOME)
        match.add_to_shootout_order(TeamSide.HOME, squad[0])
        game.match_state = match.to_dict()
        interaction = build_interaction(user_id=111)

        view = ShootoutOrderSelectView(cog, game.game_id, TeamSide.HOME)
        with suppressed_view_saves():
            await view.pick(interaction, squad[0])

        self.assertEqual(
            cog.engine.load_match_state(game).shootout_order(TeamSide.HOME),
            [squad[0]],
        )
        content = interaction.response.edit_message.await_args.kwargs[
            "content"
        ]
        self.assertIn("not still to be put in the order", content)

    async def test_starting_over_empties_a_part_built_order(self) -> None:
        cog = build_cog()
        game, match = self.build_shootout(cog)
        squad = match.shootout_squad(TeamSide.HOME)
        match.add_to_shootout_order(TeamSide.HOME, squad[0])
        game.match_state = match.to_dict()
        interaction = build_interaction(user_id=111)

        view = ShootoutOrderSelectView(cog, game.game_id, TeamSide.HOME)
        with suppressed_view_saves(), suppressed_cog_saves():
            await view.restart(interaction)

        self.assertEqual(
            cog.engine.load_match_state(game).shootout_order(TeamSide.HOME), [],
        )

    async def test_one_coach_running_both_sides_can_answer_twice(
        self,
    ) -> None:
        # A test game is one user coaching both sides. The side that
        # still owes an answer is the one the button opens.
        cog = build_cog()
        game, match = self.build_shootout(cog)
        game.test_game = True
        game.player_2_id = game.player_1_id
        match.set_shootout_order(
            TeamSide.HOME, match.shootout_squad(TeamSide.HOME),
        )
        game.match_state = match.to_dict()
        interaction = build_interaction(user_id=111)

        await ShootoutOrderPromptView(cog, game.game_id).open_menu(
            interaction,
        )

        view = interaction.response.send_message.await_args.kwargs["view"]
        self.assertEqual(view.side, TeamSide.VISITING)

    async def test_a_coach_may_look_at_their_own_order(self) -> None:
        # The rule is "look at it but not reorder it", and the prompt
        # that set it is deleted once both sides are in -- so the roll
        # message is where a coach goes back to read it.
        cog = build_cog()
        game, match = self.build_shootout(cog)
        for side in (TeamSide.HOME, TeamSide.VISITING):
            match.set_shootout_order(side, match.shootout_squad(side))
        game.match_state = match.to_dict()
        interaction = build_interaction(user_id=111)

        await ShootoutTestView(cog, game.game_id).review(interaction)

        kwargs = interaction.response.send_message.await_args.kwargs
        self.assertTrue(kwargs["ephemeral"])
        shown = interaction.response.send_message.await_args.args[0]
        self.assertIn("not reorder it", shown)
        for player_id in match.shootout_squad(TeamSide.HOME):
            self.assertIn(
                cog.engine.get_player_definition(player_id).name, shown,
            )

    async def test_sudden_death_has_no_order_to_look_at(self) -> None:
        cog = build_cog()
        game, match = self.build_shootout(cog, sudden_death=True)
        interaction = build_interaction(user_id=111)

        await ShootoutTestView(cog, game.game_id).review(interaction)

        shown = interaction.response.send_message.await_args.args[0]
        self.assertIn("Still to go out this round", shown)

    def test_the_order_menu_fits_discord_s_rows(self) -> None:
        cog = build_cog()
        game, _ = self.build_shootout(cog)

        view = ShootoutOrderSelectView(cog, game.game_id, TeamSide.HOME)

        self.assertEqual(len(view.children), 7)
        self.assertLessEqual(len(view.children), 25)

    async def test_a_set_order_cannot_be_started_over(self) -> None:
        cog = build_cog()
        game, match = self.build_shootout(cog)
        match.set_shootout_order(
            TeamSide.HOME, match.shootout_squad(TeamSide.HOME),
        )
        game.match_state = match.to_dict()
        interaction = build_interaction(user_id=111)

        view = ShootoutOrderSelectView(cog, game.game_id, TeamSide.HOME)
        with suppressed_view_saves():
            await view.restart(interaction)

        self.assertEqual(
            len(cog.engine.load_match_state(game).shootout_order(TeamSide.HOME)),
            6,
        )
        self.assertIn(
            "cannot be changed",
            interaction.response.edit_message.await_args.kwargs["content"],
        )


if __name__ == "__main__":
    unittest.main()
