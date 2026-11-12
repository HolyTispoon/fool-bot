"""
The advanced game on Discord (step 9 of docs/tnp-bot.md), Discord faked
as in `test_tnp_cog_turn`: the lobby's **Advanced game** setting, a
seat's cards on its panel -- the hand, a building tech attached, a tech
facility built, a trade by card -- and Tactical Command, chosen on each
seat's own panel from **My tactic card** on the battle message, nothing
of either card in the channel until both have chosen.
"""

from __future__ import annotations

import unittest

import discord

from codex_cog_fakes import find_button
from cogs.tnp_views import LobbyView
from cogs.tnp_views.battle import TacticalCommandView
from cogs.tnp_views.panel import TacticPanelView
from test_tnp_cog_battle import battle_message, click
from test_tnp_cog_turn import Turn
from tnp.components import TRADE


class AdvancedTurn(Turn):
    async def started(self):
        await self.cog.create_game.callback(self.cog, self.interaction(self.blue, self.hub), False)
        game = self.game
        lobby = LobbyView(self.cog, game.game_id)
        green = next(item for item in lobby.children if ":seat_green:" in item.custom_id)
        await green.callback(self.interaction(self.green))
        setting = next(item for item in lobby.children if ":advanced:" in item.custom_id)
        call = self.interaction(self.blue)
        await setting.callback(call)
        self.lobby_call = call
        start = next(item for item in LobbyView(self.cog, game.game_id).children if ":start:" in item.custom_id)
        await start.callback(self.interaction(self.blue))
        return game


class TnpAdvancedCogTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.turn = AdvancedTurn()
        await self.turn.load()
        await self.turn.started()

    async def asyncTearDown(self) -> None:
        self.turn.close()

    def give(self, seat: str, **cards: int) -> None:
        turn = self.turn
        match = turn.match()
        match.seat(seat).hand = dict(cards)
        turn.cog.service.persist(turn.game, match)

    async def test_the_lobby_chooses_the_advanced_game(self) -> None:
        turn = self.turn
        self.assertTrue(turn.game.advanced)
        edited = [kwargs for kind, _, kwargs in turn.lobby_call.answers if kind == "response.edit"][-1]
        self.assertIn("the advanced game, with the technology cards", edited["content"])
        chosen = {item.label: item.style for item in edited["view"].children}
        self.assertEqual(chosen["Advanced game"], discord.ButtonStyle.success)
        self.assertEqual(chosen["Basic game"], discord.ButtonStyle.secondary)
        match = turn.match()
        self.assertTrue(match.advanced)
        self.assertEqual(sum(len(cards) for cards in match.decks.values()), 102)

    async def test_the_panel_puts_cards_into_play_and_says_nothing_in_public(self) -> None:
        turn = self.turn
        self.give("blue", grenades=1, jeweler=1)
        mark = len(turn.channel.requests)
        view, call = await turn.my_board("blue")
        self.assertIn("Your building techs: 1 Grenades.", call.text())
        view, _ = await turn.click(view, ("step", "techs"))
        view, _ = await turn.click(view, ("attach", "grenades", "barracks"))
        view, call = await turn.click(view, ("tech", "jeweler", 0))
        plan = turn.match().seat("blue").plan
        self.assertEqual(plan["techs"]["attach"], {"barracks": "grenades"})
        self.assertEqual(plan["techs"]["build"], ["jeweler"])
        await turn.lock(view)
        public = turn.public(mark)
        self.assertNotIn("Grenades", public)
        self.assertNotIn("Jeweler", public)
        view, _ = await turn.my_board("green")
        await turn.lock(view)
        blue = turn.match().seat("blue")
        self.assertEqual((blue.tech, blue.attached), (["jeweler"], {"barracks": "grenades"}))
        self.assertNotIn("Grenades", turn.public(mark))

    async def test_a_trade_names_cards(self) -> None:
        turn = self.turn
        match = turn.match()
        match.seat("blue").hand = {"jeweler": 2}
        match.phase = TRADE
        turn.cog.service.persist(turn.game, match)
        view, call = await turn.my_board("blue")
        view, _ = await turn.click(view, ("kind", "jeweler"))
        view, _ = await turn.click(view, ("materials", "All"))
        self.assertEqual(turn.match().seat("blue").plan["materials"], {"jeweler": 2})
        await turn.press(view, "Lock in")
        self.assertEqual(turn.match().seat("blue").pool["materials"], 5 + 4)

    async def test_tactical_command_is_chosen_in_secret_and_revealed_together(self) -> None:
        turn = self.turn
        match = turn.match()
        match.areas["14"].controller = "green"
        match.pile("14", "green").add({"mercenary": 2})
        match.seat("green").available["mercenary"] -= 2
        match.seat("blue").hand = {"enhancing_drugs": 1}
        match.seat("green").hand = {"arm_workers": 1}
        turn.cog.service.persist(turn.game, match)
        view, _ = await turn.my_board("blue")
        view, _ = await turn.deploy(view, "A", {"mercenary": 3}, target="14")
        await turn.lock(view)
        view, _ = await turn.my_board("green")
        await turn.lock(view)
        battle_view = turn.channel.views[battle_message(turn)]
        self.assertIsInstance(battle_view, TacticalCommandView)
        mark = len(turn.channel.requests)
        call = await click(turn, battle_view, find_button(battle_view, "My tactic card"), who=turn.blue)
        panel = call.view()
        self.assertIsInstance(panel, TacticPanelView)
        self.assertEqual(
            [item.choice for item in panel.children if getattr(item, "choice", ())[:1] == ("play",)],
            [("play", "enhancing_drugs")],
        )
        await turn.click(panel, ("play", "enhancing_drugs"))
        self.assertNotIn("Enhancing", turn.public(mark))
        self.assertIn("has chosen", turn.public(mark))
        call = await click(turn, battle_view, find_button(battle_view, "My tactic card"), who=turn.green)
        await turn.press(call.view(), "Play none")
        public = turn.public(mark)
        self.assertIn("plays Enhancing drugs", public)
        self.assertIn("plays no tactic card", public)
        self.assertEqual(turn.match().seat("blue").hand, {})


if __name__ == "__main__":
    unittest.main()
