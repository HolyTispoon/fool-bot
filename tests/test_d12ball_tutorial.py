"""
The scripted opening a tutorial game plays -- see `d12ball/tutorial.py`
and "The tutorial" in docs/design/tutorial.md.

The centrepiece is `TutorialPlaythroughTests`, which plays the whole
script through the **real cog** with Discord mocked, pressing whichever
button the rails leave enabled. It exists because the script's one
promise is hard to check any other way: the five beats are one
continuous game, so beat 4 is played from wherever beat 3's turn left
the ball, and a change anywhere -- a maneuver's effect, the run back,
the loose-ball rule -- can put the story out of joint without breaking
anything the rest of the suite watches. What it asserts is that

- the board is set **once**, at kickoff, and never again;
- nothing moves between a turn ending and the next lesson being posted;
- every railed step leaves exactly one button pressable; and
- the whole thing arrives at a goal, at the minute it is meant to.

The lesson *text* is deliberately not asserted anywhere. It is prose,
it will be revised, and a test quoting it would only ever break on a
reword. What is asserted is every claim it makes that the data could
contradict.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

import discord

from cogs.d12ball import presentation as presentation_mod
from cogs.d12ball_views import turn as turn_views
from save_patches import suppressed_cog_saves, suppressed_full_image_links, suppressed_view_saves
from cogs.d12ball import D12Ball
from cogs.d12ball_views import (
    HomeAwaySelectionView,
    ManeuverActionPromptView,
    PlayerActionView,
)
from d12ball import stats, tutorial
from d12ball.flow import turn as turn_flow
from d12ball.prompts import PendingPrompt, PromptKind
from d12ball.ai import build_ai_strategies
from d12ball.components import (
    EVENT_MANEUVER,
    MatchState,
    PlayerRole,
    TeamSide,
    Zone,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.engine import RulesEngine
from tests.roster import fielded
from d12ball.game import (
    CoinFace,
    D12BallGame,
    Formation,
    GameStatus,
    Team,
)


CATALOG = load_player_catalog()
RULES = load_basic_ruleset()
MANEUVERS = load_maneuver_catalog()


def build_cog() -> D12Ball:
    cog = object.__new__(D12Ball)
    cog.games = {}
    cog.player_catalog = CATALOG
    cog.maneuver_catalog = MANEUVERS
    cog.basic_ruleset = RULES
    cog.coin_emojis = {}
    cog.ai_strategies = build_ai_strategies(CATALOG, MANEUVERS)
    cog.engine = RulesEngine(CATALOG, RULES, MANEUVERS, cog.ai_strategies)
    # Everything that draws or uploads.
    cog.refresh_match_image = mock.AsyncMock()
    cog.announce_board_update = mock.AsyncMock()
    cog.post_new_play_board = mock.AsyncMock()
    cog.build_match_file = mock.AsyncMock(return_value=None)
    cog.build_field_file = mock.AsyncMock(return_value=None)
    cog.build_maneuver_challenge_file = mock.AsyncMock(return_value=None)
    cog.build_score_attempt_file = mock.AsyncMock(return_value=None)
    cog.render_match_png = mock.AsyncMock(return_value=b"")
    cog.match_file_from_png = mock.Mock(return_value=None)
    cog.coaching_file = mock.AsyncMock(return_value=None)
    cog.build_maneuver_hand_file = mock.Mock(return_value=None)
    cog.build_maneuver_reference_file = mock.Mock(return_value=None)
    cog.drop_turn_prompt = mock.AsyncMock()
    cog.close_maneuver_prompt = mock.AsyncMock()
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


def build_match() -> MatchState:
    return MatchState.standard(
        catalog=CATALOG,
        ruleset=RULES,
        board_size=7,
        home_team=Team.ORANGE,
        visiting_team=Team.PURPLE,
        home_formation=Formation.TWO_TWO_TWO,
    )


def build_interaction(recorder=None, user_id: int = 111) -> SimpleNamespace:
    """
    Enough of a `discord.Interaction` for the flow to run. When a
    `recorder` is given, every message and view the cog sends is
    collected on it -- which is what the playthrough drives from.
    """

    def note(content, view):
        if recorder is None:
            return
        if content:
            recorder.messages.append(str(content))
        if view is not None:
            recorder.views.append(view)

    async def send(content=None, **kwargs):
        note(content, kwargs.get("view"))
        return SimpleNamespace(
            id=999, attachments=[], edit=mock.AsyncMock(),
        )

    async def edit_message(content=None, **kwargs):
        note(content, kwargs.get("view"))

    async def send_message(content=None, **kwargs):
        note(content, kwargs.get("view"))

    async def edit_original_response(content=None, **kwargs):
        note(content, kwargs.get("view"))
        return SimpleNamespace(
            id=999, attachments=[], edit=mock.AsyncMock(),
        )

    return SimpleNamespace(
        channel_id=2,
        guild=None,
        # The same `send` the recorder already watches through
        # `followup`: which of the two a post actually goes out through
        # depends on whether the interaction still had a response to
        # give at that point in the cascade, and the recorder cares
        # about what was said, not which route said it.
        # `get_partial_message(...).delete()` is how a view drops a
        # message it no longer owns -- backing out of a score attempt
        # deletes the composition image. Stubbed rather than left off
        # so a free-running game (the advanced golden) can reach the
        # branch at all; nothing asserts on it.
        channel=SimpleNamespace(
            send=send,
            get_partial_message=lambda message_id: SimpleNamespace(
                delete=mock.AsyncMock(),
            ),
        ),
        message=SimpleNamespace(id=999, content="prompt", attachments=[]),
        user=SimpleNamespace(id=user_id, display_name="Coach"),
        edit_original_response=edit_original_response,
        original_response=mock.AsyncMock(
            return_value=SimpleNamespace(id=999, attachments=[]),
        ),
        response=SimpleNamespace(
            defer=mock.AsyncMock(),
            send_message=send_message,
            edit_message=edit_message,
            is_done=lambda: True,
        ),
        followup=SimpleNamespace(send=send),
    )


def board_signature(match: MatchState) -> tuple:
    """
    Everything about a position the script depends on, as one
    comparable value -- who is standing where, where the ball is, and
    whose it is.
    """
    return (
        tuple(tuple(sorted(occ)) for occ in match.board.spaces_in_order()),
        match.ball.zone.value,
        match.ball.space_index,
        match.ball.possession.value,
    )


class TutorialScriptTests(unittest.TestCase):
    """The beats as data: do they say what they claim to say."""

    def test_every_card_a_beat_names_is_in_the_catalog(self) -> None:
        # The maneuvers are imported from a spreadsheet, so this is the
        # check that a rename upstream fails the cog load rather than
        # railing a coach onto a button that no longer exists.
        tutorial.validate_script(MANEUVERS)

    def test_each_beat_lands_the_outcome_it_teaches(self) -> None:
        # Read off the ranking rather than restated, because the
        # ranking is the data and the lesson is the claim. Beat 2 is
        # the tie, and the only beat whose outcome the ranking does not
        # settle -- its dice do, which is what `rolls` is for.
        expected = {
            1: "offense",   # Dribble Advance over Deflect
            2: "tie",       # Low Pass and Deflect, both rank 1
            3: "defense",   # the coach's Pressure over Dribble Advance
            4: "defense",   # the coach's Steal Intercept over Low Pass
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
                    MANEUVERS.resolve(offense, defense), expected[beat.step],
                )

    def test_the_only_beat_the_coach_loses_is_the_scripted_one(self) -> None:
        # Beat 2 is the lesson in losing the ball, and it is lost on
        # rigged dice rather than on rank. Every other beat has to
        # resolve the coach's way, or the script teaches the opposite
        # of what it says.
        for beat in tutorial.BEATS:
            outcome = MANEUVERS.resolve(
                *(
                    (beat.player_maneuver, beat.dinky_maneuver)
                    if beat.player_has_ball
                    else (beat.dinky_maneuver, beat.player_maneuver)
                )
            )
            coach_side = "offense" if beat.player_has_ball else "defense"
            with self.subTest(beat=beat.step):
                if beat.step == 2:
                    self.assertEqual(outcome, "tie")
                    self.assertIn("skill_test", beat.rolls)
                else:
                    self.assertEqual(outcome, coach_side)

    def test_only_one_card_is_ever_offered(self) -> None:
        for beat in tutorial.BEATS:
            menu = "offense" if beat.player_has_ball else "defense"
            with self.subTest(beat=beat.step):
                self.assertEqual(
                    tutorial.allowed_maneuvers(beat, menu),
                    (beat.player_maneuver,),
                )

    def test_dinky_never_picks_out_of_the_coachs_own_menu(self) -> None:
        # The two halves of the menu are keyed "offense"/"defense" and
        # the coach is on one of them; a beat handing Dinky a card for
        # the coach's half would overwrite the pick they are railed on.
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

    def test_a_scripted_contest_fixes_both_dice(self) -> None:
        # A contest rolls two. A beat naming one would send the caller
        # back an unpackable pair.
        for beat in tutorial.BEATS:
            for kind in ("skill_test", "loose_ball"):
                if kind not in beat.rolls:
                    continue
                with self.subTest(beat=beat.step, kind=kind):
                    self.assertEqual(
                        len(tutorial.scripted_dice(beat, kind, 2)), 2,
                    )

    def test_asking_for_more_dice_than_a_beat_fixes_is_refused(self) -> None:
        # Quietly padding would let a flow change roll an unscripted
        # die inside a scripted contest and nobody would notice.
        beat = tutorial.beat_for_step(2)
        with self.assertRaises(ValueError):
            tutorial.scripted_dice(beat, "skill_test", 3)

    def test_injury_checks_pass_for_the_whole_opening(self) -> None:
        # A card going down injured is a mechanic the script never
        # introduces and cannot plan around -- see BLANKET_ROLLS.
        for beat in tutorial.BEATS:
            with self.subTest(beat=beat.step):
                self.assertEqual(
                    tutorial.scripted_dice(beat, "injury", 1), [12],
                )

    def test_the_score_attempt_is_left_to_the_dice(self) -> None:
        # The one roll in the tutorial that decides something the coach
        # wants. The position makes it a heavy favourite; nothing makes
        # it certain.
        for beat in tutorial.BEATS:
            with self.subTest(beat=beat.step):
                self.assertIsNone(
                    tutorial.scripted_dice(beat, "score_attempt", 2),
                )

    def test_nothing_is_railed_without_a_beat(self) -> None:
        self.assertIsNone(tutorial.allowed_actions(None))
        self.assertIsNone(tutorial.allowed_maneuvers(None, "offense"))
        self.assertIsNone(tutorial.scripted_dice(None, "injury", 1))
        self.assertIsNone(tutorial.resolve_choice(None, "speed", (1, 7)))


class TutorialOpeningTests(unittest.TestCase):
    """
    The tutorial places nothing: it kicks off from the standard deal,
    like every other game. So these are assertions about the *deal* --
    every one of them a claim the lesson text makes, and every one of
    them something `basic_rules.json` could quietly change.

    That the deal is the opening is itself the point. A hand-written
    position was tried and dropped: it put the two sides in 2-3-1 and
    1-3-2, shapes no game ever kicks off in, which taught the wrong
    thing before the coach had pressed anything.
    """

    def deal(self) -> MatchState:
        return build_match()

    def test_both_sides_kick_off_in_2_2_2(self) -> None:
        # The whole reason the script stopped writing its own position.
        for side in (TeamSide.HOME, TeamSide.VISITING):
            setup = self.deal().setup_for_side(side)
            with self.subTest(side=side.value):
                self.assertEqual(
                    sorted(len(ids) for ids in setup.zones.values()),
                    [2, 2, 2],
                )

    def test_the_coach_starts_with_the_ball_and_one_handler(self) -> None:
        match = self.deal()
        self.assertEqual(match.ball.possession, TeamSide.HOME)
        self.assertEqual(len(match.eligible_ball_handlers()), 1)

    def test_the_opening_starts_out_of_shooting_range(self) -> None:
        # Beat 1's lesson says the shot is not offered because the ball
        # is short of range, and beat 2's says it has appeared once the
        # dribble lands. Both are claims about this space.
        self.assertFalse(self.deal().can_attempt_score())

    def test_dinky_has_somebody_on_the_ball_to_challenge(self) -> None:
        # Beat 1's note names them. An empty space would make the
        # opening maneuver uncontested instead.
        self.assertEqual(len(self.deal().automatic_challengers()), 1)

    def test_the_deal_records_itself_as_the_arrangement(self) -> None:
        # The goal at the end is a new play, and a new play restores
        # this. The tutorial skips setup coaching, so nothing else
        # would have written it.
        match = self.deal()
        for side in (TeamSide.HOME, TeamSide.VISITING):
            for player_id in match.setup_for_side(side).field_players:
                zone, space_index = match.board.meeple_position(player_id)
                with self.subTest(side=side.value, player=player_id):
                    self.assertEqual(
                        match.assigned_positions[player_id],
                        [zone.value, space_index],
                    )

    def test_both_sides_cover_their_own_kickoff_space(self) -> None:
        # The goal at the end opens a Coaching Choice, and
        # `coaching_finish_refusal` holds a coach in one until somebody
        # of theirs is standing on it.
        match = self.deal()
        for side in (TeamSide.HOME, TeamSide.VISITING):
            occupants = match.board.spaces[Zone.MIDFIELD][
                match.kickoff_space_for(side)
            ]
            with self.subTest(side=side.value):
                self.assertTrue(
                    set(occupants)
                    & set(match.setup_for_side(side).field_players)
                )

    def test_the_coachs_striker_is_where_the_last_pass_lands(self) -> None:
        # Beat 5 throws 2 spaces onto V2 and calls it a scoring
        # opportunity, which needs the striker standing there and that
        # space inside the coach's range.
        match = self.deal()
        striker = fielded(match, PlayerRole.STRIKER)
        zone, space_index = match.board.meeple_position(striker)
        self.assertEqual((zone, space_index), (Zone.VISITORS_GOAL, 1))
        self.assertTrue(
            match.board.is_in_shooting_range(
                TeamSide.HOME, match.board.flat_index(zone, space_index),
            )
        )

    def test_dinky_has_one_card_on_the_space_the_shot_is_taken_from(
        self,
    ) -> None:
        # What prices the last shot: a defender **on** the ball adds
        # all of their defensive skill, which is the 6 beat 5's note
        # quotes. A second card behind them would add half again and
        # the note would be wrong.
        match = self.deal()
        landing = match.board.spaces[Zone.VISITORS_GOAL][1]
        dinky = set(match.setup_for_side(TeamSide.VISITING).field_players)
        self.assertEqual(len(set(landing) & dinky), 1)


class TutorialPlaythroughTests(unittest.IsolatedAsyncioTestCase):
    """
    The whole script, played through the real cog. See the module
    docstring for why this exists.
    """

    async def play(self):
        """
        Kick off and then press the single enabled button at every
        step until the script hands over. Returns the cog, the game,
        and a log of what happened.
        """
        recorder = SimpleNamespace(messages=[], views=[])
        cog = build_cog()
        game = build_game(tutorial_step=None)
        game.match_state = build_match().to_dict()
        cog.games["g1"] = game

        # Nothing may re-deal a side once the game has kicked off.
        # `deploy_side` is the atomic whole-side placement a formation
        # change is made of, and it is the one call that could put a
        # seam back into the story.
        deals = []
        real_deploy = MatchState.deploy_side

        def counting_deploy(self, *args, **kwargs):
            deals.append(True)
            return real_deploy(self, *args, **kwargs)

        multi_choice = []
        signatures = []

        with suppressed_cog_saves(), \
                suppressed_view_saves(), \
                mock.patch.object(
                    turn_views, "add_full_image_button_to_response",
                    mock.AsyncMock()), \
                suppressed_full_image_links(), \
                mock.patch.object(
                    presentation_mod, "pin_board_message", mock.AsyncMock()), \
                mock.patch.object(
                    MatchState, "deploy_side", counting_deploy):

            await cog.finish_setup_coaching(
                build_interaction(recorder),
                game,
                cog.engine.load_match_state(game),
            )

            for _ in range(40):
                if not recorder.views or not game.in_tutorial:
                    break
                view = recorder.views.pop()
                recorder.views.clear()
                live = [
                    item for item in view.children
                    if not getattr(item, "disabled", False)
                    and item.label != "Maneuver Reference"
                ]
                if not live:
                    raise AssertionError(
                        f"{type(view).__name__} had nothing enabled"
                    )
                if len(live) > 1:
                    multi_choice.append(
                        (type(view).__name__, [i.label for i in live])
                    )
                before = board_signature(cog.engine.load_match_state(game))
                step_before = game.tutorial_step
                await live[0].callback(build_interaction(recorder))
                signatures.append(
                    (
                        step_before,
                        type(view).__name__,
                        before,
                        board_signature(cog.engine.load_match_state(game)),
                    )
                )

        return cog, game, SimpleNamespace(
            messages=recorder.messages,
            deals=len(deals),
            multi_choice=multi_choice,
            signatures=signatures,
        )

    async def test_the_event_log_records_the_five_scripted_beats(
        self,
    ) -> None:
        """
        That the statistics' event log is written by a real game, and
        written correctly.

        This is the one place five real turns are played end to end
        through the real cog, so it is where a log written at half a
        dozen funnels can actually be checked -- a recorder that fires
        on the wrong object, or before a save that never happens, is
        invisible in a unit test and shows up here as a missing beat.
        That is not hypothetical: the maneuver recorder was landed
        without a save of its own, and beat 1 went missing exactly
        this way.

        Asserted against `tutorial.BEATS` rather than a written-out
        list of five cards, for the reason every other tutorial
        assertion is: the script is data the author revises, and a
        copy of it here would only ever break on a rewrite.
        """
        cog, game, _ = await self.play()
        match = cog.engine.load_match_state(game)
        turns = stats.match_turns(match)

        self.assertEqual(len(turns), len(tutorial.BEATS))
        self.assertEqual(
            [turn.action for turn in turns],
            [beat.actions[0] for beat in tutorial.BEATS],
        )
        for turn, beat in zip(turns, tutorial.BEATS):
            logged = turn.first(EVENT_MANEUVER)
            self.assertIsNotNone(
                logged, f"beat {beat.player_maneuver} logged no maneuver",
            )
            self.assertEqual(
                {
                    logged.details["offense_key"],
                    logged.details["defense_key"],
                },
                {beat.player_maneuver, beat.dinky_maneuver},
            )

    async def test_the_scripted_shot_reaches_the_statistics(self) -> None:
        """
        The whole pipeline: five turns played, a shot taken off beat
        5's set-up, and whatever it produced credited to the
        possession -- and so to the High Pass that made it.

        **The shot's outcome is not asserted, because the script does
        not fix it.** It is deliberately left to the dice (see "The
        five beats" in docs/design/tutorial.md), a heavy favourite and not a
        certainty, so a test demanding a goal fails one run in seven
        for the reason the tutorial is built to allow -- which it did,
        on `main`, at about that rate. What the fold has to agree with
        is what *happened*, so the goal counts are read off the goal
        log: a separate record, written by `record_goal` rather than
        by the `shot` event this fold counts, so the two agreeing is a
        real claim either way round. The one test that does need the
        ball in the net pins the dice --
        `test_the_script_ends_in_a_goal_at_the_minute_it_should`.
        """
        cog, game, _ = await self.play()
        match = cog.engine.load_match_state(game)
        scored = len(match.goals)

        shots = stats.collect_shots([match])
        self.assertEqual(shots.attempts, 1)
        self.assertEqual(shots.set_up_attempts, 1)
        self.assertEqual(shots.goals, scored)
        self.assertEqual(shots.set_up_goals, scored)

        report = stats.collect_maneuvers([match])
        self.assertEqual(
            report.records[tutorial.HIGH_PASS].goals_for, scored,
        )

    async def test_no_side_is_ever_re_dealt(self) -> None:
        # The whole of "no seams", in one number. The tutorial kicks
        # off from the standard deal and every beat after that is
        # played, not placed -- re-dealing a side mid-script is exactly
        # the discontinuity this design was rewritten to remove.
        _, _, log = await self.play()

        self.assertEqual(log.deals, 0)

    async def test_nothing_moves_between_a_turn_and_the_next_lesson(
        self,
    ) -> None:
        # Staging a beat posts its lesson and must change nothing. If
        # it ever moves a meeple again, the story has a seam in it
        # wherever this fires.
        cog = build_cog()
        game = build_game(tutorial_step=2, tutorial_staged=True)
        match = build_match()
        game.match_state = match.to_dict()
        cog.games["g1"] = game
        before = board_signature(cog.engine.load_match_state(game))

        turn_flow.begin_turn(cog.engine, game, match)

        self.assertEqual(
            board_signature(cog.engine.load_match_state(game)), before,
        )

    # The two steps the script deliberately leaves open. Both are
    # choices with no wrong answer whose outcome no later beat reads:
    # which space a displaced player returns to, and which of two
    # equally-near players the coach sends to challenge in beat 3.
    # Anything else showing up with two live buttons means a rail has
    # gone missing, which is what this list is for.
    #
    # Beat 2's loose ball is no longer in this list: since 2026-08-24 a
    # side with nobody on the landing space is never offered a send at
    # all when the other side already has someone there, so
    # LooseBallChoiceView never appears in this script any more -- see
    # test_beat_2s_loose_ball_is_never_offered_to_either_coach.
    FREE_CHOICES = ("RunBack", "ManeuverChallengeView", "SpeedDeltaChoiceView")

    async def test_every_railed_step_leaves_one_button(self) -> None:
        _, _, log = await self.play()

        unexpected = [
            entry for entry in log.multi_choice
            if not entry[0].startswith(self.FREE_CHOICES)
        ]
        self.assertEqual(unexpected, [])

    async def test_beat_2s_loose_ball_is_never_offered_to_either_coach(
        self,
    ) -> None:
        # Dinky's own midfielder is already standing where the beaten
        # Deflect lands, and since 2026-08-24 a landing space only one
        # side occupies is theirs outright -- the coach, who has nobody
        # there, is never put on the clock and LooseBallChoiceView never
        # gets built at all. (The tied maneuver's own SkillTestView, a
        # separate prompt earlier in the same beat, is unaffected.)
        _, _, log = await self.play()

        offered = [
            labels for name, labels in log.multi_choice
            if name == "LooseBallChoiceView"
        ]
        self.assertEqual(offered, [])

    async def test_beat_3s_challenge_may_not_be_waved_through(self) -> None:
        # The one button removed from that prompt. Beat 2 no longer
        # leaves a defeated contestant standing on the ball for beat 3's
        # challenge to fall to automatically, so the coach has to send
        # somebody -- and declining would leave Dinky's Dribble Advance
        # nothing to defend against.
        _, _, log = await self.play()

        offered = [
            labels for name, labels in log.multi_choice
            if name == "ManeuverChallengeView"
        ]
        self.assertTrue(offered)
        for labels in offered:
            self.assertNotIn("Send nobody", labels)

    async def test_the_script_ends_in_a_goal_at_the_minute_it_should(
        self,
    ) -> None:
        # Five beats charge four maneuvers, a High Pass and the shot.
        # The shot is real dice, so this is the position doing the
        # work: a striker's +9 against a lone halved +3.
        with mock.patch(
            "random.randint", return_value=6,
        ):
            cog, game, log = await self.play()

        match = cog.engine.load_match_state(game)
        self.assertEqual(match.scoreboard.home_score, 1)
        self.assertEqual(match.scoreboard.visiting_score, 0)
        self.assertEqual(match.scoreboard.time, 7)

    async def test_the_script_reaches_the_handover(self) -> None:
        _, game, log = await self.play()

        self.assertFalse(game.in_tutorial)
        self.assertIsNone(game.tutorial_step)
        self.assertIn(tutorial.HANDOVER, log.messages)

    async def test_every_lesson_is_posted_in_order(self) -> None:
        _, _, log = await self.play()

        posted = [
            message for message in log.messages
            if message in {beat.lesson for beat in tutorial.BEATS}
        ]
        self.assertEqual(
            posted, [beat.lesson for beat in tutorial.BEATS],
        )

    async def test_possession_changes_hands_the_three_scripted_times(
        self,
    ) -> None:
        # Beat 2 hands the ball to Dinky, beat 4 takes it back, and the
        # goal at the end of beat 5 hands it over again for the
        # restart. A script where possession never changes is one where
        # beats 3 and 4 have nothing to teach.
        _, _, log = await self.play()

        possession = [after[3] for _, _, _, after in log.signatures]
        changes = [
            (before, after)
            for before, after in zip(possession, possession[1:])
            if before != after
        ]
        self.assertEqual(
            changes,
            [("home", "visiting"), ("visiting", "home"),
             ("home", "visiting")],
        )


class TutorialRailTests(unittest.TestCase):
    """
    What the coach may press. Every rail builds its button **disabled**
    rather than leaving it out -- a lesson about the three cards in
    your hand cannot be taught by hiding two of them.
    """

    def build(self, beat_index: int):
        cog = build_cog()
        beat = tutorial.BEATS[beat_index]
        game = build_game(tutorial_step=beat.step, tutorial_staged=True)
        match = build_match()
        if beat.player_has_ball:
            match.select_ball_handler(match.eligible_ball_handlers()[0])
        else:
            # A defending beat is Dinky on the ball, and the prompt
            # reads possession to work out whose row to build -- see
            # RulesEngine.maneuver_pick_sides.
            match.ball.possession = TeamSide.VISITING
        game.match_state = match.to_dict()
        cog.games["g1"] = game
        return cog, game, beat

    def labels(self, view):
        return {item.label: item.disabled for item in view.children}

    def cards(self, view):
        """
        A maneuver menu by **key**, which is what a rail names -- the
        label is the printed name and moves when the author renames a
        card. The reference button carries no maneuver, so it is left
        out; `labels` is still the way to ask about it.
        """
        return {
            item.custom_id.rsplit(":", 1)[1]: item.disabled
            for item in view.children
            if item.custom_id.startswith("d12ball:maneuver_pick:")
        }

    def test_only_the_beats_action_is_live(self) -> None:
        cog, game, _ = self.build(0)

        labels = self.labels(PlayerActionView(cog, "g1"))

        self.assertFalse(labels["Maneuver"])
        self.assertTrue(
            labels["Time out"],
            "the time out should be visible but not pressable",
        )

    def test_the_other_two_cards_are_shown_and_disabled(self) -> None:
        cog, game, beat = self.build(0)

        view = ManeuverActionPromptView(cog, "g1")
        cards = self.cards(view)

        self.assertEqual(len(cards), 3, "the basic three")
        self.assertIn("Maneuver Reference", self.labels(view))
        self.assertFalse(cards[beat.player_maneuver])
        self.assertTrue(
            all(
                disabled
                for key, disabled in cards.items()
                if key != beat.player_maneuver
            )
        )

    def test_a_defending_beat_rails_the_defense_menu(self) -> None:
        cog, game, beat = self.build(2)

        # Dinky is on offense in a defending beat, so the prompt is
        # the coach's own row and nothing else -- see
        # RulesEngine.maneuver_pick_sides.
        cards = self.cards(ManeuverActionPromptView(cog, "g1"))

        self.assertFalse(cards[beat.player_maneuver])

    def test_a_beats_sub_choices_are_railed(self) -> None:
        cog, game, beat = self.build(0)

        self.assertEqual(
            cog.tutorial_railed_option(game, "dribble_advance", (1, 2)), 2,
        )

    def test_a_choice_the_beat_says_nothing_about_is_free(self) -> None:
        # Beat 1 pins the dribble and the speed and nothing else, so a
        # pass distance is nobody's business but the coach's.
        cog, game, _ = self.build(0)

        self.assertIsNone(
            cog.tutorial_railed_option(game, "high_pass", (2, 3)),
        )

    def test_nothing_is_railed_once_the_tutorial_is_over(self) -> None:
        cog, game, _ = self.build(0)
        game.tutorial_step = None

        labels = self.labels(ManeuverActionPromptView(cog, "g1"))

        self.assertFalse(any(labels.values()))
        self.assertIsNone(
            cog.tutorial_railed_option(game, "dribble_advance", (1, 2)),
        )

    def test_an_ordinary_game_is_railed_by_nothing(self) -> None:
        cog, game, _ = self.build(0)
        game.tutorial = False
        game.tutorial_step = None

        self.assertFalse(
            any(self.labels(PlayerActionView(cog, "g1")).values())
        )

    def test_a_tutorial_coach_who_wins_the_toss_must_take_home(
        self,
    ) -> None:
        # The script opens with the ball theirs, so the visiting side
        # would leave every beat's lesson describing the wrong end of
        # the board.
        cog = build_cog()
        game = build_game(
            home_player_number=None,
            visiting_player_number=None,
            coin_flipped=True,
            coin_winner_player_number=1,
            coin_face=CoinFace.FORTUNE,
        )
        cog.games["g1"] = game

        labels = self.labels(HomeAwaySelectionView(cog, "g1"))

        self.assertFalse(labels["Home"])
        self.assertTrue(labels["Visiting"])

    def test_an_ordinary_game_may_still_choose_either(self) -> None:
        cog = build_cog()
        game = build_game(
            tutorial=False,
            tutorial_step=None,
            home_player_number=None,
            visiting_player_number=None,
            coin_flipped=True,
            coin_winner_player_number=1,
            coin_face=CoinFace.FORTUNE,
        )
        cog.games["g1"] = game

        labels = self.labels(HomeAwaySelectionView(cog, "g1"))

        self.assertFalse(any(labels.values()))


class TutorialStagingTests(unittest.IsolatedAsyncioTestCase):
    """
    Counting the beats. `send_turn_prompt` is called once a turn, which
    is what advances the script -- but the recovery commands call it
    too, and a beat skipped there is a lesson nobody sees.
    """

    def build(self, **overrides):
        cog = build_cog()
        game = build_game(**overrides)
        match = build_match()
        game.match_state = match.to_dict()
        cog.games["g1"] = game
        return cog, game

    async def stage(self, cog, game):
        """
        Start a turn -- `d12ball.flow.turn.begin_turn`, which is where
        the staging lives since Phase 6 -- and return what it put up:
        the note held behind Continue, or nothing for a game with no
        lesson to stage. The gate is taken down again so the next
        staging reads a clean game, the way a click would leave it.
        """
        match = cog.engine.load_match_state(game)
        result = turn_flow.begin_turn(cog.engine, game, match)
        posted = []
        if isinstance(result.next, PendingPrompt):
            self.assertIs(result.next.kind, PromptKind.TUTORIAL_CONTINUE)
            posted.append(result.next.ask)
            game.tutorial_gate = None
        return posted

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
        # turn having been played. That must not count as one.
        cog, game = self.build()

        await self.stage(cog, game)
        game.tutorial_staged = False
        await self.stage(cog, game)

        self.assertEqual(game.tutorial_step, tutorial.FIRST_STEP)

    async def test_running_out_of_beats_ends_the_tutorial(self) -> None:
        cog, game = self.build(
            tutorial_step=tutorial.BEATS[-1].step, tutorial_staged=True,
        )

        posted = await self.stage(cog, game)

        self.assertIsNone(game.tutorial_step)
        self.assertFalse(game.in_tutorial)
        self.assertIn(tutorial.HANDOVER, posted)

    async def test_a_game_that_is_not_a_tutorial_is_left_alone(self) -> None:
        cog, game = self.build(tutorial=False, tutorial_step=None)
        before = dict(game.match_state)

        posted = await self.stage(cog, game)

        self.assertEqual(game.match_state, before)
        self.assertEqual(posted, [])

    async def test_staging_posts_the_lesson(self) -> None:
        cog, game = self.build(tutorial_step=2)

        posted = await self.stage(cog, game)

        self.assertIn(tutorial.BEATS[1].lesson, posted)


class TutorialGameRecordTests(unittest.TestCase):
    """The fields, and what a save written before them does."""

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


class TutorialCoachingNoteTests(unittest.IsolatedAsyncioTestCase):
    """
    The lesson the script cannot schedule. A new play offers the window
    to the side *restarting* play, which after the coach's goal is
    Dinky -- so the note fires at the first window this coach is ever
    offered, however long that takes.
    """

    def build(self, **overrides):
        cog = build_cog()
        overrides.setdefault("tutorial_step", None)
        game = build_game(**overrides)
        match = build_match()
        game.match_state = match.to_dict()
        cog.games["g1"] = game
        return cog, game, match

    async def open_window(self, cog, game, match, side=TeamSide.HOME):
        interaction = build_interaction()
        posted = []
        recorder = mock.AsyncMock(
            side_effect=lambda content=None, **kw: posted.append(content)
            or SimpleNamespace(id=1, attachments=[]),
        )
        interaction.followup.send = recorder
        interaction.channel.send = recorder
        with suppressed_cog_saves():
            await cog.begin_substitution_window(
                interaction, game, match, side,
            )
        return posted

    async def test_it_fires_after_the_script_has_finished(self) -> None:
        cog, game, match = self.build()

        posted = await self.open_window(cog, game, match)

        self.assertIn(tutorial.COACHING_NOTE, posted)
        self.assertTrue(game.tutorial_coaching_explained)

    async def test_it_fires_only_once(self) -> None:
        cog, game, match = self.build()

        await self.open_window(cog, game, match)
        posted = await self.open_window(cog, game, match)

        self.assertNotIn(tutorial.COACHING_NOTE, posted)

    async def test_dinkys_own_window_is_not_taught(self) -> None:
        cog, game, match = self.build()

        posted = await self.open_window(cog, game, match, TeamSide.VISITING)

        self.assertNotIn(tutorial.COACHING_NOTE, posted)

    async def test_an_ordinary_game_never_sees_it(self) -> None:
        cog, game, match = self.build(tutorial=False)

        posted = await self.open_window(cog, game, match)

        self.assertNotIn(tutorial.COACHING_NOTE, posted)

    async def test_skipping_the_tutorial_suppresses_it(self) -> None:
        cog, game, match = self.build(
            tutorial_step=2, tutorial_coaching_explained=True,
        )

        posted = await self.open_window(cog, game, match)

        self.assertNotIn(tutorial.COACHING_NOTE, posted)


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
        interaction.user = mock.MagicMock(spec=discord.Member)
        interaction.user.id = 111
        interaction.user.bot = False
        interaction.user.display_name = "Coach"
        interaction.response.defer = mock.AsyncMock()
        interaction.response.send_message = mock.AsyncMock()
        interaction.followup.send = mock.AsyncMock()

        await D12Ball.create_game.callback(cog, interaction, **kwargs)
        return cog, interaction

    async def test_a_tutorial_against_a_person_is_refused(self) -> None:
        other = mock.MagicMock(spec=discord.Member)
        other.id, other.bot = 222, False

        cog, interaction = await self.run_create(tutorial=True, p2=other)

        cog.open_new_game.assert_not_awaited()
        interaction.response.send_message.assert_awaited()

    async def test_a_tutorial_test_game_is_refused(self) -> None:
        cog, _ = await self.run_create(tutorial=True, test_game=True)

        cog.open_new_game.assert_not_awaited()

    async def test_a_solo_tutorial_is_created(self) -> None:
        cog, _ = await self.run_create(tutorial=True)

        cog.open_new_game.assert_awaited()
        self.assertTrue(cog.open_new_game.await_args.kwargs["tutorial"])


if __name__ == "__main__":
    unittest.main()
