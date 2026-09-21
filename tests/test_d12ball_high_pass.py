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
from cogs.d12ball_helpers import HIGH_PASS_CONTEST_HEADLINE, contest_noun
from cogs.d12ball_views import (
    HighPassChoiceView,
    LooseBallSkillTestView,
    ScoreAttemptView,
    SetUpAttemptChoiceView,
)
from d12ball.components import (
    MatchState,
    PlayerRole,
    TeamSide,
    Zone,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.ai import DinkyAI
from d12ball.engine import RulesEngine
from d12ball.game import D12BallGame, Team
from roster import display_name, fielded
from flow_stubs import driver_reaches_cog_stubs
from save_patches import suppressed_cog_saves, suppressed_full_image_links, suppressed_view_saves


def build_cog() -> D12Ball:
    cog = object.__new__(D12Ball)
    cog.games = {}
    cog.player_catalog = load_player_catalog()
    cog.maneuver_catalog = load_maneuver_catalog()
    cog.basic_ruleset = load_basic_ruleset()
    cog.engine = RulesEngine(
        cog.player_catalog, cog.basic_ruleset, cog.maneuver_catalog, {},
    )
    cog.team_emojis = {}
    cog.refresh_match_image = mock.AsyncMock()
    cog.announce_board_update = mock.AsyncMock()
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
        self.enterContext(driver_reaches_cog_stubs(cog))
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
            cog.engine.get_player_definition(receiver)
        ).offense
        defense_skill = cog.player_catalog.effective_profile(
            cog.engine.get_player_definition(challenger)
        ).defense
        # One total is pinned level with the other, then nudged.
        offense_roll = 6
        defense_roll = offense_roll + offense_skill - defense_skill
        self.assertTrue(2 <= defense_roll <= 11)
        if winner == "offense":
            return [offense_roll, defense_roll - 1]
        return [offense_roll, defense_roll + 1]

    def test_the_prompts_name_the_contest_they_belong_to(self) -> None:
        """
        Three nouns, because three different things share this
        machinery -- and **"loose ball" is reserved for the one arrival
        it is true of** (the author, 2026-08-26): a ball on a space
        nobody was standing on.
        """
        cog, game, match, _, _ = self.build_contest(is_high_pass=True)
        self.assertEqual(contest_noun(match), "high pass")
        self.assertEqual(
            [item.label for item in LooseBallSkillTestView(
                cog, game.game_id,
            ).children],
            ["Roll for the high pass"],
        )

        # Both sides were already standing there, so it is a contest
        # for the ball and never was loose.
        cog, game, match, _, _ = self.build_contest(is_high_pass=False)
        self.assertEqual(contest_noun(match), "ball")
        self.assertEqual(
            [item.label for item in LooseBallSkillTestView(
                cog, game.game_id,
            ).children],
            ["Roll for the ball"],
        )

        # The ball came down on an empty space, so it is loose --
        # asserted on a match whose contest began before anybody was
        # sent, which is the position the noun is recorded from.
        cog, game, match, _, _ = self.build_contest(is_high_pass=False)
        # Walked off the space rather than taken off the board, or the
        # save would not validate.
        for occupant in list(
            match.board.spaces[match.ball.zone][match.ball.space_index]
        ):
            match.move_meeple(occupant, Zone.HOME_GOAL, 0)
        match.begin_loose_ball(2)
        game.match_state = match.to_dict()
        self.assertEqual(contest_noun(match), "loose ball")
        self.assertEqual(
            [item.label for item in LooseBallSkillTestView(
                cog, game.game_id,
            ).children],
            ["Roll for the loose ball"],
        )

    async def test_only_a_genuine_loose_ball_is_announced_with_a_board(
        self,
    ) -> None:
        """
        The other half of the same distinction. A loose ball is lying
        in a space nothing has named, so it is announced with the board
        under it; a High Pass is on a receiver both coaches watched
        catch it, and paying an upload to say so would say nothing.
        """
        cog, game, match, receiver, _ = self.build_contest(
            is_high_pass=True,
        )
        match.reset_maneuver()
        interaction = build_interaction()

        with suppressed_cog_saves():
            await cog.begin_loose_ball(
                interaction, game, match, 3,
                headline=HIGH_PASS_CONTEST_HEADLINE,
                is_high_pass=True,
            )

        cog.announce_board_update.assert_not_awaited()
        self.assertIn(
            HIGH_PASS_CONTEST_HEADLINE,
            interaction.followup.send.await_args_list[0].args[0],
        )

    async def test_a_receiver_who_keeps_the_ball_runs_nobody_back(
        self,
    ) -> None:
        cog, game, match, receiver, challenger = self.build_contest(
            is_high_pass=True,
        )
        possession_before = match.ball.possession

        view = LooseBallSkillTestView(cog, game.game_id)
        with suppressed_view_saves(), suppressed_cog_saves(), mock.patch(
            "random.randint",
            side_effect=self.rolls_for(cog, receiver, challenger, "offense"),
        ), mock.patch("cogs.d12ball_views.base.render_skill_test_dice"), mock.patch(
            "discord.File",
        ):
            await view.roll(build_interaction())

        saved = cog.engine.load_match_state(game)
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
        with suppressed_view_saves(), suppressed_cog_saves(), mock.patch(
            "random.randint",
            side_effect=self.rolls_for(cog, receiver, challenger, "defense"),
        ), mock.patch("cogs.d12ball_views.base.render_skill_test_dice"), mock.patch(
            "discord.File",
        ):
            await view.roll(build_interaction())

        saved = cog.engine.load_match_state(game)
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

        # The wrapper persists after the step since Phase 4 --
        # principle 9's transition rule.
        with suppressed_cog_saves():
            await cog.decline_scoring_attempt(
                build_interaction(), game, match, 2,
            )
        cog.begin_loose_ball.assert_not_awaited()
        cog.finish_maneuver_resolution.assert_awaited_once()

    async def test_declining_an_overshot_long_pass_falls_into_the_contest(
        self,
    ) -> None:
        # 2026-08-10: the shot an overshoot offers is the bonus, not a
        # replacement -- a pass of 3 or 4 still owes the contest it
        # would have owed unclamped, so declining lands there.
        cog, game, match, receiver, _ = self.build_contest(
            is_high_pass=True,
        )
        cog.begin_loose_ball = mock.AsyncMock()

        view = SetUpAttemptChoiceView(
            cog, game.game_id, receiver, 2, contest_on_decline=True,
        )
        self.assertEqual(
            [item.label for item in view.children][1],
            "Decline -- contest for the ball",
        )

        with suppressed_cog_saves():
            await cog.decline_scoring_attempt(
                build_interaction(), game, match, 2, contest=True,
            )
        cog.finish_maneuver_resolution.assert_not_awaited()
        cog.begin_loose_ball.assert_awaited_once()
        _, kwargs = cog.begin_loose_ball.await_args
        self.assertEqual(kwargs["headline"], HIGH_PASS_CONTEST_HEADLINE)
        self.assertTrue(kwargs["is_high_pass"])

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
        with suppressed_view_saves(), suppressed_cog_saves(), mock.patch(
            "random.randint",
            side_effect=self.rolls_for(cog, receiver, challenger, "defense"),
        ), mock.patch("cogs.d12ball_views.base.render_skill_test_dice"), mock.patch(
            "discord.File",
        ):
            await view.roll(build_interaction())

        saved = cog.engine.load_match_state(game)
        self.assertEqual(saved.ball.possession, possession_before)
        self.assertFalse(saved.pending_run_back)

    async def test_an_overshot_receiver_pays_the_speed_modifier_instead(
        self,
    ) -> None:
        # 2026-08-10: a High Pass that ran out of field arrives too
        # fast to settle, so the modifier that would have helped the
        # receiver keep it counts against them -- in the contest a
        # declined set-up falls into, exactly as it would have in the
        # shot. These rolls win by 1 without any modifier at all, so
        # only a negative one loses them.
        cog, game, match, receiver, challenger = self.build_fast_contest(
            is_high_pass=True,
        )
        match.pending_high_pass_overshoot = True
        self.assertEqual(match.ball_speed_modifier(), -2)
        game.match_state = match.to_dict()
        possession_before = match.ball.possession

        view = LooseBallSkillTestView(cog, game.game_id)
        with suppressed_view_saves(), suppressed_cog_saves(), mock.patch(
            "random.randint",
            side_effect=self.rolls_for(cog, receiver, challenger, "offense"),
        ), mock.patch("cogs.d12ball_views.base.render_skill_test_dice"), mock.patch(
            "discord.File",
        ):
            await view.roll(build_interaction())

        saved = cog.engine.load_match_state(game)
        self.assertNotEqual(saved.ball.possession, possession_before)
        self.assertTrue(saved.pending_run_back)

    async def test_a_loose_ball_gives_nobody_the_speed_modifier(self) -> None:
        # The other half of that rule: a genuine loose ball is nobody's
        # yet, so the same rolls on the same fast ball go the other way.
        cog, game, match, receiver, challenger = self.build_fast_contest(
            is_high_pass=False,
        )
        possession_before = match.ball.possession

        view = LooseBallSkillTestView(cog, game.game_id)
        with suppressed_view_saves(), suppressed_cog_saves(), mock.patch(
            "random.randint",
            side_effect=self.rolls_for(cog, receiver, challenger, "defense"),
        ), mock.patch("cogs.d12ball_views.base.render_skill_test_dice"), mock.patch(
            "discord.File",
        ):
            await view.roll(build_interaction())

        self.assertNotEqual(
            cog.engine.load_match_state(game).ball.possession, possession_before,
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
        with suppressed_view_saves(), suppressed_cog_saves(), mock.patch(
            "random.randint",
            side_effect=self.rolls_for(cog, receiver, challenger, "offense"),
        ), mock.patch("cogs.d12ball_views.base.render_skill_test_dice"), mock.patch(
            "discord.File",
        ):
            await view.roll(build_interaction())

        self.assertFalse(cog.engine.load_match_state(game).pending_run_back)
        cog.announce_run_back.assert_not_awaited()
        cog.finish_maneuver_resolution.assert_awaited_once()


class HighPassDistanceMenuTests(unittest.IsolatedAsyncioTestCase):
    """
    What the distance prompt offers (2026-08-10): only distances that
    fit on the field, because a longer pass landing where a shorter
    one already would is the same pass at a disadvantage. See
    D12Ball.high_pass_distance_options and "High Pass" in
    docs/living-rules.md.

    Board 7, so the flat indices are 0..6 and the home side attacks
    toward 6: midfield is flat 2-4 and the visitors' goal 5-6.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    def build(self, zone: Zone, space: int, role: PlayerRole):
        cog = build_cog()
        self.enterContext(driver_reaches_cog_stubs(cog))
        cog.apply_high_pass = mock.AsyncMock()
        cog.engine.user_controls_possession = mock.Mock(return_value=True)
        game = build_game()
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
        )
        match.ball.possession = TeamSide.HOME
        match.set_ball_space(zone, space)
        match.active_player_id = next(
            player_id for player_id in match.home.field_players
            if self.catalog.player_by_id(player_id).role == role
        )
        match.move_meeple(match.active_player_id, zone, space)
        game.match_state = match.to_dict()
        cog.games[game.game_id] = game
        return cog, game, match

    def test_a_fullback_is_not_offered_four_it_cannot_throw(self) -> None:
        # Three spaces of room: the 4 lands where the 3 does, so only
        # the 3 is offered. The ability is still real one space back.
        # The two receivers are named by role -- the label's wording is
        # what is under test, not which card is standing there.
        cog, game, match = self.build(Zone.MIDFIELD, 1, PlayerRole.FULLBACK)
        winger = display_name(fielded(match, PlayerRole.WINGER))
        striker = display_name(fielded(match, PlayerRole.STRIKER))
        self.assertEqual(
            [item.label for item in HighPassChoiceView(
                cog, game.game_id,
            ).children],
            [
                f"2 spaces (V1-{winger} [WG])",
                f"3 spaces (V2-{striker} [SK])",
            ],
        )

        cog, game, _ = self.build(Zone.MIDFIELD, 0, PlayerRole.FULLBACK)
        self.assertEqual(
            [item.label for item in HighPassChoiceView(
                cog, game.game_id,
            ).children],
            [
                # The space is named even where nobody is standing
                # on it: a pass landing there is loose, so which
                # space it is is half the coach's answer.
                "2 spaces (M3, no teammate)",
                f"3 spaces (V1-{winger} [WG])",
                f"4 spaces (Fullback ability) (V2-{striker} [SK])",
            ],
        )

    def test_nobody_is_offered_three_when_only_two_fits(self) -> None:
        cog, game, match = self.build(Zone.MIDFIELD, 2, PlayerRole.DEFENDER)
        striker = display_name(fielded(match, PlayerRole.STRIKER))
        self.assertEqual(
            [item.label for item in HighPassChoiceView(
                cog, game.game_id,
            ).children],
            [f"2 spaces (V2-{striker} [SK])"],
        )

    async def test_a_click_on_a_distance_no_longer_on_offer_is_refused(
        self,
    ) -> None:
        # The buttons carry no message id, so an older prompt still in
        # the channel dispatches here. The menu is read off the match
        # rather than off the view for exactly that reason.
        cog, game, match = self.build(
            Zone.MIDFIELD, 0, PlayerRole.FULLBACK,
        )
        view = HighPassChoiceView(cog, game.game_id)
        self.assertEqual(len(view.children), 3)

        # A later turn: the ball, and whoever is handling it, have
        # moved two spaces closer to the end of the field.
        match.set_ball_space(Zone.MIDFIELD, 2)
        match.move_meeple(match.active_player_id, Zone.MIDFIELD, 2)
        game.match_state = match.to_dict()

        interaction = build_interaction()
        await view.choose(interaction, 3)

        cog.apply_high_pass.assert_not_awaited()
        interaction.response.edit_message.assert_not_awaited()
        message, = interaction.response.send_message.await_args.args
        self.assertIn("runs off the end of the field", message)
        self.assertTrue(
            interaction.response.send_message.await_args.kwargs["ephemeral"]
        )

    async def test_the_prompt_carries_the_field_strip(self) -> None:
        # How far to throw is a question about which teammate the pass
        # reaches, how much field is left, and who is waiting where it
        # lands -- and the board has scrolled away by this point in a
        # turn. It rides on the prompt rather than on a message of its
        # own so the click can take it away again.
        cog, game, match = self.build(
            Zone.MIDFIELD, 0, PlayerRole.FULLBACK,
        )
        cog.build_field_file = mock.AsyncMock(return_value="field.png")
        interaction = build_interaction()

        with suppressed_full_image_links(), suppressed_cog_saves():
            await cog.resolve_high_pass(interaction, game, match)

        sent = interaction.followup.send.await_args
        self.assertEqual(sent.kwargs["file"], "field.png")
        cog.build_field_file.assert_awaited_once_with(game)

    async def test_choosing_takes_the_field_strip_away(self) -> None:
        # It shows the ball where it was *before* the pass, so
        # leaving it under the answer would put a stale position in the
        # channel for the rest of the game.
        cog, game, _ = self.build(Zone.MIDFIELD, 0, PlayerRole.FULLBACK)
        view = HighPassChoiceView(cog, game.game_id)
        interaction = build_interaction()

        await view.choose(interaction, 3)

        cog.apply_high_pass.assert_awaited_once()
        self.assertEqual(
            interaction.response.edit_message.await_args.kwargs["attachments"],
            [],
        )


class OvershootShotPaysTheSpeedModifierTests(unittest.IsolatedAsyncioTestCase):
    """
    The shot an overshoot sets up, from the other end: the ball speed
    modifier is subtracted from the attempt rather than added to it
    (2026-08-10). Only the arithmetic is under test, and all of it is
    in the rows handed to the dice render, so the roll is stopped
    there -- everything past it is the goal-or-miss aftermath.

    See MatchState.ball_speed_modifier and "Ball speed" in
    docs/living-rules.md.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    async def roll_shot(self, overshot: bool):
        cog = build_cog()
        self.enterContext(driver_reaches_cog_stubs(cog))
        cog.apply_exhaustion = mock.Mock(return_value="")
        # Nobody in the way, so the attacker's row is the whole test.
        cog.engine.intervening_defenders = mock.Mock(return_value=[])
        game = build_game()
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
        )
        match.active_player_id = match.setup_for_side(
            match.ball.possession
        ).field_players[0]
        match.move_meeple(
            match.active_player_id, match.ball.zone, match.ball.space_index,
        )
        match.pending_action = "shoot"
        match.ball.speed = 6  # a modifier of 3, either way round
        match.pending_high_pass_overshoot = overshot
        game.match_state = match.to_dict()
        cog.games[game.game_id] = game

        entries = []

        class Stop(Exception):
            pass

        def capture(rows):
            entries.append(rows)
            raise Stop

        view = ScoreAttemptView(cog, game.game_id)
        with suppressed_view_saves(), suppressed_cog_saves(), mock.patch(
            "random.randint", return_value=7,
        ), mock.patch(
            "cogs.d12ball_views.base.render_skill_test_dice", side_effect=capture,
        ):
            with self.assertRaises(Stop):
                await view.roll(build_interaction())
        return entries[0][0]

    async def test_an_ordinary_shot_adds_it(self) -> None:
        _, _, _, detail, total, _, _ = await self.roll_shot(overshot=False)

        self.assertIn("+3 ball speed modifier", detail)
        self.assertNotIn("-3 ball speed modifier", detail)
        skill = int(detail[1].removeprefix("Offensive skill +"))
        self.assertEqual(total, 7 + skill + 3)

    async def test_an_overshot_set_up_subtracts_it(self) -> None:
        _, _, _, detail, total, _, _ = await self.roll_shot(overshot=True)

        self.assertIn("-3 ball speed modifier", detail)
        skill = int(detail[1].removeprefix("Offensive skill +"))
        self.assertEqual(total, 7 + skill - 3)


