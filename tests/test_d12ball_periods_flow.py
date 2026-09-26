"""
The periods and the coaching windows as flow steps -- no Discord,
nothing saved.

The model-side half of what Phase 5 of `docs/design/model-discord-split.md`
lifted out of `cogs/d12ball/periods.py` and
`cogs/d12ball/turnovers.py`: `d12ball/flow/periods.py` and
`d12ball/flow/windows.py`. The cog's own behaviour is still covered
where it was -- `test_d12ball_halftime.py` drives the halftime
sequence, `test_d12ball_shootout.py` the shootout's menus,
`test_d12ball_time_out.py` the time out, `test_d12ball_coaching.py` the
window -- and `tests/test_golden_windows.py` plays a whole game through
the real cog to full time and past it. What this file asserts is the
three things a lift is judged on, the same three
`test_d12ball_spine_flow.py` names:

- the step answers the same question it answered in the cog;
- it **saves nothing** (principle 9), asserted by suppressing nothing
  and letting `save_patches.guard_stray_saves` raise if it tried;
- `interaction` is nowhere in sight, which the purity ratchet already
  guarantees mechanically and this file demonstrates by construction.

The save/load round trip at the bottom is the other half of the
phase's brief. **Every window is a state a match can sit in for
hours** -- a coach walks away mid-Coaching Choice, a shootout waits on
an order nobody has set -- so each one has to read back off `to_dict`
as the same pending prompt. The shootout's three sub-states are here
one by one for that reason: two of its four steps are the bot's own,
so a restart between them has no button anywhere and the resume reads
`pending_prompt` to find out what to put back up (see
docs/design/recovery.md).
"""

import unittest
from types import SimpleNamespace
from unittest import mock

from d12ball.components import (
    CoachingOccasion,
    MatchPeriod,
    MatchState,
    PlayerRole,
    TeamSide,
    Zone,
)
from d12ball.engine import FULL_TIME_STAGES, HALFTIME_STAGES, SETUP_STAGES
from d12ball.flow import FollowOn, FollowOnStep, StepResult
from d12ball.flow.periods import (
    advance_full_time_stage,
    advance_halftime_stage,
    advance_setup_stage,
    advance_shootout,
    begin_full_time_coaching,
    begin_halftime,
    begin_halftime_extra_token,
    begin_setup_coaching,
    begin_shootout,
    continue_shootout,
    end_period,
    finish_halftime,
)
from d12ball.flow.windows import (
    begin_time_out,
    coaching_summary,
    coaching_window_note,
    finish_substitution_window,
    finish_time_out,
    open_substitution_window,
)
from d12ball.prompts import PromptKind, owed_step, pending_prompt
from ai_answers import let_the_ai_answer

from roster import fielded
from save_patches import suppressed_cog_saves
from test_d12ball_tutorial import build_cog, build_game, build_match


class PeriodFixture(unittest.TestCase):
    """A standard deal, and the engine over it."""

    def setUp(self) -> None:
        self.cog = build_cog()
        self.engine = self.cog.engine
        # Two humans: an AI side answers its own windows and its own
        # shootout order, which is a different branch and is asserted
        # on its own below.
        self.game = build_game(
            tutorial=False, tutorial_step=None, player_2_id=222,
        )
        self.match = build_match()

    def follow_on(self, result) -> FollowOnStep:
        self.assertIsInstance(result.next, FollowOn)
        return result.next.step


