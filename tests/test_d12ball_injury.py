"""
The injured player's maneuver disadvantage.

"They automatically lose a challenge, and must win a skill test even
when their maneuver beats their opponent's outright" (docs/living-rules.md,
"Injured players" under Exhaustion and injury). So a tie against exactly
one injured participant is settled without a roll, and a decisive
maneuver owed to an injured player is downgraded to a skill test they
still have to win.

`settled_maneuver_winner` is the only place that rule lives, because the
ranking on its own now disagrees with the turn in both directions -- it
takes wins away and hands them out. The tests at the bottom pin the two
callers that reconstruct a prompt after a restart to the same answer.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

from cogs.d12ball import D12Ball
from cogs.d12ball_views import LowPassChoiceView, SkillTestView
from d12ball.ai import build_ai_strategies
from d12ball.components import (
    MatchState,
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
    cog.refresh_match_image = mock.AsyncMock()
    cog.begin_effect_resolution = mock.AsyncMock()
    return cog


def build_game() -> D12BallGame:
    return D12BallGame(
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


def build_interaction() -> SimpleNamespace:
    return SimpleNamespace(
        followup=SimpleNamespace(
            send=mock.AsyncMock(return_value=SimpleNamespace(id=999)),
        ),
    )


class ManeuverInjuryTests(unittest.IsolatedAsyncioTestCase):
    def build(self) -> tuple[D12Ball, D12BallGame, MatchState]:
        """
        Home in possession, challenged by a visiting player -- the
        ordinary two-player maneuver.
        """
        cog = build_cog()
        game = build_game()
        cog.games[game.game_id] = game
        match = cog.initialize_standard_match(game)
        match.active_player_id = match.home.field_players[0]
        match.challenger_id = match.visiting.field_players[0]
        return cog, game, match

    async def resolve(self, cog, game, match) -> SimpleNamespace:
        interaction = build_interaction()
        with mock.patch("cogs.d12ball.save_games"):
            await cog.resolve_maneuver(interaction, game, match)
        return interaction

    def last_view(self, interaction):
        for call in reversed(interaction.followup.send.await_args_list):
            if "view" in call.kwargs:
                return call.kwargs["view"]
        return None

    async def test_decisive_win_by_healthy_player_resolves_automatically(
        self,
    ) -> None:
        cog, game, match = self.build()
        match.offense_maneuver = "Low Pass"
        match.defense_maneuver = "Pressure"  # Low Pass beats Pressure.

        await self.resolve(cog, game, match)

        cog.begin_effect_resolution.assert_awaited_once()
        self.assertEqual(
            cog.begin_effect_resolution.await_args.args[3], "Low Pass",
        )

    async def test_decisive_win_by_injured_player_forces_a_skill_test(
        self,
    ) -> None:
        cog, game, match = self.build()
        match.offense_maneuver = "Low Pass"
        match.defense_maneuver = "Pressure"  # Would auto-win for offense.
        match.injured.add(match.active_player_id)

        interaction = await self.resolve(cog, game, match)

        # No automatic effect resolution -- a skill test goes up instead.
        cog.begin_effect_resolution.assert_not_awaited()
        self.assertIsInstance(self.last_view(interaction), SkillTestView)

    async def test_decisive_win_by_injured_defender_forces_a_skill_test(
        self,
    ) -> None:
        cog, game, match = self.build()
        match.offense_maneuver = "Low Pass"
        match.defense_maneuver = "Steal Intercept"  # Beats Low Pass.
        match.injured.add(match.challenger_id)

        interaction = await self.resolve(cog, game, match)

        cog.begin_effect_resolution.assert_not_awaited()
        self.assertIsInstance(self.last_view(interaction), SkillTestView)

    async def test_tie_with_one_injured_participant_is_an_auto_loss(
        self,
    ) -> None:
        cog, game, match = self.build()
        match.offense_maneuver = "Low Pass"
        match.defense_maneuver = "Block Deflect"  # Same rank -- a tie.
        match.injured.add(match.active_player_id)

        await self.resolve(cog, game, match)

        # The healthy side (defense) wins outright, no skill test.
        cog.begin_effect_resolution.assert_awaited_once()
        self.assertEqual(
            cog.begin_effect_resolution.await_args.args[3], "Block Deflect",
        )

    async def test_an_auto_loss_charges_neither_side_a_token(self) -> None:
        cog, game, match = self.build()
        match.offense_maneuver = "Low Pass"
        match.defense_maneuver = "Block Deflect"
        match.injured.add(match.active_player_id)

        await self.resolve(cog, game, match)

        # The token is what a player pays for entering the test, and no
        # test was rolled.
        self.assertNotIn(match.active_player_id, match.exhaustion)
        self.assertNotIn(match.challenger_id, match.exhaustion)

    async def test_tie_with_both_injured_still_runs_a_skill_test(
        self,
    ) -> None:
        cog, game, match = self.build()
        match.offense_maneuver = "Low Pass"
        match.defense_maneuver = "Block Deflect"
        match.injured.add(match.active_player_id)
        match.injured.add(match.challenger_id)

        interaction = await self.resolve(cog, game, match)

        # Neither has the relative advantage, so it's an ordinary tie.
        cog.begin_effect_resolution.assert_not_awaited()
        self.assertIsInstance(self.last_view(interaction), SkillTestView)

    async def test_an_injured_players_uncontested_maneuver_still_succeeds(
        self,
    ) -> None:
        cog, game, match = self.build()
        match.offense_maneuver = "Low Pass"
        match.defense_maneuver = None
        match.challenger_id = None
        match.maneuver_uncontested = True
        match.injured.add(match.active_player_id)

        await self.resolve(cog, game, match)

        # Nobody to be disadvantaged against and no challenge to lose,
        # so the disadvantage has nothing to bite on.
        cog.begin_effect_resolution.assert_awaited_once()
        self.assertEqual(
            cog.begin_effect_resolution.await_args.args[3], "Low Pass",
        )


class SettledWinnerRestoreTests(unittest.TestCase):
    """
    A restart mid-maneuver reconstructs its prompt from match state, so
    `build_effect_choice_view` has to reach the same verdict
    `resolve_maneuver` did. Deriving it from the ranking alone gets both
    injury cases backwards.
    """

    def build(self) -> tuple[D12Ball, D12BallGame, MatchState]:
        cog = build_cog()
        game = build_game()
        cog.games[game.game_id] = game
        match = cog.initialize_standard_match(game)
        match.active_player_id = match.home.field_players[0]
        match.challenger_id = match.visiting.field_players[0]
        return cog, game, match

    def test_no_effect_choice_while_an_injured_player_owes_a_test(
        self,
    ) -> None:
        cog, game, match = self.build()
        match.offense_maneuver = "Low Pass"
        match.defense_maneuver = "Pressure"
        match.injured.add(match.active_player_id)

        self.assertIsNone(cog.settled_maneuver_winner(match))
        # The ranking says Low Pass won; the turn says roll for it.
        self.assertIsNone(cog.build_effect_choice_view(game.game_id, match))

    def test_an_auto_loss_restores_the_winners_effect_choice(self) -> None:
        cog, game, match = self.build()
        match.offense_maneuver = "Low Pass"
        match.defense_maneuver = "Block Deflect"
        match.injured.add(match.challenger_id)

        # The ranking says tie, which used to mean "a skill test is
        # pending"; the injured challenger has already lost it.
        self.assertEqual(cog.settled_maneuver_winner(match), "Low Pass")
        self.assertIsInstance(
            cog.build_effect_choice_view(game.game_id, match),
            LowPassChoiceView,
        )

    def test_an_uncontested_maneuver_is_its_own_winner(self) -> None:
        cog, game, match = self.build()
        match.offense_maneuver = "Low Pass"
        match.defense_maneuver = None
        match.challenger_id = None
        match.maneuver_uncontested = True

        self.assertEqual(cog.settled_maneuver_winner(match), "Low Pass")


if __name__ == "__main__":
    unittest.main()