class PasserNeverReceivesTheirOwnPassTests(unittest.IsolatedAsyncioTestCase):
    """
    A High Pass thrown from the final space moves the ball nowhere and
    overshoots like any other -- but the passer is not who it reaches
    (2026-08-12). It is the only position where the question comes up:
    a High Pass moves the ball and not the handler, so nowhere else is
    the passer still standing on it when it lands.

    See D12Ball.high_pass_receiver_candidates and "High Pass" in
    docs/living-rules.md.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    def build_last_space_pass(self, *, teammate: bool):
        """
        The ball on the space closest to the goal the offense attacks,
        with the passer standing on it -- and a teammate beside them or
        not. The passer goes down first, so the landing space's
        occupant list starts with the one player who may not receive.
        """
        cog = build_cog()
        self.enterContext(driver_reaches_cog_stubs(cog))
        cog.offer_scoring_attempt_choice = mock.AsyncMock()
        # Only this fixture reaches apply_high_pass_out's begin_run_back
        # call (the passer-alone, no-teammate case) -- every other test
        # in this file needs it real, so it is not in the shared
        # build_cog().
        cog.begin_run_back = mock.AsyncMock()
        game = build_game()
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
        )
        offense = match.ball.possession
        zone, space = match.own_goal_restart_space(match.defending_side())
        match.set_ball_space(zone, space)
        # The standard deal already stands two of the offense in the
        # zone they attack, so clear the landing space before staffing
        # it -- otherwise "the passer alone" is nothing of the kind.
        back = match.own_goal_restart_space(offense)
        for occupant in list(match.board.spaces[zone][space]):
            match.move_meeple(occupant, *back)

        field = match.setup_for_side(offense).field_players
        passer, mate = field[0], (field[1] if teammate else None)
        match.move_meeple(passer, zone, space)
        match.active_player_id = passer
        if mate:
            match.move_meeple(mate, zone, space)

        # The premise: from here every distance is the same pass, and
        # the shortest already runs out of field.
        self.assertTrue(match.high_pass_distance_is_moot(offense))

        game.match_state = match.to_dict()
        cog.games[game.game_id] = game
        return cog, game, match, passer, mate

    async def apply(self, cog, game, match):
        with suppressed_cog_saves():
            await cog.apply_high_pass(
                build_interaction(), game, match, 2,
            )

    async def test_a_teammate_on_the_space_receives_the_overshoot(
        self,
    ) -> None:
        cog, game, match, passer, mate = self.build_last_space_pass(
            teammate=True,
        )

        await self.apply(cog, game, match)

        cog.offer_scoring_attempt_choice.assert_awaited_once()
        kwargs = cog.offer_scoring_attempt_choice.await_args.kwargs
        self.assertEqual(kwargs["shooter_id"], mate)
        self.assertNotEqual(kwargs["shooter_id"], passer)
        # Still an overshoot: the modifier turns around and declining
        # the shot owes the contest.
        self.assertTrue(kwargs["contest_on_decline"])
        self.assertTrue(match.pending_high_pass_overshoot)
        self.assertEqual(match.ball_carrier_id, mate)

    async def test_the_passer_alone_sees_the_ball_go_out(
        self,
    ) -> None:
        # 2026-08-24: a throw with nowhere left to put it and nobody to
        # put it to is no longer a free ride for the passer -- it goes
        # out exactly as a Setup Pass with no legal destination does.
        # See apply_high_pass_out.
        cog, game, match, passer, _ = self.build_last_space_pass(
            teammate=False,
        )
        possession_before = match.ball.possession
        space_before = (match.ball.zone, match.ball.space_index)

        await self.apply(cog, game, match)

        cog.offer_scoring_attempt_choice.assert_not_awaited()
        cog.finish_maneuver_resolution.assert_not_awaited()
        cog.begin_run_back.assert_awaited_once()
        kwargs = cog.begin_run_back.await_args.kwargs
        self.assertTrue(kwargs["new_play"])
        self.assertFalse(match.pending_high_pass_overshoot)
        # Possession has already flipped and the ball reset to speed 1
        # by the time begin_run_back is called -- apply_setup_pass_out
        # does the same, before its own begin_run_back call.
        self.assertNotEqual(match.ball.possession, possession_before)
        self.assertEqual((match.ball.zone, match.ball.space_index),
                         space_before)
        self.assertEqual(match.ball.speed, 1)
        self.assertIsNone(match.ball_carrier_id)
        self.assertTrue(match.pending_ball_recovery)
        self.assertNotIn(passer, match.eligible_ball_handlers())

    async def test_the_result_does_not_report_a_move_of_zero_spaces(
        self,
    ) -> None:
        cog, game, match, _, _ = self.build_last_space_pass(teammate=False)

        await self.apply(cog, game, match)

        lead_in = cog.begin_run_back.await_args.kwargs["lead_in"]
        self.assertNotIn("0 spaces", lead_in)
        self.assertIn("last space", lead_in)

    async def test_a_throw_that_moves_nothing_still_costs_its_flat_time(
        self,
    ) -> None:
        # High Pass's time cost is a flat 2 space minutes regardless of
        # distance (2026-08-16), so the one throw that moves the ball
        # nowhere is not free, and is not discounted either.
        cog, game, match, _, _ = self.build_last_space_pass(teammate=False)

        await self.apply(cog, game, match)

        kwargs = cog.begin_run_back.await_args.kwargs
        self.assertEqual(kwargs["distance_moved"], 2)

    async def test_the_minute_follows_the_set_up_the_throw_offers(
        self,
    ) -> None:
        # The clock is charged wherever the turn ends up, so the
        # set-up -- and the contest behind a decline -- carry High
        # Pass's flat 2 too, not just the branch that resolves quietly.
        cog, game, match, _, _ = self.build_last_space_pass(teammate=True)

        await self.apply(cog, game, match)

        kwargs = cog.offer_scoring_attempt_choice.await_args.kwargs
        self.assertEqual(kwargs["distance_moved"], 2)

    async def test_the_contest_behind_it_names_the_same_receiver(
        self,
    ) -> None:
        # Declining the set-up lands in the long-pass contest, which
        # has to put up the player the shot was offered to rather than
        # whoever the occupant list starts with -- the passer goes down
        # first there, and never receives their own pass.
        #
        # The contest stopped forcing a contestant on 2026-08-18: both
        # sides simply put up whoever of theirs is on the ball. So the
        # exclusion now has to live in that pool, which is what this
        # asserts.
        cog, game, match, passer, mate = self.build_last_space_pass(
            teammate=True,
        )
        offense = match.ball.possession
        self.assertEqual(
            match.board.spaces[match.ball.zone][match.ball.space_index][0],
            passer,
        )

        match.begin_loose_ball(0, is_high_pass=True)

        self.assertEqual(match.loose_ball_occupants(offense), [mate])
        self.assertEqual(
            cog.engine.loose_ball_candidates(match, offense), [mate],
        )


class DinkyAimsAtSomebodyTests(unittest.TestCase):
    """
    Dinky throws to the furthest teammate it can reach rather than
    simply the furthest -- the author, 2026-08-18. A pass landing where
    the offense has nobody is a loose ball, so maximizing distance was
    maximizing how often it gave the ball away.

    Board 7 again: flat 0..6, home attacking toward 6.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    def dinky(self) -> DinkyAI:
        return DinkyAI(self.catalog, load_maneuver_catalog())

    def build(self, zone: Zone, space: int):
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
        )
        match.ball.possession = TeamSide.HOME
        match.set_ball_space(zone, space)
        match.active_player_id = match.home.field_players[0]
        match.move_meeple(match.active_player_id, zone, space)
        # Clear the home side off the field ahead of the ball, so each
        # test says for itself who is standing where.
        for player_id in match.home.field_players:
            if player_id != match.active_player_id:
                match.board.remove_meeple(player_id)
        return match

    def test_it_takes_the_furthest_pass_that_reaches_a_teammate(
        self,
    ) -> None:
        match = self.build(Zone.HOME_GOAL, 0)  # flat 0
        mate = match.home.field_players[1]
        match.board.place_meeple(mate, Zone.MIDFIELD, 0)  # flat 2
        self.assertEqual(
            match.high_pass_receivers_at(TeamSide.HOME, 2), [mate],
        )

        self.assertEqual(
            self.dinky().choose_high_pass_distance(match, [2, 3, 4]), 2,
        )

    def test_the_furthest_of_several_reachable_teammates_wins(self) -> None:
        match = self.build(Zone.HOME_GOAL, 0)
        near, far = match.home.field_players[1], match.home.field_players[2]
        match.board.place_meeple(near, Zone.MIDFIELD, 0)   # flat 2
        match.board.place_meeple(far, Zone.MIDFIELD, 1)    # flat 3

        self.assertEqual(
            self.dinky().choose_high_pass_distance(match, [2, 3, 4]), 3,
        )

    def test_with_nobody_reachable_it_still_throws_the_longest(self) -> None:
        # Not a rule, a fallback: the maneuver has been chosen and a
        # distance has to come back, so it keeps the old answer.
        match = self.build(Zone.HOME_GOAL, 0)

        self.assertEqual(
            self.dinky().choose_high_pass_distance(match, [2, 3, 4]), 4,
        )

    def test_the_passer_is_not_a_teammate_to_aim_at(self) -> None:
        # A pass clamped back onto the passer reaches nobody, and the
        # lookahead has to say so or Dinky would aim at itself.
        match = self.build(Zone.HOME_GOAL, 0)
        self.assertEqual(
            match.high_pass_receivers_at(TeamSide.HOME, 0), [],
        )


if __name__ == "__main__":
    unittest.main()
