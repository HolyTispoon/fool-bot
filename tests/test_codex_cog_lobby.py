"""
The Codex cog from `/codex lobby` to the opening board (docs/codex-bot.md,
step 3), driven with Discord faked: the lobby posted in a channel of its
own, two seats taken, Start setting that channel up for the game and
posting the first turn's message pinned with its buttons, and **My hand** answered ephemerally with the clicker's own
hand -- the first hidden thing the bot shows.

Saves go through `suppressed_cog_saves`, which reaches the Codex service.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

import discord

from codex.game import GameStatus
from cogs.codex import Codex
# The module object, not its dotted name: closing a bot that loaded the
# extension (test_codex_bot) drops `cogs.codex.*` from sys.modules, and a
# patch by name would then reach a fresh copy the `Codex` here never reads.
from cogs.codex import core as codex_core
from cogs.codex_views import CodexBrowser, LobbyView, TurnMessageView, TurnPanelView
from save_patches import suppressed_cog_saves

GUILD, LOBBY_CHANNEL, GAME_CHANNEL = 1, 10, 20  # typed in; the game's own
LOBBY_MESSAGE, TURN_MESSAGE = 100, 555


def user(user_id: int, name: str):
    member = mock.MagicMock(spec=discord.Member)
    member.id, member.display_name = user_id, name
    member.guild_permissions = SimpleNamespace(manage_channels=False)
    return member


def interaction(who, channel_id: int = LOBBY_CHANNEL, guild=None):
    fake = mock.MagicMock()
    fake.user = who
    fake.channel_id = channel_id
    fake.guild = guild
    fake.response.is_done.return_value = False
    fake.response.send_message = mock.AsyncMock()
    fake.response.edit_message = mock.AsyncMock()
    fake.response.defer = mock.AsyncMock()
    fake.followup.send = mock.AsyncMock()
    fake.original_response = mock.AsyncMock(return_value=SimpleNamespace(id=LOBBY_MESSAGE))
    return fake


def button(view: discord.ui.View, action: str) -> discord.ui.Button:
    return next(item for item in view.children if f":{action}:" in (item.custom_id or ""))


class Table:
    """The fakes one test plays through: a bot, a server, the channel the
    command is typed in and the game's own."""

    def __init__(self) -> None:
        self.bot = mock.MagicMock()
        self.lobby_message = mock.MagicMock(id=LOBBY_MESSAGE)
        self.turn_message = mock.MagicMock(id=TURN_MESSAGE)
        self.turn_message.pin = mock.AsyncMock()
        self.guild = mock.MagicMock(id=GUILD)
        self.game_channel = mock.MagicMock(id=GAME_CHANNEL, mention=f"<#{GAME_CHANNEL}>")
        self.game_channel.guild = self.guild
        self.game_channel.send = mock.AsyncMock(side_effect=[self.lobby_message, self.turn_message])
        self.game_channel.edit = mock.AsyncMock()
        self.game_channel.get_partial_message.return_value.edit = mock.AsyncMock()
        self.bot.get_channel.side_effect = {GAME_CHANNEL: self.game_channel}.get
        self.guild.categories = []
        self.guild.create_category = mock.AsyncMock(return_value=mock.MagicMock())
        self.guild.create_text_channel = mock.AsyncMock(return_value=self.game_channel)
        with mock.patch.object(codex_core, "load_games", return_value={}):
            self.cog = Codex(self.bot)
        self.cog.tokens.refresh = mock.AsyncMock()
        self.basher, self.fencer = user(101, "basher"), user(202, "fencer")

    async def open_lobby(self):
        call = interaction(self.basher, guild=self.guild)
        await self.cog.lobby.callback(self.cog, call)
        (game,) = self.cog.games.values()
        return game, call

    async def click(self, view, action: str, who, channel_id: int = GAME_CHANNEL):
        call = interaction(who, channel_id, guild=self.guild)
        await button(view, action).callback(call)
        return call

    async def pick(self, view, specs, who, menu: str = "heroes", channel_id: int = GAME_CHANNEL):
        """The lobby's hero menu answered with `specs` -- one spec, or a
        list of them -- by `who`."""
        select = next(item for item in view.children if f":{menu}:" in (item.custom_id or ""))
        select._values = [specs] if isinstance(specs, str) else list(specs)
        call = interaction(who, channel_id, guild=self.guild)
        await select.callback(call)
        return call

    async def started(self):
        game, _ = await self.open_lobby()
        lobby = LobbyView(self.cog, game.game_id)
        await self.pick(lobby, "bashing", self.basher)
        await self.pick(lobby, "finesse", self.fencer)
        start = await self.click(lobby, "start", self.fencer)
        return game, start


class LobbyTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_lobby_is_posted_in_a_channel_of_its_own(self) -> None:
        with suppressed_cog_saves():
            table = Table()
            game, call = await table.open_lobby()
        kwargs = table.guild.create_text_channel.call_args.kwargs
        self.assertEqual(kwargs["name"], "codex-1")
        self.assertEqual(table.guild.create_category.call_args.kwargs["name"], "Codex Games")
        everyone = kwargs["overwrites"][table.guild.default_role]
        self.assertTrue(everyone.view_channel)
        self.assertTrue(everyone.send_messages)
        (text,), sent = table.game_channel.send.call_args
        self.assertIn("Codex game 1", text)
        self.assertIsInstance(sent["view"], LobbyView)
        self.assertEqual(game.message_id, LOBBY_MESSAGE)
        self.assertEqual(game.channel_id, GAME_CHANNEL)
        self.assertIs(game.status, GameStatus.LOBBY)
        # The person who asked is told where, privately.
        self.assertIn(f"<#{GAME_CHANNEL}>", call.followup.send.call_args.args[0])
        self.assertTrue(call.followup.send.call_args.kwargs["ephemeral"])

    async def test_a_channel_that_cannot_be_made_opens_no_lobby(self) -> None:
        with suppressed_cog_saves():
            table = Table()
            table.guild.create_text_channel.side_effect = discord.Forbidden(mock.MagicMock(status=403), "no")
            call = interaction(table.basher, guild=table.guild)
            await table.cog.lobby.callback(table.cog, call)
        self.assertEqual(table.cog.games, {})
        self.assertTrue(call.followup.send.call_args.kwargs["ephemeral"])

    async def test_taking_a_seat_edits_the_lobby_in_place(self) -> None:
        with suppressed_cog_saves():
            table = Table()
            game, _ = await table.open_lobby()
            call = await table.pick(LobbyView(table.cog, game.game_id), "bashing", table.basher)
        self.assertEqual(game.player_1_id, 101)
        self.assertIn("basher", call.response.edit_message.call_args.kwargs["content"])

    async def test_a_hero_not_in_this_bot_yet_is_refused_privately(self) -> None:
        with suppressed_cog_saves():
            table = Table()
            game, _ = await table.open_lobby()
            lobby = LobbyView(table.cog, game.game_id)
            await table.pick(lobby, "bashing", table.basher)
            call = await table.pick(lobby, "law", table.fencer)
        self.assertTrue(call.response.send_message.call_args.kwargs["ephemeral"])
        self.assertIn("not in this bot yet", call.response.send_message.call_args.args[0])
        self.assertIsNone(game.player_2_id)

    async def test_start_waits_for_both_seats(self) -> None:
        with suppressed_cog_saves():
            table = Table()
            game, _ = await table.open_lobby()
            lobby = LobbyView(table.cog, game.game_id)
            await table.pick(lobby, "bashing", table.basher)
            call = await table.click(lobby, "start", table.basher)
        self.assertTrue(call.response.send_message.call_args.kwargs["ephemeral"])
        table.game_channel.edit.assert_not_awaited()
        self.assertIs(game.status, GameStatus.LOBBY)

    async def test_a_stranger_cannot_start(self) -> None:
        with suppressed_cog_saves():
            table = Table()
            game, _ = await table.open_lobby()
            lobby = LobbyView(table.cog, game.game_id)
            await table.pick(lobby, "bashing", table.basher)
            await table.pick(lobby, "finesse", table.fencer)
            call = await table.click(lobby, "start", user(999, "watcher"))
        self.assertTrue(call.response.send_message.call_args.kwargs["ephemeral"])
        self.assertIs(game.status, GameStatus.LOBBY)


