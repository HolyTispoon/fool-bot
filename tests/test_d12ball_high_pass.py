"""
A High Pass is not a loose ball.

It borrows the loose-ball contest's machinery -- two players on one
space, one skill test, one winner -- and shares nothing else with it.
A loose ball is the ball lying in a space the possessing side doesn't
hold, and both sides go and get it. A High Pass has already been
caught: the receiver holds the ball and is being challenged for it, so
winning changes nothing and only losing is a turnover. These cover the
two places that difference is visible -- what the prompts call it, and
whether anyone runs back afterwards.

See D12Ball.apply_high_pass and contest_noun in cogs/d12ball_helpers.py,
and "High Pass" and "Loose ball" in docs/living-rules.md.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

from cogs.d12ball import D12Ball
from cogs.d12ball_helpers import contest_noun
from cogs.d12ball_views import (
    LooseBallSkillTestView,
    SetUpAttemptChoiceView,
)
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
    cog.announce_run_back = mock.AsyncMock()
    cog.finish_maneuver_resolution = mock.AsyncMock()
    cog.begin_substitution_window = mock.AsyncMock()
    cog.end_period = mock.AsyncMock()
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


class HighPassContestTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    def build_contest(self, is_high_pass: bool):
        """
        A match sitting on the shared contest, with the possessing
        side's receiver and one defender both on the ball's space.
        """
        cog = build_cog()
        game = build_game()
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
        )
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
        cog.games[game.game_id] = game
        return cog, game, match, receiver, challenger

    def rolls_for(
        self, cog: D12Ball, receiver: str, challenger: str, winner: str,
    ) -> list[int]:
        """Dice that make `winner` ("offense"/"defense") take the test."""
        offense_skill = cog.player_catalog.effective_profile(
            cog.get_player_definition(receiver)
        ).offense
        defense_skill = cog.player_catalog.effective_profile(
            cog.get_player_definition(challenger)
        ).defense
        # One total is pinned level with the other, then nudged.
        offense_roll = 6
        defense_roll = offense_roll + offense_skill - defense_skill
        self.assertTrue(2 <= defense_roll <= 11)
        if winner == "offense":
            return [offense_roll, defense_roll - 1]
        return [offense_roll, defense_roll + 1]

    def test_the_prompts_name_the_contest_they_belong_to(self) -> None:
        cog, game, match, _, _ = self.build_contest(is_high_pass=True)
        self.assertEqual(contest_noun(match), "high pass")
        self.assertEqual(
            [item.label for item in LooseBallSkillTestView(
                cog, game.game_id,
            ).children],
            ["Roll for the high pass"],
        )

        cog, game, match, _, _ = self.build_contest(is_high_pass=False)
        self.assertEqual(contest_noun(match), "loose ball")
        self.assertEqual(
            [item.label for item in LooseBallSkillTestView(
                cog, game.game_id,
            ).children],
            ["Roll for the loose ball"],
        )

    async def test_a_receiver_who_keeps_the_ball_runs_nobody_back(
        self,
    ) -> None:
        cog, game, match, receiver, challenger = self.build_contest(
            is_high_pass=True,
        )
        possession_before = match.ball.possession

        view = LooseBallSkillTestView(cog, game.game_id)
        with mock.patch("cogs.d12ball_views.save_games"), mock.patch(
            "cogs.d12ball.save_games",
        ), mock.patch(
            "cogs.d12ball_views.random.randint",
            side_effect=self.rolls_for(cog, receiver, challenger, "offense"),
        ), mock.patch("cogs.d12ball_views.render_skill_test_dice"), mock.patch(
            "cogs.d12ball_views.discord.File",
        ):
            await view.roll(build_interaction())

        saved = cog.load_match_state(game)
        self.assertEqual(saved.ball.possession, possession_before)
        self.assertFalse(saved.pending_run_back)
        cog.announce_run_back.assert_not_awaited()
        cog.begin_substitution_window.assert_not_awaited()
        cog.finish_maneuver_resolution.assert_awaited_once()
        self.assertFalse(
            cog.finish_maneuver_resolution.await_args.kwargs[
                "turnover_occurred"
            ]
        )

    async def test_a_receiver_who_loses_the_ball_is_a_turnover(self) -> None:
        # The other half of the rule: losing the high pass hands over
        # possession, and that -- like every turnover -- does run
        # everyone back.
        cog, game, match, receiver, challenger = self.build_contest(
            is_high_pass=True,
        )
        possession_before = match.ball.possession

        view = LooseBallSkillTestView(cog, game.game_id)
        with mock.patch("cogs.d12ball_views.save_games"), mock.patch(
            "cogs.d12ball.save_games",
        ), mock.patch(
            "cogs.d12ball_views.random.randint",
            side_effect=self.rolls_for(cog, receiver, challenger, "defense"),
        ), mock.patch("cogs.d12ball_views.render_skill_test_dice"), mock.patch(
            "cogs.d12ball_views.discord.File",
        ):
            await view.roll(build_interaction())

        saved = cog.load_match_state(game)
        self.assertNotEqual(saved.ball.possession, possession_before)
        self.assertTrue(saved.pending_run_back)
        cog.finish_maneuver_resolution.assert_not_awaited()

    async def test_declining_a_two_space_set_up_contests_nothing(
        self,
    ) -> None:
        # 2026-08-07: a pass of 2 is received, full stop. Declining the
        # scoring opportunity it offers resolves the maneuver as an
        # ordinary pass instead of falling back to the contest.
        cog, game, match, receiver, _ = self.build_contest(
            is_high_pass=True,
        )
        cog.begin_loose_ball = mock.AsyncMock()

        view = SetUpAttemptChoiceView(cog, game.game_id, receiver, 2)
        self.assertEqual(
            [item.label for item in view.children][1],
            "Decline -- resolve as a normal pass",
        )

        await cog.decline_scoring_attempt(
            build_interaction(), game, match, 2,
        )
        cog.begin_loose_ball.assert_not_awaited()
        cog.finish_maneuver_resolution.assert_awaited_once()

    def build_fast_contest(self, is_high_pass: bool):
        """The same contest, with a ball moving fast enough to matter."""
        cog, game, match, receiver, challenger = self.build_contest(
            is_high_pass=is_high_pass,
        )
        match.ball.speed = 4  # a +2 modifier
        game.match_state = match.to_dict()
        return cog, game, match, receiver, challenger

    async def test_the_receiver_adds_ball_speed_to_keep_a_high_pass(
        self,
    ) -> None:
        # 2026-08-07: the offense carries the ball speed modifier into
        # a High Pass's contest. These rolls lose by 1 without it.
        cog, game, match, receiver, challenger = self.build_fast_contest(
            is_high_pass=True,
        )
        possession_before = match.ball.possession

        view = LooseBallSkillTestView(cog, game.game_id)
        with mock.patch("cogs.d12ball_views.save_games"), mock.patch(
            "cogs.d12ball.save_games",
        ), mock.patch(
            "cogs.d12ball_views.random.randint",
            side_effect=self.rolls_for(cog, receiver, challenger, "defense"),
        ), mock.patch("cogs.d12ball_views.render_skill_test_dice"), mock.patch(
            "cogs.d12ball_views.discord.File",
        ):
            await view.roll(build_interaction())

        saved = cog.load_match_state(game)
        self.assertEqual(saved.ball.possession, possession_before)
        self.assertFalse(saved.pending_run_back)

    async def test_a_loose_ball_gives_nobody_the_speed_modifier(self) -> None:
        # The other half of that rule: a genuine loose ball is nobody's
        # yet, so the same rolls on the same fast ball go the other way.
        cog, game, match, receiver, challenger = self.build_fast_contest(
            is_high_pass=False,
        )
        possession_before = match.ball.possession

        view = LooseBallSkillTestView(cog, game.game_id)
        with mock.patch("cogs.d12ball_views.save_games"), mock.patch(
            "cogs.d12ball.save_games",
        ), mock.patch(
            "cogs.d12ball_views.random.randint",
            side_effect=self.rolls_for(cog, receiver, challenger, "defense"),
        ), mock.patch("cogs.d12ball_views.render_skill_test_dice"), mock.patch(
            "cogs.d12ball_views.discord.File",
        ):
            await view.roll(build_interaction())

        self.assertNotEqual(
            cog.load_match_state(game).ball.possession, possession_before,
        )

    async def test_a_loose_ball_kept_by_the_offense_runs_nobody_back(
        self,
    ) -> None:
        # Not specific to the high pass: any resolution that leaves
        # possession where it was skips the run back.
        cog, game, match, receiver, challenger = self.build_contest(
            is_high_pass=False,
        )

        view = LooseBallSkillTestView(cog, game.game_id)
        with mock.patch("cogs.d12ball_views.save_games"), mock.patch(
            "cogs.d12ball.save_games",
        ), mock.patch(
            "cogs.d12ball_views.random.randint",
            side_effect=self.rolls_for(cog, receiver, challenger, "offense"),
        ), mock.patch("cogs.d12ball_views.render_skill_test_dice"), mock.patch(
            "cogs.d12ball_views.discord.File",
        ):
            await view.roll(build_interaction())

        self.assertFalse(cog.load_match_state(game).pending_run_back)
        cog.announce_run_back.assert_not_awaited()
        cog.finish_maneuver_resolution.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