class EndPeriodTests(PeriodFixture):
    """The whistle, and the three things it can open."""

    def test_the_first_half_hands_straight_on_into_halftime(self) -> None:
        """
        One step, several blocks. The whistle and the halftime
        recovery were two messages before the lift and the step hands
        them back in the order they were said -- which is what
        `post_blocks_then_dispatch` posts one apiece.
        """
        self.match.scoreboard.time = 19
        self.match.scoreboard.last_possession = True

        result = end_period(self.engine, self.game, self.match)

        self.assertEqual(self.match.scoreboard.period, MatchPeriod.SECOND_HALF)
        self.assertEqual(self.match.scoreboard.time, 15)
        self.assertFalse(self.match.scoreboard.last_possession)
        self.assertIn("at 19", result.narration[0])
        self.assertTrue(result.narration[1].startswith("# Halftime"))
        self.assertEqual(
            self.match.pending_halftime_stage, HALFTIME_STAGES[0],
        )

    def test_the_first_half_gives_both_sides_their_time_out_back(
        self,
    ) -> None:
        self.match.scoreboard.time = 15
        self.match.scoreboard.last_possession = True
        self.match.time_outs_used.add(TeamSide.HOME)
        self.match.half_substitutions_used[TeamSide.HOME] = 2

        end_period(self.engine, self.game, self.match)

        self.assertEqual(self.match.time_outs_used, set())
        self.assertEqual(self.match.half_substitutions_used, {})

    def test_a_level_full_time_opens_the_window_before_the_shootout(
        self,
    ) -> None:
        self.match.scoreboard.period = MatchPeriod.SECOND_HALF
        self.match.scoreboard.time = 30
        self.match.scoreboard.last_possession = True

        result = end_period(self.engine, self.game, self.match)

        self.assertIn("**Full time!**", result.narration[0])
        self.assertIn("goes to the extreme shootout", result.narration[0])
        self.assertEqual(
            self.match.pending_full_time_stage, FULL_TIME_STAGES[0],
        )
        self.assertEqual(
            self.follow_on(result), FollowOnStep.BEGIN_SUBSTITUTION_WINDOW,
        )
        # The game record is still in progress: the shootout is what
        # ends it, so a restart mid-shootout comes back to a live game.
        self.assertFalse(self.game.is_finished)

    def test_an_unlevel_full_time_finishes_the_game(self) -> None:
        self.match.scoreboard.period = MatchPeriod.SECOND_HALF
        self.match.scoreboard.time = 30
        self.match.scoreboard.last_possession = True
        self.match.scoreboard.home_score = 2

        result = end_period(self.engine, self.game, self.match)

        self.assertTrue(self.game.is_finished)
        self.assertEqual(
            self.follow_on(result), FollowOnStep.ANNOUNCE_GAME_OVER,
        )
        # The scoresheet goes out with the whistle, in the content the
        # final board rides on.
        self.assertIn("## Goals", result.narration[0])

    def test_the_carry_does_not_survive_the_whistle(self) -> None:
        """
        A Steal under last possession names a carrier, and the second
        half kicks off from the coaches' arrangement with nobody
        holding anything.
        """
        self.match.scoreboard.time = 15
        self.match.scoreboard.last_possession = True
        self.match.ball_carrier_id = fielded(self.match, PlayerRole.MIDFIELDER)

        end_period(self.engine, self.game, self.match)

        self.assertIsNone(self.match.ball_carrier_id)

    def test_the_whistle_saves_nothing(self) -> None:
        """
        Principle 9, and nothing is suppressed here: the guard in
        `save_patches` raises if the step reached `save_games`.
        """
        self.match.scoreboard.time = 15
        self.match.scoreboard.last_possession = True
        end_period(self.engine, self.game, self.match)


