"""
How many requests a run back costs Discord.

The rules of the run back are covered in test_d12ball_formations and
test_d12ball_components; what is asserted here is the shape of the
traffic it generates. A steal that scatters a side used to post one
message and re-upload the whole board per player, which is a burst of
a dozen-odd REST calls into one channel with nothing between them --
enough to be rate limited for, and the reason discord.py was logging
"We are being rate limited" mid-game.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

from cogs.d12ball import MAX_RUN_BACK_PASSES, D12Ball
from cogs.d12ball_helpers import travel_space_phrase
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
from d12ball.game import AIOpponent, GameMode, Team
from roster import fielded
from save_patches import suppressed_cog_saves, suppressed_full_image_links, suppressed_view_saves


def build_interaction() -> SimpleNamespace:
    return SimpleNamespace(
        response=SimpleNamespace(is_done=lambda: True),
        followup=SimpleNamespace(send=mock.AsyncMock()),
        channel=SimpleNamespace(send=mock.AsyncMock()),
    )


class RunBackBatchingTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()
        cls.maneuvers = load_maneuver_catalog()

    def build_cog(self) -> D12Ball:
        cog = object.__new__(D12Ball)
        cog.games = {}
        cog.player_catalog = self.catalog
        cog.basic_ruleset = self.rules
        cog.maneuver_catalog = self.maneuvers
        cog.ai_strategies = build_ai_strategies(
            self.catalog, self.maneuvers,
        )
        cog.engine = RulesEngine(
            cog.player_catalog, cog.basic_ruleset, cog.maneuver_catalog,
            cog.ai_strategies,
        )
        cog.refresh_match_image = mock.AsyncMock()
        cog.finish_maneuver_resolution = mock.AsyncMock()
        # The cascade settles the persistent message with a board, and
        # a coach's prompt draws its own field strip beside it -- two
        # renders, two uploads, which is what the counts below assert.
        # See continue_run_back and post_run_back_prompt.
        cog.render_match_png = mock.AsyncMock(return_value=b"board")
        cog.match_file_from_png = mock.Mock(return_value=mock.Mock())
        cog.build_field_file = mock.AsyncMock(
            return_value=mock.sentinel.field,
        )
        cog.coaching_file = mock.AsyncMock()
        return cog

    def build_match(self) -> MatchState:
        # Three spaces to a zone, so a zone holding two players has one
        # to spare -- which is what makes a run back into it a choice
        # rather than the single arrangement that gets applied silently.
        return MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=9,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
        )

    def build_game(self) -> SimpleNamespace:
        # Player 2 is the AI, and holds the visiting side -- see
        # D12Ball.side_is_ai.
        return SimpleNamespace(
            match_state=None,
            game_id="g",
            game_number=1,
            is_solo_game=True,
            ai_opponent=AIOpponent.DINKY,
            home_player_number=1,
            visiting_player_number=2,
            player_1_id=11,
            player_2_id=None,
            turn_message_id=None,
            # A run back charges exhaustion, and the Exhausted
            # threshold is now a question about which modules the game
            # is playing -- basic here, so it is every player's own
            # defensive skill.
            mode=GameMode.BASIC,
            advanced_maneuvers=True,
            species_abilities=True,
        )

    def scatter_visiting_side(self, match: MatchState) -> list[str]:
        """
        Sweep the visiting side's own-goal and midfield players down
        into the far zone, the way a turnover deep in the other half
        leaves them. Each of those two zones is then empty of its own
        players with a space to spare, so every one of them is owed a
        run back that is a real choice -- four placements, which under
        the old code was four messages and four board uploads.
        """
        movers = [
            *match.visiting.zones[Zone.HOME_GOAL],
            *match.visiting.zones[Zone.MIDFIELD],
        ]
        for index, player_id in enumerate(movers):
            match.board.remove_meeple(player_id)
            match.board.place_meeple(
                player_id,
                Zone.VISITORS_GOAL,
                index % len(match.board.spaces[Zone.VISITORS_GOAL]),
            )
        return movers

    async def run_back(self, cog, game, match) -> SimpleNamespace:
        interaction = build_interaction()
        with (
            suppressed_cog_saves(),
            suppressed_full_image_links(),
        ):
            await cog.continue_run_back(interaction, game, match)
        return interaction

    async def test_the_ai_run_back_is_one_message_and_one_refresh(
        self,
    ) -> None:
        cog = self.build_cog()
        game = self.build_game()
        match = self.build_match()
        self.scatter_visiting_side(match)

        match.pending_run_back = True
        game.match_state = match.to_dict()

        interaction = await self.run_back(cog, game, match)

        # However many players moved, the channel sees one post and the
        # board is re-uploaded once.
        self.assertEqual(interaction.channel.send.await_count, 1)
        self.assertEqual(cog.refresh_match_image.await_count, 1)

        # And it really was a cascade: one message per placement is the
        # behaviour being guarded against, so a scenario with only one
        # placement would pass this test without proving anything.
        posted = interaction.channel.send.await_args_list[0].args[0]
        self.assertEqual(posted.count("runs back to"), 4)

    async def test_every_placement_is_still_reported(self) -> None:
        cog = self.build_cog()
        game = self.build_game()
        match = self.build_match()
        movers = self.scatter_visiting_side(match)

        match.pending_run_back = True
        game.match_state = match.to_dict()

        interaction = await self.run_back(cog, game, match)

        posted = interaction.channel.send.await_args_list[0].args[0]
        moved_names = [
            self.catalog.player_by_id(player_id).name
            for player_id in movers
            if match.board.meeple_position(player_id)[1] != 0
        ]
        self.assertTrue(moved_names)
        for name in moved_names:
            self.assertIn(name, posted)
        # Batched into one message, not concatenated into one line.
        self.assertIn("runs back to", posted)

    async def test_the_side_is_spread_out_by_the_end(self) -> None:
        # The batching must not change where anyone ends up: nobody is
        # left doubled up while their zone still has an empty space.
        cog = self.build_cog()
        game = self.build_game()
        match = self.build_match()
        self.scatter_visiting_side(match)

        match.pending_run_back = True
        game.match_state = match.to_dict()

        await self.run_back(cog, game, match)

        self.assertEqual(
            cog.engine.run_back_displaced(match, TeamSide.VISITING), [],
        )
        cog.finish_maneuver_resolution.assert_awaited_once()

    def displace_a_home_player(self, match: MatchState) -> str:
        """
        Sweep one home midfielder into the far zone, leaving their own
        with two spaces free -- so their run back is a real choice of
        space rather than the single arrangement applied silently.
        """
        player_id = match.home.zones[Zone.MIDFIELD][0]
        match.board.remove_meeple(player_id)
        match.board.place_meeple(player_id, Zone.VISITORS_GOAL, 0)
        return player_id

    def stack_the_home_midfield(self, match: MatchState) -> list[str]:
        """
        Both home midfielders onto one space, with the zone's other two
        free -- the position that asks the coach which of them runs
        back (2026-08-17).
        """
        midfield = list(match.home.zones[Zone.MIDFIELD])
        for player_id in midfield:
            match.board.remove_meeple(player_id)
            match.board.place_meeple(player_id, Zone.MIDFIELD, 0)
        return midfield

    async def test_a_coach_is_still_asked_one_at_a_time(self) -> None:
        # The home side is a person, so the cascade stops at their
        # first choice with a prompt rather than placing anyone.
        cog = self.build_cog()
        game = self.build_game()
        match = self.build_match()
        self.displace_a_home_player(match)

        match.pending_run_back = True
        game.match_state = match.to_dict()

        interaction = await self.run_back(cog, game, match)

        prompt = interaction.channel.send.await_args_list[-1].args[0]
        self.assertIn("choose where", prompt)
        cog.finish_maneuver_resolution.assert_not_awaited()
        self.assertNotEqual(
            cog.engine.run_back_movers(game, match, TeamSide.HOME), [],
        )

    async def test_a_stack_asks_the_coach_which_of_them_goes(self) -> None:
        # Two players on one space differ only in who they are, so the
        # cascade asks rather than keeping whichever the occupant list
        # happened to start with.
        cog = self.build_cog()
        game = self.build_game()
        match = self.build_match()
        midfield = self.stack_the_home_midfield(match)

        match.pending_run_back = True
        game.match_state = match.to_dict()

        interaction = await self.run_back(cog, game, match)

        prompt = interaction.channel.send.await_args_list[-1].args[0]
        self.assertIn("choose which of them runs back", prompt)
        for player_id in midfield:
            self.assertIn(self.catalog.player_by_id(player_id).name, prompt)
        # Asked, not answered: nobody has moved and nothing is settled.
        self.assertEqual(
            [match.board.meeple_position(player_id)[1] for player_id in midfield],
            [0, 0],
        )
        cog.finish_maneuver_resolution.assert_not_awaited()

    async def test_the_ball_holder_settles_a_stack_without_asking(
        self,
    ) -> None:
        # One of the pair is holding the ball and does not run back, so
        # there is one player to spare and only the space to choose.
        cog = self.build_cog()
        game = self.build_game()
        match = self.build_match()
        midfield = self.stack_the_home_midfield(match)

        match.pending_run_back = True
        match.pending_run_back_stays_player_id = midfield[0]
        game.match_state = match.to_dict()

        interaction = await self.run_back(cog, game, match)

        prompt = interaction.channel.send.await_args_list[-1].args[0]
        self.assertIn("choose where", prompt)
        self.assertIn(self.catalog.player_by_id(midfield[1]).name, prompt)
        self.assertNotIn(self.catalog.player_by_id(midfield[0]).name, prompt)

    async def test_the_prompt_carries_the_field_it_asks_about(self) -> None:
        # A coach choosing a space is choosing a distance, so the
        # question goes out with the position under it -- the field
        # strip, which is the same board cropped out of the jumbotron,
        # the cards and the benches none of the question turns on. The
        # whole match image still settles the persistent message.
        cog = self.build_cog()
        game = self.build_game()
        match = self.build_match()
        self.stack_the_home_midfield(match)

        match.pending_run_back = True
        game.match_state = match.to_dict()

        interaction = await self.run_back(cog, game, match)

        prompt_call = interaction.channel.send.await_args_list[-1]
        self.assertEqual(
            prompt_call.kwargs.get("file"), mock.sentinel.field,
        )
        # Not the Coaching Choice's half-field: that shows one side's
        # row with play stopped, and this is a live position.
        cog.coaching_file.assert_not_awaited()
        self.assertEqual(cog.render_match_png.await_count, 1)
        self.assertEqual(
            cog.refresh_match_image.await_args.kwargs["png"], b"board",
        )

    async def test_the_prompt_prices_every_space_it_offers(self) -> None:
        # The sentence and the buttons quote the same distance, which
        # is the price -- a run back costs a token a space. They word
        # it differently on purpose (see travel_space_phrase); what
        # they may not do is disagree about the number.
        cog = self.build_cog()
        game = self.build_game()
        match = self.build_match()
        self.displace_a_home_player(match)

        match.pending_run_back = True
        game.match_state = match.to_dict()

        interaction = await self.run_back(cog, game, match)

        prompt = interaction.channel.send.await_args_list[-1].args[0]
        side, (player_id,) = cog.engine.next_run_back_step(game, match)
        zone = match.setup_for_side(side).assigned_zone(player_id)
        spaces = match.placement_spaces_in_zone(side, zone, player_id)
        self.assertTrue(spaces)
        for space_index in spaces:
            distance = match.run_back_distance(player_id, zone, space_index)
            # The sentence above the buttons prices every space it
            # offers, in the prose form -- "M2 (1 space away)". The
            # buttons carry travel_space_label's shorter version of the
            # same distance; see travel_space_phrase.
            self.assertIn(
                travel_space_phrase(zone, space_index, distance), prompt,
            )
            # Not a label that says nothing: they are standing on M1,
            # so every space they can be sent to is a real walk.
            self.assertGreater(distance, 0)

    async def test_a_stack_asks_both_questions_on_one_message(self) -> None:
        # Which player, then which space -- and the second is an edit
        # of the first rather than a message of its own, so the board
        # uploaded for the "who" is the board the "where" is read off.
        # See RunBackPlayerChoiceView.
        cog = self.build_cog()
        game = self.build_game()
        match = self.build_match()
        midfield = self.stack_the_home_midfield(match)
        cog.games["g"] = game

        match.pending_run_back = True
        game.match_state = match.to_dict()

        interaction = await self.run_back(cog, game, match)
        sends_before = interaction.channel.send.await_count

        view = interaction.channel.send.await_args_list[-1].kwargs["view"]
        click = SimpleNamespace(
            user=SimpleNamespace(id=11),
            message=SimpleNamespace(attachments=[]),
            response=SimpleNamespace(
                edit_message=mock.AsyncMock(),
                send_message=mock.AsyncMock(),
            ),
            followup=SimpleNamespace(send=mock.AsyncMock()),
        )
        with suppressed_view_saves():
            await view.choose(click, midfield[1])

        click.response.edit_message.assert_awaited_once()
        edit = click.response.edit_message.await_args
        self.assertIn("choose where", edit.kwargs["content"])
        self.assertNotIn("attachments", edit.kwargs)
        # Nothing new posted, and nobody moved until the space is
        # picked: the second question is the same message asked again.
        self.assertEqual(
            interaction.channel.send.await_count, sends_before,
        )
        self.assertEqual(match.board.meeple_position(midfield[1])[1], 0)


class RunBackTerminationTests(unittest.IsolatedAsyncioTestCase):
    """
    As a recursion the cascade was bounded by the interpreter; as a
    loop it is bounded by MAX_RUN_BACK_PASSES, because a spin here
    would hang the event loop for every game at once.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()
        cls.maneuvers = load_maneuver_catalog()

    async def test_a_run_back_that_will_not_settle_gives_up(self) -> None:
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=9,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
        )
        # A player who stays displaced however often they are placed.
        # Which one is immaterial -- the cascade is driven by the mocks
        # below, so this is only somebody for it to keep placing.
        displaced = fielded(match, PlayerRole.WINGER, TeamSide.VISITING)

        cog = object.__new__(D12Ball)
        cog.games = {}
        cog.player_catalog = self.catalog
        cog.basic_ruleset = self.rules
        cog.maneuver_catalog = self.maneuvers
        cog.engine = RulesEngine(
            cog.player_catalog, cog.basic_ruleset, cog.maneuver_catalog, {},
        )
        cog.refresh_match_image = mock.AsyncMock()
        cog.finish_maneuver_resolution = mock.AsyncMock()
        cog.engine.apply_forced_run_backs = mock.Mock()
        cog.engine.next_run_back_step = mock.Mock(
            return_value=(TeamSide.VISITING, [displaced]),
        )
        cog.engine.side_is_ai = mock.Mock(return_value=True)
        cog.engine.get_ai_strategy = mock.Mock(
            return_value=mock.Mock(choose_run_back_space=mock.Mock(return_value=0)),
        )
        cog.apply_exhaustion = mock.Mock(return_value="")
        cog.engine.get_player_definition = mock.Mock(
            return_value=self.catalog.player_by_id(displaced),
        )

        match.run_back_player = mock.Mock(return_value=0)
        game = SimpleNamespace(
            match_state=match.to_dict(),
            game_id="g",
            is_solo_game=True,
            mode=GameMode.BASIC,
            advanced_maneuvers=True,
            species_abilities=True,
        )
        interaction = build_interaction()

        with (
            suppressed_cog_saves(),
            # The give-up log moved with the cascade in Phase 4.
            mock.patch("d12ball.flow.turnovers.LOGGER") as logger,
        ):
            await cog.continue_run_back(interaction, game, match)

        logger.error.assert_called_once()
        self.assertEqual(
            match.run_back_player.call_count, MAX_RUN_BACK_PASSES,
        )
        # And it still hands the turn on rather than stranding it.
        cog.finish_maneuver_resolution.assert_awaited_once()


