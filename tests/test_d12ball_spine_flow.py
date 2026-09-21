"""
The spine as flow steps -- no Discord, nothing saved.

The model-side half of what Phase 4 lifted out of `cogs/d12ball/`:
`d12ball/flow/arrivals.py`, `d12ball/flow/turnovers.py` and
`d12ball/flow/turn.py`. The cog's own behaviour is still covered where
it was -- `test_d12ball_species_abilities.py` drives the gates through
the views, `test_d12ball_loose_ball.py` the contest,
`test_d12ball_run_back_batching.py` the cascade's message economy --
and this asserts the three things a lift is judged on:

- the step answers the same question it answered in the cog;
- it **saves nothing** (principle 9), asserted by suppressing nothing
  and letting `save_patches.guard_stray_saves` raise if it tried;
- `interaction` is nowhere in sight, which the purity ratchet already
  guarantees mechanically and this file demonstrates by construction.

The save/load round trip at the bottom is the other half of the
phase's brief: every state the spine can now leave a match in has to
read back as the same pending prompt, because a step that ends in one
hands the turn to a click that reloads the match off disk.
"""

import unittest

from d12ball.components import MatchState, PlayerRole, TeamSide, Zone
from d12ball.flow import FollowOn, FollowOnStep
from d12ball.flow.arrivals import (
    begin_loose_ball,
    choose_loose_ball_contestant,
    decline_loose_ball_contest,
    loose_ball_decline_refusal,
    begin_own_goal_roll,
    begin_shooter_choice,
    check_for_loose_ball,
    finish_maneuver_resolution,
    resolve_loose_ball,
    send_loose_ball_out_of_bounds,
)
from d12ball.flow.turn import (
    announce_uncontested_maneuver,
    auto_resolve_challenger,
    resolve_maneuver,
)
from d12ball.flow.turnovers import (
    announce_new_play_reset,
    begin_ball_recovery,
    begin_run_back,
    finish_run_back,
    run_back_passes,
)
from d12ball.formatting import contest_noun, format_team_side_label
from d12ball.prompts import PromptKind, pending_prompt

from roster import fielded
from test_d12ball_tutorial import build_cog, build_game, build_match


class SpineFixture(unittest.TestCase):
    """A standard deal, and the engine over it."""

    def setUp(self) -> None:
        self.cog = build_cog()
        self.engine = self.cog.engine
        self.game = build_game(tutorial=False, tutorial_step=None)
        self.match = build_match()
        self.cog.games[self.game.game_id] = self.game

    def follow_on(self, result) -> FollowOnStep:
        self.assertIsInstance(result.next, FollowOn)
        return result.next.step


