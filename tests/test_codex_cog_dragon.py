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
from codex.prompts import Action, PromptKind
from codex_cog_fakes import Table, user
from codex_positions import put
from cogs.codex_views import (
    END_OF_TURN, OTHER_TEAM_STARTED, LobbyView, PatrolView, TeamConcedeView, TechChoiceView,
    TurnMessageView, TurnPanelView, UndoConfirmView, WaitingView,
)


async def end_team_turn(table: Table, team) -> None:
    """Both teammates end their main phase and lock nothing: the team's
    turn ends."""
    for seat in team:
        call = await table.turn_button("hand", table.seated(seat))
        view = (await table.press(call.view(), "End main phase", who=table.seated(seat))).view()
        await table.press(view, "Lock patrol", who=table.seated(seat))


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


    async def test_four_people_reach_the_opening_position(self) -> None:
        game = await self.table.started_dragon()
        self.assertIs(game.status, GameStatus.PLAYING)
        match = self.table.match
        self.assertEqual((match.variant, match.dragons), ("two_headed_dragon", [[1, 2], [3, 4]]))
        renamed = next(kw for kind, _, kw in reversed(self.table.game_channel.requests)
                       if kind == "channel.edit")["name"]
        self.assertEqual(renamed, "codex-1-basher-fencer-vs-dee-eli")
        self.assertEqual(game.board_layout, "stacked")
        self.assertIsNotNone(game.turn_message_id)

    async def test_a_test_game_seats_one_person_on_all_four(self) -> None:
        game = await self.table.started_dragon(test_game=True)
        self.assertIs(game.status, GameStatus.PLAYING)
        self.assertEqual(game.seats_of(self.table.basher.id), (1, 2, 3, 4))
        renamed = next(kw for kind, _, kw in reversed(self.table.game_channel.requests)
                       if kind == "channel.edit")["name"]
        self.assertEqual(renamed, "codex-1-basher-basher-vs-basher-basher")



