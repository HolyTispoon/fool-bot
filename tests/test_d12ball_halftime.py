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
from d12ball.components import (
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
        self.assertEqual(match.pending_halftime_stage, "subs_home")
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
        match.pending_halftime_stage = "subs_home"
        match.open_substitution_window(TeamSide.HOME)
        match.declare_substitution()

        with mock.patch("cogs.d12ball.save_games"):
            await cog.finish_substitution_window(
                build_interaction(), game, match,
            )

        # Halftime never offers the other side a "response" the way a
        # turnover does, and never falls through to a run back.
        cog.begin_substitution_window.assert_not_awaited()
        cog.announce_run_back.assert_not_awaited()
        cog.advance_halftime_stage.assert_awaited_once()
        self.assertEqual(match.pending_halftime_stage, "subs_visiting")

    async def test_a_window_used_for_nothing_still_advances_the_stage(
        self,
    ) -> None:
        # Halftime has no "pass" -- a side that wants no changes just
        # finishes the menu, which lands here the same way.
        cog = build_cog()
        game = build_human_game()
        match = self.build_match()
        match.pending_halftime_stage = "subs_visiting"
        match.open_substitution_window(TeamSide.VISITING)

        with mock.patch("cogs.d12ball.save_games"):
            await cog.finish_substitution_window(
                build_interaction(), game, match,
            )

        cog.begin_substitution_window.assert_not_awaited()
        cog.announce_run_back.assert_not_awaited()
        self.assertEqual(match.pending_halftime_stage, "reposition_home")

    async def test_halftime_substitutes_without_asking_or_charging(
        self,
    ) -> None:
        # Nobody is asked whether to declare: the menu comes straight
        # up. And the window is free -- the side keeps its once-a-half
        # declaration for the second half's open play.
        cog = build_cog()
        del cog.begin_substitution_window  # exercise the real one
        cog.prompt_substitution_menu = mock.AsyncMock()
        game = build_human_game()
        match = self.build_match()
        match.pending_halftime_stage = "subs_home"
        interaction = build_interaction()

        with mock.patch("cogs.d12ball.save_games"):
            await cog.begin_halftime_substitutions(
                interaction, game, match, TeamSide.HOME,
            )

        self.assertEqual(match.pending_substitution_side, "home")
        self.assertTrue(match.pending_substitution_declared)
        self.assertEqual(match.declared_substitution, set())
        self.assertTrue(match.may_declare_substitution(TeamSide.HOME))
        # No declare-or-pass prompt of its own -- the menu carries the
        # window's heading instead.
        interaction.followup.send.assert_not_awaited()
        cog.prompt_substitution_menu.assert_awaited_once()
        _, kwargs = cog.prompt_substitution_menu.await_args
        self.assertIn("Substitutions", kwargs["lead_in"])

    async def test_an_ordinary_window_still_spends_the_declaration(
        self,
    ) -> None:
        # Regression guard: only halftime's window is free.
        match = self.build_match()
        match.open_substitution_window(TeamSide.HOME)
        match.declare_substitution()

        self.assertEqual(match.declared_substitution, {"home"})
        self.assertFalse(match.may_declare_substitution(TeamSide.HOME))

    def test_a_free_window_survives_a_save_and_reload(self) -> None:
        match = self.build_match()
        match.open_substitution_window(
            TeamSide.HOME, spends_declaration=False,
        )

        reloaded = MatchState.from_dict(match.to_dict(), self.rules)

        self.assertFalse(reloaded.pending_substitution_spends_declaration)
        reloaded.declare_substitution()
        self.assertEqual(reloaded.declared_substitution, set())

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
        match.open_substitution_window(TeamSide.HOME)
        match.declare_substitution()

        with mock.patch("cogs.d12ball.save_games"):
            await cog.finish_substitution_window(
                build_interaction(), game, match,
            )

        cog.begin_substitution_window.assert_awaited_once()
        cog.advance_halftime_stage.assert_not_awaited()


class HalftimeRepositionTests(unittest.IsolatedAsyncioTestCase):
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
        # visiting meeple off of it so the AI has something to fix.
        kickoff_index = kickoff_space_index(
            len(match.board.spaces[Zone.MIDFIELD]), TeamSide.VISITING,
        )
        match.ball.zone = Zone.MIDFIELD
        match.ball.space_index = kickoff_index
        for player_id in list(match.board.spaces[Zone.MIDFIELD][kickoff_index]):
            if player_id in match.visiting.field_players:
                match.board.remove_meeple(player_id)
                match.board.place_meeple(player_id, Zone.MIDFIELD, 0)
        return match

    async def test_ai_visiting_side_fills_an_empty_kickoff_space(
        self,
    ) -> None:
        cog = build_cog()
        game = build_solo_game()
        match = self.build_match()
        match.pending_halftime_stage = "reposition_visiting"
        self.assertFalse(match.kickoff_space_occupied_by(TeamSide.VISITING))

        with mock.patch("cogs.d12ball.save_games"):
            await cog.begin_halftime_reposition(
                build_interaction(), game, match, TeamSide.VISITING,
            )

        self.assertTrue(match.kickoff_space_occupied_by(TeamSide.VISITING))
        self.assertIsNone(match.pending_halftime_stage)
        cog.advance_halftime_stage.assert_awaited_once()

    async def test_ai_home_side_does_not_need_the_kickoff_space(
        self,
    ) -> None:
        cog = build_cog()
        game = build_solo_game_home_ai()
        match = self.build_match()
        match.pending_halftime_stage = "reposition_home"

        with mock.patch("cogs.d12ball.save_games"):
            await cog.begin_halftime_reposition(
                build_interaction(), game, match, TeamSide.HOME,
            )

        # Home's AI reposition doesn't touch the kickoff space at all,
        # and just moves on to visiting's own reposition stage.
        self.assertEqual(match.pending_halftime_stage, "reposition_visiting")
        cog.advance_halftime_stage.assert_awaited_once()


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

    def test_reposition_meeple_anywhere_moves_across_zones(self) -> None:
        match = self.build_match()
        player_id = match.home.field_players[0]
        # Board 9's 2-2-2 setup only fills 2 of Visitors Goal's 3
        # spaces for home, leaving index 2 open regardless of which
        # player is being moved.
        open_index = match.open_spaces_in_zone(
            TeamSide.HOME, Zone.VISITORS_GOAL,
        )[0]

        match.reposition_meeple_anywhere(
            TeamSide.HOME, player_id, Zone.VISITORS_GOAL, open_index,
        )

        self.assertEqual(
            match.board.meeple_position(player_id),
            (Zone.VISITORS_GOAL, open_index),
        )

    def test_reposition_meeple_anywhere_rejects_a_teammates_space(
        self,
    ) -> None:
        match = self.build_match()
        mover, occupant = match.home.field_players[:2]
        zone, space_index = match.board.meeple_position(occupant)

        with self.assertRaises(ValueError):
            match.reposition_meeple_anywhere(
                TeamSide.HOME, mover, zone, space_index,
            )

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
