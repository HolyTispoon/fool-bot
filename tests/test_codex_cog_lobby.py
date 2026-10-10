"""
The Codex cog from `/codex start_game` to the opening board (docs/codex-bot.md,
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
from cogs.codex_views import CodexBrowser, LobbyView, MixedTeamView, TurnMessageView, TurnPanelView
from save_patches import suppressed_cog_saves

GUILD, LOBBY_CHANNEL, GAME_CHANNEL = 1, 10, 20  # typed in; the game's own
THREAD = 30  # the game's thread, where no channel can be made
LOBBY_MESSAGE, TURN_MESSAGE = 100, 555


def forbidden() -> discord.Forbidden:
    return discord.Forbidden(mock.MagicMock(status=403), "Missing Permissions")


def user(user_id: int, name: str):
    member = mock.MagicMock(spec=discord.Member)
    member.id, member.display_name = user_id, name
    member.guild_permissions = SimpleNamespace(manage_channels=False)
    return member


def interaction(who, channel_id: int = LOBBY_CHANNEL, guild=None, channel=None):
    fake = mock.MagicMock()
    fake.user = who
    fake.channel_id = channel_id
    fake.channel = channel
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
        # The channel the command is typed in, which a thread is opened
        # in where no channel can be made, and the game played in where
        # neither can.
        self.typed_channel = mock.MagicMock(spec=discord.TextChannel, id=LOBBY_CHANNEL,
                                            mention=f"<#{LOBBY_CHANNEL}>")
        self.typed_channel.send = mock.AsyncMock(side_effect=[self.lobby_message, self.turn_message])
        self.typed_channel.edit = mock.AsyncMock()
        self.thread = mock.MagicMock(spec=discord.Thread, id=THREAD, mention=f"<#{THREAD}>")
        self.thread.send = mock.AsyncMock(side_effect=[self.lobby_message, self.turn_message])
        self.thread.edit = mock.AsyncMock()
        self.thread.delete = mock.AsyncMock()
        self.typed_channel.create_thread = mock.AsyncMock(return_value=self.thread)
        for place in (self.typed_channel, self.thread):
            place.get_partial_message.return_value.edit = mock.AsyncMock()
        self.bot.get_channel.side_effect = {
            GAME_CHANNEL: self.game_channel, LOBBY_CHANNEL: self.typed_channel, THREAD: self.thread,
        }.get
        self.guild.categories = []
        self.guild.create_category = mock.AsyncMock(return_value=mock.MagicMock())
        self.guild.create_text_channel = mock.AsyncMock(return_value=self.game_channel)
        with mock.patch.object(codex_core, "load_games", return_value={}):
            self.cog = Codex(self.bot)
        self.cog.tokens.refresh = mock.AsyncMock()
        self.basher, self.fencer = user(101, "basher"), user(202, "fencer")

    async def open_lobby(self):
        call = interaction(self.basher, guild=self.guild, channel=self.typed_channel)
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
        await self.pick(lobby, "bashing", self.basher, channel_id=game.channel_id)
        await self.pick(lobby, "finesse", self.fencer, channel_id=game.channel_id)
        start = await self.click(lobby, "start", self.fencer, game.channel_id)
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

    async def test_taking_a_seat_edits_the_lobby_in_place(self) -> None:
        with suppressed_cog_saves():
            table = Table()
            game, _ = await table.open_lobby()
            call = await table.pick(LobbyView(table.cog, game.game_id), "bashing", table.basher)
        self.assertEqual(game.player_1_id, 101)
        self.assertIn("basher", call.response.edit_message.call_args.kwargs["content"])

    async def test_every_hero_is_offered_and_taken(self) -> None:
        """Step 13: the menu offers all twenty heroes, and a blue one takes
        the seat like any other."""
        with suppressed_cog_saves():
            table = Table()
            game, _ = await table.open_lobby()
            lobby = LobbyView(table.cog, game.game_id)
            menu = next(item for item in lobby.children if ":heroes" in (item.custom_id or ""))
            self.assertEqual(len(menu.options), 20)
            await table.pick(lobby, "bashing", table.basher)
            call = await table.pick(lobby, "law", table.fencer)
        self.assertIn("fencer", call.response.edit_message.call_args.kwargs["content"])
        self.assertEqual(game.player_2_id, 202)

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


class LobbyPlaceTests(unittest.IsolatedAsyncioTestCase):
    """Where the bot may not make a channel, the game is played in a
    thread of the channel the command was typed in; where it may make
    neither, in that channel itself (the author, 2026-10-10)."""

    async def test_no_channel_opens_a_thread(self) -> None:
        with suppressed_cog_saves():
            table = Table()
            table.guild.create_text_channel.side_effect = forbidden()
            game, call = await table.open_lobby()
        kwargs = table.typed_channel.create_thread.call_args.kwargs
        self.assertEqual(kwargs["name"], "codex-1")
        self.assertIs(kwargs["type"], discord.ChannelType.public_thread)
        (text,), sent = table.thread.send.call_args
        self.assertIn("Codex game 1", text)
        self.assertIsInstance(sent["view"], LobbyView)
        self.assertEqual((game.venue, game.channel_id, game.message_id), ("thread", THREAD, LOBBY_MESSAGE))
        table.typed_channel.send.assert_not_awaited()
        reply = call.followup.send.call_args
        self.assertIn(f"<#{THREAD}>", reply.args[0])
        self.assertTrue(reply.kwargs["ephemeral"])

    async def test_no_channel_and_no_thread_opens_the_lobby_here(self) -> None:
        with suppressed_cog_saves():
            table = Table()
            table.guild.create_text_channel.side_effect = forbidden()
            table.typed_channel.create_thread.side_effect = forbidden()
            game, call = await table.open_lobby()
        (text,), sent = table.typed_channel.send.call_args
        self.assertIn("Codex game 1", text)
        self.assertIsInstance(sent["view"], LobbyView)
        self.assertEqual((game.venue, game.channel_id), ("here", LOBBY_CHANNEL))
        self.assertIn("here", call.followup.send.call_args.args[0])

    async def test_a_channel_whose_lobby_cannot_be_posted_gives_way_to_a_thread(self) -> None:
        with suppressed_cog_saves():
            table = Table()
            table.game_channel.send.side_effect = forbidden()
            table.game_channel.delete = mock.AsyncMock()
            game, _ = await table.open_lobby()
        table.game_channel.delete.assert_awaited_once()
        self.assertEqual((game.venue, game.channel_id), ("thread", THREAD))

    async def test_nowhere_opens_no_lobby(self) -> None:
        with suppressed_cog_saves():
            table = Table()
            table.guild.create_text_channel.side_effect = forbidden()
            table.typed_channel.create_thread.side_effect = forbidden()
            table.typed_channel.send.side_effect = forbidden()
            call = interaction(table.basher, guild=table.guild, channel=table.typed_channel)
            await table.cog.lobby.callback(table.cog, call)
        self.assertEqual(table.cog.games, {})
        self.assertIn("nor post", call.followup.send.call_args.args[0])
        self.assertTrue(call.followup.send.call_args.kwargs["ephemeral"])

    async def test_a_channel_holds_one_game_at_a_time(self) -> None:
        with suppressed_cog_saves():
            table = Table()
            table.guild.create_text_channel.side_effect = forbidden()
            table.typed_channel.create_thread.side_effect = forbidden()
            first, _ = await table.open_lobby()
            call = interaction(table.basher, guild=table.guild, channel=table.typed_channel)
            await table.cog.lobby.callback(table.cog, call)
        self.assertEqual(list(table.cog.games.values()), [first])
        self.assertEqual(table.typed_channel.send.await_count, 1)
        self.assertIn("already open", call.followup.send.call_args.args[0])

    async def test_start_in_a_thread_renames_the_thread(self) -> None:
        with suppressed_cog_saves():
            table = Table()
            table.guild.create_text_channel.side_effect = forbidden()
            game, _ = await table.started()
        self.assertIs(game.status, GameStatus.PLAYING)
        self.assertEqual(table.thread.edit.call_args.kwargs["name"], "codex-1-basher-vs-fencer")
        self.assertEqual(game.turn_message_id, TURN_MESSAGE)

    async def test_a_click_takes_the_thread_out_of_the_archive(self) -> None:
        """A thread idle long enough is archived by Discord; a click on
        its game first takes it out, so the click's answer can be
        written there. A thread not archived costs nothing."""
        with suppressed_cog_saves():
            table = Table()
            table.guild.create_text_channel.side_effect = forbidden()
            game, _ = await table.started()
            view = TurnMessageView(table.cog, game.game_id)
            item = button(view, "swap")
            table.cog.boards.refresh = mock.AsyncMock()
            table.thread.archived = False
            table.thread.edit.reset_mock()
            awake = interaction(table.fencer, THREAD, guild=table.guild, channel=table.thread)
            await view._scheduled_task(item, awake)
            table.thread.edit.assert_not_awaited()
            table.thread.archived = True
            asleep = interaction(table.fencer, THREAD, guild=table.guild, channel=table.thread)
            await view._scheduled_task(item, asleep)
        table.thread.edit.assert_awaited_once_with(archived=False)
        asleep.response.defer.assert_awaited_once()

    async def test_start_here_leaves_the_channel_as_it_is(self) -> None:
        with suppressed_cog_saves():
            table = Table()
            table.guild.create_text_channel.side_effect = forbidden()
            table.typed_channel.create_thread.side_effect = forbidden()
            game, _ = await table.started()
        self.assertIs(game.status, GameStatus.PLAYING)
        table.typed_channel.edit.assert_not_awaited()
        self.assertEqual(game.turn_message_id, TURN_MESSAGE)


class StandardLobbyTests(unittest.IsolatedAsyncioTestCase):
    """The standard game from the lobby: the mode, a colour's deck by
    its name or **Mixed colours** and its two menus, the first hero's
    colour the starting deck."""

    async def test_a_colour_deck_and_a_mixed_team(self) -> None:
        with suppressed_cog_saves():
            table = Table()
            game, _ = await table.open_lobby()
            lobby = LobbyView(table.cog, game.game_id)
            mode = await table.click(lobby, "mode_standard", table.basher)
            self.assertEqual(game.mode, "standard")
            self.assertIn("three heroes a side", mode.response.edit_message.call_args.kwargs["content"])
            lobby = mode.response.edit_message.call_args.kwargs["view"]
            # No hero menu: a button per colour's deck, named, and Mixed.
            self.assertFalse([item for item in lobby.children if ":heroes" in (item.custom_id or "")])
            # Six decks and Mixed: five to a row, as Discord allows.
            self.assertEqual(
                [[item.label for item in lobby.children if item.row == row] for row in (1, 2)],
                [["Blood Anarchs", "Moss Sentinels", "Vortoss Conclave", "Blackhand Scourge",
                  "Whitestar Order"],
                 ["Flagstone Dominion", "Mixed colours"]],
            )
            chose = await table.click(lobby, "team_green", table.fencer)
            self.assertEqual(game.player_specs[1], ["balance", "feral", "growth"])
            self.assertEqual(game.player_decks[1], "green")
            self.assertIn("**Moss Sentinels**", chose.response.edit_message.call_args.kwargs["content"])

            mixed = await table.click(lobby, "mixed", table.basher)
            self.assertTrue(mixed.response.send_message.call_args.kwargs["ephemeral"])
            picker = mixed.response.send_message.call_args.kwargs["view"]
            self.assertIsInstance(picker, MixedTeamView)
            offered = {option.value for option in picker.first_menu.options}
            self.assertEqual(offered, {"bashing", "finesse", "anarchy", "blood", "fire",
                                       "balance", "feral", "growth",
                                       "past", "present", "future",
                                       "demonology", "disease", "necromancy",
                                       "discipline", "ninjutsu", "strength",
                                       "law", "peace", "truth"})
            self.assertIn("starting deck", picker.first_menu.placeholder)
            self.assertEqual((picker.others_menu.min_values, picker.others_menu.max_values), (2, 2))

            first = interaction(table.basher, GAME_CHANNEL, guild=table.guild)
            picker.first_menu._values = ["feral"]
            await picker.first_menu.callback(first)
            self.assertIsNone(game.seat_of(table.basher.id))
            self.assertIn("Calamandra Moss", first.response.edit_message.call_args.kwargs["content"])
            others = interaction(table.basher, GAME_CHANNEL, guild=table.guild)
            picker.others_menu._values = ["fire", "bashing"]
            await picker.others_menu.callback(others)
            self.assertEqual(game.player_specs[2], ["feral", "fire", "bashing"])
            self.assertEqual(game.player_decks[2], "green")
            self.assertIn("Feral/Fire/Bashing", others.response.edit_message.call_args.kwargs["content"])
            # The lobby, edited through the channel, says who is first.
            edit = table.game_channel.get_partial_message.return_value.edit
            text = edit.call_args.kwargs["content"]
            self.assertIn("**Feral/Fire/Bashing** (Calamandra Moss first, then Jaina Stormborne, "
                          "Troq Bashar); the Green starting deck", text)
            await table.click(lobby, "start", table.fencer)
        self.assertIs(game.status, GameStatus.PLAYING)
        match = table.cog.service.load(game)
        self.assertEqual(sum(match.player(1).codex.values()), 72)
        self.assertEqual(match.player(2).deck_color, "green")

    async def test_the_mixed_picker_shows_the_records_refusal(self) -> None:
        """A hero twice -- first and among the other two -- is the
        record's to refuse, and the picker says so."""
        with suppressed_cog_saves():
            table = Table()
            game, _ = await table.open_lobby()
            await table.click(LobbyView(table.cog, game.game_id), "mode_standard", table.basher)
            mixed = await table.click(LobbyView(table.cog, game.game_id), "mixed", table.basher)
            picker = mixed.response.send_message.call_args.kwargs["view"]
            picker.first_menu._values = ["fire"]
            await picker.first_menu.callback(interaction(table.basher, GAME_CHANNEL, guild=table.guild))
            call = interaction(table.basher, GAME_CHANNEL, guild=table.guild)
            picker.others_menu._values = ["fire", "feral"]
            await picker.others_menu.callback(call)
        self.assertIsNone(game.seat_of(table.basher.id))
        self.assertIn("three different heroes", call.response.edit_message.call_args.kwargs["content"])

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
    async def test_a_standard_test_game_picks_each_side_by_its_own_buttons(self) -> None:
        """One person, two sides: a row of deck buttons for each, the
        side written in front and its team lit, and Mixed for each."""
        with suppressed_cog_saves():
            table = Table()
            call = interaction(table.basher, guild=table.guild)
            await table.cog.lobby.callback(table.cog, call, test_game=True)
            (game,) = table.cog.games.values()
            await table.click(LobbyView(table.cog, game.game_id), "mode_standard", table.basher)
            await table.click(LobbyView(table.cog, game.game_id), "team1_red", table.basher)
            await table.click(LobbyView(table.cog, game.game_id), "team2_purple", table.basher)
            lobby = LobbyView(table.cog, game.game_id)
        self.assertEqual(game.player_specs, {1: ["anarchy", "blood", "fire"],
                                             2: ["future", "past", "present"]})
        # Each side's six decks and Mixed take two rows: P1's rows 1 and
        # 2, P2's 3 and 4.
        rows = {row: [item for item in lobby.children if item.row == row] for row in (1, 2, 3, 4)}
        self.assertEqual([item.label for item in rows[1] + rows[2]],
                         ["P1: Blood Anarchs", "P1: Moss Sentinels", "P1: Vortoss Conclave",
                          "P1: Blackhand Scourge", "P1: Whitestar Order",
                          "P1: Flagstone Dominion", "P1: Mixed colours"])
        self.assertEqual([item.label for item in rows[3] + rows[4]
                          if item.style is discord.ButtonStyle.success],
                         ["P2: Vortoss Conclave"])
        self.assertTrue(game.may_start())

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
