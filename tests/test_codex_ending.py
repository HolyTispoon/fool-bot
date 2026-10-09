"""
A Codex game's end (docs/codex-bot.md, step 8; docs/design/codex.md,
"The end of a game"): the concession in the model and through the
service, the finished record, the rematch's record and its Keep heroes
-- and on Discord, with the fakes of `tests/codex_cog_fakes.py`:
**Concede** behind its second click, `/codex abandon`, **Rematch**, the
channel moved to Codex Archive, `/codex admin reset_channels`, the
startup sweep, and nothing hidden in the log line a click's error
writes.
"""

from __future__ import annotations

import json
import logging
import unittest
from unittest import mock

import discord

from codex.components import MatchState
from codex.engine import RulesEngine
from codex.flow import turn
from codex.game import CodexGame, GameStatus, RuleRefusal
from codex.prompts import PromptKind, pending_prompt
from codex_cog_fakes import Table, find_button, user
from cogs.codex_helpers import CODEX_ARCHIVE_CATEGORY_NAME
from cogs.codex_views import (
    ConcedeConfirmView,
    LobbyView,
    RematchView,
    TurnMessageView,
)
from gamesaves.codex.service import GameService


def started(test_game: bool = False) -> tuple[RulesEngine, CodexGame, GameService]:
    engine = RulesEngine(seed=3)
    game = CodexGame("g1", 1, guild_id=1, channel_id=20, test_game=test_game)
    games = {game.game_id: game}
    service = GameService(engine, games, save=lambda games: None)
    game.take_seat(101, "basher", "bashing")
    game.take_seat(101 if test_game else 202, "basher" if test_game else "fencer", "finesse")
    service.start(game.game_id)
    return engine, game, service


class ConcedeModelTests(unittest.TestCase):
    def test_a_concession_ends_the_game_for_the_other_seat(self) -> None:
        engine, game, service = started()
        match = service.load(game)
        result = turn.concede(engine, game, match, 2)
        self.assertEqual((match.winner, match.conceded), (1, 2))
        self.assertEqual(result.narration, ["**{player:2} concedes. {player:1} wins!**"])
        self.assertIs(result.next.kind, PromptKind.GAME_OVER)
        self.assertEqual(result.next.ask, "{player:1} wins: {player:2} conceded.")
        self.assertEqual(result.next.options.conceded, 2)
        self.assertEqual(match.events[-1]["kind"], "conceded")

    def test_either_seat_may_concede_whoever_is_active(self) -> None:
        engine, game, service = started()
        match = service.load(game)
        waiting = 2 if match.active == 1 else 1
        turn.concede(engine, game, match, waiting)
        self.assertEqual(match.winner, match.active)

    def test_a_finished_game_cannot_be_conceded(self) -> None:
        engine, game, service = started()
        match = service.load(game)
        turn.concede(engine, game, match, 1)
        with self.assertRaises(RuleRefusal):
            turn.concede(engine, game, match, 2)

    def test_the_concession_is_saved_and_old_saves_read_none(self) -> None:
        engine, game, service = started()
        match = service.load(game)
        turn.concede(engine, game, match, 1)
        again = MatchState.from_dict(match.to_dict())
        again.validate(engine.catalog)
        self.assertEqual(again.conceded, 1)
        older = match.to_dict()
        del older["conceded"]
        self.assertIsNone(MatchState.from_dict(older).conceded)

    def test_a_destroyed_base_says_so(self) -> None:
        engine, game, service = started()
        match = service.load(game)
        turn.damage_base(match, 2, 20, turn.StepResult())
        prompt = pending_prompt(engine, game, match)
        self.assertEqual(prompt.ask, "{player:1} wins: the opposing base is destroyed.")
        self.assertIsNone(prompt.options.conceded)


