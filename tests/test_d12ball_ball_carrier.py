"""
The ball carrier.

"The ball is carried by a player, not held by a space" -- where a
resolution leaves the ball with somebody in particular, that player
takes their team's next turn instead of the coach choosing again off
the ball's space (docs/living-rules.md, "The ball carrier").

Two halves to it. `MatchState.turn_handler_candidates` is the whole of
the rule as the turn sees it, and everything that offers a handler goes
through it. The rest is which resolutions name a carrier and which
leave the ball free, which is asserted against the effects themselves
rather than against a list -- a maneuver that stopped setting one would
otherwise still pass.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

from cogs.d12ball import D12Ball
from cogs.d12ball_views import BallHandlerSelectionView, LooseBallSkillTestView
from d12ball.ai import build_ai_strategies
from d12ball.engine import RulesEngine
from d12ball.components import (
    MatchState,
    PlayerRole,
    TeamSide,
    Zone,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.game import D12BallGame, GameStatus, Team


def build_cog() -> D12Ball:
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
        cog.player_catalog, cog.basic_ruleset, cog.maneuver_catalog,
        cog.ai_strategies,
    )
    cog.refresh_match_image = mock.AsyncMock()
    cog.announce_board_update = mock.AsyncMock()
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
        status=GameStatus.IN_PROGRESS,
        home_player_number=1,
        visiting_player_number=2,
    )
    fields.update(overrides)
    return D12BallGame(**fields)


def build_interaction() -> SimpleNamespace:
    sent = SimpleNamespace(id=999)
    return SimpleNamespace(
        user=SimpleNamespace(id=111, display_name="One"),
        response=SimpleNamespace(defer=mock.AsyncMock()),
        followup=SimpleNamespace(send=mock.AsyncMock(return_value=sent)),
    )


def build_contest_interaction() -> SimpleNamespace:
    """The contest edits its own message, unlike the effects above."""
    return SimpleNamespace(
        user=SimpleNamespace(id=111, display_name="One"),
        channel=None,
        guild=None,
        followup=SimpleNamespace(
            send=mock.AsyncMock(return_value=SimpleNamespace(id=999)),
        ),
        response=SimpleNamespace(
            defer=mock.AsyncMock(),
            edit_message=mock.AsyncMock(),
            send_message=mock.AsyncMock(),
        ),
        edit_original_response=mock.AsyncMock(),
    )


def stack_two_home_players_on_the_ball(
    cog: D12Ball,
    match: MatchState,
) -> tuple[str, str]:
    """
    Home in possession in midfield with two of their players sharing
    the ball's space, so "who takes the turn" is a real choice for the
    carrier rule to take away. Returns the two, handler first.
    """
    midfielders = [
        player_id
        for player_id in match.home.field_players
        if match.board.meeple_position(player_id)[0] == Zone.MIDFIELD
    ]
    handler, teammate = midfielders[0], midfielders[1]
    zone, space_index = match.board.meeple_position(handler)
    match.board.remove_meeple(teammate)
    match.board.place_meeple(teammate, zone, space_index)

    match.ball.possession = TeamSide.HOME
    match.set_ball_space(zone, space_index)
    return handler, teammate


class TurnHandlerCandidateTests(unittest.TestCase):
    def build(self) -> tuple[D12Ball, D12BallGame, MatchState, str, str]:
        cog = build_cog()
        game = build_game()
        cog.games[game.game_id] = game
        match = cog.engine.initialize_standard_match(game)
        handler, teammate = stack_two_home_players_on_the_ball(cog, match)
        game.match_state = match.to_dict()
        return cog, game, match, handler, teammate

    def test_without_a_carrier_every_player_on_the_ball_is_offered(
        self,
    ) -> None:
        _, _, match, handler, teammate = self.build()

        self.assertIsNone(match.ball_carrier_id)
        self.assertCountEqual(
            match.turn_handler_candidates(), [handler, teammate],
        )

    def test_a_carrier_is_the_only_candidate(self) -> None:
        _, _, match, handler, teammate = self.build()

        match.set_ball_carrier(teammate)

        self.assertEqual(match.turn_handler_candidates(), [teammate])

    def test_selecting_anyone_but_the_carrier_is_refused(self) -> None:
        _, _, match, handler, teammate = self.build()
        match.set_ball_carrier(teammate)

        with self.assertRaises(ValueError):
            match.select_ball_handler(handler)

        self.assertIsNone(match.active_player_id)

    def test_selecting_the_carrier_consumes_the_carry(self) -> None:
        """
        A carry is worth exactly one turn: the resolution that ends the
        next turn is what decides who holds the ball after it.
        """
        _, _, match, _, teammate = self.build()
        match.set_ball_carrier(teammate)

        match.select_ball_handler(teammate)

        self.assertEqual(match.active_player_id, teammate)
        self.assertIsNone(match.ball_carrier_id)

    def test_a_carrier_off_the_ball_is_ignored_rather_than_trusted(
        self,
    ) -> None:
        """
        Nothing in the game should leave a carrier stranded off the
        ball, but a state saved across a period restart or an older
        build could -- and narrowing the turn to a player who cannot
        take it would strand the game rather than the value.
        """
        _, _, match, handler, teammate = self.build()
        match.set_ball_carrier(teammate)
        match.board.remove_meeple(teammate)
        match.board.place_meeple(teammate, Zone.HOME_GOAL, 0)

        self.assertEqual(match.turn_handler_candidates(), [handler])
        match.select_ball_handler(handler)
        self.assertEqual(match.active_player_id, handler)

    def test_an_opposing_carrier_is_ignored(self) -> None:
        """
        The two sides share spaces freely, so a carrier standing on the
        ball is not on its own proof they may take the turn.
        """
        _, _, match, handler, _ = self.build()
        opponent = match.visiting.field_players[0]
        match.board.remove_meeple(opponent)
        match.board.place_meeple(opponent, match.ball.zone, match.ball.space_index)

        match.set_ball_carrier(opponent)

        self.assertNotIn(opponent, match.turn_handler_candidates())
        self.assertIn(handler, match.turn_handler_candidates())

    def test_reset_maneuver_leaves_the_carry_alone(self) -> None:
        """
        The load-bearing one. reset_maneuver runs between the effect
        that sets the carrier and the prompt that spends it, so
        clearing it there would drop every carry on the floor -- and
        would make `/d12ball offensive_choice`, which calls it to start
        a turn fresh, a way to hand the ball to somebody else.
        """
        _, _, match, _, teammate = self.build()
        match.set_ball_carrier(teammate)

        match.reset_maneuver()

        self.assertEqual(match.ball_carrier_id, teammate)
        self.assertIsNone(match.active_player_id)

    def test_clear_ball_carrier_frees_the_choice_again(self) -> None:
        _, _, match, handler, teammate = self.build()
        match.set_ball_carrier(teammate)

        match.clear_ball_carrier()

        self.assertCountEqual(
            match.turn_handler_candidates(), [handler, teammate],
        )

    def test_the_carry_survives_a_save(self) -> None:
        cog, game, match, _, teammate = self.build()
        match.set_ball_carrier(teammate)
        game.match_state = match.to_dict()

        restored = cog.engine.load_match_state(game)

        self.assertEqual(restored.ball_carrier_id, teammate)
        self.assertEqual(restored.turn_handler_candidates(), [teammate])

    def test_a_game_saved_before_the_field_existed_loads(self) -> None:
        cog, _, match, handler, teammate = self.build()
        data = match.to_dict()
        del data["ball_carrier_id"]

        restored = MatchState.from_dict(data, cog.basic_ruleset)

        self.assertIsNone(restored.ball_carrier_id)
        self.assertCountEqual(
            restored.turn_handler_candidates(), [handler, teammate],
        )

    def test_the_ai_takes_the_carrier_over_the_better_skill(self) -> None:
        """
        DinkyAI otherwise picks the higher offensive skill off the
        ball's space, which is exactly the choice the rule removes.
        """
        cog, game, match, handler, teammate = self.build()
        strategy = cog.ai_strategies["dinky"]
        free_pick = strategy.choose_ball_handler(match)
        forced = handler if free_pick == teammate else teammate

        match.set_ball_carrier(forced)

        self.assertEqual(strategy.choose_ball_handler(match), forced)

    def test_the_selection_view_offers_only_the_carrier(self) -> None:
        cog, game, match, _, teammate = self.build()
        match.set_ball_carrier(teammate)
        game.match_state = match.to_dict()

        view = BallHandlerSelectionView(cog, game.game_id)

        self.assertEqual(
            [item.custom_id for item in view.children],
            [f"d12ball:ball_handler:{game.game_id}:{teammate}"],
        )


class CarrierFromResolutionTests(unittest.IsolatedAsyncioTestCase):
    """
    Which resolutions name a carrier, asserted by running the effect.
    """

    def build(self) -> tuple[D12Ball, D12BallGame, MatchState, str, str]:
        cog = build_cog()
        game = build_game()
        cog.games[game.game_id] = game
        match = cog.engine.initialize_standard_match(game)
        handler, teammate = stack_two_home_players_on_the_ball(cog, match)
        match.active_player_id = handler
        game.match_state = match.to_dict()
        return cog, game, match, handler, teammate

    def assertCarriedBy(self, match: MatchState, player_id: str) -> None:
        """
        Setting the field is not the rule -- the rule is that the named
        player takes the next turn, which also means the effect has to
        have left them standing on the ball for the side in
        possession. A carrier who is not eligible would silently fall
        back to a free choice.
        """
        self.assertEqual(match.ball_carrier_id, player_id)
        self.assertEqual(match.turn_handler_candidates(), [player_id])

    def challenger_on_the_ball(
        self,
        cog: D12Ball,
        match: MatchState,
        role: PlayerRole,
    ) -> str:
        """
        Put a visiting player of `role` on the ball's space and make
        them the challenger. Pressure is role-sensitive -- a Defender
        also steals the ball on a win -- so which role challenges is
        the whole difference between the two Pressure tests below.
        """
        challenger = next(
            player_id
            for player_id in match.visiting.field_players
            if cog.engine.get_player_definition(player_id).role == role
        )
        match.board.remove_meeple(challenger)
        match.board.place_meeple(
            challenger, match.ball.zone, match.ball.space_index,
        )
        match.challenger_id = challenger
        return challenger

    async def test_dribble_advance_leaves_it_with_the_dribbler(self) -> None:
        cog, game, match, handler, _ = self.build()
        cog.offer_speed_choice = mock.AsyncMock()

        with mock.patch("cogs.d12ball.save_games"):
            await cog.apply_dribble_advance(
                build_interaction(), game, match, 1,
            )

        self.assertCarriedBy(match, handler)

    async def test_steal_intercept_leaves_it_with_the_interceptor(
        self,
    ) -> None:
        cog, game, match, _, _ = self.build()
        challenger = self.challenger_on_the_ball(
            cog, match, PlayerRole.MIDFIELDER,
        )
        cog.begin_run_back = mock.AsyncMock()

        with mock.patch("cogs.d12ball.save_games"):
            await cog.resolve_steal_intercept(
                build_interaction(), game, match,
            )

        self.assertCarriedBy(match, challenger)

    async def test_pressure_leaves_it_with_the_player_pushed_back(
        self,
    ) -> None:
        cog, game, match, handler, _ = self.build()
        self.challenger_on_the_ball(cog, match, PlayerRole.MIDFIELDER)
        cog.finish_maneuver_resolution = mock.AsyncMock()
        cog.begin_run_back = mock.AsyncMock()

        with mock.patch("cogs.d12ball.save_games"):
            await cog.resolve_pressure(build_interaction(), game, match)

        self.assertEqual(match.ball.possession, TeamSide.HOME)
        self.assertCarriedBy(match, handler)

    async def test_a_defender_who_steals_on_pressure_carries_it(
        self,
    ) -> None:
        cog, game, match, _, _ = self.build()
        defender = self.challenger_on_the_ball(
            cog, match, PlayerRole.DEFENDER,
        )
        cog.finish_maneuver_resolution = mock.AsyncMock()
        cog.begin_run_back = mock.AsyncMock()

        with mock.patch("cogs.d12ball.save_games"):
            await cog.resolve_pressure(build_interaction(), game, match)

        self.assertEqual(match.ball.possession, TeamSide.VISITING)
        self.assertCarriedBy(match, defender)

    async def test_a_completed_low_pass_leaves_it_with_the_receiver(
        self,
    ) -> None:
        """
        The pass across a shared space: the receiver stays on the ball
        and the passer steps forward, so the two are easy to tell
        apart in the assertion.
        """
        cog, game, match, handler, teammate = self.build()
        cog.finish_maneuver_resolution = mock.AsyncMock()

        with mock.patch("cogs.d12ball.save_games"):
            await cog.apply_low_pass(
                build_interaction(), game, match, 0, receiver_id=teammate,
            )

        self.assertCarriedBy(match, teammate)

    async def test_a_loose_ball_leaves_nobody_carrying_it(self) -> None:
        """
        A contested ball is nobody's until it is won, and then it is
        won off the space rather than handed over.
        """
        cog, game, match, handler, _ = self.build()
        match.set_ball_carrier(handler)
        cog.resolve_loose_ball = mock.AsyncMock()
        cog.build_loose_ball_view = mock.Mock(return_value=None)
        cog.engine.build_loose_ball_prompt = mock.Mock(return_value="prompt")

        with mock.patch("cogs.d12ball.save_games"):
            await cog.begin_loose_ball(build_interaction(), game, match, 1)

        self.assertIsNone(match.ball_carrier_id)

    async def test_a_new_play_reset_leaves_nobody_carrying_it(self) -> None:
        cog, game, match, handler, _ = self.build()
        match.set_ball_carrier(handler)
        cog.post_new_play_board = mock.AsyncMock()

        with mock.patch("cogs.d12ball.save_games"):
            await cog.announce_new_play_reset(
                build_interaction(), game, match,
            )

        self.assertIsNone(match.ball_carrier_id)


class ContestWinnerTests(unittest.IsolatedAsyncioTestCase):
    """
    A contest is won by a player, not by a team: the winner of a loose
    ball or a long High Pass carries it into the next turn, however the
    contest was settled (author, 2026-08-09). Both run through the same
    machinery, so `is_high_pass` is the only thing that differs.
    """

    def build_contest(
        self, is_high_pass: bool,
    ) -> tuple[D12Ball, D12BallGame, MatchState, str, str]:
        cog = build_cog()
        cog.announce_run_back = mock.AsyncMock()
        cog.finish_maneuver_resolution = mock.AsyncMock()
        cog.begin_substitution_window = mock.AsyncMock()
        cog.begin_run_back = mock.AsyncMock()
        cog.end_period = mock.AsyncMock()
        game = build_game()
        cog.games[game.game_id] = game
        match = cog.engine.initialize_standard_match(game)

        receiver = match.setup_for_side(match.ball.possession).field_players[0]
        challenger = match.setup_for_side(
            match.defending_side()
        ).field_players[0]
        for player_id in (receiver, challenger):
            match.move_meeple(
                player_id, match.ball.zone, match.ball.space_index,
            )

        match.begin_loose_ball(2, is_high_pass=is_high_pass)
        match.choose_loose_ball_offense_player(receiver)
        match.choose_loose_ball_defense_player(challenger)
        game.match_state = match.to_dict()
        return cog, game, match, receiver, challenger

    def rolls_for(
        self, cog: D12Ball, receiver: str, challenger: str, winner: str,
    ) -> list[int]:
        """Dice that make `winner` ("offense"/"defense") take the test."""
        offense_skill = cog.player_catalog.effective_profile(
            cog.engine.get_player_definition(receiver)
        ).offense
        defense_skill = cog.player_catalog.effective_profile(
            cog.engine.get_player_definition(challenger)
        ).defense
        offense_roll = 6
        defense_roll = offense_roll + offense_skill - defense_skill
        self.assertTrue(2 <= defense_roll <= 11)
        if winner == "offense":
            return [offense_roll, defense_roll - 1]
        return [offense_roll, defense_roll + 1]

    async def roll_the_contest(
        self, cog: D12Ball, game: D12BallGame, dice: list[int],
    ) -> MatchState:
        view = LooseBallSkillTestView(cog, game.game_id)
        with mock.patch("cogs.d12ball_views.save_games"), mock.patch(
            "cogs.d12ball.save_games",
        ), mock.patch(
            "cogs.d12ball_views.random.randint", side_effect=dice,
        ), mock.patch(
            "cogs.d12ball_views.render_skill_test_dice",
        ), mock.patch("cogs.d12ball_views.discord.File"):
            await view.roll(build_contest_interaction())
        return cog.engine.load_match_state(game)

    async def test_a_receiver_who_keeps_a_high_pass_carries_it(self) -> None:
        cog, game, _, receiver, challenger = self.build_contest(
            is_high_pass=True,
        )

        saved = await self.roll_the_contest(
            cog, game, self.rolls_for(cog, receiver, challenger, "offense"),
        )

        self.assertEqual(saved.ball_carrier_id, receiver)
        self.assertEqual(saved.turn_handler_candidates(), [receiver])

    async def test_a_challenger_who_takes_a_high_pass_carries_it(
        self,
    ) -> None:
        cog, game, _, receiver, challenger = self.build_contest(
            is_high_pass=True,
        )

        saved = await self.roll_the_contest(
            cog, game, self.rolls_for(cog, receiver, challenger, "defense"),
        )

        self.assertEqual(saved.ball.possession, TeamSide.VISITING)
        self.assertEqual(saved.ball_carrier_id, challenger)
        self.assertEqual(saved.turn_handler_candidates(), [challenger])

    async def test_winning_a_loose_ball_carries_it(self) -> None:
        cog, game, _, receiver, challenger = self.build_contest(
            is_high_pass=False,
        )

        saved = await self.roll_the_contest(
            cog, game, self.rolls_for(cog, receiver, challenger, "defense"),
        )

        self.assertEqual(saved.ball_carrier_id, challenger)

    async def test_an_unopposed_recovery_carries_it(self) -> None:
        """
        Only one side sending anybody skips the roll, but it is still
        how that player came to be holding the ball.
        """
        cog, game, match, receiver, _ = self.build_contest(
            is_high_pass=False,
        )
        match.loose_ball_defense_player = None
        match.decline_loose_ball(match.defending_side())

        with mock.patch("cogs.d12ball.save_games"):
            await cog.resolve_loose_ball(
                build_contest_interaction(), game, match,
            )

        self.assertEqual(match.ball_carrier_id, receiver)
        self.assertEqual(match.turn_handler_candidates(), [receiver])

    async def test_an_unopposed_pick_off_carries_it(self) -> None:
        cog, game, match, _, challenger = self.build_contest(
            is_high_pass=False,
        )
        match.loose_ball_offense_player = None
        match.decline_loose_ball(match.ball.possession)

        with mock.patch("cogs.d12ball.save_games"):
            await cog.resolve_loose_ball(
                build_contest_interaction(), game, match,
            )

        self.assertEqual(match.ball.possession, TeamSide.VISITING)
        self.assertEqual(match.ball_carrier_id, challenger)

    async def test_a_ball_that_went_out_of_bounds_carries_to_nobody(
        self,
    ) -> None:
        """
        The one loose ball that is a new play: nobody contested it, so
        nobody won it, and the pickup afterwards is a placement the
        coach makes rather than a contest anyone came out of.
        """
        cog, game, match, _, _ = self.build_contest(is_high_pass=False)
        match.loose_ball_offense_player = None
        match.loose_ball_defense_player = None
        match.decline_loose_ball(match.ball.possession)
        match.decline_loose_ball(match.defending_side())

        with mock.patch("cogs.d12ball.save_games"):
            await cog.resolve_loose_ball(
                build_contest_interaction(), game, match,
            )

        self.assertTrue(match.pending_ball_recovery)
        self.assertIsNone(match.ball_carrier_id)


class RunBackExemptionTests(unittest.IsolatedAsyncioTestCase):
    """
    The player holding the ball does not run back, whoever they are
    (author, 2026-08-09). begin_run_back reads the exemption off
    ball_carrier_id rather than taking it as an argument, because the
    two are one fact -- running the ball's holder back would move them
    off the ball and charge them for it.
    """

    def build(self) -> tuple[D12Ball, D12BallGame, MatchState]:
        cog = build_cog()
        cog.announce_run_back = mock.AsyncMock()
        cog.announce_new_play_reset = mock.AsyncMock()
        cog.begin_substitution_window = mock.AsyncMock()
        cog.finish_maneuver_resolution = mock.AsyncMock()
        cog.end_period = mock.AsyncMock()
        game = build_game()
        cog.games[game.game_id] = game
        match = cog.engine.initialize_standard_match(game)
        return cog, game, match

    def displaced_winner(self, cog: D12Ball, match: MatchState) -> str:
        """
        A contestant sent after a ball outside their own zone, who then
        wins it: standing in midfield, assigned to the visitors' goal.
        Before the exemption generalised, the run back moved them.
        """
        setup = match.visiting
        winner = next(
            player_id
            for player_id in setup.field_players
            if setup.assigned_zone(player_id) == Zone.VISITORS_GOAL
        )
        match.board.remove_meeple(winner)
        match.board.place_meeple(winner, Zone.MIDFIELD, 1)
        match.ball.possession = TeamSide.VISITING
        match.set_ball_space(Zone.MIDFIELD, 1)
        return winner

    async def test_a_contest_winner_is_not_run_back_off_the_ball(
        self,
    ) -> None:
        cog, game, match = self.build()
        winner = self.displaced_winner(cog, match)
        match.set_ball_carrier(winner)

        with mock.patch("cogs.d12ball.save_games"):
            await cog.begin_run_back(build_interaction(), game, match)

        self.assertEqual(match.pending_run_back_stays_player_id, winner)
        self.assertNotIn(
            winner, cog.engine.run_back_displaced(match, TeamSide.VISITING),
        )

    async def test_the_same_player_is_run_back_without_the_ball(
        self,
    ) -> None:
        """
        The other half: the exemption is the ball, not the player. The
        identical position with nobody carrying it still runs back.
        """
        cog, game, match = self.build()
        winner = self.displaced_winner(cog, match)

        with mock.patch("cogs.d12ball.save_games"):
            await cog.begin_run_back(build_interaction(), game, match)

        self.assertIsNone(match.pending_run_back_stays_player_id)
        self.assertIn(
            winner, cog.engine.run_back_displaced(match, TeamSide.VISITING),
        )

    async def test_a_new_play_exempts_nobody(self) -> None:
        """
        A goal scored off a High Pass set-up leaves the receiver still
        recorded as carrying it. They are not -- the ball went dead,
        and the reset moves both sides whatever they were doing.
        """
        cog, game, match = self.build()
        shooter = self.displaced_winner(cog, match)
        match.set_ball_carrier(shooter)

        with mock.patch("cogs.d12ball.save_games"):
            await cog.begin_run_back(
                build_interaction(), game, match, new_play=True,
            )

        self.assertIsNone(match.ball_carrier_id)
        self.assertIsNone(match.pending_run_back_stays_player_id)

    def test_substituting_the_carrier_moves_the_carry_with_it(self) -> None:
        """
        The exemption already followed the position rather than the
        player; the carry has to travel with it, or the replacement is
        exempt from running back while the carry points at somebody no
        longer on the field.
        """
        cog, game, match = self.build()
        carrier = self.displaced_winner(cog, match)
        replacement = match.visiting.team_board.bench[0]
        match.set_ball_carrier(carrier)
        match.pending_run_back_stays_player_id = carrier

        match.inherit_run_back_exemption(carrier, replacement)

        self.assertEqual(match.ball_carrier_id, replacement)
        self.assertEqual(
            match.pending_run_back_stays_player_id, replacement,
        )

    def test_trading_the_carrier_s_meeple_moves_the_carry_with_it(
        self,
    ) -> None:
        """
        swap_meeple_positions, not swap_field_positions: trading two
        meeples moves whoever is standing on the ball, so the carry
        goes with the space. Exchanging zone *assignments* leaves both
        meeples where they are, so it leaves the carry alone too.
        """
        cog, game, match = self.build()
        carrier = self.displaced_winner(cog, match)
        other = next(
            player_id
            for player_id in match.visiting.field_players
            if player_id != carrier
        )
        match.set_ball_carrier(carrier)
        match.pending_run_back_stays_player_id = carrier

        match.swap_meeple_positions(TeamSide.VISITING, carrier, other)

        self.assertEqual(match.ball_carrier_id, other)
        self.assertEqual(match.pending_run_back_stays_player_id, other)

    def test_reassigning_zones_leaves_the_carry_where_it_is(self) -> None:
        """
        A zone swap moves cards, not meeples -- the player standing on
        the ball is still standing on it.
        """
        cog, game, match = self.build()
        carrier = self.displaced_winner(cog, match)
        other = next(
            player_id
            for player_id in match.visiting.field_players
            if match.visiting.assigned_zone(player_id)
            != match.visiting.assigned_zone(carrier)
        )
        match.set_ball_carrier(carrier)

        match.swap_field_positions(TeamSide.VISITING, carrier, other)

        self.assertEqual(match.ball_carrier_id, carrier)


if __name__ == "__main__":
    unittest.main()
