"""
The public "Choose Your Maneuver" prompt's own lifetime.

Both sides pick from the same message, so it has to stay up while
either of them still has a pick to make -- and go away once neither
does, rather than leaving a button that can only answer "you have
already chosen".
"""

import unittest
from types import SimpleNamespace
from unittest import mock

import discord

from cogs.d12ball import D12Ball
from d12ball.components import (
    MatchState,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.game import D12BallGame, Team


def build_cog() -> D12Ball:
    cog = object.__new__(D12Ball)
    cog.games = {}
    cog.player_catalog = load_player_catalog()
    cog.maneuver_catalog = load_maneuver_catalog()
    cog.basic_ruleset = load_basic_ruleset()
    cog.team_emojis = {}
    cog.condition_emojis = {}
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


def build_interaction(prompt_message) -> SimpleNamespace:
    return SimpleNamespace(
        channel=SimpleNamespace(
            get_partial_message=mock.Mock(return_value=prompt_message),
        ),
    )


class ManeuverPromptLifetimeTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    def build_match(self, cog: D12Ball) -> MatchState:
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
        )
        match.active_player_id = match.home.field_players[0]
        match.challenger_id = match.visiting.field_players[0]
        return match

    def build_prompt_message(self) -> SimpleNamespace:
        return SimpleNamespace(
            edit=mock.AsyncMock(),
            delete=mock.AsyncMock(),
        )

    async def refresh(self, cog, game, match, prompt_message) -> None:
        with mock.patch("cogs.d12ball.save_games"):
            await cog.refresh_maneuver_prompt(
                build_interaction(prompt_message), game, match,
            )

    async def test_the_prompt_stays_up_while_one_side_is_still_picking(
        self,
    ) -> None:
        cog = build_cog()
        game = build_game()
        game.turn_message_id = 555
        match = self.build_match(cog)
        match.choose_offense_maneuver(cog.maneuver_catalog.offense[0].name)

        prompt_message = self.build_prompt_message()
        await self.refresh(cog, game, match, prompt_message)

        prompt_message.edit.assert_awaited_once()
        prompt_message.delete.assert_not_awaited()
        self.assertEqual(game.turn_message_id, 555)

    async def test_the_prompt_is_deleted_once_both_sides_have_picked(
        self,
    ) -> None:
        cog = build_cog()
        game = build_game()
        game.turn_message_id = 555
        match = self.build_match(cog)
        match.choose_offense_maneuver(cog.maneuver_catalog.offense[0].name)
        match.choose_defense_maneuver(cog.maneuver_catalog.defense[0].name)

        prompt_message = self.build_prompt_message()
        await self.refresh(cog, game, match, prompt_message)

        prompt_message.delete.assert_awaited_once()
        prompt_message.edit.assert_not_awaited()
        # Nothing should try to edit or re-attach a view to it later.
        self.assertIsNone(game.turn_message_id)

    async def test_an_already_deleted_prompt_is_not_an_error(self) -> None:
        cog = build_cog()
        game = build_game()
        game.turn_message_id = 555
        match = self.build_match(cog)
        match.choose_offense_maneuver(cog.maneuver_catalog.offense[0].name)
        match.choose_defense_maneuver(cog.maneuver_catalog.defense[0].name)

        prompt_message = self.build_prompt_message()
        prompt_message.delete = mock.AsyncMock(
            side_effect=discord.NotFound(
                mock.Mock(status=404), "already gone",
            ),
        )
        await self.refresh(cog, game, match, prompt_message)

        self.assertIsNone(game.turn_message_id)


if __name__ == "__main__":
    unittest.main()
