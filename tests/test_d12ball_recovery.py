"""
Getting a game moving again after a restart, and ending one that
cannot be.

A restart re-arms exactly one message per game -- the one recorded in
`turn_message_id` -- so a game can come back with no working button
anywhere in its channel. `/d12ball resume` re-posts whatever the saved
state is waiting on, and `/d12ball abandon_game` ends the ones nobody
is going to finish. See "Recovering a stuck game" in docs/design/recovery.md.

The one thing worth guarding hardest is that `pending_turn_view` stays
the *single* reading of "what is this match waiting on?": startup
re-attaches what it returns, and resume posts it. A second copy of that
branch chain is how the two come to disagree.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

import discord

from cogs.d12ball import D12Ball
from cogs.d12ball_boards import BoardRefresher
from cogs.d12ball_views import (
    BallHandlerSelectionView,
    BallRecoveryView,
    CoachingHubView,
    CoachingOfferView,
    HalftimeExtraTokenView,
    ManeuverActionPromptView,
    PlayerActionView,
    RunBackChoiceView,
    RunBackPlayerChoiceView,
    SafeView,
    ScoreAttemptView,
    SkillTestView,
)
from d12ball.ai import build_ai_strategies
from d12ball.components import (
    CoachingOccasion,
    MatchState,
    TeamSide,
    Zone,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.engine import RulesEngine
from d12ball.game import D12BallGame, Formation, GameStatus, Team
from save_patches import suppressed_cog_saves


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
    cog.boards = BoardRefresher(cog)
    cog.refresh_match_image = mock.AsyncMock()
    cog.send_turn_prompt = mock.AsyncMock()
    cog.coaching_file = mock.AsyncMock(return_value=object())
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


def build_interaction(user_id: int = 111, **user_fields) -> SimpleNamespace:
    return SimpleNamespace(
        channel_id=2,
        channel=SimpleNamespace(
            send=mock.AsyncMock(return_value=SimpleNamespace(id=999)),
        ),
        guild=None,
        user=SimpleNamespace(
            id=user_id, display_name="One", **user_fields,
        ),
        response=SimpleNamespace(
            defer=mock.AsyncMock(), is_done=lambda: True,
        ),
        followup=SimpleNamespace(
            send=mock.AsyncMock(return_value=SimpleNamespace(id=999)),
        ),
    )


class PendingTurnViewTests(unittest.TestCase):
    """
    The branch chain startup restores from and resume posts. Only the
    orderings that have actually caused trouble are asserted here --
    the ones where two flags are set at once and the wrong branch wins.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    def build(self) -> tuple[D12Ball, MatchState]:
        cog = build_cog()
        cog.games["g1"] = build_game()
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
            home_formation=Formation.TWO_TWO_TWO,
        )
        return cog, match

    def test_no_ball_handler_yet_asks_who_takes_the_ball(self) -> None:
        cog, match = self.build()

        view, _ = cog.pending_turn_view("g1", match)

        self.assertIsInstance(view, BallHandlerSelectionView)

    def test_setup_beats_the_missing_ball_handler(self) -> None:
        # Setup leaves active_player_id None, so the kickoff branch
        # would claim it if it were checked first.
        cog, match = self.build()
        match.pending_setup_stage = "coaching_home"
        match.open_coaching_window(TeamSide.HOME, CoachingOccasion.SETUP)

        view, _ = cog.pending_turn_view("g1", match)

        self.assertIsInstance(view, CoachingHubView)

    def test_halftime_beats_the_missing_ball_handler(self) -> None:
        cog, match = self.build()
        match.pending_halftime_stage = "extra_token_visiting"

        view, _ = cog.pending_turn_view("g1", match)

        self.assertIsInstance(view, HalftimeExtraTokenView)

    def test_an_old_halftime_stage_still_resolves(self) -> None:
        # LEGACY_HALFTIME_STAGES: a game saved under the two-stage
        # halftime outlives the change that renamed things.
        cog, match = self.build()
        match.pending_halftime_stage = "reposition_visiting"

        view, _ = cog.pending_turn_view("g1", match)

        self.assertIsInstance(view, CoachingHubView)

    def test_an_undeclared_window_comes_back_as_the_offer(self) -> None:
        cog, match = self.build()
        match.active_player_id = match.eligible_ball_handlers()[0]
        match.open_coaching_window(TeamSide.HOME, CoachingOccasion.NEW_PLAY)

        view, _ = cog.pending_turn_view("g1", match)

        self.assertIsInstance(view, CoachingOfferView)

    def test_a_declared_window_comes_back_as_the_hub(self) -> None:
        cog, match = self.build()
        match.active_player_id = match.eligible_ball_handlers()[0]
        match.open_coaching_window(TeamSide.HOME, CoachingOccasion.NEW_PLAY)
        match.declare_coaching()

        view, _ = cog.pending_turn_view("g1", match)

        self.assertIsInstance(view, CoachingHubView)

    def test_a_new_plays_window_beats_the_shot_that_opened_it(self) -> None:
        """
        The exact state a restart mid-window leaves behind, and the one
        that had /d12ball offensive_choice answering "a score attempt
        is already in progress": `pending_action` stays "shoot" for the
        whole post-goal sequence, since only reset_maneuver clears it.
        """
        cog, match = self.build()
        match.active_player_id = match.eligible_ball_handlers()[0]
        match.pending_action = "shoot"
        match.pending_run_back = True
        match.pending_kickoff_fill = True
        match.open_coaching_window(
            TeamSide.VISITING, CoachingOccasion.NEW_PLAY,
        )

        view, _ = cog.pending_turn_view("g1", match)

        self.assertIsInstance(view, CoachingOfferView)

    def test_a_shot_with_nothing_else_pending_asks_for_the_roll(
        self,
    ) -> None:
        cog, match = self.build()
        match.active_player_id = match.eligible_ball_handlers()[0]
        match.pending_action = "shoot"

        view, _ = cog.pending_turn_view("g1", match)

        self.assertIsInstance(view, ScoreAttemptView)

    def test_an_out_of_bounds_pickup_names_the_space(self) -> None:
        cog, match = self.build()
        match.active_player_id = match.eligible_ball_handlers()[0]
        match.pending_ball_recovery = True

        view, ask = cog.pending_turn_view("g1", match)

        self.assertIsInstance(view, BallRecoveryView)
        self.assertIn("pick it up", ask)

    def test_a_run_back_comes_back_as_the_space_it_is_owed(self) -> None:
        cog, match = self.build()
        match.active_player_id = match.eligible_ball_handlers()[0]
        stray = match.home.zones[Zone.MIDFIELD][0]
        match.board.remove_meeple(stray)
        match.board.place_meeple(stray, Zone.VISITORS_GOAL, 0)
        match.pending_run_back = True

        view, ask = cog.pending_turn_view("g1", match)

        self.assertIsInstance(view, RunBackChoiceView)
        self.assertIn("runs back to", ask)

    def test_a_run_back_stack_comes_back_as_the_player_choice(self) -> None:
        # Which of two players on one space runs back is the coach's
        # (2026-08-17), and it is not persisted -- it lives on the view
        # -- so a restart has to put the question back rather than the
        # answer. Read off the position, the same way the cascade
        # reads it.
        cog, match = self.build()
        match.active_player_id = match.eligible_ball_handlers()[0]
        for player_id in match.home.zones[Zone.MIDFIELD]:
            match.board.remove_meeple(player_id)
            match.board.place_meeple(player_id, Zone.MIDFIELD, 0)
        match.pending_run_back = True

        view, ask = cog.pending_turn_view("g1", match)

        self.assertIsInstance(view, RunBackPlayerChoiceView)
        self.assertIn("which", ask)

    def test_a_settled_maneuver_owing_a_roll_asks_for_it(self) -> None:
        cog, match = self.build()
        match.active_player_id = match.eligible_ball_handlers()[0]
        match.challenger_id = match.visiting.field_players[0]
        # A tie on the cards, so a skill test is owed and no effect is
        # pending yet.
        match.offense_maneuver = "low_pass"
        match.defense_maneuver = "deflect"

        view, _ = cog.pending_turn_view("g1", match)

        self.assertIsInstance(view, SkillTestView)

    def test_an_ordinary_turn_asks_for_an_action(self) -> None:
        cog, match = self.build()
        match.active_player_id = match.eligible_ball_handlers()[0]

        view, _ = cog.pending_turn_view("g1", match)

        self.assertIsInstance(view, PlayerActionView)


