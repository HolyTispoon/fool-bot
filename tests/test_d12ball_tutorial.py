"""
The scripted opening a tutorial game plays -- see `d12ball/tutorial.py`
and "The tutorial" in CLAUDE.md.

Three things here are worth guarding, and they are the three the script
cannot check for itself:

- **A beat's position produces the outcome its lesson promises.** The
  text says "Dribble Advance beats Block Deflect" and "this one goes to
  the dice"; the maneuver catalog is imported data, so those claims are
  asserted against `ManeuverCatalog.resolve` rather than trusted.
- **Every beat plays the same on either side of the board.** Nothing
  forces the coin toss, so a spec written from a coach's own goal
  forward has to mirror -- and the shot at beat 5 has to be the same
  shot whichever end it is taken at.
- **The step counter cannot skip a beat.** `send_turn_prompt` is what
  advances it and the recovery commands call that without a turn having
  been played, which is exactly the way a lesson would go missing.

The lesson *text* is deliberately not asserted. It is prose, it will be
revised, and a test quoting it would only ever break on a reword.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

from cogs.d12ball import D12Ball
from cogs.d12ball_views import (
    HighPassChoiceView,
    ManeuverActionSelectView,
    PlayerActionView,
)
from d12ball import tutorial
from d12ball.ai import build_ai_strategies
from d12ball.components import (
    MatchState,
    PlayerRole,
    TeamSide,
    Zone,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.engine import RulesEngine
from d12ball.game import D12BallGame, Formation, GameStatus, Team


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
    cog.refresh_match_image = mock.AsyncMock()
    return cog


def build_game(**overrides) -> D12BallGame:
    fields = dict(
        game_id="g1",
        game_number=1,
        guild_id=1,
        channel_id=2,
        message_id=None,
        player_1_id=111,
        player_2_id=None,
        player_1_team=Team.ORANGE,
        player_2_team=Team.PURPLE,
        home_player_number=1,
        visiting_player_number=2,
        status=GameStatus.IN_PROGRESS,
        tutorial=True,
        tutorial_step=tutorial.FIRST_STEP,
    )
    fields.update(overrides)
    return D12BallGame(**fields)


def build_match(catalog, rules) -> MatchState:
    return MatchState.standard(
        catalog=catalog,
        ruleset=rules,
        board_size=7,
        home_team=Team.ORANGE,
        visiting_team=Team.PURPLE,
        home_formation=Formation.TWO_TWO_TWO,
    )


def build_interaction(user_id: int = 111) -> SimpleNamespace:
    return SimpleNamespace(
        channel_id=2,
        guild=None,
        user=SimpleNamespace(id=user_id, display_name="One"),
        response=SimpleNamespace(
            defer=mock.AsyncMock(), send_message=mock.AsyncMock(),
        ),
        followup=SimpleNamespace(
            send=mock.AsyncMock(return_value=SimpleNamespace(id=999)),
        ),
    )


BOTH_SIDES = (TeamSide.HOME, TeamSide.VISITING)


class TutorialScriptTests(unittest.TestCase):
    """The beats as data: do they say what they claim to say."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()
        cls.maneuvers = load_maneuver_catalog()

    def test_every_card_a_beat_names_is_in_the_catalog(self) -> None:
        # The maneuvers are imported from a spreadsheet, so this is the
        # check that a rename upstream fails the cog load rather than
        # railing a coach onto a button that no longer exists.
        tutorial.validate_script(self.maneuvers)

    def test_each_beat_lands_the_outcome_it_teaches(self) -> None:
        # The five lessons in order: a decisive win for the coach, a
        # tie into the skill test, the steal that takes the ball off
        # them, the Pressure they defend with, and the High Pass that
        # sets the shot up. Read off the ranking rather than restated,
        # because the ranking is the data and the lesson is the claim.
        expected = {
            1: "offense",   # Dribble Advance over Block Deflect
            2: "tie",       # Low Pass and Block Deflect, both rank 1
            3: "defense",   # Steal Intercept over Low Pass
            4: "defense",   # the coach's Pressure over Dribble Advance
            5: "offense",   # High Pass over Steal Intercept
        }
        for beat in tutorial.BEATS:
            with self.subTest(beat=beat.step):
                offense, defense = (
                    (beat.player_maneuver, beat.dinky_maneuver)
                    if beat.player_has_ball
                    else (beat.dinky_maneuver, beat.player_maneuver)
                )
                self.assertEqual(
                    self.maneuvers.resolve(offense, defense),
                    expected[beat.step],
                )

    def test_the_coach_wins_every_beat_that_is_not_the_lesson_in_losing(
        self,
    ) -> None:
        # Beat 3 is the one the coach is meant to lose -- it is the
        # turnover lesson. Any other beat resolving against them would
        # be a script that teaches the opposite of what it says.
        for beat in tutorial.BEATS:
            outcome = self.maneuvers.resolve(
                *(
                    (beat.player_maneuver, beat.dinky_maneuver)
                    if beat.player_has_ball
                    else (beat.dinky_maneuver, beat.player_maneuver)
                )
            )
            coach_side = "offense" if beat.player_has_ball else "defense"
            with self.subTest(beat=beat.step):
                if beat.step == 3:
                    self.assertNotEqual(outcome, coach_side)
                elif outcome != "tie":
                    self.assertEqual(outcome, coach_side)

    def test_only_one_card_is_ever_offered(self) -> None:
        for side in BOTH_SIDES:
            for beat in tutorial.BEATS:
                menu = "offense" if beat.player_has_ball else "defense"
                with self.subTest(beat=beat.step, side=side.value):
                    self.assertEqual(
                        tutorial.allowed_maneuvers(beat, side, menu),
                        (beat.player_maneuver,),
                    )

    def test_dinky_never_picks_out_of_the_coachs_own_menu(self) -> None:
        # The two halves of the menu are keyed "offense"/"defense" and
        # the coach is on one of them; a beat handing Dinky a card for
        # the coach's half would overwrite the pick they are being
        # railed onto.
        for beat in tutorial.BEATS:
            coach_menu = "offense" if beat.player_has_ball else "defense"
            with self.subTest(beat=beat.step):
                self.assertIsNone(beat.dinky_maneuver_for(coach_menu))
                self.assertEqual(
                    beat.dinky_maneuver_for(
                        "defense" if beat.player_has_ball else "offense"
                    ),
                    beat.dinky_maneuver,
                )


