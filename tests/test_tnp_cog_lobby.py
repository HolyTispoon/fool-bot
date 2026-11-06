"""
The TNP cog from a lobby to turn 1 (step 5 of docs/tnp-bot.md), driven
with Discord faked: `/tnp create_game` and the hub's **TNP** button each
open a channel `tnp-<n>` under TNP Games with the lobby in it and the
asker sat as Blue; a second person takes Green; Start renames the
channel `tnp-<n>-<blue>-vs-<green>`, closes the lobby and posts the
table -- the map, the turn and the phase, who has locked in -- with
**My board**, which answers each player alone with their own board.
A restart re-arms the lobby's and the table's views, and a game that
cannot be read is logged and skipped.

Saves go through `suppressed_cog_saves`, which reaches the TNP service.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

import discord

from cogs.d12ball_views import NewGameHubView
from cogs.d12ball_views import lobby as hub_views
from cogs.tnp import Tnp
# The module objects, not dotted names: a bot test that loads and closes
# an extension drops `cogs.tnp.*` from sys.modules (docs/design/testing.md).
from cogs.tnp import core as tnp_core
from cogs.tnp import table as tnp_table
from cogs.tnp import turns as tnp_turns
from cogs.tnp_helpers import UNAVAILABLE, channel_name
from cogs.tnp_views import LobbyView, TableView
from save_patches import suppressed_cog_saves
from tnp.game import GameStatus, TnpGame

GUILD, GAME_CHANNEL, HUB_CHANNEL, THREAD = 1, 20, 5, 30
LOBBY_MESSAGE, TABLE_MESSAGE = 100, 200
MAP_PNG, BOARD_PNG = b"map-png", b"board-png"


def user(user_id: int, name: str, helper: bool = False):
    member = mock.MagicMock(spec=discord.Member)
    member.id, member.display_name = user_id, name
    member.guild_permissions = SimpleNamespace(manage_channels=helper)
    return member


def interaction(who, channel_id: int = GAME_CHANNEL, guild=None, channel=None):
    fake = mock.MagicMock()
    fake.user = who
    fake.channel_id = channel_id
    fake.channel = channel
    fake.guild = guild
    fake.response.is_done.return_value = False
    fake.response.send_message = mock.AsyncMock()
    fake.response.edit_message = mock.AsyncMock()

    async def defer(**_):
        fake.response.is_done.return_value = True

    fake.response.defer = mock.AsyncMock(side_effect=defer)
    fake.followup.send = mock.AsyncMock()
    fake.edit_original_response = mock.AsyncMock()
    return fake


def button(view: discord.ui.View, action: str) -> discord.ui.Button:
    return next(item for item in view.children if f":{action}:" in (item.custom_id or ""))


def everything_said(*calls) -> str:
    """Every text a set of awaited mocks was given, joined."""
    said = []
    for call in calls:
        for one in call.await_args_list:
            said.extend(str(arg) for arg in one.args)
            said.extend(str(value) for key, value in one.kwargs.items() if key == "content")
    return "\n".join(said)


class Table:
    """The fakes one test plays through: a bot, a server and the game's
    channel."""

    def __init__(self) -> None:
        self.bot = mock.MagicMock()
        self.lobby_message = mock.MagicMock(id=LOBBY_MESSAGE)
        self.table_message = mock.MagicMock(id=TABLE_MESSAGE)
        self.guild = mock.MagicMock(id=GUILD)
        self.guild.categories = []
        self.category = mock.MagicMock()
        self.guild.create_category = mock.AsyncMock(return_value=self.category)
        self.channel = mock.MagicMock(spec=discord.TextChannel, id=GAME_CHANNEL,
                                      mention=f"<#{GAME_CHANNEL}>")
        self.channel.send = mock.AsyncMock(side_effect=[self.lobby_message, self.table_message])
        self.channel.edit = mock.AsyncMock()
        self.channel.delete = mock.AsyncMock()
        self.guild.create_text_channel = mock.AsyncMock(return_value=self.channel)
        # The channel the lobby is asked for in, where a thread is opened
        # when no channel can be made.
        self.thread = mock.MagicMock(spec=discord.Thread, id=THREAD, mention=f"<#{THREAD}>",
                                     archived=False)
        self.thread.send = mock.AsyncMock(side_effect=[self.lobby_message, self.table_message])
        self.thread.edit = mock.AsyncMock()
        self.thread.delete = mock.AsyncMock()
        self.typed = mock.MagicMock(spec=discord.TextChannel, id=HUB_CHANNEL)
        self.typed.create_thread = mock.AsyncMock(return_value=self.thread)
        self.bot.get_channel.side_effect = {GAME_CHANNEL: self.channel, THREAD: self.thread}.get
        self.cog = Tnp(self.bot)
        self.blue, self.green = user(101, "Alice"), user(202, "Bob")
        self.watcher = user(303, "Carol")

    async def load(self) -> None:
        with mock.patch.object(tnp_core, "load_games", return_value={}):
            await self.cog.cog_load()

    @property
    def game(self) -> TnpGame:
        (game,) = self.cog.games.values()
        return game

    async def create_game(self, who=None, test_game: bool = False):
        call = interaction(who or self.blue, channel_id=HUB_CHANNEL, guild=self.guild,
                           channel=self.typed)
        await self.cog.create_game.callback(self.cog, call, test_game)
        return call

    async def click(self, view, action: str, who, channel=None):
        call = interaction(who, guild=self.guild, channel=channel)
        await button(view, action).callback(call)
        return call


def pictures():
    """The map and the boards stood in for, so a test draws nothing."""
    return (
        mock.patch.object(tnp_table, "render_map", return_value=MAP_PNG),
        mock.patch.object(tnp_turns, "render_map", return_value=MAP_PNG),
        mock.patch.object(tnp_turns, "render_board", return_value=BOARD_PNG),
    )


class TnpLobbyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.saves = suppressed_cog_saves()
        self.saves.__enter__()
        self.table = Table()
        await self.table.load()
        for patch in pictures():
            patch.start()

    async def asyncTearDown(self) -> None:
        mock.patch.stopall()
        self.saves.__exit__(None, None, None)

    async def start(self):
        table = self.table
        await table.create_game()
        await table.click(LobbyView(table.cog, table.game.game_id), "seat_green", table.green)
        start = await table.click(LobbyView(table.cog, table.game.game_id), "start", table.blue)
        return start

    async def test_create_game_opens_a_channel_with_the_lobby_and_the_asker_as_blue(self) -> None:
        table = self.table
        call = await table.create_game()
        game = table.game
        kwargs = table.guild.create_text_channel.await_args.kwargs
        self.assertEqual(kwargs["name"], f"tnp-{game.game_number}")
        self.assertIs(kwargs["category"], table.category)
        table.guild.create_category.assert_awaited_once()
        self.assertEqual(table.guild.create_category.await_args.kwargs["name"], "TNP Games")
        # Open to the server: a watcher may look in and take the free seat.
        everyone = kwargs["overwrites"][table.guild.default_role]
        self.assertTrue(everyone.view_channel)
        self.assertEqual(game.seats["blue"], {"id": 101, "name": "Alice"})
        self.assertIsNone(game.seats["green"]["id"])
        self.assertEqual((game.channel_id, game.message_id), (GAME_CHANNEL, LOBBY_MESSAGE))
        lobby_text = table.channel.send.await_args.args[0]
        self.assertIn("**Blue**: Alice", lobby_text)
        self.assertIn("**Green**: *open*", lobby_text)
        self.assertIsInstance(table.channel.send.await_args.kwargs["view"], LobbyView)
        self.assertIn(f"<#{GAME_CHANNEL}>", call.followup.send.await_args.args[0])
        self.assertTrue(call.followup.send.await_args.kwargs["ephemeral"])

    def refuse_channels(self) -> None:
        self.table.guild.create_text_channel.side_effect = discord.Forbidden(
            mock.MagicMock(status=403), "Missing Permissions",
        )

    async def test_where_no_channel_may_be_made_the_game_is_played_in_a_thread(self) -> None:
        """The author, 2026-11-06: a thread in the channel the lobby was
        asked for in, named as the channel would have been."""
        table = self.table
        self.refuse_channels()
        call = await table.create_game()
        game = table.game
        kwargs = table.typed.create_thread.await_args.kwargs
        self.assertEqual(kwargs["name"], f"tnp-{game.game_number}")
        self.assertEqual(kwargs["type"], discord.ChannelType.public_thread)
        self.assertEqual((game.venue, game.channel_id, game.message_id),
                         ("thread", THREAD, LOBBY_MESSAGE))
        self.assertIsInstance(table.thread.send.await_args.kwargs["view"], LobbyView)
        self.assertIn("thread", call.followup.send.await_args.args[0])
        # Start renames the thread and posts the table in it.
        view = LobbyView(table.cog, game.game_id)
        await table.click(view, "seat_green", table.green, table.thread)
        await table.click(view, "start", table.blue, table.thread)
        self.assertEqual(table.thread.edit.await_args.kwargs["name"],
                         f"tnp-{game.game_number}-alice-vs-bob")
        self.assertIsInstance(table.thread.send.await_args.kwargs["view"], TableView)
        self.assertEqual(game.table_message_id, TABLE_MESSAGE)

    async def test_neither_a_channel_nor_a_thread_keeps_no_game(self) -> None:
        table = self.table
        self.refuse_channels()
        table.typed.create_thread.side_effect = discord.Forbidden(
            mock.MagicMock(status=403), "Missing Permissions",
        )
        call = await table.create_game()
        self.assertEqual(table.cog.games, {})
        said = call.followup.send.await_args.args[0]
        self.assertIn("Manage Channels", said)
        self.assertIn("Create Public Threads", said)

    async def test_a_click_wakes_an_archived_thread_first(self) -> None:
        table = self.table
        self.refuse_channels()
        await table.create_game()
        table.thread.archived = True
        view = LobbyView(table.cog, table.game.game_id)
        call = interaction(table.green, guild=table.guild, channel=table.thread)
        self.assertTrue(await view.interaction_check(call))
        table.thread.edit.assert_awaited_once_with(archived=False)
        # Not archived: nothing is spent.
        table.thread.archived = False
        table.thread.edit.reset_mock()
        self.assertTrue(await view.interaction_check(call))
        table.thread.edit.assert_not_called()

    async def test_taking_and_leaving_a_seat_edits_the_lobby_through_the_click(self) -> None:
        table = self.table
        await table.create_game()
        view = LobbyView(table.cog, table.game.game_id)
        call = await table.click(view, "seat_green", table.green)
        self.assertEqual(table.game.seats["green"]["id"], 202)
        self.assertIn("**Green**: Bob", call.response.edit_message.await_args.kwargs["content"])
        refused = await table.click(view, "seat_green", table.watcher)
        self.assertIn("taken", refused.response.send_message.await_args.args[0])
        await table.click(view, "leave", table.green)
        self.assertIsNone(table.game.seats["green"]["id"])
        # The channel's own bucket is never spent on the lobby's edits.
        table.channel.get_partial_message.assert_not_called()

    async def test_the_lobby_offers_the_factions_with_only_the_humans_playable(self) -> None:
        table = self.table
        await table.create_game()
        view = LobbyView(table.cog, table.game.game_id)
        self.assertEqual(button(view, "seat_blue").label, "Join as Blue")
        humans, xzzzx, dragons = (button(view, f"join_{one}") for one in ("humans", "xzzzx", "space_dragons"))
        self.assertEqual([humans.label, xzzzx.label, dragons.label],
                         ["Join as Humans", "Join as XzzzX", "Join as Space Dragons"])
        self.assertEqual([humans.disabled, xzzzx.disabled, dragons.disabled], [False, True, True])
        self.assertNotIn("Take a seat", table.cog.lobby_text(table.game))
        # Join as Humans takes the first free seat.
        await table.click(view, "join_humans", table.green)
        self.assertEqual(table.game.seats["green"]["id"], 202)

    async def test_the_test_game_button_toggles_and_is_a_seated_players(self) -> None:
        table = self.table
        await table.create_game()
        view = LobbyView(table.cog, table.game.game_id)
        refused = await table.click(view, "test_game", table.watcher)
        self.assertIn("seated player", refused.response.send_message.await_args.args[0])
        self.assertFalse(table.game.test_game)
        # The basic game is the one to play; the advanced is greyed out.
        self.assertFalse(button(view, "basic").disabled)
        self.assertTrue(button(view, "advanced").disabled)
        refused = await table.click(view, "advanced", table.blue)
        self.assertIn("not built yet", refused.response.send_message.await_args.args[0])
        self.assertFalse(table.game.advanced)
        call = await table.click(view, "test_game", table.blue)
        self.assertTrue(table.game.test_game)
        self.assertIn("test game", call.response.edit_message.await_args.kwargs["content"])
        self.assertEqual(button(call.response.edit_message.await_args.kwargs["view"], "test_game").label,
                         "Test game: on")
        # Both seats one person's; turning it off opens Green again.
        await table.click(view, "seat_green", table.blue)
        await table.click(view, "test_game", table.blue)
        self.assertFalse(table.game.test_game)
        self.assertIsNone(table.game.seats["green"]["id"])
        self.assertEqual(table.game.seats["blue"]["id"], table.blue.id)

    async def test_start_is_refused_until_both_seats_are_taken(self) -> None:
        table = self.table
        await table.create_game()
        call = await table.click(LobbyView(table.cog, table.game.game_id), "start", table.blue)
        self.assertIn("Both seats", call.followup.send.await_args.args[0])
        self.assertIs(table.game.status, GameStatus.LOBBY)

    async def test_a_watcher_may_not_start(self) -> None:
        table = self.table
        await table.create_game()
        await table.click(LobbyView(table.cog, table.game.game_id), "seat_green", table.green)
        call = await table.click(LobbyView(table.cog, table.game.game_id), "start", table.watcher)
        self.assertIn("seated player", call.response.send_message.await_args.args[0])
        self.assertIs(table.game.status, GameStatus.LOBBY)

    async def test_start_reaches_turn_1_with_the_table_posted(self) -> None:
        table = self.table
        start = await self.start()
        game = table.game
        self.assertIs(game.status, GameStatus.PLAYING)
        table.channel.edit.assert_awaited_once()
        self.assertEqual(table.channel.edit.await_args.kwargs["name"],
                         f"tnp-{game.game_number}-alice-vs-bob")
        self.assertEqual(channel_name(game), f"tnp-{game.game_number}-alice-vs-bob")
        # The lobby closed through the click's own response, buttons gone.
        closed = start.edit_original_response.await_args.kwargs
        self.assertIsNone(closed["view"])
        self.assertIn("The game has started.", closed["content"])
        text = table.channel.send.await_args.args[0]
        kwargs = table.channel.send.await_args.kwargs
        self.assertEqual(text.splitlines(), [
            "**Turn 1**: Infrastructure and Deployment",
            "**Blue** (Alice) is planning.",
            "**Green** (Bob) is planning.",
        ])
        self.assertEqual(kwargs["file"].filename, "tnp-map.png")
        self.assertIsInstance(kwargs["view"], TableView)
        self.assertEqual(game.table_message_id, TABLE_MESSAGE)
        # Three requests on the channel's own bucket at Start: the
        # lobby's send, the rename, the table's send.
        self.assertEqual(table.channel.send.await_count + table.channel.edit.await_count, 3)

    async def test_my_board_answers_each_player_alone_with_their_own_board(self) -> None:
        table = self.table
        await self.start()
        game = table.game
        boards = {}
        for who, seat in ((table.blue, "blue"), (table.green, "green")):
            with mock.patch.object(tnp_turns, "board_brief", wraps=tnp_turns.board_brief) as brief:
                call = await table.click(TableView(table.cog, game.game_id), "board", who)
            self.assertEqual([one.args[2] for one in brief.call_args_list], [seat])
            (sent,) = call.followup.send.await_args_list
            self.assertTrue(sent.kwargs["ephemeral"])
            self.assertEqual(sent.kwargs["file"].filename, f"tnp-board-{seat}.png")
            boards[seat] = sent.args[0]
        self.assertIn("your board, **Blue** (Alice)", boards["blue"])
        self.assertIn("Pool: 5 materials", boards["blue"])
        self.assertIn("Build: Worker (1 material, up to 4)", boards["blue"])
        self.assertIn("Attack spots: A, B", boards["blue"])
        self.assertIn("**Green** (Bob)", boards["green"])
        self.assertNotIn("Alice", boards["green"])

    async def test_a_watcher_sees_no_board(self) -> None:
        table = self.table
        await self.start()
        call = await table.click(TableView(table.cog, table.game.game_id), "board", table.watcher)
        self.assertIn("watching", call.response.send_message.await_args.args[0])
        call.followup.send.assert_not_called()

    async def test_a_test_game_shows_both_boards_to_its_one_player(self) -> None:
        table = self.table
        await table.create_game(test_game=True)
        view = LobbyView(table.cog, table.game.game_id)
        await table.click(view, "seat_green", table.blue)
        await table.click(view, "start", table.blue)
        call = await table.click(TableView(table.cog, table.game.game_id), "board", table.blue)
        self.assertEqual(
            [sent.kwargs["file"].filename for sent in call.followup.send.await_args_list],
            ["tnp-board-blue.png", "tnp-board-green.png"],
        )

    async def test_nothing_of_a_plan_reaches_the_channel(self) -> None:
        """A seat's saved plan (TNP 5.2, 5.3) is its own: the table's text
        reads who has locked in and nothing more (`table_lines`)."""
        table = self.table
        await self.start()
        game = table.game
        match = table.cog.service.load(game)
        match.seat("blue").plan = {"build": {"tank": 2}, "structures": ["factory"]}
        table.cog.service.persist(game, match)
        text = table.cog.table_text(game, match)
        self.assertNotIn("Tank", text)
        self.assertNotIn("Factory", text)
        public = everything_said(table.channel.send, table.channel.edit)
        self.assertNotIn("Tank", public)

    async def test_resume_posts_a_fresh_table(self) -> None:
        table = self.table
        await self.start()
        game = table.game
        table.channel.send.side_effect = None
        table.channel.send.return_value = mock.MagicMock(id=TABLE_MESSAGE + 1)
        call = interaction(table.blue, guild=table.guild)
        await table.cog.resume.callback(table.cog, call)
        self.assertEqual(game.table_message_id, TABLE_MESSAGE + 1)
        self.assertIn("back up", call.followup.send.await_args.args[0])


class TnpRestartTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_restart_re_arms_the_lobby_and_the_table(self) -> None:
        from tnp.components import opening
        from tnp.engine import RulesEngine

        lobby = TnpGame("lobby", game_number=1, message_id=11)
        playing = TnpGame("playing", game_number=2, status=GameStatus.PLAYING, table_message_id=22,
                          match_state=opening(RulesEngine().catalog).to_dict())
        broken = TnpGame("broken", game_number=3, status=GameStatus.PLAYING, table_message_id=33,
                         match_state={"seats": "not a table"})
        lost = TnpGame("lost", game_number=4, status=GameStatus.PLAYING,
                       match_state=opening(RulesEngine().catalog).to_dict())
        bot = mock.MagicMock()
        cog = Tnp(bot)
        games = {one.game_id: one for one in (lobby, playing, broken, lost)}
        with mock.patch.object(tnp_core, "load_games", return_value=games), \
                self.assertLogs("cogs.tnp.core", "ERROR") as logged:
            await cog.cog_load()
        armed = {(type(call.args[0]), call.kwargs["message_id"]) for call in bot.add_view.call_args_list}
        self.assertEqual(armed, {(LobbyView, 11), (TableView, 22)})
        said = "\n".join(logged.output)
        self.assertIn("broken", said)
        self.assertIn("/tnp resume", said)


class TnpHubButtonTests(unittest.IsolatedAsyncioTestCase):
    """The hub's **TNP** button (docs/design/hub-and-lobby.md): it opens a
    lobby through the TNP cog, found by name, and says TNP is unavailable
    where the cog is not loaded."""

    def hub(self, tnp_cog):
        d12 = mock.MagicMock()
        d12.d12_button_emoji = None
        d12.codex_emoji = d12.tnp_emoji = None
        d12.bot.get_cog.side_effect = {"Tnp": tnp_cog}.get
        return NewGameHubView(d12)

    async def test_the_button_opens_a_tnp_lobby(self) -> None:
        with suppressed_cog_saves(), pictures()[0]:
            table = Table()
            await table.load()
            view = self.hub(table.cog)
            tnp = next(item for item in view.children if item.custom_id == "d12ball:hub:tnp")
            self.assertEqual(tnp.label, "TNP")
            call = interaction(table.blue, channel_id=HUB_CHANNEL, guild=table.guild)
            await tnp.callback(call)
            self.assertEqual(table.game.seats["blue"]["id"], 101)
            self.assertEqual(table.game.channel_id, GAME_CHANNEL)
            self.assertIn("Lobby open", call.followup.send.await_args.args[0])

    async def test_the_button_without_the_tnp_cog_says_so(self) -> None:
        view = self.hub(None)
        tnp = next(item for item in view.children if item.custom_id == "d12ball:hub:tnp")
        call = interaction(user(101, "Alice"))
        with self.assertLogs(hub_views.LOGGER, "ERROR"):
            await tnp.callback(call)
        call.response.send_message.assert_awaited_once_with(
            hub_views.TNP_HUB_UNAVAILABLE, ephemeral=True,
        )

    async def test_a_tnp_cog_with_no_data_says_it_is_unavailable(self) -> None:
        bot = mock.MagicMock()
        cog = Tnp(bot)  # never loaded: no catalog, no service
        view = self.hub(cog)
        tnp = next(item for item in view.children if item.custom_id == "d12ball:hub:tnp")
        call = interaction(user(101, "Alice"), guild=mock.MagicMock(id=GUILD))
        await tnp.callback(call)
        call.response.send_message.assert_awaited_once_with(UNAVAILABLE, ephemeral=True)