class ManeuverMenuRestoreTests(unittest.IsolatedAsyncioTestCase):
    """
    The maneuver pick used to be the game's one ephemeral view, and so
    the one a restart could not re-attach to its message: it was
    registered without a message id instead, and discord.py dispatched
    it by custom_id alone.

    It is a public prompt now -- the cards are public information and
    what stays secret is the pick, which the ephemeral *reply* hides
    (see `ManeuverActionPromptView`). So there is nothing special left
    to do: the prompt is on `turn_message_id` and `on_ready` re-attaches
    it like every other view.

    The None-keyed fallback is still load-bearing for the shootout's two
    menus, and is exercised against a real ViewStore over there rather
    than asserted about -- see `ShootoutMenuRestoreTests`.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    def build(self) -> tuple[D12Ball, D12BallGame, MatchState]:
        cog = build_cog()
        cog.bot = SimpleNamespace(add_view=mock.Mock())
        game = build_game()
        cog.games[game.game_id] = game
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
            home_formation=Formation.TWO_TWO_TWO,
        )
        match.active_player_id = match.eligible_ball_handlers()[0]
        match.challenger_id = match.visiting.field_players[0]
        game.match_state = match.to_dict()
        return cog, game, match

    def test_a_restart_mid_maneuver_restores_the_prompt(self) -> None:
        cog, game, match = self.build()

        turn_view, _ = cog.pending_turn_view(game.game_id, match)

        self.assertIsInstance(turn_view, ManeuverActionPromptView)
        self.assertEqual(turn_view.sides, ("offense", "defense"))

    def test_the_prompt_is_persistent_so_add_view_will_take_it(
        self,
    ) -> None:
        # on_ready hands it to add_view with turn_message_id, which
        # refuses a view that can time out.
        cog, game, match = self.build()

        turn_view, _ = cog.pending_turn_view(game.game_id, match)

        self.assertTrue(turn_view.is_persistent())

    def test_a_side_that_has_already_picked_keeps_its_buttons(
        self,
    ) -> None:
        """
        The message is never edited once it is up, so the buttons a
        restored view dispatches have to match the buttons sitting on
        it -- taking a picked side's row away would leave those clicks
        answered by nothing. `pick` refuses the second click instead.
        """
        cog, game, match = self.build()
        match.offense_maneuver = "low_pass"
        game.match_state = match.to_dict()

        turn_view, _ = cog.pending_turn_view(game.game_id, match)

        self.assertEqual(turn_view.sides, ("offense", "defense"))
        self.assertIn(
            f"d12ball:maneuver_pick:{game.game_id}:offense:low_pass",
            [item.custom_id for item in turn_view.children],
        )

    def test_an_uncontested_maneuver_has_no_defensive_buttons(self) -> None:
        cog, game, match = self.build()
        match.challenger_id = None
        match.maneuver_uncontested = True
        game.match_state = match.to_dict()

        turn_view, _ = cog.pending_turn_view(game.game_id, match)

        self.assertEqual(turn_view.sides, ("offense",))


class ResumeDispatchTests(unittest.IsolatedAsyncioTestCase):
    """
    Which of the two things a resume does: hand the state back to the
    routine that drives it, or post the view it owes.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    def build(self) -> tuple[D12Ball, D12BallGame, MatchState]:
        cog = build_cog()
        game = build_game()
        cog.games[game.game_id] = game
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
            home_formation=Formation.TWO_TWO_TWO,
        )
        game.match_state = match.to_dict()
        cog.continue_run_back = mock.AsyncMock()
        cog.begin_ball_recovery = mock.AsyncMock()
        cog.advance_setup_stage = mock.AsyncMock()
        cog.advance_halftime_stage = mock.AsyncMock()
        return cog, game, match

    async def test_a_stranded_run_back_is_driven_on_not_re_asked(
        self,
    ) -> None:
        """
        The hardest state a restart leaves: the cascade's next step was
        the bot's own, so there is no button anywhere to press.
        """
        cog, game, match = self.build()
        match.active_player_id = match.eligible_ball_handlers()[0]
        match.pending_run_back = True
        interaction = build_interaction()

        with suppressed_cog_saves():
            waiting_on = await cog.resume_pending_prompt(
                interaction, game, match,
            )

        cog.continue_run_back.assert_awaited_once()
        self.assertEqual(waiting_on, "the run back")
        interaction.followup.send.assert_not_awaited()

    async def test_an_out_of_bounds_pickup_is_driven_on(self) -> None:
        cog, game, match = self.build()
        match.active_player_id = match.eligible_ball_handlers()[0]
        match.pending_ball_recovery = True

        with suppressed_cog_saves():
            await cog.resume_pending_prompt(
                build_interaction(), game, match,
            )

        cog.begin_ball_recovery.assert_awaited_once()

    async def test_an_open_window_is_re_posted_not_re_opened(self) -> None:
        """
        A resume must not hand a coach back the substitutions they have
        already spent, which going through begin_substitution_window
        would: it calls open_coaching_window.
        """
        cog, game, match = self.build()
        match.active_player_id = match.eligible_ball_handlers()[0]
        match.open_coaching_window(
            TeamSide.HOME, CoachingOccasion.HALFTIME,
        )
        match.declare_coaching()
        match.pending_coaching_substitutions = 2
        remaining_before = match.substitutions_remaining()
        interaction = build_interaction()

        with suppressed_cog_saves():
            waiting_on = await cog.resume_pending_prompt(
                interaction, game, match,
            )

        self.assertEqual(waiting_on, "the open Coaching Choice")
        self.assertEqual(match.pending_coaching_substitutions, 2)
        self.assertEqual(match.substitutions_remaining(), remaining_before)
        _, kwargs = interaction.channel.send.await_args
        self.assertIsInstance(kwargs["view"], CoachingHubView)
        # The image goes back up with it: exhaustion counts and the
        # benches are drawn nowhere else.
        cog.coaching_file.assert_awaited_once()
        self.assertEqual(game.turn_message_id, 999)

    async def test_an_ai_window_is_run_not_re_posted(self) -> None:
        # An AI's window is a routine that runs to completion, so a
        # restart in the middle of one leaves nobody to click anything.
        cog, game, match = self.build()
        game.player_2_id = None
        cog.run_ai_substitution_window = mock.AsyncMock()
        match.active_player_id = match.eligible_ball_handlers()[0]
        match.open_coaching_window(
            TeamSide.VISITING, CoachingOccasion.NEW_PLAY,
        )

        with suppressed_cog_saves():
            waiting_on = await cog.resume_pending_prompt(
                build_interaction(), game, match,
            )

        cog.run_ai_substitution_window.assert_awaited_once()
        self.assertEqual(waiting_on, "the AI's Coaching Choice")

    async def test_a_setup_window_is_re_posted_not_advanced(self) -> None:
        # advance_setup_stage would re-open the window; the open one is
        # checked first precisely so it doesn't.
        cog, game, match = self.build()
        match.pending_setup_stage = "coaching_home"
        match.open_coaching_window(TeamSide.HOME, CoachingOccasion.SETUP)

        with suppressed_cog_saves():
            await cog.resume_pending_prompt(
                build_interaction(), game, match,
            )

        cog.advance_setup_stage.assert_not_awaited()

    async def test_a_setup_stage_with_no_window_open_is_advanced(
        self,
    ) -> None:
        # The process died between setting the stage and sending the
        # window: nothing to re-post, so the sequence is re-driven.
        cog, game, match = self.build()
        match.pending_setup_stage = "coaching_home"

        with suppressed_cog_saves():
            waiting_on = await cog.resume_pending_prompt(
                build_interaction(), game, match,
            )

        cog.advance_setup_stage.assert_awaited_once()
        self.assertEqual(waiting_on, "the pre-kickoff Coaching Choice")

    async def test_a_halftime_stage_with_no_window_open_is_advanced(
        self,
    ) -> None:
        cog, game, match = self.build()
        match.pending_halftime_stage = "extra_token_visiting"

        with suppressed_cog_saves():
            await cog.resume_pending_prompt(
                build_interaction(), game, match,
            )

        cog.advance_halftime_stage.assert_awaited_once()

    async def test_anything_else_posts_the_view_it_owes(self) -> None:
        cog, game, match = self.build()
        match.active_player_id = match.eligible_ball_handlers()[0]
        match.pending_action = "shoot"
        interaction = build_interaction()

        with suppressed_cog_saves():
            await cog.resume_pending_prompt(interaction, game, match)

        _, kwargs = interaction.channel.send.await_args
        self.assertIsInstance(kwargs["view"], ScoreAttemptView)
        # Recorded, so the next restart re-arms the message this just
        # posted rather than the dead one it replaced.
        self.assertEqual(game.turn_message_id, 999)


class ResumeCommandTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    def build(self, **game_overrides):
        cog = build_cog()
        game = build_game(**game_overrides)
        cog.games[game.game_id] = game
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
            home_formation=Formation.TWO_TWO_TWO,
        )
        match.active_player_id = match.eligible_ball_handlers()[0]
        game.match_state = match.to_dict()
        cog.resume_pending_prompt = mock.AsyncMock(
            return_value="the run back",
        )
        return cog, game, match

    async def run_resume(self, cog, interaction, force: bool = False):
        with suppressed_cog_saves():
            await D12Ball.resume.callback(cog, interaction, force=force)

    async def test_a_player_may_resume_their_own_game(self) -> None:
        cog, _, _ = self.build()
        interaction = build_interaction(user_id=222)

        await self.run_resume(cog, interaction)

        cog.resume_pending_prompt.assert_awaited_once()

    async def test_a_bystander_may_not(self) -> None:
        cog, _, _ = self.build()
        interaction = build_interaction(
            user_id=333,
            guild_permissions=SimpleNamespace(manage_channels=False),
        )

        await self.run_resume(cog, interaction)

        cog.resume_pending_prompt.assert_not_awaited()
        message, _ = interaction.followup.send.await_args
        self.assertIn("Only a player in this game", message[0])

    async def test_a_channel_manager_may(self) -> None:
        cog, _, _ = self.build()
        interaction = build_interaction(
            user_id=333,
            guild_permissions=SimpleNamespace(manage_channels=True),
        )

        await self.run_resume(cog, interaction)

        cog.resume_pending_prompt.assert_awaited_once()

    async def test_a_finished_game_has_nothing_to_resume(self) -> None:
        cog, _, _ = self.build(status=GameStatus.FINISHED)

        await self.run_resume(cog, build_interaction())

        cog.resume_pending_prompt.assert_not_awaited()

    async def test_force_clears_the_turn_and_re_asks(self) -> None:
        cog, game, match = self.build()
        match.pending_action = "shoot"
        match.pending_run_back = True
        match.open_coaching_window(
            TeamSide.HOME, CoachingOccasion.NEW_PLAY,
        )
        game.match_state = match.to_dict()

        await self.run_resume(cog, build_interaction(), force=True)

        resumed = cog.engine.load_match_state(game)
        self.assertIsNone(resumed.pending_action)
        self.assertFalse(resumed.pending_run_back)
        self.assertIsNone(resumed.pending_coaching_side)
        cog.send_turn_prompt.assert_awaited_once()
        cog.resume_pending_prompt.assert_not_awaited()

    async def test_force_will_not_skip_setup_or_halftime(self) -> None:
        """
        Those are real positions in the game rather than a turn gone
        wrong, and clearing them would drop a coach's window on the
        floor. A plain resume walks them on instead.
        """
        for stage_field in ("pending_setup_stage", "pending_halftime_stage"):
            with self.subTest(stage_field):
                cog, game, match = self.build()
                setattr(match, stage_field, "coaching_home")
                game.match_state = match.to_dict()

                await self.run_resume(cog, build_interaction(), force=True)

                cog.send_turn_prompt.assert_not_awaited()
                self.assertIsNotNone(
                    getattr(cog.engine.load_match_state(game), stage_field),
                )

    async def test_force_will_not_skip_a_ceded_ball(self) -> None:
        """
        Same reason, plus one of its own: the ball has already changed
        hands, so a cleared turn would ask the receiving side to act
        with nobody standing on it.
        """
        cog, game, match = self.build()
        match.pending_time_out = True
        game.match_state = match.to_dict()

        await self.run_resume(cog, build_interaction(), force=True)

        cog.send_turn_prompt.assert_not_awaited()
        self.assertTrue(cog.engine.load_match_state(game).pending_time_out)

    async def test_a_state_that_will_not_load_says_so(self) -> None:
        cog, _, _ = self.build()
        cog.resume_pending_prompt.side_effect = ValueError("nope")
        interaction = build_interaction()

        await self.run_resume(cog, interaction)

        message, _ = interaction.followup.send.await_args
        self.assertIn("could not resume", message[0])
        self.assertIn("force:true", message[0])


