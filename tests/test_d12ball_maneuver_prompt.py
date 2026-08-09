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


class ManeuverChallengeAnnouncementTests(unittest.IsolatedAsyncioTestCase):
    """
    How a settled challenge is announced.

    It used to be two lines of prose -- "has chosen to maneuver" and
    "will challenge" -- naming players a coach can already see on the
    board and saying nothing about them. It is now one image, carrying
    the skills and abilities the maneuver about to be picked is
    weighed against.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    def build_match(self) -> MatchState:
        return MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
        )

    def build_interaction(self) -> SimpleNamespace:
        return SimpleNamespace(
            channel=None,
            guild=None,
            followup=SimpleNamespace(
                send=mock.AsyncMock(return_value=SimpleNamespace(id=999)),
            ),
            delete_original_response=mock.AsyncMock(),
        )

    async def resolve(self, walk_in: bool):
        cog = build_cog()
        cog.refresh_match_image = mock.AsyncMock()
        cog.begin_maneuver_action_selection = mock.AsyncMock()
        game = build_game()
        cog.games[game.game_id] = game

        match = self.build_match()
        match.select_ball_handler(match.eligible_ball_handlers()[0])
        challenger = next(
            player_id
            for player_id in match.eligible_challengers()
            if (match.distance_to_ball(player_id) > 0) == walk_in
        )
        game.match_state = match.to_dict()

        interaction = self.build_interaction()
        with mock.patch("cogs.d12ball.save_games"):
            await cog.auto_resolve_challenger(
                interaction, game, match, challenger,
            )
        return interaction

    async def test_the_matchup_is_posted_as_an_image_and_not_as_prose(
        self,
    ) -> None:
        interaction = await self.resolve(walk_in=False)

        calls = interaction.followup.send.await_args_list
        self.assertEqual(len(calls), 1)
        self.assertIn("file", calls[0].kwargs)
        self.assertFalse(calls[0].args)

    async def test_the_walk_in_is_posted_above_the_image(self) -> None:
        # Above, not below: the image is meant to sit directly on top
        # of the maneuver prompt it is being read for.
        interaction = await self.resolve(walk_in=True)

        calls = interaction.followup.send.await_args_list
        self.assertEqual(len(calls), 2)
        self.assertIn("has moved", calls[0].args[0])
        self.assertIn("file", calls[1].kwargs)

    def test_the_image_captions_a_player_with_the_short_ability(
        self,
    ) -> None:
        # The sentence version is a caption under a portrait here, next
        # to another player's, so the image takes the abbreviated form
        # the abilities sheet carries. The roster still shows the
        # sentence.
        cog = build_cog()
        match = self.build_match()
        player_id = match.home.field_players[0]
        profile = cog.player_catalog.effective_profile(
            cog.get_player_definition(player_id),
        )

        side = cog.challenge_side(player_id, attacking=True)

        self.assertEqual(side.ability, profile.ability_short)
        self.assertNotEqual(side.ability, profile.ability)

    async def test_dropping_the_turn_prompt_clears_its_id(self) -> None:
        cog = build_cog()
        game = build_game()
        game.turn_message_id = 555
        interaction = self.build_interaction()

        with mock.patch("cogs.d12ball.save_games"):
            await cog.drop_turn_prompt(interaction, game)

        interaction.delete_original_response.assert_awaited_once()
        self.assertIsNone(game.turn_message_id)

    async def test_an_already_deleted_turn_prompt_is_not_an_error(
        self,
    ) -> None:
        cog = build_cog()
        game = build_game()
        game.turn_message_id = 555
        interaction = self.build_interaction()
        interaction.delete_original_response = mock.AsyncMock(
            side_effect=discord.NotFound(
                mock.Mock(status=404), "already gone",
            ),
        )

        with mock.patch("cogs.d12ball.save_games"):
            await cog.drop_turn_prompt(interaction, game)

        self.assertIsNone(game.turn_message_id)


if __name__ == "__main__":
    unittest.main()