class WhistleBlocksTests(unittest.IsolatedAsyncioTestCase):
    """
    The cog's half of the whistle, now that the loop runs it.

    `END_PERIOD` moved into `driver.MODEL_STEPS` in Phase 6's second
    increment, which it could not do while "one message per block" was
    the cog calling a different dispatcher. `driver.advance` closes a
    `NarrationGroup` after it and `dispatch_step_result` reads the
    step off the group to decide -- so the property the golden covers
    end to end is asserted here on its own, where a regression names
    itself.
    """

    def setUp(self) -> None:
        self.cog = build_cog()
        self.game = build_game()
        self.match = build_match()
        self.cog.games[self.game.game_id] = self.game
        self.game.match_state = self.match.to_dict()

    def interaction(self):
        send = mock.AsyncMock(return_value=SimpleNamespace(id=7))
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

    async def test_the_whistle_s_blocks_are_a_message_apiece(self) -> None:
        self.match.scoreboard.time = 19
        self.match.scoreboard.last_possession = True
        interaction = self.interaction()

        with suppressed_cog_saves():
            await self.cog.dispatch_step_result(
                interaction,
                self.game,
                self.match,
                StepResult(next=FollowOn(FollowOnStep.END_PERIOD)),
            )

        posted = [
            call.args[0]
            for call in interaction.followup.send.await_args_list
            if call.args
        ]
        # The whistle and the halftime recovery: two events, two
        # messages. Joined, they would read as one paragraph.
        self.assertGreaterEqual(len(posted), 2)
        self.assertIn("at 19", posted[0])
        self.assertTrue(posted[1].startswith("# Halftime"))


class HalftimeFlowTests(PeriodFixture):
    """Recovery, the extra token, and the stages between them."""

    def test_every_fielded_player_recovers_one_token(self) -> None:
        home = self.match.home.field_players[0]
        visiting = self.match.visiting.field_players[0]
        self.match.exhaustion[home] = 3
        self.match.exhaustion[visiting] = 2

        result = begin_halftime(self.engine, self.game, self.match)

        self.assertEqual(self.match.exhaustion[home], 2)
        self.assertEqual(self.match.exhaustion[visiting], 1)
        self.assertIn("clears 1 exhaustion", result.narration[0])
        self.assertTrue(result.board_changed)

    def test_a_side_with_nothing_to_recover_says_so(self) -> None:
        result = begin_halftime(self.engine, self.game, self.match)
        self.assertIn(
            "No fielded player had any exhaustion to clear.",
            result.narration[0],
        )

    def test_the_extra_token_asks_the_coach_whose_stage_it_is(
        self,
    ) -> None:
        self.match.pending_halftime_stage = "extra_token_home"

        result = begin_halftime_extra_token(
            self.engine, self.game, self.match, TeamSide.HOME,
        )

        self.assertEqual(result.next.kind, PromptKind.HALFTIME_EXTRA_TOKEN)
        self.assertEqual(result.next.side, TeamSide.HOME)
        # Nothing advances while a coach still owes an answer.
        self.assertEqual(
            self.match.pending_halftime_stage, "extra_token_home",
        )

    def test_an_ai_side_is_asked_and_takes_the_most_tired_off(self) -> None:
        # The AI is asked the same question a coach is, and answers it
        # through the driver (step 7 of docs/architecture-migration.md).
        solo = build_game(tutorial=False, tutorial_step=None)
        self.match.pending_halftime_stage = "extra_token_visiting"
        low, high = self.match.visiting.field_players[:2]
        self.match.exhaustion[low] = 1
        self.match.exhaustion[high] = 4

        result = begin_halftime_extra_token(
            self.engine, solo, self.match, TeamSide.VISITING,
        )
        self.assertEqual(result.next.kind, PromptKind.HALFTIME_EXTRA_TOKEN)

        taken = let_the_ai_answer(self.engine, solo, self.match)

        self.assertEqual(taken[0].arguments["player_id"], high)
        self.assertEqual(self.match.exhaustion[high], 3)
        self.assertEqual(self.match.exhaustion[low], 1)
        # And carries on to the next stage, which is home's.
        self.assertEqual(
            self.match.pending_halftime_stage, "extra_token_home",
        )

    def test_a_side_with_nobody_eligible_is_passed_over_in_silence(
        self,
    ) -> None:
        """
        A menu with no button on it is not a question -- the same rule
        the full-time window skips an empty bench on.
        """
        self.match.pending_halftime_stage = "extra_token_home"
        for player_id in self.match.home.field_players:
            self.match.injured.add(player_id)

        result = begin_halftime_extra_token(
            self.engine, self.game, self.match, TeamSide.HOME,
        )

        self.assertEqual(result.narration, [])
        self.assertNotEqual(
            self.match.pending_halftime_stage, "extra_token_home",
        )

    def test_a_coaching_stage_hands_the_window_out(self) -> None:
        self.match.pending_halftime_stage = "coaching_visiting"

        result = advance_halftime_stage(self.engine, self.game, self.match)

        self.assertEqual(
            self.follow_on(result), FollowOnStep.BEGIN_SUBSTITUTION_WINDOW,
        )
        self.assertEqual(result.next.kwargs["side"], TeamSide.VISITING)
        self.assertEqual(
            result.next.kwargs["occasion"], CoachingOccasion.HALFTIME,
        )
        self.assertIn("## Halftime", result.next.kwargs["heading"])

    def test_the_last_stage_names_the_kickoff_board(self) -> None:
        self.match.pending_halftime_stage = None

        result = advance_halftime_stage(self.engine, self.game, self.match)

        self.assertEqual(
            self.follow_on(result), FollowOnStep.FINISH_HALFTIME,
        )

    def test_finishing_clears_the_flag_and_names_the_kickoff(self) -> None:
        self.match.pending_halftime_stage = "coaching_home"

        result = finish_halftime(self.engine, self.game, self.match)

        self.assertIsNone(self.match.pending_halftime_stage)
        self.assertIn("**Halftime is over.**", result.narration[0])