class TutorialPositionTests(unittest.TestCase):
    """
    The board a beat sets. Every one is checked on both sides, because
    the toss is not forced and a spec is mirrored on the way in.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    def staged(self, beat, player_side) -> MatchState:
        match = build_match(self.catalog, self.rules)
        tutorial.apply_beat(match, self.catalog, beat, player_side)
        return match

    def test_every_beat_leaves_a_match_that_validates(self) -> None:
        for side in BOTH_SIDES:
            for beat in tutorial.BEATS:
                with self.subTest(beat=beat.step, side=side.value):
                    self.staged(beat, side).validate(self.catalog)

    def test_the_ball_is_with_the_side_the_beat_says(self) -> None:
        for side in BOTH_SIDES:
            for beat in tutorial.BEATS:
                match = self.staged(beat, side)
                with self.subTest(beat=beat.step, side=side.value):
                    self.assertEqual(
                        match.ball.possession == side, beat.player_has_ball,
                    )

    def test_the_handler_is_never_a_choice(self) -> None:
        # A beat with two of the coach's players on the ball would open
        # with a handler prompt the lesson does not mention.
        for side in BOTH_SIDES:
            for beat in tutorial.BEATS:
                match = self.staged(beat, side)
                with self.subTest(beat=beat.step, side=side.value):
                    self.assertEqual(len(match.eligible_ball_handlers()), 1)

    def test_a_beat_records_its_position_as_the_coachs_arrangement(
        self,
    ) -> None:
        # A new play restores to `assigned_positions`, and the goal at
        # the end of beat 5 is a new play -- so without this the reset
        # after it would put both sides back on the *deal* rather than
        # on the position the tutorial has been playing from.
        for side in BOTH_SIDES:
            match = self.staged(tutorial.BEATS[4], side)
            for player_id in match.setup_for_side(side).field_players:
                zone, space_index = match.board.meeple_position(player_id)
                with self.subTest(side=side.value, player=player_id):
                    self.assertEqual(
                        match.assigned_positions[player_id],
                        [zone.value, space_index],
                    )

    def test_a_beat_clears_the_exhaustion_the_last_one_left(self) -> None:
        match = build_match(self.catalog, self.rules)
        somebody = match.home.field_players[0]
        match.exhaustion[somebody] = 3
        match.exhausted.add(somebody)

        tutorial.apply_beat(
            match, self.catalog, tutorial.BEATS[1], TeamSide.HOME,
        )

        self.assertEqual(match.exhaustion, {})
        self.assertEqual(match.exhausted, set())

    def test_beat_two_makes_the_defense_walk_somebody_in(self) -> None:
        # The lesson is the walk-in and what it costs, so the ball has
        # to start on a space the defense has nobody on -- otherwise
        # they challenge for free and the lesson describes nothing.
        for side in BOTH_SIDES:
            for beat in (tutorial.BEATS[1], tutorial.BEATS[2]):
                match = self.staged(beat, side)
                with self.subTest(beat=beat.step, side=side.value):
                    self.assertEqual(match.automatic_challengers(), [])
                    self.assertTrue(match.eligible_challengers())

    def test_beat_one_and_four_challenge_off_the_ball_for_free(self) -> None:
        # Their lessons both say the challenger was already standing
        # there, which is what makes the challenge free and unasked.
        for side in BOTH_SIDES:
            for beat in (tutorial.BEATS[0], tutorial.BEATS[3]):
                match = self.staged(beat, side)
                with self.subTest(beat=beat.step, side=side.value):
                    self.assertEqual(len(match.automatic_challengers()), 1)

    def test_beat_five_puts_the_striker_two_spaces_away_and_in_range(
        self,
    ) -> None:
        beat = tutorial.BEATS[4]
        for side in BOTH_SIDES:
            match = self.staged(beat, side)
            striker = tutorial.card_for_role(
                match, self.catalog, side, PlayerRole.STRIKER,
            )
            ball_flat = match.board.flat_index(
                match.ball.zone, match.ball.space_index,
            )
            landing = match.relative_flat_index(
                ball_flat, match.ball.possession, beat.high_pass_distance,
            )
            with self.subTest(side=side.value):
                zone, space_index = match.board.meeple_position(striker)
                self.assertEqual(
                    match.board.flat_index(zone, space_index), landing,
                )
                self.assertTrue(
                    match.board.is_in_shooting_range(side, landing)
                )

    def test_beat_five_leaves_one_halved_defender_in_the_lane(self) -> None:
        # The shot is meant to be near-certain without a die being
        # rigged: a lone defender off the ball contributes half their
        # skill, which is what makes the striker's +9 against +3. A
        # second defender in the lane would quietly drop it to 75%.
        beat = tutorial.BEATS[4]
        for side in BOTH_SIDES:
            match = self.staged(beat, side)
            ball_flat = match.board.flat_index(
                match.ball.zone, match.ball.space_index,
            )
            landing = match.relative_flat_index(
                ball_flat, match.ball.possession, beat.high_pass_distance,
            )
            zone, space_index = match.board.position_at_flat_index(landing)
            match.ball.zone, match.ball.space_index = zone, space_index

            defenders = match.defenders_between_ball_and_goal()
            with self.subTest(side=side.value):
                self.assertEqual(len(defenders), 1)
                self.assertFalse(defenders[0][1], "should not be on the ball")

    def test_beat_five_offers_the_distance_it_rails(self) -> None:
        # The rail disables everything but 2. If 2 were not on offer
        # the coach would be left with nothing clickable at all.
        beat = tutorial.BEATS[4]
        for side in BOTH_SIDES:
            match = self.staged(beat, side)
            with self.subTest(side=side.value):
                self.assertIn(
                    beat.high_pass_distance,
                    match.high_pass_distances(match.ball.possession, 3),
                )

    def test_every_beat_covers_the_coachs_own_kickoff_space(self) -> None:
        # `coaching_finish_refusal` holds a coach in a window until
        # somebody of theirs is on it, and beat 5's goal opens one --
        # so a beat that empties the space would strand them there.
        for side in BOTH_SIDES:
            for beat in tutorial.BEATS:
                match = self.staged(beat, side)
                occupants = match.board.spaces[Zone.MIDFIELD][
                    match.kickoff_space_for(side)
                ]
                with self.subTest(beat=beat.step, side=side.value):
                    self.assertTrue(
                        set(occupants)
                        & set(match.setup_for_side(side).field_players),
                        "nobody of this side is on their kickoff space",
                    )


class TutorialStagingTests(unittest.IsolatedAsyncioTestCase):
    """
    Counting the beats. `send_turn_prompt` is called once a turn, which
    is what advances the script -- but the recovery commands call it
    too, and a beat skipped there is a lesson nobody sees.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    def build(self, **overrides):
        cog = build_cog()
        game = build_game(**overrides)
        game.match_state = build_match(self.catalog, self.rules).to_dict()
        cog.games[game.game_id] = game
        return cog, game

    async def stage(self, cog, game):
        interaction = build_interaction()
        with mock.patch("cogs.d12ball.save_games"):
            await cog.stage_tutorial_beat(interaction, game)
        return interaction

    async def test_the_first_staging_does_not_advance(self) -> None:
        cog, game = self.build()

        await self.stage(cog, game)

        self.assertEqual(game.tutorial_step, tutorial.FIRST_STEP)
        self.assertTrue(game.tutorial_staged)

    async def test_a_played_turn_advances_to_the_next_beat(self) -> None:
        cog, game = self.build()

        await self.stage(cog, game)
        await self.stage(cog, game)

        self.assertEqual(game.tutorial_step, tutorial.FIRST_STEP + 1)

    async def test_re_entering_an_unplayed_beat_skips_nothing(self) -> None:
        # `/d12ball resume force:true` sends a turn prompt without a
        # turn having been played. Staging twice with the flag cleared
        # in between is that path, and it must not count as two turns.
        cog, game = self.build()

        await self.stage(cog, game)
        game.tutorial_staged = False
        await self.stage(cog, game)

        self.assertEqual(game.tutorial_step, tutorial.FIRST_STEP)

    async def test_running_out_of_beats_ends_the_tutorial(self) -> None:
        cog, game = self.build(
            tutorial_step=tutorial.BEATS[-1].step, tutorial_staged=True,
        )

        interaction = await self.stage(cog, game)

        self.assertIsNone(game.tutorial_step)
        self.assertFalse(game.in_tutorial)
        self.assertIn(
            tutorial.HANDOVER,
            [call.args[0] for call in interaction.followup.send.await_args_list],
        )

    async def test_a_game_that_is_not_a_tutorial_is_left_alone(self) -> None:
        cog, game = self.build(tutorial=False, tutorial_step=None)
        before = dict(game.match_state)

        interaction = await self.stage(cog, game)

        self.assertEqual(game.match_state, before)
        interaction.followup.send.assert_not_awaited()

    async def test_staging_posts_the_lesson_and_moves_the_board(self) -> None:
        cog, game = self.build(tutorial_step=2)

        interaction = await self.stage(cog, game)

        self.assertIn(
            tutorial.BEATS[1].lesson,
            [call.args[0] for call in interaction.followup.send.await_args_list],
        )
        cog.refresh_match_image.assert_awaited()