class AbandonGameTests(unittest.IsolatedAsyncioTestCase):
    def build(self, **game_overrides):
        cog = build_cog()
        game = build_game(turn_message_id=555, message_id=444)
        for field, value in game_overrides.items():
            setattr(game, field, value)
        cog.games[game.game_id] = game
        cog.channel = SimpleNamespace(
            send=mock.AsyncMock(),
            get_partial_message=mock.Mock(
                return_value=SimpleNamespace(edit=mock.AsyncMock()),
            ),
        )
        cog.fetch_game_channel = mock.AsyncMock(return_value=cog.channel)
        cog.move_channel_to_archive = mock.AsyncMock()
        return cog, game

    async def run_abandon(self, cog, interaction, confirm: str = "confirm"):
        with suppressed_cog_saves():
            await D12Ball.abandon_game.callback(cog, interaction, confirm)

    async def test_confirming_archives_and_ends_the_game(self) -> None:
        cog, game = self.build()

        await self.run_abandon(cog, build_interaction())

        cog.move_channel_to_archive.assert_awaited_once_with(cog.channel)
        self.assertEqual(game.status, GameStatus.FINISHED)
        # The record stays, so the PBD number stays taken.
        self.assertIn(game.game_id, cog.games)

    async def test_the_channel_is_told_not_just_the_caller(self) -> None:
        cog, _ = self.build()

        await self.run_abandon(cog, build_interaction())

        message, _ = cog.channel.send.await_args
        self.assertIn("Game abandoned", message[0])

    async def test_the_message_ids_are_cleared(self) -> None:
        """
        Startup restores views off `message_id` and `turn_message_id`
        and reads nothing about status, so a game that is over has to
        stop pointing at its prompts.
        """
        cog, game = self.build()

        await self.run_abandon(cog, build_interaction())

        self.assertIsNone(game.message_id)
        self.assertIsNone(game.turn_message_id)

    async def test_a_pending_board_refresh_is_cancelled(self) -> None:
        cog, game = self.build()
        task = mock.Mock()
        cog.boards.state(game.game_id).task = task

        await self.run_abandon(cog, build_interaction())

        task.cancel.assert_called_once()
        self.assertIsNone(cog.boards.state(game.game_id).task)

    async def test_without_the_confirm_word_nothing_happens(self) -> None:
        cog, game = self.build()
        interaction = build_interaction()

        await self.run_abandon(cog, interaction, confirm="yes")

        cog.move_channel_to_archive.assert_not_awaited()
        self.assertEqual(game.status, GameStatus.IN_PROGRESS)
        message, _ = interaction.followup.send.await_args
        self.assertIn("cancelled", message[0])

    async def test_a_bystander_may_not_abandon(self) -> None:
        cog, game = self.build()
        interaction = build_interaction(
            user_id=333,
            guild_permissions=SimpleNamespace(manage_channels=False),
        )

        await self.run_abandon(cog, interaction)

        cog.move_channel_to_archive.assert_not_awaited()
        self.assertEqual(game.status, GameStatus.IN_PROGRESS)

    async def test_a_failed_archive_leaves_the_game_alone(self) -> None:
        """
        The channel move is the only step that can fail, so it goes
        first: a half-ended game is worse than one still stuck.
        """
        cog, game = self.build()
        cog.move_channel_to_archive.side_effect = discord.HTTPException(
            SimpleNamespace(status=403, reason="nope"), "nope",
        )
        interaction = build_interaction()

        with self.assertLogs("cogs.d12ball_helpers", level="ERROR"):
            await self.run_abandon(cog, interaction)

        self.assertEqual(game.status, GameStatus.IN_PROGRESS)
        self.assertEqual(game.turn_message_id, 555)
        message, _ = interaction.followup.send.await_args
        self.assertIn("could not abandon", message[0])

    async def test_a_game_still_in_setup_can_be_abandoned(self) -> None:
        # finish_game refuses one; a game gets stuck before kickoff as
        # easily as after it.
        cog, game = self.build(status=GameStatus.SETUP)

        await self.run_abandon(cog, build_interaction())

        self.assertEqual(game.status, GameStatus.FINISHED)

    async def test_a_finished_game_is_refused(self) -> None:
        cog, game = self.build(status=GameStatus.FINISHED)

        await self.run_abandon(cog, build_interaction())

        cog.move_channel_to_archive.assert_not_awaited()