class SetupFlowTests(PeriodFixture):
    """The pre-kickoff window, and the tutorial's exemption from it."""

    def test_a_tutorial_kicks_off_on_the_standard_deal(self) -> None:
        tutorial_game = build_game()

        result = begin_setup_coaching(self.engine, tutorial_game, self.match)

        self.assertIsNone(self.match.pending_setup_stage)
        self.assertEqual(
            self.follow_on(result), FollowOnStep.FINISH_SETUP_COACHING,
        )

    def test_an_ordinary_game_opens_home_first(self) -> None:
        result = begin_setup_coaching(self.engine, self.game, self.match)

        self.assertEqual(self.match.pending_setup_stage, SETUP_STAGES[0])
        self.assertEqual(
            self.follow_on(result), FollowOnStep.BEGIN_SUBSTITUTION_WINDOW,
        )
        self.assertEqual(result.next.kwargs["side"], TeamSide.HOME)
        self.assertEqual(
            result.next.kwargs["occasion"], CoachingOccasion.SETUP,
        )

    def test_the_stage_runs_out_into_the_kickoff_board(self) -> None:
        self.match.pending_setup_stage = None

        result = advance_setup_stage(self.engine, self.game, self.match)

        self.assertEqual(
            self.follow_on(result), FollowOnStep.FINISH_SETUP_COACHING,
        )


class FullTimeWindowTests(PeriodFixture):
    """One substitution a side, and nothing else."""

    def test_the_window_offers_one_substitution_and_no_positioning(
        self,
    ) -> None:
        result = begin_full_time_coaching(self.engine, self.game, self.match)

        self.assertEqual(
            self.match.pending_full_time_stage, FULL_TIME_STAGES[0],
        )
        self.assertEqual(
            result.next.kwargs["occasion"], CoachingOccasion.FULL_TIME,
        )
        self.assertIn(
            "**one substitution**", result.next.kwargs["heading"],
        )

    def test_a_side_with_nobody_to_bring_on_is_skipped_in_silence(
        self,
    ) -> None:
        """
        Its only action is the substitution, so a side with an empty
        pool would get a Done button with extra steps. It takes both
        benches spent, which is a genuinely rare state.
        """
        self.match.pending_full_time_stage = "coaching_home"
        for player_id in list(self.match.substitution_pool(TeamSide.HOME)):
            self.match.injured.add(player_id)

        result = advance_full_time_stage(self.engine, self.game, self.match)

        self.assertEqual(result.narration, [])
        self.assertNotEqual(
            self.match.pending_full_time_stage, "coaching_home",
        )