class TutorialRailTests(unittest.TestCase):
    """
    What the coach may press. Every rail is built **disabled** rather
    than left out -- a lesson about the three cards in your hand cannot
    be taught by hiding two of them.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    def build(self, beat_index: int):
        cog = build_cog()
        beat = tutorial.BEATS[beat_index]
        game = build_game(tutorial_step=beat.step, tutorial_staged=True)
        match = build_match(self.catalog, self.rules)
        tutorial.apply_beat(match, self.catalog, beat, TeamSide.HOME)
        if beat.player_has_ball:
            # A maneuver's effect views are only ever built after the
            # handler has been selected, which is what send_turn_prompt
            # does before the prompt goes up.
            match.select_ball_handler(match.eligible_ball_handlers()[0])
        game.match_state = match.to_dict()
        cog.games[game.game_id] = game
        return cog, game, beat

    def labels(self, view):
        return {item.label: item.disabled for item in view.children}

    def test_only_the_beats_action_is_live(self) -> None:
        cog, game, beat = self.build(0)

        labels = self.labels(PlayerActionView(cog, game.game_id))

        self.assertFalse(labels["Maneuver"])
        self.assertTrue(
            labels["Cede ball to coach"],
            "ceding should be visible but not pressable",
        )

    def test_the_other_two_cards_are_shown_and_disabled(self) -> None:
        cog, game, beat = self.build(0)

        labels = self.labels(
            ManeuverActionSelectView(cog, game.game_id, "offense")
        )

        self.assertEqual(len(labels), 4, "three cards and the reference")
        self.assertFalse(labels[beat.player_maneuver])
        self.assertTrue(
            all(
                disabled
                for label, disabled in labels.items()
                if label not in (beat.player_maneuver, "Maneuver Reference")
            )
        )

    def test_the_defending_beat_rails_the_defense_menu(self) -> None:
        cog, game, beat = self.build(3)

        labels = self.labels(
            ManeuverActionSelectView(cog, game.game_id, "defense")
        )

        self.assertFalse(labels[beat.player_maneuver])

    def test_the_high_pass_is_railed_to_the_distance_that_sets_up(
        self,
    ) -> None:
        cog, game, beat = self.build(4)

        view = HighPassChoiceView(cog, game.game_id)
        live = [
            item.label for item in view.children if not item.disabled
        ]

        self.assertEqual(len(live), 1)
        self.assertTrue(live[0].startswith(f"{beat.high_pass_distance} "))

    def test_nothing_is_railed_once_the_tutorial_is_over(self) -> None:
        cog, game, _ = self.build(0)
        game.tutorial_step = None

        labels = self.labels(
            ManeuverActionSelectView(cog, game.game_id, "offense")
        )

        self.assertFalse(any(labels.values()))

    def test_an_ordinary_game_is_railed_by_nothing(self) -> None:
        cog, game, _ = self.build(0)
        game.tutorial = False
        game.tutorial_step = None

        self.assertFalse(
            any(self.labels(PlayerActionView(cog, game.game_id)).values())
        )


class TutorialGameRecordTests(unittest.TestCase):
    """The three fields, and what a save written before them does."""

    def test_a_game_saved_before_the_tutorial_existed_still_loads(
        self,
    ) -> None:
        saved = build_game().to_dict()
        for key in list(saved):
            if key.startswith("tutorial"):
                del saved[key]

        game = D12BallGame.from_dict(saved)

        self.assertFalse(game.tutorial)
        self.assertIsNone(game.tutorial_step)
        self.assertFalse(game.in_tutorial)

    def test_in_tutorial_is_false_once_the_script_has_run_out(self) -> None:
        game = build_game(tutorial_step=None)

        self.assertTrue(game.tutorial)
        self.assertFalse(game.in_tutorial)

    def test_the_fields_survive_a_round_trip(self) -> None:
        game = build_game(tutorial_step=3, tutorial_staged=True)

        restored = D12BallGame.from_dict(game.to_dict())

        self.assertTrue(restored.in_tutorial)
        self.assertEqual(restored.tutorial_step, 3)
        self.assertTrue(restored.tutorial_staged)


class TutorialCreationTests(unittest.IsolatedAsyncioTestCase):
    """
    What `/d12ball create_game tutorial:true` refuses. A tutorial is one
    human against Dinky; the other shapes are refused rather than
    quietly downgraded, because a coach who asked for a tutorial and
    got an ordinary game has no way to tell.
    """

    async def run_create(self, **kwargs):
        cog = build_cog()
        cog.open_new_game = mock.AsyncMock(
            return_value=SimpleNamespace(channel_id=7)
        )
        interaction = build_interaction()
        interaction.guild = SimpleNamespace(id=1)
        interaction.user = mock.MagicMock(spec=__import__("discord").Member)
        interaction.user.id = 111
        interaction.user.bot = False
        interaction.user.display_name = "One"
        interaction.response.defer = mock.AsyncMock()
        interaction.followup.send = mock.AsyncMock()

        await D12Ball.create_game.callback(cog, interaction, **kwargs)
        return cog, interaction

    async def test_a_tutorial_against_a_person_is_refused(self) -> None:
        other = mock.MagicMock(spec=__import__("discord").Member)
        other.id, other.bot = 222, False

        cog, interaction = await self.run_create(tutorial=True, p2=other)

        cog.open_new_game.assert_not_awaited()
        interaction.response.send_message.assert_awaited()

    async def test_a_tutorial_test_game_is_refused(self) -> None:
        cog, interaction = await self.run_create(
            tutorial=True, test_game=True,
        )

        cog.open_new_game.assert_not_awaited()

    async def test_a_solo_tutorial_is_created(self) -> None:
        cog, interaction = await self.run_create(tutorial=True)

        cog.open_new_game.assert_awaited()
        self.assertTrue(cog.open_new_game.await_args.kwargs["tutorial"])


if __name__ == "__main__":
    unittest.main()
