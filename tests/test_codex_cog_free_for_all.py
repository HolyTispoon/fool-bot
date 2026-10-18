"""
The free-for-all on Discord (docs/codex-multiplayer.md, step 4), with the
cog's Discord faked: the lobby's variant row, three people reaching the
opening position, the channel's name, the turn message of a table -- no
Concede, **Swap view** between stacked and side by side, the undos asking
the right seat -- and the end of the game, **Rematch** with the same
seats and every seat's heroes cleared; and the free-for-all's two
additions on the panel (Rulebook p. 14): **Repair base** on the board's
row, and each opponent's open slots as destinations in the patrol view,
which **Lock patrol** answers with `lent` beside the assignment -- a
duel's panel with no repair, a dragon's patrol view with no loan.

The requests each click spends are counted as the duel's are
(`tests/test_codex_cog_turn.py`); the board itself is `test_codex_render`'s
and `scripts/render_codex_sample.py`'s to look at.
"""

from __future__ import annotations

import unittest
from unittest import mock

import discord

from codex import history
from codex.components import PATROL_SLOTS
from codex.game import GameStatus
from codex.prompts import pending
from codex.seats import seat_numbers
from codex_cog_fakes import GAME_CHANNEL, Table, find_button, find_select, labels, user
from codex_cog_fakes import end_main_and_lock as end_turn
from codex_positions import put
from cogs.codex_views import (
    NOT_YOUR_TABLE,
    LobbyView,
    PatrolView,
    RematchView,
    TurnMessageView,
    TurnPanelView,
    UndoConfirmView,
    UndoView,
)
from cogs.codex_views.patrol import EMPTY
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

    async def test_a_test_games_lobby_says_one_person_takes_every_seat(self) -> None:
        call = self.table.interaction(self.table.basher, self.table.lobby_channel)
        await self.table.cog.lobby.callback(self.table.cog, call, test_game=True)
        (game,) = self.table.cog.games.values()
        await self.table.choose_mode(game, "basic")
        call = await self.click(game, "variant_free_for_all", self.table.basher)
        text = call.last()[2]["content"]
        self.assertIn("A **test game**: one person may take every seat and play them all.", text)
        self.assertNotIn("both", text)


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

    async def test_no_menu_has_concede(self) -> None:
        view = TurnMessageView(self.table.cog, self.game.game_id)
        self.assertNotIn("Concede", labels(view))
        for seat in seat_numbers(self.table.match):
            menu = (await self.table.turn_button("hand", self.table.seated(seat))).view()
            self.assertNotIn("Concede", labels(menu))

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

    async def test_a_watcher_is_told_the_table_is_its_players(self) -> None:
        call = await self.table.turn_button("hand", user(999, "watcher"))
        self.assertEqual(call.last()[1][0], NOT_YOUR_TABLE)
        self.assertNotIn("two", NOT_YOUR_TABLE)

    async def test_an_attack_with_nothing_to_attack_at_a_table_is_a_greyed_button(self) -> None:
        """With no defender to label, the defender panel asks nobody for
        "the one opponent", which a table of several refuses: it shows
        **Nothing can be attacked** greyed and **Cancel the attack** (the
        review of 2026-10-15)."""
        from codex.prompts import DefenderOptions, PendingPrompt, PromptKind

        match = self.table.match
        prompt = PendingPrompt(PromptKind.CHOOSE_DEFENDER, "Choose a defender.", match.active,
                               DefenderOptions(attacker="unit:1", defenders=()))
        view = TurnPanelView(self.table.cog, self.game.game_id, prompt, match)
        self.assertEqual(labels(view), ["Nothing can be attacked", "Cancel the attack"])
        self.assertTrue(find_button(view, "Nothing can be attacked").disabled)

    async def test_a_watchers_concede_is_refused_in_the_models_words(self) -> None:
        concede = self.table.cog.concede_command.callback
        call = self.table.interaction(user(999, "watcher"))
        await concede(self.table.cog, call)
        self.assertEqual(call.last()[1][0], "Only a player of the game can concede it.")

    async def test_a_target_is_named_by_its_seat(self) -> None:
        """"Their" says nothing at a table of three: another seat's thing
        carries its player's name, and your own stays "Your"."""
        from codex.engine import TargetRow
        from codex.prompts import PendingPrompt, PromptKind, TargetOptions

        match = self.table.match
        seat = match.active
        others = [one for one in (1, 2, 3) if one != seat]
        rows = tuple(TargetRow(f"{one}:base", one, "base") for one in (seat, *others))
        options = TargetOptions(seat, "brick_thief", "unit:1", 1, "repair", rows)
        view = TurnPanelView(self.table.cog, self.game.game_id,
                             PendingPrompt(PromptKind.TARGET, "", seat, options), match)
        styles = {item.label: item.style for item in view.children if getattr(item, "choice", None)}
        self.assertEqual(styles, {
            "Your Base (20 HP)": discord.ButtonStyle.primary,
            **{f"{self.game.seat_name(one)}'s Base (20 HP)": discord.ButtonStyle.danger for one in others},
        })

    async def test_the_hand_is_the_clickers_seat(self) -> None:
        active = self.table.match.active
        other = next(seat for seat in (1, 2, 3) if seat != active)
        panel = await self.table.turn_button("hand", self.table.seated(active))
        self.assertEqual(panel.view().seat, active)
        hand = await self.table.turn_button("hand", self.table.seated(other))
        self.assertEqual([item.label for item in hand.view().children], ["My deck", "Codex", "Show board"])

    async def test_the_undo_to_the_previous_turn_asks_the_seat_before(self) -> None:
        first = self.table.match.active
        await end_turn(self.table, self.table.seated(first))
        second = self.table.match.active
        self.assertNotEqual(first, second)
        self.assertEqual(self.table.cog.service.previous_turn_owners(self.game.game_id), (first,))
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


