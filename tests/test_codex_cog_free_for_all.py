"""
The free-for-all on Discord (docs/codex-multiplayer.md, step 4), with the
cog's Discord faked: the lobby's variant row, three people reaching the
opening position, the channel's name, the turn message of a table -- no
Concede, **Swap view** between stacked and side by side, the undos asking
the right seat -- and the end of the game, **Rematch** with the same
seats and every seat's heroes cleared.

The requests each click spends are counted as the duel's are
(`tests/test_codex_cog_turn.py`); the board itself is `test_codex_render`'s
and `scripts/render_codex_sample.py`'s to look at.
"""

from __future__ import annotations

import unittest

from codex import history
from codex.game import GameStatus
from codex.prompts import pending
from codex_cog_fakes import GAME_CHANNEL, Table, labels, user
from codex_cog_fakes import end_main_and_lock as end_turn
from cogs.codex_views import LobbyView, RematchView, TurnMessageView, UndoConfirmView, UndoView
from cogs.codex_views.turn import PREVIOUS_TURN_LABEL_TABLE


class LobbyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.table = Table()
        self.addCleanup(self.table.close)

    async def open(self):
        """`/codex create_game`, then the lobby's **Basic game**: one
        hero a seat."""
        call = self.table.interaction(self.table.basher, self.table.lobby_channel)
        await self.table.cog.lobby.callback(self.table.cog, call)
        (game,) = self.table.cog.games.values()
        await self.table.choose_mode(game, "basic")
        return game

    async def click(self, game, action: str, who):
        call = self.table.interaction(who)
        view = LobbyView(self.table.cog, game.game_id)
        await next(item for item in view.children if f":{action}:" in item.custom_id).callback(call)
        return call

    async def test_the_variant_row_changes_the_table(self) -> None:
        game = await self.open()
        view = LobbyView(self.table.cog, game.game_id)
        row = [item.label for item in view.children if item.row == 1]
        self.assertEqual(row, ["Duel", "Free-for-all", "Two-headed dragon"])
        call = await self.click(game, "variant_free_for_all", self.table.basher)
        self.assertEqual(game.variant, "free_for_all")
        text = call.last()[2]["content"]
        self.assertIn("Seat 3 (open)", text)
        self.assertIn("Seat 5 (open)", text)
        self.assertNotIn("Player 1", text)
        # Back to a duel: two seats again.
        await self.click(game, "variant_duel", self.table.basher)
        self.assertEqual((game.variant, game.seat_count), ("duel", 2))


    async def test_only_a_seated_player_changes_the_variant_once_somebody_sits(self) -> None:
        game = await self.open()
        await self.click(game, "variant_free_for_all", self.table.basher)
        picked = self.table.interaction(self.table.basher)
        await self.table.pick_heroes(LobbyView(self.table.cog, game.game_id), self.table.basher, "bashing")
        call = await self.click(game, "variant_duel", self.table.fencer)
        self.assertEqual(game.variant, "free_for_all")
        self.assertIn("Only a seated player", call.last()[1][0])
        del picked

    async def test_start_waits_for_three_complete_seats(self) -> None:
        game = await self.open()
        await self.click(game, "variant_free_for_all", self.table.basher)
        await self.table.pick_heroes(LobbyView(self.table.cog, game.game_id), self.table.basher, "bashing")
        await self.table.pick_heroes(LobbyView(self.table.cog, game.game_id), self.table.fencer, "finesse")
        call = await self.click(game, "start", self.table.fencer)
        self.assertIn("three to five players", call.last()[1][0])
        self.assertIs(game.status, GameStatus.LOBBY)

    async def test_a_click_in_the_lobby_costs_what_a_duels_does(self) -> None:
        """A seat taken edits the lobby through the click's own response
        and spends nothing from the channel's bucket, as in a duel."""
        game = await self.open()
        await self.click(game, "variant_free_for_all", self.table.basher)
        mark = len(self.table.lobby_channel.requests) + len(self.table.game_channel.requests)
        call = await self.table.pick_heroes(
            LobbyView(self.table.cog, game.game_id), self.table.basher, "bashing")
        self.assertEqual([kind for kind, _, _ in call.answers], ["response.edit"])
        self.assertEqual(
            len(self.table.lobby_channel.requests) + len(self.table.game_channel.requests), mark)

    async def test_three_people_reach_the_opening_position(self) -> None:
        game = await self.table.started_free_for_all()
        self.assertIs(game.status, GameStatus.PLAYING)
        match = self.table.match
        self.assertEqual((match.variant, len(match.players)), ("free_for_all", 3))
        self.assertEqual(next(kw for kind, _, kw in reversed(self.table.game_channel.requests) if kind == "channel.edit")["name"], "codex-1-ffa-basher-fencer-dee")
        self.assertIsNotNone(game.turn_message_id)
        self.assertEqual(game.board_layout, "side_by_side")

    async def test_five_players_open_stacked(self) -> None:
        game = await self.table.started_free_for_all(
            ("bashing", "finesse", "anarchy", "feral", "past"))
        self.assertEqual(len(self.table.match.players), 5)
        self.assertEqual(game.board_layout, "stacked")

    async def test_a_test_game_seats_one_person_on_every_seat(self) -> None:
        call = self.table.interaction(self.table.basher, self.table.lobby_channel)
        await self.table.cog.lobby.callback(self.table.cog, call, test_game=True)
        (game,) = self.table.cog.games.values()
        await self.click(game, "variant_free_for_all", self.table.basher)
        await self.click(game, "mode_standard", self.table.basher)
        for seat, color in ((1, "red"), (2, "green"), (3, "purple")):
            view = LobbyView(self.table.cog, game.game_id)
            shown = [item.label for item in view.children if item.row in (2, 3, 4)]
            self.assertTrue(all(label.startswith(f"P{seat}: ") for label in shown), shown)
            await self.click(game, f"team{seat}_{color}", self.table.basher)
        self.assertEqual(game.taken_seats(), (1, 2, 3))
        self.assertTrue(game.may_start())
        self.assertEqual(game.seats_of(self.table.basher.id), (1, 2, 3))


