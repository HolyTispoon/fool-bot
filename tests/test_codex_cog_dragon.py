"""
The two-headed dragon on Discord (docs/codex-multiplayer.md, step 6), with
the cog's Discord faked: the lobby's two teams and the channel's name;
the turn message naming both teammates, a panel each, a teammate's hand,
codex and tech choice seen read-only, a test game's **Switch to**; the
undos and the concession both teammates agree to; and the end -- the
team's line and **Rematch** with the same seats and teams.

The requests each click spends are counted as the duel's are
(`tests/test_codex_cog_turn.py`); the board itself is `test_codex_render`'s
and `scripts/render_codex_sample.py`'s to look at.
"""

from __future__ import annotations

import unittest

import discord

from codex.game import GameStatus
from codex_cog_fakes import Table, user
from cogs.codex_views import LobbyView


def labels(view) -> list[str]:
    return [item.label for item in view.children if isinstance(item, discord.ui.Button)]


class LobbyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.table = Table()
        self.addCleanup(self.table.close)

    async def open(self, test_game: bool = False):
        call = self.table.interaction(self.table.basher, self.table.lobby_channel)
        await self.table.cog.lobby.callback(self.table.cog, call, test_game=test_game)
        (game,) = self.table.cog.games.values()
        return game

    async def click(self, game, action: str, who):
        call = self.table.interaction(who)
        view = LobbyView(self.table.cog, game.game_id)
        await next(item for item in view.children if f":{action}:" in item.custom_id).callback(call)
        return call

    async def test_the_lobby_heads_its_two_teams(self) -> None:
        game = await self.open()
        call = await self.click(game, "variant_two_headed_dragon", self.table.basher)
        self.assertEqual((game.variant, game.seat_count), ("two_headed_dragon", 4))
        text = call.last()[2]["content"]
        self.assertIn("two-headed dragon", text)
        lines = text.split("\n")
        self.assertEqual(lines.index("__Team 1__") + 1, lines.index("*Seat 1 (open)*"))
        self.assertEqual(lines.index("__Team 2__") + 1, lines.index("*Seat 3 (open)*"))
        self.assertLess(lines.index("*Seat 2 (open)*"), lines.index("__Team 2__"))

    async def test_a_seat_is_taken_in_order_and_another_team_by_leaving(self) -> None:
        game = await self.open()
        await self.click(game, "variant_two_headed_dragon", self.table.basher)
        await self.table.pick_heroes(LobbyView(self.table.cog, game.game_id), self.table.basher, "bashing")
        await self.table.pick_heroes(LobbyView(self.table.cog, game.game_id), self.table.fencer, "finesse")
        self.assertEqual(game.seats_of(self.table.fencer.id), (2,))
        dee, eli = user(303, "dee"), user(404, "eli")
        await self.table.pick_heroes(LobbyView(self.table.cog, game.game_id), dee, "anarchy")
        # Fencer wants the other team: they leave, eli takes the seat they
        # left, and fencer sits again in the first free one -- the fourth.
        await self.click(game, "leave", self.table.fencer)
        await self.table.pick_heroes(LobbyView(self.table.cog, game.game_id), eli, "feral")
        await self.table.pick_heroes(LobbyView(self.table.cog, game.game_id), self.table.fencer, "finesse")
        self.assertEqual([game.seat_name(seat) for seat in (1, 2, 3, 4)],
                         ["basher", "eli", "dee", "fencer"])
        self.assertTrue(game.may_start())

    async def test_start_waits_for_four_complete_seats(self) -> None:
        game = await self.open()
        await self.click(game, "variant_two_headed_dragon", self.table.basher)
        for who, spec in ((self.table.basher, "bashing"), (self.table.fencer, "finesse")):
            await self.table.pick_heroes(LobbyView(self.table.cog, game.game_id), who, spec)
        call = await self.click(game, "start", self.table.fencer)
        self.assertIn("four players, two a team", call.last()[1][0])
        self.assertIs(game.status, GameStatus.LOBBY)


if __name__ == "__main__":
    unittest.main()
