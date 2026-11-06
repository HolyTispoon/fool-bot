"""
The simultaneous turn on Discord (step 6 of docs/tnp-bot.md), driven
with Discord faked (`codex_cog_fakes`' channel and interactions, every
request logged by route): two people plan Infrastructure and Deployment
on their own panels, lock in, watch March post attack spot A and then B
with the map as each left it -- a neutral territory taken by the one
ground unit a pile has, another by the unit its seat chooses, and a
harvest -- trade at Production and Trade, and reach turn 2 through
Cleanup. A restart mid-phase keeps both plans; nothing of a plan reaches
the channel before the reveal; and the requests a whole turn spends from
the channel's bucket are counted.

Saves go through `suppressed_cog_saves`; the map and the boards are
stood in for by bytes that change exactly when what they draw does.
"""

from __future__ import annotations

import hashlib
import json
import unittest
from contextlib import ExitStack
from unittest import mock

from codex_cog_fakes import FakeChannel, FakeInteraction, find_button, find_select, user
from cogs import d12ball_boards
from cogs.tnp import Tnp
from cogs.tnp import core as tnp_core
from cogs.tnp import table as tnp_table
from cogs.tnp import turns as tnp_turns
from cogs.tnp_views import ConquerPanelView, LobbyView, PlanPanelView, TableView, TradePanelView
from save_patches import suppressed_cog_saves
from tnp.game import TnpGame

GUILD, HUB_CHANNEL, GAME_CHANNEL = 1, 5, 20


def picture(catalog, brief) -> bytes:
    """A map or a board as bytes that change exactly when its brief
    does, so the gate's skip of an unchanged map counts as it would."""
    return hashlib.sha256(repr(brief).encode()).digest()


class Turn:
    """A server, the game's channel and the cog, a game started through
    the real lobby: Alice in Blue, Bob in Green."""

    def __init__(self) -> None:
        self.stack = ExitStack()
        self.stack.enter_context(suppressed_cog_saves())
        self.stack.enter_context(mock.patch.object(d12ball_boards, "BOARD_REFRESH_INTERVAL", 0))
        for module, name in ((tnp_table, "render_map"), (tnp_turns, "render_map"), (tnp_turns, "render_board")):
            self.stack.enter_context(mock.patch.object(module, name, side_effect=picture))
        self.bot = mock.MagicMock()
        self.hub = FakeChannel(HUB_CHANNEL)
        self.channel = FakeChannel(GAME_CHANNEL)
        self.bot.get_channel.side_effect = {HUB_CHANNEL: self.hub, GAME_CHANNEL: self.channel}.get
        self.guild = mock.MagicMock(id=GUILD)
        self.guild.categories = []
        self.guild.create_category = mock.AsyncMock(return_value=mock.MagicMock())
        self.guild.create_text_channel = mock.AsyncMock(return_value=self.channel)
        self.blue, self.green = user(101, "Alice"), user(202, "Bob")
        self.who = {"blue": self.blue, "green": self.green}
        self.cog = Tnp(self.bot)

    async def load(self, games=None) -> None:
        with mock.patch.object(tnp_core, "load_games", return_value=games or {}):
            await self.cog.cog_load()

    def close(self) -> None:
        self.cog.boards.shutdown()
        self.stack.close()

    @property
    def game(self) -> TnpGame:
        (game,) = self.cog.games.values()
        return game

    def match(self):
        return self.cog.service.load(self.game)

    def interaction(self, who, channel=None) -> FakeInteraction:
        return FakeInteraction(who, channel or self.channel, self.guild)

    async def started(self) -> TnpGame:
        await self.cog.create_game.callback(self.cog, self.interaction(self.blue, self.hub), False)
        game = self.game
        await LobbyView(self.cog, game.game_id).children[1].callback(self.interaction(self.green))
        start = next(item for item in LobbyView(self.cog, game.game_id).children if ":start:" in item.custom_id)
        await start.callback(self.interaction(self.blue))
        return game

    async def my_board(self, seat: str):
        """**My board**, by the seat's player: its panel's view."""
        call = self.interaction(self.who[seat])
        await TableView(self.cog, self.game.game_id).children[0].callback(call)
        return call.view(), call

    async def choose(self, view, placeholder: str, *values: str):
        select = find_select(view, placeholder)
        call = self.interaction(self.who[view.seat])
        call.data = {"custom_id": select.custom_id, "component_type": 3, "values": list(values)}
        await view._scheduled_task(select, call)
        return call.view(), call

    async def press(self, view, label: str):
        item = find_button(view, label)
        call = self.interaction(self.who[view.seat])
        call.data = {"custom_id": item.custom_id, "component_type": 2}
        await view._scheduled_task(item, call)
        return call.view(), call

    def public(self, since: int = 0) -> str:
        """Every text the game's channel was sent or edited to since a mark."""
        return "\n".join(
            str(kwargs.get("content")) for kind, _, kwargs in self.channel.requests[since:]
            if kind in ("send", "edit") and kwargs.get("content")
        )