class ShootoutFlowTests(PeriodFixture):
    """The four steps that hand back to each other."""

    def test_opening_it_explains_it_and_asks_for_an_order(self) -> None:
        result = begin_shootout(self.engine, self.game, self.match)

        self.assertTrue(self.match.pending_shootout)
        self.assertTrue(result.narration[0].startswith("# Extreme shootout"))
        self.assertEqual(result.next.kind, PromptKind.SHOOTOUT_ORDER)

    def test_an_ai_side_is_asked_its_order_one_name_at_a_time(self) -> None:
        solo = build_game(tutorial=False, tutorial_step=None)
        self.match.begin_shootout()

        result = advance_shootout(self.engine, solo, self.match)
        self.assertEqual(result.next.kind, PromptKind.SHOOTOUT_ORDER)

        taken = let_the_ai_answer(self.engine, solo, self.match)

        self.assertEqual(len(taken), 6)
        self.assertTrue(
            self.match.shootout_order_complete(TeamSide.VISITING)
        )
        # Home is human and still owes theirs, so that is what it asks
        # -- of the coach alone, now.
        prompt = pending_prompt(self.engine, solo, self.match)
        self.assertEqual(prompt.kind, PromptKind.SHOOTOUT_ORDER)
        self.assertIn("{coach:1}: set the order", prompt.ask)

    def test_both_orders_in_reveals_the_first_test(self) -> None:
        self.match.begin_shootout()
        for side in (TeamSide.HOME, TeamSide.VISITING):
            self.match.set_shootout_order(
                side, list(self.match.shootout_squad(side)),
            )

        result = advance_shootout(self.engine, self.game, self.match)

        self.assertEqual(result.next.kind, PromptKind.SHOOTOUT_TEST)
        self.assertIn("versus", result.next.ask)

    def test_a_settled_shootout_finishes_the_game(self) -> None:
        self.match.begin_shootout()
        for side in (TeamSide.HOME, TeamSide.VISITING):
            self.match.set_shootout_order(
                side, list(self.match.shootout_squad(side)),
            )
        # Six tests shot, home ahead: `shootout_winner` reads it off
        # who is left, which is nobody.
        for side in (TeamSide.HOME, TeamSide.VISITING):
            self.match.shootout_used[side.value] = list(
                self.match.shootout_squad(side)
            )
        self.match.shootout_goals[TeamSide.HOME.value] = 3
        self.match.shootout_goals[TeamSide.VISITING.value] = 1

        result = continue_shootout(self.engine, self.game, self.match)

        self.assertFalse(self.match.pending_shootout)
        self.assertTrue(self.game.is_finished)
        self.assertEqual(
            self.follow_on(result), FollowOnStep.ANNOUNCE_GAME_OVER,
        )
        self.assertIn("extreme shootout is settled", result.narration[0])