class FinishManeuverResolutionTests(SpineFixture):
    """The tail of every ordinary path."""

    def test_the_clock_advances_and_the_turn_is_handed_back(self) -> None:
        before = self.match.scoreboard.time
        result = finish_maneuver_resolution(
            self.engine, self.game, self.match, distance_moved=2,
        )
        self.assertEqual(self.match.scoreboard.time, before + 2)
        self.assertEqual(
            self.follow_on(result), FollowOnStep.SEND_TURN_PROMPT,
        )
        self.assertTrue(result.board_changed)
        self.assertIn("Time has advanced 2", result.narration[-1])

    def test_the_maneuver_state_is_cleared(self) -> None:
        """
        `reset_maneuver` runs here and nowhere earlier, which is what
        lets a restart mid-effect reconstruct where things left off.
        """
        self.match.active_player_id = fielded(
            self.match, PlayerRole.MIDFIELDER,
        )
        self.match.offense_maneuver = "low_pass"
        finish_maneuver_resolution(self.engine, self.game, self.match)
        self.assertIsNone(self.match.offense_maneuver)

    def test_a_ball_nobody_of_the_possessing_side_is_on_detours(
        self,
    ) -> None:
        """
        The loose-ball check, which runs before the clock moves: a
        maneuver that left the ball where the possessing side is not
        standing goes to the contest instead of letting the turn
        proceed with nobody eligible to act.
        """
        self.match.set_ball_space(Zone.MIDFIELD, 2)
        self.assertFalse(self.match.eligible_ball_handlers())
        before = self.match.scoreboard.time

        result = finish_maneuver_resolution(
            self.engine, self.game, self.match, distance_moved=2,
        )
        self.assertEqual(
            self.follow_on(result), FollowOnStep.BEGIN_LOOSE_BALL,
        )
        # And the clock did not move on the way past.
        self.assertEqual(self.match.scoreboard.time, before)

    def test_a_turnover_under_last_possession_ends_the_period(self) -> None:
        self.match.scoreboard.last_possession = True
        result = finish_maneuver_resolution(
            self.engine, self.game, self.match, turnover_occurred=True,
        )
        self.assertEqual(self.follow_on(result), FollowOnStep.END_PERIOD)

    def test_the_maneuver_that_declares_it_does_not_end_it(self) -> None:
        """
        "Last possession is the possession that starts there": whoever
        comes out of that maneuver with the ball plays it out, and only
        loses the period when *they* lose the ball.
        """
        self.match.scoreboard.time = self.match.scoreboard.last_minute - 1
        result = finish_maneuver_resolution(
            self.engine, self.game, self.match, turnover_occurred=True,
        )
        self.assertTrue(self.match.scoreboard.last_possession)
        self.assertEqual(
            self.follow_on(result), FollowOnStep.SEND_TURN_PROMPT,
        )
        self.assertIn("last possession", result.narration[0])

    def test_the_two_lines_stay_two(self) -> None:
        """
        The last-possession announcement and the closing line are two
        events, so they come back as two blocks -- the frontend posts
        the first on its own and the second under the board. See
        `None`.
        """
        self.match.scoreboard.time = self.match.scoreboard.last_minute - 1
        result = finish_maneuver_resolution(
            self.engine, self.game, self.match,
        )
        self.assertEqual(len(result.narration), 2)


class LooseBallFlowTests(SpineFixture):
    """What is standing on the space decides how the ball is won."""

    def make_loose(self) -> None:
        self.match.set_ball_space(Zone.MIDFIELD, 2)

    def test_the_ball_is_announced_and_the_contest_named(self) -> None:
        self.make_loose()
        result = begin_loose_ball(self.engine, self.game, self.match, 1)
        self.assertTrue(self.match.pending_loose_ball)
        self.assertIsNone(self.match.ball_carrier_id)
        self.assertTrue(result.board_changed)
        self.assertIn("The ball is at", result.narration[0])

    def test_a_high_pass_draws_no_board_of_its_own(self) -> None:
        """
        The one thing that tells the two apart: a High Pass is on a
        receiver both coaches watched catch it, and the board the pass
        moved was posted by the pass.
        """
        self.make_loose()
        result = begin_loose_ball(
            self.engine, self.game, self.match, 1, is_high_pass=True,
        )
        self.assertFalse(result.board_changed)
        self.assertTrue(self.match.pending_loose_ball_is_high_pass)

    def test_the_side_with_nobody_there_is_pre_declined(self) -> None:
        """
        Occupancy decides who may be sent, and nobody walks in: a ball
        that comes down where only one side is standing is a contest
        between the players already there.
        """
        defender = self.match.visiting.field_players[0]
        self.match.move_meeple(defender, Zone.MIDFIELD, 2)
        self.match.set_ball_space(Zone.MIDFIELD, 2)

        begin_loose_ball(self.engine, self.game, self.match, 1)
        self.assertTrue(self.match.loose_ball_offense_declined)

    def test_nobody_sent_is_out_of_bounds_and_a_new_play(self) -> None:
        self.make_loose()
        self.match.pending_loose_ball = True
        result = send_loose_ball_out_of_bounds(
            self.engine, self.game, self.match, 1,
        )
        self.assertTrue(self.match.pending_ball_recovery)
        self.assertEqual(self.match.ball.speed, 1)
        following = result.next
        self.assertEqual(following.step, FollowOnStep.BEGIN_RUN_BACK)
        # Out of bounds is the one loose ball that is a new play: the
        # ball went dead rather than being taken off anybody.
        self.assertTrue(following.kwargs["new_play"])
        self.assertIn("Out of bounds!", result.narration[0])

    def test_one_side_sending_nobody_is_an_unopposed_take(self) -> None:
        self.make_loose()
        taker = fielded(self.match, PlayerRole.MIDFIELDER)
        self.match.begin_loose_ball(1)
        self.match.loose_ball_offense_player = taker

        result = resolve_loose_ball(self.engine, self.game, self.match)
        self.assertEqual(self.match.ball_carrier_id, taker)
        self.assertFalse(self.match.pending_loose_ball)
        following = result.next
        self.assertEqual(following.step, FollowOnStep.BEGIN_RUN_BACK)
        # The side that already had it keeping it is not a turnover.
        self.assertFalse(following.kwargs["turnover_occurred"])

    def test_both_sides_sending_somebody_is_a_skill_test(self) -> None:
        self.make_loose()
        self.match.begin_loose_ball(1)
        self.match.loose_ball_offense_player = fielded(
            self.match, PlayerRole.MIDFIELDER,
        )
        self.match.loose_ball_defense_player = (
            self.match.visiting.field_players[0]
        )

        result = resolve_loose_ball(self.engine, self.game, self.match)
        self.assertEqual(result.next.kind, PromptKind.LOOSE_BALL_SKILL_TEST)
        self.assertTrue(result.board_changed)

    def test_a_ball_the_possessing_side_stands_on_is_not_loose(
        self,
    ) -> None:
        self.assertIsNone(
            check_for_loose_ball(self.engine, self.game, self.match, 1),
        )