class ServiceEndingTests(unittest.TestCase):
    def test_concede_saves_the_match_and_finishes_the_record(self) -> None:
        engine, game, service = started()
        result = service.concede(game.game_id, 1)
        self.assertIs(game.status, GameStatus.FINISHED)
        self.assertEqual(service.load(game).winner, 2)
        self.assertIs(result.prompt.kind, PromptKind.GAME_OVER)
        self.assertIn("{player:1} concedes. {player:2} wins!", result.lines[0])

    def test_a_destroyed_base_finishes_the_record_too(self) -> None:
        engine, game, service = started()
        match = service.load(game)
        turn.damage_base(match, 1, 20, turn.StepResult())
        service.persist(game, match)
        self.assertIs(game.status, GameStatus.FINISHED)

    def test_a_finished_game_is_neither_abandoned_nor_conceded(self) -> None:
        engine, game, service = started()
        service.concede(game.game_id, 1)
        with self.assertRaises(RuleRefusal):
            service.abandon(game.game_id)
        with self.assertRaises(RuleRefusal):
            service.concede(game.game_id, 2)

    def test_the_rematch_is_the_same_seats_with_the_heroes_swapped(self) -> None:
        engine, game, service = started()
        service.concede(game.game_id, 1)
        rematch = service.rematch(game.game_id)
        self.assertIs(rematch.status, GameStatus.LOBBY)
        self.assertEqual(rematch.game_number, 2)
        self.assertEqual(rematch.channel_id, game.channel_id)
        self.assertEqual((rematch.player_1_id, rematch.player_2_id), (101, 202))
        self.assertEqual(rematch.player_specs, {1: "finesse", 2: "bashing"})
        self.assertEqual(rematch.rematch_of, game.game_id)
        self.assertIs(service.rematch(game.game_id), rematch, "a second press finds it")
        self.assertTrue(rematch.may_start())

    def test_keep_heroes_needs_both_players(self) -> None:
        engine, game, service = started()
        service.concede(game.game_id, 1)
        rematch = service.rematch(game.game_id)
        service.keep_heroes(rematch.game_id, 101)
        self.assertEqual(rematch.player_specs, {1: "finesse", 2: "bashing"})
        service.keep_heroes(rematch.game_id, 202)
        self.assertEqual(rematch.player_specs, {1: "bashing", 2: "finesse"})
        service.keep_heroes(rematch.game_id, 101)
        self.assertEqual(rematch.player_specs, {1: "finesse", 2: "bashing"}, "pressed again, taken back")
        with self.assertRaises(RuleRefusal):
            service.keep_heroes(rematch.game_id, 999)

    def test_a_test_games_one_person_keeps_both(self) -> None:
        engine, game, service = started(test_game=True)
        service.concede(game.game_id, 1)
        rematch = service.rematch(game.game_id)
        self.assertTrue(rematch.test_game)
        service.keep_heroes(rematch.game_id, 101)
        self.assertEqual(rematch.player_specs, {1: "bashing", 2: "finesse"})

    def test_the_first_player_is_drawn_again(self) -> None:
        """Who goes first is the engine's draw at every Start, a rematch's
        included (UMR p. 3)."""
        firsts = set()
        for seed in range(12):
            engine, game, service = started()
            service.concede(game.game_id, 1)
            rematch = service.rematch(game.game_id)
            service.engine.rng.seed(seed)
            service.start(rematch.game_id)
            firsts.add(service.load(rematch).first)
        self.assertEqual(firsts, {1, 2})

    def test_only_a_finished_game_is_played_again(self) -> None:
        engine, game, service = started()
        with self.assertRaises(RuleRefusal):
            service.rematch(game.game_id)
        service.abandon(game.game_id)
        with self.assertRaises(RuleRefusal):
            service.rematch(game.game_id)

    def test_the_rematch_record_round_trips(self) -> None:
        engine, game, service = started()
        service.concede(game.game_id, 1)
        rematch = service.rematch(game.game_id)
        service.keep_heroes(rematch.game_id, 101)
        again = CodexGame.from_dict(json.loads(json.dumps(rematch.to_dict())))
        self.assertEqual(again, rematch)
        older = game.to_dict()
        for key in ("final_message_id", "rematch_game_id", "rematch_of", "rematch_specs", "kept_heroes"):
            older.pop(key)
        self.assertEqual(CodexGame.from_dict(older).rematch_specs, {})


class EndingCogTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.table = Table()
        self.addCleanup(self.table.close)
        self.game = await self.table.started()

    async def concede_click(self, who):
        call = await self.table.turn_button("concede", who)
        return call, call.view()

    async def test_concede_asks_a_second_click_and_spends_nothing_public(self) -> None:
        mark = len(self.table.game_channel.requests)
        call, view = await self.concede_click(self.table.waiting)
        self.assertIsInstance(view, ConcedeConfirmView)
        self.assertTrue(call.last()[2]["ephemeral"])
        self.assertEqual(self.table.game_channel.since(mark), [])
        self.assertIsNone(self.table.match.winner)

    async def test_the_second_click_ends_the_game_and_archives_the_channel(self) -> None:
        loser = self.table.waiting
        seat = self.game.seat_of(loser.id)
        _, view = await self.concede_click(loser)
        mark = len(self.table.game_channel.requests)
        confirm = await self.table.press(view, "Concede the game", who=loser)
        self.assertEqual(confirm.last()[2]["content"], "You conceded.")
        match = self.table.match
        self.assertEqual((match.winner, match.conceded), (2 if seat == 1 else 1, seat))
        self.assertIs(self.game.status, GameStatus.FINISHED)
        requests = self.table.game_channel.since(mark)
        self.assertEqual([kind for kind, _, _ in requests], ["edit", "send", "channel.edit"])
        self.assertIsNone(requests[0][2]["view"], "the turn message stands without its buttons")
        self.assertIn("conceded", requests[1][2]["content"])
        self.assertIsInstance(requests[1][2]["view"], RematchView)
        self.table.guild.create_category.assert_awaited_with(
            name=CODEX_ARCHIVE_CATEGORY_NAME, reason=mock.ANY,
        )

    async def test_cancel_goes_on(self) -> None:
        _, view = await self.concede_click(self.table.active)
        call = await self.table.press(view, "Cancel", who=self.table.active)
        self.assertIn("goes on", call.last()[2]["content"])
        self.assertIsNone(self.table.match.winner)

    async def test_only_a_player_concedes_and_only_their_own_side(self) -> None:
        helper = user(303, "helper", helper=True)
        call, view = await self.concede_click(helper)
        self.assertIsNone(view)
        self.assertIn("own side", call.text())
        # The confirmation is its asker's, whoever else sees it.
        _, view = await self.concede_click(self.table.active)
        call = await self.table.press(view, "Concede the game", who=self.table.waiting)
        self.assertIn("Only the player conceding", call.text())
        self.assertIsNone(self.table.match.winner)

    async def test_the_slash_command_asks_the_same(self) -> None:
        call = self.table.interaction(self.table.basher)
        await self.table.cog.concede_command.callback(self.table.cog, call)
        self.assertIsInstance(call.view(), ConcedeConfirmView)
        self.assertEqual(call.view().seat, self.game.seat_of(self.table.basher.id))

    async def finish(self):
        _, view = await self.concede_click(self.table.basher)
        await self.table.press(view, "Concede the game", who=self.table.basher)

    async def test_rematch_opens_a_lobby_in_the_same_channel(self) -> None:
        await self.finish()
        mark = len(self.table.game_channel.requests)
        rematch_view = RematchView(self.table.cog, self.game.game_id)
        call = self.table.interaction(self.table.fencer)
        await rematch_view._scheduled_task(rematch_view.children[0], call)
        self.assertIsNone(call.last("response.edit")[2]["view"], "Rematch comes off its line")
        rematch = self.table.cog.games[self.game.rematch_game_id]
        self.assertIs(rematch.status, GameStatus.LOBBY)
        self.assertEqual(rematch.game_number, 2)
        requests = self.table.game_channel.since(mark)
        self.assertEqual([kind for kind, _, _ in requests], ["channel.edit", "send"])
        lobby = requests[1][2]
        self.assertIsInstance(lobby["view"], LobbyView)
        self.assertEqual(rematch.message_id, requests[1][1])
        self.assertIn("swapped", lobby["content"])
        find_button(lobby["view"], "Keep heroes")
        # A second press finds it, and posts nothing.
        mark = len(self.table.game_channel.requests)
        again = self.table.interaction(self.table.basher)
        await rematch_view._scheduled_task(rematch_view.children[0], again)
        self.assertIn("already open", again.text())
        self.assertEqual(self.table.game_channel.since(mark), [])

    async def test_keep_heroes_and_start_the_rematch(self) -> None:
        await self.finish()
        played = dict(self.game.player_specs)
        rematch_view = RematchView(self.table.cog, self.game.game_id)
        await rematch_view._scheduled_task(rematch_view.children[0], self.table.interaction(self.table.basher))
        rematch = self.table.cog.games[self.game.rematch_game_id]
        lobby = LobbyView(self.table.cog, rematch.game_id)
        for who in (self.table.basher, self.table.fencer):
            click = self.table.interaction(who)
            await next(item for item in lobby.children if ":keep:" in item.custom_id).callback(click)
        self.assertIn("keep their heroes", click.last()[2]["content"])
        self.assertEqual(rematch.player_specs, played)
        start = self.table.interaction(self.table.basher)
        await next(item for item in lobby.children if ":start:" in item.custom_id).callback(start)
        self.assertIs(rematch.status, GameStatus.PLAYING)
        self.assertIs(self.table.cog.game_for_channel(self.table.game_channel.id), rematch)

    async def test_abandon_is_a_players_own_or_a_helpers(self) -> None:
        stranger = user(404, "stranger")
        call = self.table.interaction(stranger)
        await self.table.cog.abandon_command.callback(self.table.cog, call)
        self.assertIn("Only this game's players", call.text())
        self.assertIs(self.game.status, GameStatus.PLAYING)

    async def test_a_player_abandons_their_own_game(self) -> None:
        mark = len(self.table.game_channel.requests)
        call = self.table.interaction(self.table.fencer)
        await self.table.cog.abandon_command.callback(self.table.cog, call)
        self.assertIs(self.game.status, GameStatus.ABANDONED)
        self.assertIsNone(self.table.match.winner)
        requests = self.table.game_channel.since(mark)
        self.assertEqual([kind for kind, _, _ in requests], ["edit", "send", "channel.edit"])
        self.assertIn("abandoned** by fencer", requests[1][2]["content"])

    async def test_abandon_ends_the_game_with_no_winner(self) -> None:
        helper = user(303, "helper", helper=True)
        mark = len(self.table.game_channel.requests)
        call = self.table.interaction(helper)
        await self.table.cog.abandon_command.callback(self.table.cog, call)
        self.assertIs(self.game.status, GameStatus.ABANDONED)
        self.assertIsNone(self.table.match.winner)
        requests = self.table.game_channel.since(mark)
        self.assertEqual([kind for kind, _, _ in requests], ["edit", "send", "channel.edit"])
        self.assertIsNone(requests[0][2]["view"])
        self.assertIn("abandoned", requests[1][2]["content"])
        self.assertIsNone(requests[1][2].get("view"), "an abandoned game offers no rematch")

    async def test_abandon_closes_a_lobby(self) -> None:
        await self.finish()
        await RematchView(self.table.cog, self.game.game_id).children[0].callback(
            self.table.interaction(self.table.basher),
        )
        rematch = self.table.cog.games[self.game.rematch_game_id]
        call = self.table.interaction(user(303, "helper", helper=True))
        await self.table.cog.abandon_command.callback(self.table.cog, call)
        self.assertIs(rematch.status, GameStatus.ABANDONED)

    async def test_the_startup_sweep(self) -> None:
        """The current turn message's buttons for a game still playing;
        a finished game's Rematch while none is open; nothing for an
        abandoned game."""
        await self.finish()
        self.table.bot.add_view.reset_mock()
        self.table.restart()
        armed = [(type(call.args[0]), call.kwargs["message_id"])
                 for call in self.table.bot.add_view.call_args_list]
        self.assertEqual(armed, [(RematchView, self.game.final_message_id)])
        self.table.cog.service.rematch(self.game.game_id).message_id = 999
        self.table.bot.add_view.reset_mock()
        self.table.restart()
        self.assertEqual(
            [type(call.args[0]) for call in self.table.bot.add_view.call_args_list], [LobbyView],
        )

    async def test_a_playing_games_turn_message_carries_concede(self) -> None:
        view = TurnMessageView(self.table.cog, self.game.game_id)
        find_button(view, "Concede")


class ResetChannelsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.table = Table()
        self.addCleanup(self.table.close)
        self.game = await self.table.started()

    def channel(self, channel_id: int, name: str, category: str | None):
        channel = mock.MagicMock(spec=discord.TextChannel)
        channel.id, channel.name = channel_id, name
        channel.category = None if category is None else mock.MagicMock()
        if category is not None:
            channel.category.name = category
        channel.delete = mock.AsyncMock()
        return channel

    async def test_every_codex_channel_not_archived_goes_with_its_game(self) -> None:
        cog = self.table.cog
        archived = CodexGame("old", 7, guild_id=self.table.guild.id, channel_id=30)
        cog.games[archived.game_id] = archived
        live = self.channel(self.table.game_channel.id, "codex-1-basher-vs-fencer", "Codex Games")
        kept = self.channel(30, "codex-7-a-vs-b", CODEX_ARCHIVE_CATEGORY_NAME)
        other = self.channel(40, "general", None)
        self.table.guild.fetch_channels = mock.AsyncMock(return_value=[live, kept, other])
        helper = user(303, "helper", helper=True)
        call = self.table.interaction(helper)
        await cog.reset_channels.callback(cog, call, "confirm")
        live.delete.assert_awaited()
        kept.delete.assert_not_awaited()
        other.delete.assert_not_awaited()
        self.assertEqual(set(cog.games), {"old"})
        self.assertIn("next Codex game will be number 8", call.text())

    async def test_the_word_and_the_gate(self) -> None:
        cog = self.table.cog
        call = self.table.interaction(self.table.basher)
        await cog.reset_channels.callback(cog, call, "confirm")
        self.assertIn("Manage Channels", call.text())
        call = self.table.interaction(user(303, "helper", helper=True))
        await cog.reset_channels.callback(cog, call, "yes")
        self.assertIn("cancelled", call.text())
        self.assertIn(self.game.game_id, cog.games)


class NothingHiddenInTheLogTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_clicks_error_names_no_label(self) -> None:
        """A panel's button is labelled with a card in the hand; the
        error a click logs (and #logs mirrors) names the view's class,
        the item's kind and the game, never the item."""
        table = Table()
        self.addCleanup(table.close)
        await table.started()
        view = TurnMessageView(table.cog, table.game.game_id)
        item = discord.ui.Button(label="3. Secret Card (2 gold)")
        with self.assertLogs("cogs.codex_views.base", logging.ERROR) as logged:
            await view.on_error(table.interaction(table.basher), RuntimeError("boom"), item)
        self.assertNotIn("Secret Card", "\n".join(logged.output))
        self.assertIn(table.game.game_id, "\n".join(logged.output))


if __name__ == "__main__":
    unittest.main()