#: An action's answers on the click's own webhook: the defer while the
#: turn message is brought up to date, then the panel edited in place.
PANEL_EDITED = ["response.defer", "original.edit"]


def channel_requests(table: Table, mark: int) -> list[tuple[str, int]]:
    """What the channel's bucket was asked for since `mark`, by kind and
    message."""
    return [(kind, message_id) for kind, message_id, _ in table.game_channel.since(mark)]


class RepairTests(unittest.IsolatedAsyncioTestCase):
    """**Repair base** on a free-for-all's panel (Rulebook p. 14): on the
    board's row, green where the engine allows it and greyed with why
    not where it does not, answering `MAIN_ACTION` with "repair"; a
    duel's panel has none, since `MainActionOptions.repair` is `None`
    there."""

    async def asyncSetUp(self) -> None:
        self.table = Table()
        self.addCleanup(self.table.close)
        self.game = await self.table.started_free_for_all()

    def stage(self, base: int, gold: int) -> int:
        """The active seat's base at `base` HP and its gold at `gold`;
        the seat."""
        match = self.table.match
        match.set_base(match.active, base)
        match.active_player.gold = gold
        self.table.cog.service.persist(self.game, match)
        return match.active

    async def test_the_repair_is_a_green_button_on_the_boards_row(self) -> None:
        self.stage(15, 7)
        _, view = await self.table.panel()
        button = find_button(view, ("repair",))
        self.assertEqual(button.label, "Repair base (3 gold)")
        self.assertIs(button.style, discord.ButtonStyle.success)
        self.assertFalse(button.disabled)
        # After the actions row and the hand, on the board's row with
        # what may be built, before the five that always end the panel.
        self.assertGreater(button.row, 0)
        self.assertLessEqual(button.row, find_button(view, "My deck").row)
        self.assertIn("Repair base (3 gold)", labels(view))

    async def test_a_repair_costs_what_an_action_does(self) -> None:
        """The turn message edited through the gate -- one of the
        channel's -- and, on the click's own webhook, the defer and the
        panel edited in place: a main-phase action's count
        (docs/design/codex.md, "The requests per click")."""
        seat = self.stage(15, 7)
        _, view = await self.table.panel()
        old = self.game.turn_message_id
        mark = len(self.table.game_channel.requests)
        call = await self.table.press(view, ("repair",))
        self.assertEqual([kind for kind, _, _ in call.answers], PANEL_EDITED)
        self.assertEqual(channel_requests(self.table, mark), [("edit", old)])
        match = self.table.match
        self.assertEqual((match.base_of(seat), match.player(seat).gold), (16, 4))
        self.assertEqual(match.journal[-1]["action"]["choice"], "repair")
        self.assertIn("repairs the base for (3): 16 HP. (4) left.", self.table.game_channel.texts[old])
        # The panel edited in place offers it again, 4 gold being enough;
        # after the second, 1 gold is not, and the button says so.
        self.assertFalse(find_button(call.view(), ("repair",)).disabled)
        again = await self.table.press(call.view(), ("repair",))
        self.assertEqual(self.table.match.player(seat).gold, 1)
        self.assertEqual(find_button(again.view(), ("repair",)).label,
                         "Repair base (3 gold): not enough gold")

    async def test_a_refused_repair_is_greyed_with_why_not(self) -> None:
        _, view = await self.table.panel()
        button = find_button(view, ("repair",))
        self.assertTrue(button.disabled)
        self.assertIs(button.style, discord.ButtonStyle.secondary)
        self.assertEqual(button.label, "Repair base (3 gold): the base is undamaged")
        self.stage(15, 2)
        _, view = await self.table.panel()
        self.assertEqual(find_button(view, ("repair",)).label,
                         "Repair base (3 gold): not enough gold")

    async def test_a_duels_panel_has_no_repair(self) -> None:
        duel = Table()
        self.addCleanup(duel.close)
        await duel.started()
        match = duel.match
        match.set_base(match.active, 15)
        match.active_player.gold = 9
        duel.cog.service.persist(duel.game, match)
        _, view = await duel.panel()
        self.assertIsNone(view.prompt.options.repair)
        self.assertNotIn(("repair",), [getattr(item, "choice", None) for item in view.children])
        self.assertEqual([label for label in labels(view) if label.startswith("Repair")], [])