class ShooterChoiceTests(SpineFixture):
    """Who takes a scoring opportunity."""

    def test_a_single_candidate_is_not_asked(self) -> None:
        shooter = fielded(self.match, PlayerRole.STRIKER)
        result = begin_shooter_choice(
            self.engine, self.game, self.match, [shooter],
        )
        following = result.next
        self.assertEqual(following.step, FollowOnStep.START_SET_UP_SHOT)
        self.assertEqual(following.kwargs["shooter_id"], shooter)

    def test_several_candidates_put_the_question(self) -> None:
        candidates = [
            fielded(self.match, PlayerRole.STRIKER),
            fielded(self.match, PlayerRole.WINGER),
        ]
        # Two humans, so neither side answers for itself.
        self.game.player_2_id = 222
        result = begin_shooter_choice(
            self.engine, self.game, self.match, candidates,
        )
        # **A `PendingPrompt` since Phase 6.** It was a follow-on while
        # nothing in match state said a scoring opportunity was being
        # asked about; `pending_scoring_opportunity` records that now,
        # and the candidates are read back off the ball's space rather
        # than stored -- see `d12ball.prompts.scoring_opportunity_prompt`.
        prompt = result.next
        self.assertEqual(prompt.kind, PromptKind.SHOOTER_CHOICE)
        self.assertEqual(prompt.player_ids, candidates)
        self.assertIn("choose who takes the shot", prompt.ask)
        self.assertEqual(
            self.match.pending_scoring_opportunity, {"kind": "shooter"},
        )
        self.assertEqual(
            pending_prompt(self.engine, self.game, self.match).kind,
            PromptKind.SHOOTER_CHOICE,
        )