class PictureTests(unittest.TestCase):
    def test_a_target_over_several_seats_is_pictured_stacked(self) -> None:
        """A TARGET whose rows lie on several seats is pictured with the
        table stacked (`None`); on one seat, that seat alone."""
        from types import SimpleNamespace

        from codex.prompts import PendingPrompt, PromptKind
        from cogs.codex.turns import side_shown

        def target(*seats):
            rows = tuple(SimpleNamespace(seat=seat) for seat in seats)
            return PendingPrompt(PromptKind.TARGET, "", 1, SimpleNamespace(targets=rows))

        self.assertIsNone(side_shown(target(2, 3), (2, 3)))
        self.assertEqual(side_shown(target(3, 3), (2, 3)), 3)
        self.assertIsNone(side_shown(PendingPrompt(PromptKind.CHOOSE_DEFENDER, "", 1, None), (2, 3)))


class TurnTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.table = Table()
        self.addCleanup(self.table.close)
        self.game = await self.table.started_free_for_all()

    @property
    def active(self):
        return self.table.seated(self.table.match.active)

    async def test_the_turn_message_has_no_concede(self) -> None:
        view = TurnMessageView(self.table.cog, self.game.game_id)
        self.assertNotIn("Concede", labels(view))

    async def test_concede_says_a_free_for_all_has_none(self) -> None:
        concede = self.table.cog.concede_command.callback
        call = self.table.interaction(self.active)
        await concede(self.table.cog, call)
        text = call.last()[1][0]
        self.assertIn("no conceding", text)
        self.assertIs(self.game.status, GameStatus.PLAYING)

    async def test_swap_view_toggles_stacked_and_side_by_side(self) -> None:
        self.assertEqual(self.game.board_layout, "side_by_side")
        view = TurnMessageView(self.table.cog, self.game.game_id)
        self.assertIn("View: stacked", labels(view))
        await self.table.turn_button("swap", self.active)
        self.assertEqual(self.game.board_layout, "stacked")
        view = TurnMessageView(self.table.cog, self.game.game_id)
        self.assertIn("View: side by side", labels(view))
        await self.table.turn_button("swap", self.active)
        self.assertEqual(self.game.board_layout, "side_by_side")

    async def test_the_hand_is_the_clickers_seat(self) -> None:
        active = self.table.match.active
        other = next(seat for seat in (1, 2, 3) if seat != active)
        panel = await self.table.turn_button("hand", self.table.seated(active))
        self.assertEqual(panel.view().seat, active)
        hand = await self.table.turn_button("hand", self.table.seated(other))
        self.assertEqual([item.label for item in hand.view().children], ["My deck", "Codex"])

    async def test_the_undo_to_the_previous_turn_asks_the_seat_before(self) -> None:
        first = self.table.match.active
        await end_turn(self.table, self.table.seated(first))
        second = self.table.match.active
        self.assertNotEqual(first, second)
        # The seat after the next is a third party: only the seat whose
        # turn is unwound may agree.
        undo = (await self.table.turn_button("undo", self.table.seated(second))).view()
        self.assertIsInstance(undo, UndoView)
        self.assertIn(PREVIOUS_TURN_LABEL_TABLE, labels(undo))
        mark = len(self.table.game_channel.requests)
        asked = await self.table.press(undo, "To the start of the previous turn")
        (kind, _, kwargs), = self.table.game_channel.since(mark)
        confirm = kwargs["view"]
        self.assertIsInstance(confirm, UndoConfirmView)
        self.assertEqual(confirm.opponent, first)
        self.assertIn(f"<@{self.table.seated(first).id}>", kwargs["content"])
        self.assertIn("asked to agree", asked.last()[2].get("content", "") + str(asked.answers))
        third = next(seat for seat in (1, 2, 3) if seat not in (first, second))
        call = self.table.interaction(self.table.seated(third))
        await confirm.agree(call)
        self.assertEqual(self.table.match.turn, 2)

    async def test_once_the_next_seat_has_acted_the_refusal_names_them(self) -> None:
        first = self.table.match.active
        await end_turn(self.table, self.table.seated(first))
        second = self.table.match.active
        call = await self.table.turn_button("hand", self.table.seated(second))
        view = call.view()
        playable = [row.slug for row in view.prompt.options.playable if row.allowed]
        await self.table.press(view, ("play", playable[0]), who=self.table.seated(second))
        before = self.table.match.to_dict()
        refusal = await self.table.turn_button("undo", self.table.seated(first))
        name = self.game.seat_name(second)
        self.assertEqual(refusal.last()[1][0], f"{name} has already started their turn.")
        self.assertEqual(self.table.match.to_dict(), before)

    async def test_taking_the_end_of_my_turn_back_is_the_seat_that_ended_it(self) -> None:
        first = self.table.match.active
        await end_turn(self.table, self.table.seated(first))
        undo = (await self.table.turn_button("undo", self.table.seated(first))).view()
        self.assertEqual(
            labels(undo),
            ["Take back the end of my turn"],
        )
        self.assertEqual(self.table.cog.service.end_of_turn_owner(self.game.game_id), first)
        self.assertIsNotNone(history.end_of_turn_owner)


class EndTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.table = Table()
        self.addCleanup(self.table.close)
        self.game = await self.table.started_free_for_all()

    async def finish(self):
        """The game over: a base of the leader's falling, through the
        service, and what the cog puts up for it."""
        service, game = self.table.cog.service, self.game
        match = service.load(game)
        victim = next(seat for seat in (1, 2, 3) if seat != match.active)
        for seat, base in zip((victim, match.active), (0, 20)):
            match.set_base(seat, base)
        for seat in (1, 2, 3):
            if seat not in (victim, match.active):
                match.set_base(seat, 12)
        from codex.flow import turn
        from codex.flow.result import StepResult

        step = StepResult(board_changed=True)
        turn.base_destroyed(match, victim, step)
        step.next = pending(self.table.cog.engine, game, match)
        result = service.run(game, match, step)
        await self.table.cog.present(game, result)
        return result

    async def test_a_finished_free_for_all_offers_a_rematch_of_the_same_seats(self) -> None:
        result = await self.finish()
        self.assertIs(self.game.status, GameStatus.FINISHED)
        self.assertIn("wins", result.prompt.ask)
        self.assertIsNotNone(self.game.final_message_id)
        call = self.table.interaction(self.table.fencer)
        view = RematchView(self.table.cog, self.game.game_id)
        await next(item for item in view.children if ":rematch:" in item.custom_id).callback(call)
        (rematch,) = [g for g in self.table.cog.games.values() if g.game_id != self.game.game_id]
        self.assertEqual(rematch.variant, "free_for_all")
        self.assertEqual(rematch.taken_seats(), (1, 2, 3))
        self.assertEqual(rematch.player_specs, {})
        text = self.table.cog.lobby_text(rematch)
        self.assertIn("the same seats, each choosing heroes again", text)
        self.assertNotIn("Keep heroes", labels(LobbyView(self.table.cog, rematch.game_id)))


if __name__ == "__main__":
    unittest.main()
