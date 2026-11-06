"""
The end of a TNP game on Discord (step 8 of docs/tnp-bot.md), driven
with Discord faked as `test_tnp_cog_turn` drives it: a concession behind
its second click, a base that falls in battle, the table standing as the
final message with **Rematch**, the channel moved to TNP Archive,
`/tnp abandon` by a player and refused to a watcher, the rematch's lobby
in the same channel, and the startup sweep re-arming **Rematch**.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from codex_cog_fakes import find_button, user
from cogs.tnp import Tnp
from cogs.tnp import core as tnp_core
from cogs.tnp_views import ConcedeConfirmView, LobbyView, RematchView, TableView
from test_tnp_cog_battle import answer_first, current_view, dice
from test_tnp_cog_turn import Turn
from tnp.game import GameStatus, TnpGame


def archived(turn: Turn) -> bool:
    """Whether the game's channel was moved -- to TNP Archive."""
    return any(kind == "channel.edit" and "category" in kwargs for kind, _, kwargs in turn.channel.requests)


async def press(view, label: str, call):
    item = find_button(view, label)
    call.data = {"custom_id": item.custom_id or "x", "component_type": 2}
    await view._scheduled_task(item, call)
    return call


class TnpEndingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.turn = Turn()
        self.turn.channel.guild = self.turn.guild
        self.archive = SimpleNamespace(id=900, name="TNP Archive")
        self.turn.guild.create_category = mock.AsyncMock(return_value=self.archive)
        await self.turn.load()
        await self.turn.started()

    async def asyncTearDown(self) -> None:
        self.turn.close()

    async def concede(self, who, seat_label: str):
        turn = self.turn
        call = turn.interaction(who)
        await turn.cog.concede.callback(turn.cog, call)
        view = call.view()
        self.assertIsInstance(view, ConcedeConfirmView)
        second = turn.interaction(who)
        await press(view, seat_label, second)
        return second

    def table_edits(self):
        table = self.turn.game.table_message_id
        return [kwargs for kind, one, kwargs in self.turn.channel.requests if kind == "edit" and one == table]

    async def test_a_concession_ends_the_game_with_rematch_on_the_table(self) -> None:
        turn = self.turn
        mark = len(turn.channel.requests)
        second = await self.concede(turn.blue, "Concede as Blue")
        self.assertIn("You conceded", second.text())
        game = turn.game
        self.assertIs(game.status, GameStatus.FINISHED)
        match = turn.match()
        self.assertEqual((match.winner, match.won_by), ("green", "concession"))
        said = turn.public(mark)
        # Announced once.
        self.assertEqual(1, said.count("**Blue** (Alice) concedes. **Green** (Bob) wins the game."))
        final = self.table_edits()[-1]
        self.assertIsInstance(final["view"], RematchView)
        self.assertIn("has won: the other seat conceded", final["content"])
        self.assertEqual("tnp-map.png", final["attachments"][0].filename)
        self.assertTrue(archived(turn))
        # The end costs the channel's bucket the line and the table's edit;
        # the move is the channel's own route.
        spent = [row for row in turn.channel.requests[mark:] if row[0] in ("send", "edit")]
        self.assertEqual(2, len(spent))

    async def test_cancel_concedes_nothing_and_a_watcher_cannot_concede(self) -> None:
        turn = self.turn
        call = turn.interaction(turn.blue)
        await turn.cog.concede.callback(turn.cog, call)
        await press(call.view(), "Cancel", turn.interaction(turn.blue))
        self.assertIs(turn.game.status, GameStatus.PLAYING)
        watcher = turn.interaction(user(303, "Carol"))
        await turn.cog.concede.callback(turn.cog, watcher)
        self.assertIn("Only a player", watcher.text())

    async def test_a_base_that_falls_in_battle_wins_and_closes_the_battle(self) -> None:
        """Blue holds the road to Green's base and attacks it with its
        Mercenaries; Green deployed nobody there, so once its emergency
        defense is declined nobody defends it and it falls (TNP 1.3,
        6.1)."""
        turn = self.turn
        match = turn.match()
        for area in ("10", "2", "1", "3", "11"):
            match.areas[area].controller = "blue"
        turn.cog.service.persist(turn.game, match)
        view, _ = await turn.my_board("blue")
        view, _ = await turn.choose(view, "What to change", "attack:A")
        view, _ = await turn.choose(view, "Attack A's target", "green_base")
        view, _ = await turn.choose(view, "Unit for attack A", "mercenary")
        view, _ = await turn.choose(view, "How many Mercenary in attack A", "3")
        await turn.press(view, "Lock in")
        view, _ = await turn.my_board("green")
        await turn.press(view, "Lock in")
        call = None
        with dice(turn, 7):
            for _ in range(100):
                if turn.match().winner is not None:
                    break
                call = await answer_first(turn, current_view(turn, call))
        match = turn.match()
        self.assertEqual((match.winner, match.won_by), ("blue", "base"))
        self.assertIs(turn.game.status, GameStatus.FINISHED)
        self.assertIn("wins the game: Green base has fallen", turn.public())
        self.assertIsInstance(self.table_edits()[-1]["view"], RematchView)
        self.assertIsNone(turn.game.battle_post)
        self.assertTrue(archived(turn))

    async def test_rematch_opens_a_lobby_with_the_same_seats_once(self) -> None:
        turn = self.turn
        await self.concede(turn.blue, "Concede as Blue")
        finished = turn.game
        rematch_view = RematchView(turn.cog, finished.game_id)
        first = turn.interaction(turn.green)
        await press(rematch_view, "Rematch", first)
        rematch = turn.cog.games[finished.game_id].rematch_game_id
        lobby = turn.cog.games[rematch]
        self.assertIs(lobby.status, GameStatus.LOBBY)
        self.assertEqual(lobby.seats, finished.seats)
        self.assertEqual(lobby.channel_id, finished.channel_id)
        self.assertEqual(lobby.rematch_of, finished.game_id)
        sent = turn.channel.requests[-1]
        self.assertEqual("send", sent[0])
        self.assertIsInstance(sent[2]["view"], LobbyView)
        # Rematch came off the table in the click's own response.
        self.assertIsNone(first.last("response.edit")[2]["view"])
        second = turn.interaction(turn.blue)
        await press(rematch_view, "Rematch", second)
        self.assertIn("already open", second.text())
        self.assertEqual(2, len(turn.cog.games))

    async def test_abandon_by_a_player_and_not_by_a_watcher(self) -> None:
        turn = self.turn
        watcher = turn.interaction(user(303, "Carol"))
        await turn.cog.abandon.callback(turn.cog, watcher)
        self.assertIn("Only this game's players", watcher.text())
        self.assertIs(turn.game.status, GameStatus.PLAYING)
        mark = len(turn.channel.requests)
        call = turn.interaction(turn.green)
        await turn.cog.abandon.callback(turn.cog, call)
        self.assertIs(turn.game.status, GameStatus.ABANDONED)
        self.assertIn("was abandoned** by Bob", turn.public(mark))
        self.assertIsNone(self.table_edits()[-1]["view"])
        self.assertTrue(archived(turn))
        # An abandoned game offers no rematch.
        rematch = turn.interaction(turn.blue)
        await press(RematchView(turn.cog, turn.game.game_id), "Rematch", rematch)
        self.assertIn("Only a finished game", rematch.text())

    async def test_a_helper_may_abandon_a_lobby(self) -> None:
        turn = Turn()
        try:
            await turn.load()
            await turn.cog.create_game.callback(turn.cog, turn.interaction(turn.blue, turn.hub), False)
            helper = turn.interaction(user(404, "Dana", helper=True))
            await turn.cog.abandon.callback(turn.cog, helper)
            self.assertIs(turn.game.status, GameStatus.ABANDONED)
            lobby = [kwargs for kind, one, kwargs in turn.channel.requests
                     if kind == "edit" and one == turn.game.message_id]
            self.assertIsNone(lobby[-1]["view"])
        finally:
            turn.close()


class TnpEndingRestartTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_startup_sweep_re_arms_rematch_until_one_is_opened(self) -> None:
        turn = Turn()
        try:
            await turn.load()
            await turn.started()
            call = turn.interaction(turn.blue)
            await turn.cog.concede.callback(turn.cog, call)
            await press(call.view(), "Concede as Blue", turn.interaction(turn.blue))
            saved = {one: TnpGame.from_dict(game.to_dict()) for one, game in turn.cog.games.items()}
            bot = mock.MagicMock()
            again = Tnp(bot)
            with mock.patch.object(tnp_core, "load_games", return_value=saved):
                await again.cog_load()
            armed = [args[0] for args, kwargs in bot.add_view.call_args_list
                     if kwargs.get("message_id") == turn.game.table_message_id]
            self.assertEqual([RematchView], [type(view) for view in armed])
            self.assertFalse(any(isinstance(view, TableView) for view in armed))
            again.boards.shutdown()
        finally:
            turn.close()


if __name__ == "__main__":
    unittest.main()