class LooseBallAnswerTests(SpineFixture):
    """
    Answering the loose ball's pick -- the two steps Phase 6 lifted out
    of `LooseBallChoiceView`.

    **These are here because nothing else in the suite reaches them.**
    `test_golden_advanced` says so in its own docstring: every loose
    ball its seed produces comes down where somebody is already
    standing, which pre-declines the other side and settles without
    asking, so the contest pick has never been pressed by a test. The
    lift would have been the one in this phase with nothing behind it.
    """

    def loose_ball(self) -> None:
        """
        A ball lying on an empty space, with nobody yet sent.

        The handler is chosen first, as every real loose ball's was:
        `pending_prompt` reads "no ball handler yet" ahead of the loose
        ball, because a match that has neither is at the kickoff. See
        the ordering comments in `d12ball/prompts.py`.
        """
        self.match.active_player_id = self.match.eligible_ball_handlers()[0]
        for occupant in list(
            self.match.board.spaces[self.match.ball.zone][
                self.match.ball.space_index
            ]
        ):
            self.match.board.remove_meeple(occupant)
        self.match.begin_loose_ball(1)

    def test_a_pick_names_the_player_and_asks_the_other_side(
        self,
    ) -> None:
        self.loose_ball()
        striker = fielded(self.match, PlayerRole.STRIKER)

        result = choose_loose_ball_contestant(
            self.engine,
            self.game,
            self.match,
            skill_type="offense",
            player_id=striker,
        )

        self.assertEqual(self.match.loose_ball_offense_player, striker)
        self.assertEqual(
            result.narration,
            [
                f"{self.engine.format_player_label(self.match, self.engine.get_player_definition(striker))} "
                f"contests the {contest_noun(self.match)} (offense).",
            ],
        )
        # The other side is on the clock now, and the prompt is the one
        # `loose_ball_pick_prompt` reads off the position -- the same
        # one a restart comes back to.
        self.assertEqual(result.next.kind, PromptKind.LOOSE_BALL_PICK)
        self.assertEqual(result.next.skill_type, "defense")
        self.assertEqual(
            pending_prompt(self.engine, self.game, self.match).kind,
            PromptKind.LOOSE_BALL_PICK,
        )

    def test_the_second_answer_hands_on_to_the_settling(self) -> None:
        self.loose_ball()
        choose_loose_ball_contestant(
            self.engine,
            self.game,
            self.match,
            skill_type="offense",
            player_id=fielded(self.match, PlayerRole.STRIKER),
        )

        result = choose_loose_ball_contestant(
            self.engine,
            self.game,
            self.match,
            skill_type="defense",
            player_id=fielded(
                self.match, PlayerRole.FULLBACK, TeamSide.VISITING,
            ),
        )

        self.assertEqual(
            self.follow_on(result), FollowOnStep.RESOLVE_LOOSE_BALL,
        )

    def test_a_decline_says_so_and_puts_it_to_the_other_side(
        self,
    ) -> None:
        self.loose_ball()
        side = self.match.ball.possession

        result = decline_loose_ball_contest(
            self.engine, self.game, self.match, skill_type="offense",
        )

        self.assertTrue(self.match.loose_ball_offense_declined)
        self.assertEqual(
            result.narration,
            [
                f"{format_team_side_label(self.match.setup_for_side(side))} "
                f"send nobody after the {contest_noun(self.match)}.",
            ],
        )
        self.assertEqual(result.next.kind, PromptKind.LOOSE_BALL_PICK)

    def test_a_side_standing_on_the_ball_may_not_be_held_back(
        self,
    ) -> None:
        """
        **The refusal is asked without applying anything**, which is
        the whole reason it is a function of its own: the frontend has
        its own refusals to put in front of the step (the tutorial's
        rail is one), and a step that raised on the way *out* would
        already have recorded the decline by the time one of those
        fired.
        """
        self.loose_ball()
        striker = fielded(self.match, PlayerRole.STRIKER)
        self.match.board.remove_meeple(striker)
        self.match.board.place_meeple(
            striker, self.match.ball.zone, self.match.ball.space_index,
        )

        refusal = loose_ball_decline_refusal(self.match, "offense")

        self.assertIsNotNone(refusal)
        self.assertIn("cannot be held back", refusal)
        self.assertFalse(self.match.loose_ball_offense_declined)
        with self.assertRaises(ValueError):
            decline_loose_ball_contest(
                self.engine, self.game, self.match, skill_type="offense",
            )
        self.assertFalse(self.match.loose_ball_offense_declined)


class OwnGoalRiskTests(SpineFixture):
    """The roll a shove that overshot puts behind a button."""

    def test_the_risk_is_recorded_and_asked(self) -> None:
        self.match.active_player_id = fielded(
            self.match, PlayerRole.MIDFIELDER,
        )
        result = begin_own_goal_roll(
            self.engine, self.game, self.match, distance_moved=2,
        )
        self.assertTrue(self.match.pending_own_goal)
        self.assertEqual(self.match.pending_own_goal_distance, 2)
        self.assertEqual(result.next.kind, PromptKind.OWN_GOAL_ROLL)
        self.assertIn("Own goal risk!", result.next.ask)