class CoachingWindowFlowTests(PeriodFixture):
    """Opening one, closing one, and what each says."""

    def test_a_new_play_offers_the_declaration(self) -> None:
        result = open_substitution_window(
            self.engine, self.game, self.match, TeamSide.HOME,
        )

        self.assertEqual(result.next.kind, PromptKind.COACHING_OFFER)
        self.assertEqual(result.next.side, TeamSide.HOME)
        self.assertEqual(
            self.match.pending_coaching_side, TeamSide.HOME.value,
        )

    def test_halftime_opens_the_hub_directly(self) -> None:
        """
        Setup, halftime and full time are *given* rather than declared,
        so all three skip the offer -- and a time out skips it for the
        opposite reason, having been paid for already.
        """
        result = open_substitution_window(
            self.engine,
            self.game,
            self.match,
            TeamSide.HOME,
            CoachingOccasion.HALFTIME,
            heading="## Halftime",
        )

        self.assertEqual(result.next.kind, PromptKind.COACHING_HUB)
        self.assertIn("## Halftime", result.next.ask)

    def test_a_window_opens_on_the_arrangement_its_coach_last_set(
        self,
    ) -> None:
        player_id = self.match.home.field_players[0]
        settled = self.match.board.meeple_position(player_id)
        self.match.set_assigned_positions(TeamSide.HOME)
        self.match.board.place_meeple(
            player_id, settled[0], 1 if settled[1] == 0 else 0,
        )

        result = open_substitution_window(
            self.engine,
            self.game,
            self.match,
            TeamSide.HOME,
            CoachingOccasion.HALFTIME,
        )

        self.assertEqual(
            self.match.board.meeple_position(player_id), settled,
        )
        # And the board above the menu is brought in line, so the two
        # views of the same side cannot disagree.
        self.assertTrue(result.board_changed)
        self.assertIn("back on the arrangement you last set", result.next.ask)

    def test_full_time_restores_nothing(self) -> None:
        """
        `offers_positioning` is one fact read at both ends: nothing is
        played from a position after full time, so restoring would
        rearrange the last board of the game to no purpose.
        """
        player_id = self.match.home.field_players[0]
        self.match.set_assigned_positions(TeamSide.HOME)
        settled = self.match.board.meeple_position(player_id)
        self.match.board.place_meeple(
            player_id, settled[0], 1 if settled[1] == 0 else 0,
        )
        moved = self.match.board.meeple_position(player_id)

        result = open_substitution_window(
            self.engine,
            self.game,
            self.match,
            TeamSide.HOME,
            CoachingOccasion.FULL_TIME,
        )

        self.assertEqual(self.match.board.meeple_position(player_id), moved)
        self.assertFalse(result.board_changed)

    def test_an_injured_player_is_named_as_a_nudge(self) -> None:
        injured = fielded(self.match, PlayerRole.MIDFIELDER)
        self.match.injured.add(injured)

        note = coaching_window_note(
            self.engine,
            self.game,
            self.match,
            TeamSide.HOME,
            CoachingOccasion.NEW_PLAY,
            is_response=False,
            restored=False,
        )

        self.assertIn("injured and still on the field", note)
        # And the question is still asked: nothing compels a side to
        # get them off.
        self.assertIn("Coach?", note)

    def test_only_a_time_out_reply_says_why_it_opened(self) -> None:
        self.assertEqual(
            coaching_window_note(
                self.engine,
                self.game,
                self.match,
                TeamSide.HOME,
                CoachingOccasion.TIME_OUT,
                is_response=True,
                restored=False,
            ),
            "The other team called a time out.",
        )
        self.assertEqual(
            coaching_window_note(
                self.engine,
                self.game,
                self.match,
                TeamSide.HOME,
                CoachingOccasion.NEW_PLAY,
                is_response=True,
                restored=False,
            ),
            "",
        )

    def test_a_declared_window_hands_the_other_side_its_reply(self) -> None:
        self.match.open_coaching_window(
            TeamSide.HOME, CoachingOccasion.NEW_PLAY,
        )
        self.match.declare_coaching()

        result = finish_substitution_window(
            self.engine, self.game, self.match,
        )

        self.assertEqual(
            self.follow_on(result), FollowOnStep.BEGIN_SUBSTITUTION_WINDOW,
        )
        self.assertEqual(result.next.kwargs["side"], TeamSide.VISITING)
        self.assertTrue(result.next.kwargs["is_response"])

    def test_a_passed_window_falls_through_to_the_run_back(self) -> None:
        """A side that passes takes the opposing reply down with it."""
        self.match.open_coaching_window(
            TeamSide.HOME, CoachingOccasion.NEW_PLAY,
        )

        result = finish_substitution_window(
            self.engine, self.game, self.match,
        )

        self.assertEqual(
            self.follow_on(result), FollowOnStep.ANNOUNCE_RUN_BACK,
        )

    def test_the_summary_reads_the_window_before_it_closes(self) -> None:
        self.match.open_coaching_window(
            TeamSide.HOME, CoachingOccasion.HALFTIME, formation="2-2-2",
        )
        outgoing = self.match.home.field_players[0]
        incoming = self.match.substitution_pool(TeamSide.HOME)[0]
        self.match.pending_coaching_swaps.append((outgoing, incoming))

        lines = coaching_summary(self.engine, self.match, TeamSide.HOME)

        self.assertEqual(len(lines), 1)
        self.assertIn("came on for", lines[0])


