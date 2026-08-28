"""
The Coaching Choice: the four actions it offers at the model layer --
substitution, zone assignment, space positioning, and the whole-side
deployment a formation change is made of -- and the pre-kickoff
sequence that puts one to each coach before the game starts.

Halftime's own sequence is in test_d12ball_halftime, and the flow's
views in test_d12ball_formations. See "Coaching Choice" in
docs/living-rules.md.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

from cogs.d12ball import SETUP_STAGES, D12Ball
from cogs.d12ball_views import CoachingHubView
from d12ball.ai import build_ai_strategies
from d12ball.engine import RulesEngine
from d12ball.components import (
    CoachingOccasion,
    MatchState,
    TeamSide,
    Zone,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.game import AIOpponent, D12BallGame, Formation, GameStatus, Team
from view_patches import suppressed_view_saves


def build_cog() -> D12Ball:
    cog = object.__new__(D12Ball)
    cog.games = {}
    cog.player_catalog = load_player_catalog()
    cog.maneuver_catalog = load_maneuver_catalog()
    cog.basic_ruleset = load_basic_ruleset()
    cog.team_emojis = {}
    cog.condition_emojis = {}
    cog.ai_strategies = build_ai_strategies(
        cog.player_catalog, cog.maneuver_catalog,
    )
    cog.engine = RulesEngine(
        cog.player_catalog, cog.basic_ruleset, cog.maneuver_catalog,
        cog.ai_strategies,
    )
    cog.refresh_match_image = mock.AsyncMock()
    cog.post_new_play_board = mock.AsyncMock()
    cog.send_turn_prompt = mock.AsyncMock()
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
        player_1_team=Team.ORANGE,
        player_2_team=Team.PURPLE,
        home_player_number=1,
        visiting_player_number=2,
        status=GameStatus.IN_PROGRESS,
    )
    fields.update(overrides)
    return D12BallGame(**fields)


def build_interaction() -> SimpleNamespace:
    return SimpleNamespace(
        followup=SimpleNamespace(
            send=mock.AsyncMock(return_value=SimpleNamespace(id=999)),
        ),
    )


def build_click(user_id: int = 111) -> SimpleNamespace:
    """An interaction a view can answer, for the flow's own buttons."""
    return SimpleNamespace(
        user=SimpleNamespace(id=user_id, display_name="One"),
        response=SimpleNamespace(
            edit_message=mock.AsyncMock(),
            send_message=mock.AsyncMock(),
        ),
        followup=SimpleNamespace(send=mock.AsyncMock()),
    )


class CoachingModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    def build_match(
        self,
        board_size: int = 7,
        home_formation: Formation = Formation.TWO_TWO_TWO,
    ) -> MatchState:
        return MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=board_size,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
            home_formation=home_formation,
        )

    # -- Substitution --------------------------------------------------

    def test_setup_sends_an_outgoing_player_back_to_the_bench(self) -> None:
        match = self.build_match()
        outgoing = match.home.field_players[0]
        incoming = match.home.team_board.bench[0]

        match.substitute(
            TeamSide.HOME, outgoing, incoming, retire_outgoing=False,
        )

        self.assertIn(outgoing, match.home.team_board.bench)
        self.assertEqual(match.home.team_board.back_bench, [])
        # And so they can come straight back on, which is the whole
        # point of setup's exception.
        self.assertIn(outgoing, match.substitution_pool(TeamSide.HOME))

    def test_every_other_occasion_retires_them(self) -> None:
        match = self.build_match()
        outgoing = match.home.field_players[0]
        incoming = match.home.team_board.bench[0]

        match.substitute(TeamSide.HOME, outgoing, incoming)

        self.assertIn(outgoing, match.home.team_board.back_bench)
        self.assertNotIn(outgoing, match.home.team_board.bench)

    def test_the_occasion_decides_which_way(self) -> None:
        self.assertFalse(
            CoachingOccasion.SETUP.retires_outgoing_players,
        )
        for occasion in (
            CoachingOccasion.NEW_PLAY,
            CoachingOccasion.HALFTIME,
        ):
            self.assertTrue(occasion.retires_outgoing_players)

    # -- Zone assignment -----------------------------------------------

    def test_exchanging_two_players_moves_their_meeples_too(self) -> None:
        match = self.build_match()
        setup = match.home
        first = setup.zones[Zone.HOME_GOAL][0]
        second = setup.zones[Zone.VISITORS_GOAL][0]
        first_position = match.board.meeple_position(first)
        second_position = match.board.meeple_position(second)

        match.exchange_field_players(TeamSide.HOME, first, second)

        self.assertEqual(setup.assigned_zone(first), Zone.VISITORS_GOAL)
        self.assertEqual(setup.assigned_zone(second), Zone.HOME_GOAL)
        self.assertEqual(
            match.board.meeple_position(first), second_position,
        )
        self.assertEqual(
            match.board.meeple_position(second), first_position,
        )

    def test_an_exchange_leaves_nobody_outside_their_own_zone(self) -> None:
        match = self.build_match()
        setup = match.home
        first = setup.zones[Zone.MIDFIELD][0]
        second = setup.zones[Zone.HOME_GOAL][1]

        match.exchange_field_players(TeamSide.HOME, first, second)

        for player_id in setup.field_players:
            position = match.board.meeple_position(player_id)
            self.assertEqual(position[0], setup.assigned_zone(player_id))

    # -- Space positioning ---------------------------------------------

    def test_moving_to_an_empty_space_is_an_ordinary_move(self) -> None:
        # Board 9's three-space zones hold two cards under 2-2-2, and
        # the deal spreads them to the ends, so the middle space is
        # always free to step onto.
        match = self.build_match(board_size=9)
        player_id = match.home.zones[Zone.HOME_GOAL][0]

        self.assertEqual(
            match.positioning_swap_candidates(TeamSide.HOME, player_id, 1),
            [],
        )
        partner = match.position_meeple(TeamSide.HOME, player_id, 1)

        self.assertIsNone(partner)
        self.assertEqual(
            match.board.meeple_position(player_id), (Zone.HOME_GOAL, 1),
        )

    def test_a_sole_occupant_moving_onto_a_teammate_trades(self) -> None:
        match = self.build_match()
        first, second = match.home.zones[Zone.HOME_GOAL]
        first_position = match.board.meeple_position(first)
        second_position = match.board.meeple_position(second)

        partner = match.position_meeple(
            TeamSide.HOME, first, second_position[1],
        )

        self.assertEqual(partner, second)
        self.assertEqual(
            match.board.meeple_position(first), second_position,
        )
        self.assertEqual(
            match.board.meeple_position(second), first_position,
        )

    def test_leaving_a_teammate_behind_stacks_instead_of_trading(
        self,
    ) -> None:
        # Board 6 under 2-3-1 puts two of the three midfielders on one
        # space. Either of them can step across onto the third without
        # trading, because the space they leave stays covered.
        match = self.build_match(
            board_size=6, home_formation=Formation.TWO_THREE_ONE,
        )
        stacked = [
            occupants
            for occupants in match.board.spaces[Zone.MIDFIELD]
            if len(
                [
                    player_id
                    for player_id in occupants
                    if player_id in set(match.home.field_players)
                ]
            )
            > 1
        ]
        self.assertTrue(stacked, "expected 2-3-1 on board 6 to stack")
        mover = [
            player_id
            for player_id in stacked[0]
            if player_id in set(match.home.field_players)
        ][0]
        origin = match.board.meeple_position(mover)
        target = 1 - origin[1]

        self.assertEqual(
            match.positioning_swap_candidates(TeamSide.HOME, mover, target),
            [],
        )
        partner = match.position_meeple(TeamSide.HOME, mover, target)

        self.assertIsNone(partner)
        self.assertEqual(
            match.board.meeple_position(mover), (Zone.MIDFIELD, target),
        )

    def test_more_than_one_on_the_target_has_to_be_picked_between(
        self,
    ) -> None:
        match = self.build_match(
            board_size=6, home_formation=Formation.TWO_THREE_ONE,
        )
        # Pile all three midfielders onto M1, then bring the odd one
        # out back: the trade is now ambiguous.
        midfielders = list(match.home.zones[Zone.MIDFIELD])
        for player_id in midfielders:
            match.board.place_meeple(player_id, Zone.MIDFIELD, 0)
        loner = midfielders[0]
        match.board.place_meeple(loner, Zone.MIDFIELD, 1)

        candidates = match.positioning_swap_candidates(
            TeamSide.HOME, loner, 0,
        )
        self.assertEqual(sorted(candidates), sorted(midfielders[1:]))

        with self.assertRaises(ValueError):
            match.position_meeple(TeamSide.HOME, loner, 0)

        partner = match.position_meeple(
            TeamSide.HOME, loner, 0, swap_with=midfielders[2],
        )
        self.assertEqual(partner, midfielders[2])
        self.assertEqual(
            match.board.meeple_position(midfielders[2]),
            (Zone.MIDFIELD, 1),
        )

    def test_an_opponent_on_the_space_is_not_traded_with(self) -> None:
        # Occupancy is per team and opposing meeples share spaces
        # freely, so a space holding only an opponent is an ordinary
        # empty one as far as this side is concerned.
        match = self.build_match(board_size=9)
        player_id = match.home.zones[Zone.MIDFIELD][0]
        opponent = match.visiting.zones[Zone.MIDFIELD][0]
        match.board.place_meeple(opponent, Zone.MIDFIELD, 2)

        self.assertEqual(
            match.positioning_swap_candidates(TeamSide.HOME, player_id, 2),
            [],
        )
        self.assertIsNone(
            match.position_meeple(TeamSide.HOME, player_id, 2),
        )
        self.assertEqual(
            match.board.meeple_position(opponent), (Zone.MIDFIELD, 2),
        )

    def test_positioning_refuses_a_space_outside_the_assigned_zone(
        self,
    ) -> None:
        match = self.build_match()
        player_id = match.home.zones[Zone.HOME_GOAL][0]

        # Home goal has two spaces on board 7, so index 2 is not one.
        with self.assertRaises(ValueError):
            match.position_meeple(TeamSide.HOME, player_id, 2)

    # -- Whole-side deployment -----------------------------------------

    def test_deploying_a_side_sets_zones_and_spaces_together(self) -> None:
        match = self.build_match()
        players = list(match.home.field_players)
        placement = [
            (players[0], Zone.HOME_GOAL, 0),
            (players[1], Zone.HOME_GOAL, 1),
            (players[2], Zone.MIDFIELD, 0),
            (players[3], Zone.MIDFIELD, 1),
            (players[4], Zone.MIDFIELD, 2),
            (players[5], Zone.VISITORS_GOAL, 0),
        ]

        match.deploy_side(TeamSide.HOME, placement)

        self.assertEqual(len(match.home.zones[Zone.MIDFIELD]), 3)
        self.assertEqual(len(match.home.zones[Zone.VISITORS_GOAL]), 1)
        for player_id, zone, space_index in placement:
            self.assertEqual(
                match.home.assigned_zone(player_id), zone,
            )
            self.assertEqual(
                match.board.meeple_position(player_id), (zone, space_index),
            )

    def test_a_deployment_has_to_name_exactly_the_fielded_six(self) -> None:
        match = self.build_match()
        players = list(match.home.field_players)

        with self.assertRaises(ValueError):
            match.deploy_side(
                TeamSide.HOME,
                [(players[0], Zone.HOME_GOAL, 0)],
            )

        with self.assertRaises(ValueError):
            match.deploy_side(
                TeamSide.HOME,
                [(players[0], Zone.HOME_GOAL, index) for index in range(6)],
            )


