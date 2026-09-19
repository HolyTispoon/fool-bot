"""
The substitution window's flow through the cog: who is offered it,
what a pass costs the other side, and what the AI does with one.

The engine's own rules -- which pool a player comes from, what a
returning player keeps -- are covered in test_d12ball_components.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

from cogs.d12ball import D12Ball
from d12ball.ai import DinkyAI
from d12ball.components import (
    CoachingOccasion,
    MatchState,
    PlayerRole,
    TeamSide,
    Zone,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.engine import RulesEngine
from d12ball.game import D12BallGame, GameMode, Team
from roster import benched, fielded
from save_patches import suppressed_cog_saves


def build_cog() -> D12Ball:
    cog = object.__new__(D12Ball)
    cog.games = {}
    cog.player_catalog = load_player_catalog()
    cog.basic_ruleset = load_basic_ruleset()
    cog.maneuver_catalog = load_maneuver_catalog()
    cog.team_emojis = {}
    cog.condition_emojis = {}
    cog.engine = RulesEngine(
        cog.player_catalog, cog.basic_ruleset, cog.maneuver_catalog, {},
    )
    cog.announce_run_back = mock.AsyncMock()
    cog.begin_substitution_window = mock.AsyncMock()
    return cog


def build_basic_game() -> D12BallGame:
    """
    A plain basic-mode game, for the calls that now take one.

    Charging exhaustion needs a game because the Exhausted threshold is
    a Cyborg's own in a game playing the species abilities -- see
    `RulesEngine.exhaustion_threshold`. Nothing in this file is about
    that, so a basic game is exactly right: every player there is
    Exhausted on their own defensive skill, which is what these tests
    assert.
    """
    return D12BallGame(
        game_id="g1",
        game_number=1,
        guild_id=1,
        channel_id=2,
        message_id=None,
        player_1_id=111,
        player_2_id=222,
        player_1_team=Team.ORANGE,
        player_2_team=Team.PURPLE,
    )


class SubstitutionHandoffTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    def build_match(self) -> MatchState:
        return MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=6,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
        )

    async def finish(self, cog, match) -> SimpleNamespace:
        game = SimpleNamespace(match_state=None, game_id="g")
        interaction = SimpleNamespace(
            followup=SimpleNamespace(send=mock.AsyncMock())
        )
        with suppressed_cog_saves():
            await cog.finish_substitution_window(interaction, game, match)
        return game

    async def test_a_declaration_hands_the_other_team_a_reply(self) -> None:
        cog = build_cog()
        match = self.build_match()
        match.open_coaching_window(TeamSide.HOME, CoachingOccasion.NEW_PLAY)
        match.declare_coaching()

        await self.finish(cog, match)

        cog.begin_substitution_window.assert_awaited_once()
        self.assertEqual(
            cog.begin_substitution_window.await_args.args[3],
            TeamSide.VISITING,
        )
        self.assertTrue(
            cog.begin_substitution_window.await_args.kwargs["is_response"]
        )
        cog.announce_run_back.assert_not_awaited()

    async def test_passing_takes_the_other_team_reply_with_it(self) -> None:
        cog = build_cog()
        match = self.build_match()
        match.open_coaching_window(TeamSide.HOME, CoachingOccasion.NEW_PLAY)

        await self.finish(cog, match)

        # No declaration happened, so there is nothing for the other
        # team to answer -- straight on to the run back.
        cog.begin_substitution_window.assert_not_awaited()
        cog.announce_run_back.assert_awaited_once()
        self.assertTrue(match.may_take_time_out(TeamSide.HOME))

    async def test_a_reply_ends_the_window(self) -> None:
        cog = build_cog()
        match = self.build_match()
        match.open_coaching_window(TeamSide.VISITING, CoachingOccasion.NEW_PLAY, is_response=True)
        match.declare_coaching()

        await self.finish(cog, match)

        # A reply never bounces back for another reply.
        cog.begin_substitution_window.assert_not_awaited()
        cog.announce_run_back.assert_awaited_once()
        self.assertIsNone(match.pending_coaching_side)


class SubstitutionSummaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    def build_match(self) -> MatchState:
        return MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=6,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
        )

    def test_a_swap_spends_one_of_the_allowance(self) -> None:
        cog = build_cog()
        match = self.build_match()
        match.open_coaching_window(TeamSide.HOME, CoachingOccasion.NEW_PLAY)
        match.declare_coaching()

        text = cog.apply_substitution(
            build_basic_game(),
            match,
            TeamSide.HOME,
            fielded(match, PlayerRole.DEFENDER),
            match.home.team_board.bench[0],
        )

        self.assertEqual(match.pending_coaching_substitutions, 1)
        self.assertEqual(match.substitutions_remaining(), 1)
        self.assertIn("comes on for", text)
        self.assertIn("1 substitution left", text)

    def test_an_injured_player_is_named_as_such(self) -> None:
        cog = build_cog()
        match = self.build_match()
        match.open_coaching_window(TeamSide.HOME, CoachingOccasion.NEW_PLAY)
        match.declare_coaching()
        match.mark_injured(fielded(match, PlayerRole.STRIKER))

        text = cog.apply_substitution(
            build_basic_game(),
            match,
            TeamSide.HOME,
            fielded(match, PlayerRole.STRIKER),
            match.home.team_board.bench[0],
        )

        self.assertIn("(injured)", text)

    def test_a_returning_player_reports_what_is_left(self) -> None:
        cog = build_cog()
        match = self.build_match()
        returning = fielded(match, PlayerRole.FULLBACK)
        match.add_exhaustion(returning, 5)

        match.open_coaching_window(TeamSide.HOME, CoachingOccasion.NEW_PLAY)
        match.declare_coaching()
        for outgoing in (
            returning,
            fielded(match, PlayerRole.MIDFIELDER),
            fielded(match, PlayerRole.PLAYMAKER),
        ):
            match.substitute(
                TeamSide.HOME, outgoing, match.home.team_board.bench[0],
            )
        match.mark_injured(fielded(match, PlayerRole.STRIKER))

        text = cog.apply_substitution(
            build_basic_game(),
            match,
            TeamSide.HOME,
            fielded(match, PlayerRole.STRIKER),
            returning,
        )

        # 5 tokens, half rounded up removed, 2 left -- and a fullback
        # has a defensive skill of 6, so 2 is nowhere near Exhausted.
        self.assertEqual(match.exhaustion[returning], 2)
        self.assertIn("back bench", text)
        self.assertIn("2 exhaustion tokens", text)
        self.assertNotIn("Still **Exhausted**", text)

    def test_rearranging_is_free(self) -> None:
        cog = build_cog()
        match = self.build_match()
        match.open_coaching_window(TeamSide.HOME, CoachingOccasion.NEW_PLAY)
        match.declare_coaching()

        text = cog.apply_position_swap(
            match,
            TeamSide.HOME,
            fielded(match, PlayerRole.FULLBACK),
            fielded(match, PlayerRole.STRIKER),
        )

        self.assertEqual(match.exhaustion, {})
        self.assertEqual(match.pending_coaching_substitutions, 0)
        self.assertIn("No exhaustion cost", text)

    def test_a_swap_moves_the_meeples_with_the_cards(self) -> None:
        # A zone assignment used to reassign the cards and leave both
        # meeples where they stood, displaced, for a placement step or
        # the next run back to collect. It now trades the spaces too,
        # which is what lets a Coaching Choice guarantee no meeple ever
        # stands outside its own zone.
        cog = build_cog()
        match = self.build_match()
        match.open_coaching_window(TeamSide.HOME, CoachingOccasion.NEW_PLAY)
        match.declare_coaching()
        player_id = fielded(match, PlayerRole.FULLBACK)
        other_player_id = fielded(match, PlayerRole.STRIKER)
        before = match.board.meeple_position(player_id)
        other_before = match.board.meeple_position(other_player_id)

        cog.apply_position_swap(
            match, TeamSide.HOME, player_id, other_player_id,
        )

        self.assertEqual(
            match.board.meeple_position(player_id), other_before,
        )
        self.assertEqual(
            match.board.meeple_position(other_player_id), before,
        )
        for candidate in (player_id, other_player_id):
            self.assertEqual(
                match.board.meeple_position(candidate)[0],
                match.home.assigned_zone(candidate),
            )

    def test_apply_reposition_moves_a_meeple_for_free(self) -> None:
        # A 6-board's zones are exactly full (2-2-2, no slack), so a
        # swap alone never leaves an open space to step into -- this
        # exercises apply_reposition against a player who's simply
        # wandered out of position, the case it's actually built for.
        cog = build_cog()
        match = self.build_match()
        match.open_coaching_window(TeamSide.HOME, CoachingOccasion.NEW_PLAY)
        match.declare_coaching()
        player_id = fielded(match, PlayerRole.DEFENDER)
        zone = match.home.assigned_zone(player_id)
        # Displace them out of their own zone first, the way a
        # maneuver would mid-game, so their zone has an open space to
        # reposition back into.
        match.board.remove_meeple(player_id)
        other_zone = next(z for z in Zone if z != zone)
        match.board.place_meeple(player_id, other_zone, 0)
        open_space = match.open_spaces_in_zone(TeamSide.HOME, zone)[0]

        text = cog.apply_reposition(
            match, TeamSide.HOME, player_id, open_space,
        )

        self.assertEqual(
            match.board.meeple_position(player_id), (zone, open_space),
        )
        self.assertEqual(match.exhaustion, {})
        self.assertIn("No exhaustion cost", text)

    def test_a_swap_needs_no_open_space_on_a_packed_board(self) -> None:
        # Board 6's zones are exactly full under 2-2-2, so neither
        # player has anywhere to step into until the other vacates.
        # An even exchange never needs an intermediate space, which is
        # why the zone assignment is one and not two moves.
        cog = build_cog()
        match = self.build_match()
        match.open_coaching_window(TeamSide.HOME, CoachingOccasion.NEW_PLAY)
        match.declare_coaching()
        player_id = fielded(match, PlayerRole.FULLBACK)
        other_player_id = fielded(match, PlayerRole.STRIKER)

        text = cog.apply_position_swap(
            match, TeamSide.HOME, player_id, other_player_id,
        )

        for candidate in (player_id, other_player_id):
            zone = match.home.assigned_zone(candidate)
            self.assertEqual(
                match.board.meeple_position(candidate)[0], zone,
            )
            self.assertEqual(
                match.open_spaces_in_zone(TeamSide.HOME, zone), [],
            )
        self.assertEqual(match.exhaustion, {})
        self.assertIn("No exhaustion cost", text)


class DinkySubstitutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()
        cls.ai = DinkyAI(cls.catalog, load_maneuver_catalog())

    def build_match(self) -> MatchState:
        return MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=6,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
        )

    def test_dinky_passes_on_a_healthy_team(self) -> None:
        match = self.build_match()
        self.assertIsNone(
            self.ai.choose_substitution(match, TeamSide.HOME)
        )

    def test_dinky_gets_an_injured_player_off(self) -> None:
        match = self.build_match()
        match.mark_injured(fielded(match, PlayerRole.STRIKER))

        choice = self.ai.choose_substitution(match, TeamSide.HOME)

        self.assertIsNotNone(choice)
        outgoing, incoming = choice
        self.assertEqual(outgoing, fielded(match, PlayerRole.STRIKER))
        self.assertIn(incoming, match.home.team_board.bench)

    def test_dinky_brings_on_the_same_role(self) -> None:
        # A striker for a striker, over the defender the bench lists
        # first.
        match = self.build_match()
        match.mark_injured(fielded(match, PlayerRole.STRIKER))

        _, incoming = self.ai.choose_substitution(match, TeamSide.HOME)

        self.assertEqual(incoming, benched(match, PlayerRole.STRIKER))

    def test_dinky_brings_on_the_closest_role_when_it_must(self) -> None:
        # Nobody on the bench is a fullback, and the defender is the
        # next role along the spectrum.
        match = self.build_match()
        match.mark_injured(fielded(match, PlayerRole.FULLBACK))

        _, incoming = self.ai.choose_substitution(match, TeamSide.HOME)

        self.assertEqual(incoming, benched(match, PlayerRole.DEFENDER))

    def test_dinky_breaks_a_role_tie_on_bench_order(self) -> None:
        # A winger sits one step from both the playmaker and the
        # striker, so the tie goes to whichever of the two the bench
        # lists first -- read off the bench rather than written down,
        # since the order is the roster's and the roster is data.
        match = self.build_match()
        match.mark_injured(fielded(match, PlayerRole.WINGER))
        tied = {
            benched(match, PlayerRole.PLAYMAKER),
            benched(match, PlayerRole.STRIKER),
        }
        first_of_the_two = next(
            player_id
            for player_id in match.home.team_board.bench
            if player_id in tied
        )

        _, incoming = self.ai.choose_substitution(match, TeamSide.HOME)

        self.assertEqual(incoming, first_of_the_two)

    def test_dinky_matches_roles_off_the_back_bench_too(self) -> None:
        # The same question, asked of the other pool. Three swaps
        # drain the bench and put a fullback, a defender and a
        # playmaker on the back bench; an injured striker takes the
        # playmaker, who is the nearest of the three.
        match = self.build_match()
        for outgoing in (
            fielded(match, PlayerRole.FULLBACK),
            fielded(match, PlayerRole.DEFENDER),
            fielded(match, PlayerRole.PLAYMAKER),
        ):
            match.substitute(
                TeamSide.HOME, outgoing, match.home.team_board.bench[0],
            )
        match.mark_injured(fielded(match, PlayerRole.STRIKER))

        _, incoming = self.ai.choose_substitution(match, TeamSide.HOME)

        self.assertIn(incoming, match.home.team_board.back_bench)
        self.assertEqual(incoming, fielded(match, PlayerRole.PLAYMAKER))

    def test_dinky_passes_when_there_is_nobody_to_bring_on(self) -> None:
        match = self.build_match()
        for outgoing in (
            fielded(match, PlayerRole.FULLBACK),
            fielded(match, PlayerRole.MIDFIELDER),
            fielded(match, PlayerRole.PLAYMAKER),
        ):
            match.substitute(
                TeamSide.HOME, outgoing, match.home.team_board.bench[0],
            )
        match.mark_injured(fielded(match, PlayerRole.STRIKER))

        # The bench has drained, so the back bench is the pool now.
        self.assertIsNotNone(
            self.ai.choose_substitution(match, TeamSide.HOME)
        )

        # Injure everyone on it and there is genuinely nobody left:
        # injury is what closes a bench, not who is going off.
        for player_id in list(match.home.team_board.back_bench):
            match.injured.add(player_id)
        self.assertIsNone(
            self.ai.choose_substitution(match, TeamSide.HOME)
        )


class ContinueRunBackKickoffFillTests(unittest.IsolatedAsyncioTestCase):
    """
    continue_run_back's handling of a goal restart that left the
    kickoff space empty -- the scenario that used to send match state
    into a loose-ball detour with a stale active_player_id and trip
    validate() on the next reload.
    """

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

    def build_cog(self) -> D12Ball:
        cog = object.__new__(D12Ball)
        cog.games = {}
        cog.player_catalog = self.catalog
        cog.basic_ruleset = self.rules
        cog.team_emojis = {}
        cog.condition_emojis = {}
        cog.engine = RulesEngine(cog.player_catalog, cog.basic_ruleset, None, {})
        cog.refresh_match_image = mock.AsyncMock()
        cog.finish_maneuver_resolution = mock.AsyncMock()
        return cog

    async def test_kickoff_is_filled_before_run_back_finishes(self) -> None:
        cog = self.build_cog()
        match = self.build_match()
        visiting_midfield = match.visiting.zones[Zone.MIDFIELD]
        for player_id, space_index in zip(visiting_midfield, (0, 2)):
            match.board.remove_meeple(player_id)
            match.board.place_meeple(player_id, Zone.MIDFIELD, space_index)

        match.restart_after_goal(TeamSide.VISITING)
        self.assertTrue(match.pending_kickoff_fill)
        self.assertEqual(match.eligible_ball_handlers(), [])

        match.pending_run_back = True
        match.pending_run_back_distance = 3
        match.pending_run_back_turnover = True

        game = SimpleNamespace(
            match_state=match.to_dict(),
            game_id="g",
            mode=GameMode.BASIC,
            advanced_maneuvers=True,
            species_abilities=True,
        )
        interaction = SimpleNamespace(
            response=SimpleNamespace(is_done=lambda: True),
            channel=SimpleNamespace(send=mock.AsyncMock()),
            followup=SimpleNamespace(send=mock.AsyncMock()),
        )

        with suppressed_cog_saves():
            await cog.continue_run_back(interaction, game, match)

        self.assertFalse(match.pending_kickoff_fill)
        self.assertFalse(match.pending_run_back)
        self.assertNotEqual(match.eligible_ball_handlers(), [])
        cog.finish_maneuver_resolution.assert_awaited_once()
        sent = interaction.channel.send.await_args_list[0].args[0]
        self.assertIn("start the kickoff", sent)


if __name__ == "__main__":
    unittest.main()