class UnexpectedErrorNoticeTests(unittest.IsolatedAsyncioTestCase):
    """
    What a coach is told when a click or a command raises something
    nobody expected. It used to be "please try again" and nothing
    else, which is only ever right for a dropped connection: a bug in
    the flow raises on every click alike, and the turn it stranded is
    exactly what /d12ball resume is for. Asserted through the two
    handlers rather than against the constant, since the wording is
    only useful if it actually reaches the coach.
    """

    def build_interaction(self) -> SimpleNamespace:
        return SimpleNamespace(
            response=SimpleNamespace(
                is_done=mock.Mock(return_value=True),
                send_message=mock.AsyncMock(),
            ),
            followup=SimpleNamespace(send=mock.AsyncMock()),
            command=None,
        )

    async def test_a_failed_click_points_at_resume(self) -> None:
        interaction = self.build_interaction()
        view = SafeView()

        # ERROR is also what puts it in #logs, which is the only place
        # the traceback the coach is being asked to report exists.
        with self.assertLogs("cogs.d12ball_helpers", level="ERROR"):
            await view.on_error(interaction, RuntimeError("boom"), None)

        (message,), kwargs = interaction.followup.send.await_args
        self.assertIn("/d12ball resume", message)
        self.assertTrue(kwargs["ephemeral"])

    async def test_a_failed_command_points_at_resume(self) -> None:
        interaction = self.build_interaction()

        with self.assertLogs("cogs.d12ball_helpers", level="ERROR"):
            await D12Ball.cog_app_command_error(
                build_cog(), interaction, RuntimeError("boom"),
            )

        (message,), _ = interaction.followup.send.await_args
        self.assertIn("/d12ball resume", message)


if __name__ == "__main__":
    unittest.main()