class RunBackFlowTests(SpineFixture):
    """The cascade, and the three ways out of it."""

    def test_a_resolution_that_kept_possession_runs_nobody_back(
        self,
    ) -> None:
        result = begin_run_back(
            self.engine, self.game, self.match, turnover_occurred=False,
        )
        self.assertFalse(self.match.pending_run_back)
        self.assertEqual(
            self.follow_on(result), FollowOnStep.FINISH_MANEUVER_RESOLUTION,
        )

    def test_a_turnover_under_last_possession_ends_the_period(self) -> None:
        self.match.scoreboard.last_possession = True
        result = begin_run_back(self.engine, self.game, self.match)
        self.assertEqual(self.follow_on(result), FollowOnStep.END_PERIOD)
        self.assertFalse(self.match.pending_run_back)

    def test_a_steal_arms_the_run_back_and_the_charge_up(self) -> None:
        result = begin_run_back(
            self.engine, self.game, self.match, distance_moved=3,
        )
        self.assertTrue(self.match.pending_run_back)
        self.assertEqual(self.match.pending_run_back_distance, 3)
        # Charge-up is armed here and awarded at the end, because who
        # actually moved is only known once the cascade has run.
        self.assertTrue(self.match.pending_run_back_charge_up)
        self.assertEqual(
            self.follow_on(result), FollowOnStep.ANNOUNCE_RUN_BACK,
        )

    def test_a_new_play_resets_and_triggers_no_charge_up(self) -> None:
        result = begin_run_back(
            self.engine, self.game, self.match, new_play=True,
        )
        self.assertFalse(self.match.pending_run_back_charge_up)
        self.assertIsNone(self.match.ball_carrier_id)
        self.assertIn("# New play", result.narration[0])

    def test_the_carrier_is_exempt_and_read_off_the_match(self) -> None:
        """
        The exemption is `ball_carrier_id` rather than an argument,
        because the two are the same fact: a run back that moved the
        ball's holder would run them off the ball and charge them for
        it.
        """
        carrier = fielded(self.match, PlayerRole.MIDFIELDER)
        self.match.set_ball_carrier(carrier)
        begin_run_back(self.engine, self.game, self.match)
        self.assertEqual(
            self.match.pending_run_back_stays_player_id, carrier,
        )

    def test_a_new_play_exempts_nobody(self) -> None:
        self.match.set_ball_carrier(
            fielded(self.match, PlayerRole.MIDFIELDER),
        )
        begin_run_back(self.engine, self.game, self.match, new_play=True)
        self.assertIsNone(self.match.pending_run_back_stays_player_id)

    def test_the_cascade_ends_by_naming_finish_run_back(self) -> None:
        """
        Nobody is displaced straight off a kickoff, so the cascade
        finds nothing to do and falls through in one pass.
        """
        self.match.pending_run_back = True
        results = list(
            run_back_passes(self.engine, self.game, self.match),
        )
        self.assertEqual(
            results[-1].next,
            FollowOn(FollowOnStep.FINISH_RUN_BACK),
        )

    def test_a_settled_run_back_hands_the_turn_on(self) -> None:
        self.match.pending_run_back = True
        self.match.pending_run_back_distance = 2
        self.match.pending_run_back_turnover = True

        result = finish_run_back(self.engine, self.game, self.match)
        self.assertFalse(self.match.pending_run_back)
        following = result.next
        self.assertEqual(
            following.step, FollowOnStep.FINISH_MANEUVER_RESOLUTION,
        )
        # Run-back itself only ever costs exhaustion, never time: the
        # clock cost is the triggering maneuver's own.
        self.assertEqual(following.kwargs["distance_moved"], 2)

    def test_a_steal_owes_its_speed_choice_at_the_end(self) -> None:
        stealer = self.match.visiting.field_players[0]
        self.match.pending_run_back = True
        self.match.pending_run_back_speed_choice = True
        self.match.pending_run_back_stays_player_id = stealer

        result = finish_run_back(self.engine, self.game, self.match)
        following = result.next
        self.assertEqual(following.step, FollowOnStep.OFFER_SPEED_CHOICE)
        self.assertEqual(following.kwargs["player_id"], stealer)
        self.assertFalse(self.match.pending_run_back_speed_choice)

    def test_an_out_of_bounds_ball_owes_the_pickup_first(self) -> None:
        self.match.pending_run_back = True
        self.match.pending_ball_recovery = True
        self.match.set_ball_space(Zone.MIDFIELD, 2)

        result = finish_run_back(self.engine, self.game, self.match)
        self.assertEqual(result.next.kind, PromptKind.BALL_RECOVERY)

    def test_a_reset_that_already_covers_the_ball_asks_nobody(
        self,
    ) -> None:
        """
        "Unless one of theirs is already on it": a reset can perfectly
        well put one of the gaining side on the ball's space by itself.
        """
        self.match.pending_ball_recovery = True
        self.assertTrue(self.match.eligible_ball_handlers())

        result = begin_ball_recovery(self.engine, self.game, self.match)
        self.assertFalse(self.match.pending_ball_recovery)
        self.assertEqual(
            self.follow_on(result), FollowOnStep.FINISH_MANEUVER_RESOLUTION,
        )

    def test_the_new_play_reset_ends_a_double_team(self) -> None:
        """
        "So long as it's not a new play, on their next maneuver, both
        defending players challenge" -- cleared here rather than in
        `reset_maneuver`, which runs at the end of every turn including
        the one that set it.
        """
        self.match.pending_double_team = ["a", "b"]
        announce_new_play_reset(self.engine, self.game, self.match)
        self.assertEqual(self.match.pending_double_team, [])