async def plan_blue(turn: Turn):
    """Blue: two Workers built; attack A at area 14 with three Workers
    and a Mercenary, two kinds of ground unit, so March asks which is
    revealed; attack B at area 13 with a Mercenary."""
    view, _ = await turn.my_board("blue")
    view, _ = await turn.choose(view, "How many Worker to build", "2")
    view, _ = await turn.choose(view, "What to change", "attack:A")
    view, _ = await turn.choose(view, "Attack A's target", "14")
    view, _ = await turn.choose(view, "How many Worker in attack A", "3")
    view, _ = await turn.choose(view, "Unit for attack A", "mercenary")
    view, _ = await turn.choose(view, "How many Mercenary in attack A", "1")
    view, _ = await turn.choose(view, "What to change", "attack:B")
    view, _ = await turn.choose(view, "Attack B's target", "13")
    view, _ = await turn.choose(view, "Unit for attack B", "mercenary")
    view, call = await turn.choose(view, "How many Mercenary in attack B", "1")
    return view, call


async def plan_green(turn: Turn):
    """Green: attack A at area 15 with its three Workers, taken and
    harvested at once; its three Mercenaries defending its base."""
    view, _ = await turn.my_board("green")
    view, _ = await turn.choose(view, "What to change", "attack:A")
    view, _ = await turn.choose(view, "Attack A's target", "15")
    view, _ = await turn.choose(view, "How many Worker in attack A", "3")
    view, _ = await turn.choose(view, "What to change", "defense:green_base")
    view, _ = await turn.choose(view, "Unit to defend", "mercenary")
    view, call = await turn.choose(view, "How many Mercenary defend", "3")
    return view, call


class TnpTurnTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.turn = Turn()
        await self.turn.load()
        await self.turn.started()

    async def asyncTearDown(self) -> None:
        self.turn.close()

    async def test_a_plan_is_saved_click_by_click_on_the_seat_s_own_panel(self) -> None:
        turn = self.turn
        view, call = await plan_blue(turn)
        self.assertIsInstance(view, PlanPanelView)
        plan = turn.match().seat("blue").plan
        self.assertEqual(plan["build"], {"worker": 2})
        self.assertEqual(plan["attacks"]["A"], {"target": "14", "units": {"worker": 3, "mercenary": 1}})
        self.assertEqual(plan["attacks"]["B"], {"target": "13", "units": {"mercenary": 1}})
        text = call.text()
        self.assertIn("Attack A: 3 Worker, 1 Mercenary at area 14.", text)
        self.assertIn("It costs 2 materials; the pool holds 5 materials.", text)
        # Every click was answered by editing the panel in place: the
        # channel heard nothing of it.
        self.assertEqual(call.last()[0], "response.edit")
        self.assertNotIn("Worker", turn.public())

    async def test_the_model_refuses_what_the_rules_do_not_allow_and_keeps_the_plan(self) -> None:
        turn = self.turn
        view, _ = await turn.my_board("blue")
        view, _ = await turn.choose(view, "How many Worker to build", "4")
        view, _ = await turn.choose(view, "Unit to build", "mercenary")
        # Four Workers and two Mercenaries is six from a Barracks of four.
        view, call = await turn.choose(view, "How many Mercenary to build", "2")
        self.assertIn("**Not done:**", call.text())
        self.assertIn("TNP 2.4", call.text())
        self.assertEqual(turn.match().seat("blue").plan["build"], {"worker": 4})

    async def test_an_attack_needs_its_target_first(self) -> None:
        turn = self.turn
        view, _ = await turn.my_board("blue")
        view, _ = await turn.choose(view, "What to change", "attack:B")
        view, call = await turn.choose(view, "How many Worker in attack B", "1")
        self.assertIn("Choose attack B's target first.", call.text())
        self.assertIsNone(turn.match().seat("blue").plan)

    async def test_somebody_else_s_panel_answers_nobody_else(self) -> None:
        turn = self.turn
        view, _ = await turn.my_board("blue")
        select = find_select(view, "How many Worker to build")
        call = turn.interaction(turn.green)
        call.data = {"custom_id": select.custom_id, "component_type": 3, "values": ["2"]}
        await view._scheduled_task(select, call)
        self.assertIn("its seat's player's alone", call.text())
        self.assertIsNone(turn.match().seat("blue").plan)

    async def test_a_lone_lock_in_edits_the_table_and_posts_nothing(self) -> None:
        turn = self.turn
        view, _ = await plan_blue(turn)
        mark = len(turn.channel.requests)
        view, call = await turn.press(view, "Lock in")
        requests = turn.channel.since(mark)
        self.assertEqual([kind for kind, _, _ in requests], ["edit"])
        (_, message_id, kwargs) = requests[0]
        self.assertEqual(message_id, turn.game.table_message_id)
        self.assertIn("**Blue** (Alice) has locked in.", kwargs["content"])
        self.assertIn("**Green** (Bob) is planning.", kwargs["content"])
        # The map has not moved: the edit is the text alone.
        self.assertNotIn("attachments", kwargs)
        self.assertIn("You have locked in.", call.text())
        self.assertIsNone(view)
        self.assertNotIn("Worker", turn.public())

    async def test_a_whole_turn_from_infrastructure_to_cleanup(self) -> None:
        """
        The stop of step 6: Infrastructure and Deployment, March posting
        attack A then B -- area 14 taken by the unit Blue reveals and
        harvested, area 15 taken and harvested at once, area 13 taken --
        Production and Trade with both seats trading, Cleanup, and turn 2,
        through the panels alone. The requests the channel's bucket spent
        are counted.
        """
        turn = self.turn
        mark = len(turn.channel.requests)
        blue, _ = await plan_blue(turn)
        green, _ = await plan_green(turn)
        before_reveal = turn.public(mark)
        await turn.press(blue, "Lock in")
        reveal = len(turn.channel.requests)
        _, call = await turn.press(green, "Lock in")

        # March stops at area 14: Blue's pile holds two kinds of ground unit.
        sends = [one for one in turn.channel.since(reveal) if one[0] == "send"]
        self.assertEqual(len(sends), 1)
        first = sends[0][2]
        self.assertIn("Both seats have locked in.", first["content"])
        self.assertIn("reveal a ground unit from attack A to take area 14", first["content"])
        self.assertIn(f"/{turn.game.table_message_id})", first["content"])
        self.assertIsNotNone(first.get("file"))
        # The one asked is pinged, and nobody else may be.
        self.assertIn("<@101> Answer from **My board**", first["content"])
        self.assertEqual([one.id for one in first["allowed_mentions"].users], [101])

        conquer, _ = await turn.my_board("blue")
        self.assertIsInstance(conquer, ConquerPanelView)
        answered = len(turn.channel.requests)
        await turn.choose(conquer, "Ground unit to reveal", "worker")
        sends = [one[2]["content"] for one in turn.channel.since(answered) if one[0] == "send"]
        # The rest of A, then B, then March's end with Production.
        self.assertEqual(len(sends), 3)
        self.assertIn("**Blue** (Alice) reveals a Worker in attack A and takes area 14.", sends[0])
        self.assertIn("3 Worker harvest area 14: 3 blue minerals", sends[0])
        self.assertIn("**Green** (Bob) reveals a Worker in attack A and takes area 15.", sends[0])
        self.assertIn("harvest area 15: 3 blue minerals", sends[0])
        self.assertIn("attack B", sends[1])
        self.assertIn("takes area 13", sends[1])
        self.assertIn("March is over.", sends[2])
        self.assertIn("Production", sends[2])
        # Both seats are asked to trade: both pinged, on the last message alone.
        self.assertIn("<@101> <@202> Open **My board**", sends[2])
        pings = [one[2]["allowed_mentions"] for one in turn.channel.since(answered) if one[0] == "send"]
        self.assertEqual([one.id for one in pings[2].users], [101, 202])
        self.assertFalse(pings[0].users)
        match = turn.match()
        self.assertEqual(match.phase, "trade")
        self.assertEqual({area: match.controller(area) for area in ("13", "14", "15")},
                         {"13": "blue", "14": "blue", "15": "green"})

        blue_trade, _ = await turn.my_board("blue")
        self.assertIsInstance(blue_trade, TradePanelView)
        blue_trade, call = await turn.choose(blue_trade, "How many for materials", "3")
        self.assertIn("Your trade: 3 blue minerals for materials -- gaining 6 materials.", call.text())
        await turn.press(blue_trade, "Lock in")
        green_trade, _ = await turn.my_board("green")
        green_trade, _ = await turn.choose(green_trade, "How many for gold", "3")
        traded = len(turn.channel.requests)
        _, call = await turn.press(green_trade, "Lock in")
        (last,) = [one[2]["content"] for one in turn.channel.since(traded) if one[0] == "send"]
        self.assertIn("**Blue** (Alice) trades 3 blue minerals for 6 materials.", last)
        self.assertIn("**Green** (Bob) trades 3 blue minerals for 3 gold.", last)
        self.assertIn("Turn 2: Infrastructure and Deployment.", last)
        # The clicker's panel is turn 2's plan, its board drawn again.
        self.assertIsInstance(call.view(), PlanPanelView)
        self.assertEqual(call.last()[0], "original.edit")
        self.assertIn("attachments", call.last()[2])

        match = turn.match()
        self.assertEqual((match.turn, match.phase), (2, "plan"))
        self.assertEqual(match.seat("blue").pool["materials"], 5 - 2 + 6)
        self.assertEqual(match.seat("green").pool["gold"], 3)
        self.assertEqual(match.seat("blue").available.get("worker"), 3 + 2)

        # Nothing of either plan was in public before the reveal.
        for word in ("Worker", "Mercenary", "area 13", "area 14", "area 15"):
            self.assertNotIn(word, before_reveal)

        # The whole turn's spend from the channel's bucket: every send
        # and every edit through the channel, from the first plan click
        # to turn 2.
        kinds = [kind for kind, _, _ in turn.channel.since(mark)]
        self.assertEqual(kinds.count("send"), 5)
        self.assertEqual(kinds.count("edit"), 5)
        self.assertEqual(len(kinds), 10)

    async def test_a_battle_met_in_march_is_named_and_the_game_waits(self) -> None:
        """Blue attacks area 14, which Green holds: a battle (TNP 5.6),
        which step 7 fights."""
        turn = self.turn
        match = turn.match()
        match.areas["14"].controller = "green"
        match.pile("14", "green").add({"mercenary": 2})
        match.seat("green").available["mercenary"] -= 2
        turn.cog.service.persist(turn.game, match)
        view, _ = await turn.my_board("blue")
        view, _ = await turn.choose(view, "What to change", "attack:A")
        view, _ = await turn.choose(view, "Attack A's target", "14")
        view, _ = await turn.choose(view, "Unit for attack A", "mercenary")
        view, _ = await turn.choose(view, "How many Mercenary in attack A", "3")
        await turn.press(view, "Lock in")
        view, _ = await turn.my_board("green")
        await turn.press(view, "Lock in")
        said = turn.public()
        self.assertIn("arrive in step 7", said)
        self.assertIsNotNone(turn.match().battle)
        view, call = await turn.my_board("blue")
        self.assertIn("arrive in step 7", call.answers[-1][1][0])


class TnpTurnRestartTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_restart_mid_phase_keeps_both_plans(self) -> None:
        turn = Turn()
        try:
            await turn.load()
            await turn.started()
            await plan_blue(turn)
            await plan_green(turn)
            saved = {
                game_id: TnpGame.from_dict(json.loads(json.dumps(game.to_dict())))
                for game_id, game in turn.cog.games.items()
            }
            turn.cog.boards.shutdown()
            turn.cog = Tnp(turn.bot)
            await turn.load(saved)
            blue, call = await turn.my_board("blue")
            self.assertIn("Attack A: 3 Worker, 1 Mercenary at area 14.", call.answers[-1][1][0])
            self.assertIsInstance(blue, PlanPanelView)
            green, call = await turn.my_board("green")
            self.assertIn("Defend Green base: 3 Mercenary.", call.answers[-1][1][0])
            # And the plans lock in as saved.
            await turn.press(blue, "Lock in")
            await turn.press(green, "Lock in")
            self.assertEqual(turn.match().phase, "march")
        finally:
            turn.close()


if __name__ == "__main__":
    unittest.main()