class TurnTests(unittest.IsolatedAsyncioTestCase):
    """Two teammates acting in one main phase, each from a panel of
    their own (decision 13)."""

    async def asyncSetUp(self) -> None:
        self.table = Table()
        self.addCleanup(self.table.close)
        self.game = await self.table.started_dragon()
        team = self.table.cog.engine.turn_seats(self.table.match)
        self.first, self.second = team
        self.foes = self.table.cog.engine.opponents(self.table.match, self.first)

    def who(self, seat):
        return self.table.seated(seat)

    async def panel(self, seat):
        call = await self.table.turn_button("hand", self.who(seat))
        return call, call.view()

    async def test_the_turn_message_names_and_pings_both_teammates(self) -> None:
        kind, _, kwargs = next(row for row in reversed(self.table.game_channel.requests)
                               if row[0] == "send")
        pinged = {user.id for user in kwargs["allowed_mentions"].users}
        self.assertEqual(pinged, {self.who(self.first).id, self.who(self.second).id})
        heading = kwargs["content"].split("\n")[0]
        for seat in (self.first, self.second):
            self.assertIn(f"<@{self.who(seat).id}>", heading)
        self.assertIn("Concede", labels(TurnMessageView(self.table.cog, self.game.game_id)))

    async def test_each_teammate_gets_their_own_panel_and_sees_the_others_hand(self) -> None:
        for seat, mate in ((self.first, self.second), (self.second, self.first)):
            call, view = await self.panel(seat)
            self.assertIsInstance(view, TurnPanelView)
            self.assertEqual(view.seat, seat)
            self.assertIs(view.prompt.kind, PromptKind.MAIN_ACTION)
            kwargs = call.last()[2]
            # Their own hand, and the teammate's under it, named.
            self.assertEqual(len(kwargs["files"]), 2)
            count = len(self.table.match.player(mate).hand)
            self.assertIn(f"{self.game.seat_name(mate)}'s hand: {count} cards.", call.text())
            self.assertNotIn("Their hand", call.text())

    async def test_the_other_team_sees_its_hand_and_its_teammates(self) -> None:
        foe, mate = self.foes
        call = await self.table.turn_button("hand", self.who(foe))
        self.assertEqual(labels(call.view()), ["My deck", "Codex"])
        _, args, kwargs = call.last()
        self.assertEqual(len(kwargs["files"]), 2)
        self.assertIn(f"{self.game.seat_name(mate)}'s hand:", args[0])
        hand = self.table.interaction(self.who(foe))
        await self.table.cog.hand.callback(self.table.cog, hand)
        self.assertIn(f"{self.game.seat_name(mate)}'s hand:", hand.last()[1][0])

    async def test_an_action_names_its_seat_and_edits_the_message_and_its_own_panel(self) -> None:
        _, view = await self.panel(self.second)
        playable = [row.slug for row in view.prompt.options.playable if row.allowed]
        gold = {seat: self.table.match.player(seat).gold for seat in (self.first, self.second)}
        mark = len(self.table.game_channel.requests)
        call = await self.table.press(view, ("play", playable[0]), who=self.who(self.second))
        # The second seat paid, not the team's head.
        self.assertLess(self.table.match.player(self.second).gold, gold[self.second])
        self.assertEqual(self.table.match.player(self.first).gold, gold[self.first])
        # The second seat's action, journalled with its seat.
        self.assertEqual(self.table.match.journal[-1]["action"]["arguments"]["player"], self.second)
        # The turn message through the gate; the clicker's own panel edited.
        self.assertEqual([kind for kind, _, _ in self.table.game_channel.since(mark)], ["edit"])
        self.assertEqual([kind for kind, _, _ in call.answers], ["response.defer", "original.edit"])
        self.assertEqual(call.view().seat, self.second)

    async def test_a_stale_click_puts_the_panel_up_as_it_stands(self) -> None:
        _, old = await self.panel(self.second)
        moved = await self.table.press(old, "End main phase", who=self.who(self.second))
        self.assertIsInstance(moved.view(), PatrolView)
        playable = [row.slug for row in old.prompt.options.playable if row.allowed]
        call = await self.table.press(old, ("play", playable[0]), who=self.who(self.second))
        kind, _, kwargs = call.last()
        self.assertIn(kind, ("response.edit", "original.edit"))
        self.assertIsInstance(kwargs["view"], PatrolView)

    async def test_a_teammates_click_waits_on_the_attack_under_way(self) -> None:
        service, game = self.table.cog.service, self.game
        match = service.load(game)
        put(match, self.first, "older_brother")
        service.persist(game, match)
        _, other = await self.panel(self.second)
        _, view = await self.panel(self.first)
        view = (await self.table.press(view, "Attack...", who=self.who(self.first))).view()
        attacker = next(item.choice for item in view.children if getattr(item, "choice", None)
                        and item.choice[0] == "attack")
        asked = (await self.table.press(view, attacker, who=self.who(self.first))).view()
        self.assertIs(asked.prompt.kind, PromptKind.CHOOSE_DEFENDER)
        playable = [row.slug for row in other.prompt.options.playable if row.allowed]
        call = await self.table.press(other, ("play", playable[0]), who=self.who(self.second))
        kind, _, kwargs = call.last()
        self.assertIn(kind, ("response.edit", "original.edit"))
        self.assertIsInstance(kwargs["view"], WaitingView)
        self.assertIn(f"Waiting on {self.game.seat_name(self.first)}'s attack.", kwargs["content"])
        # Back to my turn, once the attack is over, asks again.
        await self.table.press(asked, "Cancel", who=self.who(self.first))
        back = await self.table.press(kwargs["view"], "Back to my turn", who=self.who(self.second))
        self.assertIs(back.view().prompt.kind, PromptKind.MAIN_ACTION)

    async def test_the_first_lock_waits_and_the_second_ends_the_turn(self) -> None:
        call, view = await self.panel(self.first)
        view = (await self.table.press(view, "End main phase", who=self.who(self.first))).view()
        locked = await self.table.press(view, "Lock patrol", who=self.who(self.first))
        self.assertIsInstance(locked.view(), WaitingView)
        self.assertIn("Your patrol is locked", locked.text())
        turn = self.table.match.turn
        _, view = await self.panel(self.second)
        view = (await self.table.press(view, "End main phase", who=self.who(self.second))).view()
        mark = len(self.table.game_channel.requests)
        ended = await self.table.press(view, "Lock patrol", who=self.who(self.second))
        self.assertEqual(self.table.match.turn, turn + 1)
        self.assertEqual([kind for kind, _, _ in self.table.game_channel.since(mark)],
                         ["edit", "pin", "send"])
        # The tech picker for the seat that locked last; both owe theirs.
        self.assertIsInstance(ended.view(), TechChoiceView)
        standing = {one.asked_player for one in self.table.cog.service.standing(
            self.game, self.table.match)}
        self.assertEqual(standing, {self.first, self.second})
        # The new turn pings the other team's two.
        _, _, kwargs = self.table.game_channel.since(mark)[-1]
        self.assertEqual({user.id for user in kwargs["allowed_mentions"].users},
                         {self.who(seat).id for seat in self.foes})

    async def test_tech_shows_the_teammates_standing_picks_read_only(self) -> None:
        await end_team_turn(self.table, (self.first, self.second))
        # The second seat saves its choice from Tech.
        call = await self.table.turn_button("tech", self.who(self.second))
        view = call.view()
        self.assertIsInstance(view, TechChoiceView)
        slugs = [slug for slug, left in view.prompt.options.codex if left][:2]
        saved = self.table.cog.service.apply_action(self.game.game_id, Action(
            PromptKind.TECH_CHOICE, "", {"player": self.second, "picks": slugs}))
        self.assertFalse(saved.refused, saved.refusal)
        call = await self.table.turn_button("tech", self.who(self.first))
        self.assertIsInstance(call.answers[0][2]["view"], TechChoiceView)
        kind, args, kwargs = call.last()
        self.assertEqual(kind, "followup.send")
        self.assertTrue(args[0].startswith(f"{self.game.seat_name(self.second)}'s tech: "))
        self.assertNotIn("view", kwargs)
        self.assertTrue(kwargs["ephemeral"])

    async def test_the_codex_browser_offers_the_teammates_codex(self) -> None:
        call = await self.table.turn_button("codex", self.who(self.first))
        browser = call.view()
        name = self.game.seat_name(self.second)
        values = [option.value for option in browser.select.options]
        self.assertIn(f"{self.second}:everything", values)
        call = await self.table.choose(browser, "Show", f"{self.second}:tech1", who=self.who(self.first))
        self.assertTrue(call.last()[2]["content"].startswith(f"{name}'s codex: "))
        self.assertEqual(browser.owner, self.second)


    async def test_either_teammate_takes_back_the_end_of_the_turn(self) -> None:
        await end_team_turn(self.table, (self.first, self.second))
        self.assertEqual(set(self.table.cog.service.end_of_turn_owners(self.game.game_id)),
                         {self.first, self.second})
        undo = (await self.table.turn_button("undo", self.who(self.second))).view()
        self.assertEqual(labels(undo), [END_OF_TURN])
        self.assertEqual(undo.seat, self.second)

    async def test_once_the_other_team_has_acted_the_refusal_names_the_team(self) -> None:
        await end_team_turn(self.table, (self.first, self.second))
        foe = self.foes[1]
        _, view = await self.panel(foe)
        playable = [row.slug for row in view.prompt.options.playable if row.allowed]
        await self.table.press(view, ("play", playable[0]), who=self.who(foe))
        refusal = await self.table.turn_button("undo", self.who(self.second))
        self.assertEqual(refusal.last()[1][0], OTHER_TEAM_STARTED)

    async def test_the_undo_to_the_previous_turn_asks_the_other_team(self) -> None:
        await end_team_turn(self.table, (self.first, self.second))
        asker, other = self.foes
        undo = (await self.table.turn_button("undo", self.who(other))).view()
        mark = len(self.table.game_channel.requests)
        await self.table.press(undo, "To the start of the previous turn", who=self.who(other))
        (_, _, kwargs), = self.table.game_channel.since(mark)
        confirm = kwargs["view"]
        self.assertIsInstance(confirm, UndoConfirmView)
        self.assertEqual(set(confirm.agreeing), {self.first, self.second})
        for seat in (self.first, self.second):
            self.assertIn(f"<@{self.who(seat).id}>", kwargs["content"])
        # The asker's teammate may not agree for the other team.
        call = self.table.interaction(self.who(asker))
        await confirm.agree(call)
        self.assertIn("The other team has to agree", call.last()[1][0])
        # Either player of the team whose turn it was may.
        turn = self.table.match.turn
        await confirm.agree(self.table.interaction(self.who(self.second)))
        self.assertEqual(self.table.match.turn, turn - 1)

    async def test_a_concession_needs_both_teammates(self) -> None:
        concede = self.table.cog.concede_command.callback
        call = self.table.interaction(self.who(self.first))
        await concede(self.table.cog, call)
        confirm = call.view()
        self.assertIn(self.game.seat_name(self.second), call.last()[1][0])
        mark = len(self.table.game_channel.requests)
        click = self.table.interaction(self.who(self.first))
        await confirm.confirm(click)
        self.assertIs(self.game.status, GameStatus.PLAYING)
        (kind, _, kwargs), = self.table.game_channel.since(mark)
        question = kwargs["view"]
        self.assertIsInstance(question, TeamConcedeView)
        self.assertIn(f"<@{self.who(self.second).id}>", kwargs["content"])
        # The asker cannot agree for their teammate; a stranger cannot
        # refuse.
        mine = self.table.interaction(self.who(self.first))
        await question.agree(mine)
        self.assertIn("teammate has to agree", mine.last()[1][0])
        stranger = self.table.interaction(user(999, "watcher"))
        await question.refuse_concession(stranger)
        self.assertIs(self.game.status, GameStatus.PLAYING)
        await question.agree(self.table.interaction(self.who(self.second)))
        self.assertIs(self.game.status, GameStatus.FINISHED)
        match = self.table.match
        self.assertEqual(set(self.table.cog.engine.dragon_of(match, match.winner)), set(self.foes))
        self.assertIsNotNone(self.game.final_message_id)

    async def test_a_teammate_may_refuse_the_concession(self) -> None:
        concede = self.table.cog.concede_command.callback
        call = self.table.interaction(self.who(self.second))
        await concede(self.table.cog, call)
        await call.view().confirm(self.table.interaction(self.who(self.second)))
        question = self.table.game_channel.requests[-1][2]["view"]
        refusal = self.table.interaction(self.who(self.first))
        await question.refuse_concession(refusal)
        self.assertIn("refused by", refusal.last()[2]["content"])
        self.assertIs(self.game.status, GameStatus.PLAYING)


class TestGameTests(unittest.IsolatedAsyncioTestCase):
    """One person on all four seats: the first unlocked teammate's
    panel, with **Switch to** the other's (decision 13)."""

    async def asyncSetUp(self) -> None:
        self.table = Table()
        self.addCleanup(self.table.close)
        self.game = await self.table.started_dragon(test_game=True)

    async def test_the_panel_switches_between_the_two_teammates(self) -> None:
        first, second = self.table.cog.engine.turn_seats(self.table.match)
        call = await self.table.turn_button("hand", self.table.basher)
        view = call.view()
        self.assertEqual(view.seat, first)
        switch = next(label for label in labels(view) if label.startswith("Switch to "))
        other = await self.table.press(view, switch, who=self.table.basher)
        self.assertEqual(other.last()[0], "response.send")
        self.assertEqual(other.view().seat, second)
        # The first locks: the panel goes on as the second's.
        view = (await self.table.press(view, "End main phase", who=self.table.basher)).view()
        locked = await self.table.press(view, "Lock patrol", who=self.table.basher)
        self.assertEqual(locked.view().seat, second)
        self.assertFalse(any(label.startswith("Switch to ") for label in labels(locked.view())))


if __name__ == "__main__":
    unittest.main()
