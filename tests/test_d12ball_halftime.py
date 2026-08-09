"""
Halftime resolution: automatic exhaustion recovery, each side's
extra-token choice, each side's own substitution window, and free
meeple repositioning gated on the visiting team covering the
second-half kickoff space. See "The clock, halftime and full time"
in docs/living-rules.md
and D12Ball.begin_halftime in cogs/d12ball.py.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

from cogs.d12ball import HALFTIME_STAGES, D12Ball
from cogs.d12ball_views import CoachingHubView
from d12ball.components import (
    CoachingOccasion,
    MatchState,
    TeamSide,
    Zone,
    kickoff_space_index,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.game import AIOpponent, D12BallGame, Team


def build_cog() -> D12Ball:
    cog = object.__new__(D12Ball)
    cog.games = {}
    cog.player_catalog = load_player_catalog()
    cog.maneuver_catalog = load_maneuver_catalog()
    cog.basic_ruleset = load_basic_ruleset()
    cog.team_emojis = {}
    cog.condition_emojis = {}
    cog.refresh_match_image = mock.AsyncMock()
    cog.advance_halftime_stage = mock.AsyncMock()
    cog.begin_substitution_window = mock.AsyncMock()
    cog.announce_run_back = mock.AsyncMock()
    return cog


def build_human_game() -> D12BallGame:
    return D12BallGame(
        game_id="g1",
        game_number=1,
        guild_id=1,
        channel_id=1,
        message_id=None,
        player_1_id=111,
        player_2_id=222,
        player_1_team=Team.ORANGE,
        player_2_team=Team.PURPLE,
        home_player_number=1,
        visiting_player_number=2,
    )


def build_solo_game() -> D12BallGame:
    """Visiting (player 2) is AI-controlled; home (player 1) is human."""
    return D12BallGame(
        game_id="g1",
        game_number=1,
        guild_id=1,
        channel_id=1,
        message_id=None,
        player_1_id=111,
        player_2_id=None,
        player_1_team=Team.ORANGE,
        player_2_team=Team.PURPLE,
        home_player_number=1,
        visiting_player_number=2,
        ai_opponent=AIOpponent.DINKY,
    )


def build_solo_game_home_ai() -> D12BallGame:
    """Home (player 2) is AI-controlled; visiting (player 1) is human."""
    return D12BallGame(
        game_id="g1",
        game_number=1,
        guild_id=1,
        channel_id=1,
        message_id=None,
        player_1_id=111,
        player_2_id=None,
        player_1_team=Team.PURPLE,
        player_2_team=Team.ORANGE,
        home_player_number=2,
        visiting_player_number=1,
        ai_opponent=AIOpponent.DINKY,
    )


def build_interaction() -> SimpleNamespace:
    return SimpleNamespace(
        followup=SimpleNamespace(
            send=mock.AsyncMock(return_value=SimpleNamespace(id=999)),
        ),
    )


class HalftimeStageSequenceTests(unittest.TestCase):
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

    def test_a_game_paused_under_the_old_sequence_resumes(self) -> None:
        # Halftime used to run substitutions and free any-zone
        # repositioning as two stages a side, home first. Both map onto
        # that side's single Coaching Choice, so a game paused in
        # either picks up there rather than falling out of halftime.
        cog = build_cog()
        match = self.build_match()

        for legacy, expected in (
            ("subs_home", "coaching_home"),
            ("subs_visiting", "coaching_visiting"),
            ("reposition_home", "coaching_home"),
            ("reposition_visiting", "coaching_visiting"),
        ):
            match.pending_halftime_stage = legacy
            self.assertEqual(cog.halftime_stage(match), expected)

        # And advancing from one lands on the next real stage rather
        # than clearing the sequence.
        match.pending_halftime_stage = "subs_visiting"
        cog.next_halftime_stage(match)
        self.assertEqual(match.pending_halftime_stage, "coaching_home")

    def test_next_halftime_stage_cycles_through_and_terminates(self) -> None:
        cog = build_cog()
        match = self.build_match()
        match.pending_halftime_stage = None

        seen = []
        match.pending_halftime_stage = HALFTIME_STAGES[0]
        while match.pending_halftime_stage is not None:
            seen.append(match.pending_halftime_stage)
            cog.next_halftime_stage(match)

        self.assertEqual(tuple(seen), HALFTIME_STAGES)


class HalftimeRecoveryTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_begin_halftime_recovers_one_token_each_side(self) -> None:
        cog = build_cog()
        game = build_human_game()
        match = self.build_match()

        home_player = match.home.field_players[0]
        visiting_player = match.visiting.field_players[0]
        match.exhaustion[home_player] = 3
        match.exhaustion[visiting_player] = 2

        with mock.patch("cogs.d12ball.save_games"):
            await cog.begin_halftime(build_interaction(), game, match)

        self.assertEqual(match.exhaustion[home_player], 2)
        self.assertEqual(match.exhaustion[visiting_player], 1)
        self.assertEqual(match.pending_halftime_stage, HALFTIME_STAGES[0])
        cog.advance_halftime_stage.assert_awaited_once()

    async def test_begin_halftime_recovery_never_drops_below_zero(
        self,
    ) -> None:
        cog = build_cog()
        game = build_human_game()
        match = self.build_match()
        # No player has any exhaustion at all -- recovery is a no-op.

        with mock.patch("cogs.d12ball.save_games"):
            await cog.begin_halftime(build_interaction(), game, match)

        self.assertEqual(match.exhaustion, {})


class HalftimeExtraTokenTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_ai_side_picks_the_most_exhausted_player(self) -> None:
        cog = build_cog()
        game = build_solo_game()
        match = self.build_match()
        match.pending_halftime_stage = "extra_token_visiting"

        low, high = match.visiting.field_players[:2]
        match.exhaustion[low] = 1
        match.exhaustion[high] = 4

        with mock.patch("cogs.d12ball.save_games"):
            await cog.begin_halftime_extra_token(
                build_interaction(), game, match, TeamSide.VISITING,
            )

        self.assertEqual(match.exhaustion[high], 3)
        self.assertEqual(match.exhaustion[low], 1)
        # The visitors go first at halftime, since they kick off the
        # second half, so home's extra token comes next.
        self.assertEqual(match.pending_halftime_stage, "extra_token_home")
        cog.advance_halftime_stage.assert_awaited_once()

    async def test_human_side_is_prompted_and_does_not_advance_yet(
        self,
    ) -> None:
        cog = build_cog()
        game = build_human_game()
        match = self.build_match()
        match.pending_halftime_stage = "extra_token_home"
        cog.games[game.game_id] = game
        game.match_state = match.to_dict()

        with mock.patch("cogs.d12ball.save_games"):
            await cog.begin_halftime_extra_token(
                build_interaction(), game, match, TeamSide.HOME,
            )

        cog.advance_halftime_stage.assert_not_awaited()
        self.assertEqual(match.pending_halftime_stage, "extra_token_home")


class HalftimeSubstitutionRoutingTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_finishing_a_halftime_window_advances_the_stage(
        self,
    ) -> None:
        cog = build_cog()
        game = build_human_game()
        match = self.build_match()
        match.pending_halftime_stage = "coaching_visiting"
        match.open_coaching_window(
            TeamSide.VISITING, CoachingOccasion.HALFTIME,
        )

        with mock.patch("cogs.d12ball.save_games"):
            await cog.finish_substitution_window(
                build_interaction(), game, match,
            )

        # Halftime never offers the other side a "response" the way a
        # turnover does, and never falls through to a run back.
        cog.begin_substitution_window.assert_not_awaited()
        cog.announce_run_back.assert_not_awaited()
        cog.advance_halftime_stage.assert_awaited_once()
        self.assertEqual(match.pending_halftime_stage, "coaching_home")

    async def test_a_window_used_for_nothing_still_advances_the_stage(
        self,
    ) -> None:
        # Halftime has no "pass" -- a side that wants no changes just
        # finishes the menu, which lands here the same way.
        cog = build_cog()
        game = build_human_game()
        match = self.build_match()
        match.pending_halftime_stage = "coaching_home"
        match.open_coaching_window(TeamSide.HOME, CoachingOccasion.HALFTIME)

        with mock.patch("cogs.d12ball.save_games"):
            await cog.finish_substitution_window(
                build_interaction(), game, match,
            )

        cog.begin_substitution_window.assert_not_awaited()
        cog.announce_run_back.assert_not_awaited()
        self.assertIsNone(match.pending_halftime_stage)

    async def test_halftime_substitutes_without_asking_or_charging(
        self,
    ) -> None:
        # Nobody is asked whether to declare: the hub comes straight
        # up. And the window is free -- the side keeps its once-a-half
        # declaration for the second half's open play.
        cog = build_cog()
        del cog.begin_substitution_window  # exercise the real one
        game = build_human_game()
        cog.games[game.game_id] = game
        match = self.build_match()
        match.pending_halftime_stage = "subs_home"
        game.match_state = match.to_dict()
        interaction = build_interaction()

        with mock.patch("cogs.d12ball.save_games"):
            await cog.begin_halftime_substitutions(
                interaction, game, match, TeamSide.HOME,
            )

        self.assertEqual(match.pending_coaching_side, "home")
        self.assertEqual(
            match.coaching_occasion, CoachingOccasion.HALFTIME,
        )
        self.assertTrue(match.pending_coaching_declared)
        self.assertEqual(match.declared_substitution, set())
        self.assertTrue(match.may_declare_coaching(TeamSide.HOME))

        # One message, carrying the hub rather than a declare-or-pass
        # offer, with the coach's own half of the field attached.
        interaction.followup.send.assert_awaited_once()
        _, kwargs = interaction.followup.send.await_args
        self.assertIsInstance(kwargs["view"], CoachingHubView)
        self.assertIsNotNone(kwargs["file"])

    async def test_an_ordinary_window_still_spends_the_declaration(
        self,
    ) -> None:
        # Regression guard: only halftime's window is free.
        match = self.build_match()
        match.open_coaching_window(TeamSide.HOME, CoachingOccasion.NEW_PLAY)
        match.declare_coaching()

        self.assertEqual(match.declared_substitution, {"home"})
        self.assertFalse(match.may_declare_coaching(TeamSide.HOME))

    def test_a_free_window_survives_a_save_and_reload(self) -> None:
        match = self.build_match()
        match.open_coaching_window(TeamSide.HOME, CoachingOccasion.HALFTIME)

        reloaded = MatchState.from_dict(match.to_dict(), self.rules)

        self.assertEqual(
            reloaded.coaching_occasion, CoachingOccasion.HALFTIME,
        )
        # Halftime's window opens already taken up, so a reload finds a
        # declared window that still cost the side nothing.
        self.assertTrue(reloaded.pending_coaching_declared)
        self.assertEqual(reloaded.declared_substitution, set())
        self.assertTrue(reloaded.may_declare_coaching(TeamSide.HOME))

    async def test_ordinary_turnover_windows_are_unaffected(self) -> None:
        """
        Regression guard: outside of halftime (pending_halftime_stage
        is None), finishing a declared window still hands the other
        side its response, and a pass still falls through to the run
        back -- the pre-existing turnover behavior.
        """
        cog = build_cog()
        game = build_human_game()
        match = self.build_match()
        match.open_coaching_window(TeamSide.HOME, CoachingOccasion.NEW_PLAY)
        match.declare_coaching()

        with mock.patch("cogs.d12ball.save_games"):
            await cog.finish_substitution_window(
                build_interaction(), game, match,
            )

        cog.begin_substitution_window.assert_awaited_once()
        cog.advance_halftime_stage.assert_not_awaited()


class HalftimeKickoffCoverTests(unittest.IsolatedAsyncioTestCase):
    """
    Halftime no longer has a repositioning stage of its own -- the
    Coaching Choice's space positioning covers it. What survives is the
    kickoff-space guarantee: the visitors kick off the second half, so
    somebody of theirs has to be standing on it. A human coach is
    refused Done until they are (coaching_finish_refusal); an AI has no
    menu to be held in, so cover_kickoff_space does it for them.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    def build_match(self) -> MatchState:
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=6,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
        )
        # Move the ball to the second-half kickoff space, the way
        # end_period does before halftime begins, and clear any
        # visiting meeple off of it so there is something to fix.
        kickoff_index = kickoff_space_index(
            len(match.board.spaces[Zone.MIDFIELD]), TeamSide.VISITING,
        )
        match.ball.zone = Zone.MIDFIELD
        match.ball.space_index = kickoff_index
        for player_id in list(
            match.board.spaces[Zone.MIDFIELD][kickoff_index]
        ):
            if player_id in match.visiting.field_players:
                match.board.remove_meeple(player_id)
                match.board.place_meeple(player_id, Zone.MIDFIELD, 0)
        return match

    def test_the_visitors_are_held_until_they_cover_it(self) -> None:
        cog = build_cog()
        match = self.build_match()
        match.open_coaching_window(
            TeamSide.VISITING, CoachingOccasion.HALFTIME,
        )

        refusal = cog.coaching_finish_refusal(match, TeamSide.VISITING)

        self.assertIsNotNone(refusal)
        self.assertIn("kick off", refusal)

    def test_home_is_never_held_at_halftime(self) -> None:
        # Home kicks off the first half, not the second.
        cog = build_cog()
        match = self.build_match()
        match.open_coaching_window(TeamSide.HOME, CoachingOccasion.HALFTIME)

        self.assertIsNone(
            cog.coaching_finish_refusal(match, TeamSide.HOME),
        )

    def test_an_ai_visiting_side_covers_it_itself(self) -> None:
        cog = build_cog()
        match = self.build_match()
        match.open_coaching_window(
            TeamSide.VISITING, CoachingOccasion.HALFTIME,
        )
        self.assertFalse(match.kickoff_space_occupied_by(TeamSide.VISITING))

        note = cog.cover_kickoff_space(match, TeamSide.VISITING)

        self.assertIsNotNone(note)
        self.assertTrue(match.kickoff_space_occupied_by(TeamSide.VISITING))
        # And whoever moved is a midfielder by assignment, so the move
        # stayed inside their own zone the way positioning has to.
        self.assertIsNone(
            cog.coaching_finish_refusal(match, TeamSide.VISITING),
        )

    def test_a_covered_space_is_left_alone(self) -> None:
        cog = build_cog()
        match = self.build_match()
        match.open_coaching_window(
            TeamSide.VISITING, CoachingOccasion.HALFTIME,
        )
        cog.cover_kickoff_space(match, TeamSide.VISITING)

        self.assertIsNone(
            cog.cover_kickoff_space(match, TeamSide.VISITING),
        )


