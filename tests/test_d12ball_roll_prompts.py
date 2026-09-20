"""
The two rolls that used to happen without being asked for.

An own goal and an injury test are both one-sided -- there is no
opposing roll to wait for -- so the bot rolled them itself and posted
the result. A coach should throw their own dice, the way they do for a
skill test and a score attempt, so each is now a button.

That turns each of them into a place a turn can *stop*, which is the
whole cost of the change and what these tests are about: what the roll
was going to do next has to survive the wait, and a restart in the
middle of it has to come back to the button rather than to the turn
underneath it. See `begin_own_goal_roll` and `begin_injury_tests` in
cogs/d12ball.py.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

from cogs.d12ball import D12Ball
from cogs.d12ball_views import (
    InjuryTestView,
    LooseBallSkillTestView,
    OwnGoalRollView,
    SkillTestView,
)
from d12ball.ai import build_ai_strategies
from d12ball.engine import RulesEngine
from d12ball.components import (
    MatchState,
    TeamSide,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.game import D12BallGame, GameStatus, Team
from follow_on_args import follow_on_argument
from save_patches import suppressed_cog_saves, suppressed_view_saves


def effect_winner_key(call) -> str:
    """
    The `winner_key` a recorded `begin_effect_resolution` was called
    with, through `follow_on_argument` -- since the front half of
    Phase 4 a settled maneuver reaches it as a `FollowOn`, so the key
    arrives by keyword where the cog used to hand it over
    positionally. See `tests/follow_on_args.py`.
    """
    return follow_on_argument(
        D12Ball.begin_effect_resolution, call, "winner_key",
    )


def build_cog() -> D12Ball:
    cog = object.__new__(D12Ball)
    cog.games = {}
    cog.player_catalog = load_player_catalog()
    cog.maneuver_catalog = load_maneuver_catalog()
    cog.basic_ruleset = load_basic_ruleset()
    cog.coin_emojis = {}
    cog.ai_strategies = build_ai_strategies(
        cog.player_catalog, cog.maneuver_catalog,
    )
    cog.engine = RulesEngine(
        cog.player_catalog, cog.basic_ruleset, cog.maneuver_catalog,
        cog.ai_strategies,
    )
    cog.refresh_match_image = mock.AsyncMock()
    cog.begin_effect_resolution = mock.AsyncMock()
    cog.begin_run_back = mock.AsyncMock()
    cog.finish_maneuver_resolution = mock.AsyncMock()
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
    # `channel.send` and `followup.send` share one mock: which route a
    # post takes depends on whether the interaction still had a response
    # to give, and these tests read back "what this posted" without
    # caring which route carried it.
    send = mock.AsyncMock(return_value=SimpleNamespace(id=999))
    return SimpleNamespace(
        user=SimpleNamespace(id=111, display_name="One"),
        channel=SimpleNamespace(send=send),
        guild=None,
        followup=SimpleNamespace(send=send),
        response=SimpleNamespace(
            defer=mock.AsyncMock(),
            edit_message=mock.AsyncMock(),
            send_message=mock.AsyncMock(),
            is_done=lambda: True,
        ),
        edit_original_response=mock.AsyncMock(),
    )


def last_view(interaction):
    for call in reversed(interaction.followup.send.await_args_list):
        if "view" in call.kwargs:
            return call.kwargs["view"]
    return None


def exhaust(match: MatchState, player_id: str, tokens: int = 3) -> None:
    """Put a player over the Exhausted threshold, flag and all."""
    match.exhaustion[player_id] = tokens
    match.exhausted.add(player_id)


class OwnGoalPromptTests(unittest.IsolatedAsyncioTestCase):
    def build(self) -> tuple[D12Ball, D12BallGame, MatchState]:
        cog = build_cog()
        game = build_game()
        cog.games[game.game_id] = game
        match = cog.engine.initialize_standard_match(game)

        handler = match.home.field_players[0]
        zone, space_index = match.board.meeple_position(handler)
        match.ball.possession = TeamSide.HOME
        match.set_ball_space(zone, space_index)
        match.active_player_id = handler
        game.match_state = match.to_dict()
        return cog, game, match

    async def test_the_risk_is_offered_rather_than_rolled(self) -> None:
        cog, game, match = self.build()
        interaction = build_interaction()

        with suppressed_cog_saves(), mock.patch(
            "random.randint",
        ) as randint:
            await cog.begin_own_goal_roll(
                interaction, game, match, distance_moved=1,
            )

        randint.assert_not_called()
        self.assertIsInstance(last_view(interaction), OwnGoalRollView)
        cog.finish_maneuver_resolution.assert_not_awaited()
        cog.begin_run_back.assert_not_awaited()

    async def test_a_pressure_that_overshoots_asks_for_the_roll(self) -> None:
        # The one thing that risks an own goal, from the one place it
        # can: the handler is already on the space closest to their own
        # goal, so there is nowhere to push them back to.
        cog = build_cog()
        game = build_game()
        cog.games[game.game_id] = game
        match = cog.engine.initialize_standard_match(game)

        handler = match.home.field_players[0]
        zone, space_index = match.own_goal_restart_space(TeamSide.HOME)
        match.move_meeple(handler, zone, space_index)
        match.ball.possession = TeamSide.HOME
        match.set_ball_space(zone, space_index)
        match.active_player_id = handler
        challenger = match.visiting.field_players[0]
        match.move_meeple(challenger, zone, space_index)
        match.challenger_id = challenger
        game.match_state = match.to_dict()

        interaction = build_interaction()
        with suppressed_cog_saves(), mock.patch(
            "random.randint",
        ) as randint:
            await cog.resolve_pressure(interaction, game, match)

        randint.assert_not_called()
        self.assertIsInstance(last_view(interaction), OwnGoalRollView)
        self.assertTrue(cog.engine.load_match_state(game).pending_own_goal)

    async def test_what_the_roll_owes_is_persisted(self) -> None:
        cog, game, match = self.build()

        with suppressed_cog_saves():
            await cog.begin_own_goal_roll(
                build_interaction(), game, match, distance_moved=2,
            )

        # The clock cost of the maneuver that risked the own goal is
        # spent by the roll whichever way it goes, so it has to outlive
        # the wait for the click.
        saved = cog.engine.load_match_state(game)
        self.assertTrue(saved.pending_own_goal)
        self.assertEqual(saved.pending_own_goal_distance, 2)

    async def test_the_prompt_is_what_a_restart_comes_back_to(self) -> None:
        cog, game, match = self.build()
        # The Pressure that risked it is still the live maneuver, so
        # everything below the own goal in pending_turn_view is set.
        match.challenger_id = match.visiting.field_players[0]
        match.offense_maneuver = "dribble_advance"
        match.defense_maneuver = "pressure"
        match.pending_own_goal = True

        view, _ = cog.pending_turn_view(game.game_id, match)
        self.assertIsInstance(view, OwnGoalRollView)

    async def roll(self, cog, game, match, roll: int) -> SimpleNamespace:
        interaction = build_interaction()
        view = OwnGoalRollView(cog, game.game_id)
        with suppressed_cog_saves(), mock.patch(
            "random.randint", return_value=roll,
        ), mock.patch("cogs.d12ball.effects.render_own_goal_dice"), mock.patch(
            "discord.File",
        ):
            await view.roll(interaction)
        return interaction

    async def test_the_button_rolls_and_resolves(self) -> None:
        cog, game, match = self.build()
        match.pending_own_goal = True
        match.pending_own_goal_distance = 1
        game.match_state = match.to_dict()

        await self.roll(cog, game, match, 12)

        # Avoided is a new play too, same as conceded -- see
        # test_a_conceded_own_goal_still_restarts_play.
        cog.begin_run_back.assert_awaited_once()
        self.assertTrue(cog.begin_run_back.await_args.kwargs["new_play"])
        self.assertTrue(cog.begin_run_back.await_args.kwargs["turnover_occurred"])
        self.assertFalse(cog.engine.load_match_state(game).pending_own_goal)
        self.assertEqual(cog.engine.load_match_state(game).ball.speed, 1)

    async def test_a_conceded_own_goal_still_restarts_play(self) -> None:
        cog, game, match = self.build()
        match.pending_own_goal = True
        match.pending_own_goal_distance = 1
        game.match_state = match.to_dict()

        await self.roll(cog, game, match, 1)

        cog.begin_run_back.assert_awaited_once()
        self.assertTrue(cog.begin_run_back.await_args.kwargs["new_play"])

    async def test_a_second_click_is_refused(self) -> None:
        cog, game, match = self.build()
        match.pending_own_goal = False
        game.match_state = match.to_dict()

        interaction = build_interaction()
        view = OwnGoalRollView(cog, game.game_id)
        await view.roll(interaction)

        interaction.response.send_message.assert_awaited_once()
        self.assertIn(
            "no longer active",
            interaction.response.send_message.await_args.args[0],
        )
        cog.finish_maneuver_resolution.assert_not_awaited()


class InjuryTestPromptTests(unittest.IsolatedAsyncioTestCase):
    """
    A contest hands out its injury tests and then has to wait for them.
    What it was going to do next rides on the queue, because by then
    nothing else in the match still says what it was.
    """

    def build_skill_test(self) -> tuple[D12Ball, D12BallGame, MatchState, str]:
        cog = build_cog()
        game = build_game()
        cog.games[game.game_id] = game
        match = cog.engine.initialize_standard_match(game)

        offense = match.home.field_players[0]
        match.active_player_id = offense
        match.challenger_id = match.visiting.field_players[0]
        match.offense_maneuver = "low_pass"
        match.defense_maneuver = "deflect"
        exhaust(match, offense)
        game.match_state = match.to_dict()
        return cog, game, match, offense

    async def resolve_skill_test(self, cog, game) -> SimpleNamespace:
        interaction = build_interaction()
        view = SkillTestView(cog, game.game_id)
        with suppressed_view_saves(), suppressed_cog_saves(), mock.patch(
            "random.randint", side_effect=[12, 1],
        ), mock.patch("cogs.d12ball_views.base.render_skill_test_dice"), mock.patch(
            "discord.File",
        ):
            await view.roll(interaction)
        return interaction

    async def roll_injury(self, cog, game, player_id, roll):
        interaction = build_interaction()
        view = InjuryTestView(cog, game.game_id, player_id)
        with suppressed_cog_saves(), mock.patch(
            "random.randint", return_value=roll,
        ), mock.patch("cogs.d12ball.core.render_injury_test_die"), mock.patch(
            "discord.File",
        ):
            await view.roll(interaction)
        return interaction

    async def test_the_effect_waits_behind_the_test(self) -> None:
        cog, game, _, offense = self.build_skill_test()

        interaction = await self.resolve_skill_test(cog, game)

        self.assertIsInstance(last_view(interaction), InjuryTestView)
        cog.begin_effect_resolution.assert_not_awaited()
        saved = cog.engine.load_match_state(game)
        self.assertEqual(saved.pending_injury_tests, [offense])
        self.assertEqual(
            saved.pending_injury_resume,
            {"kind": "maneuver_effect", "winner_key": "low_pass"},
        )

    async def test_the_effect_follows_the_roll(self) -> None:
        cog, game, _, offense = self.build_skill_test()
        await self.resolve_skill_test(cog, game)

        await self.roll_injury(cog, game, offense, 12)

        cog.begin_effect_resolution.assert_awaited_once()
        self.assertEqual(
            effect_winner_key(cog.begin_effect_resolution.await_args),
            "low_pass",
        )
        saved = cog.engine.load_match_state(game)
        self.assertEqual(saved.pending_injury_tests, [])
        self.assertIsNone(saved.pending_injury_resume)

    async def test_a_failed_roll_injures_the_player(self) -> None:
        cog, game, _, offense = self.build_skill_test()
        await self.resolve_skill_test(cog, game)

        await self.roll_injury(cog, game, offense, 1)

        self.assertIn(offense, cog.engine.load_match_state(game).injured)
        cog.begin_effect_resolution.assert_awaited_once()

    async def test_both_participants_are_asked_one_at_a_time(self) -> None:
        cog, game, match, offense = self.build_skill_test()
        defense = match.challenger_id
        exhaust(match, defense)
        game.match_state = match.to_dict()

        await self.resolve_skill_test(cog, game)
        self.assertEqual(
            cog.engine.load_match_state(game).pending_injury_tests,
            [offense, defense],
        )

        # The first roll buys the second prompt, not the effect.
        await self.roll_injury(cog, game, offense, 12)
        cog.begin_effect_resolution.assert_not_awaited()
        self.assertEqual(
            cog.engine.load_match_state(game).pending_injury_tests, [defense],
        )

        await self.roll_injury(cog, game, defense, 12)
        cog.begin_effect_resolution.assert_awaited_once()

    async def test_the_first_prompt_cannot_roll_the_second_test(self) -> None:
        cog, game, match, offense = self.build_skill_test()
        defense = match.challenger_id
        exhaust(match, defense)
        game.match_state = match.to_dict()

        await self.resolve_skill_test(cog, game)
        await self.roll_injury(cog, game, offense, 12)

        # The offense's prompt is still in the channel, above the one
        # the defense owes; clicking it again must not stand in for it.
        interaction = await self.roll_injury(cog, game, offense, 12)
        interaction.response.send_message.assert_awaited_once()
        self.assertEqual(
            cog.engine.load_match_state(game).pending_injury_tests, [defense],
        )

    async def test_an_injured_player_is_never_asked(self) -> None:
        cog, game, match, offense = self.build_skill_test()
        match.injured.add(offense)
        game.match_state = match.to_dict()

        interaction = await self.resolve_skill_test(cog, game)

        self.assertNotIsInstance(last_view(interaction), InjuryTestView)
        cog.begin_effect_resolution.assert_awaited_once()
        self.assertEqual(cog.engine.load_match_state(game).pending_injury_tests, [])

    async def test_the_prompt_is_what_a_restart_comes_back_to(self) -> None:
        cog, game, _, offense = self.build_skill_test()
        await self.resolve_skill_test(cog, game)

        # Everything the skill test set is still set underneath this,
        # so the maneuver's own branches would answer first if the
        # queue were not checked ahead of them.
        view, _ = cog.pending_turn_view(
            game.game_id, cog.engine.load_match_state(game),
        )
        self.assertIsInstance(view, InjuryTestView)
        self.assertEqual(view.player_id, offense)


class ContestInjuryResumeTests(unittest.IsolatedAsyncioTestCase):
    """
    A loose ball (and the long High Pass that borrows its machinery)
    resumes into a run back rather than an effect, and carries the two
    arguments that run back needs through the queue -- nothing left in
    the match still says what they were once the contest is cleared.
    """

    def build(self) -> tuple[D12Ball, D12BallGame, MatchState, str]:
        cog = build_cog()
        game = build_game()
        cog.games[game.game_id] = game
        match = cog.engine.initialize_standard_match(game)

        offense = match.home.field_players[0]
        match.move_meeple(offense, match.ball.zone, match.ball.space_index)
        match.active_player_id = offense
        match.pending_loose_ball = True
        match.pending_loose_ball_distance = 3
        match.loose_ball_offense_player = offense
        match.loose_ball_defense_player = match.visiting.field_players[0]
        exhaust(match, offense)
        game.match_state = match.to_dict()
        return cog, game, match, offense

    async def test_the_run_back_waits_and_keeps_its_arguments(self) -> None:
        cog, game, _, offense = self.build()

        interaction = build_interaction()
        view = LooseBallSkillTestView(cog, game.game_id)
        with suppressed_view_saves(), suppressed_cog_saves(), mock.patch(
            "random.randint", side_effect=[12, 1],
        ), mock.patch("cogs.d12ball_views.base.render_skill_test_dice"), mock.patch(
            "discord.File",
        ):
            await view.roll(interaction)

        cog.begin_run_back.assert_not_awaited()
        self.assertEqual(
            cog.engine.load_match_state(game).pending_injury_resume,
            {
                "kind": "run_back",
                "distance_moved": 3,
                "turnover_occurred": False,
            },
        )

        injury = InjuryTestView(cog, game.game_id, offense)
        with suppressed_cog_saves(), mock.patch(
            "random.randint", return_value=12,
        ), mock.patch("cogs.d12ball.core.render_injury_test_die"), mock.patch(
            "discord.File",
        ):
            await injury.roll(build_interaction())

        cog.begin_run_back.assert_awaited_once()
        self.assertEqual(
            cog.begin_run_back.await_args.kwargs["distance_moved"], 3,
        )
        self.assertFalse(
            cog.begin_run_back.await_args.kwargs["turnover_occurred"],
        )


if __name__ == "__main__":
    unittest.main()