class TimeOutFlowTests(PeriodFixture):
    """Charged, not asked; and the free pickup at the end of it."""

    def setUp(self) -> None:
        super().setUp()
        self.match.active_player_id = fielded(
            self.match, PlayerRole.MIDFIELDER,
        )

    def test_calling_one_opens_the_caller_s_window(self) -> None:
        caller = self.match.ball.possession

        result = begin_time_out(self.engine, self.game, self.match)

        self.assertTrue(self.match.pending_time_out)
        self.assertEqual(
            self.follow_on(result), FollowOnStep.BEGIN_SUBSTITUTION_WINDOW,
        )
        self.assertEqual(result.next.kwargs["side"], caller)
        self.assertEqual(
            result.next.kwargs["occasion"], CoachingOccasion.TIME_OUT,
        )
        # The announcement is narration -- the caller's own line --
        # rather than the window's heading, so an AI caller's is
        # posted too (step 7 of docs/architecture-migration.md).
        self.assertNotIn("heading", result.next.kwargs)
        self.assertIn("call a time out", result.narration[0])

    def test_it_is_logged_as_its_own_kind_of_event(self) -> None:
        """
        Not a turn action: a possession is a run of consecutive
        `turn_action`s by one side, so logging a pause as a turn would
        invent a turn nobody played.
        """
        begin_time_out(self.engine, self.game, self.match)

        self.assertEqual(self.match.events[-1].kind, "time_out")

    def test_the_tail_charges_the_minute_and_no_turnover(self) -> None:
        self.match.call_time_out()

        result = finish_time_out(self.engine, self.game, self.match)

        self.assertFalse(self.match.pending_time_out)
        self.assertEqual(
            self.follow_on(result), FollowOnStep.FINISH_MANEUVER_RESOLUTION,
        )
        self.assertEqual(result.next.kwargs["distance_moved"], 1)
        self.assertFalse(result.next.kwargs["turnover_occurred"])

    def test_a_handler_coached_off_the_ball_fetches_it_free(self) -> None:
        self.match.call_time_out()
        for player_id in list(
            self.match.board.spaces[self.match.ball.zone][
                self.match.ball.space_index
            ]
        ):
            self.match.board.place_meeple(player_id, Zone.HOME_GOAL, 0)

        finish_time_out(self.engine, self.game, self.match)

        self.assertTrue(self.match.pending_ball_recovery)
        # One flag, read at both ends: the pickup costs nothing *and*
        # it is not a turnover.
        self.assertTrue(self.match.pending_recovery_from_time_out)