class HalftimeKickoffBoardTests(unittest.IsolatedAsyncioTestCase):
    """
    A half begins with a board, posted and pinned, so the arrangement
    everyone is about to play from is one tap away for the rest of the
    game rather than buried under halftime's own messages.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    async def test_the_second_half_opens_with_a_pinned_board(self) -> None:
        cog = build_cog()
        cog.post_new_play_board = mock.AsyncMock()
        cog.send_turn_prompt = mock.AsyncMock()
        game = build_human_game()
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
        )
        match.pending_halftime_stage = HALFTIME_STAGES[-1]

        with mock.patch("cogs.d12ball.save_games"):
            await cog.finish_halftime(build_interaction(), game, match)

        self.assertIsNone(match.pending_halftime_stage)
        cog.post_new_play_board.assert_awaited_once()
        self.assertIn(
            "second half",
            cog.post_new_play_board.await_args.args[-1],
        )


class HalftimeEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    def build_match(self) -> MatchState:
        # Board 9 gives every zone a spare space under the standard
        # 2-2-2 setup (3 spaces, 2 players), so there's always
        # somewhere open to reposition into across zone boundaries.
        return MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=9,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
        )

    def test_recover_exhaustion_floors_at_zero(self) -> None:
        match = self.build_match()
        player_id = match.home.field_players[0]
        match.exhaustion[player_id] = 1

        removed = match.recover_exhaustion(player_id, 5, defense_skill=3)

        self.assertEqual(removed, 1)
        self.assertNotIn(player_id, match.exhaustion)

    def test_recover_exhaustion_clears_exhausted_below_threshold(
        self,
    ) -> None:
        match = self.build_match()
        player_id = match.home.field_players[0]
        match.exhaustion[player_id] = 5
        match.exhausted.add(player_id)

        # 5 - 1 = 4, still over a defense skill of 3 -- still exhausted.
        match.recover_exhaustion(player_id, 1, defense_skill=3)
        self.assertIn(player_id, match.exhausted)

        # 4 - 1 = 3, no longer over the threshold -- clears.
        match.recover_exhaustion(player_id, 1, defense_skill=3)
        self.assertNotIn(player_id, match.exhausted)

    def test_recover_exhaustion_is_a_no_op_for_injured_players(self) -> None:
        match = self.build_match()
        player_id = match.home.field_players[0]
        match.injured.add(player_id)

        removed = match.recover_exhaustion(player_id, 1, defense_skill=3)

        self.assertEqual(removed, 0)

    def test_kickoff_space_occupied_by_reflects_the_board(self) -> None:
        match = self.build_match()
        home_player = match.home.field_players[0]
        zone, space_index = match.board.meeple_position(home_player)
        match.ball.zone = zone
        match.ball.space_index = space_index

        self.assertTrue(match.kickoff_space_occupied_by(TeamSide.HOME))
        self.assertFalse(match.kickoff_space_occupied_by(TeamSide.VISITING))


if __name__ == "__main__":
    unittest.main()