class EndOfTurnRenderTests(unittest.IsolatedAsyncioTestCase):
    """
    The board that ends a maneuver goes to two places -- the persistent
    board message and the snapshot under the result -- and used to be
    drawn once for each.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()
        cls.maneuvers = load_maneuver_catalog()

    async def test_the_closing_board_is_drawn_once(self) -> None:
        cog = object.__new__(D12Ball)
        cog.games = {}
        cog.player_catalog = self.catalog
        cog.render_match_png = mock.AsyncMock(return_value=b"png")
        cog.match_file_from_png = mock.Mock(return_value="file")
        cog.refresh_match_image = mock.AsyncMock()
        cog.send_turn_prompt = mock.AsyncMock()
        # The two gates are inside the flow step since Phase 4, so they
        # are no longer cog methods a test can mock out. Neither fires
        # on this position anyway, which is the same thing the mocks
        # were asserting: the standard deal leaves a player on the
        # ball's space (nothing loose), and a basic game has no
        # species abilities (nothing to pull or take over).
        cog.engine = RulesEngine(
            self.catalog,
            self.rules,
            self.maneuvers,
            build_ai_strategies(self.catalog, self.maneuvers),
        )

        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
        )
        game = SimpleNamespace(
            match_state=match.to_dict(),
            game_id="g",
            game_number=1,
            home_player_number=1,
            visiting_player_number=2,
            mode=GameMode.BASIC,
            advanced_maneuvers=True,
            species_abilities=True,
        )
        send = mock.AsyncMock(return_value=SimpleNamespace(id=1, attachments=[]))
        interaction = SimpleNamespace(
            channel=SimpleNamespace(send=send),
            followup=SimpleNamespace(send=send),
            response=SimpleNamespace(is_done=lambda: True),
        )

        with (
            suppressed_cog_saves(),
            suppressed_full_image_links(),
        ):
            await cog.finish_maneuver_resolution(
                interaction, game, match,
                distance_moved=1,
                turnover_occurred=False,
            )

        cog.render_match_png.assert_awaited_once()
        # And the one render reached both uploads.
        self.assertEqual(cog.match_file_from_png.call_count, 1)
        cog.refresh_match_image.assert_awaited_once()
        self.assertEqual(
            cog.refresh_match_image.await_args.kwargs["png"], b"png",
        )


if __name__ == "__main__":
    unittest.main()