class SetupCoachingTests(unittest.IsolatedAsyncioTestCase):
    """
    Both coaches get a Coaching Choice before kickoff, home first --
    see "Setting up a game" in docs/living-rules.md. It is the same
    flow as any other, with setup's own allowance.
    """

    def build(self, **game_overrides):
        cog = build_cog()
        game = build_game(**game_overrides)
        cog.games[game.game_id] = game
        match = cog.engine.initialize_standard_match(game)
        game.match_state = match.to_dict()
        return cog, game, match

    async def test_home_is_offered_the_first_window(self) -> None:
        cog, game, _ = self.build()
        interaction = build_interaction()

        with mock.patch("cogs.d12ball.save_games"):
            await cog.begin_setup_coaching(interaction, game)

        match = cog.engine.load_match_state(game)
        self.assertEqual(match.pending_setup_stage, SETUP_STAGES[0])
        self.assertEqual(match.pending_coaching_side, "home")
        self.assertEqual(
            match.coaching_occasion, CoachingOccasion.SETUP,
        )
        # Given rather than declared, so the hub comes straight up and
        # nothing is charged for it.
        self.assertTrue(match.pending_coaching_declared)
        self.assertEqual(match.declared_substitution, set())
        _, kwargs = interaction.followup.send.await_args
        self.assertIsInstance(kwargs["view"], CoachingHubView)
        cog.send_turn_prompt.assert_not_awaited()

    async def test_the_visitors_follow_and_then_play_starts(self) -> None:
        cog, game, _ = self.build()

        with mock.patch("cogs.d12ball.save_games"):
            await cog.begin_setup_coaching(build_interaction(), game)

            match = cog.engine.load_match_state(game)
            await cog.finish_substitution_window(
                build_interaction(), game, match,
            )
            self.assertEqual(match.pending_setup_stage, "coaching_visiting")
            self.assertEqual(match.pending_coaching_side, "visiting")
            cog.send_turn_prompt.assert_not_awaited()

            await cog.finish_substitution_window(
                build_interaction(), game, match,
            )

        self.assertIsNone(match.pending_setup_stage)
        self.assertIsNone(match.pending_coaching_side)
        cog.send_turn_prompt.assert_awaited_once()

    async def test_the_board_waits_for_both_coaches(self) -> None:
        # Nothing has been played, so a board posted before the windows
        # shows a deal neither coach has finished with. The kickoff
        # board is the line-up the game actually starts from, which is
        # not known until the second coach is done -- and it goes up as
        # its own message, under the coaching, the way every other new
        # play's board does.
        cog, game, _ = self.build()

        with mock.patch("cogs.d12ball.save_games"):
            await cog.begin_setup_coaching(build_interaction(), game)
            match = cog.engine.load_match_state(game)
            await cog.finish_substitution_window(
                build_interaction(), game, match,
            )
            cog.refresh_match_image.assert_not_awaited()
            cog.post_new_play_board.assert_not_awaited()

            await cog.finish_substitution_window(
                build_interaction(), game, match,
            )

        cog.refresh_match_image.assert_not_awaited()
        cog.post_new_play_board.assert_awaited_once()

    async def test_a_setup_substitution_is_unlimited_and_reversible(
        self,
    ) -> None:
        cog, game, _ = self.build()

        with mock.patch("cogs.d12ball.save_games"):
            await cog.begin_setup_coaching(build_interaction(), game)
        match = cog.engine.load_match_state(game)

        self.assertIsNone(match.substitutions_remaining())
        self.assertEqual(cog.engine.substitution_button_label(match), "no limit")

        outgoing = match.home.field_players[0]
        incoming = match.home.team_board.bench[0]
        cog.apply_substitution(match, TeamSide.HOME, outgoing, incoming)

        # Straight back to the bench, so they can be brought on again,
        # and the half's own two are untouched.
        self.assertIn(outgoing, match.home.team_board.bench)
        self.assertEqual(match.home.team_board.back_bench, [])
        self.assertEqual(match.half_substitutions_used, {})
        self.assertIsNone(match.substitutions_remaining())

    def test_home_has_to_cover_the_kickoff_space(self) -> None:
        cog, _, match = self.build()
        match.open_coaching_window(TeamSide.HOME, CoachingOccasion.SETUP)

        # The standard deal already covers it, so nothing holds them.
        self.assertIsNone(
            cog.engine.coaching_finish_refusal(match, TeamSide.HOME),
        )
        # The visitors do not kick off the first half, so they are
        # never held here whatever they do.
        self.assertIsNone(
            cog.engine.coaching_finish_refusal(match, TeamSide.VISITING),
        )

        for player_id in list(
            match.board.spaces[match.ball.zone][match.ball.space_index]
        ):
            if player_id in match.home.field_players:
                match.board.place_meeple(
                    player_id, match.ball.zone, 0
                    if match.ball.space_index else 1,
                )

        self.assertIsNotNone(
            cog.engine.coaching_finish_refusal(match, TeamSide.HOME),
        )

    async def test_an_ai_side_passes_through_without_a_message(
        self,
    ) -> None:
        # Dinky only substitutes to get an injured player off, and
        # nobody is injured before kickoff. Its lead-in is instructions
        # for a coach, so an AI that changed nothing says nothing.
        cog, game, _ = self.build(
            player_2_id=None, ai_opponent=AIOpponent.DINKY,
        )
        interaction = build_interaction()

        with mock.patch("cogs.d12ball.save_games"):
            await cog.begin_setup_coaching(interaction, game)
            match = cog.engine.load_match_state(game)
            await cog.finish_substitution_window(interaction, game, match)

        self.assertIsNone(match.pending_setup_stage)
        cog.send_turn_prompt.assert_awaited_once()

        # One "Before kickoff" message, the human coach's. The AI's
        # window posts nothing at all.
        posted = [
            call.args[0]
            for call in interaction.followup.send.await_args_list
            if call.args
        ]
        self.assertEqual(
            len([text for text in posted if "Before kickoff" in text]), 1,
        )


