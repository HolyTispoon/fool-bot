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
    TeamSide,
    Zone,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.game import Team


def build_cog() -> D12Ball:
    cog = object.__new__(D12Ball)
    cog.games = {}
    cog.player_catalog = load_player_catalog()
    cog.team_emojis = {}
    cog.condition_emojis = {}
    cog.announce_run_back = mock.AsyncMock()
    cog.begin_substitution_window = mock.AsyncMock()
    return cog


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
        with mock.patch("cogs.d12ball.save_games"):
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
        self.assertTrue(match.may_declare_coaching(TeamSide.HOME))

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
            match,
            TeamSide.HOME,
            "orange_blazebulk",
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
        match.mark_injured("orange_kindlefoot")

        text = cog.apply_substitution(
            match,
            TeamSide.HOME,
            "orange_kindlefoot",
            match.home.team_board.bench[0],
        )

        self.assertIn("(injured)", text)

    def test_a_returning_player_reports_what_is_left(self) -> None:
        cog = build_cog()
        match = self.build_match()
        returning = "orange_hellguard"
        match.add_exhaustion(returning, 5)

        match.open_coaching_window(TeamSide.HOME, CoachingOccasion.NEW_PLAY)
        match.declare_coaching()
        for outgoing in (returning, "orange_sizzik", "orange_scorchit"):
            match.substitute(
                TeamSide.HOME, outgoing, match.home.team_board.bench[0],
            )
        match.mark_injured("orange_kindlefoot")

        text = cog.apply_substitution(
            match, TeamSide.HOME, "orange_kindlefoot", returning,
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
            match, TeamSide.HOME, "orange_hellguard", "orange_kindlefoot",
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
        player_id, other_player_id = "orange_hellguard", "orange_kindlefoot"
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
        player_id = "orange_blazebulk"
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
        player_id, other_player_id = "orange_hellguard", "orange_kindlefoot"

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
        match.mark_injured("orange_kindlefoot")

        choice = self.ai.choose_substitution(match, TeamSide.HOME)

        self.assertIsNotNone(choice)
        outgoing, incoming = choice
        self.assertEqual(outgoing, "orange_kindlefoot")
        self.assertIn(incoming, match.home.team_board.bench)

    def test_dinky_passes_when_there_is_nobody_to_bring_on(self) -> None:
        match = self.build_match()
        for outgoing in ("orange_hellguard", "orange_sizzik", "orange_scorchit"):
            match.substitute(
                TeamSide.HOME, outgoing, match.home.team_board.bench[0],
            )
        match.mark_injured("orange_kindlefoot")

        # The bench is empty, so the back bench opens -- but everyone
        # on it was subbed out, which is exactly who may come back for
        # an injury.
        self.assertIsNotNone(
            self.ai.choose_substitution(match, TeamSide.HOME)
        )

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
        cog.team_emojis = {}
        cog.condition_emojis = {}
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

        game = SimpleNamespace(match_state=match.to_dict(), game_id="g")
        interaction = SimpleNamespace(
            followup=SimpleNamespace(send=mock.AsyncMock())
        )

        with mock.patch("cogs.d12ball.save_games"):
            await cog.continue_run_back(interaction, game, match)

        self.assertFalse(match.pending_kickoff_fill)
        self.assertFalse(match.pending_run_back)
        self.assertNotEqual(match.eligible_ball_handlers(), [])
        cog.finish_maneuver_resolution.assert_awaited_once()
        sent = interaction.followup.send.await_args_list[0].args[0]
        self.assertIn("start the kickoff", sent)


if __name__ == "__main__":
    unittest.main()