class TurnFrontHalfTests(SpineFixture):
    """Who challenges, what each side picked, and which card won."""

    def arm(self) -> None:
        self.match.active_player_id = fielded(
            self.match, PlayerRole.MIDFIELDER,
        )

    def test_an_auto_challenger_is_applied_and_handed_on(self) -> None:
        self.arm()
        challenger = self.match.contest_candidates(
            self.match.defending_side(),
        )[0]
        result = auto_resolve_challenger(
            self.engine, self.game, self.match, challenger,
        )
        self.assertEqual(self.match.challenger_id, challenger)
        self.assertEqual(
            self.follow_on(result),
            FollowOnStep.BEGIN_MANEUVER_ACTION_SELECTION,
        )

    def test_an_unchallenged_maneuver_says_which_of_the_two_it_was(
        self,
    ) -> None:
        """
        The message asks the state rather than taking a flag: anyone
        still eligible means the defense was offered the challenge and
        sent nobody.
        """
        self.arm()
        result = announce_uncontested_maneuver(
            self.engine, self.game, self.match,
        )
        self.assertIn("Unchallenged!", result.narration[0])
        self.assertIn("sent nobody in to challenge", result.narration[0])

    def test_an_uncontested_pick_is_its_own_winner(self) -> None:
        self.arm()
        self.match.maneuver_uncontested = True
        self.match.offense_maneuver = "low_pass"

        result = resolve_maneuver(self.engine, self.game, self.match)
        following = result.next
        self.assertEqual(
            following.step, FollowOnStep.BEGIN_EFFECT_RESOLUTION,
        )
        self.assertEqual(following.kwargs["winner_key"], "low_pass")
        self.assertIn("unchallenged", result.narration[0])

    def test_a_decisive_win_names_the_card(self) -> None:
        self.arm()
        self.match.challenger_id = self.match.visiting.field_players[0]
        self.match.offense_maneuver = "low_pass"
        self.match.defense_maneuver = "pressure"

        result = resolve_maneuver(self.engine, self.game, self.match)
        self.assertEqual(
            result.next.kwargs["winner_key"], "low_pass",
        )
        self.assertIn("wins!", result.narration[0])

    def test_a_tie_goes_to_a_skill_test_and_says_so(self) -> None:
        self.arm()
        self.match.challenger_id = self.match.visiting.field_players[0]
        self.match.offense_maneuver = "low_pass"
        self.match.defense_maneuver = "deflect"

        result = resolve_maneuver(self.engine, self.game, self.match)
        following = result.next
        self.assertEqual(
            following.step, FollowOnStep.BEGIN_MANEUVER_SKILL_TEST,
        )
        # **The headline is an argument, not narration**: the skill
        # test embeds it in its own reveal rather than posting it
        # above one, so carrying it as a line would say it twice.
        self.assertEqual(result.narration, [])
        self.assertIn("skill test!", following.kwargs["headline"])


