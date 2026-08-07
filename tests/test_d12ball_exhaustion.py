"""
Exhaustion that crosses the Exhausted threshold has to be written out
with the tokens that caused it.

Charging tokens and testing them against a defensive skill happen in
two different places -- `MatchState.add_exhaustion` holds the count,
and the cog holds the catalog the threshold comes from -- so it is
possible to save a match between the two and lose the flag. That is
not cosmetic: `SkillTestView` reloads the saved state to resolve the
roll and hands out an injury check to whoever is in `match.exhausted`
by then, so a dropped flag is a skipped injury check.

See D12Ball.apply_exhaustion and D12Ball.run_injury_test in
cogs/d12ball.py, and "Exhaustion" in docs/d12ball-rules.md.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

from cogs.d12ball import D12Ball
from cogs.d12ball_views import SkillTestView
from d12ball.components import (
    MatchState,
    TeamSide,
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
    cog.refresh_match_image = mock.AsyncMock()
    cog.begin_effect_resolution = mock.AsyncMock()
    cog.run_injury_test = mock.AsyncMock()
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


def build_interaction() -> SimpleNamespace:
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


def tie_maneuvers(cog: D12Ball) -> tuple[str, str]:
    for offense in (m.name for m in cog.maneuver_catalog.offense):
        for defense in (m.name for m in cog.maneuver_catalog.defense):
            if cog.maneuver_catalog.resolve(offense, defense) == "tie":
                return offense, defense
    raise AssertionError("The catalog has no tying maneuver pair.")


class SkillTestExhaustionTests(unittest.IsolatedAsyncioTestCase):
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

    def defense_skill(self, cog: D12Ball, player_id: str) -> int:
        return cog.player_catalog.effective_profile(
            cog.get_player_definition(player_id)
        ).defense

    async def test_the_entry_token_s_exhausted_flag_is_saved(self) -> None:
        # One token below the threshold going in, so the token the
        # skill test itself charges is what crosses it.
        cog = build_cog()
        match = self.build_match()
        game = build_game()
        cog.games[game.game_id] = game

        offense_id = match.home.field_players[0]
        match.active_player_id = offense_id
        match.challenger_id = match.visiting.field_players[0]
        match.offense_maneuver, match.defense_maneuver = tie_maneuvers(cog)
        match.add_exhaustion(
            offense_id, self.defense_skill(cog, offense_id),
        )
        self.assertNotIn(offense_id, match.exhausted)
        game.match_state = match.to_dict()

        with mock.patch("cogs.d12ball.save_games"):
            await cog.resolve_maneuver(build_interaction(), game, match)

        self.assertIn(offense_id, cog.load_match_state(game).exhausted)

    async def test_a_tie_s_token_is_in_force_for_the_injury_check(
        self,
    ) -> None:
        # A tie sends the test back to be rolled again and charges both
        # players another token. Whoever that pushes over their
        # defensive skill has to be exhausted for the roll that finally
        # resolves the test -- and therefore for its injury check.
        cog = build_cog()
        match = self.build_match()
        game = build_game()
        cog.games[game.game_id] = game

        offense_id = match.home.field_players[0]
        defense_id = match.visiting.field_players[0]
        match.active_player_id = offense_id
        match.challenger_id = defense_id
        match.offense_maneuver, match.defense_maneuver = tie_maneuvers(cog)
        # The entry token puts them level with the threshold; the tie's
        # token is the one that crosses it.
        match.add_exhaustion(
            offense_id, self.defense_skill(cog, offense_id) - 1,
        )
        game.match_state = match.to_dict()

        interaction = build_interaction()
        with mock.patch("cogs.d12ball.save_games"):
            await cog.resolve_maneuver(interaction, game, match)
        self.assertNotIn(offense_id, cog.load_match_state(game).exhausted)

        # Rolls chosen so the two totals land level. Neither of these
        # two is a Midfielder and neither maneuver is Steal Intercept,
        # so skill is the only modifier in play.
        offense_roll = 6
        defense_roll = (
            offense_roll
            + cog.player_catalog.effective_profile(
                cog.get_player_definition(offense_id)
            ).offense
            - self.defense_skill(cog, defense_id)
        )
        self.assertTrue(1 <= defense_roll <= 12)

        view = SkillTestView(cog, game.game_id)
        with mock.patch("cogs.d12ball_views.save_games"), mock.patch(
            "cogs.d12ball_views.random.randint",
            side_effect=[offense_roll, defense_roll],
        ):
            await view.roll(interaction)

        self.assertIn(offense_id, cog.load_match_state(game).exhausted)
        cog.run_injury_test.assert_not_awaited()

    async def test_apply_exhaustion_charges_and_tests_together(self) -> None:
        cog = build_cog()
        match = self.build_match()
        player_id = match.home.field_players[0]
        skill = self.defense_skill(cog, player_id)

        text = cog.apply_exhaustion(match, player_id, skill)
        self.assertEqual(match.exhaustion[player_id], skill)
        self.assertNotIn(player_id, match.exhausted)
        self.assertNotIn("exhausted", text)

        text = cog.apply_exhaustion(match, player_id, 1)
        self.assertEqual(match.exhaustion[player_id], skill + 1)
        self.assertIn(player_id, match.exhausted)
        self.assertIn("exhausted", text)

    async def test_the_own_goal_roll_costs_the_roller_a_token(self) -> None:
        # Charged for making the attempt, not for the result, so both
        # outcomes pay it -- see "Own goal trigger" in
        # docs/d12ball-rules.md.
        for roll, outcome in ((12, "avoided"), (1, "conceded")):
            with self.subTest(outcome=outcome):
                cog = build_cog()
                cog.begin_run_back = mock.AsyncMock()
                cog.finish_maneuver_resolution = mock.AsyncMock()
                match = self.build_match()
                game = build_game()
                cog.games[game.game_id] = game

                player_id = match.home.field_players[0]
                zone, space_index = match.board.meeple_position(player_id)
                match.ball.possession = TeamSide.HOME
                match.set_ball_space(zone, space_index)
                match.active_player_id = player_id
                game.match_state = match.to_dict()

                with mock.patch("cogs.d12ball.save_games"), mock.patch(
                    "cogs.d12ball.random.randint", return_value=roll,
                ):
                    await cog.run_own_goal_roll(
                        build_interaction(), game, match, distance_moved=1,
                    )

                self.assertEqual(
                    cog.load_match_state(game).exhaustion.get(player_id), 1,
                )

    async def test_a_forced_run_back_still_tests_the_threshold(self) -> None:
        # Forced run backs are applied silently, so they carry no
        # message to run the threshold test for them.
        cog = build_cog()
        match = self.build_match()
        player_id = match.home.field_players[0]
        skill = self.defense_skill(cog, player_id)

        match.add_exhaustion(player_id, skill + 1)
        self.assertTrue(cog.retest_exhausted(match, player_id))
        self.assertIn(player_id, match.exhausted)
        # Only on the transition, so it can be announced once.
        self.assertFalse(cog.retest_exhausted(match, player_id))


if __name__ == "__main__":
    unittest.main()
