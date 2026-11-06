"""
Battles on Discord (step 7 of docs/tnp-bot.md), driven with Discord faked
(`codex_cog_fakes`' channel and interactions, every request logged by
route): Blue attacks area 14, which Green holds, and the battle is
fought on its own message round by round -- placing, the retreat
declaration and the targets asked of whichever seat the prompt names,
from its options -- every roll shown with what each die needed and why,
a round's record posted as it ends, and March going on once the battle
is over. The requests each round spends from the channel's bucket are
counted, a restart re-arms the battle's controls, and somebody else's
click on a seat's question answers nothing.

The dice are scripted (`engine.rng.randint`); the pictures are stood in
for by bytes, as in `test_tnp_cog_turn`.
"""

from __future__ import annotations

import unittest
from contextlib import contextmanager
from unittest import mock

import discord

from codex_cog_fakes import find_button, find_select
from cogs.tnp import Tnp
from cogs.tnp import core as tnp_core
from cogs.tnp_views import BattleView
from cogs.tnp_views.battle import (
    PlaceView, RepairView, RepositionView, RetreatView, RoleView, SplashView, TargetView,
    DestroyView, EmergencyView,
)
from test_tnp_cog_turn import Turn
from tnp.game import TnpGame
from tnp.prompts import PromptKind

#: Where the channel's bucket is measured against: about five requests
#: in five seconds (docs/design/rate-limits.md).
BUCKET = 5


@contextmanager
def dice(turn: Turn, *rolled: int):
    """Every d12 the next of `rolled`, the last one again once they run
    out."""
    numbers = list(rolled)

    def roll(low, high):
        return numbers.pop(0) if len(numbers) > 1 else numbers[0]

    with mock.patch.object(turn.cog.engine.rng, "randint", side_effect=roll):
        yield


async def open_battle(turn: Turn, blue: int = 3, green: int = 2):
    """Blue attacks area 14, which Green holds with `green` Mercenaries,
    with `blue` Mercenaries; both lock in, and March meets the battle."""
    match = turn.match()
    match.areas["14"].controller = "green"
    match.pile("14", "green").add({"mercenary": green})
    match.seat("green").available["mercenary"] -= green
    turn.cog.service.persist(turn.game, match)
    view, _ = await turn.my_board("blue")
    view, _ = await turn.deploy(view, "A", {"mercenary": blue}, target="14")
    await turn.lock(view)
    view, _ = await turn.my_board("green")
    await turn.lock(view)


def battle_message(turn: Turn) -> int:
    return turn.game.battle_post["id"]


async def click(turn: Turn, view: BattleView, item, who=None, values=None):
    """A click on the battle message by `who` -- the asked seat's player
    by default -- with a menu's `values`."""
    who = who or turn.who[view.prompt.asked_seat]
    call = turn.interaction(who)
    call.message = mock.MagicMock(id=battle_message(turn), attachments=[])
    if isinstance(item, discord.ui.Select):
        call.data = {"custom_id": item.custom_id, "component_type": 3, "values": list(values)}
    else:
        call.data = {"custom_id": item.custom_id, "component_type": 2}
    await view._scheduled_task(item, call)
    return call


async def answer_first(turn: Turn, view: BattleView):
    """The first legal answer to the question on the battle message, as
    a player would click it: the first slot, fight on, the first target,
    keep the flankers, no Workers, no splash, attack, produce none."""
    if isinstance(view, PlaceView):
        menu = find_select(view, "Where")
        return await click(turn, view, menu, values=[menu.options[0].value])
    if isinstance(view, TargetView):
        menu = find_select(view, "Target for")
        return await click(turn, view, menu, values=[menu.options[0].value])
    labels = {
        RetreatView: "Fight on", RepositionView: "Keep", RepairView: "Don't repair",
        SplashView: "Don't splash", RoleView: "Attack", EmergencyView: "Produce none",
    }
    if isinstance(view, DestroyView):
        menu = find_select(view, "What is destroyed")
        return await click(turn, view, menu, values=[menu.options[0].value])
    return await click(turn, view, find_button(view, labels[type(view)]))


def current_view(turn: Turn, call=None):
    """The battle message's controls: what the last click put up, or what
    the message was sent with."""
    if call is not None:
        for kind, _, kwargs in reversed(call.answers):
            if kind in ("original.edit", "response.edit") and "view" in kwargs:
                return kwargs["view"]
    return turn.channel.views[battle_message(turn)]


class TnpBattleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.turn = Turn()
        await self.turn.load()
        await self.turn.started()

    async def asyncTearDown(self) -> None:
        self.turn.close()

    async def test_a_battle_gets_its_own_message_asking_the_seat_named(self) -> None:
        turn = self.turn
        await open_battle(turn)
        post = turn.game.battle_post
        self.assertIsNotNone(post["id"])
        kind, _, sent = next(row for row in turn.channel.requests if row[1] == post["id"])
        self.assertEqual("send", kind)
        self.assertEqual("tnp-battle.png", sent["file"].filename)
        view = sent["view"]
        # Both placings had one place to go, so were made for the seats
        # and reported (the author, 2026-11-06, on PR #713); the first
        # question is Blue's retreat.
        self.assertIsInstance(view, RetreatView)
        self.assertIn("the only place they could go", sent["content"])
        # Whoever is asked is pinged on it, and nobody else.
        asked = view.prompt.asked_seat
        self.assertIn(f"<@{turn.who[asked].id}>", sent["content"])
        self.assertEqual([turn.who[asked].id], [one.id for one in sent["allowed_mentions"].users])
        self.assertIn("**Battle at area 14**, round 1 of 6", sent["content"])
        # Every control is built from the prompt's options, and persistent.
        self.assertTrue(all(item.custom_id.startswith(f"tnp:battle:{turn.game.game_id}:")
                            for item in view.children))
        self.assertIsNone(view.timeout)

    async def test_somebody_else_s_click_answers_nothing(self) -> None:
        turn = self.turn
        await open_battle(turn)
        view = current_view(turn)
        other = "blue" if view.prompt.asked_seat == "green" else "green"
        before = turn.match().to_dict()
        call = await click(turn, view, find_button(view, "Fight on"), who=turn.who[other])
        self.assertIn("battle question is", call.text())
        self.assertEqual(before, turn.match().to_dict())

    async def test_a_battle_round_by_round_and_the_requests_each_spends(self) -> None:
        """Every die rolls a 2 -- a miss at any modifier these forces
        roll at -- so nobody loses a unit, and the defender holds for six
        rounds (TNP 6.10). Each round is one send on the channel: its
        record. Every placing and every roll here has one answer, made
        for its seat, so each round asks Blue's retreat alone and the
        question never passes to the other player."""
        turn = self.turn
        await open_battle(turn)
        mark = len(turn.channel.requests)
        spent: dict[int, int] = {}
        first_asked: dict[int, PromptKind] = {}
        call = None
        with dice(turn, 2):
            for _ in range(200):
                match = turn.match()
                if match.battle is None:
                    break
                round_now = match.battle.round
                view = current_view(turn, call)
                first_asked.setdefault(round_now, view.prompt.kind)
                before = len(turn.channel.requests)
                call = await answer_first(turn, view)
                self.assertFalse(
                    any("Not done" in str(kwargs.get("content") or (args[0] if args else ""))
                        for _, args, kwargs in call.answers),
                    call.answers,
                )
                spent[round_now] = spent.get(round_now, 0) + len(turn.channel.requests) - before
        self.assertIsNone(turn.match().battle, "the battle did not end")
        self.assertEqual(list(range(1, 7)), sorted(spent))
        # Rounds 1 to 5: one request each, the round's record. Round 6 also
        # ends the battle and March goes on: its record with the outcome,
        # March's end and Production, and the table.
        for one in range(1, 6):
            self.assertEqual(1, spent[one], f"round {one}")
        self.assertLessEqual(spent[6], BUCKET)
        for one in range(1, 7):
            self.assertEqual(PromptKind.DECLARE_RETREAT, first_asked[one], f"round {one}")
        rounds = [kwargs for kind, _, kwargs in turn.channel.requests[mark:]
                  if kind == "send" and kwargs.get("files")
                  and kwargs["files"][0].filename.startswith("tnp-battle-round-")]
        self.assertEqual(6, len(rounds))
        said = turn.public(mark)
        # Every roll is shown: the dice, what each needed and why.
        fired = [line for line in said.splitlines() if " fire at " in line]
        self.assertTrue(fired)
        for line in fired:
            self.assertIn("rolled 2", line)
            self.assertIn("Fair against infantry, 6+", line)
            self.assertIn("each die hits on", line)
        self.assertIn("holds for 6 rounds", said)
        # March went on from where it stopped.
        self.assertIn("March is over", said)
        self.assertIsNone(turn.game.battle_post)
        # The battle message's last edit shows it over, with no controls.
        final = next(kwargs for kind, _, kwargs in reversed(call.answers) if kind == "original.edit")
        self.assertIsNone(final["view"])
        self.assertIn("**Battle at area 14**, over", final["content"])

    async def test_a_question_passed_to_the_other_player_pings_them(self) -> None:
        """Two kinds of unit a side, so placing and the targets go back
        and forth (the author, 2026-11-06, on PR #713: "ping each
        time"): every hand-over inside a round is one message pinging
        the person now asked, and nobody else; no click spends more than
        three requests on the channel."""
        turn = self.turn
        match = turn.match()
        match.areas["14"].controller = "green"
        match.pile("14", "green").add({"mercenary": 2, "worker": 1})
        match.seat("green").available["mercenary"] -= 2
        match.seat("green").available["worker"] -= 1
        turn.cog.service.persist(turn.game, match)
        view, _ = await turn.my_board("blue")
        view, _ = await turn.deploy(view, "A", {"mercenary": 3, "worker": 2}, target="14")
        await turn.lock(view)
        view, _ = await turn.my_board("green")
        await turn.lock(view)
        call, handovers, pings, most = None, 0, [], 0
        with dice(turn, 2):
            for _ in range(200):
                if turn.match().battle is None:
                    break
                view = current_view(turn, call)
                asked = view.prompt.asked_seat
                before = len(turn.channel.requests)
                call = await answer_first(turn, view)
                spent = turn.channel.requests[before:]
                most = max(most, len(spent))
                now = turn.match()
                recorded = any(kwargs.get("files") for kind, _, kwargs in spent if kind == "send")
                if now.battle is not None and now.battle.outcome is None and not recorded:
                    if current_view(turn, call).prompt.asked_seat != asked:
                        handovers += 1
                pings += [
                    kwargs for kind, _, kwargs in spent
                    if kind == "send" and not kwargs.get("files")
                    and "Answer on the battle message" in str(kwargs.get("content"))
                ]
        self.assertIsNone(turn.match().battle)
        self.assertGreater(handovers, 5)
        self.assertEqual(handovers, len(pings))
        for ping in pings:
            (pinged,) = ping["allowed_mentions"].users
            self.assertTrue(ping["content"].startswith(f"<@{pinged.id}>"))
        self.assertLessEqual(most, 3)

    async def test_the_table_is_left_alone_while_only_the_battle_moves(self) -> None:
        turn = self.turn
        await open_battle(turn)
        table = turn.game.table_message_id
        mark = len(turn.channel.requests)
        with dice(turn, 2):
            view = current_view(turn)
            await answer_first(turn, view)
        self.assertFalse([row for row in turn.channel.requests[mark:] if row[1] == table])

    async def test_a_seat_s_panel_points_at_the_battle_message(self) -> None:
        turn = self.turn
        await open_battle(turn)
        seat = current_view(turn).prompt.asked_seat
        _, call = await turn.my_board(seat)
        self.assertIn("battle message", call.answers[-1][1][0])
        self.assertIn(str(battle_message(turn)), call.answers[-1][1][0])


    async def test_resume_puts_the_battle_back_up_on_a_message_of_its_own(self) -> None:
        turn = self.turn
        await open_battle(turn)
        with dice(turn, 2):
            await answer_first(turn, current_view(turn))
        old = battle_message(turn)
        lines = list(turn.game.battle_post["lines"])
        call = turn.interaction(turn.blue)
        await turn.cog.resume.callback(turn.cog, call)
        new = battle_message(turn)
        self.assertNotEqual(old, new)
        kind, _, sent = next(row for row in turn.channel.requests if row[1] == new)
        self.assertEqual("send", kind)
        self.assertIsInstance(sent["view"], BattleView)
        # What the round had said is on the new message too.
        self.assertEqual(lines, turn.game.battle_post["lines"])
        self.assertTrue(lines)
        self.assertIn(lines[0], sent["content"])


class TnpBattleRestartTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_restart_re_arms_the_battle_s_controls(self) -> None:
        turn = Turn()
        try:
            await turn.load()
            await turn.started()
            await open_battle(turn)
            with dice(turn, 2):
                await answer_first(turn, current_view(turn))
            lines = list(turn.game.battle_post["lines"])
            self.assertTrue(lines)
            saved = {game_id: TnpGame.from_dict(game.to_dict()) for game_id, game in turn.cog.games.items()}
            bot = mock.MagicMock()
            bot.get_channel.side_effect = turn.bot.get_channel.side_effect
            again = Tnp(bot)
            with mock.patch.object(tnp_core, "load_games", return_value=saved):
                await again.cog_load()
            armed = {kwargs.get("message_id"): view for (view,), kwargs in
                     (call[0:2] for call in bot.add_view.call_args_list)}
            view = armed[turn.game.battle_post["id"]]
            self.assertIsInstance(view, BattleView)
            self.assertTrue(view.restored)
            # What the round had said is kept on the record.
            (game,) = again.games.values()
            self.assertEqual(lines, game.battle_post["lines"])
            again.boards.shutdown()
        finally:
            turn.close()


if __name__ == "__main__":
    unittest.main()
