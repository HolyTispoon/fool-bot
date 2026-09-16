"""
Who may act on a game they are not playing in.

Every gate in the flow -- a lobby setting, a roll button, a maneuver
pick, a coaching menu -- comes through `is_game_helper`,
`may_act_for_coach` or `may_act_in_game` in `cogs/d12ball_helpers.py`.
What is worth guarding is that there is still only the one rule: the
coach it belongs to, or a game helper, everywhere, rather than a lobby
that refuses somebody the setting while `/d12ball abandon_game` lets
them end the whole game.

See "Who may act on a game" in CLAUDE.md.
"""

import asyncio
import unittest
from types import SimpleNamespace
from unittest import mock

import discord

from cogs.d12ball import D12Ball
from cogs.d12ball_helpers import (
    game_participant_ids,
    is_game_helper,
    may_act_for_coach,
    may_act_in_game,
)
from cogs.d12ball_views import (
    LobbyView,
    ManeuverActionPromptView,
    TeamSelectionView,
)
from d12ball.components import (
    MatchState,
    load_basic_ruleset,
    load_maneuver_catalog,
    load_player_catalog,
)
from d12ball.engine import RulesEngine
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
    cog.team_emojis = {}
    cog.condition_emojis = {}
    cog.d12_emoji = None
    cog.coin_emojis = {}
    cog.engine = RulesEngine(
        cog.player_catalog, cog.basic_ruleset, cog.maneuver_catalog, {},
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


def build_interaction(user) -> SimpleNamespace:
    return SimpleNamespace(
        user=user,
        guild=None,
        channel=None,
        response=SimpleNamespace(
            send_message=mock.AsyncMock(),
            edit_message=mock.AsyncMock(),
            defer=mock.AsyncMock(),
            send_modal=mock.AsyncMock(),
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
        return view.pick_refusal(
            game,
            match,
            side,
            self.first_maneuver(view, side),
            build_interaction(user),
        )

    def first_maneuver(self, view, side: str) -> str:
        catalog = view.cog.maneuver_catalog
        definitions = catalog.offense if side == "offense" else catalog.defense
        return definitions[0].key

    def test_a_helper_may_pick_for_either_side(self) -> None:
        cog, game, match = self.build()
        view = ManeuverActionPromptView(cog, game.game_id)
        helper = person(STRANGER, manage_channels=True)

        self.assertIsNone(self.refusal(view, game, match, "offense", helper))
        self.assertIsNone(self.refusal(view, game, match, "defense", helper))

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

        self.assertTrue(
            view.may_act_in_game(
                build_interaction(person(STRANGER, manage_channels=True)),
                game,
            )
        )
        self.assertFalse(
            view.may_act_in_game(build_interaction(person(STRANGER)), game)
        )


if __name__ == "__main__":
    unittest.main()
