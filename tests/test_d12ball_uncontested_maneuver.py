"""
A maneuver with nobody to challenge it.

"With no challenger -- nobody in the zone, or nobody sent -- offense
chooses and resolves a maneuver with no reveal or test"
(docs/living-rules.md, "Maneuvers"). The offense still picks which
maneuver succeeds, so the turn keeps its shape -- a pick, then an
effect -- and only loses the half of it that needed a second player:
the challenger, the reveal, and the skill test a tie would have run.

Two ways in, and one state: the defense has nobody in the ball's zone,
or it has somebody and sends nobody rather than pay the walk-in's
exhaustion. `DeclinedChallengeTests` covers the second, which is the
author's 2026-08-12 ruling; the one challenge it does not reach is a
defender already standing on the ball, who pays nothing and so has
nothing to decline.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

from cogs.d12ball import D12Ball
from cogs.d12ball_views import (
    ManeuverActionPromptView,
    ManeuverActionSelectView,
    ManeuverChallengeView,
    PlayerActionView,
)
from d12ball.ai import build_ai_strategies
from d12ball.components import (
    MatchState,
    TeamSide,
    Zone,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.game import AIOpponent, D12BallGame, GameStatus, Team


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
    cog.refresh_match_image = mock.AsyncMock()
    cog.drop_turn_prompt = mock.AsyncMock()
    cog.begin_effect_resolution = mock.AsyncMock()
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


def build_interaction(user_id: int = 111) -> SimpleNamespace:
    sent = SimpleNamespace(id=999)
    prompt_message = SimpleNamespace(
        edit=mock.AsyncMock(), delete=mock.AsyncMock(),
    )
    return SimpleNamespace(
        user=SimpleNamespace(id=user_id, display_name="One"),
        channel=SimpleNamespace(
            get_partial_message=mock.Mock(return_value=prompt_message),
        ),
        response=SimpleNamespace(
            defer=mock.AsyncMock(),
            edit_message=mock.AsyncMock(),
            send_message=mock.AsyncMock(),
        ),
        followup=SimpleNamespace(send=mock.AsyncMock(return_value=sent)),
        delete_original_response=mock.AsyncMock(),
    )


class UncontestedManeuverTests(unittest.IsolatedAsyncioTestCase):
    def build(self, **game_overrides) -> tuple[D12Ball, D12BallGame, MatchState]:
        """
        Home in possession in midfield, with every visiting meeple
        cleared out of that zone so there is nobody to challenge with.
        """
        cog = build_cog()
        game = build_game(**game_overrides)
        cog.games[game.game_id] = game
        match = cog.initialize_standard_match(game)

        for player_id in match.visiting.field_players:
            zone, _ = match.board.meeple_position(player_id)
            if zone == Zone.MIDFIELD:
                match.board.remove_meeple(player_id)
                match.board.place_meeple(player_id, Zone.VISITORS_GOAL, 0)

        handler = next(
            player_id
            for player_id in match.home.field_players
            if match.board.meeple_position(player_id)[0] == Zone.MIDFIELD
        )
        match.ball.possession = TeamSide.HOME
        match.set_ball_space(*match.board.meeple_position(handler))
        match.active_player_id = handler
        game.match_state = match.to_dict()

        self.assertEqual(match.eligible_challengers(), [])
        return cog, game, match

    async def choose_to_maneuver(self, cog, game, interaction) -> None:
        with mock.patch("cogs.d12ball_views.save_games"), \
                mock.patch("cogs.d12ball.save_games"):
            await PlayerActionView(cog, game.game_id).choose_action(
                interaction, "maneuver", "maneuver",
            )

    async def test_maneuvering_unchallenged_goes_straight_to_the_pick(
        self,
    ) -> None:
        cog, game, _ = self.build()
        interaction = build_interaction()

        await self.choose_to_maneuver(cog, game, interaction)

        match = cog.load_match_state(game)
        self.assertTrue(match.maneuver_uncontested)
        self.assertIsNone(match.challenger_id)
        # The old behaviour was an ephemeral refusal that left the turn
        # exactly where it was.
        interaction.response.send_message.assert_not_awaited()

    async def test_the_prompt_waits_on_the_offense_alone(self) -> None:
        cog, game, _ = self.build()
        interaction = build_interaction()

        await self.choose_to_maneuver(cog, game, interaction)

        prompt = interaction.followup.send.await_args_list[-1]
        self.assertNotIn("both sides", prompt.args[0])
        self.assertIsInstance(
            prompt.kwargs["view"], ManeuverActionPromptView,
        )

    async def test_the_offense_s_pick_succeeds_outright(self) -> None:
        cog, game, _ = self.build()
        await self.choose_to_maneuver(cog, game, build_interaction())

        with mock.patch("cogs.d12ball_views.save_games"), \
                mock.patch("cogs.d12ball.save_games"):
            await ManeuverActionSelectView(
                cog, game.game_id, "offense",
            ).pick(build_interaction(), "Dribble Advance")

        self.assertEqual(
            cog.begin_effect_resolution.await_args.args[-1],
            "Dribble Advance",
        )

    async def test_no_skill_test_can_be_reached_without_a_challenger(
        self,
    ) -> None:
        cog, game, _ = self.build()
        await self.choose_to_maneuver(cog, game, build_interaction())

        with mock.patch("cogs.d12ball_views.save_games"), \
                mock.patch("cogs.d12ball.save_games"):
            await ManeuverActionSelectView(
                cog, game.game_id, "offense",
            ).pick(build_interaction(), "Low Pass")

        # Low Pass ties Block Deflect, which is what the defense would
        # have had to pick for a tie -- there is no defense, so the
        # effect runs and nobody rolls.
        cog.begin_effect_resolution.assert_awaited_once()
        match = cog.load_match_state(game)
        self.assertIsNone(match.defense_maneuver)

    async def test_the_defense_is_told_there_is_nothing_to_pick(
        self,
    ) -> None:
        cog, game, _ = self.build()
        await self.choose_to_maneuver(cog, game, build_interaction())

        interaction = build_interaction(user_id=222)
        await ManeuverActionPromptView(
            cog, game.game_id,
        ).open_action_menu(interaction)

        message = interaction.response.send_message.await_args.args[0]
        self.assertIn("nobody in the ball's zone", message)

    async def test_the_ai_maneuvers_unchallenged_too(self) -> None:
        cog, game, match = self.build(
            player_2_id=None, ai_opponent=AIOpponent.DINKY,
        )
        # The AI plays the visiting side, so flip who is unchallenged.
        match.ball.possession = TeamSide.VISITING
        handler = next(
            player_id
            for player_id in match.visiting.field_players
            if match.board.meeple_position(player_id)[0] == Zone.VISITORS_GOAL
        )
        for player_id in match.home.field_players:
            zone, _ = match.board.meeple_position(player_id)
            if zone == Zone.VISITORS_GOAL:
                match.board.remove_meeple(player_id)
                match.board.place_meeple(player_id, Zone.HOME_GOAL, 0)
        match.set_ball_space(*match.board.meeple_position(handler))
        game.match_state = match.to_dict()

        with mock.patch("cogs.d12ball.save_games"):
            await cog.play_ai_turn(build_interaction(), game, match)

        self.assertTrue(match.maneuver_uncontested)
        self.assertIsNotNone(match.offense_maneuver)
        cog.begin_effect_resolution.assert_awaited_once()

    def test_the_flag_survives_a_save_and_reload(self) -> None:
        cog, _, match = self.build()
        match.begin_uncontested_maneuver()
        match.choose_offense_maneuver("High Pass")

        reloaded = MatchState.from_dict(match.to_dict(), cog.basic_ruleset)

        self.assertTrue(reloaded.maneuver_uncontested)
        self.assertTrue(reloaded.maneuver_selections_complete)

    def test_a_mid_effect_save_still_validates(self) -> None:
        # With a challenger it is the challenger_id/defense_maneuver
        # pair that tells validate() an effect is in flight and the
        # handler is allowed to be off the ball. Uncontested has
        # neither, so the flag has to stand in for both -- otherwise a
        # pass saved mid-effect will not load again.
        cog, _, match = self.build()
        match.begin_uncontested_maneuver()
        match.choose_offense_maneuver("High Pass")
        zone, space_index = match.board.meeple_position(
            match.active_player_id,
        )
        match.set_ball_space(zone, space_index + 1)

        MatchState.from_dict(
            match.to_dict(), cog.basic_ruleset,
        ).validate(cog.player_catalog)

    def test_a_reset_clears_it(self) -> None:
        _, _, match = self.build()
        match.begin_uncontested_maneuver()

        match.reset_maneuver()

        self.assertFalse(match.maneuver_uncontested)

    def test_it_refuses_to_start_with_a_defender_on_the_ball(self) -> None:
        # The one challenge that costs the defense nothing, and so the
        # one that cannot be waved through.
        cog = build_cog()
        game = build_game()
        cog.games[game.game_id] = game
        match = cog.initialize_standard_match(game)
        match.active_player_id = match.home.field_players[0]
        defender = match.eligible_challengers()[0]
        match.board.place_meeple(
            defender, match.ball.zone, match.ball.space_index,
        )

        with self.assertRaises(ValueError):
            match.begin_uncontested_maneuver()

    def test_the_restored_view_is_the_offense_s_effect_choice(self) -> None:
        cog, game, match = self.build()
        match.begin_uncontested_maneuver()
        match.choose_offense_maneuver("High Pass")

        view = cog.build_effect_choice_view(game.game_id, match)

        self.assertIsNotNone(view)


class DeclinedChallengeTests(unittest.IsolatedAsyncioTestCase):
    """
    The defense has somebody in the ball's zone and keeps them where
    they are. The walk-in costs 1 token per space, and since
    2026-08-12 paying it is a choice -- so this ends in the same state
    as having nobody to send, reached by a button instead.
    """

    def build(self, **game_overrides) -> tuple[D12Ball, D12BallGame, MatchState]:
        """
        Home in possession in midfield, with the visiting midfielders
        standing off the ball rather than on it.
        """
        cog = build_cog()
        game = build_game(**game_overrides)
        cog.games[game.game_id] = game
        match = cog.initialize_standard_match(game)

        handler = next(
            player_id
            for player_id in match.home.field_players
            if match.board.meeple_position(player_id)[0] == Zone.MIDFIELD
        )
        match.ball.possession = TeamSide.HOME
        match.set_ball_space(*match.board.meeple_position(handler))
        match.active_player_id = handler
        match.pending_action = "maneuver"

        # Anyone sharing the ball's space would challenge for free and
        # never reach the prompt, so clear the space of visitors.
        elsewhere = 0 if match.ball.space_index else 1
        for player_id in match.visiting.field_players:
            zone, space_index = match.board.meeple_position(player_id)
            if (zone, space_index) == (
                match.ball.zone, match.ball.space_index,
            ):
                match.board.place_meeple(player_id, zone, elsewhere)

        game.match_state = match.to_dict()

        self.assertTrue(match.eligible_challengers())
        self.assertEqual(match.automatic_challengers(), [])
        self.assertTrue(match.may_decline_challenge())
        return cog, game, match

    async def decline(self, cog, game, user_id: int = 222):
        interaction = build_interaction(user_id=user_id)
        with mock.patch("cogs.d12ball_views.save_games"), \
                mock.patch("cogs.d12ball.save_games"):
            await ManeuverChallengeView(cog, game.game_id).decline(interaction)
        return interaction

    def test_the_prompt_offers_sending_nobody(self) -> None:
        cog, game, _ = self.build()

        view = ManeuverChallengeView(cog, game.game_id)

        self.assertIn(
            f"d12ball:challenge_decline:{game.game_id}",
            [item.custom_id for item in view.children],
        )

    async def test_sending_nobody_leaves_the_maneuver_uncontested(
        self,
    ) -> None:
        cog, game, _ = self.build()

        await self.decline(cog, game)

        match = cog.load_match_state(game)
        self.assertTrue(match.maneuver_uncontested)
        self.assertIsNone(match.challenger_id)
        self.assertIsNone(match.pending_action)

    async def test_nobody_moves_and_nobody_is_charged(self) -> None:
        cog, game, match = self.build()
        positions = {
            player_id: match.board.meeple_position(player_id)
            for player_id in match.visiting.field_players
        }

        await self.decline(cog, game)

        after = cog.load_match_state(game)
        self.assertEqual(
            {
                player_id: after.board.meeple_position(player_id)
                for player_id in after.visiting.field_players
            },
            positions,
        )
        self.assertEqual(after.exhaustion, {})

    async def test_it_goes_straight_to_the_offense_s_pick(self) -> None:
        cog, game, _ = self.build()

        interaction = await self.decline(cog, game)

        announcement = interaction.followup.send.await_args_list[0]
        self.assertIn("sent nobody in to challenge", announcement.args[0])
        self.assertIsInstance(
            interaction.followup.send.await_args_list[-1].kwargs["view"],
            ManeuverActionPromptView,
        )

    async def test_only_the_defense_may_send_nobody(self) -> None:
        cog, game, _ = self.build()

        interaction = await self.decline(cog, game, user_id=111)

        self.assertIn(
            "defending",
            interaction.response.send_message.await_args.args[0],
        )
        self.assertFalse(cog.load_match_state(game).maneuver_uncontested)

    async def test_a_second_click_finds_the_question_settled(self) -> None:
        cog, game, _ = self.build()
        await self.decline(cog, game)

        interaction = await self.decline(cog, game)

        self.assertIn(
            "already gone unchallenged",
            interaction.followup.send.await_args.args[0],
        )

    async def test_a_challenger_chosen_first_closes_it(self) -> None:
        cog, game, match = self.build()
        challenger = match.eligible_challengers()[0]
        view = ManeuverChallengeView(cog, game.game_id)
        cog.announce_maneuver_challenge = mock.AsyncMock()
        cog.begin_maneuver_action_selection = mock.AsyncMock()
        with mock.patch("cogs.d12ball_views.save_games"), \
                mock.patch("cogs.d12ball.save_games"):
            await view.select_challenger(build_interaction(222), challenger)

        interaction = await self.decline(cog, game)

        self.assertIn(
            "already been chosen",
            interaction.followup.send.await_args.args[0],
        )
        self.assertFalse(cog.load_match_state(game).maneuver_uncontested)

    def test_a_defender_on_the_ball_is_not_declinable(self) -> None:
        cog, game, match = self.build()
        match.board.place_meeple(
            match.eligible_challengers()[0],
            match.ball.zone,
            match.ball.space_index,
        )
        game.match_state = match.to_dict()

        self.assertFalse(match.may_decline_challenge())
        with self.assertRaises(ValueError):
            match.begin_uncontested_maneuver()

        # A prompt saved before that defender walked on is the only way
        # to be looking at this view in this state -- it offers the
        # challengers and no way out of the challenge.
        view = ManeuverChallengeView(cog, game.game_id)
        self.assertNotIn(
            f"d12ball:challenge_decline:{game.game_id}",
            [item.custom_id for item in view.children],
        )


if __name__ == "__main__":
    unittest.main()
