"""
Who may act on a game they are not playing in.

Every gate in the flow -- a lobby setting, a roll button, a maneuver
pick, a coaching menu -- comes through `is_game_helper`,
`may_act_for_coach` or `may_act_in_game` in `cogs/d12ball_helpers.py`.
What is worth guarding is that there is still only the one rule: the
coach it belongs to, or a game helper, everywhere, rather than a lobby
that refuses somebody the setting while `/d12ball abandon_game` lets
them end the whole game.

Two things a helper's reach must not undo, both found the hard way on
2026-09-18: **a coach who also holds the permission is still pressing
their own buttons** -- the shootout order handed a visiting coach with
`manage_channels` the *home* order to set -- and **a click for somebody
else is confirmed first** past the lobby, since it moves the game for a
coach who pressed nothing.

See "Who may act on a game" in docs/design/permissions.md.
"""

import asyncio
import unittest
from types import SimpleNamespace
from unittest import mock

import discord

from cogs.d12ball import D12Ball
from cogs.d12ball_helpers import (
    HELPER_CONFIRMED_EXTRA,
    HelperConfirmationRequired,
    game_participant_ids,
    is_game_helper,
    may_act_for_coach,
    may_act_in_game,
)
from cogs.d12ball_views import (
    HelperConfirmationView,
    LobbyView,
    ManeuverActionPromptView,
    ShootoutOrderPromptView,
    TeamSelectionView,
)
from d12ball.components import (
    MatchState,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.ai import build_ai_strategies
from d12ball.engine import RulesEngine
from d12ball.components import TeamSide
from d12ball.game import D12BallGame, GameMode, GameStatus, Team
from save_patches import suppressed_cog_saves, suppressed_view_saves


PLAYER_ONE = 111
PLAYER_TWO = 222
STRANGER = 333


def build_cog() -> D12Ball:
    cog = object.__new__(D12Ball)
    cog.games = {}
    cog.player_catalog = load_player_catalog()
    cog.maneuver_catalog = load_maneuver_catalog()
    cog.basic_ruleset = load_basic_ruleset()
    cog.d12_emoji = None
    cog.coin_emojis = {}
    cog.engine = RulesEngine(
        cog.player_catalog,
        cog.basic_ruleset,
        cog.maneuver_catalog,
        # A solo game's team pick draws Dinky's team through its
        # strategy (`GameService.pick_team`).
        build_ai_strategies(cog.player_catalog, cog.maneuver_catalog),
    )
    return cog


def build_game(**overrides) -> D12BallGame:
    fields = dict(
        game_id="g1",
        game_number=1,
        guild_id=1,
        channel_id=2,
        message_id=None,
        player_1_id=PLAYER_ONE,
        player_2_id=PLAYER_TWO,
        player_1_name="One",
        player_2_name="Two",
        player_1_team=Team.ORANGE,
        player_2_team=Team.PURPLE,
        home_player_number=1,
        visiting_player_number=2,
    )
    fields.update(overrides)
    return D12BallGame(**fields)


def build_lobby_game(**overrides) -> D12BallGame:
    fields = dict(
        player_2_id=None,
        player_2_name=None,
        player_1_team=None,
        player_2_team=None,
        home_player_number=None,
        visiting_player_number=None,
        in_lobby=True,
        status=GameStatus.SETUP,
    )
    fields.update(overrides)
    return build_game(**fields)


def person(user_id: int, manage_channels: bool = False) -> SimpleNamespace:
    """
    Somebody clicking, with real booleans on their permissions -- the
    shape `is_game_helper` insists on. See its docstring for why a
    `MagicMock` member is deliberately not a helper.
    """
    return SimpleNamespace(
        id=user_id,
        display_name=f"user{user_id}",
        guild_permissions=SimpleNamespace(manage_channels=manage_channels),
    )


def build_interaction(user, confirmed: bool = False) -> SimpleNamespace:
    """
    A click. `confirmed` marks it the way `HelperConfirmationView`
    marks the click that answers a confirmation, so a test can ask
    what a helper is let through *after* confirming.
    """
    return SimpleNamespace(
        user=user,
        guild=None,
        channel=None,
        message=SimpleNamespace(id=5, edit=mock.AsyncMock()),
        extras={HELPER_CONFIRMED_EXTRA: True} if confirmed else {},
        response=SimpleNamespace(
            send_message=mock.AsyncMock(),
            edit_message=mock.AsyncMock(),
            defer=mock.AsyncMock(),
            send_modal=mock.AsyncMock(),
            is_done=lambda: False,
            type=None,
        ),
        followup=SimpleNamespace(send=mock.AsyncMock()),
    )


class GameHelperPredicateTests(unittest.TestCase):
    """The three predicates the whole of this rests on."""

    def test_a_coach_is_not_a_helper_and_does_not_need_to_be(self) -> None:
        game = build_game()
        self.assertFalse(is_game_helper(person(PLAYER_ONE)))
        self.assertTrue(may_act_in_game(person(PLAYER_ONE), game))
        self.assertTrue(
            may_act_for_coach(person(PLAYER_TWO), PLAYER_TWO)
        )

    def test_a_stranger_is_refused_exactly_as_before(self) -> None:
        game = build_game()
        self.assertFalse(may_act_in_game(person(STRANGER), game))
        self.assertFalse(may_act_for_coach(person(STRANGER), PLAYER_ONE))

    def test_manage_channels_is_what_makes_a_helper(self) -> None:
        game = build_game()
        helper = person(STRANGER, manage_channels=True)
        self.assertTrue(is_game_helper(helper))
        self.assertTrue(may_act_in_game(helper, game))
        # For either coach, not just one of them: a helper holds no
        # side, so which side a button belongs to cannot narrow it.
        self.assertTrue(may_act_for_coach(helper, PLAYER_ONE))
        self.assertTrue(may_act_for_coach(helper, PLAYER_TWO))

    def test_a_helper_may_answer_a_prompt_that_belongs_to_nobody(
        self,
    ) -> None:
        # `side_controller_id` and friends answer None for an AI side.
        # Nothing ever puts a prompt to Dinky, so the only way to reach
        # one is a game that has gone wrong -- which is exactly when
        # somebody has to be able to answer it.
        self.assertTrue(
            may_act_for_coach(person(STRANGER, manage_channels=True), None)
        )
        self.assertFalse(may_act_for_coach(person(STRANGER), None))

    def test_somebody_with_no_permissions_at_all_is_not_a_helper(
        self,
    ) -> None:
        # A `discord.User` rather than a `Member` -- no `guild_permissions`
        # at all. Answering False beats raising.
        self.assertFalse(is_game_helper(SimpleNamespace(id=STRANGER)))

    def test_a_mock_member_is_not_a_helper(self) -> None:
        # The guard that keeps the rest of the suite honest: a
        # `MagicMock(spec=discord.Member)` answers truthy for every
        # attribute, so under a plain truthiness test every mocked
        # click in `tests/` would read as a helper's and every gate in
        # the game would quietly stop refusing anybody.
        member = mock.MagicMock(spec=discord.Member)
        member.id = STRANGER
        self.assertFalse(is_game_helper(member))

    def test_a_test_game_is_one_participant(self) -> None:
        game = build_game(player_2_id=PLAYER_ONE, test_game=True)
        self.assertEqual(game_participant_ids(game), {PLAYER_ONE})


class RecoveryGateTests(unittest.TestCase):
    """
    `may_administer_game` is the name the recovery commands already
    called this by, and is now one reading of the shared predicate
    rather than a second copy of the permission check.
    """

    def test_it_answers_the_same_three_ways(self) -> None:
        cog = build_cog()
        game = build_game()
        self.assertTrue(
            cog.may_administer_game(
                build_interaction(person(PLAYER_ONE)), game,
            )
        )
        self.assertFalse(
            cog.may_administer_game(build_interaction(person(STRANGER)), game)
        )
        self.assertTrue(
            cog.may_administer_game(
                build_interaction(person(STRANGER, manage_channels=True)),
                game,
            )
        )


class LobbyHelperTests(unittest.TestCase):
    """
    The case this was built for: somebody organising a playtest turning
    Tutorial on in a lobby they are not playing in.
    """

    def build(self):
        cog = build_cog()
        game = build_lobby_game()
        cog.games[game.game_id] = game
        return cog, game, LobbyView(cog, game.game_id)

    def change(self, view, interaction, game, setting, value) -> None:
        with suppressed_view_saves(), suppressed_cog_saves():
            asyncio.run(
                view.change_setting(interaction, game, setting, value)
            )

    def test_a_helper_turns_the_tutorial_on(self) -> None:
        cog, game, view = self.build()
        interaction = build_interaction(
            person(STRANGER, manage_channels=True)
        )

        self.change(view, interaction, game, "tutorial", "")

        self.assertTrue(game.tutorial)
        # Answered by editing the lobby message, not refused.
        interaction.response.edit_message.assert_awaited_once()
        interaction.response.send_message.assert_not_awaited()

    def test_a_stranger_still_cannot(self) -> None:
        cog, game, view = self.build()
        interaction = build_interaction(person(STRANGER))

        self.change(view, interaction, game, "tutorial", "")

        self.assertFalse(game.tutorial)
        interaction.response.send_message.assert_awaited_once()

    def test_a_helper_changes_the_mode(self) -> None:
        cog, game, view = self.build()
        interaction = build_interaction(
            person(STRANGER, manage_channels=True)
        )

        self.change(view, interaction, game, "mode", "advanced")

        self.assertEqual(game.mode, GameMode.ADVANCED)

    def test_a_helper_starts_the_game(self) -> None:
        cog, game, view = self.build()
        cog.post_game_setup_message = mock.AsyncMock(return_value=77)
        channel = mock.MagicMock(spec=discord.TextChannel)
        channel.guild = mock.MagicMock()
        interaction = build_interaction(
            person(STRANGER, manage_channels=True)
        )
        interaction.channel = channel

        with suppressed_cog_saves():
            asyncio.run(cog.lobby_start(interaction, game))

        self.assertFalse(game.in_lobby)
        cog.post_game_setup_message.assert_awaited_once()


class TeamPickHelperTests(unittest.TestCase):
    """
    A helper holds neither side, so a team pick has to be told which
    one it is for. The shared row fills Player 1 first.
    """

    def build(self, **overrides):
        cog = build_cog()
        game = build_lobby_game(in_lobby=False, **overrides)
        cog.games[game.game_id] = game
        cog.ensure_coin_emojis = mock.AsyncMock()
        return cog, game, TeamSelectionView(cog=cog, game_id=game.game_id)

    def pick(self, view, game, user, team, player_number=None) -> None:
        interaction = build_interaction(user)
        with suppressed_view_saves(), suppressed_cog_saves():
            asyncio.run(
                view.select_team(interaction, team, player_number)
            )
        return interaction

    def test_a_helpers_first_pick_goes_to_player_one(self) -> None:
        cog, game, view = self.build()
        helper = person(STRANGER, manage_channels=True)

        self.pick(view, game, helper, Team.ORANGE)

        self.assertEqual(game.player_1_team, Team.ORANGE)

    def test_a_helpers_second_pick_goes_to_player_two(self) -> None:
        cog, game, view = self.build(
            player_2_id=PLAYER_TWO, player_2_name="Two",
        )
        helper = person(STRANGER, manage_channels=True)

        self.pick(view, game, helper, Team.ORANGE)
        self.pick(view, game, helper, Team.PURPLE)

        self.assertEqual(game.player_1_team, Team.ORANGE)
        self.assertEqual(game.player_2_team, Team.PURPLE)

    def test_a_stranger_picks_for_neither(self) -> None:
        cog, game, view = self.build()
        interaction = self.pick(view, game, person(STRANGER), Team.ORANGE)

        self.assertIsNone(game.player_1_team)
        interaction.response.send_message.assert_awaited_once()


class LivePlayHelperTests(unittest.TestCase):
    """
    A helper reaches the buttons of a game under way, not only its
    lobby -- which is what "help somebody into a game" turns out to
    mean once they are in one and stuck.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    def build(self):
        cog = build_cog()
        game = build_game()
        cog.games[game.game_id] = game
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
        )
        # The handler has to be standing on the ball, and the
        # challenger with them -- `validate()` refuses anything else.
        match.active_player_id = match.eligible_ball_handlers()[0]
        match.challenger_id = next(
            player_id
            for player_id in match.board.spaces[match.ball.zone][
                match.ball.space_index
            ]
            if player_id in match.visiting.field_players
        )
        game.match_state = match.to_dict()
        return cog, game, match

    def refusal(self, view, game, match, side, user) -> None:
        return view.pick_refusal(game, match, side, build_interaction(user))

    def confirmed_refusal(self, view, game, match, side, user) -> None:
        return view.pick_refusal(
            game, match, side, build_interaction(user, confirmed=True),
        )

    def test_a_helper_may_pick_for_either_side_once_confirmed(self) -> None:
        cog, game, match = self.build()
        view = ManeuverActionPromptView(cog, game.game_id)
        helper = person(STRANGER, manage_channels=True)

        self.assertIsNone(
            self.confirmed_refusal(view, game, match, "offense", helper)
        )
        self.assertIsNone(
            self.confirmed_refusal(view, game, match, "defense", helper)
        )

    def test_a_helpers_unconfirmed_pick_asks_first(self) -> None:
        cog, game, match = self.build()
        view = ManeuverActionPromptView(cog, game.game_id)
        helper = person(STRANGER, manage_channels=True)

        with self.assertRaises(HelperConfirmationRequired) as asked:
            self.refusal(view, game, match, "offense", helper)
        # Home has the ball, and Player 1 is home.
        self.assertEqual(asked.exception.coach_ids, (PLAYER_ONE,))

    def test_a_coach_who_is_a_helper_picks_for_their_own_side_unasked(
        self,
    ) -> None:
        """
        The bug this file grew for: `manage_channels` on a coach does
        not turn their own clicks into a helper's. Their own side is
        theirs with no confirmation; the other side is asked for.
        """
        cog, game, match = self.build()
        view = ManeuverActionPromptView(cog, game.game_id)
        coach = person(PLAYER_ONE, manage_channels=True)

        self.assertIsNone(self.refusal(view, game, match, "offense", coach))
        with self.assertRaises(HelperConfirmationRequired) as asked:
            self.refusal(view, game, match, "defense", coach)
        self.assertEqual(asked.exception.coach_ids, (PLAYER_TWO,))

    def test_a_coach_is_still_held_to_their_own_side(self) -> None:
        cog, game, match = self.build()
        view = ManeuverActionPromptView(cog, game.game_id)
        # Player 1 is home, and home has the ball at kickoff.
        self.assertIsNone(
            self.refusal(view, game, match, "offense", person(PLAYER_ONE))
        )
        self.assertIsNotNone(
            self.refusal(view, game, match, "defense", person(PLAYER_ONE))
        )

    def test_a_stranger_may_pick_for_neither(self) -> None:
        cog, game, match = self.build()
        view = ManeuverActionPromptView(cog, game.game_id)
        stranger = person(STRANGER)

        self.assertIsNotNone(
            self.refusal(view, game, match, "offense", stranger)
        )
        self.assertIsNotNone(
            self.refusal(view, game, match, "defense", stranger)
        )

    def test_a_helper_may_roll_a_die_either_coach_could_have(self) -> None:
        cog, game, match = self.build()
        view = ManeuverActionPromptView(cog, game.game_id)
        helper = person(STRANGER, manage_channels=True)

        with self.assertRaises(HelperConfirmationRequired) as asked:
            view.may_act_in_game(build_interaction(helper), game)
        self.assertEqual(asked.exception.coach_ids, (PLAYER_ONE, PLAYER_TWO))
        self.assertTrue(
            view.may_act_in_game(
                build_interaction(helper, confirmed=True), game,
            )
        )
        self.assertFalse(
            view.may_act_in_game(build_interaction(person(STRANGER)), game)
        )

    def test_a_coach_who_is_a_helper_rolls_unasked(self) -> None:
        cog, game, match = self.build()
        view = ManeuverActionPromptView(cog, game.game_id)

        self.assertTrue(
            view.may_act_in_game(
                build_interaction(person(PLAYER_TWO, manage_channels=True)),
                game,
            )
        )


class ShootoutClaimTests(unittest.TestCase):
    """
    The shootout's order prompt derives a side from the clicker, and
    it was the one gate that read a coach's permission ahead of their
    own side: a visiting coach with `manage_channels` was handed the
    home order to set.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_player_catalog()
        cls.rules = load_basic_ruleset()

    def build(self):
        cog = build_cog()
        game = build_game()
        cog.games[game.game_id] = game
        match = MatchState.standard(
            catalog=self.catalog,
            ruleset=self.rules,
            board_size=7,
            home_team=Team.ORANGE,
            visiting_team=Team.PURPLE,
        )
        match.pending_shootout = True
        game.match_state = match.to_dict()
        return cog, game, ShootoutOrderPromptView(cog, game.game_id)

    def claim(self, view, user, confirmed=False):
        interaction = build_interaction(user, confirmed=confirmed)
        claimed = asyncio.run(view.claim(interaction))
        return None if claimed is None else claimed[2]

    def test_a_visiting_coach_with_the_permission_gets_their_own_side(
        self,
    ) -> None:
        cog, game, view = self.build()
        # Player 2 is the visitors, and home's order is still owed --
        # which is exactly the state that used to hand them home.
        self.assertEqual(
            self.claim(view, person(PLAYER_TWO, manage_channels=True)),
            TeamSide.VISITING,
        )

    def test_a_coach_gets_their_own_side_even_once_it_is_set(self) -> None:
        cog, game, view = self.build()
        match = cog.engine.load_match_state(game)
        for player_id in match.visiting.field_players:
            match.add_to_shootout_order(TeamSide.VISITING, player_id)
        game.match_state = match.to_dict()

        self.assertEqual(
            self.claim(view, person(PLAYER_TWO, manage_channels=True)),
            TeamSide.VISITING,
        )

    def test_a_helper_outside_the_game_is_asked_and_then_gets_what_is_owed(
        self,
    ) -> None:
        cog, game, view = self.build()
        helper = person(STRANGER, manage_channels=True)

        with self.assertRaises(HelperConfirmationRequired):
            self.claim(view, helper)
        self.assertEqual(
            self.claim(view, helper, confirmed=True), TeamSide.HOME,
        )

    def test_a_stranger_gets_nothing(self) -> None:
        cog, game, view = self.build()
        self.assertIsNone(self.claim(view, person(STRANGER)))


class HelperConfirmationTests(unittest.IsolatedAsyncioTestCase):
    """
    The round trip a helper's click makes past the lobby: the gate
    raises, `on_error` swaps the prompt's buttons for Confirm/Cancel,
    and Confirm re-runs the button with the click marked confirmed.
    """

    def build(self):
        cog = build_cog()
        game = build_game()
        cog.games[game.game_id] = game
        view = TeamSelectionView(cog=cog, game_id=game.game_id)
        ran: list[int] = []

        async def callback(interaction) -> None:
            if view.may_act_for(interaction, PLAYER_ONE):
                ran.append(interaction.user.id)
                await interaction.response.send_message("done", ephemeral=True)

        item = discord.ui.Button(label="x")
        item.callback = callback
        return cog, game, view, item, ran

    async def click(self, view, item, user):
        """A click the way discord.py delivers one: callback, then on_error."""
        interaction = build_interaction(user)
        try:
            await item.callback(interaction)
        except Exception as error:  # noqa: BLE001
            await view.on_error(interaction, error, item)
        return interaction

    def confirmation(self, interaction) -> HelperConfirmationView:
        interaction.response.edit_message.assert_awaited_once()
        confirmation = interaction.response.edit_message.await_args.kwargs[
            "view"
        ]
        self.assertIsInstance(confirmation, HelperConfirmationView)
        return confirmation

    async def test_a_helpers_click_is_held_until_confirmed(self) -> None:
        cog, game, view, item, ran = self.build()
        helper = person(STRANGER, manage_channels=True)

        asked = await self.click(view, item, helper)
        confirmation = self.confirmation(asked)
        self.assertEqual(ran, [])
        # The explanation is ephemeral, and names the coach.
        explanation = asked.followup.send.await_args
        self.assertTrue(explanation.kwargs["ephemeral"])
        self.assertIn("One", explanation.args[0])
        self.assertIn("One", confirmation.children[0].label)

        confirmed = build_interaction(helper)
        await confirmation.confirm(confirmed)
        self.assertEqual(ran, [STRANGER])
        self.assertTrue(confirmed.extras[HELPER_CONFIRMED_EXTRA])
        # The callback answered with a message of its own, so the
        # prompt's buttons are put back by hand.
        confirmed.message.edit.assert_awaited_once_with(view=view)

    async def test_a_click_that_edits_the_prompt_is_left_as_it_edited_it(
        self,
    ) -> None:
        cog, game, view, item, ran = self.build()
        helper = person(STRANGER, manage_channels=True)
        confirmation = self.confirmation(await self.click(view, item, helper))

        confirmed = build_interaction(helper)
        confirmed.response.type = (
            discord.InteractionResponseType.message_update
        )
        await confirmation.confirm(confirmed)
        confirmed.message.edit.assert_not_awaited()

    async def test_only_the_helper_who_asked_may_confirm(self) -> None:
        cog, game, view, item, ran = self.build()
        helper = person(STRANGER, manage_channels=True)
        confirmation = self.confirmation(await self.click(view, item, helper))

        other = build_interaction(person(PLAYER_TWO))
        await confirmation.confirm(other)
        self.assertEqual(ran, [])
        other.response.send_message.assert_awaited_once()

    async def test_a_coach_may_cancel_and_get_their_buttons_back(self) -> None:
        cog, game, view, item, ran = self.build()
        helper = person(STRANGER, manage_channels=True)
        confirmation = self.confirmation(await self.click(view, item, helper))

        cancelled = build_interaction(person(PLAYER_TWO))
        await confirmation.cancel(cancelled)
        cancelled.response.edit_message.assert_awaited_once_with(view=view)
        self.assertTrue(confirmation.is_finished())

        bystander = build_interaction(person(444))
        await confirmation.cancel(bystander)
        bystander.response.edit_message.assert_not_awaited()

    async def test_the_coach_it_belongs_to_is_never_asked(self) -> None:
        cog, game, view, item, ran = self.build()

        coach = person(PLAYER_ONE, manage_channels=True)
        own = await self.click(view, item, coach)
        self.assertEqual(ran, [PLAYER_ONE])
        own.response.edit_message.assert_not_awaited()

    async def test_the_lobby_asks_nobody(self) -> None:
        cog = build_cog()
        game = build_lobby_game()
        cog.games[game.game_id] = game
        view = LobbyView(cog, game.game_id)

        self.assertTrue(
            view.may_act_in_game(
                build_interaction(person(STRANGER, manage_channels=True)),
                game,
            )
        )


if __name__ == "__main__":
    unittest.main()