class StandardLobbyTests(unittest.IsolatedAsyncioTestCase):
    """The standard game from the lobby: the mode, three heroes from the
    menu, the deck buttons for a team of more than one colour."""

    async def test_a_standard_team_through_the_menu_and_the_deck_buttons(self) -> None:
        with suppressed_cog_saves():
            table = Table()
            game, _ = await table.open_lobby()
            lobby = LobbyView(table.cog, game.game_id)
            mode = await table.click(lobby, "mode_standard", table.basher)
            self.assertEqual(game.mode, "standard")
            self.assertIn("three heroes a side", mode.response.edit_message.call_args.kwargs["content"])
            lobby = mode.response.edit_message.call_args.kwargs["view"]
            menu = next(item for item in lobby.children if ":heroes:" in (item.custom_id or ""))
            self.assertEqual((menu.min_values, menu.max_values), (3, 3))
            offered = {option.value for option in menu.options}
            self.assertEqual(offered, {"bashing", "finesse", "anarchy", "blood", "fire",
                                       "balance", "feral", "growth",
                                       "past", "present", "future",
                                       "demonology", "disease", "necromancy"})
            # No deck buttons while nobody's heroes span two colours.
            self.assertFalse([item for item in lobby.children if ":deck" in (item.custom_id or "")])
            picked = await table.pick(lobby, ["fire", "feral", "bashing"], table.basher)
            lobby = picked.response.edit_message.call_args.kwargs["view"]
            text = picked.response.edit_message.call_args.kwargs["content"]
            self.assertIn("Jaina Stormborne, Calamandra Moss, Troq Bashar", text)
            self.assertIn("choosing a starting deck", text)
            decks = [item for item in lobby.children if ":deck1_" in (item.custom_id or "")]
            self.assertEqual([item.label for item in decks],
                             ["basher: Red deck", "basher: Green deck", "basher: Neutral deck"])
            await table.pick(lobby, ["fire", "anarchy", "blood"], table.fencer)
            refused = await table.click(lobby, "deck1_green", table.fencer)
            self.assertTrue(refused.response.send_message.call_args.kwargs["ephemeral"])
            chose = await table.click(lobby, "deck1_green", table.basher)
            self.assertEqual(game.player_decks, {1: "green", 2: "red"})
            self.assertIn("the Green starting deck", chose.response.edit_message.call_args.kwargs["content"])
            await table.click(lobby, "start", table.fencer)
        self.assertIs(game.status, GameStatus.PLAYING)
        match = table.cog.service.load(game)
        self.assertEqual(sum(match.player(1).codex.values()), 72)

    async def test_a_watcher_cannot_change_the_game_once_somebody_sits(self) -> None:
        with suppressed_cog_saves():
            table = Table()
            game, _ = await table.open_lobby()
            lobby = LobbyView(table.cog, game.game_id)
            await table.pick(lobby, "bashing", table.basher)
            call = await table.click(lobby, "mode_standard", user(999, "watcher"))
        self.assertTrue(call.response.send_message.call_args.kwargs["ephemeral"])
        self.assertEqual(game.mode, "basic")


class StartTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_reaches_the_opening_position(self) -> None:
        with suppressed_cog_saves():
            table = Table()
            game, start = await table.started()

        self.assertIs(game.status, GameStatus.PLAYING)
        # The lobby's channel becomes the game's, renamed for the players;
        # its permissions stand, so watchers may still talk in it.
        table.guild.create_text_channel.assert_awaited_once()
        edited = table.game_channel.edit.call_args.kwargs
        self.assertEqual(edited["name"], "codex-1-basher-vs-fencer")
        self.assertNotIn("overwrites", edited)
        self.assertEqual(game.channel_id, GAME_CHANNEL)

        # The first turn's message, in the same channel: the board, the
        # turn's lines, the buttons; nothing pinned, since a pin's own
        # notice would land under the board.
        self.assertEqual(table.game_channel.send.await_count, 2)
        (text,), sent = table.game_channel.send.call_args
        first = game.player_1_name if table.cog.service.load(game).first == 1 else game.player_2_name
        self.assertIn("Turn 1", text)
        self.assertIn(first, text)
        self.assertNotIn("{", text)
        self.assertTrue(sent["file"].filename.startswith("codex-"))
        self.assertIsInstance(sent["view"], TurnMessageView)
        table.turn_message.pin.assert_not_awaited()
        self.assertEqual(game.turn_message_id, TURN_MESSAGE)

        # The lobby says the game has started, once, its buttons gone.
        edit = table.game_channel.get_partial_message.return_value.edit
        edit.assert_awaited_once()
        self.assertIn("The game has started.", edit.call_args.kwargs["content"])
        self.assertNotIn("Take a seat", edit.call_args.kwargs["content"])
        self.assertIsNone(edit.call_args.kwargs["view"])
        start.followup.send.assert_awaited()

    async def test_the_turn_message_names_no_card_in_a_hand(self) -> None:
        """The public text is the narration, which is public; no card of
        either hand appears in it."""
        with suppressed_cog_saves():
            table = Table()
            game, _ = await table.started()
        (text,), _ = table.game_channel.send.call_args
        match = table.cog.service.load(game)
        for seat in (1, 2):
            for slug in match.player(seat).hand:
                self.assertNotIn(table.cog.engine.name(slug), text)


class HandTests(unittest.IsolatedAsyncioTestCase):
    async def test_my_hand_is_the_clickers_and_ephemeral(self) -> None:
        """The active player's My hand is the panel; the other's, their
        hand. Both ephemeral, both the clicker's own cards."""
        with suppressed_cog_saves():
            table = Table()
            game, _ = await table.started()
            view = TurnMessageView(table.cog, game.game_id)
            mine = await table.click(view, "hand", table.basher, GAME_CHANNEL)
            theirs = await table.click(view, "hand", table.fencer, GAME_CHANNEL)

        match = table.cog.service.load(game)
        for call, seat in ((mine, 1), (theirs, 2)):
            with self.subTest(seat=seat):
                (caption,), kwargs = call.response.send_message.call_args
                self.assertTrue(kwargs["ephemeral"])
                if seat == match.active:
                    # One button, two answers (the author, 2026-10-08):
                    # the active player's is the control panel.
                    self.assertIsInstance(kwargs["view"], TurnPanelView)
                    self.assertTrue(kwargs["files"][0].filename.startswith("codex-hand-"))
                else:
                    self.assertTrue(kwargs["file"].filename.startswith("codex-hand-"))
                    self.assertIn(f"{len(match.player(seat).hand)} cards", caption)

    async def test_a_watcher_is_told_the_table_is_not_theirs(self) -> None:
        with suppressed_cog_saves():
            table = Table()
            game, _ = await table.started()
            call = await table.click(
                TurnMessageView(table.cog, game.game_id), "hand", user(999, "watcher"), GAME_CHANNEL,
            )
        (text,), kwargs = call.response.send_message.call_args
        self.assertTrue(kwargs["ephemeral"])
        self.assertNotIn("file", kwargs)
        self.assertIn("not yours", text)

    async def test_the_hand_command_answers_the_same(self) -> None:
        with suppressed_cog_saves():
            table = Table()
            game, _ = await table.started()
            call = interaction(table.fencer, GAME_CHANNEL, table.guild)
            await table.cog.hand.callback(table.cog, call)
        kwargs = call.response.send_message.call_args.kwargs
        self.assertTrue(kwargs["ephemeral"])
        self.assertTrue(kwargs["file"].filename.startswith("codex-hand-"))

    async def test_codex_is_the_clickers_own_and_ephemeral(self) -> None:
        with suppressed_cog_saves():
            table = Table()
            game, _ = await table.started()
            call = await table.click(
                TurnMessageView(table.cog, game.game_id), "codex", table.basher, GAME_CHANNEL,
            )
        kwargs = call.response.send_message.call_args.kwargs
        self.assertTrue(kwargs["ephemeral"])
        self.assertIsInstance(kwargs["view"], CodexBrowser)
        self.assertEqual(kwargs["view"].seat, 1)
        self.assertTrue(kwargs["file"].filename.startswith("codex-everything-"))


class TestGameCogTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_person_plays_both_sides_and_sees_the_active_sides_hand(self) -> None:
        with suppressed_cog_saves():
            table = Table()
            call = interaction(table.basher, guild=table.guild)
            await table.cog.lobby.callback(table.cog, call, test_game=True)
            (game,) = table.cog.games.values()
            lobby = LobbyView(table.cog, game.game_id)
            await table.pick(lobby, "bashing", table.basher, menu="heroes1")
            await table.pick(lobby, "finesse", table.basher, menu="heroes2")
            await table.click(lobby, "start", table.basher)
            hand = await table.click(TurnMessageView(table.cog, game.game_id), "hand", table.basher)

        self.assertTrue(game.test_game)
        self.assertIs(game.status, GameStatus.PLAYING)
        self.assertEqual(table.game_channel.edit.call_args.kwargs["name"], "codex-1-basher-vs-basher")
        match = table.cog.service.load(game)
        (caption,), kwargs = hand.response.send_message.call_args
        self.assertTrue(kwargs["ephemeral"])
        # Since step 4 the active side's My hand is its panel, which the
        # one person holding both seats may act from.
        self.assertIsInstance(kwargs["view"], TurnPanelView)
        self.assertEqual(kwargs["view"].seat, match.active)

    async def test_the_lobby_says_it_is_a_test_game(self) -> None:
        with suppressed_cog_saves():
            table = Table()
            await table.cog.lobby.callback(
                table.cog, interaction(table.basher, guild=table.guild), test_game=True,
            )
        (text,), _ = table.game_channel.send.call_args
        self.assertIn("test game", text)


class SwapViewTests(unittest.IsolatedAsyncioTestCase):
    async def test_swap_view_flips_the_layout_and_writes_through_the_gate(self) -> None:
        with suppressed_cog_saves():
            table = Table()
            game, _ = await table.started()
            table.cog.boards.refresh = mock.AsyncMock()
            view = TurnMessageView(table.cog, game.game_id)
            self.assertEqual(button(view, "swap").label, "View: side by side")
            call = await table.click(view, "swap", table.fencer, GAME_CHANNEL)
        self.assertEqual(game.board_layout, "side_by_side")
        call.response.defer.assert_awaited_once()
        table.cog.boards.refresh.assert_awaited_once()
        self.assertEqual(button(TurnMessageView(table.cog, game.game_id), "swap").label,
                         "View: stacked")


class RestartTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_restart_re_arms_the_turn_message(self) -> None:
        with suppressed_cog_saves():
            table = Table()
            game, _ = await table.started()
            bot = mock.MagicMock()
            with mock.patch.object(codex_core, "load_games", return_value=table.cog.games):
                Codex(bot)
        views = [call.args[0] for call in bot.add_view.call_args_list]
        self.assertTrue(any(isinstance(view, TurnMessageView) for view in views))
        self.assertEqual(bot.add_view.call_args.kwargs["message_id"], TURN_MESSAGE)

    async def test_a_playing_game_with_no_turn_message_is_logged(self) -> None:
        with suppressed_cog_saves():
            table = Table()
            game, _ = await table.started()
            game.turn_message_id = None
            with mock.patch.object(codex_core, "load_games", return_value=table.cog.games):
                with self.assertLogs(codex_core.LOGGER, "ERROR"):
                    Codex(mock.MagicMock())


if __name__ == "__main__":
    unittest.main()
