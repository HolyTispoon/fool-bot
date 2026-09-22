"""
The score attempt prompt's "Back" button, and the composition image it
undoes -- see `ScoreAttemptView.back` and `D12Ball.begin_score_attempt`.

A coach who backs out of a shot never rolled should not leave the "what
this shot is made of" image sitting in the channel; the roll prompt
carries the id of the message that posted it for exactly this.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

import discord

from cogs.d12ball import D12Ball
from cogs.d12ball_views import PlayerActionView, ScoreAttemptView
from d12ball.components import (
    MatchState,
    Zone,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.engine import RulesEngine
from d12ball.game import D12BallGame, Team
from save_patches import suppressed_cog_saves


def build_cog() -> D12Ball:
    cog = object.__new__(D12Ball)
    cog.games = {}
    cog.player_catalog = load_player_catalog()
    cog.maneuver_catalog = load_maneuver_catalog()
    cog.basic_ruleset = load_basic_ruleset()
    cog.engine = RulesEngine(
        cog.player_catalog, cog.basic_ruleset, cog.maneuver_catalog, {},
    )
    return cog


def build_game() -> D12BallGame:
    return D12BallGame(
        game_id="g1",
        game_number=1,
        guild_id=1,
        channel_id=1,
        message_id=None,
        player_1_id=111,
        player_2_id=222,
        player_1_name="One",
        player_2_name="Two",
        player_1_team=Team.ORANGE,
        player_2_team=Team.PURPLE,
        home_player_number=1,
        visiting_player_number=2,
    )


def build_interaction(composition_message) -> SimpleNamespace:
    return SimpleNamespace(
        channel=SimpleNamespace(
            get_partial_message=mock.Mock(return_value=composition_message),
        ),
        response=SimpleNamespace(
            edit_message=mock.AsyncMock(),
            send_message=mock.AsyncMock(),
        ),
    )


class ScoreAttemptBackTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    def build_shot(self, cog: D12Ball) -> tuple[D12BallGame, MatchState]:
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
        )
        match.active_player_id = match.setup_for_side(
            match.ball.possession,
        ).field_players[0]
        match.move_meeple(
            match.active_player_id, match.ball.zone, match.ball.space_index,
        )
        match.pending_action = "shoot"

        game = build_game()
        game.match_state = match.to_dict()
        cog.games[game.game_id] = game
        return game, match

    async def back(
        self, cog: D12Ball, game: D12BallGame, view: ScoreAttemptView,
        interaction,
    ) -> None:
        with suppressed_cog_saves(), mock.patch.object(
            view, "may_act_for_possession", return_value=True,
        ):
            await view.back(interaction)

    async def test_backing_out_deletes_the_composition_image(self) -> None:
        cog = build_cog()
        game, _ = self.build_shot(cog)
        composition_message = SimpleNamespace(delete=mock.AsyncMock())
        interaction = build_interaction(composition_message)

        view = ScoreAttemptView(cog, game.game_id, composition_message_id=555)
        await self.back(cog, game, view, interaction)

        interaction.channel.get_partial_message.assert_called_once_with(555)
        composition_message.delete.assert_awaited_once()
        # The turn prompt still comes back, exactly as before.
        self.assertIsInstance(
            interaction.response.edit_message.call_args.kwargs["view"],
            PlayerActionView,
        )

    async def test_an_already_deleted_composition_image_is_not_an_error(
        self,
    ) -> None:
        cog = build_cog()
        game, _ = self.build_shot(cog)
        composition_message = SimpleNamespace(
            delete=mock.AsyncMock(
                side_effect=discord.NotFound(
                    mock.Mock(status=404), "already gone",
                ),
            ),
        )
        interaction = build_interaction(composition_message)

        view = ScoreAttemptView(cog, game.game_id, composition_message_id=555)
        await self.back(cog, game, view, interaction)

        interaction.response.edit_message.assert_awaited_once()

    async def test_a_view_rebuilt_without_the_id_deletes_nothing(
        self,
    ) -> None:
        """
        `PLAIN_PROMPT_VIEWS` rebuilds this view from the cog and the
        game id alone on a restart, so a resumed "Back" has no message
        id to delete -- the image is left as the harmless remnant it
        always was in that case.
        """
        cog = build_cog()
        game, _ = self.build_shot(cog)
        composition_message = SimpleNamespace(delete=mock.AsyncMock())
        interaction = build_interaction(composition_message)

        view = ScoreAttemptView(cog, game.game_id)
        await self.back(cog, game, view, interaction)

        interaction.channel.get_partial_message.assert_not_called()
        composition_message.delete.assert_not_awaited()
        interaction.response.edit_message.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