class LendingTests(unittest.IsolatedAsyncioTestCase):
    """Lending from the patrol view (Rulebook p. 14; docs/design/codex.md,
    "Lending is a control change"): each opponent's open slots follow the
    owner's five in the slot menu, the patroller chosen for one is lent,
    and **Lock patrol** answers with `lent` beside the assignment -- with
    the assignment alone where nothing is lent, as a duel's lock does."""

    async def asyncSetUp(self) -> None:
        self.table = Table()
        self.addCleanup(self.table.close)
        self.game = await self.table.started_free_for_all()
        match = self.table.match
        self.seat = match.active
        self.borrower, self.other = [seat for seat in (1, 2, 3) if seat != self.seat]
        self.card = put(match, self.seat, "tenderfoot")
        # The other opponent's squad leader: that slot is not open.
        put(match, self.other, "older_brother", patrol="squad_leader")
        self.table.cog.service.persist(self.game, match)
        self.name = self.game.seat_name(self.borrower)

    async def patrol(self) -> PatrolView:
        """End the main phase from a fresh panel: the patrol view."""
        _, view = await self.table.panel()
        view = (await self.table.press(view, "End main phase")).view()
        self.assertIsInstance(view, PatrolView)
        return view

    def key(self, slot: str, seat: int | None = None) -> str:
        return slot if seat is None else f"{seat}:{slot}"

    async def test_each_opponents_open_slots_follow_the_owners_in_the_slot_menu(self) -> None:
        view = await self.patrol()
        menu = find_select(view, "Choose a slot")
        values = [option.value for option in menu.options]
        self.assertEqual(values[:5], list(PATROL_SLOTS))
        self.assertEqual(values[5:10], [self.key(slot, self.borrower) for slot in PATROL_SLOTS])
        self.assertEqual(values[10:], [self.key(slot, self.other) for slot in PATROL_SLOTS
                                       if slot != "squad_leader"])
        by_value = {option.value: option.label for option in menu.options}
        self.assertEqual(by_value["elite"], "Elite: empty")
        self.assertEqual(by_value[self.key("elite", self.borrower)], f"{self.name}'s elite: empty")
        self.assertEqual(find_select(view, "Who patrols").placeholder, "Who patrols as squad leader?")

    async def test_a_destination_and_its_patroller_cost_one_edit_each_and_nothing_public(self) -> None:
        view = await self.patrol()
        mark = len(self.table.game_channel.requests)
        chosen = await self.table.choose(view, "Choose a slot", self.key("elite", self.borrower))
        self.assertEqual([kind for kind, _, _ in chosen.answers], ["response.edit"])
        view = chosen.view()
        menu = find_select(view, "Who is lent to")
        self.assertEqual(menu.placeholder, f"Who is lent to {self.name} as elite?")
        self.assertIn(self.card.ref, [option.value for option in menu.options])
        lent = await self.table.choose(view, "Who is lent to", self.card.ref)
        self.assertEqual([kind for kind, _, _ in lent.answers], ["response.edit"])
        self.assertEqual(channel_requests(self.table, mark), [])
        view = lent.view()
        self.assertEqual(view.assignment, {self.key("elite", self.borrower): self.card.ref})
        self.assertIn(f"**Lent to {self.name} as elite**: Tenderfoot", lent.text())
        # The menu moved on to the owner's first empty slot, which no
        # longer offers the card: it patrols one slot at most.
        own = find_select(view, "Who patrols as squad leader")
        self.assertNotIn(self.card.ref, [option.value for option in own.options])
        # Nothing is applied before the lock: the card is still its owner's.
        self.assertEqual(self.table.match.instance(self.card.id).controller, self.seat)

    async def test_the_lock_lends_and_costs_what_the_duels_lock_does(self) -> None:
        """The answer carries `lent` beside the assignment; the lock is
        the turn's end -- the old message's last edit, its pin, the new
        one's post -- and the defer and the panel edited into the tech
        picker, as a duel's."""
        view = await self.patrol()
        view = (await self.table.choose(view, "Choose a slot", self.key("elite", self.borrower))).view()
        view = (await self.table.choose(view, "Who is lent to", self.card.ref)).view()
        old = self.game.turn_message_id
        mark = len(self.table.game_channel.requests)
        service = self.table.cog.service
        with mock.patch.object(service, "apply_action", wraps=service.apply_action) as applied:
            lock = await self.table.press(view, "Lock patrol")
        action = applied.call_args[0][1]
        self.assertEqual(action.arguments, {
            "assignment": {}, "lent": {str(self.borrower): {"elite": self.card.ref}},
        })
        self.assertEqual([kind for kind, _, _ in lock.answers], PANEL_EDITED)
        self.assertEqual([kind for kind, _ in channel_requests(self.table, mark)],
                         ["edit", "pin", "send"])
        match = self.table.match
        card = match.instance(self.card.id)
        self.assertEqual((card.controller, card.owner, card.lent, card.patrol_slot),
                         (self.borrower, self.seat, True, "elite"))
        self.assertIn(card, match.player(self.borrower).play)
        self.assertEqual(match.patrollers(self.borrower), {"elite": card.ref})
        self.assertEqual(match.patrollers(self.seat), {})
        self.assertIn(f"lends **Tenderfoot** to {self.name} as elite.",
                      self.table.game_channel.texts[old])

    async def test_a_lock_that_lends_nothing_answers_as_a_duels_does(self) -> None:
        view = await self.patrol()
        view = (await self.table.choose(view, "Who patrols", self.card.ref)).view()
        service = self.table.cog.service
        with mock.patch.object(service, "apply_action", wraps=service.apply_action) as applied:
            await self.table.press(view, "Lock patrol")
        self.assertEqual(applied.call_args[0][1].arguments,
                         {"assignment": {"squad_leader": self.card.ref}})
        self.assertEqual(self.table.match.instance(self.card.id).controller, self.seat)

    async def test_a_loan_is_kept_through_undo_and_taken_back_by_nobody_or_clear(self) -> None:
        view = await self.patrol()
        view = (await self.table.choose(view, "Choose a slot", self.key("lookout", self.borrower))).view()
        view = (await self.table.choose(view, "Who is lent to", self.card.ref)).view()
        undo = (await self.table.press(view, "Undo...")).view()
        self.assertIsInstance(undo, TurnPanelView)
        back = (await self.table.press(undo, "Back")).view()
        self.assertIsInstance(back, PatrolView)
        self.assertEqual(back.assignment, {self.key("lookout", self.borrower): self.card.ref})
        view = (await self.table.choose(back, "Choose a slot", self.key("lookout", self.borrower))).view()
        self.assertTrue(next(option.default for option in find_select(view, "Who is lent to").options
                             if option.value == self.card.ref))
        view = (await self.table.choose(view, "Who is lent to", EMPTY)).view()
        self.assertEqual(view.assignment, {})
        view = (await self.table.choose(view, "Who is lent to", self.card.ref)).view()
        view = (await self.table.press(view, "Clear")).view()
        self.assertEqual(view.assignment, {})


class DragonPatrolTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_dragons_patrol_view_offers_no_loan(self) -> None:
        """A two-headed dragon lends nothing (Rulebook p. 13 has no such
        rule): the options carry no zones, so the slot menu is the
        owner's five alone, as a duel's."""
        table = Table()
        self.addCleanup(table.close)
        game = await table.started_dragon()
        match = table.match
        put(match, match.active, "tenderfoot")
        table.cog.service.persist(game, match)
        _, view = await table.panel()
        view = (await table.press(view, "End main phase")).view()
        self.assertIsInstance(view, PatrolView)
        self.assertEqual(view.prompt.options.zones, ())
        menu = find_select(view, "Choose a slot")
        self.assertEqual([option.value for option in menu.options], list(PATROL_SLOTS))
        self.assertFalse([label for label in (option.label for option in menu.options) if "'s " in label])
        self.assertEqual(find_select(view, "Who patrols").placeholder, "Who patrols as squad leader?")


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