class SpineSurvivesASaveTests(SpineFixture):
    """
    Every state the spine can leave a match in reads back the same.

    A step that ends in a prompt hands the turn to a click that reloads
    the match out of the save file, so what `pending_prompt` answers
    before the save and after the load has to be the same question --
    otherwise a coach is asked one thing and their click resolves
    another. This is the phase's own version of the guard
    `tests/test_d12ball_prompts.py` puts under the chain itself.
    """

    def setUp(self) -> None:
        super().setUp()
        # Every state below is mid-turn, so the handler is set: the
        # chain reads `active_player_id is None` as the kickoff and
        # would answer that instead of the question being asserted.
        self.match.active_player_id = fielded(
            self.match, PlayerRole.MIDFIELDER,
        )

    def round_trip(self) -> MatchState:
        return MatchState.from_dict(
            self.match.to_dict(), self.engine.basic_ruleset,
        )

    def assert_survives(self, expected: PromptKind) -> None:
        before = pending_prompt(self.engine, self.game, self.match)
        self.assertEqual(before.kind, expected)
        after = pending_prompt(self.engine, self.game, self.round_trip())
        self.assertEqual(after, before)

    def test_a_loose_ball_pick(self) -> None:
        # A genuinely empty space, which is the only kind that is
        # *loose*: a ball coming down where one side is already
        # standing pre-declines the other and settles without asking.
        for player_id in list(self.match.board.spaces[Zone.MIDFIELD][2]):
            self.match.move_meeple(player_id, Zone.MIDFIELD, 0)
        self.match.set_ball_space(Zone.MIDFIELD, 2)
        self.game.player_2_id = 222
        begin_loose_ball(self.engine, self.game, self.match, 1)
        self.assert_survives(PromptKind.LOOSE_BALL_PICK)

    def test_a_loose_ball_skill_test(self) -> None:
        self.match.set_ball_space(Zone.MIDFIELD, 2)
        self.match.begin_loose_ball(1)
        self.match.loose_ball_offense_player = fielded(
            self.match, PlayerRole.MIDFIELDER,
        )
        self.match.loose_ball_defense_player = (
            self.match.visiting.field_players[0]
        )
        resolve_loose_ball(self.engine, self.game, self.match)
        self.assert_survives(PromptKind.LOOSE_BALL_SKILL_TEST)

    def test_an_own_goal_roll(self) -> None:
        begin_own_goal_roll(self.engine, self.game, self.match, 1)
        self.assert_survives(PromptKind.OWN_GOAL_ROLL)

    def test_a_ball_recovery(self) -> None:
        self.match.pending_run_back = True
        self.match.pending_ball_recovery = True
        self.match.set_ball_space(Zone.MIDFIELD, 2)
        finish_run_back(self.engine, self.game, self.match)
        self.assert_survives(PromptKind.BALL_RECOVERY)

    def test_a_run_back_that_stopped_to_ask(self) -> None:
        """
        The state the cascade's per-pass save exists for: the run back
        is armed and somebody is displaced, so the next click reloads
        the match and has to find the same question.
        """
        displaced = fielded(self.match, PlayerRole.FULLBACK)
        self.match.move_meeple(displaced, Zone.VISITORS_GOAL, 0)
        self.match.pending_run_back = True
        self.match.pending_run_back_distance = 1
        self.match.pending_run_back_turnover = True
        self.game.player_2_id = 222
        self.assert_survives(PromptKind.RUN_BACK_SPACE)


if __name__ == "__main__":
    unittest.main()
