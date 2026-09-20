"""
The field strip under a maneuver's own question.

Five prompts ask a version of one thing -- how far does the ball or its
handler go, and who ends up with it -- and every one of them is
answered by reading where everybody is standing relative to the ball.
They share `D12Ball.send_field_prompt`, which is what these cover: that
each resolver reaches it rather than posting a bare menu, and that it
puts the field on the prompt.

Two of the five carried the strip already and three carried nothing at
all, so the thing worth guarding is the funnel -- a resolver that goes
back to building its own `followup.send` is exactly how the five come
apart again. The run back asks the same question and carries the same
picture through `send_run_back_prompt`; its own tests are in
test_d12ball_run_back_batching.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

from cogs.d12ball import D12Ball
from cogs.d12ball_views import (
    DribbleAdvanceChoiceView,
    DribbleBurstChoiceView,
    HighPassChoiceView,
    LowPassChoiceView,
    SetupPassChoiceView,
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
from d12ball.engine import RulesEngine
from d12ball.game import D12BallGame, GameMode, GameStatus, Team
from roster import fielded
from save_patches import suppressed_cog_saves, suppressed_full_image_links


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
    return cog


def build_interaction() -> SimpleNamespace:
    # `channel.send` and `followup.send` share one mock: which route a
    # post takes depends on whether the interaction still had a response
    # to give, and these tests read back "what this posted" without
    # caring which route carried it.
    send = mock.AsyncMock(
        return_value=SimpleNamespace(id=999, attachments=[]),
    )
    return SimpleNamespace(
        user=SimpleNamespace(id=111, display_name="One"),
        channel=SimpleNamespace(send=send),
        followup=SimpleNamespace(send=send),
        response=SimpleNamespace(
            edit_message=mock.AsyncMock(),
            send_message=mock.AsyncMock(),
            is_done=lambda: True,
        ),
    )


class HalfFieldPromptTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    def build(self, role: PlayerRole = PlayerRole.PLAYMAKER):
        """
        A home attack in midfield, with `role` on the ball. Advanced,
        so the Setup Pass and Dribble Burst prompts are reachable at
        all; two humans, so nothing routes to Dinky.
        """
        cog = build_cog()
        game = D12BallGame(
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
            status=GameStatus.IN_PROGRESS,
            mode=GameMode.ADVANCED,
        )
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
        )
        handler = fielded(match, role)
        match.ball.possession = TeamSide.HOME
        match.move_meeple(handler, Zone.MIDFIELD, 1)
        match.set_ball_space(Zone.MIDFIELD, 1)
        match.active_player_id = handler
        game.match_state = match.to_dict()
        cog.games[game.game_id] = game
        return cog, game, match

    async def resolve(self, cog, game, match, resolver, **kwargs):
        """Run one resolver with the funnel stubbed, and hand it back."""
        cog.send_field_prompt = mock.AsyncMock()
        interaction = build_interaction()
        with suppressed_cog_saves(), suppressed_full_image_links():
            await getattr(cog, resolver)(interaction, game, match, **kwargs)
        return cog.send_field_prompt

    async def test_every_distance_prompt_goes_through_the_funnel(
        self,
    ) -> None:
        """
        The claim the whole design rests on: one helper, five callers.
        Each is checked in a position where its own prompt is really
        shown, so a resolver that short-circuits (a High Pass with no
        distance left, a burst from the last space) would fail here
        rather than pass vacuously.
        """
        cases = (
            ("resolve_low_pass", {}, LowPassChoiceView),
            ("resolve_skilled_pass", {}, LowPassChoiceView),
            ("resolve_high_pass", {}, HighPassChoiceView),
            ("offer_setup_pass_distance", {}, SetupPassChoiceView),
            ("resolve_dribble_advance", {}, DribbleAdvanceChoiceView),
            ("resolve_dribble_burst", {}, DribbleBurstChoiceView),
        )
        for resolver, kwargs, view_class in cases:
            with self.subTest(resolver=resolver):
                cog, game, match = self.build()
                sent = await self.resolve(
                    cog, game, match, resolver, **kwargs
                )
                sent.assert_awaited_once()
                self.assertIsInstance(sent.await_args.args[4], view_class)

    async def test_the_skilled_pass_shares_the_low_pass_prompt(self) -> None:
        """
        It is a Low Pass with more reach, so it is the same view over
        the same picture -- which is why nothing had to be added for
        it. Worth asserting rather than assuming: the two are one
        function only for as long as nobody splits them.
        """
        cog, game, match = self.build()
        sent = await self.resolve(cog, game, match, "resolve_skilled_pass")

        view = sent.await_args.args[4]
        self.assertIsInstance(view, LowPassChoiceView)
        self.assertEqual(view.key, "skilled_pass")

    async def test_the_funnel_puts_the_field_on_the_prompt(self) -> None:
        """
        The helper itself. It is the field strip -- a crop of the same
        board both coaches are already reading -- and not the coaching
        image's half-field: these questions are about the position, and
        a position is both sides.
        """
        cog, game, match = self.build()
        cog.build_field_file = mock.AsyncMock(
            return_value=mock.sentinel.field,
        )
        cog.coaching_file = mock.AsyncMock()
        view = LowPassChoiceView(cog, game.game_id)
        interaction = build_interaction()

        with suppressed_cog_saves(), suppressed_full_image_links():
            await cog.send_field_prompt(
                interaction, game, match, "pick one:", view,
            )

        kwargs = interaction.followup.send.await_args.kwargs
        self.assertEqual(kwargs["file"], mock.sentinel.field)
        self.assertIs(kwargs["view"], view)
        cog.coaching_file.assert_not_awaited()
        # The prompt is what a restart re-arms, so it has to be the
        # recorded turn message.
        self.assertEqual(game.turn_message_id, 999)

    async def test_the_link_is_handed_the_prompts_own_view(self) -> None:
        """
        Editing a message's view replaces it wholesale, so the
        full-image link has to go on carrying the buttons -- otherwise
        the prompt reads as interactive and answers nothing. See
        add_full_image_button.
        """
        cog, game, match = self.build()
        cog.build_field_file = mock.AsyncMock(return_value=None)
        view = LowPassChoiceView(cog, game.game_id)
        interaction = build_interaction()

        with suppressed_cog_saves(), mock.patch(
            "cogs.d12ball.presentation.add_full_image_button",
            mock.AsyncMock(),
        ) as link:
            await cog.send_field_prompt(
                interaction, game, match, "pick one:", view,
            )

        link.assert_awaited_once()
        self.assertIs(link.await_args.args[1], view)


if __name__ == "__main__":
    unittest.main()