class CoachingSummaryTests(unittest.IsolatedAsyncioTestCase):
    """
    What a window says when it closes. The whole flow lives on one
    message, so every note a step leaves is written over by the next
    one -- "so-and-so comes on for so-and-so" most of all. The Done
    message is the only place those survive.
    """

    def build(self):
        cog = build_cog()
        game = build_game()
        cog.games[game.game_id] = game
        match = cog.engine.initialize_standard_match(game)
        match.open_coaching_window(
            TeamSide.HOME,
            CoachingOccasion.NEW_PLAY,
            formation=Formation.TWO_TWO_TWO.value,
        )
        match.declare_coaching()
        game.match_state = match.to_dict()
        return cog, game, match

    def test_a_window_that_changed_nothing_has_nothing_to_report(
        self,
    ) -> None:
        cog, _, match = self.build()

        self.assertEqual(cog.coaching_summary(match, TeamSide.HOME), [])

    def test_the_shape_is_reported_as_the_change_it_was(self) -> None:
        cog, _, match = self.build()

        cog.engine.apply_formation(match, TeamSide.HOME, Formation.TWO_THREE_ONE)

        self.assertEqual(
            cog.coaching_summary(match, TeamSide.HOME),
            ["Formation: **2-2-2 → 2-3-1**."],
        )

    def test_a_shape_changed_and_changed_back_is_not_a_change(
        self,
    ) -> None:
        # The summary is what the window did, not what it passed
        # through: it is read against the shape the side opened in.
        cog, _, match = self.build()

        cog.engine.apply_formation(match, TeamSide.HOME, Formation.TWO_THREE_ONE)
        cog.engine.apply_formation(match, TeamSide.HOME, Formation.TWO_TWO_TWO)

        self.assertEqual(cog.coaching_summary(match, TeamSide.HOME), [])

    def test_every_swap_is_named(self) -> None:
        cog, _, match = self.build()
        first_off = match.home.field_players[0]
        first_on = match.home.team_board.bench[0]
        cog.apply_substitution(match, TeamSide.HOME, first_off, first_on)
        second_off = match.home.field_players[1]
        second_on = match.home.team_board.bench[0]
        cog.apply_substitution(match, TeamSide.HOME, second_off, second_on)

        summary = cog.coaching_summary(match, TeamSide.HOME)

        self.assertEqual(len(summary), 2)
        for player_id, line in (
            (first_on, summary[0]),
            (second_on, summary[1]),
        ):
            self.assertIn(
                cog.engine.get_player_definition(player_id).name, line,
            )
        self.assertIn(
            cog.engine.get_player_definition(first_off).name, summary[0],
        )

    async def test_done_puts_the_summary_where_it_survives(self) -> None:
        cog, game, match = self.build()
        cog.finish_substitution_window = mock.AsyncMock()
        outgoing = match.home.field_players[0]
        incoming = match.home.team_board.bench[0]
        cog.apply_substitution(match, TeamSide.HOME, outgoing, incoming)
        game.match_state = match.to_dict()

        click = build_click()
        with suppressed_view_saves():
            await CoachingHubView(cog, game.game_id).finish(click)

        content = click.response.edit_message.await_args.kwargs["content"]
        self.assertIn("are done.", content)
        self.assertIn(
            cog.engine.get_player_definition(incoming).name, content,
        )
        self.assertIn(
            cog.engine.get_player_definition(outgoing).name, content,
        )
        cog.finish_substitution_window.assert_awaited_once()

    async def test_a_window_used_for_nothing_says_so(self) -> None:
        cog, game, _ = self.build()
        cog.finish_substitution_window = mock.AsyncMock()

        click = build_click()
        with suppressed_view_saves():
            await CoachingHubView(cog, game.game_id).finish(click)

        self.assertIn(
            "No substitutions",
            click.response.edit_message.await_args.kwargs["content"],
        )

    def test_the_record_survives_a_save_and_reload(self) -> None:
        # A restart mid-window resumes the same Coaching Choice, so it
        # has to close with what the coach did before the restart.
        cog, _, match = self.build()
        cog.engine.apply_formation(match, TeamSide.HOME, Formation.TWO_THREE_ONE)
        outgoing = match.home.field_players[0]
        incoming = match.home.team_board.bench[0]
        cog.apply_substitution(match, TeamSide.HOME, outgoing, incoming)

        reloaded = MatchState.from_dict(
            match.to_dict(), load_basic_ruleset(),
        )

        self.assertEqual(
            cog.coaching_summary(reloaded, TeamSide.HOME),
            cog.coaching_summary(match, TeamSide.HOME),
        )


if __name__ == "__main__":
    unittest.main()