class WindowStateSurvivesASaveTests(PeriodFixture):
    """
    Every window a match can sit in has to read back as the same
    question after a save and a load.

    A window is the longest wait in the game -- a coach walks away
    mid-menu, a shootout waits on an order nobody has set -- so this is
    where a lift would show up as a game that comes back asking
    something else. See "Recovering a stuck game" in
    docs/design/recovery.md.
    """

    def round_trip(self) -> MatchState:
        return MatchState.from_dict(
            self.match.to_dict(), self.engine.basic_ruleset,
        )

    def assert_survives(self, expected: PromptKind) -> None:
        before = pending_prompt(self.engine, self.game, self.match)
        self.assertEqual(before.kind, expected)
        after = pending_prompt(self.engine, self.game, self.round_trip())
        self.assertEqual(after, before)

    def assert_owed_survives(self, expected: FollowOnStep) -> None:
        before = owed_step(self.engine, self.game, self.match)
        self.assertEqual(before.step, expected)
        after = owed_step(self.engine, self.game, self.round_trip())
        self.assertEqual(after, before)

    def test_the_pre_kickoff_window(self) -> None:
        begin_setup_coaching(self.engine, self.game, self.match)
        open_substitution_window(
            self.engine,
            self.game,
            self.match,
            TeamSide.HOME,
            CoachingOccasion.SETUP,
        )
        self.assert_survives(PromptKind.COACHING_HUB)

    def test_halftime_s_extra_token(self) -> None:
        begin_halftime(self.engine, self.game, self.match)
        self.assert_survives(PromptKind.HALFTIME_EXTRA_TOKEN)

    def test_a_halftime_window(self) -> None:
        self.match.pending_halftime_stage = "coaching_home"
        open_substitution_window(
            self.engine,
            self.game,
            self.match,
            TeamSide.HOME,
            CoachingOccasion.HALFTIME,
        )
        self.assert_survives(PromptKind.COACHING_HUB)

    def test_the_window_before_the_shootout(self) -> None:
        begin_full_time_coaching(self.engine, self.game, self.match)
        open_substitution_window(
            self.engine,
            self.game,
            self.match,
            TeamSide.HOME,
            CoachingOccasion.FULL_TIME,
        )
        self.assert_survives(PromptKind.COACHING_HUB)

    def test_a_new_play_s_offer(self) -> None:
        self.match.active_player_id = fielded(
            self.match, PlayerRole.MIDFIELDER,
        )
        open_substitution_window(
            self.engine, self.game, self.match, TeamSide.HOME,
        )
        self.assert_survives(PromptKind.COACHING_OFFER)

    def test_a_time_out_s_window(self) -> None:
        self.match.active_player_id = fielded(
            self.match, PlayerRole.MIDFIELDER,
        )
        begin_time_out(self.engine, self.game, self.match)
        open_substitution_window(
            self.engine,
            self.game,
            self.match,
            self.match.ball.possession,
            CoachingOccasion.TIME_OUT,
        )
        self.assert_survives(PromptKind.COACHING_HUB)

    def test_a_time_out_waiting_on_its_tail(self) -> None:
        """
        Both windows closed and the pause still on the match: the
        state `pending_time_out` exists for, since by here nothing else
        says how the game got there.
        """
        self.match.active_player_id = fielded(
            self.match, PlayerRole.MIDFIELDER,
        )
        begin_time_out(self.engine, self.game, self.match)
        self.assert_owed_survives(FollowOnStep.FINISH_TIME_OUT)

    def test_the_shootout_waiting_on_an_order(self) -> None:
        begin_shootout(self.engine, self.game, self.match)
        self.assert_survives(PromptKind.SHOOTOUT_ORDER)

    def test_the_shootout_waiting_on_a_roll(self) -> None:
        self.match.begin_shootout()
        for side in (TeamSide.HOME, TeamSide.VISITING):
            self.match.set_shootout_order(
                side, list(self.match.shootout_squad(side)),
            )
        advance_shootout(self.engine, self.game, self.match)
        self.assert_survives(PromptKind.SHOOTOUT_TEST)

    def test_sudden_death_waiting_on_a_shooter(self) -> None:
        """
        The one state `shootout_shooters_complete` can be false in: a
        round past the first has no order to read a shooter off.
        """
        self.match.begin_shootout()
        for side in (TeamSide.HOME, TeamSide.VISITING):
            self.match.set_shootout_order(
                side, list(self.match.shootout_squad(side)),
            )
        # A level first round: `finish_shootout_test` has bumped the
        # round and cleared who has been out, so there is no order left
        # to read a shooter off.
        self.match.shootout_round = 2
        self.match.shootout_used = {}
        self.match.shootout_goals[TeamSide.HOME.value] = 3
        self.match.shootout_goals[TeamSide.VISITING.value] = 3
        continue_shootout(self.engine, self.game, self.match)
        self.assert_survives(PromptKind.SHOOTOUT_PICK)


if __name__ == "__main__":
    unittest.main()
