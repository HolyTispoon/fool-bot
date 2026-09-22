"""
Who challenges a maneuver, and who is asked.

A defender already standing on the ball challenges for nothing, so
that challenge is neither theirs to decline nor a choice to be put --
*when there is one of them*. Two on the ball is the defending coach's
pick (the author, 2026-08-17): they are the whole of the offer, since
nobody may be walked in past them, and they differ only in who they
are.

It is a count and not a flag, and the AI's own turn used to read it as
one -- `play_ai_turn` took the first name off the list and sent it, so
a coach defending Dinky with two players on the ball was never asked.
Both routes ask `MatchState.automatic_challengers` the same question
now, and word the prompt out of the same `challenger_prompt_ask`.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

from cogs.d12ball import D12Ball
from cogs.d12ball_views import ManeuverChallengeView, PlayerActionView
from d12ball.ai import build_ai_strategies
from d12ball.components import (
    MatchState,
    TeamSide,
    Zone,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.engine import RulesEngine
from d12ball.game import AIOpponent, D12BallGame, GameStatus, Team
from save_patches import suppressed_cog_saves, suppressed_view_saves
from cog_steps import play_ai_turn


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
    cog.refresh_match_image = mock.AsyncMock()
    cog.drop_turn_prompt = mock.AsyncMock()
    cog.auto_resolve_challenger = mock.AsyncMock()
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
    # `channel.send` and `followup.send` share one mock: which route a
    # post takes depends on whether the interaction still had a response
    # to give, and these tests read back "what this posted" without
    # caring which route carried it.
    send = mock.AsyncMock(return_value=SimpleNamespace(id=999))
    return SimpleNamespace(
        user=SimpleNamespace(id=user_id, display_name="One"),
        channel=SimpleNamespace(send=send),
        guild=None,
        response=SimpleNamespace(
            defer=mock.AsyncMock(),
            edit_message=mock.AsyncMock(),
            send_message=mock.AsyncMock(),
            is_done=lambda: True,
        ),
        followup=SimpleNamespace(send=send),
        message=SimpleNamespace(content="the turn prompt"),
    )


def sent_texts(interaction: SimpleNamespace) -> list[str]:
    return [
        call.args[0]
        for call in interaction.followup.send.await_args_list
        if call.args
    ]


def prompt_views(interaction: SimpleNamespace) -> list:
    return [
        call.kwargs["view"]
        for call in interaction.followup.send.await_args_list
        if call.kwargs.get("view") is not None
    ]


class ChallengerChoiceTests(unittest.IsolatedAsyncioTestCase):
    def build(self, possession: TeamSide, **game_overrides):
        """
        The ball in midfield with `possession`, and the defence stood
        clear of it -- so the fixtures below decide for themselves how
        many of them are on the ball's own space.
        """
        cog = build_cog()
        game = build_game(**game_overrides)
        cog.games[game.game_id] = game
        match = cog.engine.initialize_standard_match(game)

        setup = match.setup_for_side(possession)
        handler = next(
            player_id
            for player_id in setup.field_players
            if match.board.meeple_position(player_id)[0] == Zone.MIDFIELD
        )
        match.ball.possession = possession
        match.set_ball_space(*match.board.meeple_position(handler))
        match.active_player_id = handler

        elsewhere = 0 if match.ball.space_index else 1
        for player_id in match.setup_for_side(
            match.defending_side()
        ).field_players:
            zone, space_index = match.board.meeple_position(player_id)
            if (zone, space_index) == (match.ball.zone, match.ball.space_index):
                match.board.place_meeple(player_id, zone, elsewhere)

        return cog, game, match

    def stand_on_the_ball(self, match: MatchState, count: int) -> list[str]:
        """Put `count` of the defending side onto the ball's space."""
        defenders = match.setup_for_side(
            match.defending_side()
        ).field_players[:count]
        for player_id in defenders:
            match.board.place_meeple(
                player_id, match.ball.zone, match.ball.space_index,
            )
        self.assertEqual(len(match.automatic_challengers()), count)
        return defenders

    # -- A human offense -----------------------------------------------

    async def maneuver(self, cog, game, match, user_id: int):
        game.match_state = match.to_dict()
        interaction = build_interaction(user_id=user_id)
        view = PlayerActionView(cog, game.game_id)
        with suppressed_view_saves(), suppressed_cog_saves():
            await view.choose_action(interaction, "maneuver")
        return interaction

    async def test_one_defender_on_the_ball_challenges_unasked(self) -> None:
        cog, game, match = self.build(TeamSide.HOME)
        on_the_ball = self.stand_on_the_ball(match, 1)

        interaction = await self.maneuver(cog, game, match, user_id=111)

        cog.auto_resolve_challenger.assert_awaited_once()
        self.assertEqual(
            cog.auto_resolve_challenger.await_args.kwargs["challenger_id"],
            on_the_ball[0],
        )
        self.assertEqual(prompt_views(interaction), [])

    async def test_two_defenders_on_the_ball_are_the_coach_s_pick(
        self,
    ) -> None:
        cog, game, match = self.build(TeamSide.HOME)
        on_the_ball = self.stand_on_the_ball(match, 2)

        interaction = await self.maneuver(cog, game, match, user_id=111)

        cog.auto_resolve_challenger.assert_not_awaited()
        [view] = prompt_views(interaction)
        self.assertIsInstance(view, ManeuverChallengeView)
        self.assertEqual(
            {
                (item.custom_id or "").rsplit(":", 1)[-1]
                for item in view.children
            },
            set(on_the_ball),
        )

    # -- Dinky's own turn ----------------------------------------------

    async def ai_turn(self, cog, game, match):
        game.match_state = match.to_dict()
        interaction = build_interaction(user_id=111)
        with suppressed_view_saves(), suppressed_cog_saves():
            await play_ai_turn(cog, interaction, game, match)
        return interaction

    async def test_the_ai_s_turn_asks_when_two_defenders_are_on_the_ball(
        self,
    ) -> None:
        # The bug: `on_ball_space[0]` picked for the coach off
        # placement order, which is arbitrary, and the pick is settled
        # on defensive skill.
        cog, game, match = self.build(
            TeamSide.VISITING, player_2_id=None, ai_opponent=AIOpponent.DINKY,
        )
        on_the_ball = self.stand_on_the_ball(match, 2)

        interaction = await self.ai_turn(cog, game, match)

        cog.auto_resolve_challenger.assert_not_awaited()
        [view] = prompt_views(interaction)
        self.assertIsInstance(view, ManeuverChallengeView)
        self.assertEqual(
            {
                (item.custom_id or "").rsplit(":", 1)[-1]
                for item in view.children
            },
            set(on_the_ball),
        )

    async def test_the_ai_s_turn_still_settles_a_lone_defender(self) -> None:
        cog, game, match = self.build(
            TeamSide.VISITING, player_2_id=None, ai_opponent=AIOpponent.DINKY,
        )
        on_the_ball = self.stand_on_the_ball(match, 1)

        interaction = await self.ai_turn(cog, game, match)

        cog.auto_resolve_challenger.assert_awaited_once()
        self.assertEqual(
            cog.auto_resolve_challenger.await_args.kwargs["challenger_id"],
            on_the_ball[0],
        )
        self.assertEqual(prompt_views(interaction), [])

    # -- The wording ---------------------------------------------------

    async def test_the_ai_s_prompt_does_not_offer_a_refusal_it_has_not_got(
        self,
    ) -> None:
        # Two defenders on the ball cannot be held back, so the prompt
        # must not offer what the view does not build. It said "or send
        # nobody" regardless.
        cog, game, match = self.build(
            TeamSide.VISITING, player_2_id=None, ai_opponent=AIOpponent.DINKY,
        )
        self.stand_on_the_ball(match, 2)

        interaction = await self.ai_turn(cog, game, match)

        prompt = sent_texts(interaction)[-1]
        self.assertIn("already on the ball", prompt)
        self.assertNotIn("send nobody", prompt)

    async def test_the_ai_s_prompt_offers_the_refusal_when_there_is_one(
        self,
    ) -> None:
        cog, game, match = self.build(
            TeamSide.VISITING, player_2_id=None, ai_opponent=AIOpponent.DINKY,
        )
        self.assertTrue(match.may_decline_challenge())

        interaction = await self.ai_turn(cog, game, match)

        self.assertIn("send nobody", sent_texts(interaction)[-1])


if __name__ == "__main__":
    unittest.main()
